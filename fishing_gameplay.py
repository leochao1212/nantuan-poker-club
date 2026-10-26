"""Authoritative fishing: skill casting and shared arcade ballistics.

All mutations run inside the site's FIFO write transaction. Public paths contain
no future capture tickets. Old immutable receipts and pending v1 casts survive.
"""
import hashlib
import heapq
import json
import math
import re
import secrets
import fishing as base
import game_settings
import member_accounts
import wallet
import fishing_tension
import fishing_power
from poker_engine import RuleError

VERSION = 4
ROOMS = 6
CAPACITY = 4
LEASE = 40
WORLD_WIDTH, WORLD_HEIGHT = 1000, 600
SLOTS = 18
SPEED = 1150
FLIGHT = 1.1
RODS = [
    dict(name='經典黃銅',width=.30,rate=1.,detail='平衡收線'),
    dict(name='翡翠夜航',width=.37,rate=.8,detail='收線區較寬，收線較慢'),
    dict(name='曜金典藏',width=.25,rate=1.25,detail='收線區較窄，收線較快'),
]
CANNONS = [
    dict(name='翠玉追擊',interval=.24,radius=15,detail='平衡射速與捕網'),
    dict(name='紫電連弩',interval=.18,radius=10,detail='快射小網，適合追擊'),
    dict(name='龍焰重炮',interval=.34,radius=27,detail='慢射大網，容易瞄準'),
]
NAMES = ['黃金海灣','龍宮遺跡','人魚寶藏','深海獵場','珊瑚王庭','沉船秘境']


def encode(value):
    return game_settings.encode(value)


def number(value, label, low, high):
    if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high:
        raise RuleError(label+'超出允許範圍。')
    return value


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise RuleError(label+'必須是允許範圍內的整數。')
    return value


def initialize(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(fishing_casts)')}
    for key,schema in [('version','INTEGER NOT NULL DEFAULT 1'),('quota_cost','INTEGER NOT NULL DEFAULT 1'),('data',"TEXT NOT NULL DEFAULT '{}' ")]:
        if key not in columns:db.execute('ALTER TABLE fishing_casts ADD COLUMN '+key+' '+schema)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS fishing_cooldowns(user_id INTEGER PRIMARY KEY,ready_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS fishing_loadouts(user_id INTEGER PRIMARY KEY,rod INTEGER NOT NULL,cannon INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS fishing_rooms(id INTEGER PRIMARY KEY,seed TEXT NOT NULL,last_tick REAL NOT NULL DEFAULT 0,boss_epoch INTEGER NOT NULL DEFAULT -1);
    CREATE TABLE IF NOT EXISTS fishing_members(user_id INTEGER PRIMARY KEY,room_id INTEGER NOT NULL,seat INTEGER NOT NULL,last_seen REAL NOT NULL,skill_at REAL NOT NULL DEFAULT 0,UNIQUE(room_id,seat));
    CREATE INDEX IF NOT EXISTS fishing_member_room ON fishing_members(room_id,last_seen);
    CREATE TABLE IF NOT EXISTS fishing_entities(room_id INTEGER NOT NULL,slot INTEGER NOT NULL,id TEXT NOT NULL UNIQUE,data TEXT NOT NULL,expires_at REAL NOT NULL,PRIMARY KEY(room_id,slot));
    CREATE TABLE IF NOT EXISTS fishing_projectiles(id INTEGER PRIMARY KEY,token TEXT NOT NULL,user_id INTEGER NOT NULL,room_id INTEGER NOT NULL,operation_id TEXT NOT NULL,born_at REAL NOT NULL,checked_at REAL NOT NULL,expires_at REAL NOT NULL,state TEXT NOT NULL,data TEXT NOT NULL,UNIQUE(user_id,token));
    CREATE INDEX IF NOT EXISTS fishing_flying ON fishing_projectiles(state,expires_at);
    CREATE INDEX IF NOT EXISTS fishing_projectile_room ON fishing_projectiles(room_id,born_at);
    CREATE INDEX IF NOT EXISTS fishing_projectile_expiry ON fishing_projectiles(room_id,expires_at);
    CREATE TABLE IF NOT EXISTS fishing_captures(fish_id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,projectile_id INTEGER NOT NULL UNIQUE,gross INTEGER NOT NULL,created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS fishing_effects(id INTEGER PRIMARY KEY,room_id INTEGER NOT NULL,user_id INTEGER NOT NULL,starts_at REAL NOT NULL,ends_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS fishing_effect_room ON fishing_effects(room_id,ends_at);
    ''')
    if 'kind' not in {r[1] for r in db.execute('PRAGMA table_info(fishing_effects)')}:db.execute("ALTER TABLE fishing_effects ADD COLUMN kind TEXT NOT NULL DEFAULT 'freeze'")
    if 'laser_at' not in {r[1] for r in db.execute('PRAGMA table_info(fishing_cooldowns)')}:db.execute('ALTER TABLE fishing_cooldowns ADD COLUMN laser_at REAL NOT NULL DEFAULT 0')
    for rid in range(1,ROOMS+1):db.execute('INSERT OR IGNORE INTO fishing_rooms(id,seed) VALUES(?,?)',(rid,secrets.token_hex(16)))
    members=[dict(r) for r in db.execute('SELECT * FROM fishing_members ORDER BY room_id,seat')]
    if any(m['seat']>=CAPACITY for m in members):
        occupied={(m['room_id'],m['seat']) for m in members if m['seat']<CAPACITY}
        for m in members:
            if m['seat']<CAPACITY:continue
            place=next((pair for pair in [(r,s) for r in range(1,ROOMS+1) for s in range(CAPACITY)] if pair not in occupied),None)
            if place is None:raise RuntimeError('Cannot migrate fishing seats safely')
            occupied.add(place);db.execute('UPDATE fishing_members SET room_id=?,seat=? WHERE user_id=?',(*place,m['user_id']))


def loadout(db,uid):
    row=db.execute('SELECT rod,cannon FROM fishing_loadouts WHERE user_id=?',(uid,)).fetchone()
    return dict(row) if row else {'rod':0,'cannon':0}


def cast_option(power):
    tier=0 if power<334 else 1 if power<667 else 2
    weights=[f['weight']*(100+tier*i*55) for i,f in enumerate(base.FISH)]
    total=sum(weights)
    return {'tier':tier,'cost':tier+1,'label':['近岸','中距','遠投'][tier],
            'weights':weights,'chances':[round(w*100/total,4) for w in weights]}


def fish_y(data,at):
    elapsed=max(0,at-data['hooked_at']);p=data['path']
    return min(.93,max(.07,.5+p['a']*math.sin(elapsed*p['speed']+p['phase'])+p['b']*math.sin(elapsed*p['speed']*2.17+p['phase']*.7)))


def advance_skill(data,clock):
    if data.get('mechanic')=='tension':return fishing_tension.advance(data,clock)
    if data.get('phase')!='playing':return
    # Fixed 50 ms steps make outcomes independent of browser frame rate and polling.
    target=min(clock,data['deadline'])
    while data['sim_at']+.05<=target+1e-7 and data['phase']=='playing':
        at=data['sim_at']+.05;held=data['holding'] and at-data['input_at']<=1.1
        v=max(-.85,min(.85,data['velocity']*.86+(-.125 if held else .105)))
        y=data['zone_y']+v*.05;half=data['width']/2
        if y<half:y=half;v=0
        if y>1-half:y=1-half;v=0
        inside=abs(fish_y(data,at)-y)<=half
        data['progress']=max(0,min(1,data['progress']+(.155*data['rate'] if inside else -.105)*.05))
        data['escape']=max(0,min(1,data['escape']+(-.055 if inside else .145)*.05))
        data.update(sim_at=at,zone_y=y,velocity=v)
        if data['progress']>=1:data.update(phase='caught',finished_at=at)
        elif data['escape']>=1:data.update(phase='escaped',finished_at=at,reason='魚逃出收線區太久')
    if clock>=data['deadline'] and data['phase']=='playing':data.update(phase='escaped',finished_at=data['deadline'],reason='搏魚逾時')


def _finish_cast(db,row,data,clock):
    tension=data.get('mechanic')=='tension' and data['phase']=='caught'
    if tension:fishing_tension.result(data,row['size_cm'],base.BY_ID[row['species']]['value'])
    closed=db.execute('UPDATE fishing_casts SET collected_at=?,data=? WHERE id=? AND collected_at IS NULL',(clock,encode(data),row['id'])).rowcount
    if not closed:return
    if data['phase']=='caught':
        base._collect(db,row['user_id'],row['species'],row['size_cm'],'leisure')
        if tension:
            db.execute('UPDATE fishing_collection SET stored=stored-1 WHERE user_id=? AND species=?',(row['user_id'],row['species']))
            wallet.transfer(db,row['user_id'],data['reward'],'fishing_sale','fish:cast:'+row['id'],clock)


def _tick_cast(db,row,clock):
    data=json.loads(row['data'])
    if data['phase']=='waiting' and clock>data['hook_deadline']:
        data.update(phase='escaped',finished_at=data['hook_deadline'],reason='錯過提竿時機')
    advance_skill(data,clock)
    if data['phase'] in ('caught','escaped'):_finish_cast(db,row,data,clock)
    else:db.execute('UPDATE fishing_casts SET data=? WHERE id=?',(encode(data),row['id']))
    return data


def skill_view(db,uid,clock):
    row=db.execute('SELECT * FROM fishing_casts WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(uid,)).fetchone()
    if not row:return {'pending':None,'last_cast':None,'server_time':clock}
    if row['version']==1:
        pending={'id':row['id'],'version':1,'phase':'legacy','ready_at':row['ready_at']} if row['collected_at'] is None else None
        return {'pending':pending,'last_cast':None,'server_time':clock}
    data=json.loads(row['data'])
    if data['phase']=='waiting' and clock>data['hook_deadline']:data.update(phase='escaped',reason='錯過提竿時機')
    public={k:v for k,v in data.items() if k not in ('private_species',)}
    public.update(id=row['id'],version=VERSION,ready_at=row['ready_at'])
    if data['phase']!='waiting':public.update(species=row['species'],size_cm=row['size_cm'])
    return {'pending':public if data['phase'] in ('waiting','playing') else None,
            'last_cast':public if data['phase'] in ('caught','escaped') else None,'server_time':clock}


def origin(seat):
    return [(175,530),(825,530),(825,70),(175,70)][seat]


def spawn(room,slot,clock,previous=None,boss=False,stagger=False):
    generation=previous.get('generation',0)+1 if previous else 1
    ticket=hashlib.sha256((room['seed']+':'+str(slot//4)+':'+str(generation)).encode()).digest()
    index=[0,1,2,3,4,5,6,7,12,13][ticket[0]%10]
    if boss:index=[8,9,10,11,14,15][(int(clock//120)+room['id'])%6]
    f=base.FISH[index]
    life=24+ticket[1]%13;born=clock-((slot//4)/(SLOTS/4)*life*.78 if stagger else 0)
    direction=1 if ticket[2]%2 else -1
    return dict(id=f"{room['id']}-{slot}-{generation}",slot=slot,generation=generation,species=f['id'],
                spawned_at=born,expires_at=born+life,x0=(-90-(slot%4)*(110 if index<4 else 145)) if direction==1 else (1090+(slot%4)*(110 if index<4 else 145)),
                vx=direction*1180/life,y0=125+ticket[3]/255*250+(slot%4-1.5)*28,amplitude=15+ticket[4]%24,
                frequency=.5+ticket[5]/255*.6,phase=ticket[6]/255*math.tau,
                radius_x=(62 if index>=4 else 45)*(1.5 if boss else 1),radius_y=(31 if index>=4 else 23)*(1.5 if boss else 1),
                multiplier=(f['multiplier']+(ticket[7]%5)*f.get('bonus_step',0)),boss=boss,feature=f.get('feature'),school=slot//4)


def position(fish,clock,effects=()):
    t=max(0,clock-fish['spawned_at'])
    t-=sum(max(0,min(clock,e['ends_at'])-max(fish['spawned_at'],e['starts_at'])) for e in effects if e.get('kind','freeze')=='freeze')
    return fish['x0']+fish['vx']*t,fish['y0']+fish['amplitude']*math.sin(t*fish['frequency']+fish['phase'])


def _put_entity(db,rid,fish):
    db.execute('INSERT INTO fishing_entities VALUES(?,?,?,?,?) ON CONFLICT(room_id,slot) DO UPDATE SET id=excluded.id,data=excluded.data,expires_at=excluded.expires_at',(rid,fish['slot'],fish['id'],encode(fish),fish['expires_at']))


def prepare_room(db,rid,clock):
    room=db.execute('SELECT * FROM fishing_rooms WHERE id=?',(rid,)).fetchone()
    rows={r['slot']:r for r in db.execute('SELECT * FROM fishing_entities WHERE room_id=?',(rid,))}
    for slot in range(SLOTS):
        old=rows.get(slot)
        if old is None or old['expires_at']<clock:
            _put_entity(db,rid,spawn(room,slot,clock,json.loads(old['data']) if old else None,stagger=old is None))
    epoch=int(clock//120)
    if clock%120<25 and room['boss_epoch']!=epoch:
        old=db.execute('SELECT data FROM fishing_entities WHERE room_id=? AND slot=?',(rid,SLOTS-1)).fetchone()
        _put_entity(db,rid,spawn(room,SLOTS-1,clock,json.loads(old[0]),boss=True))
        db.execute('UPDATE fishing_rooms SET boss_epoch=? WHERE id=?',(epoch,rid))


def room_view(db,rid,clock):
    integer(rid,'魚場',1,ROOMS)
    members=[dict(r) for r in db.execute('SELECT m.user_id,m.seat,m.skill_at,u.nickname,COALESCE(l.cannon,0) AS cannon,COALESCE(c.laser_at,0) AS laser_at FROM fishing_members m JOIN users u ON u.id=m.user_id LEFT JOIN fishing_loadouts l ON l.user_id=m.user_id LEFT JOIN fishing_cooldowns c ON c.user_id=m.user_id WHERE m.room_id=? AND m.last_seen>? ORDER BY m.seat',(rid,clock-LEASE))]
    for member in members:member.update(x=origin(member['seat'])[0],y=origin(member['seat'])[1])
    entities=[json.loads(r[0]) for r in db.execute('SELECT data FROM fishing_entities WHERE room_id=? AND expires_at>? ORDER BY slot',(rid,clock))]
    effects=[dict(r) for r in db.execute('SELECT user_id,starts_at,ends_at,kind FROM fishing_effects WHERE room_id=? AND ends_at>?',(rid,clock-45))]
    shots=[]
    for r in db.execute('SELECT * FROM fishing_projectiles WHERE room_id=? AND expires_at>? ORDER BY id DESC LIMIT 120',(rid,clock-2)):
        shot=json.loads(r['data']);shot.update(id=r['id'],token=r['token'],user_id=r['user_id'],born_at=r['born_at'],state=r['state']);shots.append(shot)
    return dict(gameplay_version=VERSION,room_id=rid,name=NAMES[rid-1],capacity=CAPACITY,players=members,
                entities=entities,effects=effects,projectiles=shots,server_time=clock,width=WORLD_WIDTH,height=WORLD_HEIGHT,
                event='巨獸來襲' if any(f['boss'] for f in entities) else '魚群巡游',next_boss_at=(int(clock//120)+1)*120)


def view(db,uid,clock):
    value=base._base_view(db,uid,clock)
    used=db.execute('SELECT COALESCE(sum(quota_cost),0) FROM fishing_casts WHERE user_id=? AND day=?',(uid,wallet.day(clock))).fetchone()[0]
    member=db.execute('SELECT room_id,seat FROM fishing_members WHERE user_id=? AND last_seen>?',(uid,clock-LEASE)).fetchone()
    value.update(gameplay_version=VERSION,**skill_view(db,uid,clock),free_casts=max(0,value['daily_casts']-used),
                 loadout=loadout(db,uid),rods=RODS,cannons=CANNONS,ammo=[a for a in fishing_power.AMMO if a['stake']<=value['max_shot']],
                 cast_options=[cast_option(p) for p in (100,500,900)],member=dict(member) if member else None,
                 rooms=[dict(id=rid,name=NAMES[rid-1],capacity=CAPACITY,players=db.execute('SELECT count(*) FROM fishing_members WHERE room_id=? AND last_seen>?',(rid,clock-LEASE)).fetchone()[0]) for rid in range(1,ROOMS+1)])
    return value


def burst_view(db,uid,clock):
    stats=db.execute('SELECT shots,spent,returned FROM fishing_stats WHERE user_id=?',(uid,)).fetchone()
    return {'partial':True,'wallet':wallet.view(db,uid,clock),'server_time':clock,
            **(dict(stats) if stats else {'shots':0,'spent':0,'returned':0})}


def _first_hit(shot,start,end,entities,effects,dead):
    # 20 ms authoritative sweep, bounded by the projectile's 1.1 s life.
    at=max(start,shot['born_at']);end=min(end,shot['expires_at'])
    while at<=end+1e-8:
        elapsed=at-shot['born_at'];x=shot['x0']+shot['vx']*elapsed;y=shot['y0']+shot['vy']*elapsed
        for f in entities:
            if f['id'] in dead or not f['spawned_at']<=at<f['expires_at']:continue
            fx,fy=position(f,at,effects)
            if ((x-fx)/(f['radius_x']+shot['radius']))**2+((y-fy)/(f['radius_y']+shot['radius']))**2<=1:
                return at,f,x,y
        at+=.02
    return None


def bonus_targets(fish,entities,at,effects,dead):
    feature=fish.get('feature')
    if not feature:return []
    x,y=position(fish,at,effects);limits={'bomb':(330,8),'arms':(450,4),'lightning':(700,5),'dragon':(900,8),'treasure':(650,6),'whale':(900,8)}
    radius,count=limits[feature];candidates=[]
    for other in entities:
        if other['id']==fish['id'] or other['id'] in dead or other.get('feature') or not other['spawned_at']<=at<other['expires_at']:continue
        ox,oy=position(other,at,effects);distance=math.hypot(x-ox,y-oy)
        if distance<=radius:candidates.append((distance,other['id'],other))
    return [f for _,_,f in sorted(candidates)[:count]]


def tick(db,clock):
    rooms=set();wallet_changed=False
    casts=db.execute('SELECT * FROM fishing_casts WHERE version=2 AND collected_at IS NULL').fetchall()
    for row in casts:
        finished=_tick_cast(db,row,clock)
        if finished.get('mechanic')=='tension' and finished['phase']=='caught':wallet_changed=True
    flying=[dict(r) for r in db.execute("SELECT * FROM fishing_projectiles WHERE state='flying'")]
    by_room={}
    for row in flying:by_room.setdefault(row['room_id'],[]).append(row)
    active={r[0] for r in db.execute('SELECT DISTINCT room_id FROM fishing_members WHERE last_seen>?',(clock-LEASE,))}
    for rid in set(by_room)|active:
        entities=[json.loads(r[0]) for r in db.execute('SELECT data FROM fishing_entities WHERE room_id=?',(rid,))]
        effects=[dict(r) for r in db.execute('SELECT starts_at,ends_at,kind FROM fishing_effects WHERE room_id=? AND ends_at>?',(rid,clock-50))]
        heap=[];dead=set();rows={r['id']:r for r in by_room.get(rid,[])}
        for row in rows.values():
            shot=json.loads(row['data']);shot.update(born_at=row['born_at'],expires_at=row['expires_at'])
            hit=_first_hit(shot,row['checked_at'],clock,entities,effects,dead)
            if hit:heapq.heappush(heap,(hit[0],row['id'],hit,shot))
        settled=set()
        while heap:
            _,ident,hit,shot=heapq.heappop(heap);row=rows[ident];at,fish,x,y=hit
            if fish['id'] in dead:
                again=_first_hit(shot,at,clock,entities,effects,dead)
                if again:heapq.heappush(heap,(again[0],ident,again,shot))
                continue
            targets=bonus_targets(fish,entities,at,effects,dead)
            total_multiplier=fish['multiplier']+sum(f['multiplier'] for f in targets)
            hits,payout_unit=fishing_power.resolve(shot,total_multiplier)
            caught=hits>0;gross=payout_unit*fish['multiplier']
            shot.update(resolved_at=at,hit_x=x,hit_y=y,fish_id=fish['id'],species=fish['species'],caught=caught,gross=gross,multiplier=fish['multiplier'],feature=fish.get('feature'),critical=hits)
            if caught:
                awards=[fish,*targets];total=payout_unit*total_multiplier
                shot.update(total_gross=total,bonus_count=len(targets),bonus_fish=[f['id'] for f in targets])
                for award in awards:
                    payout=payout_unit*award['multiplier'];award_id=ident
                    if award['id']!=fish['id']:
                        fx,fy=position(award,at,effects)
                        detail=dict(x0=x,y0=y,vx=0,vy=0,radius=20,stake=0,base_stake=shot['stake'],source_id=ident,
                                    caught=True,gross=payout,resolved_at=at,hit_x=fx,hit_y=fy,fish_id=award['id'],species=award['species'],multiplier=award['multiplier'],feature=fish['feature'])
                        award_id=db.execute("INSERT INTO fishing_projectiles(token,user_id,room_id,operation_id,born_at,checked_at,expires_at,state,data) VALUES(?,?,?,?,?,?,?,'caught',?)",
                            ('feature_'+str(ident).zfill(12)+'_'+str(award['slot']),row['user_id'],rid,row['operation_id'],at,at,at+1.1,encode(detail))).lastrowid
                    db.execute('INSERT INTO fishing_captures VALUES(?,?,?,?,?)',(award['id'],row['user_id'],award_id,payout,at))
                    base._collect(db,row['user_id'],award['species'],base.BY_ID[award['species']]['length'],'arcade')
                    dead.add(award['id'])
                    room=db.execute('SELECT * FROM fishing_rooms WHERE id=?',(rid,)).fetchone()
                    _put_entity(db,rid,spawn(room,award['slot'],at+1,award))
                wallet.transfer(db,row['user_id'],total,'fishing_win','fish:projectile:'+str(ident),at,game=True)
                db.execute('UPDATE fishing_stats SET returned=returned+? WHERE user_id=?',(total,row['user_id']))
                wallet_changed=True
            db.execute('UPDATE fishing_projectiles SET state=?,data=? WHERE id=?',('caught' if caught else 'hit',encode(shot),ident));settled.add(ident);rooms.add(rid)
        for row in rows.values():
            if row['id'] in settled:continue
            if clock>=row['expires_at']:
                data=json.loads(row['data']);data.update(caught=False,gross=0,resolved_at=row['expires_at'])
                db.execute("UPDATE fishing_projectiles SET state='miss',data=? WHERE id=?",(encode(data),row['id']));rooms.add(rid)
            else:db.execute('UPDATE fishing_projectiles SET checked_at=? WHERE id=?',(max(row['checked_at'],clock),row['id']))
        before=db.total_changes;prepare_room(db,rid,clock)
        if db.total_changes>before:rooms.add(rid)
        db.execute('UPDATE fishing_rooms SET last_tick=? WHERE id=?',(clock,rid))
    expired=[r[0] for r in db.execute('SELECT DISTINCT room_id FROM fishing_members WHERE last_seen<=?',(clock-LEASE,))]
    db.execute('DELETE FROM fishing_members WHERE last_seen<=?',(clock-LEASE,));rooms.update(expired)
    return {'rooms':rooms,'wallet':wallet_changed,'active':bool(casts or active or flying)}

FIELDS={
    'cast':{'gameplay_version','expected_revision','power','rod','mechanic','lure'},
    'hook':{'gameplay_version','cast_id'},
    'input':{'gameplay_version','cast_id','sequence','holding','control'},
    'join':{'gameplay_version','room_id'},
    'leave':{'gameplay_version'},
    'heartbeat':{'gameplay_version','room_id'},
    'burst':{'gameplay_version','expected_revision','expected_limit_revision','room_id','cannon','stake','shots'},
    'skill':{'gameplay_version','room_id','kind'},
    'gear':{'gameplay_version','rod','cannon'},
}


def _member(db,uid,rid,clock):
    row=db.execute('SELECT * FROM fishing_members WHERE user_id=? AND room_id=? AND last_seen>?',(uid,rid,clock-LEASE)).fetchone()
    if not row:raise RuleError('請先加入這個魚場，或重新入場。')
    return row


def mutate(db,user,action,data,clock):
    uid=user['id'];member_accounts.require_active(db,uid)
    # Preserve completed v1 operation retries and the reward already in an old cast.
    if action in ('sell','reel') or action in ('cast','shot') and data.get('gameplay_version') is None:
        old=db.execute('SELECT 1 FROM fishing_operations WHERE user_id=? AND operation_id=?',(uid,data.get('operation_id'))).fetchone()
        legacy=db.execute('SELECT version FROM fishing_casts WHERE id=? AND user_id=?',(data.get('cast_id'),uid)).fetchone() if action=='reel' else None
        if action=='sell' or old or legacy and legacy[0]==1:return base._legacy_mutate(db,user,action,data,clock)
        raise RuleError('釣魚玩法已更新，請重新整理；新版必須提竿並完成搏魚。')
    if action not in FIELDS or set(data)-FIELDS[action]-{'operation_id'}:raise RuleError('釣魚操作包含未知欄位。')
    op=data.get('operation_id')
    if not isinstance(op,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',op):raise RuleError('釣魚操作編號無效。')
    fingerprint=encode({'action':action,**{k:data.get(k) for k in sorted(FIELDS[action]) if k not in ('mechanic','lure','control','kind') or k in data}})
    old=db.execute('SELECT * FROM fishing_operations WHERE user_id=? AND operation_id=?',(uid,op)).fetchone()
    if old:
        if old['fingerprint']!=fingerprint:raise RuleError('同一操作編號的內容不符。')
        result=json.loads(old['result'])
        return {'ok':True,'replayed':True,'result':result,**({'skill':skill_view(db,uid,clock)} if action=='input' else {'state':view(db,uid,clock)})}
    if data.get('gameplay_version')!=VERSION or type(data.get('gameplay_version')) is not int:raise RuleError('釣魚玩法已更新，請重新整理。')
    if not wallet.active(db):raise RuleError('點數制度更新中，請稍候。')
    cfg=game_settings.current(db,'fishing')
    if action in ('cast','burst') and (type(data.get('expected_revision')) is not int or data.get('expected_revision')!=cfg['revision']):raise RuleError('釣魚規則已更新，請重新讀取後操作。')
    result={'action':action,'operation_id':op,'at':clock};changed_rooms=set();wallet_changed=False
    db.execute('SAVEPOINT fishing_v2')
    try:
        if action=='cast':
            power=integer(data.get('power'),'拋竿力道',0,1000);rod=integer(data.get('rod'),'釣竿',0,2);option=cast_option(power)
            row=db.execute('SELECT * FROM fishing_casts WHERE user_id=? AND collected_at IS NULL',(uid,)).fetchone()
            if row:
                if row['version']==2:_tick_cast(db,row,clock)
                if db.execute('SELECT 1 FROM fishing_casts WHERE user_id=? AND collected_at IS NULL',(uid,)).fetchone():raise RuleError('已有一竿在水中，請先完成或放棄。')
            used=db.execute('SELECT COALESCE(sum(quota_cost),0) FROM fishing_casts WHERE user_id=? AND day=?',(uid,wallet.day(clock))).fetchone()[0]
            if used+option['cost']>cfg['params']['daily_casts']:raise RuleError('今日精力不足，近岸／中距／遠投分別消耗 1／2／3 點。')
            mechanic=data.get('mechanic','classic')
            if mechanic not in ('classic','tension'):raise RuleError('收線玩法無效。')
            if mechanic=='tension':
                lure=data.get('lure')
                if lure not in base.BY_ID or not base.BY_ID[lure]['weight']:raise RuleError('請選擇可用魚餌。')
                fish=base.BY_ID[lure];option['cost']=1+min(2,list(base.BY_ID).index(lure)//3)
                if used+option['cost']>cfg['params']['daily_casts']:raise RuleError('今日精力不足以使用這款魚餌。')
                ready=clock+.8
            else:fish=base.FISH[game_settings.weighted(option['weights'])];ready=clock+2+secrets.randbelow(2500)/1000
            ident=secrets.token_hex(16);size=max(1,fish['length']*(75+secrets.randbelow(76))//100)
            game={'phase':'waiting','power':power,'tier':option['tier'],'cost':option['cost'],'rod':rod,
                  'hook_deadline':ready+3.2,'settings_revision':cfg['revision']}
            if mechanic=='tension':game.update(mechanic='tension',lure=data['lure'],pull_phase=secrets.randbelow(6283)/1000)
            db.execute('INSERT INTO fishing_casts(id,user_id,day,species,size_cm,ready_at,collected_at,created_at,version,quota_cost,data) VALUES(?,?,?,?,?,?,NULL,?,2,?,?)',(ident,uid,wallet.day(clock),fish['id'],size,ready,clock,option['cost'],encode(game)))
            result.update(cast_id=ident,ready_at=ready,cost=option['cost'])
        elif action in ('hook','input'):
            row=db.execute('SELECT * FROM fishing_casts WHERE id=? AND user_id=? AND version=2',(data.get('cast_id'),uid)).fetchone()
            if not row:raise RuleError('找不到這一竿。')
            game=json.loads(row['data'])
            if row['collected_at'] is not None:raise RuleError('這一竿已結束，請讀取漁獲結果。')
            if action=='hook':
                if game['phase']!='waiting' or not row['ready_at']<=clock<=game['hook_deadline']:raise RuleError('尚未咬鉤，或已錯過提竿時機。')
                rod=RODS[game['rod']];index=list(base.BY_ID).index(row['species'])
                game.update(phase='playing',hooked_at=clock,sim_at=clock,deadline=clock+23,zone_y=.5,velocity=0.,progress=.12,escape=0.,holding=False,input_at=clock,sequence=0,
                            width=rod['width'],rate=rod['rate'],path={'a':.13+index*.019,'b':.035+index*.006,'speed':.65+index*.11,'phase':secrets.randbelow(6283)/1000})
                if game.get('mechanic')=='tension':fishing_tension.start(game,clock,index,rod)
            else:
                if game['phase']!='playing':raise RuleError('請先提竿再收線。')
                sequence=integer(data.get('sequence'),'收線序號',1,10000)
                if sequence!=game['sequence']+1 or type(data.get('holding')) is not bool:raise RuleError('收線狀態已更新，請同步後重試。')
                if clock-game['input_at']<.07:raise RuleError('收線操作過於頻繁。')
                advance_skill(game,clock)
                game.update(sequence=sequence,holding=data['holding'],input_at=clock)
                if 'control' in data:
                    if game.get('mechanic')!='tension':raise RuleError('這一竿不支援收線滑桿。')
                    game['control']=number(data['control'],'收線力道',0,1000)/1000
                else:game['control']=None
            if game['phase'] in ('caught','escaped'):
                _finish_cast(db,row,game,clock)
                wallet_changed=game['phase']=='caught' and game.get('mechanic')=='tension'
            else:db.execute('UPDATE fishing_casts SET data=? WHERE id=?',(encode(game),row['id']))
            result.update(cast_id=row['id'],phase=game['phase'],sequence=game.get('sequence',0))
        elif action=='gear':
            rod=integer(data.get('rod'),'釣竿',0,2);cannon=integer(data.get('cannon'),'魚炮',0,2)
            db.execute('INSERT INTO fishing_loadouts VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET rod=excluded.rod,cannon=excluded.cannon',(uid,rod,cannon))
            result.update(rod=rod,cannon=cannon)
        elif action=='join':
            rid=integer(data.get('room_id'),'魚場',0,ROOMS)
            db.execute('DELETE FROM fishing_members WHERE last_seen<=?',(clock-LEASE,))
            own=db.execute('SELECT * FROM fishing_members WHERE user_id=?',(uid,)).fetchone()
            if rid==0:rid=own['room_id'] if own else next((r for r in range(1,ROOMS+1) if db.execute('SELECT count(*) FROM fishing_members WHERE room_id=?',(r,)).fetchone()[0]<CAPACITY),0)
            if not rid:raise RuleError('目前魚場已滿，請稍候。')
            if own and own['room_id']==rid:
                db.execute('UPDATE fishing_members SET last_seen=? WHERE user_id=?',(clock,uid));seat=own['seat']
            else:
                used={r[0] for r in db.execute('SELECT seat FROM fishing_members WHERE room_id=?',(rid,))}
                seat=next((s for s in range(CAPACITY) if s not in used),None)
                if seat is None:raise RuleError('這個魚場已滿，可換其他魚場或觀戰。')
                if own:changed_rooms.add(own['room_id'])
                db.execute('DELETE FROM fishing_members WHERE user_id=?',(uid,));db.execute('INSERT INTO fishing_members VALUES(?,?,?,?,COALESCE((SELECT ready_at FROM fishing_cooldowns WHERE user_id=?),0))',(uid,rid,seat,clock,uid))
            prepare_room(db,rid,clock);changed_rooms.add(rid);result.update(room_id=rid,seat=seat)
        elif action=='leave':
            own=db.execute('SELECT room_id FROM fishing_members WHERE user_id=?',(uid,)).fetchone()
            if own:changed_rooms.add(own[0]);db.execute('DELETE FROM fishing_members WHERE user_id=?',(uid,))
        elif action=='heartbeat':
            rid=integer(data.get('room_id'),'魚場',1,ROOMS);_member(db,uid,rid,clock)
            db.execute('UPDATE fishing_members SET last_seen=? WHERE user_id=?',(clock,uid))
        elif action=='skill':
            rid=integer(data.get('room_id'),'魚場',1,ROOMS);_member(db,uid,rid,clock)
            kind=data.get('kind','freeze')
            if kind not in ('freeze','laser'):raise RuleError('技能無效。')
            cooldown=db.execute('SELECT * FROM fishing_cooldowns WHERE user_id=?',(uid,)).fetchone()
            column='ready_at' if kind=='freeze' else 'laser_at'
            if cooldown and clock<cooldown[column]:raise RuleError('技能尚在冷卻。')
            if kind=='freeze' and db.execute("SELECT 1 FROM fishing_effects WHERE room_id=? AND kind='freeze' AND ends_at>?",(rid,clock)).fetchone():raise RuleError('魚場已經處於冰凍中。')
            duration,cool= (2,30) if kind=='freeze' else (6,45)
            db.execute('INSERT INTO fishing_effects(room_id,user_id,starts_at,ends_at,kind) VALUES(?,?,?,?,?)',(rid,uid,clock,clock+duration,kind))
            db.execute('INSERT OR IGNORE INTO fishing_cooldowns(user_id,ready_at,laser_at) VALUES(?,0,0)',(uid,))
            db.execute('UPDATE fishing_cooldowns SET '+column+'=? WHERE user_id=?',(clock+cool,uid))
            if kind=='freeze':db.execute('UPDATE fishing_members SET skill_at=? WHERE user_id=?',(clock+cool,uid))
            changed_rooms.add(rid);result.update(kind=kind,ends_at=clock+duration,ready_at=clock+cool)
        elif action=='burst':
            rid=integer(data.get('room_id'),'魚場',1,ROOMS);member=_member(db,uid,rid,clock)
            cannon=integer(data.get('cannon'),'魚炮',0,2);weapon=CANNONS[cannon]
            stake=integer(data.get('stake'),'每發點數',10,min(1000,game_settings.bet_limit(cfg)))
            ammo=next((a for a in fishing_power.AMMO if a['stake']==stake),None)
            if not ammo:raise RuleError('請選擇10、100或1,000點砲彈。')
            laser=bool(db.execute("SELECT 1 FROM fishing_effects WHERE room_id=? AND user_id=? AND kind='laser' AND starts_at<=? AND ends_at>?",(rid,uid,clock,clock)).fetchone())
            speed=1800 if laser else SPEED
            if type(data.get('expected_limit_revision')) is not int or data.get('expected_limit_revision')!=cfg['bet_limit_revision']:raise RuleError('炮彈上限已更新，請重新讀取魚場。')
            shots=data.get('shots')
            if not isinstance(shots,list) or not 1<=len(shots)<=4:raise RuleError('每批限 1–4 發砲彈。')
            previous=db.execute('SELECT last_shot_at FROM fishing_stats WHERE user_id=?',(uid,)).fetchone()
            last=previous[0] if previous else -1e20;tokens=set();validated=[]
            previous_weapon=db.execute('SELECT data FROM fishing_projectiles WHERE user_id=? ORDER BY id DESC LIMIT 1',(uid,)).fetchone()
            previous_interval=CANNONS[json.loads(previous_weapon[0]).get('cannon',cannon)]['interval'] if previous_weapon else weapon['interval']
            room=db.execute('SELECT * FROM fishing_rooms WHERE id=?',(rid,)).fetchone()
            for shot in shots:
                if not isinstance(shot,dict) or set(shot)!={'token','fired_at','x','y'}:raise RuleError('砲彈欄位無效。')
                token=shot['token']
                if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',token) or token in tokens:raise RuleError('砲彈識別碼無效或重複。')
                if db.execute('SELECT 1 FROM fishing_projectiles WHERE user_id=? AND token=?',(uid,token)).fetchone():raise RuleError('這發砲彈已送出，請確認原批次。')
                tokens.add(token);fired=number(shot['fired_at'],'發射時間',clock-1.2,clock+.06)
                if fired-last<max(previous_interval,weapon['interval'])-.01:raise RuleError('發射速度超過魚炮設定。')
                last=fired;previous_interval=weapon['interval'];x=number(shot['x'],'瞄準位置',0,1000);y=number(shot['y'],'瞄準位置',0,600)
                ox,oy=origin(member['seat']);distance=math.hypot(x-ox,y-oy)
                if distance<35:raise RuleError('請朝魚場內發射。')
                born=min(clock,max(fired,clock-.2,room['last_tick']))
                body=dict(x0=ox,y0=oy,vx=(x-ox)/distance*speed,vy=(y-oy)/distance*speed,radius=weapon['radius']+(12 if laser else 0),stake=stake,power=ammo['power'],laser=laser,cannon=cannon,target_bps=cfg['params']['target_bps'],settings_revision=cfg['revision'],expires_at=born+FLIGHT)
                validated.append((token,born,body))
            total=stake*len(validated)
            wallet.transfer(db,uid,-total,'fishing_shot','fish:'+op+':cost',clock,game=True)
            accepted=[]
            for token,born,body in validated:
                ident=db.execute("INSERT INTO fishing_projectiles(token,user_id,room_id,operation_id,born_at,checked_at,expires_at,state,data) VALUES(?,?,?,?,?,?,?,'flying',?)",(token,uid,rid,op,born,born,body['expires_at'],encode(body))).lastrowid
                accepted.append({'id':ident,'token':token,'born_at':born,**body})
            db.execute('''INSERT INTO fishing_stats(user_id,shots,spent,returned,last_shot_at) VALUES(?,?,?,0,?) ON CONFLICT(user_id) DO UPDATE SET shots=shots+excluded.shots,spent=spent+excluded.spent,last_shot_at=excluded.last_shot_at''',(uid,len(accepted),total,last))
            db.execute('UPDATE fishing_members SET last_seen=? WHERE user_id=?',(clock,uid))
            result.update(room_id=rid,shots=accepted,cost=total,count=len(accepted));changed_rooms.add(rid);wallet_changed=True
        db.execute('INSERT INTO fishing_operations VALUES(?,?,?,?,?)',(uid,op,fingerprint,encode(result),clock))
        db.execute('RELEASE SAVEPOINT fishing_v2')
    except Exception:
        db.execute('ROLLBACK TO SAVEPOINT fishing_v2');db.execute('RELEASE SAVEPOINT fishing_v2');raise
    reply={'ok':True,'replayed':False,'result':result,'changed_rooms':sorted(changed_rooms),'wallet_changed':wallet_changed}
    if action=='input':reply['skill']=skill_view(db,uid,clock)
    elif action=='heartbeat':reply['member']={'room_id':data['room_id']}
    elif action=='burst':reply['state']=burst_view(db,uid,clock)
    else:reply['state']=view(db,uid,clock)
    return reply
