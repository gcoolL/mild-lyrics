"""Does everybody's copy of the song start at the same moment?

Each person in a session times against their own copy, and two copies of one
recording can differ at the start: a little more silence, a trimmed fade-in,
a different encoder's padding. Then everybody's taps are true to their own
copy and a fraction of a second out from everybody else's.

So the host sends its copy's loudness outline -- the same readings the
waveform is drawn from, a hundred a second, a byte each: about 24KB for a
four-minute song and nothing anyone could listen to -- and each joiner lines
its own outline up against it. What is compared is where the sound STARTS
(the rise in loudness, on a log scale), not how loud it is, so two masters
at different levels still agree.

Only a clear answer is acted on. The best match has to stand well above
every other shift tried, and above the second best by a margin; anything
less is reported as "could not tell", never guessed at.
"""
from __future__ import annotations

import base64
import pathlib
import tempfile

HZ = 100                 # readings a second, as waveform.envelope makes them
REACH = 15.0             # the furthest apart two copies are looked for, in s
MAX_SECONDS = 3600.0
MIN_SECONDS = 20.0       # less than this is not enough song to go on
SURE_Z = 8.0             # how far the best match must stand above the rest
SURE_RATIO = 1.25        # ...and above the next best, away from itself
NEGLIGIBLE = 0.03        # closer than this is the same, to a tapping finger


def pack(env) -> str:
    """An outline as it travels: one byte a reading, base64."""
    import numpy as np
    e = np.clip(np.asarray(env, dtype="float32"), 0.0, 1.0)
    return base64.b64encode((e * 255.0 + 0.5).astype("uint8").tobytes()).decode()


def unpack(text, hz) -> "object":
    """An outline from the host, checked: the rate this protocol uses, a
    length a song can have. Raises ValueError otherwise."""
    import numpy as np
    if hz != HZ or not isinstance(text, str):
        raise ValueError("outline rate")
    if len(text) > int(MAX_SECONDS * HZ * 4 / 3) + 8:
        raise ValueError("outline too long")
    raw = base64.b64decode(text, validate=True)
    if len(raw) < MIN_SECONDS * HZ:
        raise ValueError("outline too short")
    return np.frombuffer(raw, dtype="uint8").astype("float32") / 255.0


def _onsets(env):
    import numpy as np
    e = np.log(np.asarray(env, dtype="float64") + 1e-3)
    o = np.maximum(0.0, np.diff(e, prepend=e[:1]))
    o -= o.mean()
    sd = o.std()
    return o / sd if sd > 0 else o


def measure(theirs, mine) -> tuple[float | None, str]:
    """How much later this copy starts than theirs, in seconds -- or None,
    with why not. Positive: this copy has more before the music starts."""
    import numpy as np
    a, b = _onsets(theirs), _onsets(mine)
    if min(len(a), len(b)) < MIN_SECONDS * HZ:
        return None, "not enough of the song to compare"
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(b, n) * np.conj(np.fft.rfft(a, n)), n)
    reach = int(REACH * HZ)
    lags = np.concatenate([np.arange(0, reach + 1), np.arange(-reach, 0)])
    vals = np.concatenate([corr[:reach + 1], corr[n - reach:]])
    best = int(np.argmax(vals))
    z = (vals[best] - vals.mean()) / (vals.std() or 1.0)
    away = np.abs(lags - lags[best]) > int(0.25 * HZ)
    second = vals[away].max() if away.any() else 0.0
    ratio = vals[best] / second if second > 0 else float("inf")
    if z < SURE_Z or ratio < SURE_RATIO:
        return None, (f"no clear match (z {z:.1f}, ratio {ratio:.2f}) — "
                      "they may be different recordings")
    # Refine to between readings with the parabola through the peak.
    i = best
    lo, hi = vals[i - 1] if i > 0 else vals[i], vals[(i + 1) % len(vals)]
    den = lo - 2 * vals[i] + hi
    frac = 0.5 * (lo - hi) / den if den else 0.0
    return (float(lags[i]) + float(np.clip(frac, -0.5, 0.5))) / HZ, ""


def shifted(path: str, late: float) -> str:
    """A copy of `path` moved by `late` seconds -- cut from the start when it
    starts late, silence put in front when early -- so that it lines up
    with the host's. One such copy is kept at a time, in the temp folder."""
    import numpy as np
    import soundfile
    room = pathlib.Path(tempfile.gettempdir()) / "mild-lyrics-aligned"
    room.mkdir(exist_ok=True)
    for old in room.glob("*.wav"):
        if old.resolve() != pathlib.Path(path).resolve():
            old.unlink(missing_ok=True)
    out = room / f"{pathlib.Path(path).stem}.{'late' if late > 0 else 'early'}" \
                 f"{abs(late) * 1000:.0f}ms.wav"
    with soundfile.SoundFile(str(path)) as src:
        rate, ch = src.samplerate, src.channels
        with soundfile.SoundFile(str(out), "w", samplerate=rate, channels=ch,
                                 subtype="PCM_16") as dst:
            if late > 0:
                src.seek(min(src.frames, int(round(late * rate))))
            else:
                pad = int(round(-late * rate))
                dst.write(np.zeros((pad, ch), dtype="float32"))
            for block in src.blocks(blocksize=rate * 10, dtype="float32",
                                    always_2d=True):
                dst.write(block)
    return str(out)
