# -*- coding: utf-8 -*-
# YouTube-Live-Stream-Aufloesung ueber die InnerTube-API.
# Basiert auf dem Ansatz aus enigma2-plugin-extensions-youtube (GPL2, Taapat)
# https://github.com/Taapat/enigma2-plugin-youtube
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

_VERSION = "21.08.266"
_UA      = "com.google.android.youtube/%s (Linux; U; Android 11) gzip" % _VERSION


def is_youtube(url):
    return bool(re.search(r'(?:youtube\.com/watch|youtu\.be/)', url))


def resolve(url, best_quality=True):
    m = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})', url)
    if not m:
        return None
    vid = m.group(1)
    data = json.dumps({
        "videoId": vid,
        "playbackContext": {"contentPlaybackContext": {"html5Preference": "HTML5_PREF_WANTS"}},
        "params": "2AMB",
        "context": {"client": {
            "hl": "de",
            "clientName": "ANDROID",
            "clientVersion": _VERSION,
            "androidSdkVersion": 30,
            "osName": "Android",
            "osVersion": "11",
            "userAgent": _UA
        }}
    }).encode("utf-8")
    try:
        req = _urlreq.Request(
            "https://www.youtube.com/youtubei/v1/player?prettyPrint=false",
            data=data,
            headers={
                "content-type": "application/json",
                "Origin": "https://www.youtube.com",
                "X-YouTube-Client-Name": "3",
                "X-YouTube-Client-Version": _VERSION,
                "User-Agent": _UA,
            }
        )
        resp = _urlreq.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        if result.get("videoDetails", {}).get("videoId") != vid:
            return None
        manifest_url = result.get("streamingData", {}).get("hlsManifestUrl")
        if not manifest_url:
            return None
        if not best_quality:
            return manifest_url
        best = _best_from_manifest(manifest_url)
        return best or manifest_url
    except Exception as e:
        print("[YouTube] resolve fehler: %s" % e)
        return None


def _best_from_manifest(manifest_url):
    try:
        resp = _urlreq.urlopen(manifest_url, timeout=10)
        manifest = resp.read().decode("utf-8", "replace")
        best_bw  = -1
        best_url = None
        lines = manifest.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:"):
                m = re.search(r'BANDWIDTH=(\d+)', line)
                if m and i + 1 < len(lines):
                    candidate = lines[i + 1].strip()
                    if candidate and not candidate.startswith("#"):
                        bw = int(m.group(1))
                        if bw > best_bw:
                            best_bw  = bw
                            best_url = candidate
        if best_url:
            print("[YouTube] beste Qualitaet: %d bps" % best_bw)
        return best_url
    except Exception as e:
        print("[YouTube] manifest fehler: %s" % e)
        return None
