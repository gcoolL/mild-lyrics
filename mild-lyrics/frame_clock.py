"""A window's animation, stepped once per refresh of the screen it is on.

The same pacing LyricsView does for itself (see its _vsync_frame), made a
thing a window can hold, for the TTML Editor. Two halves:

When it steps. Where the platform paces frames -- Wayland, whose compositor
answers QWindow.requestUpdate from its frame callback -- each step asks for
the next, and so runs once per refresh. Everywhere else, and whenever the
window is idle or hidden, a PreciseTimer re-armed against a deadline carried
in float seconds. The timer alone was measured at 240Hz sending frames 6.5,
4, 3, 3ms apart to a panel that shows one every 4.17: right on average and
wrong every frame, which reads as a vibration on anything moving.

What time a step is for. `now()` is the frame's time, on the refresh grid --
the last frame's plus a whole number of periods -- rather than whenever the
callback happened to arrive, so everything read off it moves by the same
amount every refresh. Never earlier than it has said before.
"""
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
    return time.perf_counter()


# A callback this soon after the last one, in refreshes, has no refresh
# behind it. KWin's real ones were measured 3ms apart at the closest, at 240Hz.
NO_REFRESH = 0.25


def grid_step(ft, last_cb, now: float, period: float) -> tuple:
    """The time of the frame a callback arriving at `now` makes, and the
    callback to count the next one from: (frame time, last callback).

    Counted in whole refreshes from the gap since the LAST CALLBACK -- not
    from the last frame's time, which once it ran ahead of the wall clock
    read as no gap at all and was thrown back: measured in the editor at two
    refreshes a frame, a fifth of its frames stood still and the rest moved
    a fraction. At least one refresh a frame, so time never runs back; a
    period added or held back whenever the frame time strays from the wall
    clock, so it cannot wander off.

    Except a callback with no refresh behind it, which counts nothing and
    is not counted from. Qt answers a requestUpdate AT ONCE when no frame is
    in flight -- a step that drew nothing commits nothing, so the compositor
    owes no callback -- and counting each of those as a refresh ran the frame
    time away: measured on a paused window, 20,000 steps in its last second
    before going idle and the frame time 338s ahead, which on play put the
    song at its end. And however the count comes out, the frame time is
    pulled back to within a refresh and a half of the wall clock.
    """
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
    """The refresh the compositor is calling back at, where that is plainly
    not `current`; None where it agrees, or the gaps do not say.

    Qt's idea of the screen is not the compositor's. On Wayland a window
    knows nothing of where it is, only which outputs it has entered, and Qt
    names the one entered FIRST until the window has left it entirely; KWin
    sends the frame callbacks from the output holding most of the window.
    Dragged from a 60Hz panel mostly onto a 240Hz one, the window was called
    back 240 times a second while everything here -- the debug overlay, the
    frame grid, the check that gives up drawing ahead -- worked to 60. So
    the callbacks are listened to: `gaps` between them, `rates` of the
    screens there are.

    The gap taken is the mean of the middle half. Single callbacks wander
    3.5-6.5ms apart at 240Hz, a late one followed by an early one, and a
    frame that missed its refresh waits a whole one more; the middle half
    leaves both tails out and averages what wobble is left.

    A screen whose period that gap is wins outright. Failing one, a gap
    SHORTER than the current screen's period means it cannot be that one --
    no compositor calls back faster than it refreshes -- and the slowest
    screen that could be is taken. A longer gap than the period, on its
    own, is only frames missing their refresh, and says nothing.
    """
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
                # Ours, so it stops here. Let through, Qt's widget window
                # answers a window's UpdateRequest by repainting the WHOLE
                # top-level widget: measured in the editor, the backdrop at
                # full window size, the line list and everything else on
                # every frame, 70 times a second, for a step that had moved
                # the playhead. What the step changed asked for its own
                # repaint, and that goes the ordinary way.
                return True
        elif kind in WAKE_EVENTS:
            self.wake()
        return False
