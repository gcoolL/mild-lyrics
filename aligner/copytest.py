#!/usr/bin/env python3
"""Does a song's constant offset belong to the COPY, or to us?

    ./copytest.py [--songs 12]

Across 278 benchmarked songs, subtracting each song's own median error is worth
+19 points of words-inside-0.1s. On the 42 songs with tight scatter and a
modest offset, the shift that lands the reference on our own copy's onsets IS
that offset, 39 times out of 42 -- so the words are placed correctly against
the audio we were given, and the audio we were given is displaced against the
master the reference was made from.

That points at the fetch rather than the aligner, but it does not prove it. If
the offset belongs to the copy, a DIFFERENT upload of the same song should have
a different one. If it survives changing the copy, it is coming from somewhere
else and the conclusion above is incomplete.

So: for each displaced song, find another upload that matches the track length,
align against that instead, and compare. The original pin and the cached audio
are put back afterwards -- this measures, it does not decide anything for you.
"""
import argparse
import json
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
# Data lives beside the code's folder, not inside it.
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import bench                     # noqa: E402
import local_align as LA         # noqa: E402
import lyric_sources as LS       # noqa: E402
import ttml as T                 # noqa: E402

AUDIO = LS.cache_root() / "audio"
SOURCES = LS.cache_root() / "sources.json"


def displaced(want: int) -> list[tuple[str, float]]:
    """Songs the benchmark found locally tight but globally shifted."""
    out = []
    for p in (ROOT / "bench").glob("*.night.json"):
        r = json.loads(p.read_text())
        med = statistics.median(r["errors"])
        if r.get("scatter", 1) < 0.06 and 0.15 < abs(med) < 1.2:
            out.append((r["name"], med))
    out.sort(key=lambda x: -abs(x[1]))
    return out[:want]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--songs", type=int, default=12)
    args = ap.parse_args()

    pins = json.loads(SOURCES.read_text()) if SOURCES.exists() else {}
    cdp = T.spotify()
    known = T.index(cdp)
    bytid = {f"{m['artist']} - {m['title']}": (t, m) for t, m in known.items()}

    print(f"  {'song':38} {'was':>8} {'now':>8}  {'moved':>7}  uploader")
    moved, stayed = [], []
    for name, med in displaced(args.songs):
        if name not in bytid:
            continue
        tid, meta = bytid[name]
        old = pins.get(tid, "")
        try:
            cands = LA.find(f"{meta['artist']} {meta['title']}",
                            float(meta.get("length") or 0),
                            artist=meta.get("artist", ""))
        except Exception as exc:
            print(f"  {name[:38]:38} search failed: {exc}")
            continue
        alt = next((u for u, _d in cands if u != old), None)
        if not alt:
            print(f"  {name[:38]:38} no other upload of the right length")
            continue

        wav = AUDIO / f"{tid}.wav"
        keep = wav.read_bytes() if wav.exists() else None
        try:
            LS.pin_source(tid, alt)
            if wav.exists():
                wav.unlink()
            row = bench.measure(cdp, name, "altcopy", meta=dict(meta, uri="spotify:track:" + tid),
                                spare=0.4, verify=False)
        finally:
            # Put it back exactly as it was, whatever happened above. This is
            # an experiment, not a change of copy.
            LS.pin_source(tid, old)
            if wav.exists():
                wav.unlink()
            if keep is not None:
                wav.write_bytes(keep)
        if not row:
            continue
        new = statistics.median(row["errors"])
        shift = abs(new - med)
        (moved if shift > 0.05 else stayed).append((name, med, new))
        print(f"  {name[:38]:38} {med:+8.3f} {new:+8.3f}  {shift:7.3f}  {alt[-11:]}")

    n = len(moved) + len(stayed)
    if n:
        print(f"\n  {n} songs re-aligned against a different upload")
        print(f"    the offset MOVED on {len(moved)}, stayed on {len(stayed)}")
        if moved:
            better = sum(1 for _n, o, w in moved if abs(w) < abs(o))
            print(f"    of the {len(moved)} that moved, {better} landed closer to zero")
        print("\n  moved -> the offset belongs to the copy, and choosing copies "
              "better is the fix.\n  stayed -> it does not, and task 20's "
              "conclusion is incomplete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
