"""Independent enumeration and transactional checks for Taiwan-style gate choices."""
from copy import deepcopy
from fractions import Fraction
import json, unittest
import bonus_engine as b, poker_engine as p, online, wallet
import test_club
from test_gate_blackjack import deck_order, points


def make_gate(left='7c',right='7d',third='9h',legacy=False,stack=10000):
    room=b.new_room('Taiwan gate',1,'inbetween',buy_in=stack,stake=100)
    b.sit(room,1,'Player',0)
    b.start_hand(room,1,deck=deck_order([left,right,third]))
    if legacy:room['hand'].pop('gate_rules_version')
    return room


class TaiwanGateRules(unittest.TestCase):
    def test_all_rank_pairs_directions_and_third_cards_settle_conservatively(self):
        ranks='A23456789TJQK'
        for low in range(1,14):
            for high in range(low,14):
                left=ranks[low-1]+'c';right=ranks[high-1]+('d' if low==high else 'c')
                available=[card for card in p.DECK if card not in (left,right)]
                directions=['up','down'] if low==high else ['between']
                for direction in directions:
                    wins=[card for card in available if (b.gate_rank(card)>low if direction=='up' else b.gate_rank(card)<low if direction=='down' else low<b.gate_rank(card)<high)]
                    if not wins:continue
                    total_paid=total_gross=0;penalty=3 if low==high else 2
                    # Independently sum the actual deductions across all 50 outcomes.
                    expected_paid=100*sum(penalty if b.gate_rank(c) in (low,high) else 1 for c in available)
                    exact_gross=Fraction(97*expected_paid,100*len(wins));gross=exact_gross.numerator//exact_gross.denominator
                    for third in available:
                        with self.subTest(low=low,high=high,direction=direction,third=third):
                            room=make_gate(left,right,third);before=points(room)
                            b.act(room,1,'shoot',2,{'stake':100,'direction':direction})
                            h=room['hand'];result=h['results'][0];won=third in wins
                            charge=100*(penalty if b.gate_rank(third) in (low,high) else 1)
                            self.assertEqual(h['charged'],charge);self.assertEqual(result['payout'],gross if won else 0)
                            self.assertEqual(result['profit'],(gross if won else 0)-charge)
                            self.assertEqual(room['seats'][0]['stack'],10000+result['profit'])
                            self.assertEqual(points(room),before);self.assertGreaterEqual(room['bank'],0)
                            total_paid+=charge;total_gross+=result['payout']
                    self.assertEqual(expected_paid,total_paid)
                    self.assertLessEqual(Fraction(total_gross,total_paid),Fraction(97,100))

    def test_pairs_require_direction_and_edge_pairs_disable_impossible_choice(self):
        for left,right,allowed in [('7c','7d',['up','down']),('Ac','Ad',['up']),('Kc','Kd',['down'])]:
            room=make_gate(left,right,'9h');self.assertEqual(b.legal_actions(room,1)['directions'],allowed)
            for direction in (None,True,[],{},'between','sideways',*(set(['up','down'])-set(allowed))):
                before=deepcopy(room)
                with self.assertRaises(p.RuleError):b.act(room,1,'shoot',2,{'stake':100,'direction':direction})
                self.assertEqual(room,before)

    def test_maximum_loss_must_be_funded_and_actual_loss_is_not_precharged(self):
        for pair,stack,max_stake,third,direction,charge in [(False,199,99,'5d','between',198),(True,299,99,'7h','up',297)]:
            left,right=('7c','7d') if pair else ('5c','Kc')
            room=make_gate(left,right,third,stack=stack)
            self.assertEqual(b.legal_actions(room,1)['max_stake'],max_stake)
            self.assertEqual(room['hand']['players'][0]['contribution'],0)
            before=deepcopy(room)
            with self.assertRaises(p.RuleError):b.act(room,1,'shoot',2,{'stake':100,'direction':direction})
            self.assertEqual(room,before)
            b.act(room,1,'shoot',2,{'stake':99,'direction':direction});self.assertEqual(room['hand']['charged'],charge)
            self.assertEqual(room['seats'][0]['stack'],stack-charge)
        room=make_gate(stack=2);self.assertEqual(b.legal_actions(room,1)['actions'],['skip'])
        b.act(room,1,'skip',2);self.assertEqual(room['seats'][0]['stack'],2)

    def test_house_funding_invalid_direction_and_wrong_actor_leave_state_untouched(self):
        room=make_gate();room['bank']=117;before=deepcopy(room)
        with self.assertRaises(p.RuleError):b.act(room,1,'shoot',2,{'stake':100,'direction':'up'})
        self.assertEqual(room,before)
        room['bank']=118;before=points(room);b.act(room,1,'shoot',2,{'stake':100,'direction':'up'})
        self.assertEqual(room['bank'],0);self.assertEqual(points(room),before)
        room=make_gate();before=deepcopy(room)
        with self.assertRaises(p.RuleError):b.act(room,2,'shoot',2,{'stake':100,'direction':'up'})
        self.assertEqual(room,before)

    def test_legacy_rounds_keep_original_single_stake_penalty_and_payout(self):
        for third,payout,charge in [('7d',134,100),('3d',0,100),('Ac',0,100)]:
            room=make_gate('3c','Kc',third,legacy=True);b.act(room,1,'shoot',2,{'stake':100})
            self.assertEqual(room['hand']['results'][0]['payout'],payout);self.assertEqual(room['hand']['charged'],charge)
        room=make_gate(legacy=True);self.assertEqual(b.legal_actions(room,1)['actions'],['skip'])
        b.act(room,1,'skip',2);b.start_hand(room,3,deck=deck_order(['7c','7d','7h']))
        self.assertEqual(room['hand']['gate_rules_version'],2)

    def test_public_quotes_never_depend_on_secret_third_or_deck_order(self):
        first=make_gate(third='8h');second=make_gate(third='2h')
        a=b.public_view(first,1)['hand'];c=b.public_view(second,2)['hand']
        self.assertEqual(a['gate_quotes'],c['gate_quotes']);self.assertNotIn('deck',a);self.assertIsNone(a['third'])
        self.assertEqual(a['gate_quotes']['up']['winning_cards'],24)
        # JSON restart retains both the rule version and the frozen payout settings.
        restored=json.loads(json.dumps(first));restored['hand']['game_settings']['params']['target_bps']=9000
        b.act(restored,1,'shoot',2,{'stake':100,'direction':'up'})
        self.assertEqual(restored['hand']['results'][0]['payout'],202)
        for mode in ('timeout','leave'):
            room=make_gate()
            if mode=='timeout':b.tick(room,40);self.assertFalse(b.tick(room,41));self.assertEqual(room['seats'][0]['stack'],10000)
            else:b.leave(room,1,2);self.assertEqual(room['departures'][0]['stack'],10000)


class TaiwanGateReceipts(unittest.TestCase):
    setUp=test_club.WalletRules.setUp

    def test_direction_is_part_of_receipt_and_post_retry_deducts_once(self):
        user=self.users[0];clock=self.clock
        rid=online.mutate(self.db,'/api/online/rooms',{'game_type':'inbetween','operation_id':'taiwan_create_00001'},user,clock)['id'];path=f'/api/online/rooms/{rid}'
        online.mutate(self.db,path+'/start',{'operation_id':'taiwan_start_000001'},user,clock+1)
        room=online.get_room(self.db,rid);room['hand']['pillars']=['7c','7d'];room['hand']['deck']=deck_order(['7h']);online.save(self.db,room,clock+1)
        data={'action':'shoot','direction':'up','stake':100,'hand_id':room['hand']['id'],'turn_id':room['hand']['turn_id'],'operation_id':'taiwan_shoot_000001'}
        online.mutate(self.db,path+'/action',data,user,clock+2)
        self.assertTrue(online.mutate(self.db,path+'/action',data,user,clock+3)['replayed'])
        self.assertTrue(online.mutate(self.db,path+'/action',{**data,'direction':'down'},user,clock+3)['conflict'])
        self.assertTrue(online.mutate(self.db,path+'/action',{**data,'operation_id':'taiwan_shoot_000002'},user,clock+3)['conflict'])
        room=online.get_room(self.db,rid);self.assertEqual(room['seats'][0]['stack'],700)
        self.assertEqual(room['hand']['results'][0]['profit'],-300)
        self.assertEqual(self.db.execute('SELECT hands,profit FROM player_result_totals WHERE user_id=1').fetchone()[:],(1,-300))
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_operations WHERE operation_id=?',(data['operation_id'],)).fetchone()[0],1)
        online.mutate(self.db,path+'/leave',{'operation_id':'taiwan_leave_000001'},user,clock+4)
        self.assertEqual(wallet.view(self.db,1,clock+4)['balance'],2700)


if __name__=='__main__':unittest.main()
