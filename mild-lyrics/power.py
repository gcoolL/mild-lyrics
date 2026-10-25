"""Whether this machine has a battery, is on it, how full it is, or is saving
power; read each platform's own way, kept TTL seconds, "no battery" when
unsure."""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import time

TTL = 15.0
SYS = pathlib.Path("/sys/class/power_supply")

_seen: tuple[float, tuple[bool, bool, bool, float]] | None = None
NONE = (False, False, False, 100.0)


def _linux() -> tuple[bool, bool, bool, float]:
    battery = mains = discharging = False
    fills = []
    try:
        supplies = list(SYS.iterdir())
    except OSError:
        return NONE

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
            if read(d, "capacity").isdigit():
                fills.append(float(read(d, "capacity")))
        elif kind in ("Mains", "USB", "USB_C", "USB_PD") and read(d, "online") == "1":
            mains = True
    pct = sum(fills) / len(fills) if fills else 100.0
    return battery, battery and (discharging or not mains), False, pct


def _windows() -> tuple[bool, bool, bool, float]:
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
        return NONE
    flag = st.BatteryFlag & 0xFF
    battery = flag not in (128, 255)            # 128: none, 255: unknown
    pct = st.BatteryLifePercent & 0xFF
    pct = 100.0 if pct > 100 else float(pct)  # 255: unknown
    return (battery, battery and st.ACLineStatus == 0,
            st.SystemStatusFlag == 1, pct)


def _mac() -> tuple[bool, bool, bool, float]:
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                         text=True, timeout=2).stdout
    battery = "InternalBattery" in out
    m = re.search(r"(\d+)%", out)
    pct = float(m.group(1)) if m else 100.0
    return battery, battery and "'Battery Power'" in out, False, pct


def read() -> tuple[bool, bool, bool, float]:
    """(has a battery, running on it, the system's battery saver is on,
    charge in percent -- 100 where unknown)."""
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
        got = NONE
    _seen = (now, got)
    return got


def has_battery() -> bool:
    return read()[0]


def charge() -> float:
    return read()[3]


def low_power(below: float = 100.0) -> bool:
    """On battery at or under `below` percent, or the system asked to save
    power."""
    battery, on_it, saver, pct = read()
    return battery and ((on_it and pct <= below) or saver)
