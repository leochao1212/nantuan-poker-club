"""Server-authoritative, non-redeemable virtual-point table games.

Rooms use the existing seating, receipts, chat and wallet transaction boundary.
House games keep a finite table bank; players + bank conserve virtual points.
Only public_view is allowed to cross the API boundary.
"""
from collections import Counter
from copy import deepcopy
import secrets
import poker_engine as poker
import game_settings

RuleError=poker.RuleError
CATALOG={
 'big2':{'name':'大老二','capacity':4,'minimum':4},
 'blackjack':{'name':'21 點','capacity':6,'minimum':1},
 'roulette':{'name':'歐式輪盤','capacity':6,'minimum':1},
}
RED={1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BIG_RANKS='3456789TJQKA2'
SUITS='cdhs'
BLACKJACK_DECKS=6
BLACKJACK_CUT_REMAINING=78


def big2_options(raw=None):
    raw={} if raw is None else raw
    if not isinstance(raw,dict):raise RuleError('大老二規則格式無效。')
    result={'version':2,'triples':raw.get('triples',True),'twos_double':raw.get('twos_double',False)}
    if any(type(result[k]) is not bool for k in ('triples','twos_double')):raise RuleError('大老二規則開關須為布林值。')
    return result


def big2_reserve(room,settings=None):
    if settings is None and room.get('status')=='playing' and room.get('hand',{}).get('reserve') is not None:return room['hand']['reserve']
    cfg=(settings or room.get('next_game_settings') or game_settings.default('big2'))['params']
    penalties=cfg['penalties'];twos=room.get('big2_rules',{}).get('twos_double')
    return room['stake']*max(n*penalties[2 if n==13 else 1 if n>=8 else 0]*(2**min(4,n) if twos else 1) for n in range(1,14))


def _modern_big2(room):return room['hand'].get('big2_rules',{}).get('version')==2


def new_room(name,owner_id,game_type,buy_in=1000,stake=10,settings=None):
    if game_type not in CATALOG:raise RuleError('找不到這個遊戲。')
    poker.integer(stake,'每局基本點數',2 if game_type=='blackjack' else 1,game_settings.bet_limit(settings))
    if game_type=='blackjack' and stake%2:raise RuleError('21 點基本下注須為偶數，以完整支付 Blackjack 3:2 點數。')
    room=poker.new_room(name,owner_id,buy_in=buy_in)
    room.update(game_type=game_type,stake=stake,capacity=CATALOG[game_type]['capacity'],bank=1_000_000 if game_type!='big2' else 0)
    if game_type=='big2':room['big2_rules']=big2_options()
    game_settings.fund_bet_limit(room,settings or game_settings.default(game_type))
    return room


def sit(room,user_id,nickname,clock,seat=None,buy_in=None):
    cap=CATALOG[room['game_type']]['capacity']
    if len(room['seats'])>=cap:raise RuleError(f'本桌最多 {cap} 人。')
    if seat is not None and (type(seat) is not int or not 0<=seat<cap):raise RuleError('座位編號無效。')
    poker.sit(room,user_id,nickname,clock,seat,buy_in)


def turn_id(hand):return hand.get('turn_id') if hand and hand.get('phase')!='showdown' else None


def _turn(room,uid,clock,index=0):
    hand=room['hand'];hand.update(actor=uid,active_index=index,deadline=clock+(15 if room['game_type']=='big2' and _modern_big2(room) else 30),turn_id=secrets.token_hex(12))


def _player(room,uid):return next((p for p in room['hand']['players'] if p['user_id']==uid),None)


def blackjack_bet(room,seat):return seat.get('blackjack_bet',room['stake'])


def set_blackjack_bet(room,uid,amount,settings=None):
    if room.get('game_type')!='blackjack' or room['status']!='waiting':raise RuleError('請在 21 點開局前設定下注。')
    seat=poker.seated(room,uid)
    if not seat or seat['away'] or seat['leaving']:raise RuleError('請先回到座位再設定下注。')
    poker.integer(amount,'下注點數',2,game_settings.bet_limit(settings))
    if amount%2:raise RuleError('21 點下注須為偶數，以完整支付 Blackjack 3:2 點數。')
    if amount>seat['stack']:raise RuleError('下注超過你的桌上籌碼，請先從錢包帶入。')
    seat['blackjack_bet']=amount
    seat.pop('blackjack_ready_for',None)


def blackjack_waiting_players(room):
    return [s for s in room['seats'] if not s['away'] and not s['leaving'] and s['stack']>=2]


def blackjack_ready(room,seat):
    return (room['status']=='waiting' and not seat['away'] and not seat['leaving']
            and seat['stack']>=blackjack_bet(room,seat)
            and seat.get('blackjack_ready_for')==room['hand_no']+1)


def confirm_blackjack_bet(room,uid,amount,clock,expected_hand_number,settings=None):
    if type(expected_hand_number) is not int or expected_hand_number!=room['hand_no']+1:
        raise RuleError('下注已換局，請更新牌桌後再確認。')
    if clock<room['next_hand_at']:raise RuleError('請等本局結算後再確認下一局下注。')
    set_blackjack_bet(room,uid,amount,settings)
    for seat in room['seats']:
        if blackjack_bet(room,seat)>game_settings.bet_limit(settings):seat.pop('blackjack_ready_for',None)
    poker.seated(room,uid)['blackjack_ready_for']=room['hand_no']+1
    players=blackjack_waiting_players(room)
    if players and all(blackjack_ready(room,s) for s in players):
        start_hand(room,clock,settings=settings)
        return True
    return False


def _draw(hand):
    if not hand['deck']:raise RuleError('牌組已用完，請聯絡管理員。')
    return hand['deck'].pop()


def _blackjack_shoe(room,player_count,deck=None,decks=BLACKJACK_DECKS):
    """Keep the sole private remaining deck in room.hand, including on disk.

    Four split hands can use five cards each; the dealer needs at most 17.
    Reserve a full possible round before dealing, never reshuffle mid-hand.
    Explicit decks are an engine test hook, never accepted by the HTTP API.
    """
    previous=room.get('hand');state=room.get('blackjack_shoe')
    if deck is None and state and state.get('version')==1 and state.get('decks',6)==decks:
        if not previous or previous.get('shoe_id')!=state.get('id') or previous.get('phase')!='showdown':
            raise RuleError('21 點牌靴狀態無效，請聯絡管理員。')
        remaining=previous.get('deck')
        if not isinstance(remaining,list) or any(c not in poker.DECK for c in remaining) or any(n>decks for n in Counter(remaining).values()):
            raise RuleError('21 點牌靴資料無效，請聯絡管理員。')
        if len(remaining)>state.get('cut_remaining',78) and len(remaining)>=player_count*20+17:
            return list(remaining),{**state,'round_no':state['round_no']+1},False
    shoe=list(deck) if deck is not None else list(poker.DECK)*decks
    if len(shoe)<26 or any(c not in poker.DECK for c in shoe):raise RuleError('21 點牌組無效。')
    if deck is None and len(shoe)<player_count*20+17:raise RuleError('目前牌靴副數不足以支援本桌人數，請減少人數或增加牌靴副數。')
    if deck is None:secrets.SystemRandom().shuffle(shoe)
    return shoe,{'version':1,'id':secrets.token_hex(12),'round_no':1,'decks':decks,'cut_remaining':len(poker.DECK)*decks//4},True


def start_hand(room,clock,deck=None,settings=None):
    if room['status']!='waiting':raise RuleError('上一局仍在進行。')
    if room['game_type']!='roulette' and clock<room['next_hand_at']:raise RuleError('請等結算顯示完畢，再開始下一局。')
    kind=room['game_type'];snapshot=deepcopy(settings or game_settings.default(kind));cfg=snapshot['params']
    minimum=1 if kind=='roulette' else big2_reserve(room,snapshot) if kind=='big2' else room['stake']
    seats=[s for s in room['seats'] if not s['away'] and not s['leaving'] and s['stack']>=(blackjack_bet(room,s) if kind=='blackjack' else minimum)]
    if len(seats)<CATALOG[kind]['minimum']:raise RuleError(f"至少需要 {CATALOG[kind]['minimum']} 位未暫離且有足夠籌碼的玩家。"+(f' 大老二每人須有 {minimum:,} 點作為本局最高賠付預留，未使用的點數會退還。' if kind=='big2' else ''))
    if kind=='blackjack':
        for seat in seats:poker.integer(blackjack_bet(room,seat),'下注點數',2,game_settings.bet_limit(snapshot))
    if kind=='big2':poker.integer(room['stake'],'每張牌點數',1,game_settings.bet_limit(snapshot))
    if kind=='roulette':liability=(game_settings.bet_limit(snapshot)*max(cfg[k] for k in ('number_bp','even_bp','group_bp'))+9999)//10000*len(seats)
    elif kind=='blackjack':liability=sum((blackjack_bet(room,s)*max(cfg['blackjack_bp'],8*cfg['win_bp'],4*cfg['five_card_bp'])+9999)//10000 for s in seats)
    else:liability=0
    if kind!='big2' and room['bank']<liability:raise RuleError('本桌電腦莊家的虛擬點數不足，請另開新桌。')
    if kind=='blackjack':shoe,shoe_state,reshuffled=_blackjack_shoe(room,len(seats),deck,cfg['decks'])
    elif kind!='roulette':
        shoe=list(deck) if deck is not None else list(poker.DECK)
        if kind=='big2' and (len(shoe)!=52 or set(shoe)!=set(poker.DECK)):raise RuleError('大老二須使用完整 52 張牌。')
        if deck is None:secrets.SystemRandom().shuffle(shoe)
    else:shoe=[]
    players=[{'user_id':s['user_id'],'nickname':s['nickname'],'seat':s['seat'],'stack':s['stack'],
              'starting_stack':s['stack'],'contribution':0,'street_bet':0,'folded':False,'last_action':'','hole':[]} for s in sorted(seats,key=lambda s:s['seat'])]
    room['hand_no']+=1
    hand={'id':secrets.token_hex(12),'number':room['hand_no'],'phase':kind,'players':players,'deck':shoe,
          'board':[],'results':[],'pots':[],'actor':None,'deadline':clock+30,'turn_id':secrets.token_hex(12),'started_at':clock,'game_type':kind,'game_settings':snapshot}
    room.update(hand=hand,status='playing')
    __import__('economy').attach(room)
    poker.log(room,f"第 {room['hand_no']} 局 · {CATALOG[kind]['name']} 開始",clock)
    if kind=='big2':
        hand['big2_rules']=big2_options(room.get('big2_rules'))
        hand['reserve']=minimum
        for p in players:p['cards']=[];poker.pay(p,minimum)
        for _ in range(13):
            for p in players:p['cards'].append(_draw(hand))
        for p in players:p['cards'].sort(key=card_key)
        first=min((card_key(c),c,p['user_id']) for p in players for c in p['cards'])
        # Every deal starts with club three, regardless of the previous winner.
        hand.update(first_card=first[1],first_play=True,current_play=[],last_player=None,passes=[])
        _turn(room,first[2],clock)
    elif kind=='blackjack':
        for s in room['seats']:s.pop('blackjack_ready_for',None)
        room['blackjack_shoe']=shoe_state
        hand.update(shoe_id=shoe_state['id'],shoe_round=shoe_state['round_no'],shoe_reshuffled=reshuffled)
        if reshuffled:poker.log(room,f"{cfg['decks']} 副牌已重新洗牌 · 新牌靴開始",clock)
        hand['blackjack_rules']={'five_card_charlie':True,'five_card_profit':2}
        hand['dealer']=[]
        for p in players:
            bet=blackjack_bet(room,poker.seated(room,p['user_id']))
            poker.pay(p,bet);p['hands']=[{'cards':[],'bet':bet,'status':'playing','split':False}]
        for _ in range(2):
            for p in players:p['hands'][0]['cards'].append(_draw(hand))
            hand['dealer'].append(_draw(hand))
        for p in players:
            if blackjack_total(p['hands'][0]['cards'])==21:p['hands'][0]['status']='stand'
        if blackjack_total(hand['dealer'])==21:_finish_blackjack(room,clock)
        else:_next_blackjack(room,clock)
    else:
        hand.update(phase='betting',pending=[p['user_id'] for p in players])
        for p in players:p['bets']=[]
    poker.sync_stacks(room)


def card_key(card):return BIG_RANKS.index(card[0])*4+SUITS.index(card[1])


def big2_score(cards,legacy=False):
    if not isinstance(cards,list) or len(cards) not in (1,2,3,5) or any(not isinstance(c,str) or c not in poker.DECK for c in cards) or len(set(cards))!=len(cards):
        raise RuleError('請選擇有效的單張、對子、三條或五張牌型。')
    ranks=[BIG_RANKS.index(c[0]) for c in cards];counts=Counter(ranks);highest=max(cards,key=card_key)
    if len(cards)==1:return (1,card_key(cards[0]))
    if len(cards) in (2,3):
        if len(counts)!=1:raise RuleError('這組牌不是對子或三條。')
        return (len(cards),ranks[0],SUITS.index(highest[1]))
    flush=len({c[1] for c in cards})==1
    straight=len(counts)==5 and max(ranks)-min(ranks)==4 and max(ranks)<12
    if straight and flush:return (5,4,max(ranks),SUITS.index(highest[1]))
    groups=sorted(((count,rank) for rank,count in counts.items()),reverse=True)
    if groups[0][0]==4:return (5,3,groups[0][1])
    if [g[0] for g in groups]==[3,2]:return (5,2,groups[0][1])
    if flush:return (5,1,*sorted(ranks,reverse=True),SUITS.index(highest[1])) if legacy else (5,1,SUITS.index(highest[1]),*sorted(ranks,reverse=True))
    if straight:return (5,0,max(ranks),SUITS.index(highest[1]))
    raise RuleError('五張須為順子、同花、葫蘆、鐵支或同花順；順子不含 2，A 只接 K。')


def _next_big2(room,after,clock):
    hand=room['hand'];alive=[p for p in hand['players'] if not p['folded']]
    if len(alive)==1:return _finish_big2(room,alive[0]['user_id'],clock)
    next_player=_big2_order(room,alive,after)[0]
    if hand['current_play']:
        others={p['user_id'] for p in alive if p['user_id']!=hand['last_player']}
        if others<=set(hand['passes']):
            next_player=next((p for p in alive if p['user_id']==hand['last_player']),next_player)
            hand.update(current_play=[],passes=[])
    _turn(room,next_player['user_id'],clock)


def _big2_order(room,players,after):
    if not _modern_big2(room):return poker.clockwise(players,after)
    return sorted(players,key=lambda p:(after-p['seat']-1)%room['capacity'])


def _top_card(room,p):
    others=[q for q in room['hand']['players'] if not q['folded'] and q['user_id']!=p['user_id']]
    following=_big2_order(room,others,p['seat'])
    return max(p['cards'],key=card_key) if _modern_big2(room) and following and len(following[0]['cards'])==1 else None


def _act_big2(room,uid,action,data,clock):
    hand=room['hand'];p=_player(room,uid)
    if action=='pass':
        if not hand['current_play']:raise RuleError('新一輪由你先出，不能 Pass。')
        hand['passes'].append(uid);p['last_action']='Pass'
    else:
        cards=data.get('cards');score=big2_score(cards,legacy=not _modern_big2(room))
        if len(cards)==3 and not hand.get('big2_rules',{}).get('triples',True):raise RuleError('本桌未開放單打三條。')
        if any(c not in p['cards'] for c in cards):raise RuleError('只能出自己手上的牌。')
        if hand['first_play'] and hand['first_card'] and hand['first_card'] not in cards:raise RuleError('第一手必須包含梅花 3。')
        if len(cards)==1 and _top_card(room,p) and cards[0]!=_top_card(room,p):raise RuleError('下一家只剩一張牌；出單張時必須頂大，打出手中最大的牌。')
        if hand['current_play'] and (len(cards)!=len(hand['current_play']) or score<=big2_score(hand['current_play'],legacy=not _modern_big2(room))):raise RuleError('須出相同張數、且比上一組更大的牌。')
        for c in cards:p['cards'].remove(c)
        hand.update(current_play=sorted(cards,key=card_key),board=sorted(cards,key=card_key),last_player=uid,passes=[],first_play=False)
        p['last_action']=f'出 {len(cards)} 張'
        poker.log(room,f"{p['nickname']} · {p['last_action']}",clock)
        if not p['cards']:return _finish_big2(room,uid,clock)
    _next_big2(room,p['seat'],clock)


def blackjack_total(cards):
    total=sum(11 if c[0]=='A' else 10 if c[0] in 'TJQK' else int(c[0]) for c in cards);aces=sum(c[0]=='A' for c in cards)
    while total>21 and aces:total-=10;aces-=1
    return total


def blackjack_natural(cards):
    return len(cards)==2 and blackjack_total(cards)==21


def _next_blackjack(room,clock):
    hand=room['hand']
    for p in hand['players']:
        for i,h in enumerate(p['hands']):
            if h['status']=='playing':return _turn(room,p['user_id'],clock,i)
    _finish_blackjack(room,clock)


def _five_card_win(hand,h):
    return hand.get('blackjack_rules',{}).get('five_card_charlie',False) and len(h['cards'])==5 and blackjack_total(h['cards'])<=21


def _act_blackjack(room,uid,action,clock):
    hand=room['hand'];p=_player(room,uid);i=hand['active_index'];h=p['hands'][i]
    if action=='stand':h['status']='stand';p['last_action']='停牌'
    elif action=='hit':
        h['cards'].append(_draw(hand));total=blackjack_total(h['cards']);p['last_action']='要牌'
        if total>21:h['status']='bust'
        elif _five_card_win(hand,h):h['status']='five_card';p['last_action']='五張未爆 · 自動勝出'
        elif total==21:h['status']='stand'
    elif action=='double':
        poker.pay(p,h['bet']);h['bet']*=2;h['cards'].append(_draw(hand));h['status']='bust' if blackjack_total(h['cards'])>21 else 'stand';p['last_action']='加倍'
    elif action=='split':
        poker.pay(p,h['bet']);aces=h['cards'][0][0]=='A'
        hands=[{'cards':[c,_draw(hand)],'bet':h['bet'],'status':'stand' if aces else 'playing','split':True,'split_aces':aces} for c in h['cards']]
        for split in hands:
            if blackjack_total(split['cards'])==21:split['status']='stand'
        p['hands'][i:i+1]=hands;p['last_action']='分牌'
    poker.log(room,f"{p['nickname']} · {p['last_action']}",clock)
    _next_blackjack(room,clock)


def roulette_wins(bet,number):
    kind=bet['kind']
    if kind=='number':return number==bet['number']
    if number==0:return False
    if kind=='red':return number in RED
    if kind=='black':return number not in RED
    if kind=='odd':return number%2==1
    if kind=='even':return number%2==0
    if kind=='low':return number<=18
    if kind=='high':return number>=19
    if kind.startswith('dozen'):return (number-1)//12==int(kind[-1])-1
    if kind.startswith('column'):return (number-1)%3==int(kind[-1])-1
    return False


def _act_roulette(room,uid,action,data,clock):
    hand=room['hand'];p=_player(room,uid)
    bets=[]
    if action=='bet':
        raw=data.get('bets')
        if not isinstance(raw,list) or not 1<=len(raw)<=49:raise RuleError('請選擇至少一項押注。')
        keys=set()
        for b in raw:
            if not isinstance(b,dict):raise RuleError('押注格式無效。')
            kind=b.get('kind');number=b.get('number');amount=b.get('amount')
            if kind not in ('number','red','black','odd','even','low','high','dozen1','dozen2','dozen3','column1','column2','column3'):raise RuleError('押注種類無效。')
            if kind=='number' and (type(number) is not int or not 0<=number<=36):raise RuleError('號碼須為 0–36。')
            poker.integer(amount,'押注點數',1,game_settings.room_bet_limit(room))
            key=(kind,number if kind=='number' else None)
            if key in keys:raise RuleError('相同押注請合併金額。')
            keys.add(key);bets.append({'kind':kind,'number':number if kind=='number' else None,'amount':amount})
        total=sum(b['amount'] for b in bets)
        if total>min(p['stack'],game_settings.room_bet_limit(room)):raise RuleError(f'本局押注超過可用籌碼或 {game_settings.room_bet_limit(room):,} 點上限。')
        poker.pay(p,total)
    p['bets']=bets;p['last_action']='已押注' if bets else '本局略過'
    hand['pending'].remove(uid)
    poker.log(room,f"{p['nickname']} · {p['last_action']}",clock)
    if not hand['pending']:_finish_roulette(room,clock)


def legal_actions(room,uid):
    if room['status']!='playing' or not room.get('hand'):return None
    hand=room['hand'];p=_player(room,uid)
    if not p or p['folded']:return None
    kind=room['game_type']
    if kind=='roulette':return {'actions':['bet','skip'],'max_total':min(p['stack'],game_settings.room_bet_limit(room))} if uid in hand['pending'] else None
    if hand['actor']!=uid:return None
    if kind=='big2':return {'actions':['play']+(['pass'] if hand['current_play'] else []),'first_card':hand['first_card'] if hand['first_play'] else None,'required_single':_top_card(room,p),'triples':hand.get('big2_rules',{}).get('triples',True)}
    h=p['hands'][hand['active_index']];actions=['hit','stand']
    if len(h['cards'])==2 and p['stack']>=h['bet'] and not h.get('split_aces'):
        actions.append('double')
        equal=lambda c:10 if c[0] in 'TJQK' else 11 if c[0]=='A' else int(c[0])
        if len(p['hands'])<4 and equal(h['cards'][0])==equal(h['cards'][1]):actions.append('split')
    return {'actions':actions,'active_index':hand['active_index']}


def act(room,uid,action,clock,data=None,timed_out=False):
    legal=legal_actions(room,uid)
    if not legal or action not in legal['actions']:raise RuleError('現在不是你的行動時間，或此動作不允許。')
    if timed_out:
        seat=poker.seated(room,uid)
        if seat:seat.update(away=True,away_reason='timeout')
    kind=room['game_type']
    if kind=='big2':_act_big2(room,uid,action,data or {},clock)
    elif kind=='blackjack':_act_blackjack(room,uid,action,clock)
    else:_act_roulette(room,uid,action,data or {},clock)
    poker.sync_stacks(room)


def _complete(room,clock,payouts,labels,summary,bank_delta=0):
    hand=room['hand'];room['bank']+=bank_delta
    if room['bank']<0:raise RuleError('虛擬莊家點數不足。')
    for p in hand['players']:
        payout=payouts.get(p['user_id'],0);p['stack']+=payout
        hand['results'].append({'user_id':p['user_id'],'nickname':p['nickname'],'profit':p['stack']-p['starting_stack'],'payout':payout,'rank':labels.get(p['user_id'],''),'hole':[],'folded':p['folded']})
    assert sum(r['profit'] for r in hand['results'])+bank_delta==0
    hand.update(phase='showdown',actor=None,deadline=None,turn_id=None,finished_at=clock,summary=summary,bank_delta=bank_delta)
    room.update(status='waiting',next_hand_at=clock if room['game_type'] in ('roulette','slot','mines','tower','dice') else clock+3)
    poker.log(room,summary,clock);poker.sync_stacks(room)
    for seat in list(room['seats']):
        if seat['leaving']:poker.depart(room,seat,clock)


def _finish_big2(room,winner,clock):
    hand=room['hand'];pot=sum(p['contribution'] for p in hand['players']);p=_player(room,winner)
    labels={q['user_id']:'先出完' if q['user_id']==winner else '離桌' if q['folded'] else f"剩 {len(q['cards'])} 張" for q in hand['players']}
    if _modern_big2(room):
        details={};payouts={};won=0
        for q in hand['players']:
            count=len(q['cards']);penalties=game_settings.params(hand,'big2')['penalties'];multiplier=penalties[2 if count==13 else 1 if count>=8 else 0]
            if hand['big2_rules']['twos_double']:multiplier*=2**sum(c[0]=='2' for c in q['cards'])
            charge=0 if q['user_id']==winner else count*room['stake']*multiplier
            assert 0<=charge<=q['contribution']
            details[q['user_id']]={'remaining':count,'multiplier':multiplier,'charged':charge,'reserve_refund':q['contribution']-charge}
            payouts[q['user_id']]=q['contribution']-charge;won+=charge
            if q['user_id']!=winner:labels[q['user_id']]=f'剩 {count} 張 ×{multiplier} · 扣 {charge:,} 點'
        payouts[winner]+=won
        hand['pots']=[{'amount':won,'winners':[winner],'refund':False}]
        room['big2_last_winner']=winner
        _complete(room,clock,payouts,labels,f"{p['nickname']} 勝出 · 淨贏 {won:,} 點 · 未使用預留已退還")
        for row in hand['results']:row.update(details[row['user_id']])
        return
    hand['pots']=[{'amount':pot,'winners':[winner],'refund':False}]
    room['big2_last_winner']=winner
    _complete(room,clock,{winner:pot},labels,f"{p['nickname']} 勝出 · 本局底池 {pot:,} 點")


def _finish_blackjack(room,clock):
    hand=room['hand'];dealer=hand['dealer'];natural=blackjack_natural(dealer);cfg=game_settings.params(hand,'blackjack')
    if not natural and any(h['status']!='bust' for p in hand['players'] for h in p['hands']):
        while blackjack_total(dealer)<17:dealer.append(_draw(hand))
    score=blackjack_total(dealer);hand['dealer_natural']=natural;payouts={};labels={}
    for p in hand['players']:
        payout=0;names=[]
        for h in p['hands']:
            total=blackjack_total(h['cards']);bj=not h['split'] and blackjack_natural(h['cards'])
            if total>21:
                rate=cfg.get('bust_refund_bps',0);protected=rate==10000 or rate>0 and secrets.randbelow(10000)<rate
                gross=__import__('economy').benefit(room,p['user_id'],h['bet']) if protected else 0;label=f'爆牌保護 · 補回 {gross:,} 點' if protected and 'economy' in hand else '爆牌保護 · 本手全額退注' if protected else '爆牌'
                if rate:h['benefit']={'kind':'bust_refund','rate_bps':rate,'triggered':bool(protected)}
            elif natural:gross=h['bet'] if bj else 0;label='和局' if bj else '莊家 Blackjack'
            elif _five_card_win(hand,h):gross=game_settings.net_return(h['bet'],cfg['five_card_bp']);label=f"五張未爆 · 淨贏 {cfg['five_card_bp']/10000:g} 倍"
            elif bj:gross=game_settings.net_return(h['bet'],cfg['blackjack_bp']);label='Blackjack'
            elif score>21 or total>score:gross=game_settings.net_return(h['bet'],cfg['win_bp']);label='勝出'
            elif total==score:
                rate=cfg.get('tie_win_bps',0);preferred=rate==10000 or rate>0 and secrets.randbelow(10000)<rate
                extra=__import__('economy').benefit(room,p['user_id'],game_settings.net_return(h['bet'],cfg['win_bp'])-h['bet']) if preferred else 0
                gross=h['bet']+extra;label=f'同點優待 · 加碼 {extra:,} 點' if preferred and 'economy' in hand else '同點優待 · 玩家勝出' if preferred else '和局'
                if rate:h['benefit']={'kind':'tie_win','rate_bps':rate,'triggered':bool(preferred)}
            else:gross=0;label='落敗'
            h['outcome']=label;h['payout']=gross;payout+=gross;names.append(label)
        payouts[p['user_id']]=payout;labels[p['user_id']]='／'.join(names)
    hand['board']=list(dealer)
    _complete(room,clock,payouts,labels,f"莊家 {'爆牌' if score>21 else str(score)+' 點'} · 21 點結算",sum(p['contribution'] for p in hand['players'])-sum(payouts.values()))


def _finish_roulette(room,clock,number=None):
    cfg=game_settings.params(room['hand'],'roulette');number=game_settings.weighted(cfg['weights']) if number is None else number
    poker.integer(number,'輪盤號碼',0,36)
    hand=room['hand'];hand['number']=number;hand['color']='green' if number==0 else 'red' if number in RED else 'black';payouts={};labels={}
    for p in hand['players']:
        payout=sum(game_settings.net_return(b['amount'],game_settings.roulette_bp(cfg,b['kind'])) for b in p['bets'] if roulette_wins(b,number))
        payouts[p['user_id']]=payout;labels[p['user_id']]='未下注' if not p['bets'] else '命中' if payout else '未中'
    _complete(room,clock,payouts,labels,f"輪盤開出 {number} · {'綠' if number==0 else '紅' if number in RED else '黑'}",sum(p['contribution'] for p in hand['players'])-sum(payouts.values()))


def tick(room,clock,due_at=None):
    due_at=clock if due_at is None else due_at;changed=False
    if room['status']!='playing':return False
    if room['game_type']=='roulette':
        for uid in list(room['hand']['pending']):
            seat=poker.seated(room,uid)
            if room['hand']['deadline']<=due_at or seat and seat['away']:
                act(room,uid,'skip',clock,timed_out=True);changed=True
        return changed
    while room['status']=='playing':
        hand=room['hand'];uid=hand['actor'];seat=poker.seated(room,uid)
        if hand['deadline']>due_at and not (seat and seat['away']):break
        if room['game_type']=='blackjack':
            for h in _player(room,uid)['hands']:
                if h['status']=='playing':h['status']='stand'
            if seat:seat.update(away=True,away_reason='timeout')
            poker.log(room,f"{seat['nickname']} · 逾時自動停牌",clock);_next_blackjack(room,clock)
        else:
            player=_player(room,uid)
            action='pass' if hand['current_play'] else 'play';data={'cards':[_top_card(room,player) or min(player['cards'],key=card_key)]}
            act(room,uid,action,clock,data,timed_out=True)
        changed=True
    poker.sync_stacks(room)
    return changed


def leave(room,uid,clock):
    seat=poker.seated(room,uid)
    if not seat:raise RuleError('你目前未入座。')
    p=_player(room,uid) if room.get('hand') else None
    if room['status']!='playing' or not p:return poker.depart(room,seat,clock)
    seat['leaving']=True
    poker.log(room,f"{seat['nickname']} 本局結算後離桌",clock)
    if room['game_type']=='big2':
        p['folded']=True
        if room['hand']['first_play'] and room['hand'].get('first_card') in p['cards']:
            room['hand']['first_card']=None
            poker.log(room,'首出者離桌，由下一位自由領出。',clock)
        if room['hand']['actor']==uid or len([q for q in room['hand']['players'] if not q['folded']])==1:_next_big2(room,p['seat'],clock)
    elif room['game_type']=='blackjack':
        for h in p['hands']:
            if h['status']=='playing':h['status']='stand'
        _next_blackjack(room,clock)
    elif uid in room['hand']['pending']:
        _act_roulette(room,uid,'skip',{},clock)
    poker.sync_stacks(room)


def public_view(room,viewer_id):
    view=deepcopy(room);view.pop('departures',None);view.pop('bank',None)
    view.pop('blackjack_shoe',None)
    for s in view['seats']:
        s.pop('session_id',None)
        if room['game_type']=='blackjack':
            s['blackjack_ready']=blackjack_ready(room,s)
            s.pop('blackjack_ready_for',None)
    hand=view.get('hand')
    if hand:
        hand.pop('deck',None);hand.pop('pending',None)
        if room['game_type']=='big2':
            for p in hand['players']:
                p['card_count']=len(p['cards'])
                if p['user_id']!=viewer_id:p['cards']=[]
        elif room['game_type']=='blackjack' and hand['phase']!='showdown':hand['dealer']=[hand['dealer'][0],None]
        if room['game_type']=='blackjack' and room.get('blackjack_shoe') and hand.get('shoe_id')==room['blackjack_shoe']['id']:
            remaining=len(room['hand']['deck'])
            view['blackjack_shoe']={'id':hand['shoe_id'],'round_no':hand['shoe_round'],
                'total_cards':len(poker.DECK)*room['blackjack_shoe'].get('decks',6),'remaining_cards':remaining,
                'cut_remaining':room['blackjack_shoe'].get('cut_remaining',78),'cut_reached':remaining<=room['blackjack_shoe'].get('cut_remaining',78)}
            hand.update(shoe_remaining=remaining,shoe_cut_reached=remaining<=room['blackjack_shoe'].get('cut_remaining',78))
    view['legal']=legal_actions(room,viewer_id)
    if room['game_type']=='big2':view['required_stack']=big2_reserve(room)
    return view
