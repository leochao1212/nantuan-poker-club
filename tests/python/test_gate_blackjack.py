"""Individual blackjack wagers and fair, receipt-safe In Between rounds."""
from copy import deepcopy
from fractions import Fraction
import json,unittest
import arcade_engine as a,bonus_engine as b,poker_engine as p,online,wallet,game_settings
from . import test_club

def deck_order(cards):return [c for c in p.DECK if c not in cards]+list(reversed(cards))
def points(r):return r['bank']+sum(s['stack'] for s in r['seats'])+(sum(q['contribution'] for q in r['hand']['players']) if r['status']=='playing' else 0)
def blackjack(count=2):
    r=a.new_room('Separate wagers',1,'blackjack',buy_in=2000,stake=10)
    for uid in range(1,count+1):a.sit(r,uid,str(uid),0)
    return r
def gate(left='3c',right='Kc',third='7d'):
    r=b.new_room('Gate',1,'inbetween',buy_in=2000,stake=10);b.sit(r,1,'P1',0)
    b.start_hand(r,1,deck=deck_order([left,right,third]));return r

class BlackjackWagers(unittest.TestCase):
    def test_personal_bets_and_settlement_use_each_players_amount(self):
        r=blackjack();total=points(r);a.set_blackjack_bet(r,1,100);a.set_blackjack_bet(r,2,200)
        a.start_hand(r,1,deck=deck_order(['8c','8d','9c','7c','7d','7h','Kh']))
        self.assertEqual([q['hands'][0]['bet'] for q in r['hand']['players']],[100,200]);self.assertEqual([q['contribution'] for q in r['hand']['players']],[100,200])
        with self.assertRaises(p.RuleError):a.set_blackjack_bet(r,1,50)
        while r['status']=='playing':a.act(r,r['hand']['actor'],'stand',2)
        self.assertEqual([x['payout'] for x in r['hand']['results']],[200,400]);self.assertEqual(points(r),total)
        self.assertEqual(r['stake'],10)

    def test_invalid_or_unfunded_bet_cannot_change_preference(self):
        r=blackjack(1)
        for amount in (None,True,0,1,3,1001,100.5,'100'):
            before=deepcopy(r)
            with self.assertRaises(p.RuleError):a.set_blackjack_bet(r,1,amount)
            self.assertEqual(r,before)
        r['seats'][0]['stack']=50
        with self.assertRaises(p.RuleError):a.set_blackjack_bet(r,1,100)

    def test_personal_bet_reserves_split_double_and_natural_returns(self):
        r=blackjack();a.set_blackjack_bet(r,1,100);a.set_blackjack_bet(r,2,200);r['bank']=2399
        before=deepcopy(r)
        with self.assertRaises(p.RuleError):a.start_hand(r,1)
        self.assertEqual(r,before)
        r=blackjack(1);a.set_blackjack_bet(r,1,100)
        a.start_hand(r,1,deck=deck_order(['As','9c','Kh','7h','Qd']))
        self.assertEqual(r['hand']['results'][0]['payout'],250)

class GateRules(unittest.TestCase):
    def test_each_pair_has_exact_remaining_deck_probability_and_bounded_rtp(self):
        for low in range(1,14):
            for high in range(low,14):
                left='A23456789TJQK'[low-1]+'c';right='A23456789TJQK'[high-1]+('d' if low==high else 'c')
                third=next(c for c in p.DECK if c not in (left,right));r=gate(left,right,third);h=r['hand']
                self.assertEqual(len(h['deck']),50)
                quotes=b.gate_quotes(h)
                for direction,q in quotes.items():
                    wins=sum((b.gate_rank(c)>low if direction=='up' else b.gate_rank(c)<low if direction=='down' else low<b.gate_rank(c)<high) for c in h['deck'])
                    self.assertEqual(q['winning_cards'],wins)
                    for stake in (1,10,100,1000):
                        gross=b.gate_return(stake,wins,9700,q['post_cards'],q['loss_multiplier'])
                        paid=stake*(50+(q['loss_multiplier']-1)*q['post_cards'])
                        rtp=Fraction(wins*gross,paid)
                        self.assertLessEqual(rtp,Fraction(97,100));self.assertLess(Fraction(97,100)-rtp,Fraction(wins,paid))
                if not quotes:self.assertEqual(b.legal_actions(r,1)['actions'],['skip'])

    def test_win_post_outside_and_skip_conserve_chips_and_do_not_precharge(self):
        for third,label in [('7d','射中龍門'),('3d','撞柱'),('Ac','射出門外')]:
            r=gate(third=third);total=points(r);self.assertEqual(r['seats'][0]['stack'],2000);self.assertEqual(r['hand']['players'][0]['contribution'],0)
            b.act(r,1,'shoot',2,{'stake':100});result=r['hand']['results'][0];self.assertEqual(result['rank'],label)
            self.assertEqual(result['payout'],150 if label=='射中龍門' else 0);self.assertEqual(points(r),total)
            self.assertEqual(r['next_hand_at'],2)
        r=gate();b.act(r,1,'skip',2);self.assertEqual(r['seats'][0]['stack'],2000);self.assertEqual(r['hand']['results'][0]['profit'],0)

    def test_illegal_bets_bank_limit_and_zero_gap_never_take_points(self):
        for value in (None,True,0,-1,1001,'100',1.5):
            r=gate();before=deepcopy(r)
            with self.assertRaises(p.RuleError):b.act(r,1,'shoot',2,{'stake':value})
            self.assertEqual(r,before)
        r=gate();r['bank']=0;before=deepcopy(r)
        with self.assertRaises(p.RuleError):b.act(r,1,'shoot',2,{'stake':100})
        self.assertEqual(r,before)
        r=gate('Ac','2c','7d');before=deepcopy(r)
        with self.assertRaises(p.RuleError):b.act(r,1,'shoot',2,{'stake':100})
        self.assertEqual(r,before)

    def test_private_deck_fixed_settings_timeout_and_leave(self):
        r=gate();v=b.public_view(r,1);self.assertNotIn('deck',v['hand']);self.assertIsNone(v['hand']['third']);self.assertEqual(v['hand']['board'],[])
        r['hand']['game_settings']['params']['target_bps']=9000
        old=deepcopy(game_settings.DEFAULTS['inbetween']);game_settings.DEFAULTS['inbetween']['target_bps']=30000
        try:b.act(r,1,'shoot',2,{'stake':100});self.assertEqual(r['hand']['results'][0]['payout'],150)
        finally:game_settings.DEFAULTS['inbetween']=old
        r=gate();self.assertTrue(b.tick(r,32));self.assertEqual(r['seats'][0]['stack'],2000)
        r=gate();b.leave(r,1,2);self.assertEqual(r['status'],'closed');self.assertEqual(r['departures'][0]['stack'],2000)

class GateTransactions(unittest.TestCase):
    setUp=test_club.WalletRules.setUp
    def call(self,path,data,uid=1,at=1):return online.mutate(self.db,path,data,self.users[uid-1],self.clock+at)

    def test_start_shoot_retry_conflict_leave_and_projection_are_consistent(self):
        made=self.call('/api/online/rooms',{'game_type':'inbetween','operation_id':'gate_create_00000001'});rid=made['id'];path=f'/api/online/rooms/{rid}'
        request={'operation_id':'gate_start_000000001'};self.call(path+'/start',request);self.assertTrue(self.call(path+'/start',request)['replayed'])
        r=online.get_room(self.db,rid);shoe=deck_order(['3c','Kc','7d']);shoe.pop();shoe.pop()
        r['hand']['pillars']=['3c','Kc'];r['hand']['deck']=shoe;r['hand'].pop('gate_quotes',None)
        r['hand']['gate_quotes']=b.gate_quotes(r['hand']);online.save(self.db,r,self.clock+1)
        request={'action':'shoot','stake':100,'hand_id':r['hand']['id'],'turn_id':r['hand']['turn_id'],'operation_id':'gate_shoot_000000001'}
        self.call(path+'/action',request,at=2);r=online.get_room(self.db,rid);self.assertEqual(r['seats'][0]['stack'],1050)
        self.assertTrue(self.call(path+'/action',request,at=3)['replayed']);self.assertEqual(online.get_room(self.db,rid)['seats'][0]['stack'],1050)
        conflict=self.call(path+'/action',{**request,'stake':200},at=3);self.assertTrue(conflict['conflict'])
        self.assertEqual(self.db.execute('SELECT hands,profit FROM player_result_totals WHERE user_id=1').fetchone()[:],(1,50))
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_operations WHERE operation_id=?',(request['operation_id'],)).fetchone()[0],1)
        self.call(path+'/leave',{'operation_id':'gate_leave_000000001'},at=4);self.assertEqual(wallet.view(self.db,1,self.clock+4)['balance'],3050)

    def test_saved_blackjack_wager_does_not_change_others_or_wallet(self):
        rid=self.call('/api/online/rooms',{'game_type':'blackjack'})['id'];path=f'/api/online/rooms/{rid}'
        self.call(path+'/join',{'operation_id':'blackjack_join_00001'},uid=2)
        request={'stake':200,'operation_id':'blackjack_bet_000001','user_id':1,'expected_hand_number':1};self.call(path+'/wager',request,uid=2)
        self.assertTrue(self.call(path+'/wager',request,uid=2)['replayed']);r=online.get_room(self.db,rid)
        self.assertNotIn('blackjack_bet',r['seats'][0]);self.assertEqual(r['seats'][1]['blackjack_bet'],200)
        self.call(path+'/start',{'stake':100,'expected_hand_number':1,'operation_id':'blackjack_start_0001'},at=2);self.assertIsNone(online.get_room(self.db,rid)['hand'])
        self.call(path+'/start',{'stake':200,'expected_hand_number':1,'operation_id':'blackjack_start_0002'},uid=2,at=2);r=online.get_room(self.db,rid)
        self.assertEqual([q['contribution'] for q in r['hand']['players']],[100,200]);self.assertEqual(wallet.view(self.db,1,self.clock)['balance'],2000)

if __name__=='__main__':unittest.main()
