"""Sound into what the vocal view reads, and back into seconds.

Everything here works at 16 kHz mono on 80 log-mel bands taken every 10 ms,
read in pairs, so one frame of the vocal map is 20 ms: fine enough that the
marks sit where the ear puts them, coarse enough that a four-minute song is
twelve thousand frames rather than four million samples.

Carried over from the aligner's `sync` package when the vocal view came back
without it. The numbers below are the ones the kept maps on disk were measured
at; change one and every map in the cache is read at the wrong scale.
"""
from __future__ import annotations

import functools

RATE = 16000
N_MELS = 80
N_FFT = 400          # 25 ms
HOP = 160            # 10 ms
STRIDE = 2           # frames the model folds together
FRAME = HOP * STRIDE / RATE   # 0.02 s -- the resolution of every answer


@functools.lru_cache(maxsize=4)
def _mel(device: str):
    import torchaudio
    return torchaudio.transforms.MelSpectrogram(
        sample_rate=RATE, n_fft=N_FFT, hop_length=HOP, n_mels=N_MELS,
        f_min=40.0, f_max=7600.0, power=2.0).to(device)


def mel(wave, device: str = "cpu"):
    """(frames, 80) log-mel for a mono 16 kHz waveform.

    Normalised per clip, not per corpus. A song's loudness, its mastering and
    the codec it came through all move the whole spectrogram up or down
    together, and none of that is information about where the words are; taking
    each clip's own mean and spread out is what lets a bedroom recording and a
    loudness-war master look the same to the model.
    """
    import torch
    if wave.dim() > 1:
        wave = wave.mean(dim=0)
    wave = wave.to(device, dtype=torch.float32)
    spec = _mel(device)(wave)
    spec = torch.log(spec + 1e-6).transpose(0, 1)
    return (spec - spec.mean()) / (spec.std() + 1e-5)


def seconds(frame: int | float) -> float:
    """A model frame index as a time in seconds."""
    return float(frame) * FRAME


def frames(secs: float) -> int:
    """A time in seconds as a model frame index."""
    return int(round(float(secs) / FRAME))


def read(path: str):
    """(wave, rate) for a file on disk, as a (channels, samples) tensor."""
    import torch
    try:
        import soundfile
        data, sr = soundfile.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), int(sr)
    except Exception:
        pass
    import tempfile
    import os

    import noconsole
    tmp = os.path.join(tempfile.gettempdir(), f"sync-read-{os.getpid()}.wav")
    try:
        noconsole.run(["ffmpeg", "-v", "quiet", "-y", "-i", str(path),
                       "-ac", "1", "-ar", str(RATE), tmp], check=True)
        import soundfile
        data, sr = soundfile.read(tmp, dtype="float32", always_2d=True)
        return torch.from_numpy(data.T.copy()), int(sr)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def mono16k(wave, rate: int):
    """`wave` downmixed to one channel at 16 kHz."""
    import torchaudio
    if wave.dim() > 1 and wave.shape[0] > 1:
        wave = wave.mean(dim=0, keepdim=True)
    if rate != RATE:
        wave = torchaudio.functional.resample(wave, rate, RATE)
    return wave.reshape(-1)


def loudness(wave, hop: int = HOP):
    """Frame energy in dB, for the offset work. Model-free on purpose."""
    import torch
    n = wave.shape[-1] // hop
    if n < 1:
        return torch.zeros(1)
    trimmed = wave[: n * hop].reshape(n, hop)
    return 10.0 * torch.log10((trimmed ** 2).mean(dim=1) + 1e-10)
