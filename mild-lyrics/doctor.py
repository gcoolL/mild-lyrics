#!/usr/bin/env python3
"""Check this machine can run the lyrics app, and say what to do where it cannot.

Run it with no arguments to check the setup and put a launcher on the desktop:

    python doctor.py

Pass --no-shortcut to only check:

    python doctor.py --no-shortcut

Every check answers one question and, when the answer is no, prints the thing to
do about it. Making the launcher is the only thing here that changes anything,
and it overwrites its own file rather than piling up copies.

There is one other job in here, and it checks a source rather than a machine:

    python doctor.py --source qq
    python doctor.py --source netease --song Rise --artist Skillet --length 261

That asks one lyric source for one song and prints how far it got. "The
lyrics do not appear" is not a report anybody can act on -- the walk is ten
providers wide, runs on a worker thread and swallows every failure by design,
so a source that is reachable, finds the song and then hands back nothing
looks from the window exactly like one that is blocked.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(p) for p in (ROOT, HERE) if str(p) not in sys.path]

import noconsole  # noqa: E402

WIN = os.name == "nt"
MAC = sys.platform == "darwin"
PORT = 9222

OK, WARN, BAD = "  OK  ", " ---- ", " !!!! "
_fails: list[str] = []


def say(state: str, what: str, detail: str = "", fix: str = "") -> None:
    print(f"[{state}] {what}" + (f"  {detail}" if detail else ""))
    if fix:
        for line in fix.strip().splitlines():
            print(f"         {line}")
    if state is BAD:
        _fails.append(what)


def check_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        say(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    else:
        say(BAD, "Python", f"{v.major}.{v.minor}", "This needs 3.10 or newer.")


def check_qt() -> None:
    try:
        from PyQt6.QtCore import QT_VERSION_STR
        import PyQt6.QtGui as G
    except ImportError:
        say(BAD, "PyQt6", "not installed", "pip install PyQt6")
        return
    say(OK, "PyQt6", f"Qt {QT_VERSION_STR}")
    if hasattr(G.QFont, "setVariableAxis"):
        say(OK, "Font weights", "variable axis supported")
    else:
        say(WARN, "Font weights", f"Qt {QT_VERSION_STR} has no variable axis",
            "Custom font weights will be approximate. Qt 6.7+ fixes it:\n"
            "    pip install --upgrade PyQt6")


def check_files() -> None:
    missing = [n for n in ("lyrics_gui.py", "lyric_sources.py", "spicy_lyrics.py",
                           "genius_roman.py", "spotify_dom.py", "caches.py",
                           "macplayer.py")
               if not (HERE / n).exists() and not (HERE.parent / n).exists()]
    if missing:
        say(BAD, "Program files", f"missing {', '.join(missing)}",
            f"Copy them next to {HERE / 'lyrics_gui.py'}")
    else:
        say(OK, "Program files", "all present")
    editor = HERE.parent / "editor"
    gone = [n for n in ("app.py", "model.py", "ops.py", "player.py")
            if not (editor / n).exists()]
    if not editor.is_dir():
        say(WARN, "TTML synchroniser", "not in this copy",
            "Only the player is here. The editor is the editor/ folder next\n"
            "to this one.")
    elif gone:
        say(BAD, "TTML synchroniser", f"missing {', '.join(gone)}",
            f"The editor is incomplete. Expected them in {editor}")
    else:
        say(OK, "TTML synchroniser", "all present")


def check_spotify() -> None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=4) as r:
            targets = json.load(r)
        pages = [t for t in targets if t.get("type") == "page"]
        say(OK, "Spotify debug port", f"{len(pages)} page target(s) on {PORT}")
        return
    except Exception as e:
        pass
    fix = (
        "Spotify is not listening. It has to be started BY Spicetify for the\n"
        "launch flag to apply -- starting it from the taskbar or Start menu\n"
        "does not. The durable fix is to point your Spotify shortcut at:\n"
        "    spicetify auto\n"
        "Then set the flag once (edit the file if the CLI mangles it -- run\n"
        "`spicetify -c` to find it):\n"
        "    spotify_launch_flags   = --remote-debugging-port=9222"
    ) if WIN else (
        "Spotify is not listening. Restart it with the debug port:\n"
        "    osascript -e 'quit app \"Spotify\"'\n"
        f"    open -a Spotify --args --remote-debugging-port={PORT}\n"
        "Nothing here needs it, though: a Mac reads the player through its\n"
        "own now-playing instead. Nothing fetches lyrics through it any\n"
        "more -- Spicy Lyrics has its own API; see spicy_lyrics.py."
    ) if MAC else (
        "Spotify is not listening. Restart it with the debug port:\n"
        "    pkill -x spotify\n"
        f"    spotify --remote-debugging-port={PORT} >/dev/null 2>&1 &"
    )
    say(WARN if MAC else BAD, "Spotify debug port",
        f"nothing on 127.0.0.1:{PORT}", fix)


def check_spicy_key() -> None:
    """Whether there is a key to ask Spicy Lyrics with, and where it came from.

    The one thing that can switch off the source this program was built
    around, and it fails quietly: without a key the walk simply goes on to the
    next provider, so the lyrics are somebody else's and nothing says why.
    """
    try:
        sys.path.insert(0, str(HERE))
        import lyric_sources as LS
    except Exception:                                    # noqa: BLE001
        return
    got = LS.spicy_key()
    if not got:
        say(WARN, "Spicy Lyrics key", "none",
            "One ships with the program, so this means it has been emptied or\n"
            "overridden with a blank. Without a key Spicy Lyrics' own syncs --\n"
            "the community's hand-timed ones -- are skipped and another source\n"
            "answers instead. Put one back with:\n"
            f"    {sys.executable} {HERE / 'spicy_lyrics.py'} key sl_sk_...\n"
            "A publishable key for a desktop program has to be issued with\n"
            "the 'no Origin header' allowance: nothing here is a browser.")
        return
    where = next((n for n in LS.SPICY_KEY_ENV
                  if (os.environ.get(n) or "").strip()), "")
    where = f"${where}" if where else (
        str(LS.SPICY_KEY_FILE) if LS.SPICY_KEY_FILE.exists() else "built in")
    kind = ("publishable" if got.startswith("sl_pk_") else
            "secret" if got.startswith("sl_sk_") else "unrecognised")
    # A secret key of YOUR OWN, kept in the settings directory or the
    # environment, is the documented way to spend your own budget. A secret
    # key in the SOURCE is a different thing entirely: everything that ships
    # is public the moment the repository is, so this is the one arrangement
    # worth stopping on rather than reporting.
    if kind == "secret" and where == "built in":
        say(BAD, "Spicy Lyrics key", "a SECRET key is built into the source",
            "sl_sk_ is the whole application's budget, and it is readable by\n"
            "anyone who can read this program. Take it out of\n"
            "SPICY_SHIPPED_KEY, put a publishable sl_pk_ one there instead,\n"
            "and keep the secret one where it is not shipped:\n"
            f"    {sys.executable} {HERE / 'spicy_lyrics.py'} key sl_sk_...")
        return
    say(OK if kind != "unrecognised" else WARN, "Spicy Lyrics key",
        f"{kind}, from {where}",
        "" if kind != "unrecognised" else
        "A key is sl_pk_... or sl_sk_.... This one is neither, and the\n"
        "service will refuse it.")


def check_spicetify() -> None:
    exe = shutil.which("spicetify")
    if not exe:
        say(WARN, "Spicetify", "not on PATH",
            "Not needed for the lyrics themselves -- every source, Spicy\n"
            "Lyrics included, is fetched over the network. The debug port it\n"
            "sets up is what the window reads the player through on Windows,\n"
            "and what the search, the queue and the visualizer are asked of.")
        return
    try:
        got = noconsole.run([exe, "config", "spotify_launch_flags"],
                            capture_output=True, text=True, timeout=20)
        flags = (got.stdout or "").strip()
    except Exception:
        flags = ""
    if "remote-debugging-port" in flags:
        say(OK, "Spicetify launch flags", flags)
    else:
        say(WARN, "Spicetify launch flags", flags or "(empty)",
            "setup.sh sets this for you, keeping whatever else is in there:\n"
            f"    {sys.executable} {ROOT / 'mild-setup.py'}")


def log_dir() -> pathlib.Path:
    """The cache directory the window writes its log into.

    Worked out here rather than asked of lyrics_gui, which would mean
    importing the window -- and Qt with it -- to print a path. The two must
    agree; see lyrics_gui.app_dir, which this is the Windows half of.
    """
    root = os.environ.get("LOCALAPPDATA")
    base = pathlib.Path(root) if root else pathlib.Path.home() / "AppData" / "Local"
    return base / "mild-lyrics"


def check_player() -> None:
    """Whether this machine has a way of being asked what is playing.

    One question, three services. Each is the platform's own -- the session
    bus, the Windows media transport, whatever a Mac will still answer -- and
    each is what the any-media-player setting reads, so a machine where this
    is missing is a machine where the window can only follow Spotify over the
    debug port.
    """
    if WIN:
        old = old_winrt()
        if old:
            say(BAD, "Windows media transport", f"the wrong winrt ({old})",
                WINRT_WRONG)
            return
        pkg, missing = winrt_whole()
        if not pkg and missing:
            say(BAD, "Windows media transport",
                f"winrt is installed and incomplete ({missing[0]} missing)",
                WINRT_HALF)
            return
        if not pkg:
            say(WARN, "Windows media transport", "no Windows bindings installed",
                WINRT_FIX)
            return
        say(OK, "Windows media transport", f"available ({pkg})")
        check_windows_output(pkg)
        check_windows_players()
        return
    if MAC:
        check_mac_player()
        return
    try:
        import dbus
        dbus.SessionBus().get_object("org.mpris.MediaPlayer2.spotify",
                                     "/org/mpris/MediaPlayer2")
        say(OK, "MPRIS", "Spotify is on the session bus")
    except Exception:
        say(WARN, "MPRIS", "Spotify not on the session bus",
            "The app will drive the clock over the debug port instead.")
    check_other_players()


# THE BRACKETS ARE NOT OPTIONAL. winrt ships one distribution per namespace,
# and `pip install winrt-Windows.Media.Control` brings only winrt-runtime
# with it: everything that namespace itself imports -- Windows.Foundation,
# where the async operation lives, Windows.Foundation.Collections, where the
# session list lives, Windows.Media, Windows.Storage.Streams -- is declared
# under the `[all]` extra and arrives only if it is asked for. Without them
# the control module still imports, which is what made this so hard to see:
# every probe passed and the first real call died on a namespace nobody had
# named. Quoted because PowerShell reads a bare [all] as an array.
WINRT_NEEDS = ('"winrt-Windows.Media.Control[all]"',
               '"winrt-Windows.Media.Devices[all]"',
               '"winrt-Windows.Devices.Enumeration[all]"')
# Kept in step with WINRT_NEEDS in lyrics_gui.py, which is the same list from
# the other side: the namespaces, rather than the distributions that carry
# them. Deliberately not imported from there -- that module pulls in PyQt6,
# and this one has to be able to report that PyQt6 is what is broken.
WINRT_NAMESPACES = ("windows.media.control", "windows.foundation",
                    "windows.foundation.collections", "windows.storage.streams")
_WINRT_WHY = (
    "Optional, and it is what reads the browsers -- it is also what names\n"
    "the output device. Without it the window can only follow Spotify, over\n"
    "the debug port, and the song panel has no Output or Player row.\n")
_WINRT_LINE = "    pip install " + " \\\n                ".join(WINRT_NEEDS)
WINRT_FIX = (
    _WINRT_WHY +
    "\n"
    "There are two packages with one API. winsdk is the older one and its\n"
    "last wheel is for CPython 3.12, so on 3.13 and newer pip has nothing to\n"
    "install and falls back to building it, which needs a C++ toolchain and\n"
    "usually just fails. winrt is the maintained one and has wheels through\n"
    f"3.14. This is Python {sys.version.split()[0]}, so:\n"
    + _WINRT_LINE + "\n"
    "\n"
    "The [all] is load-bearing -- without it pip installs the one namespace\n"
    "and none of the ones it imports.")
WINRT_HALF = (
    "The namespaces are separate packages and the ones this one imports are\n"
    "behind an extra, so installing it by its bare name gets you a set that\n"
    "imports and cannot be called. That is where\n"
    "\"No module named 'winrt.windows.foundation'\" comes from.\n"
    "\n"
    "Asking again WITH the brackets fills in the rest:\n"
    + _WINRT_LINE)
WINRT_WRONG = (
    "That is a different, abandoned project that happens to own the name\n"
    "`winrt` on PyPI -- its last release was in 2021 and its newest wheel is\n"
    "for CPython 3.9. It installs itself as the `winrt` package, which is the\n"
    "same name the real projection puts its namespaces under, so while it is\n"
    "there nothing can import winrt.windows.anything.\n"
    "\n"
    "`pip install winrt` is the natural thing to type and it is the wrong\n"
    "package. On 3.10 and newer it usually cannot even install -- there is no\n"
    "wheel, so pip tries to build it and wants a C++ toolchain.\n"
    "\n"
    "    pip uninstall winrt\n"
    + _WINRT_LINE)


def old_winrt() -> str:
    """The abandoned `winrt` distribution's version, or "" if it is not here.

    The real projection is `winrt-runtime` plus a `winrt-Windows.*` per
    namespace; a distribution named exactly `winrt` can only be the 2021 one.
    """
    try:
        import importlib.metadata as md
        return md.version("winrt") or "installed"
    except Exception:                                    # noqa: BLE001
        return ""


def winrt_whole() -> tuple[str, list[str]]:
    """Which projection can answer for every namespace, and what is missing.

    ("winsdk"|"winrt", []) where one of them is complete, ("", [missing...])
    where winrt is present but partial, and ("", []) where neither is
    installed at all. The three are different problems with different
    answers, and the middle one used to report as the first.
    """
    import importlib

    partial: list[str] = []
    for pkg in ("winsdk", "winrt"):
        missing = []
        for tail in WINRT_NAMESPACES:
            try:
                importlib.import_module(f"{pkg}.{tail}")
            except ImportError:
                missing.append(f"{pkg}.{tail}")
        if not missing:
            return pkg, []
        if len(missing) < len(WINRT_NAMESPACES):
            partial = missing
    return "", partial


def winrt_module(tail: str) -> tuple[str, object]:
    """`winsdk.<tail>` or `winrt.<tail>`, and which of the two it came from.

    ("", None) where neither is installed. The window asks the same question
    the same way round at every one of its call sites, so this one answers
    for what it would actually get rather than for what is merely present.
    """
    import importlib

    for pkg in ("winsdk", "winrt"):
        try:
            return pkg, importlib.import_module(f"{pkg}.{tail}")
        except ImportError:
            continue
    return "", None


async def _await_winrt_operation(operation):
    return await operation


def winrt_wait(call, *args):
    """Finish a WinRT operation, preferring the projection's blocking API."""
    op = call(*args)
    get = getattr(op, "get", None)
    if callable(get):
        return get()
    import asyncio
    return asyncio.run(_await_winrt_operation(op))


def check_windows_output(pkg: str) -> None:
    """Whether the window can name the output device.

    A different pair of namespaces from the media transport, and installable
    without them, so this is asked separately -- the symptom of having the
    transport and not these is the Output row simply not being in the song
    panel, with nothing anywhere to say why.

    The two halves are not equal. Media.Devices gives the id, which is what
    the per-output timing offset is keyed by: without it every output shares
    one number again. Devices.Enumeration only gives the name, and the window
    has two more ways to come by one, so its absence costs a label at worst.
    """
    _, dev_mod = winrt_module("windows.media.devices")
    _, enum_mod = winrt_module("windows.devices.enumeration")
    missing = [name for name, mod in (("Media.Devices", dev_mod),
                                      ("Devices.Enumeration", enum_mod))
               if mod is None]
    rest = ("The media transport is there, so this is the rest of the same\n"
            "install:\n"
            "    pip install " + " ".join(WINRT_NEEDS[1:]))
    if dev_mod is None:
        say(WARN, "Output device", f"{pkg} is missing {', '.join(missing)}",
            rest)
        return
    try:
        dev = dev_mod.MediaDevice.get_default_audio_render_id(0)
    except Exception as e:                                  # noqa: BLE001
        say(WARN, "Output device", f"Windows would not name it ({e})")
        return
    if not dev:
        say(WARN, "Output device", "Windows names no default output",
            "Nothing is wrong with the install. There is no default render\n"
            "device -- every output is disabled or unplugged.")
        return
    name = ""
    if enum_mod is not None:
        try:
            info = winrt_wait(
                enum_mod.DeviceInformation.create_from_id_async, dev)
            name = (getattr(info, "name", "") or "").strip()
        except Exception:                                   # noqa: BLE001
            name = ""
    say(OK, "Output device", name or dev,
        "" if name else
        "Shown here by its interface path, which is the id -- the friendly\n"
        "name would not come back. The window does not show this: it reads\n"
        "the name out of the registry instead and falls back to a short tag,\n"
        "so this costs nothing but a nicer label.\n" + (rest if missing else ""))


def check_windows_players() -> None:
    """Who has a session open, and whether their clock is worth following.

    The same question check_other_players asks the bus, asked the Windows way.
    A session publishes a timeline and the moment it was written, so unlike
    the bus there is no need to sample twice to see whether it moves -- a
    stamp that is old is a session that has stopped writing.
    """
    import datetime as dt

    try:
        _, mod = winrt_module("windows.media.control")
        M = mod.GlobalSystemMediaTransportControlsSessionManager
        sessions = list(winrt_wait(M.request_async).get_sessions())
    except Exception as e:                                  # noqa: BLE001
        say(WARN, "Media sessions", f"the transport would not answer ({e})")
        return
    if not sessions:
        say(OK, "Media sessions", "nothing has one open",
            "Only matters with 'Any media player' on, which is off by\n"
            "default. Play something in a browser and run this again to see\n"
            "whether the window could follow it.")
        return
    for s in sessions:
        try:
            who = str(s.source_app_user_model_id or "?")
            info = winrt_wait(s.try_get_media_properties_async)
            pb, tl = s.get_playback_info(), s.get_timeline_properties()
            playing = int(getattr(pb.playback_status, "value",
                                  pb.playback_status)) == 4
            title = info.title or ""
        except Exception as e:                              # noqa: BLE001
            say(WARN, "Session", f"{who}: open but will not answer ({e})")
            continue
        said = ("playing" if playing else "not playing") + (f" — {title}" if title else "")
        if not playing:
            say(OK, f"Session: {who}", said + "; play something to test its clock")
            continue
        stamp = getattr(tl, "last_updated_time", None)
        old = None
        try:
            if stamp is not None and hasattr(stamp, "timestamp"):
                old = (dt.datetime.now(stamp.tzinfo or dt.timezone.utc)
                       - stamp).total_seconds()
        except Exception:                                   # noqa: BLE001
            old = None
        if old is None or not (0.0 <= old <= 30.0):
            say(WARN, f"Session: {who}", said + "; timeline has no usable stamp",
                "The window can still follow this one -- it watches for the\n"
                "position to change instead -- but the clock will be as\n"
                "coarse as whatever this player updates at.")
        else:
            say(OK, f"Session: {who}", said + f"; timeline written {old:.1f}s ago")


def check_mac_player() -> None:
    """Which of a Mac's three doors is open, and what to do about the shut ones.

    None of them is guaranteed, and which are available depends on the version
    of macOS and on two settings inside the browsers, so this is the check
    that most needs to say what it found -- "it does not follow my browser" is
    otherwise unanswerable from the outside.
    """
    sys.path[:0] = [str(HERE)] if str(HERE) not in sys.path else []
    try:
        import macplayer as MP
    except Exception as e:                                  # noqa: BLE001
        say(BAD, "macOS players", f"macplayer.py will not import ({e})",
            f"Copy it next to {HERE / 'lyrics_gui.py'}")
        return
    mr = MP.MediaRemote()
    card = mr.read() if mr.ok else None
    if card:
        say(OK, "MediaRemote", f"answering — {card.get('title') or 'a track'}"
            + (f" ({mr.who()})" if mr.who() else ""))
    elif mr.ok:
        say(WARN, "MediaRemote", "loads, but hands over an empty card",
            "Either nothing is playing, or this is macOS 15.4 or newer, where\n"
            "Apple shut the framework to programs without its private\n"
            "entitlement. There is nothing to install -- the Apple Events\n"
            "doors below are what the app will use instead.")
    else:
        say(WARN, "MediaRemote", mr.why or "not available",
            "The app will use Apple Events instead; see below.")

    for which in ("spotify", "music"):
        app = MP.MUSIC_APPS[which]
        if not MP.running(which):
            say(OK, f"{app}", "not running; open it and run this again")
            continue
        got = MP.music_app(which)
        if got:
            say(OK, f"{app}", f"answering — {got['title']} at {got['pos']:.1f}s")
        else:
            say(WARN, f"{app}", "running, but will not answer",
                "The first ask raises a permission prompt. Allow it, or turn\n"
                "it on under System Settings ▸ Privacy & Security ▸ Automation.")

    seen = False
    for which in sorted(MP.BROWSERS):
        if not MP.running(which):
            continue
        seen = True
        good, why = MP.checked(which)
        name = MP.BROWSERS[which]
        if good:
            say(OK, f"{name}", "will run JavaScript for us")
        elif which in MP.SAFARI:
            say(WARN, f"{name}", why,
                "Safari ▸ Settings ▸ Advanced ▸ Show features for web\n"
                "developers, then Develop ▸ Allow JavaScript from Apple\n"
                "Events. Without it the app cannot read Safari's tabs.")
        else:
            say(WARN, f"{name}", why,
                "View ▸ Developer ▸ Allow JavaScript from Apple Events.\n"
                "Without it the app cannot read this browser's tabs.")
    if not seen:
        say(OK, "Browsers", "none of the ones this can read are running",
            "Chrome, Edge, Brave, Vivaldi, Arc, Opera and Safari can be read\n"
            "through the page itself. Firefox cannot -- it has no scripting\n"
            "support on macOS -- so a song playing there is only visible\n"
            "while MediaRemote is answering.")


def check_other_players() -> None:
    """Who else is on the bus, and whether the window could follow them.

    For the any-media-player setting. What that needs from a player is a
    position that MOVES: MPRIS makes the property required, a player with
    nothing to put there publishes a zero that never changes, and that is the
    one failure here which looks like success -- the song plays and the words
    sit at 0:00 for the whole of it. It cannot be read off one sample, so a
    player that says it is playing is asked twice, a third of a second apart.

    Nothing here is a failure. Nobody has to have a second player, and a
    player that is merely paused is not being judged.
    """
    import time

    try:
        import dbus
        bus = dbus.SessionBus()
        names = sorted(str(n) for n in bus.list_names()
                       if str(n).startswith("org.mpris.MediaPlayer2.")
                       and not str(n).endswith(".spotify"))
    except Exception:                                       # noqa: BLE001
        return
    if not names:
        say(OK, "Other players", "none on the bus",
            "Only matters with 'Any media player' on, which is off by\n"
            "default. Play something in a browser and run this again to see\n"
            "whether the window could follow it.")
        return
    for name in names:
        who = name[len("org.mpris.MediaPlayer2."):].split(".")[0]
        try:
            obj = bus.get_object(name, "/org/mpris/MediaPlayer2")
            props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
            P = "org.mpris.MediaPlayer2.Player"
            status = str(props.Get(P, "PlaybackStatus"))
            title = str((props.Get(P, "Metadata") or {}).get("xesam:title", ""))
            first = float(props.Get(P, "Position")) / 1e6
        except Exception as e:                              # noqa: BLE001
            say(WARN, f"Player: {who}", f"on the bus but will not answer ({e})")
            continue
        said = f"{status.lower()}" + (f" — {title}" if title else "")
        if status != "Playing":
            say(OK, f"Player: {who}", said + "; play something to test its clock")
            continue
        time.sleep(0.35)
        try:
            again = float(props.Get(P, "Position")) / 1e6
        except Exception:                                   # noqa: BLE001
            again = first
        if abs(again - first) > 0.05:
            say(OK, f"Player: {who}", said + f"; clock moving ({first:.1f}s)")
        else:
            say(WARN, f"Player: {who}", said + f"; clock stuck at {first:.1f}s",
                "The window will not follow this one: it says it is playing\n"
                "but not where, so the words would sit at the start of the\n"
                "song for all of it. Nothing to fix here -- it is what that\n"
                "player publishes.")


def check_extras() -> None:
    if shutil.which("ffmpeg"):
        say(OK, "ffmpeg", "animated covers available")
    else:
        say(WARN, "ffmpeg", "not on PATH",
            "Only needed for animated album covers, which are off by default.")
    try:
        import pykakasi  # noqa: F401
        say(OK, "pykakasi", "Japanese romanisation available")
    except ImportError:
        say(WARN, "pykakasi", "not installed",
            "Only needed to derive romanisation for Japanese lyrics:\n"
            "    pip install pykakasi")


def check_caches() -> None:
    """What the app has left on the disk, and what it would take to get back.

    A warning at worst, and usually not even that -- a large cache is the
    app working, not the app broken. It is here because it is the one thing
    on this list nobody discovers on their own: art and animated covers
    accumulate one song at a time, and the first anybody knows of it is a
    full disk.
    """
    try:
        import caches
    except Exception as exc:                             # noqa: BLE001
        say(WARN, "Caches", f"could not read them ({exc})")
        return
    rows = caches.survey()
    total = sum(r["bytes"] for r in rows)
    big = [r for r in rows if r["bytes"] > 0][:4]
    detail = ", ".join(f"{r['key']} {r['human']}" for r in big) or "nothing yet"
    state = WARN if total > 2 * 1024 ** 3 else OK
    say(state, "Caches", f"{caches.human(total)} in {caches.cache_dir()}",
        f"Largest: {detail}\n"
        "Everything in there is derived and safe to clear:\n"
        f"    {sys.executable} {HERE / 'caches.py'}\n"
        f"    {sys.executable} {HERE / 'caches.py'} --clear all\n"
        "The ones marked * are work this machine did -- alignments and the\n"
        "editor's backups -- and are kept unless --everything is added."
        if state is WARN else f"Largest: {detail}")


def check_token() -> None:
    """Credentials this copy is holding, and how to be rid of them.

    They are not the same kind of thing. The Genius token is typed in by a
    person and is theirs, and a Spicy Lyrics secret key is its application's;
    the Apple and Musixmatch ones are lifted from a web player's own bundle
    and belong to nobody. All of them are worth naming before a copy of this
    goes to somebody else.
    """
    try:
        import caches
        held = caches.credentials()
    except Exception:
        return
    have = [c for c in held if c["present"]]
    if not have:
        say(OK, "Credentials", "none stored")
        return
    say(WARN, "Credentials", ", ".join(c["label"] for c in have),
        "Stored on this machine, not in the program files. Clear them\n"
        "before handing this copy to somebody else:\n"
        f"    {sys.executable} {HERE / 'caches.py'} --forget")


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


# Both entries point at the .pyw beside the checkout rather than into it.
# The player's used to name mild-lyrics/lyrics_gui.py directly, and a shortcut
# that names a file inside the tree breaks the day that tree is rearranged --
# which is how renaming aligner/ to mild-lyrics/ left a menu entry running a
# path that no longer existed, silently, because that is what a .desktop file
# does when its Exec is gone. The launchers are the stable door: they are at
# the top, they are what the README tells people to run, and they do their own
# sys.path work.
LAUNCHERS = [("mild-lyrics", ROOT / "mild-lyrics.pyw"),
             ("ttml-editor", ROOT / "ttml-editor.pyw")]


def make_shortcut() -> None:
    target = ROOT / "mild-lyrics.pyw"
    if WIN:
        pyw = pathlib.Path(sys.executable).with_name("pythonw.exe")
        exe = pyw if pyw.exists() else pathlib.Path(sys.executable)
        script = (
            "$ErrorActionPreference = 'Stop'\n"
            "$desk = [Environment]::GetFolderPath('Desktop')\n"
            "if (-not (Test-Path $desk)) { $desk = $env:USERPROFILE }\n"
            "$link = Join-Path $desk 'Mild Lyrics.lnk'\n"
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($link)\n"
            f"$s.TargetPath = '{exe}'\n"
            f'$s.Arguments = \'"{target}"\'\n'
            f"$s.WorkingDirectory = '{HERE}'\n"
            "$s.Save()\n"
            "Write-Output $link\n"
        )
        tmp = pathlib.Path(tempfile.gettempdir()) / "mild-lyrics-shortcut.ps1"
        try:
            tmp.write_text(script, encoding="utf-8")
            got = noconsole.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
                capture_output=True, text=True, timeout=40)
            if got.returncode == 0 and got.stdout.strip():
                say(OK, "Shortcut", got.stdout.strip())
            else:
                why = (got.stderr or got.stdout or "no output").strip().splitlines()
                say(BAD, "Shortcut", "PowerShell refused",
                    "\n".join(why[:3]) + "\n"
                    "Make one by hand instead: right-click the desktop,\n"
                    "New > Shortcut, and enter\n"
                    f'    "{exe}" "{target}"')
        except FileNotFoundError:
            say(BAD, "Shortcut", "powershell not found",
                f'Make one by hand pointing at:\n    "{exe}" "{target}"')
        except Exception as e:
            say(BAD, "Shortcut", f"{type(e).__name__}: {e}",
                f'Make one by hand pointing at:\n    "{exe}" "{target}"')
        finally:
            tmp.unlink(missing_ok=True)
        return
    if MAC:
        make_mac_apps()
        return
    apps = pathlib.Path.home() / ".local" / "share" / "applications"
    done = []
    for stem, entry in LAUNCHERS:
        src = ROOT / f"{stem}.desktop"
        if not src.exists() or not entry.exists():
            say(BAD, "Shortcut", f"{stem}: {src.name} or {entry.name} is missing")
            continue
        run = f"{sys.executable} {entry}"
        try:
            apps.mkdir(parents=True, exist_ok=True)
            out = apps / f"{stem}.desktop"
            lines = []
            for ln in src.read_text(encoding="utf-8").splitlines():
                if ln.startswith("#!"):
                    continue
                if ln.startswith("Exec="):
                    ln = f"Exec={run}"
                elif ln.startswith("Path="):
                    ln = f"Path={ROOT}"
                lines.append(ln)
            out.write_text("\n".join(lines) + "\n", encoding="utf-8")
            out.chmod(0o755)
            done.append(str(out))
        except Exception as e:
            say(BAD, "Shortcut", f"could not write {stem}.desktop ({e})")
    if not done:
        return
    for cmd in (["update-desktop-database", str(apps)], ["kbuildsycoca6"],
                ["kbuildsycoca5"]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except Exception:
            pass
    say(OK, "Shortcut", "\n".join(done))


MAC_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>%(name)s</string>
  <key>CFBundleDisplayName</key><string>%(name)s</string>
  <key>CFBundleIdentifier</key><string>%(id)s</string>
  <key>CFBundleExecutable</key><string>%(exe)s</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.15</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
"""
MAC_NAMES = {"mild-lyrics": "Mild Lyrics", "ttml-editor": "TTML Editor"}


def make_mac_apps() -> None:
    """A double-clickable bundle in ~/Applications for each program.

    A bundle rather than a .command file on the Desktop, for two reasons that
    are both about how a Mac treats a program rather than about tidiness. A
    bundle appears in Spotlight and the Dock and can be given permissions,
    which matters here more than anywhere: every Apple Events door this app
    reads is granted to an APPLICATION, and permissions granted to a bare
    script are granted to whichever terminal happened to run it.

    Written by hand rather than through a tool: this is four small files, and
    the alternative is asking somebody to install one.
    """
    apps = pathlib.Path.home() / "Applications"
    done, exe = [], sys.executable
    for stem, entry in LAUNCHERS:
        if not entry.exists():
            say(BAD, "Shortcut", f"{stem}: {entry.name} is missing")
            continue
        name = MAC_NAMES.get(stem, stem)
        bundle = apps / f"{name}.app"
        try:
            (bundle / "Contents" / "MacOS").mkdir(parents=True, exist_ok=True)
            (bundle / "Contents" / "Info.plist").write_text(
                MAC_PLIST % {"name": name, "id": f"dev.mild-lyrics.{stem}",
                             "exe": stem}, encoding="utf-8")
            run = bundle / "Contents" / "MacOS" / stem
            run.write_text(
                "#!/bin/sh\n"
                f'cd "{ROOT}" || exit 1\n'
                f'exec "{exe}" "{entry}" "$@"\n', encoding="utf-8")
            run.chmod(0o755)
            done.append(str(bundle))
        except Exception as e:                              # noqa: BLE001
            say(BAD, "Shortcut", f"could not write {name}.app ({e})")
    if done:
        say(OK, "Shortcut", "\n".join(done))


PROBE = ("Clocks", "Coldplay", 307.0)


def trace_genius(title: str, artist: str) -> None:
    """The editor's "From Genius" button, one step at a time.

    Its own path rather than the chain's provider, because the button does not
    use the provider: the editor asks for a LIST of songs and lets somebody
    pick, where the chain picks one by name and length and hands back a
    document. Two searches, two ways to fail, and the one people press is this
    one.

    Three doors, and each of them fails differently. The token is read out of
    the settings file the player writes, and on a machine where the player has
    never been opened there is none. api.genius.com wants it and answers 401
    without one. genius.com/songs/<id>/embed wants nothing and is a different
    host, so a proxy or an antivirus doing TLS interception can shut one and
    leave the other standing -- which is the shape of this on Windows, and why
    the two are asked separately here instead of being called good on the
    first answer.
    """
    sys.path.insert(0, str(HERE))
    import genius_roman as GR
    import local_align as LA
    import lyrics_gui as L

    token = L.load_token()
    if not token:
        say(BAD, "Genius token", f"none in {L.CONFIG}",
            "Genius will not search without one. Open the player, Settings,\n"
            "and paste a token from https://genius.com/api-clients -- the\n"
            "editor reads the same file.")
        return
    say(OK, "Genius token", f"{len(token)} characters, from {L.CONFIG}")

    hits = LA._genius_hits(token, title, artist, 8.0)
    if not hits:
        why = LA._genius_hits.last_error
        say(BAD if why else WARN, "Genius search",
            why or "answered, and knows no such song",
            "api.genius.com never answered. On Windows that is usually a\n"
            "proxy or a TLS interception -- an antivirus that inspects HTTPS\n"
            "-- standing in front of the request, and the line above is what\n"
            "it said. A 401 instead means the token itself was refused."
            if why else "")
        return
    say(OK, "Genius search", f"{len(hits)} hit(s): "
        + ", ".join(f"{h.get('id')} "
                    f"{str(h.get('full_title') or h.get('title')).replace(chr(160), ' ')!r}"
                    for h in hits[:3]))

    sid = int(hits[0].get("id"))
    raw = GR.lyrics_for(sid, 8.0, markup=True)
    if not raw or not raw.strip():
        why = GR.lyrics_for.last_error
        say(BAD if why else WARN, f"Genius page {sid}",
            why or "read, and has no words on it yet",
            "genius.com is a different host from api.genius.com, so this can\n"
            "fail on its own while the search above works."
            if why else "")
        return
    say(OK, f"Genius page {sid}", f"{len(raw)} characters")
    rows = GR.voiced_lines(raw)
    say(OK if rows else BAD, "Genius lyrics", f"{len(rows)} line(s)",
        "" if rows else
        "The page arrived and nothing here could read it, which is this\n"
        "program's own fault rather than the network's.")


def trace_spicy(track: str) -> None:
    """Ask Spicy Lyrics for one track and say what came back.

    By id rather than by name: Spicy Lyrics is the one source here that is
    asked about a Spotify track and not about a title, so `--song` is the id
    -- or, left as the default, whatever is playing.
    """
    sys.path.insert(0, str(HERE))
    import lyric_sources as LS
    import spicy_lyrics as SL
    tid = track if LS.SPICY_ID.match(track or "") else SL.current_track_id()
    if not tid:
        say(BAD, "Spicy Lyrics", "no track to ask about",
            "Pass a Spotify track id as --song (22 characters, the tail of a\n"
            "track URL), or start something playing.")
        return
    say(OK, "Track", tid)
    try:
        doc = LS.spicy_lyrics(tid, refresh=True)
    except LS.SpicyError as exc:
        say(BAD, "Spicy Lyrics", f"{exc.code or exc.status or 'no answer'}: {exc}",
            "A key fault is the likely one; run this without --source to see\n"
            "which key is being sent." if exc.key_fault else "")
        return
    if not doc:
        say(WARN, "Spicy Lyrics", "no lyrics for this track",
            "An answer, not a failure: nobody has a sync for it, and the\n"
            "chain goes on to the next source.")
        return
    whose = {"spl": "community", "aml": "Apple Music", "spt": "Spotify"}.get(
        str(doc.get("source") or ""), "unattributed")
    say(OK, "Spicy Lyrics", f"{LS.quality(doc)}, {len(LS._items(doc))} lines, "
                            f"from the {whose} catalogue")
    who = ", ".join(LS.credited(doc))
    if who:
        say(OK, "Timed by", who)
    if LS.SPICY_LIMIT.get("limit"):
        say(OK, "Requests left",
            f"{LS.SPICY_LIMIT['left']} of {LS.SPICY_LIMIT['limit']}, "
            f"resetting in {LS.SPICY_LIMIT.get('reset', 0):.0f}s")


def trace_source(name: str, title: str, artist: str, length: float) -> None:
    """Ask one source for one song and say how far it got.

    Here because "the lyrics do not appear" is not a report anybody can act
    on -- the walk runs ten providers wide on a worker thread and swallows
    every failure by design, so a source that is reachable, finds the song
    and then hands back nothing looks exactly like one that is blocked. This
    puts each step of the walk on the screen in turn.

    QQ Music gets its stages named because its path is the longest of them:
    a search, then a download, then a triple-DES its own client implements
    wrongly and a deflate, then the furniture -- a title card and the
    speaker labels -- taken off. Any of those can be the one that fails and
    they fail differently.
    """
    sys.path.insert(0, str(HERE))
    import lyric_sources as LS

    print(f"asking {name} for {title!r} by {artist!r}\n")
    if name == "genius":
        trace_genius(title, artist)
        return
    if name == "spicy":
        trace_spicy(title)
        return
    if name != "qq":
        fn = dict(LS.PROVIDERS).get(name)
        if fn is None:
            say(BAD, "Source", f"no provider called {name!r}",
                "The names are: " + ", ".join(n for n, _ in LS.PROVIDERS))
            return
        doc = fn("probe", {"title": title, "artist": artist, "length": length})
        if not doc:
            say(BAD, name, "no document")
            return
        say(OK, name, f"{LS.quality(doc)}, "
                      f"{len(LS._items(LS.SL.payload(doc)))} lines")
        return

    hits = LS._qq_hits(title, artist, length)
    if not hits:
        say(BAD, "QQ search", "nothing believable came back",
            "Either the endpoint refused the request -- which on Windows is\n"
            "usually a proxy or a TLS interception in front of it -- or it\n"
            "answered and no row matched on title, byline and length at once.")
        return
    say(OK, "QQ search", f"{len(hits)} candidate(s): "
                         + ", ".join(f"{sid} {name!r}" for sid, name, _ in hits[:3]))
    for sid, name_of, singer in hits[:LS.QQ_TRIES]:
        raw = LS._get(f"{LS.QQ_DOWN}?version=15&miniversion=82&lrctype=4"
                      f"&musicid={sid}", "text/xml")
        if not raw:
            say(BAD, f"QQ download {sid}", "no bytes")
            continue
        say(OK, f"QQ download {sid}", f"{len(raw)} bytes")
        parts = LS._qrc_parts(raw)
        if not parts.get("content"):
            say(BAD, f"QQ decrypt {sid}", "the payload did not come out as text",
                "The DES here is QQ's own broken one, ported bug for bug. If\n"
                "this is the step that fails the document arrived encrypted\n"
                "and something about it is not the shape this reads.")
            continue
        items, _wrote = LS._qrc_items(parts["content"])
        say(OK if items else BAD, f"QQ parse {sid}", f"{len(items)} timed lines")
        if not items:
            continue
        doc = LS._qq_doc(parts, name_of or title, singer or artist)
        if not doc:
            say(BAD, f"QQ document {sid}",
                "every line was dropped as furniture or as an instrumental card")
            continue
        say(OK, f"QQ document {sid}",
            f"{LS.quality(doc)}, {len(doc.get('Content') or [])} lines")
        return
    say(BAD, "QQ Music", "no candidate produced a document")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-shortcut", action="store_true",
                    help="check only; do not touch the desktop launcher")
    ap.add_argument("--source", metavar="NAME",
                    help="ask one lyric source for one song and print how far "
                         "it got, instead of checking the setup. Use it when a "
                         "source shows nothing and you cannot tell whether it "
                         "is the fetch or the drawing")
    ap.add_argument("--song", metavar="TITLE", default=PROBE[0],
                    help=f"what to ask --source for (default {PROBE[0]!r})")
    ap.add_argument("--artist", metavar="NAME", default=PROBE[1],
                    help=f"who it is by (default {PROBE[1]!r})")
    ap.add_argument("--length", type=float, metavar="SECONDS", default=PROBE[2],
                    help="how long the recording is, which is one of the three "
                         "signals a hit is believed on (default %.0f)" % PROBE[2])
    args = ap.parse_args()

    if args.source:
        trace_source(args.source, args.song, args.artist, args.length)
        return 1 if _fails else 0

    print("Mild Lyrics setup check  --  "
          + ("Windows" if WIN else "macOS" if MAC else os.uname().sysname))
    print(f"{HERE}\n")
    check_python()
    check_qt()
    check_files()
    check_spotify()
    check_spicetify()
    check_spicy_key()
    check_player()
    check_extras()
    check_caches()
    check_token()
    if not args.no_shortcut:
        print()
        make_shortcut()

    print()
    if _fails:
        print(f"{len(_fails)} thing(s) need attention: {', '.join(_fails)}")
        return 1
    print("Ready. Use the desktop shortcut, or:")
    print(f"    {'pythonw' if WIN else 'python3'} "
          f"{ROOT / 'mild-lyrics.pyw' if WIN else HERE / 'lyrics_gui.py'}")
    print(f"    {'pythonw' if WIN else 'python3'} "
          f"{ROOT / 'ttml-editor.pyw'}")
    if WIN:
        print()
        print("pythonw has no console, so nothing printed is visible. If the")
        print("window freezes or closes, the messages are in:")
        print(f"    {log_dir()}")
        print("named after the launcher -- mild-lyrics.log.txt, and the run")
        print("before it as mild-lyrics.log.prev.txt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
