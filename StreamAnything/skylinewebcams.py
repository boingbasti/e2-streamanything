# -*- coding: utf-8 -*-
import os
import re

try:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

try:
    import urllib2 as _urlreq
except ImportError:
    import urllib.request as _urlreq

_UA        = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_BASE_URL  = "https://hd-auth.skylinewebcams.com/"
_SOURCE_RE = re.compile(r"""(?:url|source)\s*:\s*['"]livee(\.m3u8\?a=\w+)['"]""")
_YT_RE     = re.compile(r"""YT\.Player\('live'.*?videoId:\s*'([^']+)'""", re.DOTALL)


def _dbg(msg):
    if not os.path.exists("/tmp/sa_debug"):
        return
    try:
        import time
        with open("/tmp/streamanything.log", "a") as f:
            f.write("[%.3f] [SkylineWebcams] %s\n" % (time.time(), msg))
    except Exception:
        pass


def is_skylinewebcams(url):
    return bool(re.search(r'https?://(www\.)?skylinewebcams\.com/', url, re.IGNORECASE))


def resolve(url):
    _dbg("resolve start url=%s" % url)
    try:
        req  = _urlreq.Request(url, headers={"User-Agent": _UA})
        resp = _urlreq.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", "replace")
        _dbg("page fetched len=%d" % len(html))
        m = _SOURCE_RE.search(html)
        if m:
            stream_url = _BASE_URL + "live" + m.group(1)
            _dbg("HLS resolved=%s" % stream_url)
            return stream_url
        m = _YT_RE.search(html)
        if m:
            yt_url = "https://www.youtube.com/watch?v=" + m.group(1)
            _dbg("YouTube fallback=%s" % yt_url)
            return yt_url
        _dbg("no stream URL found in page")
        _dbg("page snippet=%s" % html[html.find("source"):html.find("source")+200] if "source" in html else "no 'source' in html")
    except Exception as e:
        _dbg("resolve exception: %s" % e)
    return None
