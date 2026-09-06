"""The emissions kept on disk, so a search can be tried without listening again.

Every question this project now asks of the aligner is a question about the
SEARCH: what does a blank tax do, where does a word's posterior sit, would this
song have gone differently under a different prior. None of them is a question
about the sound. But asking any of them meant fetching a song, running demucs
or not, and pushing four minutes of audio through 95M parameters -- about a
minute a song, and a card that has to be free -- before the part being measured
even started.

So the model's answer is written down once and read back after that. `logp` and
the boundary logits are what `ctcalign` reads; `present` and `onset` are what
`vocal` measured from the same waveform, and they are here too because sweeping
GATE and ATTACK is exactly the kind of question this is for. A run over the
whole benchmark then costs seconds instead of an hour, which is the difference
between sweeping a constant and guessing it.

The precedent is `aligner/sweep.py`, which replays 4,320 onset settings out of
`bench/*.raw.json` with no GPU at all. This is the same trick one layer up: the
flux curve let the SNAP be swept, and the emissions let the SEARCH be swept.

WHAT THE KEY HAS TO CONTAIN. A jar entry is only reusable if everything upstream
of the emissions was the same: which checkpoint, which recording, and separated
or not. Get that wrong and a sweep is comparing two songs while believing it is
comparing two settings -- which is the one failure a cache like this can cause.
The checkpoint and the separation are in the NAME; the recording is checked on
the way out, against the size of the copy the benchmark has pinned. It is
checked rather than named because the lag `offset.trim` takes off the front is
measured FROM the audio, so a key that included it could only be built by
fetching the song -- which is the thing this exists to avoid.

FP16, AND WHY IT IS SAFE HERE. These are log-probabilities out of a log_softmax,
so they live in about [-30, 0]: fp16 carries three decimal places there, well
under the 20 ms the frame grid quantises everything to anyway. This is storage
only -- `read()` hands back float32 and every search runs in the precision it
always did. What is NOT safe in fp16 is a CTC forward accumulator, which reaches
five figures on levelled emissions; that stays float32 wherever it is added up.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

HOME = pathlib.Path.home() / ".cache/mild-lyrics/sync"
JAR = HOME / "jar"

# The arrays a jar entry holds. `logp` and `edge` are the model's; `present` and
# `onset` are the audio's, measured from the very waveform the model was given.
# All four or the entry is not written: a half-filled entry read back as a full
# one is how a sweep silently stops testing the thing it says it tests.
KEEP = ("logp", "edge", "present", "onset")


def stamp(ckpt) -> str:
    """A short name for which checkpoint this is.

    Size and modification time rather than a hash of the weights: a 1.1 GB
    checkpoint takes seconds to digest and this is asked once per song. It is a
    cache key on one machine, not a content address -- what it has to do is
    change when the checkpoint does, and both of these do.
    """
    p = pathlib.Path(ckpt)
    try:
        st = p.stat()
        raw = f"{p.name}:{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        raw = str(p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def slot(tid: str, mark: str, stem: bool) -> pathlib.Path:
    """Where this song's emissions live, for this checkpoint and this input."""
    return JAR / f"{tid}.{mark}.{'stem' if stem else 'mix'}.npz"


def read(tid: str, mark: str, stem: bool, bytes_: int = 0) -> dict | None:
    """What was written for this song, as float32, or None if nothing was.

    `bytes_` is the size of the audio file the caller would otherwise read. The
    benchmark pins its copies and never replaces one (see bench.AUDIO), so the
    size is a sufficient statement of "the same recording" -- and passing 0 says
    the caller has no copy to check against and will take what is here.
    """
    path = slot(tid, mark, stem)
    if not path.exists():
        return None
    import numpy as np
    import torch
    try:
        with np.load(path) as got:
            if any(k not in got for k in KEEP):
                return None
            out = {}
            for k in KEEP:
                arr = got[k]
                # A missing signal is stored as an empty array rather than left
                # out, so that "we did not measure onsets" and "this entry is
                # damaged" stay different things.
                out[k] = None if arr.size == 0 else torch.from_numpy(
                    arr.astype("float32"))
            out["meta"] = json.loads(str(got["meta"])) if "meta" in got else {}
        # A different copy of the same song is a different measurement. Better
        # to hear it again than to hand a sweep emissions from another master.
        was = int(out["meta"].get("bytes") or 0)
        if bytes_ and was and was != bytes_:
            return None
        return out
    except Exception:
        # A truncated .npz from an interrupted write reads as a zip error. The
        # answer is to hear the song again, not to crash the sweep.
        return None


def write(tid: str, mark: str, stem: bool,
          logp=None, edge=None, present=None, onset=None, **meta) -> None:
    """Keep this song's emissions under that key. Never half-written."""
    import numpy as np
    JAR.mkdir(parents=True, exist_ok=True)
    hold = {}
    for name, arr in (("logp", logp), ("edge", edge),
                      ("present", present), ("onset", onset)):
        if arr is None:
            hold[name] = np.zeros(0, dtype="float16")
        else:
            hold[name] = np.asarray(
                arr.detach().cpu().numpy() if hasattr(arr, "detach")
                else arr, dtype="float16")
    hold["meta"] = np.array(json.dumps(meta))
    path = slot(tid, mark, stem)
    tmp = path.with_suffix(path.suffix + ".part")
    with tmp.open("wb") as fh:
        np.savez(fh, **hold)
    tmp.replace(path)


def size() -> tuple[int, int]:
    """How many entries are on disk and how many bytes they take."""
    if not JAR.exists():
        return 0, 0
    files = [p for p in JAR.iterdir() if p.suffix == ".npz"]
    return len(files), sum(p.stat().st_size for p in files)
