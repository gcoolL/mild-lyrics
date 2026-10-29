"""The separated vocal: a spectrogram, landmarks (activity edges, flux attacks,
note onsets) and the stem to listen to. Never returns a time on its own.
Notes: docs/notes/editor/vocalmap.md."""
from __future__ import annotations

import bisect
import hashlib
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path[:0] = [str(p) for p in (_ROOT / "mild-lyrics", _ROOT)
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


# How far a supplied vocal's length may differ from the song's, in seconds:
# past this it is not the same cut, and every mark would be out by the gap.
OWN_SLACK = 0.5

MEL_HZ = (40.0, 7600.0)     # stem/audio.py's f_min, f_max (HTK mel)


def band_hz(edge: float, bands: int = 80) -> float:
    """The frequency at mel row `edge` (0 = bottom, `bands` = top)."""
    import math
    lo, hi = (2595.0 * math.log10(1.0 + f / 700.0) for f in MEL_HZ)
    m = lo + (hi - lo) * max(0.0, min(1.0, edge / max(1, bands)))
    return 700.0 * (10.0 ** (m / 2595.0) - 1.0)


def hz_band(hz: float, bands: int = 80) -> int:
    """The nearest mel row edge to `hz` -- band_hz the other way round."""
    import math
    lo, hi = (2595.0 * math.log10(1.0 + f / 700.0) for f in MEL_HZ)
    m = 2595.0 * math.log10(1.0 + max(0.0, float(hz)) / 700.0)
    return max(0, min(bands, round((m - lo) / (hi - lo) * bands)))
# Names a separated vocal goes by next to its song: "<song> (Vocals).flac" etc.
OWN_NAMES = ("{s} (Vocals)", "{s} (vocals)", "{s}_vocals", "{s}_Vocals",
             "{s} - Vocals", "{s} - vocals", "{s}.vocals", "{s} vocals",
             "{s}-vocals")
OWN_EXTS = (".flac", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".aiff")


def find_own(path: str) -> str:
    """A separated vocal named after this song, beside it or in a "stems"
    folder there, or ""."""
    song = pathlib.Path(path)
    for where in (song.parent, song.parent / "stems", song.parent / "Stems"):
        for name in OWN_NAMES:
            for ext in OWN_EXTS:
                cand = where / (name.format(s=song.stem) + ext)
                if cand.is_file() and cand != song:
                    return str(cand)
    return ""


def is_own(path: str) -> bool:
    """Whether this song's kept vocal was supplied rather than separated."""
    try:
        import numpy as np
        z = np.load(cache_dir() / f"{_key(path)}.npz")
        return "own" in z.files and bool(z["own"][0])
    except Exception:
        return False


def forget(path: str) -> None:
    """Drop this song's kept vocal and map, so the next view separates again."""
    for f in cache_dir().glob(f"{_key(path)}*"):
        f.unlink(missing_ok=True)


def has_map(path: str) -> bool:
    """Whether this song's vocal view is already kept (no separation needed)."""
    try:
        return (cache_dir() / f"{_key(path)}.npz").exists()
    except OSError:
        return False


def cache_dir() -> pathlib.Path:
    import lyrics_gui as L
    return pathlib.Path(L.app_dir("cache")) / "vocal-view"


def stem_path(path: str) -> pathlib.Path:
    """Where this song's separated vocal is kept as audio (FLAC), for `blend`."""
    return cache_dir() / f"{_key(path)}-vocal.flac"


def blend_path(path: str, level: float) -> pathlib.Path:
    """Where the vocal-at-`level` mix of this song is kept."""
    return cache_dir() / f"{_key(path)}-mix{int(round(level * 100)):03d}.flac"


BLENDS_KEPT = 4


def blend(path: str, level: float, say=None) -> str:
    """The song with its vocal at `level` (0..1) as a file to play:
    out = stem + (mix - stem) * (1 - level). Neither end is rendered."""
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

    from .stem import audio
    import torchaudio
    tell(f"mixing the vocal up to {level * 100:.0f}%…")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part.flac")
    if _blend_streamed(path, stem, level, tmp):
        tmp.replace(out)
        _prune_blends(path, keep=out)
        return str(out)
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
    soundfile.write(str(tmp), np.asarray(got.T, dtype="float32"), int(vrate),
                    format="FLAC")
    tmp.replace(out)
    _prune_blends(path, keep=out)
    return str(out)


BLEND_BLOCK = 1 << 18


def _blend_blocks(mix_path, voc_path, level: float):
    """The blend, a few seconds at a time, as (channels, frames) tensors.

    The same sum as `blend` does over the whole song, so every sample comes
    out the same: it is per sample, and where the two files differ in channels
    the same rules are applied to each block.
    """
    import soundfile
    import torch
    with soundfile.SoundFile(str(mix_path)) as m, \
            soundfile.SoundFile(str(voc_path)) as v:
        for a, b in zip(m.blocks(blocksize=BLEND_BLOCK, dtype="float32",
                                 always_2d=True),
                        v.blocks(blocksize=BLEND_BLOCK, dtype="float32",
                                 always_2d=True)):
            n = min(len(a), len(b))
            mix = torch.from_numpy(a[:n].T.copy())
            voc = torch.from_numpy(b[:n].T.copy())
            if mix.shape[0] != voc.shape[0]:
                if mix.shape[0] == 1:
                    mix = mix.expand(voc.shape[0], -1)
                elif voc.shape[0] == 1:
                    voc = voc.expand(mix.shape[0], -1)
                else:
                    mix = mix.mean(dim=0, keepdim=True).expand(voc.shape[0], -1)
            yield voc + (mix - voc) * (1.0 - level)
            if len(a) != len(b):
                return


def _blend_streamed(path, stem, level: float, tmp) -> bool:
    """Write the blend a block at a time: True if that was possible, False for
    the cases that need the whole song (rate mismatch, unreadable mix)."""
    import soundfile
    try:
        with soundfile.SoundFile(str(path)) as m, \
                soundfile.SoundFile(str(stem)) as v:
            rate = v.samplerate
            chans = m.channels if v.channels == 1 else v.channels
            if m.samplerate != rate:
                return False
        peak = 0.0
        for got in _blend_blocks(path, stem, level):
            peak = max(peak, float(got.abs().max()))
        with soundfile.SoundFile(str(tmp), "w", samplerate=int(rate),
                                 channels=int(chans), format="FLAC") as out:
            for got in _blend_blocks(path, stem, level):
                if peak > 1.0:
                    got = got / peak
                out.write(got.T.numpy())
        return True
    except Exception:
        tmp.unlink(missing_ok=True)
        return False


def _keep_stem(path: str, sep, srate: int, tell=None) -> None:
    """Write the separated vocal out beside its map, quietly: a failure only
    hides the mix control."""
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


# The picture, apart from the 80-band mel the marks read: rows spaced like mel
# up to 20 kHz, each the loudest bin in its slice, every 5 ms. Notes 2026-10-28.
PIC_ROWS = 128
PIC_HOP = 0.005
PIC_TOP = 20000.0
PIC_KEPT = 1                # in the kept file's name; bump to redraw them all


def pic_edges(top: float, rows: int = PIC_ROWS):
    """The frequencies between the picture's rows, bottom to top."""
    import numpy as np
    lo, hi = (2595.0 * np.log10(1.0 + f / 700.0) for f in (MEL_HZ[0], top))
    return 700.0 * (10.0 ** (np.linspace(lo, hi, rows + 1) / 2595.0) - 1.0)


def _picture(path: str):
    """(log power per row, seconds, top Hz) of a file, block by block, at its
    own rate: a 25 ms Hann window centred every 5 ms."""
    import os
    import numpy as np
    import soundfile

    def run(src):
        with soundfile.SoundFile(str(src)) as f:
            rate = f.samplerate
            win = max(16, int(round(rate * 0.025)))
            hop, half = rate * PIC_HOP, win // 2
            n = np.arange(win)
            window = (0.5 - 0.5 * np.cos(2 * np.pi * n / win)).astype("float32")
            top = min(PIC_TOP, rate / 2.0)
            edge = pic_edges(top) * win / rate          # in bins
            lo = np.ceil(edge[:-1]).astype("int64")
            hi = np.ceil(edge[1:]).astype("int64")
            thin = hi <= lo                             # no bin inside: the nearest
            lo[thin] = np.round((edge[:-1] + edge[1:])[thin] / 2).astype("int64")
            nbin = win // 2 + 1
            lo = np.clip(lo, 0, nbin - 1)
            hi = np.clip(np.maximum(hi, lo + 1), 1, nbin)
            buf = np.zeros(half, dtype="float32")   # buf[0] is sample -half
            base, done, total, rows = -half, 0, 0, []

            def take(upto: int) -> None:
                nonlocal buf, base, done
                end = base + len(buf)
                last = min(upto, int((end - win + half) // hop) + 1)
                while done < last:
                    idx = np.arange(done, min(last, done + 1024))
                    at = np.round(idx * hop).astype("int64") - half - base
                    frames = buf[at[:, None] + n] * window
                    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
                    rows.append(np.stack([power[:, a:b].max(axis=1)
                                          for a, b in zip(lo, hi)], axis=1))
                    done = int(idx[-1]) + 1
                cut = int(round(done * hop)) - half - base
                if cut > 0:
                    buf, base = buf[cut:], base + cut

            for chunk in f.blocks(blocksize=int(hop * 1024), dtype="float32",
                                  always_2d=True):
                total += len(chunk)
                buf = np.concatenate([buf, chunk.mean(axis=1)])
                take(1 << 62)
            buf = np.concatenate([buf, np.zeros(win, dtype="float32")])
            take(int(total // hop) + 1)
        if not rows or not total:
            raise ValueError("no audio in that file")
        spec = np.log(np.concatenate(rows) + 1e-6)
        return spec.astype("float16"), total / float(rate), top

    try:
        return run(path)
    except Exception:
        import tempfile
        import noconsole
        fd, name = tempfile.mkstemp(prefix="mild-editor-spec-", suffix=".wav")
        os.close(fd)
        try:
            noconsole.run(["ffmpeg", "-v", "quiet", "-y", "-i", str(path),
                           "-ac", "1", "-ar", "44100", name], check=True)
            return run(name)
        finally:
            pathlib.Path(name).unlink(missing_ok=True)


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
        self._flux_cut = None
        self._notes = None
        self.pic = None             # see _picture; None draws the mel instead
        self.pic_top = PIC_TOP

    # ------------------------------------------------------------- building
    @classmethod
    def build(cls, path: str, stems: bool = True, device: str = "auto",
              spare: float = 0.4, say=None, reuse: bool = True,
              own: str = "") -> "VocalMap":
        """Separate `path`, or read back the last time it was separated.
        `own`: a vocal somebody already has, used instead of separating."""
        import numpy as np
        tell = say or (lambda _m: None)
        store = cache_dir() / f"{_key(path)}{'' if stems else '-mix'}.npz"
        if own:
            reuse = False
        if reuse and store.exists():
            try:
                got = cls._read(store, stems, want_stem=path if stems else "")
                got._draw_from(path, stems, tell)
                tell("vocal view — read back from the last time")
                return got
            except Exception:
                store.unlink(missing_ok=True)

        from .stem import audio, spare_cores, vocal
        tell("reading the audio…")
        wave, rate = audio.read(path)
        with spare_cores():
            if own:
                tell("reading your vocal…")
                sep, srate = audio.read(own)
                gap = sep.shape[-1] / float(srate) - wave.shape[-1] / float(rate)
                if abs(gap) > OWN_SLACK:
                    raise ValueError(
                        f"your vocal is {abs(gap):.1f}s {'longer' if gap > 0 else 'shorter'}"
                        " than the song, so it is not the same cut")
                if srate != rate:
                    import torchaudio
                    sep = torchaudio.functional.resample(sep, srate, rate)
                    srate = rate
                del wave
                mono = audio.mono16k(sep, srate)
                _keep_stem(path, sep, srate, tell)
                del sep
            elif stems:
                from .stem import separate
                sep, srate = separate.vocal(wave, rate, device, tell)
                del wave
                mono = audio.mono16k(sep, srate)
                _keep_stem(path, sep, srate, tell)
                del sep
            else:
                mono = audio.mono16k(wave, rate)
                del wave
            tell("looking at the spectrum…")
            spectrum = audio.mel(mono)
            mel = spectrum.numpy()
            present = vocal.activity(mono).numpy()
            onset = vocal.onsets(mono, mel=spectrum).numpy()
            pitch = vocal.pitch(mono).numpy()
        got = cls(mel.astype("float32"), present, onset,
                  mono.shape[0] / float(audio.RATE), audio.FRAME, stems,
                  pitch.astype("float32"))
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(store, mel=mel.astype("float16"),
                                present=present, onset=onset,
                                pitch=pitch.astype("float32"),
                                length=np.array([got.length], dtype="float64"),
                                own=np.array([1 if own else 0], dtype="int8"))
        except Exception:
            pass
        got._draw_from(path, stems, tell, fresh=True)
        return got

    @classmethod
    def mixture(cls, path: str, say=None, reuse: bool = True) -> "VocalMap":
        """The song's own spectrogram, unseparated: numpy and soundfile only.
        A picture and nothing more -- no marks, no flux (see the module
        docstring for why the mixture's attacks say nothing)."""
        import numpy as np
        tell = say or (lambda _m: None)
        (cache_dir() / f"{_key(path)}-spec.npz").unlink(missing_ok=True)
        got = cls(None, np.zeros(0), np.zeros(0), 0.0, 0.02, False)
        got._draw_from(path, False, tell, fresh=not reuse, name="-spec")
        if got.pic is None:
            raise ValueError("no audio in that file")
        return got

    def _draw_from(self, path: str, stems: bool, tell, fresh: bool = False,
                   name: str = "-mix") -> None:
        """Give the map its picture: from the kept vocal for a vocal view,
        else from the song, read back when it was drawn before."""
        import numpy as np
        src = stem_path(path) if stems else pathlib.Path(path)
        if not src.exists():
            return
        store = cache_dir() / f"{_key(path)}{'' if stems else name}-pic{PIC_KEPT}.npz"
        if not fresh and store.exists():
            try:
                z = np.load(store)
                self.pic, self.pic_top = z["pic"], float(z["top"][0])
                self.length = self.length or float(z["length"][0])
                return
            except Exception:
                store.unlink(missing_ok=True)
        tell("drawing the spectrogram…")
        try:
            pic, length, top = _picture(str(src))
        except Exception:
            if not stems:
                raise
            return                  # the vocal view still draws its mel
        self.pic, self.pic_top = pic, top
        self.length = self.length or length
        try:
            store.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(store, pic=pic, top=np.array([top]),
                                length=np.array([length], dtype="float64"))
        except Exception:
            pass

    @classmethod
    def _read(cls, store: pathlib.Path, stems: bool,
              want_stem: str = "") -> "VocalMap":
        """Read a kept map back, or raise if a part is missing, so the song
        goes through `build` again."""
        import numpy as np
        from .stem import audio
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
        from .stem import vocal
        return vocal.attacks(self.onset, floor)

    def notes(self) -> list[float]:
        """Where the singing changes note: onsets that read a chopped vocal,
        which has neither edges nor attacks."""
        from .stem import vocal
        if self.pitch is None or not len(self.pitch):
            return []
        if self._notes is None:
            self._notes = vocal.notes(self.pitch)
        return self._notes

    def marks(self, floor: float = FLOOR) -> dict:
        """`{"starts": [...], "ends": [...]}` in seconds: starts by trust, a
        mark within `JOIN` of another dropped; ends are activity exits only.
        `notes` returned too."""
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
        """Whether this audio is plausibly the song `spans` was timed against:
        is the vocal much likelier to sound inside words than in rests?"""
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
              gamma: float = 1.35, bands: tuple[int, int] | None = None,
              floor_pct: float = 40.0, hz: tuple[float, float] | None = None,
              per_band: bool = False):
        """The picture (or the mel) as a coloured QImage, framed by the song's
        own percentiles -- each row by its own with `per_band` -- colour ramp
        applied in numpy. `hz` cuts the picture, `bands` the mel."""
        import numpy as np
        from PyQt6.QtGui import QImage
        mel = self._pic_rows(hz) if self.pic is not None else self._bands(bands)
        if mel is None or not len(mel):
            return None
        some = mel[::max(1, len(mel) // 20000)].astype("float32")
        axis = 0 if per_band else None
        lo = np.percentile(some, floor_pct, axis=axis) if floor is None else floor
        hi = np.percentile(some, 99.5, axis=axis) if ceiling is None else ceiling
        span = np.maximum(hi - lo, 1e-6)
        idx = np.empty(mel.shape, dtype="uint8")
        for a in range(0, len(mel), 8192):
            v = np.clip((mel[a:a + 8192].astype("float32") - lo) / span, 0.0, 1.0)
            idx[a:a + 8192] = (v ** gamma * 255).astype("uint8")
        lut = self._ramp(ramp)
        pic = np.ascontiguousarray(lut[idx.T[::-1]])
        h, w = pic.shape[:2]
        img = QImage(pic.data, w, h, w * 3, QImage.Format.Format_RGB888)
        return img.copy()

    def _pic_rows(self, hz):
        """The picture cut to the rows that reach into `hz`, or all of it."""
        if hz is None:
            return self.pic
        edge = pic_edges(self.pic_top, self.pic.shape[1])
        lo, hi = hz
        keep = [r for r in range(len(edge) - 1) if edge[r + 1] > lo and edge[r] < hi]
        if not keep:
            keep = [0]
        return self.pic[:, keep[0]:keep[-1] + 1]

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

    def _bands(self, bands):
        """The mel cut to mel rows [lo, hi), or all of it for None."""
        mel = self.mel
        if mel is None or bands is None:
            return mel
        lo, hi = bands
        lo = max(0, min(int(lo), mel.shape[1] - 1))
        hi = max(lo + 1, min(int(hi), mel.shape[1]))
        return mel if (lo, hi) == (0, mel.shape[1]) else mel[:, lo:hi]

    FLUX_FLOOR = 25

    def flux(self, bands: tuple[int, int] | None = None):
        """Energy arriving, as a 0..1 trace on the 10ms grid: half-wave flux
        against the loudest of the 5 bands around it 2 frames back (SuperFlux:
        vibrato is not an attack), over its running median floor."""
        import numpy as np
        mel = self._bands(bands)
        whole = mel is self.mel
        if whole and self._flux is not None:
            return self._flux
        if not whole and self._flux_cut is not None \
                and self._flux_cut[0] == bands:
            return self._flux_cut[1]
        if mel is None or len(mel) < 3:
            return np.zeros(0, dtype="float32")
        lo = float(np.percentile(mel, 40))
        hi = float(np.percentile(mel, 99.5))
        v = np.clip((mel - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
        reach, lag = 2, 2
        pad = np.pad(v, ((0, 0), (reach, reach)), mode="edge")
        was = np.lib.stride_tricks.sliding_window_view(
            pad, 2 * reach + 1, axis=1).max(axis=-1)
        rise = np.zeros(len(v) - 1, dtype="float32")
        rise[lag - 1:] = np.clip(v[lag:] - was[:-lag], 0.0, None).mean(axis=1)
        k = self.FLUX_FLOOR
        pad = np.pad(rise, (k, k), mode="edge")
        win = np.lib.stride_tricks.sliding_window_view(pad, 2 * k + 1)
        got = np.clip(rise - np.median(win, axis=-1), 0.0, None)
        floor = float(np.median(got))
        top = float(np.percentile(got, 99.0))
        out = np.clip((got - floor) / max(top - floor, 1e-6), 0.0, 1.0)
        out = (out ** 1.25).astype("float32")
        out = np.concatenate([out[:1], out])
        if whole:
            self._flux = out
        else:
            self._flux_cut = (bands, out)
        return out

    def rate(self) -> float:
        """Mel frames a second."""
        n = len(self.mel) if self.mel is not None else 0
        return (n / self.length) if (n and self.length > 0) else 100.0

    def pic_rate(self) -> float:
        """Picture columns a second."""
        if self.pic is None:
            return self.rate()
        n = len(self.pic)
        return (n / self.length) if (n and self.length > 0) else 1.0 / PIC_HOP
