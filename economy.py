"""Friends economy: bounded supplements, frozen per deal, never weighted cards."""
from copy import deepcopy
import json

HAPPY_CAP = 6000
TITLE_CAP = 1800
VERSION = 'friends-economy-v1'
OLD_RATES = (60,90,120,180,240,300,360,420,480,600)


def initialize(db, clock):
    import wallet, clubhouse, bank
    db.executescript('''CREATE TABLE IF NOT EXISTS economy_awards(
      user_id INTEGER NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL,
      event_key TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>=0),
      PRIMARY KEY(user_id,kind,event_key));
      CREATE INDEX IF NOT EXISTS economy_awards_day ON economy_awards(user_id,day,kind);''')
    if db.execute('SELECT 1 FROM wallet_meta WHERE key=?',(VERSION,)).fetchone():return
    db.execute('SAVEPOINT friends_economy')
    try:
        # Close the old rate, including its old storage cap, without repricing time.
        for r in db.execute('SELECT * FROM club_income').fetchall():
            rate=OLD_RATES[r['production_level']]*clubhouse.SPEED_STEPS[r['decor_level']]//2
            units=max(r['stored_units'],min(rate*clubhouse.HOURS[r['storage_level']]*clubhouse.UNIT,
                      r['stored_units']+max(0,int(clock*1000)-int(r['last_at']*1000))*rate))
            db.execute('UPDATE club_income SET stored_units=?,last_at=?,revision=revision+1 WHERE user_id=?',
                       (units,max(clock,r['last_at']),r['user_id']))
        # Preserve all interest accrued before borrowed principal becomes ineligible.
        for r in db.execute('SELECT * FROM bank_accounts').fetchall():
            a=dict(r);a['interest_units']=min(bank.MAX_SAVINGS*bank.UNIT,a['interest_units']+a['balance']*a['rate_bps']*max(0,int(clock)-a['last_at']))
            a['last_at']=max(a['last_at'],int(clock));bank.save_account(db,a)
        old_bank=bank.settings(db)
        db.execute('UPDATE bank_settings SET revision=revision+1,loan_bps=10,loan_limit=100000,loan_days=7 WHERE id=1')
        # Existing disabled/admin accounts do not receive a migration gift.
        for r in db.execute("SELECT w.user_id FROM wallets w JOIN wallet_ledger l ON l.user_id=w.user_id AND l.kind='initial' AND l.amount=3000 WHERE w.user_id NOT IN (SELECT user_id FROM account_states WHERE status!='active') AND w.user_id NOT IN (SELECT user_id FROM club_admins)").fetchall():
            wallet.transfer(db,r[0],7000,'economy_gift',VERSION+':gift',clock)
        db.execute('INSERT INTO wallet_meta VALUES(?,?)',(VERSION,json.dumps(dict(activated_at=clock,old_bank=old_bank,new_bank=bank.settings(db)))))
        db.execute('RELEASE SAVEPOINT friends_economy')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT friends_economy');db.execute('RELEASE SAVEPOINT friends_economy');raise


def remaining(db, uid, day, kind):
    cap=HAPPY_CAP if kind=='happy' else TITLE_CAP
    spent=db.execute('SELECT COALESCE(sum(amount),0) FROM economy_awards WHERE user_id=? AND day=? AND kind=?',(uid,day,kind)).fetchone()[0]
    return max(0,cap-spent)


def view(db, uid, clock):
    import wallet
    day=wallet.day(clock)
    return dict(day=day,happy_cap=HAPPY_CAP,happy_remaining=remaining(db,uid,day,'happy'),
                title_cap=TITLE_CAP,title_remaining=remaining(db,uid,day,'title'))


def prepare(db, room, clock):
    import rewards, wallet
    room['_next_economy']={'day':wallet.day(clock),'players':{str(s['user_id']):
        dict(happy=remaining(db,s['user_id'],wallet.day(clock),'happy'),used=0,
             title=rewards.game_perk(db,s['user_id'])) for s in room['seats']}}


def attach(room):
    if room.get('_next_economy') and room.get('hand'):
        room['hand']['economy']=deepcopy(room['_next_economy'])


def benefit(room, uid, requested):
    """Legacy hands remain uncapped. New deals consume their frozen allowance."""
    h=room['hand'];snapshot=h.get('economy')
    if not snapshot:return requested
    p=snapshot['players'].get(str(uid))
    if not p:return 0
    amount=min(max(0,requested),max(0,p['happy']-p['used']));p['used']+=amount
    return amount


def settle(db, room, hand_id, clock):
    import wallet
    h=room['hand'];snapshot=h.get('economy')
    if not snapshot:return
    game=room.get('game_type','holdem');players={p['user_id']:p for p in h['players']}
    for result in h['results']:
        uid=result['user_id'];p=players[uid];s=snapshot['players'].get(str(uid),{});day=snapshot['day'];key='hand:'+str(hand_id)
        db.execute('INSERT OR IGNORE INTO economy_awards VALUES(?,?,?,?,?)',(uid,day,'happy',key,s.get('used',0)))
        perk=s.get('title') or {};base=0
        if perk.get('game') not in (game,'all'):continue
        contribution=p.get('contribution',0)
        # No zero-risk cashouts, skipped hands or uncalled poker bets count.
        if game=='inbetween':contribution=h.get('stake',0) if h.get('third') else 0
        if game in ('mines','tower') and not h.get('selected'):continue
        if contribution<=0:continue
        mode=perk['mode']
        if mode=='play':base=min(contribution,1000)
        elif mode=='win':base=min(contribution,max(0,result['profit']-s.get('used',0)))
        elif mode=='loss':base=min(contribution,max(0,-result['profit']))
        elif mode=='post' and h.get('third') and ('撞柱' in result['rank']):
            base=max(0,-result['profit'])
        amount=min(base*perk['bps']//10000,perk['per_hand'],remaining(db,uid,day,'title'))
        if amount and db.execute('INSERT OR IGNORE INTO economy_awards VALUES(?,?,?,?,?)',(uid,day,'title',key,amount)).rowcount:
            wallet.transfer(db,uid,amount,'title_game_bonus','title:'+key,clock)
            result['title_bonus']=amount
