"""Deterministic natural-frequency, shoe source and settlement regression checks."""
from collections import Counter
from fractions import Fraction
from itertools import combinations
from unittest.mock import patch
import unittest
import arcade_engine as a,poker_engine as p
from .test_arcade import room,shoe,points

class BlackjackFairness(unittest.TestCase):
    def test_exact_fresh_six_deck_natural_probability(self):
        cards=p.DECK*6
        hits=sum(a.blackjack_natural(pair) for pair in combinations(cards,2))
        self.assertEqual(hits,24*96)
        self.assertEqual(Fraction(hits,len(cards)*(len(cards)-1)//2),Fraction(384,8086))
        self.assertFalse(a.blackjack_natural(['Ac','5c','5d']))

    def test_secure_shuffle_once_then_round_robin_draws_from_same_private_shoe(self):
        r=room('blackjack',2)
        with patch.object(a.secrets,'SystemRandom') as secure:
            captured=[];secure.return_value.shuffle.side_effect=lambda cards:captured.extend(cards)
            a.start_hand(r,101)
            shuffled=captured
            self.assertEqual(Counter(shuffled),Counter(p.DECK*6))
            self.assertEqual([x['hands'][0]['cards'] for x in r['hand']['players']],[['As','Js'],['Ks','Ts']])
            self.assertEqual(r['hand']['dealer'],['Qs','9s'])
            remaining=list(r['hand']['deck']);ident=r['hand']['shoe_id']
            while r['status']=='playing':a.act(r,r['hand']['actor'],'stand',102)
            # Dealer has 19, so it must not draw another card.
            self.assertEqual(r['hand']['deck'],remaining)
            a.start_hand(r,r['next_hand_at']+1)
            self.assertEqual(r['hand']['shoe_id'],ident)
            self.assertEqual(r['hand']['shoe_round'],2)
            self.assertEqual(secure.return_value.shuffle.call_count,1)
            public=a.public_view(r,1)['hand'];self.assertNotIn('deck',public)
            self.assertEqual(public['dealer'][1],None)

    def test_three_card_twenty_one_is_not_blackjack_and_points_conserve(self):
        r=room('blackjack',1);before=points(r)
        a.start_hand(r,101,shoe(['6c','Tc','5d','7c','Th']))
        a.act(r,1,'hit',102)
        self.assertEqual(r['hand']['players'][0]['hands'][0]['outcome'],'勝出')
        self.assertFalse(r['hand']['dealer_natural'])
        self.assertEqual(points(r),before)

    def test_ten_point_density_counts_all_face_cards_and_depletes_without_replacement(self):
        cards=list(p.DECK)*6
        self.assertEqual(sum(c[0] in 'TJQK' for c in cards),96)
        cards.remove('Tc');cards.remove('Qd')
        self.assertEqual(Fraction(sum(c[0] in 'TJQK' for c in cards),len(cards)),Fraction(94,310))
        self.assertEqual(sum(a.blackjack_total(['Tc','Qd',c])<=21 for c in cards),24)
        self.assertEqual(sum(a.blackjack_total(['Tc','Qd',c])>21 for c in cards),286)

    def test_five_card_dealer_twenty_one_is_normal_twenty_one_and_loses_to_natural(self):
        for player,natural in ((['Tc','Qd'],False),(['Ac','Kd'],True)):
            r=room('blackjack',1);before=points(r)
            a.start_hand(r,101,shoe([player[0],'2c',player[1],'3d','4h','5s','7c']))
            if r['status']=='playing':a.act(r,1,'stand',102)
            self.assertEqual(r['hand']['dealer'],['2c','3d','4h','5s','7c'])
            self.assertFalse(r['hand']['dealer_natural']);self.assertEqual(a.blackjack_total(r['hand']['dealer']),21)
            h=r['hand']['players'][0]['hands'][0]
            self.assertEqual(h['outcome'],'Blackjack' if natural else '落敗')
            self.assertEqual(h['payout'],25 if natural else 0);self.assertEqual(points(r),before)

if __name__=='__main__':unittest.main()
