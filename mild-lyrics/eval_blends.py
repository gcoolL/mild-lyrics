#!/usr/bin/env python3
"""Measure the blends over a fixed set of donor documents, again and again.

    ./eval_blends.py fetch              # fill the jar (the only step that
                                        # goes to the network)
    ./eval_blends.py                    # score every blend over what is in it
    ./eval_blends.py --against spicy    # ...against the community word syncs
    ./eval_blends.py --json after.json
    ./eval_blends.py --diff before.json after.json

eval_sources.py measures the document the CHAIN settles on, which is the right
question to ask of the app and the wrong one to ask of a change to _blend: the
chain fetches afresh every time, the servers answer differently on different
days, and a two-point move in the numbers can be either the code or NetEase.

So this fetches each donor once, keeps it on disk, and rebuilds every blend
over the same documents however often the code changes. Nothing after `fetch`
touches the network, a run takes seconds, and a difference in the output is a
difference in the code.

Four questions, three of which eval_sources cannot ask:

  onsets       where each word starts, against a hand-timed reference. The
               one question eval_sources already answers; kept here because a
               change that fixes an end and breaks an onset has not fixed
               anything.
  ends         how long the line stays lit, against the same reference. A
               line that stops filling while the voice is still going is
               invisible to an onset test, and it is the commonest thing
               wrong with a blend: a donor that cannot write two lines
               overlapping cuts every sustain at the next line's start.
  voices twice the same words, over the same seconds, drawn in two places.
               A three-way blend reads its filler's whole document for
               ad-libs, and the lines the first donor already spoke for are
               in there too.
  ad-libs      the backing vocals the reference has: drawn as their own
               voice, drawn inside a line, or missing. `--who` then says
               which source was holding the missing ones, which is what
               separates "the blend dropped it" from "nobody has it".

Songs are the tracks with a hand-timed TTML in --refs, or, with
`--against spicy`, the ones Spicy Lyrics holds a COMMUNITY word sync for.
Those are somebody else's answer to the question the blends are answering,
and there are usually more of them than there are files in ./lyrics.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
from difflib import SequenceMatcher

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import eval_aligner as EV       # noqa: E402  (ours, compare, shape)
import eval_sources as ES       # noqa: E402  (references, spicy, drawn, audit)
import lyric_sources as LS      # noqa: E402
import spicy_lyrics as SL       # noqa: E402

JAR = LS.cache_root() / "eval-jar"
DONORS = ("apple", "qq", "netease", "kugou", "spicy")
WHOSE = {"qq": "QQ Music", "kugou": "Kugou", "netease": "NetEase"}
CUT_SHORT = 0.30
SAME_VOICE = 0.15


def spans_of(line: dict) -> list:
    """Every voice one drawn line puts on the screen, as (words, start, end)."""
    out = []
    lead, at, done = line.get("Lead"), SL.line_start(line), LS._line_end(line)
    if isinstance(lead, dict) and (lead.get("Syllables") or []) \
            and isinstance(at, (int, float)):
        out.append((LS._key(SL.line_text(line)), at,
                    done if isinstance(done, (int, float)) else at))
    for g in (line.get("Background") or []):
        syls = (g or {}).get("Syllables") or []
        s, e = LS._group_span(g, syls)
        if syls and isinstance(s, (int, float)):
            out.append((LS._key(SL.syllables_text(syls)), s,
                        e if isinstance(e, (int, float)) else s))
    return out


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def slot(tid: str, who: str) -> pathlib.Path:
    return JAR / f"{tid}.{who}.json"


def held(tid: str) -> dict:
    """Every donor this track has on disk. Missing ones answer None, which is
    what the blend would see if the door had failed."""
    out = {}
    for who in DONORS:
        path = slot(tid, who)
        out[who] = (json.loads(path.read_text(encoding="utf-8")).get("doc")
                    if path.exists() else None)
    return out


def fetch(rows: list, again: set) -> None:
    for n, row in enumerate(rows, 1):
        meta = {k: row[k] for k in ("title", "artist", "length")}
        tid = row["tid"]
        want = [w for w in DONORS if w in again or not slot(tid, w).exists()]
        name = f"{row['artist'][:20]:20} {row['title'][:28]:28}"
        if not want:
            print(f"  {n:3}/{len(rows)} {name} cached")
            continue
        # Each donor through the door the player itself uses. Apple used to be
        # asked of LyricsPlus here, and QQ Music too; that server is gone, so
        # these are BiniLyrics and QQ's own endpoint -- the same two the walk
        # would have used. A jar filled before this change holds the old
        # door's answers; --again refetches.
        jobs = {"apple": lambda: LS.from_bini(tid, meta),
                "qq": lambda: LS.from_qq(tid, meta),
                "netease": lambda: LS.from_netease(tid, meta),
                "kugou": lambda: LS.from_kugou(tid, meta),
                "spicy": lambda: ES.spicy(tid)}
        got = LS._parallel({w: jobs[w] for w in want})
        JAR.mkdir(parents=True, exist_ok=True)
        for who in want:
            slot(tid, who).write_text(
                json.dumps({"doc": got.get(who)}, ensure_ascii=False),
                encoding="utf-8")
        print(f"  {n:3}/{len(rows)} {name} "
              + " ".join(f"{w}={LS.quality(got.get(w)) if got.get(w) else '-'}"
                         for w in want))


def cached_ids() -> list:
    """The tracks a Spicy Lyrics document is held for, so only those are read.

    A directory listing instead of a request per track. Asking the API about
    all 1022 tracks in tracks.json to find the 34 with a community sync would
    be most of the running time of a `--against spicy` run, and all of it
    spent on songs already known to be somebody else's.
    """
    return LS.spicy_ids()


def songs(where: str, spicy_ref: bool, limit: int) -> list:
    """The tracks worth measuring, and which document is the reference.

    Read out of tracks.json either way, because a blend needs the title,
    artist and length to be fetched at all.
    """
    try:
        known = json.loads(
            (LS.cache_root() / "tracks.json").read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        known = {}
    if spicy_ref:
        have = set(cached_ids())
        known = {k: v for k, v in known.items() if k in have}
    out, seen = [], set()
    refs = {} if spicy_ref else ES.references(where)
    for tid, v in known.items():
        if not (v.get("title") and v.get("artist")):
            continue
        row = {"tid": tid, "title": v["title"], "artist": v["artist"],
               "length": float(v.get("length") or 0)}
        if spicy_ref:
            if ES.spicy_ref(ES.spicy(tid)) is None:
                continue
            row["ref"] = ""
        else:
            key = f"{LS._norm(v['title'])}\x00{LS._norm(v['artist'])}"
            if key not in refs or key in seen:
                continue
            seen.add(key)
            row["ref"] = refs[key][0]
        out.append(row)
        if limit and len(out) >= limit:
            break
    return sorted(out, key=lambda r: (r["artist"], r["title"]))


def reference(row: dict, got: dict, where: str):
    """The hand-timed document this track is scored against."""
    if not row["ref"]:
        return ES.spicy_ref(got.get("spicy"))
    try:
        return LS.parse_ttml((pathlib.Path(where) / row["ref"]).read_bytes())
    except Exception:                                    # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def base_of(got: dict, spicy_ref: bool):
    """The document a blend would lay its borrowed timings under.

    _blended's own rule: everything already in hand, best quality first, with
    Spicy Lyrics' copy leading the ties. Withheld where it is also the
    reference -- a blend keeps the base's own timings wherever the relay
    fails, so handing it the answer sheet measures no blend at all.
    """
    picks = [] if spicy_ref or not got.get("spicy") else \
        [(SL.payload(got["spicy"]), "spicy")]
    if got.get("apple"):
        picks.append((got["apple"], "apple"))
    picks = [p for p in picks if LS.quality(p[0]) != "none"]
    picks.sort(key=lambda p: LS.RANK.get(LS.quality(p[0]), 0), reverse=True)
    return picks[0] if picks else (None, "")


def build(got: dict, name: str, spicy_ref: bool):
    """One named blend, over the jar, exactly as the chain would hand it over."""
    base, origin = base_of(got, spicy_ref)
    if base is None:
        return None
    uses = LS.BLENDS[name]
    timing = uses[1]
    spare = uses[2] if len(uses) > 2 else None
    lead, fill = LS.in_order(
        base, (got.get(timing), WHOSE[timing], timing),
        (got.get(spare) if spare else None, WHOSE.get(spare, ""), spare or ""))
    out = LS._blend(base, LS.BASE_WORDS.get(origin, origin), lead[0],
                    None, origin, lead[1], fill[0], fill[1])
    return LS.stand_down(out, lead[0], base, lead[2])


def drawn(doc, name: str, fold: bool):
    """...through the shaping the player does before it draws anything."""
    return ES.drawn(doc, name, fold) if doc else None


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def paired(mine: list, theirs: list) -> dict:
    """Our line index -> the reference's, by text."""
    a = [LS._key(SL.line_text(i)) for i in mine]
    b = [LS._key(SL.line_text(i)) for i in theirs]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    got = {i + k: j + k for i, j, n in sm.get_matching_blocks()
           for k in range(n) if a[i + k]}
    got.update(LS._near_pairs(a, b, got))
    return got


def ends(mine: list, theirs: list, mate: dict) -> list:
    """Per line, how much longer we hold it lit than the reference does.

    The line's own length, not its end, so a song timed against a different
    master is not read as every line ending wrong: what is being asked is how
    long the line stays up, which is the thing a donor that cannot overlap
    gets wrong.
    """
    out = []
    for i, j in mate.items():
        at, done = SL.line_start(mine[i]), LS._line_end(mine[i])
        was, ended = SL.line_start(theirs[j]), LS._line_end(theirs[j])
        if all(isinstance(v, (int, float)) for v in (at, done, was, ended)):
            out.append((done - at) - (ended - was))
    return out


def twice(doc) -> list:
    """Voices the document draws twice: the same words over the same seconds.

    Read off the finished document rather than out of _blend, so it catches
    the duplicate however it got there -- a stray lifted into the margin, a
    bracket peeled twice, or two of our own lines given one donor's span.

    The same words, by _kin, and not merely words inside other words. _doubled
    inside _lift_strays can afford the looser test because what it is holding
    is a shout of two or three words and the question is whether the line
    already says them; counted over every pair of voices in a document, that
    test calls "you know" a duplicate of every line with "you know" in it.
    """
    said, out = [], []
    for n, line in enumerate(LS._items(SL.payload(doc or {}))):
        for key, at, until in spans_of(line):
            if not key:
                continue
            for other, i, s, e in said:
                if not LS._kin(key, other):
                    continue
                if min(until, e) - max(at, s) > SAME_VOICE:
                    out.append((i, n, key, at, until))
                    break
            said.append((key, n, at, until))
    return out


def asides_of(doc) -> list:
    """(words, start, end) for every backing group a document files."""
    out = []
    for line in LS._items(SL.payload(doc or {})):
        for g in (line.get("Background") or []):
            syls = (g or {}).get("Syllables") or []
            at, done = LS._group_span(g, syls)
            key = LS._key(SL.syllables_text(syls))
            if syls and key and isinstance(at, (int, float)):
                out.append((key, at, done if isinstance(done, (int, float)) else at))
    return out


def voiced(doc, key: str, at: float, until: float, slack: float = 2.5) -> str:
    """Whether the document sings these words around here, and as what."""
    for line in LS._items(SL.payload(doc or {})):
        for k, s, e in spans_of(line):
            if k and (LS._kin(key, k) or key in k) \
                    and min(until, e) - max(at, s) > -slack:
                return "bg" if k != LS._key(SL.line_text(line)) else "lead"
    return ""


def unsound(doc) -> dict:
    """Things no document should ever contain, whatever the sources said."""
    got = {"backwards": 0, "inverted": 0, "endless": 0, "unordered": 0}
    prev = None
    for line in LS._items(SL.payload(doc or {})):
        at, done = SL.line_start(line), LS._line_end(line)
        if not isinstance(at, (int, float)):
            continue
        if isinstance(done, (int, float)):
            got["inverted"] += done < at
            got["endless"] += done - at > 30
        got["backwards"] += prev is not None and at < prev - 0.001
        prev = at
        syls = (line.get("Lead") or {}).get("Syllables") or []
        got["unordered"] += sum(1 for a, b in zip(syls, syls[1:])
                                if b["StartTime"] < a["StartTime"] - 0.001)
    return got


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def measure(rows: list, names: list, where: str, spicy_ref: bool,
            fold: bool, loud: bool) -> dict:
    acc = {n: {"per": {}, "errs": [], "ends": [], "twice": 0, "adlib": [0, 0, 0],
               "who": [], "sound": {}, "lines": 0, "worded": 0}
           for n in names}
    for row in rows:
        got = held(row["tid"])
        ref = reference(row, got, where)
        if ref is None:
            continue
        theirs = EV.ours(ref)
        rit = LS._items(SL.payload(ref))
        want = asides_of(ref)
        said = f"  {row['artist'][:18]:18} {row['title'][:24]:24}"
        for name in names:
            doc = drawn(build(got, name, spicy_ref), name, fold)
            if not doc or LS.quality(doc) == "none":
                said += f" | {name}: -"
                continue
            a = acc[name]
            errs = EV.compare(EV.ours(doc), theirs)
            audit = ES.audit(doc)
            a["lines"] += audit["lines"]
            a["worded"] += audit["worded"]
            for i, j, *_ in twice(doc):
                a["twice"] += 1
                if loud:
                    print(f"      {name} draws lines {i} and {j} of "
                          f"{row['title'][:24]} at once")
            for key, at, until in want:
                where_it_is = voiced(doc, key, at, until)
                a["adlib"][0 if where_it_is == "bg" else
                           1 if where_it_is else 2] += 1
                if not where_it_is:
                    a["who"].append(sorted(
                        w for w in ("apple", "netease", "qq", "kugou")
                        if got.get(w) and voiced(got[w], key, at, until)))
            for k, v in unsound(doc).items():
                a["sound"][k] = a["sound"].get(k, 0) + v
            mine = ends(LS._items(SL.payload(doc)), rit,
                        paired(LS._items(SL.payload(doc)), rit))
            a["ends"] += mine
            if len(errs) < 12:
                said += f" | {name}: thin"
                continue
            shape = EV.shape(errs)
            a["errs"] += errs
            a["per"][row["tid"]] = {
                "name": f"{row['artist']} - {row['title']}",
                "words": len(errs), "median": shape["median"],
                "scatter": shape["scatter"], "worst": shape["worst"],
                "loose": sum(1 for e in errs
                             if abs(e - shape["median"]) > 0.5) / len(errs),
                "worded": audit["worded"], "lines": audit["lines"]}
            said += f" | {name}: {shape['median']:+.2f}/{shape['scatter']:.3f}"
        print(said)
    return acc


def say(acc: dict) -> None:
    for name, a in acc.items():
        per = list(a["per"].values())
        if not per:
            print(f"\n{name:12} nothing answered")
            continue
        loose = [r["loose"] for r in per]
        print(f"\n{name:12} {len(per)} songs, {sum(r['words'] for r in per)} words")
        print(f"    onsets     over half a second out of step with their own "
              f"song: median {statistics.median(loose):.2%}, "
              f"mean {statistics.mean(loose):.2%}   "
              f"scatter {statistics.median([r['scatter'] for r in per]):.3f}s")
        if a["ends"]:
            short = sum(1 for e in a["ends"] if e < -CUT_SHORT)
            print(f"    ends       {len(a['ends'])} lines   "
                  f"|median| {statistics.median([abs(e) for e in a['ends']]):.3f}s   "
                  f"cut short by {CUT_SHORT}s: {short / len(a['ends']):.1%}")
        bg, inside, gone = a["adlib"]
        if bg + inside + gone:
            nobody = sum(1 for w in a["who"] if not w)
            print(f"    voices     {a['twice']} drawn twice   "
                  f"{a['worded']}/{a['lines']} lines word-timed")
            print(f"    ad-libs    {bg} drawn as one, {inside} inside a line, "
                  f"{gone} missing -- {nobody} of those held by no source at all")
        bad = {k: v for k, v in a["sound"].items() if v}
        print(f"    soundness  {bad or 'clean'}")


def diff(before: str, after: str) -> None:
    """Two runs, song by song, so a change can be read where it landed."""
    was, now = (json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
                for p in (before, after))
    for name in was:
        rows = []
        old, new = was[name]["per"], now.get(name, {}).get("per", {})
        for tid in set(old) | set(new):
            a, b = old.get(tid), new.get(tid)
            if not a or not b:
                rows.append((9e9, f"  {(a or b)['name'][:42]:42} "
                                  f"{'no longer scored' if not b else 'newly scored'}"))
                continue
            moved = b["loose"] - a["loose"]
            if abs(moved) < 0.005 and a["worded"] == b["worded"]:
                continue
            rows.append((moved,
                         f"  {a['name'][:42]:42} loose {a['loose']:6.1%} -> "
                         f"{b['loose']:6.1%}   worded {a['worded']}->{b['worded']}"))
        if rows:
            print(f"== {name}")
            for _m, line in sorted(rows):
                print(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="?", default="score", choices=("score", "fetch"))
    ap.add_argument("--refs", default=str(pathlib.Path(__file__).resolve().parent.parent
                                          / "lyrics"))
    ap.add_argument("--against", choices=("refs", "spicy"), default="refs")
    ap.add_argument("--only", default="", help="which blends, comma separated")
    ap.add_argument("--songs", type=int, default=0, help="stop after this many")
    ap.add_argument("--json", default="", help="write the per-song rows here")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="compare two --json runs instead of measuring")
    ap.add_argument("--again", default="",
                    help="donors to re-fetch even though the jar has them")
    ap.add_argument("--loud", action="store_true",
                    help="name every voice drawn twice")
    args = ap.parse_args()

    if args.diff:
        diff(*args.diff)
        return 0

    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(LS.BLENDS)
    unknown = [n for n in names if n not in LS.BLENDS]
    if unknown:
        print(f"no such blend: {', '.join(unknown)}\n"
              f"there is: {' '.join(LS.BLENDS)}")
        return 2

    if args.against == "spicy" and not cached_ids():
        print("no Spicy Lyrics documents held on this machine, and that is "
              "where --against spicy takes its reference from. Play some "
              "songs, or ask for a few with mild-lyrics/spicy_lyrics.py get.")
        return 2

    rows = songs(args.refs, args.against == "spicy", args.songs)
    print(f"{len(rows)} songs with a reference"
          + ("" if args.against == "refs" else " from Spicy Lyrics"))
    if not rows:
        return 1
    if args.what == "fetch":
        fetch(rows, {w.strip() for w in args.again.split(",") if w.strip()})
        return 0

    missing = [r for r in rows if not slot(r["tid"], "apple").exists()]
    if missing:
        print(f"{len(missing)} of them are not in the jar yet -- run `fetch` first")
    _on, _order, fold = ES.settings()
    acc = measure(rows, names, args.refs, args.against == "spicy", fold, args.loud)
    say(acc)
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps({n: {"per": a["per"]} for n, a in acc.items()}, indent=1),
            encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
