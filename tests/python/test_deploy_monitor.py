from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ops import audit_deployment as a, deploy_monitor as m

SHA = 'a' * 40


class DataAudit(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.live = Path(temp.name)/'live.sqlite3'; self.saved = Path(temp.name)/'saved.sqlite3'
        with closing(sqlite3.connect(self.live)) as db, db:
            for table in a.TABLES:
                if table == 'wallet_ledger':
                    db.execute('CREATE TABLE wallet_ledger(id INTEGER PRIMARY KEY,user_id INTEGER,amount INTEGER)')
                    db.execute('INSERT INTO wallet_ledger VALUES(1,1,100)')
                else:
                    db.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY,value TEXT)')
                    db.execute('INSERT INTO '+table+' VALUES(1,?)',('original',))
            db.execute('CREATE TABLE wallets(user_id INTEGER PRIMARY KEY,balance INTEGER)')
            db.execute('INSERT INTO wallets VALUES(1,100)')
        shutil.copyfile(self.live,self.saved)

    def test_allows_legitimate_new_transactions_without_resetting_baseline(self):
        with closing(sqlite3.connect(self.live)) as db, db:
            db.execute('INSERT INTO wallet_ledger VALUES(2,1,25)')
            db.execute('UPDATE wallets SET balance=125')
            db.execute("INSERT INTO poker_hands VALUES(2,'new hand')")
        result=a.audit(self.live,self.saved)
        self.assertTrue(result['passed']); self.assertEqual(result['unexplained_wallet_changes'],0)
        self.assertEqual(result['counts']['poker_hands'],dict(before=1,after=2))

    def test_detects_unexplained_balance_and_modified_history(self):
        with closing(sqlite3.connect(self.live)) as db, db:
            db.execute('UPDATE wallets SET balance=999')
            db.execute("UPDATE poker_hands SET value='changed'")
        result=a.audit(self.live,self.saved)
        self.assertFalse(result['passed']);self.assertEqual(result['unexplained_wallet_changes'],1)
        self.assertEqual(result['old_record_differences']['poker_hands'],1)

    def test_missing_backup_is_not_created_and_missing_user_fails(self):
        missing=self.saved.with_name('missing.sqlite3')
        with self.assertRaises(sqlite3.OperationalError):a.audit(self.live,missing)
        self.assertFalse(missing.exists())
        with closing(sqlite3.connect(self.live)) as db, db:db.execute('DELETE FROM users')
        self.assertFalse(a.audit(self.live,self.saved)['passed'])


class Monitor(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=patch.object(m,'OUT',Path(temp.name));p.start();self.addCleanup(p.stop)
        self.run=dict(path='.github/workflows/deploy.yml',event='workflow_dispatch',head_branch='main',
                      head_sha=SHA,status='in_progress',conclusion=None)
        self.state=dict(receipt=dict(sha=SHA,image='image'),image='image',backup_ok=True,health='healthy')

    def test_identity_and_receipt_fail_closed(self):
        m.identity(self.run,SHA);m.verify_receipt(self.state,SHA)
        for field,value in [('event','pull_request'),('head_sha','b'*40),('head_branch','other')]:
            with self.assertRaises(m.Failed):m.identity(dict(self.run,**{field:value}),SHA)
        for field,value in [('image','older'),('backup_ok',False),('health','unhealthy')]:
            with self.assertRaises(m.Failed):m.verify_receipt(dict(self.state,**{field:value}),SHA)

    def test_quiet_polling_accepts_receipt_even_when_github_lags(self):
        output=io.StringIO()
        def api(path):
            return {'jobs':[{'name':'deploy','status':'in_progress'}]} if path.endswith('/jobs') else self.run
        with patch.object(m,'api',side_effect=api), patch.object(m,'server_state',side_effect=[{'receipt':None},{'receipt':None},self.state]), \
                patch.object(m,'finish',return_value=dict(status='success',run_id='11',sha=SHA,backup='backup',health='healthy')), \
                patch.object(m.time,'sleep'), redirect_stdout(output):
            self.assertEqual(m.monitor('11',SHA,30,60),0)
        self.assertEqual(output.getvalue().count('Deployment phase: deploy'),1)
        self.assertEqual(json.loads((m.OUT/'11.json').read_text())['status'],'success')

    def test_failed_workflow_and_timeout_never_dispatch_or_report_success(self):
        with patch.object(m,'api',return_value=dict(self.run,status='completed',conclusion='failure')), \
                patch.object(m,'server_state',return_value={'receipt':None}), patch.object(m,'finish') as finish:
            with self.assertRaises(m.Failed):m.monitor('11',SHA,30,60)
            finish.assert_not_called()
        with patch.object(m.time,'monotonic',side_effect=[0,2]), patch.object(m,'api') as api:
            with self.assertRaisesRegex(m.Failed,'not cancelled'):m.monitor('11',SHA,30,1)
            api.assert_not_called()

    def test_resume_does_not_dispatch_and_invalid_id_never_runs_commands(self):
        m.save(m.OUT/'latest.json',dict(run_id='11',sha=SHA))
        with patch.object(m,'monitor',return_value=0), patch.object(m,'command') as command, redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(['--resume']),0)
            self.assertEqual(m.main(['--run-id','11;echo injected']),1)
            command.assert_not_called()

    def test_uncertain_dispatch_is_not_retried_or_resumed_as_an_old_run(self):
        m.save(m.OUT/'latest.json',dict(run_id='10',sha=SHA))
        with patch.object(m,'api',side_effect=lambda path: {'sha':SHA} if path=='/commits/main' else {'status':'completed'}), \
                patch.object(m,'command',return_value=SimpleNamespace(returncode=1,stdout=b'',stderr=b'')) as command, redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(['--start']),1)
            self.assertEqual(m.main(['--resume']),1)
            self.assertEqual(m.main(['--start']),1)
            self.assertEqual(command.call_count,1)
        self.assertNotIn('run_id',json.loads((m.OUT/'latest.json').read_text()))

    def test_active_previous_run_blocks_duplicate_dispatch(self):
        m.save(m.OUT/'latest.json',dict(run_id='11',sha=SHA))
        with patch.object(m,'api',return_value={'status':'in_progress'}), patch.object(m,'command') as command, redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(['--start']),1)
            command.assert_not_called()

    def test_asset_parser_checks_local_scripts_and_styles_only(self):
        parser=m.Assets();parser.feed('<script src="/game.js?v=one"></script><link href="/night.css"><script src="https://elsewhere/x.js"></script>')
        self.assertEqual(parser.paths,{'/','/game.js','/night.css'})


if __name__ == '__main__':unittest.main()
