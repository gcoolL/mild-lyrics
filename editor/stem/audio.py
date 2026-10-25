"""Sound into what the vocal view reads, and back into seconds: 16 kHz mono, 80
log-mel bands every 10 ms, a vocal-map frame of 20 ms. Changing these
invalidates every kept map."""
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
    """(frames, 80) log-mel for a mono 16 kHz waveform, normalised per clip."""
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
