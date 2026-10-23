"""Point conservation, private receipts, atomic failures and real concurrent requests."""
import sqlite3
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import online,transfers,wallet
import test_app as fixtures
from test_realtime import Stream


class TransferRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA foreign_keys=ON');self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);
          CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TESTONLY');
          INSERT INTO users VALUES(1,'alice','Alice','2026');INSERT INTO users VALUES(2,'bob','Bob','2026');INSERT INTO users VALUES(3,'carol','Carol','2026');''')
        online.initialize(self.db);transfers.initialize(self.db);self.sender={'id':1}
        self.payload=dict(recipient_id=2,recipient_username='bob',amount=1000,note='測試轉移',operation_id='transfer_test_000001')

    def test_conservation_receipt_restart_and_privacy(self):
        initial=self.db.execute('SELECT sum(balance) FROM wallets').fetchone()[0]
        result=transfers.send(self.db,self.sender,self.payload,100)
        self.assertEqual(result['wallet']['balance'],2000);self.assertEqual(wallet.view(self.db,2,100)['balance'],4000)
        self.assertEqual(self.db.execute('SELECT sum(balance) FROM wallets').fetchone()[0],initial)
        rows=self.db.execute("SELECT user_id,amount,event_key FROM wallet_ledger WHERE kind IN ('transfer_in','transfer_out') ORDER BY user_id").fetchall()
        self.assertEqual([(r[0],r[1]) for r in rows],[(1,-1000),(2,1000)]);self.assertEqual(rows[0][2],rows[1][2])
        transfers.initialize(self.db)
        self.assertTrue(transfers.send(self.db,self.sender,self.payload,101)['replayed'])
        self.assertEqual(transfers.history(self.db,1,102)['transfers'][0]['direction'],'out')
        self.assertEqual(transfers.history(self.db,2,102)['transfers'][0]['direction'],'in')
        self.assertEqual(transfers.history(self.db,3,102)['transfers'],[])
        with self.assertRaises(transfers.TransferError):transfers.record(self.db,result['transfer']['id'],3)
        for change in ({'amount':999},{'recipient_id':3,'recipient_username':'carol'},{'note':'改動內容'}):
            with self.assertRaises(transfers.TransferError) as error:transfers.send(self.db,self.sender,{**self.payload,**change},103)
            self.assertEqual(error.exception.status,409)
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_results').fetchone()[0],0)

    def test_invalid_values_and_unavailable_table_chips(self):
        for change in ({'amount':0},{'amount':-1},{'amount':True},{'amount':1.5},{'amount':1_000_001},{'recipient_id':1},{'recipient_id':True},{'recipient_id':999},{'recipient_username':'carol'},{'note':'x'*121},{'operation_id':'short'}):
            with self.assertRaises(transfers.TransferError):transfers.send(self.db,self.sender,{**self.payload,**change},100)
        user=dict(id=1,username='alice',nickname='Alice')
        online.mutate(self.db,'/api/online/rooms',dict(game_type='slot',name='test',buy_in=2500),user,100)
        self.assertEqual(wallet.view(self.db,1,100)['total'],3000)
        with self.assertRaises(transfers.TransferError) as error:transfers.send(self.db,self.sender,self.payload,101)
        self.assertEqual(error.exception.reason,'insufficient_balance')
        self.assertEqual(self.db.execute('SELECT count(*) FROM point_transfers').fetchone()[0],0)

    def test_recipient_failure_rolls_back_both_sides_and_receipt(self):
        original=wallet.transfer
        def fail(db,uid,*args):
            if uid==2:raise RuntimeError('simulated receiver failure')
            return original(db,uid,*args)
        with patch.object(wallet,'transfer',side_effect=fail):
            with self.assertRaises(RuntimeError):transfers.send(self.db,self.sender,self.payload,100)
        self.assertEqual(wallet.view(self.db,1,101)['balance'],3000)
        self.assertEqual(wallet.view(self.db,2,101)['balance'],3000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM point_transfers').fetchone()[0],0)

    def test_search_escaping_and_history_pagination(self):
        self.assertEqual(transfers.recipients(self.db,1,'bo')['recipients'][0]['username'],'bob')
        self.assertEqual(transfers.recipients(self.db,1,'%')['recipients'],[])
        self.assertEqual(transfers.recipients(self.db,1,'_')['recipients'],[])
        for i in range(35):transfers.send(self.db,self.sender,{**self.payload,'amount':1,'operation_id':f'pagination_op_{i:06}'},100+i)
        first=transfers.history(self.db,1,200);self.assertEqual(len(first['transfers']),30)
        second=transfers.history(self.db,1,200,first['next_before']);self.assertEqual(len(second['transfers']),5);self.assertIsNone(second['next_before'])
        self.assertFalse(set(r['id'] for r in first['transfers'])&set(r['id'] for r in second['transfers']))


class TransferAPI(fixtures.ServerTestCase):
    def test_auth_concurrency_live_balances_and_receipts(self):
        a,b,c=self.clients[:3]
        self.assertEqual(a.call('/api/wallet/transfers')[0],401)
        self.assertEqual(a.call('/api/wallet/recipients?search=bob')[0],401)
        self.assertEqual(a.call('/api/wallet/transfers',{})[0],401)
        a.call('/api/register',dict(username='alice',nickname='Alice',password='password123'))
        code=a.call('/api/state')[1]['invite_code']
        for client,name in [(b,'bob'),(c,'carol')]:self.assertEqual(client.call('/api/register',dict(username=name,nickname=name,password='password123',invite_code=code))[0],200)
        recipient=a.call('/api/wallet/recipients?search=bob')[1]['recipients'][0]
        request=dict(recipient_id=recipient['id'],recipient_username='BOB',amount=500,note='HTTP測試',operation_id='http_transfer_000001')
        self.assertEqual(a.call('/api/wallet/transfers',request,origin='https://foreign.invalid')[0],403)
        with closing(Stream(b,'/api/online/events?presence=client')) as stream:
            stream.state()
            with ThreadPoolExecutor(2) as pool:replies=list(pool.map(lambda _:a.call('/api/wallet/transfers',request),range(2)))
            self.assertTrue(all(r[0]==200 for r in replies));self.assertEqual(sum(not r[1]['replayed'] for r in replies),1)
            state=stream.state();self.assertEqual(state['wallet']['balance'],3500)
        self.assertEqual(c.call('/api/wallet/transfers')[1]['transfers'],[])
        self.assertEqual(len(a.call('/api/wallet/transfers')[1]['transfers']),1)
        self.assertEqual(a.call('/api/wallet/transfers',{**request,'amount':501})[0],409)
        room=a.call('/api/online/rooms',dict(name='funds',game_type='slot',buy_in=2000))[1]
        self.assertIn('id',room)
        self.assertEqual(a.call('/api/wallet/transfers',{**request,'amount':501,'operation_id':'insufficient_test_001'})[0],400)
        requests=[{**request,'amount':400,'operation_id':f'concurrent_test_{i:04}'} for i in range(2)]
        with ThreadPoolExecutor(2) as pool:replies=list(pool.map(lambda payload:a.call('/api/wallet/transfers',payload),requests))
        self.assertEqual(sorted(r[0] for r in replies),[200,400])
        self.assertEqual(a.call('/api/wallet/transfers')[1]['wallet']['balance'],100)
        self.assertEqual(b.call('/api/wallet/transfers')[1]['wallet']['balance'],3900)
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('INSERT INTO club_admins VALUES(2,1,0)');db.commit()
        self.assertEqual(b.call('/api/wallet/transfers',dict(recipient_id=1,recipient_username='alice',amount=1,operation_id='admin_first_gate_001'))[0],403)

if __name__=='__main__':unittest.main()
