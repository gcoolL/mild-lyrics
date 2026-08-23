"""Add per-word timing bounds to an existing sync dataset manifest.

Standalone on purpose: this file does not import the `sync` package, because
running from the sync/ directory makes that name collide with sync.py.
It does not download audio or recut clips.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
ALIGNER = ROOT / "aligner"
sys.path.insert(0, str(ALIGNER))

import lyric_sources as LS  # noqa: E402

HOME = pathlib.Path.home() / ".cache/mild-lyrics/sync"
SNAP = HOME / "spl"

# WHICH dataset, and cut with WHICH padding. Both are arguments because there
# are two datasets on this disk and they were cut differently: the mixture set
# under sync/ with 0.25s of room, and the older separated-vocal set beside it
# with 0.15s. Getting that wrong does not fail -- it writes bounds that are all
# 0.10s out, which then teaches the boundary head to be 0.10s out.
#
#     python3 sync/migrate_bounds.py [dataset-dir] [pad]
DATA = pathlib.Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else HOME / "dataset"
PAD = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25
MANIFEST = DATA / "manifest.jsonl"
BACKUP = DATA / "manifest.before-bounds.jsonl"


def snapshot_docs() -> dict:
    out = {}
    for path in sorted(SNAP.glob("*.json")):
        try:
            out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return out


def timed_lines(doc: dict) -> list[dict]:
    """Recover the word start/end timings from the frozen SPL document."""
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
                if (
                    word.strip()
                    and isinstance(word_start, float)
                    and isinstance(word_end, float)
                ):
                    words.append({
                        "text": word.strip(),
                        "start": word_start,
                        "end": word_end,
                    })
                word = ""
                word_start = word_end = None

        if (
            word.strip()
            and isinstance(word_start, float)
            and isinstance(word_end, float)
        ):
            words.append({
                "text": word.strip(),
                "start": word_start,
                "end": word_end,
            })

        if words:
            out.append({
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": " ".join(w["text"] for w in words),
                "words": words,
            })

    return out


def main() -> int:
    if not MANIFEST.exists():
        raise SystemExit(f"no manifest at {MANIFEST}")

    original = MANIFEST.read_text(encoding="utf-8")

    if not BACKUP.exists():
        BACKUP.write_text(original, encoding="utf-8")

    docs = snapshot_docs()
    output = []

    updated = 0
    already = 0
    skipped = 0
    clips_updated = 0

    for raw in original.splitlines():
        try:
            row = json.loads(raw)
        except Exception:
            output.append(raw)
            skipped += 1
            continue

        entries = row.get("lines") or []

        if entries and all(entry.get("bounds") for entry in entries):
            output.append(json.dumps(row, ensure_ascii=False))
            already += 1
            continue

        tid = row.get("tid")
        doc = docs.get(tid)

        if not doc:
            output.append(json.dumps(row, ensure_ascii=False))
            skipped += 1
            continue

        source_lines = timed_lines(doc)
        lag = float(row.get("lag") or 0.0)
        song_changed = False

        for entry in entries:
            match = re.search(r"_(\d{4})\.npy$", str(entry.get("clip") or ""))
            if not match:
                continue

            line_index = int(match.group(1))
            if line_index >= len(source_lines):
                continue

            source = source_lines[line_index]

            # Must match the same clip-start calculation used by dataset.py.
            clip_start = max(
                0.0,
                float(source["start"]) + lag - PAD,
            )

            bounds = [
                [
                    round(float(word["start"]) + lag - clip_start, 3),
                    round(float(word["end"]) + lag - clip_start, 3),
                ]
                for word in source["words"]
            ]

            # Refuse silently-corrupting a row if word counts don't line up.
            manifest_words = str(entry.get("text") or "").split()
            if len(bounds) != len(manifest_words):
                continue

            entry["bounds"] = bounds
            clips_updated += 1
            song_changed = True

        if song_changed:
            updated += 1
        else:
            skipped += 1

        output.append(json.dumps(row, ensure_ascii=False))

    MANIFEST.write_text("\n".join(output) + "\n", encoding="utf-8")

    print(f"manifest: {MANIFEST}")
    print(f"backup:   {BACKUP}")
    print(f"updated:  {updated} song(s)")
    print(f"bounds:   {clips_updated} clip(s)")
    print(f"already:  {already} song(s)")
    print(f"skipped:  {skipped} song(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
