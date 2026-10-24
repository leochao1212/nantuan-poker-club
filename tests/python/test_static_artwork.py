"""Public artwork can be revalidated without caching private game/account data."""
import hashlib
import urllib.error
import urllib.request

from .test_app import ServerTestCase


class ArtworkCaching(ServerTestCase):
    def fetch(self,path,headers=None):
        request=urllib.request.Request(self.base+path,headers=headers or {})
        try:
            response=urllib.request.urlopen(request,timeout=5)
        except urllib.error.HTTPError as error:
            response=error
        with response:
            return response.status,response.headers,response.read()

    def test_artwork_revalidates_exact_bytes_without_stale_content(self):
        paths=['/assets/poker-night.webp']
        paths += [f'/assets/clubhouse/tier-{tier}{suffix}.webp' for tier in range(1,5) for suffix in ('','-small')]
        paths += [f'/assets/covers/{game}.webp' for game in ('holdem','big2','blackjack','roulette','baccarat','slot','mines','dice','tower','inbetween','mahjong')]
        for path in paths:
            with self.subTest(path=path):
                status,headers,body=self.fetch(path)
                self.assertEqual(status,200)
                self.assertEqual(headers['Content-Type'],'image/webp')
                self.assertGreater(len(body),100)
                etag='"'+hashlib.sha256(body).hexdigest()+'"'
                self.assertEqual(headers['ETag'],etag)
                self.assertEqual(headers['Cache-Control'],'public, max-age=0, must-revalidate')
                status,cached,empty=self.fetch(path,{'If-None-Match':'W/'+etag})
                self.assertEqual(status,304)
                self.assertEqual(empty,b'')
                self.assertEqual(cached['ETag'],etag)
                self.assertNotIn('Content-Length',cached)
                status,_,fresh=self.fetch(path,{'If-None-Match':'"previous-artwork"'})
                self.assertEqual(status,200)
                self.assertEqual(fresh,body)

    def test_documents_private_api_and_unknown_images_remain_uncacheable(self):
        for path,expected in [('/',200),('/api/bootstrap',200),('/api/state',401),
                              ('/assets/covers/missing.webp',404),('/assets/covers/../server.py',404)]:
            with self.subTest(path=path):
                status,headers,_=self.fetch(path,{'If-None-Match':'*'})
                self.assertEqual(status,expected)
                self.assertEqual(headers['Cache-Control'],'no-store')
                self.assertNotIn('ETag',headers)
