"""Real HTTP/WebSocket sessions against disposable accounts and SQLite."""
import base64
import http.client
import json
from pathlib import Path
import secrets
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import battle
import server
from voice_transport import read_exact


class IslandHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.db_patch=patch.object(server,'DB_PATH',Path(cls.tmp.name)/'island.sqlite3');cls.db_patch.start()
        cls.invite_patch=patch.object(server,'REQUIRE_INVITE',False);cls.invite_patch.start();server.initialize()
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);cls.http.daemon_threads=True
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.host='127.0.0.1:'+str(cls.http.server_port);cls.origin='http://'+cls.host
        cls.cookies=[]
        for i in range(2):
            connection=http.client.HTTPConnection(cls.host,timeout=3)
            headers={'Content-Type':'application/json','X-Requested-With':'PokerClub','Origin':cls.origin}
            body={'username':'island_http_'+str(i),'nickname':'戰場測試'+str(i),'password':'SyntheticPreview123'}
            if i:
                with server.connect() as db:body['invite_code']=db.execute("SELECT value FROM settings WHERE key='invite_code'").fetchone()[0]
            connection.request('POST','/api/register',json.dumps(body),headers);response=connection.getresponse();assert response.status==200,response.read()
            cls.cookies.append(response.getheader('Set-Cookie').split(';')[0]);response.read();connection.close()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.thread.join(2);cls.invite_patch.stop();cls.db_patch.stop();cls.tmp.cleanup()

    def setUp(self):
        self.hub=battle.BattleHub();self.hub_patch=patch.object(battle,'HUB',self.hub);self.hub_patch.start()
        self.addCleanup(self.hub_patch.stop);self.addCleanup(self.hub.stop)

    def request(self,path,data=None,user=0,extra=None):
        connection=http.client.HTTPConnection(self.host,timeout=3)
        headers={'Origin':self.origin}
        if user is not None:headers['Cookie']=self.cookies[user]
        if data is not None:headers.update({'Content-Type':'application/json','X-Requested-With':'PokerClub'})
        headers.update(extra or {});connection.request('GET' if data is None else 'POST',path,None if data is None else json.dumps(data),headers)
        response=connection.getresponse();status=response.status;raw=response.read();head=dict(response.getheaders());connection.close()
        try:value=json.loads(raw)
        except ValueError:value=raw
        return status,value,head

    def ws(self,code,user=0,origin=None):
        connection=http.client.HTTPConnection(self.host,timeout=3)
        headers={'Cookie':self.cookies[user],'Origin':origin or self.origin,'Upgrade':'websocket','Connection':'Upgrade','Sec-WebSocket-Key':base64.b64encode(secrets.token_bytes(16)).decode(),'Sec-WebSocket-Version':'13'}
        connection.request('GET','/api/battle/socket?room='+code,headers=headers);response=connection.getresponse()
        self.assertEqual(response.status,101);self.addCleanup(connection.close);self.addCleanup(response.close)
        return connection,response

    def receive(self,response):
        first,second=read_exact(response.fp,2);length=second&127
        if length==126:length=struct.unpack('!H',read_exact(response.fp,2))[0]
        if length==127:length=struct.unpack('!Q',read_exact(response.fp,8))[0]
        data=read_exact(response.fp,length)
        return first&15,json.loads(data) if first&15==1 else data

    def send(self,connection,value):
        data=json.dumps(value).encode();mask=secrets.token_bytes(4);length=len(data)
        header=bytes([129,128|length]) if length<126 else bytes([129,254])+struct.pack('!H',length)
        connection.sock.sendall(header+mask+bytes(c^mask[i%4] for i,c in enumerate(data)))

    def until(self,response,predicate):
        for _ in range(60):
            op,value=self.receive(response)
            if op==1 and predicate(value):return value
        self.fail('Expected battle packet did not arrive')

    def test_private_routes_and_cross_origin(self):
        self.assertEqual(self.request('/api/battle',user=None)[0],401)
        self.assertEqual(self.request('/api/battle/create',{},user=None)[0],401)
        self.assertEqual(self.request('/api/battle/create',{},extra={'Origin':'https://wrong.example'})[0],403)
        self.assertEqual(self.request('/api/battle/socket?room=ABCDEF',extra={'Origin':'https://wrong.example'})[0],403)
        self.assertEqual(self.request('/api/battle/socket?room=ABCDEF')[0],403)

    def test_lobby_join_duplicate_creation_and_no_money_mutation(self):
        with server.connect() as db:before=list(db.iterdump())
        status,a,_=self.request('/api/battle/create',{'title':'測試房','bots':True});self.assertEqual(status,200)
        self.assertEqual(self.request('/api/battle/create',{'title':'重送'})[1]['code'],a['code'])
        self.assertEqual(self.request('/api/battle/join',{'code':a['code']},1)[0],200)
        status,lobby,head=self.request('/api/battle');self.assertEqual(status,200);self.assertEqual(head['Cache-Control'],'no-store')
        self.assertEqual(lobby['rooms'][0]['humans'],2);self.assertEqual(lobby['rooms'][0]['title'],'測試房')
        self.request('/api/battle/leave',{},1);self.request('/api/battle/leave',{},0)
        with server.connect() as db:self.assertEqual(list(db.iterdump()),before,'Battle requests must not mutate any wallet, card room or ledger data')

    def test_two_real_websockets_start_only_once_and_resume_same_actor(self):
        code=self.request('/api/battle/create',{})[1]['code'];self.request('/api/battle/join',{'code':code},1)
        a,ar=self.ws(code,0);b,br=self.ws(code,1)
        self.until(ar,lambda p:p['type']=='welcome');self.until(br,lambda p:p['type']=='welcome')
        self.send(b,{'type':'action','action':'start'})
        error=self.until(br,lambda p:p['type']=='error');self.assertIn('房主',error['message'])
        self.send(a,{'type':'action','action':'start'});self.send(a,{'type':'action','action':'start'})
        first=self.until(ar,lambda p:p['type']=='state' and p['phase']=='countdown');self.assertEqual(first['total'],16)
        self.assertEqual(sum(not p.bot for p in self.hub.rooms[code].match.players.values()),2)
        started=self.hub.rooms[code].match.started
        replacement,rr=self.ws(code,0);self.until(rr,lambda p:p['type']=='welcome')
        self.assertEqual(self.hub.rooms[code].match.started,started)
        resumed=self.until(rr,lambda p:p['type']=='state');self.assertEqual(resumed['self']['id'],first['self']['id']);self.assertEqual(resumed['total'],16)
        self.send(replacement,{'type':'input','seq':0,'x':999,'hp':999})
        error=self.until(rr,lambda p:p['type']=='error');self.assertIn('欄位',error['message'])
        self.assertNotEqual(self.hub.rooms[code].match.players[first['self']['id']].x,999)

    def test_pinned_vendor_assets_revalidate_and_unknown_paths_stay_private(self):
        for path in ('/battle.js','/battle-scene.js','/battle-art.js','/three.module.js','/three.core.js'):
            status,body,headers=self.request(path);self.assertEqual(status,200,path);self.assertEqual(headers['Cache-Control'],'no-cache');self.assertIn('javascript',headers['Content-Type'])
            self.assertEqual(self.request(path,extra={'If-None-Match':headers['ETag']})[0],304)
        self.assertEqual(self.request('/battle.py')[0],404);self.assertEqual(self.request('/static/battle.js')[0],404)

    def test_live_socket_loses_access_after_session_revocation(self):
        code=self.request('/api/battle/create',{})[1]['code'];connection,response=self.ws(code)
        self.until(response,lambda value:value['type']=='welcome');connection.sock.settimeout(7)
        token=self.cookies[0].split('=',1)[1];digest=server.hashlib.sha256(token.encode()).hexdigest()
        with server.connect() as db:
            expires=db.execute('SELECT expires FROM auth_sessions WHERE token_hash=?',(digest,)).fetchone()[0]
            db.execute('UPDATE auth_sessions SET expires=0 WHERE token_hash=?',(digest,))
        try:
            for _ in range(75):
                opcode,value=self.receive(response)
                if opcode==8:
                    self.assertEqual(struct.unpack('!H',value)[0],4003);break
            else:self.fail('Revoked session kept its battle socket')
        finally:
            with server.connect() as db:db.execute('UPDATE auth_sessions SET expires=? WHERE token_hash=?',(expires,digest))


if __name__=='__main__':unittest.main()
