from copy import deepcopy
import json
import random
import unittest
import poker_engine as p
from .test_app import ServerTestCase


def room_with_players(count=6, stacks=None):
    room = p.new_room("Test table", 1)
    for index in range(count):
        p.sit(room, index+1, f"Player {index+1}", 0)
        if stacks:
            room["seats"][-1]["stack"] = stacks[index]
    return room


class HandRanking(unittest.TestCase):
    def test_all_nine_categories_and_wheel(self):
        samples = ["As Kd Jh 9c 5s", "As Ad Jh 9c 5s", "As Ad Jh Jc 5s",
                   "As Ad Ah 9c 5s", "As 2d 3h 4c 5s", "As Js 9s 6s 3s",
                   "As Ad Ah 9c 9s", "As Ad Ah Ac 9s", "9s Ts Js Qs Ks"]
        ranks = [p.rank_five(c.split()) for c in samples]
        self.assertEqual([r[0] for r in ranks], list(range(9)))
        self.assertEqual(sorted(ranks), ranks)
        self.assertEqual(ranks[4], (4,5))

    def test_kickers_full_house_and_board_tie(self):
        self.assertGreater(p.rank_five("As Ad Kh 9c 5s".split()), p.rank_five("As Ad Qh Jc 5s".split()))
        score, cards = p.best_hand("As Ad Ah Kc Ks Kd 2s".split())
        self.assertEqual(score, (6,14,13))
        self.assertEqual(len(cards), 5)
        board = "As Ks Qs Js Ts".split()
        self.assertEqual(p.best_hand(board+["2c","3c"])[0], p.best_hand(board+["Ac","Ad"])[0])

    def test_duplicates_and_invalid_cards_rejected(self):
        for cards in ["As As Qs Js Ts 2c 3c", "Xs Ks Qs Js Ts 2c 3c"]:
            with self.assertRaises(p.RuleError):
                p.best_hand(cards.split())


class EngineRules(unittest.TestCase):
    def test_heads_up_button_and_action_order(self):
        room = room_with_players(2)
        p.start_hand(room, 1)
        h = room["hand"]
        self.assertEqual(room["dealer_seat"], 0)
        self.assertEqual((h["small_blind_id"],h["big_blind_id"],h["actor"]), (1,2,1))
        p.act(room, 1, "call", 2)
        p.act(room, 2, "check", 3)
        self.assertEqual(h["phase"], "flop")
        self.assertEqual(h["actor"], 2)

    def test_big_blind_option_and_four_streets(self):
        room = room_with_players(3)
        p.start_hand(room, 1)
        self.assertEqual(room["hand"]["actor"], 1)
        for _ in range(50):
            if room["status"] != "playing":
                break
            uid = room["hand"]["actor"]
            legal = p.legal_actions(room, uid)
            p.act(room, uid, "check" if "check" in legal["actions"] else "call", 2)
        h = room["hand"]
        self.assertEqual(h["phase"], "showdown")
        self.assertEqual(len(h["board"]), 5)
        self.assertEqual(len(h["burns"]), 3)
        self.assertEqual(sum(x["stack"] for x in room["seats"]), 3000)

    def test_fold_win_and_uncalled_blind_return(self):
        room = room_with_players(2)
        p.start_hand(room, 1)
        p.act(room, 1, "fold", 2)
        self.assertEqual([s["stack"] for s in room["seats"]], [995,1005])
        self.assertEqual(room["hand"]["board"], [])
        self.assertTrue(room["hand"]["uncontested"])
        self.assertEqual(p.public_view(room, -1)["hand"]["players"][0]["hole"], [])

    def test_private_cards_and_full_deck(self):
        room = room_with_players()
        p.start_hand(room, 1)
        h = room["hand"]
        self.assertEqual(len(set(h["deck"]+sum([x["hole"] for x in h["players"]],[]))), 52)
        for uid in range(1,7):
            view = p.public_view(room, uid)
            self.assertNotIn("deck", view["hand"])
            self.assertNotIn("burns", view["hand"])
            self.assertNotIn("session_id", view["seats"][0])
            self.assertEqual(sum(len(x["hole"]) for x in view["hand"]["players"]), 2)

    def test_turn_restrictions_and_min_raise(self):
        room = room_with_players()
        p.start_hand(room, 1)
        with self.assertRaises(p.RuleError):
            p.act(room, 1, "call", 2)
        with self.assertRaises(p.RuleError):
            p.act(room, 4, "check", 2)
        with self.assertRaises(p.RuleError):
            p.act(room, 4, "raise", 2, 19)
        p.act(room, 4, "raise", 2, 30)
        self.assertEqual(p.legal_actions(room, 5)["min_raise_to"], 50)

    def test_short_all_in_does_not_reopen_but_cumulative_does(self):
        for cumulative in (False, True):
            room = room_with_players(6, [50 if cumulative else 1000,1000,1000,1000,1000,40])
            p.start_hand(room, 1)
            p.act(room, 4, "raise", 2, 30)
            p.act(room, 5, "call", 3)
            p.act(room, 6, "allin", 4)
            p.act(room, 1, "allin" if cumulative else "call", 5)
            p.act(room, 2, "call", 6)
            p.act(room, 3, "call", 7)
            legal = p.legal_actions(room, 4)
            self.assertEqual("raise" in legal["actions"], cumulative)
            self.assertEqual(legal["min_raise_to"], 70 if cumulative else 60)

    def test_side_pots_and_uncalled_return(self):
        room = room_with_players(3)
        p.start_hand(room, 1)
        h = room["hand"]
        h["board"] = "2c 3c 4h 8s 9d".split()
        for player in h["players"]:
            uid = player["user_id"]
            player.update(stack=0, contribution=uid*100, street_bet=uid*100, starting_stack=uid*100,
                          hole={1:["As","Ad"],2:["Ks","Kd"],3:["Qs","Qd"]}[uid])
        p.finish(room, 2)
        self.assertEqual({r["user_id"]:r["payout"] for r in h["results"]}, {1:300,2:200,3:100})
        self.assertEqual(sum(r["profit"] for r in h["results"]), 0)

    def test_odd_chip_goes_clockwise_left_of_button(self):
        room = room_with_players(3)
        p.start_hand(room, 1)
        h = room["hand"]
        h["board"] = "As Ks Qs Js Ts".split()
        for player in h["players"]:
            uid = player["user_id"]
            player.update(stack=0, contribution=1, street_bet=1, starting_stack=1,
                          folded=uid==3, hole={1:["2c","3c"],2:["4c","5c"],3:["6c","7c"]}[uid])
        p.finish(room, 2)
        self.assertEqual({r["user_id"]:r["payout"] for r in h["results"]}, {1:1,2:2,3:0})

    def test_all_in_runout_short_big_blind_and_no_empty_side_bets(self):
        room = room_with_players(2, [1000,5])
        p.start_hand(room, 1)
        self.assertEqual(room["status"], "waiting")
        self.assertEqual(len(room["hand"]["board"]), 5)
        self.assertEqual(sum(s["stack"] for s in room["seats"]), 1005)
        room = room_with_players(2, [1000,15])
        p.start_hand(room, 1)
        p.act(room, 1, "call", 2)
        p.act(room, 2, "allin", 3)
        self.assertNotIn("raise", p.legal_actions(room, 1)["actions"])
        p.act(room, 1, "call", 4)
        self.assertEqual(room["hand"]["phase"], "showdown")

    def test_timeout_away_leave_and_return(self):
        room = room_with_players(3)
        p.start_hand(room, 1)
        actor = room["hand"]["actor"]
        self.assertFalse(p.tick(room, 30))
        self.assertTrue(p.tick(room, 31))
        self.assertTrue(p.seated(room, actor)["away"])
        p.return_to_play(room, actor, 32)
        self.assertFalse(p.seated(room, actor)["away"])
        p.leave(room, actor, 33)
        while room["status"] == "playing":
            p.act(room, room["hand"]["actor"], "fold", 34)
        self.assertIsNone(p.seated(room, actor))
        self.assertEqual(len(room["departures"]), 1)

    def test_all_in_player_leaving_retains_showdown_eligibility(self):
        room = room_with_players(3)
        p.start_hand(room, 1)
        p.act(room, 1, "allin", 2)
        p.leave(room, 1, 3)
        player = next(x for x in room["hand"]["players"] if x["user_id"] == 1)
        self.assertFalse(player["folded"])
        self.assertTrue(p.seated(room,1)["leaving"])
        p.act(room, 2, "fold", 4)
        p.act(room, 3, "fold", 5)
        self.assertIsNone(p.seated(room,1))
        self.assertGreater(room["departures"][0]["stack"], 1000)

    def test_random_hands_conserve_chips_and_recover_json(self):
        rng = random.Random(7284)
        room = room_with_players()
        clock = 1
        for _ in range(180):
            for seat in room["seats"]:
                if seat["stack"] < 10:
                    p.rebuy(room, seat["user_id"], clock)
            total = sum(s["stack"] for s in room["seats"])
            clock += 4
            p.start_hand(room, clock)
            for _ in range(200):
                room = json.loads(json.dumps(room))
                h = room["hand"]
                if room["status"] != "playing":
                    break
                self.assertEqual(sum(s["stack"]+s["contribution"] for s in h["players"]), total)
                uid = h["actor"]
                legal = p.legal_actions(room, uid)
                choices = [a for a in legal["actions"] if a != "raise" or legal["can_full_raise"]]
                action = rng.choice(choices)
                clock += 1
                p.act(room, uid, action, clock, legal["min_raise_to"] if action == "raise" else None)
            else:
                self.fail("Hand did not finish")
            self.assertEqual(sum(s["stack"] for s in room["seats"]), total)
            self.assertEqual(sum(r["profit"] for r in room["hand"]["results"]), 0)


class LiveAPI(ServerTestCase):
    def test_multi_client_persistence_visibility_and_conflicts(self):
        first = self.clients[0]
        self.assertEqual(first.call('/api/online/lobby')[0],401)
        first.call('/api/register',{"username":"first","nickname":"First","password":"password123"})
        code = first.call('/api/state')[1]['invite_code']
        for i in range(1,6):
            self.assertEqual(self.clients[i].call('/api/register',{"username":f"user{i}","nickname":f"Player {i}","password":"password123","invite_code":code})[0],200)
        status, created = first.call('/api/online/rooms',{"name":"API table"})
        self.assertEqual(status,200)
        rid = created['id']
        path = f'/api/online/rooms/{rid}'
        for i in range(1,6):
            room = self.clients[i].call(path)[1]
            self.assertEqual(self.clients[i].call(path+'/join',{"revision":room['revision']})[0],200)
        self.assertEqual(first.call('/api/online/rooms',{"name":"Second"})[0],400)
        room = first.call(path)[1]
        self.assertEqual(first.call(path+'/start',{"revision":room['revision']})[0],200)
        views = [c.call(path)[1] for c in self.clients[:6]]
        for view in views:
            self.assertNotIn('deck',view['hand'])
            self.assertEqual(sum(len(p['hole']) for p in view['hand']['players']),2)
        # A real process restart must preserve the shuffled deck, private cards,
        # turn and login cookies, without dealing the hand again.
        import os, subprocess, time
        before = views[0]
        args = self.proc.args
        self.proc.terminate()
        self.proc.wait(timeout=10)
        env = dict(os.environ, POKER_DB=str(self.db_path), PYTHONIOENCODING='utf-8',
                   POKER_SECURE_COOKIE='0', POKER_REQUIRE_INVITE='0', POKER_PUBLIC_ORIGIN='')
        type(self).proc = subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                status, resumed = first.call(path)
                break
            except OSError:
                time.sleep(.05)
        else:
            self.fail('Restarted server failed to start')
        self.assertEqual(status,200)
        self.assertEqual(resumed['hand'], before['hand'])
        self.assertEqual(resumed['revision'], before['revision'])
        room = views[0]
        actor = room['hand']['actor']
        wrong = self.clients[0 if actor != 1 else 1]
        self.assertEqual(wrong.call(path+'/action',{"revision":room['revision'],"hand_id":room['hand']['id'],"action":"call"})[0],400)
        self.assertEqual(self.clients[actor-1].call(path+'/action',{"revision":room['revision']-1,"hand_id":room['hand']['id'],"action":"call"})[0],409)
        for _ in range(100):
            room = first.call(path)[1]
            if room['status'] != 'playing':
                break
            actor = room['hand']['actor']
            client = self.clients[actor-1]
            own = client.call(path)[1]
            action = 'check' if 'check' in own['legal']['actions'] else 'call'
            self.assertEqual(client.call(path+'/action',{"revision":own['revision'],"hand_id":own['hand']['id'],"action":action})[0],200)
        else:
            self.fail('API hand never finished')
        self.assertEqual(len(room['history']),1)
        self.assertEqual(sum(r['profit'] for r in room['history'][0]['results']),0)
        self.assertEqual(first.call('/api/online/lobby')[1]['total_hands'],1)
        for _ in range(3):
            first.call(path)
        self.assertEqual(first.call('/api/online/lobby')[1]['total_hands'],1)
        # Full state is persisted and recoverable without a process-local game singleton.
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(self.db_path)) as db:
            stored = json.loads(db.execute('SELECT state FROM poker_rooms WHERE id=?',(rid,)).fetchone()[0])
            self.assertEqual(stored['hand']['phase'],'showdown')
            self.assertEqual(db.execute('SELECT count(*) FROM poker_results').fetchone()[0],6)
        self.assertEqual(self.clients[1].call(path+'/close',{"revision":room['revision']})[0],400)
        self.assertEqual(first.call(path+'/close',{"revision":room['revision']})[0],200)
        self.assertEqual(first.call('/api/online/lobby')[1]['current_room_id'],None)
        self.assertEqual(first.call('/api/state')[1]['games'],[])


if __name__ == '__main__':
    unittest.main(verbosity=2)
