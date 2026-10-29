"""The visualiser's readings from audio (loudness, pitch classes, beats) in the
shape of Spotify's analysis; live (`Analyser`) or a whole file (`analyse`).
Notes: docs/notes/mild-lyrics/live_audio.md."""
from __future__ import annotations

import collections
import shutil
import subprocess

SR = 22050
HOP = 1024                  # 46ms a row
N = 2048                    # loudness and beats: the newest 93ms
NC = 4096                   # chroma: long enough to tell semitones apart down to ~110Hz
BEAT_GAP = 0.28             # the closest two beats may land
HISTORY = 3.0               # seconds of flux the beat threshold is taken over


def usable() -> str:
    """"" when live analysis can run here, else why not (for the toast)."""
    try:
        import numpy  # noqa: F401
    except Exception:                                       # noqa: BLE001
        return "needs numpy"
    return ""


class Analyser:
    """Mono samples in, (t, loudness dB, chroma[12], beat 0..1 or 0) rows out.

    `t` is the middle of each frame, in whatever clock the caller stamps the
    last sample with: the media position for our own player, mono() for the
    mixer."""

    def __init__(self, sr: int = SR) -> None:
        import numpy as np
        self.np, self.sr = np, sr
        self.buf = np.zeros(0, np.float32)
        self.win = np.hanning(N).astype(np.float32)
        self.wic = np.hanning(NC).astype(np.float32)
        freqs = np.fft.rfftfreq(NC, 1.0 / sr)
        self.band = (freqs >= 80.0) & (freqs <= 5000.0)
        midi = 69.0 + 12.0 * np.log2(freqs[self.band] / 440.0)
        self.pc = np.round(midi).astype(int) % 12          # 0 = C, as Spotify's
        self.prev = None
        self.flux = collections.deque(maxlen=max(8, int(HISTORY * sr / HOP)))
        self.held: tuple | None = None      # last frame, waiting to see if it peaked
        self.last_beat = -1e9
        self.beats = collections.deque(maxlen=64)
        self.tempo = 0.0

    def feed(self, x, t_end: float) -> list:
        np = self.np
        self.buf = np.concatenate((self.buf, np.asarray(x, np.float32)))
        out = []
        start = 0
        while len(self.buf) - start >= NC:
            long = self.buf[start:start + NC]
            t = t_end - (len(self.buf) - start - NC + N / 2) / self.sr
            out += self._frame(long, t)
            start += HOP
        self.buf = self.buf[start:]
        return out

    def _frame(self, long, t: float) -> list:
        np = self.np
        frame = long[-N:]
        rms = float(np.sqrt(np.mean(frame * frame)))
        loud = 20.0 * np.log10(rms + 1e-9)
        mag = np.abs(np.fft.rfft(frame * self.win))
        cm = np.abs(np.fft.rfft(long * self.wic))
        c = np.bincount(self.pc, weights=cm[self.band], minlength=12)
        top = float(c.max())
        chroma = [round(float(v) / top, 3) for v in c] if top > 1e-6 else [0.0] * 12
        lm = np.log1p(10.0 * mag)
        fl = 0.0 if self.prev is None else float(np.maximum(lm - self.prev, 0.0).sum())
        self.prev = lm
        rows = []
        # A beat is a flux peak over the recent level: decided a frame late,
        # once the frame after it is lower.
        if self.held is not None:
            ht, hl, hc, hf = self.held
            hist = list(self.flux)
            beat = 0.0
            if len(hist) >= 8:
                m = sum(hist) / len(hist)
                sd = (sum((v - m) ** 2 for v in hist) / len(hist)) ** 0.5
                if hf > m + sd and hf >= fl and ht - self.last_beat >= BEAT_GAP:
                    beat = max(0.05, min(1.0, (hf - m) / (3.0 * sd + 1e-9)))
                    self.last_beat = ht
                    self.beats.append(ht)
                    self._tempo()
            rows.append((ht, hl, hc, beat))
            self.flux.append(hf)
        self.held = (t, loud, chroma, fl)
        return rows

    def _tempo(self) -> None:
        """The median gap of the last beats, folded into 70..180 bpm."""
        b = list(self.beats)[-17:]
        if len(b) < 5:
            return
        gaps = sorted(y - x for x, y in zip(b, b[1:]))
        g = gaps[len(gaps) // 2]
        if g <= 0:
            return
        bpm = 60.0 / g
        while bpm < 70:
            bpm *= 2
        while bpm > 180:
            bpm /= 2
        self.tempo = round(bpm, 1)


SECTION_WIN = 8               # seconds compared either side of a section change
SECTION_GAP = 12.0            # the shortest section


def decode(src: str, sr: int = SR):
    """A file or URL as mono float32 at `sr`: ffmpeg, else soundfile (local
    files it reads); None when neither can."""
    import numpy as np
    ff = shutil.which("ffmpeg")
    if ff:
        try:
            import noconsole
            run, run_path = noconsole.run, noconsole.real_path
        except Exception:                                   # noqa: BLE001
            run, run_path = subprocess.run, str
        try:
            got = run([ff, "-nostdin", "-v", "error", "-i", run_path(src), "-vn",
                                 "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                                capture_output=True, timeout=300)
            if got.returncode == 0 and len(got.stdout) > sr * 4:
                return np.frombuffer(got.stdout, np.float32)
        except Exception:                                   # noqa: BLE001
            pass
    if "://" in src:
        return None
    try:
        import soundfile as sf
        data, rate = sf.read(src, dtype="float32", always_2d=True)
    except Exception:                                       # noqa: BLE001
        return None
    x = data.mean(axis=1)
    if rate != sr:
        n = int(len(x) * sr / rate)
        x = np.interp(np.arange(n) * (rate / sr), np.arange(len(x)), x).astype(np.float32)
    return x


def analyse(x, sr: int = SR) -> dict:
    """A whole song's samples -> the dict Beat.load reads, rows as Analyser's.

    Knowing the whole song, a beat is judged against the flux either side of
    it, the tempo is the onset envelope's autocorrelation, and sections are
    where the 8s before and after differ most."""
    import numpy as np
    x = np.asarray(x, np.float32)
    if len(x) < NC + HOP * 64:
        return {}
    frames = np.lib.stride_tricks.sliding_window_view(x, NC)[::HOP]
    n = len(frames)
    t = (np.arange(n) * HOP + NC - N / 2) / sr
    win = np.hanning(N).astype(np.float32)
    wic = np.hanning(NC).astype(np.float32)
    freqs = np.fft.rfftfreq(NC, 1.0 / sr)
    pm = np.zeros((len(freqs), 12), np.float32)
    idx = np.nonzero((freqs >= 80.0) & (freqs <= 5000.0))[0]
    pm[idx, np.round(69.0 + 12.0 * np.log2(freqs[idx] / 440.0)).astype(int) % 12] = 1.0
    loud = np.empty(n, np.float32)
    flux = np.zeros(n, np.float32)
    chroma = np.empty((n, 12), np.float32)
    prev = None
    for a in range(0, n, 256):
        long = frames[a:a + 256]
        b = a + len(long)
        short = long[:, -N:]
        loud[a:b] = 20.0 * np.log10(np.sqrt((short * short).mean(axis=1)) + 1e-9)
        c = np.abs(np.fft.rfft(long * wic, axis=1)) @ pm
        chroma[a:b] = c / np.maximum(c.max(axis=1, keepdims=True), 1e-6)
        lm = np.log1p(10.0 * np.abs(np.fft.rfft(short * win, axis=1)))
        d = np.diff(lm, axis=0, prepend=(lm[:1] if prev is None else prev[None]))
        flux[a:b] = np.maximum(d, 0.0).sum(axis=1)
        prev = lm[-1]

    k = max(3, int(HISTORY * sr / HOP))
    box = np.ones(k) / k
    m = np.convolve(flux, box, "same")
    sd = np.sqrt(np.maximum(np.convolve(flux * flux, box, "same") - m * m, 0.0))
    mid = flux[1:-1]
    peak = (mid > flux[:-2]) & (mid >= flux[2:]) & (mid > m[1:-1] + sd[1:-1])
    beats, last = [], -1e9
    for i in np.nonzero(peak)[0] + 1:
        if t[i] - last >= BEAT_GAP:
            conf = float(np.clip((flux[i] - m[i]) / (3.0 * sd[i] + 1e-9), 0.05, 1.0))
            beats.append([round(float(t[i]), 3), round(conf, 3)])
            last = t[i]

    fps = sr / HOP
    env = np.maximum(flux - m, 0.0)
    env = env - env.mean()
    lags = np.arange(int(fps * 60 / 180), int(fps * 60 / 70) + 2)
    ac = np.array([float(np.dot(env[:-L], env[L:])) for L in lags])
    ac *= np.exp(-0.5 * (np.log2(60.0 * fps / lags / 120.0) / 0.5) ** 2)   # prior: near 120
    j = int(ac.argmax())
    lag = float(lags[j])
    if 0 < j < len(ac) - 1:
        den = ac[j - 1] - 2 * ac[j] + ac[j + 1]
        if den:
            lag += 0.5 * (ac[j - 1] - ac[j + 1]) / den
    tempo = round(60.0 * fps / lag, 1) if lag > 0 else 0.0

    per = max(1, int(round(fps)))                      # ~1s blocks
    nb = n // per
    sections = [0.0]
    if nb > 2 * SECTION_WIN + 2:
        lo, hi = np.percentile(loud, [10, 90])
        lv = np.clip((loud - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
        feat = np.concatenate((chroma[:nb * per].reshape(nb, per, 12).mean(axis=1),
                               lv[:nb * per].reshape(nb, per).mean(axis=1)[:, None] * 2.0),
                              axis=1)
        W = SECTION_WIN
        nov = np.zeros(nb)
        for i in range(W, nb - W):
            nov[i] = float(np.linalg.norm(feat[i - W:i].mean(axis=0) - feat[i:i + W].mean(axis=0)))
        live = nov[W:nb - W]
        bar = live.mean() + 0.5 * live.std()
        cand = [i for i in range(W, nb - W)
                if nov[i] > bar and nov[i] >= nov[i - 1] and nov[i] >= nov[i + 1]]
        took: list[float] = []
        for i in sorted(cand, key=lambda i: -nov[i]):
            at = i * per * HOP / sr
            if all(abs(at - o) >= SECTION_GAP for o in took + [0.0]):
                took.append(at)
        sections += sorted(round(s, 2) for s in took)

    return {"dur": round(len(x) / sr, 3), "tempo": tempo, "beats": beats,
            "sections": sections, "tatums": [],
            "segs": [[a, b] for a, b in zip(np.round(t, 3).tolist(),
                                            np.round(loud, 2).tolist())],
            "pitch": np.round(chroma, 3).tolist(), "timbre": []}


def song(src: str) -> dict:
    """decode + analyse; {} when the audio cannot be had."""
    x = decode(src)
    return analyse(x) if x is not None else {}


# ------------------------------------------------------------ one recording found in another
MATCH_SR = 11025
MATCH_HOP = 512               # 46ms a row
MATCH_WIN = 12.0              # seconds of the song compared at a time...
MATCH_STEP = 4.0              # ...every this often
MATCH_MIN = 0.6               # a window's score at its shift, 0..1, to count as found (measured 2026-10-22:
                              # the same recording 0.93-0.99, other songs 0.33 at most)
MATCH_JUMP = 0.25             # what a change of shift costs: repeated choruses score 0.9+ elsewhere too
MATCH_FAR = 0.5               # ...and more by how far it goes, in video lengths: of a chorus heard twice
                              # in a short film, the nearer (Thriller: the dance, not the end credits)
MATCH_EDGE = 0.4              # a stretch ends where its rows, over MATCH_EDGE_S, are this alike or less
MATCH_EDGE_S = 4.0            # (Thriller: the film's own 0.6-0.9, the wrong place 0.1-0.3)


def _match_rows(x):
    """Chroma rows for matching: log, centred and unit length, so loudness and mix count for little."""
    import numpy as np
    nw = 4 * MATCH_HOP
    frames = np.lib.stride_tricks.sliding_window_view(np.asarray(x, np.float32), nw)[::MATCH_HOP]
    freqs = np.fft.rfftfreq(nw, 1.0 / MATCH_SR)
    pm = np.zeros((len(freqs), 12), np.float32)
    idx = np.nonzero((freqs >= 80.0) & (freqs <= 5000.0))[0]
    pm[idx, np.round(69.0 + 12.0 * np.log2(freqs[idx] / 440.0)).astype(int) % 12] = 1.0
    win = np.hanning(nw).astype(np.float32)
    out = np.empty((len(frames), 12), np.float32)
    for a in range(0, len(frames), 512):
        out[a:a + 512] = np.log1p(100.0 * (np.abs(np.fft.rfft(frames[a:a + 512] * win, axis=1)) @ pm))
    out -= out.mean(axis=1, keepdims=True)
    out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-6)
    return out


def match(song, other) -> list:
    """Where the song's samples sit in another recording of it (a music video's sound), both mono
    at MATCH_SR: [(first, last, shift)] in the song's seconds, `other` having them `shift` later.
    Parts not found are left out; [] when none is."""
    import numpy as np
    a, b = _match_rows(song), _match_rows(other)
    fps = MATCH_SR / MATCH_HOP
    w, step = int(MATCH_WIN * fps), int(MATCH_STEP * fps)
    if len(a) < w or len(b) < w:
        return []
    starts = list(range(0, len(a) - w, step)) + [len(a) - w]
    n = 1 << int(np.ceil(np.log2(len(b) + w)))
    fb = np.fft.rfft(b, n, axis=0)
    scores, cands = [], []
    for s0 in starts:                  # each window against every place in `other`, by lag in rows
        sc = np.fft.irfft(np.conj(np.fft.rfft(a[s0:s0 + w], n, axis=0)) * fb, n, axis=0).sum(axis=1)
        sc = sc[:len(b) - w + 1] / w
        scores.append(sc)
        for _ in range(3):             # its best three, at least 2s apart
            j = int(sc.argmax())
            if sc[j] < MATCH_MIN:
                break
            cands.append(j - s0)
            sc = sc.copy()
            sc[max(0, j - int(2 * fps)):j + int(2 * fps)] = -1.0
    shifts = sorted(set(cands))
    if not shifts:
        return []
    merged = [shifts[0]]
    for d in shifts[1:]:
        if d - merged[-1] > 2:
            merged.append(d)
    shifts = merged

    def at(k: int, d: int) -> float:
        sc, j = scores[k], starts[k] + d
        lo, hi = max(0, j - 2), min(len(sc), j + 3)      # the clustered shift, give or take 2 rows
        return float(sc[lo:hi].max()) if lo < hi else -1.0
    # Viterbi over windows: a state per shift, and per shift a "not here" (scored MATCH_MIN) that
    # remembers where the video was, so a jump out of it still pays for its distance.
    N = len(shifts)
    m = np.array([[at(k, d) for d in shifts] + [MATCH_MIN] * N for k in range(len(starts))])
    sh = np.array(shifts, float)
    far = MATCH_JUMP + MATCH_FAR * np.abs(sh[:, None] - sh[None, :]) / len(b)
    np.fill_diagonal(far, 0.0)
    cost = np.full((2 * N, 2 * N), np.inf)
    cost[:N, :N] = far                                   # heard here -> heard elsewhere
    cost[N:, :N] = far                                   # not here -> heard elsewhere
    np.fill_diagonal(cost[N:, :N], MATCH_JUMP)           # ...or heard again where it was
    np.fill_diagonal(cost[:N, N:], MATCH_JUMP)           # heard -> not here
    np.fill_diagonal(cost[N:, N:], 0.0)
    best, back = m[0].copy(), []
    for k in range(1, len(starts)):
        move = best[:, None] - cost
        back.append(move.argmax(axis=0))
        best = move.max(axis=0) + m[k]
    path = [int(best.argmax())]
    for bk in reversed(back):
        path.append(int(bk[path[-1]]))
    path.reverse()
    path = [min(s, N) for s in path]                     # every "not here" as one

    runs: list = []                    # [state, first window, last window]
    for k, s in enumerate(path):
        if runs and runs[-1][0] == s and runs[-1][2] == k - 1:
            runs[-1][2] = k
        else:
            runs.append([s, k, k])
    runs = [r for r in runs if r[0] < len(shifts) and r[2] - r[1] >= 2]   # found, over three windows or more
    for k in range(len(runs) - 1, 0, -1):    # (a shorter one between two cuts was another chorus)
        if runs[k][0] == runs[k - 1][0]:
            runs[k - 1][2] = runs.pop(k)[2]
    out = []
    for s, k0, k1 in runs:             # the shift to a fraction of a row, over the whole run
        lo, hi = starts[k0], starts[k1] + w
        d0 = shifts[s]
        tot = []
        for d in range(d0 - 3, d0 + 4):
            j0, j1 = max(lo, -d), min(hi, len(b) - d)
            tot.append(float((a[j0:j1] * b[j0 + d:j1 + d]).sum() / max(1, j1 - j0)) if j1 > j0 else -1.0)
        i = int(np.argmax(tot))
        d = float(d0 - 3 + i)
        if 0 < i < len(tot) - 1:
            den = tot[i - 1] - 2 * tot[i] + tot[i + 1]
            if den < 0:
                d += 0.5 * (tot[i - 1] - tot[i + 1]) / den
        out.append([lo / fps, hi / fps, d / fps, int(d0), starts[k0], starts[k1]])
    for p, q in zip(out, out[1:]):     # where two runs meet: the row where the later shift takes over
        lo, hi = p[5], q[4] + w        # (p's last window to q's first, gap or overlap)
        if hi > lo:
            j = np.arange(lo, hi)
            def sim(dd: int):
                k = j + dd
                ok = (k >= 0) & (k < len(b))
                v = np.full(len(j), -1.0)
                v[ok] = (a[j[ok]] * b[k[ok]]).sum(axis=1)
                return v
            gain = np.cumsum(sim(p[3]) - sim(q[3]))
            cut = (lo + int(gain.argmax()) + 1) / fps
            p[1], q[0] = cut, cut
    kern = np.ones(int(MATCH_EDGE_S * fps) | 1) / (int(MATCH_EDGE_S * fps) | 1)
    for r in out:                      # its ends where the video has another part of the song there
        j = np.arange(int(round(r[0] * fps)), min(len(a), int(round(r[1] * fps))))
        k = j + r[3]
        ok = (k >= 0) & (k < len(b))
        v = np.zeros(len(j))
        v[ok] = (a[j[ok]] * b[k[ok]]).sum(axis=1)
        good = np.nonzero(np.convolve(v, kern, mode="same") > MATCH_EDGE)[0]
        if len(good):
            r[0], r[1] = max(r[0], j[good[0]] / fps), min(r[1], (j[good[-1]] + 1) / fps)
    return [(round(float(f), 3), round(float(l), 3), round(float(d), 3)) for f, l, d, *_r in out]


# ------------------------------------------------------------ the lyrics' offset, heard from the song
# Measured 2026-10-26 on 17 held-out songs, each at ten known shifts (0 to 4s) and under
# another song's lyrics: no wrong answer, 27 of 119 shifts past 0.3s found; under 0.3s it is
# a song's own scatter (about 0.15s), so those are said and not used. docs/notes/mild-lyrics/audio_analysis.md.
OFFSET_REV = 1                # kept offsets made by another revision are heard again
VOCAL_SR = 11025
VOCAL_N = 1024
VOCAL_HOP = 128               # 11.6ms a row
VOCAL_BAND = (150.0, 4000.0)  # where a voice sits; centre minus side, so what is panned out goes
OFFSET_REACH = 6.0            # seconds either way looked at
OFFSET_NEAR = 0.3             # nearer 0 than this: not told apart from right
OFFSET_RATIO = 1.5            # the peak over the next one 0.5s away (wrong answers reached 1.34)
OFFSET_ADV = 1.0              # ...and over the best near 0, in the curve's sd: whole bars score near it
OFFSET_HALF_ADV = 0.5
OFFSET_AGREE = 0.15           # both halves of the lyrics on the same shift
OFFSET_MIN_ANCHORS = 8


def decode_stereo(src: str, sr: int = VOCAL_SR):
    """A file or URL as (n, 2) float32 at `sr` by ffmpeg, or None."""
    import numpy as np
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    try:
        import noconsole
        run, run_path = noconsole.run, noconsole.real_path
    except Exception:                                       # noqa: BLE001
        run, run_path = subprocess.run, str
    try:
        got = run([ff, "-nostdin", "-v", "error", "-i", run_path(src), "-vn",
                   "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, timeout=300)
    except Exception:                                       # noqa: BLE001
        return None
    if got.returncode != 0 or len(got.stdout) < sr * 8 * 4:
        return None
    x = np.frombuffer(got.stdout, np.float32)
    return x[:len(x) // 2 * 2].reshape(-1, 2)


def vocal_rows(x2) -> dict:
    """Stereo samples -> {"fps", "level", "rise"}: the centre's voice band, summed in log, and how
    much it grows a row (onsets). Centre = |L+R| - |L-R| per bin, so a mono file is all centre."""
    import numpy as np
    x2 = np.asarray(x2, np.float32)
    if len(x2) < VOCAL_N + VOCAL_HOP * 256:
        return {}
    win = np.hanning(VOCAL_N).astype(np.float32)
    freqs = np.fft.rfftfreq(VOCAL_N, 1.0 / VOCAL_SR)
    band = np.nonzero((freqs >= VOCAL_BAND[0]) & (freqs <= VOCAL_BAND[1]))[0]
    fl = np.lib.stride_tricks.sliding_window_view(x2[:, 0], VOCAL_N)[::VOCAL_HOP]
    fr = np.lib.stride_tricks.sliding_window_view(x2[:, 1], VOCAL_N)[::VOCAL_HOP]
    n = len(fl)
    level = np.empty(n, np.float32)
    rise = np.empty(n, np.float32)
    prev = None
    for a in range(0, n, 1024):
        sl = np.fft.rfft(fl[a:a + 1024] * win, axis=1)[:, band]
        sr_ = np.fft.rfft(fr[a:a + 1024] * win, axis=1)[:, band]
        lg = np.log1p(100.0 * np.maximum(np.abs(sl + sr_) - np.abs(sl - sr_), 0.0) * 0.5)
        level[a:a + len(lg)] = lg.sum(axis=1)
        d = np.diff(lg, axis=0, prepend=(lg[:1] if prev is None else prev[None]))
        rise[a:a + len(lg)] = np.maximum(d, 0.0).sum(axis=1)
        prev = lg[-1]
    return {"fps": VOCAL_SR / VOCAL_HOP, "t0": VOCAL_N / 2 / VOCAL_SR, "level": level, "rise": rise}


def song_vocals(src: str) -> dict:
    """decode_stereo + vocal_rows; {} when the audio cannot be had."""
    x = decode_stereo(src)
    return vocal_rows(x) if x is not None else {}


def _zs(a):
    a = a - a.mean()
    return a / (a.std() + 1e-9)


def _offset_curve(rows: dict, spans: list, anchors: list):
    """How well the lyrics sit on the voice at every shift: the sung spans against the level
    (against its own 4-8s surroundings), plus the entries against the onsets, each z-scored."""
    import numpy as np
    fps, t0 = rows["fps"], rows["t0"]
    level, rise = rows["level"], rows["rise"]
    n = len(level)
    box = lambda a, s: np.convolve(a, np.ones(max(1, int(s * fps))) / max(1, int(s * fps)), "same")
    lv = box(level, 0.25)
    lv = lv - box(lv, 8.0)
    on = np.maximum(rise - box(rise, 2.0), 0.0)
    sung = np.zeros(n, np.float32)
    for s, e in spans:
        sung[max(0, int((s - t0) * fps)):max(0, min(n, int((e - t0) * fps) + 1))] = 1.0
    hits = np.zeros(n, np.float32)
    for s in anchors:
        i = int(round((s - t0) * fps))
        if 0 <= i < n:
            hits[i] += 1.0
    k = int(0.2 * fps)
    hits = np.convolve(hits, np.exp(-0.5 * (np.arange(-k, k + 1) / (0.05 * fps)) ** 2), "same")
    L = 1 << int(np.ceil(np.log2(2 * n)))
    lags = np.arange(-int(OFFSET_REACH * fps), int(OFFSET_REACH * fps) + 1)

    def xc(a, b):
        cc = np.fft.irfft(np.fft.rfft(_zs(a), L) * np.conj(np.fft.rfft(_zs(b), L)), L) / n
        return _zs(cc[lags % L])
    return lags / fps, xc(lv, sung) + xc(on, hits)


def _offset_peak(lags, c):
    """(best shift, its lead over the best near 0 in sd)."""
    import numpy as np
    j = int(c.argmax())
    z = int(np.argmax(np.where(np.abs(lags) <= OFFSET_NEAR, c, -np.inf)))
    return float(lags[j]), float((c[j] - c[z]) / (c.std() + 1e-9)), j


def lyric_offset(rows: dict, spans: list, anchors: list) -> dict:
    """How late the song's voice is against the lyrics, from vocal_rows: {} when there is too
    little to go on, else {"delta", "ratio", "adv", "spread", "n", "sure"}. `sure` only past
    OFFSET_NEAR: nearer than that is within what this can tell."""
    import numpy as np
    if not rows or len(anchors) < OFFSET_MIN_ANCHORS:
        return {}
    lags, c = _offset_curve(rows, spans, anchors)
    best, adv, j = _offset_peak(lags, c)
    far = np.abs(lags - best) > 0.5
    ratio = float(c[j] / max(float(c[far].max()), 1e-9))
    mid = (anchors[len(anchors) // 2 - 1] + anchors[len(anchors) // 2]) / 2.0
    halves = []
    for keep in (lambda t: t < mid, lambda t: t >= mid):
        hs = [(s, e) for s, e in spans if keep(s)]
        ha = [t for t in anchors if keep(t)]
        hb, hadv, _j = _offset_peak(*_offset_curve(rows, hs, ha))
        halves.append((hb, hadv))
    spread = abs(halves[0][0] - halves[1][0])
    sure = (abs(best) > OFFSET_NEAR and ratio >= OFFSET_RATIO and adv >= OFFSET_ADV
            and all(abs(hb - best) <= OFFSET_AGREE and hadv >= OFFSET_HALF_ADV for hb, hadv in halves))
    return {"delta": round(best, 3), "ratio": round(ratio, 2), "adv": round(adv, 2),
            "spread": round(spread, 3), "n": len(anchors), "sure": bool(sure)}
