"""Public, frozen settlement benefits improve player outcomes without changing any card."""
from copy import deepcopy
from fractions import Fraction
from unittest.mock import patch
import json,unittest
import arcade_engine as a,game_settings as g,poker_engine as p
from .test_arcade import room,shoe,points
from . import test_game_settings as settings_tests
from . import test_club as club_tests
import online,wallet

def settings(tie=5000,bust=2500):
    cfg=g.default('blackjack');cfg['params'].update(tie_win_bps=tie,bust_refund_bps=bust);return cfg

class BlackjackBenefits(unittest.TestCase):
    def test_tie_threshold_and_frozen_settings_preserve_cards_and_points(self):
        for ticket,win in ((0,True),(4999,True),(5000,False),(9999,False)):
            r=room('blackjack',1,stake=100);before=points(r);cfg=settings()
            a.start_hand(r,101,shoe(['Tc','9c','8d','9d']),settings=cfg)
            tail=r['hand']['deck'][:];cfg['params']['tie_win_bps']=0
            with patch.object(a.secrets,'randbelow',return_value=ticket) as rng:a.act(r,1,'stand',102)
            rng.assert_called_once_with(10000);h=r['hand']['players'][0]['hands'][0]
            self.assertEqual(h['cards'],['Tc','8d']);self.assertEqual(r['hand']['deck'],tail)
            self.assertEqual(h['payout'],200 if win else 100);self.assertEqual(h['benefit']['triggered'],win)
            self.assertEqual(points(r),before)

    def test_bust_threshold_refunds_whole_hand_without_changing_the_bust(self):
        for ticket,protected in ((2499,True),(2500,False)):
            r=room('blackjack',1,stake=100);before=points(r)
            a.start_hand(r,101,shoe(['9c','9d','7h','9h','Ts']),settings=settings())
            with patch.object(a.secrets,'randbelow',return_value=ticket) as rng:a.act(r,1,'hit',102)
            rng.assert_called_once_with(10000);h=r['hand']['players'][0]['hands'][0]
            self.assertEqual(a.blackjack_total(h['cards']),26);self.assertEqual(h['payout'],100 if protected else 0)
            self.assertEqual(h['benefit']['kind'],'bust_refund');self.assertEqual(points(r),before)

    def test_double_refund_uses_actual_doubled_bet_not_a_new_reward(self):
        r=room('blackjack',1,stake=100);before=points(r)
        a.start_hand(r,101,shoe(['Tc','9c','8d','9d','Ts']),settings=settings(10000,10000))
        with patch.object(a.secrets,'randbelow',side_effect=AssertionError('100% needs no RNG')):a.act(r,1,'double',102)
        h=r['hand']['players'][0]['hands'][0];self.assertEqual((h['bet'],h['payout']),(200,200))
        self.assertEqual(r['hand']['results'][0]['profit'],0);self.assertEqual(points(r),before)

    def test_split_settles_each_hand_once_and_publicly_shows_benefits(self):
        r=room('blackjack',1,stake=100);before=points(r)
        a.start_hand(r,101,shoe(['8c','9c','8h','9h','Tc','7c','Ts']),settings=settings(10000,10000))
        a.act(r,1,'split',102);a.act(r,1,'stand',103);a.act(r,1,'hit',104)
        hands=r['hand']['players'][0]['hands'];self.assertEqual([h['payout'] for h in hands],[200,100])
        self.assertEqual([h['benefit']['kind'] for h in hands],['tie_win','bust_refund'])
        self.assertEqual(r['hand']['results'][0]['profit'],100);self.assertEqual(points(r),before)
        public=a.public_view(r,99)['hand'];self.assertNotIn('deck',public);self.assertTrue(public['players'][0]['hands'][1]['benefit']['triggered'])

    def test_naturals_and_legacy_snapshots_do_not_receive_tie_bonuses(self):
        r=room('blackjack',1,stake=100)
        with patch.object(a.secrets,'randbelow',side_effect=AssertionError('Natural push cannot roll')):
            a.start_hand(r,101,shoe(['Ac','Ah','Tc','Th']),settings=settings(10000,10000))
        h=r['hand']['players'][0]['hands'][0];self.assertEqual(h['payout'],100);self.assertNotIn('benefit',h)
        cfg=settings();cfg['params'].pop('tie_win_bps');cfg['params'].pop('bust_refund_bps')
        r=room('blackjack',1,stake=100);a.start_hand(r,101,shoe(['Tc','9c','8d','9d']),settings=cfg)
        with patch.object(a.secrets,'randbelow',side_effect=AssertionError('Legacy cannot roll')):a.act(r,1,'stand',102)
        self.assertEqual(r['hand']['players'][0]['hands'][0]['payout'],100)

    def test_exact_expected_uplift_is_nonnegative_for_each_eligible_hand(self):
        for bet in (2,100,10000):
            extra_win=g.net_return(bet,10000)-bet
            self.assertEqual(Fraction(5000,10000)*extra_win,Fraction(bet,2))
            self.assertEqual(Fraction(2500,10000)*bet,Fraction(bet,4))

class BenefitSettings(unittest.TestCase):
    setUp=settings_tests.SettingsRules.setUp
    update=settings_tests.SettingsRules.update

    def test_existing_club_activation_is_logged_once_and_preserves_custom_payouts(self):
        old={'win_bp':12000,'blackjack_bp':18000,'five_card_bp':25000,'decks':6}
        self.db.execute("UPDATE game_settings SET params=?,revision=8 WHERE game_type='blackjack'",(g.encode(old),))
        g.initialize(self.db);saved=g.current(self.db,'blackjack');g.initialize(self.db)
        self.assertEqual(saved,g.current(self.db,'blackjack'));self.assertEqual(saved['revision'],9)
        self.assertEqual(saved['params'],{**old,'tie_win_bps':5000,'bust_refund_bps':2500})
        self.assertEqual(self.db.execute('SELECT count(*) FROM game_settings_migrations').fetchone()[0],1)
        self.assertEqual(g.admin_view(self.db,{'id':1})['history'][0]['actor'],'系統移轉（站長授權）')
        self.update('blackjack',{'tie_win_bps':0,'bust_refund_bps':0});g.initialize(self.db)
        self.assertEqual(g.current(self.db,'blackjack')['params']['tie_win_bps'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM game_settings_migrations').fetchone()[0],1)

    def test_admin_percent_boundaries_and_metrics_are_public(self):
        for key in ('tie_win_bps','bust_refund_bps'):
            for bad in (-1,10001,True,.5,'50'):
                with self.assertRaises(p.RuleError):self.update('blackjack',{key:bad})
        self.update('blackjack',{'tie_win_bps':5000,'bust_refund_bps':2500})
        s=g.public(g.current(self.db,'blackjack'));self.assertEqual(s['metrics']['tie_win_percent'],50)
        self.assertEqual(s['metrics']['bust_refund_percent'],25);self.assertNotIn('rtp_percent',s['metrics'])

class BenefitReceipts(unittest.TestCase):
    setUp=club_tests.WalletRules.setUp

    def test_confirm_action_retry_and_cashout_preserve_one_benefit_credit(self):
        self.db.execute('INSERT INTO club_admins VALUES(1,0,?)',(self.clock,))
        cfg=g.current(self.db,'blackjack')
        g.update(self.db,{'id':1},{'game_type':'blackjack','revision':cfg['revision'],'params':{**cfg['params'],'tie_win_bps':10000,'bust_refund_bps':10000},'note':'Synthetic public benefits','operation_id':'benefit_settings_receipt_01'},self.clock)
        user=self.users[0];rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'blackjack'},user,self.clock)['id'];path=f'/api/online/rooms/{rid}'
        def arrange(cards):
            selected=['Tc','9c','8d','9d'];tail=list(p.DECK)*6
            for c in selected:tail.remove(c)
            cards[:]=tail+list(reversed(selected))
        with patch.object(a.secrets,'SystemRandom') as secure:
            secure.return_value.shuffle.side_effect=arrange
            online.mutate(self.db,path+'/start',{'stake':100,'expected_hand_number':1,'operation_id':'benefit_start_receipt_001'},user,self.clock+1)
        hand=online.get_room(self.db,rid)['hand'];request={'action':'stand','hand_id':hand['id'],'turn_id':hand['turn_id'],'operation_id':'benefit_action_receipt_01'}
        online.mutate(self.db,path+'/action',request,user,self.clock+2);saved=deepcopy(online.get_room(self.db,rid))
        self.assertTrue(online.mutate(self.db,path+'/action',request,user,self.clock+3)['replayed'])
        self.assertTrue(online.mutate(self.db,path+'/action',{**request,'operation_id':'benefit_action_receipt_02'},user,self.clock+3)['conflict'])
        self.assertEqual(online.get_room(self.db,rid),saved)
        self.assertEqual(self.db.execute('SELECT hands,profit FROM player_result_totals WHERE user_id=1').fetchone()[:],(1,100))
        online.mutate(self.db,path+'/leave',{'operation_id':'benefit_leave_receipt_001'},user,self.clock+4)
        self.assertEqual(wallet.view(self.db,1,self.clock+4)['balance'],3100)
