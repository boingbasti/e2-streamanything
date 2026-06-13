# -*- coding: utf-8 -*-
import os
import re
import threading

try:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

try:
    import urllib2 as _urlreq
except ImportError:
    import urllib.request as _urlreq

try:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
except ImportError:
    from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    from SocketServer import ThreadingMixIn
except ImportError:
    from socketserver import ThreadingMixIn

_UA      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_REF     = "https://www.earthcam.com/"
_STREAM_RE = re.compile(r'"stream"\s*:\s*"(https?:\\/\\/[^"]+\.m3u8[^"]*)"')


def _dbg(msg):
    if not os.path.exists("/tmp/sa_debug"):
        return
    try:
        import time
        with open("/tmp/streamanything.log", "a") as f:
            f.write("[%.3f] [EarthCam] %s\n" % (time.time(), msg))
    except Exception:
        pass


def is_earthcam(url):
    return bool(re.search(r'https?://(www\.)?earthcam\.com/', url, re.IGNORECASE))


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _build_proxy(master_url):
    base = master_url.split("?")[0].rsplit("/", 1)[0] + "/"

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.lstrip("/")
            target = master_url if path == "live.m3u8" else base + path
            _dbg("proxy %s -> %s" % (self.path[:60], target[:80]))
            try:
                req  = _urlreq.Request(target, headers={"User-Agent": _UA, "Referer": _REF})
                resp = _urlreq.urlopen(req, timeout=15)
                data = resp.read()
                ct   = resp.headers.get("Content-Type", "application/octet-stream")
                if "mpegurl" in ct or path.endswith(".m3u8") or path == "live.m3u8":
                    text = data.decode("utf-8", "replace")
                    out  = []
                    for line in text.splitlines():
                        s = line.strip()
                        if s and not s.startswith("#") and not s.startswith("http"):
                            line = "/" + s
                        out.append(line)
                    data = "\n".join(out).encode("utf-8")
                    ct   = "application/vnd.apple.mpegurl"
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                _dbg("proxy error: %s" % e)
                self.send_response(502)
                self.end_headers()

        def log_message(self, *a):
            pass

    try:
        server = _ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port   = server.server_address[1]
        t      = threading.Thread(target=server.serve_forever)
        t.daemon = True
        t.start()
        _dbg("proxy listening port=%d" % port)
        return "http://127.0.0.1:%d/live.m3u8" % port
    except Exception as e:
        _dbg("proxy start failed: %s" % e)
        return None


def resolve(url):
    _dbg("resolve start url=%s" % url)
    try:
        req  = _urlreq.Request(url, headers={"User-Agent": _UA})
        resp = _urlreq.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", "replace")
        _dbg("page fetched len=%d" % len(html))
        m = _STREAM_RE.search(html)
        if not m:
            _dbg("kein stream-Feld gefunden")
            return None
        stream_url = m.group(1).replace("\\/", "/")
        _dbg("stream_url=%s" % stream_url)
        local = _build_proxy(stream_url)
        if local:
            return local
        _dbg("proxy fehlgeschlagen, fallback mit Referer")
        return stream_url + "|Referer=" + _REF
    except Exception as e:
        _dbg("resolve exception: %s" % e)
    return None
