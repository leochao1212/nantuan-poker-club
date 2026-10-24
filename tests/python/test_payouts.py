"""Independent payout oracles: net wins versus returned stakes, all four games."""
from fractions import Fraction
import unittest
from unittest.mock import patch
import arcade_engine as a,poker_engine as p
from .test_arcade import room,shoe,points
from .test_poker import room_with_players

class PayoutAudit(unittest.TestCase):
    def test_every_roulette_target_against_independent_winning_sets(self):
        red={1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
        targets=[({'kind':'number','number':i,'amount':10},{i},35) for i in range(37)]
        outside={'red':red,'black':set(range(1,37))-red,'odd':set(range(1,37,2)),'even':set(range(2,37,2)),
                 'low':set(range(1,19)),'high':set(range(19,37)),
                 'dozen1':set(range(1,13)),'dozen2':set(range(13,25)),'dozen3':set(range(25,37)),
                 'column1':set(range(1,37,3)),'column2':set(range(2,37,3)),'column3':set(range(3,37,3))}
        targets += [({'kind':kind,'amount':10},wins,2 if kind.startswith(('dozen','column')) else 1) for kind,wins in outside.items()]
        for bet,wins,rate in targets:
            for number in range(37):
                with self.subTest(bet=bet,number=number):
                    r=room('roulette',1);a.start_hand(r,101)
                    with patch.object(a.secrets,'randbelow',return_value=number):a.act(r,1,'bet',102,{'bets':[bet]})
                    result=r['hand']['results'][0]
                    self.assertEqual(result['profit'],10*rate if number in wins else -10)
                    self.assertEqual(result['payout'],10*(rate+1) if number in wins else 0)

    def test_blackjack_golden_payouts_at_small_normal_and_large_even_stakes(self):
        fixtures=[
            ('natural','As 9d Kh 8c',[],Fraction(3,2),Fraction(5,2)),
            ('regular_win','Ts 9d Qh 9c',['stand'],1,2),
            ('regular_loss','Ts 9d 7h 9c',['stand'],-1,0),
            ('push','Ts 9d 8h 9c',['stand'],0,1),
            ('bust','Ts 9d 6h 9c Kd',['hit'],-1,0),
            ('double_win','5s 9d 6h 8c Td',['double'],2,4),
            ('double_loss','5s 9d 6h Tc 2d',['double'],-2,0),
            ('split_one_win_one_loss','8s 9d 8h 8c 3d Tc',['split','stand','stand'],0,2),
            ('split_aces_regular_21','As 9d Ah 8c Td Kc',['split'],2,4),
            ('natural_push','As Ah Ks Kd',[],0,1),
            ('dealer_natural','8s As 8h Kd',[],-1,0),
        ]
        for stake in (2,10,1000):
            for label,draws,actions,net,gross in fixtures:
                with self.subTest(label=label,stake=stake):
                    r=room('blackjack',1,stake=stake,stack=10000);before=points(r)
                    a.start_hand(r,101,shoe(draws.split()))
                    for action in actions:a.act(r,1,action,102)
                    self.assertEqual(r['status'],'waiting')
                    result=r['hand']['results'][0]
                    self.assertEqual(result['profit'],int(stake*net));self.assertEqual(result['payout'],int(stake*gross))
                    self.assertEqual(points(r),before)

    def test_big_two_remaining_cards_pay_winner_without_house_fee(self):
        for stake in (1,10,1000):
            r=room('big2',4,stake=stake,stack=52*stake);before=points(r);a.start_hand(r,101)
            for seat in r['seats']:seat['away']=True
            a.tick(r,102);results=r['hand']['results']
            winner=next(q for q in results if q['profit']>0)
            loss=sum(q['charged'] for q in results)
            self.assertEqual(winner['profit'],loss)
            for q in results:
                if q is not winner:self.assertEqual(q['profit'],-q['remaining']*stake*(4 if q['remaining']==13 else 2 if q['remaining']>=8 else 1))
            self.assertEqual(sum(q['profit'] for q in results),0);self.assertEqual(points(r),before)

    def test_holdem_main_side_pots_uncalled_refund_and_tie_have_no_commission(self):
        for contributions,expected in (({1:100,2:300,3:300},{1:300,2:400,3:0}),({1:100,2:300,3:500},{1:300,2:400,3:200})):
            r=room_with_players(3);p.start_hand(r,1);h=r['hand'];h['board']='2c 3d 7h 9s Jc'.split()
            holes={1:'As Ad',2:'Ks Kd',3:'Qs Qd'}
            for q in h['players']:
                uid=q['user_id'];q.update(stack=0,starting_stack=contributions[uid],contribution=contributions[uid],street_bet=contributions[uid],hole=holes[uid].split(),folded=False)
            p.finish(r,2)
            self.assertEqual({q['user_id']:q['payout'] for q in h['results']},expected)
            self.assertEqual(sum(q['payout'] for q in h['results']),sum(contributions.values()))
            self.assertEqual(sum(q['profit'] for q in h['results']),0)
        r=room_with_players(3);p.start_hand(r,1);h=r['hand'];h['board']='As Ks Qs Js Ts'.split()
        for q in h['players']:
            value=1 if q['user_id']==3 else 5
            q.update(stack=0,starting_stack=value,contribution=value,street_bet=value,hole={1:['2c','3c'],2:['4c','5c'],3:['6c','7c']}[q['user_id']],folded=q['user_id']==3)
        p.finish(r,2)
        self.assertEqual(sorted(q['payout'] for q in h['results']),[0,5,6]);self.assertEqual(sum(q['profit'] for q in h['results']),0)

if __name__=='__main__':unittest.main()
