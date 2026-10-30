"""Real HTTP proofs for password work isolation and credential-version recheck."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3,tempfile,threading,time,unittest
from unittest.mock import patch
from contextlib import closing
import server as app
from . import test_app as fixtures
import arcade_engine as arcade
from realtime import Hub,WriteQueue


class AuthenticationReview(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.db=Path(temporary.name)/'auth.sqlite3'
        settings=patch.multiple(app,DB_PATH=self.db,REQUIRE_INVITE=False,SECURE_COOKIE=False,PUBLIC_ORIGIN='',ATTEMPTS={},WRITES=WriteQueue(),EVENTS=Hub())
        settings.start();self.addCleanup(settings.stop)
        quiet=patch.object(app,'print',lambda *args,**kwargs:None,create=True);quiet.start();self.addCleanup(quiet.stop)
        app.initialize()
        class Quiet(app.Handler):
            def log_message(self,*args):pass
        self.http=app.ThreadingHTTPServer(('127.0.0.1',0),Quiet);self.http.daemon_threads=True
        thread=threading.Thread(target=self.http.serve_forever,daemon=True);thread.start()
        def close():self.http.shutdown();self.http.server_close();thread.join(2)
        self.addCleanup(close)
        self.base=f'http://127.0.0.1:{self.http.server_port}'
        self.alice=fixtures.Client(self.base);self.bob=fixtures.Client(self.base)
        self.assertEqual(self.alice.call('/api/register',dict(username='alice',nickname='Alice',password='password123'))[0],200)
        code=self.alice.call('/api/state')[1]['invite_code']
        self.assertEqual(self.bob.call('/api/register',dict(username='bob',nickname='Bob',password='password123',invite_code=code))[0],200)

    def test_blocked_password_calculation_cannot_block_game_transaction_queue(self):
        started=threading.Event();release=threading.Event();original=app.pass_hash
        def slow(password,salt):started.set();release.wait(3);return original(password,salt)
        with patch.object(app,'pass_hash',side_effect=slow),ThreadPoolExecutor(1) as pool:
            pending=pool.submit(fixtures.Client(self.base).call,'/api/login',dict(username='alice',password='password123'))
            self.assertTrue(started.wait(1))
            try:
                begin=time.monotonic();reply=self.bob.call('/api/wallet/claim',{})
                self.assertEqual(reply[0],200);self.assertLess(time.monotonic()-begin,.5)
            finally:release.set()
            self.assertEqual(pending.result(timeout=4)[0],200)

    def test_password_changed_while_hashing_cannot_issue_old_credential_session(self):
        started=threading.Event();release=threading.Event();original=app.pass_hash
        def slow(password,salt):started.set();release.wait(3);return original(password,salt)
        new_salt='11'*16;new_hash=original('newpassword123',new_salt)
        with patch.object(app,'pass_hash',side_effect=slow),ThreadPoolExecutor(1) as pool:
            pending=pool.submit(fixtures.Client(self.base).call,'/api/login',dict(username='alice',password='password123'))
            self.assertTrue(started.wait(1))
            try:
                with closing(sqlite3.connect(self.db)) as db:
                    db.execute("UPDATE users SET salt=?,password_hash=? WHERE username='alice'",(new_salt,new_hash));db.commit()
            finally:release.set()
            self.assertEqual(pending.result(timeout=4)[0],401)
        self.assertEqual(fixtures.Client(self.base).call('/api/login',dict(username='alice',password='newpassword123'))[0],200)

    def test_one_account_failures_do_not_lock_other_accounts_behind_same_proxy(self):
        stranger=fixtures.Client(self.base)
        for _ in range(12):self.assertEqual(stranger.call('/api/login',dict(username='alice',password='incorrect123'))[0],401)
        self.assertEqual(stranger.call('/api/login',dict(username='alice',password='incorrect123'))[0],429)
        self.assertEqual(stranger.call('/api/login',dict(username='bob',password='password123'))[0],200)

    def test_proxy_abuse_cannot_exhaust_another_registered_account(self):
        c=fixtures.Client(self.base)
        for i in range(121):
            self.assertEqual(c.call('/api/register',dict(username=f'bad_registration_{i}',nickname='Test',password='password123',invite_code='WRONG'))[0],403)
        original=app.pass_hash
        with patch.object(app,'pass_hash',side_effect=lambda password,salt:'fake' if salt=='00'*16 else original(password,salt)):
            for i in range(120):self.assertEqual(c.call('/api/login',dict(username=f'absent_{i}',password='password123'))[0],401)
        self.assertEqual(c.call('/api/login',dict(username='absent_overflow',password='password123'))[0],429)
        self.assertEqual(c.call('/api/login',dict(username='bob',password='password123'))[0],200)

    def test_auth_hash_admission_does_not_hold_the_game_write_queue(self):
        self.assertTrue(app.AUTH_WORK.acquire(timeout=1));self.assertTrue(app.AUTH_WORK.acquire(timeout=1))
        try:
            started=time.monotonic()
            self.assertEqual(fixtures.Client(self.base).call('/api/login',dict(username='bob',password='password123'))[0],503)
            self.assertLess(time.monotonic()-started,2)
            self.assertEqual(self.bob.call('/api/wallet/claim',{})[0],200)
        finally:app.AUTH_WORK.release();app.AUTH_WORK.release()

    def test_existing_apk_resume_events_are_accepted_and_normalized(self):
        from pathlib import Path
        for reason in ('android_resume','resume'):
            status,_=self.alice.call('/api/online/client-event',dict(kind='recovery_started',client='android_contract_0001',attempt_id='resume_contract_00001',reason=reason))
            self.assertEqual(status,200)
        source=(Path(app.ROOT)/'mobile/nantuan_app/lib/main.dart').read_text(encoding='utf-8')
        self.assertIn("resumeConnections('resume')",source)

class RouletteReview(unittest.TestCase):
    def test_selected_chip_amount_does_not_require_the_original_room_denomination(self):
        for amount in (1,5,10):
            room=arcade.new_room('low balance',1,'roulette',50,1000)
            arcade.sit(room,1,'Alice',100)
            before=room['bank']+room['seats'][0]['stack']
            arcade.start_hand(room,101)
            arcade.act(room,1,'bet',102,data={'bets':[{'kind':'red','amount':amount}]})
            self.assertEqual(room['hand']['players'][0]['contribution'],amount)
            self.assertEqual(room['bank']+room['seats'][0]['stack'],before)

if __name__=='__main__':unittest.main()
