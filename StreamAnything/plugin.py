# -*- coding: utf-8 -*-

import os
import threading
from sa_locale import _

from Plugins.Plugin import PluginDescriptor
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
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

PLUGIN_VERSION = "1.6.1"

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
import magentamusik as _magentamusik
from player import play_resolved_stream, resolve_stream_url, HLSRecorder, format_size, format_duration

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


def _get_settings():
    return [
        ("wrap_lr",                  _("Links/Rechts zum Blättern"),       "toggle"),
        ("prefer_best_quality",      _("Höchste Qualität bevorzugen"),     "toggle"),
        ("serviceapp_autoconfigure", _("ServiceApp auto-konfigurieren"),   "toggle"),
        ("webif_autostart",          _("WebIF im Hintergrund"),            "toggle"),
        ("webif_port",               _("WebIF Port"),                      "port"),
        ("debug_log",                _("Debug-Log"),                       "toggle"),
        ("language",                 _("Sprache"),                         "lang"),
    ]


_PORT_OPTIONS = [8080, 8088, 8090, 8181, 8888, 9000]
_LANG_CYCLE   = ["auto", "de", "en"]
_LANG_LABELS  = {"auto": "Auto", "de": "Deutsch", "en": "English"}
_SETTINGS_DEFAULTS = {
    "wrap_lr":                  True,
    "prefer_best_quality":      True,
    "serviceapp_autoconfigure": True,
    "webif_autostart":          True,
    "debug_log":                False,
    "language":                 "auto",
}


# ------------------------------------------------------------------
# Stream-Start (Hintergrundthread)
# ------------------------------------------------------------------
def _resolve_special_url(url, prefer_bq):
    # Standortspezifische Resolver - machen Netzwerkaufrufe, nur aus
    # _play_item_bg() (Hintergrundthread) aufrufen, nie direkt aus einem
    # ActionMap-Tastendruck-Handler.
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
    elif _magentamusik.is_magentamusik(url):
        resolved = _magentamusik.resolve(url)
        if resolved:
            url = resolved
    return url


def _play_item(session, item, idx, items):
    # Startet das Abspielen eines Streams im Hintergrundthread. Sowohl die
    # standortspezifischen Resolver als auch resolve_stream_url() (HLS-
    # Audio-Fix/Best-Quality) machen blockierende HTTP-Anfragen, deren DNS-
    # Aufloesung von timeout=8 nicht zuverlaessig abgedeckt wird - direkt aus
    # dem ActionMap-Tastendruck-Handler ("OK") aufgerufen wuerde das bei
    # einem Netzwerk-Haenger den kompletten Enigma2-Prozess (inkl. WebIF,
    # gleicher GIL) einfrieren.
    url = item.get("url", "")
    if not url:
        return
    import threading
    t = threading.Thread(target=_play_item_bg, args=(session, item, idx, items, url))
    t.daemon = True
    t.start()


def _play_item_bg(session, item, idx, items, url):
    name       = item.get("name", "Stream")
    player     = item.get("player", "")
    user_agent = item.get("user_agent", "")
    hls_fix    = item.get("hls_audio_fix", False)
    referer    = item.get("referer", "")
    prefer_bq  = _get_setting("prefer_best_quality", True)

    url = _resolve_special_url(url, prefer_bq)
    url_str, user_agent = resolve_stream_url(url, user_agent, prefer_bq, hls_fix, referer)

    def _apply():
        play_resolved_stream(session, url_str, title=name, is_live=True,
                             player=player, user_agent=user_agent,
                             autoconfigure_serviceapp=_get_setting("serviceapp_autoconfigure", True),
                             prefer_best_quality=prefer_bq,
                             streams=items, stream_index=idx)

    try:
        from twisted.internet import reactor
        reactor.callFromThread(_apply)
    except Exception:
        _apply()


# ------------------------------------------------------------------
# Live-Aufnahme: parallele Hintergrund-Aufnahmen (kein Warteschlangen-
# Modell wie bei VOD-Downloads in den Schwesterprojekten - eine wartende
# Live-Aufnahme wuerde den gewuenschten Moment verpassen, daher laufen
# beliebig viele Aufnahmen gleichzeitig statt eine aktiv + Rest in Reihe)
# ------------------------------------------------------------------
RECORDING_DIR = "/media/hdd/movie/StreamAnything"

_active_recordings = []
_recordings_lock    = threading.Lock()


def _get_active_recordings():
    with _recordings_lock:
        return list(_active_recordings)


def _start_recording(item, duration_seconds):
    url = item.get("url", "")
    if not url:
        return
    name       = item.get("name", "Aufnahme")
    user_agent = item.get("user_agent", "")
    t = threading.Thread(target=_start_recording_bg, args=(url, name, user_agent, duration_seconds, None))
    t.daemon = True
    t.start()


def _start_recording_from_timer(timer):
    # Vom Scheduler (_check_recording_timers) zur geplanten Zeit aufgerufen.
    # timer_id wird durchgereicht, damit beim Abschluss der recording_timers-
    # Eintrag im WebIF korrekt auf done/error gesetzt werden kann.
    _streams.update_recording_timer_status(timer.get("id"), "running")
    t = threading.Thread(target=_start_recording_bg, args=(
        timer.get("url", ""), timer.get("name", "Aufnahme"),
        timer.get("user_agent", ""), timer.get("duration"), timer.get("id"),
    ))
    t.daemon = True
    t.start()


def _start_recording_bg(url, name, user_agent, duration_seconds, timer_id):
    # Standortspezifische Resolver sind Netzwerkaufrufe (siehe _play_item_bg)
    # - laufen deshalb hier im Hintergrundthread, bevor HLSRecorder (das
    # selbst nochmal einen eigenen Thread fuer die Aufnahmeschleife startet)
    # die finale Stream-URL bekommt.
    prefer_bq = _get_setting("prefer_best_quality", True)
    url = _resolve_special_url(url, prefer_bq)

    if not os.path.isdir(RECORDING_DIR):
        try:
            os.makedirs(RECORDING_DIR)
        except Exception:
            pass

    def _on_finished(rec, *args):
        _on_recording_finished(rec, *args)
        if timer_id:
            try:
                _streams.update_recording_timer_status(timer_id, "error" if args else "done")
            except Exception:
                pass

    rec = HLSRecorder(
        url, name, RECORDING_DIR, user_agent=user_agent, duration=duration_seconds,
        on_done=_on_finished, on_error=_on_finished,
    )
    with _recordings_lock:
        _active_recordings.append(rec)
    rec.start()


def _on_recording_finished(rec, *args):
    # Gemeinsamer Callback fuer on_done (rec) und on_error (rec, err) -
    # in beiden Faellen einfach aus der Liste der laufenden Aufnahmen
    # entfernen, Fehlerdetails landen ohnehin nur im Debug-Log.
    with _recordings_lock:
        if rec in _active_recordings:
            _active_recordings.remove(rec)
    if args:
        _dbg("Aufnahme-Fehler: %s - %s" % (rec.title, args[0]))
    else:
        _dbg("Aufnahme fertig: %s -> %s" % (rec.title, rec.filepath))


def _cancel_recording(rec):
    rec.cancel()


def _get_active_recordings_info():
    # JSON-serialisierbare Sicht auf _active_recordings fuers WebIF.
    out = []
    for rec in _get_active_recordings():
        out.append({
            "id":         rec.rec_id,
            "title":      _u(rec.title),
            "elapsed":    int(rec.elapsed()),
            "duration":   rec.duration,
            "downloaded": rec._downloaded,
        })
    return out


def _cancel_recording_by_id(rec_id):
    for rec in _get_active_recordings():
        if rec.rec_id == rec_id:
            rec.cancel()
            return True
    return False


# ------------------------------------------------------------------
# Deep-Standby-Wecktimer: ein reiner "justplay"-Eintrag im nativen
# Enigma2-RecordTimer-System, der NICHTS aufnimmt - er dient ausschliesslich
# dazu, die Box rechtzeitig aus dem Deep-Standby zu wecken (Enigma2s
# RTC-Aufwach-Mechanismus beruecksichtigt alle anstehenden Timer-Eintraege,
# nicht nur echte Aufnahmen). Der tatsaechliche Aufnahme-Start passiert
# danach ausschliesslich ueber unseren eigenen Scheduler weiter unten,
# sobald die Box wieder laeuft. dontSave=True haelt ihn aus der dauerhaft
# gespeicherten Timer-Liste raus - nach einem echten Reboot wird er daher
# in autostart() fuer alle noch offenen Timer frisch neu registriert.
# ------------------------------------------------------------------
_WAKEUP_NAME_PREFIX  = "StreamAnything-Wecktimer: "
_wakeup_reregistered = False


def _register_wakeup_timer(timer_id, name, start_time):
    try:
        import NavigationInstance
        if NavigationInstance.instance is None:
            _dbg("Wecktimer-Registrierung: NavigationInstance.instance ist None")
            return
        from RecordTimer import RecordTimerEntry
        from ServiceReference import ServiceReference
        ref = NavigationInstance.instance.getCurrentlyPlayingServiceReference()
        if ref is None:
            from enigma import eServiceReference
            ref = eServiceReference(eServiceReference.idDVB, 0)
        # Eigener Name statt des aktuell laufenden Senders, damit der reine
        # Wecktimer in der nativen Timer-Liste nicht mit einem zufaelligen/
        # verwirrenden Kanalnamen auftaucht (Zap-Ziel bleibt unveraendert,
        # nur die Anzeige wird ueberschrieben).
        ref.setName(_b("StreamAnything"))
        begin = int(start_time)
        end   = begin + 300
        entry_name = _u(_WAKEUP_NAME_PREFIX) + u"%s [%s]" % (_u(name), timer_id)
        entry = RecordTimerEntry(ServiceReference(ref), begin, end, _b(entry_name), _b(""), None, justplay=True)
        entry.dontSave = True
        NavigationInstance.instance.RecordTimer.record(entry)
        _dbg("Wecktimer registriert: %s @ %s" % (entry_name, begin))
    except Exception as e:
        _dbg("Wecktimer-Registrierung fehlgeschlagen: %s" % e)


def _unregister_wakeup_timer(timer_id):
    try:
        import NavigationInstance
        if NavigationInstance.instance is None:
            return
        rt = NavigationInstance.instance.RecordTimer
        suffix = u"[%s]" % timer_id
        for entry in list(rt.timer_list) + list(rt.processed_timers):
            ename = _u(entry.name) if entry.name else u""
            if ename.startswith(_u(_WAKEUP_NAME_PREFIX)) and ename.endswith(suffix):
                rt.removeEntry(entry)
    except Exception as e:
        _dbg("Wecktimer-Entfernung fehlgeschlagen: %s" % e)


def _has_wakeup_timer(timer_id):
    try:
        import NavigationInstance
        if NavigationInstance.instance is None:
            return False
        rt = NavigationInstance.instance.RecordTimer
        suffix = u"[%s]" % timer_id
        for entry in list(rt.timer_list) + list(rt.processed_timers):
            ename = _u(entry.name) if entry.name else u""
            if ename.startswith(_u(_WAKEUP_NAME_PREFIX)) and ename.endswith(suffix):
                return True
    except Exception:
        pass
    return False


def _get_valid_pending_timers():
    # Pending-Timer aus JSON, deren Wecktimer noch aktiv ist.
    # Wurde ein Eintrag extern (z.B. VTI-Timer-Editor) geloescht,
    # wird er still aus JSON entfernt, damit er nach dem naechsten
    # Reboot nicht wieder als Wecktimer registriert wird.
    import time as _time
    now = _time.time()
    result = []
    for t in _streams.get_recording_timers():
        if t.get("status") != "pending":
            continue
        start = t.get("start_time", 0)
        if now >= start:
            result.append(t)
            continue
        if not _wakeup_reregistered or _has_wakeup_timer(t.get("id")):
            result.append(t)
        else:
            _streams.delete_recording_timer(t.get("id"))
            _dbg("Wecktimer extern geloescht (VTI?), JSON-Eintrag entfernt: %s" % t.get("name"))
    return result


# ------------------------------------------------------------------
# Timer-Scheduler: prueft periodisch, ob ein geplanter recording_timer
# faellig ist. Laeuft unabhaengig davon, ob die Plugin-GUI offen ist
# (gestartet aus autostart() bei Enigma2-Boot) - deckt zusammen mit dem
# Wecktimer oben sowohl "Box an"/normales Standby als auch Deep-Standby ab.
# ------------------------------------------------------------------
_scheduler_timer = None
_TIMER_LATE_GRACE_SECONDS = 600  # mehr als 10min zu spaet -> Box war vermutlich aus, nicht mehr sinnvoll starten


def _check_recording_timers():
    import time as _time
    now = _time.time()
    for t in _get_valid_pending_timers():
        start = t.get("start_time", 0)
        if now < start:
            continue
        _unregister_wakeup_timer(t.get("id"))
        if now - start > _TIMER_LATE_GRACE_SECONDS:
            _streams.update_recording_timer_status(t.get("id"), "error")
            _dbg("Timer verpasst (Box vermutlich aus): %s" % t.get("name"))
            continue
        _start_recording_from_timer(t)


_wakeup_reregister_timer = None


def _reregister_wakeup_timers():
    # Nach einem echten Reboot/GUI-Neustart sind alle dontSave=True-
    # Wecktimer weg (siehe _register_wakeup_timer) - fuer alle noch offenen
    # Timer frisch neu registrieren, sonst wuerde ein geplanter Deep-
    # Standby-Wakeup nach einem Neustart verpasst. Laeuft verzoegert (siehe
    # _start_scheduler), weil NavigationInstance.instance direkt bei
    # autostart() noch None ist (Session ist da noch nicht bereit) - exakt
    # dasselbe Timing-Problem, das der bestehende WebIF-Autostart bereits
    # mit einem 8s-Delay umgeht.
    global _wakeup_reregistered
    pending = [t for t in _streams.get_recording_timers() if t.get("status") == "pending"]
    _dbg("_reregister_wakeup_timers: %d pending Timer" % len(pending))
    for t in pending:
        _register_wakeup_timer(t.get("id"), t.get("name", "Aufnahme"), t.get("start_time", 0))
    _wakeup_reregistered = True


def _start_scheduler():
    global _scheduler_timer, _wakeup_reregister_timer
    if _scheduler_timer is not None:
        return
    _scheduler_timer = eTimer()
    _scheduler_timer.callback.append(_check_recording_timers)
    _scheduler_timer.start(30000, False)

    _wakeup_reregister_timer = eTimer()
    _wakeup_reregister_timer.callback.append(_reregister_wakeup_timers)
    _wakeup_reregister_timer.start(8000, True)


class StreamAnywhereRecordingsScreen(Screen):
    if IS_FHD:
        skin = """
        <screen name="StreamAnywhereRecordingsScreen" position="360,175" size="1200,730" flags="wfNoBorder">
            <eLabel position="0,0" size="1200,730" backgroundColor="#33000000" zPosition="-6" />
            <eLabel position="0,0" size="1200,4" backgroundColor="#962d20" zPosition="1" />
            <widget name="title_label" position="40,30"  size="1120,60"  font="Regular;36" halign="center" foregroundColor="#00cc3d2d" transparent="1" />
            <eLabel position="40,110" size="1120,2" backgroundColor="#44FFFFFF" zPosition="1" />
            <widget name="rec_label"  position="40,130" size="1120,540" font="Regular;28" halign="left" valign="top" foregroundColor="#FFFFFF" transparent="1" />
            <eLabel position="40,690" size="8,40" backgroundColor="#CC0000" zPosition="2" />
            <widget name="hint_red"   position="56,684"  size="500,50" font="Regular;28" halign="left"  valign="center" foregroundColor="#CCCCCC" transparent="1" />
            <widget name="hint_exit"  position="780,684" size="380,50" font="Regular;28" halign="right" valign="center" foregroundColor="#AAAAAA" transparent="1" />
        </screen>"""
    else:
        skin = """
        <screen name="StreamAnywhereRecordingsScreen" position="240,116" size="800,488" flags="wfNoBorder">
            <eLabel position="0,0" size="800,488" backgroundColor="#33000000" zPosition="-6" />
            <eLabel position="0,0" size="800,3" backgroundColor="#962d20" zPosition="1" />
            <widget name="title_label" position="27,20"  size="746,40"  font="Regular;24" halign="center" foregroundColor="#00cc3d2d" transparent="1" />
            <eLabel position="27,72" size="746,2" backgroundColor="#44FFFFFF" zPosition="1" />
            <widget name="rec_label"  position="27,82"  size="746,358" font="Regular;19" halign="left" valign="top" foregroundColor="#FFFFFF" transparent="1" />
            <eLabel position="27,452" size="5,27" backgroundColor="#CC0000" zPosition="2" />
            <widget name="hint_red"   position="38,449"  size="330,33" font="Regular;19" halign="left"  valign="center" foregroundColor="#CCCCCC" transparent="1" />
            <widget name="hint_exit"  position="520,449" size="253,33" font="Regular;19" halign="right" valign="center" foregroundColor="#AAAAAA" transparent="1" />
        </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self._sel = 0

        self["title_label"] = Label(_b(_("Aufnahmen")))
        self["rec_label"]   = Label(_b(""))
        self["hint_red"]    = Label(_b(_("Markierte Aufnahme stoppen")))
        self["hint_exit"]   = Label(_b(_("EXIT = Schließen")))

        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions"],
            {
                "cancel":       self.close,
                "ok":           self.close,
                "up":           lambda: self._move(-1),
                "down":         lambda: self._move(1),
                "upRepeated":   lambda: self._move(-1),
                "downRepeated": lambda: self._move(1),
                "red":          self._stop_selected,
            },
            -1,
        )

        self._poll_timer = eTimer()
        self._poll_timer.callback.append(self._poll)
        self._poll_timer.start(1000, False)
        self.onClose.append(self.__stop_timer)
        self._poll()

    def __stop_timer(self):
        try:
            self._poll_timer.stop()
        except Exception:
            pass

    def _move(self, delta):
        recs = _get_active_recordings()
        if not recs:
            return
        self._sel = (self._sel + delta) % len(recs)
        self._render(recs)

    def _stop_selected(self):
        recs = _get_active_recordings()
        if not recs or self._sel >= len(recs):
            return
        _cancel_recording(recs[self._sel])

    def _poll(self):
        recs = _get_active_recordings()
        if self._sel >= len(recs):
            self._sel = max(0, len(recs) - 1)
        self._render(recs)

    def _render(self, recs):
        if not recs:
            self["rec_label"].setText(_b(_("Keine laufende Aufnahme")))
            return
        lines = []
        for i, rec in enumerate(recs):
            marker = "> " if i == self._sel else "   "
            title  = _u(rec.title)
            limit  = format_duration(rec.duration) if rec.duration else _("unbegrenzt")
            lines.append(u"%s%s\n   %s / %s  -  %s" % (
                marker, title, format_duration(rec.elapsed()), limit, format_size(rec._downloaded)
            ))
        self["rec_label"].setText(_b(u"\n\n".join(lines)))


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
            '<eLabel backgroundColor="#1ACCAA00" position="568,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_yellow" position="586,{ly}"  size="150,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_ok"     position="586,{ly}"  size="190,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<eLabel backgroundColor="#1A0066FF" position="788,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_blue"   position="806,{ly}"  size="160,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_menu"   position="1036,{ly}" size="280,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_info"   position="1338,{ly}" size="300,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
            '<widget name="page_label"  position="1648,{ly}" size="242,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;28" halign="right" valign="center" foregroundColor="#AAAAAA" noWrap="1"/>'
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
            '<eLabel backgroundColor="#1A00AA00" position="188,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_green"  position="197,{ly}"  size="130,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<eLabel backgroundColor="#1ACCAA00" position="353,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_yellow" position="362,{ly}"  size="100,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_ok"     position="362,{ly}"  size="120,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<eLabel backgroundColor="#1A0066FF" position="488,{py}" size="{pw},{ph}" zPosition="2" transparent="0"/>'
            '<widget name="hint_blue"   position="498,{ly}"  size="90,{lh}"  zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_menu"   position="608,{ly}"  size="188,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC"/>'
            '<widget name="hint_info"   position="811,{ly}"  size="195,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="left"  valign="center" foregroundColor="#CCCCCC" noWrap="1"/>'
            '<widget name="page_label"  position="1016,{ly}" size="230,{lh}" zPosition="4" transparent="1" backgroundColor="#1A000000" font="Regular;{fs}" halign="right" valign="center" foregroundColor="#AAAAAA" noWrap="1"/>'
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
    n = len(_get_settings())
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
def _get_ua_choices():
    return [
        (_("(keiner)"),      ""),
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
        list=[(_b(_("Ja")), True), (_b(_("Nein")), False)],
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
        self["ch_ok"]    = Label(_b(_("OK = Auswählen")))
        self["ch_pip_g"] = Label(_b(""))
        self["ch_green"] = Label(_b(_("Speichern")))
        self["ch_pip_r"] = Label(_b(""))
        self["ch_red"]   = Label(_b(_("Abbrechen")))
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
        _sa_confirm(self.session, _b(_("Ohne Speichern beenden?")), on_confirm)


def _stream_context_menu(session, item, update_fn, refresh_cb, delete_fn=None, _original=None):
    if _original is None:
        _original = dict(
            player        = item.get("player", ""),
            user_agent    = item.get("user_agent", ""),
            hls_audio_fix = item.get("hls_audio_fix", False),
            referer       = item.get("referer", ""),
        )

    def _reopen():
        _stream_context_menu(session, item, update_fn, refresh_cb, delete_fn, _original)

    def _has_changes():
        return (item.get("player", "")           != _original["player"]        or
                item.get("user_agent", "")       != _original["user_agent"]    or
                item.get("hls_audio_fix", False) != _original["hls_audio_fix"] or
                item.get("referer", "")          != _original["referer"])

    def _save():
        update_fn(item)
        refresh_cb()

    _PLAYER_LABELS = {
        "":            _("Auto"),
        "exteplayer3": "exteplayer3",
        "gstplayer":   "GStreamer",
        "default":     _("Standard"),
    }
    cur_player  = item.get("player", "")
    cur_ua      = _u(item.get("user_agent", ""))
    cur_hls_fix = item.get("hls_audio_fix", False)
    cur_referer = _u(item.get("referer", ""))
    cur_ua_label = next((label for label, val in _get_ua_choices() if val == cur_ua), None)
    if cur_ua_label is None:
        cur_ua_label = (cur_ua[:20] + "...") if len(cur_ua) > 20 else (cur_ua or _("(keiner)"))
    if cur_referer == "auto":
        cur_ref_label = _("Auto")
    elif cur_referer:
        cur_ref_label = (cur_referer[:25] + "...") if len(cur_referer) > 25 else cur_referer
    else:
        cur_ref_label = _("AUS")

    choices = [
        (_b(_("Player:     ") + _PLAYER_LABELS.get(cur_player, _("Auto"))),              "player"),
        (_b(_("User-Agent: ") + cur_ua_label),                                            "ua"),
        (_b(_("Lok. Playlist Server: ") + (_("EIN") if cur_hls_fix else _("AUS"))),      "hls_fix"),
        (_b(_("Quell-Website: ") + cur_ref_label),                                        "referer"),
        (_b(_("Aufnahme starten")),                                                       "record"),
        (_b(_("Löschen")),                                                                "delete"),
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

    def on_referer_custom(result):
        if result is not None:
            item["referer"] = result.strip() or "auto"
        _reopen()

    def on_referer_choice(choice):
        if choice is None:
            _reopen()
            return
        if choice[1] == "__custom__":
            cur = item.get("referer", "")
            init = cur if cur not in ("", "auto") else "https://"
            if not isinstance(init, str):
                init = init.encode("utf-8")
            session.openWithCallback(on_referer_custom, VirtualKeyBoard,
                                     title=_b(_("Als Quell-Website ausgeben")),
                                     text=init)
        else:
            item["referer"] = choice[1]
            _reopen()

    def on_delete_confirm(answer):
        if answer and delete_fn:
            delete_fn()

    def on_choice(choice):
        if choice is None:
            return
        if choice[1] == "player":
            pchoices = [
                (_b(_("Auto")),      ""),
                (_b("exteplayer3"),  "exteplayer3"),
                (_b("GStreamer"),    "gstplayer"),
                (_b(_("Standard")), "default"),
            ]
            session.openWithCallback(on_player, _SAChoiceScreen,
                                     title=_b(_("Player wählen")), list=pchoices)
        elif choice[1] == "ua":
            ua_list = [(_b(label), val) for label, val in _get_ua_choices()]
            session.openWithCallback(on_ua, _SAChoiceScreen,
                                     title=_b(_("User-Agent wählen")), list=ua_list)
        elif choice[1] == "hls_fix":
            item["hls_audio_fix"] = not item.get("hls_audio_fix", False)
            _reopen()
        elif choice[1] == "referer":
            rchoices = [
                (_b(_("AUS")),              ""),
                (_b(_("Auto")),             "auto"),
                (_b(_("Website angeben")),  "__custom__"),
            ]
            session.openWithCallback(on_referer_choice, _SAChoiceScreen,
                                     title=_b(_("Als Quell-Website ausgeben")), list=rchoices)
        elif choice[1] == "record":
            _open_record_duration_menu(session, item)
        elif choice[1] == "delete" and delete_fn:
            _sa_confirm(session, _b(_("Stream löschen?")), on_delete_confirm)

    session.openWithCallback(on_choice, _SAChoiceScreen,
                             title=_b(_u(item.get("name", "Stream"))),
                             list=choices,
                             on_save_fn=_save,
                             has_changes_fn=_has_changes)


def _open_record_duration_menu(session, item):
    presets = [
        (_("30 Minuten"),    30 * 60),
        (_("1 Stunde"),      60 * 60),
        (_("2 Stunden"),     2 * 60 * 60),
        (_("3 Stunden"),     3 * 60 * 60),
        (_("6 Stunden"),     6 * 60 * 60),
        (_("Bis ich stoppe"), None),
    ]
    choices = [(_b(label), seconds) for label, seconds in presets]
    choices.append((_b(_("Eigene Dauer (Minuten) …")), "custom"))
    choices.append((_b(_("Für später planen …")), "schedule"))

    def on_custom_minutes(text):
        if not text:
            return
        try:
            minutes = int(_u(text).strip())
        except (ValueError, TypeError):
            return
        if minutes <= 0:
            return
        _start_recording(item, minutes * 60)

    def on_duration(choice):
        if choice is None:
            return
        if choice[1] == "custom":
            session.openWithCallback(on_custom_minutes, VirtualKeyBoard,
                                     title=_b(_("Dauer in Minuten eingeben:")), text="")
        elif choice[1] == "schedule":
            _open_native_timer_editor(session, item)
        else:
            _start_recording(item, choice[1])

    session.openWithCallback(on_duration, _SAChoiceScreen,
                             title=_b(_("Aufnahmedauer wählen")), list=choices)


def _open_native_timer_editor(session, item):
    # Nutzt Enigma2s eingebauten Timer-Editor NUR als Eingabemaske fuer
    # Start-/Endzeit (native Datum/Uhrzeit-Spinner, viel angenehmer per
    # Fernbedienung als Texteingabe). Der editierte Eintrag wird NICHT
    # selbst als nativer Timer registriert - wir lesen nur begin/end aus
    # dem Ergebnis aus und legen daraus ganz normal einen eigenen
    # recording_timer an (wie auch das WebIF es tut), inkl. Wecktimer.
    try:
        from Screens.TimerEntry import TimerEntry
        from ServiceReference import ServiceReference
        from RecordTimer import RecordTimerEntry
        import NavigationInstance
        import time as _time

        ref = None
        if NavigationInstance.instance is not None:
            ref = NavigationInstance.instance.getCurrentlyPlayingServiceReference()
        if ref is None:
            from enigma import eServiceReference
            ref = eServiceReference(eServiceReference.idDVB, 0)
        ref.setName(_b("StreamAnything"))

        name  = item.get("name", "Aufnahme")
        begin = int(_time.time()) + 3600
        end   = begin + 3600
        draft = RecordTimerEntry(ServiceReference(ref), begin, end, _b(name), _b(""), None, justplay=True)

        def on_edited(answer):
            if not answer or not answer[0]:
                return
            entry = answer[1]
            timer = _streams.add_recording_timer(
                item.get("name", "Aufnahme"), item.get("url", ""),
                entry.begin, item.get("user_agent", ""),
                max(60, entry.end - entry.begin),
            )
            _register_wakeup_timer(timer["id"], timer["name"], timer["start_time"])

        session.openWithCallback(on_edited, TimerEntry, draft)
    except Exception as e:
        _dbg("Nativer Timer-Editor fehlgeschlagen: %s" % e)


# ------------------------------------------------------------------
# Settings-Screen
# ------------------------------------------------------------------
class StreamAnywhereSettingsScreen(Screen):

    skin = _build_settings_skin()

    def __init__(self, session):
        Screen.__init__(self, session)
        self._sel = 0

        self["s_title"] = Label(_b(_("Einstellungen")))
        for i, (key, label, kind) in enumerate(_get_settings()):
            self["s_sel_%d"   % i] = Label(_b(""))
            self["s_label_%d" % i] = Label(_b(label))
            self["s_value_%d" % i] = Label(_b(""))

        self["hint_ok"]    = Label(_b(_("OK = Ändern")))
        self["hint_green"] = Label(_b(_("Speichern")))
        self["hint_red"]   = Label(_b(_("Abbrechen")))

        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions"],
            {
                "ok":           self._on_ok,
                "cancel":       self._on_red,
                "up":           self._move_up,
                "down":         self._move_down,
                "upRepeated":   self._move_up,
                "downRepeated": self._move_down,
                "green":        self._on_green,
                "red":          self._on_red,
            },
            -1,
        )

        self._pending = {}
        for key, label, kind in _get_settings():
            if kind == "toggle":
                self._pending[key] = _get_setting(key, _SETTINGS_DEFAULTS.get(key, False))
            elif kind == "port":
                self._pending[key] = _streams.get_webif_port()
            elif kind == "lang":
                self._pending[key] = _get_setting(key, "auto")
        self._original = dict(self._pending)

        self._refresh()

    def _refresh(self):
        settings = _get_settings()
        self["s_title"].setText(_b(_("Einstellungen")))
        self["hint_ok"].setText(_b(_("OK = Ändern")))
        self["hint_green"].setText(_b(_("Speichern")))
        self["hint_red"].setText(_b(_("Abbrechen")))
        for i, (key, label, kind) in enumerate(settings):
            self["s_label_%d" % i].setText(_b(label))
            if kind == "toggle":
                val = self._pending.get(key, _SETTINGS_DEFAULTS.get(key, False))
                self["s_value_%d" % i].setText(_b(_("EIN") if val else _("AUS")))
            elif kind == "port":
                self["s_value_%d" % i].setText(_b(str(self._pending.get(key, 8090))))
            elif kind == "lang":
                lv = self._pending.get(key, "auto")
                self["s_value_%d" % i].setText(_b(_LANG_LABELS.get(lv, lv)))
            else:
                self["s_value_%d" % i].setText(_b(""))
            if i == self._sel:
                self["s_sel_%d" % i].show()
            else:
                self["s_sel_%d" % i].hide()

    def _move_up(self):
        n = len(_get_settings())
        if n == 0:
            return
        self._sel = (self._sel - 1) % n
        self._refresh()

    def _move_down(self):
        n = len(_get_settings())
        if n == 0:
            return
        self._sel = (self._sel + 1) % n
        self._refresh()

    def _on_ok(self):
        key, label, kind = _get_settings()[self._sel]
        if kind == "toggle":
            self._pending[key] = not self._pending.get(key, _SETTINGS_DEFAULTS.get(key, False))
            self._refresh()
        elif kind == "lang":
            cur = self._pending.get(key, "auto")
            nxt = _LANG_CYCLE[(_LANG_CYCLE.index(cur) + 1) % len(_LANG_CYCLE)] if cur in _LANG_CYCLE else "auto"
            self._pending[key] = nxt
            import sa_locale as _sa_locale
            _sa_locale.reinit(nxt)
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
                                          title=_b(_("WebIF Port wählen")),
                                          list=choices)

    def _on_green(self):
        for key, label, kind in _get_settings():
            if kind == "toggle":
                _set_setting(key, self._pending[key])
            elif kind == "port":
                new_port = self._pending.get(key, 8090)
                if new_port != _streams.get_webif_port():
                    _streams.set_webif_port(new_port)
                    _webif.stop()
                    _webif.start(new_port)
            elif kind == "lang":
                _set_setting(key, self._pending.get(key, "auto"))
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
            _sa_confirm(self.session, _b(_("Einstellungen ohne Speichern verlassen?")), on_confirm)
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
        self["hint_yellow"] = Label(_b(""))
        self["hint_blue"]   = Label(_b(""))
        self["hint_menu"]   = Label(_b(""))
        self["hint_info"]   = Label(_b(""))
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
             "ChannelSelectBaseActions", "MenuActions", "InfobarSeekActions",
             "EPGSelectActions"],
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
                "blue":              self._key_blue,
                "menu":              self._key_menu,
                "info":              self._key_info,
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

    def _update_info_hint(self):
        self["hint_info"].setText(_b(_("EPG/INFO = Aufnahmen")) if _get_active_recordings() else _b(""))

    def _poll_config(self):
        self._update_info_hint()
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
            _sa_confirm(self.session, _b(_("Sortierung verwerfen?")), on_confirm)
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

        page_label = _("CH+/- Seite %d/%d") % (self._page + 1, pages) if pages > 1 else ""
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
            # Kein oberes Clamping gegen total-LIST_ROWS: sonst wuerde die letzte
            # Seite kuenstlich zurueckgezogen und beim Runterscrollen ans Ende
            # landet der neue Eintrag nicht mehr oben, sondern mitten in einer
            # ueberlappenden vollen Seite. _render_list() blendet ueberzaehlige
            # Zeilen ohnehin per hide() aus, eine echte Teilseite ist also ok.
            self._list_scroll = max(0, self._list_scroll)

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
            self["hint_red"].setText(_b(_("Sortieren")))
            self["hint_green"].setText(_b(_("Einstellungen")))
            self["hint_yellow"].setText(_b(_("Kacheln")) if self._list_mode else _b(_("Liste")))
            self["hint_ok"].setText(_b(""))
            self["hint_menu"].setText(_b(_("MENU = Bearbeiten")) if item else _b(""))
            if item and item.get("type") != "folder":
                self["hint_blue"].setText(_b(_("Aufnahme")))
            else:
                self["hint_blue"].setText(_b(""))
        elif self._sort_grabbed_abs is None:
            self["hint_green"].setText(_b(_("Fertig")))
            self["hint_red"].setText(_b(_("Rückgängig")))
            self["hint_ok"].setText(_b(_("OK = Greifen")))
            self["hint_yellow"].setText(_b(""))
            self["hint_menu"].setText(_b(""))
            self["hint_blue"].setText(_b(""))
        else:
            self["hint_green"].setText(_b(_("Fertig")))
            self["hint_red"].setText(_b(_("Rückgängig")))
            self["hint_ok"].setText(_b(_("OK = Ablegen")))
            self["hint_yellow"].setText(_b(""))
            self["hint_menu"].setText(_b(""))
            self["hint_blue"].setText(_b(""))

        self._update_info_hint()

        if self._list_mode:
            total = len(self._items)
            self["page_label"].setText(_b("%d/%d" % (self._list_sel + 1, total) if total > 0 else ""))

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

    def _key_blue(self):
        if self._sort_mode:
            return
        if self._list_mode:
            idx = self._list_sel
        else:
            idx = self._page * TILES_PER_PAGE + self._sel
        if idx >= len(self._items):
            return
        item = self._items[idx]
        if item.get("type") == "folder":
            return
        _open_record_duration_menu(self.session, item)

    def _key_info(self):
        self.session.open(StreamAnywhereRecordingsScreen)

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
            _sa_confirm(self.session, _b(_("Ordner und alle Streams löschen?")), on_delete_folder)
            return

        def update(it):
            _streams.update_flat_stream(it["id"],
                                        player=it.get("player", ""),
                                        user_agent=it.get("user_agent", ""),
                                        hls_audio_fix=it.get("hls_audio_fix", False),
                                        referer=it.get("referer", ""))

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
        if self._list_sel < old_scroll or self._list_sel >= old_scroll + LIST_ROWS:
            # Beim Verlassen der sichtbaren Seite springt der neue Eintrag an den
            # Seitenrand, der in Bewegungsrichtung liegt (Systemlisten-Verhalten:
            # runter -> neuer Eintrag oben, hoch -> neuer Eintrag unten), statt
            # nur zeilenweise mit dem Cursor am Rand kleben zu bleiben.
            if step > 0:
                self._list_scroll = self._list_sel
            else:
                self._list_scroll = self._list_sel - LIST_ROWS + 1
        # Kein oberes Clamping gegen total-LIST_ROWS: sonst wuerde die letzte
        # Seite kuenstlich zurueckgezogen und beim Runterscrollen ans Ende
        # landet der neue Eintrag nicht mehr oben, sondern mitten in einer
        # ueberlappenden vollen Seite. _render_list() blendet ueberzaehlige
        # Zeilen ohnehin per hide() aus, eine echte Teilseite ist also ok.
        self._list_scroll = max(0, self._list_scroll)
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
            _play_item(self.session, item, self._list_sel, self._items)
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
            _play_item(self.session, item, idx, self._items)


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
        self["hint_yellow"] = Label(_b(""))
        self["hint_blue"]   = Label(_b(""))
        self["hint_menu"]   = Label(_b(""))
        self["hint_info"]   = Label(_b(""))
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
             "ChannelSelectBaseActions", "MenuActions", "InfobarSeekActions",
             "EPGSelectActions"],
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
                "blue":              self._key_blue,
                "menu":              self._key_menu,
                "info":              self._key_info,
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

    def _update_info_hint(self):
        self["hint_info"].setText(_b(_("EPG/INFO = Aufnahmen")) if _get_active_recordings() else _b(""))

    def _poll_config(self):
        self._update_info_hint()
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
            _sa_confirm(self.session, _b(_("Sortierung verwerfen?")), on_confirm)
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

        page_label = _("CH+/- Seite %d/%d") % (self._page + 1, pages) if pages > 1 else ""
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
            # Kein oberes Clamping gegen total-LIST_ROWS: sonst wuerde die letzte
            # Seite kuenstlich zurueckgezogen und beim Runterscrollen ans Ende
            # landet der neue Eintrag nicht mehr oben, sondern mitten in einer
            # ueberlappenden vollen Seite. _render_list() blendet ueberzaehlige
            # Zeilen ohnehin per hide() aus, eine echte Teilseite ist also ok.
            self._list_scroll = max(0, self._list_scroll)

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
            self["hint_red"].setText(_b(_("Sortieren")))
            self["hint_green"].setText(_b(_("Einstellungen")))
            self["hint_ok"].setText(_b(""))
            self["hint_yellow"].setText(_b(_("Kacheln")) if self._list_mode else _b(_("Liste")))
            self["hint_menu"].setText(_b(_("MENU = Bearbeiten")) if item else _b(""))
            if item and item.get("type") != "folder":
                self["hint_blue"].setText(_b(_("Aufnahme")))
            else:
                self["hint_blue"].setText(_b(""))
        elif self._sort_grabbed_abs is None:
            self["hint_green"].setText(_b(_("Fertig")))
            self["hint_red"].setText(_b(_("Rückgängig")))
            self["hint_ok"].setText(_b(_("OK = Greifen")))
            self["hint_yellow"].setText(_b(""))
            self["hint_menu"].setText(_b(""))
            self["hint_blue"].setText(_b(""))
        else:
            self["hint_green"].setText(_b(_("Fertig")))
            self["hint_red"].setText(_b(_("Rückgängig")))
            self["hint_ok"].setText(_b(_("OK = Ablegen")))
            self["hint_yellow"].setText(_b(""))
            self["hint_menu"].setText(_b(""))
            self["hint_blue"].setText(_b(""))

        self._update_info_hint()

        if self._list_mode:
            total = len(self._items)
            self["page_label"].setText(_b("%d/%d" % (self._list_sel + 1, total) if total > 0 else ""))

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

    def _key_blue(self):
        if self._sort_mode:
            return
        if self._list_mode:
            idx = self._list_sel
        else:
            idx = self._page * TILES_PER_PAGE + self._sel
        if idx >= len(self._items):
            return
        item = self._items[idx]
        if item.get("type") == "folder":
            return
        _open_record_duration_menu(self.session, item)

    def _key_info(self):
        self.session.open(StreamAnywhereRecordingsScreen)

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
        if self._list_sel < old_scroll or self._list_sel >= old_scroll + LIST_ROWS:
            # Beim Verlassen der sichtbaren Seite springt der neue Eintrag an den
            # Seitenrand, der in Bewegungsrichtung liegt (Systemlisten-Verhalten:
            # runter -> neuer Eintrag oben, hoch -> neuer Eintrag unten), statt
            # nur zeilenweise mit dem Cursor am Rand kleben zu bleiben.
            if step > 0:
                self._list_scroll = self._list_sel
            else:
                self._list_scroll = self._list_sel - LIST_ROWS + 1
        # Kein oberes Clamping gegen total-LIST_ROWS: sonst wuerde die letzte
        # Seite kuenstlich zurueckgezogen und beim Runterscrollen ans Ende
        # landet der neue Eintrag nicht mehr oben, sondern mitten in einer
        # ueberlappenden vollen Seite. _render_list() blendet ueberzaehlige
        # Zeilen ohnehin per hide() aus, eine echte Teilseite ist also ok.
        self._list_scroll = max(0, self._list_scroll)
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
                                         hls_audio_fix=it.get("hls_audio_fix", False),
                                         referer=it.get("referer", ""))

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
            item = self._items[self._list_sel]
            _play_item(self.session, item, self._list_sel, self._items)
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
        _play_item(self.session, item, idx, self._items)


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

    # Timer-Scheduler laeuft unabhaengig vom WebIF-Autostart-Setting -
    # geplante Aufnahmen sollen auch dann feuern, wenn der User das WebIF
    # im Hintergrund nicht staendig laufen lassen will.
    try:
        _start_scheduler()
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
            description = _b(_("Eigene Streams - konfigurierbar per WebIF")),
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
