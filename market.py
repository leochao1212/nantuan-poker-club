"""Paper spot and capped 1x short orders in TWD points. No network I/O; caller owns the transaction.

Cash buys reserve an integer budget; sells reserve existing fractional units.
Delayed stock orders execute on a source observation newer than their submission
snapshot. Legacy orders require source time newer than submission wall time. Quantities use 1e-8 fixed units.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import member_accounts
import market_catalog
import market_contracts
import market_charts
import market_review
from poker_engine import RuleError

SCALE = 100_000_000
CATALOG = (
    ('TW:2330','台積電','TW','TWD'),('TW:2317','鴻海','TW','TWD'),
    ('TW:2454','聯發科','TW','TWD'),('TW:0050','元大台灣50','TW','TWD'),
    ('TW:0056','元大高股息','TW','TWD'),
    ('US:AAPL','Apple','US','USD'),('US:MSFT','Microsoft','US','USD'),
    ('US:NVDA','NVIDIA','US','USD'),
    ('CC:BTC','Bitcoin','CC','USD'),('CC:ETH','Ethereum','CC','USD'),
    ('CC:SOL','Solana','CC','USD'))
INSTRUMENTS = {r[0]:dict(symbol=r[0],name=r[1],market=r[2],currency=r[3]) for r in CATALOG}
PENDING_SECONDS = {'TW':7*86400,'US':7*86400,'CC':120}
TAIPEI=timezone(timedelta(hours=8))
TW_SOURCE='TWSE MIS 盤中報價'
TW_MID_SOURCE='TWSE MIS 買賣中間參考價'
TW_QUOTE_AGE=30
TW_CHECK_AGE=20
US_SOURCE='Yahoo Finance 成交參考價'
US_QUOTE_AGE=90
US_CHECK_AGE=30
TV_SOURCE='TradingView 延遲成交參考價'
TV_CHECK_AGE=90
QUOTE_SQL="""SELECT q.*,COALESCE(h.issue,'') AS issue,m.session_start,m.session_end,t.delay_seconds,t.feed_session
 FROM market_quotes q LEFT JOIN market_quote_health h USING(symbol)
 LEFT JOIN market_quote_meta m USING(symbol) LEFT JOIN market_tv_meta t USING(symbol)"""


def tw_session(clock):
    local=datetime.fromtimestamp(clock,TAIPEI)
    return local.weekday()<5 and 9*3600<=local.hour*3600+local.minute*60+local.second<13*3600+30*60


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS market_quotes(symbol TEXT PRIMARY KEY,price TEXT NOT NULL,
      bid TEXT NOT NULL,ask TEXT NOT NULL,native TEXT NOT NULL,fx TEXT NOT NULL,
      asof REAL NOT NULL,fx_at REAL NOT NULL,checked_at REAL NOT NULL,source TEXT NOT NULL,
      token TEXT NOT NULL,halted INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS market_providers(name TEXT PRIMARY KEY,next_at REAL NOT NULL,
      last_at REAL NOT NULL,status TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS market_positions(user_id INTEGER NOT NULL REFERENCES users(id),
      symbol TEXT NOT NULL,units INTEGER NOT NULL CHECK(units>=0),cost INTEGER NOT NULL CHECK(cost>=0),
      PRIMARY KEY(user_id,symbol));
    CREATE TABLE IF NOT EXISTS market_orders(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
      symbol TEXT NOT NULL,side TEXT NOT NULL,budget INTEGER NOT NULL,units INTEGER NOT NULL,
      status TEXT NOT NULL,submitted_at REAL NOT NULL,expires_at REAL NOT NULL,
      filled_at REAL,fill_asof REAL,fill_price TEXT,filled_units INTEGER,points INTEGER,profit INTEGER,
      reason TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS market_user_orders ON market_orders(user_id,id DESC);
    CREATE INDEX IF NOT EXISTS market_pending ON market_orders(status,symbol);
    CREATE TABLE IF NOT EXISTS market_operations(user_id INTEGER NOT NULL REFERENCES users(id),
      operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,
      PRIMARY KEY(user_id,operation_id));
    CREATE TABLE IF NOT EXISTS market_prices(symbol TEXT NOT NULL,asof REAL NOT NULL,price TEXT NOT NULL,
      PRIMARY KEY(symbol,asof));
    CREATE TABLE IF NOT EXISTS market_shorts(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
      symbol TEXT NOT NULL,units INTEGER NOT NULL,margin INTEGER NOT NULL,entry_points INTEGER NOT NULL,
      entry_price TEXT NOT NULL,opened_at REAL NOT NULL,entry_asof REAL NOT NULL,status TEXT NOT NULL,
      closed_at REAL,exit_price TEXT,profit INTEGER,returned INTEGER);
    CREATE INDEX IF NOT EXISTS market_short_owner ON market_shorts(user_id,status);
    ''')
    if 'position_id' not in {r[1] for r in db.execute('PRAGMA table_info(market_orders)')}:
        db.execute('ALTER TABLE market_orders ADD COLUMN position_id INTEGER REFERENCES market_shorts(id)')
    db.execute("CREATE TABLE IF NOT EXISTS market_quote_health(symbol TEXT PRIMARY KEY,issue TEXT NOT NULL)")
    # Keep the original twelve quote columns compatible with rollback releases.
    db.execute('CREATE TABLE IF NOT EXISTS market_quote_meta(symbol TEXT PRIMARY KEY,session_start REAL NOT NULL,session_end REAL NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS market_tv_meta(symbol TEXT PRIMARY KEY,delay_seconds INTEGER NOT NULL,feed_session TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS market_order_quote_refs(kind TEXT NOT NULL,order_id INTEGER NOT NULL,source_asof REAL NOT NULL,source TEXT NOT NULL,PRIMARY KEY(kind,order_id))')
    market_catalog.initialize(db,CATALOG)
    market_contracts.initialize(db)
    market_charts.initialize(db)
    market_review.initialize(db)
    db.execute('CREATE TABLE IF NOT EXISTS market_history(symbol TEXT NOT NULL,asof REAL NOT NULL,price TEXT NOT NULL,native TEXT NOT NULL,fx TEXT NOT NULL,fx_at REAL NOT NULL,PRIMARY KEY(symbol,asof))')


def decimal(value):
    try:
        if isinstance(value,bool):raise ValueError()
        result=Decimal(str(value))
        if not result.is_finite() or result<Decimal('0.000000000001') or result>Decimal('1000000000'):raise ValueError()
        return result
    except (ValueError,InvalidOperation):raise RuleError('價格或數量無效。') from None


def value_points(units,price,*,up=False):
    numerator,denominator=decimal(price).as_integer_ratio()
    top=units*numerator;bottom=SCALE*denominator
    return (top+bottom-1)//bottom if up else top//bottom


def units_for_budget(budget,price):
    numerator,denominator=decimal(price).as_integer_ratio()
    return budget*SCALE*denominator//numerator


def quantity(units):
    return format(Decimal(units)/SCALE,'f')


def quote_ready(q,clock):
    if not q or market_catalog.group(q['symbol']) not in ('TW','US','CC') or q['halted'] or ('issue' in q.keys() and q['issue']):return False
    group=market_catalog.group(q['symbol'])
    age=clock-q['asof']
    if q['source']==TV_SOURCE:
        return (group in ('TW','US') and 'delay_seconds' in q.keys() and
            q['delay_seconds'] in (0,900) and q['feed_session']=='market' and
            -5<=age<=q['delay_seconds']+120 and -5<=clock-q['checked_at']<=TV_CHECK_AGE and
            (group!='TW' or tw_session(clock)) and (group!='US' or -5<=clock-q['fx_at']<=3*86400))
    if group=='TW':
        return q['source'] in (TW_SOURCE,TW_MID_SOURCE) and tw_session(clock) and -5<=age<=TW_QUOTE_AGE and -5<=clock-q['checked_at']<=TW_CHECK_AGE
    if group=='US':
        return (q['source']==US_SOURCE and 'session_start' in q.keys() and
            q['session_start'] is not None and q['session_end'] is not None and
            q['session_start']<=q['asof']<=clock<q['session_end'] and
            -5<=age<=US_QUOTE_AGE and -5<=clock-q['checked_at']<=US_CHECK_AGE and
            -5<=clock-q['fx_at']<=3*86400)
    return -5<=age<=120 and -5<=clock-q['checked_at']<=120 and -5<=clock-q['fx_at']<=3*86400


def quote_notice(q,code,clock):
    if q and q['halted']:return '公司行動待確認，暫停成交'
    if q and q['source']==TV_SOURCE:
        if not quote_ready(q,clock):return '休市、行情缺漏或過期，暫停成交'
        return '延遲行情模擬：等下一筆來源更新成交；外部即時價格可能有優勢'
    if market_catalog.group(code)=='US':
        if not q or q['source']!=US_SOURCE:return '等待 TradingView 行情，暫停成交'
        if 'issue' in q.keys() and q['issue']:return '行情缺資料或連線失敗，暫停成交'
        if q['session_start'] is None or q['session_end'] is None:return '交易時段待確認，暫停成交'
        if not q['session_start']<=clock<q['session_end']:return '盤後／休市，暫停成交'
        if not quote_ready(q,clock):return '行情或匯率已過期，暫停成交'
    if market_catalog.group(code)=='TW':
        if not tw_session(clock):return '盤後／休市，暫停成交'
        if not q or q['source'] not in (TW_SOURCE,TW_MID_SOURCE):return '等待 TradingView 行情，暫停成交'
        if 'issue' in q.keys() and q['issue']:return '行情缺資料或連線失敗，暫停成交'
        if not quote_ready(q,clock):return '行情已過期，暫停成交'
    return ''


def remember_order_quote(db,kind,oid,q):
    if q and q['source']==TV_SOURCE:
        db.execute('INSERT INTO market_order_quote_refs VALUES(?,?,?,?)',(kind,oid,q['asof'],q['source']))


def quote_after_order(db,kind,order,q,clock):
    if not quote_ready(q,clock):return False
    reference=db.execute('SELECT source_asof,source FROM market_order_quote_refs WHERE kind=? AND order_id=?',(kind,order['id'])).fetchone()
    # Legacy orders retain their original submission-time requirement.
    if reference:
        return q['source']==reference['source'] and q['asof']>reference['source_asof'] and q['checked_at']>order['submitted_at']
    return q['asof']>order['submitted_at']


def execution_price(q,side):
    # Stock scanner quotes are reference trades, not executable bid/ask.
    return q['price'] if market_catalog.group(q['symbol'])=='US' or q['source']==TV_SOURCE else q['ask' if side in ('buy','cover') else 'bid']


def _assets(db):
    values={r[0]:r[1] for r in db.execute("SELECT user_id,sum(budget) FROM market_orders WHERE status='pending' AND side IN ('buy','short') GROUP BY user_id")}
    # Last known marks remain in net assets when a feed goes stale. Orders stop.
    for r in db.execute('SELECT p.user_id,p.units,p.cost,q.price FROM market_positions p LEFT JOIN market_quotes q USING(symbol) WHERE p.units>0'):
        mark=value_points(r['units'],r['price']) if r['price'] else r['cost']
        values[r['user_id']]=values.get(r['user_id'],0)+mark
    for r in db.execute("SELECT s.*,q.ask FROM market_shorts s LEFT JOIN market_quotes q USING(symbol) WHERE s.status='open'"):
        values[r['user_id']]=values.get(r['user_id'],0)+short_value(r,r['ask'])
    for uid,amount in market_contracts.assets(db,{r['symbol']:dict(r) for r in db.execute('SELECT * FROM market_quotes')}).items():values[uid]=values.get(uid,0)+amount
    return values


def assets(db):
    import view_cache
    return view_cache.shared(db,'market_assets',('market_positions','market_orders','market_quotes','market_shorts','market_contracts','market_contract_orders'),lambda:_assets(db))

def view(db,uid,clock,symbol=None,period=None,interval=None):
    quotes={r['symbol']:dict(r) for r in db.execute(QUOTE_SQL)}
    instruments=[]
    for item in market_catalog.visible(db,uid,CATALOG,symbol):
        code=item['symbol']
        q=quotes.get(code)
        until=None
        if q and item['market']=='TW':
            close=datetime.fromtimestamp(clock,TAIPEI).replace(hour=13,minute=30,second=0,microsecond=0).timestamp()
            until=min(q['asof']+TW_QUOTE_AGE,q['checked_at']+TW_CHECK_AGE,close)
        if q and item['market']=='US':
            until=min(q['asof']+US_QUOTE_AGE,q['checked_at']+US_CHECK_AGE,q['fx_at']+3*86400,q['session_end'] or 0)
        if q and q['source']==TV_SOURCE:
            until=min(q['asof']+(q['delay_seconds'] or 0)+120,q['checked_at']+TV_CHECK_AGE,q['fx_at']+3*86400 if item['market']=='US' else float('inf'))
        public=dict(q,bid=None,ask=None,execution='reference_trade') if q and (item['market']=='US' or q['source']==TV_SOURCE) else q
        instruments.append(dict(item,quote=public,available=quote_ready(q,clock),valid_until=until,notice=quote_notice(q,code,clock),mode='TradingView 延遲行情模擬 · 約 30 秒檢查更新' if q and q['source']==TV_SOURCE else '盤中約 5–10 秒更新' if item['market']=='TW' else '約 10 秒更新'))
    positions=[]
    for r in db.execute('SELECT * FROM market_positions WHERE user_id=? AND units>0',(uid,)):
        item=dict(r);reserved=db.execute("SELECT COALESCE(sum(units),0) FROM market_orders WHERE user_id=? AND symbol=? AND status='pending' AND side='sell'",(uid,r['symbol'])).fetchone()[0]
        q=quotes.get(r['symbol']);mark=value_points(r['units'],q['price']) if q else r['cost']
        positions.append(dict(item,quantity=quantity(r['units']),available_quantity=quantity(r['units']-reserved),value=mark,profit=mark-r['cost'],stale=not quote_ready(q,clock)))
    shorts=[]
    for r in db.execute("SELECT * FROM market_shorts WHERE user_id=? AND status='open' ORDER BY id",(uid,)):
        item=dict(r);q=quotes.get(r['symbol']);value=short_value(r,q['ask'] if q else None)
        closing=bool(db.execute("SELECT 1 FROM market_orders WHERE position_id=? AND status='pending' AND side='cover'",(r['id'],)).fetchone())
        shorts.append(dict(item,quantity=quantity(r['units']),value=value,profit=value-r['margin'],
            liquidation_price=format(Decimal(r['margin']+r['entry_points'])*SCALE/r['units'],'f'),
            closing=closing,stale=not quote_ready(q,clock)))
    return dict(instruments=instruments,positions=positions,shorts=shorts,contracts=market_contracts.view(db,uid,clock,quotes),
        short_history=[dict(r,quantity=quantity(r['units'])) for r in db.execute("SELECT * FROM market_shorts WHERE user_id=? AND status!='open' ORDER BY id DESC LIMIT 20",(uid,))],
        chart=chart(db,symbol,period,clock,interval) if symbol else None,
        orders=[dict(r,quantity=quantity(r['filled_units'] if r['status']=='filled' else r['units'])) for r in db.execute('SELECT * FROM market_orders WHERE user_id=? ORDER BY id DESC LIMIT 50',(uid,))],
        providers=[dict(r) for r in db.execute('SELECT * FROM market_providers ORDER BY name')],
        value=assets(db).get(uid,0),server_time=clock)


def mutate(db,user,action,data,clock):
    import wallet,club_admin
    uid=user['id'];member_accounts.require_active(db,uid)
    if club_admin.identity(db,uid)['is_admin']:club_admin.require(db,uid)
    if not wallet.active(db):raise RuleError('點數制度尚未啟用。')
    op=data.get('operation_id')
    if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',op):raise RuleError('交易回執編號無效。')
    position_id=None
    if action=='order':
        symbol=data.get('symbol');side=data.get('side')
        if not isinstance(symbol,str) or not market_catalog.get(db,symbol) or side not in ('buy','sell','short','cover'):raise RuleError('請選擇交易標的與買賣方向。')
        budget=data.get('amount') if side in ('buy','short') else 0
        minimum=10 if side=='short' else 1
        if side in ('buy','short') and (type(budget) is not int or not minimum<=budget<=1_000_000):raise RuleError(f'點數須為 {minimum}–1,000,000 的整數。')
        units=0
        if side=='sell':
            raw=data.get('quantity')
            if not isinstance(raw,str) or not re.fullmatch(r'\d{1,12}(?:\.\d{1,8})?',raw):raise RuleError('賣出份額最多八位小數。')
            units=int(decimal(raw)*SCALE)
        if side=='cover':
            position_id=data.get('position_id')
            if type(position_id) is not int or position_id<1:raise RuleError('做空倉位編號無效。')
        # Keep original spot fingerprints compatible with already saved receipts.
        intent=[action,symbol,side,budget,units]
        if side=='cover':intent.append(position_id)
        fingerprint=json.dumps(intent,separators=(',',':'))
    elif action=='cancel':
        oid=data.get('order_id')
        if type(oid) is not int or oid<1:raise RuleError('委託編號無效。')
        fingerprint=json.dumps([action,oid])
    else:raise RuleError('未知交易操作。')
    old=db.execute('SELECT * FROM market_operations WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise member_accounts.AccountError('相同回執已用於其他交易。',409,'operation_conflict')
        return {**json.loads(old['result']),'replayed':True}
    if action=='order' and side in ('short','cover'):
        pause=db.execute("SELECT value FROM settings WHERE key='deploy_pause_until'").fetchone()
        if pause and float(pause[0])>clock:raise member_accounts.AccountError('版本更新中，稍後確認原委託即可；尚未保留新點數。',503,'deployment_pending')
    db.execute('SAVEPOINT market_operation')
    try:
        if action=='cancel':
            row=db.execute('SELECT * FROM market_orders WHERE id=? AND user_id=?',(oid,uid)).fetchone()
            if not row:raise RuleError('找不到這筆委託。')
            if row['status']!='pending':raise RuleError('這筆委託已結束，請查看成交紀錄。')
            cancel(db,row,clock,'cancelled','自行取消')
        else:
            q=db.execute(QUOTE_SQL+' WHERE q.symbol=?',(symbol,)).fetchone()
            if not quote_ready(q,clock):raise RuleError('行情未就緒或已過期，暫停新委託。')
            if side=='sell':
                p=db.execute('SELECT units FROM market_positions WHERE user_id=? AND symbol=?',(uid,symbol)).fetchone()
                held=db.execute("SELECT COALESCE(sum(units),0) FROM market_orders WHERE user_id=? AND symbol=? AND status='pending' AND side='sell'",(uid,symbol)).fetchone()[0]
                if not p or units>p[0]-held:raise RuleError('可賣出份額不足，部分份額可能已有委託。')
                if value_points(units,execution_price(q,'sell'))<1:raise RuleError('賣出市值至少需要 1 點。')
            elif side=='cover':
                position=db.execute("SELECT * FROM market_shorts WHERE id=? AND user_id=? AND symbol=? AND status='open'",(position_id,uid,symbol)).fetchone()
                if not position:raise RuleError('找不到可買回的做空倉位。')
                if db.execute("SELECT 1 FROM market_orders WHERE position_id=? AND side='cover' AND status='pending'",(position_id,)).fetchone():raise RuleError('這筆做空已在等待買回，不可重複平倉。')
                units=position['units']
            elif side=='short':
                if db.execute("SELECT count(*) FROM market_shorts WHERE user_id=? AND status='open'",(uid,)).fetchone()[0]+db.execute("SELECT count(*) FROM market_orders WHERE user_id=? AND side='short' AND status='pending'",(uid,)).fetchone()[0]>=20:raise RuleError('最多同時保留 20 筆做空倉位。')
            elif units_for_budget(budget,execution_price(q,'buy'))<1:raise RuleError('買入點數不足最小份額。')
            if db.execute("SELECT count(*) FROM market_orders WHERE user_id=? AND status='pending'",(uid,)).fetchone()[0]>=20:raise RuleError('最多同時保留 20 筆委託，請先取消部分委託。')
            oid=db.execute("INSERT INTO market_orders(user_id,symbol,side,budget,units,status,submitted_at,expires_at,position_id) VALUES(?,?,?,?,?,'pending',?,?,?)",(uid,symbol,side,budget,units,clock,clock+PENDING_SECONDS[market_catalog.group(symbol)],position_id)).lastrowid
            remember_order_quote(db,'spot',oid,q)
            if side in ('buy','short'):wallet.transfer(db,uid,-budget,'market_reserve','market:reserve:'+str(oid),clock)
        result=dict(ok=True,order_id=oid,action=action,replayed=False)
        db.execute('INSERT INTO market_operations VALUES(?,?,?,?)',(uid,op,fingerprint,json.dumps(result)))
        db.execute('RELEASE SAVEPOINT market_operation');return result
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT market_operation');db.execute('RELEASE SAVEPOINT market_operation');raise


def wealth_delta(db,uid,amount,clock):
    if not amount:return
    # Aggregate marks into an hourly point, rather than one unbounded ledger row
    # per quote tick. Investment price changes are neither external cash flow
    # nor casino game wins, so both counters stay zero.
    key='market:value:'+str(int(clock)//3600)
    db.execute("INSERT INTO wealth_events(user_id,amount,game_delta,flow_delta,kind,event_key,created_at) VALUES(?,?,0,0,'market_value',?,?) ON CONFLICT(user_id,event_key) DO UPDATE SET amount=amount+excluded.amount",(uid,amount,key,clock))


def cancel(db,order,clock,status,reason):
    import wallet
    if order['side'] in ('buy','short'):wallet.transfer(db,order['user_id'],order['budget'],'market_refund','market:refund:'+str(order['id']),clock)
    db.execute('UPDATE market_orders SET status=?,reason=? WHERE id=?',(status,reason,order['id']))


def settle(db,clock):
    import wallet
    changed=False
    quotes={r['symbol']:dict(r) for r in db.execute(QUOTE_SQL)}
    for position in db.execute("SELECT * FROM market_shorts WHERE status='open'").fetchall():
        q=quotes.get(position['symbol'])
        if quote_ready(q,clock) and short_value(position,q['ask'])==0:
            close_short(db,position,q,clock,liquidated=True);changed=True
    for o in db.execute("SELECT * FROM market_orders WHERE status='pending' ORDER BY id").fetchall():
        if clock>=o['expires_at']:
            cancel(db,o,clock,'expired','等候新報價逾時，已解除保留');changed=True;continue
        # A blocked/deleted account cannot have a previously queued order execute.
        try:member_accounts.require_active(db,o['user_id'])
        except member_accounts.AccountError:
            cancel(db,o,clock,'cancelled','帳號已停用');changed=True;continue
        q=quotes.get(o['symbol'])
        if not quote_after_order(db,'spot',o,q,clock):continue
        if o['side']=='short':
            price=Decimal(execution_price(q,'short'));units=units_for_budget(o['budget'],price)
            proceeds=value_points(units,price)
            if units<1 or units>10**14 or proceeds<1:
                cancel(db,o,clock,'cancelled','新報價無法建立允許範圍內的做空倉位');changed=True;continue
            pid=db.execute("INSERT INTO market_shorts(user_id,symbol,units,margin,entry_points,entry_price,opened_at,entry_asof,status) VALUES(?,?,?,?,?,?,?,?,'open')",(o['user_id'],o['symbol'],units,o['budget'],proceeds,str(price),clock,q['asof'])).lastrowid
            position=db.execute('SELECT * FROM market_shorts WHERE id=?',(pid,)).fetchone()
            wealth_delta(db,o['user_id'],short_value(position,q['ask'])-o['budget'],clock)
            db.execute("UPDATE market_orders SET status='filled',filled_at=?,fill_asof=?,fill_price=?,filled_units=?,points=?,profit=0,position_id=? WHERE id=?",(clock,q['asof'],str(price),units,proceeds,pid,o['id']))
            if short_value(position,q['ask'])==0:close_short(db,position,q,clock,liquidated=True)
            changed=True;continue
        if o['side']=='cover':
            position=db.execute("SELECT * FROM market_shorts WHERE id=? AND user_id=? AND status='open'",(o['position_id'],o['user_id'])).fetchone()
            if not position:cancel(db,o,clock,'cancelled','倉位已平倉或已強制平倉');changed=True;continue
            returned=close_short(db,position,q,clock)
            db.execute("UPDATE market_orders SET status='filled',filled_at=?,fill_asof=?,fill_price=?,filled_units=?,points=?,profit=? WHERE id=?",(clock,q['asof'],q['ask'],position['units'],returned,returned-position['margin'],o['id']))
            changed=True;continue
        price=Decimal(execution_price(q,o['side']))
        p=db.execute('SELECT units,cost FROM market_positions WHERE user_id=? AND symbol=?',(o['user_id'],o['symbol'])).fetchone()
        old_units,old_cost=(p[0],p[1]) if p else (0,0)
        if o['side']=='buy':
            units=units_for_budget(o['budget'],price)
            if units<1:cancel(db,o,clock,'cancelled','新報價不足最小份額');changed=True;continue
            points=value_points(units,price,up=True)
            new_units,new_cost=old_units+units,old_cost+points;profit=0
            if new_units>10**14 or new_cost>10**12:
                cancel(db,o,clock,'cancelled','持倉已達上限');changed=True;continue
            wallet.transfer(db,o['user_id'],o['budget']-points,'market_refund','market:change:'+str(o['id']),clock)
        else:
            units=o['units'];points=value_points(units,price)
            if points>10**12:
                cancel(db,o,clock,'cancelled','成交市值超過單筆上限');changed=True;continue
            if points<1:cancel(db,o,clock,'cancelled','新報價低於最低賣出市值');changed=True;continue
            if units>old_units:raise RuntimeError('Market reserved units invariant')
            cost=old_cost if units==old_units else old_cost*units//old_units
            new_units,new_cost=old_units-units,old_cost-cost;profit=points-cost
            wallet.transfer(db,o['user_id'],points,'market_sale','market:sale:'+str(o['id']),clock)
        before_mark=value_points(old_units,q['price'])
        after_mark=value_points(new_units,q['price'])
        wealth_delta(db,o['user_id'],after_mark-before_mark+(-points if o['side']=='buy' else points),clock)
        db.execute('INSERT INTO market_positions VALUES(?,?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET units=excluded.units,cost=excluded.cost',(o['user_id'],o['symbol'],new_units,new_cost))
        db.execute("UPDATE market_orders SET status='filled',filled_at=?,fill_asof=?,fill_price=?,filled_units=?,points=?,profit=? WHERE id=?",(clock,q['asof'],str(price),units,points,profit,o['id']))
        changed=True
    if db.execute("SELECT 1 FROM market_contracts WHERE status='open' UNION ALL SELECT 1 FROM market_contract_orders WHERE status='pending' LIMIT 1").fetchone():
        before=market_contracts.assets(db,quotes);cash={r[0]:r[1] for r in db.execute('SELECT user_id,balance FROM wallets')}
        changed=market_contracts.settle(db,clock,quotes) or changed
        after=market_contracts.assets(db,quotes);cash_after={r[0]:r[1] for r in db.execute('SELECT user_id,balance FROM wallets')}
        for uid in before.keys()|after.keys():wealth_delta(db,uid,after.get(uid,0)-before.get(uid,0)+cash_after.get(uid,0)-cash.get(uid,0),clock)
    return changed


def apply_quotes(db,rows,clock):
    """Validated provider observations; reject regressions and implausible jumps.

    A >35% stock move may be a split/corporate action. Freeze instead of silently
    repricing portfolios or granting old share counts a split-sized windfall.
    """
    changed=False
    before_contracts=market_contracts.assets(db,{r['symbol']:dict(r) for r in db.execute('SELECT * FROM market_quotes')})
    for r in rows:
        symbol=r['symbol']
        if not market_catalog.get(db,symbol):raise RuleError('未知行情標的。')
        price,bid,ask=(decimal(r[k]) for k in ('price','bid','ask'))
        native,fx=(decimal(r[k]) for k in ('native','fx'))
        if market_catalog.group(symbol)=='US':bid=ask=price
        if bid>ask or r['asof']>clock+5 or r['asof']<clock-8*86400:continue
        old=db.execute('SELECT * FROM market_quotes WHERE symbol=?',(symbol,)).fetchone()
        if old and r['asof']<old['asof']:continue
        halted=int(bool(old and (old['halted'] or market_catalog.group(symbol)!='CC' and abs(price/Decimal(old['price'])-1)>Decimal('.35'))))
        if halted and old:
            market_review.observe(db,old,{**r,'native':str(native),'fx':str(fx)},clock)
            db.execute('UPDATE market_quotes SET halted=1,checked_at=? WHERE symbol=?',(clock,symbol));changed=True;continue
        token=hashlib.sha256(json.dumps([symbol,str(price),str(bid),str(ask),r['asof'],r['fx_at']]).encode()).hexdigest()[:24]
        db.execute("INSERT INTO market_quotes(symbol,price,bid,ask,native,fx,asof,fx_at,checked_at,source,token,halted) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET price=excluded.price,bid=excluded.bid,ask=excluded.ask,native=excluded.native,fx=excluded.fx,asof=excluded.asof,fx_at=excluded.fx_at,checked_at=excluded.checked_at,source=excluded.source,token=excluded.token,halted=excluded.halted",
            (symbol,str(price),str(bid),str(ask),str(decimal(r['native'])),str(decimal(r['fx'])),r['asof'],r['fx_at'],clock,r['source'],token,halted))
        if r['source']==TV_SOURCE:
            db.execute('INSERT INTO market_tv_meta VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET delay_seconds=excluded.delay_seconds,feed_session=excluded.feed_session',(symbol,r['delay_seconds'],r['feed_session']))
            market_charts.apply(db,r.get('candles',[]),clock)
        db.execute('DELETE FROM market_quote_health WHERE symbol=?',(symbol,))
        if not halted:
            for p in db.execute('SELECT user_id,units,cost FROM market_positions WHERE symbol=? AND units>0',(symbol,)).fetchall():
                before=value_points(p['units'],old['price']) if old else p['cost']
                after=value_points(p['units'],price)
                wealth_delta(db,p['user_id'],after-before,clock)
            db.execute('INSERT OR REPLACE INTO market_prices VALUES(?,?,?)',(symbol,r['asof'],str(price)))
            market_charts.snapshot(db,r)
            for position in db.execute("SELECT * FROM market_shorts WHERE symbol=? AND status='open'",(symbol,)).fetchall():
                before=short_value(position,old['ask'] if old else None)
                after=short_value(position,str(ask))
                wealth_delta(db,position['user_id'],after-before,clock)
            keep=7*86400 if market_catalog.group(symbol)=='CC' else 180*86400
            db.execute('DELETE FROM market_prices WHERE symbol=? AND asof<?',(symbol,clock-keep))
        changed=True
    after_contracts=market_contracts.assets(db,{r['symbol']:dict(r) for r in db.execute('SELECT * FROM market_quotes')})
    for uid in before_contracts.keys()|after_contracts.keys():wealth_delta(db,uid,after_contracts.get(uid,0)-before_contracts.get(uid,0),clock)
    return changed



def short_value(position,ask):
    if ask is None:return position['margin']
    cover=value_points(position['units'],ask,up=True)
    return max(0,position['margin']+position['entry_points']-cover)


def close_short(db,position,q,clock,*,liquidated=False):
    import wallet
    value=0 if liquidated else short_value(position,q['ask'])
    wallet.transfer(db,position['user_id'],value,'market_sale','market:cover:'+str(position['id']),clock)
    db.execute("UPDATE market_shorts SET status=?,closed_at=?,exit_price=?,profit=?,returned=? WHERE id=? AND status='open'",('liquidated' if liquidated else 'closed',clock,q['ask'],value-position['margin'],value,position['id']))
    if liquidated:
        db.execute("UPDATE market_orders SET status='cancelled',reason='倉位已強制平倉，免補繳額外點數' WHERE position_id=? AND side='cover' AND status='pending'",(position['id'],))
    return value


PERIODS={'15m':900,'1h':3600,'1d':86400,'7d':7*86400,'30d':30*86400,'180d':180*86400}


def chart(db,symbol,period,clock,interval=None):
    if not market_catalog.get(db,symbol) or period not in PERIODS:raise RuleError('價格圖標的或時間範圍無效。')
    seconds=PERIODS[period]
    quote=db.execute('SELECT source,asof FROM market_quotes WHERE symbol=?',(symbol,)).fetchone()
    delayed=quote and quote['source']==TV_SOURCE
    if delayed:clock=min(clock,quote['asof'])
    if market_catalog.group(symbol)=='US':
        session=db.execute('SELECT session_start,session_end FROM market_quote_meta WHERE symbol=?',(symbol,)).fetchone()
        if not session or not session['session_start']<=clock<session['session_end']:
            # At weekends/pre-open, a short-range view ends at the last real
            # observation instead of showing a blank wall-clock window.
            latest=db.execute('SELECT max(at) FROM (SELECT max(asof) AS at FROM market_prices WHERE symbol=? AND asof<=? UNION ALL SELECT max(asof) AS at FROM market_history WHERE symbol=? AND asof<=?)',(symbol,clock,symbol,clock)).fetchone()[0]
            if latest is not None:clock=latest
    start=clock-seconds;bucket=max(1,seconds/240)
    # Historical minute closes are chart-only; settlement never reads this table.
    source='SELECT asof,price FROM market_prices WHERE symbol=:symbol AND asof>=:start AND asof<=:clock'
    if market_catalog.group(symbol)=='US':
        source+=' UNION ALL SELECT h.asof,h.price FROM market_history h WHERE h.symbol=:symbol AND h.asof>=:start AND h.asof<=:clock AND NOT EXISTS(SELECT 1 FROM market_prices p WHERE p.symbol=h.symbol AND p.asof=h.asof)'
    rows=db.execute('WITH samples AS ('+source+''') SELECT p.asof,p.price FROM samples p JOIN (
      SELECT max(asof) AS asof FROM samples WHERE asof>=:start AND asof<=:clock
      GROUP BY CAST((asof-:start)/:bucket AS INTEGER)) b ON p.asof=b.asof ORDER BY p.asof''',dict(symbol=symbol,start=start,clock=clock,bucket=bucket)).fetchall()
    # Preserve source timestamps and observed prices; never synthesize tick/K data.
    model=dict(symbol=symbol,period=period,from_at=start,to_at=clock,
      points=[dict(at=r[0],price=r[1]) for r in rows],currency='TWD',max_points=241,gap_seconds=max(90,bucket*2.5),
      retention_days=7 if market_catalog.group(symbol)=='CC' else 180,
      basis='TradingView 延遲觀測；時間軸截至最後來源時間，分鐘線逐步累積，缺樣不補造。既有歷史保留原來源，歷史線不參與成交。' if delayed else 'Yahoo 分鐘收盤線＋成交參考快照；分鐘時間為區間起點，美元依匯入時匯率換算點數。歷史線不參與成交。' if market_catalog.group(symbol)=='US' else '')

    return market_charts.enrich(db,model,symbol,clock,interval or '1m')
