"""Authenticated room chat and seat-independent voice signaling. No audio storage."""
import json
import re
import os
import poker_engine as engine
import member_accounts
import rewards


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS room_chat(id INTEGER PRIMARY KEY,room_id INTEGER NOT NULL REFERENCES poker_rooms(id),
      user_id INTEGER NOT NULL REFERENCES users(id),message TEXT NOT NULL,nonce TEXT NOT NULL,created_at REAL NOT NULL,
      UNIQUE(user_id,nonce));
    CREATE INDEX IF NOT EXISTS room_chat_room ON room_chat(room_id,id);
    CREATE TABLE IF NOT EXISTS voice_members(room_id INTEGER NOT NULL,user_id INTEGER NOT NULL,session_id TEXT NOT NULL,
      last_seen REAL NOT NULL,muted INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(room_id,user_id));
    CREATE TABLE IF NOT EXISTS voice_signals(id INTEGER PRIMARY KEY,room_id INTEGER NOT NULL,sender_id INTEGER NOT NULL,
      sender_session TEXT NOT NULL,target_id INTEGER NOT NULL,target_session TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS voice_inbox ON voice_signals(room_id,target_id,id);
    """)


def cleanup(db,clock):
    import voice_transport
    # Live sockets keep their membership even when mobile background timers pause.
    live=set(voice_transport.HUB.sessions());removed=0
    for row in db.execute('SELECT room_id,user_id,session_id FROM voice_members WHERE last_seen<?',(clock-35,)).fetchall():
        if tuple(row) not in live:
            removed+=db.execute('DELETE FROM voice_members WHERE room_id=? AND user_id=? AND session_id=?',tuple(row)).rowcount
    db.execute('DELETE FROM voice_signals WHERE created_at<?',(clock-60,))
    return bool(removed)


def config():
    servers=[{'urls':'stun:stun.l.google.com:19302'}]
    raw=os.environ.get('POKER_TURN_SERVERS','')
    if raw:
        try:
            extra=json.loads(raw)
            if isinstance(extra,list):servers.extend(extra)
        except (ValueError,TypeError):pass
    return {'iceServers':servers,'relay_configured':len(servers)>1}


def view(db,rid,uid,clock,*,profiles=None,cosmetics=None):
    import view_cache
    messages=view_cache.shared(db,('chat',rid),('room_chat','users'),lambda: [dict(r) for r in db.execute('''SELECT c.id,c.user_id,u.nickname,c.message,c.created_at FROM room_chat c
      JOIN users u ON u.id=c.user_id WHERE c.room_id=? ORDER BY c.id DESC LIMIT 50''',(rid,))][::-1])
    import voice_transport
    live=set(voice_transport.HUB.sessions())
    members=[dict(r) for r in db.execute('''SELECT v.user_id,u.nickname,v.session_id,v.muted,v.last_seen FROM voice_members v
      JOIN users u ON u.id=v.user_id WHERE v.room_id=? AND v.last_seen>? ORDER BY v.user_id''',(rid,clock-35))]
    known={m['user_id'] for m in members}
    for row in db.execute('SELECT v.user_id,u.nickname,v.session_id,v.muted,v.last_seen FROM voice_members v JOIN users u ON u.id=v.user_id WHERE v.room_id=?',(rid,)):
        if row['user_id'] not in known and (rid,row['user_id'],row['session_id']) in live:members.append(dict(row))
    for m in members:m.pop('last_seen',None)
    profiles=member_accounts.public_profiles(db) if profiles is None else profiles
    cosmetics=rewards.profile_map(db) if cosmetics is None else cosmetics
    identities={str(person['user_id']):{'cosmetics':cosmetics.get(person['user_id'],{}),**profiles.get(person['user_id'],{})} for person in messages+members}
    own=next((m for m in members if m['user_id']==uid),None)
    signals=[]
    if own:
        for row in db.execute('''SELECT id,sender_id,sender_session,kind,payload,target_session FROM voice_signals
          WHERE room_id=? AND target_id=? AND target_session=? AND created_at>? ORDER BY id DESC LIMIT 80''',
          (rid,uid,own['session_id'],clock-60)):
            signal=dict(row);signal['payload']=json.loads(signal['payload']);signals.append(signal)
        signals.reverse()
    return {'messages':messages,'voice_members':members,'identities':identities,'signals':signals}


def mutate(db,path,data,user,clock):
    member_accounts.require_active(db,user['id'])
    match=re.fullmatch(r'/api/social/rooms/(\d+)/(chat|voice/(?:join|leave|ping|signal))',path)
    if not match:raise engine.RuleError('找不到聊天室操作。')
    rid,action=int(match[1]),match[2]
    uid=user['id'];room=voice_access(db,rid,uid)
    row={'status':room.get('status','waiting')}
    if rid==0 and action=='chat':raise engine.RuleError('大廳語音不提供牌桌文字訊息。')
    if action=='voice/leave':
        db.execute('DELETE FROM voice_members WHERE room_id=? AND user_id=? AND session_id=?',(rid,uid,data.get('session_id')))
        return {'ok':True}
    if row['status']=='closed' and action=='chat':raise engine.RuleError('本桌已結束，聊天室僅供查看紀錄。')
    if action=='chat':
        text=data.get('message');nonce=data.get('nonce')
        if not isinstance(text,str) or not 1<=len(text.strip())<=300:raise engine.RuleError('訊息請填寫 1–300 個字。')
        if not isinstance(nonce,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',nonce):raise engine.RuleError('訊息編號無效。')
        previous=db.execute('SELECT id,room_id,message FROM room_chat WHERE user_id=? AND nonce=?',(uid,nonce)).fetchone()
        if previous:
            if previous['room_id']!=rid or previous['message']!=text.strip():raise engine.RuleError('訊息編號已用於另一則訊息，請重新傳送。')
            return {'ok':True,'id':previous[0]}
        if db.execute('SELECT count(*) FROM room_chat WHERE user_id=? AND created_at>?',(uid,clock-10)).fetchone()[0]>=5:
            raise engine.RuleError('訊息太密集，請稍等幾秒。')
        result=db.execute('INSERT INTO room_chat(room_id,user_id,message,nonce,created_at) VALUES(?,?,?,?,?)',
                          (rid,uid,text.strip(),nonce,clock))
        return {'ok':True,'id':result.lastrowid}
    session=data.get('session_id')
    if not isinstance(session,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',session):raise engine.RuleError('語音連線編號無效。')
    if action=='voice/join':
        previous=own_voice(db,uid,clock)
        if data.get('resume') and previous and (previous[0]!=rid or previous[1]!=session):raise engine.RuleError('語音已在另一個分頁加入，請手動重新加入。')
        db.execute('DELETE FROM voice_members WHERE user_id=? AND (room_id!=? OR session_id!=?)',(uid,rid,session))
        db.execute('''INSERT INTO voice_members VALUES(?,?,?,?,0) ON CONFLICT(room_id,user_id) DO UPDATE SET
          session_id=excluded.session_id,last_seen=excluded.last_seen,muted=0''',(rid,uid,session,clock))
        return {'ok':True,**config(),'transport':'pcm-wss-v1','channel':{'id':rid,'name':'大廳語音' if rid==0 else room['name']},'sampleRate':16000,'frameSamples':640}
    member=voice_member(db,rid,uid,session,clock)
    if not member:raise engine.RuleError('語音已中斷，請重新加入。')
    if action=='voice/ping':
        db.execute('UPDATE voice_members SET last_seen=?,muted=? WHERE room_id=? AND user_id=?',
                   (clock,int(bool(data.get('muted'))),rid,uid))
        return {'ok':True}
    target=data.get('target_id');target_session=data.get('target_session');kind=data.get('kind');payload=data.get('payload')
    if kind not in ('offer','answer','candidate') or not isinstance(payload,dict) or len(json.dumps(payload))>16000:
        raise engine.RuleError('語音協商資料無效。')
    if target==uid or not db.execute('SELECT 1 FROM voice_members WHERE room_id=? AND user_id=? AND session_id=? AND last_seen>?',
        (rid,target,target_session,clock-35)).fetchone():raise engine.RuleError('對方已離開語音。')
    if db.execute('SELECT count(*) FROM voice_signals WHERE sender_id=? AND created_at>?',(uid,clock-60)).fetchone()[0]>=240:
        raise engine.RuleError('語音重連次數過多，請稍後重新加入。')
    db.execute('INSERT INTO voice_signals(room_id,sender_id,sender_session,target_id,target_session,kind,payload,created_at) VALUES(?,?,?,?,?,?,?,?)',
               (rid,uid,session,target,target_session,kind,json.dumps(payload),clock))
    return {'ok':True}


def voice_access(db,rid,uid):
    member_accounts.require_active(db,uid)
    if rid==0:return {'id':0,'name':'大廳語音','status':'waiting'}
    row=db.execute('SELECT state FROM poker_rooms WHERE id=?',(rid,)).fetchone()
    if not row:raise engine.RuleError('找不到語音房。')
    room=json.loads(row[0])
    import club_features
    club_features.require_access(room,uid)
    return room


def voice_member(db,rid,uid,session,clock):
    voice_access(db,rid,uid)
    import voice_transport
    row=db.execute('SELECT last_seen FROM voice_members WHERE room_id=? AND user_id=? AND session_id=?',(rid,uid,session)).fetchone()
    return bool(row and (row[0]>clock-35 or (rid,uid,session) in voice_transport.HUB.sessions()))


def own_voice(db,uid,clock):
    import voice_transport
    live=set(voice_transport.HUB.sessions())
    for row in db.execute('SELECT room_id,session_id,last_seen FROM voice_members WHERE user_id=? ORDER BY last_seen DESC',(uid,)):
        if row[2]>clock-35 or (row[0],uid,row[1]) in live:return row
    return None


def voice_state(db,rid,uid,clock):
    room=voice_access(db,rid,uid)
    value=view(db,rid,uid,clock)
    import voice_transport
    connected=set(voice_transport.HUB.online(rid))
    value.pop('signals',None);value.pop('messages',None)
    for m in value['voice_members']:m['connected']=m['user_id'] in connected
    own=own_voice(db,uid,clock)
    return {**value,'channel':{'id':rid,'name':'大廳語音' if rid==0 else room['name']},'own_channel':own[0] if own else None,'own_session':own[1] if own else None,'server_time':clock,'transport':'pcm-wss-v1'}
