"""The vocal out of a mixture, with demucs.

What is left of the aligner's separation stage: the model loaded, used and let
go of inside one call, on the card where there is one and room on it, and on
the CPU otherwise -- which is several times slower and finishes, and beats
taking a card out from under a game.
"""
from __future__ import annotations

import contextlib

MODEL = "htdemucs"
# Seconds of audio demucs holds at once: the most the model was trained on,
# halved on each out-of-memory down to the least that still sounds right.
WINDOW = (2.0, 7.8)


def _device(want: str = "auto") -> str:
    if want == "cpu":
        return "cpu"
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _vocals_only(model, mix, dev: str, seg: float, overlap: float = 0.25):
    """The vocal row of `apply_model(model, mix[None], split=True, shifts=0)[0]`,
    or None if demucs does not offer what this needs.

    `apply_model` overlaps its segments into an output for EVERY source over
    the whole song -- four sources, two channels, 340MB for four minutes -- and
    this program keeps one of them. The sum is per source, so a row of it is
    the same numbers whether or not the other three are added up beside it:
    each segment is still run through the model by demucs' own non-split
    path, and only the vocal row of what comes back is weighted into the
    output. The arithmetic is apply_model's, operation for operation, so the
    result is the same to the bit; see there for the weights. A bag of models
    is combined the way apply_model combines it, again for the one row.
    """
    import torch
    try:
        from demucs.apply import BagOfModels, TensorChunk, apply_model
    except ImportError:
        return None
    row = list(model.sources).index("vocals")
    length = mix.shape[-1]

    def one(sub):
        batch, channels, _n = mix.shape
        seg_len = int(sub.samplerate * seg)
        stride = int((1 - overlap) * seg_len)
        weight = torch.cat([torch.arange(1, seg_len // 2 + 1, device=dev),
                            torch.arange(seg_len - seg_len // 2, 0, -1, device=dev)])
        weight = (weight / weight.max()) ** 1.0
        out = torch.zeros(batch, 1, channels, length)
        sum_weight = torch.zeros(length)
        for offset in range(0, length, stride):
            chunk = TensorChunk(mix, offset, seg_len)
            got = apply_model(sub, chunk, shifts=0, split=False, overlap=overlap,
                              progress=False, device=dev, segment=seg)
            n = got.shape[-1]
            out[..., offset:offset + seg_len] += (
                weight[:n] * got[:, row:row + 1]).to(mix.device)
            sum_weight[offset:offset + seg_len] += weight[:n].to(mix.device)
            del got
        out /= sum_weight
        return out

    if not isinstance(model, BagOfModels):
        model.to(dev)
        model.eval()
        return one(model)[0, 0]
    total, est = 0.0, 0.0
    for sub, weights in zip(model.models, model.weights):
        was = next(iter(sub.parameters())).device
        sub.to(dev)
        sub.eval()
        out = one(sub)
        sub.to(was)
        out[:, 0] *= weights[row]
        total += weights[row]
        est += out
        del out
    est[:, 0] /= total
    return est[0, 0]


def vocal(wave, rate: int, device: str = "auto", say=None):
    """(stem, rate): the vocal of `wave` (channels, samples), at demucs' rate."""
    import torch
    import torchaudio
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    tell = say or (lambda _m: None)
    model = get_model(MODEL)
    model.eval()
    if rate != model.samplerate:
        wave = torchaudio.functional.resample(wave, rate, model.samplerate)
    if wave.shape[0] == 1 and model.audio_channels == 2:
        wave = wave.expand(2, -1)
    elif wave.shape[0] > model.audio_channels:
        wave = wave[:model.audio_channels]
    ref = wave.mean(dim=0)
    mix = (wave - ref.mean()) / (ref.std() + 1e-8)
    dev = _device(device)
    seg = min(WINDOW[1], float(getattr(model, "segment", WINDOW[1]) or WINDOW[1]))
    if "vocals" not in list(model.sources):
        raise RuntimeError(f"{MODEL} has no vocal stem: {list(model.sources)}")
    try:
        while True:
            tell(f"separating the vocal on the {'GPU' if dev == 'cuda' else 'CPU'}"
                 " — this is the slow part…")
            try:
                with torch.no_grad():
                    only = _vocals_only(model, mix[None], dev, seg)
                    if only is None:
                        got = apply_model(model, mix[None], device=dev, split=True,
                                          overlap=0.25, shifts=0, progress=False,
                                          segment=seg)[0]
                        only = got[list(model.sources).index("vocals")]
                        del got
                break
            except RuntimeError as exc:
                if "out of memory" not in str(exc).lower():
                    raise
                with contextlib.suppress(Exception):
                    torch.cuda.empty_cache()
                if dev == "cuda" and seg > WINDOW[0]:
                    seg = max(WINDOW[0], seg / 2)
                elif dev == "cuda":
                    dev, seg = "cpu", WINDOW[1]
                else:
                    raise
        stem = only * (ref.std() + 1e-8) + ref.mean()
        return stem.clone().cpu(), model.samplerate
    finally:
        del model
        with contextlib.suppress(Exception):
            torch.cuda.empty_cache()
