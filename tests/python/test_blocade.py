import copy
import json
import sqlite3
import time
import unittest
import uuid
from unittest.mock import patch

import blocade as game
import blocade_engine as engine
import online
import wallet
from poker_engine import RuleError
from tests.python.test_app import ServerTestCase


def players(count):
    return [dict(uid=i+1, name=f'Player {i+1}', bot=False) for i in range(count)]


class BoardRules(unittest.TestCase):
    def test_two_and_four_setup_and_goals(self):
        for count in (2, 4):
            s=engine.new(players(count))
            self.assertEqual(len({tuple(p['pos']) for p in s['players']}),count)
            self.assertEqual([p['walls'] for p in s['players']],[10 if count==2 else 5]*count)
            for i,p in enumerate(s['players']):
                p['pos']=[1,3] if p['side']==0 else [3,7] if p['side']==1 else [7,3] if p['side']==2 else [3,1]
                s['turn']=i;s['winner']=None
                target=[0,3] if p['side']==0 else [3,8] if p['side']==1 else [8,3] if p['side']==2 else [3,0]
                engine.act(s,dict(kind='move',pos=target));self.assertEqual(s['winner'],i)

    def test_adjacent_jumps_and_wall_blocked_side_jumps(self):
        s=engine.new(players(2));s['players'][0]['pos']=[4,4];s['players'][1]['pos']=[3,4]
        self.assertIn([2,4],engine.moves(s));self.assertNotIn([3,3],engine.moves(s))
        s['walls']=[['h',2,4]]
        self.assertNotIn([2,4],engine.moves(s));self.assertIn([3,3],engine.moves(s));self.assertIn([3,5],engine.moves(s))
        s['walls'].append(['v',3,3]);self.assertNotIn([3,3],engine.moves(s))

    def test_four_player_cannot_land_on_or_jump_through_another_pawn(self):
        s=engine.new(players(4))
        for p,pos in zip(s['players'],([4,4],[3,4],[2,4],[3,5])):p['pos']=pos
        self.assertNotIn([2,4],engine.moves(s));self.assertNotIn([3,5],engine.moves(s));self.assertIn([3,3],engine.moves(s))

    def test_walls_overlap_cross_and_path_preservation(self):
        s=engine.new(players(2));s['walls']=[['h',3,3]]
        for w in (['h',3,3],['h',3,2],['h',3,4],['v',3,3]):self.assertFalse(engine.wall_valid(s,w))
        self.assertTrue(engine.wall_valid(s,['h',3,5]))
        s['players'][0]['pos']=[8,0];s['walls']=[['v',7,0]]
        self.assertFalse(engine.wall_valid(s,['h',7,0]))
        s=engine.new(players(4));s['walls']=[['v',3,0],['h',4,0]]
        self.assertFalse(engine.wall_valid(s,['h',2,0]),'Must preserve a route for all four players')

    def test_bad_actions_do_not_mutate(self):
        s=engine.new(players(2));before=copy.deepcopy(s)
        for action in ({'kind':'move','pos':[0,0]},{'kind':'move','pos':[True,4]},
                       {'kind':'wall','wall':['h',8,0]},{'kind':'wall','wall':['x',1,1]},
                       {'kind':'wall','wall':['h',False,0]},{'kind':'award','winner':0}):
            with self.assertRaises(RuleError):engine.act(s,action)
            self.assertEqual(s,before)

    def test_temporarily_occupied_corridor_can_pass_without_cheating(self):
        s=engine.new(players(4))
        for p,pos in zip(s['players'],([8,0],[7,0],[6,0],[7,1])):p['pos']=pos
        s['walls']=[['v',7,0]]
        self.assertEqual(engine.moves(s),[])
        action=engine.choose(s);self.assertEqual(action,{'kind':'wait'})
        engine.act(s,action);self.assertEqual(s['turn'],1)
        with self.assertRaises(RuleError):engine.act(engine.new(players(2)),{'kind':'wait'})

    def test_bot_wins_in_one_move_and_only_plays_legal_actions(self):
        s=engine.new(players(2));s['players'][0]['pos']=[1,3]
        engine.act(s,engine.choose(s));self.assertEqual(s['winner'],0)
        for count in (2,4):
            s=engine.new(players(count))
            for _ in range(120):
                if s['winner'] is not None:break
                engine.act(s,engine.choose(s))
                edges=engine.blocked(s['walls'])
                self.assertTrue(all(engine.distance(p,edges)<999 for p in s['players']))
            self.assertIsNotNone(s['winner'],'Bots must eventually finish an ordinary match')


class Escrow(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);
            CREATE TABLE audit(id INTEGER PRIMARY KEY,user_id INTEGER,action TEXT,detail TEXT,created_at TEXT);
            INSERT INTO users VALUES(1,'p1','Player 1','2026-11-03'),(2,'p2','Player 2','2026-11-03'),
            (3,'p3','Player 3','2026-11-03'),(4,'p4','Player 4','2026-11-03');''')
        online.initialize(self.db);self.clock=time.time();self.users=[self.db.execute('SELECT * FROM users WHERE id=?',(i,)).fetchone() for i in range(1,5)]
        self.db.commit()

    def tearDown(self):self.db.close()

    def call(self,uid,verb,**data):
        data.setdefault('operation_id',uuid.uuid4().hex)
        with self.db:return game.mutate(self.db,self.users[uid-1],verb,data,self.clock)

    def create(self,capacity=2,stake=100,bots=True):return self.call(1,'create',capacity=capacity,stake=stake,bots=bots)['room_id']
    def balance(self,uid):return self.db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()[0]

    def test_create_retry_refund_and_wallet_total(self):
        before=self.balance(1);op=uuid.uuid4().hex
        result=self.call(1,'create',capacity=2,stake=100,bots=True,operation_id=op);rid=result['room_id']
        self.assertTrue(self.call(1,'create',capacity=2,stake=100,bots=True,operation_id=op)['replayed'])
        self.assertEqual(self.balance(1),before-100);self.assertEqual(wallet.in_play(self.db)[1],100)
        with self.assertRaises(RuleError):self.call(1,'create',capacity=2,stake=200,bots=True,operation_id=op)
        self.call(1,'leave',room_id=rid);self.assertEqual(self.balance(1),before)
        self.assertIsNone(game.current(self.db,1));self.assertEqual(game.get(self.db,rid)['status'],'cancelled')

    def test_insufficient_balance_rolls_back_room_and_ledger(self):
        self.db.execute('UPDATE wallets SET balance=50 WHERE user_id=1');self.db.commit()
        with self.assertRaises(RuleError):self.create(stake=100)
        self.assertEqual(self.db.execute('SELECT count(*) FROM blocade_rooms').fetchone()[0],0)
        self.assertEqual(self.balance(1),50)

    def test_four_equal_buyins_and_exact_once_winner_payout(self):
        initial=sum(self.balance(i) for i in range(1,5));rid=self.create(4,bots=False)
        for uid in (2,3,4):self.call(uid,'join',room_id=rid)
        self.assertEqual(sum(wallet.in_play(self.db).values()),400)
        self.call(1,'start',room_id=rid);r=game.get(self.db,rid)
        r['game']['turn']=0;r['game']['players'][0]['pos']=[1,3];game.save(self.db,r,self.clock);self.db.commit()
        data=dict(room_id=rid,ply=r['game']['ply'],action={'kind':'move','pos':[0,3]},operation_id=uuid.uuid4().hex)
        self.call(1,'act',**data);self.call(1,'act',**data)
        game.maintenance(self.db,self.clock+100);self.assertEqual(self.balance(1),10300)
        self.assertEqual(sum(self.balance(i) for i in range(1,5)),initial)
        self.assertEqual(game.get(self.db,rid)['pot'],400)
        self.assertEqual(wallet.in_play(self.db),{})
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='blocade_prize' AND amount>0").fetchone()[0],1)

    def test_bot_contribution_payout_and_no_rigging(self):
        rid=self.create(4);self.call(1,'start',room_id=rid);r=game.get(self.db,rid)
        self.assertEqual(sum(p['bot'] for p in r['players']),3)
        r['game']['turn']=0;r['game']['players'][0]['pos']=[1,3];game.save(self.db,r,self.clock)
        self.call(1,'act',room_id=rid,ply=r['game']['ply'],action={'kind':'move','pos':[0,3]})
        r=game.get(self.db,rid);self.assertEqual(r['system_stake'],300);self.assertEqual(self.balance(1),10300)
        second=self.create();self.call(1,'start',room_id=second);self.call(1,'leave',room_id=second)
        self.assertEqual(self.balance(1),10200);self.assertEqual(game.get(self.db,second)['system_payout'],200)

    def test_permissions_turn_conflicts_and_leave_rules(self):
        rid=self.create(bots=False)
        with self.assertRaises(RuleError):self.call(2,'start',room_id=rid)
        with self.assertRaises(RuleError):self.call(1,'start',room_id=rid)
        self.call(2,'join',room_id=rid)
        with self.assertRaises(RuleError):self.call(3,'join',room_id=rid)
        self.call(1,'start',room_id=rid);r=game.get(self.db,rid);uid=r['game']['players'][r['game']['turn']]['uid']
        with self.assertRaises(RuleError):self.call(3-uid,'act',room_id=rid,ply=0,action={'kind':'move','pos':[7,3]})
        with self.assertRaises(RuleError):self.call(uid,'act',room_id=rid,ply=99,action=engine.choose(r['game']))
        self.call(1,'leave',room_id=rid);self.assertEqual(self.balance(1),9900);self.assertEqual(self.balance(2),10100)

    def test_waiting_host_transfer_expiry_and_match_draw_refund(self):
        rid=self.create(4);self.call(2,'join',room_id=rid);self.call(1,'leave',room_id=rid)
        self.assertEqual(game.get(self.db,rid)['owner'],2)
        game.maintenance(self.db,self.clock+901);self.assertEqual(self.balance(2),10000)
        rid=self.create();self.call(1,'start',room_id=rid)
        game.maintenance(self.db,self.clock+1801);game.maintenance(self.db,self.clock+1900)
        self.assertEqual(self.balance(1),10000);self.assertEqual(game.get(self.db,rid)['status'],'cancelled')

    def test_restart_preserves_pending_board_then_timeouts_forfeit(self):
        rid=self.create();self.call(1,'start',room_id=rid);r=game.get(self.db,rid)
        for attempt in range(3):
            with patch('blocade.time.time',return_value=self.clock):game.initialize(self.db)
            self.assertEqual(game.get(self.db,rid)['game']['players'][0]['misses'],attempt)
            r=game.get(self.db,rid);r['game']['turn']=0;r['deadline']=self.clock-1;game.save(self.db,r,self.clock);self.db.commit()
            game.maintenance(self.db,self.clock)
        self.assertEqual(game.get(self.db,rid)['status'],'finished');self.assertEqual(self.balance(1),9900)

    def test_deployment_pause_blocks_new_money_but_allows_refunds(self):
        rid=self.create();self.db.execute("INSERT INTO settings VALUES('deploy_pause_until',?)",(str(self.clock+100),));self.db.commit()
        with self.assertRaises(RuleError):self.call(2,'join',room_id=rid)
        with self.assertRaises(RuleError):self.call(1,'start',room_id=rid)
        self.call(1,'leave',room_id=rid);self.assertEqual(self.balance(1),10000)

    def test_bounded_bot_work_and_free_games(self):
        for uid in range(1,5):
            rid=self.call(uid,'create',capacity=2,stake=0,bots=True)['room_id'];self.call(uid,'start',room_id=rid)
            r=game.get(self.db,rid);r['game']['turn']=1;r['bot_at']=self.clock-1;game.save(self.db,r,self.clock)
        with patch('blocade_engine.choose',wraps=engine.choose) as choose:
            self.assertFalse(game.maintenance(self.db,self.clock),'Bot moves must not broadcast unrelated lobby snapshots');self.assertEqual(choose.call_count,2)
        self.assertTrue(all(self.balance(uid)==10000 for uid in range(1,5)))

    def test_deploy_freezes_turns_and_resume_restores_remaining_time(self):
        rid=self.create();self.call(1,'start',room_id=rid)
        room=game.get(self.db,rid);room['game']['turn']=0;game.save(self.db,room,self.clock)
        self.db.execute("INSERT INTO settings VALUES('deploy_pause_until',?)",(str(self.clock+600),));self.db.commit()
        game.maintenance(self.db,self.clock+5);self.db.commit()
        paused=game.get(self.db,rid);self.assertEqual(paused['paused_at'],self.clock+5)
        self.assertTrue(game.view(self.db,1,self.clock+6)['room']['paused'])
        with self.assertRaises(RuleError):self.call(1,'act',room_id=rid,ply=0,action={'kind':'move','pos':[7,4]})
        game.maintenance(self.db,self.clock+120);self.assertEqual(game.get(self.db,rid)['game']['ply'],0)
        self.db.execute("DELETE FROM settings WHERE key='deploy_pause_until'");self.db.commit()
        game.maintenance(self.db,self.clock+125)
        resumed=game.get(self.db,rid)
        self.assertEqual(resumed['deadline'],room['deadline']+120)
        self.assertEqual(resumed['started_at'],room['started_at']+120)
        self.assertEqual(resumed['game']['players'][0]['misses'],0)

    def test_board_upgrade_audit_allows_settlement_but_not_missing_stakes(self):
        from ops.audit_deployment import blocade_audit
        rid=self.create();self.db.execute("ATTACH DATABASE ':memory:' AS saved")
        for table in ('blocade_rooms','blocade_entries','blocade_operations'):
            self.db.execute(f'CREATE TABLE saved.{table} AS SELECT * FROM main.{table}')
        self.db.commit()
        self.call(1,'leave',room_id=rid)
        self.assertFalse(any(v for check in blocade_audit(self.db).values() for v in check.values()))
        self.db.execute('UPDATE blocade_entries SET stake=999 WHERE room_id=?',(rid,))
        self.assertEqual(blocade_audit(self.db)['entries']['changed'],1)


class BoardHTTP(ServerTestCase):
    def test_auth_static_create_join_retry_and_refund(self):
        a,b=self.clients[:2]
        self.assertEqual(a.call('/api/blocade')[0],401)
        for route in ('/blocade.js','/night.css'):self.assertEqual(a.call(route)[0],200)
        self.assertEqual(a.call('/api/register',dict(username='board1',nickname='Board 1',password='SyntheticPass123'))[0],200)
        invite=a.call('/api/state')[1]['invite_code']
        self.assertEqual(b.call('/api/register',dict(username='board2',nickname='Board 2',password='SyntheticPass123',invite_code=invite))[0],200)
        data=dict(capacity=2,stake=100,bots=False,operation_id=uuid.uuid4().hex)
        status,result=a.call('/api/blocade/create',data);self.assertEqual(status,200,result)
        rid=result['room_id'];self.assertEqual(result['wallet']['balance'],9900);self.assertEqual(result['wallet']['in_play'],100)
        self.assertTrue(a.call('/api/blocade/create',data)[1]['replayed'])
        self.assertEqual(b.call('/api/blocade/join',dict(room_id=rid,operation_id=uuid.uuid4().hex))[0],200)
        self.assertEqual(b.call('/api/blocade/start',dict(room_id=rid,operation_id=uuid.uuid4().hex))[0],400)
        self.assertEqual(a.call('/api/blocade/start',dict(room_id=rid,operation_id=uuid.uuid4().hex))[0],200)
        status,result=b.call('/api/blocade/leave',dict(room_id=rid,operation_id=uuid.uuid4().hex));self.assertEqual(status,200,result)
        self.assertEqual(a.call('/api/blocade?room='+str(rid))[1]['wallet']['balance'],10100)
        self.assertEqual(b.call('/api/blocade')[1]['wallet']['balance'],9900)
