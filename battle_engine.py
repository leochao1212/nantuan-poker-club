"""Original small-room battle royale. Authoritative, fixed-step, no wallet/DB writes.

Coordinates are metres, +Y up, yaw 0 looks towards -Z. Only input intent crosses
the network: positions, ammo, loot, damage and results belong to this simulation.
"""
from dataclasses import dataclass, field
import math
import random

STEP = .05
CAPACITY = 16
WORLD_RADIUS = 355
DROP_SECONDS = 7
ROUND_SECONDS = 330
WEAPONS = {
    'pistol': dict(name='9mm 手槍', damage=24, interval=.34, magazine=12, reload=1.35, range=95, spread=.014),
    'smg': dict(name='疾風衝鋒槍', damage=17, interval=.11, magazine=30, reload=1.8, range=110, spread=.026),
    'rifle': dict(name='獵鷹步槍', damage=29, interval=.19, magazine=30, reload=2.1, range=200, spread=.012),
    'sniper': dict(name='山隼狙擊槍', damage=76, interval=1.3, magazine=5, reload=2.7, range=290, spread=.003),
}
ZONES = [(45, 300), (40, 225), (40, 155), (35, 95), (35, 52), (30, 22), (25, 0)]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def number(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError('無效的戰場操作。')
    return float(v)


def ray_box(origin, direction, box, maximum):
    """Slab intersection including vertical cover; returns first distance or None."""
    low, high = 0., maximum
    for i, key in enumerate(('x', 'y', 'z')):
        half = box[('w', 'h', 'd')[i]] / 2
        a, b = box[key] - half, box[key] + half
        if abs(direction[i]) < 1e-8:
            if not a <= origin[i] <= b:
                return None
        else:
            u, v = (a-origin[i])/direction[i], (b-origin[i])/direction[i]
            low, high = max(low, min(u, v)), min(high, max(u, v))
            if high < low:
                return None
    return low if high >= 0 else None


def ray_sphere(origin, direction, center, radius):
    offset = [origin[i]-center[i] for i in range(3)]
    b = sum(offset[i]*direction[i] for i in range(3))
    c = sum(v*v for v in offset)-radius*radius
    disc = b*b-c
    if disc < 0:
        return None
    distance = -b-math.sqrt(disc)
    return distance if distance >= 0 else None


def make_map(seed):
    rng = random.Random(seed)
    structures, cover = [], []
    def box(x, y, z, w, h, d, kind='wall'):
        cover.append(dict(x=x, y=y, z=z, w=w, h=h, d=d, kind=kind))
    # Hand-authored settlement arrangement; a doorway is physical open space.
    for x, z, w, d, color in [(-65,-65,14,12,0),(-40,-65,12,16,1),(-65,-37,16,11,2),
                              (70,20,13,15,1),(94,20,13,15,2),(82,49,20,12,0),
                              (-145,105,18,12,2),(-118,112,14,15,0),
                              (128,-133,20,13,1),(155,-125,13,13,0),
                              (-20,156,18,12,1),(12,157,14,12,2),(-10,-185,22,14,2)]:
        structures.append(dict(x=x,z=z,w=w,d=d,color=color))
        box(x-w/2,1.6,z,.4,3.2,d);box(x+w/2,1.6,z,.4,3.2,d)
        box(x,1.6,z-d/2,w,3.2,.4)
        side=(w-2.8)/2
        box(x-(side+2.8)/2,1.6,z+d/2,side,3.2,.4)
        box(x+(side+2.8)/2,1.6,z+d/2,side,3.2,.4)
        box(x,4,z,w+.8,1.6,d+.8,'roof')
    for i in range(66):
        angle=rng.random()*math.tau;radius=rng.uniform(45,325)
        x,z=math.sin(angle)*radius,math.cos(angle)*radius
        if any(abs(x-b['x'])<b['w']/2+4 and abs(z-b['z'])<b['d']/2+4 for b in structures):
            continue
        kind='tree' if i%3 else 'rock';size=rng.uniform(1.6,3.1) if kind=='rock' else .8
        box(round(x,2),size/2,round(z,2),size,size,size,kind)
    for i in range(20):
        x,z=rng.uniform(-175,175),rng.uniform(-175,175)
        if not any(abs(x-b['x'])<b['w']/2+3 and abs(z-b['z'])<b['d']/2+3 for b in structures):
            box(round(x,2),1,round(z,2),3,2,3,'crate')
    box(-225,7,202,6,14,6,'tower')
    return dict(seed=seed,radius=WORLD_RADIUS,structures=structures,cover=cover)


@dataclass
class Player:
    id: int
    name: str
    bot: bool = False
    x: float = 0
    z: float = 0
    y: float = 0
    vy: float = 0
    vx: float = 0
    vz: float = 0
    yaw: float = 0
    pitch: float = 0
    hp: float = 100
    armor: float = 0
    helmet: bool = False
    stamina: float = 100
    weapons: dict = field(default_factory=dict)
    slot: str = ''
    reserve: int = 0
    medkits: int = 1
    grenades: int = 1
    kills: int = 0
    rank: int = 0
    seq: int = -1
    intent: dict = field(default_factory=dict)
    input_at: float = -100
    connected: bool = True
    gone_at: float | None = None
    next_fire: float = 0
    fire_pending: bool = False
    reload_at: float = 0
    heal_at: float = 0
    ai_at: float = 0
    next_use: float = 0
    animation: str = 'idle'


class Match:
    def __init__(self, seed, clock=0):
        self.seed=seed;self.rng=random.Random(seed ^ 0xA93B21)
        self.map=make_map(seed);self.players={};self.phase='waiting';self.started=0
        self.clock=clock;self.events=[];self.event_id=0;self.tick=0
        self.zone=dict(x=0.,z=0.,r=340.,next_x=0.,next_z=0.,next_r=300.,stage=0,seconds=45)
        self.loot={};self.grenades=[];self.winner=None;self.ended=0

    def add(self, uid, name, bot=False):
        if uid in self.players:
            return self.players[uid]
        if self.phase!='waiting' or len(self.players)>=CAPACITY:
            raise ValueError('戰局已開始或人數已滿，請選擇另一個房間。')
        p=Player(uid,name,bot);self.players[uid]=p
        return p

    def event(self, kind, **data):
        self.event_id+=1
        self.events.append(dict(id=self.event_id,kind=kind,at=round(self.clock,2),**data))
        self.events=self.events[-32:]

    def safe(self,x,z,radius=.45,y=0,height=1.8):
        if math.hypot(x,z)>WORLD_RADIUS-radius:
            return False
        for b in self.map['cover']:
            if y+height <= b['y']-b['h']/2 or y >= b['y']+b['h']/2:
                continue
            if abs(x-b['x'])<b['w']/2+radius and abs(z-b['z'])<b['d']/2+radius:
                return False
        return True

    def start(self, clock, bots=True):
        if self.phase!='waiting':
            return
        if not self.players:
            raise ValueError('至少需要一位玩家。')
        if bots:
            for i in range(CAPACITY-len(self.players)):
                self.add(-i-1,f'巡島者 {i+1:02}',True)
        if len(self.players)<2:
            raise ValueError('請等待另一位玩家，或開啟 AI 補位。')
        self.phase='countdown';self.started=clock+4;self.clock=clock
        ids=list(self.players);self.rng.shuffle(ids)
        for i,uid in enumerate(ids):
            angle=i/len(ids)*math.tau+.2;rad=120+self.rng.random()*100
            x,z=math.sin(angle)*rad,math.cos(angle)*rad
            for attempt in range(100):
                if self.safe(x,z,radius=3.5):break
                x=self.rng.uniform(-220,220);z=self.rng.uniform(-220,220)
            p=self.players[uid];p.x=x;p.z=z;p.y=34;p.yaw=-math.atan2(x,z)
            # A visible starting supply cache, not a hidden weapon grant.
            self.loot[len(self.loot)+1]=dict(id=len(self.loot)+1,x=round(x,2),z=round(z,2),kind='pistol')
        for s in self.map['structures']:
            for j in range(3):
                self.spawn_loot(s['x']+(j-1)*2,s['z'],self.rng.choice(['rifle','smg','sniper','ammo','armor','medkit','helmet']))
        for _ in range(50):
            x,z=self.rng.uniform(-270,270),self.rng.uniform(-270,270)
            if self.safe(x,z,1.2):
                self.spawn_loot(x,z,self.rng.choice(['rifle','smg','ammo','medkit','armor','grenade']))
        self.event('start')

    def spawn_loot(self,x,z,kind):
        i=max(self.loot,default=0)+1
        self.loot[i]=dict(id=i,x=round(x,2),z=round(z,2),kind=kind)

    def input(self, uid, data, clock):
        p=self.players[uid]
        if set(data)-{'type','seq','forward','strafe','yaw','pitch','fire','aim','sprint','crouch','jump'}:
            raise ValueError('不支援的控制欄位。')
        seq=number(data.get('seq'),0,2147483647)
        if seq!=int(seq):raise ValueError('操作序號需為整數。')
        if seq<=p.seq:return
        values={k:number(data.get(k,0),*bounds) for k,bounds in {
            'forward':(-1,1),'strafe':(-1,1),'yaw':(-math.tau*100,math.tau*100),'pitch':(-1.3,1.3)}.items()}
        for k in ('fire','aim','sprint','crouch','jump'):
            if not isinstance(data.get(k,False),bool):raise ValueError('無效的按鍵狀態。')
            values[k]=data.get(k,False)
        # Preserve a trigger edge when down/up packets arrive between two ticks.
        if values['fire'] and not p.intent.get('fire') and self.phase=='playing' and p.hp>0:
            p.fire_pending=True
        p.seq=int(seq);p.intent=values;p.input_at=clock

    def action(self,uid,kind,value=None):
        p=self.players[uid]
        if p.hp<=0 or self.phase!='playing':return
        if kind=='slot':
            if value in p.weapons and value!=p.slot:
                p.slot=value;p.reload_at=0;p.heal_at=0
            return
        if kind=='reload':
            if p.slot and not p.reload_at and p.reserve and p.weapons[p.slot]<WEAPONS[p.slot]['magazine']:
                p.reload_at=self.clock+WEAPONS[p.slot]['reload'];p.heal_at=0
        elif kind=='heal':
            if p.hp<100 and p.medkits and not p.heal_at:
                p.heal_at=self.clock+3;p.reload_at=0
        elif kind=='pickup':
            if self.clock<p.next_use:return
            p.next_use=self.clock+.2
            near=sorted((math.hypot(l['x']-p.x,l['z']-p.z),i) for i,l in self.loot.items())
            if near and near[0][0]<3.5:
                distance,i=near[0];item=self.loot[i];kind=item['kind']
                if p.y>1 or not self.visible((p.x,1,p.z),(item['x'],1,item['z'])):return
                if kind in WEAPONS:
                    if kind not in p.weapons and len(p.weapons)>=2:
                        old=p.slot;p.weapons.pop(old);self.spawn_loot(p.x,p.z,old)
                    p.weapons[kind]=WEAPONS[kind]['magazine'];p.slot=kind;p.reserve=min(240,p.reserve+45);p.reload_at=0
                elif kind=='ammo':p.reserve=min(240,p.reserve+60)
                elif kind=='medkit':p.medkits=min(5,p.medkits+1)
                elif kind=='armor':p.armor=75
                elif kind=='helmet':p.helmet=True
                elif kind=='grenade':p.grenades=min(5,p.grenades+1)
                del self.loot[i];self.event('pickup',player=uid,item=kind)
        elif kind=='grenade' and p.grenades and self.clock>=p.next_use:
            p.next_use=self.clock+1;p.grenades-=1
            direction=(math.sin(p.yaw),-math.cos(p.yaw))
            self.grenades.append(dict(owner=uid,x=p.x,y=p.y+1.5,z=p.z,vx=direction[0]*15,vy=8,vz=direction[1]*15,at=self.clock+2.2))
        elif kind not in ('grenade',):
            raise ValueError('不支援的戰場動作。')

    def visible(self, a, b):
        distance=math.dist(a,b)
        if distance<.001:return True
        direction=tuple((b[i]-a[i])/distance for i in range(3))
        return not any(ray_box(a,direction,box,distance) is not None for box in self.map['cover'])

    def damage(self,p,amount,attacker=None,head=False,source='bullet'):
        if p.hp<=0:return
        if source=='bullet':
            if head and p.helmet:amount*=.6;p.helmet=False
            saved=min(p.armor,amount*.45);p.armor-=saved;amount-=saved
            p.heal_at=0
        p.hp=max(0,p.hp-amount)
        if source in ('bullet','grenade'):
            self.event('hit',player=p.id,by=attacker,damage=round(amount),head=head,source=source)
        if p.hp==0:
            p.rank=sum(q.hp>0 for q in self.players.values())+1;p.intent={};p.animation='dead'
            if attacker in self.players and attacker!=p.id:self.players[attacker].kills+=1
            if p.slot:self.spawn_loot(p.x,p.z,p.slot)
            self.event('eliminated',player=p.id,by=attacker,rank=p.rank,source=source)

    def shoot(self,p,pending=None):
        if not p.slot or p.reload_at or p.heal_at or self.clock<p.next_fire:return
        w=WEAPONS[p.slot]
        if p.weapons[p.slot]<=0:
            self.action(p.id,'reload');return
        p.weapons[p.slot]-=1;p.next_fire=self.clock+w['interval']
        spread=w['spread']*(.4 if p.intent.get('aim') else 1)*(1.7 if abs(p.vx)+abs(p.vz)>1 else 1)*(.7 if p.intent.get('crouch') else 1)
        if p.bot:spread+=.05
        yaw=p.yaw+self.rng.gauss(0,spread);pitch=p.pitch+self.rng.gauss(0,spread)
        eye=1.13 if p.intent.get('crouch') else 1.55
        origin=(p.x,p.y+eye,p.z);direction=(math.sin(yaw)*math.cos(pitch),math.sin(pitch),-math.cos(yaw)*math.cos(pitch))
        nearest=w['range'];victim=None;headshot=False
        for box in self.map['cover']:
            d=ray_box(origin,direction,box,nearest)
            if d is not None:nearest=d
        for q in self.players.values():
            if q.id==p.id or q.hp<=0:continue
            crouch=q.intent.get('crouch',False)
            for height,radius,head in ((.5 if crouch else .85,.44,False),(1.17 if crouch else 1.65,.25,True)):
                d=ray_sphere(origin,direction,(q.x,q.y+height,q.z),radius)
                if d is not None and d<nearest:nearest=d;victim=q;headshot=head
        end=[round(origin[i]+direction[i]*nearest,2) for i in range(3)]
        self.event('shot',player=p.id,start=[round(v,2) for v in origin],end=end)
        if victim:
            hit=(victim,w['damage']*(1.8 if headshot else 1),p.id,headshot)
            if pending is None:self.damage(*hit)
            else:pending.append(hit)

    def bot_input(self,p):
        if self.clock<p.ai_at:return
        p.ai_at=self.clock+.35+self.rng.random()*.15
        targets=[q for q in self.players.values() if q.hp>0 and q.id!=p.id and math.hypot(q.x-p.x,q.z-p.z)<100]
        targets.sort(key=lambda q:(q.x-p.x)**2+(q.z-p.z)**2)
        target=next((q for q in targets if self.visible((p.x,1.55,p.z),(q.x,1,q.z))),None)
        outside=math.hypot(p.x-self.zone['next_x'],p.z-self.zone['next_z'])>max(5,self.zone['next_r']*.85)
        fire=False;forward=.7;strafe=0;pitch=0
        if outside:
            dx,dz=self.zone['next_x']-p.x,self.zone['next_z']-p.z
        elif not p.slot or p.reserve<10:
            loot=min(self.loot.values(),key=lambda l:(l['x']-p.x)**2+(l['z']-p.z)**2,default=None)
            if loot:dx,dz=loot['x']-p.x,loot['z']-p.z
            else:dx,dz=-p.x,-p.z
            if loot and math.hypot(dx,dz)<3:self.action(p.id,'pickup')
        elif target:
            dx,dz=target.x-p.x,target.z-p.z;fire=True;forward=.15;strafe=math.sin(self.clock+p.id)*.55
            pitch=math.atan2(target.y-p.y-.4,max(1,math.hypot(dx,dz)))
        else:
            angle=self.clock*.08+p.id;dx,dz=math.sin(angle)*50-p.x*.2,math.cos(angle)*50-p.z*.2
        if p.hp<55 and p.medkits and not target:self.action(p.id,'heal')
        if p.slot and p.weapons[p.slot]==0:self.action(p.id,'reload')
        yaw=math.atan2(dx,-dz)
        if not fire and not self.safe(p.x+math.sin(yaw)*2,p.z-math.cos(yaw)*2):
            side=1 if p.id%2 else -1
            for turn in (.7,1.4,2.1,-.7,-1.4,-2.1,math.pi):
                candidate=yaw+turn*side
                if self.safe(p.x+math.sin(candidate)*2,p.z-math.cos(candidate)*2):
                    yaw=candidate;break
        if self.clock<self.started+DROP_SECONDS+6:fire=False
        p.intent=dict(forward=forward,strafe=strafe,yaw=yaw,pitch=pitch,fire=fire,aim=fire,sprint=outside)
        p.input_at=self.clock

    def update_zone(self,elapsed):
        cursor=0;last_r=340
        for i,(duration,radius) in enumerate(ZONES):
            if elapsed<cursor+duration:
                t=clamp((elapsed-cursor)/duration,0,1)
                self.zone.update(r=round(last_r+(radius-last_r)*t,2),next_r=radius,stage=i+1,seconds=math.ceil(duration*(1-t)))
                return
            cursor+=duration;last_r=radius
        self.zone.update(r=0,next_r=0,stage=len(ZONES),seconds=0)

    def advance(self, clock):
        """Exactly one fixed step. Caller bounds catch-up; never integrates a huge dt."""
        self.clock=clock;self.tick+=1
        if self.phase=='countdown' and clock>=self.started:self.phase='drop'
        if self.phase=='drop':
            for p in self.players.values():
                p.y=max(0,34*(1-(clock-self.started)/DROP_SECONDS));p.animation='drop'
            if clock>=self.started+DROP_SECONDS:
                self.phase='playing';self.event('landed')
            else:return
        if self.phase!='playing':return
        elapsed=clock-self.started-DROP_SECONDS;self.update_zone(elapsed)
        pending=[];shooters=[]
        for p in list(self.players.values()):
            if p.hp<=0:continue
            if not p.connected and p.gone_at is not None and clock-p.gone_at>25:
                self.damage(p,1000,source='disconnect');continue
            if p.bot:self.bot_input(p)
            intent=p.intent if clock-p.input_at<.7 else {}
            p.yaw=intent.get('yaw',p.yaw);p.pitch=intent.get('pitch',p.pitch)
            forward,strafe=intent.get('forward',0),intent.get('strafe',0);length=max(1,math.hypot(forward,strafe))
            crouch=intent.get('crouch',False);sprint=intent.get('sprint',False) and p.stamina>0 and not crouch and not intent.get('aim')
            speed=7.5 if sprint else 2.2 if crouch else 4.5
            if p.heal_at:speed*=.35
            p.stamina=clamp(p.stamina+(-22 if sprint and length>0 and (forward or strafe) else 16)*STEP,0,100)
            p.vx=(math.sin(p.yaw)*forward+math.cos(p.yaw)*strafe)*speed/length
            p.vz=(-math.cos(p.yaw)*forward+math.sin(p.yaw)*strafe)*speed/length
            height=1.45 if crouch else 1.85
            nx,nz=p.x+p.vx*STEP,p.z+p.vz*STEP
            if self.safe(nx,p.z,y=p.y,height=height):p.x=nx
            else:p.vx=0
            if self.safe(p.x,nz,y=p.y,height=height):p.z=nz
            else:p.vz=0
            if intent.get('jump') and p.y==0 and not crouch:p.vy=5.8
            p.vy-=18*STEP;ny=max(0,p.y+p.vy*STEP)
            if ny>p.y and not self.safe(p.x,p.z,y=ny,height=height):p.vy=0
            else:p.y=ny
            if p.y==0:p.vy=0
            p.animation='crouch' if crouch else 'run' if abs(p.vx)+abs(p.vz)>1 else 'idle'
            if p.reload_at and clock>=p.reload_at:
                used=min(p.reserve,WEAPONS[p.slot]['magazine']-p.weapons[p.slot]);p.weapons[p.slot]+=used;p.reserve-=used;p.reload_at=0
            if p.heal_at and clock>=p.heal_at:
                p.hp=min(100,p.hp+60);p.medkits-=1;p.heal_at=0;self.event('healed',player=p.id)
            if math.hypot(p.x-self.zone['x'],p.z-self.zone['z'])>self.zone['r']:
                self.damage(p,(2+self.zone['stage']*1.2)*STEP,source='zone')
            if p.hp>0 and (intent.get('fire') or p.fire_pending and clock-p.input_at<.7):shooters.append(p)
            p.fire_pending=False
        for p in shooters:self.shoot(p,pending)
        # Resolve shots from this tick together: insertion order / room ownership
        # must not prevent an already-fired opponent from trading an elimination.
        for hit in pending:self.damage(*hit)
        fallen={p.id for p,_,_,_ in pending if p.hp<=0}
        if len(fallen)>1:
            rank=sum(p.hp>0 for p in self.players.values())+1
            for uid in fallen:self.players[uid].rank=rank
            for e in self.events:
                if e['kind']=='eliminated' and e['player'] in fallen and e['at']==round(self.clock,2):e['rank']=rank
        for g in self.grenades[:]:
            nx,nz=g['x']+g['vx']*STEP,g['z']+g['vz']*STEP
            if self.safe(nx,nz,.15,y=max(0,g['y']),height=.2):g['x']=nx;g['z']=nz
            else:g['vx']*=-.4;g['vz']*=-.4
            g['vy']-=14*STEP;g['y']=max(.15,g['y']+g['vy']*STEP)
            if g['y']<=.15:g['vx']*=.8;g['vz']*=.8;g['vy']=abs(g['vy'])*.3
            if clock>=g['at']:
                self.event('explosion',x=g['x'],y=g['y'],z=g['z'])
                for p in self.players.values():
                    distance=math.dist((p.x,p.y+.8,p.z),(g['x'],g['y'],g['z']))
                    if distance<10 and self.visible((g['x'],g['y']+.1,g['z']),(p.x,p.y+.8,p.z)):
                        self.damage(p,130*(1-distance/10),g['owner'],source='grenade')
                self.grenades.remove(g)
        alive=[p for p in self.players.values() if p.hp>0]
        if len(alive)<=1 or elapsed>=ROUND_SECONDS:
            self.phase='finished';self.ended=clock
            self.winner=alive[0].id if len(alive)==1 else None
            if self.winner is not None:alive[0].rank=1
            # A timeout is an explicit draw, never an arbitrary winner.
            self.event('finished',winner=self.winner)

    def snapshot(self,uid):
        p=self.players[uid]
        # Only nearby, visible opponents are transmitted. Minimap shows self/zone.
        eye=(p.x,p.y+(1.13 if p.intent.get('crouch') else 1.55),p.z)
        players=[]
        for q in self.players.values():
            own=q.id==uid;distance=math.hypot(p.x-q.x,p.z-q.z)
            if not own and self.phase=='playing' and p.hp>0 and (distance>240 or not self.visible(eye,(q.x,q.y+1.1,q.z))):continue
            players.append(dict(id=q.id,name=q.name,bot=q.bot,x=round(q.x,2),y=round(q.y,2),z=round(q.z,2),
                                yaw=round(q.yaw,3),pitch=round(q.pitch,3),vx=round(q.vx,2),vz=round(q.vz,2),
                                hp=round(q.hp) if own or self.phase!='playing' else int(q.hp>0)*100,
                                armor=round(q.armor) if own else int(q.armor>0),helmet=q.helmet,slot=q.slot,
                                animation=q.animation,kills=q.kills,rank=q.rank,connected=q.connected))
        nearby=[l for l in self.loot.values() if math.hypot(l['x']-p.x,l['z']-p.z)<85]
        visible_ids={q['id'] for q in players}
        events=[e for e in self.events if self.clock-e['at']<5 and (e['kind'] not in ('shot','hit') or e.get('player') in visible_ids or e.get('by')==uid)]
        return dict(type='state',round_id=self.seed,tick=self.tick,clock=round(self.clock,3),phase=self.phase,
                    starts_in=max(0,round(self.started-self.clock,1)),drop_left=max(0,round(self.started+DROP_SECONDS-self.clock,1)),
                    alive=sum(q.hp>0 for q in self.players.values()),total=len(self.players),zone=self.zone.copy(),
                    ai_grace=max(0,math.ceil(self.started+DROP_SECONDS+6-self.clock)) if any(p.bot for p in self.players.values()) else 0,
                    players=players,loot=nearby,grenades=[{k:round(v,2) for k,v in g.items() if k in ('x','y','z')} for g in self.grenades if math.hypot(g['x']-p.x,g['z']-p.z)<100],
                    self=dict(id=uid,hp=round(p.hp,1),armor=round(p.armor),stamina=round(p.stamina),weapons=p.weapons.copy(),
                              slot=p.slot,reserve=p.reserve,medkits=p.medkits,grenades=p.grenades,kills=p.kills,rank=p.rank,
                              seq=p.seq,reload=max(0,round(p.reload_at-self.clock,1)),heal=max(0,round(p.heal_at-self.clock,1))),
                    winner=self.winner,events=events)
