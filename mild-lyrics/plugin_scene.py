"""Plugin renderers (plugin API 4): a plugin hands over the song as timed
pages and the window lays them out and wipes them with the clock, so the
plugin sends nothing per frame. Checked here; renderers.PluginScene draws."""

from __future__ import annotations

import math
import re

NAME_RE = re.compile(r"[^\x00-\x1f\x7f]{1,40}")
COLOUR_RE = re.compile(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?")
MAX_RENDERERS = 3
MAX_PAGES = 4000
MAX_LINES = 24              # on one page
MAX_FRAGS = 400             # in one line
MAX_TOTAL = 60000           # fragments in the whole scene
MAX_TEXT = 300
ALIGNS = ("centre", "left", "right")
WEIGHTS = range(100, 1000, 100)


def names(m: dict) -> list[str]:
    """The renderers a plugin.json declares, checked."""
    raw = m.get("renderers") or []
    if not isinstance(raw, list) or len(raw) > MAX_RENDERERS:
        raise ValueError(f"renderers is a list of at most {MAX_RENDERERS} names")
    out: list[str] = []
    for n in raw:
        if (not isinstance(n, str) or not NAME_RE.fullmatch(n)
                or n != n.strip() or n in out):
            raise ValueError(f"renderer name {str(n)[:40]!r} is bad or repeated")
        out.append(n)
    return out


def _num(d: dict, key: str, lo: float, hi: float, default):
    v = d.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{key} is not a number")
    return min(hi, max(lo, float(v)))


def _time(d: dict, key: str):
    v = d.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{key} is not a time")
    return min(86400.0, max(-60.0, float(v)))


def _colour(d: dict, key: str, default):
    v = d.get(key)
    if v is None:
        return default
    if not isinstance(v, str) or not COLOUR_RE.fullmatch(v):
        raise ValueError(f"{key} is a colour like #rrggbb or #rrggbbaa")
    return v


def _weight(d: dict, key: str, default):
    v = d.get(key)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int) or v not in WEIGHTS:
        raise ValueError(f"{key} is 100, 200 ... 900")
    return v


def _line(d, count: list) -> dict:
    if not isinstance(d, dict):
        raise ValueError("a line is an object")
    frags = d.get("frags")
    if frags is None:
        frags = [{"text": d.get("text", "")}]
    if not isinstance(frags, list) or len(frags) > MAX_FRAGS:
        raise ValueError(f"frags is a list of at most {MAX_FRAGS}")
    count[0] += len(frags)
    if count[0] > MAX_TOTAL:
        raise ValueError(f"a scene holds at most {MAX_TOTAL} fragments")
    pieces = []
    for f in frags:
        if not isinstance(f, dict):
            raise ValueError("a fragment is an object")
        text = f.get("text")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError(f"a fragment's text is a string of at most {MAX_TEXT}")
        s, e = _time(f, "start"), _time(f, "end")
        if s is None:
            e = None
        elif e is None or e < s:
            e = s
        if s is None:
            # Untimed text wraps between its words, never inside one.
            words = text.split()
            joined = bool(f.get("joined")) and not text[-1:].isspace()
            pieces += [(None, None, w, joined and n == len(words) - 1)
                       for n, w in enumerate(words)]
        elif text.strip():
            pieces.append((s, e, text, bool(f.get("joined"))))
    start, end = _time(d, "start"), _time(d, "end")
    if start is None or end is None or end < start:
        start = end = None
    return {"pieces": pieces, "start": start, "end": end,
            "ink": _colour(d, "ink", None), "sung": _colour(d, "sung", None),
            "size": _num(d, "size", 0.2, 4.0, 1.0),
            "weight": _weight(d, "weight", None)}


def check(data) -> dict | None:
    """api.renderer()'s scene, checked; None takes it away. Raises
    ValueError saying what is wrong."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("a scene is an object")
    tid = data.get("tid")
    if not isinstance(tid, str) or not tid or len(tid) > 300:
        raise ValueError("a scene names the track it is for: tid, from api.lyrics()")
    font = data.get("font") or {}
    if not isinstance(font, dict):
        raise ValueError("font is an object")
    families = font.get("families") or []
    if (not isinstance(families, list) or len(families) > 8
            or not all(isinstance(f, str) and 0 < len(f) <= 64 for f in families)):
        raise ValueError("font.families is a list of at most 8 names")
    align = data.get("align", "centre")
    if align not in ALIGNS:
        raise ValueError(f"align is one of {', '.join(ALIGNS)}")
    pages = data.get("pages") or []
    if not isinstance(pages, list) or len(pages) > MAX_PAGES:
        raise ValueError(f"pages is a list of at most {MAX_PAGES}")
    count = [0]
    out = []
    for pg in pages:
        if not isinstance(pg, dict):
            raise ValueError("a page is an object")
        at, to = _time(pg, "from"), _time(pg, "to")
        if at is None or (to is not None and to < at):
            raise ValueError("a page needs from, and a to not before it")
        lines = pg.get("lines")
        if not isinstance(lines, list) or len(lines) > MAX_LINES:
            raise ValueError(f"a page's lines is a list of at most {MAX_LINES}")
        out.append({"from": at, "to": to, "fade": _num(pg, "fade", 0.0, 5.0, None),
                    "spacing": _num(pg, "spacing", 1.0, 4.0, None),
                    "lines": [_line(ln, count) for ln in lines]})
    out.sort(key=lambda pg: pg["from"])
    return {"tid": tid, "background": _colour(data, "background", None),
            "ink": _colour(data, "ink", "#ffffff"),
            "sung": _colour(data, "sung", "#5888f8"),
            "families": families,
            "weight": _weight(font, "weight", None),
            "size": _num(font, "size", 0.2, 4.0, 1.0),
            "spacing": _num(data, "spacing", 1.0, 4.0, 1.3),
            "fade": _num(data, "fade", 0.0, 5.0, 0.25),
            "align": align, "pages": out, "flow": _flow(data.get("flow"), count)}


def _flow(d, count: list) -> dict | None:
    """Lines the window pages itself once it knows how they wrap: `rows`
    rows a page, a new page after a gap of `break` seconds."""
    if d is None:
        return None
    if not isinstance(d, dict):
        raise ValueError("flow is an object")
    lines = d.get("lines")
    if not isinstance(lines, list) or len(lines) > MAX_PAGES:
        raise ValueError(f"flow.lines is a list of at most {MAX_PAGES}")
    rows = d.get("rows", 4)
    if isinstance(rows, bool) or not isinstance(rows, int) or not 1 <= rows <= 12:
        raise ValueError("flow.rows is a whole number, 1 to 12")
    out = []
    for ln in lines:
        got = _line(ln, count)
        got["new_page"] = bool(ln.get("new_page"))
        times = [t for pc in got["pieces"] for t in pc[:2] if t is not None]
        times += [t for t in (got["start"], got["end"]) if t is not None]
        if not times:
            raise ValueError("a flow line needs times: frags with start, or start and end")
        got["first"], got["last"] = min(times), max(times)
        out.append(got)
    return {"rows": rows, "lines": out,
            "break": _num(d, "break", 0.0, 120.0, 6.0),
            "lead": _num(d, "lead", 0.0, 60.0, 3.0),
            "hold": _num(d, "hold", 0.0, 120.0, 2.0),
            "spacing": _num(d, "spacing", 1.0, 4.0, None),
            "first_fade": _num(d, "first_fade", 0.0, 5.0, None)}
