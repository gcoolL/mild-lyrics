#!/usr/bin/env python3
"""
Apple Music / Spicy Lyrics-style lyrics window for the running Spotify app.

Reads Spicy Lyrics' cache over CDP (see spicy_lyrics.py) and renders it against
the MPRIS playback clock. Layout mirrors the Spicy Lyrics view in Spotify:
album art panel on the left, lyrics column on the right, every line the same
size with depth conveyed by opacity + distance blur rather than scaling, and
the active line filling syllable-by-syllable as it is sung.

Requires Spotify started with a DevTools port:

    spotify --remote-debugging-port=9222 &

Run:
    ./lyrics_gui.py                 # windowed
    ./lyrics_gui.py --fullscreen
    ./lyrics_gui.py --offset -0.3   # start with a timing offset
    ./lyrics_gui.py --split long    # subdivide held words (interpolated)
    ./lyrics_gui.py --top --opacity 0.9   # desktop overlay
    ./lyrics_gui.py --no-resync     # don't nudge Spotify on auto-advance
    ./lyrics_gui.py --no-auto-time  # don't measure each song's own timing
    ./lyrics_gui.py --unpause-delay 0.3   # hold the words longer on unpause

Look:
    ./lyrics_gui.py --bg mesh --align center --sung-color auto
    ./lyrics_gui.py --focus 2 --bg-dim 0.85     # cinematic, one line at a time
    ./lyrics_gui.py --bg solid --bg-motion 0 --pop 0 --edge 0   # flat and still

Keys:
    M         settings menu -- everything below is editable there, so there is
              nothing to memorise; arrows or the scroll wheel change a value
    /         search every cached song by any line in it, Enter plays the hit
    I         what this song is: type, language, songwriters, analysis
    F / F11   fullscreen          Space     play/pause
    [ / ]     this track -/+ 50ms < / >     seek -/+ 5s
    Shift+[ ] the same, by 10ms
    0         clear this track    Shift+0   reset global offset
    Up / Down previous / next line
    N / P     next / prev track   X         resync to audio
    D         background style    L         line alignment
    E         word pop            O         focus mode
    U         sung colour         G / B     glow / depth blur
    A         album art panel     + / -     text size
    C         copy line           Shift+C   copy all
    S         save as .ttml       Shift+S   copy a lyric card
    R         reload lyrics       Shift+R   fix this line's romaji
    Shift+G   fetch a human romanisation from Genius (needs a token, set in M)
    T         always on top       H / ?     this help
    Q / Esc   quit
    click a line to seek to it, drag the progress bar to scrub, scroll to
    browse (it re-centres after a moment), double-click the art to go full.

Everything above persists to ~/.config/spicy-lyrics/gui.json between runs.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import hashlib
import os
import queue
import random
import tempfile
import pathlib
import re
import signal
import subprocess
import functools
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]

import spicy_lyrics as SL  # noqa: E402
import genius_roman as GR  # noqa: E402
import lyric_sources as LS  # noqa: E402
from difflib import SequenceMatcher  # noqa: E402
try:
    from spotify_dom import connect as _connect  # noqa: E402
except ImportError:                                # pragma: no cover
    raise SystemExit(
        "Mild Lyrics: cannot find spotify_dom.py.\n"
        f"Looked in:\n  {_HERE}\n  {_HERE.parent}\n"
        "Copy it next to lyrics_gui.py and run this again."
    )

def connect(port: int, match: str | None = None):
    """spotify_dom.connect, but as a function that fails rather than one that
    ends the process.

    It is written for a command line, where exiting with an explanation is the
    right answer to "Spotify is not listening". Here it is called from poll(),
    four times a second, on the GUI thread -- and SystemExit is a BaseException,
    so `except Exception` around the caller does not stop it. On Linux this
    never showed: MPRIS carries the clock and only the worker thread ever
    connected, where an exit merely ends that thread. Drive the clock over CDP,
    as Windows must, and the first poll takes the whole window down with it.
    """
    try:
        return _connect(port, match)
    except SystemExit as e:
        raise ConnectionError(str(e) or "Spotify's debug port is not answering")


from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, pyqtSignal, QObject  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QFontMetricsF, QImage,
    QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QRegion,
)
from PyQt6.QtWidgets import QApplication, QMenu, QWidget  # noqa: E402

TEXT = QColor(234, 234, 234)
FONT_STACK = ["Outfit", "Inter", "Poppins", "Noto Sans", "Cantarell",
              "Segoe UI Variable Display", "Segoe UI", "SF Pro Display",
              "Helvetica Neue", "DejaVu Sans", "Arial"]
try:
    WGHT_AXIS = QFont.Tag("wght")
    if not hasattr(QFont, "setVariableAxis"):
        WGHT_AXIS = None
except Exception:                                  # pragma: no cover
    WGHT_AXIS = None

MPRIS = "org.mpris.MediaPlayer2.Player"
STALE_HOLD = 2.0
SETTLE = 7.0
RESYNC_NUDGE = 0.25
POLL_MS, POLL_MS_EDGE = 250, 60
POLL_MS_PAUSED = 110
SLEW_MAX, SLEW_TIME = 0.6, 0.35
PIN_EDGE = 1.0

# --- unpause delay --------------------------------------------------------
UNPAUSE_DELAY = 0.25

APP_NAME = "Mild Lyrics"
APP_SLUG = "mild-lyrics"
OLD_SLUG = "spicy-lyrics"

POLL_IDLE = 0.4
POLL_WAITING = 0.12
RETRY_FIRST = 0.3
RETRY_MAX = 2.0


def app_dir(kind: str) -> pathlib.Path:
    """Where this app keeps its settings or its cache, per platform.

    Windows has no XDG anything -- pointing a config file at ~/.config there
    leaves it somewhere no installer, backup or uninstaller will look. Roaming
    for settings, Local for the cache, which is Windows' own division and the
    same one XDG is drawing.
    """
    if os.name == "nt":
        var = "APPDATA" if kind == "config" else "LOCALAPPDATA"
        root = os.environ.get(var)
        if not root:
            root = pathlib.Path.home() / "AppData" / (
                "Roaming" if kind == "config" else "Local")
        return _migrated(pathlib.Path(root))
    var = "XDG_CONFIG_HOME" if kind == "config" else "XDG_CACHE_HOME"
    root = os.environ.get(var) or (
        pathlib.Path.home() / (".config" if kind == "config" else ".cache"))
    return _migrated(pathlib.Path(root))


def _migrated(root: pathlib.Path) -> pathlib.Path:
    """<root>/mild-lyrics, carrying over the old name's contents once."""
    new, old = root / APP_SLUG, root / OLD_SLUG
    try:
        if old.is_dir() and not new.exists():
            old.rename(new)
    except Exception:
        pass
    return new


CONFIG = app_dir("config") / "gui.json"
INDEX = app_dir("cache") / "index.json"
SRC_LABEL = {"spicy": "Spicy Lyrics", "amll": "amll-ttml-db",
             "blend": "QQ+Apple+NetEase", "youly": "YouLy+",
             "netease": "NetEase", "lrclib": "LRCLIB",
             "local": "Aligned here"}
SRC_ATTR = {"spicy": "src_spicy", "amll": "src_amll", "blend": "src_blend",
            "youly": "src_youly", "netease": "src_netease",
            "lrclib": "src_lrclib", "local": "src_local"}
SRC_DEFAULT = ["spicy", "amll", "blend", "youly", "netease", "lrclib", "local"]

DEFAULTS = {
    "offset": 0.0, "font_scale": 1.0, "blur": 1.0, "glow": 1.0, "panel": True,
    "bg": "art", "bg_dim": 0.65, "bg_motion": 1.0, "align": "left", "pop": 1.0,
    "edge": 1.0, "focus": 0, "line_spacing": 1.0, "sung_color": "white",
    "interlude": 4.0, "resync": True, "pop_min": 0.45, "beat": 1.0,
    "auto_time": True, "unpause_delay": UNPAUSE_DELAY,
    "fps_cap": 60.0,
    "roman": "off", "genius_auto": False, "furigana": False,
    "src_spicy": True, "src_amll": True, "src_youly": True,
    "src_netease": True, "src_lrclib": True, "src_local": True,
    "src_blend": False, "ne_graft": True,
    "align_on": True,
    "align_model": "sync", "align_stems": False,
    "align_device": "auto", "align_spare": 1.0,
    "align_free": True,
    "align_ahead": 1,
    "spin": 0.0,
    "zero_g": 0.0, "clouds": 0.0,
    "browse_now": True, "browse_art": True,
    "view_mode": "regular", "volume_bar": True,
    "duet_color": "off", "motion_art": False, "font": "",
    "src_order": ",".join(SRC_DEFAULT),
}
BG_MODES = ["art", "mesh", "solid"]
VIEW_MODES = ["regular", "compact"]
ALIGNMENTS = ["left", "center", "right"]
ROMAN_MODES = ["off", "instead", "under"]
SUNG_MODES = ["white", "album tint"]
DUET_MODES = ["off", "album tint"]
ALIGN_DEVICES = ["auto", "gpu", "cpu"]
def _sync_available() -> bool:
    """Whether the sync package came with this copy.

    It is a separate tree from the app and does not always travel with it --
    a copy shipped to somebody who is only going to time lyrics by hand has
    no reason to carry the trainer. Where it is absent the setting below
    offers whisper alone, rather than a choice that silently does nothing.
    """
    import importlib.util
    try:
        return importlib.util.find_spec("sync") is not None
    except Exception:
        return False


ALIGN_MODELS = ["sync", "whisper"] if _sync_available() else ["whisper"]
SYNC_HOME = app_dir("cache") / "sync"


@functools.lru_cache(maxsize=2)
def _sync_ckpt(stems: bool = False) -> str:
    """The trained model to align with, or "" if none is on disk.

    WHICH MODEL DEPENDS ON WHETHER THE VOCAL IS SEPARATED, and the difference
    is not small. Measured on the seventeen songs gc timed by hand:

                                    mixture audio     separated vocal
      trained on mixtures              0.569s              0.480s
      trained on separated vocals      1.353s              0.317s

    A model trained on stems has never heard a guitar and comes apart on one --
    four of seventeen songs usable against ten. So the pair has to match, and
    picking "the newest checkpoint" would get this right only by luck.

    Among the candidates for a mode, newest step wins, and a checkpoint without
    a boundary head loses to one with it -- it can only guess where a word
    ends. Cached per mode; the answer changes when a training run finishes.
    """
    want = "-stem" if stems else ""
    best, found = None, ""
    for path in sorted(SYNC_HOME.glob("syncnet-w2v*.pt")):
        if path.name.endswith("-lowloss.pt"):
            continue
        made_on_stems = any(k in path.name for k in ("-stem", "-pitch"))
        if made_on_stems != bool(stems):
            continue
        try:
            import torch
            got = torch.load(path, map_location="cpu", weights_only=False)
        except Exception:               # noqa: BLE001
            continue
        has = any(k.startswith("boundary.") for k in got.get("weights", {}))
        rank = (has, int(got.get("step") or 0))
        if best is None or rank > best:
            best, found = rank, str(path)
    return found

MENU_SECTIONS = [
    ("Text", [
        ("Alignment",         "align",        "choice", ALIGNMENTS),
        ("Text size",         "font_scale",   "num",    (0.6, 1.9, 0.05, "{:.2f}")),
        ("Line spacing",      "line_spacing", "num",    (0.6, 2.5, 0.1,  "{:.1f}")),
        ("Focus lines",       "focus",        "num",    (0, 8, 1,        "{:.0f}")),
        ("Sung colour",       "sung_mode",    "choice", SUNG_MODES),
        ("Duet colour",       "duet_color",   "choice", DUET_MODES),
        ("Font",              "font_name",    "text",   None),
    ]),
    ("Motion", [
        ("Word pop",          "pop",          "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Pop only past",     "pop_min",      "num",    (0.0, 2.0, 0.05, "{:.2f}s")),
        ("Fill softness",     "edge",         "num",    (0.0, 4.0, 0.25, "{:.2f}")),
        ("Glow",              "glow_scale",   "num",    (0.0, 2.0, 0.1,  "{:.1f}")),
        ("Depth blur",        "blur_scale",   "num",    (0.0, 2.0, 0.1,  "{:.1f}")),
        ("Beat response",     "beat_scale",   "num",    (0.0, 3.0, 0.25, "{:.2f}")),
    ]),
    ("Background", [
        ("Background",        "bg_mode",      "choice", BG_MODES),
        ("Background dim",    "bg_dim",       "num",    (0.0, 1.0, 0.05, "{:.2f}")),
        ("Background motion", "bg_motion",    "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("View mode",         "view_mode",    "choice", VIEW_MODES),
        ("Album art panel",   "show_panel",   "bool",   None),
        ("Volume slider",     "show_volume",  "bool",   None),
        ("Animated cover",    "motion_art",   "bool",   None),
    ]),
    ("Romanisation", [
        ("Romanisation",      "roman",        "choice", ROMAN_MODES),
        ("Furigana",          "furigana",     "bool",   None),
        ("Use Genius",        "genius_auto",  "bool",   None),
        ("Genius token",      "genius_token", "secret", None),
    ]),
    ("Timing", [
        ("Interlude gap",     "interlude",    "num",    (0.0, 12.0, 0.5, "{:.1f}s")),
        ("Timing offset",     "offset",       "num",    (-2.0, 2.0, 0.05, "{:+.2f}s")),
        ("Auto timing",       "auto_time",    "bool",   None),
        ("Unpause delay",     "unpause_delay", "num",   (0.0, 1.0, 0.05, "{:.2f}s")),
        ("Auto resync",       "resync",       "bool",   None),
        ("Local aligning",    "align_on",     "bool",   None),
        ("Timing model",      "align_model",  "choice", ALIGN_MODELS),
        ("Isolate vocals",    "align_stems",  "bool",   None),
        ("Align device",      "align_device", "choice", ALIGN_DEVICES),
        ("Keep VRAM free",    "align_spare",  "num",    (0.25, 4.0, 0.25, "{:.2f} GB")),
        ("Free models after", "align_free",   "bool",   None),
        ("Align ahead",       "align_ahead",  "num",    (0, 7, 1, "{:.0f} tracks")),
        ("NetEase word sync", "ne_graft",     "bool",   None),
    ]),
    ("Sources", [
        ("", f"src_slot{i}", "bool", None) for i in range(len(SRC_DEFAULT))
    ]),
    ("Browse", [
        ("Now playing card",  "show_now_card", "bool",   None),
        ("Album art",         "browse_art",    "bool",   None),
        ("Fill song names",   "start_backfill", "action", None),
    ]),
    ("Troll", [
        ("Word spin",         "spin",         "num",    (0.0, 4.0, 0.25, "{:.2f}")),
        ("No gravity",        "zero_g",       "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Clouds",            "clouds",       "num",    (0.0, 3.0, 0.25, "{:.2f}")),
    ]),
]


def _storage_rows() -> list:
    """One row per cache, plus the two that act on all of them.

    Built from caches.entries() rather than written out here, so a cache
    added later cannot end up with no way to clear it. The training caches
    are left out: they belong to whoever ran the training, are measured in
    tens of gigabytes, and the command line is the right place for them.
    """
    try:
        import caches
    except Exception:                                    # noqa: BLE001
        return []
    rows = [(f"Clear {r['label'].lower()}", "clear_cache", "action", r["key"])
            for r in caches.entries() if not r.get("training")]
    rows.append(("Clear all caches", "clear_cache", "action", "*"))
    rows.append(("Forget credentials", "forget_creds", "action", None))
    return rows


MENU_SECTIONS.append(("Storage", _storage_rows()))

MENU = [row for _, rows in MENU_SECTIONS for row in rows]
MENU_SPANS = []
_at = 0
for _name, _rows in MENU_SECTIONS:
    MENU_SPANS.append((_at, len(_rows)))
    _at += len(_rows)

HELP_KEYS = [
    ("M", "settings menu"),             ("/", "search all lyrics"),
    ("I", "song info"),                 ("F / F11", "fullscreen"),
    ("Space", "play / pause"),          ("< / >", "seek -/+ 5s"),
    ("Up / Down", "previous / next line"), ("[ / ]", "offset -/+ 50ms"),
    ("Shift+[ / ]", "offset -/+ 10ms"),
    ("0 / Shift+0", "clear track / global offset"),
    ("N / P", "next / previous track"),
    ("X", "resync to audio"),           ("D", "background style"),
    ("L", "line alignment"),            ("E", "word pop"),
    ("O", "focus mode"),                ("U", "sung colour"),
    ("G / B", "glow / depth blur"),     ("A", "album art panel"),
    ("+ / -", "text size"),             ("C / Shift+C", "copy line / all"),
    ("S / Shift+S", "save .ttml / card"), ("R", "reload lyrics"),
    ("Shift+R", "fix this line's romaji"),
    ("Shift+G", "romaji from Genius"),
    ("Shift+A", "align to the audio"),
    ("T", "always on top"),             ("click", "seek to a line"),
    ("drag bar", "scrub"),              ("H / ?", "close this help"),
    ("Home", "browse, search & queue"),
    ("Q / Esc", "quit"),
]


LYRIC_SUFFIXES = (".ttml", ".xml", ".lrc", ".elrc")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".avif")


def _droppable(url) -> str:
    """"lyric", "image" or "" for a dropped URL."""
    path = url.toLocalFile()
    if not path:
        return ""
    end = pathlib.Path(path).suffix.lower()
    if end in LYRIC_SUFFIXES:
        return "lyric"
    return "image" if end in IMAGE_SUFFIXES else ""


def palette_of(img: QImage, want: int = 4) -> list[QColor]:
    """Dominant colours, coarse-histogram style.

    A single averaged pixel (what the accent glow used to be) turns any cover
    with more than one hue into the same brown-grey, so bucket by hue/sat/value
    instead and keep the biggest clusters. Near-black and near-grey pixels are
    dropped: they carry no colour and would swamp the histogram on dark art.
    """
    small = img.scaled(48, 48, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    buckets: dict[tuple, list] = {}
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            h, s, v, _ = c.getHsv()
            if v < 45 or s < 35:
                continue
            key = (h // 24, s // 72, v // 72)
            b = buckets.setdefault(key, [0, 0, 0, 0])
            b[0] += c.red(); b[1] += c.green(); b[2] += c.blue(); b[3] += 1
    out: list[QColor] = []
    for r, g, bl, n in sorted(buckets.values(), key=lambda b: -b[3]):
        if len(out) >= want:
            break
        h, s, v, _ = QColor(r // n, g // n, bl // n).getHsv()
        if any(min(abs(h - o.hue()), 360 - abs(h - o.hue())) < 18 for o in out):
            continue
        out.append(QColor.fromHsv(h, min(255, int(s * 1.35)), max(70, min(205, v))))
    if not out:
        one = img.scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        c = QColor(one.pixel(0, 0))
        h, s, v, _ = c.getHsv()
        out = [QColor.fromHsv(h, min(255, int(s * 1.25)), max(60, min(135, v)))]
    return out


def parse_color(spec: str, fallback: QColor) -> QColor | None:
    """None means 'derive it from the album palette at paint time'."""
    if not spec or spec == "auto":
        return None
    c = QColor(spec)
    return c if c.isValid() else fallback


def soft_scale(pm: QPixmap, factor: float) -> QPixmap:
    """Blur a pixmap by shrinking and regrowing it through a mip chain.

    Collapsing straight to 1/10th and stretching back in one step is a bilinear
    upscale of a tiny image, which reads as blocky pixels rather than blur.
    Halving and doubling repeatedly keeps every step near 2:1, where smooth
    scaling actually behaves, and lands on something genuinely soft.
    """
    w, h = pm.width(), pm.height()
    tw, th = max(1, int(w / factor)), max(1, int(h / factor))
    ig, sm = Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    small = pm
    while small.width() // 2 > tw and small.height() // 2 > th:
        small = small.scaled(small.width() // 2, small.height() // 2, ig, sm)
    small = small.scaled(tw, th, ig, sm)
    while small.width() * 2 < w and small.height() * 2 < h:
        small = small.scaled(small.width() * 2, small.height() * 2, ig, sm)
    return small.scaled(w, h, ig, sm)


def split_to_fit(piece: tuple, fm: QFontMetricsF, width: float) -> list[tuple]:
    """Break one timed fragment into chunks that each fit the column.

    Japanese and Chinese lines carry no spaces, so the whole line arrives as a
    single unbreakable token and used to run straight off the right edge. Split
    it per character and interpolate the timings across the pieces.
    """
    s, e, txt, part = piece
    if len(txt) < 2 or fm.horizontalAdvance(txt) <= width:
        return [piece]
    chunks, cur = [], ""
    for ch in txt:
        if cur and fm.horizontalAdvance(cur + ch) > width:
            chunks.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        chunks.append(cur)
    if len(chunks) < 2:
        return [piece]
    timed = isinstance(s, (int, float)) and isinstance(e, (int, float)) and e > s
    out, t, total = [], s, len(txt)
    for i, c in enumerate(chunks):
        last = i == len(chunks) - 1
        end = e if last or not timed else t + (e - s) * len(c) / total
        out.append((t, end, c, part if last else True))
        t = end
    return out


def SL_norm(t: str) -> str:
    return re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]", "", (t or "").lower())


def track_id(meta) -> str | None:
    found = re.search(r"([A-Za-z0-9]{22})", str((meta or {}).get("mpris:trackid", "")))
    return found.group(1) if found else None


def _read_config() -> dict:
    """Settings, falling back to the previous generation if the live file is
    gone or unreadable."""
    for path in (CONFIG, CONFIG.with_suffix(".json.bak")):
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                return got
        except Exception:
            continue
    return {}


HAND_FIX_MAX = 3


def load_romaji() -> dict:
    """Per-track romaji corrections, keyed by the original line text so a
    repeated line is fixed everywhere it appears.

    Genius alignments used to land in here too, which made them permanent: a
    track fixed up by an early version of the matcher kept that version's
    mistakes forever. They live in their own store now, so anything here that
    is plainly a whole-song alignment is dropped and re-fetched rather than
    treated as your own work.
    """
    got = _read_config().get("romaji") or {}
    return {t: dict(v) for t, v in got.items()
            if isinstance(v, dict) and len(v) <= HAND_FIX_MAX}


def load_genius() -> tuple[dict, dict]:
    """Cached Genius alignments, and the matcher revision each was made with.

    Kept apart from the hand-typed corrections above because these are derived
    and therefore disposable: when the matcher improves, anything from an older
    revision is dropped so the next play re-fetches it. Everything the older
    code got wrong stayed on screen otherwise, since a track that already had
    an entry was never looked up again.
    """
    cfg = _read_config()
    got = cfg.get("genius") or {}
    revs = cfg.get("genius_rev") or {}
    out, keep = {}, {}
    for t, v in got.items():
        if not isinstance(v, dict):
            continue
        try:
            rev = int(revs.get(t, 0))
        except Exception:
            rev = 0
        if rev == GR.REVISION:
            out[t], keep[t] = dict(v), rev
    return out, keep


def load_token() -> str:
    """The Genius token lives in the settings file but never on the command
    line, where it would sit in shell history and the process list."""
    return str(_read_config().get("genius_token") or "")


def load_offsets() -> dict:
    """Per-track corrections, undoing a rebase a previous version applied.

    That version measured how far the player's clock ran ahead of its own audio
    and subtracted it centrally. Corrections made by ear already contained that
    lead, so it took the same amount back off each stored one to stop them being
    counted twice, and wrote the figure to `lag`.

    Nothing subtracts it centrally any more, so those corrections are short by
    exactly that much and adding it back restores them. This applies to every
    entry, including any tuned while the rebase was in force -- those were
    settled against a clock already holding the lead back, so they need the same
    correction to mean the same thing now.

    One-shot: `lag` is no longer written, so the next save drops it and this
    stops firing. Re-running it before that save is harmless, because it reads
    the stored figures fresh each time rather than compounding.
    """
    cfg = _read_config()
    try:
        got = {k: float(v) for k, v in (cfg.get("offsets") or {}).items()}
    except Exception:
        return {}
    try:
        lag = float(cfg.get("lag") or 0.0)
    except Exception:
        lag = 0.0
    return {k: round(v + lag, 3) for k, v in got.items()} if lag else got


def load_est() -> dict:
    """Measured timing offsets, dropped when the estimator that made them moves on.

    Same bargain as the Genius alignments above and for the same reason: these
    are derived, so a track measured once by an older revision would otherwise
    keep that revision's answer forever and never be looked at again. Anything
    stamped with a different revision is discarded and re-measured on the next
    play. The hand corrections in `offsets` are never touched by this -- those
    are the user's own work and outrank anything computed here.
    """
    out = {}
    for tid, got in (_read_config().get("est") or {}).items():
        try:
            if isinstance(got, dict) and int(got.get("rev", 0)) == EST_REVISION:
                out[tid] = {"delta": float(got["delta"]), "conf": float(got["conf"]),
                            "n": int(got.get("n", 0)), "rev": EST_REVISION}
        except Exception:
            continue
    return out


def load_settings() -> dict:
    got = _read_config()
    return {k: got[k] for k in DEFAULTS if k in got}


def save_settings(values: dict, offsets: dict | None = None,
                  romaji: dict | None = None, token: str | None = None,
                  genius: dict | None = None, genius_rev: dict | None = None,
                  est: dict | None = None) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if offsets is not None:
            values = dict(values, offsets={k: v for k, v in offsets.items() if v})
        if est is not None:
            values = dict(values, est=est)
        if romaji is not None:
            values = dict(values, romaji={k: v for k, v in romaji.items() if v})
        if genius is not None:
            values = dict(values, genius={k: v for k, v in genius.items() if v})
        if genius_rev is not None:
            values = dict(values, genius_rev=dict(genius_rev))
        if token is not None:
            values = dict(values, genius_token=token)
        if CONFIG.exists():
            try:
                CONFIG.replace(CONFIG.with_suffix(".json.bak"))
            except Exception:
                pass
        CONFIG.write_text(json.dumps(values, indent=2), encoding="utf-8")
    except Exception:
        pass


_kwin_seq = 0


def kwin_keep_above(title: str, on: bool) -> bool:
    """Ask KWin to keep our window above the rest. True if it took.

    Wayland deliberately refuses to let a client set its own stacking, so
    Qt::WindowStaysOnTopHint is silently ignored there -- the window flag is
    set, nothing happens, and the app used to report success anyway. The
    compositor will do it if asked directly, and on KWin that means loading a
    one-shot script over D-Bus. Nothing here is fatal: if any of it is missing
    we say so and the caller tells the truth instead.
    """
    global _kwin_seq
    try:
        import dbus
    except ImportError:
        return False
    js = """
var list = (workspace.windowList ? workspace.windowList() : workspace.clientList());
for (var i = 0; i < list.length; i++) {
    if (String(list[i].caption || "") === %s) list[i].keepAbove = %s;
}
""" % (json.dumps(title), "true" if on else "false")
    try:
        path = pathlib.Path(tempfile.gettempdir()) / f"spicy-keepabove-{os.getpid()}.js"
        path.write_text(js, encoding="utf-8")
        bus = dbus.SessionBus()
        obj = bus.get_object("org.kde.KWin", "/Scripting")
        iface = dbus.Interface(obj, "org.kde.kwin.Scripting")
        _kwin_seq += 1
        iface.loadScript(str(path), f"spicy-keepabove-{os.getpid()}-{_kwin_seq}",
                         signature="ss")
        iface.start()
        return True
    except Exception:
        return False


def _smooth(t: float) -> float:
    """Ease in and out, so a cloud leaves and arrives without a visible
    start or stop -- a linear ramp reads as a slide, a cubic as a snap."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def wrap_rows(fm: QFontMetricsF, text: str, width: float, maxrows: int = 2,
              elide: bool = True) -> list[str]:
    """Greedy word wrap. Overflow piles onto the last row, which is then elided.

    `elide=False` leaves that row over-long on purpose, for a caller that would
    rather scroll it than cut it. A still image has no such option, so the share
    card keeps the ellipsis.
    """
    rows, cur = [], ""
    for w in text.split():
        joined = f"{cur} {w}".strip()
        if cur and fm.horizontalAdvance(joined) > width:
            if len(rows) + 1 == maxrows:
                cur = joined
            else:
                rows.append(cur)
                cur = w
        else:
            cur = joined
    if cur:
        rows.append(cur)
    if elide and rows and fm.horizontalAdvance(rows[-1]) > width:
        rows[-1] = fm.elidedText(rows[-1], Qt.TextElideMode.ElideRight, width)
    return rows[:maxrows] or [""]


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
class MprisTransport:
    """Spotify over the session bus. Linux and the other freedesktop platforms."""

    name = "MPRIS"

    def __init__(self) -> None:
        self._props = None
        self._player = None

    @staticmethod
    def usable() -> bool:
        try:
            import dbus
        except ImportError:
            return False
        try:
            dbus.SessionBus().get_object(
                "org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2")
            return True
        except Exception:
            return False

    def _ifaces(self):
        """Cached proxies -- poll() runs 4x/second and re-resolving the bus
        object each time is pure D-Bus round-trip for no gain."""
        import dbus

        if self._props is None:
            obj = dbus.SessionBus().get_object(
                "org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2"
            )
            self._props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            self._player = dbus.Interface(obj, MPRIS)
        return dbus, self._props, self._player

    def drop(self) -> None:
        self._props = self._player = None

    def read(self, want_volume: bool) -> dict:
        _, props, _ = self._ifaces()
        m = props.Get(MPRIS, "Metadata")
        pos = float(props.Get(MPRIS, "Position")) / 1e6
        at = time.monotonic()
        status = str(props.Get(MPRIS, "PlaybackStatus"))
        vol = None
        if want_volume:
            try:
                vol = float(props.Get(MPRIS, "Volume"))
            except Exception:
                vol = None
        tid = track_id(m)
        again = props.Get(MPRIS, "Metadata")
        if track_id(again) != tid:
            m, tid = again, track_id(again)
            pos = float(props.Get(MPRIS, "Position")) / 1e6
            at = time.monotonic()
        return {
            "tid": tid, "status": status, "pos": pos, "at": at, "volume": vol,
            "meta": {
                "title": str(m.get("xesam:title", "")),
                "artist": ", ".join(str(x) for x in m.get("xesam:artist", []) or []),
                "album": str(m.get("xesam:album", "")),
                "art": str(m.get("mpris:artUrl", "")),
                "length": float(m.get("mpris:length", 0) or 0) / 1e6,
            },
        }

    def seek(self, seconds: float) -> None:
        dbus, props, player = self._ifaces()
        trackid = props.Get(MPRIS, "Metadata")["mpris:trackid"]
        player.SetPosition(trackid, dbus.Int64(int(max(0.0, seconds) * 1e6)))

    def set_volume(self, v: float) -> None:
        dbus, props, _ = self._ifaces()
        props.Set(MPRIS, "Volume", dbus.Double(v))

    def command(self, name: str) -> None:
        _, _, player = self._ifaces()
        getattr(player, name)()


JS_STATE = """(() => {
  const P = Spicetify && Spicetify.Player;
  if (!P) return null;
  const d = P.data || {};
  const it = d.item || d.track || {};
  const al = it.album || {};
  const imgs = al.images || [];
  return {
    uri: it.uri || "",
    title: it.name || "",
    artist: (it.artists || []).map(a => a && a.name).filter(Boolean).join(", "),
    album: al.name || "",
    art: (imgs[imgs.length - 1] || {}).url || (imgs[0] || {}).url || "",
    length: ((it.duration || {}).milliseconds
             || (it.duration || {}).totalMilliseconds || 0) / 1000,
    pos: (P.getProgress ? P.getProgress() : 0) / 1000,
    playing: P.isPlaying ? !!P.isPlaying() : false,
    volume: P.getVolume ? P.getVolume() : null};
})()"""


class CdpTransport:
    """Spotify over its own debug port -- the same connection the rest of the
    app already uses. Works anywhere Spotify runs, and is the only way in on
    Windows, which has no session bus to ask."""

    name = "Spicetify"

    def __init__(self, port: int) -> None:
        self.port = port
        self.cdp = None

    def usable(self) -> bool:
        try:
            self._conn()
            return True
        except Exception:
            return False

    def _conn(self):
        if self.cdp is None:
            self.cdp = connect(self.port)
        return self.cdp

    def drop(self) -> None:
        try:
            if self.cdp:
                self.cdp.close()
        except Exception:
            pass
        self.cdp = None

    def read(self, want_volume: bool) -> dict:
        got = self._conn().evaluate(JS_STATE)
        if not isinstance(got, dict) or not got.get("uri"):
            raise RuntimeError("no player state")
        vol = got.get("volume") if want_volume else None
        return {
            "tid": (got.get("uri") or "").split(":")[-1] or None,
            "status": "Playing" if got.get("playing") else "Paused",
            "pos": float(got.get("pos") or 0.0),
            "at": time.monotonic(),
            "volume": None if vol is None else float(vol),
            "meta": {
                "title": got.get("title") or "",
                "artist": got.get("artist") or "",
                "album": got.get("album") or "",
                "art": art_url(got.get("art") or ""),
                "length": float(got.get("length") or 0.0),
            },
        }

    def seek(self, seconds: float) -> None:
        self._conn().evaluate(f"Spicetify.Player.seek({int(max(0.0, seconds) * 1000)})")

    def set_volume(self, v: float) -> None:
        self._conn().evaluate(f"Spicetify.Player.setVolume({max(0.0, min(1.0, v))})")

    def command(self, name: str) -> None:
        js = {"PlayPause": "togglePlay", "Next": "next", "Previous": "back"}.get(name)
        if js:
            self._conn().evaluate(f"Spicetify.Player.{js}()")


class SmtcTransport:
    """Windows' own now-playing service.

    Windows has had a system media transport since 8 -- the thing that draws
    the little now-playing card on the volume flyout -- and Spotify feeds it
    like every other player. It is the true equivalent of MPRIS, and unlike the
    debug port it needs nothing configured: no launch flag, no Spicetify, and it
    works with the Microsoft Store build, which cannot be given a flag at all.

    Two things it does not carry. There is no volume in the protocol, so the
    slider stays hidden. And there is no Spotify track id -- only the words on
    the card -- so one is made up from the title and artist, which is stable for
    a song and is all the name-searching providers need. Spicy Lyrics' own cache
    is keyed by the real id and is read over CDP, so it is unavailable here;
    the network providers carry the lyrics instead.
    """

    name = "Windows media"

    def __init__(self) -> None:
        self._mgr = None

    @staticmethod
    def _mod():
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as M)
            return M
        except ImportError:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as M)
            return M

    @staticmethod
    def usable() -> bool:
        if os.name != "nt":
            return False
        try:
            SmtcTransport._mod()
            return True
        except Exception:
            return False

    def drop(self) -> None:
        self._mgr = None

    def _session(self):
        import asyncio

        if self._mgr is None:
            self._mgr = asyncio.run(self._mod().request_async())
        for s in self._mgr.get_sessions():
            if "spotify" in (s.source_app_user_model_id or "").lower():
                return s
        return self._mgr.get_current_session()

    def read(self, want_volume: bool) -> dict:
        import asyncio

        s = self._session()
        if s is None:
            raise RuntimeError("nothing is playing that Windows knows about")
        info = asyncio.run(s.try_get_media_properties_async())
        tl, pb = s.get_timeline_properties(), s.get_playback_info()
        title = info.title or ""
        artist = info.artist or ""
        playing = int(getattr(pb.playback_status, "value", pb.playback_status)) == 4
        secs = lambda d: (d.total_seconds() if hasattr(d, "total_seconds")
                          else float(d) / 1e7)
        key = hashlib.sha1(f"{title} {artist}".encode("utf-8")).hexdigest()[:22]
        return {
            "tid": key if title else None,
            "status": "Playing" if playing else "Paused",
            "pos": max(0.0, secs(tl.position)),
            "at": time.monotonic(),
            "volume": None,
            "meta": {
                "title": title, "artist": artist,
                "album": info.album_title or "",
                "art": "",
                "length": max(0.0, secs(tl.end_time)),
            },
        }

    def seek(self, seconds: float) -> None:
        import asyncio

        s = self._session()
        if s is not None:
            asyncio.run(s.try_change_playback_position_async(
                int(max(0.0, seconds) * 1e7)))

    def set_volume(self, v: float) -> None:
        raise NotImplementedError("Windows' media transport carries no volume")

    def command(self, name: str) -> None:
        import asyncio

        s = self._session()
        if s is None:
            return
        call = {"PlayPause": s.try_toggle_play_pause_async,
                "Next": s.try_skip_next_async,
                "Previous": s.try_skip_previous_async}.get(name)
        if call:
            asyncio.run(call())


class BackupTransport:
    """Primary, with a stand-in for while the primary is down.

    SMTC answers over a COM call per read and is noticeably slower than either
    the debug port or the bus, so it should not be what drives the clock merely
    because Spotify happened to start second. This keeps asking the primary --
    at a sensible interval, not four times a second at a dead port -- and hands
    back over the moment it answers. The stand-in is what you get in between,
    rather than nothing.
    """

    RETRY = 5.0

    def __init__(self, primary, backup) -> None:
        self.primary, self.backup = primary, backup
        self.on_backup = False
        self._next_try = 0.0

    @property
    def name(self) -> str:
        return self.backup.name if self.on_backup else self.primary.name

    def drop(self) -> None:
        (self.backup if self.on_backup else self.primary).drop()

    def _io(self, call: str, *a):
        now = time.monotonic()
        if not self.on_backup or now >= self._next_try:
            try:
                out = getattr(self.primary, call)(*a)
                self.on_backup = False
                return out
            except Exception:
                self.primary.drop()
                self.on_backup = True
                self._next_try = now + self.RETRY
        return getattr(self.backup, call)(*a)

    def read(self, want_volume: bool):
        return self._io("read", want_volume)

    def seek(self, seconds: float) -> None:
        self._io("seek", seconds)

    def set_volume(self, v: float) -> None:
        self._io("set_volume", v)

    def command(self, name: str) -> None:
        self._io("command", name)


def make_transport(port: int, prefer: str = "auto"):
    """Whichever way in is actually available here.

    Order on Windows is deliberate: the debug port first, because it is quick
    and because it is the one that also brings Spicy Lyrics, the browser and the
    queue with it. Windows' own transport sits behind it as a stand-in, for the
    stretches when the port is not answering.
    """
    if prefer == "smtc":
        return SmtcTransport()
    if prefer == "mpris":
        return MprisTransport()
    if prefer == "cdp":
        return CdpTransport(port)
    if os.name != "nt" and MprisTransport.usable():
        return MprisTransport()
    cdp = CdpTransport(port)
    if os.name == "nt" and SmtcTransport.usable():
        return BackupTransport(cdp, SmtcTransport())
    return cdp


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
class Clock:
    def __init__(self, transport=None) -> None:
        self.io = transport if transport is not None else MprisTransport()
        self.tid: str | None = None
        self.status = "Paused"
        self._pos = 0.0
        self._raw = 0.0
        self._at = time.monotonic()
        self.meta: dict = {}
        self._pos_tid: str | None = None
        self._slew = 0.0
        self._slew_at = 0.0
        self._pinned: str | None = None
        self.volume: float | None = None
        self._vol_set_at = 0.0
        self.unpause_delay = UNPAUSE_DELAY
        self._delay = 0.0

    def _drop(self) -> None:
        self.io.drop()

    def poll(self, pin_pause: bool = True) -> None:
        try:
            was_playing = self.status == "Playing"
            held = self._raw
            want_vol = time.monotonic() - self._vol_set_at > 1.0
            got = self.io.read(want_vol)
            tid, status = got["tid"], got["status"]
            pos, at = got["pos"], got["at"]
            if want_vol:
                self.volume = got.get("volume")
            self.tid, self.status = tid, status
            self.meta = got["meta"]
            resumed = status == "Playing" and not was_playing
            if resumed:
                self._delay = max(0.0, self.unpause_delay)
            elif status != "Playing":
                self._delay = 0.0
            stale = (not resumed and status == "Playing" and tid == self._pos_tid
                     and pos == self._raw and at - self._at < STALE_HOLD)
            if not stale:
                held_back = pos - self._delay
                if tid == self._pos_tid and status == "Playing" and self._at:
                    shown = self._pos + (at - self._at) if was_playing else self._pos
                    d = held_back - shown
                    if 0.0 < abs(d) <= SLEW_MAX:
                        self._slew, self._slew_at = -d, at
                self._pos, self._at, self._pos_tid = held_back, at, tid
                self._raw = pos
            if status == "Playing" or tid != self._pinned:
                self._pinned = None
            if (pin_pause and not self._pinned and status == "Paused"
                    and not was_playing and tid and pos == held):
                self._pinned = tid
                self._pin(pos)
        except Exception as e:
            self._drop()
            self.status = "Error"
            self.last_error = str(e) or e.__class__.__name__

    def position(self) -> float:
        if self.status != "Playing":
            return self._pos
        now = time.monotonic()
        pos = self._pos + (now - self._at)
        if self._slew:
            k = 1.0 - (now - self._slew_at) / SLEW_TIME
            if k <= 0.0:
                self._slew = 0.0
            else:
                pos += self._slew * k
        length = self.meta.get("length", 0.0)
        return min(pos, length) if length else pos

    def _pin(self, pos: float) -> None:
        """Ask the paused player to go where it already says it is.

        Silent, because nothing is playing: the position does not move, the
        progress bar does not move, and there is no audio to interrupt. What it
        does move is the player's idea of where its own audio is -- see SLEW_MAX
        above for how far that has drifted by the time it stops, and what it
        costs the rest of the song not to put it right.

        Failure is nothing to report. This corrects a fifth of a second on a
        track that is not playing; a player that will not take the seek simply
        keeps the sync it would have had anyway.
        """
        length = self.meta.get("length", 0.0)
        if pos < PIN_EDGE or (length and pos > length - PIN_EDGE):
            return
        try:
            self.io.seek(pos)
        except Exception:
            self._drop()

    def seek(self, seconds: float, keep_hold: bool = False) -> None:
        """Send the player somewhere. `keep_hold` leaves the output hold alone.

        A seek asked for by hand drops the hold: clicking a line asks for that
        line's own timestamp, the anchor is that timestamp exactly, and
        adjusting a seek target by a correction was what put the song too far
        in.

        A resync is not that. Nothing stopped, nobody asked to go anywhere, and
        the sound carries straight on -- the seek is this program correcting
        itself, and dropping the hold across it left a track that handed over
        running earlier than the same track skipped to, for no reason anyone
        listening could name. Measured against the sink's own output: after a
        resync lands, the player's clock reads 0.054-0.058s AHEAD of the audio
        coming out (two hand-offs, each steady to a millisecond over half a
        minute), which is the same 0.045s the clock sits ahead in any flushed
        state. That is exactly what the hold is for, so the hold stays.
        """
        self._slew = 0.0
        try:
            self.io.seek(seconds)
            self._pos = self._raw = max(0.0, seconds)
            self._at = time.monotonic()
            if not keep_hold:
                self._delay = 0.0
        except Exception:
            self._drop()

    def set_volume(self, v: float) -> None:
        v = max(0.0, min(1.0, v))
        try:
            self.io.set_volume(v)
            self.volume, self._vol_set_at = v, time.monotonic()
        except Exception:
            self._drop()

    def resync(self) -> None:
        """Seek to where we already are. Spotify's audio output can lag its own
        clock after a gapless hand-off, which shows up as lyrics running early;
        a seek flushes the pipeline and realigns them. This is the manual
        workaround (nudge the scrubber) done automatically.

        The position is re-read from the player rather than taken from
        position(), which is an interpolation from the last poll plus whatever
        slew is still easing out. Seeking to an estimate does not correct a
        drift -- it writes the estimate into the player and makes it true, which
        is how a resync could leave the timing worse than it found it.
        """
        if self.status != "Playing":
            return
        try:
            fresh = float(self.io.read(False).get("pos") or 0.0)
        except Exception:
            self._drop()
            return
        self.seek(max(0.0, fresh - RESYNC_NUDGE), keep_hold=True)
        self._pos_tid = None

    def command(self, name: str) -> None:
        """PlayPause / Next / Previous."""
        try:
            self.io.command(name)
        except Exception:
            self._drop()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
class LyricIndex:
    """Every cached song's lines, so you can find one by any phrase in it.

    Spicy Lyrics keeps well over a thousand songs; pulling them is one batched
    pass over Cache Storage (~5s) and the result is small enough to keep on disk.
    """

    V = 2

    def __init__(self) -> None:
        self.songs: list[dict] = []
        self.stale = False
        self.by_id: dict[str, dict] = {}
        self.built = 0.0
        self.dirty = False

    def load(self) -> bool:
        try:
            d = json.loads(INDEX.read_text(encoding="utf-8"))
            self.songs = d["songs"]
            self.by_id = {s["id"]: s for s in self.songs}
            self.built = d.get("built", 0.0)
            self.stale = int(d.get("v", 1)) < self.V
            return bool(self.songs)
        except Exception:
            return False

    def save(self) -> None:
        try:
            INDEX.parent.mkdir(parents=True, exist_ok=True)
            INDEX.write_text(
                json.dumps({"built": self.built, "v": self.V, "songs": self.songs}),
                encoding="utf-8")
            self.dirty = False
        except Exception:
            pass

    def note_title(self, tid: str, title: str, artist: str) -> None:
        """Whatever plays teaches the index its own name, for free. Flagged
        dirty rather than written: save() is 5MB and this runs on the GUI
        thread at every track change."""
        if not tid or not title:
            return
        s = self.by_id.get(tid)
        if s is not None and (s.get("title") != title or s.get("artist") != artist):
            s["title"], s["artist"] = title, artist
            self.dirty = True

    def search(self, query: str, current: str | None, limit: int = 40) -> list[dict]:
        q = query.strip().lower()
        if len(q) < 2:
            return []
        hits = []
        for s in self.songs:
            if q in (s.get("title", "") + " " + s.get("artist", "")).lower():
                hits.append({"id": s["id"], "line": (s["lines"] or [""])[0], "idx": 0,
                             "title": s.get("title", ""), "artist": s.get("artist", ""),
                             "next": "", "here": s["id"] == current, "why": "name"})
                continue
            for i, text in enumerate(s["lines"]):
                if q in text.lower():
                    hits.append({"id": s["id"], "line": text, "idx": i,
                                 "title": s.get("title", ""), "artist": s.get("artist", ""),
                                 "next": s["lines"][i + 1] if i + 1 < len(s["lines"]) else "",
                                 "here": s["id"] == current, "why": "line"})
                    break
            if len(hits) >= limit * 3:
                break
        hits.sort(key=lambda h: (not h["here"], not h["title"]))
        return hits[:limit]


class Beat:
    """Spotify's own analysis of the playing track.

    Spicetify hands over the same beat/bar/section/segment breakdown the web
    player uses, so the visuals can land on the beat without ever touching audio.

    The metrical grid drives the pulse; `pitch` and `timbre` are a coarse
    spectral summary of the track that nothing reads yet, kept because they
    arrive in the same round trip and are the only description of the actual
    sound available anywhere in this program.
    """

    JS = "Spicetify.getAudioData(%s).then(d => ({" \
         "dur: d.track.duration, tempo: d.track.tempo," \
         "beats: d.beats.map(b => [b.start, b.confidence])," \
         "sections: d.sections.map(s => s.start)," \
         "tatums: (d.tatums || []).map(t => t.start)," \
         "segs: d.segments.map(s => [s.start, s.loudness_max])," \
         "pitch: d.segments.map(s => (s.pitches || [])" \
         ".map(v => +(+v || 0).toFixed(3)))," \
         "timbre: d.segments.map(s => (s.timbre || [])" \
         ".map(v => +(+v || 0).toFixed(1)))}))"

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.tempo = 0.0
        self.beats: list[tuple[float, float]] = []
        self.starts: list[float] = []
        self.sections: list[float] = []
        self.tatums: list[float] = []
        self.segs: list[tuple[float, float]] = []
        self.seg_starts: list[float] = []
        self.pitch: list[list[float]] = []
        self.timbre: list[list[float]] = []
        self.lo = self.hi = 0.0

    def load(self, data: dict, length: float) -> bool:
        """A bogus uri makes getAudioData quietly return the CURRENT track's
        analysis, so refuse anything whose duration does not match the track we
        are actually playing -- otherwise the whole song pulses to the wrong beat."""
        if not data or not data.get("beats"):
            return False
        if length and abs(float(data.get("dur", 0)) - length) > 2.0:
            return False
        self.clear()
        self.tempo = float(data.get("tempo") or 0)
        self.beats = [(float(s), float(c)) for s, c in data["beats"]]
        self.starts = [b[0] for b in self.beats]
        self.sections = [float(s) for s in data.get("sections") or []]
        self.tatums = [float(t) for t in data.get("tatums") or []]
        self.segs = [(float(s), float(l)) for s, l in data.get("segs") or []]
        self.seg_starts = [s[0] for s in self.segs]
        for name in ("pitch", "timbre"):
            rows = data.get(name) or []
            setattr(self, name,
                    [[float(v) for v in row] for row in rows]
                    if len(rows) == len(self.segs) else [])
        louds = [l for _, l in self.segs]
        self.lo, self.hi = (min(louds), max(louds)) if louds else (0.0, 0.0)
        self.beats = [
            (s, (0.45 + 0.55 * c) * (0.35 + 0.65 * self.loudness(s)))
            for s, c in self.beats
        ]
        return True

    def seg_at(self, pos: float) -> int:
        """Which segment is sounding at `pos`, or -1 with nothing to say.

        The index into `segs`, `pitch` and `timbre` alike -- all three are cut
        the same way, which is the only reason the spectral rows are worth
        keeping in this shape.
        """
        if not self.seg_starts:
            return -1
        return max(0, bisect.bisect_right(self.seg_starts, pos) - 1)

    def loudness(self, pos: float) -> float:
        """Segment loudness at `pos`, normalised over this track's own range, so
        a quiet song still reacts instead of flatlining."""
        if not self.segs or self.hi <= self.lo:
            return 0.6
        i = self.seg_at(pos)
        return max(0.0, min(1.0, (self.segs[i][1] - self.lo) / (self.hi - self.lo)))

    def energy(self, pos: float) -> float:
        """0..1, spiking on each beat and decaying, scaled by how loud it is."""
        if not self.beats:
            return 0.0
        i = bisect.bisect_right(self.starts, pos) - 1
        if i < 0:
            return 0.0
        start, strength = self.beats[i]
        span = (self.beats[i + 1][0] - start) if i + 1 < len(self.beats) else 0.5
        t = (pos - start) / max(0.08, span)
        if t >= 1.0:
            return 0.0
        return max(0.0, min(1.0, (1.0 - t) ** 2.2 * strength))

    def section(self, pos: float) -> int:
        if not self.sections:
            return 0
        return max(0, bisect.bisect_right(self.sections, pos) - 1)

    def grain(self) -> float:
        """How long the median segment runs -- the finest moment this analysis
        can place, and so the floor on anything ever timed from it. Median and
        not mean because a long held note is one enormous segment and would
        otherwise report a resolution the rest of the track does not have."""
        if len(self.seg_starts) < 2:
            return 0.0
        gaps = sorted(b - a for a, b in zip(self.seg_starts, self.seg_starts[1:]))
        return gaps[len(gaps) // 2]


# --------------------------------------------------------------------------

EST_REVISION = 1
ANCHOR_GAP = 0.35
EST_RANGE = 0.75
EST_STEP = 0.005
EST_SIGMA = 0.08
MIN_ANCHORS = 8
EST_CONF_MIN = 0.18
CAL_MIN = 5


def onsets_of(beat: Beat) -> list[tuple[float, float]]:
    """Where the sound changes, and by how much it looks like a voice doing it.

    Spotify cuts a new segment at every acoustic edge it finds, so the segment
    starts already ARE an onset list. The trouble is that it cuts for a kick
    drum as readily as for a singer, and on a dense record most edges are the
    kit -- correlating against them unweighted measures the drummer.

    What distinguishes the two is not loudness, which a snare has plenty of, but
    whether the spectrum either side of the edge has a different SHAPE. Another
    snare in a bar of snares is louder than its neighbour and otherwise
    identical; a voice entering over the same bar changes the timbre. Weighting
    by that change does not identify anybody -- nothing available here could --
    but it stops the estimate being decided by whichever percussion happened to
    fall nearest the line.
    """
    segs = beat.segs
    if len(segs) < MIN_ANCHORS * 2:
        return []
    rows = beat.timbre if len(beat.timbre) == len(segs) else []
    cols: list[float] = []
    if rows:
        width = min(len(r) for r in rows)
        rows = [r[:width] for r in rows]
        for c in range(width):
            vals = [r[c] for r in rows]
            mu = sum(vals) / len(vals)
            sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals))
            cols.append(sd or 1.0)
    raw: list[tuple[float, float, float]] = []
    for i in range(1, len(segs)):
        rise = max(0.0, segs[i][1] - segs[i - 1][1])
        shape = 0.0
        if cols:
            shape = math.sqrt(sum(((rows[i][c] - rows[i - 1][c]) / cols[c]) ** 2
                                  for c in range(1, len(cols))))
        raw.append((segs[i][0], rise, shape))
    if not raw:
        return []

    def scaled(vals: list[float]) -> list[float]:
        """0..1 against this track's own 90th percentile, so a compressed master
        still produces contrast instead of a flat line of ones."""
        ref = sorted(vals)[int(len(vals) * 0.9)] or max(vals) or 1.0
        return [min(1.0, v / ref) for v in vals]

    rises = scaled([r for _, r, _ in raw])
    shapes = scaled([s for _, _, s in raw]) if cols else [0.0] * len(raw)
    out = [(t, 0.65 * shapes[i] + 0.35 * rises[i] if cols else rises[i])
           for i, (t, _, _) in enumerate(raw)]
    mid = sorted(w for _, w in out)[len(out) // 2]
    return [(t, w) for t, w in out if w >= mid]


def anchors_of(lines: list[dict]) -> list[float]:
    """Line starts that a vocal entry should be audible under.

    Only the ones that follow real silence in the lyrics, for the reason given
    at ANCHOR_GAP, and only from the untouched timeline -- interlude markers are
    inserted by prepare() at times nobody sang, so they anchor to nothing.
    """
    out: list[float] = []
    prev_end = None
    for ln in lines:
        start = ln.get("start")
        if start is None or ln.get("dots") or not (ln.get("text") or "").strip():
            continue
        if prev_end is None or start - prev_end >= ANCHOR_GAP:
            out.append(float(start))
        end = ln.get("end")
        prev_end = max(prev_end or 0.0, float(end if end is not None else start))
    return out


def estimate_offset(lines: list[dict], beat: Beat) -> dict:
    """How far the lyrics sit from the sound, by correlating one against the other.

    Returns {} when there is not enough to say, which is the common answer and
    not a failure. Otherwise `delta` is how much LATER the lyrics should be
    played than they claim, `conf` is how far the winning alignment stood above
    its nearest rival, and `n` is how many anchors voted.

    The sum is over every edge near an anchor rather than the nearest one to it.
    Pairing with the nearest looks equivalent and is not: whichever side of the
    anchor an edge falls, "nearest" picks the closer, so the residuals are
    pulled toward zero and so is every estimate made from them -- the bias is
    worst exactly where the offset is small, which is the case this exists for.
    """
    anchors = anchors_of(lines)
    onsets = onsets_of(beat)
    if len(anchors) < MIN_ANCHORS or not onsets:
        return {}
    times = [t for t, _ in onsets]
    denom = 2.0 * EST_SIGMA * EST_SIGMA
    reach = EST_SIGMA * 3.0
    steps = int(EST_RANGE / EST_STEP)
    curve: list[tuple[float, float]] = []
    for k in range(-steps, steps + 1):
        d = k * EST_STEP
        total = 0.0
        for t in anchors:
            at = t + d
            lo = bisect.bisect_left(times, at - reach)
            hi = bisect.bisect_right(times, at + reach)
            for j in range(lo, hi):
                total += onsets[j][1] * math.exp(-((at - times[j]) ** 2) / denom)
        curve.append((d, total))
    best_d, best = max(curve, key=lambda r: r[1])
    if best <= 0.0:
        return {}
    rival = max((v for d, v in curve if abs(d - best_d) > EST_SIGMA * 2.0),
                default=0.0)
    return {"delta": round(best_d, 3), "conf": round((best - rival) / best, 3),
            "n": len(anchors), "rev": EST_REVISION}


def calibrate(raw: dict[str, float], hand: dict[str, float]) -> tuple[float, int]:
    """What this estimator reads on a track the user has already fixed by ear.

    The number estimate_offset() returns is not the sync error. It is the sync
    error plus a standing difference between what a lyric timestamp marks (a
    word starting) and what a segment edge marks (the spectrum changing), which
    is consistent, has nothing to do with whether a song is in time, and cannot
    be reasoned away from the analysis alone.

    It can be measured, though, wherever both numbers are known: on a track that
    was corrected by hand the truth is the hand correction, so the difference
    between the two readings is the standing error and nothing else. The median
    of those differences is what to subtract from every other track. Median
    rather than mean because one mistaken hand correction, or one track where
    the estimate latched onto the wrong beat entirely, should not move it.

    Returns the correction and how many tracks stand behind it, so a caller can
    decline to trust one built on two songs.
    """
    diffs = sorted(raw[t] - hand[t] for t in raw.keys() & hand.keys())
    if not diffs:
        return 0.0, 0
    n = len(diffs)
    mid = (diffs[n // 2] if n % 2 else (diffs[n // 2 - 1] + diffs[n // 2]) / 2.0)
    return round(mid, 3), n


JS_ARTISTS = """(() => {
  const d = Spicetify && Spicetify.Player && Spicetify.Player.data;
  const it = d && (d.item || d.track);
  if (!it) return null;
  const uri = it.uri || "";
  if (uri && uri.split(":").pop() !== %s) return null;   // player moved on
  let list = (it.artists || [])
    .filter(a => a && a.name)
    .map(a => ({name: a.name, uri: a.uri || ""}));
  const md = it.metadata || {};
  const alt = [];
  for (let i = 0; i < 16; i++) {
    const k = i ? "artist_name:" + i : "artist_name";
    if (md[k]) alt.push(md[k]);
    else if (i) break;
  }
  // the older shape carries names only, so anyone found this way has no uri
  if (alt.length > list.length) list = alt.map(n => ({name: n, uri: ""}));
  // the album rides along: it is on the same object, and MPRIS gives its name
  // but never its uri, which is the half needed to open or link to it
  const al = it.album || {};
  return {artists: list, album: {name: al.name || "", uri: al.uri || ""}};
})()"""


FEAT_RE = re.compile(
    r"[\(\[]\s*(feat|ft|featuring|with)\.?\s+([^\)\]]+)[\)\]]", re.I)
FEAT_SPLIT = re.compile(r"\s*(?:,|&|\bx\b|\band\b)\s*", re.I)


def split_artists(title: str, artists: list) -> tuple[list, list]:
    """Everyone credited, split into who the song is by and who guests on it.

    Spotify says nothing about which of a track's artists is featured -- they
    arrive as one flat list, primary first -- so the title is the only evidence
    there is, and no evidence means no guest. Being second on the credit is not
    a demotion: "Die With A Smile" is by both of them, and reading position as
    billing would call every duet a guest spot.

    Where the title does name someone, they are matched against the credit list
    loosely and in both directions, because the two rarely spell it the same --
    "Airplanes (feat. Hayley Williams of Paramore)" is credited to plain "Hayley
    Williams". Where they agree the credit-list spelling wins, being the
    canonical one and the only one carrying a uri, and that artist leaves the
    primary side so nobody is named twice.
    """
    artists = [a for a in (artists or []) if isinstance(a, dict) and a.get("name")]
    named, how_of = [], {}
    for word, chunk in FEAT_RE.findall(title or ""):
        for n in FEAT_SPLIT.split(chunk):
            n = n.strip()
            if n:
                named.append(n)
                how_of[n] = "with" if word.lower() == "with" else "feat"

    def key(s):
        return "".join(c for c in (s or "").lower() if c.isalnum())

    def same(a, b):
        ka, kb = key(a), key(b)
        return bool(ka) and bool(kb) and (
            ka == kb or (len(ka) >= 4 and ka in kb) or (len(kb) >= 4 and kb in ka))

    if not named:
        return artists, []

    feat, seen = [], set()
    for i, a in enumerate(artists):
        hit = next((n for n in named if same(a["name"], n)), None) if i else None
        if hit is not None and key(a["name"]) not in seen:
            seen.add(key(a["name"]))
            feat.append({**a, "how": how_of.get(hit, "feat")})
    for n in named:
        if not any(same(n, a["name"]) for a in artists) and key(n) not in seen:
            seen.add(key(n))
            feat.append({"name": n, "uri": "", "how": how_of.get(n, "feat")})
    lead = [a for a in artists if key(a["name"]) not in seen]
    return (lead or artists[:1]), feat


FONT_DIR = INDEX.parent / "fonts"
FONT_UA = "Mozilla/4.0"
FONT_REV = 2
FONT_CSS = "https://fonts.googleapis.com/css"


GH_FONTS = "https://api.github.com/repos/google/fonts/contents"
WEIGHTS = {"thin": 100, "extralight": 200, "ultralight": 200, "light": 300,
           "regular": 400, "normal": 400, "medium": 500, "semibold": 600,
           "demibold": 600, "bold": 700, "extrabold": 800, "ultrabold": 800,
           "black": 900, "heavy": 900}


def split_font(spec: str) -> tuple[str, int | None]:
    """"Outfit:900" or "Outfit Black" -> ("Outfit", 900).

    A weight is worth naming because a family is not one font. Ask Google for
    "Outfit" and what comes back depends entirely on which file it decides to
    send, which is how a page designed around Black ended up drawn in Thin.
    """
    spec = (spec or "").strip()
    if not spec:
        return "", None
    if ":" in spec:
        fam, _, w = spec.rpartition(":")
        w = w.strip().lower()
        if w.isdigit():
            return fam.strip(), max(100, min(900, int(w)))
        if w in WEIGHTS:
            return fam.strip(), WEIGHTS[w]
        return spec, None
    head, _, tail = spec.rpartition(" ")
    if head and tail.lower() in WEIGHTS:
        return head.strip(), WEIGHTS[tail.lower()]
    return spec, None


def _font_file(family: str, weight: int | None):
    """Pick the best file for a family out of the fonts repo, as (url, name).

    A variable file wins outright: it carries the whole weight axis, so Qt can
    be asked for Black later rather than being stuck with whatever single weight
    was downloaded. Static families are chosen by name instead.
    """
    slug = re.sub(r"[^a-z0-9]", "", family.lower())
    want = {900: "black", 800: "extrabold", 700: "bold", 600: "semibold",
            500: "medium", 400: "regular", 300: "light", 200: "extralight",
            100: "thin"}.get(weight or 0, "")
    for lic in ("ofl", "apache", "ufl"):
        try:
            req = urllib.request.Request(f"{GH_FONTS}/{lic}/{slug}",
                                         headers={"User-Agent": UA,
                                                  "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                items = json.loads(r.read())
        except Exception:
            continue
        files = [(i.get("name") or "", i.get("download_url") or "")
                 for i in items if isinstance(i, dict)
                 and (i.get("name") or "").lower().endswith(".ttf")]
        if not files:
            continue
        def rank(f):
            n = f[0].lower()
            ital = 1 if "italic" in n else 0
            return (ital,
                    0 if "wght" in n else
                    1 if want and want in n.replace("-", "") else
                    2 if "regular" in n else 3)
        files.sort(key=rank)
        return files[0][1], files[0][0]
    return None, None


def fetch_font(name: str, weight: int | None = None) -> pathlib.Path | None:
    """Download a font family, or None. Cached, so it is fetched once.

    The repo is tried first because it serves complete TrueType, variable where
    the family has one. The CSS endpoint is the fallback: it always answers, but
    with an old User-Agent -- the only way to get TrueType rather than woff2 out
    of it -- it hands back a single weight-400 file with no axis at all, which
    is why a page drawn at Black came out looking thin.
    """
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", name or "").strip()
    if not safe:
        return None
    out = FONT_DIR / f"{safe.replace(' ', '_')}.v{FONT_REV}.ttf"
    if out.exists() and out.stat().st_size > 4096:
        return out
    data = None
    url, _fn = _font_file(safe, weight)
    for candidate, ua in ((url, UA), (None, FONT_UA)):
        try:
            if candidate is None:
                q = urllib.parse.urlencode({"family": safe})
                req = urllib.request.Request(f"{FONT_CSS}?{q}",
                                             headers={"User-Agent": FONT_UA})
                with urllib.request.urlopen(req, timeout=12) as r:
                    css = r.read().decode("utf-8", "replace")
                urls = re.findall(r"url\((https://[^)]+)\)", css)
                if not urls:
                    continue
                candidate = urls[-1]
            req = urllib.request.Request(candidate, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=25) as r:
                blob = r.read()
            if len(blob) >= 4096 and blob[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
                data = blob
                break
        except Exception:
            continue
    if data is None:
        return None
    try:
        FONT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return out
    except Exception:
        return None


ART_DIR = INDEX.parent / "art"
UA = "mild-lyrics/1.0 (+personal lyrics viewer)"


def art_url(u: str) -> str:
    """Normalise whatever a Spotify API hands back into a fetchable URL.

    Three spellings turn up for the same kind of asset: plain https, the
    `spotify:image:<hash>` form RecentlyPlayedAPI uses, and `spotify:mosaic:`
    followed by the four covers a playlist collage is built from. There is no
    endpoint that renders the collage, so the first cover stands in for it --
    better than the empty square that a playlist would otherwise get.
    """
    if not isinstance(u, str):
        return ""
    if u.startswith("spotify:mosaic:"):
        parts = [p for p in u.split(":")[2:] if p]
        return "https://i.scdn.co/image/" + parts[0] if parts else ""
    if u.startswith("spotify:image:"):
        return "https://i.scdn.co/image/" + u.rsplit(":", 1)[-1]
    return u if u.startswith("http") else ""


JS_ALBUM = """(async () => {
  try {
    const r = await Spicetify.GraphQL.Request(
      Spicetify.GraphQL.Definitions.getAlbum,
      {uri: %s, locale: "", offset: 0, limit: 60});
    const a = ((r.data || {}).albumUnion) || {};
    if (!a.uri) return null;
    const rows = ((a.tracksV2 || a.tracks || {}).items) || [];
    const out = [];
    for (const x of rows) {
      const t = (x.track) || ((x.trackV2 || {}).data) || x || {};
      if (!t.uri) continue;
      out.push({uri: t.uri, name: t.name || "",
                ms: ((t.duration || {}).totalMilliseconds) || 0,
                sub: (((t.artists || {}).items) || [])
                       .map(y => (y.profile || {}).name).filter(Boolean).join(", ")});
    }
    return {uri: a.uri, name: a.name || "",
            year: (((a.date || {}).isoString) || "").slice(0, 4),
            art: (((a.coverArt || {}).sources || [])[0] || {}).url || "",
            artists: (((a.artists || {}).items) || [])
                       .map(y => ({name: ((y.profile || {}).name) || "", uri: y.uri || ""}))
                       .filter(y => y.name),
            tracks: out};
  } catch (e) { return null; }
})()"""

JS_ARTIST = """(async () => {
  try {
    const r = await Spicetify.GraphQL.Request(
      Spicetify.GraphQL.Definitions.queryArtistOverview, {uri: %s, locale: ""});
    const a = ((r.data || {}).artistUnion) || {};
    if (!a.uri) return null;
    const rows = ((((a.discography || {}).topTracks) || {}).items) || [];
    const out = [];
    for (const x of rows.slice(0, 30)) {
      const t = x.track || {};
      if (!t.uri) continue;
      out.push({uri: t.uri, name: t.name || "",
                ms: ((t.duration || {}).totalMilliseconds) || 0,
                sub: (((t.artists || {}).items) || [])
                       .map(y => (y.profile || {}).name).filter(Boolean).join(", ")});
    }
    const v = a.visuals || {};
    return {uri: a.uri, name: ((a.profile || {}).name) || "", year: "",
            art: ((((v.avatarImage || {}).sources) || [])[0] || {}).url || "",
            artists: [], tracks: out};
  } catch (e) { return null; }
})()"""

JS_SEARCH = """(async () => {
  try {
    const V = {searchTerm: %s, offset: 0, limit: 12, numberOfTopResults: 12,
               includeAudiobooks: true, includePreReleases: true,
               includeLocalConcertsField: true, includeAuthors: true};
    const r = await Spicetify.GraphQL.Request(
      Spicetify.GraphQL.Definitions.searchModalResults, V);
    const items = ((((r||{}).data||{}).searchV2||{}).topResultsV2||{}).itemsV2 || [];
    const out = [];
    for (const w of items) {
      const t = ((w||{}).item||w||{}).data || {};
      const kind = t.__typename || "";
      if (kind !== "Track" && kind !== "Album" && kind !== "Artist") continue;
      const arts = ((t.artists||{}).items)||[];
      out.push({
        uri: t.uri || "",
        name: t.name || ((t.profile||{}).name) || "",
        sub: kind === "Track"
               ? arts.map(a => (a.profile||{}).name).filter(Boolean).join(", ")
               : kind,
        art: (((t.albumOfTrack||{}).coverArt||{}).sources||[])[0]?.url
             || ((((t.visuals||{}).avatarImage||{}).sources)||[])[0]?.url
             || (((t.coverArt||{}).sources)||[])[0]?.url || "",
        ms: ((t.duration||{}).totalMilliseconds) || 0,
        kind: kind});
    }
    return out;
  } catch (e) { return null; }
})()"""

JS_RECENTS = """(async () => {
  try {
    const out = {tracks: [], ctx: []};
    try {
      const h = await Spicetify.Platform.PlayHistoryAPI.getContents();
      for (const it of ((h||{}).items||[]).slice(0, %d)) {
        if (!it || it.type !== "track") continue;
        out.tracks.push({
          uri: it.uri || "", name: it.name || "",
          sub: (it.artists||[]).map(a => a.name).filter(Boolean).join(", "),
          art: (((it.album||{}).images||[])[0]||{}).url || "",
          ms: ((it.duration||{}).milliseconds) || 0});
      }
    } catch (e) {}
    try {
      const c = await Spicetify.Platform.RecentlyPlayedAPI.getContexts(%d);
      for (const it of (c||[]).slice(0, %d)) {
        if (!it || !it.uri) continue;
        out.ctx.push({
          uri: it.uri, name: it.name || "",
          sub: (it.artists||[]).map(a => a.name).filter(Boolean).join(", ")
               || (it.type || ""),
          art: ((it.images||[])[0]||{}).url || ""});
      }
    } catch (e) {}
    return out;
  } catch (e) { return null; }
})()"""

JS_QUEUE = """(async () => {
  try {
    const q = await Spicetify.Platform.PlayerAPI.getQueue();
    const one = (it, src) => {
      if (!it || !it.uri) return null;
      const md = it.metadata || {};
      return {uri: it.uri, uid: it.uid || "",
              name: it.name || md.title || "",
              sub: (it.artists || []).map(a => a.name).filter(Boolean).join(", ")
                   || md.artist_name || "",
              art: ((it.images || [])[0] || {}).url || md.image_url || "",
              ms: (it.duration || {}).milliseconds || Number(md.duration || 0) || 0,
              src: src};
    };
    const out = {current: one((q || {}).current, "now"), items: []};
    for (const it of ((q || {}).queued || []).slice(0, 60)) {
      const r = one(it, "queued"); if (r) out.items.push(r);
    }
    for (const it of ((q || {}).nextUp || []).slice(0, 60)) {
      const r = one(it, "next"); if (r) out.items.push(r);
    }
    return out;
  } catch (e) { return null; }
})()"""

JS_SUGGEST = """(async () => {
  const out = {related: [], playlists: [], top: [], mine: [], artist: ""};
  // Resolve who is playing here rather than shuttling it in: the fetcher
  // thread already holds the connection, and this way the answer can never be
  // for a track that has since changed.
  let A = %s;
  if (!A) {
    try {
      const d = Spicetify.Player.data, it = d && (d.item || d.track);
      A = (((it || {}).artists || [])[0] || {}).uri || "";
    } catch (e) { A = ""; }
  }
  out.artist = A || "";
  const img = o => (((o || {}).sources) || [])[0] || {};
  if (A) {
    try {
      const r = await Spicetify.GraphQL.Request(
        Spicetify.GraphQL.Definitions.queryArtistRelated, {uri: A});
      const it = (((((r.data || {}).artistUnion || {}).relatedContent || {})
                   .relatedArtists) || {}).items || [];
      for (const x of it.slice(0, 12))
        out.related.push({uri: x.uri, name: (x.profile || {}).name || "",
          sub: "Artist",
          art: img(((x.visuals || {}).avatarImage)).url || ""});
    } catch (e) {}
    try {
      const r = await Spicetify.GraphQL.Request(
        Spicetify.GraphQL.Definitions.queryArtistDiscoveredOn, {uri: A});
      const it = (((((r.data || {}).artistUnion || {}).relatedContent || {})
                   .discoveredOnV2) || {}).items || [];
      for (const x of it.slice(0, 20)) {
        const d = x.data || {};
        // the list is padded with GenericError entries for anything the
        // account cannot see; those have no uri and must not become cards
        if (d.__typename !== "Playlist" || !d.uri) continue;
        out.playlists.push({uri: d.uri, name: d.name || "",
          sub: ((d.ownerV2 || {}).data || {}).name || "Playlist",
          art: img((((d.images || {}).items || [])[0])).url || ""});
      }
    } catch (e) {}
    try {
      const r = await Spicetify.GraphQL.Request(
        Spicetify.GraphQL.Definitions.queryArtistOverview, {uri: A, locale: ""});
      const it = ((((r.data || {}).artistUnion || {}).discography || {})
                  .topTracks || {}).items || [];
      for (const x of it.slice(0, 12)) {
        const t = x.track || {};
        if (!t.uri) continue;
        out.top.push({uri: t.uri, name: t.name || "",
          sub: ((t.artists || {}).items || [])
                 .map(a => (a.profile || {}).name).filter(Boolean).join(", "),
          art: img(((t.albumOfTrack || {}).coverArt)).url || ""});
      }
    } catch (e) {}
  }
  try {
    const r = await Spicetify.Platform.RootlistAPI.getContents({limit: 30});
    for (const x of (r.items || [])) {
      if (x.type !== "playlist" || !x.uri) continue;
      out.mine.push({uri: x.uri, name: x.name || "",
        sub: "Playlist", art: ((x.images || [])[0] || {}).url || ""});
      if (out.mine.length >= 12) break;
    }
  } catch (e) {}
  return out;
})()"""

JS_DISCOVER = """(async () => {
  const out = {seed: "", because: [], songs: []};
  const img = o => (((o || {}).sources) || [])[0] || {};
  let hist = [];
  try {
    const h = await Spicetify.Platform.PlayHistoryAPI.getContents();
    hist = (h || {}).items || [];
  } catch (e) { return out; }
  if (!hist.length) return out;

  const heard = new Set();
  const tally = new Map();
  hist.forEach((x, i) => {
    if (x.uri) heard.add(x.uri);
    // newest first, so the top of the list counts for more -- what you played
    // an hour ago should steer this more than what you played last week
    const w = 1 + (hist.length - i) / hist.length;
    for (const a of (x.artists || [])) {
      if (!a.uri) continue;
      const e = tally.get(a.uri) || {name: a.name || "", score: 0};
      e.score += w;
      tally.set(a.uri, e);
    }
  });

  const cur = %s;   // excluded: whoever is playing already has their own shelves
  const seeds = [...tally.entries()].filter(e => e[0] !== cur)
                  .sort((a, b) => b[1].score - a[1].score).slice(0, 3);
  if (!seeds.length) return out;
  out.seed = seeds[0][1].name;

  const rel = new Map();
  for (const [uri] of seeds) {
    try {
      const r = await Spicetify.GraphQL.Request(
        Spicetify.GraphQL.Definitions.queryArtistRelated, {uri: uri});
      const it = (((((r.data || {}).artistUnion || {}).relatedContent || {})
                   .relatedArtists) || {}).items || [];
      for (const x of it.slice(0, 6)) {
        // skip anyone already in the history: a recommendation should be
        // something new, not a list of the artists it was derived from
        if (!x.uri || tally.has(x.uri) || rel.has(x.uri)) continue;
        rel.set(x.uri, {uri: x.uri, name: (x.profile || {}).name || "",
                        sub: "Artist",
                        art: img((x.visuals || {}).avatarImage).url || ""});
      }
    } catch (e) {}
  }
  out.because = [...rel.values()].slice(0, 12);

  for (const a of [...rel.values()].slice(0, 5)) {
    if (out.songs.length >= 12) break;
    try {
      const r = await Spicetify.GraphQL.Request(
        Spicetify.GraphQL.Definitions.queryArtistOverview, {uri: a.uri, locale: ""});
      const tt = ((((r.data || {}).artistUnion || {}).discography || {})
                  .topTracks || {}).items || [];
      for (const x of tt.slice(0, 3)) {
        const t = x.track || {};
        if (!t.uri || heard.has(t.uri)) continue;
        out.songs.push({uri: t.uri, name: t.name || "",
          sub: ((t.artists || {}).items || [])
                 .map(z => (z.profile || {}).name).filter(Boolean).join(", "),
          art: img((t.albumOfTrack || {}).coverArt).url || ""});
        if (out.songs.length >= 12) break;
      }
    } catch (e) {}
  }
  return out;
})()"""

JS_TRACKS = """(async () => {
  const ids = %s;
  const out = [];
  for (const id of ids) {
    try {
      const r = await Spicetify.GraphQL.Request(
        Spicetify.GraphQL.Definitions.getTrack, {uri: "spotify:track:" + id});
      const t = ((r||{}).data||{}).trackUnion;
      if (!t || !t.name) { out.push({id: id, name: "", artist: ""}); continue; }
      const a = ((t.firstArtist||{}).items) || ((t.artists||{}).items) || [];
      out.push({id: id, name: t.name,
                artist: a.map(x => (x.profile||{}).name).filter(Boolean).join(", ")});
    } catch (e) { out.push({id: id, name: "", artist: ""}); }
  }
  return out;
})()"""


MOTION_DIR = INDEX.parent / "motion"
MOTION_FPS = 30
MOTION_SECS = 35.0
MOTION_PX = 720
MOTION_MEMO = MOTION_DIR / "known.json"
MOTION_MISS_TTL = 30 * 86400
AMP_VIDEO = re.compile(r"<amp-ambient-video[^>]+src=\"([^\"]+\.m3u8)\"")
HLS_VARIANT = re.compile(r"^#EXT-X-STREAM-INF:.*?RESOLUTION=(\d+)x(\d+)", re.M)
APPLE_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _apple_get(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": APPLE_UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def best_variant(master_url: str) -> str:
    """The highest-resolution rendition in an HLS master playlist.

    Handed the master, ffmpeg sees every rendition at once -- twenty-odd streams
    from 360x360 up -- and picks among them by its own reckoning, interleaving
    segments from several as it goes. That is where both the softness and the
    "Invalid NAL unit" complaints came from. Choosing one rendition here and
    passing ffmpeg that leaves it nothing to guess at.
    """
    try:
        text = _apple_get(master_url)
    except Exception:
        return master_url
    lines = text.splitlines()
    best, best_url = 0, ""
    for i, line in enumerate(lines):
        m = HLS_VARIANT.match(line)
        if not m:
            continue
        for nxt in lines[i + 1:i + 4]:
            nxt = nxt.strip()
            if nxt and not nxt.startswith("#"):
                if int(m.group(1)) > best:
                    best, best_url = int(m.group(1)), urllib.parse.urljoin(
                        master_url, nxt)
                break
    return best_url or master_url


def _akey(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _loose(a: str, b: str) -> bool:
    """Same name allowing for editions and suffixes, in either direction."""
    ka, kb = _akey(a), _akey(b)
    if not ka or not kb:
        return False
    return ka == kb or (len(ka) >= 4 and ka in kb) or (len(kb) >= 4 and kb in ka)


EDITION = re.compile(
    r"\s*(?:[\(\[][^()\[\]]*(?:deluxe|edition|version|remaster|expanded|"
    r"anniversary|special|bonus|explicit|reissue)[^()\[\]]*[\)\]]"
    r"|-\s*(?:single|ep|deluxe\b.*|.*\bedition\b.*|.*\bversion\b.*))\s*$",
    re.I)
AM_ALBUM = re.compile(r"music\.apple\.com/[a-z]{2}/album/[^/\"?]+/(\d+)")


def _plain(name: str) -> str:
    """The record's name with its edition suffix off, or the name unchanged."""
    out = name
    for _ in range(2):
        out = EDITION.sub("", out)
    return out.strip() or name


def _itunes_albums(term: str) -> list:
    """What the iTunes Search API has for this term. Fast, and often enough."""
    q = urllib.parse.urlencode({"term": term, "entity": "album", "limit": 10})
    try:
        raw = _apple_get(f"https://itunes.apple.com/search?{q}")
        return (json.loads(raw) or {}).get("results") or []
    except Exception:
        return []


def _web_albums(term: str) -> list:
    """The same, from music.apple.com's search page.

    The Search API's index runs years behind for some records -- "Linkin Park
    From Zero" returns Meteora, Hybrid Theory and Living Things and never the
    2024 album at all, deluxe or not. The web page finds it. It carries no
    usable metadata for matching, though, so its album ids go back through the
    lookup endpoint to come out in the same shape as a search hit.
    """
    try:
        html = _apple_get("https://music.apple.com/us/search?term="
                          + urllib.parse.quote(term))
    except Exception:
        return []
    ids: list[str] = []
    for m in AM_ALBUM.finditer(html):
        if m.group(1) not in ids:
            ids.append(m.group(1))
        if len(ids) >= 12:
            break
    if not ids:
        return []
    try:
        raw = _apple_get("https://itunes.apple.com/lookup?id=" + ",".join(ids))
        hits = (json.loads(raw) or {}).get("results") or []
    except Exception:
        return []
    return [h for h in hits if h.get("wrapperType") == "collection"]


def motion_url(artist: str, album: str, title: str = "") -> str:
    """The animated cover's stream for this record, or "".

    Two steps because the two halves live in different places: the search knows
    which album this is and nothing about its video, and the music.apple.com
    page carries the video but cannot be found without the id.

    The animation belongs to the record, never to the track, so the album name
    is what is searched. A single is the one case where the two coincide -- the
    release is the song -- and there the song's title stands in for it.

    The artist is checked as hard as the title is. Album names are nowhere near
    unique -- searching "NF NO NAME" returns NF's own single, three unrelated NF
    records, and Jack White's "No Name" -- and since a page without an animation
    is skipped rather than fatal, matching on the title alone walked straight
    past NF and hung Jack White's video on his record.
    """
    single = not album or _loose(_plain(album), _plain(title))
    name = album or title
    if not name.strip() or not artist.strip():
        return ""
    terms = []
    for term in (f"{artist} {name}", f"{artist} {_plain(name)}",
                 f"{artist} {title}" if single and title else ""):
        term = " ".join(term.split())
        if term and term not in terms:
            terms.append(term)
    keep, seen = [], set()
    for finder in (_itunes_albums, _web_albums):
        for term in terms:
            for hit in finder(term):
                url = (hit.get("collectionViewUrl") or "").split("?")[0]
                theirs = hit.get("collectionName") or ""
                by = hit.get("artistName") or ""
                if not url or url in seen:
                    continue
                if not (_loose(name, theirs) and _loose(artist, by)):
                    continue
                seen.add(url)
                rank = 2
                if _akey(theirs) == _akey(name):
                    rank = 0
                elif _akey(_plain(theirs)) == _akey(_plain(name)):
                    rank = 1
                keep.append((rank, url))
        if keep:
            break
    keep.sort(key=lambda r: r[0])
    for _, url in keep:
        try:
            found = AMP_VIDEO.search(_apple_get(url))
        except Exception:
            continue
        if found:
            return found.group(1)
    return ""


class MotionArt(QObject):
    """The animated cover, as frames, fetched and decoded off the GUI thread.

    Everything about this is best-effort: the album may have no animation, the
    page format is Apple's and undocumented, and ffmpeg may not be installed.
    Every failure ends the same way -- no frames, and the still cover carries on
    exactly as it did before.
    """
    ready = pyqtSignal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.q: queue.Queue = queue.Queue()
        self.seen: set[str] = set()
        self.stop = False
        self._known: dict | None = None
        self._lock = threading.Lock()
        threading.Thread(target=self._work, daemon=True).start()

    def want(self, key: str, artist: str, album: str, title: str = "") -> None:
        with self._lock:
            if key in self.seen:
                return
            self.seen.add(key)
        self.q.put((key, artist, album, title))

    def _dir(self, key: str) -> pathlib.Path:
        return MOTION_DIR / hashlib.sha1(key.encode()).hexdigest()[:16]

    def _work(self) -> None:
        while not self.stop:
            try:
                key, artist, album, title = self.q.get(timeout=0.4)
            except Exception:
                continue
            if self.stop:
                return
            try:
                frames = self._frames(key, artist, album, title)
            except Exception:
                frames = []
            if frames and not self.stop:
                self.ready.emit(key, frames)

    def _memo(self) -> dict:
        """What Apple has already answered, album by album. Read once."""
        if self._known is None:
            try:
                self._known = json.loads(MOTION_MEMO.read_text())
            except Exception:
                self._known = {}
        return self._known

    def _remember(self, key: str, url: str, artist: str, album: str) -> None:
        """Record the answer. An empty url is a miss, and that is the entry
        worth having -- it is the one that saves a search next time."""
        memo = self._memo()
        memo[key] = {"url": url, "at": int(time.time()),
                     "artist": artist, "album": album,
                     "dir": self._dir(key).name}
        try:
            MOTION_MEMO.parent.mkdir(parents=True, exist_ok=True)
            tmp = MOTION_MEMO.with_suffix(".tmp")
            tmp.write_text(json.dumps(memo, indent=1))
            tmp.replace(MOTION_MEMO)
        except Exception:
            pass

    def _decode(self, url: str, out: pathlib.Path) -> list:
        """The stream, turned into frames on disk. Empty if that did not work."""
        out.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               "-user_agent", APPLE_UA, "-i", best_variant(url),
               "-t", str(MOTION_SECS),
               "-vf", f"fps={MOTION_FPS},scale={MOTION_PX}:-1",
               "-q:v", "2",
               "-frames:v", str(int(MOTION_FPS * MOTION_SECS)),
               str(out / "f_%03d.jpg")]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            subprocess.run(cmd, timeout=120, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=flags)
        except FileNotFoundError:
            return []
        except Exception:
            return []
        return sorted(out.glob("f_*.jpg"))

    def _frames(self, key: str, artist: str, album: str, title: str = "") -> list:
        out = self._dir(key)
        have = sorted(out.glob("f_*.jpg")) if out.is_dir() else []
        if not have:
            memo = self._memo().get(key) or {}
            recent = time.time() - float(memo.get("at") or 0) < MOTION_MISS_TTL
            if memo and not memo.get("url") and recent:
                return []
            url = memo.get("url") or ""
            have = self._decode(url, out) if url else []
            if not have:
                url = motion_url(artist, album, title)
                have = self._decode(url, out) if url else []
            self._remember(key, url if have else "", artist, album)
        imgs = []
        for path in have:
            img = QImage()
            if img.load(str(path)) and not img.isNull():
                imgs.append(img)
        return imgs


class ArtCache(QObject):
    """Thumbnails for the browse grid.

    _load_art spawns a thread per image and blurs it four times over -- right for
    one full-size cover behind the lyrics, hopeless for forty 160px cards. This
    is a small fixed pool with a disk cache instead.

    Workers emit QImage, never QPixmap: QPixmap is main-thread only and is a
    documented crash here.
    """
    loaded = pyqtSignal(str, object)
    MAX = 250

    def __init__(self, size: int = 320) -> None:
        super().__init__()
        self.size = size
        self.pix: dict[str, QPixmap] = {}
        self.q: queue.Queue = queue.Queue()
        self.seen: set[str] = set()
        self.stop = False
        self._lock = threading.Lock()
        for _ in range(2):
            threading.Thread(target=self._work, daemon=True).start()

    def get(self, url: str):
        """Called from paint. Returns a pixmap, or None and queues a fetch."""
        if not url:
            return None
        hit = self.pix.get(url)
        if hit is not None:
            return hit
        with self._lock:
            if url in self.seen:
                return None
            self.seen.add(url)
        self.q.put(url)
        return None

    def put(self, url: str, img) -> None:
        """GUI thread only -- QPixmap conversion has to happen here."""
        if len(self.pix) > self.MAX:
            for k in list(self.pix)[: self.MAX // 4]:
                self.pix.pop(k, None)
        self.pix[url] = QPixmap.fromImage(img)

    def _path(self, url: str) -> pathlib.Path:
        return ART_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")

    def _work(self) -> None:
        while not self.stop:
            try:
                url = self.q.get(timeout=0.4)
            except queue.Empty:
                continue
            if self.stop:
                return
            img = QImage()
            path = self._path(url)
            try:
                if path.exists():
                    img.load(str(path))
            except Exception:
                pass
            if img.isNull():
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=8) as r:
                        raw = r.read()
                    img.loadFromData(raw)
                    if not img.isNull():
                        ART_DIR.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(raw)
                except Exception:
                    continue
            if img.isNull() or self.stop:
                continue
            if max(img.width(), img.height()) > self.size:
                img = img.scaled(self.size, self.size,
                                 Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            if not self.stop:
                self.loaded.emit(url, img)


def _above(order: list, a: str, b: str) -> bool:
    """Whether `a` is consulted before `b`. False if either is switched off."""
    return a in order and b in order and order.index(a) < order.index(b)


def _people(v) -> list[str]:
    """Usernames out of a credit slot, however many it turns out to hold.

    Spicy Lyrics writes Maker and Uploader as one {id, username, avatar} object
    each, and its own UI reads them that way. But a sync can have more than one
    author, and the day the field grows into a list is not a day this should
    quietly show nothing -- so an object, a list of them, and a bare name are
    all read the same. An empty {} is how "nobody is credited here" is spelled,
    and comes back as no names rather than as a blank one.
    """
    if isinstance(v, (dict, str)):
        v = [v]
    out = []
    for one in v if isinstance(v, list) else []:
        name = (str(one.get("username") or one.get("name") or "").strip()
                if isinstance(one, dict) else str(one or "").strip())
        if name and name not in out:
            out.append(name)
    return out


class Fetcher(QObject):
    ready = pyqtSignal(str, object, object)
    artists_ready = pyqtSignal(str, object)
    beat_ready = pyqtSignal(str, object)
    index_ready = pyqtSignal(object)
    index_progress = pyqtSignal(int)
    genius_ready = pyqtSignal(str, object, object)
    recents_ready = pyqtSignal(object, object)
    catsearch_ready = pyqtSignal(str, object)
    backfill_progress = pyqtSignal(int, int)
    backfill_ready = pyqtSignal(object)
    queue_ready = pyqtSignal(object)
    suggest_ready = pyqtSignal(object)
    discover_ready = pyqtSignal(object)
    ne_roman_ready = pyqtSignal(str, object)
    album_ready = pyqtSignal(str, object)

    def __init__(self, port: int, split: str, threshold: float) -> None:
        super().__init__()
        self.port, self.split, self.threshold = port, split, threshold
        self.cdp = None
        self._want: str | None = None
        self.stop = False
        self._index = False
        self._index_at: int | None = None
        self._index_songs: list[dict] = []
        self._play: str | None = None
        self._genius: tuple | None = None
        self._ne_roman: tuple | None = None
        self._album: str | None = None
        self._meta: dict = {}
        self._sources: set = set()
        self._order: list = []
        self._graft = True
        self.done: str = ""
        self._recents = False
        self._queue = False
        self._skip: tuple | None = None
        self._suggest: str | None = None
        self._discover = False
        self._search: str | None = None
        self._backfill_ids: list = []
        self._backfill_at: int | None = None
        self._lock = threading.Lock()

    def request(self, tid: str, meta: dict | None = None, sources=None,
                order=None, graft=None) -> None:
        with self._lock:
            self._want = tid
            if meta:
                self._meta = dict(meta)
            if sources is not None:
                self._sources = set(sources)
            if order is not None:
                self._order = list(order)
            if graft is not None:
                self._graft = bool(graft)

    def request_index(self) -> None:
        with self._lock:
            self._index = True

    def request_play(self, uri: str) -> None:
        with self._lock:
            self._play = uri

    def request_recents(self) -> None:
        with self._lock:
            self._recents = True

    def request_queue(self) -> None:
        with self._lock:
            self._queue = True

    def request_skip(self, uri: str, uid: str) -> None:
        with self._lock:
            self._skip = (uri, uid)

    def request_suggest(self, artist_uri: str) -> None:
        with self._lock:
            self._suggest = artist_uri or ""

    def request_discover(self) -> None:
        with self._lock:
            self._discover = True

    def request_catsearch(self, q: str) -> None:
        with self._lock:
            self._search = q

    def request_backfill(self, ids) -> None:
        with self._lock:
            self._backfill_ids = list(ids)
            self._backfill_at = 0

    def request_genius(self, token, tid, title, artist, ours) -> None:
        with self._lock:
            self._genius = (token, tid, title, artist, ours)

    def request_ne_roman(self, tid: str, meta: dict) -> None:
        with self._lock:
            self._ne_roman = (tid, dict(meta or {}))

    def request_album(self, uri: str, kind: str = "album") -> None:
        with self._lock:
            self._album = (uri, kind) if uri else None

    def run(self) -> None:
        pending: dict[str, float] = {}
        backoff: dict[str, float] = {}
        while not self.stop:
            with self._lock:
                tid, self._want = self._want, None
                want_index, self._index = self._index, False
                play, self._play = self._play, None
                gen, self._genius = self._genius, None
                ne_rom, self._ne_roman = self._ne_roman, None
                album, self._album = self._album, None
                recents, self._recents = self._recents, False
                want_q, self._queue = self._queue, False
                skip, self._skip = self._skip, None
                sugg, self._suggest = self._suggest, None
                disc, self._discover = self._discover, False
                query, self._search = self._search, None
            if tid and pending.get(tid, 0) <= time.monotonic():
                asked = tid in pending
                lines, body = self._load(tid, settled=asked)
                if asked or lines:
                    self.done = tid
                if lines:
                    pending.pop(tid, None)
                    backoff.pop(tid, None)
                else:
                    step = backoff.get(tid)
                    step = RETRY_FIRST if not step else min(RETRY_MAX, step * 2)
                    backoff[tid] = step
                    pending[tid] = time.monotonic() + step
                    with self._lock:
                        if self._want is None:
                            self._want = tid
                if self.stop:
                    return
                self.ready.emit(tid, lines, body)
                if not self.stop:
                    self.artists_ready.emit(tid, self._artists(tid))
                if lines and not self.stop:
                    self.beat_ready.emit(tid, self._audio(tid))
            if play:
                self._eval(f"Spicetify.Player.playUri({json.dumps(play)})")
            if gen and not self.stop:
                self._genius_lookup(*gen)
            if album and not self.stop:
                a_uri, a_kind = album
                js = JS_ARTIST if a_kind == "artist" else JS_ALBUM
                got = self._eval(js % json.dumps(a_uri))
                if isinstance(got, dict):
                    got["art"] = art_url(got.get("art") or "")
                self.album_ready.emit(a_uri, got)
            if ne_rom and not self.stop:
                tid_r, meta_r = ne_rom
                try:
                    got = LS.netease_roman(meta_r)
                except Exception:
                    got = {}
                if not self.stop:
                    self.ne_roman_ready.emit(tid_r, got)
            if recents and not self.stop:
                self.recents_ready.emit(*self._recents_fetch())
            if skip and not self.stop:
                self._skip_to(*skip)
            if want_q and not self.stop:
                self.queue_ready.emit(self._queue_fetch())
            if sugg is not None and not self.stop:
                self.suggest_ready.emit(self._suggest_fetch(sugg))
            if disc and not self.stop:
                self.discover_ready.emit(self._discover_fetch())
            if query is not None and not self.stop:
                self.catsearch_ready.emit(query, self._catsearch(query))
            if self._backfill_at is not None and not self.stop:
                self._backfill_batch()
            if want_index and self._index_at is None:
                self._index_at, self._index_songs = 0, []
            if self._index_at is not None:
                self._index_batch()
            time.sleep(POLL_WAITING if tid and tid in pending else POLL_IDLE)

    def _genius_lookup(self, token, tid, title, artist, ours) -> None:
        """Network + alignment, both off the GUI thread."""
        try:
            got = GR.find_romanization(token, title, artist)
        except Exception:
            got = None
        if not got:
            self.genius_ready.emit(tid, None, None)
            return
        lines, hit = got
        try:
            mapping = GR.align(ours, lines)
        except Exception:
            mapping = {}
        self.genius_ready.emit(tid, mapping, hit.get("full_title") or "")

    def _eval(self, js):
        try:
            if self.cdp is None:
                self.cdp = connect(self.port)
            return self.cdp.evaluate(js)
        except Exception:
            return None

    def _index_batch(self) -> None:
        """One page of Cache Storage per call, so the loop keeps serving
        lyric requests while a full index is being built."""
        try:
            if self.cdp is None:
                self.cdp = connect(self.port)
            batch = self.cdp.evaluate(
                SL.JS_DUMP_PAGE % (json.dumps(SL.CACHE_NAME), self._index_at, 100))
        except Exception:
            batch = None
        if not batch:
            songs, self._index_songs, self._index_at = self._index_songs, [], None
            if not self.stop:
                self.index_ready.emit(songs)
            return
        for e in batch:
            try:
                doc = SL.payload(e["body"])
                lines = [t for t in (SL.line_text(i) for i in
                                     (doc.get("Content") or doc.get("Lines") or [])
                                     if isinstance(i, dict)) if t and t.strip()]
                if lines:
                    items = doc.get("Content") or doc.get("Lines") or []
                    synced = any(isinstance(i, dict) and isinstance(i.get("Lead"), dict)
                                 and (i["Lead"].get("Syllables") or [])
                                 for i in items)
                    roman = bool(doc.get("HasTransliterations"))
                    self._index_songs.append({"id": e["id"], "lines": lines,
                                              "synced": synced, "roman": roman,
                                              "lang": doc.get("Language") or "",
                                              "title": "", "artist": ""})
            except Exception:
                continue
        self._index_at += len(batch)
        if not self.stop:
            self.index_progress.emit(len(self._index_songs))

    def _recents_fetch(self):
        n = 24
        got = self._eval(JS_RECENTS % (n, n, n)) or {}
        tracks = [t for t in (got.get("tracks") or []) if isinstance(t, dict)]
        ctx = [c for c in (got.get("ctx") or []) if isinstance(c, dict)]
        for row in tracks + ctx:
            row["art"] = art_url(row.get("art") or "")
        return tracks, ctx

    def _skip_to(self, uri: str, uid: str) -> None:
        """Jump to an item already in the queue.

        skipTo takes the queue entry, so the uid matters -- the same track can
        legitimately sit in the queue more than once. If the shape is ever
        rejected, playing the uri outright is a worse but working answer.
        """
        js = ("(async () => { try {"
              "  await Spicetify.Platform.PlayerAPI.skipTo(%s); return true;"
              "} catch (e) { try { Spicetify.Player.playUri(%s); } catch (e2) {}"
              "  return false; } })()")
        self._eval(js % (json.dumps({"uri": uri, "uid": uid}), json.dumps(uri)))

    def _queue_fetch(self):
        got = self._eval(JS_QUEUE)
        if not isinstance(got, dict):
            return None
        items = [r for r in (got.get("items") or []) if isinstance(r, dict)]
        for r in items:
            r["art"] = art_url(r.get("art") or "")
        cur = got.get("current")
        if isinstance(cur, dict):
            cur["art"] = art_url(cur.get("art") or "")
        return {"current": cur if isinstance(cur, dict) else None, "items": items}

    def _suggest_fetch(self, artist_uri: str):
        got = self._eval(JS_SUGGEST % json.dumps(artist_uri or ""))
        if not isinstance(got, dict):
            return None
        out = {}
        out["artist"] = str(got.get("artist") or "")
        for key in ("related", "playlists", "top", "mine"):
            rows = [r for r in (got.get(key) or []) if isinstance(r, dict) and r.get("uri")]
            for r in rows:
                r["art"] = art_url(r.get("art") or "")
            out[key] = rows
        return out

    def _discover_fetch(self):
        """Up to eight round trips, so it runs on its own request rather than
        holding up the artist shelves that come back in one."""
        cur = self._eval(
            '(() => { try { const d = Spicetify.Player.data,'
            ' it = d && (d.item || d.track);'
            ' return (((it || {}).artists || [])[0] || {}).uri || ""; }'
            ' catch (e) { return ""; } })()') or ""
        got = self._eval(JS_DISCOVER % json.dumps(cur))
        if not isinstance(got, dict):
            return None
        out = {"seed": str(got.get("seed") or "")}
        for key in ("because", "songs"):
            rows = [r for r in (got.get(key) or []) if isinstance(r, dict) and r.get("uri")]
            for r in rows:
                r["art"] = art_url(r.get("art") or "")
            out[key] = rows
        return out

    def _catsearch(self, query: str):
        """Spotify's catalogue. Returns [] rather than raising when the shape
        drifts, so the screen says 'no results' instead of blanking."""
        if len(query) < 2:
            return []
        got = self._eval(JS_SEARCH % json.dumps(query))
        if not isinstance(got, list):
            return []
        rank = {"Track": 0, "Album": 1, "Artist": 2}
        label = {"Track": "Songs", "Album": "Albums", "Artist": "Artists"}
        out = []
        for r in got:
            if not isinstance(r, dict) or not r.get("uri"):
                continue
            r["art"] = art_url(r.get("art") or "")
            r["section"] = label.get(r.get("kind") or "", "On Spotify")
            out.append(r)
        out.sort(key=lambda r: rank.get(r.get("kind") or "", 3))
        return out

    def _backfill_batch(self) -> None:
        at, ids = self._backfill_at, self._backfill_ids
        if at is None or at >= len(ids):
            self._backfill_at = None
            if not self.stop:
                self.backfill_ready.emit(None)
            return
        chunk = ids[at:at + 25]
        got = self._eval(JS_TRACKS % json.dumps(chunk)) or []
        self._backfill_at = at + len(chunk)
        if self.stop:
            return
        self.backfill_ready.emit([r for r in got if isinstance(r, dict)])
        self.backfill_progress.emit(self._backfill_at, len(ids))

    def _artists(self, tid: str):
        """Everyone credited on the track, as the page has it."""
        try:
            if self.cdp is None:
                return None
            return self.cdp.evaluate(JS_ARTISTS % json.dumps(tid))
        except Exception:
            return None

    def _audio(self, tid: str):
        """Audio analysis, on this same thread and socket -- it is one round trip
        and Spicetify memoises it per track inside the page."""
        try:
            if self.cdp is None:
                return None
            return self.cdp.evaluate(Beat.JS % json.dumps(f"spotify:track:{tid}"))
        except Exception:
            return None

    def _load(self, tid: str, settled: bool = True):
        body = None
        with self._lock:
            spicy = "spicy" in self._sources or not self._sources
            order, graft = list(self._order), self._graft
        ahead = order[:order.index("spicy")] if "spicy" in order else []
        if not spicy:
            return self._only_fallback(tid)
        for attempt in (1, 2):
            try:
                if self.cdp is None:
                    self.cdp = connect(self.port)
                res = self.cdp.evaluate(
                    SL.JS_GET % SL._j(SL.CACHE_NAME, SL.IDB_NAME, SL.IDB_STORE, tid)
                ) or {}
                body = res.get("body")
                break
            except Exception:
                try:
                    if self.cdp:
                        self.cdp.close()
                except Exception:
                    pass
                self.cdp = None
                if attempt == 2:
                    return self._only_fallback(tid)
        have = LS.quality(body) if body else "none"
        if (have != "syllable" or ahead) and (body or settled):
            self._interim(tid, body)
            better = self._fallback(tid, have, ahead, local=body)
            if better is not None:
                merged = None
                whose = str(better.get("_alone") or better.get("_source") or "")
                if whose == "netease" and graft and _above(order, "spicy", "netease"):
                    merged = LS.graft_syllables(body, better)
                body = merged if merged is not None else better
        if not body:
            return [], None
        try:
            lines = SL.timeline(body, split=self.split, threshold=self.threshold)
        except Exception:
            return [], None
        self._duet(tid, lines)
        return lines, body

    def _interim(self, tid: str, body) -> None:
        """Show a document now, while a better one is still being looked for.

        Deliberately skips _duet: that goes to the network too, and the whole
        point of this emit is to reach the screen before any of that happens.
        The duet flags arrive with the final answer a moment later.
        """
        if not body or self.stop:
            return
        try:
            lines = SL.timeline(body, split=self.split, threshold=self.threshold)
        except Exception:
            return
        if lines and not self.stop:
            self.ready.emit(tid, lines, body)

    def _duet(self, tid: str, lines: list) -> None:
        """Fill in a duet's second voice when the source forgot to mark it."""
        with self._lock:
            meta, want = dict(self._meta), set(self._sources)
        try:
            flags = LS.duet_flags(lines, tid, meta, enabled=want)
        except Exception:
            return
        for ln, on in zip(lines, flags or []):
            ln["opposite"] = on

    def _only_fallback(self, tid: str):
        """Spicy Lyrics switched off: whatever the rest of the chain has."""
        body = self._fallback(tid, "none")
        if not body:
            return [], None
        try:
            lines = SL.timeline(body, split=self.split, threshold=self.threshold)
        except Exception:
            return [], None
        self._duet(tid, lines)
        return lines, body

    def _fallback(self, tid: str, have: str, ahead=(), local=None):
        """Ask the other sources, in order, for something better than `have`."""
        with self._lock:
            meta, want = dict(self._meta), set(self._sources)
            order = list(self._order)
        try:
            got = LS.fallback(tid, meta, have, enabled=want, order=order,
                              ahead=ahead, local=local)
        except Exception:
            return None
        if not got:
            return None
        doc, name = got
        doc["_source"] = name
        return doc


# --------------------------------------------------------------------------
def render_pieces(ln: dict) -> list[tuple]:
    """Timed fragments to lay out and fill for one line.

    Syllable lyrics already carry them. Line-level lyrics carry one blob of
    text, which leaves the wrapper nothing to break on -- long lines then run
    straight off the right edge -- so split into words and interpolate their
    timings, which also turns the fill into a word-by-word sweep.
    """
    if ln["syls"]:
        return ln["syls"]
    words = ln["text"].split()
    s, e = ln["start"], ln["end"]
    if not words:
        return [(s, e, ln["text"], False)]
    if s is None or e is None or e <= s:
        return [(s, e, w, False) for w in words]
    total = sum(len(w) for w in words) or 1
    out, t = [], s
    for i, w in enumerate(words):
        end = e if i == len(words) - 1 else t + (e - s) * len(w) / total
        out.append((t, end, w, False))
        t = end
    return out


def retime_roman(ln: dict, text: str) -> list[tuple]:
    """Hang a replacement romanisation on the line's real syllable timings.

    A Genius romanisation is one blob of text, so it used to go through
    render_pieces and get its timings by spreading the words evenly across the
    line -- which meant every corrected line filled at a constant rate instead
    of following the voice, and the fill drifted away from the original above
    it. The line already carries per-syllable times; the job is only to work out
    which syllable each piece of the new text belongs to.

    That is done letter by letter, not word by word. Genius writes 響いている as
    one word, "hibiiteiru", where the source times 響い / て / いる separately: as
    a single piece it fills at one flat rate across all three and visibly lags
    the original above it. Cut at the letters where the syllable changes and
    each fragment fills on its own syllable's clock, so the two lines stay in
    step. Fragments are marked part-of-word, so nothing is drawn any differently.
    """
    words = text.split()
    base = ln.get("syls_roman") or ln.get("syls") or []
    blank = {"syls": [], "text": text, "start": ln["start"], "end": ln["end"]}
    if not words or not base:
        return render_pieces(blank)

    theirs, gword, gchar = [], [], []
    for w, word in enumerate(words):
        k, idx = GR.key_map(word)
        theirs.append(k)
        gword.extend([w] * len(k))
        gchar.extend(idx)
    theirs = "".join(theirs)
    mine, syl = [], []
    for i, b in enumerate(base):
        k = GR.key(b[2])
        mine.append(k)
        syl.extend([i] * len(k))
    mine = "".join(mine)
    if not theirs or not mine:
        return render_pieces(blank)

    at: list[int | None] = [None] * len(theirs)
    for a, b, size in SequenceMatcher(None, theirs, mine, autojunk=False).get_matching_blocks():
        for d in range(size):
            at[a + d] = b + d
    anchored = {gword[c] for c in range(len(theirs)) if at[c] is not None}
    owner: list[int | None] = [syl[p] if p is not None else None for p in at]
    last = None
    for c in range(len(owner)):
        if owner[c] is None:
            owner[c] = last
        else:
            last = owner[c]
    nxt = None
    for c in range(len(owner) - 1, -1, -1):
        if owner[c] is None:
            owner[c] = nxt
        else:
            nxt = owner[c]

    atoms = []
    c = 0
    for w, word in enumerate(words):
        n = len(GR.key_map(word)[0])
        if not n:
            atoms.append([w, word, None])
            continue
        cuts, s0 = [], c
        for d in range(n):
            if d and owner[c + d] != owner[c + d - 1]:
                cuts.append(d)
        starts = [0] + cuts
        for j, d in enumerate(starts):
            lo = gchar[c + d] if d else 0
            hi = gchar[c + starts[j + 1]] if j + 1 < len(starts) else len(word)
            frag = word[lo:hi]
            if frag:
                atoms.append([w, frag, owner[c + d]])
        c += n

    out = []
    i = 0
    while i < len(atoms):
        j = i
        while (j + 1 < len(atoms) and atoms[j + 1][2] is not None
               and atoms[j + 1][2] == atoms[i][2]):
            j += 1
        run = atoms[i:j + 1]
        k = run[0][2]
        s, e = (base[k][0], base[k][1]) if k is not None else (None, None)
        if e is not None and s is not None and e < s:
            e = s
        if len(run) > 1 and s is not None and e is not None and e > s:
            total = sum(len(a[1]) for a in run) or 1
            t = s
            for m, a in enumerate(run):
                nx = e if m == len(run) - 1 else t + (e - s) * len(a[1]) / total
                out.append([t, nx, a[0], a[1]])
                t = nx
        else:
            for a in run:
                out.append([s, e, a[0], a[1]])
        i = j + 1

    for i in range(1, len(out)):
        if out[i][0] is not None and out[i - 1][0] is not None and out[i][0] < out[i - 1][0]:
            out[i][0] = out[i - 1][0]
            out[i][1] = max(out[i][0], out[i][1] if out[i][1] is not None else out[i][0])
        if (out[i - 1][1] is not None and out[i][0] is not None
                and out[i - 1][1] > out[i][0]):
            out[i - 1][1] = max(out[i - 1][0], out[i][0])

    timed = {w for s, e, w, _ in out if s is not None} & anchored
    return [
        (s if w in timed else None, e if w in timed else None, txt,
         i + 1 < len(out) and out[i + 1][2] == w)
        for i, (s, e, w, txt) in enumerate(out)
    ]


def prepare(lines: list[dict], min_gap: float) -> list[dict]:
    """Clamp open-ended lines and insert interlude markers between the rest."""
    for i, ln in enumerate(lines):
        if ln["end"] is None and ln["start"] is not None:
            nxt = next(
                (l["start"] for l in lines[i + 1:]
                 if l["start"] is not None and l["start"] > ln["start"]), None
            )
            ln["end"] = nxt if nxt is not None else ln["start"] + 4.0
        ln["pieces"] = render_pieces(ln)
        ln["pieces_roman"] = ln.get("syls_roman") or (
            render_pieces({"syls": [], "text": ln["text_roman"],
                           "start": ln["start"], "end": ln["end"]})
            if ln.get("text_roman") else [])
    if min_gap <= 0 or not any(ln["start"] is not None for ln in lines):
        return lines
    out: list[dict] = []
    prev_end = 0.0
    for ln in lines:
        start = ln["start"]
        if start is not None and start - prev_end >= min_gap:
            out.append({
                "start": prev_end, "end": start, "text": "", "syls": [], "pieces": [],
                "opposite": False, "background": False, "dots": True,
                "syls_roman": [], "pieces_roman": [],
            })
        out.append(ln)
        if ln["end"] is not None:
            prev_end = max(prev_end, ln["end"])
        elif start is not None:
            prev_end = max(prev_end, start)
    return out


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
LINK_PORT = int(os.environ.get("MILD_LYRICS_LINK_PORT", "8778") or 0)


class LiveLink(QObject):
    """A loopback socket the TTML editor talks to.

    The point of it is that a file being timed can be watched against the
    real player, on the real track, without being saved, installed or
    dropped on the window again after every keystroke. It is the drop path
    with the file left out: the editor sends the document it currently has,
    this puts it on screen for the song that is playing, and nothing is
    written anywhere.

    Loopback only, and only ever four messages -- there is no reason for this
    to be reachable from another machine and no reason for it to grow a
    vocabulary. `state` is what the editor listens to: it needs the track and
    the play position the *player* believes in, complete with the offset this
    app applies, or every time it takes would be a few tenths out from what a
    listener actually hears.
    """

    clear = pyqtSignal()
    seek = pyqtSignal(float)

    def __init__(self, view) -> None:
        super().__init__(view)
        self.view = view
        self.server = None
        self.error = ""
        self._pulse = None
        self._was = None
        if not LINK_PORT:
            return
        from PyQt6.QtNetwork import QHostAddress, QTcpServer
        self.server = QTcpServer(self)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close)
        if not self.server.listen(QHostAddress("127.0.0.1"), LINK_PORT):
            self.error = self.server.errorString()
            self.server = None
            return
        self.server.newConnection.connect(self._accept)

    def close(self) -> None:
        """Stop listening. Safe to call twice."""
        if self.server is not None:
            self.server.close()
            self.server = None

    def _accept(self) -> None:
        while self.server and self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.setProperty("buf", "")
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)
        self._watch()

    # ---------------------------------------------------------------- jumps
    def _watch(self) -> None:
        """Tell the editor when the song MOVES, rather than waiting to be asked.

        An editor polling this every tenth of a second is exact while the song
        plays -- both clocks run at 1x from the same instant -- and wrong for
        one poll after a jump, because it is still carrying the last reading
        forward through a seek that has already happened. One poll is 120 ms,
        and a time tapped inside it lands wherever the song used to be.

        There is no need to guess: this side knows the moment it happens.
        """
        if getattr(self, "_pulse", None) is not None:
            return
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._maybe_announce)
        self._pulse.start(50)
        self._was = None

    def _maybe_announce(self) -> None:
        if self.server is None:
            return
        socks = [s for s in self.findChildren(QObject)
                 if s.__class__.__name__ == "QTcpSocket"
                 and s.state() == s.SocketState.ConnectedState]
        if not socks:
            self._was = None
            return
        v = self.view
        now, pos = time.monotonic(), float(v.position())
        state = (v.clock.tid, v.clock.status)
        if self._was is not None:
            was_pos, was_at, was_state = self._was
            drift = pos - (was_pos + (now - was_at
                                      if was_state[1] == "Playing" else 0.0))
            moved = abs(drift) > 0.25 or state != was_state
        else:
            moved = True
        self._was = (pos, now, state)
        if not moved:
            return
        msg = {"ok": True, "tid": v.clock.tid or "", "status": v.clock.status,
               "title": str(v.clock.meta.get("title") or ""),
               "artist": str(v.clock.meta.get("artist") or ""),
               "length": float(v.clock.meta.get("length") or 0.0),
               "pos": pos, "offset": float(v.track_offset()), "at": now,
               "live": bool(v.dropped == v.clock.tid)}
        line = (json.dumps(msg) + "\n").encode("utf-8")
        for sock in socks:
            try:
                sock.write(line)
            except Exception:
                pass

    def _read(self, sock) -> None:
        buf = str(sock.property("buf") or "")
        buf += bytes(sock.readAll()).decode("utf-8", "replace")
        while "\n" in buf:
            row, buf = buf.split("\n", 1)
            if row.strip():
                self._handle(sock, row)
        sock.setProperty("buf", buf)

    def _handle(self, sock, row: str) -> None:
        try:
            msg = json.loads(row)
        except Exception:
            return
        cmd = str(msg.get("cmd") or "")
        out: dict = {"ok": True}
        if cmd == "state":
            v = self.view
            out.update(tid=v.clock.tid or "", status=v.clock.status,
                       title=str(v.clock.meta.get("title") or ""),
                       artist=str(v.clock.meta.get("artist") or ""),
                       length=float(v.clock.meta.get("length") or 0.0),
                       pos=float(v.position()),
                       offset=float(v.track_offset()),
                       at=time.monotonic(),
                       live=bool(v.dropped == v.clock.tid))
        elif cmd == "ttml":
            want = str(msg.get("tid") or "")
            if want and self.view.clock.tid and want != self.view.clock.tid:
                out = {"ok": False, "why": "a different song is playing"}
            else:
                ok = self.view.show_live_lyric(
                    str(msg.get("ttml") or ""),
                    str(msg.get("name") or "the editor"))
                if not ok:
                    out = {"ok": False, "why": "the player could not draw it"}
        elif cmd == "doc":
            body = self.view.body
            if not body:
                out = {"ok": False, "why": "the player has no lyrics loaded"}
            else:
                try:
                    out = {"ok": True, "ttml": SL.render(body, "ttml"),
                           "source": str(getattr(self.view, "source", "") or ""),
                           "tid": self.view.clock.tid or "",
                           "title": str(self.view.clock.meta.get("title") or ""),
                           "artist": str(self.view.clock.meta.get("artist") or "")}
                except Exception as exc:              # noqa: BLE001
                    out = {"ok": False,
                           "why": f"could not render it — {type(exc).__name__}"}
        elif cmd == "clear":
            self.clear.emit()
        elif cmd == "seek":
            try:
                self.seek.emit(float(msg.get("pos")) + self.view.track_offset())
            except (TypeError, ValueError):
                out = {"ok": False, "why": "no position"}
        else:
            out = {"ok": False, "why": f"unknown command {cmd!r}"}
        try:
            sock.write((json.dumps(out) + "\n").encode("utf-8"))
        except Exception:
            pass


# --------------------------------------------------------------------------
class Aligner(QObject):
    """Forced alignment against a song's own audio, off the GUI thread.

    One song at a time and never more, because the thing being rationed is a
    single card's memory -- see local_align.room(). Two of these running at once
    would each have been told there was room for them.

    It is kept off the Fetcher's thread for the same reason it is kept off the
    GUI's: a lookup takes a second or two and an alignment takes two or three
    minutes, and sharing a thread would mean every track change waited behind
    somebody's alignment.

    Two kinds of job come in. One the user asked for, on the song they are
    listening to, which runs whatever it costs. One this queued speculatively
    for a track coming up, which gets out of the way at the first sign it is
    not wanted: it is skipped if the card is busy, skipped if the song already
    has word timing from somewhere, and skipped if it has been aligned before.
    """
    finished_track = pyqtSignal(str, bool, str)
    progress = pyqtSignal(str)

    def __init__(self, view_settings) -> None:
        super().__init__()
        self._settings = view_settings
        self._jobs: list = []
        self._done: set = set()
        self.busy: str = ""
        self.stop = False
        self._abort = False
        self._lock = threading.Lock()

    def request(self, tid: str, meta: dict, asked: bool = False) -> bool:
        """Queue a track. False if it was already in hand or already done."""
        if not tid:
            return False
        with self._lock:
            if tid == self.busy or any(j[0] == tid for j in self._jobs):
                return False
            if not asked and tid in self._done:
                return False
            if asked:
                self._jobs.insert(0, (tid, dict(meta or {}), True))
            else:
                self._jobs.append((tid, dict(meta or {}), False))
        return True

    def forget_tried(self, tid: str) -> None:
        with self._lock:
            self._done.discard(tid)

    def cancel(self) -> str:
        """Abandon the job in hand. The track it was on, or "".

        Asking is all this does: the worker is several minutes inside two
        models and stops where it next looks, which is between windows of the
        alignment and before the separation. Demucs' own call cannot be
        interrupted, so a job that has just started separating takes until
        that finishes -- a minute at worst, against never, which is what
        pressing the key used to do while anything else was running.
        """
        with self._lock:
            if not self.busy:
                return ""
            self._abort = True
            return self.busy

    def clear(self) -> int:
        """Drop everything waiting, asked-for jobs included. How many went.

        For switching the aligner off, which is the one case where a job the
        user asked for is no longer wanted either -- keep_only() deliberately
        spares those, because it is about the queue having moved on.
        """
        with self._lock:
            n, self._jobs = len(self._jobs), []
            return n

    def keep_only(self, tids) -> int:
        """Drop queued-ahead jobs for tracks that are no longer coming up.

        The queue is offered to this every time the player reports one, and
        what it reported last time may have nothing to do with what is playing
        now -- a skip, a new playlist, a jumped-to song. Without this the
        worker went on grinding through a queue that had been replaced, which
        came right on its own only because the stale jobs eventually ran out.

        A job the user asked for is never dropped. It is not speculative and
        it is not about the queue.
        """
        with self._lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j[2] or j[0] in tids]
            return before - len(self._jobs)

    def run(self) -> None:
        while not self.stop:
            with self._lock:
                job = self._jobs.pop(0) if self._jobs else None
                self.busy = job[0] if job else ""
                self._abort = False
            if job is None:
                time.sleep(0.5)
                continue
            tid, meta, asked = job
            try:
                ok, said = self._align(tid, meta, asked)
            except Exception as exc:
                ok, said = False, f"{type(exc).__name__}: {exc}"
            with self._lock:
                stopped, self.busy, self._abort = self._abort, "", False
                if not stopped:
                    self._done.add(tid)
            if said and not self.stop and not stopped:
                self.finished_track.emit(tid, ok, said)

    def _sync_align(self, audio: str, doc: dict, cfg: dict):
        """This project's own model, on the copy the player already has.

        The document comes from the chain and only its TIMES are replaced, so
        whatever the player decided to show is what gets timed -- the model is
        not allowed to change the words.
        """
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from sync import generate as GEN
        want = "cuda" if cfg["device"] != "cpu" else "cpu"
        try:
            return GEN.against(doc, audio, _sync_ckpt(bool(cfg["stems"])),
                               device=want,
                               stem=bool(cfg["stems"]), spare=cfg["spare"],
                               log=lambda m: None,
                               stop=lambda: self._abort,
                               keep=not cfg.get("free"))
        except Exception as exc:                        # noqa: BLE001
            LA_err = f"the sync model: {type(exc).__name__}: {exc}"
            _sync_align.last_error = LA_err
            return None

    def _align(self, tid: str, meta: dict, asked: bool) -> tuple[bool, str]:
        """One track. (worked, what to say) -- an empty message says nothing."""
        import local_align as LA
        if LS.aligned(tid):
            return True, ""
        cfg = self._settings()
        if not asked:
            where, _win, why = LA.room(cfg["device"], LA.ALIGN_COST,
                                       LA.ALIGN_WINDOW, cfg["spare"])
            if where == "cpu":
                with self._lock:
                    self._done.discard(tid)
                return False, ""
        if not asked:
            names = [n for n in cfg["order"] if n in cfg["sources"] and n != "local"]
            got = (LS.fallback(tid, meta, "none", set(names), order=names)
                   if names else None)
            if got and LS.quality(SL.payload(got[0])) == "syllable":
                return False, ""
        doc = LA.genius_doc(cfg["token"], meta)
        if not doc:
            return False, ("Genius has no lyrics for this one" if asked else "")
        title = meta.get("title") or tid
        self.progress.emit(f"aligning {title}…")
        query = f"{meta.get('artist', '')} {title}".strip()
        with LA.fetched(query, float(meta.get("length") or 0.0),
                        artist=str(meta.get("artist") or ""), tid=tid) as audio:
            if not audio:
                return False, (f"no copy of {title}: {LA.fetched.last_error}"
                               if asked else "")
            if cfg.get("model", "sync") == "sync" and _sync_ckpt(cfg["stems"]):
                out = self._sync_align(audio, doc, cfg)
            else:
                out = LA.align(audio, doc, stems=cfg["stems"], want=cfg["device"],
                               spare=cfg["spare"],
                               target=float(meta.get("length") or 0.0),
                               stop=lambda: self._abort)
        if cfg.get("free"):
            LA.release()
        if out is None:
            if self._abort:
                return False, ""
            return False, (f"{title}: {LA.align.last_error}" if asked else "")
        if not LS.save_aligned(tid, out):
            return False, "could not save the alignment"
        LS.forget(tid)
        lines = LS._items(SL.payload(out))
        timed = sum(1 for it in lines
                    if isinstance(it.get("Lead"), dict) and it["Lead"].get("Syllables"))
        return True, f"aligned {title} — {timed}/{len(lines)} lines"


class LyricsView(QWidget):
    art_ready = pyqtSignal(object)
    font_ready = pyqtSignal(str)

    def __init__(self, args) -> None:
        super().__init__()
        self.args = args
        self.offset = args.offset
        self.offsets: dict[str, float] = {} if args.no_persist else dict(load_offsets())
        self.est_raw: dict[str, dict] = {} if args.no_persist else load_est()
        self.est: dict = {}
        self.est_tid: str | None = None
        self._said_outranked: str = ""
        self._cal_gen = 0
        self._cal_at = -1
        self._cal: tuple[float, int] = (0.0, 0)
        self.romaji_fix: dict[str, dict] = {} if args.no_persist else load_romaji()
        self.genius_fix, self.genius_rev = ({}, {}) if args.no_persist else load_genius()
        self.ne_fix: dict[str, dict] = {}
        self.genius_token = "" if args.no_persist else load_token()
        self.align_on = getattr(args, "align_on", DEFAULTS["align_on"])
        self.align_model = getattr(args, "align_model", "sync")
        if self.align_model not in ALIGN_MODELS:
            self.align_model = ALIGN_MODELS[0]
        self.align_stems = args.align_stems
        self.align_device = args.align_device
        self.align_spare = args.align_spare
        self.align_free = getattr(args, "align_free", DEFAULTS["align_free"])
        self.align_ahead = args.align_ahead
        self.genius_busy = False
        self.genius_quiet = False
        self.artists: dict[str, list] = {}
        self.albums: dict[str, dict] = {}
        self.detail: dict | None = None
        self.detail_stack: list = []
        self.detail_scroll = 0.0
        self.detail_rows: list = []
        self.editing = False
        self.edit_mode = "romaji"
        self.edit_text = ""
        self.edit_caret = 0
        self.edit_sel: int | None = None
        self.edit_pristine = True
        self.paste_rect: QRectF | None = None
        self.edit_for = ""
        self.font_scale = args.font_scale
        self.blur_scale = args.blur
        self.glow_scale = args.glow
        self.show_panel = args.art
        self.view_mode = args.view_mode
        self.show_volume = args.volume_bar
        self.motion_art = args.motion_art
        self.bg_mode = args.bg
        self.bg_dim = args.bg_dim
        self.bg_motion = args.bg_motion
        self.align = args.align
        self.pop = args.pop
        self.pop_min = args.pop_min
        self.edge = args.edge
        self.focus = args.focus
        self.line_spacing = args.line_spacing
        self.interlude = args.interlude
        self.resync = args.resync
        self.auto_time = args.auto_time
        self.beat_scale = args.beat
        self.roman = args.roman
        self.genius_auto = args.genius_auto
        self.furigana = args.furigana
        self.src_spicy = args.src_spicy
        self.src_amll = args.src_amll
        self.src_youly = args.src_youly
        self.src_netease = args.src_netease
        self.src_lrclib = args.src_lrclib
        self.src_blend = args.src_blend
        self.src_local = args.src_local
        self.ne_graft = args.ne_graft
        self.spin = args.spin
        self.zero_g = args.zero_g
        self.clouds = args.clouds
        self.show_now_card = args.browse_now
        self.browse_art = args.browse_art
        self.drift: dict = {}
        self.cloudy: dict = {}
        self.drift_at = 0.0
        self.source = ""
        self.genius_tried: set[str] = set()
        self.beat = Beat()
        self._sung = parse_color(args.sung_color, TEXT)
        self.duet_color = args.duet_color
        self._duet_rgb = (None if self.duet_color in DUET_MODES
                          else parse_color(self.duet_color, None))
        self.lines: list[dict] = []
        self.raw: list[dict] = []
        self.body = None
        self.synced = False
        self.dropped: str | None = None
        self.dropped_art: str | None = None
        self.status_text = "Connecting…"
        self.track_at = time.monotonic()
        self.clock = Clock(make_transport(args.port, getattr(args, 'player', 'auto')))
        self.clock.unpause_delay = float(args.unpause_delay)
        self.scroll = 0.0
        self.scroll_target = 0.0
        self.content_h = 0.0
        self.user_scroll_until = 0.0
        self.browse = 0.0
        self.activation: dict[int, float] = {}
        self.line_rects: list[tuple[int, float, float, float, float]] = []
        self.hover_idx = -1
        self.bar_rect: QRectF | None = None
        self.drag_frac: float | None = None
        self.vol_rect: QRectF | None = None
        self.vol_drag: float | None = None
        self.hot: list = []
        self.show_help = False
        self.show_info = False
        self.show_search = False
        self.query = ""
        self.hits: list[dict] = []
        self.hit_idx = 0
        self.hit_top = 0
        self.search_rects: list[tuple] = []
        self.index = LyricIndex()
        self.index_n = 0
        self.indexing = False
        self.show_menu = False
        self.view = "lyrics"
        self.browse_tab = "home"
        self.browse_scroll = 0.0
        self.browse_scroll_target = 0.0
        self.browse_rects: list[tuple] = []
        self.browse_hover: tuple | None = None
        self.shelves: list[dict] = []
        self.bq = ""
        self.bq_hits: list[dict] = []
        self.bq_cat: list[dict] = []
        self.bq_local: list[dict] = []
        self.bq_sel = 0
        self.bq_busy = False
        self.recents_tracks: list[dict] = []
        self.recents_ctx: list[dict] = []
        self.recents_at = 0.0
        self.queue_items: list[dict] = []
        self.queue_cur: dict | None = None
        self.queue_at = 0.0
        self.suggest: dict = {}
        self.discover: dict = {}
        self.discover_at = 0.0
        self.suggest_for = ""
        self._browse_tid: str | None = None
        self.backfill_n = self.backfill_total = 0
        self.on_top = False
        self.menu_idx = 0
        self.menu_rects: list[tuple] = []
        self.tab_rects: list[tuple] = []
        self.toast_text = ""
        self.toast_until = 0.0
        self.last_move = time.monotonic()
        self.skip_at = 0.0
        self.quit_requested = False
        self.mouse_pos = QPointF(-1, -1)
        self._cursor = Qt.CursorShape.ArrowCursor
        self._idle_frames = 0

        self.layout_cache: dict = {}
        self.pix_cache: dict = {}
        self.art_bg: QPixmap | None = None
        self.art_full: QPixmap | None = None
        self.art_url = ""
        self.art_gen = 0
        self.motion = MotionArt()
        self.motion_frames: list = []
        self.motion_key = ""
        self.motion_at = 0.0
        self._marq: dict = {}
        self._marq_live = False
        self.palette = [QColor(120, 60, 80), QColor(70, 60, 120), QColor(120, 90, 60)]
        self._glow_key = None
        self._glow_pm: QPixmap | None = None
        self._fade_key = None
        self._fade_pm: QPixmap | None = None
        self._scene_key = None
        self._scene_pm: QPixmap | None = None
        self._scene_at = 0.0
        self._section = 0
        _disk = {} if args.no_persist else load_settings()
        _gfix, _grev = ({}, {}) if args.no_persist else load_genius()
        self._saved: tuple | None = (
            {k: _disk.get(k, DEFAULTS[k]) for k in DEFAULTS},
            {} if args.no_persist else dict(load_offsets()),
            {} if args.no_persist else load_romaji(),
            "" if args.no_persist else load_token(),
            _gfix, _grev,
        )
        self._save_at = 0.0

        self.setMinimumSize(420, 320)
        self.setWindowTitle(f"{APP_NAME} — {os.getpid()}")
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        raw_order = [n.strip() for n in str(args.src_order or "").split(",")]
        self.src_order = [n for n in raw_order if n in SRC_LABEL]
        self.src_order += [n for n in SRC_DEFAULT if n not in self.src_order]
        self.font_name = args.font or ""
        self.font_weight: int | None = None
        self.load_cached_fonts()
        if not self.resolve_font():
            threading.Thread(target=self._font_later, daemon=True).start()
        self.art_ready.connect(self.on_art)
        self.font_ready.connect(self.on_font_ready)

        self.art_cache = ArtCache()
        self.art_cache.loaded.connect(self.on_thumb)
        self.motion.ready.connect(self.on_motion)

        self.fetcher = Fetcher(args.port, args.split, args.split_threshold)
        self.fetcher.ready.connect(self.on_lyrics)
        self.fetcher.beat_ready.connect(self.on_beat)
        self.fetcher.index_ready.connect(self.on_index)
        self.fetcher.index_progress.connect(self.on_index_progress)
        self.fetcher.genius_ready.connect(self.on_genius)
        self.fetcher.ne_roman_ready.connect(self.on_ne_roman)
        self.fetcher.album_ready.connect(self.on_album)
        self.fetcher.artists_ready.connect(self.on_artists)
        self.fetcher.recents_ready.connect(self.on_recents)
        self.fetcher.catsearch_ready.connect(self.on_catsearch)
        self.fetcher.backfill_ready.connect(self.on_backfill)
        self.fetcher.backfill_progress.connect(self.on_backfill_progress)
        self.fetcher.queue_ready.connect(self.on_queue)
        self.fetcher.suggest_ready.connect(self.on_suggest)
        self.fetcher.discover_ready.connect(self.on_discover)
        self.fetch_thread = threading.Thread(target=self.fetcher.run, daemon=True)
        self.fetch_thread.start()

        self.aligner = Aligner(self.align_settings)
        self.aligner.finished_track.connect(self.on_aligned)
        self.aligner.progress.connect(self.toast)
        self.align_thread = threading.Thread(target=self.aligner.run, daemon=True)
        self.align_thread.start()
        self._ahead_at = 0.0

        self.link = LiveLink(self)
        self.link.clear.connect(self.drop_live_lyric)
        self.link.seek.connect(lambda p: self.clock.seek(p))

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(POLL_MS)
        self.fps_cap = args.fps_cap
        self.eff_hz = 60.0
        self._watched_screen = None
        self._screen_hooked = False
        self.frame_timer = QTimer(self)
        self.frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.frame_timer.timeout.connect(self.tick)
        self.retune_frames()
        self.poll()

    # -- the frame rate follows the screen the window is actually on -----
    def retune_frames(self, *_) -> None:
        """Run the frame timer at an integer divisor of the current refresh.

        A fixed 16ms matches no real panel. On a 60Hz output it asks for 62.5
        frames the compositor will only present 60 of, and the leftover shows
        up in a word sweep as a stutter every few seconds; on a 240Hz one it
        leaves most of the panel unused anyway. Dividing the refresh down keeps
        every step the same length, which is what actually reads as smooth.
        """
        scr = self.screen() or QApplication.primaryScreen()
        hz = scr.refreshRate() if scr is not None else 0.0
        if hz <= 0:
            hz = 60.0
        n = max(1, math.ceil(hz / max(1.0, self.fps_cap)))
        self.eff_hz = hz / n
        self.frame_timer.setInterval(max(1, round(1000.0 / self.eff_hz)))
        if not self.frame_timer.isActive():
            self.frame_timer.start()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        wh = self.windowHandle()
        if wh is not None and not self._screen_hooked:
            self._screen_hooked = True
            wh.screenChanged.connect(self.follow_screen)
        self.follow_screen(self.screen())

    def follow_screen(self, scr) -> None:
        """Retime, and carry the refresh subscription onto the new screen.

        Dragging the window between panels is one way the rate changes; the
        other is the mode changing under a window that never moved, which only
        the screen's own signal reports.
        """
        if scr is not self._watched_screen:
            if self._watched_screen is not None:
                try:
                    self._watched_screen.refreshRateChanged.disconnect(
                        self.retune_frames)
                except TypeError:
                    pass
            if scr is not None:
                scr.refreshRateChanged.connect(self.retune_frames)
            self._watched_screen = scr
        self.retune_frames()

    # -- fonts sized off the window, like the web view -------------------
    def lyric_px(self) -> float:
        return max(19.0, min(46.0, self.width() * 0.0255)) * self.font_scale

    def _font_later(self) -> None:
        """Off-thread half of the startup font fetch. Only downloads here; the
        registering and the repaint have to happen where Qt lives."""
        fam, weight = split_font(self.font_name)
        path = fetch_font(fam, weight) if fam else None
        if path is not None:
            self.font_ready.emit(str(path))

    def on_font_ready(self, path: str) -> None:
        if QFontDatabase.addApplicationFont(path) < 0:
            return
        if not self.resolve_font():
            return
        self.layout_cache.clear()
        self.pix_cache.clear()
        self._marq.clear()
        self.toast(f"font: {self.family}")
        self.update()

    def load_cached_fonts(self) -> None:
        """Register anything previously downloaded, before the first lookup."""
        try:
            for path in sorted(FONT_DIR.glob(f"*.v{FONT_REV}.ttf")):
                QFontDatabase.addApplicationFont(str(path))
            for stale in FONT_DIR.glob("*.ttf"):
                if f".v{FONT_REV}." not in stale.name:
                    stale.unlink(missing_ok=True)
        except Exception:
            pass

    def resolve_font(self, online: bool = False) -> bool:
        """Settle on a family: the one asked for, else the first stocked one.

        Returns whether the requested name was actually found. Qt substitutes
        silently for a family it does not have, so a typo would otherwise look
        like the setting had simply been ignored.

        `online` allows one trip to Google Fonts for a name this machine does
        not have. Off by default so startup never waits on the network -- a font
        fetched once is cached and registered locally from then on.
        """
        want, self.font_weight = split_font(self.font_name)

        def pick():
            have = set(QFontDatabase.families())
            if not want:
                return None
            if want in have:
                return want
            fold = {f.lower(): f for f in have}
            return fold.get(want.lower())

        got = pick()
        if got is None and want and online:
            path = fetch_font(want, self.font_weight)
            if path is not None:
                idx = QFontDatabase.addApplicationFont(str(path))
                fams = QFontDatabase.applicationFontFamilies(idx) if idx >= 0 else []
                if fams:
                    self.family = min(fams, key=len)
                    return True
                got = pick()
        if got is not None:
            self.family = got
            return True
        have = set(QFontDatabase.families())
        self.family = next((f for f in FONT_STACK if f in have), FONT_STACK[-1])
        return not want

    def _weight(self, fallback):
        """The pinned weight, or the one this call asked for.

        Pinning replaces the heaviest step rather than flattening everything:
        the design leans on the difference between the lyrics and the chrome
        around them, and a single weight everywhere loses that.
        """
        if self.font_weight is None:
            return fallback
        return QFont.Weight(max(1, min(900, self.font_weight)))

    @staticmethod
    def _weigh(f: QFont, w) -> QFont:
        """Set a weight in both of the ways Qt needs to be told.

        setWeight alone is enough for an ordinary family, and enough for a
        single-axis variable file. On a multi-axis one -- Roboto ships as
        Roboto[wdth,wght] -- it collapses to two steps: 100 and 400 draw
        identically, and so do 700 and 900. Driving the wght axis directly gives
        the range back. Fonts without the axis ignore it.
        """
        f.setWeight(w)
        if WGHT_AXIS is not None:
            try:
                f.setVariableAxis(WGHT_AXIS, float(int(w)))
            except Exception:
                pass
        return f

    def lyric_font(self, background: bool = False) -> QFont:
        f = QFont(self.family, int(self.lyric_px() * (0.66 if background else 1.0)))
        return self._weigh(f, self._weight(QFont.Weight.Black))

    def ui_font(self, px: float, weight=QFont.Weight.DemiBold) -> QFont:
        f = QFont(self.family, max(8, int(px)))
        return self._weigh(f, self._weight(weight)
                           if weight >= QFont.Weight.Black else weight)

    # -- data ------------------------------------------------------------
    def poll(self) -> None:
        prev = self.clock.tid
        self.clock.poll(self.resync)
        if (self.align_on and self.align_ahead and self.clock.status == "Playing"
                and time.monotonic() - self._ahead_at > 60.0):
            self._ahead_at = time.monotonic()
            self.fetcher.request_queue()
        if getattr(self.args, "track", None):
            self.clock.tid = self.args.track
        if self.clock.tid and self.clock.tid != prev:
            self.reset_track("Loading lyrics…")
            handed_over = prev is not None and time.monotonic() - self.skip_at > 3.0
            if handed_over and self.resync:
                QTimer.singleShot(800, self.clock.resync)
        elif self.clock.tid and not self.lines:
            self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                                 self.source_order(), self.ne_graft)
        length = self.clock.meta.get("length", 0.0)
        left = length - self.clock.position() if length else 99.0
        if self.clock.status != "Playing":
            want = POLL_MS_PAUSED
        else:
            want = POLL_MS_EDGE if left < 3.0 or not self.lines else POLL_MS
        if self.poll_timer.interval() != want:
            self.poll_timer.setInterval(want)
        if self.clock.tid and self.clock.meta.get("title") and self.index.songs:
            self.index.note_title(self.clock.tid, self.clock.meta["title"],
                                  self.artist())
        if self.view == "browse" and self.clock.tid != self._browse_tid:
            self._browse_tid = self.clock.tid
            self.build_home()
            self.fetcher.request_suggest("")
            if self.browse_tab == "queue":
                self.fetcher.request_queue()
        url = self.clock.meta.get("art", "")
        if url and url != self.art_url:
            self.art_url = url
            threading.Thread(target=self._load_art, args=(url,), daemon=True).start()
        album = self.clock.meta.get("album", "")
        title = self.clock.meta.get("title", "")
        if self.motion_art and (album or title):
            lead = (split_artists(title, self.credits())[0]
                    or [{}])[0].get("name", "")
            key = f"{lead}|{album or title}"
            if key != self.motion_key:
                self.motion_key, self.motion_frames = key, []
                self.motion.want(key, lead, album, title)

    def apply_romaji_fixes(self) -> None:
        """Your corrections win over anything derived.

        No romanizer can infer a reading the lyricist invented -- 運命 sung as
        "sadame" exists only in that song. Fix a line once and it stays fixed.
        """
        tid = self.clock.tid or ""
        auto = self.genius_fix.get(tid, {})
        hand = self.romaji_fix.get(tid, {})
        ne = self.ne_fix.get(tid, {})
        if not auto and not hand and not ne:
            return
        for ln in self.lines:
            text = ln["text"].strip()
            fix = hand.get(text)
            if fix is None and SL.CJK.search(text):
                fix = auto.get(text) or ne.get(text)
            if fix:
                ln["text_roman"] = fix
                ln["pieces_roman"] = retime_roman(ln, fix)

    def line_readings(self) -> list[str]:
        """Current romaji per line, indexed to match self.lines.

        A line already in Latin script has no romanisation, and sending an empty
        string left a hole in the sequence Genius is aligned against -- so
        「鬼とチャンバラ」+ "the lyrical chainsaw massacre", which Genius prints
        as one line, had only the first half to match on and fell under the
        threshold. Such a line is its own reading.
        """
        out = []
        for ln in self.lines:
            if ln.get("dots") or not ln["text"].strip():
                out.append("")
            else:
                out.append("".join(t + ("" if p else " ")
                                   for _, _, t, p in (ln["pieces_roman"] or [])).strip()
                           or ln["text"].strip())
        return out

    def fetch_genius(self, quiet: bool = False) -> None:
        """Pull a human-written romanisation and line it up with ours.

        `quiet` is the automatic path: it should not narrate a track it had no
        business looking up in the first place.
        """
        if not self.genius_token:
            if not quiet:
                self.toast("add your Genius token in the settings menu (M)")
            return
        if not self.clock.tid or not self.lines:
            if not quiet:
                self.toast("no track loaded")
            return
        if not any(SL.CJK.search(l["text"]) for l in self.lines):
            if not quiet:
                self.toast("nothing to romanise on this track")
            return
        if self.genius_busy:
            return
        self.genius_busy = True
        self.genius_quiet = quiet
        m = self.clock.meta
        if not quiet:
            self.toast("asking Genius…")
        self.fetcher.request_genius(self.genius_token, self.clock.tid,
                                    m.get("title", ""), self.artist(),
                                    self.line_readings())
        if not self.ne_fix.get(self.clock.tid or ""):
            self.fetcher.request_ne_roman(self.clock.tid, self.fetch_meta())

    def on_genius(self, tid, mapping, name) -> None:
        self.genius_busy = False
        quiet, self.genius_quiet = getattr(self, "genius_quiet", False), False
        if tid != self.clock.tid:
            return
        if not mapping:
            if not quiet:
                self.toast("no Genius romanisation found")
            return
        fixes = {}
        for i, text in mapping.items():
            if 0 <= i < len(self.lines):
                fixes[self.lines[i]["text"].strip()] = text
        if fixes:
            self.genius_fix[tid] = fixes
            self.genius_rev[tid] = GR.REVISION
        else:
            self.genius_fix.pop(tid, None)
            self.genius_rev.pop(tid, None)
        self.rebuild_lines()
        if not quiet:
            total = sum(1 for l in self.lines if not l.get("dots") and l["text"].strip())
            self.toast(f"Genius: {len(mapping)} of {total} lines matched")

    def on_ne_roman(self, tid, got) -> None:
        if tid != self.clock.tid or not isinstance(got, dict) or not got:
            if tid == self.clock.tid:
                self.toast("no romanisation found")
            return
        self.ne_fix[tid] = got
        self.rebuild_lines()
        hit = sum(1 for ln in self.lines if ln["text"].strip() in got)
        self.toast(f"NetEase: {hit} lines romanised")

    def build_lines(self) -> list[dict]:
        """The timeline as it is actually drawn: interludes folded in, and the
        credits sitting under the last line the way Spicy Lyrics puts them.

        The credits ride as one more row rather than as chrome painted over the
        bottom of the window, so they scroll with the song and stop where it
        stops. Empty `text` on purpose -- every place that walks the lines
        looking for something to copy, search, seek to or correct already skips
        a row with no words in it, so none of them need to learn about this.
        """
        lines = prepare(self.raw, self.interlude)
        rows = self.credit_rows()
        if rows:
            lines.append({"start": None, "end": None, "text": "", "syls": [],
                          "pieces": [], "opposite": False, "background": False,
                          "credits": rows, "syls_roman": [], "pieces_roman": []})
        return lines

    def rebuild_lines(self) -> None:
        """Re-fold interludes at the current gap setting."""
        if not self.raw:
            return
        self.lines = self.build_lines()
        self.apply_romaji_fixes()
        self.layout_cache.clear()
        self.pix_cache.clear()
        self.activation.clear()
        self.line_rects = []

    # ---------------------------------------------------------- dropped files
    def dragEnterEvent(self, ev) -> None:            # noqa: N802 (Qt name)
        if ev.mimeData().hasUrls() and any(
                _droppable(u) for u in ev.mimeData().urls()):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev) -> None:             # noqa: N802 (Qt name)
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:                 # noqa: N802 (Qt name)
        for url in ev.mimeData().urls():
            path = url.toLocalFile()
            kind = _droppable(url)
            if kind == "lyric" and self.show_dropped_lyric(path):
                ev.acceptProposedAction()
                return
            if kind == "image" and self.show_dropped_art(path):
                ev.acceptProposedAction()
                return
        self.toast("nothing in that I can read")

    def timeline_of(self, body):
        """A parsed document as drawable lines, split the way the app is set.

        The syllable-splitting settings live on the FETCHER, not here -- it is
        the thing that was given them at startup and the thing that normally
        builds timelines. Reading them off `self` silently raised
        AttributeError inside the two `except Exception` blocks below, so a
        dropped file reported "could not read that file" whatever was in it.
        """
        return SL.timeline(body, split=self.fetcher.split,
                           threshold=self.fetcher.threshold) if body else None

    def show_dropped_lyric(self, path: str) -> bool:
        """Put a TTML from disk on screen, for as long as this song plays."""
        try:
            text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
            if pathlib.Path(path).suffix.lower() in (".lrc", ".elrc"):
                body = LS.parse_lrc(text)
            else:
                body = LS.parse_ttml(text)
            lines = self.timeline_of(body)
        except Exception as exc:                       # noqa: BLE001
            self.toast(f"could not read that file — {type(exc).__name__}: {exc}")
            return False
        if not lines:
            self.toast("no timed lines in that file")
            return False
        self.dropped = self.clock.tid
        self.on_lyrics(self.clock.tid, lines, body, force=True)
        timed = sum(1 for ln in lines if ln.get("start") is not None)
        self.toast(f"{pathlib.Path(path).name} — {timed}/{len(lines)} lines timed")
        return True

    def show_live_lyric(self, xml: str, name: str = "the editor") -> bool:
        """A document pushed over the live link, shown the way a drop is.

        Quiet on purpose: this arrives on every edit, and a toast per
        keystroke would cover the words being edited. The one thing it does
        say is when it could not read what it was sent, because an editor
        that has stopped updating the screen and an editor whose file no
        longer parses look identical from the other end.
        """
        try:
            body = LS.parse_ttml(xml)
            lines = self.timeline_of(body)
        except Exception as exc:                       # noqa: BLE001
            self.toast(f"{name}: could not read that — "
                       f"{type(exc).__name__}: {exc}")
            return False
        if not lines:
            self.toast(f"{name}: no lines in that")
            return False
        if self.dropped != self.clock.tid:
            self.toast(f"following {name}")
        self.dropped = self.clock.tid
        self.on_lyrics(self.clock.tid, lines, body, force=True)
        return True

    def drop_live_lyric(self) -> None:
        """Let go of the editor's document and put the song's own back."""
        if self.dropped is None:
            return
        self.dropped = None
        self.body = None
        self.toast("back to this song's own lyrics")

    def show_dropped_art(self, path: str) -> bool:
        """Use a picture from disk as this song's cover, until it changes."""
        img = QImage()
        if not img.load(path):
            self.toast("could not read that picture")
            return False
        blurred = img.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                             Qt.TransformationMode.SmoothTransformation)
        for _ in range(4):
            blurred = blurred.scaled(blurred.width() * 2, blurred.height() * 2,
                                     Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        self.on_art((img, blurred, palette_of(img)))
        self.dropped_art = self.clock.tid
        self.toast(f"cover from {pathlib.Path(path).name}")
        return True

    def reset_track(self, status: str) -> None:
        self.dropped = self.dropped_art = None
        self.lines, self.raw, self.body, self.synced = [], [], None, False
        self.track_at = time.monotonic()
        self.beat.clear()
        self.est, self.est_tid = {}, None
        self._section = 0
        self.layout_cache.clear()
        self.pix_cache.clear()
        self.activation.clear()
        self.line_rects = []
        self._marq.clear()
        self.scroll = self.scroll_target = self.content_h = 0.0
        self.hover_idx = -1
        self.status_text = status
        if self.clock.tid:
            self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                                 self.source_order(), self.ne_graft)

    def _load_art(self, url: str) -> None:
        """Runs off the GUI thread, so it may only touch QImage -- QPixmap is
        documented as main-thread only and crashes under some Qt backends."""
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                data = r.read()
            img = QImage()
            if not img.loadFromData(data):
                return
            blurred = img.scaled(
                40, 40, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            for _ in range(4):
                blurred = blurred.scaled(
                    blurred.width() * 2, blurred.height() * 2,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self.art_ready.emit((img, blurred, palette_of(img)))
        except Exception:
            pass

    def on_art(self, triple) -> None:
        img, blurred, palette = triple
        self.art_full = QPixmap.fromImage(img)
        self.art_bg = QPixmap.fromImage(blurred)
        self.palette = palette
        self.art_gen += 1

    def nudge_offset(self, delta: float) -> None:
        """[ and ] tune the TRACK you are listening to. A song that is mastered
        a little late needs its own correction, not a global one that then
        breaks every other song.

        Correcting a track by hand also retires the measured offset for it. Not
        because the measurement was wrong, but because it has been superseded by
        somebody who can actually hear the song, and two corrections stacking on
        one track would be twice the intended fix. The measurement is kept, and
        goes on to serve as one of the reference points calibration() reads.
        """
        tid = self.clock.tid
        if not tid:
            self.offset = round(self.offset + delta, 3)
            self.toast(f"global offset {self.offset:+.2f}s")
            return
        base = self.offsets.get(tid, self.auto_offset(tid))
        self.offsets[tid] = round(base + delta, 3)
        if abs(self.offsets[tid]) < 1e-6:
            self.offsets.pop(tid, None)
        self._cal_gen += 1
        self.toast(f"this track {self.offsets.get(tid, 0.0):+.2f}s "
                   f"(total {self.track_offset():+.2f}s)")

    def calibration(self) -> tuple[float, int]:
        """What to subtract from every raw measurement, and how sure of it.

        See calibrate() for why a raw measurement is not yet an answer. This is
        the wrapper that feeds it the two things it compares: everything the
        estimator has read, and every track the user has since corrected by ear.

        track_offset() reaches this on every paint, so it is memoised against a
        counter the two contributing dicts bump when they change -- the store of
        measurements grows to a row per track played and walking it sixty times
        a second to re-derive a number that moves once an evening would be a
        waste. Only the hand-corrected tracks are looked up, which is the small
        side of the intersection by a wide margin.
        """
        if self._cal_at != self._cal_gen:
            raw = {t: self.est_raw[t]["delta"]
                   for t in self.offsets if t in self.est_raw}
            self._cal, self._cal_at = calibrate(raw, self.offsets), self._cal_gen
        return self._cal

    def auto_offset(self, tid: str) -> float:
        """The measured correction for a track, or 0.0 where there is none to
        apply -- no reading, not a confident one, or nothing to calibrate it
        against yet. A hand correction on the track beats all of it.

        The confidence gate is doing real work here and is deliberately strict.
        A wrong offset applied silently is worse than no offset at all: the
        lyrics were merely out before, and now they are out and the program is
        insisting otherwise.
        """
        if not tid or not self.auto_time or tid in self.offsets:
            return 0.0
        got = self.est_raw.get(tid)
        if not got or got["conf"] < EST_CONF_MIN:
            return 0.0
        bias, n = self.calibration()
        if n < CAL_MIN:
            return 0.0
        return round(got["delta"] - bias, 3)

    def measure_offset(self) -> None:
        """Read this track's timing against Spotify's analysis of it, once.

        Both halves have to have arrived -- the lines and the analysis land from
        different requests on different threads -- so this is called from both
        and does nothing until it has the pair. The result is cached against the
        track id, so it survives a pause, a scrub, and the next thousand frames.
        """
        tid = self.clock.tid
        if not tid or self.est_tid == tid or not self.raw or not self.beat.segs:
            return
        self.est_tid = tid
        got = estimate_offset(self.raw, self.beat)
        if got:
            self.est_raw[tid] = got
            self._cal_gen += 1
        self.est = self.est_raw.get(tid, {})

    def on_index_progress(self, n: int) -> None:
        self.index_n = n

    @property
    def unpause_delay(self) -> float:
        return self.clock.unpause_delay

    @unpause_delay.setter
    def unpause_delay(self, v: float) -> None:
        self.clock.unpause_delay = max(0.0, float(v))

    def track_offset(self) -> float:
        """Global offset plus whatever this particular track needed.

        The per-track part is the hand correction where there is one and the
        measured one otherwise -- never both, or a track fixed by ear would be
        fixed twice. auto_offset() enforces that; this stays a plain sum so that
        everywhere already subtracting it keeps working unchanged.
        """
        tid = self.clock.tid or ""
        return self.offset + self.offsets.get(tid, self.auto_offset(tid))

    def on_beat(self, tid: str, data) -> None:
        if tid != self.clock.tid:
            return
        if not self.beat.load(data or {}, self.clock.meta.get("length", 0.0)):
            self.beat.clear()
        self.measure_offset()

    def beat_energy(self) -> float:
        if not self.beat_scale or self.drag_frac is not None:
            return 0.0
        if self.clock.status != "Playing" and getattr(self.args, "freeze", None) is None:
            return 0.0
        return self.beat.energy(self.position()) * self.beat_scale

    def on_lyrics(self, tid: str, lines, body, force: bool = False) -> None:
        if tid != self.clock.tid:
            return
        if not force and self.dropped == tid and body is not self.body:
            return
        if not lines and self.lines:
            return
        same = body is not None and body is self.body and len(lines) == len(self.raw)
        self.raw = lines or []
        self.body = body
        self.source = str(SL.payload(body or {}).get("_source") or "")
        self.lines = self.build_lines()
        self.apply_romaji_fixes()
        self.synced = any(ln["start"] is not None for ln in self.lines)
        if not same:
            self.est_tid = None
        self.measure_offset()
        if not same:
            self.layout_cache.clear()
            self.pix_cache.clear()
        if not self.lines:
            self.status_text = "No cached lyrics yet — waiting…"
        elif not self.synced:
            self.status_text = "Unsynced lyrics"
        else:
            self.status_text = ""
        self.maybe_auto_genius()
        self.say_alignment_outranked(tid)

    def say_alignment_outranked(self, tid: str) -> None:
        """Say so when this machine has timed a song and something else won.

        There is no fault here to fix, which is why this only talks. "local"
        sits last by design (see SRC_DEFAULT) and fallback() will not let one
        word-synced document replace another from further down the list -- so
        on a song Spicy Lyrics already word-syncs, an alignment made here is
        saved, correct, and not what is on screen. Without a word about it that
        reads as the alignment having silently failed, which is the one thing
        it did not do.

        Once per track. The fetcher answers twice on the ordinary track and
        the second answer is not news.
        """
        if not tid or tid == self._said_outranked:
            return
        if not self.lines or not LS.aligned(tid):
            return
        if str(SL.payload(self.body or {}).get("_timing") or "") == "align":
            return
        self._said_outranked = tid
        whose = self.source_name(SL.payload(self.body)) or "another source"
        self.toast(f"aligned here, but {whose} outranks it — move “Aligned "
                   f"here” ABOVE {whose} in Sources to use it")

    def on_artists(self, tid: str, got) -> None:
        if not isinstance(got, dict):
            return
        names = got.get("artists")
        if isinstance(names, list) and names:
            self.artists[tid] = [a for a in names
                                 if isinstance(a, dict) and a.get("name")]
        album = got.get("album")
        if isinstance(album, dict) and album.get("uri"):
            self.albums[tid] = album

    def credits(self) -> list:
        """[{name, uri}] for everyone on the track, page first, MPRIS second."""
        full = self.artists.get(self.clock.tid or "")
        if full:
            return full
        one = self.clock.meta.get("artist", "")
        return [{"name": one, "uri": ""}] if one else []

    def artist(self) -> str:
        """Everyone credited, not just whoever MPRIS put first."""
        names = [a["name"] for a in self.credits()]
        return ", ".join(names) or self.clock.meta.get("artist", "")

    def song_title(self) -> str:
        """The title with its guest credit taken out.

        "(feat. AzChike)" is not part of the song's name, it is a credit that
        happens to be written in the name field -- and it is already shown, in
        full, on its own line underneath. Left in the title it is said twice,
        and it is the half of the title most likely to push the rest out of the
        box. Removed only when it was actually understood: if nobody came out
        of the parse, the title stands as written.
        """
        raw = self.clock.meta.get("title", "")
        _lead, feat = split_artists(raw, self.credits())
        if not feat:
            return raw
        return (FEAT_RE.sub("", raw).strip() or raw)

    def artist_split(self) -> tuple[str, str]:
        """(who it is by, the guest line) -- the second is "" when there is none."""
        lead, feat = split_artists(self.clock.meta.get("title", ""), self.credits())
        if not feat:
            return ", ".join(a["name"] for a in lead), ""
        how = "feat." if any(a.get("how") == "feat" for a in feat) else "with"
        return (", ".join(a["name"] for a in lead),
                f"{how} " + ", ".join(a["name"] for a in feat))

    def source_name(self, doc: dict) -> str:
        """Where the lyrics on screen actually came from.

        YouLy+ is a scraper, not a corpus -- it says which upstream answered,
        and that is the part worth reporting: Apple means word-timed, while
        Musixmatch usually means line-level. Shown as "YouLy+ · Apple Music".

        Where the words and the clock come from different places the label says
        both, the same way YouLy+'s own blend is reported as "Apple Music with
        QQ". A NetEase-timed document used to report as plain "Spicy Lyrics",
        which credits the half of it that could not do the thing you are
        watching it do.
        """
        via = {"apple": "Apple Music", "musixmatch": "Musixmatch",
               "musixmatch-word": "Musixmatch", "qq": "QQ Music",
               "deezer": "Deezer", "lyricsplus": "LyricsPlus submissions",
               "qaple": "Apple Music with QQ"}
        src = self.source
        alone = str(doc.get("_alone") or "")
        if src == "blend" and alone:
            src = "" if alone == "spicy" else alone
        name = {"amll": "amll-ttml-db", "youly": "YouLy+",
                "netease": "NetEase Cloud Music", "blend": "Blend",
                "lrclib": "LRCLIB",
                "local": SRC_LABEL["local"]}.get(src)
        if not name:
            was = {"spl": "community", "aml": "Apple Music",
                   "spt": "Spotify"}.get(str(doc.get("source") or ""),
                                         str(doc.get("source") or ""))
            name = f"Spicy Lyrics · {was}" if was else "Spicy Lyrics"
        clock = {"netease": "NetEase Cloud Music"}.get(str(doc.get("_timing") or ""))
        if clock:
            return f"{name or 'Spicy Lyrics'} with {clock}"
        if not name:
            return "—"
        up = doc.get("_via")
        return f"{name} · {via.get(str(up).lower(), up)}" if up else name

    def made_by(self, doc: dict) -> str:
        """Who timed this copy of the song, as one line.

        Spicy Lyrics distinguishes the person who made the sync from the person
        who uploaded it, and often only knows the second -- Maker comes back as
        an empty {} on two thirds of the community entries here. Its own UI
        credits the uploader as the maker in that case, which is the right call:
        with nobody else named, they are who made it, and "uploaded by" credits
        them for less than they did.
        """
        meta = doc.get("TTMLUploadMetadata")
        meta = meta if isinstance(meta, dict) else {}
        makers = _people(meta.get("Maker")) or _people(doc.get("_maker"))
        uploaders = _people(meta.get("Uploader"))
        bits = []
        if makers:
            bits.append("Made by " + ", ".join(makers))
        if uploaders:
            bits.append(("Uploaded by " if makers else "Made by ")
                        + ", ".join(uploaders))
        return " · ".join(bits)

    def credit_rows(self) -> list[str]:
        """The block that sits under the last line: who wrote the song, where
        this copy came from, and who timed it -- in that order."""
        doc = SL.payload(self.body or {})
        if not doc or not self.raw:
            return []
        out = []
        writers = [str(w).strip() for w in (doc.get("SongWriters") or [])
                   if str(w).strip()]
        if writers:
            out.append(", ".join(writers))
        src = self.source_name(doc)
        if src and src != "—":
            out.append(src)
        made = self.made_by(doc)
        if made:
            out.append(made)
        return out

    def sources(self) -> set:
        """Fallback providers that are switched on."""
        return {n for n in self.src_order if getattr(self, SRC_ATTR[n], False)}

    def source_order(self) -> list:
        """The switched-on providers, in the order they should be consulted."""
        return [n for n in self.src_order if getattr(self, SRC_ATTR[n], False)]

    def align_settings(self) -> dict:
        """What the aligner should do to this machine, read fresh per job.

        A callable rather than a copy handed over at startup, so changing any of
        it in the menu applies to the next song rather than the next launch.
        """
        return {"stems": bool(self.align_stems), "device": self.align_device,
                "spare": float(self.align_spare), "sources": self.sources(),
                "order": self.source_order(), "token": self.genius_token,
                "free": bool(self.align_free),
                "model": str(self.align_model)}

    def align_now(self) -> None:
        """Align the song that is playing, because the user asked for it.

        Unlike the queued-ahead jobs this does not check whether the song
        already has word timing or whether the card is busy -- asking for it is
        the answer to both of those.
        """
        if not self.align_on:
            self.toast("local aligning is off")
            return
        tid = self.clock.tid
        if not tid:
            self.toast("no track")
            return
        if self.aligner.busy == tid:
            self.toast("already aligning this song")
            return
        if LS.aligned(tid):
            self.toast("already aligned — press again to redo")
            LS.forget(tid)
            self.aligner.forget_tried(tid)
            self.reload_lyrics()
            return
        gave_way = self.aligner.cancel()
        self.aligner.forget_tried(tid)
        if self.aligner.request(tid, self.fetch_meta(), asked=True):
            self.toast("stopping the queued-ahead one — aligning this song"
                       if gave_way else "aligning this song — a few minutes")

    def align_ahead_scan(self) -> None:
        """Offer the aligner the next song or two in the queue.

        Cheap to call: the queue arrives on the fetcher's own signal, and every
        track that is already aligned, already tried, or already word-synced is
        turned away by the aligner rather than being worked on.
        """
        n = int(self.align_ahead) if self.align_on else 0
        want = []
        for item in (self.queue_items or [])[:max(0, n)]:
            uri = str(item.get("uri") or "")
            if not uri.startswith("spotify:track:"):
                continue
            want.append((uri.rsplit(":", 1)[-1], {
                "title": item.get("name") or "", "artist": item.get("sub") or "",
                "album": "", "length": float(item.get("ms") or 0) / 1000.0}))
        self.aligner.keep_only({tid for tid, _m in want})
        if n <= 0:
            return
        for tid, meta in want:
            self.aligner.request(tid, meta)

    def on_aligned(self, tid: str, ok: bool, said: str) -> None:
        if said:
            self.toast(said)
        if ok and tid == self.clock.tid:
            self.reload_lyrics()

    def reload_lyrics(self) -> None:
        self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                             self.source_order(), self.ne_graft)

    def fetch_meta(self) -> dict:
        """What the name-based providers need to find the song."""
        m = self.clock.meta
        return {"title": m.get("title", ""), "artist": self.artist(),
                "album": m.get("album", ""), "length": m.get("length", 0.0)}

    def maybe_auto_genius(self) -> None:
        """With 'Use Genius' on, fetch the romanisation as the track loads.

        Only once per track per session, and only where there is something to
        romanise -- a miss is remembered too, or every poll would fire another
        search at Genius for a track that has no romanised version.
        """
        tid = self.clock.tid
        if not (self.genius_auto and tid and self.lines and self.genius_token):
            return
        if tid in self.genius_tried or self.genius_fix.get(tid):
            return
        if not any(SL.CJK.search(l["text"]) for l in self.lines):
            return
        self.genius_tried.add(tid)
        self.fetch_genius(quiet=True)

    def sounding(self, pos: float) -> list[int]:
        """Lines to treat as current.

        Between two lines nothing is strictly active, which used to leave every
        line six steps from an anchor that did not exist -- so the whole view
        went to maximum blur at 10% opacity in every gap between lines. Hold the
        line that just finished instead, the way the web view keeps it lit until
        the next one starts: the reading stays put and only real distance blurs.
        """
        live = SL.active_indices(self.lines, pos)
        if live:
            return live
        held, held_end = -1, None
        for i, ln in enumerate(self.lines):
            if ln["start"] is None or ln["start"] > pos:
                continue
            end = ln["end"] if ln["end"] is not None else ln["start"]
            if held_end is None or end >= held_end:
                held, held_end = i, end
        if held >= 0:
            return [held]
        return [0] if self.lines else []

    def anchor(self) -> float:
        """Where line 0 starts. Synced lyrics scroll a focus band into the upper
        third; unsynced ones never scroll themselves, so they start near the top
        instead of leaving half a window of dead space above the first line."""
        return self.height() * (0.40 if self.synced else 0.13)

    def vfade(self, y: float) -> float:
        """Opacity multiplier by vertical distance from the focus band."""
        H = max(1, self.height())
        d = abs(y - H * 0.40) / (H * 0.62)
        if d <= 0.35:
            return 1.0
        t = min(1.0, (d - 0.35) / 0.65)
        f = max(0.0, 1.0 - t * t * (3 - 2 * t))
        return f + (0.62 - f) * self.browse if f < 0.62 else f

    def position(self) -> float:
        f = getattr(self.args, "freeze", None)
        if f is not None:
            return f
        if self.drag_frac is not None:
            return self.drag_frac * self.clock.meta.get("length", 0.0)
        return self.clock.position()

    # -- geometry --------------------------------------------------------
    def instrumental(self) -> bool:
        """Nothing to show for this track, and nothing still coming.

        The fetch chain answers more than once -- a miss, then a retry a couple
        of seconds later -- so a verdict reached on the first empty answer would
        rearrange the window and then undo it. Waiting the retries out costs a
        few seconds of "…" and gets it right.

        The clock alone was not enough. A lookup that goes out to every provider
        can outlast SETTLE several times over, and the window would rearrange
        itself around a song with perfectly good word timing that simply had not
        arrived yet. So the fetcher says when it has actually finished asking,
        and until then this is a wait, however long it runs.
        """
        return (bool(self.clock.tid) and not self.lines
                and self.clock.status != "Error"
                and self.fetcher.done == self.clock.tid
                and time.monotonic() - self.track_at > SETTLE)

    def panel_width(self) -> float:
        """Left art panel; collapses on narrow windows so lyrics get the space.

        Compact mode collapses it at any width -- that is what compact means --
        and the cover it would have shown reappears small beside the title.

        A track with no lyrics gives the whole width to the panel instead. The
        column exists to hold words; with none to hold, an empty two-thirds of
        the window pushing the cover into a corner is just a layout waiting for
        something that is not coming.
        """
        if self.instrumental() and self.show_panel:
            return float(self.width())
        if self.view_mode != "regular" or not self.show_panel:
            return 0.0
        return self.width() * 0.42 if self.width() >= 980 else 0.0

    def margin(self) -> float:
        return max(28.0, self.width() * 0.034)

    def _lyr_x(self) -> float:
        panel = self.panel_width()
        return panel if panel else self.margin()

    def _lyr_width(self) -> float:
        return self.width() - self._lyr_x() - self.margin()

    def line_ox(self, ln: dict, fm: QFontMetricsF, x0: float) -> float:
        """Left origin the line's row offsets are measured from. A backing-vocal
        indent pushes inward from whichever edge the line hangs off."""
        align = self.line_align(ln)
        indent = fm.height() * 0.55 if ln["background"] else 0.0
        return x0 + (0.0 if align == "center" else (-indent if align == "right" else indent))

    def line_align(self, ln: dict) -> str:
        """The second voice of a duet hangs off the opposite side, whatever the
        base alignment is -- that contrast is the whole point of the flag."""
        if not ln["opposite"]:
            return self.align
        return {"left": "right", "center": "right", "right": "left"}[self.align]

    def wrap_pieces(self, pieces, fm: QFontMetricsF, width: float, align: str):
        """Timed fragments -> rows of (x, advance, text, start, end)."""
        words: list[list] = []
        cur: list = []
        for pc in pieces:
            cur.append(pc)
            if not pc[3]:
                words.append(cur)
                cur = []
        if cur:
            words.append(cur)

        rows: list[list] = [[]]
        x = 0.0
        for wi, word in enumerate(words):
            core = sum(fm.horizontalAdvance(pc[2]) for pc in word)
            atomic = True
            if core > width:
                word = [sub for pc in word for sub in split_to_fit(pc, fm, width)]
                atomic = False
            elif x + core > width and rows[-1]:
                rows.append([])
                x = 0.0
            for j, (s, e, txt, part) in enumerate(word):
                tail = " " if (j == len(word) - 1 and wi < len(words) - 1) else ""
                w = fm.horizontalAdvance(txt + tail)
                if not atomic and x + w > width and rows[-1]:
                    rows.append([])
                    x = 0.0
                rows[-1].append((x, w, txt + tail, s, e))
                x += w
        if align != "left":
            for row in rows:
                if not row:
                    continue
                rw = row[-1][0] + fm.horizontalAdvance(row[-1][2].rstrip())
                slack = max(0.0, width - rw)
                dx = slack if align == "right" else slack / 2
                row[:] = [(x + dx, w, t, s, e) for x, w, t, s, e in row]
        return rows

    def line_pieces(self, ln: dict):
        """Which script to lay out -- the original, or its romanisation."""
        if self.roman == "instead" and ln.get("pieces_roman"):
            return ln["pieces_roman"]
        return ln["pieces"] or [(ln["start"], ln["end"], ln["text"], False)]

    def layout_line(self, idx: int, width: float):
        key = (idx, int(width), int(self.lyric_px()), self.align, self.roman,
               self.furigana)
        hit = self.layout_cache.get(key)
        if hit:
            return hit
        ln = self.lines[idx]
        fm = QFontMetricsF(self.lyric_font(ln["background"]))
        if ln.get("dots"):
            out = ([], fm, fm.height() * 1.35, [], None, [], None)
            self.layout_cache[key] = out
            return out
        if ln.get("credits"):
            cfm = QFontMetricsF(self.credit_font())
            rows = [r for row in ln["credits"]
                    for r in wrap_rows(cfm, row, width, maxrows=3, elide=False)]
            out = (rows, cfm, cfm.height() * (1.4 * len(rows) + 1.6),
                   [], None, [], None)
            self.layout_cache[key] = out
            return out
        align = self.line_align(ln)
        rows = self.wrap_pieces(self.line_pieces(ln), fm, width, align)
        ruby, rufm = self.ruby_rows(ln, rows, fm)
        h = len(rows) * (fm.height() * 1.06 + self.ruby_h(rufm))
        rrows, rfm = [], None
        if self.roman == "under" and ln.get("pieces_roman"):
            rfm = QFontMetricsF(self.roman_font(ln))
            rrows = self.wrap_pieces(ln["pieces_roman"], rfm, width, align)
            h += fm.height() * 0.10 + len(rrows) * rfm.height() * 1.04
        out = (rows, fm, h, rrows, rfm, ruby, rufm)
        self.layout_cache[key] = out
        return out

    def ruby_font(self, ln: dict) -> QFont:
        f = QFont(self.family, int(self.lyric_px() * (0.26 if ln["background"] else 0.34)))
        f.setWeight(QFont.Weight.Bold)
        return f

    @staticmethod
    def ruby_h(rufm) -> float:
        return 0.0 if rufm is None else rufm.height() * 0.92

    def ruby_rows(self, ln: dict, rows, fm: QFontMetricsF):
        """Kana readings placed over the kanji they belong to, row by row.

        The wrapper hands back the text fragments it actually laid out, and they
        join back up into the line, so the readings are worked out against those
        rather than against the timed pieces -- no need to track which fragment
        came from which syllable, and a fragment the wrapper had to break mid-word
        still gets the part of the reading that sits over it.
        """
        if not self.furigana or not rows or self.roman == "instead":
            return [], None
        frags = [e[2] for row in rows for e in row]
        try:
            ann = SL.furigana(frags)
        except Exception:
            return [], None
        if not any(ann):
            return [], None
        rufm = QFontMetricsF(self.ruby_font(ln))
        out, k = [], 0
        for row in rows:
            marks = []
            for x, _w, txt, s, e in row:
                for a, b, read in ann[k]:
                    cx = x + fm.horizontalAdvance(txt[:a])
                    cw = fm.horizontalAdvance(txt[a:b])
                    marks.append((cx + cw / 2, read, s, e))
                k += 1
            out.append(marks)
        return out, rufm

    def roman_font(self, ln: dict) -> QFont:
        f = QFont(self.family, int(self.lyric_px() * (0.44 if ln["background"] else 0.60)))
        f.setWeight(QFont.Weight.Bold)
        return f

    # -- animation -------------------------------------------------------
    def drift_of(self, key, x0: float, y0: float, w: float, h: float):
        """Physics state for one word, seeded where it was when it came loose.

        The position is ABSOLUTE in the window, not an offset from the line.
        Holding an offset meant the line kept scrolling out from under the word
        and dragged it along, so pinning the scroll was the only way to stop
        everything migrating to a corner -- and pinning the scroll stopped the
        lyrics following the song at all. Once a word is loose it belongs to the
        window; where its line has got to no longer concerns it.

        The launch direction comes from a hash of the key rather than random, so
        a word that leaves and comes back keeps its heading instead of jumping.
        """
        st = self.drift.get(key)
        if st is None:
            if (y0 + h < 0 or y0 > self.height()
                    or x0 + w < 0 or x0 > self.width()):
                return None
            n = hash(key)
            ang = (n % 6283) / 1000.0
            speed = 18.0 + (n >> 13) % 46
            st = [x0, y0,
                  math.cos(ang) * speed, math.sin(ang) * speed,
                  0.0, ((n >> 7) % 61 - 30) / 1.4, None, 0.0]
            self.drift[key] = st
        st[6] = (w, h)
        st[7] = time.monotonic()
        return st

    def step_drift(self) -> None:
        """Integrate the loose words. No gravity, so they only ever coast and
        bounce -- nothing accelerates them downward."""
        now = time.monotonic()
        dt = min(0.05, now - self.drift_at) if self.drift_at else 0.016
        self.drift_at = now
        if self.zero_g <= 0:
            if self.drift:
                self.drift.clear()
            return
        k = self.zero_g
        W, H = self.width(), self.height()
        for st in self.drift.values():
            if st[6] is None:
                continue
            (w, h), st[6] = st[6], None
            st[0] += st[2] * k * dt
            st[1] += st[3] * k * dt
            st[4] += st[5] * k * dt
            if st[0] < 0.0 or st[0] > W - w:
                st[0] = min(W - w, max(0.0, st[0]))
                st[2] = -st[2]
            if st[1] < 0.0 or st[1] > H - h:
                st[1] = min(H - h, max(0.0, st[1]))
                st[3] = -st[3]
        if len(self.drift) > 400:
            cut = now - 4.0
            for key in [k2 for k2, st in self.drift.items() if st[7] < cut]:
                self.drift.pop(key, None)

    def tick(self) -> None:
        self.step_drift()
        pos = self.position() - self.track_offset()
        live = set(self.sounding(pos)) if self.synced else set()
        moving = False
        for i in range(len(self.lines)):
            cur = self.activation.get(i, 0.0)
            goal = 1.0 if i in live else 0.0
            if abs(cur - goal) > 0.004:
                self.activation[i] = cur + (goal - cur) * 0.2
                moving = True
            else:
                self.activation[i] = goal
        goal = 1.0 if time.monotonic() < self.user_scroll_until else 0.0
        if abs(self.browse - goal) > 0.004:
            self.browse += (goal - self.browse) * 0.18
            moving = True
        else:
            self.browse = goal

        if live and time.monotonic() > self.user_scroll_until:
            focus = SL.focus_index(self.lines, live)
            for i, top, h, _lo, _hi in self.line_rects:
                if i == focus:
                    self.scroll_target = top - self.anchor() + h / 2
                    break
        self.scroll_target = max(
            -self.height() * (0.25 if self.synced else 0.02),
            min(self.scroll_target, max(0.0, self.content_h - self.height() * 0.30)),
        )
        if abs(self.scroll_target - self.scroll) > 0.4:
            moving = True
        self.scroll += (self.scroll_target - self.scroll) * 0.12

        if self.beat_scale:
            sec = self.beat.section(self.position())
            if sec != self._section:
                self._section = sec
                self._scene_key = self._glow_key = None
                moving = True

        if self.quit_requested:
            self.quit_requested = False
            self.close()
            QApplication.instance().quit()
            return

        if time.monotonic() > self._save_at:
            self._save_at = time.monotonic() + 2.0
            self.autosave()

        if self.isFullScreen() and time.monotonic() - self.last_move > 2.5:
            self.set_cursor(Qt.CursorShape.BlankCursor)

        if self.view == "browse":
            self.browse_scroll_target = max(
                0.0, min(self.browse_scroll_target,
                         max(0.0, getattr(self, "content_h_browse", 0.0))))
            if abs(self.browse_scroll_target - self.browse_scroll) > 0.4:
                self.browse_scroll += (self.browse_scroll_target
                                       - self.browse_scroll) * 0.18
                moving = True
            else:
                self.browse_scroll = self.browse_scroll_target
            if (self.browse_hover is not None
                    or time.monotonic() - self.last_move < 1.0
                    or self.bq_busy or self.backfill_total):
                moving = True

        busy = (moving or self.clock.status == "Playing" or self._marq_live
                or bool(self.motion_art and self.motion_frames)
                or self.toast_until > time.monotonic()
                or (self.clouds > 0 and self.view == "lyrics" and bool(self.lines)))
        self._idle_frames = 0 if busy else self._idle_frames + 1
        if busy or self._idle_frames % max(1, round(self.eff_hz / 10)) == 0:
            self.update()

    # -- text pixmaps, so distant lines can be blurred cheaply -----------
    def line_pixmap(self, idx: int, width: float, blur: int) -> QPixmap:
        key = (idx, int(width), blur, int(self.lyric_px()), self.align, self.roman)
        hit = self.pix_cache.get(key)
        if hit:
            return hit
        rows, fm, h, rrows, rfm, ruby, rufm = self.layout_line(idx, width)
        pad = 10 + blur * 6
        pm = QPixmap(int(width + pad * 2), int(h + pad * 2))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self.lyric_font(self.lines[idx]["background"]))
        p.setPen(TEXT)
        ruh = self.ruby_h(rufm)
        y = pad + ruh + fm.ascent()
        rufont = self.ruby_font(self.lines[idx]) if rufm is not None else None
        for r, row in enumerate(rows):
            if rufont is not None and r < len(ruby):
                p.setFont(rufont)
                by = y - fm.ascent() - ruh + rufm.ascent()
                for cx, read, _s, _e in ruby[r]:
                    p.drawText(QPointF(pad + cx - rufm.horizontalAdvance(read) / 2, by), read)
                p.setFont(self.lyric_font(self.lines[idx]["background"]))
            for x, w, txt, s, e in row:
                p.drawText(QPointF(pad + x, y), txt)
            y += fm.height() * 1.06 + ruh
        if rrows and rfm is not None:
            p.setFont(self.roman_font(self.lines[idx]))
            y += fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent()
            for row in rrows:
                for x, w, txt, s, e in row:
                    p.drawText(QPointF(pad + x, y), txt)
                y += rfm.height() * 1.04
        p.end()
        if blur:
            pm = soft_scale(pm, 1 + blur)
        if len(self.pix_cache) > 400:
            self.pix_cache.clear()
        self.pix_cache[key] = pm
        return pm

    def glow_pixmap(self, txt: str, font: QFont, radius: int) -> QPixmap:
        """Soft halo for the syllable being sung right now."""
        key = ("glow", txt, font.pointSize(), radius)
        hit = self.pix_cache.get(key)
        if hit:
            return hit
        fm = QFontMetricsF(font)
        pad = radius * 3
        pm = QPixmap(int(fm.horizontalAdvance(txt) + pad * 2), int(fm.height() + pad * 2))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QPointF(pad, pad + fm.ascent()), txt)
        p.end()
        pm = soft_scale(pm, 1 + radius)
        if len(self.pix_cache) > 400:
            self.pix_cache.clear()
        self.pix_cache[key] = pm
        return pm

    def glow_layer(self) -> QPixmap:
        """Accent wash over the cover, cached -- rasterising radial gradients
        every frame was the single most expensive thing in paintEvent."""
        W, H = self.width(), self.height()
        key = (W, H, tuple(c.rgb() for c in self.palette), self._section)
        if key == self._glow_key and self._glow_pm is not None:
            return self._glow_pm
        pm = QPixmap(W, H)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        spots = ((0.72, 0.30, 0.85, 100), (0.16, 0.86, 0.66, 58), (0.86, 0.80, 0.55, 44))
        for i, (cx, cy, rad, alpha) in enumerate(spots):
            a = self.palette[(i + self._section) % len(self.palette)]
            g = QRadialGradient(W * cx, H * cy, max(W, H) * rad)
            g.setColorAt(0.0, QColor(a.red(), a.green(), a.blue(), alpha))
            g.setColorAt(1.0, QColor(a.red(), a.green(), a.blue(), 0))
            p.fillRect(0, 0, W, H, QBrush(g))
        p.end()
        self._glow_key, self._glow_pm = key, pm
        return pm

    def scene_layer(self) -> QPixmap:
        """The whole background, composited at 15fps and blitted at the frame
        rate. Only slow drift changes it, so rebuilding it every frame paid for
        several full-window passes nobody can see."""
        W, H = self.width(), self.height()
        now = time.monotonic()
        t = now * 0.06 * self.bg_motion
        key = (W, H, tuple(c.rgb() for c in self.palette), self.art_gen,
               self.bg_mode, round(self.bg_dim, 2), round(self.bg_motion, 2),
               self._section)
        fresh = 1 / 15 if self.bg_motion else 1.0
        if self._scene_pm is not None and key == self._scene_key and now - self._scene_at < fresh:
            return self._scene_pm
        pm = QPixmap(W, H)
        p = QPainter(pm)
        p.fillRect(0, 0, W, H, QColor(9, 9, 12))
        if self.bg_mode == "mesh":
            self._paint_mesh(p, W, H, t)
        elif self.bg_mode == "art" and self.art_bg:
            p.setOpacity(0.55)
            p.drawPixmap(QRectF(0, 0, W, H), self.art_bg, self._art_src(self.art_bg, t))
            p.setOpacity(1.0)
        veil = int(max(0.0, min(1.0, self.bg_dim)) * 255)
        p.fillRect(0, 0, W, H, QColor(6, 6, 9, veil))
        if self.bg_mode == "art":
            p.drawPixmap(0, 0, self.glow_layer())
        p.end()
        self._scene_key, self._scene_pm, self._scene_at = key, pm, now
        return pm

    def _paint_mesh(self, p, W: int, H: int, t: float) -> None:
        """Album-palette blobs drifting on out-of-phase Lissajous paths. Works
        with no cover art at all, and stays legible where a busy cover does not."""
        span = max(W, H)
        for i, c in enumerate(self.palette):
            ph = i * 2.399
            cx = W * (0.5 + 0.40 * math.sin(t * 1.9 + ph))
            cy = H * (0.5 + 0.40 * math.cos(t * 1.4 + ph * 1.7))
            rad = span * (0.46 + 0.15 * math.sin(t * 1.1 + ph))
            g = QRadialGradient(cx, cy, rad)
            g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 165))
            g.setColorAt(0.55, QColor(c.red(), c.green(), c.blue(), 55))
            g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(0, 0, W, H, QBrush(g))

    def fade_layer(self) -> QPixmap:
        """Top/bottom vignette, cached for the same reason as glow_layer."""
        W, H = self.width(), self.height()
        if (W, H) == self._fade_key and self._fade_pm is not None:
            return self._fade_pm
        pm = QPixmap(W, H)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0.0, QColor(7, 7, 10, 255))
        g.setColorAt(0.26, QColor(7, 7, 10, 0))
        g.setColorAt(0.74, QColor(7, 7, 10, 0))
        g.setColorAt(1.0, QColor(7, 7, 10, 255))
        p.fillRect(0, 0, W, H, g)
        p.end()
        self._fade_key, self._fade_pm = (W, H), pm
        return pm

    # -- painting --------------------------------------------------------
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        self._marq_live = False

        if self.view == "browse":
            self._paint_browse(p, W, H)
            if self.toast_until > time.monotonic():
                self._paint_toast(p, W, H)
            ov = self.overlay()
            if ov in ("help", "menu"):
                {"help": self._paint_help, "menu": self._paint_menu}[ov](p, W, H)
            return

        if self.view == "detail":
            self._paint_detail(p, W, H)
            if self.toast_until > time.monotonic():
                self._paint_toast(p, W, H)
            ov = self.overlay()
            if ov in ("help", "menu"):
                {"help": self._paint_help, "menu": self._paint_menu}[ov](p, W, H)
            return

        e = self.beat_energy()
        if e > 0.004:
            g = 1.0 + 0.035 * e
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.drawPixmap(QRectF(W * (1 - g) / 2, H * (1 - g) / 2, W * g, H * g),
                         self.scene_layer(), QRectF(0, 0, W, H))
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        else:
            p.drawPixmap(0, 0, self.scene_layer())

        x0, width = self._lyr_x(), self._lyr_width()
        if self.lines:
            self._paint_lines(p, x0, width, H)
        elif self.instrumental():
            pass
        else:
            p.setFont(self.lyric_font(True))
            p.setPen(QColor(234, 234, 234, 150))
            p.drawText(
                QRectF(x0, 0, width, H),
                Qt.AlignmentFlag.AlignCenter,
                self.status_text or "…",
            )
            why = getattr(self.clock, "last_error", "")
            if self.clock.status == "Error" and why:
                fs = self.ui_font(max(10, W * 0.0092))
                fms = QFontMetricsF(fs)
                p.setFont(fs)
                p.setPen(QColor(234, 234, 234, 110))
                rows = wrap_rows(fms, why, width * 0.8, 4, elide=False)
                ty = H / 2 + self.lyric_px() * 0.9
                for row in rows:
                    p.drawText(QRectF(x0, ty, width, fms.height() * 1.35),
                               Qt.AlignmentFlag.AlignCenter, row)
                    ty += fms.height() * 1.35

        p.drawPixmap(0, 0, self.fade_layer())

        panel = self.panel_width()
        self.bar_rect = self.vol_rect = None
        self.hot = []
        if panel:
            self._paint_panel(p, panel, H)
        else:
            self._paint_header(p, W, H)
        if self.toast_until > time.monotonic():
            self._paint_toast(p, W, H)
        ov = self.overlay()
        if ov:
            {"help": self._paint_help, "menu": self._paint_menu,
             "search": self._paint_search, "info": self._paint_info,
             "editor": self._paint_editor}[ov](p, W, H)

    def _art_src(self, pm: QPixmap, t: float) -> QRectF:
        """Cover-crop the blurred art, drifting slowly so the wall is not static."""
        W, H = max(1, self.width()), max(1, self.height())
        aw, ah = pm.width(), pm.height()
        s = min(aw / W, ah / H)
        z = 0.86 + 0.06 * math.sin(t * 0.7)
        sw, sh = W * s * z, H * s * z
        cx = aw / 2 + (aw - sw) * 0.28 * math.sin(t * 0.53)
        cy = ah / 2 + (ah - sh) * 0.28 * math.cos(t * 0.41)
        return QRectF(cx - sw / 2, cy - sh / 2, sw, sh)

    def _paint_lines(self, p, x0: float, width: float, H: int) -> None:
        pos = self.position() - self.track_offset()
        live = self.sounding(pos) if self.synced else []
        top = self.anchor()
        y = top - self.scroll
        self.line_rects = []
        deferred: list[tuple] = []
        for i, ln in enumerate(self.lines):
            rows, fm, h, rrows, rfm, ruby, rufm = self.layout_line(i, width)
            ox = self.line_ox(ln, fm, x0)
            grab = fm.height() * 0.45
            if ln.get("credits"):
                lo = hi = ox
            elif ln.get("dots"):
                span = fm.height() * 0.19 * 3.4 * 2
                lo, hi = ox - grab, ox + span + grab
            else:
                ink = [(r[0][0], r[-1][0] + r[-1][1]) for r in rows if r]
                lo = ox + min(a for a, _ in ink) - grab if ink else ox
                hi = ox + max(b for _, b in ink) + grab if ink else ox
            self.line_rects.append((i, y + self.scroll, h, lo, hi))
            nxt_bg = i + 1 < len(self.lines) and self.lines[i + 1]["background"]
            gap = fm.height() * (0.16 if (ln["background"] or nxt_bg) else 0.42)
            m = H if (self.zero_g > 0 or self.clouds > 0) else 40
            far = (self.clouds > 0 and live
                   and min(abs(i - j) for j in live) > 3)
            if not far and y + h > -m and y < H + m:
                args = (i, ln, rows, fm, x0, y, pos, live, rrows, rfm, ruby, rufm)
                if self.clouds > 0 and (i in live
                                        or self.activation.get(i, 0.0) > 0.02):
                    deferred.append(args)
                else:
                    self._paint_line(p, *args)
            y += h + gap * self.line_spacing
        for args in deferred:
            self._paint_line(p, *args)
        self.content_h = y + self.scroll - top

    def _paint_panel(self, p, panel: float, H: int) -> None:
        unit = min(panel, self.width() * 0.42)
        pad = unit * 0.13
        side = min(unit - pad * 2, H * 0.42)
        boxw = min(panel - pad, side + 120)
        ft = self.ui_font(max(13, unit * 0.047), QFont.Weight.ExtraBold)
        fa = self.ui_font(max(10, unit * 0.031), QFont.Weight.Medium)
        fs = self.ui_font(max(9, unit * 0.024), QFont.Weight.Medium)
        fm_t, fm_a, fm_s = QFontMetricsF(ft), QFontMetricsF(fa), QFontMetricsF(fs)

        m = self.clock.meta
        title = self.song_title()
        rows = wrap_rows(fm_t, title, boxw - 8, elide=False) if title else []
        sub, guests = self.artist_split()
        if self.track_offset():
            sub += f"   ({self.track_offset():+.2f}s)"
        dur = m.get("length", 0.0)

        block = side
        if rows:
            block += 30 + len(rows) * fm_t.height() * 1.12 + 6 + fm_a.height() * 1.3
        if dur > 0:
            block += 30 + 6 + fm_s.height()
        y = max(H * 0.10, (H - block) / 2)
        x = (panel - side) / 2

        cover = self.motion_frame() or self.art_full
        if cover:
            path = QPainterPath()
            r = side * 0.035
            path.addRoundedRect(QRectF(x, y, side, side), r, r)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(QRectF(x, y, side, side), cover, QRectF(cover.rect()))
            p.restore()
        y += side
        bx = (panel - boxw) / 2

        if rows:
            y += 30
            p.setFont(ft)
            p.setPen(TEXT)
            centred = int(Qt.AlignmentFlag.AlignHCenter
                          | Qt.AlignmentFlag.AlignVCenter)
            self.hot.append((QRectF(bx, y, boxw, fm_t.height() * 1.12 * len(rows)),
                             "song", self.clock.tid or ""))
            for r_i, row in enumerate(rows):
                self._scroll_text(p, row, QRectF(bx, y, boxw, fm_t.height() * 1.12),
                                  fm_t, f"panel.title{r_i}", centred)
                y += fm_t.height() * 1.12
            y += 6
            p.setFont(fa)
            p.setPen(QColor(234, 234, 234, 165))
            arect = QRectF(bx, y, boxw - 8, fm_a.height() * 1.3)
            lead = (split_artists(m.get("title", ""), self.credits())[0] or [{}])[0]
            if lead.get("uri"):
                self.hot.append((arect, "artist", lead["uri"]))
            self._scroll_text(p, sub, arect, fm_a, "panel.artist", centred)
            y += fm_a.height() * 1.3
            if guests:
                fg = self.ui_font(unit * 0.028, QFont.Weight.Normal)
                fm_g = QFontMetricsF(fg)
                p.setFont(fg)
                p.setPen(QColor(234, 234, 234, 110))
                self._scroll_text(p, guests,
                                  QRectF(bx, y, boxw - 8, fm_g.height() * 1.25),
                                  fm_g, "panel.feat", centred)
                y += fm_g.height() * 1.25

        if dur > 0:
            self._paint_progress(p, QRectF(bx, y + 30, boxw, 5), dur, fs, fm_s)
            y += 30 + 6 + fm_s.height()
        if self.show_volume:
            self._paint_volume(p, QRectF(bx + boxw * 0.18, y + 24, boxw * 0.64, 4))

    def _paint_progress(self, p, bar: QRectF, dur: float, fs, fm_s) -> None:
        pos = self.position()
        frac = max(0.0, min(1.0, pos / dur)) if dur else 0.0
        hot = self.drag_frac is not None or bar.adjusted(0, -9, 0, 9).contains(self.mouse_pos)
        self.bar_rect = bar
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(234, 234, 234, 55))
        p.drawRoundedRect(bar, bar.height() / 2, bar.height() / 2)
        done = QRectF(bar.x(), bar.y(), bar.width() * frac, bar.height())
        p.setBrush(QColor(234, 234, 234, 220))
        p.drawRoundedRect(done, bar.height() / 2, bar.height() / 2)
        if hot:
            p.setBrush(TEXT)
            p.drawEllipse(QPointF(done.right(), bar.center().y()), 6.0, 6.0)
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 150))
        ty = bar.bottom() + 6
        p.drawText(QRectF(bar.x(), ty, bar.width(), fm_s.height()),
                   int(Qt.AlignmentFlag.AlignLeft), fmt_time(pos))
        p.drawText(QRectF(bar.x(), ty, bar.width(), fm_s.height()),
                   int(Qt.AlignmentFlag.AlignRight), f"-{fmt_time(dur - pos)}")

    def _paint_volume(self, p, bar: QRectF) -> None:
        """Volume, on the same 0..1 the player keeps it in.

        Drawn thinner and dimmer than the progress bar on purpose: it is the
        same shape doing a different job, and the one you reach for mid-song is
        almost always the other one.
        """
        vol = self.vol_drag if self.vol_drag is not None else self.clock.volume
        if vol is None:
            return
        self.vol_rect = bar
        hot = (self.vol_drag is not None
               or bar.adjusted(-8, -9, 8, 9).contains(self.mouse_pos))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(234, 234, 234, 40))
        p.drawRoundedRect(bar, bar.height() / 2, bar.height() / 2)
        done = QRectF(bar.x(), bar.y(), bar.width() * max(0.0, min(1.0, vol)),
                      bar.height())
        p.setBrush(QColor(234, 234, 234, 150 if not hot else 210))
        p.drawRoundedRect(done, bar.height() / 2, bar.height() / 2)
        if hot:
            p.setBrush(TEXT)
            p.drawEllipse(QPointF(done.right(), bar.center().y()), 5.0, 5.0)

    def _scroll_text(self, p, text: str, rect: QRectF, fm: QFontMetricsF,
                     key: str, flags: int | None = None) -> None:
        """Draw text in rect, sliding it back and forth if it does not fit.

        An ellipsis hides the end of a long title for as long as the song plays,
        and song titles are exactly where the tail matters -- the remix, the
        version, who it is with. Passing over the whole string costs nothing and
        eventually shows all of it.

        Held still at both ends, because text that never stops is text nobody
        finishes reading. Anything that fits is drawn plainly and keeps whatever
        alignment it was given; scrolling text is always left-aligned, there
        being no sense in centring something wider than its box.
        """
        if flags is None:
            flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        span = fm.horizontalAdvance(text) - rect.width()
        if span <= 0.5:
            self._marq.pop(key, None)
            p.drawText(rect, flags, text)
            return
        hold, speed = 1.7, max(30.0, fm.height() * 1.4)
        travel = span / speed
        cycle = 2.0 * (hold + travel)
        at = (time.monotonic() - self._marq.setdefault(key, time.monotonic())) % cycle
        if at < hold:
            u = 0.0
        elif at < hold + travel:
            u = (at - hold) / travel
        elif at < 2.0 * hold + travel:
            u = 1.0
        else:
            u = 1.0 - (at - 2.0 * hold - travel) / travel
        u = u * u * (3.0 - 2.0 * u)
        self._marq_live = True
        p.save()
        p.setClipRect(rect)
        p.drawText(rect.adjusted(-span * u, 0, 0, 0),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        p.restore()

    def _paint_header(self, p, W: int, H: int) -> None:
        """Compact stand-in when the art panel is collapsed or switched off."""
        m = self.clock.meta
        dur = m.get("length", 0.0)
        if dur > 0:
            frac = max(0.0, min(1.0, self.position() / dur))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(234, 234, 234, 45))
            p.drawRect(QRectF(0, H - 3, W, 3))
            p.setBrush(QColor(234, 234, 234, 210))
            p.drawRect(QRectF(0, H - 3, W * frac, 3))
            self.bar_rect = QRectF(0, H - 14, W, 14)
        if not m.get("title"):
            return
        scrim = QLinearGradient(0, 0, 0, 96)
        scrim.setColorAt(0.0, QColor(7, 7, 10, 210))
        scrim.setColorAt(1.0, QColor(7, 7, 10, 0))
        p.fillRect(QRectF(0, 0, W, 96), scrim)
        ft = self.ui_font(W * 0.0135, QFont.Weight.ExtraBold)
        fa = self.ui_font(W * 0.0105, QFont.Weight.Medium)
        fm_t, fm_a = QFontMetricsF(ft), QFontMetricsF(fa)
        x, w = self.margin(), W * 0.5
        thumb_pm = self.motion_frame() or self.art_full
        if self.show_panel and thumb_pm:
            side = fm_t.height() + fm_a.height()
            path = QPainterPath()
            r = side * 0.12
            path.addRoundedRect(QRectF(x, 16, side, side), r, r)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(QRectF(x, 16, side, side), thumb_pm, QRectF(thumb_pm.rect()))
            p.restore()
            gap = side * 0.28
            x += side + gap
            w = max(120.0, W * 0.5 - side - gap)
        p.setFont(ft)
        p.setPen(QColor(234, 234, 234, 205))
        title = self.song_title()
        title_box = QRectF(x, 16, min(w, fm_t.horizontalAdvance(title)),
                           fm_t.height())
        self.hot.append((title_box, "song", self.clock.tid or ""))
        self._scroll_text(p, title, QRectF(x, 16, w, fm_t.height()), fm_t,
                          "head.title")
        sub, guests = self.artist_split()
        if self.track_offset():
            sub += f"   ({self.track_offset():+.2f}s)"
        p.setFont(fa)
        p.setPen(QColor(234, 234, 234, 130))
        arect = QRectF(x, 16 + fm_t.height(),
                       min(w, fm_a.horizontalAdvance(sub)), fm_a.height())
        lead = (split_artists(m.get("title", ""), self.credits())[0] or [{}])[0]
        if lead.get("uri"):
            self.hot.append((arect, "artist", lead["uri"]))
        self._scroll_text(p, sub, QRectF(x, 16 + fm_t.height(), w, fm_a.height()),
                          fm_a, "head.artist")
        if guests:
            fg = self.ui_font(W * 0.0088, QFont.Weight.Normal)
            fm_g = QFontMetricsF(fg)
            p.setFont(fg)
            p.setPen(QColor(234, 234, 234, 95))
            self._scroll_text(p, guests,
                              QRectF(x, 16 + fm_t.height() + fm_a.height(),
                                     w, fm_g.height()),
                              fm_g, "head.feat")
        if self.show_volume:
            vw = min(150.0, W * 0.13)
            self._paint_volume(p, QRectF(W - self.margin() - vw,
                                         16 + fm_t.height() * 0.5, vw, 4))

    def spin_frag(self, rows, fm, ox: float, y: float, ruh: float, pos: float):
        """The word being sung right now, and the box it occupies.

        Only one at a time: whichever fragment the clock is inside. Returns
        (row, x, box) so the base layer can be cut around it and the overlay can
        turn it about the same centre.
        """
        if self.spin <= 0:
            return None
        for r_i, row in enumerate(rows):
            for x, w, txt, s, e in row:
                if s is None or e is None or not (s <= pos < e) or not txt.strip():
                    continue
                ry = y + ruh + fm.ascent() + r_i * (fm.height() * 1.06 + ruh)
                box = QRectF(ox + x - 2, ry - fm.ascent() - ruh - 2,
                             w + 4, fm.height() + ruh + 4)
                return (r_i, x, box)
        return None

    def cloud_pixmap(self) -> QPixmap:
        """One soft puff, drawn once and blitted behind every word.

        A radial gradient per word would be dozens of full gradient fills a
        frame -- the same cost that made setOpacity under a transform expensive.
        One pixmap stretched to each word is a plain blit.
        """
        hit = self.pix_cache.get("cloud")
        if hit:
            return hit
        R = 384
        pm = QPixmap(R, R)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        lobes = ((0.50, 0.50, 0.44), (0.24, 0.56, 0.34), (0.76, 0.56, 0.34),
                 (0.37, 0.42, 0.30), (0.63, 0.42, 0.30), (0.12, 0.58, 0.22),
                 (0.88, 0.58, 0.22))
        for cx, cy, rr in lobes:
            g = QRadialGradient(R * cx, R * cy, R * rr)
            g.setColorAt(0.0, QColor(255, 255, 255, 96))
            g.setColorAt(0.5, QColor(255, 255, 255, 54))
            g.setColorAt(1.0, QColor(255, 255, 255, 0))
            q.fillRect(0, 0, R, R, QBrush(g))
        q.end()
        self.pix_cache["cloud"] = pm
        return pm

    def cloud_of(self, key, W: int, H: int):
        """Drift state for one whole LINE.

        Per word it scrambled the reading order -- each word arrived from its own
        direction and the line landed as a jumble. The cloud is the line: the
        words keep their layout inside it, so it stays readable however far it
        has floated.

        Entry and exit directions come from a hash of the key, so a line keeps
        the same path instead of teleporting when it leaves and comes back.
        """
        st = self.cloudy.get(key)
        if st is None:
            n = hash(key)
            a1 = (n % 6283) / 1000.0
            a2 = ((n >> 11) % 6283) / 1000.0
            far = max(W, H) * 1.15
            st = [time.monotonic(),
                  math.cos(a1) * far, math.sin(a1) * far,
                  math.cos(a2) * far, math.sin(a2) * far,
                  (n >> 5) % 628 / 100.0, 0.0, 0.0,
                  (((n >> 17) % 200) / 100.0 - 1.0),
                  (((n >> 23) % 200) / 100.0 - 1.0)]
            self.cloudy[key] = st
        st[6] = time.monotonic()
        return st

    def _paint_cloud(self, p, idx, ln, rows, fm, ox, y, pos, act, alpha, dist,
                     x0=0.0, colw=0.0, rrows=(), rfm=None, ruby=(),
                     rufm=None) -> None:
        """Every word adrift in its own cloud.

        It floats in from off-screen as the line arrives, bobs while the line is
        being sung, and floats away again once the line has passed. Like the
        zero-g mode this gives up depth blur and furigana -- there is nowhere for
        a reading to sit above a word that is halfway across the window.
        """
        now = time.monotonic()
        W, H = self.width(), self.height()
        k = max(0.25, self.clouds)
        font = self.lyric_font(ln["background"])
        p.setFont(font)
        p.setOpacity(1.0)
        sung = self.sung_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ruh = self.ruby_h(rufm)
        rowh = fm.height() * 1.06 + ruh
        puff = self.cloud_pixmap()

        blocks = [(rows, fm, y + ruh + fm.ascent(), rowh, font, False)]
        if rrows and rfm is not None:
            ry0 = (y + ruh + fm.ascent() + len(rows) * rowh
                   + fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent())
            blocks.append((rrows, rfm, ry0, rfm.height() * 1.04,
                           self.roman_font(ln), True))

        st = self.cloud_of((idx, ln.get("text", "")), W, H)
        span = 3.2 / max(0.4, k)
        if dist > 1 and st[7] == 0.0:
            st[7] = now
        elif dist <= 1:
            st[7] = 0.0
        tin = _smooth(min(1.0, (now - st[0]) / span))
        out = _smooth(min(1.0, (now - st[7]) / span)) if st[7] else 0.0
        if out >= 1.0:
            return

        colw = colw or float(W)
        home_x = st[8] * colw * 0.16
        home_y = (H * 0.42 - y) + st[9] * H * 0.20

        t, ph = now * 0.055 * k, st[5]
        dx = home_x + (math.sin(t + ph) * W * 0.17
                       + math.sin(t * 0.41 + ph * 2.1) * W * 0.06)
        dy = home_y + (math.cos(t * 0.77 + ph * 1.3) * H * 0.11
                       + math.cos(t * 0.29 + ph) * H * 0.04)
        dx = (home_x + st[1]) + (dx - home_x - st[1]) * tin
        dy = (home_y + st[2]) + (dy - home_y - st[2]) * tin
        if out > 0.0:
            dx += (home_x + st[3] - dx) * out
            dy += (home_y + st[4] - dy) * out
        if out <= 0.0 and tin >= 1.0 and not ln.get("dots"):
            ink = [(r[0][0], r[-1][0] + r[-1][1]) for r in rows if r]
            if ink:
                lo_x = ox + min(a2 for a2, _ in ink)
                hi_x = ox + max(b for _, b in ink)
                left = x0 + 8.0
                right = (x0 + colw - 8.0) if colw else (W - 8.0)
                if hi_x - lo_x < right - left:
                    dx = min(max(dx, left - lo_x), right - hi_x)
                else:
                    dx = max(min(dx, left - lo_x), right - hi_x)
                dy = min(max(dy, 8.0 - y), H - 8.0 - (y + fm.height()))

        for rws, met, top, step, fnt, is_rom in blocks:
            p.setFont(fnt)
            mh = met.height()
            for r_i, row in enumerate(rws):
                by = top + r_i * step
                if row:
                    rx0 = ox + row[0][0] + dx
                    rx1 = ox + row[-1][0] + row[-1][1] + dx
                    ry0 = by - met.ascent() + dy
                    a_row = alpha * tin * (1.0 - out)
                    if a_row > 0.01 and rx1 > 0 and rx0 < W and ry0 + mh > 0 and ry0 < H:
                        size = mh * 2.6
                        span = (rx1 - rx0) + mh * 1.4
                        n = max(2, int(span / (size * 0.42)))
                        p.setOpacity(min(1.0, a_row * 1.35))
                        cx0 = rx0 - mh * 0.7
                        for i2 in range(n):
                            f = i2 / max(1, n - 1)
                            bob = math.sin(f * 3.1 + ph * 2.0) * mh * 0.22
                            sc = 0.78 + 0.34 * math.sin(f * 5.3 + ph)
                            sw = size * sc
                            p.drawPixmap(
                                QRectF(cx0 + f * (span - sw),
                                       ry0 + mh * 0.5 - sw * 0.5 + bob, sw, sw),
                                puff, QRectF(puff.rect()))
                        p.setOpacity(1.0)
                for x, w, txt, s, e in row:
                    if not txt.strip():
                        continue
                    cx, cy = ox + x + dx, by - met.ascent() + dy
                    if cx + w < 0 or cx > W or cy + mh < 0 or cy > H:
                        continue
                    a = alpha * tin * (1.0 - out)
                    if a <= 0.01:
                        continue
                    px, py = cx, cy + met.ascent()
                    p.setPen(QColor(TEXT.red(), TEXT.green(), TEXT.blue(),
                                    max(0, min(255, int(a * 255)))))
                    p.drawText(QPointF(px, py), txt)
                    frac = (0.0 if s is None or e is None or pos <= s else
                            (1.0 if pos >= e else (pos - s) / max(1e-6, e - s)))
                    if frac > 0 and act > 0.01:
                        av = max(0, min(255, int(act * (1.0 - out) * tin * 255)))
                        if frac >= 1.0:
                            p.setPen(QColor(sung.red(), sung.green(), sung.blue(), av))
                        else:
                            edge = px + w * frac
                            soft = max(0.75, self.edge * mh * 0.22)
                            g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                            g.setColorAt(0.0, QColor(sung.red(), sung.green(),
                                                     sung.blue(), av))
                            g.setColorAt(1.0, clear)
                            p.setPen(QPen(QBrush(g), 0))
                        p.drawText(QPointF(px, py), txt)
        if len(self.cloudy) > 400:
            cut = now - 4.0
            for key in [k2 for k2, v in self.cloudy.items() if v[6] < cut]:
                self.cloudy.pop(key, None)

    def _paint_loose(self, p, idx, ln, rows, fm, ox, y, pos, act, alpha,
                     rrows=(), rfm=None, ruby=(), rufm=None) -> None:
        """One line with every word cut loose from it.

        Each word is drawn on its own, at its resting position plus whatever
        offset the physics has accumulated, turned about its own centre. Two
        things are deliberately given up while this is on: depth blur, because
        blurring per word instead of per line would mean a pixmap per word per
        frame, and the ruby/furigana row, because a reading has nowhere to sit
        once the kanji it belongs to has floated off. Everything else -- the
        sung fill, the activation fade, the viewport falloff -- still applies,
        so the line reads normally apart from being scattered.

        Layout is untouched: `rows` is the same list the normal path uses, so
        wrapping, hit-testing and scrolling all still see the line where it was.
        """
        font = self.lyric_font(ln["background"])
        p.setFont(font)
        p.setOpacity(1.0)
        sung = self.sung_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ruh = self.ruby_h(rufm)
        rowh = fm.height() * 1.06 + ruh

        blocks = [(rows, fm, y + ruh + fm.ascent(), rowh, font, False)]
        if rrows and rfm is not None:
            ry = (y + ruh + fm.ascent() + len(rows) * rowh
                  + fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent())
            blocks.append((rrows, rfm, ry, rfm.height() * 1.04,
                           self.roman_font(ln), True))

        W, H = self.width(), self.height()
        for rws, met, top, step, fnt, is_rom in blocks:
            p.setFont(fnt)
            mh = met.height()
            for r_i, row in enumerate(rws):
                by = top + r_i * step
                for x, w, txt, s, e in row:
                    if not txt.strip():
                        continue
                    key = (idx, is_rom, r_i, round(x, 1), txt)
                    st = self.drift_of(key, ox + x, by - met.ascent(),
                                       w, met.height())
                    if st is None:
                        continue
                    px, py = st[0], st[1] + met.ascent()
                    if (px + w < 0 or px > W or py < -mh or py - mh > H):
                        continue
                    p.save()
                    if st[4]:
                        cx, cy = px + w * 0.5, py - met.ascent() * 0.35
                        p.translate(cx, cy)
                        p.rotate(st[4])
                        p.translate(-cx, -cy)
                    p.setPen(QColor(TEXT.red(), TEXT.green(), TEXT.blue(),
                                    max(0, min(255, int(alpha * 255)))))
                    p.drawText(QPointF(px, py), txt)
                    frac = (0.0 if s is None or e is None or pos <= s else
                            (1.0 if pos >= e else (pos - s) / max(1e-6, e - s)))
                    if frac > 0 and act > 0.01:
                        a = max(0, min(255, int(act * 255)))
                        if frac >= 1.0:
                            p.setPen(QColor(sung.red(), sung.green(), sung.blue(), a))
                        else:
                            edge = px + w * frac
                            soft = max(0.75, self.edge * met.height() * 0.22)
                            g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                            g.setColorAt(0.0, QColor(sung.red(), sung.green(),
                                                     sung.blue(), a))
                            g.setColorAt(1.0, clear)
                            p.setPen(QPen(QBrush(g), 0))
                        p.drawText(QPointF(px, py), txt)
                    p.restore()

    def _paint_line(self, p, idx, ln, rows, fm, x0, y, pos, live, rrows=(), rfm=None,
                    ruby=(), rufm=None) -> None:
        width = self._lyr_width()
        act = self.activation.get(idx, 0.0)
        ox = self.line_ox(ln, fm, x0)

        if ln.get("credits"):
            self._paint_credits(p, rows, fm, x0, y, width)
            return
        if not self.synced:
            p.setOpacity(0.82)
            p.drawPixmap(QPointF(ox - 10, y - 10), self.line_pixmap(idx, width, 0))
            p.setOpacity(1.0)
            return

        dist = min((abs(idx - j) for j in live), default=6) if live else 6
        if self.focus and live and self.browse < 0.5:
            if dist > self.focus + 1:
                return
            if dist == self.focus + 1:
                act = 0.0
        blur = 0.0 if dist == 0 else min(9.0, 1.4 * dist**1.35)
        blur *= (1.0 - act) * self.blur_scale * (1.0 - self.browse)
        falloff = max(0.10, 0.32 - 0.055 * max(0, dist - 1))
        if self.focus and live and dist == self.focus + 1 and self.browse < 0.5:
            falloff *= 0.35
        falloff += (0.60 - falloff) * self.browse if falloff < 0.60 else 0.0
        alpha = (falloff + 0.14 * act) * (0.8 if ln["background"] else 1.0)
        if idx == self.hover_idx:
            alpha = min(1.0, alpha + 0.22)
        alpha_free = alpha
        alpha *= self.vfade(y + fm.height() * 0.5)
        y = y + (1.0 - act) * 7.0 * (1 if idx in live else 0)

        if ln.get("dots"):
            self._paint_dots(p, ln, fm, ox, y, pos, act,
                             self.vfade(y + fm.height() * 0.5), width)
            return

        lo = int(blur)
        frac_b = blur - lo
        if self.clouds > 0:
            self._paint_cloud(p, idx, ln, rows, fm, ox, y, pos, act, alpha_free,
                              dist, x0, width, rrows, rfm, ruby, rufm)
            return
        if self.zero_g > 0:
            self._paint_loose(p, idx, ln, rows, fm, ox, y, pos, act, alpha_free,
                              rrows, rfm, ruby, rufm)
            return
        spin = self.spin_frag(rows, fm, ox, y, self.ruby_h(rufm), pos)
        p.save()
        if spin is not None:
            p.setClipRegion(QRegion(self.rect()) - QRegion(spin[-1].toAlignedRect()))
        p.setOpacity(alpha * (1.0 - frac_b))
        pad = 10 + lo * 6
        p.drawPixmap(QPointF(ox - pad, y - pad), self.line_pixmap(idx, width, lo))
        if frac_b > 0.01:
            pad = 10 + (lo + 1) * 6
            p.setOpacity(alpha * frac_b)
            p.drawPixmap(QPointF(ox - pad, y - pad), self.line_pixmap(idx, width, lo + 1))
        p.restore()
        p.setOpacity(1.0)

        if act <= 0.01:
            return
        p.save()
        font = self.lyric_font(ln["background"])
        p.setFont(font)
        sung = self.sung_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        now = time.monotonic()
        ruh = self.ruby_h(rufm)
        rufont = self.ruby_font(ln) if rufm is not None else None
        ry = y + ruh + fm.ascent()
        for r_i, row in enumerate(rows):
            if rufont is not None and r_i < len(ruby):
                p.setFont(rufont)
                by = ry - fm.ascent() - ruh + rufm.ascent()
                for cx, read, s, e in ruby[r_i]:
                    if s is None or e is None or pos < s:
                        continue
                    p.setPen(sung)
                    p.setOpacity(act * (1.0 if pos >= e else 0.55))
                    p.drawText(QPointF(ox + cx - rufm.horizontalAdvance(read) / 2, by), read)
                p.setOpacity(1.0)
                p.setFont(font)
            for x, w, txt, s, e in row:
                px = ox + x
                if s is None or e is None:
                    continue
                frac = 1.0 if pos >= e else (0.0 if pos <= s else (pos - s) / max(1e-6, e - s))
                if frac <= 0:
                    continue
                singing = s <= pos < e
                held = min(1.0, max(0.0, (e - s - 0.18) / 1.1))
                if self.glow_scale > 0 and singing and held > 0.02:
                    core = txt.rstrip()
                    lenf = min(1.0, max(0.0, (len(core.strip()) - 1) / 7.0))
                    strength = held * (0.55 + 0.45 * lenf)
                    radius = max(1, int(2 + 8 * strength))
                    gp = self.glow_pixmap(core, font, radius)
                    swell = math.sin(math.pi * frac) ** 0.7
                    shimmer = 0.86 + 0.14 * math.sin(now * 6.5 + s * 4.0)
                    grow = 1.0 + 0.38 * swell * strength
                    gw, gh = gp.width(), gp.height()
                    pad = radius * 3
                    ccx = px - pad + gw / 2
                    ccy = ry - fm.ascent() - pad + gh / 2
                    p.setOpacity(min(1.0, act * (0.16 + 0.66 * strength)
                                     * swell * shimmer * self.glow_scale))
                    p.drawPixmap(
                        QRectF(ccx - gw * grow / 2, ccy - gh * grow / 2,
                               gw * grow, gh * grow),
                        gp, QRectF(gp.rect()),
                    )
                    p.setOpacity(1.0)
                p.save()
                gate = 1.0 if self.pop_min <= 0 else min(1.0, (e - s - self.pop_min) / 0.2)
                if self.pop > 0 and singing and gate > 0:
                    k = math.sin(math.pi * frac) * act * gate
                    lift = k * self.pop * fm.height() * 0.055
                    grow = 1.0 + k * self.pop * 0.035
                    p.translate(px + w * 0.5, ry - fm.ascent() * 0.35 - lift)
                    p.scale(grow, grow)
                    p.translate(-(px + w * 0.5), -(ry - fm.ascent() * 0.35))
                if spin is not None and (r_i, x) == (spin[0], spin[1]):
                    cx, cy = px + w * 0.5, ry - fm.ascent() * 0.35
                    p.translate(cx, cy)
                    p.rotate(360.0 * self.spin * frac)
                    p.translate(-cx, -cy)
                    p.setPen(TEXT)
                    p.setOpacity(alpha)
                    p.drawText(QPointF(px, ry), txt)
                if frac >= 1.0:
                    p.setPen(sung)
                else:
                    edge = px + w * frac
                    soft = max(0.75, self.edge * fm.height() * 0.22)
                    g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                    g.setColorAt(0.0, sung)
                    g.setColorAt(1.0, clear)
                    p.setPen(QPen(QBrush(g), 0))
                p.setOpacity(act)
                p.drawText(QPointF(px, ry), txt)
                p.restore()
            ry += fm.height() * 1.06 + ruh
        if rrows and rfm is not None:
            rfont = self.roman_font(ln)
            p.setFont(rfont)
            ry += fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent()
            for row in rrows:
                for x, w, txt, s, e in row:
                    if s is None or e is None:
                        continue
                    frac = (1.0 if pos >= e else
                            (0.0 if pos <= s else (pos - s) / max(1e-6, e - s)))
                    if frac <= 0:
                        continue
                    px = ox + x
                    if frac >= 1.0:
                        p.setPen(sung)
                    else:
                        edge = px + w * frac
                        soft = max(0.75, self.edge * rfm.height() * 0.22)
                        g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                        g.setColorAt(0.0, sung)
                        g.setColorAt(1.0, clear)
                        p.setPen(QPen(QBrush(g), 0))
                    p.setOpacity(act * 0.85)
                    p.drawText(QPointF(px, ry), txt)
                ry += rfm.height() * 1.04
        p.restore()

    def credit_font(self) -> QFont:
        f = QFont(self.family, max(9, int(self.lyric_px() * 0.30)))
        f.setWeight(QFont.Weight.DemiBold)
        return f

    def _paint_credits(self, p, rows, fm, x0: float, y: float, width: float) -> None:
        """The footer under the last line. Dim and unanimated -- it is not part
        of the song and should never look like the next thing to be sung."""
        align = {"center": Qt.AlignmentFlag.AlignHCenter,
                 "right": Qt.AlignmentFlag.AlignRight}.get(
                     self.align, Qt.AlignmentFlag.AlignLeft)
        p.save()
        p.setFont(self.credit_font())
        ry = y + fm.height() * 1.4
        for i, row in enumerate(rows):
            p.setPen(QColor(234, 234, 234, 120 if i == 0 else 88))
            p.drawText(QRectF(x0, ry, width, fm.height() * 1.4),
                       int(align | Qt.AlignmentFlag.AlignVCenter), row)
            ry += fm.height() * 1.4
        p.restore()

    def sung_color(self, ln: dict | None = None) -> QColor:
        """White unless asked otherwise; 'auto' lifts a bright tint out of the
        cover so the fill belongs to the artwork.

        A duet's second voice can take a colour of its own. The flag already
        moves those lines to the other side of the screen, which says "someone
        else" only if you know to read it; a different fill says it outright.
        """
        if ln is not None and ln.get("opposite") and self.duet_color != "off":
            return self._duet_tint()
        if self._sung is not None:
            return self._sung
        c = self.palette[0]
        h, s, v, _ = c.getHsv()
        return QColor.fromHsv(h, min(90, int(s * 0.45)), 255)

    def _duet_tint(self) -> QColor:
        """The second voice's fill. A palette entry away from the lead's, so the
        two still belong to the same cover rather than one being pasted on.

        Falls back to the lead's own colour on a single-colour cover, where
        palette[1] does not exist and there is no second tint to be had.
        """
        if self._duet_rgb is not None:
            return self._duet_rgb
        c = self.palette[min(1, len(self.palette) - 1)] if self.palette else TEXT
        h, s, v, _ = c.getHsv()
        return QColor.fromHsv(h, min(140, int(s * 0.8)), 255)

    def _paint_dots(self, p, ln, fm, ox, y, pos, act, alpha, width) -> None:
        """Instrumental break, the way Apple Music shows it: three dots that
        fill across the gap so a 40-second solo is not just dead air."""
        r = fm.height() * 0.19
        gap = r * 3.4
        span = max(1e-6, ln["end"] - ln["start"])
        t = max(0.0, min(1.0, (pos - ln["start"]) / span))
        run = gap * 2
        slack = {"left": 0.0, "center": (width - run) / 2, "right": width - run - r}
        cx = ox + r + slack[self.line_align(ln)]
        cy = y + fm.height() * 0.55
        now = time.monotonic()
        cue = max(0.0, (t - 0.88) / 0.12) if t > 0.88 else 0.0
        p.setPen(Qt.PenStyle.NoPen)
        e = self.beat_energy()
        for k in range(3):
            fill = max(0.0, min(1.0, t * 3 - k))
            if e > 0.004:
                breathe = 1.0 + 0.34 * e * act
            else:
                breathe = 1.0 + 0.10 * math.sin(now * 2.4 + k * 0.8) * act
            rad = r * (0.62 + 0.40 * fill + 0.25 * cue) * breathe
            a = alpha * (0.22 + 0.78 * fill) * (0.30 + 0.70 * act)
            p.setBrush(QColor(234, 234, 234, int(255 * max(0.0, min(1.0, a)))))
            p.drawEllipse(QPointF(cx + k * gap, cy), rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_toast(self, p, W: int, H: int) -> None:
        left = self.toast_until - time.monotonic()
        a = min(1.0, left / 0.35)
        f = self.ui_font(max(11, W * 0.011))
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(self.toast_text) + 36
        h = fm.height() + 18
        box = QRectF((W - w) / 2, H - h - max(38.0, H * 0.085), w, h)
        p.setPen(QColor(234, 234, 234, int(45 * a)))
        p.setBrush(QColor(24, 24, 29, int(235 * a)))
        p.drawRoundedRect(box, h / 2, h / 2)
        p.setFont(f)
        p.setPen(QColor(234, 234, 234, int(240 * a)))
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self.toast_text)

    def _paint_help(self, p, W: int, H: int) -> None:
        f = self.ui_font(max(11, W * 0.0105))
        fk = self.ui_font(max(11, W * 0.0105), QFont.Weight.Black)
        fm, fmk = QFontMetricsF(f), QFontMetricsF(fk)
        rowh = fm.height() * 1.62
        keyw = max(fmk.horizontalAdvance(k) for k, _ in HELP_KEYS) + 20
        descw = max(fm.horizontalAdvance(d) for _, d in HELP_KEYS) + 24
        colw = keyw + descw
        rows = (len(HELP_KEYS) + 1) // 2
        box = QRectF(0, 0, colw * 2 + 56, rows * rowh + 76)
        box.moveCenter(QPointF(W / 2, H / 2))
        p.fillRect(self.rect(), QColor(6, 6, 9, 175))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 25, 240))
        p.drawRoundedRect(box, 18, 18)
        p.setFont(self.ui_font(max(12, W * 0.0125), QFont.Weight.Black))
        p.setPen(TEXT)
        p.drawText(QRectF(box.x(), box.y() + 20, box.width(), 30),
                   int(Qt.AlignmentFlag.AlignCenter), "Keys")
        for i, (k, d) in enumerate(HELP_KEYS):
            cx = box.x() + 28 + (i % 2) * colw
            cy = box.y() + 62 + (i // 2) * rowh
            p.setFont(fk)
            p.setPen(QColor(234, 234, 234, 235))
            p.drawText(QRectF(cx, cy, keyw, rowh), int(Qt.AlignmentFlag.AlignLeft), k)
            p.setFont(f)
            p.setPen(QColor(234, 234, 234, 150))
            p.drawText(QRectF(cx + keyw, cy, descw, rowh),
                       int(Qt.AlignmentFlag.AlignLeft), d)

    # -- search ----------------------------------------------------------
    # -------------------------------------------------------- browse painting
    def browse_metrics(self, W: int) -> dict:
        """One place for every browse dimension, so paint and hit-test agree."""
        gutter = max(18.0, W * 0.022)
        cw = max(118.0, min(190.0, W / 6.5))
        t_h = QFontMetricsF(self.ui_font(max(10, cw * 0.098))).height()
        s_h = QFontMetricsF(self.ui_font(max(9, cw * 0.086))).height()
        return {"gutter": gutter, "cw": cw, "gap": 14.0,
                "card_h": cw + 8 + t_h * 1.2 + s_h * 1.3,
                "bar_h": max(52.0, W * 0.042), "row_h": 56.0}

    def _paint_browse(self, p, W: int, H: int) -> None:
        m = self.browse_metrics(W)
        p.drawPixmap(0, 0, self.scene_layer())
        p.fillRect(self.rect(), QColor(8, 8, 11, 168))

        self.browse_rects = []
        p.save()
        p.setClipRect(QRectF(0, m["bar_h"], W, H - m["bar_h"]))
        if self.browse_tab == "home":
            self.content_h_browse = self._paint_shelves(p, W, H, m)
        elif self.browse_tab == "queue":
            self.content_h_browse = self._paint_browse_queue(p, W, H, m)
        else:
            self.content_h_browse = self._paint_browse_search(p, W, H, m)
        p.restore()
        self._paint_browse_bar(p, W, H, m)

    def _paint_browse_bar(self, p, W: int, H: int, m: dict) -> None:
        bh = m["bar_h"]
        p.fillRect(QRectF(0, 0, W, bh), QColor(12, 12, 14, 232))
        p.setPen(QColor(234, 234, 234, 22))
        p.drawLine(QPointF(0, bh), QPointF(W, bh))
        p.setPen(Qt.PenStyle.NoPen)

        ft = self.ui_font(max(11, W * 0.0105), QFont.Weight.Black)
        fmt = QFontMetricsF(ft)
        p.setFont(ft)
        x = m["gutter"]
        for tab, label in (("home", "Home"), ("search", "Search"), ("queue", "Queue")):
            w = fmt.horizontalAdvance(label) + 30
            r = QRectF(x, (bh - fmt.height() * 1.7) / 2, w, fmt.height() * 1.7)
            on = self.browse_tab == tab
            p.setBrush(QColor(234, 234, 234, 30 if on else 10))
            p.drawRoundedRect(r, 7, 7)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(234, 234, 234, 240 if on else 130))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), label)
            if on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 205))
                p.drawRect(QRectF(r.x() + 8, r.bottom() + 1, r.width() - 16, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
            self.browse_rects.append(("tab", tab, r))
            p.setPen(Qt.PenStyle.NoPen)
            x += w + 6

        label = "♪  Lyrics"
        w = fmt.horizontalAdvance(label) + 40
        r = QRectF(W - m["gutter"] - w, (bh - fmt.height() * 1.8) / 2,
                   w, fmt.height() * 1.8)
        acc = self.palette[0] if self.palette else QColor(90, 90, 100)
        hot = self.browse_hover and self.browse_hover[0] == "lyrics_btn"
        p.setBrush(QColor(acc.red(), acc.green(), acc.blue(), 235 if hot else 200))
        p.drawRoundedRect(r, 9, 9)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(255, 255, 255, 245))
        p.setFont(ft)
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), label)
        self.browse_rects.append(("lyrics_btn", None, r))

        if self.backfill_total:
            frac = min(1.0, self.backfill_n / max(1, self.backfill_total))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(234, 234, 234, 150))
            p.drawRect(QRectF(0, bh, W * frac, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)

    def _shelf_label(self, item: dict, kind: str) -> tuple[str, str, str]:
        """(primary, secondary, artwork url) for one card, whatever it is."""
        if kind == "local":
            title = item.get("title") or ""
            if not title:
                title = (item.get("lines") or [""])[0][:40] or item.get("id", "")
            return title, item.get("artist") or "", ""
        return item.get("name", ""), item.get("sub", ""), item.get("art", "")

    def _paint_shelves(self, p, W: int, H: int, m: dict) -> float:
        y = m["bar_h"] + 18 - self.browse_scroll
        gut, cw, gap = m["gutter"], m["cw"], m["gap"]
        fh = self.ui_font(max(13, W * 0.0125), QFont.Weight.Black)
        ft = self.ui_font(max(10, cw * 0.098))
        fs = self.ui_font(max(9, cw * 0.086))
        fmh, fmt_, fms = QFontMetricsF(fh), QFontMetricsF(ft), QFontMetricsF(fs)
        per = max(1, int((W - 2 * gut + gap) // (cw + gap)))

        if not self.shelves:
            p.setFont(ft)
            p.setPen(QColor(234, 234, 234, 140))
            p.drawText(QRectF(gut, m["bar_h"] + 60, W - 2 * gut, 40),
                       int(Qt.AlignmentFlag.AlignLeft),
                       "Nothing to show yet — press Tab to search.")
            return 0.0

        for sh in self.shelves:
            items = sh["items"][:per] if sh["kind"] != "now" else sh["items"]
            if not items:
                continue
            if y + 40 > m["bar_h"] and y < H:
                p.setFont(fh)
                p.setPen(QColor(234, 234, 234, 235))
                p.drawText(QRectF(gut, y, W - 2 * gut, fmh.height() * 1.4),
                           int(Qt.AlignmentFlag.AlignLeft), sh["title"])
            y += fmh.height() * 1.4 + 8

            if sh["kind"] == "now":
                h = self._paint_now_card(p, gut, y, W - 2 * gut, m, ft, fs)
                y += h + 26
                continue

            for i, item in enumerate(items):
                x = gut + i * (cw + gap)
                r = QRectF(x, y, cw, m["card_h"])
                if r.bottom() > m["bar_h"] and r.top() < H:
                    self._paint_card(p, r, item, sh["kind"], cw, ft, fs, fmt_, fms)
                self.browse_rects.append((sh["kind"], item, r))
            y += m["card_h"] + 26
        return max(0.0, y + self.browse_scroll - H + 40)

    def _paint_card(self, p, r: QRectF, item: dict, kind: str, cw: float,
                    ft, fs, fmt_, fms) -> None:
        primary, secondary, url = self._shelf_label(item, kind)
        art = QRectF(r.x(), r.y(), cw, cw)
        hot = (self.browse_hover and self.browse_hover[1] is item)
        if hot:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(234, 234, 234, 20))
            p.drawRoundedRect(r.adjusted(-8, -8, 8, 8), 10, 10)
            p.setBrush(Qt.BrushStyle.NoBrush)
        pm = self.thumb(url) if url else None
        path = QPainterPath()
        path.addRoundedRect(art, cw * 0.05, cw * 0.05)
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        if pm is not None:
            p.drawPixmap(art, pm, QRectF(pm.rect()))
        else:
            p.fillRect(art, QColor(255, 255, 255, 14))
        p.restore()
        p.setFont(ft)
        p.setPen(QColor(234, 234, 234, 232))
        p.drawText(QRectF(r.x(), art.bottom() + 6, cw, fmt_.height() * 1.2),
                   int(Qt.AlignmentFlag.AlignLeft),
                   fmt_.elidedText(primary, Qt.TextElideMode.ElideRight, cw))
        if secondary:
            p.setFont(fs)
            p.setPen(QColor(234, 234, 234, 130))
            p.drawText(QRectF(r.x(), art.bottom() + 6 + fmt_.height() * 1.2, cw,
                              fms.height() * 1.2),
                       int(Qt.AlignmentFlag.AlignLeft),
                       fms.elidedText(secondary, Qt.TextElideMode.ElideRight, cw))

    def _paint_now_card(self, p, x: float, y: float, w: float, m: dict, ft, fs) -> float:
        """The current track, as a wide card that doubles as 'back to lyrics'."""
        side = min(112.0, m["cw"] * 0.8)
        r = QRectF(x, y, w, side)
        hot = self.browse_hover and self.browse_hover[0] == "now"
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(234, 234, 234, 26 if hot else 16))
        p.drawRoundedRect(r, 12, 12)
        p.setBrush(Qt.BrushStyle.NoBrush)
        art = QRectF(x + 10, y + 10, side - 20, side - 20)
        if self.art_full:
            path = QPainterPath()
            path.addRoundedRect(art, 6, 6)
            p.save()
            p.setClipPath(path, Qt.ClipOperation.IntersectClip)
            p.drawPixmap(art, self.art_full, QRectF(self.art_full.rect()))
            p.restore()
        else:
            p.fillRect(art, QColor(255, 255, 255, 14))
        meta = self.clock.meta
        tx = art.right() + 16
        fmt_, fms = QFontMetricsF(ft), QFontMetricsF(fs)
        p.setFont(ft)
        p.setPen(QColor(234, 234, 234, 235))
        p.drawText(QRectF(tx, y + side * 0.28, w - (tx - x) - 16, fmt_.height() * 1.2),
                   int(Qt.AlignmentFlag.AlignLeft),
                   fmt_.elidedText(meta.get("title", "—"),
                                   Qt.TextElideMode.ElideRight, w - (tx - x) - 16))
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 140))
        p.drawText(QRectF(tx, y + side * 0.28 + fmt_.height() * 1.2,
                          w - (tx - x) - 16, fms.height() * 1.3),
                   int(Qt.AlignmentFlag.AlignLeft),
                   fms.elidedText(self.artist() or "", Qt.TextElideMode.ElideRight,
                                  w - (tx - x) - 16))
        self.browse_rects.append(("now", None, r))
        return side

    def _paint_detail(self, p, W: int, H: int) -> None:
        """The song or album page. Cover, credits, and what can be opened next."""
        d = self.detail or {}
        gut = max(40.0, W * 0.06)
        self.detail_rows = []
        self.hot = []
        p.fillRect(QRectF(0, 0, W, H), QColor(9, 9, 12))
        if self.art_bg and self.bg_mode == "art":
            p.setOpacity(0.30)
            p.drawPixmap(QRectF(0, 0, W, H), self.art_bg,
                         self._art_src(self.art_bg, 0.0))
            p.setOpacity(1.0)
            p.fillRect(QRectF(0, 0, W, H), QColor(9, 9, 12, 205))

        ft = self.ui_font(max(20, W * 0.026), QFont.Weight.Black)
        fa = self.ui_font(max(13, W * 0.0135), QFont.Weight.Medium)
        fs = self.ui_font(max(10, W * 0.0092))
        fm_t, fm_a, fm_s = QFontMetricsF(ft), QFontMetricsF(fa), QFontMetricsF(fs)

        back = "back" if self.detail_stack else "close"
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 120))
        p.drawText(QRectF(gut, 22, W - 2 * gut, fm_s.height()),
                   int(Qt.AlignmentFlag.AlignLeft), f"Esc  {back}")

        y = 22 + fm_s.height() + 26
        side = min(W * 0.20, H * 0.30)
        album = self.albums.get(self.clock.tid or "") or {}
        data = d.get("data")
        is_album = d.get("kind") in ("album", "artist")

        pm = self.art_full
        if is_album and isinstance(data, dict) and data.get("art"):
            pm = self.thumb(data["art"]) or self.art_full
        if pm:
            path = QPainterPath()
            path.addRoundedRect(QRectF(gut, y, side, side), side * 0.04, side * 0.04)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(QRectF(gut, y, side, side), pm, QRectF(pm.rect()))
            p.restore()

        tx = gut + side + 28
        tw = W - tx - gut
        ty = y + 6
        if is_album:
            name = (data or {}).get("name") or "…"
            who = ", ".join(a["name"] for a in ((data or {}).get("artists") or []))
            if d.get("kind") == "artist":
                who = "Artist"
            extra = (data or {}).get("year") or ""
        else:
            name = self.song_title()
            who, guests = self.artist_split()
            extra = guests
        p.setFont(ft)
        p.setPen(TEXT)
        for row in wrap_rows(fm_t, name, tw, 2, elide=False)[:2]:
            self._scroll_text(p, row, QRectF(tx, ty, tw, fm_t.height() * 1.15), fm_t,
                              f"detail.title{ty:.0f}")
            ty += fm_t.height() * 1.15
        ty += 8
        p.setFont(fa)
        arect = QRectF(tx, ty, min(tw, fm_a.horizontalAdvance(who) + 4),
                       fm_a.height() * 1.2)
        lead_a = None
        if not is_album:
            lead_a = (split_artists(self.clock.meta.get("title", ""),
                                    self.credits())[0] or [{}])[0]
            if lead_a.get("uri"):
                self.hot.append((arect, "artist", lead_a["uri"]))
        hot_a = lead_a is not None and lead_a.get("uri") and arect.contains(self.mouse_pos)
        p.setPen(QColor(234, 234, 234, 235 if hot_a else 180))
        self._scroll_text(p, who, QRectF(tx, ty, tw, fm_a.height() * 1.2), fm_a,
                          "detail.artist")
        ty += fm_a.height() * 1.35
        if extra:
            p.setFont(fs)
            p.setPen(QColor(234, 234, 234, 120))
            self._scroll_text(p, extra, QRectF(tx, ty, tw, fm_s.height() * 1.2),
                              fm_s, "detail.extra")
            ty += fm_s.height() * 1.5

        if not is_album:
            label = album.get("name") or self.clock.meta.get("album", "")
            if label:
                p.setFont(fa)
                box = QRectF(tx, ty, min(tw, fm_a.horizontalAdvance(label) + 26),
                             fm_a.height() * 1.4)
                hot = box.contains(self.mouse_pos)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 34 if hot else 20))
                p.drawRoundedRect(box, 8, 8)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QColor(234, 234, 234, 235 if hot else 175))
                p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), label)
                if album.get("uri"):
                    self.hot.append((box, "album", album["uri"]))
                ty += fm_a.height() * 1.7
            dur = self.clock.meta.get("length", 0.0)
            bits = [fmt_time(dur)] if dur else []
            if self.body is not None:
                bits.append(self.source_name(SL.payload(self.body)))
                bits.append({"syllable": "word-synced", "line": "line-synced",
                             "static": "unsynced"}.get(LS.quality(self.body), "—"))
            if bits:
                p.setFont(fs)
                p.setPen(QColor(234, 234, 234, 130))
                p.drawText(QRectF(tx, ty, tw, fm_s.height() * 1.4),
                           int(Qt.AlignmentFlag.AlignLeft), "  ·  ".join(bits))

        y += side + 34
        if is_album:
            tracks = (data or {}).get("tracks") if isinstance(data, dict) else None
            p.setFont(fs)
            p.setPen(QColor(234, 234, 234, 130))
            p.drawText(QRectF(gut, y, W - 2 * gut, fm_s.height() * 1.4),
                       int(Qt.AlignmentFlag.AlignLeft),
                       "loading…" if data is None else
                       (f"{len(tracks)} "
                        + ("popular tracks" if d.get("kind") == "artist" else "tracks")
                        if tracks else "no tracks"))
            y += fm_s.height() * 2.0 - self.detail_scroll
            here = self.clock.tid or ""
            p.save()
            p.setClipRect(QRectF(0, 90, W, H - 90))
            for i, t in enumerate(tracks or []):
                r = QRectF(gut, y, W - 2 * gut, 34)
                if r.bottom() > 90 and r.top() < H:
                    playing = t.get("uri", "").split(":")[-1] == here
                    if r.contains(self.mouse_pos) or playing:
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor(234, 234, 234, 30 if playing else 18))
                        p.drawRoundedRect(r, 7, 7)
                        p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setFont(fs)
                    p.setPen(QColor(234, 234, 234, 110))
                    p.drawText(QRectF(r.x() + 10, r.y(), 30, r.height()),
                               int(Qt.AlignmentFlag.AlignVCenter), str(i + 1))
                    p.setFont(fa)
                    p.setPen(TEXT if playing else QColor(234, 234, 234, 205))
                    p.drawText(QRectF(r.x() + 46, r.y(), r.width() - 130, r.height()),
                               int(Qt.AlignmentFlag.AlignVCenter),
                               fm_a.elidedText(t.get("name", ""),
                                               Qt.TextElideMode.ElideRight,
                                               r.width() - 140))
                    ms = t.get("ms") or 0
                    if ms:
                        p.setFont(fs)
                        p.setPen(QColor(234, 234, 234, 110))
                        p.drawText(QRectF(r.x(), r.y(), r.width() - 12, r.height()),
                                   int(Qt.AlignmentFlag.AlignRight
                                       | Qt.AlignmentFlag.AlignVCenter),
                                   fmt_time(ms / 1000.0))
                self.detail_rows.append((r, t))
                y += 36
            p.restore()

    def _paint_browse_search(self, p, W: int, H: int, m: dict) -> float:
        gut = m["gutter"]
        fq = self.ui_font(max(15, W * 0.016), QFont.Weight.Black)
        ft = self.ui_font(max(11, W * 0.0105))
        fs = self.ui_font(max(9, W * 0.0086))
        fmq, fmt_, fms = QFontMetricsF(fq), QFontMetricsF(ft), QFontMetricsF(fs)
        y = m["bar_h"] + 20
        caret = "▏" if int(time.monotonic() * 2) % 2 else " "
        p.setFont(fq)
        p.setPen(TEXT if self.bq else QColor(234, 234, 234, 110))
        p.drawText(QRectF(gut, y, W - 2 * gut, fmq.height() * 1.4),
                   int(Qt.AlignmentFlag.AlignLeft),
                   (self.bq + caret) if self.bq else "Search Spotify…" + caret)
        y += fmq.height() * 1.5
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 120))
        note = ("searching…" if self.bq_busy else
                (f"{len(self.bq_hits)} results" if self.bq_hits else
                 ("no results" if len(self.bq) >= 2 else "type to search")))
        p.drawText(QRectF(gut, y, W - 2 * gut, fms.height() * 1.4),
                   int(Qt.AlignmentFlag.AlignLeft),
                   f"{note}   ↑↓ pick   Enter play   Esc back")
        y += fms.height() * 1.8 - self.browse_scroll

        rh = m["row_h"]
        section = None
        for i, hit in enumerate(self.bq_hits):
            if hit.get("section") != section:
                section = hit.get("section")
                if y + 30 > m["bar_h"] and y < H:
                    p.setFont(self.ui_font(max(10, W * 0.0092), QFont.Weight.Black))
                    p.setPen(QColor(234, 234, 234, 190))
                    p.drawText(QRectF(gut, y, W - 2 * gut, 26),
                               int(Qt.AlignmentFlag.AlignLeft), section or "")
                y += 30
            r = QRectF(gut, y, W - 2 * gut, rh)
            if r.bottom() > m["bar_h"] and r.top() < H:
                self._paint_hit_row(p, r, hit, i == self.bq_sel, ft, fs, fmt_, fms)
            self.browse_rects.append(("hit", hit, r))
            y += rh
        return max(0.0, y + self.browse_scroll - H + 40)

    def _paint_browse_queue(self, p, W: int, H: int, m: dict) -> float:
        """What is playing and what comes after it.

        Two sections, as Spotify has them: things put there by hand, then what
        the current context would play anyway.
        """
        gut = m["gutter"]
        ft = self.ui_font(max(11, W * 0.0105))
        fs = self.ui_font(max(9, W * 0.0086))
        fh = self.ui_font(max(10, W * 0.0092), QFont.Weight.Black)
        fmt_, fms = QFontMetricsF(ft), QFontMetricsF(fs)
        y = m["bar_h"] + 18 - self.browse_scroll
        rh = m["row_h"]

        def header(text: str, yy: float) -> float:
            if yy + 30 > m["bar_h"] and yy < H:
                p.setFont(fh)
                p.setPen(QColor(234, 234, 234, 190))
                p.drawText(QRectF(gut, yy, W - 2 * gut, 26),
                           int(Qt.AlignmentFlag.AlignLeft), text)
            return yy + 32

        if self.queue_cur:
            y = header("Now playing", y)
            r = QRectF(gut, y, W - 2 * gut, rh)
            if r.bottom() > m["bar_h"] and r.top() < H:
                self._paint_hit_row(p, r, self.queue_cur, True, ft, fs, fmt_, fms,
                                    inline=True)
            self.browse_rects.append(("now", None, r))
            y += rh + 14

        if not self.queue_items:
            p.setFont(ft)
            p.setPen(QColor(234, 234, 234, 140))
            p.drawText(QRectF(gut, y + 10, W - 2 * gut, 40),
                       int(Qt.AlignmentFlag.AlignLeft),
                       "Nothing queued." if self.queue_at else "Reading the queue…")
            return 0.0

        section = None
        for item in self.queue_items:
            src = item.get("src")
            if src != section:
                section = src
                y = header("Next in queue" if src == "queued" else "Next up", y)
            r = QRectF(gut, y, W - 2 * gut, rh)
            if r.bottom() > m["bar_h"] and r.top() < H:
                self._paint_hit_row(p, r, item, False, ft, fs, fmt_, fms,
                                    inline=True)
            self.browse_rects.append(("queue", item, r))
            y += rh
        return max(0.0, y + self.browse_scroll - H + 40)

    def _paint_hit_row(self, p, r: QRectF, hit: dict, sel: bool,
                       ft, fs, fmt_, fms, inline: bool = False) -> None:
        if sel or (self.browse_hover and self.browse_hover[1] is hit):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(234, 234, 234, 26))
            p.drawRoundedRect(r, 8, 8)
            p.setBrush(Qt.BrushStyle.NoBrush)
        side = r.height() - 12
        art = QRectF(r.x() + 6, r.y() + 6, side, side)
        pm = self.thumb(hit.get("art", ""))
        path = QPainterPath()
        path.addRoundedRect(art, 4, 4)
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        if pm is not None:
            p.drawPixmap(art, pm, QRectF(pm.rect()))
        else:
            p.fillRect(art, QColor(255, 255, 255, 14))
        p.restore()
        tx = art.right() + 12
        tw = r.right() - tx - 70
        name, sub = hit.get("name", ""), hit.get("sub", "")
        if inline:
            box = QRectF(tx, r.y(), tw, r.height())
            align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            p.setFont(ft)
            p.setPen(QColor(234, 234, 234, 235 if sel else 205))
            if not sub:
                p.drawText(box, align,
                           fmt_.elidedText(name, Qt.TextElideMode.ElideRight, tw))
            else:
                sep = "   ·   "
                sep_w = fmt_.horizontalAdvance(sep)
                sw = min(fms.horizontalAdvance(sub), max(60.0, tw * 0.45))
                nw = max(40.0, min(fmt_.horizontalAdvance(name), tw - sep_w - sw))
                p.drawText(QRectF(tx, r.y(), nw, r.height()), align,
                           fmt_.elidedText(name, Qt.TextElideMode.ElideRight, nw))
                p.setPen(QColor(234, 234, 234, 105))
                p.drawText(QRectF(tx + nw, r.y(), sep_w, r.height()), align, sep)
                p.setFont(fs)
                p.setPen(QColor(234, 234, 234, 150))
                rest = max(0.0, tw - nw - sep_w)
                p.drawText(QRectF(tx + nw + sep_w, r.y(), rest, r.height()), align,
                           fms.elidedText(sub, Qt.TextElideMode.ElideRight, rest))
        else:
            p.setFont(ft)
            p.setPen(QColor(234, 234, 234, 235 if sel else 200))
            p.drawText(QRectF(tx, r.y() + 8, tw, fmt_.height() * 1.2),
                       int(Qt.AlignmentFlag.AlignLeft),
                       fmt_.elidedText(name, Qt.TextElideMode.ElideRight, tw))
            p.setFont(fs)
            p.setPen(QColor(234, 234, 234, 130))
            p.drawText(QRectF(tx, r.y() + 8 + fmt_.height() * 1.2, tw, fms.height() * 1.3),
                       int(Qt.AlignmentFlag.AlignLeft),
                       fms.elidedText(sub, Qt.TextElideMode.ElideRight, tw))
        if hit.get("ms"):
            p.setPen(QColor(234, 234, 234, 110))
            p.drawText(QRectF(r.right() - 64, r.y(), 56, r.height()),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       fmt_time(hit["ms"] / 1000.0))

    def thumb(self, url: str):
        """Cached cover for a card, or None while it is still being fetched."""
        if not url or not self.browse_art:
            return None
        return self.art_cache.get(url)

    # ---------------------------------------------------------------- browse
    def open_browse(self, tab: str = "home") -> None:
        """Leave the lyrics for the home/search screen."""
        self.editing = self.show_info = self.show_search = False
        self.view, self.browse_tab = "browse", tab
        self.browse_scroll = self.browse_scroll_target = 0.0
        self.browse_hover = None
        if not self.index.songs and not self.index.load() and not self.indexing:
            self.indexing = True
            self.toast("indexing your cached lyrics…")
            self.fetcher.request_index()
        elif self.index.stale and not self.indexing:
            self.indexing = True
            self.toast("refreshing your lyric index…")
            self.fetcher.request_index()
        if time.monotonic() - self.recents_at > 120:
            self.fetcher.request_recents()
        if not self.suggest:
            self.fetcher.request_suggest("")
        if time.monotonic() - self.discover_at > 600:
            self.fetcher.request_discover()
        songs = self.index.songs or []
        if songs and sum(1 for x in songs if x.get("title")) < len(songs) * 0.25 \
                and not self.backfill_total:
            self.start_backfill()
        self.build_home()
        self.update()

    def close_browse(self) -> None:
        self.view = "lyrics"
        self.browse_hover = None
        self.set_cursor(Qt.CursorShape.ArrowCursor)
        self.update()

    # ---------------------------------------------------------------- detail
    def open_detail(self, kind: str, payload=None) -> None:
        """The song, or the album it is on, as a page of its own.

        One view for both: an album opened from a song is the same screen with a
        different subject, so going song -> album -> back is a stack rather than
        two screens that each have to know about the other.
        """
        if kind in ("album", "artist"):
            uri = payload
            if kind == "album" and not uri:
                uri = (self.albums.get(self.clock.tid or "") or {}).get("uri")
            if not uri:
                self.toast(f"no {kind} for this track")
                return
            if self.detail:
                self.detail_stack.append(self.detail)
            self.detail = {"kind": kind, "uri": uri, "data": None}
            self.fetcher.request_album(uri, kind)
        else:
            self.detail = {"kind": "song", "uri": self.clock.tid or "", "data": None}
            self.detail_stack = []
        self.editing = self.show_info = self.show_search = False
        self.view = "detail"
        self.detail_scroll = 0.0
        self.update()

    def close_detail(self) -> None:
        """Back one step, or out to the lyrics if this was the first page."""
        if self.detail_stack:
            self.detail = self.detail_stack.pop()
            if self.detail.get("kind") in ("album", "artist") \
                    and not self.detail.get("data"):
                self.fetcher.request_album(self.detail["uri"], self.detail["kind"])
        else:
            self.detail = None
            self.view = "lyrics"
        self.detail_scroll = 0.0
        self.set_cursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def on_album(self, uri, got) -> None:
        if self.detail and self.detail.get("uri") == uri:
            self.detail["data"] = got if isinstance(got, dict) else {}
            self.update()

    def build_home(self) -> None:
        """Assemble the home shelves.

        Called on state changes only -- opening browse, new recents, a finished
        index, a track change. NEVER from paintEvent: the sampled shelf below
        would pick different songs on every frame.
        """
        songs = self.index.songs or []
        shelves: list[dict] = []
        if self.show_now_card and self.clock.tid:
            shelves.append({"title": "Now playing", "kind": "now",
                            "items": [{"id": self.clock.tid}]})
        if self.recents_tracks:
            shelves.append({"title": "Recently played", "kind": "track",
                            "items": self.recents_tracks})
        if self.recents_ctx:
            shelves.append({"title": "Jump back in", "kind": "ctx",
                            "items": self.recents_ctx})
        seed = (self.discover.get("seed") or "").strip()
        for key, title, kind in (
                ("songs", "Songs you might like", "track"),
                ("because", f"Because you played {seed}" if seed
                 else "Artists you might like", "ctx")):
            rows = self.discover.get(key) or []
            if rows:
                shelves.append({"title": title, "kind": kind, "items": rows})
        who = (self.artist() or "").split(",")[0].strip()
        for key, title, kind in (
                ("top", f"Popular by {who}" if who else "Popular", "track"),
                ("playlists", f"{who} playlists" if who else "Playlists", "ctx"),
                ("related", f"More like {who}" if who else "Related artists", "ctx"),
                ("mine", "Your playlists", "ctx")):
            rows = self.suggest.get(key) or []
            if rows:
                shelves.append({"title": title, "kind": kind, "items": rows})
        synced = [s for s in songs if s.get("synced")]
        roman = [s for s in songs if s.get("roman")]
        if synced:
            shelves.append({"title": "Word-by-word in your library",
                            "kind": "local", "items": self._sample(synced, 12)})
        if roman:
            shelves.append({"title": "Romanisable", "kind": "local",
                            "items": self._sample(roman, 12)})
        if songs:
            shelves.append({"title": "From your cache", "kind": "local",
                            "items": self._sample(songs, 12)})
        self.shelves = shelves

    def _sample(self, pool: list, n: int) -> list:
        """A stable pick -- seeded on the index build time, so it only reshuffles
        when the index itself changes rather than on every repaint."""
        if len(pool) <= n:
            return list(pool)
        rnd = random.Random(int(self.index.built or 0))
        return rnd.sample(pool, n)

    def open_search(self) -> None:
        self.show_search, self.show_menu, self.show_help = True, False, False
        self.query, self.hits, self.hit_idx, self.hit_top = "", [], 0, 0
        if not self.index.songs and not self.index.load() and not self.indexing:
            self.indexing = True
            self.toast("indexing your cached lyrics…")
            self.fetcher.request_index()

    def on_index(self, songs) -> None:
        self.indexing = False
        old = self.index.by_id
        for s in songs or []:
            was = old.get(s["id"])
            if not was:
                continue
            if not s.get("title") and was.get("title"):
                s["title"] = was["title"]
            if not s.get("artist") and was.get("artist"):
                s["artist"] = was["artist"]
        self.index.songs = songs or []
        self.index.by_id = {s["id"]: s for s in self.index.songs}
        self.index.built = time.time()
        self.index.stale = False
        self.index.save()
        self.refresh_hits()
        if self.view == "browse":
            self.build_home()
        self.toast(f"indexed {len(self.index.songs)} songs")

    def refresh_hits(self) -> None:
        self.hits = self.index.search(self.query, self.clock.tid)
        self.hit_idx = min(self.hit_idx, max(0, len(self.hits) - 1))
        self.hit_top = 0

    def activate_hit(self) -> None:
        if not self.hits:
            return
        hit = self.hits[self.hit_idx]
        if hit["here"]:
            for ln in self.lines:
                if ln["start"] is not None and SL_norm(ln["text"]) == SL_norm(hit["line"]):
                    self.clock.seek(ln["start"] + self.track_offset())
                    self.user_scroll_until = 0.0
                    break
            self.toast("jumped to line")
        else:
            self.fetcher.request_play(f"spotify:track:{hit['id']}")
            self.skip_at = time.monotonic()
            self.toast("playing…")
        self.show_search = False

    def _paint_search(self, p, W: int, H: int) -> None:
        f = self.ui_font(max(11, W * 0.0098))
        fb = self.ui_font(max(12, W * 0.0118), QFont.Weight.Black)
        fs = self.ui_font(max(9, W * 0.0080))
        fm, fmb, fms = QFontMetricsF(f), QFontMetricsF(fb), QFontMetricsF(fs)
        rowh = max(30.0, fm.height() * 2.15)
        rows_shown = 10
        self.hit_top = max(0, min(self.hit_top, len(self.hits) - rows_shown))
        self.hit_top = min(self.hit_top, self.hit_idx)
        self.hit_top = max(self.hit_top, self.hit_idx - rows_shown + 1, 0)
        shown = self.hits[self.hit_top:self.hit_top + rows_shown]
        box = QRectF(0, 0, min(W * 0.82, 900.0),
                     96 + max(1, len(shown)) * rowh + 16)
        box.moveCenter(QPointF(W / 2, H / 2))

        p.fillRect(self.rect(), QColor(6, 6, 9, 190))
        p.setPen(QColor(234, 234, 234, 40))
        p.setBrush(QColor(20, 20, 25, 244))
        p.drawRoundedRect(box, 18, 18)
        p.setBrush(Qt.BrushStyle.NoBrush)

        p.setFont(fb)
        p.setPen(TEXT)
        caret = "▏" if int(time.monotonic() * 2) % 2 else " "
        p.drawText(QRectF(box.x() + 26, box.y() + 18, box.width() - 52, fmb.height() * 1.4),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                   (self.query or "search every cached lyric…") + caret)
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 115))
        n = len(self.index.songs)
        pos = f"{self.hit_idx + 1}/{len(self.hits)}  " if len(self.hits) > 10 else ""
        note = (f"{pos}{len(self.hits)} of {n} songs" if self.query else
                (f"{n} songs indexed" if n else f"indexing… {self.index_n}"))
        p.drawText(QRectF(box.x() + 26, box.y() + 18 + fmb.height() * 1.4,
                          box.width() - 52, fms.height() * 1.4),
                   int(Qt.AlignmentFlag.AlignLeft),
                   f"{note}   ↑↓ pick   Enter play   Esc close")

        self.search_rects = []
        for k, hit in enumerate(shown):
            i = self.hit_top + k
            ry = box.y() + 92 + k * rowh
            row = QRectF(box.x() + 14, ry, box.width() - 28, rowh)
            if i == self.hit_idx:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 26))
                p.drawRoundedRect(row, 8, 8)
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.setFont(f)
            p.setPen(QColor(234, 234, 234, 235 if i == self.hit_idx else 175))
            p.drawText(QRectF(row.x() + 14, ry, row.width() - 200, rowh * 0.62),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                       fm.elidedText(hit["line"], Qt.TextElideMode.ElideRight,
                                     row.width() - 210))
            p.setFont(fs)
            p.setPen(QColor(234, 234, 234, 130))
            who = " — ".join(x for x in (hit["title"], hit["artist"]) if x)
            if hit["here"]:
                who = "playing now" + (f" · {who}" if who else "")
            elif not who:
                who = hit.get("next") or hit["id"]
            p.drawText(QRectF(row.x() + 14, ry + rowh * 0.55, row.width() - 28, rowh * 0.4),
                       int(Qt.AlignmentFlag.AlignLeft),
                       fms.elidedText(who, Qt.TextElideMode.ElideRight, row.width() - 28))
            self.search_rects.append((i, row))

    # -- song info + share ----------------------------------------------
    def info_rows(self) -> list[tuple[str, str]]:
        m, doc = self.clock.meta, SL.payload(self.body or {})
        syl = sum(len(l.get("syls") or []) for l in self.lines)
        tid = self.clock.tid or ""
        rows = [("Title", m.get("title", "—")), ("Artist", self.artist() or "—"),
                ("Album", m.get("album", "—"))]
        if doc:
            rows += [
                ("Lyrics", {"Syllable": "word-synced", "Line": "line-synced",
                            "Static": "unsynced"}.get(doc.get("Type"), str(doc.get("Type")))),
                ("Language", str(doc.get("Language") or "—")),
                ("Lines", f"{len([l for l in self.lines if not l.get('dots')])}"
                          + (f", {syl} syllables" if syl else "")),
                ("Romanised", "yes" if any(l.get("pieces_roman") for l in self.lines) else "no"),
            ]
            writers = [str(w) for w in (doc.get("SongWriters") or []) if str(w).strip()]
            if writers:
                shown = ", ".join(writers[:6])
                if len(writers) > 6:
                    shown += f" +{len(writers) - 6} more"
                rows.append(("Songwriters", shown))
            rows.append(("Source", self.source_name(doc)))
            made = self.made_by(doc)
            if made:
                rows.append(("Credited", made))
        if self.beat.beats:
            grid = [f"{len(self.beat.beats)} beats", f"{self.beat.tempo:.0f} BPM",
                    f"{len(self.beat.sections)} sections"]
            if self.beat.tatums:
                grid.append(f"{len(self.beat.tatums)} tatums")
            rows.append(("Analysis", ", ".join(grid)))
        if self.beat.segs:
            have = [n for n, v in (("pitch", self.beat.pitch),
                                   ("timbre", self.beat.timbre)) if v]
            rows.append(("Spectral",
                         f"{len(self.beat.segs)} segments @ "
                         f"{self.beat.grain() * 1000:.0f}ms, "
                         + (" + ".join(have) if have else "loudness only")))
        if self.offsets.get(tid):
            rows.append(("Track offset", f"{self.offsets[tid]:+.2f}s by hand"))
        bias, cal_n = self.calibration()
        if self.est:
            short = CAL_MIN - cal_n
            if not self.auto_time:
                why = "  (auto timing off)"
            elif self.offsets.get(tid):
                why = "  (hand correction wins)"
            elif self.est["conf"] < EST_CONF_MIN:
                why = f"  (conf {self.est['conf']:.2f}, too close to call)"
            elif short > 0:
                why = (f"  (tune {short} more track{'' if short == 1 else 's'} "
                       f"by ear to calibrate)")
            else:
                why = ""
            rows.append(("Measured",
                         f"{self.est['delta'] - bias:+.2f}s from "
                         f"{self.est['n']} entries{why}"))
        elif self.beat.segs and self.raw:
            rows.append(("Measured", "not enough clean vocal entries"))
        if cal_n:
            rows.append(("Calibration", f"{bias:+.3f}s over {cal_n} hand-tuned"))
        rows.append(("Track id", tid or "—"))
        return rows

    def _paint_info(self, p, W: int, H: int) -> None:
        rows = self.info_rows()
        f = self.ui_font(max(11, W * 0.0098))
        fb = self.ui_font(max(11, W * 0.0098), QFont.Weight.Black)
        fm, fmb = QFontMetricsF(f), QFontMetricsF(fb)
        rowh = fm.height() * 1.75
        keyw = max(fmb.horizontalAdvance(k) for k, _ in rows) + 26
        valw = min(W * 0.5, max(fm.horizontalAdvance(v) for _, v in rows) + 26)
        box = QRectF(0, 0, keyw + valw + 52, len(rows) * rowh + 84)
        box.moveCenter(QPointF(W / 2, H / 2))
        p.fillRect(self.rect(), QColor(6, 6, 9, 180))
        p.setPen(QColor(234, 234, 234, 40))
        p.setBrush(QColor(20, 20, 25, 243))
        p.drawRoundedRect(box, 18, 18)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setFont(self.ui_font(max(12, W * 0.0122), QFont.Weight.Black))
        p.setPen(TEXT)
        p.drawText(QRectF(box.x(), box.y() + 18, box.width(), 28),
                   int(Qt.AlignmentFlag.AlignCenter), "This song")
        for i, (k, v) in enumerate(rows):
            ry = box.y() + 62 + i * rowh
            p.setFont(fb)
            p.setPen(QColor(234, 234, 234, 200))
            p.drawText(QRectF(box.x() + 26, ry, keyw, rowh),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), k)
            p.setFont(f)
            p.setPen(QColor(234, 234, 234, 150))
            p.drawText(QRectF(box.x() + 26 + keyw, ry, valw, rowh),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                       fm.elidedText(v, Qt.TextElideMode.ElideRight, valw - 8))

    def share_card(self) -> None:
        """The line you are on, the cover, and who made it -- as one image."""
        live = SL.active_indices(self.lines, self.position() - self.track_offset())
        lead, backing = [], []
        for i in live:
            ln = self.lines[i]
            if ln.get("dots") or not ln["text"].strip():
                continue
            (backing if ln["background"] else lead).append(ln["text"].strip())
        if not lead and not backing:
            self.toast("no line to share right now")
            return
        Wc, Hc = 1200, 630
        pm = QPixmap(Wc, Hc)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(0, 0, Wc, Hc, QColor(11, 11, 14))
        for i, c in enumerate(self.palette[:3]):
            g = QRadialGradient(Wc * (0.2 + 0.35 * i), Hc * (0.8 - 0.3 * i), Wc * 0.7)
            g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 130))
            g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(0, 0, Wc, Hc, QBrush(g))
        art = 250
        if self.art_full:
            path = QPainterPath()
            path.addRoundedRect(QRectF(70, (Hc - art) / 2, art, art), 12, 12)
            p.save(); p.setClipPath(path)
            p.drawPixmap(QRectF(70, (Hc - art) / 2, art, art), self.art_full,
                         QRectF(self.art_full.rect()))
            p.restore()
        tx, tw = 70 + art + 60, Wc - (70 + art + 60) - 70
        fl = QFont(self.family, 34); fl.setWeight(QFont.Weight.Black)
        fb = QFont(self.family, 21); fb.setWeight(QFont.Weight.DemiBold)
        fml, fmb = QFontMetricsF(fl), QFontMetricsF(fb)
        blocks = [(fl, fml, wrap_rows(fml, t, tw, 4), TEXT, 0.0) for t in lead]
        blocks += [(fb, fmb, wrap_rows(fmb, f"({t})", tw - 24, 3),
                    QColor(234, 234, 234, 175), 24.0) for t in backing]
        gap = fml.height() * 0.22 if lead and backing else 0.0
        total = sum(len(r) * m.height() * 1.16 for _, m, r, _, _ in blocks) + gap
        y = (Hc - total) / 2
        for font, m, rows, col, dx in blocks:
            if dx and gap:
                y += gap
                gap = 0.0
            p.setFont(font); p.setPen(col)
            for r in rows:
                p.drawText(QRectF(tx + dx, y, tw - dx, m.height() * 1.16),
                           int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), r)
                y += m.height() * 1.16
        fs = QFont(self.family, 15); fs.setWeight(QFont.Weight.Medium)
        p.setFont(fs); p.setPen(QColor(234, 234, 234, 165))
        m = self.clock.meta
        p.drawText(QRectF(tx, y + 14, tw, 30), int(Qt.AlignmentFlag.AlignLeft),
                   " — ".join(x for x in (m.get("title", ""), self.artist()) if x))
        p.end()
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_",
                      f"{self.artist()} - {m.get('title','')}".strip(" -"))[:110]
        path = pathlib.Path(self.args.save_dir).expanduser() / f"{name or 'lyric'} card.png"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            pm.save(str(path))
            QApplication.clipboard().setPixmap(pm)
            self.toast(f"card copied · {path.name}")
        except Exception as exc:
            self.toast(f"card failed: {exc}")

    # -- romaji correction ------------------------------------------------
    def open_editor(self, mode: str = "romaji", idx: int | None = None) -> None:
        """Correct a line's romanisation. Defaults to whichever line is sounding,
        since that is the one you noticed was wrong; `idx` names another, for a
        caller that already knows which line was pointed at."""
        self.edit_mode = mode
        if mode in ("token", "font"):
            if mode == "font":
                self.edit_text = self.font_name
                self.edit_for = f"currently drawing with {self.family}"
            else:
                self.edit_text = self.genius_token
                self.edit_for = "Genius API token"
            self.edit_caret, self.edit_sel = len(self.edit_text), None
            self.edit_pristine, self.editing = True, True
            return
        if idx is not None:
            ln = self.lines[idx] if 0 <= idx < len(self.lines) else None
            if ln is not None and (ln.get("dots") or not ln["text"].strip()):
                ln = None
        else:
            live = self.sounding(self.position() - self.track_offset())
            ln = next((self.lines[i] for i in live
                       if not self.lines[i].get("dots")
                       and self.lines[i]["text"].strip()), None)
        if ln is None:
            self.toast("no line to correct")
            return
        if not self.clock.tid:
            self.toast("no track")
            return
        self.edit_for = ln["text"].strip()
        self.edit_text = "".join(
            t + ("" if p else " ") for _, _, t, p in (ln["pieces_roman"] or [])
        ).strip() or ln.get("text_roman", "")
        self.edit_caret, self.edit_sel = len(self.edit_text), None
        self.edit_pristine, self.editing = True, True
        self.show_menu = self.show_help = self.show_info = self.show_search = False

    def paste_into_edit(self) -> None:
        """Clipboard into the field. A token is ~60 characters, so typing one is
        not realistic and backspacing the prefilled one to replace it is worse:
        an untouched field is replaced, an edited one is appended to."""
        text = (QApplication.clipboard().text() or "").strip().replace("\n", " ")
        if not text:
            self.toast("clipboard is empty")
            return
        if self.edit_pristine:
            self.edit_text = text
            self.edit_caret, self.edit_sel = len(text), None
        else:
            self.edit_replace(text)
        self.edit_pristine = False

    # -- editing the one-line field --------------------------------------
    def edit_span(self) -> tuple[int, int]:
        """The selected range, low to high. Empty when the two ends agree."""
        a = self.edit_caret if self.edit_sel is None else self.edit_sel
        return (min(a, self.edit_caret), max(a, self.edit_caret))

    def edit_replace_at(self, lo: int, hi: int, text: str) -> None:
        lo = max(0, min(len(self.edit_text), lo))
        hi = max(lo, min(len(self.edit_text), hi))
        self.edit_text = self.edit_text[:lo] + text + self.edit_text[hi:]
        self.edit_caret, self.edit_sel = lo + len(text), None

    def edit_replace(self, text: str) -> None:
        lo, hi = self.edit_span()
        self.edit_replace_at(lo, hi, text)

    def edit_move(self, key, shift: bool) -> None:
        if self.edit_sel is None and shift:
            self.edit_sel = self.edit_caret
        if key == Qt.Key.Key_Left:
            at = max(0, self.edit_caret - 1)
        elif key == Qt.Key.Key_Right:
            at = min(len(self.edit_text), self.edit_caret + 1)
        elif key == Qt.Key.Key_Home:
            at = 0
        else:
            at = len(self.edit_text)
        if not shift:
            lo, hi = self.edit_span()
            if hi > lo and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                at = lo if key == Qt.Key.Key_Left else hi
            self.edit_sel = None
        self.edit_caret = at

    @staticmethod
    def _editor_for(key: str, kind: str) -> str:
        """Which text editor a menu row opens."""
        return "token" if kind == "secret" else "font"

    def commit_edit(self) -> None:
        if self.edit_mode == "font":
            self.font_name = self.edit_text.strip()
            if self.font_name:
                self.toast(f"looking for {self.font_name}…")
                self.repaint()
            found = self.resolve_font(online=True)
            self.editing = False
            self.layout_cache.clear()
            self.pix_cache.clear()
            self._marq.clear()
            if self.font_name and not found:
                self.toast(f"no font called {self.font_name!r} — using {self.family}")
            else:
                self.toast(f"font: {self.family}")
            return
        if self.edit_mode == "token":
            self.genius_token = self.edit_text.strip()
            self.editing = False
            self.genius_tried.clear()
            self.toast("token saved" if self.genius_token else "token cleared")
            self.maybe_auto_genius()
            return
        tid = self.clock.tid or ""
        text = self.edit_text.strip()
        fixes = self.romaji_fix.setdefault(tid, {})
        if text:
            fixes[self.edit_for] = text
            self.toast("romaji saved for this line")
        else:
            fixes.pop(self.edit_for, None)
            self.toast("correction removed")
        if not fixes:
            self.romaji_fix.pop(tid, None)
        self.editing = False
        self.rebuild_lines()

    def _paint_editor(self, p, W: int, H: int) -> None:
        fb = self.ui_font(max(12, W * 0.0118), QFont.Weight.Black)
        f = self.ui_font(max(11, W * 0.0104))
        fs = self.ui_font(max(9, W * 0.0080))
        fmb, fm, fms = QFontMetricsF(fb), QFontMetricsF(f), QFontMetricsF(fs)
        rowh = max(20.0, fms.height() * 1.35)
        boxh = (16 + rowh + 6 + fm.height() * 1.3 + 18
                + fmb.height() * 1.5 + 22 + rowh + 18)
        box = QRectF(0, 0, min(W * 0.8, 860.0), boxh)
        box.moveCenter(QPointF(W / 2, H / 2))
        p.fillRect(self.rect(), QColor(6, 6, 9, 190))
        p.setPen(QColor(234, 234, 234, 40))
        p.setBrush(QColor(20, 20, 25, 244))
        p.drawRoundedRect(box, 18, 18)
        p.setBrush(Qt.BrushStyle.NoBrush)
        x, w = box.x() + 26, box.width() - 52
        y = box.y() + 16
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 120))
        p.drawText(QRectF(x, y, w, rowh), int(Qt.AlignmentFlag.AlignLeft),
                   {"token": "paste your Genius API token",
                    "font": "type a font name, or leave empty for the default"}
                   .get(self.edit_mode, "correct the reading for this line"))
        y += rowh + 6
        p.setFont(f)
        p.setPen(QColor(234, 234, 234, 190))
        p.drawText(QRectF(x, y, w, fm.height() * 1.3),
                   int(Qt.AlignmentFlag.AlignLeft),
                   fm.elidedText(self.edit_for, Qt.TextElideMode.ElideRight, w))
        y += fm.height() * 1.3 + 18

        p.setFont(fb)
        fieldw = w - 108
        fieldh = fmb.height() * 1.4
        before = self.edit_text[:self.edit_caret]
        shift = max(0.0, fmb.horizontalAdvance(before) - (fieldw - 20))
        p.save()
        p.setClipRect(QRectF(x, y, fieldw, fieldh))
        lo, hi = self.edit_span()
        if hi > lo:
            sx = x - shift + fmb.horizontalAdvance(self.edit_text[:lo])
            sw = fmb.horizontalAdvance(self.edit_text[lo:hi])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(120, 170, 255, 70))
            p.drawRect(QRectF(sx, y + 2, sw, fieldh - 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(TEXT)
        p.drawText(QRectF(x - shift, y, fieldw + shift + 400, fieldh),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.edit_text)
        if int(time.monotonic() * 2) % 2:
            cx = x - shift + fmb.horizontalAdvance(before)
            p.setPen(QPen(TEXT, 1.6))
            p.drawLine(QPointF(cx, y + 3), QPointF(cx, y + fieldh - 3))
        p.restore()
        p.setPen(QColor(234, 234, 234, 55))
        p.drawLine(QPointF(x, y + fieldh + 4), QPointF(x + fieldw, y + fieldh + 4))
        btn = QRectF(box.right() - 26 - 92, y - 4, 92, fmb.height() * 1.35)
        self.paste_rect = btn
        hot = btn.contains(self.mouse_pos)
        p.setPen(QColor(234, 234, 234, 90 if hot else 55))
        p.setBrush(QColor(234, 234, 234, 34 if hot else 18))
        p.drawRoundedRect(btn, 8, 8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 235 if hot else 175))
        p.drawText(btn, int(Qt.AlignmentFlag.AlignCenter), "Paste")
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 115))
        tail = {"token": "blanked afterwards",
                "font": "empty uses the built-in stack"}.get(
                    self.edit_mode, "empty reverts to automatic")
        p.drawText(QRectF(x, box.bottom() - rowh - 16, w, rowh),
                   int(Qt.AlignmentFlag.AlignLeft),
                   f"Ctrl+A select all   Ctrl+V paste   Enter save   {tail}   Esc cancel")

    # -- settings menu ---------------------------------------------------
    def menu_section(self) -> int:
        """Which section the selected row lives in."""
        for s, (first, count) in enumerate(MENU_SPANS):
            if first <= self.menu_idx < first + count:
                return s
        return 0

    def menu_tab(self, delta: int) -> None:
        s = (self.menu_section() + delta) % len(MENU_SPANS)
        self.menu_idx = MENU_SPANS[s][0]

    def menu_move(self, delta: int) -> None:
        """Up/down stays inside the section -- crossing into another one by
        holding an arrow would change the page out from under you."""
        first, count = MENU_SPANS[self.menu_section()]
        self.menu_idx = first + (self.menu_idx - first + delta) % count

    def src_slot(self, key: str):
        """Which provider a Sources row stands for, or None for other rows."""
        if not str(key).startswith("src_slot"):
            return None
        try:
            return self.src_order[int(key[8:])]
        except (ValueError, IndexError):
            return None

    def menu_row(self, i: int):
        """MENU[i], with the Sources rows resolved through the current order.

        The flat MENU is built once at import and addressed by index everywhere,
        so the rows themselves cannot be shuffled. The five source slots are
        given their label and their key here instead, which puts them on screen
        in the order they are actually consulted.
        """
        label, key, kind, spec = MENU[i]
        name = self.src_slot(key)
        if name is None:
            return label, key, kind, spec
        return f"{self.src_order.index(name) + 1}. {SRC_LABEL[name]}", key, kind, spec

    def src_move(self, delta: int) -> None:
        """Shift the selected provider up or down the running order."""
        label, key, kind, spec = MENU[self.menu_idx]
        name = self.src_slot(key)
        if name is None:
            return
        at = self.src_order.index(name)
        to = max(0, min(len(self.src_order) - 1, at + delta))
        if to == at:
            return
        self.src_order.insert(to, self.src_order.pop(at))
        first, _count = MENU_SPANS[self.menu_section()]
        self.menu_idx = first + to
        self.toast(" → ".join(SRC_LABEL[n] for n in self.source_order()) or "all off")

    def _cache_size(self, which: str) -> str:
        """What this row would free, from the memo rather than the disk."""
        import caches
        got = caches.sizes()
        if which == "*":
            n = sum(r["bytes"] for r in got.values()
                    if not r.get("training") and not r.get("keep"))
            return caches.human(n)
        row = got.get(which)
        return row["human"] if row else "—"

    def clear_cache(self, which: str) -> None:
        """Clear one cache, or every ordinary one, and say what it freed.

        The two marked `keep` in the inventory -- alignments made here and the
        editor's backups -- are skipped by "clear all" and cleared only by
        their own row, which is the second thought they are worth. Nothing
        asks for confirmation: every row shows its size before it is pressed,
        and all of it comes back on its own.
        """
        import caches
        if which == "*":
            freed, said = caches.clear_all(include_kept=False)
            caches.sizes(refresh=True)
            self.toast(f"{caches.human(freed)} freed" if said
                       else "the caches were already empty")
        else:
            ok, freed, why = caches.clear(which)
            caches.sizes(refresh=True)
            self.toast(why)
        try:
            self.pix_cache.clear()
        except Exception:                                # noqa: BLE001
            pass
        self.update()

    def forget_creds(self) -> None:
        """Drop the stored credentials, and stop using the Genius one now.

        Clearing the file is not enough on its own: this window read the token
        at startup and is still holding it, so without the line below it would
        go on fetching with a credential the settings say is gone.
        """
        import caches
        _n, said = caches.forget()
        self.genius_token = ""
        self.toast("; ".join(said))
        self.update()

    def menu_get(self, key: str):
        name = self.src_slot(key)
        if name is not None:
            return getattr(self, SRC_ATTR[name])
        if key in ("start_backfill", "clear_cache", "forget_creds"):
            return None
        if key == "sung_mode":
            return SUNG_MODES[0] if self._sung is not None else SUNG_MODES[1]
        return getattr(self, key)

    def menu_set(self, key: str, value) -> None:
        name = self.src_slot(key)
        if name is not None:
            setattr(self, SRC_ATTR[name], value)
            return
        if key == "sung_mode":
            self._sung = TEXT if value == SUNG_MODES[0] else None
            return
        setattr(self, key, value)
        if key == "duet_color":
            self._duet_rgb = (None if value in DUET_MODES
                              else parse_color(value, None))
        if key == "align_on" and not value:
            self.aligner.clear()
            if self.aligner.cancel():
                self.toast("stopping the alignment in hand")
        if key == "genius_auto" and value:
            self.maybe_auto_genius()
        if key in ("align", "font_scale", "line_spacing", "show_panel", "roman",
                   "furigana", "view_mode"):
            self.layout_cache.clear()
            self.pix_cache.clear()
        elif key == "blur_scale":
            self.pix_cache.clear()
        elif key == "interlude":
            self.rebuild_lines()

    def menu_step(self, delta: int) -> None:
        label, key, kind, spec = self.menu_row(self.menu_idx)
        cur = self.menu_get(key)
        if kind in ("secret", "text"):
            return
        if kind == "action":
            fn = getattr(self, key)
            fn(spec) if spec is not None else fn()
            return
        if kind == "bool":
            self.menu_set(key, not cur)
        elif kind == "choice":
            i = spec.index(cur) if cur in spec else 0
            self.menu_set(key, spec[(i + delta) % len(spec)])
        else:
            lo, hi, step, _fmt = spec
            val = min(hi, max(lo, cur + delta * step))
            self.menu_set(key, int(round(val)) if isinstance(step, int) else round(val, 4))

    def menu_value(self, key: str, kind: str, spec) -> str:
        if kind == "action":
            if key == "clear_cache":
                return self._cache_size(spec)
            if key == "forget_creds":
                import caches
                held = [c for c in caches.credentials() if c["present"]]
                return f"{len(held)} stored" if held else "none"
            if key == "start_backfill":
                if self.backfill_total:
                    return f"{self.backfill_n}/{self.backfill_total}"
                todo = sum(1 for x in (self.index.songs or []) if not x.get("title"))
                return f"{todo} to do" if todo else "done"
            return "run"
        v = self.menu_get(key)
        if kind == "secret":
            return "\u2022" * 10 if v else "not set"
        if kind == "text":
            return str(v) if v else f"auto ({self.family})"
        if kind == "bool":
            return "on" if v else "off"
        if kind == "choice":
            return str(v)
        return spec[3].format(v)

    def _paint_menu(self, p, W: int, H: int) -> None:
        f = self.ui_font(max(11, W * 0.0098))
        fb = self.ui_font(max(11, W * 0.0098), QFont.Weight.Black)
        fm, fmb = QFontMetricsF(f), QFontMetricsF(fb)
        rowh = max(26.0, fm.height() * 1.75)
        labw = max(fm.horizontalAdvance(r[0]) for r in MENU) + 30
        valw = max(150.0, fmb.horizontalAdvance("album tint") + 96)
        tab = self.menu_section()
        first, count = MENU_SPANS[tab]
        ft = self.ui_font(max(10, W * 0.0086), QFont.Weight.Black)
        fmt = QFontMetricsF(ft)
        tabh = fmt.height() * 2.1
        gap = 6.0
        pad = 26.0
        widths = [fmt.horizontalAdvance(name) + pad for name, _ in MENU_SECTIONS]
        strip = sum(widths) + gap * (len(widths) - 1)
        tall = max(n for _, n in MENU_SPANS)
        box = QRectF(0, 0, max(labw + valw + 52, strip + 32), tall * rowh + 92 + tabh)
        if box.width() > W - 24:
            pad = max(10.0, pad - (box.width() - (W - 24)) / len(widths))
            widths = [fmt.horizontalAdvance(name) + pad for name, _ in MENU_SECTIONS]
            strip = sum(widths) + gap * (len(widths) - 1)
            box.setWidth(min(W - 24, max(labw + valw + 52, strip + 32)))
        box.moveCenter(QPointF(W / 2, H / 2))

        p.fillRect(self.rect(), QColor(6, 6, 9, 185))
        p.setPen(QColor(234, 234, 234, 40))
        p.setBrush(QColor(20, 20, 25, 243))
        p.drawRoundedRect(box, 18, 18)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setFont(self.ui_font(max(12, W * 0.0122), QFont.Weight.Black))
        p.setPen(TEXT)
        p.drawText(QRectF(box.x(), box.y() + 18, box.width(), 28),
                   int(Qt.AlignmentFlag.AlignCenter), "Settings")
        p.setFont(self.ui_font(max(9, W * 0.0078)))
        p.setPen(QColor(234, 234, 234, 110))
        p.drawText(QRectF(box.x(), box.y() + 44, box.width(), 20),
                   int(Qt.AlignmentFlag.AlignCenter),
                   "↑↓ pick   ←→ change   Tab section   ⇧↑↓ reorder sources"
                   "   Enter types a value   Esc closes")

        self.tab_rects = []
        tx = box.x() + (box.width() - strip) / 2
        ty = box.y() + 70
        for s, ((name, _rows), w) in enumerate(zip(MENU_SECTIONS, widths)):
            r = QRectF(tx, ty, w, tabh - 8)
            on = s == tab
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(234, 234, 234, 30) if on else QColor(234, 234, 234, 10))
            p.drawRoundedRect(r, 7, 7)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setFont(ft)
            p.setPen(QColor(234, 234, 234, 240 if on else 130))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), name)
            if on:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 205))
                p.drawRect(QRectF(r.x() + 8, r.bottom() + 2, r.width() - 16, 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
            self.tab_rects.append((s, r))
            tx += w + gap

        self.menu_rects = []
        for n in range(count):
            i = first + n
            label, key, kind, spec = self.menu_row(i)
            ry = box.y() + 70 + tabh + n * rowh
            row = QRectF(box.x() + 12, ry, box.width() - 24, rowh)
            if i == self.menu_idx:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 26))
                p.drawRoundedRect(row, 8, 8)
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.setFont(f)
            p.setPen(QColor(234, 234, 234, 235 if i == self.menu_idx else 165))
            p.drawText(QRectF(row.x() + 14, ry, labw, rowh),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                       label)
            vx = row.x() + 14 + labw
            minus = QRectF(vx, ry + rowh * 0.14, 24, rowh * 0.72)
            plus = QRectF(vx + valw - 24, ry + rowh * 0.14, 24, rowh * 0.72)
            at_lo = kind == "num" and self.menu_get(key) <= spec[0] + 1e-9
            at_hi = kind == "num" and self.menu_get(key) >= spec[1] - 1e-9
            if kind in ("secret", "text"):
                at_lo = at_hi = True
            p.setFont(fb)
            p.setPen(QColor(234, 234, 234, 60 if at_lo else 190))
            p.drawText(minus, int(Qt.AlignmentFlag.AlignCenter), "‹")
            p.setPen(QColor(234, 234, 234, 60 if at_hi else 190))
            p.drawText(plus, int(Qt.AlignmentFlag.AlignCenter), "›")
            p.setPen(QColor(234, 234, 234, 235 if i == self.menu_idx else 175))
            p.drawText(QRectF(vx + 24, ry, valw - 48, rowh),
                       int(Qt.AlignmentFlag.AlignCenter),
                       self.menu_value(key, kind, spec))
            if kind == "num":
                lo, hi = spec[0], spec[1]
                t = (self.menu_get(key) - lo) / max(1e-9, hi - lo)
                bar = QRectF(vx + 26, row.bottom() - 5, valw - 52, 2)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 40))
                p.drawRect(bar)
                p.setBrush(QColor(234, 234, 234, 150))
                p.drawRect(QRectF(bar.x(), bar.y(), bar.width() * t, bar.height()))
                p.setBrush(Qt.BrushStyle.NoBrush)
            self.menu_rects.append((i, row, minus, plus))

    def menu_hit(self, pos) -> tuple[int, int] | None:
        """(row, delta) under the cursor; delta 0 means 'just select'."""
        for s, r in getattr(self, "tab_rects", []):
            if r.contains(pos):
                return MENU_SPANS[s][0], 0
        for i, row, minus, plus in self.menu_rects:
            if row.contains(pos):
                return i, (-1 if minus.contains(pos) else (1 if plus.contains(pos) else 0))
        return None

    # -- helpers ---------------------------------------------------------
    def toast(self, text: str) -> None:
        self.toast_text, self.toast_until = text, time.monotonic() + 1.7

    def set_cursor(self, shape) -> None:
        if shape != self._cursor:
            self._cursor = shape
            self.setCursor(shape)

    def line_at(self, px: float, py: float) -> int:
        y = py + self.scroll - self.anchor()
        for i, top, h, lo, hi in self.line_rects:
            base = top - self.anchor()
            if base <= y <= base + h and lo <= px <= hi and i < len(self.lines):
                if self.lines[i]["start"] is not None:
                    return i
        return -1

    def hot_at(self, pos):
        """The clickable chrome under the cursor, last drawn first.

        Reversed because these are appended in paint order, so the thing drawn
        last is the thing on top, and that is the one a click landed on.
        """
        for rect, kind, payload in reversed(self.hot):
            if rect.contains(pos):
                return kind, payload
        return None, None

    def open_url(self, url: str) -> None:
        if url:
            QDesktopServices.openUrl(QUrl(url))

    @staticmethod
    def web_url(uri: str) -> str:
        """spotify:track:ID -> the open.spotify.com page for it."""
        parts = (uri or "").split(":")
        if len(parts) >= 3 and parts[0] == "spotify":
            return f"https://open.spotify.com/{parts[-2]}/{parts[-1]}"
        return ""

    def seek_line(self, step: int) -> None:
        idx = [
            i for i, ln in enumerate(self.lines)
            if ln["start"] is not None and not ln.get("dots")
        ]
        if not idx:
            return
        pos = self.position() - self.track_offset()
        here = [i for i in idx if self.lines[i]["start"] <= pos + 0.1]
        j = idx.index(here[-1]) if here else -1
        if step < 0 and here and pos - self.lines[here[-1]]["start"] > 2.0:
            step = 0
        if j < 0 and step <= 0:
            return
        j = max(0, min(len(idx) - 1, j + step))
        self.clock.seek(self.lines[idx[j]]["start"] + self.track_offset())
        self.user_scroll_until = 0.0

    def copy_lyrics(self, whole: bool) -> None:
        if not self.lines:
            return
        if whole:
            text = "\n".join(ln["text"] for ln in self.lines if not ln.get("dots"))
        else:
            live = SL.active_indices(self.lines, self.position() - self.track_offset())
            text = "\n".join(
                self.lines[i]["text"] for i in live if not self.lines[i].get("dots")
            )
        if text.strip():
            QApplication.clipboard().setText(text)
            self.toast("copied all lyrics" if whole else "copied line")

    def save_lyrics(self) -> None:
        if not self.body:
            self.toast("nothing to save")
            return
        m = self.clock.meta
        name = f"{self.artist()} - {m.get('title', '')}".strip(" -")
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:120] or (self.clock.tid or "lyrics")
        path = pathlib.Path(self.args.save_dir).expanduser() / f"{name}.ttml"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SL.render(self.body, "ttml") + "\n", encoding="utf-8")
            self.toast(f"saved {path.name}")
        except Exception as exc:
            self.toast(f"save failed: {exc}")

    def bump_font(self, delta: float) -> None:
        self.font_scale = max(0.6, min(1.9, self.font_scale + delta))
        self.layout_cache.clear()
        self.pix_cache.clear()
        self.toast(f"text {self.font_scale * 100:.0f}%")

    # -- input -----------------------------------------------------------
    def on_thumb(self, url: str, img) -> None:
        self.art_cache.put(url, img)
        if self.view == "browse":
            self.update()

    def on_motion(self, key: str, frames) -> None:
        """Frames arrive as QImages off the worker; QPixmap is GUI-thread-only.

        Held at the biggest size this screen could ever draw them, not at the
        size they were decoded to: sixty frames of 720px cover is 124MB of
        pixmap for a panel that is usually painting a third of that. Sized off
        the screen rather than the window so resizing never has to rebuild.
        """
        if key != self.motion_key or not frames:
            return
        scr = self.screen() or QApplication.primaryScreen()
        cap = MOTION_PX
        if scr is not None:
            avail = scr.geometry().height() * scr.devicePixelRatio()
            cap = max(240, min(MOTION_PX, int(avail * 0.45)))
        out = []
        for img in frames:
            if img.width() > cap:
                img = img.scaledToWidth(cap, Qt.TransformationMode.SmoothTransformation)
            out.append(QPixmap.fromImage(img))
        self.motion_frames = out
        self.motion_at = time.monotonic()
        self.update()

    def motion_frame(self):
        """The frame due now, or None when there is no animation to play."""
        if not self.motion_art or not self.motion_frames:
            return None
        i = int((time.monotonic() - self.motion_at) * MOTION_FPS)
        return self.motion_frames[i % len(self.motion_frames)]

    # ----------------------------------------------------------- browse input
    def browse_hit(self, pos) -> tuple | None:
        """Topmost thing under the cursor. Walked backwards so the top bar,
        which is registered last, beats any card drawn underneath it."""
        for kind, payload, r in reversed(self.browse_rects):
            if r.contains(pos):
                return (kind, payload)
        return None

    def browse_key(self, ev) -> None:
        k, mods = ev.key(), ev.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if k == Qt.Key.Key_Escape:
            if self.browse_tab == "search" and self.bq:
                self.bq, self.bq_hits, self.bq_sel = "", [], 0
            else:
                self.close_browse()
            return
        if k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            tabs = ["home", "search", "queue"]
            i = tabs.index(self.browse_tab) if self.browse_tab in tabs else 0
            self.browse_tab = tabs[(i + (-1 if k == Qt.Key.Key_Backtab else 1)) % 3]
            self.set_browse_tab(self.browse_tab)
            return
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.browse_activate()
            return
        if self.browse_tab == "search":
            if k == Qt.Key.Key_Up:
                self.bq_sel = max(0, self.bq_sel - 1)
                return
            if k == Qt.Key.Key_Down:
                self.bq_sel = min(max(0, len(self.bq_hits) - 1), self.bq_sel + 1)
                return
            if k == Qt.Key.Key_Backspace:
                self.bq = self.bq[:-1]
                self.refresh_browse_hits()
                return
            if ev.text() and ev.text().isprintable():
                self.bq += ev.text()
                self.refresh_browse_hits()
                return
        else:
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self.browse_scroll_target += 150 * (1 if k == Qt.Key.Key_Down else -1)
                return
            if ev.text() and ev.text().isprintable() and ev.text() != " ":
                self.browse_tab = "search"
                self.bq += ev.text()
                self.refresh_browse_hits()
                return
        self.transport_key(k, shift)

    def transport_key(self, k, shift: bool) -> bool:
        """The playback keys that keep working outside the lyrics view.

        Deliberately a small named subset rather than the whole key handler:
        music carries on while you browse, so skip/seek/pause should still
        respond, but nothing that edits or reveals lyrics belongs here.
        """
        if k == Qt.Key.Key_Space:
            self.clock.command("PlayPause")
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Comma):
            self.clock.seek(self.clock.position() - 5)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Period):
            self.clock.seek(self.clock.position() + 5)
        elif k == Qt.Key.Key_N:
            self.skip_at = time.monotonic()
            self.clock.command("Next")
        elif k == Qt.Key.Key_P:
            self.skip_at = time.monotonic()
            self.clock.command("Previous")
        elif k == Qt.Key.Key_M:
            self.show_menu = not self.show_menu
        else:
            return False
        return True

    def set_browse_tab(self, tab: str) -> None:
        """Switch tab and fetch whatever that tab needs, if it has gone stale."""
        self.browse_tab = tab
        self.browse_scroll = self.browse_scroll_target = 0.0
        if tab == "queue" and time.monotonic() - self.queue_at > 5:
            self.fetcher.request_queue()

    def browse_press(self, ev) -> None:
        hit = self.browse_hit(ev.position())
        if not hit:
            return
        kind, payload = hit
        if kind in ("lyrics_btn", "now"):
            self.close_browse()
        elif kind == "tab":
            self.set_browse_tab(payload)
        else:
            self.browse_activate(payload, kind)

    def browse_move(self, ev) -> None:
        self.last_move = time.monotonic()
        hit = self.browse_hit(ev.position())
        if hit != self.browse_hover:
            self.browse_hover = hit
            self.update()
        self.set_cursor(Qt.CursorShape.PointingHandCursor if hit
                        else Qt.CursorShape.ArrowCursor)

    def browse_wheel(self, ev) -> None:
        self.browse_scroll_target -= ev.angleDelta().y() * 0.7

    def browse_activate(self, payload=None, kind: str = "") -> None:
        """Play whatever was picked, then go back to the lyrics for it."""
        if payload is None:
            if self.browse_tab != "search" or not self.bq_hits:
                return
            payload, kind = self.bq_hits[min(self.bq_sel, len(self.bq_hits) - 1)], "hit"
        uri = payload.get("uri") or ""
        if not uri and payload.get("id"):
            uri = f"spotify:track:{payload['id']}"
        if not uri:
            return
        if kind == "queue":
            self.fetcher.request_skip(uri, payload.get("uid") or "")
        else:
            self.fetcher.request_play(uri)
        self.skip_at = time.monotonic()
        self.toast("playing…")
        self.close_browse()

    def refresh_browse_hits(self) -> None:
        """Local matches immediately; the catalogue arrives later, if reachable."""
        self.bq_sel = 0
        self.browse_scroll = self.browse_scroll_target = 0.0
        local = []
        if len(self.bq) >= 2:
            for h in self.index.search(self.bq, self.clock.tid, limit=12):
                named = h.get("why") == "name"
                local.append({"section": "In your lyrics", "uri": "",
                              "id": h.get("id", ""),
                              "name": (h.get("title") or h.get("line", ""))[:80],
                              "sub": (h.get("artist", "") if named
                                      else "\u201c" + h.get("line", "")[:70] + "\u201d"),
                              "art": "", "ms": 0})
        self.bq_local = local
        self.merge_browse_hits()
        if len(self.bq) >= 2:
            self.bq_busy = True
            self.fetcher.request_catsearch(self.bq)
        else:
            self.bq_busy = False

    def merge_browse_hits(self) -> None:
        self.bq_hits = list(self.bq_cat) + list(self.bq_local)
        self.bq_sel = min(self.bq_sel, max(0, len(self.bq_hits) - 1))

    def on_catsearch(self, query: str, results) -> None:
        if query != self.bq:
            return
        self.bq_busy = False
        self.bq_cat = list(results or [])
        self.merge_browse_hits()
        self.update()

    def start_backfill(self) -> None:
        """Fill in the song names the index never learned.

        note_title only fires for tracks played while the app is open, so a
        2000-song cache arrives with a handful of names and every browse shelf
        would show raw 22-character ids.
        """
        ids = [s["id"] for s in (self.index.songs or []) if not s.get("title")]
        if not ids:
            self.toast("all songs already named")
            return
        self.backfill_n, self.backfill_total = 0, len(ids)
        self.toast(f"filling in song names… ({len(ids)})")
        self.fetcher.request_backfill(ids)

    def on_backfill_progress(self, done: int, total: int) -> None:
        self.backfill_n, self.backfill_total = done, total
        if done and done % 500 < 25:
            self.index.save()

    def on_backfill(self, rows) -> None:
        if rows is None:
            self.backfill_total = 0
            self.index.save()
            self.build_home()
            self.toast("song names filled in")
            self.update()
            return
        for r in rows:
            if r.get("name"):
                self.index.note_title(r["id"], r["name"], r.get("artist", ""))
        self.build_home()

    def on_queue(self, got) -> None:
        if not isinstance(got, dict):
            return
        self.queue_items = got.get("items") or []
        self.queue_cur = got.get("current")
        self.queue_at = time.monotonic()
        self.align_ahead_scan()
        self.update()

    def on_suggest(self, got) -> None:
        if isinstance(got, dict):
            self.suggest = got
            self.suggest_for = got.get("artist") or ""
            self.build_home()
            self.update()

    def on_discover(self, got) -> None:
        if isinstance(got, dict):
            self.discover = got
            self.discover_at = time.monotonic()
            self.build_home()
            self.update()

    def on_recents(self, tracks, contexts) -> None:
        self.recents_tracks = list(tracks or [])
        self.recents_ctx = list(contexts or [])
        self.recents_at = time.monotonic()
        self.build_home()
        self.update()

    def overlay(self) -> str | None:
        """Which panel is up, as one name -- the single source of truth.

        These five used to be tested independently in six places (paintEvent and
        the five input handlers), each in a DIFFERENT order. That was only safe
        because every open_* setter clears the others by hand, so at most one is
        ever true; the orders were therefore equivalent, not correct. Adding a
        view that replaces the base layer rather than sitting over it would have
        doubled the number of hand-kept orderings, so they collapse to this.
        """
        if self.editing:
            return "editor"
        if self.show_help:
            return "help"
        if self.show_menu:
            return "menu"
        if self.show_search:
            return "search"
        if self.show_info:
            return "info"
        return None

    def wheelEvent(self, ev) -> None:
        if self.view == "browse" and not self.overlay():
            self.browse_wheel(ev)
            return
        if self.view == "detail" and not self.overlay():
            rows = len(self.detail_rows)
            span = max(0.0, rows * 36 - (self.height() - 260))
            self.detail_scroll = max(
                0.0, min(span, self.detail_scroll - ev.angleDelta().y() * 0.6))
            self.update()
            return
        if self.show_search:
            step = -1 if ev.angleDelta().y() > 0 else 1
            self.hit_idx = max(0, min(max(0, len(self.hits) - 1), self.hit_idx + step))
            return
        if self.show_info or self.show_help or self.editing:
            return
        if self.show_menu:
            hit = self.menu_hit(ev.position())
            if hit:
                self.menu_idx = hit[0]
                self.menu_step(1 if ev.angleDelta().y() > 0 else -1)
            return
        self.scroll_target -= ev.angleDelta().y() * 0.7
        self.user_scroll_until = time.monotonic() + 4.0

    def mouseMoveEvent(self, ev) -> None:
        self.last_move = time.monotonic()
        pos = self.mouse_pos = ev.position()
        if self.drag_frac is not None and self.bar_rect:
            self.drag_frac = max(
                0.0, min(1.0, (pos.x() - self.bar_rect.x()) / max(1.0, self.bar_rect.width()))
            )
            return
        if self.vol_drag is not None and self.vol_rect:
            self.vol_drag = max(
                0.0, min(1.0, (pos.x() - self.vol_rect.x()) / max(1.0, self.vol_rect.width()))
            )
            self.clock.set_volume(self.vol_drag)
            return
        if self.view == "detail" and not self.overlay():
            kind, _ = self.hot_at(pos)
            over = kind is not None or any(r.contains(pos) and t.get("uri")
                                           for r, t in self.detail_rows)
            self.set_cursor(Qt.CursorShape.PointingHandCursor if over
                            else Qt.CursorShape.ArrowCursor)
            self.update()
            return
        if self.view == "browse" and not self.overlay():
            self.browse_move(ev)
            return
        if self.editing:
            self.set_cursor(Qt.CursorShape.PointingHandCursor
                            if self.paste_rect and self.paste_rect.contains(pos)
                            else Qt.CursorShape.ArrowCursor)
            return
        if self.show_search:
            over = any(r.contains(pos) for _, r in self.search_rects)
            self.set_cursor(Qt.CursorShape.PointingHandCursor if over
                            else Qt.CursorShape.ArrowCursor)
            return
        if self.show_menu:
            hit = self.menu_hit(pos)
            if hit:
                self.menu_idx = hit[0]
            self.set_cursor(Qt.CursorShape.PointingHandCursor if hit
                            else Qt.CursorShape.ArrowCursor)
            return
        over_bar = bool(self.bar_rect and self.bar_rect.adjusted(0, -9, 0, 9).contains(pos))
        over_vol = bool(self.vol_rect
                        and self.vol_rect.adjusted(-8, -9, 8, 9).contains(pos))
        idx = -1 if (over_bar or over_vol) else self.line_at(pos.x(), pos.y())
        if idx != self.hover_idx:
            self.hover_idx = idx
        self.set_cursor(
            Qt.CursorShape.PointingHandCursor
            if over_bar or over_vol or (idx >= 0 and self.synced)
            else Qt.CursorShape.ArrowCursor
        )

    def mousePressEvent(self, ev) -> None:
        pos = ev.position()
        btn = ev.button()
        if btn == Qt.MouseButton.MiddleButton:
            self.middle_click(pos)
            return
        if btn == Qt.MouseButton.RightButton:
            self.right_click(pos, ev.globalPosition().toPoint())
            return
        if self.view == "detail" and not self.overlay():
            kind, payload = self.hot_at(pos)
            if kind in ("album", "artist"):
                self.open_detail(kind, payload)
                return
            for r, t in self.detail_rows:
                if r.contains(pos) and t.get("uri"):
                    self.fetcher.request_play(t["uri"])
                    return
            return
        if self.view == "browse" and not self.overlay():
            self.browse_press(ev)
            return
        if self.show_help or self.show_info:
            self.show_help = self.show_info = False
            return
        if self.editing:
            if self.paste_rect and self.paste_rect.contains(pos):
                self.paste_into_edit()
            return
        if self.show_search:
            for i, r in self.search_rects:
                if r.contains(pos):
                    self.hit_idx = i
                    self.activate_hit()
                    return
            self.show_search = False
            return
        if self.show_menu:
            hit = self.menu_hit(pos)
            if hit is None:
                self.show_menu = False
            else:
                self.menu_idx = hit[0]
                if MENU[hit[0]][2] in ("secret", "text"):
                    self.open_editor(self._editor_for(MENU[hit[0]][1],
                                                      MENU[hit[0]][2]))
                elif hit[1]:
                    self.menu_step(hit[1])
            return
        if self.bar_rect and self.bar_rect.adjusted(0, -9, 0, 9).contains(pos):
            self.drag_frac = max(
                0.0, min(1.0, (pos.x() - self.bar_rect.x()) / max(1.0, self.bar_rect.width()))
            )
            return
        if self.vol_rect and self.vol_rect.adjusted(-8, -9, 8, 9).contains(pos):
            self.vol_drag = max(
                0.0, min(1.0, (pos.x() - self.vol_rect.x()) / max(1.0, self.vol_rect.width()))
            )
            self.clock.set_volume(self.vol_drag)
            return
        kind, payload = self.hot_at(pos)
        if kind == "song":
            self.open_detail("song")
            return
        if kind in ("album", "artist"):
            self.open_detail(kind, payload)
            return
        if not self.synced:
            return
        idx = self.line_at(pos.x(), pos.y())
        if idx >= 0:
            self.clock.seek(self.lines[idx]["start"] + self.track_offset())
            self.user_scroll_until = 0.0

    def line_text_at(self, pos) -> str:
        idx = self.line_at(pos.x(), pos.y())
        if idx < 0 or idx >= len(self.lines):
            return ""
        return (self.lines[idx].get("text") or "").strip()

    def middle_click(self, pos) -> None:
        """Middle click opens the thing under it, wherever that lives."""
        if self.overlay():
            return
        kind, payload = self.hot_at(pos)
        if kind == "song":
            self.open_url(self.web_url(f"spotify:track:{payload}") if payload else "")
            self.toast("opened on Spotify")
            return
        if kind in ("artist", "album"):
            self.open_url(self.web_url(payload))
            self.toast(f"opened {kind} on Spotify")
            return
        text = self.line_text_at(pos)
        if text:
            q = urllib.parse.quote(text.strip())
            self.open_url(f"https://genius.com/search?q={q}")
            self.toast("searching Genius")

    def right_click(self, pos, gpos) -> None:
        idx = self.line_at(pos.x(), pos.y())
        if self.overlay() or idx < 0 or idx >= len(self.lines):
            return
        ln = self.lines[idx]
        text = (ln.get("text") or "").strip()
        if not text:
            return
        menu = QMenu(self)
        act_copy = menu.addAction("Copy line")
        act_stamp = menu.addAction("Copy with timestamp")
        act_roman = menu.addAction("Edit romanisation")
        chosen = menu.exec(gpos)
        if chosen is None:
            return
        if chosen is act_copy:
            QApplication.clipboard().setText(text)
            self.toast("copied")
        elif chosen is act_stamp:
            start = ln.get("start")
            stamp = f"[{fmt_time(start)}] " if isinstance(start, (int, float)) else ""
            QApplication.clipboard().setText(f"{stamp}{text}")
            self.toast("copied with timestamp")
        elif chosen is act_roman:
            self.open_editor("romaji", idx)

    def mouseReleaseEvent(self, _ev) -> None:
        if self.drag_frac is not None:
            dur = self.clock.meta.get("length", 0.0)
            if dur:
                self.clock.seek(self.drag_frac * dur)
            self.drag_frac = None
            self.user_scroll_until = 0.0
        self.vol_drag = None

    def mouseDoubleClickEvent(self, ev) -> None:
        if (self.show_menu or self.show_search or self.show_info
                or self.show_help or self.editing or self.view == "browse"):
            return
        if ev.position().x() < self.panel_width():
            self.toggle_fullscreen()

    def toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()
        self.set_cursor(Qt.CursorShape.ArrowCursor)
        self.last_move = time.monotonic()

    def keyPressEvent(self, ev) -> None:
        k = ev.key()
        shift = ev.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if self.view == "browse" and not self.overlay():
            self.browse_key(ev)
            return
        if self.view == "detail" and not self.overlay():
            if k == Qt.Key.Key_Escape:
                self.close_detail()
            elif k in (Qt.Key.Key_M, Qt.Key.Key_Question):
                self.show_menu = k == Qt.Key.Key_M
                self.show_help = k != Qt.Key.Key_M
            return
        if self.editing:
            ctrl = bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if k == Qt.Key.Key_Escape:
                self.editing = False
            elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.commit_edit()
            elif k == Qt.Key.Key_V and ctrl:
                self.paste_into_edit()
            elif k == Qt.Key.Key_A and ctrl:
                self.edit_sel, self.edit_caret = 0, len(self.edit_text)
            elif k in (Qt.Key.Key_C, Qt.Key.Key_X) and ctrl:
                lo, hi = self.edit_span()
                if hi > lo:
                    QApplication.clipboard().setText(self.edit_text[lo:hi])
                    if k == Qt.Key.Key_X:
                        self.edit_replace("")
            elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right,
                       Qt.Key.Key_Home, Qt.Key.Key_End):
                self.edit_move(k, shift)
            elif k == Qt.Key.Key_Backspace:
                lo, hi = self.edit_span()
                if hi > lo:
                    self.edit_replace("")
                elif self.edit_caret > 0:
                    self.edit_caret -= 1
                    self.edit_replace_at(self.edit_caret, self.edit_caret + 1, "")
                self.edit_pristine = False
            elif k == Qt.Key.Key_Delete:
                lo, hi = self.edit_span()
                if hi > lo:
                    self.edit_replace("")
                else:
                    self.edit_replace_at(self.edit_caret, self.edit_caret + 1, "")
                self.edit_pristine = False
            elif ev.text() and ev.text().isprintable():
                self.edit_replace(ev.text())
                self.edit_pristine = False
            return
        if self.show_search:
            if k == Qt.Key.Key_Escape:
                self.show_search = False
            elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.activate_hit()
            elif k == Qt.Key.Key_Up:
                self.hit_idx = max(0, self.hit_idx - 1)
            elif k == Qt.Key.Key_Down:
                self.hit_idx = min(max(0, len(self.hits) - 1), self.hit_idx + 1)
            elif k == Qt.Key.Key_Backspace:
                self.query = self.query[:-1]
                self.refresh_hits()
            elif ev.text() and ev.text().isprintable():
                self.query += ev.text()
                self.hit_idx = 0
                self.refresh_hits()
            return
        if self.show_menu:
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                    MENU[self.menu_idx][2] in ("secret", "text"):
                self.open_editor(self._editor_for(MENU[self.menu_idx][1],
                                                  MENU[self.menu_idx][2]))
            elif k in (Qt.Key.Key_Escape, Qt.Key.Key_M, Qt.Key.Key_Return,
                       Qt.Key.Key_Enter):
                self.show_menu = False
            elif k == Qt.Key.Key_Up:
                self.src_move(-1) if shift else self.menu_move(-1)
            elif k == Qt.Key.Key_Down:
                self.src_move(+1) if shift else self.menu_move(+1)
            elif k == Qt.Key.Key_Tab:
                self.menu_tab(+1)
            elif k == Qt.Key.Key_Backtab:
                self.menu_tab(-1)
            elif k in (Qt.Key.Key_Left, Qt.Key.Key_Minus):
                self.menu_step(-1)
            elif k in (Qt.Key.Key_Right, Qt.Key.Key_Plus, Qt.Key.Key_Equal,
                       Qt.Key.Key_Space):
                self.menu_step(+1)
            elif k in (Qt.Key.Key_H, Qt.Key.Key_Question):
                self.show_menu, self.show_help = False, True
            elif k == Qt.Key.Key_Q:
                self.close()
            return
        if k in (Qt.Key.Key_Slash, Qt.Key.Key_F3):
            self.open_browse("search") if not shift else self.open_search()
        elif k == Qt.Key.Key_Home:
            self.open_browse("home")
        elif k == Qt.Key.Key_M:
            self.show_menu, self.show_help = True, False
        elif k in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_Escape:
            if self.show_help or self.show_info:
                self.show_help = self.show_info = False
            elif self.isFullScreen():
                self.showNormal()
            else:
                self.close()
        elif k == Qt.Key.Key_Q:
            self.close()
        elif k in (Qt.Key.Key_H, Qt.Key.Key_Question, Qt.Key.Key_F1):
            self.show_help = not self.show_help
            self.show_menu = False
        elif k == Qt.Key.Key_Space:
            self.clock.command("PlayPause")
        elif k in (Qt.Key.Key_BracketLeft, Qt.Key.Key_BraceLeft):
            self.nudge_offset(-0.01 if shift else -0.05)
        elif k in (Qt.Key.Key_BracketRight, Qt.Key.Key_BraceRight):
            self.nudge_offset(+0.01 if shift else +0.05)
        elif k == Qt.Key.Key_0:
            if shift:
                self.offset = 0.0
                self.toast("global offset reset")
            else:
                self.offsets.pop(self.clock.tid or "", None)
                self._cal_gen += 1
                rest = self.track_offset()
                self.toast(f"track offset cleared ({rest:+.2f}s remaining)"
                           if abs(rest) > 1e-6 else "track offset cleared")
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Comma):
            self.clock.seek(self.clock.position() - 5)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Period):
            self.clock.seek(self.clock.position() + 5)
        elif k == Qt.Key.Key_Up:
            self.seek_line(-1)
        elif k == Qt.Key.Key_Down:
            self.seek_line(+1)
        elif k == Qt.Key.Key_N:
            self.skip_at = time.monotonic()
            self.clock.command("Next")
        elif k == Qt.Key.Key_P:
            self.skip_at = time.monotonic()
            self.clock.command("Previous")
        elif k == Qt.Key.Key_X:
            self.clock.resync()
            self.toast("resynced")
        elif k == Qt.Key.Key_D:
            order = ["art", "mesh", "solid"]
            self.bg_mode = order[(order.index(self.bg_mode) + 1) % len(order)]
            self.toast(f"background: {self.bg_mode}")
        elif k == Qt.Key.Key_L:
            order = ["left", "center", "right"]
            self.align = order[(order.index(self.align) + 1) % len(order)]
            self.layout_cache.clear()
            self.pix_cache.clear()
            self.toast(f"align: {self.align}")
        elif k == Qt.Key.Key_E:
            self.pop = 0.0 if self.pop else (self.args.pop or 1.0)
            self.toast(f"word pop {'off' if not self.pop else 'on'}")
        elif k == Qt.Key.Key_O:
            self.focus = 0 if self.focus else (self.args.focus or 2)
            self.toast("focus off" if not self.focus else f"focus ±{self.focus} lines")
        elif k == Qt.Key.Key_U:
            self._sung = None if self._sung else TEXT
            self.toast(f"sung colour: {'album tint' if self._sung is None else 'white'}")
        elif k == Qt.Key.Key_A and shift:
            self.align_now()
        elif k == Qt.Key.Key_A:
            self.show_panel = not self.show_panel
            self.layout_cache.clear()
            self.pix_cache.clear()
            self.toast(f"art panel {'on' if self.show_panel else 'off'}")
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.bump_font(+0.1)
        elif k in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.bump_font(-0.1)
        elif k == Qt.Key.Key_G:
            if shift:
                self.fetch_genius()
            else:
                self.glow_scale = 0.0 if self.glow_scale else self.args.glow or 1.0
                self.toast(f"glow {'off' if not self.glow_scale else 'on'}")
        elif k == Qt.Key.Key_B:
            self.blur_scale = 0.0 if self.blur_scale else self.args.blur or 1.0
            self.pix_cache.clear()
            self.toast(f"depth blur {'off' if not self.blur_scale else 'on'}")
        elif k == Qt.Key.Key_C:
            self.copy_lyrics(bool(shift))
        elif k == Qt.Key.Key_S:
            self.share_card() if shift else self.save_lyrics()
        elif k == Qt.Key.Key_I:
            self.show_info = not self.show_info
            self.show_menu = self.show_help = False
        elif k == Qt.Key.Key_R:
            if shift:
                self.open_editor()
            else:
                if self.clock.tid:
                    LS.forget(self.clock.tid)
                self.reset_track("Reloading…")
                self.toast("reloading lyrics")
        elif k == Qt.Key.Key_T:
            self.set_on_top(not self.on_top)

    def set_on_top(self, on: bool) -> None:
        """Keep the window above the others, by whichever route works here.

        The Qt flag is still set first: it is what works on X11, and it is
        harmless where it does not. On Wayland it is quietly ignored, so KWin is
        asked directly -- and if neither route is available the toast says so
        rather than claiming a state the window is not in.
        """
        if QApplication.platformName().startswith("wayland"):
            ok = kwin_keep_above(self.windowTitle(), on)
        else:
            full = self.isFullScreen()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
            self.showFullScreen() if full else self.show()
            ok = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == on
        self.on_top = on if ok else False
        if ok:
            self.toast(f"always on top {'on' if on else 'off'}")
        else:
            self.toast("always on top unsupported by this compositor")

    def resizeEvent(self, _ev) -> None:
        self.layout_cache.clear()
        self.pix_cache.clear()

    def settings_dict(self) -> dict:
        return {
                "offset": round(self.offset, 3),
                "font_scale": round(self.font_scale, 2),
                "blur": self.blur_scale,
                "glow": self.glow_scale,
                "panel": self.show_panel,
                "view_mode": self.view_mode,
                "volume_bar": bool(self.show_volume),
                "duet_color": self.duet_color,
                "font": self.font_name,
                "src_order": ",".join(self.src_order),
                "motion_art": bool(self.motion_art),
                "bg": self.bg_mode,
                "bg_dim": round(self.bg_dim, 2),
                "bg_motion": round(self.bg_motion, 2),
                "align": self.align,
                "pop": self.pop,
                "edge": self.edge,
                "focus": self.focus,
                "line_spacing": round(self.line_spacing, 2),
                "sung_color": ("auto" if self._sung is None else
                               "white" if self._sung == QColor("white")
                               else self._sung.name()),
                "interlude": round(self.interlude, 2),
                "resync": bool(self.resync),
                "auto_time": bool(self.auto_time),
                "unpause_delay": round(self.clock.unpause_delay, 3),
                "pop_min": round(self.pop_min, 2),
                "beat": round(self.beat_scale, 2),
                "roman": self.roman,
                "genius_auto": bool(self.genius_auto),
                "furigana": bool(self.furigana),
                "src_spicy": bool(self.src_spicy),
                "src_amll": bool(self.src_amll),
                "src_youly": bool(self.src_youly),
                "src_netease": bool(self.src_netease),
                "src_lrclib": bool(self.src_lrclib),
                "src_local": bool(self.src_local),
                "src_blend": bool(self.src_blend),
                "ne_graft": bool(self.ne_graft),
                "align_on": bool(self.align_on),
                "align_model": str(self.align_model),
                "align_stems": bool(self.align_stems),
                "align_device": self.align_device,
                "align_spare": round(self.align_spare, 2),
                "align_free": bool(self.align_free),
                "align_ahead": int(self.align_ahead),
                "spin": round(self.spin, 2),
                "zero_g": round(self.zero_g, 2),
                "clouds": round(self.clouds, 2),
                "browse_now": bool(self.show_now_card),
                "browse_art": bool(self.browse_art),
                "fps_cap": round(self.fps_cap, 2),
        }

    def autosave(self) -> None:
        """Write settings as soon as they change, not only on a clean exit.

        closeEvent never runs if the process is interrupted -- Ctrl+C from the
        terminal or a SIGTERM dropped everything the user had just set. Polling
        for a change is cheap (19 scalars) and catches every path that mutates
        them: the menu, the keys, anything.
        """
        if self.args.no_persist:
            return
        state = (self.settings_dict(), dict(self.offsets),
                 {t: dict(v) for t, v in self.romaji_fix.items()}, self.genius_token,
                 {t: dict(v) for t, v in self.genius_fix.items()}, dict(self.genius_rev),
                 {t: dict(v) for t, v in self.est_raw.items()})
        if state == self._saved and CONFIG.exists():
            return
        save_settings(*state)
        self._saved = state

    def closeEvent(self, ev) -> None:
        self.frame_timer.stop()
        self.poll_timer.stop()
        self.fetcher.stop = True
        self.art_cache.stop = True
        self.motion.stop = True
        self.aligner.stop = True
        for sig in (self.aligner.finished_track, self.aligner.progress,
                    self.fetcher.ready, self.fetcher.beat_ready,
                    self.fetcher.index_ready, self.fetcher.index_progress,
                    self.fetcher.genius_ready, self.fetcher.artists_ready,
                    self.fetcher.recents_ready, self.fetcher.catsearch_ready,
                    self.fetcher.backfill_ready, self.fetcher.backfill_progress,
                    self.fetcher.queue_ready, self.fetcher.suggest_ready,
                    self.fetcher.discover_ready, self.fetcher.ne_roman_ready,
                    self.fetcher.album_ready,
                    self.art_cache.loaded, self.motion.ready):
            try:
                sig.disconnect()
            except Exception:
                pass
        self.fetch_thread.join(timeout=0.6)
        self.autosave()
        if self.index.dirty:
            self.index.save()
        ev.accept()


def hide_own_console() -> None:
    """Drop the console window Windows opened just for us.

    Double-clicking a .py file runs it under python.exe, which allocates a
    console -- so a black window sits behind the lyrics for the whole session.
    pythonw.exe does not, which is what spicy-lyrics.pyw is for, but the file
    people reach for is this one.

    Only a console we own is hidden. Started from a terminal, the console is
    shared with the shell that launched us, and taking that away would close
    the window someone is working in and swallow every message meant for them.
    GetConsoleProcessList tells the two apart: a console made for us has one
    process attached, an inherited one has at least the shell as well.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        buf = (ctypes.c_uint * 8)()
        if k32.GetConsoleProcessList(buf, 8) > 1:
            return
        wnd = k32.GetConsoleWindow()
        if wnd:
            ctypes.windll.user32.ShowWindow(wnd, 0)
    except Exception:
        pass


EXC_REPEATS, EXC_SUMMARY = 3, 500


def install_excepthook() -> None:
    """Keep one bad frame from taking the window down with it.

    PyQt turns an unhandled exception inside a slot into a call to qFatal(),
    which aborts the process outright -- a single undefined name in tick() once
    killed this app three times in a row, with no window and no message, only a
    core dump. An installed hook takes precedence over that path, so the frame
    is lost and the event loop carries on.

    Repeats are folded deliberately. tick() runs sixty times a second and
    anything that fails once there usually fails every frame after, so printing
    each one would bury the first traceback -- the only one that says where the
    trouble started -- under thousands of identical copies, and take the journal
    with it.
    """
    seen: dict[tuple, int] = {}

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc, tb)
            return
        last = tb
        while last is not None and last.tb_next is not None:
            last = last.tb_next
        where = ((last.tb_frame.f_code.co_filename, last.tb_lineno)
                 if last is not None else ("?", 0))
        key = (exc_type, *where)
        n = seen[key] = seen.get(key, 0) + 1
        if n <= EXC_REPEATS:
            traceback.print_exception(exc_type, exc, tb)
            if n == EXC_REPEATS:
                print(f"[{exc_type.__name__} at {where[0]}:{where[1]} is "
                      f"repeating; further copies will be counted, not printed]",
                      file=sys.stderr, flush=True)
        elif n % EXC_SUMMARY == 0:
            print(f"[{exc_type.__name__} at {where[0]}:{where[1]}: {n} times]",
                  file=sys.stderr, flush=True)

    sys.excepthook = hook


def main() -> None:
    install_excepthook()
    hide_own_console()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--offset", type=float)
    ap.add_argument("--split", choices=["none", "long", "all"], default="none")
    ap.add_argument("--split-threshold", type=float, default=0.7)
    ap.add_argument("--blur", type=float, metavar="SCALE",
                    help="depth-blur strength for distant lines (default 1.0)")
    ap.add_argument("--glow", type=float, metavar="SCALE",
                    help="bloom strength on sung text, 0 disables (default 1.0)")
    ap.add_argument("--font-scale", type=float, metavar="SCALE",
                    help="multiplier on the lyric text size (default 1.0)")
    ap.add_argument("--interlude", type=float, metavar="SECS",
                    help="show dots for instrumental gaps at least this long, "
                         "0 disables (default 4.0)")

    bg = ap.add_argument_group("background")
    bg.add_argument("--bg", choices=BG_MODES,
                    help="art: blurred cover, slowly drifting (default). "
                         "mesh: animated blobs in the cover's palette, no cover "
                         "needed. solid: flat, nothing moving.")
    bg.add_argument("--bg-dim", type=float, metavar="0-1",
                    help="veil over the background; higher is darker and makes "
                         "the lyrics carry more (default 0.65)")
    bg.add_argument("--bg-motion", type=float, metavar="SCALE",
                    help="drift speed, 0 freezes it entirely (default 1.0)")
    bg.add_argument("--beat", type=float, metavar="SCALE",
                    help="pulse the background on the beat, using Spotify's own "
                         "analysis of the track; 0 disables (default 1.0)")

    fx = ap.add_argument_group("lyric effects")
    fx.add_argument("--align", choices=ALIGNMENTS,
                    help="base alignment; duet lines always take the other side "
                         "(default left)")
    fx.add_argument("--pop", type=float, metavar="SCALE",
                    help="lift and swell on the syllable being sung, 0 disables "
                         "(default 1.0)")
    fx.add_argument("--pop-min", type=float, metavar="SECS",
                    help="only pop words held at least this long, so the rapid "
                         "syllables stay still; 0 pops every word (default 0.45)")
    fx.add_argument("--edge", type=float, metavar="SCALE",
                    help="softness of the fill boundary sweeping through each "
                         "word, 0 for a hard edge (default 1.0)")
    fx.add_argument("--focus", type=int, metavar="N",
                    help="show only N lines either side of the active one, "
                         "0 shows all (default 0)")
    fx.add_argument("--line-spacing", type=float, metavar="SCALE",
                    help="gap between lines (default 1.0)")
    fx.add_argument("--roman", choices=ROMAN_MODES,
                    help="romanise CJK lyrics: 'instead' replaces the original, "
                         "'under' sets it in smaller type beneath, filled in sync. "
                         "Inert on tracks with no transliteration (default off)")
    fx.add_argument("--furigana", action=argparse.BooleanOptionalAction, default=None,
                    help="set kana readings above the kanji, the way a Japanese "
                         "lyric booklet does (default off)")
    fx.add_argument("--genius-auto", action=argparse.BooleanOptionalAction, default=None,
                    help="look a human-written romanisation up on Genius for every "
                         "CJK track as it loads, instead of waiting for G. Needs a "
                         "Genius token (default off)")
    fx.add_argument("--clouds", type=float, default=None, metavar="N",
                    help="troll: set every line adrift in a soft cloud, floating "
                         "in from off-screen as it arrives and away again once "
                         "it has passed. N scales the motion (default 0, off)")
    fx.add_argument("--zero-g", type=float, default=None, metavar="N",
                    help="troll: cut every word loose from its line and let it "
                         "drift, bouncing off the window edges. N scales how fast "
                         "(default 0, off)")
    fx.add_argument("--spin", type=float, default=None, metavar="N",
                    help="troll: spin the word being sung through a full turn, "
                         "over exactly as long as it lasts. N scales how many "
                         "turns (default 0, off)")
    br = ap.add_argument_group("browse view")
    br.add_argument("--browse-now", action=argparse.BooleanOptionalAction, default=None,
                    help="show the now-playing card on the browse home screen "
                         "(default on)")
    br.add_argument("--browse-art", action=argparse.BooleanOptionalAction, default=None,
                    help="load cover thumbnails in the browse view; off makes it "
                         "text-only and does no image fetching (default on)")
    src = ap.add_argument_group("lyric sources, in priority order")
    src.add_argument("--src-spicy", action=argparse.BooleanOptionalAction, default=None,
                     help="Spicy Lyrics' own cache, read out of Spotify. Always "
                          "tried first; --no-src-spicy to see what the others "
                          "would give instead (default on)")
    src.add_argument("--src-amll", action=argparse.BooleanOptionalAction, default=None,
                     help="amll-ttml-db: community word-by-word TTML, matched by "
                          "Spotify id and then by title/artist (default on)")
    src.add_argument("--src-youly", action=argparse.BooleanOptionalAction, default=None,
                     help="YouLy+ (LyricsPlus): scrapes Apple/Musixmatch/Spotify/QQ "
                          "live. Set LYRICSPLUS_BASE to point at your own instance "
                          "(default on)")
    src.add_argument("--src-netease", action=argparse.BooleanOptionalAction, default=None,
                     help="NetEase Cloud Music: word-level where it has it, and "
                          "a human-written romanisation on the same clock as the "
                          "lyrics (default on)")
    src.add_argument("--src-lrclib", action=argparse.BooleanOptionalAction, default=None,
                     help="LRCLIB: line-level LRC only, so it is the last resort "
                          "(default on)")
    src.add_argument("--src-local", action=argparse.BooleanOptionalAction,
                     default=None,
                     help="use alignments this machine made against the audio "
                          "itself. Last in the order by default, so it only "
                          "speaks for songs nothing else has word timing for")
    src.add_argument("--src-blend", action=argparse.BooleanOptionalAction, default=None,
                     help="QQ Music's word timings under Apple Music's lines "
                          "(LRCLIB's where Apple has none), with NetEase voting "
                          "on where each line starts. Three lookups rather than "
                          "one, and independent of the switches above (default "
                          "off)")
    src.add_argument("--ne-graft", action=argparse.BooleanOptionalAction, default=None,
                     help="let NetEase lend its word timings to a line-synced "
                          "source ranked above it, so the words on screen are "
                          "one source's and the clock behind them another's "
                          "(default on)")
    fx.add_argument("--sung-color", metavar="COLOR",
                    help="colour of sung text: 'white', 'auto' to tint it from "
                         "the cover, or any #rrggbb (default white)")
    ap.add_argument("--art", action=argparse.BooleanOptionalAction, default=None,
                    help="album art panel on wide windows (default on)")
    ap.add_argument("--volume-bar", action=argparse.BooleanOptionalAction, default=None,
                    help="volume slider beside the cover (default on)")
    ap.add_argument("--src-order", metavar="A,B,C", default=None,
                    help="order the lyric providers are consulted in, e.g. "
                         "\"amll,spicy,netease,youly,lrclib\"; unlisted ones keep "
                         "their usual place at the end")
    ap.add_argument("--font", metavar="FAMILY", default=None,
                    help="font family by name, e.g. \"Segoe UI\" or \"Inter\"; "
                         "empty picks the first of the built-in stack that is "
                         "installed")
    ap.add_argument("--player", choices=["auto", "mpris", "cdp", "smtc"],
                    default="auto",
                    help="how to read the player: 'mpris' is the desktop bus "
                         "(Linux), 'cdp' is Spotify's own debug port, 'smtc' is "
                         "Windows' system media transport, which needs no launch "
                         "flag and works with the Store build but carries no "
                         "volume and no Spicy Lyrics (default auto)")
    ap.add_argument("--motion-art", action=argparse.BooleanOptionalAction, default=None,
                    help="play the animated cover where Apple Music has one "
                         "(default off; needs ffmpeg)")
    fx.add_argument("--duet-color", metavar="MODE", default=None,
                    help="fill for a duet's second voice: 'off' to paint it like "
                         "every other line, 'album tint' to lift a second colour "
                         "out of the cover, or any #rrggbb (default off)")
    ap.add_argument("--view-mode", choices=VIEW_MODES, default=None,
                    help="'regular' gives the cover its own side panel; 'compact' "
                         "puts the song in a top strip and hands the width to the "
                         "lyrics, with the cover shown small beside it (default "
                         "regular)")
    ap.add_argument("--unpause-delay", type=float, default=None, metavar="SECS",
                    help="how long the words hold still after an unpause, "
                         "covering the moment the player's audio takes to come "
                         "back. Nothing reports what this should be, so it is a "
                         "plain number set by ear (default %.2fs); 0 disables it"
                         % UNPAUSE_DELAY)
    ap.add_argument("--auto-time", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="measure each song's timing against Spotify's analysis "
                         "of it and correct what is found. A track you have "
                         "tuned by hand keeps your figure; those are also what "
                         "calibrates the measurement, so nothing is applied "
                         "until a few of them exist (default on)")
    ap.add_argument("--resync", action=argparse.BooleanOptionalAction, default=None,
                    help="let the app nudge the player to keep its clock on its "
                         "audio: a seek after Spotify rolls over to the next track "
                         "by itself, and a seek to the pause point while paused, "
                         "which is silent and is what keeps unpausing from costing "
                         "0.2s of sync (default on; --no-resync to disable). This "
                         "is the manual 'nudge the scrubber' fix, automated.")
    al = ap.add_argument_group("local forced alignment (align_song.py)")
    al.add_argument("--local-align", dest="align_on",
                    action=argparse.BooleanOptionalAction, default=None,
                    help="align songs against their own audio on this machine "
                         "(default on). --no-local-align closes both ways in, "
                         "Shift+A and the queued-ahead jobs, and makes the "
                         "rest of this group do nothing")
    al.add_argument("--align-model", choices=ALIGN_MODELS, default=None,
                    help="sync is this project's own model, which reads the "
                         "waveform and places every word itself; whisper is "
                         "the older transcribe-then-match chain, and the "
                         "fallback when no trained model is on disk "
                         "(default sync)")
    al.add_argument("--align-stems", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="separate the vocal out with demucs before aligning. "
                         "Better timings and several times slower: 0.317s "
                         "against 0.569s on the songs this was measured on. "
                         "The model is chosen to match, so this switch changes "
                         "both halves (default off)")
    al.add_argument("--align-device", choices=ALIGN_DEVICES, default=None,
                    help="auto uses the GPU only when the card has room beside "
                         "whatever else is on it, gpu insists, cpu never looks "
                         "(default auto)")
    al.add_argument("--align-ahead", type=int, default=None, metavar="N",
                    help="align this many queued tracks before they are "
                         "reached, up to 7, 0 to do none (default %d). Skips "
                         "anything that already has word timing or would not "
                         "fit on the GPU" % DEFAULTS["align_ahead"])
    al.add_argument("--align-spare", type=float, default=None, metavar="GB",
                    help="VRAM left for everything else, whatever the aligner "
                         "works out it wants (default %.2f)"
                         % DEFAULTS["align_spare"])
    al.add_argument("--align-free", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="drop the three models when an alignment finishes "
                         "instead of keeping them loaded for the next song "
                         "(default on). Keeping them saves about half a minute "
                         "per song and costs several GB of RAM and VRAM for as "
                         "long as the window is open")
    ap.add_argument("--save-dir", default=".", metavar="DIR",
                    help="where the S key writes .ttml files (default: cwd)")
    ap.add_argument("--no-persist", action="store_true",
                    help=f"do not remember settings in {CONFIG}")
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--top", action="store_true", help="keep the window above others")
    ap.add_argument("--opacity", type=float, default=1.0, metavar="0-1")
    ap.add_argument("--fps-cap", type=float, default=None, metavar="N",
                    help="ceiling on the animation rate. The frame timer follows "
                         "the refresh rate of the screen the window is on, divided "
                         "down to the first integer step at or under this, so a "
                         "60Hz and a 240Hz panel cost the same (default 60)")
    ap.add_argument("--snapshot", metavar="PATH",
                    help="debug: render the window to PATH after --snapshot-delay, then exit")
    ap.add_argument("--snapshot-delay", type=float, default=8.0)
    ap.add_argument("--freeze", type=float, metavar="SECS",
                    help="debug: pin the clock to this position instead of following MPRIS")
    ap.add_argument("--track", metavar="ID",
                    help="debug: render this track id instead of what is playing")
    args = ap.parse_args()

    saved = {} if args.no_persist else load_settings()
    for key in DEFAULTS:
        attr = {"panel": "art"}.get(key, key)
        if getattr(args, attr) is None:
            setattr(args, attr, saved.get(key, DEFAULTS[key]))

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    w = LyricsView(args)
    w.resize(1280, 820)
    if args.top:
        QTimer.singleShot(600, lambda: w.set_on_top(True))
    if args.opacity < 1.0:
        w.setWindowOpacity(max(0.2, args.opacity))
    def _bye(*_):
        w.quit_requested = True
    signal.signal(signal.SIGINT, _bye)
    if hasattr(signal, "SIGTERM") and os.name != "nt":
        signal.signal(signal.SIGTERM, _bye)

    w.showFullScreen() if args.fullscreen else w.show()
    if args.snapshot:
        def grab():
            w.grab().save(args.snapshot)
            print(f"saved {args.snapshot}")
            app.quit()
        QTimer.singleShot(int(args.snapshot_delay * 1000), grab)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
