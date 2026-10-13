"""Whether this machine has a battery, is running on it, or is saving power.

Read from the system each platform's own way -- sysfs on Linux,
GetSystemPowerStatus on Windows, pmset on macOS -- and kept for TTL seconds,
so the window can ask on a timer without the asking costing anything.
Everything answers "no battery" where it cannot tell, which leaves the
window exactly as it was before this existed.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

TTL = 15.0
SYS = pathlib.Path("/sys/class/power_supply")

_seen: tuple[float, tuple[bool, bool, bool]] | None = None


def _linux() -> tuple[bool, bool, bool]:
    battery = mains = discharging = False
    try:
        supplies = list(SYS.iterdir())
    except OSError:
        return False, False, False

    def read(d, name):
        try:
            return (d / name).read_text().strip()
        except OSError:
            return ""

    for d in supplies:
        kind = read(d, "type")
        if kind == "Battery" and read(d, "scope") != "Device":
            battery = True                      # not a mouse's or a pad's
            discharging |= read(d, "status") == "Discharging"
        elif kind in ("Mains", "USB", "USB_C", "USB_PD") and read(d, "online") == "1":
            mains = True
    return battery, battery and (discharging or not mains), False


def _windows() -> tuple[bool, bool, bool]:
    import ctypes
    from ctypes import wintypes

    class Status(ctypes.Structure):
        _fields_ = [("ACLineStatus", wintypes.BYTE),
                    ("BatteryFlag", wintypes.BYTE),
                    ("BatteryLifePercent", wintypes.BYTE),
                    ("SystemStatusFlag", wintypes.BYTE),
                    ("BatteryLifeTime", wintypes.DWORD),
                    ("BatteryFullLifeTime", wintypes.DWORD)]

    st = Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return False, False, False
    flag = st.BatteryFlag & 0xFF
    battery = flag not in (128, 255)            # 128: none, 255: unknown
    return battery, battery and st.ACLineStatus == 0, st.SystemStatusFlag == 1


def _mac() -> tuple[bool, bool, bool]:
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                         text=True, timeout=2).stdout
    battery = "InternalBattery" in out
    return battery, battery and "'Battery Power'" in out, False


def read() -> tuple[bool, bool, bool]:
    """(has a battery, running on it, the system's battery saver is on)."""
    global _seen
    now = time.monotonic()
    if _seen is not None and now - _seen[0] < TTL:
        return _seen[1]
    try:
        if os.name == "nt":
            got = _windows()
        elif sys.platform == "darwin":
            got = _mac()
        else:
            got = _linux()
    except Exception:                                   # noqa: BLE001
        got = (False, False, False)
    _seen = (now, got)
    return got


def has_battery() -> bool:
    return read()[0]


def low_power() -> bool:
    """On battery, or the system asked to save power."""
    battery, on_it, saver = read()
    return battery and (on_it or saver)
