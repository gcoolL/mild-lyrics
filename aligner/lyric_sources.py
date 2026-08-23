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
    YouLy+         the LyricsPlus backend, which scrapes Apple/Musixmatch/
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

# Bumped when the parsers change, so cached conversions from an older build are
# thrown away instead of quietly outliving the bug they were made with.
# 2: NetEase picks among duplicate releases rather than taking the search's
#    first answer, and Musixmatch word timings are read as line timings.
# 3: NetEase whitespace-only tokens no longer become empty syllables.
# 4: NetEase bracketed asides become real backing vocals.
# 5: Musixmatch really is demoted now -- the winner is spelled "Musixmatch" and
#    the test for it was case-sensitive, so every document cached under 2..4 was
#    stored with its word timings intact and has to be fetched again.
# 6: YouLy+ lines pull their first syllable back to the line's own start, the
#    blend provider joins the chain, and the cache records which providers were
#    walked -- an older record cannot say, so it cannot be trusted either.
# 7: NetEase no longer reaches past a good line-level match for a worse-matched
#    word-level one, lines pair on similarity rather than exact text, and the
#    blend takes its lines from the caller's own document when that is the
#    better copy. Every one of those changes what a stored document contains.
# 8: the blend's line ends are fixed twice over -- compared as durations from
#    the agreed start rather than as three raw clocks, and settled on the
#    soonest of them rather than the latest, since every source pads and taking
#    the latest just picked whichever had padded most. Together those took the
#    blend from holding a quarter of its lines open past the last word to
#    holding about as few as the document it is built from. Also: a donor's word
#    timings are now re-cut onto lines the two sides spell slightly differently,
#    which recovers the donor on a tenth of the lines it paired with. Stored
#    blends have the old ends and the old gaps.
# 9: whether two documents are the same song is decided against the shorter of
#    them rather than against the base, so a donor that writes fewer lines than
#    we do is no longer mistaken for a different recording. Documents stored
#    under 8 were built with donors this would have kept.
REVISION = 9

UA = "mild-lyrics/1.0 (+personal lyrics viewer)"
TIMEOUT = 8.0

AMLL_RAW = "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main"
YOULY_BASE = os.environ.get("LYRICSPLUS_BASE", "https://lyricsplus.prjktla.my.id")
LRCLIB_BASE = "https://lrclib.net"

def _cache_root() -> pathlib.Path:
    """The cache directory, per platform. Kept in step with lyrics_gui.app_dir,
    and spelled out here rather than imported so this module stays usable on its
    own -- it has no other reason to know the GUI exists."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or (
            pathlib.Path.home() / "AppData" / "Local")
        return _migrated(pathlib.Path(root))
    root = os.environ.get("XDG_CACHE_HOME") or (pathlib.Path.home() / ".cache")
    return _migrated(pathlib.Path(root))


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
# A miss is cached too, or every track change re-asks three servers that already
# said no. Short enough that a newly submitted song still shows up the same day.
MISS_TTL = 6 * 3600
# A hit does not last forever either. These are living databases -- a track that
# answered line-level a year ago may well have a word-level submission by now --
# and without this a document only ever refreshed when REVISION happened to move.
HIT_TTL = 30 * 86400

# How good a document is, so a fallback can only ever be an upgrade.
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
# quality
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
# http
# --------------------------------------------------------------------------
# How many requests may be in flight to one host at a time.
#
# Asking the providers together turned out to need this. LyricsPlus rate-limits
# by concurrency, not by rate: two requests at once are fine and the third comes
# back 429 -- and the blend alone asks it for two upstreams, so the moment the
# plain YouLy+ provider ran alongside it one of the three was refused. The
# result was worse than the serial version it replaced, because a refusal is not
# a slow answer, it is no answer.
#
# Capped per host rather than globally, so the providers still overlap each
# other -- which is where the speed came from. Only requests to the same server
# queue behind one another.
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
                # Still held off. The gate is kept across the wait on purpose:
                # the point is to stop crowding this host, not to back off and
                # immediately let a sibling take the slot.
                if e.code != 429 or attempt == 2:
                    return None
                time.sleep(0.7)
            except Exception:
                return None
    return None


def _qs(**kw) -> str:
    return urllib.parse.urlencode({k: v for k, v in kw.items() if v not in (None, "", 0)})


# --------------------------------------------------------------------------
# TTML -> Spicy Lyrics document
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
        # Stray punctuation between spans ("'", ",") belongs to the syllable it
        # follows -- left loose it would be dropped, and it is never sung alone.
        if tail.strip():
            text += tail.strip()
        nxt = "".join(spans[i + 1].itertext()) if i + 1 < len(spans) else ""
        if spaced:
            # trailing whitespace in the tail is the word boundary
            part = not (tail and tail != tail.strip())
        elif not (_latin(text) or _latin(nxt)):
            part = True                       # CJK run: no spaces are expected
        else:
            # keep an apostrophe with the word it splits: "Couldn" + "'" + "t"
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
    return _repair(out)


def _repair(syls: list[dict]) -> list[dict]:
    """Re-time syllables that go backwards.

    These are community submissions and some carry a syllable stamped
    00:00.000 in the middle of an otherwise fine line. Rendered as-is the fill
    jumps back to the start of the song and the whole line reads as sung, so
    any run that breaks the order gets interpolated across the gap its sane
    neighbours leave.
    """
    good = []
    hi = None
    for i, y in enumerate(syls):
        if hi is None or (y["StartTime"] >= hi and y["EndTime"] >= y["StartTime"]):
            good.append(i)
            hi = y["EndTime"]
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
        # share the hole evenly between however many broken syllables sit in it
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
        return syls                      # "()" on its own is not a lyric
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

    YouLy+ hands back plain, unsynced lyrics in the same timed shape as
    everything else, with every line stamped 00:00.000. Taken at face value
    that is a "synced" document where the whole song happens at once: the view
    lights every line at 0:00 and then never moves again, which is worse than
    honestly showing it as unsynced and letting it scroll. Treat a document
    whose stamps never advance as static, and say so.
    """
    starts = [i["StartTime"] for i in items if isinstance(i.get("StartTime"), (int, float))]
    if not starts:
        return items
    # Not "all zero": a file stamped entirely at 12.0 is equally not a sync.
    # One line legitimately starting at 0 is fine, so it takes every line
    # agreeing to condemn the document.
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
    <songwriters><songwriter>, and YouLy+ echoes it verbatim whichever upstream
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
            # the same name is sometimes listed by two <songwriters> blocks
            seen.add(text.lower())
            writers.append(text)
        elif tag == "curator" and text:
            maker = maker or text
        elif tag == "meta" and _attr(el, "key") in ("ttmlAuthorGithubLogin",
                                                    "ttmlAuthor"):
            maker = maker or (_attr(el, "value") or "").strip()
    return writers, maker


def parse_ttml(xml: str | bytes) -> dict | None:
    """Apple-style TTML -> the document shape timeline() reads."""
    try:
        root = ET.fromstring(xml)
    except Exception:
        return None

    paras = [el for el in root.iter() if _tag(el) == "p"]
    if not paras:
        return None

    # Two-voice songs alternate agents; the one that opens the song is the lead
    # side and the other gets mirrored to the right, which is what Apple does.
    agents = [_attr(p, "agent") for p in paras]
    primary = next((a for a in agents if a), None)

    # Decided for the whole file, not per line: a properly spaced document still
    # has lines whose words all happen to be one span, and judging those alone
    # would flip the rule mid-song.
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
            # line-level: no timed spans, just the words. Roles carry the
            # translation and romanisation, which are not part of the line.
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
        # No per-syllable TransliteratedText comes back from these sources -- the
        # x-roman role is one flat string per line, romanised per mora rather
        # than per sung syllable, so it cannot be hung on the timings. Flagging
        # the document instead lets the existing deriver produce a romanisation
        # that actually follows the voice.
        "HasTransliterations": cjk,
    }
    lang = _attr(root, "lang")
    if lang:
        doc["Language"] = lang
    writers, maker = _credits(root)
    if writers:
        # Same field Spicy Lyrics' own documents use, so the info panel reads
        # one key whatever answered.
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
        # A line whose <p> carried no begin/end kept its timing on the group
        # alone, so take it back before the group goes -- otherwise demoting the
        # word timings would strip the line of any timing at all.
        for a in ("StartTime", "EndTime"):
            if not isinstance(new.get(a), (int, float)) and lead \
                    and isinstance(lead.get(a), (int, float)):
                new[a] = lead[a]
        # Backing vocals are their own voice with their own line timing, so they
        # survive the demotion; only the syllables inside them go.
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
# LRC -> Spicy Lyrics document
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
    # Same trap as the TTML one: stamps that never advance are not a sync. Keep
    # the words -- they are still the lyrics -- and fall through to Static
    # below, using them if the record carried no plain text of its own.
    if len({t for t, _ in rows}) < 2:
        plain = plain or "\n".join(b for _, b in rows)
        rows = []
    if rows:
        items = []
        for i, (t, body) in enumerate(rows):
            if not body:
                continue                      # an empty stamp is an instrumental gap
            # LRC gives starts only; a line runs until the next one begins,
            # bounded so a long instrumental break does not leave one line lit.
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
# the providers
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
                # first submission wins; later ones are usually re-uploads
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
    # the credit line may hold several artists; any one of them matching is
    # enough, since the db files a song under each separately
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

    YouLy+'s blended answer takes its line stamps from one upstream and its
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


def from_youly(tid: str, meta: dict, source: str | None = None,
               local=None) -> dict | None:
    """LyricsPlus.

    platformId alone is not enough: the server treats it as a cache key and
    404s with an empty songInfo when it misses, so the title and artist go
    along every time and the id only disambiguates. The endpoint is documented
    as returning raw TTML but actually answers with {"ttml": "..."}, and errors
    come back as JSON too -- hence unwrapping either shape.

    `source` pins one upstream instead of letting the server pick a winner --
    "apple", "qq", "musixmatch", "deezer", "lyricsplus". Left off, the server
    runs its own race, which is what this provider wants; the blend below asks
    for one side at a time because it is doing the reconciling itself.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title or not artist:
        return None
    q = _qs(title=title, artist=artist, platformId=tid, album=meta.get("album"),
            duration=round(float(meta.get("length") or 0), 3), source=source)
    raw = _get(f"{YOULY_BASE}/v1/ttml/get?{q}", "application/xml, application/json")
    if not raw:
        return None
    head = raw.lstrip()[:1]
    won = ""
    if head == b"{":
        try:
            rec = json.loads(raw)
        except Exception:
            return None
        if not isinstance(rec, dict) or rec.get("error"):
            return None
        # It says which of its own upstreams actually answered -- "apple",
        # "musixmatch", "qq", "deezer", "lyricsplus" (its own user submissions).
        # Worth keeping: "YouLy+" alone says nothing about how good the data
        # is, whereas Apple means word-timed and Musixmatch usually does not.
        won = str((rec.get("processingTime") or {}).get("winnerSource") or "")
        raw = rec.get("ttml") or ""
        if not raw:
            return None
    elif head != b"<":
        return None
    doc = parse_ttml(raw)
    if doc is None:
        return None
    # Musixmatch is the one upstream here whose word timings are not measured.
    # Where it has them at all they are a line's duration cut up between its
    # words, so they drift against the voice while looking exactly as
    # authoritative as Apple's -- read them as the line sync they really are.
    # Covers "musixmatch-word" too, which is the same data under another name,
    # and any capitalisation of either: this is a label from someone else's API
    # and matching it exactly is a bet there is no reason to take.
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
        # /api/get insists on an exact duration match; search is fuzzy, so fall
        # back to it and pick the closest-length hit ourselves.
        q = _qs(track_name=title, artist_name=artist)
        blob = _get(f"{LRCLIB_BASE}/api/search?{q}", "application/json")
        try:
            hits = json.loads(blob) if blob else []
        except Exception:
            hits = []
        hits = [h for h in hits if isinstance(h, dict) and not h.get("instrumental")]
        if dur > 0:
            hits = [h for h in hits if abs(float(h.get("duration") or 0) - dur) <= 4.0]
        # a synced hit beats a longer unsynced one, then closest duration
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
# NetEase Cloud Music
# --------------------------------------------------------------------------
NE_BASE = "https://music.163.com"
NE_HEAD = {"User-Agent": "Mozilla/5.0", "Referer": NE_BASE}
# How many search hits to open looking for word-level timing. Every one costs a
# request, and past the first few the candidates are no longer the same song.
NE_TRIES = 3
# Beyond this much difference in length, two tracks sharing a title are two
# different songs rather than two pressings of one. Masters vary by a second or
# two; nothing legitimate varies by twenty.
NE_SPREAD = 20.0
# Credits are stamped like lyrics and would otherwise scroll past as verse one.
NE_CREDIT = re.compile(
    r"^\s*(作词|作曲|编曲|制作人|出品|监制|录音|混音|母带|吉他|贝斯|鼓|键盘|和声|"
    r"弦乐|人声|策划|统筹|发行|词|曲)\s*[:：]")
# The two of those that are songwriter credits rather than production ones:
# 作词/词 is the lyricist, 作曲/曲 the composer. Everyone else on that list
# played on the record or released it, which is not the same claim.
NE_WROTE = re.compile(r"^\s*(作词|作曲|词|曲)\s*[:：]\s*(.+)$")
# [start,dur](start,dur,0)word(start,dur,0)word...
NE_YRC_LINE = re.compile(r"^\[(\d+),(\d+)\]")
NE_YRC_TOK = re.compile(r"\((\d+),(\d+),\d+\)([^(]*)")


def _ne_get(url: str):
    req = urllib.request.Request(url, headers=NE_HEAD)
    with _gate(url):                  # same courtesy as everyone else's server
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
        # containment, not equality: NetEase files Japanese singles under both
        # scripts at once ("オトノケ - Otonoke"), which never equals either half
        theirs = _norm(s.get("name") or "")
        same = bool(key) and (theirs == key
                              or (len(key) >= 4 and key in theirs)
                              or (len(theirs) >= 4 and theirs in key))
        near = want > 0 and dur > 0 and abs(dur - want) <= 5.0
        if not (same or near):
            continue
        # Sharing a title is not being the same song. "BROKEN MIRROR" by BOOM
        # BOOM SATELLITES runs 380s against Architects' 190s, and -- being the
        # one release here with word timing -- it won outright and put a
        # Japanese rock song's lyrics on screen.
        #
        # Demoted rather than dropped. Dropping it needs the duration we were
        # handed to be right, and when it is not the veto falls on the correct
        # song instead: given a wrong length for "The Drug In Me Is Reimagined"
        # this threw away all four real matches and kept the one track on the
        # album that happened to be that long. Demotion costs nothing when the
        # duration is right -- the tier below never wins a word-timing contest --
        # and still leaves the right answer reachable when it is wrong.
        far = want > 0 and dur > 0 and abs(dur - want) > NE_SPREAD
        # Ranking only, never a veto: credited-artist strings disagree across
        # services often enough that requiring a match would cost real hits.
        # It earns its place by keeping covers -- which pass both guards above,
        # a faithful one being the same song at the same length -- below the
        # real thing now that the caller walks past the first candidate.
        mine = {_norm(a.get("name") or "") for a in (s.get("artists") or [])
                if isinstance(a, dict)}
        byline = bool(akey) and any(
            a and (a == akey or (len(akey) >= 3 and akey in a)
                   or (len(a) >= 3 and a in akey)) for a in mine)
        # a duration match is the stronger signal; prefer one that is both
        score = (0 if far else 1,
                 2 if (same and near) else 1 if near else 0,
                 1 if byline else 0,
                 -abs(dur - want) if want else 0)
        scored.append((score, s["id"]))
    scored.sort(key=lambda r: r[0], reverse=True)
    # Everything but the last component. Those are the categorical ones -- is it
    # plausibly this song at all, did the duration match, did the byline -- and
    # every pressing of one recording scores the same on all three, which is
    # exactly the group the caller may shop around inside for word timing. The
    # last is the raw duration delta, which differs by milliseconds between
    # pressings and would split that group for no reason.
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
                # Some releases spend a whole token on the space between two
                # words. It has nothing to draw, but it is still what marks the
                # token before it as ending a word -- carry that back before
                # dropping it, or the two words either side run together.
                # Left in, it renders as a timed syllable with no text: 15% of
                # the syllables in a bad case, each one a highlight step that
                # lands on nothing.
                if syls:
                    syls[-1]["IsPartOfWord"] = False
                continue
            s, dur = int(s) / 1000.0, int(dur) / 1000.0
            syls.append({"Text": text, "StartTime": s, "EndTime": s + dur,
                         # NetEase puts the space inside the token it follows
                         "IsPartOfWord": word == text})
        if not syls:
            continue
        lead, bg = _ne_bg(syls)
        # A line that is nothing but a bracketed aside ("（*Laughs*）") has no
        # lead left to sing against. Rather than emit a blank line with a
        # backing vocal hanging off it, keep it as the line it plainly is.
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


def _ne_bg(syls: list[dict]):
    """A NetEase line's syllables split into the lead and its backing vocals.

    NetEase writes backing vocals inline and in brackets -- "best （Hahahaha）",
    "（Why） Why was it easy" -- with the brackets timed as words of their own.
    The view draws a backing vocal as its own voice against the line, so they
    have to leave the lead and become groups in their own right. The brackets go
    with them: they are notation for an inline rendering, and _unwrap already
    strips the same thing off Apple's and amll's backing vocals.

    Note the brackets are fullwidth (U+FF08/U+FF09) in every NetEase line seen
    here, never ASCII, which is why this leans on PAIRS rather than "()".
    """
    lead, groups, cur, want = [], [], None, None
    for y in syls:
        text = y.get("Text") or ""
        if cur is None:
            close = PAIRS.get(text[:1])
            if not close:
                lead.append(y)
                continue
            cur, want, text = [], close, text[1:]
            if not text:
                continue
        if text.endswith(want):
            text = text[:-len(want)]
            if text:
                cur.append({**y, "Text": text})
            if cur:
                groups.append(cur)
            cur, want = None, None
            continue
        if text:
            cur.append({**y, "Text": text})
    if cur:
        # A bracket that never closes is not a backing vocal, just a stray mark
        lead.extend(cur)
    out = []
    for cur in groups:
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


# A line whose syllables all run for exactly the same length was never measured:
# nobody sings five words in five equal breaths. It is what a source hands back
# when it holds a line stamp and no word timing and divides one by the other.
# Rogue's "Let's Talk" opens with such a line -- two words, 7.37s each, against
# a real vocal of well under a second -- and on screen that is one word filling
# for seven seconds while the singer has long since moved on.
#
# Only stripped where the division actually shows. A short line split evenly is
# just as invented, but every word in it lands within a breath of where it
# belongs, and dropping the timing there would trade a harmless inaccuracy for
# a visibly untimed line.
FAKE_EVEN = 0.006          # how close to identical the durations have to be
FAKE_SHOW = 1.2            # seconds per syllable, past which the crawl is plain


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
    if not items:
        return None
    items = _unfake(_destamp(items))
    # romalrc is line-level and keyed to the same clock, so it can be matched by
    # start time -- no fuzzy alignment needed, unlike a Genius page.
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
        # false on purpose: where romalrc exists the lines already carry a real
        # romanisation, and where it does not, deriving one is the GUI's own
        # decision to make rather than something this source should assert
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
        # one credit line can list several people, and the two lines usually
        # name the same person twice over
        for name in re.split(r"\s*[/、,，&]\s*", m.group(2)):
            name = name.strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
    return out


def from_netease(tid: str, meta: dict, local=None) -> dict | None:
    """NetEase Cloud Music.

    Worth a slot of its own rather than leaving it to YouLy+: it is the only
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
    """
    ranked = _ne_rank(meta or {})[:NE_TRIES]
    if not ranked:
        return None
    # Only the candidates that are as plausible as the best one may be preferred
    # for their word timing. That walk exists because word timing belongs to a
    # pressing rather than to a song, so the copy worth having is not always the
    # search's favourite -- but it assumed every candidate WAS the song, and a
    # lower-scoring candidate is precisely the one that might not be. Reaching
    # past a good line-level match to a worse-matched word-level one is how a
    # different band's song ends up on screen.
    top = ranked[0][1]
    sids = [sid for sid, _ in ranked]
    # Opened all at once. Which release carries the word timing cannot be known
    # without looking, so this always ended up making two or three round trips
    # to the same server one after the other; made together they cost one.
    got = _parallel({sid: (lambda s=sid: _ne_get(
        f"{NE_BASE}/api/song/lyric?id={s}&lv=1&kv=1&tv=1&yv=1&rv=1")) for sid in sids})
    fallback = None
    for sid, score in ranked:         # still decided in rank order
        d = got.get(sid)
        if not d:
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
# the blend: QQ's word timings, Apple's (or LRCLIB's) lines, NetEase's opinion
# --------------------------------------------------------------------------
# Each of the three knows something the others do not. QQ Music times inside a
# line better than anyone here and writes the lyrics worse -- no punctuation, no
# casing, credits stamped as verse one. Apple has the wording, the line splits
# and the casing that should reach the screen, and line stamps that are usually
# right but sometimes sit early. NetEase is a third opinion on where a line
# begins, from a catalogue that is not derived from either of the others -- and
# the least trustworthy of the three, because the release it found may not be
# the recording being played.
#
# So: Apple says what the words are, QQ says when each of them lands, and the
# three clocks vote on where the line as a whole sits.
BLEND_NEAR = 0.35     # two clocks this close are reading the same performance
BLEND_FAR = 1.5       # this far from everyone else is a different reading
BLEND_SAME = 0.55     # matched lines below this share (of the shorter side) = not this song
BLEND_JUMP = 0.75     # a pair drifting this far from its neighbours is mis-paired


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


# A share of matched lines is not the only way to know two documents are about
# one recording, and on a donor that cuts its lines differently it is a poor
# one. What cannot happen by accident is agreement about the CLOCK: a dozen
# lines that match by text and also place themselves within half a second of one
# another are the same performance, whatever fraction of the document they are.
#
# Koven's "Gold" is the case. NetEase writes 34 lines where Apple writes 24, so
# only half of Apple's lines have a single exact counterpart and the share gate
# refused the whole donor -- while the twelve that did match agreed on one
# offset to within 0.18s across the entire song. _shared already knows about
# donors that split lines differently and defends by measuring against the
# shorter side, but that does nothing here, where the base IS the shorter side.
#
# Enough lines to be sure the agreement is not a coincidence...
COHERE_MIN = 8
# ...how close they have to sit to their own median to count as agreeing...
COHERE_TOL = 0.5
# ...and how many of them must. Not all: one line of a repeated hook matched to
# the wrong repeat is normal and _timely will deal with it later.
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
    # Decided on the exact matches alone: whether these two are the same song is
    # exactly the question the loose pass must not be allowed to answer, since
    # it would happily pair anything with anything inside a wide enough window.
    if not _shared(a, b, pairs):
        return None
    pairs.update(_near_pairs(a, b, pairs))
    return pairs


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
        return pairs              # nothing paired, or the donor was rejected whole
    delta = {}
    for i, j in pairs.items():
        s, d = SL.line_start(bit[i]), SL.line_start(dit[j])
        if isinstance(s, (int, float)) and isinstance(d, (int, float)):
            delta[i] = d - s
    keys = sorted(delta)
    if len(keys) < 4:
        return pairs                  # too few to have a trend to disagree with
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


def from_blend(tid: str, meta: dict, local=None) -> dict | None:
    """QQ Music's within-line timing under Apple Music's (or LRCLIB's) lines,
    with NetEase Cloud Music voting on where each line starts.

    Asked of the same three services the other providers use, but one upstream
    at a time and reconciled here rather than taking whichever answered first.
    Independent of their own on/off switches: this is a source in its own right,
    not a mode of the others.

    `local` is whatever the caller already holds -- in practice Spicy Lyrics'
    own document, which is usually Apple Music too and usually the better copy
    of it. Worth first refusal on the lines: LyricsPlus' Apple endpoint is a
    scrape and answers line-level for tracks Spicy Lyrics has word-level, so
    ignoring what was already on the machine meant blending against the weaker
    of two Apples -- and, when that scrape failed outright, falling all the way
    to LRCLIB while a perfectly good Apple sync sat unused.
    """
    # All three at once -- this provider is three lookups deep and serially it
    # was three times the wait of any other. LRCLIB stays out of the race: it
    # is only wanted when nothing better has lines, and asking it every time
    # would spend a request per track to save one on the few that need it.
    got = _parallel({
        "apple": lambda: from_youly(tid, meta, source="apple"),
        "qq": lambda: from_youly(tid, meta, source="qq"),
        "ne": lambda: from_netease(tid, meta),
    })
    local = SL.payload(local) if local else None
    # Best wording available, richest first. `local` wins ties: it is the copy
    # the app is already showing, so blending onto it keeps the line splits and
    # casing on screen the same before and after.
    picks = [(local, _words_from(local), "spicy"),
             (got["apple"], "Apple Music", "youly")]
    picks = [(d, w, o) for d, w, o in picks if d and quality(d) != "none"]
    # stable, so `local` keeps its place on a tie
    picks.sort(key=lambda p: RANK.get(quality(p[0]), 0), reverse=True)
    if not picks:
        lr = from_lrclib(tid, meta)
        picks = [(lr, "LRCLIB", "lrclib")] if lr else []
    if not picks:
        return None
    base, words, origin = picks[0]
    out = _blend(base, words, got["qq"], got["ne"], origin)

    # Never hand back less than what went in. With an unsynced base -- Spicy
    # Lyrics has words but no timing for the track -- and donors whose line
    # splits will not align to it, there is nothing to reconcile and the result
    # is the unsynced base back again. Meanwhile one of those donors was a
    # perfectly good line sync on its own. Turning the blend on must not be how
    # you lose the sync, so where the reconciliation ends up worse than a source
    # it was built from, that source is handed back instead.
    rank = lambda d: RANK.get(quality(d), 0) if d else 0        # noqa: E731
    spare = [(d, o, v) for d, o, v in ((got["ne"], "netease", None),
                                       (got["qq"], "youly", "qq")) if d]
    if spare:
        d, o, v = max(spare, key=lambda p: rank(p[0]))
        if rank(d) > rank(out):
            out = dict(SL.payload(d))
            out["_alone"] = o
            if v:
                out["_via"] = v
    return out


def _blend(base: dict, words: str, qq: dict | None, ne: dict | None,
           origin: str = "spicy") -> dict | None:
    """The three documents reconciled into one. Split out so it can be tested
    on fixed inputs rather than on whatever the servers feel like saying."""
    bit = _items(SL.payload(base))
    if not bit:
        return None
    qit = _items(SL.payload(qq)) if qq else []
    nit = _items(SL.payload(ne)) if ne else []
    qmap = _timely(_pair(bit, qit), bit, qit) if qit else None
    nmap = _timely(_pair(bit, nit), bit, nit) if nit else None
    # Whether this donor's line ends are measured or invented. A word-level
    # NetEase document ends a line where its last syllable ends; a line-level
    # one has no end at all, so _ne_doc fills one in from the next line's start
    # or, failing that, ten seconds. Those are placeholders, and letting them
    # into the vote had them win it: on a track where NetEase only had line
    # timing, 29 of 84 lines were stretched -- one by 8.1 seconds -- to a
    # boundary nobody had measured. The same fabrication is in parse_lrc, so
    # LRCLIB is read the same way.
    ne_ends = bool(ne) and quality(ne) == "syllable"

    used: set[str] = set()
    out, worded = [], 0
    for i, it in enumerate(bit):
        b_s, b_e = SL.line_start(it), _line_end(it)
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
            out.append(new)               # unsynced line, and nobody could time it
            continue
        start = _agree(starts)
        # Credit is for changing the answer, not for being asked. A donor whose
        # clock agrees with the base moves nothing, and naming it implies a
        # reconciliation that never took place -- so each is judged by whether
        # the line would have landed elsewhere without it.
        for who in ("qq", "ne"):
            if who not in starts:
                continue
            rest = {k: v for k, v in starts.items() if k != who}
            # No `rest` at all means this donor is the only reason the line has
            # a time -- the base is unsynced. That is the largest contribution
            # there is, and testing it by "would the answer change without it"
            # scored it as nothing, so a document NetEase had timed end to end
            # went out credited to Spicy Lyrics.
            if not rest or abs(_agree(rest) - start) > 1e-6:
                used.add(who)

        # QQ's syllables carry the shape of the line -- which word is held, which
        # is clipped -- and that shape is worth keeping even where its clock is
        # the one that lost the vote. So it is moved onto the agreed start rather
        # than thrown away: the line lands where the vote says, and inside it the
        # words fall where QQ heard them.
        qby = (start - q_s) if isinstance(q_s, (int, float)) else 0.0
        syls = _relay(new["Text"], ((q or {}).get("Lead") or {}).get("Syllables") or [])
        if syls:
            syls = [_slide(y, qby) for y in syls]
            used.add("qq")            # its word timings really are on screen
        else:
            # QQ has nothing to say about this line -- it does not carry the
            # track at all, or it words the line differently enough that the
            # syllables cannot be re-cut onto ours. Apple's own word timings
            # then stand: they are what this document would have had without
            # the blend, and dropping them to a single untimed blob would make
            # asking for the blend a downgrade on every track QQ has never
            # heard of.
            own = (it.get("Lead") or {}).get("Syllables") or []
            if own and isinstance(b_s, (int, float)):
                syls = [_slide(y, start - b_s) for y in own]
            elif isinstance(n_s, (int, float)):
                # Neither QQ nor the base can word this line, and NetEase can.
                # It is already paired and already voted on the start, so its
                # syllables move onto that start exactly as QQ's would.
                #
                # Without this the blend answered line-level for any track QQ
                # and Apple have never heard of, was outranked by NetEase alone
                # at the bottom of from_blend, and handed the whole document
                # back on NetEase's clock -- losing the very line starts it had
                # just reconciled. Rogue's "Let's Talk" opened 5.6s early that
                # way, against an LRCLIB start the blend had already agreed on.
                lent = _relay(new["Text"],
                              ((n or {}).get("Lead") or {}).get("Syllables") or [])
                if lent:
                    syls = [_slide(y, start - n_s) for y in lent]
                    used.add("ne")

        # NetEase gets a say in the end too, where it measured one at all.
        #
        # Each end arrives on its own source's clock, and the line has just been
        # moved off all of them onto the agreed start -- so each is carried over
        # by the same distance its own start sat from that agreement. What is
        # then compared is how long each source says the line lasts, which is
        # the only part of an end that survives being moved.
        #
        # Comparing them raw counted the same disagreement twice. A donor whose
        # release runs a second behind the base was handing over an end a second
        # too late as well as a start a second too late, and the start vote had
        # already dealt with the second one.
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
        # Never before the last word we are actually going to draw. The words
        # are measured; the line end is a display boundary, and a boundary that
        # falls inside its own syllables freezes the fill mid-word. This is also
        # what makes taking the soonest end safe: a sustain one source measured
        # and another clipped is in the syllables, and comes back here.
        if syls:
            end = max(end, syls[-1]["EndTime"]) if end is not None \
                else syls[-1]["EndTime"]
        if end is None or end <= start:
            end = (syls[-1]["EndTime"] if syls else start + 4.0)
        end = max(end, start + 0.05)      # a line of no duration never lights up

        new["StartTime"], new["EndTime"] = start, end
        if syls:
            # On the group, not just the item: timeline() reads a word-synced
            # line's end off its Lead and never looks at the item, so an end
            # left only up there is an end nothing downstream ever sees.
            new["Lead"] = {"StartTime": start, "EndTime": end, "Syllables": syls}
            worded += 1
        # Backing vocals came with the base's words on the base's clock, so they
        # move with the line rather than staying where the base left them.
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
    # LRCLIB names nobody and QQ rarely does, but NetEase stamps the writers
    # into the lyrics themselves -- so where the base came up empty, ask it.
    if not doc.get("SongWriters"):
        writers = (SL.payload(ne or {}).get("SongWriters")
                   or SL.payload(qq or {}).get("SongWriters"))
        if writers:
            doc["SongWriters"] = writers
    # Name only what actually got a say. A donor that failed to align was not
    # merely unhelpful, it was about a different recording, and saying it
    # contributed would misreport where these timings came from.
    parts = [n for n, key in (("QQ Music", "qq"), ("NetEase", "ne")) if key in used]
    if parts:
        doc["_via"] = " + ".join([words] + parts)
    else:
        # Neither donor had anything for this track, or nothing that matched it.
        # What comes out is then one source's document with its own timings
        # untouched -- so it should say so, and be called what that source is
        # called anywhere else. "Blend · Apple Music" for a document nothing was
        # blended into claims work that did not happen, and hides which source
        # the lyrics on screen actually are.
        doc["_alone"] = origin
        if origin == "youly":
            doc["_via"] = "apple"     # what from_youly would have reported
        else:
            doc.pop("_via", None)
    return doc


# --------------------------------------------------------------------------
# alignments made on this machine
#
# Kept in their own directory, apart from the lookup cache further down, and
# the difference is not filing. Everything in CACHE_DIR is an answer somebody
# else's server gave and can be asked for again, so it carries a TTL and
# forget() throws it away. An alignment is minutes of this machine's own GPU
# spent on a copy of the audio that has since been deleted: losing it is not a
# re-fetch, it is doing the work again. So it has no TTL, and forget() -- which
# exists to make the next ask really ask -- does not touch it.
# --------------------------------------------------------------------------
ALIGN_DIR = _cache_root() / "aligned"
# Which copy of a track was aligned against, kept so the next run uses the same
# one.
#
# Two uploads of one song can share a length to the tenth of a second and be
# different recordings -- a live take runs the same three minutes as the studio
# cut and starts singing nine seconds later. The search does not return the same
# candidates twice running, so a song could be aligned against the album on
# Monday and a live performance on Tuesday, and the second alignment would be
# nine seconds out with nothing in this program having changed. Remembering the
# choice is what makes an alignment reproducible at all.
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
# Bumped when the aligner changes enough that its old answers are worth
# re-measuring rather than trusting. Same bargain as the Genius revision: these
# are derived, so a track measured once by an older version would otherwise
# keep that version's mistakes forever.
# 2: the words now come from Genius rather than from whichever source happened
# to be best-timed, and every word in a line is given a timing and run on to
# meet the next one. Both change the answer enough that older alignments are
# worth re-measuring rather than keeping.
# 3: two changes, and the second is the reason for the bump. English words are
# divided into syllables by their pronunciation, which an old alignment simply
# does not carry. And the song is no longer walked in one pass where a
# line-synced copy of the same recording exists to anchor between -- which is
# what stops a line being stretched across an instrumental break, and is the
# difference between a line held for twenty-four seconds and one held for two.
# Alignments made before this kept whichever the single pass happened to give.
# 4: the anchoring in 3 had stopped working and nobody could tell. A log line
# referred to two names that a refactor had removed, so every call raised, the
# caller caught it and quietly fell back to the single pass -- for months of
# alignments that say "rev 3" and were made without any of it. Ninety-six of
# them were sitting in the cache, being served in preference to re-measuring.
#
# What else changed with it, any one of which would have earned a bump:
# English words are read by wav2vec2 rather than MMS_FA; a line no longer
# loses its words when the line above it overruns; ad-libs are timed as their
# own voice instead of taking the lead's time, and no longer held for four
# seconds by an envelope that cannot hear which voice it is listening to;
# syllables are divided by dictionary rather than by rules; a line the walk
# could not place falls back to where the speech model heard it, and failing
# that to a share of the gap, so a song no longer has dark lines in it.
ALIGN_REV = 4


def _align_path(tid: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tid or "unknown")[:64]
    return ALIGN_DIR / f"{safe}.json"


def save_aligned(tid: str, doc: dict) -> bool:
    """Keep an alignment for this track. True if it went down."""
    if not tid or not isinstance(doc, dict):
        return False
    try:
        ALIGN_DIR.mkdir(parents=True, exist_ok=True)
        _align_path(tid).write_text(
            json.dumps({"rev": ALIGN_REV, "at": time.time(), "doc": doc}),
            encoding="utf-8")
        return True
    except Exception:
        return False


def aligned(tid: str) -> dict | None:
    """The alignment held for this track, if there is one from this revision."""
    try:
        rec = json.loads(_align_path(tid).read_text(encoding="utf-8"))
    except Exception:
        return None
    if int(rec.get("rev") or 0) != ALIGN_REV:
        return None
    doc = rec.get("doc")
    return doc if isinstance(doc, dict) else None


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
    return aligned(tid)


PROVIDERS = [("amll", from_amll), ("blend", from_blend), ("youly", from_youly),
             ("netease", from_netease), ("lrclib", from_lrclib),
             ("local", from_local)]


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
    # where each word ends, counted in the despaced string
    stops, at = set(), 0
    for w in worded.split():
        at += len(w)
        stops.add(at)
    sm = SequenceMatcher(None, flat.lower(), worded.replace(" ", "").lower(),
                         autojunk=False)
    if sm.ratio() < 0.82:
        return mora
    # flat index -> worded index, for the stretches that matched exactly
    same = {}
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            same[i + k] = j + k
    out, cut = [], 0
    for i in range(len(flat)):
        j = same.get(i)
        if j is None or (j + 1) not in stops:
            continue
        # Never break onto or away from punctuation: the segmenter counts "K.O."
        # as three tokens and splitting there spells it "K . O .", which is
        # worse than the per-mora line this is meant to improve on.
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
        # Genius opens a line with a capital and these two get read together --
        # a Genius line, then a NetEase line filling a gap in it, then Genius
        # again. Left lowercase the borrowed ones announce themselves as coming
        # from somewhere else, which is not information anybody wanted.
        for i, c in enumerate(roman):
            if c.isalpha():
                roman = roman[:i] + c.upper() + roman[i + 1:]
                break
        out[text] = roman
    return out


# --------------------------------------------------------------------------
# disk cache
# --------------------------------------------------------------------------
def _cache_path(tid: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tid or "unknown")[:64]
    return CACHE_DIR / f"{safe}.json"


def _cached(tid: str):
    try:
        rec = json.loads(_cache_path(tid).read_text(encoding="utf-8"))
    except Exception:
        return None
    if rec.get("rev") != REVISION:
        return None
    age = time.time() - float(rec.get("at") or 0)
    if age > (MISS_TTL if not rec.get("doc") else HIT_TTL):
        return None    # a stale "nothing here", or a hit old enough to re-ask
    return rec


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
# the chain
# --------------------------------------------------------------------------
def _parallel(jobs: dict) -> dict:
    """Run {key: thunk} at once, and hand back {key: result}.

    Everything here is a blocking socket read waiting on somebody else's
    server, so threads are exactly the right tool and the GIL never enters
    into it. A thunk that raises comes back as None: one provider being down
    is not a reason for the others to have been asked in vain.
    """
    if not jobs:
        return {}
    if len(jobs) == 1:
        (k, fn), = jobs.items()
        try:
            return {k: fn()}
        except Exception:
            return {k: None}

    from concurrent.futures import ThreadPoolExecutor

    def guard(fn):
        try:
            return fn()
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(guard, fn) for k, fn in jobs.items()}
        return {k: f.result() for k, f in futures.items()}


def _gather(known: dict, names: list, tid: str, meta: dict, local=None) -> dict:
    """Every named provider asked at once."""
    return _parallel({n: (lambda fn=known[n]: fn(tid, meta, local=local))
                      for n in names})



def fallback(tid: str, meta: dict, have: str, enabled=None, force: bool = False,
             order=None, ahead=(), local=None):
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
        # Only the ones ranked above Spicy Lyrics are still in the running, and
        # asking the rest would be three network requests spent on answers that
        # cannot be accepted.
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
            # A hit is only reusable if it came out of this same running order:
            # move a provider up the list and the old winner may no longer be
            # the one that would win now, which is the whole point of the move.
            if doc and list(rec.get("names") or []) == names:
                if beats(RANK.get(quality(doc), 0), was):
                    return doc, was or "?"
            # A miss carries over to any ask that is no harder than the one that
            # produced it -- fewer providers, or a higher bar to clear.
            elif not doc and set(names) <= set(rec.get("names") or []) \
                    and bar >= int(rec.get("bar") or 0):
                return None

    # Asked all at once rather than one after another. Serially this was the
    # slowest thing the app did: four providers that each take a second or two
    # and are each allowed eight, so a track none of them had could sit there
    # for half a minute with nothing on screen. They do not depend on each
    # other, so the walk costs what the slowest one costs.
    #
    # The cost is that the short-circuit is gone -- every enabled provider is
    # now asked even when the first would have settled it. That is a handful of
    # requests once per track per month, against a wait the user actually sits
    # through.
    docs = _gather(known, names, tid, meta or {}, local)

    best = None
    for name in names:                # priority order, so ties keep the earlier
        doc = docs.get(name)
        if not doc:
            continue
        rank = RANK.get(quality(doc), 0)
        if not beats(rank, name):
            continue
        if best is None or rank > best[2]:
            best = (doc, name, rank)
    _store(tid, best[0] if best else None, best[1] if best else "", names, bar)
    return (best[0], best[1]) if best else None


# --------------------------------------------------------------------------
# duet flags
# --------------------------------------------------------------------------
# A duet miss is remembered far longer than a lyrics miss: this asks about
# tracks that already HAVE good lyrics, so it would otherwise fire on most of
# the library at every track change, forever.
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
        rec = json.loads(_duet_path(tid).read_text(encoding="utf-8"))
        if rec.get("rev") == REVISION and (
                rec.get("flags") or time.time() - float(rec.get("at") or 0) < DUET_TTL):
            return rec.get("flags") or None
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


# How near in length two lines must be before their similarity is even worth
# scoring. A typo keeps a line's length; a line that is a fragment of another
# does not, and containment is what scores misleadingly high.
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


# How alike a run of lines and the single line facing it have to read before
# they are treated as the same words cut in two places. Looser than a
# line-for-line pair is allowed to be, because the run has already had to agree
# about its own length, which is the check that does the real work in
# _near_pairs -- and the window it may look in is bounded by matched lines
# either side, so this is choosing between a couple of candidates rather than
# searching a song.
REGROUP_LIKE = 0.88
# The most lines one side may spend saying what the other says in one. Past
# this it is not a split, it is two different readings of the section.
REGROUP_SPAN = 4
# Word for word, allowing for the odd letter. A run this close to ours, with
# nothing else in the window anywhere near as close, is not a guess about WHICH
# line it is -- so the only thing left for the clock to say is where that line
# falls, and it is entitled to disagree with its neighbours about that.
REGROUP_SURE = 0.97
# How far such a run may still sit from where the clock expects it. Wide enough
# for a transcription that stamps the pickup rather than the downbeat -- one
# line on "Gold" is written a second and a half early and is plainly the right
# line -- and far short of the distance to the next repeat of a chorus, which
# is what the ordinary tolerance is there to refuse.
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
    # The same clock the rest of the graft is read against. A window bounded by
    # matched lines is not on its own enough to place a run: where the matches
    # are sparse that window is wide, and a line the song repeats will happily
    # find its own words several seconds from where it is being sung. On one
    # track here four lines were placed 5.4s early that way, all by the same
    # amount, which is a repeat matched to the wrong repeat and nothing else.
    clock = sorted(
        (s, d) for i, j in mate.items()
        for s in [SL.line_start(bit[i])] for d in [SL.line_start(dit[j])]
        if isinstance(s, (int, float)) and isinstance(d, (int, float)))
    out: dict[int, tuple] = {}
    spoken = set()                    # base lines this pass has already placed

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
                    continue          # a run is two or more
                r = SequenceMatcher(None, key, acc, autojunk=False).ratio()
                if r > REGROUP_LIKE:
                    cands.append((r, j, k))
        # Prefer a run that agrees with the clock. Failing that, a run that is
        # word for word ours and the only one of its kind left in the window is
        # still the right line -- there is no other repeat for it to be -- so it
        # is allowed to disagree about the timing, within reason.
        span = None
        cands.sort(key=lambda c: -c[0])
        agreed = [c for c in cands if timely(i, c[1])]
        if agreed:
            span = (agreed[0][1], agreed[0][2])
        elif cands:
            # Nothing sits where the clock expects. A run that is word for word
            # ours can still be right -- the donor may stamp the pickup rather
            # than the downbeat -- but only while there is no question WHICH run
            # it is. So take the near-exact ones close enough to be candidates
            # at all, and act only if that leaves exactly one. A second repeat
            # of a chorus is bars away, not inside this bound, so it does not
            # make its neighbour ambiguous; another reading of the same moment
            # would, and should.
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
            # share them out by how much of the joined text each line carries
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


# How alike two spellings of one line must be before the donor's syllable
# boundaries are trusted as cut points for ours. The line pairing has already
# decided these are the same line; this is the narrower question of whether the
# two write it closely enough to cut along, so it matches _near_pairs' floor.
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
    # at[i] is where donor letter i lands in ours; lo[i]..hi[i] the range that
    # placing it is really free to choose from, which is empty where the two
    # sides spell the letter the same and the aligner matched it outright.
    at = [0] * (len(theirs) + 1)
    lo, hi = list(at), list(at)
    loose = None                          # the run before here, if it was one
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                at[i1 + k] = lo[i1 + k] = hi[i1 + k] = j1 + k
            if loose:
                lo[i1] = loose             # the run before could go either way
        elif i2 > i1:
            # A run the two sides spell differently has no letter-for-letter
            # answer, so it is divided in proportion. Crude, and near enough:
            # these runs are a word or two long, and a cut inside one only
            # decides which of two neighbouring words a letter fills with.
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
        # nearest word boundary it is allowed to reach, the later one on a tie
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
    # Punctuation-only syllables ("!", ",") carry no letters to line up on.
    # Dropping them costs a highlight step on something nobody sings, and the
    # mark itself still arrives as part of the slice around it.
    spans = [(s, _key(s.get("Text") or "")) for s in syls or []]
    spans = [(s, k) for s, k in spans if k]
    ours = _key(text)
    # Lowercasing changed the letter count -- a Turkish dotted I, a final sigma.
    # The cuts are counted in letters, so there is nothing to count them off.
    if not spans or not idx or len(ours) != len(idx):
        return None
    theirs, bounds, n = "", [], 0
    for _, k in spans:
        theirs, n = theirs + k, n + len(k)
        bounds.append(n)
    if theirs == ours:
        cuts = bounds
    else:
        # Where our own words end: a gap in the line between two letters is
        # the space, hyphen or comma between them.
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
        # up to the next syllable's first letter, so the punctuation and spacing
        # between two words stay attached to the word they follow
        stop = idx[at] if at < len(idx) else len(text)
        piece = text[cut:stop]
        if not _key(piece):
            # The donor sings a word our line does not carry. Nothing of ours
            # can be drawn for it and a syllable with no text fills as a blank
            # step, so its time goes to the syllable beside it -- the one whose
            # letters those moments were spent on as far as this line is
            # concerned -- and `cut` stays put, leaving whatever punctuation it
            # did claim for the slice that follows.
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
        # A tail the last syllable never claimed -- a "?" the donor did not
        # write -- belongs to the last word on screen rather than to nowhere.
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
    # Same reasoning as _transfer: a weak alignment means these are not the same
    # rendition, and timings hung on the wrong lines are worse than none. Held
    # to a higher share than the blend is, because this moves the whole document
    # onto the donor's clock rather than reconciling line by line -- but against
    # the shorter side for the same reason _shared explains, or a donor that
    # simply writes fewer lines than we do never gets to lend anything.
    # Either kind of evidence will do: most of the shorter document matching, or
    # fewer matches that agree about the clock. Both are still decided on the
    # exact matches alone, which is the point _pair makes -- the loose pass must
    # not get to answer whether these two are the same recording.
    if not (_shared(a, b, dict(pairs), floor=0.6)
            or _coherent(dict(pairs), bit, dit)):
        return None

    # Which lines can actually take the donor's syllables, decided before any
    # timing is moved -- the ones that can are the anchors the rest hang off.
    mate = dict(pairs)
    mate.update(_near_pairs(a, b, mate))
    # Same trap as the blend's: a repeated chorus line matches its own text
    # wherever it lands, so a pair that disagrees with its neighbours about the
    # clock is matched to the wrong repeat and must not lend its timings.
    mate = _timely(mate, bit, dit)
    # ...and give the lines it just rejected somewhere right to go. Without
    # this a mis-anchored repeat costs its own line AND everything after the
    # last surviving anchor, which is how a song ends up word-timed for its
    # first half and interpolated for its second.
    mate.update(_retime(a, b, bit, dit, mate))
    # (start, end, syllables) per line, whatever shape it came from -- one
    # donor line, a run of them, or a share of one. Normalised here so the
    # rewrite below does not care which.
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
    # Last of all, the lines the two sides cut in different places -- they need
    # every 1:1 pairing already settled, because those are the walls of the
    # window they are allowed to look in.
    for i, got in _regroup(a, b, bit, dit, mate).items():
        take.setdefault(i, got)
    if not take:
        return None

    # The two clocks do not differ by a constant. Where the documents disagree
    # about how the song is cut into lines the gap drifts -- one pairing here
    # ran from +0.6s to +9.8s across a single track -- so an unmatched line is
    # placed by the matched lines either side of it rather than by an average
    # that is wrong at both ends.
    # Every line that got words is an anchor, including the regrouped ones --
    # they know where they landed as exactly as any 1:1 pair does, and past the
    # last of them there is nothing left to interpolate from.
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
                # Found, but its words could not be re-cut onto ours: the two
                # sides do not spell the line with the same letters, which is
                # what a censored "****ing" against the word written out comes
                # to. The words inside it are lost either way, but where the
                # line falls is known exactly -- so use that rather than
                # interpolating a position we were told.
                by = there - here
            else:
                by = (_onto(here) - here) if isinstance(here, (int, float)) else 0.0
            new.pop("Lead", None)
            new = _slide(new, by)
        # Backing vocals came with the base's words, so they keep the base's
        # timing -- but the line around them has just moved to the donor's
        # clock, and a backing vocal left behind sings against the wrong line.
        if isinstance(new.get("Background"), list):
            new["Background"] = [_slide(g, by or 0.0) for g in new["Background"]
                                 if isinstance(g, dict)]
        out.append(new)
    if not grafted:
        return None

    doc = {k: v for k, v in bdoc.items() if k not in ("Type", "Content", "Lines")}
    doc["Type"] = "Syllable"
    doc["Content"] = out
    # Provenance splits in two here, and the text is the half a reader would
    # mean by "where are these lyrics from".
    doc["_timing"] = "netease"
    return doc


def _transfer(ours: list[dict], theirs: list[dict]):
    """Copy their per-line flag onto ours, matching the lines by text.

    Line counts never agree exactly -- the two sources split and merge
    differently -- so this aligns the two text sequences and only trusts the
    stretches that match outright.
    """
    from difflib import SequenceMatcher

    if not theirs or not any(ln.get("opposite") for ln in theirs):
        return None
    a = [_key(ln.get("text", "")) for ln in ours]
    b = [_key(ln.get("text", "")) for ln in theirs]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    out = [False] * len(ours)
    matched = 0
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            out[i + k] = bool(theirs[j + k].get("opposite"))
            matched += 1
    # A weak alignment means the two are not really the same rendition of the
    # song, and guessing which side a line belongs to is worse than not saying.
    if matched < 0.6 * len(ours) or not any(out):
        return None
    return out
