"""Loopback-only application server; no credentials and no disk data writes."""
import argparse
from functools import lru_cache
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
import webbrowser

from .feed import PublicFeed, SyntheticFeed
from .service import DashboardService

STATIC = Path(__file__).parent/'static'


@lru_cache(maxsize=2)
def offline_report(name):
    if name == 'm102':
        from btc5_v3.research_adapter.offline_demo import fixtures, render
        from btc5_v3.research_adapter.target_semantics import adapt_offline, seal_offline
        envelope = seal_offline(fixtures())
        return render(adapt_offline(envelope, expected_root=envelope['root_hash']))
    from btc5_v3.target_semantics.demo import build_report
    body = escape(json.dumps(build_report(), ensure_ascii=False, indent=2))
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<title>M9.2 离线目标语义研究</title><style>body{font:16px system-ui;max-width:1100px;'
        'margin:40px auto;padding:24px;background:#101b2a;color:#d6e5ef}pre{white-space:pre-wrap;'
        'overflow-wrap:anywhere}a{color:#7dd3fc}</style><a href="/">返回 Dashboard</a>'
        '<h1>M9.2 · 离线目标语义研究</h1><p>SYNTHETIC_TEST · REAL_DATA_NOT_READY</p>'
        '<p>以下为原有模块实时重建的固定合成报告，不读取任何真实 sealed evidence，'
        '概率不是当前 BTC 的方向预测。</p><pre>'+body+'</pre></html>')


def make_server(service, root, port=8765):
    root = Path(root)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body, content_type, status=200):
            data = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.headers.get('Host', '').split(':')[0] not in ('127.0.0.1', 'localhost'):
                self.send('Invalid host', 'text/plain', 403)
                return
            path = urlsplit(self.path).path
            if path == '/api/state':
                self.send(json.dumps(service.snapshot(), allow_nan=False), 'application/json; charset=utf-8')
            elif path in ('/', '/static/app.js', '/static/app.css', '/static/decision.css'):
                name, mime = {'/': ('index.html', 'text/html'),
                              '/static/app.js': ('app.js', 'text/javascript'),
                              '/static/app.css': ('app.css', 'text/css'),
                              '/static/decision.css': ('decision.css', 'text/css')}[path]
                self.send((STATIC/name).read_bytes(), mime+'; charset=utf-8')
            elif path in ('/reports/m92', '/reports/m102'):
                self.send(offline_report(path.rsplit('/', 1)[1]), 'text/html; charset=utf-8')
            elif path == '/docs/methods':
                body = escape((root/'docs/REALTIME_DASHBOARD.md').read_text(encoding='utf-8'))
                self.send('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                    '<title>Dashboard 使用说明</title><style>body{max-width:1000px;margin:40px auto;'
                    'font:16px system-ui;padding:20px}pre{white-space:pre-wrap}</style>'
                    '<a href="/">返回 Dashboard</a><pre>'+body+'</pre></html>', 'text/html; charset=utf-8')
            else:
                self.send('Not found', 'text/plain', 404)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main(root):
    parser = argparse.ArgumentParser(description='BTC 5m Realtime Research Dashboard v1.0')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--demo', action='store_true', help='Explicit offline synthetic UI demo')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    service = DashboardService(SyntheticFeed() if args.demo else PublicFeed())
    try:
        server = make_server(service, root, args.port)
    except OSError:
        parser.exit(1, 'Port unavailable. Close the previous Dashboard or choose --port 8766.\n')
    url = f'http://127.0.0.1:{args.port}'
    print(f'BTC 5m Realtime Research Dashboard v1.0\n{url}\nMode: {service.feed.mode}\n'
          'REAL_DATA_NOT_READY / TARGET_MISMATCH\nPress Ctrl+C to stop.', flush=True)
    service.start()
    if not args.no_browser:
        timer = threading.Timer(0.7, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        server.server_close()
