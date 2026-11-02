"""Taiwan ROD sessions. Official calendars; no network in order transactions."""
from datetime import datetime,timedelta,timezone,date
import json
TZ=timezone(timedelta(hours=8))
SEED_CLOSED=['2026-01-01', '2026-02-12', '2026-02-13', '2026-02-15', '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20', '2026-02-27', '2026-02-28', '2026-04-03', '2026-04-04', '2026-04-05', '2026-04-06', '2026-05-01', '2026-06-19', '2026-09-25', '2026-09-28', '2026-10-09', '2026-10-10', '2026-10-25', '2026-10-26', '2026-12-25']


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS market_tw_calendar(year INTEGER PRIMARY KEY,closed TEXT NOT NULL)')
    db.execute('INSERT OR IGNORE INTO market_tw_calendar VALUES(2026,?)',(json.dumps(SEED_CLOSED),))
    db.execute('CREATE TABLE IF NOT EXISTS market_order_terms(kind TEXT NOT NULL,order_id INTEGER NOT NULL,limit_native TEXT,session_start REAL NOT NULL,session_end REAL NOT NULL,PRIMARY KEY(kind,order_id))')


def parse_calendar(data,year):
    if not isinstance(data,dict) or data.get('stat')!='ok' or data.get('queryYear')!=year or not isinstance(data.get('data'),list) or not data['data']:raise ValueError('Calendar unavailable')
    closed=[]
    for row in data['data']:
        if not isinstance(row,list) or len(row)<3 or date.fromisoformat(row[0]).year!=year:raise ValueError('Invalid calendar')
        if '開始交易' not in row[1] and '最後交易' not in row[1]:closed.append(row[0])
    return closed


def trading_day(db,day):
    import market
    row=db.execute('SELECT closed FROM market_tw_calendar WHERE year=?',(day.year,)).fetchone()
    if not row:raise market.RuleError('該年度台股交易日曆尚未確認，暫不能預約；請稍後再試。')
    return day.weekday()<5 and day.isoformat() not in json.loads(row[0])


def window(db,clock):
    import market
    local=datetime.fromtimestamp(clock,TZ);day=local.date()
    if local.hour*60+local.minute>=810:day+=timedelta(days=1)
    for _ in range(32):
        if trading_day(db,day):
            start=datetime.combine(day,datetime.min.time(),TZ)+timedelta(hours=9)
            return start.timestamp(),(start+timedelta(hours=4,minutes=30)).timestamp()
        day+=timedelta(days=1)
    raise market.RuleError('無法確認下一交易日。')


def terms(db,clock,limit):
    import market
    start,end=window(db,clock)
    if limit is None and not start<=clock<end-300:raise market.RuleError('台股休市、盤前及收盤集合競價時段僅接受限價 ROD，請指定限價。')
    return (str(market.decimal(limit)) if limit is not None else None,start,end)


def save(db,kind,oid,values):
    db.execute('INSERT INTO market_order_terms VALUES(?,?,?,?,?)',(kind,oid,*values))


def public(db,kind,oid):
    row=db.execute('SELECT * FROM market_order_terms WHERE kind=? AND order_id=?',(kind,oid)).fetchone()
    return dict(row) if row else None


def eligible(db,kind,order,q,clock):
    import market
    term=public(db,kind,order['id'])
    if not term:return True  # Existing orders retain their original contract.
    if not term['session_start']<=clock<term['session_end'] or not term['session_start']<=q['asof']<term['session_end']:return False
    if not trading_day(db,datetime.fromtimestamp(clock,TZ).date()):return False
    if term['limit_native'] is None:return True
    buying=order['side'] in ('buy','cover') if kind=='spot' else (order['direction']=='long')==(order['action']=='open')
    price=market.decimal(q['native']);limit=market.decimal(term['limit_native'])
    return price<=limit if buying else price>=limit



def confirm_window(data,values):
    import market
    if data.get('expected_session_end') is not None and (type(data['expected_session_end']) not in (int,float) or data['expected_session_end']!=values[2]):
        raise market.RuleError('指定交易日已切換，請更新畫面並重新確認委託。')
