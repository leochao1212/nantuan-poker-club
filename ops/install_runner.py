"""Owner-run installer; read a one-hour runner registration token from stdin.

Run beside the reviewed deploy.py with sudo, never from a workflow checkout.
The installer only grants the exact no-argument deployment gateway command.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tarfile

USER = 'nantuan-ci'
RUNNER = Path('/opt/nantuan-runner')
GATEWAY = Path('/usr/local/lib/nantuan/deploy.py')


def run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Installer command failed: ' + args[0])
    return result.stdout


def install(request):
    assert os.geteuid() == 0, 'Run installer with sudo'
    version = request['version'];expected = request['digest'];token = request['token']
    assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)
    assert re.fullmatch(r'[0-9a-f]{64}', expected)
    archive = Path('/home/leoserver/.cache/nantuan-runner-' + version + '.tar.gz')
    with archive.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected, 'Runner archive checksum mismatch'
    try:account = pwd.getpwnam(USER)
    except KeyError:
        run(['useradd', '--system', '--create-home', '--home-dir', '/var/lib/nantuan-ci', '--shell', '/usr/sbin/nologin', USER])
        account = pwd.getpwnam(USER)
    assert 'docker' not in run(['id', '-nG', USER]).split(), 'Runner must not have Docker access'
    RUNNER.mkdir(mode=0o750, exist_ok=True)
    if not (RUNNER / '.runner').exists():
        with tarfile.open(archive) as bundle:bundle.extractall(RUNNER, filter='data')
        run(['chown', '-R', USER + ':' + USER, str(RUNNER)])
        run(['sudo', '-u', USER, './config.sh', '--unattended', '--url',
             'https://github.com/leochao1212/nantuan-poker-club', '--token', token,
             '--name', 'nantuan-deploy-leoserver', '--labels', 'nantuan-deploy',
             '--no-default-labels', '--work', '_work'], cwd=RUNNER)
    else:
        assert json.loads((RUNNER / '.runner').read_text())['gitHubUrl'].rstrip('/') == 'https://github.com/leochao1212/nantuan-poker-club'
    GATEWAY.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    pending_gateway = GATEWAY.with_suffix('.new')
    pending_gateway.write_bytes(Path(__file__).with_name('deploy.py').read_bytes().replace(b'\r\n', b'\n'))
    pending_gateway.chmod(0o755);os.chown(pending_gateway, 0, 0)
    pending_gateway.replace(GATEWAY)
    sudoers = Path('/etc/sudoers.d/nantuan-deploy')
    pending_sudoers = sudoers.with_name('.nantuan-deploy.new')
    pending_sudoers.write_text('Defaults:nantuan-ci env_reset, !setenv\nnantuan-ci ALL=(leoserver) NOPASSWD: /usr/local/lib/nantuan/deploy.py ""\n')
    pending_sudoers.chmod(0o440)
    run(['visudo', '-cf', str(pending_sudoers)])
    pending_sudoers.replace(sudoers)
    if not (RUNNER / '.service').exists():run(['./svc.sh', 'install', USER], cwd=RUNNER)
    service = (RUNNER / '.service').read_text().strip()
    dropin = Path('/etc/systemd/system') / (service + '.d')
    dropin.mkdir(parents=True, exist_ok=True)
    (dropin / 'isolation.conf').write_text('''[Service]
UMask=0077
PrivateTmp=yes
ProtectSystem=full
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictRealtime=yes
MemoryMax=384M
CPUQuota=50%
TasksMax=128
''')
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', service])
    print(json.dumps({'service': service, 'user': account.pw_name, 'gateway': str(GATEWAY)}))


if __name__ == '__main__':install(json.load(sys.stdin))
