"""What the audio itself says about where the singing is.

WHY THIS EXISTS. Separation changes what a frame of silence MEANS. On a
mixture, a quiet vocal sits under a loud guitar and frame energy says nothing
about whether anybody is singing; on a separated vocal it very nearly says
exactly that. The aligner has never looked. `audio.loudness` has been in this
package the whole time and only `offset.lead_silence` ever called it.

WHAT IT IS FOR. The CTC lattice has no way to say "no lyric happens here". A
path crossing an instrumental can only idle in blank, and idling is cheap --
which is the peakiness that `ctcalign.levelled` exists to fight and only partly
wins. The measured failure is not scattered error: it is a handful of spans a
song, seconds out, where the singing stops and the path wanders. Frame energy
from a separated vocal is close to a ground-truth answer for exactly those
frames, so it is worth more than another 6,000 training steps.

ONSETS. The other half is where a word STARTS. The model already emits a
word-start channel that nothing reads (model.py:84, channel 0). Spectral flux
-- how much the spectrum jumped since the last frame -- is the classic
complement to it, and note onsets improving lyrics-to-audio alignment is a
result old enough to be uncontroversial. On a separated vocal a flux peak is a
sung attack rather than a snare.

EVERYTHING IS ON THE 20 MS GRID, audio.FRAME, the same grid as the model's
emissions and every time in every file this package writes. The two things
this reads -- audio.loudness and audio.mel -- are both on the 10 ms hop, so
both are reduced by audio.STRIDE here and nowhere else.
"""
from __future__ import annotations

import torch

from . import audio

# Below this many dB under the loudest frame, treat a frame as silence. A sung
# note and the room tone after it differ by far more than this; the value only
# has to sit in the gap.
FLOOR = -38.0
SOFT = 8.0            # dB over which "silent" fades into "singing"


def _to_frames(fine: torch.Tensor, frames: int | None = None) -> torch.Tensor:
    """A 10 ms series reduced to the 20 ms grid, by pairs."""
    n = fine.shape[0] - (fine.shape[0] % audio.STRIDE)
    out = fine[:n].reshape(-1, audio.STRIDE).mean(dim=1)
    if frames is None:
        return out
    if out.shape[0] < frames:                      # pad with the last value
        tail = out[-1:].expand(frames - out.shape[0]) if out.numel() else \
            torch.zeros(frames - out.shape[0])
        return torch.cat([out, tail])
    return out[:frames]


def activity(wave, frames: int | None = None) -> torch.Tensor:
    """Per frame, 0 where nothing is being sung and 1 where something is.

    Relative to the song's own loudest frame, not an absolute level, because
    two copies of the same song can differ by 10 dB of mastering and neither
    is wrong.
    """
    db = torch.as_tensor(audio.loudness(wave)).float()
    if not db.numel():
        return torch.zeros(frames or 0)
    quiet = db.max() + FLOOR
    # A soft edge, not a threshold: a hard gate would put a cliff in the
    # emissions at a frame chosen by a hair of level, and the path would take
    # the cliff seriously.
    return _to_frames(((db - quiet) / SOFT).sigmoid(), frames)


def onsets(wave, frames: int | None = None, device: str = "cpu") -> torch.Tensor:
    """Per frame, how much the spectrum jumped -- 0..1, peaks at attacks."""
    mel = audio.mel(wave, device).float().cpu()          # (fine frames, 80)
    if mel.shape[0] < 2:
        return torch.zeros(frames or 0)
    # Half-wave rectified: an attack is energy ARRIVING. Energy leaving is the
    # end of a note and belongs to the boundary head's other channel.
    flux = (mel[1:] - mel[:-1]).clamp_min(0).sum(dim=1)
    flux = torch.cat([flux[:1], flux])
    top = torch.quantile(flux, 0.99).clamp_min(1e-6)
    return _to_frames((flux / top).clamp(0, 1), frames)


def gate(logp, present, weight: float = 1.0, blank: int | None = None):
    """The emissions, with silence made expensive to spell through.

    `present` is `activity()`. Where it is 0 the frame gets a blank bonus of
    `weight` nats, and where it is 1 nothing changes -- so a path crossing an
    instrumental is not merely allowed to idle in blank, it is paid to. What
    this cannot do is move a word: it only makes the gaps between words honest.

    Nothing is subtracted from the letters. Penalising letters in quiet frames
    sounds equivalent and is not: it drives the path to spell the whole lyric
    inside whatever is loud, which on a song with one loud chorus is a way to
    lose the verses.
    """
    from . import text
    if weight <= 0 or present is None:
        return logp
    blank = text.BLANK if blank is None else blank
    present = present.to(logp.device)[:logp.shape[0]]
    if present.shape[0] < logp.shape[0]:
        present = torch.cat(
            [present, present[-1:].expand(logp.shape[0] - present.shape[0])])
    out = logp.clone()
    out[:, blank] = out[:, blank] + weight * (1.0 - present)
    return out


# ------------------------------------------------------- pitch, for training
# Note onsets and phoneme starts are temporally correlated -- a singer changes
# note where a syllable begins far more often than in the middle of one -- so a
# head made to predict F0 alongside the letters pushes that correlation into
# the encoder, where the CTC head can use it. See "Improving Lyrics Alignment
# through Joint Pitch Detection" (arXiv 2202.01646). The head is thrown away at
# inference; only what it did to the body is kept.
LOW, HIGH = 65.0, 1000.0      # Hz: below a bass voice, above a whistle register


def track(wave, frames: int | None = None):
    """(frames, 2): how high the note is, and how much it just changed.

    NOT voicing. A voicing channel was tried and is degenerate on this data:
    the clips are cut around words, so nearly every frame of nearly every clip
    is voiced, and a head learns nothing from a target that is almost always 1.
    (detect_pitch_frequency has no voicing decision of its own either -- it
    returns a confident frequency for silence.)

    What is left is the part the idea rests on: a singer changes note where a
    syllable begins far more often than in the middle of one, so the SECOND
    channel -- the size of the pitch change -- is a note-onset signal, and
    predicting it is what should push onset structure into the encoder.

    The height is log-scaled, because a semitone is a ratio and a linear target
    would spend all its resolution on the top octave.
    """
    import torchaudio.functional as AF
    w = torch.as_tensor(wave).float()
    if w.dim() == 1:
        w = w.unsqueeze(0)
    try:
        f0 = AF.detect_pitch_frequency(w, audio.RATE, frame_time=audio.FRAME,
                                       freq_low=int(LOW),
                                       freq_high=int(HIGH))[0]
    except Exception:
        # A clip too short for the estimator's window is not a training error.
        return torch.zeros((frames or 0), 2)
    lo, hi = torch.log(torch.tensor(LOW)), torch.log(torch.tensor(HIGH))
    height = ((torch.log(f0.clamp_min(LOW)) - lo) / (hi - lo)).clamp(0, 1)
    change = (height[1:] - height[:-1]).abs()
    # Octave errors are the estimator's characteristic failure and they look
    # like enormous note changes; clipped so they cannot dominate the loss.
    change = torch.cat([change[:1], change]).clamp(0, 0.2) * 5.0
    out = torch.stack([height, change], dim=-1)
    if frames is None:
        return out
    if out.shape[0] < frames:
        return torch.cat([out, torch.zeros(frames - out.shape[0], 2)])
    return out[:frames]


# ------------------------------------------------- a song's own standing bias
# One calibration constant for every song is a compromise. The model's lateness
# is not the same on a whispered ballad and a rapped verse, and the measured
# figures say so: three Dutch songs read 0.118-0.176s AHEAD of their reference
# and a fourth 0.192s BEHIND it, which no single number can absorb.
#
# The fix is to stop needing a reference. A sung attack is a fact about the
# recording, so the gap between where a word was placed and the attack it was
# placed on can be measured on the song itself -- no lyric, no donor, no
# language. What that gap agrees on is this song's bias, and it can simply be
# taken off.
# ---------------------------------------------------------------- the notes
# What a chopped vocal does instead of an attack.
#
# A flux peak is energy ARRIVING, and that is what a sung word does: a
# consonant, a breath, a new note struck. It is not what a CHOPPED vocal does.
# In the drop of a track built the way `Conro - Therapy` is, the lead IS the
# singer -- their own voice, cut into sixteenths and pitched up a fifth -- and
# it runs continuously: there is no gap for energy to arrive into, so the flux
# has nothing to fire on. Measured against gc's own timings on that song's
# chopped chorus, where the flux marks land 0.060 s from a syllable and only
# 43% of them within 50 ms, against 0.010 s and 71% on the sung verses of the
# same file.
#
# Every chop is a new NOTE, though, and that is readable: the pitch steps. On
# the same 74 syllables, note onsets land 0.039 s away with 61% inside 50 ms,
# and the two kinds of mark together 0.023 s with 72%.
#
# HOW THE PITCH IS FOUND. YIN (de Cheveigne & Kawahara 2002), in torch,
# because this package has torch and torchaudio and nothing else -- librosa's
# `pyin` scores a little better per mark but is a dependency the project does
# not have. The difference function is computed through the autocorrelation
# so a song is a couple of FFTs rather than a loop over lags.
PITCH_MIN = 70.0      # Hz. Below a bass voice; a bass line is not in the stem.
PITCH_MAX = 1200.0    # and above a whistle register or a pitched-up chop
PITCH_WIN = 1024      # 64 ms: two periods of the lowest pitch, and no more
# How periodic a frame has to be to be called a pitch at all. YIN's own
# threshold: the cumulative mean normalised difference at the chosen lag,
# where 0 is a perfect period and 1 is noise.
PITCH_APERIODIC = 0.20
# How far the pitch has to move to count as a new note, and over how long a
# window either side it is measured. A semitone is 100 cents; this is a bit
# over half of one, which is wider than vibrato (±30 c) and narrower than any
# interval anybody sings.
NOTE_STEP = 80.0
NOTE_WINDOW = 8       # frames of 10 ms either side
# How far past the threshold crossing to look for the bottom of the dip. The
# dip is a few samples wide at any pitch this reads, and stopping the walk
# keeps it from falling into the next one, an octave down.
DIP_REACH = 24


def pitch(wave, hop: int = audio.HOP) -> torch.Tensor:
    """f0 per 10 ms frame in Hz, NaN where the frame is not periodic.

    YIN: the difference between the frame and itself shifted by every lag in
    range, normalised so that a long lag is not automatically cheaper, then
    the first lag that dips under `PITCH_APERIODIC` -- the first, not the
    best, which is what keeps it from answering an octave down.
    """
    wave = torch.as_tensor(wave).float()
    if wave.dim() > 1:
        wave = wave.mean(dim=0)
    win = PITCH_WIN
    if wave.shape[0] < win + hop:
        return torch.full((max(1, wave.shape[0] // hop),), float("nan"))
    frames = wave.unfold(0, win, hop)                     # (n, win)
    frames = frames - frames.mean(dim=1, keepdim=True)
    half = win // 2
    lo = max(2, int(audio.RATE / PITCH_MAX))
    hi = min(half - 1, int(audio.RATE / PITCH_MIN))
    if hi <= lo:
        return torch.full((frames.shape[0],), float("nan"))
    # r(tau) for every lag at once, through the FFT. The correlation is
    # between the ANALYSIS window -- the first half of the frame -- and the
    # whole frame, so that r(tau) sums the same samples the energy terms
    # below count. Correlating the frame with itself instead makes r(tau)
    # shorter as tau grows and the difference function comes out tilted,
    # which reads as a pitch a whole tone off.
    size = 1 << (2 * win - 1).bit_length()
    full = torch.fft.rfft(frames, size)
    head = torch.fft.rfft(frames[:, :half], size)
    acf = torch.fft.irfft(full * head.conj(), size)[:, :half + 1]
    # the energy of the window and of the same window shifted by tau
    sq = (frames ** 2)
    cum = torch.cat([torch.zeros(frames.shape[0], 1), sq.cumsum(dim=1)], dim=1)
    first = cum[:, half:half + 1] - cum[:, :1]            # x[0:half]
    taus = torch.arange(half + 1)
    shifted = cum[:, taus + half] - cum[:, taus]          # x[tau:tau+half]
    diff = (first + shifted - 2 * acf).clamp_min(0.0)
    # cumulative mean normalisation: d(tau) against the mean of d(1..tau)
    run = diff[:, 1:].cumsum(dim=1)
    means = run / torch.arange(1, half + 1).float()
    cmnd = torch.ones_like(diff)
    cmnd[:, 1:] = diff[:, 1:] / means.clamp_min(1e-12)
    band = cmnd[:, lo:hi + 1]
    under = band < PITCH_APERIODIC
    # The FIRST lag under the threshold, not the best one: the best is as
    # likely to be an octave down, where the signal also repeats.
    idx = torch.where(under.any(dim=1), under.float().argmax(dim=1),
                      band.argmin(dim=1))
    # ...then down to the bottom of that dip. The threshold is crossed on the
    # way INTO the dip, a few samples before the period itself, and stopping
    # at the crossing reads every pitch about 5% sharp -- 98 Hz as 103.
    reach = torch.arange(DIP_REACH)
    walk = (idx[:, None] + reach).clamp(max=band.shape[1] - 1)
    vals = band.gather(1, walk)
    rising = torch.zeros_like(vals, dtype=torch.bool)
    rising[:, 1:] = vals[:, 1:] > vals[:, :-1]
    after = torch.cummax(rising.int(), dim=1).values.bool()
    vals = torch.where(after, torch.full_like(vals, float("inf")), vals)
    idx = walk.gather(1, vals.argmin(dim=1, keepdim=True)).squeeze(1)
    best = band.gather(1, idx[:, None]).squeeze(1)
    lag = (idx + lo).float()
    # parabolic interpolation around the dip, for a period between samples
    rows = torch.arange(frames.shape[0])
    li = (idx + lo).clamp(1, half - 1)
    y0 = cmnd[rows, li - 1]
    y1 = cmnd[rows, li]
    y2 = cmnd[rows, li + 1]
    denom = (y0 - 2 * y1 + y2)
    shift = torch.where(denom.abs() > 1e-12, 0.5 * (y0 - y2) / denom,
                        torch.zeros_like(denom))
    lag = lag + shift.clamp(-1.0, 1.0)
    f0 = audio.RATE / lag.clamp_min(1e-6)
    ok = (best < PITCH_APERIODIC) & (f0 >= PITCH_MIN) & (f0 <= PITCH_MAX)
    return torch.where(ok, f0, torch.full_like(f0, float("nan")))


# Two note onsets closer together than this are the same one: a chop spliced
# onto the one before it steps in pitch AND leaves a frame or two unvoiced at
# the join, and both of those are the same chop starting. It is also about the
# shortest a sung syllable gets, so nothing real is lost by merging.
NOTE_LEAST = 0.05


def notes(f0, floor: float = NOTE_STEP, window: int = NOTE_WINDOW,
          hop_secs: float = audio.HOP / audio.RATE,
          least: float = NOTE_LEAST) -> list[float]:
    """The times a new note starts, in seconds.

    Two kinds, and they are the same event seen from either side: the pitch
    STEPS -- the median of the frames before differs from the median of the
    frames after by more than `floor` cents -- or voicing RESUMES after a gap,
    which is a chop with silence in front of it or a consonant.

    Medians either side rather than a difference between neighbours, because
    an f0 track is noisy frame to frame and vibrato swings further than some
    intervals. Over 80 ms the wobble averages out and a step does not.
    """
    f0 = torch.as_tensor(f0).float()
    n = int(f0.shape[0])
    if n < window * 2 + 2:
        return []
    good = torch.isfinite(f0)
    if int(good.sum()) < window:
        return []
    cents = 1200.0 * torch.log2(f0.clamp_min(1e-6) / 55.0)
    # The last known pitch is carried across an unvoiced gap rather than the
    # gap being left as a hole: a hole reads as a step at both of its edges,
    # so every breath would have arrived as two notes.
    held = torch.where(good, cents, torch.zeros_like(cents))
    keep = torch.where(good, torch.arange(n), torch.zeros(n, dtype=torch.long))
    keep = torch.cummax(keep, dim=0).values
    filled = held[keep]
    before = torch.nn.functional.pad(filled[None, None], (window, 0),
                                     mode="replicate")[0, 0]
    after = torch.nn.functional.pad(filled[None, None], (0, window),
                                    mode="replicate")[0, 0]
    left = before.unfold(0, window, 1)[:n].median(dim=1).values
    right = after.unfold(0, window, 1)[:n].median(dim=1).values
    step = torch.where(good, (right - left).abs(), torch.zeros(n))
    # A step measured between two medians does not peak on one frame: it is
    # flat for about `window` frames either side of the join, because that is
    # how long both windows straddle it. Taking every frame at the top gives
    # one note per frame of the plateau, and taking the first gives one half a
    # window early -- so the run is found and its middle is the onset.
    half = max(1, window // 2)
    peaks: list[int] = []
    for i in range(1, n - 1):
        if float(step[i]) < floor:
            continue
        lo, hi = max(0, i - half), min(n, i + half + 1)
        if float(step[i]) >= float(step[lo:hi].max()):
            peaks.append(i)
    out: list[float] = []
    run: list[int] = []
    for i in peaks + [10 ** 9]:
        if run and i - run[-1] > window:
            out.append(sum(run) / len(run) * hop_secs)
            run = []
        if i < 10 ** 9:
            run.append(i)
    for i in range(1, n):
        if bool(good[i]) and not bool(good[i - 1]):
            out.append(i * hop_secs)
    kept: list[float] = []
    for t in sorted(set(round(t, 3) for t in out)):
        if not kept or t - kept[-1] >= least:
            kept.append(t)
    return kept


NEAR = 0.30           # seconds: how far from a word start to look for its attack
PEAK = 0.25           # how strong a flux peak must be to count as an attack


def attacks(onset, floor: float = PEAK) -> list[float]:
    """The times of the sung attacks in an onset track, in seconds."""
    if onset is None or not len(onset):
        return []
    out = []
    for i in range(len(onset)):
        if onset[i] < floor:
            continue
        lo, hi = max(0, i - 2), min(len(onset), i + 3)
        if onset[i] >= float(onset[lo:hi].max()):
            out.append(i * audio.FRAME)
    return out


def drift(starts, onset, near: float = NEAR) -> dict:
    """How far this song's word starts sit from the attacks they land on.

    Returns offset.summarise's verdict: a median lag, the spread around it, how
    many words voted, and whether that is tight enough to act on. Positive
    means the words sit AFTER the attacks -- the file runs late.
    """
    import bisect
    from . import offset
    beats = attacks(onset)
    if not beats or not starts:
        return {"lag": 0.0, "spread": 0.0, "pairs": 0, "trusted": False,
                "why": "nothing to measure against"}
    gaps = []
    for at in starts:
        k = bisect.bisect_left(beats, at)
        for cand in (k - 1, k):
            if 0 <= cand < len(beats) and abs(at - beats[cand]) <= near:
                gaps.append(at - beats[cand])
                break
    return offset.summarise(gaps)
