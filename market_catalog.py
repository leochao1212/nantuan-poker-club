"""Verified, bounded instrument discovery. Search network work never holds SQLite."""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import re
import time
import urllib.parse

_POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='market-search')
_LOCK=Lock()
_SEARCH={}
_INDEX={}
_INDEX_AT={}
_BUDGET={}
_INDEX_LOCKS={g:Lock() for g in ('TW','CC')}
_GROUPS={'TW','US','CC'}
_US_EXCHANGES={'NMS','NGM','NCM','NYQ','ASE','PCX','BTS','NYS','NAS','BATS'}


def initialize(db,seeds):
    db.executescript('''CREATE TABLE IF NOT EXISTS market_instruments(
      symbol TEXT PRIMARY KEY,name TEXT NOT NULL,market TEXT NOT NULL,currency TEXT NOT NULL,
      exchange TEXT NOT NULL,feed TEXT NOT NULL,kind TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS market_watch(user_id INTEGER NOT NULL REFERENCES users(id),
      symbol TEXT NOT NULL REFERENCES market_instruments(symbol),seen_at REAL NOT NULL,
      PRIMARY KEY(user_id,symbol));''')
    for s,name,group,currency in seeds:
        code=s.split(':')[1];feed={'BTC':'XXBTZUSD','ETH':'XETHZUSD','SOL':'SOLUSD'}.get(code,code)
        db.execute('INSERT OR IGNORE INTO market_instruments VALUES(?,?,?,?,?,?,?)',(s,name,group,currency,'tse' if group=='TW' else 'US' if group=='US' else 'Kraken',feed,'EQUITY' if group!='CC' else 'CRYPTO'))


def get(db,symbol):
    if not isinstance(symbol,str):return None
    r=db.execute('SELECT * FROM market_instruments WHERE symbol=?',(symbol,)).fetchone()
    return dict(r) if r else None


def group(symbol):
    return symbol.split(':',1)[0]


def visible(db,uid,seeds,selected=None):
    codes={s[0] for s in seeds}
    codes.update(r[0] for r in db.execute('SELECT symbol FROM market_watch WHERE user_id=? ORDER BY seen_at DESC LIMIT 20',(uid,)))
    for table,where in [('market_positions','units>0'),('market_shorts',"status='open'"),('market_orders',"status='pending'"),('market_contracts',"status='open'"),('market_contract_orders',"status='pending'")]:
        codes.update(r[0] for r in db.execute('SELECT DISTINCT symbol FROM '+table+' WHERE user_id=? AND '+where,(uid,)))
    if selected and get(db,selected):codes.add(selected)
    rows=[dict(r) for r in db.execute('SELECT * FROM market_instruments WHERE symbol IN ('+','.join('?' for _ in codes)+')',tuple(codes))]
    order={s[0]:n for n,s in enumerate(seeds)}
    return sorted(rows,key=lambda r:(order.get(r['symbol'],len(order)),r['symbol']))



def active(db,clock,seeds):
    # Open exposure is always monitored, even if its owner closes the webpage.
    codes={s[0] for s in seeds}
    codes.update(r[0] for r in db.execute('SELECT DISTINCT symbol FROM market_watch WHERE seen_at>?',(clock-120,)))
    for table,where in [('market_positions','units>0'),('market_shorts',"status='open'"),('market_orders',"status='pending'"),('market_contracts',"status='open'"),('market_contract_orders',"status='pending'")]:
        codes.update(r[0] for r in db.execute('SELECT DISTINCT symbol FROM '+table+' WHERE '+where))
    return {r['symbol']:dict(r) for r in db.execute('SELECT * FROM market_instruments WHERE symbol IN ('+','.join('?' for _ in codes)+')',tuple(codes))}


def _fetch(url):
    import market_data
    return market_data.fetch_json(url,limit=8_000_000)


def _index_fetch(group):
    now=time.monotonic()
    with _LOCK:
        if group in _INDEX and now-_INDEX_AT.get(group,0)<86400:return _INDEX[group]
    rows={}
    if group=='TW':
        for exchange,url,code_key,name_key in [('tse','https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL','Code','Name'),('otc','https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes','SecuritiesCompanyCode','CompanyName')]:
            for r in _fetch(url):
                code=str(r.get(code_key,''));name=r.get(name_key)
                if not re.fullmatch(r'(?:[1-9]\d{3}|00[A-Z0-9]{2,4})',code) or not isinstance(name,str) or not name:continue
                s='TW:'+code;rows[s]=dict(symbol=s,name=name[:100],market='TW',currency='TWD',exchange=exchange,feed=code,kind='ETF' if code.startswith('00') else 'EQUITY')
    elif group=='CC':
        data=_fetch('https://api.kraken.com/0/public/AssetPairs')
        if data.get('error'):raise ValueError('Pair index unavailable')
        for feed,r in data['result'].items():
            ws=r.get('wsname','').split('/')
            if len(ws)!=2 or ws[1]!='USD' or r.get('status')!='online':continue
            code={'XBT':'BTC','XDG':'DOGE'}.get(ws[0],ws[0])
            if code in {'USD','EUR','GBP','AUD','CAD','CHF','JPY','CNH'}:continue
            if not re.fullmatch(r'[A-Z0-9]{2,16}',code) or not re.fullmatch(r'[A-Z0-9]{3,24}',r.get('altname','')):continue
            s='CC:'+code;rows[s]=dict(symbol=s,name=code,market='CC',currency='USD',exchange='Kraken',feed=feed,kind='CRYPTO')
    if not rows:raise ValueError('Instrument index unavailable')
    with _LOCK:_INDEX[group]=rows;_INDEX_AT[group]=now
    return rows


def index(group):
    with _INDEX_LOCKS[group]:return _index_fetch(group)


def _lookup(group,query):
    if group=='US':
        url='https://query1.finance.yahoo.com/v1/finance/search?'+urllib.parse.urlencode(dict(q=query,quotesCount=15,newsCount=0))
        rows=[]
        for r in _fetch(url).get('quotes',[]):
            code=r.get('symbol','');name=r.get('shortname') or r.get('longname')
            if r.get('exchange') not in _US_EXCHANGES or r.get('quoteType') not in ('EQUITY','ETF') or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',code) or not isinstance(name,str):continue
            rows.append(dict(symbol='US:'+code,name=name[:100],market='US',currency='USD',exchange=r['exchange'],feed=code,kind=r['quoteType']))
        return rows[:12]
    rows=list(index(group).values());q=query.casefold()
    rows=[r for r in rows if q in (r['symbol']+' '+r['name']).casefold()]
    return sorted(rows,key=lambda r:(r['symbol'].split(':')[1].casefold()!=q,not r['name'].casefold().startswith(q),r['symbol']))[:20]


def search(group,query,uid=0):
    import market
    if group not in _GROUPS or not isinstance(query,str) or not 1<=len(query.strip())<=60 or any(ord(c)<32 for c in query):raise market.RuleError('請輸入股票名稱或代碼（最多 60 字）。')
    query=query.strip();key=(group,query.casefold());now=time.monotonic()
    with _LOCK:
        entry=_SEARCH.get(key)
        if not entry or now-entry['at']>120:
            for old in [u for u,v in _BUDGET.items() if not v or now-v[-1]>=60]:del _BUDGET[old]
            budget=[t for t in _BUDGET.get(uid,[]) if now-t<60]
            if len(budget)>=30:return dict(status='busy',results=[],message='搜尋過於頻繁，稍後再試。')
            if uid not in _BUDGET and len(_BUDGET)>=4096:return dict(status='busy',results=[],message='搜尋忙碌，請稍後再試。')
            _BUDGET[uid]=[*budget,now]
            # Admission is bounded before work is queued, including distinct queries.
            if sum(not e['future'].done() for e in _SEARCH.values())>=4:return dict(status='busy',results=[],message='搜尋忙碌，請稍後再試。')
            if len(_SEARCH)>=128:
                done=[k for k,e in _SEARCH.items() if e['future'].done()]
                if not done:return dict(status='busy',results=[],message='搜尋忙碌，請稍後再試。')
                del _SEARCH[min(done,key=lambda k:_SEARCH[k]['at'])]
            entry=dict(at=now,future=_POOL.submit(_lookup,group,query));_SEARCH[key]=entry
        f=entry['future']
        if not f.done():return dict(status='pending',results=[],message='正在搜尋行情來源…')
        try:return dict(status='ready',results=f.result(),message='')
        except Exception:return dict(status='unavailable',results=[],message='行情搜尋暫時無法使用，請稍後再試。')


def watch(db,uid,symbol,clock,wake=True):
    import market,member_accounts
    member_accounts.require_active(db,uid)
    if not isinstance(symbol,str):raise market.RuleError('交易標的無效。')
    item=get(db,symbol)
    if item is None:
        with _LOCK:
            candidates=[r for items in _INDEX.values() for r in items.values() if r['symbol']==symbol]
            for e in _SEARCH.values():
                if e['future'].done():
                    try:candidates.extend(r for r in e['future'].result() if r['symbol']==symbol)
                    except Exception:pass
        if not candidates:raise market.RuleError('請先搜尋並選擇有效標的。')
        item=candidates[0]
        db.execute('INSERT OR IGNORE INTO market_instruments VALUES(?,?,?,?,?,?,?)',tuple(item[k] for k in ('symbol','name','market','currency','exchange','feed','kind')))
    if not db.execute('SELECT 1 FROM market_watch WHERE user_id=? AND symbol=?',(uid,symbol)).fetchone():
        # Watching does not buy; older unheld watches can be replaced freely.
        old=db.execute('SELECT symbol FROM market_watch WHERE user_id=? ORDER BY seen_at DESC LIMIT -1 OFFSET 19',(uid,)).fetchall()
        db.executemany('DELETE FROM market_watch WHERE user_id=? AND symbol=?',[(uid,r[0]) for r in old])
    db.execute('INSERT INTO market_watch VALUES(?,?,?) ON CONFLICT(user_id,symbol) DO UPDATE SET seen_at=excluded.seen_at',(uid,symbol,clock))
    if wake:
        db.execute("UPDATE market_providers SET next_at=min(next_at,?) WHERE name IN (?, 'BARS') AND status IN ('ok','closed')",(clock,item['market']))
    return item
