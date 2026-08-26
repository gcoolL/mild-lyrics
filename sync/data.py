"""The clips the model learns from, and the split it is never allowed to see.

A row of the manifest is one song; a clip is one LINE of it, cut on the
timings whoever uploaded the lyric wrote by hand. The audio is the separated
vocal at 16 kHz, already on disk as float32.

Two things here matter more than they look.

THE SPLIT IS BY SONG, AND BY NAME. Lines from one song share a voice, a mix
and half their words, so a split that puts some of a song's lines in training
and the rest in validation is measuring memorisation. And the split is a hash
of the song's NAME rather than a shuffle, so it does not move when the dataset
grows -- a model trained last week and a model trained tonight are still
comparable, and a song that arrives twice under two track ids cannot land on
both sides.

THE CLIPS ARE spl ONLY. That is enforced where they are cut (dataset.py), not
here, but it is the reason this file can be simple: every label in the manifest
was typed by a person against this recording, so a disagreement between the
model and the label is the model's fault, which is what training needs to be
true.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import torch

from . import audio, text

DATA = pathlib.Path.home() / ".cache/mild-lyrics/dataset"


def held(name: str, share: float = 0.08, salt: str = "sync") -> bool:
    """Is this song held out? Stable in the name, so it never drifts."""
    digest = hashlib.sha1(f"{salt}:{name}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF < share


GOLD_HOLD = 0.25


def gold_split(names, share: float = GOLD_HOLD) -> frozenset:
    """Which of one person's songs are kept back to measure on. An exact count.

    A share of a small set has to be counted out, not sampled. Asking a hash
    "are you under 0.25?" for the 69 songs one hand has timed came back with
    five -- a three-sigma draw, and a benchmark half the width it was before
    the change that was supposed to widen it. Sorting by the hash and taking
    the first quarter gives a quarter, every time, while still being decided by
    the name rather than by the order the songs happened to arrive.

    Songs timed by one known hand are worth more as a benchmark than as
    training material: a benchmark made of one convention can see below the
    disagreement BETWEEN annotators, which is where this model now lives. Not
    all of them, though -- they are also the most precisely timed clips there
    are, and the boundary head learns exact positions from them.
    """
    names = sorted(set(names))
    ranked = sorted(names, key=lambda n: hashlib.sha1(
        f"gold:{n}".encode("utf-8")).hexdigest())
    return frozenset(ranked[:max(1, round(share * len(ranked)))])


def holdout(name: str, gold_held: frozenset | None = None,
            share: float = 0.08) -> bool:
    """Is this song held back? Gold songs by the list, everything else by hash."""
    if gold_held and name in gold_held:
        return True
    if gold_held is not None and name in getattr(gold_held, "all_gold", ()):
        return False          # a gold song kept for training, deliberately
    return held(name, share)


def songs(root=DATA) -> list[dict]:
    """Every song in a dataset directory, in the order it was gathered."""
    manifest = pathlib.Path(root).expanduser() / "manifest.jsonl"
    if not manifest.exists():
        raise SystemExit(f"no dataset at {manifest} -- run `sync dataset` first")
    out, seen = [], {}
    for row in manifest.read_text(encoding="utf-8").splitlines():
        try:
            got = json.loads(row)
        except Exception:
            continue
        # A song gathered twice keeps ONE row, and it is the LAST one: two
        # rows would double its weight in training, and a second cut is a
        # correction rather than a duplicate. `dataset build --recut` appends
        # the corrected row, so first-wins would have quietly kept the very
        # cut that was found to be wrong -- with the clips on disk already
        # replaced underneath it, which is worse than either alone.
        if not got.get("lines"):
            continue
        if got.get("tid") in seen:
            out[seen[got["tid"]]] = got
            continue
        seen[got["tid"]] = len(out)
        out.append(got)
    return out


class Clips(torch.utils.data.Dataset):
    """Line clips as (log-mel, tokens). Held-out songs in or out, never both."""

    def __init__(self, root=DATA, hold: float = 0.08, want: str = "train",
                 max_secs: float = 12.0, augment: bool = True,
                 gold: set | None = None, gold_hold: float = GOLD_HOLD,
                 gold_held: frozenset | None = None, wants: str = "mel",
                 pitch: bool = False, lines: bool = False):
        # "mel" for the small convolutional model, "wave" for a pretrained
        # encoder that reads the waveform itself. The only thing that changes
        # downstream is what a "length" counts -- frames or samples -- and
        # both models answer out_len() in their own units.
        self.wants = wants
        self.pitch = pitch and wants == "wave"
        self.lines = lines
        self.root = pathlib.Path(root).expanduser()
        self.augment = augment
        self.rows: list[tuple[str, str, list[list[float]]]] = []
        self.songs: list[str] = []
        for song in songs(self.root):
            out = holdout(song["name"], gold_held, hold)
            if (want == "held") != out:
                continue
            self.songs.append(song["name"])
            for clip in song["lines"]:
                label = text.line(clip.get("text", ""))
                if not label or clip.get("secs", 0) > max_secs:
                    continue
                # A clip must be long enough to hold its own label: CTC cannot
                # spell twelve symbols in six frames, and a batch containing
                # one is a batch with no gradient. With room to spare, because
                # stretch() may shorten it by a further eleven per cent.
                if audio.frames(clip["secs"]) * min(SPEEDS[0], 1 / SPEEDS[-1]) \
                        <= len(label) + 2:
                    continue
                self.rows.append((clip["clip"], label, clip.get("bounds") or [],
                                  clip.get("starts") or []))

    def __len__(self) -> int:
        return len(self.rows)

    def _other(self, name: str):
        """A clip from a DIFFERENT song, to play underneath this one.

        Different song matters: two lines of the same song share a voice and a
        backing, so mixing them makes a muddier version of the same thing
        rather than a distraction to learn to ignore.
        """
        import numpy as np
        import random
        mine = name.split("_")[0]
        for _ in range(4):
            pick = random.choice(self.rows)[0]
            if pick.split("_")[0] != mine:
                try:
                    return torch.from_numpy(np.load(self.root / "clips" / pick))
                except Exception:
                    return None
        return None

    def __getitem__(self, i: int):
        import numpy as np
        import random
        name, label, bounds, starts = self.rows[i]
        wave = torch.from_numpy(np.load(self.root / "clips" / name))
        if self.augment:
            wave = perturb(wave)

        if self.wants == "wave":
            # Normalised here, before anything pads it. See encoder.normalise.
            wave = (wave - wave.mean()) / (wave.std() + 1e-5)
            # No tempo stretch and no SpecAugment here: a pretrained encoder
            # brings its own masking (config.apply_spec_augment), and
            # stretching a waveform properly costs a second a clip.
            frames = max(1, wave.shape[-1] // 320 - 1)
            edge = _bounds(bounds, frames, 1.0)
            if self.pitch:
                # Channels 2 and 3: note height and note change, from the
                # audio itself. They ride along on the boundary tensor rather
                # than as a fifth item in the tuple, so no call site anywhere
                # changes -- ctcalign still reads channels 0 and 1 and knows
                # nothing about the rest.
                from . import vocal
                edge = torch.cat([edge, vocal.track(wave, frames)], dim=-1)
            # Appended LAST on purpose: channels 0 and 1 stay word start and
            # word end whatever else is switched on, so ctcalign and every
            # checkpoint that predates this keep reading what they always read.
            if self.lines:
                edge = torch.cat([edge, _line_starts(starts, frames, 1.0)], dim=-1)
            return (wave, torch.tensor(text.encode(label)), label, edge)

        if self.augment and random.random() < DISTRACT:
            wave = distract(wave, self._other(name))
        mel = audio.mel(wave)
        # Boundary targets are at the model's 20 ms output resolution.
        # The reference timing is soft: Gaussian peaks with 80 ms sigma.
        speed = random.choice(SPEEDS) if self.augment else 1.0
        if speed != 1.0:
            want = max(4, int(round(mel.shape[0] / speed)))
            mel = torch.nn.functional.interpolate(
                mel.transpose(0, 1).unsqueeze(0), size=want,
                mode="linear", align_corners=False
            )[0].transpose(0, 1)

        out_frames = max(1, int((mel.shape[0] + audio.STRIDE - 1) / audio.STRIDE))
        edge = _bounds(bounds, out_frames, speed)
        if self.lines:
            edge = torch.cat([edge, _line_starts(starts, out_frames, speed)], dim=-1)
        return (mel, torch.tensor(text.encode(label)), label, edge)


def _bounds(bounds, out_frames: int, speed: float = 1.0):
    """Word starts and ends as two soft channels, 80 ms wide, at 20 ms a frame.

    Soft rather than one-hot because a word start is not a frame, it is a
    moment somebody heard; and because a single frame's worth of positive
    signal in a four-second clip is a target a head can win by ignoring.
    """
    boundary = torch.zeros(out_frames, 2, dtype=torch.float32)
    sigma = 0.08 / audio.FRAME
    radius = max(2, int(round(3.0 * sigma)))
    for st, en in bounds:
        for seconds, channel in ((float(st) / speed, 0), (float(en) / speed, 1)):
            center = seconds / audio.FRAME
            c = int(round(center))
            lo, hi = max(0, c - radius), min(out_frames, c + radius + 1)
            if hi <= lo:
                continue
            x = torch.arange(lo, hi, dtype=torch.float32)
            vals = torch.exp(-0.5 * ((x - center) / sigma) ** 2)
            boundary[lo:hi, channel] = torch.maximum(boundary[lo:hi, channel], vals)
    return boundary


def _line_starts(starts, out_frames: int, speed: float = 1.0):
    """Where a LYRIC LINE begins, as one soft channel.

    The same shape as a word start, and deliberately so: the head is being
    asked which word starts are also line starts, not to find a different kind
    of event. In a grouped clip most word starts are not line starts, which is
    the whole reason grouped clips exist -- see dataset._runs.
    """
    line = torch.zeros(out_frames, 1, dtype=torch.float32)
    sigma = 0.08 / audio.FRAME
    radius = max(2, int(round(3.0 * sigma)))
    for st in starts or []:
        center = (float(st) / speed) / audio.FRAME
        c = int(round(center))
        lo, hi = max(0, c - radius), min(out_frames, c + radius + 1)
        if hi <= lo:
            continue
        x = torch.arange(lo, hi, dtype=torch.float32)
        vals = torch.exp(-0.5 * ((x - center) / sigma) ** 2)
        line[lo:hi, 0] = torch.maximum(line[lo:hi, 0], vals)
    return line


SPEEDS = (0.88, 0.94, 1.0, 1.06, 1.12)

# How often a clip gets another song mixed into it, and how far down.
DISTRACT = 0.5
DISTRACT_SNR = (4.0, 18.0)


def distract(wave, other):
    """`wave` with another song playing under it, the label unchanged.

    This is aimed at a failure that was measured rather than guessed at. On the
    songs this model cannot align -- dense guitar mixes -- separating the vocal
    fixes the alignment while the model's evidence AT THE TRUE WORDS does not
    improve at all (-4.50 to -4.55 on one, -3.74 to -3.98 on another). So the
    words were never the problem. What beat the search was everything else in
    the mix scoring well enough somewhere else to pull the path off.

    A model trained only on clean-ish mixes has no reason to learn that. Give
    it a second song underneath and the labelled words are still the only thing
    it is asked to spell, so the only way to keep the loss down is to stop
    treating unlabelled music as evidence.

    Note what this is NOT: adding separated vocals as extra clips. That teaches
    a model that the instrumental is ABSENT, which is the opposite lesson and
    would leave it just as helpless on the mixes that fail.
    """
    import random
    if other is None or other.numel() < 16:
        return wave
    if other.shape[-1] < wave.shape[-1]:
        other = other.repeat((wave.shape[-1] // other.shape[-1]) + 1)
    at = random.randint(0, max(0, other.shape[-1] - wave.shape[-1]))
    other = other[at:at + wave.shape[-1]]
    snr = random.uniform(*DISTRACT_SNR)
    here = float(wave.pow(2).mean().sqrt())
    there = float(other.pow(2).mean().sqrt())
    if there < 1e-6 or here < 1e-6:
        return wave
    return wave + other * (here / there) * (10 ** (-snr / 20))


def perturb(wave):
    """A little noise under the singing, before the spectrogram is taken.

    The vocal stem is a separation, and how much of the band bleeds through it
    varies from song to song. A model that has only ever heard clean
    separations reads another song's bleed as silence.
    """
    import random
    snr = random.uniform(12.0, 40.0)
    level = float(wave.pow(2).mean().sqrt()) * (10 ** (-snr / 20))
    return wave + torch.randn_like(wave) * level


def stretch(mel):
    """The same singing, a little faster or slower.

    Done on the spectrogram rather than the waveform, by interpolating the time
    axis. Resampling the audio properly costs a second a clip -- a thousand
    times what reading the clip costs -- and buys nothing here: a syllable held
    for 300 ms and the same syllable held for 340 ms are the same word, which
    is the whole point of the augmentation, and stretching the frames says
    exactly that.
    """
    import random
    speed = random.choice(SPEEDS)
    if speed == 1.0:
        return mel
    want = max(4, int(round(mel.shape[0] / speed)))
    got = torch.nn.functional.interpolate(
        mel.transpose(0, 1).unsqueeze(0), size=want, mode="linear",
        align_corners=False)
    return got[0].transpose(0, 1)


def mask(mel, bands: int = 2, band: int = 16, times: int = 3, span: int = 25):
    """SpecAugment: hide a few bands and a few moments, in place.

    Ten hours of singing is not much to learn a language from, and the fastest
    way for a small model to waste it is to memorise a singer's timbre. Cutting
    bands out forces it to spread its evidence across the spectrum; cutting
    time out forces it to keep the words in order when it cannot hear one.
    """
    import random
    T, F = mel.shape
    for _ in range(bands):
        w = random.randint(0, band)
        if w and F > w:
            f = random.randint(0, F - w)
            mel[:, f:f + w] = 0.0
    for _ in range(times):
        w = random.randint(0, span)
        if w and T > w:
            t = random.randint(0, T - w)
            mel[t:t + w, :] = 0.0
    return mel


def batches(rows, augment: bool = True):
    """Pad mels, CTC targets, and boundary targets."""
    rows = sorted(rows, key=lambda r: -r[0].shape[0])
    mels, targets, labels, boundary = zip(*rows)
    if mels[0].dim() == 1:
        # Waveforms, for a pretrained encoder that reads audio directly. The
        # shape of a "length" is the only thing that differs -- samples rather
        # than spectrogram frames -- and each model answers out_len() in its
        # own units, so nothing downstream has to know which it got.
        lengths = torch.tensor([w.shape[0] for w in mels])
        widths = torch.tensor([t.shape[0] for t in targets])
        padded = torch.zeros(len(mels), int(lengths.max()))
        edge = torch.zeros(len(mels), max(b.shape[0] for b in boundary),
                           boundary[0].shape[1])
        for i, w in enumerate(mels):
            padded[i, :w.shape[0]] = w
            edge[i, :boundary[i].shape[0]] = boundary[i]
        return padded, lengths, torch.cat(targets), widths, list(labels), edge
    if augment:
        mels = [mask(m.clone()) for m in mels]
    lengths = torch.tensor([m.shape[0] for m in mels])
    widths = torch.tensor([t.shape[0] for t in targets])
    maxlen = int(lengths.max())
    padded = torch.zeros(len(mels), maxlen, mels[0].shape[1])
    padded_boundary = torch.zeros(len(mels),
                                  max(b.shape[0] for b in boundary),
                                  boundary[0].shape[1])
    for i, m in enumerate(mels):
        padded[i, :m.shape[0]] = m
        padded_boundary[i, :boundary[i].shape[0]] = boundary[i]
    return padded, lengths, torch.cat(targets), widths, list(labels), padded_boundary


def loader(clips: Clips, batch: int = 16, shuffle: bool = True,
           workers: int = 4, augment: bool = True):
    import functools
    # A partial rather than a lambda: the worker processes are started by
    # pickling this, and a lambda defined in here cannot be pickled at all.
    return torch.utils.data.DataLoader(
        clips, batch_size=batch, shuffle=shuffle, num_workers=workers,
        collate_fn=functools.partial(batches, augment=augment),
        drop_last=shuffle, persistent_workers=workers > 0)
