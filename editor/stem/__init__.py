"""The separated vocal for the vocal view: demucs and what is read off it.
Optional (torch, torchaudio, demucs); `available` says whether, without
importing them."""
from __future__ import annotations

import contextlib
import importlib.util
import os


def available(separate: bool = True) -> tuple[bool, str]:
    """(True, "") where the vocal view can run here, else (False, why).
    `separate` False: a vocal is supplied, so demucs is not needed."""
    want = ("torch", "torchaudio", "demucs", "soundfile") if separate else (
        "torch", "torchaudio", "soundfile")
    missing = [name for name in want if importlib.util.find_spec(name) is None]
    if missing:
        return False, ("the vocal view needs " + ", ".join(missing)
                       + " installed alongside the editor — until then it "
                         "shows the waveform"
                       + ("" if separate or "demucs" in missing else
                          " (your own vocal does not need demucs)"))
    return True, ""


@contextlib.contextmanager
def spare_cores(keep: int = 2):
    """Let torch use all but `keep` cores while the body runs, restoring the
    count after; only ever lowered."""
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
