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
    the blends     somebody else's within-line timing under Apple Music's
                   lines. Two lookups rather than one, or three where a second
                   donor is kept for the lines the first cannot place, so they
                   are off unless asked for -- and they stand themselves down
                   without spending anything where a source ranked in front of
                   their donors already answered word-timed.
    LyricsPlus     the syncs LyricsPlus' own readers timed and submitted.
                   The one catalogue behind that door that is nobody else's,
                   and now the only thing asked of it: see LYRICSPLUS_OWN.
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
"""

from __future__ import annotations

import bisect
import functools
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

# 10: the blends are ordered by their donors' ranking now, and there is a
# fifth of them. Every stored answer was chosen under the old order, which
# asked QQ Music first whatever the user had said, so they are not answers to
# the question this asks any more.
# 11: a blend's second donor is asked about the lines the first one placed
# badly, not only about the ones it could not place at all. A stored blend
# still has those lines where the first donor dropped them -- on the songs
# measured here that is a line 23 seconds out of place, and a dozen more
# between one and five. The cost of saying so is one cold walk, 3.7s against
# 0.001s off the disk, on the songs stored under 10 -- 127 of them on the
# machine this was written on, the rest of that directory having already
# aged out under an earlier bump.
# 12: a blend stands down where a source ranked in front of its donors came
# back word-timed, so a stored answer credited to a blend may be one this
# walk would no longer build.
# 13: four things, and every one of them changes the document rather than
# which document wins. A document is no longer called word-synced on the
# strength of one timed line, which on the songs where Apple wraps a single
# lead in a span is the difference between a blend and no blend at all; a
# line's end may follow the base past the start of the line after it, and may
# not go further than that; a voice the document already sings is not lifted
# beside itself; and the second donor has to place a line steadily before it
# speaks for one nobody has placed. Stored answers were built before all of
# it -- and so is every answer credited to Musixmatch, which is asked at its
# own door now and comes back word-timed where it used to come back as lines.
# 14: the running order is followed between two documents timed alike. The
# walk used to hand the song to whichever of them wrote the most letters,
# reading "longer" as "the other one is missing a section" -- and a source
# that stamps every sung stutter is a quarter longer than the same lyric
# written once, so Musixmatch took songs off sources ranked ten places above
# it, 64 of them on the machine this was written on. A stored answer chosen
# that way is one this walk would no longer choose.
# 15: the LyricsPlus door is asked for LyricsPlus' own submissions and for
# nothing else (see LYRICSPLUS_OWN). Every document it handed over under
# another catalogue's name is one no walk will fetch again -- Apple Music's
# scrape, the QQ copy behind QQ's own endpoint, the line-level Musixmatch --
# and so is every blend that took its base from the first of those. A stored
# answer from any of them is an answer to a question this no longer asks.
REVISION = 15

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
# How much of a document has to be word-timed before the document is. Measured
# only in the sense that it separates cleanly: of the 277 documents cached on
# the machine this was written on, 218 of the 219 word-synced ones time every
# line and the last times 90% of them, so anything between a tenth and four
# fifths says the same thing about all of them. Half, because it is the share
# that needs no argument.
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
# Whether anybody still wants the answer to the walk this thread is part of.
#
# A walk cannot be interrupted -- it is a dozen blocking socket reads -- but it
# can be asked, and the places worth asking are the ones where it is about to
# spend something: before a request goes out, and again after it has waited
# its turn at a host gate. The player skips, the walk in hand becomes work for
# a screen that has moved on, and the requests it has not made yet are pure
# cost to the walk somebody IS waiting on -- which is queued behind them at
# the same two permits.
#
# Held per thread rather than passed from provider to provider: every one of
# them takes (tid, meta, local) and none of them has any business knowing
# about this. _parallel carries it onto the threads it starts, which is the
# only place the walk fans out, so the whole chain inherits it from the one
# call that set it.
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


def _under(alive, fn, faults=None, who=None):
    """`fn`, run as part of the walk `alive` speaks for."""
    was = (getattr(_WALK, "alive", None), getattr(_WALK, "faults", None),
           getattr(_WALK, "who", ""))
    _WALK.alive = alive
    if faults is not None:
        _WALK.faults = faults
    if who is not None:
        _WALK.who = who
    try:
        return fn()
    finally:
        _WALK.alive, _WALK.faults, _WALK.who = was


# --------------------------------------------------------------------------
# What went wrong on the walk, and who it went wrong for.
#
# A provider that answers None is saying two different things at once -- "I
# have not got this song" and "I could not be reached" -- and the second one
# is the user's business, because it is the running order not being followed
# for a reason that is nobody's ranking. The three request funnels write down
# what happened instead of an answer, filed under whichever provider the walk
# is asking at the time, and fallback() hands the list to its caller when the
# walk ends.
#
# A miss is not a fault. 404 is how every one of these doors says it has not
# got the song and half of any library is a 404 somewhere, so it is the one
# status that is passed over in silence. Everything else -- a timeout, a
# refused connection, a 5xx, a rate limit that outlasted its one retry -- is
# worth saying out loud once.
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


# How many requests a host is asked to hold at once. Four is what an ordinary
# database will not notice. The LyricsPlus door gets two, because at ten
# seconds a request a permit there is a long thing to be holding and the
# look-ahead is warming three tracks behind whatever is playing; two permits
# is two tracks in flight rather than four, and the track on screen waits one
# request rather than three to get in. It has one caller now (see
# LYRICSPLUS_OWN), so two is also two tracks, not two halves of one.
_HOST_CAP = {urllib.parse.urlsplit(YOULY_BASE).netloc: 2}
_HOST_CAP_DEFAULT = 4
# HOW LONG A HOST IS GIVEN. TIMEOUT suits a database lookup, which is what
# most of these are: a search and a row, answered in well under a second.
#
# The LyricsPlus door is not that, and it is not that for anything asked of
# it. Measured over ten songs on 2026-09-05, /v1/ttml/get took 8.2s to 17.4s
# to answer AT ALL, hits and misses alike, and /v2 took 3.9s to 10.0s on a
# song it had not seen before (0.06s on the second ask, so it caches). Asked
# again on 2026-09-07 with the pin varied and nothing else, it took 8.7s to
# 12.8s to say 404 or 502 -- so the wait is the door itself and not the
# upstream behind it: pinning its own submissions costs exactly what pinning
# Apple Music cost.
#
# Every one of those is over TIMEOUT. So the door timed out on nearly every
# song -- and its "I have not got it" arrived as a timeout too, which is the
# worse half: a 404 is passed over in silence and a timeout is reported, so
# an ordinary miss was announced as a catalogue being unreachable. That is
# the notification that would not stop, and Apple Music was up throughout.
#
# The wait is honest, then, and the way to stop paying it several times over
# is to knock once. Nothing else waits on it: the walk is run in parallel and
# hands over each answer as it lands (see `landed`), so a door that takes ten
# seconds costs the screen nothing -- whatever else answered is already up,
# and LyricsPlus takes over when it arrives if the order asks for it.
_HOST_PATIENCE = {urllib.parse.urlsplit(YOULY_BASE).netloc: 20.0}


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
        # Asked again on the way in, because the wait for a permit is where a
        # dropped walk spends most of what it costs everybody else: the host
        # that gates hardest is the slowest one. Handing the permit straight
        # back is the whole point.
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
            text += tail.strip()
        nxt = "".join(spans[i + 1].itertext()) if i + 1 < len(spans) else ""
        if spaced:
            part = not (tail and tail != tail.strip())
        elif not (_latin(text) or _latin(nxt)):
            part = True
        else:
            part = (not any(c.isalnum() for c in text)
                    or bool(nxt) and not nxt[0].isalnum())
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
            _repair(timed, begin, end)      # the same dicts, mended in place
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
        up = max(lo, up)        # the sane neighbours may themselves overlap
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


def _credits(root) -> tuple[list[str], str, dict]:
    """Who wrote the song, who timed this copy of it, and what song it is.

    Three conventions in play, all in the same <head>. Apple writes
    <songwriters><songwriter>, and Lyrics+ echoes it verbatim whichever upstream
    it got the words from. LyricsPlus adds <lyricsplus:curator> naming whoever
    submitted the sync. amll-ttml-db files the same fact as an <amll:meta
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
        # Whether an ad-lib is written BEFORE the words it answers -- the
        # "(Promise I like it like—) Promise I like it like that" shape. On a
        # timed one the times say so and the player works it out for itself
        # (spicy_lyrics.BG_LEAD); on one nobody has timed yet, where it sits
        # in the <p> is the only thing that says it, so that is read here.
        ahead = not (p.text or "").strip()
        for sp in p:
            role = _attr(sp, "role") if _tag(sp) == "span" else None
            if role == "x-bg":
                g = _group(sp, spaced, bg=True)
                if ahead and not isinstance(g.get("StartTime"), (int, float)):
                    g["LeadIn"] = True
                if not g["Syllables"]:
                    # An ad-lib written as plain text inside its wrapper,
                    # which is how one that has not been timed yet comes out.
                    # The lead's text is joined from everything that is NOT an
                    # x-bg, so a backing vocal dropped here is dropped from
                    # the document.
                    g["Text"] = _unbracket("".join(sp.itertext()).strip())
                if g["Syllables"] or g.get("Text"):
                    bg.append(g)
            elif _tag(sp) == "span" and not role:
                ahead = False           # a word of the lead, written as a span
            # ...and the lead's own words where it is written in no span at
            # all: those arrive as the tail of whatever came before them.
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
            # Nothing for an ad-lib to come in ahead of. A line that is one
            # bracket and nothing else has a first voice, not an answering
            # one, and calling it a lead-in put a space where no lead was.
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
    # By the stamps, not by the shape. A file can spell its words out in spans
    # and time none of them -- an unsynced lyric somebody has already cut into
    # syllables -- and that is a static document carrying its splits, not a
    # word-synced one.
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
# Bracketed text that is in the way of two catalogues agreeing about which
# SONG this is. Which is a different question from which CUT of it is playing
# -- see ALT_CUT, which answers that one, and answers it off the title as it
# was written, before any of this.
#
# "remix" belongs here for the first question even though it is decisive for
# the second, and the two are not in conflict. Kugou files Rogue's remix of
# "Galaxies" as "Galaxies (remix：Rogue)" and Spotify calls it "Galaxies -
# Rogue Remix": stripped, both are "galaxies" and the two catalogues agree
# they are talking about the same song, which is all _norm is for. Taking
# the word out of here to keep the remix apart from the instrumental looked
# like the same fix and was not -- it left those two spellings as
# "galaxiesremixrogue" and "galaxiesrogueremix", so Kugou stopped answering
# for the remix at all, while the instrumental was still being handed the
# remix's words by every other route. ALT_CUT is where that is decided.
#
# The one caller with no ALT_CUT test to fall back on is the amll index,
# which is a dict lookup with no hit to examine. It keys on _song_key.
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


# ONE CATALOGUE, ONE KNOCK.
#
# This door used to be four of the chain's providers at once. Apple Music was
# reached through it, so was QQ Music where QQ's own endpoint had nothing, so
# was Musixmatch where the app endpoint came back short of word timing, and so
# were the blends when nothing already in hand had Apple word-timed. Each of
# those is one or two requests, on a host that answers in eight to thirteen
# seconds whatever it is asked (see _HOST_PATIENCE) and holds two requests at
# a time (see _HOST_CAP) -- so a single walk could queue eight ten-second asks
# through a two-wide gate and spend the better part of a minute in here while
# every other source in the chain had long since answered. The blends wait on
# the round before them, so they waited on that too, and the blends are what
# usually wins.
#
# It is asked for one thing now: the syncs LyricsPlus' own readers timed and
# uploaded, which is the one catalogue behind it that is nobody else's and the
# only one it is the only door on. Apple Music comes from BiniLyrics, QQ Music
# from QQ, Musixmatch from Musixmatch -- each of them a door of its own that
# answers in a fraction of a second, and each of them the source's real
# catalogue rather than this server's copy of it. What that costs is the songs
# the scrape had and the real door does not: BiniLyrics indexes by ISRC and
# cannot answer for a recording it has not got, and Musixmatch's line-level
# scrape is gone for the tracks its app endpoint cannot match. What it buys is
# one knock instead of eight, which is the difference between a walk that is
# over in a second or two and one the blends reach a minute late.
#
# from_youly still takes a `source` of anything the server knows, because
# eval_blends builds its jar of donors through it and a measurement wants the
# scrape it is measuring against. Nothing in the CHAIN passes anything but
# this.
LYRICSPLUS_OWN = "lyricsplus"


# What the server may answer with when an upstream is asked for BY NAME.
#
# It does not always honour the pin, and there is exactly one door it does
# not: there is no "lyricsplus" filter behind it. Asked for LyricsPlus' own
# submissions it answers with them where it has them, with nothing where it
# has neither -- and, on a good third of the songs tried, with its own
# Apple+QQ reconciliation instead ("qaple"), which is not LyricsPlus' words
# at all. Filed under the slot that asked, that credits a community which
# never wrote them, and it wins the walk from a rank the user gave to
# something else: every cached document this program has ever filed under
# lyricsplus is a qaple.
#
# Every other pin is honoured exactly -- apple, qq, musixmatch and deezer all
# come back as themselves -- so refusing an answer that names a different
# upstream costs nothing anywhere else.
_YOULY_WON = {"apple": {"apple"}, "qq": {"qq"}, "deezer": {"deezer"},
              "musixmatch": {"musixmatch", "musixmatch-word"},
              "lyricsplus": {"lyricsplus"}}


def _honoured(source: str | None, won: str) -> bool:
    """Did the server answer with the upstream it was asked for?

    An answer with nothing to check -- raw TTML, no envelope, no winner
    named -- is taken at its word. There is no way to tell, and refusing on
    a silence would throw away the answers that arrive in the documented
    shape.
    """
    want = _YOULY_WON.get(str(source or "").lower())
    return not want or not won or won.lower() in want


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
    """LyricsPlus, asked once per track and upstream however many callers want it."""
    return _once(("youly", tid, _norm(meta.get("title") or ""),
                  _norm(meta.get("artist") or ""), round(float(meta.get("length") or 0)),
                  source or ""),
                 lambda: _youly(tid, meta, source))


def _youly(tid: str, meta: dict, source: str | None = None) -> dict | None:
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

    The two go out TOGETHER, and the first shape still wins where both
    answer. They used to go one after the other, which read as thrift and
    cost more than it saved: this door takes eight to thirteen seconds to
    answer whatever it is asked (see _HOST_PATIENCE) and it has not got most
    of what it is asked for, so the common path on a collaboration was a
    ten-second miss followed by a second ten-second ask -- twenty seconds of
    a walk that the blends, in the round after, were waiting on. Asked at
    once the provider costs one wait however many shapes the question has.
    What it spends is one extra request on the tracks where the first shape
    would have answered, which is the rarer half and is a request either way
    when it does not.

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
    tried = _parallel({str(i): (lambda q=q: _youly_ask(q))
                       for i, q in enumerate(asks)})
    got = None
    for i in range(len(asks)):
        answer = tried.get(str(i))
        # A pin the server could not honour is a different catalogue's
        # document, not this one's -- see _honoured. The other shape of the
        # question is still read; it sometimes reaches the copy the first one
        # missed. In the order they were asked in, so that the shape most
        # likely to be the right recording is the one taken where both
        # answered.
        if answer is not None and _honoured(source, answer[1]):
            got = answer
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


def from_lyricsplus(tid: str, meta: dict, local=None) -> dict | None:
    """LyricsPlus' own submissions.

    Everything else asked of that server belongs to somebody else -- Apple
    Music, Musixmatch, QQ Music, each pinned by name so it can be ranked as
    the catalogue it is. This is the one upstream behind the door that is
    LyricsPlus' own: TTML its readers timed and uploaded, carrying the
    curator's name in the header where Apple's carries only the songwriters
    (see _credits).

    It lost its slot when the menu stopped listing doors and started listing
    catalogues, and that was the right thing to do to "Lyrics+" -- the name
    then meant the server's own race between its upstreams, and a race cannot
    sit anywhere in an order of sources. What went with it was this, which is
    not a race and not anybody else's words. Asked for by name it ranks like
    the rest of them.

    The only caller on that door now, and so the only reason the walk waits
    on it at all: see LYRICSPLUS_OWN.
    """
    return from_youly(tid, meta, source=LYRICSPLUS_OWN)


def from_qq(tid: str, meta: dict, local=None) -> dict | None:
    """QQ Music's own document, its lines as well as its timings.

    The blends take QQ's word timing and lay it under Apple's lines, which is
    usually the better document -- Apple's wording, casing and line splits are
    the ones this player is built around. Usually is not always: QQ writes
    ad-libs the Apple copy simply does not have, on their own lines and in
    their own time, and where reconciling the two loses them the source on its
    own is the honest answer.

    Asked of QQ directly, and only of QQ; see _qq. The LyricsPlus door used
    to be kept behind this one, on the grounds that the two fail on different
    songs and its copy was worth one request on the handful QQ's own endpoint
    cannot find. One request there is ten seconds (see LYRICSPLUS_OWN), it
    was spent on every song QQ missed rather than on the handful, and it was
    spent inside the round the blends are waiting on -- for a document that,
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
# A credit line, stamped and timed like a lyric by every source that writes
# one. Kugou puts "Lyrics by：Vivian Weeks" and "Composed by：Vivian Weeks" at
# the top of a great many songs, in the Latin script and with the fullwidth
# colon, which the Chinese-only pattern walked straight past -- so they were
# sung at the listener over the intro and written into every TTML saved from
# here. The colon is required: it is what separates a credit from a lyric that
# happens to open with the word "Music".
# The Chinese half is not anchored the way the English half is, because the
# roles are QUALIFIED and the qualifier comes first: NetEase's copy of a
# Coldplay track credits 电吉他 (electric guitar), 低音吉他 (bass guitar),
# 音频工程师 (audio engineer), 助理母带工程师 (assistant mastering engineer) and
# 附加制作 (additional production), and a pattern demanding 吉他 or 母带 at the
# start of the line walks past every one of them. They were sung at the reader
# over the outro. So a few characters are allowed either side of the role --
# ahead of it for the qualifier, behind it for 人 or 师 -- while the colon
# still does the work of separating a credit from a lyric.
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
        # Before anything is weighed: a hit whose title claims a version we
        # did not ask for is not a worse copy of this recording, it is a
        # different one. It has to be thrown out rather than scored down,
        # because the other two signals carry it anyway -- NetEase's copy of
        # "Galaxies (Rogue Remix)" is credited to Protostar and is five
        # seconds off the instrumental, which is a byline and a duration, and
        # two of the three is all this asks for. See ALT_CUT.
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
    """NetEase Cloud Music, asked once per track however many callers want it."""
    return _once(("netease", tid, _norm(meta.get("title") or ""),
                  _norm(meta.get("artist") or ""), round(float(meta.get("length") or 0))),
                 lambda: _netease(tid, meta))


def _netease(tid: str, meta: dict) -> dict | None:
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
        # Our line as this donor would have written it. Where we put an ad-lib
        # inside the line and the donor files it beside one, its letters can
        # only be matched against the words of some OTHER line -- and then the
        # line they were matched into swallows the syllables of the line after
        # it. On "Never Too Late" that is Apple's "It's never too late (It's
        # never too late)" reaching forward into NetEase's "It's not", which
        # left the next line two words it could not relay and no timing at
        # all. _peel_bracket takes those brackets out of the lyric a few lines
        # further on and gives them the donor's own timing for the ad-lib, so
        # this is reading the line the way it is about to be written anyway.
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
        out.append({"Text": SL.syllables_text(take),
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
    # Longest non-decreasing run through the starts, by patience sorting over
    # the positions rather than the values, so what it keeps is the lines that
    # were already in order.
    tails, back = [], [len(out)] * len(out)
    for i, v in enumerate(at):
        if not isinstance(v, (int, float)):
            continue
        lo, hi = 0, len(tails)
        while lo < hi:                       # rightmost slot this start fits
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


# How much longer than the room it is going into a BORROWED rhythm may be.
#
# Only borrowed ones are asked. A line the pairing placed normally is on the
# donor's own clock and its end is dealt with further down, by believing the
# base about where the singing stops. A rhythm lifted off a donor line and
# anchored somewhere else has no such guarantee: nothing has checked that it
# is even the right LENGTH for the line it is being put in.
#
# LEDGER's "Foreigner" is what says it has to be checked. Kugou writes "Hold
# out your hand of riches and display your royalty" as a line running 83.58
# to 95.70 -- twelve seconds, because it smears the first word across an
# eight-second instrumental: "H" at 83.58, "o" at 86.51, "ut" at 92.22. The
# line sync says that line is 92.18 to 95.62. Anchored on that and left
# unchecked, its words ran eight seconds into the four lines after it.
#
# The test is the LENGTH and not the overrun, because the base's line spacing
# is approximate and a donor line that is a fraction long is ordinary -- a
# singer really does hold a word into the line after. Over the nine lines
# this repairs on that song, the ratio of the donor's span to the room the
# base leaves runs 0.35, 0.75, 0.77, 0.93, 0.95, 1.11, 1.18, 1.18 ... and
# then 3.52, which is the smeared one. There is nothing between 1.18 and
# 3.52 and the cut sits in the middle of that gap.
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


# How steady the second donor's own answer has to be before it is taken. It is
# measured the same way as the first donor's -- against its OWN neighbours, not
# against the first donor's line -- because the two are being asked the same
# question about the same line sync, and a donor that agrees with the lines
# around it is placing this one. Measured at 0.35 as well and 0.5 is the better
# of the two, by about as much as the whole change is worth: over the 46 songs
# with a hand-timed file here, 13.36% of Apple+NetEase+Kugou's words land more
# than half a second out at 0.5 against 13.43% at 0.35.
BLEND_STEADY = 0.5
# How much of a line may be riding on onsets nobody measured before the second
# donor is asked about it. See _guessed.
BLEND_PATCHY = 0.34
# ...and by how much the second donor has to beat that. Not a tuned number, a
# guard: two donors tokenise differently and the coarser of them guesses a
# little more on every line in the song, which is not a reason to swap a clock.
BLEND_BETTER = 0.2


# How much nearer the base's line sync the second donor's whole clock has to
# sit before it takes the song off the first. See in_order, which is where the
# measuring and the evidence are.
BLEND_LEAD = 0.05
# ...and how much less steady it is allowed to be about sitting there.
BLEND_WOBBLE = 0.05


# How much steadier one blend's donor has to be than another's before that
# outranks the order the user put the sources in.
#
# `_steady` is the donor's drift against the base's LINE SYNC, spread rather
# than offset: how far each line sits from where its own neighbours put this
# donor. A donor that agrees with the line sync line by line is placing the
# song; one that wanders is not, and the wandering is what a listener hears
# as a sync being "off in places" even when the song as a whole lines up.
#
# It predicts which donor is actually better. Over the songs here with a
# hand-timed file, every pair of donors that both answered and could both be
# scored against those timings -- nine pairs, the rest being byte-identical
# documents QQ and Kugou both serve -- the one with the lower `_steady` was
# also the one whose words really sat closer to the hand-placed ones. Nine
# out of nine.
#
# The margin is what keeps a ranking from being second-guessed on noise, and
# it is set on the BLENDS rather than on the donors, because the blends are
# what the choice is actually between. Over seven songs where two blends
# could both be scored against a hand-timed file:
#
#     margin   flips that help   flips that hurt   left to the order
#      0.005          2                 0                  3
#      0.015          2                 0                  4
#      0.020          1                 0                  5
#      0.030          1                 0                  6
#
# Nothing hurts at any setting, so the margin is only deciding how much is
# left to the order. 0.015 is the loosest one that still catches both real
# calls -- Bad Computer's "Chasing" by 0.043 and Athena's "Eternal" by 0.019
# -- while leaving Feint's "Do Better", which differs by 0.006 and is a
# genuine tie, to the ranking.
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
    # Nothing can beat a shift smaller than the margin, so the second donor
    # is not measured at all in the case that is nearly every song. _clock
    # re-streams to answer, which is the same work _blend is about to do.
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
              "lyricsplus": "LyricsPlus", "kugou": "Kugou",
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
    ABOVE this blend came back with -- BiniLyrics' TTML, amll's, Lyrics+'s own
    pick -- already fetched, because those sources are providers in their own
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
    endpoint for a base whenever nothing in hand was word-level -- ten
    seconds (see LYRICSPLUS_OWN), for a scrape of the catalogue BiniLyrics
    answers for in a tenth of one, in the round after BiniLyrics has already
    been asked and its answer handed here in `above`. Everything this blend
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
    # Which of the two times the song and which one fills its gaps is settled
    # against the base, song by song, rather than by the order they are
    # written in here. See in_order.
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
        # The donor's document, but written the way the base writes it
        # wherever the base has the line at all.
        # A blend that times less of the song than the document it borrowed
        # from is not a better document, whatever its words are. Laying one
        # source's timings under another's lines costs something every time:
        # measured against the hand-timed files in ./lyrics over sixteen
        # songs, blending NetEase under Apple's lines covers 96% of lines to
        # NetEase's own 100% and scatters 0.056s against its 0.047s. Where
        # that cost shows up as whole lines going untimed -- Chasing Clouds
        # times 29 of Apple's 40 lines where NetEase times all 31 of its own
        # -- the donor's document is simply the better one and is handed over
        # instead.
        out = dict(_reworded(donor, base))
        out["_alone"] = alone
    return out


# How much more of a song the donor must time, on its own lines, before a
# blend gives up and hands over the donor's whole document -- words and all.
#
# 0.15 was too eager. It stood the blend down on Chasing Clouds, where the
# blend times 29 of Apple's 40 lines against NetEase's 31 of 31: a 0.275 gap,
# and the price of closing it is reading NetEase's transcription of an
# English song instead of Apple's. Listened to side by side there is very
# little in it, and the words on screen are the thing the user chose a source
# for. So the bar is now high enough that Chasing Clouds keeps Apple's words,
# and a stand-down means the blend really did fail -- half the song untimed,
# not a verse of it.
# How much of the donor's lyric the blend's own words must cover before the
# blend is worth having at all. _thinner asks how much of what the base HAS
# got timed; this asks whether the base has the song. They are different
# failures: on Bad Computer's "Your Spell" the blend timed 17 of Apple's 17
# lines and looked perfect by every measure _thinner takes, while Apple's
# copy carried 359 letters against QQ Music's 589 -- the last third of the
# song simply was not in it, and no amount of word timing puts it back.
#
# Letters, not lines, because where a line ends is an editorial choice and
# sources make it differently: Apple writes as one line what QQ splits into
# two all the time, and that is not a shorter lyric.
#
# Measured as ONE stretch of the song, not as a total. Counting every letter
# the two documents disagree about made this fire on documents that are
# missing nothing at all: sources differ about whether a sung stutter is
# written out, and Musixmatch -- whose whole richsync is a stamp per sung
# token -- writes "i i see see see" and "y you" where Apple writes them once.
# On 2hollis' "jeans" that is 1071 letters against Apple's 847, a quarter
# more, none of it a part of the song Apple has not got. The largest single
# run Apple is missing there is 64 letters; the last third of "Your Spell"
# is 230. A verse that is not in a document is absent in one piece.
BLEND_SHORT = 0.85
# ...and the other direction has to hold too, or a donor padding its document
# with a title card and a credit block would look like the fuller copy. Nearly
# all of the base's own words must be inside the donor's, which is what says
# the two are the same lyric and one of them is short.
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
    # Matched here rather than through _pair, whose job is to decide whether
    # two documents are the same recording at all -- it measures the share
    # that matched against the SHORTER side and refuses below it. That is the
    # right question when a donor might be answering about a cover; it is the
    # wrong one here, where the caller has already established these are the
    # same lyric and one of them is short. Apple's 17 lines against QQ's 31
    # failed that share and left every line written QQ's way.
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


def _shorter(blend, donor) -> bool:
    """Whether the blend's words are missing a real part of the song.

    Two questions, and both have to answer yes. Is this the same lyric --
    nearly all of the blend's letters inside the donor's -- and is there one
    unbroken stretch of the donor the blend has not got, big enough to be a
    section of the song rather than a spelling difference. See BLEND_SHORT.
    """
    from difflib import SequenceMatcher

    a, b = _said(blend), _said(donor)
    if not a or not b or len(a) >= len(b):
        return False
    ops = SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    shared = sum(i2 - i1 for tag, i1, i2, _j1, _j2 in ops if tag == "equal")
    if shared < BLEND_SAME_WORDS * len(a):
        return False
    absent = max((j2 - j1 for tag, _i1, _i2, j1, j2 in ops if tag != "equal"),
                 default=0)
    return absent > (1 - BLEND_SHORT) * len(b)


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
    """Apple Music's lines with QQ Music's word timing, which is the pairing
    LyricsPlus itself makes."""
    # "qq", because that is whose document this stands down to. The name was
    # carried over as "apple" when Lyrics+ was renamed after the catalogue it
    # usually answers from, which credited QQ Music's own sync to Apple.
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


# What may be shaved off the end of the line once the tail is taken away:
# the punctuation that was joining the two, and the bracket that opened the
# one being lifted. Never a quote -- 'like, "Hey"' ends in one that belongs
# to the line.
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


# How far past a line's own end a donor's stray ad-lib may start and still
# belong to it. Wider than that and it is sitting in a gap the base does not
# describe, which is not something to guess about.
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


# How far two voices may overlap and still be called one voice written twice.
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
        # The donor's clock, against lines the blend has largely put on that
        # same clock -- whoever timed this line timed the stray beside it.
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
        # Loosely: the two sides rarely write a shout the same number of
        # times, and "Ooh, break my heart" is the line QQ Music writes as
        # "Ooooh break my heart".
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
        # Asked of the finished document rather than of the donor. _echoes
        # above asks whether the DONOR sings these words over this stretch,
        # which is what says a stray is a backing vocal at all; this asks
        # whether WE are already singing them, which is what says it has
        # nowhere left to go. The two come apart in a three-way, where the
        # filler's whole document is read for strays and the first donor has
        # already spoken for most of it: on "Never Too Late" the last "It's
        # never too late" is QQ's line 58, our line 37, and was drawn as both.
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
        # Whoever wrote it most nearly the way we did. The pool holds both
        # donors and a song repeats its shouts, so first past the post is not
        # good enough: Apple's "(Woo, woo)" should take QQ's "Woo, woo" over
        # its "Woo" when the song has both.
        best = None
        cry = _a_cry(inner)
        for item, s, e, k, syls in pool:
            if id(item) in spoken:
                continue
            said = SL.line_text({"Lead": item}) or ""
            # The same shout spelled differently is still the same shout, and
            # at this distance from the line there is nothing else it could
            # be: Apple writes "(Ooh)" where QQ times "Woo".
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
    if not _key(left):                 # the line was the ad-lib and nothing else
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
    # Whether these lines had word timing of their own before this. It decides
    # nothing here; it is written onto the result, because a document that was
    # line-synced until now had nowhere to mark a backing vocal and its
    # ad-libs are therefore still sitting in its lyric. See needs_adlibs.
    base_had = quality(SL.payload(base))
    qit = _items(SL.payload(qq)) if qq else []
    qorig = len(qit)          # before the re-stream and the filler append to it
    # The ad-libs the donors keep out of their own line streams. Every test
    # below that asks "can this line be relayed" reads the line through it,
    # because _peel_bracket is going to take those brackets out of the lyric
    # and hand them a donor's own timing -- so the question the tests answer
    # and the line that finally gets drawn are the same line. See _unaside.
    #
    # Both donors together, because _peel_bracket draws on both: a bracket
    # comes out of the lyric if EITHER of them has it filed as a group. The
    # re-stream reads a narrower set of its own -- only what the donor whose
    # stream it is keeps apart -- since that is a fact about that one stream.
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
            _relay(_unaside(SL.line_text(bit[i]), apart), syls))

    qpairs = (_pair(bit, qit) or {}) if qit else {}
    qmap = _timely(dict(qpairs), bit, qit) if qit else None
    # What the pairing found and the timing check then rejected. See `loose`
    # below: the two disagree about WHERE the line is, and about nothing else.
    astray_q = {i: j for i, j in qpairs.items() if i not in (qmap or {})}
    if qit and len(qmap or ()) < len(bit):
        # Whatever the line-by-line pairing could not place, taken from the
        # donor read as what it is -- one stream of timed syllables, cut where
        # we cut ours. It used to be all or nothing, and only when the pairing
        # had failed outright (under three lines in five), which left the
        # middle case unserved: femtanyl's P3T paired 36 of 55 lines, cleared
        # that bar, and the other 19 stayed untimed while the words for them
        # sat in the donor.
        #
        # The holes are filled and the pairings are kept. A line the pairing
        # placed was placed on better evidence than the stream can offer, and
        # where the pairing placed nothing at all every line is a hole, which
        # is the old behaviour arrived at from the other side.
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
    # Taken HERE: after the re-stream, before the filler. Both of those add
    # to the map and only one of them is still this donor speaking -- a
    # re-streamed line is this donor's own syllables re-cut to our line
    # breaks, where a filled one is somebody else's line entirely. See
    # _wander.
    steady = _wander(bit, qit, qmap or {})

    # A second donor, for the lines the first one could not place. Not a third
    # opinion -- nothing votes here -- just somebody else asked about the lines
    # nobody has answered for yet, and about the handful the first donor
    # answered for and got wrong. The old three-way blend put all three sources
    # against every line and was the worse for it; this one speaks where the
    # others are silent, and where what they said is not about this line.
    borrowed: set = set()
    # Lines taken from a donor for their WORDS while the base keeps the say
    # over where the line begins. See the drift test below and, for what it
    # means at the point of use, `start` in the main loop.
    rhythm: set = set()
    # Whose timing was handed over that way, so a line the first donor still
    # writes does not come back as an ad-lib beside itself. See below.
    dropped: set = set()
    # Parsed whether or not there are holes to fill: the second donor is
    # fetched either way, and even where it is needed for nothing else it can
    # still be the one holding the timing for an ad-lib (in the three-way the
    # lines and the words come from NetEase, and QQ is the one that times the
    # shouts).
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
                # The line the first donor timed is still this document's
                # line -- only its clock has been handed over -- so it stays
                # spoken for. Left unspoken it would come back through
                # _lift_strays as an ad-lib in the margin: the same words,
                # twice, once beside themselves.
                dropped.add(id(qit[qmap[i]]))
            elif abs(sdrift.get(i) or 0.0) > BLEND_STEADY:
                # A hole is not a free hit either. The line has no words yet,
                # but it does have the line sync's own opinion about where it
                # begins, and handing it to a donor that disagrees with its
                # OWN neighbours trades a start that was right for one that is
                # word-timed and wrong. On "Never Too Late" that is the last
                # "It's not too late", which the base places at 3:08.8 and QQ
                # Music six tenths of a second later.
                #
                # The same bar _steadier holds the filler to when it wants a
                # line the first donor already timed: the question is the same
                # one, and the answer should not turn on whether somebody else
                # got there first. No drift at all -- a base with no stamp on
                # the line, or none on its neighbours -- is no objection, and
                # the filler is taken as it always was.
                #
                # It used to `continue` here, and that is the trade read the
                # wrong way round. The objection is to the donor's PLACEMENT,
                # and the placement is not the only thing on offer: the words,
                # their order and the rhythm between them are all still this
                # line's, and the base -- being line-synced, which is the
                # whole reason a blend is being built -- has none of them. So
                # the line is taken for its rhythm and anchored on the base's
                # own stamp. Nothing is traded: the start stays the one that
                # was right, and the line stops being the only one on screen
                # that lights all at once. On LEDGER's "Foreigner" that is ten
                # of the twelve lines the blend left unworded, every one of
                # them a repeat of a chorus line that the donor places about a
                # second off where the line sync does.
                rhythm.add(i)
            extra.append(sit[smap[i]])
            qmap[i] = len(qit) + len(extra) - 1
            borrowed.add(i)
        if extra:
            qit = list(qit) + extra
    nmap = _timely(_pair(bit, nit), bit, nit) if nit else None
    ne_ends = bool(ne) and quality(ne) == "syllable"

    used: set[str] = set()
    # Which donor lines this document speaks for. By identity, because the
    # re-stream and the filler both append to qit and the second donor's
    # lines end up living in it too.
    spoken = {id(qit[k]) for k in (qmap or {}).values()
              if 0 <= k < len(qit)} | dropped
    slid: dict[int, float] = {}            # how far each line moved the donor
    over: dict[int, float] = {}            # ...and how far the BASE overlaps
    # Every donor line AND every ad-lib hanging off one, because a source
    # that marks its backing vocals properly -- NetEase does, on LOST -- has
    # the timing for a bracket our base only wrote into the lyric.
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
        # ...unless the donor is about to lend this line its words, in which
        # case the donor's own clock IS the line's clock.
        #
        # _agree weighs opinions about where a line begins, and on a
        # line-level base the base's opinion is not about that at all: Apple
        # stamps when a line should APPEAR, which is a beat before anybody
        # sings it, while the donor stamped when the word is sung. Believing
        # the earlier of the two and then sliding the donor's whole line back
        # onto it moved measured timings off the voice -- on Contra every one
        # of the eight worst lines was early, 0.36s median and 1.54s at worst.
        #
        # Worse, each line was pulled by a DIFFERENT amount, which is a
        # distortion and not an offset: lines that were spaced correctly in
        # the donor's clock ended up shuffled against each other until they
        # overlapped. NetEase's own document of Contra has no line running
        # into the next one anywhere; the blend built from it had four.
        #
        # So where the donor's syllables are going to be laid down, they are
        # laid down where the donor put them. The base's stamp still decides
        # a line the donor cannot time, and _agree still weighs the rest.
        lent = ((q or {}).get("Lead") or {}).get("Syllables") or []
        if i in rhythm:
            # Borrowed for its rhythm alone -- the base says where this one
            # begins. `qby` below then slides the donor's syllables onto it.
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

        # An ad-lib written inside our line that the donor times as a line of
        # its own. Apple writes 'Chillin\' in the back like, "Hey" (Oh, God)'
        # and QQ times 'Chillin\' in the back like "Hey"' then 'Oh God'
        # separately, so relaying one onto the other leaves everything after
        # the last timed word -- '"Hey" (Oh, God)' -- stuck to a single
        # syllable, filling in one lump. Peeled off, the lead takes the words
        # it has and the bracket takes the timing the donor already had for it.
        asides = _peel_bracket(new, pool, start, _line_end(it), spoken)
        if q is not None:
            got_aside = _peel_aside(new, q, qit, start, _line_end(it))
            if got_aside is not None:
                aside, lifted = got_aside
                asides.append(aside)
                spoken.add(id(qit[lifted]))
        qby = (start - q_s) if isinstance(q_s, (int, float)) else 0.0
        syls = _relay(new["Text"], ((q or {}).get("Lead") or {}).get("Syllables") or [])
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
                # A PAIRING _timely THREW OUT. It threw it out for being out of
                # step with its neighbours, which is how a repeated line gets
                # matched to the wrong repeat -- and rightly, because a chorus
                # landing a bar early is worse than a chorus landing whole.
                #
                # But the line then got nothing at all, and that is throwing
                # away the half of the answer that was never in doubt. What
                # _timely rejects is a PLACEMENT: it compares where the donor
                # puts the line against where the base puts it. The WORDS are
                # the same words in the same order with the same rhythm
                # between them, and the base has no rhythm to offer -- it is
                # line-synced, that is why a blend is being built at all.
                #
                # So the donor's syllables are relayed and then anchored on
                # the BASE's stamp rather than the donor's. The line is word
                # timed, and it begins where the source _timely believed put
                # it. LEDGER's "Foreigner" is twelve lines of one 56-line
                # document, every one of them a repeat of a chorus line.
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
        #
        # Nothing is done about the ends INSIDE a line, because there is
        # nothing to do it with. Every source tiles them: NetEase 99% of word
        # pairs across this cache, QQ 98%, and on the songs both have, QQ ends
        # LATER than NetEase four times as often as it ends earlier -- it has
        # no mid-line ends to lend, only longer ones. A hand-timed lyric is
        # 74% tiled itself, so a quarter of the pairs really do want an end
        # nobody is carrying. Capping a word's fill at a multiple of its
        # line's own pace was measured against 4005 words of hand timing here
        # and made it worse at every setting tried: |median| end error 0.091s
        # as it stands, 0.093s at four times the pace, 0.102s at one and a
        # half. The ends we have are not biased, only scattered, and a blunt
        # rule shortens the right words as often as the wrong ones.
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
        elif (own is not None and isinstance(b_e, (int, float))
              and isinstance(b_nxt, (int, float)) and b_e > b_nxt + BLEND_HOLD
              and own > end + BLEND_HOLD):
            # ...and where the base's line runs INTO the line after it,
            # believe that too. A voice still sounding under the next line is
            # a thing only the base can say: NetEase never writes two lines
            # overlapping, and QQ and Kugou tile theirs, so the end they hand
            # over is the next line's start whatever was actually sung. Nor is
            # it the padding _last_end guards against -- padding fills a gap,
            # and an end past the next line's start has no gap to fill.
            #
            # On "Never Too Late", "It's never too late" is held to 1:55.85
            # under "The world we knew", which begins at 1:55.18. Taking the
            # soonest end anybody measured cut it at NetEase's 1:55.23 and the
            # sustain stopped filling while it was still being sung.
            end = own
            if syls:
                syls = syls[:-1] + [{**syls[-1],
                                     "EndTime": max(syls[-1]["EndTime"], end)}]

        new["StartTime"], new["EndTime"] = start, end
        # How far the BASE runs into the line after it, which is how far this
        # line is allowed to. See the cap below the loop.
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

    # A line may run into the one after it only as far as the base says it
    # does. The branch above puts the base's overlap back where it had one,
    # and this is the same fact read the other way: a donor that overruns is
    # not describing a held note, it wrote several of our lines as one. On Dua
    # Lipa's "New Rules" NetEase files three repeats of "I got new rules, I
    # count 'em" as a single eighteen-second line, and relaying that span left
    # the hook lit over the top of its own next two repeats.
    for i in range(len(out) - 1):
        at, mine = SL.line_start(out[i + 1]), SL.line_start(out[i])
        done = _line_end(out[i])
        if not all(isinstance(v, (int, float)) for v in (at, mine, done)):
            continue
        room = at + over.get(i, 0.0)
        # Not where the base's own stamps run backwards -- Pixel Terror's
        # "Enigma" has lines out of order in the Apple document -- since there
        # the line after is no evidence about where this one stops.
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
        # Both donors, because either can be the one holding the ad-libs.
        # The three-way asks NetEase first and keeps QQ for the gaps, and QQ
        # is the one that files a shout as a line of its own.
        for lines in (qit[:qorig], spare_lines):
            if lines:
                _lift_strays(out, lines, spoken, slid)

    if not out:
        return None
    # By the same share quality() reads, so the document does not claim word
    # timing on the strength of the one line a donor could place.
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
    # How steadily the donor that actually timed this document tracks the
    # base's line sync. Recorded rather than acted on here -- the pick that
    # reads it is fallback()'s, which is the only place that can see the
    # other blends this one is being weighed against. See BLEND_PICK.
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
# How far a lyric candidate's duration may sit from the recording it is
# offered for. Much tighter than NEAR, which is there to let two CATALOGUES
# disagree about one track's length; these two numbers come from Kugou, about
# a recording Kugou has already identified by hash, and they agree to within
# about 40ms when the candidate really is filed against it. NEAR's six
# seconds are wide enough to accept the remix's lyric for the instrumental --
# 240.0 offered against 245.0 -- which is what it did.
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


# Kugou writes a credit list with an ideographic comma, everyone else with a
# slash or an ampersand. NAMES_APART already knows all of them; it is defined
# further down for _no_credit_head, and the pattern is the same question.
def _who(text: str) -> list[str]:
    """A credit line as the names in it, lead first."""
    return [n for n in (_norm(x) for x in NAMES_APART.split(text or "")) if n]


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


# Words in a title that name a DIFFERENT RECORDING rather than describing this
# one at more length.
#
# _same_song is generous about a longer title on purpose -- "Stronger (Radio
# Edit)" is the recording we asked for, written out -- and these are the
# words that make the extra text mean the opposite. A remix is a different
# performance with different words, and frequently with words where the song
# it was made from has none: Protostar's "Galaxies" is an instrumental, Rogue
# remixed it with a vocal, and QQ Music, Kugou, NetEase and Genius all file
# that vocal under a title the instrumental's title is a prefix of. Every one
# of them handed it over for the instrumental.
#
# A VETO rather than a demotion, and this is the part that was missing. Each
# of those sources already ranked its hits, and each already preferred the
# exact title -- and each then walked PAST it to the next candidate, because
# the exact title had no lyrics filed against it. Which is the correct answer
# for an instrumental and was being read as "nothing here, try the next one".
#
# One-directional, so asking for the remix still finds it: a marker is only
# held against a hit when WE did not ask for it. The direction is load-
# bearing elsewhere too -- _qq_head reads _same_song this way round, matching
# a lyric's own title card, which carries the plain name, against the longer
# name the catalogue files the track under.
#
# The vocabulary is local_align.ALT_VERSION's, which asks the same question
# about an AUDIO search hit, plus the four this library's corner of dance
# music actually uses. Kept as two lists rather than one import because they
# are two different decisions: there a marker ranks a hit last, since the
# right recording may not be on SoundCloud at all and a live take of the same
# length is better than silence, and here it drops the hit outright, since
# the wrong words on the screen are worse than no words.
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
    # No duration in the question, and no album either. Unison matches both
    # exactly rather than nearly, and its records often carry neither at all,
    # so sending one 404s a song it has: "uncomfy" answers on song and artist
    # and does not answer for the same pair with its own length attached, and
    # JMSN's "Love Me" -- filed with no album whatsoever -- stops answering
    # the moment any album is sent. The album is the worse of the two,
    # because ours is nearly never theirs: a submitter types the single a
    # song was released as ("La même") where the player is playing the record
    # it ended up on ("Ceinture noire"), and both are correct. Asking on song
    # and artist is what the endpoint is actually for; the checks below, on
    # whatever comes back, are what keep the answer honest.
    q = _qs(song=title, artist=artist)
    got = _json(f"{UNISON_BASE}/lyrics?{q}")
    rec = (got or {}).get("data") if isinstance(got, dict) else None
    if isinstance(rec, list):
        rec = rec[0] if rec else None
    if (isinstance(rec, dict) and rec.get("lyrics")
            and _near(rec.get("duration"), want)
            and _same_artist(str(rec.get("artist") or ""), artist)[1]):
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
        # The credit, as well as the name. Unison's records often carry no
        # duration at all, and _near passes anything when one side is
        # missing, so on a title as ordinary as "My Mind" the duration check
        # was doing nothing and the name check was matching everybody's song
        # of that name. Somebody else's careful sync is still somebody
        # else's song.
        lead, any_of = _same_artist(str(row.get("artist") or ""), artist)
        if not (_same_song(row.get("song") or "", title)
                and _near(row.get("duration"), want) and any_of):
            continue
        score = (1 if lead else 0,
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
# APPLE MUSIC'S OWN SEARCH, for the one field BiniLyrics is filed by.
#
# BiniLyrics indexes by ISRC -- its documents literally live at
# <ISRC>.ttml -- and from_bini has always known how to ask that way. Nothing
# ever had an ISRC to give it. The player's metadata comes off MPRIS or out
# of the Spotify page, and neither carries one, so every ask fell through to
# the name query: title, artist, album, duration, matched by string.
#
# A name query answers for a recording that shares a name. An ISRC names the
# recording. Between "Clocks" and "Clocks (Live)", between the 2002 master
# and the 2016 remaster, between a single edit and the album cut, the words
# are usually the same and the timings are not -- and a lyric on the wrong
# master is a lyric that drifts.
#
# Apple's catalogue is where the ISRC comes from, which is fitting: it is the
# same catalogue BiniLyrics holds the lyrics for, so an ISRC Apple gives for
# a recording is the key BiniLyrics filed that recording's TTML under. Asked
# with `extend=isrc`, which is not returned by default and is the whole
# reason the iTunes Search API cannot be used for this -- it has no ISRC in
# it at all.
APPLE_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
APPLE_AMP = "https://amp-api.music.apple.com/v1/catalog/us"
# Beside the caches rather than inside the sources cache, because it is not
# a source's answer and because the editor asks Apple for its songwriter
# credits through this same door: one token, one file, one lock, whichever
# of them warms it. See editor/sources.py.
APPLE_TOKEN_FILE = _cache_root() / "apple-token.json"
_APPLE_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
_apple_lock = threading.Lock()


def _apple_page(url: str) -> str:
    """A plain fetch of music.apple.com, gzip and all.

    Not _get: that one is the chain's funnel, with the chain's timeouts and
    its per-host gate, and this is a three-megabyte JavaScript bundle read
    once a day. It also has to say it is a browser to be given the bundle at
    all.
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
            html = _apple_page("https://music.apple.com/us/browse")
        except Exception as exc:                         # noqa: BLE001
            _blamed(_why(exc))
            return ""
        for js in re.findall(r'/assets/index[^"\']*?\.js', html)[:3]:
            try:
                src = _apple_page("https://music.apple.com" + js)
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


def _amp(token: str, path: str):
    """One catalogue request, or None."""
    if not token:
        return None
    req = urllib.request.Request(
        f"{APPLE_AMP}/{path}",
        headers={"Authorization": "Bearer " + token,
                 "Origin": "https://music.apple.com",
                 "Referer": "https://music.apple.com/",
                 "User-Agent": APPLE_UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # 401 and 403 are the token having turned over, which the caller
        # answers by fetching a new one -- not something to report as Apple
        # Music being unreachable.
        if e.code not in (401, 403) and e.code not in MISSED:
            _blamed(_why(e))
        return None
    except Exception as e:                               # noqa: BLE001
        _blamed(_why(e))
        return None


# Apple writes a credit as one string -- "Chris Martin, Guy Berryman, Jonny
# Buckland & Will Champion" -- and TTML wants one <songwriter> each, so it is
# cut back apart here. The same three separators the editor has always used;
# it reads them from this so the two cannot come to disagree about a name.
APPLE_NAMES = re.compile(r"\s*(?:,|&| and )\s*")


def apple_names(who: str) -> list[str]:
    """One credit line as the people in it."""
    return [n.strip() for n in APPLE_NAMES.split(str(who or "")) if n.strip()]


def apple_song(meta: dict) -> dict:
    """What Apple Music's catalogue has for this track, asked once.

    Two things come back and one request brings both: the ISRCs, which name
    the recording BiniLyrics files its TTML under, and the songwriters, which
    Apple gives as the publishing credit -- legal names, every co-writer,
    on very nearly everything it has.

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
        return {"isrcs": [], "writers": []}
    return _once(("apple", _norm(title), _norm(artist),
                  round(float(meta.get("length") or 0))),
                 lambda: _apple_song(meta, title, artist))


def _apple_song(meta: dict, title: str, artist: str) -> dict:
    token = _apple_token()
    q = _qs(term=f"{artist} {title}".strip(), types="songs", limit=10,
            extend="isrc")
    got = _amp(token, f"search?{q}")
    if got is None:
        got = _amp(_apple_token(force=True), f"search?{q}")
    rows = (((got or {}).get("results") or {}).get("songs") or {}).get("data") or []
    want = float(meta.get("length") or 0)
    hits = []
    for row in rows if isinstance(rows, list) else []:
        at = (row or {}).get("attributes") or {}
        if not _same_song(at.get("name") or "", title):
            continue
        lead, anyone = _same_artist(at.get("artistName") or "", artist)
        if not anyone:
            continue
        secs = float(at.get("durationInMillis") or 0) / 1000.0
        if not _near(secs, want):
            continue
        gap = abs(secs - want) if want > 0 and secs > 0 else NEAR
        hits.append(((0 if lead else 1, gap), at))
    hits.sort(key=lambda h: h[0])
    isrcs, writers = [], []
    for _score, at in hits:
        code = str(at.get("isrc") or "").strip().upper()
        if code and code not in isrcs:
            isrcs.append(code)
        if not writers:
            writers = apple_names(at.get("composerName") or "")
    return {"isrcs": isrcs, "writers": writers}


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
    catalogue; it is a door on that one, and the only one left (see
    LYRICSPLUS_OWN). What makes it the good door is what it is indexed by:
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
    if not isrc and not (title and artist):
        return None
    want = float(meta.get("length") or 0)

    def by_name():
        if isrc or not (title and artist):
            return []
        return _bini_rows(_qs(track=title, artist=artist, album=meta.get("album"),
                              duration=int(round(want)) if want > 0 else None))

    def by_isrc():
        codes = [isrc] if isrc else apple_isrcs(meta)
        for code in codes[:3]:
            rows = _bini_rows(_qs(isrc=code))
            if rows:
                return rows
        return []

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


# 请欣赏 -- "please enjoy" -- is the tail of the whole family of Kugou's
# placeholder cards, and it is the part worth matching. Listing the fronts one
# at a time got 纯音乐 ("pure music, please enjoy") and missed DJ音乐, which is
# the same card for a DJ edit and went on screen as the lyric. Safe to match
# on its own: _instrumental only ever looks at a document of three lines or
# fewer, and a song whose entire lyric is "please enjoy" has no words either.
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
            # The recording is already settled -- it is `hashed` -- and this
            # endpoint is only being asked which lyric documents are filed
            # against it. It does not answer that question. `keyword` is in
            # the query and it weighs, so the candidates come back sorted by
            # a title match rather than by what the hash is: asked for
            # Protostar's "Galaxies" at 245s, the one candidate offered is
            # Tchaikovsky's "The Seasons Op. 37b: June - Barcarole" at 320s,
            # and asked for the hash next to it, the second candidate is
            # "Galaxies (RogueRemix)".
            #
            # So each is checked against the recording it claims to be for.
            # Its own DURATION does that and does it whatever script the two
            # catalogues write in -- a lyric filed against this hash carries
            # this hash's length, to the millisecond -- where a title test
            # would be asking Kugou's spelling to agree with Spotify's. The
            # title is read for one thing only: whether it names a different
            # cut. See ALT_CUT.
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
# QRC is QQ Music's word-timed format, and unlike Kugou's KRC it is properly
# encrypted rather than merely obfuscated: triple DES over a fixed key, then
# a deflate. The catch is that the DES is a BROKEN one. QQ's build reads and
# writes each four-byte half back to front, carries two typos in its S-boxes
# (sbox2[23] and sbox4[53]), and takes the second half of every subkey off by
# one -- so a stock 3DES answers noise whichever way the three keys are
# ordered, which is the first thing anyone tries. It has to be reproduced bug
# for bug. What follows is a port of wangqr/QQMusicDES, itself B-Con's
# textbook implementation bent back into the shape QQ's client expects.
#
# Worth the code rather than leaving QQ to Lyrics+, which is the door this
# source used to go through. Over the 26 songs in this library the Lyrics+
# door answered word-level 17 times and QQ's own answered 24, and where both
# answered the timings were identical to the millisecond -- Lyrics+ is
# relaying this very document. The six it adds are songs it had all along and
# could not be asked for.
QQ_SEARCH = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
QQ_DOWN = "https://c.y.qq.com/qqmusic/fcgi-bin/lyric_download.fcg"
QQ_TRIES = 3
# Decrypt, encrypt, decrypt, in that order. Published in every client that
# reads a QRC; the same three keys appear in Lyricify's decrypter spelled as
# one 24-byte string, which is the same thing said differently.
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
# The three permutations DES is built out of, written as tables rather than as
# the unrolled bit expressions the C uses. QRC_IP is the initial permutation's
# left half; the right half is every one of those bits less one.
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
# Byte i of a block, as QQ's build addresses it: the two four-byte halves are
# each read back to front. This one macro is most of what makes the cipher
# incompatible with everybody else's DES.
QRC_ORDER = (3, 2, 1, 0, 7, 6, 5, 4)
QRC_UNORDER = (4, 5, 6, 7, 0, 1, 2, 3)
QRC_M32 = 0xFFFFFFFF


def _qrc_bit(src, b: int, to: int) -> int:
    """Bit b of a byte string, counted from the left, moved to position `to`."""
    return ((src[QRC_ORDER[b // 8]] >> (7 - b % 8)) & 1) << to


def _qrc_split(block) -> tuple:
    """One eight-byte block as the two 32-bit halves DES works on."""
    left = right = 0
    for i, b in enumerate(QRC_IP):
        left |= _qrc_bit(block, b, 31 - i)
        right |= _qrc_bit(block, b - 1, 31 - i)
    return left, right


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


def _qrc_f(state: int, key: bytes) -> int:
    """DES's round function: expand to 48 bits, key it, S-box it, permute it.

    Textbook from here down -- the expansion, the boxes and the P-box are the
    real DES's, and only the two typo'd entries in QRC_SBOX are QQ's.
    """
    bits = 0
    for b in QRC_EXPAND:
        bits = (bits << 1) | ((state >> (31 - b)) & 1)
    bits ^= int.from_bytes(key, "big")
    state = 0
    for i in range(8):
        six = (bits >> (42 - 6 * i)) & 0x3F
        # The row is spelled by the outer two bits of the six and the column by
        # the inner four; the tables are written the other way round.
        row = (six & 0x20) | ((six & 0x1F) >> 1) | ((six & 1) << 4)
        state |= QRC_SBOX[i][row] << (28 - 4 * i)
    out = 0
    for i, b in enumerate(QRC_PBOX):
        out |= ((state >> (31 - b)) & 1) << (31 - i)
    return out


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
    """DES-ECB over whole blocks, QQ's way. A trailing part-block is dropped."""
    rounds = _qrc_schedule(key, decrypt)
    out = bytearray()
    for at in range(0, len(data) - len(data) % 8, 8):
        left, right = _qrc_split(data[at:at + 8])
        for r in rounds[:15]:
            left, right = right, _qrc_f(right, r) ^ left
        out += _qrc_join(_qrc_f(right, rounds[15]) ^ left, right)
    return bytes(out)


def _qrc(blob: str) -> str | None:
    """One hex QRC payload as its plain text, or None if it will not decrypt.

    QQ files the translation in the same envelope as the lyric but leaves it
    in the clear, so a payload that is not hex at all is handed back as it
    stands rather than treated as a failure.
    """
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


# The download hands back an XML document inside an HTML comment, with each
# payload in a CDATA block: `content` is the lyric, `contentroma` the
# romanisation, and `contentts` a translation this module has no use for. The
# word boundary matters -- without it `content` swallows `contentts` too.
QRC_CDATA = re.compile(r"<(contentroma|content)\b[^>]*>\s*<!\[CDATA\[(.*?)\]\]>", re.S)
# Greedy, and deliberately so: QQ does not escape the quotes inside this
# attribute, so The Weeknd's "After Hours" carries a dozen raw ones and a
# lazy match stops at the first. Nothing is unescaped on the way out either,
# because nothing is escaped on the way in -- not even an apostrophe.
QRC_BODY = re.compile(r'LyricContent="(.*)"\s*/>', re.S)
QRC_LINE = re.compile(r"^\[(\d+),(\d+)\]")
QRC_STAMP = re.compile(r"\((\d+),(\d+)\)")
# QQ closes a good many of its documents with a sentinel line, timed like a
# lyric and sung by nobody.
QRC_TAIL = re.compile(r"^~+\s*end\s*~+$", re.I)
# QQ files a fuller credit block than NetEase or Kugou do, and it qualifies
# the roles: KiiiKiii's carries "Original Lyrics by：", "Vocal Directed by：",
# "Background Vocals by：" and "Programming by：". NE_CREDIT wants its keyword
# at the START of the line and walks past every one of them. What gives them
# away is the shape instead -- a short role, and then the colon that separates
# it from the names. Two shapes, because QQ writes the block both ways: a role
# ending in "by", and a bare field name.
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
            # Dropped as a lyric, kept as what it says: QQ stamps "作词 : X"
            # over the intro the way NetEase and Kugou do, and it is the only
            # place either of them names a writer.
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


# A line that is a name and a colon and nothing else -- QQ marks who takes
# each verse of a collaboration that way, and times the mark like a lyric.
QQ_SAYS = re.compile(r"^\s*(.+?)\s*[:：]\s*$")


def _qq_head(items: list[dict], name: str, artist: str) -> list[dict]:
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
    """
    while items:
        text = (SL.line_text(items[0]) or "").strip()
        head, sep, tail = text.rpartition(" - ")
        if not (sep and _who(tail) and _same_song(head, name)
                and _same_artist(tail, artist)[1]):
            break
        items = items[1:]
    who = set(_who(artist))
    out = []
    for it in items:
        said = QQ_SAYS.match(SL.line_text(it) or "")
        if said and _norm(said.group(1)) in who:
            continue
        out.append(it)
    return out


def _qq_doc(parts: dict, name: str, artist: str) -> dict | None:
    """One download response's payloads as a lyrics document."""
    items, wrote = _qrc_items(parts.get("content") or "")
    items = _qq_head(items, name, artist)
    if not items or _instrumental(items):
        return None
    # The romanisation is word-timed QRC of its own, on the same line clock as
    # the lyric, so the lines pair up by where they start. Only its text is
    # kept: the view romanises a line, not a syllable.
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
# Musixmatch answers three ways for one song -- the plain words, a line-level
# subtitle, and `richsync`, which times every word -- and one request can ask
# for all three. What this module got instead was whatever Lyrics+ scraped,
# which is the subtitle and never anything better: asked for `musixmatch` by
# name it comes back Line-typed with not a syllable on it, on every track
# tried. So Musixmatch has been in the running order contributing nothing that
# LRCLIB could not.
#
# The shape of the request is neither documented nor guessable. It is the one
# Spicetify's lyrics-plus makes (CustomApps/lyrics-plus/ProviderMusixmatch.js),
# down to the headers, which the iOS endpoint reads.
MXM_BASE = "https://apic-appmobile.musixmatch.com/ws/1.1/"
MXM_APP = "mac-ios-v2.0"
# Not decoration. The endpoint answers the iOS app and checks that it is being
# spoken to like one; the desktop host with the desktop app_id is a different
# door with a much shorter temper.
MXM_HEAD = {
    "X-Cookie": "x-mxm-token-guid=",
    "x-mxm-app-version": "10.1.1",
    "X-User-Agent": "Musixmatch/2025120901 CFNetwork/3860.300.31 Darwin/25.2.0",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "application/json",
}
MXM_TOKEN_FILE = _cache_root() / "musixmatch-token.json"
# How long to leave token.get alone once it has refused. It answers 401 with
# `hint: captcha` after a handful of asks from one machine, and asking again
# inside the cool-off only holds it open.
MXM_COLD = 1800.0
# Musixmatch files the songwriters in the copyright line rather than in a field
# of their own: "Writer(s): Joseph Hahn, Chester Charles Bennington, ...", with
# a "Copyright:" line of publishers under it. One line, so the publishers are
# not read as five more writers.
MXM_WROTE = re.compile(r"writer\(s\)\s*:\s*(.+)", re.I)
# How close a word's measured end has to be to its own start before that end
# is read as no measurement at all; see _mxm_spans. Taken off the
# distribution rather than picked: over 2247 words from eight tracks, 27 land
# within 2ms of their own start and 8 more within 10ms, and then there is a
# trough before the real spread of word lengths begins and climbs to its peak
# around a quarter of a second. The cut sits in that trough.
MXM_STOP = 0.005
# A gap shorter than this is not a rest, it is the end of the word that has
# not been written down; see _mxm_spans. Musixmatch's own median gap is 33 to
# 71ms across the tracks measured here, so the great majority close.
#
# Measured at 0.2 first and that was too tight. NEFFEX's "Are You Ok?" is the
# track that says so: 69 gaps survived it INSIDE a line, and they run 0.200,
# 0.201, 0.202 ... 0.352 in one unbroken stretch, which is not a song pausing
# 69 times in the middle of its own phrases -- it is the same missing word end
# as the shorter ones, a little larger. Past 0.4 what is left is a rest that
# was really taken: the same song's remaining mid-line gap is 0.84s, and Creep
# and "Never Too Late" hold 1.2 and 1.49 inside a line. So the cut goes where
# the continuum ends rather than where it started.
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
        # Refused lately. A forced ask is one whose token has just been
        # retired, so there is nothing to fall back on there either.
        return "" if force else held
    msg = _mxm_get("token.get")
    tok = str(((msg or {}).get("body") or {}).get("user_token") or "")
    # A failed ask writes down only the refusal, which drops the dead token
    # with it: keeping it would spend a request per track discovering again
    # that it is dead.
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
    # Across the lines as well as inside them: "the word thereafter" is the
    # next line's first where a line has run out, and two lines a tenth of a
    # second apart are one phrase however they were cut.
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
    # ...unless it is line timing wearing a syllable's clothes. Musixmatch
    # richsync for a Japanese lyric is frequently one token per line -- on
    # Kenshi Yonezu's "Peace Sign", 43 of the 60 lines are the whole line at a
    # single stamp -- and a document like that is shaped exactly like a real
    # word sync while carrying none of the information. Left alone it beats a
    # line-synced document from a source ranked above it, and the reader gets
    # the same timing with a worse lyric. _deword is the honest reading, and
    # it is the same trade _youly already makes on a Musixmatch scrape.
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


# Whether Musixmatch called the matched track explicit, filed under the same
# key as its document. Not carried on the document itself because the document
# is often None -- an instrumental, a restricted track, a song nobody has
# synced -- and the rating is worth having in every one of those cases. Swept
# against _ONCE so it cannot outlive the answer it was read from.
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

    The LyricsPlus scrape used to stand behind this one -- it needs no token
    and it answers for tracks the macro cannot match -- and what it brought
    was line-level, from a source that sits next to last precisely because
    its line-level copy is not worth much. Ten seconds of the walk, inside
    the round the blends wait on, for a document ranked below almost
    everything that had already answered. See LYRICSPLUS_OWN.
    """
    token = _mxm_token()
    msg = _mxm_ask(tid, meta, token) if token else None
    if _mxm_code(msg) == 401:
        # The stored token has been retired. Worth exactly one more ask, and
        # not worth one at all if the cool-off says the answer will be no.
        token = _mxm_token(force=True)
        msg = _mxm_ask(tid, meta, token) if token else None
    calls = ((msg or {}).get("body") or {}).get("macro_calls") \
        if isinstance((msg or {}).get("body"), dict) else None
    if calls:
        # Kept whether or not there is a document to go with it. See
        # mxm_explicit, which is the only reader.
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
        # The subtitle is asked for as LRC so that it arrives as the thing
        # parse_lrc already reads, and the plain words behind it are what that
        # falls back on for a song nobody has synced at all. It wins a tie
        # against a richsync that had to be deworded: both are then line
        # stamps, and these are the ones Musixmatch measured for display.
        lrc = "" if sub.get("restricted") else str(sub.get("subtitle_body") or "")
        plain = "" if words.get("restricted") else str(words.get("lyrics_body") or "")
        other = parse_lrc(lrc, plain)
        rank = lambda d: RANK.get(quality(d), 0) if d else 0     # noqa: E731
        if other is not None and rank(other) >= rank(doc):
            doc = other
    if doc is None:
        return None
    # "richssync_language" is Musixmatch's own typo and is the field that
    # exists; the spelling it ought to have is read too, in case they fix it.
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
# Genius: the words themselves, and no clock at all
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


# A second-round provider, and one _gather may decide not to ask at all.
# `above` is not read here: like the blends', the decision is taken in
# _gather, where it saves the request rather than only the parsing.
from_genius.wants_above = True
from_genius.untimed = True


def _genius(token: str, meta: dict) -> dict | None:
    """One ask.

    Nothing is filed against this one when the network fails, unlike every
    other provider here: local_align.genius_doc catches its own exceptions
    and answers None, so a Genius outage and a song Genius has not got
    arrive looking exactly alike. The except below is only for the ways it
    can raise on the way out. A miss is by far the commoner of the two and
    a miss is silent anyway, so the cost of the confusion is a fault that
    goes unreported rather than a wrong one shown.

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
        return None
    # `_timing` names whose CLOCK a document runs on, and this one has no
    # clock. local_align stamps it because it is about to make one; handed
    # to the chain as it stands it would have the line under the lyrics
    # claim a timing that is not there.
    return {k: v for k, v in doc.items() if k != "_timing"}


# Which providers answer for a source. Mostly one each. Spicy Lyrics is not
# in this table because it is not fetched by the chain at all: it is read out
# of the Spotify page (see Fetcher).
#
# Apple Music used to have two, BiniLyrics and the LyricsPlus door asked for
# Apple by name, and they were two doors on one catalogue at wildly different
# prices: BiniLyrics indexes by ISRC, cannot answer for the wrong recording,
# and answers in about a tenth of a second; the other fetched from Apple and
# converted the TTML on the way and took eight to seventeen (see
# _HOST_PATIENCE). The cheap one is the only one now -- see LYRICSPLUS_OWN --
# so Apple Music is a recording matched by ISRC or it is nothing, which is
# also the stricter of the two answers.
SRC_PARTS = {"spicy": ["spicy"], "apple": ["bini"], "amll": ["amll"],
             "unison": ["unison"], "lyricsplus": ["lyricsplus"], "qq": ["qq"],
             "netease": ["netease"], "kugou": ["kugou"], "mxm": ["mxm"],
             "lrclib": ["lrclib"], "local": ["local"],
             "genius": ["genius"]}
# A blend is one source's WORDS under another's word timing, so it belongs to
# the source whose words you read -- Apple Music -- and it is only asked for
# when every source it draws on is switched on. Ranking Apple Music above QQ
# Music and leaving both on is what asks for "Apple's lines, QQ's timing";
# switching QQ off is what says you would rather not have it at all.
# The tuple is (whose words, whose clock, who fills the gaps) -- the same
# order _blended takes its arguments in, and blend_rank reads it that way.
BLENDS = {"blend": ("apple", "qq"), "kublend": ("apple", "kugou"),
          "neblend": ("apple", "netease"),
          "triblend": ("apple", "netease", "qq"),
          "kutriblend": ("apple", "netease", "kugou")}
BLEND_OF = "apple"
# The settings key, argparse dest and attribute for each blend's switch, named
# for the donors rather than for the internal name: blend_ne_qq says what it
# is, where blend_triblend says only what it is called.
BLEND_KEY = {"blend": "blend_qq", "kublend": "blend_kugou",
             "neblend": "blend_netease", "triblend": "blend_ne_qq",
             "kutriblend": "blend_ne_kugou"}
# Every provider back to the source it answers for, for the line under the
# lyrics and for anything else that holds a provider name and owes the user
# the name of a catalogue.
PROVIDER_SRC = {p: n for n, parts in SRC_PARTS.items() for p in parts}
PROVIDER_SRC.update({b: BLEND_OF for b in BLENDS})
# What the old menu called things, for reading a settings file written by it.
WAS_SRC = {"youly": "apple", "bini": "apple", "blend": "apple",
           "kublend": "apple", "neblend": "apple", "triblend": "apple"}


# The order they are consulted in unless the user says otherwise.
#
# NetEase and Kugou ahead of QQ Music, because this order decides which blend
# is asked first and fallback() keeps the first of two equally good answers --
# so whoever leads here usually wins. Measured against the hand-timed files in
# ./lyrics, Apple+QQ leaves 10.7% of a song's words more than half a second
# out of step with the rest of it, against 5.8% for Apple+NetEase+Kugou, and
# it cuts a third of its lines short where the three-way cuts a quarter.
# Shipping QQ first was handing every fresh install the worst of the five.
# LyricsPlus' submissions sit with the other databases people hand-time and
# upload, which is what they are, rather than on a measurement of the kind
# above: asked by name for 40 of the songs in ./lyrics it answered for none
# of them, so there is nothing yet to rank it by. That is a reason to place
# it by kind, not to place it last -- rank only settles ties here, the whole
# enabled chain is asked in parallel either way.
#
# LRCLIB above Musixmatch, which is the one pair here ordered against the
# better clock rather than with it. Musixmatch is word-timed where LRCLIB is
# line-timed and never anything else, and on those songs it wins anyway:
# quality outranks order in both directions, so nothing about this ranking
# can hand a line-level document a song that somebody has word-timed. What it
# decides is the songs where Musixmatch came back line-level TOO -- its
# subtitle rather than its richsync -- and there the two are answering the
# same question with the same kind of answer, and LRCLIB is the open database
# with no token, no cool-off and no rate limit behind it.
#
# Genius last, and it is the one entry here placed by what it CANNOT do.
# Its documents are untimed, so it is barred by quality from taking a song
# off anything above it however anybody ranks the list, and the only songs
# it can speak for are the ones every other source was silent on. That is
# the definition of the slot at the end -- and it is the slot carried()
# hands a source nobody has ever ranked, so the placement needs no
# migration to go on being right.
SOURCES = ["spicy", "apple", "amll", "unison", "lyricsplus", "netease",
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
    eighth arrived in front of amll, Unison and LyricsPlus, and beat all
    three on a tie -- for a clock the user had ranked below them. Where the
    blend really is the better document it still wins: quality outranks
    order in fallback(), and a blend exists precisely to be word-timed where
    its base is not.

    The move pays for itself twice over in requests. `above` -- what the
    round before found -- now reaches a blend with Apple's own document
    already in it, so _blended takes its base from there instead of going
    back to the slow Lyrics+ door for a copy of what BiniLyrics has already
    handed over.

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
        # The highest-ranked donor. Not the timing donor, which is what
        # blend_rank reads: that decides which blend is asked first, a
        # question between blends, where this one is about the sources
        # around them. A three-way whose filler the user put above its
        # clock still borrows from both, and sits above both.
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
# WHO TIMED IT, rather than which database it is sitting in.
#
# Four of these sources are people: Spicy Lyrics' community entries, amll,
# LyricsPlus' curators and Unison are all somebody sitting down with a song
# and timing it by hand. The running order cannot say anything about that --
# it ranks the databases, and a database is not a person. So a user who
# knows one contributor's syncs drift and another's are better than the
# licensed copy has no way to say either, short of switching a whole source
# off and losing everybody else on it with them.
#
# That is what the two lists here are for, and they are deliberately the
# smallest thing that answers it: names to refuse, and names to take. See
# Roster.
def people(v) -> list[str]:
    """Usernames out of a credit slot, however many it turns out to hold.

    Spicy Lyrics writes Maker and Uploader as one {id, username, avatar}
    object each, and its own UI reads them that way. But a sync can have more
    than one author, and the day the field grows into a list is not a day this
    should quietly show nothing -- so an object, a list of them, and a bare
    name are all read the same. An empty {} is how "nobody is credited here"
    is spelled, and comes back as no names rather than as a blank one.
    """
    if isinstance(v, (dict, str)):
        v = [v]
    out = []
    for one in v if isinstance(v, list) else []:
        name = (str(one.get("username") or one.get("name") or "").strip()
                if isinstance(one, dict) else str(one or "").strip())
        if name and name not in out:
            out.append(name)
    return out


def credited(body) -> list[str]:
    """Everybody a document credits with its TIMING, best claim first.

    Four conventions, because four sources carry the fact at all and none of
    them agreed on where to put it: Spicy Lyrics files Maker and Uploader in
    TTMLUploadMetadata, amll and LyricsPlus arrive through _credits as
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
    out: list[str] = []
    for slot in (meta.get("Maker"), meta.get("Uploader"),
                 doc.get("_maker"), doc.get("SyncedBy")):
        for name in people(slot):
            if name not in out:
                out.append(name)
    return out


def whose(name: str) -> str:
    """One credited name, as it is compared.

    Case and spacing are noise -- the same person is "Kiri", "kiri" and
    " Kiri " depending on which of the four conventions above carried them --
    and a GitHub login typed the way it is written everywhere else, with an @
    on the front, is the same login without it.
    """
    return re.sub(r"\s+", " ", str(name or "").strip().lstrip("@")).casefold()


def name_list(raw) -> list[str]:
    """A comma-separated list of names, as typed, with the empties dropped.

    Commas, because these are usernames and a username can contain a space:
    splitting on whitespace would make two people out of "Jane Remover".
    """
    if isinstance(raw, (list, tuple)):
        bits = [str(n) for n in raw]
    else:
        bits = str(raw or "").split(",")
    out = []
    for one in bits:
        one = re.sub(r"\s+", " ", one.strip())
        if one and not any(whose(one) == whose(o) for o in out):
            out.append(one)
    return out


class Roster:
    """Whose syncs to refuse, and whose to take whatever the order says.

    Two lists of names, both usually empty, applied to documents rather than
    to sources -- so they go on meaning what they said when the person posts
    their next sync to a different database.

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

    __slots__ = ("skip", "pick")

    def __init__(self, skip=(), pick=()) -> None:
        self.skip = frozenset(k for k in map(whose, name_list(skip)) if k)
        self.pick = frozenset(k for k in map(whose, name_list(pick))
                              if k and k not in self.skip)

    def __bool__(self) -> bool:
        return bool(self.skip or self.pick)

    def blocks(self, body) -> bool:
        """Whether this document is somebody's the user has refused."""
        return bool(self.skip) and any(whose(n) in self.skip
                                       for n in credited(body))

    def likes(self, body) -> bool:
        """Whether this document is somebody's the user asked for by name."""
        if not self.pick or self.blocks(body):
            return False
        return any(whose(n) in self.pick for n in credited(body))

    def key(self) -> str:
        """The lists as one string, to store beside an answer they shaped.

        A cached answer was picked under whichever roster was in force when
        the walk ran, so the roster is part of the question the cache is
        keyed by -- exactly as `names` and `bar` are (see _store). Without
        this, refusing somebody would go on showing their document for the
        month the old answer lives, and taking them off the list again would
        not bring it back.

        Empty on an empty roster, which is what every record written before
        this existed carries -- so nobody's cache is thrown away by adding a
        feature they are not using.
        """
        if not self:
            return ""
        return ("-" + ",".join(sorted(self.skip))
                + "+" + ",".join(sorted(self.pick)))


# Named for the source each one answers from, not for the door it knocks on:
# Apple Music and Musixmatch and QQ Music all come through Lyrics+, and the
# running order the user writes is a list of sources, so the chain has to be
# able to ask for one of them without the other two.
PROVIDERS = [("amll", from_amll), ("blend", from_blend),
             ("kublend", from_kublend), ("neblend", from_neblend),
             ("triblend", from_triblend), ("kutriblend", from_kutriblend),
             ("bini", from_bini), ("unison", from_unison),
             ("lyricsplus", from_lyricsplus),
             ("qq", from_qq), ("kugou", from_kugou), ("netease", from_netease),
             ("mxm", from_musixmatch),
             ("lrclib", from_lrclib), ("local", from_local),
             ("genius", from_genius)]
# The providers worth ASKING to find out whether somebody named on the prefer
# list has this song. A name can only be found by fetching the document that
# carries it, so a walk that already holds word timing has to go and look --
# and this is what keeps going and looking from meaning all ten doors on
# every song. See _walk.
#
# Which is not quite the same list as "can say who timed it". Apple,
# Musixmatch, LRCLIB and the three Chinese catalogues have nowhere to put the
# fact and never carry it, so they are out for the obvious reason. Two are
# out for reasons of their own:
#
#   * SPICY LYRICS carries it and is the biggest source of it here -- but it
#     is not in this table because it is not in PROVIDERS at all. It is read
#     out of the Spotify page rather than fetched by the chain, so there is
#     nothing to ask: the player already has its document in hand and asks
#     the roster about it directly. See Fetcher._load.
#   * LYRICSPLUS carries a curator and is deliberately left out. Its door is
#     given twenty seconds (see _HOST_PATIENCE) and times out on nearly every
#     song, and a timeout is reported where a miss is passed over in silence
#     -- so hunting it would put a wait and a "could not reach LyricsPlus" on
#     every word-timed track, for a credit that is a submitter's name on a
#     handful of songs. It is still honoured wherever the chain is walking
#     anyway: what this list decides is only whether a door is worth opening
#     on a song that was otherwise settled.
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
    same way, three times over between Lyrics+, Apple+QQ and the three-way's
    filler.

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
            # A walk that was given up on answers None for a reason that has
            # nothing to do with the upstream. Left in the memo that reads as
            # "this track has nothing", for ONCE_TTL, to every walk that comes
            # after it -- including the one the user is actually waiting on,
            # which is usually the very next thing to ask.
            if rec["value"] is None and not _walking():
                with _ONCE_LOCK:
                    if _ONCE.get(key) is rec:
                        _ONCE.pop(key, None)
    elif not _waited(rec["done"], TIMEOUT * 3):
        # Either the first caller is taking longer than any honest ask can, or
        # this walk has been dropped. Only the first is worth asking again for:
        # the wait itself was the thing worth having.
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

    # The one place the walk fans out, and so the one place its cancel token
    # has to be handed on: a thread starts with a bare threading.local and
    # would otherwise ask nobody's permission for anything. The same goes for
    # where a failure is written down, and for whose failure it is -- inherited
    # rather than set from the job's key, because a provider fans out again
    # inside itself (NetEase asks about several song ids at once) and those
    # requests are still that provider's.
    alive = getattr(_WALK, "alive", None)
    faults = getattr(_WALK, "faults", None)
    who = getattr(_WALK, "who", "")

    def guard(k, fn):
        try:
            return tell(k, _under(alive, fn, faults, who))
        except Exception as e:                           # noqa: BLE001
            _under(alive, lambda: _blamed(_why(e), k), faults, who)
            return tell(k, None)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(guard, k, fn): k for k, fn in jobs.items()}
        out = {}
        for f in as_completed(futures):
            out[futures[f]] = f.result()
    return {k: out.get(k) for k in jobs}


# How long the round after the first will wait for it before getting on with
# what it can already answer. See _Fan and _gather.
#
# Two seconds, because that is where the chain divides. Measured over this
# library, every door but one answers inside it -- BiniLyrics and LRCLIB in a
# tenth of a second, NetEase and Kugou in about two, QQ in three or four --
# and the LyricsPlus door takes eight to thirteen whatever it is asked (see
# _HOST_PATIENCE). Waiting for the slowest of them to decide when the rest of
# the chain may start is the whole of what this is for.
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

    def guard(k, fn):
        try:
            return tell(k, _under(alive, fn, faults, who))
        except Exception as e:                           # noqa: BLE001
            _under(alive, lambda: _blamed(_why(e), k), faults, who)
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
    # The other blends are in this stretch too and are not in `got` -- they
    # are being decided in this same round -- so they answer None and abstain,
    # which is right: no blend stands another one down.
    front = [got.get(n) for n in names[:at]]
    if not any(u in (ahead or ()) for u in uses) and name not in (ahead or ()):
        front.append(local)
    return any(RANK.get(quality(d), 0) >= RANK["syllable"] for d in front if d)


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
            out[n] = (lambda fn=known[n], above=above, n=n:
                      _asks(n, lambda: fn(tid, meta, local=local, above=above)))
        return out

    timed = [n for n in later if not getattr(known[n], "untimed", False)]
    untimed = [n for n in later if n not in timed]
    # Opened only once the first round has said something, so this is the one
    # point in a walk where giving up saves the whole rest of it rather than
    # only what has not gone out yet.
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
        return _under(alive if alive is not None else getattr(_WALK, "alive", None),
                      lambda: _walk(tid, meta, have, enabled, force, order,
                                    ahead, local, report, people),
                      faults, "")
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
        # What the caller already holds is a document like any other, and a
        # refused one is no more usable as a blend's base here than it was on
        # screen. `have` is the caller's to put right -- it is a quality, not
        # a document, and a walk cannot tell "line-timed" refused from
        # line-timed -- which is why the player drops the body itself.
        local = None
    bar = RANK.get(have, 0)
    known = {n: fn for n, fn in PROVIDERS}
    # WHO ELSE IS WORTH ASKING with word timing already in hand. `ahead` is
    # the standing answer -- a source ranked above whatever the caller holds
    # wins a tie -- and a name on the prefer list is the other one: their
    # sync wins that tie from wherever it is sitting, which is the whole
    # point of naming them, and the only way to find out whether they have
    # this song is to ask. Narrowed to the sources where a name can be found
    # for what asking them costs, so preferring somebody does not turn every
    # song with word timing into a ten-door walk. See credits_people.
    hunt = (bool(rule.pick) and not rule.likes(local)
            and [n for n, fn in PROVIDERS
                 if getattr(fn, "credits_people", False)])
    if bar >= RANK["syllable"] and not ahead and not hunt:
        return None
    walk = [n for n in (order or [n for n, _ in PROVIDERS]) if n in known]
    walk += [n for n, _ in PROVIDERS if n not in walk]
    names = [n for n in walk if enabled is None or n in enabled]
    if bar >= RANK["syllable"]:
        names = [n for n in names if n in ahead or n in (hunt or ())]
    if not names:
        return None

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

    if not force:
        rec = _cached(tid)
        if rec is not None and str(rec.get("people") or "") != rule.key():
            # Not this question. The record holds the answer a walk arrived at
            # under whichever roster was in force when it ran -- both what it
            # settled on and, for a stored miss, what it found nobody worth
            # having. Refusing somebody would otherwise leave their document
            # on screen until the entry aged out, and taking them off the list
            # again would not bring it back. See Roster.key.
            rec = None
        if rec is not None:
            doc, was = rec.get("doc"), rec.get("source") or ""
            asked = list(rec.get("names") or [])
            fits = bar >= int(rec.get("bar") or 0)
            if doc and asked == names:
                if beats(RANK.get(quality(doc), 0), was, doc):
                    # Handed over the same way a fresh answer is. This is the
                    # look-ahead's whole payoff -- the track was warmed, the
                    # answer is on the disk, and the caller can draw it now --
                    # and it used to be the one path that did not report: the
                    # walk returned before _gather, so nothing landed, and a
                    # warmed song reached the screen no sooner than a cold one.
                    _told(report, doc, was)
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
            # The same three rules the final pick below uses, in the same
            # priority -- better timing, then somebody asked for by name,
            # then the running order -- so what goes up early is never
            # something the final answer would then have to take back.
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
    # Somebody asked for by name takes the tie off everybody else in it,
    # whatever source they are sitting on -- which is the whole of what
    # naming them does. The tie is what the running order would have settled
    # and the only place an order can still be overruled without overruling
    # the timing: `tied` is already down to the documents of equal quality,
    # so nothing here can put a worse-timed one on screen.
    liked = [row for row in tied if rule.likes(row[0])]
    best = _fullest(_steadiest(liked or tied))
    if not _walking():
        # Dropped part way. Nothing is stored: a walk that stopped asking did
        # not find out that nobody has the song, and _store would file that
        # silence under the whole provider list -- which _cached reads back as
        # a settled "no" for the next six hours, on a track that was only ever
        # skipped past.
        return None
    if best:
        best = (_credited(best[0], docs, names, ahead, local, meta),
                best[1], best[2])
    _store(tid, best[0] if best else None, best[1] if best else "", names, bar,
           rule.key())
    return (best[0], best[1]) if best else None


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


# How much shorter one line may be than the other and still be it. Loose,
# because length is a bad test for the thing it was standing in for: see
# _fragment, which asks the question length was being asked to answer.
LIKE_LEN = 0.65
# A line is a FRAGMENT of another when nearly all of it appears inside the
# other in one piece. That is the chorus case the length guard was really
# aimed at, and it is what makes "Caught in the middle" different from "Two
# faced, caught in the middle" -- every letter of the shorter is in the
# longer, in order, unbroken.
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
            # ...and not a piece cut out of a longer line, which is the case
            # the length guard above used to be doing on its own, badly.
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


# The marks a word can be cut at without the cut being a syllable.
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

    Matching WORDS to words instead was tried and measured, on the theory that
    a letter alignment cannot know what a word is. It is worse, and for the
    reason this docstring already gives: exact word matching drops every word
    the two sources spell differently, and near-matching words inside a window
    recovers only some of them. Against this, over Stronger, MOTTO and If You
    Want Love -- 91/91 lines timed with nothing invented, against 90/91 with
    twenty-five onsets invented; 77/79 and four, against 75/79. The letters
    already carry the words with them. See eval_sources.py for the instrument.
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
    return _unlump(_unsplit(out))


# A word the source will not print. "f***" still has letters in it and was
# never in question; "****" has none, so it reached _key as empty and went
# through the door marked punctuation -- which glued it to its neighbour and
# ate the space between them: "Damn,****, every time", "You got that**** long
# arms". It is a word. Somebody sings it, it takes a turn on screen, and the
# spaces on either side of it are its own.
#
# Two asterisks or more, because one is an ellipsis' cousin -- a footnote
# mark, a lone star between verses -- and those really are marks. Nothing
# else is read as a mask: a run of dashes or hashes is as likely to be the
# punctuation this function exists for.
MASKED = re.compile(r"\*\*+")


def _mark_only(text) -> bool:
    """Whether a syllable is nothing but punctuation. A mask is not."""
    text = str(text or "")
    return not _key(text) and not MASKED.search(text)


# A hole between two syllables of one line shorter than this is not a rest
# somebody took, it is the end of a word that was not written down; see
# close_holes.
#
# The number is the one the editor already uses for the same judgement
# (ops.MAX_GAP), and QQ Music's own documents are what say it is right here.
# Over 19 songs, 6,882 syllable-to-syllable pairs inside a line: every
# document meets end to end between 73% and 100% of the time, and 13 of the
# 19 are above 90%. Contiguous is the house style, so a document that is not
# contiguous is not phrasing differently -- it is one whose ends were left
# out. Koven's "Light Up" meets end to end 35% of the time and its holes run
# 0.15s to 0.25s in the middle of phrases: "How do you switch up your
# mindset" is written with a fifth of a second of silence after "How".
#
# What is left standing above the cut really is a rest: across the same 19
# songs only 9% of the non-zero gaps are longer than 0.7s, and those are bars
# nobody sings in.
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
            # Onto the word before: its text, and its spacing, since the mark
            # is now what ends the word.
            out[-1]["Text"] = str(out[-1].get("Text") or "") + str(y.get("Text") or "")
            out[-1]["IsPartOfWord"] = bool(y.get("IsPartOfWord"))
        # A mark that opened the line has nothing before it and was kept; give
        # it to the word after instead.
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
        # The document back as it came, not a copy of it that says the same
        # thing. Almost nothing has a stray mark in it -- 60 of 60 Spicy
        # Lyrics documents sampled here needed no repair at all -- and the
        # copy was not free: the window decides whether an answer is NEW by
        # asking whether it is the same document it already has, so rebuilding
        # one that nothing was wrong with made every redraw look like a fresh
        # lyric. See LyricsView.on_lyrics, and unlump above, which has always
        # worked this way.
        return doc
    return {**doc, key: out}


def unlump(doc):
    """Every group in a document, with no syllable holding two words.

    _relay does this to what it lays down, but a document has words in it
    that the relay never touched: the base's own syllables where the donor
    had nothing to say about that line, its backing vocals, and every line
    of a document that won outright and was never blended at all. Spicy
    Lyrics' own files carry them -- "or ​am", "I ​am ​a", two words joined
    with a zero-width space and given one timing between them -- and they
    read exactly like the ones the relay used to make.
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
        # A piece with no letters in it is not a word -- QQ's token for
        # 'like, "' leaves a lone quote mark behind -- so it rides along with
        # the one before it rather than being timed on its own.
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
            # Only the first of these starts where the source said anything.
            # The rest are shared out, and say so: eval_sources.py counts them,
            # and a measurement that cannot tell a stamp from a guess is not
            # measuring the thing that matters.
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
# How long a LONE bracketed line may be and still be read as an ad-lib on the
# line before it; see _fold_onto. Larger than CRY_WORDS, which counts the
# words of a shout, because a bracketed line and a bracketed run of words
# inside a lyric are two different claims. A shout is "(Yeah)" or "(Oh, God)"
# and four words is generous for one. A line the document put in brackets by
# itself is that document saying "second voice", and what a second voice
# sings is a phrase: Skillet's "Rise" answers "In a world gone mad" with
# "（In a place so sad）" -- five words, unmistakably the echo, and it was
# being drawn as a lyric with its brackets showing.
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


# NetEase, QQ Music and Kugou hand their lyrics over in an LRC-shaped
# document, and LRC has nowhere to put a second voice: a backing vocal is
# either a line of its own -- "Yeah", "Uh", "Straight up" -- or a bracket
# sitting inside the lead. fold_cries and split_asides put both back where
# they belong, which is a repair of THOSE sources' shape and of nothing else.
# Spicy Lyrics and amll-ttml-db write real TTML and mark their own
# backgrounds, so running the repair over one of them rewrites a document
# that was already right: an amll copy reading "made chains for the crew
# (Ice)" came apart into a line and an ad-lib nobody asked for, and the
# screen stopped matching Spicy Lyrics' own. So the repair is only offered a
# document one of the three had a hand in.
CJK_MAKERS = ("qq", "kugou", "netease")
# The blends are somebody else's lines under one of those three's word
# timing, and the donor's own ad-lib lines are lifted into them as they are
# built, so they carry the shape in with the timings. Read off BLENDS rather
# than written out, so a sixth blend cannot be added and forgotten here.
CJK_SOURCES = set(CJK_MAKERS) | set(BLENDS)
_CJK_VIA = re.compile("|".join(CJK_MAKERS), re.I)


def lrc_shaped(doc) -> bool:
    """Whether NetEase, QQ Music or Kugou had a hand in this document.

    Three marks are read, because that hand can arrive by three routes:
    `_source` is the provider the walk settled on, `_alone` is the one a
    blend stood down to when its own answer was thinner, and `_via` names the
    upstream a proxy answered from -- Lyrics+ says "qq" where the server's own
    race picked QQ Music, and a blend writes out its whole makeup, "Apple
    Music + QQ Music + NetEase".

    A grafted document is deliberately not one of them. There NetEase lends
    its word timings and nothing else; the lines, the brackets and the
    ad-libs on screen are all Spicy Lyrics' own, and they are not this
    repair's to make.
    """
    seen = [doc if isinstance(doc, dict) else {}, SL.payload(doc or {})]
    for d in seen:
        # `_alone` settles it on its own, in both directions: a blend that
        # stood down is not a blend any more, it is exactly the one document
        # it stood down to. A triblend holding LRCLIB's copy has nothing of
        # NetEase or QQ in it, and one holding NetEase's own has nothing else.
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
    # Brackets round a whole line do not always mean an ad-lib. Round a shout
    # -- "(Yeah)", "(Oh, God)" -- they do, and that is what this is for. Round
    # a whole sung sentence they mean the other thing entirely: a second voice
    # singing a line of its own, or a call answering the verse. "(Caught up in
    # the storm but we're the survivors)" is nine words and a complete lyric,
    # and folding it into the line above turned a line somebody sings into a
    # whisper hanging off the end of another one.
    #
    # A line standing on its own may be a phrase -- see ASIDE_WORDS. One with
    # another bracketed line beside it has to be a shout to come along, which
    # is the count fold_cries uses for the same judgement.
    said = SL.line_text({"Lead": {"Syllables": syls}}) or ""
    cap = ASIDE_WORDS if alone else CRY_WORDS
    if len([w for w in said.strip(UNBRACKET + " ").split() if _key(w)]) > cap:
        return False
    if isinstance(was, (int, float)) and not (was - ASIDE_REACH <= begin
                                              <= was + ASIDE_REACH):
        return False
    said = [{**y, "Text": (y.get("Text") or "").strip(UNBRACKET + " ")}
            for y in _unlump(syls)]
    # A bracket the source wrote as a syllable of its own is nothing at all
    # once the bracket comes off, and an empty syllable still takes a word's
    # turn to light on the screen.
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
            continue                       # the line IS the ad-lib
        # The bracket does not have to be alone on its syllable, and where it
        # is not, everything outside it belongs to the LEAD. QQ times
        # "Yeah (Now she missin' me), yo" with the close and the comma glued
        # into one syllable, "me),": strip only the edges of that and the
        # ad-lib keeps "me)," while the lead's words run together as "Yeahyo",
        # having lost the comma and the space it was holding. So the syllable
        # is cut at the bracket instead, and what was outside is handed back.
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
        # After the edges, so the mark this puts back is not stripped off
        # again as one of theirs. It goes on the word before the ad-lib where
        # there is one -- punctuation trailing a bracket is the lead's
        # sentence carrying on -- and on the word after it where there is not.
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
    kept = []
    for i, y in enumerate(syls):
        if i in drop:
            continue
        if i in edits:
            if not edits[i]:
                continue
            y = {**y, "Text": edits[i]}
        kept.append(y)
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
            # Whatever was hanging off the folded line comes with it. An
            # ad-lib can have an ad-lib -- "Oh, yeah" with a "Uh" against it --
            # and taking only the line's own words dropped the second one out
            # of the song entirely.
            for g in (it.get("Background") or []):
                if isinstance(g, dict):
                    groups.append(g)
                    e = g.get("EndTime")
                    if isinstance(e, (int, float)):
                        end = e if not isinstance(end, (int, float)) else max(end, e)
            if isinstance(end, (int, float)) and isinstance(host.get("EndTime"), (int, float)):
                host["EndTime"] = max(host["EndTime"], end)
            continue
        # A copy deep enough to own its own Background list. Appending to the
        # one that came in reaches back into the caller's document -- and the
        # caller here is the cache, so the next reader of that document would
        # have found ad-libs on it that nobody put there.
        fresh = dict(it)
        if isinstance(fresh.get("Background"), list):
            fresh["Background"] = list(fresh["Background"])
        out.append(fresh)
    got = {k: v for k, v in body.items() if k not in ("Content", "Lines")}
    got["Content"] = out
    return got


# --------------------------------------------------------------------------
# A masked word, filled back in from a source that wrote it out.
#
# Apple Music carries the clean edit of a great many songs, and it marks what
# was taken out rather than dropping it: "n***a", "f**k", "****". Nothing is
# missing there but the letters -- the syllable is in the document, it is
# timed, and it is being sung -- so it can be filled in from a source that
# writes the word down. Two are asked, and both are already in the chain:
# Musixmatch, which is matched by Spotify id and answers explicit, and LRCLIB
# behind it, which needs no key and has almost everything.
#
# The letters go back one at a time. A mask is believed about every character
# it really wrote and only the `*` are filled in, so "F**k" comes back "Fuck"
# and never "fuck", and "n***a," keeps its comma. A donor word may only fill
# a mask it is exactly the shape of, in a document that agrees with the donor
# about the words either side of it -- so a cover, a remix or the wrong
# single cannot write a word of its own into the middle of a line.
MASK = "*"
# Punctuation to look past at either end of a word. The mask is matched
# against somebody else's spelling of the same word, and two sources disagree
# about commas far more often than they disagree about letters.
UNMASK_EDGE = "\"'`“”‘’(){}[]<>,.!?;:…-–—"
# What share of a document's plain words a donor has to spell the same way
# before it is allowed to fill anything in. Half is the same bar _shared
# holds a blend donor to, and for the same reason: a donor about some other
# recording does not quietly agree with half of this one.
UNMASK_SHARE = 0.5
# How far either side of where the alignment leaves it a donor word may be
# picked up. A mask sits in the gap between two stretches that matched, and
# the gap is usually the mask alone; anything further out than a few words is
# not this word being spelled differently, it is a line nobody matched.
UNMASK_REACH = 4
# Who is asked for the words, in order.
UNMASK_FROM = ("mxm", "lrclib")

# A title that says the recording itself is the clean one.
#
# The whole premise above is that the DOCUMENT was censored and the RECORDING
# was not -- Apple files the clean lyric against a song whose audio says the
# word, and the letters are all that is missing. Where the recording is the
# clean edit too, putting them back is the feature running backwards: the
# screen says "fuck" over a bar of silence.
#
# Written narrowly on purpose. It matches a MARKER -- parenthesised, bracketed,
# or hung off a dash at the end -- and never a bare word, because "clean" is a
# word songs are allowed to be called: "Mr. Clean" is a title and Clean Bandit
# is a band. And "Radio Edit" is deliberately not in here. A radio edit is a
# LENGTH edit far more often than a censored one -- there are two in ./lyrics
# that say the words perfectly plainly -- and turning uncensoring off for all
# of them to catch the few would be trading a rare wrong word for a common
# missing one.
#
# EDITION in lyrics_gui and _NOISE above both know these suffixes already and
# both STRIP them, which is the opposite job: they are making two catalogues
# agree about which song this is, and this is asking which CUT of it is playing.
CLEAN_MARK = re.compile(
    r"[\(\[]\s*(?:clean|censored|edited)(?:\s+(?:version|edit))?\s*[\)\]]"
    r"|[-\u2013\u2014]\s*(?:clean|censored|edited)(?:\s+(?:version|edit))?\s*$",
    re.I)


def clean_edit(doc, tid: str, meta: dict, enabled=None) -> str:
    """Why this recording looks like the clean cut, or "" if it does not.

    Four questions, cheapest first, and the string that comes back is the one
    the window puts on screen -- a mask left standing with nothing said about
    it is how a provider that had quietly failed went unnoticed for weeks.

    Only ever reached for a document that HAS masks: `uncensor` counts them
    before it asks anything, and the great majority of songs have none. So the
    order below is about what the rare song costs, not the common one.

    None of the four is allowed to answer from silence. A source that was not
    asked, or was asked and had nothing, says nothing -- it does not say the
    recording is explicit, and it does not say it is clean.
    """
    # 1. Somebody's own file. The masks in it were put there by the person
    #    whose screen this is, timed against the copy they were listening to,
    #    and a document that was made by hand is not a document with a defect
    #    in it. This one is not evidence about the recording at all; it is
    #    about whose words these are.
    hand = str((doc or {}).get("_hand") or "")
    if hand:
        return f"timed by hand \u00b7 {hand}"
    # 2. The title, which costs nothing and is right whenever it speaks. It is
    #    also the only one of the four that works away from Spotify: MPRIS and
    #    the Windows session hand over a title and an album and no flags at all.
    for field in ("title", "album"):
        text = str((meta or {}).get(field) or "")
        if text and CLEAN_MARK.search(text):
            return f"the {field} says so"
    # 3. Spotify's own flag for the track the player has open. The best
    #    evidence there is and the cheapest: it came down with the title in
    #    the same reading, it names the RECORDING rather than the song -- a
    #    clean edit and the master it was cut from are two different tracks
    #    with two different ids -- and nothing had to be searched for to get
    #    it, so nothing can have been mismatched on the way. None where the
    #    player did not say, which is every transport but Spicetify.
    said = (meta or {}).get("explicit")
    if said is not None:
        return "" if said else "Spotify says this cut is clean"
    # 4. Musixmatch, which is asked the same way -- `_mxm_ask` sends
    #    track_spotify_id -- and is the fallback for the transports that hand
    #    over no flag of their own. Skipped when the user has switched
    #    Musixmatch off: it is not asked as a donor then either.
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
            # Whatever is under a mask is a letter. A donor that has
            # punctuation there is spelling something else.
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
        # Fewer letters than stamps. They go at the front, so the word starts
        # where the mask started -- which is the one thing about its timing
        # that is actually known.
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
        # Two letters at least. A single letter standing where a word was
        # taken out is a donor that has split something up rather than the
        # word itself -- and "a" or "I" in that slot means the mask was never
        # hiding a word of this kind at all.
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
    # The longest subsequence of those that also moves forward in b.
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
        # Stars at both ends, or at neither: this is a mask written over one
        # word, and the word it was written over is the whole of it.
        return ""
    said, run = (core[:-tail], core[-tail:]) if tail else (core[lead:], core[:lead])
    if not any(c.isalnum() for c in said):
        # No letters to check the glue against. "a" is enough -- it still has
        # to BE the donor's word at that place, and one letter agreeing where
        # the alignment says it should is the same evidence as five.
        return ""
    j = at if tail else at + 1           # where the letters should be
    k = at + 1 if tail else at           # and the word that was taken out
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
    # The donor's slots rather than only its words: which of them begin a
    # line is what says whether a capital it hands over is about the word or
    # about where that source decided to break. See _uncapped.
    yours = _word_slots(_items(SL.payload(donor or {})))
    theirs = [text for _where, _which, text in yours]
    if not holes or not theirs:
        return doc, 0

    a = [_slot_key(k, text) for k, (_w, _i, text) in enumerate(mine)]
    b = [_key(w) or f"\x01{k}" for k, w in enumerate(theirs)]
    anchors = _spine(a, b)
    real = sum(1 for x in a if not x.startswith("\x00"))
    if not real or len(anchors) < UNMASK_SHARE * real:
        # Not this recording. Every word it could offer would be a guess.
        return doc, 0

    fixes, mends, only = {}, 0, {}
    for k in holes:
        mask = mine[k][2]
        at = bisect.bisect_left(anchors, (k, -1))
        i0, j0 = anchors[at - 1] if at else (-1, -1)
        i1, j1 = anchors[at] if at < len(anchors) else (len(a), len(b))
        want = j0 + (k - i0)
        # The gap between the two stretches that did match, if the two of
        # them left one where this word is. They do not always: the aligner
        # is free to match a chorus to the same chorus sung later, and where
        # it has, the stretch after the mask begins BEFORE the stretch in
        # front of it ends. Nothing is lost by it -- a chorus matched to
        # itself spells the same words -- but there is no window to read.
        lo = hi = 0
        if j0 < want < j1:
            lo = max(j0 + 1, want - UNMASK_REACH)
            hi = min(j1, want + UNMASK_REACH + 1)
        # The rules in order of how much they know, and every one of them
        # asked before the one under it. The order is not housekeeping: a mask
        # glued to the word in front of it -- "We****" -- is the exact shape
        # of a mask written over a longer word, so a rule that goes looking
        # for one anywhere in the donor will find a word that fits and be
        # wrong. It only gets to look once the rules that know WHERE they are
        # have had their turn.
        got, src = "", None
        if _blank(mask):
            # Nothing to match, so nothing but the place: the mask stands in a
            # stretch between two words both documents share, and the two of
            # them put the SAME NUMBER of words in that stretch. Then its
            # place in the stretch names one word of the donor's and no other.
            #
            # Asking instead that both its neighbours anchor -- which is the
            # same rule with a stretch of one -- turned down every mask whose
            # neighbours the two sources merely spell differently, and that is
            # not rare: two transcriptions of the same line disagree about
            # where a word ends far more often than they disagree about what
            # is sung. A stretch that has grown or shrunk between the two IS
            # turned down, because then nothing says which word of it went.
            if i0 < k < i1 and j0 < want < j1 and i1 - i0 == j1 - j0:
                got, src = _stand_in(mask, theirs[want]), want
        else:
            # Nearest the alignment's guess first, so a line with two masks in
            # it takes them in the order they are sung rather than the order
            # the window happens to be scanned in.
            for j in sorted(range(lo, hi), key=lambda x: (abs(x - want), x)):
                got = _fill(mask, theirs[j])
                if got:
                    src = j
                    break
        if not got and j0 < want and want + 1 < j1:
            # Two of the donor's words where the document has one: the mask
            # may have been glued to its neighbour on the way through a blend.
            got = _unglue(mask, theirs, want)
        if not got and not _blank(mask):
            got = _only_fit(mask, theirs, only)
        if not got and not _blank(mask) and i1 - i0 == 2 and j1 - j0 == 2 \
                and 0 <= want < len(theirs) and _like(mask, theirs[want]):
            # The mask has been cut about on its way through a blend and no
            # longer has the shape of anything. Its letters are still in the
            # donor's word, in order, and both documents put exactly one word
            # in this place -- so it is that word, whatever length the mask
            # was left with.
            got, src = _recase(mask, _stand_in(mask, theirs[want])), want
        if got:
            # Only where one of the rules above named a word of the donor's.
            # _unglue builds its answer out of two of them and _only_fit finds
            # its word by searching the whole document, so neither has a line
            # of the donor's to hold responsible for a capital.
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
            # Right to left, so an offset is still the offset it was measured
            # at when a syllable holds two words and both of them were masked.
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
                # The line itself was holding the words, so filling them in
                # has already rewritten the only copy there is.
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
            # Unlumped again because a mend can put a space back where a blend
            # lost one, and two words under one stamp is exactly what unlump
            # is for -- see _unglue.
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
            # The base's own end, where it has one that stands clear of the
            # next line. NetEase stamps a line to where the next one begins,
            # so grafting its end onto a document that knows when the singing
            # actually stopped holds the line lit through the silence after
            # it -- the same trade the blends were making with QQ and Kugou.
            # Never into the words: if the base wants to end before a word
            # that has already finished, it is not describing this line.
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
    # A graft only ever runs on a line-quality base -- it is refused above
    # otherwise -- so these lines are lifted by definition.
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
