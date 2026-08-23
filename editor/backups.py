"""Copies of work, kept without being asked.

A lyric is hours of listening. It should not be possible to lose one to a
keystroke, a stale path or a fetch into the wrong window -- and it was: a
document replaced in the editor was simply gone, and a file written over was
gone with it.

So two nets, both silent:

  * before anything is written over, the file that was there is copied here;
  * while there is unsaved work, it is written here every half minute, and
    whenever it is about to be replaced by something else.

Kept beside the player's own cache, capped, and never in the way. Nothing
here is a substitute for saving -- it is what is left when saving did not
happen, or happened to the wrong file.
"""
from __future__ import annotations

import pathlib
import re
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "aligner", _HERE.parent)
                if str(p) not in sys.path]

KEEP = 60


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
    try:
        files = sorted(root.glob("*.ttml"), key=lambda f: f.stat().st_mtime)
        for gone in files[:-KEEP]:
            gone.unlink(missing_ok=True)
    except Exception:
        pass


def entries() -> list[dict]:
    """Everything kept, newest first."""
    from . import model as M
    out = []
    root = home()
    if not root.exists():
        return out
    for f in sorted(root.glob("*.ttml"), key=lambda f: -f.stat().st_mtime):
        got = {"path": f, "when": f.stat().st_mtime, "lines": 0, "timed": 0,
               "name": f.stem, "why": "", "first": ""}
        bits = f.stem.split("-", 3)
        if len(bits) >= 4:
            got["why"], got["name"] = bits[2], bits[3]
        try:
            doc = M.from_ttml(f.read_text(encoding="utf-8", errors="replace"))
            if doc:
                got["lines"] = len(doc.lines)
                got["timed"] = doc.timed_lines()
                got["first"] = doc.lines[0].text()[:44] if doc.lines else ""
        except Exception:
            pass
        out.append(got)
    return out
