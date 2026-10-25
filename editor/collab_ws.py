"""The way through Mild Lyrics' relay: one WebSocket to a room on the Worker,
carrying the editors' end-to-end QUIC; nobody learns another's address."""
from __future__ import annotations

import json
import struct

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal

try:
    from PyQt6.QtNetwork import QAbstractSocket
    from PyQt6.QtWebSockets import QWebSocket, QWebSocketProtocol
    MISSING = ""
except ImportError:                                # pragma: no cover
    MISSING = "PyQt6's QtWebSockets"

FLUSH_MS = 15             # how long a datagram waits for others to go with it
FRAME_MAX = 60000         # bytes in one message (the room takes 64 KiB)
OPEN_WAIT_MS = 15000      # how long a connection may take to open
BACK_OFF = (1, 2, 4, 8, 15)   # seconds between tries after a drop
PING_MS = 25000           # protocol pings: free, and keep proxies from closing it
FLOODED = 4029            # the room closed us for sending far too much: stay out

HOST = ("w:host", 0)


def address(mid: int) -> tuple[str, int]:
    return (f"w:{int(mid)}", 0)


def is_ours(addr) -> bool:
    return isinstance(addr, tuple) and isinstance(addr[0], str) \
        and addr[0].startswith("w:")


def _pack(datagrams: list[bytes]) -> bytes:
    return b"".join(struct.pack("!H", len(d)) + d for d in datagrams)


def _unpack(body: bytes) -> list[bytes]:
    out, at = [], 0
    while at + 2 <= len(body):
        n = struct.unpack("!H", body[at:at + 2])[0]
        if at + 2 + n > len(body):
            break                   # cut short: keep what was whole
        out.append(body[at + 2:at + 2 + n])
        at += 2 + n
    return out


class RoomLink(QObject):
    """One editor's WebSocket to one room. Signals `ready`, `got`, `failed`,
    `lost` (then retries by itself) and `gone(addr)`."""

    ready = pyqtSignal()
    got = pyqtSignal(bytes, object)
    failed = pyqtSignal(str)
    lost = pyqtSignal(str)
    gone = pyqtSignal(object)       # the room says this address's socket closed

    def __init__(self, base: str, room: str, host_key: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        if MISSING:
            raise RuntimeError(f"the relay needs {MISSING}")
        self.base = base.rstrip("/")
        self.room = room
        self.host_key = host_key
        self.is_host = bool(host_key)
        self.mid: int | None = None
        self.closed = False
        self.opened_once = False
        self._tries = 0
        self._queue: dict[int, list[bytes]] = {}
        self.sent = self.received = 0       # messages, for measuring use
        self._flush = QTimer(self)
        self._flush.setSingleShot(True)
        self._flush.timeout.connect(self._send_queued)
        self._open_timer = QTimer(self)
        self._open_timer.setSingleShot(True)
        self._open_timer.timeout.connect(self._open_late)
        self._ping = QTimer(self)
        self._ping.timeout.connect(self._pinged)
        self.ws = None
        self._open()

    # ------------------------------------------------------------ opening
    def _url(self) -> QUrl:
        q = f"as=host&k={self.host_key}" if self.is_host else "as=join"
        return QUrl(f"{self.base}/room/{self.room}?{q}")

    def _open(self) -> None:
        ws = QWebSocket("", QWebSocketProtocol.Version.VersionLatest, self)
        ws.textMessageReceived.connect(self._text)
        ws.binaryMessageReceived.connect(self._binary)
        ws.disconnected.connect(lambda w=ws: self._dropped(w))
        ws.errorOccurred.connect(lambda _e, w=ws: self._error(w))
        self.ws = ws
        self.mid = None
        self._open_timer.start(OPEN_WAIT_MS)
        ws.open(self._url())

    def _open_late(self) -> None:
        if self.mid is None and not self.closed:
            self._give_up(self.ws, "the relay did not answer in "
                          f"{OPEN_WAIT_MS // 1000}s")

    def _error(self, ws) -> None:
        if ws is self.ws and not self.closed and self.mid is None:
            self._give_up(ws, ws.errorString() or "the relay could not be reached")

    def _give_up(self, ws, why: str) -> None:
        """It did not open. The first time, that is the end of it; after a
        session was running, it is one more try gone."""
        if ws is not self.ws or self.closed:
            return
        self._open_timer.stop()
        self.ws = None
        ws.abort()
        ws.deleteLater()
        if not self.opened_once:
            self.closed = True
            self.failed.emit(why)
        else:
            self._retry(why)

    def _text(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if not isinstance(msg, dict):
            return
        if msg.get("t") == "gone":
            m = msg.get("m")
            if isinstance(m, int) and not isinstance(m, bool) and m >= 0:
                self.gone.emit(HOST if m == 0 else address(m))
            return
        if msg.get("t") != "you":
            return
        m = msg.get("m")
        if not isinstance(m, int) or isinstance(m, bool) or m < 0:
            return
        self.mid = m
        self._open_timer.stop()
        self._tries = 0
        self._ping.start(PING_MS)
        self.opened_once = True
        self.ready.emit()
        if self._queue:
            self._flush.start(0)

    # ---------------------------------------------------------- dropping
    def _dropped(self, ws) -> None:
        if ws is not self.ws or self.closed:
            return
        why = ws.closeReason() or "the connection to the relay closed"
        if self.mid is None and not self.opened_once:
            self._give_up(ws, why)
            return
        code = ws.closeCode()
        if getattr(code, "value", code) == FLOODED:
            # Coming back would only start the same flood over, counted
            # against everybody's day: this editor's session ends here.
            self.ws = None
            ws.deleteLater()
            self._ping.stop()
            self.mid = None
            self.closed = True
            self.lost.emit(f"flooded: {why}")
            return
        self.ws = None
        ws.deleteLater()
        self._ping.stop()
        self.mid = None
        self.lost.emit(why)
        self._retry(why)

    def _retry(self, why: str) -> None:
        if self.closed:
            return
        wait = BACK_OFF[min(self._tries, len(BACK_OFF) - 1)]
        self._tries += 1
        QTimer.singleShot(wait * 1000, lambda: None if self.closed or self.ws
                          is not None else self._open())

    def _pinged(self) -> None:
        if self.ws is not None and self.mid is not None:
            self.ws.ping(b"")

    # ------------------------------------------------------------ traffic
    def _binary(self, body) -> None:
        body = bytes(body)
        self.received += 1
        if self.is_host:
            if len(body) < 4:
                return
            mid = struct.unpack("!I", body[:4])[0]
            frm, body = address(mid), body[4:]
        else:
            frm = HOST
        for d in _unpack(body):
            if d:
                self.got.emit(d, frm)

    def send(self, data: bytes, addr) -> None:
        """Queue a datagram for `addr` ("w:host" or "w:<n>"); it goes within
        FLUSH_MS, with whatever else was sent meanwhile."""
        if self.closed or not data or len(data) > 65535:
            return
        if self.is_host:
            try:
                to = int(addr[0][2:])
            except (ValueError, TypeError):
                return
        else:
            to = 0
        self._queue.setdefault(to, []).append(bytes(data))
        if self.mid is not None and not self._flush.isActive():
            self._flush.start(FLUSH_MS)

    def _send_queued(self) -> None:
        ws = self.ws
        if ws is None or self.mid is None:
            return
        queue, self._queue = self._queue, {}
        for to, datagrams in queue.items():
            batch, size = [], 0
            for d in datagrams:
                if batch and size + 2 + len(d) > FRAME_MAX:
                    self._frame(ws, to, batch)
                    batch, size = [], 0
                batch.append(d)
                size += 2 + len(d)
            if batch:
                self._frame(ws, to, batch)

    def _frame(self, ws, to: int, batch: list[bytes]) -> None:
        body = _pack(batch)
        if self.is_host:
            body = struct.pack("!I", to) + body
        ws.sendBinaryMessage(body)
        self.sent += 1

    def flush(self) -> None:
        """Send what is queued now, not FLUSH_MS from now: on the way out."""
        self._flush.stop()
        self._send_queued()
        if self.ws is not None:
            self.ws.flush()

    def close(self) -> None:
        if self.closed:
            return
        self.flush()
        self.closed = True
        self._flush.stop()
        self._ping.stop()
        self._open_timer.stop()
        if self.ws is not None:
            self.ws.close()
            self.ws = None
