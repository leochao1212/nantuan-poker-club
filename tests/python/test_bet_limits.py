"""Configurable ceilings, frozen rounds, atomic receipts and virtual house reserves."""
from copy import deepcopy
import json,unittest
from unittest.mock import patch
import game_settings as g,bonus_engine as b,arcade_engine as a,poker_engine as p,online,wallet,club_admin
from . import test_game_settings as settings_tests
from .test_arcade import points,shoe

class BetLimits(unittest.TestCase):
 setUp=settings_tests.SettingsRules.setUp
 update=settings_tests.SettingsRules.update
 def room(self,kind,count=1,stake=10000):
  driver=b if kind in b.CATALOG else a
  r=driver.new_room('Limit fixture',2,kind,100000,stake,settings=g.current(self.db,kind))
  for uid in range(1,count+1):driver.sit(r,uid,'P'+str(uid),self.t)
  return r
 def test_default_persistence_validation_and_admin_boundaries(self):
  self.assertEqual(g.current(self.db,'limits')['params'],{'max_bet':10000})
  original=g.current(self.db,'slot')['params'];self.update('limits',{'max_bet':25000})
  self.assertEqual(g.current(self.db,'slot')['bet_limit'],25000)
  self.assertEqual(g.current(self.db,'slot')['params'],original)
  g.initialize(self.db);self.assertEqual(g.current(self.db,'limits')['revision'],2)
  for value in (0,19,1000001,True,1.5,'10000'):
   with self.subTest(value=value),self.assertRaises(p.RuleError):self.update('limits',{'max_bet':value})
  with self.assertRaises(club_admin.AdminError):g.admin_view(self.db,{'id':2})
 def test_dice_total_includes_duplicate_and_separate_bets(self):
  self.assertEqual(sum(x['amount'] for x in b.dice_bets([{'key':'big','amount':6000},{'key':'big','amount':4000}])),10000)
  for bets in ([{'key':'big','amount':10001}],[{'key':'big','amount':5000},{'key':'small','amount':5001}]):
   with self.assertRaises(p.RuleError):b.dice_bets(bets)
 def test_six_player_roulette_at_ceiling_conserves_points(self):
  r=self.room('roulette',6);before=points(r);a.start_hand(r,self.t+1,settings=g.current(self.db,'roulette'))
  self.assertEqual(a.legal_actions(r,1)['max_total'],10000)
  with patch.object(g,'weighted',return_value=17):
   for uid in range(1,7):a.act(r,uid,'bet',self.t+2,{'bets':[{'kind':'number','number':17,'amount':10000}]})
  self.assertEqual(r['status'],'waiting');self.assertEqual(points(r),before)
  self.assertTrue(all(x['payout']==360000 for x in r['hand']['results']))
 def test_six_player_dice_highest_payout_is_funded_and_conserved(self):
  r=self.room('dice',6);before=points(r);b.start_hand(r,self.t+1,settings=g.current(self.db,'dice'))
  with patch.object(g,'weighted',return_value=5):
   for uid in range(1,7):b.act(r,uid,'bet',self.t+2,{'bets':[{'key':'triple:6','amount':10000}]})
  self.assertTrue(all(x['payout']==1510000 for x in r['hand']['results']));self.assertEqual(points(r),before)
 def test_new_ceiling_applies_to_room_creation_and_each_game(self):
  for kind in ('big2','blackjack','roulette',*b.CATALOG):
   with self.subTest(kind=kind):
    r=self.room(kind);self.assertEqual(r['stake'],10000)
    driver=b if kind in b.CATALOG else a
    with self.assertRaises(p.RuleError):driver.new_room('Too much',2,kind,100000,10020,settings=g.current(self.db,kind))
  for kind in ('slot','mines','tower','baccarat'):
   with self.subTest(start=kind):
    r=self.room(kind);driver=b;before=points(r)
    driver.start_hand(r,self.t+1,settings=g.current(self.db,kind),options={'stake':10000})
    if kind=='baccarat':b.act(r,1,'bet',self.t+2,{'side':'player'})
    elif kind in ('mines','tower'):b.tick(r,self.t+32)
    self.assertEqual(points(r),before)
 def test_blackjack_initial_bet_limit_keeps_double_and_split_rules(self):
  r=self.room('blackjack');a.set_blackjack_bet(r,1,10000,settings=g.current(self.db,'blackjack'))
  with self.assertRaises(p.RuleError):a.set_blackjack_bet(r,1,10002,settings=g.current(self.db,'blackjack'))
  a.start_hand(r,self.t+1,deck=shoe(['5c','9d','6h','7c','Th','2d']),settings=g.current(self.db,'blackjack'))
  self.assertIn('double',a.legal_actions(r,1)['actions']);a.act(r,1,'double',self.t+2)
  self.assertEqual(r['hand']['players'][0]['contribution'],20000)
 def test_gate_ceiling_and_collateral_remain_separate(self):
  r=self.room('inbetween');b.start_hand(r,self.t+1,deck=list(p.DECK),settings=g.current(self.db,'inbetween'))
  h=r['hand'];h.pop('gate_quotes',None);h['pillars']=['5s','5h'];h['deck']=[c for c in p.DECK if c not in h['pillars']]
  self.assertEqual(b.legal_actions(r,1)['max_stake'],10000)
  h['players'][0]['stack']=15000;self.assertEqual(b.legal_actions(r,1)['max_stake'],5000)
  before=deepcopy(r)
  with self.assertRaises(p.RuleError):b.act(r,1,'shoot',self.t+2,{'stake':10001,'direction':'up'})
  self.assertEqual(r,before)
 def test_live_round_freezes_limit_and_legacy_round_keeps_thousand(self):
  r=self.room('roulette',2);a.start_hand(r,self.t+1,settings=g.current(self.db,'roulette'));self.update('limits',{'max_bet':2000})
  self.assertEqual(a.legal_actions(r,1)['max_total'],10000)
  a.act(r,1,'bet',self.t+2,{'bets':[{'kind':'red','amount':10000}]});a.act(r,2,'skip',self.t+3,{})
  a.start_hand(r,self.t+4,settings=g.current(self.db,'roulette'));self.assertEqual(a.legal_actions(r,1)['max_total'],2000)
  r['hand']['game_settings'].pop('bet_limit');self.assertEqual(a.legal_actions(r,1)['max_total'],1000)
 def test_online_stale_limit_and_invalid_bet_do_not_debit_and_retry_is_idempotent(self):
  user={'id':2,'username':'person_2','nickname':'P2'};wallet.transfer(self.db,2,100000,'admin_grant','limit-fixture',self.t)
  rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'slot','buy_in':50000,'stake':100},user,self.t)['id'];path=f'/api/online/rooms/{rid}/start';room=online.get_room(self.db,rid)
  self.update('limits',{'max_bet':5000});before=deepcopy(online.get_room(self.db,rid))
  payload={'operation_id':'bet_limit_stale_00001','revision':room['revision'],'expected_bet_limit_revision':1,'stake':10000}
  self.assertEqual(online.mutate(self.db,path,payload,user,self.t+1)['reason'],'stale_settings');self.assertEqual(online.get_room(self.db,rid),before)
  with self.assertRaises(p.RuleError):online.mutate(self.db,path,{**payload,'operation_id':'bet_limit_invalid_001','expected_bet_limit_revision':2},user,self.t+2)
  self.assertEqual(online.get_room(self.db,rid),before)
  payload={**payload,'operation_id':'bet_limit_valid_00001','expected_bet_limit_revision':2,'stake':5000}
  with patch.object(g,'weighted',side_effect=[0,1,2]):online.mutate(self.db,path,payload,user,self.t+3)
  settled=deepcopy(online.get_room(self.db,rid));online.mutate(self.db,path,payload,user,self.t+4)
  self.assertEqual(online.get_room(self.db,rid),settled);self.assertEqual(settled['hand']['players'][0]['contribution'],5000)
 def test_house_reserve_upgrade_is_only_between_rounds_at_a_new_high(self):
  r=self.room('dice');players=deepcopy(r['seats']);r.pop('bet_limit_funded');r.pop('house_risk_funded');r['bank']=1000000
  g.fund_bet_limit(r,g.current(self.db,'dice'));self.assertEqual(r['bank'],9060000);self.assertEqual(r['seats'],players)
  r['bank']-=123;g.fund_bet_limit(r,g.current(self.db,'dice'));self.assertEqual(r['bank'],9060000-123)
  self.update('limits',{'max_bet':2000});g.fund_bet_limit(r,g.current(self.db,'dice'));self.update('limits',{'max_bet':10000});g.fund_bet_limit(r,g.current(self.db,'dice'));self.assertEqual(r['bank'],9060000-123)

 def test_payout_increase_funds_only_added_risk_at_the_same_limit(self):
  for kind,changes in [('slot',{'triples':[500,32,20,14,10,7]}),('roulette',{'number_bp':1000000}),('dice',{'triple':500})]:
   with self.subTest(kind=kind):
    r=self.room(kind);before=deepcopy(r['seats']);peak=r['house_risk_funded'];r['bank']-=123
    self.update(kind,changes);cfg=g.current(self.db,kind);g.fund_bet_limit(r,cfg)
    self.assertGreater(r['house_risk_funded'],peak)
    self.assertEqual(r['bank'],r['house_risk_funded']-123);self.assertEqual(r['seats'],before)
    after=deepcopy(r);g.fund_bet_limit(r,cfg);self.assertEqual(r,after)
    r['status']='playing';self.update('limits',{'max_bet':20000});g.fund_bet_limit(r,g.current(self.db,kind));self.assertEqual(r['bank'],after['bank'])
    self.update('limits',{'max_bet':10000})

 def test_holdem_does_not_receive_house_credit_or_an_artificial_all_in_cap(self):
  r=p.new_room('Holdem',2,buy_in=50000);before=deepcopy(r)
  g.fund_bet_limit(r,g.current(self.db,'holdem'));self.assertEqual(r,before)
  self.assertNotIn('bank',r)

 def test_lower_ceiling_invalidates_old_blackjack_confirmation_without_debit(self):
  r=self.room('blackjack',2);a.confirm_blackjack_bet(r,1,10000,self.t+1,1,settings=g.current(self.db,'blackjack'))
  self.update('limits',{'max_bet':2000})
  self.assertFalse(a.confirm_blackjack_bet(r,2,2000,self.t+2,1,settings=g.current(self.db,'blackjack')))
  self.assertEqual(r['hand_no'],0);self.assertFalse(a.blackjack_ready(r,p.seated(r,1)))
  self.assertEqual([s['stack'] for s in r['seats']],[100000,100000])
  a.confirm_blackjack_bet(r,1,2000,self.t+3,1,settings=g.current(self.db,'blackjack'))
  self.assertEqual([q['contribution'] for q in r['hand']['players']],[2000,2000])
 def test_dice_in_progress_uses_old_limit_after_admin_changes_it(self):
  r=self.room('dice',2);b.start_hand(r,self.t+1,settings=g.current(self.db,'dice'));self.update('limits',{'max_bet':2000})
  b.act(r,1,'bet',self.t+2,{'bets':[{'key':'big','amount':10000}]});b.act(r,2,'skip',self.t+3,{})
  b.start_hand(r,self.t+4,settings=g.current(self.db,'dice'),options={'stake':20});before=deepcopy(r)
  with self.assertRaises(p.RuleError):b.act(r,1,'bet',self.t+5,{'bets':[{'key':'big','amount':2001}]})
  self.assertEqual(r,before)
