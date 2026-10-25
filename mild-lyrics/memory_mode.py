"""The Memory use setting: minimal holds a ceiling of own memory, low trades
CPU for RAM, more spends RAM where it shows, auto is low at 8GB or less and
normal above. What each mode does and why: docs/notes/mild-lyrics/memory_mode.md."""
from __future__ import annotations

import os
import sys
import threading

MODES = ["auto", "minimal", "low", "normal", "more"]
LOW_RAM = 8 << 30          # auto picks low at or below this much RAM

MB = 1 << 20
PROFILES = {
    "minimal": {
        "motion": "stream", "motion_budget": 0, "motion_ahead": 0,
        "motion_idle": 2.0,     # drop the stream once not drawn this long
        "pix": 6 * MB, "glow": 1 * MB, "words": 1 * MB, "still": 2 * MB,
        "thumbs": 4 * MB,
        "workers": 0,
        "zygote": True,         # one forked process per job, gone after
        "readers": "lean",      # pykakasi only, let go once unused
        # Not 0: let go every 2s, the next reading reloaded them on the
        # window -- 120-150ms, a freeze every few seconds on a Japanese or
        # Chinese song being pushed from the editor.
        "readers_idle": 20.0,
        "trim_every": 2.0,      # also how often the ceiling is checked
        "gpu_off": True,
        "arena_max": 2,
        "mmap_threshold": 256 << 10,   # pictures mapped apart, given back freed
        "lean": True,           # flat walls unpainted, memos not kept
        "ceiling": (100 * MB, 120 * MB, 135 * MB, 150 * MB),
    },
    "low": {
        "motion": "stream",     # frames read from disk just ahead of the clock
        "motion_budget": 0,
        "motion_ahead": 0,      # albums whose animation is decoded early
        "motion_idle": None,
        "pix": 32 * MB, "glow": 8 * MB, "words": 4 * MB, "still": 8 * MB,
        "thumbs": 12 * MB,
        "workers": 1,           # offload processes, at launch
        "zygote": False, "readers": "here",
        "readers_idle": 300.0,  # release Sudachi after this long unused
        "trim_every": 30.0,
        "gpu_off": False, "arena_max": None, "mmap_threshold": None, "lean": False, "ceiling": None,
    },
    "normal": {
        "motion": "frames", "motion_budget": 192 * MB, "motion_ahead": 0,
        "motion_idle": None,
        "pix": 96 * MB, "glow": 16 * MB, "words": 8 * MB, "still": 16 * MB,
        "thumbs": 32 * MB,
        "workers": 2, "zygote": False, "readers": "here",
        "readers_idle": None, "trim_every": None,
        "gpu_off": False, "arena_max": None, "mmap_threshold": None, "lean": False, "ceiling": None,
    },
    "more": {
        "motion": "frames", "motion_budget": 512 * MB, "motion_ahead": 1,
        "motion_idle": None,
        "pix": 256 * MB, "glow": 48 * MB, "words": 32 * MB, "still": 64 * MB,
        "thumbs": 96 * MB,
        "workers": 2, "zygote": False, "readers": "here",
        "readers_idle": None, "trim_every": None,
        "gpu_off": False, "arena_max": None, "mmap_threshold": None, "lean": False, "ceiling": None,
    },
}


def total_ram() -> int:
    """Bytes of physical memory, or 0 where it cannot be told."""
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        pass
    if os.name == "nt":
        try:
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong),
                            ("pf_total", ctypes.c_ulonglong),
                            ("pf_avail", ctypes.c_ulonglong),
                            ("v_total", ctypes.c_ulonglong),
                            ("v_avail", ctypes.c_ulonglong),
                            ("v_ext", ctypes.c_ulonglong)]
            ms = MS()
            ms.len = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return int(ms.total)
        except Exception:                                # noqa: BLE001
            pass
    return 0


def pick(mode: str) -> str:
    """The mode in force: auto resolved, anything unknown read as normal."""
    if mode in PROFILES:
        return mode
    if mode == "auto":
        ram = total_ram()
        return "low" if 0 < ram <= LOW_RAM else "normal"
    return "normal"


def profile(mode: str) -> dict:
    return PROFILES[pick(mode)]


TRIM_AFTER_S = 4.0
_trim = {"fn": None, "timer": None}


def trim_heap_soon(after: float = TRIM_AFTER_S) -> None:
    """Give freed memory back to the OS shortly (glibc only): frames decoded
    on worker threads otherwise stay in glibc's arenas once freed. See
    docs/notes/mild-lyrics/lyrics_gui.md, "Memory" (2026-10-16)."""
    if _trim["fn"] is None:
        try:
            import ctypes
            _trim["fn"] = (ctypes.CDLL("libc.so.6").malloc_trim
                           if sys.platform.startswith("linux") else False)
        except Exception:                                # noqa: BLE001
            _trim["fn"] = False
    if not _trim["fn"] or _trim["timer"] is not None:
        return

    def run() -> None:
        _trim["timer"] = None
        try:
            _trim["fn"](0)
        except Exception:                                # noqa: BLE001
            pass
    t = _trim["timer"] = threading.Timer(after, run)
    t.daemon = True
    t.start()


def _descendants(pid: int) -> list[int]:
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        try:
            for t in os.listdir(f"/proc/{p}/task"):
                with open(f"/proc/{p}/task/{t}/children") as f:
                    todo += [int(c) for c in f.read().split()]
        except OSError:
            pass
    return out


def _linux_own(pid: int) -> tuple[int, int]:
    own = res = 0
    for p in _descendants(pid):
        try:
            with open(f"/proc/{p}/smaps_rollup") as f:
                for line in f:
                    k, _, v = line.partition(":")
                    if k in ("Private_Clean", "Private_Dirty"):
                        own += int(v.split()[0]) << 10
                    elif k == "Rss":
                        res += int(v.split()[0]) << 10
        except (OSError, ValueError):
            continue
    return own, res


def own_memory() -> tuple[int, int, bool]:
    """(own, resident, measured): bytes only this player and its child
    processes hold, and resident as usually shown. Where own cannot be read
    it is resident, and `measured` is False."""
    pid = os.getpid()
    if sys.platform.startswith("linux"):
        try:
            own, res = _linux_own(pid)
            if res:
                return own, res, True
        except Exception:                                # noqa: BLE001
            pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD),
                            ("PageFaultCount", wintypes.DWORD),
                            *[(n, ctypes.c_size_t) for n in (
                                "PeakWorkingSetSize", "WorkingSetSize",
                                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                                "QuotaPeakNonPagedPoolUsage",
                                "QuotaNonPagedPoolUsage", "PagefileUsage",
                                "PeakPagefileUsage", "PrivateUsage")]]
            pmc = PMC()
            pmc.cb = ctypes.sizeof(PMC)
            # Typed: untyped, the pseudo-handle (-1) went through as a 32-bit int and was refused.
            k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(),
                                          ctypes.byref(pmc), pmc.cb):
                return int(pmc.PrivateUsage), int(pmc.WorkingSetSize), True
        except Exception:                                # noqa: BLE001
            pass
    if sys.platform == "darwin":
        try:
            import ctypes

            class RU(ctypes.Structure):          # rusage_info_v2, enough of it
                _fields_ = [("uuid", ctypes.c_uint8 * 16),
                            *[(n, ctypes.c_uint64) for n in (
                                "user", "system", "pkg_idle_wkups",
                                "interrupt_wkups", "pageins", "wired_size",
                                "resident_size", "phys_footprint")],
                            ("rest", ctypes.c_uint64 * 32)]
            ru = RU()
            lib = ctypes.CDLL("/usr/lib/libproc.dylib")
            if lib.proc_pid_rusage(pid, 2, ctypes.byref(ru)) == 0:
                return int(ru.phys_footprint), int(ru.resident_size), True
        except Exception:                                # noqa: BLE001
            pass
    try:
        with open("/proc/self/statm") as f:
            res = int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        return res, res, False
    except Exception:                                    # noqa: BLE001
        pass
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak *= 1 if sys.platform == "darwin" else 1024
        return peak, peak, False
    except Exception:                                    # noqa: BLE001
        return 0, 0, False


def mmap_threshold(n: int | None) -> None:
    """glibc maps every block of n bytes or more on its own and unmaps it
    when freed. Its default threshold climbs to the size of the largest
    block freed, so line pictures landed in the heap among small long-lived
    blocks and their pages stayed after them. Linux only."""
    if not n or not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").mallopt(-3, int(n))     # M_MMAP_THRESHOLD
    except Exception:                                    # noqa: BLE001
        pass


def arena_max(n: int | None) -> None:
    """At most n glibc arenas (before threads start, so they share them);
    fewer arenas hold less freed memory between them. Linux only."""
    if not n or not sys.platform.startswith("linux"):
        return
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").mallopt(-8, int(n))     # M_ARENA_MAX
    except Exception:                                    # noqa: BLE001
        pass
