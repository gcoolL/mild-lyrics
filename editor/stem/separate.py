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
    try:
        while True:
            tell(f"separating the vocal on the {'GPU' if dev == 'cuda' else 'CPU'}"
                 " — this is the slow part…")
            try:
                with torch.no_grad():
                    got = apply_model(model, mix[None], device=dev, split=True,
                                      overlap=0.25, shifts=0, progress=False,
                                      segment=seg)[0]
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
        got = got * (ref.std() + 1e-8) + ref.mean()
        try:
            stem = got[list(model.sources).index("vocals")]
        except ValueError:
            raise RuntimeError(f"{MODEL} has no vocal stem: {list(model.sources)}")
        return stem.clone().cpu(), model.samplerate
    finally:
        del model
        with contextlib.suppress(Exception):
            torch.cuda.empty_cache()
