"""Atomic transfers of existing virtual wallet points; never creates supply."""
import re
import wallet
import member_accounts


class TransferError(Exception):
    def __init__(self,message,status=400,reason='invalid_transfer'):
        self.message,self.status,self.reason=message,status,reason


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS point_transfers(
      id INTEGER PRIMARY KEY,sender_id INTEGER NOT NULL REFERENCES users(id),
      recipient_id INTEGER NOT NULL REFERENCES users(id),amount INTEGER NOT NULL CHECK(amount>0),
      note TEXT NOT NULL,operation_id TEXT NOT NULL,created_at REAL NOT NULL,
      CHECK(sender_id!=recipient_id),UNIQUE(sender_id,operation_id));
    CREATE INDEX IF NOT EXISTS point_transfers_sender ON point_transfers(sender_id,id DESC);
    CREATE INDEX IF NOT EXISTS point_transfers_recipient ON point_transfers(recipient_id,id DESC);
    ''')


def recipients(db,uid,search):
    if not isinstance(search,str) or not 1<=len(search.strip())<=80:raise TransferError('請輸入收款人的帳號或暱稱。')
    pattern='%'+search.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    rows=db.execute("SELECT id,username,nickname FROM users WHERE id!=? AND id NOT IN (SELECT user_id FROM account_states WHERE status!='active') AND (username LIKE ? ESCAPE '\\' OR nickname LIKE ? ESCAPE '\\') ORDER BY username LIMIT 20",(uid,pattern,pattern))
    return {'recipients':[dict(r) for r in rows]}


def public_record(row,uid):
    result=dict(row)
    result['direction']='out' if result['sender_id']==uid else 'in'
    return result


def record(db,ident,uid):
    row=db.execute('''SELECT t.id,t.sender_id,t.recipient_id,t.amount,t.note,t.created_at,
      s.username AS sender_username,s.nickname AS sender_nickname,
      r.username AS recipient_username,r.nickname AS recipient_nickname
      FROM point_transfers t JOIN users s ON s.id=t.sender_id JOIN users r ON r.id=t.recipient_id
      WHERE t.id=? AND (t.sender_id=? OR t.recipient_id=?)''',(ident,uid,uid)).fetchone()
    if not row:raise TransferError('找不到這筆轉帳。',404,'not_found')
    return public_record(row,uid)


def history(db,uid,clock,before=None):
    if before is not None:
        if not isinstance(before,str) or not re.fullmatch(r'[1-9]\d{0,17}',before):raise TransferError('紀錄游標無效。')
        before=int(before)
    rows=db.execute('''SELECT id FROM point_transfers WHERE (sender_id=? OR recipient_id=?)
      AND id<? ORDER BY id DESC LIMIT 31''',(uid,uid,before if before is not None else 9_223_372_036_854_775_807)).fetchall()
    return {'transfers':[record(db,r[0],uid) for r in rows[:30]],'next_before':str(rows[29][0]) if len(rows)>30 else None,
            'wallet':wallet.view(db,uid,clock),'server_time':clock}


def send(db,sender,data,clock):
    member_accounts.require_active(db,sender['id'])
    uid=sender['id'];target=data.get('recipient_id');username=data.get('recipient_username');amount=data.get('amount');note=data.get('note','');op=data.get('operation_id')
    if type(target) is not int or target<1 or target==uid:raise TransferError('請選擇其他帳號作為收款人。')
    if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_]{3,24}',username):raise TransferError('收款帳號無效。')
    if type(amount) is not int or not 1<=amount<=1_000_000:raise TransferError('每次可轉出 1–1,000,000 點整數點數。')
    if not isinstance(note,str) or len(note.strip())>120:raise TransferError('備註最多 120 字。')
    if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',op):raise TransferError('轉帳操作編號無效。')
    note=note.strip()
    previous=db.execute('SELECT * FROM point_transfers WHERE sender_id=? AND operation_id=?',(uid,op)).fetchone()
    if previous:
        receipt=record(db,previous['id'],uid)
        if (previous['recipient_id'],previous['amount'],previous['note'],receipt['recipient_username'].casefold())!=(target,amount,note,username.casefold()):
            raise TransferError('同一操作編號已用於另一筆轉帳，請先確認原紀錄。',409,'operation_conflict')
        return {'ok':True,'replayed':True,'transfer':receipt,'wallet':wallet.view(db,uid,clock)}
    recipient=db.execute('SELECT id,username FROM users WHERE id=?',(target,)).fetchone()
    if not recipient or recipient['username'].casefold()!=username.casefold():raise TransferError('收款帳號與編號不符，請重新選擇收款人。',404,'recipient_mismatch')
    if member_accounts.state(db,target)['status']!='active':raise TransferError('收款帳號已停用，請重新選擇。',409,'recipient_disabled')
    if not wallet.active(db):raise TransferError('籌碼制度更新中，請稍候。')
    balance=wallet.view(db,uid,clock)['balance']
    if balance<amount:raise TransferError(f'可轉出的錢包餘額只有 {balance:,} 點；桌上及底池的籌碼需先離桌取回。',400,'insufficient_balance')
    # Savepoint also protects direct callers from leaving only one side applied.
    db.execute('SAVEPOINT point_transfer')
    try:
        inserted=db.execute('INSERT INTO point_transfers(sender_id,recipient_id,amount,note,operation_id,created_at) VALUES(?,?,?,?,?,?)',(uid,target,amount,note,op,clock))
        ident=inserted.lastrowid;key=f'transfer:{ident}'
        wallet.transfer(db,uid,-amount,'transfer_out',key,clock)
        wallet.transfer(db,target,amount,'transfer_in',key,clock)
        db.execute('RELEASE SAVEPOINT point_transfer')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT point_transfer');db.execute('RELEASE SAVEPOINT point_transfer');raise
    return {'ok':True,'replayed':False,'transfer':record(db,ident,uid),'wallet':wallet.view(db,uid,clock)}
