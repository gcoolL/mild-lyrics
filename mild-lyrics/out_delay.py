"""How long this process's own audio takes from its stream to the output
device, read off PipeWire. Qt's player position counts only Qt's own buffer,
so it runs ahead of the sound by this much. Notes: docs/notes/mild-lyrics/
out_delay.md."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time

MODES = ("auto", "off")
mode = "auto"
REFRESH = 10.0          # seconds between readings, while someone asks
MOST = 0.5              # past this a reading is a fault, not a delay

_got = {"sec": 0.0, "at": -1e9, "ok": False, "busy": False}


def delay() -> float:
    """Seconds of output delay now (0 when off, unmeasured or not PipeWire).
    Never waits: a stale reading is refreshed on a thread."""
    if mode == "off" or not sys.platform.startswith("linux"):
        return 0.0
    if time.monotonic() - _got["at"] > REFRESH and not _got["busy"]:
        _got["busy"] = True
        threading.Thread(target=_refresh, name="out-delay", daemon=True).start()
    return _got["sec"] if _got["ok"] else 0.0


STRETCH_WINDOW = 0.12   # Qt's Signalsmith Stretch presetDefault block, seconds


def stretch(rate: float, compensated: bool = True) -> float:
    """Song seconds Qt's time-stretcher (pitch compensation, any rate but 1)
    holds back and Qt does not count: half a window in, half a window out."""
    if mode == "off" or not compensated or abs(rate - 1.0) < 1e-3:
        return 0.0
    return STRETCH_WINDOW / 2.0 * (1.0 + rate)


def said() -> str:
    """What auto has measured, for a setting's note."""
    if mode == "off":
        return "off"
    if not sys.platform.startswith("linux"):
        return "auto · not measured on this system"
    if not _got["ok"]:
        return "auto · not measured yet"
    return f"auto · {_got['sec'] * 1000.0:.0f} ms"


def _refresh() -> None:
    try:
        got = measure()
    except Exception:                                   # noqa: BLE001
        got = None
    if got is not None:
        _got["sec"], _got["ok"] = got, True
    _got["at"], _got["busy"] = time.monotonic(), False


def _run(*cmd: str) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3.0).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _live_quantum(driver: int) -> tuple[int, int] | None:
    """(quantum, rate) the driver runs at now, from pw-top's second sample."""
    rows = _run("pw-top", "-b", "-n", "2").splitlines()
    for line in reversed(rows):
        f = line.split()
        if len(f) > 3 and f[1] == str(driver) and f[2].isdigit() and f[3].isdigit():
            q, r = int(f[2]), int(f[3])
            return (q, r) if q and r else None
    return None


def measure(pid: int | None = None) -> float | None:
    """Seconds from this process's playback streams to the device: their
    downstream Latency param (quantum, samples, ns) at the live quantum.
    None when there is no such stream to read."""
    pid = os.getpid() if pid is None else pid
    text = _run("pw-dump")
    if not text:
        return None
    objs = json.loads(text)
    settings = {}
    for o in objs:
        if o.get("type", "").endswith("Metadata") and (o.get("props") or {}).get("metadata.name") == "settings":
            settings = {m.get("key"): m.get("value") for m in o.get("metadata") or []}
    best = None
    for o in objs:
        info = o.get("info") or {}
        p = info.get("props") or {}
        if p.get("media.class") != "Stream/Output/Audio" or str(p.get("application.process.id")) != str(pid):
            continue
        lat = [x for x in (info.get("params") or {}).get("Latency") or [] if x.get("direction") == "Input"]
        if not lat:
            continue
        x = lat[0]
        live = _live_quantum(int(p.get("node.driver-id", -1)))
        q, rate = live or (int(settings.get("clock.force-quantum") or 0)
                           or int(settings.get("clock.quantum") or 1024),
                           int(settings.get("clock.rate") or 48000))
        sec = ((x.get("minQuantum", 0) + x.get("maxQuantum", 0)) / 2.0 * q
               + (x.get("minRate", 0) + x.get("maxRate", 0)) / 2.0) / rate \
            + (x.get("minNs", 0) + x.get("maxNs", 0)) / 2e9
        if 0.0 <= sec <= MOST:
            best = sec if best is None else max(best, sec)
    return best


if __name__ == "__main__":
    args = sys.argv[1:]
    print(measure(int(args[0]) if args else None))
