"""The editor's end of the live link to a running Mild Lyrics: one socket, five
messages, a reconnect timer, the whole document each time. Never blocks."""
from __future__ import annotations

import json
import os
import time

from PyQt6.QtCore import QCoreApplication, QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QAbstractSocket, QHostAddress, QTcpSocket

PORT = int(os.environ.get("MILD_LYRICS_LINK_PORT", "8778") or 0)


class Link(QObject):
    """A connection that keeps trying, and says what the player is doing."""

    state = pyqtSignal(dict)
    refused = pyqtSignal(str)
    doc = pyqtSignal(dict)
    connected = pyqtSignal(bool)
    asked = pyqtSignal(dict)

    def __init__(self, parent=None, port: int = PORT) -> None:
        super().__init__(parent)
        self.port = port
        self.sock = QTcpSocket(self)
        self.sock.connected.connect(lambda: self.connected.emit(True))
        self.sock.readyRead.connect(self._read)
        self.sock.errorOccurred.connect(lambda _e: self.connected.emit(False))
        self.sock.disconnected.connect(lambda: self.connected.emit(False))
        self._buf = b""
        self._pending = ""
        self._want_doc = False
        self.last_state: dict = {}
        self.last_at = 0.0
        self.retry = QTimer(self)
        self.retry.timeout.connect(self._dial)
        self.retry.start(2000)
        self._dial()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.close)

    # ------------------------------------------------------------- plumbing
    def alive(self) -> bool:
        return self.sock.state() == QAbstractSocket.SocketState.ConnectedState

    def _dial(self) -> None:
        if self.sock.state() == QAbstractSocket.SocketState.UnconnectedState:
            self.sock.abort()
            self.sock.connectToHost(QHostAddress("127.0.0.1"), self.port)

    def _send(self, msg: dict) -> bool:
        if not self.alive():
            return False
        try:
            self.sock.write((json.dumps(msg) + "\n").encode("utf-8"))
            return True
        except Exception:
            return False

    def _read(self) -> None:
        """Whole lines only, decoded only once whole: the buffer holds bytes,
        so a character split across segments is not mangled."""
        new = bytes(self.sock.readAll())
        self._buf += new
        try:                                            # TEMPORARY follow log
            import lyrics_gui as L
            L.follow_log("editor", "sock-read", bytes=len(new),
                         held=len(self._buf))
        except Exception:                               # noqa: BLE001
            pass
        while b"\n" in self._buf:
            row, self._buf = self._buf.split(b"\n", 1)
            text = row.decode("utf-8", "replace")
            if not text.strip():
                continue
            try:
                got = json.loads(text)
            except Exception:
                continue
            if not isinstance(got, dict):
                continue
            if got.get("ev") and "ok" not in got:
                # Something done in the player for the file being timed
                # here: a seek or a pause made over there.
                self.asked.emit(got)
                continue
            if "ttml" in got:
                self._want_doc = False
                self.doc.emit(got)
                continue
            if "pos" in got:
                self.last_state = got
                self.last_at = time.monotonic()
                self.state.emit(got)
            elif got.get("ok") is False and self._want_doc:
                self._want_doc = False
                self.doc.emit(got)
            elif got.get("ok") is False:
                self.refused.emit(str(got.get("why") or "refused"))

    # -------------------------------------------------------------- the four
    def ask_state(self) -> None:
        self._send({"cmd": "state"})

    def ask_doc(self, own: bool = True) -> bool:
        """Ask the player for lyrics. `own` asks for the song's own document
        rather than the screen (which may be ours); older players need the
        `doc` fallback."""
        self._want_doc = True
        return self._send({"cmd": "source_doc" if own else "doc"})

    def push(self, ttml: str, tid: str = "", name: str = "the editor") -> bool:
        """Put this document on the player's screen; one that could not be sent
        is kept for the next push or reconnect."""
        self._pending = ""
        if not self._send({"cmd": "ttml", "ttml": ttml, "tid": tid, "name": name}):
            self._pending = ttml
            self._tid, self._name = tid, name
            return False
        return True

    def follow(self, pos: float, playing: bool, rate: float = 1.0,
               held: bool = False) -> bool:
        """Tell the player where the local audio being timed against is, at
        what speed, and when that was true (perf_counter). Only while timing
        against a file."""
        return self._send({"cmd": "follow", "pos": float(pos),
                           "playing": bool(playing), "rate": float(rate),
                           "held": bool(held), "at": time.perf_counter()})

    def unfollow(self) -> bool:
        """Stop walking the player along, and give it back."""
        return self._send({"cmd": "follow", "stop": True})

    def release(self) -> None:
        self._send({"cmd": "clear"})

    def seek(self, pos: float) -> bool:
        return self._send({"cmd": "seek", "pos": float(pos)})

    def discord(self, on: bool) -> bool:
        """Whether this editor's Discord card is up; the player's gives way
        while it is, and when this connection closes it comes back."""
        return self._send({"cmd": "discord", "on": bool(on)})

    def control(self, name: str) -> bool:
        """PlayPause, Next or Previous, done by the player (Mild Lyrics' own, being followed)."""
        return self._send({"cmd": "control", "name": name})

    def volume(self, v: float) -> bool:
        """Set Spotify's volume through the player, which owns it: it may
        have muted Spotify itself (see its follow_editor), and a level set
        behind its back was either undone by it or undid it."""
        return self._send({"cmd": "volume", "volume": float(v)})

    def wait_sent(self, ms: int = 200) -> None:
        """Let what is queued actually leave before the process does.

        Written out rather than pumped through the event loop: doing that
        from inside closeEvent re-enters Qt while the window is being taken
        apart, which aborts the process instead of ending it.
        """
        try:
            if self.alive():
                self.sock.flush()
                self.sock.waitForBytesWritten(int(ms))
        except Exception:
            pass

    def close(self) -> None:
        """Stop dialling and let the socket go. Safe to call twice."""
        self.retry.stop()
        try:
            self.sock.abort()
        except Exception:
            pass

    def flush(self) -> None:
        """Send whatever a lost connection left behind. Called on every state
        tick as well as on reconnect."""
        if self._pending and self.alive():
            self.push(self._pending, getattr(self, "_tid", ""),
                      getattr(self, "_name", "the editor"))
