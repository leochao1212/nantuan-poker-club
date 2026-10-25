"""Versioned public odds, administrator boundaries and frozen per-hand rules."""
from copy import deepcopy
from collections import Counter
from fractions import Fraction
from itertools import product
from unittest.mock import patch
from contextlib import closing
import json,sqlite3,time,unittest,concurrent.futures
import game_settings as g,online,club_admin,bonus_engine as b,arcade_engine as a,poker_engine as p
from .test_app import ServerTestCase
from . import test_arcade

class SettingsRules(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  self.db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TESTONLY');")
  self.db.executemany('INSERT INTO users VALUES(?,?,?,?)',[(i,f'person_{i}',f'P{i}','2026') for i in range(1,4)])
  online.initialize(self.db);self.db.execute('INSERT INTO club_admins VALUES(1,0,?)',(time.time(),));self.db.commit();self.t=time.time()
 def update(self,kind,changes,op=None,revision=None):
  old=g.current(self.db,kind);params={**old['params'],**changes}
  return g.update(self.db,{'id':1},{'game_type':kind,'revision':old['revision'] if revision is None else revision,'params':params,'note':'test rule change','operation_id':op or 'settings_'+str(time.time_ns())},self.t)
 def test_slot_216_outcomes_new_exact_rtp_and_all_legacy_versions(self):
  cfg=g.DEFAULTS['slot'];pay=0;hits=0
  for reels in product(range(6),repeat=3):
   expected=[77,32,20,14,10,7][reels[0]] if len(set(reels))==1 else 4 if reels[0]==reels[1] else 0
   self.assertEqual(b.slot_multiplier(reels),expected);pay+=expected;hits+=bool(expected)
  self.assertEqual(Fraction(pay,216),Fraction(35,27));self.assertEqual(hits,36)
  self.assertEqual(g.metrics('slot',cfg)['rtp_exact'],'35/27')
  self.assertEqual([b.slot_multiplier([0,0,0],v) for v in (1,2,3)],[75,78,77])
 def test_weighted_tickets_are_exact_and_slot_weighted_return_is_exact(self):
  weights=[1,0,3,2,0,4];counts=Counter()
  for ticket in range(10):
   with patch.object(g.secrets,'randbelow',return_value=ticket):counts[g.weighted(weights)]+=1
  self.assertEqual([counts[i] for i in range(6)],weights)
  cfg={**g.DEFAULTS['slot'],'weights':[0,5,0,0,0,0]};self.assertEqual(g.metrics('slot',cfg)['rtp_percent'],3200)
  r=b.new_room('Weighted',1,'slot',1000,10);b.sit(r,2,'P2',self.t)
  b.start_hand(r,self.t+1,settings={'game_type':'slot','revision':8,'params':cfg})
  self.assertEqual(r['hand']['reels'],[1,1,1]);self.assertEqual(r['hand']['results'][0]['payout'],320)
 def test_public_snapshot_nested_mutations_cannot_change_private_room(self):
  room=b.new_room('Private risk',1,'mines',1000,10);b.sit(room,2,'P2',self.t)
  b.start_hand(room,self.t+1)
  original=deepcopy(room);view=b.public_view(room,2)
  self.assertNotIn('hazards',view['hand']);self.assertNotIn('bank',view)
  view['hand']['players'][0]['nickname']='Changed'
  view['hand']['game_settings']['params']['bombs']=1
  view['seats'][0]['stack']=0;view['hand']['returns'].append(999)
  self.assertEqual(room,original)
 def test_admin_permissions_revision_retry_and_history(self):
  with self.assertRaises(club_admin.AdminError):g.admin_view(self.db,{'id':2})
  self.db.execute('UPDATE club_admins SET password_change_required=1')
  with self.assertRaises(club_admin.AdminError):self.update('slot',{'pair':6})
  self.db.execute('UPDATE club_admins SET password_change_required=0')
  first=self.update('slot',{'pair':6},'settings_same_operation_01');self.assertEqual(first['saved_revision'],2)
  payload={'game_type':'slot','params':{**g.DEFAULTS['slot'],'pair':6},'revision':1,'note':'test rule change','operation_id':'settings_same_operation_01'}
  self.assertTrue(g.update(self.db,{'id':1},payload,self.t)['replayed'])
  with self.assertRaises(club_admin.AdminError):g.update(self.db,{'id':1},{**payload,'note':'different'},self.t)
  with self.assertRaises(club_admin.AdminError):self.update('slot',{'pair':7},revision=1)
  self.assertEqual(self.db.execute('SELECT count(*) FROM game_settings_audit').fetchone()[0],1)
  before=g.current(self.db,'slot');g.initialize(self.db);self.assertEqual(g.current(self.db,'slot'),before)
 def test_unknown_player_target_and_invalid_parameters_are_rejected(self):
  for kind,change in [('slot',{'weights':[0]*6}),('roulette',{'weights':[1]*36}),('dice',{'weights':[-1,1,1,1,1,1]}),('tower',{'progressive_bombs':[1,2,1,2,2,2]}),('mines',{'bombs':21}),('blackjack',{'decks':0}),('slot',{'user_id':2}),('baccarat',{'banker_bp':True})]:
   with self.subTest(kind=kind,change=change),self.assertRaises(p.RuleError):self.update(kind,change)
  with self.assertRaises(p.RuleError):self.update('holdem',{})
 def test_failed_audit_insert_rolls_back_setting_change(self):
  before=g.current(self.db,'slot');self.db.commit()
  self.db.execute("CREATE TEMP TRIGGER reject_rules BEFORE INSERT ON game_settings_audit BEGIN SELECT RAISE(ABORT,'fixture'); END")
  with self.assertRaises(sqlite3.IntegrityError):
   with self.db:self.update('slot',{'pair':9})
  self.assertEqual(g.current(self.db,'slot'),before)
 def test_room_exposes_current_and_next_versions_without_changing_live_risk(self):
  user={'id':2,'username':'person_2','nickname':'P2'};rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'mines','stake':100},user,self.t)['id']
  r=online.get_room(self.db,rid);online.mutate(self.db,f'/api/online/rooms/{rid}/start',{'revision':r['revision']},user,self.t+1)
  original=online.get_room(self.db,rid)['hand'];self.update('mines',{'bombs':1,'target_bps':20000})
  view=online.room_view(self.db,rid,2,self.t+2)
  self.assertEqual(view['hand']['game_settings']['params']['bombs'],5);self.assertEqual(view['next_game_settings']['params']['bombs'],1)
  self.assertEqual(view['hand']['returns'][0],121)
  self.assertEqual(online.get_room(self.db,rid)['hand'],original)
 def test_pair_maximum_liability_is_reserved_before_deducting(self):
  cfg={**g.DEFAULTS['slot'],'triples':[1]*6,'pair':500};r=b.new_room('Reserve',1,'slot',1000,100);b.sit(r,2,'P2',self.t);r['bank']=49999;before=deepcopy(r)
  with self.assertRaises(p.RuleError):b.start_hand(r,self.t+1,settings={'game_type':'slot','revision':2,'params':cfg})
  self.assertEqual(r,before)
 def test_start_with_outdated_displayed_settings_cannot_debit_or_draw(self):
  user={'id':2,'username':'person_2','nickname':'P2'};rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'slot','stake':100},user,self.t)['id']
  room=online.get_room(self.db,rid);self.update('slot',{'pair':7});before=deepcopy(online.get_room(self.db,rid))
  result=online.mutate(self.db,f'/api/online/rooms/{rid}/start',{'operation_id':'settings_stale_start_0001','expected_settings_revision':1,'revision':room['revision']},user,self.t+1)
  self.assertEqual(result['reason'],'stale_settings');self.assertEqual(online.get_room(self.db,rid),before)
  with patch.object(b.secrets,'randbelow',side_effect=[0,0,1]):
   online.mutate(self.db,f'/api/online/rooms/{rid}/start',{'operation_id':'settings_fresh_start_0001','expected_settings_revision':2,'revision':room['revision'],'settings':{'pair':999}},user,self.t+2)
  self.assertEqual(online.get_room(self.db,rid)['hand']['results'][0]['payout'],700)
 def test_dice_shared_draw_uses_frozen_weights_and_multipliers(self):
  cfg=deepcopy(g.DEFAULTS['dice']);cfg.update(weights=[0,0,1,0,0,0],faces=[1,2,7]);snapshot={'game_type':'dice','revision':7,'params':cfg}
  r=b.new_room('Dice',1,'dice',1000,10)
  for uid in (1,2):b.sit(r,uid,f'P{uid}',self.t)
  b.start_hand(r,self.t+1,settings=snapshot);b.act(r,1,'bet',self.t+2,{'bets':[{'key':'number:3','amount':10}]})
  cfg['weights']=[0,0,0,0,0,1];cfg['faces'][2]=100
  b.act(r,2,'bet',self.t+3,{'bets':[{'key':'number:3','amount':10}]})
  self.assertEqual(r['hand']['dice'],[3,3,3]);self.assertEqual([x['payout'] for x in r['hand']['results']],[80,80])
 def test_roulette_zero_weight_and_custom_payout(self):
  cfg=deepcopy(g.DEFAULTS['roulette']);cfg['weights']=[0]*37;cfg['weights'][17]=3;cfg['number_bp']=90000
  r=test_arcade.room('roulette',1);a.start_hand(r,self.t,settings={'game_type':'roulette','revision':4,'params':cfg});cfg['number_bp']=10000
  a.act(r,1,'bet',self.t+1,{'bets':[{'kind':'number','number':17,'amount':10}]})
  self.assertEqual(r['hand']['number'],17);self.assertEqual(r['hand']['results'][0]['payout'],100)
  m=g.metrics('roulette',r['hand']['game_settings']['params']);self.assertEqual(m['bets']['number:17']['rtp_percent'],1000);self.assertEqual(m['bets']['even']['win_percent'],0)
 def test_blackjack_custom_payout_frozen_and_shoe_deck_count(self):
  cfg=deepcopy(g.DEFAULTS['blackjack']);r=test_arcade.room('blackjack',1,stake=100)
  a.start_hand(r,self.t,deck=test_arcade.shoe(['Th','9h','8c','8d']),settings={'game_type':'blackjack','revision':4,'params':cfg});cfg['win_bp']=90000
  a.act(r,1,'stand',self.t+1);self.assertEqual(r['hand']['results'][0]['payout'],200)
  cfg['decks']=1;a.start_hand(r,self.t+5,settings={'game_type':'blackjack','revision':5,'params':cfg})
  self.assertEqual(r['blackjack_shoe']['decks'],1);self.assertEqual(r['blackjack_shoe']['cut_remaining'],13);self.assertEqual(len(r['hand']['deck'])+sum(len(h['cards']) for q in r['hand']['players'] for h in q['hands'])+len(r['hand']['dealer']),52)
  crowded=test_arcade.room('blackjack',6);before=deepcopy(crowded)
  with self.assertRaises(p.RuleError):a.start_hand(crowded,self.t,settings={'game_type':'blackjack','revision':5,'params':cfg})
  self.assertEqual(crowded,before)
 def test_baccarat_payout_and_mines_tower_custom_survival(self):
  cfg={**g.DEFAULTS['baccarat'],'player_bp':20000};r=b.new_room('Baccarat',1,'baccarat',1000,20);b.sit(r,2,'P2',self.t)
  b.start_hand(r,self.t+1,deck=test_arcade.shoe(['4c','Kc','4d','Qc']),settings={'game_type':'baccarat','revision':3,'params':cfg});b.act(r,2,'bet',self.t+2,{'side':'player'})
  self.assertEqual(r['hand']['results'][0]['payout'],60)
  cfg={**g.DEFAULTS['mines'],'bombs':10,'target_bps':15000};self.assertEqual(b.risk_return('mines',100,1,settings=cfg),250)
  cfg={**g.DEFAULTS['tower'],'fixed_bombs':2,'target_bps':10000};self.assertEqual(b.risk_return('tower',100,2,settings=cfg),400)
 def test_big2_custom_reserve_covers_middle_penalty_and_conserves_points(self):
  cfg={'penalties':[1,20,1]};r=test_arcade.room('big2',4,stake=10,stack=10000);before=test_arcade.points(r)
  a.start_hand(r,self.t,settings={'game_type':'big2','revision':2,'params':cfg});self.assertEqual(r['hand']['reserve'],2400)
  for q,count in zip(r['hand']['players'],[0,8,12,13]):q['cards']=p.DECK[:count]
  a._finish_big2(r,1,self.t+1);self.assertEqual(test_arcade.points(r),before);self.assertEqual(r['hand']['results'][0]['profit'],4130)

class SettingsAPI(ServerTestCase):
 def test_auth_csrf_validation_and_persisted_revision_over_http(self):
  admin,player,anon=self.clients[:3]
  self.assertEqual(anon.call('/api/admin/game-settings')[0],401)
  self.assertEqual(admin.call('/api/register',{'username':'rules_admin','nickname':'Admin','password':'PreviewOnly123'})[0],200)
  invite=admin.call('/api/state')[1]['invite_code'];player.call('/api/register',{'username':'rules_player','nickname':'Player','password':'PreviewOnly123','invite_code':invite})
  self.assertEqual(player.call('/api/admin/game-settings')[0],403)
  with closing(sqlite3.connect(self.db_path)) as db:
   db.execute('INSERT INTO club_admins VALUES(1,0,?)',(time.time(),));db.commit()
  status,view=admin.call('/api/admin/game-settings');self.assertEqual(status,200);self.assertEqual(len(view['games']),len(g.DEFAULTS))
  slot=next(x for x in view['games'] if x['game_type']=='slot');payload={'game_type':'slot','params':{**slot['params'],'pair':6},'revision':slot['revision'],'note':'HTTP test','operation_id':'settings_http_replay_001'}
  self.assertEqual(player.call('/api/admin/game-settings',payload)[0],403)
  self.assertEqual(admin.call('/api/admin/game-settings',payload,origin='https://evil.invalid')[0],403)
  self.assertEqual(admin.call('/api/admin/game-settings/preview',payload)[0],200)
  self.assertEqual(admin.call('/api/admin/game-settings',payload)[0],200)
  self.assertTrue(admin.call('/api/admin/game-settings',payload)[1]['replayed'])
  self.assertEqual(admin.call('/api/admin/game-settings',{**payload,'operation_id':'settings_http_stale_001'})[0],409)
  status,view=admin.call('/api/admin/game-settings');self.assertEqual(view['history'][0]['revision'],2)
  rid=player.call('/api/online/rooms',{'game_type':'slot','stake':10})[1]['id']
  room=player.call(f'/api/online/rooms/{rid}')[1];self.assertEqual(room['next_game_settings']['params']['pair'],6)
  fresh=next(x for x in view['games'] if x['game_type']=='slot')
  requests=[{**payload,'params':{**fresh['params'],'pair':n},'revision':fresh['revision'],'operation_id':f'settings_parallel_{n:04d}'} for n in (7,8)]
  with concurrent.futures.ThreadPoolExecutor(2) as pool:responses=list(pool.map(lambda value:admin.call('/api/admin/game-settings',value),requests))
  self.assertEqual(sorted(r[0] for r in responses),[200,409])
