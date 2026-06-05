# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os

from enigma import eServiceReference

try:
    from Screens.MoviePlayer import MoviePlayer
except ImportError:
    from Screens.InfoBar import MoviePlayer


class SAStreamPlayer(MoviePlayer):
    def __init__(self, session, service, streams=None, stream_index=0,
                 autoconfigure_serviceapp=True, prefer_best_quality=True):
        MoviePlayer.__init__(self, session, service)
        self.skinName = ["MoviePlayer", "InfoBar"]
        self._streams             = streams or []
        self._stream_index        = stream_index
        self._autoconfigure       = autoconfigure_serviceapp
        self._prefer_best_quality = prefer_best_quality
        if len(self._streams) > 1:
            from Components.ActionMap import ActionMap
            self["_sa_nav"] = ActionMap(
                [b"ChannelSelectBaseActions"],
                {
                    b"nextBouquet": lambda: self._switch_stream(1),
                    b"prevBouquet": lambda: self._switch_stream(-1),
                },
                -1,
            )

    def _switch_stream(self, direction):
        new_idx = self._stream_index + direction
        while 0 <= new_idx < len(self._streams):
            if self._streams[new_idx].get("type") != "folder":
                break
            new_idx += direction
        if new_idx < 0 or new_idx >= len(self._streams):
            return
        item       = self._streams[new_idx]
        url        = item.get("url", "")
        name       = item.get("name", "Stream")
        player     = item.get("player", "")
        user_agent = item.get("user_agent", "")
        hls_fix    = item.get("hls_audio_fix", False)
        if not url:
            return
        try:
            import youtube as _yt
            if _yt.is_youtube(url):
                resolved = _yt.resolve(url, best_quality=self._prefer_best_quality)
                if resolved:
                    url = resolved
        except Exception:
            pass
        try:
            import feratel as _ft
            if _ft.is_feratel(url):
                resolved = _ft.resolve(url)
                if resolved:
                    url = resolved
        except Exception:
            pass
        ref = _build_ref(url, name, player, user_agent,
                         self._autoconfigure, self._prefer_best_quality,
                         hls_audio_fix=hls_fix)
        self._stream_index = new_idx
        self.session.nav.playService(ref)

    def leavePlayer(self):
        self.close()

    def doEofInternal(self, playing):
        self.close()

    def showResumePoint(self):
        pass


def _has_serviceapp():
    return os.path.exists("/usr/lib/enigma2/python/Plugins/SystemPlugins/ServiceApp")


def _has_new_exteplayer3():
    # exteplayer3 >= v181 (feedplus/manuell) bringt eigene Libs in /usr/lib/exteplayer3_deps/
    return os.path.isdir("/usr/lib/exteplayer3_deps")


def _resolve_hls_best_variant(url, user_agent=""):
    if not url.lower().split("?")[0].endswith(".m3u8"):
        return url
    try:
        try:
            from urllib2 import urlopen, Request
        except ImportError:
            from urllib.request import urlopen, Request
        import re
        headers = {"User-Agent": user_agent or "Mozilla/5.0"}
        req = Request(url, headers=headers)
        resp = urlopen(req, timeout=8)
        effective_url = resp.geturl()
        content = resp.read().decode("utf-8", "replace")
        if "#EXT-X-STREAM-INF" not in content:
            return url
        best_bw, best_url = -1, None
        lines = content.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:"):
                m = re.search(r"BANDWIDTH=(\d+)", line)
                if m and i + 1 < len(lines):
                    candidate = lines[i + 1].strip()
                    if candidate and not candidate.startswith("#"):
                        bw = int(m.group(1))
                        if bw > best_bw:
                            best_bw, best_url = bw, candidate
        if best_url:
            if not best_url.startswith("http"):
                try:
                    from urlparse import urljoin
                except ImportError:
                    from urllib.parse import urljoin
                best_url = urljoin(effective_url, best_url)
            return best_url
    except Exception:
        pass
    return url


def _build_local_playlist(master_url, user_agent=""):
    if not master_url.lower().split("?")[0].endswith(".m3u8"):
        return None
    try:
        try:
            from urllib2 import urlopen, Request as _Req
            from urlparse import urljoin as _urljoin
        except ImportError:
            from urllib.request import urlopen, Request as _Req
            from urllib.parse import urljoin as _urljoin
        import re
        import threading
        try:
            from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
        except ImportError:
            from http.server import HTTPServer, BaseHTTPRequestHandler

        headers = {"User-Agent": user_agent or "Mozilla/5.0"}
        req = _Req(master_url, headers=headers)
        resp = urlopen(req, timeout=8)
        effective_url = resp.geturl()
        content = resp.read().decode("utf-8", "replace")
        lines = content.splitlines()

        if "#EXT-X-STREAM-INF" not in content:
            return None

        best_bw, best_inf, best_url = -1, None, None
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("#EXT-X-STREAM-INF"):
                m = re.search(r"BANDWIDTH=(\d+)", line)
                bw = int(m.group(1)) if m else 0
                for j in range(i + 1, len(lines)):
                    v = lines[j].strip()
                    if v and not v.startswith("#"):
                        if bw > best_bw:
                            best_bw = bw
                            best_inf = line
                            best_url = _urljoin(effective_url, v)
                        break
            i += 1

        if not best_url:
            return None

        out = ["#EXTM3U", "#EXT-X-VERSION:4", "#EXT-X-INDEPENDENT-SEGMENTS", ""]
        for line in lines:
            if line.startswith("#EXT-X-MEDIA"):
                line = re.sub(
                    r'URI="([^"]+)"',
                    lambda m: 'URI="' + _urljoin(effective_url, m.group(1)) + '"',
                    line
                )
                out.append(line)
        out.extend(["", best_inf, best_url, ""])
        data = "\n".join(out).encode("utf-8")

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        port = server.server_address[1]
        t = threading.Thread(target=lambda: (server.handle_request(), server.server_close()))
        t.daemon = True
        t.start()
        return "http://127.0.0.1:%d/live.m3u8" % port
    except Exception:
        return None


def _configure_serviceapp_for_live():
    try:
        from Components.config import config
        from Plugins.SystemPlugins.ServiceApp.serviceapp_client import (
            setExtEplayer3Settings, setServiceAppSettings, OPTIONS_SERVICEEXTEPLAYER3
        )
        key  = "serviceexteplayer3"
        opts = config.plugins.serviceapp.options[key]
        ext3 = config.plugins.serviceapp.exteplayer3[key]

        if not ext3.downmix.value:
            ext3.downmix.value = True; ext3.downmix.save()

        if _has_new_exteplayer3():
            # v181+: exteplayer3 parst Master-Playlist selbst → HLS-Explorer deaktivieren
            if opts.hls_explorer.value:
                opts.hls_explorer.value = False; opts.hls_explorer.save()
            if not opts.autoselect_stream.value:
                opts.autoselect_stream.value = True; opts.autoselect_stream.save()
        else:
            # Alte exteplayer3 (Feed): HLS-Explorer an, autoselect an, AAC SW-Decode an
            if not opts.hls_explorer.value:
                opts.hls_explorer.value = True; opts.hls_explorer.save()
            if not opts.autoselect_stream.value:
                opts.autoselect_stream.value = True; opts.autoselect_stream.save()
            if not ext3.aac_swdecoding.value:
                ext3.aac_swdecoding.value = True; ext3.aac_swdecoding.save()

        # v181 erwartet '-a 0|1|2|3', altes serviceapp.so generiert '-a' ohne Wert → hängt
        aac_sw = False if _has_new_exteplayer3() else ext3.aac_swdecoding.value
        setExtEplayer3Settings(
            OPTIONS_SERVICEEXTEPLAYER3,
            aac_sw,
            ext3.dts_swdecoding.value,
            ext3.wma_swdecoding.value,
            ext3.lpcm_injecion.value,
            ext3.downmix.value
        )
        setServiceAppSettings(
            OPTIONS_SERVICEEXTEPLAYER3,
            opts.hls_explorer.value,
            opts.autoselect_stream.value,
            opts.connection_speed_kb.value,
            opts.autoturnon_subtitles.value
        )
    except Exception:
        pass


def _build_ref(url, title, player, user_agent,
               autoconfigure_serviceapp=True, prefer_best_quality=True,
               is_live=True, hls_audio_fix=False):
    url_str = url.decode("utf-8", "replace") if isinstance(url, bytes) else url
    if "ard-mcdn.de" in url_str:
        url_str = url_str.replace("https://", "http://", 1)
    if hls_audio_fix:
        local_url = _build_local_playlist(url_str, user_agent)
        if local_url:
            url_str    = local_url
            user_agent = ""
    elif prefer_best_quality:
        url_str = _resolve_hls_best_variant(url_str, user_agent)
    if user_agent:
        sep = "&" if "|" in url_str else "|"
        url_str = url_str + sep + "User-Agent=" + user_agent
    url_bytes   = url_str.encode("utf-8") if not isinstance(url_str, bytes) else url_str
    title_bytes = title.encode("utf-8")   if not isinstance(title, bytes)   else title
    if player == "exteplayer3":
        if autoconfigure_serviceapp and _has_serviceapp():
            _configure_serviceapp_for_live()
        player_id = 5002
    elif player == "gstplayer":
        player_id = 5001
    elif player == "default":
        player_id = 4097
    else:
        if is_live and _has_serviceapp():
            if autoconfigure_serviceapp:
                _configure_serviceapp_for_live()
            player_id = 5002
        else:
            player_id = 4097
    ref = eServiceReference(player_id, 0, url_bytes)
    ref.setName(title_bytes)
    return ref


def play_stream(session, stream_url, title="Stream", is_live=False, player="", user_agent="",
                autoconfigure_serviceapp=True, prefer_best_quality=True,
                streams=None, stream_index=0, hls_audio_fix=False):
    ref = _build_ref(stream_url, title, player, user_agent,
                     autoconfigure_serviceapp, prefer_best_quality, is_live,
                     hls_audio_fix=hls_audio_fix)
    session.open(SAStreamPlayer, ref,
                 streams=streams or [],
                 stream_index=stream_index,
                 autoconfigure_serviceapp=autoconfigure_serviceapp,
                 prefer_best_quality=prefer_best_quality)
