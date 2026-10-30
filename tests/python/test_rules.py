"""Regression coverage for split pots, heads-up transitions and dry side pots."""
import json
import sqlite3
import unittest
import online
import poker_engine as p
import wallet
from .test_poker import room_with_players


def royal_runout_deck():
    holes = '2c 2d 3c 3d 4c 4d 5c 5d 6c 6d 7c 7d'.split()
    deal = holes + '8c As Ks Qs 8d Js 8h Ts'.split()
    return [c for c in p.DECK if c not in deal] + list(reversed(deal))


class RulesRegression(unittest.TestCase):
    def test_folded_money_does_not_create_extra_split_pots(self):
        room = room_with_players(6)
        p.start_hand(room, 1, royal_runout_deck())
        for uid, action, amount in [(4,'raise',25),(5,'raise',40),(6,'call',None),
                (1,'call',None),(2,'fold',None),(3,'fold',None),(4,'fold',None),
                (5,'check',None),(6,'raise',60),(1,'call',None),(5,'fold',None)]:
            p.act(room, uid, action, 2, amount)
        while room['status'] == 'playing':
            p.act(room, room['hand']['actor'], 'check', 3)
        self.assertEqual(room['hand']['board'], 'As Ks Qs Js Ts'.split())
        self.assertEqual({v['user_id']:v['payout'] for v in room['hand']['results'] if not v['folded']}, {1:140,6:140})
        self.assertEqual(room['hand']['pots'], [{'amount':280,'winners':[6,1],'refund':False}])
        self.assertEqual(sum(s['stack'] for s in room['seats']), 6000)

    def test_real_side_pots_with_same_winners_split_separately(self):
        room = room_with_players(5)
        p.start_hand(room, 1)
        hand = room['hand']
        hand['board'] = '2c 3d 4h 8s 9d'.split()
        hands = {1:['As','Ad'],2:['Ac','Ah'],3:['Ks','Kd'],4:['Qs','Qd'],5:['Js','Jd']}
        contributions = {1:11,2:11,3:3,4:5,5:6}
        for player in hand['players']:
            uid = player['user_id']
            player.update(stack=0, contribution=contributions[uid], starting_stack=contributions[uid],
                          street_bet=contributions[uid], hole=hands[uid], folded=uid in (4,5))
        p.finish(room, 2)
        # Main 15 and side 21 each have an odd chip, despite identical winners.
        self.assertEqual([(pot['amount'],pot['winners']) for pot in hand['pots']], [(15,[2,1]),(21,[2,1])])
        self.assertEqual({r['user_id']:r['payout'] for r in hand['results']}, {1:17,2:19,3:0,4:0,5:0})

    def test_heads_up_transition_from_each_departing_seat(self):
        for leaving, expected_big in ((1,2),(2,1),(3,1)):
            with self.subTest(leaving=leaving):
                room = room_with_players(3)
                p.start_hand(room, 1)
                p.act(room, 1, 'fold', 2); p.act(room, 2, 'fold', 3)
                p.leave(room, leaving, 4)
                p.start_hand(room, 7)
                hand = room['hand']
                self.assertEqual(hand['big_blind_id'], expected_big)
                self.assertNotEqual(hand['small_blind_id'], expected_big)
                self.assertEqual(hand['actor'], hand['small_blind_id'])
                p.act(room, hand['actor'], 'call', 8)
                p.act(room, hand['actor'], 'check', 9)
                self.assertEqual(hand['phase'], 'flop')
                self.assertEqual(hand['actor'], expected_big)

    def test_heads_up_transition_when_button_away_or_busted(self):
        for reason in ('away','busted'):
            with self.subTest(reason=reason):
                room = room_with_players(3)
                p.start_hand(room, 1)
                p.act(room, 1, 'fold', 2); p.act(room, 2, 'fold', 3)
                seat = p.seated(room, 1)
                if reason == 'away': seat['away'] = True
                else: seat['stack'] = 0
                p.start_hand(room, 7)
                self.assertEqual(room['hand']['big_blind_id'], 2)
                self.assertEqual(room['hand']['small_blind_id'], 3)

    def test_heads_up_seat_gaps_restart_and_subsequent_rotation(self):
        room = room_with_players(3)
        for seat, location in zip(room['seats'], (0,2,5)): seat['seat'] = location
        p.start_hand(room, 1)
        p.act(room, 1, 'fold', 2); p.act(room, 2, 'fold', 3)
        p.leave(room, 1, 4)
        room = json.loads(json.dumps(room))
        for clock, expected_big in ((7,2),(12,3),(17,2)):
            p.start_hand(room, clock)
            self.assertEqual(room['hand']['big_blind_id'], expected_big)
            self.assertEqual(room['hand']['players'][-1]['user_id'], room['hand']['small_blind_id'])
            p.act(room, room['hand']['actor'], 'fold', clock+1)

    def test_non_actor_leave_runs_out_without_unnecessary_action(self):
        room = room_with_players(3, [1000,15,1000])
        p.start_hand(room, 1)
        p.act(room, 1, 'raise', 2, 30); p.act(room, 2, 'call', 3); p.act(room, 3, 'call', 4)
        self.assertEqual(room['hand']['actor'], 3)
        p.leave(room, 1, 5)
        hand = room['hand']
        self.assertEqual((room['status'],hand['phase']), ('waiting','showdown'))
        self.assertIsNone(hand['actor']); self.assertIsNone(hand['deadline'])
        self.assertIsNone(p.legal_actions(room, 3))
        self.assertEqual((len(hand['board']),len(hand['burns'])), (5,3))
        self.assertFalse(hand['uncontested'])
        self.assertIsNone(p.seated(room, 1))
        self.assertEqual(sum(s['stack'] for s in room['seats']+room['departures']), 2015)
        self.assertEqual(len(p.public_view(room,3)['hand']['players'][0]['hole']), 2)

    def test_non_actor_leave_preserves_required_call_and_deadline(self):
        room = room_with_players(3, [1000,20,1000])
        p.start_hand(room, 1)
        p.act(room, 1, 'raise', 2, 30); p.act(room, 2, 'call', 3)
        hand = room['hand']; before = (hand['actor'],hand['deadline'],p.turn_id(hand))
        p.leave(room, 1, 4)
        self.assertEqual((hand['actor'],hand['deadline'],p.turn_id(hand)), before)
        self.assertEqual(room['status'], 'playing')
        legal = p.legal_actions(room, 3)
        self.assertEqual(legal['to_call'], 10)
        self.assertEqual(legal['actions'], ['fold','call'])
        p.act(room, 3, 'call', 5)
        self.assertEqual(hand['phase'], 'showdown')
        self.assertEqual(sum(s['stack'] for s in room['seats']+room['departures']), 2020)

    def test_unrelated_departure_does_not_reset_current_turn(self):
        room = room_with_players(4)
        p.start_hand(room, 1)
        hand = room['hand']; before = (hand['actor'],hand['deadline'],p.turn_id(hand))
        self.assertEqual(hand['actor'], 4)
        p.leave(room, 1, 10)
        self.assertEqual((hand['actor'],hand['deadline'],p.turn_id(hand)), before)
        self.assertIn('raise', p.legal_actions(room, 4)['actions'])

    def test_current_actor_leave_also_runs_out(self):
        room = room_with_players(3, [1000,15,1000])
        p.start_hand(room, 1)
        p.act(room, 1, 'raise', 2, 30); p.act(room, 2, 'call', 3); p.act(room, 3, 'call', 4)
        p.leave(room, 3, 5)
        self.assertEqual(room['hand']['phase'], 'showdown')
        self.assertIsNone(p.seated(room, 3))


class StoredRulesRegression(unittest.TestCase):
    def test_leave_settles_and_refunds_wallet_exactly_once(self):
        db = sqlite3.connect(':memory:'); self.addCleanup(db.close); db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,nickname TEXT)')
        db.executemany('INSERT INTO users VALUES(?,?)', [(i,f'P{i}') for i in range(1,4)])
        online.initialize(db)
        from . import scenario_budget
        scenario_budget(db)
        users = {i:{'id':i,'nickname':f'P{i}'} for i in range(1,4)}
        rid = online.mutate(db,'/api/online/rooms',{},users[1],100)['id']
        path = f'/api/online/rooms/{rid}'
        def call(command, uid, clock, **data):
            room = online.get_room(db,rid)
            payload = {'revision':room['revision'],**data}
            if command == 'action': payload['hand_id'] = room['hand']['id']
            return online.mutate(db,path+'/'+command,payload,users[uid],clock)
        call('join',2,101); call('join',3,102)
        room = online.get_room(db,rid)
        p.seated(room,2).update(stack=15,bought=15)
        wallet.transfer(db,2,985,'test_fixture','short_stack_fixture',103)
        online.save(db,room,103)
        call('start',1,104); call('action',1,105,action='raise',amount=30)
        call('action',2,106,action='call')
        call('action',3,107,action='call')
        operation = 'rules-leave-00000001'
        call('leave',1,108,operation_id=operation)
        room = online.get_room(db,rid)
        self.assertEqual(room['hand']['phase'],'showdown')
        self.assertEqual(db.execute('SELECT count(*) FROM poker_hands').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM poker_results').fetchone()[0],3)
        balance = wallet.view(db,1,108)['balance']
        replay = call('leave',1,109,operation_id=operation)
        self.assertTrue(replay['replayed'])
        self.assertEqual(wallet.view(db,1,109)['balance'],balance)
        self.assertEqual(db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='leave'").fetchone()[0],1)
        self.assertEqual(db.execute('SELECT count(*) FROM poker_sessions').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT sum(balance) FROM wallets').fetchone()[0]+sum(wallet.in_play(db).values()),9000)


if __name__ == '__main__': unittest.main()
