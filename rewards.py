"""Daily missions and fixed-price cosmetic collection. No random paid drops."""
from datetime import datetime
import sqlite3
import clubhouse
import wallet
import result_stats
from poker_engine import RuleError

ITEMS = {
 'frame_brass':dict(name='黃銅徽章',slot='frame',cost=300,style='brass'),
 'frame_ruby':dict(name='紅寶石光環',slot='frame',cost=600,style='ruby'),
 'title_night':dict(name='深夜常客',slot='title',cost=8000,style='night',storage_bps=100),
 'title_ace':dict(name='王牌收藏家',slot='title',cost=20000,style='ace',production_bps=25),
 'back_crimson':dict(name='緋紅牌背',slot='back',cost=400,style='crimson'),
 'back_jade':dict(name='墨玉牌背',slot='back',cost=400,style='jade'),
 'effect_spark':dict(name='流金星芒',slot='effect',cost=600,style='spark'),
 'effect_aurora':dict(name='霓虹極光',slot='effect',cost=800,style='aurora'),
 'effect_orbit':dict(name='星軌引擎',slot='effect',cost=900,style='orbit'),
 'effect_inferno':dict(name='赤焰核心',slot='effect',cost=1000,style='inferno'),
 'effect_frost':dict(name='極寒結晶',slot='effect',cost=900,style='frost'),
 'effect_crown':dict(name='王者聖域',slot='effect',cost=1200,style='crown'),
 'title_sovereign':dict(name='夜幕主宰',slot='title',cost=60000,style='sovereign',production_bps=50),
 'title_legend':dict(name='全桌焦點',slot='title',cost=120000,style='legend',production_bps=75,storage_bps=100),
}
# Single equipped title only. Basis points keep all authoritative accrual integral.
ITEMS.update({
 'title_curator':dict(name='楠團鑑藏家',slot='title',cost=25000,style='ace',storage_bps=200),
 'title_patron':dict(name='鎏金贊助人',slot='title',cost=80000,style='sovereign',production_bps=75,storage_bps=200),
 'title_architect':dict(name='翡翠築夢師',slot='title',cost=180000,style='legend',production_bps=100,storage_bps=400),
 'title_mogul':dict(name='黑金大亨',slot='title',cost=350000,style='sovereign',production_bps=125,storage_bps=600),
 'title_celestial':dict(name='星穹領主',slot='title',cost=750000,style='legend',production_bps=150,storage_bps=800),
 'title_treasury':dict(name='楠團典藏王',slot='title',cost=1500000,style='sovereign',production_bps=200,storage_bps=1000),
})
GAMES={
 'holdem':('德州撲克','讀牌者',(50,250,1000)),
 'big2':('大老二','壓軸王',(50,250,1000)),
 'blackjack':('21 點','二十一使者',(100,1000,10000)),
 'roulette':('歐式輪盤','輪盤領航員',(100,1000,10000)),
 'baccarat':('百家樂','牌靴觀察家',(100,1000,10000)),
 'slot':('拉霸','萬轉傳奇',(100,1000,10000)),
 'mines':('尋寶礦區','礦脈探索家',(100,1000,10000)),
 'tower':('爬塔','登塔先鋒',(100,1000,10000)),
 'dice':('Dice 骰寶','骰界行者',(100,1000,10000)),
 'inbetween':('射龍門','龍門守望者',(100,1000,10000)),
 'mahjong':('台灣麻將','方城名宿',(20,100,500)),
}
MILESTONES={}
for game,(game_name,title,targets) in GAMES.items():
 for tier,target in enumerate(targets,1):
    key=f'{game}_{target}';ident='title_ms_'+key
    production=(0,25,50)[tier-1];storage=(100,200,300)[tier-1]
    name=(f'{game_name}新秀',f'{game_name}熟手',title)[tier-1]
    MILESTONES[key]=dict(game=game,target=target,title_id=ident,tier=tier)
    ITEMS[ident]=dict(name=name,slot='title',cost=None,style=('night','ace','legend')[tier-1],
                     source='milestone',milestone_id=key,production_bps=production,storage_bps=storage)


def bonus_label(item):
    parts=[]
    if item.get('production_bps'):parts.append(f"會所產速 +{item['production_bps']/100:g}%")
    if item.get('storage_bps'):parts.append(f"收益容量 +{item['storage_bps']/100:g}%")
    return ' · '.join(parts)


for item in ITEMS.values():
    item.setdefault('source','shop');item['bonus_label']=bonus_label(item)


def equipped_bonus(db,uid):
    try:
        row=db.execute("SELECT e.item_id FROM cosmetic_equipped e JOIN cosmetic_items o ON o.user_id=e.user_id AND o.item_id=e.item_id WHERE e.user_id=? AND e.slot='title'",(uid,)).fetchone()
    except sqlite3.OperationalError as ex:
        if 'no such table' not in str(ex):raise
        row=None
    item=ITEMS.get(row[0],{}) if row else {}
    return dict(production_bps=min(200,item.get('production_bps',0)),storage_bps=min(1000,item.get('storage_bps',0)),
                title_id=row[0] if row else None,name=item.get('name'),label=item.get('bonus_label',''))


def milestone_view(db,uid,owned):
    import view_cache
    counts=view_cache.shared(db,('milestone_counts',uid),('poker_results','poker_hands'),lambda:result_stats.game_counts(db,uid))
    return [dict(game=game,name=spec[0],count=counts.get(game,0),tiers=[dict(id=key,**m,title=dict(ITEMS[m['title_id']]),
             progress=min(counts.get(game,0),m['target']),claimed=m['title_id'] in owned) for key,m in MILESTONES.items() if m['game']==game]) for game,spec in GAMES.items()]


MISSIONS = {'play3':dict(name='完成 3 局',target=3,reward=150), 'variety':dict(name='體驗 2 種遊戲',target=2,reward=100), 'win1':dict(name='完成 1 局正獲利',target=1,reward=100)}

def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS milestone_claims(user_id INTEGER NOT NULL REFERENCES users(id),milestone_id TEXT NOT NULL,claimed_at REAL NOT NULL,PRIMARY KEY(user_id,milestone_id));
    CREATE INDEX IF NOT EXISTS poker_results_user ON poker_results(user_id,hand_id);
    CREATE INDEX IF NOT EXISTS poker_hands_finished ON poker_hands(finished_at);
    CREATE TABLE IF NOT EXISTS cosmetic_items(user_id INTEGER NOT NULL REFERENCES users(id),item_id TEXT NOT NULL,acquired_at REAL NOT NULL,PRIMARY KEY(user_id,item_id));
    CREATE TABLE IF NOT EXISTS cosmetic_equipped(user_id INTEGER NOT NULL REFERENCES users(id),slot TEXT NOT NULL,item_id TEXT NOT NULL,PRIMARY KEY(user_id,slot));
    CREATE TABLE IF NOT EXISTS mission_claims(user_id INTEGER NOT NULL REFERENCES users(id),day TEXT NOT NULL,mission_id TEXT NOT NULL,reward INTEGER NOT NULL,claimed_at REAL NOT NULL,PRIMARY KEY(user_id,day,mission_id));
    ''')
    result_stats.initialize(db)

def _progress(db,uid,clock):
    start=datetime.fromisoformat(wallet.day(clock)).replace(tzinfo=wallet.TAIPEI).timestamp()
    return result_stats.progress(db,uid,start)

def progress(db,uid,clock):
    import view_cache
    # These are counts derived from settled public hands, never live cards.
    return view_cache.shared(db,('mission_progress',uid,wallet.day(clock)),('poker_hands','poker_results'),lambda:_progress(db,uid,clock))


def profile_map(db):
    import view_cache
    def build():
        result={}
        for row in db.execute('SELECT user_id,slot,item_id FROM cosmetic_equipped'):
            if row[2] in ITEMS:
                result.setdefault(row[0],{})[row[1]]=dict(id=row[2],**ITEMS[row[2]])
        return result
    return view_cache.shared(db,'cosmetics',('cosmetic_equipped',),build)


def public_leaders(db):
    import view_cache
    def build():
        leaders=[dict(r) for r in db.execute("SELECT u.id,u.nickname,count(c.item_id) AS collected FROM users u LEFT JOIN cosmetic_items c ON c.user_id=u.id WHERE u.id NOT IN (SELECT user_id FROM account_states WHERE status!='active') GROUP BY u.id ORDER BY collected DESC,u.id LIMIT 20")]
        profits=[dict(r) for r in db.execute("SELECT u.id,u.nickname,COALESCE(r.profit,0) AS profit FROM users u LEFT JOIN player_result_totals r ON r.user_id=u.id WHERE u.id NOT IN (SELECT user_id FROM account_states WHERE status!='active') ORDER BY profit DESC,u.id LIMIT 20")]
        return leaders,profits
    return view_cache.shared(db,'leaders',('users','cosmetic_items','poker_results','account_states'),build)


def view(db,uid,clock,*,profiles=None,appearances=None):
    counts=progress(db,uid,clock);today=wallet.day(clock)
    claimed={r[0] for r in db.execute('SELECT mission_id FROM mission_claims WHERE user_id=? AND day=?',(uid,today))}
    owned={r[0] for r in db.execute('SELECT item_id FROM cosmetic_items WHERE user_id=?',(uid,))}
    appearances=profile_map(db) if appearances is None else appearances
    equipped=appearances.get(uid,{})
    leaders,profits=public_leaders(db)
    import member_accounts
    profiles=member_accounts.public_profiles(db) if profiles is None else profiles
    for person in leaders+profits:person.update(cosmetics=appearances.get(person['id'],{}),**profiles.get(person['id'],{}))
    return dict(day=today,missions=[dict(id=k,**m,progress=min(counts[k],m['target']),claimed=k in claimed) for k,m in MISSIONS.items()],items=[dict(id=k,**v,owned=k in owned,equipped=equipped.get(v['slot'],{}).get('id')==k) for k,v in ITEMS.items() if v['source']=='shop' or k in owned],total_items=len(ITEMS),milestones=milestone_view(db,uid,owned),title_bonus=equipped_bonus(db,uid),equipped=equipped,collected=len(owned),leaders=leaders,profit_leaders=profits)

def mutate(db,path,data,user,clock):
    uid=user['id']
    if not wallet.active(db):raise RuleError('點數制度尚未啟用。')
    if path=='/api/club/mission':
        ident=data.get('mission_id')
        if not isinstance(ident,str) or ident not in MISSIONS:raise RuleError('任務無效。')
        mission=MISSIONS[ident];today=wallet.day(clock)
        if db.execute('SELECT 1 FROM mission_claims WHERE user_id=? AND day=? AND mission_id=?',(uid,today,ident)).fetchone():return {'ok':True,'message':'今天已領取這個任務。'}
        if progress(db,uid,clock)[ident]<mission['target']:raise RuleError('任務尚未完成。')
        db.execute('INSERT INTO mission_claims VALUES(?,?,?,?,?)',(uid,today,ident,mission['reward'],clock))
        wallet.transfer(db,uid,mission['reward'],'mission','mission:'+today+':'+ident,clock)
        return {'ok':True,'message':f"已領取 {mission['reward']} 點任務獎勵。"}
    if path=='/api/club/milestone':
        key=data.get('milestone_id')
        if not isinstance(key,str) or key not in MILESTONES:raise RuleError('里程碑無效。')
        milestone=MILESTONES[key];ident=milestone['title_id']
        if db.execute('SELECT 1 FROM cosmetic_items WHERE user_id=? AND item_id=?',(uid,ident)).fetchone():return dict(ok=True,message='這個里程碑稱號已領取。')
        if result_stats.game_counts(db,uid).get(milestone['game'],0)<milestone['target']:raise RuleError('里程碑尚未達成。')
        db.execute('INSERT INTO cosmetic_items VALUES(?,?,?)',(uid,ident,clock))
        db.execute('INSERT OR IGNORE INTO milestone_claims VALUES(?,?,?)',(uid,key,clock))
        return dict(ok=True,message='已領取「'+ITEMS[ident]['name']+'」，可到收藏中裝備。')
    if path not in ('/api/club/buy','/api/club/equip'):raise RuleError('操作不存在。')
    ident=data.get('item_id')
    if not isinstance(ident,str) or ident not in ITEMS:raise RuleError('收藏品無效。')
    item=ITEMS[ident]
    owned=db.execute('SELECT 1 FROM cosmetic_items WHERE user_id=? AND item_id=?',(uid,ident)).fetchone()
    if path=='/api/club/buy':
        if item['source']!='shop':raise RuleError('此稱號需達成里程碑，不能購買。')
        if not owned:
            quote=data.get('expected_cost')
            if (quote is not None or item['slot']=='title') and (type(quote) is not int or quote!=item['cost']):
                from member_accounts import AccountError
                raise AccountError('收藏售價已更新，請重新整理後再確認。',409,'stale_cosmetic_price')
            wallet.transfer(db,uid,-item['cost'],'cosmetic','cosmetic:'+ident,clock)
            db.execute('INSERT INTO cosmetic_items VALUES(?,?,?)',(uid,ident,clock))
        return {'ok':True,'message':'已加入收藏，可按套用。'}
    if not owned:raise RuleError('尚未擁有這件收藏品。')
    current=db.execute('SELECT item_id FROM cosmetic_equipped WHERE user_id=? AND slot=?',(uid,item['slot'])).fetchone()
    if data.get('remove') is True and (not current or current[0]!=ident):return dict(ok=True,message='此收藏品目前未裝備，未變更其他裝備。')
    if data.get('remove') is not True and current and current[0]==ident:return dict(ok=True,message='目前已裝備此收藏品。')
    if item['slot']=='title':clubhouse.settle_title_change(db,uid,clock)
    if data.get('remove') is True:db.execute('DELETE FROM cosmetic_equipped WHERE user_id=? AND slot=?',(uid,item['slot']))
    else:db.execute('INSERT INTO cosmetic_equipped VALUES(?,?,?) ON CONFLICT(user_id,slot) DO UPDATE SET item_id=excluded.item_id',(uid,item['slot'],ident))
    return {'ok':True,'message':'外觀已更新。'}
