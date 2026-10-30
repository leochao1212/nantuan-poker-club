"""Money conservation, exhaustive prize odds, deadlines and restart-safe settlement."""
import itertools
import json
import sqlite3
import unittest
from collections import Counter
from datetime import datetime
from unittest.mock import patch
import lottery
import online
import wallet
from poker_engine import RuleError


class LotteryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON');self.addCleanup(self.db.close)
        self.db.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);
        CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
        INSERT INTO settings VALUES('invite_code','TESTONLY');
        INSERT INTO users VALUES(1,'alice','Alice','2026');
        INSERT INTO users VALUES(2,'bob','Bob','2026');""")
        online.initialize(self.db)
        self.clock=datetime(2026,11,1,12,tzinfo=wallet.TAIPEI).timestamp()
        self.db.execute('DELETE FROM lottery_draws')
        lottery.maintenance(self.db,self.clock)
        self.day,self.at=lottery.upcoming(self.clock)
        self.n=0

    def buy(self,chosen=None,uid=1,clock=None,**extra):
        self.n+=1
        data=dict(numbers=chosen or [1,2,3,4,5],draw_id=self.day,operation_id=f'lottery_test_{self.n:016d}')|extra
        return lottery.buy(self.db,uid,data,self.clock if clock is None else clock)

    def balance(self,uid=1):
        return self.db.execute('SELECT balance FROM wallets WHERE user_id=?',(uid,)).fetchone()[0]

    def test_exhaustive_odds_and_unique_numbers(self):
        counts=Counter()
        for chosen in itertools.combinations(range(1,21),5):
            t=lottery.tier(chosen,[1,2,3,4,5,6])
            if t:counts[t[2]]+=1
        self.assertEqual(counts,{t[2]:t[4] for t in lottery.TIERS})
        for seed in range(100):
            r=lottery.numbers(f'{seed:064x}')
            self.assertEqual(len(set(r)),6);self.assertTrue(all(1<=n<=20 for n in r))

    def test_replay_and_conflicting_receipt(self):
        before=self.balance();op='same_operation_123456'
        a=self.buy(operation_id=op)
        b=self.buy(operation_id=op,clock=self.at+60)
        self.assertEqual(a['ticket_id'],b['ticket_id']);self.assertTrue(b['replayed'])
        self.assertEqual(self.balance(),before-100)
        with self.assertRaises(RuleError):self.buy([2,3,4,5,6],operation_id=op)

    def test_cutoff_limit_and_validation(self):
        self.buy(clock=self.at-301)
        with self.assertRaises(RuleError):self.buy(clock=self.at-300)
        for _ in range(9):self.buy()
        with self.assertRaises(RuleError):self.buy()
        for chosen in ([1,1,2,3,4],[True,2,3,4,5],[0,2,3,4,5],[1,2,3,4,21]):
            with self.assertRaises(RuleError):self.buy(chosen,uid=2)

    def test_shared_jackpot_restart_and_seed_privacy(self):
        public=lottery.view(self.db,1,self.clock)['current'];self.assertNotIn('seed',public)
        draw=self.db.execute('SELECT * FROM lottery_draws').fetchone()
        chosen=lottery.numbers(draw['seed'])[:5]
        self.buy(chosen);self.buy(chosen,uid=2)
        before=[self.balance(1),self.balance(2)]
        lottery.maintenance(self.db,self.at)
        self.assertEqual([self.balance(1),self.balance(2)],[x+5020 for x in before])
        lottery.maintenance(self.db,self.at+86400*3)
        self.assertEqual([self.balance(1),self.balance(2)],[x+5020 for x in before])
        self.assertEqual(self.db.execute('SELECT amount FROM lottery_pool').fetchone()[0],10000)
        revealed=lottery.view(self.db,1,self.at)['results'][-1]
        self.assertEqual(lottery.numbers(revealed['seed']),revealed['result'])

    def test_purchase_and_settlement_rollback(self):
        self.db.execute("CREATE TRIGGER fail_ticket BEFORE INSERT ON lottery_tickets BEGIN SELECT RAISE(ABORT,'test'); END")
        before=self.balance()
        with self.assertRaises(sqlite3.IntegrityError):self.buy()
        self.assertEqual(self.balance(),before)
        self.db.execute('DROP TRIGGER fail_ticket')
        draw=self.db.execute('SELECT * FROM lottery_draws').fetchone()
        self.buy(lottery.numbers(draw['seed'])[:5]);before=self.balance()
        original=wallet.transfer
        def fail(*a,**kw):original(*a,**kw);raise RuntimeError('lost process')
        with patch('wallet.transfer',side_effect=fail),self.assertRaises(RuntimeError):lottery.maintenance(self.db,self.at)
        self.assertEqual(self.balance(),before)
        self.assertIsNone(self.db.execute('SELECT prize FROM lottery_tickets').fetchone()[0])
        lottery.maintenance(self.db,self.at)
        self.assertEqual(self.balance(),before+10020)

    def test_empty_and_no_winner_rollover(self):
        self.buy([16,17,18,19,20])
        with patch('lottery.numbers',return_value=[1,2,3,4,5,6]):lottery.maintenance(self.db,self.at)
        lottery.maintenance(self.db,self.at+86400)
        self.assertEqual(self.db.execute('SELECT amount FROM lottery_pool').fetchone()[0],10020)
        self.assertEqual(self.db.execute('SELECT count(*) FROM lottery_tickets').fetchone()[0],1)

    def test_insufficient_balance_and_stale_draw_do_not_buy(self):
        self.db.execute('UPDATE wallets SET balance=99 WHERE user_id=1')
        with self.assertRaises(RuleError):self.buy()
        self.assertEqual(self.balance(),99)
        self.assertEqual(self.db.execute('SELECT amount FROM lottery_pool').fetchone()[0],10000)
        with self.assertRaises(RuleError):self.buy(uid=2,clock=self.at+1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM lottery_tickets').fetchone()[0],0)

    def test_private_tickets_and_fixed_prize_ledger(self):
        self.buy([1,2,3,4,6])
        self.assertEqual(lottery.view(self.db,2,self.clock)['tickets'],[])
        before=self.balance()
        with patch('lottery.numbers',return_value=[1,2,3,4,5,6]):lottery.maintenance(self.db,self.at)
        self.assertEqual(self.balance(),before+10000)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='lottery_prize'").fetchone()[0],1)
        self.assertEqual(lottery.view(self.db,1,self.at)['tickets'][0]['tier'],'二獎')

    def test_clock_rollback_does_not_create_historical_draw(self):
        self.assertFalse(lottery.maintenance(self.db,self.clock-86400))
        self.assertEqual(self.db.execute('SELECT count(*) FROM lottery_draws').fetchone()[0],1)
