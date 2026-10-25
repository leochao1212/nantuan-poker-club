"""Static image serving: the cover whitelist and revalidation caching."""
from pathlib import Path
import hashlib,http.client,tempfile,threading,unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import server
from realtime import Hub,WriteQueue

COVERS=('holdem','big2','blackjack','roulette','baccarat','slot','mines','dice','tower','inbetween','mahjong')
BUTTONS=('btn-primary-l','btn-primary-m','btn-primary-r','btn-primary-sm-l','btn-primary-sm-m','btn-primary-sm-r','coin','chip-10','chip-50','chip-100','chip-500')
BUTTONS2=('btn-secondary-l','btn-secondary-m','btn-secondary-r','btn-secondary-sm-l','btn-secondary-sm-m','btn-secondary-sm-r',
          'btn-danger-sm-l','btn-danger-sm-m','btn-danger-sm-r',
          'tab-on-l','tab-on-m','tab-on-r','tab-off-l','tab-off-m','tab-off-r','frame-table','frame-card')
PIECES=('slot-777','slot-crown','slot-diamond','slot-bell','slot-cherry','slot-bar','dice-q','dice-1','dice-2','dice-3','dice-4','dice-5','dice-6','mine-gem','mine-bomb')
# P20 group 4: loaded per page by CSS (only the roulette, hold'em and blackjack tables reference them), not preloaded
TABLE_PIECES=('roul-frame','roul-hub','dealer-btn','bet-chips','bj-shoe')
# P20 group 5: mahjong tiles. One SVG sprite (faces as <view> fragments, served as text so it gets gzip + ETag)
# plus the bird and flower illustrations; only the mahjong page loads them
MJ_PIECES=('mj-bird','mj-f-spring','mj-f-summer','mj-f-autumn','mj-f-winter','mj-f-plum','mj-f-orchid','mj-f-chrys','mj-f-bamboo')
MJ_CODES=[f'{s}{n}' for s in 'mps' for n in range(1,10)]+[f'z{n}' for n in range(1,8)]+[f'f{n}' for n in range(1,9)]+['back']

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
    def test_current_ui_has_one_stylesheet_and_no_retired_routes(self):
        import re
        status,_,body=self.get('/')
        self.assertEqual(status,200)
        html=body.decode('utf-8')
        self.assertEqual(re.findall(r'<link rel="stylesheet" href="([^"]+)"',html),['/night.css?v=current-ui-20261025'])
        self.assertIn('/ui-art.js?v=current-ui-20261025',html)
        self.assertIn('/round-presentation.js',html)
        for name in ('casino','ui','arcade','mahjong','profile','effects','features','transfers','clubhouse-scene','game-settings'):
            self.assertEqual(self.get('/'+name+'.css')[0],404,name)
        for name in ('concierge','host','steward'):
            status,headers,body=self.get('/assets/staff/'+name+'.webp')
            self.assertEqual(status,200);self.assertTrue(body.startswith(b'RIFF'))
            self.assertEqual(self.get('/assets/staff/'+name+'.webp',{'If-None-Match':headers['ETag']})[0],304)
        for path in ('/assets/staff/nope.webp','/assets/staff/../poker-night.webp','/assets/staff/CONCIERGE.webp'):
            self.assertEqual(self.get(path)[0],404)

    def test_fingerprinted_images_are_immutable_and_reject_stale_versions(self):
        for path in ('/assets/covers/slot.webp','/assets/pieces/dice-1.webp','/assets/buttons/coin.webp','/assets/clubhouse/tier-1-small.webp','/assets/staff/host.webp','/assets/pieces/card-back-friends.webp','/assets/cards/as.webp','/assets/cards/kh.webp'):
            raw_status,raw_headers,raw=self.get(path)
            self.assertEqual(raw_status,200);self.assertEqual(raw_headers['Cache-Control'],'no-cache')
            version=hashlib.sha256(raw).hexdigest()[:12]
            status,headers,body=self.get(path+'?v='+version)
            self.assertEqual(status,200);self.assertEqual(body,raw)
            self.assertEqual(headers['Cache-Control'],'public, max-age=31536000, immutable')
            self.assertEqual(self.get(path+'?v='+version,{'If-None-Match':headers['ETag']})[0],304)
            for query in ('?v=old','?v=','?v='+version+'&v=old'):
                status,headers,_=self.get(path+query,{'If-None-Match':raw_headers['ETag']})
                self.assertEqual(status,404);self.assertEqual(headers['Cache-Control'],'no-store')
                self.assertNotIn('ETag',headers)

    def test_full_friend_deck_is_served_and_retired_faces_are_not(self):
        contents=set()
        for rank in 'a23456789tjqk':
            for suit in 'shdc':
                status,headers,body=self.get('/assets/cards/'+rank+suit+'.webp')
                self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'image/webp')
                self.assertTrue(body.startswith(b'RIFF'));contents.add(hashlib.sha256(body).hexdigest())
        self.assertEqual(len(contents),52)
        for path in ('/assets/cards/As.webp','/assets/cards/10s.webp','/assets/cards/1s.webp','/assets/cards/ax.webp','/assets/cards/as.webp/','/assets/cards/../pieces/dice-1.webp','/assets/cards/%61s.webp','/assets/pieces/card-j.webp','/assets/pieces/card-q.webp','/assets/pieces/card-k.webp'):
            status,headers,_=self.get(path)
            self.assertEqual(status,404,path);self.assertEqual(headers['Cache-Control'],'no-store')

    def test_every_cover_is_served(self):
        for name in COVERS:
            status,headers,body=self.get(f'/assets/covers/{name}.webp')
            self.assertEqual(status,200,name);self.assertEqual(headers['Content-Type'],'image/webp');self.assertTrue(body.startswith(b'RIFF'),name)
    def test_unknown_or_tricky_cover_paths_are_404(self):
        for path in ('/assets/covers/nope.webp','/assets/covers/HOLDEM.webp','/assets/covers/holdem.webp/','/assets/covers/../poker-night.webp','/assets/covers/holdem.png','/assets/covers/%68oldem.webp'):
            self.assertEqual(self.get(path)[0],404,path)
    def test_every_piece_is_served(self):
        self.assertEqual(len(PIECES),15)
        for name in PIECES:
            status,headers,body=self.get(f'/assets/pieces/{name}.webp')
            self.assertEqual(status,200,name);self.assertEqual(headers['Content-Type'],'image/webp');self.assertTrue(body.startswith(b'RIFF'),name)
            self.assertEqual(headers['Cache-Control'],'no-cache',name);self.assertIn('ETag',headers)
            self.assertEqual(self.get(f'/assets/pieces/{name}.webp',{'If-None-Match':headers['ETag']})[0],304,name)
    def test_unknown_or_tricky_piece_paths_are_404(self):
        for path in ('/assets/pieces/nope.webp','/assets/pieces/dice-0.webp','/assets/pieces/dice-7.webp','/assets/pieces/dice-1-256.webp','/assets/pieces/slot-seven.webp',
                     '/assets/pieces/SLOT-777.webp','/assets/pieces/slot-777.webp/','/assets/pieces/slot-777.png','/assets/pieces/%73lot-777.webp','/assets/pieces/',
                     '/assets/pieces/../covers/dice.webp','/assets/pieces/..%2Fcovers%2Fdice.webp','/assets/pieces/%2e%2e/covers/dice.webp','/assets/pieces//slot-777.webp',
                     '/assets/pieces/../../server.py','/assets/pieces/dice-1.webp%00.png',
                     '/assets/pieces/mine-tile-q.webp','/assets/pieces/mine-gem-256.webp','/assets/pieces/mine-gems.webp','/assets/pieces/MINE-GEM.webp','/assets/pieces/mine-.webp','/assets/pieces/mine-bomb.png',
                     '/assets/pieces/card-a.webp','/assets/pieces/card-2.webp','/assets/pieces/card-J.webp','/assets/pieces/CARD-K.webp','/assets/pieces/card-jq.webp','/assets/pieces/card-.webp',
                     '/assets/pieces/card-back-wrong.webp','/assets/pieces/card-k-256.webp','/assets/pieces/card-q.png','/assets/pieces/card-j.webp/','/assets/pieces/%63ard-k.webp','/assets/pieces/../pieces/card-k.webp'):
            self.assertEqual(self.get(path)[0],404,path)
    def test_every_table_piece_is_served(self):
        self.assertEqual(len(TABLE_PIECES),5)
        for name in TABLE_PIECES:
            status,headers,body=self.get(f'/assets/pieces/{name}.webp')
            self.assertEqual(status,200,name);self.assertEqual(headers['Content-Type'],'image/webp');self.assertTrue(body.startswith(b'RIFF'),name)
            self.assertEqual(headers['Cache-Control'],'no-cache',name)
            self.assertEqual(headers['ETag'],'"'+hashlib.sha256(body).hexdigest()+'"',name)
            self.assertEqual(self.get(f'/assets/pieces/{name}.webp',{'If-None-Match':headers['ETag']})[0],304,name)
    def test_unknown_or_tricky_table_piece_paths_are_404(self):
        for path in ('/assets/pieces/roul.webp','/assets/pieces/roul-.webp','/assets/pieces/roul-rim.webp','/assets/pieces/roul-frame-2x.webp','/assets/pieces/ROUL-FRAME.webp',
                     '/assets/pieces/roul-frame.png','/assets/pieces/roul-frame.webp/','/assets/pieces/roul-hubs.webp','/assets/pieces/%72oul-hub.webp',
                     '/assets/pieces/dealer.webp','/assets/pieces/dealer-btn-2.webp','/assets/pieces/Dealer-Btn.webp','/assets/pieces/dealer-btn.webp%00.png',
                     '/assets/pieces/bet-chip.webp','/assets/pieces/bet-chips.png','/assets/pieces/bet-chipss.webp','/assets/pieces//bet-chips.webp',
                     '/assets/pieces/bj-shoe-152.webp','/assets/pieces/BJ-SHOE.webp','/assets/pieces/bj-.webp','/assets/pieces/../pieces/bj-shoe.webp',
                     '/assets/pieces/..%2Fpieces%2Fbj-shoe.webp','/assets/covers/roul-frame.webp','/assets/buttons/bj-shoe.webp','/assets/roul-hub.webp','/assets/dealer-btn.webp'):
            self.assertEqual(self.get(path)[0],404,path)
    def test_every_mahjong_piece_is_served(self):
        self.assertEqual(len(MJ_PIECES),9)
        for name in MJ_PIECES:
            status,headers,body=self.get(f'/assets/pieces/{name}.webp')
            self.assertEqual(status,200,name);self.assertEqual(headers['Content-Type'],'image/webp');self.assertTrue(body.startswith(b'RIFF'),name)
            self.assertEqual(headers['Cache-Control'],'no-cache',name)
            self.assertEqual(headers['ETag'],'"'+hashlib.sha256(body).hexdigest()+'"',name)
            self.assertEqual(self.get(f'/assets/pieces/{name}.webp',{'If-None-Match':headers['ETag']})[0],304,name)
    def test_mahjong_tile_sprite_is_gzipped_and_revalidated(self):
        import gzip,re
        path='/assets/pieces/mj-tiles.svg';original=(Path(server.ROOT)/'static/assets/pieces/mj-tiles.svg').read_bytes()
        status,headers,body=self.get(path,{'Accept-Encoding':'gzip'})
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'image/svg+xml; charset=utf-8')
        self.assertEqual(headers['Content-Encoding'],'gzip');self.assertEqual(headers['Vary'],'Accept-Encoding');self.assertEqual(headers['Cache-Control'],'no-cache')
        self.assertEqual(gzip.decompress(body),original);self.assertLess(len(body),len(original)//3)
        self.assertEqual(self.get(path,{'Accept-Encoding':'gzip','If-None-Match':headers['ETag']})[0],304)
        status,plain,raw=self.get(path)
        self.assertEqual(status,200);self.assertNotIn('Content-Encoding',plain);self.assertEqual(raw,original);self.assertNotEqual(plain['ETag'],headers['ETag'])
        text=original.decode('utf-8')
        # night.css uses the file as a sprite (WebKit ignores SVG fragments in CSS images): one 4300x60 strip,
        # face i at x=i*50 and its small version at x=(43+i)*50, each 48x60, in MJ_CODES order
        self.assertIn('viewBox="0 0 4300 60"',text.split('>',1)[0])
        cells=re.findall(r'<view id="([^"]+)" viewBox="(\d+) 0 48 60"/><g transform="translate\((\d+) 0\)">',text)
        self.assertEqual(cells,[(c,str(i*50),str(i*50)) for i,c in enumerate(MJ_CODES)]+[('s-'+c,str((43+i)*50),str((43+i)*50)) for i,c in enumerate(MJ_CODES)])
        # no external or embedded images, no scripts
        for bad in ('<image','<script','href="http','xlink:href="http','style='):self.assertNotIn(bad,text)
        # the font licence (government open data licence v1) requires attribution; the file keeps it too
        self.assertIn('全字庫正楷體',text);self.assertIn('https://www.cns11643.gov.tw',text)
    def test_mahjong_css_only_uses_served_pieces(self):
        import re
        css=(Path(server.ROOT)/'static/night.css').read_text(encoding='utf-8')
        used=set(re.findall(r'/assets/pieces/(mj-[a-z-]+\.(?:webp|svg))',css))
        self.assertEqual(used,{f'{n}.webp' for n in MJ_PIECES}|{'mj-tiles.svg'})
        for name in used:self.assertEqual(self.get('/assets/pieces/'+name)[0],200,name)
        # every tile key has its sprite cell, and the cell numbers follow the sprite order
        cells=dict(re.findall(r'\.mj-tile\[data-k=([a-z0-9]+)\]\{--mj-i:(\d+);?\}',css))
        self.assertEqual(cells,{c:str(i) for i,c in enumerate(MJ_CODES)})
        # mahjong.js preloads exactly the sprite and the bird (the only face that is all illustration)
        js=(Path(server.ROOT)/'static/ui-art.js').read_text(encoding='utf-8')
        self.assertIn("['/assets/pieces/mj-tiles.svg','/assets/pieces/mj-bird.webp']",js)
    def test_unknown_or_tricky_mahjong_paths_are_404(self):
        for path in ('/assets/pieces/mj-tiles.svgz','/assets/pieces/MJ-TILES.svg','/assets/pieces/mj-tiles.svg/','/assets/pieces/mj-tiles.webp','/assets/pieces/mj-tile.svg',
                     '/assets/pieces/mj-bird.svg','/assets/pieces/mj-bird.png','/assets/pieces/mj-birds.webp','/assets/pieces/mj-f-.webp','/assets/pieces/mj-f-1.webp',
                     '/assets/pieces/mj-f-plum-2x.webp','/assets/pieces/MJ-F-PLUM.webp','/assets/pieces/mj-f-plum.webp%00.png','/assets/pieces/%6dj-bird.webp',
                     '/assets/pieces/../pieces/mj-tiles.svg','/assets/pieces/..%2Fpieces%2Fmj-tiles.svg','/assets/pieces//mj-tiles.svg','/static/assets/pieces/mj-tiles.svg',
                     '/assets/mj-tiles.svg','/assets/covers/mj-bird.webp','/assets/buttons/mj-f-plum.webp','/mj-tiles.svg'):
            status,headers,_=self.get(path,{'Accept-Encoding':'gzip'})
            self.assertEqual(status,404,path);self.assertNotIn('ETag',headers);self.assertNotIn('Content-Encoding',headers)
    def test_every_button_image_is_served(self):
        self.assertEqual(len(BUTTONS),11)
        for name in BUTTONS:
            status,headers,body=self.get(f'/assets/buttons/{name}.webp')
            self.assertEqual(status,200,name);self.assertEqual(headers['Content-Type'],'image/webp');self.assertTrue(body.startswith(b'RIFF'),name)
            self.assertEqual(headers['Cache-Control'],'no-cache',name);self.assertIn('ETag',headers)
            # ETag is the content hash, the same way pieces and covers are tagged
            self.assertEqual(headers['ETag'],'"'+hashlib.sha256(body).hexdigest()+'"',name)
            status,_,again=self.get(f'/assets/buttons/{name}.webp',{'If-None-Match':headers['ETag']})
            self.assertEqual(status,304,name);self.assertEqual(again,b'',name)
            self.assertEqual(self.get(f'/assets/buttons/{name}.webp',{'If-None-Match':'"stale"'})[0],200,name)
    def test_unknown_or_tricky_button_paths_are_404(self):
        for path in ('/assets/buttons/nope.webp','/assets/buttons/btn-primary.webp','/assets/buttons/btn-primary-sm.webp','/assets/buttons/btn-primary-x.webp',
                     '/assets/buttons/btn-primary-lm.webp','/assets/buttons/btn-tertiary-l.webp','/assets/buttons/btn-primary-sm-l-256.webp',
                     '/assets/buttons/BTN-PRIMARY-L.webp','/assets/buttons/coin.png','/assets/buttons/coin.webp/','/assets/buttons/coins.webp','/assets/buttons/coin-pressed.webp',
                     '/assets/buttons/chip-5.webp','/assets/buttons/chip-1000.webp','/assets/buttons/chip-.webp','/assets/buttons/chip-10.png','/assets/buttons/CHIP-10.webp',
                     '/assets/buttons/%63oin.webp','/assets/buttons/','/assets/buttons//coin.webp','/assets/buttons/../pieces/dice-1.webp',
                     '/assets/buttons/..%2Fpieces%2Fdice-1.webp','/assets/buttons/%2e%2e/covers/dice.webp','/assets/buttons/../../server.py','/assets/buttons/coin.webp%00.png',
                     '/assets/pieces/coin.webp','/assets/covers/chip-10.webp','/assets/chip-10.webp'):
            self.assertEqual(self.get(path)[0],404,path)
    def test_every_batch2_button_image_is_served(self):
        # P22 batch 2: secondary plaques (full and narrow), the narrow danger plaque, tab pills and the two gold frames
        self.assertEqual(len(BUTTONS2),17);self.assertEqual(len(set(BUTTONS2)&set(BUTTONS)),0)
        for name in BUTTONS2:
            status,headers,body=self.get(f'/assets/buttons/{name}.webp')
            self.assertEqual(status,200,name);self.assertEqual(headers['Content-Type'],'image/webp');self.assertTrue(body.startswith(b'RIFF'),name)
            self.assertEqual(headers['Cache-Control'],'no-cache',name)
            self.assertEqual(headers['ETag'],'"'+hashlib.sha256(body).hexdigest()+'"',name)
            status,_,again=self.get(f'/assets/buttons/{name}.webp',{'If-None-Match':headers['ETag']})
            self.assertEqual(status,304,name);self.assertEqual(again,b'',name)
            self.assertEqual(self.get(f'/assets/buttons/{name}.webp',{'If-None-Match':'"stale"'})[0],200,name)
    def test_unknown_or_tricky_batch2_button_paths_are_404(self):
        for path in ('/assets/buttons/btn-secondary.webp','/assets/buttons/btn-secondary-sm.webp','/assets/buttons/btn-secondary-x.webp','/assets/buttons/btn-secondary-lm.webp',
                     '/assets/buttons/btn-secondary-pressed.webp','/assets/buttons/btn-secondary-disabled.webp','/assets/buttons/btn-secondary-sm-l-256.webp','/assets/buttons/BTN-SECONDARY-L.webp',
                     '/assets/buttons/btn-danger.webp','/assets/buttons/btn-danger-sm.webp','/assets/buttons/btn-danger-l.webp','/assets/buttons/btn-danger-m.webp','/assets/buttons/btn-danger-r.webp','/assets/buttons/btn-danger-sm-x.webp','/assets/buttons/btn-danger-l.png','/assets/buttons/btn-dangers-l.webp',
                     '/assets/buttons/btn-tab-on-l.webp','/assets/buttons/tab-on.webp','/assets/buttons/tab-off.webp','/assets/buttons/tab-on-x.webp','/assets/buttons/tab-sm-l.webp',
                     '/assets/buttons/tab-on-sm-l.webp','/assets/buttons/tab-off-l.png','/assets/buttons/TAB-ON-L.webp','/assets/buttons/tab-on-l.webp/','/assets/buttons/%74ab-on-l.webp',
                     '/assets/buttons/frame.webp','/assets/buttons/frame-tables.webp','/assets/buttons/frame-card-l.webp','/assets/buttons/frame-deco.webp','/assets/buttons/frame-table.png',
                     '/assets/buttons/FRAME-CARD.webp','/assets/buttons/frame-card.webp%00.png','/assets/buttons/../buttons/frame-card.webp','/assets/buttons/..%2Fbuttons%2Ftab-on-l.webp',
                     '/assets/buttons//tab-off-r.webp','/assets/pieces/frame-table.webp','/assets/covers/tab-on-l.webp','/assets/frame-card.webp','/assets/tab-off-m.webp'):
            self.assertEqual(self.get(path)[0],404,path)
    def test_images_revalidate_with_etag(self):
        status,headers,body=self.get('/assets/covers/holdem.webp')
        self.assertEqual(status,200);self.assertEqual(headers['Cache-Control'],'no-cache');etag=headers['ETag']
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
