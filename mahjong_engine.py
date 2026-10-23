"""Taiwan 16-tile mahjong. Authoritative draws, claims, scoring and zero-sum chips.

Physical tile IDs 0..135 are four copies of each type; 136..143 are flowers.
This table uses head-bump ron, a 64-tai payout cap and no declared-ready bonus.
"""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import secrets
import poker_engine as poker
import arcade_engine as arcade
import game_settings

RuleError=poker.RuleError
DECK=list(range(144))
TAI_CAP=64
WINDS=['東','南','西','北']
NAMES=[f'{n}{s}' for s in ('萬','筒','索') for n in range(1,10)]+['東','南','西','北','中','發','白']+list('春夏秋冬梅蘭菊竹')

def kind(tile):return tile//4 if tile<136 else 34+tile-136
def label(tile):return NAMES[kind(tile)]
def options(raw=None):
    raw={} if raw is None else raw
    if not isinstance(raw,dict):raise RuleError('麻將底台格式無效。')
    return {'version':1,'base':poker.integer(raw.get('base',100),'底',1,1000),
            'tai_value':poker.integer(raw.get('tai_value',20),'每台點數',1,1000),'tai_cap':TAI_CAP}

def reserve(room):
    cfg=room.get('mahjong_rules') or options()
    return cfg['base']+TAI_CAP*cfg['tai_value']

def new_room(name,owner_id,game_type='mahjong',buy_in=3000,stake=100,mahjong_rules=None):
    cfg=options(mahjong_rules);r=poker.new_room(name,owner_id,buy_in=buy_in)
    r.update(game_type='mahjong',capacity=4,bank=0,stake=cfg['base'],mahjong_rules=cfg,
             mahjong_dealer=None,mahjong_streak=0,mahjong_round=0)
    return r

def sit(room,user_id,nickname,clock,seat=None,buy_in=None):
    if len(room['seats'])>=4:raise RuleError('麻將為四人桌，座位已滿。')
    if seat is not None and (type(seat) is not int or not 0<=seat<4):raise RuleError('座位編號無效。')
    poker.sit(room,user_id,nickname,clock,seat,buy_in)

def player(room,uid):return next((p for p in room['hand']['players'] if p['user_id']==uid),None)
def turn_id(hand):return hand.get('turn_id') if hand and hand['phase']!='showdown' else None

@lru_cache(maxsize=8192)
def _groups(counts,needed):
    if not any(counts):return ((),) if needed==0 else ()
    if needed<=0:return ()
    k=next(i for i,v in enumerate(counts) if v);c=list(counts);out=[]
    if c[k]>=3:
        c[k]-=3
        out.extend(((k,k,k),)+tail for tail in _groups(tuple(c),needed-1));c[k]+=3
    if k<27 and k%9<=6 and c[k+1] and c[k+2]:
        for i in (k,k+1,k+2):c[i]-=1
        out.extend(((k,k+1,k+2),)+tail for tail in _groups(tuple(c),needed-1))
    return tuple(out)

def decompositions(tiles,meld_count=0):
    if len(tiles)!=17-3*meld_count or any(type(t) is not int or not 0<=t<136 for t in tiles):return []
    counts=Counter(map(kind,tiles))
    if any(v>4 for v in counts.values()):return []
    c=[counts[i] for i in range(34)];out=[]
    for pair in range(34):
        if c[pair]<2:continue
        c[pair]-=2
        out.extend((pair,groups) for groups in _groups(tuple(c),5-meld_count));c[pair]+=2
    return out

def waits(tiles,meld_count=0):
    counts=Counter(map(kind,tiles))
    return [k for k in range(34) if counts[k]<4 and decompositions(tiles+[k*4],meld_count)]

def score(p,winning_tile,self_draw=False,round_wind=0,kong=False,last=False,rob=False,heaven=False,earth=False):
    """Choose the best legal decomposition; never sum mutually exclusive patterns."""
    tiles=p['tiles'][:] if self_draw else p['tiles']+[winning_tile]
    forms=decompositions(tiles,len(p['melds']))
    if not forms:raise RuleError('這副牌尚未構成五組面子加一對將眼。')
    closed=all(m['concealed'] for m in p['melds']);flowers=p['flowers'];seat_wind=p['wind']
    before=tiles[:];before.remove(winning_tile)
    own_counts=Counter(map(kind,before+[t for m in p['melds'] for t in m['tiles']]))
    single=len([k for k in waits(before,len(p['melds'])) if own_counts[k]<4])==1
    candidates=[]
    for pair,groups in forms:
        # The discard-completed group cannot count as a concealed triplet. When
        # ambiguous, evaluate all possible winning placements and take the best.
        placements=[None] if self_draw else ([('pair',None)] if pair==kind(winning_tile) else [])+[(i,g) for i,g in enumerate(groups) if kind(winning_tile) in g]
        for placement,_ in placements if not self_draw else [(None,None)]:
            items=[]
            def add(name,tai):items.append({'name':name,'tai':tai})
            trip=[g[0] for g in groups if len(set(g))==1]+[kind(m['tiles'][0]) for m in p['melds'] if m['kind']!='chi']
            concealed=sum(len(set(g))==1 and (self_draw or i!=placement) for i,g in enumerate(groups))+sum(m['concealed'] for m in p['melds'])
            all_kinds=[kind(t) for t in tiles]+[kind(t) for m in p['melds'] for t in m['tiles']]
            suits={k//9 for k in all_kinds if k<27};honors=any(k>=27 for k in all_kinds)
            if heaven:add('天胡',24)
            elif earth:add('地胡',16)
            elif closed and self_draw:add('門清自摸',3)
            else:
                if closed:add('門清',1)
                if self_draw:add('自摸',1)
            if not suits:add('字一色',16)
            elif len(suits)==1:add('混一色' if honors else '清一色',4 if honors else 8)
            if len(trip)==5 and suits:add('碰碰胡',4)
            if concealed>=3:add({3:'三暗刻',4:'四暗刻',5:'五暗刻'}[concealed],{3:2,4:5,5:8}[concealed])
            dragons=sum(k in trip for k in (31,32,33));winds=sum(k in trip for k in range(27,31))
            if dragons==3:add('大三元',8)
            elif dragons==2 and pair in (31,32,33):add('小三元',4)
            else:
                for k in (31,32,33):
                    if k in trip:add(NAMES[k],1)
            if winds==4:add('大四喜',16)
            elif winds==3 and 27<=pair<=30:add('小四喜',8)
            else:
                if 27+seat_wind in trip:add('門風',1)
                if 27+round_wind in trip:add('圈風',1)
            for f in flowers:
                if (f-136)%4==seat_wind:add('正花・'+label(f),1)
            for start,name in [(136,'四季齊'),(140,'四花齊')]:
                if all(f in flowers for f in range(start,start+4)):add(name,2)
            if len(p['melds'])==5 and not any(m['concealed'] for m in p['melds']):add('半求人' if self_draw else '全求人',1 if self_draw else 2)
            if single:add('獨聽',1)
            if not flowers and not honors and not trip and not single and not self_draw:add('平胡',2)
            if kong and not heaven:add('槓上開花',1)
            if rob:add('搶槓',1)
            if last:add('海底撈月' if self_draw else '河底撈魚',1)
            candidates.append({'items':items,'tai':sum(x['tai'] for x in items)})
    return max(candidates,key=lambda x:x['tai'])

def _turn(room,uid,clock,phase='discard'):
    room['hand'].update(actor=uid,phase=phase,deadline=clock+(8 if phase=='claim' else 20),turn_id=secrets.token_hex(12))

def start_hand(room,clock,deck=None,settings=None):
    if room['status']!='waiting':raise RuleError('上一局仍在進行。')
    seats=sorted(room['seats'],key=lambda p:p['seat']);required=reserve(room)
    if len(seats)!=4 or any(s['away'] or s['leaving'] or s['stack']<required for s in seats):raise RuleError(f'需要四位已入座、未暫離且至少有 {required:,} 點的玩家。')
    wall=list(DECK if deck is None else deck)
    if len(wall)!=144 or set(wall)!=set(DECK) or any(type(t) is not int for t in wall):raise RuleError('麻將牌組須為完整且不重複的 144 張牌。')
    if deck is None:secrets.SystemRandom().shuffle(wall)
    dealer=room.get('mahjong_dealer')
    if dealer not in [s['user_id'] for s in seats]:dealer=seats[0]['user_id'];room.update(mahjong_streak=0,mahjong_round=0)
    ds=next(s['seat'] for s in seats if s['user_id']==dealer)
    players=[dict(user_id=s['user_id'],nickname=s['nickname'],seat=s['seat'],wind=(s['seat']-ds)%4,
                  stack=s['stack'],starting_stack=s['stack'],contribution=0,street_bet=0,folded=False,hole=[],
                  tiles=[],melds=[],flowers=[],river=[],last_action='',passed_hu=False,passed_pong=[],draws=0) for s in seats]
    room['hand_no']+=1;room['dealer_seat']=ds;room['mahjong_dealer']=dealer
    h=dict(id=secrets.token_hex(12),number=room['hand_no'],players=players,wall=wall,phase='dealing',game_type='mahjong',
           game_settings=deepcopy(settings or game_settings.default('mahjong')),mahjong_rules=deepcopy(room['mahjong_rules']),
           reserve=required,board=[],results=[],pots=[],actor=None,deadline=None,turn_id=None,started_at=clock,
           dealer=dealer,streak=room.get('mahjong_streak',0),round_wind=(room.get('mahjong_round',0)//4)%4,
           last_discard=None,drawn_tile=None,draw_source='initial',discard_count=0,calls=0,pending={},responses={})
    room.update(status='playing',hand=h)
    for p in players:poker.pay(p,required)
    for _ in range(16):
        for p in players:_take(h,p,False)
    d=player(room,dealer);h['drawn_tile']=_take(h,d,False)
    for p in players:p['tiles'].sort(key=lambda t:(kind(t),t))
    _turn(room,dealer,clock);poker.sync_stacks(room)
    poker.log(room,f'第 {room["hand_no"]} 局・台灣麻將，{d["nickname"]} 作莊',clock)
    _flower_win(room,clock)

def _take(h,p,supplement):
    while len(h['wall'])>16:
        tile=h['wall'].pop(-1 if supplement else 0)
        if tile>=136:p['flowers'].append(tile);supplement=True;h['draw_source']='flower';continue
        p['tiles'].append(tile);return tile
    return None

def _flower_win(room,clock):
    h=room['hand'];eight=next((p for p in h['players'] if len(p['flowers'])==8),None)
    seven=next((p for p in h['players'] if len(p['flowers'])==7),None)
    if eight:_finish(room,eight['user_id'],clock,self_draw=True,special='八仙過海');return True
    other=next((p for p in h['players'] if seven and p['user_id']!=seven['user_id'] and p['flowers']),None)
    if seven and other:_finish(room,seven['user_id'],clock,loser=other['user_id'],special='七搶一');return True
    return False

def _draw(room,uid,clock,supplement=False):
    h=room['hand'];p=player(room,uid);h['draw_source']='kong' if supplement else 'normal'
    tile=_take(h,p,supplement)
    if _flower_win(room,clock):return
    if tile is None:_finish(room,None,clock);return
    p['passed_hu']=False;p['passed_pong']=[];p['draws']+=1;p['tiles'].sort(key=lambda t:(kind(t),t));h['drawn_tile']=tile
    _turn(room,uid,clock);poker.sync_stacks(room)

def _next(room,uid):
    ps=sorted(room['hand']['players'],key=lambda p:p['seat']);return ps[([p['user_id'] for p in ps].index(uid)+1)%4]['user_id']

def _claim_options(h,p,tile,source,rob=False):
    out={};k=kind(tile);counts=Counter(map(kind,p['tiles']))
    if not p['passed_hu'] and decompositions(p['tiles']+[tile],len(p['melds'])):out['hu']=True
    if rob:return out
    if counts[k]>=2 and k not in p.get('passed_pong',[]):out['pong']=[t for t in p['tiles'] if kind(t)==k][:2]
    if counts[k]>=3 and k not in p.get('passed_pong',[]) and len(h['wall'])>16:out['kong']=[t for t in p['tiles'] if kind(t)==k][:3]
    ps=sorted(h['players'],key=lambda x:x['seat']);uids=[q['user_id'] for q in ps]
    if p['user_id']==uids[(uids.index(source)+1)%4] and k<27:
        chi=[]
        for start in range(max(k//9*9,k-2),min(k,k//9*9+6)+1):
            others=[x for x in range(start,start+3) if x!=k]
            if all(counts[x] for x in others):chi.append([next(t for t in p['tiles'] if kind(t)==x) for x in others])
        if chi:out['chi']=chi
    return out

def _open_claim(room,tile,uid,clock,rob=False):
    h=room['hand'];h.update(last_discard={'tile':tile,'from':uid,'rob':rob},pending={},responses={},drawn_tile=None)
    for p in h['players']:
        if p['user_id']==uid:continue
        opts=_claim_options(h,p,tile,uid,rob)
        if opts:h['pending'][str(p['user_id'])]=opts
    if h['pending']:_turn(room,None,clock,'claim')
    elif rob:_finish_added_kong(room,clock)
    else:_draw(room,_next(room,uid),clock)

def legal_actions(room,uid):
    if room['status']!='playing':return None
    h=room['hand'];p=player(room,uid)
    if not p:return None
    if h['phase']=='claim':
        opts=h['pending'].get(str(uid))
        return {'actions':list(opts)+['pass'],**deepcopy(opts)} if opts and str(uid) not in h['responses'] else None
    if h['actor']!=uid:return None
    actions=['discard'];out={'discard_tiles':p['tiles'][:]}
    if h['drawn_tile'] in p['tiles'] and decompositions(p['tiles'],len(p['melds'])):actions.append('hu')
    if h['drawn_tile'] in p['tiles'] and len(h['wall'])>16:
        counts=Counter(map(kind,p['tiles']));concealed=[[t for t in p['tiles'] if kind(t)==k] for k,v in counts.items() if v==4]
        added=[t for t in p['tiles'] if any(m['kind']=='pong' and kind(m['tiles'][0])==kind(t) for m in p['melds'])]
        if concealed:actions.append('concealed_kong');out['concealed_kong']=concealed
        if added:actions.append('added_kong');out['added_kong']=added
    return {'actions':actions,**out}

def _resolve(room,clock):
    h=room['hand'];d=h['last_discard'];source=d['from'];tile=d['tile']
    candidates=[(int(uid),r) for uid,r in h['responses'].items() if r['action']!='pass']
    if candidates:
        order=[];u=source
        for _ in range(3):u=_next(room,u);order.append(u)
        uid,response=min(candidates,key=lambda x:({'hu':0,'kong':1,'pong':1,'chi':2}[x[1]['action']],order.index(x[0])))
        if response['action']=='hu':_finish(room,uid,clock,loser=source,rob=d['rob']);return
        p=player(room,uid);action=response['action'];selected=response['tiles']
        for t in selected:p['tiles'].remove(t)
        p['melds'].append({'kind':action,'tiles':sorted(selected+[tile]),'concealed':False,'from':source})
        player(room,source)['river'][-1]['claimed']=True
        h.update(pending={},responses={},drawn_tile=None);h['calls']+=1;p['last_action']={'chi':'吃','pong':'碰','kong':'明槓'}[action]
        if action=='kong':_draw(room,uid,clock,True)
        else:_turn(room,uid,clock)
    elif d['rob']:_finish_added_kong(room,clock)
    else:_draw(room,_next(room,source),clock)

def _claims_ready(room):
    """Do not wait for lower-priority callers after the winning claim is fixed."""
    h=room['hand']
    if len(h['responses'])==len(h['pending']):return True
    source=player(room,h['last_discard']['from'])['seat'];rank={'hu':0,'kong':1,'pong':1,'chi':2}
    offered=[(rank[r['action']],(player(room,int(uid))['seat']-source)%4) for uid,r in h['responses'].items() if r['action']!='pass']
    if not offered:return False
    best=min(offered)
    for uid,opts in h['pending'].items():
        if uid in h['responses']:continue
        possible=(min(rank[a] for a in opts),(player(room,int(uid))['seat']-source)%4)
        if possible<best:return False
    return True

def _finish_added_kong(room,clock):
    h=room['hand'];d=h['last_discard'];p=player(room,d['from']);tile=d['tile']
    meld=next(m for m in p['melds'] if m['kind']=='pong' and kind(m['tiles'][0])==kind(tile))
    p['tiles'].remove(tile);meld['tiles'].append(tile);meld['kind']='kong';h['calls']+=1
    _draw(room,p['user_id'],clock,True)

def act(room,uid,action,clock,data=None):
    legal=legal_actions(room,uid)
    if not legal or action not in legal['actions']:raise RuleError('目前不能執行這個麻將動作。')
    h=room['hand'];p=player(room,uid);data=data or {}
    if h['phase']=='claim':
        opts=h['pending'][str(uid)];selected=[]
        if action=='chi':
            selected=data.get('tiles')
            if not isinstance(selected,list) or any(type(t) is not int for t in selected) or sorted(selected) not in [sorted(x) for x in opts['chi']]:raise RuleError('請選擇畫面列出的吃牌組合。')
        elif action in ('pong','kong'):selected=opts[action]
        if 'hu' in opts and action!='hu':p['passed_hu']=True
        if 'pong' in opts and action not in ('pong','kong','hu'):p.setdefault('passed_pong',[]).append(kind(h['last_discard']['tile']))
        h['responses'][str(uid)]={'action':action,'tiles':selected};p['last_action']={'pass':'過','hu':'胡','chi':'吃','pong':'碰','kong':'槓'}[action]
        if _claims_ready(room):_resolve(room,clock)
    elif action=='discard':
        tile=data.get('tile')
        if type(tile) is not int or tile not in p['tiles']:raise RuleError('請選擇自己手中的一張牌。')
        p['tiles'].remove(tile);p['river'].append({'tile':tile,'claimed':False});p['last_action']='打 '+label(tile);h['discard_count']+=1
        poker.log(room,f'{p["nickname"]} 打出 {label(tile)}',clock);_open_claim(room,tile,uid,clock)
    elif action=='hu':_finish(room,uid,clock,self_draw=True)
    elif action=='concealed_kong':
        selected=data.get('tiles')
        if not isinstance(selected,list) or any(type(t) is not int for t in selected) or sorted(selected) not in [sorted(x) for x in legal['concealed_kong']]:raise RuleError('暗槓牌組無效。')
        for t in selected:p['tiles'].remove(t)
        p['melds'].append({'kind':'kong','tiles':selected,'concealed':True,'from':uid});h['calls']+=1;_draw(room,uid,clock,True)
    else:
        tile=data.get('tile')
        if type(tile) is not int or tile not in legal['added_kong']:raise RuleError('加槓牌張無效。')
        _open_claim(room,tile,uid,clock,True)
    poker.sync_stacks(room)

def _finish(room,winner,clock,self_draw=False,loser=None,rob=False,special=None):
    h=room['hand'];refunds={p['user_id']:h['reserve'] for p in h['players']};labels={p['user_id']:'流局' for p in h['players']};payments=[]
    if winner is not None:
        p=player(room,winner);tile=h['drawn_tile'] if self_draw else h['last_discard']['tile'] if not special else None
        result={'tai':8,'items':[{'name':special,'tai':8}]} if special else score(p,tile,self_draw,h['round_wind'],h['draw_source'] in ('kong','flower') and self_draw,len(h['wall'])<=16,rob,h['discard_count']==0 and not h['calls'] and self_draw,h['discard_count']>0 and p['draws']==1 and not h['calls'] and self_draw and p['wind']!=0)
        payers=[q for q in h['players'] if q['user_id']!=winner] if self_draw else [player(room,loser)]
        cfg=h['mahjong_rules']
        for q in payers:
            items=deepcopy(result['items']);dealer_tai=1+2*h['streak'] if h['dealer'] in (winner,q['user_id']) else 0
            if dealer_tai:items.append({'name':'莊家／連莊','tai':dealer_tai})
            raw=sum(x['tai'] for x in items);tai=min(TAI_CAP,raw);amount=cfg['base']+tai*cfg['tai_value']
            refunds[q['user_id']]-=amount;refunds[winner]+=amount;labels[q['user_id']]='被自摸' if self_draw else '放槍'
            payments.append({'from':q['user_id'],'to':winner,'base':cfg['base'],'tai_value':cfg['tai_value'],'tai':tai,'raw_tai':raw,'amount':amount,'items':items})
        labels[winner]=special or ('自摸' if self_draw else '胡牌');h.update(winner=winner,self_draw=self_draw,winning_tile=tile,payments=payments,score=result)
        summary=f'{p["nickname"]} {labels[winner]}・'+ '／'.join(f'{x["tai"]} 台 {x["amount"]:,} 點' for x in payments)
    else:summary='流局・預留點數全數退回';h.update(winner=None,payments=[])
    assert all(x>=0 for x in refunds.values()) and sum(refunds.values())==4*h['reserve']
    if winner is None or winner==h['dealer']:room['mahjong_streak']=h['streak']+1
    else:room.update(mahjong_dealer=_next(room,h['dealer']),mahjong_streak=0,mahjong_round=room.get('mahjong_round',0)+1)
    arcade._complete(room,clock,refunds,labels,summary,0)

def tick(room,clock,due_at=None):
    if room['status']!='playing':return False
    h=room['hand'];due=clock if due_at is None else due_at
    if h['phase']=='claim':
        changed=False
        for uid in h['pending']:
            if uid in h['responses']:continue
            seat=poker.seated(room,int(uid))
            if due>=h['deadline'] or seat and (seat['away'] or seat['leaving']):
                p=player(room,int(uid));opts=h['pending'][uid]
                if 'hu' in opts:p['passed_hu']=True
                if 'pong' in opts:p.setdefault('passed_pong',[]).append(kind(h['last_discard']['tile']))
                h['responses'][uid]={'action':'pass','tiles':[]};changed=True
        if _claims_ready(room):_resolve(room,clock);poker.sync_stacks(room);return True
        return changed
    seat=poker.seated(room,h['actor'])
    if due<h['deadline'] and not (seat and (seat['away'] or seat['leaving'])):return False
    p=player(room,h['actor']);tile=h['drawn_tile'] if h['drawn_tile'] in p['tiles'] else p['tiles'][-1]
    # Temporary leave is automatic draw-and-discard, never an extra penalty.
    act(room,p['user_id'],'discard',clock,{'tile':tile})
    if seat:seat.update(away=True,away_reason='timeout')
    return True

def leave(room,uid,clock):
    seat=poker.seated(room,uid)
    if not seat:raise RuleError('你目前未入座。')
    if room['status']!='playing' or not player(room,uid):poker.depart(room,seat,clock);return
    seat.update(leaving=True,away=True);tick(room,clock)

def public_view(room,viewer_id):
    v=deepcopy(room);v.pop('departures',None);v.pop('bank',None);v['required_stack']=reserve(room)
    for s in v['seats']:s.pop('session_id',None)
    h=v.get('hand')
    if h:
        h['wall_count']=max(0,len(h['wall'])-16);h.pop('wall',None);h.pop('pending',None);h.pop('responses',None)
        own=next((p for p in h['players'] if p['user_id']==viewer_id),None)
        if h['phase']!='showdown':
            if not own or h['actor']!=viewer_id:h['drawn_tile']=None
            for p in h['players']:
                p['tile_count']=len(p['tiles']);p.pop('passed_hu',None);p.pop('passed_pong',None)
                if p['user_id']!=viewer_id:
                    p['tiles']=[]
                    for m in p['melds']:
                        if m['concealed']:m['tiles']=[None]*4
    v['legal']=legal_actions(room,viewer_id)
    return v
