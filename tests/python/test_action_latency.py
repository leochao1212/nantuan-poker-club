"""Interactive snapshots stay read-only and cannot reserve the game FIFO."""
import threading,time,unittest,urllib.request,re
from unittest.mock import patch
import online,server
from . import test_connection_review
class ActionLatency(test_connection_review.ReadOnlyStreams):
 def test_http_snapshot_is_read_only(self):
  original=online.room_view;calls=[]
  def view(db,*args,**kwargs):
   self.assertFalse(kwargs.get('touch_presence',True));db.execute('PRAGMA query_only=ON');calls.append(1);return original(db,*args,**kwargs)
  with patch.object(online,'room_view',side_effect=view):
   self.assertEqual(self.clients[0].call(self.path)[0],200)
   r=self.clients[0].call(self.path+'/start',{'revision':1,'operation_id':'read_only_start_0001'})
   self.assertEqual(r[0],200,r[1]);self.assertGreaterEqual(len(calls),2)
 def assert_slow_reply_releases_queue(self,post):
  original=online.room_view;entered=threading.Event();release=threading.Event();result=[]
  def view(db,rid,uid,*args,**kwargs):
   if uid==1:entered.set();release.wait(3)
   return original(db,rid,uid,*args,**kwargs)
  with patch.object(online,'room_view',side_effect=view):
   worker=threading.Thread(target=lambda:result.append(self.clients[0].call(self.path+'/start',{'revision':1,'operation_id':'slow_snapshot_start_01'}) if post else self.clients[0].call(self.path)))
   worker.start()
   try:
    self.assertTrue(entered.wait(1));started=time.perf_counter()
    self.assertEqual(self.clients[1].call('/api/online/presence',{'room_id':self.rid})[0],200)
    self.assertLess(time.perf_counter()-started,.5);self.assertTrue(worker.is_alive())
   finally:release.set();worker.join(4)
   self.assertEqual(result[0][0],200,result)
 def test_slow_post_snapshot_releases_write_queue(self):self.assert_slow_reply_releases_queue(True)
 def test_slow_get_snapshot_releases_write_queue(self):self.assert_slow_reply_releases_queue(False)
 def test_server_timing_has_exclusive_stages(self):
  import json
  request=urllib.request.Request(self.clients[0].base+self.path+'/start',json.dumps({'revision':1,'operation_id':'timed_start_0001'}).encode(),{'Content-Type':'application/json','X-Requested-With':'PokerClub'})
  with self.clients[0].opener.open(request) as r:
   data=json.load(r);timing=dict((name,float(ms)) for name,ms in re.findall(r'(\w+);dur=([\d.]+)',r.headers['Server-Timing']))
  for key in ('receive','queue','db_wait','process','commit','snapshot','encode','server'):self.assertIn(key,timing)
  self.assertGreaterEqual(timing['server']+.1,sum(timing[k] for k in ('receive','queue','db_wait','process','commit','snapshot','encode')))
  self.assertRegex(data['request_id'],r'^[0-9a-f]{16}$')
if __name__=='__main__':unittest.main()

