"""Daily missions and fixed-price cosmetic collection. No random paid drops."""
from datetime import datetime
import wallet
import result_stats
from poker_engine import RuleError

ITEMS = {
 'frame_brass':dict(name='黃銅徽章',slot='frame',cost=300,style='brass'),
 'frame_ruby':dict(name='紅寶石光環',slot='frame',cost=600,style='ruby'),
 'title_night':dict(name='深夜常客',slot='title',cost=200,style='night'),
 'title_ace':dict(name='王牌收藏家',slot='title',cost=500,style='ace'),
 'back_crimson':dict(name='緋紅牌背',slot='back',cost=400,style='crimson'),
 'back_jade':dict(name='墨玉牌背',slot='back',cost=400,style='jade'),
 'effect_spark':dict(name='流金星芒',slot='effect',cost=600,style='spark'),
 'effect_aurora':dict(name='霓虹極光',slot='effect',cost=800,style='aurora'),
 'effect_orbit':dict(name='星軌引擎',slot='effect',cost=900,style='orbit'),
 'effect_inferno':dict(name='赤焰核心',slot='effect',cost=1000,style='inferno'),
 'effect_frost':dict(name='極寒結晶',slot='effect',cost=900,style='frost'),
 'effect_crown':dict(name='王者聖域',slot='effect',cost=1200,style='crown'),
 'title_sovereign':dict(name='夜幕主宰',slot='title',cost=700,style='sovereign'),
 'title_legend':dict(name='全桌焦點',slot='title',cost=800,style='legend'),
}
MISSIONS = {'play3':dict(name='完成 3 局',target=3,reward=150), 'variety':dict(name='體驗 2 種遊戲',target=2,reward=100), 'win1':dict(name='完成 1 局正獲利',target=1,reward=100)}

def initialize(db):
    db.executescript('''
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
    return dict(day=today,missions=[dict(id=k,**m,progress=min(counts[k],m['target']),claimed=k in claimed) for k,m in MISSIONS.items()],items=[dict(id=k,**v,owned=k in owned,equipped=equipped.get(v['slot'],{}).get('id')==k) for k,v in ITEMS.items()],equipped=equipped,collected=len(owned),leaders=leaders,profit_leaders=profits)

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
    if path not in ('/api/club/buy','/api/club/equip'):raise RuleError('操作不存在。')
    ident=data.get('item_id')
    if not isinstance(ident,str) or ident not in ITEMS:raise RuleError('收藏品無效。')
    item=ITEMS[ident]
    owned=db.execute('SELECT 1 FROM cosmetic_items WHERE user_id=? AND item_id=?',(uid,ident)).fetchone()
    if path=='/api/club/buy':
        if not owned:
            wallet.transfer(db,uid,-item['cost'],'cosmetic','cosmetic:'+ident,clock)
            db.execute('INSERT INTO cosmetic_items VALUES(?,?,?)',(uid,ident,clock))
        return {'ok':True,'message':'已加入收藏，可按套用。'}
    if not owned:raise RuleError('尚未擁有這件收藏品。')
    if data.get('remove') is True:db.execute('DELETE FROM cosmetic_equipped WHERE user_id=? AND slot=?',(uid,item['slot']))
    else:db.execute('INSERT INTO cosmetic_equipped VALUES(?,?,?) ON CONFLICT(user_id,slot) DO UPDATE SET item_id=excluded.item_id',(uid,item['slot'],ident))
    return {'ok':True,'message':'外觀已更新。'}
