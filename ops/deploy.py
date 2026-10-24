#!/usr/bin/python3 -I
"""Trusted deployment gateway. Install root-owned; never execute a PR's copy.

The unprivileged runner can invoke only this command as leoserver. The caller's
short-lived GITHUB_TOKEN is read from stdin, used in memory, and never saved.
"""
try:
    import fcntl
except ImportError:  # Policy tests also run on Windows.
    fcntl = None
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import threading
import urllib.request
from urllib.parse import urlsplit
import zipfile

REPO = 'leochao1212/nantuan-poker-club'
ROOT = Path('/home/leoserver/apps/boyband-poker')
STATE = Path('/home/leoserver/.local/state/nantuan-deploy')
CONTAINER = 'boyband-poker'
PUBLIC = 'https://poker.leoapi.dpdns.org'


class Refused(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Refused(message)


def run(args, *, data=None, check=True, timeout=180, cwd=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True,
                            timeout=timeout, cwd=cwd)
    if check and result.returncode:
        # Child output may contain signed artifact URLs. Do not echo it to CI.
        raise Refused('Command failed: ' + args[0])
    return result


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(newurl.startswith('https://'), 'Artifact redirect must use HTTPS')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urlsplit(req.full_url).netloc != urlsplit(newurl).netloc:
            redirected.remove_header('Authorization')
        return redirected


class GitHub:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(SafeRedirect())

    def open(self, path):
        require(path.startswith('/') and not path.startswith('//'), 'Invalid API path')
        request = urllib.request.Request('https://api.github.com/repos/' + REPO + path,
            headers={'Authorization': 'Bearer ' + self.token,
                     'Accept': 'application/vnd.github+json', 'User-Agent': 'nantuan-deploy'})
        return self.opener.open(request, timeout=60)

    def api(self, path):
        with self.open(path) as response:
            return json.load(response)


def validate_request(request, api):
    require(set(request) == {'token', 'run_id', 'ci_run_id', 'sha'}, 'Invalid request fields')
    for field in ['run_id', 'ci_run_id']:
        require(isinstance(request[field], str) and re.fullmatch(r'[0-9]{1,20}', request[field]), 'Invalid run ID')
    sha = request['sha']
    require(isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40}', sha), 'Expected full commit SHA')
    deploy = api('/actions/runs/' + request['run_id'])
    require(deploy['path'] == '.github/workflows/deploy.yml' and deploy['event'] == 'workflow_dispatch'
            and deploy['head_branch'] == 'main' and deploy['head_sha'] == sha
            and deploy['status'] == 'in_progress', 'Only a running manual main deployment is allowed')
    require(api('/commits/main')['sha'] == sha, 'main moved; start a new deployment')
    ci = api('/actions/runs/' + request['ci_run_id'])
    require(ci['path'] == '.github/workflows/ci.yml' and ci['head_branch'] == 'main'
            and ci['head_sha'] == sha and ci['event'] in ('push', 'workflow_dispatch')
            and ci['status'] == 'completed' and ci['conclusion'] == 'success', 'Checks/build must pass for this main commit')
    artifacts = api('/actions/runs/' + request['ci_run_id'] + '/artifacts')['artifacts']
    matches = [a for a in artifacts if a['name'] == 'release-' + sha and not a['expired']]
    require(len(matches) == 1, 'Expected one unexpired release artifact')
    return matches[0]['id']


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name and '\\' not in name and not path.is_absolute() and '..' not in path.parts
                and str(path) == name and (name.startswith('static/') or
                (len(path.parts) == 1 and (name.endswith('.py') or name in ('Dockerfile', '.dockerignore')))))


def unpack_release(folder, sha):
    release = json.loads((folder / 'release.json').read_text())
    require(release.get('schema') == 1 and release.get('sha') == sha, 'Release commit mismatch')
    require(re.fullmatch(r'sha256:[0-9a-f]{64}', release.get('image_id', '')), 'Invalid image ID')
    require(set(release['files']) == {'image.tar.gz', 'source.tar.gz'}, 'Invalid release files')
    for name, expected in release['files'].items():
        require(digest(folder / name) == expected, 'Release checksum mismatch')
    manifest = release['source_hashes']
    require(isinstance(manifest, dict) and 1 < len(manifest) <= 1000, 'Invalid source manifest')
    require(all(safe_name(n) and re.fullmatch(r'[0-9a-f]{64}', h) for n, h in manifest.items()), 'Invalid source paths')
    require({'online.py', 'server.py', 'static/index.html'} <= set(manifest), 'Incomplete source manifest')
    source = folder / 'source'
    source.mkdir()
    with tarfile.open(folder / 'source.tar.gz') as archive:
        members = archive.getmembers()
        require(len(members) <= 1002 and sum(m.size for m in members) <= 64 * 1024 * 1024, 'Source archive too large')
        require(all(m.isfile() and safe_name(m.name) for m in members), 'Unsafe source archive')
        require(len({m.name for m in members}) == len(members), 'Duplicate archive path')
        require({m.name for m in members} == set(manifest) | {'Dockerfile', '.dockerignore'}, 'Source file list mismatch')
        for member in members:
            target = source / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as src, open(target, 'wb') as dst:
                shutil.copyfileobj(src, dst)
    for name, expected in manifest.items():
        require(digest(source / name) == expected, 'Source checksum mismatch')
    return release, source


def image_check_code(release, database=False):
    code = '''import hashlib,json,urllib.request,urllib.error
from pathlib import Path
expected=EXPECTED
for name,value in expected.items():
    assert hashlib.sha256((Path('/app')/name).read_bytes()).hexdigest()==value,name
with urllib.request.urlopen('http://127.0.0.1:8765/api/bootstrap',timeout=3) as r:assert json.load(r)['capacity']==6
try:urllib.request.urlopen('http://127.0.0.1:8765/api/state',timeout=3)
except urllib.error.HTTPError as error:assert error.code==401
else:raise AssertionError('Private state exposed')
'''.replace('EXPECTED', repr(release['source_hashes']))
    if database:
        code += '''import sqlite3
with sqlite3.connect('file:/data/poker.sqlite3?mode=ro',uri=True) as d:
    assert d.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    counts={t:d.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['users','poker_hands','poker_operations']}
print(json.dumps(counts))
'''
    return code


def smoke_image(release, run_id):
    name = 'nantuan-candidate-' + run_id
    try:
        run(['docker', 'run', '-d', '--name', name, '--network', 'none', '--memory', '256m', '--cpus', '0.5',
             '--read-only', '--tmpfs', '/data:rw,uid=10001,gid=10001,mode=0700,size=64m', release['image_id']])
        for _ in range(30):
            result = run(['docker', 'exec', '-i', name, 'python'], data=image_check_code(release), check=False)
            if result.returncode == 0:
                return
            time.sleep(1)
        raise Refused('Candidate image failed its isolated smoke check')
    finally:
        run(['docker', 'rm', '-f', name], check=False)


def drain_code(clear=False, db_path="/data/poker.sqlite3"):
    return _drain_code(clear).replace("'/data/poker.sqlite3'", repr(db_path))


def _drain_code(clear=False):
    if clear:
        return """import sqlite3
d=sqlite3.connect('/data/poker.sqlite3',timeout=15)
d.executescript("BEGIN IMMEDIATE; DELETE FROM settings WHERE key='deploy_pause_until'; DROP TRIGGER IF EXISTS deploy_block_new_room; DROP TRIGGER IF EXISTS deploy_block_new_hand; COMMIT;")
d.close()
"""
    return '''import sqlite3,time,json
d=sqlite3.connect('/data/poker.sqlite3',timeout=15)
d.executescript("""
CREATE TRIGGER IF NOT EXISTS deploy_block_new_room BEFORE INSERT ON poker_rooms
WHEN unixepoch('now') < CAST((SELECT value FROM settings WHERE key='deploy_pause_until') AS REAL)
BEGIN SELECT RAISE(ABORT,'Deployment in progress; retry shortly'); END;
CREATE TRIGGER IF NOT EXISTS deploy_block_new_hand BEFORE UPDATE ON poker_rooms
WHEN unixepoch('now') < CAST((SELECT value FROM settings WHERE key='deploy_pause_until') AS REAL)
AND ((OLD.status='waiting' AND NEW.status='playing') OR COALESCE(json_extract(NEW.state,'$.hand_no'),0)>COALESCE(json_extract(OLD.state,'$.hand_no'),0))
BEGIN SELECT RAISE(ABORT,'Deployment in progress; retry shortly'); END;
""")
d.execute('BEGIN IMMEDIATE')
d.execute("INSERT INTO settings(key,value) VALUES('deploy_pause_until',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(time.time()+120),))
active=d.execute("SELECT count(*) FROM poker_rooms WHERE status='playing'").fetchone()[0]
d.commit();d.close();print(json.dumps({'active':active}))
'''


def drain():
    for _ in range(120):
        result = run(['docker', 'exec', '-i', CONTAINER, 'python'], data=drain_code())
        count = json.loads(result.stdout)['active']
        if count == 0:
            return
        print('Waiting for active hands: ' + str(count), flush=True)
        time.sleep(5)
    raise Refused('Hands did not finish within 10 minutes; deployment cancelled')


def backup(run_id):
    folder = Path('/home/leoserver/backups/boyband-poker') / ('ci-' + run_id)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    image = run(['docker', 'inspect', '--format', '{{.Image}}', CONTAINER]).stdout.strip()
    run(['docker', 'tag', image, 'boyband-poker:rollback-' + run_id])
    with tarfile.open(folder / 'source.tar.gz', 'w:gz') as archive:
        for path in [*ROOT.glob('*.py'), ROOT / 'static', *[ROOT / n for n in
                      ['Dockerfile', '.dockerignore', 'docker-compose.yml', 'compose.yml', 'compose.yaml', '.env']]]:
            if path.exists():
                archive.add(path, arcname=path.relative_to(ROOT).as_posix())
    destination = '/data/backups/ci-' + run_id + '.sqlite3'
    code = "import sqlite3,pathlib; pathlib.Path('/data/backups').mkdir(exist_ok=True); a=sqlite3.connect('/data/poker.sqlite3'); b=sqlite3.connect(" + repr(destination) + "); a.backup(b); b.close(); a.close()"
    run(['docker', 'exec', '-i', CONTAINER, 'python'], data=code)
    run(['docker', 'cp', CONTAINER + ':' + destination, str(folder / 'production.sqlite3')])
    return folder, image


def compose_up():
    run(['docker', 'compose', 'up', '-d', '--no-build', '--wait', '--wait-timeout', '120'], cwd=ROOT)


def public_check(release, folder):
    for name in ['static/index.html', 'static/night.css']:
        target = folder / ('public-' + Path(name).name)
        path = '/' if name.endswith('index.html') else '/' + name.removeprefix('static/')
        run(['curl', '--fail', '--silent', '--show-error', '--compressed', '--retry', '2', '--max-time', '20',
             '-o', str(target), PUBLIC + path + '?release=' + release['sha']])
        require(digest(target) == release['source_hashes'][name], 'Public endpoint is not serving the selected release')


def deploy(request, github):
    artifact_id = validate_request(request, github.api)
    STATE.mkdir(parents=True, mode=0o700, exist_ok=True)
    receipt = STATE / ('run-' + request['run_id'] + '.json')
    if receipt.exists():
        require(json.loads(receipt.read_text())['sha'] == request['sha'], 'Receipt mismatch')
        print('This deployment already completed successfully')
        return
    with tempfile.TemporaryDirectory(prefix='release-', dir=STATE) as tmp:
        folder = Path(tmp)
        with github.open('/actions/artifacts/' + str(artifact_id) + '/zip') as src, open(folder / 'artifact.zip', 'wb') as dst:
            size = 0
            while chunk := src.read(1024 * 1024):
                size += len(chunk)
                require(size <= 300 * 1024 * 1024, 'Release artifact too large')
                dst.write(chunk)
        with zipfile.ZipFile(folder / 'artifact.zip') as archive:
            names = archive.namelist()
            require(len(names) == 3 and set(names) == {'release.json', 'image.tar.gz', 'source.tar.gz'}, 'Unexpected artifact files')
            require(sum(x.file_size for x in archive.infolist()) <= 300 * 1024 * 1024, 'Expanded artifact too large')
            archive.extractall(folder)
        release, source = unpack_release(folder, request['sha'])
        run(['docker', 'load', '-i', str(folder / 'image.tar.gz')], timeout=300)
        labels = json.loads(run(['docker', 'image', 'inspect', '--format', '{{json .Config.Labels}}', release['image_id']]).stdout)
        require(labels.get('org.opencontainers.image.revision') == request['sha'], 'Image revision mismatch')
        smoke_image(release, request['run_id'])
        print('Verified image; waiting for current hands to finish', flush=True)
        previous = None
        switching = False
        stop = threading.Event()
        def renew():
            while not stop.wait(20):
                try:
                    run(['docker', 'exec', '-i', CONTAINER, 'python'], data=drain_code(), check=False, timeout=20)
                except Exception:
                    pass  # Container recreation can briefly make exec unavailable.
        keeper = threading.Thread(target=renew, daemon=True)
        keeper.start()
        try:
            drain()
            require(github.api('/commits/main')['sha'] == request['sha'], 'main moved while draining')
            baseline = json.loads(run(['docker', 'exec', '-i', CONTAINER, 'python'],
                data="import sqlite3,json; d=sqlite3.connect('/data/poker.sqlite3'); print(json.dumps({t:d.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['users','poker_hands','poker_operations']}))").stdout)
            saved, previous = backup(request['run_id'])
            switching = True
            for path in source.rglob('*'):
                if path.is_file():
                    target = ROOT / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
            switching = True
            run(['docker', 'tag', release['image_id'], 'boyband-poker:local'])
            compose_up()
            counts = json.loads(run(['docker', 'exec', '-i', CONTAINER, 'python'], data=image_check_code(release, True)).stdout)
            require(all(counts[t] >= value for t, value in baseline.items()), 'Persistent records disappeared')
            public_check(release, folder)
            receipt.write_text(json.dumps({'sha': request['sha'], 'image': release['image_id'], 'backup': str(saved),
                                           'previous_image': previous, 'counts': counts, 'at': time.time()}, indent=2))
            print('Deployment healthy: ' + request['sha'], flush=True)
        except BaseException:
            if switching and previous:
                print('Verification failed; restoring the previous image, preserving the current database', flush=True)
                run(['docker', 'tag', previous, 'boyband-poker:local'])
                with tarfile.open(saved / 'source.tar.gz') as archive:
                    archive.extractall(ROOT, filter='data')
                compose_up()
            raise
        finally:
            stop.set(); keeper.join(25)
            run(['docker', 'exec', '-i', CONTAINER, 'python'], data=drain_code(clear=True), check=False)


def main():
    require(fcntl is not None, 'Deployment requires Linux')
    require(len(sys.argv) == 1, 'No command-line arguments allowed')
    request = json.loads(sys.stdin.read(16385))
    token = request.get('token')
    require(isinstance(token, str) and 20 <= len(token) <= 4096 and '\n' not in token, 'Missing job token')
    STATE.mkdir(parents=True, mode=0o700, exist_ok=True)
    with open(STATE / 'deploy.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(Refused('Deployment cancelled')))
        deploy(request, GitHub(token))


if __name__ == '__main__':
    try:
        main()
    except Refused as error:
        print('Deployment refused: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print('Deployment failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
