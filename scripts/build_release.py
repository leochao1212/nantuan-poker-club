"""Build an immutable, data-free production bundle on a hosted CI runner."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(root, out, sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Expected a full commit SHA')
    out.mkdir(parents=True, exist_ok=True)
    image = 'nantuan-poker:' + sha
    subprocess.run(['docker', 'build', '--label', 'org.opencontainers.image.revision=' + sha,
                    '-t', image, '.'], cwd=root, check=True)
    image_id = subprocess.check_output(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], text=True).strip()
    subprocess.run(['docker', 'run', '--rm', '--network', 'none', image, 'python', '-c',
                    'import server,online,bonus_engine,arcade_engine,mahjong_engine; assert hasattr(online,"deployment_paused")'], check=True)
    files = sorted([p for p in root.glob('*.py') if not p.name.startswith('test_')] +
                   [p for p in (root / 'static').rglob('*') if p.is_file()])
    manifest = {p.relative_to(root).as_posix(): digest(p) for p in files}
    with tarfile.open(out / 'source.tar.gz', 'w:gz') as archive:
        for p in files + [root / 'Dockerfile', root / '.dockerignore']:
            archive.add(p, arcname=p.relative_to(root).as_posix(), recursive=False)
    with gzip.open(out / 'image.tar.gz', 'wb', compresslevel=1) as stream:
        with subprocess.Popen(['docker', 'image', 'save', image], stdout=subprocess.PIPE) as process:
            shutil.copyfileobj(process.stdout, stream)
            if process.wait():
                raise RuntimeError('Docker image export failed')
    release = {'schema': 1, 'sha': sha, 'image_id': image_id, 'source_hashes': manifest,
               'files': {n: digest(out / n) for n in ['source.tar.gz', 'image.tar.gz']}}
    (out / 'release.json').write_text(json.dumps(release, indent=2), encoding='utf-8')


if __name__ == '__main__':
    build(Path.cwd(), Path('artifacts/release'), os.environ['GITHUB_SHA'])
