"""Durable board rooms and escrow. Every mutation shares the caller's transaction."""
import hashlib
import json
import re
import secrets
import time
import blocade_engine as engine
import wallet
from poker_engine import RuleError

TURN_SECONDS = 45
WAIT_SECONDS = 900
MATCH_SECONDS = 1800
MAX_STAKE = 10000


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS blocade_rooms(
      id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id),
      status TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL,
      created_at REAL NOT NULL, updated_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS blocade_room_status ON blocade_rooms(status,updated_at);
    CREATE TABLE IF NOT EXISTS blocade_entries(
      room_id INTEGER NOT NULL REFERENCES blocade_rooms(id), user_id INTEGER NOT NULL REFERENCES users(id),
      stake INTEGER NOT NULL CHECK(stake>=0), payout INTEGER, joined_at REAL NOT NULL,
      PRIMARY KEY(room_id,user_id));
    CREATE INDEX IF NOT EXISTS blocade_user_rooms ON blocade_entries(user_id,room_id);
    CREATE TABLE IF NOT EXISTS blocade_operations(
      user_id INTEGER NOT NULL REFERENCES users(id), operation_id TEXT NOT NULL,
      fingerprint TEXT NOT NULL, room_id INTEGER NOT NULL REFERENCES blocade_rooms(id), created_at REAL NOT NULL,
      PRIMARY KEY(user_id,operation_id));
    ''')
    # This runs at server startup, not on requests. A stopped process must not
    # consume anyone's turn. Explicit deployment pauses resume in maintenance.
    clock = time.time()
    for row in db.execute("SELECT * FROM blocade_rooms WHERE status='playing'").fetchall():
        room = decode(row)
        if room.get('paused_at') is not None: continue
        room['started_at'] += max(0, clock-row['updated_at'])
        room['deadline'] = clock+TURN_SECONDS
        room['bot_at'] = clock+1.5
        save(db, room, clock)


def decode(row):
    state = json.loads(row['state'])
    return dict(state, id=row['id'], status=row['status'], revision=row['revision'])


def get(db, rid):
    if type(rid) is not int or rid <= 0: raise RuleError('桌號無效。')
    row = db.execute('SELECT * FROM blocade_rooms WHERE id=?', (rid,)).fetchone()
    if not row: raise RuleError('找不到這張棋桌。')
    return decode(row)


def save(db, room, clock):
    room['revision'] += 1
    db.execute('UPDATE blocade_rooms SET owner_id=?,status=?,revision=?,state=?,updated_at=? WHERE id=?',
               (room['owner'], room['status'], room['revision'], json.dumps(room, ensure_ascii=False), clock, room['id']))


def current(db, uid):
    row = db.execute("""SELECT r.id FROM blocade_rooms r JOIN blocade_entries e ON e.room_id=r.id
        WHERE e.user_id=? AND e.payout IS NULL AND r.status IN ('waiting','playing') LIMIT 1""", (uid,)).fetchone()
    return row[0] if row else None


def join(db, room, user, clock):
    if room['status'] != 'waiting': raise RuleError('這張桌已開始或已結束。')
    if current(db, user['id']): raise RuleError('你已有棋桌，請先完成或離開原桌。')
    if len(room['players']) >= room['capacity']: raise RuleError('這張桌已滿。')
    if db.execute('SELECT 1 FROM blocade_entries WHERE room_id=? AND user_id=?', (room['id'], user['id'])).fetchone():
        raise RuleError('已退桌的對局不能重複入場，請開新桌。')
    wallet.transfer(db, user['id'], -room['stake'], 'blocade_entry', f"blocade:{room['id']}:entry", clock)
    db.execute('INSERT INTO blocade_entries VALUES(?,?,?,NULL,?)', (room['id'], user['id'], room['stake'], clock))
    room['players'].append(dict(uid=user['id'], name=user['nickname'], bot=False))


def settle(db, room, clock, *, cancel=False, reason=''):
    if room['status'] not in ('waiting', 'playing'): return
    room['status'] = 'cancelled' if cancel else 'finished'
    room['finished_at'] = clock; room['reason'] = reason
    winner = None if cancel else room['game']['players'][room['game']['winner']]
    room['winner'] = winner
    room['pot'] = room['stake']*len(room['players'])
    room['system_stake'] = room['stake']*sum(p['bot'] for p in room['players'])
    room['system_payout'] = room['pot'] if winner and winner['bot'] else 0
    for row in db.execute('SELECT * FROM blocade_entries WHERE room_id=? AND payout IS NULL', (room['id'],)).fetchall():
        amount = row['stake'] if cancel else room['pot'] if winner['uid'] == row['user_id'] else 0
        wallet.transfer(db, row['user_id'], amount, 'blocade_refund' if cancel else 'blocade_prize',
                        f"blocade:{room['id']}:settle", clock)
        db.execute('UPDATE blocade_entries SET payout=? WHERE room_id=? AND user_id=?', (amount, room['id'], row['user_id']))


def mutate(db, user, verb, data, clock, received_at=None):
    uid = user['id']; op = data.get('operation_id')
    if not isinstance(op, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', op):
        raise RuleError('缺少有效操作編號，請重新整理。')
    fingerprint = hashlib.sha256(json.dumps([verb, data], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    old = db.execute('SELECT * FROM blocade_operations WHERE user_id=? AND operation_id=?', (uid, op)).fetchone()
    if old:
        if old['fingerprint'] != fingerprint: raise RuleError('操作編號與內容不符。')
        return dict(room_id=old['room_id'], replayed=True)
    if verb in ('create', 'join', 'start'):
        import online
        online.require_new_deal_allowed(db, clock)
        if not wallet.active(db): raise RuleError('點數制度尚未啟用。')
    if verb == 'create':
        capacity, stake, bots = data.get('capacity'), data.get('stake'), data.get('bots')
        if type(capacity) is not int or capacity not in (2, 4): raise RuleError('請選擇 2 人或 4 人桌。')
        if type(stake) is not int or not 0 <= stake <= MAX_STAKE: raise RuleError(f'每人入場請填 0–{MAX_STAKE:,} 點整數。')
        if type(bots) is not bool: raise RuleError('請選擇是否允許機器人補位。')
        if current(db, uid): raise RuleError('你已有棋桌，請先完成或離開原桌。')
        if db.execute("SELECT count(*) FROM blocade_rooms WHERE status IN ('waiting','playing')").fetchone()[0] >= 30:
            raise RuleError('目前棋桌已滿，請加入現有桌或稍後再開桌。')
        room = dict(owner=uid, capacity=capacity, stake=stake, bots=bots, players=[], game=None,
                    expires=clock+WAIT_SECONDS, deadline=0, started_at=None, winner=None, reason='')
        rid = db.execute('INSERT INTO blocade_rooms(owner_id,status,revision,state,created_at,updated_at) VALUES(?,\'waiting\',0,?,?,?)',
                         (uid, json.dumps(room), clock, clock)).lastrowid
        room.update(id=rid, status='waiting', revision=0)
        join(db, room, user, clock)
    else:
        room = get(db, data.get('room_id'))
        if verb == 'join':
            if clock >= room['expires']: raise RuleError('等候已逾時，請選擇其他棋桌。')
            join(db, room, user, clock)
        elif verb == 'start':
            if room['owner'] != uid: raise RuleError('只有桌主可以開始。')
            if room['status'] != 'waiting' or clock >= room['expires']: raise RuleError('棋桌已開始或等候逾時。')
            if not room['bots'] and len(room['players']) != room['capacity']: raise RuleError('請等真人到齊，這張桌未開啟機器人補位。')
            while len(room['players']) < room['capacity']:
                number = len(room['players'])+1
                room['players'].append(dict(uid=-number, name=f'機器人 {number}', bot=True))
            room['game'] = engine.new(room['players'])
            room['game']['turn'] = secrets.randbelow(room['capacity'])
            room['started_at'] = clock; room['status'] = 'playing'
            room['deadline'] = clock+TURN_SECONDS; room['bot_at'] = clock+1.5
        elif verb == 'act':
            import online
            if room.get('paused_at') is not None or online.deployment_paused(db, clock):
                raise RuleError('伺服器更新中，棋局已暫停計時，更新後繼續。')
            if room['status'] != 'playing': raise RuleError('這張棋桌還未開始或已結束。')
            game = room['game']; player = game['players'][game['turn']]
            if player['uid'] != uid or player['out']: raise RuleError('還沒輪到你。')
            if type(data.get('ply')) is not int or data['ply'] != game['ply']: raise RuleError('棋局已更新，請確認最新棋盤後再走。')
            if (clock if received_at is None else received_at) >= room['deadline']: raise RuleError('這個回合已逾時，請等待棋盤更新。')
            action = data.get('action')
            if not isinstance(action, dict): raise RuleError('走法格式無效。')
            engine.act(game, {k: action[k] for k in ('kind', 'pos', 'wall') if k in action})
            player['misses'] = 0
            room['deadline'] = clock+TURN_SECONDS; room['bot_at'] = clock+1.5
            if game['winner'] is not None: settle(db, room, clock)
        elif verb == 'leave':
            entry = db.execute('SELECT * FROM blocade_entries WHERE room_id=? AND user_id=?', (room['id'], uid)).fetchone()
            if not entry or entry['payout'] is not None: raise RuleError('你已離開或這張棋桌已結算。')
            if room['status'] == 'waiting':
                wallet.transfer(db, uid, entry['stake'], 'blocade_refund', f"blocade:{room['id']}:settle", clock)
                db.execute('UPDATE blocade_entries SET payout=stake WHERE room_id=? AND user_id=?', (room['id'], uid))
                room['players'] = [p for p in room['players'] if p['uid'] != uid]
                if not room['players']: settle(db, room, clock, cancel=True, reason='所有玩家已退桌')
                elif room['owner'] == uid: room['owner'] = room['players'][0]['uid']
            elif room['status'] == 'playing':
                game = room['game']; index = next(i for i,p in enumerate(game['players']) if p['uid'] == uid)
                if game['players'][index]['out']: raise RuleError('你已認輸，正在等候本局結算。')
                was_turn = game['turn'] == index
                engine.resign(game, index)
                if was_turn: room['deadline'] = clock+TURN_SECONDS; room['bot_at'] = clock+1.5
                if game['winner'] is not None: settle(db, room, clock)
            else: raise RuleError('棋桌已結算。')
        else: raise RuleError('找不到這個棋桌操作。')
    save(db, room, clock)
    db.execute('INSERT INTO blocade_operations VALUES(?,?,?,?,?)', (uid, op, fingerprint, room['id'], clock))
    return dict(room_id=room['id'], replayed=False,
                wallet_changed=verb in ('create','join','leave') or room['status'] in ('finished','cancelled'))


def maintenance(db, clock):
    import online
    paused = online.deployment_paused(db, clock)
    wallet_changed = False; bot_count = 0
    for row in db.execute("SELECT * FROM blocade_rooms WHERE status IN ('waiting','playing') ORDER BY updated_at,id").fetchall():
        room = decode(row)
        if paused:
            if room.get('paused_at') is None:
                room['paused_at'] = clock
                save(db, room, clock)
            continue
        if room.get('paused_at') is not None:
            elapsed = max(0, clock-room.pop('paused_at'))
            room['expires'] += elapsed; room['deadline'] += elapsed
            if room['started_at'] is not None:
                room['started_at'] += elapsed; room['bot_at'] += elapsed
            save(db, room, clock)
        if room['status'] == 'waiting':
            if clock < room['expires']: continue
            settle(db, room, clock, cancel=True, reason='等候超過 15 分鐘，入場點數已退還')
        else:
            game = room['game']; player = game['players'][game['turn']]
            if clock-room['started_at'] >= MATCH_SECONDS or game['ply'] >= 400:
                settle(db, room, clock, cancel=True, reason='本局達 30 分鐘或 400 回合上限，和局退還入場點數')
            elif player['bot'] and clock >= room['bot_at'] and bot_count < 2:
                engine.act(game, engine.choose(game)); bot_count += 1
                room['deadline'] = clock+TURN_SECONDS; room['bot_at'] = clock+1.5
                if game['winner'] is not None: settle(db, room, clock)
            elif not player['bot'] and clock >= room['deadline']:
                player['misses'] += 1
                if player['misses'] >= 3: engine.resign(game, game['turn'])
                else: engine.act(game, engine.choose(game, walls=False))
                room['deadline'] = clock+TURN_SECONDS; room['bot_at'] = clock+1.5
                if game['winner'] is not None: settle(db, room, clock)
            else: continue
        save(db, room, clock)
        if room['status'] in ('finished','cancelled'): wallet_changed = True
    # Board clients poll their own small snapshot. Moves must not wake every
    # unrelated poker/market client; only actual settlement changes wallets.
    return wallet_changed


def view(db, uid, clock, rid=None):
    active = current(db, uid)
    if rid is None:
        rid = active
    room = get(db, rid) if rid else None
    if room:
        game = room['game']
        room['legal_moves'] = engine.moves(game) if room['status'] == 'playing' else []
        room['pot'] = room['stake']*len(room['players'])
        room['target_pot'] = room['stake']*room['capacity']
        import online
        room['paused'] = room.get('paused_at') is not None or online.deployment_paused(db, clock)
    tables = []
    for row in db.execute("SELECT * FROM blocade_rooms WHERE status IN ('waiting','playing') ORDER BY id DESC LIMIT 30"):
        r = decode(row)
        tables.append({k: r[k] for k in ('id','owner','capacity','stake','bots','players','status')})
    history = [dict(row) for row in db.execute('''SELECT r.id,r.status,e.stake,e.payout,r.updated_at
        FROM blocade_entries e JOIN blocade_rooms r ON r.id=e.room_id
        WHERE e.user_id=? ORDER BY r.id DESC LIMIT 20''', (uid,))]
    return dict(room=room, current_id=active, tables=tables, history=history, server_time=clock,
                max_stake=MAX_STAKE, turn_seconds=TURN_SECONDS)
