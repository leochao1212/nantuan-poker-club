"""Boot the production image with an isolated, memory-only database in CI."""
from pathlib import Path
import subprocess
import time
import uuid


def main():
    root=Path(__file__).resolve().parents[1]
    name='nantuan-smoke-'+uuid.uuid4().hex[:12]
    image=name+':test'
    subprocess.run(['docker','build','-t',image,'.'],cwd=root,check=True)
    probe='''import json,os,sqlite3,urllib.request,urllib.error
from pathlib import Path
assert os.geteuid()==10001
with urllib.request.urlopen('http://127.0.0.1:8765/api/bootstrap',timeout=2) as r:
    assert json.load(r)['capacity']==6
assert Path('/app/schema_migrations.py').is_file() and Path('/app/static/market-chart.js').is_file()
assert all(Path('/app/'+name+'.py').is_file() for name in ('market_catalog','market_contracts','market_charts','market_review'))
assert Path('/app/market.py').is_file() and Path('/app/market_data.py').is_file() and Path('/app/static/market.js').is_file()
assert Path('/app/bank.py').is_file() and Path('/app/static/bank.js').is_file()
assert all(Path('/app/'+name+'.py').is_file() for name in ('battle','battle_engine'))
assert all(Path('/app/static/'+name+'.js').is_file() for name in ('battle','battle-scene','battle-motion','three.module','three.core'))
with sqlite3.connect('file:/data/poker.sqlite3?mode=ro',uri=True) as db:
    assert db.execute('SELECT count(*) FROM market_shorts').fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM market_orders').fetchone()[0]==0
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert db.execute('SELECT deposit_bps,loan_bps,loan_limit,loan_days FROM bank_settings WHERE id=1').fetchone()==(50,150,3000,7)
for route in ('bank','battle'):
    try:urllib.request.urlopen('http://127.0.0.1:8765/api/'+route,timeout=2)
    except urllib.error.HTTPError as e:assert e.code==401
    else:raise AssertionError(route+' must require authentication')
'''
    try:
        subprocess.run(['docker','run','--detach','--name',name,'--network','none','--read-only',
                        '--tmpfs','/data:rw,noexec,nosuid,size=32m,uid=10001,gid=10001',image],check=True)
        deadline=time.monotonic()+30
        while True:
            result=subprocess.run(['docker','exec',name,'python','-c',probe],capture_output=True,text=True,timeout=10)
            if result.returncode==0:break
            if time.monotonic()>=deadline:raise RuntimeError('Isolated container smoke failed: '+result.stderr)
            time.sleep(.5)
        print('Production container: non-root startup, memory-only database, bank/battle modules and private APIs OK')
    finally:
        subprocess.run(['docker','rm','--force',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,check=False)


if __name__=='__main__':main()
