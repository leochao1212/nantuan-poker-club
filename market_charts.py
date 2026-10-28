"""Native-currency observations and verified OHLC bars, never execution prices."""
from decimal import Decimal
import math


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS market_observations(symbol TEXT NOT NULL,asof REAL NOT NULL,
      native TEXT NOT NULL,fx TEXT NOT NULL,fx_at REAL NOT NULL,PRIMARY KEY(symbol,asof));
    CREATE TABLE IF NOT EXISTS market_candles(symbol TEXT NOT NULL,asof REAL NOT NULL,
      open TEXT NOT NULL,high TEXT NOT NULL,low TEXT NOT NULL,close TEXT NOT NULL,
      volume TEXT,complete INTEGER NOT NULL,source TEXT NOT NULL,PRIMARY KEY(symbol,asof));''')


def bar(symbol,at,o,h,l,c,volume,clock,source):
    import market
    if type(at) not in (int,float) or not math.isfinite(at) or not clock-8*86400<=at<=clock or at%60!=0:return None
    try:
        o,h,l,c=[market.decimal(v) for v in (o,h,l,c)]
        if h<max(o,c) or l>min(o,c) or h<l:return None
        if volume is not None:
            v=Decimal(str(volume))
            if not v.is_finite() or v<0:return None
            volume=str(v)
    except (market.RuleError,ValueError,TypeError):return None
    return (symbol,at,str(o),str(h),str(l),str(c),volume,int(at+60<=clock),source)


def yahoo(data,symbol,clock):
    import market_catalog
    group=market_catalog.group(symbol);currency='TWD' if group=='TW' else 'USD'
    result=data['chart']['result'][0];meta=result['meta']
    raw=symbol.split(':')[1]
    if meta.get('currency')!=currency or meta.get('instrumentType') not in ('EQUITY','ETF') or meta.get('dataGranularity')!='1m' or meta.get('symbol') not in ({raw+'.TW',raw+'.TWO'} if group=='TW' else {raw}):raise ValueError('Unexpected candle instrument')
    times=result.get('timestamp',[]);q=result['indicators']['quote'][0]
    if not isinstance(times,list) or len(times)>1500:return []
    rows=[];seen=set();duplicates={t for t in times if times.count(t)>1}
    for n,at in enumerate(times):
        if at in seen or at in duplicates:continue
        seen.add(at)
        try:r=bar(symbol,at,*(q[k][n] for k in ('open','high','low','close')),q.get('volume',[None]*len(times))[n],clock,'Yahoo 原始分鐘 OHLC')
        except (IndexError,KeyError,TypeError):continue
        if r:rows.append(r)
    return rows


def apply(db,rows,clock):
    db.executemany('''INSERT INTO market_candles VALUES(?,?,?,?,?,?,?,?,?)
      ON CONFLICT(symbol,asof) DO UPDATE SET open=excluded.open,high=excluded.high,low=excluded.low,
      close=excluded.close,volume=excluded.volume,complete=excluded.complete,source=excluded.source
      WHERE market_candles.complete=0''',rows)
    db.execute('DELETE FROM market_candles WHERE asof<?',(clock-8*86400,))
    db.execute('DELETE FROM market_observations WHERE asof<?',(clock-8*86400,))


def snapshot(db,row):
    db.execute('INSERT OR REPLACE INTO market_observations VALUES(?,?,?,?,?)',(row['symbol'],row['asof'],row['native'],row['fx'],row['fx_at']))


def enrich(db,model,symbol,clock,interval):
    import market_catalog
    if interval not in ('1m','5m','15m','1h','1d'):interval='1m'
    seconds={'1m':60,'5m':300,'15m':900,'1h':3600,'1d':86400}[interval]
    currency='TWD' if market_catalog.group(symbol)=='TW' else 'USD'
    # Native observations preserve their original currency, never divide old TWD
    # marks by today's FX. Legacy marks without native provenance are omitted.
    bucket=max(1,(model['to_at']-model['from_at'])/240)
    samples=db.execute('''WITH samples AS (
      SELECT asof,native FROM market_observations WHERE symbol=:symbol AND asof>=:start AND asof<=:end
      UNION ALL SELECT h.asof,h.native FROM market_history h WHERE h.symbol=:symbol AND h.asof>=:start AND h.asof<=:end
      AND NOT EXISTS(SELECT 1 FROM market_observations p WHERE p.symbol=h.symbol AND p.asof=h.asof))
      SELECT p.asof,p.native FROM samples p JOIN (
      SELECT max(asof) AS asof FROM samples GROUP BY CAST((asof-:start)/:bucket AS INTEGER)) b ON b.asof=p.asof ORDER BY p.asof''',
      dict(symbol=symbol,start=model['from_at'],end=model['to_at'],bucket=bucket)).fetchall()
    last={n:dict(at=r['asof'],price=r['native']) for n,r in enumerate(samples)}
    # Limit raw bars before aggregation by using the requested interval's last
    # 500 groups; each group is composed exclusively of source minute candles.
    # Include the entire first bucket even when the visible range begins in
    # its middle. Otherwise a 1h bar in a 15m view can have the wrong open.
    start=int(max(model['from_at'],model['to_at']-seconds*500)//seconds)*seconds
    raw=db.execute('SELECT * FROM market_candles WHERE symbol=? AND asof>=? AND asof<=? ORDER BY asof',(symbol,start,model['to_at'])).fetchall()
    groups={}
    for r in raw:
        at=int(r['asof']//seconds)*seconds
        if at not in groups:groups[at]=dict(time=at,open=r['open'],high=r['high'],low=r['low'],close=r['close'],volume=r['volume'],complete=bool(r['complete']),source=r['source'],first=r['asof'],last=r['asof'],observed_minutes=1,contiguous=True)
        else:
            b=groups[at];b['high']=str(max(Decimal(b['high']),Decimal(r['high'])));b['low']=str(min(Decimal(b['low']),Decimal(r['low'])));b['close']=r['close'];b['complete']=b['complete'] and bool(r['complete'])
            b['contiguous']=b['contiguous'] and r['asof']==b['last']+60;b['last']=r['asof'];b['observed_minutes']+=1
            b['volume']=str(Decimal(b['volume'])+Decimal(r['volume'])) if b['volume'] is not None and r['volume'] is not None else None
    candles=list(groups.values())[-500:]
    for b in candles:
        source_complete=b['complete']
        b['covered']=b['first']==b['time'] and b['last']==b['time']+seconds-60 and b['observed_minutes']==seconds//60 and b['contiguous']
        b['complete']=source_complete and b['covered'] and b['time']+seconds<=clock
        b['status']='已收盤' if b['complete'] else '尚未收盤' if not source_complete or b['time']+seconds>clock else '取樣未齊'
        del b['first'],b['last'],b['contiguous']
    model.update(currency=currency,display_points=list(last.values()),candles=candles,interval=interval,
        candle_notice='原始分鐘 OHLC 聚合；缺少分鐘資料會標示「取樣未齊」，不補畫假價格。' if candles else '尚無有效 OHLC，先顯示實際觀測線。',
        basis=('美元行情；錢包、保證金與損益以台幣點數結算。' if currency=='USD' else '台幣行情；點數與台幣 1：1。')+'原始分鐘 K 線與歷史資料不參與成交。')
    return model
