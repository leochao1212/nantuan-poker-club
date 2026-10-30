"""Virtual account chips. All calls share the caller's SQLite transaction."""
import json
import re
import secrets
import clubhouse
from datetime import datetime, timedelta, timezone
import poker_engine as engine

INITIAL = 10000
DAILY = 2000
HOURLY = 500
HOURLY_DAILY_LIMIT = 4
HOURLY_SECONDS = 3600
TAIPEI = timezone(timedelta(hours=8))


def day(clock):
    return datetime.fromtimestamp(clock,TAIPEI).date().isoformat()


def active(db):
    return db.execute("SELECT value FROM wallet_meta WHERE key='state'").fetchone()[0]=='active'


def initialize(db,clock):
    import bank,market
    bank.initialize(db)
    market.initialize(db)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS wallet_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS wallets(user_id INTEGER PRIMARY KEY REFERENCES users(id),balance INTEGER NOT NULL CHECK(balance>=0));
    CREATE TABLE IF NOT EXISTS wallet_ledger(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
      amount INTEGER NOT NULL,balance_after INTEGER NOT NULL,kind TEXT NOT NULL,event_key TEXT NOT NULL,created_at REAL NOT NULL,
      UNIQUE(user_id,event_key));
    CREATE INDEX IF NOT EXISTS wallet_ledger_claims ON wallet_ledger(user_id,kind,created_at);
    INSERT OR IGNORE INTO wallet_meta VALUES('state','pending');
    """)
    clubhouse.schema(db,clock)
    maybe_activate(db,clock)
    clubhouse.seed(db,clock)
    import economy
    economy.initialize(db,clock)


def create(db,uid,clock):
    if active(db) and db.execute('INSERT OR IGNORE INTO wallets VALUES(?,?)',(uid,INITIAL)).rowcount:
        db.execute('INSERT INTO wallet_ledger(user_id,amount,balance_after,kind,event_key,created_at) VALUES(?,?,?,?,?,?)',
                   (uid,INITIAL,INITIAL,'initial','initial-v1',clock))
        clubhouse.enroll(db,uid,clock,INITIAL)


def maybe_activate(db,clock):
    if active(db):
        for row in db.execute('SELECT id FROM users').fetchall():create(db,row[0],clock)
        return False
    if db.execute("SELECT 1 FROM poker_rooms WHERE status='playing' LIMIT 1").fetchone():return False
    # The user explicitly chose a uniform reset after all current hands end.
    # Close old tables to prevent legacy, freely minted stacks entering wallets.
    import online
    for row in db.execute("SELECT * FROM poker_rooms WHERE status!='closed'").fetchall():
        room=online.decode(row)
        for seat in list(room['seats']):engine.depart(room,seat,clock)
        room['status']='closed'
        engine.log(room,'總籌碼制度啟用，本桌已結束；請用帳號籌碼重新入桌。',clock)
        online.save(db,room,clock)
    db.execute("UPDATE wallet_meta SET value='active' WHERE key='state'")
    for row in db.execute('SELECT id FROM users').fetchall():create(db,row[0],clock)
    return True


def transfer(db,uid,amount,kind,key,clock,*,game=False):
    if not active(db):return
    if db.execute('SELECT 1 FROM wallet_ledger WHERE user_id=? AND event_key=?',(uid,key)).fetchone():return
    create(db,uid,clock)
    row=db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()
    if row[0]+amount<0:raise engine.RuleError(f'錢包籌碼不足，需要 {abs(amount):,} 點。可先離桌取回籌碼，或領取今日補給。')
    balance=row[0]+amount
    db.execute('UPDATE wallets SET balance=? WHERE user_id=?',(balance,uid))
    db.execute('INSERT INTO wallet_ledger(user_id,amount,balance_after,kind,event_key,created_at) VALUES(?,?,?,?,?,?)',
               (uid,amount,balance,kind,key,clock))
    clubhouse.record(db,uid,amount,kind,key,clock,game=game)
    if amount>0 and kind in ('daily','hourly','mission','passive'):
        import bank
        bank.auto_repay(db,uid,amount,key,clock)


def supply_amounts(db,uid):
    import rewards
    bonus=rewards.equipped_bonus(db,uid)
    return dict(daily_amount=DAILY+DAILY*bonus['daily_bps']//10000,
                hourly_amount=HOURLY+HOURLY*bonus['hourly_bps']//10000,
                daily_base=DAILY,hourly_base=HOURLY,title_bonus=bonus)


def claim(db,uid,clock):
    if not active(db):raise engine.RuleError('目前手牌結束後將啟用帳號籌碼，請稍候。')
    create(db,uid,clock)
    key='daily:'+day(clock)
    if db.execute('SELECT 1 FROM wallet_ledger WHERE user_id=? AND event_key=?',(uid,key)).fetchone():
        return {'claimed':False,'message':'今天已領取，台灣時間午夜後可再領。'}
    amount=supply_amounts(db,uid)['daily_amount']
    transfer(db,uid,amount,'daily',key,clock)
    return {'claimed':True,'amount':amount,'message':f'已領取今日 {amount:,} 點。'}



def hourly_remaining(db,uid,clock):
    start=datetime.fromisoformat(day(clock)).replace(tzinfo=TAIPEI).timestamp()
    count=db.execute("SELECT count(*) FROM wallet_ledger WHERE user_id=? AND kind='hourly' AND created_at>=? AND created_at<?",(uid,start,start+86400)).fetchone()[0]
    return max(0,HOURLY_DAILY_LIMIT-count)


def hourly_next_at(db,uid):
    row=db.execute("SELECT MAX(created_at) FROM wallet_ledger WHERE user_id=? AND kind='hourly'",(uid,)).fetchone()
    return row[0]+HOURLY_SECONDS if row[0] is not None else 0


def claim_hourly(db,uid,clock,operation_id=None):
    if not active(db):raise engine.RuleError('點數制度尚未啟用，請稍候。')
    if operation_id is None:operation_id=secrets.token_hex(16)
    if not isinstance(operation_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',operation_id):
        raise engine.RuleError('補給操作編號無效，請重新整理。')
    create(db,uid,clock)
    key='hourly:'+operation_id
    if db.execute('SELECT 1 FROM wallet_ledger WHERE user_id=? AND event_key=?',(uid,key)).fetchone():
        return {'claimed':False,'replayed':True,'message':'這筆每小時補給已領取，不會重複入帳。'}
    if not hourly_remaining(db,uid,clock):return {'claimed':False,'message':'今日 4 次補給已領完，台灣時間午夜後更新。'}
    if clock<hourly_next_at(db,uid):
        return {'claimed':False,'message':'每小時補給尚在冷卻中，領取後需等待 60 分鐘。'}
    amount=supply_amounts(db,uid)['hourly_amount']
    transfer(db,uid,amount,'hourly',key,clock)
    return {'claimed':True,'amount':amount,'message':f'已領取每小時補給 {amount:,} 點，60 分鐘後可再領。'}


def _in_play(db):
    return {row[0]:row[1] for row in db.execute("""SELECT uid,sum(amount) FROM (
      SELECT json_extract(s.value,'$.user_id') AS uid,json_extract(s.value,'$.stack') AS amount
      FROM poker_rooms r,json_each(r.state,'$.seats') s WHERE r.status!='closed'
      UNION ALL
      SELECT json_extract(p.value,'$.user_id'),json_extract(p.value,'$.contribution')
      FROM poker_rooms r,json_each(r.state,'$.hand.players') p WHERE r.status='playing'
    ) GROUP BY uid""")}


def in_play(db):
    import view_cache
    return view_cache.shared(db,'in_play',('poker_rooms',),lambda:_in_play(db))


def view(db,uid,clock,totals=None):
    import bank,market
    import economy
    enabled=active(db)
    row=db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()
    balance=row[0] if row else 0
    table=(in_play(db) if totals is None else totals).get(uid,0)
    claimed=bool(db.execute('SELECT 1 FROM wallet_ledger WHERE user_id=? AND event_key=?',(uid,'daily:'+day(clock))).fetchone())
    next_at=hourly_next_at(db,uid)
    banking=bank.summary(db,uid,clock)
    investing=market.assets(db).get(uid,0)
    return {'economy':economy.view(db,uid,clock),'hourly_remaining':hourly_remaining(db,uid,clock),'hourly_daily_limit':HOURLY_DAILY_LIMIT,'investments':investing,'bank':banking,'income':clubhouse.income_view(db,uid,clock),**supply_amounts(db,uid),'hourly_next_at':next_at,'hourly_available':enabled and clock>=next_at and hourly_remaining(db,uid,clock)>0,'hourly_interval':HOURLY_SECONDS,
            'enabled':enabled,'migration_pending':not enabled,'balance':balance,'in_play':table,'total':balance+table+banking['savings']-banking['debt']+investing,
            'daily_claimed':claimed,'day':day(clock),'initial':INITIAL}
