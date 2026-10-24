"""Committed public model reuse, invalidation and table/lobby push isolation."""
from contextlib import contextmanager,closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json,sqlite3,tempfile,threading,time,unittest
from unittest.mock import patch
import online,rewards,wallet,member_accounts,social,view_cache,server
from . import test_club,test_connection_review
from .test_realtime import Stream

class PublicModels(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'views.sqlite3';self.db=sqlite3.connect(self.path);self.db.row_factory=sqlite3.Row;self.addCleanup(self.db.close)
  self.db.execute('PRAGMA journal_mode=WAL')
  self.db.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,nickname TEXT);CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);INSERT INTO settings VALUES('invite_code','TESTCODE');")
  self.db.executemany('INSERT INTO users VALUES(?,?,?)',[(i,f'u{i}',f'P{i}') for i in range(1,4)]);online.initialize(self.db)
  self.users=[{'id':i,'username':f'u{i}','nickname':f'P{i}'} for i in range(1,4)];self.clock=1792425600
  self.cache=view_cache.ViewCache();self.patch=patch.object(view_cache,'CACHE',self.cache);self.patch.start();self.addCleanup(self.patch.stop)
  self.db.commit()
 @contextmanager
 def reader(self):
  db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row
  try:
   db.execute('PRAGMA query_only=ON');db.execute('BEGIN');yield db
  finally:db.close()
 def lobby(self,uid=1):
  with self.reader() as db:return online.lobby(db,self.users[uid-1],self.clock,touch_presence=False)
 def test_cached_lobby_equals_uncached_and_reuses_aggregates(self):
  uncached=online.lobby(self.db,self.users[0],self.clock,touch_presence=False);queries=[]
  with self.reader() as db:
   db.set_trace_callback(queries.append);first=online.lobby(db,self.users[0],self.clock,touch_presence=False);cut=len(queries);second=online.lobby(db,self.users[0],self.clock,touch_presence=False)
  self.assertEqual(first,uncached);self.assertEqual(second,uncached)
  expensive=lambda xs:sum('GROUP BY' in q or 'SELECT h.public_state' in q for q in xs)
  self.assertGreater(expensive(queries[:cut]),0);self.assertEqual(expensive(queries[cut:]),0);self.assertGreater(self.cache.stats()['hits'],0)
 def test_settled_results_and_day_invalidate_progress_and_leaders(self):
  before=self.lobby();rid=online.mutate(self.db,'/api/online/rooms',{},self.users[0],self.clock)['id']
  hand={'board':[],'results':[],'pots':[],'players':[{'user_id':1,'contribution':10}], 'game_type':'holdem'}
  hid=self.db.execute('INSERT INTO poker_hands(room_id,hand_number,public_state,finished_at) VALUES(?,?,?,?)',(rid,1,json.dumps(hand),self.clock)).lastrowid
  self.db.execute('INSERT INTO poker_results VALUES(?,?,?,?,?)',(hid,1,12,22,'fixture'));self.db.commit();after=self.lobby()
  self.assertEqual(after['users'][0]['profit'],12);self.assertEqual(after['club']['profit_leaders'][0]['profit'],12)
  self.assertEqual(next(x for x in after['club']['missions'] if x['id']=='play3')['progress'],1)
  with self.reader() as db:self.assertEqual(rewards.progress(db,1,self.clock+86400)['play3'],0)
  self.db.execute('INSERT INTO mission_claims VALUES(?,?,?,?,?)',(1,wallet.day(self.clock),'play3',150,self.clock));self.db.commit()
  self.assertTrue(next(x for x in self.lobby()['club']['missions'] if x['id']=='play3')['claimed'])
 def test_profile_chat_nickname_and_blocked_members_refresh(self):
  rid=online.mutate(self.db,'/api/online/rooms',{},self.users[0],self.clock)['id'];self.db.execute('INSERT INTO room_chat VALUES(1,?,?,?,?,?)',(rid,1,'hello','public_cache_chat_1',self.clock));self.db.commit()
  with self.reader() as db:self.assertEqual(social.view(db,rid,2,self.clock)['messages'][0]['nickname'],'P1')
  self.lobby();self.db.execute("UPDATE users SET nickname='Renamed' WHERE id=1");self.db.execute("INSERT INTO member_profiles VALUES(1,'fox',NULL,1)");self.db.execute("INSERT INTO account_states VALUES(2,'blocked',1,'fixture',?)",(self.clock,));self.db.commit()
  after=self.lobby();self.assertNotIn(2,[u['id'] for u in after['users']]);self.assertEqual(next(u for u in after['users'] if u['id']==1)['nickname'],'Renamed')
  with self.reader() as db:
   self.assertEqual(social.view(db,rid,2,self.clock)['messages'][0]['nickname'],'Renamed');self.assertEqual(member_accounts.public_profiles(db)[1]['avatar_key'],'fox')
  self.assertNotIn(2,[u['id'] for u in after['club']['leaders']])
 def test_read_snapshot_versions_do_not_mix_old_and_new_commits(self):
  with self.reader() as old:
   before=rewards.public_leaders(old);self.db.execute("UPDATE users SET nickname='New commit' WHERE id=1");self.db.commit()
   with self.reader() as fresh:self.assertEqual(rewards.public_leaders(fresh)[0][0]['nickname'],'New commit')
   self.assertEqual(rewards.public_leaders(old),before)
 def test_uncommitted_rollback_cannot_poison_later_same_revision(self):
  self.db.execute("UPDATE users SET nickname='Rolled back' WHERE id=1");self.assertEqual(rewards.public_leaders(self.db)[0][0]['nickname'],'Rolled back');self.db.rollback()
  self.db.execute("UPDATE users SET nickname='Committed' WHERE id=1");self.db.commit()
  self.assertEqual(self.lobby()['club']['leaders'][0]['nickname'],'Committed')
 def test_users_keep_their_own_cards_and_receipts(self):
  rid=online.mutate(self.db,'/api/online/rooms',{},self.users[0],self.clock)['id'];r=online.get_room(self.db,rid)
  online.mutate(self.db,f'/api/online/rooms/{rid}/join',{'revision':r['revision']},self.users[1],self.clock)
  r=online.get_room(self.db,rid);online.mutate(self.db,f'/api/online/rooms/{rid}/start',{'revision':r['revision'],'operation_id':'cache_private_start_01'},self.users[0],self.clock);self.db.commit()
  for uid in (1,2,1):
   with self.reader() as db:v=online.room_view(db,rid,uid,self.clock,touch_presence=False)
   for p in v['hand']['players']:self.assertEqual(len(p['hole']),2 if p['user_id']==uid else 0)
   self.assertEqual('cache_private_start_01' in v['accepted_operations'],uid==1)
 def test_existing_receipts_gain_index_without_changing_order_or_account_scope(self):
  self.db.execute('DROP INDEX poker_operations_recent')
  rows=[]
  for uid in (1,2):
   for i in range(40):
    operation=f'index_receipt_{uid}_{40-i:03d}'
    rows.append((uid,operation,'fixture','{}',self.clock+i//3))
  self.db.executemany('INSERT INTO poker_operations VALUES(?,?,?,?,?)',rows)
  query='SELECT operation_id FROM poker_operations WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 8'
  expected={uid:[r[0] for r in self.db.execute(query,(uid,))] for uid in (1,2)}
  before=[tuple(r) for r in self.db.execute('SELECT * FROM poker_operations ORDER BY rowid')]
  online.initialize(self.db);online.initialize(self.db)
  self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM poker_operations ORDER BY rowid')],before)
  for uid in (1,2):
   self.assertEqual([r[0] for r in self.db.execute(query,(uid,))],expected[uid])
   plan=' '.join(r[3] for r in self.db.execute('EXPLAIN QUERY PLAN '+query,(uid,)))
   self.assertIn('poker_operations_recent',plan)
   self.assertNotIn('TEMP B-TREE',plan)
  self.assertEqual([r[0] for r in self.db.execute(query,(3,))],[])
 def test_shared_chat_does_not_share_voice_inboxes(self):
  rid=online.mutate(self.db,'/api/online/rooms',{},self.users[0],self.clock)['id'];r=online.get_room(self.db,rid);online.mutate(self.db,f'/api/online/rooms/{rid}/join',{'revision':r['revision']},self.users[1],self.clock)
  for uid in (1,2):self.db.execute('INSERT INTO voice_members VALUES(?,?,?,?,0)',(rid,uid,f'voice_session_{uid:04d}',self.clock))
  self.db.execute('INSERT INTO voice_signals(room_id,sender_id,sender_session,target_id,target_session,kind,payload,created_at) VALUES(?,?,?,?,?,?,?,?)',(rid,2,'voice_session_0002',1,'voice_session_0001','offer',json.dumps({'fixture':'only-one'}),self.clock));self.db.commit()
  for uid in (1,2,3,1):
   with self.reader() as db:v=social.view(db,rid,uid,self.clock)
   self.assertEqual(len(v['signals']),1 if uid==1 else 0)
 def test_database_identity_and_return_values_are_isolated(self):
  with self.reader() as db:
   first=rewards.public_leaders(db);first[0][0]['nickname']='mutated';self.assertEqual(rewards.public_leaders(db)[0][0]['nickname'],'P1')
  other=sqlite3.connect(':memory:');other.row_factory=sqlite3.Row;other.executescript('CREATE TABLE users(id INTEGER PRIMARY KEY);');view_cache.initialize(other);other.commit();other.execute('PRAGMA query_only=ON');other.execute('BEGIN')
  with self.reader() as db:
   self.assertEqual(view_cache.shared(db,'identity_test',('users',),lambda:'one'),'one');self.assertEqual(view_cache.shared(other,'identity_test',('users',),lambda:'two'),'two')
  other.close()
 def test_single_flight_failure_cleanup_and_bounded_storage(self):
  cache=view_cache.ViewCache(2);calls=[]
  def build():calls.append(1);time.sleep(.03);return {'x':[]}
  with ThreadPoolExecutor(6) as pool:values=list(pool.map(lambda _:cache.get('same',build),range(6)))
  self.assertEqual(len(calls),1);values[0]['x'].append(1);self.assertEqual(values[1]['x'],[])
  with self.assertRaises(ValueError):cache.get('failure',lambda:(_ for _ in ()).throw(ValueError()))
  self.assertIsNone(cache.get('failure',lambda:None));self.assertIsNone(cache.get('failure',lambda:1));cache.get('third',lambda:3)
  self.assertLessEqual(cache.stats()['entries'],2);self.assertEqual(cache.stats()['pending'],0)

class PushSeparation(test_connection_review.ReadOnlyStreams):
 def test_only_lobby_visible_changes_notify_the_lobby(self):
  status,started=self.clients[0].call(self.path+'/start',{'operation_id':'lobby_boundary_start_01'})
  self.assertEqual(status,200);state=started['state'];actor=state['hand']['actor'];own=self.clients[actor-1].call(self.path)[1]
  lobby_before=server.EVENTS.version_for(None);table_before=server.EVENTS.version_for(self.rid)
  first=own['legal']['first_card'];status,played=self.clients[actor-1].call(self.path+'/action',{'operation_id':'table_only_first_play_01','hand_id':own['hand']['id'],'turn_id':own['hand']['turn_id'],'action':'play','cards':[first]})
  self.assertEqual(status,200,played);self.assertEqual(server.EVENTS.version_for(None),lobby_before);self.assertNotEqual(server.EVENTS.version_for(self.rid),table_before)
  status,left=self.clients[actor-1].call(self.path+'/leave',{'operation_id':'lobby_visible_leave_001'})
  self.assertEqual(status,200,left);self.assertNotEqual(server.EVENTS.version_for(None),lobby_before)
 def test_slow_lobby_does_not_block_table_snapshot_or_action(self):
  entered=threading.Event();release=threading.Event();original=online.lobby
  def slow(*args,**kwargs):entered.set();release.wait(3);return original(*args,**kwargs)
  with patch.object(online,'lobby',side_effect=slow):
   lobby=Stream(self.clients[0],'/api/online/events?presence=client')
   try:
    self.assertTrue(entered.wait(1));start=time.perf_counter()
    with closing(Stream(self.clients[1],f'/api/online/events?presence=client&room={self.rid}')) as table:
     v=table.state();self.assertLess(time.perf_counter()-start,.8)
     begin=time.perf_counter();status,response=self.clients[2].call(self.path+'/start',{'operation_id':'priority_start_001','revision':v['revision']})
     self.assertEqual(status,200);self.assertLess(time.perf_counter()-begin,.8);self.assertGreater(table.state(response['state']['revision'])['revision'],v['revision'])
   finally:release.set();lobby.close()
if __name__=='__main__':unittest.main()
