"""Timing a part of a song with the sync model, on demand.

The model is the same one the player aligns whole songs with. What is
different here is the scope: an editor asks for a verse, a line, or the two
words that came out wrong, against a song whose other lines are already timed
and must not move. So this keeps the expensive half -- decoding the audio and
running the network over it -- for as long as the song is open, and each
request is only a search through emissions that are already in memory.

Two shapes of request:

  * a WINDOW. The selected lines are aligned inside the stretch of audio
    between the timed line before them and the timed line after them, so the
    search cannot wander into a neighbouring verse and the lines around the
    selection are untouched. This is what the section button does.
  * the WHOLE song. One forced alignment over everything, which is what makes
    a repeated chorus land on the right repeat -- the path cannot go
    backwards, so the fourth chorus cannot borrow the second's timing.

Either way only TIMES come back. The words are the user's, and the model is
never allowed to change them.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path[:0] = [str(p) for p in (_ROOT / "aligner", _ROOT)
                if str(p) not in sys.path]

from .model import Doc, Group, Syl  # noqa: E402


# How far past the NEXT line's start an ad-lib may still be ringing. The
# aligner allows itself two seconds to find one after the line it answers
# (generate._window); this is the matching allowance for keeping it.
BG_TAIL = 2.0


class NoModel(RuntimeError):
    """There is no trained checkpoint on this machine."""


def checkpoint(stems: bool = False) -> str:
    import lyrics_gui as L
    return L._sync_ckpt(stems)


def player_choice() -> dict:
    """What Mild Lyrics itself would run, read from its own settings.

    Not the editor's argparse defaults. The two ran different checkpoints on
    the same song and neither said so: the player takes `align_stems` from
    its config, and which model that selects is the whole difference between
    a mixture-trained and a stem-trained network.
    """
    import lyrics_gui as L
    cfg = L.load_settings()
    stems = bool(cfg.get("align_stems", L.DEFAULTS.get("align_stems", False)))
    return {"stems": stems,
            "device": str(cfg.get("align_device",
                                  L.DEFAULTS.get("align_device", "auto"))),
            "spare": float(cfg.get("align_spare",
                                   L.DEFAULTS.get("align_spare", 0.4))),
            "model": str(cfg.get("align_model",
                                 L.DEFAULTS.get("align_model", "sync"))),
            "ckpt": checkpoint(stems)}


def _meta(path: pathlib.Path) -> dict:
    """Step, calibration and whether it has a boundary head, cached on disk.

    Reading a checkpoint means unpickling a gigabyte, and there are eleven of
    them here. The answer only changes when the file does, so it is kept
    against the file's size and mtime.
    """
    from . import keys as K
    stat = path.stat()
    key = f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}"
    store = K.config().get("ckpt_meta") or {}
    if key in store:
        return store[key]
    got = {"step": None, "boundary": False, "calibration": None}
    try:
        import torch
        raw = torch.load(path, map_location="cpu", weights_only=False)
        got = {"step": raw.get("step"),
               "boundary": any(k.startswith("boundary.")
                               for k in raw.get("weights", {})),
               "calibration": raw.get("calibration")}
    except Exception:
        pass
    store = {k: v for k, v in store.items() if k.split(":")[0] != path.name}
    store[key] = got
    K.remember(ckpt_meta=store)
    return got


def checkpoints(rescan: bool = False) -> list[dict]:
    """Every trained model on this machine, newest first.

    `rescan` drops the player's memo of which checkpoint wins, which is
    `lru_cache`d for the life of the process -- so a model that finished
    training while this window was open is invisible until something asks for
    it again.
    """
    import lyrics_gui as L
    if rescan:
        L._sync_ckpt.cache_clear()
    out = []
    for path in sorted(L.SYNC_HOME.glob("syncnet*.pt")):
        info = dict(_meta(path))
        info.update(path=str(path), name=path.name,
                    mtime=path.stat().st_mtime,
                    # the same reading _sync_ckpt uses to pair a model with
                    # the audio it was trained on
                    stems=any(k in path.name for k in ("-stem", "-pitch")),
                    draft=path.name.endswith("-lowloss.pt"))
        out.append(info)
    return sorted(out, key=lambda d: -d["mtime"])


class Engine:
    """The model, the song, and everything derived from the pair.

    Built lazily and kept. Loading the network costs about four seconds and
    listening to a song about half of one, so an editor that dropped both
    between two clicks of the same button would spend all its time starting
    the engine.
    """

    def __init__(self, stems: bool = False, device: str = "auto",
                 spare: float = 0.4, ckpt: str = "", cut: bool = True) -> None:
        self.stems = bool(stems)
        self.device = device
        self.spare = spare
        # "" means whichever the player would pick for this stems setting.
        self.ckpt = str(ckpt or "")
        # Cut a whole word into syllables from the model's character path, as
        # the player does. Off leaves the words whole and times them as one
        # piece each; a word the user has already split is never re-cut
        # either way.
        self.cut = bool(cut)
        self.path = ""
        self._net = None
        self._rest: dict = {}
        self._loaded = ""
        self._logp = None
        self._boundary = None
        self._present = None
        self._onset = None
        self._dev = "cpu"

    # ----------------------------------------------------------------- setup
    def load(self, audio_path: str, log=None) -> None:
        """Have this song's emissions ready. Cheap after the first call."""
        say = log or (lambda _m: None)
        if self.path == audio_path and self._logp is not None:
            return
        import torch
        from sync import audio, generate as GEN, model as M, vocal

        ckpt = self.ckpt or checkpoint(self.stems)
        if not ckpt:
            raise NoModel(
                "no sync checkpoint on this machine — train one with "
                "`python -m sync.sync train`, or time by hand")
        want = "cuda" if (self.device != "cpu" and torch.cuda.is_available()) else "cpu"
        if self._net is None or self._dev != want or self._loaded != ckpt:
            say(f"loading {pathlib.Path(ckpt).name}…")
            self._loaded = ckpt
            self._net, self._rest = M.load(ckpt, want)
            self._dev = want
        say("listening to the song…")
        wave, rate = audio.read(audio_path)
        mono = audio.mono16k(wave, rate)
        if self.stems:
            import local_align as LA
            dev, win, _ = LA.room("gpu", LA.DEMUCS_COST, LA.DEMUCS_WINDOW, self.spare)
            sep, srate = LA.separate(wave, rate, dev, win, LA.MODEL, None, None)
            mono = audio.mono16k(sep, srate)
            LA.release()
        logp, boundary = M.emit(self._net, mono, self._dev, return_boundary=True)
        if not getattr(self._net, "has_boundary", True):
            boundary = None
        self._logp, self._boundary = logp, boundary
        self._present = vocal.activity(mono, logp.shape[0])
        self._onset = vocal.onsets(mono, logp.shape[0])
        self.path = audio_path
        self._gen = GEN
        say(f"ready — {audio.seconds(logp.shape[0]):.0f}s of audio")

    def drop(self) -> None:
        """Let go of the audio, keeping the network."""
        self._logp = self._boundary = self._present = self._onset = None
        self.path = ""

    @property
    def lag(self) -> float:
        """The checkpoint's standing lateness, to be taken off every answer."""
        return -float(self._rest.get("calibration") or 0.0)

    # ------------------------------------------------------------- the work
    def time_lines(self, doc: Doc, indices: list[int],
                   window: tuple[float, float] | None = None,
                   log=None) -> tuple[int, int]:
        """Time these lines in place. Returns (words placed, words asked).

        `window` bounds the search. None means the whole song, which is only
        right when the selection IS the whole song -- see the note above about
        repeated choruses.
        """
        from sync import audio, ctcalign
        say = log or (lambda _m: None)
        if self._logp is None:
            raise RuntimeError("no song loaded")
        idx = [i for i in sorted(set(indices)) if 0 <= i < len(doc.lines)]
        if not idx:
            return 0, 0

        lo, hi = 0, self._logp.shape[0]
        base = 0.0
        if window:
            a, b = window
            lo = max(0, audio.frames(max(0.0, a)))
            hi = min(self._logp.shape[0], audio.frames(b))
            base = audio.seconds(lo)
        if hi - lo < 4:
            return 0, sum(len(ln.lead.words()) for ln in
                          (doc.lines[i] for i in idx))

        logp = self._logp[lo:hi]
        cut = (lambda t: None if t is None else t[lo:hi])
        # The lead voices of the selection are ONE sequence, in the order they
        # are written: that is what stops line two being timed before line one.
        runs: list[tuple[int, Group]] = []
        flat: list[str] = []
        owner: list[tuple[int, Group, int]] = []
        for i in idx:
            g = doc.lines[i].lead
            for w, run in enumerate(g.words()):
                flat.append(g.word_text(run))
                owner.append((i, g, w))
            runs.append((i, g))
        if not flat:
            return 0, 0
        say(f"placing {len(flat)} word(s)…")
        rows = ctcalign.words(
            logp, flat, self._dev,
            prior_from=None if window is None else self._logp,
            boundary=cut(self._boundary), present=cut(self._present),
            gate=self._gen.GATE, onset=cut(self._onset),
            attack=self._gen.ATTACK, sustain=self._gen.SUSTAIN)
        placed = self._apply(rows, owner, base + self.lag, self.cut)

        # Backing voices are not in that sequence, because they are not sung
        # in it: an ad-lib answers its line from inside or just after it. Each
        # is searched inside its own line's span, exactly as the whole-song
        # aligner does.
        for i in idx:
            ln = doc.lines[i]
            if not ln.bg:
                continue
            a, b = ln.lead.span()
            if a is None:
                continue
            nxt = next((doc.lines[j].span()[0] for j in range(i + 1, len(doc.lines))
                        if doc.lines[j].span()[0] is not None), None)
            end = b + 2.0 if b is not None else a + 4.0
            if nxt is not None:
                end = min(end, max(nxt, b or a))
            # How far back an ad-lib may be found. An answering voice usually
            # comes in over the end of the line it answers -- but one marked
            # as opening its line sounds BEFORE it, and searching from the
            # lead's own start means it can only ever be placed after the
            # words it precedes.
            prev = next((doc.lines[j].span()[1] for j in range(i - 1, -1, -1)
                         if doc.lines[j].span()[1] is not None), None)
            early = max(0.0, prev if prev is not None else a - 4.0)
            for g in ln.bg:
                placed += self._inside(g, (early if g.lead_in else a, end))
        polish(doc, idx)
        return placed, len(flat) + sum(len(g.words())
                                       for i in idx for g in doc.lines[i].bg)

    def _inside(self, g: Group, window: tuple[float, float]) -> int:
        from sync import audio, ctcalign
        a, b = window
        lo = max(0, audio.frames(a))
        hi = min(self._logp.shape[0], audio.frames(b))
        words = [g.word_text(run) for run in g.words()]
        if hi - lo < len(" ".join(words)) or not words:
            return 0
        cut = (lambda t: None if t is None else t[lo:hi])
        rows = ctcalign.words(self._logp[lo:hi], words, self._dev,
                              prior_from=self._logp,
                              boundary=cut(self._boundary),
                              present=cut(self._present), gate=self._gen.GATE,
                              onset=cut(self._onset), attack=self._gen.ATTACK)
        owner = [(0, g, w) for w in range(len(words))]
        return self._apply(rows, owner, audio.seconds(lo) + self.lag, self.cut)

    def _apply(self, rows, owner, base: float, cut: bool = True) -> int:
        """Write the model's word times onto the document.

        Two things happen here, and both are the player's own behaviour --
        see sync/generate.document, which is what Mild Lyrics runs when it
        times a song by itself:

          * a word the user has NOT split is cut into syllables from the
            model's per-character path, exactly as generate._syllables cuts
            it. This is strictly better than cutting it afterwards by letter
            count, because the model actually heard where the letters were.
          * a word the user HAS split keeps their pieces, and they are timed
            from the same character path. Their splits are theirs; nothing
            here re-cuts them.

        Words are applied back-to-front within a group, because cutting one
        into three changes the indices of everything after it.
        """
        from sync import generate as GEN
        by = {r["i"]: r for r in rows}
        jobs: dict = {}
        for k, (_line, g, w) in enumerate(owner):
            row = by.get(k)
            if row:
                jobs.setdefault(id(g), (g, []))[1].append((w, row))
        placed = 0
        for g, items in jobs.values():
            for w, row in sorted(items, key=lambda x: -x[0]):
                runs = g.words()
                if w >= len(runs):
                    continue
                run = runs[w]
                start = row["start"] + base
                end = max(row["end"] + base, start)
                chars = [(a + base, b + base) for a, b in (row.get("chars") or [])]
                if len(run) == 1 and cut:
                    text = g.syls[run[0]].text
                    pieces = GEN._syllables(text, {"start": start, "end": end,
                                                   "chars": chars})
                    if len(pieces) > 1:
                        g.syls[run[0]:run[0] + 1] = [
                            Syl(str(y["Text"]), float(y["StartTime"]),
                                float(y["EndTime"]), bool(y["IsPartOfWord"]))
                            for y in pieces]
                        placed += 1
                        continue
                if len(run) == 1:
                    g.syls[run[0]].start, g.syls[run[0]].end = start, end
                    placed += 1
                    continue
                spans = _share(g, run, chars, start, end)
                for j, (a, b) in zip(run, spans):
                    g.syls[j].start, g.syls[j].end = a, b
                placed += 1
        return placed


def polish(doc: Doc, indices=None) -> None:
    """The player's own finishing passes, over what was just timed.

    `sweep` is the one that shows. A player draws a moving highlight, and
    what a viewer reads is the SWEEP rather than the endpoint -- so a
    syllable runs to wherever the next one begins unless the gap is a real
    pause. Measured on Clocks before this existed: 94% of the player's
    consecutive syllables touched exactly and 10% of the editor's did, with a
    60 ms hole between every other word. Every endpoint was within a few
    hundredths of the player's, and it still read as words ending early --
    for exactly the reason generate.sweep gives.

    `settle` is the guard after it: times that only ever move forwards, with
    a backing run clamped inside the line it answers.

    Both are imported rather than reimplemented. They are the definition of
    what the player will draw, and a second copy here would be a second thing
    to keep in step with it.
    """
    from sync import generate as GEN
    lines = (range(len(doc.lines)) if indices is None
             else [i for i in indices if 0 <= i < len(doc.lines)])
    for i in lines:
        for g in doc.lines[i].groups():
            timed = [(k, s) for k, s in enumerate(g.syls) if s.timed]
            if len(timed) < 2:
                continue
            rows = [{"i": k, "StartTime": float(s.start),
                     "EndTime": float(s.end if s.end is not None else s.start)}
                    for k, s in timed]
            for got in GEN.sweep(rows):
                s = g.syls[got["i"]]
                s.start, s.end = float(got["StartTime"]), float(got["EndTime"])

    # ...then settle, over the whole document: it is a cross-line guard, and
    # the lines around a re-timed section are part of what it checks.
    items, back = [], []
    for ln in doc.lines:
        item: dict = {}
        for voice, g in enumerate(ln.groups()):
            if not g.syls or any(not s.timed for s in g.syls):
                continue                  # settle cannot read an untimed run
            if voice:
                # Backing voices are ordered below instead of by settle.
                #
                # settle clamps every backing run inside its LEAD's span. An
                # ad-lib that opens the line collapses onto the lead's first
                # syllable (9.0-10.0s became 10.5-10.5 under a line starting
                # at 10.5), and one that answers after the line ends collapses
                # onto its last. Neither is what an ad-lib does, and the
                # renderer already disagrees with it: _covering widens the <p>
                # precisely to hold voices that sound outside the lead.
                #
                # So they are put in order against the lines around them
                # rather than squeezed into the line above them.
                continue
            syls = []
            for s in g.syls:
                syls.append({"StartTime": float(s.start),
                             "EndTime": float(s.end if s.end is not None
                                              else s.start)})
                back.append(s)
            group = {"Syllables": syls}
            if voice == 0:
                item["Lead"] = group
                item["StartTime"] = syls[0]["StartTime"]
                item["EndTime"] = max(y["EndTime"] for y in syls)
            else:
                item.setdefault("Background", []).append(group)
        if item:
            items.append(item)
    if not items:
        return
    GEN.settle(items)
    _order_backing(doc, GEN)
    at = 0
    for item in items:
        for group in ([item["Lead"]] if "Lead" in item else []) + list(
                item.get("Background") or []):
            for y in group["Syllables"]:
                back[at].start = float(y["StartTime"])
                back[at].end = float(y["EndTime"])
                at += 1


def _order_backing(doc: Doc, GEN) -> None:
    """Put each backing voice in order, where it actually sounds.

    An ad-lib is allowed to overlap the line before it and to ring on past
    the line it belongs to -- both are ordinary, and both are what a listener
    hears. The only bounds are the lines on either side: it may not begin
    before the previous line began, and may not run into the verse after the
    next line starts. Inside that, only real disorder is corrected.
    """
    for i, ln in enumerate(doc.lines):
        runs = [g for g in ln.bg
                if g.syls and all(s.timed for s in g.syls)]
        if not runs:
            continue
        floor = next((doc.lines[j].span()[0] for j in range(i - 1, -1, -1)
                      if doc.lines[j].span()[0] is not None), 0.0)
        after = next((doc.lines[j].span()[0] for j in range(i + 1, len(doc.lines))
                      if doc.lines[j].span()[0] is not None), None)
        ceiling = None if after is None else after + BG_TAIL
        for g in runs:
            rows = []
            for s in g.syls:
                a = max(float(s.start), floor)
                b = max(float(s.end if s.end is not None else s.start), a)
                if ceiling is not None:
                    a, b = min(a, ceiling), min(b, ceiling)
                rows.append({"StartTime": a, "EndTime": b})
            for s, y in zip(g.syls, GEN._ordered(rows, None)):
                s.start, s.end = float(y["StartTime"]), float(y["EndTime"])


def _share(g: Group, run: list[int], chars, start: float, end: float):
    """One word's span, divided among the syllables it was written in.

    By characters where the model gave them -- each syllable takes the frames
    its own letters were placed on -- and by letter count where it did not,
    which is a guess but a proportionate one.
    """
    from sync import text as T
    lens = [max(len(T.flatten(g.syls[j].text)), 0) for j in run]
    total = sum(lens)
    if chars and total and len(chars) >= total:
        out, at = [], 0
        for n in lens:
            span = chars[at:at + n] if n else []
            at += n
            if span:
                out.append((span[0][0], span[-1][1]))
            else:
                out.append((out[-1][1] if out else start,
                            out[-1][1] if out else start))
        out[0] = (start, out[0][1])
        out[-1] = (out[-1][0], max(end, out[-1][1]))
        return out
    weights = [max(n, 1) for n in lens] or [1]
    span, at, out = end - start, 0.0, []
    tot = sum(weights)
    for wgt in weights:
        a = start + span * at / tot
        at += wgt
        out.append((a, start + span * at / tot))
    return out


def bounds(doc: Doc, indices: list[int], duration: float,
           pad: float = 0.35) -> tuple[float, float]:
    """The stretch of audio a selection is allowed to be found in.

    From the end of the last timed line before it to the start of the first
    timed line after it, so nothing outside the selection can be disturbed
    and nothing inside it can be placed on a neighbour's words. A little
    padding either side, because a line's first syllable often begins under
    the tail of the one before.
    """
    idx = sorted(i for i in indices if 0 <= i < len(doc.lines))
    if not idx:
        return 0.0, duration
    before = [doc.lines[j].span()[1] for j in range(0, idx[0])
              if doc.lines[j].span()[1] is not None]
    after = [doc.lines[j].span()[0] for j in range(idx[-1] + 1, len(doc.lines))
             if doc.lines[j].span()[0] is not None]
    lo = max(before) - pad if before else 0.0
    hi = min(after) + pad if after else (duration or 0.0)
    if hi <= lo:
        hi = duration or (lo + 30.0)
    return max(0.0, lo), hi
