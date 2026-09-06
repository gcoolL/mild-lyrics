"""Measuring the model in seconds, against lyrics people timed by hand.

    python -m sync.sync bench                 the songs it was never shown
    python -m sync.sync bench --songs 20
    python -m sync.sync bench --calibrate     and fix its standing bias

Only held-out songs are measured, chosen by the same hash of the song's name
the trainer split on, so this cannot accidentally be scored on a song it has
memorised. The reference is the spl document as it was snapshotted.

What is reported, and why each one is there:

  median      where the model sits against the reference on average. A whole
              song shifted by a fifth of a second reads here and nowhere else.
  |median|    the same number with the sign taken off first -- the size of a
              typical error, which a signed median hides when half the words
              are early and half are late.
  within 0.3s the share a listener would call correct.
  lost        the share more than a second out. These are not timing errors,
              they are the alignment having gone somewhere else entirely, and
              one of them is worth more attention than fifty near misses.
  spread      how scattered the errors are around their own median. This is
              the number that separates "this copy is displaced" from "this
              alignment is a mess" -- a displaced song has a large median and a
              small spread, and correcting it is a subtraction. A mess has both.

And then, because none of the above can see the thing people actually complain
about -- WHERE the wrong words are, rather than how many:

  adrift      the share of words more than a second from where their own song
              sits. `lost` measured against zero and so condemned every word of
              a displaced copy; this measures against the song's own median.
  runs        how many separate places the alignment went somewhere else.
  longest     the worst of them, in consecutive words. This is the number that
              tells forty scattered near-misses from one block of forty, which
              are the same `adrift` and not remotely the same file.
  blocks      the share of adrift words inside a run of five or more. Measured
              here it sits around three quarters, so the blocks ARE the problem
              and a summary that cannot see them is reporting the wrong thing.
  tail        the same share over the last tenth of a song, where it roughly
              doubles -- not because the model hears less there (it barely
              does) but because that is where damage from earlier blocks lands.
  verdict     clean, locally broken, or displaced. The headline is how many
              songs came out clean, not what the errors averaged: one song can
              carry most of the error and seventeen songs can average to a
              number none of them has.

The settings the run used are written into the report. They used to differ from
the ones the generator ships -- gate, attack and sustain all defaulted to 0 here
and to 2.0, 0.12 and 0.8 there -- and no report said which of the two it was, so
two reports could disagree about the model while agreeing about everything
except the one thing that was different.

The references carry their own error: they were typed by people, against a
master, and a song sitting at 0.05-0.10s here is inside the noise of what it is
being compared to. Differences that small between two runs are not results.

SEPARATION IS OFF BY DEFAULT. The model reads the song as it was mixed. A
separated vocal is cleaner but it is also invented: demucs leaves smearing and
phantom onsets exactly where a quiet consonant sits under a cymbal, and a
timing model taught on those artefacts learns to time the artefact. Pass
--stem to turn separation back on; if you do, everything downstream has to be
stem too, because a model trained on one and run on the other is a domain
mismatch and will read as "the timings got worse".
"""
from __future__ import annotations

import contextlib
import json
import pathlib
import statistics
import sys
import time

from . import audio, ctcalign, data, dataset, jar, model as M, offset, text

ALIGNER = pathlib.Path(__file__).resolve().parent.parent / "aligner"
sys.path.insert(0, str(ALIGNER))

HOME = pathlib.Path.home() / ".cache/mild-lyrics/sync"
REPORTS = pathlib.Path(__file__).resolve().parent / "reports"

# The audio the benchmark is allowed to keep forever.
#
# The player's own `fetched/` cache is an LRU with a cap, which is right for a
# player and wrong for a benchmark: a held-out song's copy gets evicted, the
# next run searches YouTube again, and comes back with a DIFFERENT recording of
# the same length. That is not hypothetical -- "Three Days Grace - Apologies"
# measured 0.190s in two runs, was evicted, was re-fetched tonight, and
# measured 1.386s on a copy the model plainly disagrees with. Nothing about the
# model had changed.
#
# A benchmark whose inputs move cannot answer "did that change help", which is
# the only question it exists to answer. So the copies live here, outside the
# cap, and are never replaced once written.
AUDIO = HOME / "bench-audio"


def _pairs(mine: list[dict], ref: list[tuple[str, float, float]]):
    """Pair model words with reference words in text order."""
    from difflib import SequenceMatcher
    a = [text.flatten(w["word"]) for w in mine]
    b = [text.flatten(w) for w, _s, _e in ref]
    out = []
    for i, j, n in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(n):
            if a[i + k]:
                # The reference index rides along as a fourth field. Everything
                # that reads a pair reads r[1] and r[2] by position and stops,
                # so nothing downstream notices -- but _detail can now say WHERE
                # in the song a word was, which is the whole of the run
                # structure.
                out.append((mine[i + k], tuple(ref[j + k]) + (j + k,)))
    return out

def _errors(mine: list[dict], ref: list[tuple[str, float, float]]) -> list[float]:
    return [m["start"] - r[1] for m, r in _pairs(mine, ref)]

def _end_errors(mine: list[dict], ref: list[tuple[str, float, float]]) -> list[float]:
    return [m["end"] - r[2] for m, r in _pairs(mine, ref)]


def _detail(mine: list[dict], ref: list[tuple[str, float, float]],
            words: int) -> list[dict]:
    """One row per paired word: where it sits in the song, and how wrong it was.

    THE THING THE SUMMARY CANNOT SAY. `lost` is a share, and a share cannot
    tell forty scattered near-misses from one block of forty consecutive words
    in the wrong verse -- which are the same number and not remotely the same
    file. The block is what a listener calls a mess-up, and it needs the words
    in order, each with the place it came from, to be seen at all.

    `at` is the index into the REFERENCE's word sequence, not into the pairs:
    words the alphabet could not spell are absent from the alignment, so the
    pairs are not the song. Carrying the reference index is what lets a run of
    lost words be located in the song rather than in the list.
    """
    out = []
    for m, r in _pairs(mine, ref):
        out.append({"at": r[3] if len(r) > 3 else -1,
                    "err": round(m["start"] - r[1], 4),
                    "end_err": round(m["end"] - r[2], 4),
                    "score": round(float(m.get("score") or 0.0), 4)})
    for row in out:
        row["of"] = words
    return out


WORST = 30


def score(errs: list[float], at: list[int] | None = None) -> dict:
    """What a set of word errors amounts to. NOT just a median.

    The median was the headline here for a while and it lied twice in one
    evening. "Coldplay - Clocks" reported 0.046s -- which reads as the best
    song in the set -- while a fifth of its words sat more than a second out
    and the file was unusable. A median cannot see a tail, and a lyric file is
    exactly as good as its tail: nobody notices the eight words that are
    perfect, everybody notices the one still lit three lines later.

    So the numbers that lead are the ones a tail moves:

      mean      the average size of an error, which a handful of disasters
                drags upward -- as it should.
      p90       nine words in ten are at least this good.
      worst30   the mean of the thirty largest errors, i.e. what the file
                looks like where it is worst. On a song with 165 words that
                is the fifth of it that ruins the read.
      early     the share of the near-misses that land AHEAD of the reference.
                Direction, because being early and being late look nothing
                alike to somebody watching, and a symmetric error measure
                cannot tell them apart. Around 50% is unbiased; Clocks came
                back at 70% early with a median of -0.03s, which no
                single-number summary would have shown.

    `median` and `size` stay because earlier reports quote them, not because
    they are the number to judge on.
    """
    if not errs:
        return {}
    med = statistics.median(errs)
    sizes = sorted(abs(e) for e in errs)
    near = [e for e in errs if abs(e) < 1.0]
    worst = sizes[-min(WORST, len(sizes)):]
    return {"n": len(errs),
            "median": round(med, 3),
            # What the errors look like once a CONSTANT displacement is taken
            # off: the model's tracking, as distinct from where the copy sits.
            # Slipknot - Unsainted reads 1.164s mean and 95% lost, and 0.028s
            # here -- it is not mis-heard, it is 1.07s late as a block.
            "tracking": round(statistics.mean([abs(e - med) for e in errs]), 3),
            "size": round(statistics.median(sizes), 3),
            "mean": round(statistics.mean(sizes), 3),
            "p90": round(sizes[min(len(sizes) - 1, int(0.9 * len(sizes)))], 3),
            "worst30": round(statistics.mean(worst), 3),
            "early": round(sum(1 for e in near if e < 0) / max(1, len(near)), 3),
            "hit": sum(1 for e in errs if abs(e) < 0.1) / len(errs),
            "near": sum(1 for e in errs if abs(e) < 0.3) / len(errs),
            "lost": sum(1 for e in errs if abs(e) > 1.0) / len(errs),
            "spread": round(statistics.median([abs(e - med) for e in errs]), 3),
            **shape(errs, at)}


# How far a word has to sit from where its own song sits before it stops being
# a timing error and becomes a mess-up. The same 1.0s `lost` uses, but measured
# against the song's own median rather than against zero, so a displaced copy
# does not report every one of its words as a disaster.
ADRIFT = 1.0
# A run of lost words this long is the thing a listener sees: the highlight
# stops belonging to the song for a bar or more. Below it, a lost word is a
# word; at or above it, the alignment went somewhere else and came back.
BLOCK = 5


def shape(errs: list[float], at: list[int] | None = None) -> dict:
    """WHERE the wrong words are, not how many of them there are.

    `lost` is a share, and a share cannot tell forty scattered near-misses from
    one block of forty consecutive words in the wrong verse. Measured over 255
    songs of the older pipeline, three quarters of lost words sat in runs of
    five or more and half in runs of twenty or more -- so the blocks are almost
    all of it, and a summary that cannot see them is reporting the wrong thing.

    Everything here is measured after the song's own median is taken off. A
    copy that sits a second late is one fact about the copy; this is asking
    what happened to the alignment INSIDE the song.

      runs      how many separate places it went wrong
      longest   the worst of them, in words
      blocks    the share of lost words that are in a run of BLOCK or more
      adrift    the share of words that are lost in this sense at all
      tail      the same share over the last tenth of the song, where the
                older pipeline lost words at nearly four times its own rate

    `at` is each word's index in the song. Given it, a run is broken by a word
    the alphabet could not spell as well as by a word that was placed right --
    without it, two lost words with thirty unspellable ones between them read
    as neighbours.
    """
    if not errs:
        return {"runs": 0, "longest": 0, "blocks": 0.0,
                "adrift": 0.0, "tail": 0.0}
    med = statistics.median(errs)
    bad = [abs(e - med) > ADRIFT for e in errs]
    where = list(at) if at and len(at) == len(errs) else list(range(len(errs)))
    runs, i = [], 0
    while i < len(bad):
        if not bad[i]:
            i += 1
            continue
        j = i + 1
        while j < len(bad) and bad[j] and where[j] == where[j - 1] + 1:
            j += 1
        runs.append(j - i)
        i = j
    lost = sum(runs)
    span = max(where) + 1 if where else 1
    cut = span - max(1, span // 10)
    late = [b for b, w in zip(bad, where) if w >= cut]
    return {"runs": len(runs),
            "longest": max(runs) if runs else 0,
            "blocks": round(sum(r for r in runs if r >= BLOCK)
                            / lost, 3) if lost else 0.0,
            "adrift": round(lost / len(errs), 4),
            "tail": round(sum(late) / len(late), 3) if late else 0.0}


def verdict(row: dict) -> str:
    """clean, locally broken, or displaced -- the count that matters.

    A mean cannot be the headline for "how often does this go wrong": one song
    in the set can carry most of the error and seventeen songs can average to a
    number none of them has. What the person asking wants to know is how many
    files came out with a mess-up in them, so that is counted directly.

    Displaced first, because a displaced copy's words are all far from the
    reference and none of that is the alignment's doing -- `spread` is what
    tells the two apart, exactly as `reading` uses it.
    """
    if row.get("spread", 9.9) <= offset.SPREAD_MAX and abs(row.get("median", 0)) > 0.3:
        return "displaced"
    if abs(row.get("median", 0)) > 1.0:
        return "displaced"
    if row.get("longest", 0) >= BLOCK or row.get("adrift", 0) > 0.02:
        return "locally broken"
    return "clean"


def provenance() -> dict:
    """What is known about where each benchmark copy came from."""
    try:
        return json.loads((AUDIO / "provenance.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def reading(row: dict, given: bool = False) -> str:
    """What this song's numbers are saying, in words.

    The three failures look nothing alike once the spread is in front of you: a
    displaced copy is a large median with a tight spread and is a subtraction
    away from correct; an unstable alignment is scattered everywhere; and a
    recording that is not this song at all loses most of its words entirely.
    Reporting them as one "error" number was how a wrong recording used to hide
    in an average.
    """
    # DISPLACEMENT FIRST. A copy that sits a second from the reference puts
    # every word more than a second out, so `lost` alone reads exactly like a
    # wrong recording -- and the two could not be less alike. What separates
    # them is the SPREAD: a displaced copy is tightly clustered around its own
    # offset (Slipknot: median +1.07s, spread 0.028s, which is the model
    # tracking that song better than most it gets right), while a recording
    # that is not this song scatters.
    if row["spread"] <= offset.SPREAD_MAX and abs(row["median"]) > 0.3:
        return (f"copy displaced {row['median']:+.2f}s "
                f"— the model tracks it to {row.get('tracking', 0):.2f}s")
    if row["lost"] > 0.5 or row["spread"] > 1.0:
        # The same numbers mean two different things, and only provenance can
        # separate them. A copy the search found could be the wrong recording.
        # A copy handed over by the person who timed the lyric is NOT -- so the
        # model is what is failing, and saying "not this recording?" about it
        # would be blaming the audio for the model's deafness. Measured on
        # three such songs: the letters score -5.6 logp where the reference
        # puts them, against about -3.0 on songs that align well.
        return ("the model cannot hear this one" if given
                else "not this recording?")
    if row["spread"] > offset.SPREAD_MAX:
        return "alignment unstable"
    return "ok"


def listen(net, tid: str, meta: dict, device: str, stem: bool, spare: float,
           doc: dict | None = None, log=print,
           gate: float = 0.0, attack: float = 0.0, floor: float = 0.0,
           alpha: float = ctcalign.PRIOR, keep: bool = True,
           sustain: float = 0.0, uncrush: bool = False,
           repace: bool = False, onattack: bool = False,
           mark: str = "", refresh: bool = False):
    """Align one song and hand back (errors, seconds taken), or (None, why).

    `mark` names the checkpoint for the emissions jar. Given one, this listens
    to a song at most once ever: the model's answer and the two signals the
    audio supplies are written to `sync/jar/` and read back on every run after,
    so a sweep over the search costs seconds a song rather than a minute. Pass
    `refresh` to hear it again anyway.
    """
    import local_align as LA
    import torch
    if doc is None:
        doc = dataset.snapshots().get(tid) or {}
    ref = [
        (w["text"], float(w["start"]), float(w["end"]))
        for line in dataset.lines(doc)
        for w in line["words"]
    ]
    if len(ref) < 20:
        return None, "the snapshot has no usable reference for it"
    t0 = time.monotonic()

    # THE JAR FIRST. Nothing below this point depends on the audio except the
    # four arrays it produces, so if they are already on disk for this
    # checkpoint and this copy there is nothing to fetch, separate or run.
    kept = AUDIO / f"{tid}.wav"
    have = kept.stat().st_size if kept.exists() else 0
    held = None if (refresh or not mark) else jar.read(tid, mark, stem, have)
    if held is not None:
        logp, boundary = held["logp"], held["edge"]
        present, onset = held["present"], held["onset"]
        # No offset.trim here, and that is not an omission: the entry was
        # written from audio that had already been trimmed, so its lag is
        # baked into the frames. It is kept in the entry's meta only so a
        # reader can see which copy this was.
        return _place(logp, boundary, present, onset, ref, doc, device, t0,
                      gate=gate, attack=attack, floor=floor, alpha=alpha,
                      sustain=sustain, uncrush=uncrush, repace=repace,
                      onattack=onattack, log=log)

    with _copy(tid, meta, keep=keep) as path:
        if not path:
            return None, f"no copy could be fetched — {LA.fetched.last_error[:50]}"
        wave, rate = audio.read(path)
        mono = audio.mono16k(wave, rate)
        lag, why = offset.trim(mono, float(meta.get("length") or 0))
        if why:
            log(f"      {why}")
        if lag:
            mono = mono[int(lag * audio.RATE):]
        if stem:
            dev, win, _ = LA.room("gpu", LA.DEMUCS_COST, LA.DEMUCS_WINDOW, spare)
            # A BENCHMARK MUST NOT DEPEND ON WHAT ELSE THE CARD IS DOING.
            # room() sizes the separation window from free VRAM, demucs over a
            # different window produces a different vocal, and a discrete
            # search can flip a borderline song on that. Measured the hard way:
            # the same configuration scored 0.327s with the card idle and
            # 0.356s while a training run held 2.8 GB of it. So the window is
            # reported, and a run that had to shrink it is not comparable to
            # one that did not.
            if win < LA.DEMUCS_WINDOW[1] - 1e-6:
                log(f"      NOT COMPARABLE: separated at a {win:.1f}s window "
                    f"instead of {LA.DEMUCS_WINDOW[1]:.1f}s — something else "
                    f"is using the card")
            sep, srate = LA.separate(wave, rate, dev, win, LA.MODEL, None, None)
            mono = audio.mono16k(sep, srate)
            if lag:
                mono = mono[int(lag * audio.RATE):]
            LA.release()
        logp, boundary = M.emit(net, mono, device, return_boundary=True)
        if not getattr(net, "has_boundary", True):
            boundary = None
    # The audio's own account of where the singing is. Measured from whatever
    # the model was given -- so in stem mode, from the separated vocal, where
    # a quiet frame means nobody is singing rather than nobody is loud.
    #
    # BOTH are measured now, whatever gate and attack are set to. They cost a
    # spectrogram between them, and computing them only when the current
    # settings ask for them would put a jar entry on disk that cannot answer
    # the next question -- which is precisely the question the jar is for.
    from . import vocal
    present = vocal.activity(mono, logp.shape[0])
    onset = vocal.onsets(mono, logp.shape[0])
    if mark:
        jar.write(tid, mark, stem, logp=logp, edge=boundary,
                  present=present, onset=onset, lag=round(float(lag), 4),
                  bytes=(kept.stat().st_size if kept.exists() else 0),
                  secs=round(mono.shape[-1] / audio.RATE, 2))
    return _place(logp, boundary, present, onset, ref, doc, device, t0,
                  gate=gate, attack=attack, floor=floor, alpha=alpha,
                  sustain=sustain, uncrush=uncrush, repace=repace,
                  onattack=onattack, log=log)


def _place(logp, boundary, present, onset, ref, doc, device, t0,
           gate: float = 0.0, attack: float = 0.0, floor: float = 0.0,
           alpha: float = ctcalign.PRIOR, sustain: float = 0.0,
           uncrush: bool = False, repace: bool = False,
           onattack: bool = False, log=print):
    """Everything after the listening: the search, and what it came to.

    Split out so that a jar hit and a fresh run go through the SAME code. The
    alternative -- a second copy of the search for the cached path -- is how a
    sweep ends up measuring two slightly different aligners and calling the
    difference a result.
    """
    got = ctcalign.words(logp, [w for w, _s, _e in ref], device,
                         boundary=boundary,
                         present=present if gate > 0 else None, gate=gate,
                         onset=onset if attack > 0 else None, attack=attack,
                         floor=floor, alpha=alpha, sustain=sustain)
    # THE SECOND PASS, measured here for the first time.
    #
    # _uncrush lives in the generator and has only ever been looked at, never
    # scored: it re-solves a squeezed line together with the line before it,
    # because a crushed line is not crushed on its own account. The rows it
    # wants are line-shaped, and the reference is already line-shaped -- the
    # flat word list above is those lines end to end, in order -- so the
    # alignment slices straight back into lines with no second matching step.
    if uncrush or repace or onattack:
        from . import generate
        # BY INDEX, NOT BY POSITION. ctcalign.words keys every row with the
        # word it came from and leaves out the ones it could not place -- 12%
        # of them on this set -- so the alignment is NOT parallel to the
        # reference list. Slicing it positionally silently walks the line
        # boundaries off by one dropped word each time, which is a fault that
        # looks exactly like a bad second pass: it moved Toxicity 0.061 ->
        # 0.098 and lost three words, and none of that was _uncrush.
        placed = {r["i"]: r for r in got}
        rows, at = [], 0
        for line in dataset.lines(doc):
            said = [w["text"] for w in line["words"]]
            rows.append({"role": "Lead", "at": 0, "words": said,
                         "timed": [placed.get(at + k)
                                   or {"word": w, "start": None, "end": None,
                                       "score": 0.0, "chars": []}
                                   for k, w in enumerate(said)]})
            at += len(said)
        if uncrush:
            moved = generate._uncrush(rows, logp, device, boundary=boundary,
                                      present=present if gate > 0 else None,
                                      onset=onset if attack > 0 else None,
                                      gate=gate, attack=attack, log=None)
            if moved:
                log(f"      re-solved {moved} crushed line(s)")
        if repace:
            moved = generate._repace(rows, logp, device, boundary=boundary,
                                     present=present if gate > 0 else None,
                                     onset=onset if attack > 0 else None,
                                     gate=gate, attack=attack, log=None)
            if moved:
                log(f"      started {moved} over-long line(s) again")
        if onattack:
            moved = generate._onattack(rows, logp, device, boundary=boundary,
                                       present=present if gate > 0 else None,
                                       onset=onset if attack > 0 else None,
                                       gate=gate, attack=attack, log=None)
            if moved:
                log(f"      moved {moved} line(s) onto a stronger attack")
        # Unplaced words go back out of the list, so that with nothing to
        # re-solve this returns exactly what the first pass returned.
        got = [w for r in rows for w in r["timed"] if w.get("start") is not None]

    # How sure the model was, kept rather than dropped. This is the number the
    # generator's auto-separation decides on, and it has never been measured
    # against songs whose error is known -- so it is carried out of here now,
    # alongside the errors, and the two can finally be compared.
    import statistics as _st
    said = [w["score"] for w in got if w.get("score")]
    sure = round(float(_st.median(said)), 4) if said else 0.0
    # ON THE FUNCTION, NOT IN THE TUPLE. listen() answers with four values when
    # it worked and two when it did not, and unpacking that wrongly is a fault
    # this file has already had twice -- it measured no offsets at all for as
    # long as it stood. Adding a fifth value would be inviting the third. The
    # house does this elsewhere for the same reason: LA.fetched.last_error,
    # _snap.before, _anchored.why.
    listen.detail = _detail(got, ref, len(ref))
    return (_errors(got, ref), _end_errors(got, ref),
            time.monotonic() - t0, sure)


WORDS = HOME / "bench-words"
SCORES = HOME / "scores.json"


def _ckpt_key(path) -> str:
    """The name the player already knows a checkpoint by.

    Deliberately the same string `lyrics_gui.ckpt_facts` keys its cache on --
    name, whole-second mtime and size -- so the measured score and the facts
    read out of the file itself line up without either side having to know how
    the other spells it.
    """
    path = pathlib.Path(path)
    st = path.stat()
    return f"{path.name}:{int(st.st_mtime)}:{st.st_size}"


def _measured(ckpt, summary: dict, stem: bool, by: str) -> None:
    """Write what this run found, where the thing that CHOOSES a model can see it.

    "bench decides and the loss does not" is this project's own rule, and it was
    true of everything except the one decision that matters -- which checkpoint
    the player picks up. That went on step count, and a continuation trained for
    1500 steps on five songs with no held-out set therefore outranked the model
    it was continued from and aligned the mixture twice as badly.

    A score per INPUT, not one per checkpoint: a model reads a separated vocal
    and a mixture very differently, and a number taken on one says nothing about
    the other.
    """
    try:
        got = json.loads(SCORES.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        got = {}
    # KEYED BY THE SET AS WELL AS THE INPUT. A mean over the 17 gold songs and
    # a mean over all 43 held-out ones are different questions, and ranking two
    # checkpoints on one each is how a model measured on the easier half wins.
    # This file exists to stop exactly that, so it may not commit it itself.
    row = got.setdefault(_ckpt_key(ckpt), {})
    row[f"{'stem' if stem else 'mix'}:{summary.get('how', {}).get('set', 'hash')}"] = {
        "mean": summary.get("mean"), "clean": summary.get("clean"),
        "local": summary.get("local"), "songs": summary.get("songs"),
        "adrift": summary.get("adrift"), "by": by or "",
        "step": summary.get("step"),
        "at": time.strftime("%Y-%m-%d"),
    }
    tmp = SCORES.with_suffix(".json.part")
    tmp.write_text(json.dumps(got, indent=1), encoding="utf-8")
    tmp.replace(SCORES)


def _remember(tid: str, name: str, detail: list[dict], **how) -> None:
    """One file per song, holding every paired word.

    Beside bench.json rather than inside it: that file is meant to be read by a
    person and a few thousand floats a song is not reading matter. The comment
    that put them there in the first place was right about why they were needed
    and wrong about where they should live.
    """
    WORDS.mkdir(parents=True, exist_ok=True)
    # THE CONFIGURATION IS IN THE NAME. Keyed on the track alone, a separated
    # run silently overwrote the mixture run it was being compared against --
    # and the comparison then read as one set of numbers with no sign that it
    # was two.
    tag = "stem" if how.get("stem") else "mix"
    for flag in ("uncrush", "repace", "onattack"):
        if how.get(flag):
            tag += f"-{flag}"
    if how.get("mark"):
        tag += f".{how['mark']}"
    (WORDS / f"{tid}.{tag}.json").write_text(
        json.dumps({"tid": tid, "name": name, "how": how, "tag": tag,
                    "at": [d["at"] for d in detail],
                    "err": [d["err"] for d in detail],
                    "end_err": [d["end_err"] for d in detail],
                    "score": [d["score"] for d in detail],
                    "of": detail[0]["of"] if detail else 0}),
        encoding="utf-8")


@contextlib.contextmanager
def _copy(tid: str, meta: dict, keep: bool = True):
    """This song's copy — pinned here for good when `keep`, borrowed when not.

    PINNING IS FOR THE BENCHMARK AND NOTHING ELSE. These copies sit outside the
    fetcher's 8 GB LRU precisely so a benchmark song cannot be evicted and
    silently replaced by a different upload -- one such swap moved a song's
    error from 0.190s to 1.386s between runs, with nothing in the code changed.
    That is worth a couple of gigabytes for seventeen songs.

    It is NOT worth it for every song in the library. `offsets` measures 572 of
    them through this same function, and pinning them all took this directory
    from 2.0 GB to 9.7 GB on the way to about 14 GB, which would have filled
    the disk and stopped the run it was part of. Anything that is not a
    benchmark song borrows a copy from the LRU cache like everything else.
    """
    import local_align as LA
    import shutil
    kept = AUDIO / f"{tid}.wav"
    if kept.exists() and kept.stat().st_size > 1024:
        yield str(kept)
        return
    with LA.fetched(f"{meta['artist']} {meta['title']}",
                    float(meta.get("length") or 0), artist=meta.get("artist", ""),
                    tid=tid) as path:
        if path and keep:
            with contextlib.suppress(Exception):
                AUDIO.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, kept)
        yield path


def run(ckpt=None, songs: int = 12, device: str = "cuda", stem: bool = False,
        gate: float = 0.0, attack: float = 0.0, floor: float = 0.0,
        alpha: float = ctcalign.PRIOR, sustain: float = 0.0,
        spare: float = 0.4, calibrate: bool = False, names: list[str] | None = None,
        root=data.DATA, report: bool = True, by: str = "",
        uncrush: bool = False, repace: bool = False,
        onattack: bool = False, refresh: bool = False,
        all_held: bool = False) -> int:
    import torch
    ckpt = pathlib.Path(ckpt or (HOME / "syncnet.pt")).expanduser()
    if not ckpt.exists():
        raise SystemExit(f"no model at {ckpt} -- train one first")
    device = device if torch.cuda.is_available() else "cpu"
    net, rest = M.load(ckpt, device)
    mark = jar.stamp(ckpt)
    hold = float(rest.get("hold") or 0.08)
    step = rest.get("step", "?")
    tracks = dataset._tracks()
    # SNAP only: the benchmark never sees a lyric the model may have trained
    # on. Training reads both spl and aml; measuring reads the community ones.
    have = dataset.snapshots(dataset.SNAP)
    if not have:
        raise SystemExit("nothing in the snapshot -- run `sync snapshot` first")
    gold_held = None
    gold_names = frozenset()
    # EVERY SONG THE MODEL WAS HELD OUT FROM, by either rule, in one report.
    # The two hold-out rules answer different questions -- one hand throughout
    # for `--by`, and a name hash for everything else -- and measuring them
    # separately means neither report has enough songs to tell a real change
    # from a fresh run. Measured over 43 songs, the community references turn
    # out to be exactly as tight as the hand-timed ones (|median| 0.043s and
    # spread 0.043s on both), so there is no reason to keep them apart.
    if all_held:
        whose = dataset.by_hand(by or "gc", have)
        gold_names = data.gold_split(
            {dataset.name_of(t, tracks) for t in whose},
            float(rest.get("gold_hold") or data.GOLD_HOLD)) if whose else frozenset()
    elif by:
        # Measured against one person's own timings only. The mixed set's
        # references disagree with each other by more than the model's typical
        # error, so a number taken across all of them cannot see below about
        # 0.10s. One hand throughout is what makes 50ms a meaningful question.
        have = dataset.by_hand(by, have)
        if not have:
            raise SystemExit(f"no snapshotted lyric is credited to {by!r}")
        # The SAME split the trainer held back, not a second one that happens
        # to look similar. Two independent hold-out rules is how a song ends up
        # trained on and measured on at once.
        gold_held = data.gold_split(
            {dataset.name_of(t, tracks) for t in have},
            float(rest.get("gold_hold") or data.GOLD_HOLD))
        gold_names = frozenset()

    # Only songs the model was never trained on. A song absent from the
    # dataset is unseen too, but the held split is what the trainer measured
    # itself on, so it is what makes two runs comparable.
    want = []
    for tid in have:
        if tid not in tracks:
            continue
        name = dataset.name_of(tid, tracks)
        if names:
            if not any(n.lower() in name.lower() for n in names):
                continue
        elif all_held:
            if name not in gold_names and not data.held(name, hold):
                continue
        elif gold_held is not None:
            if name not in gold_held:
                continue
        elif not data.held(name, hold):
            continue
        want.append((tid, name))
    want.sort(key=lambda x: x[1])
    # How many there WERE, before --songs cut the list. Two runs over different
    # subsets of the held-out set are not comparable, and with --songs
    # defaulting to 12 against a 17-song gold set that is the ordinary case
    # rather than the exotic one. The report says so rather than leaving the
    # reader to notice.
    offered = len(want)
    want = want[:songs] if songs else want
    if not want:
        raise SystemExit("no held-out song has both a lyric and a track entry")

    given = provenance()
    print(f"{ckpt.name} at step {step}, {net.size()}; "
          f"measuring {len(want)} song(s) it has never seen")
    rows, skipped = [], []
    for tid, name in want:
        listen.detail = []
        result = listen(net, tid, tracks[tid], device, stem, spare,
                        doc=have.get(tid), gate=gate, attack=attack,
                        floor=floor, alpha=alpha, sustain=sustain,
                        uncrush=uncrush, repace=repace,
                        onattack=onattack, mark=mark, refresh=refresh)
        if result[0] is None:
            _, why = result
            print(f"  {name[:52]:52} skipped — {why}")
            skipped.append((name, why))
            continue
        errs, end_errs, took, sure = result
        detail = list(getattr(listen, "detail", []) or [])
        at = [d["at"] for d in detail] if len(detail) == len(errs) else None
        got = score(errs, at)
        # The raw errors are kept, not just their summary: every pooled figure
        # below needs them, and by the time `rows` is built they used to be
        # gone. They are floats, a few thousand per song -- nothing.
        pooled = list(errs)
        end = score(end_errs, at)
        # EVERY WORD, KEPT. The summary is what a person reads; this is what a
        # question is asked of afterwards -- where the lost words were, whether
        # the model's own confidence knew, what a different search would have
        # done with the same song. None of that could be asked before, because
        # by the time bench.json was written the words were gone.
        if detail:
            _remember(tid, name, detail, sure=sure, step=step,
                      ckpt=ckpt.name, mark=mark, stem=stem, gate=gate,
                      attack=attack, sustain=sustain, floor=floor, alpha=alpha)
        if not got:
            skipped.append((name, "no words paired"))
            continue
        got.update(errs=pooled, sure=sure, name=name, tid=tid,
                   secs=round(took, 1),
                   end_median=end.get("median", 0.0),
                   end_size=end.get("size", 0.0),
                   end_near=end.get("near", 0.0),
                   end_lost=end.get("lost", 0.0),
                   end_spread=end.get("spread", 0.0))
        got["given"] = (given.get(tid) or {}).get("how") == "given"
        got["reading"] = reading(got, got["given"])
        got["verdict"] = verdict(got)
        rows.append(got)
        print(f"  {name[:52]:52} {got['n']:4}w  mean {got['mean']:6.3f}  "
              f"p90 {got['p90']:6.3f}  worst30 {got['worst30']:6.2f}  "
              f"adrift {got['adrift']*100:3.0f}%  run {got['longest']:3}  "
              f"{got['verdict']:14} {got['reading']}")

    if not rows:
        raise SystemExit("nothing could be measured")

    # PER SONG or PER WORD, and the two disagree enough to matter.
    #
    # Averaging per-song values lets a 165-word song that broke count as much
    # as a 780-word song that did not. Measured on the stem model: the
    # per-song mean says 10.4% of words are lost, weighting by words says
    # 9.2%, and one song -- whose copy has no measured offset -- is 61% of
    # them. Both are reported. The per-song figures stay first and keep their
    # names so that every report written before this still means what it said.
    every = [e for r in rows for e in r.get("errs", [])]
    sizes = sorted(abs(e) for e in every)
    total = max(1, len(every))

    def by_word(field):
        """That per-song share, weighted by how many words it was a share of."""
        return round(sum(r[field] * r["n"] for r in rows) / max(1, sum(
            r["n"] for r in rows)), 3)

    worst = sizes[-min(WORST, len(sizes)):] if sizes else [0.0]
    near = [e for e in every if abs(e) < 1.0]
    pooled = {
        "mean": round(statistics.mean(sizes), 3) if sizes else 0.0,
        "p90": round(sizes[min(len(sizes) - 1, int(0.9 * len(sizes)))], 3)
               if sizes else 0.0,
        "worst30": round(statistics.mean(worst), 3),
        "median": round(statistics.median(sizes), 3) if sizes else 0.0,
        # by_word works for a weighted MEAN as well as a share.
        "tracking": by_word("tracking"),
        "near": by_word("near"),
        "lost": by_word("lost"),
        "hit": by_word("hit"),
        "early": round(sum(1 for e in near if e < 0) / max(1, len(near)), 3),
    }
    summary = {
        "songs": len(rows),
        "by_word": pooled,
        "words": sum(r["n"] for r in rows),
        "median": round(statistics.median([r["median"] for r in rows]), 3),
        "size": round(statistics.median([r["size"] for r in rows]), 3),
        "early": round(statistics.mean([r["early"] for r in rows]), 3),
        "worst30": round(statistics.mean([r["worst30"] for r in rows]), 3),
        "p90": round(statistics.mean([r["p90"] for r in rows]), 3),
        "mean": round(statistics.mean([r["mean"] for r in rows]), 3),
        "near": round(statistics.mean([r["near"] for r in rows]), 3),
        "lost": round(statistics.mean([r["lost"] for r in rows]), 3),
        "spread": round(statistics.median([r["spread"] for r in rows]), 3),
        "end_size": round(statistics.median([r["end_size"] for r in rows]), 3),
        "end_near": round(statistics.mean([r["end_near"] for r in rows]), 3),
        "end_lost": round(statistics.mean([r["end_lost"] for r in rows]), 3),
        "end_spread": round(statistics.median([r["end_spread"] for r in rows]), 3),
        # A song counts as usable on its MEAN, not its median: half a file
        # being right is not a usable file.
        "usable": sum(1 for r in rows if r["mean"] < 0.3),
        "good": sum(1 for r in rows if r["size"] < 0.3),
        "broken": sum(1 for r in rows if r["size"] > 1.0),
        "doubted": sum(1 for r in rows if r.get("reading") == "not this recording?"),
        # THE HEADLINE THIS FILE EXISTS FOR. Not a mean -- how many files came
        # out with a mess-up in them. `clean` is what the person asking wants
        # to go up; `local` is the alignment going somewhere else and coming
        # back, and is the one a better search could move; `displaced` is the
        # copy, and no search will touch it.
        "clean": sum(1 for r in rows if r.get("verdict") == "clean"),
        "local": sum(1 for r in rows if r.get("verdict") == "locally broken"),
        "displaced": sum(1 for r in rows if r.get("verdict") == "displaced"),
        "longest": max((r.get("longest", 0) for r in rows), default=0),
        "adrift": by_word("adrift"),
        "blocks": round(sum(r.get("blocks", 0) * r.get("adrift", 0) * r["n"]
                            for r in rows)
                        / max(1e-9, sum(r.get("adrift", 0) * r["n"]
                                        for r in rows)), 3),
        "tail": round(statistics.mean([r.get("tail", 0) for r in rows]), 3),
        "step": step,
        # What produced these numbers. The defaults for gate, attack and
        # sustain used to differ between this benchmark and the generator that
        # ships, and no report said which it had been given -- so two reports
        # could disagree about the model while agreeing about everything except
        # the one thing that was different.
        "how": {"stem": bool(stem), "gate": gate, "attack": attack,
                "sustain": sustain, "floor": floor, "alpha": alpha,
                "uncrush": bool(uncrush), "repace": bool(repace),
                "onattack": bool(onattack), "by": by or "", "ckpt": ckpt.name,
                "set": "all-held" if all_held else ("gold" if by else "hash"),
                "offered": offered},
    }
    # Led by the numbers a tail can move. The median is last and in brackets,
    # because it is the one that called an unusable file excellent.
    print(f"\n{summary['songs']} songs, {summary['words']} words | "
          f"mean {summary['mean']:.3f}s | p90 {summary['p90']:.3f}s | "
          f"worst-30 {summary['worst30']:.2f}s | lost {summary['lost']*100:.0f}% | "
          f"early {summary['early']*100:.0f}% | "
          f"usable (mean<0.3s) {summary['usable']}/{summary['songs']} | "
          f"(median {summary['size']:.3f}s)")
    print(f"{'':>{len(str(summary['songs']))}}   MESS-UPS | "
          f"clean {summary['clean']}/{summary['songs']} | "
          f"locally broken {summary['local']} | "
          f"displaced {summary['displaced']} | "
          f"adrift {summary['adrift']*100:.1f}% of words, "
          f"{summary['blocks']*100:.0f}% of those in runs of {BLOCK}+ | "
          f"longest run {summary['longest']}w | "
          f"last tenth {summary['tail']*100:.1f}%")
    print(f"{'':>{len(str(summary['songs']))}}   per word | "
          f"mean {pooled['mean']:.3f}s | p90 {pooled['p90']:.3f}s | "
          f"worst-30 {pooled['worst30']:.2f}s | lost {pooled['lost']*100:.0f}% | "
          f"early {pooled['early']*100:.0f}% | "
          f"within 0.3s {pooled['near']*100:.0f}% | "
          f"tracking {pooled['tracking']:.3f}s")


    if calibrate:
        # The model's own standing bias, not any song's displacement: the
        # median of the SONG medians, over songs whose errors are tight enough
        # that their median means something. CTC puts a symbol where it is
        # most sure of it, which is a little after the sound starts, and that
        # much is the same on every song -- so it is worth subtracting once
        # here rather than being paid on every word forever.
        tight = [r["median"] for r in rows if r["spread"] <= offset.SPREAD_MAX]
        if len(tight) < 4:
            print("  not calibrating: too few songs aligned tightly enough")
        else:
            bias = round(statistics.median(tight), 3)
            M.save(ckpt, net, calibration=bias, **{
                k: v for k, v in rest.items()
                if k not in ("config", "alphabet", "frame", "calibration")})
            print(f"  calibration set to {bias:+.3f}s (from {len(tight)} tight "
                  f"song(s)) -- new files will have it taken off")

    # Written whether or not a report is, because this is not a report: it is
    # the fact the player consults when it decides which model to load.
    try:
        _measured(ckpt, summary, stem, by)
    except Exception as why:                                # noqa: BLE001
        print(f"  could not record the score: {why}")

    if report:
        REPORTS.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M")
        path = REPORTS / f"bench-{stamp}.md"
        path.write_text(_markdown(summary, rows, skipped, ckpt), encoding="utf-8")
        (HOME / "bench.json").write_text(
            json.dumps({"summary": summary,
                        # without the per-word errors: they are needed to
                        # compute the pooled figures and are noise in a file
                        # meant to be read.
                        "songs": [{k: v for k, v in r.items() if k != "errs"}
                                  for r in rows]}, indent=1),
            encoding="utf-8")
        print(f"  written to {path}")
    return 0


def _markdown(summary: dict, rows: list[dict], skipped, ckpt) -> str:
    out = [f"# sync bench — {time.strftime('%Y-%m-%d %H:%M')}", "",
           f"`{ckpt}` at step {summary['step']}, "
           f"{summary['songs']} held-out songs"
           + (f" of {summary['how']['offered']} available"
              if summary.get("how", {}).get("offered", 0) > summary["songs"]
              else "")
           + f", {summary['words']} words.", "",
           f"- word STARTS: mean error **{summary['mean']:.3f}s**, "
           f"p90 **{summary['p90']:.3f}s**, worst-30 **{summary['worst30']:.2f}s**, "
           f"lost **{summary['lost']*100:.1f}%**, "
           f"early **{summary['early']*100:.0f}%** "
           f"(median {summary['size']:.3f}s, within 0.3s {summary['near']*100:.0f}%)",
           f"- the same PER WORD, so a short broken song cannot outvote a "
           f"long clean one: mean **{summary['by_word']['mean']:.3f}s**, "
           f"p90 **{summary['by_word']['p90']:.3f}s**, "
           f"worst-30 **{summary['by_word']['worst30']:.2f}s**, "
           f"lost **{summary['by_word']['lost']*100:.1f}%**, "
           f"early **{summary['by_word']['early']*100:.0f}%**",
           f"- word ENDS: typical error **{summary['end_size']:.3f}s**, "
           f"within 0.3s **{summary['end_near']*100:.0f}%**, "
           f"lost **{summary['end_lost']*100:.1f}%**",
           f"- they run **{summary['median']:+.3f}s** "
           f"{'late' if summary['median'] > 0 else 'early'}, "
           f"spread **{summary['spread']:.3f}s**",
           f"- **{summary['usable']} of {summary['songs']} songs usable** "
           f"(mean error under 0.3s); {summary['broken']} broken (>1s). "
           f"By median alone {summary['good']} would look good, which is the "
           f"gap this table exists to show.",
           f"- **MESS-UPS: {summary['clean']} of {summary['songs']} songs "
           f"came out clean**, {summary['local']} locally broken, "
           f"{summary['displaced']} displaced. "
           f"{summary['adrift']*100:.1f}% of words sit more than "
           f"{ADRIFT:.0f}s from where their own song sits, "
           f"{summary['blocks']*100:.0f}% of those inside a run of "
           f"{BLOCK} or more; the longest run was "
           f"{summary['longest']} words. Over the last tenth of a song the "
           f"rate is {summary['tail']*100:.1f}%.",
           f"- measured with " + ", ".join(
               f"`{k}={v}`" for k, v in summary.get("how", {}).items()
               if k not in ("ckpt", "by") and v not in (False, 0, 0.0))
           + (f", `by={summary['how']['by']}`"
              if summary.get("how", {}).get("by") else "")
           + ". Anything not listed was off.", "",
           "| song | words | mean | p90 | worst-30 | adrift | runs | "
           "longest | median | sure | verdict | reading |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["mean"]):
        out.append(f"| {r['name']} | {r['n']} | {r['mean']:.3f} | "
                   f"{r['p90']:.3f} | {r['worst30']:.2f} | "
                   f"{r.get('adrift', 0)*100:.1f}% | {r.get('runs', 0)} | "
                   f"{r.get('longest', 0)} | "
                   f"{r['size']:.3f} | {r.get('sure', 0):.2f} | "
                   f"{r.get('verdict', '')} | {r.get('reading', '')} |")

    if skipped:
        out += ["", "## not measured", ""]
        out += [f"- {name} — {why}" for name, why in skipped]
    out += ["", "The references were typed by people against a master and "
            "carry their own error at 0.05-0.10s. A song inside that is as "
            "good as this measurement can tell."]
    return "\n".join(out) + "\n"


def offsets(ckpt=None, device: str = "cuda", stem: bool = False,
            spare: float = 0.4, songs: int = 0, root=data.DATA) -> int:
    """Measure where every copy sits against its lyric, and write it down.

    This is the feedback loop the dataset needs. The clips are cut on somebody
    else's timings against a copy fetched from somewhere else, and about a
    quarter of copies are displaced. After this has run, `sync dataset` cuts
    those songs where the singing actually is -- and only those songs, because
    a measurement whose errors are scattered is not a displacement and is
    written down as not trusted.
    """
    import torch
    ckpt = pathlib.Path(ckpt or (HOME / "syncnet.pt")).expanduser()
    if not ckpt.exists():
        raise SystemExit(f"no model at {ckpt} -- train one first")
    device = device if torch.cuda.is_available() else "cpu"
    net, _rest = M.load(ckpt, device)
    tracks = dataset._tracks()
    have = dataset.snapshots()
    rows = offset.load()
    todo = [(t, dataset.name_of(t, tracks)) for t in have if t in tracks]
    todo.sort(key=lambda x: x[1])
    if songs:
        todo = [x for x in todo if x[1] not in rows][:songs]
    print(f"measuring {len(todo)} song(s) against their own lyrics")
    moved = 0
    for tid, name in todo:
        meta = tracks[tid]
        full = f"{meta['artist']} - {meta['title']}"
        # THREE values: listen() has returned (starts, ends, seconds) since
        # word ends were added, and unpacking two raised ValueError on the
        # first song of every run -- which is to say this command measured
        # nothing at all for as long as that mismatch stood. Slipknot's
        # missing offset, and the flat 1.07s shift the benchmark read as a
        # wrong recording, were this line.
        # listen() answers with FOUR values when it worked and TWO when it did
        # not, so the shape has to be checked before it is unpacked. Unpacking
        # four unconditionally is what broke this command a second time -- the
        # first was unpacking two after a third was added.
        result = listen(net, tid, meta, device, stem, spare,
                        doc=have.get(tid), log=lambda m: None, keep=False)
        if result[0] is None:
            _none, why = result
            print(f"  {name[:52]:52} not measured — {why}")
            continue
        errs, _ends, took, _sure = result
        if len(errs) < offset.PAIRS_MIN:
            print(f"  {name[:52]:52} not measured — "
                  f"{len(errs)} words paired")
            continue
        got = offset.summarise(errs)
        rows[full] = dict(got, at=time.strftime("%Y-%m-%d"))
        if got["trusted"] and abs(got["lag"]) >= offset.LEAST:
            moved += 1
        print(f"  {name[:52]:52} {got['lag']:+.3f}s  "
              f"spread {got['spread']:.3f}  {got['why']}")
        offset.save(rows)
    print(f"{moved} song(s) have a displacement worth cutting at; "
          f"written to {offset.STORE}")
    return 0
