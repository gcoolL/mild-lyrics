"""The song's beat grid, for drawing behind the words and snapping drags to:
an onset envelope, a tempo from its autocorrelation, and beats placed by
dynamic programming (Ellis 2007). numpy only. Notes: docs/notes/editor/beats.md."""
from __future__ import annotations

import pathlib

SR = 22050
HOP = 256                   # 11.6 ms a frame
N_FFT = 512                 # 23 ms: a longer window hears a hit early (93 ms: 21 ms)
BANDS = 64
TIGHT = 100.0               # how hard the grid resists changing its gap
LOW_BANDS = 6               # the bands under ~160 Hz: where the kick is
KEPT = 1                    # in the kept file's name; bump to redo them all


def _mono(path: str):
    """The song as mono float32 at SR, or None."""
    import audio_analysis
    return audio_analysis.decode(str(path), SR)


def _mel_bank():
    import numpy as np
    m = lambda f: 2595.0 * np.log10(1.0 + f / 700.0)
    pts = 700.0 * (10.0 ** (np.linspace(m(30.0), m(8000.0), BANDS + 2) / 2595.0) - 1.0)
    bins = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    down = (bins[:, None] - pts[None, :-2]) / np.diff(pts)[None, :-1]
    up = (pts[None, 2:] - bins[:, None]) / np.diff(pts)[None, 1:]
    return np.clip(np.minimum(down, up), 0.0, None).astype("float32")


def onsets(x):
    """Energy arriving, one value a frame, over every band and over the bands
    under 160 Hz alone: half-wave log-mel flux less its running mean."""
    import numpy as np
    win = np.hanning(N_FFT).astype("float32")
    bank = _mel_bank()
    pad = np.concatenate([np.zeros(N_FFT // 2, "float32"), x,
                          np.zeros(N_FFT, "float32")])
    n = len(x) // HOP + 1
    rows = []
    for a in range(0, n, 2048):
        idx = np.arange(a, min(n, a + 2048)) * HOP
        fr = pad[idx[:, None] + np.arange(N_FFT)] * win
        p = (np.abs(np.fft.rfft(fr, axis=1)) ** 2).astype("float32") @ bank
        rows.append(10.0 * np.log10(np.maximum(p, 1e-10)))
    db = np.concatenate(rows)
    db = np.maximum(db, db.max() - 80.0)
    rise = np.clip(np.diff(db, axis=0), 0.0, None)
    k = int(round(0.5 * SR / HOP))

    def less_mean(flux):
        flux = np.concatenate([[0.0], flux])
        mean = np.convolve(flux, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
        env = np.clip(flux - mean, 0.0, None)
        return env / (env.std() + 1e-9)

    low = (np.arange(BANDS) < LOW_BANDS)
    return less_mean(rise.mean(axis=1)), less_mean(rise[:, low].mean(axis=1))


def period(env):
    """The beat's length in frames: the envelope's autocorrelation, leaning
    towards 120 bpm, with the peak's fraction found."""
    import numpy as np
    # Softened first: a peak a frame wide misses itself at a whole-frame lag
    # when the beat is not a whole number of frames, and its double wins.
    g = np.arange(-6, 7)
    env = np.convolve(env, np.exp(-0.5 * (g / 2.0) ** 2), mode="same")
    n = len(env)
    f = np.fft.rfft(env - env.mean(), 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    fps = SR / HOP
    lo, hi = int(fps * 60 / 240), min(n - 2, int(fps * 60 / 40))
    lags = np.arange(lo, hi)
    bpm = 60.0 * fps / lags
    lean = np.exp(-0.5 * np.log2(bpm / 120.0) ** 2)
    k = lo + int(np.argmax(ac[lo:hi] * lean))
    a, b, c = ac[k - 1], ac[k], ac[k + 1]
    bend = a - 2 * b + c
    return k + (0.5 * (a - c) / bend if bend < 0 else 0.0)


def track(x):
    """(beat times in seconds, bpm) of mono samples at SR."""
    import numpy as np
    env, low = onsets(x)
    if len(env) < 4 * SR / HOP or env.max() <= 0:
        return np.zeros(0), 0.0
    p = period(env)
    g = np.arange(-int(p), int(p) + 1)
    local = np.convolve(env, np.exp(-0.5 * (g * 32.0 / p) ** 2), mode="same")
    near, far = int(round(p / 2)), int(round(2 * p))
    back = np.arange(-far, -near + 1)
    cost = -TIGHT * np.log(-back / p) ** 2
    score = local.copy()
    link = np.full(len(env), -1)
    for t in range(far, len(env)):
        cand = score[t + back] + cost
        j = int(np.argmax(cand))
        if cand[j] > 0:
            score[t] += cand[j]
            link[t] = t + back[j]
    peaks = [t for t in range(1, len(score) - 1)
             if score[t] >= score[t - 1] and score[t] >= score[t + 1]]
    if not peaks:
        return np.zeros(0), 0.0
    top = np.median(score[peaks])
    t = max(q for q in peaks if score[q] >= 0.5 * top)
    out = []
    while t >= 0:
        out.append(t)
        t = link[t]
    out = np.array(out[::-1])
    # Before the music and after it the grid only extrapolates: drop beats
    # where nothing lands near them.
    strong = local[out] > 0.5 * np.median(local[out])
    if strong.any():
        a, b = np.argmax(strong), len(strong) - np.argmax(strong[::-1])
        out = out[a:b]
    if len(out) < 4:
        return np.zeros(0), 0.0
    # The grid can lock onto off-beat hats, which fill more bands than the
    # kick does; a kick landing between the beats moves it half a beat.
    near = lambda f: low[np.clip(np.round(f).astype(int) + np.arange(-2, 3)[:, None],
                                 0, len(low) - 1)].max(axis=0).mean()
    mids = (out[:-1] + out[1:]) / 2.0
    if near(mids) > 1.5 * near(out):
        out = np.concatenate([mids, [out[-1] + (out[-1] - out[-2]) / 2.0]])
    return out * HOP / SR, 60.0 * SR / HOP / p


def for_song(path: str, keep: pathlib.Path | None = None):
    """(beats, bpm) of a song file, read back from `keep` when it was found
    before."""
    import numpy as np
    if keep is not None and keep.exists():
        try:
            z = np.load(keep)
            return z["beats"], float(z["bpm"][0])
        except Exception:
            keep.unlink(missing_ok=True)
    x = _mono(path)
    if x is None:
        raise ValueError("the audio could not be read")
    beats, bpm = track(x)
    if keep is not None:
        try:
            keep.parent.mkdir(parents=True, exist_ok=True)
            np.savez(keep, beats=beats, bpm=np.array([bpm]))
        except Exception:
            pass
    return beats, bpm


def grid(beats, split: int):
    """The beats with `split - 1` evenly spaced points between each pair."""
    import numpy as np
    beats = np.asarray(beats, dtype="float64")
    if split <= 1 or len(beats) < 2:
        return beats
    gaps = np.diff(beats)
    sub = beats[:-1, None] + gaps[:, None] * (np.arange(split) / split)[None, :]
    return np.concatenate([sub.ravel(), beats[-1:]])
