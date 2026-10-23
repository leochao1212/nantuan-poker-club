"""Member profiles, bounded local avatars and audited account access controls."""
import base64,binascii,hashlib,json,re,struct,unicodedata,zlib
from poker_engine import RuleError

AVATARS={'initial','spade','heart','diamond','club','crown','fox','cat'}

class AccountError(Exception):
    def __init__(self,message,status=400,reason='invalid_profile'):
        self.message,self.status,self.reason=message,status,reason

def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS member_profiles(user_id INTEGER PRIMARY KEY REFERENCES users(id),
      avatar_key TEXT NOT NULL DEFAULT 'initial',avatar_png BLOB,revision INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS account_states(user_id INTEGER PRIMARY KEY REFERENCES users(id),
      status TEXT NOT NULL CHECK(status IN ('active','blocked','deleted')),revision INTEGER NOT NULL,
      reason TEXT NOT NULL,changed_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS profile_operations(user_id INTEGER NOT NULL REFERENCES users(id),
      operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(user_id,operation_id));
    CREATE TABLE IF NOT EXISTS admin_account_events(id INTEGER PRIMARY KEY,
      actor_id INTEGER NOT NULL REFERENCES users(id),target_id INTEGER NOT NULL REFERENCES users(id),
      action TEXT NOT NULL,previous_status TEXT NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL,
      username_snapshot TEXT NOT NULL,nickname_snapshot TEXT NOT NULL,operation_id TEXT NOT NULL,
      created_at REAL NOT NULL,UNIQUE(actor_id,operation_id));
    ''')

def state(db,uid):
    row=db.execute('SELECT status,revision,reason,changed_at FROM account_states WHERE user_id=?',(uid,)).fetchone()
    return dict(row) if row else dict(status='active',revision=0,reason='',changed_at=None)

def require_active(db,uid):
    if state(db,uid)['status']!='active':raise AccountError('此帳號已停用，請聯絡管理員。',401,'account_disabled')

def public_profiles(db):
    import view_cache
    return view_cache.shared(db,'profiles',('member_profiles',),lambda: {r['user_id']:{'avatar_key':r['avatar_key'],'avatar_url':f"/api/profile/avatar/{r['user_id']}/{r['revision']}.png" if r['avatar_png'] else None,'profile_revision':r['revision']} for r in db.execute('SELECT user_id,avatar_key,revision,avatar_png IS NOT NULL AS avatar_png FROM member_profiles')})

def profile(db,uid):
    user=db.execute('SELECT id,username,nickname,created_at FROM users WHERE id=?',(uid,)).fetchone()
    if not user:raise AccountError('找不到帳號。',404,'not_found')
    return {**dict(user),**public_profiles(db).get(uid,{'avatar_key':'initial','avatar_url':None,'profile_revision':0})}

def operation_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',value):raise RuleError('操作編號無效。')
    return value

def _chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',binascii.crc32(kind+body)&0xffffffff)

def png_image(value):
    """Accept only small RGB/RGBA PNGs, strip metadata and bound inflation."""
    if not isinstance(value,str) or not value.startswith('data:image/png;base64,') or len(value)>100000:raise RuleError('請選擇照片，由頁面縮小後上傳。')
    try:raw=base64.b64decode(value.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error):raise RuleError('圖片資料無效。')
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise RuleError('圖片必須為 PNG。')
    pos=8;header=None;packed=bytearray();done=False
    while pos+12<=len(raw):
        size=struct.unpack('>I',raw[pos:pos+4])[0];kind=raw[pos+4:pos+8]
        if size>75000 or pos+size+12>len(raw):raise RuleError('圖片資料不完整。')
        data=raw[pos+8:pos+8+size];crc=raw[pos+8+size:pos+12+size]
        if struct.pack('>I',binascii.crc32(kind+data)&0xffffffff)!=crc:raise RuleError('圖片校驗失敗。')
        if header is None and kind!=b'IHDR':raise RuleError('圖片標頭無效。')
        if kind==b'IHDR':
            if header is not None or len(data)!=13:raise RuleError('圖片標頭無效。')
            width,height,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',data)
            if not (1<=width<=128 and 1<=height<=128 and depth==8 and color in (2,6) and compression==filtering==interlace==0):raise RuleError('圖片須縮小為 128 × 128 以內。')
            header=data;channels=3 if color==2 else 4;stride=width*channels+1;expected=stride*height
        elif kind==b'IDAT':packed.extend(data)
        elif kind==b'IEND':
            if data:raise RuleError('圖片結尾無效。')
            done=True;pos+=12;break
        elif not kind[0]&32:raise RuleError('圖片格式不支援。')
        pos+=size+12
    if not done or pos!=len(raw) or not packed:raise RuleError('圖片資料不完整。')
    try:
        decoder=zlib.decompressobj();pixels=decoder.decompress(bytes(packed),expected+1)
        if len(pixels)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or any(pixels[i]>4 for i in range(0,expected,stride)):raise ValueError()
    except (ValueError,zlib.error):raise RuleError('圖片像素資料無效。')
    return b'\x89PNG\r\n\x1a\n'+_chunk(b'IHDR',header)+_chunk(b'IDAT',zlib.compress(pixels))+_chunk(b'IEND',b'')

def update(db,user,data,clock):
    require_active(db,user['id'])
    uid=user['id'];op=operation_id(data.get('operation_id'))
    nickname=data.get('nickname');key=data.get('avatar_key','initial');revision=data.get('profile_revision')
    if not isinstance(nickname,str) or not 1<=len(nickname.strip())<=16 or any(unicodedata.category(c).startswith('C') for c in nickname):raise RuleError('暱稱請填寫 1–16 字，不能含控制字元。')
    if not isinstance(key,str) or key not in AVATARS|{'photo'}:raise RuleError('頭像款式無效。')
    if type(revision) is not int or revision<0:raise RuleError('個人資料版本無效。')
    image=data.get('avatar_data');fingerprint=hashlib.sha256(json.dumps({'nickname':nickname.strip(),'key':key,'revision':revision,'image':image},sort_keys=True).encode()).hexdigest()
    old=db.execute('SELECT fingerprint,result FROM profile_operations WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise AccountError('同一編號已用於其他修改。',409,'operation_conflict')
        return {**json.loads(old['result']),'replayed':True}
    current=db.execute('SELECT * FROM member_profiles WHERE user_id=?',(uid,)).fetchone()
    if revision!=(current['revision'] if current else 0):raise AccountError('資料已在其他分頁更新，請重新載入後再修改。',409,'stale_profile')
    if image is not None and key!='photo':raise RuleError('請選擇照片頭像後再上傳。')
    picture=png_image(image) if image is not None else current['avatar_png'] if current and key=='photo' else None
    if key=='photo' and picture is None:raise RuleError('請先選擇照片。')
    db.execute('INSERT INTO member_profiles VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET avatar_key=excluded.avatar_key,avatar_png=excluded.avatar_png,revision=excluded.revision',(uid,key,picture,revision+1))
    db.execute('UPDATE users SET nickname=? WHERE id=?',(nickname.strip(),uid))
    # Current seat names follow edits; settled records remain immutable.
    import online
    for row in db.execute("SELECT * FROM poker_rooms WHERE status!='closed'").fetchall():
        room=online.decode(row);seat=online.engine.seated(room,uid)
        if seat:
            seat['nickname']=nickname.strip()
            if room['status']=='playing':
                for player in room['hand']['players']:
                    if player['user_id']==uid:player['nickname']=nickname.strip()
            online.save(db,room,clock)
    result={'ok':True,'profile':profile(db,uid),'replayed':False}
    db.execute('INSERT INTO profile_operations VALUES(?,?,?,?)',(uid,op,fingerprint,json.dumps(result)))
    return result

def moderate(db,actor,data,clock):
    import club_admin,online
    club_admin.require(db,actor['id'])
    uid=data.get('user_id');action=data.get('action');reason=data.get('reason');op=operation_id(data.get('operation_id'))
    if type(uid) is not int or action not in ('block','unblock','delete'):raise RuleError('帳號管理動作無效。')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=200:raise RuleError('請填寫 1–200 字的處理原因。')
    reason=reason.strip();revision=data.get('state_revision')
    if type(revision) is not int or revision<0:raise RuleError('帳號狀態版本無效。')
    old=db.execute('SELECT * FROM admin_account_events WHERE actor_id=? AND operation_id=?',(actor['id'],op)).fetchone()
    if old:
        if (uid,action,reason)!=(old['target_id'],old['action'],old['reason']):raise AccountError('操作編號與原紀錄不符。',409,'operation_conflict')
        return {'ok':True,'event_id':old['id'],'replayed':True}
    target=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not target:raise AccountError('找不到帳號。',404,'not_found')
    if uid==actor['id'] or club_admin.identity(db,uid)['is_admin']:raise AccountError('管理員帳號受保護，不能在此封鎖或刪除。',403,'protected_admin')
    before=state(db,uid)
    if before['revision']!=revision:raise AccountError('帳號狀態已變更，請重新整理。',409,'stale_account')
    if before['status']=='deleted' or action=='unblock' and before['status']!='blocked' or action=='block' and before['status']!='active':raise AccountError('目前帳號狀態不允許此操作。',409,'invalid_account_state')
    if action=='delete' and data.get('confirm_username')!=target['username']:raise RuleError('請輸入完整帳號確認刪除。')
    status={'block':'blocked','unblock':'active','delete':'deleted'}[action]
    if status!='active':
        rid=online.current_room(db,uid)
        if rid:
            room=online.get_room(db,rid);online.rules(room).leave(room,uid,clock);online.save(db,room,clock)
        # Minimal fixture databases need not have authentication tables.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='auth_sessions'").fetchone():db.execute('DELETE FROM auth_sessions WHERE user_id=?',(uid,))
        db.execute('DELETE FROM poker_presence WHERE user_id=?',(uid,));db.execute('DELETE FROM voice_members WHERE user_id=?',(uid,))
        db.execute('DELETE FROM voice_signals WHERE sender_id=? OR target_id=?',(uid,uid))
    if action=='delete':
        anonymous=f'已刪除帳號 #{uid}'
        db.execute('UPDATE users SET nickname=? WHERE id=?',(anonymous,uid))
        db.execute("UPDATE member_profiles SET avatar_key='initial',avatar_png=NULL,revision=revision+1 WHERE user_id=?",(uid,))
    db.execute('INSERT INTO account_states VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET status=excluded.status,revision=excluded.revision,reason=excluded.reason,changed_at=excluded.changed_at',(uid,status,revision+1,reason,clock))
    event=db.execute('INSERT INTO admin_account_events(actor_id,target_id,action,previous_status,status,reason,username_snapshot,nickname_snapshot,operation_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(actor['id'],uid,action,before['status'],status,reason,target['username'],target['nickname'],op,clock))
    return {'ok':True,'event_id':event.lastrowid,'replayed':False}
