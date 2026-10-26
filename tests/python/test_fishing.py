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
        if action not in ('sell','reel','shot'):data.setdefault('gameplay_version',3)
        if action in ('cast','burst'):data.setdefault('expected_revision',cfg['revision'])
        if action=='burst':data.setdefault('expected_limit_revision',cfg['bet_limit_revision'])
        if action=='cast':data.setdefault('power',100);data.setdefault('rod',0)
        return f.mutate(self.db,{'id':uid},action,data,self.t+self.serial if clock is None else clock)
    def burst(self,uid=1,clock=None,token=None,**fields):
        clock=self.t if clock is None else clock
        return self.call('burst',uid,clock,room_id=1,cannon=0,stake=5,shots=[dict(token=token or 'projectile_'+str(self.serial).zfill(10),fired_at=clock,x=500,y=240)],**fields)
    def single_fish(self,multiplier=2):
        self.db.execute('DELETE FROM fishing_entities');room=self.db.execute('SELECT * FROM fishing_rooms WHERE id=1').fetchone()
        fish=g.spawn(room,0,self.t,{'generation':self.serial});fish.update(x0=500,vx=0,y0=240,amplitude=0,phase=0,expires_at=self.t+100,species='sardine',multiplier=multiplier)
        g._put_entity(self.db,1,fish);return fish
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
        replay=f.mutate(self.db,{'id':1},'input',dict(gameplay_version=3,operation_id=op,cast_id=ident,sequence=last['result']['sequence'],holding=holding),clock+1)
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
        self.assertEqual(self.db.execute('SELECT sum(returned),sum(spent) FROM fishing_stats').fetchone()[:],(10,10))
        self.assertEqual(sum(f.view(self.db,u,self.t+2)['bag_count'] for u in (1,2)),0)
        g.tick(self.db,self.t+2);self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],1)
        totals=self.db.execute("SELECT sum(game_delta),sum(flow_delta) FROM wealth_events WHERE kind LIKE 'fishing_%'").fetchone();self.assertEqual(totals[:],(0,0))
    def test_conditional_odds_exact_boundaries_and_real_miss(self):
        for multiplier in (2,3,5,8,12,20,35,60,70):
            self.assertEqual(Fraction(9500,10000*multiplier)*multiplier,Fraction(95,100))
        for j,(ticket,caught) in enumerate(((0,True),(9499,True),(9500,False),(19999,False))):
            clock=self.t+j*3;self.call('join',clock=clock,room_id=1);self.single_fish();self.burst(clock=clock)
            with patch.object(g.secrets,'randbelow',return_value=ticket):g.tick(self.db,clock+1.5)
            last=self.db.execute('SELECT state,data FROM fishing_projectiles ORDER BY id DESC LIMIT 1').fetchone();self.assertEqual(last['state'],'caught' if caught else 'hit')
        self.db.execute('DELETE FROM fishing_entities');clock=self.t+15;self.burst(clock=clock);g.tick(self.db,clock+1.5)
        self.assertEqual(self.db.execute('SELECT state FROM fishing_projectiles ORDER BY id DESC LIMIT 1').fetchone()[0],'miss')
    def test_batch_idempotency_conflict_cadence_balance_and_validations(self):
        self.call('join',clock=self.t,room_id=1);first=self.burst();op=first['result']['operation_id']
        self.assertTrue(first['state']['partial']);self.assertNotIn('catalog',first['state']);self.assertEqual(first['state']['wallet']['balance'],2995)
        data=dict(operation_id=op,gameplay_version=3,room_id=1,cannon=0,stake=5,expected_revision=1,expected_limit_revision=1,shots=[dict(token='projectile_0000000001',fired_at=self.t,x=500,y=240)])
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
        self.assertEqual(f.view(self.db,1,self.t+2)['wallet']['balance'],2995)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT state FROM fishing_projectiles').fetchone()[0],'flying')
        with patch.object(g.secrets,'randbelow',return_value=0):
            with self.db:g.tick(self.db,self.t+1.5)
        self.assertEqual(f.view(self.db,1,self.t+2)['wallet']['balance'],3005)
        self.assertEqual(f.view(self.db,1,self.t+2)['shots'],1)

    def test_restart_resolves_paid_shots_before_expired_world_is_replaced(self):
        self.call('join',clock=self.t,room_id=1);fish=self.single_fish();self.burst();self.db.commit()
        f.initialize(self.db)
        with patch.object(g.secrets,'randbelow',return_value=0):g.tick(self.db,self.t+120)
        self.assertEqual(self.db.execute('SELECT fish_id FROM fishing_captures').fetchone()[0],fish['id'])
        self.assertEqual(f.view(self.db,1,self.t+120)['returned'],10)
        g.tick(self.db,self.t+121);self.assertEqual(f.view(self.db,1,self.t+121)['wallet']['balance'],3005)

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
            op=result['result']['operation_id'];data=dict(gameplay_version=3,operation_id=op,cast_id=game['id'],sequence=result['result']['sequence'],holding=holding,**fields)
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
            other={**boss,'id':'bonus_target_'+str(slot),'slot':slot,'species':species,'multiplier':mult,'x0':500+slot*70,'feature':None,'boss':False};g._put_entity(self.db,1,other)
        self.burst(uid=1);self.burst(uid=2)
        with patch.object(g.secrets,'randbelow',return_value=0) as random:g.tick(self.db,self.t+1.5)
        random.assert_called_once_with(850000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],3)
        self.assertEqual(self.db.execute('SELECT sum(returned),sum(spent),sum(shots) FROM fishing_stats').fetchone()[:],(425,10,2))
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='fishing_win'").fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT sum(gross) FROM fishing_captures').fetchone()[0],425)
        g.tick(self.db,self.t+2);self.assertEqual(self.db.execute('SELECT count(*) FROM fishing_captures').fetchone()[0],3)

    def test_completed_v2_receipt_replays_but_stale_new_shots_cannot_spend(self):
        self.call('join',clock=self.t,room_id=1);result=self.burst();op=result['result']['operation_id']
        row=self.db.execute('SELECT fingerprint FROM fishing_operations WHERE operation_id=?',(op,)).fetchone();fingerprint=json.loads(row[0]);fingerprint['gameplay_version']=2
        self.db.execute('UPDATE fishing_operations SET fingerprint=? WHERE operation_id=?',(g.encode(fingerprint),op))
        data={k:v for k,v in fingerprint.items() if k!='action'};data['operation_id']=op
        self.assertTrue(f.mutate(self.db,{'id':1},'burst',data,self.t+5)['replayed'])
        with self.assertRaises(f.RuleError):f.mutate(self.db,{'id':1},'burst',{**data,'operation_id':'stale_new_shot_000001'},self.t+5)
        self.assertEqual(f.view(self.db,1,self.t+5)['wallet']['balance'],2995)

    def test_blocked_account_cannot_enter_or_shoot(self):
        self.db.execute("INSERT INTO account_states(user_id,status,revision,reason,changed_at) VALUES(1,'blocked',1,'test',0)")
        with self.assertRaises(member_accounts.AccountError):self.call('cast')

class FishingAPI(ServerTestCase):
    def test_twenty_concurrent_players_replay_and_private_state(self):
        a=self.clients[0];self.assertEqual(a.call('/api/fishing?version=3')[0],401)
        self.assertEqual(a.call('/api/register',dict(username='angler_0',nickname='Fishing',password='SyntheticFishing123'))[0],200)
        self.assertEqual(a.call('/api/fishing')[0],426)
        invite=a.call('/api/state')[1]['invite_code'];people=[a]
        for i in range(1,20):
            client=Client(self.base);self.assertEqual(client.call('/api/register',dict(username='angler_'+str(i),nickname='Angler'+str(i),password='SyntheticFishing123',invite_code=invite))[0],200);people.append(client)
        def join(pair):
            i,c=pair;return c.call('/api/fishing/join',dict(gameplay_version=3,operation_id='http_join_'+str(i).zfill(12),room_id=i//6+1))
        with ThreadPoolExecutor(20) as pool:joined=list(pool.map(join,enumerate(people)))
        self.assertTrue(all(s==200 for s,r in joined),joined)
        self.assertEqual(a.call('/api/fishing/join',dict(gameplay_version=3,operation_id='http_full_room_0001',room_id=2))[0],400)
        def burst(pair):
            i,c=pair;return c.call('/api/fishing/burst',dict(gameplay_version=3,operation_id='http_burst_00000001',room_id=i//6+1,cannon=0,stake=5,expected_revision=1,expected_limit_revision=1,shots=[dict(token='http_token_'+str(i).zfill(12),fired_at=time.time(),x=500,y=240)]))
        started=time.monotonic()
        with ThreadPoolExecutor(20) as pool:responses=list(pool.map(burst,enumerate(people)))
        self.assertTrue(all(s==200 for s,r in responses),responses);self.assertLess(time.monotonic()-started,8)
        i=0;data=dict(gameplay_version=3,operation_id='http_burst_00000001',room_id=1,cannon=0,stake=5,expected_revision=1,expected_limit_revision=1,shots=[dict(token='http_token_'+str(i).zfill(12),fired_at=responses[0][1]['result']['shots'][0]['born_at'],x=500,y=240)])
        with closing(sqlite3.connect(self.db_path)) as db:
            fingerprint=json.loads(db.execute("SELECT fingerprint FROM fishing_operations WHERE user_id=1 AND operation_id='http_burst_00000001'").fetchone()[0]);data.update({k:v for k,v in fingerprint.items() if k!='action'})
        self.assertEqual(a.call('/api/fishing/burst',data,origin='https://foreign.invalid')[0],403)
        with ThreadPoolExecutor(8) as pool:replays=list(pool.map(lambda _:a.call('/api/fishing/burst',data),range(8)))
        self.assertTrue(all(s==200 and r['replayed'] for s,r in replays),replays)
        self.assertEqual(a.call('/api/fishing?version=3')[1]['shots'],1)
        world=a.call('/api/fishing/world?room=1')[1];self.assertEqual(len(world['players']),6);self.assertEqual(len(world['entities']),18)
        self.assertNotIn('wallet',world);self.assertNotIn('seed',json.dumps(world))
        # Public paths and already fired settings are public; no future capture tickets.
        self.assertNotIn('caught_ticket',json.dumps(world));self.assertNotIn('pending',world)
        with closing(sqlite3.connect(self.db_path)) as db:self.assertEqual(db.execute('SELECT sum(shots),sum(spent) FROM fishing_stats').fetchone(),(20,100))
