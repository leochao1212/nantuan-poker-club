"""Private-table admission, single-click starts and privacy-filtered replay frames."""
import hmac
import json
import secrets
import poker_engine as engine

READY_FRESH_SECONDS = 30


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS replay_steps (
        room_id INTEGER NOT NULL REFERENCES poker_rooms(id), hand_number INTEGER NOT NULL,
        step INTEGER NOT NULL, at REAL NOT NULL, label TEXT NOT NULL,
        public_state TEXT NOT NULL, private_state TEXT NOT NULL,
        PRIMARY KEY(room_id,hand_number,step));
    ''')


def create_party(room, data, uid):
    private=data.get('private',False)
    if type(private) is not bool:raise engine.RuleError('包廂設定無效。')
    # ready_required from older clients is intentionally ignored for every game.
    if private:
        room['party']={'private':True,'required':False,'code':secrets.token_urlsafe(24),
                       'members':[uid],'ready':{}}


def require_access(room, uid):
    party=room.get('party',{})
    if party.get('private') and uid not in party.get('members',[]):
        raise engine.RuleError('這是私人包廂，請使用朋友分享的邀請連結加入。')


def redeem(room, uid, code):
    party=room.get('party')
    if not party or not isinstance(code,str) or not hmac.compare_digest(code,party['code']):
        raise engine.RuleError('包廂邀請連結無效，請向桌主索取。')
    if room['status']=='closed':raise engine.RuleError('這個包廂已經結束。')
    if uid not in party['members']:party['members'].append(uid)


def required_stack(room):
    if room.get('game_type')=='mahjong':
        import mahjong_engine
        return mahjong_engine.reserve(room)
    if room.get('game_type')=='big2':
        import arcade_engine
        return arcade_engine.big2_reserve(room)
    return room.get('stake',1) if room.get('game_type') in ('blackjack','baccarat') else 1


def party_view(room, uid, seen, clock):
    party=room.get('party')
    if not party or not party.get('private'):return None
    players=[dict(user_id=s['user_id'],nickname=s['nickname'],
                  online=clock-max(seen.get(s['user_id'],0),s['joined_at'])<READY_FRESH_SECONDS,
                  funded=s['stack']>=required_stack(room))
             for s in room['seats'] if not s['away'] and not s['leaving']]
    minimum=4 if room.get('game_type') in ('big2','mahjong') else 2 if room.get('game_type','holdem')=='holdem' else 1
    result=dict(private=True,required=False,players=players,minimum=minimum,
                can_start=room['status']=='waiting' and sum(p['funded'] for p in players)>=minimum,
                owner_id=room['owner_id'])
    if uid in party['members']:result['invite_code']=party['code']
    return result


def set_ready(room, uid, data):
    raise engine.RuleError('準備功能已取消，入座後可直接按開局。請重新整理牌桌。')


def check_start(db, room, uid, clock):
    # Private invitations still guard admission; the game engine checks minimum
    # players, available chips and turn ownership without a second ready phase.
    return


def capture(db,room,driver,clock,label=None):
    hand=room.get('hand')
    if not hand:return
    public=driver.public_view(room,-1)['hand']
    # Explicit fields exclude shoe, future hazards, burns and session/receipt data.
    state={key:public[key] for key in ('phase','board','dealer','current_play','actor','number','color','dice','total','triple','reels','selected','steps','cashout','summary','pots','results','uncontested','last_discard','wall_count','streak','round_wind','payments') if key in public}
    state['game_type']=room.get('game_type','holdem')
    state['players']=[]
    for p in public['players']:
        fields=('user_id','nickname','seat','stack','starting_stack','street_bet','contribution','last_action','folded','hole','cards','card_count','hands','bets','side','tiles','tile_count','flowers','melds','river','wind')
        state['players'].append({k:p[k] for k in fields if k in p})
    private={str(p['user_id']):{k:p[k] for k in ('hole','cards','bets','side','tiles','melds') if k in p} for p in hand['players']}
    encoded=json.dumps(state,ensure_ascii=False,separators=(',',':'))
    own=json.dumps(private,separators=(',',':'))
    previous=db.execute('SELECT step,public_state,private_state FROM replay_steps WHERE room_id=? AND hand_number=? ORDER BY step DESC LIMIT 1',(room['id'],room['hand_no'])).fetchone()
    if not previous and hand['phase']=='showdown' and db.execute('SELECT 1 FROM poker_hands WHERE room_id=? AND hand_number=?',(room['id'],room['hand_no'])).fetchone():return
    if previous and previous[1]==encoded and previous[2]==own:return
    step=previous[0]+1 if previous else 0
    if step>=1500:return  # Bound malformed or excessively long hands.
    label=label or (room['log'][-1]['text'] if room['log'] else '牌局更新')
    db.execute('INSERT INTO replay_steps VALUES(?,?,?,?,?,?,?)',(room['id'],room['hand_no'],step,clock,label[:240],encoded,own))


def replay(db,room,number,uid):
    require_access(room,uid)
    settled=db.execute('SELECT public_state FROM poker_hands WHERE room_id=? AND hand_number=?',(room['id'],number)).fetchone()
    if not settled:raise engine.RuleError('只能重播已結束的牌局。')
    rows=db.execute('SELECT * FROM replay_steps WHERE room_id=? AND hand_number=? ORDER BY step',(room['id'],number)).fetchall()
    frames=[]
    for row in rows:
        state=json.loads(row['public_state']);own=json.loads(row['private_state']).get(str(uid),{})
        for p in state['players']:
            if p['user_id']==uid:p.update(own)
        frames.append({'step':row['step'],'at':row['at'],'label':row['label'],'state':state})
    return {'room_id':room['id'],'number':number,'frames':frames,'legacy':not bool(rows),
            'result':json.loads(settled[0]),'privacy':'只顯示當時已公開的資訊，以及你自己的手牌。'}
