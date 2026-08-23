#!/usr/bin/env python3
"""Try a hundred onset settings on a song already aligned, without a GPU.

    ./bench.py bipolar showstopper          once, to lay down bench/*.raw.json
    ./sweep.py                              then as often as you like

Everything after the emissions is arithmetic: pick peaks out of the flux, walk
each one back down its rise, move word starts onto them. None of it needs the
card, and the card is usually busy with something that does. So the flux, the
word starts CTC produced, and the reference are kept by bench.py, and this
replays the last stage over a grid.

It checks itself first. The shipping settings are replayed and compared with
what bench.py measured for real; if the two disagree the grid is meaningless
and it says so rather than handing back a best-looking number.
"""
import argparse
import itertools
import json
import pathlib
import statistics
import sys
from difflib import SequenceMatcher

HERE = pathlib.Path(__file__).resolve().parent
# Data lives beside the code's folder, not inside it.
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import local_align as LA        # noqa: E402

OUT = ROOT / "bench"


def peaks(flux: list[float], step: float, near: int, over: float,
          back: int) -> list[float]:
    """The same peak-picking _onsets does, on flux already computed."""
    import torch
    f = torch.tensor(flux)
    local = torch.nn.functional.avg_pool1d(
        f[None, None], kernel_size=2 * near + 1, stride=1, padding=near)[0, 0]
    strong = f > local * over
    peak = (f[1:-1] > f[:-2]) & (f[1:-1] >= f[2:]) & strong[1:-1]
    out = []
    for i in torch.nonzero(peak).flatten().tolist():
        k = i + 1
        for _ in range(back):
            if k <= 0 or flux[k - 1] >= flux[k]:
                break
            k -= 1
        out.append(k * step)
    return out


def snap(before: list, marks: list[float], window: float, forward: float,
         doubt: float, late: float, lead_kept: bool) -> list[tuple[str, float]]:
    """_snap, parameterised, returning (word, start) rather than mutating."""
    out, floor, at = [], -1.0, 0
    back, fwd = window, window * forward
    # Rows carry a CTC score too, on runs recorded since that was added.
    for word, start, end, *_rest in before:
        if not marks:
            out.append((word, start))
            continue
        while at < len(marks) - 1 and marks[at] < start - back:
            at += 1
        aim = start - late
        best, gap = None, None
        for k in range(at, len(marks)):
            if marks[k] > start + fwd:
                break
            if marks[k] <= floor or marks[k] >= end:
                continue
            d = aim - marks[k]
            d = -d * doubt if d < 0 else d
            if gap is None or d < gap:
                best, gap = marks[k], d
        if best is not None:
            start = round(best, 3)
        elif lead_kept:
            start = round(max(floor, start - late), 3)
        floor = start
        out.append((word, start))
    return out


def errors(mine, ref) -> list[float]:
    a = [LA._flat(w) for w, _t in mine]
    b = [LA._flat(w) for w, _t in ref]
    out = []
    for i, j, n in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(n):
            if a[i + k]:
                out.append(mine[i + k][1] - ref[j + k][1])
    return out


def hit(errs: list[float], under: float = 0.1) -> float:
    return sum(1 for e in errs if abs(e) < under) / max(1, len(errs))


def run(raw: dict, near, over, back, window, forward, doubt, late,
        lead_kept) -> list[float]:
    marks = peaks(raw["flux"], raw["step"], near, over, back)
    marks = [t + raw["offset"] for t in marks]
    got = snap(raw["before"], marks, window, forward, doubt, late, lead_kept)
    return errors(got, [(w, t) for w, t in raw["ref"]])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--under", type=float, default=0.1)
    args = ap.parse_args()

    raws = [json.loads(p.read_text()) for p in sorted(OUT.glob("*.raw.json"))]
    if not raws:
        print("  no bench/*.raw.json — run ./bench.py first")
        return 1
    print(f"  {len(raws)} song(s): " + ", ".join(r["name"] for r in raws))

    # Self-check. If replaying the shipping settings does not reproduce what
    # was measured on the card, the flux or the word starts were not captured
    # faithfully and every number below is fiction.
    print("\n  replaying the shipping settings:")
    ok = True
    for r in raws:
        errs = run(r, LA.ONSET_NEAR, LA.ONSET_OVER, LA.ONSET_BACK,
                   LA.ONSET_WINDOW, LA.ONSET_FORWARD, LA.ONSET_DOUBT,
                   LA.ONSET_LATE, LA.ONSET_LEAD_KEPT)
        print(f"    {r['name'][:38]:38} {len(errs):4} words  "
              f"within {args.under}s {hit(errs, args.under):.0%}  "
              f"median {statistics.median(errs):+.3f}")
        if len(errs) < 20:
            ok = False
    if not ok:
        print("  too few words matched — not sweeping")
        return 1

    grid = {"near": [15, 25, 40], "over": [1.2, 1.4, 1.7],
            "back": [0, 3, 5, 8, 12], "window": [0.08, 0.12, 0.18],
            "forward": [0.2, 0.4], "doubt": [1.5, 2.0, 3.0],
            "late": [0.03, 0.05, 0.06, 0.08], "lead_kept": [False, True]}
    keys = list(grid)
    rows = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        how = dict(zip(keys, combo))
        per, every = [], []
        for r in raws:
            errs = run(r, how["near"], how["over"], how["back"], how["window"],
                       how["forward"], how["doubt"], how["late"],
                       how["lead_kept"])
            per.append(hit(errs, args.under))
            every.extend(errs)
        # Ranked on the WORST song, not the pooled average: a setting that
        # wins by helping the long song while hurting the short one is not an
        # improvement to the aligner, it is an improvement to the average.
        rows.append((min(per), sum(per) / len(per), per, how, len(every)))
    rows.sort(key=lambda x: (-x[0], -x[1]))

    print(f"\n  {len(rows)} settings tried, best by worst-song "
          f"within {args.under}s:\n")
    for worst, mean, per, how, n in rows[:args.top]:
        print(f"    worst {worst:.0%}  mean {mean:.0%}  "
              + " ".join(f"{p:.0%}" for p in per) + "   "
              + " ".join(f"{k}={v}" for k, v in how.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
