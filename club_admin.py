"""Explicit administrator roles and audited, idempotent virtual-chip adjustments."""
import json
import re
import wallet
import member_accounts
from poker_engine import RuleError


class AdminError(Exception):
    def __init__(self,message,status=403,reason='admin_required'):
        self.message,self.status,self.reason=message,status,reason


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS club_admins(user_id INTEGER PRIMARY KEY REFERENCES users(id),
      password_change_required INTEGER NOT NULL DEFAULT 1,created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS admin_grants(id INTEGER PRIMARY KEY,actor_id INTEGER NOT NULL REFERENCES users(id),
      target_id INTEGER NOT NULL REFERENCES users(id),amount INTEGER NOT NULL CHECK(amount>0),note TEXT NOT NULL,
      operation_id TEXT NOT NULL,created_at REAL NOT NULL,UNIQUE(actor_id,operation_id));
    CREATE TABLE IF NOT EXISTS admin_adjustments(id INTEGER PRIMARY KEY,actor_id INTEGER NOT NULL REFERENCES users(id),
      target_id INTEGER NOT NULL REFERENCES users(id),amount INTEGER NOT NULL CHECK(amount<>0),note TEXT NOT NULL,
      operation_id TEXT NOT NULL,created_at REAL NOT NULL,UNIQUE(actor_id,operation_id));
    ''')


def identity(db,uid):
    row=db.execute('SELECT password_change_required FROM club_admins WHERE user_id=?',(uid,)).fetchone()
    return {'is_admin':bool(row),'password_change_required':bool(row and row[0])}


def require(db,uid,allow_password_change=False):
    role=identity(db,uid)
    if not role['is_admin']:raise AdminError('只有管理員可以使用此功能。')
    if role['password_change_required'] and not allow_password_change:
        raise AdminError('首次登入請先更換管理員密碼。',reason='password_change_required')


def grant(db,actor,data,clock):
    require(db,actor['id'])
    uid,amount,note,op=(data.get(k) for k in ('user_id','amount','note','operation_id'))
    if type(uid) is not int or type(amount) is not int or not 1<=amount<=1_000_000:
        raise RuleError('對象需為有效帳號，每次可發放 1–1,000,000 點整數籌碼。')
    if not isinstance(note,str) or not 1<=len(note.strip())<=200:raise RuleError('請填寫 1–200 字的發放備註。')
    if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',op):raise RuleError('發放操作編號無效。')
    note=note.strip()
    previous=db.execute('SELECT * FROM admin_grants WHERE actor_id=? AND operation_id=?',(actor['id'],op)).fetchone()
    if previous:
        if (previous['target_id'],previous['amount'],previous['note'])!=(uid,amount,note):
            raise AdminError('同一操作編號已用於另一筆發放，請先確認原紀錄。',409,'operation_conflict')
        return {'ok':True,'grant_id':previous['id'],'replayed':True,'wallet':wallet.view(db,uid,clock)}
    if not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():raise AdminError('找不到這個帳號。',404,'not_found')
    if member_accounts.state(db,uid)['status']=='deleted':raise RuleError('此帳號已刪除，不能再發放籌碼。')
    if not wallet.active(db):raise RuleError('籌碼制度更新中，請稍候再發放。')
    wallet.transfer(db,uid,amount,'admin_grant',f'admin:{actor["id"]}:{op}',clock)
    result=db.execute('INSERT INTO admin_grants(actor_id,target_id,amount,note,operation_id,created_at) VALUES(?,?,?,?,?,?)',
                      (actor['id'],uid,amount,note,op,clock))
    return {'ok':True,'grant_id':result.lastrowid,'replayed':False,'wallet':wallet.view(db,uid,clock)}


def adjust(db,actor,data,clock):
    require(db,actor['id'])
    uid,amount,note,op=(data.get(k) for k in ('user_id','amount','note','operation_id'))
    if type(uid) is not int or type(amount) is not int or not 1<=abs(amount)<=1_000_000:
        raise RuleError('對象需為有效帳號，每次可增加或扣除 1–1,000,000 點整數籌碼。')
    if not isinstance(note,str) or not 1<=len(note.strip())<=200:raise RuleError('請填寫 1–200 字的調整備註。')
    if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',op):raise RuleError('調整操作編號無效。')
    note=note.strip()
    previous=db.execute('SELECT * FROM admin_adjustments WHERE actor_id=? AND operation_id=?',(actor['id'],op)).fetchone()
    if previous:
        if (previous['target_id'],previous['amount'],previous['note'])!=(uid,amount,note):
            raise AdminError('同一操作編號已用於另一筆調整，請先確認原紀錄。',409,'operation_conflict')
        return {'ok':True,'adjustment_id':previous['id'],'replayed':True,'wallet':wallet.view(db,uid,clock)}
    if not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():raise AdminError('找不到這個帳號。',404,'not_found')
    if member_accounts.state(db,uid)['status']=='deleted':raise RuleError('此帳號已刪除，不能再調整籌碼。')
    if not wallet.active(db):raise RuleError('籌碼制度更新中，請稍候再調整。')
    balance=wallet.view(db,uid,clock)['balance']
    if balance+amount<0:
        raise RuleError(f'錢包餘額只有 {balance:,} 點，無法扣除 {abs(amount):,} 點；桌上與底池的籌碼需先離桌取回。')
    wallet.transfer(db,uid,amount,'admin_adjustment',f'adjust:{actor["id"]}:{op}',clock)
    result=db.execute('INSERT INTO admin_adjustments(actor_id,target_id,amount,note,operation_id,created_at) VALUES(?,?,?,?,?,?)',
                      (actor['id'],uid,amount,note,op,clock))
    return {'ok':True,'adjustment_id':result.lastrowid,'replayed':False,'wallet':wallet.view(db,uid,clock)}


def accounts(db,actor,clock,search='',page=1):
    require(db,actor['id'])
    if not isinstance(search,str) or len(search)>80:raise RuleError('搜尋文字最多 80 字。')
    try:page=int(page)
    except (ValueError,TypeError):raise RuleError('頁碼無效。')
    if not 1<=page<=1_000_000:raise RuleError('頁碼無效。')
    pattern='%'+search.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    where="NOT EXISTS (SELECT 1 FROM account_states s WHERE s.user_id=u.id AND s.status='deleted') AND (u.username LIKE ? ESCAPE '\\' OR u.nickname LIKE ? ESCAPE '\\')"
    count=db.execute('SELECT count(*) FROM users u WHERE '+where,(pattern,pattern)).fetchone()[0]
    totals=wallet.in_play(db)
    import bank
    banking=bank.assets(db,clock)
    seats={}
    for row in db.execute("SELECT id,name,status,state FROM poker_rooms WHERE status!='closed'"):
        for seat in json.loads(row['state'])['seats']:
            seats[seat['user_id']]={'id':row['id'],'name':row['name'],'status':row['status'],'seat':seat['seat']+1,
                                   'stack':seat['stack'],'away':seat['away'],'leaving':seat['leaving']}
    rows=db.execute('''SELECT u.id,u.username,u.nickname,u.created_at,COALESCE(w.balance,0) AS balance,
      COALESCE(p.last_seen,0) AS last_seen,COALESCE(a.password_change_required,0) AS password_change_required,
      CASE WHEN a.user_id IS NULL THEN 0 ELSE 1 END AS is_admin
      FROM users u LEFT JOIN wallets w ON w.user_id=u.id LEFT JOIN poker_presence p ON p.user_id=u.id
      LEFT JOIN club_admins a ON a.user_id=u.id WHERE '''+where+' ORDER BY u.id LIMIT 50 OFFSET ?',
      (pattern,pattern,(page-1)*50))
    people=[]
    for row in rows:
        person=dict(row);uid=person['id']
        access=member_accounts.state(db,uid)
        person.update(online=clock-person['last_seen']<16,in_play=totals.get(uid,0),
                      total=person['balance']+totals.get(uid,0)+banking.get(uid,0),room=seats.get(uid),bank=bank.summary(db,uid,clock),status=access['status'],state_revision=access['revision'],status_reason=access['reason'])
        people.append(person)
    history=[dict(row) for row in db.execute('''SELECT 'admin:'||g.id AS id,g.amount AS amount,g.note AS note,g.created_at AS created_at,
      a.nickname AS actor,a.username AS actor_username,t.nickname AS target,t.username AS target_username
      FROM admin_grants g JOIN users a ON a.id=g.actor_id JOIN users t ON t.id=g.target_id
      UNION ALL SELECT 'adjust:'||g.id,g.amount,g.note,g.created_at,a.nickname,a.username,t.nickname,t.username
      FROM admin_adjustments g JOIN users a ON a.id=g.actor_id JOIN users t ON t.id=g.target_id
      UNION ALL SELECT 'owner:'||l.id,l.amount,'站方要求的維護補給',l.created_at,
      '站方維護','system',t.nickname,t.username FROM wallet_ledger l JOIN users t ON t.id=l.user_id
      WHERE l.kind='owner_grant' ORDER BY created_at DESC,id DESC LIMIT 50''')]
    account_history=[dict(r) for r in db.execute('''SELECT e.id,e.action,e.reason,e.username_snapshot,e.nickname_snapshot,e.created_at,u.username AS actor_username FROM admin_account_events e JOIN users u ON u.id=e.actor_id ORDER BY e.id DESC LIMIT 50''')]
    return {'accounts':people,'history':history,'account_history':account_history,'total_matches':count,'page':page,'page_size':50,
            'total_accounts':db.execute("SELECT count(*) FROM users u WHERE NOT EXISTS (SELECT 1 FROM account_states s WHERE s.user_id=u.id AND s.status='deleted')").fetchone()[0],
            'online_accounts':db.execute("SELECT count(*) FROM poker_presence p WHERE last_seen>? AND NOT EXISTS (SELECT 1 FROM account_states s WHERE s.user_id=p.user_id AND s.status='deleted')",(clock-16,)).fetchone()[0],
            'total_chips':db.execute('SELECT COALESCE(sum(balance),0) FROM wallets').fetchone()[0]+sum(totals.values())+sum(banking.values()),
            'server_time':clock}
