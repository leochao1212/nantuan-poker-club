"""Administrator boundary, private fields, audited grants and first-login credentials."""
import concurrent.futures
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
import club_admin,online,wallet
from poker_engine import RuleError
from .test_app import ServerTestCase,Client


class AdminRules(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);self.db.row_factory=sqlite3.Row
        self.db.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT,created_at TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);')
        self.db.executemany('INSERT INTO users VALUES(?,?,?,?)',[(i,f'user_{i}',f'Player{i}','2026-10-20T00:00:00Z') for i in range(1,4)])
        online.initialize(self.db);self.db.execute('INSERT INTO club_admins VALUES(1,0,?)',(time.time(),));self.db.commit()
        self.actor={'id':1};self.clock=time.time()
        self.request={'user_id':2,'amount':500,'note':'test allowance','operation_id':'grant_regression_0001'}

    def test_permissions_and_first_password_gate(self):
        with self.assertRaises(club_admin.AdminError):club_admin.grant(self.db,{'id':2},self.request,self.clock)
        self.db.execute('UPDATE club_admins SET password_change_required=1')
        with self.assertRaises(club_admin.AdminError):club_admin.accounts(self.db,self.actor,self.clock)
        with self.assertRaises(club_admin.AdminError):club_admin.grant(self.db,self.actor,self.request,self.clock)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],3000)

    def test_grant_is_persisted_once_and_conflicting_retry_rejected(self):
        result=club_admin.grant(self.db,self.actor,self.request,self.clock);self.db.commit()
        again=club_admin.grant(self.db,self.actor,self.request,self.clock+1)
        self.assertEqual(result['grant_id'],again['grant_id']);self.assertTrue(again['replayed'])
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],3500)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='admin_grant'").fetchone()[0],1)
        for change in ({'amount':501},{'user_id':3},{'note':'different'}):
            with self.assertRaises(club_admin.AdminError):club_admin.grant(self.db,self.actor,{**self.request,**change},self.clock+2)

    def test_grant_validation_and_missing_account_leave_no_ledger(self):
        for amount in (True,False,0,-1,1.5,'1000',1_000_001):
            with self.assertRaises(Exception):club_admin.grant(self.db,self.actor,{**self.request,'amount':amount},self.clock)
        with self.assertRaises(Exception):club_admin.grant(self.db,self.actor,{**self.request,'note':' '},self.clock)
        with self.assertRaises(club_admin.AdminError):club_admin.grant(self.db,self.actor,{**self.request,'user_id':999},self.clock)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_grants').fetchone()[0],0)

    def test_snapshot_search_pagination_and_private_cards(self):
        rid=online.mutate(self.db,'/api/online/rooms',{'name':'Admin test'},
          {'id':1,'nickname':'Admin'},self.clock)['id']
        room=online.get_room(self.db,rid)
        online.mutate(self.db,f'/api/online/rooms/{rid}/join',{'revision':room['revision']},{'id':2,'nickname':'P2'},self.clock+1)
        room=online.get_room(self.db,rid)
        online.mutate(self.db,f'/api/online/rooms/{rid}/start',{'revision':room['revision']},{'id':1},self.clock+2)
        snapshot=club_admin.accounts(self.db,self.actor,self.clock+3)
        person=next(p for p in snapshot['accounts'] if p['id']==2)
        self.assertEqual(person['total'],3000);self.assertEqual(person['room']['status'],'playing')
        self.assertNotIn('hole',json.dumps(snapshot));self.assertNotIn('deck',json.dumps(snapshot))
        self.assertEqual(club_admin.accounts(self.db,self.actor,self.clock,'user_2')['total_matches'],1)
        self.assertEqual(club_admin.accounts(self.db,self.actor,self.clock,'%',1)['total_matches'],0)
        self.assertEqual(club_admin.accounts(self.db,self.actor,self.clock,'',2)['accounts'],[])

    def test_audit_and_chips_roll_back_together(self):
        with self.assertRaises(RuntimeError):
            with self.db:
                club_admin.grant(self.db,self.actor,self.request,self.clock)
                raise RuntimeError('transaction aborted')
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],3000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_grants').fetchone()[0],0)

    def test_owner_maintenance_grant_has_accurate_audit_source(self):
        wallet.transfer(self.db,2,1000,'owner_grant','owner:synthetic:once',self.clock)
        history=club_admin.accounts(self.db,self.actor,self.clock)['history']
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]['actor_username'],'system')
        self.assertEqual(history[0]['amount'],1000)

    def test_signed_adjustments_exact_balance_replay_and_conflict(self):
        request={**self.request,'amount':-3000}
        result=club_admin.adjust(self.db,self.actor,request,self.clock);self.db.commit()
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],0)
        self.assertTrue(club_admin.adjust(self.db,self.actor,request,self.clock+1)['replayed'])
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='admin_adjustment'").fetchone()[0],1)
        for change in ({'amount':3000},{'user_id':3},{'note':'changed'}):
            with self.assertRaises(club_admin.AdminError):club_admin.adjust(self.db,self.actor,{**request,**change},self.clock)
        history=club_admin.accounts(self.db,self.actor,self.clock)['history']
        self.assertEqual(history[0]['amount'],-3000)
        self.assertEqual(history[0]['actor_username'],'user_1')
        added=club_admin.adjust(self.db,self.actor,{**request,'amount':500,'operation_id':'adjust_positive_0001'},self.clock+2)
        self.assertEqual(added['wallet']['balance'],500)

    def test_adjustment_permissions_and_validation(self):
        with self.assertRaises(club_admin.AdminError):club_admin.adjust(self.db,{'id':2},self.request,self.clock)
        for amount in (True,False,0,-1_000_001,1_000_001,1.5,'-100'):
            with self.assertRaises(RuleError):club_admin.adjust(self.db,self.actor,{**self.request,'amount':amount},self.clock)
        for change in ({'note':' '},{'operation_id':'bad'},{'user_id':True}):
            with self.assertRaises(RuleError):club_admin.adjust(self.db,self.actor,{**self.request,**change},self.clock)
        with self.assertRaises(club_admin.AdminError):club_admin.adjust(self.db,self.actor,{**self.request,'user_id':999},self.clock)
        self.db.execute('UPDATE club_admins SET password_change_required=1')
        with self.assertRaises(club_admin.AdminError):club_admin.adjust(self.db,self.actor,self.request,self.clock)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_adjustments').fetchone()[0],0)

    def test_deduct_only_wallet_while_seated(self):
        rid=online.mutate(self.db,'/api/online/rooms',{'name':'Preserve table'},{'id':2,'nickname':'Player2'},self.clock)['id']
        original=self.db.execute('SELECT state FROM poker_rooms WHERE id=?',(rid,)).fetchone()[0]
        request={**self.request,'amount':-2001}
        with self.assertRaises(RuleError):club_admin.adjust(self.db,self.actor,request,self.clock)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],2000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_adjustments').fetchone()[0],0)
        result=club_admin.adjust(self.db,self.actor,{**request,'amount':-2000},self.clock)
        self.assertEqual(result['wallet']['balance'],0);self.assertEqual(result['wallet']['in_play'],1000)
        self.assertEqual(self.db.execute('SELECT state FROM poker_rooms WHERE id=?',(rid,)).fetchone()[0],original)

    def test_adjustment_and_audit_rollback_together(self):
        with self.assertRaises(RuntimeError):
            with self.db:
                club_admin.adjust(self.db,self.actor,{**self.request,'amount':-500},self.clock)
                raise RuntimeError('transaction aborted')
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],3000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_adjustments').fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM wallet_ledger WHERE kind='admin_adjustment'").fetchone()[0],0)

    def test_restart_preserves_old_grants_and_new_deductions(self):
        club_admin.grant(self.db,self.actor,self.request,self.clock)
        club_admin.adjust(self.db,self.actor,{**self.request,'amount':-200},self.clock+1)
        self.db.commit();online.initialize(self.db)
        self.assertEqual(wallet.view(self.db,2,self.clock)['balance'],3300)
        self.assertEqual(sorted(row['amount'] for row in club_admin.accounts(self.db,self.actor,self.clock)['history']),[-200,500])


class AdminAPI(ServerTestCase):
    def test_dedicated_admin_password_rotation_permission_and_concurrent_retry(self):
        normal=self.clients[0]
        self.assertEqual(normal.call('/api/register',{'username':'normal','nickname':'Normal','password':'password123','is_admin':True})[0],200)
        self.assertFalse(normal.call('/api/online/lobby')[1]['me']['is_admin'])
        self.assertEqual(Client(self.base).call('/api/admin/accounts')[0],401)
        self.assertEqual(normal.call('/api/admin/accounts')[0],403)
        env=dict(os.environ,POKER_DB=str(self.db_path),PYTHONIOENCODING='utf-8')
        command=[sys.executable,str(Path(__file__).resolve().parents[2]/'manage_admin.py'),'create','--username','test_admin']
        created=subprocess.run(command,input='SyntheticAdmin123!\n',text=True,capture_output=True,env=env)
        self.assertEqual(created.returncode,0,created.stderr)
        admin=self.clients[1];login={'username':'test_admin','password':'SyntheticAdmin123!'}
        self.assertEqual(admin.call('/api/login',login)[0],200)
        self.assertEqual(admin.call('/api/admin/accounts')[1]['reason'],'password_change_required')
        old=Client(self.base);self.assertEqual(old.call('/api/login',login)[0],200)
        self.assertEqual(admin.call('/api/admin/password',{'current_password':'wrongpassword','new_password':'SyntheticNew456!'})[0],403)
        self.assertEqual(admin.call('/api/admin/password',{'current_password':login['password'],'new_password':'SyntheticNew456!'})[0],200)
        self.assertEqual(old.call('/api/admin/accounts')[0],401)
        self.assertEqual(old.call('/api/login',login)[0],401)
        self.assertEqual(old.call('/api/login',{**login,'password':'SyntheticNew456!'})[0],200)
        snapshot=admin.call('/api/admin/accounts')[1]
        self.assertEqual(snapshot['total_accounts'],2)
        for field in ('password_hash','salt','token_hash','hole','deck'):self.assertNotIn(field,json.dumps(snapshot))
        request={'user_id':1,'amount':750,'note':'API grant','operation_id':'api_grant_once_00001'}
        self.assertEqual(normal.call('/api/admin/grants',request)[0],403)
        self.assertEqual(normal.call('/api/admin/password',{})[0],403)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:admin.call('/api/admin/grants',request),range(4)))
        self.assertEqual([r[0] for r in results],[200]*4)
        self.assertEqual(normal.call('/api/online/lobby')[1]['wallet']['balance'],3750)
        self.assertEqual(len(admin.call('/api/admin/accounts')[1]['history']),1)
        self.assertEqual(admin.call('/api/admin/grants',{**request,'amount':751})[0],409)
        adjustment={**request,'amount':-750,'operation_id':'api_adjust_once_0001'}
        self.assertEqual(Client(self.base).call('/api/admin/adjustments',adjustment)[0],401)
        self.assertEqual(normal.call('/api/admin/adjustments',adjustment)[0],403)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:admin.call('/api/admin/adjustments',adjustment),range(4)))
        self.assertEqual([r[0] for r in results],[200]*4)
        self.assertEqual(normal.call('/api/online/lobby')[1]['wallet']['balance'],3000)
        self.assertEqual(admin.call('/api/admin/adjustments',{**adjustment,'amount':750})[0],409)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda i:admin.call('/api/admin/adjustments',{**adjustment,'amount':-2000,'operation_id':f'api_adjust_race_000{i}'}),range(2)))
        self.assertEqual(sorted(r[0] for r in results),[200,400])
        self.assertEqual(normal.call('/api/online/lobby')[1]['wallet']['balance'],1000)
        self.assertEqual(len(admin.call('/api/admin/accounts')[1]['history']),3)
        duplicate=subprocess.run(command,input='AnotherPassword123!\n',text=True,capture_output=True,env=env)
        self.assertNotEqual(duplicate.returncode,0)
        self.assertEqual(old.call('/api/login',{**login,'password':'SyntheticNew456!'})[0],200)


if __name__=='__main__':unittest.main(verbosity=2)
