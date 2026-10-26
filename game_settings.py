"""Versioned public game rules. Never contain player-specific odds or future draws."""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from itertools import product
import hashlib,json,re,secrets
from poker_engine import RuleError

DEFAULTS={
 'holdem':{},
 'mahjong':{},
 'big2':{'penalties':[1,2,4]},
 'blackjack':{'win_bp':10000,'blackjack_bp':15000,'five_card_bp':20000,'decks':6},
 'roulette':{'number_bp':350000,'even_bp':10000,'group_bp':20000,'weights':[1]*37},
 'baccarat':{'player_bp':10000,'banker_bp':9500,'tie_bp':80000,'decks':8},
 'slot':{'triples':[77,32,20,14,10,7],'pair':4,'weights':[1]*6},
 'mines':{'target_bps':9700,'bombs':5},
 'tower':{'target_bps':9700,'fixed_bombs':1,'progressive_bombs':[1,1,1,2,2,2]},
 'dice':{'even':1,'faces':[1,2,3],'totals':[50,18,14,12,8,6,6,6,6,8,12,14,18,50],'any_triple':24,'triple':150,'weights':[1]*6},
 'inbetween':{'target_bps':9700,'post_protection_bps':5000},
}
NAMES=dict(zip(DEFAULTS,['德州撲克','台灣麻將','大老二','21 點','輪盤','百家樂','拉霸','礦區','爬塔','骰寶','射龍門']))
DEFAULTS['limits']={'max_bet':10000}
NAMES['limits']='共用下注上限'
DEFAULTS['fishing']={'target_bps':9500,'daily_casts':20}
NAMES['fishing']='楠團漁港'
def field(key,label,minimum,maximum,labels=None,unit='integer'):
 return {'key':key,'label':label,'min':minimum,'max':maximum,'labels':labels,'unit':unit}
SCHEMAS={
 'inbetween':[field('target_bps','保護前派彩基準返還率（%）',100,30000,unit='percent_bp'),field('post_protection_bps','撞柱保護觸發率（%，0 為關閉）',0,10000,unit='percent_bp')],
 'holdem':[],
 'mahjong':[],
 'big2':[field('penalties','剩牌賠付倍率',1,20,['1–7 張','8–12 張','13 張'])],
 'blackjack':[field('win_bp','普通勝局淨贏倍數',0,1000000,unit='net_bp'),field('blackjack_bp','Blackjack 淨贏倍數',0,1000000,unit='net_bp'),field('five_card_bp','五張未爆淨贏倍數',0,1000000,unit='net_bp'),field('decks','牌靴副數',1,8)],
 'roulette':[field('number_bp','單號淨贏倍數',0,1000000,unit='net_bp'),field('even_bp','紅黑／單雙／大小淨贏倍數',0,1000000,unit='net_bp'),field('group_bp','打／列淨贏倍數',0,1000000,unit='net_bp'),field('weights','號碼抽樣權重',0,1000,[str(i) for i in range(37)])],
 'baccarat':[field('player_bp','閒勝淨贏倍數',0,1000000,unit='net_bp'),field('banker_bp','莊勝淨贏倍數',0,1000000,unit='net_bp'),field('tie_bp','和局淨贏倍數',0,1000000,unit='net_bp'),field('decks','每局洗牌副數',1,8)],
 'slot':[field('triples','三連線總返還倍數（含本金）',1,500,['七','皇冠','鑽石','鈴鐺','櫻桃','BAR']),field('pair','只有前兩格相同：總返還倍數',1,500),field('weights','各軸共用的符號權重',0,1000,['七','皇冠','鑽石','鈴鐺','櫻桃','BAR'])],
 'mines':[field('target_bps','派彩基準返還率（%）',100,30000,unit='percent_bp'),field('bombs','25 格中的地雷數',1,20)],
 'tower':[field('target_bps','派彩基準返還率（%）',100,30000,unit='percent_bp'),field('fixed_bombs','固定難度每層地雷數',1,3),field('progressive_bombs','遞增難度各層地雷數',1,3,[f'{i}F' for i in range(1,7)])],
 'dice':[field('even','大小／單雙淨贏倍數',0,500),field('faces','單骰點數淨贏倍數',0,500,['出現 1 顆','出現 2 顆','出現 3 顆']),field('totals','總和淨贏倍數',0,500,[str(i) for i in range(4,18)]),field('any_triple','任意豹子淨贏倍數',0,500),field('triple','指定豹子淨贏倍數',0,500),field('weights','每顆骰子共用的點數權重',0,1000,[str(i) for i in range(1,7)])],
}
NOTES={
 'limits':'適用原本有單局下注上限的遊戲。輪盤與骰寶限制每人每局合計；21 點限制初始下注，加倍／分牌依原規則追加；射龍門撞柱額外扣點不算新下注。大老二限制每張牌底分，麻將底台與德州全押沿用各自桌規。儲存後下一局生效，進行中的局保留原上限。',
 'mahjong':'台灣 16 張，144 張含八花，五面一將。房主自訂底／台；每筆支付＝底＋台數×台值，最多 64 台；放槍者獨付、自摸三家分別付。莊家 1 台、連莊每次加 2 台，只對涉及莊家的收付加計。胡＞碰／槓＞吃，同時胡採截胡；過胡須自摸一張解禁。公開桌規與逐項結算，公平洗牌，無莊家抽水。',
 'inbetween':'標準 52 張連續牌靴，剩 13 張以下於下一局重洗。A=1、K=13，同點可選上下。普通撞柱扣 2 倍、對子扣 3 倍；抽中柱牌才依設定機率啟動保護，公開作廢柱牌並按原牌序補到非柱牌，仍可能射出門外。保留保護前含本金倍率，保護會提高整體返還率，牌桌顯示本局實際機率及返還率；小額派彩向下取整。設定只於新局生效，所有玩家一致。',
 'holdem':'玩家按底池與邊池分配，沒有電腦莊家賠率。標準 52 張公平洗牌，機率固定。',
 'big2':'標準 52 張公平洗牌，機率固定。倍率決定輸家扣款及贏家收入，最高賠付預留會一併調整。',
 'blackjack':'標準牌公平洗牌；副數影響自然機率。副數變更後，下一局建立新牌靴。返還率依玩家決策而異。',
 'baccarat':'標準牌公平洗牌、每局重洗，依標準補牌規則。副數影響自然機率，和局退本金不加倍。',
 'slot':'三軸獨立使用相同權重。總返還含本金；前兩格相同與三連線不疊加。',
 'roulette':'抽中號碼的機率＝該號碼權重／全部權重。0 不命中紅黑、單雙、大小、打或列。',
 'dice':'三顆骰子獨立使用相同權重。大小、單雙遇豹子皆輸；其餘依各自押法派彩。',
 'mines':'地雷等機率分布，最多翻 5 格。派彩含本金、向下取整，小額下注實際返還率較低。',
 'tower':'每層四選一，地雷等機率分布。遞增難度的地雷數須逐層不減。派彩向下取整。',
}
SCHEMAS['fishing']=[field('target_bps','命中魚體後派彩基準（%）',100,10000,unit='percent_bp'),field('daily_casts','休閒每日精力',1,100)]
NOTES['fishing']='休閒精力於台灣午夜重置，魚餌消耗1／2／3精力；控制張力收線，失敗會逃脫、成功漁獲自動入帳。共享街機每發1–100點且受共用上限限制；命中魚體後捕獲率＝派彩基準÷含本金總倍率，特殊魚會把連鎖目標計入本次總倍率，落空仍扣點。新設定於下次拋竿／發射生效，已接受的砲彈保留設定快照。'
SCHEMAS['limits']=[field('max_bet','每人每局下注上限（點）',20,1000000)]

def initialize(db):
 db.executescript('''CREATE TABLE IF NOT EXISTS game_settings (
 game_type TEXT PRIMARY KEY,revision INTEGER NOT NULL,params TEXT NOT NULL,updated_by INTEGER,updated_at REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS game_settings_audit (
 id INTEGER PRIMARY KEY,actor_id INTEGER NOT NULL,game_type TEXT NOT NULL,revision INTEGER NOT NULL,
 previous_params TEXT NOT NULL,params TEXT NOT NULL,note TEXT NOT NULL,operation_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL,created_at REAL NOT NULL,UNIQUE(actor_id,operation_id));''')
 for game,params in DEFAULTS.items():db.execute('INSERT OR IGNORE INTO game_settings VALUES(?,1,?,NULL,0)',(game,encode(params)))
 # One-time schema extension: preserve customized payouts; old hands keep their snapshot.
 row=db.execute("SELECT params FROM game_settings WHERE game_type='inbetween'").fetchone()
 if row and 'post_protection_bps' not in (old:=json.loads(row[0])):
  db.execute("UPDATE game_settings SET params=?,revision=revision+1 WHERE game_type='inbetween' AND params=?",(encode({**old,'post_protection_bps':5000}),row[0]))

def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def default(game):
 value={'game_type':game,'revision':0,'params':deepcopy(DEFAULTS[game])}
 if game!='limits':value.update(bet_limit=DEFAULTS['limits']['max_bet'],bet_limit_revision=0)
 return value
def current(db,game):
 row=db.execute('SELECT revision,params FROM game_settings WHERE game_type=?',(game,)).fetchone()
 value={'game_type':game,'revision':row[0],'params':json.loads(row[1])} if row else default(game)
 if game!='limits':
  limits=current(db,'limits');value.update(bet_limit=limits['params']['max_bet'],bet_limit_revision=limits['revision'])
 return value

def bet_limit(snapshot=None):
 # Missing metadata belongs to a hand dealt before configurable limits existed.
 return snapshot.get('bet_limit',1000) if snapshot is not None else DEFAULTS['limits']['max_bet']

def room_bet_limit(room):
 return bet_limit(room['hand'].get('game_settings',{})) if room.get('status')=='playing' else bet_limit(room.get('next_game_settings'))

def fund_bet_limit(room,snapshot):
 """Fund virtual house reserves only when the configured ceiling reaches a new high.

 This never moves player/wallet points or changes outcomes, and is called only
 between hands in the same transaction as opening/starting a table.
 """
 if room.get('status')!='waiting':return
 kind=room.get('game_type','holdem');limit=bet_limit(snapshot)
 if kind in ('holdem','mahjong','big2') or limit<=room.get('bet_limit_funded',1000):return
 p=snapshot['params'];cap=room.get('capacity',6)
 if kind=='roulette':multiple=Fraction(max(p[k] for k in ('number_bp','even_bp','group_bp')),10000)+1
 elif kind=='dice':multiple=max(p['even'],*p['faces'],*p['totals'],p['any_triple'],p['triple'])+1
 elif kind=='blackjack':multiple=Fraction(max(p['blackjack_bp'],8*p['win_bp'],4*p['five_card_bp']),10000)+1
 elif kind=='baccarat':multiple=Fraction(max(p[k] for k in ('player_bp','banker_bp','tie_bp')),10000)+1
 elif kind=='slot':multiple=max(*p['triples'],p['pair'])
 elif kind in ('tower','mines'):
  import bonus_engine
  multiple=max(Fraction(bonus_engine.risk_return(kind,limit,5 if kind=='mines' else 6,mode=m,settings=p),limit) for m in ('fixed','progressive'))
 else:multiple=500
 reserve=max(1000000,(limit*multiple*cap).__ceil__())
 room['bank']=max(room['bank'],reserve);room['bet_limit_funded']=limit
def params(hand,game):return hand.get('game_settings',{}).get('params',DEFAULTS[game])

def validate(game,value):
 if not isinstance(game,str) or game not in SCHEMAS or game=='holdem':raise RuleError('這個遊戲沒有可調整的莊家參數。')
 if not isinstance(value,dict) or set(value)!=set(DEFAULTS[game]):raise RuleError('設定欄位不完整或包含未知欄位。')
 for f in SCHEMAS[game]:
  data=value[f['key']];items=data if f['labels'] else [data]
  if not isinstance(items,list) or f['labels'] and len(items)!=len(f['labels']):raise RuleError(f"{f['label']}數量不符。")
  if any(type(x) is not int or not f['min']<=x<=f['max'] for x in items):raise RuleError(f"{f['label']}必須在允許範圍內，且需為整數設定單位。")
  if f['key']=='weights' and sum(items)==0:raise RuleError('至少一個抽樣權重必須大於 0。')
 if game=='tower' and value['progressive_bombs']!=sorted(value['progressive_bombs']):raise RuleError('遞增難度的地雷數不可逐層減少。')
 return deepcopy(value)

def weighted(weights):
 if len(set(weights))==1:return secrets.randbelow(len(weights))
 draw=secrets.randbelow(sum(weights))
 for i,w in enumerate(weights):
  if draw<w:return i
  draw-=w
 raise AssertionError('Invalid weights')

def net_return(stake,bp):return stake+stake*bp//10000
RED={1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
def roulette_win(kind,n):
 if kind.startswith('number:'):return n==int(kind.split(':')[1])
 if n==0:return False
 if kind in ('red','black'):return (n in RED)==(kind=='red')
 if kind in ('odd','even'):return n%2==(kind=='odd')
 if kind in ('low','high'):return (n<=18)==(kind=='low')
 if kind.startswith('dozen'):return (n-1)//12==int(kind[-1])-1
 return (n-1)%3==int(kind[-1])-1
def roulette_bp(p,kind):return p['number_bp'] if kind.startswith('number') else p['group_bp'] if kind.startswith(('dozen','column')) else p['even_bp']

@lru_cache(maxsize=64)
def _metrics(game,encoded):
 p=json.loads(encoded)
 if game=='limits':return {'max_bet':p['max_bet']}
 if game=='slot':
  w=p['weights'];total=sum(w);pay=Fraction(0)
  for a,b,c in product(range(6),repeat=3):
   multiplier=p['triples'][a] if a==b==c else p['pair'] if a==b else 0
   pay+=Fraction(w[a]*w[b]*w[c]*multiplier,total**3)
  return {'rtp_percent':float(pay*100),'rtp_exact':str(pay),'hit_percent':100*sum(x*x for x in w)/total**2}
 if game=='roulette':
  total=sum(p['weights']);rates={}
  for kind in ['red','black','odd','even','low','high',*[f'dozen{i}' for i in range(1,4)],*[f'column{i}' for i in range(1,4)],*[f'number:{i}' for i in range(37)]]:
   probability=Fraction(sum(w for n,w in enumerate(p['weights']) if roulette_win(kind,n)),total)
   rates[kind]={'win_percent':float(probability*100),'rtp_percent':float(probability*(1+Fraction(roulette_bp(p,kind),10000))*100)}
  return {'bets':rates,'rounding_note':'小額派彩向下取整，實際返還率可能較低。'}
 if game=='dice':
  import bonus_engine
  total=sum(p['weights']);rates={};keys=['small','big','odd','even','any_triple',*[f'number:{i}' for i in range(1,7)],*[f'total:{i}' for i in range(4,18)],*[f'triple:{i}' for i in range(1,7)]]
  outcomes=[(list(d),p['weights'][d[0]-1]*p['weights'][d[1]-1]*p['weights'][d[2]-1]) for d in product(range(1,7),repeat=3)]
  for key in keys:
   returned=hits=0
   for d,w in outcomes:
    multiplier=bonus_engine.dice_multiplier(d,key,p);returned+=w*multiplier;hits+=w*(multiplier>0)
   rates[key]={'win_percent':100*hits/total**3,'rtp_percent':100*returned/total**3}
  return {'bets':rates}
 if game=='fishing':return {'hit_return_basis_percent':p['target_bps']/100}
 if game=='inbetween':return {'target_percent':p['target_bps']/100,'post_protection_percent':p.get('post_protection_bps',0)/100}
 if game in ('tower','mines'):return {'target_percent':p['target_bps']/100}
 return {}
def metrics(game,p):return deepcopy(_metrics(game,encode(p)))
def public(snapshot):return {**snapshot,'metrics':metrics(snapshot['game_type'],snapshot['params'])}

def admin_view(db,actor):
 import club_admin
 club_admin.require(db,actor['id'])
 games=[{'name':NAMES[g],'note':NOTES[g],'fields':SCHEMAS[g],'defaults':deepcopy(DEFAULTS[g]),**public(current(db,g))} for g in DEFAULTS]
 history=[dict(r) for r in db.execute('SELECT a.id,a.game_type,a.revision,a.note,a.previous_params,a.params,a.created_at,u.username AS actor FROM game_settings_audit a JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 30')]
 return {'games':games,'history':history}

def update(db,actor,data,clock):
 import club_admin
 club_admin.require(db,actor['id'])
 game=data.get('game_type');value=validate(game,data.get('params'));op=data.get('operation_id');note=data.get('note');revision=data.get('revision')
 if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',op):raise RuleError('設定操作編號無效。')
 if not isinstance(note,str) or not 1<=len(note.strip())<=200:raise RuleError('請填寫 1–200 字的變更原因。')
 if type(revision) is not int or revision<1:raise RuleError('設定版本無效。')
 note=note.strip();fingerprint=hashlib.sha256(encode([game,value,note,revision]).encode()).hexdigest()
 previous=db.execute('SELECT fingerprint,revision,params FROM game_settings_audit WHERE actor_id=? AND operation_id=?',(actor['id'],op)).fetchone()
 if previous:
  if previous[0]!=fingerprint:raise club_admin.AdminError('同一操作編號已用於其他設定。',409,'operation_conflict')
  return {'ok':True,'replayed':True,'saved_revision':previous[1],'current':public(current(db,game))}
 old=current(db,game)
 if old['revision']!=revision:raise club_admin.AdminError('設定已由其他管理員更新，請重新讀取後再修改。',409,'settings_conflict')
 new_revision=revision+1
 db.execute('UPDATE game_settings SET revision=?,params=?,updated_by=?,updated_at=? WHERE game_type=? AND revision=?',(new_revision,encode(value),actor['id'],clock,game,revision))
 db.execute('INSERT INTO game_settings_audit(actor_id,game_type,revision,previous_params,params,note,operation_id,fingerprint,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(actor['id'],game,new_revision,encode(old['params']),encode(value),note,op,fingerprint,clock))
 return {'ok':True,'replayed':False,'saved_revision':new_revision,'current':public(current(db,game))}
