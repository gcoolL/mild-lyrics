"""Copies of work, kept without being asked.

A lyric is hours of listening. It should not be possible to lose one to a
keystroke, a stale path or a fetch into the wrong window -- and it was: a
document replaced in the editor was simply gone, and a file written over was
gone with it.

So two nets, both silent:

  * before anything is written over, the file that was there is copied here;
  * while there is unsaved work, it is written here every half minute, and
    whenever it is about to be replaced by something else.

Kept beside the player's own cache, for two weeks, and never in the way. Nothing
here is a substitute for saving -- it is what is left when saving did not
happen, or happened to the wrong file.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "mild-lyrics", _HERE.parent)
                if str(p) not in sys.path]

KEEP_DAYS = 14
INDEX = "index.json"
PRUNE_EVERY = 3600.0
_PRUNED = [0.0]


def home() -> pathlib.Path:
    import lyrics_gui as L
    return L.app_dir("cache") / "editor-history"


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()[:80] or "lyric"


def stash(doc, name: str, why: str) -> pathlib.Path | None:
    """Keep a copy of `doc`. Returns where it went, or None.

    Never raises: this runs on the way past something more important, and a
    backup that fails must not take the edit with it.
    """
    from . import model as M
    try:
        if not doc or not doc.lines:
            return None
        root = home()
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        where = root / f"{stamp}-{_safe(why)}-{_safe(name)}.ttml"
        where.write_text(M.to_ttml(doc) + "\n", encoding="utf-8")
        _note(root, where, doc)
        prune(root)
        return where
    except Exception:
        return None


def keep_copy(path) -> pathlib.Path | None:
    """Copy a file that is about to be written over."""
    try:
        path = pathlib.Path(path)
        if not path.exists() or path.stat().st_size < 16:
            return None
        root = home()
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        where = root / f"{stamp}-replaced-{_safe(path.stem)}.ttml"
        where.write_bytes(path.read_bytes())
        prune(root)
        return where
    except Exception:
        return None


def prune(root: pathlib.Path) -> None:
    """Let go of what is past KEEP_DAYS -- at most once an hour, because it
    lists and stats every copy kept and a copy is written every half minute."""
    now = time.time()
    if now - _PRUNED[0] < PRUNE_EVERY:
        return
    _PRUNED[0] = now
    try:
        cutoff = now - KEEP_DAYS * 86400
        for f in root.glob("*.ttml"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except Exception:
        pass


def _index(root: pathlib.Path) -> dict:
    """What is known about each copy without opening it: {file name:
    [mtime_ns, size, lines, timed, first line]}.

    Reading them back means parsing every one -- 21ms for a 91KB copy, so
    about six seconds for three hundred, all on the thread the window draws
    on. A copy is never changed once it is written, so what was seen of it
    then is what it is: written when the copy is, and worked out once for
    any that predate it.
    """
    try:
        got = json.loads((root / INDEX).read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}


def _save_index(root: pathlib.Path, got: dict) -> None:
    try:
        (root / INDEX).write_text(json.dumps(got), encoding="utf-8")
    except Exception:
        pass


def _row(f: pathlib.Path, doc) -> list:
    st = f.stat()
    return [st.st_mtime_ns, st.st_size, len(doc.lines), doc.timed_lines(),
            doc.lines[0].text()[:44] if doc.lines else ""]


def _note(root: pathlib.Path, where: pathlib.Path, doc) -> None:
    got = _index(root)
    got[where.name] = _row(where, doc)
    _save_index(root, got)


def entries() -> list[dict]:
    """Everything kept, newest first."""
    from . import model as M
    out = []
    root = home()
    if not root.exists():
        return out
    known, seen, fresh = _index(root), {}, False
    for f in sorted(root.glob("*.ttml"), key=lambda f: -f.stat().st_mtime):
        st = f.stat()
        got = {"path": f, "when": st.st_mtime, "lines": 0, "timed": 0,
               "name": f.stem, "why": "", "first": ""}
        bits = f.stem.split("-", 3)
        if len(bits) >= 4:
            got["why"], got["name"] = bits[2], bits[3]
        row = known.get(f.name)
        if not (isinstance(row, list) and len(row) == 5
                and row[0] == st.st_mtime_ns and row[1] == st.st_size):
            row = None
            try:
                doc = M.from_ttml(f.read_text(encoding="utf-8", errors="replace"))
                if doc:
                    row = _row(f, doc)
            except Exception:
                pass
            fresh = fresh or row is not None
        if row:
            got["lines"], got["timed"], got["first"] = row[2], row[3], row[4]
            seen[f.name] = row
        out.append(got)
    if fresh or len(seen) != len(known):
        _save_index(root, seen)
    return out
