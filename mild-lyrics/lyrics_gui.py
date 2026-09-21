#!/usr/bin/env python3
"""
Apple Music / Spicy Lyrics-style lyrics window for the running Spotify app.

Fetches lyrics from Spicy Lyrics' API (see spicy_lyrics.py) and renders them
against the MPRIS playback clock. Layout mirrors the Spicy Lyrics view in Spotify:
album art panel on the left, lyrics column on the right, every line the same
size with depth conveyed by opacity + distance blur rather than scaling, and
the active line filling syllable-by-syllable as it is sung.

That column is one of several -- see renderers.py, and --renderer. The window
draws the background, the cover, the header and every overlay; what happens
between them belongs to whichever renderer is holding the column.

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
    ./lyrics_gui.py --renderer spotlight        # one line, large, no scrolling
    ./lyrics_gui.py --renderer word             # one word at a time
    ./lyrics_gui.py --rise 2 --pop 0            # words go up as sung, and stay

Keys:
    M         settings menu -- everything below is editable there, so there is
              nothing to memorise; arrows or the scroll wheel change a value
    /         search every cached song by any line in it, and Genius for the
              lines no cached song has; Enter plays the hit
    I         what this song is: type, language, songwriters, analysis
    Y         review the document on screen -- the characters that should not
              be in a lyric, the syllable splits, and everything overlapping
              everything else; meant for a TTML you dropped in or are writing.
              K in there says a seam it doubted is right, and the splitter
              learns the word for good -- in here and in the editor both
    Shift+Y   mark those faults on the words while the song plays
    F / F11   fullscreen          Space     play/pause
    [ / ]     this track -/+ 50ms < / >     seek -/+ 5s
    Shift+[ ] the same, by 10ms
    0         clear this track    Shift+0   reset global offset
    Up / Down previous / next line
    N / P     next / prev track   X         resync to audio
    D         background style    L         line alignment
    V         visualizer
    E         word pop            O         focus mode
    U         sung colour         G / B     glow / depth blur
    A         regular/compact     + / -     text size
    C         copy line           Shift+C   copy all
    S         save as .ttml       Shift+S   copy a lyric card
    R         reload lyrics       Shift+R   fix this line's romaji
    Shift+G   fetch a human romanisation from Genius (needs a token, set in M)
    T         always on top       H / ?     this help
    Q / Esc   quit
    click a line to seek to it, drag the progress bar to scrub, scroll to
    browse (it re-centres after a moment), scroll on the volume bar to change
    it, double-click the art to go full.

Everything above persists to ~/.config/spicy-lyrics/gui.json between runs.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from collections import OrderedDict
import hashlib
import os
import queue
import random
import tempfile
import pathlib
import re
import signal
import statistics
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
import macplayer as MP  # noqa: E402
import noconsole  # noqa: E402
import renderers as RD  # noqa: E402
import review as RV  # noqa: E402
import saves  # noqa: E402
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


from PyQt6.QtCore import (  # noqa: E402
    QPointF, QRectF, Qt, QThread, QTimer, QUrl, pyqtSignal, QObject,
)
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
SAMPLE_MS = 16
WARM_LOOK = 0.25
WARM_PATIENCE = 60.0
SLEW_MAX, SLEW_TIME = 0.6, 0.35
RESUME_SETTLE = 1.0
RESUME_STEP_FLOOR = 0.06


def _step_floor(got: dict) -> float:
    """How large a step has to be, on THIS player, to mean anything.

    RESUME_STEP_FLOOR is the floor for a player that answers continuously:
    below it, a forward step at a resume is the poll interval and the status
    arriving a moment late, not a clock that leapt.

    A player that answers in steps needs a bigger one. A browser publishes a
    position four times a second at best -- Firefox's own MPRIS once a second
    -- so the first reading after an unpause can be a whole update interval
    further on than the last one while nothing whatsoever has leapt. Measured
    on the bus: a 0.28s step, which is exactly plasma-browser-integration's
    refresh, was being read as a 0.244s leap and held against the words for
    the rest of the track.

    So the transport says what its player's resolution is (see
    SessionTransport._tick, which learns it by watching when the answer
    changes) and a step smaller than that is not evidence of anything. Zero
    or missing for a transport that does not know, which is every one that
    reads a clock rather than a series of answers.
    """
    return max(RESUME_STEP_FLOOR, abs(float(got.get("grain") or 0.0)))


def _within(want: float, cap: float) -> float:
    """`want`, held inside +/-|cap|. The ceiling on a resume correction is a
    SIZE, and the correction has a direction of its own."""
    cap = abs(cap)
    return max(-cap, min(cap, want))


def _measured_cap(setting: float) -> float:
    """How large a MEASURED resume correction is allowed to be.

    The setting when it is a ceiling, and the default when it is not. See
    `_stated_push`: the two halves of `unpause_delay` mean different things
    in measured mode because the two directions are not equally knowable.
    """
    return setting if setting > 0 else UNPAUSE_DELAY


def _stated_push(setting: float) -> float:
    """How far to move the words on top of whatever was measured.

    Only the negative half of `unpause_delay`, and only because that half
    cannot be measured at all.

    A player whose clock LEAPS forward on resume gives itself away: the
    position moves further than the wall clock did, and that difference is
    the whole correction. A player whose AUDIO leads its own reported clock
    does not: every reading it gives is self-consistent, the position simply
    starts from an origin a tenth of a second behind the sound. Nothing in a
    sequence of honest readings can reveal it, so it has to be told -- and a
    setting that is only ever a ceiling has no way to be told anything.

    So in measured mode a positive setting caps what is read, which is what
    it has always done, and a negative one is added to it. Both directions of
    the number now move the words in the direction somebody dialling it in
    expects, which the ceiling alone did not: dialled negative it did nothing
    whatever, because a ceiling has no sign.
    """
    return setting if setting < 0 else 0.0
RESUME_MEASURE = 2.0
PIN_EDGE = 1.0
FRAME_IDLE_HZ = 10.0


def mono() -> float:
    """This program's clock for how much time has passed.

    NOT time.monotonic, and on Windows that is the difference between smooth
    and not. Under CPython 3.12 and earlier, time.monotonic on Windows is
    GetTickCount64, which moves in steps of 15.625ms -- so every reading of
    elapsed time in this program was rounded down to the nearest sixteenth of
    a second there, on a clock read sixty times a second to decide where a
    word has been sung to and how far a spring has travelled.

    Three things read it every frame and all three reach the eye. _frame asks
    how much of the period is left, and against a 15.6ms grain asked the timer
    for the wrong number in a fresh direction every frame -- measured at a
    20ms period, the interval smeared from 6ms to 34ms around a 20ms peak, and
    on perf_counter it lands in four buckets, 19 to 21, with nothing over 1.5x
    the period. Clock.position carries the song forward from the last reading,
    so the fill sweeping through a word advances in 15.6ms lurches. And
    Amll._step takes the difference between two of these readings as the
    timestep it integrates every spring in the column with, which comes out
    15.6, 15.6, 15.6, 31.2 where it should have been a flat 20.

    THE FRAME RATE IS NOT THE REFRESH RATE, and the difference decides how bad
    that last one gets. retune_frames runs at an integer divisor of the panel,
    so eff_hz is never above fps_cap whatever the panel does -- and at the
    default cap of 60 that puts the period at 16.7ms or longer, ALWAYS longer
    than the 15.625ms grain. A screen slower than the cap only makes it longer
    still. That is why the step merely alternated rather than stopping.

    Raise --fps-cap past 64 and it stops. Once the period is shorter than the
    grain, consecutive frames read the same tick and the step is zero -- a
    frame the column does not move on at all. Over 2000 frames of Amll._step,
    by the rate the frames are actually DRAWN at, which is the divided one:

        50 fps   0.0% of frames a zero step     step 15.6-31.2ms
        60 fps   0.0%                           step 15.6-31.2ms
        75 fps  14.7%                           step  0.0-15.6ms
       120 fps  46.7%                           step  0.0-15.6ms
       144 fps  55.6%                           step  0.0-15.6ms
       240 fps  73.3%                           step  0.0-15.6ms

    On perf_counter every one of those is a flat step at the period. So the
    divisor was quietly keeping the default cap out of the bottom four rows,
    and anyone who had raised it to match a fast panel was in them.

    perf_counter is QueryPerformanceCounter on Windows and the same
    clock_gettime(CLOCK_MONOTONIC) that monotonic already is everywhere else,
    so this is a Windows fix that changes nothing elsewhere. CPython 3.13
    moved monotonic onto QPC too, which is why this was only ever felt on some
    machines.

    Used for EVERY elapsed-time reading in this program rather than only the
    three that showed, because the danger in a half-done change is mixing two
    clocks in one subtraction -- Clock.position differences `now` against a
    stamp the transports wrote, and those are not the same lines of code. One
    clock everywhere cannot be mixed. Nothing here is ever serialised, sent or
    saved, so no reading outlives the process that took it.
    """
    return time.perf_counter()

# --- unpause delay --------------------------------------------------------
UNPAUSE_DELAY = 0.25

APP_NAME = "Mild Lyrics"
APP_SLUG = "mild-lyrics"
OLD_SLUG = "spicy-lyrics"

SAY_DRIFT = 0.25
SAY_EVERY = 0.5

POLL_IDLE = 0.4
GENIUS_TYPED_MS = 150
TROUBLE_QUIET = 3600.0
FOLLOW_DRIFT = 0.35
FOLLOW_STEADY = 0.6
FOLLOW_GONE = 2.0
FOLLOW_AGAIN = 0.2
FOLLOW_TRIES = 4
FOLLOW_REST = 3.0
POLL_WAITING = 0.12
RETRY_FIRST = 0.3
RETRY_MAX = 30.0


def app_dir(kind: str) -> pathlib.Path:
    """Where this app keeps its settings or its cache, per platform.

    Windows has no XDG anything -- pointing a config file at ~/.config there
    leaves it somewhere no installer, backup or uninstaller will look. Roaming
    for settings, Local for the cache, which is Windows' own division and the
    same one XDG is drawing.

    macOS draws the same division under ~/Library: Application Support is
    backed up and carried to a new machine, Caches is not, which is exactly
    what the two words mean here. XDG_* is still honoured where it is set,
    because somebody who has set it has said what they want -- and a Mac that
    already has a ~/.config/mild-lyrics from before this was written keeps
    using it rather than being silently started over. See _mac_dir.
    """
    if os.name == "nt":
        var = "APPDATA" if kind == "config" else "LOCALAPPDATA"
        root = os.environ.get(var)
        if not root:
            root = pathlib.Path.home() / "AppData" / (
                "Roaming" if kind == "config" else "Local")
        return _migrated(pathlib.Path(root))
    var = "XDG_CONFIG_HOME" if kind == "config" else "XDG_CACHE_HOME"
    root = os.environ.get(var)
    if not root and sys.platform == "darwin":
        return _mac_dir(kind)
    root = root or (
        pathlib.Path.home() / (".config" if kind == "config" else ".cache"))
    return _migrated(pathlib.Path(root))


def _mac_dir(kind: str) -> pathlib.Path:
    """A Mac's own place for this, unless an older copy is already elsewhere.

    The XDG directories are where every version of this program before the Mac
    was supported would have put things, and a Mac that ran one of those has a
    real settings file in one of them. Moving it is not this function's job --
    people copy this folder between machines and run it from a stick -- so the
    rule is simply: a directory that is already there wins, and otherwise the
    Mac's own is made.
    """
    legacy = pathlib.Path.home() / (".config" if kind == "config" else ".cache")
    for slug in (APP_SLUG, OLD_SLUG):
        if (legacy / slug).is_dir():
            return _migrated(legacy)
    root = pathlib.Path.home() / "Library" / (
        "Application Support" if kind == "config" else "Caches")
    return _migrated(root)


def _migrated(root: pathlib.Path) -> pathlib.Path:
    """<root>/mild-lyrics, carrying over the old name's contents once."""
    new, old = root / APP_SLUG, root / OLD_SLUG
    try:
        if old.is_dir() and not new.exists():
            old.rename(new)
    except Exception:
        pass
    return new


def _writable(path: pathlib.Path) -> bool:
    """Whether a file can really be made in this directory.

    Asked by making one and taking it away again, because that is the only
    form of the question with a reliable answer. os.access reads the
    permission bits, and on Windows those are not what decides it -- an ACL,
    a read-only attribute, a folder redirected into OneDrive while it is
    signed out, or a directory like C:\\Windows\\System32 that looks readable
    to everyone and writable to nobody.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".mild-lyrics-{os.getpid()}"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


SAVE_HOME = saves.PLAYER


def save_dir(want: str) -> tuple[pathlib.Path, bool]:
    """Where a file the user asked to keep actually goes, and whether that is
    where they asked for it.

--save-dir defaults to SAVE_HOME, which is lyrics/fetched beside
    the program -- the same place on both platforms and whoever started it,
    and kept apart from what the editor writes because they are not the same
    kind of file; see saves.py.

    It used to default to the folder the program lives in, and before that to
    the working directory. That is the right answer when the program was
    started from a terminal and no answer at all when it was not, and the two
    platforms then disagreed for no reason anybody chose: running `python
    mild-lyrics/lyrics_gui.py` from the checkout puts the files in the
    checkout, and a Windows shortcut with no "Start in" set leaves the working
    directory at C:\\Windows\\System32, where every save is "[Errno 13]
    Permission denied" -- reported as a save that failed, on a machine where
    nothing was wrong except that nobody had said where to put the file.

    So a directory that cannot be written to is not an error here, it is a
    question nobody answered, and the answer is the user's own Music folder.
    The caller is told it moved so it can say so -- silently writing
    somewhere else is its own kind of failure -- and --save-dir still means
    exactly what it says wherever it can be honoured.
    """
    asked = pathlib.Path(want or SAVE_HOME).expanduser()
    if _writable(asked):
        return asked, True
    home = pathlib.Path.home()
    for path in (home / "Music" / APP_SLUG, home / APP_SLUG, app_dir("cache")):
        if _writable(path):
            return path, False
    return asked, True


CONFIG = app_dir("config") / "gui.json"
INDEX = app_dir("cache") / "index.json"
PEOPLE_KEYS = {"people_skip": "whose syncs to refuse",
               "people_pick": "whose syncs to prefer"}

SRC_LABEL = {"spicy": "Spicy Lyrics Community", "apple": "Apple Music",
             "amll": "amll-ttml-db", "unison": "Unison",
             "qq": "QQ Music",
             "netease": "NetEase", "kugou": "Kugou", "mxm": "Musixmatch",
             "lrclib": "LRCLIB",
             "genius": "Genius"}


# Sources whose trouble is not worth saying out loud. Empty: LyricsPlus was
# the only one, its door timed out on nearly every song, and it is gone.
TROUBLE_MUTE: set = set()


def unreached(bad) -> str:
    """The sources a walk could not reach, named the way the user ranked them.

    By catalogue rather than by provider, because that is what they ordered
    and what the failure actually costs them -- and deduped through the same
    map, since a source can be more than one door and either of them going
    down is one thing to say. One reason for the lot of them: an outage takes
    a host down, not a source, and the second line would say what the first
    one said.
    """
    said, why = [], ""
    for name, said_why in bad or ():
        src = LS.PROVIDER_SRC.get(name, name)
        if src in TROUBLE_MUTE:
            continue
        label = SRC_LABEL.get(src, name)
        if label not in said:
            said.append(label)
            why = why or said_why
    if not said:
        return ""
    more = f" +{len(said) - 2} more" if len(said) > 2 else ""
    return f"{', '.join(said[:2])}{more} — {why}"


SRC_ATTR = {"spicy": "src_spicy", "apple": "src_apple", "amll": "src_amll",
            "unison": "src_unison",
            "qq": "src_qq", "netease": "src_netease",
            "kugou": "src_kugou", "mxm": "src_mxm", "lrclib": "src_lrclib",
            "genius": "src_genius"}
SRC_DEFAULT = list(LS.SOURCES)
SRC_PARTS, BLENDS, BLEND_OF = LS.SRC_PARTS, LS.BLENDS, LS.BLEND_OF
PROVIDER_SRC, WAS_SRC, BLEND_KEY = LS.PROVIDER_SRC, LS.WAS_SRC, LS.BLEND_KEY
BLEND_LABEL = {"blend": "Apple+QQ", "kublend": "Apple+Kugou",
               "neblend": "Apple+NetEase", "triblend": "Apple+NetEase+QQ",
               "kutriblend": "Apple+NetEase+Kugou"}

DEFAULTS = {
    "offset": 0.0, "font_scale": 1.0, "blur": 1.0, "glow": 1.0,
    "word_glow": 0.0, "syll_hold": 0.0, "panel": True,
    "bg": "art", "bg_dim": 0.65, "bg_motion": 1.0, "bg_fade": 0.6,
    "mesh_style": "blobs", "mesh_tint": 1.0, "mesh_spread": 1.0,
    "mesh_colors": 4,
    "align": "left", "pop": 1.0, "line_drop": 1.0,
    "viz": 0.0, "viz_mode": "bloom",
    "edge": 1.0, "focus": 0, "line_spacing": 1.0, "sung_color": "white",
    "renderer": "flow", "rise": 0.0, "art_side": "left",
    "interlude": 4.0, "resync": True, "pop_min": 0.45, "beat": 1.0,
    "merge_ms": 0.0,
    "scroll_lead": 0.35,
    "auto_time": True, "unpause_delay": UNPAUSE_DELAY,
    "any_player": False, "song_max": 15.0,
    "unpause_mode": "measured",
    "fps_cap": 60.0,
    "roman": "off", "genius_auto": False, "furigana": False,
    "src_spicy": True, "src_apple": True, "src_amll": True,
    "src_unison": True,
    "src_qq": True, "src_netease": True,
    "src_kugou": True, "src_mxm": True, "src_lrclib": True,
    "src_genius": True,
    **{key: True for key in BLEND_KEY.values()},
    "fold_adlibs": True,
    "review_marks": False,
    "people_skip": "",
    "people_pick": "",
    "uncensor": True,
    "ne_graft": True,
    "fetch_ahead": 3,
    "spin": 0.0,
    "zero_g": 0.0, "clouds": 0.0, "float_up": 0.0,
    "off_by_one": 0.0, "searching": 0.0,
    "browse_now": True, "browse_art": True,
    "view_mode": "regular", "volume_bar": True,
    "duet_color": "off", "motion_art": False, "font": "",
    "src_order": ",".join(SRC_DEFAULT),
    "offsets_device": {},
}
DEVICE_POLL = 2.0
DEVICE_APP = "spotify"

GLOW_FULL = 0.40
GLOW_FLOOR = 0.20
BG_MODES = ["art", "mesh", "solid"]
MESH_STYLES = ["blobs", "wash", "veil"]
VIZ_IN_KEY = 8
VIZ_MODES = ["bloom", "pulse", "bars", "tide"]
VIEW_MODES = ["regular", "compact"]
RENDER_MODES = RD.RENDER_MODES
UNPAUSE_MODES = ["measured", "fixed"]
ALIGNMENTS = ["left", "center", "right"]
ART_SIDES = ["left", "right"]
ROMAN_MODES = ["off", "instead", "under"]
SUNG_MODES = ["white", "album tint"]
DUET_MODES = ["off", "album tint"]
OFF_AT_ZERO = {"syll_hold"}

MENU_SECTIONS = [
    ("Text", [
        ("Renderer",          "renderer",     "choice", RENDER_MODES),
        ("Alignment",         "align",        "choice", ALIGNMENTS),
        ("Text size",         "font_scale",   "num",    (0.6, 1.9, 0.05, "{:.2f}")),
        ("Line spacing",      "line_spacing", "num",    (0.6, 2.5, 0.1,  "{:.1f}")),
        ("Focus lines",       "focus",        "num",    (0, 8, 1,        "{:.0f}")),
        ("Sung colour",       "sung_mode",    "choice", SUNG_MODES),
        ("Duet colour",       "duet_color",   "choice", DUET_MODES),
        ("Fold ad-libs",      "fold_adlibs",  "bool",   None),
        ("Review marks",      "review_marks", "bool",   None),
        ("Font",              "font_name",    "text",   None),
    ]),
    ("Motion", [
        ("Word pop",          "pop",          "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Word rise",         "rise",         "num",    (0.0, 4.0, 0.25, "{:.2f}")),
        ("Line drop",         "line_drop",    "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Pop only past",     "pop_min",      "num",    (0.0, 2.0, 0.05, "{:.2f}s")),
        ("Fill softness",     "edge",         "num",    (0.0, 4.0, 0.25, "{:.2f}")),
        ("Glow",              "glow_scale",   "num",    (0.0, 2.0, 0.1,  "{:.1f}")),
        ("Glow every word",   "word_glow",    "num",    (0.0, 2.0, 0.1,  "{:.1f}")),
        ("Hold per syllable", "syll_hold",    "num",    (0.0, 2.0, 0.05, "{:.2f}s")),
        ("Depth blur",        "blur_scale",   "num",    (0.0, 2.0, 0.1,  "{:.1f}")),
        ("Beat response",     "beat_scale",   "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Scroll ahead",      "scroll_lead",  "num",    (0.0, 1.5, 0.05, "{:.2f}s")),
    ]),
    ("Background", [
        ("Background",        "bg_mode",      "choice", BG_MODES),
        ("Mesh style",        "mesh_style",   "choice", MESH_STYLES),
        ("Mesh strength",     "mesh_tint",    "num",    (0.0, 2.5, 0.1,  "{:.1f}")),
        ("Mesh spread",       "mesh_spread",  "num",    (0.3, 2.5, 0.1,  "{:.1f}")),
        ("Mesh colours",      "mesh_colors",  "num",    (1, 4, 1,        "{:.0f}")),
        ("Visualizer",        "viz",          "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Visualizer mode",   "viz_mode",     "choice", VIZ_MODES),
        ("Background dim",    "bg_dim",       "num",    (0.0, 1.0, 0.05, "{:.2f}")),
        ("Background motion", "bg_motion",    "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Background fade",   "bg_fade",      "num",    (0.0, 2.0, 0.1,  "{:.1f}s")),
        ("View mode",         "view_mode",    "choice", VIEW_MODES),
        ("Album art panel",   "show_panel",   "bool",   None),
        ("Album art side",    "art_side",     "choice", ART_SIDES),
        ("Volume slider",     "show_volume",  "bool",   None),
        ("Animated cover",    "motion_art",   "bool",   None),
    ]),
    ("Romanisation", [
        ("Romanisation",      "roman",        "choice", ROMAN_MODES),
        ("Readings above",    "furigana",     "bool",   None),
        ("Use Genius",        "genius_auto",  "bool",   None),
        ("Genius token",      "genius_token", "secret", None),
    ]),
    ("Timing", [
        ("Interlude gap",     "interlude",    "num",    (0.0, 12.0, 0.5, "{:.1f}s")),
        ("Merge flat splits", "merge_ms",     "num",    (0.0, 120.0, 5.0, "{:.0f} ms")),
        ("Timing offset",     "offset",       "num",    (-2.0, 2.0, 0.05, "{:+.2f}s")),
        ("Auto timing",       "auto_time",    "bool",   None),
        ("Unpause delay",     "unpause_delay", "num",   (-1.0, 1.0, 0.01, "{:+.2f}s")),
        ("Unpause hold",      "unpause_mode", "choice", UNPAUSE_MODES),
        ("Auto resync",       "resync",       "bool",   None),
        ("NetEase word sync", "ne_graft",     "bool",   None),
    ]),
    ("Sources", [
        ("", f"src_slot{i}", "bool", None) for i in range(len(SRC_DEFAULT))
    ] + [
        ("Fetch ahead",       "fetch_ahead",  "num",    (0, 7, 1, "{:.0f} tracks")),
        ("Uncensor words",    "uncensor",     "bool",   None),
        ("Refuse syncs by",   "people_skip",  "text",   None),
        ("Prefer syncs by",   "people_pick",  "text",   None),
    ]),
    ("Blends", [
        ("", f"blend_slot{i}", "bool", None) for i in range(len(BLENDS))
    ]),
    ("Player", [
        ("Any media player",  "any_player",   "bool",   None),
        ("Longest song",      "song_max",     "num",    (2.0, 60.0, 1.0, "{:.0f} min")),
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
        ("Float away",        "float_up",     "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Off by one",        "off_by_one",   "num",    (0.0, 1.0, 0.05, "{:.0%}")),
        ("Lost scrolling",    "searching",    "num",    (0.0, 3.0, 0.25, "{:.2f}")),
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

SECTION_NOTE = {
    "Romanisation": "Japanese needs pykakasi and Chinese needs pypinyin, both "
                    "optional; Korean is worked out here and needs nothing. A "
                    "reading the source itself ships always wins",
    "Player": "Off, the window follows Spotify and nothing else. On, it "
              "follows whoever is playing — a song on YouTube in Firefox, a "
              "file in mpv — and a track from any of them is looked up "
              "before it is shown: a music catalogue that has the record, or "
              "a provider that has the words. A video has neither and leaves "
              "the song you had on screen",
    "Blends": "Apple Music's lines with somebody else's word timing under "
              "them — each asked just above the highest source it borrows "
              "from, in the order you ranked the one lending the clock",
}

MENU = [row for _, rows in MENU_SECTIONS for row in rows]
MENU_SPANS = []
_at = 0
for _name, _rows in MENU_SECTIONS:
    MENU_SPANS.append((_at, len(_rows)))
    _at += len(_rows)

HELP_SECTIONS = [
    ("Playback", [
        ("Space", "play / pause"),          ("< / >", "seek -/+ 5s"),
        ("Up / Down", "previous / next line"),
        ("N / P", "next / previous track"),
        ("click", "seek to a line"),        ("drag bar", "scrub"),
        ("wheel", "volume, on its bar"),
    ]),
    ("Timing", [
        ("[ / ]", "offset -/+ 50ms"),       ("Shift+[ / ]", "offset -/+ 10ms"),
        ("0 / Shift+0", "clear track / global offset"),
        ("X", "resync to audio"),
    ]),
    ("Lyrics", [
        ("R", "reload lyrics"),             ("Shift+R", "fix this line's romaji"),
        ("K / Shift+K", "prefer / refuse this sync's maker"),
        ("Shift+G", "romaji from Genius"),
        ("C / Shift+C", "copy line / all"),
        ("S / Shift+S", "save .ttml / card"),
        ("/", "search all lyrics + Genius"), ("I", "song info"),
        ("Y", "review this document"),
        ("Shift+Y", "mark any lyric's faults as it plays"),
    ]),
    ("Look", [
        ("D", "background style"),          ("V", "visualizer"),
        ("Shift+V", "visualizer mode"),     ("L", "line alignment"),
        ("E", "word pop"),                  ("O", "focus mode"),
        ("U", "sung colour"),               ("G / B", "glow / depth blur"),
        ("A", "regular / compact view"),    ("+ / -", "text size"),
    ]),
    ("Window", [
        ("M", "settings menu"),             ("Home", "browse, search & queue"),
        ("F / F11", "fullscreen"),          ("T", "always on top"),
        ("Tab / ← →", "these sections"),    ("H / ?", "close this help"),
        ("Q / Esc", "quit"),
    ]),
]
HELP_KEYS = [row for _name, rows in HELP_SECTIONS for row in rows]
HELP_MARGIN = 26.0


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


def luma_of(img: QImage) -> float:
    """How bright the cover actually is, 0 to 1.

    Deliberately the plain average, black pixels and all. palette_of throws
    those away on purpose -- it is looking for the colours -- and that is
    exactly why it cannot answer this: a cover that is nine tenths black with
    a bright orange burst in it has a vivid orange palette and is a dark
    picture, and the accent wash needs to know the second thing.
    """
    small = img.scaled(32, 32, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    n = small.width() * small.height()
    if not n:
        return 0.4
    total = 0.0
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            total += 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return total / n


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


PIX_BUDGET = 96 << 20
GLOW_BUDGET = 16 << 20

PIX_PER_FRAME = 2
NEW_PER_FRAME = 2
SHAPE_MEMO = 4096


def _pm_bytes(pm: QPixmap) -> int:
    """Roughly what a pixmap costs to keep. Qt does not promise 32 bits per
    pixel, but every format this draws into is, and being out by a channel
    would move a budget, not break one."""
    return max(1, pm.width() * pm.height() * 4)


_DWMWA_CORNER = 33
_DWMWA_BORDER = 34
_DWMWCP_DEFAULT, _DWMWCP_DONOTROUND = 0, 1
_DWMWA_COLOR_NONE, _DWMWA_COLOR_DEFAULT = 0xFFFFFFFE, 0xFFFFFFFF


def _no_dwm_border(w, rounded: bool = False) -> None:
    """Ask DWM not to round or outline this window. Silent where it cannot."""
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = int(w.winId())
        dwm = ctypes.windll.dwmapi                       # noqa: F821
        for attr, value in (
                (_DWMWA_CORNER,
                 _DWMWCP_DEFAULT if rounded else _DWMWCP_DONOTROUND),
                (_DWMWA_BORDER,
                 _DWMWA_COLOR_DEFAULT if rounded else _DWMWA_COLOR_NONE)):
            val = ctypes.c_int(value) if attr == _DWMWA_CORNER else \
                ctypes.c_uint(value)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                                      ctypes.byref(val), ctypes.sizeof(val))
    except Exception:                                    # noqa: BLE001
        pass


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


def advance(fm: QFontMetricsF, txt: str) -> float:
    """fm.horizontalAdvance, remembered per face.

    Text measurement is the whole cost of a cold layout -- wrap_pieces says
    so where it takes care to ask only once per fragment, and measured over
    "NF - Time" it is 985 calls and about half the milliseconds of laying the
    document out from nothing.

    The memo hangs on the QFontMetricsF rather than on the window, and that is
    what makes it worth having. A cold layout is not a rare event: layout_cache
    is emptied by every resize and by every track change, and -- the case this
    is really for -- by a better source arriving mid-song, which is the same
    words with a better clock. The fragments are IDENTICAL across a re-time, so
    the second cold layout is asking the font exactly what it asked the first
    time. Hanging the memo off the face means it survives the cache being
    emptied, and dies by itself when the type changes, because a new face is a
    new object and _lyric_face is what keeps them.

    The ration is generous and the clear is blunt because the working set is
    one song's distinct fragments -- 219 on that document, and a long one runs
    to a few thousand.
    """
    try:
        memo = fm._adv
    except AttributeError:
        memo = fm._adv = {}
    got = memo.get(txt)
    if got is None:
        if len(memo) > 8192:
            memo.clear()
        got = memo[txt] = fm.horizontalAdvance(txt)
    return got


def split_to_fit(piece: tuple, fm: QFontMetricsF, width: float) -> list[tuple]:
    """Break one timed fragment into chunks that each fit the column.

    Japanese and Chinese lines carry no spaces, so the whole line arrives as a
    single unbreakable token and used to run straight off the right edge. Split
    it per character and interpolate the timings across the pieces.
    """
    s, e, txt, part = piece
    if len(txt) < 2 or advance(fm, txt) <= width:
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


def wrap_shape(pieces, fm: QFontMetricsF, width: float, align: str):
    """Where the words go, with no clock in it.

    Rows of (x, advance, text, piece, chunk), plus the character lengths of
    every piece that had to be split -- which is everything wrap_pieces used
    to work out except WHEN each fragment is sung. Nothing here reads a time:
    the wrapping is decided by the text, the face and the width, and a split
    piece is cut on characters.

    Remembered on the QFontMetricsF for the same reason advance() is, and it
    is the same working set: one song's distinct lines at the widths it has
    been shown at. A better source arriving mid-song is the SAME words with a
    better clock, so it asks for shapes this has already worked out and pays
    only for stamping the new times onto them.
    """
    try:
        memo = fm._shape
    except AttributeError:
        memo = fm._shape = {}
    key = (tuple((pc[2], bool(pc[3])) for pc in pieces), int(width), align)
    got = memo.get(key)
    if got is not None:
        return got

    words: list[list] = []
    cur: list = []
    for i, pc in enumerate(pieces):
        cur.append((i, 0, pc))
        if not pc[3]:
            words.append(cur)
            cur = []
    if cur:
        words.append(cur)

    chunks: dict = {}
    rows: list[list] = [[]]
    x = 0.0
    last_word = len(words) - 1
    for wi, word in enumerate(words):
        adv = [advance(fm, pc[2]) for _i, _c, pc in word]
        core = sum(adv)
        atomic = True
        if core > width:
            grown = []
            for i, _c, pc in word:
                subs = split_to_fit(pc, fm, width)
                if len(subs) > 1:
                    chunks[i] = [len(sub[2]) for sub in subs]
                grown += [(i, ci, sub) for ci, sub in enumerate(subs)]
            word = grown
            adv = None
            atomic = False
        elif x + core > width and rows[-1]:
            rows.append([])
            x = 0.0
        last_piece = len(word) - 1
        for j, (i, ci, (s, e, txt, part)) in enumerate(word):
            if j == last_piece and wi < last_word:
                txt += " "
                w = advance(fm, txt)
            elif adv is not None:
                w = adv[j]
            else:
                w = advance(fm, txt)
            if not atomic and x + w > width and rows[-1]:
                rows.append([])
                x = 0.0
            rows[-1].append((x, w, txt, i, ci))
            x += w
    if align != "left":
        for row in rows:
            if not row:
                continue
            rw = row[-1][0] + advance(fm, row[-1][2].rstrip())
            slack = max(0.0, width - rw)
            dx = slack if align == "right" else slack / 2
            row[:] = [(x + dx, w, t, i, ci) for x, w, t, i, ci in row]
    if len(memo) > SHAPE_MEMO:
        memo.clear()
    memo[key] = (rows, chunks)
    return rows, chunks


def stamp_rows(shape, pieces):
    """A shape, with this document's times written onto it.

    The arithmetic for a split piece is split_to_fit's own, character by
    character, and the untimed case falls out the same way it does there: the
    first chunk carries the whole span and the rest are empty at the end of it.
    """
    rows, chunks = shape
    times: dict = {}
    for i, lens in chunks.items():
        s, e, txt, _part = pieces[i]
        timed = (isinstance(s, (int, float)) and isinstance(e, (int, float))
                 and e > s)
        total = sum(lens)
        out, t = [], s
        for ci, n in enumerate(lens):
            last = ci == len(lens) - 1
            end = e if last or not timed else t + (e - s) * n / total
            out.append((t, end))
            t = end
        times[i] = out
    out_rows = []
    for row in rows:
        line = []
        for x, w, txt, i, ci in row:
            got = times.get(i)
            if got is None:
                s, e = pieces[i][0], pieces[i][1]
            else:
                s, e = got[ci]
            line.append((x, w, txt, s, e))
        out_rows.append(line)
    return out_rows


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


_SINKS: dict[int, tuple[str, str]] = {}


def _pactl(*argv: str) -> str:
    out = subprocess.run(("pactl",) + argv, capture_output=True, text=True,
                         timeout=2.0)
    return out.stdout if out.returncode == 0 else ""


def _sinks() -> None:
    """Index -> (id, name) for every output there is.

    Read only when an index turns up that is not in it. Sinks are made and
    destroyed when a device is plugged in or a profile switched, not while
    something is playing through one, so this is a handful of calls a day
    rather than one every DEVICE_POLL.
    """
    try:
        rows = json.loads(_pactl("-f", "json", "list", "sinks") or "[]")
    except Exception:                                       # noqa: BLE001
        return
    _SINKS.clear()
    for row in rows if isinstance(rows, list) else []:
        name = str((row or {}).get("name") or "")
        if name:
            _SINKS[row.get("index")] = (name, str(row.get("description") or "")
                                        or name)


def audio_sink(app: str = DEVICE_APP) -> tuple[str, str]:
    """Where the song's sound is actually coming out: (id, name to show).

    `app` is whoever is playing it, which is not always Spotify -- see
    SessionTransport.app and the any-media-player setting. The delay being
    corrected belongs to the output, so following the wrong application's
    stream means reading the wrong output's offset.

    The PLAYER's own stream, not the desktop's default output. Moving one
    application to another device is a thing people do, and the delay this is
    asked for belongs to the device the song comes out of rather than to
    whatever would play a notification beep. The default sink stands in while
    nothing is playing, so the window still knows where it is between tracks.

    ("", "") where there is nothing to ask -- no pactl, no PipeWire or
    PulseAudio, no answer from the platform. Everything then shares one
    offset, which is what it did before there was more than one.

    THE OTHER TWO PLATFORMS ANSWER A SLIGHTLY SMALLER QUESTION, because they
    have a smaller one to answer: both name the default output rather than the
    player's own stream. On macOS that is the same question -- there is no way
    for a person to send one application to a different speaker, so the
    default IS where the sound comes out. On Windows there is such a way (App
    volume and device preferences), and finding what it did for one process
    means a COM interface per audio session; the default device is what is
    read instead, which is right for everybody who has not gone into that
    page. Both are worth having: the offset this exists for is a bluetooth
    headset against a monitor's speakers, and that is a change of default.
    """
    if sys.platform == "darwin":
        return MP.default_output()
    if os.name == "nt":
        return windows_output()
    if not sys.platform.startswith("linux"):
        return "", ""
    try:
        rows = json.loads(_pactl("-f", "json", "list", "sink-inputs") or "[]")
        at = None
        for row in rows if isinstance(rows, list) else []:
            props = (row or {}).get("properties") or {}
            who = " ".join(str(props.get(k) or "") for k in
                           ("application.name", "application.process.binary"))
            if app in who.lower():
                at = row.get("sink")
                break
        if at is None:
            name = (_pactl("get-default-sink") or "").strip()
            if not name:
                return "", ""
            if name not in {n for n, _ in _SINKS.values()}:
                _sinks()
            return name, dict(_SINKS.values()).get(name, name)
        if at not in _SINKS:
            _sinks()
        return _SINKS.get(at, ("", ""))
    except Exception:                                       # noqa: BLE001
        return "", ""


_WIN_OUT: tuple = ("", "", 0.0)

WIN_GUID = re.compile(r"\{[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\}")

# Windows keeps an endpoint's names under its own key, as property-store
# values rather than as named ones. The first is the whole label the sound
# settings show ("Headphones (WH-1000XM4 Stereo)"), the second is just the
# part the user is allowed to rename, the third the driver's word for the
# hardware. Any of the three is a name; the interface path is not.
WIN_NAMED = ("{a45c254e-df1c-4efd-8020-67d146a850e0},2",
             "{b3f8fa53-0004-438e-9003-51a46e139bfc},6",
             "{a45c254e-df1c-4efd-8020-67d146a850e0},14")


async def _await_winrt_operation(operation):
    """Await a WinRT operation when the projection has no synchronous get()."""
    return await operation


def _run_winrt_here(call, *args):
    """Create and finish a WinRT async operation on the current thread."""
    operation = call(*args)
    get = getattr(operation, "get", None)
    if callable(get):
        return get()
    import asyncio
    return asyncio.run(_await_winrt_operation(operation))


def _run_async_call(call, *args):
    """Run WinRT work without putting a blocking operation on Qt's GUI thread."""
    qt_gui_thread = (
        threading.current_thread() is threading.main_thread()
        and QApplication.instance() is not None
    )
    if not qt_gui_thread:
        return _run_winrt_here(call, *args)

    box = {}
    done = threading.Event()

    def worker():
        try:
            box["value"] = _run_winrt_here(call, *args)
        except BaseException as exc:
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=worker, name="mild-winrt-call", daemon=True).start()
    done.wait()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _win_reg_name(dev: str) -> str:
    """An output's friendly name, read off the registry rather than asked for.

    Second way round for when the device-information lookup will not answer --
    it is a packaged call and it is the first thing to go when the
    Devices.Enumeration half of the projection is missing, while the registry
    is there on every Windows and costs nothing.

    The interface path carries the endpoint's own guid in it, which is what
    the MMDevices key is named by, so the two need no lookup between them.
    """
    found = WIN_GUID.search(dev or "")
    if not found:
        return ""
    try:
        import winreg

        path = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
                "\\Render\\" + found.group(0) + r"\Properties")
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            for prop in WIN_NAMED:
                try:
                    got = winreg.QueryValueEx(key, prop)[0]
                except OSError:
                    continue
                if isinstance(got, str) and got.strip():
                    return got.strip()
    except Exception:                                       # noqa: BLE001
        return ""
    return ""


def _win_short(dev: str) -> str:
    """A label for an output that will not give a name, short enough to read.

    Last resort, and the point of it is what it is NOT: the interface path is
    ninety characters of guid and it is the id, not a name -- putting it in a
    toast or in the song panel says nothing except that something went wrong
    upstream of the label. The endpoint's first block is stable, is different
    for two identical headsets, and fits.
    """
    found = WIN_GUID.search(dev or "")
    return f"Windows output ({found.group(0)[1:9]})" if found else "Windows output"


def windows_output() -> tuple[str, str]:
    """Windows' current output device: (a stable id, a name to show).

    The id is the device interface path, which is what Windows itself keys a
    device by -- it survives a rename and it is different for two identical
    headsets, which a friendly name is not. It is also not a name: nothing
    shown to the user is ever the path, which is what the two fallbacks below
    the lookup are for.

    Cached for a few seconds because the name costs a device-information
    lookup and this is asked on a timer. The id alone is a cheap call, so the
    cache is checked against it rather than against the clock: plug something
    in and the change is picked up on the next poll, not the next minute.
    """
    global _WIN_OUT
    try:
        try:
            from winsdk.windows.media.devices import MediaDevice
        except ImportError:
            from winrt.windows.media.devices import MediaDevice
        dev = MediaDevice.get_default_audio_render_id(0)
        if not dev:
            return "", ""
        if _WIN_OUT[0] == dev:
            return _WIN_OUT[0], _WIN_OUT[1]
        # Asked for separately from the id: Devices.Enumeration is its own
        # package and an install can have one half and not the other, and
        # half of this is still worth having -- the id is what the offset is
        # keyed by, and there are two more ways below to come by a name.
        name = ""
        try:
            try:
                from winsdk.windows.devices.enumeration import DeviceInformation
            except ImportError:
                from winrt.windows.devices.enumeration import DeviceInformation
            info = _run_async_call(DeviceInformation.create_from_id_async, dev)
            name = (getattr(info, "name", "") or "").strip()
        except Exception:                                   # noqa: BLE001
            name = ""
        name = name or _win_reg_name(dev) or _win_short(dev)
        _WIN_OUT = (dev, name, mono())
        return dev, name
    except Exception:                                       # noqa: BLE001
        return "", ""


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
                            "spread": float(got.get("spread", EST_RANGE * 2.0)),
                            "n": int(got.get("n", 0)), "rev": EST_REVISION}
        except Exception:
            continue
    return out


def load_settings() -> dict:
    got = _merge_ms(_upgrade_sources(_read_config()))
    if got.get("src_order"):
        got = dict(got, src_order=",".join(LS.lrclib_first(LS.carried(
            [n.strip() for n in str(got["src_order"]).split(",")]))))
    return {k: got[k] for k in DEFAULTS if k in got}


MERGE_WAS_ON = 40.0


def _merge_ms(got: dict) -> dict:
    """A settings file that still measures the merge as a fraction.

    The tolerance is now a flat number of milliseconds rather than a fraction
    of the word (see _join_flat for why). Both are small numbers and a stored
    0.14 reads perfectly well as either, so the key was renamed and this is
    what carries the old one over -- once, on the first load, after which the
    old key is dropped by load_settings like any other.

    The number cannot survive, only the intent: somebody who had it on gets it
    on at MERGE_WAS_ON, and somebody who had it off gets it off. Anyone who had
    tuned the fraction will want to look at the slider again, which is the
    honest outcome -- it is now measuring a different thing.
    """
    if not isinstance(got, dict) or "merge_ms" in got or "merge_splits" not in got:
        return got
    try:
        was = float(got.get("merge_splits") or 0.0)
    except (TypeError, ValueError):
        was = 0.0
    return dict(got, merge_ms=MERGE_WAS_ON if was > 0 else 0.0)


def _upgrade_sources(got: dict) -> dict:
    """A settings file written when the list was one of providers.

    It named things this program no longer has -- "youly", "bini" and the four
    blends -- and there is no honest way to read that order as an order of
    sources: it ranked Apple Music in six places at once, in a list where it
    now has one. So the switches are carried across, on if anything that
    spoke for the source was on, and the ORDER is taken fresh from the
    default. It is the one setting that cannot survive the change, and it is
    a dozen keystrokes to put back.

    What is deliberately NOT carried across is `src_blend` and its three
    fellows onto the new `blend_*` switches, though that looks like the
    obvious thing to do. Those defaulted to false and were written out to
    every settings file whether or not anybody had thought about them, so
    inheriting them would ship a version that brings the blends back and then
    switches them off again for everyone who ever ran the old one. The new
    keys ask a different question -- "do you want this blend at all", where
    the old ones asked "where does it rank" -- so they start from their own
    default. The old keys are dropped on the next save, by load_settings.
    """
    if not isinstance(got, dict) or "src_apple" in got:
        return got
    if not any(k.startswith("src_") for k in got):
        return got
    got = dict(got)
    for name, attr in SRC_ATTR.items():
        if attr in got:
            continue
        was = [old for old, now in WAS_SRC.items() if now == name] or [name]
        marks = [bool(got[f"src_{old}"]) for old in was if f"src_{old}" in got]
        got[attr] = any(marks) if marks else DEFAULTS[attr]
    if any(n in WAS_SRC for n in str(got.get("src_order") or "").split(",")):
        got["src_order"] = ",".join(SRC_DEFAULT)
    return got


def save_settings(values: dict, offsets: dict | None = None,
                  romaji: dict | None = None, token: str | None = None,
                  genius: dict | None = None, genius_rev: dict | None = None,
                  est: dict | None = None) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        if offsets is not None:
            values = dict(values, offsets={k: float(v) for k, v in offsets.items()
                                           if v is not None})
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


RD.TEXT, RD._smooth = TEXT, _smooth


def fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def wrap_parts(fm: QFontMetricsF, parts, sep: str, width: float,
               maxrows: int = 3) -> list:
    """Wrap a line that is a row of parts, keeping the parts apart.

    wrap_rows would do this if the parts were words, but they are not: the
    wide gaps between them are what groups the words INSIDE them, and a
    greedy wrap over `text.split()` hands every one of those gaps back as a
    single space. So the parts are wrapped rather than the words, and the
    last row is left over-long rather than elided -- a key spelled "Esc ba…"
    is worse than one drawn past the edge.
    """
    rows, cur = [], ""
    for part in parts:
        joined = f"{cur}{sep}{part}" if cur else part
        if cur and fm.horizontalAdvance(joined) > width \
                and len(rows) + 1 < maxrows:
            rows.append(cur)
            cur = part
        else:
            cur = joined
    if cur:
        rows.append(cur)
    return rows or [""]


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
MPRIS_BUS = "org.mpris.MediaPlayer2."
SPOTIFY_BUS = MPRIS_BUS + "spotify"
BRIDGE_PLAYERS = ("plasma-browser-integration",)

VIDEO_SITES = ("netflix.", "twitch.tv", "vimeo.", "disneyplus.", "hulu.",
               "primevideo.", "iplayer.", "crunchyroll.", "tiktok.",
               "dailymotion.", "ted.com")
MUSIC_SITES = ("music.youtube.", "open.spotify.", "soundcloud.", "bandcamp.",
               "music.apple.", "deezer.", "tidal.", "music.amazon.",
               "mixcloud.", "audiomack.")
VIDEO_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".mpg",
             ".mpeg", ".wmv", ".ts")
AUDIO_EXT = (".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac",
             ".wma", ".aif", ".aiff")
VIDEO_APPS = ("kodi", "plex", "jellyfin", "stremio", "mpvpaper", "obs")
SONG_SHORT = 20.0
SONG_MAX = DEFAULTS["song_max"]
STILL_FOR = 2.0
LOOK_EVERY = 0.5
SMTC_CARRY = 10.0
SMTC_LIST_FOR = 1.0
VET_AGAIN = 5.0


def looks_like_a_song(meta: dict, who: str = "", longest: float = SONG_MAX,
                      kind: str = "") -> bool:
    """Whether this reading is a song rather than something being watched.

    See the lists above for what the guess is made of and what it cannot see.
    `who` is the player's name, `longest` the ceiling in MINUTES -- the
    setting's own unit, so the number in the menu is the number compared.

    `kind` is the one field the bus does not have and the other two services
    do: Windows and macOS both carry what the player called this session,
    music or video. It is read ONE WAY ONLY. "music" is taken as a yes,
    because a player that bothered to say so is describing a song and it is
    the only positive signal here that is a statement rather than a shape.
    "video" is ignored, and that is deliberate: a browser sets it from the
    element the page is playing, and YouTube plays its music through a <video>
    like everything else -- so believing a no there would refuse the exact
    case this whole setting exists for. What decides those is the lookup (see
    SessionTransport._worth), which asks whether a music catalogue has the
    record or a provider has the words.
    """
    if not (meta.get("title") or "").strip():
        return False
    if any(app in who for app in VIDEO_APPS):
        return False
    if kind == "music":
        return True
    url = (meta.get("url") or "").lower()
    path = url.split("?", 1)[0].split("#", 1)[0]
    if path.endswith(VIDEO_EXT):
        return False
    if path.endswith(AUDIO_EXT):
        return True
    host = re.sub(r"^[a-z]+://(?:www\.)?", "", url).split("/", 1)[0]
    if host and any(site in host for site in MUSIC_SITES):
        return True
    if host and any(site in host for site in VIDEO_SITES):
        return False
    length = float(meta.get("length") or 0.0)
    return not length or SONG_SHORT <= length <= longest * 60.0


VIDEO_NOISE = {
    "official", "officiel", "oficial", "video", "videos", "videoclip",
    "audio", "lyric", "lyrics", "lyrical", "visualizer", "visualiser",
    "mv", "m/v", "pv", "hd", "hq", "4k", "8k", "uhd", "full", "clip",
    "teaser", "trailer", "premiere", "release", "out", "now", "free",
    "download", "stream", "music", "song", "track", "new", "the", "a",
    "an", "and", "with", "版", "官方",
    "youtube", "yt", "spotify", "soundcloud", "bandcamp", "vimeo", "deezer",
    "tidal", "apple", "watch", "listen", "play",
}
VERSION_ONLY = re.compile(
    r"^(?:\W*(?:radio|album|single|extended|club|original|instrumental|"
    r"acoustic|live|remaster(?:ed)?|remix|edit|mix|version|vip|bootleg|"
    r"cover|sped\s*up|slowed|reverb|\d{4})\W*)+$", re.I)
BRACKETS = re.compile(r"[\(\[\{【『「]([^\)\]\}】』」]*)[\)\]\}】』」]")
TRAILING_NOISE = re.compile(
    r"(?:\s*[-–—,]?\s*\b(?:official(?:\s+(?:music\s+)?(?:video|audio|"
    r"visuali[sz]er))?|(?:music|lyric)\s+video|lyrics?|visuali[sz]er"
    r"|mv|hd|hq|uhd|4k|8k"
    r"|youtube(?:\s+music)?|apple\s+music|soundcloud|bandcamp|vimeo"
    r"|tidal|deezer|spotify)\b\W*)+$", re.I)
TAB_COUNT = re.compile(r"^\s*\(\s*\d+\s*\)\s*")


def _version_only(text: str) -> bool:
    """Whether the far side of a dash names a version rather than a song.

    A year on its own does not count, or The Smashing Pumpkins' "1979" is a
    remaster of something by a band called The Smashing Pumpkins. It only
    counts alongside a word -- "2011 Remaster" -- which is why the test is
    for a letter and not for a match.
    """
    return bool(VERSION_ONLY.match(text or "") and re.search(r"[^\W\d_]", text))


def _packaging(text: str) -> bool:
    """Whether a bracket holds nothing but what the upload was dressed in."""
    words = re.findall(r"[^\W_]+", (text or "").lower())
    if not words:
        return False
    if len(words) <= 3 and words[-1] in ("release", "premiere", "exclusive"):
        return True
    return all(w in VIDEO_NOISE for w in words)


def song_from_video(title: str, artist: str) -> tuple[str, str]:
    """The song's name and its artist, out of what a video was called.

    Returns the pair unchanged where there is nothing to do, which is every
    player that files its music properly and most of the ones that do not.
    """
    title, artist = (title or "").strip(), (artist or "").strip()
    was = title
    if not title:
        return title, artist
    artist = re.sub(r"\s*-\s*topic$", "", artist, flags=re.I).strip()
    if len(artist) > 4:
        artist = re.sub(r"vevo$", "", artist, flags=re.I).strip()
    while True:
        cut = re.split(r"\s*(?://|\|)\s*", title)
        if len(cut) < 2 or not _packaging(cut[-1]):
            break
        title = "  ".join(cut[:-1]).strip()
    title = BRACKETS.sub(lambda m: " " if _packaging(m.group(1)) else m.group(0),
                         title)
    title = TRAILING_NOISE.sub(" ", TAB_COUNT.sub("", title))
    title = re.sub(r"(?:\s+#[^\W_]+)+$", " ", title)
    title = re.sub(r"\s*[-–—]\s*$", " ", title)
    title = re.sub(r"\s{2,}", " ", title).strip().strip("\"'“”‘’ ").strip()
    halves = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
    if len(halves) == 2 and all(h.strip() for h in halves) \
            and len(halves[0]) <= 45 and not _version_only(halves[1]):
        artist, title = halves[0].strip(), halves[1].strip()
    return title or was, artist


def song_key(title: str, artist: str) -> str:
    """An id for a player that has no Spotify track id to give.

    Twenty-two characters, like Spotify's, so everything downstream that only
    wants "some id for this song" is satisfied -- and hex rather than base62,
    so nothing takes it for a real one. Made from what is on the card, which
    is all the name-searching providers ever needed.
    """
    return hashlib.sha1(f"{title} {artist}".encode("utf-8")).hexdigest()[:22]


class NothingPlaying(RuntimeError):
    """No player here has a song to hand over.

    Not a fault, and the difference matters to whoever is holding two ways in
    at once. BackupTransport reads an exception as "that side is down" and
    stands off it for RETRY seconds; this says "that side is fine and has
    nothing for you", which is what a paused desktop -- or a track still
    waiting to be vouched for -- looks like from the outside. Standing off a
    working bus for five seconds because a video was playing on it is how a
    song that HAS been cleared waits three and a half seconds for the screen.
    """


class SessionTransport:
    """Whoever is playing, off a service that knows about every player.

    Three platforms have one of these and they are the same thing three ways:
    the session bus on Linux, the system media transport on Windows, the
    now-playing service on macOS. Each hands over a list of sessions, each
    session answers what it is playing and where it has got to, and the
    problems that come with reading them are not the platform's -- they are
    the same six problems every time.

    What is here is those six, and nothing about any particular service:

      * WHICH SESSION TO FOLLOW. Whoever is playing wins, the music player
        first among equals. One is followed until it stops, so pausing does
        not hand the window to a tab with a video paused in it, and the
        others are only looked at while what is being followed has stopped.
      * WHAT IS A SONG. None of these services says whether the thing playing
        is a song or a film -- see looks_like_a_song for the guess, and
        `vetting` for the window's better answer.
      * WHAT THE SONG IS CALLED, which off a browser is the name of a video
        rather than the name of a song. See song_from_video.
      * A CLOCK THAT STEPS. A browser publishes a position rounded to the
        second on every one of these services, and taken at face value that
        is a clock which stalls and jumps. See _tick.
      * A CLOCK THAT DOES NOT MOVE AT ALL, which is the one failure that
        looks like success. See _moving.
      * WHAT THE PLAYER LEFT OUT, filled in from a catalogue. See dress.

    A subclass supplies the service: HOME, the player never second-guessed;
    `_sessions`, who is there; `_read_one`, one reading off one of them;
    `_app_of`, what to call it; `_forget`, drop whatever was cached for it;
    and `_rank`, which of two sessions saying the same thing to believe.
    """

    LABEL = "player"
    HOME = ""
    HAS_VOLUME = False
    WHERE = "this machine"

    def __init__(self, any_player: bool = False, longest: float = SONG_MAX) -> None:
        self.any_player = bool(any_player)
        self.longest = float(longest)
        self.who = self.HOME
        self._ports: dict = {}
        self._looked = 0.0
        self.vetting = False
        self.pending: dict | None = None
        self._swept = False
        self._ok: set = set()
        self._dressed: dict = {}
        self._held: dict | None = None
        self._clocks: dict = {}
        self.trouble = ""
        self._last: dict | None = None
        self._gate = threading.RLock()

    def _sessions(self) -> list:
        """Every player the service knows about, best first."""
        raise NotImplementedError

    def _read_one(self, want_volume: bool, who=None) -> dict:
        """One reading off one session, in the shape `read` returns."""
        raise NotImplementedError

    def _forget(self, who) -> None:
        """Drop whatever was being held for this session. It has gone."""
        self._ports.pop(who, None)

    def _app_of(self, who) -> str:
        """The player's own short name: spotify, firefox, mpv."""
        return str(who or "")

    @staticmethod
    def _rank(who) -> int:
        """Which of two sessions saying the same thing to believe. Low wins."""
        return 0

    def drop(self) -> None:
        with self._gate:
            self._ports.clear()

    @property
    def name(self) -> str:
        if self.who == self.HOME:
            return self.LABEL
        return f"{self.LABEL}: {self.app}"

    @property
    def app(self) -> str:
        """Whose sound is playing, for audio_sink.

        What the platform's mixer files a playback stream under, near enough
        to match on -- see audio_sink, which needs to know whose sound to
        follow now that it is not always Spotify's.
        """
        return self._app_of(self.who or self.HOME)

    def read(self, want_volume: bool) -> dict:
        with self._gate:
            if not self.any_player:
                return self._read_one(want_volume, self.HOME)
            return self._read_any(want_volume)

    def _read_any(self, want_volume: bool) -> dict:
        """The same reading, off whichever player is worth following.

        The one being followed is asked first and every time: while it is
        playing a song there is no question to answer and nobody else is
        disturbed. Only when it has stopped, gone, or turned out to be
        playing a video is anybody else asked -- and at LOOK_EVERY, not at the
        sampler's rate.
        """
        self._held = None
        self._swept = False
        got = None
        try:
            got = self._read_one(want_volume)
        except Exception:                                   # noqa: BLE001
            self._forget(self.who)
        if got is None or got["status"] != "Playing" or not self._worth(got):
            other = self._look(want_volume)
            if other is not None:
                got = other
        elif self._rank(self.who) > 1:
            better = self._look(want_volume, outrank=True)
            if better is not None:
                got = better
        if self._held is not None:
            self.pending = self._held
        elif self._swept:
            self.pending = None
        if got is not None and self._worth(got):
            self._last = got
            return got
        if self._last is not None:
            return dict(self._last, status="Paused", at=mono())
        raise NothingPlaying(f"no player on {self.WHERE} is playing a song")

    def _worth(self, got: dict) -> bool:
        """Whether this reading is one to hand over. Two questions.

        Is it a song at all -- looks_like_a_song, and only for a player that
        is not the music player; what plays THERE was picked in a music
        player and is not second-guessed here.

        And, where somebody is vetting, has this track been cleared yet. One
        that has not is remembered in `pending` instead of being returned, so
        the window can go and look it up -- in a music catalogue, and at the
        providers -- and until it says yes the reading is not handed over, so
        a video never reaches the screen at all.
        """
        who = got.get("who")
        if who == self.HOME:
            return True
        if not looks_like_a_song(got.get("meta") or {}, self._app_of(who),
                                 self.longest, str(got.get("kind") or "")):
            return False
        if not self._moving(got):
            return False
        tid = got.get("tid")
        if not self.vetting or tid in self._ok:
            return True
        if got.get("status") == "Playing" and self._held is None and tid:
            self._held = {"tid": tid, "meta": dict(got.get("meta") or {}),
                          "who": who}
        return False

    def _tick(self, who, tid, pos: float, at: float, status: str) -> float:
        """Where the song is, from a player that only says now and then.

        Spotify answers this question with a clock. A browser answers it with
        whatever it last wrote down: Firefox's own MPRIS publishes a position
        rounded to the second, so the same 3.000 comes back sixty times and
        then becomes 4.000 all at once. Taken at face value that is a clock
        which stands still for a second and then jumps one, and the words
        above it stall and race -- which is what "laggy, and it keeps
        re-timing" is.

        So the reading is used the way CdpTransport uses the engine: as an
        ANCHOR rather than as the position. When the player's answer CHANGES,
        that is news and it is taken whole -- and it is news that arrived
        just now, so it is accurate to the poll rather than to the player's
        step. When the answer repeats, the player has not moved on, not the
        song, and the last anchor carries forward at 1x.

        Measured on the machine this was written on: Firefox's step to N
        appears while the audio is at N-0.1 or so, so anchoring on the change
        lands within about a tenth of a second where taking the number as it
        stands is out by up to half of one.

        Inert where it is not needed. Spotify's own position over the bus
        differs on every read, so every read is an anchor and this returns
        exactly what it was given -- and so does a service that stamps its
        readings itself, which is what Windows' timeline does. The carry is
        capped at STILL_FOR, which is where a player that has stopped
        answering is dropped anyway.
        """
        was = self._clocks.get(who)
        if (status != "Playing" or was is None or was["tid"] != tid
                or abs(pos - was["raw"]) > 1e-6):
            gaps = (was or {}).get("gaps") or []
            if (was is not None and status == "Playing"
                    and was["tid"] == tid and was["at"]):
                gaps = (gaps + [at - was["at"]])[-8:]
            self._clocks[who] = {"raw": pos, "at": at, "tid": tid, "gaps": gaps}
            return pos
        return pos + min(max(0.0, at - was["at"]), STILL_FOR)

    def _grain(self, who) -> float:
        """The player's resolution in seconds, or 0 where it is not known yet."""
        gaps = (self._clocks.get(who) or {}).get("gaps") or []
        return statistics.median(gaps) if len(gaps) >= 3 else 0.0

    def _moving(self, got: dict) -> bool:
        """Whether this player's clock is actually running.

        A player is not followed on its word that it is playing -- it is
        followed once its position has been SEEN to move, because a position
        that never moves is the one failure here that looks like success (see
        STILL_FOR). Judged only while it claims to be playing: a paused player
        standing still is a paused player.

        The reading is the one _tick kept: when the player last said something
        new. Self-healing, since that is rewritten every time the player does
        move, so one that stalls and comes back is followed again at once and
        nothing is remembered against it.
        """
        who = got.get("who")
        if got.get("status") != "Playing":
            return True
        was = self._clocks.get(who)
        if was is None or got["at"] - was["at"] < STILL_FOR:
            if was is not None:
                self.trouble = ""
            return True
        app = self._app_of(who) or str(who)
        self.trouble = f"{app} is playing but will not say where — not following it"
        return False

    def dress(self, tid: str, extra: dict) -> None:
        """Fill in what the player left out, for this track.

        Only the empty fields are filled -- except the cover and the name,
        which are replaced. The cover because a browser's is a video's
        thumbnail, sixteen by nine with the channel's lettering across it,
        where the album's own square is what the window is built to draw.
        The name because an upload is titled by whoever uploaded it: YouTube
        shouts the artist in capitals and writes the song's name with the
        label's tag on the end, and a catalogue spells it the way the record
        does. See LyricsView.on_card, which is what decides there is enough
        agreement to rename anything at all.
        """
        keep = {k: v for k, v in (extra or {}).items() if v not in ("", None)}
        if not keep:
            return
        if len(self._dressed) > 256:
            self._dressed.clear()
        self._dressed[tid] = keep

    def allow(self, tid: str) -> None:
        """This track is a song; stop holding it back.

        Said by the window once a provider has words for it. Kept per track
        rather than per player: the next thing in the same tab is a fresh
        question, which is the point.
        """
        if len(self._ok) > 256:
            self._ok.clear()
        self._ok.add(tid)
        if (self.pending or {}).get("tid") == tid:
            self.pending = None
        self._looked = 0.0

    def _look(self, want_volume: bool, outrank: bool = False) -> dict | None:
        """Whoever else is playing a song, or None.

        `outrank` narrows it to the players worth leaving this one FOR, which
        is how a browser hands over to the desktop's bridge mid-song. See
        _rank.
        """
        now = mono()
        if now - self._looked < LOOK_EVERY:
            return None
        self._looked = now
        self._swept = True
        try:
            names = self._sessions()
        except Exception:                                   # noqa: BLE001
            return None
        for who in names:
            if who == self.who or (outrank
                                   and self._rank(who) >= self._rank(self.who)):
                continue
            try:
                got = self._read_one(want_volume, who)
            except Exception:                               # noqa: BLE001
                self._forget(who)
                continue
            if got["status"] == "Playing" and self._worth(got):
                self.who = who
                return got
        return None

    def _worn(self, card: dict, tid) -> dict:
        """The card with whatever dress() was told about the track on it."""
        extra = self._dressed.get(tid)
        if not extra:
            return card
        out = dict(card)
        for key, value in extra.items():
            if key in ("art", "title", "artist") or not out.get(key):
                out[key] = value
        return out


class MprisTransport(SessionTransport):
    """Spotify over the session bus. Linux and the other freedesktop platforms.

    With `any_player` it is every player on the bus instead: a song playing on
    YouTube in Firefox, a file in mpv, anything that publishes MPRIS at all.

    That is a setting and not the behaviour, because the bus does not only
    carry songs. A film has a title and an artist on it exactly as a single
    does, and a window that followed whatever last made a noise would throw
    away the lyrics it is showing to say nothing about an episode of
    something. So the other players are filtered -- see looks_like_a_song --
    and Spotify is not: whatever is playing THERE was chosen in a music
    player, and a podcast picked there is still what is being listened to.

    Everything in that paragraph is SessionTransport's, and so is the rest of
    what it takes to follow a stranger's player. What is left here is the bus:
    proxies, the xesam field names, and the two things MPRIS has that the
    other platforms' services do not -- a volume, and a per-player statement
    of what it is willing to be told (see _able).
    """

    LABEL = "MPRIS"
    HOME = SPOTIFY_BUS
    WHERE = "the session bus"
    HAS_VOLUME = True

    @staticmethod
    def usable(any_player: bool = False) -> bool:
        try:
            import dbus
        except ImportError:
            return False
        try:
            bus = dbus.SessionBus()
            if not any_player:
                bus.get_object(SPOTIFY_BUS, "/org/mpris/MediaPlayer2")
                return True
            return bool(MprisTransport._on(bus))
        except Exception:
            return False

    @staticmethod
    def _rank(who: str) -> int:
        """Which of two players saying the same thing to believe.

        Spotify first: it is the one with the better clock and the one the
        rest of this program is built around, so where two things are playing
        at once -- a tab left running under a song -- it is the one to
        believe. Then the desktop's bridge, then the players themselves. See
        BRIDGE_PLAYERS for what that middle rank is and what it is worth.
        """
        if who == SPOTIFY_BUS:
            return 0
        name = who[len(MPRIS_BUS):]
        return 1 if any(name.startswith(b) for b in BRIDGE_PLAYERS) else 2

    @staticmethod
    def _on(bus) -> list[str]:
        """Every player on the bus, best first."""
        names = sorted(str(n) for n in bus.list_names()
                       if str(n).startswith(MPRIS_BUS))
        return sorted(names, key=MprisTransport._rank)

    def _sessions(self) -> list[str]:
        import dbus

        return self._on(dbus.SessionBus())

    def _app_of(self, who) -> str:
        """The player's own name, as the bus spells it: spotify, firefox, mpv."""
        return str(who or SPOTIFY_BUS)[len(MPRIS_BUS):].split(".")[0]

    def _ifaces(self, who: str = ""):
        """Cached proxies -- poll() runs 4x/second and re-resolving the bus
        object each time is pure D-Bus round-trip for no gain."""
        import dbus

        who = who or self.who
        if who not in self._ports:
            obj = dbus.SessionBus().get_object(who, "/org/mpris/MediaPlayer2")
            self._ports[who] = (dbus.Interface(obj, "org.freedesktop.DBus.Properties"),
                                dbus.Interface(obj, MPRIS))
        return (dbus, *self._ports[who])

    def _read_one(self, want_volume: bool, who=None) -> dict:
        who = who or self.who
        _, props, _ = self._ifaces(who)

        def position() -> tuple[float, float]:
            """The position, and the middle of the call that asked for it.

            A property read is a round trip over the session bus, and the
            answer describes where the song was somewhere inside it. See
            CdpTransport.read for why the middle is the honest stamp; the bus
            is slower than the debug port, so there is rather more of it here.
            """
            began = mono()
            got = float(props.Get(MPRIS, "Position")) / 1e6
            return got, began + (mono() - began) / 2

        m = props.Get(MPRIS, "Metadata")
        card, tid = self._song_of(m, who)
        pos, at = position()
        status = str(props.Get(MPRIS, "PlaybackStatus"))
        pos = self._tick(who, tid, pos, at, status)
        card = self._worn(card, tid)
        grain = self._grain(who)
        vol = None
        if want_volume:
            try:
                vol = float(props.Get(MPRIS, "Volume"))
            except Exception:
                vol = None
        again, then = self._song_of(props.Get(MPRIS, "Metadata"), who)
        if then != tid:
            card, tid = self._worn(again, then), then
            pos, at = position()
            pos = self._tick(who, tid, pos, at, status)
        return {
            "tid": tid, "status": status, "pos": pos, "at": at, "volume": vol,
            "who": who,
            "grain": grain,
            "meta": card,
        }

    @staticmethod
    def _song_of(meta, who: str) -> tuple[dict, str | None]:
        """The card as the window wants it, and the id to key it by.

        Off Spotify the card is not a song's -- it is a video's, and the
        title is the name of an upload rather than the name of a song. It is
        cleaned up here, at the edge, so that everything after this point is
        looking at the song: the search, the card on screen, the offsets, the
        id. See song_from_video for what that means and what it leaves alone.

        The id is Spotify's own where there is one. There is nothing to use
        off Spotify -- a browser's trackid counts tabs and mpv's counts the
        playlist -- so the words on the card become the id, which is the
        bargain the Windows media transport already makes. Made from the
        CLEANED words, so the same song uploaded twice with two different
        decorations is one track and not two.
        """
        meta = meta or {}
        title = str(meta.get("xesam:title", ""))
        artist = ", ".join(str(x) for x in meta.get("xesam:artist", []) or [])
        if who != SPOTIFY_BUS:
            title, artist = song_from_video(title, artist)
        card = {
            "title": title, "artist": artist,
            "album": str(meta.get("xesam:album", "")),
            "art": str(meta.get("mpris:artUrl", "")),
            "length": float(meta.get("mpris:length", 0) or 0) / 1e6,
            "url": str(meta.get("xesam:url", "")),
        }
        if who == SPOTIFY_BUS:
            return card, track_id(meta)
        return card, (song_key(title, artist) if title else None)

    CAN = {"Next": "CanGoNext", "Previous": "CanGoPrevious",
           "PlayPause": "CanPause", "seek": "CanSeek"}

    def _able(self, what: str) -> str:
        """Which player to tell, for something the followed one may not do.

        The bridge and the browser publish the SAME playback -- see
        BRIDGE_PLAYERS -- and they do not publish the same powers over it.
        Measured here on one YouTube Music tab: the bridge has the position
        and the pause and says CanGoNext false, while Firefox's own MPRIS,
        describing that same tab, will skip. Following the better clock is
        right and losing the skip key over it is not, so an instruction goes
        to whoever can carry it out rather than to whoever is being read.

        Only to a player that is on the SAME thing, matched by the address it
        is playing or by the words on its card. Nothing weaker: Spotify sits
        on the bus paused, saying it can skip, and a Next that woke it up
        would be the wrong song playing out loud.
        """
        import dbus

        flag = self.CAN.get(what)
        if not flag:
            return self.who
        def asks(who: str):
            props, _ = self._ifaces(who)[1:]
            return props
        try:
            if bool(asks(self.who).Get(MPRIS, flag)):
                return self.who
        except Exception:                                   # noqa: BLE001
            return self.who
        try:
            mine = asks(self.who).Get(MPRIS, "Metadata") or {}
            names = self._on(dbus.SessionBus())
        except Exception:                                   # noqa: BLE001
            return self.who
        for who in names:
            if who == self.who or who == SPOTIFY_BUS:
                continue
            try:
                props = asks(who)
                if not bool(props.Get(MPRIS, flag)):
                    continue
                theirs = props.Get(MPRIS, "Metadata") or {}
            except Exception:                               # noqa: BLE001
                self._ports.pop(who, None)
                continue
            if self._same_thing(mine, theirs):
                return who
        raise RuntimeError(f"{self.app} will not {what.lower()}")

    @staticmethod
    def _same_thing(mine, theirs) -> bool:
        """Whether two players are describing one piece of playback."""
        here = str((mine or {}).get("xesam:url", ""))
        there = str((theirs or {}).get("xesam:url", ""))
        if here and there:
            return here == there
        a = SL_norm(str((mine or {}).get("xesam:title", "")))
        b = SL_norm(str((theirs or {}).get("xesam:title", "")))
        return bool(a and b) and (a in b or b in a)

    def seek(self, seconds: float) -> None:
        with self._gate:
            who = self._able("seek")
            dbus, props, player = self._ifaces(who)
            trackid = props.Get(MPRIS, "Metadata")["mpris:trackid"]
            player.SetPosition(trackid, dbus.Int64(int(max(0.0, seconds) * 1e6)))
            self._clocks.pop(who, None)
            self._clocks.pop(self.who, None)

    def set_volume(self, v: float) -> None:
        with self._gate:
            dbus, props, _ = self._ifaces()
            props.Set(MPRIS, "Volume", dbus.Double(v))

    def command(self, name: str) -> None:
        with self._gate:
            _, _, player = self._ifaces(self._able(name))
            getattr(player, name)()


ENGINE_WAIT_MS = 400

BEAT_SOON_MS = 700
BEAT_WAIT_MS = 12000
ENGINE_TAU, ENGINE_SNAP = 0.30, 0.50
JS_STATE = """(async () => {
  const P = Spicetify && Spicetify.Player;
  if (!P) return null;
  const d = P.data || {};
  const it = d.item || d.track || {};
  const al = it.album || {};
  const imgs = al.images || [];
  // Two clocks, every reading. `ctl` is the control state -- what the player
  // has PUBLISHED about itself, extrapolated from its own timestamp. `engine`
  // is the playback engine's own position, which is the one the audio comes
  // out of. They agree until a track hands over to the next one; see
  // CdpTransport._pick for which is used and why.
  const ctl = (P.getProgress ? P.getProgress() : 0) / 1000;
  // Whether SPOTIFY calls this track explicit. It is the one flag anywhere in
  // this program that names the recording rather than the song: a clean edit
  // and the master it was cut from are two different tracks with two different
  // ids, and this is the id the player has open. Spotify has moved it about
  // between client versions -- a boolean on the item, a "true"/"false" string
  // in the legacy metadata bag -- so all the spellings are read and anything
  // unrecognised comes back null, which means "no answer" and never "clean".
  const md = it.metadata || {};
  let explicit = null;
  for (const v of [it.isExplicit, it.explicit, md.is_explicit, md.explicit]) {
    if (v === true || v === "true" || v === 1 || v === "1") { explicit = true; break; }
    if (v === false || v === "false" || v === 0 || v === "0") { explicit = false; break; }
  }
  let engine = null;
  try {
    const PA = Spicetify.Platform;
    // Only where playback is HERE. On a Connect device the engine is on the
    // other machine and there is nothing local to ask; the control state is
    // all there is, and is right, because the lag this exists for is between
    // a clock and a speaker that are in the same process.
    if (PA && PA.PlaybackAPI && PA.PlaybackAPI._isLocal
        && PA.PlayerAPI && PA.PlayerAPI._contextPlayer
        && PA.PlayerAPI._contextPlayer.getPositionState) {
      const got = await Promise.race([
        PA.PlayerAPI._contextPlayer.getPositionState({}),
        new Promise(r => setTimeout(() => r(null), %d))]);
      if (got && got.position != null) engine = Number(got.position) / 1000;
    }
  } catch (e) { engine = null; }
  return {
    uri: it.uri || "",
    title: it.name || "",
    artist: (it.artists || []).map(a => a && a.name).filter(Boolean).join(", "),
    album: al.name || "",
    art: (imgs[imgs.length - 1] || {}).url || (imgs[0] || {}).url || "",
    length: ((it.duration || {}).milliseconds
             || (it.duration || {}).totalMilliseconds || 0) / 1000,
    explicit: explicit,
    ctl: ctl,
    engine: engine,
    playing: P.isPlaying ? !!P.isPlaying() : false,
    volume: P.getVolume ? P.getVolume() : null};
})()""" % ENGINE_WAIT_MS


class CdpTransport:
    """Spotify over its own debug port -- the same connection the rest of the
    app already uses. Works anywhere Spotify runs, and is the only way in on
    Windows, which has no session bus to ask.

    Two threads use this at once: the sampler reading sixty times a second,
    and whoever seeks. The socket underneath was built for that (see
    spotify_dom.CDP -- every answer goes to whoever asked for it), so only
    the lazy connect needs guarding, and only the connect: holding a lock
    across a READ would put the seek back on the caller's thread to wait out,
    which is the whole thing the sampler exists to avoid.
    """

    name = "Spotify"
    HAS_VOLUME = True

    def __init__(self, port: int) -> None:
        self.port = port
        self.cdp = None
        self._dial = threading.Lock()
        self.source = "engine"
        self._eng_pos: float | None = None
        self._eng_at = 0.0
        self._eng_lock = threading.Lock()
        self._eng_show: float | None = None
        self._eng_show_at = 0.0
        self._eng_tid: str | None = None

    def usable(self) -> bool:
        try:
            self._conn()
            return True
        except Exception:
            return False

    def _conn(self):
        with self._dial:
            if self.cdp is None:
                self.cdp = connect(self.port)
            return self.cdp

    def drop(self) -> None:
        with self._dial:
            cdp, self.cdp = self.cdp, None
        try:
            if cdp:
                cdp.close()
        except Exception:
            pass

    def _smooth(self, raw: float, at: float, tid: str | None,
                playing: bool) -> float:
        """The engine's position, with the shake taken out of it.

        A clock of our own that advances at 1x and is pulled towards each
        reading, rather than the reading itself. See ENGINE_TAU for why, and
        for the two numbers.

        Re-anchored outright on a new song, on the first reading, and whenever
        the song is not playing -- a paused position is meant to stand still,
        and a clock that went on advancing towards it would drift off the end
        of a pause. A long gap between readings re-anchors by itself: alpha
        goes to 1 as the gap grows, which is exactly what should happen to a
        prediction nobody has checked in a while.
        """
        if self._eng_show is None or tid != self._eng_tid or not playing:
            self._eng_show, self._eng_show_at, self._eng_tid = raw, at, tid
            return raw
        elapsed = max(0.0, at - self._eng_show_at)
        show = self._eng_show + elapsed
        err = raw - show
        if abs(err) > ENGINE_SNAP:
            show = raw
        else:
            show += err * (1.0 - math.exp(-elapsed / ENGINE_TAU))
        self._eng_show, self._eng_show_at = show, at
        return show

    def _pick(self, engine: float | None, control: float, playing: bool,
              at: float, tid: str | None = None) -> float:
        """Which of the player's two clocks to believe.

        The engine's, whenever it is there. The control state is what Spotify
        has PUBLISHED about itself -- position as of a timestamp -- and it is
        published when a transition is decided, not when it is heard: at a
        gapless hand-off the new track is announced at position zero while the
        device is still draining the last seconds of the old one. A clock
        anchored on that is ahead of the sound for the top of every
        automatically-played track, which is what resync() has been flushing
        the pipeline to undo. The engine's position is where the audio
        actually is, so it never gets ahead of it and there is nothing to
        undo. Spicy Lyrics reads it for the same reason and has no resync.

        The control state is the backup, for two ways the engine can go:

        Gone -- not local playback, an internal renamed, the call throwing or
        timing out. `engine` arrives as None and there is nothing to decide.

        Stopped -- the nastier one, and the reason this holds a clock. Spicy
        Lyrics' own source warns that not every client refreshes
        getPositionState continuously: on some builds it only moves when the
        player emits a state change, so the same value comes back for hundreds
        of polls. That is indistinguishable from a song that has stopped, and
        believing it would freeze the words mid-line with the music playing.

        A brief stall is not a failure, though, and switching source is a step
        in the clock -- the two do not agree to the millisecond -- so it is
        worth waiting out. STALE_HOLD is exactly how long the clock goes on
        extrapolating an unchanged reading before it stops believing it, so
        using the same number here means the backup takes over at the moment
        the hold would otherwise expire and the words would stall. Not a
        coincidence to be kept in step by hand: they are the same question.

        Paused, the position is meant to stand still, so the wait restarts on
        every reading and a long pause never counts as a stall.
        """
        with self._eng_lock:
            if engine is None:
                self._eng_pos = None
                self.source = "control"
                return control
            if engine != self._eng_pos or not playing:
                self._eng_pos, self._eng_at = engine, at
            if playing and at - self._eng_at > STALE_HOLD:
                self.source = "control"
                return control
            self.source = "engine"
            return self._smooth(engine, at, tid, playing)

    def read(self, want_volume: bool) -> dict:
        """A position, and the moment it was TRUE rather than the moment it
        arrived.

        The page computes the position when it runs the script; this side only
        hears about it once the answer has come back down the socket. Stamping
        the reading on arrival says the song was there at a moment it had
        already passed, so every word is late by the return leg -- and the
        anchor is what the clock then extrapolates from, so the error does not
        wash out, it is carried until the next reading replaces it.

        Charging half the round trip is the best available guess at when the
        page actually looked, and is the same correction Spicy Lyrics makes
        inside the page for its own IPC. Idle it is worth a fifth of a
        millisecond and no one could hear it. It is not idle that matters:
        around a seek or a resume Spotify's renderer is busy and an answer
        that normally takes 0.3ms can take most of a second -- exactly the
        moments the words are being watched hardest.
        """
        began = mono()
        got = self._conn().evaluate(JS_STATE)
        at = began + (mono() - began) / 2
        if not isinstance(got, dict) or not got.get("uri"):
            raise RuntimeError("no player state")
        if not str(got.get("title") or "").strip():
            self._bare = n = getattr(self, "_bare", 0) + 1
            if n <= 3 or n % 100 == 0:
                print(f"[player state with a uri and no title: "
                      f"{got.get('uri')!r} ({n})]", file=sys.stderr, flush=True)
        vol = got.get("volume") if want_volume else None
        eng = got.get("engine")
        tid = (got.get("uri") or "").split(":")[-1] or None
        return {
            "tid": tid,
            "status": "Playing" if got.get("playing") else "Paused",
            "pos": self._pick(None if eng is None else float(eng),
                              float(got.get("ctl") or 0.0),
                              bool(got.get("playing")), at, tid),
            "at": at,
            "source": self.source,
            "volume": None if vol is None else float(vol),
            "meta": {
                "title": got.get("title") or "",
                "artist": got.get("artist") or "",
                "album": got.get("album") or "",
                "art": art_url(got.get("art") or ""),
                "length": float(got.get("length") or 0.0),
                "explicit": (None if got.get("explicit") is None
                             else bool(got["explicit"])),
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


AUMID_NAMES = {
    "308046b0af4a39cb": "firefox",
    "e7cf176e110c211b": "firefox",
    "6f193ccc56814779": "firefox",
    "d5bbdc5e5eb9b1bb": "firefox",
    "7458cb0b8b2f1a1b": "waterfox",
}
SPOTIFY_AUMID = "spotify"


class SmtcTransport(SessionTransport):
    """Windows' own now-playing service.

    Windows has had a system media transport since 8 -- the thing that draws
    the little now-playing card on the volume flyout -- and Spotify feeds it
    like every other player. It is the true equivalent of MPRIS, and unlike the
    debug port it needs nothing configured: no launch flag, no Spicetify, and it
    works with the Microsoft Store build, which cannot be given a flag at all.

    IT IS ALSO WHERE THE BROWSERS ARE. Chrome, Edge and Firefox each publish a
    session for whatever their pages are playing -- the same MediaSession card
    the page filled in -- so "follow whoever is playing" is one list here, the
    way it is one bus on Linux. Everything that decides which of them to
    follow, what is a song and what a song is called is SessionTransport's and
    is the same code the bus runs.

    Three things this service has that the bus does not. Its timeline carries
    the moment it was WRITTEN, so a position can be carried forward against a
    real timestamp instead of being inferred from when it last changed -- see
    _read_one, and _tick, which stays behind it to answer the other question.
    It says whether a session is playing music or video, which is worth
    something and not much -- see looks_like_a_song. And its covers come as
    bytes rather than as an address, so they are put on the disk and handed
    over as one.

    Two things it does not carry. There is no volume in the protocol, so the
    slider stays hidden. And there is no Spotify track id -- only the words on
    the card -- so one is made up from the title and artist, which is stable for
    a song and is all the name-searching providers need. Spicy Lyrics is asked
    by the real Spotify id, which nothing here knows, so it cannot answer for
    these sessions; the name-searching providers carry the lyrics instead.
    """

    LABEL = "Windows media"
    HOME = "spotify"
    WHERE = "Windows' media transport"

    def __init__(self, any_player: bool = False, longest: float = SONG_MAX) -> None:
        super().__init__(any_player, longest)
        self._mgr = None
        self._seen: dict = {}
        self._seen_at = 0.0
        self._art: dict = {}

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
    def usable(any_player: bool = False) -> bool:
        if os.name != "nt":
            return False
        try:
            SmtcTransport._mod()
            return True
        except Exception:                                   # noqa: BLE001
            return False

    def drop(self) -> None:
        with self._gate:
            self._ports.clear()
            self._seen, self._seen_at = {}, 0.0
            self._mgr = None

    def _forget(self, who) -> None:
        """That session would not answer. Take the list again before the next
        one is picked out of it -- it is the list that is wrong, not the
        player, and a stale entry would be chosen straight back."""
        super()._forget(who)
        self._seen_at = 0.0

    @staticmethod
    def _key(aumid: str) -> str:
        """The short name for a session: firefox, chrome, spotify, msedge."""
        got = str(aumid or "").strip()
        if not got:
            return ""
        named = AUMID_NAMES.get(got.lower())
        if named:
            return named
        got = got.split("!")[-1]
        got = re.sub(r"\.exe$", "", got, flags=re.I)
        got = got.split("_")[0]
        return (got.rsplit(".", 1)[-1] or got).lower()

    def _app_of(self, who) -> str:
        return str(who or self.HOME)

    @staticmethod
    def _rank(who) -> int:
        """Spotify first, everybody else level. No bridge here: on Windows the
        browser publishes its own session and there is nothing in front of it
        with a better view of the same page."""
        return 0 if str(who) == SmtcTransport.HOME else 2

    def _manager(self):
        with self._gate:
            if self._mgr is None:
                self._mgr = _run_async_call(self._mod().request_async)
            return self._mgr

    def _live(self) -> dict:
        """Short name -> session, for everything the transport has open.

        Keyed by the short name rather than by the session object, because a
        session object is handed out fresh on every call and nothing that
        remembers a player -- the clocks, the covers, the offsets -- could be
        keyed by one.
        """
        now = mono()
        if self._seen and now - self._seen_at < SMTC_LIST_FOR:
            return self._seen
        out: dict = {}
        for s in self._manager().get_sessions():
            try:
                key = self._key(s.source_app_user_model_id)
            except Exception:                               # noqa: BLE001
                continue
            if key and key not in out:
                out[key] = s
        self._seen, self._seen_at = out, now
        return out

    def _sessions(self) -> list:
        return sorted(self._live(), key=self._rank)

    def _session(self, who=None):
        """The session to read, or None.

        Asked for Spotify and without it there, the answer is whatever Windows
        calls the current session -- which is what this has always done, and
        is what makes the plain Spotify-only setting keep working when
        somebody is listening in a browser instead.
        """
        who = who or self.who
        live = self._live()
        got = live.get(str(who))
        if got is not None:
            return got
        if str(who) == self.HOME and not self.any_player:
            for key, s in live.items():
                if SPOTIFY_AUMID in key:
                    return s
            return self._manager().get_current_session()
        return None

    def _read_one(self, want_volume: bool, who=None) -> dict:
        who = who or self.who
        s = self._session(who)
        if s is None:
            raise RuntimeError(f"{who} is not playing anything Windows knows about")
        began = mono()
        info = _run_async_call(s.try_get_media_properties_async)
        tl, pb = s.get_timeline_properties(), s.get_playback_info()
        at = began + (mono() - began) / 2
        try:
            who = self._key(s.source_app_user_model_id) or who
        except Exception:                                   # noqa: BLE001
            pass
        title, artist = info.title or "", info.artist or ""
        if who != self.HOME:
            title, artist = song_from_video(title, artist)
        playing = int(getattr(pb.playback_status, "value",
                              pb.playback_status)) == 4
        start, end = _ticks(tl.start_time), _ticks(tl.end_time)
        raw = max(0.0, _ticks(tl.position) - start)
        tid = song_key(title, artist) if title else None
        anchored = self._tick(who, tid, raw, at, "Playing" if playing else "Paused")
        lead = _since(tl.last_updated_time) if playing else 0.0
        if 0.0 <= lead <= SMTC_CARRY:
            pos, grain = raw + lead, 0.0
        else:
            pos, grain = anchored, self._grain(who)
        card = {
            "title": title, "artist": artist,
            "album": info.album_title or "",
            "art": self._cover(tid, info),
            "length": max(0.0, end - start),
            "url": "",
        }
        return {
            "tid": tid,
            "status": "Playing" if playing else "Paused",
            "pos": max(0.0, pos), "at": at,
            "volume": None,
            "who": who,
            "grain": grain,
            "kind": _kind_of(pb),
            "meta": card,
        }

    def _cover(self, tid, info) -> str:
        """The cover as an address, having first made it into a file.

        Every other way in hands over a url and the window fetches it. This one
        hands over a stream, so it is read once per track, written into the
        same cache the fetched covers live in, and named as a file -- after
        which nothing downstream can tell the difference.
        """
        if not tid:
            return ""
        if tid in self._art:
            return self._art[tid]
        raw = b""
        try:
            raw = _thumb_bytes(info.thumbnail)
        except Exception:                                   # noqa: BLE001
            raw = b""
        url = ""
        if raw:
            try:
                ART_DIR.mkdir(parents=True, exist_ok=True)
                path = ART_DIR / f"smtc-{tid}.img"
                path.write_bytes(raw)
                url = path.as_uri()
            except Exception:                               # noqa: BLE001
                url = ""
        if len(self._art) > 256:
            self._art.clear()
        self._art[tid] = url
        return url

    def seek(self, seconds: float) -> None:
        with self._gate:
            s = self._session()
            if s is None:
                raise RuntimeError("nothing to seek")
            _run_async_call(s.try_change_playback_position_async,
                            int(max(0.0, seconds) * 1e7))
            self._clocks.pop(self.who, None)

    def set_volume(self, v: float) -> None:
        raise NotImplementedError("Windows' media transport carries no volume")

    def command(self, name: str) -> None:
        with self._gate:
            s = self._session()
            if s is None:
                return
            call = {"PlayPause": s.try_toggle_play_pause_async,
                    "Next": s.try_skip_next_async,
                    "Previous": s.try_skip_previous_async}.get(name)
            if not call:
                return
            if not _allows(s, name):
                raise RuntimeError(f"{self.app} will not {name.lower()}")
            _run_async_call(call)


def _ticks(value) -> float:
    """Seconds, out of whatever the transport put in a duration field.

    The projection hands these over as timedeltas where it can and as raw
    hundred-nanosecond counts where it cannot, and which of the two you get
    depends on the binding rather than on Windows.
    """
    if value is None:
        return 0.0
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    try:
        return float(value) / 1e7
    except (TypeError, ValueError):
        return 0.0


def _since(stamp) -> float:
    """How long ago the transport wrote that timeline down, in seconds.

    Negative or absurd where the session has not set it -- a player that
    leaves it at zero reports something in 1601 -- so the caller checks the
    answer rather than trusting it. -1.0 says there is no answer at all.
    """
    if stamp is None:
        return -1.0
    try:
        import datetime as _dt

        if hasattr(stamp, "timestamp"):
            now = _dt.datetime.now(stamp.tzinfo or _dt.timezone.utc)
            return (now - stamp).total_seconds()
        secs = float(stamp) / 1e7 - 11644473600.0
        return time.time() - secs
    except Exception:                                       # noqa: BLE001
        return -1.0


def _kind_of(playback) -> str:
    """"music", "video" or "" -- what Windows was told this session is."""
    try:
        got = playback.playback_type
        if got is None:
            return ""
        return {1: "music", 2: "video"}.get(
            int(getattr(got, "value", got)), "")
    except Exception:                                       # noqa: BLE001
        return ""


def _allows(session, what: str) -> bool:
    """Whether the session says it will take this instruction.

    Windows publishes a flag per control exactly as MPRIS does, and it means
    the same thing: a session that answers false does nothing when told,
    silently. Unlike MPRIS there is no second session describing the same
    playback to ask instead -- the browser publishes its own and that is the
    only one -- so this is a yes or a message, not a redirection.
    """
    try:
        c = session.get_playback_info().controls
        return bool({"PlayPause": c.is_pause_enabled or c.is_play_enabled,
                     "Next": c.is_next_enabled,
                     "Previous": c.is_previous_enabled}.get(what, True))
    except Exception:                                       # noqa: BLE001
        return True


def _thumb_bytes(ref) -> bytes:
    """A cover's bytes, off the stream the transport hands over.

    Written twice on purpose. The buffer is what the projection is happiest
    with and what the newer bindings support the Python buffer protocol for;
    the reader is the older shape and is there because these bindings are two
    packages with one API and they do not agree on this corner of it. Either
    failing is not a failure -- it is a song without a cover.
    """
    if ref is None:
        return b""

    box = {}
    done = threading.Event()

    def read() -> None:
        try:
            stream = _run_winrt_here(ref.open_read_async)
            size = int(getattr(stream, "size", 0) or 0)
            if not size:
                box["value"] = b""
                return
            try:
                from winsdk.windows.storage.streams import Buffer, InputStreamOptions
            except ImportError:
                from winrt.windows.storage.streams import Buffer, InputStreamOptions
            buf = Buffer(size)
            _run_winrt_here(stream.read_async, buf, size, InputStreamOptions.NONE)
            try:
                box["value"] = bytes(buf)
            except TypeError:
                try:
                    from winsdk.windows.storage.streams import DataReader
                except ImportError:
                    from winrt.windows.storage.streams import DataReader
                box["value"] = bytes(DataReader.from_buffer(buf).read_bytes(size))
        except Exception:
            box["value"] = b""
        finally:
            done.set()

    threading.Thread(target=read, name="mild-winrt-thumbnail", daemon=True).start()
    # Some WinRT projections never resolve a thumbnail read. Art is optional;
    # the lyrics window is not.
    return box.get("value", b"") if done.wait(0.75) else b""



MAC_PROCS = {
    "spotify": "Spotify", "music": "Music", "safari": "Safari",
    "chrome": "Google Chrome", "msedge": "Microsoft Edge",
    "brave": "Brave Browser", "vivaldi": "Vivaldi", "arc": "Arc",
    "chromium": "Chromium", "opera": "Opera",
}
MAC_EVERY = 0.25
MAC_APPS_FOR = 5.0
MR_DOUBT = 3.0


class MacTransport(SessionTransport):
    """Whoever is playing on a Mac.

    macOS is the platform with no single answer to this question, so this one
    holds three doors and prefers whichever is open -- see macplayer, which is
    where each of them lives and why. What the doors have in common is exactly
    what SessionTransport wants: a name, an artist, a length, a position and
    whether it is going. Everything about choosing between players, telling a
    song from a film and making a stepping clock move is the same code the
    session bus and the Windows transport run.

    The one thing that is different in kind is the COST of a reading. A bus
    property is a round trip and a Windows session is a COM call; an Apple
    Event is a process, and the sampler asks sixty times a second. So the
    Apple Events doors are read in the background at MAC_EVERY and handed over
    from a slot, which makes them a player with a coarse clock -- and a player
    with a coarse clock is what _tick has always been for. MediaRemote, where
    it is open, is read inline: it is a function call, it carries the moment
    its position was true, and it needs none of this.
    """

    LABEL = "macOS"
    HOME = "spotify"
    WHERE = "this Mac"

    def __init__(self, any_player: bool = False, longest: float = SONG_MAX) -> None:
        super().__init__(any_player, longest)
        self._mr = None
        self._mr_shut = False
        self._mr_quiet = 0.0
        self._mr_card: dict | None = None
        self._mr_at = 0.0
        self._slots: dict = {}
        self._apps: list = []
        self._apps_at = 0.0
        self._art: dict = {}

    @staticmethod
    def usable(any_player: bool = False) -> bool:
        if sys.platform != "darwin":
            return False
        if MP.MediaRemote().ok:
            return True
        return bool(MacTransport._open_apps())

    def _app_of(self, who) -> str:
        return str(who or self.HOME)

    @staticmethod
    def _rank(who) -> int:
        """Spotify first, then the other music player, then the browsers.

        The same order as everywhere else and for the same reason: what is
        playing in a music player was chosen in one.
        """
        who = str(who)
        return 0 if who == MacTransport.HOME else 1 if who == "music" else 2

    @staticmethod
    def _open_apps() -> list:
        """The players that are running, off the process table.

        `ps` rather than System Events on purpose: this is asked every few
        seconds from a program that has not yet been given permission to
        automate anything, and asking the wrong way would raise a consent
        prompt to find out whether Safari is open.
        """
        try:
            got = noconsole.run(["ps", "-Ao", "comm="], capture_output=True,
                                text=True, timeout=3.0)
        except Exception:                                   # noqa: BLE001
            return []
        lines = (got.stdout or "")
        out = []
        for key, proc in MAC_PROCS.items():
            if f"/{proc}.app/" in lines or lines.endswith(f"/{proc}") \
                    or f"/{proc}\n" in lines:
                out.append(key)
        return out

    def _running(self) -> list:
        now = mono()
        if now - self._apps_at > MAC_APPS_FOR:
            self._apps_at = now
            self._apps = self._open_apps()
        return self._apps

    def _sessions(self) -> list:
        out = []
        who = (self._card() or {}).get("who") or ""
        if who:
            out.append(who)
        if self._mr_shut or self._doubted():
            out += [w for w in self._running() if w not in out]
        return sorted(out, key=self._rank)

    def _doubted(self) -> bool:
        """Whether MediaRemote has been quiet long enough to be suspected."""
        return bool(self._mr_quiet
                    and mono() - self._mr_quiet > MR_DOUBT)

    def _card(self) -> dict | None:
        """MediaRemote's now-playing card, at most once per sampler tick.

        None where the framework is shut or said nothing. The distinction it
        cannot draw -- shut versus silent -- is drawn by _read_one, which
        notices somebody else playing while this says nobody is.
        """
        if self._mr_shut or sys.platform != "darwin":
            return None
        if self._mr is None:
            self._mr = MP.MediaRemote()
            if not self._mr.ok:
                self._mr_shut = True
                return None
        now = mono()
        if now - self._mr_at < MAC_EVERY / 4.0:
            return self._mr_card
        self._mr_at = now
        got = self._mr.read()
        if got:
            self._mr_quiet = 0.0
            got = dict(got, who=self._mr.who() or "")
        else:
            self._mr_quiet = self._mr_quiet or now
        self._mr_card = got or None
        return self._mr_card

    def _slot(self, who: str) -> dict | None:
        """The last thing that player said, and a fetch for the next one.

        Never blocks. The first ask for a player comes back empty and the
        reading after it has an answer -- which costs one sampler tick at the
        moment a new player is picked up, and nothing at all thereafter.
        """
        now = mono()
        slot = self._slots.get(who)
        if slot is None:
            slot = self._slots[who] = {"got": None, "at": 0.0, "busy": False}
        if not slot["busy"] and now - slot["at"] >= MAC_EVERY:
            slot["busy"] = True
            threading.Thread(target=self._refill, args=(who, slot),
                             daemon=True).start()
        return slot["got"]

    @staticmethod
    def _ask(who: str) -> dict | None:
        return (MP.music_app(who) if who in MP.MUSIC_APPS
                else MP.browser(who) if who in MP.BROWSERS else None)

    def _refill(self, who: str, slot: dict) -> None:       # pragma: no cover
        try:
            slot["got"] = self._ask(who)
        except Exception:                                   # noqa: BLE001
            slot["got"] = None
        finally:
            slot["at"] = mono()
            slot["busy"] = False

    def _read_one(self, want_volume: bool, who=None) -> dict:
        who = str(who or self.who)
        card = self._card()
        got = card if card and card.get("who") == who else None
        if got is None:
            got = self._slot(who)
            if got is not None and card is not None and self._doubted():
                if got.get("playing"):
                    self._mr_shut = True
        if got is None:
            raise RuntimeError(f"{who} is not playing anything that can be read")
        return self._shape(got, who)

    def _shape(self, got: dict, who: str) -> dict:
        title, artist = got.get("title") or "", got.get("artist") or ""
        if who != self.HOME and who != "music":
            title, artist = song_from_video(title, artist)
        tid = song_key(title, artist) if title else None
        at = mono()
        status = "Playing" if got.get("playing") else "Paused"
        raw = float(got.get("pos") or 0.0)
        return {
            "tid": tid, "status": status,
            "pos": max(0.0, self._tick(who, tid, raw, at, status)),
            "at": at,
            "volume": None,
            "who": who,
            "grain": self._grain(who),
            "kind": str(got.get("kind") or ""),
            "meta": {
                "title": title, "artist": artist,
                "album": got.get("album") or "",
                "art": self._cover(tid, got),
                "length": max(0.0, float(got.get("length") or 0.0)),
                "url": got.get("url") or "",
            },
        }

    def _cover(self, tid, got: dict) -> str:
        """The cover as an address. A browser gives one; MediaRemote gives
        bytes, which are put on the disk and named the same way the Windows
        transport's are."""
        if got.get("art"):
            return str(got["art"])
        raw = got.get("art_bytes") or b""
        if not tid or not raw:
            return ""
        if tid in self._art:
            return self._art[tid]
        url = ""
        try:
            ART_DIR.mkdir(parents=True, exist_ok=True)
            path = ART_DIR / f"mac-{tid}.img"
            path.write_bytes(raw)
            url = path.as_uri()
        except Exception:                                   # noqa: BLE001
            url = ""
        if len(self._art) > 256:
            self._art.clear()
        self._art[tid] = url
        return url

    def _tell(self, what: str) -> None:
        app = MP.MUSIC_APPS.get(self.who) or ""
        if not app or not what:
            raise RuntimeError(f"{self.app} cannot be controlled from here")
        if MP.run_script(f'tell application "{app}" to {what}\n"ok"') != "ok":
            raise RuntimeError(f"{self.app} would not take that")

    def seek(self, seconds: float) -> None:
        with self._gate:
            self._tell(f"set player position to {max(0.0, float(seconds)):.3f}")
            self._clocks.pop(self.who, None)
            slot = self._slots.get(self.who)
            if slot:
                slot["at"] = 0.0

    def set_volume(self, v: float) -> None:
        raise NotImplementedError("no player on a Mac publishes a volume here")

    def command(self, name: str) -> None:
        with self._gate:
            self._tell({"PlayPause": "playpause", "Next": "next track",
                        "Previous": "previous track"}.get(name, ""))



class BackupTransport:
    """Primary, with a stand-in for while the primary is down.

    SMTC answers over a COM call per read and is noticeably slower than either
    the debug port or the bus, so it should not be what drives the clock merely
    because Spotify happened to start second. This keeps asking the primary --
    at a sensible interval, not four times a second at a dead port -- and hands
    back over the moment it answers. The stand-in is what you get in between,
    rather than nothing.

    `handover` changes what counts as "down" -- see the flag itself. It is on
    when the stand-in is reading a DIFFERENT player rather than the same one
    a second way, which is what the any-media-player setting makes of it.
    """

    RETRY = 5.0
    LOOK = 0.5

    def __init__(self, primary, backup, handover: bool = False) -> None:
        self.primary, self.backup = primary, backup
        self.on_backup = False
        self._next_try = 0.0
        self.handover = handover
        self._next_look = 0.0

    @property
    def name(self) -> str:
        return self.backup.name if self.on_backup else self.primary.name

    @property
    def pending(self) -> dict | None:
        """A track one side is holding back, from whichever side has one.

        Asked of both, and normally answered by the one NOT being followed:
        holding a track back is what stops it being followed in the first
        place. See MprisTransport._worth.
        """
        return (getattr(self.backup, "pending", None)
                or getattr(self.primary, "pending", None))

    @property
    def trouble(self) -> str:
        return (getattr(self.backup, "trouble", "")
                or getattr(self.primary, "trouble", ""))

    @property
    def app(self) -> str:
        """Whose sound is playing, for audio_sink."""
        side = self.backup if self.on_backup else self.primary
        return getattr(side, "app", DEVICE_APP)

    @property
    def HAS_VOLUME(self) -> bool:
        """Whether a volume can be set right now, which side by side is not
        the same question as whether either side has one: a slider that works
        until the debug port hiccups and then stops is worse than no slider."""
        return bool(getattr(self.primary, "HAS_VOLUME", False)
                    and getattr(self.backup, "HAS_VOLUME", False))

    def allow(self, tid: str) -> None:
        for side in (self.primary, self.backup):
            if hasattr(side, "allow"):
                side.allow(tid)
        self._next_look = 0.0

    def dress(self, tid: str, extra: dict) -> None:
        for side in (self.primary, self.backup):
            if hasattr(side, "dress"):
                side.dress(tid, extra)

    def drop(self) -> None:
        (self.backup if self.on_backup else self.primary).drop()

    def _io(self, call: str, *a):
        now = mono()
        if not self.on_backup or (not self.handover and now >= self._next_try):
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
        if not self.handover:
            return self._io("read", want_volume)
        return self._follow(want_volume)

    def _follow(self, want_volume: bool):
        """Read whoever is playing; glance at the other one in the silences.

        The side already being followed is read every time, at the sampler's
        full rate, so a song playing costs exactly the one reading it always
        did. The other side is only asked while THIS one has nothing playing
        -- which is the only moment its answer could change anything -- and
        then no more often than LOOK.

        A side that raises hands over at once: that is the old stand-in rule,
        and it is the same rule, since a player that is not there is not
        playing either.
        """
        here, there = ((self.backup, self.primary) if self.on_backup
                       else (self.primary, self.backup))
        try:
            got = here.read(want_volume)
        except NothingPlaying:
            got = None
        except Exception:
            here.drop()
            got = None
        if got is not None and got.get("status") == "Playing" and not self.on_backup:
            return got
        now = mono()
        if (got is not None and got.get("status") == "Playing"
                and now < self._next_look):
            return got
        if now >= self._next_look:
            try:
                other = there.read(want_volume)
            except NothingPlaying:
                other = None
                self._next_look = now + self.LOOK
            except Exception:
                there.drop()
                other = None
                self._next_look = now + self.RETRY
            else:
                self._next_look = now + self.LOOK
            if other is not None and (got is None
                                      or other.get("status") == "Playing"):
                self.on_backup = not self.on_backup
                return other
        if got is None:
            raise RuntimeError(f"neither {self.primary.name} nor "
                               f"{self.backup.name} is answering")
        return got

    def seek(self, seconds: float) -> None:
        self._io("seek", seconds)

    def set_volume(self, v: float) -> None:
        self._io("set_volume", v)

    def command(self, name: str) -> None:
        self._io("command", name)


def session_transport():
    if os.name == "nt":
        return SmtcTransport
    if sys.platform == "darwin":
        return MacTransport
    return MprisTransport


def make_transport(port: int, prefer: str = "auto", any_player: bool = False,
                   longest: float = SONG_MAX):
    """Whichever way in is actually available here.

    The debug port leads on all three platforms, because it is quick, because
    it is the one that also brings the search, the browser and the queue with
    it, and -- the reason it leads on Linux too -- because it is the clock
    Spotify itself is drawn from.

    The session bus is not that clock. Spotify publishes a position on it that
    freezes across its own transport changes and catches up a moment later,
    which nobody notices while a track simply plays and everybody notices the
    instant one does not. Measured against Spicetify's progress over the bus,
    4x/second: a seek made in Spotify's own window reports the seek target for
    the first read after it, so the position comes back 0.5-0.6s behind the
    audio; an unpause reports the paused position, 0.3s behind. Both are right
    again within two polls, which is exactly long enough to throw a word-synced
    line and then snap it back. A seek made from HERE has neither problem: the
    clock is told where it went and does not have to ask.

    So the bus becomes the stand-in rather than the primary -- what drives the
    clock when Spotify was started without the port open, which is the case it
    was really there for. --player mpris still pins it.

    THE OTHER TWO PLATFORMS ARE THE SAME ARRANGEMENT with a different stand-in
    -- Windows' media transport, or the Mac's now-playing -- and they are the
    same arrangement because they now answer the same question. Each is a list
    of every player on the machine and each can be followed the same way, so
    `any_player` does on all three what it used to do on one: the pair follows
    whoever is actually PLAYING rather than always preferring the port (that
    is BackupTransport's `handover`), and the stand-in is every player rather
    than a second view of Spotify. Spotify still wins while Spotify is
    playing, and still over the port rather than the platform.

    Off, both ways in read Spotify and the better one leads, which is what
    each platform did before any of this.
    """
    here = session_transport()
    if prefer in ("smtc", "mpris", "macos"):
        pinned = {"smtc": SmtcTransport, "mpris": MprisTransport,
                  "macos": MacTransport}[prefer]
        return pinned(any_player, longest)
    if prefer == "cdp":
        return CdpTransport(port)
    cdp = CdpTransport(port)
    if here.usable(any_player):
        theirs = here(any_player, longest)
        return BackupTransport(cdp, theirs, handover=any_player) \
            if cdp.usable() else theirs
    return cdp


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
class Clock:
    def __init__(self, transport=None) -> None:
        self.io = transport if transport is not None else MprisTransport()
        self.lock = threading.RLock()
        self.tid: str | None = None
        self.status = "Paused"
        self._pos = 0.0
        self._raw = 0.0
        self._at = mono()
        self.meta: dict = {}
        self._pos_tid: str | None = None
        self._slew = 0.0
        self._slew_at = 0.0
        self._pinned: str | None = None
        self._resyncing = False
        self.volume: float | None = None
        self._vol_set_at = 0.0
        self.unpause_delay = UNPAUSE_DELAY
        self.unpause_fixed = False
        self._resumed_at = 0.0
        self._bias = 0.0
        self._resume_pos = 0.0
        self._resume_lead = 0.0
        self._bias_tid: str | None = None

    def _drop(self) -> None:
        self.io.drop()

    def poll(self, pin_pause: bool = True) -> None:
        """Ask the player where it is, and take the answer.

        Split in two so a window that cannot afford to block has somewhere to
        put the waiting: `read` is the round-trip to the player, `apply` is
        arithmetic. The editor runs the first on a thread of its own and the
        second under `lock` -- see editor/player.py. Everything that polls on
        the thread it draws on keeps calling this and notices no difference.
        """
        try:
            want_vol = self.wants_volume()
            got = self.io.read(want_vol)
        except Exception as e:
            self._drop()
            self.status = "Error"
            self.last_error = str(e) or e.__class__.__name__
            return
        self.apply(got, want_vol, pin_pause)

    def wants_volume(self) -> bool:
        return mono() - self._vol_set_at > 1.0

    def apply(self, got: dict, want_vol: bool = True,
              pin_pause: bool = True) -> None:
        """Take a reading. Arithmetic only -- no player is spoken to here."""
        with self.lock:
            self._apply(got, want_vol, pin_pause)

    def _apply(self, got: dict, want_vol: bool, pin_pause: bool) -> None:
        try:
            was_playing = self.status == "Playing"
            held = self._raw
            tid, status = got["tid"], got["status"]
            pos, at = got["pos"], got["at"]
            engine = str(got.get("source") or "") == "engine"
            if want_vol:
                self.volume = got.get("volume")
            self.tid, self.status = tid, status
            self.meta = got["meta"]
            resumed = (status == "Playing" and not was_playing
                       and tid == self._pos_tid)
            jumped = (not resumed and status == "Playing" and was_playing
                      and tid == self._pos_tid and self._at
                      and at - self._resumed_at > RESUME_SETTLE
                      and abs(pos - (self._raw + (at - self._at))) > SLEW_MAX)
            if not resumed and (status != "Playing" or tid != self._bias_tid
                                or jumped):
                self._bias = 0.0
            elif (not resumed and self._at and not self.unpause_fixed
                    and at - self._resumed_at <= RESUME_MEASURE):
                free = self._resume_pos + (at - self._resumed_at)
                want = self._resume_lead + (pos - free)
                read = (_within(want, _measured_cap(self.unpause_delay))
                        if abs(want) > _step_floor(got) and not engine else 0.0)
                self._bias = read + _stated_push(self.unpause_delay)
            if resumed and self.unpause_fixed:
                self._resume_lead = self.unpause_delay
                self._resume_pos = pos
                self._bias = self.unpause_delay
                self._resumed_at = at
            elif resumed:
                self._resume_lead = (pos - held) - max(0.0, at - self._at)
                self._resume_pos = pos
                read = (_within(self._resume_lead,
                                 _measured_cap(self.unpause_delay))
                        if abs(self._resume_lead) > _step_floor(got)
                        and not engine else 0.0)
                self._bias = read + _stated_push(self.unpause_delay)
                self._resumed_at = at
            stale = (not resumed and status == "Playing" and tid == self._pos_tid
                     and pos == self._raw and at - self._at < STALE_HOLD)
            if not stale:
                held_back = pos - self._bias
                if (tid == self._pos_tid and status == "Playing"
                        and was_playing and self._at
                        and at - self._resumed_at > RESUME_SETTLE):
                    shown = self._pos + (at - self._at)
                    d = held_back - shown
                    if 0.0 < abs(d) <= SLEW_MAX:
                        self._slew, self._slew_at = -d, at
                self._pos, self._at, self._pos_tid = held_back, at, tid
                self._bias_tid = tid
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

    @property
    def resumed_at(self) -> float:
        """When playback last resumed, by this clock's reckoning."""
        return self._resumed_at

    @property
    def resume_hold(self) -> float:
        """How far the words are being moved for the last unpause.

        The displacement the player made when it resumed and did not come back
        from, carried until something re-establishes where playback is. Worth
        having where it can be read: it is the one correction in here with no
        visible cause, and the difference between "the setting does nothing"
        and "the setting is doing exactly what it says and the fault is
        elsewhere" is this number.

        POSITIVE HOLDS THE WORDS BACK, which is the common case -- the player
        leaps forward on resume and the sound has not caught up. Negative
        pushes them on, for the other one: the audio was already running by
        the time the player admitted to playing, so the position it reports is
        behind its own sound and the words are late for the rest of the track.
        Nothing in a position reading can tell you that has happened, which is
        why `unpause_delay` reaches below zero and can simply be set.
        """
        return self._bias

    def position(self) -> float:
        with self.lock:
            if self.status != "Playing":
                return self._pos
            now = mono()
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
        """Send the player somewhere. `keep_hold` leaves the carried unpause
        leap alone.

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
        began = mono()
        try:
            self.io.seek(seconds)
        except Exception:
            self._drop()
            return
        with self.lock:
            self._pos = self._raw = max(0.0, seconds)
            self._at = began + (mono() - began) / 2
            if not keep_hold:
                self._bias = 0.0

    def set_volume(self, v: float) -> None:
        v = max(0.0, min(1.0, v))
        try:
            self.io.set_volume(v)
            self.volume, self._vol_set_at = v, mono()
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

    def resync_soon(self) -> None:
        """The same resync, on a thread of its own, and one at a time.

        Nothing about the correction moves: this runs resync itself, so the
        position is still re-read from the player and seek()'s arithmetic is
        the same arithmetic. Only the waiting happens somewhere the window is
        not.
        """
        if self.status != "Playing" or self._resyncing:
            return
        self._resyncing = True

        def run() -> None:
            try:
                self.resync()
            except Exception:                   # noqa: BLE001
                pass
            finally:
                self._resyncing = False

        threading.Thread(target=run, name="resync", daemon=True).start()

    def command(self, name: str) -> bool:
        """PlayPause / Next / Previous. False where the player would not.

        Not every player can do all three. A browser tab with one song in it
        has nothing to skip to, and MPRIS says so in a property rather than
        by failing -- see MprisTransport._able, which is what turns that into
        the exception caught here. Passed back rather than swallowed, because
        silence is the wrong answer to a key that did nothing.
        """
        try:
            self.io.command(name)
            return True
        except Exception:
            self._drop()
            return False


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
class Pump(QThread):
    """The thread that asks Spotify where it is, as often as a frame.

    A seek made in Spotify's OWN window is the one move this program cannot
    know about until it asks. Between asking, the clock does the only sane
    thing and carries the last reading forward at 1x -- straight through a
    jump that has already happened. So the words are wrong for as long as the
    gap between readings, and asked four times a second that is a quarter of a
    second of the wrong line, every time the scrubber is touched.

    Spicy Lyrics has no such gap: it lives inside the page, so it re-reads the
    position every frame and a seek is stale for one. The same rate is
    affordable here, but not on the thread that draws. Every reading is a
    round trip -- 0.28ms median down the debug port, measured over 200 of them
    -- and that is the quiet case; around a resume or a seek the renderer is
    busy and the same question can take most of a second. Sixty of those a
    second on the GUI thread would stall the window exactly when the song is
    doing something worth watching.

    So the waiting happens here and the arithmetic happens under the clock's
    lock, which is what that lock has always been for. The window reads an
    interpolated position between readings and never blocks on the player.
    This is the editor's `_Pump` (see editor/player.py) doing the same job for
    the same reason; the window simply never had one.

    Only reads. Transport WRITES still go from whoever wants them -- the
    socket underneath is explicitly usable from more than one thread (see
    spotify_dom.CDP), and a seek asked for here is one call, not sixty a
    second.
    """

    read = pyqtSignal()

    def __init__(self, clock, every: float = SAMPLE_MS / 1000.0,
                 pin_pause=True, parent=None) -> None:
        super().__init__(parent)
        self.clock = clock
        self.every = every
        self.pin_pause = pin_pause
        self.last_tid: str | None = None
        self._wake = threading.Event()
        self._going = True

    def stop(self) -> None:
        self._going = False
        self._wake.set()
        self.wait(2000)

    def run(self) -> None:                                  # pragma: no cover
        while self._going:
            try:
                want_vol = self.clock.wants_volume()
                got = self.clock.io.read(want_vol)
            except Exception as e:              # noqa: BLE001
                self.clock._drop()
                self.clock.status = "Error"
                self.clock.last_error = str(e) or e.__class__.__name__
                got = None
            except BaseException:
                self.clock.status = "Error"
                got = None
            if got is not None:
                pin = self.pin_pause
                self.clock.apply(got, want_vol,
                                 bool(pin() if callable(pin) else pin))
                self.last_tid = got.get("tid") or None
            if self._going:
                self.read.emit()
            self._wake.wait(self.every if self.clock.status != "Error"
                            else POLL_MS / 1000.0)
            self._wake.clear()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
HAVE_IT = 0.25


def score_local(query: str, hit: dict) -> float:
    """A cached hit on the same scale as a Genius one, so the two can be put
    in one order. Without this the cached hits simply came first, and a search
    for "in the end" answered with three songs that mention the words before
    the song called In the End."""
    score, _ = GR.score_song(query, hit.get("title") or "", hit.get("artist") or "",
                             hit.get("line") if hit.get("why") == "line" else "")
    return score + HAVE_IT


class LyricIndex:
    """Every held song's lines, so you can find one by any phrase in it.

    The songs are the ones Spicy Lyrics has been asked about from here, which
    on a machine that has been listening is well over a thousand; pulling them
    is one batched pass over the cache on disk and the result is small enough
    to keep beside it.
    """

    V = 1

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
        for h in hits:
            h["score"] = score_local(query, h)
        hits.sort(key=lambda h: (not h["here"], -h["score"]))
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

    JS = "Promise.race([Spicetify.getAudioData(%s).then(d => ({" \
         "dur: d.track.duration, tempo: d.track.tempo," \
         "beats: d.beats.map(b => [b.start, b.confidence])," \
         "sections: d.sections.map(s => s.start)," \
         "tatums: (d.tatums || []).map(t => t.start)," \
         "segs: d.segments.map(s => [s.start, s.loudness_max])," \
         "pitch: d.segments.map(s => (s.pitches || [])" \
         ".map(v => +(+v || 0).toFixed(3)))," \
         "timbre: d.segments.map(s => (s.timbre || [])" \
         ".map(v => +(+v || 0).toFixed(1)))}))," \
         "new Promise(r => setTimeout(() => r(null), %d))])"

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
        self.plo = self.phi = 0.0

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
        if louds:
            ranked = sorted(louds)
            self.plo = ranked[int(len(ranked) * 0.10)]
            self.phi = ranked[min(len(ranked) - 1, int(len(ranked) * 0.90))]
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

    def chroma(self, pos: float) -> list[float]:
        """The twelve pitch-class strengths sounding at `pos`, or nothing.

        Spotify normalises each vector so the loudest class in it reads 1.0.
        That makes the SHAPE comparable between segments but not the level --
        a near-silent segment still reports a peak of 1.0 -- so anything
        sizing itself from this has to take its scale from `loudness`.
        """
        if not self.pitch:
            return []
        i = self.seg_at(pos)
        return self.pitch[i] if 0 <= i < len(self.pitch) else []

    def voiced(self, pos: float) -> float:
        """How much of a pitch there is to answer to at `pos`, 0..1.

        Chroma arrives normalised so the loudest class always reads 1.0,
        which means an unpitched segment comes back looking exactly as
        confident as a chord -- just flatter. A snare, a hi-hat and a spoken
        consonant all report a spread of twelve middling classes, and anything
        sizing itself from the SHAPE of that is sizing itself from noise: it
        is why a beat-driven track scatters the visualizer where a sung one
        moves it. The flatness is the tell, so it is what gets measured, and
        the peakier the vector the more the shape is worth reading.
        """
        row = self.chroma(pos)
        if not row:
            return 0.0
        flat = sum(row) / len(row)
        return max(0.0, min(1.0, (0.72 - flat) / 0.34))

    def recent(self, pos: float, span: float) -> list[tuple[int, float, float]]:
        """(index, start, strength) for every beat landing in the `span`
        seconds up to `pos`, oldest first.

        `energy` gives the one beat under way, which is all a pulse on the
        window needs; anything drawing a beat as something that TRAVELS needs
        the ones still crossing, so they are handed over whole.
        """
        if not self.starts:
            return []
        lo = bisect.bisect_left(self.starts, pos - span)
        hi = bisect.bisect_right(self.starts, pos)
        return [(i, self.beats[i][0], self.beats[i][1]) for i in range(lo, hi)]

    def level(self, pos: float) -> float:
        """Loudness again, but normalised over the tenth to the ninetieth
        percentile instead of the full range.

        `loudness` spans min to max, and every track has a near-silent segment
        somewhere in a fade or a gap -- measured across a dozen tracks, that
        floor sits 43 to 61dB under the body of the song, which leaves the
        whole song crushed into the top sliver of the scale. It reads out at a
        standard deviation of 0.08: a constant, near enough, and anything
        modulated by it does not move.

        Rock suffers this worst, being compressed and wide at once: its middle
        eighty percent covers about 13% of its full range where a sparser mix
        covers 25%. Cutting the tails brings the variation back to 0.33 and,
        more to the point, brings it back EQUALLY -- the gap between genres
        closes to nothing. The tails are what differed, never the music.

        `loudness` is left as it was because the beat strengths are weighted
        with it at load, and those are read by the offset estimator.
        """
        if not self.segs or self.phi <= self.plo:
            return 0.6
        i = self.seg_at(pos)
        return max(0.0, min(1.0, (self.segs[i][1] - self.plo) / (self.phi - self.plo)))

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
EST_MAX = 0.25
EST_AGREE = 0.12


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
    """Moments a vocal entry should be audible under.

    Only the ones that follow real silence in the lyrics, for the reason given
    at ANCHOR_GAP, and only from the untouched timeline -- interlude markers are
    inserted by prepare() at times nobody sang, so they anchor to nothing.

    WORDS AS WELL AS LINES, which is most of what this now finds. The test an
    anchor has to pass is that the edge in the sound near it can only be this
    word's own entry, and a break before it is what makes that true -- the
    singer stopped, then started again. Nothing about that is a property of
    being a LINE start: a word that follows the same silence inside a line is
    the same event at a smaller scale, and one that runs straight on from the
    word before it is no good as either, because there is no entry to find --
    the spectrum simply changes and the edge belongs as much to what came
    before. Line starts alone meant the run-on ones were counted and the clean
    ones inside a line were thrown away.

    Measured over the 55 documents in this directory: 839 anchors to 1102, a
    median of 10 a song to 16, and the songs with too few to measure AT ALL
    (see MIN_ANCHORS) from 15 down to 10. Five of those become measurable, and
    the extreme is the lyric written without a gap between one line and the
    next -- "Sexion d'Assaut - Ma direction" had ONE anchor in the whole song
    and has 13.

    The word pass advances its `prev_end` over a line that has no syllable
    times of its own, and that is worth a sentence because getting it wrong
    flatters the numbers: a line-timed line still occupies the time it covers,
    and skipping it leaves the next word looking like it follows half a bar of
    silence when the singer never stopped. Counting those put this at 1228
    rather than 1102, and every one of the difference was an anchor with no
    entry under it.

    A UNION, and deliberately: the word pass carries its own `prev_end`, which
    runs to the last word's end rather than to whatever the line claims for
    its own, so a line whose words overrun it would lose a line start that the
    line-level rule was happy with. Nothing here may take an anchor away.

    Sorted, because estimate_offset splits this list down the middle to get a
    second opinion from each half of the SONG, and a set is not in any order.
    """
    out: set[float] = set()
    prev_line_end = prev_end = None
    for ln in lines:
        start = ln.get("start")
        if start is None or ln.get("dots") or not (ln.get("text") or "").strip():
            continue
        start = float(start)
        if prev_line_end is None or start - prev_line_end >= ANCHOR_GAP:
            out.add(start)
        for syl in (ln.get("syls") or ()):
            s, e = syl[0], syl[1]
            if s is None:
                continue
            s = float(s)
            if prev_end is not None and s - prev_end >= ANCHOR_GAP:
                out.add(s)
            prev_end = max(prev_end or 0.0, float(e if e is not None else s))
        end = ln.get("end")
        line_end = float(end if end is not None else start)
        prev_line_end = max(prev_line_end or 0.0, line_end)
        prev_end = max(prev_end or 0.0, line_end)
    return sorted(out)


def _est_curve(anchors: list[float], onsets: list[tuple[float, float]],
               times: list[float]) -> list[tuple[float, float]]:
    """How well these anchors sit on the sound, at every shift in range.

    The sum is over every edge near an anchor rather than the nearest one to it.
    Pairing with the nearest looks equivalent and is not: whichever side of the
    anchor an edge falls, "nearest" picks the closer, so the residuals are
    pulled toward zero and so is every estimate made from them -- the bias is
    worst exactly where the offset is small, which is the case this exists for.
    """
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
    return curve


def _est_peak(curve: list[tuple[float, float]]):
    """The winning shift and how far it stood above its nearest rival, or None.

    A rival within 2 sigma of the winner is the same peak seen from the side,
    not a competing answer, so the runner-up is looked for outside that.
    """
    best_d, best = max(curve, key=lambda r: r[1])
    if best <= 0.0:
        return None
    rival = max((v for d, v in curve if abs(d - best_d) > EST_SIGMA * 2.0),
                default=0.0)
    return best_d, round((best - rival) / best, 3)


def estimate_offset(lines: list[dict], beat: Beat) -> dict:
    """How far the lyrics sit from the sound, by correlating one against the other.

    Returns {} when there is not enough to say, which is the common answer and
    not a failure. Otherwise `delta` is how much LATER the lyrics should be
    played than they claim, `conf` is how far the winning alignment stood above
    its nearest rival, and `n` is how many anchors voted.

    `spread` is the second opinion: the same measurement made again on each
    half of the song alone, and how far the two halves' answers sit apart. It
    asks something confidence cannot, because confidence is a fact about one
    curve and this is a fact about the song -- an offset the recording really
    has is there in both halves, while a shift that won on the strength of one
    stretch of it is not. See EST_AGREE. A half that correlates with nothing at
    all reports the widest disagreement there is rather than no disagreement:
    an answer that could not be checked has not passed a check.
    """
    anchors = anchors_of(lines)
    onsets = onsets_of(beat)
    if len(anchors) < MIN_ANCHORS or not onsets:
        return {}
    times = [t for t, _ in onsets]
    whole = _est_peak(_est_curve(anchors, onsets, times))
    if whole is None:
        return {}
    best_d, conf = whole
    mid = len(anchors) // 2
    halves = [_est_peak(_est_curve(part, onsets, times))
              for part in (anchors[:mid], anchors[mid:])]
    spread = (round(abs(halves[0][0] - halves[1][0]), 3)
              if all(halves) else round(EST_RANGE * 2.0, 3))
    return {"delta": round(best_d, 3), "conf": conf, "spread": spread,
            "n": len(anchors), "rev": EST_REVISION}


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
FONT_REV = 1
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
ART_TRIES = 3
ART_GIVE_UP = 3


def art_path(url: str) -> pathlib.Path:
    return ART_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")


def art_bytes(url: str, tries: int = ART_TRIES):
    """One cover: off the disk if it has ever been fetched, off the network
    if it has not, and None if it could not be had at all.

    KEPT ON THE DISK, which is the strongest half of this. A cover that was
    fetched once is never fetched again, so a machine that drops one request
    in twenty stops mattering the second time a song comes round -- and the
    browse grid has worked that way all along. It was only the big cover
    behind the lyrics that went back to the network every play.

    It also asks as this program rather than as Python's urllib, which is
    what the grid has always done and what the panel never did. A default
    User-Agent is the first thing an interfering proxy declines.
    """
    path = art_path(url)
    try:
        raw = path.read_bytes()
        if raw:
            return raw
    except OSError:
        pass
    for n in range(max(1, tries)):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read()
        except Exception:                                # noqa: BLE001
            raw = b""
        if raw:
            try:
                ART_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            except OSError:
                pass
            return raw
        if n + 1 < tries:
            time.sleep(0.4 * (n + 1))
    return None
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
              album: md.album_title || (it.album || {}).name || "",
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
MOTION_BUDGET = 192 << 20
MOTION_SLICE_MS = 4.0
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
        """Ask for this album's animation, unless it is already being fetched.

        `seen` means IN FLIGHT, not "ever asked". It used to mean the second,
        which is why skipping a song and coming back to it left the cover
        still: the view drops its frames when the key changes, and this then
        refused to send them again, so the animation was gone until the app
        restarted.

        Asking twice is cheap. The frames are decoded to disk the first time,
        so a repeat is a handful of JPEG reads -- no network, no ffmpeg -- and
        an album with no animation is remembered as a miss and answered
        without either.
        """
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
            finally:
                with self._lock:
                    self.seen.discard(key)
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
        try:
            noconsole.run(cmd, timeout=120, check=False,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    def _work(self) -> None:
        while not self.stop:
            try:
                url = self.q.get(timeout=0.4)
            except queue.Empty:
                continue
            if self.stop:
                return
            raw = art_bytes(url)
            img = QImage()
            if raw:
                img.loadFromData(raw)
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


_people = LS.people


class Fetcher(QObject):
    ready = pyqtSignal(str, object, object)
    artists_ready = pyqtSignal(str, object)
    beat_ready = pyqtSignal(str, object)
    index_ready = pyqtSignal(object)
    index_progress = pyqtSignal(int)
    genius_ready = pyqtSignal(str, object, object)
    recents_ready = pyqtSignal(object, object)
    catsearch_ready = pyqtSignal(str, object)
    gsearch_ready = pyqtSignal(str, object)
    gmatch_ready = pyqtSignal(object, object)
    backfill_progress = pyqtSignal(int, int)
    backfill_ready = pyqtSignal(object)
    queue_ready = pyqtSignal(object)
    suggest_ready = pyqtSignal(object)
    discover_ready = pyqtSignal(object)
    ne_roman_ready = pyqtSignal(str, object)
    card_ready = pyqtSignal(str, object)
    album_ready = pyqtSignal(str, object)
    source_trouble = pyqtSignal(str, object)

    def __init__(self, port: int, split: str, threshold: float) -> None:
        super().__init__()
        self.port, self.split, self.threshold = port, split, threshold
        self.cdp = None
        self._want: str | None = None
        self.stop = False
        self._index = False
        self._index_at: int | None = None
        self._index_songs: list[dict] = []
        self._doing: tuple | None = None
        self._doing_busy = False
        self._genius: tuple | None = None
        self._ne_roman: tuple | None = None
        self._card: tuple | None = None
        self._album: str | None = None
        self._meta: dict = {}
        self._sources: set = set()
        self._order: list = []
        self._people = LS.Roster()
        self._graft = True
        self._fold = True
        self._clean = True
        self.done: str = ""
        self._recents = False
        self._queue = False
        self._stood_in: str | None = None
        self._shown: tuple = ("", 0)
        self._suggest: str | None = None
        self._discover = False
        self._search: str | None = None
        self._search_busy = False
        self._gsearch: str | None = None
        self._gsearch_busy = False
        self._gmatch: dict | None = None
        self._backfill_ids: list = []
        self._backfill_at: int | None = None
        self._ahead: list = []
        self._ahead_gen = 0
        self._ahead_thread: threading.Thread | None = None
        self._kept: dict = {}
        self._wake = threading.Event()
        self._lock = threading.Lock()

    def request(self, tid: str, meta: dict | None = None, sources=None,
                order=None, graft=None, fold=None, clean=None,
                people=None) -> None:
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
            if fold is not None:
                self._fold = bool(fold)
            if clean is not None:
                self._clean = bool(clean)
            if people is not None:
                self._people = people
        self._wake.set()

    def request_card(self, tid: str, meta: dict) -> None:
        """Ask Apple Music what this track looks like.

        For the players that cannot say. A browser hands over a video's
        thumbnail or nothing at all, and the catalogue this already asks
        about the words has the cover, the album and the rating -- see
        LS.apple_song, which answers all of it out of one request and
        remembers the answer.
        """
        with self._lock:
            self._card = (tid, dict(meta or {}))
        self._wake.set()

    def request_index(self) -> None:
        with self._lock:
            self._index = True

    def request_play(self, uri: str) -> None:
        """Play this, now. See `_act` for why it does not go in the queue."""
        self._act(("play", uri))

    def request_recents(self) -> None:
        with self._lock:
            self._recents = True

    def request_queue(self) -> None:
        with self._lock:
            self._queue = True

    def request_skip(self, uri: str, uid: str) -> None:
        """Jump down the queue. Heard the moment it lands, like a play."""
        self._act(("skip", (uri, uid)))

    def _act(self, what: tuple) -> None:
        """Make the player do something, on a thread of its own.

        THE TWO THINGS IN HERE SOMEBODY IS WAITING TO HEAR, and the reason
        they are not in the fetcher's queue with everything else: that queue
        is served one pass at a time and a pass contains the lyric walk. A
        song picked out of a search therefore started playing when ten
        providers had finished answering about the song playing BEFORE it.

        Usually that is quick. Sometimes it is not: a door that answers
        slowly holds the whole pass, so picking a song could sit in silence
        for most of that, and whether it did depended on what the loop
        happened to be doing when you clicked. LyricsPlus was the worst of
        them at eight to seventeen seconds, hits and misses alike, and it is
        gone -- but nothing here should depend on that staying true.
        Moving these to the front of the pass is not the fix, because the
        pass is usually already running: it has to leave the queue.

        Nothing waits on it and nothing it waits on -- it is one round trip
        to the page -- so it belongs on a thread, exactly as the catalogue
        search does and for the same reason. See `request_catsearch`.

        One slot for both, last one wins. A play and a skip are the same
        question about what to hear next and only the last answer is wanted;
        two picks in the same moment are one pick, the way two volumes in the
        same moment are one volume. The thread is started on demand and ends
        when the slot is empty, so an idle window is not holding one.
        """
        with self._lock:
            self._doing = what
            if self._doing_busy:
                return
            self._doing_busy = True
        threading.Thread(target=self._act_loop, daemon=True).start()

    def _act_loop(self) -> None:
        while not self.stop:
            with self._lock:
                what, self._doing = self._doing, None
                if what is None:
                    self._doing_busy = False
                    return
            kind, arg = what
            try:
                if kind == "play":
                    self._eval(f"Spicetify.Player.playUri({json.dumps(arg)})")
                else:
                    self._skip_to(*arg)
            except Exception:                            # noqa: BLE001
                pass
        with self._lock:
            self._doing_busy = False

    def request_suggest(self, artist_uri: str) -> None:
        with self._lock:
            self._suggest = artist_uri or ""

    def request_discover(self) -> None:
        with self._lock:
            self._discover = True

    def request_catsearch(self, q: str) -> None:
        """On a thread of its own, like the Genius search beside it.

        It is one round trip to the page and it used to sit at the END of the
        fetcher's loop, behind the lyric walk, the artists, the audio analysis
        -- the slowest call in the window, and the one right in front of this
        -- and then Genius and the NetEase romanisation. A query typed while a
        song was changing waited for all of it, which is why searching
        sometimes took an age and usually did not: it depended entirely on
        what the loop happened to be doing.

        Nothing waits on it and nothing it waits on, so it belongs on a thread
        rather than in a queue. A query typed while one is out replaces it;
        the window knows which query is on screen and drops an answer to any
        other.
        """
        with self._lock:
            self._search = q
            if self._search_busy:
                return
            self._search_busy = True
        threading.Thread(target=self._catsearch_loop, daemon=True).start()

    def _catsearch_loop(self) -> None:
        while not self.stop:
            with self._lock:
                q, self._search = self._search, None
                if q is None:
                    self._search_busy = False
                    return
            got = self._catsearch(q)
            if not self.stop:
                self.catsearch_ready.emit(q, got)
        with self._lock:
            self._search_busy = False

    def request_gsearch(self, q: str) -> None:
        """On a thread of its own, for the same reason as _warm: this is a
        request to Genius over the network with seconds of timeout behind it,
        and the fetcher's own loop is what answers the track that is playing.
        A query typed while one is out replaces it; see _gsearch_loop."""
        with self._lock:
            self._gsearch = q
            if self._gsearch_busy:
                return
            self._gsearch_busy = True
        threading.Thread(target=self._gsearch_loop, daemon=True).start()

    def _gsearch_loop(self) -> None:
        while not self.stop:
            with self._lock:
                q, self._gsearch = self._gsearch, None
                if q is None:
                    self._gsearch_busy = False
                    return
            got = self._genius_search(q)
            if not self.stop:
                self.gsearch_ready.emit(q, got)
        with self._lock:
            self._gsearch_busy = False

    def request_gmatch(self, hit: dict) -> None:
        with self._lock:
            self._gmatch = dict(hit or {})

    def request_ahead(self, rows, sources, order, people=None) -> None:
        """Warm the cache for tracks that are coming up. See _warm.

        Cheap where there is nothing to do: a track whose answer is already on
        disk costs the walk one stat and no round trip, so this can be handed
        the same three tracks every minute without spending anything on them.
        """
        with self._lock:
            if people is not None:
                self._people = people
            self._ahead = [(str(tid), dict(meta), set(sources), list(order))
                           for tid, meta in (rows or []) if tid]
            self._ahead_gen += 1
            if not self._ahead:
                return
        t = self._ahead_thread
        if t is None or not t.is_alive():
            t = threading.Thread(target=self._warm, name="lyrics-ahead",
                                 daemon=True)
            self._ahead_thread = t
            t.start()

    def _warm(self) -> None:
        """The fallback chain, walked for a track nobody is looking at yet.

        On a thread of its own rather than in this object's own loop, which
        would be self-defeating: that loop is what answers the track the user
        just skipped to, and holding it for somebody else's lookup is exactly
        the wait this is here to remove. Nothing below touches the page -- that
        socket belongs to the fetcher thread, and _load is the only thing
        allowed to speak on it -- so this is network and disk and no more.

        Spicy Lyrics is warmed with the rest, and that is new: it used to be
        unwarmable, because it fetched inside the Spotify page and only for
        the track that was playing. It is a provider in the chain now and the
        one the walk leads with, so a track warmed here has its copy on disk
        before the load asks for it. Nothing is said about a failure -- nobody
        is looking at this song yet, and the load that follows will make the
        same request and say so then.

        The question asked is the widest one -- `have="none"`, nothing ranked
        ahead -- because that is the form whose answer satisfies the narrower
        one the real load asks later, whatever Spicy Lyrics turns out to have
        by then. fallback() stores the question beside the answer and will not
        read back a walk that was allowed to skip providers; asking the whole
        thing here is what keeps the stored answer usable.

        A track being loaded is waited out, not taken as a reason to forget
        what is coming up. Binning the queue there is what stopped this
        working at all: the window re-requests the track it is on every
        POLL_MS_EDGE for as long as its screen is empty, which is precisely
        the stretch after a track change -- so the list built by the scan on
        that change was thrown away a moment later, and nothing rebuilt it
        until the next scan a minute on. The look-ahead was armed exactly
        when it could not run, and the song it had been asked to warm was the
        one already playing by then.
        """
        waited = 0.0
        while not self.stop:
            with self._lock:
                if not self._ahead:
                    return
                gen, rule = self._ahead_gen, self._people
                job = None if self._want is not None else self._ahead.pop(0)
            if job is None:
                if waited >= WARM_PATIENCE:
                    with self._lock:
                        if self._ahead_gen == gen:
                            self._ahead = []
                    return
                waited += WARM_LOOK
                time.sleep(WARM_LOOK)
                continue
            waited = 0.0
            tid, meta, want, order = job
            if not want or not str(meta.get("title") or "").strip():
                continue
            got = None
            try:
                got = LS.fallback(tid, meta, "none", enabled=want, order=order,
                                  people=rule,
                                  alive=lambda: not self.stop and self._want is None)
            except Exception:                            # noqa: BLE001
                pass
            with self._lock:
                if (got is None and self._want is not None
                        and self._ahead_gen == gen):
                    self._ahead.insert(0, job)

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
        beat_tid = ""
        while not self.stop:
            with self._lock:
                tid, self._want = self._want, None
                want_index, self._index = self._index, False
                gen, self._genius = self._genius, None
                ne_rom, self._ne_roman = self._ne_roman, None
                card, self._card = self._card, None
                album, self._album = self._album, None
                recents, self._recents = self._recents, False
                want_q, self._queue = self._queue, False
                sugg, self._suggest = self._suggest, None
                disc, self._discover = self._discover, False
                gmatch, self._gmatch = self._gmatch, None
                self._wake.clear()
            if tid and pending.get(tid, 0) <= mono():
                asked = tid in pending
                if tid != beat_tid:
                    early = self._audio(tid, BEAT_SOON_MS)
                    if early and not self.stop:
                        beat_tid = tid
                        self.beat_ready.emit(tid, early)
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
                    pending[tid] = mono() + step
                    with self._lock:
                        if self._want is None:
                            self._want = tid
                if self.stop:
                    return
                if body:
                    self._shown = (tid, LS.RANK.get(LS.quality(body), 0))
                self.ready.emit(tid, lines, body)
                if not self.stop:
                    self.artists_ready.emit(tid, self._artists(tid))
                if tid != beat_tid and not self.stop:
                    beat_tid = tid
                    self.beat_ready.emit(tid, self._audio(tid, BEAT_WAIT_MS))
            elif tid:
                with self._lock:
                    if self._want is None:
                        self._want = tid
            if gen and not self.stop:
                self._genius_lookup(*gen)
            if album and not self.stop:
                a_uri, a_kind = album
                js = JS_ARTIST if a_kind == "artist" else JS_ALBUM
                got = self._eval(js % json.dumps(a_uri))
                if isinstance(got, dict):
                    got["art"] = art_url(got.get("art") or "")
                self.album_ready.emit(a_uri, got)
            if card and not self.stop:
                tid_c, meta_c = card
                try:
                    got = LS.track_card(meta_c)
                except Exception:                            # noqa: BLE001
                    got = {}
                if not self.stop:
                    self.card_ready.emit(tid_c, got)
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
            if want_q and not self.stop:
                self.queue_ready.emit(self._queue_fetch())
            if sugg is not None and not self.stop:
                self.suggest_ready.emit(self._suggest_fetch(sugg))
            if disc and not self.stop:
                self.discover_ready.emit(self._discover_fetch())
            if gmatch is not None and not self.stop:
                self.gmatch_ready.emit(gmatch, self._genius_match(gmatch))
            if self._backfill_at is not None and not self.stop:
                self._backfill_batch()
            if want_index and self._index_at is None:
                self._index_at, self._index_songs = 0, []
            if self._index_at is not None:
                self._index_batch()
            self._wake.wait(POLL_WAITING if tid and tid in pending else POLL_IDLE)

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

    def _alive(self, tid: str) -> bool:
        """Whether anybody is still waiting on this track's walk.

        run() takes _want off the slot before it loads, so None there means
        "this is still the one". A different id in it is the user having
        skipped: the walk in hand is then several seconds of requests for a
        screen that has moved on, and the walk they ARE waiting on is queued
        behind it at somebody's host gate. See LS.fallback's `alive`.

        The same id is not a reason to stop -- the window re-requests the
        track it is on four times a second while the screen is empty, and
        every one of those means "still want it", not "start again".
        """
        if self.stop:
            return False
        with self._lock:
            return self._want is None or self._want == tid

    def _conn(self):
        """The page connection, made if there is not one.

        Under the lock, and only one of them: this is called from the loop,
        from the catalogue search's thread and from Genius's, so two threads
        finding it empty at the same moment would build two sockets and one
        of them would be dropped by the next failure -- taking the other
        thread's live connection with it.

        connect() ends the PROCESS when the port cannot be reached, which is
        the right answer for the command line this module also is and the
        wrong one on a worker thread: SystemExit is not an Exception, so it
        goes straight past every guard here and quietly kills whichever
        thread asked -- the fetcher's loop, usually, after which the window
        never loads another song. Turned back into the failure it is.
        """
        with self._lock:
            cdp = self.cdp
        if cdp is not None:
            return cdp
        try:
            made = connect(self.port)
        except SystemExit as exc:
            raise ConnectionError(str(exc) or "no page to connect to") from exc
        with self._lock:
            if self.cdp is None:
                self.cdp = made
                return made
            cdp = self.cdp
        made.close()
        return cdp

    def _drop(self, cdp=None) -> None:
        """Let go of the page connection. After ANY failed call, not some.

        A read that timed out did not merely fail. It left the socket halfway
        through a frame, and the bytes still to come are the tail of a reply
        nobody is waiting for any more -- so the next call reads them as its
        own, gets nonsense, and fails too. Everything after one timeout on
        that socket is garbage until somebody throws it away.

        Throwing it away used to be the lyric read's private business, and it
        was the only caller that did it. Every other read -- the artists, the
        audio analysis, the queue, the recents -- swallowed its exception and
        left the poisoned socket in place for whoever asked next. That is the
        shape of the complaint: one song's extras will not load while the one
        before it loaded fine. The lyrics themselves no longer come this way
        at all (see _spicy_body), but everything else here still does.
        """
        with self._lock:
            if cdp is not None and self.cdp is not cdp:
                return
            gone, self.cdp = self.cdp, None
        try:
            if gone:
                gone.close()
        except Exception:                                # noqa: BLE001
            pass

    def _ask(self, js):
        """One evaluation in the page, or None -- and never a bad socket left up.

        None means "no answer", which is all every caller here does with it.
        """
        cdp = None
        try:
            cdp = self._conn()
            return cdp.evaluate(js)
        except Exception:                                # noqa: BLE001
            self._drop(cdp)
            return None

    def _eval(self, js):
        return self._ask(js)

    def _index_batch(self) -> None:
        """One page of the lyrics held on disk per call, so the loop keeps
        serving lyric requests while a full index is being built.

        The songs it can offer are the ones Spicy Lyrics has been asked about
        from this machine. The API answers about one track and does not list
        its catalogue, so "every song in the cache" now means every song
        fetched here, and it fills up as things are played."""
        batch = LS.spicy_page(self._index_at, 100)
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

    def _genius_search(self, query: str):
        """Genius's own lyric search, for the words that are in no cached song.

        The index only knows songs whose lyrics are already on this machine,
        so half-remembered lines from songs never played here found nothing.
        Genius searches the words themselves and needs no token for it.
        """
        try:
            return GR.search_lyrics(query, load_token(), limit=6)
        except Exception:
            return []

    def _genius_match(self, hit: dict):
        """The Spotify track a Genius hit is about, or None if it is not clear.

        Genius names a song, Spotify holds the recording, and nothing joins the
        two but the words -- so this asks the catalogue for the name and keeps
        the track only if it really answers to it. A near miss played the wrong
        song, which is worse than saying so, hence the floor.
        """
        raw = (hit.get("title") or "").strip()
        title = re.sub(r"[\(\[\{].*?[\)\]\}]", "", raw).strip() or raw
        artist = (hit.get("artist") or "").strip()
        if GR.GENIUS_ACCOUNT.search(artist):
            artist = ""
        if not title:
            return None
        rows = self._catsearch(f"{title} {artist}".strip()) or []
        best, score = None, 0.0
        for r in rows:
            if r.get("kind") != "Track" or not r.get("uri"):
                continue
            s = 0.65 * GR.similar(title, r.get("name") or "")
            s += 0.35 * (GR.similar(artist, r.get("sub") or "") if artist else 0.35)
            if s > score:
                best, score = r, s
        if best is None or score < 0.45:
            return None
        return dict(best, score=round(score, 3))

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
        if self.cdp is None:
            return None
        return self._ask(JS_ARTISTS % json.dumps(tid))

    def _audio(self, tid: str, wait_ms: int = BEAT_WAIT_MS):
        """Audio analysis, on this same thread and socket -- it is one round trip
        and Spicetify memoises it per track inside the page.

        The one call here that waits on a promise the page has to fetch, so it
        is the one most likely to time out -- and the reason _drop matters:
        whatever it leaves behind is what the next read on that socket gets.
        `wait_ms` is how long the PAGE is given before it answers null, which
        is what keeps a slow one off the front of the lyric walk; see
        BEAT_SOON_MS.

        It dials if there is no socket yet, which it used to refuse to do --
        the analysis was an optional extra asked once the lyrics were already
        up, and paying a connect for it alone would have been the tail wagging
        the dog. Asked BEFORE the walk that reasoning inverted it, and it is
        this ask that makes the connection now that the lyrics no longer come
        through it at all. Refusing to make it is what left the FIRST track of
        a session with no visualizer until the words arrived -- measured at
        +462ms into a run, socket not yet up, the ask back in 0ms with nothing,
        and the wall dark for the whole walk. Every track after it worked,
        which is what made it look fixed.
        """
        return self._ask(Beat.JS % (json.dumps(f"spotify:track:{tid}"), wait_ms))

    def _spicy_body(self, tid: str):
        """Spicy Lyrics' copy of a track, and whether the service answered.

        None with reached=True is the whole answer: Spicy Lyrics has nothing
        for this track, and nothing is what it will have until somebody
        uploads a sync. That used to be the uncertain case -- the copy came
        out of the Spotify page's own cache, which filled in behind the user
        while the song played, so "not there" meant "not there YET" and the
        window kept asking for half a minute. The API has no such state: one
        request, one final answer, and the ask is not made twice.

        reached=False is the service being unreachable, out of requests, or
        refusing the key. The caller falls through to the rest of the chain
        exactly as it does for any other source that is down, and the window
        says which one it was.
        """
        try:
            return LS.spicy_lyrics(tid), True
        except LS.SpicyError as exc:
            self.source_trouble.emit(tid, [("spicy", str(exc))])
            return None, False

    def _load(self, tid: str, settled: bool = True):
        """The song's words, Spicy Lyrics first and then whoever else.

        Spicy Lyrics is a request like every other source's now, and its
        answer is final when it lands: what used to be here as well was a
        hold, a grace period and a watch, all of them waiting on the Spotify
        page's cache to finish filling in behind the user. There is nothing
        left to wait for -- the API has either got the sync or it has not --
        so the walk goes straight on to the chain when the answer is thin,
        and never comes back to ask again.
        """
        with self._lock:
            spicy = "spicy" in self._sources or not self._sources
            order, graft = list(self._order), self._graft
            rule = self._people
        ahead = order[:order.index("spicy")] if "spicy" in order else []
        if not spicy:
            return self._only_fallback(tid)
        body, reached = self._spicy_body(tid)
        if not reached:
            return self._only_fallback(tid)
        refused = bool(body) and rule.blocks(body)
        if refused:
            body = None
        have = LS.quality(body) if body else "none"
        shaped = None
        if body:
            shaped = self._shaped(body)
            self._interim(tid, shaped, shaped=True)
        elif self._stood_in != tid:
            self._stood_in = tid
            was = LS.stored(tid)
            self._interim(tid, None if rule.blocks(was) else was)
        liked = rule.likes(body)
        if liked:
            ahead = []
        hunt = bool(rule.pick) and not liked
        better = None
        if (have != "syllable" or ahead or hunt) and (body or settled):
            better = self._fallback(tid, have, ahead, local=body)
        if better is not None:
            merged = None
            whose = str(better.get("_alone") or better.get("_source") or "")
            if whose == "netease" and graft and _above(order, "spicy", "netease"):
                merged = LS.graft_syllables(body, better)
            body = merged if merged is not None else better
            shaped = None
        if not body:
            return [], None
        body = self._shaped(body) if shaped is None else shaped
        body = self._uncensored(tid, body)
        try:
            lines = SL.timeline(body, split=self.split, threshold=self.threshold)
        except Exception:
            return [], None
        self._duet(tid, lines)
        return lines, body

    def _shaped(self, body):
        """The document as it is drawn: unlumped, its ad-libs put back.

        The ad-lib repair is only run over a document that still has its
        ad-libs written into its lyric -- NetEase, QQ Music and Kugou, whose
        shape has nowhere else to put them, and any document that was
        line-synced until a donor lent it word timing. See LS.needs_adlibs().
        Everything else is handed on as its source wrote it, which is what
        keeps a Spicy Lyrics or amll document on this screen line for line the
        same as the one Spicy Lyrics draws itself.
        """
        with self._lock:
            fold = self._fold and LS.needs_adlibs(body)
        if fold:
            body = LS.fold_cries(body)
        body = LS.unlump(body)
        if LS.lrc_shaped(body):
            body = LS.close_holes(body)
        body = LS.quiet_marks(body)
        if fold:
            body = LS.split_asides(body)
        # Last, over whatever every step above left behind.
        return LS.no_overlap(body)

    def _uncensored(self, tid: str, body):
        """The letters a clean edit masked out, put back into the document.

        After _shaped and not before it: the walk reads the words out of the
        syllables, and until the unlump has run a syllable can be holding two
        of them. Handed back unchanged -- the very same object -- when there
        was nothing masked or nobody could fill it, because the window tells a
        new lyric from the one it is already drawing by identity, and a
        document that says exactly what the last one said should not cost a
        rebuild.

        Never on the interim: this goes to the network, and the interim's
        whole job is to reach the screen before anything does.
        """
        with self._lock:
            meta, want, on = dict(self._meta), set(self._sources), self._clean
        if not on:
            return body

        def kept(why: str) -> None:
            with self._lock:
                self._kept[tid] = why

        with self._lock:
            self._kept.pop(tid, None)
        try:
            return LS.uncensor(body, tid, meta, enabled=want, on_skip=kept)
        except Exception:                                # noqa: BLE001
            return body

    def masks_kept(self, tid: str) -> str:
        """Why this track's masks were left as they were, or ""."""
        with self._lock:
            return self._kept.get(tid, "")

    def _interim(self, tid: str, body, shaped: bool = False) -> None:
        """Show a document now, while a better one is still being looked for.

        Deliberately skips _duet: that goes to the network too, and the whole
        point of this emit is to reach the screen before any of that happens.
        The duet flags arrive with the final answer a moment later.

        `shaped` says the caller has already run _shaped over this one and is
        handing over the very object it means to keep -- see _load. The walk's
        own reports have not, and are shaped here.

        Never backwards. Every early answer for a track comes through here --
        the page's own copy, the last-known one that stands in while the walk
        runs, and each report the walk makes as a provider lands -- and each
        of those knows only what IT is worth, not what is already on screen.
        The stand-in is the one that showed: _load reads `have` off the page's
        body, so a track whose page could not be reached walks with a bar of
        "none" while a perfectly good stored document is up, and the first
        line-timed answer to land replaces it. It goes back at the end, when
        the walk's own pick lands, which is the flicker.
        """
        if not body or self.stop:
            return
        rank = LS.RANK.get(LS.quality(body), 0)
        was_tid, was_rank = self._shown
        if tid == was_tid and rank < was_rank:
            return
        if not shaped:
            body = self._shaped(body)
        try:
            lines = SL.timeline(body, split=self.split, threshold=self.threshold)
        except Exception:
            return
        if lines and not self.stop:
            self._shown = (tid, rank)
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
        """Spicy Lyrics switched off: whatever the rest of the chain has.

        Shaped like any other answer. With Spicy Lyrics off this is where
        NetEase, QQ Music and Kugou documents actually reach the screen, and
        they are the ones whose ad-libs need putting back.
        """
        body = self._fallback(tid, "none")
        if not body:
            return [], None
        body = self._uncensored(tid, self._shaped(body))
        try:
            lines = SL.timeline(body, split=self.split, threshold=self.threshold)
        except Exception:
            return [], None
        self._duet(tid, lines)
        return lines, body

    def _fallback(self, tid: str, have: str, ahead=(), local=None):
        """Ask the other sources, in order, for something better than `have`.

        Whatever comes back first and beats what is on screen goes up while
        the rest are still being asked -- see the report callback below. The
        walk is ten providers wide now and only as fast as its slowest
        server; there is no reason to hold a good answer back for it.

        A source that could not be reached is passed up to the window rather
        than swallowed. The chain is built to carry on without any one of
        them, which is right, but it means a source the user ranked first can
        be quietly skipped for the length of an outage and the only evidence
        is somebody else's name under the lyric.
        """
        with self._lock:
            meta, want = dict(self._meta), set(self._sources)
            order, rule = list(self._order), self._people
        try:
            got = LS.fallback(tid, meta, have, enabled=want, order=order,
                              ahead=ahead, local=local, people=rule,
                              alive=lambda: self._alive(tid),
                              report=lambda doc, _name: self._interim(tid, doc),
                              note=lambda bad: self.source_trouble.emit(tid, bad))
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


DASHES = "-\u2010\u2011\u2012\u2013\u2014"

JOIN_AT_MOST = 2


def _flat_group(run: list[tuple], cores: list[str], i: int, j: int,
                tol: float) -> bool:
    """Whether run[i..j] would fill the same drawn as one fragment as as many.

    The guess is taken over THIS GROUP and not over the whole word, because
    the group is what would actually be drawn: a fragment fills at a rate
    proportional to its own letters, so the only question is where the
    boundaries would land inside it.
    """
    s, e = run[i][0], run[j][1]
    span = e - s
    if span <= 0:
        return False
    total = sum(len(cores[k]) for k in range(i, j + 1))
    if not total:
        return False
    at = s
    for k in range(i, j):
        at += span * len(cores[k]) / total
        if abs(run[k][1] - at) > tol:
            return False
        if abs(run[k + 1][0] - run[k][1]) > tol:
            return False
    return True


def _join_flat(run: list[tuple], tol: float) -> list[tuple]:
    """One word's syllables, with the splits that tell us nothing taken out.

    A split earns its keep by saying something the text could not have said on
    its own. split_syllables, which is what this app does when asked to invent
    splits, puts a boundary at the point proportional to the LETTERS: three
    letters of a six-letter word get half its time. So a measured split that
    lands where that guess would have put it anyway carries no information --
    the word fills identically either way -- and all it costs is another
    fragment to lay out, wrap, cache, light and lift.

    ONE SEAM AT A TIME. This used to be all or nothing: one boundary worth
    keeping and every other split in the word was kept with it. That is wrong
    on the ordinary case rather than on an edge -- "a·ny·thing" is a flat
    split followed by a real one, and it could only ever come out "a·ny·thing"
    or "anything", never the "any·thing" it actually is.

    So a seam is judged on its own, against the two pieces it separates, and
    at most two pieces are ever joined (JOIN_AT_MOST). Folding three or more
    together in one go is a different and much larger claim -- that several
    boundaries are all redundant SIMULTANEOUSLY, under one reconstruction
    spanning the lot -- and it is a claim this test gets easier the more of
    the word it is asked about, which is the opposite of what it should do.

    Measured over the 1267 multi-syllable words in this folder, at 40ms, the
    share of seams removed when a run could grow without limit:

        2 syllables 38%   3 syllables 41%   4 syllables 53%   5+ 62%

    A word's seams do not become more redundant because the word is longer;
    what happens is that a long word's syllables carry equal letter counts
    (median imbalance 0.20 at two syllables, 0.00 at five), so the guess is
    simply the midpoint and any evenly-sung long word matches it -- the test
    removes the most where it discriminates least. Held to pairs the same
    figures are 38%, 33%, 36%, 37%, which is the rule saying the same thing
    about a word whatever its length.

    Greedy from the left, which is not always the partition with the fewest
    fragments and is always the one you can read off the word.

    `tol` is how far from the guess still counts as "nothing", IN SECONDS,
    flat -- the same number on a syllable held two seconds and one gone by in
    a tenth. It used to be a fraction of the word's own span, on the reasoning
    that a proportional error means the same thing at any length. It does not:
    a boundary is seen where it lands, in milliseconds, not in percent of the
    word it is inside. Measured over 1267 multi-syllable words in this folder,
    a tolerance of 14% of the span merged away boundaries 465ms, 302ms and
    294ms from the guess -- displacements nobody could miss, on exactly the
    held words where the hand timing is doing the most work -- while on a word
    gone by in 0.15s the same 14% was 21ms, which is stricter than anything
    anyone can see, so the splits that really do say nothing were kept.
    Running backwards at both ends is what a proportional rule buys.

    It is also what a rest inside a word is measured against: a gap between
    two syllables is real timing whatever its size, and a run is never taken
    across one.

    A split the text SPELLS OUT is never joined either, whatever the clock
    says about it. "B-A-B-Y-B-O-Y", "Mum-mum-mum-mah", "Oh-oh-oh-oh": the
    syllables are written with the dash on them, the reader can see where the
    word comes apart, and it should come apart there as it fills. Those are
    the worst possible case for the letter-count test as well -- a word cut
    into equal letters at equal times is as proportional as a split can be, so
    the rule that is meant to find splits carrying nothing would throw away
    every one of them first.

    Nor is a seam beside a piece with no letter or digit in it. The test asks
    what a splitter would have guessed, and no splitter here guesses a
    standalone full stop -- the sung rule cuts at vowel groups and hyphenation
    cuts between letters -- so one is always a person's own decision. It is
    the same worst case again and worse: "7", ".", "0" are one character each
    at equal lengths, so the guess fits perfectly and a hand-timed "7.0" was
    drawn "7." and "0". Over this folder's 53 files at 40ms the wall costs
    nothing at all -- the same 587 seams are folded with it as without -- so
    what it removes is precisely the case it was put in for.
    """
    if len(run) < 2:
        return run
    if any(y[0] is None or y[1] is None for y in run):
        return run
    cores = [y[2].strip() for y in run]
    if not sum(len(c) for c in cores):
        return run
    walls = {k for k, (a, b) in enumerate(zip(cores, cores[1:]))
             if (a and a[-1] in DASHES) or (b and b[0] in DASHES)
             or not any(c.isalnum() for c in a)
             or not any(c.isalnum() for c in b)}
    out: list[tuple] = []
    i = 0
    while i < len(run):
        j = i
        while (j + 1 < len(run) and j + 1 - i < JOIN_AT_MOST
               and j not in walls
               and _flat_group(run, cores, i, j + 1, tol)):
            j += 1
        if j == i:
            out.append(run[i])
        else:
            out.append((run[i][0], run[j][1],
                        "".join(y[2] for y in run[i:j + 1]), run[j][3]))
        i = j + 1
    return out


def merge_flat_splits(pieces: list[tuple], tol: float) -> list[tuple]:
    """Fragments with the uninformative splits taken back out.

    Word by word -- the last fragment of a word is the one NOT flagged as part
    of one, which is how everything else here finds word boundaries too. See
    _join_flat for what makes a split worth keeping.

    Returns the list it was given, unchanged and uncopied, when the setting is
    off, so nothing about the default path is different from before.
    """
    if tol <= 0 or not pieces:
        return pieces
    out: list[tuple] = []
    run: list[tuple] = []
    for y in pieces:
        run.append(y)
        if not y[3]:
            out.extend(_join_flat(run, tol))
            run = []
    if run:
        out.extend(_join_flat(run, tol))
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


def _level_of(chip, tab: str, level: str) -> str:
    """What the column should mark one piece of the document with.

    The review page's own two filters, applied to the marks in the words: the
    tab says what is being read for, and `level` which weight of it. A
    catalogue's copy carries a zero-width space between every pair of words,
    so the difference between this reading the filters and ignoring them is
    the difference between a legible screen and an underlined one.
    """
    _marks, worst = chip.shows(tab)
    said = [m.level for m in _marks] + ([worst] if worst else [])
    if level:
        said = [x for x in said if x == level]
    for want in RV.LEVELS:
        if want in said:
            return want
    return ""


def _worst_told(rep, row, tab: str, level: str) -> str:
    """The heaviest thing the page would say about this line, under its filter."""
    for want in RV.LEVELS:
        if any(lv == want for lv, *_rest in rep.told(row, tab, level)):
            return want
    return ""


def prepare(lines: list[dict], min_gap: float, merge: float = 0.0) -> list[dict]:
    """Clamp open-ended lines and insert interlude markers between the rest.

    `merge` takes the uninformative syllable splits back out of what gets
    DRAWN. It is applied to the pieces and never to `syls`, which stays the
    document's own account of itself: seeking, the redraw signature, the
    editor and everything exported still see every syllable the source timed.
    See merge_flat_splits.
    """
    for i, ln in enumerate(lines):
        if ln["end"] is None and ln["start"] is not None:
            nxt = next(
                (l["start"] for l in lines[i + 1:]
                 if l["start"] is not None and l["start"] > ln["start"]), None
            )
            ln["end"] = nxt if nxt is not None else ln["start"] + 4.0
        ln["pieces"] = merge_flat_splits(render_pieces(ln), merge)
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
                "opposite": bool(ln.get("opposite")),
                "background": False, "dots": True,
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
    follow = pyqtSignal(float, bool)
    let_go = pyqtSignal()

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
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(
                lambda s=sock: getattr(self, "_bufs", {}).pop(id(s), None))
            sock.disconnected.connect(self._maybe_let_go)
            sock.disconnected.connect(sock.deleteLater)
        self._watch()

    def _maybe_let_go(self) -> None:
        if not [s for s in self.findChildren(QObject)
                if s.__class__.__name__ == "QTcpSocket"
                and s.state() == s.SocketState.ConnectedState]:
            self.let_go.emit()

    # ---------------------------------------------------------------- jumps
    def _watch(self) -> None:
        """Tell the editor when the song MOVES, rather than waiting to be asked.

        An editor polling this every tenth of a second is exact while the song
        plays -- both clocks run at 1x from the same instant -- and wrong for
        one poll after a jump, because it is still carrying the last reading
        forward through a seek that has already happened. One poll is 120 ms,
        and a time tapped inside it lands wherever the song used to be.

        There is no need to guess: this side knows the moment it happens.

        A word is still said every SAY_EVERY even when nothing has happened.
        The editor carries the last reading forward and will only do so for
        as long as it can believe it, so a state that stops arriving is a
        clock that stops moving over there -- see SpotifyPlayer.position.
        Two lines a second down a loopback socket costs nothing next to that.
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
        now, pos = mono(), float(v.position())
        state = (v.clock.tid, v.clock.status)
        if self._was is not None:
            was_pos, was_at, was_state = self._was
            drift = pos - (was_pos + (now - was_at
                                      if was_state[1] == "Playing" else 0.0))
            moved = (abs(drift) > SAY_DRIFT or state != was_state
                     or now - was_at >= SAY_EVERY)
        else:
            moved = True
        if not moved:
            return
        self._was = (pos, now, state)
        msg = {"ok": True, "tid": v.clock.tid or "", "status": v.clock.status,
               "title": str(v.clock.meta.get("title") or ""),
               "artist": str(v.clock.meta.get("artist") or ""),
               "length": float(v.clock.meta.get("length") or 0.0),
               "pos": pos, "offset": float(v.track_offset()),
               "base": float(v.offset),
               "track": round(float(v.track_offset()) - float(v.offset), 4),
               "at": now, "live": bool(v.dropped == v.clock.tid)}
        line = (json.dumps(msg) + "\n").encode("utf-8")
        for sock in socks:
            try:
                sock.write(line)
            except Exception:
                pass

    def _read(self, sock) -> None:
        """Whole lines only, and decoded only once they are whole.

        A reply is split across TCP segments -- a 90 KB document arrives in
        three -- and a multi-byte character lands across a boundary sooner or
        later. Decoding each chunk as it comes turned that character into
        U+FFFD, the row it was in stopped being JSON, and it was dropped
        without a word: the request simply timed out. Pure ASCII lyrics never
        showed it; Dutch, Korean and Japanese ones would.
        """
        held = getattr(self, "_bufs", None)
        if held is None:
            held = self._bufs = {}
        key = id(sock)
        buf = held.get(key, b"") + bytes(sock.readAll())
        while b"\n" in buf:
            row, buf = buf.split(b"\n", 1)
            text = row.decode("utf-8", "replace").strip()
            if text:
                self._handle(sock, text)
        held[key] = buf

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
                       base=float(v.offset),
                       track=round(float(v.track_offset()) - float(v.offset), 4),
                       at=mono(),
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
        elif cmd in ("doc", "source_doc"):
            v = self.view
            mine = bool(v.dropped is not None and v.dropped == v.clock.tid)
            body = v.body
            whose = str(getattr(v, "source", "") or "")
            why = ""
            if cmd == "source_doc" and mine:
                body = getattr(v, "own_body", None)
                mine = False
                if not body:
                    why = ("this song's own lyrics are not loaded — the "
                           "editor's are")
            if not body and not why:
                why = "the player has no lyrics loaded"
            if why:
                out = {"ok": False, "why": why}
            else:
                try:
                    out = {"ok": True, "ttml": SL.render(body, "ttml"),
                           "source": whose,
                           "live": mine,
                           "from": str(getattr(v, "dropped_from", "") or ""),
                           "tid": v.clock.tid or "",
                           "title": str(v.clock.meta.get("title") or ""),
                           "artist": str(v.clock.meta.get("artist") or "")}
                except Exception as exc:              # noqa: BLE001
                    out = {"ok": False,
                           "why": f"could not render it — {type(exc).__name__}"}
        elif cmd == "follow":
            if msg.get("stop"):
                self.let_go.emit()
            else:
                try:
                    self.follow.emit(float(msg.get("pos") or 0.0),
                                     bool(msg.get("playing")))
                except (TypeError, ValueError):
                    out = {"ok": False, "why": "not a position"}
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


def _spread(marks: list, rufm, edge: float, gap: float = 2.0) -> list:
    """Push readings apart where they would sit on top of each other.

    A kana reading is narrower than the kanji under it and this never has
    anything to do. A Latin one is not: "gyeok" set over one Hangul block is
    most of the block's width, and two of them centred on neighbouring blocks
    touch. So each reading is nudged right off the one before it, and if that
    walks the last one off the end of the line the whole run is pushed back
    from the right -- which spreads the crowding over the row instead of
    piling it all up at the end.

    Each reading still starts as centred on its own characters, so where
    there is room nothing moves at all.

    It lives out here, next to nothing in particular, because that is where
    it was when the forced aligner was taken out: it sat directly under the
    Aligner's last method and went with the block, and nothing noticed until
    a song with readings was played, because ruby_rows is the only caller and
    it returns before this unless furigana is on AND the line has a reading.
    """
    if len(marks) < 2:
        return marks
    wide = [rufm.horizontalAdvance(m[1]) for m in marks]
    left = [m[0] - w / 2 for m, w in zip(marks, wide)]
    for i in range(1, len(left)):
        left[i] = max(left[i], left[i - 1] + wide[i - 1] + gap)
    over = left[-1] + wide[-1] - edge
    if over > 0:
        left[-1] -= over
        for i in range(len(left) - 2, -1, -1):
            left[i] = min(left[i], left[i + 1] - wide[i] - gap)
    return [(x + w / 2, m[1], m[2], m[3])
            for x, w, m in zip(left, wide, marks)]


# --------------------------------------------------------------------------
SEARCH_MAX = 300
EDIT_MAX = 2000


class Field:
    """One line of editable text, drawn by hand.

    This window paints its own text boxes -- a QLineEdit laid over the lyrics
    would bring its own frame, palette and font with it -- so everything a
    text box does has to be written down once: where the caret is, what is
    selected, what the clipboard keys mean, and where the last frame put the
    characters, because a box that only ever gets painted has no other way to
    answer a click.

    `at`, `fm` and `rect` are filled in by the painter on every frame; see
    LyricsView._paint_field. A click arrives between frames and is placed
    against what was last drawn, which is the geometry the hand aimed at.
    """

    def __init__(self, text: str = "", limit: int | None = None) -> None:
        self.limit = limit
        self.clipped = False
        self.text = text if limit is None else text[:limit]
        self.caret = len(self.text)
        self.sel: int | None = None
        self.at = 0.0
        self.fm: QFontMetricsF | None = None
        self.rect: QRectF | None = None

    def set_text(self, text: str) -> None:
        """Replace the lot: caret at the end, nothing selected."""
        if self.limit is not None and len(text) > self.limit:
            text, self.clipped = text[:self.limit], True
        self.text = text
        self.caret, self.sel = len(text), None

    def span(self) -> tuple[int, int]:
        """The selected range, low to high. Empty when the two ends agree."""
        a = self.caret if self.sel is None else self.sel
        return (min(a, self.caret), max(a, self.caret))

    def replace_at(self, lo: int, hi: int, text: str) -> None:
        lo = max(0, min(len(self.text), lo))
        hi = max(lo, min(len(self.text), hi))
        if self.limit is not None:
            room = self.limit - len(self.text) + (hi - lo)
            if len(text) > room:
                text, self.clipped = text[:max(0, room)], True
        self.text = self.text[:lo] + text + self.text[hi:]
        self.caret, self.sel = lo + len(text), None

    def replace(self, text: str) -> None:
        lo, hi = self.span()
        self.replace_at(lo, hi, text)

    def select_all(self) -> None:
        self.sel, self.caret = 0, len(self.text)

    def paste(self) -> bool:
        """The clipboard, as one line. False when there was nothing in it."""
        got = (QApplication.clipboard().text() or "").replace("\n", " ").strip()
        if not got:
            return False
        self.replace(got)
        return True

    def word(self, at: int, step: int) -> int:
        """One word-hop from `at`: over the spaces, then over the word they
        were against, which is what a control-arrow means everywhere else."""
        if step < 0:
            while at > 0 and self.text[at - 1].isspace():
                at -= 1
            while at > 0 and not self.text[at - 1].isspace():
                at -= 1
            return at
        n = len(self.text)
        while at < n and self.text[at].isspace():
            at += 1
        while at < n and not self.text[at].isspace():
            at += 1
        return at

    def go(self, at: int, keep: bool) -> None:
        """Put the caret here, growing the selection or dropping it."""
        if keep and self.sel is None:
            self.sel = self.caret
        elif not keep:
            self.sel = None
        self.caret = max(0, min(len(self.text), at))

    def key(self, ev) -> bool:
        """Whatever a text box does with this key press.

        False when it does nothing with it, so the caller can go on to its
        own meaning for the key -- which is how Up and Down still walk a
        results list while the caret lives in the box above it.
        """
        k, mods = ev.key(), ev.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        keep = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        lo, hi = self.span()
        if ctrl and not alt:
            if k == Qt.Key.Key_A:
                self.select_all()
                return True
            if k in (Qt.Key.Key_C, Qt.Key.Key_X):
                if hi > lo:
                    QApplication.clipboard().setText(self.text[lo:hi])
                    if k == Qt.Key.Key_X:
                        self.replace("")
                return True
            if k == Qt.Key.Key_V:
                self.paste()
                return True
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            back = k == Qt.Key.Key_Left
            if ctrl:
                at = self.word(self.caret, -1 if back else 1)
            elif hi > lo and not keep:
                at = lo if back else hi
            else:
                at = self.caret + (-1 if back else 1)
            self.go(at, keep)
            return True
        if k in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self.go(0 if k == Qt.Key.Key_Home else len(self.text), keep)
            return True
        if k in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            back = k == Qt.Key.Key_Backspace
            if hi > lo:
                self.replace("")
            elif ctrl:
                at = self.word(self.caret, -1 if back else 1)
                self.replace_at(min(at, self.caret), max(at, self.caret), "")
            elif back:
                self.replace_at(self.caret - 1, self.caret, "")
            else:
                self.replace_at(self.caret, self.caret + 1, "")
            return True
        if ev.text() and ev.text().isprintable() and (alt or not ctrl):
            self.replace(ev.text())
            return True
        return False

    def laid_out(self, at: float, fm, rect) -> None:
        """Called by the painter: x of character 0, the metrics it was drawn
        in, and the box a click has to land in to be this field's."""
        self.at, self.fm, self.rect = at, fm, rect

    def index_at(self, x: float) -> int:
        """The gap between characters nearest this x, in the geometry the
        last frame drew.

        Measured on PREFIXES, because a prefix is what the painter advances
        by -- adding up one character at a time drifts from the drawn text
        wherever the font kerns. Found by halving, though, not by walking: a
        prefix is never shorter than a shorter one, so the widths are in
        order, and walking them measured the string once per character. That
        is a click costing 50ms on a long token and eleven seconds on a
        pasted page, which is most of what made a long paste look like a
        hang. The last few are still checked one at a time, so a kerned pair
        that makes one prefix a hair shorter than the one before it cannot
        put the caret in the wrong gap.
        """
        if self.fm is None or not self.text:
            return 0
        want = x - self.at
        lo, hi = 0, len(self.text)
        while hi - lo > 4:
            mid = (lo + hi) // 2
            if self.fm.horizontalAdvance(self.text[:mid]) < want:
                lo = mid
            else:
                hi = mid
        best, near = lo, abs(want - self.fm.horizontalAdvance(self.text[:lo]))
        for i in range(lo + 1, hi + 1):
            gap = abs(want - self.fm.horizontalAdvance(self.text[:i]))
            if gap < near:
                best, near = i, gap
        return best

    def under(self, pos) -> bool:
        return self.rect is not None and self.rect.contains(pos)

    def press(self, pos, keep: bool = False) -> bool:
        """Put the caret where the click landed. False if it landed elsewhere."""
        if not self.under(pos):
            return False
        self.go(self.index_at(pos.x()), keep)
        return True

    def drag_to(self, pos) -> None:
        """Carry on a selection the mouse is dragging out."""
        if self.sel is None:
            self.sel = self.caret
        self.caret = self.index_at(pos.x())

    def pick_word(self, pos) -> bool:
        """Double click: the run of word or of blank under the pointer."""
        if not self.under(pos) or not self.text:
            return self.under(pos)
        n = len(self.text)
        at = min(self.index_at(pos.x()), n - 1)
        if self.text[at].isspace() and at > 0 and not self.text[at - 1].isspace():
            at -= 1
        blank = self.text[at].isspace()
        lo = hi = at
        while lo > 0 and self.text[lo - 1].isspace() == blank:
            lo -= 1
        while hi < n and self.text[hi].isspace() == blank:
            hi += 1
        self.sel, self.caret = lo, hi
        return True


class LyricsView(QWidget):
    art_ready = pyqtSignal(str, object)
    font_ready = pyqtSignal(str)
    device_ready = pyqtSignal(str, str)

    query = property(lambda s: s.q_field.text,
                     lambda s, v: s.q_field.set_text(v))
    bq = property(lambda s: s.bq_field.text,
                  lambda s, v: s.bq_field.set_text(v))
    edit_text = property(lambda s: s.edit_field.text,
                         lambda s, v: s.edit_field.set_text(v))

    def __init__(self, args) -> None:
        super().__init__()
        self.args = args
        self.offset = args.offset
        self.offsets: dict[str, float] = {} if args.no_persist else dict(load_offsets())
        self.est_raw: dict[str, dict] = {} if args.no_persist else load_est()
        self.est: dict = {}
        self.est_tid: str | None = None
        self.romaji_fix: dict[str, dict] = {} if args.no_persist else load_romaji()
        self.genius_fix, self.genius_rev = ({}, {}) if args.no_persist else load_genius()
        self.ne_fix: dict[str, dict] = {}
        self.genius_token = "" if args.no_persist else load_token()
        self.fetch_ahead = args.fetch_ahead
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
        self.edit_field = Field(limit=EDIT_MAX)
        self.edit_pristine = True
        self.paste_rect: QRectF | None = None
        self.judge_rect: QRectF | None = None
        self.edit_ids: list = []
        self.field_drag: Field | None = None
        self.edit_for = ""
        self.font_scale = args.font_scale
        self.blur_scale = args.blur
        self.glow_scale = args.glow
        self.word_glow = args.word_glow
        self.syll_hold = args.syll_hold
        self.show_panel = args.art
        self.art_side = args.art_side
        self.view_mode = args.view_mode
        self.show_volume = args.volume_bar
        self.motion_art = args.motion_art
        self.bg_mode = args.bg
        self.mesh_style = (args.mesh_style if args.mesh_style in MESH_STYLES
                           else DEFAULTS["mesh_style"])
        self.mesh_tint = args.mesh_tint
        self.mesh_spread = args.mesh_spread
        self.mesh_colors = int(args.mesh_colors)
        self.viz = args.viz
        self.viz_mode = args.viz_mode
        self.bg_dim = args.bg_dim
        self.bg_motion = args.bg_motion
        self.bg_fade = args.bg_fade
        self.align = args.align
        self.pop = args.pop
        self.rise = args.rise
        self.line_drop = args.line_drop
        self.pop_min = args.pop_min
        self.renderer = (args.renderer if args.renderer in RD.RENDERERS
                         else DEFAULTS["renderer"])
        self.render = RD.RENDERERS[self.renderer](self)
        self.edge = args.edge
        self.focus = args.focus
        self._focus_on = args.focus or 2
        self.line_spacing = args.line_spacing
        self.interlude = args.interlude
        self.merge_ms = args.merge_ms
        self.scroll_lead = args.scroll_lead
        self.resync = args.resync
        self.auto_time = args.auto_time
        self.any_player = bool(getattr(args, "any_player", False))
        self.song_max = float(getattr(args, "song_max", SONG_MAX))
        self.vet_at: dict[str, float] = {}
        self.vet_body: tuple | None = None
        self._said_player = ""
        self.card_asked: set[str] = set()
        self.card_len: dict[str, float] = {}
        self.vet_meta: dict[str, dict] = {}
        self.vet_sent: set[str] = set()
        self.card_done: set[str] = set()
        self.beat_scale = args.beat
        self.roman = args.roman
        self.genius_auto = args.genius_auto
        self.furigana = args.furigana
        for name, attr in SRC_ATTR.items():
            setattr(self, attr, getattr(args, attr))
        for _blend, attr in BLEND_KEY.items():
            setattr(self, attr, getattr(args, attr))
        self.ne_graft = args.ne_graft
        self.fold_adlibs = args.fold_adlibs
        self.review_marks = bool(getattr(args, "review_marks", False))
        self.uncensor = args.uncensor
        self.people_skip = LS.person_list(getattr(args, "people_skip", ""))
        self.people_pick = LS.person_list(getattr(args, "people_pick", ""))
        self.spin = args.spin
        self.zero_g = args.zero_g
        self.clouds = args.clouds
        self.float_up = args.float_up
        self.off_by_one = args.off_by_one
        self.searching = args.searching
        self.troll_skew = 0
        self.troll_at: tuple | None = None
        self.search_until = 0.0
        self.search_next = 0.0
        self.search_goal = 0.0
        self.search_speed = 0.0
        self.search_at = 0.0
        self.show_now_card = args.browse_now
        self.browse_art = args.browse_art
        self.drift: dict = {}
        self.cloudy: dict = {}
        self.drift_at = 0.0
        self.source = ""
        self.dropped_from = ""
        self.own_body = None
        self.reloading: str | None = None
        self._drawn: list = []
        self.genius_tried: set[str] = set()
        self.beat = Beat()
        self._sung = parse_color(args.sung_color, TEXT)
        self.duet_color = args.duet_color
        self._duet_rgb = (None if self.duet_color in DUET_MODES
                          else parse_color(self.duet_color, None))
        self.lines: list[dict] = []
        self.japanese = False
        self.raw: list[dict] = []
        self.body = None
        self.synced = False
        self.dropped: str | None = None
        self.dropped_art: str | None = None
        self.status_text = "Connecting…"
        self.track_at = mono()
        self.clock = Clock(self.make_player())
        self.clock.unpause_delay = float(args.unpause_delay)
        self.clock.unpause_fixed = (args.unpause_mode == UNPAUSE_MODES[1])
        self.scroll = 0.0
        self.scroll_target = 0.0
        self.content_h = 0.0
        self.user_scroll_until = 0.0
        self.browse = 0.0
        self.focus_idx = -1
        self.activation: dict[int, float] = {}
        self.line_rects: list[tuple[int, float, float, float, float]] = []
        self.hover_idx = -1
        self.bar_rect: QRectF | None = None
        self.drag_frac: float | None = None
        self.vol_rect: QRectF | None = None
        self.vol_drag: float | None = None
        self.vol_want: float | None = None
        self._vol_sent_at = 0.0
        self.hot: list = []
        # The credit block's links, which are the lyric column's rather than
        # the chrome's and so cannot live in `hot`: the column is painted
        # first and `hot` is emptied after it, for the header. Filled by
        # renderers._paint_credits, read by credit_at.
        self.credit_hot: list = []
        self.show_help = False
        self.help_tab = 0
        self.help_tab_rects: list = []
        self.show_info = False
        self.info_rects: list = []
        self.show_search = False
        self.q_field = Field(limit=SEARCH_MAX)
        self.hits: list[dict] = []
        self.hit_idx = 0
        self.hit_top = 0
        self.search_rects: list[tuple] = []
        self.local_hits: list[dict] = []
        self._trouble_said: dict[str, float] = {}
        self._follow_at = 0.0
        self._follow_cmd_at = 0.0
        self._follow_seek_at = 0.0
        self._follow_want = 0.0
        self._follow_tries = 0
        self._follow_said = False
        self._follow_from: float | None = None
        self._follow_gave_at = 0.0
        self._muted_from: float | None = None
        self.gq_hits: list[dict] = []
        self.gq_query = ""
        self.gq_asked = ""
        self.gq_busy = False
        self.gq_matching: dict | None = None
        self.index = LyricIndex()
        self.index_n = 0
        self.indexing = False
        self.show_menu = False
        self.view = "lyrics"
        self.review = None
        self.review_at: tuple | None = None
        self.review_body = None
        self.review_rule = "auto"
        self.review_tab = "all"
        self.review_level = ""
        self.review_tab_rects: list[tuple] = []
        self.review_level_rects: list[tuple] = []
        self.review_open: set = set()
        self.review_fold_rects: list[tuple] = []
        self.review_also_rects: list[tuple] = []
        self.review_keep_rects: list[tuple] = []
        self.review_kept: list[tuple] = []
        self._rev_spans = None
        self.review_lang = ""
        self.review_all = False
        self.review_sel = 0
        self.review_scroll = self.review_scroll_target = 0.0
        self.review_rects: list[tuple] = []
        self._rev_plan = self._rev_key = None
        self._rev_top = 120.0
        self.browse_tab = "home"
        self.browse_scroll = 0.0
        self.browse_scroll_target = 0.0
        self.browse_rects: list[tuple] = []
        self.browse_hover: tuple | None = None
        self.shelves: list[dict] = []
        self.bq_field = Field(limit=SEARCH_MAX)
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
        self.last_move = mono()
        self.skip_at = 0.0
        self.quit_requested = False
        self.mouse_pos = QPointF(-1, -1)
        self._cursor = Qt.CursorShape.ArrowCursor
        self._idle_frames = 0
        self._scene_old: QPixmap | None = None
        self._scene_from = 0.0
        self._scene_viz: bool | None = None
        self._viz_mix = 0.0
        self._viz_last: QPixmap | None = None

        self.layout_cache: dict = {}
        self._font_memo: dict = {}
        self._ink_gen = 0
        self.pix_cache: OrderedDict = OrderedDict()
        self.glow_cache: OrderedDict = OrderedDict()
        self._pix_bytes = self._glow_bytes = 0
        self._pix_left = PIX_PER_FRAME
        self._new_left = NEW_PER_FRAME
        self.art_bg: QPixmap | None = None
        self.art_luma = 0.40
        self.art_full: QPixmap | None = None
        self.art_url = ""
        self._art_fails: dict = {}
        self.art_gen = 0
        self.motion = MotionArt()
        self.motion_frames: list = []
        self._motion_todo: list = []
        self._motion_cap = MOTION_PX
        self._motion_for = ""
        self.motion_key = ""
        self.motion_at = 0.0
        self.motion_fps = float(MOTION_FPS)
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
        self._viz_ch = [0.0] * 12
        self._viz_tone = 1.0
        self._viz_lvl = 0.0
        self._viz_kick = 0.0
        self._viz_at = 0.0
        self._viz_key = None
        self._viz_pm: QPixmap | None = None
        self._viz_was = 0.0
        _disk = {} if args.no_persist else load_settings()
        self.device = self.device_name = ""
        self.player = ""
        try:
            self.dev_offsets = {str(k): float(v) for k, v in
                                (_disk.get("offsets_device") or {}).items()}
        except Exception:                                # noqa: BLE001
            self.dev_offsets = {}
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
        self.device_ready.connect(self.on_device)

        self.art_cache = ArtCache()
        self.art_cache.loaded.connect(self.on_thumb)
        self.motion.ready.connect(self.on_motion)

        self.fetcher = Fetcher(args.port, args.split, args.split_threshold)
        self.fetcher.ready.connect(self.on_fetched)
        self.fetcher.card_ready.connect(self.on_card)
        self.fetcher.beat_ready.connect(self.on_beat)
        self.fetcher.index_ready.connect(self.on_index)
        self.fetcher.index_progress.connect(self.on_index_progress)
        self.fetcher.genius_ready.connect(self.on_genius)
        self.fetcher.ne_roman_ready.connect(self.on_ne_roman)
        self.fetcher.album_ready.connect(self.on_album)
        self.fetcher.source_trouble.connect(self.on_source_trouble)
        self.fetcher.artists_ready.connect(self.on_artists)
        self.fetcher.recents_ready.connect(self.on_recents)
        self.fetcher.catsearch_ready.connect(self.on_catsearch)
        self.fetcher.gsearch_ready.connect(self.on_gsearch)
        self.fetcher.gmatch_ready.connect(self.on_gmatch)
        self.fetcher.backfill_ready.connect(self.on_backfill)
        self.fetcher.backfill_progress.connect(self.on_backfill_progress)
        self.fetcher.queue_ready.connect(self.on_queue)
        self.fetcher.suggest_ready.connect(self.on_suggest)
        self.fetcher.discover_ready.connect(self.on_discover)
        self.fetch_thread = threading.Thread(target=self.fetcher.run, daemon=True)
        self.fetch_thread.start()
        threading.Thread(target=self._watch_device, name="lyrics-output",
                         daemon=True).start()
        threading.Thread(target=LS.sweep, daemon=True).start()

        self._ahead_at = 0.0

        self.link = LiveLink(self)
        self.link.clear.connect(self.drop_live_lyric)
        self.link.seek.connect(lambda p: self.clock.seek(p))
        self.link.follow.connect(self.follow_editor)
        self.link.let_go.connect(self.unfollow_editor)

        self._seen_tid: str | None = None
        self.clock.poll(self.resync)
        self._read_tid = self.clock.tid or None
        self.pump = Pump(self.clock, pin_pause=lambda: self.resync, parent=self)
        self.pump.read.connect(self.on_reading)
        self.pump.start()

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(POLL_MS)
        self.gq_timer = QTimer(self)
        self.gq_timer.setSingleShot(True)
        self.gq_timer.setInterval(GENIUS_TYPED_MS)
        self.gq_timer.timeout.connect(self.ask_genius)
        self.fps_cap = args.fps_cap
        self.eff_hz = 60.0
        self._watched_screen = None
        self._screen_hooked = False
        self.frame_timer = QTimer(self)
        self.frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.frame_timer.setSingleShot(True)
        self.frame_timer.timeout.connect(self._frame)
        self._frame_due = mono()
        self.retune_frames()
        self.poll()

    def retune_frames(self, *_) -> None:
        """Run the frame timer at an integer divisor of the current refresh.

        A fixed 16ms matches no real panel. On a 60Hz output it asks for 62.5
        frames the compositor will only present 60 of, and the leftover shows
        up in a word sweep as a stutter every few seconds; on a 240Hz one it
        leaves most of the panel unused anyway. Dividing the refresh down keeps
        every step the same length, which is what actually reads as smooth.

        Only the rate is settled here. The interval is not, because a whole
        number of milliseconds cannot express it -- see _frame.
        """
        scr = self.screen() or QApplication.primaryScreen()
        hz = scr.refreshRate() if scr is not None else 0.0
        if hz <= 0:
            hz = 60.0
        n = max(1, math.ceil(hz / max(1.0, self.fps_cap)))
        self.eff_hz = hz / n
        if not self.frame_timer.isActive():
            self._frame_due = mono()
            self.frame_timer.start(0)

    def showing(self) -> bool:
        """Whether the frames being painted actually reach a screen.

        A wall-clock timer has no idea the window is gone: minimised, this went
        on painting the whole window sixty times a second and handing every one
        of them to the compositor. isExposed is the accurate answer under
        Wayland -- the compositor stops exposing a surface it is not showing --
        and the widget flags cover the platforms and the startup moment where
        it is not yet.

        Being covered by another window is NOT this. No compositor tells a
        client it has been occluded, so a buried window still reports itself
        exposed and still pays in full; only the damage itself could be made
        cheaper there.
        """
        if self.isHidden() or self.isMinimized():
            return False
        wh = self.windowHandle()
        return wh is None or wh.isExposed()

    def _frame(self) -> None:
        """One animation step, then re-arm for the next one.

        Single-shot and re-armed against a deadline carried in float seconds,
        rather than left running at a fixed interval, because setInterval takes
        whole milliseconds and no whole number of them divides a real refresh.
        59.913Hz wants 16.691ms; the 17 it used to be rounded to runs 1.09Hz
        slow, which lands as one duplicated frame every 0.92s -- exactly the
        stutter the divisor in retune_frames is there to remove, put back by
        the last line of it. Carrying the deadline forward keeps the long-run
        rate exact and leaves only sub-millisecond dither, which is well inside
        one refresh and so never reaches the eye.
        """
        try:
            self.tick()
        finally:
            period = 1.0 / max(1.0, self.eff_hz
                               if self.showing() else FRAME_IDLE_HZ)
            self._frame_due += period
            delay = self._frame_due - mono()
            if delay < -period:
                self._frame_due = mono() + period
                delay = period
            self.frame_timer.start(max(0, round(delay * 1000)))

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
        self.drop_pixmaps()
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
        return self._lyric_face(background)[0]

    def lyric_fm(self, background: bool = False) -> QFontMetricsF:
        """Metrics for the lyric font, built once per face rather than per ask.

        `word_lifts` wants the line height on every active line on every frame,
        and building a QFontMetricsF means building a QFont to ask it about.
        """
        return self._lyric_face(background)[2]

    def lyric_font_key(self) -> str:
        """The lyric font as a string, for the drawn-line cache's key.

        The font is in that key by name rather than by emptying the cache when
        the family changes -- see line_pixmap -- which means serialising a
        QFont twice per visible line per frame. It is the same string every
        time until somebody changes the type, so it is worked out with the
        face and kept with it.
        """
        return self._lyric_face(False)[1]

    def _lyric_face(self, background: bool):
        """(font, its name, its metrics) for the lyric type, memoised.

        Everything the face is built from is in the key -- the family, the
        size, the pinned weight -- so this cannot hand back a stale one and
        nothing has to remember to empty it. What it saves is the building: a
        QFont and a QFontMetricsF were being constructed forty thousand times
        over a forty-second sweep, all but a handful of them identical.

        The same object goes back to every caller. Nothing here mutates a font
        it was given -- the painters copy it, the metrics copy it, and the one
        place that wanted a bigger one takes a copy first.
        """
        key = (self.family, int(self.lyric_px() * (0.66 if background else 1.0)),
               self.font_weight)
        got = self._font_memo.get(key)
        if got is None:
            f = self._weigh(QFont(self.family, key[1]),
                            self._weight(QFont.Weight.Black))
            if len(self._font_memo) > 16:
                self._font_memo.clear()
            got = self._font_memo[key] = (f, f.toString(), QFontMetricsF(f))
        return got

    def ui_font(self, px: float, weight=QFont.Weight.DemiBold) -> QFont:
        f = QFont(self.family, max(8, int(px)))
        return self._weigh(f, self._weight(weight)
                           if weight >= QFont.Weight.Black else weight)

    def on_reading(self) -> None:
        """A reading has landed. Almost always there is nothing to do.

        The clock has already taken it -- that happened on the sampler's
        thread, under the lock -- and the words are drawn from the clock, so
        sixty of these a second would otherwise be sixty chances to do no
        work. The exception is a track change, which the rest of the window
        does have to hear about: the lyric on screen belongs to a song that
        has stopped playing, and waiting up to a quarter second for the next
        bookkeeping tick to notice is a quarter second of the wrong song's
        words. That was what the old 60ms poll near the end of a track was
        buying, and this buys it everywhere instead -- a track change reaches
        the window as fast as the clock sees one.
        """
        tid = self.pump.last_tid
        if tid != self._read_tid:
            self._read_tid = tid
            self.poll()

    def player_do(self, name: str) -> None:
        """Tell the player, and say so where it will not.

        Every one of these works on Spotify, so nothing ever had to report
        that a key had done nothing. Off Spotify they are not all there: a
        single video in a tab has nothing to skip to, and the desktop's
        bridge does not offer next and previous even where the page does --
        which is why the instruction is sent to whoever can take it before
        anybody gives up on it. See MprisTransport._able.
        """
        if self.clock.command(name):
            return
        self.toast({"Next": "this player cannot skip",
                    "Previous": "this player cannot go back",
                    "PlayPause": "this player cannot be paused from here"}
                   .get(name, "the player would not take that"))

    def make_player(self) -> object:
        """The way in to the player, as the settings have it.

        `vetting` is set here rather than inside make_transport because it is
        a statement about the CALLER and not about the bus: this window can go
        and look a track up before showing it, so the transport is entitled to
        hold an unknown one back and wait to be told. Everything else that
        builds a transport -- the editor -- cannot do the looking,
        and gets the plain guess.
        """
        io = make_transport(self.args.port, getattr(self.args, "player", "auto"),
                            self.any_player, self.song_max)
        for part in (io, getattr(io, "backup", None), getattr(io, "primary", None)):
            if isinstance(part, SessionTransport):
                part.vetting = self.any_player
                part.longest = self.song_max
        return io

    def follow_players(self, say: bool = True) -> None:
        """Take up the setting's new answer, mid-session.

        A rebuild rather than a flag flipped in place: with the setting on,
        the bus is a different player and the pair has to be wired differently
        for it -- see make_transport, and BackupTransport.handover. The old
        one is let go of afterwards, since a swap mid-reading leaves the
        sampler holding it for one more round trip.
        """
        was = self.clock.io
        self.clock.io = self.make_player()
        self.vet_at.clear()
        self.vet_meta.clear()
        self.vet_sent.clear()
        self.card_done.clear()
        self.vet_body = None
        try:
            was.drop()
        except Exception:                                    # noqa: BLE001
            pass
        if say:
            self.toast("following whoever is playing" if self.any_player
                       else "following Spotify only")

    def vet_pending(self) -> None:
        """Look up a track another player is holding out, without showing it.

        The transport will not hand over a track off anything but Spotify
        until it is told the track is a song, and there are two ways to be
        told. The catalogue is asked first and answers first -- it is one
        request and it is being made anyway -- and a record it is sure of is
        the track vouched for outright; see on_card. The providers answer the
        same question with words, for a song no catalogue has; that one is
        fetched here exactly as the playing track would be, while the window
        goes on showing what it was showing, and lands in vet_answer.

        Not on every poll: the fetcher retries a track it found nothing for on
        its own backoff, and asking again on top of that would be a second
        walk for the length of whatever is playing. Not once and for all
        either -- see VET_AGAIN.
        """
        want = getattr(self.clock.io, "pending", None)
        if not want:
            return
        tid, m = want["tid"], want["meta"]
        now = mono()
        if now - self.vet_at.get(tid, -VET_AGAIN) < VET_AGAIN:
            return
        self.vet_at[tid] = now
        self.vet_meta[tid] = dict(m)
        if want.get("who") != SPOTIFY_BUS and tid not in self.card_asked:
            self.want_card(tid, m, True)
            if tid in self.card_asked:
                return
        self.ask_lyrics(tid)

    def ask_lyrics(self, tid: str) -> None:
        """Put a held-back track to the providers, once.

        With whatever is known by now: the catalogue's spelling and the
        record's length where it answered, the player's own card where it did
        not. Called from vet_pending when there is nothing to wait for, and
        from on_card when there was.
        """
        m = self.vet_meta.get(tid)
        if m is None or tid in self.vet_sent:
            return
        self.vet_sent.add(tid)
        self.fetcher.request(tid,
                             {"title": m.get("title", ""),
                              "artist": m.get("artist", ""),
                              "album": m.get("album", ""),
                              "length": self.card_len.get(tid,
                                                          m.get("length", 0.0)),
                              "explicit": None},
                             self.sources(), self.source_order(), self.ne_graft,
                             self.fold_adlibs, self.uncensor, self.roster())

    def want_card(self, tid: str, meta: dict, other: bool | None = None) -> None:
        """Ask a catalogue what a track looks like, for a player that cannot.

        Spotify says what is playing and hands over the cover it belongs to.
        A browser hands over a video's thumbnail -- sixteen by nine, the
        channel's lettering across it, and sometimes nothing at all -- and an
        album field with the site's name in it or nothing. Apple Music has
        the same song filed properly, and this app is already asking it about
        the words, so the cover comes out of a request it was making anyway.

        Only for the other players. Nothing is asked about a Spotify track:
        its card is already right, and a lookup could only make it wrong.
        `other` says whether this track is one of theirs, for a caller that
        knows -- a track being vetted belongs to a player that is NOT the one
        being followed, so the transport cannot be asked about it.
        """
        if not tid or tid in self.card_asked or not meta.get("title"):
            return
        if other is None:
            other = getattr(self.clock.io, "app", DEVICE_APP) != DEVICE_APP
        if not other:
            return
        self.card_asked.add(tid)
        self.fetcher.request_card(tid, {
            "title": meta.get("title", ""), "artist": meta.get("artist", ""),
            "album": meta.get("album", ""), "length": meta.get("length", 0.0)})

    def on_card(self, tid: str, card) -> None:
        """What the catalogue had. Worn by the track from the next reading on.

        Put on the TRANSPORT rather than on the clock: the clock's card is
        rewritten from the player sixty times a second, so anything written
        there is gone by the next frame. See SessionTransport.dress.
        """
        if not isinstance(card, dict) or not card.get("sure"):
            self.ask_lyrics(tid)
            return
        dress = getattr(self.clock.io, "dress", None)
        if dress is None:
            self.ask_lyrics(tid)
            return
        dress(tid, {"art": card.get("art") or "",
                    "album": card.get("album") or "",
                    "title": card.get("title") or "",
                    "artist": card.get("artist") or ""})
        if tid in self.vet_meta:
            for key in ("title", "artist", "album"):
                if card.get(key):
                    self.vet_meta[tid][key] = card[key]
        secs = float(card.get("length") or 0.0)
        if secs > 0:
            self.card_len[tid] = secs
        if tid in self.vet_at and tid != self.clock.tid:
            self.clock.io.allow(tid)
        if (tid == self.clock.tid and tid not in self.card_done
                and self.better_question(tid, card, secs)):
            self.card_done.add(tid)
            LS.forget(tid)
            self.fetcher.request(tid, self.fetch_meta(), self.sources(),
                                 self.source_order(), self.ne_graft,
                                 self.fold_adlibs, self.uncensor,
                                 self.roster())
        self.ask_lyrics(tid)

    def better_question(self, tid: str, card: dict, secs: float) -> bool:
        """Whether the catalogue improved on what the player said.

        A different name or a different length is a different question, and
        the providers are searched by both. The same card said twice is not
        worth another walk.
        """
        was = self.clock.meta if tid == self.clock.tid else self.vet_meta.get(tid, {})
        if secs > 0 and abs(secs - float(was.get("length") or 0)) > 1.5:
            return True
        return any(card.get(key) and SL_norm(card[key]) != SL_norm(was.get(key, ""))
                   for key in ("title", "artist"))

    def vet_answer(self, tid: str, lines, body=None) -> bool:
        """Words came back for a track being held out. So it is a song.

        The OTHER answer to that question is on_card's, which does not come
        through here: a catalogue sure of the record vouches for the track
        without waiting to hear whether anybody wrote its words down. This one
        is what still answers for a song no catalogue has heard of, and for
        one whose card came back with nothing to go on.

        True means this answer was about a track that is not on screen and has
        now been dealt with, so the caller should stop. A hit lets the track
        through -- the next reading a sixtieth of a second later carries it,
        poll() sees a new song, and the words are already fetched and cached
        by the time it asks for them.

        A miss is not final here: the fetcher goes on retrying a track it
        found nothing for, and the next answer comes back through this same
        door. What settles it is the video ending.
        """
        if tid == self.clock.tid or tid not in self.vet_at:
            return False
        if not lines:
            return True
        self.vet_at.pop(tid, None)
        self.vet_body = (tid, lines, body)
        self.clock.io.allow(tid)
        return True

    def poll(self) -> None:
        """Everything the window has to keep up with EXCEPT the clock.

        The player is not asked anything here any more -- the sampler does
        that, sixty times a second on its own thread, and this runs on the
        readings it has already taken. So `prev` cannot be read off the clock
        either: it used to be the value from before this method's own reading,
        and there is no longer a reading here to be before. It is the track
        this method last SAW, which is the same thing said in a way that does
        not depend on who took the reading.
        """
        prev = self._seen_tid
        self.check_editor_gone()
        self.on_player(getattr(self.clock.io, "app", DEVICE_APP))
        if self.any_player:
            self.vet_pending()
            self.want_card(self.clock.tid or "", self.clock.meta)
            say = getattr(self.clock.io, "trouble", "")
            if say and say != self._said_player:
                self._said_player = say
                self.toast(say)
        if (self.fetch_ahead and self.clock.status == "Playing"
                and mono() - self._ahead_at > 60.0):
            self._ahead_at = mono()
            self.fetcher.request_queue()
        if getattr(self.args, "track", None):
            self.clock.tid = self.args.track
        self._seen_tid = self.clock.tid
        if self.clock.tid and self.clock.tid != prev:
            self.reset_track("Loading lyrics…")
            self._ahead_at = 0.0
            if self.vet_body and self.vet_body[0] == self.clock.tid:
                self.on_lyrics(*self.vet_body)
                self.vet_body = None
            handed_over = prev is not None and mono() - self.skip_at > 3.0
            if handed_over and self.resync:
                QTimer.singleShot(800, self.clock.resync_soon)
        elif self.clock.tid and not self.lines and not self.searched():
            self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                                 self.source_order(), self.ne_graft, self.fold_adlibs,
                                 self.uncensor, self.roster())
        length = self.clock.meta.get("length", 0.0)
        left = length - self.clock.position() if length else 99.0
        want = (POLL_MS_EDGE if left < 3.0
                or (not self.lines and not self.searched()) else POLL_MS)
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
        elif self.motion_frames or self.motion_key:
            self.motion_key, self.motion_frames = "", []

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
                self._ink_gen += 1

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
        lines = prepare(self.raw, self.interlude, self.merge_ms / 1000.0)
        rows, links = self.credit_rows()
        if rows:
            lines.append({"start": None, "end": None, "text": "", "syls": [],
                          "pieces": [], "opposite": False, "background": False,
                          "credits": rows, "credit_links": links,
                          "syls_roman": [], "pieces_roman": []})
        return lines

    def rebuild_lines(self) -> None:
        """Re-fold interludes at the current gap setting."""
        if not self.raw:
            return
        self.lines = self.build_lines()
        self.apply_romaji_fixes()
        self.layout_cache.clear()
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
        """Put a TTML from disk on screen, and keep it for this track.

        It lasts the play. It used to be kept on disk and put back the next
        time the song came round, in the same store an alignment made here was
        kept in -- and that store went when the aligner did, so a file dropped
        now is a file dropped now. R still takes it off, which is the same
        gesture that already means "that answer was wrong, go and ask again".
        """
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
        tid, name = self.clock.tid, pathlib.Path(path).name
        self.dropped = tid
        self.dropped_from = name
        self.on_lyrics(tid, lines, body, force=True)
        timed = sum(1 for ln in lines if ln.get("start") is not None)
        if tid:
            LS.forget(tid)
        self.toast(f"{name} — {timed}/{len(lines)} lines timed · Y to review it")
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
        if self.dropped != self.clock.tid and self.body is not None:
            self.own_body = self.body
        self.dropped = self.clock.tid
        self.dropped_from = str(name or "the editor")
        self.on_lyrics(self.clock.tid, lines, body, force=True)
        return True

    def follow_editor(self, pos: float, playing: bool) -> None:
        """Walk Spotify along with the editor's own copy of the song.

        Somebody timing against a local file is watching THIS window draw
        their document -- and this window draws against Spotify's clock. So
        the words they had just placed swept past at whatever point Spotify
        happened to be sitting at, which is usually nought and sometimes
        another song entirely: the one screen that was supposed to show them
        their work in place was the one screen that could not.

        So Spotify is put where their file is and kept there: seeked when
        it drifts more than FOLLOW_DRIFT -- see _follow_to -- playing while
        their file plays, paused when they pause. Muted the whole time it is
        playing, because two copies of one song a fraction of a second apart
        is not something anybody can time against, and unmuted once it has
        actually stopped, so what is handed back is a player sitting where
        they are, audible.

        Only while their document is the one on screen. The editor sends this
        only when it is timing against a local file, but "there is an editor
        attached" is not on its own a reason for this window to take hold of
        somebody's playback.
        """
        if self.dropped is None or self.dropped != self.clock.tid:
            return
        self._follow_at = mono()
        self._follow_to(max(0.0, float(pos)) + self.track_offset())
        if playing:
            self._mute_for_editor()
        self._transport(playing)
        if not playing and self.clock.status != "Playing":
            self._unmute_for_editor()

    def _follow_to(self, want: float) -> None:
        """Put the player where the editor's audio is -- rationed, and not
        for ever. One seek every FOLLOW_AGAIN, and a place that will not be
        reached let go of after FOLLOW_TRIES.

        WHAT COUNTS AS A REFUSAL is the whole of this. A seek is not answered
        the instant it is sent: it goes out, the player moves, and the
        position read here catches up a poll or two later -- longer than
        FOLLOW_AGAIN, comfortably. Counting every seek SENT as a try that
        failed therefore ran the count out on a player that was behaving
        perfectly, and the way to see it is to nudge a timestamp: each nudge
        asks for somewhere a few hundredths further on, none of them far
        enough from the last to read as a new place, and four of them in a
        row spent the budget. What followed was a stretch of the editor being
        ignored -- until the nudges added up to more than FOLLOW_DRIFT, which
        started the count again, and then stopped it again four nudges later.
        Timing a line, which is small nudges and nothing else, is exactly the
        case it broke on.

        So a try is only a failure where the player has NOT MOVED since the
        last one: a player travelling towards where it was sent is following,
        however far behind the count it is.

        And giving up is giving up for FOLLOW_REST, not for good. The editor
        goes on saying where it is several times a second; something that has
        stopped listening to that has to have a way back, or a single bad
        minute -- the player buffering, a track loading -- costs the rest of
        the session. Said once per stretch of not following, though: the
        toast belongs to the first refusal, not to every retry.
        """
        now, here = mono(), self.clock.position()
        if abs(here - want) <= FOLLOW_DRIFT:
            self._arrived(want)
            return
        if abs(want - self._follow_want) > FOLLOW_DRIFT:
            self._follow_tries, self._follow_said = 0, False
            self._follow_gave_at = 0.0
        elif (self._follow_tries and self._follow_from is not None
                and abs(here - want) < abs(self._follow_from - want) - FOLLOW_DRIFT):
            # The gap closed: it went where it was sent, or most of the way.
            # Closing rather than merely MOVING, because a player left running
            # moves on its own -- a second of playback is three times
            # FOLLOW_DRIFT -- and reading that as an answer would retire the
            # count altogether and with it the one case it is for, a player
            # that takes seeks and ignores them.
            self._follow_tries = 0
            self._follow_gave_at = 0.0
        if self._follow_tries >= FOLLOW_TRIES:
            if not self._follow_gave_at:
                self._follow_gave_at = now
            if now - self._follow_gave_at < FOLLOW_REST:
                if not self._follow_said:
                    self._follow_said = True
                    self.toast("the player will not go where the editor is — "
                               "waiting a moment and trying again")
                return
            self._follow_tries, self._follow_gave_at = 0, 0.0
        if now - self._follow_seek_at < FOLLOW_AGAIN:
            return
        self._follow_seek_at, self._follow_want = now, want
        self._follow_from = here
        self._follow_tries += 1
        self.clock.seek(want)

    def _arrived(self, want: float) -> None:
        """The player is where the editor is. Nothing owed, nothing counted."""
        self._follow_tries, self._follow_said = 0, False
        self._follow_gave_at, self._follow_from = 0.0, None
        self._follow_want = want

    def _transport(self, playing: bool) -> None:
        """Put Spotify into the play state the editor is in, at most one
        command every FOLLOW_STEADY -- the status this reads is a poll or two
        behind the command that changes it, and without the wait a pause
        arriving eight times a second is eight PlayPauses."""
        if playing == (self.clock.status == "Playing"):
            return
        now = mono()
        if now - self._follow_cmd_at < FOLLOW_STEADY:
            return
        self._follow_cmd_at = now
        self.clock.command("PlayPause")

    def _mute_for_editor(self) -> None:
        """Silence Spotify, remembering what it was set to.

        Its own volume, not the system's: this is the one knob that belongs
        to the player rather than to whatever else is making noise, and it is
        put back exactly as it was. Where the transport carries no volume at
        all -- Windows' media controls do not -- nothing is muted and nothing
        is claimed to have been.
        """
        if self._muted_from is not None:
            return
        was = self.clock.volume
        if was is None or was <= 0.0:
            return
        self._muted_from = float(was)
        self.clock.set_volume(0.0)
        self.toast("following the editor's own audio — Spotify muted")

    def _unmute_for_editor(self) -> None:
        if self._muted_from is None:
            return
        was, self._muted_from = self._muted_from, None
        self.clock.set_volume(was)
        self.toast("Spotify unmuted")

    def check_editor_gone(self) -> None:
        """Hand the playback back if the editor walking it has gone quiet.

        Closed on a crash, its socket dropped without a word, its checkbox
        turned off by somebody who then went to lunch. It says where it is
        several times a second while it means it, so silence for FOLLOW_GONE
        is silence for good -- and a muted player running on by itself is the
        one state nobody asked for.
        """
        if (self._muted_from is not None
                and mono() - self._follow_at > FOLLOW_GONE):
            self.unfollow_editor()

    def unfollow_editor(self, pause: bool = True) -> None:
        """Give the player back. Called when the editor says it has stopped,
        when it goes away without saying, and when the track changes under it.

        Paused as well as unmuted where this window is what set it playing:
        an editor that has closed is not timing anything, and a muted song
        running on by itself is the one state nobody asked for.
        """
        if self._muted_from is None:
            self._follow_at = 0.0
            return
        if pause and self.clock.status == "Playing":
            self._follow_cmd_at = mono()
            self.clock.command("PlayPause")
        self._unmute_for_editor()
        self._follow_at = 0.0
        self._follow_tries, self._follow_said = 0, False

    def drop_live_lyric(self) -> None:
        """Let go of the editor's document and put the song's own back.

        The asking matters as much as the letting go. Clearing `body` only
        says what is NOT on screen; nothing then goes and gets what should
        be, so the song sat with no lyrics at all until the track changed --
        which is what the editor closing, or its checkbox being turned off,
        looked like from here. reset_track has always re-requested; this is
        the same request, for the track that is already playing.
        """
        if self.dropped is None:
            return
        self.unfollow_editor()
        self.dropped = None
        self.dropped_from = ""
        self.own_body = None
        self.lines, self.raw, self.body, self.synced = [], [], None, False
        self.layout_cache.clear()
        self.drop_pixmaps()
        self.line_rects = []
        self.toast("back to this song's own lyrics")
        if self.clock.tid:
            self.status_text = "looking for lyrics…"
            self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                                 self.source_order(), self.ne_graft, self.fold_adlibs,
                                 self.uncensor, self.roster())

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
        self.on_art("", (img, blurred, palette_of(img)), dropped=True)
        self.dropped_art = self.clock.tid
        self.toast(f"cover from {pathlib.Path(path).name}")
        return True

    def reset_track(self, status: str, keep: bool = False) -> None:
        """Start this track's lyrics again, and say what is being waited for.

        `keep` is the same song asked for a second time -- R -- rather than a
        new one, and it leaves the words where they are. Blanking them means
        the window shows nothing at all for as long as the answer takes, and
        the answer is not always the page read it ought to be: one wedged
        socket, one provider on a long timeout, and a reload of a song whose
        document is sitting in the page a tenth of a second away is ten
        seconds of "Reloading…" over an empty screen. What is on screen is
        this song's lyric until a better one lands, so it stays up and is
        replaced rather than removed first; see on_lyrics, which takes an
        empty answer over it once the fetcher says it has finished asking.
        """
        self.unfollow_editor(pause=False)
        self.dropped = self.dropped_art = None
        self.dropped_from = ""
        self.own_body = None
        self.reloading = self.clock.tid if keep else None
        if not keep:
            self.lines, self.raw, self.body, self.synced = [], [], None, False
            self._drawn = []
            self.beat.clear()
            self.est, self.est_tid = {}, None
            self.layout_cache.clear()
            self.drop_pixmaps()
            self.activation.clear()
            self.line_rects = []
            self._marq.clear()
            self.scroll = self.scroll_target = self.content_h = 0.0
            self.hover_idx = -1
        self.track_at = mono()
        self._section = 0
        self._viz_ch = [0.0] * 12
        self._viz_tone = 1.0
        self._viz_lvl = self._viz_kick = 0.0
        self.status_text = status
        if self.clock.tid:
            self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                                 self.source_order(), self.ne_graft, self.fold_adlibs,
                                 self.uncensor, self.roster())

    def _load_art(self, url: str) -> None:
        """Runs off the GUI thread, so it may only touch QImage -- QPixmap is
        documented as main-thread only and crashes under some Qt backends.

        The url it was fetching goes back with the picture, because by the
        time it lands it may not be the picture anybody wants; see on_art.
        None goes back where there is no picture, for the same reason: a
        failure nobody is told about is a failure nobody retries.
        """
        raw = art_bytes(url)
        img = QImage()
        if not raw or not img.loadFromData(raw):
            self.art_ready.emit(url, None)
            return
        try:
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
            triple = (img, blurred, palette_of(img))
        except Exception:                                # noqa: BLE001
            self.art_ready.emit(url, None)
            return
        self.art_ready.emit(url, triple)

    def on_art(self, url: str, triple, dropped: bool = False) -> None:
        """A cover to draw. `dropped` means it came off the window, by hand.

        ONLY IF IT IS STILL THE COVER BEING ASKED FOR. Every track change
        starts a download of its own on a thread of its own, and they finish
        in whatever order the network hands them over -- so skipping quickly
        through three songs raced three downloads, and whichever one happened
        to land LAST won, however long ago the song it belonged to had gone.
        The cover on screen was then somebody else's album, and so were the
        two things drawn out of it: the blurred plate behind the words, and
        the palette every other colour in the window is lifted from. That is
        why an animated cover taking the picture's place did not put it right
        -- the picture was only one of the three, and the other two are the
        background.

        `art_url` is what the last track change asked for, so a picture that
        does not answer to it is a picture for a song that is no longer
        playing. The same guard on_motion has always had, one signal along.

        A picture dropped on a song holds until the song changes -- including
        against the cover this app is still downloading for it, which used to
        arrive a moment later and quietly put itself back.
        """
        if not dropped and url != self.art_url:
            return
        if triple is None:
            self._art_fails[url] = self._art_fails.get(url, 0) + 1
            if self._art_fails[url] < ART_GIVE_UP:
                self.art_url = ""
            return
        self._art_fails.pop(url, None)
        if (not dropped and self.dropped_art is not None
                and self.dropped_art == self.clock.tid):
            return
        img, blurred, palette = triple
        self.art_full = QPixmap.fromImage(img)
        self.art_bg = QPixmap.fromImage(blurred)
        self.palette = palette
        self.art_luma = luma_of(img)
        self.art_gen += 1

    def nudge_offset(self, delta: float) -> None:
        """[ and ] tune the TRACK you are listening to. A song that is mastered
        a little late needs its own correction, not a global one that then
        breaks every other song.

        Correcting a track by hand also retires the measured offset for it. Not
        because the measurement was wrong, but because it has been superseded by
        somebody who can actually hear the song, and two corrections stacking on
        one track would be twice the intended fix. The measurement is kept --
        it is still what the menu shows, and it comes back if the hand
        correction is cleared.

        A hand correction of ZERO is one of those statements and is kept as
        one. It used to be deleted as if it had never been made -- which
        handed the track straight back to the measured offset it had just been
        tuned off, and made any track whose measurement is an exact multiple
        of the step impossible to tune past: BABY I'M BACK measures +0.05,
        every press of [ landed on 0.00, the entry was dropped, +0.05 came
        back, and the offset sat at -0.05 (with a -0.10 global) however many
        times the key went down. Clearing a track and setting it to nothing
        are different requests, and 0 is the key that does the first.
        """
        tid = self.clock.tid
        if not tid:
            self.offset = round(self.offset + delta, 3)
            self.toast(f"global offset {self.offset:+.2f}s")
            return
        base = self.offsets.get(tid, self.auto_offset(tid))
        self.offsets[tid] = round(base + delta, 3)
        self.toast(f"this track {self.offsets[tid]:+.2f}s "
                   f"(total {self.track_offset():+.2f}s)")

    def _watch_device(self) -> None:
        """Which output the sound is coming out of, asked off the GUI thread.

        Two short subprocesses per look, which is two too many for the thread
        that draws. Polled rather than subscribed to: pactl will hold a
        subscription open, but that is a process kept alive for the life of
        the window to learn something that changes when somebody picks up
        their headphones.
        """
        while not self.fetcher.stop:
            try:
                dev, name = audio_sink(getattr(self.clock.io, "app", DEVICE_APP))
            except Exception:                            # noqa: BLE001
                dev, name = "", ""
            if dev != self.device:
                self.device_ready.emit(dev, name)
            time.sleep(DEVICE_POLL)

    def offset_key(self) -> str:
        """Which standing offset applies here: the output, and who is playing.

        TWO REASONS THE SAME SONG ARRIVES LATE, and they are independent.

        The output is the one this was built for: a headset two hundred
        milliseconds behind the monitor it was tuned on is not the lyrics
        being wrong, it is the sound having further to go.

        The PLAYER is the other, and it is what the any-media-player setting
        made reachable. Spotify's clock and a browser's do not sit the same
        distance from their own sound: the browser publishes a position it
        rounds to the second, through a pipeline of its own, and whatever
        standing difference that leaves is a property of the program and not
        of the speaker it comes out of. Tuning YouTube by ear used to move
        Spotify with it, on the same headset, because there was one number
        for the pair -- so the two could not both be right and the second one
        tuned undid the first.

        The key is the pairing. Written player-first so a settings file reads
        as what it is -- `firefox@alsa_output.usb-046d_G435.iec958-stereo` --
        and a bare output name, which is every settings file written before
        this, is still a key: see _swap_offset, where it is what a player
        heard for the first time on a known output starts from.
        """
        if not self.device:
            return ""
        return f"{self.player}@{self.device}" if self.player else self.device

    def _swap_offset(self, was: str) -> bool:
        """Put the live offset away under `was` and take out the one for now.

        Answers whether the number actually moved, which is not the same
        question as whether the pairing changed: whoever is playing can flip
        back and forth in a silence, and a toast per flip is chatter about
        nothing. See on_player.
        """
        if was:
            self.dev_offsets[was] = round(self.offset, 3)
        key = self.offset_key()
        if not key:
            return False
        before = self.offset
        if key in self.dev_offsets:
            self.offset = round(float(self.dev_offsets[key]), 3)
        elif self.device in self.dev_offsets:
            self.offset = round(float(self.dev_offsets[self.device]), 3)
            self.dev_offsets[key] = self.offset
        else:
            self.dev_offsets[key] = round(self.offset, 3)
        return self.offset != before

    def on_player(self, app: str) -> None:
        """Somebody else is playing; take their own standing offset out.

        The same swap on_device makes, for the other half of the key. Called
        off poll() rather than watched for: it is a string already on the
        transport, and reading it costs nothing next to the two subprocesses
        the output costs.

        Said out loud only where the number MOVED. An output changing is
        worth a line whatever it does to the timing -- see on_device, the
        number now belongs somewhere else and that is worth knowing -- but
        who is playing flips about on its own in the silences between songs,
        and a toast on each of those is noise about nothing that changed.
        """
        app = str(app or "")
        if app == self.player:
            return
        was = self.offset_key()
        self.player = app
        if self._swap_offset(was) and was:
            self.toast(f"{app or 'the player'} — offset {self.offset:+.2f}s")

    def on_device(self, dev: str, name: str) -> None:
        """The sound has moved to another output; take its timing with it.

        A headset two hundred milliseconds behind the monitor it was tuned on
        is not the lyrics being wrong, it is the sound arriving late -- and
        the correction for that belongs to the device. It is the same song,
        the same document and the same window; the only thing that changed is
        how far the audio has to travel. So the global offset is kept per
        output and swapped when the output does, while the per-track
        corrections and the measured ones -- which are statements about the
        LYRIC -- carry over untouched.

        An output heard from for the first time inherits whatever is set now
        rather than snapping to zero. It is a guess, but it is the guess that
        changes nothing, and the first nudge on it writes the real number.

        The output is half the key now, not the whole of it -- see offset_key
        for the other half and why it is there. Nothing about THIS method's
        behaviour changed with it: what is put away and what is taken out are
        the same two acts, against a key that also names whoever is playing.
        """
        if dev == self.device:
            return
        was = self.offset_key()
        self.device = dev
        self.device_name = name or dev
        if not dev:
            if was:
                self.dev_offsets[was] = round(self.offset, 3)
            return
        self._swap_offset(was)
        if was:
            self.toast(f"{self.device_name} — offset {self.offset:+.2f}s")

    def device_offsets(self) -> dict:
        """Every output's offset, with the one in use kept up to date.

        The live value lives in `offset` -- the menu, the keys and the reset
        all write there and know nothing about outputs -- so it is folded in
        here rather than mirrored on every path that could touch it.

        Every OTHER key is written back exactly as it was read, bare output
        names included. Those are what a player heard for the first time on a
        known output starts from (see _swap_offset), so dropping them because
        nothing writes them any more would throw away the tuning that is the
        whole reason somebody has a settings file with offsets in it.
        """
        got = {k: round(float(v), 3) for k, v in self.dev_offsets.items()}
        key = self.offset_key()
        if key:
            got[key] = round(self.offset, 3)
        return got

    def auto_offset(self, tid: str) -> float:
        """The measured correction for a track, or 0.0 where there is none to
        apply -- no reading, not a confident one, or nothing to calibrate it
        against yet. A hand correction on the track beats all of it.

        The gates are doing real work here and are deliberately strict. A wrong
        offset applied silently is worse than no offset at all: the lyrics were
        merely out before, and now they are out and the program is insisting
        otherwise. Three of them, asking three different questions -- was the
        reading clear (conf), did the song say the same thing twice (spread),
        and is the answer a size a lyric sheet is ever actually out by
        (EST_MAX) -- because the readings that are badly wrong pass the first
        one comfortably. See EST_MAX.

        The reading is applied as it stands. There used to be a calibration
        subtracted from it first, worked out from the tracks that had been
        tuned by hand -- see the note where calibrate() was, which is about why
        those tracks could not answer the question they were being asked. What
        it also did, while it was there, was gate this: with fewer than five
        hand-tuned tracks carrying a reading the answer was 0.0 whatever the
        measurement said, and a fresh install has none, so the feature could
        not start working until somebody had tuned five songs by ear that it
        had also happened to measure. Nothing said so except a line in a menu.
        """
        if not tid or not self.auto_time or tid in self.offsets:
            return 0.0
        got = self.est_raw.get(tid)
        if not got or got["conf"] < EST_CONF_MIN:
            return 0.0
        if got.get("spread", EST_RANGE * 2.0) > EST_AGREE:
            return 0.0
        delta = round(got["delta"], 3)
        return 0.0 if abs(delta) > EST_MAX else delta

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
        self.est = self.est_raw.get(tid, {})

    def on_index_progress(self, n: int) -> None:
        self.index_n = n

    @property
    def unpause_delay(self) -> float:
        return self.clock.unpause_delay

    @unpause_delay.setter
    def unpause_delay(self, v: float) -> None:
        self.clock.unpause_delay = max(-1.0, min(1.0, float(v)))

    @property
    def unpause_mode(self) -> str:
        return UNPAUSE_MODES[1] if self.clock.unpause_fixed else UNPAUSE_MODES[0]

    @unpause_mode.setter
    def unpause_mode(self, v: str) -> None:
        self.clock.unpause_fixed = (v == UNPAUSE_MODES[1])

    def track_offset(self) -> float:
        """Global offset plus whatever this particular track needed.

        The per-track part is the hand correction where there is one and the
        measured one otherwise -- never both, or a track fixed by ear would be
        fixed twice. auto_offset() enforces that; this stays a plain sum so that
        everywhere already subtracting it keeps working unchanged.

        A document that is not this song's own gets the global offset and
        NOTHING else -- one pushed over the live link from the editor, or
        dropped in as a file. Both of those are somebody timing a lyric
        against this recording and watching the result here, and both
        per-track corrections are statements about a DIFFERENT document: the
        hand one says how far the song's own lyric sits out, the measured one
        was read off it. Applying either to a lyric being written puts the
        editor and the player at different times for the same file, so a
        syllable placed dead on lands late on screen -- and the writer then
        corrects for a shift the file does not contain, baking it in.
        """
        if self.dropped is not None and self.dropped == self.clock.tid:
            return self.offset
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

    def on_fetched(self, tid: str, lines, body) -> None:
        """A lyric answer off the fetcher. Two questions it could be about.

        Nearly always the song on screen, and those go straight through. The
        other kind is a track some other player is holding out, looked up only
        to find out whether it is a song at all -- that answer is taken by
        vet_answer and never drawn. It is caught HERE rather than in
        on_lyrics, which is the window putting words up and is called by
        everything that has words to put up.
        """
        if not self.vet_answer(tid, lines, body):
            self.on_lyrics(tid, lines, body)

    def on_lyrics(self, tid: str, lines, body, force: bool = False) -> None:
        if tid != self.clock.tid:
            return
        if not force and self.dropped == tid and body is not self.body:
            if body is not None and self.own_body is None:
                self.own_body = body
            return
        if not lines and self.lines and not (self.reloading == tid
                                             and self.fetcher.done == tid):
            return
        if self.reloading == tid:
            self.reloading = None
        same = self.same_lyric(lines, body)
        if same:
            self.body = body if body is not None else self.body
            self.source = str(SL.payload(self.body or {}).get("_source") or "")
            return
        self._drawn = self.lyric_key(lines)
        self.raw = lines or []
        self.body = body
        self.source = str(SL.payload(body or {}).get("_source") or "")
        self.lines = self.build_lines()
        self.japanese = any(SL.KANA.search(ln.get("text") or "")
                            for ln in self.lines)
        self.apply_romaji_fixes()
        self.synced = any(ln["start"] is not None for ln in self.lines)
        if not same:
            self.est_tid = None
        self.measure_offset()
        if not same:
            self.layout_cache.clear()
        if not self.lines:
            self.status_text = "No cached lyrics yet — waiting…"
        elif not self.synced:
            self.status_text = "Unsynced lyrics"
        else:
            self.status_text = ""
        self.maybe_auto_genius()

    @staticmethod
    def lyric_key(lines) -> list:
        """What a document draws, as plain values.

        Taken as the lines ARRIVE, before prepare() fills each of them in --
        it clamps an open end and hangs the laid-out pieces on the same dicts,
        so `raw` a moment later no longer equals the list it was made from and
        cannot be compared against the next one.

        `pieces` are left out for the same reason and a better one: they are
        derived from the timings already here, so a document that agrees on
        every start, end and syllable cannot disagree on them.
        """
        return [(ln.get("start"), ln.get("end"), ln.get("text"),
                 tuple(ln.get("syls") or ()), bool(ln.get("opposite")),
                 bool(ln.get("background")), ln.get("text_roman"))
                for ln in lines or []]

    def same_lyric(self, lines, body) -> bool:
        """Whether an arriving answer draws exactly what is on screen already.

        Asked of the LINES, not of the document. The document cannot answer
        it: the same lyric reaches here as a different object every time --
        the walk reports a copy of what it is about to return, _shaped builds
        a repaired document rather than editing one, and every re-read of the
        page hands back a freshly parsed dict. Comparing those by identity
        said "new lyric" to every one of them, and a new lyric costs the whole
        screen: every line laid out again, every pixmap dropped, the offset
        measured again on the drawing thread. Three handovers on an ordinary
        song, two of them drawing what was already there.

        The lines are what gets drawn, so they are the honest question, and
        they are cheap to ask it of -- a tuple per line, against a re-layout
        of the window.
        """
        if body is not None and body is self.body:
            return True
        return bool(self._drawn) and self.lyric_key(lines) == self._drawn

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

    def _said_language(self, doc: dict) -> str:
        """What language this is.

        The ANSWER, not the argument. Providers guess this and guess it wrong
        the same way every time -- an English lyric filed under a small
        Latin-script code -- and showing "pcm (reads as en, the words are
        English)" put the wrong code first and made a plain fact into a
        paragraph. The panel says en, because it is en.
        """
        claimed = str(doc.get("LanguageISO2") or doc.get("Language") or "")
        if not claimed:
            return "—"
        try:
            import language as LANG
            said = " ".join(str(r.get("text") or "") for r in self.lines[:80])
            got, _why = LANG.check(claimed, said)
        except Exception:
            return claimed
        return got or claimed

    def source_name(self, doc: dict) -> str:
        """Where the lyrics on screen actually came from.

        The catalogue, never the door: a document fetched through a proxy that
        holds several catalogues is its catalogue's, and naming the proxy
        instead left the reader no wiser about who wrote the words. The
        upstream is still printed where it says something the name does not --
        a blend reports its whole makeup -- and dropped where it only repeats
        it.

        Where the words and the clock come from different places the label says
        both. A NetEase-timed document used to report as plain "Spicy Lyrics",
        which credits the half of it that could not do the thing you are
        watching it do.
        """
        via = {"apple": "Apple Music", "musixmatch": "Musixmatch",
               "musixmatch-word": "Musixmatch", "qq": "QQ Music",
               "deezer": "Deezer", "qaple": "Apple Music with QQ"}
        was_really = {"apple": "apple", "qaple": "blend", "qq": "qq",
                      "musixmatch": "mxm", "musixmatch-word": "mxm"}
        if self.dropped is not None and self.dropped == self.clock.tid:
            whose = str(getattr(self, "dropped_from", "") or "")
            return f"the synchroniser · {whose}" if whose else "the synchroniser"
        src = self.source
        alone = str(doc.get("_alone") or "")
        if src in BLENDS and alone:
            src = "" if alone == "spicy" else alone
        name = {"amll": "amll-ttml-db", "apple": "Apple Music",
                "bini": "Apple Music · BiniLyrics", "unison": "Unison",
                "qq": "QQ Music", "kugou": "Kugou",
                "netease": "NetEase Cloud Music", "mxm": "Musixmatch",
                "deezer": "Deezer", "blend": "Apple Music with QQ",
                "kublend": "Apple Music with Kugou",
                "neblend": "Apple Music with NetEase",
                "triblend": "Apple Music with NetEase and QQ",
                "kutriblend": "Apple Music with NetEase and Kugou",
                "lrclib": "LRCLIB", "genius": "Genius"}.get(src)
        if not name and src:
            # A source this build no longer has -- a document cached before it
            # was taken out, which LS.stored will still put up while the walk
            # runs. Say that rather than falling through to the line below,
            # which would credit the words to Spicy Lyrics: naming the wrong
            # source is worse than naming none, and it is the one thing a
            # credit line must never do.
            return "unknown source"
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
        up = "" if src in BLENDS else doc.get("_via")
        was = via.get(str(up).lower(), up) if up else ""
        return f"{name} · {was}" if was and was != name else name

    def made_by(self, doc: dict) -> str:
        """Who timed this copy of the song, as one line."""
        return self.made_by_linked(doc)[0]

    def made_by_linked(self, doc: dict) -> tuple:
        """The same line, and the pages the names in it point at.

        Spicy Lyrics distinguishes the person who made the sync from the person
        who uploaded it, and often only knows the second -- Maker comes back as
        an empty {} on two thirds of the community entries here. Its own UI
        credits the uploader as the maker in that case, which is the right call:
        with nobody else named, they are who made it, and "uploaded by" credits
        them for less than they did.

        Each of them carries the address of their own page, and the credit is
        required to LINK there rather than only name them -- that is section 6
        of the terms this lyric arrived under, not a flourish. The link is
        [(the words to underline, where they go), ...]; a contributor with no
        page of their own contributes no entry, which is everybody the other
        sources credit, and is why this comes back empty rather than dead.
        """
        meta = doc.get("TTMLUploadMetadata")
        meta = meta if isinstance(meta, dict) else {}
        makers = LS.people_of(meta.get("Maker")) or LS.people_of(doc.get("_maker"))
        uploaders = LS.people_of(meta.get("Uploader"))
        bits = []
        if makers:
            bits.append("Made by " + ", ".join(p["name"] for p in makers))
        if uploaders:
            bits.append(("Uploaded by " if makers else "Made by ")
                        + ", ".join(p["name"] for p in uploaders))
        links = [(p["name"], p["url"]) for p in makers + uploaders
                 if p.get("name") and p.get("url")]
        words = str(doc.get("_words_by") or "").strip()
        if words:
            bits.append(words)
        return " · ".join(bits), links

    def credit_rows(self) -> tuple:
        """The block that sits under the last line: who wrote the song, where
        this copy came from, and who timed it -- in that order.

        Two lists, the second one the shape of the first: for each row, the
        stretches of it that are links and where they lead. Empty for every
        row that has none, which is most of them. What is linked is what the
        sources asked to have linked -- a Spicy Lyrics contributor's own page,
        and Unison's address, which was already written out in full here and
        is now worth clicking as well as reading.
        """
        doc = SL.payload(self.body or {})
        if not doc or not self.raw:
            return [], []
        out, links = [], []

        def row(text: str, hot=()) -> None:
            out.append(text)
            links.append(list(hot))

        writers = [str(w).strip() for w in (doc.get("SongWriters") or [])
                   if str(w).strip()]
        if writers:
            row(", ".join(writers))
        src = self.source_name(doc)
        unison = [(LS.UNISON_BASE, LS.UNISON_BASE)]
        if str(doc.get("_source") or "") == "unison":
            row(LS.UNISON_CREDIT, unison)
        elif src and src != "—":
            row(src)
            if str(doc.get("_via") or "").startswith(LS.BASE_WORDS["unison"]):
                row(LS.UNISON_CREDIT, unison)
        got = getattr(self, "fetcher", None)
        why = got.masks_kept(self.clock.tid) if got is not None else ""
        if why and not why.startswith(LS.COMMUNITY_SYNC):
            row(f"Masked words kept · {why}")
        made, who = self.made_by_linked(doc)
        if made:
            row(made, who)
        return out, links

    def src_on(self, name: str) -> bool:
        """Whether a source is switched on."""
        return bool(getattr(self, SRC_ATTR[name], False))

    def blend_on(self, name: str) -> bool:
        """Whether a blend is switched on. Its donors still have to be too."""
        return bool(getattr(self, BLEND_KEY[name], False))

    def roster(self) -> LS.Roster:
        """Whose syncs to refuse and whose to prefer, as the chain wants it.

        Built fresh rather than kept, for the same reason source_order() is:
        both lists can change under a menu row or a key while a walk is out,
        and the walk that has already been handed one is the walk that should
        finish under it.
        """
        return LS.Roster(self.people_skip, self.people_pick)

    def this_sync_by(self) -> dict | None:
        """Whoever timed the document on screen, as a roster entry, or None.

        The MAKER, where the document names one, and the uploader only where
        it does not: credits_of() puts them in that order for the same reason
        made_by prints them in it, and refusing the person who passed a sync
        on when the sync is somebody else's work is not what was meant.
        """
        # Through person_list, which keeps the name and the id and drops the
        # rest: a credit also carries the page it links to (see
        # made_by_linked), and that belongs under the lyrics rather than in
        # one of these two lists or in the settings file they are written to.
        return next(iter(LS.person_list(LS.credits_of(self.body))), None)

    def on_people(self, key: str, who) -> bool:
        """Whether that person is already on one of the two lists."""
        return any(LS.same_person(p, who) for p in getattr(self, key))

    def judge_sync(self, prefer: bool) -> None:
        """Refuse or prefer whoever timed the document on screen.

        The credit line under the lyrics is where anybody forms this opinion
        -- you read a name, and you know whether their syncs have been good --
        so the two lists can be written from there without typing it out and
        without spelling it the way the settings file wants. It is also the
        only route by which a Spicy Lyrics id ever reaches the lists: the
        document has it, the credit line does not print it, and nobody could
        type it. Written from here, the entry goes on meaning this person
        after they rename themselves; typed into the settings row, it means
        whoever is called that today. See LS.same_person.

        Pressing it again on somebody who is already on the list takes them
        off, because there is nowhere else to undo this from with the
        document in front of you.
        """
        who = self.this_sync_by()
        if not who or not (who.get("name") or who.get("id")):
            self.toast("this document does not say who timed it")
            return
        key = "people_pick" if prefer else "people_skip"
        got = [p for p in getattr(self, key) if not LS.same_person(p, who)]
        if len(got) == len(getattr(self, key)):
            got.append(who)
        self.set_people(key, got)

    def judge_label(self) -> str:
        """What the button inside the two list boxes says right now.

        A button in a box that is being TYPED IN answers to what is in the
        box, not to what is saved -- press it, see the name arrive in the
        line, press it again and see it go. So it reads off the field.
        """
        who = self.this_sync_by()
        name = str((who or {}).get("name") or "").strip()
        if not who or not name:
            return ""
        listed = any(LS.same_person(p, who)
                     for p in LS.person_list(self.edit_text))
        if listed:
            return f"Remove {name}"
        return ("Prefer this sync" if self.edit_mode == "people_pick"
                else "Refuse this sync")

    def judge_into_edit(self) -> None:
        """This sync's maker into the line being typed, or out of it again.

        The one thing typing cannot do, which is why the button is here and
        not only on the K keys: a Spicy Lyrics id is in the document and is
        printed nowhere, so a name reaching the list this way brings the id
        with it and goes on meaning this person after they rename themselves.
        The ids ride in `edit_ids` until the box is saved -- the line itself
        is names, because a line of ids is not something anybody can read.
        """
        who = self.this_sync_by()
        name = str((who or {}).get("name") or "").strip()
        if not who or not name:
            self.toast("this document does not say who timed it")
            return
        was = LS.person_list(self.edit_text)
        got = [p for p in was if not LS.same_person(p, who)]
        if len(got) == len(was):
            got.append(who)
            self.edit_ids = [p for p in self.edit_ids
                             if not LS.same_person(p, who)] + [who]
        self.edit_text = ", ".join(LS.name_list(got))
        self.edit_pristine = False
        self.said_clipped(self.edit_field)

    def set_people(self, key: str, names, knew=()) -> None:
        """Write one of the two lists and act on it now, not next track.

        The song on screen is the one the user is making this decision ABOUT
        -- they have just read a name under the lyrics and had an opinion
        about it -- so the ask goes out again straight away. It is not a
        second walk in practice: the chain's stored answer is keyed by the
        roster it was picked under (see LS._store), so this re-walk is the
        first ask of a question that has just changed, and every other track's
        answer is still on the disk where it was.

        Whatever ids the old list had are carried onto the new one, because
        the settings row hands this a line of typed text and typed text has
        no ids in it -- see LS.with_ids. Fixing a spelling should not quietly
        turn a refusal that follows somebody through a rename into one that
        does not.
        """
        setattr(self, key, LS.with_ids(names, list(knew) + list(getattr(self, key))))
        other = "people_pick" if key == "people_skip" else "people_skip"
        keep = [p for p in getattr(self, other)
                if not any(LS.same_person(p, q) for q in getattr(self, key))]
        setattr(self, other, keep)
        held = getattr(self, key)
        got = LS.name_list(held)
        word = "refusing" if key == "people_skip" else "preferring"
        self.toast(f"{word} {', '.join(got)}" if got
                   else f"{word} {len(held)} unnamed" if held
                   else f"{word} nobody" if key == "people_skip"
                   else "no preferred names left")
        if self.clock.tid:
            self.reset_track("Reloading…", keep=True)

    def sources(self) -> set:
        """Fallback providers that are switched on."""
        return set(self.source_order())

    def source_order(self) -> list:
        """The providers to consult, in the order the SOURCES were ranked.

        The chain below still speaks in providers, and it has more of them
        than there are sources: two doors on Apple Music, and four blends that
        put Apple's words on somebody else's clock. Each source expands to the
        providers that answer for it, in its own place in the order, so moving
        Apple Music up the list moves everything that speaks for Apple Music
        with it.

        Each blend goes in immediately above the highest-ranked source it
        borrows from -- Apple+NetEase above NetEase, Apple+Kugou above Kugou
        -- rather than up at Apple Music's own slot, which is where they sat
        before. A blend is two sources' work and has no claim on a place in
        front of a third that lent it nothing; where it really is the better
        document it still wins, because quality outranks order. Among
        themselves they follow the donors' ranking, which is what the Blends
        section is showing.
        """
        return LS.provider_order(self.src_order, self.src_on, self.blend_on)

    def fetch_ahead_scan(self) -> None:
        """Look the next few queued tracks up before they are reached.

        The bet is that a track thirty seconds away can be fetched now, for nothing, instead of being
        waited on at the moment it starts. The chain is ten providers wide and
        a cold song takes seconds to walk, which is the "Loading lyrics…" the
        first bars of a song are read through.

        Handed over whole every time rather than added to. The queue is re-read
        every minute and after every track change, and the user reorders it:
        what was coming up a minute ago is no evidence about what is coming up
        now, and warming it would spend requests on a song nobody will hear.
        """
        want = []
        for item in (self.queue_items or [])[:max(0, int(self.fetch_ahead))]:
            uri = str(item.get("uri") or "")
            if not uri.startswith("spotify:track:"):
                continue
            want.append((uri.rsplit(":", 1)[-1], {
                "title": item.get("name") or "", "artist": item.get("sub") or "",
                "album": item.get("album") or "",
                "length": float(item.get("ms") or 0) / 1000.0}))
        self.fetcher.request_ahead(want, self.sources(), self.source_order(),
                                   self.roster())

    def on_source_trouble(self, tid: str, bad) -> None:
        """A source that could not be reached, said once and then left alone.

        Only for the track on screen. The look-ahead walks other songs on a
        thread of its own, and a toast about one of those would be about a
        song the user cannot see and has not asked for yet.

        And once per source, not once per song. A host that is down is down
        for every track, so what was meant as "you are not getting what you
        ranked second, and here is why" arrived on every song change instead
        -- which is how a single unreachable source became a notification
        that would not stop. It is worth repeating only if it is still true
        much later, hence the hour: long enough not to nag, short enough
        that an outage which outlives a listening session says so again.
        """
        if tid != self.clock.tid:
            return
        said = unreached(bad)
        if not said:
            return
        now = mono()
        self._trouble_said = {k: v for k, v in self._trouble_said.items()
                              if now - v < TROUBLE_QUIET}
        if said in self._trouble_said:
            return
        self._trouble_said[said] = now
        self.toast(f"could not reach {said}")

    def searched(self) -> bool:
        """Whether the chain has finished looking for THIS song and found none.

        `done` is the fetcher saying it has been all the way round for a
        track, which `on_lyrics` already reads the same way.

        It is asked because a screen with no words on it used to re-ask on
        every poll -- and the poll runs at POLL_MS_EDGE precisely because
        there are no words, so a song nobody has a lyric for was asking
        sixteen times a second, for as long as it played. The fetcher's own
        backoff kept that from being sixteen WALKS a second, but every one of
        them still woke its loop, and the walks that did get through knocked
        on every door again, the slowest of them included. What that
        looks like from the front is the screen going back to looking for
        lyrics over and over on a song that has none.

        Nothing is given up by stopping. The retry that matters is the
        fetcher's, which still runs and backs off properly (RETRY_MAX). This
        is only the window asking the same question again before the answer
        to the last one has changed.
        """
        return bool(self.clock.tid) and self.fetcher.done == self.clock.tid

    def reload_lyrics(self) -> None:
        self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                             self.source_order(), self.ne_graft,
                             self.fold_adlibs, self.uncensor, self.roster())

    def fetch_meta(self) -> dict:
        """What the name-based providers need to find the song.

        The length is the RECORDING's where a catalogue has said what that is,
        and the player's otherwise. They are not the same number off a
        browser: an upload runs a few seconds longer than the release it is
        of, and those few seconds are load-bearing here. Every provider
        weighs the duration, and measured on Conro's "Thrill of It" -- 200.4s
        released, 206 as uploaded -- the five-second difference dropped the
        song out of NetEase's "near" and let a stranger's song of the same
        name, a second closer to the upload, outrank it. Nothing about what
        is DRAWN uses this: the progress bar belongs to the audio actually
        playing, which is the upload. See on_card.
        """
        m = self.clock.meta
        return {"title": m.get("title", ""), "artist": self.artist(),
                "album": m.get("album", ""),
                "length": self.card_len.get(self.clock.tid or "",
                                            m.get("length", 0.0)),
                "explicit": m.get("explicit")}

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

    def focus_line(self, pos: float) -> int:
        """The line the song is ON at `pos`, as opposed to everything audible.

        sounding() answers a different question -- it hands back every line
        covering `pos`, which is what the stack needs, because it draws all of
        them. A renderer that draws ONE line has to choose, and the choice is
        not "the first of them": a line whose end has been stretched over the
        ad-lib written into it goes on covering `pos` for as long as that
        ad-lib lasts, which on a chorus with a tail is well into the line
        after it. Taking the first live line there kept the view on a line
        whose words were finished while the next one sang.

        The same answer the scroll uses, so a pinned renderer and the stack
        agree about where the song is -- but with no scroll-ahead, since
        nothing here is moving and there is nothing to be early for.
        """
        return SL.focus_index(self.lines, pos, 0.0)

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

    def troll_aim(self, idx: int) -> int:
        """Which line the column scrolls to for the one being sung.

        The song is drawn at the real time throughout -- the right line is
        lit, and it fills word by word exactly as it would with this off. All
        that is wrong is where the COLUMN has stopped: the reading band holds
        the line above or below, so the words being sung sit a row out of
        place and the line you are reading at is one nobody is singing.

        That is the off-by-one worth having. Lying to the clock instead lights
        the wrong line and fills THAT, which is a different fault and reads as
        a broken document rather than as a view that has miscounted -- and it
        would put the lie in front of the seek, the measurement and the
        clipboard, none of which have anything to do with scrolling.

        Re-rolled when the column moves to a new line, because a skew that
        changed mid-line would be seen as a jump. Once it has gone wrong it
        tends to STAY wrong -- a real off-by-one does not fix itself every
        other line -- so a skew already running is kept more often than one is
        started, with the stickiness a floor under the knob and never a cap on
        it: a knob turned past it is asking for more wrongness, not less.
        """
        lines = self.lines
        if idx < 0 or not lines or self.off_by_one <= 0:
            self.troll_skew, self.troll_at = 0, None
            return idx
        at = (idx, lines[idx].get("start") if idx < len(lines) else None)
        if at != self.troll_at:
            self.troll_at = at
            keep = self.off_by_one
            if self.troll_skew:
                keep = max(keep, 0.62)
            if random.random() >= min(0.95, keep):
                self.troll_skew = 0
            else:
                want = [-1, 1]
                random.shuffle(want)
                if self.troll_skew and random.random() < 0.75:
                    want.insert(0, self.troll_skew)
                self.troll_skew = next(
                    (d for d in want if 0 <= idx + d < len(lines)), 0)
        j = idx + self.troll_skew
        return j if 0 <= j < len(lines) else idx

    def searching_now(self) -> bool:
        """Whether the column is currently hunting for the lyrics.

        Bouts come at random and end on their own. The knob sets how often
        and how long: at 1.0 there is six to twenty seconds of ordinary
        scrolling between them and each one runs three or four, which came
        out at a bout every seventeen seconds over a hundred seconds of
        frames; at 3.0 the gaps are a third as long and the bouts twice as
        long, and it spends more of the song hunting than following it.

        Nothing starts while the reader is scrolling by hand -- being fought
        for the scrollbar is a different feeling from watching the app lose
        its place, and only one of them is funny -- and nothing starts under a
        pinned renderer, which has no scroll to lose.
        """
        if (self.searching <= 0 or not self.lines or not self.synced
                or not self.render.scrolls):
            self.search_until = self.search_next = 0.0
            return False
        now = mono()
        if now < self.user_scroll_until:
            self.search_until = 0.0
            self.search_next = now + 4.0
            return False
        if now < self.search_until:
            return True
        if not self.search_next:
            self.search_next = now + random.uniform(6.0, 20.0) / self.searching
            return False
        if now < self.search_next:
            return False
        self.search_next = 0.0
        self.search_until = now + random.uniform(3.0, 4.0 + 2.5 * self.searching)
        self.search_goal = self.scroll_target
        self.search_at = 0.0
        return True

    def _search_leg(self) -> None:
        """Somewhere else to look, and the pace it is gone after at.

        The places are over the WHOLE lyric, not around wherever the bout
        happened to start, and each one is across the middle of the document
        from where the column is now, so a leg is the length of the song and
        not a nudge. One in four ignores that and lands anywhere, because a
        hunt that alternates perfectly is a pattern and a pattern looks
        deliberate.

        The pace is measured in windows a second rather than in pixels, so it
        means the same thing on a laptop panel and on a television: three to
        seven of them, and half as many again at the top of the knob. Nothing
        can be read at that speed, which is the point.
        """
        H = max(1.0, float(self.height()))
        lo = -H * 0.25
        hi = max(lo + H * 0.5, self.content_h - H * 0.30)
        mid = (lo + hi) / 2
        if random.random() < 0.75:
            a, b = (lo, mid) if self.scroll_target > mid else (mid, hi)
        else:
            a, b = lo, hi
        self.search_goal = random.uniform(a, b)
        self.search_speed = H * random.uniform(3.0, 7.0) * (0.75 + 0.25 * self.searching)

    def troll_search(self) -> float:
        """Travel between the places, without ever stopping at one.

        Somewhere to look is picked the way a hunt picks: a long way off,
        usually the other side of the song. What the column does about it is
        SCROLL there -- at a few windows a second, continuously, the words
        going past too fast to read -- and the moment it arrives it is already
        leaving for the next place at a fresh pace. It never comes to rest
        between legs, so a bout is one unbroken run up and down the lyric
        rather than a series of stops.

        Driven as a velocity rather than as a destination for exactly that
        reason: an eased approach decelerates into every place it looks, and a
        column that keeps slowing down and setting off again reads as a series
        of decisions. tick() leaves the ease nearly off underneath this, or
        the lag would put a curve back on both ends of every leg.
        """
        now = mono()
        dt = min(0.05, now - self.search_at) if self.search_at else 0.016
        self.search_at = now
        if not self.search_speed:
            self._search_leg()
        step = self.search_speed * dt
        for _ in range(8):
            left = self.search_goal - self.scroll_target
            if self.search_speed and step < abs(left):
                break
            self.scroll_target = self.search_goal
            step = max(0.0, step - abs(left))
            self._search_leg()
        left = self.search_goal - self.scroll_target
        if left:
            self.scroll_target += math.copysign(min(step, abs(left)), left)
        return self.scroll_target

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
                and mono() - self.track_at > SETTLE)

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

    def panel_x(self) -> float:
        """The panel's left edge. 0 unless it has been sent to the other side.

        Everything in the panel is laid out from this rather than from the
        window, so switching sides is one number and not a second layout: the
        cover, the title block, the progress bar and the volume slider all
        keep the arithmetic they had.

        A panel filling the whole window -- which is what an instrumental
        gets -- starts at 0 whichever side it is nominally on, and falls out
        of the same subtraction.
        """
        panel = self.panel_width()
        return self.width() - panel if panel and self.art_side == "right" else 0.0

    def _lyr_x(self) -> float:
        """The lyric column's left edge: the panel where the panel is in the
        way, and the plain margin where it is not."""
        panel = self.panel_width()
        if panel and self.art_side != "right":
            return panel
        return self.margin()

    def _lyr_width(self) -> float:
        panel = self.panel_width()
        other = panel if panel and self.art_side == "right" else self.margin()
        return self.width() - self._lyr_x() - other

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
        return stamp_rows(wrap_shape(pieces, fm, width, align), pieces)

    def line_ink(self, ln: dict):
        """Everything about a line that changes the glyphs, and nothing else.

        Deliberately no times. The cached pixmap is the un-sung text; when it
        is sung is decided every frame by the painter reading the line itself,
        so a line re-timed to the millisecond draws the identical picture.

        Deliberately no line number either -- see line_pixmap.

        Kept on the line, because line_pixmap asks for this before it can look
        anything up and it is asked twice per visible line per frame -- once
        for each of the two blur levels a line is blitted at. What it builds is
        a tuple per syllable, and a long song has eleven thousand of them.

        The three things it depends on that are not the line itself are all in
        the memo's own key: which script is being laid out, whether the
        readings are drawn, and a counter that moves when a romanisation is
        corrected in place. Everything else about a line is settled before it
        is ever painted -- `prepare` writes the pieces and the duet flags
        arrive with the document.
        """
        key = (self.roman, self.furigana, self._ink_gen)
        got = ln.get("_ink")
        if got is not None and got[0] == key:
            return got[1]
        out = self._line_ink(ln)
        ln["_ink"] = (key, out)
        return out

    def _line_ink(self, ln: dict):
        if ln.get("dots"):
            return ("dots",)
        if ln.get("credits"):
            return ("credits", tuple(ln["credits"]),
                    tuple(tuple(row) for row in (ln.get("credit_links") or ())),
                    bool(ln.get("opposite")))
        return (tuple((pc[2], bool(pc[3])) for pc in self.line_pieces(ln)),
                tuple((pc[2], bool(pc[3]))
                      for pc in (ln.get("pieces_roman") or ())),
                bool(ln.get("background")), bool(ln.get("opposite")),
                bool(self.furigana))

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
        fm = self.lyric_fm(ln["background"])
        if ln.get("dots"):
            out = ([], fm, fm.height() * 1.35, [], None, [], None)
            self.layout_cache[key] = out
            return out
        if ln.get("credits"):
            cfm = QFontMetricsF(self.credit_font())
            rows = [(n, r) for n, row in enumerate(ln["credits"])
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
        """Readings placed over the characters they belong to, row by row.

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
            ann = SL.ruby(frags, self.japanese)
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
            edge = (row[-1][0] + row[-1][1]) if row else 0.0
            out.append(_spread(marks, rufm, edge))
        return out, rufm

    def roman_font(self, ln: dict) -> QFont:
        f = QFont(self.family, int(self.lyric_px() * (0.44 if ln["background"] else 0.60)))
        f.setWeight(QFont.Weight.Bold)
        return f

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
        st[7] = mono()
        return st

    def step_drift(self) -> None:
        """Integrate the loose words. No gravity, so they only ever coast and
        bounce -- nothing accelerates them downward."""
        now = mono()
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
        if not self.showing():
            self.step_drift()
            if self.quit_requested:
                self.quit_requested = False
                self.close()
                QApplication.instance().quit()
                return
            if mono() > self._save_at:
                self._save_at = mono() + 2.0
                self.autosave()
            return
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
        hunting = self.searching_now()
        goal = 1.0 if hunting or mono() < self.user_scroll_until else 0.0
        if abs(self.browse - goal) > 0.004:
            self.browse += (goal - self.browse) * 0.18
            moving = True
        else:
            self.browse = goal

        if live and self.render.scrolls:
            self.focus_idx = SL.focus_index(self.lines, pos, self.scroll_lead)
        elif not live:
            self.focus_idx = -1
        if hunting:
            self.troll_search()
            moving = True
        elif (live and self.render.scrolls
                and mono() > self.user_scroll_until):
            want = self.troll_aim(self.focus_idx)
            for i, top, h, _lo, _hi in self.line_rects:
                if i == want:
                    self.scroll_target = top - self.anchor() + h / 2
                    break
        self.scroll_target = max(
            -self.height() * (0.25 if self.synced else 0.02),
            min(self.scroll_target, max(0.0, self.content_h - self.height() * 0.30)),
        )
        gap = self.scroll_target - self.scroll
        if abs(gap) > 0.4:
            moving = True
        if (abs(gap) > self.height() and self.synced and not hunting
                and mono() > self.user_scroll_until):
            self.scroll = self.scroll_target
        else:
            self.scroll += gap * (0.55 if hunting else 0.12)

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

        if mono() > self._save_at:
            self._save_at = mono() + 2.0
            self.autosave()

        if self.isFullScreen() and mono() - self.last_move > 2.5:
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
                    or mono() - self.last_move < 1.0
                    or self.bq_busy or self.backfill_total):
                moving = True

        if self.view == "review":
            if abs(self.review_scroll_target - self.review_scroll) > 0.4:
                self.review_scroll += (self.review_scroll_target
                                       - self.review_scroll) * 0.25
                moving = True
            else:
                self.review_scroll = self.review_scroll_target

        if self.step_viz_mix() or self.scene_prev() is not None:
            moving = True

        self.flush_volume()

        busy = (moving or self.clock.status == "Playing" or self._marq_live
                or self.vol_want is not None
                or bool(self.motion_art and self.motion_frames)
                or self.toast_until > mono()
                or (self.clouds > 0 and self.view == "lyrics" and bool(self.lines))
                or (self.view == "lyrics" and self.render.animating()))
        self._idle_frames = 0 if busy else self._idle_frames + 1
        if busy or self._idle_frames % max(1, round(self.eff_hz / 10)) == 0:
            self.update()

    def drop_pixmaps(self) -> None:
        """Let go of every drawn line and every glow.

        This is about MEMORY, not about correctness. Both keys say everything
        about the picture they stand for -- the ink, the width, the blur, the
        size, the alignment, the script and the font -- so nothing here is
        ever needed to stop a stale picture being drawn. A key that no longer
        matches is simply never asked for again and falls off the cold end of
        its own budget.

        That is why the invalidations went away. They were the stall: a
        better source arriving mid-song threw away every drawn line in the
        column and paid 26ms on the frame it landed and 48ms over the six
        after it, for pictures it almost always still wanted -- a better
        answer is usually the same WORDS with a better clock under them, and
        the clock is not in this picture.

        What is left is the honest case: a different track. The old song's
        lines will never be asked for again, and there is no reason to hold
        a hundred megabytes of them until the budget notices.
        """
        self.pix_cache.clear()
        self.glow_cache.clear()
        self._pix_bytes = self._glow_bytes = 0

    def line_pixmap(self, idx: int, width: float, blur: int,
                    pen: QColor | None = None) -> QPixmap:
        pen = self.base_color(self.lines[idx]) if pen is None else pen
        key = (self.line_ink(self.lines[idx]), int(width), blur,
               int(self.lyric_px()), self.align, self.roman, pen.rgb(),
               self.lyric_font_key())
        hit = self.pix_cache.get(key)
        if hit is not None:
            self.pix_cache.move_to_end(key)
            return hit
        if self._pix_left <= 0:
            near = self._nearest_blur(key, blur)
            if near is not None:
                return near
            if self._new_left <= 0:
                return None
            self._new_left -= 1
        rows, fm, h, rrows, rfm, ruby, rufm = self.layout_line(idx, width)
        pad = 10 + blur * 6
        pm = QPixmap(int(width + pad * 2), int(h + pad * 2))
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self.lyric_font(self.lines[idx]["background"]))
        p.setPen(pen)
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
        self._pix_left -= 1
        self.pix_cache[key] = pm
        self._pix_bytes += _pm_bytes(pm)
        while self._pix_bytes > PIX_BUDGET and len(self.pix_cache) > 1:
            _old, gone = self.pix_cache.popitem(last=False)
            self._pix_bytes -= _pm_bytes(gone)
        return pm

    def _nearest_blur(self, key: tuple, blur: int):
        """The same line at the closest blur already in hand, or None.

        The key carries the blur at a known place and everything else about
        the picture -- the words, the width, the type, the pen -- so the
        family of levels for one line is reached by swapping that one field
        rather than by keeping a second index beside the cache. Ten probes of
        a dict is nothing next to building a picture, which is the thing being
        avoided.

        Searched outwards from the level actually wanted, so the substitute is
        the least wrong one available.
        """
        for step in range(1, RD.MAX_BLUR + 1):
            for cand in (blur - step, blur + step):
                if 0 <= cand <= RD.MAX_BLUR:
                    hit = self.pix_cache.get(key[:2] + (cand,) + key[3:])
                    if hit is not None:
                        self.pix_cache.move_to_end(key[:2] + (cand,) + key[3:])
                        return hit
        return None

    def glow_pixmap(self, txt: str, font: QFont, radius: int) -> QPixmap:
        """Soft halo for the syllable being sung right now."""
        key = (txt, font.toString(), radius)
        hit = self.glow_cache.get(key)
        if hit is not None:
            self.glow_cache.move_to_end(key)
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
        self.glow_cache[key] = pm
        self._glow_bytes += _pm_bytes(pm)
        while self._glow_bytes > GLOW_BUDGET and len(self.glow_cache) > 1:
            _old, gone = self.glow_cache.popitem(last=False)
            self._glow_bytes -= _pm_bytes(gone)
        return pm

    def glow_layer(self) -> QPixmap:
        """Accent wash over the cover, cached -- rasterising radial gradients
        every frame was the single most expensive thing in paintEvent.

        Scaled by how bright the cover is, which is not the same question as
        what colour it is. The palette is built by throwing the black pixels
        away, so femtanyl's BODY THE PISTOL -- a near-black square with a
        white-hot burst in the middle of it -- hands back a vivid ochre, and
        the wash then lit the window to a brightness the cover never reaches:
        measured off the screen, patches of background at 0.25 and 0.33
        against a cover averaging 0.205. A dark cover now gets a wash in
        proportion, down to a fifth of it, and a bright one is untouched.
        """
        W, H = self.width(), self.height()
        lift = min(1.0, max(GLOW_FLOOR, self.art_luma / GLOW_FULL))
        key = (W, H, tuple(c.rgb() for c in self.palette), self._section,
               round(lift, 2))
        if key == self._glow_key and self._glow_pm is not None:
            return self._glow_pm
        pm = QPixmap(W, H)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        spots = ((0.72, 0.30, 0.85, 100), (0.16, 0.86, 0.66, 58), (0.86, 0.80, 0.55, 44))
        for i, (cx, cy, rad, alpha) in enumerate(spots):
            a = self.palette[(i + self._section) % len(self.palette)]
            alpha = int(round(alpha * lift))
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
        now = mono()
        t = now * 0.06 * self.bg_motion
        key = (W, H, tuple(c.rgb() for c in self.palette), self.art_gen,
               self.bg_mode, round(self.bg_dim, 2), round(self.bg_motion, 2),
               self._section, self.viz_live(), self.viz_mode,
               self.mesh_style, round(self.mesh_tint, 2),
               round(self.mesh_spread, 2), int(self.mesh_colors))
        assert key[VIZ_IN_KEY] is self.viz_live(), "VIZ_IN_KEY is out of step"
        fresh = 1 / 15 if self.bg_motion else 1.0
        if self._scene_pm is not None and key == self._scene_key and now - self._scene_at < fresh:
            return self._scene_pm
        if (self.bg_fade > 0 and self._scene_pm is not None
                and self._scene_key is not None and key != self._scene_key
                and (W, H) == (self._scene_pm.width(), self._scene_pm.height())):
            self._scene_old, self._scene_from = self._scene_pm, now
            old_key = self._scene_key
            self._scene_viz = (
                key[VIZ_IN_KEY] if len(key) == len(old_key)
                and all(a == b for i, (a, b) in enumerate(zip(key, old_key))
                        if i != VIZ_IN_KEY) else None)
        pm = QPixmap(W, H)
        p = QPainter(pm)
        p.fillRect(0, 0, W, H, QColor(9, 9, 12))
        if self.bg_mode == "mesh" and not (
                self.viz_live() and self.viz_mode == "bloom"
                and self.mesh_style == "blobs"):
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

    def _paint_scene(self, p, dst: QRectF, W: int, H: int) -> None:
        """The wall, with the one it is replacing still under it if it is
        mid-change.

        Both are opaque and both cover the window, so the outgoing one is laid
        down whole and the incoming one painted over it at the mix. No third
        buffer, and the frames either side of a fade cost exactly what they
        cost before.
        """
        pm = self.scene_layer()
        mix = self.scene_mix()
        old = self.scene_prev()
        if old is not None and mix < 1.0:
            p.drawPixmap(dst, old, QRectF(0, 0, W, H))
            p.setOpacity(mix)
            p.drawPixmap(dst, pm, QRectF(0, 0, W, H))
            p.setOpacity(1.0)
            return
        p.drawPixmap(dst, pm, QRectF(0, 0, W, H))

    def step_viz_mix(self) -> bool:
        """Move the visualizer's fade on by one frame. True while it moves.

        The visualizer arriving is the change nobody asked for and everybody
        sees: the analysis lands mid-song and a lit wall replaces a still one
        between two frames. This is what gives it the same `bg_fade` a change
        of cover gets.

        Stepped here rather than in the painter so it takes bg_fade whatever
        the window happens to be drawing at, and so that a fade in progress is
        itself a reason to keep drawing -- see `busy` in tick(), without which
        a paused song would walk through it at the idle ten frames a second.
        """
        goal = 1.0 if self.viz_live() else 0.0
        if self.bg_fade <= 0:
            self._viz_mix = goal
            return False
        if self._viz_mix == goal:
            return False
        step = (1.0 / max(1.0, self.eff_hz)) / self.bg_fade
        if abs(goal - self._viz_mix) <= step:
            self._viz_mix = goal
        else:
            self._viz_mix += step if goal > self._viz_mix else -step
        return True

    def viz_face(self, W: int, H: int):
        """The visualizer as it should be drawn, or None when there is none.

        Held back a frame's worth of nothing: `viz_live` turns false the
        instant a track change drops the analysis, and the layer built without
        one is an empty picture rather than the last full one. So the last
        picture is kept and handed back while the mix runs down, which is what
        makes the way out a fade rather than a cut to the still wall.
        """
        if self.viz_live():
            self._viz_last = self.viz_layer(W, H)
        elif self._viz_last is not None and self._viz_mix <= 0.004:
            self._viz_last = None
        got = self._viz_last
        if got is None:
            return None
        d = self.VIZ_DIVS.get(self.viz_mode, self.VIZ_DIV)
        if (got.width(), got.height()) != (max(1, W // d), max(1, H // d)):
            return None
        return got

    def scene_mix(self) -> float:
        """How far the wall has changed into the new one, 0 to 1.

        1 means there is nothing to fade and the caller can just draw the
        current one, which is the answer on all but the second or so after a
        change. The outgoing picture is dropped here rather than in the
        painter, so nothing holds a window's worth of pixels once it is done.
        """
        if self._scene_old is None:
            return 1.0
        if self.bg_fade <= 0:
            self._scene_old = None
            self._scene_viz = None
            return 1.0
        if self._scene_viz is not None:
            k = self._viz_mix if self._scene_viz else 1.0 - self._viz_mix
            if k >= 1.0:
                self._scene_old = None
                self._scene_viz = None
                return 1.0
            return max(0.0, k)
        k = (mono() - self._scene_from) / self.bg_fade
        if k >= 1.0:
            self._scene_old = None
            return 1.0
        k = max(0.0, k)
        return k * k * (3.0 - 2.0 * k)

    def scene_prev(self) -> QPixmap | None:
        """The wall being faded out of, while there is one."""
        return self._scene_old

    VIZ_DIV = 3
    VIZ_DIVS = {"bloom": 3, "tide": 3, "pulse": 2, "bars": 1}
    VIZ_ALPHA = 124
    VIZ_SAT = 0.52
    VIZ_NEEDS = {"bloom": "pitch", "bars": "pitch", "pulse": "beats", "tide": "segs"}

    def viz_live(self) -> bool:
        """Whether there is anything to draw. Turning the visualizer on for a
        track Spotify never analysed has to leave the background it was laid
        over exactly as it was, not blank it."""
        need = self.VIZ_NEEDS.get(self.viz_mode, "pitch")
        return bool(self.viz and self.palette and getattr(self.beat, need))

    @staticmethod
    def _ease(cur: float, goal: float, dt: float, up: float, down: float) -> float:
        """One pole towards `goal`, faster up than down.

        Every reading the visualizer takes is a step function -- a segment
        holds one loudness for a quarter-second and then jumps -- so nothing
        off the analysis reaches the window without passing through here.
        """
        tau = up if goal > cur else down
        return cur + (goal - cur) * (1.0 - math.exp(-dt / tau))

    def viz_level(self) -> float:
        """Loudness, eased. What every mode sizes its light by."""
        return self._viz_lvl

    def viz_kick(self) -> float:
        """The beat, eased. Still an attack, but one with a frame or two of
        rise in it rather than a vertical edge."""
        return self._viz_kick

    def viz_bands(self, dt: float) -> list[float]:
        """Everything the modes read, eased: up almost at once, down over
        about a third of a second.

        Segments run a quarter-second or so, so reading any of this raw makes
        the background step from segment to segment instead of moving -- and
        loudness raw is worse than chroma raw, because it scales the light on
        the whole window at once and so steps the whole window at once. The
        attack stays near-instant because a swell arriving late is the one
        error the eye reliably catches; it is the slow release that turns a
        sequence of discrete readings into something continuous.

        The gate is what keeps a rapped verse from thrashing. Where `voiced`
        says the twelve are carrying no chord, they are replaced by the
        loudness rather than merely flattened: a chroma vector arrives
        normalised to its own peak, so its mean on unpitched material sits
        near the top of the scale, and flattening alone pins every blob wide
        open for the whole verse. Loudness is what that material actually has
        to say. Nothing is lost where the vector IS pitched: there the gate is
        fully open and the shape arrives untouched.
        """
        pos = self.position()
        want = self.beat.chroma(pos)
        self._viz_lvl = self._ease(self._viz_lvl, self.beat.level(pos), dt, 0.09, 0.38)
        self._viz_kick = self._ease(self._viz_kick, self.beat.energy(pos),
                                    dt, 0.035, 0.16)
        goal_tone = self.beat.voiced(pos) if want else self._viz_tone
        self._viz_tone = self._ease(self._viz_tone, goal_tone, dt, 0.60, 0.60)
        if want:
            tone = self._viz_tone
            want = [tone * v + (1.0 - tone) * self._viz_lvl for v in want]
        for i in range(12):
            goal = want[i] if i < len(want) else 0.0
            self._viz_ch[i] = self._ease(self._viz_ch[i], goal, dt, 0.045, 0.320)
        return self._viz_ch

    def _viz_tint(self, c: QColor, i: int, n: int) -> QColor:
        """The palette colour, brought up to something that shows on the wall.

        A cover whose colours are all weak gives blobs that read as a smudge
        rather than as anything answering the music -- which is most of what
        "the visualizer is hard to see" turns out to mean in practice. So a
        colour under the floor is saturated up to it. Only those: a cover with
        real colour in it still shows its own and nothing else.

        A TRUE GREY IS LEFT GREY. It reports no hue at all, and the only way to
        saturate something with no hue is to invent one -- which this used to
        do, spreading the blobs around the wheel from 0.58 by position. What
        that meant in the window: a grey cover lit up blue, and a cover the
        window drew grey all the way through until the visualizer arrived
        changed colour when it did. The brightness floor still applies, so the
        blobs are still something rather than nothing; they tell apart from
        each other by size and by light, which is what the modes vary anyway.
        """
        if not self.VIZ_SAT:
            return c
        h, sat, v, a = c.getHsvF()
        if sat >= self.VIZ_SAT and v >= 0.45:
            return c
        if h < 0:
            return QColor.fromHsvF(0.0, 0.0, max(v, 0.58), a)
        return QColor.fromHsvF(h, max(sat, self.VIZ_SAT), max(v, 0.58), a)

    def viz_tints(self) -> list[QColor]:
        """The palette every mode paints in, each colour brought up to the
        floor -- and a grey one left where it is."""
        n = len(self.palette)
        return [self._viz_tint(c, i, n) for i, c in enumerate(self.palette)]

    def _viz_a(self, f: float) -> int:
        """An alpha from a 0..1 weight, scaled by strength and kept in range.

        Strength runs past 1.0, so every alpha here has to be clamped rather
        than trusted -- Qt reads a QColor alpha of 300 as 44 and the brightest
        blob in the frame turns into the faintest one.
        """
        return max(0, min(255, int(self.VIZ_ALPHA * f * self.viz)))

    def viz_clock(self, now: float) -> float:
        """Drift time for the modes that drift.

        A fast song should move faster, but only somewhat -- taking tempo
        straight would have a 170bpm track tearing across the window.
        """
        tempo = self.beat.tempo or 120.0
        return now * 0.06 * self.bg_motion * (0.55 + 0.45 * tempo / 120.0)

    def viz_layer(self, W: int, H: int) -> QPixmap:
        """The driven layer, in whichever mode is chosen.

        Painted into a reduced pixmap and scaled back up on the way out, by
        the divisor that mode can afford. It brings a per-frame repaint back
        down to about what the cached 15fps scene cost.

        Composited with Plus rather than over, because this lands on top of a
        background that is already finished: adding light to the album wall
        keeps it, while painting over it would punch translucent holes in it.
        """
        now = mono()
        key = (W, H, self.viz, self.viz_mode, self._section)
        if (self.clock.status != "Playing" and self._viz_pm is not None
                and self._viz_key == key):
            return self._viz_pm
        dt = min(0.25, now - self._viz_at) if self._viz_at else 1 / 60.0
        self._viz_at = now
        bands = self.viz_bands(dt)

        d = self.VIZ_DIVS.get(self.viz_mode, self.VIZ_DIV)
        w, h = max(1, W // d), max(1, H // d)
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        paint = {"bloom": self._viz_bloom, "pulse": self._viz_pulse,
                 "bars": self._viz_bars, "tide": self._viz_tide}
        paint.get(self.viz_mode, self._viz_bloom)(p, w, h, bands, now)
        p.end()
        self._viz_key, self._viz_pm = key, pm
        return pm

    def _viz_bloom(self, p, w, h, bands: list[float], now: float) -> None:
        """The mesh, driven: the same drifting blobs, sized by what is sounding.

        The mode for music with chords in it. Each blob owns a slice of the
        twelve, so a chord moves them apart rather than pumping all of them
        together -- which is also why it is the mode with the least to say
        about a track that is mostly drums.
        """
        pos = self.position()
        span = max(w, h)
        n = len(self.palette)
        t = self.viz_clock(now)
        loud = self.viz_level()
        tint = self.viz_tints()
        share = 2.5 / max(2.5, n)
        lifts = []
        for i in range(n):
            lo, hi = i * 12 // n, (i + 1) * 12 // n
            lifts.append(sum(bands[lo:hi]) / max(1, hi - lo))
        reach = max(lifts) - min(lifts)
        if reach > 0.02 and self._viz_tone > 0.35:
            base = min(lifts)
            lifts = [0.5 * v + 0.5 * (0.10 + 0.90 * (v - base) / reach)
                     for v in lifts]
        for i in range(n):
            c = tint[(i + self._section) % n]
            ph = i * 2.399
            lift = lifts[i]
            kick = self.viz_kick() * (1.0 - 0.18 * i)
            cx = w * (0.5 + 0.40 * math.sin(t * 1.9 + ph))
            cy = h * (0.5 + 0.40 * math.cos(t * 1.4 + ph * 1.7))
            rad = span * (0.46 + 0.15 * math.sin(t * 1.1 + ph)) * (
                0.80 + 0.26 * lift + 0.10 * kick)
            a = self._viz_a(share * (0.55 + 0.30 * loud) * (0.70 + 0.30 * lift))
            g = QRadialGradient(cx, cy, max(1.0, rad))
            g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), a))
            g.setColorAt(0.55, QColor(c.red(), c.green(), c.blue(), a // 3))
            g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(0, 0, w, h, QBrush(g))

    VIZ_RING = 1.35

    def _viz_pulse(self, p, w, h, bands: list[float], now: float) -> None:
        """One ring per beat, expanding from the middle and fading out.

        Everything here comes off the metrical grid and nothing off chroma,
        which is the point: on a rapped verse the chroma reader is being handed
        snares and consonants, while the grid is the one part of the analysis
        the music is actually built on. Each ring keeps the colour it was born
        with as it travels, so a bar reads as four rings crossing the window
        rather than as the window flashing four times.
        """
        pos = self.position()
        span = max(w, h) * 0.62
        n = len(self.palette)
        tint = self.viz_tints()
        cx, cy = w * 0.5, h * 0.5
        loud = self.viz_level()
        for i, start, strength in self.beat.recent(pos, self.VIZ_RING):
            age = max(0.0, min(1.0, (pos - start) / self.VIZ_RING))
            a = self._viz_a(1.9 * (1.0 - age) ** 1.7 * strength
                            * (0.45 + 0.55 * loud))
            if a <= 0:
                continue
            c = tint[(i + self._section) % n]
            r = span * (0.05 + 1.15 * age)
            thick = span * (0.04 + 0.13 * age)
            out = r + thick
            body = QColor(c.red(), c.green(), c.blue(), a)
            clear = QColor(c.red(), c.green(), c.blue(), 0)
            g = QRadialGradient(cx, cy, out)
            g.setColorAt(0.0, clear)
            inner = (r - thick) / out
            if inner > 0.02:
                g.setColorAt(inner, clear)
            g.setColorAt(r / out, body)
            g.setColorAt(1.0, clear)
            p.fillRect(0, 0, w, h, QBrush(g))
        core = tint[self._section % n]
        a = self._viz_a(0.35 + 0.60 * self.viz_kick())
        g = QRadialGradient(cx, cy, max(1.0, span * 0.42))
        g.setColorAt(0.0, QColor(core.red(), core.green(), core.blue(), a))
        g.setColorAt(1.0, QColor(core.red(), core.green(), core.blue(), 0))
        p.fillRect(0, 0, w, h, QBrush(g))

    def _viz_bars(self, p, w, h, bands: list[float], now: float) -> None:
        """The twelve pitch classes as a row of columns standing on the floor.

        Ordered around the circle of fifths rather than up the chromatic
        scale, so the classes that sound together stand together: a chord
        lights a neighbourhood of the row instead of scattering across it, and
        a key change slides the lit part sideways. Chromatic order would put a
        triad's three notes four columns apart and show a comb.

        This is the mode that says what the analysis actually holds, so it is
        painted full size and left hard-edged rather than smeared into the
        wall like the others.
        """
        pos = self.position()
        n = len(self.palette)
        tint = self.viz_tints()
        loud = self.viz_level()
        kick = self.viz_kick()
        gap = w / 12.0
        bw = gap * 0.58
        floor = h * 0.97
        for j in range(12):
            cls = (j * 7) % 12
            v = (bands[cls] if cls < len(bands) else 0.0) ** 2
            tall = floor * (0.05 + 0.80 * v * (0.40 + 0.60 * loud) + 0.09 * kick)
            c = tint[(j * n // 12 + self._section) % n]
            a = self._viz_a(0.45 + 0.55 * v)
            g = QLinearGradient(0.0, floor, 0.0, floor - tall)
            g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), a))
            g.setColorAt(0.6, QColor(c.red(), c.green(), c.blue(), a // 2))
            g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(QRectF(gap * j + (gap - bw) / 2, floor - tall, bw, tall),
                       QBrush(g))

    def _viz_tide(self, p, w, h, bands: list[float], now: float) -> None:
        """A horizon that rises with the track: slow water, stacked.

        The calm one. No single beat moves it -- the crest takes its height
        from how loud the moment is and its speed from the tempo, so a dense
        track raises the water instead of strobing it. It is what to reach for
        when the blobs are too busy and the rings are too insistent, and it
        wants nothing from the analysis but loudness, which every analysis has.
        """
        loud = self.viz_level()
        kick = self.viz_kick()
        n = len(self.palette)
        tint = self.viz_tints()
        t = self.viz_clock(now) * 2.6
        for i in range(min(3, n)):
            c = tint[(i + self._section) % n]
            base = h * (0.68 + 0.10 * i)
            amp = h * (0.035 + 0.085 * loud + 0.035 * kick) * (1.0 - 0.22 * i)
            path = QPainterPath()
            path.moveTo(0.0, h)
            steps = 40
            for k in range(steps + 1):
                u = k / steps
                y = base - amp * (math.sin(t * 0.9 + u * 6.1 + i * 1.7)
                                  + 0.5 * math.sin(t * 1.5 - u * 9.7 + i))
                path.lineTo(w * u, y)
            path.lineTo(w, h)
            path.closeSubpath()
            a = self._viz_a(0.20 + 0.30 * loud)
            g = QLinearGradient(0.0, base - amp * 2.0, 0.0, h)
            g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), a))
            g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), max(0, a // 4)))
            p.fillPath(path, QBrush(g))

    def mesh_colours(self) -> list[QColor]:
        """The palette the mesh is allowed to spend, longest-first as always.

        `mesh_colors` is a ceiling and not a promise: a cover that yielded two
        dominant colours has two, whatever the setting says. One is the Genius
        picture -- a single album colour over the whole window -- and taking
        the first N rather than a spread of them is what makes that the
        DOMINANT colour rather than an arbitrary one.
        """
        cols = self.palette or [QColor(90, 90, 100)]
        return cols[:max(1, min(int(self.mesh_colors), len(cols)))]

    def _mesh_a(self, f: float) -> int:
        """An alpha from a 0..1 weight, scaled by strength and clamped.

        Clamped for the reason _viz_a is: strength runs past 1.0 and Qt reads
        a QColor alpha of 300 as 44, so the boldest wash in the window would
        come back the faintest one.
        """
        return max(0, min(255, int(round(255 * f * self.mesh_tint))))

    def _paint_mesh(self, p, W: int, H: int, t: float) -> None:
        """The mesh, in whichever style is chosen. Works with no cover art at
        all, and stays legible where a busy cover does not."""
        {"wash": self._mesh_wash, "veil": self._mesh_veil}.get(
            self.mesh_style, self._mesh_blobs)(p, W, H, t)

    def _mesh_blobs(self, p, W: int, H: int, t: float) -> None:
        """Album-palette blobs drifting on out-of-phase Lissajous paths."""
        span = max(W, H) * self.mesh_spread
        for i, c in enumerate(self.mesh_colours()):
            ph = i * 2.399
            cx = W * (0.5 + 0.40 * math.sin(t * 1.9 + ph))
            cy = H * (0.5 + 0.40 * math.cos(t * 1.4 + ph * 1.7))
            rad = max(1.0, span * (0.46 + 0.15 * math.sin(t * 1.1 + ph)))
            g = QRadialGradient(cx, cy, rad)
            g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), self._mesh_a(0.65)))
            g.setColorAt(0.55, QColor(c.red(), c.green(), c.blue(), self._mesh_a(0.22)))
            g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(0, 0, W, H, QBrush(g))

    def _mesh_wash(self, p, W: int, H: int, t: float) -> None:
        """One colour down the window from the top, the next back up from the
        bottom: a tinted room rather than lights moving in a dark one.

        Nothing here falls to nothing, and that is the whole difference from
        the blobs. The window already wears a vignette -- fade_layer, opaque
        at the top and bottom edges and clear by a quarter of the way in --
        so a gradient that spends its colour at the top edge spends it exactly
        where it is about to be painted out, and the band left in the middle,
        where the eye actually is, comes back black. The strong end is
        therefore only a lean, and the far end keeps a share of the tint.

        Spread is how far the lean carries: at 1.0 the middle of the window
        holds half the top's colour and the bottom a quarter, and by 2.5 the
        three are equal and the wash has become the veil. Motion is left with
        something to do -- the lean breathes by a twentieth -- because a
        frozen gradient makes `bg_motion` a setting that does nothing in this
        style, and a setting that does nothing reads as a broken one.
        """
        cols = self.mesh_colours()
        m = min(1.0, 0.5 * self.mesh_spread) * (1.0 + 0.05 * math.sin(t * 1.3))
        m = max(0.0, min(1.0, m))
        for i, c in enumerate(cols[:2]):
            top = i == 0
            g = QLinearGradient(0.0, 0.0 if top else float(H),
                                0.0, float(H) if top else 0.0)
            w = 0.60 if top else 0.34
            g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), self._mesh_a(w)))
            g.setColorAt(0.5, QColor(c.red(), c.green(), c.blue(), self._mesh_a(w * m)))
            g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), self._mesh_a(w * m * m)))
            p.fillRect(0, 0, W, H, QBrush(g))

    def _mesh_veil(self, p, W: int, H: int, _t: float) -> None:
        """The wash with no gradient in it: the whole window one album tint.

        Spread here is not a distance -- there is nothing to reach across --
        so it is spent on how much of the second colour is mixed into the
        first, which is the only other thing a flat field can vary.
        """
        cols = self.mesh_colours()
        c = cols[0]
        if len(cols) > 1:
            k = max(0.0, min(0.5, 0.20 * self.mesh_spread))
            o = cols[1]
            c = QColor(int(c.red() * (1 - k) + o.red() * k),
                       int(c.green() * (1 - k) + o.green() * k),
                       int(c.blue() * (1 - k) + o.blue() * k))
        p.fillRect(0, 0, W, H, QColor(c.red(), c.green(), c.blue(), self._mesh_a(0.42)))

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

    def paintEvent(self, _ev) -> None:
        """Draw the window, and put the painter down whatever happens.

        The try is not decoration. A QPainter that is still ACTIVE when this
        unwinds leaves the backing store mid-paint: Qt says so once per frame
        -- "endPaint() called with active painter" -- and then dies on
        "Cannot destroy paint device that is being painted". An exception in
        here also loses everything drawn AFTER the point it was raised, and
        the lyric column is painted first, so the symptom of a fault anywhere
        below it is a window with words scrolling and no art panel, no
        progress bar, no volume and no toast.

        None of which says what went wrong. The traceback does, and it only
        gets printed if the frame it came from does not take the process down
        with it first.
        """
        p = QPainter(self)
        try:
            self._paint_window(p, _ev)
        finally:
            p.end()

    def _paint_window(self, p: QPainter, _ev) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        self._marq_live = False

        if self.view == "browse":
            self._paint_browse(p, W, H)
            if self.toast_until > mono():
                self._paint_toast(p, W, H)
            ov = self.overlay()
            if ov in ("help", "menu"):
                {"help": self._paint_help, "menu": self._paint_menu}[ov](p, W, H)
            return

        if self.view == "detail":
            self._paint_detail(p, W, H)
            if self.toast_until > mono():
                self._paint_toast(p, W, H)
            ov = self.overlay()
            if ov in ("help", "menu"):
                {"help": self._paint_help, "menu": self._paint_menu}[ov](p, W, H)
            return

        if self.view == "review":
            self._paint_review(p, W, H)
            if self.toast_until > mono():
                self._paint_toast(p, W, H)
            ov = self.overlay()
            if ov in ("help", "menu"):
                {"help": self._paint_help, "menu": self._paint_menu}[ov](p, W, H)
            return

        e = self.beat_energy()
        if e > 0.004:
            g = 1.0 + 0.035 * e
            dst = QRectF(W * (1 - g) / 2, H * (1 - g) / 2, W * g, H * g)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            self._paint_scene(p, dst, W, H)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        else:
            dst = QRectF(0, 0, W, H)
            self._paint_scene(p, dst, W, H)
        vp = self.viz_face(W, H)
        if vp is not None and self._viz_mix > 0.004:
            p.setOpacity(self._viz_mix)
            p.drawPixmap(dst, vp, QRectF(vp.rect()))
            p.setOpacity(1.0)

        x0, width = self._lyr_x(), self._lyr_width()
        self._pix_left = PIX_PER_FRAME
        self._new_left = NEW_PER_FRAME
        self.credit_hot = []
        if self.lines:
            self.render.paint(p, x0, width, H)
            if self.marking():
                self._paint_review_marks(p, x0, width, H)
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
        if self.toast_until > mono():
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

    def _paint_panel(self, p, panel: float, H: int) -> None:
        px0 = self.panel_x()
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
        dur = m.get("length", 0.0)

        block = side
        if rows:
            block += 30 + len(rows) * fm_t.height() * 1.12 + 6 + fm_a.height() * 1.3
        if dur > 0:
            block += 30 + 6 + fm_s.height()
        y = max(H * 0.10, (H - block) / 2)
        x = px0 + (panel - side) / 2

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
        bx = px0 + (panel - boxw) / 2

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
        vol = (self.vol_drag if self.vol_drag is not None else
               self.vol_want if self.vol_want is not None else
               self.clock.volume)
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
        at = (mono() - self._marq.setdefault(key, mono())) % cycle
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

    def credit_font(self) -> QFont:
        f = QFont(self.family, max(9, int(self.lyric_px() * 0.30)))
        f.setWeight(QFont.Weight.DemiBold)
        return f

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

    def glow_color(self, ln: dict | None = None) -> QColor:
        """The ink a line's halo is drawn in: its sung colour, at full value.

        A glow is brighter than the thing it comes off, and that is not a
        matter of laying the same colour on harder. The sung colour is TEXT
        unless somebody has asked otherwise -- the very ink the line is
        already drawn in -- so a halo cut from it and added back over the
        line is the line out of focus, which is the depth blur and not a
        glow at all. Lifting the value is what makes it light.

        The hue and the saturation are kept, so a duet's second voice glows
        in its own colour and an `auto` fill taken off the cover glows in the
        cover's. Only the brightness is taken to the top. See glow_pixmap,
        which has always cut the per-word halo in flat white for the same
        reason and gets away with it because it is only ever one word.
        """
        h, sat, _v, a = self.sung_color(ln).getHsv()
        return QColor.fromHsv(h, sat, 255, a)

    def base_color(self, ln: dict) -> QColor:
        """The pen a line's words are drawn in before any of them is sung.

        White, except for a duet's second voice on an untimed line inside a
        document that is otherwise timed. The tint is normally carried by the
        sung fill, and a line with no timing never gets one -- so the colour
        that says "somebody else" was the one part of a duet that did not
        arrive on the lines the source could not place. The side it hangs off
        always did; see line_align.

        NOT ON A STATIC DOCUMENT, where nothing is timed at all. There the
        rule caught every second-voice line in the song at once, and a page
        of unsynced words came up half in one colour and half in another with
        nothing on screen to say why -- no reveal for it to be the resting
        state of, and nothing sung for it to differ from. It read as two
        lyrics rather than as two voices. A whole document with no clock is
        read, not followed, and the only thing colour can do to that is get
        in the way; the side of the screen still says who is singing.

        Only where the line itself is untimed, then, and only where its
        neighbours are not. A timed line keeps the fill it has always had,
        sweeping the tint across as it is sung, and painting its base coat in
        the same colour would take that reveal away on every duet in the
        library.

        The tint is laid on at TEXT's own value rather than the fill's, so
        the second voice reads as another voice rather than as a line that
        has already been sung: brightness is what says sung on this screen,
        and hue is what says who.
        """
        if not (ln.get("opposite") and self.duet_color != "off"
                and ln.get("start") is None and self.synced):
            return TEXT
        h, sat, _v, _a = self._duet_tint().getHsv()
        return QColor.fromHsv(h, sat, TEXT.value())

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

    def _paint_toast(self, p, W: int, H: int) -> None:
        left = self.toast_until - mono()
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

    def _help_fit(self, W: int, H: int, rows: list, head: float,
                  tries: tuple, force: bool = False):
        """A layout for `rows` that fits this window, or None.

        `head` is the room above the rows -- the title, and the tab strip
        where there is one. `tries` is the column counts worth attempting, in
        the order they look best; the sizes are tried largest first, so the
        panel only gets smaller when it has to. With `force` the last
        combination tried is returned however badly it fits, which is the
        answer for a window too small for anything: something legible and
        clipped beats nothing drawn at all.
        """
        base = max(11.0, W * 0.0105)
        got = None
        for px in (base, base * 0.92, base * 0.84, base * 0.76):
            f = self.ui_font(max(9.0, px))
            fk = self.ui_font(max(9.0, px), QFont.Weight.Black)
            fm, fmk = QFontMetricsF(f), QFontMetricsF(fk)
            rowh = fm.height() * 1.62
            keyw = max(fmk.horizontalAdvance(k) for k, _ in rows) + 20
            descw = max(fm.horizontalAdvance(d) for _, d in rows) + 24
            colw = keyw + descw
            for cols in tries:
                n = (len(rows) + cols - 1) // cols
                got = {"rows": rows, "cols": cols, "f": f, "fk": fk,
                       "rowh": rowh, "keyw": keyw, "descw": descw, "colw": colw,
                       "head": head, "lines": n,
                       "w": colw * cols + 56, "h": n * rowh + head + 24}
                if (got["w"] <= W - 2 * HELP_MARGIN
                        and got["h"] <= H - 2 * HELP_MARGIN):
                    return got
        return got if force else None

    def help_layout(self, W: int, H: int) -> dict:
        """What the Keys panel draws in a window this size.

        The whole list first, because seeing every key at once is the better
        answer wherever there is room for it -- two columns, then three if the
        window is wide and short. Only when nothing fits does it fall back to
        one section at a time, and then the tab strip appears with it: tabs
        that are never needed are clutter, and a panel that fits needs none.
        """
        whole = self._help_fit(W, H, HELP_KEYS, 62.0, (2, 3))
        if whole is not None:
            return {**whole, "tabs": [], "tab": -1}
        tab = max(0, min(len(HELP_SECTIONS) - 1, self.help_tab))
        rows = HELP_SECTIONS[tab][1]
        got = self._help_fit(W, H, rows, 100.0, (2, 1), force=True)
        return {**got, "tabs": [n for n, _r in HELP_SECTIONS], "tab": tab}

    def help_tab_step(self, delta: int) -> None:
        """Round the sections, and only where they are on show."""
        n = len(HELP_SECTIONS)
        self.help_tab = (max(0, self.help_tab) + delta) % n
        self.update()

    def _paint_help(self, p, W: int, H: int) -> None:
        m = self.help_layout(W, H)
        box = QRectF(0, 0, m["w"], m["h"])
        box.moveCenter(QPointF(W / 2, H / 2))
        p.fillRect(self.rect(), QColor(6, 6, 9, 175))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(20, 20, 25, 240))
        p.drawRoundedRect(box, 18, 18)
        p.setFont(self.ui_font(max(12, W * 0.0125), QFont.Weight.Black))
        p.setPen(TEXT)
        p.drawText(QRectF(box.x(), box.y() + 20, box.width(), 30),
                   int(Qt.AlignmentFlag.AlignCenter), "Keys")
        self.help_tab_rects = []
        if m["tabs"]:
            ft = self.ui_font(max(10, W * 0.0095), QFont.Weight.Bold)
            fmt = QFontMetricsF(ft)
            pads = [fmt.horizontalAdvance(t) + 26 for t in m["tabs"]]
            x = box.x() + (box.width() - sum(pads)) / 2
            y = box.y() + 56
            p.setFont(ft)
            for i, (name, wide) in enumerate(zip(m["tabs"], pads)):
                r = QRectF(x, y, wide, fmt.height() + 10)
                on = i == m["tab"]
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 30) if on
                           else QColor(0, 0, 0, 0))
                p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
                p.setPen(QColor(234, 234, 234, 235 if on else 120))
                p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), name)
                self.help_tab_rects.append((i, r))
                x += wide
        keyw, descw, colw, rowh = m["keyw"], m["descw"], m["colw"], m["rowh"]
        for i, (k, d) in enumerate(m["rows"]):
            cx = box.x() + 28 + (i % m["cols"]) * colw
            cy = box.y() + m["head"] + (i // m["cols"]) * rowh
            p.setFont(m["fk"])
            p.setPen(QColor(234, 234, 234, 235))
            p.drawText(QRectF(cx, cy, keyw, rowh), int(Qt.AlignmentFlag.AlignLeft), k)
            p.setFont(m["f"])
            p.setPen(QColor(234, 234, 234, 150))
            p.drawText(QRectF(cx + keyw, cy, descw, rowh),
                       int(Qt.AlignmentFlag.AlignLeft), d)

    # -------------------------------------------------------- browse painting
    ROW_PAD = 8.0

    def browse_metrics(self, W: int) -> dict:
        """One place for every browse dimension, so paint and hit-test agree."""
        gutter = max(18.0, W * 0.022)
        cw = max(118.0, min(190.0, W / 6.5))
        t_h = QFontMetricsF(self.ui_font(max(10, cw * 0.098))).height()
        s_h = QFontMetricsF(self.ui_font(max(9, cw * 0.086))).height()
        r_t = QFontMetricsF(self.ui_font(max(11, W * 0.0105))).height()
        r_s = QFontMetricsF(self.ui_font(max(9, W * 0.0086))).height()
        return {"gutter": gutter, "cw": cw, "gap": 14.0,
                "card_h": cw + 8 + t_h * 1.2 + s_h * 1.3,
                "bar_h": max(52.0, W * 0.042),
                "row_h": max(56.0, self.ROW_PAD * 2 + r_t * 1.2 + r_s * 1.3)}

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
        p.setFont(fq)
        p.setPen(TEXT)
        self._paint_field(p, self.bq_field,
                          QRectF(gut, y, W - 2 * gut, fmq.height() * 1.4),
                          fmq, "Search Spotify…")
        y += fmq.height() * 1.5
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 120))
        note = ("searching…" if self.bq_busy else
                (f"{len(self.bq_hits)} results" if self.bq_hits else
                 ("no results" if len(self.bq) >= 2 else "type to search")))
        if self.gq_busy:
            note += " · asking Genius…"
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
            nh, sh = fmt_.height() * 1.2, fms.height() * 1.3
            ty = r.y() + max(0.0, (r.height() - nh - sh) / 2)
            p.setFont(ft)
            p.setPen(QColor(234, 234, 234, 235 if sel else 200))
            p.drawText(QRectF(tx, ty, tw, nh),
                       int(Qt.AlignmentFlag.AlignLeft),
                       fmt_.elidedText(name, Qt.TextElideMode.ElideRight, tw))
            p.setFont(fs)
            p.setPen(QColor(234, 234, 234, 130))
            p.drawText(QRectF(tx, ty + nh, tw, sh),
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
        if mono() - self.recents_at > 120:
            self.fetcher.request_recents()
        if not self.suggest:
            self.fetcher.request_suggest("")
        if mono() - self.discover_at > 600:
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

    # ---------------------------------------------------------------- review
    REV_INK = {"error": QColor(255, 104, 104),
               "warn": QColor(250, 190, 88),
               "note": QColor(132, 194, 255)}
    REV_RULES = ("auto", "sung", "hyphen", "off")
    REV_SEAM = QColor(112, 222, 192, 205)
    REV_KEEP = "the split is right"
    REVIEW_KEYS = ("↑↓ line", "→← open a repeat", "Enter play",
                   "Tab these tabs", "1 2 3 one weight (0 all)",
                   "A every line", "S split rule",
                   "K this split is right (⇧K take it back)", "L language",
                   "V mark as it plays", "C copy", "Esc back")

    def open_review(self) -> None:
        """Go through the document on screen the way a person would.

        It is the one screen in this window that is not trying to make the
        lyrics look good. Everywhere else the player quietly puts a document
        right as it draws it -- the invisible characters are stripped, a line
        is played to the end of its words whatever its own end says, an open
        end is clamped -- so the things worth fixing in a file somebody is
        still writing are exactly the things the lyrics view cannot show. See
        review.py for what is looked for and why.

        Meant for a TTML that came in from outside: one dropped on the window
        or pushed over the live link. It will read anybody's document, and on
        a catalogue's copy it mostly reports the zero-width spaces that
        catalogue puts in -- which is true, and is worth seeing once.
        """
        if not self.body:
            self.toast("no lyrics to review")
            return
        self.editing = self.show_info = self.show_search = self.show_menu = False
        self.show_help = False
        self.view = "review"
        self.review_scroll = self.review_scroll_target = 0.0
        self.review_sel = 0
        self.build_review()
        self.update()

    def close_review(self) -> None:
        self.view = "lyrics"
        self.set_cursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def review_key_of(self) -> tuple:
        """What the report in hand was made from, apart from the document."""
        return (self.review_rule, self.review_lang, self.clock.tid or "")

    def build_review(self) -> None:
        """Read the document, unless the same one has already been read.

        The document is held and compared by IDENTITY, the way the rest of
        the window asks whether the lyric changed (see same_lyric) -- and the
        object itself is kept rather than its id, because this holds the
        REPORT rather than the thing it was made from, and an id belonging to
        something that has been freed is an id another document can be handed
        next. The live link is what makes that matter: an editor pushes a new
        document on every keystroke, each one replacing the last.
        """
        key = self.review_key_of()
        if (self.review is not None and self.review_at == key
                and self.review_body is self.body):
            return
        whose = (self.dropped_from if self.dropped is not None
                 and self.dropped == self.clock.tid and self.dropped_from
                 else self.source_name(SL.payload(self.body or {})))
        try:
            self.review = RV.review(
                self.body, whose=whose, rule=self.review_rule,
                lang=self.review_lang,
                length=float(self.clock.meta.get("length") or 0.0),
                title=str(self.clock.meta.get("title") or ""),
                artist=str(self.clock.meta.get("artist") or ""))
        except Exception as exc:                         # noqa: BLE001
            self.review = self.review_at = self.review_body = None
            self.toast(f"could not review this — {type(exc).__name__}: {exc}")
            self.close_review()
            return
        self.review_at, self.review_body = key, self.body
        self._rev_plan = self._rev_key = self._rev_spans = None

    def review_shown(self) -> list:
        """The rows the page is listing, which is not always all of them.

        A row with nothing to say about it is left out, and one exception is
        kept: the LINE an ad-lib is written in comes with it. An ad-lib is
        half a line -- the words that are sung over the ones in front of them
        -- and on its own, under a line number that belongs to something else
        on screen, it reads as a line the song does not have.
        """
        rep = self.review
        if rep is None:
            return []
        if self.review_all:
            return rep.rows
        said = {r: bool(rep.told(r, self.review_tab, self.review_level))
                for r in rep.rows}
        keep = {r.group for r in rep.rows if said[r] and r.kind == "bg"}
        return [r for r in rep.rows
                if said[r] or (r.kind == "lead" and r.group in keep)]

    def review_folded(self) -> list:
        """The listed rows with the repeats folded in: [(row, [the others])].

        A song repeats itself, and a document's faults repeat with it: "Wha-
        wha- what" is three lines of this folder's She Bugging and the same
        sentence three times, and Music Baby says "B-A-B-Y-B-O-Y" eleven
        times. Reading the same finding eleven times is not eleven times the
        information; it is a page somebody stops reading.

        Folded on what is ON SCREEN -- the words, and what is said about them
        under the tab and weight being read -- so two lines that only look
        alike stay apart, and the times of the others are kept and printed.
        `A` unfolds them, because "every line" should mean every line.
        """
        rows = self.review_shown()
        if self.review_all or self.review is None:
            return [(r, []) for r in rows]
        out, at = [], {}
        for row in rows:
            key = (row.kind, row.text(),
                   tuple((lv, kind, says) for lv, kind, says, _more, _k
                         in self.review.told(row, self.review_tab,
                                             self.review_level)))
            if key in at:
                out[at[key]][1].append(row)
            else:
                at[key] = len(out)
                out.append((row, []))
        return out

    def review_fonts(self, W: int):
        f = self.ui_font(max(12, W * 0.0125), QFont.Weight.Medium)
        fs = self.ui_font(max(9, W * 0.0086))
        fn = self.ui_font(max(9, W * 0.0082), QFont.Weight.Black)
        return f, fs, fn

    def review_plan(self, W: int):
        """Every listed row laid out down the page, worked out once.

        The same bargain the lyrics column strikes in Flow.plan: none of this
        answers to the clock or to the scroll, so a frame reads it instead of
        building it. It is rebuilt when the document, the filter, the rule or
        the width change -- which is what the key holds.
        """
        key = (self.review, int(W), self.review_all, self.review_rule,
               self.review_tab, self.review_level,
               tuple(sorted(self.review_open)))
        if self._rev_key == key and self._rev_plan is not None:
            return self._rev_plan
        f, fs, _fn = self.review_fonts(W)
        fm, fms = QFontMetricsF(f), QFontMetricsF(fs)
        gut = max(34.0, W * 0.045)
        numw = max(96.0, W * 0.10)
        textw = max(120.0, W - gut * 2 - numw)
        # The gap a seam is drawn in the middle of. Measured on the mark the
        # notes underneath write it with (RV.SEAM), so the bar the eye follows
        # down the line and the character it reads in the sentence take the
        # same room.
        sep = fm.horizontalAdvance(RV.SEAM)
        space = fm.horizontalAdvance(" ")
        lineh = fm.height() * 1.28
        noteh = fms.height() * 1.30
        out, y = [], 0.0
        for row, also in self.review_folded():
            placed, x = [[]], 0.0
            for chip in row.chips:
                w = fm.horizontalAdvance(chip.shown)
                if x > 0 and x + w > textw:
                    placed.append([])
                    x = 0.0
                placed[-1].append((x, w, chip))
                x += w + (sep if chip.glue else space)
            notes = []
            keepw = fms.horizontalAdvance(self.REV_KEEP) + 30
            for level, _kind, says, more, k in (
                    self.review.told(row, self.review_tab, self.review_level)
                    if row.found else []):
                said = says + (f"  (and {more} more like it in this line)"
                               if more else "")
                keep = bool(self.review.findings[k].get("fix"))
                wide = textw - 22 - (keepw if keep else 0)
                for r_i, text in enumerate(wrap_rows(fms, said, wide, 4,
                                                     elide=False)):
                    notes.append((level, text, k if r_i == 0 else -1,
                                  keep and r_i == 0))
            open_ = bool(also) and (row.n, row.kind) in self.review_open
            extra = (2 + len(also)) if open_ else (1 if also else 0)
            h = (len(placed) * lineh + (len(notes) + extra) * noteh
                 + lineh * 0.42)
            out.append({"row": row, "also": also, "open": open_, "y": y,
                        "h": h, "placed": placed, "notes": notes,
                        "lineh": lineh, "noteh": noteh})
            y += h
        plan = (out, y, gut, numw, textw)
        self._rev_key, self._rev_plan = key, plan
        return plan

    def _paint_review(self, p, W: int, H: int) -> None:
        """The review, as a page of the document with what is wrong marked on it."""
        p.fillRect(QRectF(0, 0, W, H), QColor(9, 9, 12))
        if self.art_bg and self.bg_mode == "art":
            p.setOpacity(0.18)
            p.drawPixmap(QRectF(0, 0, W, H), self.art_bg,
                         self._art_src(self.art_bg, 0.0))
            p.setOpacity(1.0)
            p.fillRect(QRectF(0, 0, W, H), QColor(9, 9, 12, 215))
        self.build_review()
        rep = self.review
        if rep is None:
            return
        f, fs, fn = self.review_fonts(W)
        fm, fms, fmn = QFontMetricsF(f), QFontMetricsF(fs), QFontMetricsF(fn)
        sepw = fm.horizontalAdvance("·")
        plan, total, gut, numw, textw = self.review_plan(W)
        self.review_sel = max(0, min(self.review_sel, len(plan) - 1))
        top = self._rev_top = self._paint_review_head(p, W, rep, gut,
                                                      textw + numw)

        view_h = max(40.0, H - top - 12)
        self.review_scroll_target = max(0.0, min(self.review_scroll_target,
                                                 max(0.0, total - view_h)))
        pos = self.position() - self.track_offset()
        self.review_rects = []
        self.review_fold_rects = []
        self.review_also_rects = []
        self.review_keep_rects = []
        if not plan:
            p.setFont(f)
            p.setPen(QColor(234, 234, 234, 150))
            p.drawText(QRectF(gut, top + 30, W - gut * 2, fm.height() * 2.2),
                       int(Qt.AlignmentFlag.AlignLeft),
                       "nothing timed here to read"
                       if not rep.rows else
                       "nothing to report — Tab reads the document anyway")
            return
        p.save()
        p.setClipRect(QRectF(0, top, W, view_h))
        for i, item in enumerate(plan):
            y = top + item["y"] - self.review_scroll
            if y > H or y + item["h"] < top:
                continue
            row = item["row"]
            x0 = gut + numw
            here = QRectF(gut - 10, y - 4, W - gut * 2 + 20, item["h"])
            self.review_rects.append((i, here))
            if i == self.review_sel:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 20))
                p.drawRoundedRect(here, 10, 10)
                p.setBrush(Qt.BrushStyle.NoBrush)
            last = row.last()
            if row.start is not None and last is not None and row.start <= pos < last:
                p.fillRect(QRectF(gut - 10, y - 4, 3.0, item["h"]),
                           QColor(234, 234, 234, 190))
            p.setFont(fn)
            p.setPen(QColor(234, 234, 234, 150 if row.kind == "lead" else 95))
            label = f"{row.n}" + ("" if row.kind == "lead" else " ad-lib")
            p.drawText(QRectF(gut, y, numw - 16, fmn.height() * 1.4),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       label)
            p.setPen(QColor(234, 234, 234, 105))
            p.drawText(QRectF(gut, y + fmn.height() * 1.35, numw - 16,
                              fmn.height() * 1.4),
                       int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                       RV.stamp(row.start))
            if item["also"]:
                p.setPen(QColor(234, 234, 234, 140))
                p.drawText(QRectF(gut, y + fmn.height() * 2.7, numw - 16,
                                  fmn.height() * 1.4),
                           int(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter),
                           f"\u00d7{len(item['also']) + 1}")
            p.setFont(f)
            ty = y + fm.ascent() + item["lineh"] * 0.12
            for line in item["placed"]:
                for x, w, chip in line:
                    cx = x0 + x
                    marks, worst = chip.shows(self.review_tab)
                    for m in marks:
                        a = fm.horizontalAdvance(chip.shown[:m.a])
                        b = fm.horizontalAdvance(chip.shown[:m.b])
                        ink = self.REV_INK.get(m.level, TEXT)
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(QColor(ink.red(), ink.green(), ink.blue(), 78))
                        p.drawRoundedRect(
                            QRectF(cx + a - 1.5, ty - fm.ascent() * 0.92,
                                   max(4.0, b - a + 3.0), fm.height() * 0.98), 3, 3)
                        p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(TEXT if not row.background
                             else QColor(234, 234, 234, 185))
                    p.drawText(QPointF(cx, ty), chip.shown)
                    if worst:
                        ink = self.REV_INK[worst]
                        p.fillRect(QRectF(cx, ty + fm.descent() * 0.45, w, 1.8),
                                   QColor(ink.red(), ink.green(), ink.blue(), 225))
                    if chip.glue:
                        tick = max(1.5, fm.height() * 0.055)
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(self.REV_SEAM)
                        p.drawRoundedRect(
                            QRectF(cx + w + (sepw - tick) / 2,
                                   ty - fm.ascent() * 0.78,
                                   tick, fm.ascent() * 0.92),
                            tick / 2, tick / 2)
                        p.setBrush(Qt.BrushStyle.NoBrush)
                ty += item["lineh"]
            ny = y + len(item["placed"]) * item["lineh"]
            p.setFont(fs)
            for level, text, _k, keep in item["notes"]:
                ink = self.REV_INK.get(level, TEXT)
                p.setPen(QColor(ink.red(), ink.green(), ink.blue(), 235))
                p.drawText(QRectF(x0 + 2, ny, 8, item["noteh"]),
                           int(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter),
                           "•" if _k >= 0 and level else "")
                p.setPen(QColor(234, 234, 234, 205 if level == "error"
                                else 110 if not level else 165))
                p.drawText(QRectF(x0 + 20, ny, textw - 22, item["noteh"]),
                           int(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter), text)
                if keep:
                    self._paint_review_keep(p, _k, x0 + textw, ny,
                                            item["noteh"], fms)
                ny += item["noteh"]
            if item["also"]:
                ny = self._paint_review_fold(p, i, item, x0, ny, textw, fs, fms)
        p.restore()
        if total > view_h:
            frac = self.review_scroll / max(1.0, total - view_h)
            bar = max(40.0, view_h * view_h / total)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(234, 234, 234, 45))
            p.drawRoundedRect(QRectF(W - 10, top + (view_h - bar) * frac, 4, bar),
                              2, 2)
            p.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_review_head(self, p, W: int, rep, gut: float, wide: float) -> float:
        """The heading, and where the list underneath it starts."""
        ft = self.ui_font(max(17, W * 0.0205), QFont.Weight.Black)
        fa = self.ui_font(max(11, W * 0.0105), QFont.Weight.Medium)
        fs = self.ui_font(max(9, W * 0.0086))
        fmt, fma, fms = QFontMetricsF(ft), QFontMetricsF(fa), QFontMetricsF(fs)
        y = 20.0
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 120))
        p.drawText(QRectF(gut, y, W - gut * 2, fms.height()),
                   int(Qt.AlignmentFlag.AlignLeft), "Esc  back to the lyrics")
        y += fms.height() + 14
        p.setFont(ft)
        p.setPen(TEXT)
        title = rep.whose or self.song_title() or "this document"
        p.drawText(QRectF(gut, y, W - gut * 2, fmt.height() * 1.15),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   fmt.elidedText(f"Review · {title}", Qt.TextElideMode.ElideRight,
                                  W - gut * 2))
        y += fmt.height() * 1.25
        y = self._paint_review_tabs(p, W, rep, gut, y)
        p.setFont(fa)
        x = gut
        self.review_level_rects = []
        for level, name in (("error", "wrong"), ("warn", "doubtful"),
                            ("note", "worth a look")):
            n = len(rep.in_group(self.review_tab, level))
            ink = self.REV_INK[level]
            said = f"{n} {name}"
            wide = 14 + fma.horizontalAdvance(said) + 18
            box = QRectF(x - 6, y - 1, wide, fma.height() * 1.2 + 2)
            on = self.review_level == level
            if on or box.contains(self.mouse_pos):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(234, 234, 234, 30 if on else 14))
                p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ink.red(), ink.green(), ink.blue(),
                              235 if n else 70))
            p.drawEllipse(QPointF(x + 4, y + fma.height() * 0.55), 4.0, 4.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(234, 234, 234,
                            235 if on else 215 if n else 95))
            p.drawText(QRectF(x + 14, y, fma.horizontalAdvance(said) + 8,
                              fma.height() * 1.2),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       said)
            self.review_level_rects.append((level, box))
            x += wide + 10
        folded = self.review_folded()
        rows, said = len(self.review_shown()), len(folded)
        quiet = len(rep.rows) - rows
        again = rows - said
        p.setPen(QColor(234, 234, 234, 120))
        tail = (f"{said} line{'' if said == 1 else 's'}"
                + (f", {again} repeat{'' if again == 1 else 's'} folded in"
                   if again else "")
                + (f", {quiet} clean one{'' if quiet == 1 else 's'} hidden"
                   if quiet else ""))
        p.drawText(QRectF(x, y, W - x - gut, fma.height() * 1.2),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   tail)
        y += fma.height() * 1.5
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 125))
        about = [f"splits: {rep.said_rule()}",
                 f"language: {rep.lang}"
                 + ("  (yours)" if self.review_lang else "  (the file's)"),
                 "a syllable seam inside a word is ticked"]
        if rep.kept:
            about.append(rep.said_kept())
        for text in wrap_parts(fms, about, "   ·   ", W - gut * 2):
            p.drawText(QRectF(gut, y, W - gut * 2, fms.height() * 1.3),
                       int(Qt.AlignmentFlag.AlignLeft), text)
            y += fms.height() * 1.3
        y += fms.height() * 0.15
        p.setPen(QColor(234, 234, 234, 95))
        for text in wrap_parts(fms, self.REVIEW_KEYS, "   ", W - gut * 2):
            p.drawText(QRectF(gut, y, W - gut * 2, fms.height() * 1.3),
                       int(Qt.AlignmentFlag.AlignLeft), text)
            y += fms.height() * 1.3
        y += fms.height() * 0.3
        y = self._paint_review_loose(p, W, rep, gut, y)
        p.fillRect(QRectF(gut, y, W - gut * 2, 1.0), QColor(234, 234, 234, 28))
        return y + 14

    def _paint_review_loose(self, p, W: int, rep, gut: float, y: float) -> float:
        """What is wrong with the DOCUMENT, which belongs to no line of it.

        Nothing is timed; something is timed past the end of the recording;
        nobody is credited with writing the song. The list below is a list of
        lines, so a finding with no line to hang on had nowhere to be drawn
        and was counted in the tabs without ever being shown -- a number
        beside a weight that nothing on the page accounted for.

        Read through the same filter as everything else: these belong to a
        tab and carry a weight like any other finding, and a page narrowed to
        the things that are wrong should not keep showing a note about the
        header.
        """
        loose = [f for f in rep.in_group(self.review_tab, self.review_level)
                 if f["row"] is None]
        if not loose:
            return y
        fs = self.ui_font(max(9, W * 0.0086))
        fms = QFontMetricsF(fs)
        p.setFont(fs)
        for f in loose[:4]:
            ink = self.REV_INK.get(f["level"], TEXT)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ink.red(), ink.green(), ink.blue(), 235))
            p.drawEllipse(QPointF(gut + 4, y + fms.height() * 0.6), 3.5, 3.5)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QColor(234, 234, 234, 190))
            for row, text in enumerate(
                    wrap_rows(fms, f["says"], W - gut * 2 - 20, 3, elide=True)):
                p.drawText(QRectF(gut + 16, y, W - gut * 2 - 18,
                                  fms.height() * 1.3),
                           int(Qt.AlignmentFlag.AlignLeft), text)
                y += fms.height() * 1.3
        if len(loose) > 4:
            p.setPen(QColor(234, 234, 234, 110))
            p.drawText(QRectF(gut + 16, y, W - gut * 2 - 18, fms.height() * 1.3),
                       int(Qt.AlignmentFlag.AlignLeft),
                       f"and {len(loose) - 4} more about the document")
            y += fms.height() * 1.3
        return y + 10

    REVIEW_NEAR = 2

    def marking(self) -> bool:
        """Whether the words being drawn should carry their review marks.

        Any document, not only a file of the user's own. It was held to their
        own files at first, on the argument that being told about a zero-width
        space while a song plays is help on a file you are writing and noise
        on a copy you cannot edit -- and the argument is sound about ZWSPs,
        which the catalogues put between every pair of words. It is not a
        reason to refuse the question: what a catalogue's copy gets wrong is
        worth seeing too, and it is how anybody would decide whether to go and
        time the song themselves.

        What answers the noise instead is the filter the review page already
        has, which this reads: with the Splits tab up, or with `1` pressed for
        the things that are wrong, a document nobody would otherwise look at
        twice marks four words rather than four hundred.
        """
        return bool(self.review_marks and self.body is not None and self.lines)

    def review_spans(self):
        """Where this document's faults are, as the column needs them.

        ({line key: [(start, end, level)]}, {line key: level}) -- the pieces to
        underline, and the worst thing said about each line for the bar in the
        margin.

        Built once per document and held: the read itself is a pass over the
        whole document, about 8ms for a song of this length, and the first one
        of a session also loads pyphen's patterns for another 70ms. The map is
        then 0.5ms to build and the drawing 0.09ms a frame, measured here over
        300 frames of "Love Blur" -- so what this costs is one hitch on the
        frame a document lands, which is the frame that was already laying the
        whole column out.

        Keyed by TIME, which is the one thing a drawn line and a document row
        certainly agree on. They agree on nothing else: what gets drawn has
        been through `prepare` and the syllable splitter, so one document
        syllable can be three drawn fragments (split "all") or three can be
        one (merge), and the indices do not survive either. A fragment belongs
        to whichever piece of the document its start falls inside.
        """
        self.build_review()
        rep = self.review
        want = (self.review_tab, self.review_level)
        got = self._rev_spans
        if got is not None and got[0] is rep and got[3] == want:
            return got[1], got[2]
        spans: dict = {}
        worst: dict = {}
        for row in (rep.rows if rep else []):
            if row.start is None:
                continue
            key = (round(row.start, 3), bool(row.background))
            here = spans.setdefault(key, [])
            for c in row.chips:
                if c.start is not None:
                    here.append((c.start, max(c.end or c.start, c.start),
                                 _level_of(c, self.review_tab, self.review_level)))
            here.sort()
            if not any(level for _s, _e, level in here):
                spans.pop(key, None)
            said = _worst_told(rep, row, self.review_tab, self.review_level)
            if said and (worst.get(key) is None
                         or RV.LEVELS.index(said) < RV.LEVELS.index(worst[key])):
                worst[key] = said
        self._rev_spans = (rep, spans, worst, want)
        return spans, worst

    @staticmethod
    def _mark_level(spans, t: float) -> str:
        """What is wrong with the piece of the document sounding at `t`.

        A piece that BEGINS at `t` answers for it, and otherwise the last one
        to have started by then. Both halves are needed. Pieces of one word
        touch exactly, so one ends at the same millisecond the next begins,
        and accepting any piece containing `t` put every fragment inside its
        predecessor as well -- the rule under a bad seam ran on under the
        syllable after it.

        And more than one piece can begin at `t`, which is what the second
        half is for: a piece with no length at all sits exactly on top of the
        one after it. Walking on to the last of them handed the mark to the
        piece on top, so a syllable timed to last nothing -- which is the
        fault being reported -- was the one thing on the line with nothing
        drawn under it. LEDGER's "Foreigner" is 30 of them.
        """
        got, here, found = "", "", False
        for start, end, level in spans or ():
            if start > t + 0.002:
                break
            if abs(start - t) <= 0.002:
                found = True
                if level and (not here or RV.LEVELS.index(level)
                              < RV.LEVELS.index(here)):
                    here = level
            elif t <= max(end, start) + 0.002:
                got = level
            else:
                got = ""
        return here if found else got

    def _paint_review_marks(self, p, x0: float, width: float, H: int) -> None:
        """The review, drawn over the column it is about.

        Two marks, and they answer different questions. A bar in the margin
        says THIS LINE has something wrong with it, on every line the window
        is showing, so a fault arrives on screen before the voice does. A rule
        under a word says WHICH WORD, and is drawn only within a line or two
        of the one being sung -- underlines all the way down a column are
        wallpaper, and stop being read after the first screenful.

        The geometry is the stack's own: `layout_line` lays out the rows and
        both the picture path and the live path put the first baseline at
        y + ruby + ascent and step by height * 1.06 + ruby. The one thing
        added back here is the line drop, because the line being sung is
        drawn a few pixels low as it arrives and a mark that ignored that
        would come unstuck from its word for the length of the entrance. What
        is deliberately NOT followed is the rise: a lifted word climbs off a
        rule that stays where the line is, which is what a rule under a line
        of type should do.

        The pinned renderers lay their own rows out at their own size (see
        Renderer.stacked) and get the margin bar alone, as do the three
        trolls that take the words off the line entirely -- there is nothing
        sensible to underline when the word is in the air.

        A stacked renderer may still DRAW a line under a scale -- the amll
        column shrinks everything but the line being sung -- and that moves
        the ink without moving the layout this works from. So each line's
        rules go through the renderer's own transform, taken from
        `line_scale` and applied about the same centre it uses, which is how
        they stay under the words through the grow rather than only at the
        two ends of it. The bar in the margin is deliberately left out of it:
        it is a mark against the COLUMN, at a fixed place beside it, and a
        bar that crept in and out by three percent as the voice went past
        would be the most distracting thing on screen.
        """
        spans, worst = self.review_spans()
        if not spans and not worst:
            return
        pos = self.position() - self.track_offset()
        live = set(self.sounding(pos)) if self.synced else set()
        here = self.focus_idx if self.focus_idx is not None and self.focus_idx >= 0 \
            else (min(live) if live else -1)
        in_words = (getattr(self.render, "stacked", False)
                    and self.zero_g <= 0 and self.clouds <= 0 and self.float_up <= 0)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for i, top, h, lo, _hi in self.line_rects:
            if i >= len(self.lines):
                continue
            ln = self.lines[i]
            if ln.get("dots") or ln.get("credits") or ln.get("start") is None:
                continue
            y = top - self.scroll
            if y > H or y + h < 0:
                continue
            key = (round(ln["start"], 3), bool(ln["background"]))
            level, row_spans = worst.get(key, ""), spans.get(key)
            if not level and not row_spans:
                continue
            if level:
                ink = self.REV_INK[level]
                p.setBrush(QColor(ink.red(), ink.green(), ink.blue(), 135))
                bar = QRectF(max(x0 - 16, lo - 8), y + 3, 3.0, max(8.0, h - 8))
                p.drawRoundedRect(bar, 1.5, 1.5)
            if not in_words or not row_spans:
                continue
            dist = min((abs(i - j) for j in live), default=9)
            if here >= 0:
                dist = min(dist, abs(i - here))
            if dist > self.REVIEW_NEAR and self.browse < 0.2:
                continue
            rows, fm, _h, _rr, _rf, _ruby, rufm = self.layout_line(i, width)
            ox = self.line_ox(ln, fm, x0)
            ruh = self.ruby_h(rufm)
            drop = ((1.0 - self.activation.get(i, 0.0)) * 7.0 * self.line_drop
                    if i in live else 0.0)
            ry = y + drop + ruh + fm.ascent()
            thick = max(1.6, fm.height() * 0.055)
            scale = self.render.line_scale(i)
            scaled = abs(scale - 1.0) >= self.render.SCALE_EPS
            if scaled:
                p.save()
                self.render.scale_about(p, scale, x0, width, y, h)
            for row in rows:
                for fx, _fw, txt, s, _e in row:
                    if s is None:
                        continue
                    mark = self._mark_level(row_spans, s)
                    if not mark:
                        continue
                    ink = self.REV_INK[mark]
                    fade = max((215, 130, 80)[min(dist, 2)]
                               if dist <= self.REVIEW_NEAR else 0,
                               int(165 * self.browse))
                    p.setBrush(QColor(ink.red(), ink.green(), ink.blue(), fade))
                    ink_w = fm.horizontalAdvance(txt.rstrip())
                    if ink_w <= 0:
                        continue
                    p.drawRect(QRectF(ox + fx, ry + fm.descent() * 0.5,
                                      ink_w, thick))
                ry += fm.height() * 1.06 + ruh
            if scaled:
                p.restore()
        p.restore()

    REVIEW_LOUD = 60

    def toggle_review_marks(self) -> None:
        """Turn the marks in the column on or off, and say what is about to
        happen -- which is not the same answer on every document.

        The count is worth the 8ms it costs to have: the same key over a file
        somebody hand-timed marks four words, and over a copy fetched from a
        catalogue it marks four hundred, and being told which of those is
        coming is the difference between a feature and a broken window.
        """
        self.review_marks = not self.review_marks
        self._rev_spans = None
        if not self.review_marks:
            self.toast("review marks off")
            return
        if not self.marking():
            self.toast("review marks on — no lyrics on screen to mark yet")
            return
        self.build_review()
        n = self.review.total() if self.review else 0
        if not n:
            self.toast("review marks on — nothing to mark on this copy")
        elif n > self.REVIEW_LOUD:
            self.toast(f"review marks on — {n} things to mark on this copy; "
                       f"Y, then a tab or 1, marks fewer")
        else:
            self.toast(f"review marks on — {n} thing{'' if n == 1 else 's'} "
                       f"to mark")

    def _paint_review_fold(self, p, i: int, item, x0: float, ny: float,
                           textw: float, fs, fms) -> float:
        """The repeats of one line: one line about them, or all of them.

        Closed it is a sentence with the times in it, which is enough to know
        that the fault repeats and roughly where. Open it is a row per
        occurrence, each one somewhere to click and each one a place in the
        song to play from -- because the third time a line is sung is
        sometimes the one that is wrong in a way the first two are not, and
        the only way to find that out is to be able to reach it.
        """
        also, noteh = item["also"], item["noteh"]
        p.setFont(fs)
        arrow = "\u25be" if item["open"] else "\u25b8"
        head = (f"{arrow} the same line {len(also) + 1} times"
                if item["open"] else
                f"{arrow} again at "
                + ", ".join(RV.stamp(r.start) for r in also[:4])
                + (f" and {len(also) - 4} more" if len(also) > 4 else "")
                + " \u2014 the same words, and the same thing to say")
        rect = QRectF(x0 + 14, ny, textw - 16, noteh)
        p.setPen(QColor(234, 234, 234, 150 if rect.contains(self.mouse_pos)
                        else 110))
        p.drawText(rect, int(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter), head)
        self.review_fold_rects.append((i, rect))
        ny += noteh
        if not item["open"]:
            return ny
        for other in [item["row"]] + list(also):
            r = QRectF(x0 + 34, ny, textw - 36, noteh)
            on = r.contains(self.mouse_pos)
            p.setPen(QColor(234, 234, 234, 190 if on else 130))
            p.drawText(r, int(Qt.AlignmentFlag.AlignLeft
                              | Qt.AlignmentFlag.AlignVCenter),
                       f"line {other.n}   {RV.stamp(other.start)}"
                       + ("   \u2014 play from here" if on else ""))
            self.review_also_rects.append((other, r))
            ny += noteh
        return ny

    def _paint_review_keep(self, p, k: int, right: float, y: float,
                           h: float, fm) -> None:
        """The button that answers one finding about a seam.

        Drawn in the seam's own colour, at the right-hand end of the sentence
        it answers rather than under the row -- a row can carry several
        findings and only some of them are answerable, and a button under the
        row would have nothing to say which one it meant. The sentence is
        wrapped to leave room for it (see review_plan), so it never lands on
        top of the words it belongs to.
        """
        wide = fm.horizontalAdvance(self.REV_KEEP) + 22
        box = QRectF(right - wide, y + 1, wide, max(12.0, h - 2))
        hot = box.contains(self.mouse_pos)
        r, g, b = (self.REV_SEAM.red(), self.REV_SEAM.green(),
                   self.REV_SEAM.blue())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(r, g, b, 46 if hot else 22))
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(r, g, b, 255 if hot else 200))
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), self.REV_KEEP)
        self.review_keep_rects.append((k, box))

    def review_fixes(self, at: int) -> list:
        """Which of the findings listed against one row can be ruled on.

        Read off what the page is SHOWING rather than off the row, because
        `told` writes out the first of each kind and counts the rest: a line
        that cuts two words oddly shows one sentence and one button, and the
        second word surfaces as the first once the first has been answered.
        """
        plan, *_rest = self.review_plan(self.width())
        if self.review is None or not 0 <= at < len(plan):
            return []
        return [k for _lv, _kind, _says, _more, k in
                self.review.told(plan[at]["row"], self.review_tab,
                                 self.review_level)
                if self.review.findings[k].get("fix")]

    def review_keep(self, at: int) -> None:
        """Rule that the document has this word right and the splitter wrong.

        The reviewer holds every seam in a document to `editor.syllables`,
        and that rule is wrong about words often enough to matter -- it is a
        rule, and a lyric is full of names, spellings nobody prints and words
        sung the way they are sung. Until now the only place to tell it so
        was the editor's Syllabify dialog, which means opening the other
        window over a document this one is only reading.

        It writes the editor's own store, so it is one decision rather than
        two: the word is settled here, in the editor, and in every song after
        this one. Nothing about the DOCUMENT is touched -- the seam stays
        exactly where the person who timed it put it, which is the whole
        point of saying it was right.
        """
        rep = self.review
        if rep is None or not 0 <= at < len(rep.findings):
            return
        fix = rep.findings[at].get("fix")
        if not fix:
            return
        word, pieces = fix
        was = RV.corrections().get(SL.peel(word)[1].lower())
        why = RV.keep_split(word, list(pieces))
        if why:
            self.toast(f"could not keep that split — {why}")
            return
        self.review_kept.append((word, list(was) if was else None))
        self.review = self.review_at = None
        self.build_review()
        self.review_show_sel()
        shown = "·".join(pieces)
        self.toast(f"kept: {word} is cut {shown}"
                   + (f", not {'·'.join(was)}" if was else "")
                   + " — the rule follows you now, here and in the editor "
                     " (Shift+K takes it back)")

    def review_unkeep(self) -> None:
        """Take back the last split kept from this page.

        Back to what it was rather than back to nothing: keeping a split over
        a word that already had one is how a correction gets corrected, and
        undoing that should leave the earlier one standing. Only this
        session's keeps are on the stack -- the rest of the store is the
        editor's dialog to manage, which lists every correction there is.
        """
        if not self.review_kept:
            self.toast("nothing kept here yet — K says a seam is right, "
                       "Shift+K takes it back")
            return
        word, was = self.review_kept.pop()
        if was:
            why = RV.keep_split("".join(was), list(was))
            said = f"{word} is back to {'·'.join(was)}"
        else:
            why = "" if RV.forget_split(word) else "nothing was kept for it"
            said = f"{word} is back under the rule"
        if why:
            self.toast(f"could not take it back — {why}")
            return
        self.review = self.review_at = None
        self.build_review()
        self.review_show_sel()
        self.toast(said)

    def _paint_review_tabs(self, p, W: int, rep, gut: float, y: float) -> float:
        """The strip that divides the findings into the questions they answer.

        Drawn the way the Keys panel draws its sections, and carrying each
        tab's count, because the count is the reason to press one: a document
        with nothing wrong in its words and eleven things wrong in its timing
        says so before anything is read.
        """
        ft = self.ui_font(max(10, W * 0.0098), QFont.Weight.Bold)
        fmt = QFontMetricsF(ft)
        counts = rep.group_counts()
        names = {"all": "Everything", "words": "Words", "splits": "Splits",
                 "sync": "Sync"}
        self.review_tab_rects = []
        p.setFont(ft)
        x = gut
        for tab in RV.TABS:
            said = f"{names[tab]}  {counts.get(tab, 0)}"
            wide = fmt.horizontalAdvance(said) + 26
            r = QRectF(x, y, wide, fmt.height() + 12)
            on = tab == self.review_tab
            hot = r.contains(self.mouse_pos)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(234, 234, 234, 30 if on else 14 if hot else 0))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setPen(QColor(234, 234, 234, 235 if on else 130))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), said)
            self.review_tab_rects.append((tab, r))
            x += wide + 8
        return y + fmt.height() + 22

    def review_set_tab(self, tab: str) -> None:
        if tab == self.review_tab:
            return
        self.review_tab = tab
        self.review_sel, self.review_scroll_target = 0, 0.0
        self._rev_key = None

    def review_fold(self, at: int, open_=None) -> None:
        """Open or close the repeats under one entry."""
        plan, *_rest = self.review_plan(self.width())
        if not plan or not 0 <= at < len(plan):
            return
        item = plan[at]
        if not item["also"]:
            return
        key = (item["row"].n, item["row"].kind)
        want = (not item["open"]) if open_ is None else bool(open_)
        if want == item["open"]:
            return
        self.review_open.add(key) if want else self.review_open.discard(key)
        self._rev_key = None

    def review_set_level(self, level: str) -> None:
        """Read one weight at a time, or all three again."""
        want = "" if level == self.review_level else level
        if want == self.review_level:
            return
        self.review_level = want
        self.review_sel, self.review_scroll_target = 0, 0.0
        self._rev_key = None
        self.toast({"error": "the things that are wrong",
                    "warn": "the doubtful things",
                    "note": "the things worth a look",
                    "": "all three weights"}[want])

    def review_move_sel(self, step: int) -> None:
        plan, *_rest = self.review_plan(self.width())
        if not plan:
            return
        self.review_sel = max(0, min(len(plan) - 1, self.review_sel + step))
        self.review_show_sel()

    def review_show_sel(self) -> None:
        """Scroll far enough that the selected row is on screen, and no further."""
        plan, total, _g, _n, _t = self.review_plan(self.width())
        if not plan or self.review_sel >= len(plan):
            return
        item = plan[self.review_sel]
        view_h = max(40.0, self.height() - self._rev_top - 12)
        if item["y"] < self.review_scroll_target:
            self.review_scroll_target = item["y"]
        elif item["y"] + item["h"] > self.review_scroll_target + view_h:
            self.review_scroll_target = item["y"] + item["h"] - view_h
        self.review_scroll_target = max(0.0, min(self.review_scroll_target,
                                                 max(0.0, total - view_h)))

    def review_seek(self) -> None:
        """Play the song from the line being looked at.

        The FIRST of a folded set: the others are the same words and the same
        fault later in the song, and the one somebody wants to hear is the one
        the page is showing them.
        """
        plan, *_rest = self.review_plan(self.width())
        if not plan or self.review_sel >= len(plan):
            return
        at = plan[self.review_sel]["row"].start
        if at is None:
            self.toast("that line has no time to play from")
            return
        self.clock.seek(max(0.0, at) + self.track_offset())
        if self.clock.status != "Playing":
            self.player_do("PlayPause")

    def review_cycle_rule(self) -> None:
        """Hold the splits to a different rule, or to none at all."""
        i = self.REV_RULES.index(self.review_rule) if self.review_rule \
            in self.REV_RULES else 0
        self.review_rule = self.REV_RULES[(i + 1) % len(self.REV_RULES)]
        self.build_review()
        said = {"auto": "whichever rule fits the language",
                "sung": "the sung rule", "hyphen": "hyphenation",
                "off": "splits not checked"}[self.review_rule]
        self.toast(f"splits: {said}")

    def review_cycle_lang(self) -> None:
        """Read the document as another language.

        Not a setting so much as a correction. Which seams a word may be cut
        at is a fact about the language it is in, and the only thing that says
        what language a document is in is a tag anybody can get wrong -- every
        Dutch file in this folder is tagged `en`, and against English rules a
        Dutch lyric looks wrong at al·les, da·mes and lan·ge, all three of
        which are exactly right. Telling it takes the Krantenwijk file in this
        folder from sixteen findings to eight.
        """
        langs = RV.languages(self.body)
        if not langs:
            return
        here = self.review_lang or langs[0]
        i = langs.index(here) if here in langs else 0
        self.review_lang = langs[(i + 1) % len(langs)]
        self.build_review()
        self.toast(f"reading it as {self.review_lang}"
                   + ("  (the file's own tag)" if self.review_lang == langs[0]
                      else ""))

    def copy_review(self) -> None:
        if self.review is None:
            return
        QApplication.clipboard().setText(self.review.as_text())
        self.toast(f"copied the review — {self.review.summary()}")

    def review_key(self, ev) -> None:
        k = ev.key()
        shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_Y):
            self.close_review()
        elif k == Qt.Key.Key_Down:
            self.review_move_sel(1)
        elif k == Qt.Key.Key_Up:
            self.review_move_sel(-1)
        elif k in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
            self.review_move_sel(8 if k == Qt.Key.Key_PageDown else -8)
        elif k == Qt.Key.Key_Home:
            self.review_sel = 0
            self.review_show_sel()
        elif k == Qt.Key.Key_End:
            self.review_sel = max(0, len(self.review_plan(self.width())[0]) - 1)
            self.review_show_sel()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.review_seek()
        elif k == Qt.Key.Key_Right:
            self.review_fold(self.review_sel, True)
        elif k == Qt.Key.Key_Left:
            self.review_fold(self.review_sel, False)
        elif k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            at = RV.TABS.index(self.review_tab) if self.review_tab in RV.TABS else 0
            step = -1 if k == Qt.Key.Key_Backtab or shift else 1
            self.review_set_tab(RV.TABS[(at + step) % len(RV.TABS)])
        elif k in (Qt.Key.Key_1, Qt.Key.Key_2, Qt.Key.Key_3):
            self.review_set_level(RV.LEVELS[(Qt.Key.Key_1, Qt.Key.Key_2,
                                             Qt.Key.Key_3).index(k)])
        elif k == Qt.Key.Key_0:
            self.review_set_level("")
        elif k == Qt.Key.Key_A and not shift:
            self.review_all = not self.review_all
            self.review_sel, self.review_scroll_target = 0, 0.0
            self._rev_key = None
            self.toast("every line" if self.review_all
                       else "only the lines with something to say")
        elif k == Qt.Key.Key_K and not shift:
            got = self.review_fixes(self.review_sel)
            if got:
                self.review_keep(got[0])
            else:
                self.toast("K rules on a syllable seam the rules refused — "
                           "this line has none to rule on")
        elif k == Qt.Key.Key_K and shift:
            self.review_unkeep()
        elif k == Qt.Key.Key_S and not shift:
            self.review_cycle_rule()
        elif k == Qt.Key.Key_L and not shift:
            self.review_cycle_lang()
        elif k == Qt.Key.Key_V and not shift:
            self.toggle_review_marks()
        elif k == Qt.Key.Key_C and not shift:
            self.copy_review()
        elif k == Qt.Key.Key_R and not shift:
            self.review = self.review_at = None
            self.build_review()
            self.toast("read again")
        else:
            self.transport_key(k, shift)
        self.update()

    def review_wheel(self, ev) -> None:
        self.review_scroll_target -= ev.angleDelta().y() * 0.8

    def review_press(self, ev) -> None:
        for k, rect in getattr(self, "review_keep_rects", []):
            if rect.contains(ev.position()):
                self.review_keep(k)
                self.update()
                return
        for other, rect in getattr(self, "review_also_rects", []):
            if rect.contains(ev.position()) and other.start is not None:
                self.clock.seek(max(0.0, other.start) + self.track_offset())
                if self.clock.status != "Playing":
                    self.player_do("PlayPause")
                self.update()
                return
        for at, rect in getattr(self, "review_fold_rects", []):
            if rect.contains(ev.position()):
                self.review_fold(at)
                self.update()
                return
        for tab, rect in getattr(self, "review_tab_rects", []):
            if rect.contains(ev.position()):
                self.review_set_tab(tab)
                self.update()
                return
        for level, rect in getattr(self, "review_level_rects", []):
            if rect.contains(ev.position()):
                self.review_set_level(level)
                self.update()
                return
        for i, rect in getattr(self, "review_rects", []):
            if not rect.contains(ev.position()):
                continue
            if i == self.review_sel:
                self.review_seek()
            else:
                self.review_sel = i
            self.update()
            return

    def review_move(self, ev) -> None:
        self.last_move = mono()
        over = any(r.contains(ev.position())
                   for _i, r in list(getattr(self, "review_rects", []))
                   + list(getattr(self, "review_tab_rects", []))
                   + list(getattr(self, "review_level_rects", []))
                   + list(getattr(self, "review_fold_rects", []))
                   + list(getattr(self, "review_also_rects", []))
                   + list(getattr(self, "review_keep_rects", [])))
        self.set_cursor(Qt.CursorShape.PointingHandCursor if over
                        else Qt.CursorShape.ArrowCursor)

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
        self.local_hits, self.gq_hits = [], []
        self.gq_query = self.gq_asked = ""
        self.gq_busy, self.gq_matching = False, None
        self.gq_timer.stop()
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
        self.local_hits = self.index.search(self.query, self.clock.tid)
        self.wind_genius(self.query)
        self.merge_hits()
        self.hit_top = 0

    def wind_genius(self, typed: str) -> None:
        """Start the countdown to asking Genius, or drop what it last said.

        Called on every keystroke in either box: the countdown is restarted so
        the request only goes once the typing stops (ask_genius), and a box
        emptied back below a searchable query forgets the answer to the one
        before it.
        """
        if len(typed.strip()) < 3:
            self.gq_timer.stop()
            self.gq_hits, self.gq_query, self.gq_asked = [], "", ""
            self.gq_busy = False
        else:
            self.gq_timer.start()

    def search_text(self) -> str:
        """Whatever search box is on screen -- the overlay's, or the browse
        tab's. Both search the lyrics, so both ask Genius."""
        if self.show_search:
            return self.query.strip()
        if self.view == "browse" and self.browse_tab == "search":
            return self.bq.strip()
        return ""

    def ask_genius(self) -> None:
        """Search Genius for the words in the box, GENIUS_TYPED_MS after the
        last one was typed. The index only holds songs whose lyrics are already
        cached here, so a line from a song never played on this machine found
        nothing at all; Genius searches the lyrics themselves."""
        q = self.search_text()
        if len(q) < 3 or q == self.gq_asked:
            return
        self.gq_asked, self.gq_busy = q, True
        self.fetcher.request_gsearch(q)
        self.update()

    def on_gsearch(self, query: str, results) -> None:
        if query != self.search_text():
            return
        self.gq_busy = False
        self.gq_query, self.gq_hits = query, list(results or [])
        self.merge_hits()
        self.merge_browse_hits()
        self.update()

    def genius_rows(self, typed: str, known) -> list[dict]:
        """The Genius hits worth showing under a box that says `typed`.

        Dropped from them is anything `known` already covers: a song this
        machine has the lyrics to, or one the catalogue search itself found,
        is better as that row -- it has a Spotify id already and needs no
        matching. `known` is (title, artist) pairs in GR.key form.
        """
        if not self.gq_query or not typed.startswith(self.gq_query):
            return []
        out = []
        for g in self.gq_hits:
            pair = (GR.key(g.get("title") or ""), GR.key(g.get("artist") or ""))
            if pair in known:
                continue
            out.append(g)
        return out

    def merge_hits(self) -> None:
        """One order over both sources, best answer first.

        Cached and Genius rows are scored the same way (score_local, and
        GR.rank_hit before them), so a song whose NAME is what was typed comes
        above songs that merely quote the words, whichever side it came from.
        The song playing right now stays pinned at the top regardless.

        A song that is both is shown once, as the cached hit: that one can be
        jumped to inside the lyrics, and it already knows its Spotify id.
        """
        hits = list(self.local_hits)
        here = {(GR.key(h.get("title") or ""), GR.key(h.get("artist") or ""))
                for h in hits if h.get("title")}
        for g in self.genius_rows(self.query.strip(), here):
            line = g.get("line") or ""
            hits.append({"id": "", "line": line or (g.get("title") or ""),
                         "idx": 0, "title": g.get("title") if line else "",
                         "artist": g.get("artist") or "", "next": "",
                         "here": False, "why": "genius", "genius": g,
                         "score": g.get("score") or 0.0})
        hits.sort(key=lambda h: (not h["here"], -(h.get("score") or 0.0)))
        self.hits = hits
        self.hit_idx = min(self.hit_idx, max(0, len(self.hits) - 1))

    def activate_hit(self) -> None:
        if not self.hits:
            return
        hit = self.hits[self.hit_idx]
        if hit.get("why") == "genius":
            self.gq_matching = hit["genius"]
            self.fetcher.request_gmatch(hit["genius"])
            self.toast("finding it on Spotify…")
            return
        if hit["here"]:
            for ln in self.lines:
                if ln["start"] is not None and SL_norm(ln["text"]) == SL_norm(hit["line"]):
                    self.clock.seek(ln["start"] + self.track_offset())
                    self.user_scroll_until = 0.0
                    break
            self.toast("jumped to line")
        else:
            self.fetcher.request_play(f"spotify:track:{hit['id']}")
            self.skip_at = mono()
            self.toast("playing…")
        self.show_search = False

    def on_gmatch(self, hit, track) -> None:
        """What Spotify had for the Genius song that was clicked."""
        want = self.gq_matching or {}
        if not hit or hit.get("id") != want.get("id"):
            return
        self.gq_matching = None
        name = " — ".join(x for x in (hit.get("title") or "",
                                      hit.get("artist") or "") if x)
        if not track or not track.get("uri"):
            self.toast(f"not on Spotify: {name}" if name else "not on Spotify")
            return
        self.fetcher.request_play(track["uri"])
        self.skip_at = mono()
        self.toast("playing " + (track.get("name") or name))
        self.show_search = False
        if self.view == "browse":
            self.close_browse()

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
        self._paint_field(p, self.q_field,
                          QRectF(box.x() + 26, box.y() + 18,
                                 box.width() - 52, fmb.height() * 1.4),
                          fmb, "search every cached lyric…")
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 115))
        n = len(self.index.songs)
        pos = f"{self.hit_idx + 1}/{len(self.hits)}  " if len(self.hits) > 10 else ""
        note = (f"{pos}{len(self.hits)} of {n} songs" if self.query else
                (f"{n} songs indexed" if n else f"indexing… {self.index_n}"))
        gn = sum(1 for h in self.hits if h.get("why") == "genius")
        if self.gq_busy:
            note += " · asking Genius…"
        elif gn:
            note += f" · {gn} from Genius"
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
            elif hit.get("why") == "genius":
                who = "Genius" + (f" · {who}" if who else "")
            elif not who:
                who = hit.get("next") or hit["id"]
            p.drawText(QRectF(row.x() + 14, ry + rowh * 0.55, row.width() - 28, rowh * 0.4),
                       int(Qt.AlignmentFlag.AlignLeft),
                       fms.elidedText(who, Qt.TextElideMode.ElideRight, row.width() - 28))
            self.search_rects.append((i, row))

    def info_rows(self) -> list[tuple[str, str]]:
        m, doc = self.clock.meta, SL.payload(self.body or {})
        syl = sum(len(l.get("syls") or []) for l in self.lines)
        tid = self.clock.tid or ""
        rows = [(name, value) for name, value in
                (("Title", m.get("title", "")), ("Artist", self.artist()),
                 ("Album", m.get("album", ""))) if str(value).strip()]
        if doc:
            rows += [
                ("Lyrics", {"syllable": "word-synced", "line": "line-synced",
                            "static": "unsynced"}.get(LS.quality(doc), "—")),
                ("Language", self._said_language(doc)),
                ("Lines", f"{len([l for l in self.lines if not l.get('dots')])}"
                          + (f", {syl} syllables" if syl else "")),
            ]
            if any(l.get("pieces_roman") for l in self.lines):
                rows.append(("Romanised", "yes"))
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
        if tid in self.offsets:
            rows.append(("Track offset", f"{self.offsets[tid]:+.2f}s by hand"))
        hold = self.clock.resume_hold
        if hold:
            rows.append((
                "Resume hold",
                f"{hold:+.3f}s carried"
                + (f"  (measured, up to {self.clock.unpause_delay:.2f}s)"
                   if self.clock.unpause_delay > 0 else
                   f"  (measured, plus {self.clock.unpause_delay:+.2f}s stated)")
                + (f", {hold - self.track_offset():+.3f}s"
                   f" behind the player with the offset"
                   if self.track_offset() else "")))
        if self.est:
            spread = float(self.est.get("spread", EST_RANGE * 2.0))
            if not self.auto_time:
                why = "  (auto timing off)"
            elif tid in self.offsets:
                why = "  (hand correction wins)"
            elif self.est["conf"] < EST_CONF_MIN:
                why = f"  (conf {self.est['conf']:.2f}, too close to call)"
            elif spread > EST_AGREE:
                why = f"  (halves disagree by {spread:.2f}s, not trusted)"
            elif abs(self.est["delta"]) > EST_MAX:
                why = f"  (past {EST_MAX:.2f}s, too big to trust)"
            else:
                why = ""
            rows.append(("Measured",
                         f"{self.est['delta']:+.2f}s from "
                         f"{self.est['n']} entries{why}"))
        elif self.beat.segs and self.raw:
            rows.append(("Measured", "not enough clean vocal entries"))
        if self.device:
            rows.append(("Output", f"{self.device_name}  "
                                   f"({self.offset:+.2f}s global"
                                   + (f", {self.player}" if self.player else "")
                                   + ")"))
        if self.any_player:
            rows.append(("Player", self.clock.io.name))
        if tid:
            rows.append(("Track id", tid))
        return [(k, v) for k, v in rows
                if str(v).strip() and str(v).strip() not in ("—", "none")]

    def _paint_info(self, p, W: int, H: int) -> None:
        rows = self.info_rows()
        self.info_rects = []
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
            self.info_rects.append(
                (QRectF(box.x() + 12, ry, box.width() - 24, rowh), k, v))
            p.setFont(fb)
            p.setPen(QColor(234, 234, 234, 200))
            p.drawText(QRectF(box.x() + 26, ry, keyw, rowh),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), k)
            p.setFont(f)
            p.setPen(QColor(234, 234, 234, 150))
            p.drawText(QRectF(box.x() + 26 + keyw, ry, valw, rowh),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                       fm.elidedText(v, Qt.TextElideMode.ElideRight, valw - 8))

    def copy_info_row(self, pos) -> bool:
        """Take the value of whichever row was clicked. False if none was.

        The panel is the one place in the window where the answer to a
        question is a string somebody wants elsewhere -- a track id to paste
        into a search, an ISRC, the songwriters, the name of the output. It
        stays open afterwards: copying one of them is usually the start of
        copying another.
        """
        for rect, key, value in getattr(self, "info_rects", []):
            if not rect.contains(pos):
                continue
            text = str(value).strip()
            if not text:
                return False
            QApplication.clipboard().setText(text)
            self.toast(f"copied {key.lower()}")
            self.update()
            return True
        return False

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
        where, asked = save_dir(self.args.save_dir)
        path = where / f"{name or 'lyric'} card.png"
        try:
            wrote = pm.save(str(path))
            QApplication.clipboard().setPixmap(pm)
            if not wrote:
                self.toast(f"card copied · could not write {path}")
            else:
                self.toast(f"card copied · {path.name if asked else path}")
        except Exception as exc:
            self.toast(f"card failed: {exc}")

    def open_editor(self, mode: str = "romaji", idx: int | None = None) -> None:
        """Correct a line's romanisation. Defaults to whichever line is sounding,
        since that is the one you noticed was wrong; `idx` names another, for a
        caller that already knows which line was pointed at."""
        self.edit_mode = mode
        if mode in ("token", "font") or mode in PEOPLE_KEYS:
            if mode == "font":
                self.edit_text = self.font_name
                self.edit_for = f"currently drawing with {self.family}"
            elif mode in PEOPLE_KEYS:
                self.edit_text = ", ".join(LS.name_list(getattr(self, mode)))
                self.edit_ids = []
                who = str((self.this_sync_by() or {}).get("name") or "").strip()
                self.edit_for = (f"{PEOPLE_KEYS[mode]} — this one is timed "
                                 f"by {who}" if who else PEOPLE_KEYS[mode])
            else:
                self.edit_text = self.genius_token
                self.edit_for = "Genius API token"
            self.edit_pristine, self.editing = True, True
            self.said_clipped(self.edit_field)
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
        self.edit_pristine, self.editing = True, True
        self.said_clipped(self.edit_field)
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
        else:
            self.edit_field.replace(text)
        self.said_clipped(self.edit_field)
        self.edit_pristine = False

    @staticmethod
    def _editor_for(key: str, kind: str) -> str:
        """Which text editor a menu row opens."""
        if key in PEOPLE_KEYS:
            return key
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
            self.drop_pixmaps()
            self._marq.clear()
            if self.font_name and not found:
                self.toast(f"no font called {self.font_name!r} — using {self.family}")
            else:
                self.toast(f"font: {self.family}")
            return
        if self.edit_mode in PEOPLE_KEYS:
            self.set_people(self.edit_mode, self.edit_text, knew=self.edit_ids)
            self.edit_ids = []
            self.editing = False
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

    def _paint_field(self, p, fld, rect: QRectF, fm, hint: str = "") -> None:
        """Draw a hand-made text box in the font and colour already set on
        the painter: the text, the selection under it, and the caret,
        scrolled so the caret stays in view however long the text runs -- and
        tell the field where all of that landed, so the next click can be
        placed in it.

        The only place any of this is written down. The romanisation editor,
        the lyric search and the Spotify search all come through here, which
        is what keeps the caret, the selection and a click on the text
        meaning the same thing in all three.
        """
        pad = 2.0
        wide = max(20.0, rect.width() - pad * 2)
        before = fm.horizontalAdvance(fld.text[:fld.caret])
        shift = max(0.0, before - (wide - 12))
        x0 = rect.x() + pad - shift
        fld.laid_out(x0, fm, rect)
        align = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        p.save()
        p.setClipRect(rect)
        if fld.text:
            lo, hi = fld.span()
            if hi > lo:
                p.save()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(120, 170, 255, 70))
                p.drawRect(QRectF(x0 + fm.horizontalAdvance(fld.text[:lo]),
                                  rect.y() + 2,
                                  fm.horizontalAdvance(fld.text[lo:hi]),
                                  rect.height() - 4))
                p.restore()
            p.drawText(QRectF(x0, rect.y(), fm.horizontalAdvance(fld.text) + 8,
                              rect.height()), align, fld.text)
        elif hint:
            p.save()
            p.setPen(QColor(234, 234, 234, 110))
            p.drawText(QRectF(x0, rect.y(), wide, rect.height()), align, hint)
            p.restore()
        if int(mono() * 2) % 2:
            p.setPen(QPen(p.pen().color(), 1.6))
            p.drawLine(QPointF(x0 + before, rect.y() + 3),
                       QPointF(x0 + before, rect.bottom() - 3))
        p.restore()

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
        hint = {"token": "paste your Genius API token",
                "font": "type a font name, or leave empty for the default",
                "people_skip": "names, separated by commas — their syncs are "
                               "never used. A name TYPED here means whoever "
                               "is called that today",
                "people_pick": "names, separated by commas — their syncs win "
                               "a tie. A name TYPED here means whoever is "
                               "called that today"}.get(
                    self.edit_mode, "correct the reading for this line")
        p.drawText(QRectF(x, y, w, rowh), int(Qt.AlignmentFlag.AlignLeft),
                   fms.elidedText(hint, Qt.TextElideMode.ElideRight, w))
        y += rowh + 6
        p.setFont(f)
        p.setPen(QColor(234, 234, 234, 190))
        p.drawText(QRectF(x, y, w, fm.height() * 1.3),
                   int(Qt.AlignmentFlag.AlignLeft),
                   fm.elidedText(self.edit_for, Qt.TextElideMode.ElideRight, w))
        y += fm.height() * 1.3 + 18

        p.setFont(fb)
        btnh = fmb.height() * 1.35
        # The two lists get a second button, because the one thing typing
        # into this line cannot do is carry a Spicy Lyrics id -- see
        # judge_into_edit. It is drawn first and Paste keeps its corner, so
        # the box a person already knows does not move under them.
        said = self.judge_label() if self.edit_mode in PEOPLE_KEYS else ""
        judgew = min(w * 0.42, fms.horizontalAdvance(said) + 26) if said else 0.0
        pastew = 92.0
        fieldw = w - 108 - (judgew + 10 if judgew else 0)
        fieldh = fmb.height() * 1.4
        p.setPen(TEXT)
        self._paint_field(p, self.edit_field, QRectF(x, y, fieldw, fieldh), fmb)
        p.setPen(QColor(234, 234, 234, 55))
        p.drawLine(QPointF(x, y + fieldh + 4), QPointF(x + fieldw, y + fieldh + 4))

        def button(left: float, width: float, label: str) -> QRectF:
            r = QRectF(left, y - 4, width, btnh)
            warm = r.contains(self.mouse_pos)
            p.setPen(QColor(234, 234, 234, 90 if warm else 55))
            p.setBrush(QColor(234, 234, 234, 34 if warm else 18))
            p.drawRoundedRect(r, 8, 8)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setFont(fs)
            p.setPen(QColor(234, 234, 234, 235 if warm else 175))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter),
                       fms.elidedText(label, Qt.TextElideMode.ElideRight,
                                      width - 12))
            return r

        right = box.right() - 26
        self.paste_rect = button(right - pastew, pastew, "Paste")
        self.judge_rect = (button(right - pastew - 10 - judgew, judgew, said)
                           if judgew else None)
        p.setFont(fs)
        p.setPen(QColor(234, 234, 234, 115))
        tail = {"token": "blanked afterwards",
                "font": "empty uses the built-in stack",
                "people_skip": "empty refuses nobody",
                "people_pick": "empty prefers nobody"}.get(
                    self.edit_mode, "empty reverts to automatic")
        keys = ("Ctrl+A select all   Ctrl+V paste"
                + ("   Ctrl+K this sync's maker" if said else "")
                + f"   Enter save   {tail}   Esc cancel")
        p.drawText(QRectF(x, box.bottom() - rowh - 16, w, rowh),
                   int(Qt.AlignmentFlag.AlignLeft), keys)

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

    def blend_slot(self, key: str):
        """Which blend a Blends row stands for, or None for other rows.

        A family of its own, deliberately not folded into src_slot: a slot
        that answers there is one that can be REORDERED and whose switch is
        read through SRC_ATTR, and neither is true of a blend. The test is on
        the whole of "blend_slot" so it cannot catch the switches themselves,
        which are spelled blend_qq, blend_ne_qq and so on.
        """
        if not str(key).startswith("blend_slot"):
            return None
        try:
            return LS.blend_order(self.src_order)[int(key[10:])]
        except (ValueError, IndexError):
            return None

    def menu_row(self, i: int):
        """MENU[i], with the Sources and Blends rows resolved.

        The flat MENU is built once at import and addressed by index everywhere,
        so the rows themselves cannot be shuffled. The slots are given their
        label and their key here instead, which puts them on screen in the
        order they are actually consulted.

        The blends are numbered from LS.blend_order, which is the same call
        the chain expands them with -- so the two cannot drift apart, and
        there is no second order stored anywhere.
        """
        label, key, kind, spec = MENU[i]
        name = self.src_slot(key)
        if name is not None:
            return (f"{self.src_order.index(name) + 1}. {SRC_LABEL[name]}",
                    key, kind, spec)
        blend = self.blend_slot(key)
        if blend is not None:
            at = LS.blend_order(self.src_order).index(blend) + 1
            return f"{at}. {BLEND_LABEL[blend]}", key, kind, spec
        return label, key, kind, spec

    def src_move(self, delta: int) -> None:
        """Shift the selected provider up or down the running order."""
        label, key, kind, spec = MENU[self.menu_idx]
        if self.blend_slot(key) is not None:
            self.toast("the blends follow the sources' order — reorder those")
            return
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
        self.toast(" → ".join(SRC_LABEL[n] for n in self.src_order
                              if self.src_on(n)) or "all off")

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
            self.drop_pixmaps()
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
        blend = self.blend_slot(key)
        if blend is not None:
            return getattr(self, BLEND_KEY[blend])
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
        blend = self.blend_slot(key)
        if blend is not None:
            setattr(self, BLEND_KEY[blend], value)
            return
        if key == "sung_mode":
            self._sung = TEXT if value == SUNG_MODES[0] else None
            return
        setattr(self, key, value)
        if key == "renderer":
            self.render = RD.RENDERERS[value](self)
            self.layout_cache.clear()
            self.drop_pixmaps()
            self.scroll = self.scroll_target = 0.0
            self.content_h = 0.0
        if key == "duet_color":
            self._duet_rgb = (None if value in DUET_MODES
                              else parse_color(value, None))
        if key == "genius_auto" and value:
            self.maybe_auto_genius()
        if key in ("any_player", "song_max"):
            self.follow_players(say=key == "any_player")
        if key in ("align", "font_scale", "line_spacing", "show_panel", "roman",
                   "furigana", "view_mode", "art_side"):
            self.layout_cache.clear()
            self.drop_pixmaps()
        elif key == "blur_scale":
            self.drop_pixmaps()
        elif key in ("interlude", "merge_ms"):
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
            if key in PEOPLE_KEYS:
                named = LS.name_list(v)
                return ("nobody" if not v else named[0] if len(v) == 1 and named
                        else f"{len(v)} people")
            return str(v) if v else f"auto ({self.family})"
        if kind == "bool":
            blend = self.blend_slot(key)
            if blend is not None and v:
                off = [u for u in BLENDS[blend] if not self.src_on(u)]
                if off:
                    return f"needs {SRC_LABEL[off[0]]}"
            return "on" if v else "off"
        if kind == "choice":
            return str(v)
        if not v and key in OFF_AT_ZERO:
            return "off"
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

        note = SECTION_NOTE.get(MENU_SECTIONS[tab][0], "")
        fn = self.ui_font(max(9, W * 0.0078))
        fmn = QFontMetricsF(fn)
        noteh = 0.0
        if note and count < tall:
            noteh = min(fmn.height() * 2.6, (tall - count) * rowh)
            p.setFont(fn)
            p.setPen(QColor(234, 234, 234, 108))
            p.drawText(QRectF(box.x() + 22, box.y() + 70 + tabh,
                              box.width() - 44, noteh),
                       int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
                           | Qt.TextFlag.TextWordWrap),
                       note)

        self.menu_rects = []
        for n in range(count):
            i = first + n
            label, key, kind, spec = self.menu_row(i)
            ry = box.y() + 70 + tabh + noteh + n * rowh
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

    def flip_view(self) -> None:
        """A, between the cover's own panel and the compact strip.

        It used to switch the art panel on and off, which is the same setting
        the menu offers as a switch and is not the one anybody reaches for
        while reading: what you want is the lyrics to have the width, and
        compact is how you say that -- the cover goes to a thumbnail beside
        the title and the words take the rest.

        Through menu_set, so the menu shows what the key just did and the
        layout caches are dropped by the one place that knows which settings
        make them stale -- which is also the line the old branch was quietly
        duplicating. Whether the cover is shown at all stays a separate
        question with a separate row in the menu.
        """
        want = "compact" if self.view_mode == "regular" else "regular"
        self.menu_set("view_mode", want)
        self.toast("compact — the cover beside the title" if want == "compact"
                   else "regular — the cover in its own panel")

    def toast(self, text: str) -> None:
        self.toast_text, self.toast_until = text, mono() + 1.7

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

    def credit_at(self, pos) -> str:
        """The page a credit under the cursor points at, or "".

        Only where the credit is actually on screen: the block scrolls with
        the song, so these rects are whatever the last frame drew and nothing
        at all on a frame that did not reach them.
        """
        for rect, url in self.credit_hot:
            if rect.contains(pos):
                return url
        return ""

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
        where, asked = save_dir(self.args.save_dir)
        path = where / f"{name}.ttml"
        try:
            path.write_text(SL.render(self.body, "ttml") + "\n", encoding="utf-8")
            self.toast(f"saved {path.name}" if asked else f"saved {path}")
        except Exception as exc:
            self.toast(f"save failed: {exc}")

    def bump_font(self, delta: float) -> None:
        self.font_scale = max(0.6, min(1.9, self.font_scale + delta))
        self.layout_cache.clear()
        self.drop_pixmaps()
        self.toast(f"text {self.font_scale * 100:.0f}%")

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
        fits = max(1, MOTION_BUDGET // max(1, cap * cap * 4))
        step = max(1, -(-len(frames) // fits))
        self._motion_todo = list(frames[::step])
        self._motion_cap = cap
        self._motion_for = key
        self.motion_frames = []
        self.motion_fps = MOTION_FPS / step
        self.motion_at = mono()
        self._take_motion()

    def _take_motion(self) -> None:
        """As many frames as fit in a slice of a frame, then give the loop back.

        Scaling and converting the whole animation takes about as long as four
        frames are allowed, and it lands on a track change where there is
        nothing to spare. The list is filled a slice at a time instead;
        motion_frame reads whatever is in it, so the animation starts on the
        first slice and simply loops shorter until the rest arrives.
        """
        if self._motion_for != self.motion_key:
            self._motion_todo = []
            return
        cap = self._motion_cap
        until = time.perf_counter() + MOTION_SLICE_MS / 1000.0
        at = 0
        for img in self._motion_todo:
            if img.width() > cap:
                img = img.scaledToWidth(cap, Qt.TransformationMode.SmoothTransformation)
            self.motion_frames.append(QPixmap.fromImage(img))
            at += 1
            if time.perf_counter() >= until:
                break
        del self._motion_todo[:at]
        if self._motion_todo:
            QTimer.singleShot(0, self._take_motion)
        self.update()

    def motion_frame(self):
        """The frame due now, or None when there is no animation to play.

        A picture dropped on this song beats the animation, for as long as
        that song is playing. Both are drawn through here -- `motion_frame()
        or art_full` -- so an animated cover simply went on playing over the
        image that had just been dropped, and the drop looked like it had
        done nothing at all.
        """
        if self.dropped_art is not None and self.dropped_art == self.clock.tid:
            return None
        if not self.motion_art or not self.motion_frames:
            return None
        i = int((mono() - self.motion_at)
                * (self.motion_fps or MOTION_FPS))
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
            used, changed = self.field_key(self.bq_field, ev)
            if used:
                if changed:
                    self.refresh_browse_hits()
                return
        else:
            if k in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self.browse_scroll_target += 150 * (1 if k == Qt.Key.Key_Down else -1)
                return
            if ev.text() and ev.text().isprintable() and ev.text() != " ":
                self.browse_tab = "search"
                self.bq_field.replace(ev.text())
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
            self.player_do("PlayPause")
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Comma):
            self.clock.seek(self.clock.position() - 5)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Period):
            self.clock.seek(self.clock.position() + 5)
        elif k == Qt.Key.Key_N:
            self.skip_at = mono()
            self.player_do("Next")
        elif k == Qt.Key.Key_P:
            self.skip_at = mono()
            self.player_do("Previous")
        elif k == Qt.Key.Key_M:
            self.show_menu = not self.show_menu
        else:
            return False
        return True

    def set_browse_tab(self, tab: str) -> None:
        """Switch tab and fetch whatever that tab needs, if it has gone stale."""
        self.browse_tab = tab
        self.browse_scroll = self.browse_scroll_target = 0.0
        if tab == "queue" and mono() - self.queue_at > 5:
            self.fetcher.request_queue()

    def browse_press(self, ev) -> None:
        if self.browse_tab == "search" and self.bq_field.press(
                ev.position(),
                bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self.field_drag = self.bq_field
            return
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
        self.last_move = mono()
        hit = self.browse_hit(ev.position())
        if hit != self.browse_hover:
            self.browse_hover = hit
            self.update()
        if self.browse_tab == "search" and self.bq_field.under(ev.position()):
            self.set_cursor(Qt.CursorShape.IBeamCursor)
            return
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
        if not uri and payload.get("genius"):
            self.gq_matching = payload["genius"]
            self.fetcher.request_gmatch(payload["genius"])
            self.toast("finding it on Spotify…")
            return
        if not uri and payload.get("id"):
            uri = f"spotify:track:{payload['id']}"
        if not uri:
            return
        if kind == "queue":
            self.fetcher.request_skip(uri, payload.get("uid") or "")
        else:
            self.fetcher.request_play(uri)
        self.skip_at = mono()
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
        self.wind_genius(self.bq)
        self.merge_browse_hits()
        if len(self.bq) >= 2:
            self.bq_busy = True
            self.fetcher.request_catsearch(self.bq)
        else:
            self.bq_busy = False

    def merge_browse_hits(self) -> None:
        """The catalogue, then this machine's own lyrics, then the songs only
        Genius could name -- those last are the ones a typed LINE finds, since
        Spotify's search reads names and not words."""
        hits = list(self.bq_cat) + list(self.bq_local)
        known = {(GR.key(h.get("name") or ""), GR.key(h.get("sub") or ""))
                 for h in hits}
        for g in self.genius_rows(self.bq.strip(), known):
            hits.append({"section": "On Genius", "uri": "", "id": "",
                         "name": g.get("title") or "",
                         "sub": (g.get("artist") or "")
                                + (f" · \u201c{g['line'][:60]}\u201d"
                                   if g.get("line") else ""),
                         "art": art_url(g.get("art") or ""), "ms": 0,
                         "genius": g})
        self.bq_hits = hits
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
        self.queue_at = mono()
        self.fetch_ahead_scan()
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
            self.discover_at = mono()
            self.build_home()
            self.update()

    def on_recents(self, tracks, contexts) -> None:
        self.recents_tracks = list(tracks or [])
        self.recents_ctx = list(contexts or [])
        self.recents_at = mono()
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
        if self.view == "review" and not self.overlay():
            self.review_wheel(ev)
            self.update()
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
        if self.vol_wheel(ev):
            return
        if (self.view == "lyrics" and self.lines
                and self.render.wheel(ev.angleDelta().y())):
            self.user_scroll_until = mono() + 4.0
            self.update()
            return
        self.scroll_target -= ev.angleDelta().y() * 0.7
        self.user_scroll_until = mono() + 4.0

    VOL_NOTCH = 0.05
    VOL_GAP = 0.065

    def flush_volume(self) -> None:
        """Send what the wheel has asked for, at most every `VOL_GAP`.

        Called from the wheel, so the first notch of a turn goes out at once,
        and again from `tick`, which is what gets the LAST one out: the wheel
        has stopped by then and there is nobody else to send it.
        """
        if self.vol_want is None:
            return
        now = mono()
        if now - self._vol_sent_at < self.VOL_GAP:
            return
        want, self.vol_want = self.vol_want, None
        self._vol_sent_at = now
        self.clock.set_volume(want)

    def vol_wheel(self, ev) -> bool:
        """The volume, if the pointer is on its bar. Otherwise not ours.

        Last of the wheel's branches on purpose. Everything above it has
        already turned the wheel away in the views where this rect means
        nothing -- browse and detail paint through `_paint_browse`, which
        never touches `vol_rect`, so the one left over from the last lyric
        frame would still be sitting there claiming a strip of a screen that
        is not showing it.

        Hit-tested with the same slack the drag and the hover use. The bar is
        drawn four pixels tall because it is the control you reach for least,
        and a wheel is aimed no better than a click is.
        """
        if self.vol_rect is None or self.clock.volume is None:
            return False
        if not self.vol_rect.adjusted(-8, -9, 8, 9).contains(ev.position()):
            return False
        at = self.vol_want if self.vol_want is not None else self.clock.volume
        self.vol_want = max(0.0, min(1.0, at + self.VOL_NOTCH
                                     * ev.angleDelta().y() / 120.0))
        self.toast(f"volume {self.vol_want * 100:.0f}%")
        self.last_move = mono()
        self.flush_volume()
        self.update()
        return True

    def mouseMoveEvent(self, ev) -> None:
        self.last_move = mono()
        pos = self.mouse_pos = ev.position()
        if self.field_drag is not None:
            self.field_drag.drag_to(pos)
            self.update()
            return
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
        if self.view == "review" and not self.overlay():
            self.review_move(ev)
            self.update()
            return
        if self.editing:
            self.set_cursor(
                Qt.CursorShape.PointingHandCursor
                if ((self.paste_rect and self.paste_rect.contains(pos))
                    or (self.judge_rect and self.judge_rect.contains(pos)))
                else (Qt.CursorShape.IBeamCursor if self.edit_field.under(pos)
                      else Qt.CursorShape.ArrowCursor))
            return
        if self.show_search:
            if self.q_field.under(pos):
                self.set_cursor(Qt.CursorShape.IBeamCursor)
                return
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
        over_credit = not (over_bar or over_vol) and bool(self.credit_at(pos))
        idx = -1 if (over_bar or over_vol or over_credit) else self.line_at(
            pos.x(), pos.y())
        if idx != self.hover_idx:
            self.hover_idx = idx
        self.set_cursor(
            Qt.CursorShape.PointingHandCursor
            if over_bar or over_vol or over_credit or (idx >= 0 and self.synced)
            else Qt.CursorShape.ArrowCursor
        )

    def mousePressEvent(self, ev) -> None:
        pos = ev.position()
        btn = ev.button()
        shift = ev.modifiers() & Qt.KeyboardModifier.ShiftModifier
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
        if self.view == "review" and not self.overlay():
            self.review_press(ev)
            return
        if self.show_help or self.show_info:
            for i, r in self.help_tab_rects:
                if r.contains(pos):
                    self.help_tab = i
                    self.update()
                    return
            if self.show_info and self.copy_info_row(pos):
                return
            self.show_help = self.show_info = False
            return
        if self.editing:
            if self.judge_rect and self.judge_rect.contains(pos):
                self.judge_into_edit()
            elif self.paste_rect and self.paste_rect.contains(pos):
                self.paste_into_edit()
            elif self.edit_field.press(pos, bool(shift)):
                self.field_drag = self.edit_field
            return
        if self.show_search:
            if self.q_field.press(pos, bool(shift)):
                self.field_drag = self.q_field
                return
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
        url = self.credit_at(pos)
        if url:
            self.open_url(url)
            self.toast("opened their page")
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
        # Whose sync this is, where the document says -- the same opinion K
        # and the two Sources rows write, offered where the person is already
        # looking at the words they have the opinion about.
        who = self.this_sync_by()
        named = str((who or {}).get("name") or "").strip()
        act_pick = act_skip = None
        if who and (named or who.get("id")):
            shown = named or "this maker"
            menu.addSeparator()
            act_pick = menu.addAction(
                f"Stop preferring {shown}" if self.on_people("people_pick", who)
                else f"Prefer {shown}'s syncs")
            act_skip = menu.addAction(
                f"Stop refusing {shown}" if self.on_people("people_skip", who)
                else f"Refuse {shown}'s syncs")
        chosen = menu.exec(gpos)
        if chosen is None:
            return
        if chosen is act_pick:
            self.judge_sync(prefer=True)
        elif chosen is act_skip:
            self.judge_sync(prefer=False)
        elif chosen is act_copy:
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
        self.field_drag = None
        if self.drag_frac is not None:
            dur = self.clock.meta.get("length", 0.0)
            if dur:
                self.clock.seek(self.drag_frac * dur)
            self.drag_frac = None
            self.user_scroll_until = 0.0
        self.vol_drag = None

    def mouseDoubleClickEvent(self, ev) -> None:
        fld = self.field_at(ev.position())
        if fld is not None:
            fld.pick_word(ev.position())
            self.update()
            return
        if (self.show_menu or self.show_search or self.show_info
                or self.show_help or self.editing
                or self.view in ("browse", "review")):
            return
        if self.on_panel(ev.position().x()):
            self.toggle_fullscreen()

    def field_key(self, fld, ev) -> tuple[bool, bool]:
        """One key press into one of the hand-drawn boxes: whether the box
        had a use for it, and whether what is in it changed.

        Both answers are needed and they are not the same one. A caller only
        searches again when the TEXT changed -- a caret key is not a new
        search -- and browse only keeps the key from the transport when the
        box USED it, so Left still seeks on a tab with no box on it.
        """
        was = fld.text
        used = fld.key(ev)
        self.said_clipped(fld)
        return used, fld.text != was

    def said_clipped(self, fld) -> None:
        """Say so if the last thing to go in was too long for the box.

        Worth a line of its own because the alternative is silence: a token
        pasted into a full box keeps its first however-many characters and
        looks like a token, and the first anybody would know of it is Genius
        refusing them.
        """
        if not fld.clipped:
            return
        fld.clipped = False
        self.toast(f"that is longer than this box takes "
                   f"({fld.limit} characters)")

    def field_at(self, pos) -> Field | None:
        """The text box under the pointer, if one is both on show and hit.

        Which box is on show is asked the same way every other input handler
        asks it -- the editor first, then the overlay, then the view -- so a
        click cannot land in a field that is not being drawn.
        """
        if self.editing:
            fld = self.edit_field
        elif self.show_search:
            fld = self.q_field
        elif (self.view == "browse" and not self.overlay()
                and self.browse_tab == "search"):
            fld = self.bq_field
        else:
            return None
        return fld if fld.under(pos) else None

    def enter_fullscreen(self) -> None:
        """Fill the screen, and on Windows actually fill it.

        Everywhere else showFullScreen is the whole of this.

        On Windows it leaves a border, and the border is DWM's rather than
        Qt's -- Windows 11 draws a one-pixel line round a top-level window
        and rounds its corners, and it goes on doing both to a window that
        has been given the screen. Neither is a window style anybody can drop:
        FramelessWindowHint does not remove them, it INVITES them, because a
        popup with no frame of its own is exactly the shape DWM decorates. So
        that was tried and it made the report worse -- a border, and now
        rounded corners on it too.

        The two attributes below are the ones that actually answer: do not
        round this window, and draw no border colour on it. Both are Windows
        11 and both are refused with a shrug on Windows 10, which is why the
        call is wrapped and its result ignored.

        The geometry is then asked for outright as the screen's rectangle,
        which is a separate fix for a separate thing: at a fractional display
        scale the logical-to-physical rounding can leave a strip of desktop
        showing along one edge with nothing decorating anything.
        """
        self.showFullScreen()
        if os.name == "nt":
            _no_dwm_border(self)
            scr = self.screen() or QApplication.primaryScreen()
            if scr is not None and self.geometry() != scr.geometry():
                self.setGeometry(scr.geometry())

    def leave_fullscreen(self) -> None:
        """Back to a window. Nothing to undo: the window was never re-created
        and its own frame was never taken off, so the corner and border
        attributes are all there is, and they are set again on the way back
        out of fullscreen because Windows re-decorates the frame it restores."""
        self.showNormal()
        if os.name == "nt":
            _no_dwm_border(self, rounded=True)

    def on_panel(self, x: float) -> bool:
        """Whether a click at this x landed on the album art panel."""
        panel = self.panel_width()
        return bool(panel) and self.panel_x() <= x < self.panel_x() + panel

    def toggle_fullscreen(self) -> None:
        self.leave_fullscreen() if self.isFullScreen() else self.enter_fullscreen()
        self.set_cursor(Qt.CursorShape.ArrowCursor)
        self.last_move = mono()

    def keyPressEvent(self, ev) -> None:
        k = ev.key()
        shift = ev.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if k == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            return
        if self.view == "browse" and not self.overlay():
            self.browse_key(ev)
            return
        if self.view == "review" and not self.overlay():
            self.review_key(ev)
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
            elif k == Qt.Key.Key_K and ctrl and self.edit_mode in PEOPLE_KEYS:
                self.judge_into_edit()
            else:
                if self.field_key(self.edit_field, ev)[1]:
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
            else:
                if self.field_key(self.q_field, ev)[1]:
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
        if self.show_help and k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
                                    Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.help_tab_step(
                -1 if k in (Qt.Key.Key_Backtab, Qt.Key.Key_Left) else +1)
            return
        if k in (Qt.Key.Key_Slash, Qt.Key.Key_F3):
            self.open_browse("search") if not shift else self.open_search()
        elif k == Qt.Key.Key_Home:
            self.open_browse("home")
        elif k == Qt.Key.Key_M:
            self.show_menu, self.show_help = True, False
        elif k == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_Escape:
            if self.show_help or self.show_info:
                self.show_help = self.show_info = False
            elif self.isFullScreen():
                self.leave_fullscreen()
            else:
                self.close()
        elif k == Qt.Key.Key_Q:
            self.close()
        elif k in (Qt.Key.Key_H, Qt.Key.Key_Question, Qt.Key.Key_F1):
            self.show_help = not self.show_help
            self.show_menu = False
        elif k == Qt.Key.Key_Space:
            self.player_do("PlayPause")
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
            self.skip_at = mono()
            self.player_do("Next")
        elif k == Qt.Key.Key_P:
            self.skip_at = mono()
            self.player_do("Previous")
        elif k == Qt.Key.Key_X:
            self.clock.resync()
            self.toast("resynced")
        elif k == Qt.Key.Key_D:
            order = ["art", "mesh", "solid"]
            self.bg_mode = order[(order.index(self.bg_mode) + 1) % len(order)]
            self.toast(f"background: {self.bg_mode}")
        elif k == Qt.Key.Key_V and shift:
            i = VIZ_MODES.index(self.viz_mode) if self.viz_mode in VIZ_MODES else 0
            self.viz_mode = VIZ_MODES[(i + 1) % len(VIZ_MODES)]
            self._scene_key = self._viz_key = None
            if not self.viz:
                self.viz = self._viz_was or self.args.viz or 1.0
            self.toast(f"visualizer: {self.viz_mode}")
        elif k == Qt.Key.Key_V:
            if self.viz:
                self._viz_was, self.viz = self.viz, 0.0
            else:
                self.viz = self._viz_was or self.args.viz or 1.0
            self._scene_key = None
            need = self.VIZ_NEEDS.get(self.viz_mode, "pitch")
            if self.viz and not getattr(self.beat, need):
                self.toast("visualizer: on, no analysis for this track")
            else:
                self.toast(f"visualizer: {'on' if self.viz else 'off'}")
        elif k == Qt.Key.Key_L:
            order = ["left", "center", "right"]
            self.align = order[(order.index(self.align) + 1) % len(order)]
            self.layout_cache.clear()
            self.drop_pixmaps()
            self.toast(f"align: {self.align}")
        elif k == Qt.Key.Key_E:
            self.pop = 0.0 if self.pop else (self.args.pop or 1.0)
            self.toast(f"word pop {'off' if not self.pop else 'on'}")
        elif k == Qt.Key.Key_O:
            if self.focus:
                self._focus_on = self.focus
                self.focus = 0
            else:
                self.focus = self._focus_on
            self.toast("focus off" if not self.focus else f"focus ±{self.focus} lines")
        elif k == Qt.Key.Key_U:
            self._sung = None if self._sung else TEXT
            self.toast(f"sung colour: {'album tint' if self._sung is None else 'white'}")
        elif k == Qt.Key.Key_A:
            self.flip_view()
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
            self.drop_pixmaps()
            self.toast(f"depth blur {'off' if not self.blur_scale else 'on'}")
        elif k == Qt.Key.Key_K:
            self.judge_sync(prefer=not shift)
        elif k == Qt.Key.Key_C:
            self.copy_lyrics(bool(shift))
        elif k == Qt.Key.Key_S:
            self.share_card() if shift else self.save_lyrics()
        elif k == Qt.Key.Key_I:
            self.show_info = not self.show_info
            self.show_menu = self.show_help = False
        elif k == Qt.Key.Key_Y:
            self.toggle_review_marks() if shift else self.open_review()
        elif k == Qt.Key.Key_R:
            if shift:
                self.open_editor()
            else:
                if self.clock.tid:
                    LS.forget(self.clock.tid)
                whose = (self.dropped_from or "the editor"
                         if self.dropped is not None
                         and self.dropped == self.clock.tid else "")
                self.reset_track("Reloading…", keep=True)
                self.toast(f"reloading this song's own lyrics — {whose} "
                           f"draws over it again" if whose else
                           "reloading lyrics")
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
            self.on_top = on
            self.enter_fullscreen() if full else self.show()
            ok = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == on
        self.on_top = on if ok else False
        if ok:
            self.toast(f"always on top {'on' if on else 'off'}")
        else:
            self.toast("this desktop will not keep a window on top")

    def resizeEvent(self, _ev) -> None:
        self.layout_cache.clear()

    def settings_dict(self) -> dict:
        return {
                "offset": round(self.offset, 3),
                "offsets_device": self.device_offsets(),
                "font_scale": round(self.font_scale, 2),
                "blur": self.blur_scale,
                "glow": self.glow_scale,
                "word_glow": self.word_glow,
                "syll_hold": round(self.syll_hold, 2),
                "panel": self.show_panel,
                "art_side": self.art_side,
                "view_mode": self.view_mode,
                "volume_bar": bool(self.show_volume),
                "duet_color": self.duet_color,
                "font": self.font_name,
                "src_order": ",".join(self.src_order),
                "motion_art": bool(self.motion_art),
                "bg": self.bg_mode,
                "bg_fade": float(self.bg_fade),
                "mesh_style": self.mesh_style,
                "mesh_tint": round(self.mesh_tint, 2),
                "mesh_spread": round(self.mesh_spread, 2),
                "mesh_colors": int(self.mesh_colors),
                "viz": round(self.viz, 2),
                "viz_mode": self.viz_mode,
                "bg_dim": round(self.bg_dim, 2),
                "bg_motion": round(self.bg_motion, 2),
                "align": self.align,
                "pop": self.pop,
                "rise": round(self.rise, 2),
                "line_drop": round(self.line_drop, 2),
                "renderer": self.renderer,
                "edge": self.edge,
                "focus": self.focus,
                "line_spacing": round(self.line_spacing, 2),
                "sung_color": ("auto" if self._sung is None else
                               "white" if self._sung == QColor("white")
                               else self._sung.name()),
                "interlude": round(self.interlude, 2),
                "merge_ms": round(self.merge_ms, 1),
                "scroll_lead": round(self.scroll_lead, 2),
                "resync": bool(self.resync),
                "auto_time": bool(self.auto_time),
                "any_player": bool(self.any_player),
                "song_max": round(self.song_max, 1),
                "unpause_delay": round(self.clock.unpause_delay, 3),
                "unpause_mode": self.unpause_mode,
                "pop_min": round(self.pop_min, 2),
                "beat": round(self.beat_scale, 2),
                "roman": self.roman,
                "genius_auto": bool(self.genius_auto),
                "furigana": bool(self.furigana),
                **{attr: bool(getattr(self, attr))
                   for attr in SRC_ATTR.values()},
                **{attr: bool(getattr(self, attr))
                   for attr in BLEND_KEY.values()},
                "ne_graft": bool(self.ne_graft),
                "fold_adlibs": bool(self.fold_adlibs),
                "review_marks": bool(self.review_marks),
                "people_skip": list(self.people_skip),
                "people_pick": list(self.people_pick),
                "uncensor": bool(self.uncensor),
                "fetch_ahead": int(self.fetch_ahead),
                "spin": round(self.spin, 2),
                "zero_g": round(self.zero_g, 2),
                "clouds": round(self.clouds, 2),
                "float_up": round(self.float_up, 2),
                "off_by_one": round(self.off_by_one, 2),
                "searching": round(self.searching, 2),
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
        self.unfollow_editor(pause=False)
        self.frame_timer.stop()
        self.poll_timer.stop()
        self.pump.stop()
        LS.offload.shutdown()
        self.fetcher.stop = True
        self.art_cache.stop = True
        self.motion.stop = True
        for sig in (self.fetcher.ready, self.fetcher.beat_ready,
                    self.fetcher.index_ready, self.fetcher.index_progress,
                    self.fetcher.genius_ready, self.fetcher.artists_ready,
                    self.fetcher.recents_ready, self.fetcher.catsearch_ready,
                    self.fetcher.gsearch_ready, self.fetcher.gmatch_ready,
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


def log_path(prev: bool = False) -> pathlib.Path:
    """Where this program's messages go when it has no console to print to.

    Named after whatever was started, so the player and the editor -- which
    share this module and share a cache directory -- do not write over each
    other when both are open. `prev` is the run before this one.
    """
    stem = pathlib.Path(sys.argv[0] or "mild-lyrics").stem or "mild-lyrics"
    return app_dir("cache") / f"{stem}.log{'.prev' if prev else ''}.txt"


def log_to_file() -> pathlib.Path | None:
    """Point this process's output at that file. The path, or None.

    THE DESCRIPTORS AS WELL AS THE PYTHON OBJECTS. Qt writes its own warnings
    from C++ straight to fd 2 and they never pass through sys.stderr, and they
    are half of what is worth having here -- "endPaint() called with active
    painter" is Qt's account of the same bad frame the traceback below is
    Python's. Both land in one file, in the order they happened.

    One previous run is kept. A log that grows for the life of an install is
    a log nobody opens, and the run before this one is the only other one
    anybody ever wants: it is where the fault that closed the window is.
    """
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.replace(log_path(prev=True))
        stream = open(path, "w", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        os.dup2(stream.fileno(), 1)
        os.dup2(stream.fileno(), 2)
    except (OSError, ValueError):
        pass
    sys.stdout = sys.stderr = stream
    print(f"[{APP_SLUG} {time.strftime('%Y-%m-%d %H:%M:%S')} "
          f"pid {os.getpid()} python {sys.version.split()[0]} {sys.platform}]")
    return path


def hide_own_console() -> None:
    """Drop the console window Windows opened just for us, and keep its output.

    Double-clicking a .py file runs it under python.exe, which allocates a
    console -- so a black window sits behind the lyrics for the whole session.
    pythonw.exe does not, which is what spicy-lyrics.pyw is for, but the file
    people reach for is this one.

    Only a console we own is hidden. Started from a terminal, the console is
    shared with the shell that launched us, and taking that away would close
    the window someone is working in and swallow every message meant for them.
    GetConsoleProcessList tells the two apart: a console made for us has one
    process attached, an inherited one has at least the shell as well.

    A hidden console is a console nobody can read, so the output goes to the
    log instead -- otherwise this call is the second of the two ways a Windows
    run ends up with nowhere to print a traceback, and the one that looks like
    it worked. The other is pythonw, which install_excepthook catches.
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
            log_to_file()
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

    None of which is worth anything where the messages have nowhere to go, and
    on Windows they have nowhere to go: the launchers are .pyw files, pythonw
    leaves sys.stdout and sys.stderr as None, and printing to None is not an
    error -- print returns silently rather than raising. So every traceback
    this has ever folded on Windows went into nothing, which is why a window
    that stopped drawing there could not be told from one that was drawing
    something empty. log_to_file is what it prints to instead.
    """
    if sys.stderr is None or sys.stdout is None:
        log_to_file()
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
    ap.add_argument("--merge-ms", type=float, metavar="MS",
                    help="draw a word whole when every one of its syllable "
                         "boundaries lands within this many MILLISECONDS of "
                         "where a plain letter-count would put them -- such a "
                         "split changes nothing on screen and costs a fragment. "
                         "Flat rather than a fraction of the word, because a "
                         "boundary is seen where it lands and not in percent of "
                         "the word it is inside. 0 shows every split the source "
                         "wrote (default 0)")
    ap.add_argument("--blur", type=float, metavar="SCALE",
                    help="depth-blur strength for distant lines (default 1.0)")
    ap.add_argument("--glow", type=float, metavar="SCALE",
                    help="bloom strength on sung text, 0 disables (default 1.0)")
    ap.add_argument("--word-glow", type=float, metavar="SCALE",
                    help="light every word of the column from behind, not only "
                         "the one being sung, 0 disables (default 0). Stacks "
                         "with --glow, which is the sung word's own halo. The "
                         "scrolling renderers only -- flow, snap and amll")
    ap.add_argument("--syll-hold", type=float, metavar="SECS",
                    help="judge each SYLLABLE on its own length rather than "
                         "the word's, and emphasise the ones held at least "
                         "this long, 0 for the word (default 0). The amll "
                         "renderer only. Its held-note gate asks about a whole "
                         "word -- Titanium, four seconds, all eight letters "
                         "lighting together -- because a syllable cannot clear "
                         "a bar of a second; give it a smaller bar and the "
                         "piece actually being held is the piece that lights. "
                         "The bar is what sets how much of the song glows, and "
                         "1.0 is about the word unit's own density: measured "
                         "over the documents in this folder it leaves a lit "
                         "piece in 22%% of lines against the word unit's "
                         "25%%. Lower is busier and quickly much busier -- "
                         "0.5 is 56%% of lines and 0.4 is 70%%")
    ap.add_argument("--font-scale", type=float, metavar="SCALE",
                    help="multiplier on the lyric text size (default 1.0)")
    ap.add_argument("--interlude", type=float, metavar="SECS",
                    help="show dots for instrumental gaps at least this long, "
                         "0 disables (default 4.0)")
    ap.add_argument("--scroll-lead", type=float, metavar="SECS",
                    help="begin scrolling to the next line this long before it "
                         "starts, once the line before it has finished; "
                         "0 waits for the line itself (default 0.35)")

    bg = ap.add_argument_group("background")
    bg.add_argument("--bg", choices=BG_MODES,
                    help="art: blurred cover, slowly drifting (default). "
                         "mesh: animated blobs in the cover's palette, no cover "
                         "needed. solid: flat, nothing moving.")
    bg.add_argument("--mesh-style", choices=MESH_STYLES,
                    help="how the mesh spends the album's colours. blobs: the "
                         "drifting circles (default). wash: the dominant colour "
                         "down the window from the top and the next one back up "
                         "from the bottom, which is the flat tinted page a "
                         "Genius album gets. veil: one tint over the whole "
                         "window, nothing moving in it.")
    bg.add_argument("--mesh-tint", type=float, metavar="SCALE",
                    help="how strongly the mesh colours read; past 1.0 the album "
                         "tint carries the window rather than sitting behind it "
                         "(default 1.0). Note --bg-dim veils whatever this "
                         "paints, so a bold wash usually wants that lower too.")
    bg.add_argument("--mesh-spread", type=float, metavar="SCALE",
                    help="how far each colour reaches: blob size in blobs, how "
                         "far down the window the gradient carries in wash, and "
                         "how much of the second colour is mixed into the first "
                         "in veil (default 1.0)")
    bg.add_argument("--mesh-colors", type=int, metavar="N",
                    help="how many of the cover's dominant colours the mesh may "
                         "use, 1 to 4; 1 is a single-colour background (default 4)")
    bg.add_argument("--bg-dim", type=float, metavar="0-1",
                    help="veil over the background; higher is darker and makes "
                         "the lyrics carry more (default 0.65)")
    bg.add_argument("--bg-motion", type=float, metavar="SCALE",
                    help="drift speed, 0 freezes it entirely (default 1.0)")
    bg.add_argument("--bg-fade", type=float, metavar="SECS",
                    help="how long the background takes to change into another "
                         "one -- a new cover, a new section, a switch of mode, "
                         "and the visualizer arriving over the still wall when "
                         "the track's analysis lands. 0 cuts straight to it, "
                         "which is what it used to do (default 0.6)")
    bg.add_argument("--viz", type=float, metavar="SCALE",
                    help="drive the background blobs from Spotify's analysis of "
                         "the track -- they swell on what is sounding and kick "
                         "on the beat; 0 disables (default 0). Layers over any "
                         "background; replaces the mesh, which is the same "
                         "shapes standing still.")
    bg.add_argument("--viz-mode", choices=VIZ_MODES,
                    help="what the visualizer draws. bloom: the drifting blobs, "
                         "swelling on the chord sounding (default). pulse: a ring "
                         "per beat, off the metrical grid alone, which is what "
                         "stays legible on music built out of drums. bars: the "
                         "twelve pitch classes as columns, ordered by fifths. "
                         "tide: slow water rising with the loudness.")
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
    fx.add_argument("--rise", type=float, metavar="SCALE",
                    help="lift each word as it is sung and LEAVE it lifted, "
                         "rather than letting it drop back the way --pop does. "
                         "The line settles as a whole once it has passed; 0 "
                         "disables (default 0)")
    fx.add_argument("--line-drop", type=float, metavar="SCALE",
                    help="knock the whole line down a few pixels the moment its "
                         "first word starts and let it ride back up, so a line "
                         "arriving reads as a hit rather than as a light coming "
                         "on; 0 disables and the line lights up where it already "
                         "sits (default 1.0). Only the scrolling stack has an "
                         "entrance to scale -- the pinned renderers do not move "
                         "their lines at all")
    fx.add_argument("--renderer", choices=RENDER_MODES,
                    help="how the lyric column is drawn. flow: the scrolling "
                         "stack, every line one size, the one being sung "
                         "filling syllable by syllable (default). snap: the "
                         "same, but each word takes the sung colour whole "
                         "instead of filling. amll: the stack again, carried "
                         "by a spring per line instead of one scroll, so a "
                         "line change passes down the column as a wave "
                         "(Apple Music-like Lyrics' own movement); the wheel "
                         "does nothing to it. spotlight: the line being sung "
                         "alone, large and centred, with the next one under it. "
                         "karaoke: two lines in the middle of the window, "
                         "alternating, ad-libs under the line they belong to "
                         "and the line coming next brightening as its turn "
                         "arrives. word: one word at a time, very large, with "
                         "any ad-lib under it. cards: a card per line, the "
                         "whole song, scrolling")
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
                         "A reading the source ships is used as it is; where it "
                         "ships none, Japanese is read with pykakasi, Chinese "
                         "with pypinyin and Korean by rule (default off)")
    fx.add_argument("--furigana", action=argparse.BooleanOptionalAction, default=None,
                    help="set the reading above the characters it belongs "
                         "to, the way a lyric booklet does: kana over kanji, "
                         "pinyin over hanzi, romaja over Hangul (default off)")
    fx.add_argument("--genius-auto", action=argparse.BooleanOptionalAction, default=None,
                    help="look a human-written romanisation up on Genius for every "
                         "CJK track as it loads, instead of waiting for G. Needs a "
                         "Genius token (default off)")
    fx.add_argument("--clouds", type=float, default=None, metavar="N",
                    help="troll: set every line adrift in a soft cloud, floating "
                         "in from off-screen as it arrives and away again once "
                         "it has passed. N scales the motion (default 0, off)")
    fx.add_argument("--float-up", type=float, default=None, metavar="N",
                    help="troll: let go of every syllable as the voice reaches "
                         "it, so the words lift off the line while they are "
                         "being sung and fade out on the way up, growing as "
                         "they come so they pass over the reader rather than "
                         "away from them. The line empties from the front "
                         "instead of scrolling away, and an interlude's three "
                         "dots go the same way one after another as the break "
                         "runs out. Timed off the song, so a seek brings the "
                         "words back and a pause holds them where they are. N "
                         "scales how fast they go (default 0, off)")
    fx.add_argument("--zero-g", type=float, default=None, metavar="N",
                    help="troll: cut every word loose from its line and let it "
                         "drift, bouncing off the window edges. N scales how fast "
                         "(default 0, off)")
    fx.add_argument("--spin", type=float, default=None, metavar="N",
                    help="troll: spin the word being sung through a full turn, "
                         "over exactly as long as it lasts. N scales how many "
                         "turns (default 0, off)")
    fx.add_argument("--off-by-one", type=float, default=None, metavar="P",
                    help="troll: now and then scroll to the line above or below "
                         "the one being sung, so the words play in time but sit "
                         "a row out of the reading band. P is the chance per "
                         "line, 0 to 1, and a slip that starts tends to last a "
                         "few lines (default 0, off)")
    fx.add_argument("--searching", type=float, default=None, metavar="N",
                    help="troll: every so often lose the words and hunt for "
                         "them, scrolling up and down the whole lyric without "
                         "stopping, several windows a second, before settling "
                         "back on the song. N scales how often, how long and "
                         "how fast (default 0, off)")
    br = ap.add_argument_group("browse view")
    br.add_argument("--browse-now", action=argparse.BooleanOptionalAction, default=None,
                    help="show the now-playing card on the browse home screen "
                         "(default on)")
    br.add_argument("--browse-art", action=argparse.BooleanOptionalAction, default=None,
                    help="load cover thumbnails in the browse view; off makes it "
                         "text-only and does no image fetching (default on)")
    src = ap.add_argument_group("lyric sources, in priority order")
    src.add_argument("--fetch-ahead", type=int, default=None, metavar="N",
                     help="look the lyrics up for this many queued tracks "
                          "before they are reached, up to 7, 0 to do none "
                          "(default %d)" % DEFAULTS["fetch_ahead"])
    src.add_argument("--src-spicy", action=argparse.BooleanOptionalAction, default=None,
                     help="the Spicy Lyrics community's own documents, from "
                          "its API. Always tried first; --no-src-spicy to see "
                          "what the others would give instead (default on)")
    src.add_argument("--src-apple", action=argparse.BooleanOptionalAction, default=None,
                     help="Apple Music's word-timed TTML, by two doors on the one "
                          "catalogue: Lyrics+ asked for Apple by name, and "
                          "BiniLyrics by ISRC. Its lines are also what the blends "
                          "put NetEase, QQ or Kugou timing under (default on)")
    src.add_argument("--src-amll", action=argparse.BooleanOptionalAction, default=None,
                     help="amll-ttml-db: community word-by-word TTML, matched by "
                          "Spotify id and then by title/artist (default on)")
    src.add_argument("--src-unison", action=argparse.BooleanOptionalAction, default=None,
                     help="Unison: the Better Lyrics community's own database, "
                          "written and voted on by its readers (default on)")
    src.add_argument("--src-qq", action=argparse.BooleanOptionalAction, default=None,
                     help="QQ Music: its lines as well as its word timing, ad-libs "
                          "included, and the timing the Apple+QQ blend lays under "
                          "Apple's lines (default on)")
    src.add_argument("--src-netease", action=argparse.BooleanOptionalAction, default=None,
                     help="NetEase Cloud Music: word-level where it has it, and "
                          "a human-written romanisation on the same clock as the "
                          "lyrics (default on)")
    src.add_argument("--src-kugou", action=argparse.BooleanOptionalAction, default=None,
                     help="Kugou: word-timed KRC, strongest on the Chinese "
                          "catalogue (default on)")
    src.add_argument("--src-mxm", action=argparse.BooleanOptionalAction, default=None,
                     help="Musixmatch, through the Lyrics+ door and asked for by "
                          "name. Line-level: its claimed word timing is dropped "
                          "(default on)")
    src.add_argument("--src-lrclib", action=argparse.BooleanOptionalAction, default=None,
                     help="LRCLIB: line-level LRC only, so it is the last resort "
                          "of the databases (default on)")
    src.add_argument("--src-genius", action=argparse.BooleanOptionalAction,
                     default=None,
                     help="Genius: the words with no timing under them at all, "
                          "which is why it sits last -- it can only speak for a "
                          "song nothing else here has, and is only asked where "
                          "nothing else answered. Needs your Genius token "
                          "(default on)")
    bl = ap.add_argument_group(
        "blends: Apple Music's lines with another source's word timing under "
        "them. Asked in the order you ranked the source lending the clock, "
        "and only where every source they draw on is switched on")
    bl.add_argument("--blend-netease", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="NetEase's word timings under Apple's lines. The "
                         "steadier of the two where both have the song "
                         "(default on)")
    bl.add_argument("--blend-ne-qq", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="the same, with QQ Music asked only about the lines "
                         "NetEase could not place at all (default on)")
    bl.add_argument("--blend-ne-kugou", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="the same again, with Kugou filling those lines "
                         "instead -- a second door rather than a second "
                         "opinion, since QQ and Kugou largely agree but fail "
                         "separately (default on)")
    bl.add_argument("--blend-qq", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="QQ Music's word timings under Apple's lines "
                         "(default on)")
    bl.add_argument("--blend-kugou", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="Kugou's underneath instead, which reach songs QQ's "
                         "do not (default on)")
    ap.add_argument("--review-marks", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="mark what is wrong with the lyric on the words as "
                         "they are sung -- the splits no rule would make, the "
                         "pieces running through each other, the characters "
                         "that should not be in a lyric. Any document, yours "
                         "or a source's; press Y for the whole review, where "
                         "a tab or a weight narrows what is marked "
                         "(default off)")
    ap.add_argument("--fold-adlibs", action=argparse.BooleanOptionalAction, default=None,
                    help="draw a shouted line filed as its own line -- \"Yeah\", "
                         "\"Oh, God\" -- as an ad-lib on the line before it, and "
                         "lift a bracketed backing vocal out of the lyric. Only "
                         "on documents NetEase, QQ Music or Kugou had a hand in, "
                         "the three that cannot mark a second voice any other "
                         "way (default on)")
    src.add_argument("--uncensor", action=argparse.BooleanOptionalAction, default=None,
                     help="put back the letters a clean edit masked out -- "
                          "\"n***a\", \"f**k\", \"****\" -- from a source that "
                          "writes the word. Musixmatch first and LRCLIB behind "
                          "it, asked only for a document that has masks in it "
                          "at all, and only allowed to fill a mask it is "
                          "exactly the shape of (default on)")
    src.add_argument("--skip-people", metavar="A,B", dest="people_skip",
                     default=None,
                     help="never use a sync timed by these people, whichever "
                          "source it turns up on -- names as the credit under "
                          "the lyrics spells them, separated by commas. The "
                          "source itself is untouched: one contributor's "
                          "syncs are not the database they are sitting in")
    src.add_argument("--prefer-people", metavar="A,B", dest="people_pick",
                     default=None,
                     help="take these people's syncs over an equally good one "
                          "from a source you ranked higher. Timing still "
                          "outranks both: a name here cannot put a line-synced "
                          "document on screen over a word-synced one")
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
    ap.add_argument("--art-side", choices=ART_SIDES, default=None,
                    help="which edge the album art panel hangs off "
                         "(default left). Independent of --align, which is "
                         "where the words sit in the column that is left")
    ap.add_argument("--volume-bar", action=argparse.BooleanOptionalAction, default=None,
                    help="volume slider beside the cover (default on)")
    ap.add_argument("--src-order", metavar="A,B,C", default=None,
                    help="order the lyric sources are consulted in, e.g. "
                         "\"amll,spicy,netease,apple,lrclib\"; unlisted ones keep "
                         "their usual place at the end. The names are "
                         + ", ".join(SRC_DEFAULT))
    ap.add_argument("--font", metavar="FAMILY", default=None,
                    help="font family by name, e.g. \"Segoe UI\" or \"Inter\"; "
                         "empty picks the first of the built-in stack that is "
                         "installed")
    ap.add_argument("--player", choices=["auto", "mpris", "cdp", "smtc", "macos"],
                    default="auto",
                    help="how to read the player: 'cdp' is Spotify's own debug "
                         "port, and the other three are the platform's own "
                         "now-playing service -- 'mpris' the desktop bus on "
                         "Linux, 'smtc' Windows' system media transport, "
                         "'macos' whichever of MediaRemote and Apple Events is "
                         "open on a Mac. All three need no launch flag and work "
                         "with a store build, and none of them carries Spicy "
                         "Lyrics; only the bus carries a volume (default auto)")
    ap.add_argument("--any-player", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="follow whoever is playing rather than Spotify alone: "
                         "a song on YouTube in a browser, a file in mpv, "
                         "anything the platform's own now-playing service knows "
                         "about (default off). Spotify still wins while Spotify "
                         "is playing. A track from anybody else is looked up "
                         "before it goes on screen and only takes the window "
                         "over if a provider has words for it, which is what "
                         "keeps videos out -- nothing in the metadata says "
                         "whether a YouTube tab is playing a single or a "
                         "lecture. All three platforms: the session bus on "
                         "Linux, the media transport on Windows, MediaRemote or "
                         "Apple Events on a Mac")
    ap.add_argument("--song-max", type=float, default=None, metavar="MINUTES",
                    help="the longest a track from another player may be and "
                         "still be taken for a song (default %.0f). The coarse "
                         "half of telling one from a film, an episode or a set; "
                         "only applied where the player says how long the thing "
                         "is, which a browser often does not"
                         % DEFAULTS["song_max"])
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
    ap.add_argument("--unpause-mode", choices=UNPAUSE_MODES, default=None,
                    help="what --unpause-delay means. measured: it is the "
                         "ceiling on the forward leap read off the player at "
                         "an unpause (default). fixed: it IS the hold, taken "
                         "whole every time -- for a player whose leap cannot "
                         "be measured steadily, where a number set by ear "
                         "beats a number read badly")
    ap.add_argument("--unpause-delay", type=float, default=None, metavar="SECS",
                    help="how long the words hold still after an unpause, "
                         "covering the moment the player's audio takes to come "
                         "back. Really the gap between the forward jump the "
                         "player's clock makes on unpausing and the audio it "
                         "kept playing into the pause; measured at 0.095s for "
                         "Spotify (default %.2fs); 0 disables it. NEGATIVE "
                         "pushes the words on instead, for a player whose "
                         "audio starts before it admits to playing -- nothing "
                         "in a position reading can reveal that, so it has to "
                         "be set" % UNPAUSE_DELAY)
    ap.add_argument("--auto-time", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="measure each song's timing against Spotify's analysis "
                         "of it and correct what is found. A track you have "
                         "tuned by hand keeps your figure. The measurement is "
                         "applied as it is read, where it is clear enough and "
                         "small enough to be a sync error at all -- see the "
                         "note where calibrate() was (default on)")
    ap.add_argument("--resync", action=argparse.BooleanOptionalAction, default=None,
                    help="let the app nudge the player to keep its clock on its "
                         "audio: a seek after Spotify rolls over to the next track "
                         "by itself, and a seek to the pause point while paused, "
                         "which is silent and is what keeps unpausing from costing "
                         "0.2s of sync (default on; --no-resync to disable). This "
                         "is the manual 'nudge the scrubber' fix, automated.")
    ap.add_argument("--save-dir", default="", metavar="DIR",
                    help=f"where the S key writes .ttml files (default: "
                         f"{SAVE_HOME}, or your Music folder where that "
                         f"cannot be written)")
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
    ap.add_argument("--fixture", metavar="TTML",
                    help="debug: put this document on screen and stop asking "
                         "the player anything. --track only seeds the first "
                         "reading -- the pump overwrites it a frame later -- so "
                         "this is what makes a snapshot a snapshot OF something. "
                         "Nothing is cached and the file is not saved for the "
                         "track the way dropping it on the window would be")
    args = ap.parse_args()

    saved = {} if args.no_persist else load_settings()
    for key in DEFAULTS:
        attr = {"panel": "art"}.get(key, key)
        if not hasattr(args, attr):
            continue
        if getattr(args, attr) is None:
            setattr(args, attr, saved.get(key, DEFAULTS[key]))

    LS.offload.warm()
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

    if args.fixture:
        def _fixture():
            w.pump.stop()
            w.pump.wait(2000)
            body = LS.parse_ttml(
                pathlib.Path(args.fixture).read_text(encoding="utf-8"))
            w.clock.tid = w._seen_tid = "fixture"
            w.clock.meta = {"title": pathlib.Path(args.fixture).stem,
                            "artist": "", "length": 300.0}
            w.clock.status = "Playing"
            w.on_lyrics("fixture", w.timeline_of(body), body, force=True)
        QTimer.singleShot(700, _fixture)

    w.enter_fullscreen() if args.fullscreen else w.show()
    if args.snapshot:
        def grab():
            w.grab().save(args.snapshot)
            print(f"saved {args.snapshot}")
            app.quit()
        QTimer.singleShot(int(args.snapshot_delay * 1000), grab)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
