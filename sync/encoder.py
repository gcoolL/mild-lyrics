"""The same synchroniser, on an encoder that has already heard speech.

Everything else in this package stays: the CTC lattice in ctcalign.py, the
prior levelling, the offset measurements, the benchmark, the TTML writer. Only
the thing that turns sound into per-frame symbol scores is replaced.

WHY. The from-scratch model was trained on 26 hours of singing and, on songs it
had never seen, averaged half a second of error -- a real improvement on the
11-hour version and nowhere near the 50 ms a hand-timed lyric is written to.
The failures were not search failures; they were the model not perceiving the
vocal. wav2vec2-base has been pretrained on ~960 hours of speech and fine-tuned
to transcribe it, which is roughly a hundred times the audio this project can
gather, and it starts where the small model was trying to arrive.

WHAT IS KEPT ANYWAY. The heads are ours and start from noise: the same 29
symbols, and the same two boundary channels for word starts and ends. The
pretrained part knows speech; nothing has taught it singing, or this alphabet,
or where a syllable is held -- that is what the clips are for.

THE FRAME GRID IS THE REASON THIS IS A DROP-IN. wav2vec2 emits one frame per
320 samples at 16 kHz, which is 20 ms: exactly audio.FRAME, exactly what
SyncNet produced after its stride-2 stem. Every time in every downstream file
means the same thing before and after this swap.

WHAT IT COSTS. 95M parameters against 5.6M, so it is slower and wants more of
the card. The convolutional feature extractor stays frozen -- it is a
waveform front end, it is already good, and freezing it is the difference
between fitting on this GPU and not.
"""
from __future__ import annotations

import pathlib

import torch
from torch import nn

from . import audio, text

NAME = "facebook/wav2vec2-base-960h"
# The bigger encoder already on this disk: the same architecture at 24 layers,
# 60,000 hours of pretraining against base's 960, and fine-tuned for
# multilingual PHONEME recognition rather than English words -- which is
# nearer to what alignment needs, and does not assume the lyric is English.
# Only its body is used; its phoneme head is discarded with everything else.
LARGE = "facebook/wav2vec2-lv-60-espeak-cv-ft"
# MULTILINGUAL, at base size. The 24-layer LARGE above was measured on the gold
# songs and lost badly (1.187s against 0.395s), so "bigger" is not the lesson
# to draw from a model that cannot hear Dutch; "pretrained on more than
# English" is. This one is the same 12 layers and ~95M parameters as the
# default -- so it fits the same card and the same batch -- but its
# pretraining is 10,000 hours across 23 European languages, Dutch among them.
#
# The case that motivates it: Krantenwijk 1:35 reads 0.043 letter confidence
# where Dutch normally reads 0.14-0.16 on the base encoder, and the aligner
# prefers the WRONG place because the model hears the lyric better there.
VOXPOPULI = "facebook/wav2vec2-base-10k-voxpopuli"
STRIDE = 320          # samples per output frame -- 20 ms, the same as audio.FRAME


class Wav2VecSync(nn.Module):
    """A pretrained speech encoder with this project's two heads on top."""

    wants = "wave"     # not mel: this one reads the waveform itself

    def __init__(self, name: str = NAME, drop: float = 0.1,
                 classes: int = text.SIZE, freeze_extractor: bool = True,
                 train_top: int = 0, pitch: bool = False,
                 lines: bool = False):
        super().__init__()
        from transformers import Wav2Vec2Model
        self.name = name
        self.body = Wav2Vec2Model.from_pretrained(name)
        if freeze_extractor:
            self.body.feature_extractor._freeze_parameters()
        width = self.body.config.hidden_size
        self.drop = nn.Dropout(drop)
        self.head = nn.Linear(width, classes)
        # Two channels, or four with a pitch head bolted on: word start, word
        # end, note height, note change. The extra two are a TRAINING device
        # only -- ctcalign reads channels 0 and 1 and nothing else -- and they
        # are part of the same Linear so that no call site, saver or loader
        # anywhere has to know whether this model was trained with them.
        self.pitch = pitch
        # And one more for a LINE start, always last, so channels 0 and 1 stay
        # word start and word end no matter what else is switched on. A model
        # trained without any of this still emits two and still loads.
        self.lines = lines
        self.boundary = nn.Linear(width, 2 + (2 if pitch else 0) + (1 if lines else 0))
        for layer in (self.head, self.boundary):
            nn.init.trunc_normal_(layer.weight, std=0.02)
            nn.init.zeros_(layer.bias)
        # Train only the top `train_top` layers, if asked. A 317M model needs
        # about 5.7 GB for weights and Adam states alone and this card has
        # roughly 5 GB free with a desktop on it, so the large encoder fits
        # only if most of it holds still. The top layers are the ones that
        # carry phonetic detail; the lower ones are closer to a spectrogram
        # and have little to learn from 26 hours of singing.
        self.train_top = train_top
        if train_top:
            layers = self.body.encoder.layers
            for n, layer in enumerate(layers):
                if n < len(layers) - train_top:
                    for q in layer.parameters():
                        q.requires_grad = False
            for q in self.body.feature_projection.parameters():
                q.requires_grad = False
        self.drop_p, self.classes = drop, classes

    def forward(self, wave):
        """(batch, samples) -> (log-probs, boundary logits), 20 ms a frame."""
        if wave.dim() == 1:
            wave = normalise(wave).unsqueeze(0)
        # NOTE: batches arrive already normalised, per clip, over each clip's
        # OWN samples -- see normalise(). Doing it here instead, across a
        # padded row, is what collapsed the first fine-tune: a two-second clip
        # padded into a ten-second batch takes four fifths of its mean and
        # spread from the padding, so the real audio is mis-scaled and the pad
        # becomes a constant block that attention mixes into the real frames.
        # After 8000 steps the model emitted the same distribution at every
        # frame -- blank 0.841, min 0.841 -- which is a model that has stopped
        # listening.
        hidden = self.body(wave).last_hidden_state
        hidden = self.drop(hidden)
        return (nn.functional.log_softmax(self.head(hidden), dim=-1),
                self.boundary(hidden))

    def out_len(self, samples: int) -> int:
        """Frames out for that many samples in."""
        return self.body._get_feat_extract_output_lengths(
            torch.tensor(samples)).item()

    def context(self) -> int:
        """Output frames of context a frame's answer leans on.

        A transformer attends everywhere, so this is not exact arithmetic the
        way it was for a stack of convolutions. Two seconds is a working
        answer: it is well past the receptive field of the convolutional front
        end, and windowed inference trims that much off each seam.
        """
        return int(2.0 / audio.FRAME)

    @property
    def config(self) -> dict:
        return {"name": self.name, "drop": self.drop_p,
                "classes": self.classes, "train_top": self.train_top,
                "pitch": self.pitch, "lines": self.lines}

    def size(self) -> str:
        n = sum(p.numel() for p in self.parameters())
        train = sum(p.numel() for p in self.parameters() if p.requires_grad)
        return f"{n / 1e6:.0f}M parameters ({train / 1e6:.0f}M trained)"


def normalise(wave):
    """One clip, zero mean and unit spread, over its own samples and no others."""
    return (wave - wave.mean()) / (wave.std() + 1e-5)


def build(config: dict | None = None) -> Wav2VecSync:
    return Wav2VecSync(**(config or {}))


def load(path, device: str = "cpu") -> tuple[Wav2VecSync, dict]:
    got = torch.load(path, map_location=device, weights_only=False)
    if got.get("alphabet") not in (None, text.SYMBOLS):
        raise ValueError(f"{path} was trained on a different alphabet")
    model = build(got.get("config"))
    model.load_state_dict(got["weights"], strict=False)
    model.has_boundary = any(k.startswith("boundary.") for k in got["weights"])
    model.to(device).eval()
    return model, {k: v for k, v in got.items() if k != "weights"}


@torch.no_grad()
def emit(model, wave, device: str = "cpu", window: float = 20.0,
         overlap: float | None = None):
    """Log-probabilities for a whole song, in windows, joined without a seam.

    Windows are shorter here than for the small model -- attention costs the
    square of the input, and a four-minute song in one piece does not fit. The
    trim either side is the model's stated context, so what is thrown away is
    strictly more than what could have been affected by the missing sound.
    """
    model.eval()
    wave = wave.to(device)
    total = model.out_len(wave.shape[-1])
    span = max(4, int(window / audio.FRAME))
    guard = (model.context() if overlap is None
             else max(2, int(overlap / audio.FRAME))) // 2
    step = span - 2 * guard
    if total <= span:
        ctc, bound = model(wave)
        return ctc[0].float().cpu(), bound[0].float().cpu()

    out = torch.empty(total, model.classes)
    # As many boundary channels as the model actually has, not two. A model
    # trained with the pitch task emits four -- word start, word end, note
    # height, note change -- and hardcoding two here made every windowed
    # inference on such a model die at the first seam. Only channels 0 and 1
    # are ever read downstream, but they have to survive the journey.
    edge = torch.empty(total, getattr(model.boundary, "out_features", 2))
    at = 0
    while True:
        chunk = wave[at * STRIDE:(at + span) * STRIDE + 400]
        ctc, bound = model(chunk)
        ctc, bound = ctc[0].float().cpu(), bound[0].float().cpu()
        last = at + span >= total
        head = 0 if at == 0 else guard
        tail = min(ctc.shape[0], (total - at) if last else span - guard)
        if tail <= head:
            break
        out[at + head:at + tail] = ctc[head:tail]
        edge[at + head:at + tail] = bound[head:tail]
        if last:
            break
        at += step
    return out, edge


def save(path, model, **extra) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # NEVER overwrite a good checkpoint with a broken one. A continuation run
    # went NaN and wrote itself over a model that had taken an hour to train;
    # what survived was a -lowloss copy with one dead tensor in it. A run that
    # has diverged has nothing worth saving, and saying so at the moment of
    # writing is the only place where the old file still exists.
    weights = model.state_dict()
    bad = [k for k, v in weights.items()
           if torch.is_tensor(v) and not torch.isfinite(v).all()]
    if bad:
        print(f"  NOT saving: {len(bad)} tensor(s) are not finite "
              f"({bad[0]} and {len(bad) - 1} more) -- the run has diverged, "
              f"and {path} is left as it was")
        return
    tmp = path.with_suffix(path.suffix + ".part")
    torch.save({"config": model.config, "weights": weights,
                "alphabet": text.SYMBOLS, "frame": audio.FRAME,
                "kind": "wav2vec", **extra}, tmp)
    tmp.replace(path)
