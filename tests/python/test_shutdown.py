"""Actual voice HTTP readers must exit before the server joins handlers."""
import os,signal,subprocess,sys,threading,time,unittest
from unittest.mock import patch
from . import test_auth_review as auth_tests
from .test_app import ServerTestCase
from .test_voice import Wire
import server,voice_transport,wallet

class ShutdownRules(unittest.TestCase):
 def test_relay_shutdown_retires_all_peers_and_new_admission(self):
  import socket
  a,b=socket.socketpair();self.addCleanup(a.close);self.addCleanup(b.close)
  hub=voice_transport.Relay();peer=voice_transport.Peer(1,0,'shutdown_session',a);hub.add(peer)
  hub.stop();hub.stop();self.assertTrue(peer.stopped.is_set());self.assertEqual(hub.sessions(),[])
  with self.assertRaises(ValueError):hub.add(voice_transport.Peer(2,0,'next_session',b))
 @unittest.skipUnless(os.name=='posix','Fast buffered-socket shutdown is validated on Linux CI')
 def test_stopping_relays_unblocks_server_close_without_waiting_for_clients(self):
  f=auth_tests.AuthenticationReview();f.setUp();wire=None;thread=None
  try:
   with patch.object(voice_transport,'HUB',voice_transport.Relay()):
    f.http.daemon_threads=False;sid='shutdown_probe_session_01'
    self.assertEqual(f.alice.call('/api/social/rooms/0/voice/join',dict(session_id=sid))[0],200)
    wire=Wire(f.base,f.alice,0,sid);self.assertEqual(wire.status,101)
    start=time.monotonic();server.stop_transports();f.http.shutdown()
    thread=threading.Thread(target=f.http.server_close,daemon=True);thread.start();thread.join(2)
    self.assertFalse(thread.is_alive());self.assertLess(time.monotonic()-start,2.5)
    self.assertEqual(voice_transport.HUB.sessions(),[])
    with self.assertRaises(ValueError):voice_transport.HUB.add(voice_transport.Peer(2,0,'shutdown_new_session_01',wire.sock))
    voice_transport.HUB.stop()
  finally:
   if wire:wire.close()
   if thread:thread.join(3)
   f.doCleanups()

@unittest.skipUnless(os.name=='posix','Actual SIGTERM lifecycle is exercised on Linux CI')
class ShutdownSignal(ServerTestCase):
 def test_sigterm_with_voice_exits_cleanly_and_receipts_survive_restart(self):
  c=self.clients[0];self.assertEqual(c.call('/api/register',dict(username='shutdown_signal',nickname='Synthetic',password='password123'))[0],200)
  payload=dict(operation_id='shutdown_hourly_once_01');self.assertTrue(c.call('/api/wallet/hourly',payload)[1]['claimed'])
  sid='sigterm_voice_session_01';self.assertEqual(c.call('/api/social/rooms/0/voice/join',dict(session_id=sid))[0],200)
  wire=Wire(self.base,c,0,sid)
  try:
   begin=time.monotonic();self.proc.send_signal(signal.SIGTERM)
   self.assertEqual(self.proc.wait(timeout=5),0);self.assertLess(time.monotonic()-begin,5)
  finally:wire.close()
  from .test_app import ROOT
  env=dict(os.environ,POKER_DB=str(self.db_path),POKER_MARKET_DATA='0',POKER_REQUIRE_INVITE='0',POKER_SECURE_COOKIE='0',POKER_PUBLIC_ORIGIN='')
  self.__class__.proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--host','127.0.0.1','--port',self.base.rsplit(':',1)[1]],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  for _ in range(100):
   try:
    if c.call('/api/bootstrap')[0]==200:break
   except OSError:pass
   time.sleep(.05)
  result=c.call('/api/wallet/hourly',payload)
  self.assertEqual(result[0],200);self.assertTrue(result[1]['replayed']);self.assertEqual(result[1]['wallet']['balance'],wallet.INITIAL+wallet.HOURLY)
