"""Every lyric provider: Spicy Lyrics, and the ten for when it has nothing good.

Spicy Lyrics (Community / Apple Music) is the source the app was built around,
and its data is what every other feature (romanisation, furigana, Genius
alignment) is tuned against, so it leads the running order by default. But a
fair slice of any library comes back line-synced, unsynced, or missing
entirely, and for those there is often better data elsewhere. This module goes
and gets all of it.

Spicy Lyrics is asked FIRST AND ALONE, and what it answers is what the rest
have to beat -- see from_spicy and _walk's lead. That is not a courtesy to the
source it leads with, it is what a track id is worth: Spicy Lyrics is the one
provider here that can be asked about a song by its Spotify id rather than by
title, artist and length, so it costs one request and cannot come back with
the wrong song. It word-syncs most tracks, and on those the other ten are
never asked at all.

The chain, in default order:

    amll-ttml-db   word-by-word TTML, community-submitted, indexed by Spotify
                   id among others. Same data model as Apple Music, so it drops
                   straight in.
    the blends     somebody else's within-line timing under Apple Music's
                   lines. Two lookups rather than one, or three where a second
                   donor is kept for the lines the first cannot place, so they
                   are off unless asked for -- and they stand themselves down
                   without spending anything where a source ranked in front of
                   their donors already answered word-timed.
    NetEase        word-level `yrc` where it has it, and -- uniquely here -- a
                   human-written romanisation on the same clock as the lyrics.
    Kugou          word-timed KRC, and the Chinese catalogue the English
                   sources here are worst at.
    QQ Music       word-timed QRC from QQ itself, its lines as well as its
                   timings. Worth having beside the blends because it writes
                   ad-libs Apple has not written at all.
    LRCLIB         huge, open, no key needed -- but line-level LRC only, so
                   it only ever wins a song nobody word-timed.
    Musixmatch     its own app endpoint, which is the difference between a
                   word-timed document and a line-timed one; see _musixmatch.
                   Below LRCLIB, which costs it nothing where it is word-timed
                   -- quality outranks order -- and settles the songs where
                   both of them came back as lines; see SOURCES.

NetEase and Kugou lead QQ Music because that ranking is also what picks the
blend, and the ones built on NetEase measure better; see SOURCES.

The order is the caller's to set, Spicy Lyrics included; see fallback(). What
the order cannot do is trade quality away -- a source ranked first still only
wins against an equal or worse document, never by replacing word timing with
line timing. The one other thing that overrules it is a document that is
missing a whole section of the song, which no ranking asked for; see
_fullest. Being longer than everybody else is not that, and reading it that
way is how Musixmatch used to win from the bottom of the list.

A source that could not be reached is not a source that had nothing, and the
difference is the user's: fallback() hands back what went wrong, so the
window can say which catalogue the order asked for and did not get.

Everything is converted to the shape spicy_lyrics.timeline() already eats, so
nothing downstream needs to know where a song came from.

The answers are kept on disk, two ways and for two questions. A record under
`sources` is what a WALK decided, read back only by a walk asking the same
question of the same providers; a record under `spicy` is one catalogue's
answer about one track, and is also the only list of songs this program can
offer, since that API answers about a track and does not enumerate. Both age
by the same rule and sweep() clears both.
"""

from __future__ import annotations

import bisect
import functools
import json
import os
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import offload
import spicy_lyrics as SL

# What a stored answer was written by. It rides on every record under
# `sources` and a walk will not read one back that does not match, so bumping
# it is how a change to the document shape or to the chain throws the old
# answers away rather than drawing them.
#
# Counted from one again at 1.0.0. It had reached seventeen, which measured
# nothing but how many times the shape changed before there was a version to
# say it in -- and it costs one re-walk per song, spread over listening, which
# is what every one of those seventeen cost.
REVISION = 1

UA = "mild-lyrics/1.0 (+personal lyrics viewer)"
TIMEOUT = 8.0

AMLL_RAW = "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main"
LRCLIB_BASE = "https://lrclib.net"

def cache_root() -> pathlib.Path:
    """The cache directory, per platform. Kept in step with lyrics_gui.app_dir,
    and spelled out here rather than imported so this module stays usable on its
    own -- it has no other reason to know the GUI exists."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or (
            pathlib.Path.home() / "AppData" / "Local")
        return _migrated(pathlib.Path(root))
    root = os.environ.get("XDG_CACHE_HOME")
    if not root and sys.platform == "darwin":
        return _mac_root(".cache", "Caches")
    return _migrated(pathlib.Path(root or (pathlib.Path.home() / ".cache")))


def config_root() -> pathlib.Path:
    """The settings directory, the same way. Roaming on Windows, ~/Library on a
    Mac, XDG_CONFIG_HOME elsewhere -- the division lyrics_gui.app_dir draws."""
    if os.name == "nt":
        root = os.environ.get("APPDATA") or (
            pathlib.Path.home() / "AppData" / "Roaming")
        return _migrated(pathlib.Path(root))
    root = os.environ.get("XDG_CONFIG_HOME")
    if not root and sys.platform == "darwin":
        return _mac_root(".config", "Application Support")
    return _migrated(pathlib.Path(root or (pathlib.Path.home() / ".config")))


def _mac_root(legacy: str, library: str) -> pathlib.Path:
    """A Mac's own directory, unless an older copy is already in the XDG one.

    The same rule lyrics_gui._mac_dir follows, and it has to be the same rule:
    these two walk to the same folder from different modules, and a disagreement
    would be a program reading its cache from one place and writing it to
    another."""
    here = pathlib.Path.home() / legacy
    for slug in ("mild-lyrics", "spicy-lyrics"):
        if (here / slug).is_dir():
            return _migrated(here)
    return _migrated(pathlib.Path.home() / "Library" / library)


def _migrated(root: pathlib.Path) -> pathlib.Path:
    """Kept in step with lyrics_gui.app_dir, including its one-time rename."""
    new, old = root / "mild-lyrics", root / "spicy-lyrics"
    try:
        if old.is_dir() and not new.exists():
            old.rename(new)
    except Exception:
        pass
    return new


_cache_root = cache_root


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
WORDED_SHARE = 0.5


def quality(body) -> str:
    """What we actually have, judged by the data rather than the Type field.

    A document can claim "Syllable" and carry no timed syllables at all, and a
    "Line" one is useless if none of its lines got a StartTime, so this looks.

    MOST of the lines, though, not one of them. Apple ships line-synced TTML
    that carries a single timed <span>: the one line with a backing vocal on
    it, whose lead has to be wrapped in a span so the x-bg can hang off it.
    Read as word timing, that is a 38-line document declaring itself
    word-synced on the strength of line 36 -- Three Days Grace's "Never Too
    Late" through BiniLyrics is the case. It said "word-synced" under the
    lyrics, it left the other 37 lines to light in one lump, and it stood
    every blend on the track down (see _outdone), which is the one thing that
    would have given those lines their words.
    """
    doc = SL.payload(body or {})
    items = next(
        (doc[k] for k in ("Content", "Lines") if isinstance(doc.get(k), list) and doc[k]), []
    )
    items = [i for i in items if isinstance(i, dict)]
    if not items:
        return "none"
    worded = sum(
        1 for item in items
        if isinstance(item.get("Lead"), dict)
        and any(isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float))
                for y in item["Lead"].get("Syllables") or [])
    )
    if worded >= WORDED_SHARE * len(items):
        return "syllable"
    if any(SL.line_start(i) is not None for i in items):
        return "line"
    return "static" if any((SL.line_text(i) or "").strip() for i in items) else "none"


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
_WALK = threading.local()


def _walking() -> bool:
    """Whether this thread's walk is still wanted. True where nobody said.

    A caller that passes no `alive` gets what it always got: a walk that
    finishes what it started. The predicate is somebody else's and is called
    from every provider thread, so it is never allowed to decide the question
    by raising.
    """
    alive = getattr(_WALK, "alive", None)
    if alive is None:
        return True
    try:
        return bool(alive())
    except Exception:                                    # noqa: BLE001
        return True


def _latched(alive):
    """A walk's cancel token, made final.

    Callers spell "does anybody still want this?" as a question about the
    state of this moment, and the state of this moment comes back. The
    fetcher asks whether the slot still holds the track it is walking for;
    the look-ahead asks whether the slot is empty at all. Both can answer no
    and then, a moment later, answer yes again -- the fetcher's own loop
    takes the wanted id OFF the slot before it starts loading it, so a track
    change is a blink of "nobody wants this" between two stretches of
    "carry on".

    A blink is all it takes. Every request in flight reads the token (see
    _get) and comes back empty the instant it says no, so the providers that
    were mid-fetch lose their answers; the walk then finds the token saying
    yes again, reaches the end, and STORES what is left as though it were the
    whole truth. That record outlives the blink by a month -- the store is
    keyed by the question, and the question it wrote down is the full one --
    so a song whose first round was cut off keeps a second-best answer for as
    long as it stays in rotation.

    Seen as Apple Music's own word-timed document missing from a song Apple
    Music has, with a blend on somebody else's lines stored in its place, and
    the same walk run again by hand picking Apple in four tenths of a second.

    So a cancel is final here. Once a walk has been told it is not wanted it
    stays told, it stores nothing, and the caller -- which is still there, or
    it would not have changed the slot -- asks the question again from the
    top. Nobody waits any longer for it: the walk was already being abandoned,
    this only stops it coming back.
    """
    if alive is None:
        return None
    gone: list = []

    def still() -> bool:
        if gone:
            return False
        try:
            ok = bool(alive())
        except Exception:                                # noqa: BLE001
            ok = True
        if not ok:
            gone.append(True)
        return ok

    return still


def _under(alive, fn, faults=None, who=None, people=None):
    """`fn`, run as part of the walk `alive` speaks for.

    `people` rides along for the one provider that has to choose between
    documents BEFORE the walk ever sees them -- see from_unison, where a
    community database offers several syncs of one song and the roster is the
    user saying which of those people they trust. Everywhere else the roster
    is asked about the answer, which is after the choosing and too late.
    """
    was = (getattr(_WALK, "alive", None), getattr(_WALK, "faults", None),
           getattr(_WALK, "who", ""), getattr(_WALK, "people", None))
    _WALK.alive = alive
    if faults is not None:
        _WALK.faults = faults
    if who is not None:
        _WALK.who = who
    if people is not None:
        _WALK.people = people
    try:
        return fn()
    finally:
        _WALK.alive, _WALK.faults, _WALK.who, _WALK.people = was


# --------------------------------------------------------------------------
MISSED = {404}


def _why(exc: BaseException, limit: float = TIMEOUT) -> str:
    """One short line for what a request did instead of answering."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    inner = getattr(exc, "reason", None)
    if isinstance(inner, BaseException):
        exc, inner = inner, getattr(inner, "reason", None)
    if isinstance(exc, TimeoutError):
        return f"timed out after {limit:g}s"
    return str(inner or exc).strip() or type(exc).__name__


def _blamed(why: str, whom: str = "") -> None:
    """File one failure against whoever the walk is asking.

    The FIRST one is kept. A provider is several requests -- a search, then a
    download, then the same again for the second shape of the question -- and
    once its host is down they all say the same thing; what the user wants is
    the name of the source and one reason, not five lines of the same reason.

    `whom` is who to file it under where the walk has not said -- which is
    the case for a provider that raised on its way out, since it is no longer
    inside the _asks that named it.
    """
    faults = getattr(_WALK, "faults", None)
    who = getattr(_WALK, "who", "") or whom
    if faults is not None and who:
        faults.setdefault(who, why)


def _asks(name: str, fn):
    """`fn`, with whatever it does to the network filed under `name`."""
    return _under(getattr(_WALK, "alive", None), fn, who=name)


_HOST_CAP: dict[str, int] = {}
_HOST_CAP_DEFAULT = 4
# A host that wants longer than TIMEOUT before it is given up on. Empty since
# LyricsPlus went: twenty seconds was its, and nothing else here has ever
# asked for more than the eight everybody gets.
_HOST_PATIENCE: dict[str, float] = {}


def _patience(url: str) -> float:
    return _HOST_PATIENCE.get(urllib.parse.urlsplit(url).netloc, TIMEOUT)
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
    if not _walking():
        return None
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    wait = _patience(url)
    with _gate(url):
        if not _walking():
            return None
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(req, timeout=wait) as r:
                    if r.status == 200:
                        return r.read()
                    _blamed(f"HTTP {r.status}")
                    return None
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 2:
                    if e.code not in MISSED:
                        _blamed(_why(e, wait))
                    return None
                time.sleep(0.7)
                if not _walking():
                    return None
            except Exception as e:                       # noqa: BLE001
                _blamed(_why(e, wait))
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


_OPENS = "\u00ab\u201c\u00bf\u00a1([{"
_CLOSES = "\u00bb\u201d)]}"


def _apart(a: str, b: str) -> bool:
    """Whether a space belongs between these two spans whatever the file says.

    Two spans written back to back are a file saying they spell ONE word --
    "Couldn't" cut into "Couldn" and "'t" -- and that rule is right and is
    what _syllables is built on. It cannot be true of every pair, though. An
    opening quotation mark never sits against the word in front of it and a
    closing one never sits against the word behind it, in any language that
    uses them: a source that writes

        <span>crie :</span><span>\u00ab</span>

    has dropped a space, it is not claiming "crie :\u00ab" is a word. French
    drops that one often, because the space it wants there is a narrow
    no-break space and does not survive whatever handled the file before this.

    ONLY THE UNAMBIGUOUS MARKS, and the two exclusions are the whole of why
    this is a list and not a category test:

      * \u2019 is left out. It is the apostrophe in "don\u2019t" and
        "c\u2019est" at least as often as it is a quote, and a rule that put
        a space inside those would be far worse than the one it fixes.
      * \u300c \u300d \u300e \u300f and the other CJK brackets are left
        out for the opposite reason: they take no spaces at all, so inserting
        one would be the same fault in the other direction.
    """
    return bool(a and b and (b[0] in _OPENS or a[-1] in _CLOSES))


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

    A span with no `begin` is still a syllable. A file being written carries
    its words -- and the splits somebody cut them into -- long before it
    carries a timing, and this editor's own working copies and backups are
    exactly that file. Dropping the untimed spans left the line to be read
    back out of its flattened text, where every split, and every word a
    half-timed line had not reached yet, had gone.

    Only where the <p> holds no loose text of its own, though, and only once
    nothing in it is timed: a paragraph that mixes plain words with a span or
    two is writing a sentence, not spelling one out, and the words outside
    the spans would be lost if the spans were read as the whole line.
    """
    out = []
    spans = [sp for sp in parent if _tag(sp) == "span" and not _attr(sp, "role")]
    if not any(_secs(_attr(sp, "begin")) is not None for sp in spans) \
            and (parent.text or "").strip():
        spans = []
    for i, sp in enumerate(spans):
        s, e = _secs(_attr(sp, "begin")), _secs(_attr(sp, "end"))
        text = "".join(sp.itertext())
        tail = sp.tail or ""
        if tail.strip():
            text += tail.rstrip()
        nxt = "".join(spans[i + 1].itertext()) if i + 1 < len(spans) else ""
        if spaced:
            part = not (tail and tail != tail.strip())
        elif not (_latin(text) or _latin(nxt)):
            part = True
        else:
            part = (not any(c.isalnum() for c in text)
                    or bool(nxt) and not nxt[0].isalnum())
        if part and _apart(text, nxt):
            part = False
        y = {"Text": text, "IsPartOfWord": part}
        if s is not None:
            y["StartTime"] = s
            y["EndTime"] = e if e is not None else s
        out.append(y)
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

    Syllables with no stamp at all are not out of place, only unwritten yet;
    they sit the repair out and keep their neighbours' company.
    """
    timed = [y for y in syls if isinstance(y.get("StartTime"), (int, float))]
    if len(timed) != len(syls):
        if timed:
            _repair(timed, begin, end)
        return syls
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
        up = max(lo, up)
        run = [j for j in range(len(syls)) if j not in ok
               and (j == i or lo <= syls[j].get("StartTime", -1) <= up)]
        run = [j for j in run if all(k not in ok for k in range(min(j, i), max(j, i)))]
        k, n = run.index(i), max(len(run), 1)
        y["StartTime"] = lo + (up - lo) * k / n
        y["EndTime"] = lo + (up - lo) * (k + 1) / n
    return syls


PAIRS = {"(": ")", "[": "]", "（": "）", "「": "」", "【": "】"}


def _unbracket(text: str) -> str:
    """The same peel as `_unwrap`, for an ad-lib written as one piece of text."""
    close = PAIRS.get(text[:1])
    if close and len(text) > 2 and text.endswith(close):
        return text[1:-1].strip() or text
    return text


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
    stamps = [y for y in syls if isinstance(y.get("StartTime"), (int, float))]
    if s is None and stamps:
        s = stamps[0]["StartTime"]
    ends = [y["EndTime"] for y in stamps if isinstance(y.get("EndTime"), (int, float))]
    if e is None and ends:
        e = max(ends)
    if s is not None:
        g["StartTime"] = s
    if e is not None:
        g["EndTime"] = e
    return g


def _destamp(items: list[dict]) -> list[dict]:
    """Drop timings that are not really timings.

    A document can arrive with plain, unsynced lyrics in the same timed shape
    as everything else, every line stamped 00:00.000. Taken at face value
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


def _credits(root) -> tuple[list[str], str, dict]:
    """Who wrote the song, who timed this copy of it, and what song it is.

    Three conventions in play, all in the same <head>. Apple writes
    <songwriters><songwriter>. A <lyricsplus:curator> names whoever submitted
    a sync, which no source here fetches any more and a file dropped on the
    window can still carry. amll-ttml-db files the same fact as an <amll:meta
    key="ttmlAuthorGithubLogin">.

    Matched by local name: the prefixes differ per file, and amll's <metadata>
    binds xmlns="" so half of it is in no namespace at all.

    The title, artist and album come out of the same <amll:meta> tags, and
    they are the only place in a TTML head a song can say what it is. Apple's
    own files never do, which is why a document saved out of the editor used
    to come back not knowing its own name.
    """
    head = next((el for el in root if _tag(el) == "head"), root)
    writers, maker, seen, said = [], "", set(), {}
    for el in head.iter():
        tag, text = _tag(el), (el.text or "").strip()
        if tag == "songwriter" and text and text.lower() not in seen:
            seen.add(text.lower())
            writers.append(text)
        elif tag == "curator" and text:
            maker = maker or text
        elif tag == "meta":
            key, value = _attr(el, "key"), (_attr(el, "value") or "").strip()
            if key in ("ttmlAuthorGithubLogin", "ttmlAuthor"):
                maker = maker or value
            elif key in SL.AMLL_LABELS and value:
                said.setdefault(SL.AMLL_LABELS[key], value)
    return writers, maker, said


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
        ahead = not (p.text or "").strip()
        for sp in p:
            role = _attr(sp, "role") if _tag(sp) == "span" else None
            if role == "x-bg":
                g = _group(sp, spaced, bg=True)
                if ahead and not isinstance(g.get("StartTime"), (int, float)):
                    g["LeadIn"] = True
                if not g["Syllables"]:
                    g["Text"] = _unbracket("".join(sp.itertext()).strip())
                if g["Syllables"] or g.get("Text"):
                    bg.append(g)
            elif _tag(sp) == "span" and not role:
                ahead = False
            if (sp.tail or "").strip():
                ahead = False
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
        if not text.strip():
            for g in bg:
                g.pop("LeadIn", None)
            if not bg:
                continue
        cjk = cjk or bool(SL.CJK.search(text))
        item: dict = {"Text": text}
        if lead:
            if ps is not None:
                lead.setdefault("StartTime", ps)
            if pe is not None:
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
    worded = any(isinstance(y.get("StartTime"), (int, float))
                 for i in items
                 for y in ((i.get("Lead") or {}).get("Syllables") or []))
    typed = "Syllable" if worded else (
        "Line" if any("StartTime" in i for i in items) else "Static")
    doc = {
        "Type": typed,
        ("Lines" if typed == "Static" else "Content"): items,
        "HasTransliterations": cjk,
    }
    lang = _attr(root, "lang")
    if lang:
        doc["Language"] = lang
    writers, maker, said = _credits(root)
    if writers:
        doc["SongWriters"] = writers
    if maker:
        doc["_maker"] = maker
    doc.update(said)
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
                    "HasTransliterations": any(SL.SCRIPTED.search(i["Text"]) for i in items)}
    lines = [l.strip() for l in (plain or "").splitlines() if l.strip()]
    if not lines:
        return None
    return {"Type": "Static", "Lines": [{"Text": l} for l in lines],
            "HasTransliterations": any(SL.SCRIPTED.search(l) for l in lines)}


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


def _song_key(name: str) -> str:
    """_norm, with any version marker kept out of the words it swallowed.

    For the one lookup that is a dict and not a list of hits to examine.
    Everywhere else a candidate arrives with its title attached and _same_cut
    reads it there; here the question has to be asked of the key itself, or
    "Galaxies (Remix)" and "Galaxies" are the same three-word string and the
    index has no way left to tell them apart. See ALT_CUT.

    A title carrying no marker keys exactly as _norm alone did, which is
    almost all of them and is what lets an index cached before this existed
    go on answering for them.
    """
    cut = _cut_words(name)
    return _norm(name) + ("\x01" + ",".join(sorted(cut)) if cut else "")


# --------------------------------------------------------------------------
# Spicy Lyrics.
#
# The source this project was built around, and now an ordinary provider in
# this file with the other ten: one HTTP request, a key, the same timeout, the
# same trouble reporting, the same cache rules. It reads by Spotify track id
# rather than by title and artist, which is the one thing that makes it
# different in kind -- and is why it can be asked before the rest and its
# answer handed to them as the document already in hand; see _walk's lead.
#
# It used to be read over the Chrome DevTools protocol out of the Spicetify
# extension's own Cache Storage inside a running Spotify, which is why it
# lived in spicy_lyrics.py and not here. That module keeps what it always
# was -- the document, its timeline, its renderers -- and none of the fetching.
# --------------------------------------------------------------------------
SPICY_BASE = (os.environ.get("SPICY_LYRICS_API")
              or "https://api.spicylyrics.org").rstrip("/")
SPICY_ID = re.compile(r"^[A-Za-z0-9]{22}$")

# Spicy Lyrics names the winning catalogue in full; this project has always
# filed it in three letters, and those three letters are what is written into
# the snapshots, the datasets and every "was this a person's work" branch in
# sync/. Translating here, at the one door its documents come in by, is what
# keeps a fetch made today comparable with a snapshot taken last year.
# "unknown" becomes no source at all, which is what an unattributed document
# has always looked like downstream -- and what the terms require it be called.
SPICY_CODES = {"spicy_lyrics": "spl", "apple_music": "aml", "spotify": "spt",
               "unknown": ""}

# The key that ships. Public by design: a publishable key travels in the
# program and anyone can read it, which is exactly why a SECRET key must never
# be put here. This one is issued with the "no Origin header" allowance, which
# is what a desktop client needs -- nothing here is a browser, so no Origin is
# ever sent and an allowlist would refuse every request made from here.
# Verified against the live API on 2026-09-20 with no Origin header sent.
SPICY_SHIPPED_KEY = "sl_pk_2fyQ-sFN0OnWEjG9WmusHHY9vS8Re7zHj3kSbJncHbM"

SPICY_KEY_ENV = ("SPICY_LYRICS_KEY", "SPICY_LYRICS_SECRET_KEY")
SPICY_KEY_FILE = config_root() / "spicy-key.txt"

# Its own directory rather than a corner of `sources`, because the two answer
# different questions. A record under `sources` is what a WALK decided, and is
# read back only by a walk asking the same question of the same providers;
# these are one catalogue's answer about one track, asked for by id, and they
# are the only list of songs this program can offer -- the API answers about a
# track and does not enumerate its catalogue. Same rules either way, and
# sweep() clears both.
SPICY_DIR = _cache_root() / "spicy"
SPICY_REV = 1

# Set when this application's OWN request window is spent. Nothing asks again
# before it passes: the window fetches on every track change and the batch
# tools walk thousands of ids, so the one thing this must not do with a rate
# limit is spend the whole of the next window finding out about it again.
#
# Only ours. A 429 whose code is `upstream_rate_limited` is Spicy Lyrics being
# throttled by the catalogue it asked, for that lookup -- measured with 56 of
# 60 requests still in hand, and the very next track answering 200. Standing
# the whole program down over one of those would turn one unlucky song into a
# minute of silence for every other song.
_spicy_hushed = 0.0
_spicy_hushed_why = ""

# What the service last said was left of the window, as
# {"limit", "left", "reset", "at"}. Every answer carries it, happy or not.
SPICY_LIMIT: dict = {}


class SpicyError(Exception):
    """Spicy Lyrics could not be asked, or would not answer.

    Not the same thing as it saying a track has no lyrics, which is an answer
    -- None -- and is cached as one. This is everything else: no key, a key
    the service will not take, a rate limit, a timeout, a 500. The difference
    matters to every caller, because a source that had nothing is settled and
    a source that could not be reached is worth saying out loud and asking
    again later; see lyrics_gui.Fetcher._spicy_body.

    `code` is the service's own machine-readable error where it gave one
    ("lyrics_not_found", "rate_limited", "key_revoked", ...), `status` the
    HTTP status, and `after` the seconds it asked to be left alone for.
    """

    def __init__(self, why: str, code: str = "", status: int = 0,
                 after: float = 0.0):
        super().__init__(why)
        self.code, self.status, self.after = code, int(status), float(after)

    @property
    def key_fault(self) -> bool:
        """Whether this is the key's fault, and so will not fix itself.

        Worth telling apart from an outage: retrying costs nothing when a host
        is down and is pure noise when the credential is wrong.
        """
        return self.status in (401, 403) or self.code.startswith("key_") or (
            self.code in ("missing_authorization", "malformed_authorization",
                          "missing_scope", "origin_not_allowed",
                          "origins_not_configured", "application_paused",
                          "application_suspended", "application_deleted",
                          "user_suspended"))


def spicy_key() -> str:
    """The key to send, from the environment, the config file, or the build.

    The environment wins so that a rotated key can be tried without editing
    anything, and a secret key handed to one machine stays on that machine.
    """
    for name in SPICY_KEY_ENV:
        got = (os.environ.get(name) or "").strip()
        if got:
            return got
    try:
        for row in SPICY_KEY_FILE.read_text(encoding="utf-8").splitlines():
            if row.strip() and not row.lstrip().startswith("#"):
                return row.strip()
    except Exception:                                    # noqa: BLE001
        pass
    return SPICY_SHIPPED_KEY.strip()


def set_spicy_key(value: str) -> pathlib.Path:
    """Keep a key for next time, readable only by its owner.

    In the config directory rather than this tree: a secret key that lands in
    a working copy is one `git add -A` away from being published, and no
    permission on the file prevents that. A publishable one belongs in
    SPICY_SHIPPED_KEY instead, where it ships.
    """
    SPICY_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SPICY_KEY_FILE.write_text(value.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(SPICY_KEY_FILE, 0o600)
    except OSError:
        pass
    return SPICY_KEY_FILE


def _spicy_envelope(raw: bytes, status: int) -> dict:
    try:
        got = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError as exc:
        raise SpicyError(f"unreadable answer ({exc})", status=status) from None
    return got if isinstance(got, dict) else {}


def _spicy_refused(status: int, body: dict, after: float) -> SpicyError:
    """The error an unhappy status describes, with the service's own words."""
    err = body.get("Body") if isinstance(body.get("Body"), dict) else {}
    return SpicyError(str(err.get("message") or "").strip() or f"HTTP {status}",
                      code=str(err.get("error") or ""), status=status,
                      after=after)


def _head_num(headers, name: str):
    """One header as a number, or None where it was not sent or not one."""
    try:
        return float((headers.get(name) or "").strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _head_secs(headers, name: str) -> float:
    """One header as a wait in seconds, capped at an hour, or 0."""
    got = _head_num(headers, name)
    return min(got, 3600.0) if got and got > 0 else 0.0


def _spicy_after(headers) -> float:
    """How long the service asked to be left alone, in seconds.

    Retry-After where it sent one, the window's own reset where it did not,
    and a minute where it said neither -- a limit with no stated window is
    still a limit, and hammering it is how a key gets suspended.
    """
    return (_head_secs(headers, "Retry-After")
            or _head_secs(headers, "RateLimit-Reset") or 60.0)


def _spicy_hush(after: float, why: str) -> None:
    global _spicy_hushed, _spicy_hushed_why
    _spicy_hushed = time.monotonic() + max(after, 1.0)
    _spicy_hushed_why = why


def _spicy_budget(headers) -> None:
    """Note what is left of this application's window, and stop when it is.

    Every answer carries it, so this is free, and it is the one reading here
    that is about US rather than about one lookup: a spent window refuses the
    next request whatever it is for, so there is no sense in making it. The
    difference between noticing at zero and noticing at the first refusal is
    a run that pauses and a run that fills a log with 429s.
    """
    left = _head_num(headers, "RateLimit-Remaining")
    if left is None:
        return
    limit = _head_num(headers, "RateLimit-Limit")
    reset = _head_secs(headers, "RateLimit-Reset")
    SPICY_LIMIT.update({"limit": int(limit or 0), "left": int(left),
                        "reset": reset, "at": time.time()})
    if left <= 0:
        _spicy_hush(reset or 60.0,
                    f"out of requests ({int(limit or 0) or '?'} a window)")


def _spicy_fetch(track: str, timeout: float = TIMEOUT) -> dict | None:
    """Spicy Lyrics' document for one track, or None where it has no lyrics.

    Everything that is not an answer raises SpicyError, including a track id
    this never sent: 22 base62 characters is the whole of the API's contract
    for the path, and a URI, a URL or a stray space would otherwise be spent
    on a round trip that can only come back 400.
    """
    tid = (track or "").strip()
    if not SPICY_ID.match(tid):
        raise SpicyError(f"{tid!r} is not a Spotify track id "
                         f"(22 base62 characters)", code="invalid_track_id")
    token = spicy_key()
    if not token:
        raise SpicyError(
            "no Spicy Lyrics key -- set SPICY_LYRICS_KEY or run "
            "`spicy_lyrics.py key sl_sk_...`", code="missing_authorization")
    left = _spicy_hushed - time.monotonic()
    if left > 0:
        raise SpicyError(f"{_spicy_hushed_why or 'asked to wait'}; "
                         f"{left:.0f}s left", code="rate_limited", after=left)
    req = urllib.request.Request(
        f"{SPICY_BASE}/v1/lyrics/{tid}",
        headers={"Authorization": f"Bearer {token}", "User-Agent": UA,
                 "Accept": "application/json"})
    try:
        with _gate(SPICY_BASE):
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                _spicy_budget(r.headers)
                got = _spicy_envelope(raw, r.status)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:                                # noqa: BLE001
            raw = b""
        _spicy_budget(exc.headers)
        body = _spicy_envelope(raw, exc.code) if raw else {}
        wait = _spicy_after(exc.headers)
        bad = _spicy_refused(exc.code, body, wait)
        # 404 is the one unhappy status that is an ANSWER: nobody has lyrics
        # for this track. It is worth remembering for a while (see MISS_TTL)
        # and it is not worth telling anyone about. Read with its code rather
        # than on the status alone, so that a 404 from somewhere that is not
        # this endpoint -- a base URL pointed wrong, a proxy answering for it
        # -- is the failure it is instead of six hours of "this song has no
        # lyrics".
        if exc.code == 404 and bad.code in ("lyrics_not_found", "not_found", ""):
            return None
        # Our own window, and only ours: `rate_limited` is this application's
        # (or this viewer's) budget spent, and nothing else will be answered
        # until it resets. `upstream_rate_limited` is the catalogue throttling
        # Spicy Lyrics for one lookup, and the next track is unaffected.
        if exc.code == 429 and bad.code in ("rate_limited", ""):
            _spicy_hush(wait, str(bad) or "rate limited")
        raise bad from None
    except urllib.error.URLError as exc:
        raise SpicyError(f"could not reach {SPICY_BASE} ({exc.reason})") from None
    except (TimeoutError, OSError) as exc:
        raise SpicyError(f"could not reach {SPICY_BASE} ({exc})") from None
    doc = got.get("Body")
    if not isinstance(doc, dict):
        raise SpicyError("the answer carried no document", status=200)
    return _spicy_docked(doc, tid)


def _spicy_docked(doc: dict, tid: str) -> dict:
    """A document as this project keeps them.

    Three small things, all of them at this one door so that nothing
    downstream has to know a document was fetched today rather than snapshotted
    two years ago:

      * the zero-width spaces Spicy Lyrics writes into its text come out (see
        SL.unzwsp_body for why removal and not substitution);
      * the catalogue is renamed to its three-letter code (see SPICY_CODES);
      * the credits are filed under TTMLUploadMetadata, which is where every
        reader of them in this program looks -- the roster that refuses or
        prefers a person by id, the credit line under the lyrics, and the
        dataset builder that will only train on a sync somebody's hand made.
        The API calls the field UploadAttribution and its contents are
        identical; the name on disk is the older one, and the snapshots still
        holding it are the ones the benchmarks are measured against.

    The track id is filled in where the service left it out, because
    everything downstream reads it off the document.
    """
    out = dict(SL.unzwsp_body(doc))
    was = str(out.get("source") or "")
    if was in SPICY_CODES:
        out["source"] = SPICY_CODES[was]
    credit = out.pop("UploadAttribution", None)
    if isinstance(credit, dict) and credit:
        out.setdefault("TTMLUploadMetadata", credit)
    if not out.get("id"):
        out["id"] = tid
    return out


# --------------------------------------------------------------------------
# Its cache. The same rules as the walk's own -- a record per track, a month
# from its last use, six hours for a "nobody has this" -- and the same reasons;
# see _cached.
# --------------------------------------------------------------------------
def _spicy_path(track: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", track or "unknown")[:64]
    return SPICY_DIR / f"{safe}.json"


def _spicy_record(track: str, touch: bool = True) -> dict | None:
    """The stored answer for a track, or None if there is not a usable one.

    A miss ages from when it was taken: six hours after the service said no,
    asking again is worth the round trip, because the thing that changes is
    somebody uploading a sync. A hit ages from when it was last USED, so a
    song in rotation keeps its lyrics for as long as it stays in rotation.
    """
    path = _spicy_path(track)
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return None
    if not isinstance(rec, dict) or rec.get("rev") != SPICY_REV:
        return None
    at = float(rec.get("at") or 0)
    if not isinstance(rec.get("doc"), dict) or not rec["doc"]:
        return None if time.time() - at > MISS_TTL else rec
    try:
        used = max(at, path.stat().st_mtime)
    except OSError:
        used = at
    if time.time() - used > HIT_TTL:
        return None
    if touch:
        _touch(path)
    return rec


def _spicy_keep(track: str, doc: dict | None) -> None:
    """Remember an answer, a nothing included. Never raises."""
    try:
        SPICY_DIR.mkdir(parents=True, exist_ok=True)
        _spicy_path(track).write_text(
            json.dumps({"rev": SPICY_REV, "at": time.time(), "doc": doc or None},
                       ensure_ascii=False), encoding="utf-8")
    except Exception:                                    # noqa: BLE001
        pass


def spicy_held(track: str) -> dict | None:
    """The document held on disk for a track, asking nobody.

    For the callers that want something true to put up while a fetch happens,
    and for the ones that must not go to the network at all -- the benchmarks
    and the dataset builders, which walk thousands of ids.
    """
    rec = _spicy_record(track)
    doc = (rec or {}).get("doc")
    return doc if isinstance(doc, dict) and doc else None


def spicy_lyrics(track: str, refresh: bool = False, timeout: float = TIMEOUT):
    """Spicy Lyrics' document for a track: off the disk, or asked for.

    None means the service has nothing for this track. SpicyError means it was
    not asked or would not say, which is a different thing and is never cached
    as an answer -- an outage must not become a month of "this song has no
    lyrics".
    """
    if not refresh:
        rec = _spicy_record(track)
        if rec is not None:
            doc = rec.get("doc")
            return doc if isinstance(doc, dict) and doc else None
    doc = _spicy_fetch(track, timeout=timeout)
    _spicy_keep(track, doc)
    return doc


def from_spicy(tid: str, meta: dict | None = None, local=None, **_kw):
    """Spicy Lyrics, in the shape every other provider in this file has.

    Never raises: trouble is filed through _blamed like anybody else's, so a
    walk carries on without it and the window is told which source it did not
    get. The direct form -- spicy_lyrics() -- is for the callers that want the
    reason in their hands rather than in a report.

    `meta` is ignored. This is the one source here asked by Spotify track id
    rather than by title, artist and length, which is also why it cannot
    answer at all for a player that has no Spotify id to give (see
    lyrics_gui.SmtcTransport).
    """
    try:
        return spicy_lyrics(tid)
    except SpicyError as exc:
        _blamed(str(exc), "spicy")
        return None


from_spicy.leads = True
from_spicy.credits_people = True


def spicy_ids() -> list[str]:
    """The tracks a Spicy Lyrics document is held for here.

    This is the whole of what can be enumerated, and it is worth being plain
    about what it is not: the API answers about one track and does not list
    its catalogue, so this is the songs this machine has fetched, not the
    songs Spicy Lyrics has. Every batch command that used to walk the
    Spicetify cache -- the window's search index, the benchmarks, the dataset
    builders -- is asking that narrower question now, and it grows as songs
    are played.
    """
    out = []
    try:
        rows = sorted(SPICY_DIR.glob("*.json"))
    except OSError:
        return out
    for path in rows:
        if spicy_held(path.stem):
            out.append(path.stem)
    return out


def spicy_page(offset: int, limit: int) -> list[dict]:
    """One page of what is held: [{id, body}, ...], oldest id first.

    Paged for the same reason it always was -- the window walks the lot while
    it goes on answering lyric requests between pages; see Fetcher._index_batch.
    """
    try:
        rows = sorted(SPICY_DIR.glob("*.json"))[offset:offset + max(0, limit)]
    except OSError:
        return []
    out = []
    for path in rows:
        doc = spicy_held(path.stem)
        if doc:
            out.append({"id": path.stem, "body": doc})
    return out


def forget_spicy(track: str) -> None:
    """Drop what is held for a track, so the next ask really asks."""
    try:
        _spicy_path(track).unlink()
    except OSError:
        pass


def _sweep_spicy(now: float) -> int:
    """The Spicy Lyrics cache, aged out by the same rule as the walk's."""
    if not SPICY_DIR.is_dir():
        return 0
    gone = 0
    for path in SPICY_DIR.glob("*.json"):
        if _spicy_record(path.stem, touch=False) is not None:
            continue
        try:
            path.unlink()
            gone += 1
        except OSError:
            pass
    return gone


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
                out.setdefault(f"{_song_key(name)}\x00{_norm(art)}", f)
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
        f = idx.get(f"{_song_key(title)}\x00{_norm(art)}")
        if f:
            raw = _get(f"{AMLL_RAW}/raw-lyrics/{urllib.parse.quote(f)}", "application/xml")
            if raw:
                doc = parse_ttml(raw)
                if doc:
                    return doc
    return None


def from_qq(tid: str, meta: dict, local=None) -> dict | None:
    """QQ Music's own document, its lines as well as its timings.

    The blends take QQ's word timing and lay it under Apple's lines, which is
    usually the better document -- Apple's wording, casing and line splits are
    the ones this player is built around. Usually is not always: QQ writes
    ad-libs the Apple copy simply does not have, on their own lines and in
    their own time, and where reconciling the two loses them the source on its
    own is the honest answer.

    Asked of QQ directly, and only of QQ; see _qq. A second door used to be
    kept behind this one -- LyricsPlus', which is gone -- on the grounds that
    the two fail on different songs and its copy was worth one request on the
    handful QQ's own endpoint cannot find. One request there was ten seconds,
    it was spent on every song QQ missed rather than on the handful, and it
    was spent inside the round the blends are waiting on, for a document that,
    where it arrived at all, was QQ's anyway.
    """
    return _once(("qq", tid, _norm(meta.get("title") or ""),
                  _norm(meta.get("artist") or ""),
                  round(float(meta.get("length") or 0))),
                 lambda: _qq(tid, meta))


def from_lrclib(tid: str, meta: dict, local=None) -> dict | None:
    """LRCLIB, by exact record where it has one and by search where it does not.

    /api/get matches the name, the byline and the duration itself, so what
    comes back from it is this recording or nothing. /api/search matches on
    the words, and until the ALT_CUT test below the only thing asked of a hit
    was that it be within four seconds -- which is how the search for
    Protostar's instrumental "Galaxies" came back with "Galaxies (Rogue
    Remix)", four minutes flat against four minutes five, sorted to the top
    for being the only hit anybody had synced.
    """
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
        hits = [h for h in hits if isinstance(h, dict) and not h.get("instrumental")
                and _same_cut(h.get("trackName") or "", title)]
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
NE_CREDIT = re.compile(
    r"^\s*(?:"
    r"[一-鿿]{0,6}?(?:作词|作曲|编曲|制作|出品|监制|录音|混音|母带|吉他|贝斯"
    r"|鼓|键盘|和声|弦乐|人声|策划|统筹|发行|工程师|演奏|词|曲)[一-鿿]{0,2}?"
    r"|lyric(?:s|ist)?|compos(?:ed|er|ition)|writ(?:ten|er)|music"
    r"|arrang(?:ed|er|ement)|produc(?:ed|er|tion)|mix(?:ed|ing)?|talkbox|rap"
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
    wait = _patience(url)
    with _gate(url):
        try:
            with urllib.request.urlopen(req, timeout=wait) as r:
                return json.loads(r.read())
        except Exception as e:                           # noqa: BLE001
            if not isinstance(e, urllib.error.HTTPError) or e.code not in MISSED:
                _blamed(_why(e, wait))
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
        if not _same_cut(s.get("name") or "", title):
            continue
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
        if int(same) + int(near) + int(byline) < 2:
            continue
        mismatch = bool(akey) and bool(mine) and not byline and any(
            _comparable(akey, a) for a in mine)
        score = (0 if far else 1,
                 0 if mismatch else 1,
                 1 if same else 0,
                 1 if byline else 0,
                 1 if near else 0,
                 -abs(dur - want) if want else 0)
        scored.append((score, s["id"]))
    scored.sort(key=lambda r: r[0], reverse=True)
    return [(sid, sc[:5]) for sc, sid in scored]


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
    """NetEase Cloud Music, asked once per track however many callers want it."""
    return _once(("netease", tid, _norm(meta.get("title") or ""),
                  _norm(meta.get("artist") or ""), round(float(meta.get("length") or 0))),
                 lambda: _netease(tid, meta))


def _netease(tid: str, meta: dict) -> dict | None:
    """NetEase Cloud Music.

    Worth a slot of its own: it is the only source here that ships a human-written romanisation (`romalrc`) on the same
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
ASIDE_REACH = 2.0
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


def _filed_apart(doc) -> set:
    """The ad-libs a donor keeps out of its own line stream, by their words.

    A source that marks its backing vocals properly puts them in a group of
    their own, beside the line rather than inside it. Their letters are
    therefore not in the stream _restream reads, and a base that writes the
    same ad-lib INSIDE its line has letters with nothing to match against.
    """
    got = {_key(SL.syllables_text(g.get("Syllables") or []))
           for it in _items(SL.payload(doc or {}))
           for g in (it.get("Background") or []) if isinstance(g, dict)}
    got.discard("")
    return got


def _unaside(text: str, apart: set) -> str:
    """A line without the ad-libs the donor files apart from its own words.

    Only those. A bracket the donor writes into its line like everybody else
    is in the stream and has to stay here too, or the line loses the letters
    that were going to fetch its timing: on Linkin Park's "Runaway", "Mind
    (Gonna run away, gonna run away)" is one line to NetEase as well, and
    taking every bracket out left that line matched to the four letters of
    "Mind" with nothing to relay.
    """
    if not apart:
        return text

    def take(m):
        key = _key(m.group(1))
        return "" if key and any(_kin(key, k) for k in apart) else m.group(0)

    return BRACKETED.sub(take, text)


def _alike(got) -> float:
    """How alike a line and the syllables offered for it have to be.

    One question with two answers, because the two ways a line can be offered
    syllables at all are not equally good evidence; see RECUT_LIKE.
    """
    return RECUT_LIKE if (got or {}).get("_recut") else RELAY_LIKE


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
    apart = _filed_apart({"Content": donor})
    theirs, owner = [], []
    for i, y in enumerate(syls):
        k = _key(y.get("Text") or "")
        theirs.append(k)
        owner.extend([i] * len(k))
    ours, lineof = [], []
    for i, it in enumerate(base):
        k = _key(_unaside(SL.line_text(it), apart))
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
        out.append({"Text": SL.syllables_text(take), "_recut": True,
                    "StartTime": float(take[0]["StartTime"]), "EndTime": end,
                    "Lead": {"Syllables": take,
                             "StartTime": float(take[0]["StartTime"]),
                             "EndTime": end}})
    return out if any(o for o in out) else None


def _in_step(out: list, based: list) -> None:
    """Lines that borrowed the wrong repeat of themselves, given back.

    A donor cannot tell one repeat of a line from another, and a chorus or an
    outro is the same words several times over. _timely settles that where the
    line-by-line pairing made it -- a pair sitting a bar off its neighbours'
    offset is dropped -- but a start can also arrive by the re-stream or from
    the second donor, and both are added to the map AFTER _timely has run. So
    the wrong repeat still gets through, by the back door.

    NF's "Change" is the case: its outro is four lines said twice, and the
    Apple+NetEase+Kugou blend came out running 200.8, 210.8, 212.6, 207.0,
    208.9, 211.1, 212.7 -- two lines carrying the second repeat's timing while
    sitting in the first repeat's place, and the rest of the outro playing
    catch-up behind them.

    Out of sequence is the first half of the test and cannot be all of it: a
    line both donors independently place late is out of sequence too, and
    there it is the donors' reading of the song rather than a mistake -- see
    the "no steadier" case in test_blends. What separates the two is that a
    wrong repeat is a repeat. So a line is only given back when the song says
    the same words somewhere else AND this line has landed on top of that
    other one's timing, which is what borrowing the wrong repeat looks like
    from the outside and what a genuinely late line never looks like.

    Which lines are out of sequence is not a question the neighbours can
    answer one pair at a time: read that way the run above accuses 212.6 and
    207.0 alike, and 207.0 is the one telling the truth. The longest run of
    starts that DO ascend is the answer -- the largest set of lines that can
    all be right together -- and a line outside it is handed back to the
    base's own stamp. Handed back whole: a start that landed on the wrong
    repeat was carrying that repeat's syllables, so the words go with it.

    Nothing is done where the base has no stamp of its own to return to, or
    where its stamps are the ones out of order: Pixel Terror's "Enigma" is
    written that way in the Apple document, and there the sequence is not
    evidence about anything.
    """
    at = [SL.line_start(i) for i in out]
    if len(out) != len(based) or sum(
            isinstance(v, (int, float)) for v in at) < 4:
        return
    was = [b[0] for b in based]
    if any(isinstance(x, (int, float)) and isinstance(y, (int, float)) and x > y
           for x, y in zip(was, was[1:])):
        return
    tails, back = [], [len(out)] * len(out)
    for i, v in enumerate(at):
        if not isinstance(v, (int, float)):
            continue
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if at[tails[mid]] <= v:
                lo = mid + 1
            else:
                hi = mid
        back[i] = tails[lo - 1] if lo else len(out)
        if lo == len(tails):
            tails.append(i)
        else:
            tails[lo] = i
    kept, i = set(), tails[-1] if tails else len(out)
    while i < len(out):
        kept.add(i)
        i = back[i]
    said = {}
    for i, it in enumerate(out):
        if i in kept and isinstance(at[i], (int, float)):
            said.setdefault(_key(SL.line_text(it)), []).append(at[i])
    for i, (start, end) in enumerate(based):
        if i in kept or not isinstance(at[i], (int, float)):
            continue
        if not isinstance(start, (int, float)):
            continue
        twin = said.get(_key(SL.line_text(out[i])) or "\0") or []
        if not any(abs(v - at[i]) <= BLEND_FAR for v in twin):
            continue
        line = {k: v for k, v in out[i].items()
                if k not in ("Lead", "Background", "StartTime", "EndTime")}
        line["StartTime"] = start
        if isinstance(end, (int, float)):
            line["EndTime"] = end
        out[i] = line


BLEND_LONG = 1.6


def _fits(syls: list, at, nxt) -> bool:
    """Whether a borrowed rhythm is the right length for the room it is
    going into. See BLEND_LONG."""
    if not syls or not isinstance(at, (int, float)) \
            or not isinstance(nxt, (int, float)) or nxt <= at:
        return True
    first, last = syls[0].get("StartTime"), syls[-1].get("EndTime")
    if not isinstance(first, (int, float)) or not isinstance(last, (int, float)):
        return True
    return (last - first) <= (nxt - at) * BLEND_LONG


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


BLEND_STEADY = 0.5
BLEND_PATCHY = 0.34
BLEND_BETTER = 0.2


BLEND_LEAD = 0.05
BLEND_WOBBLE = 0.05


BLEND_PICK = 0.015


def _wander(bit: list, dit: list, dmap: dict) -> float | None:
    """How much this donor's clock WANDERS against the base's line sync.

    Each paired line's offset from the base, then the median distance of
    those from their own median -- so the constant difference between two
    clocks is taken out and only the inconsistency is left. None where too
    little of the song is paired to say anything.

    Off the PAIRING, before the re-stream and the filler have added to the
    map. That matters: those add lines this donor could not place on its own,
    and their offsets are the other donor's or a cut of our own making, so
    counting them measures something that is no longer one donor's clock.
    Measured both ways against the hand-timed files here -- the pairing alone
    picks the truly better donor 7 times out of 7, the finished map 6.
    """
    off = _offsets(bit, dit, dmap)
    if len(off) < 6:
        return None
    mid = off[len(off) // 2]
    apart = sorted(abs(v - mid) for v in off)
    return apart[len(apart) // 2]


def _offsets(bit: list, dit: list, dmap: dict) -> list:
    """Every paired line's distance from where the base puts it, in order."""
    off = []
    for i, j in (dmap or {}).items():
        if not 0 <= j < len(dit):
            continue
        a, b = SL.line_start(bit[i]), SL.line_start(dit[j])
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            off.append(b - a)
    off.sort()
    return off


def _clock(bit: list, doc) -> tuple:
    """Where this donor's clock sits against the base's line sync.

    (shift, wander): how far the whole document is out, and how much it
    wanders about that. `_wander` is the second of those on its own, off the
    pairing alone, which is the right question when what is being weighed is
    two donors' steadiness. This is the other one, and it needs the whole
    song: a donor's copy of a recording can be shifted bodily -- a different
    master, a different cut, an intro the other pressing does not have -- and
    a shift is invisible to every test the blend already runs. Each line
    agrees with its neighbours, `_timely` passes them all, `_astray` finds
    nothing, and the finished document plays a second early from start to
    finish.

    Over the songs measured here that failure is not rare and it is not
    small: NetEase hands back Cartoon's "Why We Lose" 21.9 seconds out,
    J. Cole's "MIDDLE CHILD" 1.8 seconds early and Linkin Park's "Faint" 1.7
    late, and QQ Music has all three within a tenth. The base's line sync is
    the only witness to it, because it is the one document known to be timed
    against the recording actually playing.

    Read off the pairing AND the donor's own stream re-cut, unlike `_wander`:
    a re-streamed line is still this donor's syllables at this donor's times,
    which is all a shift is asking about, and on a third of the songs here
    the two sides break their lines differently enough that the pairing alone
    says nothing at all.
    """
    d = _stamped(doc)
    it = _items(SL.payload(d)) if d else []
    if not bit or not it:
        return None, None
    dmap = dict(_timely(dict(_pair(bit, it) or {}), bit, it) or {})
    if len(dmap) < len(bit):
        for i, got in enumerate(_restream(bit, it) or []):
            if got and i not in dmap:
                it = list(it) + [got]
                dmap[i] = len(it) - 1
    off = _offsets(bit, it, dmap)
    if len(off) < 6:
        return None, None
    mid = off[len(off) // 2]
    apart = sorted(abs(v - mid) for v in off)
    return mid, apart[len(apart) // 2]


def in_order(base, first: tuple, second: tuple) -> tuple:
    """The blend's two donors, the one holding THIS recording first.

    Each donor is (document, what to call it, which source it is). A
    three-way blend takes its words from the first and asks the second only
    about the lines the first could not place, so which of them leads is the
    single biggest thing about the document that comes out -- and it used to
    be settled once, in the source order, for every song alike. NetEase is
    the steadier of the two in general, which is why it leads by default and
    still does wherever there is nothing to choose between them. It is not
    the steadier one on every song, and on the songs where it is not, a fixed
    order is simply wrong -- gc's ear on Lil Tecca's "Amigo" said QQ Music
    long before any of this could say why.

    What decides is `_clock`'s shift: how far the donor's whole document sits
    from the base's line sync. Not the wander -- the blends already weigh
    that, line by line and blend against blend -- but the constant nothing
    else looks at. Whichever document _blended settled on is the witness,
    because it is the one that was timed against a recording rather than
    matched to one by its text; where that is LRCLIB rather than Apple it is
    a poorer witness, and it is still the only one there is.

    Measured through eval_blends over 354 songs with a community word sync to
    score against, the rule off and then on, same jar and same run. It moves
    32 of the 354 and leaves the rest exactly where they were; of those 32 it
    helps 15, hurts 6 and comes out level on the remaining 11. Words more
    than half a second out of step with their own song go from 1.10% to 0.97%
    of the song at the median and 4.68% to 4.21% on average, and the mean
    scatter across the set falls from 0.258s to 0.163s.

    Those are small numbers for what is behind them, because the songs it
    catches are not slightly wrong. Cartoon's "Why We Lose" goes from 81.2%
    of its words out to 0.8%, J. Cole's "MIDDLE CHILD" from 62.0% to 1.2%,
    Linkin Park's "Faint" from 8.5% to none: three songs where NetEase was
    holding another pressing and the blend was a second or twenty out for its
    whole length. The six it hurts are all of the other kind -- BBpanzu's
    "Bang Bang Bang" is the worst at 0% to 12.6% -- and they are the limit of
    what a line sync can witness: it can say which donor's clock is on this
    recording, and nothing at all about whether the words underneath are
    placed well once it is.

    The margin cannot be picked off that set, which is worth saying plainly:
    0.05, 0.065 and 0.08 all land within a thousandth of each other over the
    354 (4.21%, 4.23%, 4.22% of words out), the tighter one simply moving
    more songs in both directions. So the call is made by the one song
    somebody actually listened to -- "Amigo", NetEase 0.093 against QQ's
    0.023 -- and 0.05 is the loosest setting that gets it right. Two clocks
    over one recording disagree by a few hundredths for honest reasons, and
    that is about as fine as a real call gets.

    The wobble guard does earn its keep: without it the same margin moves 30
    songs instead of 32 and gets 10 of them wrong instead of 6. A donor
    nearer the line sync overall but visibly less steady about sitting there
    has not earned the song.
    """
    if not second[0] or not first[0]:
        return first, second
    bit = _items(SL.payload(_stamped(base) or {}))
    mine = _clock(bit, first[0])
    if mine[0] is None or abs(mine[0]) <= BLEND_LEAD:
        return first, second
    theirs = _clock(bit, second[0])
    if theirs[0] is None or abs(theirs[0]) >= abs(mine[0]) - BLEND_LEAD:
        return first, second
    if theirs[1] > mine[1] + BLEND_WOBBLE:
        return first, second
    return second, first


def _drift(bit: list, dit: list, dmap: dict) -> dict:
    """How far each line sits from where the lines around it put this donor.

    Two clocks over one recording differ by an offset that drifts, so "off"
    is never a distance -- it is a distance compared with the lines either
    side. _timely asks exactly this of the pairing and then throws the number
    away, keeping only the verdict; this asks it of the FINISHED map, which
    the re-stream and the filler have both added to since, and hands the
    number back, because the caller wants to know how far off and not only
    whether.
    """
    off = {}
    for i, j in (dmap or {}).items():
        if not 0 <= j < len(dit):
            continue
        s, d = SL.line_start(bit[i]), SL.line_start(dit[j])
        if isinstance(s, (int, float)) and isinstance(d, (int, float)):
            off[i] = d - s
    keys = sorted(off)
    out = {}
    for pos, i in enumerate(keys):
        near = sorted(off[k] for k in keys[max(0, pos - 3):pos + 4] if k != i)
        if near:
            out[i] = off[i] - near[len(near) // 2]
    return out


def _guessed(text: str, group) -> float | None:
    """The share of a line's words that would fill on an onset nobody measured.

    A donor that times three words of a nine-word line relays those three and
    hangs everything after them off the last one; _unlump then shares that
    single stamp out among the six words left over, and they go past in a
    rush somewhere the singing has already left. On screen it reads as the
    line coming apart partway through -- the fill tracks the voice, and then
    stops meaning anything -- which is a different failure from a line landing
    in the wrong place, and invisible to any test that only looks at where the
    line begins.

    None where the donor has nothing to lay under this line at all: that is a
    hole, and holes are already the second donor's business.
    """
    syls = (group or {}).get("Syllables") or []
    got = _relay(text, syls) if syls else None
    if not got:
        return None
    return sum(1 for y in got if y.get("Guess")) / len(got)


def _astray(bit: list, qit: list, qmap: dict, apart: set = frozenset()) -> dict:
    """The lines the first donor timed, and timed wrong. i -> (drift, guessed).

    A donor answers for a song, not for a line, and it can be right about the
    song and wrong about one line of it -- matched to the wrong repeat of a
    chorus, or carrying only half the words the base writes. Until now the
    second donor was only ever asked about the lines the first could not place
    AT ALL, so a line placed badly kept its bad placement while a source
    holding the right one sat unused three lines away.

    Two ways of being wrong, because they show up differently and neither test
    sees the other:

      * the line sits somewhere its own neighbours say it does not -- over
        BLEND_JUMP from where the same donor's surrounding lines put it. The
        same tolerance _timely uses, and for once that is measured rather than
        borrowed: 0.75 and 1.0 came back level over the songs here and 1.5 and
        2.0 came back worse, so there is nothing for a second number to say;
      * the donor times only part of it, over BLEND_PATCHY of the line filling
        on an onset it never measured.

    Nearly everything the first test catches came in through the re-stream,
    and that is not a coincidence: _timely already throws out a PAIRING that
    disagrees with its neighbours by this much, and the re-stream then fills
    the hole it left from the same donor's syllable stream, unasked and
    unchecked. On the songs here that is where the misplaced lines are --
    Chasing Clouds, Gold and The Mystic pair nothing at all and come through
    the stream whole.

    Whether the second donor is any better is _steadier's question, not this
    one's. Lines the first donor cannot place at all are left out: those are
    holes, and the caller asks about them separately -- on the same terms,
    since a hole is only a line nobody has answered for yet.

    `apart` is the ad-libs the donors file beside their lines rather than
    inside them, so the second test reads our line the way _peel_bracket is
    about to write it. Without it a line whose bracket the donor keeps
    somewhere else scores as barely timed and is handed over on the strength
    of words nothing was ever going to relay. See _unaside.
    """
    if not qmap:
        return {}
    drift = _drift(bit, qit, qmap)
    out = {}
    for i, j in qmap.items():
        if not 0 <= j < len(qit):
            continue
        got = _guessed(_unaside(SL.line_text(bit[i]), apart),
                       (qit[j] or {}).get("Lead"))
        if got is None:
            continue
        was = drift.get(i)
        if (was is not None and abs(was) > BLEND_JUMP) or got > BLEND_PATCHY:
            out[i] = (was, got)
    return out


def _steadier(mine: tuple, theirs: tuple) -> bool:
    """Whether the second donor's answer for one line beats the first's.

    Conservative on purpose. The second donor has to be placing the line
    itself -- agreeing with its own neighbours to within BLEND_STEADY -- before
    anything it says is worth hearing, which is what stops a bad line being
    swapped for a differently bad one. Past that the failure decides: a line
    the first donor put in the wrong place is simply handed over, since the
    second one demonstrably has it in the right place, while a line the first
    donor only half timed is handed over only where the second really does
    time more of it.
    """
    drift, guessed = mine
    other, patch = theirs
    if other is None or abs(other) > BLEND_STEADY:
        return False
    if drift is not None and abs(drift) > BLEND_JUMP:
        return True
    return (patch is not None and guessed > BLEND_PATCHY
            and patch <= guessed - BLEND_BETTER)


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


BASE_WORDS = {"apple": "Apple Music", "bini": "Apple Music",
              "amll": "amll-ttml-db", "unison": "Unison",
              "kugou": "Kugou",
              "netease": "NetEase", "lrclib": "LRCLIB", "local": "this machine"}


def _blended(tid: str, meta: dict, local, timing, whose: str, alone: str,
             above=None, spare=None, spare_name: str = "",
             spare_alone: str = "") -> dict | None:
    """Apple Music's lines with somebody else's word timing under them.

    Two documents, not three. NetEase used to vote here on where each line
    begins, and it was a bad third opinion: it is the source least likely to
    be holding the same master, so its vote pulled line starts around on
    songs the other two already agreed about.

    Asked one upstream at a time and reconciled here rather than taking
    whichever answered first, and independent of those upstreams' own on/off
    switches: this is a source in its own right, not a mode of the others.

    The lines do not have to be Apple's. `above` holds what the sources ranked
    ABOVE this blend came back with -- BiniLyrics' TTML, amll's, Unison's --
    already fetched, because those sources are providers in their own
    right and were asked in the round before this one. Any of them can be the
    base, and a source the user put higher wins a tie against one they did
    not. Only quality outranks that: nothing here will lay word timing under
    line-level lines while word-level lines are on the table.

    `local` is whatever the caller already holds -- in practice Spicy Lyrics'
    own document, which is usually Apple Music too and usually the better copy
    of it. It is offered alongside them: ignoring what was already on the
    machine meant blending against a weaker copy of the same Apple document,
    and, where the round before had found nothing, falling all the way to
    LRCLIB while a perfectly good Apple sync sat unused. It matters more for
    the Chinese catalogue than it looks, where the round before often has
    nothing and the lines can only come from here.

    There is no ask of its own left. This used to knock on LyricsPlus' Apple
    endpoint for a base whenever nothing in hand was word-level -- ten seconds
    of the walk, for a scrape of the catalogue BiniLyrics answers for in a
    tenth of one, in the round after BiniLyrics has already been asked and its
    answer handed here in `above`. Everything this blend
    can build on has been fetched by the time it runs, which is what the
    second round is for.
    """
    got = _parallel({
        "timed": lambda: timing(tid, meta),
        **({"spare": lambda: spare(tid, meta)} if spare is not None else {}),
    })
    local = SL.payload(local) if local else None
    picks = [(local, _words_from(local), "spicy")]
    for name, doc in (above or {}).items():
        picks.append((SL.payload(doc), BASE_WORDS.get(name, name), name))
    picks = [(d, w, o) for d, w, o in picks if d and quality(d) != "none"]
    picks.sort(key=lambda p: RANK.get(quality(p[0]), 0), reverse=True)
    if not picks:
        lr = from_lrclib(tid, meta)
        picks = [(lr, "LRCLIB", "lrclib")] if lr else []
    if not picks:
        return None
    base, words, origin = picks[0]
    lead, fill = in_order(base, (got["timed"], whose, alone),
                          (got.get("spare"), spare_name, spare_alone))
    out = _blend(base, words, lead[0], None, origin, lead[1], fill[0], fill[1])
    return stand_down(out, lead[0], base, lead[2])


def stand_down(out, donor, base, alone: str):
    """The blend, or the donor's own document where the blend was not worth it.

    Split out of _blended so a measurement can build a blend from documents
    already on disk and still be measuring what the chain would really hand
    over. eval_blends.py rebuilds every blend over a fixed jar of donors, and
    a copy of this rule kept beside it would drift away from this one.
    """
    rank = lambda d: RANK.get(quality(d), 0) if d else 0        # noqa: E731
    if donor and rank(donor) > rank(out):
        out = dict(_reworded(donor, base))
        out["_alone"] = alone
    elif donor and (_thinner(out, donor) or _shorter(out, donor)):
        out = dict(_reworded(donor, base))
        out["_alone"] = alone
    return out


BLEND_SHORT = 0.85
BLEND_SAME_WORDS = 0.85


def _reworded(donor, base):
    """The donor's document, written the way the base writes it.

    Standing a blend down to the donor gets the song back whole, and throws
    away the thing the base was chosen for: its wording. Apple writes "You've
    gotten me under your spell" and an apostrophe where QQ Music writes
    "You've got me under your spell"; the reader picked Apple Music, and on
    the two thirds of the song Apple has there is no reason they should stop
    seeing it.

    So the donor keeps its lines, its coverage and its clock -- everything
    the stand-down was for -- and every line the base also has is re-lettered
    from the base, cut along the donor's own syllables. That is exactly what
    _relay does inside a blend; this is the same trade, made line by line
    over a document the blend gave up on.

    A line the base does not have keeps the donor's words, because there is
    nothing else to write it with. A line whose letters will not re-cut is
    left alone rather than half-done.
    """
    dit, bit = _items(SL.payload(donor)), _items(SL.payload(base or {}))
    if not dit or not bit:
        return donor
    a = [_key(SL.line_text(i)) for i in dit]
    b = [_key(SL.line_text(i)) for i in bit]
    from difflib import SequenceMatcher

    sm = SequenceMatcher(None, a, b, autojunk=False)
    mate = {i + k: j + k
            for i, j, n in sm.get_matching_blocks() for k in range(n) if a[i + k]}
    mate.update(_near_pairs(a, b, mate))
    out, said = [], 0
    for i, it in enumerate(dit):
        lead = it.get("Lead") if isinstance(it.get("Lead"), dict) else None
        syls = (lead or {}).get("Syllables") or []
        text = SL.line_text(bit[mate[i]]) if i in mate else ""
        got = _relay(text, syls) if (text and syls) else None
        if not got:
            out.append(it)
            continue
        said += 1
        out.append({**it, "Text": text, "Lead": {**lead, "Syllables": got}})
    if not said:
        return donor
    doc = SL.payload(donor)
    key = "Content" if isinstance(doc.get("Content"), list) else "Lines"
    return {**doc, key: out}


def _said(doc) -> str:
    """Every letter a document actually sings, punctuation and spacing gone."""
    return "".join(_key(SL.line_text(i)) for i in _items(SL.payload(doc or {})))


def _short_of(a: str, b: str) -> bool:
    """_shorter, once the two documents are down to their letters.

    Split out for one reason: this is the part that costs, and it needs
    nothing but two strings, so it is the part that can be done in another
    process. Measured over a cold walk it was 2046ms across twelve calls, the
    worst of them 389ms on 3216 letters against 3293 -- and every millisecond
    of it held the GIL away from the thread drawing the words. See offload.

    Not made cheaper, moved. What difflib matches here is what it matched
    before, to the opcode.
    """
    from difflib import SequenceMatcher

    if not a or not b or len(a) >= len(b):
        return False
    ops = SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    shared = sum(i2 - i1 for tag, i1, i2, _j1, _j2 in ops if tag == "equal")
    if shared < BLEND_SAME_WORDS * len(a):
        return False
    absent = max((j2 - j1 for tag, _i1, _i2, j1, j2 in ops if tag != "equal"),
                 default=0)
    return absent > (1 - BLEND_SHORT) * len(b)


def _shorter(blend, donor) -> bool:
    """Whether the blend's words are missing a real part of the song.

    Two questions, and both have to answer yes. Is this the same lyric --
    nearly all of the blend's letters inside the donor's -- and is there one
    unbroken stretch of the donor the blend has not got, big enough to be a
    section of the song rather than a spelling difference. See BLEND_SHORT.
    """
    return offload.call(_short_of, _said(blend), _said(donor))


BLEND_THIN = 0.35


def _thinner(blend, donor) -> bool:
    """Whether the blend leaves a materially larger share of lines untimed."""
    def share(doc):
        items = _items(SL.payload(doc or {}))
        if not items:
            return 0.0
        timed = sum(1 for i in items
                    if ((i.get("Lead") or {}).get("Syllables") or []))
        return timed / len(items)
    return share(donor) - share(blend) >= BLEND_THIN


def from_blend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """Apple Music's lines with QQ Music's word timing."""
    return _blended(tid, meta, local, from_qq, "QQ Music", "qq", above)


def from_kublend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """The same, with Kugou underneath instead.

    Kugou and QQ are very largely the same word-timed data -- on eight CJK
    tracks measured here, six agreed syllable for syllable to within seventy
    milliseconds -- so this is not a second opinion so much as a second way
    in. It matters because the doors fail separately: Kugou answered for ten
    of those ten tracks where QQ answered for eight.
    """
    return _blended(tid, meta, local, from_kugou, "Kugou", "kugou", above)


def from_neblend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """The same, with NetEase's word timings under Apple's lines.

    A different pairing from the old three-way blend, which is worth saying
    because that one was bad: there NetEase was a third opinion voting on
    where each LINE begins, against two sources more likely to be holding
    the same master, and it pulled line starts around. Here it is doing the
    thing it is actually good at -- saying where each word lands inside a
    line somebody else has already placed.

    Worth its own slot because QQ and NetEase, unlike QQ and Kugou, are not
    the same data: on NF's "If You Want Love" they agree on where a line
    starts to within 0.19s everywhere, and on where the WORDS fall only 30%
    of the time within 50ms, one of them by as much as 0.81s.
    """
    return _blended(tid, meta, local, from_netease, "NetEase", "netease", above)


def from_triblend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """Apple's lines, NetEase's words, and QQ for the lines NetEase misses.

    The three-way blend that was here before asked all three sources about
    every line and let them vote, and it was bad at it -- NetEase is the one
    least likely to be holding the same master, so its vote dragged line
    starts around on songs the other two agreed about. This is the other way
    round: one donor times the words, and the second is asked only about the
    lines the first could not place -- either because it had nothing for them
    or because what it had landed somewhere the line sync says the line is
    not. Nothing is voted on and nothing is averaged; the question put to the
    second donor is the same one, line by line, and its answer is taken whole
    or not at all. See _astray.

    NetEase goes first because it is the steadier of the two where both have
    the song -- measured against a hand-timed reference, its words wobble
    0.079s against QQ's 0.099s -- and QQ covers more songs, which is exactly
    what a filler is for.

    Goes first, not always first. Steadier in general is not steadier on this
    song, and where NetEase's whole clock sits further from the base's line
    sync than QQ's does, QQ times the words and NetEase fills the gaps. See
    in_order.
    """
    return _blended(tid, meta, local, from_netease, "NetEase", "netease",
                    above, from_qq, "QQ Music", "qq")


def from_kutriblend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """The same three-way again, with Kugou filling the lines NetEase misses.

    Kugou and QQ are not a second opinion. They are the same data: over the
    22 songs in this cache that both answer for, their word onsets agree on
    100% of words to within 70ms, with a median offset and a median scatter
    of 0.000s each -- they are writing the same numbers. (from_kublend says
    the same from a smaller sample; eval_sources.py --donors is what measured
    this one.)

    So this is a second DOOR, and that is the whole of what it is for: the two
    fail separately. Measured against triblend over 30 songs, the two came
    back as the same document wherever both answered -- identical scatter on
    17 of the 23 they both scored, and never more than 9ms apart on the rest
    -- and the entire difference between them was three songs where QQ's door
    returned nothing at all and Kugou's returned 150 timed lines. Never the
    other way round.

    Neither fills BETTER, because there is nothing to choose between the
    numbers they write. This one just answers more often.

    Which of the two leads is still decided per song, as in from_triblend:
    being the same document as QQ, Kugou is the same second opinion about
    which pressing NetEase is holding.
    """
    return _blended(tid, meta, local, from_netease, "NetEase", "netease",
                    above, from_kugou, "Kugou", "kugou")


from_blend.wants_above = True
from_kublend.wants_above = True
from_neblend.wants_above = True
from_triblend.wants_above = True
from_kutriblend.wants_above = True


ASIDE_TRIM = " \t,;:.-—–~(（[【"
OPENERS, CLOSERS = "(（[【", ")）]】"


def _unclosed(text: str) -> str:
    """The line without a bracket the lifted piece left hanging open.

    QQ writes 'Woo' where Apple writes '(Woo, woo)', so peeling the ad-lib
    off the tail can cut inside the brackets and leave the line reading
    "I ain't playin' nice (Woo".
    """
    depth, at = 0, None
    for i, c in enumerate(text or ""):
        if c in OPENERS:
            if not depth:
                at = i
            depth += 1
        elif c in CLOSERS and depth:
            depth -= 1
    return text[:at].rstrip(ASIDE_TRIM) if depth and at is not None else text


def _peel_aside(new: dict, q: dict, qit: list, start, end):
    """Lift a trailing ad-lib out of a line the donor times without it.

    Apple writes one line where the donor writes two:

        Chillin' in the back like, "Hey" (Oh, God)
        No nominations, but it's cool though, oh, God

    and QQ times 'Chillin' in the back like "Hey"' then 'Oh God', and
    'No nominations but it's cool though' then 'Oh God'. Relaying one onto
    the other leaves everything past the donor's last word stuck to a single
    syllable, so the tail fills in one lump while the donor's timing for it
    sits unused in the next line down.

    The brackets are not the signal and never were -- the second line has
    none. What says so is that the donor's line for this line is a PREFIX of
    it: the donor split where we did not. Two conditions, both required:

      * everything the donor's paired line says is the start of what ours
        says, and there is something left over;
      * some other line of the donor's says exactly the leftover, near
        enough in time to be this line's.

    Returns the backing group with the donor line it came from, and shortens
    the line's own text; or None, which is the answer whenever either
    condition is in doubt.
    """
    text = new.get("Text") or ""
    ours, theirs = _key(text), _key(SL.line_text(q))
    if not theirs or not ours.startswith(theirs) or len(ours) <= len(theirs):
        return None
    want = ours[len(theirs):]
    idx = [i for i, c in enumerate(text) if c.isalnum()]
    if len(idx) != len(ours) or len(theirs) >= len(idx):
        return None
    cut = idx[len(theirs)]
    core = _unclosed(text[:cut].rstrip(ASIDE_TRIM))
    if not core:
        return None
    lo = start if isinstance(start, (int, float)) else None
    hi = (end if isinstance(end, (int, float)) else lo)
    for j, other in enumerate(qit):
        if other is q or _key(SL.line_text(other)) != want:
            continue
        syls = (other.get("Lead") or {}).get("Syllables") or []
        s2, e2 = SL.line_start(other), _line_end(other)
        if not syls or not isinstance(s2, (int, float)):
            continue
        if lo is not None and not (lo - ASIDE_REACH <= s2 <= (hi or lo) + ASIDE_REACH):
            continue
        new["Text"] = core
        return {"Syllables": syls, "StartTime": s2,
                "EndTime": e2 if isinstance(e2, (int, float)) else s2}, j
    return None


STRAY_REACH = 0.6


def _asides_in(text: str) -> list:
    """The bracketed pieces of a line, so an ad-lib already written into the
    lyric is not written a second time beside it."""
    return [m for m in re.findall(r"[(\[（【]([^)\]）】]*)[)\]）】]", text or "")
            if _key(m)]


def _kin(one: str, two: str) -> bool:
    """Whether two shouts are the same shout, however many times it is
    written down: "yes" against "yesyes", "woo" against "woowoo".

    Containment alone is not enough for anything but a line already known to
    be an ad-lib -- "you know" is inside "Heard the catalog, you know I got
    some scars on me" -- so what is left of the longer one once the shorter
    is taken out of it has to be next to nothing.
    """
    if not one or not two:
        return False
    small, big = (one, two) if len(one) <= len(two) else (two, one)
    return small in big and len(big.replace(small, "")) <= 0.2 * len(big)


def _spoken_for(text: str, line: dict) -> bool:
    """Whether the line already writes this ad-lib into its own text.

    Two shouts at the same moment are one shout, whichever way each side
    happened to spell it -- Apple's "(Ooh)" against QQ's "Woo". Writing both
    puts the same voice on the screen twice.
    """
    key = _key(text)
    return any(_kin(key, _key(a)) or (_a_cry(a) and _a_cry(text))
               for a in _asides_in(line.get("Text") or ""))


def _echoes(key: str, j: int, line: dict, said: list) -> bool:
    """Whether the donor has these words elsewhere over the same seconds."""
    lo, hi = line.get("StartTime"), line.get("EndTime")
    if not isinstance(lo, (int, float)):
        return False
    hi = hi if isinstance(hi, (int, float)) else lo
    return any(k and key in k and i != j and s <= hi and e >= lo
               for i, s, e, k in said)


DOUBLE_SLACK = 0.15


def _spans_of(line: dict) -> list:
    """Every voice one finished line draws, as (words, start, end)."""
    out = []
    lead, at, done = line.get("Lead"), SL.line_start(line), _line_end(line)
    if isinstance(lead, dict) and (lead.get("Syllables") or []) \
            and isinstance(at, (int, float)):
        out.append((_key(SL.line_text(line)), at,
                    done if isinstance(done, (int, float)) else at))
    for g in (line.get("Background") or []):
        syls = (g or {}).get("Syllables") or []
        s, e = _group_span(g, syls)
        if syls and isinstance(s, (int, float)):
            out.append((_key(SL.syllables_text(syls)), s,
                        e if isinstance(e, (int, float)) else s))
    return out


def _doubled(out: list, key: str, at: float, until: float) -> bool:
    """Whether the document already sings these words across these seconds.

    An ad-lib is a SECOND voice. Where the words are on the screen already --
    as a line's own lyric, or as an ad-lib another donor has lent it -- adding
    them again does not add a voice, it draws the one that is there twice.

    The hand-timed files here are what settles it. Apple writes "It never goes
    away" over Linkin Park's own "Never goes away" and Dua Lipa's "Ooooh break
    my heart" over "Ooh, break my heart"; the hand-timed Figure.09 and Break
    My Heart write each of those once, as plain consecutive lines. What they
    do keep is a background whose words are NOT the line's -- "Get away from
    me" under "It never goes away" -- which is why this asks about the words
    and the seconds together rather than about either alone.
    """
    for line in out:
        for k, s, e in _spans_of(line):
            if not k or not (_kin(key, k) or key in k):
                continue
            if min(until, e) - max(at, s) > -DOUBLE_SLACK:
                return True
    return False


def _place_dark(out: list, qit: list, spoken: set) -> None:
    """A line nobody could match by its letters, given the stamp of the donor
    line left standing where it belongs.

    A donor that mishears a line writes a different line. On slayr's
    "Eyesight" Apple has "In your life (In your life)" where NetEase and QQ
    Music both heard "And you'll learn (And you'll learn)" -- the same second
    and a half of the same recording, 0.52 alike by their letters, so the
    pairing, _near_pairs at 0.75 and _restream's cut all walk past it. Apple's
    document for that song is words only, so the line was left with a stamp
    from nobody at all and came out of the blend as bare text: on the screen
    for the whole song, lit up never, twice.

    Only for a line with no time at all. One that has its own loses nothing by
    going unpaired, and this leaves those alone.

    So it asks the one question the letters cannot: our line has a lit line
    either side of it, and exactly one line of the donor's is still standing
    free in the hole between them -- then they are the same line, whatever
    either side heard. One line and no choice to make is the whole of the
    test; two, and it declines, because picking between them is the guessing
    this is here to avoid. Shouting is not a candidate: an ad-lib in the hole
    is an ad-lib, and _lift_strays is what that is for.

    Only the timing is taken, which is what a donor is for in a blend. The
    words stay the base's -- the donor misheard this line, and that is the
    reason it is here at all.
    """
    lit = [i for i, ln in enumerate(out)
           if isinstance(ln.get("StartTime"), (int, float))]
    if len(lit) < 2:
        return
    free = []
    for q in qit:
        at, done = SL.line_start(q), _line_end(q)
        text = SL.line_text(q) or ""
        if isinstance(at, (int, float)) and _key(text) and not _a_cry(text):
            free.append((q, at, done if isinstance(done, (int, float)) else at))
    if not free:
        return
    for a, b in zip(lit, lit[1:]):
        if b - a != 2:
            continue
        lo, hi = _line_end(out[a]), out[b]["StartTime"]
        if not isinstance(lo, (int, float)) or lo >= hi:
            continue
        said = [(q, at, done) for q, at, done in free
                if id(q) not in spoken and lo - STRAY_REACH <= at < hi]
        if len(said) != 1:
            continue
        q, at, done = said[0]
        ln = out[a + 1]
        if _spoken_for(SL.line_text(q), ln):
            continue
        start = max(at, lo)
        ln["StartTime"] = start
        ln["EndTime"] = max(min(done, hi), start + 0.05)
        spoken.add(id(q))


def _lift_strays(out: list, qit: list, spoken: set, slid: dict) -> None:
    """The donor's ad-libs that our lines have no place for, lifted onto them.

    QQ Music and Kugou file an ad-lib as a line of its own far more often than
    Apple does, and where Apple has not written it at all there is nothing for
    the line-by-line pairing to attach it to -- so it was dropped, timing and
    all. NF's SUFFICE is the plain case: through the first chorus QQ times
    "Yes", "No", "Woo", "Ayy", "Want a slice" as their own lines and Apple
    writes none of them, while in the LATER chorus Apple writes the same
    ad-libs inline and they come through as backgrounds. The same voice, in
    the same song, appearing only when Apple happened to type it.

    Only two kinds are lifted, because the cost of being wrong is a real
    lyric drawn as an afterthought:

      * the shouting -- every word of it in CRIES, the same test fold_cries
        uses on a document's own lines;
      * an echo -- words another of the donor's own lines is singing across
        this stretch of the song, which is what a backing vocal repeating
        the hook is.

    That second test asks the donor rather than the base on purpose. Where
    the base writes one line and the donor writes two, the donor's second
    line is the rest of the lyric, not an ad-lib: on the same song QQ times
    "Stop complainin', man, my head hurts" and then "These catchy records",
    and Apple writes them as one line. Read against the base's text those
    three words look like an echo of words the line already has -- the base
    does have them, further along. Read against the donor's own lines over
    the same seconds, nobody has sung them yet, and they are left where they
    are. The same test keeps "We ain't never spoke", "Uncertain" and "We're
    all hypocrites" out of the margin on this one song, all of them the
    second half of a line Apple wrote whole.

    Anything the base already writes in brackets is left alone: that one has
    a home in the lyric and, more often than not, _peel_aside has already
    given it its timing. Matched loosely, because the two rarely write the
    shout the same number of times -- Apple's "(Yes)" against QQ's "Yes yes".
    """
    starts = [(i, ln.get("StartTime")) for i, ln in enumerate(out)
              if isinstance(ln.get("StartTime"), (int, float))]
    if not starts:
        return
    said = []
    for j, q in enumerate(qit):
        s, e = SL.line_start(q), _line_end(q)
        if isinstance(s, (int, float)):
            said.append((j, s, e if isinstance(e, (int, float)) else s,
                         _key(SL.line_text(q))))
    for j, q in enumerate(qit):
        if id(q) in spoken:
            continue
        text = SL.line_text(q) or ""
        key = _key(text)
        syls = (q.get("Lead") or {}).get("Syllables") or []
        begin = SL.line_start(q)
        if not key or not syls or not isinstance(begin, (int, float)):
            continue
        if len([w for w in re.split(r"[^\w'’-]+", text) if w]) > CRY_WORDS:
            continue
        host = None
        for i, at in starts:
            if at <= begin:
                host = i
            else:
                break
        if host is None:
            continue
        ln = out[host]
        stop = ln.get("EndTime")
        if isinstance(stop, (int, float)) and begin > stop + STRAY_REACH:
            continue
        if _kin(key, _key(ln.get("Text") or "")):
            continue
        if not (_a_cry(text) or _echoes(key, j, ln, said)):
            continue
        if _spoken_for(text, ln) or (host + 1 < len(out)
                                     and _spoken_for(text, out[host + 1])):
            continue
        groups = ln.setdefault("Background", [])
        if any(_kin(key, _key(SL.line_text({"Lead": g}))) for g in groups
               if isinstance(g, dict)):
            continue
        end = _line_end(q)
        group = _slide({"Syllables": syls, "StartTime": begin,
                        "EndTime": end if isinstance(end, (int, float)) else begin},
                       slid.get(host, 0.0))
        if _doubled(out, key, group["StartTime"], group["EndTime"]):
            continue
        groups.append(group)
        groups.sort(key=lambda g: (g.get("StartTime")
                                   if isinstance(g.get("StartTime"), (int, float))
                                   else 0.0))
        if isinstance(ln.get("EndTime"), (int, float)):
            ln["EndTime"] = max(ln["EndTime"], group["EndTime"])


def _syls_of(part: dict) -> list:
    """The syllables of a line or of one of its backing groups."""
    lead = part.get("Lead")
    return ((lead.get("Syllables") if isinstance(lead, dict) else None)
            or part.get("Syllables") or [])


def _group_span(part: dict, syls: list):
    """(start, end) of a line or a backing group, from whatever it carries."""
    at = part.get("StartTime")
    if not isinstance(at, (int, float)):
        at = syls[0].get("StartTime") if syls else None
    done = part.get("EndTime")
    if not isinstance(done, (int, float)):
        done = syls[-1].get("EndTime") if syls else None
    return at, done if isinstance(done, (int, float)) else at


def _our_words(inner: str, syls: list) -> list:
    """The base's own words for an ad-lib, on the donor's clock.

    The two write the same shout differently often enough that the letters
    will not always line up -- "(Ooh)" against "Woo", "(Woo, woo)" against a
    single "Woo", "(Out of sight)" against "I'm out of sight out of sight".
    What is on the screen should still be what the lyric says, so the words
    are the base's in every case and only the timing is borrowed:

      * where the letters do line up, straight through _relay, which is one
        stamp per word;
      * where they line up against PART of the donor's line, the same, over
        the run of syllables that says it;
      * failing both, one stamp across the whole of it. unlump cuts that into
        words afterwards, and marks them as the guesses they are.
    """
    if not syls:
        return []
    said = _relay(inner, syls)
    if said:
        return said
    key = _key(inner)
    keys = [_key(y.get("Text") or "") for y in syls]
    for i in range(len(syls)):
        run = ""
        for j in range(i, len(syls)):
            run += keys[j]
            if run == key:
                said = _relay(inner, syls[i:j + 1])
                if said:
                    return said
            if len(run) >= len(key):
                break
    return [{"Text": inner.strip(), "StartTime": syls[0].get("StartTime"),
             "EndTime": syls[-1].get("EndTime")}]


BRACKETED = re.compile(r"\s*[(（\[【]([^)）\]】]{1,60})[)）\]】]")


def _peel_bracket(new: dict, pool: list, start, end, spoken: set) -> list:
    """Ad-libs the base writes into the line, given the timing a donor has.

    Apple marks a backing vocal by writing it in brackets inside the lead's
    own text -- "Yeah, if I did it, then I did it right (Yes)". Read as text
    it is sung by the lead voice, in the lead voice's place on the screen,
    and its words fill in whenever the last word of the line does. Somebody
    else usually knows better: QQ times that "Yes" as a line of its own, and
    with it the bracket can come out of the lyric and be what it is.

    _peel_aside does this from the other side -- OUR line runs past where the
    donor's stops -- and only where the donor's text matches the leftover
    exactly. Neither holds here. The line is identical to the donor's own,
    brackets and all, in the three-way where the lines come from NetEase; and
    the two sides rarely write a shout the same number of times, Apple's
    "(Woo, woo)" against QQ's "Woo". So this one takes the bracket as the
    signal, which for a document that uses brackets this way it is, and
    matches the shout loosely.

    The words that reach the screen are still the base's: the donor's
    syllables are cut points for what Apple wrote inside the brackets, which
    is what _relay is for. Anything the pool cannot time at about the right
    moment is left in the lyric exactly as it was.
    """
    text = new.get("Text") or ""
    if not text or "(" not in text and "（" not in text and "[" not in text \
            and "【" not in text:
        return []
    lo = start if isinstance(start, (int, float)) else None
    if lo is None:
        return []
    hi = end if isinstance(end, (int, float)) else lo
    got = []

    def take(m):
        inner = m.group(1)
        key = _key(inner)
        if not key:
            return m.group(0)
        best = None
        cry = _a_cry(inner)
        for item, s, e, k, syls in pool:
            if id(item) in spoken:
                continue
            said = SL.line_text({"Lead": item}) or ""
            if not (_kin(key, k) or (cry and _a_cry(said))):
                continue
            if not (lo - ASIDE_REACH <= s <= hi + ASIDE_REACH):
                continue
            near = (0 if _kin(key, k) else 1,
                    abs(len(k) - len(key)), abs(s - lo))
            if best is None or near < best[0]:
                best = (near, item, syls)
        if best is None:
            return m.group(0)
        item, syls = best[1], best[2]
        said = _our_words(inner, syls)
        got.append({"Syllables": said, "StartTime": said[0]["StartTime"],
                    "EndTime": said[-1]["EndTime"]})
        spoken.add(id(item))
        return ""

    left = re.sub(r"\s{2,}", " ", BRACKETED.sub(take, text)).strip()
    if not got:
        return []
    if not _key(left):
        del got[:]
        return []
    new["Text"] = left
    return got


def _stamped(doc):
    """A document with the syllables nobody has timed yet left out.

    parse_ttml keeps those now -- a file being written carries its words long
    before it carries their timings, and this project's own editor saves that
    file every half minute. The blender is not written for them: every
    question it asks of a syllable is where it sits in time, and a syllable
    with no time has no answer to give. They come off here, once, rather than
    being guarded against at each of the thirty places downstream that ask.

    Nothing is edited in place -- the caller's document is somebody else's,
    usually a cache entry -- and a document with no untimed syllables in it is
    handed straight back.
    """
    if not isinstance(doc, dict):
        return doc
    body = SL.payload(doc)
    def bare(g):
        return isinstance(g, dict) and any(
            not isinstance(y.get("StartTime"), (int, float))
            for y in g.get("Syllables") or [] if isinstance(y, dict))
    def parts(it):
        bg = it.get("Background")
        return [it.get("Lead")] + (bg if isinstance(bg, list) else
                                   [bg] if isinstance(bg, dict) else [])
    items = _items(body)
    if not any(bare(g) for it in items for g in parts(it)):
        return doc
    def kept(g):
        if not bare(g):
            return g
        return {**g, "Syllables": [y for y in g["Syllables"]
                                   if isinstance(y, dict) and isinstance(
                                       y.get("StartTime"), (int, float))]}
    out = []
    for it in items:
        it = dict(it)
        if isinstance(it.get("Lead"), dict):
            it["Lead"] = kept(it["Lead"])
        bg = it.get("Background")
        if isinstance(bg, list):
            it["Background"] = [kept(g) if isinstance(g, dict) else g for g in bg]
        elif isinstance(bg, dict):
            it["Background"] = kept(bg)
        out.append(it)
    body = dict(body)
    body["Lines" if body.get("Type") == "Static" else "Content"] = out
    return body


def _blend(base: dict, words: str, qq: dict | None, ne: dict | None,
           origin: str = "spicy", whose: str = "QQ Music",
           spare: dict | None = None, spare_name: str = "") -> dict | None:
    """The documents reconciled into one. Split out so it can be tested on
    fixed inputs rather than on whatever the servers feel like saying.

    `ne` is a third opinion on line starts. Nothing passes one any more; the
    parameter stays because every "who moved this line" branch below is
    written around having more than one opinion to weigh, and collapsing that
    to a single voice would rewrite the reconciling rather than simplify it.
    """
    base, qq, ne, spare = (_stamped(d) for d in (base, qq, ne, spare))
    bit = _items(SL.payload(base))
    if not bit:
        return None
    base_had = quality(SL.payload(base))
    qit = _items(SL.payload(qq)) if qq else []
    qorig = len(qit)
    apart = _filed_apart(qq) | _filed_apart(spare)
    nit = _items(SL.payload(ne)) if ne else []
    def worded(m, items, i) -> bool:
        """Whether line i would actually come out with words on it.

        Having a pairing is not the same as having timings, in two ways. A
        donor with only line stamps pairs with everything and places nothing,
        which is how NetEase's line-level copy of SICK SICK SICK filled every
        slot in the map and left the song bare. And a pairing to the wrong
        line relays nothing: on NF's MOTTO the last "Yeah" was paired to a QQ
        line whose letters are not its letters, so it came out untimed while
        the re-stream had the right syllables for it and was never asked,
        because the map said the line was spoken for.

        So this asks the question the loop below will ask, rather than the
        one the map answers.
        """
        got = items[m[i]] if m and i in m and m[i] < len(items) else None
        syls = ((got or {}).get("Lead") or {}).get("Syllables") or []
        return bool(syls) and bool(
            _relay(_unaside(SL.line_text(bit[i]), apart), syls, _alike(got)))

    qpairs = (_pair(bit, qit) or {}) if qit else {}
    qmap = _timely(dict(qpairs), bit, qit) if qit else None
    astray_q = {i: j for i, j in qpairs.items() if i not in (qmap or {})}
    if qit and len(qmap or ()) < len(bit):
        recut = _restream(bit, qit)
        if recut is not None:
            qmap, extra = dict(qmap or {}), []
            for i, got in enumerate(recut):
                if not got or worded(qmap, qit, i):
                    continue
                extra.append(got)
                qmap[i] = len(qit) + len(extra) - 1
            if extra:
                qit = list(qit) + extra
    steady = _wander(bit, qit, qmap or {})

    borrowed: set = set()
    rhythm: set = set()
    dropped: set = set()
    spare_lines = _items(SL.payload(spare)) if spare else []
    holes = [i for i in range(len(bit)) if not worded(qmap, qit, i)]
    astray = _astray(bit, qit, qmap, apart) if spare is not None else {}
    want = holes + sorted(astray)
    if spare is not None and want:
        sit = list(spare_lines)
        smap = dict(_timely(_pair(bit, sit), bit, sit) or {}) if sit else {}
        if sit and len(smap) < len(bit):
            for i, got in enumerate(_restream(bit, sit) or []):
                if i not in smap and got:
                    sit = list(sit) + [got]
                    smap[i] = len(sit) - 1
        sdrift = _drift(bit, sit, smap)
        qmap, extra = dict(qmap or {}), []
        for i in want:
            if not worded(smap, sit, i):
                continue
            if i in astray:
                theirs = (sdrift.get(i),
                          _guessed(_unaside(SL.line_text(bit[i]), apart),
                                   (sit[smap[i]] or {}).get("Lead")))
                if not _steadier(astray[i], theirs):
                    continue
                dropped.add(id(qit[qmap[i]]))
            elif abs(sdrift.get(i) or 0.0) > BLEND_STEADY:
                rhythm.add(i)
            extra.append(sit[smap[i]])
            qmap[i] = len(qit) + len(extra) - 1
            borrowed.add(i)
        if extra:
            qit = list(qit) + extra
    nmap = _timely(_pair(bit, nit), bit, nit) if nit else None
    ne_ends = bool(ne) and quality(ne) == "syllable"

    used: set[str] = set()
    spoken = {id(qit[k]) for k in (qmap or {}).values()
              if 0 <= k < len(qit)} | dropped
    slid: dict[int, float] = {}
    over: dict[int, float] = {}
    pool = []
    for item in list(qit[:qorig]) + list(spare_lines):
        parts = [item] + [g for g in (item.get("Background") or [])
                          if isinstance(g, dict)]
        for part in parts:
            syls = _syls_of(part)
            at, done = _group_span(part, syls)
            if syls and isinstance(at, (int, float)):
                pool.append((part, at, done, _key(SL.line_text({"Lead": part})),
                             syls))
    out, worded, based = [], 0, []
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
            based.append((b_s, b_e))
            continue
        start = _agree(starts)
        lent = ((q or {}).get("Lead") or {}).get("Syllables") or []
        if i in rhythm:
            if isinstance(b_s, (int, float)):
                start = b_s
        elif isinstance(q_s, (int, float)) and _relay(SL.line_text(it), lent):
            start = q_s
        for who in ("qq", "ne"):
            if who not in starts:
                continue
            rest = {k: v for k, v in starts.items() if k != who}
            if not rest or abs(_agree(rest) - start) > 1e-6:
                used.add(who)

        asides = _peel_bracket(new, pool, start, _line_end(it), spoken)
        if q is not None:
            got_aside = _peel_aside(new, q, qit, start, _line_end(it))
            if got_aside is not None:
                aside, lifted = got_aside
                asides.append(aside)
                spoken.add(id(qit[lifted]))
        qby = (start - q_s) if isinstance(q_s, (int, float)) else 0.0
        syls = _relay(new["Text"],
                      ((q or {}).get("Lead") or {}).get("Syllables") or [],
                      _alike(q))
        if syls:
            syls = [_slide(y, qby) for y in syls]
            if i in rhythm and not _fits(syls, start, b_nxt):
                syls = []
            else:
                used.add("spare" if i in borrowed else "qq")
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
            if not syls and i in astray_q:
                loose = qit[astray_q[i]]
                lent = _relay(new["Text"],
                              ((loose.get("Lead") or {}).get("Syllables") or []))
                d_s = SL.line_start(loose)
                if lent and isinstance(d_s, (int, float)):
                    lent = [_slide(y, start - d_s) for y in lent]
                    if _fits(lent, start, b_nxt):
                        syls = lent
                        spoken.add(id(loose))
                        used.add("qq")

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

        own = ends.get("base")
        sung = max([y["EndTime"] for y in syls[:-1]] or [start]) if syls else start
        if (own is not None and isinstance(b_e, (int, float))
                and isinstance(b_nxt, (int, float)) and b_nxt - b_e >= BLEND_TAIL
                and end - own > BLEND_HOLD
                and (not syls or own >= max(sung, syls[-1]["StartTime"] + 0.05))):
            end = max(own, start + 0.05)
            if syls and syls[-1]["EndTime"] > end:
                syls = syls[:-1] + [{**syls[-1], "EndTime": end}]
        elif (own is not None and isinstance(b_e, (int, float))
              and isinstance(b_nxt, (int, float)) and b_e > b_nxt + BLEND_HOLD
              and own > end + BLEND_HOLD):
            end = own
            if syls:
                syls = syls[:-1] + [{**syls[-1],
                                     "EndTime": max(syls[-1]["EndTime"], end)}]

        new["StartTime"], new["EndTime"] = start, end
        over[len(out)] = (max(0.0, b_e - b_nxt)
                          if isinstance(b_e, (int, float))
                          and isinstance(b_nxt, (int, float)) else 0.0)
        slid[len(out)] = qby
        if syls:
            new["Lead"] = {"StartTime": start, "EndTime": end, "Syllables": syls}
            worded += 1
        bg = [g for g in (it.get("Background") or []) if isinstance(g, dict)]
        if asides:
            bg = bg + asides
        if bg and isinstance(b_s, (int, float)):
            new["Background"] = [_slide(g, start - b_s) for g in bg]
        elif bg:
            new["Background"] = bg
        out.append(new)
        based.append((b_s, b_e))

    _in_step(out, based)

    for i in range(len(out) - 1):
        at, mine = SL.line_start(out[i + 1]), SL.line_start(out[i])
        done = _line_end(out[i])
        if not all(isinstance(v, (int, float)) for v in (at, mine, done)):
            continue
        room = at + over.get(i, 0.0)
        if at <= mine or done <= room:
            continue
        lead = out[i].get("Lead")
        keep = max(room, mine + 0.05)
        syls = (lead or {}).get("Syllables") or []
        if syls:
            keep = max(keep, syls[-1]["StartTime"] + 0.05)
            if syls[-1]["EndTime"] > keep:
                out[i]["Lead"] = {**lead, "EndTime": keep,
                                  "Syllables": syls[:-1]
                                  + [{**syls[-1], "EndTime": keep}]}
        out[i]["EndTime"] = keep

    if out:
        for lines in (qit[:qorig], nit, spare_lines):
            if lines:
                _place_dark(out, lines, spoken)
        for lines in (qit[:qorig], spare_lines):
            if lines:
                _lift_strays(out, lines, spoken, slid)

    if not out:
        return None
    worded = sum(1 for i in out
                 if ((i.get("Lead") or {}).get("Syllables") or []))
    typed = ("Syllable" if worded >= WORDED_SHARE * len(out) else
             "Line" if any("StartTime" in i for i in out) else "Static")
    doc = {k: v for k, v in SL.payload(base).items()
           if k not in ("Type", "Content", "Lines", "_via")}
    doc["Type"] = typed
    doc["Lines" if typed == "Static" else "Content"] = out
    if not doc.get("SongWriters"):
        writers = (SL.payload(ne or {}).get("SongWriters")
                   or SL.payload(qq or {}).get("SongWriters"))
        if writers:
            doc["SongWriters"] = writers
    doc = unlump(doc)
    if steady is not None and ("qq" in used or "spare" in used):
        doc["_steady"] = round(steady, 4)
    parts = [n for n, key in ((whose, "qq"), (spare_name, "spare"),
                              ("NetEase", "ne")) if key in used and n]
    if parts:
        doc["_via"] = " + ".join([words] + parts)
        if base_had != "syllable":
            doc["_lifted"] = True
    else:
        doc["_alone"] = origin
        if origin == "apple":
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


# NOT counted back to one with the rest of them at 1.0.0, and this is the one
# to leave alone. Every other revision here guards something derived: a walk's
# answer, a romanisation, a measured offset, each of them re-made by playing
# the song again. This guards what is kept under `aligned` -- an alignment
# this machine produced, which costs minutes and a GPU, and a file somebody
# dropped in, which is their own work. A document stamped with a revision this
# does not recognise is not read, so resetting the number would throw both
# away in silence. It moves when the shape of what is stored moves, and for
# no other reason.
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


def hand_aligned(tid: str) -> tuple[dict, str] | None:
    """A file somebody DROPPED for this track, and the name it came in under.

    `aligned` answers for both kinds of document held here -- this machine's
    alignment and a file dropped on the window -- because to everything
    downstream they are one thing: a document held for one track, ranked as
    "Aligned here". This is the question where they are not one thing.

    A dropped file has to be askable OUTSIDE the running order, because inside
    it the order is exactly what loses it: "Aligned here" sits last by design,
    and a walk that already holds word timing never reaches it (see _walk) --
    so on every song any ranked source word-syncs, the drop came back only for
    as long as the play it was dropped in. See LyricsView.restore_dropped.
    """
    rec = _align_rec(tid)
    hand = str((rec or {}).get("hand") or "") if rec else ""
    return (rec["doc"], hand) if hand else None


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
UNISON_CREDIT = f"Lyrics from Unison ({UNISON_BASE})"
BINI_BASE = "https://lyrics-api.binimum.org"
BINI_HOST = "binimum.org"
KUGOU_SEARCH = "https://mobileservice.kugou.com/api/v3/search/song"
KUGOU_KRCS = "https://krcs.kugou.com/search"
KUGOU_DOWN = "https://lyrics.kugou.com/download"
KRC_SLACK = 2.0
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


def _who(text: str) -> list[str]:
    """A credit line as the names in it, lead first."""
    return [n for n in (_norm(x) for x in NAMES_APART.split(text or "")) if n]


def _comparable(a: str, b: str) -> bool:
    """Whether two names are written in the same kind of script.

    Two spellings of one artist in one alphabet can be compared, and a
    disagreement between them means something. "YOASOBI" against a
    catalogue's "ヨアソビ" is not a disagreement -- it is the same name
    written the only way that catalogue writes names -- and reading it as one
    would throw away the hits this program exists to find.
    """
    def kinds(text: str) -> set:
        out = set()
        for ch in text or "":
            if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff":
                out.add("cjk")
            elif "\uac00" <= ch <= "\ud7af":
                out.add("hangul")
            elif ch.isalpha() and ch.isascii():
                out.add("latin")
        return out
    here, there = kinds(a), kinds(b)
    return bool(here and there and here & there)


def _same_artist(theirs: str, ours: str) -> tuple[bool, bool]:
    """(the lead is the same person, anybody is), by name.

    Two answers because they are worth different amounts. A shared LEAD is
    what tells S.L.I.D.E by Tory Lanez from Slide by Packy featuring him: the
    titles normalise to the same five letters and the durations are six
    seconds apart, so the lead credit is the only thing left that differs.
    Anybody in common is weaker but still worth having -- sources disagree
    about who leads a collaboration often enough that demanding the lead
    would throw away real hits.

    Both true where either side has no credit at all: an unnamed artist is
    not evidence of anything, and Kugou leaves the field empty often enough.
    """
    a, b = _who(theirs), _who(ours)
    if not a or not b:
        return True, True
    return a[0] == b[0], bool(set(a) & set(b))


ALT_CUT = re.compile(
    r"\b(live|acoustic|cover|remix|instrumental|karaoke|nightcore|demo"
    r"|tribute|rehearsal|session|mashup|parody|sped[\s-]?up|slowed"
    r"|bootleg|re-?work|flip|vip)\b", re.I)


def _cut_words(text: str) -> set[str]:
    r"""The version markers a title carries, spelling flattened.

    Run over a title with its camel case pulled apart, because Kugou files
    the one this was written for as "Galaxies (RogueRemix)" -- no space, and
    so no word boundary for `\bremix\b` to find. The capital is the boundary
    there, and it is the only place the missing space can be read from.
    """
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text or "")
    return {re.sub(r"[^a-z]", "", m.group(1).lower())
            for m in ALT_CUT.finditer(text)}


def _same_cut(theirs: str, ours: str) -> bool:
    """Whether a hit's title is about the recording we asked for.

    False only when the hit claims a version we did not ask for. A title
    that says less than ours says nothing against itself -- half the
    catalogues here drop the parenthetical -- so the test runs one way.
    """
    return not (_cut_words(theirs) - _cut_words(ours))


def _same_song(theirs: str, ours: str) -> bool:
    """Whether two titles name the same song, allowing for a longer one.

    Deliberately generous in ONE direction only: a source is allowed to have
    "Stronger (Radio Edit)" where we asked for "Stronger", because that is
    the same recording described at more length. It is not allowed to answer
    for something that merely contains our words, and -- see ALT_CUT -- not
    for something whose extra words say it is a different recording.
    """
    a, b = _norm(theirs), _norm(ours)
    if not a or not b:
        return False
    if not _same_cut(theirs, ours):
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


def _people_of(row: dict):
    """A Unison record, shaped so the roster can be asked about it.

    Unison names its submitter in the record rather than in the TTML, and
    `credited` reads the shape _unison_doc builds -- so a row that has not
    been turned into a document yet is given the same shape here, and the
    roster answers the same question about both.
    """
    who = ((row or {}).get("submitter") or {}).get("displayName") or ""
    return {"_maker": who} if who else {}


FEAT_BRACKET = re.compile(r"\s*[(\[](?:with|feat|ft|featuring|from)\b[^)\]]*[)\]]",
                          re.I)
SOURCE_TAIL = re.compile(
    r"\s*[-\u2013\u2014]\s*(?:from\b.*|single|ep|bonus track\b.*)$", re.I)


def _plain_title(title: str) -> str:
    """The song's name with the packaging off, for a search box.

    Returns the title unchanged where there is nothing to take off, which is
    most of them -- the caller uses that to know there is no second question
    worth asking.
    """
    was = (title or "").strip()
    got = SOURCE_TAIL.sub("", FEAT_BRACKET.sub("", was)).strip(" -\u2013\u2014")
    if _cut_words(was) - _cut_words(got):
        return was
    return got or was


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
    rule = getattr(_WALK, "people", None) or Roster()
    q = _qs(song=title, artist=artist)
    got = _json(f"{UNISON_BASE}/lyrics?{q}")
    rec = (got or {}).get("data") if isinstance(got, dict) else None
    if isinstance(rec, list):
        rec = rec[0] if rec else None
    if (isinstance(rec, dict) and rec.get("lyrics")
            and _near(rec.get("duration"), want)
            and not rule.blocks(_people_of(rec))
            and _same_artist(str(rec.get("artist") or ""), artist)[1]):
        return _unison_doc(rec)
    if not artist:
        return None
    rows = []
    seen = set()
    for ask in (title, _plain_title(title)):
        if ask in seen:
            continue
        seen.add(ask)
        got = _json(f"{UNISON_BASE}/lyrics/search?q="
                    f"{urllib.parse.quote(f'{ask} {artist}')}")
        found = (got or {}).get("data") if isinstance(got, dict) else None
        rows += found if isinstance(found, list) else []
    rank = {"high": 2, "medium": 1, "low": 0}
    best = None
    done = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        if row["id"] in done:
            continue
        done.add(row["id"])
        lead, any_of = _same_artist(str(row.get("artist") or ""), artist)
        if not (_same_song(row.get("song") or "", title)
                and _near(row.get("duration"), want) and any_of):
            continue
        who = _people_of(row)
        if rule.blocks(who):
            continue
        try:
            said = float(row.get("duration") or 0)
        except (TypeError, ValueError):
            said = 0.0
        score = (1 if rule.likes(who) else 0,
                 1 if lead else 0,
                 1 if (said and want) else 0,
                 -abs(said - want) if (said and want) else 0.0,
                 rank.get(str(row.get("confidence") or "").lower(), 0),
                 float(row.get("matchScore") or 0), int(row.get("voteCount") or 0))
        if best is None or score > best[0]:
            best = (score, row["id"])
    if best is None:
        return None
    got = _json(f"{UNISON_BASE}/lyrics/{urllib.parse.quote(str(best[1]))}")
    rec = (got or {}).get("data") if isinstance(got, dict) else None
    return _unison_doc(rec) if isinstance(rec, dict) else None


# --------------------------------------------------------------------------
APPLE_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
APPLE_AMP = "https://amp-api.music.apple.com/v1/catalog/us"
APPLE_CATALOG = "https://amp-api.music.apple.com/v1/catalog"

# Kana, Hangul and Han, and the storefront that writes each one natively.
#
# The US storefront romanises: it answers "Idol" for YOASOBI's アイドル,
# "Usseewa" for Ado's うっせぇわ, "Show" for 唱. A player says what its own
# catalogue says, which for this repertoire is the native title -- so the
# search matched nothing, no ISRC came back, and BiniLyrics (which files by
# ISRC) was never asked. Measured over eight Japanese-titled tracks here, six
# of them got no ISRC at all from `us` alone.
#
# Han on its own does not say which language it is, so it asks both.
NATIVE_STORE = ((re.compile(r"[\u3040-\u30ff]"), ("jp",)),
                (re.compile(r"[\uac00-\ud7af]"), ("kr",)),
                (re.compile(r"[\u4e00-\u9fff]"), ("jp", "tw")))


def _native_stores(*texts: str) -> tuple:
    """The storefronts that write these names the way the player does."""
    said = " ".join(t or "" for t in texts)
    for script, stores in NATIVE_STORE:
        if script.search(said):
            return stores
    return ()
APPLE_TOKEN_FILE = _cache_root() / "apple-token.json"
_APPLE_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
_apple_lock = threading.Lock()


def _plain_page(url: str) -> str:
    """A plain fetch of a web page or its JavaScript, gzip and all.

    Not _get: that one is the chain's funnel, with the chain's timeouts and
    its per-host gate, and this is a three-megabyte JavaScript bundle read
    once a day. It also has to say it is a browser to be given the bundle at
    all. Apple Music's catalogue token and SoundCloud's client id are both
    read out of a bundle this way; see _apple_token and _sc_client_id.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": APPLE_UA, "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=TIMEOUT * 2) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def _apple_token(force: bool = False) -> str:
    """The music.apple.com web player's catalogue key, cached until it expires.

    Apple's catalogue API needs a developer token and the web player carries
    one in its own JavaScript bundle -- the same one handed to every visitor.
    It is read from there, checked against the API once, and kept on disk with
    the expiry Apple stamped into it, because the bundle is megabytes and this
    is a lookup of one field.

    The bundle holds more than one JWT and only one of them is the catalogue
    key, so they are tried in turn rather than guessed at by shape. Under a
    lock, because a walk is ten threads wide and the look-ahead is warming
    three more tracks: without it a cold cache is a dozen threads each pulling
    the same bundle.

    The same trick editor/sources.py plays for Apple's songwriter credits,
    and deliberately a second copy of it: this module is the one every
    provider lives in and it does not import the editor, or the GUI, or
    anything else that could make a lyric fetch depend on a window existing.
    """
    with _apple_lock:
        if not force:
            try:
                got = json.loads(APPLE_TOKEN_FILE.read_text(encoding="utf-8"))
                if float(got.get("exp") or 0) > time.time() + 3600:
                    return str(got.get("token") or "")
            except Exception:                            # noqa: BLE001
                pass
        try:
            html = _plain_page("https://music.apple.com/us/browse")
        except Exception as exc:                         # noqa: BLE001
            _blamed(_why(exc))
            return ""
        for js in re.findall(r'/assets/index[^"\']*?\.js', html)[:3]:
            try:
                src = _plain_page("https://music.apple.com" + js)
            except Exception:                            # noqa: BLE001
                continue
            for tok in sorted(set(_APPLE_JWT.findall(src)), key=len):
                if _amp(tok, "search?term=test&types=songs&limit=1") is None:
                    continue
                exp = time.time() + 86400
                try:
                    import base64
                    pad = tok.split(".")[1] + "=="
                    exp = float(json.loads(base64.urlsafe_b64decode(pad))
                                .get("exp") or exp)
                except Exception:                        # noqa: BLE001
                    pass
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    APPLE_TOKEN_FILE.write_text(
                        json.dumps({"token": tok, "exp": exp}), encoding="utf-8")
                except Exception:                        # noqa: BLE001
                    pass
                return tok
        return ""


def _amp(token: str, path: str, store: str = ""):
    """One catalogue request, or None.

    `store` names a storefront other than the default one. The catalogue is
    the same catalogue either way -- the same recordings under the same ISRCs
    -- but each storefront writes the names in its own language, which is the
    whole reason for asking a second one. See NATIVE_STORE.
    """
    if not token:
        return None
    where = f"{APPLE_CATALOG}/{store}" if store else APPLE_AMP
    req = urllib.request.Request(
        f"{where}/{path}",
        headers={"Authorization": "Bearer " + token,
                 "Origin": "https://music.apple.com",
                 "Referer": "https://music.apple.com/",
                 "User-Agent": APPLE_UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403) and e.code not in MISSED:
            _blamed(_why(e))
        return None
    except Exception as e:                               # noqa: BLE001
        _blamed(_why(e))
        return None


APPLE_NAMES = re.compile(r"\s*(?:,|&| and )\s*")


def apple_names(who: str) -> list[str]:
    """One credit line as the people in it."""
    return [n.strip() for n in APPLE_NAMES.split(str(who or "")) if n.strip()]


def apple_art(art: dict, size: int = 1000) -> str:
    """One artwork url out of Apple's template.

    Apple hands the address over with the size left blank --
    ".../{w}x{h}bb.jpg", and sometimes the crop and the format as well -- so
    it is filled in here and everything downstream gets a plain url to fetch,
    the way every other source gives one.
    """
    url = str((art or {}).get("url") or "")
    if not url:
        return ""
    side = str(int(max(64, min(3000, size))))
    return (url.replace("{w}", side).replace("{h}", side)
               .replace("{c}", "bb").replace("{f}", "jpg"))


def apple_song(meta: dict) -> dict:
    """What Apple Music's catalogue has for this track, asked once.

    Three things come back and one request brings all of them: the ISRCs,
    which name the recording BiniLyrics files its TTML under; the
    songwriters, which Apple gives as the publishing credit -- legal names,
    every co-writer, on very nearly everything it has; and the card, which is
    the cover, the album and the rating.

    The card is here because of the players that have none. Spotify hands
    over a square cover and the album it belongs to; a browser hands over a
    video's thumbnail, or nothing, and a title where the album should be. The
    catalogue this already asks about the words has the cover too, so it is
    taken while the answer is open rather than asked for again later.

    Asked once per track however many callers want it, because they are two
    unrelated errands that happen to share an answer: from_bini wants a key
    to look up, _credited wants a list of names, and neither should cost the
    other a request. The pair are only fetched together because the search
    already returns them both; nothing here asks Apple twice.

    More than one ISRC, because a song is issued more than once -- the album
    cut, the single, a remaster, a regional edition -- and they are all the
    same lyric with the same timing. BiniLyrics may hold the TTML under any
    one of them, so the ones that match are all worth trying, in the order of
    how well they match.

    Matched on the same three things every other source here is matched on:
    the title allowing for a longer one, somebody in common on the byline,
    and the duration. The duration is the one that separates the album cut
    from the live version -- Apple has "Clocks" at 306.9s and "Clocks (Live)"
    at 285.0s, and only one of them is the recording anybody is playing.
    """
    title = (meta.get("title") or "").strip()
    artist = (meta.get("artist") or "").strip()
    if not title:
        return {"isrcs": [], "writers": [], "card": {}}
    return _once(("apple", _norm(title), _norm(artist),
                  round(float(meta.get("length") or 0))),
                 lambda: _apple_song(meta, title, artist))


def _apple_search(token: str, term: str, store: str) -> list:
    """One storefront's answer to one search, as its rows' attributes."""
    q = _qs(term=term, types="songs", limit=10, extend="isrc")
    got = _amp(token, f"search?{q}", store)
    if got is None:
        got = _amp(_apple_token(force=True), f"search?{q}", store)
    rows = (((got or {}).get("results") or {}).get("songs") or {}).get("data") or []
    return [(row or {}).get("attributes") or {}
            for row in (rows if isinstance(rows, list) else [])]


def _apple_song(meta: dict, title: str, artist: str) -> dict:
    token = _apple_token()
    term = f"{artist} {title}".strip()
    reads = [("", _apple_search(token, term, ""))]
    for store in _native_stores(title, artist):
        rows = _apple_search(token, term, store)
        if rows:
            reads.append((store, rows))

    want = float(meta.get("length") or 0)
    hits, loose = [], []
    named, billed = {}, {}
    for which, (_store, rows) in enumerate(reads):
        for rank, at in enumerate(rows):
            secs = float(at.get("durationInMillis") or 0) / 1000.0
            code = str(at.get("isrc") or "").strip().upper()
            said = _same_song(at.get("name") or "", title)
            lead, anyone = _same_artist(at.get("artistName") or "", artist)
            # Each half of the name, remembered against the recording it names,
            # so a storefront that writes only one of them the player's way
            # still gets a vote. See _confirmed.
            if code and _near(secs, want):
                if said:
                    named.setdefault(code, at)
                if anyone:
                    billed.setdefault(code, at)
            if not said or not anyone:
                continue
            order = (which, 0 if lead else 1)
            if not _near(secs, want):
                loose.append(((order, abs(secs - want)), at, rank))
                continue
            gap = abs(secs - want) if want > 0 and secs > 0 else NEAR
            hits.append(((order, gap), at, rank))
    hits.sort(key=lambda h: h[0])
    loose.sort(key=lambda h: h[0])
    if not hits:
        hits = _confirmed(named, billed, want)

    isrcs, writers = [], []
    for _score, at, _rank in hits:
        code = str(at.get("isrc") or "").strip().upper()
        if code and code not in isrcs:
            isrcs.append(code)
        if not writers:
            writers = apple_names(at.get("composerName") or "")
    return {"isrcs": isrcs, "writers": writers,
            "card": _apple_card(_cover_cut(hits or loose), meta)}


def _confirmed(named: dict, billed: dict, want: float) -> list:
    """Recordings both writings of the catalogue agree about, by ISRC.

    The last resort, and not a loose one. Spotify hands over a native title
    with a romanised artist -- "感電" by "Kenshi Yonezu" -- and neither
    storefront writes both of those: `us` has "Denki" by "Kenshi Yonezu",
    `jp` has "感電" by "米津玄師". Asked of either alone the song is missed,
    and asked of either alone with one half of the test dropped it is worse
    than missed: every Kenshi Yonezu track of about the right length matches
    on the artist, and the first of them is a different song.

    A recording named by one storefront and billed by the other is checked on
    the title, the artist AND the duration, same as anything here -- the three
    answers are simply spread across two writings of the same entry, and the
    ISRC is what staples them back together.
    """
    both = [(code, at) for code, at in named.items() if code in billed]
    if not both:
        return []
    def gap(at):
        secs = float(at.get("durationInMillis") or 0) / 1000.0
        return abs(secs - want) if want > 0 and secs > 0 else NEAR
    both.sort(key=lambda p: gap(p[1]))
    return [(((0, 0), gap(at)), at, n) for n, (_code, at) in enumerate(both)]


def _cover_cut(rows: list):
    """Which of several copies of one song the cover should come from.

    NOT the closest duration, which is what the ISRCs are ranked by. Asked of
    "Hymn for the Weekend" that picks a Coldplay compilation over A Head Full
    of Dreams, because the compilation's cut is half a second nearer -- the
    right recording and a cover nobody would recognise.

    The earliest release is the album the song came out on; anything later
    carrying the same recording is a compilation of it. Where two say the
    same day, Apple's own order of relevance decides, which is what put the
    real album first in that example and every other one tried.
    """
    if not rows:
        return None
    return min(rows, key=lambda r: (r[0][0],
                                    str((r[1].get("releaseDate") or "9999")),
                                    r[2]))[1]


def _apple_card(at: dict | None, meta: dict) -> dict:
    """The catalogue's own description of a track, for a player with none.

    Empty where nothing matched, and every field empty where Apple left it
    empty -- the caller fills in around what it already has rather than
    trusting this over it.

    `sure` is whether the match had anything real to go on. The search is
    matched on three things and two of them can be vacant: a card with no
    artist matches anybody, and one with no duration matches any length. A
    title alone is not enough to rename somebody's song by, so where that is
    all there was, the answer is offered as a cover and not as a name. See
    LyricsView.on_card.
    """
    if not at:
        return {}
    rating = str(at.get("contentRating") or "")
    ours = (meta.get("artist") or "").strip()
    _lead, anyone = _same_artist(str(at.get("artistName") or ""), ours)
    want = float(meta.get("length") or 0)
    secs = float(at.get("durationInMillis") or 0) / 1000.0
    return {
        "sure": bool((ours and anyone) or (want > 0 and secs > 0
                                           and abs(secs - want) <= NEAR)),
        "title": str(at.get("name") or ""),
        "artist": str(at.get("artistName") or ""),
        "album": str(at.get("albumName") or ""),
        "art": apple_art(at.get("artwork") or {}),
        "length": float(at.get("durationInMillis") or 0) / 1000.0,
        "explicit": True if rating == "explicit" else False if rating else None,
    }


def apple_card(meta: dict) -> dict:
    """Apple Music's cover, album and rating for this track, or {}."""
    return dict(apple_song(meta).get("card") or {})


# --------------------------------------------------------------------------
SC_API = "https://api-v2.soundcloud.com"
SC_ID_FILE = _cache_root() / "soundcloud-id.json"
SC_ID_LIFE = 24 * 3600.0
_SC_ID = re.compile(r'client_id\s*[:=]\s*"([0-9a-zA-Z]{20,})"')
_sc_lock = threading.Lock()


def _sc_client_id(force: bool = False) -> str:
    """The web player's key, cached on disk for a day.

    Read out of the last bundle first: the id lives in one of a dozen scripts
    and it has been in the last few for years, so walking them backwards
    finds it in one fetch rather than twelve.
    """
    with _sc_lock:
        if not force:
            try:
                got = json.loads(SC_ID_FILE.read_text(encoding="utf-8"))
                if got.get("id") and time.time() < float(got.get("exp") or 0):
                    return str(got["id"])
            except Exception:                            # noqa: BLE001
                pass
        try:
            html = _plain_page("https://soundcloud.com/")
        except Exception:                                # noqa: BLE001
            return ""
        for src in reversed(re.findall(r'src="(https://[^"]+\.js)"', html)):
            try:
                body = _plain_page(src)
            except Exception:                            # noqa: BLE001
                continue
            found = _SC_ID.search(body)
            if not found:
                continue
            cid = found.group(1)
            try:
                SC_ID_FILE.write_text(json.dumps(
                    {"id": cid, "exp": time.time() + SC_ID_LIFE}), encoding="utf-8")
            except Exception:                            # noqa: BLE001
                pass
            return cid
        return ""


def _sc_search(cid: str, term: str) -> list:
    if not cid:
        return []
    got = _json(f"{SC_API}/search/tracks?{_qs(q=term, client_id=cid, limit=10)}")
    rows = (got or {}).get("collection")
    return rows if isinstance(rows, list) else []


def _sc_art(url: str, size: int = 500) -> str:
    """SoundCloud's cover at a size worth drawing.

    The search hands over the 100-pixel one. The same file is served at every
    size the site uses, named in the url, and t500x500 is the largest that
    exists for every upload.
    """
    url = str(url or "")
    if not url:
        return ""
    return re.sub(r"-(large|t\d+x\d+|original)\.(jpg|png)$",
                  f"-t{int(size)}x{int(size)}.jpg", url)


def soundcloud_card(meta: dict) -> dict:
    """What SoundCloud has for this track: the cover, and little else.

    Matched the same way as everything else here -- the title, somebody on
    the byline, the duration -- with one extra allowance. A SoundCloud title
    is very often "Artist - Title", the artist written twice over, so the far
    side of the dash is tried as the title as well. Without that, the
    uploader's own habit is what loses the match.

    The duration is allowed to disagree. An upload is edited, a radio cut, a
    version with the tag on the front; that makes it the wrong recording to
    take an ISRC from and the right one to take a cover from, since it is
    still the same release. A byline that agrees is what carries it instead,
    and nothing without one is taken at all.
    """
    title = (meta.get("title") or "").strip()
    artist = (meta.get("artist") or "").strip()
    if not title or not artist:
        return {}
    return _once(("soundcloud", _norm(title), _norm(artist),
                  round(float(meta.get("length") or 0))),
                 lambda: _soundcloud_card(meta, title, artist))


def _soundcloud_card(meta: dict, title: str, artist: str) -> dict:
    rows = _sc_search(_sc_client_id(), f"{artist} {title}")
    if not rows:
        rows = _sc_search(_sc_client_id(force=True), f"{artist} {title}")
    want = float(meta.get("length") or 0)
    hits = []
    for rank, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        theirs = str(row.get("title") or "")
        who = str((row.get("user") or {}).get("username") or "")
        names = [theirs] + ([theirs.split(" - ", 1)[1]] if " - " in theirs else [])
        if not any(_same_song(n, title) for n in names):
            continue
        _lead, anyone = _same_artist(who, artist)
        if not anyone:
            continue
        secs = float(row.get("duration") or 0) / 1000.0
        hits.append(((0 if _near(secs, want) else 1, rank), row))
    if not hits:
        return {}
    hits.sort(key=lambda h: h[0])
    row = hits[0][1]
    pub = row.get("publisher_metadata") or {}
    return {
        "album": str(pub.get("album_title") or ""),
        "art": _sc_art(row.get("artwork_url") or ""),
        "explicit": pub.get("explicit") if isinstance(pub.get("explicit"), bool) else None,
        "sure": True,
    }


def track_card(meta: dict) -> dict:
    """What the catalogues know about a track, for a player that says little.

    Apple Music first and for everything, because its catalogue is edited: it
    is where the song's name is spelt the way the label spells it, which is
    what a YouTube upload shouting the artist in capitals is not. SoundCloud
    after it and for the cover alone -- see soundcloud_card -- because the
    songs Apple has never heard of are very often there.

    {} where neither knows it, and the player's own card stands.
    """
    card = dict(apple_card(meta))
    if card.get("art"):
        return card
    other = soundcloud_card(meta)
    if not other:
        return card
    for key, value in other.items():
        if value not in ("", None) and not card.get(key):
            card[key] = value
    return card


def apple_isrcs(meta: dict) -> list[str]:
    """The ISRCs Apple Music has for this track, best match first."""
    return list(apple_song(meta).get("isrcs") or [])


def apple_writers(meta: dict) -> list[str]:
    """Apple Music's songwriter credit, one name each.

    The publishing credit rather than an editor's: where Genius has "Ink" and
    "Sounwave", this has "Roshwita Larisha Bacha" and "Mark Anthony Spears".
    It is the credit Apple's own TTML carries, which is what most of the
    documents in this chain are copies of -- so filling a gap from here fills
    it with the same names the file would have had if the copy that reached
    us had kept them.
    """
    return list(apple_song(meta).get("writers") or [])


def _bini_rows(q: str) -> list:
    """One BiniLyrics lookup, as its rows."""
    got = _json(f"{BINI_BASE}/?{q}")
    rows = (got or {}).get("results") if isinstance(got, dict) else None
    return rows if isinstance(rows, list) else []


def from_bini(tid: str, meta: dict, local=None) -> dict | None:
    """BiniLyrics -- Apple Music's TTML, reached by a different key.

    The words are the same ones Apple Music hands over, so this is not a new
    catalogue; it is a door on that one, and the only one left now that
    LyricsPlus' is gone. What makes it the good door is what it is indexed by:
    every other source here is found by a Spotify id or by the words in a
    title, and this one is found by ISRC, which names the recording rather
    than the song.

    So the ISRC is worth going and getting. It is asked of Apple Music's own
    search -- the same catalogue, so its answer is the key this door files by
    (see apple_isrcs) -- and both ways of asking go out at once, because the
    name query is one request against a database and there is no sense making
    the answer wait behind a lookup it does not need. Where the ISRC lands a
    document that is the one taken: it cannot be the wrong recording, and the
    name query can. Where it does not, nothing is lost that was ever there.

    `meta` may carry an ISRC of its own, and it is believed over Apple's --
    a caller that knows the recording knows better than a search does.

    The lyrics live at a URL of their own, one fetch further on. It is
    followed only when it stays on the host that named it -- a document is
    worth having, a redirect somewhere else is not.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    isrc = str(meta.get("isrc") or "").strip()
    want = float(meta.get("length") or 0)
    if not isrc and not (title and (artist or want > 0)):
        return None

    def by_name():
        if isrc or not (title and artist):
            return []
        return _bini_rows(_qs(track=title, artist=artist, album=meta.get("album"),
                              duration=int(round(want)) if want > 0 else None))

    def by_isrc():
        """Every pressing's rows, up to the first that is word-timed.

        NOT the first code that answers at all, which is what this did and
        what cost Sweater Weather its word sync. Apple issued that recording
        three times -- the album, the anniversary edition, and the EP it came
        out on first -- and BiniLyrics holds the album's two word-timed and
        the EP's line-timed. The codes are ranked by how near each pressing's
        duration is to the track being played, so the EP sorts first the
        moment the length in hand is the EP's 240.04 rather than the album's
        240.4 -- which is exactly what happens once Apple's own card has been
        asked for, since the card takes its cover from the earliest release
        and its length from the same row (see _cover_cut, and card_len in
        lyrics_gui). One line-timed pressing then shut out two word-timed
        ones, and the blend built on those lines is what reached the screen.

        Merging them is not a looser match. This module's whole reason for
        keeping more than one ISRC is that they are the same lyric with the
        same timing, issued more than once -- so between two copies of it the
        question is which is better TIMED, and that is _bini_pick's to answer
        rather than the duration ranking's. Quality outranks order here as it
        does everywhere else in this walk.

        It costs nothing where the best-matching pressing is word-timed,
        which is the common case: the loop stops on the first word row. It
        costs the two extra lookups only where the alternative was handing
        back a line sync, and it already spent them where an earlier code
        answered with nothing.
        """
        codes = [isrc] if isrc else apple_isrcs(meta)
        got: list = []
        for code in codes[:3]:
            got += [r for r in _bini_rows(_qs(isrc=code)) if isinstance(r, dict)]
            if any(str(r.get("timing_type") or "").lower() == "word" for r in got):
                break
        return got

    got = _parallel({"isrc": by_isrc, "named": by_name})
    for which in ("isrc", "named"):
        url = _bini_pick(got.get(which) or [], title, want,
                         checked=which == "named")
        if not url:
            continue
        host = urllib.parse.urlsplit(url)
        if host.scheme != "https" or not (host.hostname or "").endswith(BINI_HOST):
            continue
        raw = _get(url, "application/xml")
        doc = parse_ttml(raw) if raw else None
        if doc is not None:
            return doc
    return None


def _bini_pick(rows: list, title: str, want: float, checked: bool) -> str:
    """The best of one lookup's rows, as the URL its TTML is at.

    `checked` says the rows came back from a query that only matched on the
    words in a name, so the title and the duration are looked at again here.
    Rows fetched by ISRC are not checked: the ISRC IS the check, and it is a
    stricter one than any string comparison -- a remaster with a different
    title and a different length is still not the recording that code names.
    """
    best = None
    for row in rows:
        if not isinstance(row, dict) or not row.get("lyricsUrl"):
            continue
        if checked and not (_same_song(row.get("track_name") or "", title)
                            and _near(row.get("duration"), want)):
            continue
        score = (1 if str(row.get("timing_type") or "").lower() == "word" else 0,
                 -abs(float(row.get("duration") or 0) - want) if want > 0 else 0)
        if best is None or score > best[0]:
            best = (score, str(row["lyricsUrl"]))
    return best[1] if best else ""


# --------------------------------------------------------------------------
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
    r"纯音乐|純音樂|请欣赏|請欣賞|此歌曲为没有填词|沒有填詞|无歌词|暫無歌詞|暂无歌词|"
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

    And it needs the ARTIST, which is the check this went without and which
    a short title cannot do without. "S.L.I.D.E" normalises to "slide", and
    _same_song lets a longer title contain a shorter one -- for "Stronger
    (Radio Edit)", which is what that rule is for -- so a search for Tory
    Lanez's S.L.I.D.E came back with Packy's "Slide (feat. Tory Lanez)" at
    227s, Calvin Harris, Frank Ocean and Migos' "Slide" at 230s, and the
    right song at 233s, all four inside the six seconds _near allows. With
    only the duration to sort them, the winner was whichever recording our
    copy happened to be nearest in length to, and on a track whose Spotify
    duration is a few seconds off Kugou's that is somebody else's song.

    The credit is asked for twice over. A row sharing nobody at all with us
    is dropped, and among those that remain a shared LEAD is preferred to a
    shared guest -- which is what separates the song Tory Lanez made from the
    one he appears on. Duration only breaks what is left.
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
        singer = str(row.get("singername") or "")
        if not name:
            said = str(row.get("filename") or "").split(" - ", 1)
            name = said[-1]
            singer = singer or (said[0] if len(said) > 1 else "")
        lead, any_of = _same_artist(singer, artist)
        if not (_same_song(name, title) and _near(dur, want) and any_of):
            continue
        out.append((0 if lead else 1, abs(dur - want) if want > 0 else 0.0,
                    str(row["hash"]), int(dur * 1000)))
    out.sort()
    return [(h, ms) for _lead, _d, h, ms in out]


def from_kugou(tid: str, meta: dict, local=None) -> dict | None:
    """Kugou, asked once per track however many callers want it."""
    return _once(("kugou", tid, _norm(meta.get("title") or ""),
                  _norm(meta.get("artist") or ""), round(float(meta.get("length") or 0))),
                 lambda: _kugou(tid, meta))


def _kugou(tid: str, meta: dict) -> dict | None:
    """Kugou, by way of KRC.

    Worth a slot of its own: Kugou times its lyrics per syllable, and its
    catalogue is the Chinese one, which is the half of the library the
    English-speaking sources here are worst at. Where amll and Apple have
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
            if not (_near(float(cand.get("duration") or 0) / 1000.0,
                          ms / 1000.0, KRC_SLACK)
                    and _same_cut(cand.get("song") or "", title)):
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


# --------------------------------------------------------------------------
QQ_SEARCH = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQ_DOWN = "https://c.y.qq.com/qqmusic/fcgi-bin/lyric_download.fcg"
QQ_TRIES = 3
QRC_KEYS = (b"!@#)(NHL", b"123ZXC!@", b"!@#)(*$%")
QRC_SBOX = (
    bytes((
        14,  4, 13,  1,  2, 15, 11,  8,  3, 10,  6, 12,  5,  9,  0,  7,
         0, 15,  7,  4, 14,  2, 13,  1, 10,  6, 12, 11,  9,  5,  3,  8,
         4,  1, 14,  8, 13,  6,  2, 11, 15, 12,  9,  7,  3, 10,  5,  0,
        15, 12,  8,  2,  4,  9,  1,  7,  5, 11,  3, 14, 10,  0,  6, 13,
    )),
    bytes((
        15,  1,  8, 14,  6, 11,  3,  4,  9,  7,  2, 13, 12,  0,  5, 10,
         3, 13,  4,  7, 15,  2,  8, 15, 12,  0,  1, 10,  6,  9, 11,  5,
         0, 14,  7, 11, 10,  4, 13,  1,  5,  8, 12,  6,  9,  3,  2, 15,
        13,  8, 10,  1,  3, 15,  4,  2, 11,  6,  7, 12,  0,  5, 14,  9,
    )),
    bytes((
        10,  0,  9, 14,  6,  3, 15,  5,  1, 13, 12,  7, 11,  4,  2,  8,
        13,  7,  0,  9,  3,  4,  6, 10,  2,  8,  5, 14, 12, 11, 15,  1,
        13,  6,  4,  9,  8, 15,  3,  0, 11,  1,  2, 12,  5, 10, 14,  7,
         1, 10, 13,  0,  6,  9,  8,  7,  4, 15, 14,  3, 11,  5,  2, 12,
    )),
    bytes((
         7, 13, 14,  3,  0,  6,  9, 10,  1,  2,  8,  5, 11, 12,  4, 15,
        13,  8, 11,  5,  6, 15,  0,  3,  4,  7,  2, 12,  1, 10, 14,  9,
        10,  6,  9,  0, 12, 11,  7, 13, 15,  1,  3, 14,  5,  2,  8,  4,
         3, 15,  0,  6, 10, 10, 13,  8,  9,  4,  5, 11, 12,  7,  2, 14,
    )),
    bytes((
         2, 12,  4,  1,  7, 10, 11,  6,  8,  5,  3, 15, 13,  0, 14,  9,
        14, 11,  2, 12,  4,  7, 13,  1,  5,  0, 15, 10,  3,  9,  8,  6,
         4,  2,  1, 11, 10, 13,  7,  8, 15,  9, 12,  5,  6,  3,  0, 14,
        11,  8, 12,  7,  1, 14,  2, 13,  6, 15,  0,  9, 10,  4,  5,  3,
    )),
    bytes((
        12,  1, 10, 15,  9,  2,  6,  8,  0, 13,  3,  4, 14,  7,  5, 11,
        10, 15,  4,  2,  7, 12,  9,  5,  6,  1, 13, 14,  0, 11,  3,  8,
         9, 14, 15,  5,  2,  8, 12,  3,  7,  0,  4, 10,  1, 13, 11,  6,
         4,  3,  2, 12,  9,  5, 15, 10, 11, 14,  1,  7,  6,  0,  8, 13,
    )),
    bytes((
         4, 11,  2, 14, 15,  0,  8, 13,  3, 12,  9,  7,  5, 10,  6,  1,
        13,  0, 11,  7,  4,  9,  1, 10, 14,  3,  5, 12,  2, 15,  8,  6,
         1,  4, 11, 13, 12,  3,  7, 14, 10, 15,  6,  8,  0,  5,  9,  2,
         6, 11, 13,  8,  1,  4, 10,  7,  9,  5,  0, 15, 14,  2,  3, 12,
    )),
    bytes((
        13,  2,  8,  4,  6, 15, 11,  1, 10,  9,  3, 14,  5,  0, 12,  7,
         1, 15, 13,  8, 10,  3,  7,  4, 12,  5,  6, 11,  0, 14,  9,  2,
         7, 11,  4,  1,  9, 12, 14,  2,  0,  6, 10, 13, 15,  3,  5,  8,
         2,  1, 14,  7,  4, 10,  8, 13, 15, 12,  9,  0,  3,  5,  6, 11,
    )),
)
QRC_IP = (57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
          61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7)
QRC_PBOX = (15, 6, 19, 20, 28, 11, 27, 16, 0, 14, 22, 25, 4, 17, 30, 9,
            1, 7, 23, 13, 31, 26, 2, 8, 18, 12, 29, 5, 21, 10, 3, 24)
QRC_EXPAND = (31, 0, 1, 2, 3, 4, 3, 4, 5, 6, 7, 8, 7, 8, 9, 10,
              11, 12, 11, 12, 13, 14, 15, 16, 15, 16, 17, 18, 19, 20, 19, 20,
              21, 22, 23, 24, 23, 24, 25, 26, 27, 28, 27, 28, 29, 30, 31, 0)
QRC_SHIFT = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)
QRC_PERM_C = (56, 48, 40, 32, 24, 16, 8, 0, 57, 49, 41, 33, 25, 17,
              9, 1, 58, 50, 42, 34, 26, 18, 10, 2, 59, 51, 43, 35)
QRC_PERM_D = (62, 54, 46, 38, 30, 22, 14, 6, 61, 53, 45, 37, 29, 21,
              13, 5, 60, 52, 44, 36, 28, 20, 12, 4, 27, 19, 11, 3)
QRC_SQUEEZE = (13, 16, 10, 23, 0, 4, 2, 27, 14, 5, 20, 9,
               22, 18, 11, 3, 25, 7, 15, 6, 26, 19, 12, 1,
               40, 51, 30, 36, 46, 54, 29, 39, 50, 44, 32, 47,
               43, 48, 38, 55, 33, 52, 45, 41, 49, 35, 28, 31)
QRC_ORDER = (3, 2, 1, 0, 7, 6, 5, 4)
QRC_UNORDER = (4, 5, 6, 7, 0, 1, 2, 3)
QRC_M32 = 0xFFFFFFFF


def _qrc_bit(src, b: int, to: int) -> int:
    """Bit b of a byte string, counted from the left, moved to position `to`."""
    return ((src[QRC_ORDER[b // 8]] >> (7 - b % 8)) & 1) << to


def _qrc_tables():
    """Every fixed permutation here, precomputed against the bytes it takes.

      sp   the S-boxes with the P-box already applied, per box, per 6 bits
      exp  the expansion, per byte of the half-block it expands
      ipl  the initial permutation's left half, per byte of the block
      ipr  ...and its right half, which reads the bit one to the left
    """
    sp = []
    for i in range(8):
        box = [0] * 64
        for six in range(64):
            row = (six & 0x20) | ((six & 0x1F) >> 1) | ((six & 1) << 4)
            state = QRC_SBOX[i][row] << (28 - 4 * i)
            out = 0
            for k, b in enumerate(QRC_PBOX):
                out |= ((state >> (31 - b)) & 1) << (31 - k)
            box[six] = out
        sp.append(box)
    exp = [[0] * 256 for _ in range(4)]
    for k, b in enumerate(QRC_EXPAND):
        col = exp[b // 8]
        for v in range(256):
            col[v] |= ((v >> (7 - b % 8)) & 1) << (47 - k)
    ipl = [[0] * 256 for _ in range(8)]
    ipr = [[0] * 256 for _ in range(8)]
    for i, b in enumerate(QRC_IP):
        lcol, rcol = ipl[QRC_ORDER[b // 8]], ipr[QRC_ORDER[b // 8]]
        for v in range(256):
            lcol[v] |= ((v >> (7 - b % 8)) & 1) << (31 - i)
            rcol[v] |= ((v >> (7 - (b - 1) % 8)) & 1) << (31 - i)
    return sp, exp, ipl, ipr


QRC_SP, QRC_EXP, QRC_IPL, QRC_IPR = _qrc_tables()


def _qrc_split(block) -> tuple:
    """One eight-byte block as the two 32-bit halves DES works on."""
    left = right = 0
    for i in range(8):
        b = block[i]
        left |= QRC_IPL[i][b]
        right |= QRC_IPR[i][b]
    return left, right


def _qrc_f(state: int, key: bytes) -> int:
    """DES's round function: expand to 48 bits, key it, S-box it, permute it.

    Textbook from here down -- the expansion, the boxes and the P-box are the
    real DES's, and only the two typo'd entries in QRC_SBOX are QQ's. All of
    it is read out of _qrc_tables; the P-box is already folded into the
    S-box answers.
    """
    bits = (QRC_EXP[0][(state >> 24) & 0xFF] | QRC_EXP[1][(state >> 16) & 0xFF]
            | QRC_EXP[2][(state >> 8) & 0xFF] | QRC_EXP[3][state & 0xFF])
    bits ^= int.from_bytes(key, "big")
    return (QRC_SP[0][(bits >> 42) & 0x3F] | QRC_SP[1][(bits >> 36) & 0x3F]
            | QRC_SP[2][(bits >> 30) & 0x3F] | QRC_SP[3][(bits >> 24) & 0x3F]
            | QRC_SP[4][(bits >> 18) & 0x3F] | QRC_SP[5][(bits >> 12) & 0x3F]
            | QRC_SP[6][(bits >> 6) & 0x3F] | QRC_SP[7][bits & 0x3F])


def _qrc_join(left: int, right: int) -> bytes:
    """The halves put back, undoing the permutation and the byte swap at once."""
    out = bytearray(8)
    for k in range(8):
        v = 0
        for j in range(4):
            v |= (((right >> (31 - k - 8 * j)) & 1) << (7 - 2 * j)
                  | ((left >> (31 - k - 8 * j)) & 1) << (6 - 2 * j))
        out[QRC_UNORDER[k]] = v
    return bytes(out)


def _qrc_schedule(key: bytes, decrypt: bool) -> list:
    """The sixteen round keys, in the order this direction wants them.

    The `- 27` is QQ's off-by-one. A correct DES takes the second half of the
    compression permutation off the right register with `- 28`, which is where
    that register's bits actually start.
    """
    c = d = 0
    for i in range(28):
        c |= _qrc_bit(key, QRC_PERM_C[i], 31 - i)
        d |= _qrc_bit(key, QRC_PERM_D[i], 31 - i)
    rounds = [bytearray(6) for _ in range(16)]
    for i, shift in enumerate(QRC_SHIFT):
        c = (((c << shift) & QRC_M32) | (c >> (28 - shift))) & 0xFFFFFFF0
        d = (((d << shift) & QRC_M32) | (d >> (28 - shift))) & 0xFFFFFFF0
        into = rounds[15 - i if decrypt else i]
        for j in range(24):
            into[j // 8] |= ((c >> (31 - QRC_SQUEEZE[j])) & 1) << (7 - j % 8)
        for j in range(24, 48):
            into[j // 8] |= ((d >> (31 - QRC_SQUEEZE[j] + 27)) & 1) << (7 - j % 8)
    return rounds


def _qrc_des(data: bytes, key: bytes, decrypt: bool) -> bytes:
    """DES-ECB over whole blocks, QQ's way. A trailing part-block is dropped.

    The round function is written out rather than called; it is the same
    expression as _qrc_f, and tests/test_qrc.py holds the two together.
    """
    rounds = [int.from_bytes(bytes(r), "big")
              for r in _qrc_schedule(key, decrypt)]
    sp, ex, ipl, ipr = QRC_SP, QRC_EXP, QRC_IPL, QRC_IPR
    last, rounds = rounds[15], rounds[:15]
    out = bytearray()
    for at in range(0, len(data) - len(data) % 8, 8):
        block = data[at:at + 8]
        left = right = 0
        for i in range(8):
            b = block[i]
            left |= ipl[i][b]
            right |= ipr[i][b]
        for rk in rounds:
            bits = (ex[0][(right >> 24) & 0xFF] | ex[1][(right >> 16) & 0xFF]
                    | ex[2][(right >> 8) & 0xFF] | ex[3][right & 0xFF]) ^ rk
            left, right = right, (
                sp[0][(bits >> 42) & 0x3F] | sp[1][(bits >> 36) & 0x3F]
                | sp[2][(bits >> 30) & 0x3F] | sp[3][(bits >> 24) & 0x3F]
                | sp[4][(bits >> 18) & 0x3F] | sp[5][(bits >> 12) & 0x3F]
                | sp[6][(bits >> 6) & 0x3F] | sp[7][bits & 0x3F]) ^ left
        bits = (ex[0][(right >> 24) & 0xFF] | ex[1][(right >> 16) & 0xFF]
                | ex[2][(right >> 8) & 0xFF] | ex[3][right & 0xFF]) ^ last
        left = (sp[0][(bits >> 42) & 0x3F] | sp[1][(bits >> 36) & 0x3F]
                | sp[2][(bits >> 30) & 0x3F] | sp[3][(bits >> 24) & 0x3F]
                | sp[4][(bits >> 18) & 0x3F] | sp[5][(bits >> 12) & 0x3F]
                | sp[6][(bits >> 6) & 0x3F] | sp[7][bits & 0x3F]) ^ left
        out += _qrc_join(left, right)
    return bytes(out)


def _qrc(blob: str) -> str | None:
    """One hex QRC payload as its plain text, or None if it will not decrypt.

    QQ files the translation in the same envelope as the lyric but leaves it
    in the clear, so a payload that is not hex at all is handed back as it
    stands rather than treated as a failure.
    """
    return offload.call(_qrc_here, blob)


def _qrc_here(blob: str) -> str | None:
    """The decrypt itself. Triple DES over a few thousand blocks is the second
    thing on a cold walk that never lets the interpreter go -- ~930ms even
    with the tables. See offload."""
    import zlib

    blob = (blob or "").strip()
    if not blob:
        return None
    try:
        raw = bytes.fromhex(blob)
    except ValueError:
        return blob
    for key, decrypt in zip(QRC_KEYS, (True, False, True)):
        raw = _qrc_des(raw, key, decrypt)
    try:
        text = zlib.decompress(raw)
    except Exception:
        return None
    return text.decode("utf-8-sig", "replace")


QRC_CDATA = re.compile(r"<(contentroma|content)\b[^>]*>\s*<!\[CDATA\[(.*?)\]\]>", re.S)
QRC_BODY = re.compile(r'LyricContent="(.*)"\s*/>', re.S)
QRC_LINE = re.compile(r"^\[(\d+),(\d+)\]")
QRC_STAMP = re.compile(r"\((\d+),(\d+)\)")
QRC_TAIL = re.compile(r"^~+\s*end\s*~+$", re.I)
QQ_CREDIT = re.compile(
    r"^.{0,40}\bby\s*[:：]"
    r"|^.{0,30}\b(?:title|writer|publisher|lyrics?|composer|arranger|producer"
    r"|vocals?|programming|engineer|mix|master)\s*[:：]", re.I)


def _qrc_parts(raw) -> dict:
    """The lyric and the romanisation out of one download response."""
    text = raw.decode("utf-8", "replace") if raw else ""
    out = {}
    for tag, blob in QRC_CDATA.findall(text):
        got = _qrc(blob)
        if not got:
            continue
        body = QRC_BODY.search(got)
        out[tag] = body.group(1) if body else got
    return out


def _qrc_items(text: str):
    """QRC -> timed items, and whoever its credit lines named.

    A line is `[start,length]` and then one `word(start,length)` per syllable,
    with the word BEFORE its stamp and every time measured from the song --
    where Kugou writes the stamp first and measures it from the line. The rest
    is the same shape, credits and backing vocals included, so the same
    filters run over it.

    The words are read BETWEEN the stamps rather than matched as tokens of
    their own, because a lyric may open a bracket the pattern would eat:
    KiiiKiii's title line ends "Phone (" and hands its bracket to the next
    syllable if the parentheses are what the words are found by.
    """
    items, wrote = [], []
    for raw in (text or "").splitlines():
        m = QRC_LINE.match(raw)
        if not m:
            continue
        toks, at = [], m.end()
        for stamp in QRC_STAMP.finditer(raw, m.end()):
            toks.append((raw[at:stamp.start()],
                         int(stamp.group(1)), int(stamp.group(2))))
            at = stamp.end()
        if not toks:
            continue
        body = "".join(t[0] for t in toks).strip()
        if not body or QRC_TAIL.match(body) or NE_CREDIT.match(body) \
                or QQ_CREDIT.match(body):
            said = NE_WROTE.match(body) if body else None
            for name in (re.split(r"\s*[/、,，&]\s*", said.group(2)) if said else []):
                name = name.strip()
                if name and name not in wrote:
                    wrote.append(name)
            continue
        start, length = int(m.group(1)) / 1000.0, int(m.group(2)) / 1000.0
        syls = []
        for word, at_ms, dur in toks:
            got = word.rstrip()
            if not got:
                if syls:
                    syls[-1]["IsPartOfWord"] = False
                continue
            at_s = at_ms / 1000.0
            syls.append({"Text": got, "StartTime": at_s,
                         "EndTime": at_s + dur / 1000.0,
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


def _qq_hits(title: str, artist: str, want: float) -> list[tuple]:
    """(id, the name and byline QQ files it under) for its likeliest copies.

    The desktop search every other client reaches for is behind a login now --
    it answers `code 2001` and a sign-in URL to an anonymous caller, whatever
    headers it is given -- so this asks the older one, which still answers and
    still carries the duration a match has to be checked against.

    Believed on the same three signals Kugou's hits are: the title, the
    byline, the length. QQ's search is as willing as anyone's to answer for a
    song it does not have.

    QQ's own spelling of the title comes back with the id because the lyric
    needs it: the document opens with a title card written from these strings
    and not from ours, so ours cannot recognise it.
    """
    q = urllib.parse.quote(f"{title} {artist}".strip())
    got = _json(f"{QQ_SEARCH}?format=json&p=1&n=10&w={q}"
                "&cr=1&t=0&aggr=1&lossless=0&flag_qc=0")
    rows = (((got or {}).get("data") or {}).get("song") or {}).get("list") or []
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("songid"):
            continue
        dur = float(row.get("interval") or 0)
        name = str(row.get("songname") or "")
        singer = "/".join(str(s.get("name") or "") for s in (row.get("singer") or [])
                          if isinstance(s, dict))
        lead, any_of = _same_artist(singer, artist)
        if not (_same_song(name, title) and _near(dur, want) and any_of):
            continue
        out.append((0 if lead else 1, abs(dur - want) if want > 0 else 0.0,
                    int(row["songid"]), name, singer))
    out.sort()
    return [(sid, name, singer) for _lead, _off, sid, name, singer in out]


QQ_SAYS = re.compile(r"^\s*(.+?)\s*[:：]\s*$")


def _qq_head(items: list[dict], name: str, artist: str,
             wrote: list[str] | None = None) -> list[dict]:
    """QQ's own furniture taken out of the lyric.

    Two pieces of it. The first line is a title card -- "Clocks - Coldplay" --
    timed across the introduction like Kugou's, but _krc_head cannot be the
    thing that drops it, because it asks for the card to spell the title and
    the byline exactly as we hold them and QQ's card does neither. It writes
    "Time - NF" for a song QQ itself files as "Time (Edit)", and where the
    title carries a bracket -- KiiiKiii's "(나 어떡해)" -- _ne_bg has already
    lifted it out of the line as a backing vocal before anyone can compare.
    So the card is recognised by its SHAPE instead: the title and the byline
    either side of a dash, each matched the way a search hit is.

    The second is the speaker label. On a collaboration QQ marks the handover
    with a line reading "Lil Peep：", stamped and timed like a verse, and
    white tee carries four of them. A label is only a label when what it names
    is somebody actually credited on the song, which is what keeps this from
    eating a lyric that happens to end in a colon.

    Credited on the song, and not only in the byline: a group is billed under
    the group's name and hands over between its members, none of whom the
    byline mentions. Sexion d'Assaut's "Ma direction" is the case -- four
    lines reading "Maître Gims：", timed and drawn like verses, against a
    byline that says "Sexion D'Assaut" and nothing else. What names him is
    the document itself, in the credit block `_qrc_items` has already read
    two lines above the first of them ("Lyrics by：Maître Gims/Lefa/Barack
    Adama/Maska"), so `wrote` is asked as well as the byline. A name QQ went
    to the trouble of filing as this song's writer is not a lyric that
    happens to be a name and a colon.
    """
    while items:
        text = (SL.line_text(items[0]) or "").strip()
        head, sep, tail = text.rpartition(" - ")
        if not (sep and _who(tail) and _same_song(head, name)
                and _same_artist(tail, artist)[1]):
            break
        items = items[1:]
    who = set(_who(artist)) | {_norm(n) for n in (wrote or []) if _norm(n)}
    out = []
    for it in items:
        said = QQ_SAYS.match(SL.line_text(it) or "")
        names = _who(said.group(1)) if said else []
        if names and all(n in who for n in names):
            continue
        out.append(it)
    return out


def _qq_doc(parts: dict, name: str, artist: str) -> dict | None:
    """One download response's payloads as a lyrics document."""
    items, wrote = _qrc_items(parts.get("content") or "")
    items = _qq_head(items, name, artist, wrote)
    if not items or _instrumental(items):
        return None
    roma, _ = _qrc_items(parts.get("contentroma") or "")
    said = {round(float(it.get("StartTime") or 0), 3): SL.line_text(it) or ""
            for it in roma}
    for it in items:
        got = said.get(round(float(it.get("StartTime") or 0), 3), "").strip()
        if got:
            it["TransliteratedText"] = got
    doc = {"Type": "Syllable", "Content": _destamp(items),
           "HasTransliterations": False}
    if wrote:
        doc["SongWriters"] = wrote
    return doc


def _qq(tid: str, meta: dict) -> dict | None:
    """QQ Music, by way of QRC.

    Two requests deep -- find the recording, download the lyric filed against
    it -- and the walk stops at the first copy that answers, since a release
    QQ has no words for is not evidence about the next one.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title:
        return None
    want = float(meta.get("length") or 0)
    for sid, name, singer in _qq_hits(title, artist, want)[:QQ_TRIES]:
        raw = _get(f"{QQ_DOWN}?version=15&miniversion=82&lrctype=4&musicid={sid}",
                   "text/xml")
        doc = _qq_doc(_qrc_parts(raw), name or title, singer or artist)
        if doc:
            return doc
    return None


# --------------------------------------------------------------------------
MXM_BASE = "https://apic-appmobile.musixmatch.com/ws/1.1/"
MXM_APP = "mac-ios-v2.0"
MXM_HEAD = {
    "X-Cookie": "x-mxm-token-guid=",
    "x-mxm-app-version": "10.1.1",
    "X-User-Agent": "Musixmatch/2025120901 CFNetwork/3860.300.31 Darwin/25.2.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json",
}
MXM_TOKEN_FILE = _cache_root() / "musixmatch-token.json"
MXM_COLD = 1800.0
MXM_WROTE = re.compile(r"writer\(s\)\s*:\s*(.+)", re.I)
MXM_STOP = 0.005
MXM_GAP = 0.4


def _mxm_get(path: str, **kw):
    """One call at Musixmatch's door, as the parsed `message`, or None.

    Everything here answers HTTP 200 and puts the real answer in the
    envelope's own header, so the status that matters is the inner one and
    the caller is the one that has to read it.
    """
    kw.setdefault("app_id", MXM_APP)
    kw.setdefault("format", "json")
    url = MXM_BASE + path + "?" + _qs(**kw)
    req = urllib.request.Request(url, headers=MXM_HEAD)
    wait = _patience(url)
    with _gate(url):
        try:
            with urllib.request.urlopen(req, timeout=wait) as r:
                got = json.loads(r.read())
        except Exception as e:                           # noqa: BLE001
            if not isinstance(e, urllib.error.HTTPError) or e.code not in MISSED:
                _blamed(_why(e, wait))
            return None
    msg = got.get("message") if isinstance(got, dict) else None
    return msg if isinstance(msg, dict) else None


def _mxm_code(msg) -> int:
    return int(((msg or {}).get("header") or {}).get("status_code") or 0)


def _mxm_token(force: bool = False) -> str:
    """The app token Musixmatch hands out, kept on disk between runs.

    Not a secret and not a credential: token.get gives one to anyone who asks
    in the iOS app's clothes. But it cannot be asked for often -- a few in a
    row and the endpoint answers 401 `hint: captcha` for a while -- so one is
    fetched, written down, and used until a call comes back unauthorised.

    Spicetify ships a shared token as its default, and copying that is the one
    thing not to do: the value in the repository today is already refused.
    Everybody using it is why.
    """
    got = {}
    try:
        got = json.loads(MXM_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        pass
    held = str(got.get("token") or "")
    if held and not force:
        return held
    if time.time() - float(got.get("cold") or 0) < MXM_COLD:
        return "" if force else held
    msg = _mxm_get("token.get")
    tok = str(((msg or {}).get("body") or {}).get("user_token") or "")
    try:
        MXM_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        MXM_TOKEN_FILE.write_text(
            json.dumps({"token": tok, "at": time.time()} if tok
                       else {"cold": time.time()}), encoding="utf-8")
    except OSError:
        pass
    return tok


def _mxm_ask(tid: str, meta: dict, token: str):
    """Everything Musixmatch has for one track, in one request.

    `optional_calls` is what puts the word timing in the answer at all -- the
    macro leaves track.richsync out unless it is asked for by name, and
    without it finding the richsync costs a second round trip.

    `track_spotify_id` is what makes the answer the right recording, and it is
    not a nicety. Asked for "In the End" by name and duration the matcher
    returns track 422430305, which has no richsync; asked with the Spotify id
    it returns 15889056, which does. The name query is sent alongside it as
    what to fall back on, the way BiniLyrics is asked by ISRC first.
    """
    dur = float(meta.get("length") or 0)
    return _mxm_get(
        "macro.subtitles.get", usertoken=token,
        namespace="lyrics_richsynched", subtitle_format="lrc",
        optional_calls="track.richsync", richsync_compact_type="words",
        track_spotify_id=tid or None,
        q_track=(meta.get("title") or "").strip() or None,
        q_artist=(meta.get("artist") or "").strip() or None,
        q_album=(meta.get("album") or "").strip() or None,
        q_duration=round(dur, 3) or None,
        f_subtitle_length=int(round(dur)) or None)


def _mxm_syllables(row: dict) -> list[dict]:
    """One richsync line's words, with the ends the gaps between them give.

    richsync writes the spaces as entries of their own --
    ("It", 0), (" ", 0.06), ("starts", 0.13) -- so the space says when the
    word before it stopped. That is a measured end, and Musixmatch is the only
    source here that has one: NetEase, QQ and Kugou all tile, running every
    word until the next one starts. 2% of Musixmatch's word pairs are tiled
    against 84-90% of theirs.

    Measured is not the same as better, and it was worth checking before
    believing: against the hand-timed files in ./lyrics its word ends land
    0.213s out where the tiled sources land 0.075s out. A hand-timed lyric is
    itself about three quarters tiled, so the invented end is closer to what
    somebody would write than the real one is. The ends are kept because they
    are this document's own; nothing else is built on them.

    A gap also ends a WORD, which is what tells the two apart where richsync
    is letter-by-letter rather than word-by-word: two tokens with no space
    between them are one word, however the line was cut.

    Where the gap is stamped at the word's OWN offset the measurement says the
    word stopped the instant it started, which is not a short word but a
    missing reading, and the view draws it as a word that never lights at all.
    They are left standing here and repaired in _mxm_spans, which can see the
    whole document and so can see how long a word of this one runs for.
    """
    ts, te = float(row.get("ts") or 0.0), float(row.get("te") or 0.0)
    out, gap = [], None
    for w in row.get("l") or []:
        text = str(w.get("c") or "")
        at = ts + float(w.get("o") or 0.0)
        if not text.strip():
            gap = at if gap is None else gap
            continue
        if out:
            out[-1]["EndTime"] = max(out[-1]["StartTime"],
                                     gap if gap is not None else at)
            out[-1]["IsPartOfWord"] = gap is None
        out.append({"Text": text, "StartTime": at, "EndTime": at,
                    "IsPartOfWord": False})
        gap = None
    if not out:
        return []
    out[-1]["EndTime"] = max(out[-1]["StartTime"], te)
    for a, b in zip(out, out[1:]):
        a["EndTime"] = min(max(a["EndTime"], a["StartTime"]), b["StartTime"])
    return out


def _mxm_spans(out: list) -> None:
    """Musixmatch's word ends, made ends a reader can see.

    Two passes, because there are two things wrong with them.

    First, a word whose end is its own start never lights at all, and richsync
    writes a good many: 29 across the eight tracks measured here, 27 of them
    the last word of their line, where it ends the line exactly where that word
    begins. Nothing can be read off a reading like that, so the word is given
    the LENGTH of the words beside it -- the median of its own line's timed
    words, which tracks a verse sung faster than its chorus, and the whole
    document's median where a line has none to offer. Clamped to the next
    onset, so the repair is never the longest word on the line.

    Then the gaps. Musixmatch stops a word where the singing stops rather than
    running it to the next one -- only 0-4% of its pairs meet end to end -- and
    at the scale a lyric is read at, a tenth of a second of dead air in the
    middle of a phrase reads as the word cutting out, not as phrasing. So a gap
    shorter than MXM_GAP is closed onto the next word's start, and one longer
    than that is left standing, because at that length it is a rest somebody
    actually took. This is what makes the first pass show: without it a
    repaired word ends a fifth of a second before the next begins and still
    looks like it stopped dead.
    """
    every = sorted(y["EndTime"] - y["StartTime"] for it in out
                   for y in (it["Lead"]["Syllables"] or [])
                   if y["EndTime"] - y["StartTime"] > MXM_STOP)
    if not every:
        return
    usual = every[len(every) // 2]
    for i, it in enumerate(out):
        syls = it["Lead"]["Syllables"] or []
        mine = sorted(y["EndTime"] - y["StartTime"] for y in syls
                      if y["EndTime"] - y["StartTime"] > MXM_STOP)
        span = mine[len(mine) // 2] if mine else usual
        for j, y in enumerate(syls):
            if y["EndTime"] - y["StartTime"] > MXM_STOP:
                continue
            if j + 1 < len(syls):
                room = syls[j + 1]["StartTime"]
            elif i + 1 < len(out):
                after = out[i + 1]["Lead"]["Syllables"] or []
                room = after[0]["StartTime"] if after else out[i + 1]["StartTime"]
            else:
                room = it["EndTime"]
            end = y["StartTime"] + span
            if isinstance(room, (int, float)) and room > y["StartTime"]:
                end = min(end, room)
            y["EndTime"] = max(y["EndTime"], end)
    flat = [y for it in out for y in (it["Lead"]["Syllables"] or [])]
    for a, b in zip(flat, flat[1:]):
        if 0.0 < b["StartTime"] - a["EndTime"] < MXM_GAP:
            a["EndTime"] = b["StartTime"]
    for it in out:
        syls = it["Lead"]["Syllables"] or []
        if not syls:
            continue
        last = syls[-1]["EndTime"]
        it["Lead"]["EndTime"] = max(it["Lead"].get("EndTime") or last, last)
        it["EndTime"] = max(it.get("EndTime") or last, last)


def _mxm_rich(body: str) -> dict | None:
    """richsync_body -> the document shape timeline() reads."""
    try:
        rows = json.loads(body)
    except Exception:                                    # noqa: BLE001
        return None
    out = []
    for row in rows if isinstance(rows, list) else []:
        syls = _mxm_syllables(row) if isinstance(row, dict) else []
        if not syls:
            continue
        at = syls[0]["StartTime"]
        end = max(float(row.get("te") or at), syls[-1]["EndTime"])
        out.append({"Text": str(row.get("x") or "").strip()
                            or SL.syllables_text(syls),
                    "StartTime": at, "EndTime": end,
                    "Lead": {"Syllables": syls, "StartTime": at, "EndTime": end}})
    _mxm_spans(out)
    if not out or _instrumental(out):
        return None
    doc = {"Type": "Syllable", "Content": _destamp(out),
           "HasTransliterations": any(SL.SCRIPTED.search(i["Text"]) for i in out)}
    cut = sum(1 for i in out if len(i["Lead"]["Syllables"]) > 1)
    return doc if cut > WORDED_SHARE * len(out) else _deword(doc)


def _mxm_body(calls: dict, which: str) -> dict:
    """One of the macro's answers, or {} where that call did not land.

    Six calls come back in the one envelope and any of them can have failed on
    its own -- userblob.get 404s on every track measured here -- so each is
    read through its own status rather than the macro's.
    """
    got = (calls or {}).get(which) or {}
    body = (got.get("message") or {}).get("body")
    if _mxm_code(got.get("message")) != 200 or not isinstance(body, dict):
        return {}
    return body


def _mxm_key(tid: str, meta: dict) -> tuple:
    """The memo key one track's Musixmatch answer is filed under."""
    return ("mxm", tid, _norm(meta.get("title") or ""),
            _norm(meta.get("artist") or ""),
            round(float(meta.get("length") or 0)))


_MXM_EXPLICIT: dict = {}


def from_musixmatch(tid: str, meta: dict, local=None) -> dict | None:
    """Musixmatch, asked once per track however many callers want it."""
    return _once(_mxm_key(tid, meta), lambda: _musixmatch(tid, meta))


def mxm_explicit(tid: str, meta: dict) -> str:
    """Musixmatch's word on whether this RECORDING is explicit.

    "explicit", "clean", or "" for no answer -- and "" is the common case, so
    nothing may read silence as either one.

    Worth more than a catalogue search because of how the ask is addressed:
    `_mxm_ask` sends `track_spotify_id`, so what comes back is the row for the
    very track the player has open rather than for the song in general, and a
    clean edit and an explicit master are two different tracks with two
    different ids. Where the id misses and the name query answers instead, the
    row is about the song and the flag is worth less -- but a name match that
    lands on the wrong master is already the thing every mask rule here is
    written to survive.

    Second to the player's own flag, not first: where Spotify itself has
    answered, nothing was searched for and nothing can have been mismatched.
    This is what the transports that hand over no flag fall back on.

    Costs no request of its own: this is the same answer `from_musixmatch`
    fetches, memoised, and Musixmatch is the first donor uncensoring asks
    anyway. See UNMASK_FROM.
    """
    key = _mxm_key(tid, meta)
    if key not in _MXM_EXPLICIT:
        from_musixmatch(tid, meta)
    got = _MXM_EXPLICIT.get(key)
    return "" if got is None else ("explicit" if got else "clean")


def _musixmatch(tid: str, meta: dict) -> dict | None:
    """Musixmatch's own door, and no other.

    Ranked where Musixmatch already was, next to last, and that is where it
    belongs rather than where its word timing would put it. Over the 46 songs
    with a hand-timed file here, 32 come back word-timed against none at all
    through the scrape -- but on the 22 that a blend also word-times, the
    blend is the closer document on 20: 4% of its words more than half a
    second out of step with their own song against 20% of these. fallback()
    lets quality outrank order but only between different qualities, so the
    blends keep every one of those.

    What it is for is the songs nobody above it has word-timed at all. It
    wins the chain once over those 46 -- they are the songs somebody cared
    enough about to hand-time, so they are the well-covered ones -- and four
    times over 40 tracks taken at random from this library. Two of those four
    turn a line-synced song word-synced (wifiskeleton's "isnt it obvious",
    DAMAG3's "SHOULD i STAY?"), and the one over the 46 is xaviersobased'
    "love hate", whose words land 1% out. The other two take a song off
    `local`, which is what a machine alignment sitting last is for.

    The LyricsPlus scrape used to stand behind this one -- it needed no token
    and it answered for tracks the macro cannot match -- and what it brought
    was line-level, from a source that sat next to last precisely because
    its line-level copy was not worth much. Ten seconds of the walk, inside
    the round the blends wait on, for a document ranked below almost
    everything that had already answered. That source is gone altogether now.
    """
    token = _mxm_token()
    msg = _mxm_ask(tid, meta, token) if token else None
    if _mxm_code(msg) == 401:
        token = _mxm_token(force=True)
        msg = _mxm_ask(tid, meta, token) if token else None
    calls = ((msg or {}).get("body") or {}).get("macro_calls") \
        if isinstance((msg or {}).get("body"), dict) else None
    if calls:
        track = _mxm_body(calls, "matcher.track.get").get("track") or {}
        if track.get("track_id") and track.get("explicit") is not None:
            with _ONCE_LOCK:
                for gone in [k for k in _MXM_EXPLICIT if k not in _ONCE]:
                    _MXM_EXPLICIT.pop(gone, None)
                _MXM_EXPLICIT[_mxm_key(tid, meta)] = int(track["explicit"] or 0)
    return _mxm_doc(calls) if calls else None


def _mxm_doc(calls: dict) -> dict | None:
    """The best of what one macro answer holds."""
    track = _mxm_body(calls, "matcher.track.get").get("track") or {}
    if not track.get("track_id") or track.get("instrumental") \
            or track.get("restricted"):
        return None
    rich = _mxm_body(calls, "track.richsync.get").get("richsync") or {}
    listed = _mxm_body(calls, "track.subtitles.get").get("subtitle_list") or []
    sub = (listed[0] or {}).get("subtitle") or {} if listed else {}
    words = _mxm_body(calls, "track.lyrics.get").get("lyrics") or {}
    doc = None
    if rich.get("richsync_body") and not rich.get("restricted"):
        doc = _mxm_rich(rich["richsync_body"])
    if doc is None or quality(doc) != "syllable":
        lrc = "" if sub.get("restricted") else str(sub.get("subtitle_body") or "")
        plain = "" if words.get("restricted") else str(words.get("lyrics_body") or "")
        other = parse_lrc(lrc, plain)
        rank = lambda d: RANK.get(quality(d), 0) if d else 0     # noqa: E731
        if other is not None and rank(other) >= rank(doc):
            doc = other
    if doc is None:
        return None
    lang = (rich.get("richssync_language") or rich.get("richsync_language")
            or sub.get("subtitle_language") or words.get("lyrics_language"))
    if lang:
        doc["Language"] = str(lang)
    wrote = _mxm_writers(rich, sub, words)
    if wrote:
        doc["SongWriters"] = wrote
    return doc


def _mxm_writers(*bodies) -> list[str]:
    """Songwriters, out of whichever copyright line came back with the words.

    Musixmatch has a writer_list field and leaves it empty; what it fills in
    is the copyright line -- "Writer(s): Joseph Hahn, Chester Charles
    Bennington, ..." -- so that is where they are read from, the same way
    NetEase's are read out of its credit lines.
    """
    for body in bodies:
        m = MXM_WROTE.search(str((body or {}).get("lyrics_copyright") or ""))
        if not m:
            continue
        out, seen = [], set()
        for name in re.split(r"\s*[/,、，&]\s*", m.group(1)):
            name = name.strip().rstrip(".")
            if name and len(name) > 1 and name.lower() not in seen:
                seen.add(name.lower())
                out.append(name)
        if out:
            return out
    return []


# --------------------------------------------------------------------------
GENIUS_CONFIG = "gui.json"
GENIUS_KEY = "genius_token"


def genius_token() -> str:
    """The Genius token, read out of the player's own settings file.

    Read here rather than handed in, because a provider is given a track and
    nothing else, and this is the only one of them that needs a credential
    belonging to the user. The backup is read as well: the player rotates
    gui.json to gui.json.bak on every write, so a token that is only in the
    older of the two is still the token this machine has. caches.credentials
    reads the same two files, and for the same reason.
    """
    live = config_root() / GENIUS_CONFIG
    for path in (live, live.with_suffix(".json.bak")):
        try:
            got = str((json.loads(path.read_text(encoding="utf-8")) or {})
                      .get(GENIUS_KEY) or "").strip()
        except Exception:
            continue
        if got:
            return got
    return ""


def from_genius(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """Genius' words, with nothing timed.

    The only source here that can never answer better than "static", which
    settles where it goes and most of what it does. Quality outranks order
    in both directions, so it cannot take a song off anything that came back
    timed however anybody ranks the list, and it loses a tie with another
    untimed document to whoever is above it -- which is everybody. What is
    left is the songs the rest of them have never heard of, and Genius is
    very good at those: it is edited by people who are listening to the
    song, rather than filed from a label's delivery. A lyric on the screen
    with no clock under it is worth having over the notice that says nobody
    has this one.

    It is also the text the local aligner has always taken its words from,
    which until now was the only way any of this reached the screen: the
    aligner had to find a copy of the audio and spend minutes on a GPU
    before Genius could say a word. This is the same document, offered
    directly, on the songs where that never happens.

    The search needs the user's own token and there is no anonymous door on
    it, so with none typed in this answers nothing rather than spending four
    queries and three retries each on a 401. That is a source switched on
    and silent, which is the honest reading -- Genius is not reachable
    without it.
    """
    if not (meta.get("title") or "").strip():
        return None
    token = genius_token()
    if not token:
        return None
    return _once(("genius", _norm(meta.get("title") or ""),
                  _norm(meta.get("artist") or "")),
                 lambda: _genius(token, meta))


from_genius.wants_above = True
from_genius.untimed = True


def _genius(token: str, meta: dict) -> dict | None:
    """One ask.

    This one used to file nothing when the network failed, unlike every other
    provider here: local_align.genius_doc catches its own exceptions and
    answers None, so a Genius outage and a song Genius has not got arrived
    looking exactly alike and the only one of the two worth reporting went
    unreported. It says which now -- `genius_doc.last_error` is empty on a
    miss and carries the reason on a shut door -- so the notification can name
    Genius the way it names everybody else.

    local_align is imported here rather than at the top of the file because
    it imports this module; by the time anybody reaches a provider both are
    loaded and the lazy import costs a dict lookup.
    """
    import local_align as LA

    try:
        doc = LA.genius_doc(token, meta, timeout=TIMEOUT)
    except Exception as exc:                             # noqa: BLE001
        _blamed(_why(exc))
        return None
    if not isinstance(doc, dict):
        if LA.genius_doc.last_error:
            _blamed(LA.genius_doc.last_error)
        return None
    return {k: v for k, v in doc.items() if k != "_timing"}


SRC_PARTS = {"spicy": ["spicy"], "apple": ["bini"], "amll": ["amll"],
             "unison": ["unison"], "qq": ["qq"],
             "netease": ["netease"], "kugou": ["kugou"], "mxm": ["mxm"],
             "lrclib": ["lrclib"], "local": ["local"],
             "genius": ["genius"]}
BLENDS = {"blend": ("apple", "qq"), "kublend": ("apple", "kugou"),
          "neblend": ("apple", "netease"),
          "triblend": ("apple", "netease", "qq"),
          "kutriblend": ("apple", "netease", "kugou")}
BLEND_OF = "apple"
BLEND_KEY = {"blend": "blend_qq", "kublend": "blend_kugou",
             "neblend": "blend_netease", "triblend": "blend_ne_qq",
             "kutriblend": "blend_ne_kugou"}
PROVIDER_SRC = {p: n for n, parts in SRC_PARTS.items() for p in parts}
PROVIDER_SRC.update({b: BLEND_OF for b in BLENDS})
WAS_SRC = {"bini": "apple", "blend": "apple",
           "kublend": "apple", "neblend": "apple", "triblend": "apple"}


SOURCES = ["spicy", "apple", "amll", "unison", "netease",
           "kugou", "qq", "lrclib", "mxm", "local", "genius"]


def blend_rank(order: list, name: str) -> tuple:
    """Where a blend sits, read off the user's ranking of its donors.

    There is no second list to keep in step. A blend is Apple's lines with
    somebody else's clock under them, and "somebody else" is a source already
    standing in an order the user wrote; so that order decides this one too.

    The TIMING donor decides, not the best-ranked of all of them, because the
    timing donor is whose word timing this actually is. Keying on the best
    instead would hand a user who ranked QQ Music first a NetEase-timed
    document, on the strength of the QQ that only fills its gaps.

    A blend carrying a filler goes ahead of the same blend without one -- it
    can only cover more of the song -- and the filler breaks what is left of
    the tie. BLEND_OF is deliberately not read: it is in every tuple, so
    counting it would make every blend tie whenever Apple outranks all the
    donors, which is most of the time.
    """
    uses = [u for u in BLENDS[name] if u != BLEND_OF]
    at = [order.index(u) if u in order else len(order) for u in uses]
    return (at[0], -len(at), at[1:])


def blend_order(order: list) -> list:
    """Every blend, in the order that ranking puts them in."""
    return sorted(BLENDS, key=lambda b: blend_rank(order, b))


def provider_order(order: list, on, blend_on=None) -> list:
    """The providers to consult, in the order the SOURCES were ranked.

    The chain speaks in providers and there are more of them than there are
    sources: two doors on Apple Music, and five blends that put Apple's words
    on somebody else's clock. Each source expands to the providers that answer
    for it, in its own place in the order, so moving Apple Music up the list
    moves everything that speaks for Apple Music with it.

    A BLEND GOES IMMEDIATELY ABOVE THE HIGHEST-RANKED SOURCE IT BORROWS FROM
    -- Apple+NetEase above NetEase, Apple+Kugou above Kugou, the three-way
    above whichever of NetEase and QQ Music the user put first. Above all of
    its donors, because it is those donors' clock plus something they have
    not got; below everything that is not one of them, because a document
    built out of two sources cannot claim a place in front of a third that
    lent it nothing.

    They used to go in at Apple Music's own slot, ahead of Apple's document,
    on the grounds that they are Apple's lines with word timing added. But
    that slot is usually second, so a blend of two sources ranked sixth and
    eighth arrived in front of amll and Unison, and beat both on a tie -- for
    a clock the user had ranked below them. Where the
    blend really is the better document it still wins: quality outranks
    order in fallback(), and a blend exists precisely to be word-timed where
    its base is not.

    The move pays for itself twice over in requests. `above` -- what the
    round before found -- now reaches a blend with Apple's own document
    already in it, so _blended takes its base from there instead of going
    back out for a copy of what BiniLyrics has already handed over.

    Among themselves they go in donor order -- they used to go in the order
    this file happens to declare them, which put QQ Music first and, since
    fallback() keeps the FIRST of two equally good answers, meant
    Apple+NetEase won once in 1547 cached walks on the machine this was
    written on. Not because it was worse. Because it was asked fourth.
    """
    blend_on = blend_on or (lambda _b: True)
    live = [b for b in blend_order(order)
            if blend_on(b) and all(on(u) for u in BLENDS[b])]
    homes: dict[str, list] = {}
    for b in live:
        donors = [u for u in BLENDS[b] if u != BLEND_OF and u in order]
        home = min(donors, key=order.index) if donors else BLEND_OF
        homes.setdefault(home, []).append(b)
    out = []
    for name in order:
        if not on(name):
            continue
        out += homes.get(name, [])
        out += SRC_PARTS.get(name, [])
    return out


def carried(order: list) -> list:
    """A saved running order, with the sources it predates put where they go.

    A source this program gained after somebody last wrote their order is not
    one they ranked anywhere -- it is one they have never seen. Appending it
    files it below LRCLIB and the machine's own alignments, which is the slot
    kept for a last resort, so a source added near the top of SOURCES would
    arrive switched on and never win a song.

    Each unseen name goes in behind whichever source precedes it in SOURCES
    and the reader actually has, so it lands among the neighbours it was
    ranked with while every source they did order stays exactly where they
    left it. A hand-written --src-order is deliberately not run through this:
    a list typed out means what it says, and its unlisted names keep their
    documented place at the end.
    """
    out = [n for n in order if n in SOURCES]
    for name in SOURCES:
        if name in out:
            continue
        at = len(out)
        for prev in reversed(SOURCES[:SOURCES.index(name)]):
            if prev in out:
                at = out.index(prev) + 1
                break
        out.insert(at, name)
    return out


def lrclib_first(order: list) -> list:
    """A saved order with Musixmatch put back behind LRCLIB.

    The default used to ship them the other way round, and a stored order is
    a copy of whatever the default was on the day it was written -- so every
    settings file older than this change still ranks Musixmatch first, and
    changing SOURCES alone would give the new order to new installs and to
    nobody else.

    ONLY WHERE THEY ARE STILL SIDE BY SIDE in that order, which is the one
    arrangement nobody can have asked for: moving either of them anywhere at
    all breaks the adjacency, and a reader who did move them keeps exactly
    what they moved. What is left is the shipped default, untouched, which is
    the thing being changed.
    """
    out = list(order)
    for i in range(len(out) - 1):
        if out[i] == "mxm" and out[i + 1] == "lrclib":
            out[i], out[i + 1] = out[i + 1], out[i]
            break
    return out


# --------------------------------------------------------------------------
def people_of(v) -> list[dict]:
    """A credit slot as the people in it: a name each, and an id where there is one.

    Spicy Lyrics writes Maker and Uploader as one {id, username, avatar}
    object each, and its own UI reads them that way. But a sync can have more
    than one author, and the day the field grows into a list is not a day this
    should quietly show nothing -- so an object, a list of them, and a bare
    name are all read the same. An empty {} is how "nobody is credited here"
    is spelled, and comes back as nobody rather than as a blank name.

    THE ID IS THE POINT OF THIS SHAPE. A Spicy Lyrics display name is the
    person's to change whenever they like, and a roster that knew them only
    by the name they had last month quietly stops refusing -- or preferring --
    the very person it was written about. The id underneath it does not move,
    so it is carried alongside the name from here to the roster and back out
    to the settings file. Only Spicy Lyrics publishes one; everybody else
    here credits a bare name, which is why the name still matches on its own.

    The `url` rides along for the same reason and is put to a different use:
    it is the contributor's own page, and the terms this API is used under ask
    that a community credit LINK to it rather than merely name it. Absent for
    everybody who does not publish one, which is everybody but Spicy Lyrics,
    and an empty one means "do not draw a link" rather than "draw a dead one".
    """
    if isinstance(v, (dict, str)):
        v = [v]
    out: list[dict] = []
    for one in v if isinstance(v, list) else []:
        if isinstance(one, dict):
            name = str(one.get("username") or one.get("name") or "").strip()
            uid = str(one.get("id") or "").strip()
            url = str(one.get("url") or "").strip()
        else:
            name, uid, url = str(one or "").strip(), "", ""
        if not name and not uid:
            continue
        got = {"name": name, "id": uid, "url": url}
        if not any(same_person(got, had) for had in out):
            out.append(got)
    return out


def people(v) -> list[str]:
    """The same slot as bare names, for everything that only prints them."""
    return [p["name"] for p in people_of(v) if p["name"]]


def credits_of(body) -> list[dict]:
    """Everybody a document credits with its TIMING, best claim first.

    Four conventions, because four sources carry the fact at all and none of
    them agreed on where to put it: Spicy Lyrics files Maker and Uploader in
    TTMLUploadMetadata, amll and a dropped TTML arrive through _credits as
    `_maker`, Unison names its submitter in the record rather than the TTML
    (see _unison_doc), and a file written by this program's own editor spells
    it SyncedBy.

    Not the SONGWRITERS, which is the other credit a document carries and a
    question about the song rather than about this copy of it. Refusing
    somebody's syncs is not refusing to listen to what they wrote.

    Maker before Uploader for the same reason lyrics_gui.made_by prints them
    that way: where both are named they are two different people, and the
    first of them is the one whose timing this is.
    """
    doc = SL.payload(body or {})
    meta = doc.get("TTMLUploadMetadata")
    meta = meta if isinstance(meta, dict) else {}
    out: list[dict] = []
    for slot in (meta.get("Maker"), meta.get("Uploader"),
                 doc.get("_maker"), doc.get("SyncedBy")):
        for one in people_of(slot):
            if not any(same_person(one, had) for had in out):
                out.append(one)
    return out


def credited(body) -> list[str]:
    """The same credits as bare names, best claim first."""
    return [c["name"] for c in credits_of(body) if c["name"]]


def whose(name: str) -> str:
    """One credited name, as it is compared.

    Case and spacing are noise -- the same person is "Kiri", "kiri" and
    " Kiri " depending on which of the four conventions above carried them --
    and a GitHub login typed the way it is written everywhere else, with an @
    on the front, is the same login without it.
    """
    return re.sub(r"\s+", " ", str(name or "").strip().lstrip("@")).casefold()


def keys_of(who) -> frozenset:
    """The handles one person can be recognised by, for hashing a question by.

    Two at most: the id Spicy Lyrics filed them under, and their name. Not
    the comparison itself -- see same_person, which knows that one of the two
    outranks the other. This is what Roster.key is built out of, where all
    that is wanted is a value that moves when the question moves.
    """
    if not isinstance(who, dict):
        who = {"name": str(who or ""), "id": ""}
    out = set()
    uid = str(who.get("id") or "").strip()
    if uid:
        out.add("#" + uid.casefold())
    key = whose(who.get("name"))
    if key:
        out.add(key)
    return frozenset(out)


def _uid(who) -> str:
    """One person's stable id, casefolded, or "" where there is none."""
    if not isinstance(who, dict):
        return ""
    return str(who.get("id") or "").strip().casefold()


def same_person(a, b) -> bool:
    """Whether two credits, or a credit and a list entry, are one person.

    THE ID DECIDES WHEREVER BOTH SIDES HAVE ONE. It is the only thing here
    that holds still: a Spicy Lyrics display name is the person's to change
    whenever they like, so a roster that knew them only by last month's
    spelling stops refusing them at the moment they are hardest to recognise,
    and two different ids under one name are two different people however the
    name reads today.

    Where either side has no id the name is all there is, and it is enough.
    An id is Spicy Lyrics' own: the same person's syncs on amll-ttml-db
    or Unison arrive with a bare name and nothing else, and so
    does every entry anybody types into the settings row. Matching those on
    the name is exactly what this did before there were ids at all -- and it
    is what lets an entry written from under one lyric go on recognising the
    same person on a database that has never heard of Spicy Lyrics.
    """
    one, two = _uid(a), _uid(b)
    if one and two:
        return one == two
    left, right = whose(a.get("name") if isinstance(a, dict) else a), \
        whose(b.get("name") if isinstance(b, dict) else b)
    return bool(left) and left == right


def person_list(raw) -> list[dict]:
    """One of the two lists, however it was stored, typed or passed.

    Three shapes reach this. A list of {name, id} is what the app writes now.
    A plain string is what it wrote before, what `--skip-people` hands over,
    and what somebody editing gui.json by hand will type -- commas, because
    these are usernames and a username can contain a space: splitting on
    whitespace would make two people out of "Jane Remover". A list of bare
    strings is the same thing already split.

    An entry with an id but no name is kept: it is somebody who was refused
    and has since renamed themselves, and dropping it for having no name to
    show would be undoing the refusal at the moment it starts to matter.
    """
    if isinstance(raw, (dict, str)) or raw is None:
        raw = str(raw or "").split(",") if not isinstance(raw, dict) else [raw]
    out: list[dict] = []
    for one in raw if isinstance(raw, (list, tuple)) else []:
        if isinstance(one, dict):
            name = str(one.get("name") or one.get("username") or "").strip()
            uid = str(one.get("id") or "").strip()
        else:
            name, uid = str(one or "").strip(), ""
        name = re.sub(r"\s+", " ", name)
        if not name and not uid:
            continue
        got = {"name": name, "id": uid}
        if not any(same_person(got, had) for had in out):
            out.append(got)
    return out


def name_list(raw) -> list[str]:
    """The same list as the names in it, as typed, with the empties dropped."""
    return [p["name"] for p in person_list(raw) if p["name"]]


def with_ids(want, had) -> list[dict]:
    """`want` as it was typed, wearing the ids the list it replaces already knew.

    The settings row is a line of text and always will be: names are what a
    person reads under a lyric and what they can sensibly type. So a list
    edited there comes back as names alone, and every id the app had learned
    would be thrown away by the one person who was doing nothing but fixing a
    spelling.

    Matched by name, which is all the typed side has. A name that was not on
    the list before is a new person and keeps the nothing it arrived with.
    """
    knew = {whose(p["name"]): p["id"] for p in person_list(had)
            if p["id"] and whose(p["name"])}
    out = []
    for one in person_list(want):
        uid = one["id"] or knew.get(whose(one["name"]), "")
        out.append({"name": one["name"], "id": uid})
    return out


class Roster:
    """Whose syncs to refuse, and whose to take whatever the order says.

    Two lists of people, both usually empty, applied to documents rather than
    to sources -- so they go on meaning what they said when the person posts
    their next sync to a different database, and, because each name is kept
    beside the id it was read off, when the person renames themselves. See
    keys_of.

    SKIP drops the document outright: it is not shown, not handed to a blend
    as a base, and not counted when the walk decides whether anybody better
    has answered. The source itself is untouched, which is the point -- one
    contributor's syncs on Spicy Lyrics are not Spicy Lyrics.

    PICK wins a tie against everybody, however the sources are ranked. That
    is the whole of what it does, and the limit is deliberate: quality still
    outranks order here as it does everywhere else in this walk, so a name on
    this list cannot put a line-timed document on screen over a word-timed
    one. What it settles is the case the user actually described -- two
    documents that are as good as each other, one of them by somebody whose
    work they trust, sitting on a source they ranked below.

    A skip beats a pick where a document credits one of each -- a sync made
    by somebody on the skip list and uploaded by somebody on the pick list is
    still that first person's timing.
    """

    __slots__ = ("skip", "pick", "skip_people", "pick_people")

    def __init__(self, skip=(), pick=()) -> None:
        self.skip_people = person_list(skip)
        self.pick_people = [p for p in person_list(pick)
                            if not any(same_person(p, q) for q in self.skip_people)]
        self.skip = frozenset(k for p in self.skip_people for k in keys_of(p))
        self.pick = frozenset(k for p in self.pick_people for k in keys_of(p))

    def __bool__(self) -> bool:
        return bool(self.skip_people or self.pick_people)

    def blocks(self, body) -> bool:
        """Whether this document is somebody's the user has refused."""
        return bool(self.skip_people) and any(
            same_person(c, p) for c in credits_of(body) for p in self.skip_people)

    def likes(self, body) -> bool:
        """Whether this document is somebody's the user asked for by name."""
        if not self.pick_people or self.blocks(body):
            return False
        return any(same_person(c, p)
                   for c in credits_of(body) for p in self.pick_people)

    def key(self) -> str:
        """The lists as one string, to store beside an answer they shaped.

        A cached answer was picked under whichever roster was in force when
        the walk ran, so the roster is part of the question the cache is
        keyed by -- exactly as `names` and `bar` are (see _store). Without
        this, refusing somebody would go on showing their document for the
        month the old answer lives, and taking them off the list again would
        not bring it back.

        Built from the MATCH KEYS rather than from the names, so learning
        somebody's id -- which happens the first time they are refused from
        under a lyric rather than typed in -- re-asks the question, and a
        rename, which changes nothing about who is refused, does not.

        Empty on an empty roster, which is what every record written before
        this existed carries -- so nobody's cache is thrown away by adding a
        feature they are not using.
        """
        if not self:
            return ""
        return ("-" + ",".join(sorted(self.skip))
                + "+" + ",".join(sorted(self.pick)))


PROVIDERS = [("spicy", from_spicy), ("amll", from_amll), ("blend", from_blend),
             ("kublend", from_kublend), ("neblend", from_neblend),
             ("triblend", from_triblend), ("kutriblend", from_kutriblend),
             ("bini", from_bini), ("unison", from_unison),
             ("qq", from_qq), ("kugou", from_kugou), ("netease", from_netease),
             ("mxm", from_musixmatch),
             ("lrclib", from_lrclib), ("local", from_local),
             ("genius", from_genius)]
from_amll.credits_people = True
from_unison.credits_people = True
from_local.credits_people = True


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
    Both caches go round together: what Spicy Lyrics answered is kept by the
    same rule, in its own directory for its own reasons (see SPICY_DIR), and
    two sweeps on two clocks would be two things to remember.
    """
    stamp = CACHE_DIR / ".swept"
    now = time.time()
    if not force:
        try:
            if now - stamp.stat().st_mtime < SWEEP_EVERY:
                return 0
        except OSError:
            pass
    gone = _sweep_spicy(now)
    if not CACHE_DIR.is_dir():
        return gone
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


def _store(tid: str, doc, source: str, names: list, bar: int,
           people: str = "") -> None:
    """Remember the answer, and what was asked to get it.

    `names` and `bar` are the question, and without them the answer cannot be
    reused safely: a walk that skipped half the providers because Spicy Lyrics
    already had word timing would otherwise be read back as "nobody has
    anything" by a later ask that really did want to know.

    `people` is the rest of the question -- who was being refused and who was
    being preferred while this was decided. Empty for anybody not using
    either list, which is what every record written before them holds, so
    those go on matching.
    """
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(tid).write_text(
            json.dumps({"rev": REVISION, "at": time.time(), "source": source,
                        "names": list(names), "bar": int(bar),
                        "people": str(people or ""), "doc": doc}),
            encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
_ONCE: dict = {}
_ONCE_LOCK = threading.Lock()
ONCE_TTL = 25.0


def _waited(done, limit: float) -> bool:
    """Another caller's answer, waited for -- unless this walk is dropped.

    A flat wait here was the longest single stall in the chain: TIMEOUT * 3,
    spent on an answer for a track the user had already skipped past, while
    the walk for the one they were listening to sat behind it.
    """
    end = time.monotonic() + limit
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return False
        if done.wait(min(0.25, left)):
            return True
        if not _walking():
            return False


def _once(key: tuple, fn):
    """Ask an upstream once, however many things want the answer.

    A walk asks the same servers over and over. With the blends switched on,
    NetEase is fetched three times for one track -- once as itself, once
    under Apple+NetEase, once under the three-way -- and each of those is a
    search and then a lyric fetch, better than a second each. QQ goes the
    same way, three times over between QQ Music itself, Apple+QQ and the
    three-way's filler.

    The second caller waits on the first rather than starting again, so the
    duplicates cost nothing at all rather than costing the same again. Kept
    for ONCE_TTL, which is long enough to cover a walk and its retry and
    short enough that a song still gets a fresh answer when it comes round.

    A copy goes back to each caller. They mutate what they are given --
    peeling ad-libs off lines, folding, re-stamping -- and one caller's edits
    have no business reaching another's document.
    """
    import copy

    now = time.time()
    with _ONCE_LOCK:
        for k, rec in [(k, r) for k, r in _ONCE.items() if now - r["at"] > ONCE_TTL]:
            _ONCE.pop(k, None)
        rec, mine = _ONCE.get(key), False
        if rec is None:
            rec = {"at": now, "done": threading.Event(), "value": None}
            _ONCE[key], mine = rec, True
    if mine:
        try:
            rec["value"] = fn()
        finally:
            rec["done"].set()
            if rec["value"] is None and not _walking():
                with _ONCE_LOCK:
                    if _ONCE.get(key) is rec:
                        _ONCE.pop(key, None)
    elif not _waited(rec["done"], TIMEOUT * 3):
        return fn() if _walking() else None
    got = rec["value"]
    return copy.deepcopy(got) if isinstance(got, dict) else got


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
        except Exception as e:                           # noqa: BLE001
            _blamed(_why(e), k)
            return {k: tell(k, None)}

    from concurrent.futures import ThreadPoolExecutor, as_completed

    alive = getattr(_WALK, "alive", None)
    faults = getattr(_WALK, "faults", None)
    who = getattr(_WALK, "who", "")
    people = getattr(_WALK, "people", None)

    def guard(k, fn):
        try:
            return tell(k, _under(alive, fn, faults, who, people))
        except Exception as e:                           # noqa: BLE001
            _under(alive, lambda: _blamed(_why(e), k), faults, who, people)
            return tell(k, None)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(guard, k, fn): k for k, fn in jobs.items()}
        out = {}
        for f in as_completed(futures):
            out[futures[f]] = f.result()
    return {k: out.get(k) for k in jobs}


ROUND_HOLD = 2.0


class _Fan:
    """Jobs already running, and whatever they have answered so far.

    _parallel is this and then waiting for all of it, which is the right
    shape nearly everywhere: an answer sheet with a row for every provider.
    The walk wants the two apart exactly once. Its second round -- the blends
    and Genius -- reads the first round's answers, and it used to wait for
    every one of them before it started; one slow door then decided when the
    blends began, and the blends are what usually wins.

    So the round can be read EARLY, with the stragglers still out, and the
    stragglers collected afterwards. What that costs is judgement made on a
    partial sheet: a blend may be built that a late word-timed answer would
    have stood down (see _outdone), or may take its lines from the second-best
    base because the best had not landed. Neither is wrong, only wasted --
    the late answer is still collected, still ranked, and still wins the walk
    if it deserves to. What it buys is a chain whose slowest member costs one
    wait rather than deciding the pace of everything after it.
    """

    def __init__(self, pool, futures: dict, order: list) -> None:
        self._pool, self._futures, self._order = pool, futures, order

    def so_far(self, hold: float) -> dict:
        """What has landed within `hold` seconds, waiting no longer than that.

        A dropped walk stops the waiting early, the same way _waited does:
        the answer is nobody's now, and the thread is wanted for the track
        the user did move to.
        """
        from concurrent.futures import wait

        end = time.monotonic() + max(0.0, hold)
        while True:
            left = end - time.monotonic()
            outstanding = [f for f in self._futures if not f.done()]
            if left <= 0 or not outstanding or not _walking():
                break
            wait(outstanding, timeout=min(0.25, left))
        return {self._futures[f]: f.result()
                for f in self._futures if f.done()}

    def all(self) -> dict:
        """Every job, waited out. A row for each, None where nothing came."""
        out = {}
        for f, k in self._futures.items():
            out[k] = f.result()
        self._pool.shutdown(wait=True)
        return {k: out.get(k) for k in self._order}


def _fan(jobs: dict, each=None) -> "_Fan":
    """`jobs` started at once and handed back still running.

    The plumbing is _parallel's -- the same cancel token, the same fault
    sheet, the same refusal to let one thunk's exception cost the others --
    and it is written twice rather than shared because the shape of the two
    differs at the one point that matters: this one does not close the pool,
    so the caller has to (see _Fan.all).
    """
    from concurrent.futures import ThreadPoolExecutor

    def tell(k, v):
        if each is not None:
            try:
                each(k, v)
            except Exception:                            # noqa: BLE001
                pass
        return v

    alive = getattr(_WALK, "alive", None)
    faults = getattr(_WALK, "faults", None)
    who = getattr(_WALK, "who", "")
    people = getattr(_WALK, "people", None)

    def guard(k, fn):
        try:
            return tell(k, _under(alive, fn, faults, who, people))
        except Exception as e:                           # noqa: BLE001
            _under(alive, lambda: _blamed(_why(e), k), faults, who, people)
            return tell(k, None)

    pool = ThreadPoolExecutor(max_workers=max(1, len(jobs)))
    futures = {pool.submit(guard, k, fn): k for k, fn in jobs.items()}
    return _Fan(pool, futures, list(jobs))


def _outdone(name: str, names: list, ahead, got: dict, local) -> bool:
    """Whether somebody ranked in front of a blend's donors has the song
    word-timed already, which is the whole of what a blend was for.

    A blend costs doors of its own -- one for Apple+QQ, two for the three-ways
    -- on top of the ones this walk is already knocking on, and what it buys
    is word timing under lines that had none. Where a source the user put in
    front of its donors came back word-timed, there is nothing left for the
    blend to add that they asked for, so it is not built at all.

    In front of the DONORS, which is now the same stretch as in front of the
    blend: provider_order puts each blend immediately above the highest-ranked
    source it borrows from. It was not always -- the blends used to sit up at
    Apple Music's slot, and reading this the other way would have left out
    Apple's own document, amll and Unison, who sit between Apple Music and QQ
    in the default order and are exactly the sources whose word timing makes a
    blend beside the point. Written this way it stays right either way.

    Spicy Lyrics counts too, judged by `local`, wherever it is in front of the
    donors. It is not a provider in this walk, so that is read off `ahead`
    instead: the donors being ranked above Spicy Lyrics is what puts Spicy
    behind them. Not where the blend itself outranks Spicy Lyrics -- there the
    user has already said which of those two they want, and it is not Spicy.
    """
    uses = [u for u in BLENDS.get(name, ()) if u != BLEND_OF]
    if not uses:
        return False
    at = min([names.index(u) for u in uses if u in names] or [len(names)])
    front = [got.get(n) for n in names[:at]]
    if not any(u in (ahead or ()) for u in uses) and name not in (ahead or ()):
        front.append(local)
    return any(RANK.get(quality(d), 0) >= RANK["syllable"] for d in front if d)


def _beaten_to_it(name: str, above: dict, ahead, bar: int) -> bool:
    """Whether a costly door has already been answered over the top of.

    True when something the user ranked ABOVE it has come back word-timed.
    Word timing is the ceiling of this chain -- the walk stops early on it
    precisely because nothing can beat it -- so a word-timed document from
    higher up the order wins on quality and on order at once, and there is no
    song left for this one to win. Asking anyway buys nothing and costs the
    whole of its wait.

    ABOVE it, not merely anywhere, and that is the whole care taken here. A
    word-timed answer from a source the user ranked BELOW this one does not
    stand it down: they said which of those two they would rather have, and
    quietly taking the other because it happened to be quicker is the one
    thing this walk has always refused to do. On a song nobody else has
    word-timed, the door is knocked on exactly as before.

    Spicy Lyrics is read off `bar` rather than out of `above`, because it is
    not a provider in this walk -- the player already holds its document. It
    counts as being above unless the caller ranked this source above it,
    which is what `ahead` names. Same reading as `_outdone`.
    """
    best = max([RANK.get(quality(d), 0) for d in above.values() if d] or [0])
    if name not in (ahead or ()):
        best = max(best, bar)
    return best >= RANK["syllable"]


def _answered_already(above: dict, bar: int) -> bool:
    """Whether an untimed source has anything left it could answer for.

    Named apart from `_spoken_for`, which is a different question about a
    different thing -- whether a line already writes an ad-lib into its own
    text -- and which this used to be called as well. Two module-level
    functions of one name is one function: the later definition wins, so
    _lift_strays was calling THIS with (text, line) and raising
    AttributeError, and since a provider that raises is passed over in
    silence, the Apple+QQ blend simply never appeared on any song whose
    ad-libs needed lifting. Skillet's "You Ain't Ready" is one of them.

    Genius is the only one, and this is why it waits for a second round
    rather than going out with the rest of the walk. Every other provider
    here is a request or two against a database; Genius is four searches and
    a page fetch, on a token that is the user's own and rate-limited to
    their account -- and with the look-ahead warming three tracks in front
    of the one playing, asking it for every song would spend twenty requests
    per track change to answer the handful where anybody needed it.

    Nothing is lost by waiting, because there is no song an untimed document
    can win off a source that answered. It ties with another untimed one and
    loses the tie on order, since it sits below them all; against anything
    line-timed or better it is not close. So a single answer from the round
    before -- ANY answer, however poor its timing -- settles it.

    `bar` is what the caller already holds, which is usually Spicy Lyrics.
    Read as the walk itself reads it rather than off the `local` document,
    because the two are not always the same question: eval_sources hands a
    provider Spicy's copy to build on while asking it what it has of its
    own, and reading the document there would have this answer nothing on
    every song Spicy has -- which is the opposite of what was asked.

    A bar of "static" does not stand it down. That is a tie, and a tie goes
    to whoever the user ranked first; `ahead` is what decides it and the pick
    does that later. Spicy Lyrics is line-timed or better on very nearly
    everything it has, so the case is rare and asking is what makes it right.
    """
    if any(RANK.get(quality(d), 0) >= RANK["static"] for d in above.values() if d):
        return True
    return bar >= RANK["line"]


def _gather(known: dict, names: list, tid: str, meta: dict, local=None,
            each=None, ahead=(), bar: int = 0, rule=None) -> dict:
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

    A blend whose donors are outranked by a word-timed answer is not asked at
    all -- see _outdone. That is decided here rather than inside the blend
    because it is the point of the second round: by now the first round has
    said who has the song, and the blend has not yet spent a request. An
    untimed source -- Genius -- is stood down on the same grounds and by the
    same reasoning, one rung lower down: see _answered_already.

    THE SECOND ROUND DOES NOT WAIT FOR THE WHOLE OF THE FIRST. It waits
    ROUND_HOLD and then reads what has landed. The first round is nine or ten
    doors wide and all but one of them answer inside two seconds; the odd one
    out takes ten, and while the round was a barrier it was that one door that
    decided when the blends started -- which is to say when the answer that
    usually wins was ready. The stragglers keep running, are collected below,
    and are ranked in the usual way by whoever called this.

    What a partial sheet costs is judgement, not correctness: a blend may be
    built that a late word-timed answer would have stood down, or may take
    its base from the best document that had landed rather than the best there
    was. Both are waste rather than error -- and the blends do not race their
    own donors, because a donor still in flight is one the blend joins inside
    _once rather than fetches again.

    Genius is the exception to the exception. It is untimed, so there is no
    song it can win off anybody who answered, and asking it costs the user's
    own rate-limited token -- so it is worth the full wait to find out whether
    it was needed at all. It is decided on the complete first round.
    """
    later = [n for n in names if getattr(known[n], "wants_above", False)]
    first = [n for n in names if n not in later]
    jobs = {n: (lambda fn=known[n], n=n:
                _asks(n, lambda: fn(tid, meta, local=local)))
            for n in first}
    if not later:
        return _parallel(jobs, each)
    fan = _fan(jobs, each)

    def second(who: list, got: dict) -> dict:
        """The ones of `who` still worth asking, given `got`.

        A refused document is not in `got` as far as this round is concerned.
        It cannot be handed to a blend as a base -- ignoring somebody's sync
        and then reading their lines under a borrowed clock is not what
        refusing them meant -- and it cannot stand a blend or Genius down
        either, which would be the same document deciding the round without
        appearing in it.
        """
        if rule:
            got = {k: v for k, v in got.items() if not rule.blocks(v)}
        out = {}
        for n in who:
            if _outdone(n, names, ahead, got, local):
                continue
            above = {k: got[k] for k in names[:names.index(n)] if got.get(k)}
            if getattr(known[n], "untimed", False) and _answered_already(above, bar):
                continue
            if getattr(known[n], "costly", False) and _beaten_to_it(
                    n, above, ahead, bar):
                continue
            out[n] = (lambda fn=known[n], above=above, n=n:
                      _asks(n, lambda: fn(tid, meta, local=local, above=above)))
        return out

    timed = [n for n in later if not getattr(known[n], "untimed", False)]
    untimed = [n for n in later if n not in timed]
    early = fan.so_far(ROUND_HOLD) if _walking() else {}
    now = second(timed, early) if timed and _walking() else {}
    blends = _fan(now, each) if now else None
    got = fan.all()
    if untimed and _walking():
        got.update(_parallel(second(untimed, got), each))
    if blends is not None:
        got.update(blends.all())
    return got



def fallback(tid: str, meta: dict, have: str, enabled=None, force: bool = False,
             order=None, ahead=(), local=None, report=None, alive=None,
             note=None, people=None):
    """Best document the chain can offer, or None to keep what we already have.

    `alive` is asked, from every thread the walk reaches, whether anybody
    still wants the answer. Left off nobody is asked and the walk finishes
    what it started, which is what a caller with somewhere to put the answer
    wants. A player is not one: it asks for whatever is playing, and what is
    playing changes under it. See _walking.

    A no there is final, whatever the caller's own predicate answers next:
    see _latched, and the stored second-best answer that was written because
    it was not.

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

    `people` is a Roster: whose syncs to refuse whatever source they turn up
    on, and whose to prefer whatever the order says. It is asked about
    documents rather than providers, and it is part of the cache key, since
    an answer picked under one is not the answer another would have picked.

    `note` is told what went wrong, as [(provider, why), ...], once the walk
    is over -- a source that timed out or was refused is one the order asked
    for and did not get, which is not the same thing as it having nothing and
    is worth putting in front of the user. See _blamed. It is called on the
    walk's own thread, once, and only where something did go wrong.
    """
    faults: dict = {}
    try:
        return _under(_latched(alive if alive is not None
                               else getattr(_WALK, "alive", None)),
                      lambda: _walk(tid, meta, have, enabled, force, order,
                                    ahead, local, report, people),
                      faults, "", people)
    finally:
        if note is not None and faults:
            try:
                note(sorted(faults.items()))
            except Exception:                            # noqa: BLE001
                pass


def _walk(tid: str, meta: dict, have: str, enabled, force: bool,
          order, ahead, local, report, people=None):
    """The walk itself, with the caller's cancel token already installed."""
    rule = people if people is not None else Roster()
    if local is not None and rule.blocks(local):
        local = None
    bar = RANK.get(have, 0)
    known = {n: fn for n, fn in PROVIDERS}

    def _told(report, doc, name: str) -> None:
        """One answer, handed over the moment it is in hand. Never breaks the
        walk: the callback draws, and drawing is not this function's business
        to be right about."""
        if report is None or not isinstance(doc, dict) or not _walking():
            return
        try:
            report({**doc, "_source": name}, name)
        except Exception:                                # noqa: BLE001
            pass

    # THE LEAD. One provider is asked before the rest and alone, and what it
    # answers becomes the document the others have to beat: Spicy Lyrics reads
    # by track id, costs one request, and word-syncs most songs, so asking it
    # first is what keeps the usual song from fanning out to ten servers that
    # could not have won anyway. This is the shape the window's own loader had
    # -- fetch Spicy, then hand it to the chain as `local` -- moved in here so
    # that every caller gets it and not just that one. A caller holding a
    # document already (the window still does) passes it as `local` and no
    # lead is asked.
    mine, lead_name = False, ""
    if local is None:
        for name in [n for n, fn in PROVIDERS if getattr(fn, "leads", False)]:
            if enabled is not None and name not in enabled:
                continue
            got = _asks(name, lambda: known[name](tid, meta or {}))
            if not isinstance(got, dict) or rule.blocks(got):
                continue
            local, mine, lead_name = got, True, name
            bar = max(bar, RANK.get(quality(got), 0))
            _told(report, got, name)
            # What the caller would have worked out for itself: the sources it
            # ranked ABOVE the lead still get asked, since a tie goes to the
            # one the user put first and a word-timed lead must not end the
            # walk before they have answered.
            if not ahead and order and name in order:
                ahead = [n for n in order[:order.index(name)] if n in known]
            break

    def nothing():
        """Nothing beat what is in hand. Where the lead round is what put it
        there, that document IS the answer rather than None -- None means
        "keep what you already had", and a caller that handed nothing in has
        nothing to keep."""
        return (local, lead_name) if mine and local else None

    hunt = (bool(rule.pick) and not rule.likes(local)
            and [n for n, fn in PROVIDERS
                 if getattr(fn, "credits_people", False)
                 and not getattr(fn, "leads", False)])
    if bar >= RANK["syllable"] and not ahead and not hunt:
        return nothing()
    walk = [n for n in (order or [n for n, _ in PROVIDERS]) if n in known]
    walk += [n for n, _ in PROVIDERS if n not in walk]
    # The lead is never in the fan-out: it has already answered, and its
    # answer is `local`.
    names = [n for n in walk if (enabled is None or n in enabled)
             and not getattr(known[n], "leads", False)]
    if bar >= RANK["syllable"]:
        names = [n for n in names if n in ahead or n in (hunt or ())]
    if not names:
        return nothing()

    def beats(rank: int, name: str, doc=None) -> bool:
        """Whether this answer is worth having over what the caller holds.

        A tie is won two ways: by a source the caller ranked above what it
        holds, and by a document timed by somebody they asked for by name.
        Neither can win anything else -- rank is read first and read hardest,
        so a preferred name still cannot put line timing over word timing.
        """
        if rank <= 0 or rank < bar:
            return False
        if rank > bar:
            return True
        return name in ahead or (doc is not None and rule.likes(doc))

    if not force:
        rec = _cached(tid)
        if rec is not None and str(rec.get("people") or "") != rule.key():
            rec = None
        if rec is not None:
            doc, was = rec.get("doc"), rec.get("source") or ""
            asked = list(rec.get("names") or [])
            fits = bar >= int(rec.get("bar") or 0)
            if doc and asked == names:
                if beats(RANK.get(quality(doc), 0), was, doc):
                    _told(report, doc, was)
                    return doc, was or "?"
                if fits:
                    return nothing()
            elif not doc and set(names) <= set(asked) and fits:
                return nothing()

    said = threading.Lock()
    told = []

    def landed(name, doc):
        """The best answer SO FAR, handed over the moment it lands.

        The walk is ten providers wide and two rounds deep, and it used to
        hand back nothing at all until the slowest of them had finished --
        so a song nobody had cached sat under "Loading lyrics…" for as long
        as the worst server took, with a perfectly good document from the
        first one already in hand.

        Which is worth keeping, but it used to hand over whoever answered
        FIRST and then refuse to look again until the walk was over. The
        clock is not the running order: Musixmatch's endpoint is quick and
        sits last on most lists, so a song where it and a source ranked well
        above it both have word timing put Musixmatch on screen and left it
        there for the rest of the walk. The final answer did replace it, but
        the screen had already backtracked once by then, and the name under
        the lyric was somebody the user had ranked below.

        So the early answer can now be overtaken, on the same two rules the
        final pick uses and in the same priority: better timing takes the
        screen from worse, and between two documents timed alike the user's
        order decides. Nothing shown is ever replaced by something the final
        pick would not itself have chosen, so this walks towards that answer
        rather than flickering, and it arrives at the one the order asks for
        instead of the one that happened to be quick.
        """
        if report is None or not isinstance(doc, dict) or not _walking():
            return
        rank = RANK.get(quality(doc), 0)
        if not beats(rank, name, doc) or rule.blocks(doc):
            return
        at, liked = names.index(name), rule.likes(doc)
        with said:
            was = told[0] if told else None
            if was and (rank, liked, -at) <= (was[1], was[2], -was[0]):
                return
            told[:] = [(at, rank, liked)]
        _told(report, doc, name)

    docs = _gather(known, names, tid, meta or {}, local,
                   landed if report is not None else None, ahead, bar, rule)

    tied = []
    for name in names:
        doc = docs.get(name)
        if not doc:
            continue
        rank = RANK.get(quality(doc), 0)
        if not beats(rank, name, doc) or rule.blocks(doc):
            continue
        if not tied or rank > tied[0][2]:
            tied = [(doc, name, rank)]
        elif rank == tied[0][2]:
            tied.append((doc, name, rank))
    liked = [row for row in tied if rule.likes(row[0])]
    best = _fullest(_steadiest(liked or tied))
    if not _walking():
        return None
    if best:
        best = (_credited(best[0], docs, names, ahead, local, meta),
                best[1], best[2])
    _store(tid, best[0] if best else None, best[1] if best else "", names, bar,
           rule.key())
    return (best[0], best[1]) if best else nothing()


def _steadiest(tied: list):
    """The tied answers with a meaningfully steadier blend moved to the front.

    Two blends of one song differ in exactly one thing that matters: whose
    clock is under the words. The running order settles that by whoever the
    user ranked higher, which is right when there is nothing to choose
    between them and wrong when there is -- and on any given song there often
    is. NetEase is the better bet in general and QQ Music is plainly better
    on some songs; a fixed order cannot say which is which.

    `_steady` can, and is measured on the way past: see BLEND_PICK for what
    it is and for the six-out-of-six that says it predicts the right answer.
    Only a MEANINGFUL difference moves anything, so a ranking is never
    second-guessed on noise -- and only blends carry the number at all, so
    nothing else in the running order is touched.
    """
    marks = [(k, SL.payload(c[0]).get("_steady")) for k, c in enumerate(tied)]
    marks = [(k, v) for k, v in marks if isinstance(v, (int, float))]
    if len(marks) < 2:
        return tied
    at, best = min(marks, key=lambda kv: kv[1])
    if marks[0][1] - best <= BLEND_PICK:
        return tied
    out = list(tied)
    out.insert(0, out.pop(at))
    return out


def _fullest(tied: list):
    """Of the answers the walk ranked equal, the first that has the whole song.

    Order decides between two documents of the same lyric; it does not get to
    decide that a third of the words are not shown. On Bad Computer's "Your
    Spell" every blend answers word-timed, and the NetEase ones are built on
    an Apple copy carrying 359 of the song's 589 letters -- the last section
    is not in it. Ranking NetEase first asks for its clock, not for a shorter
    lyric.

    What it does not mean is that the fullest document wins. This used to walk
    the list keeping whichever answer the one in hand was short against, which
    handed the song to whoever wrote the most letters however the user had
    ranked them -- and on 2hollis' "jeans" that was Musixmatch, ranked last of
    fifteen, over a document Apple, QQ Music and Kugou all had whole (see
    BLEND_SHORT for why it read as short at all). A document missing a section
    is passed over; it is the ORDER that then says who gets the song instead,
    which is usually the source ranked next and not the longest one.

    Everything is measured against the fullest answer rather than against each
    other, because a document can only be short against a longer one and that
    is the longest there is -- one comparison each, on a list that is up to
    fifteen documents long by the time the blends have answered.
    """
    if len(tied) < 2:
        return tied[0] if tied else None
    full = max(tied, key=lambda c: len(_said(c[0])))
    return next((c for c in tied if c is full or not _shorter(c[0], full[0])), full)


def _credited(doc: dict, docs: dict, names: list, ahead, local, meta=None) -> dict:
    """The winning document, credited to whoever the top source says wrote it.

    Who wrote a song and who timed this copy of it are different questions with
    different best answers. Apple names the publishing writers -- legal names,
    every co-writer -- and a document that beat Apple on timing can easily
    carry one name or none: Kugou gives "Vivian Weeks" where Apple gives four
    people, and LRCLIB gives nobody at all. Taking the words from whoever timed
    them best and the credit from whoever is ranked highest is not a
    contradiction; they were never the same claim.

    Ranked highest means the user's own order, Spicy Lyrics in its place in it.

    AND WHERE NOBODY ANSWERED AT ALL, Apple Music is asked outright. Half of
    what this chain fetches arrives with no credit on it -- LRCLIB carries
    none by design, NetEase and Kugou carry one name where there were four,
    and a scrape drops the header before anybody sees it -- so a saved file
    ended up with no <songwriters> in it for a song whose writers are not in
    any doubt. It costs no request: Apple's catalogue was already asked about
    this track for the ISRC BiniLyrics is filed by, and the credit came back
    in the same answer (see apple_song). Last, because a document that
    carries its own credit is carrying the one its own source stands behind
    -- the winning document included, which is why it is looked at here as
    well as in the ranking. Nothing already written is replaced by a search.
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
    if not wrote and meta and not (doc.get("SongWriters") or []):
        wrote = apple_writers(meta)
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


@functools.lru_cache(maxsize=8192)
def _key(s: str) -> str:
    """A line reduced to the letters and digits in it, for comparing by text.

    Cached because of how it is ASKED. Forty-nine call sites, and the ones
    that matter sit inside the matching loops -- every line of one document
    against every line of another, the same handful of strings coming round
    again and again. Blending five songs calls this 9,668 times over 1,084
    distinct strings, nine reads of each, and the strings are short enough
    (twelve characters on average) that a dict lookup is the cheaper half by
    a wide margin: it was 27% of the blend and is now under 2%.

    Bounded rather than unbounded because the walk blends whatever is playing
    for as long as the window is open, and lyrics are a stream of new strings.
    8192 is several songs' worth of lines and syllables at once.
    """
    return "".join(c for c in (s or "").lower() if c.isalnum())


LIKE_LEN = 0.65
FRAGMENT = 0.95


def _fragment(one: str, other: str) -> bool:
    """Whether the shorter of two lines is a piece cut out of the longer.

    Length alone cannot tell a line rewritten at the head from a line that is
    half of another. "Learned to make it on my own" against a donor's "Had to
    make it on my own" is 82% of the length and 85% similar, and it is plainly
    the same line -- but so, on those numbers, is "Caught in the middle"
    against "Two faced, caught in the middle", which is a different line sung
    a bar later and pairing them put Linkin Park's chorus 1.4s out.

    What separates them is not how much shorter one is. It is whether what
    they share is CONTIGUOUS: the chorus fragment is inside the longer line
    whole, every letter of it in one run, while the rewritten head shares only
    its tail -- 15 of 18 letters, and the other three are somewhere else.
    """
    from difflib import SequenceMatcher

    short, long = sorted((one, other), key=len)
    if not short:
        return False
    block = SequenceMatcher(None, short, long, autojunk=False)\
        .find_longest_match(0, len(short), 0, len(long))
    return block.size >= FRAGMENT * len(short)


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
            if len(key) != len(b[j]) and _fragment(key, b[j]):
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
#     ------   (none at all, at 0.75)
RECUT_LIKE = 0.65


def _recut(theirs: str, ours: str, bounds: list[int], breaks: set[int],
           floor: float = RELAY_LIKE) -> list[int] | None:
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
    if sm.ratio() < floor:
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


CONTRACTED = "'\u2019"


def _unsplit(syls: list[dict]) -> list[dict]:
    """Pieces of one word the letters were cut between, put back together.

    Two sources spell a contraction differently -- NetEase writes "It is never
    too late" where Apple writes "It's" -- and the letter alignment then puts
    a cut inside OUR word, at the apostrophe. What comes out is "It'" and "s"
    lighting a tenth of a second apart, on a word nobody sings in two pieces.
    Over the songs measured here it is the commonest shape of sub-word cut
    there is: "don'" and "t", "I'" and "m", "walk'" and "s".

    Only at the apostrophe, and only where the word runs on. A syllable that
    ENDS a word keeps its own timing however it is spelled, and a sub-word cut
    anywhere else is the donor really having measured two syllables of one
    word, which is the thing this whole file is for.
    """
    out: list[dict] = []
    for y in syls:
        was = out[-1] if out else None
        if (was and was.get("IsPartOfWord")
                and str(was.get("Text") or "").rstrip()[-1:] in CONTRACTED):
            out[-1] = {**was,
                       "Text": str(was.get("Text") or "") + str(y.get("Text") or ""),
                       "EndTime": max(float(was["EndTime"]), float(y["EndTime"])),
                       "IsPartOfWord": bool(y.get("IsPartOfWord"))}
            continue
        out.append(dict(y))
    return out


def _relay(text: str, syls: list[dict],
           floor: float = RELAY_LIKE) -> list[dict] | None:
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

    Matching WORDS to words instead was tried and measured, on the theory that
    a letter alignment cannot know what a word is. It is worse, and for the
    reason this docstring already gives: exact word matching drops every word
    the two sources spell differently, and near-matching words inside a window
    recovers only some of them. Against this, over Stronger, MOTTO and If You
    Want Love -- 91/91 lines timed with nothing invented, against 90/91 with
    twenty-five onsets invented; 77/79 and four, against 75/79. The letters
    already carry the words with them. See eval_sources.py for the instrument.

    `floor` is how alike the two have to be before the cuts are taken at all.
    It is looser for a line the re-stream handed over than for one a pairing
    did, because those two arrive with very different amounts of evidence
    behind them; see RECUT_LIKE.
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
        cuts = _recut(theirs, ours, bounds, breaks, floor)
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
    return _unlump(_unsplit(out))


MASKED = re.compile(r"\*\*+")

WORD_MARKS = re.compile(r"^[&+/@]$")


def _mark_only(text) -> bool:
    """Whether a syllable is nothing but punctuation. A mask is not, and
    neither is a symbol that is really a word -- see WORD_MARKS."""
    text = str(text or "")
    return (not _key(text) and not MASKED.search(text)
            and not WORD_MARKS.match(text.strip()))


HOLE_GAP = 0.35


def close_holes(doc):
    """Ends that were not written, made ends a reader can see.

    The same repair `_mxm_spans` does for Musixmatch and for the same reason,
    which is that at the scale a lyric is read at a tenth of a second of dead
    air in the middle of a phrase does not read as phrasing -- it reads as the
    word cutting out. A word held to the next word's start is what everybody
    who has hand-timed a line writes.

    INSIDE A LINE ONLY, which is where this differs from the Musixmatch one.
    That one closes across lines too, on the grounds that two lines a tenth of
    a second apart are one phrase however they were cut. Here they are not:
    these sources write a line's end deliberately and the player draws a line
    for exactly as long as it lasts, so holding the last word of a line into
    the next one lights both at once.

    Backing groups get the same treatment as the lead, separately -- an ad-lib
    is its own phrase and its last word has nothing after it to run to.
    """
    body = SL.payload(doc or {})
    items = _items(body)
    if not items:
        return doc
    out, touched = [], 0
    for it in items:
        got = dict(it)
        for key in ("Lead", "Background"):
            groups = got.get(key)
            groups = [groups] if isinstance(groups, dict) else (
                list(groups) if isinstance(groups, list) else [])
            fresh = []
            for g in groups:
                syls = list((g or {}).get("Syllables") or [])
                said = []
                for a, b in zip(syls, syls[1:] + [None]):
                    if b is not None:
                        gap = (b.get("StartTime") or 0.0) - (a.get("EndTime") or 0.0)
                        if 1e-6 < gap <= HOLE_GAP:
                            a = {**a, "EndTime": b["StartTime"]}
                            touched += 1
                    said.append(a)
                fresh.append({**g, "Syllables": said} if said else g)
            if not fresh:
                continue
            got[key] = fresh[0] if key == "Lead" else fresh
        out.append(got)
    if not touched:
        return doc
    fresh = {k: v for k, v in body.items() if k not in ("Content", "Lines")}
    fresh["Content"] = out
    return fresh


def no_overlap(doc):
    """No line drawn past the start of the line after it, where the part of
    it past that start is slack rather than singing.

    Every other rule here is about what a line SAYS; this one is about the
    screen, where two lines lit at once is two lines the reader has to choose
    between. It happens for honest reasons -- a source holds a line open
    until the next is due, an ad-lib lifted onto a line carries an end from
    further down the song, a fold brings that end up with it -- and on Conro's
    "All I Want" they stacked: "All I want is" ran 25.98 to 34.80 over "All I
    want" at 30.60 and "(All I want)" at 32.88, three lines lit together.

    The line's own end is what gives way, and its backing groups with it,
    because the next line's start is a measurement and the end usually is not
    -- it is a held tail, or a stamp somebody put where the next line begins.

    But only as far as its own content: an end gives way where it is slack,
    and a sung syllable is not slack. So an end is never pulled below the last
    thing the line is actually singing, and a syllable is clipped only where
    it STRADDLES that start AND is the last of its group, because only then is
    its end slack -- an interior syllable's end is the next one's onset, which
    is a measurement, and pulling it back ends a word before it is sung. One
    that begins after that start is not a tail running over, it is a voice
    singing there,
    and on slayr's "promise" that is most of the song: the echoes that answer
    "Promise-- that you couldn't keep" are each sung a whole line late, and
    pulling their ends back to the next line's start squashed all seven words
    of them to the 50ms floor. The light then stood still for 49 frames out of
    76 and jumped 20px between them -- a line playing choppily on a renderer
    with nothing wrong with it. A group that begins past that start is left
    alone entirely, which also keeps an end from crossing its own beginning.

    Two lines really can sound together -- a trade, an answer, an ad-lib held
    over the line beneath it -- and where the stamps say so, they say so
    because somebody measured it. See Sweep in renderers, which draws a row
    with two voices in it.

    So this runs over a blend and nothing else. Every overrun named above is
    one source's end landing on another source's lines: a donor holds a line
    open until the next is due and the base it was laid over disagrees, a
    graft carries an end from further down the song, a fold brings that end up
    with it. Reconciling them is this rule's business. A document from one
    source is not that. Its ends and the starts they run past were written by
    the same hand, in one pass, against one clock, and where they overlap that
    is what was heard -- on Linkin Park's "In the End" the echo answering
    "watch you go" holds its last vowel 46.692 to 54.017, over three lines of
    the verse under it, and clipping it to the next line's start took 6.97s of
    a 7.33s syllable off a note that is plainly still being sung. There is
    nothing to reconcile there and no second opinion to prefer, so the
    measurement stands. See blended().
    """
    if not blended(doc):
        return SL.payload(doc or {})
    doc = SL.payload(doc or {})
    items = _items(doc)
    if len(items) < 2:
        return doc
    key = "Content" if isinstance(doc.get("Content"), list) else "Lines"

    def later(a, b):
        """The later of two moments, either of which may be missing."""
        if a is None:
            return b
        return a if b is None else max(a, b)

    out = []
    for n, it in enumerate(items):
        nxt = SL.line_start(items[n + 1]) if n + 1 < len(items) else None
        end = _line_end(it)
        start = SL.line_start(it)
        if not isinstance(nxt, (int, float)) or not isinstance(end, (int, float)) \
                or end <= nxt:
            out.append(it)
            continue
        if isinstance(start, (int, float)) and start >= nxt:
            # Wholly inside the next line's time: nothing here is a tail.
            out.append(it)
            continue

        def clip(group):
            """The group with its slack past `nxt` taken off, and the last
            moment it is still singing."""
            got = dict(group or {})
            at, done = got.get("StartTime"), got.get("EndTime")
            if isinstance(at, (int, float)) and at >= nxt:
                return got, (max(float(at), float(done))
                             if isinstance(done, (int, float)) else float(at))
            sung = float(at) if isinstance(at, (int, float)) else None
            syls = got.get("Syllables") or []
            last = len(syls) - 1
            fresh = []
            for i, y in enumerate(syls):
                st, en = y.get("StartTime"), y.get("EndTime")
                if isinstance(st, (int, float)) and isinstance(en, (int, float)):
                    # Only the last syllable's end is slack. An interior one's
                    # end IS the next one's onset -- a measurement, and moving
                    # it ends a word before it is sung.
                    if i == last and st < nxt < en:
                        y, en = {**y, "EndTime": nxt}, nxt
                    sung = en if sung is None else max(sung, en)
                fresh.append(y)
            syls = fresh
            if syls:
                got["Syllables"] = syls
            if isinstance(got.get("EndTime"), (int, float)) and got["EndTime"] > nxt:
                got["EndTime"] = nxt if sung is None else max(nxt, sung)
            return got, sung

        new = dict(it)
        # The last moment the line is still singing: its own end may give way
        # to `nxt`, but never past this.
        floor = float(start) if isinstance(start, (int, float)) else None
        if isinstance(it.get("Lead"), dict):
            new["Lead"], sung = clip(it["Lead"])
            floor = later(floor, sung)
        bg = [g for g in (it.get("Background") or []) if isinstance(g, dict)]
        if bg:
            done = [clip(g) for g in bg]
            new["Background"] = [g for g, _ in done]
            for _, sung in done:
                floor = later(floor, sung)
        new["EndTime"] = nxt if floor is None else max(nxt, floor)
        out.append(new)
    return {**doc, key: out}


def quiet_marks(doc):
    """Timing taken off a syllable that is nothing but punctuation.

    A source that stamps "..." or an em dash as a syllable of its own gives
    it a turn on screen, and the turn can be enormous: the mark sits between
    two verses and its stamp spans the instrumental break between them, so
    the fill crawls across a dash for twenty seconds while nobody sings.

    It is not sung, so it does not get a clock. Its text rides on the word
    before it -- or on the word after, where it opens the line -- and that
    neighbour keeps its OWN times, which is the whole point: the break stops
    being drawn as if something were happening in it.

    A masked word is not one of these; see MASKED. Riding it onto its
    neighbour is what took the space out from around it on screen.

    A line that is nothing but marks is left alone. There is no word for it
    to ride on, and a line of dots between verses is a real thing a lyricist
    writes; the interlude setting is what answers that one.
    """
    def fixed(group):
        syls = (group or {}).get("Syllables") or []
        if len(syls) < 2 or all(_mark_only(y.get("Text")) for y in syls):
            return group
        out = []
        for y in syls:
            if not _mark_only(y.get("Text")) or not out:
                out.append(dict(y))
                continue
            out[-1]["Text"] = str(out[-1].get("Text") or "") + str(y.get("Text") or "")
            out[-1]["IsPartOfWord"] = bool(y.get("IsPartOfWord"))
        while len(out) > 1 and _mark_only(out[0].get("Text")):
            out[1] = dict(out[1], Text=str(out[0].get("Text") or "")
                          + str(out[1].get("Text") or ""))
            out.pop(0)
        if len(out) == len(syls):
            return group
        return {**group, "Syllables": out,
                "StartTime": out[0].get("StartTime", group.get("StartTime")),
                "EndTime": out[-1].get("EndTime", group.get("EndTime"))}

    doc = SL.payload(doc or {})
    key = "Content" if isinstance(doc.get("Content"), list) else "Lines"
    items = _items(doc)
    if not items:
        return doc
    out, touched = [], False
    for it in items:
        new = dict(it)
        if isinstance(it.get("Lead"), dict):
            new["Lead"] = fixed(it["Lead"])
            touched = touched or new["Lead"] is not it["Lead"]
        bg = [g for g in (it.get("Background") or []) if isinstance(g, dict)]
        if bg:
            new["Background"] = [fixed(g) for g in bg]
            touched = touched or any(a is not b for a, b in zip(new["Background"], bg))
        out.append(new)
    if not touched:
        return doc
    return {**doc, key: out}


def unlump(doc):
    """Every group in a document, with no syllable holding two words.

    _relay does this to what it lays down, but a document has words in it
    that the relay never touched: the base's own syllables where the donor
    had nothing to say about that line, its backing vocals, and every line
    of a document that won outright and was never blended at all. The donors
    carry them -- "or ​am", "I ​am ​a", two words joined with a zero-width
    space and given one timing between them -- and they read exactly like the
    ones the relay used to make.

    Not Spicy Lyrics' copy any more, though it used to be the example here.
    Its zero-width spaces are its own -- it writes them over a line that
    already spells its gaps -- so _spicy_docked takes every one of them out at
    the door and a lump of its can only be a lump of real spaces now. See
    SL.unzwsp_body.
    """
    body = SL.payload(doc or {})
    items = _items(body)
    if not items:
        return doc
    out, touched = [], False
    for it in items:
        got = dict(it)
        for key in ("Lead",):
            g = got.get(key)
            if isinstance(g, dict) and g.get("Syllables"):
                fresh = _unlump(g["Syllables"])
                if len(fresh) != len(g["Syllables"]):
                    touched = True
                    got[key] = {**g, "Syllables": fresh}
        bg = got.get("Background")
        if isinstance(bg, list) and bg:
            rows = []
            for g in bg:
                if isinstance(g, dict) and g.get("Syllables"):
                    fresh = _unlump(g["Syllables"])
                    if len(fresh) != len(g["Syllables"]):
                        touched = True
                        g = {**g, "Syllables": fresh}
                rows.append(g)
            got["Background"] = rows
        out.append(got)
    if not touched:
        return doc
    made = {k: v for k, v in body.items() if k not in ("Content", "Lines")}
    made["Content"] = out
    return made


def _unlump(syls: list[dict]) -> list[dict]:
    """One timing covering several words, shared out among them.

    The donor does not always cut where we do. Where it holds two of our
    words in one token -- "let me", "that shit", "a fuck," -- and wherever
    the tail of a line ends up on the last syllable, those words fill as a
    single block: they all light at once and none of them lights when it is
    sung. Nearly seven per cent of the syllables in the blends here were
    carrying more than one word.

    The share is by character count, which is the same guess `_cut` makes and
    wrong in the same small way. It cannot move a word's onset earlier than
    the donor put the group, and it cannot push one past the group's end, so
    the error it can introduce is bounded by the length of the lump.
    """
    out = []
    for y in syls:
        text = y.get("Text") or ""
        parts = re.findall(r"[^\s\u200b]+[\s\u200b]*", text)
        s, e = y.get("StartTime"), y.get("EndTime")
        if len(parts) < 2 or not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            out.append(y)
            continue
        joined: list[str] = []
        for piece in parts:
            if joined and not any(c.isalnum() for c in piece):
                joined[-1] += piece
            else:
                joined.append(piece)
        parts = joined
        if len(parts) < 2:
            out.append(y)
            continue
        span = max(0.0, float(e) - float(s))
        total = sum(len(p.strip()) for p in parts) or 1
        at = float(s)
        for k, piece in enumerate(parts):
            body = piece.rstrip()
            last = k == len(parts) - 1
            end = float(e) if last else at + span * len(body) / total
            made = {**y, "Text": body if last else piece,
                    "StartTime": at, "EndTime": max(end, at),
                    "IsPartOfWord": bool(y.get("IsPartOfWord")) if last
                    else piece == body}
            if k:
                made["Guess"] = True
            out.append(made)
            at = end
    return out


CRIES = {"yeah", "yea", "yah", "yuh", "ye", "oh", "ooh", "ohh", "oo", "ah",
         "ahh", "aah", "uh", "uhh", "huh", "hey", "ay", "ayy", "aye", "woo",
         "whoo", "hoo", "wow", "damn", "god", "lord", "what", "nah", "na",
         "la", "mm", "mmm", "hmm", "hm", "ha", "haha", "hahaha", "go", "come",
         "on", "let's", "lets", "yo", "ey", "eh", "okay", "ok", "mhm", "brr",
         "skrrt", "uh-huh", "woah", "whoa", "baby", "now", "yes", "no", "one",
         "two", "three", "four"}
CRY_WORDS = 4
ASIDE_WORDS = 6


def _a_cry(text: str) -> bool:
    """Whether a line is nothing but shouting: yeah, ooh, come on, oh God."""
    words = [w.strip("'’-") for w in re.split(r"[^\w'’-]+", (text or "").lower()) if w]
    return bool(words) and all(w in CRIES for w in words)


def _cry_lines(items: list[dict]) -> set:
    """Lines that are an ad-lib somebody filed as a line of its own.

    Sources disagree about this constantly. Apple marks "(What)" inline and
    gives "Oh, God" a line to itself on the same song; QQ and NetEase file
    both as lines. Read as lines they are sung by the lead voice, in the lead
    voice's type, and they take a turn in the scroll that nobody sang.

    Nothing here is marked, so it is inferred, and the inference is kept
    narrow because the cost of being wrong is a real lyric drawn as an
    afterthought. All of:

      * the line is nothing but shouting -- every word of it in CRIES;
      * it is short, and it repeats somewhere else in the song, because an
        ad-lib is a thing a song does more than once;
      * both its neighbours are full lines, so a run of "Go, go, go!" against
        itself is left alone -- that is a refrain, not an ad-lib;
      * it is neither the first line nor the last.

    A looser version of this -- short, repeated, between two long lines, no
    vocabulary -- folded 3.2% of every line in this library and swallowed
    "You big disgrace" and "Suffocation, no breathing". With the vocabulary
    it folds 0.29%, and they are all "Yeah", "Ooh", "Come on".
    """
    from collections import Counter

    texts = [SL.line_text(i) or "" for i in items]
    keys = [_key(t) for t in texts]
    sizes = [len(t.split()) for t in texts]
    seen = Counter(k for k, n in zip(keys, sizes) if k and n <= CRY_WORDS)
    out = set()
    for i, (k, n) in enumerate(zip(keys, sizes)):
        if not k or n > CRY_WORDS or seen[k] < 2:
            continue
        if i == 0 or i + 1 >= len(items):
            continue
        if keys[i - 1] == k or keys[i + 1] == k:
            continue
        if sizes[i - 1] <= CRY_WORDS or sizes[i + 1] <= CRY_WORDS:
            continue
        if _a_cry(texts[i]):
            out.add(i)
    return out


CJK_MAKERS = ("qq", "kugou", "netease")
CJK_SOURCES = set(CJK_MAKERS) | set(BLENDS)
_CJK_VIA = re.compile("|".join(CJK_MAKERS), re.I)


def lrc_shaped(doc) -> bool:
    """Whether NetEase, QQ Music or Kugou had a hand in this document.

    Three marks are read, because that hand can arrive by three routes:
    `_source` is the provider the walk settled on, `_alone` is the one a
    blend stood down to when its own answer was thinner, and `_via` names the
    upstream a proxy answered from, and a blend writes out its whole makeup,
    "Apple Music + QQ Music + NetEase".

    A grafted document is deliberately not one of them. There NetEase lends
    its word timings and nothing else; the lines, the brackets and the
    ad-libs on screen are all Spicy Lyrics' own, and they are not this
    repair's to make.
    """
    seen = [doc if isinstance(doc, dict) else {}, SL.payload(doc or {})]
    for d in seen:
        alone = str(d.get("_alone") or "")
        if alone:
            return alone in CJK_MAKERS
        if str(d.get("_source") or "") in CJK_SOURCES:
            return True
        if _CJK_VIA.search(str(d.get("_via") or "")):
            return True
    return False


def lifted(doc) -> bool:
    """Whether these lines were line-synced until somebody lent them words.

    Written where it happens rather than worked out here, because by the time
    the document reaches this it no longer remembers: _blend marks a document
    it laid a donor's timings over a base that had none, and graft_syllables
    marks its own output, which is only ever a line-quality base.
    """
    for d in (doc if isinstance(doc, dict) else {}, SL.payload(doc or {})):
        if d.get("_lifted"):
            return True
    return False


def blended(doc) -> bool:
    """Whether this document's timings were stitched together from more than
    one source.

    `_via` names the makeup a blend wrote out -- "Apple Music + QQ Music" --
    so more than one part in it is the mark of a blend. `_lifted` is the same
    answer arriving another way: _blend sets it where it laid a donor's clock
    over a base that had none, and graft_syllables sets it on a document whose
    words are one source's and whose lines are another's. Both are two sources
    reconciled, which is the whole of what this asks.

    `_alone` is read first and answers no. It is written where a blend stood
    down and handed over one donor's own document instead, and that document
    is one source's work however close it came to being a blend.

    A document nobody blended carries none of these -- a file off disk, a
    provider's own answer, a lyric somebody timed by hand -- and its ends are
    its author's measurements.
    """
    for d in (doc if isinstance(doc, dict) else {}, SL.payload(doc or {})):
        if str(d.get("_alone") or ""):
            return False
        if d.get("_lifted") or " + " in str(d.get("_via") or ""):
            return True
    return False


def needs_adlibs(doc) -> bool:
    """Whether this document's ad-libs are still written into its lyric.

    Two ways they can be, and they are different faults with the same shape.

    lrc_shaped: NetEase, QQ Music and Kugou hand their lyrics over in an
    LRC-shaped document, and LRC has nowhere to put a second voice at all.

    lifted: the lines had only line stamps until a donor lent them word
    timing. A document with no word timing has no per-word groups either, so
    whoever wrote it had exactly two places to put a backing vocal -- in
    brackets inside the lead, or on a line of its own -- and both of those are
    what fold_cries and split_asides put back. The donor's clock is what makes
    it possible to; before the words were timed there was nothing to hang a
    background on.

    Still not "repair everything": a document that marks its own backgrounds
    is believed, whoever wrote it, which is the case lrc_shaped's own
    docstring was written around.
    """
    return lrc_shaped(doc) or lifted(doc)


def split_asides(doc):
    """Ad-libs a document writes into the lyric, made backing groups of it.

    Apple marks a backing vocal by putting it in brackets inside the line's
    own text -- "Life's got me by the neck with a blade against it (What?)".
    Every other way a document can say "this is a second voice" gets drawn as
    one: NetEase files the same "(What?)" as a proper background and it comes
    out beside the line, in the ad-lib's own place, filling on its own. Left
    in the text it is drawn as part of the lead, in the lead's size, and its
    words light when the last word of the line does.

    The blend already peels a bracket off when a donor has separate timing
    for it (see _peel_bracket), which is the better answer because the timing
    is somebody's measurement rather than ours. This is for all the rest, and
    it needs no donor at all: the words are in the line, so the line's own
    syllables already say when they are sung. They are lifted out and the
    lyric keeps everything else.

    A line that is nothing but the bracket goes onto the line before it
    instead, timing and all, the way fold_cries moves a shout -- there is no
    lead of its own to hang it on, and a document that marks its ad-libs this
    way has said what that line is. Only where it sits against the line
    before: an ad-lib alone in the middle of a gap is not that line's.

    And only where it stands ALONE. Bracketed lines that come one after
    another are not asides at all, they are a passage sung by the second
    voice, and each of them is a lyric in its own right: "(Caught up in the
    storm but we're the survivors)" is answered by "(Lookin' out for love in
    a little bit of darkness)", and "（You're such a fail, what's wrong with
    you?）" by two more like it. Folding those hangs a whole section off one
    line of the verse above it as a whisper. A run of them is left as it
    stands unless every line in the run is a plain shout -- "(Yeah)",
    "(Woo)" -- which is a document listing its ad-libs, not singing a
    passage. See ASIDE_WORDS and CRY_WORDS: the two counts are exactly this
    difference.

    Left alone: any bracket whose words the line does not time cleanly, which
    is the answer whenever the two do not line up exactly.
    """
    body = SL.payload(doc or {})
    items = _items(body)
    if not items:
        return doc
    aside = [_all_aside(SL.line_text(it)) for it in items]
    out, touched = [], False
    for i, it in enumerate(items):
        if out and aside[i] and _fold_onto(out[-1], it, _alone(aside, i)):
            touched = True
            continue
        got = _split_aside(it)
        touched = touched or got is not None
        out.append(got if got is not None else _own(it))
    if not touched:
        return doc
    fresh = {k: v for k, v in body.items() if k not in ("Content", "Lines")}
    fresh["Content"] = out
    return fresh


UNBRACKET = "()[]（）【】"
WHOLLY = re.compile(r"^\s*[(（\[【]([^)）\]】]+)[)）\]】]\s*$")


def _all_aside(text: str) -> bool:
    """Whether the line is one bracket and nothing else."""
    return bool(WHOLLY.match(text or ""))


def _alone(aside: list, i: int) -> bool:
    """Whether the bracketed line at `i` is the only one in its run."""
    return not ((i and aside[i - 1]) or (i + 1 < len(aside) and aside[i + 1]))


def _fold_onto(host: dict, it: dict, alone: bool = True) -> bool:
    """Put a wholly-bracketed line onto the line before it. True if it went.

    The host is edited in place, so it has to be a copy this pass made rather
    than the caller's own line -- everything reaching here has been through
    _split_aside or this, and both copy.
    """
    syls = _syls_of(it)
    begin, end = _group_span(it, syls)
    was = _line_end(host)
    if not syls or not isinstance(begin, (int, float)):
        return False
    said = SL.line_text({"Lead": {"Syllables": syls}}) or ""
    cap = ASIDE_WORDS if alone else CRY_WORDS
    if len([w for w in said.strip(UNBRACKET + " ").split() if _key(w)]) > cap:
        return False
    # An echo of the line is not an ad-lib on it. Apple writes Conro's "All I
    # Want" as "All I want" at 30.60 and "(All I want)" at 32.88 -- a call and
    # its answer, two lines, sung a bar apart. Folded together they are drawn
    # together: one line running 30.60 to 33.99 with the same three words in
    # the lead and in the backing group, which reads as the lyric stuttering.
    # Nothing is gained by it either; the echo already had a line and a time
    # of its own.
    if _key(said) == _key(SL.line_text(host)):
        return False
    if isinstance(was, (int, float)) and not (was - ASIDE_REACH <= begin
                                              <= was + ASIDE_REACH):
        return False
    said = [{**y, "Text": (y.get("Text") or "").strip(UNBRACKET + " ")}
            for y in _unlump(syls)]
    said = [y for y in said if y["Text"]]
    if not any(_key(y["Text"]) for y in said):
        return False
    group = {"Syllables": said, "StartTime": said[0].get("StartTime"),
             "EndTime": said[-1].get("EndTime")}
    bg = [g for g in (host.get("Background") or []) if isinstance(g, dict)]
    bg.append(group)
    for g in (it.get("Background") or []):
        if isinstance(g, dict):
            bg.append(g)
    bg.sort(key=lambda g: (g.get("StartTime") if isinstance(g.get("StartTime"),
                                                            (int, float)) else 0.0))
    host["Background"] = bg
    if isinstance(host.get("EndTime"), (int, float)) and isinstance(end, (int, float)):
        host["EndTime"] = max(host["EndTime"], end)
    return True


def _own(it: dict) -> dict:
    """A copy deep enough to take a Background of its own. The document this
    is walking belongs to the cache, and a line folded onto it in place would
    be found there by the next reader."""
    got = dict(it)
    if isinstance(got.get("Background"), list):
        got["Background"] = list(got["Background"])
    return got


OPENERS, CLOSERS = "([（【", ")]）】"


def _unbracket_edges(syls: list, run: list, drop: set, edits: dict) -> None:
    """Take the brackets off what an ad-lib leaves behind.

    The run is chosen on letters alone, so a source that writes its brackets
    as syllables of their own -- NetEase writes "（", "No", "thoughts", "）"
    -- has them stepped straight over: the words left with the ad-lib and the
    marks stayed standing on the lead, "Hold my hand ( ) tonight". Where the
    same marks are glued to a word instead they ride out on the word before
    and the word after, and have to come off those without taking the word
    with them.

    A mark left with nothing on it goes altogether rather than staying as an
    empty syllable: the space between two words is drawn from IsPartOfWord
    when the line is written out, so nothing is holding it apart.

    One neighbour each side and no further. Two ad-libs in a row would
    otherwise reach past their own bracket into the one beside it.
    """
    for i, chars, at_end in ((run[0] - 1, OPENERS, True),
                             (run[-1] + 1, CLOSERS, False)):
        if not (0 <= i < len(syls)) or i in drop:
            continue
        was = edits.get(i, syls[i].get("Text") or "")
        cut = chars + " \t" + SL.ZWSP
        got = was.rstrip(cut) if at_end else was.lstrip(cut)
        if got != was:
            edits[i] = got.strip()


def _reglue(syls: list, kept: list, live: list) -> None:
    """Let a word end where the ad-lib that was finishing it went.

    "You (Okay), must find" is two words to the source: "You (" is marked
    part-of-word because "Okay)," is the rest of it. Move the ad-lib into the
    Background and the mark is a lie -- the word ends at "You," now -- but the
    flag still says the next syllable is glued on, and the line came out
    "You,must find".

    Whatever stood last before the next surviving syllable is the thing that
    knew whether the word carried on into it, so its flag comes back with it.
    A bracket inside a word, "wo(oo)ah", is marked glued there and stays
    glued here, which is the same rule and the right answer for it.
    """
    for pos, i in enumerate(live):
        nxt = live[pos + 1] if pos + 1 < len(live) else len(syls)
        if nxt == i + 1:
            continue
        glue = bool(syls[nxt - 1].get("IsPartOfWord"))
        if bool(kept[pos].get("IsPartOfWord")) != glue:
            kept[pos] = {**kept[pos], "IsPartOfWord": glue}


def _split_aside(it: dict):
    """One line, with its bracketed ad-libs moved into Background, or None
    where there was nothing to move."""
    lead = it.get("Lead") if isinstance(it.get("Lead"), dict) else None
    syls = (lead or {}).get("Syllables") or []
    text = SL.line_text(it)
    if not syls or not BRACKETED.search(text or ""):
        return None
    syls = _unlump(syls)
    spans, at = [], 0
    for y in syls:
        n = len(_key(y.get("Text") or ""))
        spans.append((at, at + n))
        at += n
    drop, groups, cuts, edits = set(), [], [], {}
    for m in BRACKETED.finditer(text):
        key = _key(m.group(1))
        if not key:
            continue
        lo = len(_key(text[:m.start()]))
        hi = lo + len(key)
        run = [i for i, (a, b) in enumerate(spans) if a >= lo and b <= hi and b > a]
        if not run or run[-1] - run[0] + 1 != len(run) or drop & set(run):
            continue
        if "".join(_key(syls[i].get("Text") or "") for i in run) != key:
            continue
        if len(run) == sum(1 for a, b in spans if b > a):
            continue
        said, spill = [], ""
        for pos, i in enumerate(run):
            y = dict(syls[i])
            txt = y.get("Text") or ""
            if pos == 0:
                at = min((txt.find(c) for c in OPENERS if c in txt), default=-1)
                if at >= 0:
                    spill, txt = spill + txt[:at], txt[at + 1:]
            if pos == len(run) - 1:
                at = max((txt.rfind(c) for c in CLOSERS if c in txt), default=-1)
                if at >= 0:
                    txt, spill = txt[:at], spill + txt[at + 1:]
            y["Text"] = txt.strip(UNBRACKET + " ")
            said.append(y)
        if not said or not any(_key(y["Text"]) for y in said):
            continue
        drop.update(run)
        _unbracket_edges(syls, run, drop, edits)
        if spill.strip():
            side = [i for i in (run[0] - 1, run[-1] + 1)
                    if 0 <= i < len(syls) and i not in drop]
            if side:
                i = side[0]
                was = edits.get(i, syls[i].get("Text") or "")
                edits[i] = ((was + spill.strip()) if i < run[0]
                            else (spill.strip() + was)).strip()
        cuts.append(m.span())
        groups.append({"Syllables": said,
                       "StartTime": said[0].get("StartTime"),
                       "EndTime": said[-1].get("EndTime")})
    kept, live = [], []
    for i, y in enumerate(syls):
        if i in drop:
            continue
        if i in edits:
            if not edits[i]:
                continue
            y = {**y, "Text": edits[i]}
        live.append(i)
        kept.append(y)
    _reglue(syls, kept, live)
    if not groups or not kept:
        return None
    left = text
    for a, b in reversed(cuts):
        left = left[:a] + left[b:]
    left = re.sub(r"\s{2,}", " ", left).strip()
    got = dict(it)
    if isinstance(got.get("Text"), str):
        got["Text"] = left
    got["Lead"] = {**(lead or {}), "Syllables": kept}
    if isinstance(got["Lead"].get("EndTime"), (int, float)):
        got["Lead"]["EndTime"] = max(
            [y.get("EndTime") for y in kept
             if isinstance(y.get("EndTime"), (int, float))] or [got["Lead"]["EndTime"]])
    bg = [g for g in (it.get("Background") or []) if isinstance(g, dict)] + groups
    bg.sort(key=lambda g: (g.get("StartTime") if isinstance(g.get("StartTime"),
                                                            (int, float)) else 0.0))
    got["Background"] = bg
    return got


def fold_cries(doc):
    """Ad-libs filed as their own lines, folded onto the line before them.

    Their timing comes with them untouched -- the point is not to re-time
    anything, only to stop a shout taking a line's worth of the screen and a
    turn in the scroll.
    """
    body = SL.payload(doc or {})
    items = _items(body)
    picks = _cry_lines(items) if len(items) > 2 else set()
    if not picks:
        return doc
    out: list[dict] = []
    for i, it in enumerate(items):
        lead = (it.get("Lead") or {}) if isinstance(it.get("Lead"), dict) else {}
        syls = lead.get("Syllables") or []
        if i in picks and out and syls:
            host = out[-1]
            end = _line_end(it)
            groups = host.setdefault("Background", [])
            groups.append({"Syllables": syls, "StartTime": SL.line_start(it),
                           "EndTime": end})
            for g in (it.get("Background") or []):
                if isinstance(g, dict):
                    groups.append(g)
                    e = g.get("EndTime")
                    if isinstance(e, (int, float)):
                        end = e if not isinstance(end, (int, float)) else max(end, e)
            if isinstance(end, (int, float)) and isinstance(host.get("EndTime"), (int, float)):
                host["EndTime"] = max(host["EndTime"], end)
            continue
        fresh = dict(it)
        if isinstance(fresh.get("Background"), list):
            fresh["Background"] = list(fresh["Background"])
        out.append(fresh)
    got = {k: v for k, v in body.items() if k not in ("Content", "Lines")}
    got["Content"] = out
    return got


# --------------------------------------------------------------------------
MASK = "*"
UNMASK_EDGE = "\"'`“”‘’(){}[]<>,.!?;:…-–—"
UNMASK_SHARE = 0.5
UNMASK_REACH = 4
UNMASK_FROM = ("mxm", "lrclib")

CLEAN_MARK = re.compile(
    r"[\(\[]\s*(?:clean|censored|edited)(?:\s+(?:version|edit))?\s*[\)\]]"
    r"|[-\u2013\u2014]\s*(?:clean|censored|edited)(?:\s+(?:version|edit))?\s*$",
    re.I)


COMMUNITY_SYNC = "a community sync"


def clean_edit(doc, tid: str, meta: dict, enabled=None) -> str:
    """Why the masks in this document are to be left alone, or "" if they are not.

    Five questions, cheapest first, and the string that comes back is the one
    the window puts on screen -- a mask left standing with nothing said about
    it is how a provider that had quietly failed went unnoticed for weeks.

    Two of the five are about the RECORDING being the clean cut, where
    filling a mask writes a word over a bar of silence. The other two are
    about whose words these are: a document somebody typed is not a document
    with a defect in it, and its masks are that person's reading of what they
    heard.

    Only ever reached for a document that HAS masks: `uncensor` counts them
    before it asks anything, and the great majority of songs have none. So the
    order below is about what the rare song costs, not the common one.

    None of the four is allowed to answer from silence. A source that was not
    asked, or was asked and had nothing, says nothing -- it does not say the
    recording is explicit, and it does not say it is clean.
    """
    hand = str((doc or {}).get("_hand") or "")
    if hand:
        return f"timed by hand \u00b7 {hand}"
    who = credited(doc)
    if who:
        return f"{COMMUNITY_SYNC} \u00b7 " + ", ".join(who[:2])
    for field in ("title", "album"):
        text = str((meta or {}).get(field) or "")
        if text and CLEAN_MARK.search(text):
            return f"the {field} says so"
    said = (meta or {}).get("explicit")
    if said is not None:
        return "" if said else "Spotify says this cut is clean"
    if enabled is None or "mxm" in enabled:
        try:
            if mxm_explicit(tid, meta) == "clean":
                return "Musixmatch says this cut is clean"
        except Exception:                                # noqa: BLE001
            pass
    return ""


def _bare(word: str) -> tuple[str, str, str]:
    """A word as (punctuation, letters, punctuation)."""
    i, j = 0, len(word)
    while i < j and word[i] in UNMASK_EDGE:
        i += 1
    while j > i and word[j - 1] in UNMASK_EDGE:
        j -= 1
    return word[:i], word[i:j], word[j:]


def _hidden(word: str) -> bool:
    """Whether a word has had letters taken out of it.

    Two characters at least: a lone asterisk is a footnote mark or a
    separator, not a word with something hidden inside it.

    And a word with stars on BOTH sides of it is not one either. Asterisks
    around a word that is all there are an effect -- *spit*, *Taylored* --
    which is how a lyric writes a stage direction or leans on a word, and
    every one of them is spelled exactly as it is meant to be read. Counting
    those as masks sent the pass to two servers for a song with nothing to
    mend, and left it holding a word it might have talked itself into
    replacing.
    """
    core = _bare(word)[1]
    if MASK not in core or len(core) < 2:
        return False
    lead, tail = core[:1] == MASK, core[-1:] == MASK
    return not (lead and tail and core.strip(MASK))


def _blank(mask: str) -> bool:
    """Whether a mask says nothing about the word at all.

    Two kinds of mask get written, and they are not the same evidence. One is
    written OVER the word -- "n***a", "f**k", "h*es" -- and keeps its length
    and every letter it did not hide. The other stands IN for it: Apple
    writes four stars for a word of any length, and 21 of the 35 masks in the
    track this was measured on hide a five-letter word behind them. The first
    kind can be matched; the second can only be placed.
    """
    return not _bare(mask)[1].strip(MASK)


def _fill(mask: str, word: str) -> str:
    """`mask` with its letters put back from `word`, or "" if that is not it.

    Character for character, and the mask wins every character it wrote: the
    case, the apostrophes and the punctuation that come out of this are the
    document's own, and only what was hidden comes from the donor. A donor
    word of a different length is not the word being hidden -- this kind of
    mask is written over the word rather than in place of it -- and one that
    is masked itself has nothing to give.
    """
    lo, core, hi = _bare(mask)
    said = _bare(word)[1]
    if len(core) != len(said) or MASK not in core or MASK in said or _blank(mask):
        return ""
    out = []
    for m, s in zip(core, said):
        if m != MASK:
            if m.lower() != s.lower():
                return ""
            out.append(m)
        elif s.isalnum() or s in "'’-":
            out.append(s)
        else:
            return ""
    return lo + "".join(out) + hi


def _syl_words(syls: list) -> list[tuple]:
    """(where the word lives, what it says) for every word in one group.

    A word ends at the syllable that is not part of the word after it -- but
    it can also end INSIDE one, and it can be spread across a great many of
    them, and a document that has been through the blends does both:

      "This ****"                 two words under one stamp, which is how
                                  plenty of sources write them
      "*" "*" "*" "*"             one mask relayed onto somebody else's
                                  timing, which lends a stamp per character

    So a word is located by character range rather than by whole syllables --
    a tuple of (syllable, from, to) -- which addresses either. Reading them
    by whole syllables left every mask in a NetEase-timed document unfindable
    and every mask that shared a stamp with its neighbour unmatchable, which
    between them is most of the masks in a blend.
    """
    out, run, word = [], [], ""
    for k, y in enumerate(syls or []):
        if not isinstance(y, dict):
            continue
        text = str(y.get("Text") or "")
        at = 0
        for piece in re.split(r"(\s+)", text):
            if not piece:
                continue
            if piece.strip():
                run.append((k, at, at + len(piece)))
                word += piece
            elif word:
                out.append((tuple(run), word))
                run, word = [], ""
            at += len(piece)
        if word and not y.get("IsPartOfWord"):
            out.append((tuple(run), word))
            run, word = [], ""
    if word:
        out.append((tuple(run), word))
    return out


def _spread(word: str, widths: list) -> list:
    """`word` cut into as many pieces as the mask it is replacing was cut into.

    The pieces of a mask are STAMPS: a relay lends a document its donor's
    timing by cutting the base's text across the donor's syllables, and a run
    of stars gets cut like any other letters. The word going back in has to
    be cut the same way, because those stamps are the timing this document
    was built on and there is nothing here that could re-time them.

    Cut in the mask's own proportions, and cumulatively, so a word that is
    longer or shorter than the mask spreads its difference along the run
    instead of dumping it all in the last piece.
    """
    if len(widths) < 2:
        return [word]
    if len(word) <= len(widths):
        return [word[n:n + 1] for n in range(len(widths))]
    total = sum(widths) or len(widths)
    out, at, done = [], 0, 0
    for n, w in enumerate(widths):
        done += w
        upto = len(word) if n == len(widths) - 1 else round(len(word) * done / total)
        upto = max(at, min(int(upto), len(word)))
        out.append(word[at:upto])
        at = upto
    return out


def _groups_of(it: dict, i: int) -> list[tuple]:
    """One line's groups, as (where, whatever is holding the words).

    A line keeps its words in its lead group's syllables -- or, where the
    source only ever had lines, in the line's own Text and no group at all.
    Reading and writing have to make that choice the same way, and a document
    that has a Lead with no syllables under it is the one that catches a walk
    making it differently: the words are read off the line, and the letters
    put back into a group that never held them. Nothing changes on screen and
    nothing raises.
    """
    lead = it.get("Lead")
    syls = lead.get("Syllables") if isinstance(lead, dict) else None
    out = [(("lead", i), lead if isinstance(syls, list) and syls else it)]
    for k, g in enumerate(it.get("Background") or []):
        if isinstance(g, dict):
            out.append((("bg", i, k), g))
    return out


def _word_slots(items: list) -> list[tuple]:
    """Every word in a document, in the order it is sung.

    (where, which, text): `where` names the group -- ("lead", line) or
    ("bg", line, k) -- and `which` is the syllables that spell the word, or
    the word's place in a line that has no syllables under it at all. The two
    together are enough to find the word again when it is time to write it
    back, and the walk is in document order, so one document's words can be
    aligned against another's straight through.
    """
    out = []
    for i, it in enumerate(items):
        for where, group in _groups_of(it, i):
            syls = group.get("Syllables")
            if isinstance(syls, list) and syls:
                out += [(where, idx, text) for idx, text in _syl_words(syls)]
                continue
            out += [(where, w, word) for w, word
                    in enumerate(str(group.get("Text") or "").split())]
    return out


def masked_words(doc) -> int:
    """How many words in this document have had letters taken out of them."""
    return sum(1 for _w, _i, text in _word_slots(_items(SL.payload(doc or {})))
               if _hidden(text))


def _plain_words(doc) -> list[str]:
    """Every word a document spells, in the order it sings them.

    Read out of the syllables by the same walk that reads the document being
    mended, and not out of each line's own Text. The two do not always spell
    the same line: a source writes its ad-libs into the lead's text as well
    as into a group of their own, or lumps two words under one syllable with
    a zero-width space between them, and either of those is a word that is in
    one stream and not the other. Aligning a stream against a differently
    built one puts every word after the first disagreement a place out, which
    is exactly the offset that leaves a mask unfilled with its own answer
    sitting a word away.
    """
    return [text for _where, _which, text
            in _word_slots(_items(SL.payload(doc or {})))]


def _slot_key(at: int, text: str) -> str:
    """One word, as the aligner compares words.

    A masked word is given a key of its own so that it can never match: it is
    the thing being looked for, and the whole method is that it falls into
    the gap between two stretches that did match. A word with no letters in
    it gets one too -- two documents agreeing that a line contains a comma is
    not the two of them agreeing about a line.
    """
    key = _key(text)
    return key if key and not _hidden(text) else f"\x00{at}"


def _stand_in(mask: str, word: str) -> str:
    """The word a blank mask is standing in for, taken on trust from its place.

    A mask with no letters left in it cannot be matched against anything, so
    the only evidence there is is where it stands -- and this is only ever
    asked where that evidence is as strong as it gets: the words either side
    of the mask are words the donor sings too, and the donor has exactly one
    word between them. The mask keeps its own punctuation and takes the
    donor's letters, case and all, having none of its own to keep.
    """
    lo, _core, hi = _bare(mask)
    said = _bare(word)[1]
    if len(said) < 2 or MASK in said or not any(c.isalnum() for c in said):
        return ""
    return lo + said + hi


def _spine(a: list, b: list) -> list:
    """Anchor pairs (i, j) for two tellings of the same song, in order.

    difflib takes the longest block it can find anywhere and fits everything
    else around it, which on a lyric means it is free to match a chorus to
    the same chorus sung two verses later. What comes back is a perfectly
    good alignment; it is just not the one where the song lines up with
    itself, and a word that has been masked out is then looked for beside the
    wrong neighbours -- or falls into a gap that runs backwards, where there
    is nothing to look at at all.

    So the spine is built first, out of the words that occur exactly ONCE on
    each side: one copy cannot be matched to the wrong copy of itself. The
    longest run of those that moves forward on both sides is an alignment
    that cannot have jumped, and the stretches between them are short enough
    for difflib to be right about. This is patience diff, for the reason
    patience diff exists.
    """
    from difflib import SequenceMatcher

    ca, cb = {}, {}
    for x in a:
        ca[x] = ca.get(x, 0) + 1
    for x in b:
        cb[x] = cb.get(x, 0) + 1
    where = {}
    for j, x in enumerate(b):
        if cb[x] == 1 and ca.get(x) == 1:
            where[x] = j
    once = [(i, where[x]) for i, x in enumerate(a) if x in where]
    tails, back, at = [], [None] * len(once), []
    for n, (_i, j) in enumerate(once):
        k = bisect.bisect_left(tails, j)
        if k == len(tails):
            tails.append(j)
            at.append(n)
        else:
            tails[k], at[k] = j, n
        back[n] = at[k - 1] if k else None
    spine = []
    n = at[-1] if at else None
    while n is not None:
        spine.append(once[n])
        n = back[n]
    spine.reverse()

    out, i0, j0 = [], -1, -1
    for i1, j1 in spine + [(len(a), len(b))]:
        if i1 > i0 + 1 and j1 > j0 + 1:
            sm = SequenceMatcher(None, a[i0 + 1:i1], b[j0 + 1:j1], autojunk=False)
            out += [(i0 + 1 + i + t, j0 + 1 + j + t)
                    for i, j, n in sm.get_matching_blocks() for t in range(n)]
        if i1 < len(a):
            out.append((i1, j1))
        i0, j0 = i1, j1
    return out


def _unglue(mask: str, theirs: list, at: int) -> str:
    """A mask that has lost the space between it and the word beside it.

    A relay lends a document somebody else's timing by cutting its words
    across the donor's stamps, and the boundary between two words can go with
    the cut: what is left under one stamp is "the*****", which is a word
    nobody ever sang and which nothing could ever match, because there is
    nothing there to match. It is the commonest way a mask survives a blend
    -- on the three blends measured here it is most of them.

    The donor has both words, so the glue is undone against it rather than
    guessed at: the letters have to BE the donor's word at that place --
    exactly, or by filling a mask of their own -- and only then may the run
    of stars beside them take the word next to it. The space comes back with
    them, and unlump gives the two halves a stamp each.
    """
    lo, core, hi = _bare(mask)
    lead = len(core) - len(core.lstrip(MASK))
    tail = len(core) - len(core.rstrip(MASK))
    if bool(lead) == bool(tail):
        return ""
    said, run = (core[:-tail], core[-tail:]) if tail else (core[lead:], core[:lead])
    if not any(c.isalnum() for c in said):
        return ""
    j = at if tail else at + 1
    k = at + 1 if tail else at
    if not (0 <= j < len(theirs) and 0 <= k < len(theirs)):
        return ""
    if MASK in said:
        got = _fill(said, theirs[j])
    else:
        got = said if _key(said) and _key(said) == _key(theirs[j]) else ""
    if not got:
        return ""
    hidden = _stand_in(run, theirs[k]) if _blank(run) else _fill(run, theirs[k])
    if not hidden:
        return ""
    return f"{lo}{got} {hidden}{hi}" if tail else f"{lo}{hidden} {got}{hi}"


def _like(mask: str, word: str) -> bool:
    """Whether a donor word could be what a DAMAGED mask was written over.

    A weaker question than the one _fill asks, for the case where the mask can
    no longer answer the strong one. A mask is written over its word and keeps
    its length -- but a blend cuts a document's words across its donor's
    stamps, and a mask cut that way can lose characters to the syllable next
    door: "C**ked," comes back as "c**k," and is four letters where the word
    is six. Matched character for character it fits nothing, and it never
    will.

    What its letters still do is appear, in order, in the word it was written
    over. A word the singer did not sing has no reason to spell them in that
    order, and this is only ever asked where the placing is already as good as
    it gets -- one word of ours between two words both documents share, and
    one word of theirs in the same place.
    """
    said = _bare(word)[1].casefold()
    core = _bare(mask)[1].casefold()
    if not said or MASK in said or core.strip(MASK) == "":
        return False
    at = 0
    for c in core:
        if c == MASK:
            continue
        at = said.find(c, at) + 1
        if at <= 0:
            return False
    return True


def _opens(slots: list, at: int) -> bool:
    """Whether this word begins a line, in the document it came out of.

    A group start, or the word before it ending a sentence. Both are reasons
    for a capital that have nothing to do with the word itself, which is the
    whole of what this is asked for.
    """
    if at <= 0 or slots[at - 1][0] != slots[at][0]:
        return True
    return any(c in ".!?\u2026" for c in _bare(slots[at - 1][2])[2])


def _uncapped(mask: str, got: str, opens: bool, they_open: bool) -> str:
    """`got` with a capital that belonged to the DONOR's line break taken off.

    Where a line ends is an editorial decision and two sources make it
    differently -- which is why _unmask_with aligns them as one stream of
    words in the first place. A capital at the start of a donor's line is
    that decision showing, not a fact about the word: Musixmatch breaks
    "...eight in the process, nigga tryna tippy-toe..." after "process" and
    capitalises what follows, and Apple, which writes the whole of it as one
    line with two blank masks in it, was handed that capital back in the
    middle of its line.

    So it is taken off again -- but only where every part of the reason is
    present. The mask has to have hidden the first letter, because a mask
    that kept one has already said what the case is (see _recase and _fill).
    The donor's word has to begin the donor's line, because a capital
    anywhere else is the donor spelling a name. And ours must not begin
    ours, or the capital is right where it stands whatever it came from.
    A word in capitals throughout is left alone: that is a spelling too, and
    lowering its first letter alone would make a mess of it rather than a
    sentence.
    """
    if opens or not they_open:
        return got
    if next((c for c in _bare(mask)[1] if c != MASK), ""):
        return got
    lo, said, hi = _bare(got)
    if not said[:1].isupper() or any(c.isupper() for c in said[1:]):
        return got
    return lo + said[:1].lower() + said[1:] + hi


def _recase(mask: str, word: str) -> str:
    """`word` wearing the mask's own capital, where the mask kept one."""
    first = next((c for c in _bare(mask)[1] if c != MASK), "")
    if first.isupper() and word[:1].islower():
        return word[:1].upper() + word[1:]
    if first.islower() and word[:1].isupper():
        return word[:1].lower() + word[1:]
    return word


def _only_fit(mask: str, theirs: list, memo: dict) -> str:
    """The word the donor is hiding, when the donor only knows one that fits.

    The fallback for a mask the alignment could not put a finger on. Asked of
    the whole donor rather than of a window, so it is only allowed an answer
    the donor is unanimous about: "n***a" has one spelling in any document
    that has the word at all, and a mask like "****" that half the four
    letter words in the song would fit gets no answer from here, which is the
    right answer. The donor is already known to be this recording -- nothing
    reaches here until it has matched half the document.
    """
    if mask in memo:
        return memo[mask]
    said = {}
    for word in theirs:
        got = _fill(mask, word)
        if got:
            said[got.casefold()] = got
            if len(said) > 1:
                break
    memo[mask] = next(iter(said.values())) if len(said) == 1 else ""
    return memo[mask]


def _unmask_with(doc, donor):
    """`doc` with every mask this donor can fill filled in, and how many.

    The two documents are aligned as one long stream of words rather than
    line by line, because where a line ends is an editorial decision and two
    sources make it differently -- and because a mask cannot match anything,
    so it lands in a gap between matched stretches wherever the lines fall.
    What is in the donor's side of that gap is what the mask is hiding.
    """
    body = SL.payload(doc or {})
    items = _items(body)
    mine = _word_slots(items)
    holes = [k for k, (_w, _i, text) in enumerate(mine) if _hidden(text)]
    yours = _word_slots(_items(SL.payload(donor or {})))
    theirs = [text for _where, _which, text in yours]
    if not holes or not theirs:
        return doc, 0

    a = [_slot_key(k, text) for k, (_w, _i, text) in enumerate(mine)]
    b = [_key(w) or f"\x01{k}" for k, w in enumerate(theirs)]
    anchors = _spine(a, b)
    real = sum(1 for x in a if not x.startswith("\x00"))
    if not real or len(anchors) < UNMASK_SHARE * real:
        return doc, 0

    fixes, mends, only = {}, 0, {}
    for k in holes:
        mask = mine[k][2]
        at = bisect.bisect_left(anchors, (k, -1))
        i0, j0 = anchors[at - 1] if at else (-1, -1)
        i1, j1 = anchors[at] if at < len(anchors) else (len(a), len(b))
        want = j0 + (k - i0)
        lo = hi = 0
        if j0 < want < j1:
            lo = max(j0 + 1, want - UNMASK_REACH)
            hi = min(j1, want + UNMASK_REACH + 1)
        got, src = "", None
        if _blank(mask):
            if i0 < k < i1 and j0 < want < j1 and i1 - i0 == j1 - j0:
                got, src = _stand_in(mask, theirs[want]), want
        else:
            for j in sorted(range(lo, hi), key=lambda x: (abs(x - want), x)):
                got = _fill(mask, theirs[j])
                if got:
                    src = j
                    break
        if not got and j0 < want and want + 1 < j1:
            got = _unglue(mask, theirs, want)
        if not got and not _blank(mask):
            got = _only_fit(mask, theirs, only)
        if not got and not _blank(mask) and i1 - i0 == 2 and j1 - j0 == 2 \
                and 0 <= want < len(theirs) and _like(mask, theirs[want]):
            got, src = _recase(mask, _stand_in(mask, theirs[want])), want
        if got:
            if src is not None:
                got = _uncapped(mask, got, _opens(mine, k), _opens(yours, src))
            fixes[(mine[k][0], mine[k][1])] = got
            mends += 1
    if not mends:
        return doc, 0
    fresh = {k: v for k, v in body.items() if k not in ("Content", "Lines")}
    fresh["Content"] = _unmask_write(items, fixes)
    if isinstance(doc, dict) and isinstance(doc.get("Content"), dict):
        fresh = {**doc, "Content": fresh}
    return fresh, mends


def _retext(text: str, swaps: list) -> str:
    """A line's own text, with each mask swapped for the word it was hiding.

    One occurrence each, left to right, which is what makes a line with the
    same mask written twice in it come out right: nothing filled in can
    contain a mask, so the next search passes over what has just been put in.
    """
    for mask, filled in swaps:
        at = text.find(mask)
        if at >= 0:
            text = text[:at] + filled + text[at + len(mask):]
    return text


def _unmask_group(where, group: dict, fixes: dict) -> tuple:
    """One group with its masks filled in, and the swaps that were made."""
    swaps = []
    syls = group.get("Syllables")
    if isinstance(syls, list) and syls:
        said = list(syls)
        edits: dict = {}
        for idx, text in _syl_words(said):
            got = fixes.get((where, idx))
            if not got:
                continue
            swaps.append((text, got))
            bits = _spread(got, [hi - lo for _k, lo, hi in idx])
            for (k, lo, hi), bit in zip(idx, bits):
                edits.setdefault(k, []).append((lo, hi, bit))
        if not swaps:
            return group, swaps
        for k, rows in edits.items():
            was = str(said[k].get("Text") or "")
            for lo, hi, bit in sorted(rows, reverse=True):
                was = was[:lo] + bit + was[hi:]
            said[k] = {**said[k], "Text": was}
        group = {**group, "Syllables": said}
    else:
        text = str(group.get("Text") or "")
        for w, word in enumerate(text.split()):
            got = fixes.get((where, w))
            if got:
                swaps.append((word, got))
        if not swaps:
            return group, swaps
    if isinstance(group.get("Text"), str) and swaps:
        group = {**group, "Text": _retext(group["Text"], swaps)}
    return group, swaps


def _unmask_write(items: list, fixes: dict) -> list:
    """The document again, with the words that were hidden written into it."""
    out = []
    for i, it in enumerate(items):
        own, fresh = it, dict(it)
        bg = list(it.get("Background") or [])
        for where, group in _groups_of(own, i):
            got, said = _unmask_group(where, group, fixes)
            if not said:
                continue
            if where[0] == "bg":
                bg[where[2]] = got
            elif group is own:
                fresh = dict(got)
            else:
                fresh["Lead"] = got
                if isinstance(fresh.get("Text"), str):
                    fresh["Text"] = _retext(fresh["Text"], said)
        if bg:
            fresh["Background"] = bg
        out.append(fresh)
    return out


def uncensor(doc, tid: str, meta: dict, enabled=None, on_skip=None):
    """A document with the words its source masked put back into it.

    Costs nothing at all on a document that has none: the masks are counted
    before anybody is asked anything, and the great majority of songs have
    none to count. Where there are some, the donors are asked in order and
    each is given whatever the one before it could not fill -- Musixmatch and
    LRCLIB do not mask the same words, and neither of them masks many.

    `enabled` is the set of sources the user has switched on, so a donor
    turned off for the chain is not quietly asked here either.

    A recording that is ITSELF the clean cut is left exactly as it is, and
    `on_skip` is told why so the window can say so. See clean_edit: filling a
    mask whose word is not in the audio does not restore anything, it writes a
    word over a silence.

    Either refusal hands back `doc` -- the very same object, never a copy.
    The window tells a new lyric from the one it is drawing by identity, and a
    document that says what the last one said must not cost a rebuild.
    """
    if not masked_words(doc):
        return doc
    why = clean_edit(doc, tid, meta, enabled=enabled)
    if why:
        if on_skip is not None:
            try:
                on_skip(why)
            except Exception:                            # noqa: BLE001
                pass
        return doc
    known = {n: fn for n, fn in PROVIDERS}
    out = doc
    for name in UNMASK_FROM:
        fn = known.get(name)
        if fn is None or (enabled is not None and name not in enabled):
            continue
        try:
            donor = _asks(name, lambda fn=fn: fn(tid, meta))
        except Exception:                                # noqa: BLE001
            donor = None
        if not donor:
            continue
        got, mends = _unmask_with(out, donor)
        if mends:
            out = unlump(got)
            if not masked_words(out):
                break
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
            own, b_e = new.get("EndTime"), _line_end(it)
            b_nxt = SL.line_start(bit[i + 1]) if i + 1 < len(bit) else None
            sung = max([y["EndTime"] for y in syls[:-1]] or [syls[0]["StartTime"]])
            shift = (start - SL.line_start(it)) if isinstance(SL.line_start(it), (int, float)) \
                and isinstance(start, (int, float)) else 0.0
            if (isinstance(own, (int, float)) and isinstance(b_e, (int, float))
                    and isinstance(b_nxt, (int, float)) and b_nxt - b_e >= BLEND_TAIL
                    and isinstance(end, (int, float))
                    and end - (b_e + shift) > BLEND_HOLD
                    and (b_e + shift) >= max(sung, syls[-1]["StartTime"] + 0.05)):
                end = b_e + shift
                if syls[-1]["EndTime"] > end:
                    syls = syls[:-1] + [{**syls[-1], "EndTime": end}]
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
    doc["_lifted"] = True
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
