"""YouTube's captions for a video playing here, and the lyrics moved onto that video's clock.

The words and their timing stay the chosen source's; the captions only say where each stretch
of the song sits in the video (an intro, a skit, a cut). Notes: docs/notes/mild-lyrics/yt_captions.md.
"""
from __future__ import annotations

import copy
import json
import pathlib
import re
import statistics
import threading
import time
import urllib.request

import spicy_lyrics as SL

LINKS: dict = {}          # video id -> {"uploaded": url, "auto": url}, as the resolver's yt-dlp call saw them
KEEP_FOR = 7 * 86400      # a video's captions, or that it has none, kept this long
TOL = 1.0                 # an anchor this close to a stretch's shift belongs to it
JUMP = 3.0                # what a change of shift costs the chain, in anchors
MIN_WEIGHT = 4            # a stretch needs this much behind it: a caption word counts 1, a subtitle line 2
SHIFT_MIN = 0.5           # every stretch nearer than this: the video already runs on the lyrics' clock
                          # (uploaded subtitles lead by ~0.2s, so smaller is their habit, not a cut)
NOISE = re.compile(r"\[[^\]]*\]|\([^)]*\b(?:music|applause|laugh\w*|sound\w*|cheer\w*|instrumental|"
                   r"silence|singing|vocali\w*|humming)\b[^)]*\)|♪|>>", re.I)
_lock = threading.Lock()


def tokens(text: str) -> list[str]:
    """Words as both sides are compared: lower case, no apostrophes, "drinkin'" as "drinking"."""
    words = re.findall(r"[^\W_]+", re.sub(r"['’‘ʼ`]", "", (text or "").lower()))
    return [w + "g" if len(w) > 4 and w.endswith("in") else w for w in words]


# ------------------------------------------------------------ captions
def links_of(info: dict) -> dict:
    """The json3 links of a yt-dlp info's own-language uploaded subtitles and automatic captions."""
    lang = (info.get("language") or "").split("-")[0].lower()

    def pick(tracks: dict, auto: bool) -> str:
        keys = [k for k in (tracks or {}) if k != "live_chat"]
        if auto:                     # the recogniser's own track, never one machine-translated from it
            keys = [k for k in keys if k.endswith("-orig")] or [k for k in keys if k in (lang, "en")]
        if not keys:
            return ""
        keys.sort(key=lambda k: (k.split("-")[0].lower() != lang if lang else False,
                                 k.split("-")[0].lower() != "en"))
        return next((f.get("url") or "" for f in tracks[keys[0]] if f.get("ext") == "json3"), "")
    return {"uploaded": pick(info.get("subtitles"), False),
            "auto": pick(info.get("automatic_captions"), True)}


def _json(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception:                                    # noqa: BLE001
        return None


def _words(j: dict) -> list:
    """Automatic captions as [[seconds, word]], one per recognised word."""
    out = []
    for e in (j or {}).get("events") or []:
        t0 = e.get("tStartMs") or 0
        for s in e.get("segs") or []:
            for w in tokens(NOISE.sub(" ", s.get("utf8") or "")):
                out.append([round((t0 + (s.get("tOffsetMs") or 0)) / 1000.0, 3), w])
    return out


def _lines(j: dict) -> list:
    """Uploaded subtitles as [[start, end, words]], ♪ and sound descriptions gone."""
    out = []
    for e in (j or {}).get("events") or []:
        words = tokens(NOISE.sub(" ", "".join(s.get("utf8") or "" for s in e.get("segs") or [])))
        if words:
            t0 = (e.get("tStartMs") or 0) / 1000.0
            out.append([round(t0, 3), round(t0 + (e.get("dDurationMs") or 0) / 1000.0, 3), " ".join(words)])
    return out


def captions(vid: str, cache: pathlib.Path) -> dict:
    """{"words": automatic captions, "lines": uploaded subtitles} for a video; kept on disk."""
    path = cache / f"{vid}.json"
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(got.get("at") or 0) < KEEP_FOR:
            return got
    except Exception:                                    # noqa: BLE001
        pass
    links = LINKS.get(vid)     # only links a lookup already made has given: a page of its own each
    out = {"at": time.time(), "words": [], "lines": []}            # time fed YouTube's bot check
    if links is None:
        return out                                       # none in hand: not kept, looked for next time
    for kind, url in links.items():
        if url:
            j = _json(url)
            if j is None:
                return out
            out["words" if kind == "auto" else "lines"] = (_words if kind == "auto" else _lines)(j)
    with _lock:
        try:
            cache.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out), encoding="utf-8")
        except OSError:
            pass
    return out


# ------------------------------------------------------------ retiming
def _items(doc: dict) -> list:
    for k in ("Content", "Lines"):
        v = (doc or {}).get(k)
        if isinstance(v, list):
            return v
    return []


def _base_words(items: list) -> list:
    """The lyrics' words as (line index, seconds, word); None past a line's first word where the
    words have no times of their own (an even spread would be a guess, and guesses skew the shift)."""
    out = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        start = SL.line_start(it)
        if start is None:
            continue
        syls = [s for s in ((it.get("Lead") or {}).get("Syllables") or []) if isinstance(s, dict)]
        if syls and all(isinstance(s.get("StartTime"), (int, float)) for s in syls):
            word, at = "", None
            for s in syls:
                if at is None:
                    at = float(s["StartTime"])
                word += s.get("Text") or ""
                if not s.get("IsPartOfWord"):
                    out += [(i, at, w) for w in tokens(word)]
                    word, at = "", None
            if word:
                out += [(i, at, w) for w in tokens(word)]
            continue
        out += [(i, None if k else start, w) for k, w in enumerate(tokens(SL.line_text(it)))]
    return out


def _chain(base: list, theirs: list, weight: float) -> list:
    """The best in-order pairing of the lyrics' words with timed caption words, as anchors.

    Candidates are word pairs that also agree on the next word. The chain keeps both orders,
    counts anchors, and pays JUMP for every change of shift, so one steady shift wins.
    """
    a = [w for _i, _t, w in base]
    nxt = {}
    for j, (_t, w, follow) in enumerate(theirs):
        nxt.setdefault((w, follow), []).append(j)
    cands = []
    for i in range(len(a) - 1):
        if base[i][1] is None:
            continue
        for j in nxt.get((a[i], a[i + 1]), ()):
            cands.append((i, j, theirs[j][0] - base[i][1]))
    cands.sort()
    best, back = [], []
    for k, (i, j, d) in enumerate(cands):
        score, prev = weight, -1
        for p in range(k - 1, max(-1, k - 400), -1):        # nearby predecessors are enough
            pi, pj, pd = cands[p]
            if pi < i and pj < j:
                s = best[p] + weight - (JUMP if abs(pd - d) > TOL else 0.0)
                if s > score:
                    score, prev = s, p
        best.append(score)
        back.append(prev)
    if not best:
        return []
    k, out = max(range(len(best)), key=best.__getitem__), []
    while k >= 0:
        i, j, d = cands[k]
        out.append((base[i][1], base[i][1] + d, weight))
        k = back[k]
    return out[::-1]


def stretches(base: list, caps: dict) -> list:
    """[(first, last, shift)] in the lyrics' seconds: where the video runs that much later."""
    words = [(t, w, (caps.get("words") or [])[k + 1][1] if k + 1 < len(caps.get("words") or []) else "")
             for k, (t, w) in enumerate(caps.get("words") or [])]
    firsts = []                      # a subtitle line's start belongs to its first word only
    for start, _end, text in caps.get("lines") or []:
        ws = text.split()
        if len(ws) >= 2:
            firsts.append((start, ws[0], ws[1]))
    anchors = sorted(_chain(base, words, 1.0) + _chain(base, firsts, 2.0))
    runs: list = []
    for b, v, w in anchors:
        d = v - b
        if runs and abs(d - statistics.median(x[1] for x in runs[-1])) <= TOL:
            runs[-1].append((b, d, w))
        else:
            runs.append([(b, d, w)])
    kept: list = []
    for r in (r for r in runs if sum(x[2] for x in r) >= MIN_WEIGHT):
        if kept and abs(statistics.median(x[1] for x in kept[-1])
                        - statistics.median(x[1] for x in r)) <= TOL / 2:
            kept[-1] += r            # the same shift either side of a stretch too thin to count
        else:
            kept.append(r)
    return [(r[0][0], r[-1][0], round(statistics.median(x[1] for x in r), 3)) for r in kept]


def _shift(node, by: float) -> None:
    if isinstance(node, dict):
        for k in ("StartTime", "EndTime"):
            if isinstance(node.get(k), (int, float)):
                node[k] = round(node[k] + by, 3)
        for v in node.values():
            if isinstance(v, (dict, list)):
                _shift(v, by)
    elif isinstance(node, list):
        for v in node:
            _shift(v, by)


def shift_at(runs: list, t: float) -> float:
    """How much later the video has the moment `t` of the lyrics: its stretch's, or the nearest one's."""
    near = min(runs, key=lambda r: 0.0 if r[0] - TOL <= t <= r[1] + TOL
               else min(abs(t - r[0]), abs(t - r[1])))
    return near[2]


def retime(body, caps: dict) -> dict | None:
    """The document on the video's clock, or None where the captions say nothing about it."""
    doc = SL.payload(body)
    items = _items(doc)
    base = _base_words(items)
    if not base or not (caps.get("words") or caps.get("lines")):
        return None
    runs = stretches(base, caps)
    if not runs or all(abs(d) < SHIFT_MIN for _f, _l, d in runs):
        return None
    out = copy.deepcopy(doc)
    for it in _items(out):
        start = SL.line_start(it) if isinstance(it, dict) else None
        if start is not None:
            _shift(it, shift_at(runs, start))
    starts = [s for s in (SL.line_start(it) for it in _items(out) if isinstance(it, dict)) if s is not None]
    ends = [it["EndTime"] for it in _items(out) if isinstance(it, dict) and isinstance(it.get("EndTime"), (int, float))]
    if starts and isinstance(out.get("StartTime"), (int, float)):
        out["StartTime"] = min(starts)
    if ends and isinstance(out.get("EndTime"), (int, float)):
        out["EndTime"] = max(ends)
    out["_yt_shift"] = [list(r) for r in runs]
    return out
