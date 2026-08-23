"""Time every snapshotted lyric, and say which of them to distrust.

WHY A REPORT AND NOT JUST FILES. Three hundred TTMLs of unknown quality is not
better than none: somebody still has to listen to all of them to find the four
that are wrong. So every song is scored as it is written, on things that can be
measured without a reference, and the worst come out at the top of a list.

WHAT CAN BE MEASURED WITHOUT A REFERENCE:

  sure      the median confidence the model had in the words it placed. Low
            means it could not hear the singing -- or, on a language it was
            never trained on, that it could not spell it. Dutch reads 0.14-0.16
            with perfectly good timing, so this number is a symptom, not a
            verdict.
  onset     the share of word starts that land on a measured sung attack. This
            one is language-free: it asks the audio, not the alphabet.
  rushed    the share of words shorter than 60 ms. Across 27,736 words timed by
            hand, 0.12% are that short. A file with several per cent of them
            has a line that was squeezed to reach an anchor it was sure of.
  apart     how far the copy fetched is from the length of the track the file
            will be played over. Not decisive -- one song differed by an entire
            intro tag with the durations matching to 0.08s -- but when it is
            large the file is timed against a different edit.

The report is ordered by the ones worth a listen first.
"""
from __future__ import annotations

import json
import pathlib
import time

from . import audio, dataset, generate, vocal

HOME = pathlib.Path.home() / ".cache/mild-lyrics/sync"


def _safe(name: str) -> str:
    return "".join(c for c in name if c not in '/\\:*?"<>|').strip() or "song"


def _quality(doc: dict, rows: list[dict] | None = None) -> dict:
    """What can be said about a finished document without a reference."""
    import lyric_sources as LS
    spans = []
    for item in LS._items(doc):
        for part in ([item.get("Lead")] +
                     (item.get("Background") if isinstance(
                         item.get("Background"), list) else [])):
            if isinstance(part, dict):
                spans += [(float(s["StartTime"]), float(s["EndTime"]))
                          for s in (part.get("Syllables") or [])]
    if not spans:
        return {"words": 0, "rushed": 1.0}
    quick = sum(1 for a, b in spans if 0 < b - a < 0.06)
    return {"words": len(spans), "rushed": round(quick / len(spans), 4)}


def run(ckpt=None, out="lyrics/library", limit: int = 0, device: str = "cuda",
        stem: bool | None = True, spare: float = 0.4, redo: bool = False,
        gate: float | None = None, attack: float | None = None) -> int:
    """Write a TTML for every snapshotted lyric, and a report beside them."""
    where = pathlib.Path(out).expanduser()
    where.mkdir(parents=True, exist_ok=True)
    tracks = dataset._tracks()
    have = dataset.snapshots(dataset.SNAP)
    todo = [(tid, tracks[tid]) for tid in have if tid in tracks]
    todo.sort(key=lambda x: f"{x[1].get('artist','')} {x[1].get('title','')}")
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} snapshotted song(s) to time, writing to {where}")

    kept = where / "report.json"
    done = json.loads(kept.read_text()) if kept.exists() and not redo else {}
    import spicy_lyrics as SL
    taken: dict[str, str] = {}
    for n, (tid, meta) in enumerate(todo, 1):
        name = f"{meta.get('artist','')} - {meta.get('title','')}"
        # A track id in the name when two entries share one. The same song sits
        # in the cache under several ids -- different releases of it -- and
        # writing them all to one filename means the file on disk is whichever
        # happened to be timed last, against whichever master. Viva La Vida had
        # seven of them.
        file = where / f"{_safe(name)}.ttml"
        if taken.get(_safe(name), tid) != tid:
            file = where / f"{_safe(name)} [{tid[:6]}].ttml"
        taken.setdefault(_safe(name), tid)
        if tid in done and file.exists() and not redo:
            continue
        t0 = time.monotonic()
        try:
            doc = generate.make(meta, tid, ckpt, device=device, stem=stem,
                                spare=spare, any_source=False,
                                gate=gate, attack=attack, log=lambda m: None)
        except SystemExit as exc:
            print(f"  {n:3}/{len(todo)} {name[:44]:46} skipped — {str(exc)[:40]}")
            done[tid] = {"name": name, "why": str(exc)[:80]}
            kept.write_text(json.dumps(done, indent=1), encoding="utf-8")
            continue
        except Exception as exc:                      # noqa: BLE001
            print(f"  {n:3}/{len(todo)} {name[:44]:46} FAILED — "
                  f"{type(exc).__name__}: {str(exc)[:40]}")
            continue
        file.write_text(SL.render(doc, "ttml") + "\n", encoding="utf-8")
        placed, total = doc.get("_placed", (0, 0))
        got = _quality(doc)
        got.update(name=name, placed=placed, total=total,
                   apart=(doc.get("TimedAgainst") or {}).get("apart", 0.0),
                   secs=round(time.monotonic() - t0, 1))
        done[tid] = got
        kept.write_text(json.dumps(done, indent=1), encoding="utf-8")
        print(f"  {n:3}/{len(todo)} {name[:44]:46} {placed}/{total} words, "
              f"rushed {got['rushed']*100:.1f}%, {got['secs']:.0f}s")
    _report(done, where)
    return 0


def _report(done: dict, where: pathlib.Path) -> None:
    """The worklist: worst first, by what can be measured."""
    rows = [r for r in done.values() if r.get("words")]
    if not rows:
        return
    def worry(r):
        # Ordered by how likely the file is to be wrong, not by any one number.
        miss = 1.0 - (r.get("placed", 0) / max(1, r.get("total", 1)))
        return -(r.get("rushed", 0) * 3 + miss * 2 + min(abs(r.get("apart", 0)), 3) / 3)
    rows.sort(key=worry)
    lines = [f"# the library, timed — {time.strftime('%Y-%m-%d %H:%M')}", "",
             f"{len(rows)} song(s) written. Worst first: `rushed` is the share "
             f"of words under 60 ms (0.12% of hand-timed words are), `apart` is "
             f"how far the copy sits from the track it will be played over.", "",
             "| song | words | placed | rushed | apart |", "|---|---|---|---|---|"]
    for r in rows[:60]:
        lines.append(f"| {r['name']} | {r['words']} | "
                     f"{r.get('placed',0)}/{r.get('total',0)} | "
                     f"{r.get('rushed',0)*100:.1f}% | {r.get('apart',0):+.2f}s |")
    skipped = [r for r in done.values() if r.get("why")]
    if skipped:
        lines += ["", "## not written", ""]
        lines += [f"- {r['name']} — {r['why']}" for r in skipped[:40]]
    (where / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  report at {where / 'report.md'}")
