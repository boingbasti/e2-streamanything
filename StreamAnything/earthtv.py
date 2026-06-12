# -*- coding: utf-8 -*-
import os
import re
import json

try:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

try:
    import urllib2 as _urlreq
except ImportError:
    import urllib.request as _urlreq

_UA         = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_API_URL    = "https://livecloud.earthtv.com/api/v1/media.getPlayerConfig?playerToken=%s"
_TOKEN_RE   = re.compile(r'<etv-player\b[^>]+\btoken="([^"]+)"')


def _dbg(msg):
    if not os.path.exists("/tmp/sa_debug"):
        return
    try:
        import time
        with open("/tmp/streamanything.log", "a") as f:
            f.write("[%.3f] [EarthTV] %s\n" % (time.time(), msg))
    except Exception:
        pass


def is_earthtv(url):
    return bool(re.search(r'https?://(www\.)?earthtv\.com/[^/]+/webcam/', url, re.IGNORECASE))


def resolve(url):
    _dbg("resolve start url=%s" % url)
    if "/live-stream" not in url:
        url = url.rstrip("/") + "/live-stream"
        _dbg("appended /live-stream: %s" % url)
    try:
        req  = _urlreq.Request(url, headers={"User-Agent": _UA})
        resp = _urlreq.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", "replace")
        _dbg("page fetched len=%d" % len(html))
        m = _TOKEN_RE.search(html)
        if not m:
            _dbg("kein etv-player token gefunden")
            return None
        token = m.group(1)
        _dbg("token=%s" % token[:30])
        req2  = _urlreq.Request(_API_URL % token, headers={"User-Agent": _UA})
        resp2 = _urlreq.urlopen(req2, timeout=10)
        data  = json.loads(resp2.read().decode("utf-8", "replace"))
        hls   = data.get("streamUris", {}).get("hls")
        if hls:
            _dbg("HLS resolved=%s" % hls)
            return hls
        _dbg("kein streamUris.hls in API-Antwort")
    except Exception as e:
        _dbg("resolve exception: %s" % e)
    return None
