"""Deployment authorization, archive safety, draining and rollback boundaries."""
from contextlib import redirect_stdout, closing
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
import zipfile

from ops import deploy as d
import online
import poker_engine as poker
from . import test_club as fixtures

SHA = 'a' * 40


class DeploymentPolicy(unittest.TestCase):
    def setUp(self):
        self.request = {'token': 'x' * 30, 'run_id': '11', 'ci_run_id': '12', 'sha': SHA}
        self.responses = {
            '/actions/runs/11': {'path': '.github/workflows/deploy.yml', 'event': 'workflow_dispatch',
                'head_branch': 'main', 'head_sha': SHA, 'status': 'in_progress'},
            '/actions/runs/12': {'path': '.github/workflows/ci.yml', 'event': 'push',
                'head_branch': 'main', 'head_sha': SHA, 'status': 'completed', 'conclusion': 'success'},
            '/commits/main': {'sha': SHA},
            '/actions/runs/12/artifacts': {'artifacts': [{'id': 99, 'name': 'release-' + SHA, 'expired': False}]}}

    def api(self, path):
        return self.responses[path]

    def test_only_manual_main_with_successful_matching_build(self):
        self.assertEqual(d.validate_request(self.request, self.api), 99)
        for path, field, value in [('/actions/runs/11', 'event', 'pull_request'),
                ('/actions/runs/11', 'head_branch', 'design/unsafe'),
                ('/actions/runs/11', 'status', 'completed'),
                ('/actions/runs/12', 'conclusion', 'failure'),
                ('/actions/runs/12', 'head_sha', 'b' * 40),
                ('/commits/main', 'sha', 'b' * 40)]:
            old = self.responses[path][field]
            self.responses[path][field] = value
            with self.assertRaises(d.Refused, msg=field):
                d.validate_request(self.request, self.api)
            self.responses[path][field] = old

    def test_expired_or_duplicate_artifact_rejected(self):
        artifacts = self.responses['/actions/runs/12/artifacts']['artifacts']
        artifacts[0]['expired'] = True
        with self.assertRaises(d.Refused):d.validate_request(self.request, self.api)
        artifacts[0]['expired'] = False
        artifacts.append(deepcopy(artifacts[0]))
        with self.assertRaises(d.Refused):d.validate_request(self.request, self.api)

    def test_delayed_deployment_status_requires_eventual_running_status(self):
        pending = dict(self.responses['/actions/runs/11'], status='queued')
        with patch.object(d.time, 'sleep') as sleep:
            reads = iter([pending, self.responses['/actions/runs/11']])
            def api(path):
                return next(reads) if path == '/actions/runs/11' else self.api(path)
            self.assertEqual(d.validate_request(self.request, api, status_attempts=2), 99)
            sleep.assert_called_once_with(10)
        self.responses['/actions/runs/11'] = pending
        with patch.object(d.time, 'sleep'), self.assertRaisesRegex(d.Refused, 'Timed out'):
            d.validate_request(self.request, self.api, status_attempts=2)
        # A pending job with the wrong identity is never retried or authorized.
        pending['head_sha'] = 'b' * 40
        with patch.object(d.time, 'sleep') as sleep, self.assertRaises(d.Refused):
            d.validate_request(self.request, self.api)
        sleep.assert_not_called()

    def test_completed_or_cancelled_deployment_is_rejected_without_waiting(self):
        for status in ['completed', 'cancelled']:
            self.responses['/actions/runs/11']['status'] = status
            with patch.object(d.time, 'sleep') as sleep, self.assertRaises(d.Refused):
                d.validate_request(self.request, self.api)
            sleep.assert_not_called()

    def test_github_transient_errors_retry_but_auth_errors_fail_closed(self):
        client = d.GitHub('private-token')
        response = io.BytesIO(b'{"ok":true}')
        error = urllib.error.HTTPError('https://api.github.com', 502, 'Bad Gateway', {}, None)
        with patch.object(client.opener, 'open', side_effect=[error, response]) as opening, patch.object(d.time, 'sleep') as sleep:
            self.assertEqual(client.api('/commits/main'), {'ok': True})
            self.assertEqual(opening.call_count, 2)
            sleep.assert_called_once_with(2)
        for code, expected in [(401, 1), (403, 1), (404, 1), (503, 4)]:
            with patch.object(client.opener, 'open', side_effect=lambda *a, **k: (_ for _ in ()).throw(
                    urllib.error.HTTPError('https://api.github.com', code, 'secret-url', {}, None))) as opening, patch.object(d.time, 'sleep'):
                with self.assertRaises(d.Refused) as caught:client.api('/commits/main')
                self.assertEqual(opening.call_count, expected)
                self.assertNotIn('private-token', str(caught.exception))
                self.assertNotIn('secret-url', str(caught.exception))

    def test_arbitrary_arguments_and_paths_rejected(self):
        for field, value in [('run_id', '../other'), ('sha', '--help')]:
            request = dict(self.request, **{field: value})
            with self.assertRaises(d.Refused):d.validate_request(request, self.api)
        for path in ['../.env', '/etc/passwd', 'static/../../.ssh/key', '.env', 'docker-compose.yml', 'static\\x', './server.py']:
            self.assertFalse(d.safe_name(path), path)
        for path in ['server.py', 'static/night.css', 'static/assets/pieces/dice-1.webp', '.dockerignore']:
            self.assertTrue(d.safe_name(path), path)

    def test_cross_host_redirect_does_not_forward_job_token(self):
        req = urllib.request.Request('https://api.github.com/repos/a/b', headers={'Authorization': 'Bearer secret'})
        redirected = d.SafeRedirect().redirect_request(req, None, 302, '', {}, 'https://storage.example/file')
        self.assertIsNone(redirected.get_header('Authorization'))
        with self.assertRaises(d.Refused):d.SafeRedirect().redirect_request(req, None, 302, '', {}, 'http://storage.example/file')

    def bundle(self, root, malicious=False):
        source = {'server.py': b'server', 'online.py': b'online', 'static/index.html': b'index'}
        with tarfile.open(root / 'source.tar.gz', 'w:gz') as archive:
            for name, value in {**source, 'Dockerfile': b'FROM test', '.dockerignore': b'**'}.items():
                member = tarfile.TarInfo(name);member.size = len(value);archive.addfile(member, io.BytesIO(value))
            if malicious:
                member = tarfile.TarInfo('static/escape');member.type = tarfile.SYMTYPE;member.linkname = '/etc/passwd';archive.addfile(member)
        (root / 'image.tar.gz').write_bytes(b'test image')
        release = {'schema': 1, 'sha': SHA, 'image_id': 'sha256:' + 'b' * 64,
            'source_hashes': {n: d.hashlib.sha256(v).hexdigest() for n, v in source.items()},
            'files': {n: d.digest(root / n) for n in ['source.tar.gz', 'image.tar.gz']}}
        (root / 'release.json').write_text(json.dumps(release))
        return release

    def test_loaded_image_identity_across_docker_storage_backends(self):
        release = {'sha': SHA, 'image_id': 'sha256:'+'b'*64}
        info = {'Id': 'sha256:'+'c'*64, 'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Labels': {'org.opencontainers.image.revision': SHA}}}
        with patch.object(d, 'run', return_value=SimpleNamespace(stdout=json.dumps(info))):
            d.resolve_loaded_image(release)
        self.assertEqual(release['build_image_id'], 'sha256:'+'b'*64)
        self.assertEqual(release['image_id'], 'sha256:'+'c'*64)
        info['Config']['Labels']['org.opencontainers.image.revision'] = 'f'*40
        with patch.object(d, 'run', return_value=SimpleNamespace(stdout=json.dumps(info))):
            with self.assertRaises(d.Refused):d.resolve_loaded_image(release)

    def test_archive_manifest_and_symlink_validation(self):
        for malicious in [False, True]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp);self.bundle(root, malicious)
                if malicious:
                    with self.assertRaises(d.Refused):d.unpack_release(root, SHA)
                else:
                    release, source = d.unpack_release(root, SHA)
                    self.assertEqual((source / 'server.py').read_bytes(), b'server')
                    self.assertEqual(release['sha'], SHA)

    def test_modified_image_is_rejected_before_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);self.bundle(root);(root / 'image.tar.gz').write_bytes(b'changed')
            with self.assertRaises(d.Refused):d.unpack_release(root, SHA)

    def test_failed_cutover_restores_image_and_source_without_restoring_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);bundle = root / 'bundle';bundle.mkdir();self.bundle(bundle)
            zipped = io.BytesIO()
            with zipfile.ZipFile(zipped, 'w') as archive:
                for name in ['release.json', 'image.tar.gz', 'source.tar.gz']:archive.write(bundle / name, name)
            production = root / 'production';production.mkdir();(production / 'server.py').write_text('old')
            saved = root / 'saved';saved.mkdir()
            with tarfile.open(saved / 'source.tar.gz', 'w:gz') as archive:archive.add(production / 'server.py', 'server.py')
            (production / 'poker.sqlite3').write_bytes(b'latest live transactions')
            commands = []
            def command(args, **kwargs):
                commands.append(args)
                value = json.dumps({'Id': 'sha256:'+'b'*64, 'Os': 'linux', 'Architecture': 'amd64', 'Config': {'Labels': {'org.opencontainers.image.revision': SHA}}}) if 'image' in args and 'inspect' in args else json.dumps({'users': 2, 'poker_hands': 3, 'poker_operations': 4})
                return SimpleNamespace(stdout=value, returncode=0)
            github = SimpleNamespace(api=self.api, open=lambda _: io.BytesIO(zipped.getvalue()))
            with patch.object(d, 'ROOT', production), patch.object(d, 'STATE', root / 'state'), \
                 patch.object(d, 'run', side_effect=command), patch.object(d, 'smoke_image'), patch.object(d, 'drain'), \
                 patch.object(d, 'backup', return_value=(saved, 'old-image')), \
                 patch.object(d, 'compose_up', side_effect=[d.Refused('health failed'), None]):
                with self.assertRaises(d.Refused):d.deploy(self.request, github)
            self.assertIn(['docker', 'tag', 'old-image', 'boyband-poker:local'], commands)
            self.assertEqual((production / 'server.py').read_text(), 'old')
            self.assertEqual((production / 'poker.sqlite3').read_bytes(), b'latest live transactions')


class DrainDatabase(unittest.TestCase):
    def test_database_backstop_blocks_new_hands_but_allows_settlement_and_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'test.sqlite3')
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript('CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE poker_rooms(id INTEGER PRIMARY KEY,status TEXT,state TEXT);')
                db.execute('INSERT INTO poker_rooms VALUES(1,?,?)', ('playing', '{"hand_no":1}'))
            with redirect_stdout(io.StringIO()):exec(d.drain_code(db_path=path), {})
            with closing(sqlite3.connect(path)) as db, db:
                with self.assertRaises(sqlite3.IntegrityError):db.execute("INSERT INTO poker_rooms VALUES(2,'waiting','{}')")
                db.execute("UPDATE poker_rooms SET status='waiting' WHERE id=1")
                with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE poker_rooms SET state='{\"hand_no\":2}' WHERE id=1")
                db.execute("UPDATE settings SET value='0'")
                db.execute("UPDATE poker_rooms SET status='playing',state='{\"hand_no\":2}' WHERE id=1")
            exec(d.drain_code(clear=True, db_path=path), {})
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0], 0)


class DrainGame(unittest.TestCase):
    setUp = fixtures.WalletRules.setUp

    def call(self, path, data, uid=1, at=1):
        return online.mutate(self.db, path, data, self.users[uid-1], self.clock+at)

    def pause(self):
        self.db.execute("INSERT INTO settings VALUES('deploy_pause_until',?)", (str(self.clock+120),))

    def test_create_blocked_without_wallet_change_and_expiry_resumes(self):
        before = self.db.execute('SELECT sum(balance) FROM wallets').fetchone()[0]
        self.pause()
        with self.assertRaisesRegex(poker.RuleError, '系統準備更新'):self.call('/api/online/rooms', {})
        self.assertEqual(self.db.execute('SELECT sum(balance) FROM wallets').fetchone()[0], before)
        self.assertIn('id', self.call('/api/online/rooms', {}, at=121))

    def test_shared_dice_accepts_existing_round_bets_while_paused(self):
        rid = self.call('/api/online/rooms', {'game_type': 'dice'})['id'];path = '/api/online/rooms/' + str(rid)
        self.call(path+'/join', {'operation_id': 'deploy_dice_join_000001'}, uid=2)
        self.call(path+'/start', {'operation_id': 'deploy_dice_start_00001', 'expected_hand_number': 1, 'bets': [{'key': 'big', 'amount': 20}]}, at=2)
        self.pause()
        request = {'operation_id': 'deploy_dice_second_0001', 'expected_hand_number': 1, 'bets': [{'key': 'small', 'amount': 30}]}
        self.call(path+'/start', request, uid=2, at=3)
        room = online.get_room(self.db, rid)
        self.assertEqual(room['hand_no'], 1);self.assertEqual(room['status'], 'waiting')
        balances = [seat['stack'] for seat in room['seats']]
        self.assertTrue(self.call(path+'/start', request, uid=2, at=4)['replayed'])
        self.assertEqual([seat['stack'] for seat in online.get_room(self.db, rid)['seats']], balances)

    def test_running_hand_and_duplicate_operation_continue_during_drain(self):
        operation = {'operation_id': 'deploy_room_create_0001', 'game_type': 'inbetween'}
        rid = self.call('/api/online/rooms', operation)['id'];path = '/api/online/rooms/' + str(rid)
        self.call(path+'/start', {'operation_id': 'deploy_start_hand_00001'}, at=2)
        room = online.get_room(self.db, rid);self.pause()
        self.assertTrue(self.call('/api/online/rooms', operation, at=3)['replayed'])
        self.call(path+'/action', {'action': 'skip', 'hand_id': room['hand']['id'], 'turn_id': room['hand']['turn_id'], 'operation_id': 'deploy_skip_hand_000001'}, at=3)
        self.assertEqual(online.get_room(self.db, rid)['status'], 'waiting')
        stacks = [s['stack'] for s in online.get_room(self.db, rid)['seats']]
        with self.assertRaisesRegex(poker.RuleError, '系統準備更新'):self.call(path+'/start', {'operation_id': 'deploy_next_hand_000001'}, at=4)
        self.assertEqual([s['stack'] for s in online.get_room(self.db, rid)['seats']], stacks)


if __name__ == '__main__':unittest.main()
