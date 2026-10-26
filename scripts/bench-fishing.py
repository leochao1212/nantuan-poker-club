"""Optional isolated 20-player / 40-SSE benchmark; run from the repository root.
Set FISH_FAST=1 for the faster cannon. Never connects to production.
"""
import sys,os,json,time,threading,sqlite3,statistics,urllib.request,ctypes
FAST=os.environ.get("FISH_FAST")=="1"
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from tests.python.test_app import ServerTestCase,Client
class Bench(ServerTestCase):pass
Path('artifacts/fishing-gameplay').mkdir(parents=True,exist_ok=True)
Bench.setUpClass();stop=threading.Event();streams=[];threads=[]
try:
 if os.name=='nt':
  k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.restype=ctypes.c_void_p;k.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];h=k.OpenProcess(0x0600,False,Bench.proc.pid);a=ctypes.c_size_t();b=ctypes.c_size_t();k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)];k.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];assert k.GetProcessAffinityMask(h,ctypes.byref(a),ctypes.byref(b));assert k.SetProcessAffinityMask(h,a.value&-a.value);k.CloseHandle.argtypes=[ctypes.c_void_p];k.CloseHandle(h)
 elif hasattr(os,'sched_setaffinity'):os.sched_setaffinity(Bench.proc.pid,{min(os.sched_getaffinity(Bench.proc.pid))})
 people=[];invite=None
 for i in range(20):
  c=Client(Bench.base);s,r=c.call('/api/register',dict(username='load_'+str(i),nickname='Load'+str(i),password='SyntheticLoad123',invite_code=invite));assert s==200,(s,r);invite=invite or c.call('/api/state')[1]['invite_code'];people.append(c)
  assert c.call('/api/fishing/join',dict(gameplay_version=3,operation_id='load_join_'+str(i).zfill(12),room_id=i//6+1))[0]==200
 def listen(c,path):
  try:
   req=urllib.request.Request(c.base+path,headers={'X-Requested-With':'PokerClub'});r=c.opener.open(req,timeout=15);streams.append(r)
   while not stop.is_set():r.readline()
  except (OSError,ValueError):pass
 for i,c in enumerate(people):
  for path in ('/api/fishing/events?room='+str(i//6+1)+'&client=fish_load_'+str(i).zfill(12),'/api/online/events?presence=client&client=lobby_load_'+str(i).zfill(12)):
   t=threading.Thread(target=listen,args=(c,path),daemon=True);t.start();threads.append(t)
 time.sleep(1)
 start=time.monotonic();barrier=threading.Barrier(20);latency=[];failed=[]
 def play(pair):
  i,c=pair;barrier.wait()
  previous=0
  for j in range(20):
   target=max(start+j*(.40 if FAST else .56)+i*.003,previous+(.38 if FAST else .51))
   wait=target-time.monotonic()
   if wait>0:time.sleep(wait)
   previous=time.monotonic();clock=time.time();shots=[dict(token='load_token_'+str(i).zfill(3)+'_'+str(j).zfill(6)+'_'+str(n),fired_at=clock-(1-n)*(.18 if FAST else .25),x=200+i*30,y=180+j%5*35) for n in range(2)]
   body=dict(gameplay_version=3,operation_id='load_burst_'+str(i).zfill(3)+'_'+str(j).zfill(8),room_id=i//6+1,cannon=1 if FAST else 0,stake=1,shots=shots,expected_revision=1,expected_limit_revision=1)
   at=time.monotonic();status,result=c.call('/api/fishing/burst',body);latency.append((time.monotonic()-at)*1000)
   if status!=200:failed.append([i,j,status,result])
 with ThreadPoolExecutor(20) as pool:list(pool.map(play,enumerate(people)))
 time.sleep(1.5)
 from contextlib import closing
 with closing(sqlite3.connect(Bench.db_path)) as db:
  totals=db.execute('SELECT sum(shots),sum(spent),sum(returned) FROM fishing_stats').fetchone();ledger=db.execute("SELECT -sum(amount) FROM wallet_ledger WHERE kind='fishing_shot'").fetchone()[0];active=db.execute("SELECT count(*) FROM fishing_projectiles WHERE state='flying'").fetchone()[0]
 latency.sort();result=dict(cpu_affinity='one core',players=20,sse_connections=len(streams),batches=len(latency),expected_shots=800,totals=totals,ledger_debits=ledger,unsettled=active,failed=failed,p50_ms=round(statistics.median(latency),2),p95_ms=round(latency[int(len(latency)*.95)],2),max_ms=round(max(latency),2),elapsed=round(time.monotonic()-start,2))
 Path('artifacts/fishing-gameplay/load-fast.json' if FAST else 'artifacts/fishing-gameplay/load.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result));assert not failed;assert totals[0]==800 and totals[1]==ledger==800 and not active
finally:
 stop.set();Bench.tearDownClass()
