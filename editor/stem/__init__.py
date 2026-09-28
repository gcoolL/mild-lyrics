"""The separated vocal, for the vocal view: demucs, and what is read off it.

Optional. Everything in here stands on torch, torchaudio and demucs, which
the rest of the program no longer needs, so nothing imports this until the
vocal view is asked for -- and `available` says whether it can be, and why
not, without importing any of it.
"""
from __future__ import annotations

import contextlib
import importlib.util
import os


def available() -> tuple[bool, str]:
    """(True, "") where the vocal view can run here, else (False, why)."""
    missing = [name for name in ("torch", "torchaudio", "demucs", "soundfile")
               if importlib.util.find_spec(name) is None]
    if missing:
        return False, ("the vocal view needs " + ", ".join(missing)
                       + " installed alongside the editor — until then it "
                         "shows the waveform")
    return True, ""


@contextlib.contextmanager
def spare_cores(keep: int = 2):
    """Let torch use all but `keep` cores while the body runs.

    Torch takes every core it is given, and a separation on the CPU runs for
    minutes: the window and the audio player it shares the machine with are
    starved for all of them. The count is put back when the body is done, and
    is only ever lowered, so a machine with few cores is not asked for more
    than torch would have used.
    """
    import torch
    was = torch.get_num_threads()
    want = max(1, (os.cpu_count() or 1) - keep)
    try:
        if want < was:
            torch.set_num_threads(want)
        yield
    finally:
        with contextlib.suppress(Exception):
            torch.set_num_threads(was)
