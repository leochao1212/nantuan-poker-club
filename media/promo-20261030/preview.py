"""Local-only film preview. Exposes only the completed MP4, never project files."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

movie=Path(__file__).resolve().parents[2]/'artifacts/promo-20261030/nantuan-friends-30s.mp4'
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/':
            data='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>楠團牌室｜30 秒宣傳影片</title><style>body{margin:0;background:#102b23;color:#f5eedb;font:16px system-ui;display:grid;place-items:center;min-height:100vh}main{width:min(1200px,94vw)}video{width:100%;border-radius:16px}h1{font-size:24px}p{color:#c9d4c8}</style><main><h1>今晚，差你一個。</h1><video controls autoplay muted playsinline src="/promo.mp4"></video><p>楠團牌室 · 30 秒 · 1080p · 原創配樂（可開啟聲音）</p></main></html>'''.encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        elif self.path=='/promo.mp4':
            size=movie.stat().st_size;start=0;end=size-1
            if self.headers.get('Range','').startswith('bytes='):
                a,b=self.headers['Range'][6:].split('-',1);start=int(a or 0);end=min(int(b) if b else end,end)
                if start>end:self.send_error(416);return
                self.send_response(206);self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            else:self.send_response(200)
            self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.end_headers()
            try:
                with movie.open('rb') as f:
                    f.seek(start);remaining=end-start+1
                    while remaining:
                        block=f.read(min(65536,remaining))
                        if not block:break
                        self.wfile.write(block);remaining-=len(block)
            except (BrokenPipeError,ConnectionResetError):pass
        else:self.send_error(404)

if __name__=='__main__':ThreadingHTTPServer(('127.0.0.1',8880),Handler).serve_forever()
