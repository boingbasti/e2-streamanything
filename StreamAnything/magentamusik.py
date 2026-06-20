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

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_ASSETDETAILS_URL = "https://wcps.t-online.de/cvss/magentamusic/vodclient/v2/assetdetails/58938/%s"
_PLAYER_URL_RE    = re.compile(r'"player"\s*:\s*\{\s*"href"\s*:\s*"([^"]+)"')
_ASSETID_RE       = re.compile(r'"assetId"\s*:\s*"(DMM_MOVIE_[0-9]+)"')
_MEDIA_HREF_RE    = re.compile(r'"href"\s*:\s*"(https://wcps\.t-online\.de/cmrs/[^"]+)"')
_SMIL_SRC_RE      = re.compile(r'<media[^>]+src="([^"]+)"')


def _dbg(msg):
    if not os.path.exists("/tmp/sa_debug"):
        return
    try:
        import time
        with open("/tmp/streamanything.log", "a") as f:
            f.write("[%.3f] [MagentaMusik] %s\n" % (time.time(), msg))
    except Exception:
        pass


def is_magentamusik(url):
    return bool(re.search(r'https?://(www\.)?magentamusik\.de/', url, re.IGNORECASE))


def _fetch(url):
    req  = _urlreq.Request(url, headers={"User-Agent": _UA})
    resp = _urlreq.urlopen(req, timeout=10)
    return resp.read().decode("utf-8", "replace")


def resolve(url):
    _dbg("resolve start url=%s" % url)
    try:
        html = _fetch(url)
        m = _ASSETID_RE.search(html)
        if not m:
            _dbg("keine assetId auf Seite gefunden")
            return None
        asset_id = m.group(1)
        _dbg("assetId=%s" % asset_id)

        details_json = _fetch(_ASSETDETAILS_URL % asset_id)
        m = _PLAYER_URL_RE.search(details_json)
        if not m:
            _dbg("keine player-href in assetdetails")
            return None
        player_url = m.group(1).replace("\\/", "/")
        _dbg("player_url=%s" % player_url)

        player_json = _fetch(player_url)
        m = _MEDIA_HREF_RE.search(player_json)
        if not m:
            _dbg("keine media-href im player-json")
            return None
        media_url = m.group(1).replace("\\/", "/")
        _dbg("media_url=%s" % media_url)

        smil = _fetch(media_url)
        m = _SMIL_SRC_RE.search(smil)
        if not m:
            _dbg("keine src im SMIL")
            return None
        stream_url = m.group(1)
        _dbg("resolved stream_url=%s" % stream_url)
        return stream_url
    except Exception as e:
        _dbg("resolve Fehler: %s" % e)
        return None
