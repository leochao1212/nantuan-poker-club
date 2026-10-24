"""Custom buy-in/top-up amounts remain wallet-backed and idempotent."""
import json
import sqlite3
import unittest
import online
import wallet
import poker_engine as engine
from .test_app import ServerTestCase


class FundingRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);self.db.row_factory=sqlite3.Row
        self.db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,nickname TEXT)')
        self.db.executemany('INSERT INTO users VALUES(?,?)',[(i,f'P{i}') for i in range(1,4)])
        online.initialize(self.db)
        self.users={i:{'id':i,'nickname':f'P{i}'} for i in range(1,4)}
        self.clock=100

    def create(self,uid=1,**data):
        return online.mutate(self.db,'/api/online/rooms',data,self.users[uid],100)['id']

    def call(self,rid,command,uid=1,**data):
        self.clock+=1
        room=online.get_room(self.db,rid)
        return online.mutate(self.db,f'/api/online/rooms/{rid}/{command}',{'revision':room['revision'],**data},self.users[uid],self.clock)

    def test_create_any_positive_wallet_amount_including_all(self):
        for uid,amount in ((1,1),(2,237),(3,3000)):
            rid=self.create(uid,buy_in=amount)
            room=online.get_room(self.db,rid)
            self.assertEqual(room['seats'][0]['stack'],amount)
            self.assertEqual(wallet.view(self.db,uid,100)['balance'],3000-amount)
            self.assertEqual(wallet.view(self.db,uid,100)['total'],3000)

    def test_join_independent_amount_and_selected_seat_then_leave(self):
        rid=self.create()
        self.call(rid,'join',2,buy_in=42,seat=4)
        self.call(rid,'join',3,buy_in=3000)
        room=online.get_room(self.db,rid)
        self.assertEqual((engine.seated(room,2)['stack'],engine.seated(room,2)['seat']),(42,4))
        self.assertEqual(engine.seated(room,3)['stack'],3000)
        self.assertEqual(wallet.view(self.db,2,100)['balance'],2958)
        self.assertEqual(wallet.view(self.db,3,100)['balance'],0)
        self.call(rid,'leave',2);self.call(rid,'leave',3)
        self.assertEqual(wallet.view(self.db,2,100)['balance'],3000)
        self.assertEqual(wallet.view(self.db,3,100)['balance'],3000)

    def test_custom_top_up_and_legacy_default_use_remaining_wallet(self):
        rid=self.create()
        self.call(rid,'rebuy',amount=1801)
        self.call(rid,'rebuy')
        self.assertEqual(engine.seated(online.get_room(self.db,rid),1)['stack'],3000)
        self.assertEqual(wallet.view(self.db,1,100)['balance'],0)
        with self.assertRaisesRegex(engine.RuleError,'不足'):self.call(rid,'rebuy')

    def test_legacy_join_with_less_than_table_default(self):
        rid=self.create()
        wallet.transfer(self.db,2,-2901,'test_fixture','remaining_wallet',100)
        self.call(rid,'join',2)
        self.assertEqual(engine.seated(online.get_room(self.db,rid),2)['stack'],99)
        self.assertEqual(wallet.view(self.db,2,100)['balance'],0)

    def test_invalid_amounts_do_not_change_room_or_ledger(self):
        rid=self.create()
        for command,uid,key in (('join',2,'buy_in'),('rebuy',1,'amount')):
            for amount in (0,-1,1.5,True,None,'100',3001):
                with self.subTest(command=command,amount=amount):
                    before=json.dumps(online.get_room(self.db,rid),sort_keys=True)
                    ledger=self.db.execute('SELECT count(*) FROM wallet_ledger').fetchone()[0]
                    with self.assertRaises(engine.RuleError):self.call(rid,command,uid,**{key:amount})
                    self.assertEqual(json.dumps(online.get_room(self.db,rid),sort_keys=True),before)
                    self.assertEqual(self.db.execute('SELECT count(*) FROM wallet_ledger').fetchone()[0],ledger)
        for amount in (0,-1,1.5,True,None,'100',3001):
            with self.assertRaises(engine.RuleError):self.create(2,buy_in=amount)
        self.assertEqual(wallet.view(self.db,2,100)['balance'],3000)

    def test_custom_join_and_top_up_retry_do_not_debit_twice(self):
        rid=self.create()
        for command,uid,data in (('join',2,{'buy_in':777}),('rebuy',1,{'amount':333})):
            operation='funding-retry-'+command+'-0001'
            self.call(rid,command,uid,operation_id=operation,**data)
            balance=wallet.view(self.db,uid,100)['balance']
            self.assertTrue(self.call(rid,command,uid,operation_id=operation,**data)['replayed'])
            changed={key:value+1 for key,value in data.items()}
            self.assertEqual(self.call(rid,command,uid,operation_id=operation,**changed)['reason'],'operation_mismatch')
            self.assertEqual(wallet.view(self.db,uid,100)['balance'],balance)

    def test_full_wallet_above_old_million_and_table_caps(self):
        wallet.transfer(self.db,1,1_000_001,'test_fixture','large_wallet',100)
        rid=self.create(buy_in=1_003_001)
        self.assertEqual(wallet.view(self.db,1,100)['balance'],0)
        wallet.transfer(self.db,1,2000,'test_fixture','new_chips',101)
        self.call(rid,'rebuy',amount=2000)
        self.assertEqual(engine.seated(online.get_room(self.db,rid),1)['stack'],1_005_001)

    def test_join_during_hand_waits_and_top_up_stays_between_hands(self):
        rid=self.create()
        self.call(rid,'join',2,buy_in=2000)
        self.call(rid,'start')
        self.call(rid,'join',3,buy_in=7)
        room=online.get_room(self.db,rid)
        self.assertNotIn(3,[v['user_id'] for v in room['hand']['players']])
        balance=wallet.view(self.db,1,100)['balance']
        with self.assertRaises(engine.RuleError):self.call(rid,'rebuy',amount=100)
        self.assertEqual(wallet.view(self.db,1,100)['balance'],balance)


class FundingAPI(ServerTestCase):
    def test_custom_funding_over_http(self):
        a,b=self.clients[:2]
        self.assertEqual(a.call('/api/register',{'username':'funding_a','nickname':'A','password':'password123'})[0],200)
        invite=a.call('/api/state')[1]['invite_code']
        self.assertEqual(b.call('/api/register',{'username':'funding_b','nickname':'B','password':'password123','invite_code':invite})[0],200)
        status,result=a.call('/api/online/rooms',{'buy_in':123,'operation_id':'funding-create-0001'})
        self.assertEqual(status,200,result);path=f'/api/online/rooms/{result["id"]}'
        payload={'buy_in':3000,'seat':5,'operation_id':'funding-join-000001'}
        self.assertEqual(b.call(path+'/join',payload)[0],200)
        self.assertEqual(b.call(path+'/join',payload)[0],200)
        state=b.call(path)[1]
        self.assertEqual(state['wallet']['balance'],0)
        self.assertEqual(next(s['stack'] for s in state['seats'] if s['seat']==5),3000)
        self.assertEqual(a.call(path+'/rebuy',{'amount':2877,'operation_id':'funding-topup-0001'})[0],200)
        self.assertEqual(a.call(path)[1]['wallet']['balance'],0)
        self.assertEqual(a.call(path+'/rebuy',{'amount':1,'operation_id':'funding-empty-0001'})[0],400)


if __name__=='__main__':unittest.main()
