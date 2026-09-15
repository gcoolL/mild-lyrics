#!/usr/bin/env python3
"""Measure named songs, word by word, against the cache's own timings.

    ./bench.py bipolar showstopper
    ./bench.py bipolar --no-onsets --tag flat
    ./bench.py --show bipolar          what it got wrong, word by word

eval_aligner.py walks the cache and takes the first N songs with a reference.
That is the right instrument for "how is the aligner doing"; it is the wrong
one for "make THESE two songs right", which needs the same song measured over
and over under different settings, and needs to say which words missed.

So: the audio and the reference are fetched once and kept, every run writes its
per-word errors to bench/<song>.<tag>.json AND the document it produced to
bench/<song>.<tag>.ttml, and the summary is the share of words inside 0.1s --
the number actually being aimed at -- rather than a median, which hides a song
that is half perfect and half lost.

The .ttml beside the .json is there to be played. Every defect worth finding in
this aligner so far was found by somebody watching a file, not by reading a
summary: the ad-libs arriving a second early, the tail of syllables landing
where you can see them. The numbers say which song to look at; they have not
once said what is wrong with it.

Most references here are somebody else's opinion, not ground truth. Read a
CONSTANT offset with tight scatter as a difference of convention (they mark the
beat, we mark the consonant); read scatter as real disagreement.

TWO ARE EXCEPTIONS, and they are the ones to judge a change by:

  ToxiPlays - SHOWSTOPPER    timed by the artist who recorded it
  wifiskeleton - bipolar     timed by the person this aligner is for

Both were checked against the cache and match it to 0.000s across all 820
syllables, so every number ever reported for those two was already measured
against them. On these two there is no convention to argue about. An ad-lib
that lands 2.16s before where the artist put their own ad-lib is not a
disagreement, and a syllable outside 0.1s is not the reference's fault.
"""
import argparse
import json
import pathlib
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import eval_aligner as EV       # noqa: E402
import local_align as LA        # noqa: E402
import lyric_sources as LS      # noqa: E402
import lyrics_gui as L          # noqa: E402
import spicy_lyrics as SL       # noqa: E402
import ttml as T                # noqa: E402

OUT = ROOT / "bench"


def measure(cdp, query: str, tag: str, meta=None, **how) -> dict | None:
    if meta is None:
        meta = T.look_up(cdp, query)
    if not meta:
        print(f"  {query}: not in the lyrics cache")
        return None
    tid = meta["uri"].rsplit(":", 1)[-1]
    name = f"{meta['artist']} - {meta['title']}"
    ref = EV.reference(cdp, tid)
    if len(ref) < 20:
        print(f"  {name}: no word-synced reference to measure against")
        return None

    doc = LA.genius_doc(L.load_token(), meta)
    if not doc:
        print(f"  {name}: Genius has no lyrics")
        return None

    t0 = time.monotonic()
    with LA.fetched(f"{meta['artist']} {meta['title']}",
                    float(meta.get("length") or 0), artist=meta["artist"],
                    tid=tid) as audio:
        if not audio:
            print(f"  {name}: no copy — {LA.fetched.last_error[:60]}")
            return None
        got = LA.align(audio, doc, want="gpu", spare=how.pop("spare", 0.4),
                       target=float(meta.get("length") or 0) or None, **how)
    LA.release()
    if got is None:
        print(f"  {name}: {LA.align.last_error[:60]}")
        return None

    mine = EV.ours(got)
    errs = EV.compare(mine, ref)
    if len(errs) < 20:
        print(f"  {name}: only {len(errs)} words matched the reference")
        return None
    refdoc = cached(cdp, tid)
    syl = EV.compare(syllables(got), ref_syllables(refdoc))
    adlib = EV.compare(backing(LS._items(SL.payload(got))),
                       backing(LS._items(refdoc) if refdoc else []))

    pairs = paired(mine, ref)
    OUT.mkdir(exist_ok=True)
    row = {"name": name, "tag": tag, "how": {k: str(v) for k, v in how.items()},
           "seconds": round(time.monotonic() - t0, 1),
           "packed": got.get("_packed"), "heard": got.get("_heard_share"),
           "null": got.get("_heard_null"),
           "snapped": got.get("_snapped"), "of": got.get("_words"),
           "errors": errs, "words": pairs, "syllables": syl, "adlib": adlib}
    row.update(score(errs))
    row.update(seen(syl))
    (OUT / f"{T.safe(name)}.{tag}.json").write_text(json.dumps(row))

    (OUT / f"{T.safe(name)}.{tag}.ttml").write_text(
        SL.render(got, "ttml") + "\n", encoding="utf-8")

    flux = getattr(LA._onsets, "flux", None)
    if flux:
        (OUT / f"{T.safe(name)}.raw.json").write_text(json.dumps(
            {"name": name, "flux": [round(x, 4) for x in flux],
             "step": LA._onsets.step, "offset": getattr(LA._onsets, "offset", 0.0),
             "before": LA._snap.before, "ref": ref}))
    return row


def syllables(doc) -> list[tuple[str, float]]:
    """(text, start) per SYLLABLE, not glued back into words.

    eval_aligner deliberately glues them: a word is the largest unit this
    aligner and whoever made the reference both agree exists, so it is the
    honest unit to score on. That is right for "is the aligner correct" and
    wrong for "does it look right", which is the question a syllable-synced
    display asks. The highlight moves per syllable, so a syllable in the wrong
    place is a thing you SEE, whether or not its word began on time.
    """
    out = []
    for item in LS._items(SL.payload(doc)):
        lead = item.get("Lead")
        if not isinstance(lead, dict):
            continue
        for syl in lead.get("Syllables") or []:
            at = syl.get("StartTime")
            if str(syl.get("Text") or "").strip() and isinstance(at, (int, float)):
                out.append((str(syl["Text"]), float(at)))
    return out


def backing(items, key="Background") -> list[tuple[str, float]]:
    """(text, start) per AD-LIB syllable.

    Measured separately because it was never measured at all. eval_aligner
    reads each line's Lead and stops, so every number this project has ever
    produced has been about the main voice -- and on SHOWSTOPPER the ad-libs
    came in a median 2.16 SECONDS early, 43 of 46 of them, while the lead was
    inside 0.1s for 89% of its words. A song can be right and wrong at once,
    and only one half of it was being looked at.
    """
    out = []
    for item in items:
        for group in item.get(key) or []:
            if not isinstance(group, dict):
                continue
            for syl in group.get("Syllables") or []:
                at = syl.get("StartTime")
                if str(syl.get("Text") or "").strip() and isinstance(at, (int, float)):
                    out.append((str(syl["Text"]), float(at)))
    return out


def cached(cdp, tid: str):
    """The cache's own document for a track, parsed, or None."""
    body = SL.cached_body(cdp.evaluate, tid)
    if not body:
        return None
    doc = SL.payload(body)
    return doc if LS.quality(doc) == "syllable" else None


def ref_syllables(doc) -> list[tuple[str, float]]:
    """The same as syllables(), from an already-parsed cache document."""
    if doc is None:
        return []
    out = []
    for item in LS._items(doc):
        lead = item.get("Lead")
        if not isinstance(lead, dict):
            continue
        for syl in lead.get("Syllables") or []:
            at = syl.get("StartTime")
            if str(syl.get("Text") or "").strip() and isinstance(at, (int, float)):
                out.append((str(syl["Text"]), float(at)))
    return out


def paired(mine, ref) -> list:
    """[(word, ours, theirs)] for the words both sides have, in order."""
    from difflib import SequenceMatcher
    a = [LA._flat(w) for w, _t in mine]
    b = [LA._flat(w) for w, _t in ref]
    out = []
    for i, j, n in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(n):
            if a[i + k]:
                out.append([mine[i + k][0], round(mine[i + k][1], 3),
                            round(ref[j + k][1], 3)])
    return out


def score(errs: list[float]) -> dict:
    got = {"n": len(errs),
           "hit": sum(1 for e in errs if abs(e) < 0.1) / len(errs),
           "near": sum(1 for e in errs if abs(e) < 0.3) / len(errs),
           "lost": sum(1 for e in errs if abs(e) > 1.0) / len(errs)}
    got.update(EV.shape(errs))
    return got


SEEN = 0.2


def seen(errs: list[float]) -> dict:
    """How many syllables land somewhere a viewer will notice.

    A COUNT, not a share. "84% of syllables within 0.1s" reads as nearly
    finished; the same song's "42 syllables land more than 0.2s out" is the
    same fact and matches what somebody watching it actually complains about.
    The median stopped being the problem some time ago -- both songs sit at
    +0.02 to +0.04 -- and what is left is a tail, which a share hides and a
    count does not.
    """
    if not errs:
        return {"syl": 0, "off": 0, "off_share": 0.0}
    off = sum(1 for e in errs if abs(e) > SEEN)
    return {"syl": len(errs), "off": off, "off_share": off / len(errs)}


def line(row: dict) -> str:
    t = row.get("thirds") or (0, 0, 0)
    return (f"  {row['name'][:40]:40} {row['tag'][:10]:10} "
            f"{row['n']:4}w  within 0.1s {row['hit']*100:3.0f}%  "
            f"0.3s {row['near']*100:3.0f}%  lost {row['lost']*100:3.0f}%  "
            f"median {row['median']:+.3f}  scatter {row['scatter']:.3f}  "
            f"thirds {t[0]:+.2f}/{t[1]:+.2f}/{t[2]:+.2f}\n"
            f"  {'':40} {'':10} {row.get('syl', 0):4}s  "
            f"** {row.get('off', 0)} syllable(s) further than {SEEN}s "
            f"out ** ({row.get('off_share', 0)*100:.0f}%)"
            + (f"\n  {'':40} {'':10} {len(row['adlib']):4}a  "
               f"ad-libs median {statistics.median(row['adlib']):+.2f}s "
               f"(negative = they come in EARLY), "
               f"{sum(1 for e in row['adlib'] if abs(e) < 0.3)/len(row['adlib'])*100:.0f}% "
               f"within 0.3s" if row.get("adlib") else ""))


def show(name: str, tag: str, limit: int = 40) -> int:
    """The words that missed, worst first, with what came before and after."""
    hits = sorted(OUT.glob(f"*{tag}.json"))
    want = [p for p in hits if name.lower().replace(" ", "") in
            T.safe(p.name).lower().replace(" ", "")]
    if not want:
        print(f"  nothing measured for {name!r} with tag {tag!r}; "
              f"have: {[p.name for p in hits]}")
        return 1
    row = json.loads(want[0].read_text())
    print(line(row))
    words = row["words"]
    bad = sorted(range(len(words)), key=lambda i: -abs(words[i][1] - words[i][2]))
    print(f"\n  {'word':<18} {'ours':>8} {'theirs':>8} {'off':>8}")
    for i in bad[:limit]:
        w, us, them = words[i]
        print(f"  {w[:18]:<18} {us:8.2f} {them:8.2f} {us - them:+8.2f}")
    return 0


def every_referenced(cdp, want: int) -> list[dict]:
    """Songs the cache has WORD-SYNCED timings for, in a stable order.

    Ordered by a hash of the name, not by when the song was played: the cache
    grows every day, and a set that re-draws itself between runs cannot be
    compared with the run before it.
    """
    import hashlib
    ids = cdp.evaluate(SL.JS_IDS % json.dumps(SL.CACHE_PREFIX)) or []
    known = T.index(cdp)
    rows = []
    for tid in ids:
        meta = known.get(tid)
        if not meta or not meta.get("length"):
            continue
        rows.append(dict(meta, uri="spotify:track:" + tid))
    rows.sort(key=lambda m: hashlib.sha1(
        f"{m['artist']} - {m['title']}".encode("utf-8")).hexdigest())
    out = []
    for meta in rows:
        if len(out) >= want:
            break
        tid = meta["uri"].rsplit(":", 1)[-1]
        doc = cached(cdp, tid)
        if doc is None or str(doc.get("source") or "") != "spl":
            continue
        if len(EV.reference(cdp, tid)) >= 40:
            out.append(meta)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("songs", nargs="*")
    ap.add_argument("--all", type=int, default=0,
                    help="benchmark this many cached songs that have a "
                         "word-synced reference, instead of naming them")
    ap.add_argument("--tag", default="now", help="what to call this setting")
    ap.add_argument("--no-onsets", action="store_true")
    ap.add_argument("--tuned", action="store_true",
                    help="align with the fine-tuned model, not the bundled one")
    ap.add_argument("--reach", type=float, default=-1.0,
                    help="seconds past its line's end an ad-lib may be found")
    ap.add_argument("--back", type=int, default=-1,
                    help="frames a peak may walk back to the foot of its rise")
    ap.add_argument("--late", type=float, default=-1.0,
                    help="where a word's start is expected, behind CTC's guess")
    ap.add_argument("--lead-kept", action="store_true",
                    help="also take the model's lateness off words that found "
                         "no onset")
    ap.add_argument("--no-stems", action="store_true",
                    help="align against the full mix — no demucs at all, "
                         "which also costs the VAD and puts the onsets on "
                         "the mix")
    ap.add_argument("--emit", default="", choices=["", "stem", "mix"],
                    help="which audio wav2vec2 reads. `mix` keeps demucs for "
                         "the VAD, onsets and syllables but takes the "
                         "emission off the untouched mix, which is the only "
                         "arm that isolates separation artifacts")
    ap.add_argument("--acoustic", default="")
    ap.add_argument("--model", default="", help="the stem model, align(name=)")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the is-this-the-right-recording check (~20s)")
    ap.add_argument("--show", action="store_true", help="read a kept run back")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--spare", type=float, default=0.4)
    args = ap.parse_args()

    if args.show:
        return max(show(s, args.tag, args.limit) for s in args.songs)

    how = {"spare": args.spare, "onsets": not args.no_onsets,
           "verify": not args.no_verify}
    if args.no_stems:
        how["stems"] = False
    if args.emit:
        how["emit_from"] = args.emit
    if args.acoustic:
        how["acoustic"] = args.acoustic
    if args.model:
        how["name"] = args.model

    if args.tuned:
        import run_pipeline as RP
        RP.patched_w2v()
        print(f"  aligning with {RP.TUNED}")
    LA.ONSET_LEAD_KEPT = args.lead_kept
    if args.reach >= 0:
        LA.ADLIB_REACH = args.reach
    if args.back >= 0:
        LA.ONSET_BACK = args.back
    if args.late >= 0:
        LA.ONSET_LATE = args.late
    cdp = T.spotify()
    if not args.no_verify:
        how["decoys"] = T.decoys(cdp)
        print(f"  {len(how['decoys'])} decoy song(s) for the recording check")
    jobs = [(s, None) for s in args.songs]
    if args.all:
        picked = every_referenced(cdp, args.all)
        print(f"  {len(picked)} cached song(s) have a word-synced reference")
        jobs += [(f"{m['artist']} - {m['title']}", m) for m in picked]
    if not jobs:
        print("  name some songs, or pass --all N")
        return 1
    rows = []
    for song, meta in jobs:
        try:
            row = measure(cdp, song, args.tag, meta=meta, **how)
        except Exception as exc:
            print(f"  {song}: {type(exc).__name__}: {exc}")
            LA.release()
            continue
        if row:
            rows.append(row)
            print(line(row), flush=True)
    if not rows:
        return 1
    every = [e for r in rows for e in r["errors"]]
    syl = [e for r in rows for e in r.get("syllables") or []]
    print(f"\n  {len(rows)} song(s), {len(every)} words: within 0.1s "
          f"{sum(1 for e in every if abs(e) < 0.1)/len(every)*100:.0f}%")
    if syl:
        off = sum(1 for e in syl if abs(e) > SEEN)
        print(f"  {len(syl)} syllables: {off} further than {SEEN}s out "
              f"({off/len(syl)*100:.0f}%) — {off/len(rows):.0f} per song")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
