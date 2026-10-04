# -*- coding: utf-8 -*-
import os
import re

ENIGMA2_DIR = "/etc/enigma2"
BOUQUETS_TV = "/etc/enigma2/bouquets.tv"


def _has_native():
    try:
        from Plugins.SystemPlugins.ServiceApp.serviceapp_caps import HAS_NATIVE_REFERER
        return bool(HAS_NATIVE_REFERER)
    except Exception:
        return False


def _bouquet_slug(value):
    if isinstance(value, bytes):
        name = value.decode("utf-8", "replace")
    else:
        name = value
    for src, dst in [(u"\xe4", u"ae"), (u"\xf6", u"oe"), (u"\xfc", u"ue"),
                     (u"\xc4", u"Ae"), (u"\xd6", u"Oe"), (u"\xdc", u"Ue"), (u"\xdf", u"ss")]:
        name = name.replace(src, dst)
    name = re.sub(u"[^A-Za-z0-9]+", u"_", name).strip(u"_")
    return (name[:60] or u"streamanything").lower()


def _stream_sid(stream_id):
    h = 0
    if isinstance(stream_id, bytes):
        s = stream_id
    else:
        s = (stream_id or u"").encode("utf-8")
    for b in bytearray(s):
        h = (h * 31 + b) & 0xFFFF
    return h or 1


def _encode_url(url):
    return url.replace(":", "%3a").replace(" ", "%20")


def _encode_param(val):
    out = []
    safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    for c in val:
        if c in safe:
            out.append(c)
        else:
            out.append("%%%02x" % ord(c))
    return "".join(out)


def _player_id(stream):
    if stream.get("player") == "gstplayer":
        return 5001
    return 5002


def _build_ref_line(stream, sid):
    url        = stream.get("url", "")
    name       = stream.get("name", "")
    user_agent = stream.get("user_agent", "")
    referer    = stream.get("referer", "")

    for attr in ("url", "name", "user_agent", "referer"):
        v = locals()[attr]
        if isinstance(v, bytes):
            locals()[attr]  # just a read — assign below
    if isinstance(url,        bytes): url        = url.decode("utf-8",        "replace")
    if isinstance(name,       bytes): name       = name.decode("utf-8",       "replace")
    if isinstance(user_agent, bytes): user_agent = user_agent.decode("utf-8", "replace")
    if isinstance(referer,    bytes): referer    = referer.decode("utf-8",    "replace")

    if referer == "auto":
        referer = "https://www.ard.de/"

    enc_url = _encode_url(url)

    param_parts = []
    if user_agent:
        param_parts.append("User-Agent=" + _encode_param(user_agent))
    if referer:
        param_parts.append("Referer=" + _encode_param(referer))
    params = ("|" + "&".join(param_parts)) if param_parts else ""

    pid = _player_id(stream)
    return "#SERVICE %d:0:1:%X:0:0:0:0:0:0:%s%s:%s" % (pid, sid, enc_url, params, name)


def _get_picon_dir():
    try:
        from Components.config import config
        pdir = config.usage.picon_dir.value
        if isinstance(pdir, bytes):
            pdir_b = pdir
            pdir   = pdir.decode("utf-8", "replace")
        else:
            pdir_b = pdir.encode("utf-8")
        if pdir and os.path.isdir(pdir_b):
            return pdir
    except Exception:
        pass
    for d in ["/usr/share/enigma2/picon", "/media/hdd/picon", "/media/usb/picon"]:
        if os.path.isdir(d.encode("utf-8")):
            return d
    return None


def _copy_picon(stream, picon_dir):
    logo_rel = stream.get("logo", "")
    if not logo_rel:
        return
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    if isinstance(plugin_dir, bytes):
        plugin_dir = plugin_dir.decode("utf-8", "replace")
    logo_path   = os.path.join(plugin_dir, logo_rel)
    logo_path_b = logo_path if isinstance(logo_path, bytes) else logo_path.encode("utf-8")
    if not os.path.isfile(logo_path_b):
        return

    sid  = _stream_sid(stream.get("id", ""))
    pid  = _player_id(stream)
    picon_name = "%d_0_1_%X_0_0_0_0_0_0.png" % (pid, sid)
    pdir = picon_dir if isinstance(picon_dir, str) else picon_dir.decode("utf-8", "replace")
    picon_path   = os.path.join(pdir, picon_name)
    picon_path_b = picon_path if isinstance(picon_path, bytes) else picon_path.encode("utf-8")

    try:
        import subprocess
        subprocess.call([b"/usr/bin/ffmpeg", b"-y", b"-i", logo_path_b,
                         b"-vf", b"scale=220:132:force_original_aspect_ratio=decrease,pad=220:132:(ow-iw)/2:(oh-ih)/2:color=black@0.0",
                         b"-pix_fmt", b"rgba",
                         b"-map_metadata", b"-1",
                         b"-update", b"1", picon_path_b])
    except Exception:
        pass


def _ensure_in_bouquets_tv(filename):
    ref_line = '#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "%s" ORDER BY bouquet' % filename
    try:
        btv_b = BOUQUETS_TV.encode("utf-8")
        try:
            with open(btv_b, "r") as f:
                content = f.read()
        except Exception:
            content = ""
        if filename not in content:
            content = content.rstrip("\n") + "\n" + ref_line + "\n"
            with open(btv_b, "w") as f:
                f.write(content)
    except Exception:
        pass


def _reload_bouquets():
    try:
        from enigma import eDVBDB
        eDVBDB.getInstance().reloadBouquets()
    except Exception:
        pass


def _merge_bouquet(existing, new_entries):
    """Merged neue (ref_line, desc_line)-Paare in einen bestehenden Bouquet-Inhalt.
    Eintraege mit gleicher SID werden ersetzt, neue werden angehaengt."""
    sid_re = re.compile(r"^#SERVICE \d+:0:1:([0-9a-fA-F]+):", re.IGNORECASE)

    new_by_sid = {}
    for ref_line, desc_line in new_entries:
        m = sid_re.match(ref_line)
        if m:
            new_by_sid[m.group(1).lower()] = (ref_line, desc_line)

    out       = []
    skip_next = False
    for line in existing.split("\n"):
        if skip_next:
            skip_next = False
            continue
        m = sid_re.match(line)
        if m and m.group(1).lower() in new_by_sid:
            ref_line, desc_line = new_by_sid.pop(m.group(1).lower())
            out.append(ref_line)
            out.append(desc_line)
            skip_next = True
            continue
        out.append(line)

    while out and out[-1].strip() == "":
        out.pop()

    for ref_line, desc_line in new_by_sid.values():
        out.append(ref_line)
        out.append(desc_line)

    return "\n".join(out) + "\n"


def export_bouquet(bouquet_name, streams, picon_dir=None, reload=True):
    if not streams:
        return
    if isinstance(bouquet_name, bytes):
        bouquet_name = bouquet_name.decode("utf-8", "replace")

    slug       = _bouquet_slug(bouquet_name)
    filename   = "userbouquet.sa_%s.tv" % slug
    filepath   = os.path.join(ENIGMA2_DIR, filename)
    filepath_b = filepath.encode("utf-8")

    new_entries = []
    for stream in streams:
        if stream.get("type") == "folder":
            continue
        sid = _stream_sid(stream.get("id", ""))
        ref_line = _build_ref_line(stream, sid)
        desc = stream.get("name", "")
        if isinstance(desc, bytes):
            desc = desc.decode("utf-8", "replace")
        new_entries.append((ref_line, "#DESCRIPTION " + desc))

    if os.path.isfile(filepath_b):
        try:
            with open(filepath_b, "r") as f:
                existing = f.read()
        except Exception:
            existing = "#NAME " + bouquet_name + "\n"
        content = _merge_bouquet(existing, new_entries)
    else:
        lines = ["#NAME " + bouquet_name]
        for ref_line, desc_line in new_entries:
            lines.append(ref_line)
            lines.append(desc_line)
        content = "\n".join(lines) + "\n"

    content_b = content.encode("utf-8")
    with open(filepath_b, "wb") as f:
        f.write(content_b)

    _ensure_in_bouquets_tv(filename)

    if picon_dir:
        for stream in streams:
            if stream.get("type") != "folder":
                _copy_picon(stream, picon_dir)

    if reload:
        _reload_bouquets()


def export_bouquet_items(items, default_name):
    """items: Liste aus Streams und/oder Ordnern (wie aus dem Plugin-Menü).
    Ordner werden mit ihrem Namen als Bouquet exportiert; einzelne Streams
    landen im Standard-Bouquet (default_name)."""
    if not _has_native():
        return False, "serviceapp nicht verfügbar"
    picon_dir   = _get_picon_dir()
    root_streams = []
    for item in items:
        if item.get("type") == "folder":
            fstreams = item.get("streams", [])
            if fstreams:
                fname = item.get("name") or default_name
                export_bouquet(fname, fstreams, picon_dir=picon_dir, reload=False)
        else:
            root_streams.append(item)
    if root_streams:
        export_bouquet(default_name, root_streams, picon_dir=picon_dir, reload=False)
    _reload_bouquets()
    return True, None


def export_folder(folder_item, default_name):
    return export_bouquet_items([folder_item], default_name)


def export_all(all_items, default_name, by_folder):
    if not _has_native():
        return False, "serviceapp nicht verfügbar"
    if isinstance(default_name, bytes):
        default_name = default_name.decode("utf-8", "replace")

    root_streams = [i for i in all_items if i.get("type") != "folder"]
    folders      = [i for i in all_items if i.get("type") == "folder"]
    picon_dir    = _get_picon_dir()

    if by_folder:
        for folder in folders:
            fstreams = folder.get("streams", [])
            if fstreams:
                fname = folder.get("name") or default_name
                export_bouquet(fname, fstreams, picon_dir=picon_dir, reload=False)
        if root_streams:
            export_bouquet(default_name, root_streams, picon_dir=picon_dir, reload=False)
    else:
        all_streams = list(root_streams)
        for folder in folders:
            all_streams.extend(folder.get("streams", []))
        if all_streams:
            export_bouquet(default_name, all_streams, picon_dir=picon_dir, reload=False)

    _reload_bouquets()
    return True, None
