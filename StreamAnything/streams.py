# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import hashlib
import io
import json
import os
import threading
import uuid

_config_lock = threading.Lock()

CONFIG_FILE = "/etc/enigma2/streamanything.json"
LOGO_DIR    = os.path.join(os.path.dirname(__file__), "logos")

_DEFAULTS = {
    "webif_port": 8090,
    "items":      [],
}


def _load_raw():
    try:
        if os.path.exists(CONFIG_FILE):
            with io.open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return dict(_DEFAULTS)


def _save_raw(data):
    try:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        if not isinstance(content, bytes):
            content = content.encode("utf-8")
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "wb") as f:
            f.write(content)
        if os.path.exists(CONFIG_FILE) and not os.access(CONFIG_FILE, os.W_OK):
            os.remove(CONFIG_FILE)
        os.rename(tmp, CONFIG_FILE)
        return True
    except Exception:
        return False


def get_config():
    with _config_lock:
        cfg = _load_raw()
        for k, v in _DEFAULTS.items():
            if k not in cfg:
                cfg[k] = v
        _migrate(cfg)
        return cfg


def _migrate(cfg):
    old_mode = cfg.pop("mode", None)
    changed  = False
    for item in cfg.get("items", []):
        if "type" not in item:
            if old_mode == "groups" or "streams" in item:
                item["type"] = "folder"
            else:
                item["type"] = "stream"
            changed = True
    if changed or old_mode is not None:
        _save_raw(cfg)


def save_config(cfg):
    with _config_lock:
        return _save_raw(cfg)


def get_webif_port():
    return int(get_config().get("webif_port", 8090))


def move_stream(stream_id, source_group_id, target_group_id, insert_before_id=None):
    with _config_lock:
        cfg   = _load_raw()
        items = cfg.get("items", [])
        stream = None

        if source_group_id:
            for item in items:
                if item.get("id") == source_group_id and item.get("type") == "folder":
                    src = item.get("streams", [])
                    for i, s in enumerate(src):
                        if s.get("id") == stream_id:
                            stream = src.pop(i)
                            break
                    break
        else:
            for i, item in enumerate(items):
                if item.get("id") == stream_id and item.get("type") == "stream":
                    stream = items.pop(i)
                    break

        if not stream:
            return False

        if target_group_id:
            for item in items:
                if item.get("id") == target_group_id and item.get("type") == "folder":
                    item.setdefault("streams", []).append(stream)
                    break
            else:
                return False
        else:
            if insert_before_id:
                for i, item in enumerate(items):
                    if item.get("id") == insert_before_id:
                        items.insert(i, stream)
                        break
                else:
                    items.append(stream)
            else:
                items.append(stream)

        return _save_raw(cfg)


def set_webif_port(port):
    cfg = get_config()
    cfg["webif_port"] = int(port)
    save_config(cfg)


# ------------------------------------------------------------------
# Flat-Modus: flache Stream-Liste
# Jedes Item: {"id": str, "name": str, "url": str, "logo": str|""}
# ------------------------------------------------------------------

def get_flat_streams():
    return get_config().get("items", [])


def add_flat_stream(name, url, logo="", player="", user_agent="", logo_url="", hls_audio_fix=False):
    cfg = get_config()
    cfg.setdefault("items", []).append({
        "id":            str(uuid.uuid4()),
        "type":          "stream",
        "name":          name,
        "url":           url,
        "logo":          logo,
        "logo_url":      logo_url,
        "player":        player,
        "user_agent":    user_agent,
        "hls_audio_fix": bool(hls_audio_fix),
    })
    save_config(cfg)


def update_flat_stream(stream_id, name=None, url=None, logo=None, player=None,
                       user_agent=None, logo_url=None, hls_audio_fix=None):
    cfg = get_config()
    for item in cfg.get("items", []):
        if item.get("id") == stream_id:
            if name          is not None: item["name"]          = name
            if url           is not None: item["url"]           = url
            if logo          is not None: item["logo"]          = logo
            if logo_url      is not None: item["logo_url"]      = logo_url
            if player        is not None: item["player"]        = player
            if user_agent    is not None: item["user_agent"]    = user_agent
            if hls_audio_fix is not None: item["hls_audio_fix"] = bool(hls_audio_fix)
            break
    save_config(cfg)


def delete_flat_stream(stream_id):
    cfg = get_config()
    cfg["items"] = [i for i in cfg.get("items", []) if i.get("id") != stream_id]
    save_config(cfg)


def reorder_flat_streams(id_list):
    cfg = get_config()
    by_id = {i["id"]: i for i in cfg.get("items", [])}
    cfg["items"] = [by_id[sid] for sid in id_list if sid in by_id]
    save_config(cfg)


# ------------------------------------------------------------------
# Group-Modus: Gruppen mit je einer Stream-Liste
# Gruppe:  {"id": str, "name": str, "logo": str, "streams": [...]}
# Stream:  {"id": str, "name": str, "url": str}
# ------------------------------------------------------------------

def get_groups():
    return get_config().get("items", [])


def add_group(name, logo="", logo_url=""):
    cfg = get_config()
    new_id = str(uuid.uuid4())
    cfg.setdefault("items", []).append({
        "id":       new_id,
        "type":     "folder",
        "name":     name,
        "logo":     logo,
        "logo_url": logo_url,
        "streams":  [],
    })
    save_config(cfg)
    return new_id


def update_group(group_id, name=None, logo=None, logo_url=None):
    cfg = get_config()
    for grp in cfg.get("items", []):
        if grp.get("id") == group_id:
            if name     is not None: grp["name"]     = name
            if logo     is not None: grp["logo"]     = logo
            if logo_url is not None: grp["logo_url"] = logo_url
            break
    save_config(cfg)


def delete_group(group_id):
    cfg = get_config()
    cfg["items"] = [g for g in cfg.get("items", []) if g.get("id") != group_id]
    save_config(cfg)


def reorder_groups(id_list):
    cfg = get_config()
    by_id = {g["id"]: g for g in cfg.get("items", [])}
    cfg["items"] = [by_id[gid] for gid in id_list if gid in by_id]
    save_config(cfg)


def get_group_streams(group_id):
    for grp in get_config().get("items", []):
        if grp.get("id") == group_id:
            return grp.get("streams", [])
    return []


def add_group_stream(group_id, name, url, logo="", player="", user_agent="", logo_url="", hls_audio_fix=False):
    cfg = get_config()
    for grp in cfg.get("items", []):
        if grp.get("id") == group_id:
            grp.setdefault("streams", []).append({
                "id":            str(uuid.uuid4()),
                "name":          name,
                "url":           url,
                "logo":          logo,
                "logo_url":      logo_url,
                "player":        player,
                "user_agent":    user_agent,
                "hls_audio_fix": bool(hls_audio_fix),
            })
            break
    save_config(cfg)


def update_group_stream(group_id, stream_id, name=None, url=None, logo=None, player=None,
                        user_agent=None, logo_url=None, hls_audio_fix=None):
    cfg = get_config()
    for grp in cfg.get("items", []):
        if grp.get("id") == group_id:
            for s in grp.get("streams", []):
                if s.get("id") == stream_id:
                    if name          is not None: s["name"]          = name
                    if url           is not None: s["url"]           = url
                    if logo          is not None: s["logo"]          = logo
                    if logo_url      is not None: s["logo_url"]      = logo_url
                    if player        is not None: s["player"]        = player
                    if user_agent    is not None: s["user_agent"]    = user_agent
                    if hls_audio_fix is not None: s["hls_audio_fix"] = bool(hls_audio_fix)
                    break
            break
    save_config(cfg)


def delete_group_stream(group_id, stream_id):
    cfg = get_config()
    for grp in cfg.get("items", []):
        if grp.get("id") == group_id:
            grp["streams"] = [s for s in grp.get("streams", []) if s.get("id") != stream_id]
            break
    save_config(cfg)


def reorder_group_streams(group_id, id_list):
    cfg = get_config()
    for grp in cfg.get("items", []):
        if grp.get("id") == group_id:
            by_id = {s["id"]: s for s in grp.get("streams", [])}
            grp["streams"] = [by_id[sid] for sid in id_list if sid in by_id]
            break
    save_config(cfg)


# ------------------------------------------------------------------
# Logo-Hilfsfunktionen
# ------------------------------------------------------------------

def logo_path_for(filename):
    return os.path.join(LOGO_DIR, filename)


def cleanup_orphaned_logos():
    import re
    uuid_re = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.png$'
    )
    try:
        cfg = _load_raw()
        referenced = set()
        for item in cfg.get("items", []):
            if item.get("logo"):
                referenced.add(os.path.basename(item["logo"]))
            for s in item.get("streams", []):
                if s.get("logo"):
                    referenced.add(os.path.basename(s["logo"]))
        for fname in os.listdir(LOGO_DIR):
            if uuid_re.match(fname) and fname not in referenced:
                try:
                    os.remove(os.path.join(LOGO_DIR, fname))
                except Exception:
                    pass
    except Exception:
        pass


def _ensure_rgba_png(data):
    """Wandelt ein RGB-PNG (color_type=2) in RGBA um, damit Enigma2 es laden kann."""
    import struct, zlib
    if len(data) < 33 or data[25:26] != b'\x02':
        return data  # kein RGB-PNG
    try:
        # IHDR patchen: color_type 2 → 6 (RGBA)
        ihdr_data = bytearray(data[16:29])
        ihdr_data[9] = 6
        ihdr_bytes = bytes(ihdr_data)
        new_crc = struct.pack('>I', zlib.crc32(b'IHDR' + ihdr_bytes) & 0xFFFFFFFF)
        width  = struct.unpack('>I', data[16:20])[0]
        height = struct.unpack('>I', data[20:24])[0]
        # IDAT-Chunks sammeln und dekomprimieren
        pos = 8
        idat_chunks = []
        while pos + 12 <= len(data):
            length = struct.unpack('>I', data[pos:pos+4])[0]
            ctype  = data[pos+4:pos+8]
            cdata  = data[pos+8:pos+8+length]
            if ctype == b'IDAT':
                idat_chunks.append(cdata)
            pos += 12 + length
        pixels = bytearray(zlib.decompress(b''.join(idat_chunks)))
        # RGB → RGBA: Filter-Byte + je 3 RGB-Bytes → Filter-Byte + je 4 RGBA-Bytes
        stride_rgb  = 1 + width * 3
        stride_rgba = 1 + width * 4
        out = bytearray(height * stride_rgba)
        for y in range(height):
            out[y * stride_rgba] = pixels[y * stride_rgb]
            for x in range(width):
                src = y * stride_rgb  + 1 + x * 3
                dst = y * stride_rgba + 1 + x * 4
                out[dst:dst+3] = pixels[src:src+3]
                out[dst+3] = 0xFF
        compressed = zlib.compress(bytes(out), 9)
        idat_len = struct.pack('>I', len(compressed))
        idat_crc = struct.pack('>I', zlib.crc32(b'IDAT' + compressed) & 0xFFFFFFFF)
        # Neues PNG zusammensetzen (bytearray für Python 2/3-Kompatibilität)
        result = bytearray(data[:16])
        result += ihdr_bytes
        result += bytearray(new_crc)
        result += bytearray(idat_len + b'IDAT' + compressed + idat_crc)
        result += bytearray(b'\x00\x00\x00\x00IEND\xaeB`\x82')
        return bytes(result)
    except Exception:
        return data


def save_logo_bytes(data, filename=None):
    if not data or data[:4] != b'\x89PNG':
        return None
    data = _ensure_rgba_png(data)
    if not filename:
        filename = hashlib.sha1(data).hexdigest() + ".png"
    path = logo_path_for(filename)
    try:
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
        # Plugin-seitigen Pixmap-Cache bei ersetzter Datei ungültig machen
        try:
            import plugin as _plugin
            _plugin._pixmap_cache.pop(path, None)
        except Exception:
            pass
        return path
    except Exception:
        return None


def fetch_logo_from_url(url):
    try:
        try:
            from urllib2 import urlopen, Request
        except ImportError:
            from urllib.request import urlopen, Request
        import ssl
        ctx = ssl._create_unverified_context()
        req = Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urlopen(req, timeout=10, context=ctx)
        data = resp.read()
        if len(data) > 2 * 1024 * 1024:
            return None
        return save_logo_bytes(data)
    except Exception:
        return None
