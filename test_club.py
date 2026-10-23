"""Account chips, migration, daily Taipei claims, chat/voice authorization."""
from contextlib import closing
import json
import sqlite3
import unittest
import wallet,online,social
from test_app import ServerTestCase


class WalletRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);self.db.row_factory=sqlite3.Row
        self.db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TESTCODE');")
        self.db.executemany('INSERT INTO users VALUES(?,?,?)',[(i,f'u{i}',f'P{i}') for i in range(1,4)])
        online.initialize(self.db)
        self.users=[{'id':i,'username':f'u{i}','nickname':f'P{i}'} for i in range(1,4)]
        self.clock=1792425600

    def create(self):
        return online.mutate(self.db,'/api/online/rooms',{'name':'Wallet table'},self.users[0],self.clock)['id']

    def test_initial_join_rebuy_leave_conserve_account_chips(self):
        rid=self.create();path=f'/api/online/rooms/{rid}'
        self.assertEqual(wallet.view(self.db,1,self.clock)['balance'],2000)
        self.assertEqual(wallet.view(self.db,1,self.clock)['total'],3000)
        online.mutate(self.db,path+'/rebuy',{'operation_id':'wallet_rebuy_000001'},self.users[0],self.clock+1)
        self.assertEqual(wallet.view(self.db,1,self.clock)['balance'],1000)
        self.assertEqual(wallet.view(self.db,1,self.clock)['total'],3000)
        online.mutate(self.db,path+'/leave',{'operation_id':'wallet_leave_000001'},self.users[0],self.clock+2)
        self.assertEqual(wallet.view(self.db,1,self.clock)['balance'],3000)
        online.mutate(self.db,path+'/leave',{'operation_id':'wallet_leave_000001'},self.users[0],self.clock+3)
        self.assertEqual(wallet.view(self.db,1,self.clock)['balance'],3000)

    def test_daily_once_and_taipei_midnight(self):
        before=1792425599
        # Pick actual neighboring instants straddling Taipei midnight.
        from datetime import datetime,timezone
        before=datetime(2026,10,19,15,59,59,tzinfo=timezone.utc).timestamp()
        self.assertTrue(wallet.claim(self.db,1,before)['claimed'])
        self.assertFalse(wallet.claim(self.db,1,before+.5)['claimed'])
        self.assertTrue(wallet.claim(self.db,1,before+1)['claimed'])
        self.assertEqual(wallet.view(self.db,1,before+1)['balance'],5000)

    def test_insufficient_wallet_and_repeated_initialization(self):
        rid=self.create();path=f'/api/online/rooms/{rid}'
        for i in range(2):online.mutate(self.db,path+'/rebuy',{'operation_id':f'insufficient_{i:08d}'},self.users[0],self.clock+i)
        with self.assertRaisesRegex(Exception,'不足'):
            online.mutate(self.db,path+'/rebuy',{'operation_id':'insufficient_final_01'},self.users[0],self.clock+3)
        wallet.maybe_activate(self.db,self.clock+4)
        self.assertEqual(wallet.view(self.db,1,self.clock)['balance'],0)
        self.assertEqual(wallet.view(self.db,1,self.clock)['total'],3000)

    def test_reset_waits_for_hand_and_closes_legacy_tables(self):
        rid=self.create();path=f'/api/online/rooms/{rid}'
        room=online.get_room(self.db,rid)
        online.mutate(self.db,path+'/join',{'revision':room['revision']},self.users[1],self.clock+1)
        room=online.get_room(self.db,rid)
        online.mutate(self.db,path+'/start',{'revision':room['revision']},self.users[0],self.clock+2)
        self.db.execute('DELETE FROM wallet_ledger');self.db.execute('DELETE FROM wallets')
        self.db.execute("UPDATE wallet_meta SET value='pending' WHERE key='state'")
        self.assertFalse(wallet.maybe_activate(self.db,self.clock+3))
        room=online.get_room(self.db,rid);uid=room['hand']['actor']
        online.mutate(self.db,path+'/action',{'revision':room['revision'],'hand_id':room['hand']['id'],'turn_id':room['hand']['turn_id'],'action':'fold'},self.users[uid-1],self.clock+4)
        self.assertTrue(wallet.maybe_activate(self.db,self.clock+5))
        self.assertEqual(online.get_room(self.db,rid)['status'],'closed')
        self.assertEqual(self.db.execute('SELECT count(*) FROM poker_hands').fetchone()[0],1)
        self.assertEqual([r[0] for r in self.db.execute('SELECT balance FROM wallets')],[3000,3000,3000])

    def test_play_and_exit_preserve_wallet_sum(self):
        rid=self.create();path=f'/api/online/rooms/{rid}'
        room=online.get_room(self.db,rid)
        online.mutate(self.db,path+'/join',{'revision':room['revision']},self.users[1],self.clock+1)
        room=online.get_room(self.db,rid)
        online.mutate(self.db,path+'/start',{'revision':room['revision']},self.users[0],self.clock+2)
        room=online.get_room(self.db,rid);uid=room['hand']['actor']
        online.mutate(self.db,path+'/action',{'revision':room['revision'],'hand_id':room['hand']['id'],'turn_id':room['hand']['turn_id'],'action':'fold'},self.users[uid-1],self.clock+3)
        for i in range(2):
            room=online.get_room(self.db,rid)
            online.mutate(self.db,path+'/leave',{'revision':room['revision']},self.users[i],self.clock+4)
        values=[r[0] for r in self.db.execute('SELECT balance FROM wallets WHERE user_id IN (1,2)')]
        self.assertEqual(sum(values),6000);self.assertNotEqual(values[0],3000)


class ClubAPI(ServerTestCase):
    def test_many_accounts_six_seats_chat_voice_wallet(self):
        first=self.clients[0]
        first.call('/api/register',{'username':'club0','nickname':'P0','password':'password123'})
        code=first.call('/api/state')[1]['invite_code']
        for i in range(1,8):
            status,result=self.clients[i].call('/api/register',{'username':f'club{i}','nickname':f'P{i}','password':'password123','invite_code':code})
            self.assertEqual(status,200,result)
        self.assertIsNone(first.call('/api/bootstrap')[1]['account_limit'])
        lobby=first.call('/api/online/lobby')[1]
        self.assertEqual(lobby['total_members'],8)
        self.assertEqual(lobby['wallet']['total'],3000)
        self.assertEqual(first.call('/api/wallet/claim',{})[1]['wallet']['balance'],4000)
        self.assertFalse(first.call('/api/wallet/claim',{})[1]['claimed'])
        rid=first.call('/api/online/rooms',{'name':'Social room'})[1]['id'];path=f'/api/online/rooms/{rid}'
        for i in range(1,6):
            room=self.clients[i].call(path)[1]
            self.assertEqual(self.clients[i].call(path+'/join',{'revision':room['revision']})[0],200)
        room=self.clients[6].call(path)[1]
        self.assertEqual(self.clients[6].call(path+'/join',{'revision':room['revision']})[0],400)
        prefix=f'/api/social/rooms/{rid}/'
        self.assertEqual(self.clients[6].call(prefix+'chat',{'message':'spectator','nonce':'outsider_chat_0001'})[0],200)
        self.assertEqual(self.clients[6].call(prefix+'voice/join',{'session_id':'spectator_voice_0001'})[0],200)
        self.clients[6].call(prefix+'voice/leave',{'session_id':'spectator_voice_0001'})
        message={'message':'<script>alert(1)</script> 測試','nonce':'chat_regression_0001'}
        self.assertEqual(first.call(prefix+'chat',message)[0],200)
        self.assertEqual(first.call(prefix+'chat',message)[0],200)
        self.assertEqual(first.call(prefix+'chat',{**message,'message':'changed content'})[0],400)
        after=first.call(path)[1]
        self.assertEqual(len(after['social']['messages']),2)
        self.assertEqual(after['revision'],room['revision'])
        self.assertEqual(after['social']['messages'][1]['message'],message['message'])
        sessions=['voice_session_0000001','voice_session_0000002']
        for i in range(2):self.assertEqual(self.clients[i].call(prefix+'voice/join',{'session_id':sessions[i]})[0],200)
        signal={'session_id':sessions[0],'target_id':2,'target_session':sessions[1],'kind':'offer','payload':{'type':'offer','sdp':'v=0\r\n'}}
        self.assertEqual(first.call(prefix+'voice/signal',signal)[0],200)
        self.assertEqual(len(self.clients[1].call(path)[1]['social']['signals']),1)
        self.assertEqual(len(self.clients[2].call(path)[1]['social']['signals']),0)
        self.assertEqual(first.call(prefix+'voice/signal',{**signal,'target_session':'wrong_session_000'})[0],400)
        self.assertEqual(first.call(prefix+'voice/ping',{'session_id':sessions[0],'muted':True})[0],200)
        self.assertTrue(first.call(path)[1]['social']['voice_members'][0]['muted'])
        self.assertEqual(first.call(prefix+'voice/leave',{'session_id':sessions[0]})[0],200)
        self.assertEqual(len(first.call(path)[1]['social']['voice_members']),1)
        from test_app import Client
        self.assertEqual(Client(self.base).call(prefix+'chat',{'message':'anonymous','nonce':'anonymous_chat_001'})[0],401)
        room=first.call(path)[1]
        self.assertEqual(first.call(path+'/close',{'revision':room['revision']})[0],200)
        self.assertEqual(self.clients[6].call(prefix+'chat',{'message':'closed','nonce':'closed_chat_00001'})[0],400)


if __name__=='__main__':unittest.main(verbosity=2)
