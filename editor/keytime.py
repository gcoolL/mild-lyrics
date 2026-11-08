"""How long a key waited before the editor read it, from the press time the
platform puts on the event: a tap read while the window was busy is moved
back by that much. Notes: docs/notes/editor/keytime.md."""
from __future__ import annotations

import collections
import sys
import time

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication

# Below this a wait is noise (event clocks tick in whole ms, 15.6ms on
# Windows); above it the tap is moved back.
QUIET_MS = 20.0
# Windows' event clock ticks every 15.6ms: half a tick is the honest middle.
SLACK_MS = 8.0 if sys.platform == "win32" else 0.0
CALIBRATE = 5               # presses seen before any correction
WINDOW_S = 120.0            # how far back the quickest press is looked for
FRESH_MS = 50.0             # a reading older than this is not this key's
MAX_MS = 1000.0             # a longer "wait" is a clock fault, not a wait

_KEYS = (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)


class KeyClock(QObject):
    """Watches the focused widget's key events (a shortcut is decided on its
    ShortcutOverride, before any window sees the press)."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self._on: list = []
        self._seen: collections.deque = collections.deque(maxlen=256)
        self._last_ts = None
        self._wait = None
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._focus)
            self._focus(None, app.focusWidget())

    def _focus(self, _old, new) -> None:
        for o in self._on:
            try:
                o.removeEventFilter(self)
            except RuntimeError:            # already deleted
                pass
        self._on = []
        handle = self._window.windowHandle()
        for o in (new, handle):
            if o is not None:
                o.installEventFilter(self)
                self._on.append(o)

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt name)
        if ev.type() in _KEYS and not ev.isAutoRepeat():
            self.seen(ev.timestamp(), time.perf_counter() * 1000.0)
        return False

    def seen(self, ts: int, now_ms: float) -> None:
        """A press stamped `ts` (the platform's ms) read at `now_ms`."""
        if not ts:
            self._wait = None
            return
        if self._last_ts is not None and ts < self._last_ts - MAX_MS:
            self._seen.clear()              # the event clock was reset
        self._last_ts = max(ts, self._last_ts or ts)
        gap = now_ms - ts
        while self._seen and now_ms - self._seen[0][0] > WINDOW_S * 1000.0:
            self._seen.popleft()
        self._seen.append((now_ms, gap))
        if len(self._seen) < CALIBRATE:
            self._wait = None
            return
        wait = gap - min(g for _t, g in self._seen)
        self._wait = (now_ms, wait) if 0.0 <= wait <= MAX_MS else None

    def waited(self, now_ms: float | None = None) -> float:
        """Seconds the key being handled right now waited; 0 when it did not
        wait long enough to matter, or nothing says how long."""
        got, self._wait = self._wait, None
        if got is None:
            return 0.0
        now_ms = time.perf_counter() * 1000.0 if now_ms is None else now_ms
        at, wait = got
        if now_ms - at > FRESH_MS or wait <= QUIET_MS:
            return 0.0
        return (wait - SLACK_MS) / 1000.0
