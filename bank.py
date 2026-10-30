"""Virtual-point savings and simple-interest loans; caller owns the transaction."""
import hashlib
import json
import re
import member_accounts
from poker_engine import RuleError

DAY = 86400
UNIT = DAY * 10000
MAX_SAVINGS = 1_000_000_000


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS bank_settings(id INTEGER PRIMARY KEY CHECK(id=1),
      revision INTEGER NOT NULL,deposit_bps INTEGER NOT NULL,loan_bps INTEGER NOT NULL,
      loan_limit INTEGER NOT NULL,loan_days INTEGER NOT NULL);
    INSERT OR IGNORE INTO bank_settings VALUES(1,1,50,150,3000,7);
    CREATE TABLE IF NOT EXISTS bank_accounts(user_id INTEGER PRIMARY KEY REFERENCES users(id),
      balance INTEGER NOT NULL CHECK(balance>=0),interest_units INTEGER NOT NULL CHECK(interest_units>=0),
      rate_bps INTEGER NOT NULL,last_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS bank_loans(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
      original INTEGER NOT NULL,principal INTEGER NOT NULL CHECK(principal>=0),rate_bps INTEGER NOT NULL,
      interest_units INTEGER NOT NULL CHECK(interest_units>=0),generated_units INTEGER NOT NULL,
      started_at INTEGER NOT NULL,due_at INTEGER NOT NULL,last_at INTEGER NOT NULL,closed_at INTEGER);
    CREATE UNIQUE INDEX IF NOT EXISTS bank_active_loan ON bank_loans(user_id) WHERE closed_at IS NULL;
    CREATE TABLE IF NOT EXISTS bank_operations(user_id INTEGER NOT NULL REFERENCES users(id),
      operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(user_id,operation_id));
    CREATE TABLE IF NOT EXISTS bank_ledger(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
      kind TEXT NOT NULL,amount INTEGER NOT NULL,savings_after INTEGER NOT NULL,wallet_after INTEGER NOT NULL,
      loan_id INTEGER REFERENCES bank_loans(id),created_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS bank_history ON bank_ledger(user_id,id DESC);
    CREATE TABLE IF NOT EXISTS bank_settings_history(id INTEGER PRIMARY KEY,actor_id INTEGER NOT NULL REFERENCES users(id),
      operation_id TEXT NOT NULL,fingerprint TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL,
      note TEXT NOT NULL,created_at INTEGER NOT NULL,UNIQUE(actor_id,operation_id));
    ''')

    columns={r[1] for r in db.execute('PRAGMA table_info(bank_loans)')}
    for name,definition in {'terms_version':'INTEGER NOT NULL DEFAULT 0','grace_until':'INTEGER NOT NULL DEFAULT 0','cap_units':'INTEGER','auto_repay':'INTEGER NOT NULL DEFAULT 0','repay_remainder':'INTEGER NOT NULL DEFAULT 0'}.items():
        if name not in columns:db.execute('ALTER TABLE bank_loans ADD COLUMN '+name+' '+definition)


def lending_limit(db,uid,clock):
    import clubhouse
    rate=clubhouse.income_view(db,uid,clock)['rate']
    return min(settings(db)['loan_limit'],100000,max(10000,(rate*24+2000)*3))


def eligible_savings(db,uid,balance):
    row=db.execute('SELECT principal FROM bank_loans WHERE user_id=? AND closed_at IS NULL',(uid,)).fetchone()
    return max(0,balance-(row[0] if row else 0))


def accrue_loan(value,clock):
    at=max(value['last_at'],int(clock));cap=value.get('cap_units')
    if cap is None:cap=value['original']*UNIT
    elapsed=max(0,at-max(value['last_at'],value.get('grace_until',0)))
    units=min(max(0,cap-value['generated_units']),value['principal']*value['rate_bps']*elapsed)
    value.update(interest_units=value['interest_units']+units,generated_units=value['generated_units']+units,last_at=at)
    return value


def settings(db):
    return {k:v for k,v in dict(db.execute('SELECT * FROM bank_settings WHERE id=1').fetchone()).items() if k!='id'}


def account(db,uid,clock):
    row=db.execute('SELECT * FROM bank_accounts WHERE user_id=?',(uid,)).fetchone()
    value=dict(row) if row else dict(user_id=uid,balance=0,interest_units=0,rate_bps=settings(db)['deposit_bps'],last_at=int(clock))
    at=max(value['last_at'],int(clock))
    value['interest_units']=min(MAX_SAVINGS*UNIT,value['interest_units']+eligible_savings(db,uid,value['balance'])*value['rate_bps']*(at-value['last_at']))
    value['last_at']=at
    return value


def loan(db,uid,clock):
    row=db.execute('SELECT * FROM bank_loans WHERE user_id=? AND closed_at IS NULL',(uid,)).fetchone()
    if not row:return None
    return accrue_loan(dict(row),clock)



def debt(value):
    return value['principal']+(value['interest_units']+UNIT-1)//UNIT if value else 0


def summary(db,uid,clock):
    a=account(db,uid,clock)
    return dict(savings=a['balance'],debt=debt(loan(db,uid,clock)),interest=a['interest_units']//UNIT)



def assets(db,clock):
    # One pair of indexed scans for a lobby, rather than queries per member.
    values={r['user_id']:r['balance'] for r in db.execute('SELECT user_id,balance FROM bank_accounts')}
    for r in db.execute('SELECT * FROM bank_loans WHERE closed_at IS NULL'):
        value=accrue_loan(dict(r),clock)
        values[r['user_id']]=values.get(r['user_id'],0)-debt(value)
    return values


def view(db,uid,clock,before=None):
    if before is not None and (not isinstance(before,str) or not re.fullmatch(r'[1-9]\d{0,17}',before)):raise RuleError('銀行紀錄游標無效。')
    a=account(db,uid,clock);l=loan(db,uid,clock)
    if l:l={k:l[k] for k in ('id','original','principal','rate_bps','started_at','due_at','terms_version','grace_until','auto_repay')}|dict(interest=debt(l)-l['principal'],total_due=debt(l),overdue=int(clock)>=l['due_at'])
    rows=[dict(r) for r in db.execute('SELECT * FROM bank_ledger WHERE user_id=? AND id<? ORDER BY id DESC LIMIT 31',(uid,int(before) if before else 2**63-1))]
    return dict(borrow_limit=lending_limit(db,uid,clock),eligible_savings=eligible_savings(db,uid,a['balance']),settings=settings(db),savings=a['balance'],interest=a['interest_units']//UNIT,loan=l,
                history=rows[:30],next_before=str(rows[29]['id']) if len(rows)>30 else None,server_time=clock)


def save_account(db,a):
    db.execute('INSERT INTO bank_accounts VALUES(:user_id,:balance,:interest_units,:rate_bps,:last_at) ON CONFLICT(user_id) DO UPDATE SET balance=excluded.balance,interest_units=excluded.interest_units,rate_bps=excluded.rate_bps,last_at=excluded.last_at',a)


def save_loan(db,l):
    db.execute('UPDATE bank_loans SET principal=:principal,interest_units=:interest_units,generated_units=:generated_units,last_at=:last_at,closed_at=:closed_at,repay_remainder=:repay_remainder WHERE id=:id',l)


def mutate(db,user,action,data,clock):
    import wallet,club_admin
    uid=user['id'];member_accounts.require_active(db,uid)
    if club_admin.identity(db,uid)['is_admin']:club_admin.require(db,uid)
    if not wallet.active(db):raise RuleError('點數制度尚未啟用。')
    if action not in ('deposit','withdraw','collect','borrow','repay','convert'):raise RuleError('銀行操作無效。')
    op=member_accounts.operation_id(data.get('operation_id'));amount=data.get('amount',0);revision=data.get('expected_revision');pay_all=data.get('pay_all',False);loan_id=data.get('loan_id')
    if type(pay_all) is not bool or pay_all and action!='repay':raise RuleError('還款方式無效。')
    limit=2_000_000 if action=='repay' else 1_000_000
    if action not in ('collect','convert') and (type(amount) is not int or not 1<=amount<=limit):raise RuleError(f'每次請填寫 1–{limit:,} 整數點數。')
    if action in ('collect','convert') and amount!=0:raise RuleError('領息不需指定點數。')
    if action in ('repay','convert') and (type(loan_id) is not int or not 1<=loan_id<2**63):raise RuleError('請重新確認要償還的貸款。')
    consent=data.get('accept_auto_repay')
    fields=[action,amount,revision,pay_all,loan_id]
    # Preserve receipts issued before consent was introduced; consent-bearing
    # requests remain distinct so retrying cannot silently change accepted terms.
    if consent is not None:fields.append(consent)
    fingerprint=hashlib.sha256(json.dumps(fields).encode()).hexdigest()
    old=db.execute('SELECT * FROM bank_operations WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise member_accounts.AccountError('同一操作編號已用於其他銀行操作。',409,'operation_conflict')
        return {**json.loads(old['result']),'replayed':True}
    a=account(db,uid,clock);l=loan(db,uid,clock);policy=settings(db);at=int(clock);ident=l['id'] if l else None;key='bank:'+op
    db.execute('SAVEPOINT bank_action')
    try:
        if action=='deposit':
            if a['balance']+amount>MAX_SAVINGS:raise RuleError('存款已達銀行容量上限。')
            wallet.transfer(db,uid,-amount,'bank_deposit',key,at);a['balance']+=amount
        elif action=='withdraw':
            if amount>a['balance']:raise RuleError('存款餘額不足。')
            a['balance']-=amount;wallet.transfer(db,uid,amount,'bank_withdraw',key,at)
        elif action=='collect':
            amount=a['interest_units']//UNIT
            if amount<1:raise RuleError('利息尚未累積到 1 點。')
            a['interest_units']-=amount*UNIT;wallet.transfer(db,uid,amount,'bank_interest',key,at)
        elif action=='borrow':
            if type(revision) is not int or revision!=policy['revision']:raise member_accounts.AccountError('借款條件已更新，請重新確認。',409,'stale_bank_settings')
            if l:raise RuleError('請先還清現有貸款。')
            if consent is not True:raise RuleError('請確認同意到期未還清時，將之後日常獎勵與會所收益的 20% 用於還款。')
            allowed=lending_limit(db,uid,clock)
            if amount>allowed:raise RuleError(f'本次最多可借 {allowed:,} 點。')
            ident=db.execute('INSERT INTO bank_loans(user_id,original,principal,rate_bps,interest_units,generated_units,started_at,due_at,last_at) VALUES(?,?,?,?,0,0,?,?,?)',(uid,amount,amount,policy['loan_bps'],at,at+policy['loan_days']*DAY,at)).lastrowid
            db.execute('UPDATE bank_loans SET terms_version=1,grace_until=?,cap_units=?,auto_repay=1 WHERE id=?',(at,amount*UNIT*5//100,ident))
            wallet.transfer(db,uid,amount,'bank_loan',key,at)
        elif action=='convert':
            if not l or l['id']!=loan_id:raise RuleError('請重新確認現有貸款。')
            if l['terms_version']:raise RuleError('這筆貸款已是新版條件。')
            if consent is not True:raise RuleError('請確認同意新條件與到期未還清後的獎勵 20% 還款。')
            if revision!=policy['revision']:raise RuleError('借款條件已更新，請重新確認。')
            save_loan(db,l)
            db.execute('UPDATE bank_loans SET terms_version=1,rate_bps=?,due_at=?,grace_until=?,cap_units=?,auto_repay=1 WHERE id=?',(policy['loan_bps'],at+7*DAY,at,l['generated_units']+l['principal']*UNIT*5//100,l['id']))
        else:
            if not l:raise RuleError('目前沒有未清償貸款。')
            if l['id']!=loan_id:raise member_accounts.AccountError('貸款已變更，請重新確認要還款的貸款。',409,'stale_loan')
            if pay_all:amount=debt(l)
            if amount>debt(l):raise RuleError('還款點數超過目前欠款，請重新確認。')
            interest=min(amount,(l['interest_units']+UNIT-1)//UNIT);principal=amount-interest
            if interest:wallet.transfer(db,uid,-interest,'bank_loan_interest',key+':interest',at)
            if principal:wallet.transfer(db,uid,-principal,'bank_repay_principal',key+':principal',at)
            # Rounded points already paid also consume the lifetime interest cap.
            rounding=max(0,interest*UNIT-l['interest_units'])
            l['generated_units']=min(l['cap_units'] if l['cap_units'] is not None else l['original']*UNIT,l['generated_units']+rounding)
            l['interest_units']=max(0,l['interest_units']-interest*UNIT);l['principal']-=principal
            if not l['principal'] and not l['interest_units']:l['closed_at']=at
            save_loan(db,l)
        save_account(db,a)
        balance=db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()[0]
        ledger=db.execute('INSERT INTO bank_ledger(user_id,kind,amount,savings_after,wallet_after,loan_id,created_at) VALUES(?,?,?,?,?,?,?)',(uid,action,amount,a['balance'],balance,ident,at)).lastrowid
        result=dict(ok=True,replayed=False,action=action,amount=amount,record_id=ledger)
        db.execute('INSERT INTO bank_operations VALUES(?,?,?,?)',(uid,op,fingerprint,json.dumps(result)))
        db.execute('RELEASE SAVEPOINT bank_action')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT bank_action');db.execute('RELEASE SAVEPOINT bank_action');raise
    return result


def admin_view(db,user):
    import club_admin
    club_admin.require(db,user['id'])
    return dict(settings=settings(db),history=[dict(r) for r in db.execute('SELECT id,actor_id,before_json,after_json,note,created_at FROM bank_settings_history ORDER BY id DESC LIMIT 20')])


def configure(db,user,data,clock):
    import club_admin
    club_admin.require(db,user['id']);op=member_accounts.operation_id(data.get('operation_id'))
    fields=('deposit_bps','loan_bps','loan_limit','loan_days');values={k:data.get(k) for k in fields};revision=data.get('revision');note=data.get('note')
    if any(type(v) is not int for v in values.values()) or type(revision) is not int:raise RuleError('銀行設定需為整數。')
    if not 0<=values['deposit_bps']<=500 or not 0<=values['loan_bps']<=1000:raise RuleError('存款日息需為 0–5%，貸款日息 0–10%。借款本金不參與存款計息。')
    if not 0<=values['loan_limit']<=1_000_000 or values['loan_days']!=7:raise RuleError('借款上限需為 0–1,000,000 點、期限固定 7 天；上限 0 代表暫停新借款。')
    if not isinstance(note,str) or not 1<=len(note.strip())<=200:raise RuleError('請填寫設定修改備註。')
    fingerprint=hashlib.sha256(json.dumps([values,revision,note.strip()],sort_keys=True).encode()).hexdigest()
    old=db.execute('SELECT fingerprint FROM bank_settings_history WHERE actor_id=? AND operation_id=?',(user['id'],op)).fetchone()
    if old:
        if old[0]!=fingerprint:raise member_accounts.AccountError('同一編號已用於其他設定。',409,'operation_conflict')
        return dict(ok=True,replayed=True)
    previous=settings(db)
    if previous['revision']!=revision:raise member_accounts.AccountError('設定已由其他管理員更新，請重新載入。',409,'stale_bank_settings')
    db.execute('SAVEPOINT bank_settings_change')
    try:
        # Settle savings at the old rate before changing the future rate.
        for row in db.execute('SELECT user_id FROM bank_accounts').fetchall():
            a=account(db,row[0],clock);a['rate_bps']=values['deposit_bps'];save_account(db,a)
        db.execute('UPDATE bank_settings SET revision=revision+1,deposit_bps=:deposit_bps,loan_bps=:loan_bps,loan_limit=:loan_limit,loan_days=:loan_days WHERE id=1',values)
        db.execute('INSERT INTO bank_settings_history(actor_id,operation_id,fingerprint,before_json,after_json,note,created_at) VALUES(?,?,?,?,?,?,?)',(user['id'],op,fingerprint,json.dumps(previous),json.dumps(settings(db)),note.strip(),int(clock)))
        db.execute('RELEASE SAVEPOINT bank_settings_change')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT bank_settings_change');db.execute('RELEASE SAVEPOINT bank_settings_change');raise
    return dict(ok=True,replayed=False)


def auto_repay(db,uid,reward,event_key,clock):
    """Only overdue consented loans; called inside the reward's transaction, never transfers."""
    import wallet
    l=loan(db,uid,clock)
    if not l or not l['auto_repay'] or int(clock)<l['due_at']:return
    amount=min((reward+l['repay_remainder'])//5,debt(l))
    l['repay_remainder']=(reward+l['repay_remainder'])%5
    if not amount:
        save_loan(db,l)
        return
    a=account(db,uid,clock)
    interest=min(amount,(l['interest_units']+UNIT-1)//UNIT);principal=amount-interest
    key='auto:'+event_key
    if interest:wallet.transfer(db,uid,-interest,'bank_loan_interest',key+':interest',clock)
    if principal:wallet.transfer(db,uid,-principal,'bank_repay_principal',key+':principal',clock)
    rounding=max(0,interest*UNIT-l['interest_units']);cap=l['cap_units'] if l['cap_units'] is not None else l['original']*UNIT
    l['generated_units']=min(cap,l['generated_units']+rounding)
    l['interest_units']=max(0,l['interest_units']-interest*UNIT);l['principal']-=principal
    if not l['principal'] and not l['interest_units']:l['closed_at']=int(clock)
    save_account(db,a);save_loan(db,l)
    balance=db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()[0]
    db.execute('INSERT INTO bank_ledger(user_id,kind,amount,savings_after,wallet_after,loan_id,created_at) VALUES(?,?,?,?,?,?,?)',(uid,'auto_repay',amount,a['balance'],balance,l['id'],int(clock)))
