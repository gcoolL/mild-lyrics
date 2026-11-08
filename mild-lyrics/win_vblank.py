"""Windows refresh signal: a thread that waits on the window's display's
vertical blank (D3DKMTWaitForVerticalBlankEvent) and tells the GUI thread,
so frames are timed to the refresh instead of a timer DWM samples."""
from __future__ import annotations

import ctypes
import math
import os
import statistics
import sys
import threading
from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal

import frame_clock as FCK

IDLE_S = 0.5          # no frame asked for this long: stop waiting on blanks
RECHECK_S = 1.0       # how often the window's monitor is looked up again
JUDGE_AFTER = 120     # blanks measured before the source is trusted
TOO_FAST = 0.002      # a median gap under this: the wait is not waiting
FAILS = 10            # failed waits in a row before giving up
DWM_AGREE = 0.03      # DWM's refresh within this share of the measured one: its timing is this display's


class _OpenAdapter(ctypes.Structure):
    _fields_ = [("hDc", ctypes.c_void_p), ("hAdapter", ctypes.c_uint),
                ("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32),
                ("VidPnSourceId", ctypes.c_uint)]


class _WaitBlank(ctypes.Structure):
    _fields_ = [("hAdapter", ctypes.c_uint), ("hDevice", ctypes.c_uint),
                ("VidPnSourceId", ctypes.c_uint)]


class _Rect(ctypes.Structure):
    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                ("r", ctypes.c_long), ("b", ctypes.c_long)]


class _MonitorInfoEx(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("rcMonitor", _Rect), ("rcWork", _Rect),
                ("dwFlags", ctypes.c_uint32), ("szDevice", ctypes.c_wchar * 32)]


_U32, _U64 = ctypes.c_uint32, ctypes.c_uint64


class _DwmTiming(ctypes.Structure):
    """DWM_TIMING_INFO (dwmapi.h, packed to 1 byte)."""
    _pack_ = 1
    _fields_ = [("cbSize", _U32), ("rateRefreshNum", _U32), ("rateRefreshDen", _U32),
                ("qpcRefreshPeriod", _U64), ("rateComposeNum", _U32), ("rateComposeDen", _U32),
                ("qpcVBlank", _U64), ("cRefresh", _U64), ("cDXRefresh", _U32),
                ("qpcCompose", _U64), ("cFrame", _U64), ("cDXPresent", _U32),
                ("cRefreshFrame", _U64), ("cFrameSubmitted", _U64), ("cDXPresentSubmitted", _U32),
                ("cFrameConfirmed", _U64), ("cDXPresentConfirmed", _U32),
                ("cRefreshConfirmed", _U64), ("cDXRefreshConfirmed", _U32),
                ("cFramesLate", _U64), ("cFramesOutstanding", _U32),
                ("cFrameDisplayed", _U64), ("qpcFrameDisplayed", _U64),
                ("cRefreshFrameDisplayed", _U64), ("cFrameComplete", _U64),
                ("qpcFrameComplete", _U64), ("cFramePending", _U64), ("qpcFramePending", _U64),
                ("cFramesDisplayed", _U64), ("cFramesComplete", _U64), ("cFramesPending", _U64),
                ("cFramesAvailable", _U64), ("cFramesDropped", _U64), ("cFramesMissed", _U64),
                ("cRefreshNextDisplayed", _U64), ("cRefreshNextPresented", _U64),
                ("cRefreshesDisplayed", _U64), ("cRefreshesPresented", _U64),
                ("cRefreshStarted", _U64), ("cPixelsReceived", _U64), ("cPixelsDrawn", _U64),
                ("cBuffersEmpty", _U64)]


class _Api:
    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32                  # noqa: F821
        self.gdi32 = ctypes.windll.gdi32                    # noqa: F821
        self.kernel32 = ctypes.windll.kernel32              # noqa: F821
        self.user32.MonitorFromWindow.restype = ctypes.c_void_p
        self.user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.gdi32.CreateDCW.restype = ctypes.c_void_p
        self.gdi32.CreateDCW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p,
                                         ctypes.c_void_p, ctypes.c_void_p]
        self.gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
        for name in ("D3DKMTOpenAdapterFromHdc", "D3DKMTWaitForVerticalBlankEvent",
                     "D3DKMTCloseAdapter"):
            fn = getattr(self.gdi32, name)
            fn.restype = ctypes.c_long                      # NTSTATUS
            fn.argtypes = [ctypes.c_void_p]
        try:
            self.dwm = ctypes.windll.dwmapi                 # noqa: F821
            self.dwm.DwmGetCompositionTimingInfo.restype = ctypes.c_long
            self.dwm.DwmGetCompositionTimingInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        except Exception:                                   # noqa: BLE001
            self.dwm = None
        f = ctypes.c_int64()
        self.kernel32.QueryPerformanceFrequency(ctypes.byref(f))
        self.qpf = float(f.value) or 1.0

    def monitor(self, hwnd: int) -> int:
        return self.user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2) or 0   # NEAREST

    def open(self, monitor: int) -> tuple[int, int, str, bool] | None:
        """(adapter, source id, device name, primary) for a monitor, or None."""
        info = _MonitorInfoEx()
        info.cbSize = ctypes.sizeof(info)
        if not self.user32.GetMonitorInfoW(ctypes.c_void_p(monitor), ctypes.byref(info)):
            return None
        dc = self.gdi32.CreateDCW(None, info.szDevice, None, None)
        if not dc:
            return None
        try:
            oa = _OpenAdapter(hDc=dc)
            if self.gdi32.D3DKMTOpenAdapterFromHdc(ctypes.byref(oa)) != 0:
                return None
            return oa.hAdapter, oa.VidPnSourceId, info.szDevice, bool(info.dwFlags & 1)
        finally:
            self.gdi32.DeleteDC(dc)

    def wait(self, adapter: int, source: int) -> int:
        w = _WaitBlank(hAdapter=adapter, hDevice=0, VidPnSourceId=source)
        return self.gdi32.D3DKMTWaitForVerticalBlankEvent(ctypes.byref(w))

    def close(self, adapter: int) -> None:
        h = ctypes.c_uint(adapter)
        self.gdi32.D3DKMTCloseAdapter(ctypes.byref(h))

    def dwm_blank(self) -> tuple[float, float] | None:
        """(the latest blank on FCK.mono, period) from DWM's own timing --
        exact, unlike a stamp taken once this thread has the GIL back.
        DWM times one display: the caller checks it is this one."""
        if self.dwm is None:
            return None
        ti = _DwmTiming()
        ti.cbSize = ctypes.sizeof(ti)
        if self.dwm.DwmGetCompositionTimingInfo(None, ctypes.byref(ti)) != 0:
            return None
        if not ti.qpcRefreshPeriod or not ti.qpcVBlank:
            return None
        q = ctypes.c_int64()
        self.kernel32.QueryPerformanceCounter(ctypes.byref(q))
        mono = FCK.mono()
        n = math.floor((q.value - ti.qpcVBlank) / ti.qpcRefreshPeriod)
        latest = ti.qpcVBlank + n * ti.qpcRefreshPeriod
        return mono - (q.value - latest) / self.qpf, ti.qpcRefreshPeriod / self.qpf


class VBlank(QObject):
    """One blank signal per want(), on FCK.mono. `ok()` once measured sane;
    `broken` says why it stopped."""

    blank = pyqtSignal(float)
    note = pyqtSignal(str, object)      # (event, fields) for follow.log, from the thread

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.broken = ""
        self.hz: float | None = None    # measured
        self.device = ""
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._hwnd = 0
        self._wanted = False
        self._want_at = 0.0
        self._last: float | None = None   # the latest blank
        self._used: float | None = None   # the blank last answered
        self._going = os.name == "nt"
        if not self._going:
            self.broken = "not Windows"
            return
        threading.Thread(target=self._run, name="win-vblank", daemon=True).start()

    def ok(self) -> bool:
        return not self.broken and self.hz is not None

    def watch(self, hwnd: int) -> None:
        with self._lock:
            self._hwnd = int(hwnd)
        self._wake.set()

    def stop(self) -> None:
        self._going = False
        self._wake.set()

    def want(self) -> None:
        """Ask for the next blank. A blank that went by since the last answer,
        under a period ago, is answered at once (the frame ran late)."""
        now = FCK.mono()
        with self._lock:
            self._want_at = now
            last, period = self._last, 1.0 / self.hz if self.hz else 0.0
            if last is not None and last != self._used and now - last < period:
                self._used = last
                self._wanted = False
            else:
                self._wanted = True
                last = None
        if last is not None:
            self.blank.emit(last)
        else:
            self._wake.set()

    # ------------------------------------------------------------ the thread
    def _give_up(self, why: str) -> None:
        self.broken = why
        self._going = False
        self.note.emit("vblank-gave-up", {"why": why})

    def _judge(self, api: _Api, stamps: list[float], primary: bool) -> float | None:
        """After JUDGE_AFTER blanks: the refresh rate, where DWM's timing is
        this display's; else None, and the window stays on its timer. A wake
        is stamped once the thread has the GIL back -- late by up to the
        switch interval, more than a 240Hz period -- so the rate heard is
        counted over the whole run, and the blank times are DWM's."""
        per = (stamps[-1] - stamps[0]) / (len(stamps) - 1)
        if per < TOO_FAST:
            self._give_up(f"blanks {per * 1000:.2f}ms apart: not waiting")
            return None
        got = api.dwm_blank()
        if got is None or abs(got[1] - per) > DWM_AGREE * per:
            self._give_up(f"DWM times another rate ({1.0 / got[1]:.2f}Hz)" if got
                          else "no DWM timing")
            self.note.emit("vblank-heard", {"heard": round(1.0 / per, 2), "device": self.device,
                                            "primary": primary})
            return None
        self.note.emit("vblank-hz", {"hz": round(1.0 / got[1], 3), "heard": round(1.0 / per, 2),
                                     "device": self.device, "primary": primary})
        return 1.0 / got[1]

    def _run(self) -> None:                                   # pragma: no cover
        try:
            api = _Api()
        except Exception as e:                              # noqa: BLE001
            self._give_up(f"no D3DKMT: {e!r}"[:200])
            return
        adapter = source = monitor = 0
        primary = False
        checked = -RECHECK_S
        fails = 0
        stamps: list[float] = []
        judged = False
        while self._going:
            now = FCK.mono()
            with self._lock:
                idle = (not self._wanted and now - self._want_at > IDLE_S
                        and judged)                     # judging runs unasked
                hwnd = self._hwnd
            if idle or not hwnd:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            if now - checked > RECHECK_S:
                checked = now
                mon = api.monitor(hwnd)
                if mon != monitor or not adapter:
                    if adapter:
                        api.close(adapter)
                        adapter = 0
                    got = api.open(mon) if mon else None
                    monitor = mon
                    if got is None:
                        self._give_up("could not open the display's adapter")
                        return
                    adapter, source, self.device, primary = got
                    stamps, judged, self.hz = [], False, None
                    with self._lock:
                        self._last = None
            if api.wait(adapter, source) != 0:
                fails += 1
                if fails >= FAILS:
                    api.close(adapter)
                    self._give_up("vertical blank waits fail")
                    return
                continue
            fails = 0
            raw = FCK.mono()
            if not judged:
                if stamps and raw - stamps[-1] > 0.1:
                    stamps = []                         # a pause: count again
                stamps.append(raw)
                if len(stamps) > JUDGE_AFTER:
                    hz = self._judge(api, stamps, primary)
                    if hz is None:
                        api.close(adapter)
                        return
                    judged, self.hz = True, hz
                continue
            got = api.dwm_blank()
            if got is None:
                continue
            t = got[0]
            with self._lock:
                self._last = t
                fire = self._wanted
                if fire:
                    self._wanted = False
                    self._used = t
            if fire:
                self.blank.emit(t)
        if adapter:
            api.close(adapter)


def probe(seconds: float = 3.0) -> None:
    """Print blank gaps and DWM's timing for the primary monitor (a check over SSH)."""
    api = _Api()
    print("DWM_TIMING_INFO size", ctypes.sizeof(_DwmTiming), "(292 by dwmapi.h's fields)")
    hwnd = ctypes.windll.user32.GetDesktopWindow()          # noqa: F821
    got = api.open(api.monitor(hwnd))
    print("adapter:", got)
    if got is None:
        return
    adapter, source = got[0], got[1]
    t0 = last = FCK.mono()
    gaps, lag = [], []
    while last - t0 < seconds:
        st = api.wait(adapter, source)
        t = FCK.mono()
        if st != 0:
            print("status", hex(st & 0xFFFFFFFF))
            break
        d = api.dwm_blank()
        if d is not None:
            lag.append(t - d[0])
        gaps.append(t - last)
        last = t
    api.close(adapter)
    if len(gaps) > 1:
        gaps = gaps[1:]
        print(f"{len(gaps)} blanks, median {statistics.median(gaps) * 1000:.3f}ms, "
              f"min {min(gaps) * 1000:.3f} max {max(gaps) * 1000:.3f}")
    print("dwm:", api.dwm_blank())
    if lag:
        print(f"wake after DWM's blank: median {statistics.median(lag) * 1000:.3f}ms "
              f"min {min(lag) * 1000:.3f} max {max(lag) * 1000:.3f}")


if __name__ == "__main__":
    probe(float(sys.argv[1]) if len(sys.argv) > 1 else 3.0)
