"""Listen along: one player shares what it plays, others follow in their own.

Through a `Listen` room on Mild Lyrics' Worker (docs/discord-cover-worker).
Only the sharer ever sends, and only when the song, the pause or the place
changes; listeners send nothing and keep in step locally. The state is
encrypted under a key that only the invite carries. See
docs/notes/mild-lyrics/listen_along.md.
"""
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
import time

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

try:
    from PyQt6.QtWebSockets import QWebSocket, QWebSocketProtocol
    MISSING = ""
except ImportError:                                # pragma: no cover
    MISSING = "PyQt6's QtWebSockets"

import discord_presence as DP

WORKER = re.sub(r"^http", "ws", DP.ART_HOST.rstrip("/"))
INVITE = re.compile(r"(?:ml-listen:|mild-lyrics://listen/?|/l#)([A-Za-z0-9_-]{43})")
SCHEME = "mild-lyrics"
PAGE = f"{DP.ART_HOST.rstrip('/')}/l"          # the Discord button's page
KEYS = ("listen_share", "listen_join", "listen_stop")
MENU_ROWS = [
    ("Share what I play",  "listen_share", "action", None),
    ("Listen along",       "listen_join",  "action", None),
    ("Stop",               "listen_stop",  "action", None),
    ("Show on screen",     "listen_badge", "bool",   None),
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
def _now(offset: float) -> float:
    """The server's clock, in seconds, as well as we know it."""
    return time.time() + offset


class ListenAlong(QObject):
    """The window's listen along: sharing, or following someone's share."""

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
        self._sent_at = 0.0
        # listening
        self.want: dict | None = None      # the sharer's latest state
        self._got_at = 0.0
        self._asked: tuple | None = None   # (host tid, mono) of a play asked for
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
            if not self._connect(os.urandom(16).hex()):
                return
            self.role, self._last, self._seen = "host", None, None
            self.auto = auto
            self.timer.start(TICK_MS)
        if clipboard is None:
            return
        clipboard.setText(invite_text(self.secret))
        v = self.view
        on_card = getattr(v, "discord", False) and getattr(v, "discord_listen", False)
        self.toast("invite copied" + (" and on your Discord status" if on_card else "")
                   + " — anyone with it can listen along")

    def discord_url(self) -> str:
        """The Discord button's link while sharing, else ""."""
        return page_url(self.secret) if self.role == "host" else ""

    def join(self, text: str) -> bool:
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
        self._act_after = time.monotonic() + 10.0     # until the room answers
        self.timer.start(TICK_MS)
        self.toast("listening along — waiting for the song")
        return True

    def stop(self, quiet: bool = False, by_hand: bool = False) -> None:
        """`by_hand`: an automatic share stays stopped until it is toggled."""
        if by_hand and self.role == "host" and self.auto:
            self._auto_held = True
        if self.role == "host" and self.link is not None and self.link.up \
                and self.heard:
            self._send({"end": True})
        if self.link is not None:
            self.link.close()
            self.link.deleteLater()
        self.link, self.role, self.heard = None, "", 0
        self.want, self._last, self.auto = None, None, False
        self.timer.stop()
        if not quiet:
            self.toast("listen along stopped")
        self._changed()

    def _connect(self, host_key: str) -> bool:
        self.error = ("", "")
        try:
            link = Link(room_of(self.secret), host_key, self.base, self)
        except RuntimeError as e:
            self.toast(str(e))
            return False
        link.ready.connect(self._ready)
        link.got.connect(self._got)
        link.said.connect(self._room_said)
        link.failed.connect(self._failed)
        self.link = link
        return True

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
        return {"tid": st["tid"], "sp": st["spotify"] or st["spotify_match"],
                "title": st["title"], "artist": st["artist"],
                "len": round(st["length"], 2), "pos": round(st["pos"], 3),
                "on": bool(st["playing"] and st["tid"])}

    def _send(self, st: dict) -> None:
        st = {**st, "at": round(_now(self.offset), 3), "v": 1}
        blob = seal(self.secret, json.dumps(st, separators=(",", ":")).encode())
        if self.link is not None and self.link.send(blob):
            self._last = {**st, "mono": time.monotonic()}
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
        expect = last["pos"] + ((time.monotonic() - last["mono"]) if last["on"] else 0.0)
        if st["tid"] and abs(st["pos"] - expect) > JUMP:
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
        if self._host_gone_at:
            self._changed()
        self._host_gone_at = 0.0
        if st.get("end"):
            self.stop(quiet=True)
            self.toast("the sharer stopped — listen along ended")
            return
        if not all(isinstance(st.get(k), t) for k, t in (
                ("tid", str), ("sp", str), ("pos", (int, float)),
                ("at", (int, float)), ("on", bool))):
            return
        new = self.want is None or self.want["tid"] != st["tid"]
        self.want, self._got_at = st, time.monotonic()
        self._seeks, self._seek_at, self._toggle_at = 0, 0.0, 0.0
        self._end_armed = ""            # a repeat of the same song ends again
        if new:
            self._asked = None
        self._hear_tick()              # waits out _act_after by itself

    def expected(self) -> float:
        w = self.want or {}
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
        if self._host_gone_at and time.monotonic() - self._host_gone_at > HOST_WAIT:
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
        """Start the sharer's song here: by its Spotify id, else by a search
        of Spotify's catalogue, whose first track is taken as it."""
        if self._asked and self._asked[0] == w["tid"]:
            if not w["sp"] and tid and tid != self._asked[2]:
                self._mine[w["tid"]] = tid     # what the search started
            elif now - self._asked[1] > PLAY_WAIT and self._warned != w["tid"]:
                self._warned = w["tid"]
                self.toast("could not start the song here — "
                           "listen along plays it in Spotify, with its port open")
            return
        self._asked = (w["tid"], now, tid)
        self._seeks = 0                 # it starts from the top: step it in again
        if w["sp"]:
            self.view.fetcher.request_play(f"spotify:track:{w['sp']}")
        elif w.get("title"):
            q = f"{w['title']} {w.get('artist') or ''}".strip()
            self.view.paste_q = q
            self.view.fetcher.request_catsearch(q)

    # -------------------------------------------------------------- tick
    def _tick(self) -> None:
        try:
            if self.role == "host":
                self._host_tick()
            elif self.role == "hear":
                self._hear_tick()
        except Exception as e:                       # noqa: BLE001
            print(f"[listen] {type(e).__name__}: {e}", flush=True)
