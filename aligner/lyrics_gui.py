#!/usr/bin/env python3
"""
Apple Music / Spicy Lyrics-style lyrics window for the running Spotify app.

Reads Spicy Lyrics' cache over CDP (see spicy_lyrics.py) and renders it against
the MPRIS playback clock. Layout mirrors the Spicy Lyrics view in Spotify:
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
    browse (it re-centres after a moment), double-click the art to go full.

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
import noconsole  # noqa: E402
import renderers as RD  # noqa: E402
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
# How often the WINDOW looks at itself: the fetcher, the artwork, the queue,
# the track it thinks is playing. None of that is the clock, and none of it is
# urgent -- a track change reaches it the moment the clock sees one anyway,
# because the sampler pokes it. The edge rate is for a screen still waiting on
# a lyric, which is the one thing here worth retrying quickly.
POLL_MS, POLL_MS_EDGE = 250, 60
# How often the PLAYER is asked where it is -- every frame, near enough, and
# on a thread of its own. See Pump.
#
# This is the whole of the delay on anything the player does that cannot be
# predicted from here. A seek made in Spotify's own window is invisible until
# the next reading: the clock carries the old position forward at 1x straight
# through it, so the gap between readings is exactly how long the wrong line
# stays up. It also sets how long after an unpause the words move at all --
# the audio is back 46ms after the play command and resumes ~0.16s beyond the
# parked reading, and at 250ms that left them 0.31s behind the voice with a
# visible flicker as they caught up.
#
# Spicy Lyrics samples every frame and that is the reason a seek never shows
# there. The number is affordable for the same reason it is affordable inside
# the page: a reading is 0.28ms down the debug port (median of 200, an idle
# renderer), so sixty a second is under 2% of one core, and none of it is on
# the thread that draws.
SAMPLE_MS = 16
# How often the look-ahead looks up to see whether the fetcher is free, and
# how long it will wait there before deciding its queue has gone stale. The
# patience matches the queue scan's own minute: waiting longer than the thing
# that rebuilds the list cannot buy anything.
WARM_LOOK = 0.25
WARM_PATIENCE = 60.0
SLEW_MAX, SLEW_TIME = 0.6, 0.35
# How long after an unpause the player is still settling; see the slew
# guard in Clock.poll for what arrives inside this window.
RESUME_SETTLE = 1.0
# Under this, a forward step across a resume is the measurement, not a leap:
# the poll interval, the status arriving a moment after the audio did, the
# engine's own few ms of quantisation. Charging those to the words puts them
# permanently behind the voice, which is the whole failure this guards. A
# player that really does step its clock at an unpause steps it a quarter of a
# second -- Spotify's own is 0.253s over the control state -- so there is an
# order of magnitude between the two and nothing that matters is lost by
# insisting a leap clear this first.
RESUME_STEP_FLOOR = 0.06
# How long the leap goes on being measured for. Longer than RESUME_SETTLE,
# which is what the SEEK test and the slew are timed against and must not move:
# this is only the window the displacement is read over. Measured on Spotify
# over the debug port the leap does not always arrive promptly -- on two
# unpauses in seven it was still climbing at 0.7s and had not finished by 1.0s,
# so the old window shut on a half-measured leap and carried that instead.
# Safe to run long only because what it reads is a displacement from the resume
# and not a running total: past the leap it stops changing, and a seek in here
# is caught by `jumped` and clears the bias outright.
RESUME_MEASURE = 2.0
PIN_EDGE = 1.0
# The frame rate while the window is not on a screen -- minimised, or on
# another virtual desktop. Not zero: the clock still has to drift, the settings
# still have to be written, and a SIGTERM arriving at a hidden window still has
# to close it. Nothing here is drawn, so this only has to be often enough that
# those three stay responsive.
FRAME_IDLE_HZ = 10.0

# --- unpause delay --------------------------------------------------------
# A ceiling, not a duration. Spotify's reported position leaps forward when it
# is unpaused -- measured at 0.253s, within 30ms of the command, sd 0.005 over
# 24 unpauses -- and then advances with the clock and never gives it back. The
# leap is read from the player each time rather than assumed, and carried for
# as long as that stretch of playback lasts; this is as much of it as will be
# taken. Over the session bus there is no leap and nothing is subtracted, so
# the number only bites where it applies.
#
# 0.25 covers the measured leap with nothing to spare. Lower it and the words
# keep some of the leap and run ahead of the voice; 0 disables the correction
# entirely. Unlike the duration this replaces, a wrong value here lasts until
# the next seek or track change rather than a quarter second, so it is worth
# setting by ear on a song you know well.
UNPAUSE_DELAY = 0.25

APP_NAME = "Mild Lyrics"
APP_SLUG = "mild-lyrics"
OLD_SLUG = "spicy-lyrics"

# How the live link keeps the editor's clock: say something whenever the song
# moves in a way the far end cannot have predicted, and say something anyway
# this often, so the reading over there never goes stale enough to be dropped.
SAY_DRIFT = 0.25
SAY_EVERY = 0.5

POLL_IDLE = 0.4
# How long the search box waits after the last keystroke before it asks
# Genius. The local index answers on every letter -- it is a dictionary
# lookup -- but Genius is a request over the network, and a query typed
# at speed would send one per letter and be answered out of order.
GENIUS_TYPED_MS = 150
# How long a source that could not be reached is left unmentioned after
# it has been mentioned once. See on_source_trouble.
TROUBLE_QUIET = 3600.0
# Walking Spotify along with an editor that is timing against a local copy of
# the song. See follow_editor. How far Spotify may drift from the file before
# it is put back; how long a transport command is given to take effect before
# another is sent; and how long the editor may go quiet before this window
# decides it has gone and hands the player back.
FOLLOW_DRIFT = 0.35
FOLLOW_STEADY = 0.6
FOLLOW_GONE = 2.0
POLL_WAITING = 0.12
RETRY_FIRST = 0.3
RETRY_MAX = 2.0
# Spicy Lyrics fetches its own copy inside the Spotify page, and on a song it
# has not seen before that can land a second or two after this window has
# already asked everybody else and put a perfectly good answer up -- and it
# lands twice, a line-level copy first and the word-timed one after it. Keep
# looking for the word timing, so the source the user ranked first is not lost
# to a race it was always going to lose on a cold song.
#
# The looking used to stop after SPICY_GRACE and the song was then stuck with
# somebody else's document until it was played again: Spicy Lyrics' own copy
# can land a good deal later than that -- a slow fetch, a line-level copy it
# upgrades in its own time, or a lyrics view the user only opens halfway
# through -- and every one of those cases ended with two different lyrics on
# two halves of the same screen. So the grace now only sets the PACE: quick
# looks while the copy is most likely to arrive, one every SPICY_SLOW for as
# long as the track stays up. It is a read from the page over a socket this
# thread already holds, which is what makes keeping it up all song cheap.
SPICY_GRACE = 25.0
SPICY_LOOK = 0.75
SPICY_SLOW = 3.0
# ...and how long a load will hold the CREDIT for it before writing somebody
# else's name under the lyrics. The walk is not a race Spicy Lyrics lost, it
# is one it was never in: the chain answers off the disk in a millisecond on
# any song it has been asked about in the last month, while Spicy Lyrics'
# own copy needs one request inside the page -- and it needs it on nearly
# every song, because its cache holds a track for three days and most songs
# are not played twice in three days. So the answer the walk brings back is
# shown at once, as it always was, and then this much is spent looking again
# before it is allowed to be the answer. Nothing waits on screen for it.
#
# Long enough to cover the page's own request -- a few hundred milliseconds,
# and the load is already a beat behind the track change when it starts
# counting -- and no longer, because everything else the fetcher hands over
# on a new song, the artists and the beat among them, waits behind this.
SPICY_HOLD = 1.5


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


# Where saved lyrics go unless somebody says otherwise: the folder holding
# this program, which is the parent of aligner/ -- the checkout, beside the
# two launchers and the editor. It is a real answer on a machine nobody has
# configured, and the same answer whether the window was started from a
# terminal, a .desktop file, a Start-menu shortcut or a double-clicked .pyw.
SAVE_HOME = _HERE.parent


def save_dir(want: str) -> tuple[pathlib.Path, bool]:
    """Where a file the user asked to keep actually goes, and whether that is
    where they asked for it.

--save-dir defaults to SAVE_HOME, the folder the program lives in,
    which is the same place on both platforms and whoever started it.

    It used to default to the working directory. That is the right answer
    when the program was started from a terminal and no answer at all when it
    was not, and the two platforms then disagreed for no reason anybody
    chose: running `python aligner/lyrics_gui.py` from the checkout puts the
    files in the checkout, and a Windows shortcut with no "Start in" set
    leaves the working directory at C:\\Windows\\System32, where every save
    is "[Errno 13] Permission denied" -- reported as a save that failed, on a
    machine where nothing was wrong except that nobody had said where to put
    the file.

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
# The running order is a list of SOURCES -- who wrote the lyrics -- and not
# of the doors this program knocks on to reach them. Those are two different
# lists, and the old menu was the second one: it offered "Lyrics+", which is
# a scraper that answers from Apple Music, Musixmatch, QQ Music or its own
# submissions depending on the day, and "Apple+QQ", which is not a source at
# all but a reconciliation of two. Ranking those means ranking a route, and a
# route cannot be ranked: whoever put Lyrics+ second was putting Apple Music
# second on one song and Musixmatch second on the next.
#
# So the ten below are the catalogues the words actually come from, and the
# providers underneath are arranged to serve them (see SRC_PARTS).
SRC_LABEL = {"spicy": "Spicy Lyrics Community", "apple": "Apple Music",
             "amll": "amll-ttml-db", "unison": "Unison",
             "lyricsplus": "LyricsPlus Community", "qq": "QQ Music",
             "netease": "NetEase", "kugou": "Kugou", "mxm": "Musixmatch",
             "lrclib": "LRCLIB", "local": "Aligned here",
             "genius": "Genius"}


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
        label = SRC_LABEL.get(LS.PROVIDER_SRC.get(name, name), name)
        if label not in said:
            said.append(label)
            why = why or said_why
    if not said:
        return ""
    more = f" +{len(said) - 2} more" if len(said) > 2 else ""
    return f"{', '.join(said[:2])}{more} — {why}"


SRC_ATTR = {"spicy": "src_spicy", "apple": "src_apple", "amll": "src_amll",
            "unison": "src_unison", "lyricsplus": "src_lyricsplus",
            "qq": "src_qq", "netease": "src_netease",
            "kugou": "src_kugou", "mxm": "src_mxm", "lrclib": "src_lrclib",
            "local": "src_local", "genius": "src_genius"}
SRC_DEFAULT = list(LS.SOURCES)
# The mapping from a source to the providers that answer for it lives with
# the providers themselves, in lyric_sources, because eval_sources has to
# read this same list without dragging a window in behind it.
SRC_PARTS, BLENDS, BLEND_OF = LS.SRC_PARTS, LS.BLENDS, LS.BLEND_OF
PROVIDER_SRC, WAS_SRC, BLEND_KEY = LS.PROVIDER_SRC, LS.WAS_SRC, LS.BLEND_KEY
# A blend is not a catalogue and cannot be ranked as one -- it is Apple Music's
# lines with somebody else's clock under them -- so it gets a section of its
# own rather than a slot among the sources. Written short because the menu
# sizes its label column from the LITERAL strings in MENU, and the Sources
# rows carry "" there: a long label here would run under the value column
# instead of widening the panel. See _paint_menu.
BLEND_LABEL = {"blend": "Apple+QQ", "kublend": "Apple+Kugou",
               "neblend": "Apple+NetEase", "triblend": "Apple+NetEase+QQ",
               "kutriblend": "Apple+NetEase+Kugou"}

DEFAULTS = {
    "offset": 0.0, "font_scale": 1.0, "blur": 1.0, "glow": 1.0, "panel": True,
    "bg": "art", "bg_dim": 0.65, "bg_motion": 1.0, "align": "left", "pop": 1.0,
    "viz": 0.0, "viz_mode": "bloom",
    "edge": 1.0, "focus": 0, "line_spacing": 1.0, "sung_color": "white",
    "renderer": "flow", "rise": 0.0, "art_side": "left",
    "interlude": 4.0, "resync": True, "pop_min": 0.45, "beat": 1.0,
    "scroll_lead": 0.35,
    "auto_time": True, "unpause_delay": UNPAUSE_DELAY,
    "unpause_mode": "measured",
    "fps_cap": 60.0,
    "roman": "off", "genius_auto": False, "furigana": False,
    "src_spicy": True, "src_apple": True, "src_amll": True,
    "src_unison": True, "src_lyricsplus": True,
    "src_qq": True, "src_netease": True,
    "src_kugou": True, "src_mxm": True, "src_lrclib": True, "src_local": True,
    "src_genius": True,
    # On, all five. They were off by default when each one was a rankable row
    # of its own; folded into Apple Music they have been on for everybody
    # since, and switching them off now would quietly change what is on
    # screen for anyone who never knew they had come back.
    **{key: True for key in BLEND_KEY.values()},
    "fold_adlibs": True,
    "ne_graft": True,
    "align_on": True,
    "align_model": "sync", "align_stems": False, "align_ckpt": "",
    "align_device": "auto", "align_spare": 1.0,
    "align_free": True,
    "align_ahead": 1,
    "fetch_ahead": 3,
    "spin": 0.0,
    "zero_g": 0.0, "clouds": 0.0,
    "browse_now": True, "browse_art": True,
    "view_mode": "regular", "volume_bar": True,
    "duet_color": "off", "motion_art": False, "font": "",
    "src_order": ",".join(SRC_DEFAULT),
    # The global offset, per output. See audio_sink and on_device. Settings
    # only: there is no switch for it on argv, because the thing it is keyed
    # by is not known until the window has looked.
    "offsets_device": {},
}
# How often the window looks at which output the sound is coming out of. Two
# short subprocesses, on a thread of their own; the thing being watched for is
# somebody reaching for their headphones, so seconds is the right unit.
DEVICE_POLL = 2.0
# Whose stream to follow, matched loosely against the names PipeWire files a
# playback stream under.
DEVICE_APP = "spotify"

GLOW_FULL = 0.40
GLOW_FLOOR = 0.20
BG_MODES = ["art", "mesh", "solid"]
# bloom: the drifting blobs, sized by the chord sounding. pulse: a ring per
# beat, off the grid alone and so the one that holds up on a track with no
# chords in it. bars: the twelve pitch classes as columns. tide: slow water,
# rising with the loudness and answering nothing else.
VIZ_MODES = ["bloom", "pulse", "bars", "tide"]
VIEW_MODES = ["regular", "compact"]
# How the lyric column itself is drawn. See renderers.py; the window only
# ever asks the one it is holding to paint, and knows nothing else about it.
RENDER_MODES = RD.RENDER_MODES
# measured: unpause_delay is the ceiling on the leap read off the player.
# fixed: it IS the hold, taken whole at every unpause. See Clock._apply.
UNPAUSE_MODES = ["measured", "fixed"]
ALIGNMENTS = ["left", "center", "right"]
# Which edge the album art panel hangs off. Not the same question as
# ALIGNMENTS, which is where the WORDS sit inside whatever column is left
# over -- the two are set independently and both are worth having: art on
# the right with the lyrics still ranged left is a different picture from
# art on the right with them ranged right against it.
ART_SIDES = ["left", "right"]
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


def _ckpt_note() -> pathlib.Path:
    return SYNC_HOME / "checkpoints.json"


_CKPT_FACTS: dict = {}


def ckpt_facts(path) -> dict:
    """What a checkpoint says about itself: step, stem, boundary, calibration.

    UNPICKLING IS NOT THE WAY TO ASK. There are eleven of these on this
    machine and nine gigabytes of them; reading every one to decide which is
    newest cost four seconds of a dead window at every start, and again every
    time the model list was opened. The answer is four scalars, it only
    changes when the file does, and it is therefore kept -- keyed on name,
    mtime and size, in a small file beside the checkpoints so the player and
    the editor share one copy of the work.

    A miss reads the file with `mmap=True`, which pulls the pickle's index
    and leaves the tensors on disk: 0.03s against 0.34s, for an answer that
    never involved a weight.
    """
    path = pathlib.Path(path)
    try:
        stat = path.stat()
    except OSError:
        return {"step": None, "stem": None, "boundary": False,
                "calibration": None, "read": False}
    key = f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}"
    if key in _CKPT_FACTS:
        return _CKPT_FACTS[key]
    if not _CKPT_FACTS:
        try:
            _CKPT_FACTS.update(json.loads(
                _ckpt_note().read_text(encoding="utf-8")))
        except Exception:
            pass
        if key in _CKPT_FACTS:
            return _CKPT_FACTS[key]
    got = {"step": None, "stem": None, "boundary": False,
           "calibration": None, "read": False}
    try:
        import torch
        try:
            raw = torch.load(path, map_location="cpu", weights_only=False,
                             mmap=True)
        except Exception:                       # not a zipfile save, or old torch
            raw = torch.load(path, map_location="cpu", weights_only=False)
        got = {"step": raw.get("step"),
               "stem": raw.get("stem"),
               "boundary": any(k.startswith("boundary.")
                               for k in raw.get("weights", {})),
               "calibration": raw.get("calibration"), "read": True}
    except Exception:                           # noqa: BLE001
        return got                              # not remembered: try again later
    _CKPT_FACTS[key] = got
    # Only this file's older readings go; another machine's rows in a synced
    # copy are none of our business.
    for gone in [k for k in _CKPT_FACTS
                 if k.split(":")[0] == path.name and k != key]:
        _CKPT_FACTS.pop(gone, None)
    try:
        _ckpt_note().parent.mkdir(parents=True, exist_ok=True)
        _ckpt_note().write_text(json.dumps(_CKPT_FACTS), encoding="utf-8")
    except Exception:
        pass
    return got


def have_ckpt() -> bool:
    """Whether there is anything trained on this machine at all.

    Deliberately a glob and not `_sync_ckpt()`: this answers a window-building
    question -- do the model buttons belong on the ribbon -- and the full
    answer costs a scan of every checkpoint on disk. Which one runs is decided
    when one is about to.
    """
    try:
        return any(SYNC_HOME.glob("syncnet*.pt"))
    except OSError:
        return False


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

    Among the candidates for a mode, a MEASURED checkpoint beats an unmeasured
    one and the better mean error wins; only where nothing has been measured
    does newest step decide. A checkpoint without a boundary head loses to one
    with it either way -- it can only guess where a word ends. Cached per mode;
    the answer changes when a training run finishes.

    Step count used to decide on its own, and that is how syncnet-w2v-nl.pt
    came to align every song on this machine: 1500 steps of continuation on
    five Dutch songs, held out against nothing, and 1500 steps more than the
    model it was continued from. Measured on the seventeen gold songs it reads
    the mixture at 1.222s where its parent reads 0.571s -- three songs clean
    against seven. `sync bench` had the number all along; nothing asked it.

    So a newly trained checkpoint does NOT displace a measured one until it has
    been benchmarked itself. That is the intended order: train, measure, then
    it is picked up.
    """
    # AN EXPLICIT CHOICE WINS OVER A MEASURED ONE. `align_ckpt` names a
    # checkpoint outright, and it is obeyed without being scored against
    # anything -- because the benchmark cannot see everything a person cares
    # about. Its 43 songs contain no Dutch at all, and the Dutch-tuned
    # checkpoint measures worse on them precisely because they are not what it
    # was tuned for. A number taken where a model was not aimed is not a reason
    # to overrule the person who aimed it.
    pinned = ""
    try:
        pinned = str(load_settings().get("align_ckpt") or "")
    except Exception:                                       # noqa: BLE001
        pinned = ""
    if pinned:
        got = pathlib.Path(pinned).expanduser()
        if not got.is_absolute():
            got = SYNC_HOME / got
        if got.exists():
            return str(got)

    want = "-stem" if stems else ""
    best, found, able = None, "", []
    for path in sorted(SYNC_HOME.glob("syncnet-w2v*.pt")):
        if path.name.endswith("-lowloss.pt"):
            continue
        # What the checkpoint SAYS it was trained on, and only then the name.
        # The name is a convention two models have already broken: both were
        # trained on separated vocals and called "-lines" and "-vox", so they
        # read as mixture models and were saved from being chosen only by
        # having fewer steps than the incumbent.
        got = ckpt_facts(path)
        if not got.get("read"):                 # unreadable: not a candidate
            continue
        made_on_stems = got.get("stem")
        if made_on_stems is None:
            made_on_stems = any(k in path.name for k in ("-stem", "-pitch"))
        if bool(made_on_stems) != bool(stems):
            continue
        able.append((path, got))

    # WHICH MEASUREMENT MAY DECIDE. A score taken on a separated vocal says
    # nothing about a mixture, and a mean over seventeen songs is not
    # comparable with a mean over forty-three -- so only checkpoints measured
    # on the SAME input and the SAME set may be ranked against each other.
    # The set chosen is the one the most candidates share, largest first;
    # anything not measured on it ranks as unmeasured and falls back to step
    # count, which is where this started.
    want = "stem" if stems else "mix"
    seen: dict[str, dict] = {}
    for path, _got in able:
        for name, row in _scores_for(path).items():
            how, _, which = name.partition(":")
            if how != want:
                continue
            seen.setdefault(which or "hash", {})[str(path)] = row
    on = ""
    if seen:
        on = max(seen, key=lambda k: (len(seen[k]),
                                      max(r.get("songs") or 0
                                          for r in seen[k].values())))
    scored = seen.get(on, {})

    for path, got in able:
        row = scored.get(str(path)) or {}
        # ON CLEAN SONGS, NOT ON THE MEAN. They disagree, and the disagreement
        # is the point: over 43 songs one checkpoint came out 1.177s against
        # another's 1.484s while having FEWER songs free of a mess-up, 17
        # against 19. It made its catastrophes smaller rather than rarer, and
        # rarer is what a person notices. The mean only breaks ties.
        clean = row.get("clean")
        songs = row.get("songs") or 0
        share = (clean / songs) if isinstance(clean, int) and songs else None
        mean = row.get("mean")
        rank = (bool(got.get("boundary")),
                1 if share is not None else 0,
                share if share is not None else 0.0,
                -float(mean) if isinstance(mean, (int, float)) else 0.0,
                int(got.get("step") or 0))
        if best is None or rank > best:
            best, found = rank, str(path)
    return found


def _scores_for(path) -> dict:
    """Every measurement recorded against this exact file."""
    try:
        st = pathlib.Path(path).stat()
    except OSError:
        return {}
    return _ckpt_scores().get(
        f"{pathlib.Path(path).name}:{int(st.st_mtime)}:{st.st_size}") or {}


_CKPT_SCORES: dict = {}


def _ckpt_scores() -> dict:
    """What `sync bench` wrote about each checkpoint, keyed as ckpt_facts is.

    Re-read when the file changes rather than cached for the session: a
    benchmark finishing while the player is open should be able to change its
    mind about which model to load.
    """
    path = SYNC_HOME / "scores.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        _CKPT_SCORES.clear()
        return {}
    if _CKPT_SCORES.get("_at") != stamp:
        try:
            _CKPT_SCORES.clear()
            _CKPT_SCORES.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:                                   # noqa: BLE001
            _CKPT_SCORES.clear()
        _CKPT_SCORES["_at"] = stamp
    return _CKPT_SCORES

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
        ("Font",              "font_name",    "text",   None),
    ]),
    ("Motion", [
        ("Word pop",          "pop",          "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Word rise",         "rise",         "num",    (0.0, 4.0, 0.25, "{:.2f}")),
        ("Pop only past",     "pop_min",      "num",    (0.0, 2.0, 0.05, "{:.2f}s")),
        ("Fill softness",     "edge",         "num",    (0.0, 4.0, 0.25, "{:.2f}")),
        ("Glow",              "glow_scale",   "num",    (0.0, 2.0, 0.1,  "{:.1f}")),
        ("Depth blur",        "blur_scale",   "num",    (0.0, 2.0, 0.1,  "{:.1f}")),
        ("Beat response",     "beat_scale",   "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Scroll ahead",      "scroll_lead",  "num",    (0.0, 1.5, 0.05, "{:.2f}s")),
    ]),
    ("Background", [
        ("Background",        "bg_mode",      "choice", BG_MODES),
        ("Visualizer",        "viz",          "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("Visualizer mode",   "viz_mode",     "choice", VIZ_MODES),
        ("Background dim",    "bg_dim",       "num",    (0.0, 1.0, 0.05, "{:.2f}")),
        ("Background motion", "bg_motion",    "num",    (0.0, 3.0, 0.25, "{:.2f}")),
        ("View mode",         "view_mode",    "choice", VIEW_MODES),
        ("Album art panel",   "show_panel",   "bool",   None),
        ("Album art side",    "art_side",     "choice", ART_SIDES),
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
        # A hundredth, not a twentieth: what this trims is the gap between the
        # leap the player is measured to make and the one it really makes, and
        # that gap is tens of milliseconds. At 0.05 the only settings either
        # side of the default were 0.20 and 0.30, which overshoot it by more
        # than the error being corrected.
        ("Unpause delay",     "unpause_delay", "num",   (0.0, 1.0, 0.01, "{:.2f}s")),
        ("Unpause hold",      "unpause_mode", "choice", UNPAUSE_MODES),
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
    ] + [
        # After the slots, not before them: src_move addresses the running
        # order as MENU_SPANS' first row plus the position moved to, so a row
        # of any other kind at the top of this section puts the cursor one out
        # on every reorder.
        ("Fetch ahead",       "fetch_ahead",  "num",    (0, 7, 1, "{:.0f} tracks")),
    ]),
    ("Blends", [
        ("", f"blend_slot{i}", "bool", None) for i in range(len(BLENDS))
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

# A line under the tab strip, for a section whose rows cannot say what they
# are on their own. Kept beside MENU_SECTIONS rather than inside it: three
# places unpack those entries as two-tuples, and a third element would break
# every one of them.
SECTION_NOTE = {
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

# THE KEYS PANEL, in sections.
#
# It is a painted overlay rather than a scrolling widget, so it has exactly
# the room the window has -- and at thirty-five keys in two columns it was
# taller than a 768-line laptop screen, drawn centred, which put the first
# rows and the last rows off the top and bottom with no way to reach them.
#
# So it fits itself to the window (see help_layout): as many columns as the
# width allows, a smaller size before anything is hidden, and only when even
# that will not do does it show one section at a time with the tab strip to
# move between them. On a screen where the whole list fits, the whole list is
# what is drawn, exactly as before.
HELP_SECTIONS = [
    ("Playback", [
        ("Space", "play / pause"),          ("< / >", "seek -/+ 5s"),
        ("Up / Down", "previous / next line"),
        ("N / P", "next / previous track"),
        ("click", "seek to a line"),        ("drag bar", "scrub"),
    ]),
    ("Timing", [
        ("[ / ]", "offset -/+ 50ms"),       ("Shift+[ / ]", "offset -/+ 10ms"),
        ("0 / Shift+0", "clear track / global offset"),
        ("X", "resync to audio"),           ("Shift+A", "align to the audio"),
    ]),
    ("Lyrics", [
        ("R", "reload lyrics"),             ("Shift+R", "fix this line's romaji"),
        ("Shift+G", "romaji from Genius"),
        ("C / Shift+C", "copy line / all"),
        ("S / Shift+S", "save .ttml / card"),
        ("/", "search all lyrics + Genius"), ("I", "song info"),
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
# The room kept clear between the panel and the edge of the window. Whatever
# is left is what the panel has to fit inside.
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


# What the drawn-line and glow caches are allowed to hold, in bytes.
#
# They used to be one dict with one rule: over 400 entries, THROW IT ALL
# AWAY. Two things are wrong with that and they compound. Counting entries
# is not counting memory -- a line pixmap on a wide window is around 700 KB
# and a glow is a few KB, so 400 of them is anywhere between 2 MB and 280 MB
# -- and emptying the whole thing means every line in the column has to be
# re-rasterised at once, blurred ones through soft_scale, on the frame that
# happened to tip it over.
#
# Measured by sweeping the clock through three songs at eight times speed
# with the window painting every frame: the cache reached 401 and was dumped
# two to three times per song, each dump costing a frame of up to 23ms on
# this machine and more on a slower text rasteriser. That is the "shaky for
# a moment, at random" -- and the same clearing is done deliberately when a
# better source arrives mid-song, which is why a refresh both caused it and
# then cured it for a while.
#
# So: a byte budget, and the LEAST RECENTLY USED entry goes when it is
# reached. The working set is what is on screen -- a dozen lines at one or
# two blur levels, well under 20 MB -- so the budget below holds it several
# times over and evictions come off the cold end where nobody is looking.
#
# Separate budgets because the two are not interchangeable. A glow is keyed
# by word, size and radius, so a song full of long words mints hundreds of
# them; sharing one budget let that flood evict the lines, which are the
# expensive ones to rebuild.
PIX_BUDGET = 96 << 20
GLOW_BUDGET = 16 << 20


def _pm_bytes(pm: QPixmap) -> int:
    """Roughly what a pixmap costs to keep. Qt does not promise 32 bits per
    pixel, but every format this draws into is, and being out by a channel
    would move a budget, not break one."""
    return max(1, pm.width() * pm.height() * 4)


# DwmSetWindowAttribute, the two attributes that decide whether Windows 11
# draws its own decoration over a window it has already been told to make
# fullscreen. Both were added in Windows 11 and both are refused with
# E_INVALIDARG on Windows 10, which is a perfectly good answer and is
# ignored. Numbers rather than names because there is no Python binding for
# this and there is no reason to grow one.
_DWMWA_CORNER = 33          # DWMWA_WINDOW_CORNER_PREFERENCE
_DWMWA_BORDER = 34          # DWMWA_BORDER_COLOR
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

    The PLAYER's own stream, not the desktop's default output. Moving one
    application to another device is a thing people do, and the delay this is
    asked for belongs to the device the song comes out of rather than to
    whatever would play a notification beep. The default sink stands in while
    nothing is playing, so the window still knows where it is between tracks.

    ("", "") where there is nothing to ask -- no pactl, no PipeWire or
    PulseAudio, another platform. Everything then shares one offset, which is
    what it did before there was more than one.
    """
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
    got = _upgrade_sources(_read_config())
    if got.get("src_order"):
        got = dict(got, src_order=",".join(LS.lrclib_first(LS.carried(
            [n.strip() for n in str(got["src_order"]).split(",")]))))
    return {k: got[k] for k in DEFAULTS if k in got}


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
            # Zero included. It is a correction like any other -- "this track
            # is right as it stands, do not measure it" -- and dropping it
            # here would restore the measured offset on the next launch.
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


# The two names the renderers need from this module, handed over rather than
# imported back: `import lyrics_gui` from there would load a second copy of
# this module whenever the window is started as a script, which is how the
# .desktop file starts it.
RD.TEXT, RD._smooth = TEXT, _smooth


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
        # One caller at a time on the bus. Unlike the debug port -- whose
        # socket sorts out who asked for what -- python-dbus makes no such
        # promise, and the sampler now reads from its own thread while the
        # window seeks from the one it draws on. Every call under this lock is
        # a millisecond or so, so waiting for one costs nothing worth having.
        self._bus = threading.RLock()

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
        with self._bus:
            self._props = self._player = None

    def read(self, want_volume: bool) -> dict:
        with self._bus:
            return self._read(want_volume)

    def _read(self, want_volume: bool) -> dict:
        _, props, _ = self._ifaces()

        def position() -> tuple[float, float]:
            """The position, and the middle of the call that asked for it.

            A property read is a round trip over the session bus, and the
            answer describes where the song was somewhere inside it. See
            CdpTransport.read for why the middle is the honest stamp; the bus
            is slower than the debug port, so there is rather more of it here.
            """
            began = time.monotonic()
            got = float(props.Get(MPRIS, "Position")) / 1e6
            return got, began + (time.monotonic() - began) / 2

        m = props.Get(MPRIS, "Metadata")
        pos, at = position()
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
            pos, at = position()
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
        with self._bus:
            dbus, props, player = self._ifaces()
            trackid = props.Get(MPRIS, "Metadata")["mpris:trackid"]
            player.SetPosition(trackid, dbus.Int64(int(max(0.0, seconds) * 1e6)))

    def set_volume(self, v: float) -> None:
        with self._bus:
            dbus, props, _ = self._ifaces()
            props.Set(MPRIS, "Volume", dbus.Double(v))

    def command(self, name: str) -> None:
        with self._bus:
            _, _, player = self._ifaces()
            getattr(player, name)()


# How long the playback engine is given to say where it is before the reading
# goes ahead without it. Measured on this machine it answers in 0.35ms and is
# under 3.5ms at the 99th percentile, so this is not a budget -- it is the
# difference between degrading in half a second and hanging until the socket's
# own fifteen. Generous on purpose: around a seek Spotify's renderer is busy
# and a slow answer is still the right one, where falling back to the control
# state mid-song is a step in the clock.
ENGINE_WAIT_MS = 400
# The engine says where the audio is, but not smoothly: measured here at 60Hz
# against real time, its steps scatter with a standard deviation of 63ms and
# individual ones land 200ms out. That is the audio pipeline reporting itself
# in chunks, not the song stuttering, and passed on raw it is a word sweep
# that visibly shakes -- the clock's own slew does not take it out, because
# that was built for a source which is smooth and occasionally drifts, not one
# which is ragged every frame.
#
# So the engine is used as an ANCHOR, not as the position: a clock that runs
# at 1x on its own and is pulled towards the anchor. TAU is how hard --
# alpha = 1 - exp(-elapsed/TAU) per reading, which is a pull rather than a
# deadband, so it settles with no standing error and adds no lag of its own.
# SNAP is where a difference stops being scatter and becomes a real move (a
# seek, a hand-off) and is taken whole instead. Both are Spicy Lyrics'
# numbers, from the same problem on the same builds.
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

    name = "Spicetify"

    def __init__(self, port: int) -> None:
        self.port = port
        self.cdp = None
        self._dial = threading.Lock()
        # Which clock the last reading came from, and how long the engine has
        # been saying the same thing. The sampler takes nearly every reading,
        # but not quite all of them -- resync() takes one on the thread it is
        # called from -- and a stall is counted across readings, so the count
        # is kept straight rather than left to whichever arrives first.
        self.source = "engine"
        self._eng_pos: float | None = None
        self._eng_at = 0.0
        self._eng_lock = threading.Lock()
        # The smoothed engine clock: where it is, when that was, and whose
        # song it is. See _smooth.
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
            # The stall is looked for in the RAW reading. The smoothed one
            # goes on advancing by construction, so asking it whether the
            # engine has stopped would never get an answer.
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
        began = time.monotonic()
        got = self._conn().evaluate(JS_STATE)
        at = began + (time.monotonic() - began) / 2
        if not isinstance(got, dict) or not got.get("uri"):
            raise RuntimeError("no player state")
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
        # As on the bus: the sampler reads on its own thread while the window
        # seeks on the one it draws on, and the session manager is resolved
        # lazily. Guarding the resolution is enough -- each call after it runs
        # its own asyncio loop and shares nothing.
        self._get = threading.RLock()

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

        with self._get:
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

    The debug port leads on both platforms, because it is quick, because it is
    the one that also brings Spicy Lyrics, the browser and the queue with it,
    and -- the reason it leads on Linux too -- because it is the clock Spotify
    itself is drawn from.

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
    """
    if prefer == "smtc":
        return SmtcTransport()
    if prefer == "mpris":
        return MprisTransport()
    if prefer == "cdp":
        return CdpTransport(port)
    cdp = CdpTransport(port)
    if os.name != "nt" and MprisTransport.usable():
        return BackupTransport(cdp, MprisTransport()) if cdp.usable() \
            else MprisTransport()
    if os.name == "nt" and SmtcTransport.usable():
        return BackupTransport(cdp, SmtcTransport())
    return cdp


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
class Clock:
    def __init__(self, transport=None) -> None:
        self.io = transport if transport is not None else MprisTransport()
        # Held across `apply`, `position` and the assignments in `seek` -- the
        # three that read and write the same half-dozen floats. A window that
        # polls off its GUI thread would otherwise be able to read `_pos` from
        # before a reading and `_at` from after it, which is a position wrong
        # by the whole poll interval and would be stamped into a lyric.
        self.lock = threading.RLock()
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
        # Whether unpause_delay is the CEILING on a measured leap or the hold
        # itself. Measuring needs the player to be honest about where it
        # stopped, and where the same unpause reads 0.13s one time and 0.50s
        # the next, a number set by ear is the better one. See _apply.
        self.unpause_fixed = False
        self._resumed_at = 0.0
        self._bias = 0.0
        # Where the position was when playback resumed, and how far it had
        # already stepped by then. The window after a resume measures itself
        # against these rather than against the reading before it -- see
        # _apply, and why a sum of forward steps is not a measurement.
        self._resume_pos = 0.0
        self._resume_lead = 0.0
        # Which track the carried unpause leap belongs to. Its own field
        # rather than a reading of `_pos_tid`, because resync() clears that
        # one deliberately -- to stop the reading after a resync being eased
        # into -- and the bias was being dropped as a side effect of that,
        # which is the opposite of what resync asks for by passing keep_hold.
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
        return time.monotonic() - self._vol_set_at > 1.0

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
            if want_vol:
                self.volume = got.get("volume")
            self.tid, self.status = tid, status
            self.meta = got["meta"]
            resumed = status == "Playing" and not was_playing
            # How far the player's own clock jumped when it unpaused, which is
            # how far it is now ahead of the sound. Spotify leaps 0.253s at the
            # unpause and then keeps it -- it never comes back -- so cancelling
            # it for a quarter second and letting go put the words back ahead
            # of the voice for the rest of the song. It is carried instead,
            # until something re-establishes where playback is: a seek, a
            # resync, a new track, or the next pause.
            #
            # Taken from the player rather than assumed, because it is the
            # player's habit and not every one has it -- over the session bus
            # there is no leap at all, `pos - held` is nothing, and this
            # subtracts nothing. unpause_delay is the ceiling on it.
            # A jump this clock did not make itself: the scrubber in Spotify's
            # own window, a keyboard skip, another Connect device. A seek made
            # from HERE is written into `_pos`/`_raw` as it is sent, so the
            # reading that follows one is continuous with it and does not land
            # here -- which is what leaves resync's kept hold alone.
            #
            # The leap is a statement about a stretch of playback that has now
            # been thrown away. The pipeline is flushed by the seek, the audio
            # is back with the clock, and going on subtracting a quarter second
            # holds the words behind a voice that no longer leads them.
            #
            # SLEW_MAX is the boundary the clock already draws between drift it
            # will ease and a difference it takes whole; a difference too big to
            # ease is exactly what "went somewhere else" means, so there is no
            # second threshold to keep in step with this one. Inside RESUME_
            # SETTLE the same test would fire on the unpause leap arriving late,
            # which is the one forward step that is not a seek.
            jumped = (not resumed and status == "Playing" and was_playing
                      and tid == self._pos_tid and self._at
                      and at - self._resumed_at > RESUME_SETTLE
                      and abs(pos - (self._raw + (at - self._at))) > SLEW_MAX)
            if not resumed and (status != "Playing" or tid != self._bias_tid
                                or jumped):
                self._bias = 0.0
            elif (not resumed and self._at and not self.unpause_fixed
                    and at - self._resumed_at <= RESUME_MEASURE):
                # It does not always land in the first reading; take it when
                # it does.
                #
                # Measured from where the resume left off, NOT summed reading
                # by reading. The engine's position does not advance smoothly
                # -- it jitters a few milliseconds either side of free-running
                # and comes back -- and adding up only the forward halves of
                # that rectifies the noise into a bias. Sixty readings a second
                # for a second, at the +-8ms measured on this machine, made
                # tens of milliseconds of hold out of a player that had not
                # moved at all: the words sat that far behind the voice for the
                # rest of the song, every time, which is exactly steady enough
                # to be mistaken for a constant somewhere else.
                #
                # The displacement since the resume is the same measurement for
                # a real leap -- which lands and stays, so it shows here whole
                # however late it arrives -- and averages to nothing for jitter.
                free = self._resume_pos + (at - self._resumed_at)
                want = max(0.0, self._resume_lead + (pos - free))
                self._bias = min(self.unpause_delay,
                                 want if want > RESUME_STEP_FLOOR else 0.0)
            if resumed and self.unpause_fixed:
                # Stated, not measured. Nothing to read off the player and
                # nothing to accumulate: the hold is the setting, every
                # unpause, which is what makes it tunable by ear at all --
                # each 0.01 moves the words 10ms against the voice, in one
                # direction, every time.
                self._resume_lead = self.unpause_delay
                self._resume_pos = pos
                self._bias = self.unpause_delay
                self._resumed_at = at
            elif resumed:
                # Only the part of the step that real time cannot account for.
                # A position further on than it was is not by itself a clock
                # that has jumped: between the last reading and this one the
                # song was allowed to play, and on the debug port the engine's
                # position is the sound's own -- it is SUPPOSED to have moved.
                # Spotify does not announce itself playing at the instant the
                # audio starts, so by the first reading that says "Playing"
                # the sound has often been running for a few tens of ms, and
                # taking the whole step held the words back by exactly that,
                # for the rest of the track. What a leap means is a position
                # that has moved further than the clock on the wall.
                self._resume_lead = max(
                    0.0, (pos - held) - max(0.0, at - self._at))
                self._resume_pos = pos
                self._bias = min(
                    self.unpause_delay,
                    self._resume_lead
                    if self._resume_lead > RESUME_STEP_FLOOR else 0.0)
                self._resumed_at = at
            # The hold this replaces was a DURATION: subtract the delay, run it
            # out over the next quarter second, let go. That is the right shape
            # for a player whose audio is late coming back -- a thing that ends
            # -- and the wrong one for a clock that has stepped ahead and
            # stays there, because letting go is what puts the words back in
            # front of the voice. Same number, carried instead of spent.
            stale = (not resumed and status == "Playing" and tid == self._pos_tid
                     and pos == self._raw and at - self._at < STALE_HOLD)
            if not stale:
                held_back = pos - self._bias
                # Only across CONTINUOUS playback. The slew is here to absorb
                # the drift between the player's clock and this one without the
                # words visibly stepping, and drift is something that happens
                # while a song runs. A resume is not drift: the words were
                # parked where the song stopped, the audio has already started
                # somewhere ahead of them, and there is no continuity left to
                # protect -- so easing the difference in holds them at the
                # parked position for the whole of the first poll and then
                # slides them forward, which is the lurch this exists to
                # prevent, produced on purpose.
                # ...and not while the player is still settling from one.
                # It does not finish unpausing in a single reading: it can
                # report itself playing BEFORE it applies the forward leap its
                # position makes, and then the leap lands on the next poll --
                # by which time playback is already running, `was_playing` is
                # true, and the test above no longer recognises it as part of
                # the unpause. Measured over ten unpauses it arrived late on
                # four of them, +0.263s, and was eased in over the following
                # third of a second: the words start correct and then slide,
                # which is worse than a step and much harder to place. The
                # smaller one is this clock's own doing -- the hold running out
                # is a step in `held_back` too, and easing that is easing a
                # correction it just made on purpose.
                #
                # Everything arriving in this window is the unpause completing,
                # so it goes on immediately and whole.
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
        """How far the words are being held back for the last unpause.

        The leap the player made when it resumed and did not come back from,
        carried until something re-establishes where playback is. Worth having
        where it can be read: it is the one correction in here with no visible
        cause, and the difference between "the setting does nothing" and "the
        setting is doing exactly what it says and the fault is elsewhere" is
        this number.
        """
        return self._bias

    def position(self) -> float:
        with self.lock:
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
        began = time.monotonic()
        try:
            self.io.seek(seconds)
        except Exception:
            self._drop()
            return
        with self.lock:
            self._pos = self._raw = max(0.0, seconds)
            # Where the song went is known exactly; WHEN it went there is not.
            # The player takes the command somewhere inside the round trip, so
            # the middle of it is the honest anchor -- the same correction the
            # readings get, and for the same reason: this timestamp is what
            # every position between now and the next reading is measured from.
            self._at = began + (time.monotonic() - began) / 2
            if not keep_hold:
                self._bias = 0.0

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
        # Either a flag or something to ask. The window's is a SETTING, and
        # the settings menu rebinds the attribute rather than writing through
        # it, so a copy taken here would go on pinning after it was switched
        # off -- and, worse, stop when it was switched back on.
        self.pin_pause = pin_pause
        # The track the last reading reported, as the PLAYER gave it. Not the
        # same question as `clock.tid`, which --track overwrites after the
        # fact: a watcher comparing against that sees the override and the
        # reading disagree and thinks the song changed, twice per poll,
        # forever. This is only ever written here, once per reading.
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
                # `spotify_dom.connect` calls sys.exit when the debug port has
                # gone. SystemExit is not an Exception, and raised on the GUI
                # thread it used to take the window down with it; here it ends
                # nothing but the reading it arrived in.
                self.clock.status = "Error"
                got = None
            if got is not None:
                pin = self.pin_pause
                self.clock.apply(got, want_vol,
                                 bool(pin() if callable(pin) else pin))
                self.last_tid = got.get("tid") or None
            if self._going:
                self.read.emit()
            # A player that is not answering is not worth asking sixty times a
            # second: back off to the old rate until it does. Nothing is
            # moving while it is down, so there is nothing to be late for.
            self._wake.wait(self.every if self.clock.status != "Error"
                            else POLL_MS / 1000.0)
            self._wake.clear()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# What a song already on this machine is worth beside one only Genius knows
# about. It stands in for the popularity Genius supplies and a local index
# cannot -- pitched at the top of that range on purpose, so an equally good
# match the user already has, and has probably timed by hand, takes the tie.
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

EST_REVISION = 2
ANCHOR_GAP = 0.35
EST_RANGE = 0.75
EST_STEP = 0.005
EST_SIGMA = 0.08
MIN_ANCHORS = 8
EST_CONF_MIN = 0.18
CAL_MIN = 5
# The two gates on the SIZE of a measured correction, as against how confident
# the reading was.
#
# Confidence says the winning shift beat the runner-up; it does not say the
# winner was the right one. The way this fails is a latch: the true alignment
# is weak -- a soft entry, a lyric whose first line is early, an analysis that
# cut no clean edge under the voice -- and some other shift wins the curve
# outright. Confidence is then HIGH, because there really was one clear peak,
# and the number under it is nonsense. Those land big: half a second and more,
# which no community lyric sheet is actually out by.
#
# So a correction past EST_MAX is refused however well it scored. Scored
# against the tracks on this machine that have been tuned by ear -- the only
# truth there is -- the estimate's own median error runs 0.06s where it reads
# under 0.15s, 0.19s in the 0.15-0.25 band, 0.28s in 0.25-0.35, and 0.46s
# beyond that. Past a quarter of a second the error is as big as the
# correction it is offering, so the reading has stopped saying anything: not a
# worse fix, no fix at all.
#
# Nor is much given up by refusing them. Of 140 corrections made by ear here
# only five are bigger than 0.35s and the median is 0.03s, so songs genuinely
# out by half a second barely exist -- while readings CLAIMING half a second
# are common, twenty of them sitting exactly on the ±EST_RANGE rail, which is
# a curve with no peak in it running out of room rather than a song out by
# three quarters of a second.
EST_MAX = 0.25
# ...and the same reading taken twice, once on each half of the song, has to
# come back with the same answer. A real offset is a property of the recording
# and holds from the first line to the last; a latch is usually the doing of
# one stretch of the song and the other half does not agree with it. Neither
# half is asked to be confident on its own -- half the anchors is a noisier
# curve and the peak can be a close-run thing -- only to point the same way.
#
# Over the same hand-tuned tracks the halves' disagreement sorts the readings
# better than confidence does: under 0.05s apart the median error is 0.085s,
# between 0.05 and 0.12 it is 0.21s, past 0.25 it is 0.43s. Set where this and
# EST_MAX between them stop the disasters -- the worst correction any of those
# tracks would now be given is 0.20s out, against 3.04s under the confidence
# gate alone -- and no tighter, because tightening it further only refuses
# tracks the size gate has already made safe.
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
# HOW HARD A COVER IS TRIED. Three goes inside one fetch, a moment apart,
# then the fetch itself worth three: a cover that did not arrive used to be
# gone for the whole song, because art_url is set before the thread starts
# and the poll will not ask twice for the same url. So one timeout, one
# refused connection, one proxy having a bad second, and the song played
# through with the last song's picture on it -- silently, since the failure
# was caught and dropped. Which is how it turns up on a machine behind
# whatever Windows has in front of its sockets, on a song Spotify itself is
# showing perfectly well out of its own cache.
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
# The most an animated cover may occupy once it is decoded and sitting in
# pixmaps, in bytes.
#
# It used to have no ceiling at all, only a per-frame width, and the two are
# not the same thing: 30fps for up to 35 seconds is a thousand frames, and a
# thousand frames at 720px is 2.1GB of pixmap. That is the whole of the
# reported "2GB while a song with animated artwork is playing", and it is
# arithmetic rather than a leak. Even the ordinary case is not small -- the
# covers cached on this machine run 80 to 120 frames, which is 250MB on a 4K
# screen.
#
# When a cover will not fit, FRAMES are dropped and the picture is left
# alone: an animation played at 15fps instead of 30 is barely remarked on
# and a cover at half the resolution is the first thing anybody sees. See
# on_motion, which works out the stride and slows the clock to match.
MOTION_BUDGET = 192 << 20
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
                # Off the in-flight list either way, so the same album can be
                # asked for again when it comes round.
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
    gsearch_ready = pyqtSignal(str, object)
    gmatch_ready = pyqtSignal(object, object)
    backfill_progress = pyqtSignal(int, int)
    backfill_ready = pyqtSignal(object)
    queue_ready = pyqtSignal(object)
    suggest_ready = pyqtSignal(object)
    discover_ready = pyqtSignal(object)
    ne_roman_ready = pyqtSignal(str, object)
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
        self._play: str | None = None
        self._genius: tuple | None = None
        self._ne_roman: tuple | None = None
        self._album: str | None = None
        self._meta: dict = {}
        self._sources: set = set()
        self._order: list = []
        self._graft = True
        self._fold = True
        self.done: str = ""
        self._recents = False
        self._queue = False
        self._skip: tuple | None = None
        self._stood_in: str | None = None
        self._late = ""
        self._page_seen = False
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
        self._lock = threading.Lock()

    def request(self, tid: str, meta: dict | None = None, sources=None,
                order=None, graft=None, fold=None) -> None:
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
                # Emitted whatever has been typed since: the window knows
                # which query is on screen and drops an answer to any other.
                self.gsearch_ready.emit(q, got)
        with self._lock:
            self._gsearch_busy = False

    def request_gmatch(self, hit: dict) -> None:
        with self._lock:
            self._gmatch = dict(hit or {})

    def request_ahead(self, rows, sources, order) -> None:
        """Warm the cache for tracks that are coming up. See _warm.

        Cheap where there is nothing to do: a track whose answer is already on
        disk costs the walk one stat and no round trip, so this can be handed
        the same three tracks every minute without spending anything on them.
        """
        with self._lock:
            self._ahead = [(str(tid), dict(meta), set(sources), list(order))
                           for tid, meta in (rows or []) if tid]
            # Bumped whoever is warming out of putting a track back on a list
            # that is no longer the list it took it from; see _warm.
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

        Spicy Lyrics is therefore not warmed, and cannot be: it fetches inside
        the page and only for the track that is playing. What is warmed is the
        chain behind it, which is the part that takes seconds.

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
                gen = self._ahead_gen
                job = None if self._want is not None else self._ahead.pop(0)
            if job is None:
                if waited >= WARM_PATIENCE:
                    # Longer than the scan that would rebuild this. Whatever
                    # was coming up when the list was written is not evidence
                    # about what is coming up now.
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
                # Yields to a real request the moment one arrives, and not
                # only between tracks: warming the next song while the user
                # waits on this one is the exact trade this thread exists to
                # avoid, and a walk takes seconds.
                got = LS.fallback(tid, meta, "none", enabled=want, order=order,
                                  alive=lambda: not self.stop and self._want is None)
            except Exception:                            # noqa: BLE001
                pass
            with self._lock:
                # Cut short part way: fallback stores nothing from a walk it
                # gave up on, so the track has to go back or the look-ahead
                # has quietly dropped it. Only onto the list it came off --
                # a scan since then has replaced it with what is coming up
                # now, and this one is not that.
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
        watch: dict[str, tuple] = {}
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
                gmatch, self._gmatch = self._gmatch, None
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
                watch.clear()
                if lines and self._late == tid:
                    now = time.monotonic()
                    watch[tid] = (now + SPICY_GRACE, now + SPICY_LOOK)
            elif tid:
                # Asked for, but still inside the backoff from a load that
                # came back empty. The request has to be put back: it was
                # taken off _want at the top of the loop, and nothing else
                # here would ever ask again. What covered for that was the
                # window's own poll, which re-requests four times a second --
                # but only while the screen is EMPTY, so the retry that
                # matters least is the only one that survived.
                with self._lock:
                    if self._want is None:
                        self._want = tid
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
            if gmatch is not None and not self.stop:
                self.gmatch_ready.emit(gmatch, self._genius_match(gmatch))
            if self._backfill_at is not None and not self.stop:
                self._backfill_batch()
            if want_index and self._index_at is None:
                self._index_at, self._index_songs = 0, []
            if self._index_at is not None:
                self._index_batch()
            if watch and not self.stop:
                self._watch_spicy(watch)
            time.sleep(POLL_WAITING if tid and tid in pending else POLL_IDLE)

    def _watch_spicy(self, watch: dict) -> None:
        """Ask again for the word timing Spicy Lyrics did not have yet.

        The walk answered while Spicy Lyrics was still fetching -- or while it
        was holding the line-level copy it puts up before the word-timed one
        arrives -- so the screen is showing somebody else's document for a
        song the user's first source word-syncs. Look every SPICY_LOOK while
        the grace lasts and every SPICY_SLOW after it, until it turns up or
        the track changes; when it does, re-request the track and _load hands
        it over. The entry is dropped by the caller on the next load, which is
        what ends this on a track change.
        """
        now = time.monotonic()
        for tid, (grace, due) in list(watch.items()):
            if now < due:
                continue
            body, reached = self._spicy_body(tid)
            if not reached:
                # A read that did not get through says nothing about what
                # Spicy Lyrics has. Dropping the watch on it ended the
                # looking for good on one dropped socket, and left the song
                # on somebody else's document for the rest of its play; hang
                # on and ask again at the slow pace.
                watch[tid] = (grace, now + SPICY_SLOW)
                continue
            if body and LS.quality(body) == "syllable":
                watch.pop(tid, None)
                with self._lock:
                    if self._want is None:
                        self._want = tid
            else:
                watch[tid] = (grace,
                              now + (SPICY_LOOK if now < grace else SPICY_SLOW))

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

        Throwing it away used to be _spicy_body's private business, and it was
        the only caller that did it. Every other read -- the artists, the
        audio analysis, the queue, a page of the index -- swallowed its
        exception and left the poisoned socket in place for whoever asked
        next, which is Spicy Lyrics' own copy of the next song. That is the
        shape of the complaint: one song will not load while the one before
        it loaded fine.
        """
        with self._lock:
            if cdp is not None and self.cdp is not cdp:
                # The connection this call failed on has already been thrown
                # away, and what is up now is somebody else's fresh one.
                # Dropping that is how one thread's timeout came to cost
                # every other thread its working socket, in a round nobody
                # can win: each of them drops the last one made.
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
        _spicy_body is the one place that has to tell "the page says it has
        nothing" apart from "the page did not answer", and it asks its own way.
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
        """One page of Cache Storage per call, so the loop keeps serving
        lyric requests while a full index is being built."""
        batch = self._ask(
            SL.JS_DUMP_PAGE % (json.dumps(SL.CACHE_PREFIX), self._index_at, 100))
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
        # "(Romanized)", "[Live]" and the rest are Genius's own bookkeeping and
        # match nothing in the catalogue -- but a title that is ALL brackets is
        # the song's actual name, so the trim is only kept if it leaves one.
        title = re.sub(r"[\(\[\{].*?[\)\]\}]", "", raw).strip() or raw
        artist = (hit.get("artist") or "").strip()
        if GR.GENIUS_ACCOUNT.search(artist):
            artist = ""      # "Genius Romanizations" is not who recorded it
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

    def _audio(self, tid: str):
        """Audio analysis, on this same thread and socket -- it is one round trip
        and Spicetify memoises it per track inside the page.

        The one call here that waits on a promise the page has to fetch, so it
        is the one most likely to time out -- and the reason _drop matters: it
        runs straight after the lyrics have gone up, and whatever it leaves
        behind is what the next song's lyrics are read through.
        """
        if self.cdp is None:
            return None
        return self._ask(Beat.JS % json.dumps(f"spotify:track:{tid}"))

    def _spicy_body(self, tid: str):
        """Spicy Lyrics' own copy of a track, and whether the page answered.

        None with reached=True means Spicy Lyrics simply has nothing for this
        track *yet* -- which on a cold song is different from having nothing at
        all, and is why the caller keeps asking (see SPICY_GRACE).
        """
        for _attempt in (1, 2):
            cdp = None
            try:
                cdp = self._conn()
                res = cdp.evaluate(
                    SL.JS_GET % SL._j(SL.CACHE_PREFIX, SL.IDB_NAME, SL.IDB_STORE, tid)
                ) or {}
                self._page_seen = True
                return res.get("body"), True
            except Exception:                            # noqa: BLE001
                self._drop(cdp)
        return None, False

    def _spicy_hold(self, tid: str, began: float):
        """Spicy Lyrics' word-timed copy if it lands within SPICY_HOLD, else None.

        The deadline runs from the start of the load rather than from here,
        so a walk that really did go to the network has already spent it and
        this returns at once -- the hold is for the ordinary case, where the
        walk answered off the disk before Spicy Lyrics' own request had left
        the page.

        Gives up the moment the track changes. The window asks for whatever
        is playing, so a second track id waiting to be loaded means nobody is
        going to look at this one's lyrics, and holding the thread here would
        only make the next song later.
        """
        while not self.stop:
            if began + SPICY_HOLD - time.monotonic() <= 0:
                # Asked before the round trip, not after it, or the deadline
                # is only honoured once it has already been overrun. This is
                # the case the docstring above describes -- a walk that really
                # went to the network -- and it was still paying for one more
                # read of the page, on the connection that walk had just spent
                # several seconds not using.
                return None
            body, ok = self._spicy_body(tid)
            if ok and body and LS.quality(body) == "syllable":
                return body
            left = began + SPICY_HOLD - time.monotonic()
            if left <= 0:
                return None
            with self._lock:
                moved = self._want is not None and self._want != tid
            if moved:
                return None
            time.sleep(min(SPICY_LOOK, left))
        return None

    def _load(self, tid: str, settled: bool = True):
        self._late = ""
        began = time.monotonic()
        with self._lock:
            spicy = "spicy" in self._sources or not self._sources
            order, graft = list(self._order), self._graft
        ahead = order[:order.index("spicy")] if "spicy" in order else []
        if not spicy:
            return self._only_fallback(tid)
        body, reached = self._spicy_body(tid)
        if not reached:
            # The page did not answer -- the socket dropped, Spotify is still
            # starting. That is not Spicy Lyrics saying it has nothing, so the
            # song must not spend the rest of its play on whoever the chain
            # finds instead: mark it late, and the watch below asks again for
            # as long as the track is up.
            #
            # Only where the page has answered before. On Linux the clock
            # comes off MPRIS, so the whole window runs against a Spotify
            # started without the debug port -- and there the watch would be
            # a failed connection every SPICY_SLOW, all day, for an answer
            # that is never coming.
            self._late = tid if self._page_seen else ""
            return self._only_fallback(tid)
        have = LS.quality(body) if body else "none"
        # Nothing from Spicy Lyrics -- or nothing WORD-TIMED from it -- is not
        # the same answer as there being nothing to have. It fetches inside
        # the page, and on a cold song it lands late and it lands twice: a
        # line-level copy first and the word-timed one after. Say so, so the
        # walk's answer can be shown now and handed back when Spicy's own
        # arrives, which is what the order asks for.
        self._late = "" if have == "syllable" else tid
        # Whatever is already here goes up first, before anybody is asked
        # anything. Spicy Lyrics has usually cached the song before the window
        # even knows the track changed, and the walk that might improve on it
        # can take seconds across ten providers -- there is no reason to spend
        # them looking at an empty screen holding a document that is very
        # probably the one that wins anyway. If Spicy has nothing, the last
        # answer stored for this track on disk stands in: it was good enough
        # to keep, so it is good enough to read while a better one is fetched.
        # Shaped once, and the same object handed to the interim and to the
        # answer below. Shaping twice made two documents that say exactly the
        # same thing, and the window compares an arriving answer with the one
        # it holds by identity -- so the second of them read as a NEW lyric
        # for the same song and cost a full rebuild: every line laid out
        # again, every pixmap dropped, the offset re-measured on the drawing
        # thread. Once per track, every track, in the second after the words
        # first appear.
        shaped = None
        if body:
            shaped = self._shaped(body)
            self._interim(tid, shaped, shaped=True)
        elif self._stood_in != tid:
            self._stood_in = tid
            self._interim(tid, LS.stored(tid))
        better = None
        if (have != "syllable" or ahead) and (body or settled):
            better = self._fallback(tid, have, ahead, local=body)
        # Keep asking Spicy Lyrics until SPICY_HOLD is up, before taking
        # anybody else's answer. Asking exactly once here was not enough: the
        # walk it was meant to outlast usually never went to the network at
        # all -- a month of answers sits on disk, so `better` comes back in a
        # millisecond -- and Spicy Lyrics' own fetch was still a few hundred
        # of them away. So the song was credited to NetEase or Apple Music
        # and put right a second later, on nearly every song whose three-day
        # cache entry had aged out. The watch below would still catch it;
        # this stops the wrong name going up at all. Not where the user has
        # ranked something above Spicy Lyrics: then the walk's answer is the
        # one they asked for.
        if better is not None and not ahead and have != "syllable":
            again = self._spicy_hold(tid, began)
            if again is not None:
                body, have, better, shaped = again, "syllable", None, None
                self._late = ""
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
        # After the unlump, so a mark that was glued into a lumped syllable
        # has been cut out of it and can be seen for what it is.
        body = LS.quiet_marks(body)
        if fold:
            body = LS.split_asides(body)
        return body

    def _interim(self, tid: str, body, shaped: bool = False) -> None:
        """Show a document now, while a better one is still being looked for.

        Deliberately skips _duet: that goes to the network too, and the whole
        point of this emit is to reach the screen before any of that happens.
        The duet flags arrive with the final answer a moment later.

        `shaped` says the caller has already run _shaped over this one and is
        handing over the very object it means to keep -- see _load. The walk's
        own reports have not, and are shaped here.
        """
        if not body or self.stop:
            return
        if not shaped:
            body = self._shaped(body)
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
        """Spicy Lyrics switched off: whatever the rest of the chain has.

        Shaped like any other answer. With Spicy Lyrics off this is where
        NetEase, QQ Music and Kugou documents actually reach the screen, and
        they are the ones whose ad-libs need putting back.
        """
        body = self._fallback(tid, "none")
        if not body:
            return [], None
        body = self._shaped(body)
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
            order = list(self._order)
        try:
            got = LS.fallback(tid, meta, have, enabled=want, order=order,
                              ahead=ahead, local=local,
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
                # The side the dots hang off is the side of the line they lead
                # INTO, not the window's default. In a duet the two voices sit
                # against opposite edges, and dots pinned to the left through
                # an eight-bar gap in front of a right-hand line count down on
                # the wrong side of the screen -- they are that singer's
                # count-in, so they wait where that singer will arrive.
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
            # An editor that was walking Spotify along with it and then went
            # away -- closed, crashed, unplugged -- must not leave the player
            # muted and running. Nobody is timing against it any more.
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
        now, pos = time.monotonic(), float(v.position())
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
        # Measured from what was last SAID, not from the last tick. Anchored
        # on the tick, a drift that comes on slowly is never more than a
        # fiftieth of a second at a time, so it was never announced at all --
        # and the editor was extrapolating from a reading that had quietly
        # stopped describing the song.
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
                       # The two halves, apart. `offset` is a sum whose meaning
                       # changes with `live` -- it drops the per-track part the
                       # moment an editor's document is on screen -- so anyone
                       # stamping times against this clock has to be told which
                       # number is which. An editor wants `base` and only
                       # `base`: the per-track correction describes how far the
                       # SONG'S OWN lyric sits out of true, and the document
                       # being written is a different document.
                       base=float(v.offset),
                       track=round(float(v.track_offset()) - float(v.offset), 4),
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
        elif cmd in ("doc", "source_doc"):
            # Two different questions, and they had one answer between them.
            # `doc` is "what is on screen"; while an editor is pushing, that
            # is the editor's own file, handed straight back to it. Anybody
            # asking a PLAYER for lyrics means the other question -- what this
            # song's own document is -- so `source_doc` answers that from the
            # copy kept aside when the push landed.
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
                # Always an answer. A reply that is neither a document nor a
                # refusal tells the asker nothing, so it sits out its timeout
                # and reports "the player did not answer" -- which is untrue
                # and hides the only useful part.
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
            # Where the editor's own audio is, for a file being timed against
            # a local copy rather than against Spotify. See follow_editor.
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
    art_ready = pyqtSignal(str, object)
    font_ready = pyqtSignal(str)
    device_ready = pyqtSignal(str, str)

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
        self.art_side = args.art_side
        self.view_mode = args.view_mode
        self.show_volume = args.volume_bar
        self.motion_art = args.motion_art
        self.bg_mode = args.bg
        self.viz = args.viz
        self.viz_mode = args.viz_mode
        self.bg_dim = args.bg_dim
        self.bg_motion = args.bg_motion
        self.align = args.align
        self.pop = args.pop
        self.rise = args.rise
        self.pop_min = args.pop_min
        # An unknown name in gui.json falls back rather than taking the window
        # down on the way up: a settings file can outlive the renderer it names.
        self.renderer = (args.renderer if args.renderer in RD.RENDERERS
                         else DEFAULTS["renderer"])
        self.render = RD.RENDERERS[self.renderer](self)
        self.edge = args.edge
        self.focus = args.focus
        # What O turns focus back on to: the width it had when it was last
        # switched off, so the key returns the setting rather than a default.
        self._focus_on = args.focus or 2
        self.line_spacing = args.line_spacing
        self.interlude = args.interlude
        self.scroll_lead = args.scroll_lead
        self.resync = args.resync
        self.auto_time = args.auto_time
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
        self.spin = args.spin
        self.zero_g = args.zero_g
        self.clouds = args.clouds
        self.show_now_card = args.browse_now
        self.browse_art = args.browse_art
        self.drift: dict = {}
        self.cloudy: dict = {}
        self.drift_at = 0.0
        self.source = ""
        self.dropped_from = ""
        self.own_body = None
        # The track whose lyrics R has asked for again, with the ones it is
        # replacing still on screen. See reset_track and on_lyrics.
        self.reloading: str | None = None
        # What the lines on screen say, as they arrived. See same_lyric.
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
        self.track_at = time.monotonic()
        self.clock = Clock(make_transport(args.port, getattr(args, 'player', 'auto')))
        self.clock.unpause_delay = float(args.unpause_delay)
        self.clock.unpause_fixed = (args.unpause_mode == UNPAUSE_MODES[1])
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
        # Which section of the Keys panel is on show, where the window is too
        # small to show them all at once. -1 until anybody pages.
        self.help_tab = 0
        self.help_tab_rects: list = []
        self.show_info = False
        self.show_search = False
        self.query = ""
        self.hits: list[dict] = []
        self.hit_idx = 0
        self.hit_top = 0
        self.search_rects: list[tuple] = []
        self.local_hits: list[dict] = []
        self._trouble_said: dict[str, float] = {}
        self._follow_at = 0.0
        self._follow_cmd_at = 0.0
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
        # Two caches, not one, and both of them least-recently-used. See
        # PIX_BUDGET: a shared dict emptied wholesale is where the stutter
        # was.
        self.pix_cache: OrderedDict = OrderedDict()
        self.glow_cache: OrderedDict = OrderedDict()
        self._pix_bytes = self._glow_bytes = 0
        self.art_bg: QPixmap | None = None
        self.art_luma = 0.40
        self.art_full: QPixmap | None = None
        self.art_url = ""
        # How many fetches each cover url has already cost, so a url that
        # cannot be had is dropped rather than asked for forever. See on_art.
        self._art_fails: dict = {}
        self.art_gen = 0
        self.motion = MotionArt()
        self.motion_frames: list = []
        self.motion_key = ""
        self.motion_at = 0.0
        # Frames a second AS KEPT, which is MOTION_FPS divided by whatever
        # stride the budget forced. See on_motion.
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
        # Open, not shut: a track opening on a chord should answer to it from
        # the first frame, and one opening on drums closes the gate inside a
        # second anyway.
        self._viz_tone = 1.0
        self._viz_lvl = 0.0
        self._viz_kick = 0.0
        self._viz_at = 0.0
        self._viz_key = None
        self._viz_pm: QPixmap | None = None
        self._viz_last = 0.0
        _disk = {} if args.no_persist else load_settings()
        # Which output the sound is coming out of, and what the global offset
        # was set to on each of the ones seen so far. See on_device.
        self.device = self.device_name = ""
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
        self.fetcher.ready.connect(self.on_lyrics)
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
        # Nothing else ages the lyric cache out, and a document is kept for as
        # long as the song is still being played, so the only pass over it is
        # this one: once a day, off the startup path, drop what has gone a
        # month unheard.
        threading.Thread(target=LS.sweep, daemon=True).start()

        self.aligner = Aligner(self.align_settings)
        self.aligner.finished_track.connect(self.on_aligned)
        self.aligner.progress.connect(self.toast)
        self.align_thread = threading.Thread(target=self.aligner.run, daemon=True)
        self.align_thread.start()
        self._ahead_at = 0.0

        self.link = LiveLink(self)
        self.link.clear.connect(self.drop_live_lyric)
        self.link.seek.connect(lambda p: self.clock.seek(p))
        self.link.follow.connect(self.follow_editor)
        self.link.let_go.connect(self.unfollow_editor)

        # One reading before the pump starts, so the window comes up already
        # knowing the song rather than showing an empty frame for a sixtieth
        # of a second. It is also the only reading taken on this thread.
        self._seen_tid: str | None = None
        self.clock.poll(self.resync)
        # What the last reading the window ACTED on said. Compared against the
        # sampler's own record rather than the clock, so that --track, which
        # overwrites the clock's id after every poll, cannot look like the
        # song changing back and forth. See on_reading.
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
        self._frame_due = time.monotonic()
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
            self._frame_due = time.monotonic()
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
            # In a finally because the old repeating timer would have carried
            # on through a raised frame and this one would not: one traceback
            # out of tick would leave the window alive but permanently frozen.
            period = 1.0 / max(1.0, self.eff_hz if self.showing() else FRAME_IDLE_HZ)
            self._frame_due += period
            delay = self._frame_due - time.monotonic()
            if delay < -period:
                # A long stall: a slow fetch on this thread, a resize, the
                # machine suspended. Start the cadence again from here rather
                # than firing a burst of frames chasing a moment that has gone.
                self._frame_due = time.monotonic() + period
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
        f = QFont(self.family, int(self.lyric_px() * (0.66 if background else 1.0)))
        return self._weigh(f, self._weight(QFont.Weight.Black))

    def ui_font(self, px: float, weight=QFont.Weight.DemiBold) -> QFont:
        f = QFont(self.family, max(8, int(px)))
        return self._weigh(f, self._weight(weight)
                           if weight >= QFont.Weight.Black else weight)

    # -- data ------------------------------------------------------------
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
        if (((self.align_on and self.align_ahead) or self.fetch_ahead)
                and self.clock.status == "Playing"
                and time.monotonic() - self._ahead_at > 60.0):
            self._ahead_at = time.monotonic()
            self.fetcher.request_queue()
        if getattr(self.args, "track", None):
            self.clock.tid = self.args.track
        self._seen_tid = self.clock.tid
        if self.clock.tid and self.clock.tid != prev:
            self.reset_track("Loading lyrics…")
            self._ahead_at = 0.0
            handed_over = prev is not None and time.monotonic() - self.skip_at > 3.0
            if handed_over and self.resync:
                QTimer.singleShot(800, self.clock.resync)
        elif self.clock.tid and not self.lines:
            self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                                 self.source_order(), self.ne_graft, self.fold_adlibs)
        length = self.clock.meta.get("length", 0.0)
        left = length - self.clock.position() if length else 99.0
        # Both of the rates this used to run at while paused were about the
        # CLOCK -- how long after an unpause the words move at all, and how
        # long the leap took to arrive. The sampler answers both of those in a
        # sixtieth of a second now, whatever this timer is doing. What is left
        # to hurry for is a screen still waiting on a lyric.
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
        elif self.motion_frames or self.motion_key:
            # A track with no album and no title to look one up by, or the
            # setting switched off. The frames belonged to the song before it
            # and are a couple of hundred megabytes; letting go of them was
            # only ever done on the way IN to another animated cover, so a
            # song without one kept the last one resident for as long as it
            # played.
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
        # Same words, re-folded: every line that survives the new gap keeps
        # its picture. See line_pixmap.
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

        Dropping a file used to last until the song changed, which is the
        wrong lifetime for the thing people drop: a document somebody timed
        themselves is the best copy of that song that exists anywhere, and
        having to find it again on every play made it the least convenient.
        It is saved where an alignment made here is saved, and ranked as one
        -- so where "Aligned here" sits in the Sources order is where a
        dropped file sits too.

        R takes it off again: reload forgets the lookups for the track and
        this document with them, which is the same gesture that already means
        "that answer was wrong, go and ask again".
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
        kept = ""
        if tid and LS.save_aligned(tid, SL.payload(body), hand=name):
            # The stored lookup would otherwise answer for this track before
            # anybody asks the local slot, and the drop would come back only
            # until the cache aged out.
            LS.forget(tid)
            kept = ", kept for this track"
        self.toast(f"{name} — {timed}/{len(lines)} lines timed{kept}")
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
            # The song's own document, kept aside before the editor's takes
            # the screen. Without it "fetch what the player is showing"
            # answers with whatever the editor last pushed -- which is the
            # editor's own file, handed back to it as if it were a source.
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

        So Spotify is put where their file is and kept there: seeked when it
        drifts more than FOLLOW_DRIFT, playing while their file plays, paused
        when they pause. Muted the whole time it is playing, because two
        copies of one song a fraction of a second apart is not something
        anybody can time against -- and unmuted the moment they stop, so what
        is handed back is a player sitting where they are, audible.

        Only while their document is the one on screen. The editor sends this
        only when it is timing against a local file, but "there is an editor
        attached" is not on its own a reason for this window to take hold of
        somebody's playback.
        """
        if self.dropped is None or self.dropped != self.clock.tid:
            return
        self._follow_at = time.monotonic()
        want = max(0.0, float(pos)) + self.track_offset()
        if abs(self.clock.position() - want) > FOLLOW_DRIFT:
            self.clock.seek(want)
        if playing:
            self._mute_for_editor()
        self._transport(playing)
        if not playing:
            self._unmute_for_editor()

    def _transport(self, playing: bool) -> None:
        """Put Spotify into the play state the editor is in, at most one
        command every FOLLOW_STEADY -- the status this reads is a poll or two
        behind the command that changes it, and without the wait a pause
        arriving eight times a second is eight PlayPauses."""
        if playing == (self.clock.status == "Playing"):
            return
        now = time.monotonic()
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
                and time.monotonic() - self._follow_at > FOLLOW_GONE):
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
            self._follow_cmd_at = time.monotonic()
            self.clock.command("PlayPause")
        self._unmute_for_editor()
        self._follow_at = 0.0

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
                                 self.source_order(), self.ne_graft, self.fold_adlibs)

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
        # Said outright rather than left to the order of the two lines below
        # it: a second picture dropped on a song already wearing one is still
        # a picture somebody dropped, and reading it off dropped_art would
        # have this refuse it.
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
        # Whatever was being timed, it was being timed against the song that
        # was playing. Hand the player back rather than leaving it muted on
        # the next one -- but leave it PLAYING, since the track changing is
        # somebody listening to something, not somebody stopping.
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
        self.track_at = time.monotonic()
        self._section = 0
        self._viz_ch = [0.0] * 12
        self._viz_tone = 1.0
        self._viz_lvl = self._viz_kick = 0.0
        self.status_text = status
        if self.clock.tid:
            self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                                 self.source_order(), self.ne_graft, self.fold_adlibs)

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
            # The download gave up. Nothing would ever ask again: art_url is
            # set to the wanted url before the thread starts, so the poll's
            # own "have we already asked for this one" is what kept the song
            # on the last song's cover for the rest of its play. Handing the
            # url back is what lets the next poll ask afresh -- a few times,
            # and then no more, because a url that is genuinely gone should
            # not be asked for four times a second until the track changes.
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
        one track would be twice the intended fix. The measurement is kept, and
        goes on to serve as one of the reference points calibration() reads.

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
        self._cal_gen += 1
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
                dev, name = audio_sink()
            except Exception:                            # noqa: BLE001
                dev, name = "", ""
            if dev != self.device:
                self.device_ready.emit(dev, name)
            time.sleep(DEVICE_POLL)

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
        """
        if dev == self.device:
            return
        if self.device:
            self.dev_offsets[self.device] = round(self.offset, 3)
        was, self.device = self.device, dev
        self.device_name = name or dev
        if not dev:
            return
        if dev in self.dev_offsets:
            self.offset = round(float(self.dev_offsets[dev]), 3)
        else:
            self.dev_offsets[dev] = round(self.offset, 3)
        # Nothing is said about the output the window came up on: that is not
        # a change, it is where it started.
        if was:
            self.toast(f"{self.device_name} — offset {self.offset:+.2f}s")

    def device_offsets(self) -> dict:
        """Every output's offset, with the one in use kept up to date.

        The live value lives in `offset` -- the menu, the keys and the reset
        all write there and know nothing about outputs -- so it is folded in
        here rather than mirrored on every path that could touch it.
        """
        got = {k: round(float(v), 3) for k, v in self.dev_offsets.items()}
        if self.device:
            got[self.device] = round(self.offset, 3)
        return got

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

        The gates are doing real work here and are deliberately strict. A wrong
        offset applied silently is worse than no offset at all: the lyrics were
        merely out before, and now they are out and the program is insisting
        otherwise. Three of them, asking three different questions -- was the
        reading clear (conf), did the song say the same thing twice (spread),
        and is the answer a size a lyric sheet is ever actually out by
        (EST_MAX) -- because the readings that are badly wrong pass the first
        one comfortably. See EST_MAX.

        The size is judged AFTER the calibration is taken off, since that is
        the number the words are actually moved by. A standing bias of a tenth
        of a second is not evidence about this track and should not count
        against its correction, in either direction.
        """
        if not tid or not self.auto_time or tid in self.offsets:
            return 0.0
        got = self.est_raw.get(tid)
        if not got or got["conf"] < EST_CONF_MIN:
            return 0.0
        if got.get("spread", EST_RANGE * 2.0) > EST_AGREE:
            return 0.0
        bias, n = self.calibration()
        if n < CAL_MIN:
            return 0.0
        delta = round(got["delta"] - bias, 3)
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

    def on_lyrics(self, tid: str, lines, body, force: bool = False) -> None:
        if tid != self.clock.tid:
            return
        if not force and self.dropped == tid and body is not self.body:
            # An editor's document is on screen, so this one is not drawn --
            # but it IS kept. It is the song's own copy, which is what the
            # editor asks for with source_doc and what R was pressed to go
            # and fetch; dropping it on the floor here is how a reload made
            # under a live document came to have no effect anybody could see.
            if body is not None and self.own_body is None:
                self.own_body = body
            return
        if not lines and self.lines and not (self.reloading == tid
                                             and self.fetcher.done == tid):
            # Nothing to put up and something already up: keep what is there.
            # The one exception is a reload that has now been answered with
            # nothing -- R is how somebody shakes a bad answer loose, and a
            # window that went on showing the old one would have said the key
            # did nothing at all. `done` is the fetcher saying it has finished
            # asking, so the empty first pass of a walk still does not count.
            return
        if self.reloading == tid:
            self.reloading = None
        same = self.same_lyric(lines, body)
        if same:
            # The same words at the same times, arriving again. It happens on
            # nearly every song and more than once: the interim goes up off
            # Spicy Lyrics' copy, the walk reports its best answer as it
            # lands, and then the load returns that same answer as its own --
            # three handovers, two of which draw exactly what is already
            # there. Keep the newer document, because it is the one carrying
            # the credit, and leave the screen alone.
            self.body = body if body is not None else self.body
            self.source = str(SL.payload(self.body or {}).get("_source") or "")
            return
        self._drawn = self.lyric_key(lines)
        self.raw = lines or []
        self.body = body
        self.source = str(SL.payload(body or {}).get("_source") or "")
        self.lines = self.build_lines()
        # Asked of the whole document, not of the line being drawn: a Japanese
        # lyric has lines that are all kanji, and one of those is not a Chinese
        # song. One of THESE is.
        self.japanese = any(SL.KANA.search(ln.get("text") or "")
                            for ln in self.lines)
        self.apply_romaji_fixes()
        self.synced = any(ln["start"] is not None for ln in self.lines)
        if not same:
            self.est_tid = None
        self.measure_offset()
        if not same:
            # The LAYOUT goes, because it carries the times and this is a
            # document that disagrees about them. The drawn lines stay: they
            # are keyed by their ink, and a better answer mid-song is nearly
            # always the same words with a better clock under them. Throwing
            # them away here is what made a refresh stall the window.
            self.layout_cache.clear()
        if not self.lines:
            self.status_text = "No cached lyrics yet — waiting…"
        elif not self.synced:
            self.status_text = "Unsynced lyrics"
        else:
            self.status_text = ""
        self.maybe_auto_genius()
        self.say_alignment_outranked(tid)

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

        The catalogue, never the door: a document fetched through Lyrics+ with
        `source=apple` is Apple Music's, and saying "Lyrics+" instead named
        the scraper and left the reader no wiser about who wrote the words.
        The upstream is still printed where it says something the name does
        not -- a blend reports its whole makeup -- and dropped where it only
        repeats it.

        Where the words and the clock come from different places the label says
        both. A NetEase-timed document used to report as plain "Spicy Lyrics",
        which credits the half of it that could not do the thing you are
        watching it do.
        """
        via = {"apple": "Apple Music", "musixmatch": "Musixmatch",
               "musixmatch-word": "Musixmatch", "qq": "QQ Music",
               "deezer": "Deezer", "lyricsplus": "LyricsPlus Community",
               "qaple": "Apple Music with QQ"}
        # The same names as this program's own source keys, for the reading
        # below: a door is not a catalogue, and where the two disagree it is
        # the catalogue that gets printed.
        was_really = {"apple": "apple", "qaple": "blend", "qq": "qq",
                      "musixmatch": "mxm", "musixmatch-word": "mxm",
                      "lyricsplus": "lyricsplus"}
        # A document somebody is writing here is not a document from a
        # source. Its payload carries no `_source` at all, so this used to
        # fall all the way through to "Spicy Lyrics" and credit the work to a
        # database that has never seen it.
        if self.dropped is not None and self.dropped == self.clock.tid:
            whose = str(getattr(self, "dropped_from", "") or "")
            return f"the synchroniser · {whose}" if whose else "the synchroniser"
        src = self.source
        # LyricsPlus' server has no filter for its own submissions: asked for
        # them by name it hands back its Apple+QQ reconciliation instead
        # about a third of the time, and a document of Apple's words with
        # QQ's clock is that, whichever door it came through. It is refused
        # at the door now (see _honoured in lyric_sources), but the ones
        # fetched before that are still in the cache, so the reading is put
        # right here as well -- every copy this program has filed under
        # lyricsplus is one of them.
        upstream = was_really.get(str(doc.get("_via") or "").lower())
        if src == "lyricsplus" and upstream and upstream != "lyricsplus":
            src = upstream
        alone = str(doc.get("_alone") or "")
        if src in BLENDS and alone:
            src = "" if alone == "spicy" else alone
        hand = str(doc.get("_hand") or "")
        if src == "local" and hand:
            return f"timed by hand · {hand}"
        name = {"amll": "amll-ttml-db", "apple": "Apple Music",
                "bini": "Apple Music · BiniLyrics", "unison": "Unison",
                "lyricsplus": "LyricsPlus Community",
                "qq": "QQ Music", "kugou": "Kugou",
                "netease": "NetEase Cloud Music", "mxm": "Musixmatch",
                "deezer": "Deezer", "blend": "Apple Music with QQ",
                "kublend": "Apple Music with Kugou",
                "neblend": "Apple Music with NetEase",
                "triblend": "Apple Music with NetEase and QQ",
                "kutriblend": "Apple Music with NetEase and Kugou",
                "lrclib": "LRCLIB", "genius": "Genius",
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
        up = "" if src in BLENDS else doc.get("_via")
        was = via.get(str(up).lower(), up) if up else ""
        # Pinned to one upstream, the "via" only repeats the name already
        # printed -- "Apple Music · Apple Music", and a blend's name already
        # spells out everything its makeup would.
        return f"{name} · {was}" if was and was != name else name

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

    def src_on(self, name: str) -> bool:
        """Whether a source is switched on."""
        return bool(getattr(self, SRC_ATTR[name], False))

    def blend_on(self, name: str) -> bool:
        """Whether a blend is switched on. Its donors still have to be too."""
        return bool(getattr(self, BLEND_KEY[name], False))

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
                "album": item.get("album") or "",
                "length": float(item.get("ms") or 0) / 1000.0}))
        self.aligner.keep_only({tid for tid, _m in want})
        if n <= 0:
            return
        for tid, meta in want:
            self.aligner.request(tid, meta)

    def fetch_ahead_scan(self) -> None:
        """Look the next few queued tracks up before they are reached.

        The same list align_ahead_scan works from and the same bet: a track
        thirty seconds away can be fetched now, for nothing, instead of being
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
        self.fetcher.request_ahead(want, self.sources(), self.source_order())

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
        now = time.monotonic()
        self._trouble_said = {k: v for k, v in self._trouble_said.items()
                              if now - v < TROUBLE_QUIET}
        if said in self._trouble_said:
            return
        self._trouble_said[said] = now
        self.toast(f"could not reach {said}")

    def on_aligned(self, tid: str, ok: bool, said: str) -> None:
        if said:
            self.toast(said)
        if ok and tid == self.clock.tid:
            self.reload_lyrics()

    def reload_lyrics(self) -> None:
        self.fetcher.request(self.clock.tid, self.fetch_meta(), self.sources(),
                             self.source_order(), self.ne_graft, self.fold_adlibs)

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

    def line_ink(self, ln: dict):
        """Everything about a line that changes the glyphs, and nothing else.

        Deliberately no times. The cached pixmap is the un-sung text; when it
        is sung is decided every frame by the painter reading the line itself,
        so a line re-timed to the millisecond draws the identical picture.

        Deliberately no line number either -- see line_pixmap.
        """
        if ln.get("dots"):
            return ("dots",)
        if ln.get("credits"):
            return ("credits", tuple(ln["credits"]), bool(ln.get("opposite")))
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
        fm = QFontMetricsF(self.lyric_font(ln["background"]))
        if ln.get("dots"):
            out = ([], fm, fm.height() * 1.35, [], None, [], None)
            self.layout_cache[key] = out
            return out
        if ln.get("credits"):
            cfm = QFontMetricsF(self.credit_font())
            # Each wrapped row remembers WHICH of the credits it came out of.
            # The block is a few separate things -- the songwriters, then where
            # the copy came from, then who timed it -- and only the first of
            # them is the song's own credit and drawn bright. Flattened to
            # plain rows the painter had nothing to go on but the row number,
            # so a list of songwriters long enough to wrap went dim halfway
            # through: the second line of one credit was being drawn as though
            # it were the next credit down.
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
        """Kana readings placed over the kanji they belong to, row by row.

        The wrapper hands back the text fragments it actually laid out, and they
        join back up into the line, so the readings are worked out against those
        rather than against the timed pieces -- no need to track which fragment
        came from which syllable, and a fragment the wrapper had to break mid-word
        still gets the part of the reading that sits over it.
        """
        # Furigana is a Japanese reading, and pykakasi will give one for any
        # Han character put in front of it -- it read 低音吉他, Chinese for
        # "bass guitar", as ていおん・きち and set that over the credits. The
        # kanji are shared; the kana are what say whose song this is.
        if (not self.furigana or not rows or self.roman == "instead"
                or not self.japanese):
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
        if not self.showing():
            # None of the easing below reaches a screen, so only the three
            # things that have to go on running do. The quit path is one of
            # them: a SIGTERM sets quit_requested and nothing else reads it,
            # so skipping it here would leave a minimised window ignoring it.
            # The animation resumes from wherever it left off.
            self.step_drift()
            if self.quit_requested:
                self.quit_requested = False
                self.close()
                QApplication.instance().quit()
                return
            if time.monotonic() > self._save_at:
                self._save_at = time.monotonic() + 2.0
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
        goal = 1.0 if time.monotonic() < self.user_scroll_until else 0.0
        if abs(self.browse - goal) > 0.004:
            self.browse += (goal - self.browse) * 0.18
            moving = True
        else:
            self.browse = goal

        if (live and self.render.scrolls
                and time.monotonic() > self.user_scroll_until):
            focus = SL.focus_index(self.lines, pos, self.scroll_lead)
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
                or (self.clouds > 0 and self.view == "lyrics" and bool(self.lines))
                or (self.view == "lyrics" and self.render.animating()))
        self._idle_frames = 0 if busy else self._idle_frames + 1
        if busy or self._idle_frames % max(1, round(self.eff_hz / 10)) == 0:
            self.update()

    # -- text pixmaps, so distant lines can be blurred cheaply -----------
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

    def line_pixmap(self, idx: int, width: float, blur: int) -> QPixmap:
        # The pen is in the key. It is the one thing here that can change
        # without the cache being cleared: the palette a duet's second voice
        # is tinted from arrives with the album art, a moment after the lines
        # are already on screen and drawn in the placeholder colours.
        pen = self.base_color(self.lines[idx])
        # Keyed by what is DRAWN, not by which line it is. A pixmap here is
        # glyphs and nothing else -- the fill, the rise and the glow are all
        # painted live over the top -- so two lines that read the same are
        # the same picture, and, far more usefully, a line is still the same
        # picture after a better source arrives.
        #
        # That is the whole point. A better answer mid-song is normally the
        # same WORDS with a better clock under them, and keying on the line
        # number threw away every drawn line in the column for that: the
        # refresh cost 26ms on the frame it landed and 48ms over the six
        # after it, measured here, which is the stall that showed up as "it
        # lags when it finds a better source". Keyed on the ink, a document
        # that only re-times the song rebuilds nothing at all.
        # The font is in the key by name rather than by "the family changed,
        # so empty the cache": it is the last thing about a drawn line that
        # was not, and putting it in is what lets the invalidations below go
        # away entirely.
        key = (self.line_ink(self.lines[idx]), int(width), blur,
               int(self.lyric_px()), self.align, self.roman, pen.rgb(),
               self.lyric_font(False).toString())
        hit = self.pix_cache.get(key)
        if hit is not None:
            self.pix_cache.move_to_end(key)
            return hit
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
        self.pix_cache[key] = pm
        self._pix_bytes += _pm_bytes(pm)
        while self._pix_bytes > PIX_BUDGET and len(self.pix_cache) > 1:
            _old, gone = self.pix_cache.popitem(last=False)
            self._pix_bytes -= _pm_bytes(gone)
        return pm

    def glow_pixmap(self, txt: str, font: QFont, radius: int) -> QPixmap:
        """Soft halo for the syllable being sung right now."""
        # The whole font, not just its size: the family and the weight change
        # the shape being blurred, and a key that forgets them hands back the
        # last font's glow. See drop_pixmaps, which is allowed to leave these
        # alone precisely because the key is complete.
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
        now = time.monotonic()
        t = now * 0.06 * self.bg_motion
        key = (W, H, tuple(c.rgb() for c in self.palette), self.art_gen,
               self.bg_mode, round(self.bg_dim, 2), round(self.bg_motion, 2),
               self._section, self.viz_live(), self.viz_mode)
        fresh = 1 / 15 if self.bg_motion else 1.0
        if self._scene_pm is not None and key == self._scene_key and now - self._scene_at < fresh:
            return self._scene_pm
        pm = QPixmap(W, H)
        p = QPainter(pm)
        p.fillRect(0, 0, W, H, QColor(9, 9, 12))
        if self.bg_mode == "mesh" and not (self.viz_live() and self.viz_mode == "bloom"):
            # The live mesh IS this, driven -- painting both would double every
            # blob and leave the still copy showing through the moving one.
            # Only bloom, though: the other modes leave most of the window
            # theirs to fill, and dropping it under those empties the wall.
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

    # -- visualizer ------------------------------------------------------
    VIZ_DIV = 3          # paint at a third size, then blow it back up
    # Per mode, because the divisor is only free where the shape has no detail
    # in it. Blobs and water are gradients a few cycles across the window and
    # lose nothing; a column with an edge on it would come back as a smear.
    VIZ_DIVS = {"bloom": 3, "tide": 3, "pulse": 2, "bars": 1}
    VIZ_ALPHA = 124      # per blob at full strength, before the track scales it
    VIZ_SAT = 0.52       # saturation floor for the blobs; 0 keeps the palette
    # What each mode cannot draw a frame without. Chroma is the part of an
    # analysis most often missing, and the part worth least on a track built
    # out of drums -- a mode reading only the grid still has all it needs there.
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
        """The palette colour, lifted off grey.

        A monochrome cover gives a monochrome palette, and blobs painted in it
        read as a smudge on the wall rather than as anything answering the
        music -- which is most of what "the visualizer is hard to see" turns
        out to mean in practice. Only colours already under the floor move, so
        a cover with real colour in it still shows its own and nothing else.

        A true grey reports no hue at all, so there is nothing to lift and one
        has to be chosen. Spreading them around the wheel by position is the
        only choice that keeps the blobs telling apart from each other, which
        is the whole reason there is more than one of them.
        """
        if not self.VIZ_SAT:
            return c
        h, sat, v, a = c.getHsvF()
        if sat >= self.VIZ_SAT and v >= 0.45:
            return c
        if h < 0:
            h = (0.58 + i / max(1, n)) % 1.0
        return QColor.fromHsvF(h, max(sat, self.VIZ_SAT), max(v, 0.58), a)

    def viz_tints(self) -> list[QColor]:
        """The palette every mode paints in, each colour lifted off grey."""
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
        now = time.monotonic()
        key = (W, H, self.viz, self.viz_mode, self._section)
        if (self.clock.status != "Playing" and self._viz_pm is not None
                and self._viz_key == key):
            return self._viz_pm
        dt = min(0.25, now - self._viz_at) if self._viz_at else 1 / 60.0
        self._viz_at = now
        # Eased every frame whoever is painting, so switching mode mid-song
        # arrives at chroma already settled rather than climbing from nothing.
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
        # These are added, not laid over, so the blobs share one budget: four
        # of them at a weight that suits one puts a wall of light on the
        # window wherever two overlap, and the album art under it is gone.
        share = 2.5 / max(2.5, n)
        lifts = []
        for i in range(n):
            lo, hi = i * 12 // n, (i + 1) * 12 // n
            lifts.append(sum(bands[lo:hi]) / max(1, hi - lo))
        # Distortion smears chroma across every class at once, so on a loud
        # guitar all four slices read alike and the blobs move as one lump.
        # Pulling them apart by their own spread keeps them telling apart
        # there; material with real harmonic contrast is already spread and
        # comes back barely touched. Only where the vector is pitched at all,
        # though: on drums this is a noise amplifier, and the gate in
        # viz_bands is undone by exactly the step that follows it.
        reach = max(lifts) - min(lifts)
        if reach > 0.02 and self._viz_tone > 0.35:
            base = min(lifts)
            lifts = [0.5 * v + 0.5 * (0.10 + 0.90 * (v - base) / reach)
                     for v in lifts]
        for i in range(n):
            c = tint[(i + self._section) % n]
            ph = i * 2.399
            lift = lifts[i]
            # Staggered so the kick travels across the blobs rather than
            # flashing the whole window at once.
            # Staggered off the eased envelope, so the beat still travels
            # across the blobs but arrives at each of them as a rise.
            kick = self.viz_kick() * (1.0 - 0.18 * i)
            cx = w * (0.5 + 0.40 * math.sin(t * 1.9 + ph))
            cy = h * (0.5 + 0.40 * math.cos(t * 1.4 + ph * 1.7))
            rad = span * (0.46 + 0.15 * math.sin(t * 1.1 + ph)) * (
                0.80 + 0.26 * lift + 0.10 * kick)
            # Swing kept narrow on purpose. The eye reads a change in light
            # far more readily than a change in size, so the loudness is spent
            # mostly on the radius and only a little on the alpha -- a blob
            # that halves in brightness twice a bar is a flash, not a pulse.
            a = self._viz_a(share * (0.55 + 0.30 * loud) * (0.70 + 0.30 * lift))
            g = QRadialGradient(cx, cy, max(1.0, rad))
            g.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), a))
            g.setColorAt(0.55, QColor(c.red(), c.green(), c.blue(), a // 3))
            g.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            p.fillRect(0, 0, w, h, QBrush(g))

    VIZ_RING = 1.35      # seconds a ring takes to cross the window and go out

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
            # A ring is a thin band where a blob is half the window, so it
            # needs the weight a blob does not: the same alpha spread over
            # a twentieth of the area reads as nothing at all.
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
        # A core under the rings, so a bar's rest still has something standing
        # in the middle rather than an empty window between beats.
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
            # Squared, because the twelve arrive normalised to their own
            # peak and sit high: read straight, a triad differs from the nine
            # classes it is not by a few pixels of column.
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
            dst = QRectF(W * (1 - g) / 2, H * (1 - g) / 2, W * g, H * g)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            p.drawPixmap(dst, self.scene_layer(), QRectF(0, 0, W, H))
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        else:
            dst = QRectF(0, 0, W, H)
            p.drawPixmap(0, 0, self.scene_layer())
        if self.viz_live():
            # Rides the beat zoom with the scene under it: they are one wall.
            vp = self.viz_layer(W, H)
            p.drawPixmap(dst, vp, QRectF(vp.rect()))

        x0, width = self._lyr_x(), self._lyr_width()
        if self.lines:
            self.render.paint(p, x0, width, H)
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

    def _paint_panel(self, p, panel: float, H: int) -> None:
        # Every x below is measured from the panel's own left edge, which is
        # the window's unless the art has been sent to the other side.
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
            return          # answered a query the user has already typed past
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
        # Kept up while the query is still being extended, so refining a line
        # does not blink the Genius rows out and back on every letter; a
        # backspace or a different query drops them, since those are no longer
        # answers to what the box says.
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
            # Where Genius matched a LINE, the row reads like every other one:
            # the line above, the song under it. Where it matched the name,
            # the name is already the line above -- so the row under it is the
            # artist alone, rather than the same words a second time.
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
            # Genius named a song; Spotify has to be asked which recording
            # that is, and only for the one actually picked -- matching all
            # eight would be eight catalogue searches per keystroke's worth
            # of results, for seven nobody asked about.
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
            self.skip_at = time.monotonic()
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
        self.skip_at = time.monotonic()
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

    # -- song info + share ----------------------------------------------
    def info_rows(self) -> list[tuple[str, str]]:
        m, doc = self.clock.meta, SL.payload(self.body or {})
        syl = sum(len(l.get("syls") or []) for l in self.lines)
        tid = self.clock.tid or ""
        rows = [("Title", m.get("title", "—")), ("Artist", self.artist() or "—"),
                ("Album", m.get("album", "—"))]
        if doc:
            rows += [
                # LS.quality, not the Type the document claims. NetEase, QQ
                # Music and Kugou all stamp "Syllable" on whatever they hand
                # over, and the line under the lyrics has always read the
                # data instead -- so the two panels disagreed, and this was
                # the one that could be talked into "word-synced" by a
                # document with no word timing in it.
                ("Lyrics", {"syllable": "word-synced", "line": "line-synced",
                            "static": "unsynced"}.get(LS.quality(doc), "—")),
                ("Language", self._said_language(doc)),
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
        if tid in self.offsets:
            rows.append(("Track offset", f"{self.offsets[tid]:+.2f}s by hand"))
        hold = self.clock.resume_hold
        rows.append((
            "Resume hold",
            (f"{hold:.3f}s carried" if hold else "none")
            + f"  (ceiling {self.clock.unpause_delay:.2f}s)"))
        bias, cal_n = self.calibration()
        if self.est:
            short = CAL_MIN - cal_n
            # A reading old enough to predate the agreement check has not
            # passed it, and says so rather than raising on a missing key.
            spread = float(self.est.get("spread", EST_RANGE * 2.0))
            if not self.auto_time:
                why = "  (auto timing off)"
            elif tid in self.offsets:
                why = "  (hand correction wins)"
            elif self.est["conf"] < EST_CONF_MIN:
                why = f"  (conf {self.est['conf']:.2f}, too close to call)"
            elif spread > EST_AGREE:
                why = f"  (halves disagree by {spread:.2f}s, not trusted)"
            elif short > 0:
                why = (f"  (tune {short} more track{'' if short == 1 else 's'} "
                       f"by ear to calibrate)")
            elif abs(self.est["delta"] - bias) > EST_MAX:
                why = f"  (past {EST_MAX:.2f}s, too big to trust)"
            else:
                why = ""
            rows.append(("Measured",
                         f"{self.est['delta'] - bias:+.2f}s from "
                         f"{self.est['n']} entries{why}"))
        elif self.beat.segs and self.raw:
            rows.append(("Measured", "not enough clean vocal entries"))
        if cal_n:
            rows.append(("Calibration", f"{bias:+.3f}s over {cal_n} hand-tuned"))
        # Which output the global offset above belongs to. Worth saying: the
        # number changes on its own when the sound moves to another device,
        # and a number that changes on its own is worth being able to see the
        # reason for.
        if self.device:
            rows.append(("Output", f"{self.device_name}  "
                                   f"({self.offset:+.2f}s global)"))
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
        where, asked = save_dir(self.args.save_dir)
        path = where / f"{name or 'lyric'} card.png"
        try:
            # QPixmap.save answers False rather than raising, so a card that
            # never reached the disk was announced as copied.
            wrote = pm.save(str(path))
            QApplication.clipboard().setPixmap(pm)
            if not wrote:
                self.toast(f"card copied · could not write {path}")
            else:
                self.toast(f"card copied · {path.name if asked else path}")
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
            self.drop_pixmaps()
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
            # Silently doing nothing here reads as a broken key. The blends
            # are ordered by where their donors sit in Sources, on purpose --
            # say which list to go and move.
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
        # The SOURCES that were just reordered, not the providers they expand
        # to. source_order() returns the expansion -- "bini", "triblend" -- and
        # SRC_LABEL is keyed by source, so reading it through this raised
        # KeyError on every reorder.
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
            # Nothing to fire. source_order() reads the attribute on its next
            # call, and the chain's stored answer is keyed by the list of
            # providers it asked, so a changed list re-walks on its own.
            setattr(self, BLEND_KEY[blend], value)
            return
        if key == "sung_mode":
            self._sung = TEXT if value == SUNG_MODES[0] else None
            return
        setattr(self, key, value)
        if key == "renderer":
            self.render = RD.RENDERERS[value](self)
            # The pinned renderers set type at their own sizes, and none of
            # them wants the column where the last one left it.
            self.layout_cache.clear()
            self.drop_pixmaps()
            self.scroll = self.scroll_target = 0.0
            self.content_h = 0.0
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
                   "furigana", "view_mode", "art_side"):
            self.layout_cache.clear()
            self.drop_pixmaps()
        elif key == "blur_scale":
            self.drop_pixmaps()
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
            blend = self.blend_slot(key)
            if blend is not None and v:
                # Switched on and still never asked. Every source it draws on
                # has to be on too -- and Apple Music above all, since with
                # that off the whole blend run is skipped -- which is not
                # visible from this section otherwise.
                off = [u for u in BLENDS[blend] if not self.src_on(u)]
                if off:
                    return f"needs {SRC_LABEL[off[0]]}"
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

        # A section whose rows cannot say what they are on their own gets a
        # line under the tabs. It is drawn in the slack a short section leaves
        # under its last row -- the box is sized to the TALLEST section -- so
        # a section already at full height silently gets none rather than
        # overflowing the panel.
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

    # -- helpers ---------------------------------------------------------
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
        where, asked = save_dir(self.args.save_dir)
        path = where / f"{name}.ttml"
        try:
            path.write_text(SL.render(self.body, "ttml") + "\n", encoding="utf-8")
            # The whole path where it is not the one they asked for. "saved
            # song.ttml" is all anybody needs when they said where it goes;
            # when this program picked, it owes them the place.
            self.toast(f"saved {path.name}" if asked else f"saved {path}")
        except Exception as exc:
            self.toast(f"save failed: {exc}")

    def bump_font(self, delta: float) -> None:
        self.font_scale = max(0.6, min(1.9, self.font_scale + delta))
        self.layout_cache.clear()
        self.drop_pixmaps()
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
        # How many of these the budget can hold at that size, and hence how
        # many to skip. Thinning rather than shrinking -- see MOTION_BUDGET.
        fits = max(1, MOTION_BUDGET // max(1, cap * cap * 4))
        step = max(1, -(-len(frames) // fits))
        out = []
        for img in frames[::step]:
            if img.width() > cap:
                img = img.scaledToWidth(cap, Qt.TransformationMode.SmoothTransformation)
            out.append(QPixmap.fromImage(img))
        self.motion_frames = out
        self.motion_fps = MOTION_FPS / step
        self.motion_at = time.monotonic()
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
        i = int((time.monotonic() - self.motion_at)
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
        if not uri and payload.get("genius"):
            # Genius named a song, not a recording; ask Spotify which one it
            # is, and only for the row actually picked. See on_gmatch.
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
        # Genius once the typing stops, same as the overlay; see ask_genius.
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
        # The catalogue's own order is Spotify's ranking and is left alone;
        # what is sorted here is the tail this window adds to it.
        for g in self.genius_rows(self.bq.strip(), known):
            hits.append({"section": "On Genius", "uri": "", "id": "",
                         "name": g.get("title") or "",
                         "sub": (g.get("artist") or "")
                                + (f" · \u201c{g['line'][:60]}\u201d"
                                   if g.get("line") else ""),
                         # Through art_url like every other cover, which is
                         # also what keeps anything but http out of the
                         # fetcher's hands.
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
        self.queue_at = time.monotonic()
        self.align_ahead_scan()
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
            for i, r in self.help_tab_rects:
                if r.contains(pos):
                    self.help_tab = i
                    self.update()
                    return
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
        if self.on_panel(ev.position().x()):
            self.toggle_fullscreen()

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
        if self.show_help and k in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
                                    Qt.Key.Key_Left, Qt.Key.Key_Right):
            # Only while the panel is up, and only these four: everything else
            # still reaches the player, so the song can be driven with the keys
            # in front of you, which is most of what having them up is for.
            self.help_tab_step(
                -1 if k in (Qt.Key.Key_Backtab, Qt.Key.Key_Left) else +1)
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
                self.leave_fullscreen()
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
        elif k == Qt.Key.Key_V and shift:
            i = VIZ_MODES.index(self.viz_mode) if self.viz_mode in VIZ_MODES else 0
            self.viz_mode = VIZ_MODES[(i + 1) % len(VIZ_MODES)]
            self._scene_key = self._viz_key = None
            # Cycling to a mode while it is switched off would report a change
            # nothing on the window shows, so asking for a mode turns it on.
            if not self.viz:
                self.viz = self._viz_last or self.args.viz or 1.0
            self.toast(f"visualizer: {self.viz_mode}")
        elif k == Qt.Key.Key_V:
            # Remembered rather than taken from the flag, because the flag
            # defaults to 0 -- reading it back would silently reset a strength
            # set in the menu to 1.0 every time this was switched off and on.
            if self.viz:
                self._viz_last, self.viz = self.viz, 0.0
            else:
                self.viz = self._viz_last or self.args.viz or 1.0
            self._scene_key = None
            need = self.VIZ_NEEDS.get(self.viz_mode, "pitch")
            if self.viz and not getattr(self.beat, need):
                # Say so rather than leave them staring at an unchanged
                # background wondering whether the key did anything.
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
        elif k == Qt.Key.Key_A and shift:
            self.align_now()
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
                gone = False
                if self.clock.tid:
                    LS.forget(self.clock.tid)
                    gone = LS.forget_aligned(self.clock.tid)
                # Who was drawing, before reset_track forgets. A live document
                # is not something R takes away: the editor pushing it is
                # still open and still ticked, and it puts it back within the
                # second -- so say what this actually did, which is to go and
                # fetch the song's own copy underneath it.
                whose = (self.dropped_from or "the editor"
                         if self.dropped is not None
                         and self.dropped == self.clock.tid else "")
                self.reset_track("Reloading…", keep=True)
                self.toast(f"reloading this song's own lyrics — {whose} "
                           f"draws over it again" if whose else
                           "dropped file forgotten, reloading lyrics"
                           if gone else "reloading lyrics")
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
            # on_top is set below, and enter_fullscreen reads it to carry the
            # hint over the window it re-creates; tell it now.
            self.on_top = on
            self.enter_fullscreen() if full else self.show()
            ok = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == on
        self.on_top = on if ok else False
        if ok:
            self.toast(f"always on top {'on' if on else 'off'}")
        else:
            self.toast("always on top unsupported by this compositor")

    def resizeEvent(self, _ev) -> None:
        # Not drop_pixmaps: the width a line was drawn at is in its key, so
        # the old ones are simply not asked for again, and a drag across the
        # desktop delivers a resize a frame -- each of which would otherwise
        # have thrown away the column and rebuilt it before the next one
        # arrived.
        self.layout_cache.clear()

    def settings_dict(self) -> dict:
        return {
                "offset": round(self.offset, 3),
                "offsets_device": self.device_offsets(),
                "font_scale": round(self.font_scale, 2),
                "blur": self.blur_scale,
                "glow": self.glow_scale,
                "panel": self.show_panel,
                "art_side": self.art_side,
                "view_mode": self.view_mode,
                "volume_bar": bool(self.show_volume),
                "duet_color": self.duet_color,
                "font": self.font_name,
                "src_order": ",".join(self.src_order),
                "motion_art": bool(self.motion_art),
                "bg": self.bg_mode,
                "viz": round(self.viz, 2),
                "viz_mode": self.viz_mode,
                "bg_dim": round(self.bg_dim, 2),
                "bg_motion": round(self.bg_motion, 2),
                "align": self.align,
                "pop": self.pop,
                "rise": round(self.rise, 2),
                "renderer": self.renderer,
                "edge": self.edge,
                "focus": self.focus,
                "line_spacing": round(self.line_spacing, 2),
                "sung_color": ("auto" if self._sung is None else
                               "white" if self._sung == QColor("white")
                               else self._sung.name()),
                "interlude": round(self.interlude, 2),
                "scroll_lead": round(self.scroll_lead, 2),
                "resync": bool(self.resync),
                "auto_time": bool(self.auto_time),
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
                "align_on": bool(self.align_on),
                "align_model": str(self.align_model),
                "align_stems": bool(self.align_stems),
                "align_device": self.align_device,
                "align_spare": round(self.align_spare, 2),
                "align_free": bool(self.align_free),
                "align_ahead": int(self.align_ahead),
                "fetch_ahead": int(self.fetch_ahead),
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
        # Before anything else: a muted player is this window's doing and
        # must not outlive it.
        self.unfollow_editor(pause=False)
        self.frame_timer.stop()
        self.poll_timer.stop()
        # Before the signals are pulled: the sampler emits on every reading,
        # and one landing in a half-dismantled window is a slot running
        # against objects that have gone.
        self.pump.stop()
        self.fetcher.stop = True
        self.art_cache.stop = True
        self.motion.stop = True
        self.aligner.stop = True
        for sig in (self.aligner.finished_track, self.aligner.progress,
                    self.fetcher.ready, self.fetcher.beat_ready,
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
    ap.add_argument("--scroll-lead", type=float, metavar="SECS",
                    help="begin scrolling to the next line this long before it "
                         "starts, once the line before it has finished; "
                         "0 waits for the line itself (default 0.35)")

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
    fx.add_argument("--renderer", choices=RENDER_MODES,
                    help="how the lyric column is drawn. flow: the scrolling "
                         "stack, every line one size, the one being sung "
                         "filling syllable by syllable (default). snap: the "
                         "same, but each word takes the sung colour whole "
                         "instead of filling. spotlight: the line being sung "
                         "alone, large and centred, with the next one under it. "
                         "karaoke: two lines pinned at the foot of the window, "
                         "alternating. word: one word at a time, very large. "
                         "cards: a card per line, sliding up as it arrives")
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
    src.add_argument("--fetch-ahead", type=int, default=None, metavar="N",
                     help="look the lyrics up for this many queued tracks "
                          "before they are reached, up to 7, 0 to do none "
                          "(default %d)" % DEFAULTS["fetch_ahead"])
    src.add_argument("--src-spicy", action=argparse.BooleanOptionalAction, default=None,
                     help="the Spicy Lyrics community's own documents, read out "
                          "of Spotify. Always tried first; --no-src-spicy to see "
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
    src.add_argument("--src-lyricsplus", action=argparse.BooleanOptionalAction,
                     default=None,
                     help="LyricsPlus' own submissions: word-timed TTML its "
                          "readers hand-timed and uploaded, credited to the "
                          "curator who did it. The one catalogue behind that "
                          "door that is not somebody else's (default on)")
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
    src.add_argument("--src-local", action=argparse.BooleanOptionalAction,
                     default=None,
                     help="alignments this machine made against the audio itself. "
                          "Last of the timed sources by default, so it only "
                          "speaks for songs nothing else has word timing for")
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
                    help="QQ Music's word timings under Apple's lines, which "
                         "is the pairing LyricsPlus itself makes (default on)")
    bl.add_argument("--blend-kugou", action=argparse.BooleanOptionalAction,
                    default=None,
                    help="Kugou's underneath instead, which reach songs QQ's "
                         "do not (default on)")
    ap.add_argument("--fold-adlibs", action=argparse.BooleanOptionalAction, default=None,
                    help="draw a shouted line filed as its own line -- \"Yeah\", "
                         "\"Oh, God\" -- as an ad-lib on the line before it, and "
                         "lift a bracketed backing vocal out of the lyric. Only "
                         "on documents NetEase, QQ Music or Kugou had a hand in, "
                         "the three that cannot mark a second voice any other "
                         "way (default on)")
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
                         "Spotify (default %.2fs); 0 disables it"
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
        # Not every setting is a flag. `align_ckpt` names a checkpoint to obey
        # for good, which is a decision that outlives one launch -- it is read
        # from the settings file at the point of use and has no business on
        # argv, so there is no attribute here to fill in. Filling in only what
        # the parser actually declared lets a settings-only key exist without
        # taking the whole window down on the way up.
        if not hasattr(args, attr):
            continue
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

    if args.fixture:
        def _fixture():
            # After the first poll, not before it: poll() reconciles the
            # window with whatever the player last said, and a document put on
            # screen ahead of that is the first thing it clears away.
            w.pump.stop()
            w.pump.wait(2000)
            body = LS.parse_ttml(
                pathlib.Path(args.fixture).read_text(encoding="utf-8"))
            w.clock.tid = w._seen_tid = "fixture"
            # poll() calls reset_track on a track it has not seen before, and
            # the document below would be the first thing that cleared.
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
