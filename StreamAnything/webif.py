# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import cgi
import io
import json
import os
import re
import threading
import uuid
import zipfile

try:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from SocketServer import ThreadingMixIn
    from urlparse import parse_qs, urlparse
except ImportError:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from socketserver import ThreadingMixIn
    from urllib.parse import parse_qs, urlparse


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

import streams as _streams
try:
    from plugin import PLUGIN_VERSION as _PLUGIN_VERSION
except Exception:
    _PLUGIN_VERSION = "?"

from sa_locale import _ as _gettext


def _(txt):
    s = _gettext(txt)
    if isinstance(s, bytes):
        try:
            return s.decode("utf-8")
        except Exception:
            return txt
    return s

_server = None
_server_thread = None
_server_lock = threading.Lock()

LOGO_DIR = os.path.join(os.path.dirname(__file__), "logos")

# ------------------------------------------------------------------
# HTTP-Handler
# ------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, code=200):
        body = html.encode("utf-8") if not isinstance(html, bytes) else html
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".ico": "image/x-icon"}.get(ext, "application/octet-stream")
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            self.send_response(404)
            self.end_headers()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _parse_json_body(self):
        raw = self._read_body()
        try:
            text = raw.decode("utf-8")
            return json.loads(text)
        except Exception:
            return {}

    def _handle_export(self):
        try:
            cfg = _streams.get_config()
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                content = json.dumps(cfg, ensure_ascii=False, indent=2)
                if not isinstance(content, bytes):
                    content = content.encode("utf-8")
                zf.writestr("streamanything.json", content)
                seen = set()
                items = cfg.get("items", [])
                all_logos = [i.get("logo", "") for i in items]
                all_logos += [s.get("logo", "") for i in items for s in i.get("streams", [])]
                for logo_rel in all_logos:
                    if logo_rel and logo_rel not in seen:
                        path = os.path.join(os.path.dirname(__file__), logo_rel)
                        if os.path.isfile(path):
                            zf.write(path, logo_rel)
                        seen.add(logo_rel)
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition",
                             'attachment; filename="streamanything_backup.zip"')
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_group_export(self, group_id):
        try:
            groups = _streams.get_groups()
            group = None
            for g in groups:
                if g.get("type") == "folder" and g.get("id") == group_id:
                    group = g
                    break
            if not group:
                self.send_response(404)
                self.end_headers()
                return
            streams = _streams.get_group_streams(group_id)
            lines = ["#EXTM3U"]
            for s in streams:
                lines.append("#EXTINF:-1," + s.get("name", ""))
                lines.append(s.get("url", ""))
            data = ("\n".join(lines) + "\n").encode("utf-8")
            safe_name = re.sub(r"[^A-Za-z0-9_\-]+", "_", group.get("name", "playlist")).strip("_") or "playlist"
            self.send_response(200)
            self.send_header("Content-Type", "audio/x-mpegurl")
            self.send_header("Content-Disposition",
                             'attachment; filename="%s.m3u"' % safe_name)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_import(self, parsed):
        qs   = parse_qs(parsed.query)
        mode = qs.get("mode", ["merge"])[0]
        ct   = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ct:
            self._send_json({"ok": False, "error": _("multipart erforderlich")}, 400)
            return
        try:
            form  = cgi.FieldStorage(
                fp=self.rfile, headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": ct}
            )
            data  = form["file"].file.read()
            zf    = zipfile.ZipFile(io.BytesIO(data))
            raw   = zf.read("streamanything.json").decode("utf-8")
            imported_cfg = json.loads(raw)

            for name in zf.namelist():
                if name.startswith("logos/") and name.lower().endswith((".png", ".jpg", ".jpeg")):
                    basename = os.path.basename(name)
                    if basename:
                        _streams.save_logo_bytes(zf.read(name), basename)

            new_items = imported_cfg.get("items", [])
            cfg = _streams.get_config()

            if mode == "replace":
                cfg["items"] = new_items
                count = len(new_items)
            else:
                existing_by_id = {i["id"]: i for i in cfg.get("items", []) if "id" in i}
                count = 0
                for new_item in new_items:
                    nid = new_item.get("id")
                    if nid not in existing_by_id:
                        cfg.setdefault("items", []).append(new_item)
                        count += 1
                    elif new_item.get("type") == "folder":
                        ex_folder = existing_by_id[nid]
                        ex_stream_ids = {s["id"] for s in ex_folder.get("streams", [])}
                        new_streams = [s for s in new_item.get("streams", [])
                                       if s.get("id") not in ex_stream_ids]
                        ex_folder.setdefault("streams", []).extend(new_streams)
                        count += len(new_streams)

            _streams.save_config(cfg)
            zf.close()
            self._send_json({"ok": True, "count": count})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/") or "/"

        if path == "/":
            self._send_html(_build_html())
            return

        if path.startswith("/logos/"):
            filename = path[len("/logos/"):]
            filepath = os.path.join(LOGO_DIR, filename)
            if os.path.isfile(filepath):
                self._send_file(filepath)
            else:
                self.send_response(404)
                self.end_headers()
            return

        if path == "/plugin.png":
            self._send_file(os.path.join(os.path.dirname(__file__), "plugin.png"))
            return

        if path == "/api/config":
            cfg = _streams.get_config()
            self._send_json({"webif_port": cfg.get("webif_port", 8090)})
            return

        if path == "/api/items":
            self._send_json(_streams.get_config().get("items", []))
            return

        if path == "/api/recording_timers":
            self._send_json(_streams.get_recording_timers())
            return

        if path == "/api/recordings/active":
            try:
                import plugin as _plugin
                self._send_json(_plugin._get_active_recordings_info())
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/export":
            self._handle_export()
            return

        if path.startswith("/api/groups/") and path.endswith("/export"):
            group_id = path[len("/api/groups/"):-len("/export")]
            self._handle_group_export(group_id)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        # ---- Konfiguration ----
        if path == "/api/config":
            data = self._parse_json_body()
            if "webif_port" in data:
                _streams.set_webif_port(int(data["webif_port"]))
            self._send_json({"ok": True})
            return

        # ---- Logo-Upload ----
        if path == "/api/logo":
            ct = self.headers.get("Content-Type", "")
            if "multipart/form-data" in ct:
                try:
                    form = cgi.FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={"REQUEST_METHOD": "POST",
                                 "CONTENT_TYPE": ct}
                    )
                    field = form["file"]
                    ext   = os.path.splitext(field.filename)[1].lower()
                    if ext not in (".png", ".jpg", ".jpeg"):
                        self._send_json({"ok": False, "error": _("Nur PNG/JPG-Dateien erlaubt")}, 400)
                        return
                    data = field.file.read()
                    if len(data) > 2 * 1024 * 1024:
                        self._send_json({"ok": False, "error": _("Datei zu groß (max. 2 MB)")}, 400)
                        return
                    saved = _streams.save_logo_bytes(data)
                    if saved:
                        self._send_json({"ok": True, "logo": "logos/" + os.path.basename(saved)})
                    else:
                        self._send_json({"ok": False, "error": _("Keine gültige PNG/JPG-Datei")}, 400)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            else:
                # URL-basierter Logo-Download
                data = self._parse_json_body()
                url  = data.get("url", "")
                if not url:
                    self._send_json({"ok": False, "error": _("Keine URL")}, 400)
                    return
                saved = _streams.fetch_logo_from_url(url)
                if saved:
                    self._send_json({"ok": True, "logo": "logos/" + os.path.basename(saved)})
                else:
                    self._send_json({"ok": False, "error": _("Download fehlgeschlagen oder keine gültige PNG/JPG-Datei")}, 400)
            return

        # ---- Sofort-Aufnahme starten ----
        if path == "/api/recordings/start":
            data       = self._parse_json_body()
            name       = data.get("name", "").strip()
            url        = data.get("url", "").strip()
            user_agent = data.get("user_agent", "")
            duration   = data.get("duration")
            if not name or not url:
                self._send_json({"ok": False, "error": _("Name und URL erforderlich")}, 400)
                return
            try:
                duration_seconds = int(duration) if duration not in (None, "") else None
            except (TypeError, ValueError):
                duration_seconds = None
            try:
                import plugin as _plugin
                _plugin._start_recording(
                    {"name": name, "url": url, "user_agent": user_agent}, duration_seconds)
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # ---- Laufende Aufnahme stoppen ----
        if path.startswith("/api/recordings/") and path.endswith("/cancel"):
            rec_id = path[len("/api/recordings/"):-len("/cancel")]
            try:
                import plugin as _plugin
                ok = _plugin._cancel_recording_by_id(rec_id)
                self._send_json({"ok": ok})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # ---- Geplante Aufnahme anlegen ----
        if path == "/api/recording_timers":
            data       = self._parse_json_body()
            name       = data.get("name", "").strip()
            url        = data.get("url", "").strip()
            user_agent = data.get("user_agent", "")
            start_time = data.get("start_time")
            duration   = data.get("duration")
            if not name:
                self._send_json({"ok": False, "error": _("Name erforderlich")}, 400)
                return
            if not url:
                self._send_json({"ok": False, "error": _("URL erforderlich")}, 400)
                return
            try:
                start_time = int(start_time)
            except (TypeError, ValueError):
                self._send_json({"ok": False, "error": _("Ungültige Startzeit")}, 400)
                return
            try:
                duration = int(duration) if duration not in (None, "") else None
            except (TypeError, ValueError):
                duration = None
            timer = _streams.add_recording_timer(name, url, start_time, user_agent, duration)
            try:
                import plugin as _plugin
                _plugin._register_wakeup_timer(timer["id"], timer["name"], timer["start_time"])
            except Exception:
                pass
            self._send_json({"ok": True, "timer": timer})
            return

        # ---- Flat: Stream hinzufügen ----
        if path == "/api/streams":
            data          = self._parse_json_body()
            name          = data.get("name", "").strip()
            url           = data.get("url", "").strip()
            logo          = data.get("logo", "")
            player        = data.get("player", "")
            user_agent    = data.get("user_agent", "")
            logo_url      = data.get("logo_url", "")
            hls_audio_fix = bool(data.get("hls_audio_fix", False))
            referer       = data.get("referer", "")
            if not name:
                self._send_json({"ok": False, "error": _("Name erforderlich")}, 400)
                return
            if not url:
                self._send_json({"ok": False, "error": _("URL erforderlich")}, 400)
                return
            _streams.add_flat_stream(name, url, logo, player, user_agent, logo_url, hls_audio_fix, referer)
            self._send_json({"ok": True})
            return

        # ---- Flat: Reihenfolge ----
        if path == "/api/streams/reorder":
            data = self._parse_json_body()
            _streams.reorder_flat_streams(data.get("ids", []))
            self._send_json({"ok": True})
            return

        # ---- Stream in Ordner verschieben ----
        if path == "/api/streams/move":
            data            = self._parse_json_body()
            stream_id        = data.get("stream_id", "")
            source_group_id  = data.get("source_group") or None
            target_group_id  = data.get("target_group") or None
            insert_before_id = data.get("insert_before") or None
            if not stream_id:
                self._send_json({"ok": False, "error": "stream_id erforderlich"}, 400)
                return
            ok = _streams.move_stream(stream_id, source_group_id, target_group_id, insert_before_id)
            self._send_json({"ok": ok})
            return

        # ---- Groups: Gruppe hinzufügen ----
        if path == "/api/groups":
            data     = self._parse_json_body()
            name     = data.get("name", "").strip()
            logo     = data.get("logo", "")
            logo_url = data.get("logo_url", "")
            if not name:
                self._send_json({"ok": False, "error": _("Name erforderlich")}, 400)
                return
            group_id = _streams.add_group(name, logo, logo_url)
            self._send_json({"ok": True, "id": group_id})
            return

        # ---- Groups: Reihenfolge ----
        if path == "/api/groups/reorder":
            data = self._parse_json_body()
            _streams.reorder_groups(data.get("ids", []))
            self._send_json({"ok": True})
            return

        # ---- Groups: Stream in Gruppe hinzufügen ----
        # POST /api/groups/<id>/streams
        parts = path.split("/")
        if len(parts) == 5 and parts[1] == "api" and parts[2] == "groups" and parts[4] == "streams":
            group_id   = parts[3]
            data       = self._parse_json_body()
            name          = data.get("name", "").strip()
            url           = data.get("url", "").strip()
            logo          = data.get("logo", "")
            player        = data.get("player", "")
            user_agent    = data.get("user_agent", "")
            logo_url      = data.get("logo_url", "")
            hls_audio_fix = bool(data.get("hls_audio_fix", False))
            referer       = data.get("referer", "")
            if not name:
                self._send_json({"ok": False, "error": _("Name erforderlich")}, 400)
                return
            if not url:
                self._send_json({"ok": False, "error": _("URL erforderlich")}, 400)
                return
            _streams.add_group_stream(group_id, name, url, logo, player, user_agent, logo_url, hls_audio_fix, referer)
            self._send_json({"ok": True})
            return

        # ---- Groups: Stream-Reihenfolge in Gruppe ----
        # POST /api/groups/<id>/streams/reorder
        if len(parts) == 6 and parts[1] == "api" and parts[2] == "groups" and parts[4] == "streams" and parts[5] == "reorder":
            group_id = parts[3]
            data = self._parse_json_body()
            _streams.reorder_group_streams(group_id, data.get("ids", []))
            self._send_json({"ok": True})
            return

        if path == "/api/import":
            self._handle_import(parsed)
            return

        self.send_response(404)
        self.end_headers()

    def do_PUT(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")
        parts  = path.split("/")
        data   = self._parse_json_body()

        # PUT /api/recording_timers/<id>
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "recording_timers":
            timer_id = parts[3]
            name = (data.get("name") or "").strip()
            try:
                start_time = int(data.get("start_time"))
            except (TypeError, ValueError):
                self._send_json({"ok": False, "error": _("Ungültige Startzeit")}, 400)
                return
            duration = data.get("duration")
            try:
                duration = int(duration) if duration not in (None, "") else None
            except (TypeError, ValueError):
                duration = None
            if not name:
                self._send_json({"ok": False, "error": _("Name erforderlich")}, 400)
                return
            timer = _streams.update_recording_timer(timer_id, name, start_time, duration)
            if not timer:
                self.send_response(404)
                self.end_headers()
                return
            try:
                import plugin as _plugin
                _plugin._unregister_wakeup_timer(timer_id)
                _plugin._register_wakeup_timer(timer_id, timer["name"], timer["start_time"])
            except Exception:
                pass
            self._send_json({"ok": True, "timer": timer})
            return

        # PUT /api/streams/<id>
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "streams":
            stream_id = parts[3]
            name = (data.get("name") or "").strip()
            if not name:
                self._send_json({"ok": False, "error": _("Name erforderlich")}, 400)
                return
            _streams.update_flat_stream(
                stream_id,
                name=name,
                url=data.get("url"),
                logo=data.get("logo"),
                player=data.get("player"),
                user_agent=data.get("user_agent"),
                logo_url=data.get("logo_url"),
                hls_audio_fix=data.get("hls_audio_fix"),
                referer=data.get("referer"),
            )
            self._send_json({"ok": True})
            return

        # PUT /api/groups/<id>
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "groups":
            group_id = parts[3]
            name = (data.get("name") or "").strip()
            if not name:
                self._send_json({"ok": False, "error": _("Name erforderlich")}, 400)
                return
            _streams.update_group(
                group_id,
                name=name,
                logo=data.get("logo"),
                logo_url=data.get("logo_url"),
            )
            self._send_json({"ok": True})
            return

        # PUT /api/groups/<gid>/streams/<sid>
        if len(parts) == 6 and parts[1] == "api" and parts[2] == "groups" and parts[4] == "streams":
            group_id  = parts[3]
            stream_id = parts[5]
            name = (data.get("name") or "").strip()
            if not name:
                self._send_json({"ok": False, "error": _("Name erforderlich")}, 400)
                return
            _streams.update_group_stream(
                group_id, stream_id,
                name=name,
                url=data.get("url"),
                logo=data.get("logo"),
                player=data.get("player"),
                user_agent=data.get("user_agent"),
                logo_url=data.get("logo_url"),
                hls_audio_fix=data.get("hls_audio_fix"),
                referer=data.get("referer"),
            )
            self._send_json({"ok": True})
            return

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")
        parts  = path.split("/")

        # DELETE /api/streams/<id>
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "streams":
            _streams.delete_flat_stream(parts[3])
            self._send_json({"ok": True})
            return

        # DELETE /api/groups/<id>
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "groups":
            _streams.delete_group(parts[3])
            self._send_json({"ok": True})
            return

        # DELETE /api/recording_timers/<id>
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "recording_timers":
            try:
                import plugin as _plugin
                _plugin._unregister_wakeup_timer(parts[3])
            except Exception:
                pass
            _streams.delete_recording_timer(parts[3])
            self._send_json({"ok": True})
            return

        # DELETE /api/groups/<gid>/streams/<sid>
        if len(parts) == 6 and parts[1] == "api" and parts[2] == "groups" and parts[4] == "streams":
            _streams.delete_group_stream(parts[3], parts[5])
            self._send_json({"ok": True})
            return

        self.send_response(404)
        self.end_headers()


# ------------------------------------------------------------------
# Server-Lifecycle
# ------------------------------------------------------------------

def start(port=None):
    global _server, _server_thread
    with _server_lock:
        if _server is not None:
            return
        if port is None:
            port = _streams.get_webif_port()
        try:
            _server = _ThreadedHTTPServer(("0.0.0.0", port), _Handler)
            _server_thread = threading.Thread(target=_server.serve_forever)
            _server_thread.daemon = True
            _server_thread.start()
            threading.Thread(target=_streams.cleanup_orphaned_logos).start()
        except Exception:
            _server = None


def stop():
    global _server, _server_thread
    with _server_lock:
        if _server is not None:
            _server.shutdown()
            _server = None
            _server_thread = None


def is_running():
    with _server_lock:
        return _server is not None


# ------------------------------------------------------------------
# HTML-Seite (inline, als Raw-String r"""...""")
# ------------------------------------------------------------------

def _build_html():  # noqa — long raw string intentional
    _html = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StreamAnything</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#111;color:#eee;min-height:100vh}
header{background:#1a1a2e;padding:16px 24px;display:flex;align-items:center;justify-content:center;gap:16px;border-bottom:2px solid #cc3d2d}
header h1{font-size:1.4rem;color:#cc3d2d}
main{max-width:900px;margin:0 auto;padding:24px 16px}
.section{background:#1c1c2e;border-radius:10px;padding:20px;margin-bottom:20px}
.section h2{font-size:1rem;margin-bottom:14px;color:#aaa;text-transform:uppercase;letter-spacing:.05em}
.form-row{display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.form-row input,.form-row select{flex:1;min-width:160px;padding:8px 10px;background:#111;border:1px solid #333;border-radius:6px;color:#eee;font-size:.9rem}
.form-row input[type=checkbox],.form-row input[type=radio]{flex:none;min-width:0;padding:0;background:none;border:none;width:auto;margin-right:4px}
.form-row input:focus,.form-row select:focus{outline:none;border-color:#cc3d2d}
.btn{padding:8px 16px;border:none;border-radius:6px;cursor:pointer;font-size:.9rem;white-space:nowrap}
.btn-primary{background:#cc3d2d;color:#fff}
.btn-primary:hover{background:#a83225}
.btn-sm{padding:4px 10px;font-size:.8rem}
.btn-danger{background:#333;color:#cc3d2d}
.btn-danger:hover{background:#cc3d2d;color:#fff}
.btn-edit{background:#333;color:#aaa}
.btn-edit:hover{background:#444;color:#fff}
.type-toggle{display:flex;gap:8px;margin-bottom:14px}
.btn-toggle{background:#222;color:#aaa;border-radius:6px;padding:7px 20px;border:2px solid #333;font-size:.9rem;cursor:pointer}
.btn-toggle.active{background:#cc3d2d;color:#fff;border-color:#cc3d2d}
.item-list{list-style:none}
.item{display:flex;align-items:center;gap:8px;padding:8px;border-radius:6px;background:#111;margin-bottom:6px}
.item-logo{width:48px;height:30px;object-fit:contain;border-radius:4px;background:#222;flex-shrink:0}
.item-logo-placeholder{width:48px;height:30px;border-radius:4px;background:#222;flex-shrink:0}
.item-name{flex:1;font-size:.95rem}
.item-url{font-size:.75rem;color:#666;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:300px}
.item-actions{display:flex;gap:4px;flex-shrink:0}
.drag-handle{cursor:grab;color:#444;padding:0 4px 0 0;font-size:1.1rem;flex-shrink:0;user-select:none;line-height:1}
.drag-handle:active{cursor:grabbing}
.item.drag-over{outline:2px solid #cc3d2d;outline-offset:-2px}
.item.folder-drop-target{outline:2px solid #2d8a4e;outline-offset:-2px;background:#1a2e1a}
.item.insert-before{border-top:2px solid #2d8a4e}
.item.insert-after{border-bottom:2px solid #2d8a4e}
.item.dragging{opacity:.35}
.badge{display:inline-block;font-size:.7rem;padding:2px 7px;border-radius:10px;margin-left:6px;vertical-align:middle}
.badge-stream{background:#3a1020;color:#cc3d2d}
.badge-folder{background:#1a1a40;color:#7878dd}
.logo-section{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.logo-preview{width:64px;height:40px;object-fit:contain;border-radius:4px;background:#222}
.folder-streams{padding:8px 0 4px 16px}
.btn-collapse{background:none;border:none;color:#888;cursor:pointer;font-size:.8rem;padding:2px 4px;flex-shrink:0;line-height:1}
.btn-collapse:hover{color:#bbb}
.empty{color:#555;font-size:.9rem;padding:8px 0}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.fi-wrap{display:inline-flex;align-items:center;gap:8px}
.fi-name{color:#888;font-size:.9em}
.modal{background:#1c1c2e;border-radius:10px;padding:24px;width:100%;max-width:460px}
.modal h3{margin-bottom:16px;color:#cc3d2d}
.modal .form-row{margin-bottom:10px}
.modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:16px}
.hint{font-size:.78rem;color:#555;margin-top:4px;margin-bottom:8px}
</style>
</head>
<body onload="load()">
<header>
  <img src="/plugin.png" style="height:40px;width:auto">
  <h1><span style="color:#fff">Stream</span>Anything</h1>
  <span style="color:#666;font-size:.85rem">v__SA_VERSION__</span>
</header>
<main>
  <div id="dbg" style="color:#888;font-size:.8rem;padding:4px 0 8px 0"></div>
  <div id="app"></div>
</main>

<!-- Edit-Modal (Stream) -->
<div class="modal-overlay" id="editModal">
  <div class="modal">
    <h3 id="editModalTitle">Stream bearbeiten</h3>
    <div class="form-row"><input id="editName" placeholder="Name"></div>
    <div id="editUrlRow" class="form-row"><input id="editUrl" placeholder="Stream-URL"></div>
    <div id="editPlayerRow" class="form-row">
      <select id="editPlayer">
        <option value="">Auto</option>
        <option value="exteplayer3">exteplayer3 (HLS / HTTPS)</option>
        <option value="gstplayer">GStreamer</option>
        <option value="default">Enigma2 Standard</option>
      </select>
    </div>
    <div id="editUaRow" class="form-row"><input id="editUserAgent" placeholder="User-Agent (optional)" list="uaList"></div>
    <p id="editUaHint" class="hint">User-Agent gilt nur bei Player: exteplayer3 (HLS)</p>
    <div class="form-row"><label style="white-space:nowrap"><input type="checkbox" id="editHlsAudioFix"> Lokaler Playlist Server (HLS Audiofix)</label></div>
    <div id="editRefererRow" class="form-row" style="flex-direction:column;align-items:stretch;gap:4px">
      <label style="white-space:nowrap"><input type="checkbox" id="editRefererProxy" onchange="document.getElementById('editRefererSub').style.display=this.checked?'':'none'"> Als Quell-Website ausgeben</label>
      <div id="editRefererSub" style="display:none;padding-left:20px;margin-top:4px">
        <label><input type="radio" name="editRefererMode" value="auto" checked onchange="_refModeChange('editRefererCustom',this)"> Auto</label>
        <label style="margin-left:12px"><input type="radio" name="editRefererMode" value="custom" onchange="_refModeChange('editRefererCustom',this)"> Website angeben</label>
        <input id="editRefererCustom" placeholder="https://..." style="display:none;width:100%;margin-top:4px">
      </div>
    </div>
    <div class="logo-section">
      <img id="editLogoPreview" class="logo-preview" src="" style="display:none">
      <div>
        <div class="form-row">
          <input id="editLogoUrl" placeholder="Logo-URL (optional)">
          <button class="btn btn-edit btn-sm" onclick="fetchLogoFromUrl('edit')">Laden</button>
          <button class="btn btn-edit btn-sm" id="editInheritFolderBtn" style="display:none" onclick="inheritFolderLogoEdit()">Von Ordner</button>
        </div>
        <div class="form-row">
          <span class="fi-wrap" data-no-file="__FI_NONE__"><button type="button" class="btn btn-edit btn-sm" onclick="document.getElementById('editLogoFile').click()">__FI_BTN__</button><span id="editLogoFile_nm" class="fi-name">__FI_NONE__</span><input type="file" id="editLogoFile" accept=".png,.jpg,.jpeg" style="display:none" onchange="uploadLogo('edit');document.getElementById('editLogoFile_nm').textContent=this.files.length?this.files[0].name:this.parentNode.getAttribute('data-no-file')"></span>
        </div>
        <p class="hint">PNG/JPG</p>
      </div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-edit" onclick="closeModal('editModal')">Abbrechen</button>
      <button class="btn btn-primary" onclick="saveEdit()">Speichern</button>
    </div>
  </div>
</div>

<!-- Edit-Modal (Ordner) -->
<div class="modal-overlay" id="folderEditModal">
  <div class="modal">
    <h3>Ordner bearbeiten</h3>
    <div class="form-row"><input id="folderEditName" placeholder="Ordnername"></div>
    <div class="logo-section">
      <img id="folderEditLogoPreview" class="logo-preview" src="" style="display:none">
      <div>
        <div class="form-row">
          <input id="folderEditLogoUrl" placeholder="Logo-URL (optional)">
          <button class="btn btn-edit btn-sm" onclick="fetchLogoFromUrl('folderEdit')">Laden</button>
        </div>
        <div class="form-row">
          <span class="fi-wrap" data-no-file="__FI_NONE__"><button type="button" class="btn btn-edit btn-sm" onclick="document.getElementById('folderEditLogoFile').click()">__FI_BTN__</button><span id="folderEditLogoFile_nm" class="fi-name">__FI_NONE__</span><input type="file" id="folderEditLogoFile" accept=".png,.jpg,.jpeg" style="display:none" onchange="uploadLogo('folderEdit');document.getElementById('folderEditLogoFile_nm').textContent=this.files.length?this.files[0].name:this.parentNode.getAttribute('data-no-file')"></span>
        </div>
        <p class="hint">PNG/JPG</p>
      </div>
    </div>
    <label style="display:flex;align-items:center;gap:8px;font-size:.9rem;color:#aaa;margin-bottom:12px">
      <input type="checkbox" id="folderEditApplyAll">
      Logo für alle Streams im Ordner übernehmen
    </label>
    <div class="modal-actions">
      <button class="btn btn-edit" onclick="closeModal('folderEditModal')">Abbrechen</button>
      <button class="btn btn-primary" onclick="saveFolderEdit()">Speichern</button>
    </div>
  </div>
</div>

<!-- Aufnahme-Modal -->
<div class="modal-overlay" id="recordModal">
  <div class="modal" style="max-width:480px">
    <h3 id="recordModalTitle">Aufnahme</h3>
    <div id="recordModalBody"></div>
    <div class="modal-actions">
      <button class="btn btn-edit" onclick="closeModal('recordModal')">Schließen</button>
    </div>
  </div>
</div>

<!-- Timer-Bearbeiten-Modal -->
<div class="modal-overlay" id="editTimerModal">
  <div class="modal" style="max-width:420px">
    <h3>Geplante Aufnahme bearbeiten</h3>
    <div class="form-row"><input id="editTimerName" placeholder="Name"></div>
    <div class="form-row"><label>Start: <input type="datetime-local" id="editTimerStart"></label></div>
    <div class="form-row"><label>Dauer (Minuten, leer = bis manuell gestoppt): <input type="number" id="editTimerDuration" min="1"></label></div>
    <div class="modal-actions">
      <button class="btn btn-edit" onclick="closeModal('editTimerModal')">Abbrechen</button>
      <button class="btn btn-primary" onclick="saveEditTimer()">Speichern</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="m3uModal">
  <div class="modal" style="max-width:520px">
    <h3>M3U importieren</h3>
    <p id="m3uInfo" style="color:#aaa;margin-bottom:14px"></p>

    <!-- Schritt 1: Alle oder Auswählen -->
    <div id="m3uStepChoice">
      <div class="modal-actions" style="justify-content:center;gap:12px">
        <button class="btn btn-primary" onclick="m3uChooseAll()">Alle übernehmen</button>
        <button class="btn btn-edit" onclick="m3uChooseSelect()">Auswählen</button>
      </div>
    </div>

    <!-- Schritt 2: Auswahlliste -->
    <div id="m3uStepList" style="display:none">
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <button class="btn btn-edit btn-sm" onclick="m3uCheckAll(true)">Alle</button>
        <button class="btn btn-edit btn-sm" onclick="m3uCheckAll(false)">Keine</button>
        <span id="m3uSelCount" style="color:#aaa;font-size:.85rem;margin-left:auto;align-self:center"></span>
      </div>
      <div id="m3uList" style="max-height:280px;overflow-y:auto;border:1px solid #2a2a2a;border-radius:6px;padding:4px 0"></div>
      <div class="modal-actions" style="margin-top:12px">
        <button class="btn btn-edit" onclick="m3uBackToChoice()">&#8592; Zurück</button>
        <button class="btn btn-primary" onclick="m3uProceedFromList()">Weiter</button>
      </div>
    </div>

    <!-- Schritt 3: Import-Optionen -->
    <div id="m3uForm" style="display:none">
      <div class="form-row" style="display:flex;gap:20px;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
          <input type="radio" name="m3uMode" value="flat" checked onchange="m3uModeChange()"> Einzelne Streams
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
          <input type="radio" name="m3uMode" value="folder" onchange="m3uModeChange()"> Als neuer Ordner
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
          <input type="radio" name="m3uMode" value="existing" onchange="m3uModeChange()"> In vorhandenen Ordner
        </label>
      </div>
      <div id="m3uFolderRow" class="form-row" style="display:none">
        <input id="m3uFolderName" placeholder="Ordner-Name">
      </div>
      <div id="m3uExistingRow" class="form-row" style="display:none">
        <select id="m3uExistingFolder"></select>
      </div>
      <div class="form-row">
        <select id="m3uPlayer">
          <option value="">Auto</option>
          <option value="exteplayer3">exteplayer3 (HLS / HTTPS)</option>
          <option value="gstplayer">GStreamer</option>
          <option value="default">Enigma2 Standard</option>
        </select>
      </div>
      <div class="form-row">
        <input id="m3uUserAgent" placeholder="User-Agent (optional)" list="uaList">
      </div>
      <div class="form-row"><label style="white-space:nowrap"><input type="checkbox" id="m3uHlsAudioFix"> Lokaler Playlist Server (HLS Audiofix)</label></div>
      <div class="form-row">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
          <input type="checkbox" id="m3uFetchLogos" checked> Logo-URLs automatisch laden
        </label>
      </div>
      <div class="modal-actions">
        <button class="btn btn-edit" id="m3uCancelBtn" onclick="closeModal('m3uModal')">Abbrechen</button>
        <button class="btn btn-primary" id="m3uImportBtn" onclick="confirmM3UImport()">Importieren</button>
      </div>
    </div>

    <!-- Schritt 4: Fortschritt -->
    <div id="m3uProgress" style="display:none">
      <p id="m3uProgressText" style="color:#aaa;margin-bottom:8px;font-size:.9rem"></p>
      <div style="background:#111;border-radius:4px;height:8px;overflow:hidden">
        <div id="m3uProgressBar" style="height:100%;background:#cc3d2d;width:0%;transition:width .2s"></div>
      </div>
    </div>
  </div>
</div>

<script>
function resetFileInput(id){
  var inp=document.getElementById(id);if(!inp)return;
  try{inp.value='';}catch(e){}
  var nm=document.getElementById(id+'_nm');
  if(nm)nm.textContent=inp.parentNode.getAttribute('data-no-file')||'';
}

var state = {
  items: [],
  recordingTimers: [],
  activeRecordings: [],
  addType: 'stream',
  pendingLogo: {edit: '', folderEdit: '', add: ''},
  pendingLogoUrl: {edit: '', folderEdit: '', add: ''},
  editId: null,
  editGroupId: null,
  m3uAllParsed: [],
  m3uStreams: [],
  collapsedFolders: {}
};

function xhr(method, url, body, cb){
  var r = new XMLHttpRequest();
  r.open(method, url, true);
  if(body && !(body instanceof FormData)){
    r.setRequestHeader('Content-Type','application/json');
  }
  r.onreadystatechange = function(){
    if(r.readyState !== 4) return;
    var data = {};
    try{ data = JSON.parse(r.responseText); }catch(e){}
    if(cb) cb(data);
  };
  r.onerror = function(){ if(cb) cb(null); };
  r.send(body instanceof FormData ? body : (body ? JSON.stringify(body) : null));
}

function dbg(msg){ var el=document.getElementById('dbg'); if(el) el.textContent=msg; }

function load(){
  xhr('GET','/api/items',null,function(items){
    state.items = Array.isArray(items) ? items : [];
    render();
  });
  loadRecordings();
}

function loadRecordings(){
  xhr('GET','/api/recording_timers',null,function(timers){
    state.recordingTimers = Array.isArray(timers) ? timers : [];
    renderRecordingsInPlace();
  });
  xhr('GET','/api/recordings/active',null,function(recs){
    state.activeRecordings = Array.isArray(recs) ? recs : [];
    renderRecordingsInPlace();
  });
}

function renderRecordingsInPlace(){
  // Aktualisiert nur die Aufnahmen-Sektion, nicht die komplette Seite -
  // sonst wuerden offene Eingabefelder/Modals beim periodischen Poll
  // (alle 3s) verloren gehen.
  var el = document.getElementById('recordingsSection');
  if(el) el.outerHTML = renderRecordingsSection();
}

setInterval(loadRecordings, 3000);

function render(){
  document.getElementById('app').innerHTML = renderRecordingsSection() + renderAddForm() + renderItemList() + renderBackupSection();
}

function playerSelectHtml(id, val){
  var opts=[['','Auto'],['exteplayer3','exteplayer3 (HLS / HTTPS)'],['gstplayer','GStreamer'],['default','Enigma2 Standard']];
  var s='<select id="'+id+'">';
  for(var i=0;i<opts.length;i++) s+='<option value="'+opts[i][0]+'"'+(val===opts[i][0]?' selected':'')+'>'+opts[i][1]+'</option>';
  return s+'</select>';
}

function esc(s){
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---- Add-Formular ----

function setAddType(t){
  state.addType = t;
  state.pendingLogo['add'] = '';
  state.pendingLogoUrl['add'] = '';
  render();
}

function renderAddForm(){
  var isStream = (state.addType === 'stream');
  var h = '<div class="section"><h2>Eintrag hinzufügen</h2>';
  h += '<input type="file" id="m3uFileHidden" accept=".m3u,.m3u8" style="display:none" onchange="handleM3UFile(this)">';
  h += '<div class="type-toggle">';
  h += '<button class="btn-toggle'+(isStream?' active':'')+'" onclick="setAddType(\'stream\')">&#9654; Stream</button>';
  h += '<button class="btn-toggle'+(!isStream?' active':'')+'" onclick="setAddType(\'folder\')">&#128193; Ordner</button>';
  h += '<button class="btn-toggle" onclick="document.getElementById(\'m3uFileHidden\').click()">&#128203; Playlist</button>';
  h += '</div>';
  h += '<div class="form-row"><input id="newName" placeholder="Name"></div>';
  if(isStream){
    h += '<div class="form-row"><input id="newUrl" placeholder="Stream-URL"></div>';
    h += '<div class="form-row">' + playerSelectHtml('newPlayer','') + '</div>';
    h += '<div class="form-row"><input id="newUserAgent" placeholder="User-Agent (optional)" list="uaList"></div>';
    h += '<p class="hint">User-Agent gilt nur bei Player: exteplayer3 (HLS)</p>';
    h += '<div class="form-row"><label style="white-space:nowrap"><input type="checkbox" id="newHlsAudioFix"> Lokaler Playlist Server (HLS Audiofix)</label></div>';
    h += '<div class="form-row" style="flex-direction:column;align-items:stretch;gap:4px">';
    h += '<label style="white-space:nowrap"><input type="checkbox" id="newRefererProxy" onchange="document.getElementById(\'newRefererSub\').style.display=this.checked?\'\':\' none\'"> Als Quell-Website ausgeben</label>';
    h += '<div id="newRefererSub" style="display:none;padding-left:20px;margin-top:4px">';
    h += '<label><input type="radio" name="newRefererMode" value="auto" checked onchange="_refModeChange(\'newRefererCustom\',this)"> Auto</label>';
    h += '<label style="margin-left:12px"><input type="radio" name="newRefererMode" value="custom" onchange="_refModeChange(\'newRefererCustom\',this)"> Website angeben</label>';
    h += '<input id="newRefererCustom" placeholder="https://..." style="display:none;width:100%;margin-top:4px"></div></div>';
  }
  h += '<div class="logo-section">';
  h += '<img id="newLogoPreview" class="logo-preview" src="" style="display:none">';
  h += '<div>';
  h += '<div class="form-row"><input id="newLogoUrl" placeholder="Logo-URL (optional)">';
  h += '<button class="btn btn-edit btn-sm" onclick="fetchLogoFromUrl(\'add\')">Laden</button></div>';
  h += '<div class="form-row"><span class="fi-wrap" data-no-file="__FI_NONE__"><button type="button" class="btn btn-edit btn-sm" onclick="document.getElementById(\'newLogoFile\').click()">__FI_BTN__</button><span id="newLogoFile_nm" class="fi-name">__FI_NONE__</span><input type="file" id="newLogoFile" accept=".png,.jpg,.jpeg" style="display:none" onchange="uploadLogo(\'add\');document.getElementById(\'newLogoFile_nm\').textContent=this.files.length?this.files[0].name:this.parentNode.getAttribute(\'data-no-file\')"></span></div>';
  h += '<p class="hint">PNG/JPG</p>';
  h += '</div></div>';
  h += '<button class="btn btn-primary" onclick="addItem()">'+(isStream?'Stream hinzufügen':'Ordner hinzufügen')+'</button>';
  h += '</div>';
  return h;
}

// ---- Item-Liste ----

function renderItemList(){
  var h = '<div class="section"><h2>Einträge ('+state.items.length+')</h2>';
  if(state.items.length === 0){
    h += '<p class="empty">Noch keine Einträge.</p>';
  } else {
    var hasFolders = state.items.some(function(it){ return it.type==='folder'; });
    if(hasFolders){
      h += '<div style="text-align:right;margin-bottom:8px">';
      h += '<button class="btn-collapse" onclick="collapseAll()">&#9654; Alle einklappen</button>';
      h += '&nbsp;&nbsp;';
      h += '<button class="btn-collapse" onclick="expandAll()">&#9660; Alle ausklappen</button>';
      h += '</div>';
    }
    h += '<ul class="item-list">';
    for(var i=0;i<state.items.length;i++){
      var item = state.items[i];
      if(item.type === 'folder') h += renderFolderItem(item, i);
      else h += renderStreamItem(item, i);
    }
    h += '</ul>';
  }
  h += '</div>';
  return h;
}

function renderStreamItem(s, i){
  var da='draggable="true" ondragstart="dStart(event,\''+s.id+'\',null)" ondragover="dOver(event,\''+s.id+'\',null)" ondragleave="dLeave(event)" ondrop="dDrop(event,\''+s.id+'\',null)" ondragend="dEnd(event)"';
  var h = '<li class="item" data-id="'+s.id+'" '+da+'>';
  h += '<span class="drag-handle" ontouchstart="tStart(event,\''+s.id+'\',null)">&#9776;</span>';
  if(s.logo) h += '<img class="item-logo" src="/'+esc(s.logo)+'" onerror="this.style.display=\'none\'">';
  else h += '<div class="item-logo-placeholder"></div>';
  h += '<div style="flex:1;overflow:hidden">';
  h += '<div class="item-name">'+esc(s.name)+'<span class="badge badge-stream">Stream</span></div>';
  h += '<div class="item-url">'+esc(s.url||'')+'</div>';
  h += '</div>';
  h += '<div class="item-actions">';
  h += '<button class="btn btn-edit btn-sm" style="color:#e74c3c" onclick="openRecordModal(\''+s.id+'\')" title="Aufnahme">&#9679;</button>';
  h += '<button class="btn btn-edit btn-sm" onclick="openEditStream(\''+s.id+'\')">&#9998;</button>';
  h += '<button class="btn btn-danger btn-sm" onclick="deleteStream(\''+s.id+'\')">&#10005;</button>';
  h += '</div></li>';
  return h;
}

function toggleFolder(id){
  state.collapsedFolders[id] = !state.collapsedFolders[id];
  render();
}
function collapseAll(){
  for(var i=0;i<state.items.length;i++){
    if(state.items[i].type==='folder') state.collapsedFolders[state.items[i].id]=true;
  }
  render();
}
function expandAll(){
  state.collapsedFolders={};
  render();
}
function renderFolderItem(g, gi){
  var collapsed = !!state.collapsedFolders[g.id];
  var da='draggable="true" ondragstart="dStart(event,\''+g.id+'\',null)" ondragover="dOver(event,\''+g.id+'\',null)" ondragleave="dLeave(event)" ondrop="dDrop(event,\''+g.id+'\',null)" ondragend="dEnd(event)"';
  var h = '<li class="item" style="flex-direction:column;align-items:stretch;cursor:default" data-id="'+g.id+'" '+da+'>';
  h += '<div style="display:flex;align-items:center;gap:8px">';
  h += '<span class="drag-handle" ontouchstart="tStart(event,\''+g.id+'\',null)">&#9776;</span>';
  h += '<button class="btn-collapse" onclick="event.stopPropagation();toggleFolder(\''+g.id+'\')">'+(collapsed?'&#9654;':'&#9660;')+'</button>';
  if(g.logo) h += '<img class="item-logo" src="/'+esc(g.logo)+'" onerror="this.style.display=\'none\'">';
  else h += '<div class="item-logo-placeholder"></div>';
  h += '<div class="item-name" style="font-weight:600">'+esc(g.name)+'<span class="badge badge-folder">Ordner</span></div>';
  h += '<div class="item-actions" style="margin-left:auto">';
  h += '<a class="btn btn-edit btn-sm" href="/api/groups/'+g.id+'/export" download title="Exportieren">&#8595;</a>';
  h += '<button class="btn btn-edit btn-sm" onclick="openEditFolder(\''+g.id+'\')">&#9998;</button>';
  h += '<button class="btn btn-danger btn-sm" onclick="deleteFolder(\''+g.id+'\')">&#10005;</button>';
  h += '</div></div>';
  h += '<div class="folder-streams"'+(collapsed?' style="display:none"':'')+' id="fsc-'+g.id+'">';
  var streams = g.streams || [];
  if(streams.length === 0){
    h += '<p class="empty">Noch keine Streams in diesem Ordner.</p>';
  } else {
    h += '<ul class="item-list">';
    for(var j=0;j<streams.length;j++){
      var s = streams[j];
      var sda='draggable="true" ondragstart="dStart(event,\''+s.id+'\',\''+g.id+'\')" ondragover="dOver(event,\''+s.id+'\',\''+g.id+'\')" ondragleave="dLeave(event)" ondrop="dDrop(event,\''+s.id+'\',\''+g.id+'\')" ondragend="dEnd(event)"';
      h += '<li class="item" data-id="'+s.id+'" '+sda+'>';
      h += '<span class="drag-handle" ontouchstart="tStart(event,\''+s.id+'\',\''+g.id+'\')">&#9776;</span>';
      if(s.logo) h += '<img class="item-logo" src="/'+esc(s.logo)+'" onerror="this.style.display=\'none\'">';
      else h += '<div class="item-logo-placeholder"></div>';
      h += '<div style="flex:1;overflow:hidden">';
      h += '<div class="item-name" style="font-size:.9rem">'+esc(s.name)+'</div>';
      h += '<div class="item-url">'+esc(s.url||'')+'</div>';
      h += '</div>';
      h += '<div class="item-actions">';
      h += '<button class="btn btn-edit btn-sm" style="color:#e74c3c" onclick="openRecordModal(\''+s.id+'\')" title="Aufnahme">&#9679;</button>';
      h += '<button class="btn btn-edit btn-sm" onclick="openEditFolderStream(\''+g.id+'\',\''+s.id+'\')">&#9998;</button>';
      h += '<button class="btn btn-danger btn-sm" onclick="deleteFolderStream(\''+g.id+'\',\''+s.id+'\')">&#10005;</button>';
      h += '</div></li>';
    }
    h += '</ul>';
  }
  h += '</div>';
  h += '</li>';
  // Add-Formular bewusst als eigenes, NICHT-draggable <li> ausserhalb des Ordner-<li>:
  // liegt es im selben draggable-Element wie der Ordner, kapert ein Long-Press auf den
  // Eingabefeldern (z.B. URL) auf Mobilgeraeten den nativen HTML5-Drag, das Android-
  // Einfuegen-Menue erscheint dann nicht mehr (haengt teils sogar in der Markierung fest).
  h += '<li class="item folder-addform" style="flex-direction:column;align-items:stretch;cursor:default'+(collapsed?';display:none':'')+'" id="fsadd-'+g.id+'">';
  h += '<div class="form-row"><input id="fs_name_'+g.id+'" placeholder="Name" style="flex:.4"><input id="fs_url_'+g.id+'" placeholder="URL"></div>';
  h += '<div class="form-row">' + playerSelectHtml('fs_player_'+g.id,'') + '</div>';
  h += '<div class="form-row"><input id="fs_ua_'+g.id+'" placeholder="User-Agent (optional)" list="uaList"></div>';
  h += '<div class="form-row"><label style="white-space:nowrap"><input type="checkbox" id="fs_hls_'+g.id+'"> Lokaler Playlist Server (HLS Audiofix)</label></div>';
  h += '<div class="form-row" style="flex-direction:column;align-items:stretch;gap:4px">';
  h += '<label style="white-space:nowrap"><input type="checkbox" id="fs_rp_'+g.id+'" onchange="document.getElementById(\'fs_rsub_'+g.id+'\').style.display=this.checked?\'\':\' none\'"> Als Quell-Website ausgeben</label>';
  h += '<div id="fs_rsub_'+g.id+'" style="display:none;padding-left:20px;margin-top:4px">';
  h += '<label><input type="radio" name="fs_rmode_'+g.id+'" value="auto" checked onchange="_refModeChange(\'fs_rc_'+g.id+'\',this)"> Auto</label>';
  h += '<label style="margin-left:12px"><input type="radio" name="fs_rmode_'+g.id+'" value="custom" onchange="_refModeChange(\'fs_rc_'+g.id+'\',this)"> Website angeben</label>';
  h += '<input id="fs_rc_'+g.id+'" placeholder="https://..." style="display:none;width:100%;margin-top:4px"></div></div>';
  h += '<div class="logo-section">';
  h += '<img id="fs_logo_prev_'+g.id+'" class="logo-preview" src="" style="display:none">';
  h += '<div>';
  h += '<div class="form-row"><input id="fs_logo_url_'+g.id+'" placeholder="Logo-URL (optional)">';
  h += '<button class="btn btn-edit btn-sm" onclick="fetchLogoTo(\'fs_logo_url_'+g.id+'\',\'fs_logo_prev_'+g.id+'\',\'fsadd_'+g.id+'\')">Laden</button>';
  h += '<button class="btn btn-edit btn-sm" onclick="inheritFolderLogo(\''+g.id+'\')">Von Ordner</button></div>';
  h += '<div class="form-row"><span class="fi-wrap" data-no-file="__FI_NONE__"><button type="button" class="btn btn-edit btn-sm" onclick="document.getElementById(\'fs_logo_file_'+g.id+'\').click()">__FI_BTN__</button><span id="fs_logo_file_'+g.id+'_nm" class="fi-name">__FI_NONE__</span><input type="file" id="fs_logo_file_'+g.id+'" accept=".png,.jpg,.jpeg" style="display:none" onchange="uploadLogoTo(\'fs_logo_file_'+g.id+'\',\'fs_logo_prev_'+g.id+'\',\'fsadd_'+g.id+'\');document.getElementById(\'fs_logo_file_'+g.id+'_nm\').textContent=this.files.length?this.files[0].name:this.parentNode.getAttribute(\'data-no-file\')"></span></div>';
  h += '<p class="hint">PNG/JPG</p>';
  h += '</div></div>';
  h += '<button class="btn btn-primary btn-sm" onclick="addFolderStream(\''+g.id+'\')">Stream hinzufügen</button>';
  h += '</li>';
  return h;
}

// ---- Hinzufügen ----

function addItem(){
  if(state.addType === 'stream') addStream(); else addFolder();
}

function addStream(){
  var name      = document.getElementById('newName').value.trim();
  var url       = document.getElementById('newUrl').value.trim();
  var logo      = state.pendingLogo['add'] || '';
  var logo_url  = state.pendingLogoUrl['add'] || '';
  var player    = document.getElementById('newPlayer').value;
  var ua        = document.getElementById('newUserAgent').value.trim();
  var hlsFix    = document.getElementById('newHlsAudioFix').checked;
  var referer   = _refRead('newRefererProxy','newRefererMode','newRefererCustom');
  if(!name){alert('Name erforderlich');return;}
  if(!url){alert('URL erforderlich');return;}
  xhr('POST','/api/streams',{name:name,url:url,logo:logo,logo_url:logo_url,player:player,user_agent:ua,hls_audio_fix:hlsFix,referer:referer},function(){
    state.pendingLogo['add']=''; state.pendingLogoUrl['add']=''; load();
  });
}

function addFolder(){
  var name     = document.getElementById('newName').value.trim();
  var logo     = state.pendingLogo['add'] || '';
  var logo_url = state.pendingLogoUrl['add'] || '';
  if(!name){alert('Name erforderlich');return;}
  xhr('POST','/api/groups',{name:name,logo:logo,logo_url:logo_url},function(){
    state.pendingLogo['add']=''; state.pendingLogoUrl['add']=''; load();
  });
}

// ---- Löschen ----

function deleteStream(id){
  if(!confirm('Stream löschen?'))return;
  xhr('DELETE','/api/streams/'+id,null,load);
}
function deleteFolder(id){
  if(!confirm('Ordner und alle enthaltenen Streams löschen?'))return;
  xhr('DELETE','/api/groups/'+id,null,load);
}
function deleteFolderStream(gid,sid){
  if(!confirm('Stream löschen?'))return;
  xhr('DELETE','/api/groups/'+gid+'/streams/'+sid,null,load);
}

// ---- Bearbeiten: Stream (direkt oder in Ordner) ----

function openEditStream(id){
  var s = _findItem(id);
  if(!s)return;
  state.editId=id; state.editGroupId=null;
  document.getElementById('editModalTitle').textContent='Stream bearbeiten';
  document.getElementById('editInheritFolderBtn').style.display='none';
  _showStreamFields(true);
  document.getElementById('editName').value=s.name||'';
  document.getElementById('editUrl').value=s.url||'';
  document.getElementById('editPlayer').value=s.player||'';
  document.getElementById('editUserAgent').value=s.user_agent||'';
  document.getElementById('editHlsAudioFix').checked=!!s.hls_audio_fix;
  _refFill('editRefererProxy','editRefererSub','editRefererMode','editRefererCustom',s.referer||'');
  document.getElementById('editLogoUrl').value=s.logo_url||'';
  state.pendingLogo['edit']=s.logo||'';
  state.pendingLogoUrl['edit']=s.logo_url||'';
  var prev=document.getElementById('editLogoPreview');
  if(s.logo){prev.src='/'+s.logo;prev.style.display='';}else{prev.style.display='none';}
  document.getElementById('editModal').classList.add('open');
  resetFileInput('editLogoFile');
}

function openEditFolderStream(gid,sid){
  var g=_findItem(gid); if(!g)return;
  var s=_findInStreams(g.streams||[],sid); if(!s)return;
  state.editId=sid; state.editGroupId=gid;
  document.getElementById('editModalTitle').textContent='Stream bearbeiten';
  document.getElementById('editInheritFolderBtn').style.display='';
  _showStreamFields(true);
  document.getElementById('editName').value=s.name||'';
  document.getElementById('editUrl').value=s.url||'';
  document.getElementById('editPlayer').value=s.player||'';
  document.getElementById('editUserAgent').value=s.user_agent||'';
  document.getElementById('editHlsAudioFix').checked=!!s.hls_audio_fix;
  _refFill('editRefererProxy','editRefererSub','editRefererMode','editRefererCustom',s.referer||'');
  document.getElementById('editLogoUrl').value=s.logo_url||'';
  state.pendingLogo['edit']=s.logo||'';
  state.pendingLogoUrl['edit']=s.logo_url||'';
  var prev=document.getElementById('editLogoPreview');
  if(s.logo){prev.src='/'+s.logo;prev.style.display='';}else{prev.style.display='none';}
  document.getElementById('editModal').classList.add('open');
  resetFileInput('editLogoFile');
}

function saveEdit(){
  var name=document.getElementById('editName').value.trim();
  var url=document.getElementById('editUrl').value.trim();
  var logo=state.pendingLogo['edit'];
  var logo_url=state.pendingLogoUrl['edit']||'';
  var player=document.getElementById('editPlayer').value;
  var ua=document.getElementById('editUserAgent').value.trim();
  var hlsFix=document.getElementById('editHlsAudioFix').checked;
  var referer=_refRead('editRefererProxy','editRefererMode','editRefererCustom');
  if(!name){alert('Name erforderlich');return;}
  if(!url){alert('URL erforderlich');return;}
  var path=state.editGroupId
    ? '/api/groups/'+state.editGroupId+'/streams/'+state.editId
    : '/api/streams/'+state.editId;
  var body={name:name,url:url,logo:logo,logo_url:logo_url,player:player,user_agent:ua,hls_audio_fix:hlsFix,referer:referer};
  xhr('PUT',path,body,function(){closeModal('editModal');load();});
}

function _showStreamFields(show){
  var d=show?'':'none';
  document.getElementById('editUrlRow').style.display=d;
  document.getElementById('editPlayerRow').style.display=d;
  document.getElementById('editUaRow').style.display=d;
  document.getElementById('editUaHint').style.display=d;
  document.getElementById('editRefererRow').style.display=d;
}
function _refModeChange(inputId,radio){
  document.getElementById(inputId).style.display=radio.value==='custom'?'':'none';
}
function _refFill(proxy,sub,modeRadioName,customId,val){
  document.getElementById(proxy).checked=!!val;
  document.getElementById(sub).style.display=val?'':'none';
  if(val&&val!=='auto'){
    document.querySelector('input[name="'+modeRadioName+'"][value="custom"]').checked=true;
    document.getElementById(customId).style.display='';
    document.getElementById(customId).value=val;
  }else{
    document.querySelector('input[name="'+modeRadioName+'"][value="auto"]').checked=true;
    document.getElementById(customId).style.display='none';
    document.getElementById(customId).value='';
  }
}
function _refRead(proxy,modeRadioName,customId){
  if(!document.getElementById(proxy)||!document.getElementById(proxy).checked)return'';
  var m=document.querySelector('input[name="'+modeRadioName+'"]:checked');
  return(m&&m.value==='custom')?(document.getElementById(customId).value.trim()||'auto'):'auto';
}

// ---- Bearbeiten: Ordner ----

function openEditFolder(id){
  var g=_findItem(id); if(!g)return;
  state.editId=id;
  document.getElementById('folderEditName').value=g.name||'';
  document.getElementById('folderEditLogoUrl').value=g.logo_url||'';
  document.getElementById('folderEditApplyAll').checked=false;
  state.pendingLogo['folderEdit']=g.logo||'';
  state.pendingLogoUrl['folderEdit']=g.logo_url||'';
  var prev=document.getElementById('folderEditLogoPreview');
  if(g.logo){prev.src='/'+g.logo;prev.style.display='';}else{prev.style.display='none';}
  document.getElementById('folderEditModal').classList.add('open');
  resetFileInput('folderEditLogoFile');
}

function saveFolderEdit(){
  var name=document.getElementById('folderEditName').value.trim();
  var logo=state.pendingLogo['folderEdit'];
  var logo_url=state.pendingLogoUrl['folderEdit']||'';
  var applyAll=document.getElementById('folderEditApplyAll').checked;
  if(!name){alert('Name erforderlich');return;}
  xhr('PUT','/api/groups/'+state.editId,{name:name,logo:logo,logo_url:logo_url},function(){
    if(!applyAll){closeModal('folderEditModal');load();return;}
    var folder=_findItem(state.editId);
    var streams=(folder&&folder.streams)||[];
    if(!streams.length){closeModal('folderEditModal');load();return;}
    var idx=0;
    var gid=state.editId;
    function next(){
      if(idx>=streams.length){closeModal('folderEditModal');load();return;}
      var s=streams[idx++];
      xhr('PUT','/api/groups/'+gid+'/streams/'+s.id,
        {name:s.name,url:s.url,logo:logo,logo_url:logo_url,player:s.player||'',user_agent:s.user_agent||''},
        next);
    }
    next();
  });
}

// ---- Ordner-Streams ----

function inheritFolderLogo(gid){
  var folder=_findItem(gid);
  if(!folder||!folder.logo)return;
  var stateKey='fsadd_'+gid;
  state.pendingLogo[stateKey]=folder.logo;
  state.pendingLogoUrl[stateKey]=folder.logo_url||'';
  var prev=document.getElementById('fs_logo_prev_'+gid);
  var urlInput=document.getElementById('fs_logo_url_'+gid);
  if(prev){prev.src='/logos/'+folder.logo.split('/').pop();prev.style.display='';}
  if(urlInput){urlInput.value=folder.logo_url||'';}
}

function inheritFolderLogoEdit(){
  var folder=_findItem(state.editGroupId);
  if(!folder||!folder.logo)return;
  state.pendingLogo['edit']=folder.logo;
  state.pendingLogoUrl['edit']=folder.logo_url||'';
  document.getElementById('editLogoUrl').value=folder.logo_url||'';
  var prev=document.getElementById('editLogoPreview');
  prev.src='/'+folder.logo; prev.style.display='';
}

function addFolderStream(gid){
  var name     = document.getElementById('fs_name_'+gid).value.trim();
  var url      = document.getElementById('fs_url_'+gid).value.trim();
  var player   = document.getElementById('fs_player_'+gid).value;
  var ua       = document.getElementById('fs_ua_'+gid).value.trim();
  var hlsFix   = document.getElementById('fs_hls_'+gid).checked;
  var referer  = _refRead('fs_rp_'+gid,'fs_rmode_'+gid,'fs_rc_'+gid);
  var logo     = state.pendingLogo['fsadd_'+gid] || '';
  var logo_url = state.pendingLogoUrl['fsadd_'+gid] || '';
  if(!name){alert('Name erforderlich');return;}
  if(!url){alert('URL erforderlich');return;}
  xhr('POST','/api/groups/'+gid+'/streams',{name:name,url:url,logo:logo,logo_url:logo_url,player:player,user_agent:ua,hls_audio_fix:hlsFix,referer:referer},function(){
    state.pendingLogo['fsadd_'+gid]=''; state.pendingLogoUrl['fsadd_'+gid]=''; load();
  });
}

// ---- Logo ----

function uploadLogoTo(fileInputId, previewId, stateKey){
  var file=document.getElementById(fileInputId).files[0];
  if(!file)return;
  var _ext=file.name.toLowerCase().split('.').pop();
  if(_ext!=='png'&&_ext!=='jpg'&&_ext!=='jpeg'){
    alert('Nur PNG/JPG-Dateien werden unterstützt.');
    document.getElementById(fileInputId).value='';
    return;
  }
  var fd=new FormData();
  fd.append('file',file,file.name);
  document.getElementById(fileInputId).value='';
  xhr('POST','/api/logo',fd,function(res){
    if(res&&res.ok){
      state.pendingLogo[stateKey]=res.logo;
      state.pendingLogoUrl[stateKey]='';
      var el=document.getElementById(previewId);
      if(el){el.src='/'+res.logo;el.style.display='';}
    } else {
      alert('Upload fehlgeschlagen: '+(res&&res.error||''));
    }
  });
}

function fetchLogoTo(urlInputId, previewId, stateKey){
  var url=document.getElementById(urlInputId).value.trim();
  if(!url){alert('Bitte eine URL eingeben');return;}
  var _u=url.split('?')[0].toLowerCase();if(_u.indexOf('.png')===-1&&_u.indexOf('.jpg')===-1&&_u.indexOf('.jpeg')===-1&&!confirm('URL endet nicht auf .png/.jpg – trotzdem versuchen?')) return;
  xhr('POST','/api/logo',{url:url},function(res){
    if(res&&res.ok){
      state.pendingLogo[stateKey]=res.logo;
      state.pendingLogoUrl[stateKey]=url;
      var el=document.getElementById(previewId);
      if(el){el.src='/'+res.logo;el.style.display='';}
    } else {
      alert('Logo-Download fehlgeschlagen: '+(res&&res.error||''));
    }
  });
}

function uploadLogo(ctx){
  var m={add:['newLogoFile','newLogoPreview'],edit:['editLogoFile','editLogoPreview'],folderEdit:['folderEditLogoFile','folderEditLogoPreview']};
  if(m[ctx]) uploadLogoTo(m[ctx][0],m[ctx][1],ctx);
}

function fetchLogoFromUrl(ctx){
  var m={add:['newLogoUrl','newLogoPreview'],edit:['editLogoUrl','editLogoPreview'],folderEdit:['folderEditLogoUrl','folderEditLogoPreview']};
  if(m[ctx]) fetchLogoTo(m[ctx][0],m[ctx][1],ctx);
}

function showLogoPreview(ctx,src){
  var ids={add:'newLogoPreview',edit:'editLogoPreview',folderEdit:'folderEditLogoPreview'};
  var el=document.getElementById(ids[ctx]);
  if(el){el.src=src;el.style.display='';}
}

// ---- Hilfsfunktionen ----

function _existingUrls(){
  var urls={};
  for(var i=0;i<state.items.length;i++){
    var it=state.items[i];
    if(it.url) urls[it.url]=1;
    var ss=it.streams||[];
    for(var j=0;j<ss.length;j++) if(ss[j].url) urls[ss[j].url]=1;
  }
  return urls;
}

function _findItem(id){
  for(var i=0;i<state.items.length;i++) if(state.items[i].id===id) return state.items[i];
  return null;
}
function _findAnyItem(id){
  for(var i=0;i<state.items.length;i++){
    if(state.items[i].id===id) return state.items[i];
    if(state.items[i].type==='folder'){
      var ss=state.items[i].streams||[];
      for(var j=0;j<ss.length;j++) if(ss[j].id===id) return ss[j];
    }
  }
  return null;
}
function _findInStreams(arr,id){
  for(var i=0;i<arr.length;i++) if(arr[i].id===id) return arr[i];
  return null;
}

// ---- Aufnahmen ----

function fmtTimerDate(ts){
  var d = new Date(ts * 1000);
  function p(n){ return (n<10?'0':'')+n; }
  return p(d.getDate())+'.'+p(d.getMonth()+1)+'.'+d.getFullYear()+' '+p(d.getHours())+':'+p(d.getMinutes());
}

function fmtTimerDuration(sec){
  if(!sec) return 'bis gestoppt';
  var h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60);
  return h ? (h+'h '+m+'min') : (m+' Min');
}

var TIMER_STATUS_LABELS = {
  pending: 'geplant', running: 'läuft', done: 'fertig', error: 'Fehler', cancelled: 'abgebrochen'
};

function fmtElapsed(sec){
  sec = sec||0;
  var h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = sec%60;
  function p(n){ return (n<10?'0':'')+n; }
  return h ? (h+':'+p(m)+':'+p(s)) : (m+':'+p(s));
}

function fmtBytes(b){
  b = b||0;
  if(b >= 1024*1024*1024) return (b/1024/1024/1024).toFixed(1)+' GB';
  if(b >= 1024*1024) return Math.round(b/1024/1024)+' MB';
  if(b >= 1024) return Math.round(b/1024)+' KB';
  return b+' B';
}

function renderRecordingsSection(){
  var h = '<div class="section" id="recordingsSection"><h2>Aufnahmen</h2>';
  h += '<p class="hint">Gestartet/geplant wird über das &#9679;-Symbol an einem Stream.</p>';

  h += '<h3 style="font-size:.95rem;color:#999;margin:12px 0 6px;font-weight:600">Laufende Aufnahmen</h3>';
  if(state.activeRecordings.length === 0){
    h += '<p class="empty">Keine laufende Aufnahme.</p>';
  } else {
    h += '<ul class="item-list">';
    for(var i=0;i<state.activeRecordings.length;i++){
      var r = state.activeRecordings[i];
      h += '<li class="item"><div style="flex:1;overflow:hidden">';
      h += '<div class="item-name" style="font-size:.9rem">'+esc(r.title)+'</div>';
      h += '<div class="item-url">'+fmtElapsed(r.elapsed)+' / '+(r.duration?fmtTimerDuration(r.duration):'unbegrenzt')+' &middot; '+fmtBytes(r.downloaded)+'</div>';
      h += '</div><div class="item-actions">';
      h += '<button class="btn btn-danger btn-sm" onclick="stopActiveRecording(\''+r.id+'\')" title="Stoppen">&#9632;</button>';
      h += '</div></li>';
    }
    h += '</ul>';
  }

  h += '<h3 style="font-size:.95rem;color:#999;margin:16px 0 6px;font-weight:600">Geplante Aufnahmen</h3>';
  if(state.recordingTimers.length === 0){
    h += '<p class="empty">Keine geplanten Aufnahmen.</p>';
  } else {
    h += '<ul class="item-list">';
    for(var j=0;j<state.recordingTimers.length;j++){
      var t = state.recordingTimers[j];
      h += '<li class="item"><div style="flex:1;overflow:hidden">';
      h += '<div class="item-name" style="font-size:.9rem">'+esc(t.name)+'</div>';
      h += '<div class="item-url">'+fmtTimerDate(t.start_time)+' &middot; '+fmtTimerDuration(t.duration)+' &middot; '+(TIMER_STATUS_LABELS[t.status]||t.status)+'</div>';
      h += '</div><div class="item-actions">';
      if(t.status === 'pending'){
        h += '<button class="btn btn-edit btn-sm" onclick="openEditTimerModal(\''+t.id+'\')" title="Bearbeiten">&#9998;</button>';
      }
      h += '<button class="btn btn-danger btn-sm" onclick="deleteRecordingTimer(\''+t.id+'\')">&#10005;</button>';
      h += '</div></li>';
    }
    h += '</ul>';
  }
  h += '</div>';
  return h;
}

function stopActiveRecording(id){
  if(!confirm('Diese laufende Aufnahme stoppen?')) return;
  xhr('POST', '/api/recordings/' + id + '/cancel', null, function(res){
    loadRecordings();
  });
}

function deleteRecordingTimer(id){
  if(!confirm('Diesen Aufnahme-Timer löschen?')) return;
  xhr('DELETE', '/api/recording_timers/' + id, null, function(res){
    loadRecordings();
  });
}

var _editTimerId = null;

function openEditTimerModal(id){
  var t = null;
  for(var i=0;i<state.recordingTimers.length;i++) if(state.recordingTimers[i].id===id) t = state.recordingTimers[i];
  if(!t) return;
  _editTimerId = id;
  document.getElementById('editTimerName').value = t.name;
  var d = new Date(t.start_time * 1000);
  function p(n){ return (n<10?'0':'')+n; }
  document.getElementById('editTimerStart').value =
    d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes());
  document.getElementById('editTimerDuration').value = t.duration ? Math.round(t.duration/60) : '';
  document.getElementById('editTimerModal').classList.add('open');
}

function saveEditTimer(){
  var name     = document.getElementById('editTimerName').value.trim();
  var startVal = document.getElementById('editTimerStart').value;
  var durVal   = document.getElementById('editTimerDuration').value;
  if(!name || !startVal){ alert('Bitte Name und Startzeit angeben.'); return; }
  var startTs = Math.floor(new Date(startVal).getTime() / 1000);
  if(isNaN(startTs)){ alert('Ungültige Startzeit.'); return; }
  xhr('PUT', '/api/recording_timers/' + _editTimerId, {
    name: name, start_time: startTs, duration: durVal ? parseInt(durVal, 10) * 60 : null
  }, function(res){
    if(res && res.ok){
      closeModal('editTimerModal');
      loadRecordings();
    } else {
      alert('Speichern fehlgeschlagen: ' + (res && res.error || 'Unbekannter Fehler'));
    }
  });
}

// ---- Aufnahme-Modal (pro Stream über das &#9679;-Symbol) ----

var _recordTarget = null;

function openRecordModal(id){
  var s = _findAnyItem(id);
  if(!s) return;
  _recordTarget = {name: s.name, url: s.url, user_agent: s.user_agent || ''};
  document.getElementById('recordModalTitle').textContent = 'Aufnahme: ' + s.name;
  renderRecordModalBody();
  document.getElementById('recordModal').classList.add('open');
}

function renderRecordModalBody(){
  var presets = [['30 Min',30],['1 Std',60],['2 Std',120],['3 Std',180],['6 Std',360]];
  var h = '<div style="margin-bottom:8px;font-weight:600">Jetzt aufnehmen</div>';
  h += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px">';
  for(var i=0;i<presets.length;i++){
    h += '<button class="btn btn-edit btn-sm" onclick="startInstantRecording('+presets[i][1]+')">'+presets[i][0]+'</button>';
  }
  h += '<button class="btn btn-edit btn-sm" onclick="startInstantRecording(null)">Bis gestoppt</button>';
  h += '</div>';
  h += '<div class="form-row"><input type="number" id="recordCustomMinutes" placeholder="Eigene Dauer (Minuten)" style="width:180px;display:inline-block;margin-right:8px">';
  h += '<button class="btn btn-edit btn-sm" onclick="startInstantRecordingCustom()">Start</button></div>';

  h += '<div style="border-top:1px solid #2a2a2a;margin:20px 0 12px"></div>';
  h += '<div style="margin-bottom:8px;font-weight:600">Für später planen</div>';
  h += '<div class="form-row"><label>Start: <input type="datetime-local" id="recordScheduleStart"></label></div>';
  h += '<div class="form-row"><label>Dauer (Minuten, leer = bis manuell gestoppt): <input type="number" id="recordScheduleDuration" min="1" placeholder="z.B. 180"></label></div>';
  h += '<button class="btn btn-primary" onclick="scheduleRecordingFromModal()">Timer anlegen</button>';

  document.getElementById('recordModalBody').innerHTML = h;
}

function startInstantRecording(minutes){
  if(!_recordTarget) return;
  xhr('POST', '/api/recordings/start', {
    name: _recordTarget.name, url: _recordTarget.url, user_agent: _recordTarget.user_agent,
    duration: minutes ? minutes * 60 : null
  }, function(res){
    if(res && res.ok){
      closeModal('recordModal');
      loadRecordings();
    } else {
      alert('Start fehlgeschlagen: ' + (res && res.error || 'Unbekannter Fehler'));
    }
  });
}

function startInstantRecordingCustom(){
  var val = document.getElementById('recordCustomMinutes').value;
  var minutes = parseInt(val, 10);
  if(!minutes || minutes <= 0){ alert('Bitte eine gültige Dauer in Minuten angeben.'); return; }
  startInstantRecording(minutes);
}

function scheduleRecordingFromModal(){
  if(!_recordTarget) return;
  var startVal = document.getElementById('recordScheduleStart').value;
  var durVal   = document.getElementById('recordScheduleDuration').value;
  if(!startVal){ alert('Bitte Startzeit angeben.'); return; }
  var startTs = Math.floor(new Date(startVal).getTime() / 1000);
  if(isNaN(startTs)){ alert('Ungültige Startzeit.'); return; }

  xhr('POST', '/api/recording_timers', {
    name: _recordTarget.name, url: _recordTarget.url, user_agent: _recordTarget.user_agent,
    start_time: startTs, duration: durVal ? parseInt(durVal, 10) * 60 : null
  }, function(res){
    if(res && res.ok){
      closeModal('recordModal');
      loadRecordings();
    } else {
      alert('Anlegen fehlgeschlagen: ' + (res && res.error || 'Unbekannter Fehler'));
    }
  });
}

// ---- Backup / Import ----

function renderBackupSection(){
  var h = '<div class="section"><h2>Backup</h2>';
  h += '<div style="display:flex;gap:24px;flex-wrap:wrap;align-items:flex-start">';

  h += '<div>';
  h += '<p style="color:#666;font-size:.85rem;margin-bottom:8px">Alle Einträge und Logos als ZIP exportieren</p>';
  h += '<a href="/api/export" class="btn btn-edit" download="streamanything_backup.zip">&#8595; Exportieren</a>';
  h += '</div>';

  h += '<div style="width:1px;background:#2a2a2a;align-self:stretch"></div>';

  h += '<div style="flex:1;min-width:260px">';
  h += '<p style="color:#666;font-size:.85rem;margin-bottom:8px">ZIP-Backup importieren</p>';
  h += '<div class="form-row"><span class="fi-wrap" data-no-file="__FI_NONE__"><button type="button" class="btn btn-edit btn-sm" onclick="document.getElementById(\'importFile\').click()">__FI_BTN__</button><span id="importFile_nm" class="fi-name">__FI_NONE__</span><input type="file" id="importFile" accept=".zip" style="display:none" onchange="document.getElementById(\'importFile_nm\').textContent=this.files.length?this.files[0].name:this.parentNode.getAttribute(\'data-no-file\')"></span></div>';
  h += '<div style="display:flex;gap:8px;margin-top:4px">';
  h += '<button class="btn btn-edit" id="importBtnMerge" onclick="importSettings(\'merge\')">Einträge hinzufügen</button>';
  h += '<button class="btn btn-danger" id="importBtnReplace" onclick="importSettings(\'replace\')">Alles ersetzen</button>';
  h += '</div></div>';

  h += '</div></div>';
  return h;
}

function importSettings(mode){
  var file = document.getElementById('importFile').files[0];
  if(!file){ alert('Bitte zuerst eine Backup-Datei (.zip) auswählen.'); return; }
  var msg = mode === 'replace'
    ? 'Achtung: Alle vorhandenen Einträge werden gelöscht und durch die Backup-Datei ersetzt. Fortfahren?'
    : 'Die Einträge aus der Backup-Datei werden zu den vorhandenen hinzugefügt. Duplikate werden übersprungen. Fortfahren?';
  if(!confirm(msg)) return;
  var btnMerge   = document.getElementById('importBtnMerge');
  var btnReplace = document.getElementById('importBtnReplace');
  if(btnMerge)   { btnMerge.disabled=true;   btnMerge.textContent='Importiere…'; }
  if(btnReplace) { btnReplace.disabled=true; btnReplace.textContent='Importiere…'; }
  var fd = new FormData();
  fd.append('file', file, file.name);
  xhr('POST', '/api/import?mode=' + mode, fd, function(res){
    if(btnMerge)   { btnMerge.disabled=false;   btnMerge.textContent='Einträge hinzufügen'; }
    if(btnReplace) { btnReplace.disabled=false; btnReplace.textContent='Alles ersetzen'; }
    if(res && res.ok){
      alert('Import abgeschlossen: ' + res.count + ' Einträge importiert.');
      load();
    } else {
      alert('Import fehlgeschlagen: ' + (res && res.error || 'Unbekannter Fehler'));
    }
  });
}

// ---- M3U-Import ----

function parseM3U(text){
  var streams=[], lines=text.split(/\r?\n/);
  var name=null, logo=null;
  for(var i=0;i<lines.length;i++){
    var line=lines[i].trim();
    if(line.toUpperCase().indexOf('#EXTINF:')===0){
      var comma=line.lastIndexOf(',');
      name = comma>=0 ? line.slice(comma+1).trim() : '';
      var lm=line.match(/tvg-logo="([^"]+)"/i);
      logo = lm ? lm[1] : '';
    } else if(line && line[0]!=='#'){
      if(!name){try{name=decodeURIComponent(line.split('?')[0].split('/').filter(Boolean).pop()||'');}catch(ex){name='';}}
      streams.push({name: name||line, url: line, logo_url: logo||''});
      name=null; logo=null;
    }
  }
  return streams;
}

function _m3uInfoText(streams){
  var withLogos=streams.filter(function(s){return s.logo_url;}).length;
  return streams.length+' Stream'+(streams.length!==1?'s':'')+' gefunden'+(withLogos?' · '+withLogos+' mit Logo':'');
}

function handleM3UFile(input){
  var file=input.files[0]; if(!file) return;
  var reader=new FileReader();
  reader.onload=function(e){
    var streams=parseM3U(e.target.result);
    if(!streams.length){alert('Keine Streams in der Datei gefunden.');return;}
    state.m3uAllParsed=streams;
    state.m3uStreams=streams;
    document.getElementById('m3uInfo').textContent=_m3uInfoText(streams);
    var fname=file.name.replace(/\.m3u8?$/i,'');
    document.getElementById('m3uFolderName').value=fname;
    document.getElementById('m3uStepChoice').style.display='';
    document.getElementById('m3uStepList').style.display='none';
    document.getElementById('m3uForm').style.display='none';
    document.getElementById('m3uProgress').style.display='none';
    document.getElementById('m3uModal').classList.add('open');
  };
  reader.readAsText(file);
}

function m3uChooseAll(){
  state.m3uStreams=state.m3uAllParsed;
  document.getElementById('m3uStepChoice').style.display='none';
  document.getElementById('m3uForm').style.display='';
  document.getElementById('m3uImportBtn').disabled=false;
  document.getElementById('m3uImportBtn').textContent='Importieren';
}

function m3uChooseSelect(){
  var list=document.getElementById('m3uList');
  list.innerHTML='';
  state.m3uAllParsed.forEach(function(s,i){
    var label=document.createElement('label');
    label.style.cssText='display:flex;align-items:center;gap:8px;padding:6px 10px;cursor:pointer;border-bottom:1px solid #1a1a2a;font-size:.9rem';
    var displayName=s.name ? s.name : '<span style="color:#555">'+s.url+'</span>';
    label.innerHTML='<input type="checkbox" checked data-idx="'+i+'" onchange="m3uUpdateSelCount()"> '
      +'<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+displayName+'</span>';
    list.appendChild(label);
  });
  m3uUpdateSelCount();
  document.getElementById('m3uStepChoice').style.display='none';
  document.getElementById('m3uStepList').style.display='';
}

function m3uUpdateSelCount(){
  var boxes=document.querySelectorAll('#m3uList input[type=checkbox]');
  var checked=0; boxes.forEach(function(b){if(b.checked)checked++;});
  document.getElementById('m3uSelCount').textContent=checked+' ausgewählt';
}

function m3uCheckAll(val){
  document.querySelectorAll('#m3uList input[type=checkbox]').forEach(function(b){b.checked=val;});
  m3uUpdateSelCount();
}

function m3uBackToChoice(){
  document.getElementById('m3uStepList').style.display='none';
  document.getElementById('m3uStepChoice').style.display='';
}

function m3uProceedFromList(){
  var selected=[];
  document.querySelectorAll('#m3uList input[type=checkbox]').forEach(function(b){
    if(b.checked) selected.push(state.m3uAllParsed[parseInt(b.dataset.idx)]);
  });
  if(!selected.length){alert('Bitte mindestens einen Stream auswählen.');return;}
  state.m3uStreams=selected;
  document.getElementById('m3uInfo').textContent=_m3uInfoText(selected);
  document.getElementById('m3uStepList').style.display='none';
  document.getElementById('m3uForm').style.display='';
  document.getElementById('m3uImportBtn').disabled=false;
  document.getElementById('m3uImportBtn').textContent='Importieren';
}

function m3uModeChange(){
  var mode=document.querySelector('input[name="m3uMode"]:checked').value;
  document.getElementById('m3uFolderRow').style.display=mode==='folder'?'':'none';
  var existingRow=document.getElementById('m3uExistingRow');
  existingRow.style.display=mode==='existing'?'':'none';
  if(mode==='existing'){
    var sel=document.getElementById('m3uExistingFolder');
    sel.innerHTML='';
    var folders=state.items.filter(function(it){return it.type==='folder';});
    if(folders.length===0){
      sel.innerHTML='<option value="">— Keine Ordner vorhanden —</option>';
    } else {
      folders.forEach(function(f){
        var opt=document.createElement('option');
        opt.value=f.id; opt.textContent=f.name;
        sel.appendChild(opt);
      });
    }
  }
}

function _m3uSetProgress(current, total){
  var pct=Math.round(current/total*100);
  document.getElementById('m3uProgressBar').style.width=pct+'%';
  document.getElementById('m3uProgressText').textContent=
    'Stream '+current+' von '+total+' importiert…';
}

function confirmM3UImport(){
  var mode=document.querySelector('input[name="m3uMode"]:checked').value;
  var folderName=document.getElementById('m3uFolderName').value.trim();
  var player=document.getElementById('m3uPlayer').value;
  var ua=document.getElementById('m3uUserAgent').value.trim();
  var hlsFix=document.getElementById('m3uHlsAudioFix').checked;
  var fetchLogos=document.getElementById('m3uFetchLogos').checked;
  if(mode==='folder' && !folderName){alert('Bitte einen Ordner-Namen eingeben.');return;}
  if(mode==='existing' && !document.getElementById('m3uExistingFolder').value){alert('Bitte einen Ordner auswählen.');return;}

  var streams=state.m3uStreams;
  var total=streams.length;
  var done=0, imported=0, skipped=0;
  var groupId=null;
  var existingUrls=_existingUrls();

  document.getElementById('m3uStepChoice').style.display='none';
  document.getElementById('m3uStepList').style.display='none';
  document.getElementById('m3uForm').style.display='none';
  document.getElementById('m3uProgress').style.display='';
  document.getElementById('m3uImportBtn').disabled=true;
  _m3uSetProgress(0, total);

  function finish(){
    closeModal('m3uModal');
    document.getElementById('m3uFileHidden').value='';
    var msg=imported+' Stream'+(imported!==1?'s':'')+' importiert.';
    if(skipped) msg+=' '+skipped+' bereits vorhanden, übersprungen.';
    alert(msg);
    load();
  }

  function addStream(s, logo, cb){
    var body={name:s.name, url:s.url, logo:logo, logo_url:s.logo_url||'', player:player, user_agent:ua, hls_audio_fix:hlsFix, referer:s.referer||''};
    var path=groupId ? '/api/groups/'+groupId+'/streams' : '/api/streams';
    xhr('POST', path, body, cb);
  }

  function processNext(){
    if(done>=total){finish();return;}
    var s=streams[done];
    if(existingUrls[s.url]){done++;skipped++;_m3uSetProgress(done,total);processNext();return;}
    function doAdd(logo){
      addStream(s, logo, function(res){
        if(res&&res.ok===false){done++;skipped++;_m3uSetProgress(done,total);processNext();return;}
        existingUrls[s.url]=1;
        done++;imported++;
        _m3uSetProgress(done,total);
        processNext();
      });
    }
    if(fetchLogos && s.logo_url){
      xhr('POST','/api/logo',{url:s.logo_url},function(res){
        doAdd((res&&res.ok) ? res.logo : '');
      });
    } else {
      doAdd('');
    }
  }

  if(mode==='folder'){
    xhr('POST','/api/groups',{name:folderName,logo:''},function(res){
      if(!res||!res.ok){alert('Fehler beim Erstellen des Ordners.');return;}
      groupId=res.id;
      processNext();
    });
  } else if(mode==='existing'){
    groupId=document.getElementById('m3uExistingFolder').value;
    if(!groupId){alert('Bitte einen Ordner auswählen.');return;}
    processNext();
  } else {
    processNext();
  }
}

// ---- Drag & Drop (Desktop: HTML5, Mobile: Touch) ----

var drag={srcId:null,srcGroup:null};

function _idxOf(arr,val){for(var i=0;i<arr.length;i++) if(arr[i]===val) return i; return -1;}

function _doMove(srcId,srcGroup,targetGroupId,insertBeforeId){
  var body={stream_id:srcId,source_group:srcGroup,target_group:targetGroupId};
  if(insertBeforeId) body.insert_before=insertBeforeId;
  xhr('POST','/api/streams/move',body,function(){load();});
}

var _scrollIv=null;
function _autoScrollStart(dir){if(!_scrollIv)_scrollIv=setInterval(function(){window.scrollBy(0,dir*15);},16);}
function _autoScrollStop(){if(_scrollIv){clearInterval(_scrollIv);_scrollIv=null;}}
document.addEventListener('dragover',function(e){
  if(!drag.srcId){_autoScrollStop();return;}
  var m=80;
  if(e.clientY<m) _autoScrollStart(-1);
  else if(e.clientY>window.innerHeight-m) _autoScrollStart(1);
  else _autoScrollStop();
});

function _doReorder(srcId,srcGroup,targetId,insertBefore){
  if(!srcGroup){
    var ids=state.items.map(function(i){return i.id;});
    var fi=_idxOf(ids,srcId), ti=_idxOf(ids,targetId);
    if(fi<0||ti<0) return;
    var mv=state.items.splice(fi,1)[0];
    ti=_idxOf(state.items.map(function(i){return i.id;}),targetId);
    state.items.splice(insertBefore?ti:ti+1,0,mv);
    xhr('POST','/api/streams/reorder',{ids:state.items.map(function(i){return i.id;})},render);
  } else {
    var folder=_findItem(srcGroup); if(!folder) return;
    var ss=folder.streams||[];
    var sids=ss.map(function(s){return s.id;});
    var fi2=_idxOf(sids,srcId), ti2=_idxOf(sids,targetId);
    if(fi2<0||ti2<0) return;
    var mv2=ss.splice(fi2,1)[0];
    ti2=_idxOf(ss.map(function(s){return s.id;}),targetId);
    ss.splice(insertBefore?ti2:ti2+1,0,mv2);
    xhr('POST','/api/groups/'+srcGroup+'/streams/reorder',{ids:ss.map(function(s){return s.id;})},render);
  }
}

// Desktop
function dStart(e,id,gid){
  drag.srcId=id; drag.srcGroup=gid||null;
  e.dataTransfer.effectAllowed='move';
  e.currentTarget.classList.add('dragging');
  e.stopPropagation();
}
function _clearDragClasses(el){
  el.classList.remove('dragging','drag-over','folder-drop-target','insert-before','insert-after');
}
function dOver(e,id,gid){
  if(drag.srcId===id) return;
  var srcGroup=drag.srcGroup;
  var tgtGroup=gid||null;
  var tgt=_findAnyItem(id);
  if(!tgt) return;
  // Eigenen Ordner-Header beim Drag innerhalb des Ordners ignorieren
  if(tgt.type==='folder'&&tgt.id===srcGroup) return;
  // Drag zwischen zwei verschiedenen Ordnern auf Stream-Ebene: ignorieren
  if(srcGroup&&tgtGroup&&srcGroup!==tgtGroup) return;
  var srcItem=_findItem(drag.srcId);
  var srcIsFolder=srcItem&&srcItem.type==='folder';
  // Ordner/Stream über Stream innerhalb eines Ordners: nur für Ordner preventDefault, dann zurück
  if(!srcGroup&&tgtGroup){
    if(srcIsFolder) e.preventDefault();
    return;
  }
  e.preventDefault();
  if(tgt.type==='folder'&&!srcIsFolder){
    var frect=e.currentTarget.getBoundingClientRect();
    var frelY=e.clientY-frect.top;
    e.currentTarget.classList.remove('insert-before','insert-after','folder-drop-target');
    if(frelY<frect.height*0.25) e.currentTarget.classList.add('insert-before');
    else if(frelY>frect.height*0.75) e.currentTarget.classList.add('insert-after');
    else e.currentTarget.classList.add('folder-drop-target');
  } else {
    var rect=e.currentTarget.getBoundingClientRect();
    e.currentTarget.classList.remove('insert-before','insert-after','folder-drop-target');
    if(e.clientY<rect.top+rect.height/2) e.currentTarget.classList.add('insert-before');
    else e.currentTarget.classList.add('insert-after');
  }
}
function dLeave(e){ _clearDragClasses(e.currentTarget); }
function dDrop(e,id,gid){
  e.preventDefault();
  var isFolderDrop=e.currentTarget.classList.contains('folder-drop-target');
  var isInsertBefore=e.currentTarget.classList.contains('insert-before');
  var isInsertAfter=e.currentTarget.classList.contains('insert-after');
  _clearDragClasses(e.currentTarget);
  if(!drag.srcId||drag.srcId===id) return;
  var srcGroup=drag.srcGroup;
  var tgtGroup=gid||null;
  if(isFolderDrop){
    _doMove(drag.srcId,srcGroup,id);
    return;
  }
  if(isInsertBefore||isInsertAfter){
    if(srcGroup&&!tgtGroup){
      // Ordner-Stream → flache Liste an bestimmter Position
      var ibId=id;
      if(isInsertAfter){
        var flat=state.items.filter(function(i){return i.id!==drag.srcId;});
        var fi=_idxOf(flat.map(function(i){return i.id;}),id);
        ibId=(fi>=0&&fi+1<flat.length)?flat[fi+1].id:null;
      }
      _doMove(drag.srcId,srcGroup,null,ibId);
    } else {
      _doReorder(drag.srcId,srcGroup,id,isInsertBefore);
    }
    return;
  }
}
function dEnd(e){
  _autoScrollStop();
  var els=document.querySelectorAll('.dragging,.drag-over,.folder-drop-target,.insert-before,.insert-after');
  for(var i=0;i<els.length;i++) _clearDragClasses(els[i]);
  drag.srcId=null; drag.srcGroup=null;
}

// Touch
var ts={active:false,srcId:null,srcGroup:null,srcEl:null,clone:null,origTop:0,origLeft:0,startX:0,startY:0,overEl:null,insertBefore:false};

function _closestItem(el){
  while(el){if(el.tagName==='LI'&&el.classList.contains('item')) return el; el=el.parentElement;}
  return null;
}
function _liGroup(li){
  var p=li.parentElement;
  while(p&&p!==document.body){
    if(p.tagName==='LI'&&p.classList.contains('item')&&p.dataset.id) return p.dataset.id;
    p=p.parentElement;
  }
  return null;
}

function tStart(e,id,gid){
  if(e.touches.length!==1) return;
  e.preventDefault();
  var t=e.touches[0];
  var li=_closestItem(e.currentTarget); if(!li) return;
  var rect=li.getBoundingClientRect();
  ts.active=true; ts.srcId=id; ts.srcGroup=gid||null; ts.srcEl=li;
  ts.startX=t.clientX; ts.startY=t.clientY;
  ts.origLeft=rect.left; ts.origTop=rect.top;
  var clone=li.cloneNode(true);
  clone.style.cssText='position:fixed;left:'+rect.left+'px;top:'+rect.top+'px;width:'+rect.width+'px;'
    +'opacity:.75;z-index:9999;pointer-events:none;border-radius:6px;box-shadow:0 4px 20px rgba(0,0,0,.6)';
  document.body.appendChild(clone);
  ts.clone=clone;
  li.classList.add('dragging');
  document.addEventListener('touchmove',tMove,{passive:false});
  document.addEventListener('touchend',tEnd,{passive:false});
}

function tMove(e){
  if(!ts.active) return;
  e.preventDefault();
  var t=e.touches[0];
  ts.clone.style.top=(ts.origTop+t.clientY-ts.startY)+'px';
  ts.clone.style.left=(ts.origLeft+t.clientX-ts.startX)+'px';
  var m=80;
  if(t.clientY<m) _autoScrollStart(-1);
  else if(t.clientY>window.innerHeight-m) _autoScrollStart(1);
  else _autoScrollStop();
  ts.clone.style.display='none';
  var el=document.elementFromPoint(t.clientX,t.clientY);
  ts.clone.style.display='';
  var li=_closestItem(el);
  if(ts.overEl&&ts.overEl!==li) _clearDragClasses(ts.overEl);
  ts.overEl=null; ts.insertBefore=false;
  if(li&&li!==ts.srcEl&&li.dataset.id){
    var lg=_liGroup(li);
    var tgt=_findAnyItem(li.dataset.id);
    if(!tgt) return;
    if(tgt.type==='folder'&&tgt.id===ts.srcGroup) return;
    if(ts.srcGroup&&lg&&ts.srcGroup!==lg) return;
    if(!ts.srcGroup&&lg) return;
    var srcItem2=_findItem(ts.srcId);
    if(tgt.type==='folder'&&!(srcItem2&&srcItem2.type==='folder')){
      var frect2=li.getBoundingClientRect();
      var frelY2=t.clientY-frect2.top;
      li.classList.remove('insert-before','insert-after','folder-drop-target');
      if(frelY2<frect2.height*0.25){ ts.insertBefore=true; li.classList.add('insert-before'); }
      else if(frelY2>frect2.height*0.75){ ts.insertBefore=false; li.classList.add('insert-after'); }
      else li.classList.add('folder-drop-target');
    } else {
      var rect=li.getBoundingClientRect();
      ts.insertBefore=t.clientY<rect.top+rect.height/2;
      li.classList.remove('insert-before','insert-after');
      li.classList.add(ts.insertBefore?'insert-before':'insert-after');
    }
    ts.overEl=li;
  }
}

function tEnd(e){
  document.removeEventListener('touchmove',tMove);
  document.removeEventListener('touchend',tEnd);
  _autoScrollStop();
  if(!ts.active) return;
  var srcId=ts.srcId, srcGroup=ts.srcGroup, overEl=ts.overEl, ib=ts.insertBefore;
  if(ts.clone) ts.clone.remove();
  if(ts.srcEl) ts.srcEl.classList.remove('dragging');
  var isFolderDrop=overEl&&overEl.classList.contains('folder-drop-target');
  var isInsertBefore=overEl&&overEl.classList.contains('insert-before');
  var isInsertAfter=overEl&&overEl.classList.contains('insert-after');
  if(overEl) _clearDragClasses(overEl);
  ts.active=false; ts.srcId=null; ts.srcGroup=null; ts.srcEl=null; ts.clone=null; ts.overEl=null; ts.insertBefore=false;
  if(!overEl||!overEl.dataset.id||overEl.dataset.id===srcId) return;
  if(isFolderDrop){
    _doMove(srcId,srcGroup,overEl.dataset.id);
  } else if(isInsertBefore||isInsertAfter){
    if(srcGroup&&!_liGroup(overEl)){
      var ibId=overEl.dataset.id;
      if(isInsertAfter){
        var flat=state.items.filter(function(i){return i.id!==srcId;});
        var fi=_idxOf(flat.map(function(i){return i.id;}),overEl.dataset.id);
        ibId=(fi>=0&&fi+1<flat.length)?flat[fi+1].id:null;
      }
      _doMove(srcId,srcGroup,null,ibId);
    } else {
      _doReorder(srcId,srcGroup,overEl.dataset.id,ib);
    }
  }
}

function closeModal(id){
  var el=document.getElementById(id);
  if(el) el.classList.remove('open');
}
</script>

<datalist id="uaList">
  <option value="Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/91">Android / Chrome</option>
  <option value="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120">Windows / Chrome</option>
  <option value="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15">iPhone / Safari</option>
  <option value="VLC/3.0.18 LibVLC/3.0.18">VLC</option>
</datalist>
</body>
</html>"""
    _html = _html.replace("__SA_VERSION__", _PLUGIN_VERSION)
    import os as _os
    _html = _html.replace(
        '<html lang="de">',
        '<html lang="' + (_os.environ.get("LANGUAGE", "de") or "de")[:2] + '">')

    # --- longer / more specific strings first ---
    _html = _html.replace(
        "Achtung: Alle vorhandenen Eintr\xe4ge werden gel\xf6scht und durch die Backup-Datei ersetzt. Fortfahren?",
        _("Achtung: Alle vorhandenen Eintr\xe4ge werden gel\xf6scht und durch die Backup-Datei ersetzt. Fortfahren?"))
    _html = _html.replace(
        "Die Eintr\xe4ge aus der Backup-Datei werden zu den vorhandenen hinzugef\xfcgt. Duplikate werden \xfcbersprungen. Fortfahren?",
        _("Die Eintr\xe4ge aus der Backup-Datei werden zu den vorhandenen hinzugef\xfcgt. Duplikate werden \xfcbersprungen. Fortfahren?"))
    _html = _html.replace(
        "Logo f\xfcr alle Streams im Ordner \xfcbernehmen",
        _("Logo f\xfcr alle Streams im Ordner \xfcbernehmen"))
    _html = _html.replace(
        "Alle Eintr\xe4ge und Logos als ZIP exportieren",
        _("Alle Eintr\xe4ge und Logos als ZIP exportieren"))
    _html = _html.replace(
        "User-Agent gilt nur bei Player: exteplayer3 (HLS)",
        _("User-Agent gilt nur bei Player: exteplayer3 (HLS)"))
    _html = _html.replace(
        "Lokaler Playlist Server (HLS Audiofix)",
        _("Lokaler Playlist Server (HLS Audiofix)"))
    _html = _html.replace(
        "Als Quell-Website ausgeben",
        _("Als Quell-Website ausgeben"))
    _html = _html.replace("> Website angeben", ">" + _("Website angeben"))
    _html = _html.replace(
        "Bitte zuerst eine Backup-Datei (.zip) ausw\xe4hlen.",
        _("Bitte zuerst eine Backup-Datei (.zip) ausw\xe4hlen."))
    _html = _html.replace(
        "Bitte mindestens einen Stream ausw\xe4hlen.",
        _("Bitte mindestens einen Stream ausw\xe4hlen."))
    _html = _html.replace(
        "Bitte einen Ordner-Namen eingeben.",
        _("Bitte einen Ordner-Namen eingeben."))
    _html = _html.replace(
        "Bitte einen Ordner ausw\xe4hlen.",
        _("Bitte einen Ordner ausw\xe4hlen."))
    _html = _html.replace(
        "Fehler beim Erstellen des Ordners.",
        _("Fehler beim Erstellen des Ordners."))
    _html = _html.replace(
        "Nur PNG/JPG-Dateien werden unterst\xfctzt.",
        _("Nur PNG/JPG-Dateien werden unterst\xfctzt."))
    _html = _html.replace(
        "Logo-Download fehlgeschlagen: ",
        _("Logo-Download fehlgeschlagen: "))
    _html = _html.replace(
        "Upload fehlgeschlagen: ",
        _("Upload fehlgeschlagen: "))
    _html = _html.replace(
        "Bitte eine URL eingeben",
        _("Bitte eine URL eingeben"))
    _html = _html.replace(
        "URL endet nicht auf .png/.jpg – trotzdem versuchen?",
        _("URL endet nicht auf .png/.jpg – trotzdem versuchen?"))
    _html = _html.replace(
        "Keine Streams in der Datei gefunden.",
        _("Keine Streams in der Datei gefunden."))
    _html = _html.replace(
        "Noch keine Streams in diesem Ordner.",
        _("Noch keine Streams in diesem Ordner."))
    _html = _html.replace(
        "Noch keine Eintr\xe4ge.",
        _("Noch keine Eintr\xe4ge."))
    _html = _html.replace(
        "Ordner und alle enthaltenen Streams l\xf6schen?",
        _("Ordner und alle enthaltenen Streams l\xf6schen?"))
    _html = _html.replace(
        "ZIP-Backup importieren",
        _("ZIP-Backup importieren"))
    _html = _html.replace(
        "Logo-URLs automatisch laden",
        _("Logo-URLs automatisch laden"))
    _html = _html.replace(
        "Alle \xfcbernehmen",
        _("Alle \xfcbernehmen"))
    _html = _html.replace(
        "Alle einklappen",
        _("Alle einklappen"))
    _html = _html.replace(
        "Alle ausklappen",
        _("Alle ausklappen"))
    _html = _html.replace(
        "Eintr\xe4ge hinzuf\xfcgen",
        _("Eintr\xe4ge hinzuf\xfcgen"))
    _html = _html.replace(
        "Alles ersetzen",
        _("Alles ersetzen"))
    _html = _html.replace(
        "M3U importieren",
        _("M3U importieren"))
    _html = _html.replace(
        "Ordner bearbeiten",
        _("Ordner bearbeiten"))
    _html = _html.replace(
        "Stream bearbeiten",
        _("Stream bearbeiten"))
    _html = _html.replace(
        "Eintrag hinzuf\xfcgen",
        _("Eintrag hinzuf\xfcgen"))
    _html = _html.replace(
        "Ordner hinzuf\xfcgen",
        _("Ordner hinzuf\xfcgen"))
    _html = _html.replace(
        "Stream hinzuf\xfcgen",
        _("Stream hinzuf\xfcgen"))
    _html = _html.replace(
        "Stream l\xf6schen?",
        _("Stream l\xf6schen?"))
    _html = _html.replace(
        "In vorhandenen Ordner",
        _("In vorhandenen Ordner"))
    _html = _html.replace(
        "Als neuer Ordner",
        _("Als neuer Ordner"))
    _html = _html.replace(
        "Einzelne Streams",
        _("Einzelne Streams"))
    _html = _html.replace(
        "Import abgeschlossen: ",
        _("Import abgeschlossen: "))
    _html = _html.replace(
        "Import fehlgeschlagen: ",
        _("Import fehlgeschlagen: "))
    _html = _html.replace(
        "Unbekannter Fehler",
        _("Unbekannter Fehler"))
    _html = _html.replace(
        "Name erforderlich",
        _("Name erforderlich"))
    _html = _html.replace(
        "URL erforderlich",
        _("URL erforderlich"))
    _html = _html.replace(
        "Importiere…",
        _("Importiere…"))
    _html = _html.replace(
        "Importieren",
        _("Importieren"))
    _html = _html.replace(
        "Exportieren",
        _("Exportieren"))
    _html = _html.replace(
        "Ausw\xe4hlen",
        _("Ausw\xe4hlen"))
    _html = _html.replace("Abbrechen", _("Abbrechen"))
    _html = _html.replace("Speichern", _("Speichern"))
    _html = _html.replace("Von Ordner", _("Von Ordner"))
    _html = _html.replace("Laden", _("Laden"))
    _html = _html.replace("Weiter", _("Weiter"))
    _html = _html.replace(">Alle<", ">" + _("Alle") + "<")
    _html = _html.replace(">Keine<", ">" + _("Keine") + "<")
    _html = _html.replace(">Ordner<", ">" + _("Ordner") + "<")
    _html = _html.replace(">&#128193; Ordner<", ">&#128193; " + _("Ordner") + "<")
    _html = _html.replace("__FI_BTN__", _("Datei ausw\xe4hlen"))
    _html = _html.replace("__FI_NONE__", _("Keine ausgew\xe4hlt"))
    _html = _html.replace('placeholder="Ordnername"',
                          'placeholder="' + _("Ordnername") + '"')
    _html = _html.replace('placeholder="Name"',
                          'placeholder="' + _("Name") + '"')
    _html = _html.replace('placeholder="URL"',
                          'placeholder="' + _("URL") + '"')
    _html = _html.replace('placeholder="Stream-URL"',
                          'placeholder="' + _("Stream-URL") + '"')
    _html = _html.replace('placeholder="User-Agent (optional)"',
                          'placeholder="' + _("User-Agent (optional)") + '"')
    _html = _html.replace('placeholder="Logo-URL (optional)"',
                          'placeholder="' + _("Logo-URL (optional)") + '"')
    _html = _html.replace('>PNG/JPG<', '>' + _("PNG/JPG") + '<')
    _html = _html.replace('placeholder="Ordner-Name"',
                          'placeholder="' + _("Ordner-Name") + '"')
    _html = _html.replace(" bereits vorhanden, \xfcbersprungen.",
                          " " + _("bereits vorhanden, \xfcbersprungen."))
    _html = _html.replace(" Eintr\xe4ge importiert.",
                          " " + _("Eintr\xe4ge importiert."))
    _html = _html.replace("h2>Eintr\xe4ge ('+",
                          "h2>" + _("Eintr\xe4ge") + " ('+")
    _html = _html.replace("— Keine Ordner vorhanden —",
                          "— " + _("Keine Ordner vorhanden") + " —")
    _html = _html.replace("' gefunden'", "' " + _("gefunden") + "'")
    _html = _html.replace("' mit Logo'", "' " + _("mit Logo") + "'")
    _html = _html.replace("' von '", "' " + _("von") + " '")
    _html = _html.replace("' importiert…'", "' " + _("importiert…") + "'")
    _html = _html.replace("' importiert.'", "' " + _("importiert.") + "'")
    _html = _html.replace("' ausgew\xe4hlt'", "' " + _("ausgew\xe4hlt") + "'")
    _html = _html.replace("&#8592; Zur\xfcck", "&#8592; " + _("Zur\xfcck"))

    # Aufnahme-Modal (statisches HTML)
    _html = _html.replace(">Schlie\xdfen</button>", ">" + _("Schlie\xdfen") + "</button>")
    _html = _html.replace(">Geplante Aufnahme bearbeiten</h3>", ">" + _("Geplante Aufnahme bearbeiten") + "</h3>")
    _html = _html.replace(
        "Dauer (Minuten, leer = bis manuell gestoppt):",
        _("Dauer (Minuten, leer = bis manuell gestoppt):"))

    # Aufnahmen-Sektion (JS-generiert)
    _html = _html.replace("<h2>Aufnahmen</h2>", "<h2>" + _("Aufnahmen") + "</h2>")
    _html = _html.replace(
        "Gestartet/geplant wird \xfcber das &#9679;-Symbol an einem Stream.",
        _("Gestartet/geplant wird \xfcber das &#9679;-Symbol an einem Stream."))
    _html = _html.replace(">Laufende Aufnahmen<", ">" + _("Laufende Aufnahmen") + "<")
    _html = _html.replace("Keine laufende Aufnahme.", _("Keine laufende Aufnahme."))
    _html = _html.replace(">Geplante Aufnahmen<", ">" + _("Geplante Aufnahmen") + "<")
    _html = _html.replace("Keine geplanten Aufnahmen.", _("Keine geplanten Aufnahmen."))
    _html = _html.replace("'unbegrenzt'", "'" + _("unbegrenzt") + "'")
    _html = _html.replace("'bis gestoppt'", "'" + _("bis gestoppt") + "'")

    # Timer-Status-Labels (ganzes Objekt ersetzen, vermeidet Substring-Kollisionen)
    _html = _html.replace(
        "pending: 'geplant', running: 'l\xe4uft', done: 'fertig', error: 'Fehler', cancelled: 'abgebrochen'",
        "pending: '" + _("geplant") + "', running: '" + _("l\xe4uft") + "', done: '" + _("fertig") + "', error: '" + _("Fehler") + "', cancelled: '" + _("abgebrochen") + "'")

    # Aufnahme-Modal-Body (JS-generiert via renderRecordModalBody)
    _html = _html.replace(">30 Min<", ">" + _("30 Min") + "<")
    _html = _html.replace(">1 Std<", ">" + _("1 Std") + "<")
    _html = _html.replace(">2 Std<", ">" + _("2 Std") + "<")
    _html = _html.replace(">3 Std<", ">" + _("3 Std") + "<")
    _html = _html.replace(">6 Std<", ">" + _("6 Std") + "<")
    _html = _html.replace(">Bis gestoppt<", ">" + _("Bis gestoppt") + "<")
    _html = _html.replace('placeholder="Eigene Dauer (Minuten)"', 'placeholder="' + _("Eigene Dauer (Minuten)") + '"')
    _html = _html.replace(">Jetzt aufnehmen</div>", ">" + _("Jetzt aufnehmen") + "</div>")
    _html = _html.replace(">F\xfcr sp\xe4ter planen</div>", ">" + _("F\xfcr sp\xe4ter planen") + "</div>")
    _html = _html.replace(">Timer anlegen</button>", ">" + _("Timer anlegen") + "</button>")
    _html = _html.replace("'Aufnahme: '", "'" + _("Aufnahme: ") + "'")

    # Aufnahme-Alerts und Confirms
    _html = _html.replace("'Diese laufende Aufnahme stoppen?'", "'" + _("Diese laufende Aufnahme stoppen?") + "'")
    _html = _html.replace("'Diesen Aufnahme-Timer l\xf6schen?'", "'" + _("Diesen Aufnahme-Timer l\xf6schen?") + "'")
    _html = _html.replace("'Bitte Name und Startzeit angeben.'", "'" + _("Bitte Name und Startzeit angeben.") + "'")
    _html = _html.replace("'Ungl\xfcltige Startzeit.'", "'" + _("Ungl\xfcltige Startzeit.") + "'")
    _html = _html.replace("'Speichern fehlgeschlagen: '", "'" + _("Speichern fehlgeschlagen: ") + "'")
    _html = _html.replace("'Start fehlgeschlagen: '", "'" + _("Start fehlgeschlagen: ") + "'")
    _html = _html.replace("'Bitte eine g\xfcltige Dauer in Minuten angeben.'", "'" + _("Bitte eine g\xfcltige Dauer in Minuten angeben.") + "'")
    _html = _html.replace("'Bitte Startzeit angeben.'", "'" + _("Bitte Startzeit angeben.") + "'")
    _html = _html.replace("'Anlegen fehlgeschlagen: '", "'" + _("Anlegen fehlgeschlagen: ") + "'")

    return _html
