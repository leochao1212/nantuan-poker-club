"""WAL snapshots cannot block game actions; idle SSE uses cheap keepalives."""
from contextlib import closing
from pathlib import Path
import tempfile,threading,time,unittest,socket
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import server,online
from realtime import Hub,WriteQueue
from .test_app import Client
from .test_realtime import Stream

class ReadOnlyStreams(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.patches=[patch.object(server,'DB_PATH',Path(self.tmp.name)/'test.sqlite3'),patch.object(server,'EVENTS',Hub()),patch.object(server,'WRITES',WriteQueue()),patch.object(server,'SNAPSHOTS',threading.Semaphore(1))]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        server.initialize();self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.http.daemon_threads=True
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
        self.clients=[Client(f'http://127.0.0.1:{self.http.server_port}') for _ in range(4)]
        for i,c in enumerate(self.clients):
            data={'username':f'read_stream_{i}','nickname':str(i),'password':'password123'}
            if i:data['invite_code']=self.clients[0].call('/api/state')[1]['invite_code']
            self.assertEqual(c.call('/api/register',data)[0],200)
        self.rid=self.clients[0].call('/api/online/rooms',{'name':'Read test','game_type':'big2'})[1]['id'];self.path=f'/api/online/rooms/{self.rid}'
        for c in self.clients[1:]:c.call(self.path+'/join',{'revision':self.clients[0].call(self.path)[1]['revision']})
    def close(self):
        server.EVENTS.stop();self.http.shutdown();self.http.server_close();self.thread.join(2)
    def test_slow_snapshot_does_not_hold_action_write_queue(self):
        entered=threading.Event();release=threading.Event();original=online.room_view
        def slow(db,rid,uid,clock,**kwargs):
            if uid==1:
                db.execute('PRAGMA query_only=ON');entered.set();release.wait(3)
            return original(db,rid,uid,clock,**kwargs)
        with patch.object(online,'room_view',side_effect=slow):
            stream=Stream(self.clients[0],f'/api/online/events?presence=client&room={self.rid}')
            try:
                self.assertTrue(entered.wait(1));revision=self.clients[1].call(self.path)[1]['revision']
                start=time.perf_counter();status,result=self.clients[1].call(self.path+'/start',{'revision':revision})
                self.assertEqual(status,200);self.assertLess(time.perf_counter()-start,.8)
            finally:release.set();stream.close()
    def test_idle_ping_does_not_rebuild_snapshot_and_auth_still_revokes(self):
        original=online.room_view;calls=[]
        def readonly(db,*args,**kwargs):
            db.execute('PRAGMA query_only=ON');calls.append(1)
            return original(db,*args,**kwargs)
        with patch.object(online,'room_view',side_effect=readonly),closing(Stream(self.clients[0],f'/api/online/events?presence=client&room={self.rid}')) as stream:
            stream.state();kind,ping=stream.event();self.assertEqual(kind,'ping');self.assertIn('server_time',ping)
            self.assertEqual(len(calls),1)
            self.assertEqual(self.clients[0].call('/api/logout',{})[0],200)
            self.assertEqual(stream.event(),('auth',{}))
    def test_presence_exposes_only_current_revision_for_recovery(self):
        c=self.clients[0];r=c.call(self.path)[1]
        response=c.call('/api/online/presence',{'room_id':self.rid})[1]
        self.assertEqual(response['room_revision'],r['revision']);self.assertNotIn('state',response)
        self.assertEqual(c.call('/api/online/client-event',{'client':'valid_connection_id_01','kind':'password','password':'ignored'})[0],400)
        self.assertEqual(c.call('/api/online/client-event',{'client':'valid_connection_id_01','kind':'stream_stale','room_id':self.rid,'revision':r['revision']})[0],200)
    def test_partial_body_times_out_without_entering_action_queue(self):
        before=server.WRITES.next_ticket
        with patch.object(server.Handler,'timeout',.2),socket.create_connection(('127.0.0.1',self.http.server_port),timeout=2) as sock:
            sock.sendall(b'POST /api/online/presence HTTP/1.0\r\nHost: localhost\r\nX-Requested-With: PokerClub\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{')
            self.assertIn(b'408',sock.recv(4096).split(b'\r\n')[0])
        self.assertEqual(server.WRITES.next_ticket,before)
        self.assertEqual(self.clients[0].call(self.path)[0],200)

if __name__=='__main__':unittest.main()
