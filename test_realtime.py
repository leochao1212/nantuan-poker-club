"""Real streaming HTTP clients: multicast latency, privacy, reconnect, revocation."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import http.client
import json
import time
import unittest
import urllib.request
from urllib.parse import urlsplit
from test_app import ServerTestCase


class Stream:
    def __init__(self, client, path):
        request = urllib.request.Request(client.base+path)
        for handler in client.opener.handlers:
            if isinstance(handler, urllib.request.HTTPCookieProcessor):
                handler.cookiejar.add_cookie_header(request)
        address = urlsplit(client.base)
        self.connection = http.client.HTTPConnection(address.hostname, address.port, timeout=4)
        self.connection.request('GET',path,headers={'Cookie':request.get_header('Cookie','')})
        self.response = self.connection.getresponse()
        assert self.response.status == 200, self.response.status
        assert self.response.getheader('Content-Type').startswith('text/event-stream')

    def event(self):
        event, data = '', ''
        while True:
            raw = self.response.readline()
            if not raw:
                raise EOFError('Event stream closed')
            line = raw.decode().rstrip('\r\n')
            if line.startswith('event: '): event = line[7:]
            elif line.startswith('data: '): data = line[6:]
            elif not line and data: return event, json.loads(data)

    def state(self, revision=0):
        while True:
            event, data = self.event()
            if event == 'state' and data.get('revision',revision) >= revision:
                return data

    def close(self):
        self.response.close()
        self.connection.close()


class PushFlow(ServerTestCase):
    def test_five_clients_push_reconnect_and_logout(self):
        first = self.clients[0]
        self.assertEqual(first.call('/api/online/events')[0],401)
        first.call('/api/register',{'username':'push0','nickname':'First','password':'password123'})
        code = first.call('/api/state')[1]['invite_code']
        for i in range(1,5):
            self.assertEqual(self.clients[i].call('/api/register',{'username':f'push{i}','nickname':f'Player{i}','password':'password123','invite_code':code})[0],200)
        rid = first.call('/api/online/rooms',{'name':'Push table'})[1]['id']
        path = f'/api/online/rooms/{rid}'
        for client in self.clients[1:5]:
            state = client.call(path)[1]
            self.assertEqual(client.call(path+'/join',{'revision':state['revision']})[0],200)
        streams = [Stream(c,f'/api/online/events?room={rid}') for c in self.clients[:5]]
        try:
            waiting = [s.state() for s in streams]
            before = time.perf_counter()
            status, started = first.call(path+'/start',{'revision':waiting[0]['revision']})
            self.assertEqual(status,200)
            revision = started['state']['revision']
            with ThreadPoolExecutor(5) as pool:
                views = list(pool.map(lambda s:s.state(revision),streams))
            elapsed = time.perf_counter()-before
            print(f'Five-player push delivery including action HTTP: {elapsed*1000:.1f} ms',flush=True)
            self.assertLess(elapsed, .8, 'Push should not wait for a one-second poll')
            for index, state in enumerate(views):
                self.assertNotIn('deck',state['hand'])
                self.assertNotIn('burned',state['hand'])
                for player in state['hand']['players']:
                    self.assertEqual(len(player['hole']),2 if player['user_id']==index+1 else 0)
            actor = views[0]['hand']['actor']
            own = views[actor-1]
            result = self.clients[actor-1].call(path+'/action',{'revision':revision,'hand_id':own['hand']['id'],'action':'call'})
            self.assertEqual(result[0],200)
            after = result[1]['state']
            self.assertGreater(after['revision'],revision)
            with ThreadPoolExecutor(5) as pool:
                views = list(pool.map(lambda s:s.state(after['revision']),streams))
            # Reconnect gets a fresh snapshot, not a replay exposing another user's cards.
            streams[2].close()
            streams[2] = Stream(self.clients[2],f'/api/online/events?room={rid}')
            resumed = streams[2].state()
            self.assertEqual(resumed['revision'],after['revision'])
            self.assertEqual(resumed['hand'],views[2]['hand'])
            self.assertEqual(self.clients[4].call('/api/logout',{})[0],200)
            event, data = streams[4].event()
            self.assertEqual(event,'auth')
            self.assertEqual(data,{})
            # Dealer timeouts must wake subscribers even without another GET or action.
            import sqlite3
            with closing(sqlite3.connect(self.db_path)) as db:
                with db:
                    stored = json.loads(db.execute('SELECT state FROM poker_rooms WHERE id=?',(rid,)).fetchone()[0])
                    stored['hand']['deadline'] = time.time()-1
                    db.execute('UPDATE poker_rooms SET state=? WHERE id=?',(json.dumps(stored),rid))
            timed = streams[0].state(after['revision']+1)
            self.assertGreater(timed['revision'],after['revision'])
            self.assertNotEqual(timed['hand']['actor'],after['hand']['actor'])
        finally:
            for stream in streams: stream.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
