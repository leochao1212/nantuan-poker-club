"""Deterministic fairness invariants; sampling cannot prove random fairness."""
from collections import Counter
from fractions import Fraction
from copy import deepcopy
import json,random,unittest
from unittest.mock import patch
import arcade_engine as a,poker_engine as p
from .test_arcade import room,points

class Fairness(unittest.TestCase):
    def test_exact_roulette_return_for_every_supported_bet_and_outcome(self):
        targets=[{'kind':'number','number':i,'amount':10} for i in range(37)]+[{'kind':k,'amount':10} for k in ('red','black','odd','even','low','high','dozen1','dozen2','dozen3','column1','column2','column3')]
        for bet in targets:
            profit=0
            for number in range(37):
                r=room('roulette',1);before=points(r);a.start_hand(r,101)
                with patch.object(a.secrets,'randbelow',return_value=number) as draw:
                    a.act(r,1,'bet',102,{'bets':[bet],'winning_number':(number+1)%37})
                draw.assert_called_once_with(37)
                self.assertEqual(r['hand']['number'],number)
                self.assertEqual(points(r),before)
                profit+=r['hand']['results'][0]['profit']
            self.assertEqual(Fraction(profit,37*10),Fraction(-1,37),bet)

    def test_fresh_shoes_use_os_randomness_with_correct_card_multiplicity(self):
        class Shuffler:
            calls=[]
            def shuffle(self,shoe):self.calls.append(Counter(shoe));shoe.reverse()
        shuffler=Shuffler()
        for kind,count in (('big2',4),('blackjack',6)):
            with patch.object(a.secrets,'SystemRandom',return_value=shuffler):a.start_hand(room(kind,count),101)
        self.assertEqual(shuffler.calls[0],Counter(p.DECK))
        self.assertEqual(shuffler.calls[1],Counter(list(p.DECK)*6))
        self.assertEqual(len(p.DECK),52);self.assertEqual(len(set(p.DECK)),52)

    def test_account_identity_cannot_change_cards_dealer_or_wheel_outcome(self):
        for kind in ('big2','blackjack','roulette'):
            left=room(kind,4 if kind=='big2' else 2);right=deepcopy(left)
            for s in right['seats']:s.update(nickname='Administrator',profit=999999,is_admin=True)
            if kind=='roulette':
                for r in (left,right):
                    a.start_hand(r,101)
                    with patch.object(a.secrets,'randbelow',return_value=17):
                        for uid in (1,2):a.act(r,uid,'bet',102,{'bets':[{'kind':'red','amount':10}]})
                self.assertEqual(left['hand']['number'],right['hand']['number'])
                self.assertEqual([s['stack'] for s in left['seats']],[s['stack'] for s in right['seats']])
            else:
                deck=p.DECK if kind=='big2' else list(p.DECK)*6
                for r in (left,right):a.start_hand(r,101,deck)
                for l,r in zip(left['hand']['players'],right['hand']['players']):self.assertEqual(l.get('cards',l.get('hands')),r.get('cards',r.get('hands')))
                self.assertEqual(left['hand'].get('dealer'),right['hand'].get('dealer'))

    def test_blackjack_random_split_double_rounds_keep_shoe_and_point_invariants(self):
        rng=random.Random(714)
        for _ in range(200):
            r=room('blackjack',6);before=points(r);a.start_hand(r,101)
            while r['status']=='playing':
                uid=r['hand']['actor'];actions=a.legal_actions(r,uid)['actions']
                a.act(r,uid,rng.choice(actions),102)
            self.assertEqual(points(r),before)
            used=Counter(r['hand']['deck'])+Counter(r['hand']['dealer'])
            for q in r['hand']['players']:
                for h in q['hands']:used+=Counter(h['cards'])
            self.assertEqual(used,Counter(list(p.DECK)*6))

    def test_big_two_views_never_contain_other_players_cards_or_unused_deck(self):
        for count in (4,):
            r=room('big2',count);a.start_hand(r,101)
            for uid in range(1,count+1):
                view=a.public_view(r,uid)
                self.assertNotIn('deck',view['hand']);self.assertNotIn('bank',view)
                self.assertEqual(sum(len(q['cards']) for q in view['hand']['players']),13)
                self.assertTrue(all(not q['cards'] for q in view['hand']['players'] if q['user_id']!=uid))

if __name__=='__main__':unittest.main()
