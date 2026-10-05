"""Serve the offline coach desk on this laptop only; no third-party packages."""
import argparse
import functools
import http.server
import webbrowser
from pathlib import Path
from check_setup import check

ROOT = Path(__file__).resolve().parents[1]

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        super().end_headers()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        check(ROOT)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Coach desk cannot start: {error}\n')
    # MSYS Python can have a minimal MIME database. Set module MIME explicitly.
    Handler.extensions_map = {**Handler.extensions_map, '.js': 'text/javascript', '.json': 'application/json', '.css': 'text/css'}
    handler = functools.partial(Handler, directory=str(ROOT / 'gui'))
    with http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
        url = f'http://127.0.0.1:{server.server_port}'
        print(f'Coach desk: {url}\nKeep this window open. Press Ctrl+C to stop.', flush=True)
        if not args.no_browser: webbrowser.open(url)
        try: server.serve_forever()
        except KeyboardInterrupt: pass

if __name__ == '__main__': main()
