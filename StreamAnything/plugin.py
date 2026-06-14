# -*- coding: utf-8 -*-

import os

from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Components.ActionMap import ActionMap
from Components.Label import Label
from enigma import eTimer, ePoint, eSize, getDesktop

try:
    from Components.Pixmap import Pixmap as _Pixmap
except ImportError:
    _Pixmap = None

try:
    from Tools.LoadPixmap import LoadPixmap as _LoadPixmap
except ImportError:
    _LoadPixmap = None

PLUGIN_VERSION = "1.3.1"

_pixmap_cache = {}

def _cached_pixmap(path):
    if path not in _pixmap_cache:
        if _LoadPixmap and os.path.isfile(path):
            _pixmap_cache[path] = _LoadPixmap(_b(path))
        else:
            _pixmap_cache[path] = None
    return _pixmap_cache[path]

import streams as _streams
import webif   as _webif
import youtube as _youtube
import feratel as _feratel
import skylinewebcams as _skyline
import earthtv as _earthtv
import earthcam as _earthcam
from player import play_stream

PLUGIN_DIR = os.path.dirname(__file__)
LOGO_DIR   = os.path.join(PLUGIN_DIR, "logos")

try:
    IS_FHD = getDesktop(0).size().width() > 1280
except Exception:
    IS_FHD = True


def _b(val):
    if isinstance(val, bytes):
        return val
    try:
        return val.encode("utf-8")
    except Exception:
        return str(val)


def _u(val):
    if isinstance(val, bytes):
        return val.decode("utf-8", "replace")
    return val


_SA_DEBUG_FLAG = "/tmp/sa_debug"
_SA_DEBUG_LOG  = "/tmp/streamanything.log"


def _dbg(msg):
    if not os.path.exists(_SA_DEBUG_FLAG):
        return
    try:
        import time
        with open(_SA_DEBUG_LOG, "a") as f:
            f.write("[%.3f] %s\n" % (time.time(), msg))
    except Exception:
        pass


# ------------------------------------------------------------------
# Einstellungen
# ------------------------------------------------------------------
def _get_setting(key, default=False):
    fallback = _SETTINGS_DEFAULTS.get(key, default)
    return _streams.get_config().get("settings", {}).get(key, fallback)


def _set_setting(key, value):
    cfg = _streams.get_config()
    cfg.setdefault("settings", {})[key] = value
    _streams.save_config(cfg)


_SETTINGS = [
    ("wrap_lr",                  "Links/Rechts zum Bl\xc3\xa4ttern",    "toggle"),
    ("prefer_best_quality",      "H\xc3\xb6chste Qualit\xc3\xa4t bevorzugen", "toggle"),
    ("serviceapp_autoconfigure", "ServiceApp auto-konfigurieren", "toggle"),
    ("webif_autostart",          "WebIF im Hintergrund",          "toggle"),
    ("webif_port",               "WebIF Port",                    "port"),
    ("debug_log",                "Debug-Log",                     "toggle"),
]

_PORT_OPTIONS = [8080, 8088, 8090, 8181, 8888, 9000]
_SETTINGS_DEFAULTS = {
    "wrap_lr":                  True,
    "prefer_best_quality":      True,
    "serviceapp_autoconfigure": True,
    "webif_autostart":          True,
    "debug_log":                False,
}


# ------------------------------------------------------------------
# Kachel-Layout  (identisch zu OeMediathek)
# ------------------------------------------------------------------
TILE_COLS      = 4
TILE_ROWS      = 3
TILES_PER_PAGE = TILE_COLS * TILE_ROWS

if IS_FHD:
    TILE_W, TILE_H   = 450, 160
    TILE_LABEL_H     = 38
    TILE_LABEL_GAP   = 8
    _TX = [30, 500, 970, 1440]
    _TY = [180, 426, 672]           # zentriert zwischen Titelleiste (y=93) und Legende (y=960)
    _SCREEN_W, _SCREEN_H = 1920, 1080
    _TITLE_X, _TITLE_Y, _TITLE_W, _TITLE_H = 30, 30, 1860, 60
    _LEGEND_Y  = 960
    _LEGEND_H  = 100
    _CONTENT_Y = 100
    _CONTENT_H = 850
else:
    TILE_W, TILE_H   = 290, 107
    TILE_LABEL_H     = 25
    TILE_LABEL_GAP   = 5
    _TX = [30, 340, 650, 960]
    _TY = [120, 284, 448]           # zentriert zwischen Titelleiste (y=62) und Legende (y=634)
    _SCREEN_W, _SCREEN_H = 1280, 720
    _TITLE_X, _TITLE_Y, _TITLE_W, _TITLE_H = 20, 20, 1240, 40
    _LEGEND_Y  = 634
    _LEGEND_H  = 60
    _CONTENT_Y = 70
    _CONTENT_H = 554

TILE_POSITIONS = [(_TX[c], _TY[r]) for r in range(TILE_ROWS) for c in range(TILE_COLS)]

if IS_FHD:
    LIST_ROWS   = 12
    LIST_ROW_H  = 70
    LIST_ROW_Y0 = _CONTENT_Y
else:
    LIST_ROWS   = 11
    LIST_ROW_H  = 47
    LIST_ROW_Y0 = _CONTENT_Y

_LOGO_W = 220 if IS_FHD else 140
_LOGO_H = 124 if IS_FHD else 79


_eth0_ip_cache   = None
_eth0_ip_fetched = False

def _get_eth0_ip():
    global _eth0_ip_cache, _eth0_ip_fetched
    if not _eth0_ip_fetched:
        try:
            import socket, struct, fcntl
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                _eth0_ip_cache = socket.inet_ntoa(fcntl.ioctl(
                    s.fileno(), 0x8915,
                    struct.pack('256s', b'eth0')
                )[20:24])
            finally:
                s.close()
        except Exception:
            _eth0_ip_cache = None
        _eth0_ip_fetched = True
    return _eth0_ip_cache


def _logo_base_rect(idx):
    tx, ty = TILE_POSITIONS[idx]
    lx = tx + (TILE_W - _LOGO_W) // 2
    ly = ty + (TILE_H - _LOGO_H) // 2
    return lx, ly, _LOGO_W, _LOGO_H


# ------------------------------------------------------------------
# Skin-Templates
# ------------------------------------------------------------------
def _tile_widget(idx, x, y, w, h):
    lw = _LOGO_W
    lh = _LOGO_H
    lx = x + (w - lw) // 2
    ly = y + (h - lh) // 2
    bs = 40 if IS_FHD else 28
    bp = 6  if IS_FHD else 4
    return (
        '<widget name="tile_bg_{i}" position="{x},{y}" size="{w},{h}" '
        'backgroundColor="#1A000000" zPosition="-4"/>'
        '<widget name="tile_logo_{i}" position="{lx},{ly}" size="{lw},{lh}" '
        'alphatest="blend" zPosition="1" transparent="1" scale="1"/>'
        '<widget name="tile_sel_{i}" position="{x},{y}" size="{w},{h}" '
        'alphatest="blend" zPosition="3" transparent="1"/>'
        '<widget name="tile_type_{i}" position="{bx},{by}" size="{bs},{bs}" '
        'alphatest="blend" zPosition="4" transparent="1" scale="1"/>'
        '<widget name="tile_label_{i}" position="{x},{labely}" size="{w},{labelh}" '
        'zPosition="2" font="Regular;{fs}" halign="center" '
        'valign="center" foregroundColor="#00E0E0E0" backgroundColor="#33000000" noWrap="1"/>'
    ).format(
        i=idx, x=x, y=y, w=w, h=h,
        lx=lx, ly=ly, lw=lw, lh=lh,
        labely=y + h + TILE_LABEL_GAP,
        labelh=TILE_LABEL_H,
        fs=22 if IS_FHD else 15,
        bx=x + bp,
        by=y + h - bs - bp,
        bs=bs,
    )


def _build_skin():
    sw, sh = _SCREEN_W, _SCREEN_H
    tiles_xml = "".join(
        _tile_widget(i, x, y, TILE_W, TILE_H)
        for i, (x, y) in enumerate(TILE_POSITIONS)
    )

    if IS_FHD:
        lr_x, lr_w = 30, sw - 60
        lo_x, lo_w = lr_x + 10, 100
        lt_s       = 40
        lt_x       = lo_x + lo_w + 8
        lt_oy      = (LIST_ROW_H - lt_s) // 2
        ll_x       = lt_x + lt_s + 8
        ll_w       = lr_x + lr_w - 10 - ll_x
        l_rf       = 32
        ls_x       = lo_x + lo_w + 5
        ls_w       = lr_x + lr_w - ls_x
    else:
        lr_x, lr_w = 30, sw - 60
        lo_x, lo_w = lr_x + 8, 65
        lt_s       = 26
        lt_x       = lo_x + lo_w + 5
        lt_oy      = (LIST_ROW_H - lt_s) // 2
        ll_x       = lt_x + lt_s + 5
        ll_w       = lr_x + lr_w - 8 - ll_x
        l_rf       = 21
        ls_x       = lo_x + lo_w + 4
        ls_w       = lr_x + lr_w - ls_x

    list_xml = ""
    for i in range(LIST_ROWS):
        y = LIST_ROW_Y0 + i * LIST_ROW_H
        list_xml += (
            '<widget name="list_sel_{i}"   position="{sx},{y}"   size="{sw},{rh}" '
            'backgroundColor="#11962d20" zPosition="1" transparent="0"/>'
            '<widget name="list_grab_{i}"  position="{sx},{y}"   size="{sw},{rh}" '
            'backgroundColor="#11967e00" zPosition="1" transparent="0"/>'
            '<widget name="list_logo_{i}"  position="{lox},{y}"  size="{low},{rh}" '
            'alphatest="blend" zPosition="2" transparent="1" scale="1"/>'
            '<widget name="list_label_{i}" position="{lbx},{y}"  size="{lbw},{rh}" '
            'zPosition="2" font="Regular;{rf}" halign="left" valign="center" '
            'foregroundColor="#00E0E0E0" backgroundColor="#33000000" transparent="1" noWrap="1"/>'
            '<widget name="list_type_{i}"  position="{ltx},{lty}" size="{lts},{lts}" '
            'alphatest="blend" zPosition="2" transparent="1" scale="1"/>'
        ).format(i=i, y=y, sx=ls_x, sw=ls_w, rh=LIST_ROW_H,
                 lox=lo_x, low=lo_w, lbx=ll_x, lbw=ll_w, rf=l_rf,
                 ltx=lt_x, lty=y + lt_oy, lts=lt_s)

    if IS_FHD:
        ly, lh = _LEGEND_Y, _LEGEND_H
        pip_y  = ly + (lh - 60) // 2
        pip_h  = 60
        pip_w  = 8
        fs     = 32
        legend = (
            '<eLabel backgroundColor="#1A000000" position="30,{ly}" size="1860,{lh}" zPosition="-3" transparent="0"/>'
            '<eLabel backgroundColor="#1AEE0000" position="50,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_red"    position="68,{ly}"   size="178,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<eLabel backgroundColor="#1A00AA00" position="298,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_green"  position="316,{ly}"  size="200,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<eLabel backgroundColor="#1ACCAA00" position="606,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_yellow" position="624,{ly}"  size="150,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_ok"     position="796,{ly}"  size="258,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_menu"   position="1076,{ly}" size="280,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_ch"     position="1450,{ly}" size="320,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
            '<widget name="page_label"  position="1790,{ly}" size="80,{lh}"  zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;28" halign="right" valign="center" foregroundColor="#AAAAAA"/>'
        ).format(ly=ly, lh=lh, py=pip_y, ph=pip_h, pw=pip_w, fs=fs)
    else:
        ly, lh = _LEGEND_Y, _LEGEND_H
        pip_y  = ly + (lh - 30) // 2
        pip_h  = 30
        pip_w  = 5
        fs     = 21
        legend = (
            '<eLabel backgroundColor="#1A000000" position="30,{ly}" size="1220,{lh}" zPosition="-3" transparent="0"/>'
            '<eLabel backgroundColor="#1AEE0000" position="33,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_red"    position="42,{ly}"   size="120,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<eLabel backgroundColor="#1A00AA00" position="190,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_green"  position="199,{ly}"  size="130,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<eLabel backgroundColor="#1ACCAA00" position="385,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_yellow" position="394,{ly}"  size="100,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_ok"     position="514,{ly}"  size="172,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_menu"   position="706,{ly}"  size="188,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_ch"     position="955,{ly}"  size="220,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
            '<widget name="page_label"  position="1188,{ly}" size="62,{lh}"  zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="right" valign="center" foregroundColor="#AAAAAA"/>'
        ).format(ly=ly, lh=lh, py=pip_y, ph=pip_h, pw=pip_w, fs=fs)

    tpad = 30 if IS_FHD else 20
    tpx  = _TITLE_X + tpad
    if IS_FHD:
        ttw, wfx, wfw, vtx, vtw = 600, 660, 780, 1490, 370
        tfs, vfs, ifs = 36, 26, 26
    else:
        ttw, wfx, wfw, vtx, vtw = 400, 440, 500, 960, 280
        tfs, vfs, ifs = 24, 18, 18
    return (
        '<screen backgroundColor="transparent" flags="wfNoBorder" '
        'position="0,0" size="{sw},{sh}" title="StreamAnything">'
        '<eLabel backgroundColor="#66000000" position="0,0" size="{sw},{sh}" zPosition="-6" transparent="0"/>'
        '<eLabel backgroundColor="#0A000000" position="{tx},{ty}" size="{tw},{th}" zPosition="-5" transparent="0"/>'
        '<eLabel backgroundColor="#00cc3d2d" position="{tx},{tby}" size="{tw},{tbs}" zPosition="-4" transparent="0"/>'
        '<eLabel backgroundColor="#33000000" position="{tx},{cy}" size="{tw},{ch}" zPosition="-5" transparent="0"/>'
        '<widget name="title" position="{tpx},{ty}" size="{ttw},{th}" '
        'zPosition="4" backgroundColor="#0A000000" font="Regular;{tfs}" halign="left" '
        'valign="center" foregroundColor="#00cc3d2d"/>'
        '<widget name="webif_addr" position="{wfx},{ty}" size="{wfw},{th}" '
        'zPosition="4" backgroundColor="#0A000000" font="Regular;{ifs}" halign="center" '
        'valign="center" foregroundColor="#00888888"/>'
        '<eLabel text="v{ver}" position="{vtx},{ty}" size="{vtw},{th}" '
        'zPosition="4" backgroundColor="#0A000000" font="Regular;{vfs}" halign="right" '
        'valign="center" foregroundColor="#00888888"/>'
        '{legend}'
        '{tiles}'
        '{list_rows}'
        '</screen>'
    ).format(
        sw=sw, sh=sh,
        tx=_TITLE_X, ty=_TITLE_Y, tw=_TITLE_W, th=_TITLE_H,
        tby=_TITLE_Y + _TITLE_H, tbs=3 if IS_FHD else 2,
        tpx=tpx, ttw=ttw, wfx=wfx, wfw=wfw, vtx=vtx, vtw=vtw, ver=PLUGIN_VERSION,
        cy=_CONTENT_Y, ch=_CONTENT_H,
        tfs=tfs, vfs=vfs, ifs=ifs,
        legend=legend,
        tiles=tiles_xml,
        list_rows=list_xml,
    )


def _build_settings_skin():
    n = len(_SETTINGS)
    if IS_FHD:
        sx, sy          = 510, 200
        sw              = 900
        tf, rf          = 36, 26
        row_h           = 70
        row_y0          = 110
        sel_h           = 60
        val_w           = 200
        leg_h           = 60
        sh              = 140 + n * row_h + 40 + leg_h
        leg_y           = sh - leg_h
        pip_py          = leg_y + (leg_h - 30) // 2
        pip_h, pip_w    = 30, 6
        lfs             = 26
        ok_x,  ok_w     = 20,  260
        gp_x, g_x, g_w  = 300, 316, 248
        rp_x, r_x, r_w  = 586, 602, 248
    else:
        sx, sy          = 340, 133
        sw              = 600
        tf, rf          = 24, 18
        row_h           = 47
        row_y0          = 73
        sel_h           = 40
        val_w           = 133
        leg_h           = 40
        sh              = 93 + n * row_h + 27 + leg_h
        leg_y           = sh - leg_h
        pip_py          = leg_y + (leg_h - 20) // 2
        pip_h, pip_w    = 20, 5
        lfs             = 18
        ok_x,  ok_w     = 15,  170
        gp_x, g_x, g_w  = 200, 213, 164
        rp_x, r_x, r_w  = 393, 406, 164

    rows_xml = ""
    for i in range(n):
        y = row_y0 + i * row_h
        rows_xml += (
            '<widget name="s_sel_{i}" position="0,{y}" size="{w},{sh}" '
            'backgroundColor="#11962d20" zPosition="-1" transparent="0"/>'
            '<widget name="s_label_{i}" position="20,{y}" size="{lw},{sh}" '
            'zPosition="1" font="Regular;{rf}" halign="left" '
            'valign="center" foregroundColor="#00E0E0E0" backgroundColor="#33000000" transparent="1"/>'
            '<widget name="s_value_{i}" position="{vx},{y}" size="{vw},{sh}" '
            'zPosition="1" font="Regular;{rf}" halign="right" '
            'valign="center" foregroundColor="#00FFFFFF" backgroundColor="#33000000" transparent="1"/>'
        ).format(
            i=i, y=y, w=sw, sh=sel_h,
            lw=sw - val_w - 40,
            vx=sw - val_w - 20, vw=val_w,
            rf=rf,
        )

    legend_xml = (
        '<eLabel backgroundColor="#1A000000" position="0,{ly}" size="{sw},{lh}" zPosition="-2" transparent="0"/>'
        '<widget name="hint_ok"    position="{okx},{ly}" size="{okw},{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{lfs}" halign="left"  valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
        '<eLabel backgroundColor="#1A00AA00" position="{gpx},{ppy}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
        '<widget name="hint_green" position="{gx},{ly}"  size="{gw},{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{lfs}" halign="left"  valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
        '<eLabel backgroundColor="#1AEE0000" position="{rpx},{ppy}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
        '<widget name="hint_red"   position="{rx},{ly}"  size="{rw},{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{lfs}" halign="left"  valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
    ).format(
        sw=sw, lh=leg_h, ly=leg_y, lfs=lfs,
        pw=pip_w, ph=pip_h, ppy=pip_py,
        okx=ok_x, okw=ok_w,
        gpx=gp_x, gx=g_x, gw=g_w,
        rpx=rp_x, rx=r_x, rw=r_w,
    )

    return (
        '<screen backgroundColor="transparent" flags="wfNoBorder" '
        'position="{sx},{sy}" size="{sw},{sh}">'
        '<eLabel backgroundColor="#1A000000" position="0,0" size="{sw},{sh}" zPosition="-5" transparent="0"/>'
        '<eLabel backgroundColor="#cc3d2d" position="0,0" size="{sw},4" zPosition="1" transparent="0"/>'
        '<widget name="s_title" position="20,20" size="{tw},{th}" '
        'zPosition="1" font="Regular;{tf}" halign="left" '
        'valign="center" foregroundColor="#00cc3d2d" backgroundColor="#1A000000"/>'
        '{rows}'
        '{legend}'
        '</screen>'
    ).format(
        sx=sx, sy=sy, sw=sw, sh=sh,
        tw=sw - 40, th=tf + 14,
        tf=tf,
        rows=rows_xml,
        legend=legend_xml,
    )


# ------------------------------------------------------------------
# Stream-Kontextmen\xc3\xbc (MENU-Taste): Player und User-Agent \xc3\xa4ndern
# ------------------------------------------------------------------
_UA_CHOICES = [
    ("(keiner)",         ""),
    ("Android / Chrome", "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/91"),
    ("Windows / Chrome", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"),
    ("iPhone / Safari",  "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"),
    ("VLC",              "VLC/3.0.18 LibVLC/3.0.18"),
]


def _sa_confirm(session, text, callback):
    def _map(choice):
        callback(bool(choice and choice[1]))
    session.openWithCallback(
        _map, _SAChoiceScreen,
        title=text if isinstance(text, bytes) else _b(_u(text)),
        list=[(_b("Ja"), True), (_b("Nein"), False)],
    )


_CHOICE_MAX_ROWS = 8


def _build_choice_skin(n_rows=None):
    if n_rows is None:
        n_rows = _CHOICE_MAX_ROWS
    if IS_FHD:
        sw, row_h, sel_h  = 700, 60, 52
        title_h, tf, rf   = 70, 32, 26
        leg_h, lfs        = 60, 26
        pip_h, pip_w      = 30, 6
        ok_x,  ok_w       = 20,  190
        gp_x, g_x, g_w   = 224, 240, 180
        rp_x, r_x, r_w   = 434, 450, 180
        sx = (1920 - sw) // 2
    else:
        sw, row_h, sel_h  = 460, 40, 34
        title_h, tf, rf   = 48, 22, 18
        leg_h, lfs        = 40, 18
        pip_h, pip_w      = 20, 5
        ok_x,  ok_w       = 15,  126
        gp_x, g_x, g_w   = 150, 163, 118
        rp_x, r_x, r_w   = 290, 303, 118
        sx = (1280 - sw) // 2
    row_y0  = title_h + 8
    leg_y   = row_y0 + n_rows * row_h + 8
    sh      = leg_y + leg_h
    sy      = ((1080 if IS_FHD else 720) - sh) // 2
    pip_py  = leg_y + (leg_h - pip_h) // 2
    rows    = ""
    for i in range(n_rows):
        y = row_y0 + i * row_h
        rows += (
            '<widget name="cs_{i}" position="0,{y}" size="{sw},{sh}" '
            'backgroundColor="#11962d20" zPosition="1" transparent="0"/>'
            '<widget name="cl_{i}" position="20,{y}" size="{lw},{sh}" '
            'zPosition="2" font="Regular;{rf}" halign="left" valign="center" '
            'foregroundColor="#00E0E0E0" backgroundColor="#33000000" transparent="1" noWrap="1"/>'
        ).format(i=i, y=y, sw=sw, sh=sel_h, lw=sw - 30, rf=rf)
    legend = (
        '<eLabel backgroundColor="#1A000000" position="0,{ly}" size="{sw},{lh}" zPosition="-2" transparent="0"/>'
        '<widget name="ch_ok"    position="{okx},{ly}" size="{okw},{lh}" zPosition="4" transparent="1" '
        'backgroundColor="#1A000000" font="Regular;{lfs}" halign="left" valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
        '<widget name="ch_pip_g" position="{gpx},{ppy}" size="{pw},{ph}" zPosition="2" backgroundColor="#1A00AA00" transparent="0"/>'
        '<widget name="ch_green" position="{gx},{ly}"  size="{gw},{lh}" zPosition="4" transparent="1" '
        'backgroundColor="#1A000000" font="Regular;{lfs}" halign="left" valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
        '<widget name="ch_pip_r" position="{rpx},{ppy}" size="{pw},{ph}" zPosition="2" backgroundColor="#1AEE0000" transparent="0"/>'
        '<widget name="ch_red"   position="{rx},{ly}"  size="{rw},{lh}" zPosition="4" transparent="1" '
        'backgroundColor="#1A000000" font="Regular;{lfs}" halign="left" valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
    ).format(
        sw=sw, lh=leg_h, ly=leg_y, lfs=lfs,
        pw=pip_w, ph=pip_h, ppy=pip_py,
        okx=ok_x, okw=ok_w,
        gpx=gp_x, gx=g_x, gw=g_w,
        rpx=rp_x, rx=r_x, rw=r_w,
    )
    return (
        '<screen backgroundColor="transparent" flags="wfNoBorder" '
        'position="{sx},{sy}" size="{sw},{sh}">'
        '<eLabel backgroundColor="#1A000000" position="0,0" size="{sw},{sh}" zPosition="-5" transparent="0"/>'
        '<eLabel backgroundColor="#962d20" position="0,0" size="{sw},4" zPosition="1" transparent="0"/>'
        '<widget name="ct" position="20,14" size="{tw},{th}" zPosition="1" '
        'font="Regular;{tf}" halign="left" valign="center" '
        'foregroundColor="#00cc3d2d" backgroundColor="#1A000000"/>'
        '{rows}{legend}'
        '</screen>'
    ).format(sx=sx, sy=sy, sw=sw, sh=sh, tw=sw - 40, th=tf + 14, tf=tf,
             rows=rows, legend=legend)


class _SAChoiceScreen(Screen):
    skin = _build_choice_skin()

    def __init__(self, session, title=b"", list=None, on_save_fn=None, has_changes_fn=None):
        n = min(len(list or []), _CHOICE_MAX_ROWS)
        if n < _CHOICE_MAX_ROWS:
            self.skin = _build_choice_skin(n)
        Screen.__init__(self, session)
        self._choices        = list or []
        self._sel            = 0
        self._scroll         = 0
        self._moved          = False
        self._on_save_fn     = on_save_fn
        self._has_changes_fn = has_changes_fn
        self["ct"]       = Label(title if isinstance(title, bytes) else _b(_u(title)))
        self["ch_ok"]    = Label(_b("OK = Ausw\xc3\xa4hlen"))
        self["ch_pip_g"] = Label(_b(""))
        self["ch_green"] = Label(_b("Speichern"))
        self["ch_pip_r"] = Label(_b(""))
        self["ch_red"]   = Label(_b("Abbrechen"))
        if not on_save_fn:
            self["ch_pip_g"].hide()
            self["ch_green"].hide()
            self["ch_pip_r"].hide()
            self["ch_red"].hide()
        for i in range(_CHOICE_MAX_ROWS):
            self["cs_%d" % i] = Label(_b(""))
            self["cl_%d" % i] = Label(_b(""))
            self["cs_%d" % i].hide()
            self["cl_%d" % i].hide()
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions"],
            {
                "ok":           self._ok,
                "green":        self._green,
                "red":          self._on_cancel,
                "cancel":       self._on_cancel,
                "up":           lambda: self._move(-1),
                "down":         lambda: self._move(1),
                "upRepeated":   lambda: self._move(-1),
                "downRepeated": lambda: self._move(1),
            },
            -1,
        )
        self._render()

    def _move(self, delta):
        total = len(self._choices)
        if not total:
            return
        self._sel    = (self._sel + delta) % total
        self._moved  = True
        if self._sel < self._scroll:
            self._scroll = self._sel
        elif self._sel >= self._scroll + _CHOICE_MAX_ROWS:
            self._scroll = self._sel - _CHOICE_MAX_ROWS + 1
        self._render()

    def _render(self):
        total = len(self._choices)
        for i in range(_CHOICE_MAX_ROWS):
            idx = self._scroll + i
            if idx < total:
                lbl = self._choices[idx][0]
                self["cl_%d" % i].setText(lbl if isinstance(lbl, bytes) else _b(_u(lbl)))
                self["cl_%d" % i].show()
                if idx == self._sel:
                    self["cs_%d" % i].show()
                else:
                    self["cs_%d" % i].hide()
            else:
                self["cl_%d" % i].hide()
                self["cs_%d" % i].hide()

    def _ok(self):
        if self._choices and self._sel < len(self._choices):
            self.close(self._choices[self._sel])
        else:
            self.close(None)

    def _green(self):
        if self._on_save_fn:
            self._on_save_fn()
            self.close(None)
        else:
            self._ok()

    def _on_cancel(self):
        has_changes = self._has_changes_fn() if self._has_changes_fn else self._moved
        if not has_changes:
            self.close(None)
            return
        def on_confirm(result):
            if result:
                self.close(None)
        _sa_confirm(self.session, _b("Ohne Speichern beenden?"), on_confirm)


def _stream_context_menu(session, item, update_fn, refresh_cb, delete_fn=None, _original=None):
    if _original is None:
        _original = dict(
            player      = item.get("player", ""),
            user_agent  = item.get("user_agent", ""),
            hls_audio_fix = item.get("hls_audio_fix", False),
        )

    def _reopen():
        _stream_context_menu(session, item, update_fn, refresh_cb, delete_fn, _original)

    def _has_changes():
        return (item.get("player", "")        != _original["player"]       or
                item.get("user_agent", "")    != _original["user_agent"]   or
                item.get("hls_audio_fix", False) != _original["hls_audio_fix"])

    def _save():
        update_fn(item)
        refresh_cb()

    _PLAYER_LABELS = {
        "":            "Auto",
        "exteplayer3": "exteplayer3",
        "gstplayer":   "GStreamer",
        "default":     "Standard",
    }
    cur_player  = item.get("player", "")
    cur_ua      = _u(item.get("user_agent", ""))
    cur_hls_fix = item.get("hls_audio_fix", False)
    cur_ua_label = next((label for label, val in _UA_CHOICES if val == cur_ua), None)
    if cur_ua_label is None:
        cur_ua_label = (cur_ua[:20] + "...") if len(cur_ua) > 20 else (cur_ua or "(keiner)")

    choices = [
        (_b("Player:     " + _PLAYER_LABELS.get(cur_player, "Auto")),              "player"),
        (_b("User-Agent: " + cur_ua_label),                                         "ua"),
        (_b("Lok. Playlist Server: " + ("EIN" if cur_hls_fix else "AUS")),          "hls_fix"),
        (_b("L\xc3\xb6schen"),                                                      "delete"),
    ]

    def on_ua(choice):
        if choice is None:
            _reopen()
            return
        item["user_agent"] = choice[1]
        _reopen()

    def on_player(choice):
        if choice is None:
            _reopen()
            return
        item["player"] = choice[1]
        _reopen()

    def on_delete_confirm(answer):
        if answer and delete_fn:
            delete_fn()

    def on_choice(choice):
        if choice is None:
            return
        if choice[1] == "player":
            pchoices = [
                (_b("Auto"),        ""),
                (_b("exteplayer3"), "exteplayer3"),
                (_b("GStreamer"),   "gstplayer"),
                (_b("Standard"),   "default"),
            ]
            session.openWithCallback(on_player, _SAChoiceScreen,
                                     title=_b("Player w\xc3\xa4hlen"), list=pchoices)
        elif choice[1] == "ua":
            ua_list = [(_b(label), val) for label, val in _UA_CHOICES]
            session.openWithCallback(on_ua, _SAChoiceScreen,
                                     title=_b("User-Agent w\xc3\xa4hlen"), list=ua_list)
        elif choice[1] == "hls_fix":
            item["hls_audio_fix"] = not item.get("hls_audio_fix", False)
            _reopen()
        elif choice[1] == "delete" and delete_fn:
            _sa_confirm(session, _b("Stream l\xc3\xb6schen?"), on_delete_confirm)

    session.openWithCallback(on_choice, _SAChoiceScreen,
                             title=_b(_u(item.get("name", "Stream"))),
                             list=choices,
                             on_save_fn=_save,
                             has_changes_fn=_has_changes)


# ------------------------------------------------------------------
# Settings-Screen
# ------------------------------------------------------------------
class StreamAnywhereSettingsScreen(Screen):

    skin = _build_settings_skin()

    def __init__(self, session):
        Screen.__init__(self, session)
        self._sel = 0

        self["s_title"] = Label(_b("Einstellungen"))
        for i, (key, label, kind) in enumerate(_SETTINGS):
            self["s_sel_%d"   % i] = Label(_b(""))
            self["s_label_%d" % i] = Label(_b(label))
            self["s_value_%d" % i] = Label(_b(""))

        self["hint_ok"]    = Label(_b("OK = \xc3\x84ndern"))
        self["hint_green"] = Label(_b("Speichern"))
        self["hint_red"]   = Label(_b("Abbrechen"))

        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions"],
            {
                "ok":     self._on_ok,
                "cancel": self._on_red,
                "up":     self._move_up,
                "down":   self._move_down,
                "green":  self._on_green,
                "red":    self._on_red,
            },
            -1,
        )

        self._pending = {}
        for key, label, kind in _SETTINGS:
            if kind == "toggle":
                self._pending[key] = _get_setting(key, _SETTINGS_DEFAULTS.get(key, False))
            elif kind == "port":
                self._pending[key] = _streams.get_webif_port()
        self._original = dict(self._pending)

        self._refresh()

    def _refresh(self):
        for i, (key, label, kind) in enumerate(_SETTINGS):
            if kind == "toggle":
                val = self._pending.get(key, _SETTINGS_DEFAULTS.get(key, False))
                self["s_value_%d" % i].setText(_b("EIN" if val else "AUS"))
            elif kind == "port":
                self["s_value_%d" % i].setText(_b(str(self._pending.get(key, 8090))))
            else:
                self["s_value_%d" % i].setText(_b(""))
            if i == self._sel:
                self["s_sel_%d" % i].show()
            else:
                self["s_sel_%d" % i].hide()

    def _move_up(self):
        if self._sel > 0:
            self._sel -= 1
            self._refresh()

    def _move_down(self):
        if self._sel < len(_SETTINGS) - 1:
            self._sel += 1
            self._refresh()

    def _on_ok(self):
        key, label, kind = _SETTINGS[self._sel]
        if kind == "toggle":
            self._pending[key] = not self._pending.get(key, _SETTINGS_DEFAULTS.get(key, False))
            self._refresh()
        elif kind == "port":
            try:
                from Screens.ChoiceBox import ChoiceBox
            except ImportError:
                return
            cur = self._pending.get(key, 8090)
            choices = [(_b(str(p) + (" *" if p == cur else "")), p) for p in _PORT_OPTIONS]
            def on_port(choice):
                if choice is None:
                    return
                self._pending[key] = choice[1]
                self._refresh()
            self.session.openWithCallback(on_port, ChoiceBox,
                                          title=_b("WebIF Port w\xc3\xa4hlen"),
                                          list=choices)

    def _on_green(self):
        for key, label, kind in _SETTINGS:
            if kind == "toggle":
                _set_setting(key, self._pending[key])
            elif kind == "port":
                new_port = self._pending.get(key, 8090)
                if new_port != _streams.get_webif_port():
                    _streams.set_webif_port(new_port)
                    _webif.stop()
                    _webif.start(new_port)
        if self._pending.get("debug_log", False):
            try:
                open(_SA_DEBUG_FLAG, "w").close()
            except Exception:
                pass
        else:
            try:
                os.remove(_SA_DEBUG_FLAG)
            except Exception:
                pass
        self.close()

    def _on_red(self):
        if self._pending != self._original:
            def on_confirm(result):
                if result:
                    self.close()
            _sa_confirm(self.session, _b("Einstellungen ohne Speichern verlassen?"), on_confirm)
        else:
            self.close()


# ------------------------------------------------------------------
# Haupt-Kachel-Screen
# ------------------------------------------------------------------
class StreamAnywhereScreen(Screen):

    skin = _build_skin()

    def __init__(self, session):
        Screen.__init__(self, session)
        self._page             = 0
        self._items            = []
        self._timer            = eTimer()
        self._timer.callback.append(self._load)
        self._sort_mode        = False
        self._sort_grabbed_abs = None
        self._sort_backup      = None
        self._config_mtime     = 0
        self._poll_timer       = eTimer()
        self._poll_timer.callback.append(self._poll_config)
        self._list_mode        = _get_setting("list_mode", False)
        self._list_sel         = 0
        self._list_scroll      = 0
        self._prev_render_mode = None

        self["title"]       = Label(_b("StreamAnything"))
        self["hint_red"]    = Label(_b(""))
        self["hint_green"]  = Label(_b(""))
        self["hint_ok"]     = Label(_b(""))
        self["hint_ch"]     = Label(_b("CH+/- = Seite"))
        self["hint_yellow"] = Label(_b(""))
        self["hint_menu"]   = Label(_b(""))
        self["page_label"]  = Label(_b(""))
        self["webif_addr"]  = Label(_b(""))

        for i in range(TILES_PER_PAGE):
            self["tile_bg_%d"    % i] = Label(_b(""))
            self["tile_label_%d" % i] = Label(_b(""))
            if _Pixmap:
                self["tile_logo_%d" % i]  = _Pixmap()
                self["tile_sel_%d" % i]   = _Pixmap()
                self["tile_type_%d" % i]  = _Pixmap()
            self["tile_bg_%d" % i].hide()

        for i in range(LIST_ROWS):
            self["list_sel_%d"   % i] = Label(_b(""))
            self["list_grab_%d"  % i] = Label(_b(""))
            self["list_label_%d" % i] = Label(_b(""))
            if _Pixmap:
                self["list_logo_%d" % i] = _Pixmap()
                self["list_type_%d" % i] = _Pixmap()
            self["list_sel_%d"   % i].hide()
            self["list_grab_%d"  % i].hide()
            self["list_label_%d" % i].hide()

        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions",
             "ChannelSelectBaseActions", "MenuActions", "InfobarSeekActions"],
            {
                "ok":                self._ok,
                "playpauseService":  self._ok,
                "cancel":            self._key_cancel,
                "left":              self._key_left,
                "right":            self._key_right,
                "up":                self._key_up,
                "upRepeated":        self._key_up_repeat,
                "down":              self._key_down,
                "downRepeated":      self._key_down_repeat,
                "nextBouquet":       lambda: self._page_nav(1),
                "prevBouquet":       lambda: self._page_nav(-1),
                "red":               self._key_red,
                "green":             self._key_green,
                "yellow":            self._key_yellow,
                "menu":              self._key_menu,
            },
            -1,
        )

        self._sel = 0
        self._timer.start(50, True)

    def _load(self):
        cfg  = _streams.get_config()
        self._items = cfg.get("items", [])
        ip   = _get_eth0_ip()
        try:
            port = int(cfg.get("webif_port", 8090))
        except (ValueError, TypeError):
            port = 8090
        self._webif_str = _b("WebIF: %s:%d" % (ip, port) if ip else "WebIF: Port %d" % port)
        self._page  = 0
        self._sel   = 0
        try:
            self._config_mtime = os.path.getmtime(_streams.CONFIG_FILE)
        except Exception:
            self._config_mtime = 0
        self._poll_timer.start(3000, False)
        self._render()

    def _poll_config(self):
        if self._sort_mode:
            return
        try:
            mtime = os.path.getmtime(_streams.CONFIG_FILE)
        except Exception:
            return
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        cfg = _streams.get_config()
        self._items = cfg.get("items", [])
        ip   = _get_eth0_ip()
        port = _streams.get_webif_port()
        self._webif_str = _b("WebIF: %s:%d" % (ip, port) if ip else "WebIF: Port %d" % port)
        self._render()

    def close(self):
        self._poll_timer.stop()
        if not _get_setting("webif_autostart", False):
            _webif.stop()
        Screen.close(self)

    def _key_cancel(self):
        if self._sort_mode and self._sort_backup is not None and self._items != self._sort_backup:
            def on_confirm(result):
                if result:
                    self._items            = list(self._sort_backup)
                    self._sort_mode        = False
                    self._sort_grabbed_abs = None
                    self._sort_backup      = None
                    if self._list_mode:
                        self._render_list()
                    else:
                        self._render()
            _sa_confirm(self.session, _b("Sortierung verwerfen?"), on_confirm)
        elif self._sort_mode:
            self._sort_mode        = False
            self._sort_grabbed_abs = None
            self._sort_backup      = None
            if self._list_mode:
                self._render_list()
            else:
                self._render()
        else:
            self.close()

    def _key_yellow(self):
        if self._sort_mode:
            return
        self._list_mode = not self._list_mode
        _set_setting("list_mode", self._list_mode)
        if self._list_mode:
            offset = self._page * TILES_PER_PAGE
            self._list_sel    = min(offset + self._sel, max(0, len(self._items) - 1))
            self._list_scroll = max(0, self._list_sel - LIST_ROWS // 2)
        else:
            self._page = self._list_sel // TILES_PER_PAGE
            self._sel  = self._list_sel % TILES_PER_PAGE
        self._render()

    def _render(self):
        if self._list_mode:
            if self._prev_render_mode is not True:
                self._clear_all_tiles()
                self._prev_render_mode = True
            self._render_list()
        else:
            if self._prev_render_mode is not False:
                self._clear_all_list()
                self._prev_render_mode = False
            self._render_tiles()

    def _render_tiles(self):
        total  = len(self._items)
        pages  = max(1, (total + TILES_PER_PAGE - 1) // TILES_PER_PAGE)
        self._page = max(0, min(self._page, pages - 1))

        offset     = self._page * TILES_PER_PAGE
        page_items = self._items[offset:offset + TILES_PER_PAGE]

        for i in range(TILES_PER_PAGE):
            if i < len(page_items):
                item = page_items[i]
                name = _u(item.get("name", ""))
                self["tile_bg_%d"    % i].show()
                self["tile_label_%d" % i].show()
                self["tile_label_%d" % i].setText(_b(name))
                self._load_logo(i, item.get("logo", ""))
                self._load_type_icon(i, item.get("type", "stream"))
            else:
                self["tile_bg_%d"    % i].hide()
                self["tile_label_%d" % i].hide()
                self._clear_logo(i)
                self._clear_type_icon(i)

        self._sel = min(self._sel, max(0, len(page_items) - 1))
        self._update_sel_marker()

        page_label = "Seite %d/%d" % (self._page + 1, pages) if pages > 1 else ""
        self["page_label"].setText(_b(page_label))
        self["webif_addr"].setText(getattr(self, "_webif_str", _b("")))
        self._update_legend()

    def _render_list(self):
        total = len(self._items)
        if total == 0:
            self._list_sel = self._list_scroll = 0
        else:
            self._list_sel = max(0, min(self._list_sel, total - 1))
            if self._list_sel < self._list_scroll:
                self._list_scroll = self._list_sel
            elif self._list_sel >= self._list_scroll + LIST_ROWS:
                self._list_scroll = self._list_sel - LIST_ROWS + 1
            self._list_scroll = max(0, min(self._list_scroll, max(0, total - LIST_ROWS)))

        for i in range(LIST_ROWS):
            abs_idx = self._list_scroll + i
            if abs_idx < total:
                item    = self._items[abs_idx]
                is_sel  = (abs_idx == self._list_sel)
                is_grab = (self._sort_grabbed_abs is not None and
                           self._sort_grabbed_abs == abs_idx)
                if is_grab:
                    self["list_grab_%d" % i].show()
                    self["list_sel_%d"  % i].hide()
                elif is_sel:
                    self["list_sel_%d"  % i].show()
                    self["list_grab_%d" % i].hide()
                else:
                    self["list_sel_%d"  % i].hide()
                    self["list_grab_%d" % i].hide()
                self["list_label_%d" % i].setText(_b(_u(item.get("name", ""))))
                self["list_label_%d" % i].show()
                self._load_list_logo(i, item.get("logo", ""))
                self._load_list_type_icon(i, item.get("type", "stream"))
            else:
                self["list_sel_%d"   % i].hide()
                self["list_label_%d" % i].hide()
                self._clear_list_logo(i)
                self._clear_list_type_icon(i)

        count_str = "%d/%d" % (self._list_sel + 1, total) if total > 0 else ""
        self["page_label"].setText(_b(count_str))
        self["webif_addr"].setText(getattr(self, "_webif_str", _b("")))
        self._update_legend()

    def _clear_all_tiles(self):
        for i in range(TILES_PER_PAGE):
            self["tile_bg_%d"    % i].hide()
            self["tile_label_%d" % i].hide()
            if _Pixmap:
                try:
                    self["tile_logo_%d" % i].instance.setPixmap(None)
                    self["tile_sel_%d"  % i].instance.setPixmap(None)
                    self["tile_type_%d" % i].instance.setPixmap(None)
                except Exception:
                    pass

    def _clear_all_list(self):
        for i in range(LIST_ROWS):
            self["list_sel_%d"  % i].hide()
            self["list_grab_%d" % i].hide()
            self["list_label_%d" % i].hide()
            self._clear_list_logo(i)
            self._clear_list_type_icon(i)

    def _load_list_logo(self, idx, logo_rel):
        if not _LoadPixmap or not _Pixmap:
            return
        lox = 40 if IS_FHD else 38
        low = 100 if IS_FHD else 65
        loh = LIST_ROW_H - 10
        loy = LIST_ROW_Y0 + idx * LIST_ROW_H + 5
        widget = self["list_logo_%d" % idx]
        try:
            if logo_rel:
                path = os.path.join(PLUGIN_DIR, logo_rel)
                px = _cached_pixmap(path)
                if px:
                    iw, ih = px.size().width(), px.size().height()
                    if iw > 0 and ih > 0:
                        s  = min(float(low) / iw, float(loh) / ih)
                        nw = max(1, int(iw * s))
                        nh = max(1, int(ih * s))
                        ox = (low - nw) // 2
                        oy = (loh - nh) // 2
                        widget.instance.resize(eSize(nw, nh))
                        widget.instance.move(ePoint(lox + ox, loy + oy))
                    widget.instance.setPixmap(px)
                    return
            widget.instance.setPixmap(None)
            widget.instance.resize(eSize(low, loh))
            widget.instance.move(ePoint(lox, loy))
        except Exception:
            pass

    def _clear_list_logo(self, idx):
        if not _Pixmap:
            return
        try:
            self["list_logo_%d" % idx].instance.setPixmap(None)
        except Exception:
            pass

    def _load_list_type_icon(self, idx, item_type):
        if not _LoadPixmap or not _Pixmap:
            return
        name = "type_folder.png" if item_type == "folder" else "type_stream.png"
        path = os.path.join(LOGO_DIR, name)
        try:
            px = _cached_pixmap(path)
            if px:
                self["list_type_%d" % idx].instance.setPixmap(px)
                return
            self["list_type_%d" % idx].instance.setPixmap(None)
        except Exception:
            pass

    def _clear_list_type_icon(self, idx):
        if not _Pixmap:
            return
        try:
            self["list_type_%d" % idx].instance.setPixmap(None)
        except Exception:
            pass

    def _update_legend(self):
        if self._list_mode:
            item = self._items[self._list_sel] if 0 <= self._list_sel < len(self._items) else None
        else:
            idx  = self._page * TILES_PER_PAGE + self._sel
            item = self._items[idx] if idx < len(self._items) else None

        if not self._sort_mode:
            self["hint_red"].setText(_b("Sortieren"))
            self["hint_green"].setText(_b("Einstellungen"))
            if self._list_mode:
                self["hint_yellow"].setText(_b("Kacheln"))
                if item and item.get("type") == "folder":
                    self["hint_ok"].setText(_b("OK = \xc3\x96ffnen"))
                else:
                    self["hint_ok"].setText(_b("OK = Abspielen"))
            else:
                self["hint_yellow"].setText(_b("Liste"))
                if item and item.get("type") == "folder":
                    self["hint_ok"].setText(_b("OK = \xc3\x96ffnen"))
                else:
                    self["hint_ok"].setText(_b("OK = Abspielen"))
            self["hint_menu"].setText(_b("MENU = Bearbeiten") if item else _b(""))
        elif self._sort_grabbed_abs is None:
            self["hint_green"].setText(_b("Fertig"))
            self["hint_red"].setText(_b("R\xc3\xbcckg\xc3\xa4ngig"))
            self["hint_ok"].setText(_b("OK = Greifen"))
            self["hint_yellow"].setText(_b(""))
            self["hint_menu"].setText(_b(""))
        else:
            self["hint_green"].setText(_b("Fertig"))
            self["hint_red"].setText(_b("R\xc3\xbcckg\xc3\xa4ngig"))
            self["hint_ok"].setText(_b("OK = Ablegen"))
            self["hint_yellow"].setText(_b(""))
            self["hint_menu"].setText(_b(""))

        if self._list_mode:
            total = len(self._items)
            self["page_label"].setText(_b("%d/%d" % (self._list_sel + 1, total) if total > 0 else ""))
            self["hint_ch"].setText(_b(""))
        else:
            self["hint_ch"].setText(_b("CH+/- = Seite bl\xc3\xa4ttern"))

    def _key_red(self):
        if not self._sort_mode:
            self._sort_mode        = True
            self._sort_backup      = list(self._items)
            self._sort_grabbed_abs = None
        else:
            self._items            = list(self._sort_backup)
            self._sort_mode        = False
            self._sort_grabbed_abs = None
        self._render()

    def _key_green(self):
        if self._sort_mode:
            self._sort_mode        = False
            self._sort_grabbed_abs = None
            self._save_order()
            self._render()
        else:
            self.session.openWithCallback(
                self._on_settings_closed,
                StreamAnywhereSettingsScreen,
            )

    def _on_settings_closed(self):
        ip   = _get_eth0_ip()
        port = _streams.get_webif_port()
        self._webif_str = _b("WebIF: %s:%d" % (ip, port) if ip else "WebIF: Port %d" % port)
        self._render()

    def _key_menu(self):
        if self._list_mode:
            idx = self._list_sel
        else:
            idx = self._page * TILES_PER_PAGE + self._sel
        if idx >= len(self._items):
            return
        item = self._items[idx]
        if "id" not in item:
            return

        if item.get("type") == "folder":
            def on_delete_folder(answer):
                if not answer:
                    return
                _streams.delete_group(item["id"])
                self._items = _streams.get_config().get("items", [])
                if self._list_mode:
                    self._list_sel = max(0, min(self._list_sel, len(self._items) - 1))
                else:
                    page_count = min(TILES_PER_PAGE, len(self._items) - self._page * TILES_PER_PAGE)
                    if page_count <= 0 and self._page > 0:
                        self._page -= 1
                        page_count = min(TILES_PER_PAGE, len(self._items) - self._page * TILES_PER_PAGE)
                    if self._sel >= max(1, page_count):
                        self._sel = max(0, page_count - 1)
                self._render()
            _sa_confirm(self.session, _b("Ordner und alle Streams l\xc3\xb6schen?"), on_delete_folder)
            return

        def update(it):
            _streams.update_flat_stream(it["id"],
                                        player=it.get("player", ""),
                                        user_agent=it.get("user_agent", ""),
                                        hls_audio_fix=it.get("hls_audio_fix", False))

        def delete():
            _streams.delete_flat_stream(item["id"])
            self._items = _streams.get_config().get("items", [])
            if self._list_mode:
                self._list_sel = max(0, min(self._list_sel, len(self._items) - 1))
            else:
                page_count = min(TILES_PER_PAGE, len(self._items) - self._page * TILES_PER_PAGE)
                if page_count <= 0 and self._page > 0:
                    self._page -= 1
                    page_count = min(TILES_PER_PAGE, len(self._items) - self._page * TILES_PER_PAGE)
                if self._sel >= max(1, page_count):
                    self._sel = max(0, page_count - 1)
            self._render()

        _stream_context_menu(self.session, item, update, self._render, delete_fn=delete)

    def _save_order(self):
        id_list = [item["id"] for item in self._items if "id" in item]
        _streams.reorder_flat_streams(id_list)

    def _load_type_icon(self, idx, item_type):
        if not _LoadPixmap or not _Pixmap:
            return
        name = "type_folder.png" if item_type == "folder" else "type_stream.png"
        path = os.path.join(LOGO_DIR, name)
        px = _cached_pixmap(path)
        if px:
            self["tile_type_%d" % idx].instance.setPixmap(px)

    def _clear_type_icon(self, idx):
        if _Pixmap:
            self["tile_type_%d" % idx].instance.setPixmap(None)

    def _load_logo(self, idx, logo_rel):
        if not _LoadPixmap or not _Pixmap:
            return
        lx, ly, lw, lh = _logo_base_rect(idx)
        if logo_rel:
            path = os.path.join(PLUGIN_DIR, logo_rel)
            px = _cached_pixmap(path)
            if px:
                iw, ih = px.size().width(), px.size().height()
                if iw > 0 and ih > 0:
                    s  = min(float(lw) / iw, float(lh) / ih)
                    nw = max(1, int(iw * s))
                    nh = max(1, int(ih * s))
                    ox = (lw - nw) // 2
                    oy = (lh - nh) // 2
                    self["tile_logo_%d" % idx].instance.resize(eSize(nw, nh))
                    self["tile_logo_%d" % idx].instance.move(ePoint(lx + ox, ly + oy))
                self["tile_logo_%d" % idx].instance.setPixmap(px)
                return
        self._clear_logo(idx)

    def _clear_logo(self, idx):
        if _Pixmap:
            lx, ly, lw, lh = _logo_base_rect(idx)
            self["tile_logo_%d" % idx].instance.setPixmap(None)
            self["tile_logo_%d" % idx].instance.resize(eSize(lw, lh))
            self["tile_logo_%d" % idx].instance.move(ePoint(lx, ly))

    def _update_sel_marker(self):
        sel_px  = os.path.join(PLUGIN_DIR, "logos", "sel.png")
        grab_px = os.path.join(PLUGIN_DIR, "logos", "sel_grabbed.png")
        for i in range(TILES_PER_PAGE):
            if not _Pixmap:
                break
            is_sel  = (i == self._sel)
            is_grab = (self._sort_grabbed_abs is not None and
                       self._sort_grabbed_abs == self._page * TILES_PER_PAGE + i)
            if is_grab:
                path = grab_px if os.path.isfile(grab_px) else sel_px
                px = _cached_pixmap(path)
                if px:
                    self["tile_sel_%d" % i].instance.setPixmap(px)
            elif is_sel:
                px = _cached_pixmap(sel_px)
                if px:
                    self["tile_sel_%d" % i].instance.setPixmap(px)
            else:
                self["tile_sel_%d" % i].instance.setPixmap(None)

    def _move(self, delta):
        if self._list_mode:
            total = len(self._items)
            if total == 0:
                return
            step = 1 if delta > 0 else -1
            if self._sort_mode and self._sort_grabbed_abs is not None:
                old = self._sort_grabbed_abs
                new = max(0, min(old + delta, total - 1))
                if old != new:
                    item = self._items.pop(old)
                    self._items.insert(new, item)
                    self._sort_grabbed_abs = new
                    self._list_sel = new
                self._render_list()
                return
            self._list_step(step)
            return

        total      = len(self._items)
        offset     = self._page * TILES_PER_PAGE
        page_count = min(TILES_PER_PAGE, total - offset)
        if page_count <= 0:
            return

        if self._sort_mode and self._sort_grabbed_abs is not None:
            old_abs = self._sort_grabbed_abs
            new_abs = old_abs + delta
            if 0 <= new_abs < total:
                item = self._items.pop(old_abs)
                self._items.insert(new_abs, item)
                self._sort_grabbed_abs = new_abs
                self._page = new_abs // TILES_PER_PAGE
                self._sel  = new_abs % TILES_PER_PAGE
                self._render()
            return

        col = self._sel % TILE_COLS
        row = self._sel // TILE_COLS

        if abs(delta) == 1:
            if delta == 1:  # rechts
                if col < TILE_COLS - 1:
                    new_sel = self._sel + 1
                    if new_sel < page_count:
                        self._sel = new_sel
                        self._update_sel_marker()
                        self._update_legend()
                else:
                    if _get_setting("wrap_lr"):
                        new_abs = (offset + self._sel + 1) % total
                        self._page = new_abs // TILES_PER_PAGE
                        self._sel  = new_abs % TILES_PER_PAGE
                        self._render()
                    else:
                        self._sel = row * TILE_COLS
                        self._update_sel_marker()
                        self._update_legend()
            else:  # links
                if col > 0:
                    self._sel -= 1
                    self._update_sel_marker()
                    self._update_legend()
                else:
                    if _get_setting("wrap_lr"):
                        new_abs = (offset + self._sel - 1) % total
                        self._page = new_abs // TILES_PER_PAGE
                        self._sel  = new_abs % TILES_PER_PAGE
                        self._render()
                    else:
                        self._sel = min(row * TILE_COLS + TILE_COLS - 1, page_count - 1)
                        self._update_sel_marker()
                        self._update_legend()
        else:
            if delta > 0:  # unten
                new_row = (row + 1) % TILE_ROWS
            else:  # oben
                new_row = (row - 1 + TILE_ROWS) % TILE_ROWS
            new_sel = new_row * TILE_COLS + col
            if new_sel >= page_count:
                if new_row * TILE_COLS < page_count:
                    new_sel = page_count - 1
                elif delta < 0:
                    new_sel = ((page_count - col - 1) // TILE_COLS) * TILE_COLS + col if col < page_count else page_count - 1
                else:
                    new_sel = min(col, page_count - 1)
            self._sel = new_sel
            self._update_sel_marker()
            self._update_legend()

    def _list_step(self, step):
        total = len(self._items)
        if total == 0:
            return
        old_sel    = self._list_sel
        old_scroll = self._list_scroll
        self._list_sel = (self._list_sel + step) % total
        if self._list_sel < self._list_scroll:
            self._list_scroll = self._list_sel
        elif self._list_sel >= self._list_scroll + LIST_ROWS:
            self._list_scroll = self._list_sel - LIST_ROWS + 1
        self._list_scroll = max(0, min(self._list_scroll, max(0, total - LIST_ROWS)))
        if self._list_scroll != old_scroll:
            self._render_list()
        else:
            old_row = old_sel - old_scroll
            new_row = self._list_sel - self._list_scroll
            if 0 <= old_row < LIST_ROWS:
                self["list_sel_%d"  % old_row].hide()
                self["list_grab_%d" % old_row].hide()
            if 0 <= new_row < LIST_ROWS:
                self["list_sel_%d"  % new_row].show()
            self._update_legend()

    def _key_up(self):
        self._move(-1 if self._list_mode else -TILE_COLS)

    def _key_up_repeat(self):
        if self._list_mode:
            self._move(-1)

    def _key_down(self):
        self._move(1 if self._list_mode else TILE_COLS)

    def _key_down_repeat(self):
        if self._list_mode:
            self._move(1)

    def _key_left(self):
        if self._list_mode:
            if self._sort_mode and self._sort_grabbed_abs is not None:
                self._move(-LIST_ROWS)
            else:
                self._page_nav(-1)
        else:
            self._move(-1)

    def _key_right(self):
        if self._list_mode:
            if self._sort_mode and self._sort_grabbed_abs is not None:
                self._move(LIST_ROWS)
            else:
                self._page_nav(1)
        else:
            self._move(1)

    def _page_nav(self, direction):
        if self._list_mode:
            total = len(self._items)
            if total == 0:
                return
            self._list_sel = max(0, min(self._list_sel + direction * LIST_ROWS, total - 1))
            self._render_list()
            return
        total = len(self._items)
        pages = max(1, (total + TILES_PER_PAGE - 1) // TILES_PER_PAGE)
        new_page = self._page + direction
        if 0 <= new_page < pages:
            self._page = new_page
            self._sel  = 0
            self._render()

    def _ok(self):
        if self._list_mode:
            total = len(self._items)
            if total == 0 or self._list_sel >= total:
                return
            if self._sort_mode:
                if self._sort_grabbed_abs is None:
                    self._sort_grabbed_abs = self._list_sel
                else:
                    self._sort_grabbed_abs = None
                self._render_list()
                return
            item = self._items[self._list_sel]
            if item.get("type") == "folder":
                self.session.open(StreamAnywhereGroupScreen, item)
                return
            url        = item.get("url", "")
            name       = item.get("name", "Stream")
            player     = item.get("player", "")
            user_agent = item.get("user_agent", "")
            if url:
                prefer_bq = _get_setting("prefer_best_quality", True)
                if _youtube.is_youtube(url):
                    resolved = _youtube.resolve(url, best_quality=prefer_bq)
                    if resolved:
                        url = resolved
                elif _feratel.is_feratel(url):
                    resolved = _feratel.resolve(url)
                    if resolved:
                        url = resolved
                elif _skyline.is_skylinewebcams(url):
                    resolved = _skyline.resolve(url)
                    if resolved:
                        url = resolved
                        if _youtube.is_youtube(url):
                            yt = _youtube.resolve(url, best_quality=prefer_bq)
                            if yt:
                                url = yt
                elif _earthtv.is_earthtv(url):
                    resolved = _earthtv.resolve(url)
                    if resolved:
                        url = resolved
                elif _earthcam.is_earthcam(url):
                    resolved = _earthcam.resolve(url)
                    if resolved:
                        url = resolved
                play_stream(self.session, url, title=name, is_live=True,
                            player=player, user_agent=user_agent,
                            autoconfigure_serviceapp=_get_setting("serviceapp_autoconfigure", True),
                            prefer_best_quality=prefer_bq,
                            streams=self._items, stream_index=self._list_sel,
                            hls_audio_fix=item.get("hls_audio_fix", False))
            return

        offset = self._page * TILES_PER_PAGE
        idx    = offset + self._sel
        if idx >= len(self._items):
            return

        if self._sort_mode:
            if self._sort_grabbed_abs is None:
                self._sort_grabbed_abs = idx
            else:
                self._sort_grabbed_abs = None
            self._update_sel_marker()
            self._update_legend()
            return

        item = self._items[idx]
        if item.get("type") == "folder":
            self.session.open(StreamAnywhereGroupScreen, item)
            return
        else:
            url        = item.get("url", "")
            name       = item.get("name", "Stream")
            player     = item.get("player", "")
            user_agent = item.get("user_agent", "")
            if url:
                prefer_bq = _get_setting("prefer_best_quality", True)
                if _youtube.is_youtube(url):
                    resolved = _youtube.resolve(url, best_quality=prefer_bq)
                    if resolved:
                        url = resolved
                elif _feratel.is_feratel(url):
                    resolved = _feratel.resolve(url)
                    if resolved:
                        url = resolved
                elif _skyline.is_skylinewebcams(url):
                    resolved = _skyline.resolve(url)
                    if resolved:
                        url = resolved
                        if _youtube.is_youtube(url):
                            yt = _youtube.resolve(url, best_quality=prefer_bq)
                            if yt:
                                url = yt
                elif _earthtv.is_earthtv(url):
                    resolved = _earthtv.resolve(url)
                    if resolved:
                        url = resolved
                elif _earthcam.is_earthcam(url):
                    resolved = _earthcam.resolve(url)
                    if resolved:
                        url = resolved
                play_stream(self.session, url, title=name, is_live=True,
                            player=player, user_agent=user_agent,
                            autoconfigure_serviceapp=_get_setting("serviceapp_autoconfigure", True),
                            prefer_best_quality=prefer_bq,
                            streams=self._items, stream_index=idx,
                            hls_audio_fix=item.get("hls_audio_fix", False))


# ------------------------------------------------------------------
# Gruppen-Screen
# ------------------------------------------------------------------
class StreamAnywhereGroupScreen(Screen):

    skin = _build_skin()

    def __init__(self, session, group):
        Screen.__init__(self, session)
        self._group            = group
        self._items            = group.get("streams", [])
        self._page             = 0
        self._sel              = 0
        self._sort_mode        = False
        self._sort_grabbed_abs = None
        self._sort_backup      = None
        self._config_mtime     = 0
        self._list_mode        = _get_setting("list_mode", False)
        self._list_sel         = 0
        self._list_scroll      = 0
        self._prev_render_mode = None
        self._timer = eTimer()
        self._timer.callback.append(self._init_load)
        self._poll_timer = eTimer()
        self._poll_timer.callback.append(self._poll_config)

        self["title"]       = Label(_b(_u(group.get("name", "Streams"))))
        self["hint_red"]    = Label(_b(""))
        self["hint_green"]  = Label(_b(""))
        self["hint_ok"]     = Label(_b(""))
        self["hint_ch"]     = Label(_b("CH+/- = Seite"))
        self["hint_yellow"] = Label(_b(""))
        self["hint_menu"]   = Label(_b(""))
        self["page_label"]  = Label(_b(""))
        self["webif_addr"]  = Label(_b(""))

        for i in range(TILES_PER_PAGE):
            self["tile_bg_%d"    % i] = Label(_b(""))
            self["tile_label_%d" % i] = Label(_b(""))
            if _Pixmap:
                self["tile_logo_%d" % i] = _Pixmap()
                self["tile_sel_%d" % i]  = _Pixmap()
                self["tile_type_%d" % i] = _Pixmap()
            self["tile_bg_%d" % i].hide()

        for i in range(LIST_ROWS):
            self["list_sel_%d"   % i] = Label(_b(""))
            self["list_grab_%d"  % i] = Label(_b(""))
            self["list_label_%d" % i] = Label(_b(""))
            if _Pixmap:
                self["list_logo_%d" % i] = _Pixmap()
                self["list_type_%d" % i] = _Pixmap()
            self["list_sel_%d"   % i].hide()
            self["list_grab_%d"  % i].hide()
            self["list_label_%d" % i].hide()

        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions",
             "ChannelSelectBaseActions", "MenuActions", "InfobarSeekActions"],
            {
                "ok":                self._ok,
                "playpauseService":  self._ok,
                "cancel":            self._key_cancel,
                "left":              self._key_left,
                "right":            self._key_right,
                "up":                self._key_up,
                "upRepeated":        self._key_up_repeat,
                "down":              self._key_down,
                "downRepeated":      self._key_down_repeat,
                "nextBouquet":       lambda: self._page_nav(1),
                "prevBouquet":       lambda: self._page_nav(-1),
                "red":               self._key_red,
                "green":             self._key_green,
                "yellow":            self._key_yellow,
                "menu":              self._key_menu,
            },
            -1,
        )

        self._timer.start(50, True)

    def _init_load(self):
        ip   = _get_eth0_ip()
        port = _streams.get_webif_port()
        self._webif_str = _b("WebIF: %s:%d" % (ip, port) if ip else "WebIF: Port %d" % port)
        try:
            self._config_mtime = os.path.getmtime(_streams.CONFIG_FILE)
        except Exception:
            self._config_mtime = 0
        self._poll_timer.start(3000, False)
        self._render()

    def _poll_config(self):
        if self._sort_mode:
            return
        try:
            mtime = os.path.getmtime(_streams.CONFIG_FILE)
        except Exception:
            return
        if mtime == self._config_mtime:
            return
        self._config_mtime = mtime
        cfg      = _streams.get_config()
        ip   = _get_eth0_ip()
        port = _streams.get_webif_port()
        self._webif_str = _b("WebIF: %s:%d" % (ip, port) if ip else "WebIF: Port %d" % port)
        group_id = self._group.get("id")
        if not group_id:
            return
        for g in cfg.get("items", []):
            if g.get("id") == group_id and g.get("type") == "folder":
                self._group = g
                self._items = g.get("streams", [])
                break
        self._render()

    def close(self):
        self._poll_timer.stop()
        Screen.close(self)

    def _key_cancel(self):
        if self._sort_mode and self._sort_backup is not None and self._items != self._sort_backup:
            def on_confirm(result):
                if result:
                    self._items            = list(self._sort_backup)
                    self._sort_mode        = False
                    self._sort_grabbed_abs = None
                    self._sort_backup      = None
                    if self._list_mode:
                        self._render_list()
                    else:
                        self._render()
            _sa_confirm(self.session, _b("Sortierung verwerfen?"), on_confirm)
        elif self._sort_mode:
            self._sort_mode        = False
            self._sort_grabbed_abs = None
            self._sort_backup      = None
            if self._list_mode:
                self._render_list()
            else:
                self._render()
        else:
            self.close()

    def _render(self):
        if self._list_mode:
            if self._prev_render_mode is not True:
                self._clear_all_tiles()
                self._prev_render_mode = True
            self._render_list()
        else:
            if self._prev_render_mode is not False:
                self._clear_all_list()
                self._prev_render_mode = False
            self._render_tiles()

    def _render_tiles(self):
        total  = len(self._items)
        pages  = max(1, (total + TILES_PER_PAGE - 1) // TILES_PER_PAGE)
        self._page = max(0, min(self._page, pages - 1))

        offset     = self._page * TILES_PER_PAGE
        page_items = self._items[offset:offset + TILES_PER_PAGE]

        for i in range(TILES_PER_PAGE):
            if i < len(page_items):
                item = page_items[i]
                name = _u(item.get("name", ""))
                self["tile_bg_%d"    % i].show()
                self["tile_label_%d" % i].show()
                self["tile_label_%d" % i].setText(_b(name))
                self._load_logo(i, item.get("logo", ""))
                self._load_type_icon(i)
            else:
                self["tile_bg_%d"    % i].hide()
                self["tile_label_%d" % i].hide()
                self._clear_logo(i)
                self._clear_type_icon(i)

        self._sel = min(self._sel, max(0, len(page_items) - 1))
        self._update_sel_marker()

        page_label = "Seite %d/%d" % (self._page + 1, pages) if pages > 1 else ""
        self["page_label"].setText(_b(page_label))
        self["webif_addr"].setText(getattr(self, "_webif_str", _b("")))
        self._update_legend()

    def _render_list(self):
        total = len(self._items)
        if total == 0:
            self._list_sel = self._list_scroll = 0
        else:
            self._list_sel = max(0, min(self._list_sel, total - 1))
            if self._list_sel < self._list_scroll:
                self._list_scroll = self._list_sel
            elif self._list_sel >= self._list_scroll + LIST_ROWS:
                self._list_scroll = self._list_sel - LIST_ROWS + 1
            self._list_scroll = max(0, min(self._list_scroll, max(0, total - LIST_ROWS)))

        for i in range(LIST_ROWS):
            abs_idx = self._list_scroll + i
            if abs_idx < total:
                item    = self._items[abs_idx]
                is_sel  = (abs_idx == self._list_sel)
                is_grab = (self._sort_grabbed_abs is not None and
                           self._sort_grabbed_abs == abs_idx)
                if is_grab:
                    self["list_grab_%d" % i].show()
                    self["list_sel_%d"  % i].hide()
                elif is_sel:
                    self["list_sel_%d"  % i].show()
                    self["list_grab_%d" % i].hide()
                else:
                    self["list_sel_%d"  % i].hide()
                    self["list_grab_%d" % i].hide()
                self["list_label_%d" % i].setText(_b(_u(item.get("name", ""))))
                self["list_label_%d" % i].show()
                self._load_list_logo(i, item.get("logo", ""))
                self._load_list_type_icon(i, item.get("type", "stream"))
            else:
                self["list_sel_%d"   % i].hide()
                self["list_label_%d" % i].hide()
                self._clear_list_logo(i)
                self._clear_list_type_icon(i)

        count_str = "%d/%d" % (self._list_sel + 1, total) if total > 0 else ""
        self["page_label"].setText(_b(count_str))
        self["webif_addr"].setText(getattr(self, "_webif_str", _b("")))
        self._update_legend()

    def _clear_all_tiles(self):
        for i in range(TILES_PER_PAGE):
            self["tile_bg_%d"    % i].hide()
            self["tile_label_%d" % i].hide()
            if _Pixmap:
                try:
                    self["tile_logo_%d" % i].instance.setPixmap(None)
                    self["tile_sel_%d"  % i].instance.setPixmap(None)
                    self["tile_type_%d" % i].instance.setPixmap(None)
                except Exception:
                    pass

    def _clear_all_list(self):
        for i in range(LIST_ROWS):
            self["list_sel_%d"  % i].hide()
            self["list_grab_%d" % i].hide()
            self["list_label_%d" % i].hide()
            self._clear_list_logo(i)
            self._clear_list_type_icon(i)

    def _load_list_logo(self, idx, logo_rel):
        if not _LoadPixmap or not _Pixmap:
            return
        lox = 40 if IS_FHD else 38
        low = 100 if IS_FHD else 65
        loh = LIST_ROW_H - 10
        loy = LIST_ROW_Y0 + idx * LIST_ROW_H + 5
        widget = self["list_logo_%d" % idx]
        try:
            if logo_rel:
                path = os.path.join(PLUGIN_DIR, logo_rel)
                px = _cached_pixmap(path)
                if px:
                    iw, ih = px.size().width(), px.size().height()
                    if iw > 0 and ih > 0:
                        s  = min(float(low) / iw, float(loh) / ih)
                        nw = max(1, int(iw * s))
                        nh = max(1, int(ih * s))
                        ox = (low - nw) // 2
                        oy = (loh - nh) // 2
                        widget.instance.resize(eSize(nw, nh))
                        widget.instance.move(ePoint(lox + ox, loy + oy))
                    widget.instance.setPixmap(px)
                    return
            widget.instance.setPixmap(None)
            widget.instance.resize(eSize(low, loh))
            widget.instance.move(ePoint(lox, loy))
        except Exception:
            pass

    def _clear_list_logo(self, idx):
        if not _Pixmap:
            return
        try:
            self["list_logo_%d" % idx].instance.setPixmap(None)
        except Exception:
            pass

    def _load_list_type_icon(self, idx, item_type):
        if not _LoadPixmap or not _Pixmap:
            return
        name = "type_folder.png" if item_type == "folder" else "type_stream.png"
        path = os.path.join(LOGO_DIR, name)
        try:
            px = _cached_pixmap(path)
            if px:
                self["list_type_%d" % idx].instance.setPixmap(px)
                return
            self["list_type_%d" % idx].instance.setPixmap(None)
        except Exception:
            pass

    def _clear_list_type_icon(self, idx):
        if not _Pixmap:
            return
        try:
            self["list_type_%d" % idx].instance.setPixmap(None)
        except Exception:
            pass

    def _update_legend(self):
        if self._list_mode:
            item = self._items[self._list_sel] if 0 <= self._list_sel < len(self._items) else None
        else:
            idx  = self._page * TILES_PER_PAGE + self._sel
            item = self._items[idx] if idx < len(self._items) else None

        if not self._sort_mode:
            self["hint_red"].setText(_b("Sortieren"))
            self["hint_green"].setText(_b("Einstellungen"))
            self["hint_ok"].setText(_b("OK = Abspielen"))
            self["hint_yellow"].setText(_b("Kacheln") if self._list_mode else _b("Liste"))
            self["hint_menu"].setText(_b("MENU = Bearbeiten") if item else _b(""))
        elif self._sort_grabbed_abs is None:
            self["hint_green"].setText(_b("Fertig"))
            self["hint_red"].setText(_b("R\xc3\xbcckg\xc3\xa4ngig"))
            self["hint_ok"].setText(_b("OK = Greifen"))
            self["hint_yellow"].setText(_b(""))
            self["hint_menu"].setText(_b(""))
        else:
            self["hint_green"].setText(_b("Fertig"))
            self["hint_red"].setText(_b("R\xc3\xbcckg\xc3\xa4ngig"))
            self["hint_ok"].setText(_b("OK = Ablegen"))
            self["hint_yellow"].setText(_b(""))
            self["hint_menu"].setText(_b(""))

        if self._list_mode:
            total = len(self._items)
            self["page_label"].setText(_b("%d/%d" % (self._list_sel + 1, total) if total > 0 else ""))
            self["hint_ch"].setText(_b(""))
        else:
            self["hint_ch"].setText(_b("CH+/- = Seite bl\xc3\xa4ttern"))

    def _key_red(self):
        if not self._sort_mode:
            self._sort_mode        = True
            self._sort_backup      = list(self._items)
            self._sort_grabbed_abs = None
        else:
            self._items            = list(self._sort_backup)
            self._sort_mode        = False
            self._sort_grabbed_abs = None
        self._render()

    def _key_yellow(self):
        if self._sort_mode:
            return
        self._list_mode = not self._list_mode
        _set_setting("list_mode", self._list_mode)
        if self._list_mode:
            offset = self._page * TILES_PER_PAGE
            self._list_sel    = min(offset + self._sel, max(0, len(self._items) - 1))
            self._list_scroll = max(0, self._list_sel - LIST_ROWS // 2)
        else:
            self._page = self._list_sel // TILES_PER_PAGE
            self._sel  = self._list_sel % TILES_PER_PAGE
        self._render()

    def _key_green(self):
        if self._sort_mode:
            self._sort_mode        = False
            self._sort_grabbed_abs = None
            self._save_order()
            self._render()
        else:
            self.session.openWithCallback(
                self._on_settings_closed,
                StreamAnywhereSettingsScreen,
            )

    def _on_settings_closed(self):
        ip   = _get_eth0_ip()
        port = _streams.get_webif_port()
        self._webif_str = _b("WebIF: %s:%d" % (ip, port) if ip else "WebIF: Port %d" % port)
        self._render()

    def _save_order(self):
        group_id = self._group.get("id")
        if not group_id:
            return
        id_list = [item["id"] for item in self._items if "id" in item]
        _streams.reorder_group_streams(group_id, id_list)

    def _load_type_icon(self, idx):
        if not _LoadPixmap or not _Pixmap:
            return
        path = os.path.join(LOGO_DIR, "type_stream.png")
        px = _cached_pixmap(path)
        if px:
            self["tile_type_%d" % idx].instance.setPixmap(px)

    def _clear_type_icon(self, idx):
        if _Pixmap:
            self["tile_type_%d" % idx].instance.setPixmap(None)

    def _load_logo(self, idx, logo_rel):
        if not _LoadPixmap or not _Pixmap:
            return
        lx, ly, lw, lh = _logo_base_rect(idx)
        if logo_rel:
            path = os.path.join(PLUGIN_DIR, logo_rel)
            px = _cached_pixmap(path)
            if px:
                iw, ih = px.size().width(), px.size().height()
                if iw > 0 and ih > 0:
                    s  = min(float(lw) / iw, float(lh) / ih)
                    nw = max(1, int(iw * s))
                    nh = max(1, int(ih * s))
                    ox = (lw - nw) // 2
                    oy = (lh - nh) // 2
                    self["tile_logo_%d" % idx].instance.resize(eSize(nw, nh))
                    self["tile_logo_%d" % idx].instance.move(ePoint(lx + ox, ly + oy))
                self["tile_logo_%d" % idx].instance.setPixmap(px)
                return
        self._clear_logo(idx)

    def _clear_logo(self, idx):
        if _Pixmap:
            lx, ly, lw, lh = _logo_base_rect(idx)
            self["tile_logo_%d" % idx].instance.setPixmap(None)
            self["tile_logo_%d" % idx].instance.resize(eSize(lw, lh))
            self["tile_logo_%d" % idx].instance.move(ePoint(lx, ly))

    def _update_sel_marker(self):
        sel_px  = os.path.join(PLUGIN_DIR, "logos", "sel.png")
        grab_px = os.path.join(PLUGIN_DIR, "logos", "sel_grabbed.png")
        for i in range(TILES_PER_PAGE):
            if not _Pixmap:
                break
            is_sel  = (i == self._sel)
            is_grab = (self._sort_grabbed_abs is not None and
                       self._sort_grabbed_abs == self._page * TILES_PER_PAGE + i)
            if is_grab:
                path = grab_px if os.path.isfile(grab_px) else sel_px
                px = _cached_pixmap(path)
                if px:
                    self["tile_sel_%d" % i].instance.setPixmap(px)
            elif is_sel:
                px = _cached_pixmap(sel_px)
                if px:
                    self["tile_sel_%d" % i].instance.setPixmap(px)
            else:
                self["tile_sel_%d" % i].instance.setPixmap(None)

    def _move(self, delta):
        if self._list_mode:
            total = len(self._items)
            if total == 0:
                return
            step = 1 if delta > 0 else -1
            if self._sort_mode and self._sort_grabbed_abs is not None:
                old = self._sort_grabbed_abs
                new = max(0, min(old + delta, total - 1))
                if old != new:
                    item = self._items.pop(old)
                    self._items.insert(new, item)
                    self._sort_grabbed_abs = new
                    self._list_sel = new
                self._render_list()
                return
            self._list_step(step)
            return

        total      = len(self._items)
        offset     = self._page * TILES_PER_PAGE
        page_count = min(TILES_PER_PAGE, total - offset)
        if page_count <= 0:
            return

        if self._sort_mode and self._sort_grabbed_abs is not None:
            old_abs = self._sort_grabbed_abs
            new_abs = old_abs + delta
            if 0 <= new_abs < total:
                item = self._items.pop(old_abs)
                self._items.insert(new_abs, item)
                self._sort_grabbed_abs = new_abs
                self._page = new_abs // TILES_PER_PAGE
                self._sel  = new_abs % TILES_PER_PAGE
                self._render()
            return

        col = self._sel % TILE_COLS
        row = self._sel // TILE_COLS

        if abs(delta) == 1:
            if delta == 1:  # rechts
                if col < TILE_COLS - 1:
                    new_sel = self._sel + 1
                    if new_sel < page_count:
                        self._sel = new_sel
                        self._update_sel_marker()
                        self._update_legend()
                else:
                    if _get_setting("wrap_lr"):
                        new_abs = (offset + self._sel + 1) % total
                        self._page = new_abs // TILES_PER_PAGE
                        self._sel  = new_abs % TILES_PER_PAGE
                        self._render()
                    else:
                        self._sel = row * TILE_COLS
                        self._update_sel_marker()
                        self._update_legend()
            else:  # links
                if col > 0:
                    self._sel -= 1
                    self._update_sel_marker()
                    self._update_legend()
                else:
                    if _get_setting("wrap_lr"):
                        new_abs = (offset + self._sel - 1) % total
                        self._page = new_abs // TILES_PER_PAGE
                        self._sel  = new_abs % TILES_PER_PAGE
                        self._render()
                    else:
                        self._sel = min(row * TILE_COLS + TILE_COLS - 1, page_count - 1)
                        self._update_sel_marker()
                        self._update_legend()
        else:
            if delta > 0:  # unten
                new_row = (row + 1) % TILE_ROWS
            else:  # oben
                new_row = (row - 1 + TILE_ROWS) % TILE_ROWS
            new_sel = new_row * TILE_COLS + col
            if new_sel >= page_count:
                if new_row * TILE_COLS < page_count:
                    new_sel = page_count - 1
                elif delta < 0:
                    new_sel = ((page_count - col - 1) // TILE_COLS) * TILE_COLS + col if col < page_count else page_count - 1
                else:
                    new_sel = min(col, page_count - 1)
            self._sel = new_sel
            self._update_sel_marker()
            self._update_legend()

    def _list_step(self, step):
        total = len(self._items)
        if total == 0:
            return
        old_sel    = self._list_sel
        old_scroll = self._list_scroll
        self._list_sel = (self._list_sel + step) % total
        if self._list_sel < self._list_scroll:
            self._list_scroll = self._list_sel
        elif self._list_sel >= self._list_scroll + LIST_ROWS:
            self._list_scroll = self._list_sel - LIST_ROWS + 1
        self._list_scroll = max(0, min(self._list_scroll, max(0, total - LIST_ROWS)))
        if self._list_scroll != old_scroll:
            self._render_list()
        else:
            old_row = old_sel - old_scroll
            new_row = self._list_sel - self._list_scroll
            if 0 <= old_row < LIST_ROWS:
                self["list_sel_%d"  % old_row].hide()
                self["list_grab_%d" % old_row].hide()
            if 0 <= new_row < LIST_ROWS:
                self["list_sel_%d"  % new_row].show()
            self._update_legend()

    def _key_up(self):
        self._move(-1 if self._list_mode else -TILE_COLS)

    def _key_up_repeat(self):
        if self._list_mode:
            self._move(-1)

    def _key_down(self):
        self._move(1 if self._list_mode else TILE_COLS)

    def _key_down_repeat(self):
        if self._list_mode:
            self._move(1)

    def _key_left(self):
        if self._list_mode:
            if self._sort_mode and self._sort_grabbed_abs is not None:
                self._move(-LIST_ROWS)
            else:
                self._page_nav(-1)
        else:
            self._move(-1)

    def _key_right(self):
        if self._list_mode:
            if self._sort_mode and self._sort_grabbed_abs is not None:
                self._move(LIST_ROWS)
            else:
                self._page_nav(1)
        else:
            self._move(1)

    def _page_nav(self, direction):
        if self._list_mode:
            total = len(self._items)
            if total == 0:
                return
            self._list_sel = max(0, min(self._list_sel + direction * LIST_ROWS, total - 1))
            self._render_list()
            return
        total = len(self._items)
        pages = max(1, (total + TILES_PER_PAGE - 1) // TILES_PER_PAGE)
        new_page = self._page + direction
        if 0 <= new_page < pages:
            self._page = new_page
            self._sel  = 0
            self._render()

    def _key_menu(self):
        if self._list_mode:
            idx = self._list_sel
        else:
            idx = self._page * TILES_PER_PAGE + self._sel
        if idx >= len(self._items):
            return
        item     = self._items[idx]
        group_id = self._group.get("id")
        if not group_id or "id" not in item:
            return

        def update(it):
            _streams.update_group_stream(group_id, it["id"],
                                         player=it.get("player", ""),
                                         user_agent=it.get("user_agent", ""),
                                         hls_audio_fix=it.get("hls_audio_fix", False))

        def delete():
            _streams.delete_group_stream(group_id, item["id"])
            cfg = _streams.get_config()
            for g in cfg.get("items", []):
                if g.get("id") == group_id:
                    self._items = g.get("streams", [])
                    self._group = g
                    break
            if self._list_mode:
                self._list_sel = max(0, min(self._list_sel, len(self._items) - 1))
            else:
                page_count = min(TILES_PER_PAGE, len(self._items) - self._page * TILES_PER_PAGE)
                if page_count <= 0 and self._page > 0:
                    self._page -= 1
                    page_count = min(TILES_PER_PAGE, len(self._items) - self._page * TILES_PER_PAGE)
                if self._sel >= max(1, page_count):
                    self._sel = max(0, page_count - 1)
            self._render()

        _stream_context_menu(self.session, item, update, self._render, delete_fn=delete)

    def _ok(self):
        if self._list_mode:
            total = len(self._items)
            if total == 0 or self._list_sel >= total:
                return
            if self._sort_mode:
                if self._sort_grabbed_abs is None:
                    self._sort_grabbed_abs = self._list_sel
                else:
                    self._sort_grabbed_abs = None
                self._render_list()
                return
            item       = self._items[self._list_sel]
            url        = item.get("url", "")
            name       = item.get("name", "Stream")
            player     = item.get("player", "")
            user_agent = item.get("user_agent", "")
            if url:
                prefer_bq = _get_setting("prefer_best_quality", True)
                if _youtube.is_youtube(url):
                    resolved = _youtube.resolve(url, best_quality=prefer_bq)
                    if resolved:
                        url = resolved
                elif _feratel.is_feratel(url):
                    resolved = _feratel.resolve(url)
                    if resolved:
                        url = resolved
                elif _skyline.is_skylinewebcams(url):
                    resolved = _skyline.resolve(url)
                    if resolved:
                        url = resolved
                        if _youtube.is_youtube(url):
                            yt = _youtube.resolve(url, best_quality=prefer_bq)
                            if yt:
                                url = yt
                elif _earthtv.is_earthtv(url):
                    resolved = _earthtv.resolve(url)
                    if resolved:
                        url = resolved
                elif _earthcam.is_earthcam(url):
                    resolved = _earthcam.resolve(url)
                    if resolved:
                        url = resolved
                play_stream(self.session, url, title=name, is_live=True,
                            player=player, user_agent=user_agent,
                            autoconfigure_serviceapp=_get_setting("serviceapp_autoconfigure", True),
                            prefer_best_quality=prefer_bq,
                            streams=self._items, stream_index=self._list_sel,
                            hls_audio_fix=item.get("hls_audio_fix", False))
            return

        offset = self._page * TILES_PER_PAGE
        idx    = offset + self._sel
        if idx >= len(self._items):
            return

        if self._sort_mode:
            if self._sort_grabbed_abs is None:
                self._sort_grabbed_abs = idx
            else:
                self._sort_grabbed_abs = None
            self._update_sel_marker()
            self._update_legend()
            return

        item       = self._items[idx]
        url        = item.get("url", "")
        name       = item.get("name", "Stream")
        player     = item.get("player", "")
        user_agent = item.get("user_agent", "")
        if url:
            prefer_bq = _get_setting("prefer_best_quality", True)
            if _youtube.is_youtube(url):
                resolved = _youtube.resolve(url, best_quality=prefer_bq)
                if resolved:
                    url = resolved
            elif _feratel.is_feratel(url):
                resolved = _feratel.resolve(url)
                if resolved:
                    url = resolved
            elif _skyline.is_skylinewebcams(url):
                resolved = _skyline.resolve(url)
                if resolved:
                    url = resolved
                    if _youtube.is_youtube(url):
                        yt = _youtube.resolve(url, best_quality=prefer_bq)
                        if yt:
                            url = yt
            elif _earthtv.is_earthtv(url):
                resolved = _earthtv.resolve(url)
                if resolved:
                    url = resolved
            elif _earthcam.is_earthcam(url):
                resolved = _earthcam.resolve(url)
                if resolved:
                    url = resolved
            play_stream(self.session, url, title=name, is_live=True,
                        player=player, user_agent=user_agent,
                        autoconfigure_serviceapp=_get_setting("serviceapp_autoconfigure", True),
                        prefer_best_quality=prefer_bq,
                        streams=self._items, stream_index=idx,
                        hls_audio_fix=item.get("hls_audio_fix", False))


# ------------------------------------------------------------------
# Enigma2-Plugin-Registrierung
# ------------------------------------------------------------------
_autostart_timer = None


def main(session, **kwargs):
    _webif.start()
    session.open(StreamAnywhereScreen)


def autostart(reason, **kwargs):
    global _autostart_timer
    if reason != 0:
        return
    if _get_setting("debug_log", False):
        try:
            open(_SA_DEBUG_FLAG, "w").close()
        except Exception:
            pass
    if not _get_setting("webif_autostart", False):
        return
    try:
        _autostart_timer = eTimer()
        _autostart_timer.callback.append(_webif.start)
        _autostart_timer.start(8000, True)
    except Exception:
        pass


def Plugins(**kwargs):
    return [
        PluginDescriptor(
            name        = b"StreamAnything",
            description = b"Eigene Streams - konfigurierbar per WebIF",
            where       = PluginDescriptor.WHERE_PLUGINMENU,
            icon        = b"plugin.png",
            fnc         = main,
        ),
        PluginDescriptor(
            name  = b"StreamAnything",
            where = PluginDescriptor.WHERE_AUTOSTART,
            fnc   = autostart,
        ),
    ]
