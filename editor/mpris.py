"""The TTML Editor in the system's media controls (MPRIS) while it times a
local file, as org.mpris.MediaPlayer2.ttml_editor. Never offscreen or with
MILD_NO_MPRIS=1."""
from __future__ import annotations

import os

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication

import mpris_player as MP


class _Adapter:
    """The editor's player, shaped like local_player.LocalPlayer as far as Mpris reads it."""

    def __init__(self, ed) -> None:
        self.ed = ed
        self.shuffle, self.repeat = False, "off"
        self._cur: dict = {}

    @property
    def _p(self):
        return self.ed.player

    def active(self) -> bool:
        return getattr(self._p, "kind", "") == "local" and bool(self._p.audio_path())

    @property
    def queue(self) -> list:
        return [self.current] if self.active() else []

    @property
    def current(self) -> dict:
        meta = self.ed._audio_meta()
        got = {"title": meta.get("title", ""), "artist": meta.get("artist", ""),
               "album": str(self.ed.doc.meta.get("Album") or ""), "ms": self._p.duration() * 1000.0}
        if got != self._cur:
            self._cur = got                 # one dict while it says the same: Mpris keys tracks by it
        return self._cur

    @property
    def volume(self) -> float:
        return float(self._p.volume())

    def set_volume(self, v: float) -> None:
        self._p.set_volume(max(0.0, min(1.0, v)))
        if hasattr(self.ed, "sync_volume"):
            self.ed.sync_volume()

    def rate(self) -> float:
        return float(self._p.rate())

    def playing(self) -> bool:
        return bool(self._p.playing())

    def reading(self) -> dict:
        return {"pos": self._p.position(), "meta": {"length": self._p.duration()}}

    def tell(self, what: str, arg=None) -> None:
        if what == "PlayPause":
            self.ed.toggle()
        elif what == "seek":
            self.ed.seek(float(arg or 0.0))


def attach(ed):
    """Put the editor on the bus while it times a file; returns the Mpris, or None."""
    if (os.environ.get("MILD_NO_MPRIS") == "1" or not MP.available()
            or QGuiApplication.platformName() in ("offscreen", "minimal")):
        return None

    def raise_window() -> None:
        ed.showNormal()
        ed.raise_()
        ed.activateWindow()

    mp = MP.Mpris(_Adapter(ed), raise_window, name=MP.EDITOR_NAME, identity="TTML Editor",
                  desktop="ttml-editor", skips=False)
    if mp.bus is None:
        return None
    timer = QTimer(ed)
    timer.timeout.connect(lambda: _tick(mp))
    timer.start(500)
    mp._timer = timer
    return mp


def _tick(mp) -> None:
    try:
        mp.changed()
    except Exception:                                        # noqa: BLE001
        pass
