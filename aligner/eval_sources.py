#!/usr/bin/env python3
"""Measure the documents the CHAIN produces, not the ones this machine aligns.

    ./eval_sources.py --songs 20
    ./eval_sources.py --track 3i5qVV8azKqGFK4Gzdt5YS
    ./eval_sources.py --songs 40 --json before.json
    ./eval_sources.py --songs 40 --only neblend,triblend,blend --against spicy
    ./eval_sources.py --donors --songs 60

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
`--against spicy` reads them from Spicy Lyrics' own COMMUNITY word syncs
instead -- the ones people hand-timed and uploaded, sitting in the Spotify
page's cache. There are more of those on any machine than there are files in
./lyrics, and they are the yardstick the songs were judged against by ear.

`--only` measures named providers head to head rather than whatever the
running order settles on, which is the only way to ask whether one blend is
better than another: left to the chain, the answer is always whichever one it
asked first.

`--donors` asks a different question entirely. Not "how good is the document"
but "what are NetEase, QQ Music and Kugou actually doing" -- fetched raw, with
nothing blended over them, and compared with each other. A blend can only be
as good as the clock it borrows, and every constant in _blend is a claim about
these three that nobody can check without the numbers. See donors_report().
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
    order = LS.carried([n.strip() for n in
                        str(cfg.get("src_order") or "").split(",")])
    live = {n for n in LS.SOURCES if cfg.get(f"src_{n}", True) is not False}
    # Sources in, providers out -- the walk is asked in the same terms the
    # player asks it in, or this measures a chain nobody is running. The
    # blends carry their own switches, so they are read too.
    got = LS.provider_order(order, lambda n: n in live,
                            lambda b: cfg.get(LS.BLEND_KEY[b], True) is not False)
    return set(got), got, bool(cfg.get("fold_adlibs", True))


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


def drawn(doc, who: str, fold: bool):
    """One document, put through the steps the player puts it through.

    Split out of shown() because --only asks the same question of a provider
    the chain did not pick, and measuring that one unshaped would be measuring
    a document nobody would ever see.
    """
    if not doc:
        return None
    # Only the documents whose ad-libs are still in their lyric, exactly as
    # the player decides it -- and the name has to be put on the document
    # first, because that is what the player is holding by the time it asks.
    fold = fold and LS.needs_adlibs(dict(doc, _source=who))
    if fold:
        doc = LS.fold_cries(doc)
    doc = LS.unlump(doc)
    doc = LS.quiet_marks(doc)
    return LS.split_asides(doc) if fold else doc


def shown(tid: str, meta: dict, body, on: set, order: list, fold: bool):
    """What the player would draw for this track, by the same steps it takes."""
    have = LS.quality(body) if body else "none"
    ahead = order[:order.index("spicy")] if "spicy" in order else []
    got = LS.fallback(tid, meta, have, enabled=on, order=order, ahead=ahead,
                      local=body, force=True)
    doc, who = (got if got else (body, "spicy" if body else ""))
    return drawn(doc, who, fold), who


def alone(tid: str, meta: dict, name: str, body, fold: bool):
    """What ONE named provider offers, shaped the same way.

    `body` -- Spicy Lyrics' own copy -- is handed over as `local`, which is
    what the player does. It matters most for the blends: `local` is the
    document a blend lays its borrowed timings under (see _blended), so
    withholding it would measure a blend built on a base the player would
    never have given it, and on the Chinese catalogue often on no base at all.
    """
    try:
        got = LS.fallback(tid, meta, "none", enabled={name}, order=[name],
                          local=body, force=True)
    except Exception:                                    # noqa: BLE001
        return None
    if not got:
        return None
    doc = got[0] if isinstance(got, tuple) else got
    return drawn(dict(doc, _source=name), name, fold)


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


def spicy_ref(body):
    """Spicy Lyrics' copy, but only where it is a COMMUNITY word sync.

    Its Apple-derived documents (`source: "aml"`) are not a reference: they
    are one of the things being measured, and scoring Apple's own timings
    against Apple's own timings would report zero and mean nothing. Only the
    hand-timed community uploads -- `spl` -- are somebody's answer to the
    question the blends are also answering.
    """
    doc = SL.payload(body or {})
    if str(doc.get("source") or "") != "spl":
        return None
    return body if LS.quality(body) == "syllable" else None


# --------------------------------------------------------------------------
# what the donors are actually doing
# --------------------------------------------------------------------------
# Two milliseconds. Every one of these sources writes its stamps to the
# millisecond, so anything at this distance was written as the same number.
TILED = 0.002
# Seventy, because that is the figure from_kublend already quotes for QQ and
# Kugou agreeing "syllable for syllable" -- reused so the two claims can be
# read against each other.
AGREE = 0.070
DONORS = ("netease", "qq", "kugou")


def _word_spans(doc) -> list[list[tuple[float, float]]]:
    """Per line, every word's (start, end).

    Syllables are glued into words by IsPartOfWord, the same way EV.ours does
    it, because the questions below are about words: a source that splits
    "running" into "run"+"ning" has not thereby measured two onsets.
    """
    out = []
    for item in LS._items(SL.payload(doc)):
        lead = item.get("Lead")
        line, at, end = [], None, None
        for y in (lead or {}).get("Syllables") or []:
            st, en = y.get("StartTime"), y.get("EndTime")
            if not isinstance(st, (int, float)):
                continue
            if at is None:
                at = float(st)
            end = float(en) if isinstance(en, (int, float)) else float(st)
            if not y.get("IsPartOfWord"):
                line.append((at, end))
                at = None
        if at is not None and end is not None:
            line.append((at, end))
        out.append(line)
    return out


def _words(doc) -> list[tuple[str, float, int]]:
    """Every word's onset, with the line it was written on.

    EV.ours() answers the same question without the line number, and the line
    number is the whole of H5: whether the filler times its lines badly, or
    is only ever handed the lines that were going to be timed badly anyway.
    """
    out = []
    for i, item in enumerate(LS._items(SL.payload(doc))):
        lead = item.get("Lead")
        if not isinstance(lead, dict):
            continue
        word, at = "", None
        for y in lead.get("Syllables") or []:
            if at is None:
                at = y.get("StartTime")
            word += str(y.get("Text") or "")
            if not y.get("IsPartOfWord"):
                if word.strip() and isinstance(at, (int, float)):
                    out.append((word.strip(), float(at), i))
                word, at = "", None
        if word.strip() and isinstance(at, (int, float)):
            out.append((word.strip(), float(at), i))
    return out


def _errs(mine, theirs) -> list[tuple[float, int]]:
    """EV.compare, but keeping which line of `mine` each error came from.

    The matching is EV's own -- by order, because a song repeats words -- and
    is re-walked here only because compare() hands its errors back flat.
    """
    from difflib import SequenceMatcher

    a = [EV.LA._flat(w) for w, _t, _i in mine]
    b = [EV.LA._flat(w) for w, _t in theirs]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    out = []
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            if a[i + k]:
                out.append((mine[i + k][1] - theirs[j + k][1], mine[i + k][2]))
    return out


def tiling(doc) -> tuple[int, int]:
    """H1. (word pairs where one word's end IS the next word's start, pairs).

    A tiled source has no mid-line ends to lend: every word is held lit until
    the next one starts, so a word sung short and a word sung long are written
    identically. _blend says this about QQ and Kugou in passing and acts on it
    at the line's last word only; this counts it, which is what says whether
    "the fill looks random" is tiling rather than noise.
    """
    tiled = pairs = 0
    for line in _word_spans(doc):
        for (_s, e), (nxt, _e2) in zip(line, line[1:]):
            pairs += 1
            tiled += 1 if abs(nxt - e) <= TILED else 0
    return tiled, pairs


def tails(doc) -> tuple[list, int, int]:
    """H2. How far each line runs past its own last word, and how often that
    is exactly where the next line starts.

    _last_end already assumes all three pad and none of them pads the same
    lines. The second number is the sharper one: an end that IS the next
    line's start was never measured at all, it was filled in.
    """
    items = LS._items(SL.payload(doc))
    spans = _word_spans(doc)
    past, butted, ends = [], 0, 0
    for i, (it, line) in enumerate(zip(items, spans)):
        end = LS._line_end(it)
        if not line or not isinstance(end, (int, float)):
            continue
        past.append(end - line[-1][1])
        nxt = SL.line_start(items[i + 1]) if i + 1 < len(items) else None
        if isinstance(nxt, (int, float)):
            ends += 1
            butted += 1 if abs(end - nxt) <= TILED else 0
    return past, butted, ends


def pairwise(a, b) -> dict | None:
    """H3/H4. How far apart two documents' word onsets are, offset removed.

    The median IS the offset -- two sources holding different masters, or one
    timed against a copy with a longer lead-in -- and _blend already absorbs a
    constant like that, per line, in `qby`. What it cannot absorb is what is
    left afterwards. So both are reported, and it is the SCATTER that means
    "clunky": an offset is a fact about the recording, a scatter is a fact
    about the timing.
    """
    got = EV.compare(EV.ours(a), EV.ours(b))
    if len(got) < 12:
        return None
    med = statistics.median(got)
    left = [e - med for e in got]
    return {"n": len(got), "offset": med,
            "scatter": statistics.median([abs(e) for e in left]),
            "within": sum(1 for e in left if abs(e) <= AGREE) / len(left)}


def filler_lines(two, three) -> set:
    """H5. The lines the second donor had to speak for.

    A line the first donor could not place comes out of the two-way blend with
    no words on it and out of the three-way with some. That difference is
    exactly the filler's work, and it is readable from the two finished
    documents without reaching inside _blend for it.

    Matched by the line's own TEXT, not by position. The two blends are built
    separately and either can stand down to a donor's whole document when its
    own answer is thinner (see _thinner), so the same song comes back with
    different line counts often enough that an index means nothing between
    them -- measured over 40 songs, matching by index found no holes at all
    while the two documents differed by fourteen points of coverage.
    """
    def worded(doc):
        got = {}
        for it in LS._items(SL.payload(doc or {})):
            key = LS._key(SL.line_text(it))
            if key:
                got[key] = bool(((it.get("Lead") or {}).get("Syllables") or []))
        return got

    a, b = worded(two), worded(three)
    if not b:
        return set()
    out = set()
    for i, it in enumerate(LS._items(SL.payload(three or {}))):
        key = LS._key(SL.line_text(it))
        # Not in the two-way at all counts too: either way the filler is
        # speaking for a line the first donor did not.
        if key and b.get(key) and not a.get(key, False):
            out.add(i)
    return out


def donors_report(picked, cdp, refs, use_spicy: bool, fold: bool,
                  limit: int) -> dict:
    """NetEase, QQ Music and Kugou as they really are, and where they differ.

    Raw -- nothing blended over them -- because a blend's clock can only be as
    good as the clock it borrowed, and every constant in _blend is a claim
    about these three that nobody can check without the numbers.
    """
    tile = {n: [0, 0] for n in DONORS}
    tail = {n: [[], 0, 0] for n in DONORS}
    pairs = {("qq", "kugou"): [], ("qq", "netease"): [], ("netease", "kugou"): []}
    filled, elsewhere, holes = [], [], 0
    rows, seen = [], 0
    for tid, v in picked:
        if seen >= limit:
            break
        meta = {"title": v.get("title", ""), "artist": v.get("artist", ""),
                "length": float(v.get("length") or 0)}
        if not meta["title"]:
            continue
        asked = dict(LS.PROVIDERS)
        got = {}
        for name in DONORS:
            try:
                doc = asked[name](tid, meta)
            except Exception:                            # noqa: BLE001
                doc = None
            if doc and LS.quality(doc) == "syllable":
                got[name] = doc
        if len(got) < 2:
            continue
        seen += 1
        for name, doc in got.items():
            a, b = tiling(doc)
            tile[name][0] += a
            tile[name][1] += b
            past, butted, ends = tails(doc)
            tail[name][0] += past
            tail[name][1] += butted
            tail[name][2] += ends
        said = []
        for (x, y), acc in pairs.items():
            if x in got and y in got:
                one = pairwise(got[x], got[y])
                if one:
                    acc.append(one)
                    said.append(f"{x[:2]}–{y[:2]} {one['offset']:+.3f} "
                                f"±{one['scatter']:.3f}")
        name = f"{meta['artist'][:20]} - {meta['title'][:24]}"
        print(f"  {name:46} {' '.join(sorted(got)):22} {'   '.join(said)}")
        rows.append({"tid": tid, "name": name, "have": sorted(got)})

        # H5 needs a reference and both three-way shapes of the same song.
        # Spicy Lyrics' own copy goes in as `local` either way, because that
        # is what the player hands a blend -- and where it is also the
        # reference, the words on both sides are the same words, which leaves
        # the clock as the only thing being measured.
        body = spicy(cdp, tid)
        ref = spicy_ref(body) if use_spicy else None
        if ref is None and not use_spicy:
            key = f"{LS._norm(meta['title'])}\x00{LS._norm(meta['artist'])}"
            ref = refs.get(key, (None, None))[1]
        if ref is None or "netease" not in got:
            continue
        # Not `body`. A blend keeps the base's own word timings where the
        # relay fails, so building on the community sync leaves no holes to
        # find -- the base already timed every line. Apple's own document is
        # both the honest base here and the one a blend really gets, since a
        # blend only reaches the screen where Spicy Lyrics has no word sync.
        two = alone(tid, meta, "neblend", None, fold)
        three = alone(tid, meta, "triblend", None, fold)
        where = filler_lines(two, three)
        if not where or not three:
            continue
        holes += len(where)
        for err, line in _errs(_words(three), EV.ours(ref)):
            (filled if line in where else elsewhere).append(err)
    return {"rows": rows, "tile": tile, "tail": tail,
            # Written out with a string key, so the whole report is one
            # json.dump away -- a tuple key is not a thing JSON has.
            "pairs": {f"{x}-{y}": acc for (x, y), acc in pairs.items()},
            "filled": filled, "elsewhere": elsewhere, "holes": holes}


def say_donors(got: dict) -> None:
    """The five questions, answered."""
    def pct(a, b):
        return f"{a / b:.1%}" if b else "  --  "

    print("\nH1  a word's end IS the next word's start")
    for n in DONORS:
        a, b = got["tile"][n]
        print(f"      {n:9} {pct(a, b)} of {b} word pairs")

    print("\nH2  how far a line runs past its own last word")
    for n in DONORS:
        past, butted, ends = got["tail"][n]
        med = f"{statistics.median(past):+.3f}s" if past else "  --  "
        print(f"      {n:9} median {med}   "
              f"and it IS the next line's start {pct(butted, ends)} of the time")

    print("\nH3/H4  two donors on the same song, the song's own offset removed")
    for both, acc in got["pairs"].items():
        pair = both.replace("-", "–")
        if not acc:
            print(f"      {pair:18} no song has both")
            continue
        off = statistics.median([abs(r["offset"]) for r in acc])
        sca = statistics.median([r["scatter"] for r in acc])
        win = statistics.median([r["within"] for r in acc])
        print(f"      {pair:18} {len(acc):3} songs   |offset| {off:.3f}s   "
              f"scatter {sca:.3f}s   "
              f"{win:.0%} of words within {AGREE * 1000:.0f}ms")

    print("\nH5  the lines the filler had to speak for")
    if not got["filled"]:
        print(f"      nothing measured -- {got['holes']} holes found, and no "
              f"song had both a reference and one")
        return
    for what, errs in (("on filled lines ", got["filled"]),
                       ("everywhere else ", got["elsewhere"])):
        if not errs:
            continue
        said = EV.shape(errs)
        print(f"      {what} {len(errs):5} words   median {said['median']:+.3f}s"
              f"   scatter {said['scatter']:.3f}s")
    print(f"      {got['holes']} lines NetEase could not place")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", type=int, default=20)
    ap.add_argument("--track", default="", help="measure one track id")
    ap.add_argument("--refs", default=str(pathlib.Path(__file__).resolve().parent.parent
                                          / "lyrics"))
    ap.add_argument("--json", default="", help="write the rows here")
    ap.add_argument("--no-spicy", action="store_true",
                    help="do not read Spicy Lyrics' own copy over CDP")
    ap.add_argument("--only", default="",
                    help="measure these providers head to head instead of the "
                         "running order, e.g. neblend,triblend,blend")
    ap.add_argument("--against", choices=("refs", "spicy"), default="refs",
                    help="where the reference timing comes from: the TTMLs in "
                         "--refs, or Spicy Lyrics' own community word syncs")
    ap.add_argument("--donors", action="store_true",
                    help="measure NetEase, QQ Music and Kugou raw, against "
                         "each other, instead of measuring a document")
    args = ap.parse_args()

    on, order, fold = settings()
    known = {n for n, _fn in LS.PROVIDERS}
    only = [n.strip() for n in args.only.split(",") if n.strip()]
    bad = [n for n in only if n not in known]
    if bad:
        print(f"no such provider: {', '.join(bad)}\n"
              f"there is: {' '.join(sorted(known))}")
        return 2
    if args.donors:
        print(f"donors, raw and unblended: {' '.join(DONORS)}")
    elif only:
        print(f"only: {' '.join(only)}"
              f"{'   (folding ad-libs)' if fold else ''}")
    else:
        print(f"sources: {' '.join(n for n in order if n in on)}"
              f"{'   (folding ad-libs)' if fold else ''}")
    refs = references(args.refs) if args.against == "refs" else {}
    if refs:
        print(f"{len(refs)} hand-timed reference(s) in {args.refs}")
    if args.against == "spicy":
        print("reference: Spicy Lyrics' own community word syncs")
        if args.no_spicy:
            print("...which --no-spicy refuses to read. Pick one.")
            return 2

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

    if args.donors:
        got = donors_report(picked, cdp, refs, args.against == "spicy", fold,
                            args.songs)
        if not got["rows"]:
            print("nothing measured -- no song had two donors answer")
            return 1
        say_donors(got)
        if args.json:
            pathlib.Path(args.json).write_text(json.dumps(got, indent=1),
                                               encoding="utf-8")
            print(f"wrote {args.json}")
        return 0

    rows, errs = [], []
    songs = 0
    for tid, v in picked:
        if songs >= args.songs and not args.track:
            break
        meta = {"title": v.get("title", ""), "artist": v.get("artist", ""),
                "length": float(v.get("length") or 0)}
        if not meta["title"]:
            continue
        body = spicy(cdp, tid)
        # The reference first, so a song without one is not fetched at all
        # when there would be nothing to say about it.
        key = f"{LS._norm(meta['title'])}\x00{LS._norm(meta['artist'])}"
        ref_name, ref_doc = "", None
        if args.against == "spicy":
            ref_doc = spicy_ref(body)
            ref_name = "the community's"
            # No community sync, nothing to score against, and a walk of ten
            # providers is too expensive to spend on a song that could only
            # ever contribute a coverage number. --against refs is the mode
            # that measures everything.
            if ref_doc is None:
                continue
        elif key in refs:
            ref_name, ref_doc = refs[key]
        # Head to head, or whatever the running order settles on. Either way
        # one line per document measured, so the two read the same.
        if only:
            # Not `body`, where `body` is also the reference. A blend lays a
            # donor's timings over a base and keeps the base's own where the
            # relay fails (see _blend), so handing it the very document it is
            # about to be scored against lets it copy the answer: Apple+QQ
            # came back "median +0.000s scatter 0.000s" on two songs here,
            # which is not a good blend, it is no blend at all.
            #
            # Nothing is lost by withholding it. A blend only ever reaches
            # the screen on a song Spicy Lyrics has NOT word-synced, which is
            # exactly the case this now measures.
            base = None if args.against == "spicy" else body
            asked = [(n, alone(tid, meta, n, base, fold)) for n in only]
        else:
            doc, who = shown(tid, meta, body, on, order, fold)
            asked = [(who, doc)]
        counted = False
        for who, doc in asked:
            if not doc or LS.quality(doc) == "none":
                continue
            got = audit(doc)
            if got["lines"] < 6:
                continue
            counted = True
            mark = ""
            if ref_doc is not None:
                one = EV.compare(EV.ours(doc), EV.ours(ref_doc))
                if len(one) >= 12:
                    errs.extend((who, e) for e in one)
                    said = EV.shape(one)
                    mark = (f"   vs {ref_name[:22]}: median {said['median']:+.3f}s "
                            f"scatter {said['scatter']:.3f}s")
            name = f"{meta['artist'][:22]} - {meta['title'][:26]}"
            rows.append({"tid": tid, "name": name, "won": who, **got})
            print(f"  {name:50} {who:11} {got['lines']:3} lines "
                  f"{got['worded']:3} word-timed {got['words']:5} words "
                  f"{got['bridged']:4} bridged {got['lumps']:3} lumps{mark}")
        songs += 1 if counted else 0

    if not rows:
        print("nothing measured")
        return 1
    for who in (only or [None]):
        mine = [r for r in rows if who is None or r["won"] == who]
        ours = [e for w, e in errs if who is None or w == who]
        if not mine:
            print(f"\n{who:11} nothing answered")
            continue
        tot = {k: sum(r[k] for r in mine) for k in ("lines", "worded", "words",
                                                    "bridged", "lumps")}
        print(f"\n{(who + '   ') if who else ''}{len(mine)} songs   "
              f"{tot['lines']} lines   "
              f"{tot['worded']} word-timed ({tot['worded'] / max(1, tot['lines']):.0%})   "
              f"{tot['words']} words   "
              f"{tot['bridged']} bridged ({tot['bridged'] / max(1, tot['words']):.1%})   "
              f"{tot['lumps']} lumps")
        if ours:
            said = EV.shape(ours)
            print(f"    against {len(ours)} reference words: "
                  f"median {said['median']:+.3f}s   "
                  f"scatter {said['scatter']:.3f}s   worst {said['worst']:+.2f}s")
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps({"rows": rows, "only": only, "against": args.against,
                        "errors": [{"who": w, "err": e} for w, e in errs]},
                       indent=1), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
