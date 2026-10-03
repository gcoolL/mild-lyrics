"""A per-frame record of the player's pacing, for reading afterwards.

Off unless MILD_FRAME_TRACE names a file. Then every frame step, paint and
GPU buffer swap is stamped on the mono clock, with what the window was at
the time -- fullscreen or not, its size, CPU or GPU -- and the lot is written
to that file as JSON lines when the program exits. The debug overlay gives
averages over a second; a slipped refresh, two frames shown in one, or a
paint that started late is only visible frame by frame, which is what this
keeps.

Cheap enough to leave hooked: off, every hook is one attribute test.
"""
from __future__ import annotations

import atexit
import json
import os
import time

PATH = os.environ.get("MILD_FRAME_TRACE", "")
ON = bool(PATH)
KEEP = 400_000          # about half an hour at 240 frames a second

_rows: list = []
_state = None


def mono() -> float:
    return time.perf_counter()


def mark(kind: str, *vals) -> None:
    """One event: `kind` and whatever numbers go with it."""
    if len(_rows) < KEEP:
        _rows.append((mono(), kind) + vals)


def sect(kind: str) -> None:
    """A point inside a paint, with this thread's CPU time: wall time that
    passes with no CPU time is waiting -- on the GL driver, mostly."""
    if len(_rows) < KEEP:
        _rows.append((mono(), kind, time.thread_time()))


def state(full: bool, w: int, h: int, gpu: bool, hz: float,
          ahead: bool = False) -> None:
    """What the window is; recorded only when it changes."""
    global _state
    now = (bool(full), int(w), int(h), bool(gpu), round(float(hz), 2),
           bool(ahead))
    if now != _state:
        _state = now
        mark("state", *now)


def _dump() -> None:
    try:
        with open(PATH, "w", encoding="utf-8") as fh:
            for r in _rows:
                fh.write(json.dumps(r) + "\n")
    except OSError:
        pass


if ON:
    atexit.register(_dump)
