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
