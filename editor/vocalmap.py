"""The separated vocal, as a picture and as a list of places a word could start.

WHY A SPECTROGRAM HERE AND NOT IN `waveform`. That module says, correctly,
that a picture of the MIXTURE invites snapping to the wrong thing: the loudest
attack in a bar is a snare, and gc's word starts do not sit on snares. Measured
on `ToxiPlays, Hypertoxicated - MaKE ME FAMOUSS >_<`, 251 hand-placed word
starts against the spectral flux of the same audio:

    mixture   median -0.018 s,  spread 0.070 s   (chance spread 0.098 s)
    stem      median -0.028 s,  spread 0.040 s   (chance spread 0.060 s)

The `chance spread` column is the same statistic with the document slid half a
second to a second and a half either way, which is what "the attacks are so
dense that everything hits one" looks like. On the mixture the true figure is
most of the way to chance and the picture really is not worth tracing. On the
demucs vocal it is two thirds of it, and consistently -- so the stem's attacks
DO know something about where this file's words are, and the mixture's very
nearly do not. That difference is the whole reason this module separates
first.

WHAT IT IS STILL NOT. A spread of 0.040 s is not a placement. It is enough to
say that a word sitting 0.2 s from every attack in earshot is in the wrong
place, and nowhere near enough to justify moving a word that is already within
about 0.05 s of one. Snapping to these was built and then removed on the
evidence; `ops.consistency` measures what is left and `ops.claims` decides
which marks are readable at all. Nothing here ever returns a time on its own.

THE TWO KINDS OF LANDMARK, in the order they are trusted:

  * an ACTIVITY edge -- the vocal starting after real silence, or stopping.
    Unambiguous when it happens, and on a dense rapped song it hardly ever
    happens: this one is 81% sung and yields nine of them.
  * a FLUX attack -- energy arriving in the mel spectrum. Always available,
    which is the problem: at the floor `vocal.attacks` uses for calibration
    there are 7.6 a second and a nearest-attack match means nothing. `FLOOR`
    below is set where the measurement above still shows signal.

Everything is on `audio.FRAME`, the 20 ms grid the rest of the project reports
times on.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path[:0] = [str(p) for p in (_ROOT / "aligner", _ROOT)
                if str(p) not in sys.path]

# How strong a flux peak has to be to count as a place a word could start.
# `vocal.PEAK` is 0.25, which is right for its own job -- measuring a whole
# song's standing bias, where more attacks is more votes and a wrong one costs
# nothing. Here a wrong one moves a word. At 0.25 the spread against the hand
# timings is 0.023 s and chance is 0.026: no signal at all. This is where the
# measurement in the docstring holds up.
FLOOR = 0.45

# Where the vocal is loud enough to be singing rather than a reverb tail.
# `vocal.activity` is a soft 0..1 and its own -38 dB floor is generous by
# design; this reads the top of that curve, so an edge is a real entrance.
ALIVE = 0.90
JOIN = 0.06            # gaps in the activity shorter than this are not gaps
LEAST = 0.08           # and runs shorter than this are not entrances


def _key(path: str) -> str:
    st = pathlib.Path(path).stat()
    raw = f"{pathlib.Path(path).resolve()}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def cache_dir() -> pathlib.Path:
    import lyrics_gui as L
    return pathlib.Path(L.app_dir("cache")) / "vocal-view"


class VocalMap:
    """One song's separated vocal: the picture, and where it starts things.

    Built once and kept on disk, because the separation is the expensive part
    -- half a minute on a GPU, several on a CPU -- and the editor is a program
    somebody opens the same song in twice.
    """

    def __init__(self, mel, present, onset, length: float, frame: float,
                 stems: bool = True) -> None:
        self.mel = mel                  # (fine frames, 80) float32, for drawing
        self.present = present          # (frames,) 0..1
        self.onset = onset              # (frames,) 0..1
        self.length = float(length)
        self.frame = float(frame)
        self.stems = bool(stems)
        self._marks: dict = {}

    # ------------------------------------------------------------- building
    @classmethod
    def build(cls, path: str, stems: bool = True, device: str = "auto",
              spare: float = 0.4, say=None, reuse: bool = True) -> "VocalMap":
        """Separate `path`, or read back the last time it was separated."""
        import numpy as np
        tell = say or (lambda _m: None)
        store = cache_dir() / f"{_key(path)}{'' if stems else '-mix'}.npz"
        if reuse and store.exists():
            try:
                got = cls._read(store, stems)
                tell("vocal view — read back from the last time")
                return got
            except Exception:
                store.unlink(missing_ok=True)

        from sync import audio, vocal
        tell("reading the audio…")
        wave, rate = audio.read(path)
        mono = audio.mono16k(wave, rate)
        if stems:
            import local_align as LA
            tell("separating the vocal — this is the slow part…")
            dev, win, _why = LA.room("gpu", LA.DEMUCS_COST, LA.DEMUCS_WINDOW,
                                     spare)
            if device == "cpu":
                dev, win = "cpu", LA.DEMUCS_WINDOW[0]
            sep, srate = LA.separate(wave, rate, dev, win, LA.MODEL, None, None)
            mono = audio.mono16k(sep, srate)
            LA.release()
        tell("looking at the spectrum…")
        mel = audio.mel(mono).numpy()
        present = vocal.activity(mono).numpy()
        onset = vocal.onsets(mono).numpy()
        got = cls(mel.astype("float32"), present, onset,
                  mono.shape[0] / float(audio.RATE), audio.FRAME, stems)
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            # float16 for the picture: it is displayed, never measured, and
            # half the bytes of a four-minute song is worth more than a
            # precision nothing here can see.
            np.savez_compressed(store, mel=mel.astype("float16"),
                                present=present, onset=onset,
                                length=np.array([got.length], dtype="float64"))
        except Exception:
            pass
        return got

    @classmethod
    def _read(cls, store: pathlib.Path, stems: bool) -> "VocalMap":
        import numpy as np
        from sync import audio
        z = np.load(store)
        return cls(z["mel"].astype("float32"), z["present"], z["onset"],
                   float(z["length"][0]), audio.FRAME, stems)

    # ------------------------------------------------------------ landmarks
    def segments(self, alive: float = ALIVE, join: float = JOIN,
                 least: float = LEAST) -> list[tuple[float, float]]:
        """The stretches where somebody is actually singing."""
        on = self.present >= alive
        out: list[list[float]] = []
        i, n = 0, len(on)
        while i < n:
            if not on[i]:
                i += 1
                continue
            j = i
            while j < n and on[j]:
                j += 1
            a, b = i * self.frame, j * self.frame
            if out and a - out[-1][1] <= join:
                out[-1][1] = b
            else:
                out.append([a, b])
            i = j
        return [(a, b) for a, b in out if b - a >= least]

    def attacks(self, floor: float = FLOOR) -> list[float]:
        """Where energy arrives in the vocal: the times a word could start."""
        from sync import vocal
        return vocal.attacks(self.onset, floor)

    def marks(self, floor: float = FLOOR) -> dict:
        """`{"starts": [...], "ends": [...]}` -- every landmark, in seconds.

        A start is an activity entrance or a flux attack; an entrance that has
        an attack within `JOIN` of it is the same event heard twice and only
        the entrance is kept, because it is the better-founded of the two.
        Ends are activity exits only. Nothing in the flux says a word STOPPED
        -- half-wave rectification threw that away on purpose, back in
        `vocal.onsets` -- so an end has no second-best source and simply is
        not offered where the singing does not stop.
        """
        if floor in self._marks:
            return self._marks[floor]
        segs = self.segments()
        rises = [a for a, _ in segs]
        starts = list(rises)
        for t in self.attacks(floor):
            if not any(abs(t - r) <= JOIN for r in rises):
                starts.append(t)
        got = {"starts": sorted(starts), "ends": sorted(b for _, b in segs),
               "entrances": rises}
        self._marks[floor] = got
        return got

    # ----------------------------------------------------------- does it fit
    # How many points of separation between "the document says somebody is
    # singing here" and "the document says nobody is" before the audio is
    # believed to be this document's song. Measured: the right recording of
    # `MaKE ME FAMOUSS >_<` scores +69, and a 212-second recording opened
    # against the same 103-second document scores -7. There is no sensible
    # threshold between those two that is hard to choose.
    AGREE = 25.0

    def agrees(self, spans: list[tuple[float, float]]) -> dict:
        """Whether this audio is plausibly the song `spans` was timed against.

        WHY THIS EXISTS. The view will happily separate whatever audio the
        window has open and draw it behind whatever document is loaded, and
        the two have no reason to be the same song. That is not a hypothetical
        -- it is how this was first used: a 212-second recording behind a
        103-second lyric, every mark landing somewhere arbitrary, and nothing
        anywhere saying so. A picture that is confidently wrong is worse than
        no picture, because the whole point of it is to be believed.

        The test is the one thing a lyric knows about audio without knowing
        the words: WHEN NOBODY IS SINGING. Take the frames the document says
        are inside a rest and the frames it says are inside a word, and ask
        how much likelier the vocal is to be sounding in the second than the
        first. On the right recording that gap is enormous. On the wrong one
        it is nothing, and it stays nothing however the two are slid about,
        which is why this beats correlating the two masks -- both are on most
        of the time, so their overlap is high whatever you do to it.

        Only the document's own span is looked at, so a song with a long
        outro nobody has timed is not held against it.
        """
        import numpy as np
        spans = [(a, b) for a, b in spans if a is not None and b is not None]
        if not spans or self.present is None or not len(self.present):
            return {"trusted": False, "why": "nothing timed to check against"}
        n = len(self.present)
        on = self.present >= ALIVE
        first = min(a for a, _ in spans)
        last = max(b for _, b in spans)
        mask = np.zeros(n, dtype=bool)
        for a, b in spans:
            mask[max(0, int(a / self.frame)):min(n, int(b / self.frame))] = True
        lo, hi = max(0, int(first / self.frame)), min(n, int(last / self.frame))
        got = {"audio": round(self.length, 2), "first": round(first, 2),
               "last": round(last, 2),
               "heard": round(float(np.flatnonzero(on)[0]) * self.frame, 2)
               if on.any() else None}
        if hi - lo < 50:
            got.update(trusted=False, why="too little of the song is timed")
            return got
        sung, quiet = mask[lo:hi], ~mask[lo:hi]
        if quiet.sum() < 25:
            # A document with no rests in it cannot be checked this way. The
            # lead-in is the fallback: a lyric that starts singing thirteen
            # seconds in, over audio that starts singing at half a second, is
            # not that audio's lyric.
            lead = abs((got["heard"] if got["heard"] is not None else 0.0)
                       - first)
            got.update(separation=None, trusted=lead <= 2.0,
                       why="" if lead <= 2.0 else
                       f"the singing starts {lead:.1f}s from where the lyric "
                       f"says it does")
            return got
        hit = float(on[lo:hi][sung].mean()) * 100.0
        leak = float(on[lo:hi][quiet].mean()) * 100.0
        sep = hit - leak
        got.update(sung=round(hit, 1), rest=round(leak, 1),
                   separation=round(sep, 1), trusted=sep >= self.AGREE)
        got["why"] = "" if got["trusted"] else (
            f"the vocal is singing {hit:.0f}% of the time this lyric has "
            f"words and {leak:.0f}% of the time it has rests -- on the right "
            f"recording those are far apart. This audio is "
            f"{self.length:.0f}s and the lyric ends at {last:.0f}s")
        return got

    # -------------------------------------------------------------- picture
    def image(self, ramp=((20, 22, 28), (91, 140, 255), (233, 234, 238)),
              floor: float | None = None, ceiling: float | None = None,
              gamma: float = 1.35):
        """The mel as a coloured QImage, one column per 10 ms, low band at the
        bottom.

        `audio.mel` is already normalised per song -- its own mean and spread
        taken out -- but that is not the same as being FRAMED. The values it
        produces are lopsided: this song's bottom fifth of pixels sit in the
        1e-6 log floor and its top thousandth reach 2.0, so a symmetric window
        spends most of its brightness on the quiet half and the picture comes
        out a flat wash. The window is taken from the song's own percentiles
        instead, which puts the median down near the background and leaves the
        top of the ramp for the formants -- the part somebody is looking at.

        The ramp is applied here, in numpy, rather than by compositing a tint
        over a grey image in the widget. Painting the picture inside
        `paintEvent` meant a third QPainter open on top of the two the strip
        already has, which Qt ends the process over; and a lookup table over
        256 values is the cheaper of the two anyway.
        """
        import numpy as np
        from PyQt6.QtGui import QImage
        mel = self.mel
        if mel is None or not len(mel):
            return None
        if floor is None:
            floor = float(np.percentile(mel, 40))
        if ceiling is None:
            ceiling = float(np.percentile(mel, 99.5))
        v = np.clip((mel - floor) / max(ceiling - floor, 1e-6), 0.0, 1.0)
        v = v ** gamma                       # hold the quiet detail down
        idx = (v * 255).astype("uint8")
        lut = self._ramp(ramp)
        # (frames, bands) -> (bands, frames), then flipped so band 0 is the
        # bottom row, which is what everybody expects a spectrogram to do.
        pic = np.ascontiguousarray(lut[idx.T[::-1]])
        h, w = pic.shape[:2]
        img = QImage(pic.data, w, h, w * 3, QImage.Format.Format_RGB888)
        return img.copy()                    # own the bytes; `pic` is local

    @staticmethod
    def _ramp(stops) -> "object":
        """A 256-entry RGB table through the given stops."""
        import numpy as np
        stops = np.asarray(stops, dtype="float32")
        at = np.linspace(0.0, 1.0, len(stops))
        x = np.linspace(0.0, 1.0, 256)
        out = np.stack([np.interp(x, at, stops[:, c]) for c in range(3)],
                       axis=-1)
        return out.clip(0, 255).astype("uint8")

    def rate(self) -> float:
        """Picture columns a second."""
        n = len(self.mel) if self.mel is not None else 0
        return (n / self.length) if (n and self.length > 0) else 100.0
