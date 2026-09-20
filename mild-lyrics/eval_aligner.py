#!/usr/bin/env python3
"""Measure this aligner against the word-synced lyrics already held here.

    ./eval_aligner.py --songs 10

Everything else in this program is measured against itself: how many lines got
an anchor, whether two of our own runs agree, whether a number went up. None of
that says whether a word is in the right place, and the only instrument that
could say so has been somebody listening.

The lyrics held here from Spicy Lyrics are word-synced documents -- Apple
Music's own timings and community ones -- for songs this machine has played. They are not
perfect and they are not ours, which is exactly what makes them useful: they
are an outside opinion about where the words are, on the very recordings this
aligner is asked about.

So: align a song the ordinary way, match our words to theirs by their order,
and report the difference. The sign matters as much as the size -- a timing
that is always early is a bug with a fix, where one that is sometimes early and
sometimes late is noise.
"""
import argparse
import json
import pathlib
import statistics
import sys
import time
from difflib import SequenceMatcher

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import local_align as LA       # noqa: E402
import lyric_sources as LS     # noqa: E402
import lyrics_gui as L         # noqa: E402
import spicy_lyrics as SL      # noqa: E402

JS_TRACK = """(async () => {
  try {
    const r = await Spicetify.GraphQL.Request(
      Spicetify.GraphQL.Definitions.getTrack, {uri: %s});
    const t = ((r.data || {}).trackUnion) || {};
    if (!t.name) return null;
    const arts = [...(((t.firstArtist || {}).items) || []),
                  ...(((t.otherArtists || {}).items) || [])];
    return {title: t.name,
            length: (((t.duration || {}).totalMilliseconds) || 0) / 1000,
            artist: arts.map(x => ((x.profile) || {}).name)
                        .filter(Boolean).join(", ")};
  } catch (e) { return null; }
})()"""


def reference(tid: str):
    """Spicy Lyrics' word timings for one track: [(word, start)] in order."""
    body = LS.spicy_held(tid)
    if not body:
        return []
    doc = SL.payload(body)
    if LS.quality(doc) != "syllable":
        return []
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


def ours(doc) -> list[tuple[str, float]]:
    """The same, from a document this aligner produced."""
    out = []
    for item in LS._items(SL.payload(doc)):
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


def shape(errs: list[float], times: list[float] | None = None) -> dict:
    """What KIND of wrong a song is, which a median cannot say.

    Papa Roach once scored a median of 22.8s while its last third was correct
    to five milliseconds: thirds of +66 / +24.8 / -0.005. One number for a song
    whose beginning and end disagree that violently describes neither.

      shift    every word out by the same amount -- a constant to subtract
      stretch  the error changes across the song -- a walk that ran away
      scatter  spread about the song's own median, not about zero
    """
    if not errs:
        return {}
    med = statistics.median(errs)
    out = {"median": med,
           "scatter": statistics.median([abs(e - med) for e in errs]),
           "worst": max(errs, key=abs)}
    order = ([e for _t, e in sorted(zip(times, errs))] if times and
             len(times) == len(errs) else list(errs))
    n = len(order) // 3
    if n:
        out["thirds"] = tuple(statistics.median(part) for part in
                              (order[:n], order[n:2 * n], order[2 * n:]))
    return out


def compare(mine, theirs) -> list[float]:
    """Signed error per word, in seconds, for the words both of them have.

    Matched by ORDER, not by text alone: a song repeats words, and the third
    "yeah" of a chorus is only identifiable as the third one.
    """
    a = [LA._flat(w) for w, _t in mine]
    b = [LA._flat(w) for w, _t in theirs]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            if a[i + k]:
                out.append(mine[i + k][1] - theirs[j + k][1])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", type=int, default=10)
    ap.add_argument("--spare", type=float, default=0.4)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from spotify_dom import connect
    cdp = connect(9222, "spotify")
    ids = LS.spicy_ids()
    print(f"{len(ids)} tracks held here")

    rows, every = [], []
    for tid in ids:
        if len(rows) >= args.songs:
            break
        ref = reference(tid)
        if len(ref) < 40:
            continue
        meta = cdp.evaluate(JS_TRACK % json.dumps("spotify:track:" + tid))
        if not meta or not meta.get("length"):
            continue
        doc = LA.genius_doc(L.load_token(), meta)
        if not doc:
            continue
        name = f"{meta['artist'][:24]} - {meta['title'][:28]}"
        query = f"{meta['artist']} {meta['title']}"
        t0 = time.monotonic()
        with LA.fetched(query, float(meta["length"]),
                        artist=meta.get("artist", ""), tid=tid) as audio:
            if not audio:
                print(f"  skip {name}: no copy ({LA.fetched.last_error[:40]})")
                continue
            out = LA.align(audio, doc, want="gpu", spare=args.spare,
                           target=float(meta["length"]))
        if out is None:
            print(f"  skip {name}: {LA.align.last_error[:50]}")
            continue
        errs = compare(ours(out), ref)
        LA.release()
        if len(errs) < 20:
            print(f"  skip {name}: only {len(errs)} words matched the reference")
            continue
        errs.sort()
        med = statistics.median(errs)
        rows.append((name, len(errs), med,
                     statistics.median([abs(e) for e in errs]),
                     sum(1 for e in errs if abs(e) < 0.3) / len(errs)))
        every.extend(errs)
        print(f"  {name:56} {len(errs):4} words  median {med:+.3f}s  "
              f"|median| {rows[-1][3]:.3f}s  within 0.3s {rows[-1][4] * 100:.0f}%  "
              f"({time.monotonic() - t0:.0f}s)")

    if not every:
        print("nothing measured")
        return 1
    every.sort()
    print("\n" + "=" * 78)
    print(f"{len(rows)} songs, {len(every)} words compared with the cache")
    print(f"  signed median   {statistics.median(every):+.3f}s   "
          f"(negative = this aligner is EARLY)")
    print(f"  absolute median {statistics.median([abs(e) for e in every]):.3f}s")
    print(f"  within 0.1s {sum(1 for e in every if abs(e) < 0.1) / len(every) * 100:.0f}%"
          f"   0.3s {sum(1 for e in every if abs(e) < 0.3) / len(every) * 100:.0f}%"
          f"   1.0s {sum(1 for e in every if abs(e) < 1.0) / len(every) * 100:.0f}%")
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(
            {"songs": rows, "errors": every}))
        print(f"  written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
