# `editor/stem/audio.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/stem/audio.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Sound into what the vocal view reads, and back into seconds.
>
> Everything here works at 16 kHz mono on 80 log-mel bands taken every 10 ms,
> read in pairs, so one frame of the vocal map is 20 ms: fine enough that the
> marks sit where the ear puts them, coarse enough that a four-minute song is
> twelve thousand frames rather than four million samples.
>
> Carried over from the aligner's `sync` package when the vocal view came back
> without it. The numbers below are the ones the kept maps on disk were measured
> at; change one and every map in the cache is read at the wrong scale.

### `mel`

**line 25** — from the docstring, `def mel(wave, device: str = "cpu"):`

> (frames, 80) log-mel for a mono 16 kHz waveform.
>
> Normalised per clip, not per corpus. A song's loudness, its mastering and
> the codec it came through all move the whole spectrogram up or down
> together, and none of that is information about where the words are; taking
> each clip's own mean and spread out is what lets a bedroom recording and a
> loudness-war master look the same to the model.
