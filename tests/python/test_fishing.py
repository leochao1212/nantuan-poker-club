"""Fishing v2: real skill outcomes, shared collisions, immutable coins and migration."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from unittest.mock import patch
import copy,json,math,sqlite3,time,unittest
import fishing as f,fishing_gameplay as g,online,wallet,game_settings,member_accounts
from .test_app import ServerTestCase,Client

class FishingRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
        self.db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TEST');INSERT INTO users VALUES(1,'alice','Alice','2026');INSERT INTO users VALUES(2,'bob','Bob','2026');")
        online.initialize(self.db);f.initialize(self.db);self.serial=0;self.t=1792944000.
    def call(self,action,uid=1,clock=None,**fields):
        self.serial+=1;cfg=game_settings.current(self.db,'fishing')
        data=dict(operation_id='fishing_test_'+str(self.serial).zfill(8),**fields)
        if action not in ('sell','reel','shot'):data.setdefault('gameplay_version',6)
        if action in ('cast','burst'):data.setdefault('expected_revision',cfg['revision'])
        if action=='burst':data.setdefault('expected_limit_revision',cfg['bet_limit_revision'])
        if action=='cast':data.setdefault('power',100);data.setdefault('rod',0)
        return f.mutate(self.db,{'id':uid},action,data,self.t+self.serial if clock is None else clock)
    def burst(self,uid=1,clock=None,token=None,**fields):
        clock=self.t if clock is None else clock
        data=dict(room_id=1,cannon=0,stake=10,shots=[dict(token=token or 'projectile_'+str(self.serial).zfill(10),fired_at=clock,x=500,y=240)]);data.update(fields)
        return self.call('burst',uid,clock,**data)
    def single_fish(self,multiplier=2):
        self.db.execute('DELETE FROM fishing_entities');room=self.db.execute('SELECT * FROM fishing_rooms WHERE id=1').fetchone()
        fish=g.spawn(room,0,self.t,{'generation':self.serial});fish.update(x0=500,vx=0,y0=240,amplitude=0,phase=0,expires_at=self.t+100,species='sardine',multiplier=multiplier,base_multiplier=multiplier,growth_step=0)
        g._put_entity(self.db,1,fish);return fish

    def test_daily_skill_supply_taipei_boundary_and_immutable_replay(self):
        before=f.view(self.db,1,self.t);midnight=before['supply']['next_at']
        first=self.call('supply',clock=midnight-.1)
        self.assertTrue(first['result']['supply']['claimed'])
        self.assertEqual(first['state']['items'],dict(freeze=8,laser=3))
        self.assertEqual(first['state']['wallet']['balance'],before['wallet']['balance'])
        again=self.call('supply',clock=midnight-.01)
        self.assertFalse(again['result']['supply']['claimed'])
        self.assertEqual(again['state']['items'],first['state']['items'])
        op=first['result']['operation_id']
        replay=f.mutate(self.db,{'id':1},'supply',dict(gameplay_version=6,operation_id=op),midnight+.1)
        self.assertTrue(replay['replayed'])
        self.assertEqual(replay['state']['items'],first['state']['items'])
        self.assertFalse(replay['state']['supply']['claimed'])
        tomorrow=self.call('supply',clock=midnight+.1)
        self.assertEqual(tomorrow['state']['items'],dict(freeze=11,laser=4))
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_supplies').fetchone()[0],2)
        self.assertEqual(f.view(self.db,2,midnight+.1)['items'],dict(freeze=5,laser=2))
        self.assertFalse(f.view(self.db,2,midnight+.1)['supply']['claimed'])

    def test_supply_failure_rolls_back_claim_and_blocked_account_cannot_claim(self):
        import fishing_bonus
        with patch.object(fishing_bonus,'stock',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):self.call('supply',clock=self.t)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_supplies').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_operations').fetchone()[0],0)
        with self.assertRaises(f.RuleError):self.call('supply',clock=self.t,amount=999)
        self.db.execute("INSERT INTO account_states(user_id,status,revision,reason,changed_at) VALUES(1,'blocked',1,'test',0)")
        with self.assertRaises(member_accounts.AccountError):self.call('supply',clock=self.t)

    def test_private_shot_report_bounded_excludes_chain_and_unsettled_results(self):
        def add(uid,state,body):
            ident=self.db.execute('SELECT COALESCE(max(id),0)+1 FROM fishing_projectiles').fetchone()[0]
            return self.db.execute('INSERT INTO fishing_projectiles VALUES(?,?,?,?,?,?,?,?,?,?)',
                (ident,'report_'+str(ident),uid,1,'report_operation',self.t,self.t,self.t+1,state,g.encode(body))).lastrowid
        body=dict(stake=100,species='sardine',caught=True,gross=200,total_gross=500,multiplier=2,bonus_count=2)
        for _ in range(20):add(1,'caught',body)
        add(2,'caught',{**body,'total_gross':99999})
        add(1,'flying',{**body,'caught_ticket':'must_not_leak'})
        add(1,'caught',{**body,'source_id':1,'stake':0})
        hit=add(1,'hit',{**body,'caught':False,'gross':200,'total_gross':500})
        report=g.shot_history(self.db,1)
        self.assertEqual(len(report),12)
        self.assertEqual(report[0]['id'],hit)
        self.assertEqual((report[0]['gross'],report[0]['net']),(0,-100))
        self.assertEqual((report[1]['gross'],report[1]['net'],report[1]['chain']),(500,400,2))
        self.assertNotIn('caught_ticket',json.dumps(report))
        self.assertNotIn('99999',json.dumps(report))
        self.assertNotIn('recent_shots',g.room_view(self.db,1,self.t))
        plan=self.db.execute('EXPLAIN QUERY PLAN SELECT id FROM fishing_projectiles WHERE user_id=? ORDER BY id DESC LIMIT 48',(1,)).fetchall()
        self.assertIn('fishing_projectile_owner',str([tuple(r) for r in plan]))

    def test_oriented_geometry_and_frozen_motion_share_sprite_aspect(self):
        import fishing_geometry as geometry
        self.call('join',clock=self.t,room_id=1)
        room=self.db.execute('SELECT * FROM fishing_rooms WHERE id=1').fetchone()
        fish=g.spawn(room,0,self.t);fish.update(x0=500,y0=240,vx=1,amplitude=100,frequency=1,phase=0,radius_x=60,radius_y=15)
        angle=geometry.heading(fish,self.t);self.assertGreater(angle,1.5)
        self.assertTrue(geometry.collides(fish,500,240,500,290,0,self.t))
        self.assertFalse(geometry.collides(fish,500,240,550,240,0,self.t))
        self.assertTrue(geometry.beam_hit(fish,500,240,0,290,1,0,1000,0,self.t))
        self.assertFalse(geometry.beam_hit(fish,500,240,0,315,1,0,1000,0,self.t))
        self.assertFalse(geometry.beam_hit(fish,500,240,0,290,1,0,450,0,self.t))
        legacy={**fish,'geometry_version':1}
        self.assertTrue(geometry.collides(legacy,500,240,550,240,0,self.t))
        frozen=[dict(starts_at=self.t,ends_at=self.t+2,kind='freeze')]
        self.assertEqual(g.position(fish,self.t+1,frozen),g.position(fish,self.t))
        self.assertEqual(geometry.heading(fish,self.t+1,frozen),angle)
        for rid in range(1,7):
            r=self.db.execute('SELECT * FROM fishing_rooms WHERE id=?',(rid,)).fetchone()
            for slot in range(g.SLOTS):
                f=g.spawn(r,slot,self.t)
                if f['species'] in geometry.ART:self.assertAlmostEqual(f['radius_y']/f['radius_x'],geometry.ART[f['species']]['aspect'])

    def test_ammo_changes_actual_projectile_geometry_without_hidden_rng_trials(self):
        import fishing_power
        self.call('join',clock=self.t,room_id=1)
        shots=[self.burst(clock=self.t+i,stake=stake)['result']['shots'][0] for i,stake in enumerate((10,100,1000))]
        self.assertEqual([round(math.hypot(s['vx'],s['vy'])) for s in shots],[1150,1400,1650])
        self.assertEqual([s['radius'] for s in shots],[15,21,27])
        for s in shots:
            with patch.object(fishing_power.secrets,'randbelow',return_value=0) as draw:
                self.assertEqual(fishing_power.resolve(s,20),(1,s['stake']))
                draw.assert_called_once_with(20000000)

    def test_laser_chain_has_one_paid_shot_and_combined_probability_budget(self):
        self.call('join',clock=self.t,room_id=1);first=self.single_fish()
        ox,oy=g.origin(0);ux,uy=500-ox,240-oy;length=math.hypot(ux,uy);ux/=length;uy/=length
        for slot in range(1,6):
            other={**first,'id':'laser_extra_'+str(slot),'slot':slot,'x0':500+ux*slot*80,'y0':240+uy*slot*80,'feature':None}
            g._put_entity(self.db,1,other)
        self.call('skill',clock=self.t,room_id=1,kind='laser');self.burst()
        with patch.object(g.secrets,'randbelow',return_value=0) as draw:g.tick(self.db,self.t+1.5)
        draw.assert_called_once_with(8000000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],4)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='fishing_win'").fetchone()[0],1)
        self.assertEqual(f.view(self.db,1,self.t+2)['shots'],1)
        self.assertEqual(f.view(self.db,1,self.t+2)['returned'],80)
        g.tick(self.db,self.t+3)
        self.assertEqual(f.view(self.db,1,self.t+3)['returned'],80)

    def test_boss_multiplier_changes_at_capture_time_and_old_entities_stay_fixed(self):
        self.call('join',clock=self.t,room_id=1);fish=self.single_fish(200)
        fish.update(species='mermaid',feature='treasure',boss=True,growth_step=100,spawned_at=self.t-3.9)
        g._put_entity(self.db,1,fish)
        self.assertEqual(g.room_view(self.db,1,self.t)['entities'][0]['multiplier'],200)
        self.assertEqual(g.room_view(self.db,1,self.t+.2)['entities'][0]['multiplier'],300)
        self.burst(stake=100)
        with patch.object(g.secrets,'randbelow',return_value=0) as draw:g.tick(self.db,self.t+1.5)
        draw.assert_called_once_with(10000*(30000+3*631))
        paid=json.loads(self.db.execute('SELECT data FROM fishing_projectiles ORDER BY id LIMIT 1').fetchone()[0])
        self.assertEqual((paid['multiplier'],paid['gross']),(300,30000))
        self.assertEqual(g.fish_multiplier({'multiplier':200},self.t+100),200)

    def test_rooms_have_distinct_encounters_and_backgrounds(self):
        bosses=[]
        for rid in range(1,7):
            room=self.db.execute('SELECT * FROM fishing_rooms WHERE id=?',(rid,)).fetchone()
            bosses.append(g.spawn(room,g.SLOTS-1,self.t,boss=True)['species'])
        self.assertEqual(len(set(bosses)),6)
        self.assertEqual({g.room_view(self.db,rid,self.t)['theme'] for rid in range(1,7)},{'sea-board','sea-palace','sea-wreck'})

    def test_returning_to_idle_room_starts_with_fish_already_in_the_field(self):
        self.call('join',clock=self.t,room_id=1)
        self.db.execute('UPDATE fishing_entities SET expires_at=? WHERE room_id=1',(self.t-10,))
        g.prepare_room(self.db,1,self.t+1)
        entities=g.room_view(self.db,1,self.t+1)['entities']
        self.assertGreaterEqual(sum(0<g.position(f,self.t+1)[0]<1000 for f in entities),6)
    def hook(self,rod=0):
        cast=self.call('cast',clock=self.t,rod=rod);ident=cast['result']['cast_id'];at=cast['result']['ready_at']+.1
        return self.call('hook',clock=at,cast_id=ident)['state']['pending']
    def test_cast_privacy_timing_power_energy_no_reel_bypass(self):
        cast=self.call('cast',clock=self.t,power=900);pending=cast['state']['pending'];ident=pending['id']
        self.assertNotIn('species',pending);self.assertNotIn('species',cast['result']);self.assertEqual(cast['state']['free_casts'],17)
        self.assertEqual(cast['state']['wallet']['balance'],3000)
        with self.assertRaises(f.RuleError):self.call('reel',clock=self.t+5,cast_id=ident)
        with self.assertRaises(f.RuleError):self.call('hook',clock=self.t+1,cast_id=ident)
        with self.assertRaises(f.RuleError):self.call('hook',uid=2,clock=cast['result']['ready_at'],cast_id=ident)
        with self.assertRaises(f.RuleError):self.call('cast',clock=self.t+1)
        g.tick(self.db,pending['hook_deadline']+.1)
        state=f.view(self.db,1,pending['hook_deadline']+.1);self.assertIsNone(state['pending']);self.assertEqual(state['last_cast']['phase'],'escaped');self.assertEqual(state['bag_count'],0)
        self.assertEqual(sum(g.cast_option(100)['chances']),100)
        self.assertGreater(g.cast_option(900)['chances'][7],g.cast_option(100)['chances'][7])
        self.assertEqual(f.view(self.db,1,self.t+86400)['free_casts'],20)
    def test_real_control_can_catch_once_and_idle_escapes(self):
        game=self.hook(rod=1);clock=game['hooked_at'];ident=game['id'];last=None
        for i in range(180):
            clock+=.1;projection=copy.deepcopy(game);g.advance_skill(projection,clock)
            target=g.fish_y(game,clock+.16);holding=projection['zone_y']+projection['velocity']*.14>target
            last=self.call('input',clock=clock,cast_id=ident,sequence=game['sequence']+1,holding=holding)
            if not last['skill']['pending']:break
            game=last['skill']['pending']
        self.assertEqual(last['skill']['last_cast']['phase'],'caught');self.assertEqual(f.view(self.db,1,clock)['bag_count'],1)
        before=f.view(self.db,1,clock)['bag_value'];op=last['result']['operation_id']
        replay=f.mutate(self.db,{'id':1},'input',dict(gameplay_version=6,operation_id=op,cast_id=ident,sequence=last['result']['sequence'],holding=holding),clock+1)
        self.assertTrue(replay['replayed']);g.tick(self.db,clock+10);self.assertEqual(f.view(self.db,1,clock+10)['bag_count'],1)
        sale=self.call('sell',clock=clock+10);self.assertEqual(sale['state']['wallet']['balance'],3000+before);self.assertEqual(sale['state']['discovered'],1)
        cast=self.call('cast',clock=clock+11);at=cast['result']['ready_at'];self.call('hook',clock=at,cast_id=cast['result']['cast_id']);g.tick(self.db,at+24)
        self.assertEqual(f.view(self.db,1,at+24)['last_cast']['phase'],'escaped')
    def test_simulation_tick_partition_is_frame_independent(self):
        pending=self.hook();a=copy.deepcopy(pending);b=copy.deepcopy(pending)
        g.advance_skill(a,a['hooked_at']+4)
        for i in range(80):g.advance_skill(b,b['hooked_at']+(i+1)*.05)
        for k in ('phase','progress','escape','zone_y','velocity'):self.assertEqual(a[k],b[k])
    def test_rods_are_functional_and_input_sequence_strict(self):
        game=self.hook(2);self.assertEqual(game['width'],g.RODS[2]['width']);self.assertEqual(game['rate'],1.25)
        for fields in ({'sequence':2,'holding':True},{'sequence':1,'holding':1},{'sequence':True,'holding':False}):
            with self.assertRaises(f.RuleError):self.call('input',clock=game['hooked_at']+.1,cast_id=game['id'],**fields)
        with self.assertRaises(f.RuleError):self.call('input',clock=game['hooked_at']+.01,cast_id=game['id'],sequence=1,holding=True)
        self.call('gear',rod=1,cannon=2);self.assertEqual(f.view(self.db,1,self.t+10)['loadout'],dict(rod=1,cannon=2))
    def test_shared_fish_one_capture_no_sellable_stock_and_ledger(self):
        self.call('join',clock=self.t,room_id=1);self.call('join',uid=2,clock=self.t,room_id=1);fish=self.single_fish()
        for uid in (1,2):self.burst(uid=uid)
        with patch.object(g.secrets,'randbelow',return_value=0):g.tick(self.db,self.t+1.5)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures WHERE fish_id=?',(fish['id'],)).fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT sum(returned),sum(spent) FROM fishing_stats').fetchone()[:],(20,20))
        self.assertEqual(sum(f.view(self.db,u,self.t+2)['bag_count'] for u in (1,2)),0)
        g.tick(self.db,self.t+2);self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],1)
        totals=self.db.execute("SELECT sum(game_delta),sum(flow_delta) FROM wealth_events WHERE kind LIKE 'fishing_%'").fetchone();self.assertEqual(totals[:],(0,0))
    def test_conditional_odds_exact_boundaries_and_real_miss(self):
        for multiplier in (2,3,5,8,12,20,35,60,70):
            self.assertEqual(Fraction(9500,10000*multiplier)*multiplier,Fraction(95,100))
        for j,(ticket,caught) in enumerate(((0,True),(949999,True),(950000,False),(1999999,False))):
            clock=self.t+j*3;self.call('join',clock=clock,room_id=1);self.single_fish();self.burst(clock=clock)
            with patch.object(g.secrets,'randbelow',return_value=ticket):g.tick(self.db,clock+1.5)
            last=self.db.execute('SELECT state,data FROM fishing_projectiles ORDER BY id DESC LIMIT 1').fetchone();self.assertEqual(last['state'],'caught' if caught else 'hit')
        self.db.execute('DELETE FROM fishing_entities');clock=self.t+15;self.burst(clock=clock);g.tick(self.db,clock+1.5)
        self.assertEqual(self.db.execute('SELECT state FROM fishing_projectiles ORDER BY id DESC LIMIT 1').fetchone()[0],'miss')
    def test_batch_idempotency_conflict_cadence_balance_and_validations(self):
        self.call('join',clock=self.t,room_id=1);first=self.burst();op=first['result']['operation_id']
        self.assertTrue(first['state']['partial']);self.assertNotIn('catalog',first['state']);self.assertEqual(first['state']['wallet']['balance'],2990)
        data=dict(operation_id=op,gameplay_version=6,room_id=1,cannon=0,stake=10,expected_revision=1,expected_limit_revision=1,shots=[dict(token='projectile_0000000001',fired_at=self.t,x=500,y=240)])
        self.assertTrue(f.mutate(self.db,{'id':1},'burst',data,self.t+20)['replayed'])
        with self.assertRaises(f.RuleError):f.mutate(self.db,{'id':1},'burst',{**data,'stake':6},self.t+20)
        with self.assertRaises(f.RuleError):self.burst(clock=self.t+.1)
        for change in ({'stake':True},{'stake':101},{'cannon':4},{'expected_revision':0},{'expected_limit_revision':True},{'room_id':2},{'shots':[]},{'gross':999}):
            fields={**data,**change,'operation_id':'invalid_fishing_'+str(self.serial).zfill(8)};self.serial+=1
            with self.assertRaises(f.RuleError):f.mutate(self.db,{'id':1},'burst',fields,self.t+.5)
        self.db.execute('UPDATE wallets SET balance=0 WHERE user_id=1')
        with self.assertRaises(f.RuleError):self.burst(clock=self.t+1)
        self.assertEqual(f.view(self.db,1,self.t+1)['shots'],1)
    def test_freeze_shared_motion_cooldown_survives_rejoin_and_lease(self):
        self.call('join',clock=self.t,room_id=1);self.call('skill',clock=self.t,room_id=1)
        world=g.room_view(self.db,1,self.t);fish=world['entities'][0]
        self.assertEqual(g.position(fish,self.t,world['effects']),g.position(fish,self.t+1.5,world['effects']))
        self.call('leave',clock=self.t+3);self.call('join',clock=self.t+3,room_id=2)
        with self.assertRaises(f.RuleError):self.call('skill',clock=self.t+3,room_id=2)
        self.call('skill',clock=self.t+31,room_id=2);g.tick(self.db,self.t+75)
        self.assertIsNone(f.view(self.db,1,self.t+75)['member'])
    def test_migration_keeps_old_pending_cast_and_immutable_receipt(self):
        ident='a'*32;op='old_fishing_cast_001';result=dict(action='cast',operation_id=op,at=self.t,cast_id=ident,ready_at=self.t+3)
        self.db.execute('INSERT INTO fishing_casts(id,user_id,day,species,size_cm,ready_at,created_at) VALUES(?,?,?,?,?,?,?)',(ident,1,wallet.day(self.t),'goldfish',80,self.t+3,self.t))
        self.db.execute('INSERT INTO fishing_operations VALUES(?,?,?,?,?)',(1,op,f._intent('cast',{'expected_revision':1}),g.encode(result),self.t))
        f.initialize(self.db);f.initialize(self.db)
        replay=f.mutate(self.db,{'id':1},'cast',dict(operation_id=op,expected_revision=1),self.t+10);self.assertTrue(replay['replayed']);self.assertEqual(replay['state']['pending']['version'],1)
        self.call('reel',clock=self.t+10,cast_id=ident);sale=self.call('sell',clock=self.t+11);self.assertEqual(sale['result']['amount'],100)
        with self.assertRaises(f.RuleError):self.call('shot',species='sardine',stake=1)
    def test_credit_failure_rolls_back_resolution_without_losing_paid_projectile(self):
        self.call('join',clock=self.t,room_id=1);self.single_fish();self.burst();self.db.commit()
        original=wallet.transfer
        def fail(db,uid,amount,*args,**kwargs):
            if amount>0:raise RuntimeError('simulated credit failure')
            return original(db,uid,amount,*args,**kwargs)
        with patch.object(g.secrets,'randbelow',return_value=0),patch.object(wallet,'transfer',side_effect=fail):
            with self.assertRaises(RuntimeError):
                with self.db:g.tick(self.db,self.t+1.5)
        self.assertEqual(f.view(self.db,1,self.t+2)['wallet']['balance'],2990)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT state FROM fishing_projectiles').fetchone()[0],'flying')
        with patch.object(g.secrets,'randbelow',return_value=0):
            with self.db:g.tick(self.db,self.t+1.5)
        self.assertEqual(f.view(self.db,1,self.t+2)['wallet']['balance'],3010)
        self.assertEqual(f.view(self.db,1,self.t+2)['shots'],1)

    def test_restart_resolves_paid_shots_before_expired_world_is_replaced(self):
        self.call('join',clock=self.t,room_id=1);fish=self.single_fish();self.burst();self.db.commit()
        f.initialize(self.db)
        with patch.object(g.secrets,'randbelow',return_value=0):g.tick(self.db,self.t+120)
        self.assertEqual(self.db.execute('SELECT fish_id FROM fishing_captures').fetchone()[0],fish['id'])
        self.assertEqual(f.view(self.db,1,self.t+120)['returned'],20)
        g.tick(self.db,self.t+121);self.assertEqual(f.view(self.db,1,self.t+121)['wallet']['balance'],3010)

    def test_cannon_pricing_exact_ev_all_stakes_with_bonus_budget(self):
        import fishing_power,fishing_bonus
        mean=sum(Fraction(p['multiplier']*p['weight'],100) for p in fishing_bonus.POOL)
        self.assertEqual(mean,Fraction(631,100))
        for multiplier in (2,20,60,1000):
            for stake in (10,100,1000):
                for count in (0,3,5):
                    expected=multiplier+count*mean
                    p=Fraction(9500*100,10000*(multiplier*100+count*631))
                    self.assertEqual(p*stake*expected,stake*Fraction(95,100))
                    for ticket,hits in ((0,1),(949999,1),(950000,0)):
                        shot=dict(pricing='cannon-v1',power=stake//10,stake=stake,target_bps=9500)
                        with patch.object(fishing_power.secrets,'randbelow',return_value=ticket) as draw:
                            self.assertEqual(fishing_power.resolve(shot,multiplier,count*631),(hits,stake*hits))
                            draw.assert_called_once_with(10000*(multiplier*100+count*631))
        # Accepted v4 attack packs retain their exact, old number of trials.
        with patch.object(fishing_power.secrets,'randbelow',side_effect=[0,9499,9500]+[9500]*97) as draw:
            self.assertEqual(fishing_power.resolve(dict(power=100,stake=1000,target_bps=9500),60),(2,20))
            self.assertEqual(draw.call_count,100);draw.assert_called_with(600000)

    def test_treasure_capture_snapshot_owner_restart_replay_and_ledger(self):
        import fishing_bonus
        self.call('join',clock=self.t,room_id=1);fish=self.single_fish(multiplier=20);fish.update(species='chest',feature='chest');g._put_entity(self.db,1,fish)
        shot=self.burst(stake=100)
        with patch.object(g.secrets,'randbelow',return_value=0) as draw:g.tick(self.db,self.t+1.5)
        draw.assert_called_once_with(10000*(2000+3*631))
        pending=f.view(self.db,1,self.t+2)['bonuses'];self.assertEqual(len(pending),1);event=pending[0];self.assertNotIn('draws',event)
        self.assertEqual(f.view(self.db,1,self.t+2)['wallet']['balance'],4900)
        self.assertEqual(f.view(self.db,2,self.t+2)['bonuses'],[])
        with self.assertRaises(f.RuleError):self.call('bonus',uid=2,clock=self.t+2,bonus_id=event['id'])
        for invalid in (None,[],1,'no'):
            with self.assertRaises(f.RuleError):self.call('bonus',clock=self.t+2,bonus_id=invalid)
        f.initialize(self.db);self.assertEqual(f.view(self.db,1,self.t+2)['bonuses'][0],event)
        # Later admin/pool changes cannot rewrite an earned event.
        with patch.object(fishing_bonus,'POOL',[dict(multiplier=999,weight=100)]),patch.object(fishing_bonus.secrets,'randbelow',side_effect=[0,30,99,1]):
            reply=self.call('bonus',clock=self.t+3,bonus_id=event['id'])
        result=reply['result']['bonus'];self.assertEqual(result['draws'],[2,3,100]);self.assertEqual(result['gross'],10500)
        self.assertEqual(reply['state']['wallet']['balance'],15400);self.assertEqual(reply['state']['items'],dict(freeze=5,laser=3))
        op=reply['result']['operation_id'];replay=f.mutate(self.db,{'id':1},'bonus',dict(operation_id=op,gameplay_version=6,bonus_id=event['id']),self.t+4)
        self.assertTrue(replay['replayed']);self.assertEqual(replay['result']['bonus'],result)
        self.assertEqual(self.call('bonus',clock=self.t+5,bonus_id=event['id'])['result']['bonus'],result)
        self.assertEqual(f.view(self.db,1,self.t+5)['wallet']['balance'],15400)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE event_key=?",('fish:bonus:'+event['id'],)).fetchone()[0],1)
        self.assertEqual(f.view(self.db,1,self.t+5)['returned'],12500)
        self.assertEqual(f.view(self.db,1,self.t+5)['bonuses'],[])

    def test_bonus_rollback_and_inventory_cannot_be_replenished_by_rejoin(self):
        import fishing_bonus
        self.call('join',clock=self.t,room_id=1)
        ident=fishing_bonus.create(self.db,1,'synthetic',100,fishing_bonus.rules('whale'),self.t)
        before=f.view(self.db,1,self.t)
        with patch.object(fishing_bonus.wallet,'transfer',side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError):self.call('bonus',clock=self.t+1,bonus_id=ident)
        self.assertEqual(f.view(self.db,1,self.t+1)['bonuses'],before['bonuses']);self.assertEqual(f.view(self.db,1,self.t+1)['wallet']['balance'],3000)
        for index in range(2):
            at=self.t+index*46;self.call('join',clock=at,room_id=1);reply=self.call('skill',clock=at,room_id=1,kind='laser')
            self.assertEqual(reply['state']['items']['laser'],1-index)
        self.call('join',clock=self.t+92,room_id=1)
        with self.assertRaises(f.RuleError):self.call('skill',clock=self.t+92,room_id=1,kind='laser')
        self.assertEqual(f.view(self.db,1,self.t+92)['items']['laser'],0)

    def test_pending_v4_pack_keeps_old_settlement(self):
        self.call('join',clock=self.t,room_id=1);self.single_fish(multiplier=2);self.burst(stake=100)
        row=self.db.execute('SELECT id,data FROM fishing_projectiles').fetchone();old=json.loads(row['data']);old.pop('pricing');old.pop('bonus_rules')
        self.db.execute('UPDATE fishing_projectiles SET data=? WHERE id=?',(g.encode(old),row['id']))
        with patch.object(g.secrets,'randbelow',side_effect=[0,0]+[9500]*8) as draw:g.tick(self.db,self.t+1.5)
        self.assertEqual(draw.call_count,10);self.assertEqual(f.view(self.db,1,self.t+2)['returned'],40)

    def test_heavy_ammo_critical_one_capture_one_credit_and_limit_snapshot(self):
        self.call('join',clock=self.t,room_id=1);fish=self.single_fish()
        shot=self.burst(stake=1000);self.assertEqual(shot['result']['cost'],1000);self.assertEqual(shot['result']['shots'][0]['power'],100)
        self.db.execute("UPDATE game_settings SET params=?,revision=revision+1 WHERE game_type='limits'",(g.encode({'max_bet':100}),))
        self.assertEqual([a['stake'] for a in f.view(self.db,1,self.t)['ammo']],[10,100])
        with self.assertRaises(f.RuleError):self.burst(clock=self.t+.5,stake=1000)
        with patch.object(g.secrets,'randbelow',return_value=0):g.tick(self.db,self.t+1.5)
        row=self.db.execute('SELECT data FROM fishing_projectiles ORDER BY id LIMIT 1').fetchone();data=json.loads(row[0])
        self.assertEqual((data['critical'],data['gross'],data['total_gross']),(1,2000,2000))
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures WHERE fish_id=?',(fish['id'],)).fetchone()[0],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='fishing_win'").fetchone()[0],1)
        self.assertEqual(f.view(self.db,1,self.t+2)['wallet']['balance'],4000)
        g.tick(self.db,self.t+3);self.assertEqual(f.view(self.db,1,self.t+3)['wallet']['balance'],4000)
    def test_laser_geometry_snapshot_cooldown_and_freeze_are_independent(self):
        self.call('join',clock=self.t,room_id=1);fish=self.single_fish()
        result=self.call('skill',clock=self.t,room_id=1,kind='laser')
        self.assertEqual(result['result']['ends_at'],self.t+6)
        world=g.room_view(self.db,1,self.t);moving={**fish,'vx':10}
        self.assertNotEqual(g.position(moving,self.t,world['effects']),g.position(moving,self.t+1,world['effects']))
        shot=self.burst(clock=self.t+.1,stake=100)['result']['shots'][0]
        self.assertTrue(shot['laser']);self.assertAlmostEqual(math.hypot(shot['vx'],shot['vy']),1800);self.assertEqual(shot['radius'],g.CANNONS[0]['radius']+6+12)
        self.call('skill',clock=self.t+.2,room_id=1,kind='freeze')
        with self.assertRaises(f.RuleError):self.call('skill',clock=self.t+1,room_id=1,kind='laser')
        with self.assertRaises(f.RuleError):self.call('skill',clock=self.t+1,room_id=1,kind='unknown')
        self.call('leave',clock=self.t+2);self.call('join',clock=self.t+2,room_id=2)
        with self.assertRaises(f.RuleError):self.call('skill',clock=self.t+3,room_id=2,kind='laser')
        self.assertFalse(self.burst(clock=self.t+7,room_id=2)['result']['shots'][0]['laser'])
        self.assertEqual(json.loads(self.db.execute('SELECT data FROM fishing_projectiles ORDER BY id LIMIT 1').fetchone()[0])['radius'],33)
    def test_four_seat_migration_preserves_all_twenty_four_members(self):
        for uid in range(3,25):self.db.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,str(uid),'Player'+str(uid),'2026'))
        for uid in range(1,25):
            self.db.execute('INSERT INTO fishing_members VALUES(?,?,?,?,?)',(uid,(uid-1)//6+1,(uid-1)%6,self.t,self.t+30))
            self.db.execute('INSERT INTO fishing_cooldowns(user_id,ready_at,laser_at) VALUES(?,?,?)',(uid,self.t+30,self.t+45))
        f.initialize(self.db);f.initialize(self.db)
        members=self.db.execute('SELECT * FROM fishing_members').fetchall();self.assertEqual(len(members),24)
        self.assertTrue(all(m['seat']<4 and 1<=m['room_id']<=6 and m['skill_at']==self.t+30 for m in members))
        self.assertEqual(len({(m['room_id'],m['seat']) for m in members}),24)
        self.assertEqual(self.db.execute('SELECT min(laser_at) FROM fishing_cooldowns').fetchone()[0],self.t+45)
    def test_pending_v3_projectile_keeps_original_payout_after_upgrade(self):
        self.call('join',clock=self.t,room_id=1);self.single_fish();self.burst(stake=1000)
        row=self.db.execute('SELECT id,data FROM fishing_projectiles').fetchone();old=json.loads(row['data']);old.pop('power');old.pop('laser');old.pop('pricing');old.pop('bonus_rules');self.db.execute('UPDATE fishing_projectiles SET data=? WHERE id=?',(g.encode(old),row['id']))
        with patch.object(g.secrets,'randbelow',return_value=0) as draw:g.tick(self.db,self.t+1.5)
        draw.assert_called_once_with(20000)
        self.assertEqual(f.view(self.db,1,self.t+2)['returned'],2000)

    def tension_hook(self):
        cast=self.call('cast',clock=self.t,mechanic='tension',lure='sardine');at=cast['result']['ready_at']+.05
        return self.call('hook',clock=at,cast_id=cast['result']['cast_id'])['state']['pending']
    def test_tension_button_and_slider_catch_credit_once(self):
        import fishing_tension
        for slider in (False,True):
            game=self.tension_hook();clock=game['hooked_at'];before=f.view(self.db,1,clock)['wallet']['balance']
            for i in range(200):
                clock+=.15;project=copy.deepcopy(game);g.advance_skill(project,clock)
                holding=project['tension']<.5;fields={}
                if slider:fields['control']=max(0,min(1000,round(1000*(fishing_tension.pull(game,clock)/.62+(.5-project['tension'])*2))))
                result=self.call('input',clock=clock,cast_id=game['id'],sequence=game['sequence']+1,holding=holding,**fields)
                if not result['skill']['pending']:break
                game=result['skill']['pending']
            final=result['skill']['last_cast'];self.assertEqual(final['phase'],'caught');self.assertGreater(final['score'],0);self.assertGreaterEqual(final['stars'],1)
            state=f.view(self.db,1,clock);self.assertEqual(state['bag_count'],0);self.assertEqual(state['wallet']['balance'],before+2)
            op=result['result']['operation_id'];data=dict(gameplay_version=6,operation_id=op,cast_id=game['id'],sequence=result['result']['sequence'],holding=holding,**fields)
            self.assertTrue(f.mutate(self.db,{'id':1},'input',data,clock+1)['replayed']);g.tick(self.db,clock+1)
            self.assertEqual(f.view(self.db,1,clock+1)['wallet']['balance'],before+2)
            self.t=clock+2
    def test_tension_too_loose_or_tight_fails_and_slider_is_validated(self):
        game=self.tension_hook()
        for value in (-1,1001,True,'500'):
            with self.assertRaises(f.RuleError):self.call('input',clock=game['hooked_at']+.15,cast_id=game['id'],sequence=1,holding=True,control=value)
        g.tick(self.db,game['hooked_at']+31);last=f.view(self.db,1,game['hooked_at']+31)['last_cast'];self.assertEqual(last['phase'],'escaped');self.assertEqual(f.view(self.db,1,self.t+40)['wallet']['balance'],3000)
        self.t+=40;game=self.tension_hook();clock=game['hooked_at']
        for i in range(60):
            clock+=.3;result=self.call('input',clock=clock,cast_id=game['id'],sequence=game['sequence']+1,holding=True)
            if not result['skill']['pending']:break
            game=result['skill']['pending']
        self.assertEqual(result['skill']['last_cast']['phase'],'escaped');self.assertIn('高',result['skill']['last_cast']['reason'])
    def test_tension_lure_cost_and_read_only_snapshot_does_not_pretend_credit(self):
        cast=self.call('cast',clock=self.t,mechanic='tension',lure='goldfish');self.assertEqual(cast['state']['free_casts'],17)
        ready=cast['result']['ready_at'];game=self.call('hook',clock=ready,cast_id=cast['result']['cast_id'])['state']['pending']
        self.assertEqual(f.view(self.db,1,ready+50)['pending']['phase'],'playing')
        g.tick(self.db,ready+50);self.assertIsNone(f.view(self.db,1,ready+50)['pending'])
        with self.assertRaises(f.RuleError):self.call('cast',clock=ready+51,mechanic='tension',lure='crab')
    def test_bonus_chain_unique_capture_and_total_payout_odds(self):
        self.call('join',clock=self.t,room_id=1);self.call('join',uid=2,clock=self.t,room_id=1);boss=self.single_fish(multiplier=80);boss.update(species='crab',feature='bomb',boss=True,radius_x=80,radius_y=60);g._put_entity(self.db,1,boss)
        for slot,species,mult in ((1,'sardine',2),(2,'clownfish',3)):
            other={**boss,'id':'bonus_target_'+str(slot),'slot':slot,'species':species,'multiplier':mult,'base_multiplier':mult,'x0':500+slot*70,'y0':100,'feature':None,'boss':False};g._put_entity(self.db,1,other)
        self.burst(uid=1);self.burst(uid=2)
        with patch.object(g.secrets,'randbelow',return_value=0) as random:g.tick(self.db,self.t+1.5)
        random.assert_called_once_with(85000000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],3)
        self.assertEqual(self.db.execute('SELECT sum(returned),sum(spent),sum(shots) FROM fishing_stats').fetchone()[:],(850,20,2))
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='fishing_win'").fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT sum(gross) FROM fishing_captures').fetchone()[0],850)
        g.tick(self.db,self.t+2);self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],3)

    def test_completed_old_receipts_replay_but_stale_new_shots_cannot_spend(self):
        self.call('join',clock=self.t,room_id=1);result=self.burst();op=result['result']['operation_id']
        row=self.db.execute('SELECT fingerprint FROM fishing_operations WHERE operation_id=?',(op,)).fetchone();fingerprint=json.loads(row[0])
        for version in (2,3,4,5):
            fingerprint['gameplay_version']=version
            self.db.execute('UPDATE fishing_operations SET fingerprint=? WHERE operation_id=?',(g.encode(fingerprint),op))
            data={k:v for k,v in fingerprint.items() if k!='action'};data['operation_id']=op
            self.assertTrue(f.mutate(self.db,{'id':1},'burst',data,self.t+5)['replayed'])
            with self.assertRaises(f.RuleError):f.mutate(self.db,{'id':1},'burst',{**data,'operation_id':'stale_new_shot_000001'},self.t+5)
        self.assertEqual(f.view(self.db,1,self.t+5)['wallet']['balance'],2990)
    def test_dynamic_boss_ranges_and_laser_receipt_replay(self):
        room=self.db.execute('SELECT * FROM fishing_rooms WHERE id=1').fetchone();seen=set()
        for i in range(30):
            boss=g.spawn(room,17,120*(100+i),boss=True);fish=f.BY_ID[boss['species']];seen.add(boss['species'])
            self.assertIn(boss['multiplier'],[fish['multiplier']+j*fish.get('bonus_step',0) for j in range(5)])
        self.assertEqual(seen,{'crab','octopus','eel','dragon','mermaid','whale'})
        self.call('join',clock=self.t,room_id=1);reply=self.call('skill',clock=self.t,room_id=1,kind='laser');op=reply['result']['operation_id']
        replay=f.mutate(self.db,{'id':1},'skill',dict(gameplay_version=6,operation_id=op,room_id=1,kind='laser'),self.t+1)
        self.assertTrue(replay['replayed']);self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_effects').fetchone()[0],1)

    def test_blocked_account_cannot_enter_or_shoot(self):
        self.db.execute("INSERT INTO account_states(user_id,status,revision,reason,changed_at) VALUES(1,'blocked',1,'test',0)")
        with self.assertRaises(member_accounts.AccountError):self.call('cast')

class FishingAPI(ServerTestCase):
    def test_twenty_concurrent_players_replay_and_private_state(self):
        a=self.clients[0];self.assertEqual(a.call('/api/fishing?version=6')[0],401)
        self.assertEqual(a.call('/api/register',dict(username='angler_0',nickname='Fishing',password='SyntheticFishing123'))[0],200)
        self.assertEqual(a.call('/api/fishing')[0],426)
        invite=a.call('/api/state')[1]['invite_code'];people=[a]
        for i in range(1,20):
            client=Client(self.base);self.assertEqual(client.call('/api/register',dict(username='angler_'+str(i),nickname='Angler'+str(i),password='SyntheticFishing123',invite_code=invite))[0],200);people.append(client)
        def join(pair):
            i,c=pair;return c.call('/api/fishing/join',dict(gameplay_version=6,operation_id='http_join_'+str(i).zfill(12),room_id=i//4+1))
        with ThreadPoolExecutor(20) as pool:joined=list(pool.map(join,enumerate(people)))
        self.assertTrue(all(s==200 for s,r in joined),joined)
        self.assertEqual(a.call('/api/fishing/join',dict(gameplay_version=6,operation_id='http_full_room_0001',room_id=2))[0],400)
        def burst(pair):
            i,c=pair;return c.call('/api/fishing/burst',dict(gameplay_version=6,operation_id='http_burst_00000001',room_id=i//4+1,cannon=0,stake=10,expected_revision=1,expected_limit_revision=1,shots=[dict(token='http_token_'+str(i).zfill(12),fired_at=time.time(),x=500,y=240)]))
        with ThreadPoolExecutor(8) as pool:
            supplies=list(pool.map(lambda i:a.call('/api/fishing/supply',dict(gameplay_version=6,operation_id='supply_parallel_'+str(i).zfill(8))),range(8)))
        self.assertTrue(all(status==200 for status,_ in supplies),supplies)
        self.assertEqual(sum(reply['result']['supply']['claimed'] for _,reply in supplies),1)
        self.assertEqual(a.call('/api/fishing?version=6')[1]['items'],dict(freeze=8,laser=3))
        started=time.monotonic()
        with ThreadPoolExecutor(20) as pool:responses=list(pool.map(burst,enumerate(people)))
        self.assertTrue(all(s==200 for s,r in responses),responses);self.assertLess(time.monotonic()-started,8)
        i=0;data=dict(gameplay_version=6,operation_id='http_burst_00000001',room_id=1,cannon=0,stake=10,expected_revision=1,expected_limit_revision=1,shots=[dict(token='http_token_'+str(i).zfill(12),fired_at=responses[0][1]['result']['shots'][0]['born_at'],x=500,y=240)])
        with closing(sqlite3.connect(self.db_path)) as db:
            fingerprint=json.loads(db.execute("SELECT fingerprint FROM fishing_operations WHERE user_id=1 AND operation_id='http_burst_00000001'").fetchone()[0]);data.update({k:v for k,v in fingerprint.items() if k!='action'})
        self.assertEqual(a.call('/api/fishing/burst',data,origin='https://foreign.invalid')[0],403)
        with ThreadPoolExecutor(8) as pool:replays=list(pool.map(lambda _:a.call('/api/fishing/burst',data),range(8)))
        self.assertTrue(all(s==200 and r['replayed'] for s,r in replays),replays)
        self.assertEqual(a.call('/api/fishing?version=6')[1]['shots'],1)
        world=a.call('/api/fishing/world?room=1')[1];self.assertEqual(len(world['players']),4);self.assertEqual(len(world['entities']),18)
        self.assertNotIn('wallet',world);self.assertNotIn('seed',json.dumps(world))
        # Public paths and already fired settings are public; no future capture tickets.
        self.assertNotIn('caught_ticket',json.dumps(world));self.assertNotIn('bonus_rules',json.dumps(world));self.assertNotIn('pending',world)
        with closing(sqlite3.connect(self.db_path)) as db:self.assertEqual(db.execute('SELECT sum(shots),sum(spent) FROM fishing_stats').fetchone(),(20,200))
