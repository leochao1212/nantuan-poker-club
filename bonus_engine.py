"""Additional virtual-point games; secrets stay server-side until settlement."""
from copy import deepcopy
from fractions import Fraction
from math import comb
from itertools import product
import secrets
import poker_engine as poker
import arcade_engine as arcade
import game_settings
import view_cache

RuleError = poker.RuleError
CATALOG = {
    'baccarat': {'name': '百家樂', 'capacity': 6, 'minimum': 1},
    'slot': {'name': '拉霸', 'capacity': 1, 'minimum': 1},
    'mines': {'name': '尋寶礦區', 'capacity': 1, 'minimum': 1},
    'tower': {'name': '爬塔', 'capacity': 1, 'minimum': 1},
    'dice': {'name': 'Dice 骰寶', 'capacity': 6, 'minimum': 1},
    'inbetween': {'name': '射龍門', 'capacity': 1, 'minimum': 1},
}
SLOT_SYMBOLS = ['seven', 'crown', 'diamond', 'bell', 'cherry', 'bar']
SLOT_PAYOUT_VERSION = 3
SLOT_BASE_TRIPLES = [75, 30, 18, 12, 8, 5]
SLOT_V2_TRIPLES = [value + 3 for value in SLOT_BASE_TRIPLES]
SLOT_TRIPLES = [value + 2 for value in SLOT_BASE_TRIPLES]  # total return, including stake
SLOT_PAIR = 4
SLOT_RTP = Fraction(sum(SLOT_TRIPLES) + 30 * SLOT_PAIR, 216)
GATE_CUT_REMAINING = len(poker.DECK) // 4

TOWER_BOMBS = {'fixed': [1]*6, 'progressive': [1,1,1,2,2,2]}
DICE_TOTALS = {4:50,5:18,6:14,7:12,8:8,9:6,10:6,11:6,12:6,13:8,14:12,15:14,16:18,17:50}

def tower_mode(value):
    if not isinstance(value,str) or value not in TOWER_BOMBS: raise RuleError('請選擇固定難度或越爬越難。')
    return value

def risk_return(kind, stake, steps, tower_options=4, mode='fixed',settings=None):
    if steps == 0: return stake
    cfg=settings or game_settings.DEFAULTS[kind]
    probability = Fraction(comb(25-cfg['bombs'], steps), comb(25, steps)) if kind == 'mines' else Fraction(tower_options-cfg['fixed_bombs'], tower_options) ** steps
    if kind=='tower' and mode=='progressive':
        probability=Fraction(1)
        for bombs in cfg['progressive_bombs'][:steps]:probability*=Fraction(4-bombs,4)
    value = Fraction(stake * cfg['target_bps'], 10000) / probability
    return value.numerator // value.denominator

def dice_multiplier(dice, key,settings=None):
    """Gross multiplier including stake. Totals and face bets still win on triples."""
    cfg=settings or game_settings.DEFAULTS['dice'];total=sum(dice);triple=len(set(dice))==1
    if key in ('small','big','odd','even'):
        win=not triple and {'small':4<=total<=10,'big':11<=total<=17,'odd':total%2==1,'even':total%2==0}[key]
        return cfg['even']+1 if win else 0
    if key=='any_triple':return cfg['any_triple']+1 if triple else 0
    kind,number=key.split(':');number=int(number)
    if kind=='number':
        matches=dice.count(number)
        return cfg['faces'][matches-1]+1 if matches else 0
    if kind=='total':return cfg['totals'][number-4]+1 if total==number else 0
    return cfg['triple']+1 if triple and dice[0]==number else 0

def dice_bets(raw):
    if not isinstance(raw,list) or not 1<=len(raw)<=31:raise RuleError('請至少選擇一個骰寶押注。')
    allowed={'small','big','odd','even','any_triple',*[f'number:{i}' for i in range(1,7)],*[f'total:{i}' for i in range(4,18)],*[f'triple:{i}' for i in range(1,7)]}
    bets={}
    for item in raw:
        if not isinstance(item,dict) or not isinstance(item.get('key'),str) or item['key'] not in allowed:raise RuleError('骰寶押注類型無效。')
        amount=poker.integer(item.get('amount'),'下注點數',1,1000)
        bets[item['key']]=bets.get(item['key'],0)+amount
    if sum(bets.values())>1000:raise RuleError('骰寶每局總下注上限為 1,000 點。')
    return [{'key':key,'amount':amount} for key,amount in bets.items()]

def dice_gross(dice,bets,settings=None):return sum(bet['amount']*dice_multiplier(dice,bet['key'],settings) for bet in bets)

def new_room(name, owner_id, game_type, buy_in=1000, stake=10):
    if game_type not in CATALOG: raise RuleError('遊戲類型無效。')
    poker.integer(stake, '每局點數', 20 if game_type == 'baccarat' else 1, 1000)
    if game_type == 'baccarat' and stake % 20: raise RuleError('百家樂下注須為 20 的倍數，以完整計算莊家勝局 5% 佣金。')
    room = poker.new_room(name, owner_id, buy_in=buy_in)
    room.update(game_type=game_type, stake=stake, capacity=CATALOG[game_type]['capacity'], bank=1_000_000)
    return room

def sit(room, user_id, nickname, clock, seat=None, buy_in=None):
    cap = room['capacity']
    if len(room['seats']) >= cap: raise RuleError('本桌座位已滿。')
    if seat is not None and (type(seat) is not int or not 0 <= seat < cap): raise RuleError('座位編號無效。')
    poker.sit(room, user_id, nickname, clock, seat, buy_in)

def turn_id(hand): return arcade.turn_id(hand)

def _gate_shoe(room, deck=None):
    """Reuse one private 52-card shoe until its cut card is reached.

    A test-supplied deck starts a new shoe. In normal play the previous
    settled hand is the only source of the remaining, ordered cards.
    """
    previous=room.get('hand');state=room.get('gate_shoe')
    if deck is None and state and state.get('version')==1:
        if not previous or previous.get('shoe_id')!=state.get('id') or previous.get('phase')!='showdown':
            raise RuleError('射龍門牌靴狀態無效，請聯絡管理員。')
        remaining=previous.get('deck')
        if not isinstance(remaining,list) or len(remaining)!=len(set(remaining)) or any(c not in poker.DECK for c in remaining):
            raise RuleError('射龍門牌靴資料無效，請聯絡管理員。')
        if len(remaining)>state.get('cut_remaining',GATE_CUT_REMAINING) and len(remaining)>=3:
            return list(remaining),{**state,'round_no':state['round_no']+1},False
    shoe=list(deck) if deck is not None else list(poker.DECK)
    if len(shoe)!=52 or set(shoe)!=set(poker.DECK):raise RuleError('射龍門須使用完整 52 張牌。')
    if deck is None:secrets.SystemRandom().shuffle(shoe)
    return shoe,{'version':1,'id':secrets.token_hex(12),'round_no':1,'cut_remaining':GATE_CUT_REMAINING},True

def start_hand(room, clock, deck=None, options=None, user_id=None,settings=None):
    if room['status'] != 'waiting': raise RuleError('上一局仍在進行。')
    kind=room['game_type'];options=options or {};snapshot=deepcopy(settings or game_settings.default(kind));cfg=snapshot['params']
    if kind=='baccarat' and clock<room['next_hand_at']:raise RuleError('請等結算顯示完畢。')
    # Round settings and any initiating player's bets are validated before payment.
    stake=poker.integer(options.get('stake',room['stake']),'每局點數',1,1000) if kind in ('slot','mines','tower','dice') else room['stake']
    mode=tower_mode(options.get('tower_mode',room.get('tower_mode','fixed'))) if kind=='tower' else 'fixed'
    bets=dice_bets(options['bets']) if kind=='dice' and 'bets' in options else None
    needed=sum(b['amount'] for b in bets) if bets else stake
    seats = sorted([s for s in room['seats'] if not s['away'] and not s['leaving'] and s['stack'] >= (1 if kind in ('dice','inbetween') else needed)], key=lambda s:s['seat'])
    if not seats: raise RuleError('至少需要一位有足夠籌碼且未暫離的玩家。')
    if kind=='dice':
        if bets:
            if user_id is None:
                if len(seats)!=1:raise RuleError('請指定本人的骰寶押注。')
                user_id=seats[0]['user_id']
            own=next((s for s in seats if s['user_id']==user_id),None)
            if not own or own['stack']<needed:raise RuleError('本人的籌碼不足以支付押注。')
        maximum=max(dice_gross(list(d),bets,cfg) for d in product(range(1,7),repeat=3)) if bets else 0
    else:
        if kind=='slot':maximum=stake*max(*cfg['triples'],cfg['pair'])
        elif kind=='inbetween':maximum=0
        elif kind=='baccarat':maximum=max(game_settings.net_return(stake,cfg[k]) for k in ('player_bp','banker_bp','tie_bp'))*len(seats)
        else:maximum=risk_return(kind,stake,5 if kind=='mines' else 6,mode=mode,settings=cfg)*len(seats)
    if room['bank'] < maximum: raise RuleError('本桌莊家點數不足以保留最大派彩，請另開新桌。')
    if kind=='inbetween':
        shoe,shoe_state,reshuffled=_gate_shoe(room,deck)
    room['stake']=stake
    if kind=='tower':room['tower_mode']=mode
    players = [dict(user_id=s['user_id'],nickname=s['nickname'],seat=s['seat'],stack=s['stack'],starting_stack=s['stack'],contribution=0,street_bet=0,folded=False,last_action='',hole=[]) for s in seats]
    room['hand_no'] += 1
    h = dict(id=secrets.token_hex(12),number=room['hand_no'],phase=kind,players=players,board=[],results=[],pots=[],actor=None,deadline=clock+30,turn_id=secrets.token_hex(12),started_at=clock,game_type=kind,game_settings=snapshot)
    room.update(hand=h,status='playing')
    poker.log(room, f"第 {room['hand_no']} 局 · {CATALOG[kind]['name']} 開始",clock)
    if kind=='dice':
        h.update(phase='betting',pending=[p['user_id'] for p in players])
        for p in players:p['bets']=[]
        if bets:act(room,user_id,'bet',clock,{'bets':bets})
    elif kind == 'baccarat':
        shoe = list(deck) if deck is not None else list(poker.DECK)*cfg['decks']
        if len(shoe)<6 or any(c not in poker.DECK for c in shoe): raise RuleError('百家樂牌組無效。')
        if deck is None: secrets.SystemRandom().shuffle(shoe)
        h.update(deck=shoe,pending=[p['user_id'] for p in players],player_cards=[],banker_cards=[])
        for p in players: p['side']=None
    else:
        p=players[0]
        if kind=='inbetween':
            pillars=sorted([shoe.pop(),shoe.pop()],key=gate_rank)
            h.update(deck=shoe,pillars=pillars,third=None,remaining_cards=len(shoe),gate_rules_version=2,
                     gate_shoe_version=1,shoe_id=shoe_state['id'],shoe_round=shoe_state['round_no'],shoe_reshuffled=reshuffled)
            h['gate_quotes']=gate_quotes(h)
            h['winning_cards']=h['gate_quotes'].get('between',{}).get('winning_cards',0)
            room['gate_shoe']=shoe_state
            if reshuffled:poker.log(room,'52 張牌已重新洗牌 · 新牌靴開始',clock)
            arcade._turn(room,p['user_id'],clock);poker.sync_stacks(room)
            return
        poker.pay(p,needed)
        if kind == 'slot':
            h['slot_payout_version']=SLOT_PAYOUT_VERSION
            h['reels']=[game_settings.weighted(cfg['weights']) for _ in range(3)]
            finish_slot(room,clock)
        else:
            h.update(selected=[],steps=0,cashout=stake)
            if kind == 'mines': h['hazards']=secrets.SystemRandom().sample(range(25),cfg['bombs'])
            else:
                counts=[cfg['fixed_bombs']]*6 if mode=='fixed' else cfg['progressive_bombs'][:]
                h.update(tower_options=4,tower_mode=mode,bomb_counts=counts,hazards=[secrets.randbelow(4) if mode=='fixed' and count==1 else secrets.SystemRandom().sample(range(4),count) for count in counts])
            arcade._turn(room,p['user_id'],clock)
    poker.sync_stacks(room)

def slot_multiplier(reels, payout_version=SLOT_PAYOUT_VERSION,settings=None):
    if payout_version not in (1,2,SLOT_PAYOUT_VERSION):raise RuleError('拉霸派彩版本無效。')
    triples=SLOT_BASE_TRIPLES if payout_version==1 else SLOT_V2_TRIPLES if payout_version==2 else (settings or game_settings.DEFAULTS['slot'])['triples']
    if reels[0] == reels[1] == reels[2]: return triples[reels[0]]
    return (2 if payout_version==1 else 5 if payout_version==2 else (settings or game_settings.DEFAULTS['slot'])['pair']) if reels[0] == reels[1] else 0

def finish_slot(room,clock):
    h=room['hand'];p=h['players'][0];gross=room['stake']*slot_multiplier(h['reels'],h.get('slot_payout_version',1),game_settings.params(h,'slot'))
    label='三連線' if len(set(h['reels']))==1 else '前兩格相同' if gross else '未中獎'
    arcade._complete(room,clock,{p['user_id']:gross},{p['user_id']:label},f'拉霸 · {label} · 總返還 {gross:,} 點',p['contribution']-gross)

def baccarat_value(card): return 1 if card[0]=='A' else int(card[0]) if card[0] in '23456789' else 0

def baccarat_total(cards): return sum(map(baccarat_value,cards))%10

def banker_draws(total,third):
    if third is None: return total<=5
    return total<=2 or total==3 and third!=8 or total==4 and 2<=third<=7 or total==5 and 4<=third<=7 or total==6 and 6<=third<=7

def finish_baccarat(room,clock):
    h=room['hand'];a=h['player_cards'];b=h['banker_cards'];cfg=game_settings.params(h,'baccarat')
    for _ in range(2): a.append(h['deck'].pop());b.append(h['deck'].pop())
    if max(baccarat_total(a),baccarat_total(b))<8:
        third=None
        if baccarat_total(a)<=5:
            a.append(h['deck'].pop());third=baccarat_value(a[-1])
        if banker_draws(baccarat_total(b),third): b.append(h['deck'].pop())
    av,bv=baccarat_total(a),baccarat_total(b)
    winner='tie' if av==bv else 'player' if av>bv else 'banker'
    h.update(winner=winner,player_total=av,banker_total=bv,board=a+b)
    payouts={};labels={}
    names={'tie':'和','player':'閒','banker':'莊'}
    for p in h['players']:
        bet=p['contribution'];side=p['side']
        gross=game_settings.net_return(bet,cfg[side+'_bp']) if side==winner else bet if winner=='tie' and side in ('banker','player') else 0
        payouts[p['user_id']]=gross
        labels[p['user_id']]='未下注' if not bet else '和局退本金' if winner=='tie' and side!='tie' else '命中' if gross else '未中'
    arcade._complete(room,clock,payouts,labels,f"百家樂 · 閒 {av} / 莊 {bv} · {names[winner]}勝" if winner!='tie' else f'百家樂 · 閒 {av} / 莊 {bv} · 和局',sum(p['contribution'] for p in h['players'])-sum(payouts.values()))

def legal_actions(room,uid):
    if room['status']!='playing': return None
    h=room['hand'];p=next((p for p in h['players'] if p['user_id']==uid),None)
    if not p:return None
    if room['game_type'] in ('baccarat','dice'): return {'actions':['bet','skip']} if uid in h['pending'] else None
    if room['game_type']=='inbetween':
        if h['actor']!=uid:return None
        quotes=gate_quotes(h);loss=max((q['loss_multiplier'] for q in quotes.values()),default=1)
        maximum=min(1000,p['stack']//loss)
        return {'actions':(['shoot'] if quotes and maximum else [])+['skip'],'max_stake':maximum,'directions':list(quotes),'quotes':quotes,'loss_multiplier':loss}
    return {'actions':['pick']+(['cashout'] if h['steps'] else [])} if h['actor']==uid else None

def finish_risk(room,clock,lost=False):
    h=room['hand'];p=h['players'][0];gross=0 if lost else h['cashout'];label='踩雷' if lost else '未翻格退本金' if not h['steps'] else '收取獎勵'
    arcade._complete(room,clock,{p['user_id']:gross},{p['user_id']:label},f"{CATALOG[room['game_type']]['name']} · {label} · 總返還 {gross:,} 點",p['contribution']-gross)

def gate_rank(card):return 'A23456789TJQK'.index(card[0])+1


def gate_return(stake,winning_cards,target_bps=9700,post_cards=0,loss_multiplier=1,total_cards=50):
    if not 0<winning_cards<=total_cards:raise RuleError('這組門柱沒有可命中的點數，請重發門柱。')
    # RTP uses all actually deducted points, including the extra post penalty.
    return stake*target_bps*(total_cards+(loss_multiplier-1)*post_cards)//(10000*winning_cards)


def gate_quotes(hand):
    """Freeze odds from the unseen shoe composition, never its card order."""
    if 'gate_quotes' in hand:return hand['gate_quotes']
    low,high=map(gate_rank,hand['pillars']);modern=hand.get('gate_rules_version',1)>=2
    target=game_settings.params(hand,'inbetween')['target_bps']
    if hand.get('gate_shoe_version')==1:
        remaining=hand['deck'];total=len(remaining)
        choices={'between':sum(low<gate_rank(c)<high for c in remaining)}
        if modern and low==high:choices={'up':sum(gate_rank(c)>low for c in remaining),'down':sum(gate_rank(c)<low for c in remaining)}
        posts=sum(gate_rank(c) in (low,high) for c in remaining)
    else:
        # Existing hands that began before the shoe change keep their quote.
        total=50;choices={'between':max(0,high-low-1)*4}
        if modern and low==high:choices={'up':4*(13-low),'down':4*(low-1)}
        posts=2 if low==high else 6
    loss=(3 if low==high else 2) if modern else 1
    return {direction:{'winning_cards':wins,'total_cards':total,'post_cards':posts,'loss_multiplier':loss,
                       'return_numerator':target*(total+(loss-1)*posts),'return_denominator':10000*wins}
            for direction,wins in choices.items() if wins}


def finish_gate(room,clock,stake=None,direction=None):
    h=room['hand'];p=h['players'][0];gross=0
    if stake is None:label='略過門柱';h['board']=h['pillars'][:]
    else:
        poker.integer(stake,'下注點數',1,1000)
        quotes=gate_quotes(h)
        if direction is None and 'between' in quotes:direction='between'
        if not isinstance(direction,str) or direction not in quotes:raise RuleError('請先選擇有效的往上或往下方向；相鄰門柱請免費略過。')
        quote=quotes[direction];maximum_loss=stake*quote['loss_multiplier']
        if maximum_loss>p['stack']:raise RuleError(f'籌碼須足以支付最大損失 {maximum_loss:,} 點，請降低下注或從錢包帶入。')
        potential=stake*quote['return_numerator']//quote['return_denominator']
        if room['bank']+stake<potential:raise RuleError('本桌莊家點數不足以支付這次最高派彩，請降低下注或另開新桌。')
        third=h['deck'][-1];point=gate_rank(third);low,high=map(gate_rank,h['pillars'])
        won=point>low if direction=='up' else point<low if direction=='down' else low<point<high
        post=point in (low,high);charged=maximum_loss if post else stake
        poker.pay(p,charged);room['stake']=stake;h['third']=h['deck'].pop();gross=potential if won else 0
        label='射中龍門' if won else '對子撞柱' if post and low==high else '撞柱' if post else '射出門外'
        h.update(board=[h['pillars'][0],h['third'],h['pillars'][1]],stake=stake,direction=direction,
                 winning_cards=quote['winning_cards'],charged=charged,max_loss=maximum_loss)
    p['last_action']=label
    h['remaining_cards']=len(h['deck'])
    arcade._complete(room,clock,{p['user_id']:gross},{p['user_id']:label},f'{label} · 扣點 {p["contribution"]:,} · 總返還 {gross:,} 點',p['contribution']-gross)
    room['next_hand_at']=clock


def finish_dice(room,clock):
    h=room['hand'];cfg=game_settings.params(h,'dice');dice=[game_settings.weighted(cfg['weights'])+1 for _ in range(3)]
    h.update(dice=dice,total=sum(dice),triple=len(set(dice))==1)
    payouts={p['user_id']:dice_gross(dice,p['bets'],cfg) for p in h['players']}
    labels={p['user_id']:'未下注' if not p['bets'] else '命中' if payouts[p['user_id']] else '未中' for p in h['players']}
    if len(h['players'])==1:h['bets']=h['players'][0]['bets']
    arcade._complete(room,clock,payouts,labels,f"骰寶 · {' / '.join(map(str,dice))} · 合計 {h['total']} 點{' · 豹子' if h['triple'] else ''}",sum(p['contribution'] for p in h['players'])-sum(payouts.values()))

def act(room,uid,action,clock,data=None,timed_out=False):
    legal=legal_actions(room,uid)
    if not legal or action not in legal['actions']:raise RuleError('此動作目前不允許。')
    h=room['hand'];kind=room['game_type'];data=data or {};p=arcade._player(room,uid)
    if kind=='inbetween':finish_gate(room,clock,poker.integer(data.get('stake'),'下注點數',1,1000) if action=='shoot' else None,data.get('direction'))
    elif kind=='dice':
        if action=='bet':
            bets=dice_bets(data.get('bets'));amount=sum(bet['amount'] for bet in bets)
            if amount>p['stack']:raise RuleError('本人的籌碼不足以支付押注。')
            # Reserve all accepted bets against the same one of 216 outcomes.
            maximum=max(sum(dice_gross(list(d),bets if q['user_id']==uid else q['bets'],game_settings.params(h,'dice')) for q in h['players']) for d in product(range(1,7),repeat=3))
            if maximum>room['bank']:raise RuleError('本桌莊家點數不足以保留最大派彩，請調整押注或略過。')
            poker.pay(p,amount);p['bets']=bets
        h['pending'].remove(uid);p['last_action']='已下注' if action=='bet' else '略過'
        if not h['pending']:finish_dice(room,clock)
    elif kind=='baccarat':
        if action=='bet':
            side=data.get('side')
            if side not in ('banker','player','tie'): raise RuleError('請選擇莊、閒或和。')
            poker.pay(p,room['stake']);p['side']=side
        h['pending'].remove(uid);p['last_action']='已下注' if action=='bet' else '略過'
        if not h['pending']:finish_baccarat(room,clock)
    elif action=='cashout': finish_risk(room,clock)
    else:
        cell=poker.integer(data.get('cell'),'格子',0,24 if kind=='mines' else h.get('tower_options',3)-1)
        if kind=='mines' and cell in h['selected']:raise RuleError('這格已經翻開。')
        h['selected'].append(cell)
        hazard=h['hazards'] if kind=='mines' else h['hazards'][h['steps']]
        lost=cell in hazard if isinstance(hazard,list) else cell==hazard
        if lost: finish_risk(room,clock,True)
        else:
            h['steps']+=1;h['cashout']=risk_return(kind,room['stake'],h['steps'],h.get('tower_options',3),h.get('tower_mode','fixed'),game_settings.params(h,kind))
            if h['steps']==(5 if kind=='mines' else 6):finish_risk(room,clock)
            else:arcade._turn(room,uid,clock)
    if timed_out:
        seat=poker.seated(room,uid)
        if seat:seat.update(away=True,away_reason='timeout')
    poker.sync_stacks(room)

def tick(room,clock,due_at=None):
    if room['status']!='playing':return False
    h=room['hand'];due_at=clock if due_at is None else due_at
    if room['game_type'] in ('baccarat','dice'):
        changed=False
        for uid in list(h['pending']):
            seat=poker.seated(room,uid)
            if h['deadline']<=due_at or seat and seat['away']:
                act(room,uid,'skip',clock,timed_out=True);changed=True
        return changed
    seat=poker.seated(room,h['actor'])
    if h['deadline']>due_at and not (seat and seat['away']):return False
    if seat:seat.update(away=True,away_reason='timeout')
    if room['game_type']=='inbetween':finish_gate(room,clock)
    else:finish_risk(room,clock)
    return True

def leave(room,uid,clock):
    seat=poker.seated(room,uid)
    if not seat:raise RuleError('你目前未入座。')
    if room['status']!='playing' or not arcade._player(room,uid):return poker.depart(room,seat,clock)
    seat['leaving']=True
    if room['game_type'] in ('baccarat','dice'):
        if uid in room['hand']['pending']:act(room,uid,'skip',clock)
    elif room['game_type']=='inbetween':finish_gate(room,clock)
    else:finish_risk(room,clock)
    poker.sync_stacks(room)

def public_view(room,viewer_id):
    # Persisted rooms contain JSON records only. Clone containers without
    # deepcopy's per-leaf memo bookkeeping on every spin and push snapshot.
    view=view_cache.clone(room);view.pop('departures',None);view.pop('bank',None);view.pop('gate_shoe',None)
    for s in view['seats']:s.pop('session_id',None)
    h=view.get('hand')
    if h:
        h.pop('deck',None);h.pop('pending',None)
        if room['game_type']=='inbetween':h['gate_quotes']=gate_quotes(room['hand'])
        if h['phase']!='showdown':
            h.pop('hazards',None)
            for p in h['players']:
                p.pop('side',None)
                if room['game_type']=='dice' and p['user_id']!=viewer_id:p['bets']=[]
        if room['game_type'] in ('mines','tower'):
            limit=5 if room['game_type']=='mines' else 6
            if room['game_type']=='tower':h.setdefault('tower_options',3)
            h['returns']=[risk_return(room['game_type'],room['stake'],k,h.get('tower_options',3),h.get('tower_mode','fixed'),game_settings.params(h,room['game_type'])) for k in range(1,limit+1)]
    view['legal']=legal_actions(room,viewer_id)
    return view
