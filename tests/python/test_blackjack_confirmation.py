"""Blackjack wagers are explicit per round; confirmations never spend twice."""
import unittest
import arcade_engine as a
import poker_engine as p
import online
from . import test_club as fixtures

class BlackjackConfirmation(unittest.TestCase):
    setUp=fixtures.WalletRules.setUp
    def call(self,path,data,uid=1,at=1):
        return online.mutate(self.db,path,data,self.users[uid-1],self.clock+at)
    def table(self):
        rid=self.call('/api/online/rooms',{'game_type':'blackjack'})['id']
        self.path=f'/api/online/rooms/{rid}';self.rid=rid
        self.call(self.path+'/join',{'operation_id':'bj_join_player_00002'},uid=2)
        return online.get_room(self.db,rid)
    def confirm(self,uid=1,stake=100,number=1,op=None,at=2):
        return self.call(self.path+'/start',{'stake':stake,'expected_hand_number':number,'operation_id':op or f'bj_confirm_player_{uid:05d}'},uid,at)
    def test_first_confirmation_spends_nothing_last_confirmation_deals_once(self):
        r=self.table();before=[s['stack'] for s in r['seats']]
        self.confirm();r=online.get_room(self.db,self.rid)
        self.assertEqual(r['hand_no'],0);self.assertIsNone(r['hand']);self.assertEqual([s['stack'] for s in r['seats']],before)
        view=a.public_view(r,2);self.assertTrue(view['seats'][0]['blackjack_ready']);self.assertFalse(view['seats'][1]['blackjack_ready'])
        self.assertNotIn('blackjack_ready_for',view['seats'][0])
        self.assertTrue(self.confirm()['replayed']);self.confirm(2,200)
        r=online.get_room(self.db,self.rid);self.assertEqual(r['hand_no'],1)
        self.assertEqual([q['contribution'] for q in r['hand']['players']],[100,200])
        saved=r.copy();self.assertTrue(self.confirm(2,200)['replayed']);self.assertEqual(online.get_room(self.db,self.rid),saved)
        self.assertTrue(all('blackjack_ready_for' not in s for s in r['seats']))
        self.assertTrue(self.confirm(1,100,op='bj_stale_distinct_0001')['conflict'])
    def test_edit_cancels_confirmation_and_unconfirmed_player_blocks_deal(self):
        self.table();self.confirm()
        self.call(self.path+'/wager',{'stake':100,'expected_hand_number':1,'operation_id':'bj_cancel_confirm_001'})
        self.confirm(2,200);r=online.get_room(self.db,self.rid)
        self.assertEqual(r['hand_no'],0);self.assertFalse(a.public_view(r,1)['seats'][0]['blackjack_ready'])
        self.confirm(1,50,op='bj_reconfirm_player_1');r=online.get_room(self.db,self.rid)
        self.assertEqual([q['contribution'] for q in r['hand']['players']],[50,200])
    def test_new_joiner_must_confirm_and_departure_does_not_force_a_charge(self):
        self.table();self.confirm()
        self.call(self.path+'/join',{'operation_id':'bj_join_player_00003'},uid=3)
        self.confirm(2,200);self.assertEqual(online.get_room(self.db,self.rid)['hand_no'],0)
        self.call(self.path+'/leave',{'operation_id':'bj_leave_player_00003'},uid=3)
        self.assertEqual(online.get_room(self.db,self.rid)['hand_no'],0)
        self.confirm(op='bj_reconfirm_after_exit');self.assertEqual(online.get_room(self.db,self.rid)['hand_no'],1)
    def test_away_confirmation_clears_and_return_must_confirm(self):
        r=self.table();self.confirm();r=online.get_room(self.db,self.rid)
        r['seats'][0]['away']=True;online.save(self.db,r,self.clock+2)
        r=online.get_room(self.db,self.rid);self.assertNotIn('blackjack_ready_for',r['seats'][0])
        self.call(self.path+'/return',{'operation_id':'bj_return_player_0001'})
        self.confirm(2);self.assertEqual(online.get_room(self.db,self.rid)['hand_no'],0)
        self.confirm(op='bj_confirm_after_return');self.assertEqual(online.get_room(self.db,self.rid)['hand_no'],1)
    def test_invalid_and_legacy_requests_cannot_confirm_or_charge(self):
        self.table()
        for stake in (1,3,1002,True,'100'):
            with self.assertRaises(p.RuleError):self.confirm(stake=stake)
        with self.assertRaises(p.RuleError):self.call(self.path+'/start',{'stake':100,'operation_id':'bj_legacy_start_0001'})
        self.assertTrue(self.confirm(number=2)['conflict'])
        r=online.get_room(self.db,self.rid);self.assertEqual(r['hand_no'],0);self.assertEqual([s['stack'] for s in r['seats']],[1000,1000])
    def test_single_player_deals_on_one_confirmation_and_next_round_is_not_confirmed(self):
        self.rid=self.call('/api/online/rooms',{'game_type':'blackjack'})['id'];self.path=f'/api/online/rooms/{self.rid}'
        self.confirm();r=online.get_room(self.db,self.rid);self.assertEqual(r['hand_no'],1)
        while r['status']=='playing':
            a.act(r,r['hand']['actor'],'stand',self.clock+3)
        online.save(self.db,r,self.clock+3)
        self.assertFalse(a.public_view(r,1)['seats'][0]['blackjack_ready'])
        self.assertTrue(self.confirm(number=1,op='bj_old_round_start_01',at=10)['conflict'])
        self.confirm(number=2,op='bj_next_round_start_1',at=10)
        self.assertEqual(online.get_room(self.db,self.rid)['hand_no'],2)
    def test_all_player_hands_visible_but_dealer_hole_card_remains_private(self):
        r=a.new_room('Shared cards',1,'blackjack');a.sit(r,1,'A',1);a.sit(r,2,'B',1)
        deck=[c for c in p.DECK if c not in ['8c','9d','6s','7c','8h','9s']]+list(reversed(['8c','9d','6s','7c','8h','9s']))
        a.start_hand(r,10,deck)
        v=a.public_view(r,1);self.assertEqual(v['hand']['dealer'][1],None)
        self.assertTrue(all(len(q['hands'][0]['cards'])==2 for q in v['hand']['players']))
        self.assertNotIn('deck',v['hand']);self.assertNotIn('deck',v.get('blackjack_shoe',{}))

if __name__=='__main__':unittest.main()
