"""Hourly rolling cooldown, exactly-once claims, and daily independence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime,timezone
import sqlite3
import unittest
import wallet
from . import test_club as fixtures
from .test_app import ServerTestCase

class HourlyRules(unittest.TestCase):
    setUp=fixtures.WalletRules.setUp
    def test_hourly_cooldown_boundary_and_accounts(self):
        t=self.clock
        self.assertTrue(wallet.view(self.db,1,t)['hourly_available'])
        self.assertTrue(wallet.claim_hourly(self.db,1,t,'hourly_first_000001')['claimed'])
        self.assertEqual(wallet.view(self.db,1,t)['balance'],3200)
        self.assertEqual(wallet.view(self.db,1,t)['hourly_next_at'],t+3600)
        self.assertFalse(wallet.view(self.db,1,t+3599.999)['hourly_available'])
        self.assertFalse(wallet.claim_hourly(self.db,1,t+3599.999,'hourly_next_0000001')['claimed'])
        self.assertTrue(wallet.claim_hourly(self.db,1,t+3600,'hourly_next_0000001')['claimed'])
        self.assertTrue(wallet.claim_hourly(self.db,2,t,'hourly_first_000001')['claimed'])
        self.assertEqual(wallet.view(self.db,1,t+3600)['balance'],3400)
        self.assertEqual(wallet.view(self.db,2,t)['balance'],3200)
    def test_daily_hourly_midnight_and_no_accumulation(self):
        t=datetime(2026,10,19,15,59,59,tzinfo=timezone.utc).timestamp()
        self.assertTrue(wallet.claim(self.db,1,t)['claimed'])
        self.assertTrue(wallet.claim_hourly(self.db,1,t,'hourly_midnight_0001')['claimed'])
        self.assertTrue(wallet.claim(self.db,1,t+1)['claimed'])
        self.assertFalse(wallet.claim_hourly(self.db,1,t+1,'hourly_midnight_0002')['claimed'])
        self.assertTrue(wallet.claim_hourly(self.db,1,t+86400*3,'hourly_after_gap_0001')['claimed'])
        self.assertEqual(wallet.view(self.db,1,t+86400*3)['balance'],5400)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='hourly'").fetchone()[0],2)
        self.assertFalse(wallet.view(self.db,1,t+86400*3)['daily_claimed'])
    def test_replay_after_hour_and_restart_does_not_claim_again(self):
        op='hourly_restart_0001';t=self.clock
        wallet.claim_hourly(self.db,1,t,op)
        wallet.initialize(self.db,t+7200)
        self.assertTrue(wallet.view(self.db,1,t+7200)['hourly_available'])
        self.assertTrue(wallet.claim_hourly(self.db,1,t+7200,op)['replayed'])
        self.assertEqual(wallet.view(self.db,1,t+7200)['balance'],3200)
        self.assertTrue(wallet.claim_hourly(self.db,1,t+7200,'hourly_new_request_01')['claimed'])
    def test_validation_and_pending_migration(self):
        for op in ['',True,123,'<script>','x'*81]:
            with self.assertRaises(Exception):wallet.claim_hourly(self.db,1,self.clock,op)
        self.assertEqual(wallet.view(self.db,1,self.clock)['balance'],3000)
        self.db.execute("UPDATE wallet_meta SET value='pending' WHERE key='state'")
        self.assertFalse(wallet.view(self.db,1,self.clock)['hourly_available'])
        with self.assertRaises(Exception):wallet.claim_hourly(self.db,1,self.clock,'hourly_pending_0001')

class HourlyAPI(ServerTestCase):
    def test_claims_concurrent_persistent_and_not_game_profit(self):
        c=self.clients[0];payload={'operation_id':'hourly_http_claim_001'}
        self.assertEqual(c.call('/api/wallet/hourly',payload)[0],401)
        self.assertEqual(c.call('/api/register',{'username':'hourlyuser','nickname':'補給測試','password':'password123'})[0],200)
        self.assertEqual(c.call('/api/wallet/hourly',{})[0],400)
        self.assertEqual(c.call('/api/wallet/claim',{})[1]['wallet']['balance'],4000)
        with ThreadPoolExecutor(8) as pool:
            results=list(pool.map(lambda i:c.call('/api/wallet/hourly',{'operation_id':f'hourly_parallel_{i:04d}'}),range(8)))
        self.assertTrue(all(s==200 for s,r in results));self.assertEqual(sum(r['claimed'] for s,r in results),1)
        v=c.call('/api/online/lobby')[1]
        self.assertEqual(v['wallet']['balance'],4200);self.assertFalse(v['wallet']['hourly_available'])
        self.assertEqual(v['users'][0]['profit'],0)
        winner=next(f'hourly_parallel_{i:04d}' for i,(s,r) in enumerate(results) if r['claimed'])
        self.assertTrue(c.call('/api/wallet/hourly',{'operation_id':winner})[1]['replayed'])
        with closing(sqlite3.connect(self.db_path)) as d:
            self.assertEqual(d.execute("SELECT count(*) FROM wallet_ledger WHERE kind='hourly'").fetchone()[0],1)
            d.execute("UPDATE wallet_ledger SET created_at=created_at-3601 WHERE kind='hourly'");d.commit()
        self.assertTrue(c.call('/api/online/lobby')[1]['wallet']['hourly_available'])
        self.assertTrue(c.call('/api/wallet/hourly',{'operation_id':winner})[1]['replayed'])
        self.assertTrue(c.call('/api/wallet/hourly',payload)[1]['claimed'])
        self.assertEqual(c.call('/api/online/lobby')[1]['wallet']['balance'],4400)

if __name__=='__main__':unittest.main()
