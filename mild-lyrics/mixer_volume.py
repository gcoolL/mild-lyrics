"""Our own player's volume, kept in the system mixer (Linux, through pactl), so
the bar and the desktop's per-app volume are one control. Notes:
docs/notes/mild-lyrics/home_page.md (Volume)."""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

NORM = 65536                    # the mixer's 100%
APP = "Mild Lyrics"
EVENT = re.compile(r"Event '(\w+)' on sink-input #(\d+)")


def gain(v: float) -> float:
    """The amplitude the mixer would give the bar's `v`: its scale is cubic."""
    return max(0.0, min(1.0, v)) ** 3


def _pactl(*args: str, timeout: float = 2.0) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(("pactl", *args), capture_output=True, text=True, timeout=timeout)
    except Exception:                                       # noqa: BLE001
        return None


def our_streams() -> dict[int, float]:
    """{sink-input index: volume 0..1} of this process's sound."""
    got = _pactl("-f", "json", "list", "sink-inputs")
    try:
        rows = json.loads(got.stdout or "[]") if got is not None and got.returncode == 0 else []
    except ValueError:
        return {}
    out = {}
    for row in rows if isinstance(rows, list) else []:
        props = (row or {}).get("properties") or {}
        pid = props.get("application.process.id")
        if str(pid) == str(os.getpid()) or (pid is None and props.get("node.name") == APP):
            vols = [c.get("value", 0) for c in (row.get("volume") or {}).values() if isinstance(c, dict)]
            out[int(row["index"])] = max(vols, default=NORM) / NORM
    return out


class StreamVolume(QObject):
    """Holds our sink-inputs at `want`, and hears the mixer move them.

    `heard(v)`: someone else set our volume (0..1, mixer percent).
    `placed()`: a stream of ours is at `want` -- the player's own gain can go to 1."""

    heard = pyqtSignal(float)
    placed = pyqtSignal()

    QUIET = 0.4                 # a change this soon after our own set is our own set

    def __init__(self) -> None:
        super().__init__()
        self.ok = sys.platform.startswith("linux") and shutil.which("pactl") is not None
        self.want: float | None = None
        self._sent: float | None = None
        self._sent_at = 0.0
        self._ours: dict[int, float] = {}
        self._relist = True
        self._wake = threading.Event()
        self._sub: subprocess.Popen | None = None
        self._started = False

    def start(self) -> None:
        if not self.ok or self._started:
            return
        self._started = True
        threading.Thread(target=self._push, name="mixer-volume", daemon=True).start()
        threading.Thread(target=self._listen, name="mixer-events", daemon=True).start()

    def set(self, v: float) -> None:
        self.want = max(0.0, min(1.0, float(v)))
        self._wake.set()

    def _push(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            v = self.want
            if v is None:
                continue
            if self._relist or not self._ours:
                self._ours, self._relist = our_streams(), False
            raw = str(round(v * NORM))
            for idx, at in list(self._ours.items()):
                if abs(at - v) < 0.5 / NORM:
                    continue
                self._sent_at = time.monotonic()
                got = _pactl("set-sink-input-volume", str(idx), raw)
                if got is None or got.returncode != 0:
                    self._ours.pop(idx, None)
                    self._relist = True
                else:
                    self._ours[idx] = v
            self._sent, self._sent_at = v, time.monotonic()
            if self._ours:
                self.placed.emit()
            time.sleep(0.03)                # a drag is one set per frame; the mixer needs fewer

    def _listen(self) -> None:
        try:
            self._sub = subprocess.Popen(("pactl", "subscribe"), stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True)
        except OSError:
            return
        atexit.register(self._sub.kill)
        for line in self._sub.stdout:
            m = EVENT.match(line.strip())
            if not m:
                continue
            kind, idx = m.group(1), int(m.group(2))
            if kind == "new":
                self._relist = True
                self._wake.set()            # a fresh stream of ours takes `want`
            elif kind == "remove":
                self._ours.pop(idx, None)
            elif (kind == "change" and idx in self._ours and not self._wake.is_set()
                  and time.monotonic() - self._sent_at > self.QUIET):
                v = our_streams().get(idx)
                if v is not None and abs(v - self._ours[idx]) > 0.5 / NORM:
                    self._ours[idx] = self._sent = self.want = v
                    self.heard.emit(v)
