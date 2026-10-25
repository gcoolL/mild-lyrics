"""A per-frame record of the player's pacing (steps, paints, swaps), written as
JSON lines at exit when MILD_FRAME_TRACE names a file; off, one attribute
test."""
from __future__ import annotations

import atexit
import json
import os
import time

import frame_clock as FCK

PATH = os.environ.get("MILD_FRAME_TRACE", "")
ON = bool(PATH)
KEEP = 400_000          # about half an hour at 240 frames a second

_rows: list = []
_state = None


mono = FCK.mono


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
