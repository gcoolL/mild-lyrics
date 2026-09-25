"""The separated vocal, for the vocal view: demucs, and what is read off it.

Optional. Everything in here stands on torch, torchaudio and demucs, which
the rest of the program no longer needs, so nothing imports this until the
vocal view is asked for -- and `available` says whether it can be, and why
not, without importing any of it.
"""
from __future__ import annotations

import importlib.util


def available() -> tuple[bool, str]:
    """(True, "") where the vocal view can run here, else (False, why)."""
    missing = [name for name in ("torch", "torchaudio", "demucs", "soundfile")
               if importlib.util.find_spec(name) is None]
    if missing:
        return False, ("the vocal view needs " + ", ".join(missing)
                       + " installed alongside the editor — until then it "
                         "shows the waveform")
    return True, ""
