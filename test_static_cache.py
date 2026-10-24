"""Static CSS/JS/SVG: gzip when accepted, ETag revalidation; index.html and APIs unchanged (P21)."""
from pathlib import Path
import gzip,hashlib,http.client,socket,tempfile,threading,unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import server
from realtime import Hub,WriteQueue

STATIC=Path(server.ROOT)/'static'
REVALIDATE='no-cache'  # not max-age=0: Cloudflare's Browser Cache TTL would stretch that to 4 hours

class StaticTextCaching(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        for p in [patch.object(server,'DB_PATH',Path(self.tmp.name)/'test.sqlite3'),patch.object(server,'EVENTS',Hub()),patch.object(server,'WRITES',WriteQueue()),patch.object(server,'SNAPSHOTS',threading.Semaphore(1))]:
            p.start();self.addCleanup(p.stop)
        server.initialize();self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.http.daemon_threads=True
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.close)
    def close(self):
        server.EVENTS.stop();self.http.shutdown();self.http.server_close();self.thread.join(2)
    def get(self,path,headers=None,method='GET'):
        c=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)
        try:
            # http.client sends "Accept-Encoding: identity" unless the caller supplies one.
            c.request(method,path,headers=headers or {});r=c.getresponse();return r.status,dict(r.getheaders()),r.read()
        finally:c.close()
    def raw(self,lines):
        with socket.create_connection(('127.0.0.1',self.http.server_port),timeout=5) as sock:
            sock.sendall(('\r\n'.join(lines)+'\r\n\r\n').encode());data=b''
            while chunk:=sock.recv(65536):data+=chunk
        head,_,body=data.partition(b'\r\n\r\n');return head.decode('latin-1'),body

    def test_gzip_when_accepted(self):
        for path,ctype in (('/night.css','text/css; charset=utf-8'),('/bonus.js','text/javascript; charset=utf-8'),('/app.js','text/javascript; charset=utf-8'),('/favicon.svg','image/svg+xml; charset=utf-8')):
            with self.subTest(path=path):
                status,headers,body=self.get(path,{'Accept-Encoding':'gzip, deflate, br'})
                original=(STATIC/path[1:]).read_bytes()
                self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],ctype)
                self.assertEqual(headers['Content-Encoding'],'gzip');self.assertEqual(headers['Vary'],'Accept-Encoding')
                self.assertEqual(int(headers['Content-Length']),len(body))
                self.assertEqual(gzip.decompress(body),original)
                self.assertEqual(headers['Cache-Control'],REVALIDATE)
                self.assertEqual(headers['ETag'],'"'+hashlib.sha256(original).hexdigest()+'-gz"')
        self.assertLess(len(self.get('/night.css',{'Accept-Encoding':'gzip'})[2]),len((STATIC/'night.css').read_bytes())//2)

    def test_identity_without_gzip(self):
        for headers in ({},{'Accept-Encoding':'identity'},{'Accept-Encoding':'br, deflate'},{'Accept-Encoding':'gzip;q=0'},{'Accept-Encoding':'gzip;q=0, *'}):
            for path in ('/night.css','/bonus.js'):
                with self.subTest(path=path,headers=headers):
                    status,got,body=self.get(path,headers)
                    original=(STATIC/path[1:]).read_bytes()
                    self.assertEqual(status,200);self.assertNotIn('Content-Encoding',got);self.assertEqual(got['Vary'],'Accept-Encoding')
                    self.assertEqual(body,original);self.assertEqual(int(got['Content-Length']),len(original))
                    self.assertEqual(got['ETag'],'"'+hashlib.sha256(original).hexdigest()+'"');self.assertEqual(got['Cache-Control'],REVALIDATE)
        for value in ('GZIP','x-gzip','*','deflate, gzip;q=0.5'):
            self.assertEqual(self.get('/night.css',{'Accept-Encoding':value})[1].get('Content-Encoding'),'gzip',value)

    def test_etags_differ_and_revalidate(self):
        for path in ('/night.css','/bonus.js'):
            with self.subTest(path=path):
                plain=self.get(path)[1]['ETag'];packed=self.get(path,{'Accept-Encoding':'gzip'})[1]['ETag']
                self.assertNotEqual(plain,packed)
                status,headers,body=self.get(path,{'If-None-Match':plain})
                self.assertEqual(status,304);self.assertEqual(body,b'');self.assertEqual(headers['ETag'],plain);self.assertEqual(headers['Vary'],'Accept-Encoding');self.assertEqual(headers['Cache-Control'],REVALIDATE)
                status,headers,body=self.get(path,{'Accept-Encoding':'gzip','If-None-Match':packed})
                self.assertEqual(status,304);self.assertEqual(body,b'');self.assertEqual(headers['ETag'],packed);self.assertNotIn('Content-Encoding',headers)
                # Validator of the other representation must not produce a 304.
                self.assertEqual(self.get(path,{'Accept-Encoding':'gzip','If-None-Match':plain})[0],200)
                self.assertEqual(self.get(path,{'If-None-Match':packed})[0],200)
                for value in ('"stale"','',packed.strip('"'),'w/'+packed):
                    self.assertEqual(self.get(path,{'Accept-Encoding':'gzip','If-None-Match':value})[0],200,value)
                for value in ('W/'+packed,'"x", '+packed,'"x",'+packed,'*'):
                    self.assertEqual(self.get(path,{'Accept-Encoding':'gzip','If-None-Match':value})[0],304,value)

    def test_multiple_if_none_match_lines_and_304_headers(self):
        packed=self.get('/night.css',{'Accept-Encoding':'gzip'})[1]['ETag']
        head,body=self.raw(['GET /night.css HTTP/1.1','Host: x','Accept-Encoding: gzip','If-None-Match: "x"','If-None-Match: '+packed,'Connection: close'])
        lower=head.lower()
        self.assertIn(' 304 ',head.split('\r\n')[0]);self.assertEqual(body,b'')
        self.assertNotIn('content-length:',lower);self.assertNotIn('content-type:',lower);self.assertNotIn('content-encoding:',lower)
        self.assertIn('etag: '+packed.lower(),lower);self.assertIn('vary: accept-encoding',lower)

    def test_post_with_etag_is_not_a_304(self):
        packed=self.get('/bonus.js',{'Accept-Encoding':'gzip'})[1]['ETag']
        self.assertNotEqual(self.get('/bonus.js',{'Accept-Encoding':'gzip','If-None-Match':packed},method='POST')[0],304)

    def test_index_html_stays_no_store(self):
        for path in ('/','/index.html','/ledger'):
            for headers in ({},{'Accept-Encoding':'gzip'},{'Accept-Encoding':'gzip','If-None-Match':'*'}):
                with self.subTest(path=path,headers=headers):
                    status,got,body=self.get(path,headers)
                    self.assertEqual(status,200);self.assertEqual(got['Cache-Control'],'no-store');self.assertNotIn('ETag',got)
                    self.assertEqual(got['Vary'],'Accept-Encoding')
                    name='ledger.html' if path=='/ledger' else 'index.html'
                    expected=(STATIC/name).read_bytes()
                    self.assertEqual(gzip.decompress(body) if got.get('Content-Encoding')=='gzip' else body,expected)
                    self.assertEqual(got.get('Content-Encoding'),'gzip' if 'Accept-Encoding' in headers else None)

    def test_api_untouched(self):
        status,headers,body=self.get('/api/bootstrap',{'Accept-Encoding':'gzip','If-None-Match':'*'})
        self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-store')
        for name in ('Content-Encoding','Vary','ETag'):self.assertNotIn(name,headers)
        self.assertTrue(body.startswith(b'{'))

    def test_outside_whitelist_404(self):
        for path in ('/server.py','/static/night.css','/night.css/','/NIGHT.css','/../server.py','/nope.js','/%6eight.css','/night.css%00.js'):
            status,headers,_=self.get(path,{'Accept-Encoding':'gzip'})
            self.assertEqual(status,404,path);self.assertNotIn('Content-Encoding',headers);self.assertNotIn('ETag',headers)

    def test_concurrent_cold_requests_compress_each_file_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        file=Path(self.tmp.name)/'cold.css';file.write_bytes(b'.card{color:red}'*1000)
        original=server.gzip.compress
        def slow(*args,**kwargs):
            time.sleep(.02)
            return original(*args,**kwargs)
        with patch.object(server.gzip,'compress',side_effect=slow) as compress:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(lambda _:server.static_text(file),range(8)))
        self.assertEqual(compress.call_count,1)
        self.assertTrue(all(value is results[0] for value in results))

    def test_cache_reused_until_file_changes(self):
        tmp=Path(self.tmp.name)/'x.css';tmp.write_bytes(b'a{color:red}'*50)
        first=server.static_text(tmp);self.assertIs(server.static_text(tmp),first)
        with patch.object(server.gzip,'compress',side_effect=AssertionError('recompressed')):
            server.static_text(tmp)
        tmp.write_bytes(b'b{color:blue}'*50)
        import os;st=tmp.stat();os.utime(tmp,ns=(st.st_atime_ns,st.st_mtime_ns+1_000_000_000))
        second=server.static_text(tmp);self.assertNotEqual(first[1],second[1]);self.assertEqual(gzip.decompress(second[2]),b'b{color:blue}'*50)

if __name__=='__main__':unittest.main()
