"""Fallback lyric providers, for when Spicy Lyrics has nothing good.

Spicy Lyrics (Community / Apple Music) is the source the app was built around,
and its data is what every other feature (romanisation, furigana, Genius
alignment) is tuned against, so it leads the running order by default. But a
fair slice of any library comes back line-synced, unsynced, or missing
entirely, and for those there is often better data elsewhere. This module goes
and gets it.

The chain, in default order:

    amll-ttml-db   word-by-word TTML, community-submitted, indexed by Spotify
                   id among others. Same data model as Apple Music, so it drops
                   straight in.
    the blend      QQ Music's within-line timing under Apple Music's lines,
                   with NetEase voting on where each line starts. Three lookups
                   rather than one, so it is off unless asked for.
    Lyrics+         the LyricsPlus backend, which scrapes Apple/Musixmatch/
                   Spotify/QQ live and can also hand back TTML.
    NetEase        word-level `yrc` where it has it, and -- uniquely here -- a
                   human-written romanisation on the same clock as the lyrics.
    LRCLIB         huge, open, no key needed -- but line-level LRC only, so it
                   is the last resort and only ever an upgrade over nothing.

The order is the caller's to set, Spicy Lyrics included; see fallback(). What
the order cannot do is trade quality away -- a source ranked first still only
wins against an equal or worse document, never by replacing word timing with
line timing.

Everything is converted to the shape spicy_lyrics.timeline() already eats, so
nothing downstream needs to know where a song came from.
"""

from __future__ import annotations

import bisect
import json
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import spicy_lyrics as SL

REVISION = 9

UA = "mild-lyrics/1.0 (+personal lyrics viewer)"
TIMEOUT = 8.0

AMLL_RAW = "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main"
YOULY_BASE = os.environ.get("LYRICSPLUS_BASE", "https://lyricsplus.prjktla.my.id")
LRCLIB_BASE = "https://lrclib.net"

def cache_root() -> pathlib.Path:
    """The cache directory, per platform. Kept in step with lyrics_gui.app_dir,
    and spelled out here rather than imported so this module stays usable on its
    own -- it has no other reason to know the GUI exists."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or (
            pathlib.Path.home() / "AppData" / "Local")
        return _migrated(pathlib.Path(root))
    root = os.environ.get("XDG_CACHE_HOME") or (pathlib.Path.home() / ".cache")
    return _migrated(pathlib.Path(root))


def config_root() -> pathlib.Path:
    """The settings directory, the same way. Roaming on Windows, XDG_CONFIG_HOME
    elsewhere -- the division lyrics_gui.app_dir draws."""
    if os.name == "nt":
        root = os.environ.get("APPDATA") or (
            pathlib.Path.home() / "AppData" / "Roaming")
        return _migrated(pathlib.Path(root))
    root = os.environ.get("XDG_CONFIG_HOME") or (pathlib.Path.home() / ".config")
    return _migrated(pathlib.Path(root))


_cache_root = cache_root


def _migrated(root: pathlib.Path) -> pathlib.Path:
    """Kept in step with lyrics_gui.app_dir, including its one-time rename."""
    new, old = root / "mild-lyrics", root / "spicy-lyrics"
    try:
        if old.is_dir() and not new.exists():
            old.rename(new)
    except Exception:
        pass
    return new


CACHE_DIR = _cache_root() / "sources"
MISS_TTL = 6 * 3600
HIT_TTL = 30 * 86400
SWEEP_EVERY = 86400

RANK = {"none": 0, "static": 1, "line": 2, "syllable": 3}


def _items(doc: dict) -> list[dict]:
    """A document's lines, whichever key this one filed them under."""
    for k in ("Content", "Lines"):
        v = (doc or {}).get(k)
        if isinstance(v, list) and v:
            return [i for i in v if isinstance(i, dict)]
    return []


def _line_end(item: dict) -> float | None:
    """End time in seconds, the group's if the line itself carries none."""
    for src in (item, item.get("Lead") if isinstance(item, dict) else None):
        if isinstance(src, dict) and isinstance(src.get("EndTime"), (int, float)):
            return float(src["EndTime"])
    return None


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def quality(body) -> str:
    """What we actually have, judged by the data rather than the Type field.

    A document can claim "Syllable" and carry no timed syllables at all, and a
    "Line" one is useless if none of its lines got a StartTime, so this looks.
    """
    doc = SL.payload(body or {})
    items = next(
        (doc[k] for k in ("Content", "Lines") if isinstance(doc.get(k), list) and doc[k]), []
    )
    items = [i for i in items if isinstance(i, dict)]
    if not items:
        return "none"
    for item in items:
        lead = item.get("Lead")
        if isinstance(lead, dict):
            for y in lead.get("Syllables") or []:
                if isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float)):
                    return "syllable"
    if any(SL.line_start(i) is not None for i in items):
        return "line"
    return "static" if any((SL.line_text(i) or "").strip() for i in items) else "none"


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
_HOST_CAP = {urllib.parse.urlsplit(YOULY_BASE).netloc: 2}
_HOST_CAP_DEFAULT = 4
_gates: dict[str, "threading.Semaphore"] = {}
_gates_lock = threading.Lock()


def _gate(url: str):
    host = urllib.parse.urlsplit(url).netloc
    with _gates_lock:
        g = _gates.get(host)
        if g is None:
            g = _gates[host] = threading.Semaphore(
                _HOST_CAP.get(host, _HOST_CAP_DEFAULT))
    return g


def _get(url: str, accept: str = "*/*") -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with _gate(url):
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    return r.read() if r.status == 200 else None
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 2:
                    return None
                time.sleep(0.7)
            except Exception:
                return None
    return None


def _qs(**kw) -> str:
    return urllib.parse.urlencode({k: v for k, v in kw.items() if v not in (None, "", 0)})


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def _tag(el) -> str:
    """Local name. Sources disagree about namespaces -- amll-ttml-db writes its
    <div> with xmlns="" so the lines are in no namespace at all, while Apple's
    own files keep everything in the TTML one."""
    t = el.tag
    return t.rsplit("}", 1)[-1] if isinstance(t, str) and "}" in t else str(t)


def _attr(el, name: str) -> str | None:
    """Attribute by local name, whatever prefix the file bound it to."""
    for k, v in el.attrib.items():
        if k.rsplit("}", 1)[-1] == name:
            return v
    return None


def _secs(v) -> float | None:
    """TTML clock value -> seconds. Handles h:mm:ss.mmm, mm:ss.mmm, 12.5s, 300ms."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)?", v)
    if m:
        n = float(m.group(1))
        return n * {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, None: 1.0}[m.group(2)]
    parts = v.split(":")
    if not 2 <= len(parts) <= 3:
        return None
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.insert(0, 0.0)
    return nums[0] * 3600 + nums[1] * 60 + nums[2]


def _latin(s: str) -> bool:
    return any(c.isascii() and c.isalpha() for c in s)


def _syllables(parent, spaced: bool = True) -> list[dict]:
    """Timed <span> children -> Syllables, with word breaks taken from spacing.

    TTML has no word flag; a well-formed file puts whitespace between the spans
    that end a word and none between the spans inside one, which is the same
    information IsPartOfWord carries, just written differently.

    Some of amll-ttml-db's older hand-made submissions put no whitespace
    anywhere -- every word is its own span, back to back. Reading those by the
    spacing rule spells "Couldn'tbeathersmileitstirredupallthemedia", so when
    the file never spaces anything (`spaced` is False) each span is taken as a
    word instead. Not for CJK, which genuinely runs together and where the
    spans really are sub-word.
    """
    out = []
    spans = [sp for sp in parent if _tag(sp) == "span" and not _attr(sp, "role")
             and _secs(_attr(sp, "begin")) is not None]
    for i, sp in enumerate(spans):
        s, e = _secs(_attr(sp, "begin")), _secs(_attr(sp, "end"))
        text = "".join(sp.itertext())
        tail = sp.tail or ""
        if tail.strip():
            text += tail.strip()
        nxt = "".join(spans[i + 1].itertext()) if i + 1 < len(spans) else ""
        if spaced:
            part = not (tail and tail != tail.strip())
        elif not (_latin(text) or _latin(nxt)):
            part = True
        else:
            part = (not any(c.isalnum() for c in text)
                    or bool(nxt) and not nxt[0].isalnum())
        out.append({
            "Text": text,
            "StartTime": s,
            "EndTime": e if e is not None else s,
            "IsPartOfWord": part,
        })
    if out:
        out[-1]["IsPartOfWord"] = False
    return _repair(out, _secs(_attr(parent, "begin")), _secs(_attr(parent, "end")))


SLACK = 0.25


def _repair(syls: list[dict], begin: float | None = None,
            end: float | None = None) -> list[dict]:
    """Re-time syllables that are stamped somewhere the line is not.

    These are community submissions and some carry a syllable stamped
    00:00.000 in the middle of an otherwise fine line. Rendered as-is the fill
    jumps back to the start of the song and the whole line reads as sung, so
    any run that lands outside the line gets interpolated across the gap its
    sane neighbours leave.

    Outside the LINE, though -- not merely out of turn. Syllables inside a
    line overlap each other on purpose: a word held over the ones after it, a
    rapped line whose breath carries through, an ad-lib sung across the words
    beneath it. Two syllables sounding at once is a thing a singer does, and a
    file that says so is not corrupt. The old test -- every syllable must
    start where the last one ended -- called each of those a mistake and
    flattened the whole rest of the line onto one instant, which is precisely
    the damage this is here to undo.

    A line with no stamps of its own has nothing to be outside of, so there
    the reading falls back to the order the syllables are written in.
    """
    first = None if begin is None else begin - SLACK
    last = None if end is None else end + SLACK
    good, after = [], None
    for i, y in enumerate(syls):
        if y["EndTime"] < y["StartTime"]:
            continue
        if first is not None:
            fits = y["StartTime"] >= first and (last is None
                                                or y["StartTime"] <= last)
        else:
            fits = after is None or y["StartTime"] >= after
        if fits:
            good.append(i)
            after = y["StartTime"]
    if len(good) == len(syls):
        return syls
    ok = set(good)
    for i, y in enumerate(syls):
        if i in ok:
            continue
        lo = next((syls[j]["EndTime"] for j in range(i - 1, -1, -1) if j in ok), None)
        up = next((syls[j]["StartTime"] for j in range(i + 1, len(syls)) if j in ok), None)
        if lo is None and up is None:
            continue
        lo = up if lo is None else lo
        up = lo if up is None else up
        up = max(lo, up)        # the sane neighbours may themselves overlap
        run = [j for j in range(len(syls)) if j not in ok
               and (j == i or lo <= syls[j].get("StartTime", -1) <= up)]
        run = [j for j in run if all(k not in ok for k in range(min(j, i), max(j, i)))]
        k, n = run.index(i), max(len(run), 1)
        y["StartTime"] = lo + (up - lo) * k / n
        y["EndTime"] = lo + (up - lo) * (k + 1) / n
    return syls


PAIRS = {"(": ")", "[": "]", "（": "）", "「": "」", "【": "】"}


def _unwrap(syls: list[dict]) -> list[dict]:
    """Peel the brackets off a backing vocal.

    Apple's TTML -- and amll-ttml-db following it -- writes backing vocals with
    the parentheses baked into the text: "(For" ... "you)". The app draws
    backing vocals as their own indented line and adds brackets itself where it
    wants them, and Spicy Lyrics' own data has none, so leaving these in shows
    one convention's punctuation inside the other's layout.

    Only stripped when they actually pair up across the group, so a line that
    genuinely contains a bracket is left alone.
    """
    if not syls:
        return syls
    head, tail = syls[0].get("Text", ""), syls[-1].get("Text", "")
    close = PAIRS.get(head[:1])
    if not close or not tail.endswith(close):
        return syls
    if len(syls) == 1 and len(head) < 3:
        return syls
    syls[0]["Text"] = head[1:]
    syls[-1]["Text"] = syls[-1]["Text"][:-1]
    return [y for y in syls if y.get("Text", "").strip()] or syls


def _group(el, spaced: bool = True, bg: bool = False) -> dict:
    syls = _syllables(el, spaced)
    if bg:
        syls = _unwrap(syls)
    g = {"Syllables": syls}
    s, e = _secs(_attr(el, "begin")), _secs(_attr(el, "end"))
    if s is None and syls:
        s = syls[0]["StartTime"]
    if e is None and syls:
        e = max(y["EndTime"] for y in syls)
    if s is not None:
        g["StartTime"] = s
    if e is not None:
        g["EndTime"] = e
    return g


def _destamp(items: list[dict]) -> list[dict]:
    """Drop timings that are not really timings.

    Lyrics+ hands back plain, unsynced lyrics in the same timed shape as
    everything else, with every line stamped 00:00.000. Taken at face value
    that is a "synced" document where the whole song happens at once: the view
    lights every line at 0:00 and then never moves again, which is worse than
    honestly showing it as unsynced and letting it scroll. Treat a document
    whose stamps never advance as static, and say so.
    """
    starts = [i["StartTime"] for i in items if isinstance(i.get("StartTime"), (int, float))]
    if not starts:
        return items
    if len(set(starts)) > 1 or len(starts) < 2:
        return items
    out = []
    for i in items:
        i = {k: v for k, v in i.items() if k not in ("StartTime", "EndTime", "Lead")}
        i.pop("Background", None)
        if (i.get("Text") or "").strip():
            out.append(i)
    return out or items


def _credits(root) -> tuple[list[str], str]:
    """Who wrote the song, and who timed this copy of it.

    Three conventions in play, all in the same <head>. Apple writes
    <songwriters><songwriter>, and Lyrics+ echoes it verbatim whichever upstream
    it got the words from. LyricsPlus adds <lyricsplus:curator> naming whoever
    submitted the sync. amll-ttml-db files the same fact as an <amll:meta
    key="ttmlAuthorGithubLogin">.

    Matched by local name: the prefixes differ per file, and amll's <metadata>
    binds xmlns="" so half of it is in no namespace at all.
    """
    head = next((el for el in root if _tag(el) == "head"), root)
    writers, maker, seen = [], "", set()
    for el in head.iter():
        tag, text = _tag(el), (el.text or "").strip()
        if tag == "songwriter" and text and text.lower() not in seen:
            seen.add(text.lower())
            writers.append(text)
        elif tag == "curator" and text:
            maker = maker or text
        elif tag == "meta" and _attr(el, "key") in ("ttmlAuthorGithubLogin",
                                                    "ttmlAuthor"):
            maker = maker or (_attr(el, "value") or "").strip()
    return writers, maker


def _agents(root) -> list[str]:
    """The voices the header declares, in the order it declares them.

    A ttm:agent id is an arbitrary name -- v1, v2, singer1, whoever -- but the
    ORDER they are declared in is not arbitrary: the first is the voice the
    document is written from, and it is the one a player draws on the near
    side. Apple's files declare it first, and this project's own renderer
    writes v1 before v2 for exactly that reason.

    Taking the primary from whichever LINE came first instead -- which is what
    this used to do -- flips a whole duet the moment the other singer opens
    the song, and plenty of duets open that way. The file said v2, v1, v2 and
    read back as v1, v2, v1: both sides swapped, in the editor on reopening
    and in the player over the live link.
    """
    head = next((el for el in root if _tag(el) == "head"), root)
    out: list[str] = []
    for el in head.iter():
        if _tag(el) != "agent":
            continue
        got = _attr(el, "id")
        if got and got not in out:
            out.append(got)
    return out


def parse_ttml(xml: str | bytes) -> dict | None:
    """Apple-style TTML -> the document shape timeline() reads."""
    try:
        root = ET.fromstring(xml)
    except Exception:
        return None

    paras = [el for el in root.iter() if _tag(el) == "p"]
    if not paras:
        return None

    agents = [_attr(p, "agent") for p in paras]
    used = {a for a in agents if a}
    primary = (next((a for a in _agents(root) if a in used), None)
               or next((a for a in agents if a), None))

    spaced = any((sp.tail or "") != (sp.tail or "").strip()
                 for p in paras for sp in p if _tag(sp) == "span")

    items, cjk = [], False
    for p in paras:
        ps, pe = _secs(_attr(p, "begin")), _secs(_attr(p, "end"))
        lead = _group(p, spaced)
        bg = []
        for sp in p:
            if _tag(sp) == "span" and _attr(sp, "role") == "x-bg":
                g = _group(sp, spaced, bg=True)
                if g["Syllables"]:
                    bg.append(g)
        if lead["Syllables"]:
            text = SL.syllables_text(lead["Syllables"])
        else:
            lead = None
            text = "".join(
                t for t in ([p.text or ""] + [
                    ("" if _attr(sp, "role") else "".join(sp.itertext())) + (sp.tail or "")
                    for sp in p
                ])
            ).strip()
        if not text.strip() and not bg:
            continue
        cjk = cjk or bool(SL.CJK.search(text))
        item: dict = {"Text": text}
        if lead:
            lead.setdefault("StartTime", ps)
            lead.setdefault("EndTime", pe)
            item["Lead"] = lead
        if ps is not None:
            item["StartTime"] = ps
        if pe is not None:
            item["EndTime"] = pe
        if bg:
            item["Background"] = bg
        agent = _attr(p, "agent")
        if primary and agent and agent != primary:
            item["OppositeAligned"] = True
        items.append(item)

    if not items:
        return None
    items = _destamp(items)
    typed = "Syllable" if any("Lead" in i for i in items) else (
        "Line" if any("StartTime" in i for i in items) else "Static")
    doc = {
        "Type": typed,
        ("Lines" if typed == "Static" else "Content"): items,
        "HasTransliterations": cjk,
    }
    lang = _attr(root, "lang")
    if lang:
        doc["Language"] = lang
    writers, maker = _credits(root)
    if writers:
        doc["SongWriters"] = writers
    if maker:
        doc["_maker"] = maker
    return doc


def _deword(doc: dict) -> dict:
    """Word-timed document -> line-timed, keeping the line stamps.

    Not a loss of information so much as a refusal to claim some: a source that
    times words by dividing a line across its syllables produces a document
    shaped exactly like a real word sync, and the view has no way to tell them
    apart -- it just highlights the wrong syllable very confidently. Dropping to
    the line stamps, which are measured either way, is the honest reading.
    """
    key = "Lines" if doc.get("Type") == "Static" else "Content"
    items, out = doc.get(key) or [], []
    for it in items:
        if not isinstance(it, dict):
            continue
        lead = it.get("Lead") if isinstance(it.get("Lead"), dict) else None
        new = {k: v for k, v in it.items() if k != "Lead"}
        for a in ("StartTime", "EndTime"):
            if not isinstance(new.get(a), (int, float)) and lead \
                    and isinstance(lead.get(a), (int, float)):
                new[a] = lead[a]
        bg = [g for g in (new.get("Background") or []) if isinstance(g, dict)]
        flat = []
        for g in bg:
            text = g["Text"] if isinstance(g.get("Text"), str) else SL.syllables_text(
                g.get("Syllables"))
            g = {k: v for k, v in g.items() if k != "Syllables"}
            if (text or "").strip():
                g["Text"] = text
                flat.append(g)
        if flat:
            new["Background"] = flat
        else:
            new.pop("Background", None)
        out.append(new)
    typed = "Line" if any("StartTime" in i for i in out) else "Static"
    doc = {k: v for k, v in doc.items() if k not in ("Type", "Content", "Lines")}
    doc["Type"] = typed
    doc["Lines" if typed == "Static" else "Content"] = out
    return doc


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
LRC_TAG = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")


def parse_lrc(text: str, plain: str = "") -> dict | None:
    """LRC -> a Line-timed document, or a Static one from the plain text."""
    rows: list[tuple[float, str]] = []
    for raw in (text or "").splitlines():
        stamps = list(LRC_TAG.finditer(raw))
        if not stamps:
            continue
        body = raw[stamps[-1].end():].strip()
        for m in stamps:
            rows.append((int(m.group(1)) * 60 + float(m.group(2).replace(":", ".")), body))
    rows.sort(key=lambda r: r[0])
    if len({t for t, _ in rows}) < 2:
        plain = plain or "\n".join(b for _, b in rows)
        rows = []
    if rows:
        items = []
        for i, (t, body) in enumerate(rows):
            if not body:
                continue
            nxt = next((rows[j][0] for j in range(i + 1, len(rows))), None)
            end = min(nxt, t + 10.0) if nxt is not None else t + 6.0
            items.append({"Text": body, "StartTime": t, "EndTime": end})
        if items:
            return {"Type": "Line", "Content": items,
                    "HasTransliterations": any(SL.CJK.search(i["Text"]) for i in items)}
    lines = [l.strip() for l in (plain or "").splitlines() if l.strip()]
    if not lines:
        return None
    return {"Type": "Static", "Lines": [{"Text": l} for l in lines],
            "HasTransliterations": any(SL.CJK.search(l) for l in lines)}


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
AMLL_INDEX = CACHE_DIR / "amll-index.json"
AMLL_INDEX_TTL = 7 * 86400
_NOISE = re.compile(r"\s*[(\[](?:feat|ft|with|remaster|remix|explicit|deluxe)[^)\]]*[)\]]",
                    re.I)


def _norm(s: str) -> str:
    """Loose title/artist key: case, spacing and punctuation all thrown away."""
    s = _NOISE.sub("", s or "")
    s = re.sub(r"\s*-\s*(single|ep|remaster(ed)?.*|feat\..*)$", "", s, flags=re.I)
    return "".join(c for c in s.lower() if c.isalnum())


def amll_index() -> dict:
    """title+artist -> raw lyric file, built from the db's own index.

    Only 2362 of the entries are filed under a Spotify id, but every one of the
    3157 raw submissions is listed here with its title and artists. On a real
    library the id lookup alone finds almost nothing; this is what makes the
    source worth having.
    """
    try:
        if time.time() - AMLL_INDEX.stat().st_mtime < AMLL_INDEX_TTL:
            return json.loads(AMLL_INDEX.read_text(encoding="utf-8"))
    except Exception:
        pass
    blob = _get(f"{AMLL_RAW}/metadata/raw-lyrics-index.jsonl", "application/x-ndjson")
    if not blob:
        try:
            return json.loads(AMLL_INDEX.read_text(encoding="utf-8"))
        except Exception:
            return {}
    out: dict[str, str] = {}
    for line in blob.decode("utf-8", "replace").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        meta = {k: v for k, v in (rec.get("metadata") or []) if isinstance(v, list)}
        f = rec.get("rawLyricFile")
        if not f:
            continue
        for name in meta.get("musicName") or []:
            for art in meta.get("artists") or []:
                out.setdefault(f"{_norm(name)}\x00{_norm(art)}", f)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        AMLL_INDEX.write_text(json.dumps(out), encoding="utf-8")
    except Exception:
        pass
    return out


def from_amll(tid: str, meta: dict, local=None) -> dict | None:
    if tid:
        raw = _get(f"{AMLL_RAW}/spotify-lyrics/{urllib.parse.quote(tid)}.ttml",
                   "application/xml")
        if raw:
            doc = parse_ttml(raw)
            if doc:
                return doc
    title, artist = meta.get("title") or "", meta.get("artist") or ""
    if not title or not artist:
        return None
    idx = amll_index()
    if not idx:
        return None
    for art in re.split(r"\s*[,;/&]\s*|\s+feat\.?\s+|\s+x\s+", artist):
        f = idx.get(f"{_norm(title)}\x00{_norm(art)}")
        if f:
            raw = _get(f"{AMLL_RAW}/raw-lyrics/{urllib.parse.quote(f)}", "application/xml")
            if raw:
                doc = parse_ttml(raw)
                if doc:
                    return doc
    return None


def _lead_in(doc: dict) -> dict:
    """Pull a line's first syllable back to where the line itself begins.

    Lyrics+'s blended answer takes its line stamps from one upstream and its
    word stamps from another -- Apple's <p begin> against QQ's first <span> --
    and the two do not quite agree. The line lights up, and then a tenth of a
    second later the first word starts filling, which reads as the singer being
    late on every line of the song.

    Only ever earlier: a first word that starts after its line is the line
    waiting for the voice, which is a real thing that happens and not a defect.
    """
    for it in doc.get("Content") or []:
        lead = it.get("Lead")
        if not isinstance(lead, dict):
            continue
        syls = lead.get("Syllables") or []
        start = SL.line_start(it)
        if not syls or not isinstance(start, (int, float)):
            continue
        if isinstance(syls[0].get("StartTime"), (int, float)) and start < syls[0]["StartTime"]:
            syls[0] = {**syls[0], "StartTime": float(start)}
            lead["Syllables"] = syls
            lead["StartTime"] = float(start)
    return doc


def _youly_ask(q: str):
    """One shape of the question, as (document, which upstream won).

    The endpoint is documented as returning raw TTML and actually answers with
    {"ttml": "..."}, errors included -- hence unwrapping either shape.
    """
    raw = _get(f"{YOULY_BASE}/v1/ttml/get?{q}", "application/xml, application/json")
    if not raw:
        return None
    head, won = raw.lstrip()[:1], ""
    if head == b"{":
        try:
            rec = json.loads(raw)
        except Exception:
            return None
        if not isinstance(rec, dict) or rec.get("error"):
            return None
        won = str((rec.get("processingTime") or {}).get("winnerSource") or "")
        raw = rec.get("ttml") or ""
        if not raw:
            return None
    elif head != b"<":
        return None
    doc = parse_ttml(raw)
    return None if doc is None else (doc, won)


def from_youly(tid: str, meta: dict, source: str | None = None,
               local=None) -> dict | None:
    """LyricsPlus.

    The platformId is NOT sent first, which is the opposite of what it looks
    like it should do. The server treats it as a cache key: where it has not
    already answered for that Spotify id it 404s on the spot, and the title
    and artist alongside it are never reached. Measured over fifteen tracks
    from this library, asking as this used to -- id, album, duration and the
    full byline -- answered six times; the same fifteen asked on name and
    duration alone answered twelve. It was refusing songs it had.

    The id is still worth one ask, alongside the FIRST artist only, for the
    collaborations where the full byline ("BLCKK, ISSBROKIE") matches nothing
    the server has filed. Two requests at most, and only one for a track
    credited to a single artist.

    `source` pins one upstream instead of letting the server pick a winner --
    "apple", "qq", "musixmatch", "deezer", "lyricsplus". Left off, the server
    runs its own race, which is what this provider wants; the blend below asks
    for one side at a time because it is doing the reconciling itself.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title or not artist:
        return None
    dur = round(float(meta.get("length") or 0), 3)
    first = re.split(r"\s*[,;/&]\s*|\s+feat\.?\s+", artist)[0].strip()
    asks = [_qs(title=title, artist=artist, duration=dur, source=source)]
    if first and first != artist:
        asks.append(_qs(title=title, artist=first, platformId=tid, duration=dur,
                        source=source))
    got = None
    for q in asks:
        got = _youly_ask(q)
        if got is not None:
            break
    if got is None:
        return None
    doc, won = got
    if "musixmatch" in won.lower() and doc.get("Type") == "Syllable":
        doc = _deword(doc)
    else:
        doc = _lead_in(doc)
    doc["_via"] = won or "?"
    return doc


def from_lrclib(tid: str, meta: dict, local=None) -> dict | None:
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title or not artist:
        return None
    dur = float(meta.get("length") or 0)
    got = None
    if dur > 0:
        q = _qs(track_name=title, artist_name=artist,
                album_name=meta.get("album"), duration=int(round(dur)))
        got = _get(f"{LRCLIB_BASE}/api/get?{q}", "application/json")
    if not got:
        q = _qs(track_name=title, artist_name=artist)
        blob = _get(f"{LRCLIB_BASE}/api/search?{q}", "application/json")
        try:
            hits = json.loads(blob) if blob else []
        except Exception:
            hits = []
        hits = [h for h in hits if isinstance(h, dict) and not h.get("instrumental")]
        if dur > 0:
            hits = [h for h in hits if abs(float(h.get("duration") or 0) - dur) <= 4.0]
        hits.sort(key=lambda h: (not h.get("syncedLyrics"),
                                 abs(float(h.get("duration") or 0) - dur)))
        if not hits:
            return None
        rec = hits[0]
    else:
        try:
            rec = json.loads(got)
        except Exception:
            return None
    if not isinstance(rec, dict) or rec.get("instrumental"):
        return None
    return parse_lrc(rec.get("syncedLyrics") or "", rec.get("plainLyrics") or "")


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
NE_BASE = "https://music.163.com"
NE_HEAD = {"User-Agent": "Mozilla/5.0", "Referer": NE_BASE}
NE_TRIES = 3
NE_SPREAD = 20.0
# A credit line, stamped and timed like a lyric by every source that writes
# one. Kugou puts "Lyrics by：Vivian Weeks" and "Composed by：Vivian Weeks" at
# the top of a great many songs, in the Latin script and with the fullwidth
# colon, which the Chinese-only pattern walked straight past -- so they were
# sung at the listener over the intro and written into every TTML saved from
# here. The colon is required: it is what separates a credit from a lyric that
# happens to open with the word "Music".
NE_CREDIT = re.compile(
    r"^\s*(作词|作曲|编曲|制作人|出品|监制|录音|混音|母带|吉他|贝斯|鼓|键盘|和声|"
    r"弦乐|人声|策划|统筹|发行|词|曲"
    r"|lyric(?:s|ist)?|compos(?:ed|er|ition)|writ(?:ten|er)|music"
    r"|arrang(?:ed|er|ement)|produc(?:ed|er|tion)|mix(?:ed|ing)?"
    r"|master(?:ed|ing)?|record(?:ed|ing)?|vocals?|performed|engineer(?:ed)?"
    r"|backing vocals?|guitars?|bass|drums|keyboards?|strings?|piano"
    r")\s*(?:by)?\s*[:：]", re.I)
NE_WROTE = re.compile(
    r"^\s*(作词|作曲|词|曲|lyric(?:s|ist)?|compos(?:ed|er|ition)|writ(?:ten|er)|music)"
    r"\s*(?:by)?\s*[:：]\s*(.+)$", re.I)
NE_YRC_LINE = re.compile(r"^\[(\d+),(\d+)\]")
NE_YRC_TOK = re.compile(r"\((\d+),(\d+),\d+\)([^(]*)")


def _ne_get(url: str):
    req = urllib.request.Request(url, headers=NE_HEAD)
    with _gate(url):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except Exception:
            return None


def _ne_rank(meta: dict) -> list[int]:
    """Plausible NetEase song ids for this track, best first.

    Search never fails -- it returns a nearest match for anything, including
    tracks it plainly does not have -- so a hit is only believed when the
    duration lines up, or failing that when the title matches outright. Without
    that check this source would confidently answer for the whole library.

    A list rather than a single winner because NetEase routinely carries the
    same recording several times over -- standard, deluxe, compilation -- and
    only some of those releases are stamped word-level. They tie on every
    signal available here (same title, same duration to the millisecond), so
    which one "wins" is decided by result order, and the caller has to open
    more than one to find the timing.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title:
        return []
    q = urllib.parse.quote(f"{title} {artist}".strip())
    d = _ne_get(f"{NE_BASE}/api/search/get?s={q}&type=1&limit=8")
    songs = ((d or {}).get("result") or {}).get("songs") or []
    want = float(meta.get("length") or 0)
    key, akey, scored = _norm(title), _norm(artist), []
    for s in songs:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        dur = float(s.get("duration") or 0) / 1000.0
        theirs = _norm(s.get("name") or "")
        same = bool(key) and (theirs == key
                              or (len(key) >= 4 and key in theirs)
                              or (len(theirs) >= 4 and theirs in key))
        near = want > 0 and dur > 0 and abs(dur - want) <= 5.0
        far = want > 0 and dur > 0 and abs(dur - want) > NE_SPREAD
        mine = {_norm(a.get("name") or "") for a in (s.get("artists") or [])
                if isinstance(a, dict)}
        byline = bool(akey) and any(
            a and (a == akey or (len(akey) >= 3 and akey in a)
                   or (len(a) >= 3 and a in akey)) for a in mine)
        # Two of the three have to agree: the title, the byline, the length.
        # One was enough here and one is not evidence -- a duration inside
        # five seconds is a coincidence a four-minute song has with half the
        # catalogue, and a title alone is every cover and karaoke cut of it.
        # On a song NetEase does not have, and search always answers with
        # SOMETHING, that single signal is exactly how the wrong lyric got in.
        if int(same) + int(near) + int(byline) < 2:
            continue
        score = (0 if far else 1,
                 2 if (same and near) else 1 if near else 0,
                 1 if byline else 0,
                 -abs(dur - want) if want else 0)
        scored.append((score, s["id"]))
    scored.sort(key=lambda r: r[0], reverse=True)
    return [(sid, sc[:3]) for sc, sid in scored]


def _ne_yrc(text: str) -> list[dict]:
    """NetEase word-level lyrics -> timed items."""
    items = []
    for raw in (text or "").splitlines():
        m = NE_YRC_LINE.match(raw)
        if not m:
            continue
        toks = NE_YRC_TOK.findall(raw[m.end():])
        if not toks:
            continue
        body = "".join(t[2] for t in toks).strip()
        if not body or NE_CREDIT.match(body):
            continue
        syls = []
        for s, dur, word in toks:
            text = word.rstrip()
            if not text:
                if syls:
                    syls[-1]["IsPartOfWord"] = False
                continue
            s, dur = int(s) / 1000.0, int(dur) / 1000.0
            syls.append({"Text": text, "StartTime": s, "EndTime": s + dur,
                         "IsPartOfWord": word == text})
        if not syls:
            continue
        lead, bg = _ne_bg(syls)
        if not lead:
            lead, bg = syls, []
        lead[-1] = {**lead[-1], "IsPartOfWord": False}
        start, dur = int(m.group(1)) / 1000.0, int(m.group(2)) / 1000.0
        end = max([start + dur, lead[-1]["EndTime"]]
                  + [g["EndTime"] for g in bg])
        item = {"Text": SL.syllables_text(lead), "StartTime": start, "EndTime": end,
                "Lead": {"StartTime": start, "EndTime": start + dur,
                         "Syllables": lead}}
        if bg:
            item["Background"] = bg
        items.append(item)
    return items


def _ne_lead_cap(text: str) -> str:
    """Capitalise the first letter, leaving any punctuation before it alone."""
    for i, c in enumerate(text or ""):
        if c.isalpha():
            return text[:i] + c.upper() + text[i + 1:]
    return text


def _cut(y: dict, at: int):
    """One syllable split in two at a character, sharing its time by length.

    A bracket does not have to fall on a syllable boundary -- "(hey)" arrives
    as one token, and so does "said (hey) to" -- so the split has to be able
    to happen inside one. The time is divided by character count, which is
    wrong in the way every interpolation is wrong and right in the way that
    matters: the two halves still run end to end over the same span.
    """
    text = y.get("Text") or ""
    if at <= 0:
        return None, y
    if at >= len(text):
        return y, None
    s = float(y.get("StartTime") or 0.0)
    e = float(y.get("EndTime") or s)
    mid = s + (e - s) * (at / len(text))
    return ({**y, "Text": text[:at], "EndTime": mid, "IsPartOfWord": False},
            {**y, "Text": text[at:], "StartTime": mid})


def _despace(rows: list[dict]) -> list[dict]:
    """Close the gap a lifted bracket leaves behind.

    "Do (hey) anybody" is cut into "Do " and " anybody" with the ad-lib taken
    out from between them, and the two spaces that were on either side of it
    are now next to each other.
    """
    out = []
    for y in rows:
        text = y.get("Text") or ""
        if out and text[:1].isspace() and (out[-1].get("Text") or "")[-1:].isspace():
            text = text.lstrip()
            if not text:
                continue
            y = {**y, "Text": text}
        out.append(y)
    return out


def _ne_bg(syls: list[dict]):
    """A line's syllables split into the lead and its backing vocals.

    NetEase writes backing vocals inline and in brackets -- "best （Hahahaha）",
    "（Why） Why was it easy" -- with the brackets timed as words of their own,
    and Kugou's KRC does the same. The view draws a backing vocal as its own
    voice against the line, so they have to leave the lead and become groups in
    their own right. The brackets go with them: they are notation for an inline
    rendering, and _unwrap already strips the same thing off Apple's and amll's
    backing vocals.

    Brackets are looked for INSIDE the syllables, not only at their edges. They
    were once only recognised where a token began with one and a later token
    ended with one, which is true of the fullwidth NetEase lines this was
    written for and false of nearly every English one: "(hey) " carries a
    trailing space, so it opened a group it could not close, and the group then
    ran on until some later token happened to end in a bracket --

        Do (hey) anybody make it)   ->  lead "Do", backing "hey) anybody make it"

    swallowing the rest of the line into a voice that never sang it. Now the
    close is found wherever it is and the syllable holding it is cut there.

    A group that never closes is not a group: its text goes back to the lead
    with its bracket restored, rather than being silently dropped.
    """
    lead, groups, cur, want, opened = [], [], None, None, ""
    rest = list(syls)
    while rest:
        y = rest.pop(0)
        text = y.get("Text") or ""
        if cur is None:
            at = next((i for i, c in enumerate(text) if c in PAIRS), -1)
            if at < 0:
                lead.append(y)
                continue
            before, after = _cut(y, at)
            if before is not None and (before.get("Text") or "").strip():
                lead.append(before)
            opened = (after.get("Text") or "")[0]
            want, cur = PAIRS[opened], []
            after = _cut(after, 1)[1]
            if after is not None:
                rest.insert(0, after)
            continue
        at = text.find(want)
        if at < 0:
            if text:
                cur.append(y)
            continue
        before, after = _cut(y, at)
        if before is not None and (before.get("Text") or "").strip():
            cur.append(before)
        if cur:
            groups.append(cur)
        cur, want = None, None
        after = _cut(after, 1)[1] if after is not None else None
        if after is not None:
            rest.insert(0, after)
    if cur:
        cur[0] = {**cur[0], "Text": opened + (cur[0].get("Text") or "")}
        lead.extend(cur)
    lead = _despace(lead)
    out = []
    for cur in groups:
        cur = _despace(cur)
        cur = [y for y in cur if (y.get("Text") or "").strip()]
        if not cur:
            continue
        cur[0] = {**cur[0], "Text": _ne_lead_cap(cur[0].get("Text") or "")}
        cur[-1] = {**cur[-1], "IsPartOfWord": False}
        out.append({"Syllables": cur, "StartTime": cur[0]["StartTime"],
                    "EndTime": max(y["EndTime"] for y in cur)})
    return lead, out


def _ne_lrc_rows(text: str) -> list[tuple]:
    rows = []
    for raw in (text or "").splitlines():
        stamps = list(LRC_TAG.finditer(raw))
        if not stamps:
            continue
        body = raw[stamps[-1].end():].strip()
        if not body or NE_CREDIT.match(body):
            continue
        for m in stamps:
            rows.append((int(m.group(1)) * 60 + float(m.group(2).replace(":", ".")), body))
    rows.sort(key=lambda r: r[0])
    return rows


def _ne_romanised(doc: dict) -> bool:
    items = doc.get("Lines") if doc.get("Type") == "Static" else doc.get("Content")
    return any("TransliteratedText" in i for i in (items or []))


FAKE_EVEN = 0.006
FAKE_SHOW = 1.2


def _faked(syls: list[dict]) -> bool:
    """Whether these syllables are a line's span divided by its word count."""
    spans = []
    for y in syls:
        a, b = y.get("StartTime"), y.get("EndTime")
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return False
        spans.append(b - a)
    return (len(spans) >= 2 and max(spans) - min(spans) < FAKE_EVEN
            and min(spans) > FAKE_SHOW)


def _unfake(items: list[dict]) -> list[dict]:
    """Divided lines put back to line level, so they light as one.

    Left alone where the line carries a backing vocal: the lead's text is only
    recoverable from its syllables, and the pairing of an untimed lead with a
    timed background is a shape nothing downstream expects. Both together are
    rare enough to not be worth the second code path.
    """
    out = []
    for it in items:
        lead = it.get("Lead")
        if (isinstance(lead, dict) and not it.get("Background")
                and _faked(lead.get("Syllables") or [])):
            it = {k: v for k, v in it.items() if k != "Lead"}
        out.append(it)
    return out


def _ne_doc(d: dict) -> dict | None:
    """One NetEase lyric payload -> a lyrics document, or None if it is empty."""
    get = lambda k: ((d.get(k) or {}).get("lyric") or "")  # noqa: E731
    items = _ne_yrc(get("yrc"))
    if not items:
        rows = _ne_lrc_rows(get("lrc"))
        for i, (t, body) in enumerate(rows):
            nxt = rows[i + 1][0] if i + 1 < len(rows) else None
            end = min(nxt, t + 10.0) if nxt is not None else t + 6.0
            items.append({"Text": body, "StartTime": t, "EndTime": end})
    if not items or _instrumental(items):
        return None
    items = _unfake(_destamp(items))
    roma = _ne_lrc_rows(get("romalrc"))
    if roma:
        for it in items:
            s = it.get("StartTime")
            if s is None:
                continue
            near = min(roma, key=lambda r: abs(r[0] - s))
            if abs(near[0] - s) <= 0.35:
                it["TransliteratedText"] = near[1]
    typed = "Syllable" if any("Lead" in i for i in items) else (
        "Line" if any("StartTime" in i for i in items) else "Static")
    doc = {
        "Type": typed,
        ("Lines" if typed == "Static" else "Content"): items,
        "HasTransliterations": False,
    }
    writers = _ne_writers(get("lrc"))
    if writers:
        doc["SongWriters"] = writers
    return doc


def _ne_writers(lrc: str) -> list[str]:
    """Songwriters out of the credit lines the parse above drops.

    NetEase stamps them like lyrics -- "[00:00.000]作词 : Ester Dean" -- so they
    have to be recognised anyway to keep them from scrolling past as verse one.
    Having found them, they are worth keeping: this is the only source here
    that names a songwriter for a track Apple has never carried.
    """
    out, seen = [], set()
    for raw in (lrc or "").splitlines():
        stamps = list(LRC_TAG.finditer(raw))
        body = raw[stamps[-1].end():].strip() if stamps else raw.strip()
        m = NE_WROTE.match(body)
        if not m:
            continue
        for name in re.split(r"\s*[/、,，&]\s*", m.group(2)):
            name = name.strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
    return out


def from_netease(tid: str, meta: dict, local=None) -> dict | None:
    """NetEase Cloud Music.

    Worth a slot of its own rather than leaving it to Lyrics+: it is the only
    source here that ships a human-written romanisation (`romalrc`) on the same
    timestamps as the lyrics, which is the one thing the Genius path has to
    work hard to reconstruct.

    Word-level timing is not a property of the song here but of the particular
    release, so the search's own favourite is not necessarily the copy worth
    having: take the first candidate that is stamped word-level, and settle for
    the best-ranked line-level copy only once the alternates are exhausted.

    Falling back costs nothing extra to do well -- reaching the end of the
    candidates is what "no word-level copy exists" means -- so among line-level
    copies prefer one carrying `romalrc`, which is as unevenly distributed
    across releases as the timing is.

    An alternate is only an alternate if it ties with the best on every signal
    there is: same title, same length, same byline. Ranking below the winner
    on one of those does not make it a second pressing of this song, it makes
    it a different song -- and walking down to it is how Pipotaku's "SOUR"
    ended up showing somebody else's SOUR of the same length. The word-level
    branch has always demanded that tie; the line-level fallback took whatever
    was left, which is where the wrong lyric got in.
    """
    ranked = _ne_rank(meta or {})[:NE_TRIES]
    if not ranked:
        return None
    top = ranked[0][1]
    sids = [sid for sid, _ in ranked]
    got = _parallel({sid: (lambda s=sid: _ne_get(
        f"{NE_BASE}/api/song/lyric?id={s}&lv=1&kv=1&tv=1&yv=1&rv=1")) for sid in sids})
    fallback = None
    for sid, score in ranked:
        d = got.get(sid)
        if not d or score != top:
            continue
        doc = _ne_doc(d)
        if not doc:
            continue
        if doc["Type"] == "Syllable" and score == top:
            return doc
        if fallback is None or (_ne_romanised(doc) and not _ne_romanised(fallback)):
            fallback = doc
    return fallback


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
BLEND_TAIL = 0.35
BLEND_HOLD = 0.15
BLEND_NEAR = 0.35
BLEND_FAR = 1.5
BLEND_SAME = 0.55
BLEND_JUMP = 0.75


def _shared(a: list[str], b: list[str], pairs: dict, floor: float = BLEND_SAME) -> bool:
    """Whether two line sequences are the same song, given what matched.

    Measured against the shorter of the two, not against the base. What is
    being asked here is whether the donor is about this recording, and a donor
    can only answer with the lines it has: one that omits an ad-lib hook, or
    writes as one line what the other splits into two, covers less of the base
    without being any less the same song.

    Judged the other way it was the base's length that decided, and a donor was
    turned away for being less complete than the copy on screen. Koven's "Light
    Up" is 46 lines to NetEase's 30 -- NetEase leaves out the "High, high,
    yeah" hook entirely and splits "Who knew that we have the power to be
    whatever we wanted" across two lines. Twenty-two lines matched outright,
    which is 48% of the base and 73% of NetEase, and the base's share is the one
    that was read: the two were declared different recordings and a word-level
    sync was thrown away for a song that had none.

    Still a share and not a count, so the donor has to match most of what it
    does carry. A donor about some other recording does not quietly agree with
    two thirds of itself.
    """
    real = min(sum(1 for x in a if x), sum(1 for x in b if x))
    return bool(real) and len(pairs) >= floor * real


COHERE_MIN = 8
COHERE_TOL = 0.5
COHERE_SHARE = 0.9


def _coherent(pairs: dict, bit: list, dit: list) -> bool:
    """Whether the matched lines agree about where they are in the song.

    A wrong donor does not reach this test. Against a different recording the
    aligner finds a handful of stock lines at most, scattered anywhere -- and
    against a genuinely different song, nothing at all: the control run here
    produced zero exact matches before any timing was even looked at.
    """
    off = []
    for i, j in pairs.items():
        s, d = SL.line_start(bit[i]), SL.line_start(dit[j])
        if isinstance(s, (int, float)) and isinstance(d, (int, float)):
            off.append(d - s)
    if len(off) < COHERE_MIN:
        return False
    off.sort()
    mid = off[len(off) // 2]
    return sum(1 for x in off if abs(x - mid) <= COHERE_TOL) >= COHERE_SHARE * len(off)


def _pair(base: list[dict], other: list[dict]):
    """base line index -> other's, by text, or None if these are not one song.

    The two sides split and merge lines differently, so this aligns the text
    sequences and keeps only the stretches that match outright. Too few and the
    donor is answering about some other recording -- a cover, a live version,
    the wrong single entirely -- and every timing it offers is noise.
    """
    from difflib import SequenceMatcher

    a = [_key(SL.line_text(i)) for i in base]
    b = [_key(SL.line_text(i)) for i in other]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    pairs = {i + k: j + k
             for i, j, n in sm.get_matching_blocks() for k in range(n) if a[i + k]}
    if not _shared(a, b, pairs):
        return None
    pairs.update(_near_pairs(a, b, pairs))
    return pairs


def _restream(base: list[dict], donor: list[dict], floor: float = 0.80):
    """The donor's syllables re-cut where the BASE breaks its lines.

    Two sources can spell a song identically and still pair badly, because
    where a line ends is an editorial decision and they make it differently.
    Apple writes

        I'll give you something to hold all my disasters in
        Under your skin

    where Kugou writes both as one line, and splits "Elbows shouldn't bend
    that way / But it's okay" after "okay" instead of before it. Matched line
    by line that is a song disagreeing with itself: on STOMACH BOOK's "My
    Diorama" only 25 of 48 lines paired, under the floor that decides whether
    the two are even the same recording, and a perfectly good word-timed
    document was thrown away over punctuation.

    So the donor is read as what it really is -- one stream of timed
    syllables -- and cut again at the base's own line ends. The alignment is
    over the letters of the whole song, which makes a line break just another
    thing the two sides can disagree about, and one that no longer matters.

    Spans are forced apart afterwards so no syllable lands in two lines: a
    letter that matches in both places would otherwise time a word twice.
    """
    from difflib import SequenceMatcher

    syls = [y for it in donor
            for y in ((it.get("Lead") or {}).get("Syllables") or [])
            if isinstance(y.get("StartTime"), (int, float))]
    if not syls or not base:
        return None
    theirs, owner = [], []
    for i, y in enumerate(syls):
        k = _key(y.get("Text") or "")
        theirs.append(k)
        owner.extend([i] * len(k))
    ours, lineof = [], []
    for i, it in enumerate(base):
        k = _key(SL.line_text(it))
        ours.append(k)
        lineof.extend([i] * len(k))
    ours, theirs = "".join(ours), "".join(theirs)
    if not ours or not theirs:
        return None
    sm = SequenceMatcher(None, ours, theirs, autojunk=False)
    if sm.quick_ratio() < floor or sm.ratio() < floor:
        return None
    span: dict[int, list] = {}
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            li, si = lineof[i + k], owner[j + k]
            got = span.get(li)
            span[li] = [si, si] if got is None else [min(got[0], si), max(got[1], si)]
    seen = -1
    out = []
    for i in range(len(base)):
        got = span.get(i)
        if got is None or got[1] <= seen:
            out.append(None)
            continue
        lo = max(got[0], seen + 1)
        take = syls[lo:got[1] + 1]
        if not take:
            out.append(None)
            continue
        seen = got[1]
        end = max(float(y.get("EndTime") or y["StartTime"]) for y in take)
        out.append({"Text": SL.syllables_text(take),
                    "StartTime": float(take[0]["StartTime"]), "EndTime": end,
                    "Lead": {"Syllables": take,
                             "StartTime": float(take[0]["StartTime"]),
                             "EndTime": end}})
    return out if any(o for o in out) else None


def _timely(pairs: dict, bit: list, dit: list, tol: float = BLEND_JUMP) -> dict:
    """Drop pairings whose timing disagrees with their neighbours'.

    Text cannot place a line in a song that repeats it. "Caught in the middle"
    is ten separate lines of one Linkin Park chorus, "Two faced, caught in the
    middle" six more, and where two sources carry different numbers of repeats
    the aligner is free to pick the wrong one -- it is the same string either
    way, and the result was a chorus landing 2.5s early.

    Time tells them apart. Two real transcriptions of one recording drift
    against each other slowly, so every genuine pair in a stretch of song shares
    roughly one offset; a pair matched to the wrong repeat sits a bar or two off
    that. Compared against the median of its neighbours rather than a figure for
    the whole song, so a document that really does drift is not punished for it.
    """
    if not pairs:
        return pairs
    delta = {}
    for i, j in pairs.items():
        s, d = SL.line_start(bit[i]), SL.line_start(dit[j])
        if isinstance(s, (int, float)) and isinstance(d, (int, float)):
            delta[i] = d - s
    keys = sorted(delta)
    if len(keys) < 4:
        return pairs
    out = dict(pairs)
    for pos, i in enumerate(keys):
        near = sorted(delta[k] for k in keys[max(0, pos - 3):pos + 4] if k != i)
        if near and abs(delta[i] - near[len(near) // 2]) > tol:
            out.pop(i, None)
    return out


def _between(anchors: list, t: float) -> float:
    """`t` on the base's clock, read onto the donor's.

    The two do not differ by a constant -- where they cut the song into lines
    differently the gap drifts -- so a time is placed by the matched lines
    either side of it, and held to the nearest one's offset beyond both ends.
    """
    if not anchors:
        return t
    if t <= anchors[0][0]:
        return t + anchors[0][1] - anchors[0][0]
    if t >= anchors[-1][0]:
        return t + anchors[-1][1] - anchors[-1][0]
    k = bisect.bisect_left([a[0] for a in anchors], t)
    (s0, d0), (s1, d1) = anchors[k - 1], anchors[k]
    if s1 == s0:
        return d1
    return d0 + (d1 - d0) * (t - s0) / (s1 - s0)


def _retime(a: list[str], b: list[str], bit: list, dit: list,
            mate: dict, tol: float = BLEND_JUMP) -> dict:
    """Re-pair lines the aligner put on the wrong repeat of themselves.

    Aligning by text alone cannot tell one chorus from the next, and the
    aligner reads the two sides in order, so it can only use each donor line
    once and takes them in the order it meets them. Where the base sings a line
    more times than the donor writes it, that pairs early repeats with late
    ones: on a 40-line track here, two lines were matched to donor lines 45
    seconds away while the donor lines actually beside them went unused.

    _timely throws those out, correctly -- but a rejected pair simply became no
    pair, and everything after the last surviving anchor fell back to
    interpolated word timing. The whole back half of that song lost its
    syllables while the donor was holding them.

    So: for a line still unpaired, look for a donor line with the SAME text
    whose time agrees with where the surviving anchors say it should be, and
    take the closest one within `tol`. Exact text only, and a donor line only
    once -- this runs after the decision about whether the two documents are
    the same recording has already been made, and must not be able to revisit
    it.
    """
    anchors = sorted(
        (s, d) for i, j in mate.items()
        for s in [SL.line_start(bit[i])] for d in [SL.line_start(dit[j])]
        if isinstance(s, (int, float)) and isinstance(d, (int, float)))
    if not anchors:
        return {}
    where = {}
    for j, key in enumerate(b):
        if key:
            where.setdefault(key, []).append(j)
    taken = set(mate.values())
    out: dict[int, int] = {}
    for i, key in enumerate(a):
        if i in mate or not key:
            continue
        s = SL.line_start(bit[i])
        if not isinstance(s, (int, float)):
            continue
        want = _between(anchors, s)
        best, gap = None, tol
        for j in where.get(key, ()):
            if j in taken:
                continue
            d = SL.line_start(dit[j])
            if isinstance(d, (int, float)) and abs(d - want) < gap:
                best, gap = j, abs(d - want)
        if best is not None:
            out[i] = best
            taken.add(best)
    return out


def _outliers(votes: dict) -> set:
    """Whose time sits further than BLEND_FAR from every other vote.

    A vote that disagrees with one neighbour but not the other is a rounding
    difference; one that disagrees with all of them is a different clock, and
    including it in a min() would drag the whole line to where nobody sang.
    """
    return {k for k, v in votes.items()
            if len(votes) > 1 and all(abs(v - u) > BLEND_FAR
                                      for j, u in votes.items() if j != k)}


def _agree(starts: dict) -> float:
    """Where a line begins, given up to three opinions about it.

    Two rules, both the caller's:

      * the ones that are not too far out are believed, and the earliest of
        them wins -- a line that lights slightly early reads as anticipation,
        one that lights late reads as lag;
      * where all three survive and still disagree by more than a rounding
        difference, the middle one wins instead. The earliest of three that
        genuinely disagree is the most likely to be the odd one out, and
        picking it would let the least reliable vote decide the line.

    With everyone an outlier -- three clocks, no two of them close -- there is
    nothing to average, and the line sync gets the line: it is the one that
    came with the words, so it is the one that at least matches what is on
    screen.
    """
    keep = {k: v for k, v in starts.items() if k not in _outliers(starts)}
    if not keep:
        keep = {"base": starts["base"]} if "base" in starts else starts
    vals = sorted(keep.values())
    if len(vals) >= 3 and vals[-1] - vals[0] > BLEND_NEAR:
        return vals[len(vals) // 2]
    return vals[0]


def _last_end(ends: list[float]) -> float | None:
    """The line's end: the soonest anyone measured.

    The caller has already carried every end onto the line's agreed start, so
    what is being compared here is how long each source says the line runs.
    That is the whole of what an end means once the line has moved; two sources
    disagreeing about where in the song it sits is the start vote's business,
    and letting that disagreement in here again counted it twice.

    The soonest, because all three pad and none of them pad the same lines.
    Apple holds a line open to where it should stop being displayed, QQ pushes
    its last stamp out towards the line after, NetEase invents an end from the
    next line's start when it has none of its own. Taking the latest of two
    opinions therefore did not find the line's end at all -- it found whichever
    source had padded that particular line more. On The Hills it ran a
    seven-word line 4.2s past its last word and held "Yeah", which is sung for
    .6s, on screen for 3.2s. Over the tracks measured that left 27% of blended
    lines still lit more than .4s after the last word had finished filling,
    against 0.7% of the Apple document the blend was built from: a line already
    fully drawn, sitting there into the next one.

    Nothing measured is lost by taking the soonest, because the caller then
    pushes the end back out to the last syllable it is actually going to draw.
    A sustain that a source really did measure is in those syllables and stays
    on screen for as long as it was held; what the soonest end drops is only
    the stretch past the last word, which nobody is singing.
    """
    ends = [e for e in ends if isinstance(e, (int, float))]
    return min(ends) if ends else None


def _words_from(doc) -> str:
    """What to call the document the lines were taken from."""
    return {"aml": "Apple Music", "spl": "Spicy Lyrics community",
            "spt": "Spotify"}.get(str((doc or {}).get("source") or ""),
                                  "Spicy Lyrics")


BASE_WORDS = {"youly": "Apple Music", "bini": "Apple Music",
              "amll": "amll-ttml-db", "unison": "Unison", "kugou": "Kugou",
              "netease": "NetEase", "lrclib": "LRCLIB", "local": "this machine"}


def _blended(tid: str, meta: dict, local, timing, whose: str,
             alone: str, above=None) -> dict | None:
    """Apple Music's lines with somebody else's word timing under them.

    Two documents, not three. NetEase used to vote here on where each line
    begins, and it was a bad third opinion: it is the source least likely to
    be holding the same master, so its vote pulled line starts around on
    songs the other two already agreed about.

    Asked one upstream at a time and reconciled here rather than taking
    whichever answered first, and independent of those upstreams' own on/off
    switches: this is a source in its own right, not a mode of the others.

    The lines do not have to be Apple's. `above` holds what the sources ranked
    ABOVE this blend came back with -- BiniLyrics' TTML, amll's, Lyrics+'s own
    pick -- already fetched, because those sources are providers in their own
    right and were asked in the round before this one. Any of them can be the
    base, and a source the user put higher wins a tie against one they did
    not. Only quality outranks that: nothing here will lay word timing under
    line-level lines while word-level lines are on the table.

    `local` is whatever the caller already holds -- in practice Spicy Lyrics'
    own document, which is usually Apple Music too and usually the better copy
    of it. It is offered first: LyricsPlus' Apple endpoint is a scrape and
    answers line-level for tracks Spicy Lyrics has word-level, so ignoring
    what was already on the machine meant blending against the weaker of two
    Apples -- and, when that scrape failed outright, falling all the way to
    LRCLIB while a perfectly good Apple sync sat unused. It matters more for
    the Chinese catalogue than it looks: LyricsPlus' Apple side answers for
    almost none of it, so on those tracks the lines can only come from here.

    The Apple ask of its own is skipped when something already in hand is
    word-level, since nothing that scrape returns could displace it.
    """
    ready = [SL.payload(d) for d in list((above or {}).values()) + [local] if d]
    covered = any(quality(d) == "syllable" for d in ready)
    got = _parallel({
        **({} if covered else
           {"apple": lambda: from_youly(tid, meta, source="apple")}),
        "timed": lambda: timing(tid, meta),
    })
    local = SL.payload(local) if local else None
    picks = [(local, _words_from(local), "spicy")]
    for name, doc in (above or {}).items():
        picks.append((SL.payload(doc), BASE_WORDS.get(name, name), name))
    picks.append((got.get("apple"), "Apple Music", "youly"))
    picks = [(d, w, o) for d, w, o in picks if d and quality(d) != "none"]
    picks.sort(key=lambda p: RANK.get(quality(p[0]), 0), reverse=True)
    if not picks:
        lr = from_lrclib(tid, meta)
        picks = [(lr, "LRCLIB", "lrclib")] if lr else []
    if not picks:
        return None
    base, words, origin = picks[0]
    out = _blend(base, words, got["timed"], None, origin, whose)

    rank = lambda d: RANK.get(quality(d), 0) if d else 0        # noqa: E731
    if got["timed"] and rank(got["timed"]) > rank(out):
        out = dict(SL.payload(got["timed"]))
        out["_alone"] = alone
    return out


def from_blend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """Apple Music's lines with QQ Music's word timing, which is the pairing
    LyricsPlus itself makes."""
    return _blended(tid, meta, local,
                    lambda t, m: from_youly(t, m, source="qq"), "QQ Music",
                    "youly", above)


def from_kublend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """The same, with Kugou underneath instead.

    Kugou and QQ are very largely the same word-timed data -- on eight CJK
    tracks measured here, six agreed syllable for syllable to within seventy
    milliseconds -- so this is not a second opinion so much as a second way
    in. It matters because the doors fail separately: Kugou answered for ten
    of those ten tracks where QQ answered for eight.
    """
    return _blended(tid, meta, local, from_kugou, "Kugou", "kugou", above)


from_blend.wants_above = True
from_kublend.wants_above = True


def _blend(base: dict, words: str, qq: dict | None, ne: dict | None,
           origin: str = "spicy", whose: str = "QQ Music") -> dict | None:
    """The documents reconciled into one. Split out so it can be tested on
    fixed inputs rather than on whatever the servers feel like saying.

    `ne` is a third opinion on line starts. Nothing passes one any more; the
    parameter stays because every "who moved this line" branch below is
    written around having more than one opinion to weigh, and collapsing that
    to a single voice would rewrite the reconciling rather than simplify it.
    """
    bit = _items(SL.payload(base))
    if not bit:
        return None
    qit = _items(SL.payload(qq)) if qq else []
    nit = _items(SL.payload(ne)) if ne else []
    qmap = _timely(_pair(bit, qit), bit, qit) if qit else None
    if qit and len(qmap or ()) < 0.6 * len(bit):
        # The two disagree about where lines end more than about the words.
        # Read the donor as the stream it is and cut it where we cut ours.
        recut = _restream(bit, qit)
        if recut is not None:
            qit = recut
            qmap = {i: i for i, q in enumerate(recut) if q}
    nmap = _timely(_pair(bit, nit), bit, nit) if nit else None
    ne_ends = bool(ne) and quality(ne) == "syllable"

    used: set[str] = set()
    out, worded = [], 0
    for i, it in enumerate(bit):
        b_s, b_e = SL.line_start(it), _line_end(it)
        b_nxt = SL.line_start(bit[i + 1]) if i + 1 < len(bit) else None
        q = qit[qmap[i]] if qmap and i in qmap else None
        n = nit[nmap[i]] if nmap and i in nmap else None
        q_s, q_e = (SL.line_start(q), _line_end(q)) if q else (None, None)
        n_s = SL.line_start(n) if n else None

        starts = {k: v for k, v in (("base", b_s), ("qq", q_s), ("ne", n_s))
                  if isinstance(v, (int, float))}
        new = {k: v for k, v in it.items()
               if k not in ("StartTime", "EndTime", "Lead", "Background")}
        new["Text"] = SL.line_text(it)
        if not starts:
            out.append(new)
            continue
        start = _agree(starts)
        for who in ("qq", "ne"):
            if who not in starts:
                continue
            rest = {k: v for k, v in starts.items() if k != who}
            if not rest or abs(_agree(rest) - start) > 1e-6:
                used.add(who)

        qby = (start - q_s) if isinstance(q_s, (int, float)) else 0.0
        syls = _relay(new["Text"], ((q or {}).get("Lead") or {}).get("Syllables") or [])
        if syls:
            syls = [_slide(y, qby) for y in syls]
            used.add("qq")
        else:
            own = (it.get("Lead") or {}).get("Syllables") or []
            if own and isinstance(b_s, (int, float)):
                syls = [_slide(y, start - b_s) for y in own]
            elif isinstance(n_s, (int, float)):
                lent = _relay(new["Text"],
                              ((n or {}).get("Lead") or {}).get("Syllables") or [])
                if lent:
                    syls = [_slide(y, start - n_s) for y in lent]
                    used.add("ne")

        n_e = (_line_end(n) if n else None) if ne_ends else None
        ends = {}
        for who, e, was in (("base", b_e, b_s), ("qq", q_e, q_s), ("ne", n_e, n_s)):
            if isinstance(e, (int, float)) and isinstance(was, (int, float)):
                ends[who] = e + (start - was)
        end = _last_end(list(ends.values()))
        for who in ("qq", "ne"):
            if who not in ends:
                continue
            rest = [v for k, v in ends.items() if k != who]
            if not rest or abs((_last_end(rest) or end) - end) > 1e-6:
                used.add(who)
        if syls:
            end = max(end, syls[-1]["EndTime"]) if end is not None \
                else syls[-1]["EndTime"]
        if end is None or end <= start:
            end = (syls[-1]["EndTime"] if syls else start + 4.0)
        end = max(end, start + 0.05)

        # Where the base says the singing stops, believe it. QQ's and Kugou's
        # words tile their line -- every word runs until the next one starts,
        # and the last one runs to wherever the line was cut -- so a line whose
        # voice stops early is held lit through the gap after it. Apple times
        # the end of the singing instead. On NF's "If You Want Love", "Ask me,
        # how I'm doing" ends at 24.32 by Apple and at 24.87 by Kugou, which is
        # exactly where the next line begins.
        #
        # Only where the base's own end stands clear of the next line: an end
        # that IS the next line's start is a tile too, and swapping one for the
        # other gains nothing.
        own = ends.get("base")
        sung = max([y["EndTime"] for y in syls[:-1]] or [start]) if syls else start
        if (own is not None and isinstance(b_e, (int, float))
                and isinstance(b_nxt, (int, float)) and b_nxt - b_e >= BLEND_TAIL
                and end - own > BLEND_HOLD
                # Never into the words. Only the last one's tail is stretched
                # by the tiling; if the base wants to end before the word
                # before it has finished, the two do not agree about this line
                # and the base's end is not describing it.
                and (not syls or own >= max(sung, syls[-1]["StartTime"] + 0.05))):
            end = max(own, start + 0.05)
            if syls and syls[-1]["EndTime"] > end:
                syls = syls[:-1] + [{**syls[-1], "EndTime": end}]

        new["StartTime"], new["EndTime"] = start, end
        if syls:
            new["Lead"] = {"StartTime": start, "EndTime": end, "Syllables": syls}
            worded += 1
        bg = [g for g in (it.get("Background") or []) if isinstance(g, dict)]
        if bg and isinstance(b_s, (int, float)):
            new["Background"] = [_slide(g, start - b_s) for g in bg]
        elif bg:
            new["Background"] = bg
        out.append(new)

    if not out:
        return None
    typed = "Syllable" if worded else ("Line" if any("StartTime" in i for i in out)
                                       else "Static")
    doc = {k: v for k, v in SL.payload(base).items()
           if k not in ("Type", "Content", "Lines", "_via")}
    doc["Type"] = typed
    doc["Lines" if typed == "Static" else "Content"] = out
    if not doc.get("SongWriters"):
        writers = (SL.payload(ne or {}).get("SongWriters")
                   or SL.payload(qq or {}).get("SongWriters"))
        if writers:
            doc["SongWriters"] = writers
    parts = [n for n, key in ((whose, "qq"), ("NetEase", "ne")) if key in used]
    if parts:
        doc["_via"] = " + ".join([words] + parts)
    else:
        doc["_alone"] = origin
        if origin == "youly":
            doc["_via"] = "apple"
        else:
            doc.pop("_via", None)
    return doc


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
ALIGN_DIR = _cache_root() / "aligned"
SOURCE_FILE = _cache_root() / "sources.json"


def pinned_source(tid: str) -> str:
    """The copy this track was aligned against last time, or ''."""
    if not tid:
        return ""
    try:
        got = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
        return str(got.get(tid) or "")
    except Exception:
        return ""


def pin_source(tid: str, url: str) -> None:
    """Remember that this track was aligned against `url`.

    An empty `url` forgets it, which is what a caller does when the copy it
    remembered has gone away.
    """
    if not tid:
        return
    try:
        try:
            got = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
        except Exception:
            got = {}
        if not isinstance(got, dict):
            got = {}
        if url:
            got[tid] = url
        else:
            got.pop(tid, None)
        SOURCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SOURCE_FILE.write_text(json.dumps(got), encoding="utf-8")
    except Exception:
        pass
ALIGN_REV = 4


def _align_path(tid: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tid or "unknown")[:64]
    return ALIGN_DIR / f"{safe}.json"


def save_aligned(tid: str, doc: dict, hand: str = "") -> bool:
    """Keep a document for this track. True if it went down.

    `hand` names the file it was dropped in from, and marks it as somebody's
    own work rather than this machine's alignment. The two live in the same
    place because they are the same thing to everyone downstream -- a document
    held for one track, ranked as "Aligned here" -- but they are not the same
    thing to throw away: an alignment costs minutes and a GPU to make again,
    and a dropped file is still sitting on the disk where it came from.
    """
    if not tid or not isinstance(doc, dict):
        return False
    try:
        ALIGN_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"rev": ALIGN_REV, "at": time.time(), "doc": doc}
        if hand:
            rec["hand"] = str(hand)
        _align_path(tid).write_text(json.dumps(rec), encoding="utf-8")
        return True
    except Exception:
        return False


def _align_rec(tid: str) -> dict | None:
    try:
        rec = json.loads(_align_path(tid).read_text(encoding="utf-8"))
    except Exception:
        return None
    if int(rec.get("rev") or 0) != ALIGN_REV:
        return None
    return rec if isinstance(rec.get("doc"), dict) else None


def aligned(tid: str) -> dict | None:
    """The document held for this track, if there is one from this revision."""
    rec = _align_rec(tid)
    return rec.get("doc") if rec else None


def forget_aligned(tid: str, hand_only: bool = True) -> bool:
    """Drop the document held here for a track. True if one went.

    Refuses to touch an alignment this machine made unless asked outright:
    reloading the lyrics is a thing people do to shake a bad answer loose, and
    it must not quietly cost an hour of GPU time. A file somebody dropped in
    is a different matter -- throwing it away loses nothing that is not still
    on their disk.
    """
    rec = _align_rec(tid)
    if rec is None or (hand_only and not rec.get("hand")):
        return False
    try:
        _align_path(tid).unlink()
        return True
    except OSError:
        return False


def from_local(tid: str, meta: dict, local=None) -> dict | None:
    """This machine's own alignment of the song, if it has made one.

    A provider like any other, which is what makes the running order mean
    something here -- and it means more here than for the rest. An alignment is
    right to about a fifth of a second across a whole song and then, on a line
    the song repeats, occasionally many seconds out; see the note at the foot of
    local_align.py. Sitting last by default, as it does, that trade only ever
    applies to songs where the alternative was no word timing at all, because
    fallback() will not let a provider replace word timing with word timing
    unless the user has ranked it above. Drag it up the list in the menu and it
    wins those ties instead.

    Free to ask: it is a file this machine wrote, so unlike every other entry
    here it costs no request and cannot fail slowly.
    """
    rec = _align_rec(tid)
    if rec is None:
        return None
    doc = rec["doc"]
    return {**doc, "_hand": rec["hand"]} if rec.get("hand") else doc


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
UNISON_BASE = "https://unison.boidu.dev"
BINI_BASE = "https://lyrics-api.binimum.org"
BINI_HOST = "binimum.org"
KUGOU_SEARCH = "https://mobileservice.kugou.com/api/v3/search/song"
KUGOU_KRCS = "https://krcs.kugou.com/search"
KUGOU_DOWN = "https://lyrics.kugou.com/download"
NEAR = 6.0


def _json(url: str, accept: str = "application/json"):
    """A JSON GET that answers None instead of raising, the way _get does."""
    raw = _get(url, accept)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _near(theirs, want: float, slack: float = NEAR) -> bool:
    """Whether two durations are the same recording's, when both are known."""
    try:
        theirs = float(theirs or 0)
    except (TypeError, ValueError):
        return False
    return not (want > 0 and theirs > 0) or abs(theirs - want) <= slack


def _same_song(theirs: str, ours: str) -> bool:
    """Whether two titles name the same song, allowing for a longer one.

    Deliberately generous in ONE direction only: a source is allowed to have
    "Stronger (Radio Edit)" where we asked for "Stronger", because that is
    the same recording described at more length. It is not allowed to answer
    for something that merely contains our words.
    """
    a, b = _norm(theirs), _norm(ours)
    if not a or not b:
        return False
    return a == b or (len(b) >= 4 and b in a) or (len(a) >= 4 and a in b)


def _written(text, kind: str = "") -> dict | None:
    """A provider's lyric text in whichever of the three shapes it came in.

    Unison stores TTML, LRC and plain text side by side and says which in a
    field; the field is believed, but the text is checked anyway, because a
    document filed under the wrong one is a rendering of nothing.
    """
    text = (text.decode("utf-8", "replace") if isinstance(text, bytes) else
            str(text or "")).strip()
    if not text:
        return None
    kind = (kind or "").lower()
    if kind == "ttml" or text[:1] == "<":
        return parse_ttml(text)
    if kind in ("lrc", "elrc") or re.match(r"\s*\[\d+:\d\d", text):
        return parse_lrc(text)
    return parse_lrc("", text)


def _unison_doc(rec: dict) -> dict | None:
    """One Unison record as a document, with the person who timed it on it.

    Unison names its submitter in the record and nowhere in the TTML, so a
    document that went through the parser alone arrived anonymous -- and on
    this source, of all of them, that is the credit that matters. Nobody was
    paid to time these: somebody sat down and did it, and the only place they
    are named is a field the lyrics do not carry.
    """
    doc = _written(rec.get("lyrics"), str(rec.get("format") or ""))
    if doc is None:
        return None
    who = rec.get("submitter")
    name = (str(who.get("displayName") or who.get("name") or "").strip()
            if isinstance(who, dict) else str(who or "").strip())
    if name:
        doc["_maker"] = name
    return doc


def from_unison(tid: str, meta: dict, local=None) -> dict | None:
    """Unison -- the Better Lyrics community's own database.

    The only source in this chain whose documents were typed in by the people
    reading them. There is no catalogue behind it and nothing is scraped: a
    song is there because somebody sat down and timed it, which is exactly
    why it is worth asking. It answers for tracks no licensed source carries,
    and it answers in TTML with real word timing.

    The same thing makes it the one source here that can be somebody's first
    attempt, so a hit found by searching has to clear a duration check and
    carry its own votes; Unison scores every document low/medium/high and the
    hint is taken. A direct hit is trusted as it stands -- the server already
    matched it -- but its duration is still checked, because the query is
    name-shaped and names repeat.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title:
        return None
    want = float(meta.get("length") or 0)
    # No duration in the question. Unison matches it exactly rather than
    # nearly, and its records often carry none at all, so sending one 404s a
    # song it has: "uncomfy" answers on song and artist and does not answer
    # for the same pair with its own length attached. The check still happens
    # here, against whatever length comes back.
    q = _qs(song=title, artist=artist, album=meta.get("album"))
    got = _json(f"{UNISON_BASE}/lyrics?{q}")
    rec = (got or {}).get("data") if isinstance(got, dict) else None
    if isinstance(rec, list):
        rec = rec[0] if rec else None
    if isinstance(rec, dict) and rec.get("lyrics") and _near(rec.get("duration"), want):
        return _unison_doc(rec)
    if not artist:
        return None
    got = _json(f"{UNISON_BASE}/lyrics/search?q="
                f"{urllib.parse.quote(f'{title} {artist}')}")
    rows = (got or {}).get("data") if isinstance(got, dict) else None
    rank = {"high": 2, "medium": 1, "low": 0}
    best = None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        if not (_same_song(row.get("song") or "", title)
                and _near(row.get("duration"), want)):
            continue
        score = (rank.get(str(row.get("confidence") or "").lower(), 0),
                 float(row.get("matchScore") or 0), int(row.get("voteCount") or 0))
        if best is None or score > best[0]:
            best = (score, row["id"])
    if best is None:
        return None
    got = _json(f"{UNISON_BASE}/lyrics/{urllib.parse.quote(str(best[1]))}")
    rec = (got or {}).get("data") if isinstance(got, dict) else None
    return _unison_doc(rec) if isinstance(rec, dict) else None


def from_bini(tid: str, meta: dict, local=None) -> dict | None:
    """BiniLyrics -- Apple Music's TTML, reached by a different key.

    The words are the same ones Lyrics+ hands back when it is told
    `source=apple`, so this is not a new catalogue. It is a second door on
    the same one, and doors are what fail: every other source here is found
    by a Spotify id or by the words in a title, and this one indexes by ISRC,
    which names the recording itself. Where it has the ISRC it cannot answer
    for the wrong song, and where it does not, the name query is checked
    against the duration like everything else.

    The lyrics live at a URL of their own, one fetch further on. It is
    followed only when it stays on the host that named it -- a document is
    worth having, a redirect somewhere else is not.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    isrc = str(meta.get("isrc") or "").strip()
    if not isrc and not (title and artist):
        return None
    want = float(meta.get("length") or 0)
    q = (_qs(isrc=isrc) if isrc else
         _qs(track=title, artist=artist, album=meta.get("album"),
             duration=int(round(want)) if want > 0 else None))
    got = _json(f"{BINI_BASE}/?{q}")
    rows = (got or {}).get("results") if isinstance(got, dict) else None
    best = None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("lyricsUrl"):
            continue
        if not isrc:
            if not (_same_song(row.get("track_name") or "", title)
                    and _near(row.get("duration"), want)):
                continue
        score = (1 if str(row.get("timing_type") or "").lower() == "word" else 0,
                 -abs(float(row.get("duration") or 0) - want) if want > 0 else 0)
        if best is None or score > best[0]:
            best = (score, str(row["lyricsUrl"]))
    if best is None:
        return None
    url = best[1]
    host = urllib.parse.urlsplit(url)
    if host.scheme != "https" or not (host.hostname or "").endswith(BINI_HOST):
        return None
    raw = _get(url, "application/xml")
    return parse_ttml(raw) if raw else None


# --------------------------------------------------------------------------
# KRC is Kugou's own lyric format and the only word-timed one it serves. It
# arrives base64'd, with a four-byte "krc1" header, XOR'd against a fixed
# sixteen-byte key and then deflated -- an obfuscation rather than a secret,
# published the same way in every client that reads it.
KRC_KEY = bytes((64, 71, 97, 119, 94, 50, 116, 71,
                 81, 54, 49, 45, 206, 210, 110, 105))
KRC_LINE = re.compile(r"^\[(\d+),(\d+)\]")
KRC_TOK = re.compile(r"<(\d+),(\d+),\d+>([^<]*)")


def _krc(blob: str) -> str | None:
    """The KRC behind one download response, or None if it is not one."""
    import base64
    import zlib

    try:
        raw = base64.b64decode(blob or "", validate=False)
    except Exception:
        return None
    if raw[:4] != b"krc1":
        return None
    body = bytes(b ^ KRC_KEY[i % 16] for i, b in enumerate(raw[4:]))
    try:
        return zlib.decompress(body).decode("utf-8", "replace")
    except Exception:
        return None


def _krc_items(text: str) -> list[dict]:
    """KRC -> timed items.

    A line is `[start,length]` and then one `<offset,length,0>` per syllable,
    the offset measured from the line rather than from the song. Kugou writes
    the credits as lyric lines like NetEase does -- and, unlike NetEase, often
    writes the artist and title as the first sung line too, timed across the
    intro -- so the same credit filter runs here.

    Returns the lines and whoever those credits named, since the credit lines
    are the only place Kugou says.
    """
    items, wrote = [], []
    for raw in (text or "").splitlines():
        m = KRC_LINE.match(raw)
        if not m:
            continue
        toks = KRC_TOK.findall(raw[m.end():])
        if not toks:
            continue
        body = "".join(t[2] for t in toks).strip()
        if not body or NE_CREDIT.match(body):
            # Dropped from the lyrics, kept as what it says. Kugou stamps the
            # credits like verses -- "Lyrics by：Vivian Weeks" timed across the
            # intro -- and they are the only place it names a writer.
            said = NE_WROTE.match(body) if body else None
            for name in (re.split(r"\s*[/、,，&]\s*", said.group(2)) if said else []):
                name = name.strip()
                if name and name not in wrote:
                    wrote.append(name)
            continue
        start, length = int(m.group(1)) / 1000.0, int(m.group(2)) / 1000.0
        syls = []
        for off, dur, word in toks:
            got = word.rstrip()
            if not got:
                if syls:
                    syls[-1]["IsPartOfWord"] = False
                continue
            at = start + int(off) / 1000.0
            syls.append({"Text": got, "StartTime": at,
                         "EndTime": at + int(dur) / 1000.0,
                         "IsPartOfWord": word == got})
        if not syls:
            continue
        lead, bg = _ne_bg(syls)
        if not lead:
            lead, bg = syls, []
        lead[-1] = {**lead[-1], "IsPartOfWord": False}
        end = max([start + length, lead[-1]["EndTime"]] + [g["EndTime"] for g in bg])
        item = {"Text": SL.syllables_text(lead), "StartTime": start, "EndTime": end,
                "Lead": {"StartTime": start, "EndTime": start + length,
                         "Syllables": lead}}
        if bg:
            item["Background"] = bg
        items.append(item)
    return items, wrote


NO_WORDS = re.compile(
    r"纯音乐|純音樂|此歌曲为没有填词|沒有填詞|无歌词|暫無歌詞|暂无歌词|"
    r"^\W*instrumental\W*$|^\W*no lyrics\W*$", re.I)


def _instrumental(items: list[dict]) -> bool:
    """Whether this document is a note saying the track has no words in it.

    Kugou and NetEase both answer for an instrumental with a single line
    reading 纯音乐，请欣赏 -- "instrumental, please enjoy" -- stamped across the
    whole song. Taken at face value that is a word-timed document, and a
    word-timed document beats every real lyric further down the chain: on
    passengerprincess' FINALE it was on the screen as the lyric while NetEase
    was holding the words.

    Only ever a note: three lines at most, and one of them has to say it.
    """
    if not items or len(items) > 3:
        return False
    text = " ".join(SL.line_text(i) or "" for i in items).strip()
    return bool(text) and bool(NO_WORDS.search(text))


def _krc_head(items: list[dict], title: str, artist: str) -> list[dict]:
    """The lyrics with Kugou's own title card taken off the front.

    Nearly every KRC opens with "artist - title" timed across the intro, as a
    line of the song. It is not one -- nobody sings it -- and left in it takes
    the whole introduction as its own line and lights up while the music is
    still playing.
    """
    while items:
        got = _norm(SL.line_text(items[0]))
        if got and got in (_norm(f"{artist}{title}"), _norm(f"{title}{artist}")):
            items = items[1:]
            continue
        break
    return items


def _kugou_hits(title: str, artist: str, want: float) -> list[tuple]:
    """(hash, milliseconds) for the Kugou recordings that look like this one.

    Kugou's search answers for anything, so nothing is believed on the name
    alone: a hit needs the duration, and the title has to survive being read
    out of "artist - title", which is the only place the search puts it.
    """
    q = urllib.parse.quote(f"{title} {artist}".strip())
    got = _json(f"{KUGOU_SEARCH}?format=json&keyword={q}&page=1&pagesize=10"
                "&showtype=1")
    info = ((got or {}).get("data") or {}).get("info") or []
    out = []
    for row in info:
        if not isinstance(row, dict) or not row.get("hash"):
            continue
        dur = float(row.get("duration") or 0)
        name = str(row.get("songname") or "")
        if not name:
            name = str(row.get("filename") or "").split(" - ", 1)[-1]
        if not (_same_song(name, title) and _near(dur, want)):
            continue
        out.append((abs(dur - want) if want > 0 else 0.0,
                    str(row["hash"]), int(dur * 1000)))
    out.sort()
    return [(h, ms) for _d, h, ms in out]


def from_kugou(tid: str, meta: dict, local=None) -> dict | None:
    """Kugou, by way of KRC.

    Worth a slot of its own: Kugou times its lyrics per syllable, and its
    catalogue is the Chinese one, which is the half of the library the
    English-speaking sources here are worst at. Where amll and Lyrics+ have
    nothing for a Mandarin or Cantonese track this frequently has it, word by
    word, and where they do have it this is a second opinion for the blend.

    Three requests deep -- find the recording, ask which lyric documents are
    filed against it, download one -- so the walk stops at the first release
    that answers rather than opening every one.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title:
        return None
    want = float(meta.get("length") or 0)
    for hashed, ms in _kugou_hits(title, artist, want)[:3]:
        got = _json(f"{KUGOU_KRCS}?ver=1&man=yes&client=mobi&hash={hashed}"
                    f"&duration={ms}&keyword={urllib.parse.quote(title)}")
        for cand in ((got or {}).get("candidates") or [])[:2]:
            if not isinstance(cand, dict) or not cand.get("id"):
                continue
            got = _json(f"{KUGOU_DOWN}?ver=1&client=pc"
                        f"&id={urllib.parse.quote(str(cand['id']))}"
                        f"&accesskey={urllib.parse.quote(str(cand.get('accesskey') or ''))}"
                        "&fmt=krc&charset=utf8")
            krc = _krc((got or {}).get("content") or "") if got else None
            items, wrote = _krc_items(krc) if krc else ([], [])
            items = _krc_head(items, title, artist)
            if not items or _instrumental(items):
                continue
            doc = {"Type": "Syllable", "Content": _destamp(items),
                   "HasTransliterations": False}
            if wrote:
                doc["SongWriters"] = wrote
            return doc
    return None


PROVIDERS = [("amll", from_amll), ("blend", from_blend),
             ("kublend", from_kublend), ("youly", from_youly),
             ("bini", from_bini), ("unison", from_unison),
             ("kugou", from_kugou), ("netease", from_netease),
             ("lrclib", from_lrclib), ("local", from_local)]


def _rejoin(mora: str, worded: str) -> str:
    """NetEase's readings, cut into words the way a segmenter would cut them.

    romalrc is written one mora at a time -- "u sse e wa", "ha n pa na ra" --
    which is accurate and nearly unreadable: under a lyric it looks like the
    song is being spelled out rather than sung. A segmenter knows where the
    words end but gets the readings themselves wrong often enough to matter
    (愛して as "itoshite", 頑張って as "ganbatsute", both wrong here), so the
    two are combined: NetEase says what the sounds are, the segmenter says
    where to break them.

    Both sides are compared with their spaces removed, and only the stretches
    that agree outright are re-cut -- where they disagree, NetEase's own
    spacing stands. Guessing a word boundary is not worth a wrong reading.
    """
    from difflib import SequenceMatcher

    flat = mora.replace(" ", "")
    if not flat or not worded:
        return mora
    stops, at = set(), 0
    for w in worded.split():
        at += len(w)
        stops.add(at)
    sm = SequenceMatcher(None, flat.lower(), worded.replace(" ", "").lower(),
                         autojunk=False)
    if sm.ratio() < 0.82:
        return mora
    same = {}
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            same[i + k] = j + k
    out, cut = [], 0
    for i in range(len(flat)):
        j = same.get(i)
        if j is None or (j + 1) not in stops:
            continue
        nxt = flat[i + 1] if i + 1 < len(flat) else "a"
        if not flat[i].isalnum() or not nxt.isalnum():
            continue
        out.append(flat[cut:i + 1])
        cut = i + 1
    out.append(flat[cut:])
    joined = " ".join(x for x in out if x)
    return joined or mora


def netease_roman(meta: dict) -> dict:
    """{lyric line -> romanisation} from NetEase, for a track it did not supply.

    Keyed by text rather than by time because the caller is holding somebody
    else's document: the two clocks have nothing to do with each other, but the
    words are the same words. Same shape as the Genius map, so it drops into the
    same slot.
    """
    doc = from_netease("", meta or {})
    if not doc:
        return {}
    items = doc.get("Content") or doc.get("Lines") or []
    kks = SL._kakasi()
    out = {}
    for it in items:
        text = (it.get("Text") or "").strip()
        roman = (it.get("TransliteratedText") or "").strip()
        if not text or not roman or text == roman:
            continue
        if kks is not None:
            try:
                worded = " ".join(x.get("hepburn", "") for x in kks.convert(text))
                roman = _rejoin(roman, worded)
            except Exception:
                pass
        for i, c in enumerate(roman):
            if c.isalpha():
                roman = roman[:i] + c.upper() + roman[i + 1:]
                break
        out[text] = roman
    return out


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def _cache_path(tid: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tid or "unknown")[:64]
    return CACHE_DIR / f"{safe}.json"


def _touch(path: pathlib.Path) -> None:
    """Mark a cache entry as used just now. Never raises."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def _cached(tid: str, touch: bool = True):
    """The stored answer for a track, or None if there is not a usable one.

    A miss ages from when it was taken: six hours after a provider said no,
    asking again is worth the round trip. A hit ages from when it was last
    USED, not when it was fetched -- the file's mtime is bumped every time it
    is read back, so a song in rotation keeps its lyrics for as long as it
    stays in rotation, and only a month of not being played lets go.
    """
    path = _cache_path(tid)
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if rec.get("rev") != REVISION:
        return None
    at = float(rec.get("at") or 0)
    if not rec.get("doc"):
        return None if time.time() - at > MISS_TTL else rec
    try:
        used = max(at, path.stat().st_mtime)
    except OSError:
        used = at
    if time.time() - used > HIT_TTL:
        return None
    if touch:
        _touch(path)
        duet = _duet_path(tid)
        if duet.exists():
            _touch(duet)
    return rec


def sweep(force: bool = False) -> int:
    """Delete the entries nothing has asked for in a month. Returns how many.

    Nothing else removes a cached document: the size of this directory is a
    few kilobytes a song and the whole point of it is to still be there the
    next time the song comes round. What ages out is what stopped being
    listened to, plus the six-hour "nobody has this" notes, which are only
    worth keeping until it is worth asking again.

    Runs at most once a day -- the stamp file is the clock -- unless forced.
    """
    stamp = CACHE_DIR / ".swept"
    now = time.time()
    if not force:
        try:
            if now - stamp.stat().st_mtime < SWEEP_EVERY:
                return 0
        except OSError:
            pass
    if not CACHE_DIR.is_dir():
        return 0
    gone = 0
    for path in CACHE_DIR.glob("*.json"):
        if path.name.startswith("amll-index"):
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            at = float(rec.get("at") or 0)
            miss = "doc" in rec and not rec.get("doc")
            idle = now - max(at, path.stat().st_mtime)
            stale = (now - at > MISS_TTL) if miss else (idle > HIT_TTL)
        except Exception:
            stale = True
        if not stale:
            continue
        try:
            path.unlink()
            gone += 1
        except OSError:
            pass
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(int(now)), encoding="utf-8")
    except Exception:
        pass
    return gone


def stored(tid: str):
    """The document last stored for this track, asking nobody.

    Not the same question as fallback()'s: that one wants to know whether a
    stored answer settles the walk it is about to do, and refuses a record
    taken under a different set of providers. This one only wants something
    true to put on the screen while that walk happens, and last week's answer
    from a provider since switched off is still this song's words.
    """
    rec = _cached(tid)
    doc = (rec or {}).get("doc")
    if not isinstance(doc, dict):
        return None
    # Carry the name of whoever answered, so the line under the lyrics is
    # right from the first frame rather than guessing Spicy Lyrics and
    # correcting itself a moment later.
    return {**doc, "_source": str(rec.get("source") or "")} if rec.get("source") else doc


def forget(tid: str) -> None:
    """Drop everything cached about a track, so the next ask really asks.

    Both files go: the duet flags were derived from the document being thrown
    away, and keeping them would let a stale second-voice reading outlive the
    lyrics it was aligned against.
    """
    for path in (_cache_path(tid), _duet_path(tid)):
        try:
            path.unlink()
        except Exception:
            pass


def _store(tid: str, doc, source: str, names: list, bar: int) -> None:
    """Remember the answer, and what was asked to get it.

    `names` and `bar` are the question, and without them the answer cannot be
    reused safely: a walk that skipped half the providers because Spicy Lyrics
    already had word timing would otherwise be read back as "nobody has
    anything" by a later ask that really did want to know.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(tid).write_text(
            json.dumps({"rev": REVISION, "at": time.time(), "source": source,
                        "names": list(names), "bar": int(bar), "doc": doc}),
            encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def _parallel(jobs: dict, each=None) -> dict:
    """Run {key: thunk} at once, and hand back {key: result}.

    Everything here is a blocking socket read waiting on somebody else's
    server, so threads are exactly the right tool and the GIL never enters
    into it. A thunk that raises comes back as None: one provider being down
    is not a reason for the others to have been asked in vain.

    `each(key, value)` is called as each one lands, on whichever thread it
    landed on, so a caller can do something with the first answer instead of
    waiting for the last. It is never allowed to break the walk.
    """
    if not jobs:
        return {}

    def tell(k, v):
        if each is not None:
            try:
                each(k, v)
            except Exception:                            # noqa: BLE001
                pass
        return v

    if len(jobs) == 1:
        (k, fn), = jobs.items()
        try:
            return {k: tell(k, fn())}
        except Exception:
            return {k: tell(k, None)}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def guard(k, fn):
        try:
            return tell(k, fn())
        except Exception:
            return tell(k, None)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(guard, k, fn): k for k, fn in jobs.items()}
        out = {}
        for f in as_completed(futures):
            out[futures[f]] = f.result()
    return {k: out.get(k) for k in jobs}


def _gather(known: dict, names: list, tid: str, meta: dict, local=None,
            each=None) -> dict:
    """Every named provider asked at once, in two rounds where one has to be.

    The blends are the exception: they lay word timing under somebody else's
    lines, and "somebody else" should be able to be any source the user has
    ranked above them. So they go in a second round, and are handed what the
    first round came back with -- the documents they might build on have then
    already been fetched, by the providers those sources are, and the blend
    costs no request to reach them.

    Only the sources ABOVE a blend are offered to it. One ranked below is one
    the user has said they want less, and inheriting its lines through the
    back door is not what putting it there meant.
    """
    later = [n for n in names if getattr(known[n], "wants_above", False)]
    first = [n for n in names if n not in later]
    got = _parallel({n: (lambda fn=known[n]: fn(tid, meta, local=local))
                     for n in first}, each)
    if not later:
        return got
    jobs = {}
    for n in later:
        above = {k: got[k] for k in names[:names.index(n)] if got.get(k)}
        jobs[n] = (lambda fn=known[n], above=above:
                   fn(tid, meta, local=local, above=above))
    got.update(_parallel(jobs, each))
    return got



def fallback(tid: str, meta: dict, have: str, enabled=None, force: bool = False,
             order=None, ahead=(), local=None, report=None):
    """Best document the chain can offer, or None to keep what we already have.

    `have` is quality() of the Spicy Lyrics document. A provider is only
    accepted if it beats that, so a line-synced LRCLIB hit can rescue a song
    with no lyrics but can never demote a line-synced Spicy Lyrics one. The walk
    stops early on word timing, since nothing later in the chain could beat it.

    `order` overrides the order they are asked in. It matters because the walk
    stops at the first word-synced answer, so whoever comes first decides the
    result on every track where more than one of them has word timing.

    `ahead` names the providers the caller has ranked ABOVE Spicy Lyrics. They
    win a tie -- an equally good document from a source the user put first is
    the one they asked for -- and their being there is also why a word-synced
    `have` no longer ends the walk before it starts. Quality still outranks
    order in both directions: nothing here can replace word timing with line
    timing just by sitting higher up the list.
    """
    bar = RANK.get(have, 0)
    if bar >= RANK["syllable"] and not ahead:
        return None
    known = {n: fn for n, fn in PROVIDERS}
    walk = [n for n in (order or [n for n, _ in PROVIDERS]) if n in known]
    walk += [n for n, _ in PROVIDERS if n not in walk]
    names = [n for n in walk if enabled is None or n in enabled]
    if bar >= RANK["syllable"]:
        names = [n for n in names if n in ahead]
    if not names:
        return None

    def beats(rank: int, name: str) -> bool:
        """Whether this answer is worth having over what the caller holds."""
        return rank > 0 and (rank > bar or (rank == bar and name in ahead))

    if not force:
        rec = _cached(tid)
        if rec is not None:
            doc, was = rec.get("doc"), rec.get("source") or ""
            asked = list(rec.get("names") or [])
            fits = bar >= int(rec.get("bar") or 0)
            if doc and asked == names:
                if beats(RANK.get(quality(doc), 0), was):
                    return doc, was or "?"
                if fits:
                    # The best the same walk could find, and it does not beat
                    # what we already hold. Asking again cannot change that:
                    # anything it passed over was ranked no higher than a bar
                    # this one has already cleared. Without this the whole
                    # chain went back to the network on every play of a song
                    # whose lyrics were cached and simply not an improvement.
                    return None
            elif not doc and set(names) <= set(asked) and fits:
                return None

    said = threading.Lock()
    told = []

    def landed(name, doc):
        """The first answer worth having, handed over the moment it lands.

        The walk is ten providers wide and two rounds deep, and it used to
        hand back nothing at all until the slowest of them had finished --
        so a song nobody had cached sat under "Loading lyrics…" for as long
        as the worst server took, with a perfectly good document from the
        first one already in hand. Whoever comes back first and beats what
        the caller holds goes up now; the best of them still wins at the end
        and replaces it.
        """
        if report is None or not isinstance(doc, dict) or told:
            return
        if not beats(RANK.get(quality(doc), 0), name):
            return
        with said:
            if told:
                return
            told.append(name)
        try:
            report({**doc, "_source": name}, name)
        except Exception:                                # noqa: BLE001
            pass

    docs = _gather(known, names, tid, meta or {}, local,
                   landed if report is not None else None)

    best = None
    for name in names:
        doc = docs.get(name)
        if not doc:
            continue
        rank = RANK.get(quality(doc), 0)
        if not beats(rank, name):
            continue
        if best is None or rank > best[2]:
            best = (doc, name, rank)
    if best:
        best = (_credited(best[0], docs, names, ahead, local), best[1], best[2])
    _store(tid, best[0] if best else None, best[1] if best else "", names, bar)
    return (best[0], best[1]) if best else None


def _credited(doc: dict, docs: dict, names: list, ahead, local) -> dict:
    """The winning document, credited to whoever the top source says wrote it.

    Who wrote a song and who timed this copy of it are different questions with
    different best answers. Apple names the publishing writers -- legal names,
    every co-writer -- and a document that beat Apple on timing can easily
    carry one name or none: Kugou gives "Vivian Weeks" where Apple gives four
    people, and LRCLIB gives nobody at all. Taking the words from whoever timed
    them best and the credit from whoever is ranked highest is not a
    contradiction; they were never the same claim.

    Ranked highest means the user's own order, Spicy Lyrics in its place in it.
    """
    ranked = ([(n, docs.get(n)) for n in names if n in (ahead or ())]
              + [("spicy", local)]
              + [(n, docs.get(n)) for n in names if n not in (ahead or ())])
    wrote = []
    for _name, d in ranked:
        wrote = [str(w).strip() for w in (SL.payload(d or {}).get("SongWriters") or [])
                 if str(w).strip()]
        if wrote:
            break
    doc = _no_credit_head(doc, wrote)
    if wrote and wrote != [str(w).strip() for w in (doc.get("SongWriters") or [])]:
        doc = {**doc, "SongWriters": wrote}
    return doc


NAMES_APART = re.compile(r"\s*[/、，,&;·・]\s*|\s+feat\.?\s+|\s+x\s+", re.I)
UNSINGABLE = 25.0
PARTICLES = {"de", "van", "der", "den", "von", "la", "le", "du", "di", "da",
             "dos", "el", "bin", "al", "and", "of"}


def _names_shaped(text: str) -> bool:
    """Whether this reads as a list of people rather than a line of a song.

    Names are capitalised and lyrics are not, which is the whole test. Two
    words at least, so a one-word shout does not qualify, and the particles
    that live inside real names -- de, van, der -- are allowed to stay small.
    """
    words = [w for w in re.split(r"[^\w'’-]+", text or "") if w]
    if len(words) < 2:
        return False
    return all(w.lower() in PARTICLES or (w[:1].isupper() and not w.isupper())
               or w.isdigit() for w in words)


def _no_credit_head(doc: dict, wrote: list) -> dict:
    """Drop a leading line that is not a lyric but a credit.

    QQ Music opens a good many of its syncs with the songwriters' names as
    the first sung line -- "Noelle Stockwood/Juno Callender" on femtanyl's
    SICK OF IT, "Vivian Weeks" on STOMACH BOOK's -- with no label in front of
    them to say what they are, which is what makes them harder to find than
    Kugou's "Lyrics by：". Two things give them away and both are needed,
    because either alone would eventually throw away somebody's lyric:

      * the line says exactly what some source says the writers are, and
        nothing else. Whoever wrote the song is known here from every other
        provider that answered, which is what makes this cheap.
      * or it cannot be sung AND reads as a list of names: thirty-one
        characters in a fifth of a second is a marker, not a line. Speed alone
        is not enough -- "Ayy, woo" goes past at 44 characters a second and is
        a lyric -- so the words have to be capitalised like names too, which
        "Whatever you got for me is not enough" is not. Only where the
        syllables are really timed, since a line-level document's ends are
        this program's own guesses.
    """
    items = _items(SL.payload(doc))
    if len(items) < 2:
        return doc
    names = {_norm(w) for w in wrote if _norm(w)}
    cut = 0
    for it in items[:2]:
        text = (SL.line_text(it) or "").strip()
        if not text:
            break
        parts = [_norm(x) for x in NAMES_APART.split(text) if x.strip()]
        theirs = bool(names) and bool(parts) and all(p in names for p in parts)
        timed = bool(((it.get("Lead") or {}).get("Syllables")))
        s, e = SL.line_start(it), _line_end(it)
        fast = (timed and isinstance(s, (int, float)) and isinstance(e, (int, float))
                and e > s and len(text) / (e - s) > UNSINGABLE
                and _names_shaped(text))
        if not (theirs or fast):
            break
        cut += 1
    if not cut or cut >= len(items):
        return doc
    doc = dict(doc)
    doc["Lines" if "Lines" in doc else "Content"] = items[cut:]
    return doc


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
DUET_TTL = 30 * 86400


def _duet_path(tid: str) -> pathlib.Path:
    return _cache_path(tid).with_suffix(".duet.json")


def duet_flags(lines: list[dict], tid: str, meta: dict, enabled=None):
    """Recover the second-voice flag from amll-ttml-db.

    Spicy Lyrics carries OppositeAligned per line, but a good number of its
    entries are duets with the flag never set -- on the tracks this library
    shares with amll-ttml-db, six of twenty had no flags at all where amll had
    them. Nothing in the cached document can reveal that, since every line is
    just Type "Vocal"; the only way to know is to ask a source that kept the
    TTML agents.

    Deliberately only for lines that carry NO flags. Where Spicy Lyrics did
    mark a song up, amll often marks up considerably more of it -- a chorus
    agent read as a second singer -- and overwriting good data with that would
    trade one wrong answer for another. Returns a list of bools, or None.
    """
    if enabled is not None and "amll" not in enabled:
        return None
    if not lines or any(ln.get("opposite") for ln in lines):
        return None
    try:
        path = _duet_path(tid)
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("rev") == REVISION and (
                rec.get("flags") or time.time() - float(rec.get("at") or 0) < DUET_TTL):
            _touch(path)
            got = rec.get("flags")
            # Tied again on the way out: a file written before ad-libs were
            # held to their own line still has one on the wrong side of the
            # screen in it, and nothing else would ever correct it.
            return _tie_backing(lines, list(got)) if got else None
    except Exception:
        pass

    flags = None
    try:
        doc = from_amll(tid, meta or {})
        if doc:
            theirs = SL.timeline(doc)
            flags = _transfer(lines, theirs)
    except Exception:
        flags = None
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _duet_path(tid).write_text(
            json.dumps({"rev": REVISION, "at": time.time(), "flags": flags}),
            encoding="utf-8")
    except Exception:
        pass
    return flags


def _key(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


LIKE_LEN = 0.8


def _near_pairs(a: list[str], b: list[str], mate: dict, floor: float = 0.75) -> dict:
    """Line pairings the exact match missed, taken on similarity instead.

    Matching lines by their letters exactly leaves a hole wherever the donor's
    transcription differs by a character, and community transcriptions differ by
    a character constantly. On one 41-line song NetEase wrote "l opened" for "I
    opened" (a capital I typed as a lowercase L, three times), "stelking" for
    "stalking", "****ing" for the word Apple spells out, and dropped the I from
    "And I'm so high" -- six lines that are plainly the same line, left untimed
    because one glyph was wrong.

    Safe to be loose here because the exact matches have already pinned the song
    down: an unmatched line can only be paired inside the window its matched
    neighbours leave, so this is choosing between the two or three donor lines
    that could possibly be it, not searching the song. A line still finds no
    mate if nothing in that window resembles it.

    Length is checked before similarity, and it is the part that does the real
    work. A chorus gives you "Two faced, caught in the middle" and "Caught in
    the middle" as separate lines, and one contains the other, so they score 0.8
    similar while being different lines sung a bar apart -- pairing them put
    Linkin Park's chorus 1.4s out. A mistyped line is still the same length; a
    shorter line is a shorter line.
    """
    from difflib import SequenceMatcher

    taken = set(mate.values())
    anchors = sorted(mate)
    out: dict[int, int] = {}
    for i, key in enumerate(a):
        if i in mate or not key:
            continue
        lo = max((mate[k] for k in anchors if k < i), default=-1)
        hi = min((mate[k] for k in anchors if k > i), default=len(b))
        best, score = None, floor
        for j in range(lo + 1, hi):
            if j in taken or not b[j]:
                continue
            if min(len(key), len(b[j])) < LIKE_LEN * max(len(key), len(b[j])):
                continue
            r = SequenceMatcher(None, key, b[j], autojunk=False).ratio()
            if r > score:
                best, score = j, r
        if best is not None:
            out[i] = best
            taken.add(best)
    return out


REGROUP_LIKE = 0.88
REGROUP_SPAN = 4
REGROUP_SURE = 0.97
REGROUP_FAR = 2.5


def _regroup(a: list[str], b: list[str], bit: list, dit: list, mate: dict) -> dict:
    """Time the lines the two sides cut in different places.

    Everything up to here pairs one line with one line, so a line that the
    donor writes as two -- or two that it writes as one -- has no counterpart
    and gets no words, however plainly it is the same singing. That is not a
    rare shape: Koven's "Gold" is 24 lines against NetEase's 34, and after
    every other pass has run, EVERY line still missing from it is one Apple
    writes whole and NetEase breaks in two.

    Both directions are the same problem seen from either end, so both are
    handled here:

      one of ours, several of theirs -- their syllables are concatenated in
      order and re-cut onto our line, which is exactly what _relay already does
      for a line whose spelling differs;

      several of ours, one of theirs -- their syllables are shared out between
      our lines in proportion to how much of the text each carries, and each
      share is re-cut onto its own line.

    Returns {base index: (start, end, syllables)} for the lines it could place.
    Only donor lines nobody else is using, and only inside the window the
    matched lines either side leave -- the same discipline as _near_pairs, for
    the same reason.
    """
    from difflib import SequenceMatcher

    taken = set(mate.values())
    anchors = sorted(mate)
    clock = sorted(
        (s, d) for i, j in mate.items()
        for s in [SL.line_start(bit[i])] for d in [SL.line_start(dit[j])]
        if isinstance(s, (int, float)) and isinstance(d, (int, float)))
    out: dict[int, tuple] = {}
    spoken = set()

    def window(i):
        lo = max((mate[k] for k in anchors if k < i), default=-1) + 1
        hi = min((mate[k] for k in anchors if k > i), default=len(b))
        return lo, hi

    def timely(i, j):
        """Is donor line j where the matched lines say base line i should be?

        Compared against the interpolated clock rather than against zero, so a
        donor that genuinely drifts against ours is not punished for it.
        """
        if not clock:
            return True
        s, d = SL.line_start(bit[i]), SL.line_start(dit[j])
        if not (isinstance(s, (int, float)) and isinstance(d, (int, float))):
            return True
        return abs(d - _between(clock, s)) <= BLEND_JUMP

    def syllables(j):
        lead = dit[j].get("Lead")
        return list(lead.get("Syllables") or []) if isinstance(lead, dict) else []

    for i, key in enumerate(a):
        if i in mate or i in spoken or not key:
            continue
        lo, hi = window(i)

        # --- one of ours, a run of theirs ---------------------------------
        cands = []
        for j in range(lo, min(hi + 1, len(b))):
            if j in taken or not b[j]:
                continue
            acc = ""
            for k in range(j, min(j + REGROUP_SPAN, len(b))):
                if k in taken or not b[k]:
                    break
                acc += b[k]
                if len(acc) > len(key) * 1.4:
                    break
                if k == j:
                    continue
                r = SequenceMatcher(None, key, acc, autojunk=False).ratio()
                if r > REGROUP_LIKE:
                    cands.append((r, j, k))
        span = None
        cands.sort(key=lambda c: -c[0])
        agreed = [c for c in cands if timely(i, c[1])]
        if agreed:
            span = (agreed[0][1], agreed[0][2])
        elif cands:
            s = SL.line_start(bit[i])
            want = _between(clock, s) if clock and isinstance(s, (int, float)) else None
            close = []
            for r, j, k in cands:
                if r < REGROUP_SURE:
                    continue
                d = SL.line_start(dit[j])
                if want is None or not isinstance(d, (int, float)):
                    close.append((r, j, k))
                elif abs(d - want) <= REGROUP_FAR:
                    close.append((r, j, k))
            if len(close) == 1:
                span = (close[0][1], close[0][2])
        if span:
            j0, j1 = span
            syls = [s for j in range(j0, j1 + 1) for s in syllables(j)]
            cut = _relay(SL.line_text(bit[i]), syls) if syls else None
            if cut:
                start = SL.line_start(dit[j0])
                end = dit[j1].get("EndTime")
                out[i] = (start, end if isinstance(end, (int, float))
                          else cut[-1]["EndTime"], cut)
                taken.update(range(j0, j1 + 1))
                spoken.add(i)
                continue

        # --- a run of ours, one of theirs ---------------------------------
        for n in range(2, REGROUP_SPAN + 1):
            if i + n > len(a):
                break
            run = list(range(i, i + n))
            if any(x in mate or x in spoken or not a[x] for x in run):
                break
            joined = "".join(a[x] for x in run)
            pick = None
            for j in range(lo, min(hi + 1, len(b))):
                if j in taken or not b[j] or not timely(i, j):
                    continue
                if SequenceMatcher(None, joined, b[j],
                                   autojunk=False).ratio() >= REGROUP_LIKE:
                    pick = j
                    break
            if pick is None:
                continue
            syls = syllables(pick)
            if not syls:
                continue
            shares, at = [], 0
            for x in run:
                want = len(a[x]) / len(joined)
                take_n = max(1, round(want * len(syls)))
                shares.append(syls[at:at + take_n])
                at += take_n
            if at < len(syls):
                shares[-1].extend(syls[at:])
            cuts = [_relay(SL.line_text(bit[x]), s) if s else None
                    for x, s in zip(run, shares)]
            if any(c is None for c in cuts):
                continue
            for x, c in zip(run, cuts):
                out[x] = (c[0]["StartTime"], c[-1]["EndTime"], c)
                spoken.add(x)
            taken.add(pick)
            break
    return out


def _slide(node, by):
    """Every stamp in a group, moved by the same amount."""
    node = dict(node)
    for attr in ("StartTime", "EndTime"):
        if isinstance(node.get(attr), (int, float)):
            node[attr] = node[attr] + by
    if isinstance(node.get("Syllables"), list):
        node["Syllables"] = [_slide(y, by) for y in node["Syllables"]
                             if isinstance(y, dict)]
    return node


RELAY_LIKE = 0.75


def _recut(theirs: str, ours: str, bounds: list[int],
           breaks: set[int]) -> list[int] | None:
    """Cut positions in the donor's letters, moved onto ours.

    Both sides are the same line with the punctuation and casing taken out, so
    they are nearly the same string, and where they are exactly the same string
    the caller never gets here. What is left is a handful of letters one side
    spells differently -- which is a job for the same aligner that paired the
    lines in the first place, one level down.

    Letters only one side wrote have no position of their own, and a cut next
    to a run of them can honestly go anywhere in it. `breaks` -- the offsets in
    `ours` that fall between two words -- settles those, because the two live
    cases pull in opposite directions and nothing else tells them apart: a
    donor writing "nothin" for "nothing" leaves a "g" that has to stay with the
    word before it, and one writing "****ing" for a word spelled out leaves
    four letters that have to go with the syllable after. Both are one cut
    against one inserted run; the difference is only which side of it finishes
    a word of ours.
    """
    from difflib import SequenceMatcher

    sm = SequenceMatcher(None, theirs, ours, autojunk=False)
    if sm.ratio() < RELAY_LIKE:
        return None
    at = [0] * (len(theirs) + 1)
    lo, hi = list(at), list(at)
    loose = None
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                at[i1 + k] = lo[i1 + k] = hi[i1 + k] = j1 + k
            if loose:
                lo[i1] = loose
        elif i2 > i1:
            for k in range(i2 - i1):
                at[i1 + k] = j1 + round(k * (j2 - j1) / (i2 - i1))
                lo[i1 + k], hi[i1 + k] = j1, j2
        loose = None if tag == "equal" else j1
    at[-1] = lo[-1] = hi[-1] = len(ours)
    if loose is not None:
        lo[-1] = loose
    out = []
    for b in bounds:
        free = [p for p in range(lo[b], hi[b] + 1) if p in breaks]
        out.append(min(free, key=lambda p: (abs(p - at[b]), -p)) if free else at[b])
    return out


def _relay(text: str, syls: list[dict]) -> list[dict] | None:
    """Re-cut `text` along `syls`' boundaries, keeping our own characters.

    The two sides spell the same line but not identically -- one capitalises
    "Internet", the other does not; one writes an em dash with spaces around it.
    Since only the timing is being borrowed, the donor's syllables are used
    purely as cut points and every character that reaches the screen still comes
    from `text`.

    Nor do the two always spell it with the same letters, and demanding that
    they did cost far more than it saved. A donor line reading "nothin" for
    "nothing", or "****ing" for the word Apple writes out, is one letter or four
    from ours and unmistakably the same line -- _near_pairs exists precisely to
    keep those pairings -- and refusing to cut along it threw away every word
    timing the donor had for that line anyway. Where the base carries no word
    timings of its own to fall back on that is the difference between a line
    that fills and a line that just sits there: on the cached blends built over
    LRCLIB it left three lines in ten unfilled, scattered through songs that
    were otherwise filling word by word.

    So the letters are lined up when they do not match outright, and the cuts
    come across with them.
    """
    idx = [i for i, c in enumerate(text or "") if c.isalnum()]
    spans = [(s, _key(s.get("Text") or "")) for s in syls or []]
    spans = [(s, k) for s, k in spans if k]
    ours = _key(text)
    if not spans or not idx or len(ours) != len(idx):
        return None
    theirs, bounds, n = "", [], 0
    for _, k in spans:
        theirs, n = theirs + k, n + len(k)
        bounds.append(n)
    if theirs == ours:
        cuts = bounds
    else:
        breaks = {0, len(ours)} | {p for p in range(1, len(ours))
                                   if idx[p] - idx[p - 1] > 1}
        cuts = _recut(theirs, ours, bounds, breaks)
    if cuts is None:
        return None

    out, cut, held = [], 0, None
    for (s, _k), at in zip(spans, cuts):
        st, en = s.get("StartTime"), s.get("EndTime")
        if not isinstance(st, (int, float)) or not isinstance(en, (int, float)):
            return None
        stop = idx[at] if at < len(idx) else len(text)
        piece = text[cut:stop]
        if not _key(piece):
            if out:
                out[-1]["EndTime"] = max(out[-1]["EndTime"], float(en))
            else:
                held = float(st) if held is None else min(held, float(st))
            continue
        body = piece.rstrip()
        out.append({"Text": body,
                    "StartTime": float(st) if held is None else held,
                    "EndTime": float(en), "IsPartOfWord": piece == body})
        held, cut = None, stop
    if not out:
        return None
    if cut < len(text):
        out[-1]["Text"] += text[cut:].rstrip()
    out[-1]["IsPartOfWord"] = False
    return out


def graft_syllables(base, donor) -> dict | None:
    """Lend a word-timed document's timings to a line-timed one's own lines.

    Spicy Lyrics' lyrics are the ones actually chosen for display -- its
    wording, its line splits, its casing -- but where it only has line stamps it
    cannot say when inside a line each word lands. A word-timed source can,
    without having to supply the words as well.

    The whole result is put on the donor's clock, including the lines that did
    not match: a line still timed by the base would sit against a different
    reading of the song, and the seam is audible where they meet.
    """
    from difflib import SequenceMatcher

    bdoc, ddoc = SL.payload(base or {}), SL.payload(donor or {})
    if quality(bdoc) != "line" or quality(ddoc) != "syllable":
        return None
    bit, dit = _items(bdoc), _items(ddoc)
    if not bit or not dit:
        return None

    a = [_key(SL.line_text(i)) for i in bit]
    b = [_key(SL.line_text(i)) for i in dit]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    pairs = [(i + k, j + k)
             for i, j, n in sm.get_matching_blocks() for k in range(n) if a[i + k]]
    if not (_shared(a, b, dict(pairs), floor=0.6)
            or _coherent(dict(pairs), bit, dit)):
        return None

    mate = dict(pairs)
    mate.update(_near_pairs(a, b, mate))
    mate = _timely(mate, bit, dit)
    mate.update(_retime(a, b, bit, dit, mate))
    take = {}
    for i, it in enumerate(bit):
        d = dit[mate[i]] if i in mate else None
        lead = (d or {}).get("Lead") if isinstance((d or {}).get("Lead"), dict) else None
        syls = _relay(SL.line_text(it), (lead or {}).get("Syllables") or []) if lead else None
        if syls:
            start = d.get("StartTime")
            end = d.get("EndTime")
            take[i] = (start if isinstance(start, (int, float)) else syls[0]["StartTime"],
                       end if isinstance(end, (int, float)) else syls[-1]["EndTime"],
                       syls)
    for i, got in _regroup(a, b, bit, dit, mate).items():
        take.setdefault(i, got)
    if not take:
        return None

    anchors = sorted(
        (s, d) for i, (d, _e, _s) in take.items()
        for s in [SL.line_start(bit[i])]
        if isinstance(s, (int, float)) and isinstance(d, (int, float)))

    def _onto(t):
        return _between(anchors, t)

    out, grafted = [], 0
    for i, it in enumerate(bit):
        new = dict(it)
        if i in take:
            start, end, syls = take[i]
            by = None
            for attr, val in (("StartTime", start), ("EndTime", end)):
                if isinstance(val, (int, float)):
                    if by is None and isinstance(new.get(attr), (int, float)):
                        by = val - new[attr]
                    new[attr] = val
            new["Lead"] = {"Syllables": syls,
                           "StartTime": syls[0]["StartTime"],
                           "EndTime": syls[-1]["EndTime"]}
            grafted += 1
        else:
            here = SL.line_start(it)
            there = SL.line_start(dit[mate[i]]) if i in mate else None
            if isinstance(here, (int, float)) and isinstance(there, (int, float)):
                by = there - here
            else:
                by = (_onto(here) - here) if isinstance(here, (int, float)) else 0.0
            new.pop("Lead", None)
            new = _slide(new, by)
        if isinstance(new.get("Background"), list):
            new["Background"] = [_slide(g, by or 0.0) for g in new["Background"]
                                 if isinstance(g, dict)]
        out.append(new)
    if not grafted:
        return None

    doc = {k: v for k, v in bdoc.items() if k not in ("Type", "Content", "Lines")}
    doc["Type"] = "Syllable"
    doc["Content"] = out
    doc["_timing"] = "netease"
    return doc


def _lead_of(lines: list[dict], i: int) -> int:
    """The line an ad-lib belongs to, where the list does not say.

    Only for flags cached before lines carried a group, and for line lists
    somebody built by hand. Nearest by start time, which is what "written as
    part of that line" comes out as once the document is flattened.
    """
    here = lines[i].get("start")
    best, how = -1, None
    for j, ln in enumerate(lines):
        if ln.get("background"):
            continue
        d = abs((ln.get("start") or 0.0) - (here or 0.0))
        if how is None or d < how:
            best, how = j, d
    return best


def _tie_backing(lines: list[dict], flags: list[bool]) -> list[bool]:
    """Give every ad-lib the side the line it belongs to hangs off.

    An ad-lib is not a voice of its own: it is written inside a line and it is
    drawn against that line, indented from whichever edge the line hangs off.
    Letting it answer this question separately puts a backing vocal on the far
    side of the screen from the words it is backing, which is not a thing the
    layout is supposed to be able to do.
    """
    rows = list(enumerate(lines))[:len(flags)]
    side = {ln.get("group"): flags[i] for i, ln in rows
            if not ln.get("background") and ln.get("group") is not None}
    for i, ln in rows:
        if not ln.get("background"):
            continue
        if ln.get("group") in side:
            flags[i] = side[ln["group"]]
        else:
            j = _lead_of(lines, i)
            flags[i] = flags[j] if 0 <= j < len(flags) else False
    return flags


def _transfer(ours: list[dict], theirs: list[dict]):
    """Copy their per-line flag onto ours, matching the lines by text.

    Line counts never agree exactly -- the two sources split and merge
    differently -- so this aligns the two text sequences and only trusts the
    stretches that match outright.

    Ad-libs are kept out of the match on both sides and take their own line's
    answer afterwards. Their text is short, repeated, and identical wherever a
    chorus repeats -- "ooh", "yeah", the hook sung behind itself -- which is
    exactly the material a sequence match pairs with the wrong copy; and the
    side an ad-lib hangs off was never its own to have.
    """
    from difflib import SequenceMatcher

    if not theirs or not any(ln.get("opposite") for ln in theirs):
        return None
    mine = [i for i, ln in enumerate(ours) if not ln.get("background")]
    yours = [j for j, ln in enumerate(theirs) if not ln.get("background")]
    if not mine or not yours:
        return None
    a = [_key(ours[i].get("text", "")) for i in mine]
    b = [_key(theirs[j].get("text", "")) for j in yours]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    out = [False] * len(ours)
    matched = 0
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            out[mine[i + k]] = bool(theirs[yours[j + k]].get("opposite"))
            matched += 1
    if matched < 0.6 * len(mine) or not any(out):
        return None
    return _tie_backing(ours, out)
