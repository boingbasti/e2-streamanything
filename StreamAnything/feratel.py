# -*- coding: utf-8 -*-
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

_UA       = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_GETLATEST = "https://webtvfc.feratel.com/webtv/?cam=%s&getlatest=1"


def is_feratel(url):
    return bool(re.search(r'https?://(www\.)?feratel\.com/', url, re.IGNORECASE))


def resolve(url):
    cam_id = _get_cam_id(url)
    if not cam_id:
        print("[Feratel] Keine cam_id gefunden fuer: %s" % url)
        return None
    try:
        req  = _urlreq.Request(_GETLATEST % cam_id, headers={"User-Agent": _UA})
        resp = _urlreq.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", "replace")
        m = re.search(r'<source\s+src="(https://[^"]+\.mp4[^"]*)"', html)
        if not m:
            print("[Feratel] Keine MP4-URL in getlatest-Antwort")
            return None
        mp4_url = m.group(1)
        print("[Feratel] cam=%s url=%s" % (cam_id, mp4_url))
        return mp4_url
    except Exception as e:
        print("[Feratel] resolve Fehler: %s" % e)
        return None


def _get_cam_id(url):
    try:
        req  = _urlreq.Request(url, headers={"User-Agent": _UA})
        resp = _urlreq.urlopen(req, timeout=10)
        html = resp.read().decode("utf-8", "replace")
        m = re.search(r'[?&]cam=(\d+)', html)
        if m:
            return m.group(1)
        m = re.search(r'wtvpict\.feratel\.com/picture/\d+/(\d+)\.jpeg', html)
        if m:
            return m.group(1)
    except Exception as e:
        print("[Feratel] cam_id Fehler: %s" % e)
    return None
