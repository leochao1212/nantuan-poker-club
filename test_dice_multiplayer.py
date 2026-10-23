"""A shared Sic Bo roll, per-player stakes, replay and departure accounting."""
import copy,itertools,json,unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack,closing
from unittest.mock import patch
import bonus_engine as b,poker_engine as p,online,wallet
import test_bonus as fixtures
from test_app import ServerTestCase
from test_realtime import Stream

class SharedDice(unittest.TestCase):
    def test_six_players_share_every_possible_roll_with_individual_payouts(self):
        choices=[('big',20),('small',30),('number:1',40),('total:9',10),('any_triple',5),('triple:6',2)]
        for outcome in itertools.product(range(1,7),repeat=3):
            r=fixtures.room('dice',count=6);before=fixtures.points(r)
            b.start_hand(r,101)
            self.assertNotIn('dice',r['hand'])
            with patch.object(b.secrets,'randbelow',side_effect=[x-1 for x in outcome]) as rng:
                for uid,(key,amount) in enumerate(choices,1):
                    b.act(r,uid,'bet',102,{'bets':[{'key':key,'amount':amount}]})
                    if uid<6:
                        self.assertEqual(r['status'],'playing');rng.assert_not_called()
                self.assertEqual([c.args for c in rng.call_args_list],[(6,)]*3)
            self.assertEqual(r['hand']['dice'],list(outcome));self.assertEqual(len(r['hand']['results']),6)
            for row,(key,amount) in zip(r['hand']['results'],choices):
                expected=amount*b.dice_multiplier(list(outcome),key)
                self.assertEqual(row['payout'],expected);self.assertEqual(row['profit'],expected-amount)
            self.assertEqual(fixtures.points(r),before)

    def test_only_initiator_is_charged_and_seventh_seat_is_rejected(self):
        r=fixtures.room('dice',count=6)
        with self.assertRaises(p.RuleError):b.sit(r,7,'7',100)
        b.start_hand(r,101,options={'bets':[{'key':'big','amount':37}]},user_id=4)
        self.assertEqual([q['contribution'] for q in r['hand']['players']],[0,0,0,37,0,0])
        self.assertEqual([s['stack'] for s in r['seats']],[10000,10000,10000,9963,10000,10000])
        self.assertIsNone(b.legal_actions(r,4));self.assertIsNotNone(b.legal_actions(r,1))
        self.assertEqual(b.public_view(r,1)['hand']['players'][3]['bets'],[])
        self.assertEqual(b.public_view(r,4)['hand']['players'][3]['bets'],[{'key':'big','amount':37}])
        before=copy.deepcopy(r)
        with self.assertRaises(p.RuleError):b.act(r,4,'bet',102,{'bets':[{'key':'small','amount':1}]})
        self.assertEqual(r,before)

    def test_timeout_and_departures_keep_confirmed_bets_and_conserve_points(self):
        r=fixtures.room('dice',count=3);total=fixtures.points(r)
        b.start_hand(r,101,options={'bets':[{'key':'big','amount':20}]},user_id=1)
        b.leave(r,1,102);self.assertTrue(p.seated(r,1)['leaving'])
        b.leave(r,2,102);self.assertEqual(r['status'],'playing')
        self.assertEqual(r['hand']['pending'],[3]);self.assertFalse(b.tick(r,130.99))
        with patch.object(b.secrets,'randbelow',side_effect=[3,3,4]):self.assertTrue(b.tick(r,131))
        self.assertEqual(r['status'],'waiting');self.assertEqual(r['hand']['results'][0]['payout'],40)
        self.assertEqual([q['payout'] for q in r['hand']['results'][1:]],[0,0])
        self.assertIsNone(p.seated(r,1));self.assertIsNone(p.seated(r,2))
        self.assertEqual(fixtures.points(r),total)

    def test_aggregate_liability_and_own_balance_are_checked_without_mutation(self):
        r=fixtures.room('dice',count=2);r['bank']=20000
        b.start_hand(r,101,options={'bets':[{'key':'triple:6','amount':100}]},user_id=1)
        before=copy.deepcopy(r)
        with self.assertRaises(p.RuleError):b.act(r,2,'bet',102,{'bets':[{'key':'triple:6','amount':100}]})
        self.assertEqual(r,before)
        # A different triple has a disjoint maximum, so the same bank can cover it.
        with patch.object(b.secrets,'randbelow',side_effect=[5,5,5]):b.act(r,2,'bet',102,{'bets':[{'key':'triple:5','amount':100}]})
        self.assertGreaterEqual(r['bank'],0)
        r=fixtures.room('dice',count=2);r['seats'][1]['stack']=1;b.start_hand(r,101)
        before=copy.deepcopy(r)
        with self.assertRaises(p.RuleError):b.act(r,2,'bet',102,{'bets':[{'key':'big','amount':2}]})
        self.assertEqual(r,before)

    def test_joining_midround_waits_until_next_round(self):
        r=fixtures.room('dice',count=2);b.start_hand(r,101)
        b.sit(r,3,'3',102);self.assertIsNone(b.legal_actions(r,3))
        for uid in (1,2):b.act(r,uid,'skip',102)
        b.start_hand(r,103);self.assertEqual(r['hand']['pending'],[1,2,3])

class StoredDice(unittest.TestCase):
    setUp=fixtures.Storage.setUp
    def test_legacy_table_upgrade_and_combined_starts_keep_one_hand_and_receipts(self):
        rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'dice'},self.user,100)['id'];path=f'/api/online/rooms/{rid}'
        room=online.get_room(self.db,rid);room['capacity']=1
        self.db.execute('UPDATE poker_rooms SET state=? WHERE id=?',(json.dumps(room),rid))
        balance=wallet.view(self.db,1,100)['total'];online.upgrade_dice_capacity(self.db)
        r=online.get_room(self.db,rid);self.assertEqual(r['capacity'],6);self.assertEqual(wallet.view(self.db,1,100)['total'],balance)
        revision=r['revision'];online.upgrade_dice_capacity(self.db);self.assertEqual(online.get_room(self.db,rid)['revision'],revision)
        other={'id':2,'username':'b','nickname':'B'}
        online.mutate(self.db,path+'/join',{'revision':revision,'buy_in':75},other,100)
        revision=online.get_room(self.db,rid)['revision']
        one={'revision':revision,'operation_id':'dice_first_player_0001','expected_hand_number':1,'bets':[{'key':'big','amount':20}]}
        two={'revision':revision,'operation_id':'dice_second_player_001','expected_hand_number':1,'bets':[{'key':'small','amount':30}]}
        online.mutate(self.db,path+'/start',one,self.user,101)
        self.assertEqual(online.get_room(self.db,rid)['status'],'playing')
        self.assertTrue(online.mutate(self.db,path+'/start',one,self.user,102)['replayed'])
        online.mutate(self.db,path+'/start',two,other,102)
        r=online.get_room(self.db,rid);self.assertEqual(r['status'],'waiting');self.assertEqual(r['hand_no'],1)
        self.assertEqual([q['contribution'] for q in r['hand']['players']],[20,30])
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_hands WHERE room_id=?',(rid,)).fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_results').fetchone()[0],2)
        before=copy.deepcopy(r)
        stale={**one,'operation_id':'late_old_dice_intent_01'}
        self.assertEqual(online.mutate(self.db,path+'/start',stale,self.user,103),{'conflict':True,'reason':'stale_hand'})
        self.assertEqual(online.get_room(self.db,rid),before)
        for user in (self.user,other):
            r=online.get_room(self.db,rid);online.mutate(self.db,path+'/leave',{'revision':r['revision']},user,104)
        self.assertEqual(sum(wallet.view(self.db,u,104)['total'] for u in (1,2))+online.get_room(self.db,rid)['bank'],1006000)

class DiceAPI(ServerTestCase):
    def test_six_simultaneous_combined_bets_share_one_pushed_result_and_replay(self):
        a=self.clients[0]
        for i,c in enumerate(self.clients[:7]):
            data={'username':f'dice_multi_{i}','nickname':f'P{i}','password':'password123'}
            if i:data['invite_code']=a.call('/api/state')[1]['invite_code']
            self.assertEqual(c.call('/api/register',data)[0],200)
        rid=a.call('/api/online/rooms',{'game_type':'dice'})[1]['id'];path=f'/api/online/rooms/{rid}'
        for c in self.clients[1:6]:self.assertEqual(c.call(path+'/join',{'revision':a.call(path)[1]['revision']})[0],200)
        self.assertEqual(self.clients[6].call(path+'/join',{'revision':a.call(path)[1]['revision']})[0],400)
        revision=a.call(path)[1]['revision']
        data=[{'revision':revision,'operation_id':f'concurrent_dice_bet_{i:02}','expected_hand_number':1,'bets':[{'key':'big' if i%2 else 'small','amount':10*(i+1)}]} for i in range(6)]
        with ExitStack() as stack:
            streams=[stack.enter_context(closing(Stream(c,f'/api/online/events?presence=client&client=dice_multiplayer_test_{i}&room={rid}'))) for i,c in enumerate(self.clients[:6])]
            for s in streams:s.state()
            with ThreadPoolExecutor(6) as pool:replies=list(pool.map(lambda i:self.clients[i].call(path+'/start',data[i]),range(6)))
            self.assertTrue(all(r[0]==200 for r in replies),replies)
            final=a.call(path)[1];self.assertEqual(final['status'],'waiting');self.assertEqual(final['hand_no'],1)
            with ThreadPoolExecutor(6) as pool:views=list(pool.map(lambda s:s.state(final['revision']),streams))
            self.assertTrue(all(v['hand']['dice']==final['hand']['dice'] for v in views))
            self.assertTrue(all(len(v['hand']['results'])==6 for v in views))
            self.assertEqual([q['contribution'] for q in final['hand']['players']],[10,20,30,40,50,60])
            for i,c in enumerate(self.clients[:6]):self.assertTrue(c.call(path+'/start',data[i])[1]['replayed'])
            self.assertEqual(a.call(path)[1]['hand_no'],1)
            self.assertEqual(len(a.call(path)[1]['history']),1)

if __name__=='__main__':unittest.main()
