"""How the vocal view is drawn, as the person timing likes it.

Brightness, contrast, which part of the spectrum, the colours, and how tall
the attack trace stands -- set in Settings, under Vocal view. All of it is
the picture only: no mark, no time and no measurement in `vocalmap` reads
these.
"""
from __future__ import annotations

from . import keys as K
from . import theme as T
from . import vocalmap

BANDS = 80
LOW_HZ, HIGH_HZ = vocalmap.MEL_HZ
COLOURS = ("Accent", "Heat", "Ice", "Grey")
DEFAULT = {"voc_bright": 50.0, "voc_contrast": 50.0, "voc_low_hz": LOW_HZ,
           "voc_high_hz": HIGH_HZ, "voc_colours": "Accent", "voc_trace": 42.0}


def look(cfg: dict | None = None) -> dict:
    """The look in `cfg` (the saved settings by default), every field present
    and in range, with the band range as mel rows."""
    cfg = K.config() if cfg is None else cfg
    out = {}
    for k in ("voc_bright", "voc_contrast", "voc_trace"):
        try:
            out[k] = max(0.0, min(100.0, float(cfg.get(k, DEFAULT[k]))))
        except (TypeError, ValueError):
            out[k] = DEFAULT[k]
    lo = _band(cfg.get("voc_low_hz", LOW_HZ), LOW_HZ)
    hi = _band(cfg.get("voc_high_hz", HIGH_HZ), HIGH_HZ)
    # Crossed or too close: the low end wins, and four rows stay shown.
    lo = min(lo, BANDS - 4)
    out["low"], out["high"] = lo, max(hi, lo + 4)
    c = cfg.get("voc_colours")
    out["voc_colours"] = c if c in COLOURS else DEFAULT["voc_colours"]
    return out


def _band(hz, fallback: float) -> int:
    try:
        hz = float(hz)
    except (TypeError, ValueError):
        hz = fallback
    return vocalmap.hz_band(hz, BANDS)


def floor_pct(lk: dict) -> float:
    """Brightness as the percentile that draws black: 70 at 0, 40 at 50."""
    return 70.0 - 0.6 * lk["voc_bright"]


def gamma(lk: dict) -> float:
    """Contrast as the ramp's curve: 1.35 at 50, a third or three times that
    at the ends."""
    return 1.35 * 3.0 ** ((lk["voc_contrast"] - 50.0) / 50.0)


def bands(lk: dict) -> tuple[int, int] | None:
    """The mel rows shown, or None for all of them."""
    lo, hi = lk["low"], lk["high"]
    return None if (lo, hi) == (0, BANDS) else (lo, hi)


def trace(lk: dict) -> float:
    """The attack trace's height, as a share of the picture; 0 hides it."""
    return lk["voc_trace"] / 100.0


def ramp(lk: dict) -> tuple:
    """The colour stops, dark to bright."""
    bg = T.INK_1
    stops = {"Accent": (bg, T.LEAD, T.TEXT),
             "Heat": (bg, "#5b2a86", "#e8743b", "#fff1a8"),
             "Ice": (bg, "#1f4e79", "#5fd3e6", "#f4fdff"),
             "Grey": (bg, "#f2f2f2")}[lk["voc_colours"]]
    return tuple(_rgb(c) for c in stops)


def _rgb(c: str) -> tuple[int, int, int]:
    q = T.q(c)
    return q.red(), q.green(), q.blue()
