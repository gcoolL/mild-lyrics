"""Voice chat in a multiplayer session: the host is the hub, and its key goes
to each joiner inside QUIC. Joining and the microphone always ask first, every
time. Notes: docs/notes/mild-lyrics/voice.md."""
from __future__ import annotations

import base64
import secrets

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QWidget

from . import keys as K
import voice as V  # noqa: E402  (mild-lyrics/voice.py, on the path keys sets)

ASK_JOIN = ("With your microphone on, everyone in voice hears you while you "
            "speak (nothing goes out while you are quiet). Headphones keep "
            "the others from hearing themselves back. This is asked every time.")


def apply_settings(v: V.Voice) -> None:
    cfg = K.config()
    v.volume = max(0.0, min(2.0, float(cfg.get("voice_volume", 1.0) or 0.0)))
    v.sense = str(cfg.get("voice_sense") or "normal")
    v.denoise = bool(cfg.get("voice_denoise", True))


class SessionVoice(QObject):
    """The Controller's voice: made when a session starts, closed when it ends."""

    changed = pyqtSignal()

    def __init__(self, ctl) -> None:
        super().__init__(ctl)
        self.ctl = ctl
        self.v: V.Voice | None = None
        self.key = b""
        self._box: QMessageBox | None = None
        self._offered = False      # the pop-up came up by itself once for this key

    # --------------------------------------------------------- lifecycle
    def host_started(self) -> None:
        self._make(secrets.token_bytes(32), hub=True)
        self.peers()

    def member_key(self, raw) -> None:
        try:
            key = base64.b64decode(str(raw), validate=True)
        except (ValueError, TypeError):
            return
        if len(key) == 32 and key != self.key:
            self._make(key, hub=False)

    def key_msg(self) -> dict:
        return {"t": "voice", "k": base64.b64encode(self.key).decode()}

    def _make(self, key: bytes, hub: bool) -> None:
        self.close()
        self.key = key
        self._offered = False

        def send(peer, data, hub=hub):
            if self.ctl.net is not None:
                self.ctl.net.send_voice(peer if hub else None, data)
        self.v = V.Voice(key, hub, send, name=self.ctl.name(),
                         batch=hub and self.ctl.route() == "worker", parent=self)
        apply_settings(self.v)
        self.v.changed.connect(self.changed)
        self.v.opened.connect(self._opened)
        self.v.ended.connect(lambda why: self.ctl.ed.notify(f"voice chat ended — {why}"))
        self.v.failed.connect(lambda why: self.ctl.ed.notify(f"voice chat: {why}"))
        self.changed.emit()

    def got(self, cid: int, data: bytes) -> None:
        if self.v is not None:
            self.v.got(cid if self.v.hub else None, data)

    def peers(self) -> None:
        """Host: who the hub may hear from and tells the roster to."""
        s = self.ctl.session
        if self.v is None or not self.v.hub or s is None or s.role != "host":
            return
        self.v.set_peers({pid: p["n"] for pid, p in s.peers.items()
                          if pid != 0 and "voice" in s.can.get(pid, ())})

    def close(self, why: str = "") -> None:
        if self._box is not None:
            self._box.close()
            self._box = None
        if self.v is not None:
            self.v.close(why or "the session ended")
            self.v.deleteLater()
            self.v = None
            self.changed.emit()
        self.key = b""

    def settings_changed(self) -> None:
        if self.v is not None:
            apply_settings(self.v)

    # ------------------------------------------------------------ asking
    def _opened(self, who: str) -> None:
        """Somebody is in voice: ask once a voice chat; after that the row's button asks."""
        if not self._offered:
            self._offered = True
            self.ask_join(who)

    def ask_join(self, who: str = "") -> None:
        """The permission pop-up: join with the microphone, listen only, or not."""
        if self.v is None or self.v.on or self._box is not None:
            return
        box = QMessageBox(self.ctl.ed)
        box.setWindowTitle("Voice chat")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"{who} is in voice chat. Join?" if who else "Join the voice chat?")
        box.setInformativeText(ASK_JOIN)
        mic = box.addButton("Join with microphone", QMessageBox.ButtonRole.AcceptRole)
        ear = box.addButton("Listen only", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(ear)

        def done(button):
            self._box = None
            if self.v is None:
                return
            if button is mic:
                self.v.join(mic=True)
            elif button is ear:
                self.v.join(mic=False)
        box.buttonClicked.connect(done)
        box.finished.connect(lambda _r: setattr(self, "_box", None))
        self._box = box
        box.open()

    def ask_mic(self) -> None:
        if self.v is None or not self.v.on or self.v.mic or self._box is not None:
            return
        if self.v.mic_ok:
            self.v.set_mic(True)                 # allowed once already, this time in voice
            return
        box = QMessageBox(self.ctl.ed)
        box.setWindowTitle("Voice chat")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("Turn your microphone on?")
        box.setInformativeText("Everyone in voice will hear you while you speak.")
        yes = box.addButton("Turn it on", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Keep it off", QMessageBox.ButtonRole.RejectRole)

        def done(button):
            self._box = None
            if button is yes and self.v is not None:
                self.v.set_mic(True)
        box.buttonClicked.connect(done)
        box.finished.connect(lambda _r: setattr(self, "_box", None))
        self._box = box
        box.open()

    # ------------------------------------------------------------- shown
    def said(self) -> str:
        v = self.v
        if v is None:
            return "Voice chat: not available in this session"
        rows = v.who()
        if not rows:
            return "Voice chat: nobody in yet"
        bits = []
        for r in rows:
            name = "you" if r["me"] else r["n"]
            bits.append(name + (" 🔊" if r["talk"] else "") + ("" if r["mic"] else " (listening)"))
        return "Voice chat: " + ", ".join(bits)


class VoiceRow(QWidget):
    """The session page's voice line: who is in, and the two buttons."""

    def __init__(self, sv: SessionVoice) -> None:
        super().__init__()
        self.sv = sv
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("")
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        lay.addWidget(self.label, 1)
        self.join_btn = QPushButton("Join voice…")
        self.join_btn.clicked.connect(self._join)
        lay.addWidget(self.join_btn)
        self.mic_btn = QPushButton("Microphone on…")
        self.mic_btn.clicked.connect(self._mic)
        lay.addWidget(self.mic_btn)
        sv.changed.connect(self.refresh)
        self.refresh()

    def _join(self) -> None:
        v = self.sv.v
        if v is None:
            return
        if v.on:
            v.leave()
        else:
            self.sv.ask_join()

    def _mic(self) -> None:
        v = self.sv.v
        if v is None or not v.on:
            return
        if v.mic:
            v.set_mic(False)
        else:
            self.sv.ask_mic()

    def refresh(self) -> None:
        v = self.sv.v
        self.label.setText(self.sv.said())
        self.join_btn.setEnabled(v is not None)
        self.join_btn.setText("Leave voice" if v is not None and v.on else "Join voice…")
        self.mic_btn.setVisible(v is not None and v.on)
        self.mic_btn.setText("Mute" if v is not None and v.mic else
                             "Unmute" if v is not None and v.mic_ok else "Microphone on…")
