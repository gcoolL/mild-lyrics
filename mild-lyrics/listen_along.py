"""Listen along: one player shares what it plays through a `Listen` room on the
Worker, others follow in their own. Notes:
docs/notes/mild-lyrics/listen_along.md."""
from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

try:
    from PyQt6.QtWebSockets import QWebSocket, QWebSocketProtocol
    MISSING = ""
except ImportError:                                # pragma: no cover
    MISSING = "PyQt6's QtWebSockets"

import discord_presence as DP
import listen_voice as LV

WORKER = re.sub(r"^http", "ws", DP.ART_HOST.rstrip("/"))
INVITE = re.compile(r"(?:ml-listen:|mild-lyrics://listen/?|/l#)([A-Za-z0-9_-]{43})")
SCHEME = "mild-lyrics"
PAGE = f"{DP.ART_HOST.rstrip('/')}/l"          # the Discord button's page
KEYS = ("listen_share", "listen_join", "listen_stop", "listen_voice", "listen_mic")
MENU_ROWS = [
    ("Share what I play",  "listen_share", "action", None),
    ("Listen along",       "listen_join",  "action", None),
    ("Stop",               "listen_stop",  "action", None),
    ("Voice chat",         "listen_voice", "action", None),
    ("Microphone",         "listen_mic",   "action", None),
    ("Show on screen",     "listen_badge", "bool",   None),
    ("Voice volume",       "voice_volume", "num",    (0.0, 2.0, 0.1, "{:.1f}×")),
    ("Microphone sensitivity", "voice_sense", "choice", ["low", "normal", "high"]),
    ("Remove background noise", "voice_denoise", "bool", None),
]

TICK_MS = 500             # local only: reading the player costs no request
SETTLE_TICKS = 2          # a song change is sent once it has held this long
SEND_GAP = 1.0            # seconds between two sends, at least
JUMP = 2.0                # a place this far off the expected one was a seek
DRIFT = 1.0               # a listener this far out is moved back into step
SEEK_REST = 4.0           # seconds between two such moves
SEEKS_PER_EVENT = 3       # a player that will not land is not chased forever
HOLD = 10.0               # after a change, play/pause is kept as the sharer's
PLAY_WAIT = 8.0           # a song asked for that has not started by then
OPEN_WAIT_MS = 15000
PING_MS = 25000           # protocol pings: free, and keep proxies from closing it
BACK_OFF = (2, 5, 15, 30, 60)
TRIES = 12                # reconnects in a row before giving up
HOST_WAIT = 15 * 60       # a listener waits this long for a dropped sharer
FIRST_SETTLE = 0.8        # a joiner waits this long before acting on what it hears
AUTO_RETRY = 300          # seconds before an automatic share that failed tries again
SKIP_AGAIN = 5.0          # a refused skip done again this soon stops listening along
END_NEAR = 2.0            # the sharer's song this close to its end: the next is theirs
END_LEAD = 0.25           # a followed song is paused this far from its end, before autoplay
FLOODED = 4029
MOVE_GRACE_MS = 4000      # after locking, the old room is ended this long after the move
RESUME_WITHIN = 60.0      # reopened this soon after closing: the same share (or listen) carries on
BYE_MARGIN = 15.0         # a listener waits the sharer's "back within" and this much more
UPCOMING = 7              # the sharer's next songs sent along, at most (fetch ahead's own most)
QUEUE_GAP = 3.0           # a change to the queue alone is sent this long after the last send
STATE_MAX = 1024          # the Worker's limit on one sealed state (worker.js): fuller is dropped
CUT = 80                  # a queued song sent by name: title and artist cut to this many characters
ART_MAX = 300             # a cover address longer than this is left out of the state
ISRC = re.compile(r"[A-Z]{2}[A-Z0-9]{3}\d{7}")
SPOTIFY_ID = re.compile(r"[A-Za-z0-9]{22}")


# ------------------------------------------------------------------ crypto
def _derive(secret: bytes, what: bytes, n: int) -> bytes:
    return hashlib.blake2b(key=secret, digest_size=n, person=b"ml-listen-" + what).digest()


def room_of(secret: bytes) -> str:
    return _derive(secret, b"room", 16).hex()


def seal(secret: bytes, data: bytes) -> bytes:
    """nonce | data under a BLAKE2b keystream | BLAKE2b tag (encrypt-then-MAC)."""
    nonce = os.urandom(16)
    body = bytes(a ^ b for a, b in zip(data, _stream(secret, nonce, len(data))))
    tag = hashlib.blake2b(nonce + body, key=_derive(secret, b"mac", 32),
                          digest_size=16).digest()
    return nonce + body + tag


def unseal(secret: bytes, blob: bytes) -> bytes | None:
    if len(blob) < 32:
        return None
    nonce, body, tag = blob[:16], blob[16:-16], blob[-16:]
    want = hashlib.blake2b(nonce + body, key=_derive(secret, b"mac", 32),
                           digest_size=16).digest()
    if not hmac.compare_digest(tag, want):
        return None
    return bytes(a ^ b for a, b in zip(body, _stream(secret, nonce, len(body))))


def _stream(secret: bytes, nonce: bytes, n: int) -> bytes:
    key = _derive(secret, b"enc", 32)
    out = b"".join(hashlib.blake2b(nonce + i.to_bytes(8, "big"), key=key).digest()
                   for i in range((n + 63) // 64))
    return out[:n]


def code_of(secret: bytes) -> str:
    return base64.urlsafe_b64encode(secret).rstrip(b"=").decode()


def invite_text(secret: bytes) -> str:
    return f"Listen along with me in Mild Lyrics: ml-listen:{code_of(secret)}"


def page_url(secret: bytes) -> str:
    """The Discord button's link. The code rides after '#', which a browser
    never sends, so the Worker serving the page does not see it."""
    return f"{PAGE}#{code_of(secret)}"


def read_invite(text: str) -> bytes | None:
    m = INVITE.search(text or "")
    if not m:
        return None
    try:
        got = base64.urlsafe_b64decode(m.group(1) + "=")
    except ValueError:
        return None
    return got if len(got) == 32 else None


def plain(why: str) -> str:
    """A connection failure in words: Qt says handshakes in HTTP codes."""
    m = re.search(r"status code: (\d{3})", why or "")
    code = m.group(1) if m else ""
    if code == "404":
        return "Mild Lyrics' server has no listen along yet"
    if code == "403":
        return "somebody else is sharing with that invite"
    if code == "429":
        return "that share is full"
    return why or "the connection failed"


# -------------------------------------------------------- mild-lyrics://
def _launcher() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve().parent
    pyw = here.parent / "mild-lyrics.pyw"
    return pyw if pyw.exists() else here / "lyrics_gui.py"


def register() -> str:
    """Make mild-lyrics:// links open this copy of Mild Lyrics, so a click on
    a Discord card can reach it. Idempotent; says what it did."""
    exe, script = sys.executable, str(_launcher())
    if sys.platform.startswith("linux") or "bsd" in sys.platform:
        apps = pathlib.Path(os.environ.get("XDG_DATA_HOME")
                            or pathlib.Path.home() / ".local" / "share") / "applications"
        name = "mild-lyrics-listen.desktop"
        body = ("[Desktop Entry]\nType=Application\nName=Mild Lyrics (listen along)\n"
                f'Exec="{exe}" "{script}" --listen %u\n'
                f"Path={pathlib.Path(script).parent}\n"
                "NoDisplay=true\nTerminal=false\n"
                f"MimeType=x-scheme-handler/{SCHEME};\n")
        f = apps / name
        if not f.exists() or f.read_text(encoding="utf-8") != body:
            apps.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        mime = f"x-scheme-handler/{SCHEME}"
        got = subprocess.run(["xdg-mime", "query", "default", mime], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        if got != name:
            subprocess.run(["xdg-mime", "default", name, mime],
                           capture_output=True, timeout=10)
            return "registered"
        return "already registered"
    if os.name == "nt":
        import winreg
        w = pathlib.Path(exe).with_name("pythonw.exe")
        cmd = f'"{w if w.exists() else exe}" "{script}" --listen "%1"'
        base = rf"Software\Classes\{SCHEME}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:Mild Lyrics")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                              base + r"\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd)
        return "registered"
    return "not on this system"          # macOS needs an app bundle for it


def register_quietly() -> None:
    """register(), on a thread at startup: a failure only costs the links."""
    try:
        print(f"[listen] mild-lyrics:// links: {register()}", flush=True)
    except Exception as e:                           # noqa: BLE001
        print(f"[listen] mild-lyrics:// links not registered: {e}", flush=True)


def _server_name() -> str:
    try:
        who = getpass.getuser()
    except Exception:                                # noqa: BLE001
        who = "me"
    return "mild-lyrics-listen-" + hashlib.sha1(who.encode()).hexdigest()[:10]


def hand_over(text: str) -> bool:
    """Pass an invite to a Mild Lyrics already running; False if none is."""
    sock = QLocalSocket()
    sock.connectToServer(_server_name())
    if not sock.waitForConnected(1500):
        return False
    sock.write((text.strip()[:400] + "\n").encode())
    sock.flush()
    sock.waitForBytesWritten(1500)
    sock.disconnectFromServer()
    return True


class Door(QObject):
    """The running window's end of hand_over: an invite comes in, `knocked`."""

    knocked = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._new)
        name = _server_name()
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(300):
            probe.abort()              # another window has the door: leave it
            return
        if not self.server.listen(name):
            QLocalServer.removeServer(name)        # left behind by a crash
            self.server.listen(name)

    def _new(self) -> None:
        while self.server.hasPendingConnections():
            s = self.server.nextPendingConnection()
            s.readyRead.connect(lambda s=s: self._read(s))
            s.disconnected.connect(s.deleteLater)

    def _read(self, s) -> None:
        if s.canReadLine():
            text = bytes(s.readLine()).decode("utf-8", "replace").strip()
            s.abort()
            if read_invite(text):
                self.knocked.emit(text)


# -------------------------------------------------------------------- link
class Link(QObject):
    """One WebSocket to a listen room. Reconnects by itself after a drop."""

    ready = pyqtSignal(float)        # server clock minus ours, in seconds
    got = pyqtSignal(bytes)
    said = pyqtSignal(dict)          # the room's own text: n, gone
    failed = pyqtSignal(str)         # never opened, or gave up

    def __init__(self, room: str, host_key: str = "", base: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        if MISSING:
            raise RuntimeError(f"listen along needs {MISSING}")
        self.url = (f"{(base or WORKER).rstrip('/')}/listen/{room}?"
                    + (f"as=host&k={host_key}" if host_key else "as=hear"))
        self.ws = None
        self.up = False
        self.closed = False
        self.opened_once = False
        self.tries = 0
        self.sent = 0
        self._wait = QTimer(self, singleShot=True, timeout=self._late)
        self._ping = QTimer(self, timeout=self._pinged)
        self._open()

    def _open(self) -> None:
        ws = QWebSocket("", QWebSocketProtocol.Version.VersionLatest, self)
        ws.textMessageReceived.connect(self._text)
        ws.binaryMessageReceived.connect(lambda b: self.got.emit(bytes(b)))
        ws.disconnected.connect(lambda w=ws: self._dropped(w))
        ws.errorOccurred.connect(lambda _e, w=ws: None if self.up else self._dropped(w))
        self.ws, self.up = ws, False
        self._wait.start(OPEN_WAIT_MS)
        ws.open(QUrl(self.url))

    def _late(self) -> None:
        if self.ws is not None and not self.up:
            ws, self.ws = self.ws, None
            ws.abort()
            ws.deleteLater()
            self._again("Mild Lyrics' server did not answer")

    def _text(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("t") == "you":
            now = msg.get("now")
            if not isinstance(now, (int, float)):
                return
            self.up, self.opened_once, self.tries = True, True, 0
            self._wait.stop()
            self._ping.start(PING_MS)
            self.ready.emit(now / 1000.0 - time.time())
            self.said.emit(msg)
        else:
            self.said.emit(msg)

    def _dropped(self, ws) -> None:
        if ws is not self.ws or self.closed:
            return
        self.ws, self.up = None, False
        self._ping.stop()
        self._wait.stop()
        code = ws.closeCode()
        why = ws.closeReason() or ws.errorString() or "the connection closed"
        ws.deleteLater()
        if getattr(code, "value", code) == FLOODED:
            self.closed = True
            self.failed.emit(why)
            return
        self._again(why)

    def _again(self, why: str) -> None:
        if self.closed:
            return
        if not self.opened_once or self.tries >= TRIES:
            self.closed = True
            self.failed.emit(why)
            return
        wait = BACK_OFF[min(self.tries, len(BACK_OFF) - 1)]
        self.tries += 1
        QTimer.singleShot(wait * 1000, lambda: None if self.closed or self.ws
                          is not None else self._open())

    def _pinged(self) -> None:
        if self.ws is not None and self.up:
            self.ws.ping(b"")

    def send(self, data: bytes) -> bool:
        if self.ws is None or not self.up:
            return False
        self.ws.sendBinaryMessage(data)
        self.sent += 1
        return True

    def close(self) -> None:
        self.closed = True
        self._wait.stop()
        self._ping.stop()
        if self.ws is not None:
            self.ws.flush()
            self.ws.close()
            self.ws = None


# ------------------------------------------------------------------ session
def _compact(obj) -> bytes:
    """JSON as sent: no spaces, and UTF-8 rather than \\u escapes (a state has a size limit)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()


_NAMES: dict[str, tuple | None] = {}    # ISRC -> (title, artist, length), None if Deezer has none
_NAMING: set = set()
_NAMES_LOCK = threading.Lock()


def _deezer_names(isrc: str):
    """(title, artist, length) of a recording from Deezer by its ISRC; None when Deezer has no
    such recording, False when it could not be asked."""
    import stream_source as SS
    try:
        got = SS._get(f"{SS.DZ}/track/isrc:{isrc}")
    except OSError as e:
        return None if "no data" in str(e).lower() else False
    except ValueError:
        return False
    if not isinstance(got, dict) or not got.get("title"):
        return None
    who = [str(c.get("name") or "") for c in got.get("contributors") or [] if isinstance(c, dict)]
    artist = ", ".join(dict.fromkeys(w for w in who if w)) or str((got.get("artist") or {}).get("name") or "")
    return _drop_feat(str(got["title"]), artist), artist, float(got.get("duration") or 0)


def _drop_feat(title: str, artist: str) -> str:
    """A featured name the artists already carry is said once: "Feels (feat. Katy Perry)" by
    "Calvin Harris, Katy Perry" -> "Feels" (stream_source.drop_credited_feat)."""
    import stream_source as SS
    return SS.drop_credited_feat(title, artist)


def _song_of(t: dict) -> tuple:
    """A queued track, as far as following the sharer's queue tells songs apart."""
    return (t.get("spotify") or "", t.get("yt") or "", t.get("title") or "", t.get("artist") or "")


def _now(offset: float) -> float:
    """The server's clock, in seconds, as well as we know it."""
    return time.time() + offset


class ListenAlong(QObject):
    """The window's listen along: sharing, or following someone's share."""

    named = pyqtSignal()           # queued songs sent by ISRC were named (Deezer, off this thread)

    def __init__(self, view, base: str = "") -> None:
        super().__init__(view)
        self.view = view
        self.base = base
        self.role = ""             # "", "host" or "hear"
        self.secret = b""
        self.link: Link | None = None
        self.offset = 0.0
        self.heard = 0             # listeners, as the room counts them
        self.error = ("", "")      # (role it ended, why): shown until the next try
        self.timer = QTimer(self, timeout=self._tick)
        # sharing
        self._last: dict | None = None     # what was sent, with when (mono)
        self._seen = None                  # (tid, playing) and ticks held
        self._q_seen = None                # (queue, ticks held), the same for what comes next
        self._q_now: list = []             # who the songs in the last _state's queue are
        self._q_sent: list | None = None   # ... and in the last one sent
        self.named.connect(self._follow_queue)
        self._sent_at = 0.0
        # listening
        self.want: dict | None = None      # the sharer's latest state
        self._got_at = 0.0
        self._asked: tuple | None = None   # (host tid, mono, our tid then, in Mild Lyrics) of a play asked for
        self._mine: dict[str, str] = {}    # sharer's tid -> ours, found by search
        self._seek_at = 0.0
        self._seeks = 0
        self._toggle_at = 0.0
        self._host_gone_at = 0.0
        self._warned = ""
        self._act_after = 0.0              # a joiner's first states may be stale
        self._held_at = 0.0                # when a skip was last refused (holds)
        self._end_armed = ""               # our tid whose end pause is set (_arm_end)
        # sharing by itself, for the Discord button (keep_auto)
        self.auto = False
        self._auto_held = False            # stopped by hand: not again until toggled
        self._auto_retry = 0.0
        self.host_key = ""                 # the room's sharer key, kept to come back with
        self.locked = False                # sharing: no one new can join (see lock)
        self.started = 0.0                 # when this share or listen began (time.time())
        self._gone_wait = HOST_WAIT        # how long a listener waits for a dropped sharer
        self.voice = LV.ListenVoice(self)

    # -------------------------------------------------------------- menu
    def said(self, key: str) -> str:
        if key == "listen_share":
            if self.role == "host":
                n = self.heard
                how = "on your Discord card" if self.auto else "sharing"
                return (f"{how} · {n} listening" if self.link and self.link.up
                        else f"{how} · connecting")
            return self._ended("host") or "off"
        if key == "listen_join":
            if self.role == "hear":
                if not (self.link and self.link.up):
                    return "connecting"
                if self._host_gone_at:
                    return "waiting for the sharer"
                w = self.want or {}
                return f"with {w['title']}" if w.get("title") else "listening"
            return self._ended("hear") or "off"
        if key == "listen_voice":
            return self.voice.said()
        if key == "listen_mic":
            return self.voice.mic_said()
        return "run"

    def badge(self) -> tuple[str, bool] | None:
        """(text, live) for the main view's badge, or None to draw nothing:
        sharing shows only once somebody listens."""
        up = self.link is not None and self.link.up
        if self.role == "host" and up and self.heard:
            return f"{self.heard} listening along", True
        if self.role == "hear":
            if not up or self._host_gone_at:
                return "Listening along · waiting", False
            return "Listening along", True
        return None

    def look(self, key: str) -> tuple[str, bool]:
        """(verb, dimmed) for a row's button."""
        if key == "listen_share":
            return ("Copy invite" if self.role == "host" else "Start…"), False
        if key == "listen_join":
            return "Paste invite…", False
        if key == "listen_voice":
            return self.voice.look()
        if key == "listen_mic":
            return self.voice.mic_look()
        return "Stop", not self.role

    def toast(self, text: str) -> None:
        self.view.toast(text)
        self._changed()

    def _changed(self) -> None:
        """Redraw: the badge and the rows say what changed, and a paused
        window has no frame coming to show it."""
        update = getattr(self.view, "update", None)
        if update is not None:
            update()

    # ------------------------------------------------------------ actions
    def keep_auto(self, want: bool) -> None:
        """Share by itself while `want` (Discord status and its Listen along
        button on), so the card always has the button; stop when not."""
        if not want:
            self._auto_held = False
            if self.role == "host" and self.auto:
                self.stop(quiet=True)
            return
        if self.role or self._auto_held or time.monotonic() < self._auto_retry:
            return
        self.share(None, auto=True)

    def share(self, clipboard, auto: bool = False) -> None:
        """Start sharing, or copy the invite again; the invite goes on the
        clipboard either way (none for an automatic share)."""
        if self.role != "host":
            self.stop(quiet=True)
            self.secret = os.urandom(32)
            self.host_key = os.urandom(16).hex()
            if not self._connect(self.host_key):
                return
            self.role, self._last, self._seen, self._q_seen = "host", None, None, None
            self.auto, self.locked, self.started = auto, False, time.time()
            self.timer.start(TICK_MS)
        if clipboard is None:
            return
        if self.locked:
            self.toast("listen along is locked — unlock it to invite anyone else")
            return
        clipboard.setText(invite_text(self.secret))
        v = self.view
        on_card = getattr(v, "discord", False) and getattr(v, "discord_listen", False)
        self.toast("invite copied" + (" and on your Discord status" if on_card else "")
                   + " — anyone with it can listen along")

    def discord_url(self) -> str:
        """The Discord button's link while sharing (and not locked), else ""."""
        return page_url(self.secret) if self.role == "host" and not self.locked else ""

    def join(self, text: str, quiet: bool = False) -> bool:
        secret = read_invite(text)
        if secret is None:
            self.toast("that is not a listen-along invite")
            return False
        if self.role == "host" and secret == self.secret:
            self.toast("that is your own invite")
            return False
        self.stop(quiet=True)
        self.secret = secret
        if not self._connect(""):
            return False
        self.role, self.want, self._mine = "hear", None, {}
        self._host_gone_at = 0.0
        self._gone_wait = HOST_WAIT
        self.started = time.time()
        self._act_after = time.monotonic() + 10.0     # until the room answers
        self.timer.start(TICK_MS)
        if not quiet:
            self.toast("listening along — waiting for the song")
        return True

    def stop(self, quiet: bool = False, by_hand: bool = False) -> None:
        """`by_hand`: an automatic share stays stopped until it is toggled."""
        if by_hand and self.role == "host" and self.auto:
            self._auto_held = True
        self.voice.stop(quiet=True)
        self.voice.offered = ""
        if self.role == "host" and self.link is not None and self.link.up \
                and self.heard:
            self._send({"end": True})
        if self.link is not None:
            self.link.close()
            self.link.deleteLater()
        if self.role == "hear" and self.upnext() is not None and not self._in_mild():
            ask = getattr(self.view.fetcher, "request_queue", None)
            if ask is not None:
                ask()                  # the Spotify queue was the sharer's: read our own again
        self.link, self.role, self.heard = None, "", 0
        self.want, self._last, self.auto = None, None, False
        self.locked = False
        self.timer.stop()
        if not quiet:
            self.toast("listen along stopped")
        self._changed()

    # ------------------------------------------------------- session actions
    def lock(self) -> None:
        """No one new can join; those listening carry on.

        Done without the server's help: everyone listening is moved, inside
        the sealed channel only they can read, to a fresh room whose invite is
        never shown, and the old room -- the one whose invite is out there --
        is ended. Unlocking lets the current room's invite be copied again."""
        if self.role != "host" or self.locked or self.link is None:
            return
        if self.voice.v is not None:
            # its key is the old secret's, which the invite out there still gives
            self.voice.stop("listen along was locked — start voice chat again")
        old_link, old_secret = self.link, self.secret
        for sig in (old_link.ready, old_link.got, old_link.said, old_link.failed):
            try:
                sig.disconnect()
            except TypeError:
                pass
        self.secret, self.host_key = os.urandom(32), os.urandom(16).hex()
        self.link = None
        if not self._connect(self.host_key):
            self.link, self.secret = old_link, old_secret     # could not open a room: stay as is
            self._wire(old_link)
            return
        self.locked, self._last = True, None
        moved = self.heard

        def move(_offset=0.0):
            if old_link.closed:
                return
            if moved:
                old_link.send(self._sealed(old_secret, {"move": self.secret.hex()}))
            QTimer.singleShot(MOVE_GRACE_MS, lambda: self._end_room(old_link, old_secret))
        self.link.ready.connect(move)
        self._changed()
        self.toast("listen along locked — no one new can join")

    def unlock(self) -> None:
        if self.role == "host" and self.locked:
            self.locked = False
            self._changed()
            self.toast("listen along unlocked — the invite can be shared again")

    def restart(self, clipboard) -> None:
        """Everyone listening is dropped and a new invite takes over: the way to
        remove people when there is no telling who they are."""
        if self.role != "host":
            return
        auto = self.auto
        self.stop(quiet=True)
        self.share(clipboard, auto=auto)
        self.toast("everyone was dropped — new invite " + ("copied" if clipboard is not None else "ready"))

    def _sealed(self, secret: bytes, st: dict) -> bytes:
        st = {**st, "at": round(_now(self.offset), 3), "v": 1}
        return seal(secret, json.dumps(st, ensure_ascii=False, separators=(",", ":")).encode())

    def _end_room(self, link, secret: bytes) -> None:
        """Close a room that was moved out of; anyone still there (an older app,
        a late joiner on the old invite) is told it ended."""
        if not link.closed:
            link.send(self._sealed(secret, {"end": True}))
            QTimer.singleShot(1500, link.close)
            QTimer.singleShot(2000, link.deleteLater)

    def _hop(self, secret: bytes) -> None:
        """Told by the sharer to move to a locked room: go, keeping the song as it is."""
        if self.link is not None:
            old = self.link
            for sig in (old.ready, old.got, old.said, old.failed):
                try:
                    sig.disconnect()
                except TypeError:
                    pass
            old.close()
            old.deleteLater()
            self.link = None
        self.voice.stop(quiet=True)            # its key was the old room's
        self.voice.offered = ""
        self.secret = secret
        if not self._connect(""):
            self.stop(quiet=True)
            self.toast("could not follow the sharer into their locked room — listen along ended")
            return
        self._act_after = time.monotonic() + FIRST_SETTLE
        self._changed()

    # ----------------------------------------------------- across a restart
    def suspend(self, path) -> None:
        """The app is closing: listeners are told it will be back within RESUME_WITHIN,
        and the share (or the listen) is kept to carry on if it is reopened that soon."""
        role = self.role
        if role:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"role": role, "secret": self.secret.hex(),
                                            "key": self.host_key, "auto": self.auto,
                                            "locked": self.locked, "started": self.started,
                                            "at": time.time()}), encoding="utf-8")
                os.chmod(path, 0o600)
            except OSError:
                role = ""
        if role == "host" and self.link is not None and self.link.up and self.heard:
            self._send({"bye": RESUME_WITHIN})
            self.heard = 0                 # so stop() does not send "end" after it
        self.stop(quiet=True)

    def resume(self, path) -> bool:
        """Carry on a share or a listen from before a restart, if it was this soon ago."""
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
            path.unlink()
        except (OSError, ValueError):
            return False
        if not isinstance(got, dict) or time.time() - float(got.get("at") or 0) > RESUME_WITHIN:
            return False
        try:
            secret = bytes.fromhex(str(got.get("secret") or ""))
        except ValueError:
            return False
        if len(secret) != 32:
            return False
        if got.get("role") == "host" and got.get("key"):
            self.secret, self.host_key = secret, str(got["key"])
            if not self._connect(self.host_key):
                return False
            self.role, self._last, self._seen, self._q_seen = "host", None, None, None
            self.auto = bool(got.get("auto"))
            self.locked = bool(got.get("locked"))
            self.started = float(got.get("started") or time.time())
            self.timer.start(TICK_MS)
            return True
        if got.get("role") == "hear":
            return self.join(invite_text(secret), quiet=True)
        return False

    def _connect(self, host_key: str) -> bool:
        self.error = ("", "")
        try:
            link = Link(room_of(self.secret), host_key, self.base, self)
        except RuntimeError as e:
            self.toast(str(e))
            return False
        self._wire(link)
        self.link = link
        return True

    def _wire(self, link) -> None:
        link.ready.connect(self._ready)
        link.got.connect(self._got)
        link.said.connect(self._room_said)
        link.failed.connect(self._failed)

    # ------------------------------------------------------------- room
    def _ready(self, offset: float) -> None:
        self.offset = offset
        self._changed()
        if self.role == "host":
            self._last = None          # whoever joined meanwhile gets it now
            self._tick()
        else:
            # The room hands over the last state it kept, which can be from
            # before the sharer went quiet; a fresh one follows at once.
            self._act_after = time.monotonic() + FIRST_SETTLE

    def _room_said(self, msg: dict) -> None:
        n = msg.get("n")
        if self.role == "host" and isinstance(n, int) and not isinstance(n, bool):
            if n > self.heard:
                self.toast(f"{n} listening along")
                self._last = None      # nothing is sent to nobody: send it now
            self.heard = n
            self._changed()
            self._tick()
        if self.role == "hear" and msg.get("t") == "gone" and not self._host_gone_at:
            self._host_gone_at = time.monotonic()
            self.toast("the sharer dropped — waiting for them")

    def _ended(self, role: str) -> str:
        return f"stopped · {self.error[1]}" if self.error[0] == role else ""

    def _failed(self, why: str) -> None:
        was, auto = self.role, self.auto
        self.stop(quiet=True)
        why = plain(why)
        self.error = (was, why)
        if auto:
            self._auto_retry = time.monotonic() + AUTO_RETRY
            print(f"[listen] automatic share stopped: {why}", flush=True)
            return
        self.toast(f"listen along {'sharing ' if was == 'host' else ''}ended — {why}")

    # ----------------------------------------------------------- sharing
    def _state(self) -> dict:
        st = self.view.plugin_state()
        out = {"tid": st["tid"], "sp": st["spotify"] or st["spotify_match"],
               "title": st["title"], "artist": st["artist"],
               "len": round(st["length"], 2), "pos": round(st["pos"], 3),
               "on": bool(st["playing"] and st["tid"])}
        # Played in Mild Lyrics: what a listener's Mild Lyrics needs to stream the same recording.
        art = str(st.get("art") or "")
        if art.startswith("https://") and len(art) <= ART_MAX:
            out["art"] = art                     # the listener's own player has no other cover for it
        if self.voice.v is not None and self.voice.room:
            out["vc"] = self.voice.room          # the voice room; its key is the secret's
        cur = self._own_track()
        if cur and st["tid"]:
            out.update({k: str(cur.get(k) or "") for k in ("yt", "isrc", "album") if cur.get(k)})
            if not out["sp"] and cur.get("spotify"):
                out["sp"] = str(cur["spotify"])
        # What comes next, as many songs as fit in one state (Worker's STATE_MAX, sealed, with at and v).
        q, ident = self._upcoming(out) if out["tid"] else ([], [])
        size = len(_compact(out)) + 32 + 40
        while q and size + 5 + len(_compact(q)) > STATE_MAX:
            q.pop()
            ident.pop()
        out["q"] = q
        self._q_now = ident
        return out

    def _upcoming(self, cur: dict) -> tuple[list, list]:
        """The sharer's next songs, from Mild Lyrics' own queue when it is the one followed, else
        Spotify's, and who each is (what a change is told by). A song with an ISRC goes as its ids,
        {"i", "s", "y"}, which a listener names from Deezer; any other by name, {"t", "a", "l"}."""
        rows = []
        if self._own_track() is not None:
            lp = self.view.local_player
            for t in lp.queue[lp.idx + 1:lp.idx + 1 + UPCOMING]:
                rows.append((t.get("title"), t.get("artist"), t.get("ms"), t.get("spotify"),
                             t.get("yt"), t.get("isrc")))
        else:
            for it in getattr(self.view, "queue_items", None) or []:
                uri = str(it.get("uri") or "")
                if uri.startswith("spotify:track:"):
                    rows.append((it.get("name"), it.get("sub"), it.get("ms"),
                                 uri.rsplit(":", 1)[-1], "", it.get("isrc")))
                if len(rows) >= UPCOMING:
                    break
        out, ident = [], []
        for title, artist, ms, sp, yt, isrc in rows:
            title, artist, sp, yt = (str(x or "") for x in (title, artist, sp, yt))
            isrc = str(isrc or "").upper()
            if not (title or sp or yt):
                continue
            if not out and ((sp and sp == cur["sp"])
                            or (not sp and (title, artist) == (cur["title"], cur["artist"]))):
                continue           # the song playing, from a queue read before it started
            if ISRC.fullmatch(isrc):
                e = {"i": isrc}
            else:
                e = {"t": _drop_feat(title, artist)[:CUT], "a": artist[:CUT],
                     "l": round(float(ms or 0) / 1000.0, 1)}
            e.update({k: v for k, v in (("s", sp), ("y", yt)) if v})
            out.append(e)
            ident.append((sp, yt, title, artist))
        return out, ident

    def _own_track(self) -> dict | None:
        """The song Mild Lyrics' own player is playing, when it is the one followed."""
        lp = getattr(self.view, "local_player", None)
        if lp is None or not getattr(self.view.clock.io, "mine", lambda: False)():
            return None
        return lp.current

    def _send(self, st: dict) -> None:
        st = {**st, "at": round(_now(self.offset), 3), "v": 1}
        blob = seal(self.secret, _compact(st))
        if self.link is not None and self.link.send(blob):
            self._last = {**st, "mono": time.monotonic()}
            if "q" in st:
                self._q_sent = self._q_now
            self._sent_at = time.monotonic()

    def _host_tick(self) -> None:
        if self.link is None or not self.link.up:
            return
        if not self.heard:
            self._last = None          # nobody to tell: every message is counted
            return
        st = self._state()
        key = (st["tid"], st["on"])
        held = self._seen[1] + 1 if self._seen and self._seen[0] == key else 1
        self._seen = (key, held)
        ident = self._q_now           # the songs, not how they are sent: an ISRC found later is no change
        q_held = self._q_seen[1] + 1 if self._q_seen and self._q_seen[0] == ident else 1
        self._q_seen = (ident, q_held)
        last = self._last
        if last is None:
            self._send(st)
            return
        if time.monotonic() - self._sent_at < SEND_GAP:
            return
        if key != (last["tid"], last["on"]):
            if held >= SETTLE_TICKS:
                self._send(st)
            return
        if st.get("art") and st.get("art") != last.get("art"):
            self._send(st)             # the cover landed after the song was sent
            return
        expect = last["pos"] + ((time.monotonic() - last["mono"]) if last["on"] else 0.0)
        if st["tid"] and abs(st["pos"] - expect) > JUMP:
            self._send(st)
            return
        # Only what is queued changed (a song added, autoplay topping up): sent once it holds,
        # and not hard on another send, so a burst of edits is one message.
        if ident != self._q_sent and q_held >= SETTLE_TICKS \
                and time.monotonic() - self._sent_at >= QUEUE_GAP:
            self._send(st)

    # --------------------------------------------------------- listening
    def _got(self, blob: bytes) -> None:
        if self.role != "hear":
            return
        raw = unseal(self.secret, blob)
        try:
            st = json.loads(raw) if raw else None
        except ValueError:
            st = None
        if not isinstance(st, dict) or st.get("v") != 1:
            return
        if isinstance(st.get("move"), str):
            try:
                to = bytes.fromhex(st["move"])
            except ValueError:
                to = b""
            if len(to) == 32:
                self._hop(to)
            return
        if isinstance(st.get("bye"), (int, float)) and not isinstance(st.get("bye"), bool):
            # The sharer closed the app and may be back within this long.
            self._host_gone_at = time.monotonic()
            self._gone_wait = float(st["bye"]) + BYE_MARGIN
            self._changed()
            self.toast("the sharer is restarting Mild Lyrics — waiting for them")
            return
        if self._host_gone_at:
            self._changed()
        self._host_gone_at = 0.0
        self._gone_wait = HOST_WAIT
        if st.get("end"):
            self.stop(quiet=True)
            self.toast("the sharer stopped — listen along ended")
            return
        if not all(isinstance(st.get(k), t) for k, t in (
                ("tid", str), ("sp", str), ("pos", (int, float)),
                ("at", (int, float)), ("on", bool))):
            return
        self.voice.offer(st.get("vc"))
        old = self.want
        new = old is None or old["tid"] != st["tid"]
        if not new and st.get("q") != old.get("q") and st["on"] == old["on"] \
                and abs(self._expected(st) - self.expected()) <= JUMP:
            self.want = st             # only the queue changed: no new hold, no new seeks
            self._follow_queue()
            return
        self.want, self._got_at = st, time.monotonic()
        self._seeks, self._seek_at, self._toggle_at = 0, 0.0, 0.0
        self._end_armed = ""            # a repeat of the same song ends again
        if new:
            self._asked = None
        self._hear_tick()              # waits out _act_after by itself
        if new or st.get("q") != old.get("q"):
            self._follow_queue()

    def upnext(self) -> list[dict] | None:
        """The sharer's next songs as home rows, or None when not listening along or the
        sharer sends none (an app from before the queue was shared). Songs sent by ISRC
        are named from Deezer; the rows stop at the first still being asked about, so the
        order is never wrong, and one Deezer does not know goes without a name."""
        q = (self.want or {}).get("q")
        if self.role != "hear" or not isinstance(q, list):
            return None
        rows, ask = [], []
        for e in q:
            if not isinstance(e, dict) or not all(isinstance(v, str) for k, v in e.items() if k != "l"):
                continue
            sp, yt = e.get("s", ""), e.get("y", "")
            sp = sp if SPOTIFY_ID.fullmatch(sp) else ""
            isrc = e.get("i", "")
            if isrc:
                if not ISRC.fullmatch(isrc):
                    continue
                if isrc not in _NAMES:
                    ask.append(isrc)
                    continue
                title, artist, length = _NAMES[isrc] or ("", "", 0.0)
                if not (title or sp or yt):
                    continue
            else:
                title, artist, length = e.get("t", ""), e.get("a", ""), e.get("l", 0)
                if not isinstance(length, (int, float)) or isinstance(length, bool):
                    continue
            if ask:
                continue                # after one not named yet: kept back, not reordered
            rows.append({"kind": "track", "name": title, "sub": artist, "album": "",
                         "ms": int(max(0.0, float(length)) * 1000),
                         "uri": f"spotify:track:{sp}" if sp else "", "yt": yt, "isrc": isrc,
                         "src": "listen"})
        if ask:
            self._name(ask)
        return rows

    def _name(self, codes: list) -> None:
        """Ask Deezer for these ISRCs' names on a thread; `named` once they are in."""
        with _NAMES_LOCK:
            codes = [c for c in codes if c not in _NAMING]
            _NAMING.update(codes)
        if codes:
            threading.Thread(target=self._naming, args=(codes,), name="listen-names",
                             daemon=True).start()

    def _naming(self, codes: list) -> None:
        for code in codes:
            got = _deezer_names(code)
            with _NAMES_LOCK:
                _NAMING.discard(code)
                if got is not False:          # a failure to ask is asked again with the next queue
                    _NAMES[code] = got
                    while len(_NAMES) > 256:
                        _NAMES.pop(next(iter(_NAMES)))
        self.named.emit()

    def spotify_queue(self, items: list) -> list:
        """What the window takes as Spotify's queue: listening along in Spotify, the sharer's
        next songs (it cannot be set in Spotify itself, but fetch ahead reads this)."""
        rows = None if self._in_mild() else self.upnext()
        return items if rows is None else [r for r in rows if r["uri"]]

    def _follow_queue(self) -> None:
        """The sharer's queue changed: ours follows. In Mild Lyrics' player, after the song
        playing, once it is theirs (until then _play queues it with the song); in Spotify, as
        the window's queue for fetch ahead."""
        rows = self.upnext()
        if rows is None:
            return
        v = self.view
        if not self._in_mild():
            v.queue_items, v.queue_at = self.spotify_queue([]), time.monotonic()
            for then in ("fetch_ahead_scan", "update"):
                if hasattr(v, then):
                    getattr(v, then)()
            return
        lp = getattr(v, "local_player", None)
        if lp is None or lp.current is None or not self._ours(self.want, v.clock.tid or ""):
            return
        tracks = [v.homep().stream_of(r) for r in rows]
        if [_song_of(t) for t in lp.queue[lp.idx + 1:]] != [_song_of(t) for t in tracks]:
            lp.replace_after(tracks)

    def expected(self) -> float:
        return self._expected(self.want or {})

    def _expected(self, w: dict) -> float:
        if not w:
            return 0.0
        pos = float(w["pos"])
        if w["on"]:
            pos += max(0.0, _now(self.offset) - float(w["at"]))
        return pos

    def _ours(self, w: dict, tid: str) -> bool:
        return bool(tid) and tid in (w["tid"], w["sp"], self._mine.get(w["tid"]))

    def _hear_tick(self) -> None:
        w = self.want
        if self._host_gone_at and time.monotonic() - self._host_gone_at > self._gone_wait:
            self.stop(quiet=True)
            self.toast("the sharer did not come back — listen along ended")
            return
        if not w or time.monotonic() < self._act_after:
            return
        v, now = self.view, time.monotonic()
        tid = v.clock.tid or ""
        playing = v.clock.status == "Playing"
        fresh = now - self._got_at < HOLD
        if not w["tid"]:
            if playing and fresh and now - self._toggle_at > 2.0:
                self._toggle_at = now
                v.clock.command("PlayPause")
            return
        ending = self._over(w)
        if not self._ours(w, tid):
            if self._host_gone_at:
                return              # nobody to follow meanwhile: theirs to pick
            if ending:
                # Our own autoplay got in before the sharer's next song came.
                if playing and now - self._toggle_at > 2.0:
                    self._toggle_at = now
                    v.clock.command("PlayPause")
                return
            self._play(w, tid, now)     # skipped some other way: back to theirs
            return
        if self._asked:
            self._asked = None
            self._got_at = now      # the hold starts once it is really playing
            fresh = True
            self._follow_queue()    # a queue sent while it was starting
        if ending and not self._host_gone_at:
            if not playing:
                return              # paused at its end: the next song is the sharer's
            self._arm_end(tid)
        if fresh and playing != w["on"] and now - self._toggle_at > 2.0:
            self._toggle_at = now
            v.clock.command("PlayPause")
            return
        if playing == w["on"] and not ending and self._seeks < SEEKS_PER_EVENT \
                and now - self._seek_at > SEEK_REST:
            if abs(v.clock.position() - self.expected()) > DRIFT:
                self._seek_at, self._seeks = now, self._seeks + 1
                v.clock.seek(self.expected())

    def holds(self, what: str) -> bool:
        """While listening along, skips and picked songs are the sharer's:
        the first is refused, the same again within SKIP_AGAIN stops
        listening and goes through."""
        if self.role != "hear":
            return False
        now = time.monotonic()
        if now - self._held_at < SKIP_AGAIN:
            self._held_at = 0.0
            self.stop()
            return False
        self._held_at = now
        again = "pick it" if what == "play" else "skip"
        self.toast(f"the sharer picks the songs — {again} again to stop listening along")
        return True

    def _over(self, w: dict) -> bool:
        return bool(w["on"]) and float(w.get("len") or 0) > 0 \
            and self.expected() > float(w["len"]) - END_NEAR

    def _arm_end(self, tid: str) -> None:
        """Pause our copy just before it ends, so the player's own autoplay
        never sounds before the sharer's next song arrives."""
        v = self.view
        length = float(v.clock.meta.get("length") or 0.0) or float(self.want["len"])
        left = length - v.clock.position()
        if self._end_armed == tid or not 0.0 < left < 1.5:
            return
        self._end_armed = tid
        QTimer.singleShot(int(max(0.0, left - END_LEAD) * 1000), lambda: self._at_end(tid))

    def _at_end(self, tid: str) -> None:
        v = self.view
        if self.role == "hear" and self._end_armed == tid and v.clock.tid == tid \
                and v.clock.status == "Playing":
            self._toggle_at = time.monotonic()
            v.clock.command("PlayPause")

    def _play(self, w: dict, tid: str, now: float) -> None:
        """Start the sharer's song here, in whichever player this window plays songs in
        (the home page's play_in): Mild Lyrics' own, streamed by name and recording; else
        Spotify, by its Spotify id or a search of Spotify's catalogue (first track taken)."""
        if self._asked and self._asked[0] == w["tid"]:
            if tid and tid != self._asked[2] and (self._asked[3] or not w["sp"]):
                self._mine[w["tid"]] = tid     # what the search or the stream started (keyed its own way)
            elif now - self._asked[1] > PLAY_WAIT and self._warned != w["tid"]:
                self._warned = w["tid"]
                self.toast("could not start the song here — " + (
                    "Mild Lyrics could not stream it" if self._asked[3]
                    else "listen along plays it in Spotify, with its port open"))
            return
        here = self._in_mild()
        self._asked = (w["tid"], now, tid, here)
        self._seeks = 0                 # it starts from the top: step it in again
        if here:
            hp = self.view.homep()
            item = {"kind": "track", "name": w.get("title") or "", "sub": w.get("artist") or "",
                    "album": w.get("album") or "", "ms": int(float(w.get("len") or 0) * 1000),
                    "uri": f"spotify:track:{w['sp']}" if w["sp"] else "",
                    "yt": w.get("yt") or "", "isrc": w.get("isrc") or "",
                    "art": w["art"] if str(w.get("art") or "").startswith("https://") else ""}
            if item["name"] or item["uri"] or item["yt"]:
                # The sharer's queue comes with it, in their order: not shuffled here.
                pl = getattr(hp, "player", None)
                was = getattr(pl, "shuffle", False)
                if pl is not None:
                    pl.shuffle = False
                try:
                    hp.play_stream(item, [item] + (self.upnext() or []))
                finally:
                    if pl is not None:
                        pl.shuffle = was
        elif w["sp"]:
            self.view.fetcher.request_play(f"spotify:track:{w['sp']}")
        elif w.get("title"):
            q = f"{w['title']} {w.get('artist') or ''}".strip()
            self.view.paste_q = q
            self.view.fetcher.request_catsearch(q)

    def _in_mild(self) -> bool:
        """Whether the sharer's songs start in Mild Lyrics' own player here."""
        try:
            return self.view.homep().play_in() == "mild"
        except Exception:                            # noqa: BLE001
            return False

    # -------------------------------------------------------------- tick
    def _tick(self) -> None:
        try:
            if self.role == "host":
                self._host_tick()
            elif self.role == "hear":
                self._hear_tick()
        except Exception as e:                       # noqa: BLE001
            print(f"[listen] {type(e).__name__}: {e}", flush=True)
