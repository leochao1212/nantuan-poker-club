"""Authoritative survival rules and bounded transport; no production database."""
import json
import math
import time
import unittest

import battle
from battle_engine import Match, Player, STEP, WEAPONS, ray_box, ray_sphere, ray_capsule


class IslandRules(unittest.TestCase):
    def match(self):
        m=Match(41);m.add(1,'測試甲');m.add(2,'測試乙');m.start(0,False);m.advance(12)
        m.map['cover']=[]
        for i,p in enumerate(m.players.values()):p.x=0;p.z=-10*i;p.y=0;p.yaw=0
        return m

    def intent(self,m,uid=1,**kw):
        m.input(uid,{'type':'input','seq':m.players[uid].seq+1,**kw},m.clock)

    def test_population_spawn_and_deterministic_map(self):
        a=Match(17);b=Match(17);self.assertEqual(a.map,b.map)
        a.add(1,'甲');a.start(0);self.assertEqual(len(a.players),16)
        self.assertEqual(sum(p.bot for p in a.players.values()),15)
        self.assertTrue(all(a.safe(p.x,p.z) for p in a.players.values()))
        self.assertTrue(all(a.safe(p.x,p.z,radius=3.5) for p in a.players.values()))
        self.assertTrue(all(math.sin(p.yaw)*p.x-math.cos(p.yaw)*p.z<0 for p in a.players.values()),'Spawn faces inland')
        with self.assertRaises(ValueError):a.add(2,'遲到')
        a.advance(4);self.assertEqual(a.phase,'drop');a.advance(11);self.assertEqual(a.phase,'playing')
        self.assertTrue(all(p.y==0 for p in a.players.values()))

    def test_no_double_start_and_humans_only_requires_two(self):
        m=Match(1);m.add(1,'甲')
        with self.assertRaises(ValueError):m.start(0,False)
        m.add(2,'乙');m.start(0,False);start=m.started;m.start(9,False)
        self.assertEqual(m.started,start);self.assertEqual(len(m.players),2)

    def test_input_rejects_position_damage_nan_and_bad_buttons(self):
        m=self.match()
        for extra in ({'x':99},{'hp':999},{'forward':float('nan')},{'yaw':float('inf')},{'forward':2},{'fire':1},{'seq':1.2}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):m.input(1,{'type':'input','seq':0,**extra},12)
        self.intent(m,forward=1);m.input(1,{'type':'input','seq':0,'forward':-1},12)
        self.assertEqual(m.players[1].intent['forward'],1)

    def test_speed_diagonal_stale_input_and_no_teleport(self):
        m=self.match();p=m.players[1];self.intent(m,forward=1,strafe=1)
        m.advance(12.05);self.assertAlmostEqual(math.hypot(p.x,p.z),4.5*STEP,5)
        previous=(p.x,p.z);m.advance(1000)
        self.assertEqual((p.x,p.z),previous,'Stale input cannot continue after a stalled browser')
        self.intent(m,forward=1);m.advance(1000.05)
        self.assertLess(math.dist(previous,(p.x,p.z)),.3,'Fixed dt cannot integrate a client-supplied time jump')

    def test_cover_blocks_movement_and_diagonal_slide(self):
        m=self.match();p=m.players[1];m.map['cover']=[dict(x=0,y=1,z=-1,w=5,h=2,d=.3)]
        for i in range(15):self.intent(m,forward=1,strafe=1);m.advance(12+(i+1)*STEP)
        self.assertGreater(p.x,1);self.assertGreater(p.z,-.41)

    def test_shot_ammo_cooldown_range_and_cover(self):
        m=self.match();p=m.players[1];q=m.players[2];p.slot='pistol';p.weapons={'pistol':12}
        m.map['cover']=[dict(x=0,y=1,z=-5,w=5,h=3,d=.3)];m.shoot(p)
        self.assertEqual(q.hp,100);self.assertEqual(p.weapons['pistol'],11)
        m.shoot(p);self.assertEqual(p.weapons['pistol'],11)
        m.map['cover']=[];m.clock+=1;m.shoot(p);self.assertLess(q.hp,100)
        old=q.hp;q.z=-200;m.clock+=1;m.shoot(p);self.assertEqual(q.hp,old)

    def test_shoulder_aim_converges_at_near_far_and_crouched_targets(self):
        for distance,crouch in ((6,False),(90,False),(18,True)):
            with self.subTest(distance=distance,crouch=crouch):
                m=self.match();m.rng.gauss=lambda *_:0;p=m.players[1];q=m.players[2]
                p.slot='rifle';p.weapons={'rifle':30};q.x=1.05;q.z=-distance
                self.intent(m,aim_x=q.x,aim_y=1.55,aim_z=q.z,crouch=crouch)
                m.shoot(p);self.assertLess(q.hp,100);self.assertEqual(p.weapons['rifle'],29)
                m.shoot(p);self.assertEqual(p.weapons['rifle'],29,'Aim cannot bypass cooldown')
                self.assertEqual(p.intent['yaw'],0,'Movement keeps the look direction')

    def test_aim_target_cannot_bypass_cover_or_range(self):
        m=self.match();m.rng.gauss=lambda *_:0;p=m.players[1];q=m.players[2]
        p.slot='pistol';p.weapons={'pistol':12};q.x=1;q.z=-20
        self.intent(m,aim_x=1,aim_y=1.55,aim_z=-20)
        m.map['cover']=[dict(x=.5,y=1.5,z=-5,w=4,h=3,d=.4)]
        m.shoot(p);self.assertEqual(q.hp,100)
        m.clock+=1;m.map['cover']=[];q.z=-200
        self.intent(m,aim_x=1,aim_y=1.55,aim_z=-200)
        m.shoot(p);self.assertEqual(q.hp,100)

    def test_aim_rejects_partial_nonfinite_backward_and_out_of_bounds(self):
        m=self.match()
        for point in ({'aim_x':0},{'aim_x':float('nan'),'aim_y':1,'aim_z':-10},
                      {'aim_x':0,'aim_y':1.55,'aim_z':10},
                      {'aim_x':0,'aim_y':1.55,'aim_z':0},
                      {'aim_x':1001,'aim_y':1,'aim_z':-10},{'aim_x':0,'aim_y':501,'aim_z':-10}):
            with self.subTest(point=point),self.assertRaises(ValueError):self.intent(m,**point)
        self.assertEqual(m.players[1].seq,-1,'Rejected aims must not consume a sequence')
        self.intent(m,pitch=1.2,aim_x=0,aim_y=280,aim_z=-110)
        self.assertIn('aim_point',m.players[1].intent,'Looking up with a long-range weapon remains valid')

    def test_continuous_body_hits_upper_chest_legs_and_crouched_body(self):
        for height,crouch in ((.2,False),(.85,False),(1.34,False),(1.0,True)):
            with self.subTest(height=height,crouch=crouch):
                m=self.match();m.rng.gauss=lambda *_:0;p=m.players[1];q=m.players[2]
                p.slot='pistol';p.weapons={'pistol':12};q.animation='crouch' if crouch else 'idle'
                self.intent(m,aim_x=0,aim_y=height,aim_z=-10);m.shoot(p)
                self.assertLess(q.hp,100,'Visible body regions must not contain a hitbox gap')
                self.assertEqual(p.weapons['pistol'],11)
        self.assertAlmostEqual(ray_capsule((0,3,0),(0,-1,0),0,0,.35,1.25,.34),1.41)
        self.assertIsNone(ray_capsule((2,1,0),(0,0,-1),0,-10,.35,1.25,.34))

    def moving_fixture(self):
        m=self.match();m.rng.gauss=lambda *_:0;p=m.players[1];q=m.players[2]
        p.slot='pistol';p.weapons={'pistol':12}
        for at,x in ((12.,-.9),(12.15,0),(12.30,.9)):
            m.clock=at;q.x=x;m.remember_positions()
        return m,p,q

    def view_intent(self,m,*,at=12.15,tick=123,receipts=True,**kwargs):
        packet=dict(type='input',seq=m.players[1].seq+1,fire=True,aim_x=0,aim_y=1.34,aim_z=-10,view_at=at,view_tick=tick,**kwargs)
        m.input(1,packet,m.clock,[(m.seed,123,12.15)] if receipts else ())

    def test_moving_target_hits_the_issued_rendered_position_without_relocating_it(self):
        m,p,q=self.moving_fixture();self.view_intent(m);m.shoot(p)
        self.assertEqual(q.hp,76);self.assertEqual(q.x,.9,'Rewind must never move a live actor')
        self.assertEqual(p.weapons['pistol'],11)
        m.shoot(p);self.assertEqual(p.weapons['pistol'],11,'Lag compensation must preserve cooldown')

    def test_rewind_needs_this_connections_round_and_a_recent_issued_view(self):
        for changes in ({'receipts':False},{'tick':999},{'at':11.5},{'at':12.29}):
            with self.subTest(changes=changes):
                m,p,q=self.moving_fixture();self.view_intent(m,**changes);m.shoot(p)
                self.assertEqual(q.hp,100);self.assertNotIn('view_at',p.intent)
        m,p,q=self.moving_fixture()
        packet=dict(type='input',seq=0,aim_x=0,aim_y=1.34,aim_z=-10,view_at=12.15,view_tick=123)
        m.input(1,packet,m.clock,[(m.seed+1,123,12.15)])
        self.assertNotIn('view_at',p.intent,'A prior round receipt cannot authorize a shot')

    def test_rewind_still_respects_cover_and_does_not_extend_its_window(self):
        m,p,q=self.moving_fixture();self.view_intent(m)
        m.map['cover']=[dict(x=0,y=1.5,z=-5,w=5,h=3,d=.3)];m.shoot(p);self.assertEqual(q.hp,100)
        m.map['cover']=[];m.clock=12.7;m.shoot(p);self.assertEqual(q.hp,100,'An old held intent cannot keep rewinding')
        for i in range(25):m.clock+=STEP;m.remember_positions()
        self.assertEqual(len(m.history),12,'History must remain bounded')

    def test_rewind_invalid_clock_metadata_is_rejected_without_consuming_input(self):
        for metadata in ({'view_at':12.15},{'view_at':float('nan'),'view_tick':123},
                         {'view_at':13,'view_tick':123},{'view_at':12.15,'view_tick':1.5}):
            m,p,q=self.moving_fixture()
            with self.subTest(metadata=metadata),self.assertRaises(ValueError):
                m.input(1,dict(type='input',seq=0,aim_x=0,aim_y=1.34,aim_z=-10,**metadata),m.clock,[(m.seed,123,12.15)])
            self.assertEqual(p.seq,-1)

    def test_helmet_and_armor_reduce_only_real_hits(self):
        m=self.match();p=m.players[2];p.helmet=True;p.armor=20
        m.damage(p,100,1,head=True)
        self.assertFalse(p.helmet);self.assertEqual(p.armor,0);self.assertEqual(p.hp,60)
        m.damage(p,100,source='zone');self.assertEqual(p.hp,0);self.assertEqual(p.rank,2)

    def test_same_tick_fire_can_trade_without_host_order_advantage(self):
        m=self.match();m.rng.gauss=lambda mean,spread:0
        for uid,yaw in ((1,0),(2,math.pi)):
            p=m.players[uid];p.hp=10;p.weapons={'pistol':12};p.slot='pistol'
            self.intent(m,uid,yaw=yaw,fire=True)
        m.advance(12.05)
        self.assertTrue(all(p.hp==0 and p.kills==1 and p.weapons['pistol']==11 and p.rank==1 for p in m.players.values()))
        self.assertEqual(m.phase,'finished');self.assertIsNone(m.winner)

    def test_short_trigger_survives_release_before_next_tick_without_extra_shots(self):
        m=self.match();p=m.players[1];p.slot='pistol';p.weapons={'pistol':12}
        self.intent(m,fire=True);self.intent(m,fire=False);m.advance(12.05)
        self.assertEqual(p.weapons['pistol'],11,'A press and release in the same tick must fire once')
        m.advance(12.10);self.assertEqual(p.weapons['pistol'],11)
        self.intent(m,fire=True);self.intent(m,fire=False);m.advance(12.15)
        self.assertEqual(p.weapons['pistol'],11,'Rapid taps must not bypass weapon cooldown')
        m.advance(12.60);self.assertEqual(p.weapons['pistol'],11,'A blocked tap must not fire later')
        self.intent(m,fire=True);self.intent(m,fire=False);m.advance(12.65)
        self.assertEqual(p.weapons['pistol'],10)
        self.intent(m,fire=True);self.intent(m,fire=False);m.advance(13.65)
        self.assertEqual(p.weapons['pistol'],10,'Expired trigger edges must not fire after a stall')

    def test_reload_and_heal_are_once_and_interruptible(self):
        m=self.match();p=m.players[1];p.slot='rifle';p.weapons={'rifle':2};p.reserve=10
        m.action(1,'reload');at=p.reload_at;m.action(1,'reload');self.assertEqual(p.reload_at,at)
        m.shoot(p);self.assertEqual(p.weapons['rifle'],2)
        m.advance(at);self.assertEqual((p.weapons['rifle'],p.reserve),(12,0))
        p.hp=30;m.action(1,'heal');at=p.heal_at;m.action(1,'heal');self.assertEqual(p.heal_at,at)
        m.damage(p,10,2);self.assertEqual(p.heal_at,0)
        m.action(1,'heal');m.advance(p.heal_at);self.assertEqual(p.medkits,0);self.assertEqual(p.hp,80)
        m.advance(m.clock+1);self.assertEqual(p.hp,80)

    def test_loot_distance_wall_and_two_weapon_limit(self):
        m=self.match();p=m.players[1];m.loot={1:dict(id=1,x=0,z=-2,kind='rifle')}
        m.map['cover']=[dict(x=0,y=1,z=-1,w=3,h=3,d=.2)];m.action(1,'pickup');self.assertFalse(p.weapons)
        m.map['cover']=[];m.clock+=1;m.action(1,'pickup');self.assertEqual(p.slot,'rifle');self.assertFalse(m.loot)
        for kind in ('smg','sniper'):
            m.spawn_loot(p.x,p.z,kind);m.clock+=1;m.action(1,'pickup')
        self.assertEqual(len(p.weapons),2);self.assertEqual(p.slot,'sniper')
        self.assertEqual([v['kind'] for v in m.loot.values()],['smg'])

    def test_grenade_single_charge_damage_and_cover(self):
        m=self.match();p=m.players[1];p.x=20;m.action(1,'grenade');m.action(1,'grenade')
        self.assertEqual(p.grenades,0);self.assertEqual(len(m.grenades),1)
        g=m.grenades[0];g.update(x=0,y=.2,z=-8,vx=0,vy=0,vz=0,at=12)
        m.advance(12.05);self.assertLess(m.players[2].hp,100);self.assertFalse(m.grenades)

    def test_disconnect_grace_and_return(self):
        m=self.match();p=m.players[1];p.connected=False;p.gone_at=12
        m.advance(36.9);self.assertEqual(p.hp,100)
        p.connected=True;p.gone_at=None;m.advance(39);self.assertEqual(p.hp,100)
        p.connected=False;p.gone_at=39;m.advance(64.1);self.assertEqual(p.hp,0);self.assertEqual(m.phase,'finished');self.assertEqual(m.winner,2)

    def test_zone_kills_and_final_survivor_or_explicit_draw(self):
        m=self.match();m.players[1].x=350;m.advance(200);self.assertLess(m.players[1].hp,100)
        m.damage(m.players[1],1000,source='zone');m.advance(201);self.assertEqual(m.winner,2)
        m=self.match();m.players[2].z=1;m.advance(400);self.assertEqual(m.phase,'finished');self.assertIsNone(m.winner)

    def test_snapshot_privacy_bounds_and_no_stale_projectiles(self):
        m=self.match();p=m.players[2];p.weapons={'sniper':1};p.reserve=19
        m.map['cover']=[dict(x=0,y=1,z=-5,w=20,h=4,d=.3)]
        m.event('shot',player=2,start=[0,1,-10],end=[0,1,0]);s=m.snapshot(1)
        self.assertEqual([p['id'] for p in s['players']],[1]);self.assertFalse([e for e in s['events'] if e['kind']=='shot'])
        self.assertNotIn('weapons',s['players'][0]);self.assertNotIn('reserve',s['players'][0])
        m.clock+=6;self.assertFalse(m.snapshot(2)['events'])

    def test_intersection_edges(self):
        b=dict(x=0,y=1,z=-5,w=2,h=2,d=2)
        self.assertEqual(ray_box((0,1,0),(0,0,-1),b,10),4)
        self.assertIsNone(ray_box((3,1,0),(0,0,-1),b,10))
        self.assertAlmostEqual(ray_sphere((0,1,0),(0,0,-1),(0,1,-5),1),4)


class IslandRooms(unittest.TestCase):
    def setUp(self):self.hub=battle.BattleHub(run=False)
    def test_duplicate_create_join_and_start_only_host(self):
        first=self.hub.create(1,'甲');self.assertEqual(self.hub.create(1,'甲'),first);code=first['code']
        self.assertEqual(self.hub.join(1,'甲',code),first);self.hub.join(2,'乙',code)
        class Sock:
            def shutdown(self,*a):pass
        a=battle.Peer(1,code,Sock());b=battle.Peer(2,code,Sock());self.hub.attach(a);self.hub.attach(b)
        with self.assertRaises(ValueError):self.hub.handle(b,dict(type='action',action='start'))
        self.hub.handle(a,dict(type='action',action='start'));self.hub.handle(a,dict(type='action',action='start'))
        self.assertEqual(len(self.hub.rooms[code].match.players),16)
        self.assertEqual(self.hub.list(1)['current'],code)

    def test_room_cap_and_disconnect_lease_replacement(self):
        for i in range(battle.MAX_ROOMS):self.hub.create(i+1,str(i))
        with self.assertRaises(ValueError):self.hub.create(99,'滿')
        code=self.hub.members[1]
        class Sock:
            def shutdown(self,*a):pass
        a=battle.Peer(1,code,Sock());b=battle.Peer(1,code,Sock());self.hub.attach(a);self.hub.attach(b);self.hub.detach(a)
        self.assertIs(self.hub.peers[1],b);self.assertTrue(self.hub.rooms[code].match.players[1].connected)
        self.assertEqual(a.controls.get()[1]['type'],'welcome');self.assertEqual(a.controls.get()[0],8)
        for i in range(100):b.snapshot({'tick':i})
        self.assertEqual(b.snapshots.qsize(),1);self.assertEqual(b.snapshots.get()['tick'],99)

    def test_join_rejects_running_and_leave_is_idempotent(self):
        code=self.hub.create(1,'甲')['code'];self.hub.rooms[code].match.start(time.monotonic())
        with self.assertRaises(ValueError):self.hub.join(2,'乙',code)
        self.hub.leave(1);self.hub.leave(1);self.assertFalse(self.hub.rooms);self.assertFalse(self.hub.members)

    def test_finished_participant_count_survives_a_player_leaving(self):
        code=self.hub.create(1,'甲')['code'];self.hub.join(2,'乙',code);match=self.hub.rooms[code].match
        match.start(0,False);match.advance(12);match.damage(match.players[2],1000,1);match.advance(12.05)
        self.hub.leave(2)
        self.assertEqual(match.snapshot(1)['total'],2);self.assertEqual(match.players[2].rank,2)
        self.assertEqual(self.hub.list(1)['rooms'][0]['humans'],1);self.assertNotIn(2,self.hub.members)
        other=self.hub.create(2,'乙')['code'];self.hub.leave(1)
        self.assertNotIn(code,self.hub.rooms);self.assertEqual(self.hub.members[2],other)

    def test_room_title_ai_validation_and_expiry(self):
        with self.assertRaises(ValueError):self.hub.create(1,'甲','x'*33)
        with self.assertRaises(ValueError):self.hub.create(1,'甲',bots='yes')
        code=self.hub.create(1,'甲')['code'];r=self.hub.rooms[code]
        self.hub.cleanup(r.touched+91);self.assertFalse(self.hub.rooms);self.assertFalse(self.hub.members)

    def test_host_reset_changes_round_identity_and_clears_combat_state(self):
        code=self.hub.create(1,'甲')['code'];self.hub.join(2,'乙',code)
        class Sock:
            def shutdown(self,*a):pass
        peer=battle.Peer(1,code,Sock());self.hub.attach(peer)
        self.hub.handle(peer,dict(type='action',action='start'));match=self.hub.rooms[code].match
        old=match.seed;match.phase='finished';match.players[1].hp=0;match.players[1].weapons={'rifle':1}
        self.hub.handle(peer,dict(type='action',action='reset'));match=self.hub.rooms[code].match
        self.assertNotEqual(match.snapshot(1)['round_id'],old);self.assertEqual(match.phase,'waiting')
        self.assertEqual(len(match.players),2);self.assertEqual(match.players[1].hp,100);self.assertFalse(match.players[1].weapons)

    def test_pack_supports_full_map_and_no_nan(self):
        value=Match(2).map;raw=battle.pack(value);self.assertEqual(raw[0],129)
        with self.assertRaises(ValueError):battle.pack({'x':float('nan')})


if __name__=='__main__':unittest.main()
