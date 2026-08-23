"""The editor's end of the live link to a running Mild Lyrics.

One socket, four messages, and a reconnect timer. Everything is asynchronous:
the player is a GUI too, and an editor that blocks on it would stutter exactly
when the user is tapping times.

What travels over it is the whole document, every time. TTML for a long song
is some tens of kilobytes over loopback, which is nothing next to the cost of
being clever -- a patch protocol would have to agree with the player about
what a line is, and the two would drift the first time either changed.
"""
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

    def __init__(self, parent=None, port: int = PORT) -> None:
        super().__init__(parent)
        self.port = port
        self.sock = QTcpSocket(self)
        self.sock.connected.connect(lambda: self.connected.emit(True))
        self.sock.readyRead.connect(self._read)
        self.sock.errorOccurred.connect(lambda _e: self.connected.emit(False))
        self.sock.disconnected.connect(lambda: self.connected.emit(False))
        self._buf = ""
        self._pending = ""
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
        self._buf += bytes(self.sock.readAll()).decode("utf-8", "replace")
        while "\n" in self._buf:
            row, self._buf = self._buf.split("\n", 1)
            if not row.strip():
                continue
            try:
                got = json.loads(row)
            except Exception:
                continue
            if not isinstance(got, dict):
                continue
            if "ttml" in got:
                self.doc.emit(got)
                continue
            if "pos" in got:
                self.last_state = got
                self.last_at = time.monotonic()
                self.state.emit(got)
            elif got.get("ok") is False:
                self.refused.emit(str(got.get("why") or "refused"))

    # -------------------------------------------------------------- the four
    def ask_state(self) -> None:
        self._send({"cmd": "state"})

    def ask_doc(self) -> bool:
        """Ask for the lyrics the player currently has on screen."""
        return self._send({"cmd": "doc"})

    def push(self, ttml: str, tid: str = "", name: str = "the editor") -> bool:
        """Put this document on the player's screen.

        A document that could not be sent is kept, not dropped: the player is
        usually a second away from being back, and the next push -- or the
        reconnect -- carries the newest version of the file rather than
        leaving the screen a few edits behind.
        """
        self._pending = ""
        if not self._send({"cmd": "ttml", "ttml": ttml, "tid": tid, "name": name}):
            self._pending = ttml
            self._tid, self._name = tid, name
            return False
        return True

    def release(self) -> None:
        self._send({"cmd": "clear"})

    def seek(self, pos: float) -> bool:
        return self._send({"cmd": "seek", "pos": float(pos)})

    def close(self) -> None:
        """Stop dialling and let the socket go. Safe to call twice."""
        self.retry.stop()
        try:
            self.sock.abort()
        except Exception:
            pass

    def flush(self) -> None:
        """Send whatever a lost connection left behind.

        Called on every state tick as well as on reconnect: a push that could
        not go out is the one thing here the user cannot see has failed, and
        waiting for the next edit to carry it is how a document ends up on
        screen one version behind.
        """
        if self._pending and self.alive():
            self.push(self._pending, getattr(self, "_tid", ""),
                      getattr(self, "_name", "the editor"))
