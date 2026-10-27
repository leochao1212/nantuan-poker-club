"""Site-defined treasure events. Settlement is independent of reveal animation."""
import json
import secrets
import re
from datetime import datetime,timedelta
import wallet
from poker_engine import RuleError

POOL=[dict(multiplier=m,weight=w) for m,w in zip((2,3,5,8,10,20,50,100),(30,25,20,12,7,4,1,1))]
MEAN_HUNDREDTHS=631
ROUNDS={'chest':3,'treasure':3,'whale':5}
SUPPLY={'freeze':3,'laser':1}

def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS fishing_bonus_events(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,source_id TEXT NOT NULL UNIQUE,created_at REAL NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS fishing_bonus_owner ON fishing_bonus_events(user_id,status,created_at);
    CREATE TABLE IF NOT EXISTS fishing_items(user_id INTEGER PRIMARY KEY,freeze INTEGER NOT NULL DEFAULT 5 CHECK(freeze>=0),laser INTEGER NOT NULL DEFAULT 2 CHECK(laser>=0));
    CREATE TABLE IF NOT EXISTS fishing_supplies(user_id INTEGER NOT NULL,day TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(user_id,day));
    """)

def items(db,uid):
    row=db.execute('SELECT freeze,laser FROM fishing_items WHERE user_id=?',(uid,)).fetchone()
    return dict(row) if row else {'freeze':5,'laser':2}

def stock(db,uid):
    db.execute('INSERT OR IGNORE INTO fishing_items(user_id) VALUES(?)',(uid,))

def supply_view(db,uid,clock):
    today=wallet.day(clock)
    claimed=bool(db.execute('SELECT 1 FROM fishing_supplies WHERE user_id=? AND day=?',(uid,today)).fetchone())
    next_at=(datetime.fromisoformat(today).replace(tzinfo=wallet.TAIPEI)+timedelta(days=1)).timestamp()
    return dict(day=today,claimed=claimed,next_at=next_at,rewards=SUPPLY.copy())

def claim_supply(db,uid,clock):
    today=wallet.day(clock)
    claimed=bool(db.execute('INSERT OR IGNORE INTO fishing_supplies VALUES(?,?,?)',(uid,today,clock)).rowcount)
    if claimed:
        stock(db,uid)
        db.execute('UPDATE fishing_items SET freeze=freeze+?,laser=laser+? WHERE user_id=?',(SUPPLY['freeze'],SUPPLY['laser'],uid))
    return dict(claimed=claimed,day=today,rewards=SUPPLY.copy() if claimed else dict(freeze=0,laser=0))

def rules(feature):
    count=ROUNDS.get(feature,0)
    return dict(version=1,rounds=count,pool=POOL,mean_hundredths=MEAN_HUNDREDTHS) if count else None

def create(db,uid,source,stake,snapshot,clock):
    ident=secrets.token_hex(16)
    data=dict(stake=stake,**snapshot)
    db.execute('INSERT INTO fishing_bonus_events VALUES(?,?,?,?,?,?)',(ident,uid,str(source),clock,'ready',json.dumps(data)))
    return ident

def public(row):
    return dict(id=row['id'],status=row['status'],created_at=row['created_at'],**json.loads(row['data']))

def view(db,uid):
    pending=[public(r) for r in db.execute("SELECT * FROM fishing_bonus_events WHERE user_id=? AND status='ready' ORDER BY created_at,id",(uid,))]
    last=db.execute("SELECT * FROM fishing_bonus_events WHERE user_id=? AND status='settled' ORDER BY created_at DESC,id DESC LIMIT 1",(uid,)).fetchone()
    return dict(bonuses=pending,last_bonus=public(last) if last else None,items=items(db,uid))

def settle(db,uid,ident,clock):
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident):raise RuleError('寶箱識別碼無效。')
    row=db.execute('SELECT * FROM fishing_bonus_events WHERE id=? AND user_id=?',(ident,uid)).fetchone()
    if not row:raise RuleError('找不到你的寶箱。')
    if row['status']=='settled':return public(row)
    data=json.loads(row['data']);pool=data['pool'];total_weight=sum(p['weight'] for p in pool);draws=[]
    for _ in range(data['rounds']):
        ticket=secrets.randbelow(total_weight)
        for prize in pool:
            if ticket<prize['weight']:draws.append(prize['multiplier']);break
            ticket-=prize['weight']
    gross=data['stake']*sum(draws);item=('freeze','laser')[secrets.randbelow(2)]
    data.update(draws=draws,gross=gross,item=item,settled_at=clock)
    # Owner row, wallet entry, inventory, stats and immutable operation receipt share one savepoint.
    wallet.transfer(db,uid,gross,'fishing_win','fish:bonus:'+ident,clock,game=True)
    stock(db,uid);db.execute('UPDATE fishing_items SET '+item+'='+item+'+1 WHERE user_id=?',(uid,))
    db.execute('UPDATE fishing_stats SET returned=returned+? WHERE user_id=?',(gross,uid))
    db.execute("UPDATE fishing_bonus_events SET status='settled',data=? WHERE id=?",(json.dumps(data),ident))
    return dict(id=ident,status='settled',created_at=row['created_at'],**data)
