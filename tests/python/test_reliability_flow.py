import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading
import unittest
import tempfile
import hashlib
from contextlib import closing
from unittest.mock import patch

import market_data, market_tw
from realtime import WriteQueue, QueueBusy
from ops.audit_deployment import market_audit
from ops.verify_restore import verify
from ops.service_health import probe


class ReliabilityFlow(unittest.TestCase):
    def test_restore_uses_a_copy_and_leaves_source_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'saved.sqlite3'
            with closing(sqlite3.connect(source)) as db, db:
                for table in ('users','wallet_ledger','poker_hands','market_orders','market_contract_orders'):
                    db.execute('CREATE TABLE '+table+'(id INTEGER)')
                    db.execute('INSERT INTO '+table+' VALUES(1)')
                db.execute('CREATE TABLE wallets(balance INTEGER)')
                db.execute('INSERT INTO wallets VALUES(200)')
            before = hashlib.sha256(source.read_bytes()).digest()
            self.assertTrue(verify(source, folder)['passed'])
            self.assertEqual(before, hashlib.sha256(source.read_bytes()).digest())
            self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_monitor_requires_application_health_not_just_http_success(self):
        from types import SimpleNamespace
        with patch('ops.service_health.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'{"ok":false}')):
            self.assertFalse(probe('http://localhost/api/health')['ok'])
        with patch('ops.service_health.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'{"ok":true}')):
            self.assertTrue(probe('http://localhost/api/health')['ok'])
    def test_queue_refuses_before_mutation_and_recovers_after_timeout(self):
        q = WriteQueue(max_pending=2, wait_seconds=.05)
        def attempt():
            with q.enter():
                self.fail('Timed-out request must never enter a transaction')
        with q.enter(), ThreadPoolExecutor(1) as pool:
            with self.assertRaises(QueueBusy):
                pool.submit(attempt).result(timeout=1)
        with q.enter():
            self.assertEqual(q.metrics()['pending'], 1)
        self.assertEqual(q.metrics(), dict(pending=0, capacity=2, rejected=1))

    def test_capacity_rejection_does_not_leave_ticket_hole(self):
        q = WriteQueue(max_pending=1)
        with q.enter():
            with self.assertRaises(QueueBusy):
                with q.enter(): pass
        with q.enter(): pass
        self.assertEqual(q.next_ticket, q.serving)

    def test_calendar_is_started_and_applied_through_provider_pipeline(self):
        tree = ast.parse(Path('server.py').read_text(encoding='utf8'))
        loop = next(n for n in ast.walk(tree) if isinstance(n, ast.For)
                    and isinstance(n.target, ast.Name) and n.target.id == 'provider')
        self.assertEqual(ast.unparse(loop.iter), 'market_data.PROVIDERS')
        self.assertIn('TW_CALENDAR', market_data.PROVIDERS)
        with sqlite3.connect(':memory:') as db:
            db.row_factory = sqlite3.Row
            market_tw.initialize(db)
            db.execute('CREATE TABLE market_providers(name TEXT PRIMARY KEY,next_at REAL,last_at REAL,status TEXT)')
            with patch.object(market_data, 'read_provider', return_value=([(2027, ['2027-01-01'])], 'ok', 1, None)):
                results = market_data.refresh(['TW_CALENDAR'], 0, None)
            market_data.apply(db, results, 0)
            self.assertEqual(db.execute('SELECT closed FROM market_tw_calendar WHERE year=2027').fetchone()[0], '["2027-01-01"]')

    def test_trade_audit_allows_settlement_but_detects_history_changes(self):
        with sqlite3.connect(':memory:') as db:
            db.execute("ATTACH DATABASE ':memory:' AS saved")
            for schema in ('main', 'saved'):
                db.execute(f'CREATE TABLE {schema}.market_orders(id INT,user_id INT,symbol TEXT,status TEXT)')
                db.executemany(f'INSERT INTO {schema}.market_orders VALUES(?,?,?,?)', [(1,1,'TW:2330','pending'),(2,1,'TW:2330','filled')])
            db.execute("UPDATE main.market_orders SET status='filled' WHERE id=1")
            self.assertEqual(market_audit(db)['market_orders']['changed_completed'], 0)
            db.execute('UPDATE main.market_orders SET user_id=2 WHERE id=2')
            self.assertEqual(market_audit(db)['market_orders'], dict(missing_or_reassigned=1, changed_completed=1))
