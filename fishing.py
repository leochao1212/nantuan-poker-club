"""Two virtual-point fishing modes; one durable receipt per account/action."""
import json
import re
import secrets
import wallet
import game_settings
import member_accounts
from poker_engine import RuleError

FISH = [
    dict(id='sardine', name='銀鱗沙丁', rarity='常見', color='#88c9d8', weight=30, value=2, multiplier=2, length=18),
    dict(id='clownfish', name='珊瑚小丑', rarity='常見', color='#f5a45d', weight=25, value=3, multiplier=3, length=14),
    dict(id='mackerel', name='青花鯖魚', rarity='常見', color='#63b5a1', weight=20, value=5, multiplier=5, length=32),
    dict(id='snapper', name='胭脂紅鯛', rarity='少見', color='#ef8e90', weight=12, value=8, multiplier=8, length=45),
    dict(id='tuna', name='深海鮪魚', rarity='少見', color='#7f9ce0', weight=7, value=15, multiplier=12, length=110),
    dict(id='ray', name='月光魟魚', rarity='稀有', color='#b2a1e5', weight=4, value=25, multiplier=20, length=90),
    dict(id='swordfish', name='逐浪旗魚', rarity='稀有', color='#70ced6', weight=1, value=50, multiplier=35, length=180),
    dict(id='goldfish', name='曜金龍魚', rarity='傳說', color='#f1d178', weight=1, value=100, multiplier=60, length=80),
    dict(id='crab',name='黃金帝王蟹',rarity='特殊',color='#f5c54c',weight=0,value=0,multiplier=80,length=140,feature='bomb'),
    dict(id='octopus',name='深海章魚',rarity='特殊',color='#b17ee9',weight=0,value=0,multiplier=90,length=180,feature='arms'),
    dict(id='eel',name='雷霆電鰻',rarity='特殊',color='#6bb8f2',weight=0,value=0,multiplier=100,length=220,feature='lightning'),
    dict(id='dragon',name='翡翠海龍',rarity='特殊',color='#6be2b6',weight=0,value=0,multiplier=120,length=300,feature='dragon'),
]
BY_ID = {f['id']: f for f in FISH}
SHOT_INTERVAL = .6


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS fishing_casts(
      id TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),day TEXT NOT NULL,
      species TEXT NOT NULL,size_cm INTEGER NOT NULL,ready_at REAL NOT NULL,collected_at REAL,
      created_at REAL NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS fishing_one_cast ON fishing_casts(user_id) WHERE collected_at IS NULL;
    CREATE INDEX IF NOT EXISTS fishing_daily ON fishing_casts(user_id,day);
    CREATE TABLE IF NOT EXISTS fishing_collection(
      user_id INTEGER NOT NULL REFERENCES users(id),species TEXT NOT NULL,stored INTEGER NOT NULL DEFAULT 0 CHECK(stored>=0),
      leisure INTEGER NOT NULL DEFAULT 0,arcade INTEGER NOT NULL DEFAULT 0,largest_cm INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(user_id,species));
    CREATE TABLE IF NOT EXISTS fishing_stats(
      user_id INTEGER PRIMARY KEY REFERENCES users(id),shots INTEGER NOT NULL DEFAULT 0,
      spent INTEGER NOT NULL DEFAULT 0,returned INTEGER NOT NULL DEFAULT 0,last_shot_at REAL NOT NULL DEFAULT -1);
    CREATE TABLE IF NOT EXISTS fishing_operations(
      user_id INTEGER NOT NULL REFERENCES users(id),operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
      result TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(user_id,operation_id));
    CREATE INDEX IF NOT EXISTS fishing_recent ON fishing_operations(user_id,created_at DESC);
    ''')
    import fishing_gameplay
    fishing_gameplay.initialize(db)


def _base_view(db, uid, clock):
    cfg = game_settings.current(db, 'fishing')
    pending = db.execute('SELECT id,ready_at FROM fishing_casts WHERE user_id=? AND collected_at IS NULL', (uid,)).fetchone()
    used = db.execute('SELECT count(*) FROM fishing_casts WHERE user_id=? AND day=?', (uid, wallet.day(clock))).fetchone()[0]
    rows = {r['species']: dict(r) for r in db.execute('SELECT * FROM fishing_collection WHERE user_id=?', (uid,))}
    collection = [{**f, **{k: rows.get(f['id'], {}).get(k, 0) for k in ('stored','leisure','arcade','largest_cm')},
                   'catch_percent': cfg['params']['target_bps'] / (100 * f['multiplier']), 'chain':bool(f.get('feature'))} for f in FISH]
    stats = db.execute('SELECT * FROM fishing_stats WHERE user_id=?', (uid,)).fetchone()
    recent = [json.loads(r[0]) for r in db.execute('SELECT result FROM fishing_operations WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 8', (uid,))]
    return dict(catalog=collection, pending=dict(pending) if pending else None, day=wallet.day(clock),
                free_casts=max(0, cfg['params']['daily_casts'] - used), daily_casts=cfg['params']['daily_casts'],
                bag_value=sum(f['stored'] * f['value'] for f in collection),
                bag_count=sum(f['stored'] for f in collection), discovered=sum(f['leisure']+f['arcade']>0 for f in collection),
                shots=stats['shots'] if stats else 0, spent=stats['spent'] if stats else 0,
                returned=stats['returned'] if stats else 0, next_shot_at=(stats['last_shot_at']+SHOT_INTERVAL) if stats else 0,
                max_shot=min(100, game_settings.bet_limit(cfg)), settings=cfg, recent=recent,
                wallet=wallet.view(db, uid, clock), server_time=clock)


def _collect(db, uid, species, size, mode):
    leisure = int(mode=='leisure')
    db.execute('''INSERT INTO fishing_collection(user_id,species,stored,leisure,arcade,largest_cm)
      VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,species) DO UPDATE SET
      stored=stored+excluded.stored,leisure=leisure+excluded.leisure,arcade=arcade+excluded.arcade,
      largest_cm=max(largest_cm,excluded.largest_cm)''', (uid,species,leisure,leisure,1-leisure,size))


def _intent(action, data):
    fields = {'cast': ('expected_revision',), 'reel': ('cast_id',),
              'shot': ('species','stake','expected_revision','expected_limit_revision'), 'sell': ()}
    if action not in fields: raise RuleError('釣魚操作無效。')
    if set(data) - {'operation_id', *fields[action]}: raise RuleError('釣魚操作包含未知欄位。')
    value = {key:data.get(key) for key in fields[action]}
    return game_settings.encode({'action':action, **value})


def _legacy_mutate(db, user, action, data, clock):
    uid=user['id'];member_accounts.require_active(db,uid)
    op=data.get('operation_id')
    if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',op): raise RuleError('釣魚操作編號無效。')
    fingerprint=_intent(action,data)
    old=db.execute('SELECT fingerprint,result FROM fishing_operations WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint: raise RuleError('同一釣魚操作編號的內容不符，請先確認原操作。')
        return dict(ok=True,replayed=True,result=json.loads(old['result']),state=view(db,uid,clock))
    if not wallet.active(db): raise RuleError('點數制度更新中，請稍候。')
    if action not in ('reel','sell'):raise RuleError('釣魚玩法已更新，請重新整理。')
    result={'action':action,'operation_id':op,'at':clock}
    db.execute('SAVEPOINT fishing_action')
    try:
        if action=='reel':
            ident=data.get('cast_id')
            if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident): raise RuleError('魚竿編號無效。')
            cast=db.execute('SELECT * FROM fishing_casts WHERE id=? AND user_id=? AND version=1 AND collected_at IS NULL',(ident,uid)).fetchone()
            if not cast: raise RuleError('找不到這一竿，請重新讀取漁港。')
            if clock<cast['ready_at']: raise RuleError('魚還沒咬鉤，再等一下。')
            _collect(db,uid,cast['species'],cast['size_cm'],'leisure')
            db.execute('UPDATE fishing_casts SET collected_at=? WHERE id=?',(clock,ident))
            result.update(species=cast['species'],size_cm=cast['size_cm'],value=BY_ID[cast['species']]['value'])
        else:
            rows=db.execute('SELECT species,stored FROM fishing_collection WHERE user_id=? AND stored>0',(uid,)).fetchall()
            amount=sum(BY_ID[r['species']]['value']*r['stored'] for r in rows);count=sum(r['stored'] for r in rows)
            if not amount: raise RuleError('魚簍是空的，先釣幾條魚吧。')
            db.execute('UPDATE fishing_collection SET stored=0 WHERE user_id=?',(uid,))
            wallet.transfer(db,uid,amount,'fishing_sale','fish:'+op+':sale',clock)
            result.update(amount=amount,count=count)
        db.execute('INSERT INTO fishing_operations VALUES(?,?,?,?,?)',(uid,op,fingerprint,game_settings.encode(result),clock))
        db.execute('RELEASE SAVEPOINT fishing_action')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT fishing_action');db.execute('RELEASE SAVEPOINT fishing_action');raise
    return dict(ok=True,replayed=False,result=result,state=view(db,uid,clock))


def view(db,uid,clock):
    import fishing_gameplay
    return fishing_gameplay.view(db,uid,clock)


def mutate(db,user,action,data,clock):
    import fishing_gameplay
    return fishing_gameplay.mutate(db,user,action,data,clock)
