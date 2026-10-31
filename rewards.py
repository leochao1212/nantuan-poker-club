"""Daily missions and fixed-price cosmetic collection. No random paid drops."""
from datetime import datetime
import sqlite3
import wallet
import result_stats
from poker_engine import RuleError

ITEMS = {
 'frame_brass':dict(name='黃銅徽章',slot='frame',cost=300,style='brass'),
 'frame_ruby':dict(name='紅寶石光環',slot='frame',cost=600,style='ruby'),
 'title_night':dict(name='深夜常客',slot='title',cost=8000,style='night',hourly_bps=100),
 'title_ace':dict(name='王牌收藏家',slot='title',cost=20000,style='ace',daily_bps=25),
 'back_crimson':dict(name='緋紅牌背',slot='back',cost=400,style='crimson'),
 'back_jade':dict(name='墨玉牌背',slot='back',cost=400,style='jade'),
 'effect_spark':dict(name='流金星芒',slot='effect',cost=600,style='spark'),
 'effect_aurora':dict(name='霓虹極光',slot='effect',cost=800,style='aurora'),
 'effect_orbit':dict(name='星軌引擎',slot='effect',cost=900,style='orbit'),
 'effect_inferno':dict(name='赤焰核心',slot='effect',cost=1000,style='inferno'),
 'effect_frost':dict(name='極寒結晶',slot='effect',cost=900,style='frost'),
 'effect_crown':dict(name='王者聖域',slot='effect',cost=1200,style='crown'),
 'title_sovereign':dict(name='夜幕主宰',slot='title',cost=60000,style='sovereign',daily_bps=50),
 'title_legend':dict(name='全桌焦點',slot='title',cost=120000,style='legend',daily_bps=75,hourly_bps=100),
}
# Single equipped title only. Basis points keep authoritative supply amounts integral.
ITEMS.update({
 'title_curator':dict(name='楠團鑑藏家',slot='title',cost=25000,style='ace',hourly_bps=200),
 'title_patron':dict(name='鎏金贊助人',slot='title',cost=80000,style='sovereign',daily_bps=75,hourly_bps=200),
 'title_architect':dict(name='翡翠築夢師',slot='title',cost=180000,style='legend',daily_bps=100,hourly_bps=400),
 'title_mogul':dict(name='黑金大亨',slot='title',cost=350000,style='sovereign',daily_bps=125,hourly_bps=600),
 'title_celestial':dict(name='星穹領主',slot='title',cost=750000,style='legend',daily_bps=150,hourly_bps=800),
 'title_treasury':dict(name='楠團典藏王',slot='title',cost=1500000,style='sovereign',daily_bps=200,hourly_bps=1000),
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
    daily=(0,25,50)[tier-1];hourly=(100,200,300)[tier-1]
    name=(f'{game_name}新秀',f'{game_name}熟手',title)[tier-1]
    MILESTONES[key]=dict(game=game,target=target,title_id=ident,tier=tier)
    ITEMS[ident]=dict(name=name,slot='title',cost=None,style=('night','ace','legend')[tier-1],
                     source='milestone',milestone_id=key,daily_bps=daily,hourly_bps=hourly)


# Only the equipped title at deal time applies. All titles share one daily cap.
GAME_PERKS = {
 'holdem':('play','有效參局'), 'big2':('play','有效參局'), 'mahjong':('play','有效參局'),
 'blackjack':('win','贏局加碼'), 'baccarat':('win','贏局加碼'),
 'roulette':('loss','落敗回饋'), 'dice':('loss','落敗回饋'),
 'slot':('win','贏局加碼'), 'mines':('win','探險獲利加碼'),
 'tower':('win','登塔獲利加碼'), 'inbetween':('win','射中加碼')}
for key, milestone in MILESTONES.items():
    item=ITEMS[milestone['title_id']];tier=milestone['tier'];game=milestone['game'];mode,label=GAME_PERKS[game]
    item['game_perk']=dict(game=game,mode=mode,bps=(150,250,400)[tier-1],per_hand=(40,75,125)[tier-1])
    item['game_label']=f"{GAMES[game][0]}{label} +{item['game_perk']['bps']/100:g}% · 每局最多 {item['game_perk']['per_hand']} 點"
for ident,item in ITEMS.items():
    if item['slot']=='title' and item.get('source')!='milestone':
        bps=75 if item['cost']<80000 else 125 if item['cost']<350000 else 175 if item['cost']<1500000 else 250
        item['game_perk']=dict(game='all',mode='win',bps=bps,per_hand=125)
        item['game_label']=f"全遊戲贏局加碼 +{bps/100:g}% · 每局最多 125 點"

def game_perk(db,uid):
    row=db.execute("SELECT e.item_id FROM cosmetic_equipped e JOIN cosmetic_items o ON o.user_id=e.user_id AND o.item_id=e.item_id WHERE e.user_id=? AND e.slot='title'",(uid,)).fetchone()
    return dict(ITEMS.get(row[0],{}).get('game_perk',{}),title_id=row[0]) if row else {}


def bonus_label(item):
    parts=[]
    if item.get('game_label'):parts.append(item['game_label'])
    if item.get('daily_bps'):parts.append(f"每日補給 +{item['daily_bps']/100:g}%")
    if item.get('hourly_bps'):parts.append(f"每小時補給 +{item['hourly_bps']/100:g}%")
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
    return dict(daily_bps=min(200,item.get('daily_bps',0)),hourly_bps=min(1000,item.get('hourly_bps',0)),
                title_id=row[0] if row else None,name=item.get('name'),label=item.get('bonus_label',''))


def milestone_view(db,uid,owned):
    import view_cache
    counts=view_cache.shared(db,('milestone_counts',uid),('poker_results','poker_hands'),lambda:result_stats.game_counts(db,uid))
    return [dict(game=game,name=spec[0],count=counts.get(game,0),tiers=[dict(id=key,**m,title=dict(ITEMS[m['title_id']]),
             progress=min(counts.get(game,0),m['target']),claimed=m['title_id'] in owned) for key,m in MILESTONES.items() if m['game']==game]) for game,spec in GAMES.items()]


MISSIONS = {'play3':dict(name='完成 3 局',target=3,reward=500), 'variety':dict(name='體驗 2 種遊戲',target=2,reward=300), 'win1':dict(name='完成 1 局正獲利',target=1,reward=200)}

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
    if set(MISSIONS)<=claimed:
        counts['complete']=1
    leaders,profits=public_leaders(db)
    import member_accounts
    profiles=member_accounts.public_profiles(db) if profiles is None else profiles
    for person in leaders+profits:person.update(cosmetics=appearances.get(person['id'],{}),**profiles.get(person['id'],{}))
    return dict(day=today,missions=[dict(id=k,**m,progress=min(counts.get(k,0),m['target']),claimed=k in claimed) for k,m in (MISSIONS|{'complete':dict(name='今日任務全完成',target=1,reward=500)}).items()],items=[dict(id=k,**v,owned=k in owned,equipped=equipped.get(v['slot'],{}).get('id')==k) for k,v in ITEMS.items() if v['source']=='shop' or k in owned],total_items=len(ITEMS),milestones=milestone_view(db,uid,owned),title_bonus=equipped_bonus(db,uid),equipped=equipped,collected=len(owned),leaders=leaders,profit_leaders=profits)

def mutate(db,path,data,user,clock):
    uid=user['id']
    if not wallet.active(db):raise RuleError('點數制度尚未啟用。')
    if path=='/api/club/claim-all':return claim_all(db,user,data,clock)
    if path=='/api/club/mission':
        ident=data.get('mission_id')
        if not isinstance(ident,str) or ident not in (*MISSIONS,'complete'):raise RuleError('任務無效。')
        mission=MISSIONS.get(ident,dict(target=1,reward=500));today=wallet.day(clock)
        if db.execute('SELECT 1 FROM mission_claims WHERE user_id=? AND day=? AND mission_id=?',(uid,today,ident)).fetchone():return {'ok':True,'message':'今天已領取這個任務。'}
        if ident=='complete':
            claimed={r[0] for r in db.execute('SELECT mission_id FROM mission_claims WHERE user_id=? AND day=?',(uid,today))}
            if not set(MISSIONS)<=claimed:raise RuleError('請先領完三項今日任務。')
        elif progress(db,uid,clock)[ident]<mission['target']:raise RuleError('任務尚未完成。')
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
    if data.get('remove') is True:db.execute('DELETE FROM cosmetic_equipped WHERE user_id=? AND slot=?',(uid,item['slot']))
    else:db.execute('INSERT INTO cosmetic_equipped VALUES(?,?,?) ON CONFLICT(user_id,slot) DO UPDATE SET item_id=excluded.item_id',(uid,item['slot'],ident))
    return {'ok':True,'message':'外觀已更新。'}


def claim_all(db,user,data,clock):
    """One transactional receipt; existing eligibility, caps and debt rules apply.

    Called through online.mutate, whose operation receipt makes retries safe even
    across midnight or after a new hourly reward becomes available.
    """
    import clubhouse,hashlib
    uid=user['id'];op=data['operation_id'];rows=[]
    sub=lambda name:hashlib.sha256(('reward-hub:'+op+':'+name).encode()).hexdigest()
    wallet.create(db,uid,clock)
    before=db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()[0]
    db.execute('SAVEPOINT reward_hub')
    try:
        for name,result in [('每日補給',wallet.claim(db,uid,clock)),('每小時補給',wallet.claim_hourly(db,uid,clock,sub('hourly')))]:
            if result.get('claimed'):rows.append(dict(name=name,amount=result['amount']))
        for ident in (*MISSIONS,'complete'):
            today=wallet.day(clock)
            claimed={r[0] for r in db.execute('SELECT mission_id FROM mission_claims WHERE user_id=? AND day=?',(uid,today))}
            eligible=set(MISSIONS)<=claimed if ident=='complete' else progress(db,uid,clock)[ident]>=MISSIONS[ident]['target']
            if ident not in claimed and eligible:
                mutate(db,'/api/club/mission',dict(mission_id=ident),user,clock)
                mission=MISSIONS.get(ident,dict(name='今日任務全完成',reward=500))
                rows.append(dict(name=mission['name'],amount=mission['reward']))
        for name,result in [('會所收益',clubhouse.claim(db,user,dict(operation_id=sub('income')),clock)),('員工派遣',clubhouse.staff_mutate(db,user,'collect_all',dict(operation_id=sub('staff')),clock))]:
            if result.get('amount',0):rows.append(dict(name=name,amount=result['amount']))
        owned={r[0] for r in db.execute('SELECT item_id FROM cosmetic_items WHERE user_id=?',(uid,))}
        for group in milestone_view(db,uid,owned):
            for tier in group['tiers']:
                if not tier['claimed'] and tier['progress']>=tier['target']:
                    mutate(db,'/api/club/milestone',dict(milestone_id=tier['id']),user,clock)
                    rows.append(dict(name=tier['title']['name'],amount=0,title_id=tier['title_id']))
        total=sum(r['amount'] for r in rows)
        after=db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()[0]
        result=dict(ok=True,receipt=dict(rows=rows,gross=total,net=after-before,repaid=total-(after-before)),message=f'已領取 {len(rows)} 項獎勵。' if rows else '目前沒有待領獎勵，去玩一局吧。')
        db.execute('RELEASE SAVEPOINT reward_hub')
        return result
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT reward_hub');db.execute('RELEASE SAVEPOINT reward_hub');raise
