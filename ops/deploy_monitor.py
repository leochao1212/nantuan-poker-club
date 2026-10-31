"""One deployment dispatch, resumable quiet monitoring, then mandatory data audit.

Uses existing gh authentication and SSH configuration; never accepts/stores tokens.
This is a local operator tool, not a replacement for the trusted host gateway.
"""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPO = 'leochao1212/nantuan-poker-club'
HOST = 'leoserver@100.99.220.15'
PUBLIC = 'https://poker.leoapi.dpdns.org'
OUT = ROOT / '.qa' / 'deploy-monitor'


class Failed(RuntimeError):
    pass


def command(args, *, data=None, timeout=60, check=True):
    result = subprocess.run(args, input=data, capture_output=True, cwd=ROOT, timeout=timeout)
    if check and result.returncode:
        # Do not echo command output: third-party errors can include signed URLs.
        raise Failed(args[0] + ' failed (exit ' + str(result.returncode) + ')')
    return result


def api(path):
    return json.loads(command(['gh', 'api', '-H', 'Cache-Control: no-cache',
                              'repos/' + REPO + path]).stdout)


def ssh(code, remote='python3 -', timeout=60, check=True):
    return command(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', HOST, remote],
                   data=code.encode('utf-8'), timeout=timeout, check=check)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def identity(run, sha):
    if not (run['path'] == '.github/workflows/deploy.yml' and run['event'] == 'workflow_dispatch'
            and run['head_branch'] == 'main' and run['head_sha'] == sha):
        raise Failed('Deployment workflow or commit does not match')


def server_state(run_id):
    # Only this validated numeric ID is interpolated into the read-only remote code.
    code = '''import json,subprocess
from pathlib import Path
run_id=RUN_ID
p=Path('/home/leoserver/.local/state/nantuan-deploy')/('run-'+run_id+'.json')
result={'receipt':None}
if p.exists():
 r=json.loads(p.read_text()); result['receipt']=r
 expected=Path('/home/leoserver/backups/boyband-poker')/('ci-'+run_id)
 result['backup_ok']=r.get('backup')==str(expected) and all((expected/n).is_file() and (expected/n).stat().st_size>0 for n in ('source.tar.gz','production.sqlite3'))
 info=json.loads(subprocess.check_output(['docker','inspect','boyband-poker']))[0]
 result['image']=info['Image'];result['health']=info['State'].get('Health',{}).get('Status')
print(json.dumps(result))
'''.replace('RUN_ID', repr(run_id))
    return json.loads(ssh(code).stdout)


def verify_receipt(state, sha):
    receipt = state['receipt']
    if receipt['sha'] != sha or state['image'] != receipt['image']:
        raise Failed('Receipt or current container version mismatch; may have been superseded')
    if not state['backup_ok'] or state['health'] != 'healthy':
        raise Failed('Backup missing or production container unhealthy')


class Assets(HTMLParser):
    def __init__(self):
        super().__init__(); self.paths = {'/'}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        url = attrs.get('src') if tag == 'script' else attrs.get('href') if tag == 'link' else None
        if url:
            path = url.split('?', 1)[0]
            if re.fullmatch(r'/[A-Za-z0-9_.-]+\.(?:js|css)', path):
                self.paths.add(path)


def public_check(sha):
    git = ['git', 'show', sha + ':static/index.html']
    result = command(git, check=False)
    if result.returncode:
        command(['git', 'fetch', '--no-tags', 'https://github.com/' + REPO + '.git', sha], timeout=120)
        result = command(git)
    parser = Assets(); parser.feed(result.stdout.decode('utf-8'))
    curl = 'curl.exe' if sys.platform == 'win32' else 'curl'
    for path in sorted(parser.paths):
        source = 'static/index.html' if path == '/' else 'static' + path
        expected = command(['git', 'show', sha + ':' + source]).stdout
        actual = command([curl, '-fsS', '--retry', '2', '--max-time', '20',
                          PUBLIC + path + '?release=' + sha], timeout=90).stdout
        if hashlib.sha256(expected).digest() != hashlib.sha256(actual).digest():
            raise Failed('Public asset mismatch: ' + path)
    return {'passed': True, 'files': len(parser.paths)}


def finish(run_id, sha, state):
    verify_receipt(state, sha)
    result = ssh((ROOT / 'ops/audit_deployment.py').read_text(encoding='utf-8'),
                 'docker exec -e SQLITE_TMPDIR=/data/backups -i boyband-poker python - ' + run_id,
                 timeout=180, check=False)
    audit = json.loads(result.stdout)
    save(OUT / (run_id + '-audit.json'), audit)
    if result.returncode or not audit['passed']:
        raise Failed('Production data audit failed')
    public = public_check(sha)
    # Detect a replacement deployment that happened during verification.
    verify_receipt(server_state(run_id), sha)
    return dict(status='success', run_id=run_id, sha=sha, backup=state['receipt']['backup'],
                health='healthy', data=audit, public=public)


def monitor(run_id, sha, interval, timeout):
    report = OUT / (run_id + '.json'); start = time.monotonic(); previous = None
    transient = 0
    while time.monotonic() - start < timeout:
        try:
            run = api('/actions/runs/' + run_id); identity(run, sha)
            state = server_state(run_id)
            if state['receipt']:
                print('Verifying backup, production data and public assets...', flush=True)
                result = finish(run_id, sha, state)
                save(report, result)
                print(json.dumps({k: result[k] for k in ('status','run_id','sha','backup','health')}) +
                      '\nData/public checks passed. Report: ' + str(report), flush=True)
                return 0
            if run['status'] == 'completed':
                raise Failed('Workflow ended without a verified deployment receipt: ' + str(run['conclusion']))
            jobs = api('/actions/runs/' + run_id + '/jobs')['jobs']
            phase = next((j['name'] for j in jobs if j['status'] == 'in_progress'), run['status'])
            snapshot = dict(status='running', phase=phase, run_id=run_id, sha=sha,
                            elapsed_seconds=int(time.monotonic()-start), checked_at=time.time())
            save(report, snapshot)
            if phase != previous:
                print('Deployment phase: ' + phase, flush=True); previous = phase
            transient = 0
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            transient += 1
            if transient >= 4:raise Failed('Monitoring unavailable after 4 attempts; resume the same run') from error
        except Failed as error:
            if ' failed (exit ' not in str(error):raise
            transient += 1
            if transient >= 4:raise
        time.sleep(interval)
    raise Failed('Monitor timed out; deployment was not cancelled. Resume the same run')


def main(argv=None):
    # Windows legacy console encodings cannot represent every workspace path.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--start', action='store_true', help='Dispatch main exactly once, then monitor')
    mode.add_argument('--run-id', help='Monitor/audit an existing deployment without dispatching')
    mode.add_argument('--resume', action='store_true', help='Resume the last locally recorded run')
    parser.add_argument('--interval', type=int, default=30)
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args(argv)
    if not 5 <= args.interval <= 60 or args.timeout < 1:parser.error('interval must be 5–60 seconds; timeout positive')
    run_id = None
    try:
        if args.start:
            checkpoint = OUT/'latest.json'
            if checkpoint.exists():
                prior = json.loads(checkpoint.read_text(encoding='utf-8'))
                if 'run_id' not in prior:
                    raise Failed('Previous dispatch unconfirmed; locate its run before starting another deployment')
                prior_id = str(prior['run_id'])
                if not re.fullmatch(r'\d{1,20}', prior_id):raise Failed('Invalid saved run ID')
                if api('/actions/runs/'+prior_id)['status'] != 'completed':
                    raise Failed('Previous deployment still active; use --resume instead of dispatching again')
            sha = api('/commits/main')['sha']
            save(OUT/'latest.json',dict(status='dispatch_unconfirmed',sha=sha,started_at=time.time()))
            result = command(['gh','workflow','run','deploy.yml','--repo',REPO,'--ref','main'],check=False)
            if result.returncode:
                raise Failed('Dispatch outcome uncertain; inspect GitHub Actions and use --run-id. Do not dispatch again')
            # No blind retry after dispatch: a lost response can still have started a run.
            match = re.search(r'/actions/runs/(\d+)', (result.stdout+result.stderr).decode('utf-8'))
            if not match:raise Failed('Dispatch returned no run ID; inspect GitHub Actions and use --run-id. Do not dispatch again')
            run_id = match[1]
        elif args.resume:
            saved = json.loads((OUT / 'latest.json').read_text(encoding='utf-8'))
            if 'run_id' not in saved:
                raise Failed('Previous dispatch unconfirmed; inspect GitHub Actions and use --run-id. Do not dispatch again')
            run_id, sha = saved['run_id'], saved['sha']
        else:
            run_id = args.run_id
            if not re.fullmatch(r'\d{1,20}',run_id):raise Failed('Invalid numeric run ID')
            sha = api('/actions/runs/'+run_id)['head_sha']
        if not re.fullmatch(r'\d{1,20}',run_id) or not re.fullmatch(r'[0-9a-f]{40}',sha):raise Failed('Invalid run identity')
        save(OUT/'latest.json',dict(run_id=run_id,sha=sha))
        print('Monitoring https://github.com/'+REPO+'/actions/runs/'+run_id,flush=True)
        return monitor(run_id,sha,args.interval,args.timeout)
    except (Failed, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
        message = str(error) if isinstance(error, Failed) else type(error).__name__
        result = dict(status='failed',run_id=run_id,error=message)
        if run_id:save(OUT/(run_id+'.json'),result)
        print(json.dumps(result),flush=True)
        if run_id:print('Inspect only if needed: gh run view '+run_id+' --repo '+REPO+' --log-failed',flush=True)
        return 1
    except KeyboardInterrupt:
        print('Monitor stopped; deployment may continue. Use --resume or locate the run in GitHub Actions.',flush=True)
        return 130


if __name__ == '__main__':
    sys.exit(main())
