#!/usr/bin/env python3
"""Measure the documents the CHAIN produces, not the ones this machine aligns.

    ./eval_sources.py --songs 20
    ./eval_sources.py --track 3i5qVV8azKqGFK4Gzdt5YS
    ./eval_sources.py --songs 40 --json before.json

eval_aligner.py asks whether local_align put the words in the right place. This
asks the same question of the answer the player actually shows: Spicy Lyrics'
document with the walk's best effort laid over it, folded and unlumped exactly
as lyrics_gui does it before drawing.

Four numbers, because four different things go wrong and one of them is
invisible without saying so:

  word-timed   lines that came out with syllables at all. A line the sources
               only stamp at line level lights as a whole, which is honest and
               is not a defect.
  bridged      onsets nobody measured -- shared out between two that were.
               A blend that borrows timings from a document tokenised
               differently invents these by the dozen, and they are the
               difference between a sync that reads right and one that reads
               "off" without ever being far out.
  lumps        syllables holding two or more words. Should be zero. They light
               together and none of them lights when it is sung.
  against a    where a hand-timed TTML exists for the track, the signed error
  reference    per word, through eval_aligner's own compare() and shape().

References are read from --refs (default ./lyrics), named "ARTIST - TITLE"
however much else is in the filename, which is how the ones here are named.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import eval_aligner as EV       # noqa: E402  (compare, shape, ours)
import lyric_sources as LS      # noqa: E402
import spicy_lyrics as SL       # noqa: E402


def settings() -> tuple[set, list, bool]:
    """The player's own source list, so this measures what it would show."""
    try:
        cfg = json.loads((LS.config_root() / "gui.json").read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        cfg = {}
    order = [n.strip() for n in str(cfg.get("src_order") or "").split(",") if n.strip()]
    on = {k[4:] for k, v in cfg.items() if k.startswith("src_") and v is True}
    if not order:
        order = ["spicy", "amll", "youly", "netease", "lrclib", "local"]
    if not on:
        on = set(order)
    return on, order, bool(cfg.get("fold_adlibs", True))


def spicy(cdp, tid: str):
    """Spicy Lyrics' own document for a track, which is usually the base."""
    if cdp is None:
        return None
    try:
        got = cdp.evaluate(SL.JS_GET % SL._j(SL.CACHE_NAME, SL.IDB_NAME,
                                             SL.IDB_STORE, tid)) or {}
    except Exception:                                    # noqa: BLE001
        return None
    return got.get("body") or None


def shown(tid: str, meta: dict, body, on: set, order: list, fold: bool):
    """What the player would draw for this track, by the same steps it takes."""
    have = LS.quality(body) if body else "none"
    ahead = order[:order.index("spicy")] if "spicy" in order else []
    got = LS.fallback(tid, meta, have, enabled=on, order=order, ahead=ahead,
                      local=body, force=True)
    doc, who = (got if got else (body, "spicy" if body else ""))
    if not doc:
        return None, ""
    if fold:
        doc = LS.fold_cries(doc)
    return LS.unlump(doc), who


def audit(doc) -> dict:
    """Lines, words, and how many of the words nobody actually timed."""
    items = LS._items(SL.payload(doc))
    got = {"lines": len(items), "worded": 0, "words": 0, "bridged": 0, "lumps": 0}
    for it in items:
        if ((it.get("Lead") or {}).get("Syllables") or []):
            got["worded"] += 1
        for group in [it.get("Lead")] + list(it.get("Background") or []):
            for y in ((group or {}).get("Syllables") or []):
                got["words"] += 1
                if y.get("Guess"):
                    got["bridged"] += 1
                text = str(y.get("Text") or "").strip()
                if SL.CJK.search(text):
                    continue
                if len([w for w in text.split() if any(c.isalnum() for c in w)]) >= 2:
                    got["lumps"] += 1
    return got


def references(where: str) -> dict:
    """title+artist -> a hand-timed document, from a directory of TTMLs."""
    out = {}
    root = pathlib.Path(where).expanduser()
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*.ttml")):
        stem = re.sub(r"\s*[(\[].*?[)\]]\s*", " ", path.stem).strip()
        if " - " not in stem:
            continue
        artist, title = (s.strip() for s in stem.split(" - ", 1))
        try:
            doc = LS.parse_ttml(path.read_bytes())
        except Exception:                                # noqa: BLE001
            continue
        if doc and LS.quality(doc) == "syllable":
            out[f"{LS._norm(title)}\x00{LS._norm(artist)}"] = (path.name, doc)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", type=int, default=20)
    ap.add_argument("--track", default="", help="measure one track id")
    ap.add_argument("--refs", default=str(pathlib.Path(__file__).resolve().parent.parent
                                          / "lyrics"))
    ap.add_argument("--json", default="", help="write the rows here")
    ap.add_argument("--no-spicy", action="store_true",
                    help="do not read Spicy Lyrics' own copy over CDP")
    args = ap.parse_args()

    on, order, fold = settings()
    print(f"sources: {' '.join(n for n in order if n in on)}"
          f"{'   (folding ad-libs)' if fold else ''}")
    refs = references(args.refs)
    if refs:
        print(f"{len(refs)} hand-timed reference(s) in {args.refs}")

    try:
        tracks = json.loads((LS.cache_root() / "tracks.json").read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        tracks = {}
    picked = ([(args.track, tracks.get(args.track) or {})] if args.track
              else [(k, v) for k, v in tracks.items() if v.get("title") and v.get("artist")])

    cdp = None
    if not args.no_spicy:
        try:
            from spotify_dom import connect
            cdp = connect(9222, "spotify")
        except Exception as exc:                         # noqa: BLE001
            print(f"no Spicy Lyrics to read ({type(exc).__name__}); "
                  f"measuring the walk alone")

    rows, errs = [], []
    for tid, v in picked:
        if len(rows) >= args.songs and not args.track:
            break
        meta = {"title": v.get("title", ""), "artist": v.get("artist", ""),
                "length": float(v.get("length") or 0)}
        if not meta["title"]:
            continue
        doc, who = shown(tid, meta, spicy(cdp, tid), on, order, fold)
        if not doc or LS.quality(doc) == "none":
            continue
        got = audit(doc)
        if got["lines"] < 6:
            continue
        name = f"{meta['artist'][:22]} - {meta['title'][:26]}"
        key = f"{LS._norm(meta['title'])}\x00{LS._norm(meta['artist'])}"
        mark = ""
        if key in refs:
            ref_name, ref_doc = refs[key]
            one = EV.compare(EV.ours(doc), EV.ours(ref_doc))
            if len(one) >= 12:
                errs.extend(one)
                said = EV.shape(one)
                mark = (f"   vs {ref_name[:22]}: median {said['median']:+.3f}s "
                        f"scatter {said['scatter']:.3f}s")
        rows.append({"tid": tid, "name": name, "won": who, **got})
        print(f"  {name:50} {who:9} {got['lines']:3} lines "
              f"{got['worded']:3} word-timed {got['words']:5} words "
              f"{got['bridged']:4} bridged {got['lumps']:3} lumps{mark}")

    if not rows:
        print("nothing measured")
        return 1
    tot = {k: sum(r[k] for r in rows) for k in ("lines", "worded", "words",
                                                "bridged", "lumps")}
    print(f"\n{len(rows)} songs   {tot['lines']} lines   "
          f"{tot['worded']} word-timed ({tot['worded'] / max(1, tot['lines']):.0%})   "
          f"{tot['words']} words   "
          f"{tot['bridged']} bridged ({tot['bridged'] / max(1, tot['words']):.1%})   "
          f"{tot['lumps']} lumps")
    if errs:
        said = EV.shape(errs)
        print(f"against {len(errs)} hand-timed words: median {said['median']:+.3f}s   "
              f"scatter {said['scatter']:.3f}s   worst {said['worst']:+.2f}s")
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps({"rows": rows, "total": tot,
                        "errors": errs}, indent=1), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
