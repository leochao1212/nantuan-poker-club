"""Refund protection consumes one actual card, waives all charge, and retains gross odds."""
from copy import deepcopy
from fractions import Fraction
from itertools import permutations
from unittest.mock import patch
import unittest
import bonus_engine as b,poker_engine as poker
from .test_gate_protection import room
from .test_gate_blackjack import points

class GateRefund(unittest.TestCase):
    def test_enumerates_physical_posts_waivers_charges_and_payouts(self):
        for rate in (0,5000,10000):
            wins=posts=waivers=paid=returned=0
            for order in permutations(['5d','9d','7h','2h']):
                for ticket in (0,5000):
                    r=room(rate,version=4);h=r['hand'];h['deck']=list(order);h.pop('gate_quotes');h['gate_quotes']=b.gate_quotes(h)
                    quote=deepcopy(h['gate_quotes']['between']);before=points(r);tail=list(h['deck'])
                    with patch.object(b.secrets,'randbelow',return_value=ticket):b.act(r,1,'shoot',2,{'stake':100})
                    self.assertEqual(points(r),before);self.assertEqual(h['third'],tail[-1]);self.assertEqual(h['deck'],tail[:-1])
                    self.assertEqual(h['protected_discards'],[]);self.assertEqual(h['gate_quotes']['between'],quote)
                    posts+=b.gate_rank(h['third']) in (5,9);waivers+=h['post_protection_triggered'];wins+=h['results'][0]['payout']>0
                    paid+=h['charged'];returned+=h['results'][0]['payout']
            self.assertEqual(posts,24);self.assertEqual(Fraction(wins,48),Fraction(1,4))
            self.assertEqual(Fraction(waivers,48),Fraction(quote['protected_numerator'],quote['protected_denominator']))
            self.assertEqual(Fraction(posts-waivers,48),Fraction(quote['post_numerator'],quote['post_denominator']))
            self.assertEqual(Fraction(paid,4800),Fraction(quote['charge_numerator'],quote['charge_denominator']))
            self.assertAlmostEqual(100*returned/paid,quote['rtp_percent'])

    def test_boundary_ordinary_and_pair_keep_original_card_and_all_chips(self):
        for cards,direction,loss in ((['5c','9c','5d','9d','2h'],None,2),(['7c','7d','7h','2h'],'up',3)):
            for ticket,triggered in ((4999,True),(5000,False)):
                r=room(cards=cards,version=4);h=r['hand'];before=points(r);stack=r['seats'][0]['stack'];tail=list(h['deck'])
                with patch.object(b.secrets,'randbelow',return_value=ticket) as rng:b.act(r,1,'shoot',2,{'stake':100,'direction':direction})
                rng.assert_called_once_with(10000);self.assertEqual(h['third'],cards[2]);self.assertEqual(h['deck'],tail[:-1]);self.assertEqual(points(r),before)
                self.assertEqual(h['charged'],0 if triggered else 100*loss)
                self.assertTrue(h['post_protection_checked'])
                self.assertEqual(r['seats'][0]['stack'],stack if triggered else stack-100*loss)
                if triggered:
                    self.assertEqual(h['results'][0]['profit'],0);self.assertEqual(h['results'][0]['payout'],0)
                    self.assertEqual(h['protection_event'],dict(mode='refund',user_id=1,nickname='Player',card=cards[2],rate_bps=5000,avoided_charge=100*loss))
                    self.assertIn('Player 觸發撞柱保護',r['log'][-2]['text'])
                    public=b.public_view(r,99)['hand'];self.assertEqual(public['protection_event'],h['protection_event']);self.assertNotIn('deck',public)
                else:self.assertIn('保護未觸發',h['results'][0]['rank'])

    def test_full_protection_has_no_rng_no_extra_cards_and_only_one_stake_reserve(self):
        r=room(10000,stack=100,version=4);self.assertEqual(b.legal_actions(r,1)['max_stake'],100)
        tail=list(r['hand']['deck'])
        with patch.object(b.secrets,'randbelow',side_effect=AssertionError('100% protection needs no draw')):b.act(r,1,'shoot',2,{'stake':100})
        self.assertEqual(r['seats'][0]['stack'],100);self.assertEqual(r['hand']['deck'],tail[:-1])

    def test_validation_and_skip_do_not_consume_card_or_protection_roll(self):
        r=room(version=4);r['bank']=0;before=deepcopy(r)
        with patch.object(b.secrets,'randbelow',side_effect=AssertionError('invalid request must not roll')):
            with self.assertRaises(poker.RuleError):b.act(r,1,'shoot',2,{'stake':100})
        self.assertEqual(r,before);tail=list(r['hand']['deck']);b.act(r,1,'skip',2)
        self.assertEqual(r['hand']['deck'],tail);self.assertEqual(r['seats'][0]['stack'],10000)

    def test_gross_multiplier_and_winning_probability_do_not_change_with_protection(self):
        classic=room(0,version=4)['hand']['gate_quotes']['between']
        for rate in (1,5000,9999,10000):
            q=room(rate,version=4)['hand']['gate_quotes']['between']
            self.assertEqual(q['protection_mode'],'refund')
            for key in ('return_numerator','return_denominator','win_numerator','win_denominator'):self.assertEqual(q[key],classic[key])
            self.assertGreater(q['rtp_percent'],classic['rtp_percent'])
