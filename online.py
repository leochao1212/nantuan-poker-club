"""Transactional storage and HTTP-facing operations for the live poker engine."""
import json
import re
import time
import hashlib
import poker_engine as engine
import wallet
import clubhouse
import social
import club_admin
import mahjong_engine
import arcade_engine
import bonus_engine
import rewards
import member_accounts
import club_features
import view_cache
import game_settings
import result_stats

OFFLINE_GRACE_SECONDS = 120


def deployment_paused(db, clock):
    """A renewable lease blocks new deals while existing hands finish."""
    row = db.execute("SELECT value FROM settings WHERE key='deploy_pause_until'").fetchone()
    try:
        return bool(row and float(row[0]) > clock)
    except (ValueError, TypeError):
        return False


def require_new_deal_allowed(db, clock):
    if deployment_paused(db, clock):
        raise engine.RuleError('系統準備更新，請完成目前牌局；稍後即可開新局。')

def rules(room):
    return mahjong_engine if room.get('game_type')=='mahjong' else engine if room.get('game_type','holdem')=='holdem' else bonus_engine if room['game_type'] in bonus_engine.CATALOG else arcade_engine


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS poker_rooms (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner_id INTEGER NOT NULL REFERENCES users(id),
        status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL,
        created_at REAL NOT NULL, updated_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS poker_hands (
        id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL REFERENCES poker_rooms(id),
        hand_number INTEGER NOT NULL, public_state TEXT NOT NULL, finished_at REAL NOT NULL,
        UNIQUE(room_id,hand_number));
    CREATE TABLE IF NOT EXISTS poker_results (
        hand_id INTEGER NOT NULL REFERENCES poker_hands(id), user_id INTEGER NOT NULL REFERENCES users(id),
        profit INTEGER NOT NULL, payout INTEGER NOT NULL, rank TEXT NOT NULL,
        PRIMARY KEY(hand_id,user_id));
    CREATE TABLE IF NOT EXISTS poker_sessions (
        id TEXT PRIMARY KEY, room_id INTEGER NOT NULL REFERENCES poker_rooms(id), user_id INTEGER NOT NULL REFERENCES users(id),
        bought INTEGER NOT NULL, final_stack INTEGER NOT NULL, joined_at REAL NOT NULL, left_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS poker_presence (
        user_id INTEGER PRIMARY KEY REFERENCES users(id), room_id INTEGER, last_seen REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS poker_operations (
        user_id INTEGER NOT NULL REFERENCES users(id), operation_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL,
        PRIMARY KEY(user_id,operation_id));
    -- A reverse scan also orders equal timestamps by rowid DESC. Avoid sorting
    -- an account's entire receipt history for every HTTP and SSE snapshot.
    CREATE INDEX IF NOT EXISTS poker_operations_recent ON poker_operations(user_id,created_at);
    """)
    member_accounts.initialize(db)
    club_features.initialize(db)
    rewards.initialize(db)
    social.initialize(db)
    club_admin.initialize(db)
    wallet.initialize(db,time.time())
    upgrade_dice_capacity(db)
    upgrade_big2_rules(db)
    view_cache.initialize(db)
    game_settings.initialize(db)


def upgrade_big2_rules(db):
    """Apply new rules to the next deal; active hands keep their original rules."""
    for row in db.execute("SELECT id,state FROM poker_rooms WHERE status!='closed'").fetchall():
        room=json.loads(row['state'])
        if room.get('game_type')=='big2' and 'big2_rules' not in room:
            room['big2_rules']=arcade_engine.big2_options()
            hand=room.get('hand')
            if hand and hand.get('phase')=='showdown':
                winner=next((q['user_id'] for q in hand.get('results',[]) if q['profit']>0),None)
                if winner:room['big2_last_winner']=winner
            db.execute('UPDATE poker_rooms SET state=?,revision=revision+1 WHERE id=?',(json.dumps(room,ensure_ascii=False),row['id']))


def upgrade_dice_capacity(db):
    """Keep existing tables, stakes and settled hands while exposing six seats."""
    for row in db.execute("SELECT id,state FROM poker_rooms WHERE status!='closed'").fetchall():
        room=json.loads(row['state'])
        if room.get('game_type')=='dice' and room.get('capacity')!=6:
            room['capacity']=6
            db.execute('UPDATE poker_rooms SET state=?,revision=revision+1 WHERE id=?',(json.dumps(room,ensure_ascii=False),row['id']))


def decode(row):
    room = json.loads(row["state"])
    room["id"], room["revision"] = row["id"], row["revision"]
    return room


def get_room(db, room_id):
    row = db.execute("SELECT * FROM poker_rooms WHERE id=?", (room_id,)).fetchone()
    if not row:
        raise engine.RuleError("找不到這張牌桌。")
    return decode(row)


def save(db, room, clock):
    if room.get("game_type")=="blackjack":
        for seat in room["seats"]:
            if not arcade_engine.blackjack_ready(room,seat):seat.pop("blackjack_ready_for",None)
    hand = room.get("hand")
    replay_label=room.pop('_replay_label',None)
    club_features.capture(db,room,rules(room),clock,replay_label)
    if hand and hand["phase"] == "showdown":
        result = db.execute("INSERT OR IGNORE INTO poker_hands(room_id,hand_number,public_state,finished_at) VALUES(?,?,?,?)",
            (room["id"], room["hand_no"], json.dumps(rules(room).public_view(room, -1)["hand"], ensure_ascii=False), hand["finished_at"]))
        if result.rowcount:
            for row in hand["results"]:
                db.execute("INSERT INTO poker_results VALUES(?,?,?,?,?)", (result.lastrowid, row["user_id"], row["profit"], row["payout"], row["rank"]))
                clubhouse.record(db,row["user_id"],row["profit"],"game","hand:"+str(result.lastrowid),hand["finished_at"],game=True)
    for departure in room["departures"]:
        inserted=db.execute("INSERT OR IGNORE INTO poker_sessions VALUES(?,?,?,?,?,?,?)",
            (departure["session_id"], room["id"], departure["user_id"], departure["bought"], departure["stack"], departure["joined_at"], departure["left_at"]))
        if inserted.rowcount:
            wallet.transfer(db,departure["user_id"],departure["stack"],"leave","leave:"+departure["session_id"],clock)
    room["departures"] = []
    room["revision"] += 1
    db.execute("UPDATE poker_rooms SET name=?,owner_id=?,status=?,revision=?,state=?,updated_at=? WHERE id=?",
        (room["name"], room["owner_id"], room["status"], room["revision"], json.dumps(room, ensure_ascii=False), clock, room["id"]))


def maintenance(db, clock=None, due_at=None):
    clock = time.time() if clock is None else clock
    due_at = clock if due_at is None else due_at
    changed = False
    seen = {row['user_id']:row['last_seen'] for row in db.execute('SELECT user_id,last_seen FROM poker_presence')}
    for row in db.execute("SELECT * FROM poker_rooms WHERE status!='closed'").fetchall():
        room = decode(row)
        room_changed = False
        for seat in list(room['seats']):
            if not engine.seated(room,seat['user_id']) or seat['leaving']:
                continue
            last_seen = max(seen.get(seat['user_id'],0),seat['joined_at'])
            if due_at-last_seen < OFFLINE_GRACE_SECONDS:
                continue
            engine.log(room,f"{seat['nickname']} 離線超過 {OFFLINE_GRACE_SECONDS} 秒，系統自動安排離桌",clock)
            rules(room).leave(room,seat['user_id'],clock)
            room_changed = True
        room_changed = rules(room).tick(room, clock, due_at) or room_changed
        if room_changed:
            save(db, room, clock)
            changed = True
    changed = wallet.maybe_activate(db,clock) or changed
    changed = social.cleanup(db,clock) or changed
    return changed


def presence(db, user_id, room_id, clock):
    row = db.execute("SELECT * FROM poker_presence WHERE user_id=?", (user_id,)).fetchone()
    if not row or clock-row["last_seen"] >= 5 or row["room_id"] != room_id:
        db.execute("INSERT INTO poker_presence VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET room_id=excluded.room_id,last_seen=excluded.last_seen",
            (user_id, room_id, clock))


def current_room(db, user_id):
    # Project only seat IDs inside SQLite; repeatedly decoding every other
    # table's private hand for each reply scales poorly with concurrent rooms.
    row=db.execute("""SELECT r.id FROM poker_rooms r,json_each(r.state,'$.seats') s
        WHERE r.status!='closed' AND json_extract(s.value,'$.user_id')=? LIMIT 1""",(user_id,)).fetchone()
    return row[0] if row else None


def heartbeat(db, user_id, room_id, clock):
    room = None
    if room_id is not None:
        if type(room_id) is not int or room_id <= 0:raise engine.RuleError('牌桌編號無效。')
        room = get_room(db,room_id)
        club_features.require_access(room,user_id)
    presence(db,user_id,room_id,clock)
    # Only a real client heartbeat on its table restores a timed-out seat.
    # Server-side SSE snapshots must never bring an absent player back.
    seat = engine.seated(room,user_id) if room else None
    resumed = bool(seat and seat['away'] and not seat['leaving'] and room['status']!='closed')
    if resumed:
        engine.return_to_play(room,user_id,clock)
        seat.pop('away_reason',None)
        save(db,room,clock)
    return {'ok':True,'server_time':clock,'offline_grace_seconds':OFFLINE_GRACE_SECONDS,'resumed':resumed,'room_revision':room['revision'] if room else None}


def lobby_fingerprint(room):
    """Only changes visible in a lobby card need to wake lobby subscribers.

    Per-turn revisions/cards/actions belong to the table channel. Seat stacks,
    membership, private invitation access, settings and hand boundaries do not.
    """
    fields=tuple(room.get(k) for k in ('name','status','owner_id','small_blind','big_blind','buy_in','hand_no','game_type','capacity','stake'))
    seats=tuple(tuple(s.get(k) for k in ('user_id','nickname','stack','away','leaving')) for s in room['seats'])
    party=room.get('party',{})
    return fields,seats,party.get('private',False),tuple(party.get('members',[]))


def lobby(db, user, clock, *, touch_presence=True):
    if touch_presence:presence(db, user["id"], None, clock)
    rooms = []
    for row in db.execute("SELECT * FROM poker_rooms WHERE status!='closed' ORDER BY id DESC"):
        room = decode(row)
        if room.get('party',{}).get('private') and user['id'] not in room['party']['members']:continue
        rooms.append({k: room[k] for k in ("id", "revision", "name", "status", "owner_id", "small_blind", "big_blind", "buy_in", "hand_no")})
        rooms[-1].update(game_type=room.get('game_type','holdem'),capacity=room.get('capacity',6),stake=room.get('stake',0))
        rooms[-1]['private']=room.get('party',{}).get('private',False)
        rooms[-1]["seats"] = [{k: p[k] for k in ("user_id", "nickname", "stack", "away", "leaving")} for p in room["seats"]]
    people=[dict(row) for row in db.execute("SELECT u.id,u.username,u.nickname,COALESCE(w.balance,0) AS balance,COALESCE(p.last_seen,0) AS last_seen FROM users u LEFT JOIN poker_presence p ON p.user_id=u.id LEFT JOIN wallets w ON w.user_id=u.id")]
    stats=view_cache.shared(db,'player_results',('poker_results','poker_hands'),lambda:result_stats.players(db))
    for person in people:
        result=stats.get(person['id'],{})
        person.update({k:result.get(k,0) for k in ('hands','profit','wins')})
    cosmetics=rewards.profile_map(db);profiles=member_accounts.public_profiles(db)
    disabled={r[0] for r in db.execute("SELECT user_id FROM account_states WHERE status!='active'")}
    people=[p for p in people if p['id'] not in disabled]
    for person in people:person.update(cosmetics=cosmetics.get(person['id'],{}),**profiles.get(person['id'],{}))
    for room in rooms:
        for seat in room['seats']:seat.update(cosmetics=cosmetics.get(seat['user_id'],{}),**profiles.get(seat['user_id'],{}))
    totals=wallet.in_play(db)
    for person in people:person['total_chips']=person['balance']+totals.get(person['id'],0)
    people.sort(key=lambda u:(-u['total_chips'],-u['profit'],u['id']))
    for index,person in enumerate(people):person['rank']=index+1
    member_count=len(people)
    online_count=sum(clock-u['last_seen']<16 for u in people)
    own=next((u for u in people if u['id']==user['id']),None)
    people=people[:100]
    if own and own not in people:people.append(own)
    return {"club":rewards.view(db,user['id'],clock,profiles=profiles,appearances=cosmetics),"total_members":member_count,"online_count":online_count,"wallet":wallet.view(db,user['id'],clock,totals),"me": {**{k: user[k] for k in ("id", "username", "nickname")},**profiles.get(user['id'],{}),"cosmetics":cosmetics.get(user["id"],{}),**club_admin.identity(db,user['id'])}, "users": people,
        "betting_limits":game_settings.current(db,'limits'),"rooms": rooms, "current_room_id": current_room(db, user["id"]), "server_time": clock,
        "invite_code": db.execute("SELECT value FROM settings WHERE key='invite_code'").fetchone()[0],
        "total_hands": db.execute("SELECT count(*) FROM poker_hands").fetchone()[0]}


def room_view(db, room_id, user_id, clock, *, touch_presence=True):
    room = get_room(db, room_id)
    kind=room.get('game_type','holdem')
    club_features.require_access(room,user_id)
    if touch_presence:presence(db, user_id, room_id, clock)
    view = rules(room).public_view(room, user_id)
    view['next_game_settings']=game_settings.public(game_settings.current(db,kind))
    view['game_rules_note']=game_settings.NOTES[kind]
    if view.get('hand',{}):
        snapshot=view['hand'].get('game_settings')
        if snapshot:view['hand']['game_settings']=game_settings.public(snapshot)
    view.setdefault('game_type','holdem');view.setdefault('capacity',6)
    seen = {row["user_id"]: row["last_seen"] for row in db.execute("SELECT * FROM poker_presence")}
    view['party']=club_features.party_view(room,user_id,seen,clock)
    for seat in view["seats"]:
        seat["online"] = clock-seen.get(seat["user_id"], 0) < 16
    cosmetics=rewards.profile_map(db)
    profiles=member_accounts.public_profiles(db)
    for seat in view["seats"]:seat.update(cosmetics=cosmetics.get(seat['user_id'],{}),**profiles.get(seat['user_id'],{}))
    view['appearance_revision']=[(s['user_id'],s.get('profile_revision',0),s['cosmetics']) for s in view['seats']]
    view["server_time"] = clock
    view['wallet']=wallet.view(db,user_id,clock)
    view['social']=social.view(db,room_id,user_id,clock,profiles=profiles,cosmetics=cosmetics)
    view["current_room_id"] = current_room(db, user_id)
    view["accepted_operations"] = [row[0] for row in db.execute(
        "SELECT operation_id FROM poker_operations WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 8",(user_id,))]
    view['history']=view_cache.shared(db,('history',room_id),('poker_hands',),lambda: [{"number": row["hand_number"], "finished_at": row["finished_at"],
                        "board": (h := json.loads(row["public_state"]))["board"], "results": h["results"], "pots": h["pots"],"summary":h.get('summary',''),"game_type":h.get('game_type','holdem')}
                       for row in db.execute("SELECT * FROM poker_hands WHERE room_id=? ORDER BY hand_number DESC LIMIT 12", (room_id,))])
    return view


def mutate(db, path, data, user, clock, received_at=None):
    operation_id = data.get("operation_id")
    fingerprint = None
    if operation_id is not None:
        if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}",operation_id):
            raise engine.RuleError("操作編號無效，請重新整理牌桌。")
        intent = {k:v for k,v in data.items() if k not in ("revision", "operation_id")}
        fingerprint = hashlib.sha256((path+json.dumps(intent,sort_keys=True,separators=(",",":"))).encode()).hexdigest()
        previous = db.execute("SELECT * FROM poker_operations WHERE user_id=? AND operation_id=?",(user["id"],operation_id)).fetchone()
        if previous:
            if previous["fingerprint"] != fingerprint:
                return {"conflict":True,"reason":"operation_mismatch"}
            return {**json.loads(previous["result"]), "replayed":True}
    result = _mutate(db,path,data,user,clock,clock if received_at is None else received_at)
    if operation_id and not result.get("conflict"):
        db.execute("INSERT INTO poker_operations VALUES(?,?,?,?,?)",(user["id"],operation_id,fingerprint,json.dumps(result),clock))
    return result


def funding_amount(db, uid, data, key, default, clock):
    wallet.create(db, uid, clock)
    balance = db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()[0]
    if key not in data and balance == 0:
        raise engine.RuleError('錢包籌碼不足，請先領取每日補給或離桌取回籌碼。')
    amount = engine.integer(data[key] if key in data else min(default,balance), '帶入籌碼', 1, engine.MAX_CHIP_AMOUNT)
    if amount > balance:
        raise engine.RuleError(f'錢包籌碼不足，目前可帶入 {balance:,} 點。')
    return amount


def _mutate(db, path, data, user, clock, received_at):
    uid = user["id"]
    member_accounts.require_active(db,uid)
    if path.startswith("/api/club/"):return rewards.mutate(db,path,data,user,clock)
    if path == "/api/online/rooms":
        require_new_deal_allowed(db, clock)
        if current_room(db, uid):
            raise engine.RuleError("你已在另一張桌上，請先離桌再開新桌。")
        if db.execute("SELECT count(*) FROM poker_rooms WHERE status!='closed'").fetchone()[0] >= 12:
            raise engine.RuleError("牌桌數量已滿，請先結束不使用的牌桌。")
        name = data.get("name", "楠團深夜局")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 32:
            raise engine.RuleError("牌桌名稱請填寫 1–32 個字。")
        if not wallet.active(db):raise engine.RuleError('籌碼制度更新中，請等目前手牌結束後重新開桌。')
        amount = funding_amount(db,uid,data,'buy_in',1000,clock)
        kind=data.get('game_type','holdem')
        if not isinstance(kind,str) or kind not in ('holdem','mahjong','big2','blackjack','roulette',*bonus_engine.CATALOG):raise engine.RuleError('遊戲類型無效。')
        room = mahjong_engine.new_room(name.strip(),uid,buy_in=amount,mahjong_rules=data.get('mahjong_rules')) if kind=='mahjong' else (engine.new_room(name.strip(), uid, data.get("small_blind", 5), data.get("big_blind", 10), amount) if kind=='holdem' else (bonus_engine if kind in bonus_engine.CATALOG else arcade_engine).new_room(name.strip(),uid,kind,amount,data.get('stake',20 if kind=='baccarat' else 10),settings=game_settings.current(db,kind)))
        game_settings.fund_bet_limit(room,game_settings.current(db,kind))
        if kind=='tower':room['tower_mode']=bonus_engine.tower_mode(data.get('tower_mode','fixed'))
        if kind=='big2':room['big2_rules']=arcade_engine.big2_options(data.get('big2_rules'))
        club_features.create_party(room,data,uid)
        rules(room).sit(room, uid, user["nickname"], clock)
        wallet.transfer(db,uid,-room['buy_in'],'buy_in','join:'+engine.seated(room,uid)['session_id'],clock)
        result = db.execute("INSERT INTO poker_rooms(name,owner_id,status,revision,state,created_at,updated_at) VALUES(?,?,'waiting',1,?,?,?)",
            (room["name"], uid, json.dumps(room, ensure_ascii=False), clock, clock))
        return {"id": result.lastrowid}
    match = re.fullmatch(r"/api/online/rooms/(\d+)/(join|start|action|leave|rebuy|return|close|invite|ready|wager)", path)
    if not match:
        raise engine.RuleError("找不到這個牌桌操作。")
    room_id, action = int(match[1]), match[2]
    room = get_room(db, room_id)
    before=lobby_fingerprint(room)
    if action=='invite':
        club_features.redeem(room,uid,data.get('code'))
        save(db,room,clock)
        return {'id':room_id,'_lobby_changed':before!=lobby_fingerprint(room)}
    club_features.require_access(room,uid)
    driver=rules(room)
    if driver.tick(room, clock, due_at=received_at):
        save(db, room, clock)
        return {"conflict": True, "reason":"turn_expired"}
    if action == "action" and data.get("turn_id") is not None:
        if not room["hand"] or data.get("hand_id") != room["hand"]["id"]:
            return {"conflict":True,"reason":"stale_hand"}
        if data["turn_id"] != driver.turn_id(room["hand"]) or driver.legal_actions(room,uid) is None:
            return {"conflict":True,"reason":"stale_turn"}
    elif not data.get("operation_id") or action == "action":
        # Legacy clients keep strict revision checks. New non-betting commands
        # validate their semantics against the locked state instead.
        if type(data.get("revision")) is not int or data["revision"] != room["revision"]:
            return {"conflict": True, "reason":"stale_version"}
    if room["status"] == "closed":
        raise engine.RuleError("這張牌桌已經結束。")
    if action == "join":
        other = current_room(db, uid)
        if other:
            raise engine.RuleError("你已經入座，請先離開原本的牌桌。")
        if not wallet.active(db):raise engine.RuleError('籌碼制度更新中，請等目前手牌結束。')
        amount = funding_amount(db,uid,data,'buy_in',room['buy_in'],clock)
        driver.sit(room, uid, user["nickname"], clock, data.get("seat"), buy_in=amount)
        wallet.transfer(db,uid,-amount,'buy_in','join:'+engine.seated(room,uid)['session_id'],clock)
    else:
        seat = engine.seated(room, uid)
        if not seat:
            raise engine.RuleError("請先入座，才能操作這張牌桌。")
        if action == "start":
            # Dice/roulette accept bets on an already running hand via /start.
            if room['status'] == 'waiting':
                require_new_deal_allowed(db, clock)
            expected_limit=data.get('expected_bet_limit_revision')
            if room['status']=='waiting' and expected_limit is not None and (type(expected_limit) is not int or expected_limit!=game_settings.current(db,'limits')['revision']):
                return {'conflict':True,'reason':'stale_settings'}
            expected_settings=data.get('expected_settings_revision')
            if room['status']=='waiting' and expected_settings is not None:
                current_settings=game_settings.current(db,room.get('game_type','holdem'))
                if type(expected_settings) is not int or expected_settings!=current_settings['revision']:
                    return {'conflict':True,'reason':'stale_settings'}
            club_features.check_start(db,room,uid,clock)
            if not wallet.active(db):raise engine.RuleError('本手結束後會啟用總籌碼制度，請稍候重新開桌。')
            if seat["away"] or seat["leaving"] or seat["stack"] == 0:
                raise engine.RuleError("請先回到牌桌並補充籌碼，再發牌。")
            if room['status']=='waiting':game_settings.fund_bet_limit(room,game_settings.current(db,room.get('game_type','holdem')))
            if room.get('game_type')=='blackjack':
                if type(data.get('expected_hand_number')) is not int:
                    raise engine.RuleError('21 點已改為各自確認下注，請重新整理後再操作。')
                if room['status']!='waiting' or data['expected_hand_number']!=room['hand_no']+1:
                    return {'conflict':True,'reason':'stale_hand'}
                started=arcade_engine.confirm_blackjack_bet(room,uid,data.get('stake'),clock,data['expected_hand_number'],settings=game_settings.current(db,'blackjack'))
                room['_replay_label']='全桌下注確認／發牌' if started else f"{user['nickname']} · 已確認下注"
            elif room.get('game_type')=='dice':
                expected=data.get('expected_hand_number')
                if expected is not None and (type(expected) is not int or expected!=room['hand_no']+(room['status']=='waiting')):
                    return {'conflict':True,'reason':'stale_hand'}
                if room['status']=='playing':driver.act(room,uid,'bet',clock,data=data)
                else:driver.start_hand(room,clock,options=data,user_id=uid,settings=game_settings.current(db,'dice'))
            elif driver is bonus_engine:driver.start_hand(room, clock, options=data,settings=game_settings.current(db,room['game_type']))
            elif room.get('game_type','holdem')!='roulette' or room['status']!='playing' or 'bets' not in data:
                if driver is engine:driver.start_hand(room,clock)
                else:driver.start_hand(room,clock,settings=game_settings.current(db,room['game_type']))
            if room.get('game_type')=='roulette' and 'bets' in data:
                driver.act(room,uid,'bet',clock,data=data)
            if room.get('party'):room['party']['ready']={}
            if room.get('game_type')!='blackjack':room['_replay_label']='電腦發牌／開局'
        elif action == "action":
            if not room["hand"] or data.get("hand_id") != room["hand"]["id"]:
                raise engine.RuleError("已經開始新的一手，請更新牌桌。")
            if driver is engine:engine.act(room, uid, data.get("action"), clock, data.get("amount"))
            else:driver.act(room,uid,data.get('action'),clock,data=data)
            names={'fold':'棄牌','check':'過牌','call':'跟注','raise':'加注','allin':'全下','play':'出牌','pass':'Pass','discard':'打牌','chi':'吃','pong':'碰','kong':'槓','hu':'胡','concealed_kong':'暗槓','added_kong':'加槓','hit':'要牌','stand':'停牌','double':'加倍','split':'分牌','pick':'翻格','cashout':'收手','bet':'下注','skip':'略過'}
            room['_replay_label']=f"{user['nickname']} · {names.get(data.get('action'),'行動')}"+(f" {data['amount']}" if type(data.get('amount')) is int else '')
        elif action == "leave":
            driver.leave(room, uid, clock)
        elif action == "rebuy":
            if not wallet.active(db):raise engine.RuleError('籌碼制度更新中，請稍候。')
            amount = funding_amount(db,uid,data,'amount',room['buy_in'],clock)
            engine.rebuy(room, uid, clock, amount)
            wallet.transfer(db,uid,-amount,'rebuy','rebuy:'+seat['session_id']+':'+str(seat['bought']),clock)
        elif action == "return":
            engine.return_to_play(room, uid, clock)
        elif action == 'ready':
            club_features.set_ready(room,uid,data)
        elif action == 'wager':
            if room['status']!='waiting' or type(data.get('expected_hand_number')) is not int or data['expected_hand_number']!=room['hand_no']+1:
                return {'conflict':True,'reason':'stale_hand'}
            arcade_engine.set_blackjack_bet(room,uid,data.get('stake'),settings=game_settings.current(db,'blackjack'))
        elif action == "close":
            if room["owner_id"] != uid or room["status"] != "waiting":
                raise engine.RuleError("只有桌主能在一手結束後結束牌桌。")
            for player in list(room["seats"]):
                engine.depart(room, player, clock)
            room["status"] = "closed"
    save(db, room, clock)
    presence(db, uid, room_id, clock)
    return {"id": room_id,"_lobby_changed":before!=lobby_fingerprint(room)}
