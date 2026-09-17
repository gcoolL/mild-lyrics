"""The separated vocal: a picture, a list of places a word could start, and
the stem itself to listen to.

The third of those is the newest and the plainest. Everything below measures
the vocal and draws what it measured; `stem_path` and `blend` just hand it
back as audio, so a person timing by hand can take the band out of their ears
instead of reading it off a spectrogram. Half speed is called the single most
useful thing there is for placing syllables by hand -- it gives the ear more
of the consonant to aim at -- and turning the drums down does the same job
from the other side. The two compose. See Editor._vocal_mix for the control.

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

THE THREE KINDS OF LANDMARK, in the order they are trusted:

  * an ACTIVITY edge -- the vocal starting after real silence, or stopping.
    Unambiguous when it happens, and on a dense rapped song it hardly ever
    happens: this one is 81% sung and yields nine of them.
  * a FLUX attack -- energy arriving in the mel spectrum. Always available,
    which is the problem: at the floor `vocal.attacks` uses for calibration
    there are 7.6 a second and a nearest-attack match means nothing. `FLOOR`
    below is set where the measurement above still shows signal.
  * a NOTE onset -- the pitch stepping, or voicing resuming. The one that
    reads a chopped vocal, which has no edges and no attacks and is most of
    what a drop is made of; see `VocalMap.notes` for what it is worth where
    the other two fail and where they do not.

Everything is on `audio.FRAME`, the 20 ms grid the rest of the project reports
times on.
"""
from __future__ import annotations

import bisect
import hashlib
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path[:0] = [str(p) for p in (_ROOT / "aligner", _ROOT)
                if str(p) not in sys.path]

FLOOR = 0.45

ALIVE = 0.90
JOIN = 0.06
ALONE = 0.15
LEAST = 0.08


def _key(path: str) -> str:
    st = pathlib.Path(path).stat()
    raw = f"{pathlib.Path(path).resolve()}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def cache_dir() -> pathlib.Path:
    import lyrics_gui as L
    return pathlib.Path(L.app_dir("cache")) / "vocal-view"


def stem_path(path: str) -> pathlib.Path:
    """Where this song's separated vocal is kept as AUDIO, not as a picture.

    The map beside it is a spectrogram and three curves -- enough to draw the
    vocal and to say where it starts things, and not a thing you can listen
    to. Timing by hand wants the other one: the mixture's drums land on the
    beat and the singer does not, so a word start that is inaudible under a
    full mix is obvious on the stem alone. See `blend`, and Editor._vocal_mix
    for the control.

    FLAC rather than WAV. It is exact, every path this editor already opens
    accepts it (see app.AUDIO), and it is about half the bytes -- which is
    the difference between a cache somebody notices and one they do not.
    """
    return cache_dir() / f"{_key(path)}-vocal.flac"


def blend_path(path: str, level: float) -> pathlib.Path:
    """Where the vocal-at-`level` mix of this song is kept."""
    return cache_dir() / f"{_key(path)}-mix{int(round(level * 100)):03d}.flac"


BLENDS_KEPT = 4


def blend(path: str, level: float, say=None) -> str:
    """The song with its vocal at `level`, as a file to play. 0..1.

    0 is the mixture untouched and 1 is the stem by itself. In between, the
    backing is what is left when the vocal is taken out of the mixture --
    `mix - stem`, which is exact by construction and needs no second
    separation -- and it is turned down by `level`:

        out = stem + (mix - stem) * (1 - level)

    so 0 really is the file that was opened, sample for sample, and not a
    re-encode of it that drifts a frame. Neither end is rendered: both are
    already on disk.
    """
    import numpy as np
    import soundfile
    tell = say or (lambda _m: None)
    level = max(0.0, min(1.0, float(level)))
    stem = stem_path(path)
    if level <= 0.0:
        return str(path)
    if not stem.exists():
        raise FileNotFoundError("this song has not been separated yet")
    if level >= 1.0:
        return str(stem)
    out = blend_path(path, level)
    if out.exists():
        return str(out)

    from sync import audio
    import torchaudio
    tell(f"mixing the vocal up to {level * 100:.0f}%…")
    voc, vrate = audio.read(str(stem))
    mix, mrate = audio.read(str(path))
    if mrate != vrate:
        mix = torchaudio.functional.resample(mix, mrate, vrate)
    if mix.shape[0] != voc.shape[0]:
        if mix.shape[0] == 1:
            mix = mix.expand(voc.shape[0], -1)
        elif voc.shape[0] == 1:
            voc = voc.expand(mix.shape[0], -1)
        else:
            mix = mix.mean(dim=0, keepdim=True).expand(voc.shape[0], -1)
    n = min(mix.shape[-1], voc.shape[-1])
    mix, voc = mix[:, :n], voc[:, :n]
    got = voc + (mix - voc) * (1.0 - level)
    peak = float(got.abs().max())
    if peak > 1.0:
        got = got / peak
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.flac")
    soundfile.write(str(tmp), np.asarray(got.T, dtype="float32"), int(vrate),
                    format="FLAC")
    tmp.replace(out)
    _prune_blends(path, keep=out)
    return str(out)


def _keep_stem(path: str, sep, srate: int, tell=None) -> None:
    """Write the separated vocal out beside its map.

    Quietly. A song whose picture came out fine but whose stem could not be
    written -- a full disk, a cache directory somebody has made read-only --
    still has a vocal view, and the mix control is simply not offered for it;
    that is a better answer than refusing the view over the half of the job
    that was not asked for.
    """
    import numpy as np
    say = tell or (lambda _m: None)
    out = stem_path(path)
    try:
        import soundfile
        out.parent.mkdir(parents=True, exist_ok=True)
        wave = sep if getattr(sep, "dim", lambda: 2)() > 1 else sep[None]
        tmp = out.with_suffix(".part.flac")
        soundfile.write(str(tmp), np.asarray(wave.T, dtype="float32"),
                        int(srate), format="FLAC")
        tmp.replace(out)
        _prune_blends(path, keep=None)
        for f in cache_dir().glob(f"{_key(path)}-mix*.flac"):
            f.unlink(missing_ok=True)
    except Exception as exc:                             # noqa: BLE001
        say(f"the vocal could not be kept to listen to — {exc}")
        out.unlink(missing_ok=True)


def _prune_blends(path: str, keep: pathlib.Path | None = None) -> None:
    """Drop this song's oldest rendered blends, newest BLENDS_KEPT held."""
    try:
        rows = sorted(cache_dir().glob(f"{_key(path)}-mix*.flac"),
                      key=lambda f: f.stat().st_mtime, reverse=True)
    except Exception:
        return
    for f in rows[BLENDS_KEPT:]:
        if keep is None or f != keep:
            f.unlink(missing_ok=True)


class VocalMap:
    """One song's separated vocal: the picture, and where it starts things.

    Built once and kept on disk, because the separation is the expensive part
    -- half a minute on a GPU, several on a CPU -- and the editor is a program
    somebody opens the same song in twice.
    """

    def __init__(self, mel, present, onset, length: float, frame: float,
                 stems: bool = True, pitch=None) -> None:
        self.mel = mel
        self.pitch = pitch
        self.present = present
        self.onset = onset
        self.length = float(length)
        self.frame = float(frame)
        self.stems = bool(stems)
        self._marks: dict = {}
        self._flux = None
        self._notes = None

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
                got = cls._read(store, stems, want_stem=path if stems else "")
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
            _keep_stem(path, sep, srate, tell)
            LA.release()
        tell("looking at the spectrum…")
        mel = audio.mel(mono).numpy()
        present = vocal.activity(mono).numpy()
        onset = vocal.onsets(mono).numpy()
        pitch = vocal.pitch(mono).numpy()
        got = cls(mel.astype("float32"), present, onset,
                  mono.shape[0] / float(audio.RATE), audio.FRAME, stems,
                  pitch.astype("float32"))
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(store, mel=mel.astype("float16"),
                                present=present, onset=onset,
                                pitch=pitch.astype("float32"),
                                length=np.array([got.length], dtype="float64"))
        except Exception:
            pass
        return got

    @classmethod
    def _read(cls, store: pathlib.Path, stems: bool,
              want_stem: str = "") -> "VocalMap":
        """Read a kept map back, or refuse it if it is missing a part.

        A map written before there was a pitch track cannot have one added,
        and one written before the stem was kept cannot be listened to:
        either way what is missing was measured from audio this file does not
        hold. Raising here puts the song through `build` again, which costs a
        separation once and then never again -- which is better than a song
        quietly having half the marks, or half the modes, that every other
        song has.
        """
        import numpy as np
        from sync import audio
        z = np.load(store)
        if "pitch" not in z.files:
            raise KeyError("no pitch track in this one")
        if want_stem and not stem_path(want_stem).exists():
            raise KeyError("the separated vocal was not kept for this one")
        return cls(z["mel"].astype("float32"), z["present"], z["onset"],
                   float(z["length"][0]), audio.FRAME, stems, z["pitch"])

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

    def notes(self) -> list[float]:
        """Where the singing changes note: the times a chop or a word starts.

        THE THIRD KIND OF LANDMARK, and the one that answers for the material
        the other two cannot read. An activity edge needs the vocal to stop; a
        flux attack needs energy to arrive. A chopped vocal lead -- the
        singer's own voice cut into sixteenths and pitched up, which is how
        half the drops in this folder are built -- does neither: it runs
        continuously, so there is no edge, and each chop is spliced onto the
        last at the same level, so there is no attack.

        What it does do is change PITCH, every chop. Measured on `Conro -
        Therapy`, whose first chorus gc had timed by hand and whose drop is
        the same material:

                                 nearest mark   within 50ms   chance
            chopped chorus
              flux attacks           0.060s         43%       0.088s
              note onsets            0.042s         58%       0.056s
              both                   0.024s         77%       0.038s
            sung verses
              flux attacks           0.010s         71%       0.075s
              both                   0.005s         84%       0.052s

        So on the material that was failing it roughly doubles the syllables
        that land where they belong, and on ordinary singing -- where the flux
        was already good -- it still helps rather than getting in the way.

        Those figures are for every note this finds. `marks` passes on fewer:
        one only where no better mark is within `ALONE`, which on that song
        leaves 172 of 425 and takes the chorus from 68% to 57%. That is the
        price of not moving `ops.from_first`, which the full set costs three
        points of words -- and the strip draws what `marks` passes on rather
        than everything found here, so a tick on screen is a tick the walk
        can also use.
        """
        from sync import vocal
        if self.pitch is None or not len(self.pitch):
            return []
        if self._notes is None:
            self._notes = vocal.notes(self.pitch)
        return self._notes

    def marks(self, floor: float = FLOOR) -> dict:
        """`{"starts": [...], "ends": [...]}` -- every landmark, in seconds.

        A start is an activity entrance, a flux attack or a note onset, in
        that order of trust, and each one that lands within `JOIN` of a mark
        already found is dropped as the same event heard a second way.
        `notes` is also handed back on its own, because the strip draws it
        differently: it is the weakest of the three and the one most worth
        being able to tell apart by eye.

        Ends are activity exits only. Nothing in the flux says a word STOPPED
        -- half-wave rectification threw that away on purpose, back in
        `vocal.onsets` -- and a note ending is where the next one begins, so
        an end has no second-best source and simply is not offered where the
        singing does not stop.
        """
        if floor in self._marks:
            return self._marks[floor]
        segs = self.segments()
        rises = [a for a, _ in segs]
        starts = list(rises)
        for t in self.attacks(floor):
            if not any(abs(t - r) <= JOIN for r in rises):
                starts.append(t)
        held = sorted(starts)
        notes = []
        for t in self.notes():
            k = bisect.bisect_left(held, t)
            near = held[max(0, k - 1):k + 1]
            if not any(abs(t - x) <= ALONE for x in near):
                notes.append(t)
        got = {"starts": sorted(starts + notes),
               "ends": sorted(b for _, b in segs),
               "entrances": rises, "notes": notes}
        self._marks[floor] = got
        return got

    # ----------------------------------------------------------- does it fit
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
        v = v ** gamma
        idx = (v * 255).astype("uint8")
        lut = self._ramp(ramp)
        pic = np.ascontiguousarray(lut[idx.T[::-1]])
        h, w = pic.shape[:2]
        img = QImage(pic.data, w, h, w * 3, QImage.Format.Format_RGB888)
        return img.copy()

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

    FLUX_FLOOR = 25

    def flux(self):
        """Energy ARRIVING, as a 0..1 trace on the picture's own 10ms grid.

        Why this and not the picture. The mel says how loud each band is, and
        a word start is not loudness -- it is a change in it. Measured on
        `MaKE ME FAMOUSS >_<` against 226 hand-placed word starts, and on
        `Scared of the Dark` against 419, taking how much the signal rises at
        a word start against how much it rises anywhere:

                                        rapped    sung
            the mel as drawn             1.40x    1.34x
            half-wave flux of it         1.61x    1.37x
            flux over its running floor  3.41x    2.58x

        So the picture really does not say where words start -- 1.4 times the
        background is nothing to read -- and the same audio, differenced and
        then read against its own neighbourhood, says it three times over.
        That is not a placement either (see this module's docstring, which is
        emphatic about it, and it still stands) but it is a trace somebody
        can look at and see where the singer started something.

        The running floor is what does the work. Raw flux is loud where the
        song is loud, so a peak in a quiet bar is invisible beside an ordinary
        one in a loud chorus; taking each peak against the median of its own
        neighbourhood puts the two on the same footing. It is what an onset
        detector does before it thresholds, and `vocal.attacks` is already
        thresholding something like it to make the ticks -- this is the same
        evidence drawn continuously, so the marks below the threshold can be
        seen rather than only counted.
        """
        import numpy as np
        if self._flux is not None:
            return self._flux
        mel = self.mel
        if mel is None or len(mel) < 3:
            self._flux = np.zeros(0, dtype="float32")
            return self._flux
        lo = float(np.percentile(mel, 40))
        hi = float(np.percentile(mel, 99.5))
        v = np.clip((mel - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
        rise = np.clip(np.diff(v, axis=0), 0.0, None).mean(axis=1)
        k = self.FLUX_FLOOR
        pad = np.pad(rise, (k, k), mode="edge")
        win = np.lib.stride_tricks.sliding_window_view(pad, 2 * k + 1)
        got = np.clip(rise - np.median(win, axis=-1), 0.0, None)
        floor = float(np.median(got))
        top = float(np.percentile(got, 99.0))
        out = np.clip((got - floor) / max(top - floor, 1e-6), 0.0, 1.0)
        out = (out ** 1.25).astype("float32")
        self._flux = np.concatenate([out[:1], out])
        return self._flux

    def rate(self) -> float:
        """Picture columns a second."""
        n = len(self.mel) if self.mel is not None else 0
        return (n / self.length) if (n and self.length > 0) else 100.0
