"""A window's animation stepped once per refresh: frame callbacks where the
platform paces them, a PreciseTimer elsewhere; `now()` sits on the refresh
grid."""
from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtWidgets import QApplication

WAIT_MS = 50          # the timer behind a frame callback that never comes
IDLE_HZ = 30.0        # nothing moving: what the editor always ran at
HIDDEN_HZ = 10.0
WOKEN_FOR = 1.0       # seconds of full rate after any input

WAKE_EVENTS = frozenset({
    QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease, QEvent.Type.Wheel, QEvent.Type.KeyPress,
    QEvent.Type.KeyRelease, QEvent.Type.Resize})


def mono() -> float:
    """The one clock every elapsed-time reading in both programs uses: NOT
    time.monotonic, which moves in 15.6ms steps on Windows under CPython 3.12
    and earlier. Why: docs/notes/mild-lyrics/frame_clock.md."""
    return time.perf_counter()


# A callback this soon after the last one, in refreshes, has no refresh
# behind it. KWin's real ones were measured 3ms apart at the closest, at 240Hz.
NO_REFRESH = 0.25


def grid_step(ft, last_cb, now: float, period: float) -> tuple:
    """(frame time, last callback) for a callback at `now`: whole refreshes
    counted from the last callback; an instant answer counts nothing; kept
    near the wall clock."""
    if ft is None or last_cb is None or not 0.0 <= now - last_cb < 8 * period:
        return now, now
    if now - last_cb < NO_REFRESH * period:
        return ft, last_cb
    n = max(1, round((now - last_cb) / period))
    ft += n * period
    ahead = ft - now
    if ahead > 1.5 * period:
        ft -= period * max(1, round((ahead - 0.5 * period) / period))
    elif ahead < -period:
        ft += period * max(1, round(-ahead / period))
    return ft, now


# Callbacks to hear before naming the screen they come from, and how far off
# a screen's period they can run and still be taken for it.
HEARD_AFTER = 32
HEARD_NEAR = 0.1


def heard_refresh(gaps, rates, current: float) -> float | None:
    """The refresh the compositor is calling back at, where plainly not
    `current`, from the middle half of the callback `gaps`; None when they
    agree or cannot tell."""
    gaps = sorted(g for g in gaps if g > 0)
    if len(gaps) < HEARD_AFTER or current <= 0:
        return None
    q = len(gaps) // 4
    mid = gaps[q:len(gaps) - q]
    gap = sum(mid) / len(mid)
    if abs(gap * current - 1.0) <= HEARD_NEAR:
        return None
    rates = [r for r in rates if r > 0]
    near = [r for r in rates if abs(gap * r - 1.0) <= HEARD_NEAR]
    if near:
        best = min(near, key=lambda r: abs(gap * r - 1.0))
    elif gap * current >= 1.0 - HEARD_NEAR:
        return None
    else:
        could = [r for r in rates if gap * r >= 1.0 - HEARD_NEAR]
        if not could:
            return None
        best = min(could)
    return None if abs(best - current) < 0.5 else best


class FrameClock(QObject):
    """Calls `step()` once per refresh while `busy()` says something moves.

    `window` is the top-level widget the frames are shown in. Read `now()`
    inside a step for the time that step is for.
    """

    def __init__(self, window, step, busy=None, cap: float = 0.0) -> None:
        super().__init__(window)
        self.window = window
        self.step = step
        self.busy = busy or (lambda: True)
        self.cap = cap
        self.hz = 60.0
        self._ft = None
        self._cb = None
        self._floor = 0.0
        self._live = False
        self._handle = None
        self._screen = None
        self._woke = 0.0
        self._due = mono()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timer_step)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ------------------------------------------------------------- reading
    def now(self) -> float:
        t = self._ft if self._ft is not None else mono()
        if t < self._floor:
            t = self._floor
        self._floor = t
        return t

    def lag(self) -> float:
        """How far the frame's time is from this moment: what to add to a
        clock read now to have it at the frame's time."""
        return self.now() - mono()

    # ------------------------------------------------------------- running
    def start(self) -> None:
        self._due = mono()
        self.timer.start(0)

    def stop(self) -> None:
        self.timer.stop()
        self._live = False

    def wake(self) -> None:
        """Something happened: full rate for a while, starting now."""
        self._woke = mono()
        if self._live:
            return
        if self.timer.remainingTime() > 1000.0 / max(1.0, self.hz) + 2.0:
            self._due = mono()
            self.timer.start(0)

    def _hook(self) -> None:
        """Follow the window's native handle and screen, which change."""
        wh = self.window.windowHandle()
        if wh is not None and wh is not self._handle:
            self._live = False
            self._handle = wh
            wh.installEventFilter(self)
            wh.screenChanged.connect(lambda *_: self._retune())
        scr = self.window.screen()
        if scr is not self._screen:
            self._screen = scr
            self._retune()

    def _retune(self) -> None:
        scr = self.window.screen() or QApplication.primaryScreen()
        hz = scr.refreshRate() if scr is not None else 0.0
        self.hz = hz if hz > 0 else 60.0

    def _showing(self) -> bool:
        w = self.window
        if w.isHidden() or w.isMinimized():
            return False
        wh = w.windowHandle()
        return wh is None or wh.isExposed()

    def rate(self) -> float:
        if not self._showing():
            return HIDDEN_HZ
        full = min(self.hz, self.cap) if self.cap > 0 else self.hz
        if self.busy() or mono() - self._woke < WOKEN_FOR:
            return full
        return min(full, IDLE_HZ)

    def _vsync_ok(self) -> bool:
        # Only while something moves: a step that repaints nothing commits
        # nothing, and Qt answers requestUpdate at once -- see grid_step.
        return (self._handle is not None
                and self._handle is self.window.windowHandle()
                and QApplication.platformName().startswith("wayland")
                and abs(self.rate() - self.hz) < 0.5
                and self.busy())

    def _arm(self) -> None:
        self._hook()
        if self._vsync_ok():
            self._live = True
            self._handle.requestUpdate()
            self.timer.start(WAIT_MS)
            return
        self._live = False
        self._ft = None
        period = 1.0 / max(1.0, self.rate())
        self._due += period
        delay = self._due - mono()
        if delay < -period:
            self._due = mono() + period
            delay = period
        self.timer.start(max(0, round(delay * 1000)))

    def _timer_step(self) -> None:
        self._ft = None
        try:
            self.step()
        finally:
            self._arm()

    def _vsync_step(self) -> None:
        """One step on the frame callback, timed on the refresh grid."""
        self._live = False
        self._ft, self._cb = grid_step(self._ft, self._cb, mono(),
                                      1.0 / max(1.0, self.hz))
        try:
            self.step()
        finally:
            self._arm()

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt name)
        kind = ev.type()
        if kind == QEvent.Type.UpdateRequest:
            if self._live and obj is self._handle:
                self._vsync_step()
                # Ours, so it stops here: let through, Qt repaints the whole
                # top-level widget on every step.
                return True
        elif kind in WAKE_EVENTS:
            self.wake()
        return False
