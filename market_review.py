"""Quarantined stock quotes and audited administrator recovery; no network I/O."""
import hashlib,json,secrets
import member_accounts
from poker_engine import RuleError


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS market_halts(
      symbol TEXT PRIMARY KEY,case_id TEXT NOT NULL,base_quote TEXT NOT NULL,
      candidate_quote TEXT NOT NULL,started_at REAL NOT NULL,updated_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS market_halt_events(
      id INTEGER PRIMARY KEY,actor_id INTEGER NOT NULL REFERENCES users(id),symbol TEXT NOT NULL,
      action TEXT NOT NULL,note TEXT NOT NULL,case_id TEXT NOT NULL,operation_id TEXT NOT NULL,
      fingerprint TEXT NOT NULL,result TEXT NOT NULL,base_quote TEXT NOT NULL,
      candidate_quote TEXT NOT NULL,created_at REAL NOT NULL,UNIQUE(actor_id,operation_id));''')


def quote_key(q):
    return hashlib.sha256(json.dumps([str(q[k]) for k in ('price','bid','ask','native','fx','source')],separators=(',',':')).encode()).hexdigest()


def observe(db,old,candidate,clock):
    row=db.execute('SELECT * FROM market_halts WHERE symbol=?',(candidate['symbol'],)).fetchone()
    value=json.dumps(candidate,sort_keys=True)
    if row:
        if candidate['asof']<json.loads(row['candidate_quote'])['asof']:return
        db.execute('UPDATE market_halts SET candidate_quote=?,updated_at=? WHERE symbol=?',(value,clock,candidate['symbol']))
    else:
        db.execute('INSERT INTO market_halts VALUES(?,?,?,?,?,?)',(candidate['symbol'],secrets.token_hex(12),json.dumps(dict(old)),value,clock,clock))
    # A valid but quarantined observation is distinct from a provider omission.
    db.execute('DELETE FROM market_quote_health WHERE symbol=?',(candidate['symbol'],))


def candidate(db,row,clock):
    import market
    q=json.loads(row['candidate_quote']);q.update(halted=0,checked_at=row['updated_at'])
    meta=db.execute('SELECT session_start,session_end FROM market_quote_meta WHERE symbol=?',(row['symbol'],)).fetchone()
    q.update(session_start=meta[0] if meta else None,session_end=meta[1] if meta else None)
    issue=db.execute('SELECT issue FROM market_quote_health WHERE symbol=?',(row['symbol'],)).fetchone()
    q['issue']=issue[0] if issue else ''
    return q,market.quote_ready(q,clock)


def exposure(db,symbol):
    return dict(spot=db.execute('SELECT count(*) FROM market_positions WHERE symbol=? AND units>0',(symbol,)).fetchone()[0],
                shorts=db.execute("SELECT count(*) FROM market_shorts WHERE symbol=? AND status='open'",(symbol,)).fetchone()[0],
                contracts=db.execute("SELECT count(*) FROM market_contracts WHERE symbol=? AND status='open'",(symbol,)).fetchone()[0],
                orders=db.execute("SELECT count(*) FROM market_orders WHERE symbol=? AND status='pending'",(symbol,)).fetchone()[0]+db.execute("SELECT count(*) FROM market_contract_orders WHERE symbol=? AND status='pending'",(symbol,)).fetchone()[0])


def view(db,user,clock):
    import club_admin
    club_admin.require(db,user['id']);rows=[]
    for quote in db.execute('SELECT * FROM market_quotes WHERE halted=1 ORDER BY symbol'):
        row=db.execute('SELECT * FROM market_halts WHERE symbol=?',(quote['symbol'],)).fetchone()
        q,ready=candidate(db,row,clock) if row else (None,False)
        rows.append(dict(symbol=quote['symbol'],base_price=quote['native'],base_at=quote['asof'],base_points=quote['price'],
                         candidate_price=q['native'] if q else None,candidate_at=q['asof'] if q else None,
                         case_id=row['case_id'] if row else None,quote_key=quote_key(q) if q else None,
                         ready=ready,exposure=exposure(db,quote['symbol'])))
    history=[dict(r) for r in db.execute('SELECT id,actor_id,symbol,action,note,result,created_at FROM market_halt_events ORDER BY id DESC LIMIT 30')]
    for row in history:row['result']=json.loads(row['result'])
    return dict(cases=rows,history=history,server_time=clock)


def settle_exposure(db,symbol,base,clock,case_id):
    import market,market_contracts,wallet
    reason='管理員審核公司行動：撤單並按停牌前可信報價結清'
    for row in db.execute("SELECT * FROM market_orders WHERE symbol=? AND status='pending'",(symbol,)).fetchall():market.cancel(db,row,clock,'cancelled',reason)
    for row in db.execute("SELECT * FROM market_contract_orders WHERE symbol=? AND status='pending'",(symbol,)).fetchall():market_contracts.cancel(db,row,clock,'cancelled',reason)
    for row in db.execute('SELECT * FROM market_positions WHERE symbol=? AND units>0',(symbol,)).fetchall():
        amount=market.value_points(row['units'],base['price'])
        wallet.transfer(db,row['user_id'],amount,'market_sale','halt:spot:'+case_id,clock)
        db.execute('UPDATE market_positions SET units=0,cost=0 WHERE user_id=? AND symbol=?',(row['user_id'],symbol))
        db.execute("INSERT INTO market_orders(user_id,symbol,side,budget,units,status,submitted_at,expires_at,filled_at,fill_asof,fill_price,filled_units,points,profit,reason) VALUES(?,?,'sell',0,?,'filled',?,?,?,?,?,?,?,?,?)",
                   (row['user_id'],symbol,row['units'],clock,clock,clock,base['asof'],base['price'],row['units'],amount,amount-row['cost'],reason))
    for row in db.execute("SELECT * FROM market_shorts WHERE symbol=? AND status='open'",(symbol,)).fetchall():market.close_short(db,row,base,clock)
    for row in db.execute("SELECT * FROM market_contracts WHERE symbol=? AND status='open' ORDER BY id",(symbol,)).fetchall():market_contracts.close(db,row,base,clock,reason=reason)


def resolve(db,user,data,clock):
    import market,club_admin
    club_admin.require(db,user['id']);op=member_accounts.operation_id(data.get('operation_id'))
    symbol=data.get('symbol');action=data.get('action');case_id=data.get('case_id');expected=data.get('quote_key');note=data.get('note')
    if action not in ('resume','settle') or not all(isinstance(v,str) for v in (symbol,case_id,expected,note)) or not 1<=len(note.strip())<=200:raise RuleError('請選擇處理方式並填寫 1–200 字的審核備註。')
    note=note.strip();fingerprint=hashlib.sha256(json.dumps([symbol,action,case_id,expected,note]).encode()).hexdigest()
    old=db.execute('SELECT fingerprint,result FROM market_halt_events WHERE actor_id=? AND operation_id=?',(user['id'],op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise member_accounts.AccountError('相同編號已用於其他停牌審核。',409,'operation_conflict')
        return dict(json.loads(old['result']),replayed=True)
    row=db.execute('SELECT * FROM market_halts WHERE symbol=?',(symbol,)).fetchone()
    base=db.execute('SELECT * FROM market_quotes WHERE symbol=?',(symbol,)).fetchone()
    if not row or not base or not base['halted'] or row['case_id']!=case_id:raise member_accounts.AccountError('停牌案件已變更，請重新載入。',409,'stale_halt')
    q,ready=candidate(db,row,clock)
    if not ready:raise RuleError('目前行情缺少、過期或不在交易時段，請等待有效報價再審核。')
    if quote_key(q)!=expected:raise member_accounts.AccountError('候選價格已變動，請重新核對後再確認。',409,'stale_halt_quote')
    counts=exposure(db,symbol)
    if action=='resume' and any(counts.values()) and abs(market.decimal(q['price'])/market.decimal(base['price'])-1)>market.Decimal('.35'):
        raise RuleError('價格仍偏離停牌前超過 35%，有舊部位時請維持停牌，或選擇撤單並結清後恢復。')
    db.execute('SAVEPOINT resolve_market_halt')
    try:
        before=market._assets(db);cash={r[0]:r[1] for r in db.execute('SELECT user_id,balance FROM wallets')}
        if action=='settle':settle_exposure(db,symbol,base,clock,case_id)
        db.execute('UPDATE market_quotes SET halted=0 WHERE symbol=?',(symbol,))
        # Replace the trusted baseline before normal ingestion so a reviewed
        # company action does not immediately trip the same 35% guard again.
        if action=='settle' or not any(counts.values()):
            db.execute('UPDATE market_quotes SET price=?,bid=?,ask=?,native=?,fx=?,fx_at=? WHERE symbol=?',tuple(q[k] for k in ('price','bid','ask','native','fx','fx_at'))+(symbol,))
        market.apply_quotes(db,[q],clock)
        after=market._assets(db);cash_after={r[0]:r[1] for r in db.execute('SELECT user_id,balance FROM wallets')}
        # Normal ingestion already records mark changes for resume; settlement
        # only converts the existing trusted mark/reserves into wallet points.
        if action=='settle':
            for uid in before.keys()|after.keys():market.wealth_delta(db,uid,after.get(uid,0)-before.get(uid,0)+cash_after.get(uid,0)-cash.get(uid,0),clock)
        result=dict(ok=True,replayed=False,symbol=symbol,action=action,exposure=counts,message='已完成停牌審核'+('，原部位按停牌前報價結清，未成交委託已撤回。' if action=='settle' else '，已恢復有效報價。'))
        db.execute('INSERT INTO market_halt_events(actor_id,symbol,action,note,case_id,operation_id,fingerprint,result,base_quote,candidate_quote,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (user['id'],symbol,action,note,case_id,op,fingerprint,json.dumps(result),json.dumps(dict(base)),json.dumps(q),clock))
        db.execute('DELETE FROM market_halts WHERE symbol=?',(symbol,))
        db.execute('RELEASE SAVEPOINT resolve_market_halt');return result
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT resolve_market_halt');db.execute('RELEASE SAVEPOINT resolve_market_halt');raise
