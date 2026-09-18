#!/usr/bin/env python3
"""Measure the window's frame pump, with nothing but the pump in the window.

    python tools_frame_probe.py                     # 20s, the pump as it ships
    python tools_frame_probe.py --seconds 60
    python tools_frame_probe.py --mode repeat       # the other way of arming it
    python tools_frame_probe.py --paint full        # with a full-window repaint
    python tools_frame_probe.py --log frames.jsonl  # every frame, for later

It draws no lyrics, fetches nothing and reads no player. What it runs is
LyricsView's timer arrangement and nothing else, so a number that comes out
of here is the cost of getting to a frame rather than the cost of the frame.

WHY THE TWO MODES ARE DIFFERENT ON WINDOWS AND THE SAME ON LINUX. The window
arms a single-shot Qt::PreciseTimer against a deadline it carries in float
seconds, and re-arms it every frame -- which is the only way to run at
16.691ms when setInterval takes whole milliseconds. On Linux that costs an
entry in a sorted list. On Windows a PreciseTimer is a multimedia timer:
Qt calls timeSetEvent to arm it and timeKillEvent with TIME_KILL_SYNCHRONOUS
to disarm it, so the re-arm is two winmm calls a frame, the second of which
blocks until any callback in flight has finished. --mode repeat arms one
periodic timer at whole milliseconds and never touches it again, which gives
up the exact long-run rate and buys back whatever that costs.

Run both on the machine that is not smooth. If they come out the same, the
arming is not it and the answer is in --paint.

WHAT --paint SEPARATES. The window repaints the WHOLE window every frame and
blits the whole thing. On Windows that is a GDI BitBlt out of a DIB section,
on Linux usually a shared-memory pixmap the server already has; they are not
the same price and the difference grows with the window. `none` never asks
for a repaint, `cheap` asks for 64x64, `full` asks for the lot and fills it.
The gap between `none` and `full` is what the window is paying to put a frame
on the screen at this size on this machine.

WHAT THE TIMER RESOLUTION LINE MEANS, on Windows only. Windows' scheduler tick
is 15.6ms unless something has asked for finer, and what it grants is global
to the process. A multimedia timer raises it while it exists; so do Chrome, a
game, and a media player. That is the mechanism behind "some PCs": the same
build gets a different clock depending on what else is open, and the line
prints what this process actually has.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

from PyQt6.QtCore import Qt, QTimer, QRect                    # noqa: E402
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget             # noqa: E402

FRAME_IDLE_HZ = 10.0
TICK = 0.015625


def coarse() -> float:
    """perf_counter dropped onto the 15.625ms grid GetTickCount64 moves on.

    So the fault can be reproduced where there is no Windows to reproduce it
    on: this is what time.monotonic is under CPython 3.12 and earlier there.
    """
    return (time.perf_counter() // TICK) * TICK


CLOCKS = {"perf": time.perf_counter, "monotonic": time.monotonic,
          "coarse": coarse}


def system_resolution() -> float:
    """Windows' SYSTEM-WIDE scheduler tick in milliseconds, or 0 elsewhere.

    NOT what this process gets, and the difference is the whole point. Since
    Windows 10 2004 timeBeginPeriod is per-process: a process that has not
    asked for a finer tick is not given one because another process did.
    NtQueryTimerResolution still reports the global figure, so this line
    describes the MACHINE and says nothing about the timers in this window --
    which is exactly how it was read the first time it was printed, and it
    was wrong. What this process actually gets is measured, not asked for;
    see the interval histogram, which is the only honest answer.
    """
    if os.name != "nt":
        return 0.0
    try:
        import ctypes

        ntdll = ctypes.WinDLL("ntdll")
        lo, hi, cur = (ctypes.c_ulong() for _ in range(3))
        if ntdll.NtQueryTimerResolution(ctypes.byref(lo), ctypes.byref(hi),
                                        ctypes.byref(cur)) != 0:
            return 0.0
        return cur.value / 1e4
    except Exception:                                       # noqa: BLE001
        return 0.0


def hold_period(ms: int):
    """Ask Windows for a finer tick FOR THIS PROCESS. A release, or None.

    timeBeginPeriod is the only way a process gets one since the 2004 rule
    change, and it is what every program that animates on a schedule does.
    """
    if os.name != "nt" or ms <= 0:
        return None
    try:
        import ctypes

        winmm = ctypes.WinDLL("winmm")
        if winmm.timeBeginPeriod(ms) != 0:
            return None
        return lambda: winmm.timeEndPeriod(ms)
    except Exception:                                       # noqa: BLE001
        return None


class Probe(QWidget):
    """The pump, with a paint of a chosen size behind it."""

    def __init__(self, args) -> None:
        super().__init__()
        self.args = args
        self.setWindowTitle("mild-lyrics frame probe")
        w, h = args.size
        self.resize(w, h)
        self.frames: list[float] = []
        self.arms: list[float] = []
        self.paints: list[float] = []
        self.pairs: dict[tuple, int] = {}
        self.asked = 0
        self.stalls: list[tuple] = []
        self.rows: list[dict] = []
        self.n = 0
        self.clock = CLOCKS[args.clock]
        self.screen_hz = 0.0
        self.divisor = 1
        self.eff_hz = self._rate()
        self.began = 0.0
        self.last = 0.0
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._frame)
        self._frame_due = self.clock()

    def _rate(self) -> float:
        """The frame rate, which is NOT the screen's -- see retune_frames.

        The window runs at an integer divisor of the refresh, so a 100Hz panel
        under the default 60fps cap is driven at 50 and a 240Hz one at 60. The
        screen rate and the divisor are both reported, because a target of
        50.000Hz was read here as a 50Hz monitor and it was a 100Hz one.
        """
        scr = self.screen() or QApplication.primaryScreen()
        hz = scr.refreshRate() if scr is not None else 0.0
        self.screen_hz = hz if hz > 0 else 60.0
        self.divisor = max(1, math.ceil(self.screen_hz / max(1.0, self.args.hz)))
        return self.screen_hz / self.divisor

    def start(self) -> None:
        self.began = self.last = time.perf_counter()
        self._frame_due = self.clock()
        if self.args.mode == "repeat":
            self.timer.setSingleShot(False)
            self.timer.start(max(1, round(1000.0 / self.eff_hz)))
        else:
            self.timer.setSingleShot(True)
            self.timer.start(0)

    def showing(self) -> bool:
        if self.isHidden() or self.isMinimized():
            return False
        wh = self.windowHandle()
        return wh is None or wh.isExposed()

    def _frame(self) -> None:
        now = time.perf_counter()
        gap = (now - self.last) * 1000.0
        self.last = now
        self.n += 1
        if self.n > self.args.warmup:
            self.frames.append(gap)
            if self.args.mode == "single":
                key = (self.asked, int(round(gap)))
                self.pairs[key] = self.pairs.get(key, 0) + 1
            if gap > 3000.0 / self.eff_hz:
                self.stalls.append((time.strftime("%H:%M:%S"), gap, self.n))
        if self.args.paint == "full":
            self.update()
        elif self.args.paint == "cheap":
            self.update(QRect(0, 0, 64, 64))
        if self.args.log:
            self.rows.append({"n": self.n, "gap_ms": round(gap, 3),
                              "at": round(now - self.began, 4)})
        if self.args.mode == "repeat":
            return
        period = 1.0 / max(1.0, self.eff_hz if self.showing() else FRAME_IDLE_HZ)
        self._frame_due += period
        delay = self._frame_due - self.clock()
        if delay < -period:
            self._frame_due = self.clock() + period
            delay = period
        self.asked = max(0, round(delay * 1000))
        armed = time.perf_counter()
        self.timer.start(self.asked)
        if self.n > self.args.warmup:
            self.arms.append((time.perf_counter() - armed) * 1000.0)

    def paintEvent(self, _ev) -> None:
        began = time.perf_counter()
        p = QPainter(self)
        try:
            if self.args.paint == "full":
                W, H = self.width(), self.height()
                t = (self.n % 240) / 240.0
                g = QLinearGradient(0, 0, W, H)
                g.setColorAt(0.0, QColor.fromHsvF(t, 0.5, 0.18))
                g.setColorAt(1.0, QColor.fromHsvF((t + 0.3) % 1.0, 0.5, 0.30))
                p.fillRect(self.rect(), g)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
                p.setPen(QColor(234, 234, 234))
                p.setFont(QFont("", max(12, int(H * 0.06))))
                p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                           f"{self.n}")
            else:
                p.fillRect(0, 0, 64, 64, QColor(40, 40, 48))
        finally:
            p.end()
        if self.n > self.args.warmup:
            self.paints.append((time.perf_counter() - began) * 1000.0)


def spread(name: str, ms: list[float], unit: str = "ms") -> str:
    if not ms:
        return f"  {name}: nothing measured"
    got = sorted(ms)
    n = len(got)
    return (f"  {name}: {n}  median {statistics.median(got):.3f}{unit}  "
            f"p95 {got[min(n - 1, int(n * 0.95))]:.3f}  "
            f"p99 {got[min(n - 1, int(n * 0.99))]:.3f}  "
            f"worst {got[-1]:.3f}")


def report(win: Probe, args, res_before: float) -> None:
    hz = win.eff_hz
    period = 1000.0 / hz
    print()
    print(f"mode {args.mode}  paint {args.paint}  clock {args.clock}  "
          f"{win.width()}x{win.height()}")
    print(f"  screen {win.screen_hz:.3f}Hz / divisor {win.divisor} "
          f"= target {hz:.3f}Hz ({period:.3f}ms a frame), "
          f"cap {args.hz:.0f}fps")
    for name in ("monotonic", "perf_counter"):
        got = time.get_clock_info(name).resolution * 1000.0
        used = name.startswith(args.clock[:4])
        print(f"  {name:13} steps of {got:9.6f}ms"
              + ("   <- the deadline is measured against this" if used else ""))
    res_now = system_resolution()
    if res_before or res_now:
        print(f"  system-wide tick: {res_before:.3f}ms before, "
              f"{res_now:.3f}ms now -- the MACHINE's, not this process's")
    if args.period:
        print(f"  this process asked for a {args.period}ms tick of its own")
    print(spread("frame interval", win.frames))
    if win.frames:
        late = [g for g in win.frames if g > period * 1.5]
        twice = [g for g in win.frames if g > period * 2.5]
        print(f"    over 1.5x period: {len(late)} "
              f"({len(late) / len(win.frames):.1%})   "
              f"over 2.5x: {len(twice)} "
              f"({len(twice) / len(win.frames):.1%})")
        ran = sum(win.frames) / 1000.0 or 1.0
        print(f"    {len(win.frames)} measured frames in {ran:.1f}s "
              f"= {len(win.frames) / ran:.2f}fps, asked for {hz:.2f}")
    if win.frames:
        print("  where the frames landed, to the millisecond:")
        buckets: dict[int, int] = {}
        for g in win.frames:
            buckets[int(round(g))] = buckets.get(int(round(g)), 0) + 1
        for ms in sorted(buckets):
            n = buckets[ms]
            if n / len(win.frames) < 0.005:
                continue
            print(f"    {ms:3d}ms  {n:5d}  {n / len(win.frames):5.1%}  "
                  + "#" * max(1, round(40 * n / len(win.frames))))
    if win.pairs:
        print("  what the timer was asked for, and what it gave:")
        for (asked, got), n in sorted(win.pairs.items(),
                                      key=lambda kv: -kv[1])[:8]:
            print(f"    asked {asked:3d}ms  ->  {got:3d}ms   {n:5d}  "
                  f"{n / len(win.frames):5.1%}")
    print(spread("arming the timer", win.arms))
    print(spread("paintEvent", win.paints))
    if win.stalls:
        print(f"  stalls over 3x period: {len(win.stalls)}")
        for at, gap, n in win.stalls[-8:]:
            print(f"    {at}  {gap:.1f}ms  at frame {n}")
    else:
        print("  stalls over 3x period: none")
    if args.log:
        with open(args.log, "w", encoding="utf-8") as fh:
            for row in win.rows:
                fh.write(json.dumps(row) + "\n")
        print(f"  every frame written to {args.log}")


def size(text: str) -> tuple[int, int]:
    w, _, h = text.lower().partition("x")
    return int(w), int(h)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--hz", type=float, default=60.0,
                    help="the fps cap, as --fps-cap sets it on the window")
    ap.add_argument("--mode", choices=["single", "repeat"], default="single",
                    help="single: re-armed every frame against a carried "
                         "deadline, which is what the window does. repeat: "
                         "one periodic timer at whole milliseconds")
    ap.add_argument("--paint", choices=["none", "cheap", "full"], default="full",
                    help="how much of the window to repaint each frame "
                         "(default full, as the window does)")
    ap.add_argument("--size", type=size, default=(1280, 720),
                    metavar="WxH")
    ap.add_argument("--clock", choices=sorted(CLOCKS), default="perf",
                    help="the clock the frame deadline is measured against. "
                         "perf is perf_counter, which is what the window uses "
                         "and is QueryPerformanceCounter on Windows. monotonic "
                         "is time.monotonic, which the window used to use and "
                         "which under CPython 3.12 and earlier on Windows is "
                         "GetTickCount64, in steps of 15.625ms. coarse is "
                         "perf_counter rounded down onto that same 15.625ms "
                         "grid, which reproduces the Windows fault on any "
                         "platform. Run both")
    ap.add_argument("--period", type=int, default=0, metavar="MS",
                    help="call timeBeginPeriod(MS) for this process before "
                         "running. Since Windows 10 2004 that is the only way "
                         "a process gets a finer tick than 15.6ms, whatever "
                         "the rest of the machine is running at. Try 1")
    ap.add_argument("--warmup", type=int, default=20, metavar="N",
                    help="frames to run before measuring anything, so the "
                         "first paint and the first window mapping are not "
                         "read as a stall (default 20)")
    ap.add_argument("--log", default="", metavar="PATH",
                    help="write every frame's interval as JSON lines")
    args = ap.parse_args()

    app = QApplication(sys.argv[:1])
    release = hold_period(args.period)
    if args.period and release is None:
        print(f"timeBeginPeriod({args.period}) was refused; running without it")
        args.period = 0
    res_before = system_resolution()
    win = Probe(args)
    win.show()
    print(f"Qt {__import__('PyQt6.QtCore', fromlist=['QT_VERSION_STR']).QT_VERSION_STR}"
          f"  {QApplication.platformName()}  python {sys.version.split()[0]}")
    print(f"running {args.seconds:.0f}s -- leave the window alone and in front")
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    win.start()
    app.exec()
    report(win, args, res_before)
    if release is not None:
        release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
