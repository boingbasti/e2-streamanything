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
_GETLATEST = "https://webtvfc.feratel.com/webtv/?cam=%s&getlatest=1"


def _dbg(msg):
    if not os.path.exists("/tmp/sa_debug"):
        return
    try:
        import time
        with open("/tmp/streamanything.log", "a") as f:
            f.write("[%.3f] [Feratel] %s\n" % (time.time(), msg))
    except Exception:
        pass


def is_feratel(url):
    return bool(re.search(r'https?://(www\.)?feratel\.com/', url, re.IGNORECASE))


def resolve(url):
    _dbg("resolve start url=%s" % url)
    cam_id = _get_cam_id(url)
    if not cam_id:
        _dbg("keine cam_id gefunden")
        return None
    try:
        req  = _urlreq.Request(_GETLATEST % cam_id, headers={"User-Agent": _UA})
        resp = _urlreq.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", "replace")
        m = re.search(r'<source\s+src="(https://[^"]+\.mp4[^"]*)"', html)
        if not m:
            _dbg("keine MP4-URL in getlatest-Antwort")
            return None
        mp4_url = m.group(1)
        _dbg("cam=%s url=%s" % (cam_id, mp4_url))
        return mp4_url
    except Exception as e:
        _dbg("resolve Fehler: %s" % e)
        return None


def _get_cam_id(url):
    try:
        req  = _urlreq.Request(url, headers={"User-Agent": _UA})
        resp = _urlreq.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", "replace")
        m = re.search(r'[?&]cam=(\d+)', html)
        if m:
            _dbg("cam_id via cam-param: %s" % m.group(1))
            return m.group(1)
        m = re.search(r'wtvpict\.feratel\.com/picture/\d+/(\d+)\.jpeg', html)
        if m:
            _dbg("cam_id via picture-url: %s" % m.group(1))
            return m.group(1)
        _dbg("cam_id nicht gefunden in html")
    except Exception as e:
        _dbg("cam_id Fehler: %s" % e)
    return None
