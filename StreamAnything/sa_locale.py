# -*- coding: utf-8 -*-
import gettext
import os

_DOMAIN = "StreamAnything"
_LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locale")

_catalog = None  # GNUTranslations object, or None = pass-through


def _load_catalog():
    global _catalog
    try:
        _catalog = gettext.translation(_DOMAIN, _LOCALE_DIR)
    except Exception:
        _catalog = None


def _saved_language():
    try:
        import streams as _streams
        return _streams.get_config().get("settings", {}).get("language", "auto")
    except Exception:
        return "auto"


def _init():
    lang = _saved_language()
    if lang and lang != "auto":
        os.environ["LANGUAGE"] = lang
    else:
        try:
            from Components.Language import language
            os.environ["LANGUAGE"] = language.getLanguage()[:2]
        except Exception:
            pass
    _load_catalog()


def reinit(lang=None):
    """Sprache neu setzen; lang = 'de' | 'en' | 'auto' | None."""
    if lang and lang != "auto":
        os.environ["LANGUAGE"] = lang
    else:
        try:
            from Components.Language import language
            os.environ["LANGUAGE"] = language.getLanguage()[:2]
        except Exception:
            os.environ.pop("LANGUAGE", None)
    # Clear module-level cache so translation() re-reads the .mo
    try:
        import gettext as _gt
        _gt._translations.clear()
    except Exception:
        pass
    _load_catalog()


def _(txt):
    if _catalog is not None:
        try:
            # Python 2.7: GNUTranslations stores catalog keys as unicode.
            # Decode byte strings before lookup so Umlaut strings are found.
            if isinstance(txt, bytes):
                result = _catalog.gettext(txt.decode("utf-8"))
                if isinstance(result, type(u"")):
                    try:
                        return result.encode("utf-8")
                    except Exception:
                        pass
                return result
            return _catalog.gettext(txt)
        except Exception:
            pass
    return txt


_init()
