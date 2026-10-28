"""Bounded public quote fetches; never called from request/SQLite write paths."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
import re
import urllib.request
import urllib.parse
import market

TAIPEI=timezone(timedelta(hours=8))
URLS={'TW':'https://mis.twse.com.tw/stock/api/getStockInfo.jsp',
      'CC':'https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD,SOLUSD',
      'FX':'https://open.er-api.com/v6/latest/USD'}
PERIODS={'TW':5,'US':86400,'CC':10,'FX':86400}


def mis_rows(data,clock):
    """Strict per-symbol observations. Missing prices never borrow yesterday's close.

    The source observation time (d/t, cross-checked against tlong), not fetch
    time, determines freshness and next-observation execution eligibility.
    """
    if not isinstance(data,dict) or data.get('rtcode')!='0000' or not isinstance(data.get('msgArray'),list):
        raise ValueError('Invalid MIS response')
    grouped={}
    for row in data['msgArray']:
        if isinstance(row,dict) and isinstance(row.get('c'),str):grouped.setdefault('TW:'+row['c'],[]).append(row)
    rows=[]
    for symbol,item in market.INSTRUMENTS.items():
        if item['market']!='TW' or len(grouped.get(symbol,[]))!=1:continue
        row=grouped[symbol][0]
        try:
            if row.get('ex')!='tse' or not re.fullmatch(r'\d{8}',str(row.get('d',''))) or not re.fullmatch(r'\d{2}:\d{2}:\d{2}',str(row.get('t',''))):continue
            at=datetime.strptime(row['d']+' '+row['t'],'%Y%m%d %H:%M:%S').replace(tzinfo=TAIPEI).timestamp()
            raw=row.get('tlong')
            if not isinstance(raw,str) or not re.fullmatch(r'\d{13}',raw) or abs(int(raw)/1000-at)>1:continue
            if not math.isfinite(at) or not -5<=clock-at<=market.TW_QUOTE_AGE or not market.tw_session(at):continue
            price,bid,ask=(market.decimal(row.get(k,'').split('_')[0]) for k in ('z','b','a'))
            bid_size,ask_size=(market.decimal(row.get(k,'').split('_')[0]) for k in ('g','f'))
            if bid>ask:continue
        except (ValueError,TypeError,AttributeError,OverflowError,market.RuleError):continue
        rows.append(dict(symbol=symbol,price=str(price),bid=str(bid),ask=str(ask),native=str(price),fx='1',asof=at,fx_at=at,source=market.TW_SOURCE))
    return rows


def fetch_json(url):
    request=urllib.request.Request(url,headers={'User-Agent':'NantuanPaperMarket/1.0','Accept':'application/json','Cache-Control':'no-cache'})
    with urllib.request.urlopen(request,timeout=8) as response:
        raw=response.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('Oversized market response')
        return json.loads(raw)


def due(db,clock):
    values={r['name']:r['next_at'] for r in db.execute('SELECT name,next_at FROM market_providers')}
    # Upgrade the old hourly EOD schedule without waiting for its next run.
    tw=db.execute("SELECT source FROM market_quotes WHERE symbol LIKE 'TW:%' LIMIT 1").fetchone()
    if (not tw or tw[0]!=market.TW_SOURCE) and values.get('TW',0)>clock+PERIODS['TW']:values['TW']=0
    return [key for key in ('FX','TW','US','CC') if clock>=values.get(key,0)]


def fx_state(db):
    row=db.execute("SELECT status,last_at FROM market_providers WHERE name='FX'").fetchone()
    if not row:return None
    try:
        value=json.loads(row['status'])
        return dict(rate=str(market.decimal(value['rate'])),asof=value['asof'])
    except (ValueError,KeyError,TypeError,market.RuleError):return None


def read_provider(name,clock,fx):
    """Returns no secrets in status. An absent free US key is an explicit state."""
    if name=='US' and not os.environ.get('POKER_MARKETSTACK_KEY'):
        return [],'missing_key',clock+3600,None
    if name in ('US','CC') and (not fx or not -5<=clock-fx['asof']<=3*86400):
        return [],'fx_unavailable',clock+60,None
    url=URLS.get(name)
    if name=='TW':
        if not market.tw_session(clock):return [],'closed',clock+5,None
        channels='|'.join('tse_'+s.split(':')[1]+'.tw' for s,i in market.INSTRUMENTS.items() if i['market']=='TW')
        url+='?'+urllib.parse.urlencode({'ex_ch':channels,'_':int(clock*1000)})
    if name=='US':
        # Three symbols cost <=93 daily requests/month, within the 100 free quota.
        # Persisted next_at prevents restarts or visitors multiplying requests.
        url='https://api.marketstack.com/v2/eod/latest?'+urllib.parse.urlencode({'access_key':os.environ['POKER_MARKETSTACK_KEY'],'symbols':'AAPL,MSFT,NVDA','limit':'3'})
    data=fetch_json(url)
    if name=='FX':
        if data.get('result')!='success' or data.get('base_code')!='USD':raise ValueError('Invalid FX response')
        result=dict(rate=str(market.decimal(data['rates']['TWD'])),asof=float(data['time_last_update_unix']))
        if not -5<=clock-result['asof']<=3*86400:raise ValueError('Stale FX response')
        return [],json.dumps(result),max(clock+3600,float(data['time_next_update_unix'])),result
    rows=[]
    if name=='TW':
        rows=mis_rows(data,clock)
        return rows,'ok' if len(rows)==sum(i['market']=='TW' for i in market.INSTRUMENTS.values()) else 'partial' if rows else 'missing_data',clock+PERIODS['TW'],None
    elif name=='CC':
        if data.get('error'):raise ValueError('Kraken feed error')
        for key,symbol in [('XXBTZUSD','CC:BTC'),('XETHZUSD','CC:ETH'),('SOLUSD','CC:SOL')]:
            r=data['result'][key];rate=Decimal(fx['rate'])
            native=market.decimal(r['c'][0]);bid=market.decimal(r['b'][0]);ask=market.decimal(r['a'][0])
            rows.append(dict(symbol=symbol,price=str(native*rate),bid=str(bid*rate),ask=str(ask*rate),native=str(native),fx=fx['rate'],fx_at=fx['asof'],asof=clock,source='Kraken 公開買賣報價'))
    elif name=='US':
        if data.get('error') or not isinstance(data.get('data'),list):raise ValueError('US feed unavailable')
        for r in data['data']:
            symbol='US:'+r['symbol']
            if symbol not in market.INSTRUMENTS:continue
            # Date is the trading session date, not the API fetch date. Fixed UTC
            # midnight is conservative: no after-close submission can fill that day.
            asof=datetime.fromisoformat(r['date'].replace('Z','+00:00')).timestamp()
            native=market.decimal(r['close']);price=str(native*Decimal(fx['rate']))
            rows.append(dict(symbol=symbol,price=price,bid=price,ask=price,native=str(native),fx=fx['rate'],fx_at=fx['asof'],asof=asof,source='Marketstack 免費收盤行情'))
    if not rows:raise ValueError('Empty market response')
    return rows,'ok',clock+PERIODS[name],None


def refresh(names,clock,fx):
    def read(name,current_fx):
        try:return (name,*read_provider(name,clock,current_fx))
        except Exception:
            # Upstream exceptions may contain the key; never return/log them.
            return name,[],'unavailable',clock+(60 if name=='CC' else 86400 if name=='US' else PERIODS['TW'] if name=='TW' else 3600),None
    results=[]
    if 'FX' in names:
        name,rows,status,next_at,new_fx=read('FX',fx)
        if new_fx:fx=new_fx
        results.append((name,rows,status,next_at))
    others=[n for n in names if n!='FX']
    if others:
        # An unavailable stock endpoint cannot add several serial timeouts to
        # the crypto path. Three bounded requests, shared across all members.
        with ThreadPoolExecutor(max_workers=3) as pool:
            for name,rows,status,next_at,_ in pool.map(lambda n:read(n,fx),others):
                results.append((name,rows,status,next_at))
    return results


def apply(db,results,clock):
    changed=False
    for name,rows,status,next_at in results:
        if name=='TW':
            # Immediately stop every omitted/invalid symbol, even when its old
            # observation is still within the age window. Keep its last mark.
            db.executemany('INSERT INTO market_quote_health VALUES(?,?) ON CONFLICT(symbol) DO UPDATE SET issue=excluded.issue',[(symbol,'missing_data' if rows else status) for symbol,item in market.INSTRUMENTS.items() if item['market']=='TW'])
        if rows:
            db.execute('SAVEPOINT provider_quotes')
            try:
                updated=market.apply_quotes(db,rows,clock)
                db.execute('RELEASE SAVEPOINT provider_quotes');changed=updated or changed
            except (market.RuleError,ValueError,KeyError,TypeError):
                db.execute('ROLLBACK TO SAVEPOINT provider_quotes');db.execute('RELEASE SAVEPOINT provider_quotes')
                status='unavailable';next_at=clock+(86400 if name=='US' else 60 if name=='CC' else PERIODS['TW'] if name=='TW' else 3600)
        # Failed FX requests retain the last good rate for a bounded 72h.
        old=db.execute('SELECT status FROM market_providers WHERE name=?',(name,)).fetchone()
        if name=='FX' and status=='unavailable' and old:
            try:
                json.loads(old[0])['rate'];status=old[0]
            except (ValueError,KeyError,TypeError):pass
        db.execute('INSERT INTO market_providers VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET next_at=excluded.next_at,last_at=excluded.last_at,status=excluded.status',(name,next_at,clock,status))
    return changed
