"""The synchroniser: a small convolutional acoustic model, trained from noise.

It is not a speech recogniser that alignment is borrowed from. It is trained
for this job only -- given singing, say which of twenty-nine symbols is being
sung in each 20 ms frame -- and the timing falls out of the frames rather than
being inferred afterwards.

WHY IT HAS NO ATTENTION. The clips it learns from are four seconds long and the
songs it is asked about are four minutes. A transformer trained on 200 frames
and shown 12,000 is being asked about positions it has never seen, and the
quadratic cost of showing it the whole song at once does not fit on this card
anyway. Every layer here is a convolution, so a frame is judged by the second
or so of sound around it and by nothing else: the model cannot tell how long
the song is or where in it the frame sits, and therefore cannot be wrong about
it. Train on lines, run on songs, no seam.

The shape, per block, is a depthwise convolution to mix time, then a pointwise
pair to mix bands -- cheap where the cost would otherwise be, expensive where
the capacity is wanted. Dilations climb 1, 2, 4, 8 and repeat, so twelve blocks
reach about a second and a half either side without ever pooling the time axis
away.

The head emits log-probabilities over the alphabet in text.py, trained with
CTC. CTC is what makes the offset problem survivable: the loss asks only that
the symbols appear IN ORDER somewhere inside the clip, so a clip whose words
sit 200 ms from where its reference claimed is still a correct example. What it
cannot survive is a clip whose words have been cut off the edge -- which is
what offset.py is for.
"""
from __future__ import annotations

import math

import torch
from torch import nn

from . import audio, text


class Block(nn.Module):
    """One residual step: mix time with a depthwise conv, then mix bands."""

    def __init__(self, dim: int, kernel: int, dilation: int, drop: float):
        super().__init__()
        pad = dilation * (kernel - 1) // 2
        self.norm = nn.LayerNorm(dim)
        self.time = nn.Conv1d(dim, dim, kernel, padding=pad, dilation=dilation,
                              groups=dim)
        self.up = nn.Linear(dim, dim * 2)
        self.down = nn.Linear(dim * 2, dim)
        self.drop = nn.Dropout(drop)
        # The residual starts as identity: a fresh block passes its input
        # through untouched and has to earn every change it makes. Deep stacks
        # of these train from noise without warm-up tricks because of it.
        self.scale = nn.Parameter(torch.full((dim,), 1e-3))

    def forward(self, x):                     # x: (batch, time, dim)
        y = self.norm(x)
        y = self.time(y.transpose(1, 2)).transpose(1, 2)
        y = self.down(nn.functional.gelu(self.up(y)))
        return x + self.drop(y) * self.scale


class SyncNet(nn.Module):
    """Log-mel in, log-probabilities over the alphabet out, at 20 ms a frame."""

    wants = "mel"      # encoder.Wav2VecSync says "wave"; emit() reads this

    def __init__(self, dim: int = 320, blocks: int = 12, kernel: int = 9,
                 drop: float = 0.2, classes: int = text.SIZE):
        super().__init__()
        self.dim, self.blocks, self.kernel, self.drop_p = dim, blocks, kernel, drop
        self.stem = nn.Sequential(
            nn.Conv1d(audio.N_MELS, dim, 5, stride=audio.STRIDE, padding=2),
            nn.GELU(),
            nn.Conv1d(dim, dim, 5, padding=2),
        )
        cycle = [1, 2, 4, 8]
        self.body = nn.ModuleList([
            Block(dim, kernel, cycle[i % len(cycle)], drop) for i in range(blocks)
        ])
        self.norm = nn.LayerNorm(dim)
        self.head = nn.Linear(dim, classes)
        # Two local boundary channels: word-start and word-end evidence.
        self.boundary = nn.Linear(dim, 2)
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, (nn.Conv1d, nn.Linear)):
            nn.init.trunc_normal_(m.weight, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)

    def forward(self, mel):
        """Return CTC log-probs and boundary logits at 20 ms/frame."""
        x = self.stem(mel.transpose(1, 2)).transpose(1, 2)
        for block in self.body:
            x = block(x)
        x = self.norm(x)
        return (nn.functional.log_softmax(self.head(x), dim=-1),
                self.boundary(x))

    def context(self) -> int:
        """Output frames of sound each side that a frame's answer depends on.

        Every layer is a convolution, so this is exact arithmetic rather than a
        guess, and windowed inference uses it directly: trim less than this off
        a window's edge and the join is visible in the emissions.
        """
        reach = 2 + sum(b.time.dilation[0] * (self.kernel - 1) // 2
                        for b in self.body)
        return reach + 1

    def out_len(self, n: int) -> int:
        """Frames out for `n` mel frames in -- the stem's stride, once."""
        return (n + audio.STRIDE - 1) // audio.STRIDE

    @property
    def config(self) -> dict:
        return {"dim": self.dim, "blocks": self.blocks, "kernel": self.kernel,
                "drop": self.drop_p, "classes": self.head.out_features}

    def size(self) -> str:
        n = sum(p.numel() for p in self.parameters())
        return f"{n / 1e6:.1f}M parameters"


def build(config: dict | None = None) -> SyncNet:
    return SyncNet(**(config or {}))


def save(path, model, **extra) -> None:
    # Dispatches like load() does. The alternative is what happened: the
    # periodic saves went through the right saver and the FINAL one did not,
    # so the finished checkpoint came out missing the field that says which
    # kind of model it holds -- and would not load.
    if getattr(model, "wants", "mel") == "wave":
        from . import encoder
        return encoder.save(path, model, **extra)
    import pathlib
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
                "alphabet": text.SYMBOLS, "frame": audio.FRAME, **extra}, tmp)
    tmp.replace(path)          # never a half-written checkpoint on disk


def load(path, device: str = "cpu"):
    """Whatever model is on `path`, whichever kind it is.

    One door for two kinds of model. Everything downstream -- bench, offsets,
    generate -- says M.load and M.emit and does not care which it got; the
    checkpoint says what it is and this dispatches. Adding a second kind
    without this was worth two failed benchmark runs: the model was a drop-in
    everywhere EXCEPT at the point where it is loaded.
    """
    import torch as _t
    peek = _t.load(path, map_location="cpu", weights_only=False)
    # By the marker, or failing that by the shape of the config: a checkpoint
    # written before save() learned to dispatch has no marker, but only the
    # encoder's config carries a model `name`.
    if peek.get("kind") == "wav2vec" or "name" in (peek.get("config") or {}):
        from . import encoder
        return encoder.load(path, device)
    del peek
    return _load_syncnet(path, device)


def _load_syncnet(path, device: str = "cpu") -> tuple[SyncNet, dict]:
    """The model on `path`, and everything else the checkpoint carried.

    The alphabet is checked rather than assumed. A checkpoint trained before a
    symbol was added would otherwise load happily and mean something different
    by every id in it, which is the kind of fault that shows up as "the timings
    got worse" three days later.
    """
    got = torch.load(path, map_location=device, weights_only=False)
    if got.get("alphabet") not in (None, text.SYMBOLS):
        raise ValueError(
            f"{path} was trained on a different alphabet "
            f"({got['alphabet']!r}) and cannot be read with this one")
    model = build(got.get("config"))
    # Old checkpoints have no boundary head. Keep their CTC weights and leave
    # the new boundary head at its fresh initialization -- but SAY SO. A fresh
    # head is random numbers, and the word-end refinement downstream reads it
    # as evidence; a checkpoint trained before the head existed would otherwise
    # have its word ends nudged around by noise, silently and only at the ends.
    model.load_state_dict(got["weights"], strict=False)
    model.has_boundary = any(k.startswith("boundary.") for k in got["weights"])
    model.to(device).eval()
    rest = {k: v for k, v in got.items() if k not in ("weights",)}
    return model, rest


@torch.no_grad()
def emit(model: SyncNet, wave, device: str = "cpu", window: float = 60.0,
         overlap: float | None = None, return_boundary: bool = False):
    """Log-probs for a whole song, optionally with stitched boundary logits."""
    if getattr(model, "wants", "mel") == "wave":
        # A pretrained encoder reads the waveform; windowing it is its own job.
        from . import encoder
        ctc, edge = encoder.emit(model, wave, device, window=min(window, 20.0),
                                 overlap=overlap)
        return (ctc, edge) if return_boundary else ctc
    model.eval()
    mel = audio.mel(wave, device)
    mel = mel[:mel.shape[0] - mel.shape[0] % audio.STRIDE]
    total = model.out_len(mel.shape[0])
    span = max(2, int(window / audio.FRAME))
    context = (2 * model.context() if overlap is None
               else max(2, int(overlap / audio.FRAME)))
    span = max(span, 4 * context)

    def run(chunk):
        ctc, boundary = model(chunk.unsqueeze(0))
        return ctc[0].float().cpu(), boundary[0].float().cpu()

    if total <= span:
        ctc, boundary = run(mel)
        return (ctc, boundary) if return_boundary else ctc

    out_ctc = torch.empty(total, model.head.out_features)
    out_boundary = torch.empty(total, 2)
    guard, step = context // 2, span - context
    at = 0
    while True:
        chunk = mel[at * audio.STRIDE:(at + span) * audio.STRIDE]
        got_ctc, got_boundary = run(chunk)
        last = at + span >= total
        head = 0 if at == 0 else guard
        tail = got_ctc.shape[0] if last else got_ctc.shape[0] - guard
        out_ctc[at + head:at + tail] = got_ctc[head:tail]
        out_boundary[at + head:at + tail] = got_boundary[head:tail]
        if last:
            break
        at += step

    return (out_ctc, out_boundary) if return_boundary else out_ctc


def scale_lr(model: SyncNet) -> float:
    """A learning rate that suits the width, so `--dim` does not need tuning."""
    return 3e-3 / math.sqrt(model.dim / 320)
