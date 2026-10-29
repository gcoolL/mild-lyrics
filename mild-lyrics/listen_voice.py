"""Voice chat beside a listen along. The sharer hosts a voice room on the relay
(the TTML Editor's Room, unchanged); its id rides in the sealed state, and the
key comes from the listen-along secret. Notes: docs/notes/mild-lyrics/voice.md."""
from __future__ import annotations

import os
import re

from PyQt6.QtCore import QObject, pyqtSignal

import voice as V

ROOM = re.compile(r"[0-9a-f]{32}\Z")


def _ws():
    from editor import collab_ws as WS
    return WS


class ListenVoice(QObject):
    """The listen along's voice: hub for the sharer, member for a listener."""

    changed = pyqtSignal()

    def __init__(self, la) -> None:
        super().__init__(la)
        self.la = la
        self.v: V.Voice | None = None
        self.link = None
        self.room = ""             # the voice room in use
        self.offered = ""          # a listener: the room last asked about

    def key(self) -> bytes:
        import listen_along as LN
        return LN._derive(self.la.secret, b"voice", 32)

    def base(self) -> str:
        import listen_along as LN
        return (self.la.base or LN.WORKER).rstrip("/")

    # -------------------------------------------------------------- open
    def start(self, mic: bool, name: str) -> str:
        """Sharer: open a voice room and be in it. Asked for by then."""
        if self.la.role != "host":
            return "share first — voice chat goes with listen along"
        if self.v is not None:
            self.v.join(mic)
            return ""
        WS = _ws()
        if WS.MISSING:
            return f"voice chat needs {WS.MISSING}"
        room = os.urandom(16).hex()
        link = WS.RoomLink(self.base(), room, os.urandom(16).hex(), self)
        v = self._make(True, name, lambda mid, d: link.send(d, WS.address(mid)))
        link.got.connect(lambda d, a: v.got(_mid(a), d))
        link.gone.connect(lambda a: v.peer_gone(_mid(a)))
        link.failed.connect(lambda why: self.stop(f"the relay refused it ({why})"))
        self.link, self.room = link, room
        v.join(mic)
        self.la._last = None               # the state carries the room: send it now
        self.la._changed()
        return ""

    def offer(self, room) -> None:
        """Listener: the sharer's state names a voice room (or none)."""
        room = room if isinstance(room, str) and ROOM.match(room) else ""
        if not room:
            self.offered = ""
            if self.v is not None:
                self.stop("the sharer closed voice chat")
            return
        if room == self.room or room == self.offered:
            return
        self.offered = room
        ask = getattr(self.la.view, "voice_ask", None)
        if ask is not None:
            ask("The sharer opened voice chat", lambda mic, name: self.join(room, mic, name))

    def join(self, room: str, mic: bool, name: str) -> str:
        if self.la.role != "hear" or not ROOM.match(room or ""):
            return "not listening along"
        WS = _ws()
        if WS.MISSING:
            return f"voice chat needs {WS.MISSING}"
        self.stop(quiet=True)
        link = WS.RoomLink(self.base(), room, "", self)
        v = self._make(False, name, lambda _p, d: link.send(d, WS.HOST))
        link.got.connect(lambda d, _a: v.got(None, d))
        link.failed.connect(lambda why: self.stop(f"the relay refused it ({why})"))
        self.link, self.room = link, room
        v.join(mic)
        return ""

    def _make(self, hub: bool, name: str, send) -> V.Voice:
        v = self.v = V.Voice(self.key(), hub, send, name=name, batch=True, parent=self)
        view = self.la.view
        v.volume = float(getattr(view, "voice_volume", 1.0) or 0.0)
        v.denoise = bool(getattr(view, "voice_denoise", True))
        v.sense = str(getattr(view, "voice_sense", "normal") or "normal")
        v.changed.connect(self._changed)
        v.opened.connect(lambda who: self.la.toast(f"{who} joined voice chat"))
        v.ended.connect(lambda why: self.stop(why))
        v.failed.connect(lambda why: self.la.toast(f"voice chat: {why}"))
        return v

    def _changed(self) -> None:
        self.changed.emit()
        self.la._changed()

    # ------------------------------------------------------------- close
    def stop(self, why: str = "", quiet: bool = False) -> None:
        v, link = self.v, self.link
        self.v, self.link, self.room = None, None, ""
        if v is not None:
            v.close(why or "voice chat ended")
            v.deleteLater()
        if link is not None:
            link.close()
            link.deleteLater()
        if v is not None and self.la.role == "host":
            self.la._last = None           # the room is gone from the state
        if v is not None and not quiet:
            self.la.toast(f"voice chat ended — {why}" if why else "voice chat ended")
        self._changed()

    def leave(self) -> None:
        """Out of voice; the sharer's leaving closes the room for everyone."""
        if self.la.role == "host":
            self.stop("the sharer left voice chat")
        else:
            self.stop("you left", quiet=True)
            self.la.toast("left voice chat")

    # ------------------------------------------------------------- shown
    def said(self) -> str:
        v = self.v
        if v is None:
            if self.la.role == "hear" and self.offered:
                return "open · not joined"
            return "off"
        rows = v.who()
        talking = [("you" if r["me"] else r["n"]) for r in rows if r["talk"]]
        out = f"{len(rows)} in voice"
        return out + (f" · {', '.join(talking)} talking" if talking else "")

    def look(self) -> tuple[str, bool]:
        if self.v is not None:
            return "Leave", False
        if self.la.role == "host":
            return "Start…", False
        if self.la.role == "hear":
            return "Join…", not self.offered
        return "Start…", True

    def mic_said(self) -> str:
        if self.v is None:
            return "off"
        return "on" + (" · talking" if self.v.talking() else "") if self.v.mic else "muted"

    def mic_look(self) -> tuple[str, bool]:
        if self.v is None:
            return "Turn on…", True
        if self.v.mic:
            return "Mute", False
        return ("Unmute" if self.v.mic_ok else "Turn on…"), False


def _mid(addr) -> int:
    try:
        return int(str(addr[0])[2:])
    except (ValueError, TypeError, IndexError):
        return -1
