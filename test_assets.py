"""Static image serving: the cover whitelist and revalidation caching."""
from pathlib import Path
import http.client,tempfile,threading,unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import server
from realtime import Hub,WriteQueue

COVERS=('holdem','big2','blackjack','roulette','baccarat','slot','mines','dice','tower','inbetween','mahjong')

class StaticImages(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for p in [patch.object(server,'DB_PATH',Path(self.tmp.name)/'test.sqlite3'),patch.object(server,'EVENTS',Hub()),patch.object(server,'WRITES',WriteQueue()),patch.object(server,'SNAPSHOTS',threading.Semaphore(1))]:
            p.start();self.addCleanup(p.stop)
        server.initialize();self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.http.daemon_threads=True
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
    def close(self):
        server.EVENTS.stop();self.http.shutdown();self.http.server_close();self.thread.join(2)
    def get(self,path,headers=None):
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)
        try:
            c.request('GET',path,headers=headers or {});r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def test_every_cover_is_served(self):
        for name in COVERS:
            status,headers,body=self.get(f'/assets/covers/{name}.webp')
            self.assertEqual(status,200,name);self.assertEqual(headers['Content-Type'],'image/webp');self.assertTrue(body.startswith(b'RIFF'),name)
    def test_unknown_or_tricky_cover_paths_are_404(self):
        for path in ('/assets/covers/nope.webp','/assets/covers/HOLDEM.webp','/assets/covers/holdem.webp/','/assets/covers/../poker-night.webp','/assets/covers/holdem.png','/assets/covers/%68oldem.webp'):
            self.assertEqual(self.get(path)[0],404,path)
    def test_images_revalidate_with_etag(self):
        status,headers,body=self.get('/assets/covers/holdem.webp')
        self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'public, max-age=0, must-revalidate');etag=headers['ETag']
        status,headers,body=self.get('/assets/covers/holdem.webp',{'If-None-Match':etag})
        self.assertEqual(status,304);self.assertEqual(body,b'')
        self.assertEqual(self.get('/assets/covers/holdem.webp',{'If-None-Match':'"stale"'})[0],200)
    def raw(self,lines):
        import socket
        with socket.create_connection(('127.0.0.1',self.http.server_port),timeout=5) as sock:
            sock.sendall(('\r\n'.join(lines)+'\r\n\r\n').encode());data=b''
            while chunk:=sock.recv(65536):data+=chunk
        head,_,body=data.partition(b'\r\n\r\n');return head.decode('latin-1'),body
    def test_if_none_match_forms(self):
        etag=self.get('/assets/covers/dice.webp')[1]['ETag']
        for value in ('W/'+etag,'"x", '+etag,'"x",'+etag,'*'):
            self.assertEqual(self.get('/assets/covers/dice.webp',{'If-None-Match':value})[0],304,value)
        for value in ('','"x"','w/'+etag,etag.strip('"')):
            self.assertEqual(self.get('/assets/covers/dice.webp',{'If-None-Match':value})[0],200,value)
        head,body=self.raw(['GET /assets/covers/dice.webp HTTP/1.1','Host: x','If-None-Match: "x"','If-None-Match: '+etag,'Connection: close'])
        self.assertTrue(head.startswith('HTTP/1.0 304') or head.startswith('HTTP/1.1 304'),head.split('\r\n')[0])
    def test_304_has_no_body_headers(self):
        etag=self.get('/assets/covers/slot.webp')[1]['ETag']
        head,body=self.raw(['GET /assets/covers/slot.webp HTTP/1.1','Host: x','If-None-Match: '+etag,'Connection: close'])
        lower=head.lower()
        self.assertIn(' 304 ',head.split('\r\n')[0]);self.assertEqual(body,b'')
        self.assertNotIn('content-length:',lower);self.assertNotIn('content-type:',lower);self.assertIn('etag:',lower)
    def test_non_image_responses_stay_no_store(self):
        status,headers,_=self.get('/api/bootstrap')
        self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store');self.assertNotIn('ETag',headers)

if __name__=='__main__':unittest.main()
