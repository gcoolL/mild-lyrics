"""Discord Rich Presence: the song, and the line being sung, on a profile.

Discord's desktop app listens on a local socket -- a Unix socket under the
runtime directory, a named pipe on Windows -- and anything on the machine may
say "this is what I am doing" over it. Nothing goes over the network from
here: Discord itself carries the activity to everyone else.

Spoken by hand rather than through pypresence. The protocol is five opcodes
and a JSON body, and this program is installed by people with no pip of their
own (see setup.sh), so one module less to fetch is one way less to break.

Everything the activity says comes from `activity()`, which is pure: the
settings preview draws exactly what would be sent, from the same function.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# The application whose name the profile shows -- "Listening to <its name>".
# Mild Lyrics' own, made on discord.com/developers; public by design, as every
# client that shows a presence sends its id. A setting can name another.
DEFAULT_APP_ID = "1558869325237059724"

REPO_URL = "https://github.com/gcoolL/mild-lyrics"

# Where animated covers are kept for Discord to fetch: the Worker in
# docs/discord-cover-worker. Empty, and the card keeps the still cover.
ART_HOST = "https://raspy-snowflake-c23c.gcoolltm.workers.dev"

OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG = range(5)

# Discord takes five activity changes in twenty seconds and drops the rest
# without a word. Lines take three of the five, spaced GAP apart, and the
# rest are kept for a change of song, which goes the moment it is seen --
# held behind a line's gap it reached the profile seconds late. A line
# shorter than GAP can be passed over: what goes is always the newest, never
# a queue of stale ones.
WINDOW, LIMIT = 20.0, 5
# Two of the five are kept for song changes: the cover lands a moment after
# the title, and with only one kept that second send waited up to 20s.
SPARE = 2
GAP = WINDOW / (LIMIT - SPARE)
# An urgent change waits this long for the rest of it (cover, album) to land,
# so a new song is usually one send rather than two.
SETTLE = 0.35
# How often a missing Discord is looked for again. A local socket, so cheap.
RETRY = 15.0
# The last line stays up this long after it ends, then the gap text does.
HOLD = 4.0

KINDS = ["listening", "playing"]
KIND_TYPE = {"playing": 0, "listening": 2}
LIST_SAYS = ["app", "top line", "second line"]
LIST_TYPE = {"app": 0, "second line": 1, "top line": 2}
PAUSED = ["hide", "show"]
PLACES = ("line", "next", "title", "artist", "album")

DEFAULTS = {
    "discord": False,
    "discord_kind": "listening",
    "discord_top": "{line}",
    "discord_mid": "{title} — {artist}",
    "discord_low": "{album}",
    "discord_gap": "♪",
    "discord_list": "app",
    "discord_cover": True,
    "discord_motion": True,
    "discord_time": True,
    "discord_paused": "hide",
    "discord_button": True,
    "discord_ad": False,
    "discord_listen": False,       # on: shares listen along by itself
    "discord_app": "",
}
# The rows typed into: templates, and the application id.
TEXT_KEYS = ("discord_top", "discord_mid", "discord_low", "discord_gap",
             "discord_app")
HINTS = {
    "discord_top": "the top line — {line} {next} {title} {artist} {album}",
    "discord_mid": "the second line — {line} {next} {title} {artist} {album}",
    "discord_low": "the third line, under the cover — {line} {next} {title} "
                   "{artist} {album}",
    "discord_gap": "what {line} says between lines and in songs without "
                   "synced lyrics",
    "discord_app": "a Discord application id from discord.com/developers — "
                   "its name is what “Listening to” says",
}
TAILS = {"discord_app": "empty uses Mild Lyrics' own",
         "discord_gap": "empty leaves {line} blank",
         **{k: "empty leaves the line out" for k in
            ("discord_top", "discord_mid", "discord_low")}}


def album_said(album: str, *titles: str) -> str:
    """The album, or "" when it is only the song's name again -- a single
    is filed as an album of its own name, "Song - Single" on Apple's side,
    and the card would say the title twice."""
    album = " ".join(str(album or "").split())
    bare = re.sub(r"\s*[-–—]\s*single\s*$", "", album, flags=re.I).casefold()
    if any(bare == " ".join(str(t).split()).casefold() for t in titles if t):
        return ""
    return album


def clean(values: dict) -> dict:
    """Saved settings, each one the type its default is."""
    out = {}
    for k, d in DEFAULTS.items():
        v = values.get(k, d)
        if isinstance(d, bool):
            v = bool(v)
        else:
            v = str(v if v is not None else d)
        if k == "discord_kind" and v not in KINDS:
            v = d
        if k == "discord_list" and v not in LIST_SAYS:
            v = d
        if k == "discord_paused" and v not in PAUSED:
            v = d
        if k == "discord_listen" and values.get(k) in ("off", "False"):
            v = False                   # from a build that had it as a choice
        out[k] = v
    return out


class _Blank(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fill(template: str, values: dict) -> str:
    """A template with its {places} filled. A place nobody knows is left as
    it was typed, and so is a template whose braces do not pair -- a typo
    shows up as itself rather than as nothing."""
    try:
        text = str(template or "").format_map(
            _Blank({k: str(values.get(k) or "") for k in PLACES}))
    except (ValueError, IndexError, AttributeError):
        text = str(template or "")
    return " ".join(text.split())


def _field(text: str, cap: int = 128) -> str:
    """Discord refuses a field under two characters and cuts it at 128."""
    text = text.strip(" —-·|,")
    if not text:
        return ""
    if len(text) > cap:
        text = text[:cap - 1].rstrip() + "…"
    if len(text) < 2:
        text += "\u2800"
    return text


def activity(state: dict, cfg: dict) -> dict | None:
    """What Discord is told, or None to show nothing.

    `state`: title, artist, album, line, next, art (a cover URL), playing,
    pos and length (seconds), spotify (a track id, or ""), listen (the
    listen-along page while sharing, or ""). `cfg`: the discord_* settings.
    """
    if not state or not state.get("title"):
        return None
    playing = bool(state.get("playing"))
    if not playing and cfg["discord_paused"] == "hide":
        return None
    values = dict(state)
    if not values.get("line"):
        values["line"] = cfg["discord_gap"]
    top = _field(fill(cfg["discord_top"], values))
    mid = _field(fill(cfg["discord_mid"], values))
    low = _field(fill(cfg["discord_low"], values))
    if not playing and top:
        top = _field("⏸ " + top)
    act: dict = {"type": KIND_TYPE.get(cfg["discord_kind"], 2)}
    if top:
        act["details"] = top
    if mid:
        act["state"] = mid
    say = LIST_TYPE.get(cfg["discord_list"], 0)
    if (say == 2 and top) or (say == 1 and mid):
        act["status_display_type"] = say
    art = str(state.get("art") or "")
    assets = {}
    if cfg["discord_cover"] and art.startswith("https://"):
        assets["large_image"] = art
    if low and (assets or cfg["discord_kind"] == "listening"):
        assets["large_text"] = low
    if assets:
        act["assets"] = assets
    length = float(state.get("length") or 0.0)
    if cfg["discord_time"] and playing and length > 0:
        start = time.time() - max(0.0, float(state.get("pos") or 0.0))
        act["timestamps"] = {"start": int(start * 1000),
                             "end": int((start + length) * 1000)}
    buttons = []
    listen = str(state.get("listen") or "")
    if cfg["discord_listen"] and listen.startswith("https://"):
        buttons.append({"label": "Listen along", "url": listen})
    sid = str(state.get("spotify") or "")
    if cfg["discord_button"] and sid:
        buttons.append({"label": "Listen on Spotify",
                        "url": f"https://open.spotify.com/track/{sid}"})
    if cfg["discord_ad"]:
        buttons.append({"label": "Get Mild Lyrics", "url": REPO_URL})
    if buttons:
        act["buttons"] = buttons[:2]        # Discord shows two at most
    return act


def same(a: dict | None, b: dict | None) -> bool:
    """Whether sending `a` after `b` would be an update for nothing.

    The time bar's times are not compared at all: it counts on by itself,
    and a send spent on moving it is one of the five in twenty seconds a
    line could have had. A seek's new times go with the next change that is
    sent anyway. Whether there is a time bar is compared -- it comes and
    goes with pausing and playing, and that is a change worth sending.
    """
    if a is None or b is None:
        return a is b
    if ("timestamps" in a) != ("timestamps" in b):
        return False
    strip = lambda d: {k: v for k, v in d.items() if k != "timestamps"}  # noqa: E731
    return strip(a) == strip(b)


# ------------------------------------------------------------------ the pipe
def _candidates() -> list[str]:
    if os.name == "nt":
        return [rf"\\?\pipe\discord-ipc-{i}" for i in range(10)]
    bases = [os.environ.get(k) for k in
             ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP")] + ["/tmp"]
    # Flatpak and Snap Discords, and Vesktop's, put theirs a folder down.
    subs = ["", "app/com.discordapp.Discord", "app/com.discordapp.DiscordCanary",
            "app/dev.vencord.Vesktop", ".flatpak/dev.vencord.Vesktop/xdg-run",
            "snap.discord", "snap.discord-canary"]
    out, seen = [], set()
    for base in bases:
        if not base or base in seen:
            continue
        seen.add(base)
        for sub in subs:
            for i in range(10):
                out.append(os.path.join(base, sub, f"discord-ipc-{i}"))
    return out


class _Pipe:
    """One open connection to Discord, either kind."""

    def __init__(self):
        self.sock = self.fh = None
        for path in _candidates():
            try:
                if os.name == "nt":
                    self.fh = open(path, "r+b", buffering=0)  # noqa: SIM115
                else:
                    if not os.path.exists(path):
                        continue
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(3.0)
                    s.connect(path)
                    self.sock = s
                return
            except OSError:
                continue
        raise ConnectionError("Discord is not running")

    def send(self, op: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        frame = struct.pack("<II", op, len(data)) + data
        if self.sock is not None:
            self.sock.sendall(frame)
        else:
            self.fh.write(frame)
            self.fh.flush()

    def _read(self, n: int) -> bytes:
        got = b""
        while len(got) < n:
            part = (self.sock.recv(n - len(got)) if self.sock is not None
                    else self.fh.read(n - len(got)))
            if not part:
                raise ConnectionError("Discord closed the connection")
            got += part
        return got

    def recv(self) -> tuple[int, dict]:
        op, n = struct.unpack("<II", self._read(8))
        try:
            return op, json.loads(self._read(n).decode("utf-8") or "{}")
        except ValueError:
            return op, {}

    def close(self) -> None:
        for h in (self.sock, self.fh):
            try:
                if h is not None:
                    h.close()
            except OSError:
                pass
        self.sock = self.fh = None


class Presence:
    """Keeps Discord showing whatever `want()` was last handed, from a thread
    of its own, so a slow or absent Discord never holds up a frame."""

    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._want: dict | None = None
        self._song = ""
        self._app = ""
        self._on = False
        self._stop = False
        self._thread: threading.Thread | None = None
        self.status = "off"          # what the settings row says beside "on"

    def want(self, act: dict | None, on: bool, app: str, song: str = "") -> None:
        """Show `act` (None: nothing). `song` names the track, so a change
        of it can go ahead of the lines' spacing."""
        with self._lock:
            self._want, self._on, self._song = act, bool(on), str(song or "")
            self._app = (app or "").strip() or DEFAULT_APP_ID
        if on and self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="discord-presence")
            self._thread.start()
        self._wake.set()

    def stop(self, wait: float = 0.5) -> None:
        """Take the activity down and let go of the pipe."""
        self._stop = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=wait)

    def said(self) -> str:
        return self.status

    def said_short(self) -> str:
        """The status in a word or two, for beside the switch; the whole
        sentence goes under the preview."""
        s = self.status
        for start, short in (("connected", "connected"),
                             ("no application", "no app ID"),
                             ("Discord is not", "Discord not open"),
                             ("Discord refused", "app ID refused"),
                             ("lost", "lost Discord"),
                             ("Discord did not", "no answer")):
            if s.startswith(start):
                return short
        return s if len(s) <= 20 else s[:19] + "…"

    def _run(self) -> None:
        pipe: _Pipe | None = None
        app_of = ""                 # the app this pipe was opened as
        sent: dict | None = None
        sent_song = ""
        shown = False               # whether Discord holds an activity of ours
        last = tried = 0.0
        times: list[float] = []     # sends within the last WINDOW
        moved_at = 0.0              # when the song key first differed
        nap = 1.0
        while True:
            self._wake.wait(timeout=nap)
            self._wake.clear()
            nap = 1.0
            with self._lock:
                want, on, app, song = (self._want, self._on, self._app,
                                       self._song)
            if self._stop or not on:
                if pipe is not None:
                    try:
                        if shown:
                            self._set(pipe, None)
                    except OSError:
                        pass
                    pipe.close()
                    pipe, shown, sent = None, False, None
                self.status = "off"
                if self._stop:
                    return
                continue
            if not app:
                self.status = "no application ID yet — set one under Application"
                continue
            if pipe is not None and app != app_of:
                pipe.close()
                pipe, shown, sent = None, False, None
            if pipe is None:
                if time.monotonic() - tried < RETRY and tried:
                    continue
                tried = time.monotonic()
                try:
                    pipe = self._connect(app)
                    app_of = app
                    self.status = "connected"
                except ConnectionError as exc:
                    self.status = str(exc) or "Discord is not running"
                    continue
                except (OSError, ValueError):
                    self.status = "Discord is not running"
                    continue
            if shown and same(want, sent):
                # Nothing to send -- and nothing owed: a song key that moved
                # without the card changing is not a change waiting to go.
                sent_song, moved_at = song, 0.0
                continue
            if not shown and want is None:
                continue
            now = time.monotonic()
            times = [t for t in times if now - t < WINDOW]
            # A new song, or the card coming or going, is not a line.
            urgent = song != sent_song or (want is None) == shown
            if urgent:
                moved_at = moved_at or now
                wait = max(SETTLE - (now - moved_at),
                           times[0] + WINDOW - now if len(times) >= LIMIT
                           else 0.0)
            else:
                wait = max(GAP - (now - last),
                           times[0] + WINDOW - now
                           if len(times) >= LIMIT - SPARE else 0.0)
            if wait > 0:
                # Back for it when there is room, newest wish then.
                nap = wait
                continue
            try:
                self._set(pipe, want)
                last, sent, shown = time.monotonic(), want, want is not None
                sent_song, moved_at = song, 0.0
                times.append(last)
                self.status = "connected" if want is not None else "connected · idle"
            except (OSError, ConnectionError, struct.error) as exc:
                pipe.close()
                pipe, shown, sent, tried = None, False, None, 0.0
                self.status = f"lost Discord ({exc.__class__.__name__})"

    @staticmethod
    def _connect(app: str) -> _Pipe:
        pipe = _Pipe()
        try:
            pipe.send(OP_HANDSHAKE, {"v": 1, "client_id": str(app)})
            op, body = pipe.recv()
        except (OSError, struct.error) as exc:
            pipe.close()
            raise ConnectionError("Discord did not answer") from exc
        if op == OP_CLOSE or body.get("evt") == "ERROR":
            pipe.close()
            code = (body.get("data") or {}).get("code") or body.get("code")
            raise ConnectionError("Discord refused the application id"
                                  if code in (4000, 4001, 4002) or "client"
                                  in str(body.get("message", "")).lower()
                                  else f"Discord said no ({code})")
        return pipe

    @staticmethod
    def _set(pipe: _Pipe, act: dict | None) -> None:
        args: dict = {"pid": os.getpid()}
        if act is not None:
            args["activity"] = act
        pipe.send(OP_FRAME, {"cmd": "SET_ACTIVITY", "args": args,
                             "nonce": str(uuid.uuid4())})
        while True:
            op, body = pipe.recv()
            if op == OP_PING:
                pipe.send(OP_PONG, body)
                continue
            if op == OP_CLOSE:
                raise ConnectionError("Discord closed the connection")
            if body.get("cmd") == "SET_ACTIVITY" or body.get("evt") == "ERROR":
                if body.get("evt") == "ERROR":
                    print("discord:", (body.get("data") or {}).get("message"),
                          file=sys.stderr)
                return


# ------------------------------------------------------- animated covers
# The GIF: a few seconds of the animation, small -- Discord draws the cover
# at under 120px -- and in few colours, so it is well under the Worker's 2MB.
GIF_SECS, GIF_FPS, GIF_PX, GIF_COLOURS = 5, 12, 160, 128
GIF_MAX = 2 * 1024 * 1024
# How long a GIF just put on the Worker is kept from Discord. The Worker
# keeps them in KV, and a write takes up to a minute to be seen at Cloudflare
# locations other than the one it went in at: handed over at once, Discord's
# image proxy -- fetching from elsewhere -- got "no cover" and showed a "?"
# (After Hours, 2026-10-12). The still cover stands in meanwhile.
GIF_SETTLE = 90.0
# How many queued tracks have their GIF made before they play. One: a song
# longer than GIF_SETTLE covers the wait by itself, and the queue is read
# again at every track change. Each upload is a KV write, and the Worker's
# free plan has 1,000 a day for every Mild Lyrics user together -- spent
# further ahead, they go on albums that are skipped or never reached.
AHEAD_TRACKS = 1
# How long "this album has no animation" is believed before asking again.
COVER_MISS_TTL = 30 * 86400
RESOLUTION = re.compile(r"^#EXT-X-STREAM-INF:.*?RESOLUTION=(\d+)x(\d+)", re.M)


def cover_key(source: str) -> str:
    """The Worker's name for a stream's GIF -- see worker.js, which checks
    it is this and not something picked freely."""
    return hashlib.sha256(source.encode()).hexdigest()[:32]


def small_variant(master: str, text: str, at_least: int = 320) -> str:
    """The smallest rendition at least `at_least` wide, from the master
    playlist's text: five seconds of the 4K one is downloaded for a 160px
    GIF otherwise."""
    lines = text.splitlines()
    pick = []
    for i, line in enumerate(lines):
        m = RESOLUTION.match(line)
        if not m:
            continue
        for nxt in lines[i + 1:i + 4]:
            nxt = nxt.strip()
            if nxt and not nxt.startswith("#"):
                pick.append((int(m.group(1)), urllib.parse.urljoin(master, nxt)))
                break
    if not pick:
        return master
    big = sorted(p for p in pick if p[0] >= at_least)
    return (big[0] if big else max(pick))[1]


class Covers:
    """Animated covers on the Worker, album by album, from a thread of its own.

    `want()` names an album; the first time, Apple is asked for its animated
    cover (`find`), the Worker is asked whether it already has the GIF, and if
    not one is made here with ffmpeg and put there. `url()` is then the
    address to give Discord, or "" while there is none -- the still cover
    stands in until then, and for every album with no animation at all.

    What has been learnt is kept in `memo` (a JSON file), so an album is only
    ever looked up once and a GIF only ever uploaded once.
    """

    def __init__(self, memo: pathlib.Path, find, fetch_text, run, ua: str):
        self.memo_path = memo
        self.find, self.fetch_text, self.run, self.ua = find, fetch_text, run, ua
        self._lock = threading.Lock()
        self._jobs: list = []
        self._busy: set = set()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.stop = False
        try:
            self.memo = json.loads(memo.read_text())
        except (OSError, ValueError):
            self.memo = {}

    def url(self, album: str) -> str:
        got = self.memo.get(album) or {}
        if not (ART_HOST and got.get("on_host") and got.get("source")):
            return ""
        if time.time() < float(got.get("ready_at") or 0):
            return ""                       # see GIF_SETTLE
        return f"{ART_HOST.rstrip('/')}/a/{cover_key(got['source'])}.gif"

    def want(self, album: str, artist: str, name: str, title: str,
             ahead: bool = False) -> None:
        """`ahead`: for a track still in the queue, so it waits behind the
        one playing rather than in front of it."""
        if not ART_HOST or not album.strip("|"):
            return
        got = self.memo.get(album) or {}
        if got.get("on_host"):
            return
        if (got and not got.get("source")
                and time.time() - float(got.get("at") or 0) < COVER_MISS_TTL):
            return
        if got.get("failed_at") and time.time() - got["failed_at"] < 600:
            return
        with self._lock:
            if album in self._busy:
                # Queued ahead and now playing: to the front of the line.
                for i, j in enumerate(self._jobs):
                    if j[0] == album and not ahead:
                        self._jobs.insert(0, self._jobs.pop(i))
                        break
                return
            self._busy.add(album)
            job = (album, artist, name, title)
            if ahead:
                self._jobs.append(job)
            else:
                self._jobs.insert(0, job)
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, daemon=True,
                                            name="discord-covers")
            self._thread.start()
        self._wake.set()

    def _note(self, album: str, **kw) -> None:
        with self._lock:
            self.memo[album] = {**(self.memo.get(album) or {}), **kw,
                                "at": int(time.time())}
            try:
                self.memo_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.memo_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.memo, indent=1))
                tmp.replace(self.memo_path)
            except OSError:
                pass

    def _work(self) -> None:
        while not self.stop:
            self._wake.wait(timeout=30)
            self._wake.clear()
            while not self.stop:
                with self._lock:
                    if not self._jobs:
                        break
                    job = self._jobs.pop(0)
                try:
                    self._one(*job)
                except Exception as exc:                 # noqa: BLE001
                    print(f"discord cover: {exc}", file=sys.stderr)
                    self._note(job[0], failed_at=time.time())
                finally:
                    with self._lock:
                        self._busy.discard(job[0])

    def _one(self, album: str, artist: str, name: str, title: str) -> None:
        source = (self.memo.get(album) or {}).get("source") or ""
        if not source:
            source = self.find(artist, name, title) or ""
            self._note(album, source=source)
            if not source:
                return
        where = f"{ART_HOST.rstrip('/')}/a/{cover_key(source)}.gif"
        if self._has(where):
            self._note(album, on_host=True)
            return
        gif = self._make(source)
        if not gif:
            self._note(album, failed_at=time.time())
            return
        req = urllib.request.Request(where, data=gif, method="PUT", headers={
            "Content-Type": "image/gif", "X-Source": source,
            "User-Agent": "Mild Lyrics"})
        try:
            with urllib.request.urlopen(req, timeout=30):
                pass
        except urllib.error.HTTPError as exc:
            if exc.code != 409:                     # 409: somebody beat us to it
                raise
        # Just written -- or written by somebody else moments ago, for a
        # 409 -- so not yet everywhere: see GIF_SETTLE.
        self._note(album, on_host=True, ready_at=time.time() + GIF_SETTLE)

    @staticmethod
    def _has(where: str) -> bool:
        req = urllib.request.Request(where, method="HEAD",
                                     headers={"User-Agent": "Mild Lyrics"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status == 200
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise

    def _make(self, source: str) -> bytes:
        """The GIF, from the stream, with ffmpeg; b"" if that did not work."""
        import subprocess
        import tempfile
        try:
            variant = small_variant(source, self.fetch_text(source))
        except Exception:                                # noqa: BLE001
            variant = source
        with tempfile.TemporaryDirectory(prefix="mild-gif-") as tmp:
            out = pathlib.Path(tmp) / "cover.gif"
            for fps, px, colours in ((GIF_FPS, GIF_PX, GIF_COLOURS),
                                     (10, 128, 64)):
                vf = (f"fps={fps},scale={px}:-2:flags=lanczos,split[a][b];"
                      f"[a]palettegen=max_colors={colours}[p];"
                      f"[b][p]paletteuse=dither=bayer:bayer_scale=4")
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                       "-threads", "1", "-user_agent", self.ua,
                       "-t", str(GIF_SECS), "-i", variant,
                       "-vf", vf, "-loop", "0", str(out)]
                if os.name != "nt" and __import__("shutil").which("nice"):
                    cmd = ["nice", "-n", "10", *cmd]
                try:
                    self.run(cmd, timeout=90, check=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except (OSError, subprocess.SubprocessError):
                    return b""
                try:
                    data = out.read_bytes()
                except OSError:
                    continue
                if data[:6] in (b"GIF89a", b"GIF87a") and len(data) <= GIF_MAX:
                    return data
        return b""


# --------------------------------------------------------------- the preview
def paint_preview(p, rect, act: dict | None, state: dict, cfg: dict,
                  cover, font, u: float, app_name: str = "Mild Lyrics") -> None:
    """A Discord profile card showing `act`, drawn into `rect`.

    Drawn from the same activity that would be sent, so what it says is what
    Discord is told; the look is Discord's dark card, approximately -- the
    client lays it out, and it does not lay every version out the same.
    `cover` is the album art as a QPixmap, or None. `font(px, weight)` makes
    a QFont.
    """
    from PyQt6.QtCore import QPointF, QRectF, Qt
    from PyQt6.QtGui import QColor, QFontMetricsF, QPainterPath, QPen

    left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    def text(r, s, f, colour, align=left):
        p.setFont(f)
        p.setPen(colour)
        s = QFontMetricsF(f).elidedText(s, Qt.TextElideMode.ElideRight, r.width())
        p.drawText(r, int(align), s)

    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(35, 36, 40))
    p.drawRoundedRect(rect, 10 * u, 10 * u)
    pad = 16 * u
    x, y, w = rect.x() + pad, rect.y() + pad, rect.width() - 2 * pad
    fhead = font(11.5 * u, 800)
    fbold, freg, fsmall = font(14 * u, 700), font(13.5 * u, 500), font(12 * u, 500)
    grey, white = QColor(181, 186, 193), QColor(242, 243, 245)
    if act is None:
        why = ("Nothing is playing" if not state.get("title") else
               "Paused — hidden while paused" if not state.get("playing")
               else "Nothing to show")
        text(QRectF(x, y, w, 20 * u), "NOT SHOWN", fhead, grey)
        text(QRectF(x, y + 24 * u, w, 22 * u), why, freg, grey)
        p.restore()
        return
    kind = "LISTENING TO" if act.get("type") == 2 else "PLAYING"
    text(QRectF(x, y, w, 18 * u), f"{kind} {app_name.upper()}", fhead, grey)
    y += 26 * u
    img = 84 * u
    assets = act.get("assets") or {}
    body_x = x
    if "large_image" in assets:
        box = QRectF(x, y, img, img)
        path = QPainterPath()
        path.addRoundedRect(box, 8 * u, 8 * u)
        p.setClipPath(path)
        if cover is not None and not cover.isNull():
            p.drawPixmap(box, cover, QRectF(cover.rect()))
        else:
            p.fillRect(box, QColor(64, 66, 73))
        p.setClipping(False)
        body_x = x + img + 14 * u
    bw = rect.right() - pad - body_x
    lines = []
    if act.get("details"):
        lines.append((act["details"], fbold, white))
    if act.get("state"):
        lines.append((act["state"], freg, grey))
    if assets.get("large_text") and act.get("type") == 2:
        lines.append((assets["large_text"], freg, grey))
    ly = y + 2 * u
    for s, f, c in lines:
        h = QFontMetricsF(f).height() * 1.3
        text(QRectF(body_x, ly, bw, h), s, f, c)
        ly += h
    ts = act.get("timestamps")
    if ts:
        span = max(1.0, (ts["end"] - ts["start"]) / 1000.0)
        at = max(0.0, min(span, time.time() - ts["start"] / 1000.0))
        by = max(ly + 8 * u, y + img - 16 * u) if "large_image" in assets \
            else ly + 8 * u
        bar = QRectF(body_x, by, bw, 4 * u)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(78, 80, 88))
        p.drawRoundedRect(bar, 2 * u, 2 * u)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * at / span,
                                 bar.height()), 2 * u, 2 * u)
        mm = lambda s: f"{int(s // 60)}:{int(s % 60):02d}"  # noqa: E731
        tr = QRectF(body_x, bar.bottom() + 3 * u, bw, 16 * u)
        text(tr, mm(at), fsmall, grey)
        text(tr, mm(span), fsmall, grey,
             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ly = tr.bottom()
    y = max(ly, y + (img if "large_image" in assets else 0)) + 12 * u
    buttons = act.get("buttons") or []
    if buttons:
        bw2 = (w - 8 * u * (len(buttons) - 1)) / len(buttons)
        for i, b in enumerate(buttons):
            r = QRectF(x + i * (bw2 + 8 * u), y, bw2, 32 * u)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(78, 80, 88))
            p.drawRoundedRect(r, 6 * u, 6 * u)
            text(r, b["label"], font(13 * u, 600), white,
                 Qt.AlignmentFlag.AlignCenter)
        y += 32 * u + 10 * u
    say = act.get("status_display_type", 0)
    what = (act.get("details") if say == 2 else act.get("state") if say == 1
            else app_name) or app_name
    verb = "Listening to" if act.get("type") == 2 else "Playing"
    p.setPen(QPen(QColor(63, 65, 71), 1))
    p.drawLine(QPointF(rect.x() + pad, y), QPointF(rect.right() - pad, y))
    # What the member list says, in white after a grey label: it is the
    # part of the card most people see, and the hardest to guess.
    label = "MEMBER LIST  "
    lw = QFontMetricsF(fhead).horizontalAdvance(label)
    text(QRectF(x, y + 6 * u, lw, 18 * u), label, fhead, grey)
    text(QRectF(x + lw, y + 6 * u, w - lw, 18 * u), f"{verb} {what}",
         font(12.5 * u, 600), white)
    p.restore()


def preview_height(act: dict | None, u: float) -> float:
    """How tall paint_preview draws `act`, for the row that holds it."""
    if act is None:
        return 70 * u
    h = 16 + 26 + 92 + 12 + 30
    if act.get("buttons"):
        h += 42
    return (h + 14) * u
