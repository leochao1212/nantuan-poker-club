"""Real authenticated WebSocket relay, privacy, expiry and chip conservation."""
import base64,io,json,os,socket,struct,time,unittest,urllib.parse
from contextlib import closing
from unittest.mock import patch
import online,social,voice_transport as v
from . import test_club as fixtures
from .test_app import ServerTestCase,Client


class Wire:
    def __init__(self,base,client,room,session,origin=None):
        parsed=urllib.parse.urlsplit(base);self.sock=socket.create_connection((parsed.hostname,parsed.port),timeout=3);self.sock.settimeout(3);self.file=self.sock.makefile('rb')
        cookies=next(h.cookiejar for h in client.opener.handlers if hasattr(h,'cookiejar'))
        cookie='; '.join(c.name+'='+c.value for c in cookies)
        key=base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET /api/social/voice/socket?room={room}&session={session} HTTP/1.1\r\nHost: {parsed.netloc}\r\nOrigin: {origin or base}\r\nCookie: {cookie}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        self.status=int(self.file.readline().split()[1])
        while self.file.readline().strip():pass
        if self.status==101:self.receive()
    def send(self,payload,opcode=2):
        mask=b'1234';length=len(payload);head=bytes([128|opcode,128|length]) if length<126 else bytes([128|opcode,128|126])+struct.pack('!H',length)
        self.sock.sendall(head+mask+bytes(b^mask[i%4] for i,b in enumerate(payload)))
    def receive(self):
        a,b=v.read_exact(self.file,2);n=b&127
        if n==126:n=struct.unpack('!H',v.read_exact(self.file,2))[0]
        elif n==127:n=struct.unpack('!Q',v.read_exact(self.file,8))[0]
        payload=v.read_exact(self.file,n)
        if a&15==9:self.send(payload,10);return self.receive()
        return a&15,payload
    def close(self):
        try:self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        self.file.close();self.sock.close()


class VoiceRules(unittest.TestCase):
    def setUp(self):fixtures.WalletRules.setUp(self)
    def test_private_access_spectator_and_leaving_seat(self):
        room=online.mutate(self.db,'/api/online/rooms',{'private':True,'name':'Private'},self.users[0],self.clock)['id']
        with self.assertRaisesRegex(Exception,'私人包廂'):social.voice_state(self.db,room,2,self.clock)
        path=f'/api/social/rooms/{room}/voice/join';sid='voice_owner_session_1'
        social.mutate(self.db,path,{'session_id':sid},self.users[0],self.clock)
        online.mutate(self.db,f'/api/online/rooms/{room}/leave',{'operation_id':'voice_leave_seat_0001'},self.users[0],self.clock+1)
        self.assertTrue(social.voice_member(self.db,room,1,sid,self.clock+2))
        self.assertFalse(online.get_room(self.db,room)['seats'])
    def test_background_socket_preserves_membership_without_timer_writes(self):
        sid='background_voice_session';social.mutate(self.db,'/api/social/rooms/0/voice/join',{'session_id':sid},self.users[0],self.clock)
        with patch.object(v.HUB,'sessions',return_value=[(0,1,sid)]):
            social.cleanup(self.db,self.clock+100)
            self.assertTrue(social.voice_member(self.db,0,1,sid,self.clock+100))
            self.assertEqual(social.voice_state(self.db,0,1,self.clock+100)['own_session'],sid)
            self.assertEqual(len(social.voice_state(self.db,0,1,self.clock+100)['voice_members']),1)
            with self.assertRaisesRegex(Exception,'另一個分頁'):social.mutate(self.db,'/api/social/rooms/0/voice/join',{'session_id':'different_session_001','resume':True},self.users[0],self.clock+100)
        social.cleanup(self.db,self.clock+101)
        self.assertFalse(social.voice_member(self.db,0,1,sid,self.clock+101))
    def test_membership_is_single_channel_and_resume_cannot_steal(self):
        rid=online.mutate(self.db,'/api/online/rooms',{},self.users[0],self.clock)['id']
        social.mutate(self.db,'/api/social/rooms/0/voice/join',{'session_id':'lobby_voice_session1'},self.users[1],self.clock)
        with self.assertRaisesRegex(Exception,'另一個分頁'):social.mutate(self.db,f'/api/social/rooms/{rid}/voice/join',{'session_id':'table_voice_session1','resume':True},self.users[1],self.clock+1)
        social.mutate(self.db,f'/api/social/rooms/{rid}/voice/join',{'session_id':'table_voice_session1'},self.users[1],self.clock+1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM voice_members WHERE user_id=2').fetchone()[0],1)
        self.assertFalse(social.voice_member(self.db,0,2,'lobby_voice_session1',self.clock+1))
    def test_slow_peer_queue_is_bounded_and_channels_isolated(self):
        hub=v.Relay();socks=[]
        try:
            peers=[]
            for uid,room in [(1,0),(2,0),(3,9)]:
                a,b=socket.socketpair();socks.extend([a,b]);peer=v.Peer(uid,room,str(uid),a);hub.add(peer);peers.append(peer)
            for i in range(100):hub.broadcast(peers[0],bytes([i])*1280)
            self.assertEqual(peers[1].queue.qsize(),8);self.assertEqual(peers[2].queue.qsize(),0)
            for i in range(92,100):self.assertEqual(peers[1].queue.get(),struct.pack('!I',1)+bytes([i])*1280)
        finally:
            for s in socks:s.close()
    def test_websocket_rejects_unmasked_fragmented_and_large_frames(self):
        for payload in (b'\x82\x00',b'\x02\x80',b'\x82\xfe'+struct.pack('!H',3000)):
            with self.assertRaises(ValueError):v.read_frame(io.BytesIO(payload))


class VoiceAPI(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();invite=None
        for i,c in enumerate(cls.clients[:3]):
            code,result=c.call('/api/register',{'username':f'voice_user_{i}','nickname':f'V{i}','password':'IsolatedOnly123',**({'invite_code':invite} if invite else {})})
            assert code==200,result
            if not invite:invite=c.call('/api/state')[1]['invite_code']
    def test_real_audio_delivery_auth_isolation_and_finances(self):
        a,b,c=self.clients[:3];before=[x.call('/api/online/lobby')[1]['wallet']['total'] for x in (a,b,c)]
        sid=['real_voice_session_'+str(i) for i in range(3)];wires=[]
        try:
            for i,client in enumerate((a,b,c)):
                self.assertEqual(client.call('/api/social/rooms/0/voice/join',{'session_id':sid[i]})[0],200)
                wire=Wire(self.base,client,0,sid[i]);wires.append(wire);self.assertEqual(wire.status,101)
            time.sleep(.5)
            pcm=struct.pack('<h',1234)*640;wires[0].send(pcm);op,payload=wires[1].receive();self.assertEqual(op,2);self.assertEqual(payload,struct.pack('!I',1)+pcm)
            self.assertEqual(wires[2].receive()[1],struct.pack('!I',1)+pcm)
            self.assertTrue(all(m['connected'] for m in a.call('/api/social/voice/state?room=0')[1]['voice_members']))
            denied=Wire(self.base,a,0,sid[0],origin='https://evil.invalid');self.assertEqual(denied.status,403);denied.close()
            anonymous=Wire(self.base,Client(self.base),0,sid[0]);self.assertEqual(anonymous.status,401);anonymous.close()
            a.call('/api/social/rooms/0/voice/leave',{'session_id':sid[0]})
            expired=Wire(self.base,a,0,sid[0]);self.assertEqual(expired.status,403);expired.close()
            self.assertEqual(before,[x.call('/api/online/lobby')[1]['wallet']['total'] for x in (a,b,c)])
            # Periodic authorization closes an existing transport after logout.
            b.call('/api/logout',{});wires[1].sock.settimeout(8);started=time.monotonic()
            try:
                while time.monotonic()-started<8:
                    opcode,_=wires[1].receive()
                    if opcode==8:break
                else:self.fail('Revoked voice remained connected')
            except (EOFError,ConnectionError):pass
            self.assertGreater(time.monotonic()-started,2,'Transport must stay alive until the periodic authorization check')
        finally:
            for w in wires:w.close()


if __name__=='__main__':unittest.main(verbosity=2)
