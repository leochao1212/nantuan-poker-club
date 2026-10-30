"""Server-authoritative, integer-chip no-limit Texas Hold'em for 2–6 friends.

State is JSON serializable. Only public_view may cross the network. No external
dependencies; the default shuffle uses the operating system's secure randomness.
"""
from collections import Counter
from copy import deepcopy
from itertools import combinations
import secrets

RANKS = "23456789TJQKA"
DECK = [r+s for s in "cdhs" for r in RANKS]
PHASES = ("preflop", "flop", "turn", "river")
RANK_NAMES = ("高牌", "一對", "兩對", "三條", "順子", "同花", "葫蘆", "四條", "同花順")
TURN_SECONDS = 30
MAX_CHIP_AMOUNT = 2**53-1


class RuleError(Exception):
    pass


def integer(value, label, low=0, high=1_000_000):
    if type(value) is not int or not low <= value <= high:
        raise RuleError(f"{label}必須是 {low:,}–{high:,} 的整數。")
    return value


def rank_five(cards):
    values = sorted((RANKS.index(c[0])+2 for c in cards), reverse=True)
    counts = Counter(values)
    groups = sorted(((n, v) for v, n in counts.items()), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    unique = sorted(counts, reverse=True)
    straight = unique[0] if len(unique) == 5 and unique[0]-unique[-1] == 4 else 5 if unique == [14,5,4,3,2] else 0
    if flush and straight:
        return (8, straight)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if [g[0] for g in groups] == [3,2]:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *values)
    if straight:
        return (4, straight)
    if groups[0][0] == 3:
        return (3, groups[0][1], *sorted((v for v in values if v != groups[0][1]), reverse=True))
    pairs = sorted((v for v, n in counts.items() if n == 2), reverse=True)
    if len(pairs) == 2:
        return (2, *pairs, next(v for v in values if v not in pairs))
    if pairs:
        return (1, pairs[0], *sorted((v for v in values if v != pairs[0]), reverse=True))
    return (0, *values)


def best_hand(cards):
    if len(cards) < 5 or len(set(cards)) != len(cards) or any(c not in DECK for c in cards):
        raise RuleError("牌組資料無效。")
    score, selected = max((rank_five(combo), tuple(combo)) for combo in combinations(cards, 5))
    return score, list(selected)


def new_room(name, owner_id, small_blind=5, big_blind=10, buy_in=1000):
    integer(small_blind, "小盲", 1, 5000)
    integer(big_blind, "大盲", small_blind*2, 10000)
    integer(buy_in, "入桌籌碼", 1, MAX_CHIP_AMOUNT)
    return {"name": name, "owner_id": owner_id, "small_blind": small_blind,
            "big_blind": big_blind, "buy_in": buy_in, "status": "waiting",
            "seats": [], "dealer_seat": -1, "hand_no": 0, "hand": None,
            "log": [], "departures": [], "next_hand_at": 0}


def log(room, text, clock):
    room["log"].append({"text": text, "at": clock})
    room["log"] = room["log"][-60:]


def seated(room, user_id):
    return next((p for p in room["seats"] if p["user_id"] == user_id), None)


def sit(room, user_id, nickname, clock, seat=None, buy_in=None):
    if room["status"] == "closed":
        raise RuleError("這張桌已經結束，請回大廳開新桌。")
    if seated(room, user_id):
        raise RuleError("你已經在這張桌上。")
    free = sorted(set(range(6))-{p["seat"] for p in room["seats"]})
    if not free:
        raise RuleError("這張桌的六個座位已滿。")
    if seat is None:
        seat = free[0]
    if type(seat) is not int or seat not in free:
        raise RuleError("這個座位已被坐走，請選其他座位。")
    amount = integer(room["buy_in"] if buy_in is None else buy_in, "入桌籌碼", 1, MAX_CHIP_AMOUNT)
    room["seats"].append({"user_id": user_id, "nickname": nickname, "seat": seat,
        "stack": amount, "bought": amount, "away": False,
        "leaving": False, "session_id": secrets.token_hex(12), "joined_at": clock})
    log(room, f"{nickname} 入座，帶入 {amount:,} 籌碼", clock)


def clockwise(players, after):
    return sorted(players, key=lambda p: (p["seat"]-after-1) % 6)


def sync_stacks(room):
    hand = room.get("hand")
    if hand:
        for p in hand["players"]:
            seat = seated(room, p["user_id"])
            if seat:
                seat["stack"] = p["stack"]


def pay(player, amount):
    amount = min(player["stack"], amount)
    player["stack"] -= amount
    player["street_bet"] += amount
    player["contribution"] += amount


def start_hand(room, clock, deck=None):
    if room["status"] != "waiting":
        raise RuleError("上一手還在進行中。")
    if clock < room["next_hand_at"]:
        raise RuleError("請稍等攤牌結果顯示完畢，再開始下一手。")
    players = [p for p in room["seats"] if p["stack"] > 0 and not p["away"] and not p["leaving"]]
    if len(players) < 2:
        raise RuleError("至少需要兩位有籌碼、未暫離的玩家才能發牌。")
    dealer = clockwise(players, room["dealer_seat"])[0]["seat"]
    if len(players) == 2 and room.get("hand"):
        proposed_big = next(p for p in players if p["seat"] != dealer)
        if proposed_big["user_id"] == room["hand"].get("big_blind_id"):
            # On transition to heads-up, the previous BB becomes the button/SB.
            dealer = proposed_big["seat"]
    order = clockwise(players, dealer)
    shoe = list(deck) if deck is not None else list(DECK)
    if len(shoe) != 52 or set(shoe) != set(DECK):
        raise RuleError("牌組必須包含 52 張不同的牌。")
    if deck is None:
        secrets.SystemRandom().shuffle(shoe)
    room["hand_no"] += 1
    room["dealer_seat"] = dealer
    participants = [{"user_id": p["user_id"], "nickname": p["nickname"], "seat": p["seat"],
        "stack": p["stack"], "starting_stack": p["stack"], "hole": [], "folded": False,
        "street_bet": 0, "contribution": 0, "acted_at": None, "last_action": ""} for p in order]
    for _ in range(2):
        for p in participants:
            p["hole"].append(shoe.pop())
    hand = {"id": secrets.token_hex(12), "number": room["hand_no"], "phase": "preflop",
        "deck": shoe, "board": [], "burns": [], "players": participants,
        "current_bet": room["big_blind"], "min_raise": room["big_blind"],
        "pending": [p["user_id"] for p in participants if p["stack"] > 0],
        "actor": None, "deadline": None, "started_at": clock, "results": [], "pots": []}
    room["hand"] = hand
    __import__('economy').attach(room)
    room["status"] = "playing"
    small = next(p for p in participants if p["seat"] == dealer) if len(players) == 2 else participants[0]
    big = next(p for p in participants if p["seat"] != dealer) if len(players) == 2 else participants[1]
    pay(small, room["small_blind"])
    pay(big, room["big_blind"])
    small["last_action"], big["last_action"] = "小盲", "大盲"
    hand["small_blind_id"], hand["big_blind_id"] = small["user_id"], big["user_id"]
    log(room, f"第 {room['hand_no']} 手發牌 · 盲注 {room['small_blind']}/{room['big_blind']}", clock)
    advance(room, big["seat"], clock)
    sync_stacks(room)


def live_players(hand):
    return [p for p in hand["players"] if not p["folded"]]


def next_street(room, clock):
    hand = room["hand"]
    if hand["phase"] == "river":
        finish(room, clock)
        return
    hand["burns"].append(hand["deck"].pop())
    count = 3 if hand["phase"] == "preflop" else 1
    hand["board"].extend(hand["deck"].pop() for _ in range(count))
    hand["phase"] = PHASES[PHASES.index(hand["phase"])+1]
    hand["current_bet"], hand["min_raise"] = 0, room["big_blind"]
    for p in hand["players"]:
        p["street_bet"], p["acted_at"] = 0, None
        if not p["folded"]:
            p["last_action"] = "All-in" if p["stack"] == 0 else ""
    hand["pending"] = [p["user_id"] for p in live_players(hand) if p["stack"] > 0]
    label = {"flop": "翻牌", "turn": "轉牌", "river": "河牌"}[hand["phase"]]
    log(room, f"電腦莊家發出{label}", clock)
    advance(room, room["dealer_seat"], clock)


def advance(room, after_seat, clock):
    hand = room["hand"]
    alive = live_players(hand)
    able = [p for p in alive if p["stack"] > 0]
    if len(alive) == 1:
        finish(room, clock, uncontested=True)
        return
    if len(able) <= 1:
        if not able or able[0]["street_bet"] >= max(p["street_bet"] for p in alive):
            while hand["phase"] != "showdown":
                next_street(room, clock)
            return
        hand["pending"] = [able[0]["user_id"]]
    pending = [p for p in able if p["user_id"] in hand["pending"]]
    if not pending:
        next_street(room, clock)
        return
    actor = clockwise(pending, after_seat)[0]
    hand["actor"], hand["deadline"] = actor["user_id"], clock+TURN_SECONDS
    hand["turn_id"] = secrets.token_hex(12)


def turn_id(hand):
    if not hand or hand.get("actor") is None:
        return None
    # Stable upgrade token for hands already in progress before this release.
    return hand.get("turn_id") or f"{hand['id']}:{hand['phase']}:{hand['actor']}:{hand['deadline']}"


def legal_actions(room, user_id):
    hand = room.get("hand")
    if room["status"] != "playing" or not hand or hand["actor"] != user_id:
        return None
    player = next(p for p in hand["players"] if p["user_id"] == user_id)
    others = [p for p in live_players(hand) if p["user_id"] != user_id]
    can_raise = any(p["stack"] > 0 for p in others) and (player["acted_at"] is None or hand["current_bet"]-player["acted_at"] >= hand["min_raise"])
    target = hand["current_bet"]
    if not any(p["stack"] > 0 for p in others):
        target = min(target, max((p["street_bet"] for p in others), default=0))
    owed = max(0, target-player["street_bet"])
    maximum = player["stack"]+player["street_bet"]
    minimum = hand["current_bet"]+hand["min_raise"]
    actions = ["fold", "check" if owed == 0 else "call"]
    if can_raise and maximum > hand["current_bet"]:
        actions.append("raise")
    if maximum <= hand["current_bet"] or can_raise:
        actions.append("allin")
    return {"actions": actions, "to_call": min(owed, player["stack"]), "owed": owed,
            "min_raise_to": minimum, "max_raise_to": maximum, "current_bet": player["street_bet"],
            "can_full_raise": can_raise and maximum >= minimum}


def act(room, user_id, action, clock, amount=None, timed_out=False):
    legal = legal_actions(room, user_id)
    if not legal or action not in legal["actions"]:
        raise RuleError("現在不是你的回合，或這個動作目前不允許。")
    hand = room["hand"]
    player = next(p for p in hand["players"] if p["user_id"] == user_id)
    if action == "fold":
        player["folded"], label = True, "棄牌"
    elif action == "check":
        label = "過牌"
    elif action == "call":
        pay(player, legal["to_call"])
        label = f"跟注 {legal['to_call']:,}" if player["stack"] else "All-in 跟注"
    else:
        target = legal["max_raise_to"] if action == "allin" else integer(amount, "加注至", 1, legal["max_raise_to"])
        if target > legal["max_raise_to"] or target <= player["street_bet"]:
            raise RuleError("加注金額超出可用籌碼。")
        if target > hand["current_bet"]:
            if "raise" not in legal["actions"]:
                raise RuleError("不足額 All-in 沒有重新開放你的加注權，請跟注或棄牌。")
            increase = target-hand["current_bet"]
            full_raise = increase >= hand["min_raise"]
            if not full_raise and target != legal["max_raise_to"]:
                raise RuleError(f"本輪至少須加注至 {legal['min_raise_to']:,}，籌碼不足時可 All-in。")
            pay(player, target-player["street_bet"])
            hand["current_bet"] = target
            if full_raise:
                hand["min_raise"] = increase
                for p in hand["players"]:
                    p["acted_at"] = None
                hand["pending"] = [p["user_id"] for p in live_players(hand) if p["stack"] > 0 and p != player]
            else:
                hand["pending"] = list(set(hand["pending"]) | {p["user_id"] for p in live_players(hand) if p["stack"] > 0 and p["street_bet"] < target and p != player})
            label = f"{'All-in ' if player['stack'] == 0 else ''}加注至 {target:,}"
        else:
            if action != "allin":
                raise RuleError("加注須高於目前下注額；跟注請使用跟注按鈕。")
            pay(player, player["stack"])
            label = "All-in 跟注"
    player["acted_at"] = hand["current_bet"]
    player["last_action"] = label
    hand["pending"] = [uid for uid in hand["pending"] if uid != user_id]
    if timed_out:
        seat = seated(room, user_id)
        if seat:
            seat["away"] = True
            seat["away_reason"] = "timeout"
        label = "逾時自動"+label
    log(room, f"{player['nickname']} · {label}", clock)
    advance(room, player["seat"], clock)
    sync_stacks(room)


def tick(room, clock, due_at=None):
    due_at = clock if due_at is None else due_at
    changed = False
    while room["status"] == "playing" and (hand := room.get("hand")):
        seat = seated(room, hand["actor"])
        if not (seat and seat["away"]) and hand["deadline"] > due_at:
            break
        legal = legal_actions(room, hand["actor"])
        act(room, hand["actor"], "check" if "check" in legal["actions"] else "fold", clock, timed_out=True)
        changed = True
    return changed


def finish(room, clock, uncontested=False):
    hand = room["hand"]
    alive = live_players(hand)
    scores = {p["user_id"]: best_hand(p["hole"]+hand["board"]) for p in alive} if not uncontested else {}
    payouts = {p["user_id"]: 0 for p in hand["players"]}
    previous = 0
    pots, layers = [], []
    for level in sorted({p["contribution"] for p in hand["players"] if p["contribution"] > 0}):
        contributors = [p for p in hand["players"] if p["contribution"] >= level]
        amount = (level-previous)*len(contributors)
        previous = level
        refund = len(contributors) == 1
        eligible = contributors if refund else [p for p in alive if p["contribution"] >= level] or alive
        eligible_ids = tuple(p["user_id"] for p in eligible)
        # Folded contributions are dead money, not new side-pot boundaries.
        # Merge before rounding; distinct eligible sets must still split separately.
        if layers and not refund and not layers[-1]["refund"] and layers[-1]["eligible_ids"] == eligible_ids:
            layers[-1]["amount"] += amount
        else:
            layers.append({"amount": amount, "eligible": eligible, "eligible_ids": eligible_ids, "refund": refund})
    for layer in layers:
        amount, eligible, refund = layer["amount"], layer["eligible"], layer["refund"]
        if uncontested or refund:
            winners = eligible
        else:
            top = max(scores[p["user_id"]][0] for p in eligible)
            winners = [p for p in eligible if scores[p["user_id"]][0] == top]
        winners = clockwise(winners, room["dealer_seat"])
        share, remainder = divmod(amount, len(winners))
        for index, p in enumerate(winners):
            payouts[p["user_id"]] += share+(index < remainder)
        pots.append({"amount": amount, "winners": [p["user_id"] for p in winners], "refund": refund})
    hand["pots"] = pots
    for p in hand["players"]:
        uid = p["user_id"]
        p["stack"] += payouts[uid]
        hand["results"].append({"user_id": uid, "nickname": p["nickname"],
            "profit": p["stack"]-p["starting_stack"], "payout": payouts[uid],
            "rank": RANK_NAMES[scores[uid][0][0]] if uid in scores else "未攤牌",
            "best_five": scores[uid][1] if uid in scores else [],
            "hole": p["hole"] if uid in scores else [], "folded": p["folded"]})
    assert sum(r["profit"] for r in hand["results"]) == 0
    hand["phase"], hand["actor"], hand["deadline"] = "showdown", None, None
    hand["uncontested"], hand["finished_at"] = uncontested, clock
    room["status"], room["next_hand_at"] = "waiting", clock+3
    summary = "、".join(f"{r['nickname']} +{r['profit']:,}" for r in hand["results"] if r["profit"] > 0) or "本手平分底池"
    log(room, "本手結算 · "+summary, clock)
    sync_stacks(room)
    for seat in list(room["seats"]):
        if seat["leaving"]:
            depart(room, seat, clock)


def depart(room, seat, clock):
    room["departures"].append({**seat, "left_at": clock})
    room["seats"].remove(seat)
    if room["owner_id"] == seat["user_id"] and room["seats"]:
        room["owner_id"] = room["seats"][0]["user_id"]
    log(room, f"{seat['nickname']} 離桌，本次淨輸贏 {seat['stack']-seat['bought']:+,}", clock)
    if not room["seats"]:
        room["status"] = "closed"


def leave(room, user_id, clock):
    seat = seated(room, user_id)
    if not seat:
        raise RuleError("你目前不在這張桌上。")
    hand = room.get("hand")
    player = next((p for p in (hand["players"] if hand else []) if p["user_id"] == user_id), None)
    if room["status"] == "playing" and player:
        seat["leaving"] = True
        if player["stack"] == 0 and not player["folded"]:
            log(room, seat["nickname"]+" 將在 All-in 結算後離桌", clock)
            return
        if not player["folded"]:
            player["folded"], player["last_action"] = True, "離桌棄牌"
            hand["pending"] = [uid for uid in hand["pending"] if uid != user_id]
            log(room, seat["nickname"]+" 離桌棄牌，結算後釋放座位", clock)
            alive = live_players(hand)
            able = [p for p in alive if p["stack"] > 0]
            runout_ready = not able or len(able) == 1 and able[0]["street_bet"] >= max(p["street_bet"] for p in alive)
            if hand["actor"] == user_id or len(alive) == 1 or runout_ready:
                advance(room, player["seat"], clock)
        sync_stacks(room)
    else:
        depart(room, seat, clock)


def rebuy(room, user_id, clock, amount=None):
    seat = seated(room, user_id)
    if not seat or room["status"] != "waiting":
        raise RuleError("請等本手結束後，再補充虛擬籌碼。")
    amount = integer(room["buy_in"] if amount is None else amount, "補碼籌碼", 1, MAX_CHIP_AMOUNT)
    seat["stack"] += amount
    seat["bought"] += amount
    seat["away"] = False
    log(room, f"{seat['nickname']} 補充 {amount:,} 虛擬籌碼", clock)


def return_to_play(room, user_id, clock):
    seat = seated(room, user_id)
    if not seat or seat["leaving"]:
        raise RuleError("請先入座。")
    seat["away"] = False
    log(room, seat["nickname"]+" 回到牌桌，將參與下一手", clock)


def public_view(room, viewer_id):
    view = deepcopy(room)
    view.pop("departures", None)
    for seat in view["seats"]:
        seat.pop("session_id", None)
    hand = view.get("hand")
    if hand:
        hand["turn_id"] = turn_id(hand)
        hand.pop("deck", None)
        hand.pop("burns", None)
        hand.pop("pending", None)
        for p in hand["players"]:
            show = hand["phase"] == "showdown" and not hand.get("uncontested") and not p["folded"]
            if p["user_id"] != viewer_id and not show:
                p["hole"] = []
            p.pop("acted_at", None)
        view["legal"] = legal_actions(room, viewer_id)
    else:
        view["legal"] = None
    return view
