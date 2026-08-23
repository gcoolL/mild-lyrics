"""Making sure the audio and the timings are talking about the same second.

This is the part that decides whether training works at all, so it is worth
saying plainly what goes wrong without it.

The labels come from a person who timed the master. The audio comes from
wherever a copy could be fetched. About a quarter of copies are DISPLACED
against that master -- a radio edit, a re-upload with a beat of silence bolted
on the front, a different pressing -- by anything from 0.13 s to over a second,
with the singing inside them otherwise perfect. Cut a three-second line out of
such a copy on the master's timings and a large part of what you saved is the
wrong words entirely, handed to the model as if it were right.

Two defences, and they are different in kind.

  1. A LENGTH CHECK, before any model exists. If the copy is longer than the
     track and the extra is silence at the front, that much is taken off. It is
     arithmetic on durations and silence, it needs nothing trained, and it
     catches the single commonest displacement there is.

  2. A MEASUREMENT, once a model exists. Align the whole song, pair the words
     with the reference's words, and take the median difference. That is the
     displacement, in the same units the reference is in.

What is deliberately NOT here: guessing the shift by sliding the reference's
line starts against the copy's loudest moments. That was tried in this project,
checked against 104 songs, and agreed within 0.1 s on 61% of them while being
SIGN-FLIPPED on a good few -- +0.13 s where the truth was -0.28 s. Energy
coincidence locks onto the beat, and a drum half a beat away scores as sharply
as the voice. A wrong shift is worse than no shift, so a song this cannot
measure keeps the timings it came with.

Every measurement here is gated on its own spread. A song whose word errors are
scattered over a second has no displacement to speak of -- it has a bad
alignment, and its median is the middle of a mess, not an offset.
"""
from __future__ import annotations

import json
import pathlib
import statistics

from . import audio

STORE = pathlib.Path.home() / ".cache/mild-lyrics/sync/offsets.json"

# Below this a shift is not worth making: it is inside the model's own frame.
LEAST = 0.05
# A measurement is only believed if the errors around it are this tight.
SPREAD_MAX = 0.35
# And only if this many words could be paired.
PAIRS_MIN = 20


def lead_silence(wave, rate: int = audio.RATE, floor: float = -45.0) -> float:
    """Seconds of near-silence at the front of a waveform."""
    db = audio.loudness(wave)
    quiet = (db < floor).tolist()
    n = 0
    for q in quiet:
        if not q:
            break
        n += 1
    return n * audio.HOP / rate


def trim(wave, track_secs: float, rate: int = audio.RATE) -> tuple[float, str]:
    """How far this copy runs behind the master, from length and silence alone.

    Positive means the copy is late: everything in it happens that many seconds
    after the timings say, so a reference time `t` is found at `t + lag` in this
    audio.

    Only claims a shift when the two agree -- the copy is longer than the track
    by about as much as it is silent at the front. A copy that is longer for
    some other reason (a hidden track, a fade-out held longer, a live intro)
    has extra at the END, is not silent at the front, and is left alone.
    """
    if not track_secs or track_secs <= 0:
        return 0.0, ""
    have = wave.shape[-1] / rate
    extra = have - track_secs
    quiet = lead_silence(wave, rate)
    if extra < LEAST or quiet < LEAST:
        return 0.0, ""
    # The silence explains the length, within a quarter of a second.
    if abs(extra - quiet) > 0.25:
        return 0.0, (f"this copy is {extra:+.2f}s against the track but opens "
                     f"with {quiet:.2f}s of silence -- not shifting on that")
    lag = min(extra, quiet)
    return lag, (f"this copy is {extra:.2f}s longer than the track and opens "
                 f"with {quiet:.2f}s of silence -- it runs {lag:.2f}s late, "
                 f"and is read that way")


def summarise(errs: list[float]) -> dict:
    """Where a copy sits against its reference, from that song's word errors.

    `errs` is ours-minus-theirs per word. The sign convention, which is the
    one thing here worth being pedantic about, is the same as trim()'s: a
    positive lag means the copy is LATE, so a reference time `t` is found at
    `t + lag` in this audio, and a clip for that line is cut there. A copy with
    a beat of silence bolted on the front makes our alignment report every word
    late, which is a positive median and a positive lag.

    Returns {lag, spread, pairs, trusted, why}. `trusted` is the only field a
    caller should act on. It is false when too few words paired, and false when
    the errors are scattered too widely for a median to be a displacement at
    all -- that song has a bad alignment, and shifting its clips by the middle
    of a mess moves them somewhere no better and possibly worse.
    """
    if len(errs) < PAIRS_MIN:
        return {"lag": 0.0, "spread": 0.0, "pairs": len(errs), "trusted": False,
                "why": f"only {len(errs)} word(s) paired"}
    med = statistics.median(errs)
    # The median absolute deviation, not the standard deviation: one word
    # placed in the wrong verse must not decide whether a song is believed.
    spread = statistics.median([abs(e - med) for e in errs])
    trusted = spread <= SPREAD_MAX
    return {"lag": round(float(med), 3), "spread": round(float(spread), 3),
            "pairs": len(errs), "trusted": bool(trusted),
            "why": "" if trusted else
                   f"errors scatter by {spread:.2f}s -- a bad alignment, "
                   f"not a displacement"}


def load(path=STORE) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(rows: dict, path=STORE) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, sort_keys=True), encoding="utf-8")


def for_song(name: str, rows: dict | None = None) -> float:
    """The measured displacement for a song, or 0.0 if it has none worth using."""
    row = (rows if rows is not None else load()).get(name)
    if not isinstance(row, dict) or not row.get("trusted"):
        return 0.0
    lag = float(row.get("lag") or 0.0)
    return lag if abs(lag) >= LEAST else 0.0
