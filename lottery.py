"""Friends lottery v1. Caller owns the serialized SQLite transaction."""
import hashlib
import hmac
import json
import math
import re
import secrets
from datetime import datetime, timedelta

import wallet
from poker_engine import RuleError

PRICE, LIMIT, SEED_POOL, CONTRIBUTION = 100, 10, 10000, 20
TIERS = [(5, False, '頭獎', None, 1), (4, True, '二獎', 10000, 5),
         (4, False, '三獎', 3000, 70), (3, True, '四獎', 1000, 140),
         (3, False, '五獎', 400, 910), (2, True, '六獎', 200, 910),
         (2, False, '七獎', 50, 3640)]


def initialize(db, clock):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS lottery_pool(id INTEGER PRIMARY KEY CHECK(id=1),amount INTEGER NOT NULL);
    INSERT OR IGNORE INTO lottery_pool VALUES(1,10000);
    CREATE TABLE IF NOT EXISTS lottery_draws(
      id TEXT PRIMARY KEY,draw_at REAL NOT NULL,cutoff REAL NOT NULL,seed TEXT NOT NULL,
      commitment TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,result TEXT,
      jackpot INTEGER,paid INTEGER,settled_at REAL);
    CREATE INDEX IF NOT EXISTS lottery_due ON lottery_draws(settled_at,draw_at);
    CREATE TABLE IF NOT EXISTS lottery_tickets(
      id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
      draw_id TEXT NOT NULL REFERENCES lottery_draws(id),numbers TEXT NOT NULL,
      operation_id TEXT NOT NULL,created_at REAL NOT NULL,prize INTEGER,tier TEXT,
      UNIQUE(user_id,operation_id));
    CREATE INDEX IF NOT EXISTS lottery_user_draw ON lottery_tickets(user_id,draw_id);
    CREATE INDEX IF NOT EXISTS lottery_draw_tickets ON lottery_tickets(draw_id,id);
    ''')
    maintenance(db, clock)


def upcoming(clock):
    local = datetime.fromtimestamp(clock, wallet.TAIPEI)
    at = local.replace(hour=21, minute=0, second=0, microsecond=0)
    if local >= at:
        at += timedelta(days=1)
    return at.date().isoformat(), at.timestamp()


def numbers(seed):
    """HMAC-SHA256(seed bytes, ASCII friends-lottery-v1:<counter>), rejection sampling."""
    result, counter = [], 0
    while len(result) < 6:
        block = hmac.new(bytes.fromhex(seed), f'friends-lottery-v1:{counter}'.encode(), hashlib.sha256).digest()
        counter += 1
        for byte in block:
            if byte >= 240:
                continue
            value = byte % 20 + 1
            if value not in result:
                result.append(value)
                if len(result) == 6:
                    break
    return result


def tier(ticket, result):
    count = len(set(ticket) & set(result[:5]))
    special = result[5] in ticket
    return next((t for t in TIERS if t[:2] == (count, special)), None)


def maintenance(db, clock):
    changed = False
    for draw in db.execute('SELECT * FROM lottery_draws WHERE settled_at IS NULL AND draw_at<=? ORDER BY draw_at', (clock,)).fetchall():
        db.execute('SAVEPOINT lottery_settle')
        try:
            result = numbers(draw['seed'])
            tickets = db.execute('SELECT * FROM lottery_tickets WHERE draw_id=? ORDER BY id', (draw['id'],)).fetchall()
            awards = [(t, tier(json.loads(t['numbers']), result)) for t in tickets]
            winners = sum(bool(t and t[0] == 5) for _, t in awards)
            pool = db.execute('SELECT amount FROM lottery_pool WHERE id=1').fetchone()[0]
            share = pool // winners if winners else 0
            paid = 0
            for ticket, award in awards:
                prize = (share if award[0] == 5 else award[3]) if award else 0
                db.execute('UPDATE lottery_tickets SET prize=?,tier=? WHERE id=?', (prize, award[2] if award else '未中獎', ticket['id']))
                if prize:
                    wallet.transfer(db, ticket['user_id'], prize, 'lottery_prize', f'lottery:prize:{ticket["id"]}', clock, game=True)
                paid += prize
            if winners:
                db.execute('UPDATE lottery_pool SET amount=? WHERE id=1', (SEED_POOL + pool % winners,))
            db.execute('UPDATE lottery_draws SET result=?,jackpot=?,paid=?,settled_at=? WHERE id=?', (json.dumps(result), pool, paid, clock, draw['id']))
            db.execute('RELEASE lottery_settle')
            changed = True
        except Exception:
            db.execute('ROLLBACK TO lottery_settle')
            db.execute('RELEASE lottery_settle')
            raise
    day, at = upcoming(clock)
    # A backwards system clock must not create historical draws before an existing open one.
    if not db.execute('SELECT 1 FROM lottery_draws WHERE settled_at IS NULL LIMIT 1').fetchone() and not db.execute('SELECT 1 FROM lottery_draws WHERE id=?', (day,)).fetchone():
        seed = secrets.token_hex(32)
        db.execute('INSERT INTO lottery_draws(id,draw_at,cutoff,seed,commitment) VALUES(?,?,?,?,?)',
                   (day, at, at-300, seed, hashlib.sha256(bytes.fromhex(seed)).hexdigest()))
        changed = True
    return changed


def buy(db, uid, data, clock):
    op, chosen, draw_id = data.get('operation_id'), data.get('numbers'), data.get('draw_id')
    if not isinstance(op, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', op):
        raise RuleError('購票回執無效，請重新整理。')
    if not isinstance(chosen, list) or len(chosen) != 5 or any(type(n) is not int or not 1 <= n <= 20 for n in chosen) or len(set(chosen)) != 5:
        raise RuleError('請從 1–20 選出 5 個不同號碼。')
    if not isinstance(draw_id, str):
        raise RuleError('請確認購買期別。')
    encoded = json.dumps(sorted(chosen))
    old = db.execute('SELECT * FROM lottery_tickets WHERE user_id=? AND operation_id=?', (uid, op)).fetchone()
    if old:
        if old['draw_id'] != draw_id or old['numbers'] != encoded:
            raise RuleError('這張回執已用於其他選號，請確認原購票。')
        return dict(ok=True, replayed=True, ticket_id=old['id'])
    if not wallet.active(db):
        raise RuleError('點數制度尚未啟用。')
    maintenance(db, clock)
    draw = db.execute('SELECT * FROM lottery_draws WHERE id=?', (draw_id,)).fetchone()
    if not draw or draw['settled_at'] is not None or clock >= draw['cutoff']:
        raise RuleError('本期已截止，請重新整理並確認下一期。')
    if db.execute('SELECT count(*) FROM lottery_tickets WHERE user_id=? AND draw_id=?', (uid, draw_id)).fetchone()[0] >= LIMIT:
        raise RuleError('本期已購買 10 注，明天再來玩。')
    db.execute('SAVEPOINT lottery_buy')
    try:
        wallet.transfer(db, uid, -PRICE, 'lottery_ticket', 'lottery:buy:'+op, clock, game=True)
        ticket = db.execute('INSERT INTO lottery_tickets(user_id,draw_id,numbers,operation_id,created_at) VALUES(?,?,?,?,?)', (uid, draw_id, encoded, op, clock)).lastrowid
        db.execute('UPDATE lottery_pool SET amount=amount+? WHERE id=1', (CONTRIBUTION,))
        db.execute('RELEASE lottery_buy')
    except Exception:
        db.execute('ROLLBACK TO lottery_buy')
        db.execute('RELEASE lottery_buy')
        raise
    return dict(ok=True, replayed=False, ticket_id=ticket)


def public_draw(row):
    d = dict(row)
    if d['settled_at'] is None:
        del d['seed']
    d['result'] = json.loads(d['result']) if d['result'] else None
    return d


def view(db, uid, clock):
    current = db.execute('SELECT * FROM lottery_draws WHERE settled_at IS NULL ORDER BY draw_at LIMIT 1').fetchone()
    tickets = []
    for row in db.execute('SELECT * FROM lottery_tickets WHERE user_id=? ORDER BY id DESC LIMIT 100', (uid,)):
        t = dict(row)
        t['numbers'] = json.loads(t['numbers'])
        tickets.append(t)
    return dict(server_time=clock, current=public_draw(current) if current else None,
                jackpot=db.execute('SELECT amount FROM lottery_pool WHERE id=1').fetchone()[0],
                price=PRICE, limit=LIMIT, tickets=tickets,
                bought=db.execute('SELECT count(*) FROM lottery_tickets WHERE user_id=? AND draw_id=?', (uid, current['id'] if current else '')).fetchone()[0],
                results=[public_draw(r) for r in db.execute('SELECT * FROM lottery_draws WHERE settled_at IS NOT NULL ORDER BY draw_at DESC LIMIT 14')],
                tiers=[dict(label=t[2], match=t[0], special=t[1], prize=t[3], outcomes=t[4], total=math.comb(20,5)) for t in TIERS])
