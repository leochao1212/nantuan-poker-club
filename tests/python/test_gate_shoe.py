"""A gate room draws from one private shoe until the next cut-card boundary."""
from fractions import Fraction
import json
import unittest

import game_settings
import bonus_engine as gate
import poker_engine as poker
from .test_gate_blackjack import points


class GateShoeRules(unittest.TestCase):
    def test_rounds_consume_one_shoe_and_reshuffle_only_between_hands(self):
        room=gate.new_room('Continuous gate',1,'inbetween',buy_in=2000,stake=100)
        gate.sit(room,1,'Player',0)
        gate.start_hand(room,1,deck=list(poker.DECK),settings={**game_settings.default('inbetween'),'params':{'target_bps':9700,'post_protection_bps':0}})
        first_id=room['hand']['shoe_id']
        original_points=points(room)
        drawn=[]
        shot=False
        for clock in range(2,35):
            hand=room['hand']
            self.assertEqual(hand['shoe_id'],first_id)
            self.assertEqual(hand['shoe_round'],clock-1)
            self.assertEqual(hand['remaining_cards'],len(hand['deck']))
            self.assertEqual(len(hand['deck']),len(set(hand['deck'])))
            self.assertEqual(len(set(drawn+hand['pillars']+hand['deck'])),52)
            drawn.extend(hand['pillars'])
            self.assertNotIn('gate_shoe',gate.public_view(room,1))
            self.assertNotIn('deck',gate.public_view(room,1)['hand'])

            # Choose one later round to verify settlement against a depleted shoe.
            quotes=gate.gate_quotes(hand)
            if clock>2 and not shot and quotes:
                direction,quote=next(iter(quotes.items()))
                self.assertEqual(quote['total_cards'],len(hand['deck']))
                self.assertEqual(quote['winning_cards'],sum(
                    gate.gate_rank(card)>gate.gate_rank(hand['pillars'][0]) if direction=='up' else
                    gate.gate_rank(card)<gate.gate_rank(hand['pillars'][0]) if direction=='down' else
                    gate.gate_rank(hand['pillars'][0])<gate.gate_rank(card)<gate.gate_rank(hand['pillars'][1])
                    for card in hand['deck']))
                self.assertEqual(quote['post_cards'],sum(gate.gate_rank(card) in set(map(gate.gate_rank,hand['pillars'])) for card in hand['deck']))
                gross=100*quote['return_numerator']//quote['return_denominator']
                paid=100*(quote['total_cards']+(quote['loss_multiplier']-1)*quote['post_cards'])
                self.assertLessEqual(Fraction(gross*quote['winning_cards'],paid),Fraction(97,100))
                third=hand['deck'][-1]
                gate.act(room,1,'shoot',clock,{'stake':100,'direction':direction})
                self.assertEqual(hand['third'],third)
                drawn.append(third)
                shot=True
            else:
                gate.act(room,1,'skip',clock)
            self.assertEqual(points(room),original_points)
            self.assertEqual(hand['remaining_cards'],len(hand['deck']))
            if len(hand['deck'])<=gate.GATE_CUT_REMAINING:
                last_id=hand['shoe_id']
                room=json.loads(json.dumps(room))
                gate.start_hand(room,clock+1)
                self.assertNotEqual(room['hand']['shoe_id'],last_id)
                self.assertEqual(room['hand']['shoe_round'],1)
                self.assertTrue(room['hand']['shoe_reshuffled'])
                self.assertEqual(len(room['hand']['deck']),50)
                break
            remaining=list(hand['deck'])
            room=json.loads(json.dumps(room))  # persistence/restart between rounds
            gate.start_hand(room,clock+1)
            self.assertEqual(room['hand']['shoe_id'],first_id)
            self.assertFalse(room['hand']['shoe_reshuffled'])
            self.assertEqual(room['hand']['pillars'],sorted([remaining[-1],remaining[-2]],key=gate.gate_rank))
            self.assertEqual(room['hand']['deck'],remaining[:-2])
        else:
            self.fail('The cut card was never reached')
        self.assertTrue(shot)


if __name__=='__main__':unittest.main()
