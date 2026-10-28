"""Isolated, linear virtual contracts. Integer points and exact rational P&L.

Risk mechanics follow the isolated USDT-linear model, with explicit site TWD
notional brackets. This is not an exchange matching engine or live derivatives.
"""
from fractions import Fraction
from decimal import Decimal
import json
import re
import member_accounts

# TWD-point thresholds are site limits; rates/max leverage reference OKX's
# BTC isolated tiers observed 2026-10-28. Never label these as OKX stock tiers.
TIERS=((1_000_000,100,40),(5_000_000,66,50),(20_000_000,50,75),(100_000_000,40,125))
LEVERAGES=(1,2,3,5,10,20,25,40,50,66,100)
FEE_BPS=5
SCALE=100_000_000


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS market_contracts(
      id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,
      direction TEXT NOT NULL,leverage INTEGER NOT NULL,units INTEGER NOT NULL,margin INTEGER NOT NULL,
      entry_native TEXT NOT NULL,entry_fx TEXT NOT NULL,entry_asof REAL NOT NULL,opened_at REAL NOT NULL,
      opening_fee INTEGER NOT NULL,fee_bps INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'open',
      closed_at REAL,exit_native TEXT,returned INTEGER,profit INTEGER,reason TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS market_contract_owner ON market_contracts(user_id,status,symbol,direction);
    CREATE TABLE IF NOT EXISTS market_contract_orders(
      id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,
      action TEXT NOT NULL,direction TEXT NOT NULL,leverage INTEGER NOT NULL,margin INTEGER NOT NULL,
      reserve INTEGER NOT NULL,status TEXT NOT NULL,submitted_at REAL NOT NULL,expires_at REAL NOT NULL,
      position_id INTEGER REFERENCES market_contracts(id),filled_at REAL,fill_asof REAL,
      fill_native TEXT,fee INTEGER,reason TEXT NOT NULL DEFAULT '');
    CREATE INDEX IF NOT EXISTS market_contract_pending ON market_contract_orders(status,symbol);
    CREATE INDEX IF NOT EXISTS market_contract_order_owner ON market_contract_orders(user_id,id DESC);
    CREATE UNIQUE INDEX IF NOT EXISTS market_contract_one_close ON market_contract_orders(position_id)
      WHERE action='close' AND status='pending';''')
    # Additive migration preserves existing positions, pending receipts and balances.
    for table,columns in {
        'market_contracts':(('take_profit','TEXT'),('stop_loss','TEXT')),
        'market_contract_orders':(('order_kind',"TEXT NOT NULL DEFAULT 'market'"),('limit_native','TEXT'),('take_profit','TEXT'),('stop_loss','TEXT')),
    }.items():
        existing={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
        for name,definition in columns:
            if name not in existing:db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)


def ceil(value):return -(-value.numerator//value.denominator)
def floor(value):return value.numerator//value.denominator

def fraction(value):
    import market
    return Fraction(market.decimal(value))


def tier(notional):
    for index,(cap,leverage,bps) in enumerate(TIERS):
        if notional<=cap:return dict(tier=index+1,cap=cap,max_leverage=leverage,mmr_bps=bps)
    return dict(tier=len(TIERS),cap=TIERS[-1][0],max_leverage=TIERS[-1][1],mmr_bps=TIERS[-1][2])


def price(q):return fraction(q['native']),fraction(q['fx'])


def exit_levels(direction,entry,take_profit,stop_loss):
    """Validate native-price exits against intended/actual entry, including gaps."""
    sign=1 if direction=='long' else -1
    return (take_profit is None or (fraction(take_profit)-entry)*sign>0) and (stop_loss is None or (entry-fraction(stop_loss))*sign>0)


def group_notional(db,uid,symbol,direction,q,include_orders=False):
    native,fx=price(q)
    units=db.execute("SELECT COALESCE(sum(units),0) FROM market_contracts WHERE user_id=? AND symbol=? AND direction=? AND status='open'",(uid,symbol,direction)).fetchone()[0]
    value=Fraction(units,SCALE)*native*fx
    if include_orders:value+=db.execute("SELECT COALESCE(sum(margin*leverage),0) FROM market_contract_orders WHERE user_id=? AND symbol=? AND direction=? AND action='open' AND status='pending'",(uid,symbol,direction)).fetchone()[0]
    return value


def risk(position,q,bracket):
    native,fx=price(q);qty=Fraction(position['units'],SCALE);entry=fraction(position['entry_native'])
    direction=1 if position['direction']=='long' else -1
    pnl=qty*(native-entry)*fx*direction
    equity=Fraction(position['margin'])+pnl
    notional=qty*native*fx
    close_fee=ceil(notional*position['fee_bps']/10000)
    requirement=notional*bracket['mmr_bps']/10000+close_fee
    value=max(0,floor(equity-close_fee))
    rate=Fraction(bracket['mmr_bps']+position['fee_bps'],10000)
    # Native-currency estimate; actual trigger uses exact equity/requirement.
    liq=(qty*entry-position['margin']/fx)/(qty*(1-rate)) if direction==1 else (qty*entry+position['margin']/fx)/(qty*(1+rate))
    ratio=float(equity/requirement*100) if requirement>0 else None
    return dict(value=value,unrealized_profit=floor(pnl),profit=value-position['margin']-position['opening_fee'],
        equity=floor(equity),notional=ceil(notional),closing_fee=close_fee,maintenance=ceil(notional*bracket['mmr_bps']/10000),
        mmr_bps=bracket['mmr_bps'],tier=bracket['tier'],risk_ratio=round(ratio,2) if ratio is not None else None,
        liquidation_price=format(Decimal(max(Fraction(0),liq).numerator)/Decimal(max(Fraction(0),liq).denominator),'f'),
        liquidate=equity<=requirement)


def values(db,quotes,uid=None):
    rows=[dict(r) for r in db.execute("SELECT * FROM market_contracts WHERE status='open'"+(' AND user_id=?' if uid is not None else ''),() if uid is None else (uid,))]
    units={}
    for p in rows:
        key=(p['user_id'],p['symbol'],p['direction']);units[key]=units.get(key,0)+p['units']
    result={};brackets={}
    for p in rows:
        q=quotes.get(p['symbol']);key=(p['user_id'],p['symbol'],p['direction'])
        if q:
            if key not in brackets:
                native,fx=price(q);brackets[key]=tier(Fraction(units[key],SCALE)*native*fx)
            result[p['id']]=risk(p,q,brackets[key])
        else:result[p['id']]=dict(value=p['margin'],profit=-p['opening_fee'],unrealized_profit=0,equity=p['margin'],notional=0,closing_fee=0,maintenance=0,mmr_bps=0,tier=1,risk_ratio=None,liquidation_price=None,liquidate=False)
    return result


def assets(db,quotes):
    result={};marks=values(db,quotes)
    for p in db.execute("SELECT id,user_id FROM market_contracts WHERE status='open'"):
        result[p['user_id']]=result.get(p['user_id'],0)+marks[p['id']]['value']
    for p in db.execute("SELECT user_id,sum(reserve) AS amount FROM market_contract_orders WHERE status='pending' AND action='open' GROUP BY user_id"):
        result[p['user_id']]=result.get(p['user_id'],0)+p['amount']
    return result


def view(db,uid,clock,quotes):
    import market
    marks=values(db,quotes,uid)
    positions=[]
    for row in db.execute("SELECT * FROM market_contracts WHERE user_id=? AND status='open' ORDER BY id DESC",(uid,)):
        p=dict(row);q=quotes.get(p['symbol'])
        closing=bool(db.execute("SELECT 1 FROM market_contract_orders WHERE position_id=? AND action='close' AND status='pending'",(p['id'],)).fetchone())
        positions.append(dict(p,**marks[p['id']],units=str(p['units']),quantity=market.quantity(p['units']),stale=not market.quote_ready(q,clock),closing=closing))
    return dict(positions=positions,orders=[dict(r) for r in db.execute('SELECT * FROM market_contract_orders WHERE user_id=? ORDER BY id DESC LIMIT 50',(uid,))],
        history=[dict(r) for r in db.execute("SELECT * FROM market_contracts WHERE user_id=? AND status!='open' ORDER BY id DESC LIMIT 30",(uid,))],
        rules=dict(leverage_options=LEVERAGES,fee_bps=FEE_BPS,funding_bps=0,mode='isolated',tiers=[dict(cap=cap,max_leverage=lever,mmr_bps=mmr) for cap,lever,mmr in TIERS],
          reference='OKX 逐倉線性模型；本站台幣點數級距',max_margin=1_000_000,max_positions=20,order_types=['market','limit'],limit_expiry_seconds=7*86400))


def mutate(db,user,action,data,clock):
    import market,market_catalog,wallet,club_admin
    uid=user['id'];member_accounts.require_active(db,uid)
    if club_admin.identity(db,uid)['is_admin']:club_admin.require(db,uid)
    if not wallet.active(db):raise market.RuleError('點數制度尚未啟用。')
    op=data.get('operation_id')
    if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',op):raise market.RuleError('交易回執無效。')
    if action=='open':
        symbol=data.get('symbol');direction=data.get('direction');leverage=data.get('leverage');margin=data.get('margin')
        if not market_catalog.get(db,symbol) or direction not in ('long','short') or type(leverage) is not int or leverage not in LEVERAGES or type(margin) is not int or not 10<=margin<=1_000_000:raise market.RuleError('請選擇有效標的、多空、槓桿與 10–1,000,000 整數點保證金。')
        intent=[action,symbol,direction,leverage,margin]
        kind=data.get('order_kind','market')
        if kind not in ('market','limit'):raise market.RuleError('請選擇市價或限價委託。')
        limit=str(market.decimal(data.get('limit_price'))) if kind=='limit' else None
        if kind=='market' and data.get('limit_price') is not None:raise market.RuleError('市價委託不可附帶限價。')
        tp=str(market.decimal(data['take_profit'])) if data.get('take_profit') is not None else None
        sl=str(market.decimal(data['stop_loss'])) if data.get('stop_loss') is not None else None
        # Keep legacy fingerprints byte-identical for in-flight older clients.
        if kind!='market' or tp is not None or sl is not None:intent.extend([kind,limit,tp,sl])
    elif action in ('close','cancel'):
        key='position_id' if action=='close' else 'order_id';target=data.get(key)
        if type(target) is not int or target<1:raise market.RuleError('倉位或委託編號無效。')
        intent=[action,target]
    else:raise market.RuleError('合約操作無效。')
    fingerprint=json.dumps(['contract',*intent],separators=(',',':'))
    old=db.execute('SELECT * FROM market_operations WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise member_accounts.AccountError('相同回執已用於其他交易。',409,'operation_conflict')
        return dict(json.loads(old['result']),replayed=True)
    pause=db.execute("SELECT value FROM settings WHERE key='deploy_pause_until'").fetchone()
    if action!='cancel' and pause and float(pause[0])>clock:raise member_accounts.AccountError('版本更新中，尚未保留新點數。',503,'deployment_pending')
    db.execute('SAVEPOINT contract_operation')
    try:
        if action=='cancel':
            order=db.execute("SELECT * FROM market_contract_orders WHERE id=? AND user_id=? AND status='pending'",(target,uid)).fetchone()
            if not order:raise market.RuleError('找不到待成交合約委託。')
            cancel(db,order,clock,'cancelled','自行取消');oid=target
        else:
            if action=='close':
                position=db.execute("SELECT * FROM market_contracts WHERE id=? AND user_id=? AND status='open'",(target,uid)).fetchone()
                if not position:raise market.RuleError('找不到可平倉的合約。')
                if db.execute("SELECT 1 FROM market_contract_orders WHERE position_id=? AND action='close' AND status='pending'",(target,)).fetchone():raise market.RuleError('這筆倉位已在等待平倉。')
                symbol=position['symbol'];direction=position['direction'];leverage=position['leverage'];margin=0
                kind='market';limit=tp=sl=None
            q=db.execute(market.QUOTE_SQL+' WHERE q.symbol=?',(symbol,)).fetchone()
            if not q or kind!='limit' and not market.quote_ready(q,clock):raise market.RuleError('行情未就緒或已過期，暫停合約成交。')
            if db.execute("SELECT count(*) FROM market_contract_orders WHERE user_id=? AND status='pending'",(uid,)).fetchone()[0]>=20:raise market.RuleError('最多二十筆待成交合約委託。')
            reserve=0
            if action=='open':
                entry=fraction(limit) if limit is not None else fraction(q['native'])
                if not exit_levels(direction,entry,tp,sl):raise market.RuleError('多單止盈須高於入場價、止損須低於入場價；空單相反。')
                if db.execute("SELECT count(*) FROM market_contracts WHERE user_id=? AND status='open'",(uid,)).fetchone()[0]+db.execute("SELECT count(*) FROM market_contract_orders WHERE user_id=? AND status='pending' AND action='open'",(uid,)).fetchone()[0]>=20:raise market.RuleError('最多二十筆合約倉位與開倉委託。')
                total=group_notional(db,uid,symbol,direction,q,True)+margin*leverage;bracket=tier(total)
                if total>TIERS[-1][0] or leverage>bracket['max_leverage']:raise market.RuleError('同標的同方向名目部位超過這個槓桿的級距，請降低槓桿或保證金。')
                existing=db.execute("SELECT max(leverage) FROM market_contracts WHERE user_id=? AND symbol=? AND direction=? AND status='open'",(uid,symbol,direction)).fetchone()[0] or 0
                if existing>bracket['max_leverage']:raise market.RuleError('新增後會超過既有倉位的槓桿級距，請先減倉。')
                reserve=margin+ceil(Fraction(margin*leverage*FEE_BPS,10000))
            expiry=7*86400 if kind=='limit' else market.PENDING_SECONDS[market_catalog.group(symbol)]
            oid=db.execute("INSERT INTO market_contract_orders(user_id,symbol,action,direction,leverage,margin,reserve,status,submitted_at,expires_at,position_id,order_kind,limit_native,take_profit,stop_loss) VALUES(?,?,?,?,?,?,?,'pending',?,?,?,?,?,?,?)",(uid,symbol,action,direction,leverage,margin,reserve,clock,clock+expiry,target if action=='close' else None,kind,limit,tp,sl)).lastrowid
            if reserve:wallet.transfer(db,uid,-reserve,'market_reserve','contract:reserve:'+str(oid),clock)
        result=dict(ok=True,order_id=oid,action=action,replayed=False,order_type='contract')
        db.execute('INSERT INTO market_operations VALUES(?,?,?,?)',(uid,op,fingerprint,json.dumps(result)))
        db.execute('RELEASE SAVEPOINT contract_operation');return result
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT contract_operation');db.execute('RELEASE SAVEPOINT contract_operation');raise


def cancel(db,order,clock,status,reason):
    import wallet
    if order['action']=='open':wallet.transfer(db,order['user_id'],order['reserve'],'market_refund','contract:refund:'+str(order['id']),clock)
    db.execute('UPDATE market_contract_orders SET status=?,reason=? WHERE id=?',(status,reason,order['id']))


def close(db,position,q,clock,liquidated=False,reason=None):
    import wallet,market
    bracket=tier(group_notional(db,position['user_id'],position['symbol'],position['direction'],q))
    mark=risk(position,q,bracket);returned=0 if liquidated else mark['value']
    wallet.transfer(db,position['user_id'],returned,'market_sale','contract:close:'+str(position['id']),clock)
    db.execute("UPDATE market_contracts SET status=?,closed_at=?,exit_native=?,returned=?,profit=?,reason=? WHERE id=? AND status='open'",('liquidated' if liquidated else 'closed',clock,q['native'],returned,returned-position['margin']-position['opening_fee'],'權益不足維持保證金與平倉費' if liquidated else reason or '自行平倉',position['id']))
    if liquidated or reason:db.execute("UPDATE market_contract_orders SET status='cancelled',reason='倉位已自動結束，不會重複平倉' WHERE position_id=? AND action='close' AND status='pending'",(position['id'],))
    return returned,mark['closing_fee']


def settle(db,clock,quotes):
    import market,wallet
    changed=False
    for p in db.execute("SELECT * FROM market_contracts WHERE status='open' ORDER BY id").fetchall():
        q=quotes.get(p['symbol'])
        if not market.quote_ready(q,clock):continue
        if risk(p,q,tier(group_notional(db,p['user_id'],p['symbol'],p['direction'],q)))['liquidate']:
            close(db,p,q,clock,True);changed=True
        elif q['asof']>p['entry_asof']:
            current=fraction(q['native']);sign=1 if p['direction']=='long' else -1
            tp=p['take_profit'];sl=p['stop_loss']
            reason='止損觸發' if sl is not None and (current-fraction(sl))*sign<=0 else '止盈觸發' if tp is not None and (current-fraction(tp))*sign>=0 else None
            if reason:close(db,p,q,clock,reason=reason);changed=True
    for o in db.execute("SELECT * FROM market_contract_orders WHERE status='pending' ORDER BY id").fetchall():
        if clock>=o['expires_at']:cancel(db,o,clock,'expired','等待有效新價格逾時');changed=True;continue
        try:member_accounts.require_active(db,o['user_id'])
        except member_accounts.AccountError:cancel(db,o,clock,'cancelled','帳號已停用');changed=True;continue
        q=quotes.get(o['symbol'])
        if not market.quote_ready(q,clock) or q['asof']<=o['submitted_at']:continue
        if o['action']=='close':
            p=db.execute("SELECT * FROM market_contracts WHERE id=? AND status='open'",(o['position_id'],)).fetchone()
            if not p:cancel(db,o,clock,'cancelled','倉位已結束');changed=True;continue
            _,fee=close(db,p,q,clock);pid=p['id']
        else:
            native,fx=price(q)
            if o['order_kind']=='limit':
                limit=fraction(o['limit_native'])
                if (native>limit if o['direction']=='long' else native<limit):continue
            if not exit_levels(o['direction'],native,o['take_profit'],o['stop_loss']):
                cancel(db,o,clock,'cancelled','新價格已越過預設止盈／止損，已退回全部保留點數');changed=True;continue
            total=group_notional(db,o['user_id'],o['symbol'],o['direction'],q,True);bracket=tier(total)
            existing=db.execute("SELECT max(leverage) FROM market_contracts WHERE user_id=? AND symbol=? AND direction=? AND status='open'",(o['user_id'],o['symbol'],o['direction'])).fetchone()[0] or 0
            if total>TIERS[-1][0] or max(o['leverage'],existing)>bracket['max_leverage']:
                cancel(db,o,clock,'cancelled','新價格超出槓桿級距，已退回全部保留點數');changed=True;continue
            units=floor(Fraction(o['margin']*o['leverage']*SCALE)/(native*fx))
            notional=Fraction(units,SCALE)*native*fx;fee=ceil(notional*FEE_BPS/10000)
            if units<1 or units>10**17 or o['margin']<=ceil(notional*bracket['mmr_bps']/10000)+fee:
                cancel(db,o,clock,'cancelled','保證金不足安全開倉或份額超出上限');changed=True;continue
            pid=db.execute("INSERT INTO market_contracts(user_id,symbol,direction,leverage,units,margin,entry_native,entry_fx,entry_asof,opened_at,opening_fee,fee_bps,take_profit,stop_loss) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(o['user_id'],o['symbol'],o['direction'],o['leverage'],units,o['margin'],q['native'],q['fx'],q['asof'],clock,fee,FEE_BPS,o['take_profit'],o['stop_loss'])).lastrowid
            wallet.transfer(db,o['user_id'],o['reserve']-o['margin']-fee,'market_refund','contract:change:'+str(o['id']),clock)
        db.execute("UPDATE market_contract_orders SET status='filled',position_id=?,filled_at=?,fill_asof=?,fill_native=?,fee=? WHERE id=?",(pid,clock,q['asof'],q['native'],fee,o['id']))
        changed=True
    return changed
