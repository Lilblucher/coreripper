"""
Dev-only static file server  identical to `python3 -m http.server` except it
adds Cache-Control: no-store to every response. Plain http.server sends no
cache headers at all, so browsers apply their own (often aggressive) default
caching, which repeatedly served stale HTML during manual browser testing in
this project (edits on disk not reflected without a hard refresh). Not meant
for production  this project's static files are served by a real webserver
there; this is purely to make local iteration match what's on disk.
"""
import http.server
import sys


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    http.server.test(HandlerClass=NoCacheHandler, port=port)
