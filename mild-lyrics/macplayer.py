"""What is playing on a Mac, by whichever of the three doors is open.

macOS has no session bus and no media transport that a program may simply
ask. What it has is:

  * MEDIAREMOTE, a private framework behind the now-playing card in Control
    Centre. It is the true equivalent of MPRIS -- one answer covering every
    player on the machine, browsers included, with an elapsed time, the
    moment that elapsed time was true, the rate it is running at, and the
    artwork as bytes. It is also the door Apple closed: since macOS 15.4 the
    functions answer nothing unless the caller carries an entitlement no
    third-party program can have. So it is TRIED, and where it answers it is
    used for everything, and where it does not the other two carry it.

  * APPLE EVENTS to the music players. Spotify and Music both publish a
    scripting dictionary with an exact player position in it -- better than
    anything MPRIS gives, since it is the player's own clock rather than a
    property sampled off a bus. The first ask raises the Automation consent
    prompt; a refusal is not a crash, it is this door reporting itself shut.

  * APPLE EVENTS INTO A BROWSER'S PAGE, which is how a song playing on
    YouTube reaches the window on a Mac with MediaRemote closed. Safari and
    the Chromium browsers will run a line of JavaScript in a tab for us,
    which reads the page's own MediaSession card and -- the part no other
    door on any platform gives -- the media element's currentTime, which is
    the exact position rather than a figure rounded to the second. Both
    browsers ship with that switched OFF; see NEEDS_JS, which is the message
    the window and the doctor both show.

Nothing here knows about lyrics, the window, or the transport that wraps it.
It answers one question -- who is playing what, and where have they got to --
and answers it as plain dictionaries, so it can be tested without a Mac by
handing the two readers something else to run.

One thing here is not about players at all: default_output, which names the
speaker the sound is coming out of. It lives here because it is the same kind
of thing -- a fact about this Mac that takes a framework to ask for -- and
because putting it anywhere else would mean a second ctypes preamble.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

import noconsole  # noqa: E402

MAC = sys.platform == "darwin"

NEEDS_JS = ("the browser will not run JavaScript for Apple Events yet — "
            "turn on Develop ▸ Allow JavaScript from Apple Events")

ASK_TIMEOUT = 4.0


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
MR_KEYS = {
    "title": "kMRMediaRemoteNowPlayingInfoTitle",
    "artist": "kMRMediaRemoteNowPlayingInfoArtist",
    "album": "kMRMediaRemoteNowPlayingInfoAlbum",
    "length": "kMRMediaRemoteNowPlayingInfoDuration",
    "elapsed": "kMRMediaRemoteNowPlayingInfoElapsedTime",
    "stamp": "kMRMediaRemoteNowPlayingInfoTimestamp",
    "rate": "kMRMediaRemoteNowPlayingInfoPlaybackRate",
    "art": "kMRMediaRemoteNowPlayingInfoArtworkData",
    "kind": "kMRMediaRemoteNowPlayingInfoMediaType",
    "uid": "kMRMediaRemoteNowPlayingInfoUniqueIdentifier",
}
MR_PATH = ("/System/Library/PrivateFrameworks/MediaRemote.framework/"
           "Versions/A/MediaRemote")
CF_EPOCH = 978307200.0
BUNDLE_NAMES = {
    "com.spotify.client": "spotify",
    "com.apple.music": "music",
    "com.apple.itunes": "music",
    "com.apple.safari": "safari",
    "com.apple.webkit": "safari",
    "com.google.chrome": "chrome",
    "com.microsoft.edgemac": "msedge",
    "com.brave.browser": "brave",
    "org.mozilla.firefox": "firefox",
    "company.thebrowser.browser": "arc",
    "com.operasoftware.opera": "opera",
    "com.vivaldi.vivaldi": "vivaldi",
    "org.videolan.vlc": "vlc",
    "io.mpv": "mpv",
}


def short_name(bundle: str) -> str:
    """The short name for a bundle id: com.spotify.client -> spotify."""
    got = str(bundle or "").strip().lower()
    if not got:
        return ""
    return BUNDLE_NAMES.get(got) or re.sub(r"[^a-z0-9]", "", got.rsplit(".", 1)[-1])


class MediaRemote:
    """The private framework, resolved once, or a closed door that says why.

    `ok` answers whether the framework is HERE -- loaded, with the symbols
    this calls exported. It does not answer whether it will tell you anything,
    because that is not a question it can be asked: since macOS 15.4 an
    unentitled caller gets a framework that loads, symbols that resolve, calls
    that succeed and an empty card, which is byte for byte what a Mac with
    nothing playing looks like. `read` returns {} for both, and telling them
    apart means asking somebody else whether they have a song -- which is
    MacTransport's job, not this one's.
    """

    def __init__(self) -> None:
        self.ok = False
        self.why = ""
        self._lib = None
        self._cf = None
        self._blocks: dict = {}
        self._landed: dict = {}
        self._lock = threading.RLock()
        self._who = ""
        self._who_at = 0.0
        if not MAC:
            self.why = "not a Mac"
            return
        try:
            self._open()
        except Exception as e:                              # noqa: BLE001
            self.why = f"MediaRemote will not load ({e})"

    def _open(self) -> None:
        import ctypes
        import ctypes.util

        self._cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        self._dispatch = ctypes.CDLL(ctypes.util.find_library("System"))
        self._lib = ctypes.CDLL(MR_PATH)
        cf = self._cf
        c_void_p, c_int, c_long = ctypes.c_void_p, ctypes.c_int, ctypes.c_long
        cf.CFStringCreateWithCString.restype = c_void_p
        cf.CFStringCreateWithCString.argtypes = [c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringGetCString.argtypes = [c_void_p, ctypes.c_char_p, c_long, ctypes.c_uint32]
        cf.CFStringGetLength.argtypes = [c_void_p]
        cf.CFStringGetLength.restype = c_long
        cf.CFDictionaryGetValue.restype = c_void_p
        cf.CFDictionaryGetValue.argtypes = [c_void_p, c_void_p]
        cf.CFGetTypeID.restype = c_long
        cf.CFGetTypeID.argtypes = [c_void_p]
        for name in ("CFStringGetTypeID", "CFNumberGetTypeID", "CFDateGetTypeID",
                     "CFDataGetTypeID", "CFBooleanGetTypeID"):
            getattr(cf, name).restype = c_long
        cf.CFNumberGetValue.argtypes = [c_void_p, c_int, c_void_p]
        cf.CFDateGetAbsoluteTime.restype = ctypes.c_double
        cf.CFDateGetAbsoluteTime.argtypes = [c_void_p]
        cf.CFAbsoluteTimeGetCurrent.restype = ctypes.c_double
        cf.CFDataGetLength.restype = c_long
        cf.CFDataGetLength.argtypes = [c_void_p]
        cf.CFDataGetBytePtr.restype = c_void_p
        cf.CFDataGetBytePtr.argtypes = [c_void_p]
        cf.CFRelease.argtypes = [c_void_p]
        self._dispatch.dispatch_get_global_queue.restype = c_void_p
        self._dispatch.dispatch_get_global_queue.argtypes = [c_long, ctypes.c_ulong]
        self._info = self._lib.MRMediaRemoteGetNowPlayingInfo
        self._info.argtypes = [c_void_p, c_void_p]
        self._is_playing = self._lib.MRMediaRemoteGetNowPlayingApplicationIsPlaying
        self._is_playing.argtypes = [c_void_p, c_void_p]
        try:
            self._client = self._lib.MRMediaRemoteGetNowPlayingClient
            self._client.argtypes = [c_void_p, c_void_p]
            self._bundle = self._lib.MRNowPlayingClientGetBundleIdentifier
            self._bundle.argtypes = [c_void_p]
            self._bundle.restype = c_void_p
        except AttributeError:
            self._client = self._bundle = None
        self.ok = True

    def _block(self, name: str, fn, *argtypes):
        """A C function wrapped as an Objective-C block, made once and kept.

        MediaRemote answers by calling a block, and a block is a struct whose
        fourth word is a function pointer -- so one can be built out of ctypes
        without an Objective-C runtime in sight. It has to be kept alive for
        as long as the framework might call it, which here is for the life of
        this object: `fn` reads what the caller left in `_landed`, and the
        lock above means there is never more than one caller.
        """
        import ctypes

        if name in self._blocks:
            return ctypes.byref(self._blocks[name][-1])

        class Descriptor(ctypes.Structure):
            _fields_ = [("reserved", ctypes.c_ulong), ("size", ctypes.c_ulong)]

        class Block(ctypes.Structure):
            _fields_ = [("isa", ctypes.c_void_p), ("flags", ctypes.c_int),
                        ("reserved", ctypes.c_int), ("invoke", ctypes.c_void_p),
                        ("descriptor", ctypes.POINTER(Descriptor))]

        kind = ctypes.CFUNCTYPE(None, ctypes.c_void_p, *argtypes)
        held = kind(lambda _self, value: fn(value))
        desc = Descriptor(0, ctypes.sizeof(Block))
        blk = Block()
        blk.isa = ctypes.c_void_p.in_dll(self._dispatch, "_NSConcreteGlobalBlock")
        blk.flags = 1 << 29
        blk.reserved = 0
        blk.invoke = ctypes.cast(held, ctypes.c_void_p)
        blk.descriptor = ctypes.pointer(desc)
        self._blocks[name] = (held, desc, blk)
        return ctypes.byref(blk)

    def _queue(self):
        return self._dispatch.dispatch_get_global_queue(0, 0)

    def _text(self, ref) -> str:
        import ctypes

        if not ref:
            return ""
        n = int(self._cf.CFStringGetLength(ref)) * 4 + 8
        buf = ctypes.create_string_buffer(n)
        if not self._cf.CFStringGetCString(ref, buf, n, 0x08000100):
            return ""
        return buf.value.decode("utf-8", "replace")

    def _number(self, ref) -> float:
        import ctypes

        if not ref:
            return 0.0
        out = ctypes.c_double(0.0)
        self._cf.CFNumberGetValue(ref, 13, ctypes.byref(out))
        return float(out.value)

    def _value(self, ref):
        """A Python value for whatever CoreFoundation type this is."""
        if not ref:
            return None
        tid = int(self._cf.CFGetTypeID(ref))
        if tid == int(self._cf.CFStringGetTypeID()):
            return self._text(ref)
        if tid == int(self._cf.CFNumberGetTypeID()):
            return self._number(ref)
        if tid == int(self._cf.CFDateGetTypeID()):
            return float(self._cf.CFDateGetAbsoluteTime(ref)) + CF_EPOCH
        if tid == int(self._cf.CFDataGetTypeID()):
            import ctypes

            n = int(self._cf.CFDataGetLength(ref))
            if n <= 0:
                return b""
            ptr = self._cf.CFDataGetBytePtr(ref)
            return ctypes.string_at(ptr, n)
        return None

    def _key(self, name: str):
        return self._cf.CFStringCreateWithCString(None, name.encode("utf-8"),
                                                  0x08000100)

    def who(self) -> str:
        """The short name of whoever the card belongs to, or "".

        Asked separately from the card because the framework keeps it
        separately, and cached for a moment because the answer only changes
        when somebody else starts playing. "" is a real answer and the caller
        must cope with it: the two symbols behind this are the first thing an
        older MediaRemote is missing.
        """
        if not self.ok or self._client is None:
            return ""
        now = time.monotonic()
        with self._lock:
            if now - self._who_at < 1.0:
                return self._who
            self._who_at = now
            import ctypes

            box: dict = {}
            done = threading.Event()
            self._landed["client"] = (box, done)

            def landed(ref):
                got, flag = self._landed.get("client", (None, None))
                try:
                    if ref and got is not None:
                        got["id"] = self._text(self._bundle(ref))
                except Exception:                           # noqa: BLE001
                    pass
                finally:
                    if flag is not None:
                        flag.set()

            self._client(self._queue(),
                         self._block("client", landed, ctypes.c_void_p))
            if not done.wait(ASK_TIMEOUT):
                return self._who
            self._who = short_name(box.get("id") or "")
            return self._who

    def read(self) -> dict | None:
        """The now-playing card, or None if this door is shut.

        None and an EMPTY card are two different answers and both happen: shut
        is shut, and an empty card is a Mac with nothing playing. The
        difference is what stops the transport falling back to Apple Events
        every time somebody pauses.
        """
        if not self.ok:
            return None
        import ctypes

        with self._lock:
            got: dict = {}
            done = threading.Event()
            playing = {"on": False}
            ready = threading.Event()
            self._landed["info"] = (got, done)
            self._landed["state"] = (playing, ready)

            def landed(ref):
                box, flag = self._landed.get("info", (None, None))
                try:
                    if ref and box is not None:
                        for field, key in MR_KEYS.items():
                            ckey = self._key(key)
                            try:
                                box[field] = self._value(
                                    self._cf.CFDictionaryGetValue(ref, ckey))
                            finally:
                                self._cf.CFRelease(ckey)
                except Exception:                           # noqa: BLE001
                    pass
                finally:
                    if flag is not None:
                        flag.set()

            def state(on):
                box, flag = self._landed.get("state", (None, None))
                if box is not None:
                    box["on"] = bool(on)
                if flag is not None:
                    flag.set()

            self._info(self._queue(), self._block("info", landed, ctypes.c_void_p))
            self._is_playing(self._queue(),
                             self._block("state", state, ctypes.c_bool))
            if not done.wait(ASK_TIMEOUT) or not ready.wait(0.5):
                return None
            if not got.get("title"):
                return {}
            said = got.get("rate")
            rate = float(said) if isinstance(said, float) else (
                1.0 if playing["on"] else 0.0)
            pos = float(got.get("elapsed") or 0.0)
            stamp = got.get("stamp")
            if playing["on"] and rate and isinstance(stamp, float):
                pos += max(0.0, time.time() - stamp) * rate
            kind = str(got.get("kind") or "")
            return {
                "who": "", "title": str(got.get("title") or ""),
                "artist": str(got.get("artist") or ""),
                "album": str(got.get("album") or ""),
                "length": float(got.get("length") or 0.0),
                "pos": max(0.0, pos),
                "playing": bool(playing["on"] and rate != 0.0),
                "art_bytes": got.get("art") if isinstance(got.get("art"), bytes) else b"",
                "art": "", "url": "",
                "kind": ("music" if kind.endswith("Music")
                         else "video" if kind.endswith("Video") else ""),
            }


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def run_script(source: str, timeout: float = ASK_TIMEOUT) -> str:
    """One AppleScript, its output, and "" for every way it can fail.

    Never raises. A player that is not installed, a consent prompt that was
    refused, a browser with JavaScript from Apple Events switched off and
    osascript itself missing all arrive here as the same empty string, and
    the caller's next move is the same for all of them: ask somebody else.
    """
    if not shutil.which("osascript"):
        return ""
    try:
        got = noconsole.run(["osascript", "-l", "AppleScript", "-e", source],
                            capture_output=True, text=True, timeout=timeout)
    except Exception:                                       # noqa: BLE001
        return ""
    if got.returncode != 0:
        return ""
    return (got.stdout or "").strip()


MUSIC_APPS = {"spotify": "Spotify", "music": "Music"}
MUSIC_MS = ("spotify",)
ASK_MUSIC = """
if application "%(app)s" is running then
  tell application "%(app)s"
    if player state is stopped then return ""
    set t to current track
    set out to (player state as text) & tab & ((player position) as text)
    set out to out & tab & (name of t) & tab & (artist of t)
    set out to out & tab & (album of t) & tab & ((duration of t) as text)
    return out
  end tell
end if
return ""
"""


def music_app(which: str) -> dict | None:
    """Spotify or Music, over Apple Events. None if it is not there."""
    app = MUSIC_APPS.get(which, "")
    if not app:
        return None
    out = run_script(ASK_MUSIC % {"app": app})
    if not out:
        return None
    parts = out.split("\t")
    if len(parts) < 6:
        return None
    state, pos, title, artist, album, length = (p.strip() for p in parts[:6])
    try:
        pos = float(pos)
        length = float(length)
    except ValueError:
        return None
    if which in MUSIC_MS:
        length /= 1000.0
    return {
        "who": which, "title": title, "artist": artist, "album": album,
        "length": max(0.0, length), "pos": max(0.0, pos),
        "playing": state.lower() == "playing",
        "art": "", "art_bytes": b"", "url": "",
        "kind": "music",
    }


PAGE_JS = (
    "(function(){var e=[].slice.call(document.querySelectorAll('video,audio'))"
    ".filter(function(x){return x.duration>0&&!x.ended;});"
    "var m=e.filter(function(x){return !x.paused;})[0]||e[0];if(!m)return '';"
    "var s=(navigator.mediaSession||{}).metadata||{};"
    "var a=(s.artwork||[]);"
    "return JSON.stringify({t:s.title||document.title||'',a:s.artist||'',"
    "al:s.album||'',p:m.currentTime,d:m.duration,u:location.href,"
    "r:m.paused?0:1,art:a.length?a[a.length-1].src:''});})()"
)

CHROMIUM = {
    "chrome": "Google Chrome", "brave": "Brave Browser",
    "msedge": "Microsoft Edge", "vivaldi": "Vivaldi", "arc": "Arc",
    "chromium": "Chromium", "opera": "Opera",
}
SAFARI = {"safari": "Safari"}
BROWSERS = dict(CHROMIUM, **SAFARI)

ASK_CHROMIUM = '''
if application "%(app)s" is running then
  tell application "%(app)s"
    repeat with w in windows
      repeat with t in tabs of w
        try
          set r to (execute t javascript "%(js)s")
          if r is not "" and r is not missing value then return r
        end try
      end repeat
    end repeat
  end tell
end if
return ""
'''
ASK_SAFARI = '''
if application "Safari" is running then
  tell application "Safari"
    repeat with w in windows
      repeat with t in tabs of w
        try
          set r to (do JavaScript "%(js)s" in t)
          if r is not "" and r is not missing value then return r
        end try
      end repeat
    end repeat
  end tell
end if
return ""
'''


def _js_literal(js: str) -> str:
    """The script as an AppleScript string literal."""
    return js.replace("\\", "\\\\").replace('"', '\\"')


def browser(which: str) -> dict | None:
    """A browser's playing tab, read through the page itself. None if shut.

    None covers every reason there is nothing here: the browser is not
    running, no tab is playing, the user never switched on Apple Events for
    JavaScript, or they refused the Automation prompt. Which of those it was
    is not knowable from the outside -- `checked` below is what tells the
    difference, and it is asked once by the doctor rather than four times a
    second by the window.
    """
    app = BROWSERS.get(which)
    if not app:
        return None
    js = _js_literal(PAGE_JS)
    src = (ASK_SAFARI % {"js": js} if which in SAFARI
           else ASK_CHROMIUM % {"app": app, "js": js})
    out = run_script(src)
    if not out:
        return None
    try:
        got = json.loads(out)
    except Exception:                                       # noqa: BLE001
        return None
    if not isinstance(got, dict):
        return None
    return {
        "who": which,
        "title": str(got.get("t") or ""), "artist": str(got.get("a") or ""),
        "album": str(got.get("al") or ""),
        "length": float(got.get("d") or 0.0), "pos": float(got.get("p") or 0.0),
        "playing": bool(got.get("r")),
        "art": str(got.get("art") or ""), "art_bytes": b"",
        "url": str(got.get("u") or ""),
        "kind": "",
    }


def running(which: str) -> bool:
    """Whether that application is open, without opening it."""
    app = BROWSERS.get(which) or MUSIC_APPS.get(which) or ""
    if not app:
        return False
    return run_script(f'return (application "{app}" is running) as text') == "true"


def checked(which: str) -> tuple[bool, str]:
    """Whether this browser will run JavaScript for us, and why not.

    For the doctor and for the one toast the window shows. Told apart by
    asking for something every page can answer: a browser that is merely
    playing nothing returns an empty document title, and one that has Apple
    Events switched off for JavaScript returns an error instead.
    """
    app = BROWSERS.get(which)
    if not app:
        return False, "not a browser this knows"
    if not running(which):
        return False, "not running"
    js = _js_literal("(function(){return 'ok';})()")
    src = (ASK_SAFARI % {"js": js} if which in SAFARI
           else ASK_CHROMIUM % {"app": app, "js": js})
    return (True, "") if run_script(src) == "ok" else (False, NEEDS_JS)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
CA_PATH = "/System/Library/Frameworks/CoreAudio.framework/Versions/A/CoreAudio"
def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


CA_SYSTEM = 1
CA_DEFAULT_OUT = _fourcc("dOut")
CA_GLOBAL = _fourcc("glob")
CA_NAME = _fourcc("lnam")
CA_UID = _fourcc("uid ")


def default_output() -> tuple[str, str]:
    """The Mac's current output device: (a stable id, a name to show).

    ("", "") for every way there is nothing to say, which on a Mac is only
    ever "this is not a Mac" or "CoreAudio would not answer" -- there is no
    optional piece to install and no permission to grant.

    It is the DEFAULT device rather than the player's own stream, and unlike
    PipeWire there is no per-application route to ask about: macOS has no user
    -facing way to send one app to a different output, so the default is the
    output, for every application on the machine.
    """
    if not MAC:
        return "", ""
    try:
        import ctypes
        import ctypes.util

        ca = ctypes.CDLL(CA_PATH)
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                          ctypes.c_long, ctypes.c_uint32]
        cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
        cf.CFStringGetLength.restype = ctypes.c_long
        cf.CFRelease.argtypes = [ctypes.c_void_p]

        class Address(ctypes.Structure):
            _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32),
                        ("element", ctypes.c_uint32)]

        ca.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(Address), ctypes.c_uint32,
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]

        def ask(obj, selector, out, size):
            addr = Address(selector, CA_GLOBAL, 0)
            n = ctypes.c_uint32(size)
            got = ca.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None,
                                                ctypes.byref(n), ctypes.byref(out))
            return got == 0

        dev = ctypes.c_uint32(0)
        if not ask(CA_SYSTEM, CA_DEFAULT_OUT, dev, 4) or not dev.value:
            return "", ""

        def text(selector) -> str:
            ref = ctypes.c_void_p()
            if not ask(dev.value, selector, ref, ctypes.sizeof(ref)) or not ref:
                return ""
            try:
                n = int(cf.CFStringGetLength(ref)) * 4 + 8
                buf = ctypes.create_string_buffer(n)
                if not cf.CFStringGetCString(ref, buf, n, 0x08000100):
                    return ""
                return buf.value.decode("utf-8", "replace")
            finally:
                cf.CFRelease(ref)

        name = text(CA_NAME)
        uid = text(CA_UID) or name
        return (uid, name or uid) if uid else ("", "")
    except Exception:                                       # noqa: BLE001
        return "", ""
