"""Cutting singing into clips the model can be taught from, and keeping the
lyrics they were cut on.

    python -m sync.sync snapshot            keep every spl lyric on disk
    python -m sync.sync dataset --songs 50  cut more clips

Two commands because they fail differently. The snapshot needs a running
Spotify and a minute; the cutting needs the network, a GPU and an hour, and it
is resumable precisely because it will be interrupted.

Everything here is spl only -- the documents people uploaded to Spicy Lyrics.
The same cache holds Apple Music's word-synced lyrics under `aml`, and the two
were mixed together in this project once already: 149 of 376 documents were
Apple's, and nothing told them apart until somebody counted. `source` is
checked, and `TTMLUploadMetadata` is checked with it, because a single field is
a single point of quiet failure.

The clips are cut a little wider than the line they hold. A reference marks
where a word STARTS and the last word of a line has to finish somewhere; and a
copy displaced from the master by a fifth of a second would otherwise have that
fifth of a second of singing cut off the front of every clip in it, which is
the one thing CTC cannot forgive.

SEPARATION IS OFF BY DEFAULT. The model reads the song as it was mixed. A
separated vocal is cleaner but it is also invented: demucs leaves smearing and
phantom onsets exactly where a quiet consonant sits under a cymbal, and a
timing model taught on those artefacts learns to time the artefact. Pass
--stem to turn separation back on; if you do, everything downstream has to be
stem too, because a model trained on one and run on the other is a domain
mismatch and will read as "the timings got worse".
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
import time

from . import audio, offset, text

ALIGNER = pathlib.Path(__file__).resolve().parent.parent / "aligner"
sys.path.insert(0, str(ALIGNER))

HOME = pathlib.Path.home() / ".cache/mild-lyrics/sync"
SNAP = HOME / "spl"
# Apple Music's own word-synced lyrics, kept SEPARATELY and on purpose.
#
# They are wanted for training -- of the sources in this cache only spl and aml
# time syllables well enough to learn from, and aml roughly doubles what there
# is. They are not wanted for measuring: a model trained on a lyric cannot be
# scored against it, and one directory that both stages read is one edit away
# from that happening silently. So the split is structural rather than a flag.
# `snapshots()` is what training reads and covers both; `snapshots(SNAP)` is
# what the benchmark reads and covers only the community ones.
APPLE = HOME / "aml"
DATA = HOME / "dataset"

MIN_CLIP = 0.6
MAX_CLIP = 12.0
# A grouped clip holds several consecutive lines. Two limits, both real: the
# trainer refuses a clip longer than 12s, and two lines with a long instrumental
# between them are not context, they are one line with a hole after it.
GROUP_MAX = 11.0
GROUP_GAP = 4.0
PAD = 0.25
COMMUNITY = "spl"

JS_TRACK = """(async () => {
  try {
    const r = await Spicetify.GraphQL.Request(
      Spicetify.GraphQL.Definitions.getTrack, {uri: %s});
    const t = ((r.data || {}).trackUnion) || {};
    if (!t.name) return null;
    const a = [...(((t.firstArtist || {}).items) || []),
               ...(((t.otherArtists || {}).items) || [])];
    return {title: t.name,
            length: (((t.duration || {}).totalMilliseconds) || 0) / 1000,
            artist: a.map(x => ((x.profile) || {}).name).filter(Boolean).join(", ")};
  } catch (e) { return null; }
})()"""


def _cdp():
    from spotify_dom import connect
    got = connect(9222, "spotify")
    if got is None:
        raise SystemExit("Spotify is not reachable on port 9222 -- start it "
                         "with Spicetify and try again")
    return got


def community(doc: dict) -> bool:
    """Did a person upload this lyric, rather than Apple Music?

    Two independent answers have to agree. They did agree, 227 to 227, the last
    time this was counted -- which is the reason to keep asking both.
    """
    if not isinstance(doc, dict):
        return False
    if str(doc.get("source") or "") != COMMUNITY:
        return False
    meta = doc.get("TTMLUploadMetadata")
    return meta is None or isinstance(meta, dict)


def lines(doc: dict) -> list[dict]:
    """Timed lead lines, retaining each word's source start/end."""
    import lyric_sources as LS
    out = []
    for item in LS._items(doc):
        lead = item.get("Lead")
        if not isinstance(lead, dict):
            continue
        syls = lead.get("Syllables") or []
        if not syls:
            continue

        words = []
        word = ""
        word_start = None
        word_end = None
        for syl in syls:
            text_s = str(syl.get("Text") or "")
            st = syl.get("StartTime")
            en = syl.get("EndTime")
            if word_start is None and isinstance(st, (int, float)):
                word_start = float(st)
            if isinstance(en, (int, float)):
                word_end = float(en)
            word += text_s
            if not syl.get("IsPartOfWord"):
                if (word.strip() and isinstance(word_start, float)
                        and isinstance(word_end, float)):
                    words.append({
                        "text": word.strip(),
                        "start": word_start,
                        "end": word_end,
                    })
                word = ""
                word_start = word_end = None

        if word.strip() and isinstance(word_start, float) and isinstance(word_end, float):
            words.append({"text": word.strip(), "start": word_start, "end": word_end})

        if words:
            out.append({
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": " ".join(w["text"] for w in words),
                "words": words,
            })
    return out


def reference(doc: dict) -> list[tuple[str, float]]:
    """[(word, start)] for a document -- what a measurement is made against.

    Syllables are glued back into words: whoever timed the lyric and whoever
    wrote this model do not divide words the same way, and the word is the
    largest unit both of them agree exists.
    """
    import lyric_sources as LS
    out = []
    for item in LS._items(doc):
        lead = item.get("Lead")
        if not isinstance(lead, dict):
            continue
        word, at = "", None
        for syl in lead.get("Syllables") or []:
            if at is None:
                at = syl.get("StartTime")
            word += str(syl.get("Text") or "")
            if not syl.get("IsPartOfWord"):
                if word.strip() and isinstance(at, (int, float)):
                    out.append((word.strip(), float(at)))
                word, at = "", None
        if word.strip() and isinstance(at, (int, float)):
            out.append((word.strip(), float(at)))
    return out


def snapshot(limit: int = 0, apple: bool = False) -> int:
    """Keep every spl lyric in the player's cache on disk, with its track.

    After this, training, measuring and generating all work with Spotify shut.
    It is also the only record of what a document said on the day a model was
    measured against it -- an upload can be edited by its author, and a
    benchmark that silently moves is not a benchmark.
    """
    import spicy_lyrics as SL
    cdp = _cdp()
    into = APPLE if apple else SNAP
    into.mkdir(parents=True, exist_ok=True)
    ids = cdp.evaluate("""(async () => {
          const c = await caches.open(%s);
          return (await c.keys()).map(r => r.url.split('/').pop());
        })()""" % json.dumps(SL.CACHE_NAME)) or []
    tracks = _tracks()
    kept = foreign = thin = 0
    for n, tid in enumerate(ids, 1):
        if limit and kept >= limit:
            break
        got = cdp.evaluate(SL.JS_GET % SL._j(SL.CACHE_NAME, SL.IDB_NAME,
                                             SL.IDB_STORE, tid)) or {}
        doc = SL.payload(got.get("body") or {})
        if not doc:
            continue
        want = (str(doc.get("source") or "") == "aml") if apple else community(doc)
        if not want:
            foreign += 1
            continue
        if len(lines(doc)) < 6:
            thin += 1
            continue
        (into / f"{tid}.json").write_text(json.dumps(doc, ensure_ascii=False),
                                          encoding="utf-8")
        if tid not in tracks:
            meta = cdp.evaluate(JS_TRACK % json.dumps("spotify:track:" + tid))
            if meta and meta.get("title"):
                tracks[tid] = meta
        kept += 1
        if n % 50 == 0:
            print(f"  {n} of {len(ids)}…", flush=True)
    _tracks(tracks)
    print(f"kept {kept} {'aml' if apple else 'spl'} lyric(s) in {into}; passed "
          f"over {foreign} from other sources and {thin} with too few timed lines")
    return 0


def _tracks(write: dict | None = None) -> dict:
    """Track titles and lengths, shared with the rest of the project."""
    path = pathlib.Path.home() / ".cache/mild-lyrics/tracks.json"
    if write is not None:
        path.write_text(json.dumps(write), encoding="utf-8")
        return write
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# Whose hand timed a document, in the order Spicy Lyrics fills the fields in.
LEGACY = "gc"


def credited(doc: dict) -> str:
    """The person whose hand these timings came from.

    Three cases, and the third is the one worth writing down:

      Maker set          -- the uploader was passing on somebody else's work,
                            and the Maker is who timed it.
      Maker unset        -- the uploader timed it themselves.
      Neither, but spl   -- an upload from before the metadata existed. Those
                            are all gc's: they are what is left of the oldest
                            community TTMLs, and nobody else's survive.

    A community document should always carry one of the two. One that carries
    neither AND is not spl did not come from a person at all -- it is Apple
    Music's or Spotify's -- and gets nobody's name, so it can never be counted
    as a hand-timed reference.
    """
    meta = doc.get("TTMLUploadMetadata")
    if isinstance(meta, dict):
        maker = (meta.get("Maker") or {}).get("username")
        if maker:
            return str(maker)
        uploader = (meta.get("Uploader") or {}).get("username")
        if uploader:
            return str(uploader)
    return LEGACY if str(doc.get("source") or "") == COMMUNITY else ""


def by_hand(who: str, docs: dict | None = None) -> dict:
    """Only the documents `who` timed.

    Worth having as its own thing rather than a filter written twice: a lyric
    somebody timed by ear against the master is a different KIND of label from
    one that came out of a pipeline, and it is the only kind that can settle a
    question at 50 ms. The benchmark's floor is the reference's own error, so
    measuring against a set with one author's hand on all of it is the only way
    to see below the 0.05-0.10s noise the mixed set carries.
    """
    docs = snapshots() if docs is None else docs
    return {tid: doc for tid, doc in docs.items() if credited(doc) == who}


def snapshots(*where) -> dict:
    """{tid: document} for the snapshot directories named, spl and aml by default.

    The benchmark passes SNAP explicitly. Training passes nothing and gets
    both. A caller that wants everything and means it says so.
    """
    out = {}
    for root in (where or (SNAP, APPLE)):
        out.update(_read(pathlib.Path(root)))
    return out


def _read(root: pathlib.Path) -> dict:
    out = {}
    for path in sorted(root.glob("*.json")):
        try:
            out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return out


def name_of(tid: str, tracks: dict | None = None) -> str:
    meta = (tracks if tracks is not None else _tracks()).get(tid) or {}
    return f"{meta.get('artist', '?')[:22]} - {meta.get('title', tid)[:26]}"


def _measure(net, mono, doc: dict, already: float) -> dict:
    """Where this copy sits against its own lyric, using the audio in hand."""
    import torch
    from . import ctcalign, model as M
    ref = reference(doc)
    if len(ref) < offset.PAIRS_MIN:
        return {"trusted": False, "why": "too few reference words", "lag": 0.0,
                "spread": 0.0}
    keep = mono[int(already * audio.RATE):] if already else mono
    logp = M.emit(net, keep, "cuda" if torch.cuda.is_available() else "cpu")
    got = ctcalign.words(logp, [w for w, _t in ref])
    from difflib import SequenceMatcher
    a = [text.flatten(w["word"]) for w in got]
    b = [text.flatten(w) for w, _t in ref]
    errs = []
    for i, j, n in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(n):
            if a[i + k]:
                errs.append(got[i + k]["start"] - ref[j + k][1])
    return offset.summarise(errs)


def _runs(rows: list[dict], group: int) -> list[list[int]]:
    """Consecutive lines gathered into clips of at most `group` of them.

    WHY GROUPED CLIPS EXIST. One clip per line cannot teach a line-start head
    anything: every clip has exactly one line start, always its first word,
    always about `pad` seconds in. A head trained on that learns the position,
    not the sound, and predicts nothing useful over a whole song. Negatives --
    word starts that are NOT line starts -- only exist inside a clip that holds
    more than one line.
    """
    out, at = [], 0
    while at < len(rows):
        run = [at]
        while len(run) < group and run[-1] + 1 < len(rows):
            nxt = run[-1] + 1
            if rows[nxt]["start"] - rows[run[-1]]["end"] > GROUP_GAP:
                break
            if rows[nxt]["end"] - rows[run[0]]["start"] > GROUP_MAX:
                break
            run.append(nxt)
        out.append(run)
        at = run[-1] + 1
    return out


def build(songs: int = 50, out=DATA, spare: float = 0.4, stem: bool = False,
          pad: float = PAD, recut: bool = False, ckpt=None,
          group: int = 1) -> int:
    """Cut clips for songs the snapshot has and the dataset does not.

    With `recut`, songs ALREADY in the manifest are cut again -- and the offset
    they are cut at is measured inside this same pass, against the very copy
    being cut, rather than read from a file written on some other day against
    some other download.

    That distinction is the whole reason this exists. The first pass of this
    dataset was cut before any offset had been measured, the measurements
    arrived afterwards, and nothing ever went back: 75 songs holding a third of
    the clips sat at a lag their own measurement contradicted, one of them by
    1.77s on clips padded by 0.25s -- which is to say most of that song's clips
    held different words than their labels said. Data that wrong does not
    average out; it teaches the model that words it cannot hear are present.
    """
    import numpy as np
    import local_align as LA

    out = pathlib.Path(out).expanduser()
    (out / "clips").mkdir(parents=True, exist_ok=True)
    # WHAT THIS DATASET IS, written down. A model trained on separated vocals
    # comes apart on a mixture -- 0.317s becomes 1.353s, four of seventeen
    # songs usable instead of ten -- so the player has to know which kind it is
    # holding. It used to infer that from the FILENAME, looking for "-stem" or
    # "-pitch", which made two stem-trained models named "-lines" and "-vox"
    # read as mixture models. They only failed to be chosen because they had
    # fewer steps than the incumbent.
    (out / "meta.json").write_text(json.dumps(
        {"stem": bool(stem), "group": int(group), "pad": float(pad)}), "utf-8")
    manifest = out / "manifest.jsonl"
    done, fixed = set(), set()
    if manifest.exists():
        for row in manifest.read_text(encoding="utf-8").splitlines():
            try:
                got = json.loads(row)
            except Exception:
                continue
            done.add(got["tid"])
            # Which songs a re-cut pass has already corrected. Without this a
            # run interrupted at song 200 starts again at song 1, and a pass
            # over the whole dataset takes hours -- it will be interrupted.
            if got.get("recut"):
                fixed.add(got["tid"])
    docs = snapshots()
    if not docs:
        raise SystemExit("nothing in the snapshot -- run `sync snapshot` first")
    tracks = _tracks()
    lags = offset.load()
    print(f"{len(docs)} lyric(s) on hand, {len(done)} already cut, "
          f"{sum(1 for v in lags.values() if v.get('trusted'))} with a measured "
          f"offset")

    net = None
    if recut:
        import torch
        from . import model as M
        where = pathlib.Path(ckpt or (HOME / "syncnet-boundary.pt")).expanduser()
        if not where.exists():
            raise SystemExit(f"--recut needs a model to measure with; none at {where}")
        net, _rest = M.load(where, "cuda" if torch.cuda.is_available() else "cpu")
        print(f"re-cutting at offsets measured by {where.name} in this same pass")

    added = clips = shifted = 0
    secs = 0.0
    with manifest.open("a", encoding="utf-8") as log:
        for tid, doc in docs.items():
            if added >= songs:
                break
            if tid not in tracks:
                continue
            if tid in done and not recut:
                continue
            if recut and tid in fixed:
                continue
            meta = tracks[tid]
            name = name_of(tid, tracks)
            rows = lines(doc)
            if len(rows) < 6:
                continue
            t0 = time.monotonic()
            try:
                with LA.fetched(f"{meta['artist']} {meta['title']}",
                                float(meta.get("length") or 0),
                                artist=meta.get("artist", ""), tid=tid) as path:
                    if not path:
                        print(f"  skip {name}: {LA.fetched.last_error[:40]}")
                        continue
                    wave, rate = audio.read(path)
                    mono = audio.mono16k(wave, rate)
                    # Two corrections, in order: what the lengths say, then
                    # what a model measured. The first is arithmetic and is
                    # always applied; the second is only ever applied to songs
                    # whose measurement was tight enough to believe.
                    lag, why = offset.trim(mono, float(meta.get("length") or 0))
                    if why:
                        print(f"  {name}: {why}")
                    if recut and net is not None:
                        # Measured here, on this audio, in this pass.
                        said = _measure(net, mono, doc, lag)
                        if said["trusted"]:
                            lag += said["lag"]
                            print(f"  {name:52} measured {said['lag']:+.2f}s "
                                  f"(spread {said['spread']:.2f})")
                        else:
                            print(f"  {name:52} not measured — {said['why']}")
                    else:
                        lag += offset.for_song(
                            f"{meta['artist']} - {meta['title']}", lags)
                    if abs(lag) >= offset.LEAST:
                        shifted += 1
                    else:
                        lag = 0.0
                    if stem:
                        dev, win, _ = LA.room("gpu", LA.DEMUCS_COST,
                                              LA.DEMUCS_WINDOW, spare)
                        sep, srate = LA.separate(wave, rate, dev, win,
                                                 LA.MODEL, None, None)
                        mono = audio.mono16k(sep, srate)
            except Exception as exc:
                print(f"  skip {name}: {type(exc).__name__}: {exc}")
                continue
            finally:
                LA.release()

            kept = []
            have = mono.shape[-1] / audio.RATE
            for k, run in enumerate(_runs(rows, group)):
                part = [rows[i] for i in run]
                lo, hi = part[0]["start"], part[-1]["end"]
                label = " ".join(x for x in (text.line(r["text"]) for r in part) if x)
                if not label:
                    continue
                # JITTERED LEAD-IN for grouped clips. Cut at a fixed pad, the
                # first line of every clip begins at exactly `pad` seconds, and
                # a line-start head can collect half its positives by predicting
                # that constant instead of listening. Interior line starts are
                # already honest; this makes the first one honest too.
                lead = pad if group == 1 else random.uniform(0.10, 0.70)
                a = max(0.0, lo + lag - lead)
                b = min(have, hi + lag + pad)
                if not (MIN_CLIP <= b - a <= MAX_CLIP):
                    continue
                piece = mono[int(a * audio.RATE):int(b * audio.RATE)]
                if piece.shape[-1] < int(MIN_CLIP * audio.RATE):
                    continue
                np.save(out / "clips" / f"{tid}_{k:04d}.npy",
                        piece.numpy().astype("float32"))
                bounds = [
                    [round(float(w["start"] + lag - a), 3),
                     round(float(w["end"] + lag - a), 3)]
                    for r in part for w in r["words"]
                    if isinstance(w.get("start"), (int, float))
                    and isinstance(w.get("end"), (int, float))
                ]
                # Where each LINE begins inside the clip, which is the thing a
                # single-line clip cannot say: in a grouped clip most word
                # starts are not line starts, so the head has negatives.
                starts = [
                    round(float(r["words"][0]["start"] + lag - a), 3)
                    for r in part
                    if r.get("words")
                    and isinstance(r["words"][0].get("start"), (int, float))
                ]
                kept.append({
                    "clip": f"{tid}_{k:04d}.npy",
                    "text": label,
                    "secs": round(float(b - a), 3),
                    "bounds": bounds,
                    **({"starts": starts} if group > 1 else {}),
                })
            if not kept:
                print(f"  skip {name}: no usable lines")
                continue
            log.write(json.dumps({"tid": tid, "name": name, "lines": kept,
                                  "lag": round(lag, 3),
                                  **({"recut": time.strftime("%Y-%m-%d")}
                                     if recut else {})}) + "\n")
            log.flush()
            added += 1
            clips += len(kept)
            secs += sum(x["secs"] for x in kept)
            print(f"  {name:52} {len(kept):3} clips  {sum(x['secs'] for x in kept):6.1f}s"
                  f"  ({time.monotonic() - t0:.0f}s)")

    print(f"added {added} song(s), {clips} clips, {secs / 3600:.2f} hours"
          + (f"; {shifted} cut at a corrected offset" if shifted else ""))
    return 0
