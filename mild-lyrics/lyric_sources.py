"""Every lyric provider: Spicy Lyrics, asked first and alone by track id, then
the chain (amll-ttml-db, blends, NetEase, Kugou, QQ, Kuwo, lrc.red, LRCLIB,
Musixmatch). All converted to spicy_lyrics.timeline()'s shape."""

from __future__ import annotations

import bisect
import collections
import functools
import html
import json
import os
import pathlib
import re
import unicodedata
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import offload
import spicy_lyrics as SL

if os.name == "nt":
    # Windows' proxy bypass check resolves the host (getfqdn) on every
    # request when a system proxy is set, which can take seconds each; the
    # answer for a host does not change within a session.
    urllib.request.proxy_bypass = functools.lru_cache(maxsize=512)(
        urllib.request.proxy_bypass)

REVISION = 1
# The stored walks' own revision: bumped when the PICK changes, so a song is
# walked again the next time it plays rather than keeping a choice the rules
# no longer make. Apart from REVISION so the duet flags are not asked again
# with it. 2: credits read as lyric, and _fullest's letters-only shortness
# (Beat It went to NetEase over BiniLyrics on both counts).
PICK_REVISION = 2

UA = "mild-lyrics/1.0 (+personal lyrics viewer)"
# lrc.red's API terms want a link and a contact address (BiniLyrics is it).
LRCRED_UA = "mild-lyrics/1.0 (+https://github.com/gcoolL/mild-lyrics; gcoolltm@gmail.com)"
TIMEOUT = 8.0

AMLL_RAW = "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main"
LRCLIB_BASE = "https://lrclib.net"

def cache_root() -> pathlib.Path:
    """The cache directory, per platform: Local on Windows, ~/Library/Caches on a
    Mac, XDG_CACHE_HOME elsewhere. Both programs ask here (lyrics_gui.app_dir);
    why each: docs/notes/mild-lyrics/lyric_sources.md, 2026-10-24."""
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or (
            pathlib.Path.home() / "AppData" / "Local")
        return _migrated(pathlib.Path(root))
    root = os.environ.get("XDG_CACHE_HOME")
    if not root and sys.platform == "darwin":
        return _mac_root(".cache", "Caches")
    return _migrated(pathlib.Path(root or (pathlib.Path.home() / ".cache")))


def config_root() -> pathlib.Path:
    """The settings directory, the same way: Roaming on Windows, ~/Library/
    Application Support on a Mac, XDG_CONFIG_HOME elsewhere."""
    if os.name == "nt":
        root = os.environ.get("APPDATA") or (
            pathlib.Path.home() / "AppData" / "Roaming")
        return _migrated(pathlib.Path(root))
    root = os.environ.get("XDG_CONFIG_HOME")
    if not root and sys.platform == "darwin":
        return _mac_root(".config", "Application Support")
    return _migrated(pathlib.Path(root or (pathlib.Path.home() / ".config")))


def _mac_root(legacy: str, library: str) -> pathlib.Path:
    """A Mac's own directory, unless an older copy is already in the XDG one."""
    here = pathlib.Path.home() / legacy
    for slug in ("mild-lyrics", "spicy-lyrics"):
        if (here / slug).is_dir():
            return _migrated(here)
    return _migrated(pathlib.Path.home() / "Library" / library)


def _migrated(root: pathlib.Path) -> pathlib.Path:
    """<root>/mild-lyrics, carrying over the old name's contents once."""
    new, old = root / "mild-lyrics", root / "spicy-lyrics"
    try:
        if old.is_dir() and not new.exists():
            old.rename(new)
    except Exception:
        pass
    return new


_cache_root = cache_root


CACHE_DIR = _cache_root() / "sources"
COMMUNITY_TTL = 3 * 86400.0
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
    """What we actually have, judged by the data rather than the Type field:
    word timing only when most lines carry timed syllables."""
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
    """Whether this thread's walk is still wanted; True where nobody said.
    Never raises."""
    alive = getattr(_WALK, "alive", None)
    if alive is None:
        return True
    try:
        return bool(alive())
    except Exception:                                    # noqa: BLE001
        return True


def _latched(alive):
    """A walk's cancel token, made final: once told no it stays told and stores
    nothing, so a blink of "not wanted" cannot leave a half answer on disk."""
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
    """`fn`, run as part of the walk `alive` speaks for; `people` rides along
    for from_unison, which chooses before the walk sees anything."""
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
    """File one failure against whoever the walk is asking, keeping only the
    first; `whom` names it where the walk has not."""
    faults = getattr(_WALK, "faults", None)
    who = getattr(_WALK, "who", "") or whom
    if faults is not None and who:
        faults.setdefault(who, why)


# Told about every provider a walk asks, as TRACE(tid, name, seconds, answer,
# why) -- `why` the fault filed against it, or "". Set by the player's debug
# overlay; see debug_hud. Called on the walk's own threads, and never allowed
# to break the walk.
TRACE = None


def _asks(name: str, fn, tid: str = ""):
    """`fn`, with whatever it does to the network filed under `name`.

    `tid` is only for TRACE: a blend's nested ask for its donor passes none,
    and is counted in the blend's own time.
    """
    tell = TRACE if tid else None
    ask = fn

    def fn():
        """A note saying there are no words is no answer: see wordless."""
        got = ask()
        return None if wordless(got) else got

    if tell is None:
        return _under(getattr(_WALK, "alive", None), fn, who=name)
    began, got, why = time.perf_counter(), None, ""
    part = {"name": name, "told": False,
            "tell": lambda who, secs, doc, why: tell(tid, who, secs, doc, why)}
    was, _WALK.part = getattr(_WALK, "part", None), part
    try:
        got = _under(getattr(_WALK, "alive", None), fn, who=name)
    except Exception as e:                               # noqa: BLE001
        why = _why(e)
        raise
    finally:
        _WALK.part = was
        why = why or (getattr(_WALK, "faults", None) or {}).get(name, "")
        try:
            if not part["told"]:
                tell(tid, name, time.perf_counter() - began, got, why)
        except Exception:                                # noqa: BLE001
            pass
    return got


# The doors a provider reports to TRACE one by one rather than as itself, in
# the order it asks them. See _door.
PROVIDER_PARTS = {"bini": ("lrc.red", "bini")}


def _door(provider: str, name: str, fn):
    """`fn`, one door of `provider`, traced under its own `name` when the walk
    asks `provider` itself; its fault is then handed on to the provider's."""
    part = getattr(_WALK, "part", None)
    if not part or part["name"] != provider:
        return fn()
    outer, mine = getattr(_WALK, "faults", None), {}
    began, got, why = time.perf_counter(), None, ""
    try:
        got = _under(getattr(_WALK, "alive", None), fn, faults=mine, who=provider)
    except Exception as e:                               # noqa: BLE001
        why = _why(e)
        raise
    finally:
        if outer is not None:
            for k, v in mine.items():
                outer.setdefault(k, v)
        part["told"] = True
        try:
            part["tell"](name, time.perf_counter() - began,
                         None if wordless(got) else got, why or mine.get(provider, ""))
        except Exception:                                # noqa: BLE001
            pass
    return got


_HOST_CAP: dict[str, int] = {}
_HOST_CAP_DEFAULT = 4
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


_host_hush: dict[str, float] = {}
_HUSH_DEFAULT = 30.0
_HUSH_MAX = 3600.0


def _hushed(url: str) -> bool:
    """Whether this URL's host has asked to be left alone for now."""
    until = _host_hush.get(urllib.parse.urlsplit(url).netloc)
    if until is None:
        return False
    if time.monotonic() >= until:
        _host_hush.pop(urllib.parse.urlsplit(url).netloc, None)
        return False
    return True


def _hush_from(url: str, e) -> None:
    """Note a refusal's asked-for wait against its host, if it is one."""
    if getattr(e, "code", None) not in (429, 503):
        return
    heads = getattr(e, "headers", None) or {}
    after = (_head_secs(heads, "Retry-After")
             or _head_secs(heads, "RateLimit-Reset")
             or (_HUSH_DEFAULT if e.code == 429 else 0.0))
    if after > 0:
        host = urllib.parse.urlsplit(url).netloc
        _host_hush[host] = max(_host_hush.get(host, 0.0),
                               time.monotonic() + min(after, _HUSH_MAX))


def _get(url: str, accept: str = "*/*") -> bytes | None:
    if not _walking():
        return None
    if _hushed(url):
        _blamed("asked to wait")
        return None
    host = urllib.parse.urlsplit(url).hostname or ""
    ua = LRCRED_UA if any(host == h or host.endswith("." + h) for h in BINI_HOSTS) else UA
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": accept})
    wait = _patience(url)
    with _gate(url):
        if not _walking():
            return None
        if _hushed(url):
            _blamed("asked to wait")
            return None
        try:
            with urllib.request.urlopen(req, timeout=wait) as r:
                if r.status == 200:
                    return r.read()
                _blamed(f"HTTP {r.status}")
                return None
        except urllib.error.HTTPError as e:
            _hush_from(url, e)
            if e.code not in MISSED:
                _blamed(_why(e, wait))
            return None
        except Exception as e:                           # noqa: BLE001
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


def read_pushed(xml: str, split: str, threshold: float):
    """A document the editor pushed, read: (body, drawable lines). Here, at
    module level, so the player can have it done in another process -- see
    LyricsView.show_live_lyric_soon."""
    body = parse_ttml(xml)
    return body, (SL.timeline(body, split=split, threshold=threshold)
                  if body else None)


def _secs(v) -> float | None:
    """TTML clock value -> seconds. Handles h:mm:ss.mmm, mm:ss.mmm, 12.5s, 300ms."""
    if not isinstance(v, str):
        return None
    return _secs_of(v)


@functools.lru_cache(maxsize=16384)
def _secs_of(v: str) -> float | None:
    """_secs on a string, remembered: the editor pushes the same document
    every few hundred ms, and this was ~8ms of each push on the window."""
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
OPENS = _OPENS + "\"'\u2018"


def _apart(a: str, b: str) -> bool:
    """Whether a space belongs between these two spans whatever the file says:
    only around unambiguous quotation marks (not ’, not CJK brackets)."""
    if not (a and b and (b[0] in _OPENS or a[-1] in _CLOSES)):
        return False
    # 傾(かぶ)けば: a kana reading in brackets against Japanese is inside
    # the word it reads.
    if (b[0] in "(（" and _KANA_RE.match(b[1:2]) and _CJK_RE.match(a[-1])) \
            or (a[-1] in ")）" and _KANA_RE.match(a[-2:-1])
                and _CJK_RE.match(b[0])):
        return False
    return True


_KANA_RE = re.compile(r"[぀-ヿ]")
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿々]")


def _syllables(parent, spaced: bool = True) -> list[dict]:
    """Timed <span> children -> Syllables, word breaks from spacing (each span
    a word when the file never spaces, except CJK); untimed spans kept when
    nothing is timed."""
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
    """Re-time syllables stamped outside their line (e.g. 00:00.000),
    interpolated from sane neighbours; overlaps inside the line are left
    alone."""
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
# 「」 quote a word the lead sings, so inline it is never a backing vocal.
BG_PAIRS = {k: v for k, v in PAIRS.items() if k != "「"}


def _unbracket(text: str) -> str:
    """The same peel as `_unwrap`, for an ad-lib written as one piece of text."""
    close = PAIRS.get(text[:1])
    if close and len(text) > 2 and text.endswith(close):
        return text[1:-1].strip() or text
    return text


def _unwrap(syls: list[dict]) -> list[dict]:
    """Peel brackets baked into a backing vocal's text, only when they pair up
    across the group."""
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
    """Treat a document whose stamps never advance as static, and say so."""
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


def _credits(root) -> tuple[list[str], str, str, dict]:
    """Who wrote the song, who timed this copy, their id (GitHub, prefixed) and
    what song it is, from Apple, lyricsplus and amll tags by local name."""
    head = next((el for el in root if _tag(el) == "head"), root)
    writers, maker, uid, seen, said = [], "", "", set(), {}
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
            elif key == "ttmlAuthorGithub" and value.isdigit():
                uid = uid or "github:" + value
            elif key in SL.AMLL_LABELS and value:
                said.setdefault(SL.AMLL_LABELS[key], value)
    return writers, maker, (uid if maker else ""), said


def _agents(root) -> list[str]:
    """The voices the header declares, in declaration order (the first is the
    near side), not the order lines use them."""
    head = next((el for el in root if _tag(el) == "head"), root)
    out: list[str] = []
    for el in head.iter():
        if _tag(el) != "agent":
            continue
        got = _attr(el, "id")
        if got and got not in out:
            out.append(got)
    return out


def _translits(root) -> dict:
    """Apple's per-syllable readings by line key: {key: (lead readings, [bg
    readings, ...])}."""
    out: dict = {}
    for el in root.iter():
        if _tag(el) != "text" or not _attr(el, "for"):
            continue
        lead, bgs = [], []
        for sp in el:
            if _tag(sp) != "span":
                continue
            if _attr(sp, "role") == "x-bg":
                bgs.append([("".join(x.itertext()).strip(),
                             _secs(_attr(x, "begin")))
                            for x in sp if _tag(x) == "span"
                            and not _attr(x, "role")])
            elif not _attr(sp, "role"):
                lead.append(("".join(sp.itertext()).strip(),
                             _secs(_attr(sp, "begin"))))
        out.setdefault(_attr(el, "for"), (lead, bgs))
    return out


def _x_roman(el) -> str:
    """The reading an amll-ttml-db file gives a whole line or backing run."""
    for sp in el:
        if _tag(sp) == "span" and _attr(sp, "role") == "x-roman":
            got = " ".join("".join(sp.itertext()).split())
            if got:
                return got
    return ""


def _pair_roman(syls: list[dict], said: list) -> None:
    """Hang readings on syllables: by position when the counts agree, and
    by start time when they do not."""
    if not said or not syls:
        return
    if len(said) == len(syls):
        for y, (r, _t) in zip(syls, said):
            if r:
                y["TransliteratedText"] = r
        return
    at = {}
    for r, t in said:
        if r and t is not None:
            at.setdefault(round(t, 3), r)
    for y in syls:
        t = y.get("StartTime")
        if isinstance(t, (int, float)) and round(t, 3) in at:
            y["TransliteratedText"] = at[round(t, 3)]


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
    translits = _translits(root)
    for p in paras:
        ps, pe = _secs(_attr(p, "begin")), _secs(_attr(p, "end"))
        lead = _group(p, spaced)
        said_lead, said_bg = translits.get(_attr(p, "key") or "", ([], []))
        _pair_roman(lead["Syllables"], said_lead)
        bg = []
        ahead = not (p.text or "").strip()
        for sp in p:
            role = _attr(sp, "role") if _tag(sp) == "span" else None
            if role == "x-bg":
                g = _group(sp, spaced, bg=True)
                if ahead and not isinstance(g.get("StartTime"), (int, float)):
                    g["LeadIn"] = True
                if not g["Syllables"]:
                    g["Text"] = _unbracket("".join(
                        [sp.text or ""] + ["".join(x.itertext()) + (x.tail or "")
                                           for x in sp if not _attr(x, "role")]
                    ).strip())
                if len(bg) < len(said_bg):
                    _pair_roman(g["Syllables"], said_bg[len(bg)])
                rom = _x_roman(sp)
                if rom:
                    g["TransliteratedText"] = rom
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
        rom = _x_roman(p)
        if rom:
            item["TransliteratedText"] = rom
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
    writers, maker, uid, said = _credits(root)
    if writers:
        doc["SongWriters"] = writers
    if maker:
        doc["_maker"] = maker
    if uid:
        doc["_maker_id"] = uid
    doc.update(said)
    return doc


def _deword(doc: dict) -> dict:
    """Word-timed document -> line-timed, keeping the line stamps."""
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
    """_norm, with any version marker kept apart, so "Galaxies (Remix)" and
    "Galaxies" key differently. See ALT_CUT."""
    cut = _cut_words(name)
    return _norm(name) + ("\x01" + ",".join(sorted(cut)) if cut else "")


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
SPICY_BASE = (os.environ.get("SPICY_LYRICS_API")
              or "https://api.spicylyrics.org").rstrip("/")
SPICY_ID = re.compile(r"^[A-Za-z0-9]{22}$")
SONG_KEY_HEX = re.compile(r"[0-9a-f]{22}")       # a name key, never a Spotify id (odds ~1e-13)

SPICY_CODES = {"spicy_lyrics": "spl", "apple_music": "aml", "spotify": "spt",
               "unknown": ""}

SPICY_SHIPPED_KEY = "sl_pk_2fyQ-sFN0OnWEjG9WmusHHY9vS8Re7zHj3kSbJncHbM"

SPICY_KEY_ENV = ("SPICY_LYRICS_KEY", "SPICY_LYRICS_SECRET_KEY")
SPICY_KEY_FILE = config_root() / "spicy-key.txt"

SPICY_DIR = _cache_root() / "spicy"
SPICY_REV = 1

_spicy_hushed = 0.0
_spicy_hushed_why = ""

SPICY_LIMIT: dict = {}


class SpicyError(Exception):
    """Spicy Lyrics could not be asked or would not answer (not "no lyrics",
    which is None). `code`, `status` and `after` are the service's."""

    def __init__(self, why: str, code: str = "", status: int = 0,
                 after: float = 0.0):
        super().__init__(why)
        self.code, self.status, self.after = code, int(status), float(after)

    @property
    def temporary(self) -> bool:
        """An outage or a throttle that clears itself, not worth a toast.

        The next source in the chain answers for the song in the meantime,
        so "Upstream lyrics access is temporarily unavailable" said on the
        screen is news about somebody else's server and nothing to act on.
        """
        return (not self.key_fault
                and (self.status == 0 or self.status >= 500
                     or self.status == 429 or self.status == 408
                     or self.code.startswith("upstream")
                     or self.code == "rate_limited"))

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
    """Keep a Spicy key for next time in the config directory, readable only by
    its owner; publishable keys go in SPICY_SHIPPED_KEY."""
    SPICY_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SPICY_KEY_FILE.write_text(value.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(SPICY_KEY_FILE, 0o600)
    except OSError:
        pass
    return SPICY_KEY_FILE


# --------------------------------------------------------------------------
SPOTIFY_IDS = _cache_root() / "spotify-ids.json"
_sp_ids: dict | None = None
_sp_lock = threading.Lock()


SPOTIFY_SESSION = _cache_root() / "spotify-token.json"


def keep_spotify_session(token: str, exp_ms: float) -> None:
    """The desktop app's own token, kept like the Apple Music key is."""
    exp = exp_ms / 1000.0 if exp_ms else time.time() + 3000
    try:
        SPOTIFY_SESSION.parent.mkdir(parents=True, exist_ok=True)
        SPOTIFY_SESSION.write_text(json.dumps({"token": token, "exp": exp}),
                                   encoding="utf-8")
        os.chmod(SPOTIFY_SESSION, 0o600)
    except Exception:                                    # noqa: BLE001
        pass


def _spotify_session() -> tuple[str, float]:
    try:
        got = json.loads(SPOTIFY_SESSION.read_text(encoding="utf-8"))
        return str(got.get("token") or ""), float(got.get("exp") or 0)
    except Exception:                                    # noqa: BLE001
        return "", 0.0


def forget_spotify_session() -> None:
    """Delete the kept desktop token, as Spotify lookup is turned off."""
    try:
        SPOTIFY_SESSION.unlink(missing_ok=True)
    except Exception:                                    # noqa: BLE001
        pass


def spotify_session_left() -> float:
    """Seconds the kept desktop token has left, 0 where there is none."""
    tok, exp = _spotify_session()
    return max(0.0, exp - time.time()) if tok else 0.0


def _spotify_token() -> str:
    """The token kept from the desktop app while it lasts, else ""."""
    if spotify_session_left() > 60:
        return _spotify_session()[0]
    return ""


_WEB_WAIT = [0.0]      # Spotify's Retry-After: no Web API asks before this (monotonic)


def _compilation(album: dict) -> bool:
    """Whether a Web API album is a various-artists compilation, which shares its ISRCs
    with the artist's own release."""
    return (album.get("album_type") == "compilation"
            or any(str(a.get("name") or "").lower() == "various artists"
                   for a in album.get("artists") or []))


def spotify_web_search(meta: dict) -> list[dict] | None:
    """Spotify's catalogue over its Web API in JS_SEARCH's row shape, or None;
    ISRC hits carry "isrc": True. `meta["isrcs"]` overrides Apple's."""
    try:
        tok = _spotify_token()
    except Exception:                                    # noqa: BLE001
        return None
    if not tok or time.monotonic() < _WEB_WAIT[0]:
        return None                                      # none kept, or still in Spotify's "retry after"

    def ask(q: str) -> list[dict]:
        url = ("https://api.spotify.com/v1/search?"
               + urllib.parse.urlencode({"q": q, "type": "track", "limit": 10}))
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            items = ((json.loads(r.read().decode("utf-8")) or {})
                     .get("tracks") or {}).get("items") or []
        return [{"kind": "Track", "uri": str(t.get("uri") or ""),
                 "name": str(t.get("name") or ""),
                 "sub": ", ".join(a.get("name", "") for a in t.get("artists") or []),
                 "ms": int(t.get("duration_ms") or 0),
                 "album": str((t.get("album") or {}).get("name") or ""),
                 "compilation": _compilation(t.get("album") or {})}
                for t in items if isinstance(t, dict)]

    rows: list[dict] = []
    try:
        codes = meta["isrcs"] if "isrcs" in meta else apple_isrcs(meta)    # a song's own codes, given
        for code in (codes or [])[:3]:
            rows += [dict(r, isrc=True) for r in ask(f"isrc:{code}")]
        title = str(meta.get("title") or "").strip()
        artist = str(meta.get("artist") or "").strip()
        if title:
            rows += ask(f"{title} {artist}".strip())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            try:
                wait = float(e.headers.get("Retry-After") or 30)
            except (TypeError, ValueError):
                wait = 30.0
            _WEB_WAIT[0] = time.monotonic() + max(5.0, min(wait, 3600.0))
        return rows or None
    except Exception:                                    # noqa: BLE001
        return rows or None
    return rows


def spotify_id_known(tid: str) -> str | None:
    """A Spotify id found for this song before, kept on disk."""
    global _sp_ids
    with _sp_lock:
        if _sp_ids is None:
            try:
                _sp_ids = json.loads(SPOTIFY_IDS.read_text(encoding="utf-8"))
            except Exception:                            # noqa: BLE001
                _sp_ids = {}
        return _sp_ids.get(tid)


def spotify_id_keep(tid: str, sid: str) -> None:
    spotify_id_known(tid)
    with _sp_lock:
        _sp_ids[tid] = sid
        try:
            SPOTIFY_IDS.parent.mkdir(parents=True, exist_ok=True)
            SPOTIFY_IDS.write_text(json.dumps(_sp_ids), encoding="utf-8")
        except Exception:                                # noqa: BLE001
            pass


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
    """Note what is left of this application's Spicy window, and stop when it
    is spent."""
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
    """Spicy Lyrics' document for one track, or None where it has no lyrics;
    anything else (including a malformed id) raises SpicyError."""
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
        if exc.code == 404 and bad.code in ("lyrics_not_found", "not_found", ""):
            return None
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
    """A Spicy document as this project keeps it: zero-width spaces removed,
    the catalogue code renamed, credits under TTMLUploadMetadata, the track
    id filled."""
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
# --------------------------------------------------------------------------
def _spicy_path(track: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", track or "unknown")[:64]
    return SPICY_DIR / f"{safe}.json"


def _spicy_record(track: str, touch: bool = True) -> dict | None:
    """The stored answer for a track, or None: a miss ages from when it was
    taken (six hours), a hit from when it was last used."""
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
    if (str(rec["doc"].get("source") or "") == "spl"
            and time.time() - at > COMMUNITY_TTL):
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


SPICY_FAIL_WAIT = 30.0
_spicy_failed: dict = {}
_spicy_fresh: set = set()


def spicy_lyrics(track: str, refresh: bool = False, timeout: float = TIMEOUT):
    """Spicy Lyrics' document for a track, from disk or asked for; None means
    it has nothing, SpicyError is never cached."""
    asked = track in _spicy_fresh
    if asked:
        _spicy_fresh.discard(track)
        refresh = True
    if not refresh:
        rec = _spicy_record(track)
        if rec is not None:
            doc = rec.get("doc")
            return doc if isinstance(doc, dict) and doc else None
    failed = _spicy_failed.get(track)
    if failed and time.monotonic() < failed[0]:
        raise failed[1]
    try:
        doc = _spicy_fetch(track, timeout=timeout)
    except SpicyError as exc:
        if exc.temporary:
            if len(_spicy_failed) > 256:
                _spicy_failed.clear()
            _spicy_failed[track] = (time.monotonic()
                                    + max(exc.after, SPICY_FAIL_WAIT), exc)
            if asked:
                held = spicy_held(track)
                if held:
                    return held
        raise
    _spicy_failed.pop(track, None)
    _spicy_keep(track, doc)
    return doc


def from_spicy(tid: str, meta: dict | None = None, local=None, **_kw):
    """Spicy Lyrics in the providers' shape; never raises (trouble goes through
    _blamed). Asked by Spotify id only; name keys are not asked."""
    if SONG_KEY_HEX.fullmatch(tid or ""):
        return None
    try:
        return spicy_lyrics(tid)
    except SpicyError as exc:
        if not exc.temporary:
            _blamed(str(exc), "spicy")
        return None


from_spicy.leads = True
from_spicy.credits_people = True


def community_sync(body) -> bool:
    """Whether this is a Spicy Lyrics community sync: shown here, but never
    saved or handed out as a file -- Apple Music's is offered instead."""
    return str(SL.payload(body or {}).get("source") or "") == "spl"


def spicy_made(body) -> bool:
    """Whether the Spicy Lyrics API answered with this, whichever catalogue
    -- the editor takes none of them in."""
    said = SL.payload(body or {})
    return (str(said.get("_source") or "") == "spicy"
            or str(said.get("source") or "") in ("spl", "aml", "spt"))


def apple_instead(tid: str, meta: dict) -> dict | None:
    """Apple Music's sync for a song whose community sync may not leave, or
    None where Apple has none. Network: keep it off the GUI thread."""
    try:
        doc = from_apple(tid, meta or {})
    except Exception:                                    # noqa: BLE001
        return None
    return None if wordless(doc) else doc


def spicy_ids() -> list[str]:
    """The tracks a Spicy document is held for here: the songs this machine has
    fetched, not Spicy's catalogue."""
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
    """title+artist -> raw lyric file, built from amll-ttml-db's own index."""
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
    """QQ Music's own document, lines and timings, asked of QQ alone (see _qq)."""
    return _once(("qq", tid, _norm(meta.get("title") or ""),
                  _norm(meta.get("artist") or ""),
                  round(float(meta.get("length") or 0))),
                 lambda: _or_native(_qq, tid, meta))


def from_lrclib(tid: str, meta: dict, local=None) -> dict | None:
    """LRCLIB by exact record (/api/get) where it has one, by search otherwise,
    search hits checked against ALT_CUT."""
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
    doc = parse_lrc(rec.get("syncedLyrics") or "", rec.get("plainLyrics") or "")
    if not doc or _instrumental(_items(doc)):
        return None
    return doc


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
    r")\s*(?:by)?\s*[:：]"
    # NetEase writes credits as "Role : Name"; matched by that shape (credits
    # only, over 79653 cached lines).
    r"|^\s*[^\W\d_][\w&/'’.\- ]{0,38}?\s[:：]\s*\S"
    # And the studio line that closes such a run, which has no colon.
    r"|^\s*(?:recorded|mixed|mastered|engineered|published|administered)"
    r"\s+(?:at|by|in)\b|^\s*[℗©]", re.I)
NE_WROTE = re.compile(
    r"^\s*(作词|作曲|词|曲|lyric(?:s|ist)?|compos(?:ed|er|ition)|writ(?:ten|er)|music)"
    r"\s*(?:by)?\s*[:：]\s*(.+)$", re.I)
# Word-stamped lines: `[start,length]`, then a stamp per word.
STAMP_LINE = re.compile(r"^\[(\d+),(\d+)\]")
YRC_STAMP = re.compile(r"\((\d+),(\d+),\d+\)")    # NetEase: (start,length,0)word
KRC_STAMP = re.compile(r"<(\d+),(\d+),\d+>")      # Kugou: <offset,length,0>word
QRC_STAMP = re.compile(r"\((\d+),(\d+)\)")        # QQ: word(start,length)


def _ne_get(url: str):
    if _hushed(url):
        _blamed("asked to wait")
        return None
    req = urllib.request.Request(url, headers=NE_HEAD)
    wait = _patience(url)
    with _gate(url):
        try:
            with urllib.request.urlopen(req, timeout=wait) as r:
                return json.loads(r.read())
        except Exception as e:                           # noqa: BLE001
            _hush_from(url, e)
            if not isinstance(e, urllib.error.HTTPError) or e.code not in MISSED:
                _blamed(_why(e, wait))
            return None


def _ne_rank(meta: dict) -> list[int]:
    """Plausible NetEase song ids for this track, best first, believed only on
    duration or an exact title; a list because releases differ in timing."""
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
        if not same and key and SL.needs_roman(theirs) and not SL.needs_roman(title):
            # Spotify's romanised title against NetEase's own script.
            same = _norm(SL.reading(theirs)) == key
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


def _words_between(raw: str, start: int, stamps, before: bool):
    """(word, stamp) for a line's stamps: each word after its stamp (KRC, YRC)
    or before it (QRC, LYS). Read between the stamps rather than matched as
    tokens, so a word may hold a bracket -- KiiiKiii's "Phone (" did."""
    out = []
    stamps = list(stamps)
    for k, m in enumerate(stamps):
        if before:
            lo = stamps[k - 1].end() if k else start
            word = raw[lo:m.start()]
        else:
            hi = stamps[k + 1].start() if k + 1 < len(stamps) else len(raw)
            word = raw[m.end():hi]
        out.append((word, m))
    return out


def _stamped_rows(text: str, stamp, before: bool = False, relative: bool = False,
                  unescape: bool = False):
    """(line start, line end, [(word, start, end)]) per word-stamped line, in
    seconds from the song; `relative` stamps count from the line (KRC)."""
    for raw in (text or "").splitlines():
        raw = raw.lstrip("﻿")
        m = STAMP_LINE.match(raw)
        if not m:
            continue
        at = int(m.group(1)) / 1000.0
        base = at if relative else 0.0
        words = []
        for word, s in _words_between(raw, m.end(), stamp.finditer(raw, m.end()), before):
            s_at = base + int(s.group(1)) / 1000.0
            words.append((html.unescape(word) if unescape else word,
                          s_at, s_at + int(s.group(2)) / 1000.0))
        if words:
            yield at, at + int(m.group(2)) / 1000.0, words


def _stamped_items(rows, credit) -> tuple[list[dict], list[str]]:
    """Timed items from _stamped_rows, and whoever the credit lines named.
    `credit(body)` says a line is a credit rather than a lyric."""
    items, wrote = [], []
    for start, end, words in rows:
        body = "".join(w for w, _s, _e in words).strip()
        if not body or credit(body):
            said = NE_WROTE.match(body) if body else None
            for name in (re.split(r"\s*[/、,，&]\s*", said.group(2)) if said else []):
                name = name.strip()
                if name and name not in wrote:
                    wrote.append(name)
            continue
        syls = []
        for word, s, e in words:
            got = word.rstrip()
            if not got:
                if syls:
                    syls[-1]["IsPartOfWord"] = False
                continue
            syls.append({"Text": got, "StartTime": s, "EndTime": e,
                         "IsPartOfWord": word == got})
        if not syls:
            continue
        lead, bg = _ne_bg(syls)
        if not lead:
            lead, bg = syls, []
        lead[-1] = {**lead[-1], "IsPartOfWord": False}
        last = max([end, lead[-1]["EndTime"]] + [g["EndTime"] for g in bg])
        item = {"Text": SL.syllables_text(lead), "StartTime": start, "EndTime": last,
                "Lead": {"StartTime": start, "EndTime": end, "Syllables": lead}}
        if bg:
            item["Background"] = bg
        items.append(item)
    return items, wrote


def _ne_yrc(text: str) -> list[dict]:
    """NetEase word-level lyrics -> timed items."""
    return _stamped_items(_stamped_rows(text, YRC_STAMP), NE_CREDIT.match)[0]


def _ne_lead_cap(text: str) -> str:
    """Capitalise the first letter, leaving any punctuation before it alone."""
    for i, c in enumerate(text or ""):
        if c.isalpha():
            return text[:i] + c.upper() + text[i + 1:]
    return text


def _cut(y: dict, at: int):
    """One syllable split in two at a character, its time shared by length."""
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


def _ne_bg(syls: list[dict], cap: bool = True):
    """A line's syllables split into the lead and its bracketed backing vocals
    (NetEase, Kugou), brackets found inside syllables; unclosed ones go
    back."""
    lead, groups, cur, want, opened = [], [], None, None, ""
    rest = list(syls)
    while rest:
        y = rest.pop(0)
        text = y.get("Text") or ""
        if cur is None:
            at = next((i for i, c in enumerate(text) if c in BG_PAIRS), -1)
            if at < 0:
                lead.append(y)
                continue
            before, after = _cut(y, at)
            if before is not None and (before.get("Text") or "").strip():
                lead.append(before)
            opened = (after.get("Text") or "")[0]
            want, cur = BG_PAIRS[opened], []
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
        if cap:
            # NetEase's own lowercase; a file from disk keeps what it says
            # (lyric_formats passes cap=False).
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
    """Divided lines put back to line level, except where the line has a
    backing vocal."""
    out = []
    for it in items:
        lead = it.get("Lead")
        if (isinstance(lead, dict) and not it.get("Background")
                and _faked(lead.get("Syllables") or [])):
            it = {k: v for k, v in it.items() if k != "Lead"}
        out.append(it)
    return out


def _ne_doc(d: dict, title: str = "", artist: str = "") -> dict | None:
    """One NetEase lyric payload -> a lyrics document, or None if it is empty."""
    get = lambda k: ((d.get(k) or {}).get("lyric") or "")  # noqa: E731
    items = _ne_yrc(get("yrc"))
    if not items:
        rows = _ne_lrc_rows(get("lrc"))
        for i, (t, body) in enumerate(rows):
            nxt = rows[i + 1][0] if i + 1 < len(rows) else None
            end = min(nxt, t + 10.0) if nxt is not None else t + 6.0
            items.append({"Text": body, "StartTime": t, "EndTime": end})
    items = _furniture(items, title, artist)
    if not items or _instrumental(items):
        return None
    items = _unfake(_destamp(items))
    _ne_romanise(items, _ne_roman_pairs(d))
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


def _rkey(text: str) -> str:
    """Text compared for romanisation: width, case, spaces and marks gone."""
    return "".join(c for c in unicodedata.normalize("NFKC", text or "").lower()
                   if c.isalnum())


def _ne_roman_pairs(d: dict) -> list[tuple]:
    """(time, lrc text, romanisation) rows. romalrc is stamped to lrc, not to
    yrc, so it is paired with lrc by its own timestamps."""
    get = lambda k: ((d.get(k) or {}).get("lyric") or "")  # noqa: E731
    roma = _ne_lrc_rows(get("romalrc"))
    if not roma:
        return []
    lrc = _ne_lrc_rows(get("lrc"))
    if len(lrc) == len(roma) and all(abs(a[0] - b[0]) <= 1.0 for a, b in zip(lrc, roma)):
        # Row for row, where romalrc was stamped on its own (up to 0.5s off).
        return [(t, body, r) for (t, body), (_u, r) in zip(lrc, roma)
                if _rkey(r) != _rkey(body)]
    out = []
    for t, body in lrc:
        near = min(roma, key=lambda r: abs(r[0] - t))
        if abs(near[0] - t) <= 0.05 and _rkey(near[1]) != _rkey(body):
            out.append((t, body, near[1]))
    return out


def _ne_romanise(items: list[dict], pairs: list[tuple],
                 by_time: bool = True) -> None:
    """Put romanisations on the items that lack one: by text first (nearest
    in time among equal lines), else by time within 0.35s where `by_time`."""
    if not pairs:
        return
    keyed: dict = {}
    for t, body, rom in pairs:
        keyed.setdefault(_rkey(body), []).append((t, rom))
    for it in items:
        if it.get("TransliteratedText"):
            continue
        s = it.get("StartTime")
        same = keyed.get(_rkey(it.get("Text") or ""))
        if same:
            it["TransliteratedText"] = (min(same, key=lambda r: abs(r[0] - s))
                                        if s is not None else same[0])[1]
        elif by_time and s is not None:
            near = min(pairs, key=lambda r: abs(r[0] - s))
            if abs(near[0] - s) <= 0.35:
                it["TransliteratedText"] = near[2]


def _ne_writers(lrc: str) -> list[str]:
    """Songwriters from NetEase's credit lines ("作词 : ..."), which the parse
    drops."""
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
                 lambda: _or_native(_netease, tid, meta))


def _netease(tid: str, meta: dict) -> dict | None:
    """NetEase Cloud Music: the first word-level candidate that ties the best
    on title, length and byline, else the best line-level one (with
    romalrc)."""
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
        doc = _ne_doc(d, (meta or {}).get("title") or "",
                      (meta or {}).get("artist") or "")
        if not doc:
            continue
        if doc["Type"] == "Syllable" and score == top:
            _ne_borrow_roman(doc, [got.get(sid) for sid, sc in ranked
                                   if sc == top])
            return doc
        if fallback is None or (_ne_romanised(doc) and not _ne_romanised(fallback)):
            fallback = doc
    if fallback is not None:
        _ne_borrow_roman(fallback, [got.get(sid) for sid, sc in ranked
                                    if sc == top])
    return fallback


def _ne_borrow_roman(doc: dict, payloads: list) -> None:
    """Fill romanisation from sibling pressings of the same song: the
    word-timed copy often ships no romalrc while another release does."""
    items = doc.get("Lines") if doc.get("Type") == "Static" else doc.get("Content")
    for d in payloads:
        if not items or all(i.get("TransliteratedText") for i in items):
            return
        if isinstance(d, dict):
            _ne_romanise(items, _ne_roman_pairs(d), by_time=False)


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
    """Whether two line sequences are the same song, measured against the
    shorter."""
    real = min(sum(1 for x in a if x), sum(1 for x in b if x))
    return bool(real) and len(pairs) >= floor * real


COHERE_MIN = 8
COHERE_TOL = 0.5
COHERE_SHARE = 0.9


def _coherent(pairs: dict, bit: list, dit: list) -> bool:
    """Whether the matched lines agree about where they are in the song."""
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
    """base line index -> other's by text, or None if these are not one song;
    near pairs count toward the bar, filed-apart ad-libs removed first."""
    from difflib import SequenceMatcher

    apart = _filed_apart({"Content": other})
    a = [_key(_unaside(SL.line_text(i), apart)) for i in base]
    b = [_key(SL.line_text(i)) for i in other]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    pairs = {i + k: j + k
             for i, j, n in sm.get_matching_blocks() for k in range(n) if a[i + k]}
    if not pairs:
        return None
    pairs.update(_near_pairs(a, b, pairs))
    if not _shared(a, b, pairs):
        return None
    return pairs


def _filed_apart(doc) -> set:
    """The ad-libs a donor keeps out of its own line stream, by their words."""
    got = {_key(SL.syllables_text(g.get("Syllables") or []))
           for it in _items(SL.payload(doc or {}))
           for g in (it.get("Background") or []) if isinstance(g, dict)}
    got.discard("")
    return got


def _unaside(text: str, apart: set) -> str:
    """A line without the ad-libs the donor files apart (only those)."""
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


@functools.lru_cache(maxsize=8)
def _stream_blocks(ours: str, theirs: str, floor: float):
    """The matching blocks of two whole songs' letters, or None if not alike
    enough; one difflib pass per pair, shared."""
    from difflib import SequenceMatcher

    sm = SequenceMatcher(None, ours, theirs, autojunk=False)
    if sm.quick_ratio() < floor or sm.ratio() < floor:
        return None
    return tuple(sm.get_matching_blocks())


# How much further from the base line a re-cut may sit and still beat a
# pairing that shares its syllables; Ice Ice Baby's wrong one was 4s out.
OWNER_SLACK = 0.5


def _one_owner(qmap: dict, qit: list, recut: list, timed) -> tuple[dict, list]:
    """Paired lines whose donor syllables a re-cut line already took, re-cut
    too, so no syllable times two lines (LUV U NEED U's "I do", 2026-10-16) --
    where the re-cut times as many words and sits about as near the base."""
    qit = list(qit)
    while True:
        taken = {id(y) for k in qmap.values() if qit[k].get("_recut")
                 for y in ((qit[k].get("Lead") or {}).get("Syllables") or [])}
        moved = False
        for i, k in sorted(qmap.items()):
            if qit[k].get("_recut"):
                continue
            mine = (qit[k].get("Lead") or {}).get("Syllables") or []
            alt = recut[i] if i < len(recut) else None
            if not alt or not any(id(y) in taken for y in mine):
                continue
            trial = dict(qmap)
            trial[i] = len(qit)
            (n_now, far_now), (n_alt, far_alt) = (timed(qmap, qit, i),
                                                   timed(trial, qit + [alt], i))
            if not n_now or n_alt < n_now or far_alt > far_now + OWNER_SLACK:
                continue
            qit.append(alt)
            qmap = trial
            moved = True
            break
        if not moved:
            return qmap, qit


def _restream(base: list[dict], donor: list[dict], floor: float = 0.80):
    """The donor's syllables re-cut where the base breaks its lines, by
    aligning the whole song's letters; spans forced apart afterwards."""
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
    blocks = _stream_blocks(ours, theirs, floor)
    if blocks is None:
        return None
    span: dict[int, list] = {}
    for i, j, n in blocks:
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


# How far one kept line's donor offset may sit from the last one's; a re-cut
# slipping onto another repeat moves by a bar or more.
CLOCK_STEP = 1.5
# The share of a line's letters a re-cut near its place has to find.
NEAR_LIKE = 0.6
# Below this share of lines on one steady clock there is no clock to judge by
# (Have Fun: 4 of 24 -- Apple and NetEase lay the song out differently).
CLOCK_SHARE = 0.7


def _steady_run(off: dict) -> set:
    """The longest run of lines, in order, whose offsets move by CLOCK_STEP at most."""
    ks = sorted(off)
    best, prev = [1] * len(ks), [-1] * len(ks)
    for a in range(len(ks)):
        for b in range(a - 1, -1, -1):
            if abs(off[ks[a]] - off[ks[b]]) <= CLOCK_STEP and best[b] + 1 > best[a]:
                best[a], prev[a] = best[b] + 1, b
    if not ks:
        return set()
    at, run = max(range(len(ks)), key=lambda k: best[k]), set()
    while at >= 0:
        run.add(ks[at])
        at = prev[at]
    return run


def _on_clock(bit: list, dit: list, pairs, recut):
    """`recut` without the repeated lines it slipped off the donor's clock,
    those re-cut again from the syllables near where that clock puts them.
    See docs/notes lyric_sources.md, 2026-10-18 (I Can Be's outro)."""
    from collections import Counter
    from difflib import SequenceMatcher

    if not recut:
        return recut
    pairs = pairs or {}
    off = {}
    for i, j in pairs.items():
        s = SL.line_start(bit[i])
        d = SL.line_start(dit[j]) if 0 <= j < len(dit) else None
        if isinstance(s, (int, float)) and isinstance(d, (int, float)):
            off[i] = d - s
    for i, got in enumerate(recut):
        s = SL.line_start(bit[i]) if i < len(bit) else None
        if got and i not in pairs and isinstance(s, (int, float)):
            off[i] = got["StartTime"] - s
    keep = _steady_run(off)
    if len(keep) < CLOCK_SHARE * len(off):
        return recut
    said = Counter(_key(SL.line_text(x)) for x in bit)
    twice = {i for i in range(len(bit)) if said[_key(SL.line_text(bit[i]))] > 1}
    out = list(recut) + [None] * (len(bit) - len(recut))
    astray = {i for i in off if i not in pairs and i not in keep}
    apart = _filed_apart({"Content": dit})
    unsure = {}
    for i in sorted(off):
        if i in pairs:
            continue
        mine = out[i]["Lead"]["Syllables"]
        nxt = SL.line_start(bit[i + 1]) if i + 1 < len(bit) else None
        unlike = (not _relay(_unaside(SL.line_text(bit[i]), apart), mine, RECUT_LIKE)
                  or not _fits(mine, SL.line_start(bit[i]), nxt))
        # A lone outlier said once is the base's stamp wobbling, not a slip.
        lone = i not in twice and i - 1 not in astray and i + 1 not in astray
        if i in astray and not lone:
            out[i] = None
            off.pop(i)
        elif unlike:
            unsure[i] = out[i]
            out[i] = None
            off.pop(i)
    syls = [y for it in dit for y in ((it.get("Lead") or {}).get("Syllables") or [])
            if isinstance(y.get("StartTime"), (int, float))]
    owned = {id(y) for j in pairs.values() if 0 <= j < len(dit)
             for y in ((dit[j].get("Lead") or {}).get("Syllables") or [])}
    owned |= {id(y) for x in out if x for y in x["Lead"]["Syllables"]}
    kept = sorted(off)
    for i in range(len(bit)):
        b_s = SL.line_start(bit[i])
        if i in pairs or out[i] is not None or not isinstance(b_s, (int, float)):
            continue
        near = sorted(kept, key=lambda k: abs(k - i))[:6]
        if not near:
            continue
        o = sorted(off[k] for k in near)[len(near) // 2]
        nxt = SL.line_start(bit[i + 1]) if i + 1 < len(bit) else None
        b_e = _line_end(bit[i])
        b_e = b_e if isinstance(b_e, (int, float)) else (
            nxt if isinstance(nxt, (int, float)) else b_s + 6.0)
        lo, hi = b_s + o - BLEND_JUMP, b_e + o + BLEND_JUMP
        cand = [y for y in syls if lo <= y["StartTime"] <= hi and id(y) not in owned]
        ours = _key(_unaside(SL.line_text(bit[i]), apart)) or _key(SL.line_text(bit[i]))
        theirs, owner = [], []
        for k, y in enumerate(cand):
            t = _key(y.get("Text") or "")
            theirs.append(t)
            owner.extend([k] * len(t))
        if not ours or not owner:
            continue
        blocks = [b for b in SequenceMatcher(None, ours, "".join(theirs),
                                             autojunk=False).get_matching_blocks() if b[2]]
        # The line's opening has to be found, bar a short lead-in ("Ohhh").
        if sum(b[2] for b in blocks) < NEAR_LIKE * len(ours) \
                or blocks[0][0] > max(2, len(ours) // 4):
            continue
        span = [owner[j + k] for _i, j, n in blocks for k in range(n)]
        take = cand[min(span):max(span) + 1]
        if abs(take[0]["StartTime"] - (b_s + o)) > BLEND_JUMP or not _fits(
                take, b_s + o, (nxt + o) if isinstance(nxt, (int, float)) else None):
            continue
        got = "".join(_key(y.get("Text") or "") for y in take)
        if SequenceMatcher(None, ours, got, autojunk=False).ratio() < RELAY_LIKE:
            continue
        owned |= {id(y) for y in take}
        end = max(float(y.get("EndTime") or y["StartTime"]) for y in take)
        out[i] = {"Text": SL.syllables_text(take), "_recut": True,
                  "StartTime": float(take[0]["StartTime"]), "EndTime": end,
                  "Lead": {"Syllables": take, "StartTime": float(take[0]["StartTime"]),
                           "EndTime": end}}
    # A re-cut that only failed the relay stays where nothing better was found.
    for i, was in unsure.items():
        if out[i] is None and not any(id(y) in owned for y in was["Lead"]["Syllables"]):
            out[i] = was
    return out if any(o for o in out) else None


def _in_step(out: list, based: list) -> None:
    """Lines that borrowed the wrong repeat of themselves, given back to the
    base's stamp: outside the longest ascending run and on another repeat's
    timing."""
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
    """Drop pairings whose offset disagrees with their neighbours' median,
    judging only pairings that could be the wrong repeat."""
    from collections import Counter

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
    def nth(items):
        """Each line's key, which time it is said, and how many times in all."""
        seen, at = Counter(), []
        for x in items:
            k = _key(SL.line_text(x))
            seen[k] += 1
            at.append((k, seen[k]))
        return [(n, seen[k]) for k, n in at]

    a, b = nth(bit), nth(dit)
    out = dict(pairs)
    for pos, i in enumerate(keys):
        if a[i] == b[pairs[i]]:
            continue
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
# The margin grows with the clocks being compared: 0.02 apart at 0.14 is noise.
BLEND_PICK_SHARE = 0.2


def _wander(bit: list, dit: list, dmap: dict) -> float | None:
    """How much this donor's clock wanders against the base's line sync (median
    deviation of paired offsets), off the pairing alone; None with too few
    pairs."""
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
    """(shift, wander) of this donor's clock against the base's line sync, over
    the pairing and the re-stream, so a bodily shifted pressing shows."""
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
    """The blend's two donors, the one whose clock sits nearest the base's line
    sync first (by `_clock`'s shift, with a wobble guard); NetEase on a tie."""
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
    """How far each line of the finished map sits from where the lines around
    it put this donor."""
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
    """The share of a line's words that would fill on an onset nobody measured,
    or None where the donor has nothing for the line."""
    syls = (group or {}).get("Syllables") or []
    got = _relay(text, syls) if syls else None
    if not got:
        return None
    return sum(1 for y in got if y.get("Guess")) / len(got)


def _astray(bit: list, qit: list, qmap: dict, apart: set = frozenset()) -> dict:
    """The lines the first donor timed wrong, i -> (drift, guessed): over
    BLEND_JUMP from its neighbours, or over BLEND_PATCHY guessed. `apart` as
    in _unaside."""
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
    """Whether the second donor's answer for one line beats the first's: it
    must be steady itself (BLEND_STEADY) and fix the first's failure."""
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
    """Re-pair lines left unpaired on the wrong repeat with a same-text donor
    line whose time fits the surviving anchors, within `tol`."""
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
    """Where a line begins from up to three opinions: the earliest believable
    one, or the middle when all three disagree; the line sync when all are
    outliers."""
    keep = {k: v for k, v in starts.items() if k not in _outliers(starts)}
    if not keep:
        keep = {"base": starts["base"]} if "base" in starts else starts
    vals = sorted(keep.values())
    if len(vals) >= 3 and vals[-1] - vals[0] > BLEND_NEAR:
        return vals[len(vals) // 2]
    return vals[0]


def _last_end(ends: list[float]) -> float | None:
    """The line's end: the soonest anyone measured (each source pads
    differently), later pushed out to its last drawn syllable."""
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
              "netease": "NetEase", "lrclib": "LRCLIB",
              "mxm": "Musixmatch", "genius": "Genius"}


def _blended(tid: str, meta: dict, local, timing, whose: str, alone: str,
             above=None, spare=None, spare_name: str = "",
             spare_alone: str = "") -> dict | None:
    """Apple Music's (or another base's) lines with somebody else's word timing
    under them; bases from _bases, `local` offered too. No request of its
    own."""
    got = _parallel({
        "timed": lambda: timing(tid, meta),
        **({"spare": lambda: spare(tid, meta)} if spare is not None else {}),
    })
    picks = _bases(tid, meta, local, above)
    if not picks:
        return None
    base, words, origin = picks[0]
    lead, fill = in_order(base, (got["timed"], whose, alone),
                          (got.get("spare"), spare_name, spare_alone))
    out = _blend(base, words, lead[0], None, origin, lead[1], fill[0], fill[1])
    if unblended(out):
        out = None
    return stand_down(out, lead[0], base, lead[2])


def unblended(doc) -> bool:
    """Whether a blend came back as nothing but its base's own lines
    (`_alone`)."""
    for d in (doc if isinstance(doc, dict) else {}, SL.payload(doc or {})):
        alone = str(d.get("_alone") or "")
        if alone:
            return alone in BASE_FROM or alone in ("spicy", "apple")
    return False


BASE_FROM = ("bini", "lrclib", "mxm", "genius")
BASE_KEY = {"bini": "blend_base_apple", "lrclib": "blend_base_lrclib",
            "mxm": "blend_base_mxm", "genius": "blend_base_genius"}
BASE_ON = set(BASE_FROM)
BASE_SHUT: set = set()


ALL_BASES = ",".join(BASE_FROM)


def set_bases(on, shut=()) -> None:
    """Which of BASE_FROM a blend may take its lines from; `shut` ones count
    only when already in hand."""
    global BASE_ON, BASE_SHUT
    BASE_ON = {n for n in on if n in BASE_FROM}
    BASE_SHUT = {n for n in shut if n in BASE_FROM}


def bases_key() -> str:
    """BASE_ON as a stored answer remembers it. See fallback."""
    return ",".join(n for n in BASE_FROM if n in BASE_ON)


def _bases(tid: str, meta: dict, local, above) -> list:
    """The documents a blend may take its lines from, best first (Apple,
    LRCLIB, Musixmatch, Genius), from `above` or asked, stopping at a
    line-timed one."""
    above = above or {}
    on, shut = set(BASE_ON), set(BASE_SHUT)
    local = SL.payload(local) if local else None
    picks = []
    if local and "bini" in on and _words_from(local) == "Apple Music":
        picks.append((local, "Apple Music", "spicy"))
    fetchers = {"bini": from_apple, "lrclib": from_lrclib,
                "mxm": from_musixmatch, "genius": from_genius}
    for name in BASE_FROM:
        if name not in on:
            continue
        fetch = fetchers[name]
        if any(RANK.get(quality(d), 0) >= RANK["line"] for d, _w, _o in picks):
            if name not in above:
                continue
        doc = above.get(name)
        if doc is None and name not in above and name not in shut:
            doc = (fetch(tid, meta) if name != "genius"
                   else fetch(tid, meta, above=above))
        doc = SL.payload(doc) if doc else None
        if doc and name == "mxm":
            doc = _line_only(doc)
        if not doc and name == "bini":
            model = above.get("lrcmodel")
            if model is None and name not in shut:
                model = from_lrcred_model(tid, meta)
            doc = _starts_only(SL.payload(model)) if model else None
        if doc:
            picks.append((doc, BASE_WORDS.get(name, name), name))
    picks = [(d, w, o) for d, w, o in picks if d and quality(d) != "none"]
    picks.sort(key=lambda p: RANK.get(quality(p[0]), 0), reverse=True)
    return picks


def _line_only(doc):
    """A document with its word timing taken off, each line kept whole.

    For Musixmatch, whose word sync the blends are not to use: its lines and
    their starts are worth building on, its syllables are not.
    """
    if quality(doc) != "syllable":
        return doc
    out = []
    for it in _items(doc):
        text = SL.line_text(it)
        start = SL.line_start(it)
        if not text or start is None:
            continue
        syls = ((it.get("Lead") or {}).get("Syllables") or [])
        ends = [y.get("EndTime") for y in syls if isinstance(y, dict)]
        ends = [e for e in ends + [it.get("EndTime"), (it.get("Lead") or {})
                                   .get("EndTime")]
                if isinstance(e, (int, float))]
        out.append({"Text": text, "StartTime": start,
                    "EndTime": max(ends) if ends else start + 6.0})
    if not out:
        return None
    rest = {k: v for k, v in doc.items() if k not in ("Type", "Content", "Lines")}
    return {**rest, "Type": "Line", "Content": out}


def _starts_only(doc):
    """lrc.red's model sync as Apple's lines and their starts, ended as LRC is.

    The model's ends run well off; its line starts and Apple's words are good.
    """
    rows = [(SL.line_start(it), SL.line_text(it)) for it in _items(doc)]
    rows = sorted((t, x) for t, x in rows if x and isinstance(t, (int, float)))
    if not rows:
        return None
    out = []
    for i, (t, text) in enumerate(rows):
        nxt = rows[i + 1][0] if i + 1 < len(rows) else None
        out.append({"Text": text, "StartTime": t,
                    "EndTime": min(nxt, t + 10.0) if nxt is not None else t + 6.0})
    rest = {k: v for k, v in doc.items()
            if k not in ("Type", "Content", "Lines", "_by_model")}
    return {**rest, "Type": "Line", "Content": out}


def stand_down(out, donor, base, alone: str):
    """The blend, or the donor's own document where the blend was not worth it;
    shared with eval_blends.py so the rule cannot drift."""
    rank = lambda d: RANK.get(quality(d), 0) if d else 0        # noqa: E731
    if donor and other_song(donor, base):
        return out
    if donor and rank(donor) > rank(out):
        out = dict(_reworded(donor, base))
        out["_alone"] = alone
    elif donor and (_thinner(out, donor) or _shorter(out, donor)):
        out = dict(_reworded(donor, base))
        out["_alone"] = alone
    return out


BLEND_SHORT = 0.85
BLEND_SAME_WORDS = 0.85
STRAY_SHARE = 0.2
STRAY_MIN = 8
_STRAY_TOK = re.compile(r"[぀-ヿ㐀-鿿가-힯]|[^\W_]+")


def _word_pairs(doc) -> tuple[set, bool]:
    """A document's consecutive word pairs (a CJK character is a word), and
    whether it is mostly CJK."""
    words = [w.lower() for i in _items(SL.payload(doc or {}))
             for w in _STRAY_TOK.findall(SL.line_text(i) or "")]
    cjk = sum(1 for w in words if len(w) == 1 and ord(w) >= 0x3040)
    return {tuple(words[k:k + 2]) for k in range(len(words) - 1)}, 2 * cjk > len(words)


def other_song(doc, ref, native: bool = False) -> bool:
    """Whether doc carries some other song's words than ref: under STRAY_SHARE
    of word pairs shared. Never on a few words; across scripts only where ref is
    `native` (Spicy's: never romaji). See the 2026-10-22 wrong-song section of
    docs/notes/mild-lyrics/lyric_sources.md."""
    if not isinstance(doc, dict) or not isinstance(ref, dict):
        return False
    (a, a_cjk), (b, b_cjk) = _word_pairs(doc), _word_pairs(ref)
    least = min(len(a), len(b))
    return ((native or a_cjk == b_cjk) and least >= STRAY_MIN
            and len(a & b) < STRAY_SHARE * least)


def _cjk_made(name: str, doc) -> bool:
    """Whether an answer's words are QQ's, Kugou's, Kuwo's or NetEase's own."""
    if name in CJK_MAKERS:
        return True
    d = doc if isinstance(doc, dict) else {}
    return str(SL.payload(d).get("_alone") or d.get("_alone") or "") in CJK_MAKERS


def _reference(docs: dict, local):
    """The lines a CJK maker's answer is checked against: Spicy's, else a base's."""
    if _items(SL.payload(local or {})):
        return local
    return next((docs[n] for n in BASE_FROM
                 if isinstance(docs.get(n), dict) and _items(SL.payload(docs[n]))), None)


def _reworded(donor, base):
    """The donor's document re-lettered from the base wherever the base has the
    line, cut along the donor's syllables."""
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
    """_shorter on the two documents' letters only, so it can run in another
    process (see offload). Same opcodes as before."""
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
    """Whether the blend's words miss a real part of the song: the same lyric,
    with one unbroken donor stretch over BLEND_SHORT missing."""
    return offload.call(_short_of, _said(blend), _said(donor))


BLEND_THIN = 0.35


def _thinner(blend, donor) -> bool:
    """Whether the blend leaves a materially larger share of lines untimed:
    without words, or without even a start (an unsynced base the donor
    merges two lines at a time, as on Encore Dance)."""
    def share(doc, timed):
        items = _items(SL.payload(doc or {}))
        if not items:
            return 0.0
        return sum(1 for i in items if timed(i)) / len(items)
    worded = lambda i: bool((i.get("Lead") or {}).get("Syllables"))   # noqa: E731
    started = lambda i: isinstance(SL.line_start(i), (int, float))    # noqa: E731
    return any(share(donor, t) - share(blend, t) >= BLEND_THIN
               for t in (worded, started))


def from_blend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """Apple Music's lines with QQ Music's word timing."""
    return _blended(tid, meta, local, from_qq, "QQ Music", "qq", above)


def from_kublend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """The blend with Kugou underneath instead (the same data as QQ, a second
    door)."""
    return _blended(tid, meta, local, from_kugou, "Kugou", "kugou", above)


def from_neblend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """The blend with NetEase's word timings under Apple's lines."""
    return _blended(tid, meta, local, from_netease, "NetEase", "netease", above)


def from_triblend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """Apple's lines, one donor's words (NetEase, or QQ per in_order), and the
    other only for lines the first misses or misplaces (_astray)."""
    return _blended(tid, meta, local, from_netease, "NetEase", "netease",
                    above, from_qq, "QQ Music", "qq")


def from_kutriblend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """The three-way blend with Kugou as the second donor instead of QQ: the
    same numbers through a door that fails separately."""
    return _blended(tid, meta, local, from_netease, "NetEase", "netease",
                    above, from_kugou, "Kugou", "kugou")


def from_kwblend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """Apple Music's lines with Kuwo's word timing: mostly QQ's numbers, another door."""
    return _blended(tid, meta, local, from_kuwo, "Kuwo", "kuwo", above)


def from_kwtriblend(tid: str, meta: dict, local=None, above=None) -> dict | None:
    """Apple's lines, NetEase's words, and Kuwo for the lines NetEase misses."""
    return _blended(tid, meta, local, from_netease, "NetEase", "netease",
                    above, from_kuwo, "Kuwo", "kuwo")


from_blend.wants_above = True
from_kublend.wants_above = True
from_neblend.wants_above = True
from_triblend.wants_above = True
from_kutriblend.wants_above = True
from_kwblend.wants_above = True
from_kwtriblend.wants_above = True


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
    """Lift a trailing ad-lib out of a line when the donor's line is a prefix
    of it and another donor line, near in time, says the leftover; else
    None."""
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
    """Whether two shouts are the same however many times written
    ("yes"/"yesyes")."""
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
    """Whether the document already sings these words across these seconds."""
    for line in out:
        for k, s, e in _spans_of(line):
            if not k or not (_kin(key, k) or key in k):
                continue
            if min(until, e) - max(at, s) > -DOUBLE_SLACK:
                return True
    return False


def _place_dark(out: list, qit: list, spoken: set) -> None:
    """A line with no time and no letter match, given the stamp of the one
    donor line left free between its lit neighbours; words stay the base's."""
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
    """The donor's ad-libs our lines have no place for, lifted onto them:
    shouts (CRIES) and echoes of the donor's own lines; bracketed ones left
    alone."""
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
            # an ad-lib may run on as a background, not stretch its host over
            # the next line
            nxt = SL.line_start(out[host + 1]) if host + 1 < len(out) else None
            reach = group["EndTime"]
            if isinstance(nxt, (int, float)):
                reach = min(reach, max(ln["EndTime"], nxt))
            ln["EndTime"] = max(ln["EndTime"], reach)


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
    """The base's own words for an ad-lib on the donor's clock: relayed whole,
    over part of the donor line, or one stamp for unlump to cut."""
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
    """Ad-libs the base writes in brackets inside a line, peeled into a backing
    group with a donor's timing (loose match); untimed ones stay."""
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
    """A document with untimed syllables left out, copied, or the same object
    when there were none."""
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
    """The documents reconciled into one (testable on fixed inputs); `ne` is
    unused but kept for the multi-opinion code paths."""
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
        """Whether line i would actually come out with words on it, not merely
        paired."""
        got = items[m[i]] if m and i in m and m[i] < len(items) else None
        syls = ((got or {}).get("Lead") or {}).get("Syllables") or []
        return bool(syls) and bool(
            _relay(_unaside(SL.line_text(bit[i]), apart), syls, _alike(got)))

    def timed(m, items, i) -> tuple[int, float]:
        """How many of line i's words its pairing times, and how far from
        the base line's own span those words sit (smaller is closer)."""
        got = items[m[i]] if m and i in m and m[i] < len(items) else None
        syls = ((got or {}).get("Lead") or {}).get("Syllables") or []
        lent = _relay(_unaside(SL.line_text(bit[i]), apart), syls,
                      _alike(got)) if syls else None
        if not lent:
            return 0, float("inf")
        b_s, b_e = SL.line_start(bit[i]), _line_end(bit[i])
        if not isinstance(b_s, (int, float)):
            return len(lent), 0.0
        far = abs(lent[0]["StartTime"] - b_s)
        if isinstance(b_e, (int, float)):
            far += abs(max(y["EndTime"] for y in lent) - b_e)
        return len(lent), far

    qpairs = (_pair(bit, qit) or {}) if qit else {}
    qmap = _timely(dict(qpairs), bit, qit) if qit else None
    astray_q = {i: j for i, j in qpairs.items() if i not in (qmap or {})}
    if qit and len(qmap or ()) < len(bit):
        recut = _on_clock(bit, qit, qmap, _restream(bit, qit))
        if recut is not None:
            qmap, extra = dict(qmap or {}), []
            for i, got in enumerate(recut):
                if not got or worded(qmap, qit, i):
                    continue
                extra.append(got)
                qmap[i] = len(qit) + len(extra) - 1
            if extra:
                qit = list(qit) + extra
                qmap, qit = _one_owner(qmap, qit, recut, timed)
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
            for i, got in enumerate(_on_clock(bit, sit, smap, _restream(bit, sit)) or []):
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
        relayed = False
        if syls:
            syls = [_slide(y, qby) for y in syls]
            if i in rhythm and not _fits(syls, start, b_nxt):
                syls = []
            else:
                used.add("spare" if i in borrowed else "qq")
                relayed = True
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
        # qby is only a measured offset where the donor's words placed this
        # line; otherwise it slid strays 5.4s on LUV U NEED U's intro.
        slid[len(out)] = qby if relayed else 0.0
        if syls:
            new["Lead"] = {"StartTime": start, "EndTime": end, "Syllables": syls}
            worded += 1
        bg = [g for g in (it.get("Background") or []) if isinstance(g, dict)]
        if bg and isinstance(b_s, (int, float)):
            bg = [_slide(g, start - b_s) for g in bg]
        # The asides are the donor's, on the donor's clock, and move with its
        # words -- by qby -- not with the base's line. Slid by the base's they
        # landed a quarter second late on "All We Needed"'s "(cold light)".
        bg += [_slide(g, qby) for g in asides]
        if bg:
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
DROP_DIR = _cache_root() / "dropped"
# A file somebody dropped is their own work, kept under its own revision so a
# change to how derived caches are stamped can never throw it away.
DROP_REV = 1
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


PICK_FILE = _cache_root() / "picks.json"


def song_pick(tid: str) -> str:
    """The source picked for this track on its Song page (Use), or '' for the walk's own pick."""
    if not tid:
        return ""
    try:
        return str(json.loads(PICK_FILE.read_text(encoding="utf-8")).get(tid) or "")
    except Exception:
        return ""


def pick_for_song(tid: str, name: str) -> None:
    """Remember `name` as this track's source; '' forgets it."""
    if not tid:
        return
    try:
        try:
            got = json.loads(PICK_FILE.read_text(encoding="utf-8"))
        except Exception:
            got = {}
        if not isinstance(got, dict):
            got = {}
        if name:
            got[tid] = name
        else:
            got.pop(tid, None)
        PICK_FILE.parent.mkdir(parents=True, exist_ok=True)
        PICK_FILE.write_text(json.dumps(got), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
UNISON_BASE = "https://unison.boidu.dev"
UNISON_CREDIT = f"Lyrics from Unison ({UNISON_BASE})"
BINI_BASE = "https://lyrics-api.binimum.org"
BINI_STORE = "https://lyrics-storage.binimum.org"
BINI_HOSTS = ("binimum.org", "lrc.red")
LRCRED_BASE = "https://lrc.red"
ISRC = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
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
    """Whether two names are written in the same kind of script."""
    here, there = _kinds(a), _kinds(b)
    return bool(here and there and here & there)


def _kinds(text: str) -> set:
    """The scripts a name is written in: cjk, hangul, latin."""
    out = set()
    for ch in text or "":
        if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff":
            out.add("cjk")
        elif "\uac00" <= ch <= "\ud7af":
            out.add("hangul")
        elif ch.isalpha() and ch.isascii():
            out.add("latin")
    return out


def _billed_apart(name: str, title: str, dur: float, want: float,
                  singer: str, artist: str) -> bool:
    """An exact title within KRC_SLACK, where the two bylines are written in
    different scripts ("TK from Ling tosite sigure" / "TK from \u51db\u3068\u3057\u3066\u6642\u96e8")."""
    a, b = _kinds(singer), _kinds(artist)
    return (bool(a and b) and a != b and bool(_norm(title))
            and _norm(name) == _norm(title) and want > 0 and dur > 0
            and _near(dur, want, KRC_SLACK))


def _same_artist(theirs: str, ours: str) -> tuple[bool, bool]:
    """(the lead is the same person, anybody is), by name; both True where
    either side has no credit."""
    a, b = _who(theirs), _who(ours)
    if not a or not b:
        return True, True
    return a[0] == b[0], bool(set(a) & set(b))


ALT_CUT = re.compile(
    r"\b(live|acoustic|cover|remix|instrumental|karaoke|nightcore|demo"
    r"|tribute|rehearsal|session|mashup|parody|sped[\s-]?up|slowed"
    r"|bootleg|re-?work|flip|vip)\b", re.I)


def _cut_words(text: str) -> set[str]:
    r"""The version markers a title carries, camel case split apart first."""
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


_TAG_TAIL = re.compile(r"\s+[-–—~～/|]\s.*$|\s+(?:feat|ft|featuring)\.?\s.*$", re.I)


def _tagged(longer: str, shorter: str) -> bool:
    """Whether `longer` is `shorter` plus a tag: "Stronger (Radio Edit)", "Song - From X".

    Bare extra words are another song ("LOST IN THE ECHO" is not "Lost", 2026-10-24).
    Where the extra holds no Latin letters or digits (感電 and its kana), containment is enough."""
    s, whole = _norm(shorter), _norm(longer)
    if len(s) < 4 or s not in whole:
        return False
    core = lambda t: _norm(_TAG_TAIL.sub("", BRACKETED.sub("", t)))
    if core(longer) == core(shorter):
        return True
    return not re.search(r"[a-z0-9]", whole.replace(s, "", 1))


def _same_song(theirs: str, ours: str) -> bool:
    """Whether two titles name the same song, allowing a longer one unless its
    extra words mark another recording (ALT_CUT)."""
    a, b = _norm(theirs), _norm(ours)
    if not a or not b:
        return False
    if not _same_cut(theirs, ours):
        return False
    if a == b or _tagged(theirs, ours) or _tagged(ours, theirs):
        return True
    # A short title with a tag, equal once the tag is gone: 新時代 (ウタ from …).
    return b == _norm(BRACKETED.sub("", theirs)) or a == _norm(BRACKETED.sub("", ours))


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
    """One Unison record as a document, with its submitter named on it."""
    doc = _written(rec.get("lyrics"), str(rec.get("format") or ""))
    if doc is None:
        return None
    doc.update(_people_of(rec))
    return doc


def _people_of(row: dict):
    """A Unison record's submitter in a document's fields; `keyId` as a
    prefixed `_maker_id`."""
    who = (row or {}).get("submitter")
    name = (str(who.get("displayName") or who.get("name") or "").strip()
            if isinstance(who, dict) else str(who or "").strip())
    if not name:
        return {}
    out = {"_maker": name}
    if isinstance(who, dict):
        uid = str(who.get("keyId") or "").strip()
        if uid:
            out["_maker_id"] = "unison:" + uid
        face = who.get("avatarUrl")
        if isinstance(face, str) and face.strip():
            out["_maker_avatar"] = face.strip()
    return out


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
    """Unison, the Better Lyrics community's database: search hits must clear a
    duration check and its vote hint; direct hits get the duration check."""
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
APPLE_CATALOGUE = "https://amp-api.music.apple.com/v1/catalog"

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


ISRC_HOME = {"JP": "jp", "KR": "kr", "TW": "tw", "HK": "hk"}


def native_names(meta: dict) -> tuple[str, str] | None:
    """(title, artist) as the recording's home storefront writes them, where
    Spotify gave them translated or romanised ("New Genesis" for 新時代)."""
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title or _native_stores(title, artist):
        return None
    return _once(("native", _norm(title), _norm(artist),
                  round(float(meta.get("length") or 0))),
                 lambda: _native_names(meta, title, artist))


def _native_names(meta: dict, title: str, artist: str) -> tuple[str, str] | None:
    want = float(meta.get("length") or 0)
    for code in apple_song(meta).get("isrcs", [])[:2]:
        store = ISRC_HOME.get(code[:2])
        if not store:
            continue
        got = _amp(_apple_token(), f"songs?filter[isrc]={urllib.parse.quote(code)}", store)
        rows = [r.get("attributes") or {} for r in (got or {}).get("data") or []
                if isinstance(r, dict)]
        rows = [at for at in rows if at.get("name") and _near(
            float(at.get("durationInMillis") or 0) / 1000.0, want)]
        if not rows:
            continue
        at = min(rows, key=lambda at: abs(float(at.get("durationInMillis") or 0) / 1000.0 - want))
        named = (str(at["name"]), str(at.get("artistName") or artist))
        if (_norm(named[0]), _norm(named[1])) != (_norm(title), _norm(artist)):
            return named
    return None


def _or_native(fn, tid: str, meta: dict):
    """fn's answer, else its answer under native_names."""
    got = fn(tid, meta)
    if got:
        return got
    named = native_names(meta)
    return fn(tid, {**meta, "title": named[0], "artist": named[1]}) if named else None


APPLE_TOKEN_FILE = _cache_root() / "apple-token.json"
_APPLE_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
_apple_lock = threading.Lock()


def _plain_page(url: str) -> str:
    """A plain browser-like fetch of a page or bundle, gzip included (not
    _get)."""
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
    """The music.apple.com web player's catalogue token, read from its bundle,
    checked once and cached until it expires, under a lock."""
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
    """One Apple catalogue request, or None; `store` names another storefront
    (see NATIVE_STORE)."""
    if not token:
        return None
    where = f"{APPLE_CATALOGUE}/{store}" if store else APPLE_AMP
    req = urllib.request.Request(
        f"{where}/{path}",
        headers={"Authorization": "Bearer " + token,
                 "Origin": "https://music.apple.com",
                 "Referer": "https://music.apple.com/",
                 "User-Agent": APPLE_UA})
    if _hushed(req.full_url):
        _blamed("asked to wait")
        return None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        _hush_from(req.full_url, e)
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
    """One artwork url filled in from Apple's template."""
    url = str((art or {}).get("url") or "")
    if not url:
        return ""
    side = str(int(max(64, min(3000, size))))
    return (url.replace("{w}", side).replace("{h}", side)
               .replace("{c}", "bb").replace("{f}", "jpg"))


def apple_song(meta: dict) -> dict:
    """What Apple Music has for this track, asked once: matching ISRCs best
    first, songwriters, and the card (cover, album, rating)."""
    title = (meta.get("title") or "").strip()
    artist = (meta.get("artist") or "").strip()
    if not title:
        return {"isrcs": [], "writers": [], "card": {}}
    return _once(("apple", _norm(title), _norm(artist),
                  round(float(meta.get("length") or 0)), _album_of(meta.get("album") or "")),
                 lambda: _apple_song(meta, title, artist))


def _apple_search(token: str, term: str, store: str) -> list:
    """One storefront's answer to one search, as its rows' attributes."""
    q = _qs(term=term, types="songs", limit=10, extend="isrc") + "&include[songs]=artists"
    got = _amp(token, f"search?{q}", store)
    if got is None:
        got = _amp(_apple_token(force=True), f"search?{q}", store)
    rows = (((got or {}).get("results") or {}).get("songs") or {}).get("data") or []
    out = []
    for row in (rows if isinstance(rows, list) else []):
        at = dict((row or {}).get("attributes") or {})
        # each credited artist on its own: "Jennifer Lopez & David Guetta" is two, "Simon & Garfunkel" one
        rel = ((((row or {}).get("relationships") or {}).get("artists") or {}).get("data")) or []
        at["_artists"] = [str((a.get("attributes") or {}).get("name") or "") for a in rel
                          if isinstance(a, dict) and (a.get("attributes") or {}).get("name")]
        out.append(at)
    return out


def _apple_song(meta: dict, title: str, artist: str) -> dict:
    token = _apple_token()
    term = f"{artist} {title}".strip()
    reads = [("", _apple_search(token, term, ""))]
    for store in _native_stores(title, artist):
        rows = _apple_search(token, term, store)
        if rows:
            reads.append((store, rows))

    want = float(meta.get("length") or 0)
    hits, loose = _ranked(reads, title, artist, want)
    isrcs, writers = [], []
    for _score, at, _rank in hits:
        code = str(at.get("isrc") or "").strip().upper()
        if code and code not in isrcs:
            isrcs.append(code)
        if not writers:
            writers = apple_names(at.get("composerName") or "")
    # the card from the plain title where a read has one; see lyric_sources.md, 2026-10-25
    hits, loose = _ranked(_untagged(reads, title), title, artist, want)
    return {"isrcs": isrcs, "writers": writers,
            "card": _apple_card(_cover_cut(hits or loose, meta.get("album") or "", title), meta)}


def _untagged(reads: list, title: str) -> list:
    """Each read's rows titled exactly as asked, where it has any."""
    plain = _norm(title)
    out = []
    for store, rows in reads:
        same = [at for at in rows if _norm(at.get("name") or "") == plain]
        out.append((store, same or rows))
    return out


def _ranked(reads: list, title: str, artist: str, want: float) -> tuple[list, list]:
    """Rows of this song within NEAR of the length, best first, and the rest."""
    hits, loose = [], []
    named, billed = {}, {}
    for which, (_store, rows) in enumerate(reads):
        for rank, at in enumerate(rows):
            secs = float(at.get("durationInMillis") or 0) / 1000.0
            code = str(at.get("isrc") or "").strip().upper()
            said = _same_song(at.get("name") or "", title)
            lead, anyone = _same_artist(at.get("artistName") or "", artist)
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
    return hits, loose


def _confirmed(named: dict, billed: dict, want: float) -> list:
    """Recordings both storefronts agree about by ISRC, title, artist and
    duration spread across the two writings."""
    both = [(code, at) for code, at in named.items() if code in billed]
    if not both:
        return []
    def gap(at):
        secs = float(at.get("durationInMillis") or 0) / 1000.0
        return abs(secs - want) if want > 0 and secs > 0 else NEAR
    both.sort(key=lambda p: gap(p[1]))
    return [(((0, 0), gap(at)), at, n) for n, (_code, at) in enumerate(both)]


def _album_of(name: str) -> str:
    """An album's name without its edition: "Hands All Over (Revised International Deluxe)"."""
    return _norm(BRACKETED.sub("", re.sub(r"\s-\s(single|ep)$", "", name or "", flags=re.I)))


def _cover_cut(rows: list, album: str = "", title: str = ""):
    """Which copy of a song the cover comes from: the album named, the untagged
    title, then the earliest release, then Apple's order."""
    if not rows:
        return None
    want, named = _album_of(album), _norm(title)
    return min(rows, key=lambda r: (r[0][0],
                                    0 if want and _album_of(r[1].get("albumName") or "") == want else 1,
                                    0 if named and _norm(r[1].get("name") or "") == named else 1,
                                    str((r[1].get("releaseDate") or "9999")),
                                    r[2]))[1]


def _apple_card(at: dict | None, meta: dict) -> dict:
    """The catalogue's description of a track for a player with none; `sure`
    says whether the match had more than a title."""
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
        "artists": list(at.get("_artists") or []),
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
    """SoundCloud's cover for this track, matched by title (also after "Artist
    - "), byline required, duration allowed to differ."""
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
    """What the catalogues know about a track: Apple Music for everything, then
    SoundCloud for the cover; {} where neither knows it."""
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
    """Apple Music's songwriter credit (the publishing names), one name each."""
    return list(apple_song(meta).get("writers") or [])


def _bini_rows(q: str) -> list:
    """One BiniLyrics lookup, as its rows."""
    got = _json(f"{BINI_BASE}/?{q}")
    rows = (got or {}).get("results") if isinstance(got, dict) else None
    return rows if isinstance(rows, list) else []


def from_bini(tid: str, meta: dict, local=None) -> dict | None:
    """BiniLyrics: Apple Music's TTML found by ISRC (from Apple's search, or
    `meta`) and by name at once, the ISRC hit preferred; same-host redirects
    only."""
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    isrc = str(meta.get("isrc") or "").strip()
    want = float(meta.get("length") or 0)
    if not isrc and not (title and (artist or want > 0)):
        return None

    def by_name():
        if isrc or not (title and artist):
            return []
        # No album: an edition's name ("Long Way Down (Deluxe)") misses
        # Apple's "Long Way Down" outright. Rows are checked by title and length.
        return _bini_rows(_qs(track=title, artist=artist,
                              duration=int(round(want)) if want > 0 else None))

    def by_isrc():
        """Every pressing's rows up to the first word-timed one, so a
        line-timed pressing nearer in duration cannot shut out word-timed
        ones."""
        codes = [isrc] if isrc else apple_isrcs(meta)
        got: list = []
        for code in codes[:3]:
            got += [r for r in _bini_rows(_qs(isrc=code)) if isinstance(r, dict)]
            if any(str(r.get("timing_type") or "").lower() == "word" for r in got):
                break
        return got

    got = _parallel({"isrc": by_isrc, "named": by_name})
    for which in ("isrc", "named"):
        url, said = _bini_pick(got.get(which) or [], title, want,
                               checked=which == "named")
        if not url:
            continue
        host = urllib.parse.urlsplit(url)
        if host.scheme != "https" or not any(
                (host.hostname or "") == h or (host.hostname or "").endswith("." + h)
                for h in BINI_HOSTS):
            continue
        code = host.path.rsplit("/", 1)[-1].removesuffix(".ttml").upper()
        urls = ([f"{BINI_STORE}/{code}.ttml"] if ISRC.match(code) else []) + [url]
        for at in urls:
            raw = _get(at, "application/xml")
            doc = parse_ttml(raw) if raw else None
            if doc is not None:
                # The row keeps Apple's own level; word timing beyond it is
                # lrc.red's model, which is that source's, not Apple's.
                if said != "word" and quality(doc) == "syllable":
                    break
                return doc
    return None


def _bini_pick(rows: list, title: str, want: float, checked: bool) -> tuple:
    """The best of one lookup's rows as (TTML URL, timing_type); `checked` rows
    (name queries) are re-checked on title and duration, ISRC rows are not."""
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
            best = (score, str(row["lyricsUrl"]),
                    str(row.get("timing_type") or "").lower())
    return best[1:] if best else ("", "")


def _lrcred_songs(meta: dict) -> list:
    """lrc.red's songs for this track, as [(byModel, TTML)], asked once.

    One /s/<ISRC>.song.json answers both lrc.red's doors: Apple's own sync
    (from_lrcred) and its model's (from_lrcred_model). Not a mirror of
    BiniLyrics; see the 2026-10-15 note in docs/notes/mild-lyrics/lyric_sources.md.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    isrc = str(meta.get("isrc") or "").strip().upper()
    return _once(("lrc.red", _norm(title), _norm(artist), isrc,
                  round(float(meta.get("length") or 0))),
                 lambda: _lrcred_fetch(meta, title, artist, isrc))


def _lrcred_fetch(meta: dict, title: str, artist: str, isrc: str) -> list:
    """Up to three pressings, stopping at the first hand-timed word sync.

    The track's or Apple's codes first; where none of them is a hand word
    sync, the ones lrc.red's own search names. Another Love: Apple files the
    album cut as GBARL1300522, which lrc.red lacks; its EP code has the words.
    """
    want = float(meta.get("length") or 0)
    out: list = []
    tried: set = set()

    def ask(codes) -> bool:
        for code in [c for c in codes if ISRC.match(c or "") and c not in tried][:3]:
            tried.add(code)
            song = _json(f"{LRCRED_BASE}/s/{code}.song.json")
            raw = song.get("source") if isinstance(song, dict) else None
            if not isinstance(raw, str) or not raw:
                continue
            model = bool(song.get("byModel"))
            out.append((model, raw))
            if not model and quality(parse_ttml(raw)) == "syllable":
                return True
        return False

    if ask([isrc] if isrc else apple_isrcs(meta)) or not (title and artist):
        return out
    got = _json(f"{LRCRED_BASE}/search.json?{_qs(q=f'{title} {artist}')}")
    hits = (got or {}).get("hits") if isinstance(got, dict) else None
    hits = [h for h in hits if isinstance(h, dict)] if isinstance(hits, list) else []
    hits = [h for h in hits if _same_song(h.get("title") or "", title)
            and _same_artist(h.get("artist") or "", artist)[1]
            and _near(h.get("duration"), want)]
    hits.sort(key=lambda h: abs(float(h.get("duration") or 0) - want))
    ask([str(h.get("isrc") or "").upper() for h in hits])
    return out


def _lrcred_best(meta: dict, model: bool) -> dict | None:
    """The best-timed of lrc.red's documents that are (or are not) its model's."""
    best = None
    for by_model, raw in _lrcred_songs(meta):
        doc = parse_ttml(raw) if by_model == model else None
        if doc is not None and (best is None or
                                RANK.get(quality(doc), 0) > RANK.get(quality(best), 0)):
            best = doc
    return best


def from_lrcred(tid: str, meta: dict, local=None) -> dict | None:
    """lrc.red's copy of Apple Music's own sync, by ISRC. Its model's are not this."""
    return _lrcred_best(meta, model=False)


def from_lrcred_model(tid: str, meta: dict, local=None) -> dict | None:
    """lrc.red's in-house model word sync (`byModel`), a source of its own."""
    doc = _lrcred_best(meta, model=True)
    return dict(doc, _by_model=True) if doc else None


def from_apple(tid: str, meta: dict, local=None) -> dict | None:
    """Apple Music's TTML: lrc.red first, then BiniLyrics, never both.

    BiniLyrics is only asked where lrc.red has no song at all: where it has
    only its model's sync, BiniLyrics links that same file. `_door` says which.
    """
    red = _door("bini", "lrc.red", lambda: from_lrcred(tid, meta))
    if red:
        return dict(red, _door="lrc.red")
    if _lrcred_songs(meta):
        return None
    bini = _door("bini", "bini", lambda: from_bini(tid, meta))
    return dict(bini, _door="BiniLyrics") if bini else None


# --------------------------------------------------------------------------
KRC_KEY = bytes((64, 71, 97, 119, 94, 50, 116, 71,
                 81, 54, 49, 45, 206, 210, 110, 105))


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
    """KRC -> timed items, plus whoever the credit lines named (same credit
    filter as NetEase)."""
    return _stamped_items(_stamped_rows(text, KRC_STAMP, relative=True, unescape=True),
                          NE_CREDIT.match)


NO_WORDS = re.compile(
    r"纯音乐|純音樂|请您?欣赏|請您?欣賞|此歌曲为没有填词|沒有填詞|无歌词|暫無歌詞|暂无歌词|"
    r"为DJ歌曲|為DJ歌曲|"
    r"^\W*instrumental(?:\s+only)?\W*$|^\W*no lyrics\W*$|"
    r"^\W+$", re.I)


def _instrumental(items: list[dict]) -> bool:
    """Whether this document is only a "no words" note (纯音乐，请欣赏, a lone ♪):
    three lines at most, one saying it."""
    if not items or len(items) > 3:
        return False
    text = " ".join(SL.line_text(i) or "" for i in items).strip()
    return bool(text) and bool(NO_WORDS.search(text))


def wordless(doc) -> bool:
    """Whether any provider's answer is only the note that there are no words."""
    return isinstance(doc, dict) and _instrumental(_items(doc))


INST_CUT = re.compile(
    r"[(\[](?:[^)\]]*\W)?(?:instrumental|inst\.?|off[\s-]?vocal)(?:\W[^)\]]*)?[)\]]"
    r"|\s[-–—]\s+(?:.*\W)?(?:instrumental|inst\.?|off[\s-]?vocal)\b",
    re.I)


def instrumental_cut(title: str) -> bool:
    """Whether a track's own title marks it as an instrumental (a bracketed or
    dashed version marker); karaoke cuts are left alone."""
    return bool(INST_CUT.search(FEAT_BRACKET.sub("", title or "")))


def _krc_head(items: list[dict], title: str, artist: str) -> list[dict]:
    """The lyrics with Kugou's own "artist - title" card taken off the front."""
    while items:
        got = _norm(SL.line_text(items[0]))
        if got and got in (_norm(f"{artist}{title}"), _norm(f"{title}{artist}")):
            items = items[1:]
            continue
        break
    return items


SECTION_HEAD = re.compile(
    r"^\s*[\[［【(（<]\s*(?:verse|chorus|pre-?chorus|post-?chorus|bridge|intro"
    r"|outro|hook|drop|refrain|interlude|break(?:down)?|build-?up|instrumental"
    r"|solo|rap|skit|副歌|主歌|间奏|前奏|尾奏|桥段|说唱|念白)\b[^\]］】)）>]{0,40}"
    r"[\]］】)）>]\s*$"
    r"|^\s*(?:verse|chorus|pre-?chorus|post-?chorus|bridge|intro|outro|hook"
    r"|refrain|interlude|副歌|主歌|间奏|前奏|尾奏)(?:\s*\d+)?\s*[:：]?\s*$", re.I)
EDGE_CREDIT = re.compile(
    r"^\s*[一-鿿]{1,6}\s*[:：]\s*\S|^\s*(?:OP|SP|ISRC)\s*[:：]"
    r"|未经.{0,24}许可|著作权|版权所有|版权声明|不得.{0,12}(?:翻唱|翻录|使用)"
    r"|TME享有|本歌曲|本作品", re.I)
MACHINE_MADE = re.compile(r"TME\s*AI|AI\s*技术生成", re.I)   # "本字幕由TME AI技术生成": heard, not written
EDGE_REACH = 8
SCRIPT_OF = (("ko", re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")),
             ("ja", re.compile(r"[぀-ヿㇰ-ㇿｦ-ﾟ]")),
             ("zh", re.compile(r"[㐀-䶿一-鿿豈-﫿]")),
             ("latin", re.compile(r"[^\W\d_]")))
SUNG_UNIT = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏぀-ヿㇰ-ㇿｦ-ﾟ㐀-䶿一-鿿豈-﫿]|[A-Za-zÀ-ɏ']+")
SQUEEZED = 0.06


def _script(text: str) -> str:
    """The writing a line is in: ko, ja, zh, latin, or "" for none."""
    for name, pat in SCRIPT_OF:
        if pat.search(text):
            return name
    return ""


def _squeezed(items: list[dict], i: int) -> bool:
    """Whether line i goes by faster than anybody sings, under SQUEEZED a
    syllable -- or, line-timed, shares its stamp with the line before it."""
    it = items[i]
    syls = [y for y in ((it.get("Lead") or {}).get("Syllables") or [])
            if isinstance(y.get("StartTime"), (int, float))
            and isinstance(y.get("EndTime"), (int, float))]
    at = it.get("StartTime")
    if syls:
        span = max(y["EndTime"] for y in syls) - min(y["StartTime"] for y in syls)
    elif isinstance(at, (int, float)):
        was = items[i - 1].get("StartTime") if i else None
        if isinstance(was, (int, float)) and abs(was - at) < 0.01:
            return True
        later = [n["StartTime"] for n in items[i + 1:]
                 if isinstance(n.get("StartTime"), (int, float)) and n["StartTime"] > at]
        end = later[0] if later else it.get("EndTime")
        if not isinstance(end, (int, float)):
            return False
        span = end - at
    else:
        return False
    n = max(len(syls), len(SUNG_UNIT.findall(SL.line_text(it) or "")))
    return n >= 2 and span / n < SQUEEZED


def _translations(items: list[dict]) -> set:
    """Indexes of translation lines filed between the sung ones, if this
    document has them. See the 2026-10-17 section of lyric_sources.md."""
    said = [_script(SL.line_text(it) or "") for it in items]
    turns = [i for i in range(1, len(items))
             if said[i] and said[i - 1] and said[i] != said[i - 1]]
    fast = [i for i in turns if _squeezed(items, i)]
    if len(fast) < 3:
        return set()
    into = collections.Counter(said[i] for i in fast).most_common(1)[0][0]
    sung = collections.Counter(said[i - 1] for i in fast).most_common(1)[0][0]
    pairs = {i for i in turns if said[i] == into and said[i - 1] == sung}
    if len(pairs & set(fast)) < 3 or len(pairs & set(fast)) * 4 < len(pairs):
        return set()
    return pairs


def _furniture(items: list[dict], title: str, artist: str) -> list[dict]:
    """Kugou/NetEase/QQ lines nobody sings, taken out: the "title - artist"
    card at the top, credit runs at either edge, section headers, and
    translations filed as lines of their own. A TME AI transcription is all
    taken out: on instrumentals it hears "啦啦啦" and "The yeah"."""
    def text(it):
        return (SL.line_text(it) or "").strip()

    if any(MACHINE_MADE.search(text(it)) for it in items[:EDGE_REACH]):
        return []

    def card(t):
        for name in {title, BRACKETED.sub("", title)}:
            if _norm(t) in (_norm(f"{artist}{name}"), _norm(f"{name}{artist}")):
                return True
        head, sep, tail = t.rpartition(" - ")
        # An exact title stands without the byline: Kugou bills TK from
        # 凛として時雨 as "TK from 凛冽时雨", which no name rule ties to ours.
        return bool(sep) and any(
            _who(b) and _same_song(a, title) and (
                _same_artist(b, artist)[1] or _norm(a) == _norm(title))
            for a, b in ((head, tail), (tail, head)))

    def credit(t):
        return bool(NE_CREDIT.match(t) or EDGE_CREDIT.search(t))

    items = [it for it in items if not SECTION_HEAD.match(text(it))]
    dropped = _translations(items)
    items = [it for i, it in enumerate(items) if i not in dropped]
    lo = 0
    while lo < min(len(items), EDGE_REACH) and (
            credit(text(items[lo])) or (title and card(text(items[lo])))):
        lo += 1
    hi = len(items)
    while hi > max(lo, len(items) - EDGE_REACH) and credit(text(items[hi - 1])):
        hi -= 1
    return items[lo:hi]


def _kugou_hits(title: str, artist: str, want: float) -> list[tuple]:
    """(hash, ms) for Kugou recordings that look like this one: duration, title
    from "artist - title", and a shared artist, lead preferred."""
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
        any_of = any_of or _billed_apart(name, title, dur, want, singer, artist)
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
                 lambda: _or_native(_kugou, tid, meta))


def _kugou(tid: str, meta: dict) -> dict | None:
    """Kugou via KRC, three requests deep, stopping at the first release that
    answers."""
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
            items = _furniture(_krc_head(items, title, artist), title, artist)
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
    """Every fixed DES permutation, precomputed per byte:
    sp (S-boxes with P applied), exp (expansion), ipl/ipr (initial permutation
    halves)."""
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
    """DES's round function, read out of _qrc_tables (only QRC_SBOX's two typos
    are QQ's)."""
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
    """QRC -> timed items and whoever its credit lines named (word before
    stamp, times from the song)."""
    return _stamped_items(
        _stamped_rows(text, QRC_STAMP, before=True),
        lambda body: bool(QRC_TAIL.match(body) or NE_CREDIT.match(body)
                          or QQ_CREDIT.match(body)))


def _qq_hits(title: str, artist: str, want: float) -> list[tuple]:
    """(id, QQ's own name and byline) for its likeliest copies via the older
    anonymous search, checked on title, byline and length."""
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
        any_of = any_of or _billed_apart(name, title, dur, want, singer, artist)
        if not (_same_song(name, title) and _near(dur, want) and any_of):
            continue
        out.append((0 if lead else 1, abs(dur - want) if want > 0 else 0.0,
                    int(row["songid"]), name, singer))
    out.sort()
    return [(sid, name, singer) for _lead, _off, sid, name, singer in out]


QQ_SAYS = re.compile(r"^\s*(.+?)\s*[:：]\s*$")


def _qq_head(items: list[dict], name: str, artist: str,
             wrote: list[str] | None = None) -> list[dict]:
    """QQ's furniture taken out: the title card recognised by shape, and
    speaker labels naming someone credited (byline or `wrote`)."""
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
    items = _furniture(_qq_head(items, name, artist, wrote), name, artist)
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
KUWO_SEARCH = "https://search.kuwo.cn/r.s"
KUWO_LYRIC = "https://newlyric.kuwo.cn/newlyric.lrc"
KUWO_KEY = b"yeelion"
KUWO_TRIES = 3
KUWO_RID = re.compile(r"MUSIC_\d+")
KUWO_LINE = re.compile(r"^\[(\d+):(\d+)(?:\.(\d+))?\]")
KUWO_TOK = re.compile(r"<(-?\d+),(-?\d+)>([^<]*)")
KUWO_CUT = re.compile(r"伴奏|片段|现场|翻唱|铃声|DJ版|试听")
KUWO_NOTE = re.compile(r"歌词翻译由.{0,24}提供")


def from_kuwo(tid: str, meta: dict, local=None) -> dict | None:
    """Kuwo, asked once per track however many callers want it."""
    return _once(("kuwo", tid, _norm(meta.get("title") or ""),
                  _norm(meta.get("artist") or ""), round(float(meta.get("length") or 0))),
                 lambda: _or_native(_kuwo, tid, meta))


def _kuwo(tid: str, meta: dict) -> dict | None:
    """Kuwo, by way of its LRCX; a word-timed copy beats a line or plain one.

    Mostly QQ's own numbers, through a door that fails apart from QQ's; see
    the 2026-10-13 Kuwo section of docs/notes/mild-lyrics/lyric_sources.md.
    """
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title:
        return None
    want = float(meta.get("length") or 0)
    fallback = None
    for rid, name, singer in _kuwo_hits(title, artist, want)[:KUWO_TRIES]:
        text = _kuwo_text(rid)
        doc = _kuwo_doc(text, name or title, singer or artist) if text else None
        if doc and doc["Type"] == "Syllable":
            return doc
        fallback = fallback or doc
    return fallback


def _kuwo_hits(title: str, artist: str, want: float) -> list[tuple]:
    """(rid, Kuwo's title, byline) for its likeliest copies, checked as _qq_hits does.

    Kuwo also marks other cuts in Chinese (伴奏, 片段, 现场), which ALT_CUT does not read.
    """
    q = urllib.parse.quote(f"{title} {artist}".strip())
    # The client's whole set: without it the studio cut can drop out of the top ten.
    got = _json(f"{KUWO_SEARCH}?all={q}&ft=music&rformat=json&encoding=utf8&rn=10&pn=0"
                "&client=kt&ver=kwplayer_ar_9.2.2.1&vipver=1&show_copyright_off=1"
                "&newver=1&cluster=0&strategy=2012&vermerge=1&mobi=1&issubtitle=1")
    out = []
    for row in (got or {}).get("abslist") or []:
        if not isinstance(row, dict) or not KUWO_RID.fullmatch(str(row.get("MUSICRID") or "")):
            continue
        name = html.unescape(str(row.get("SONGNAME") or ""))
        singer = html.unescape(str(row.get("ARTIST") or ""))
        try:
            dur = float(row.get("DURATION") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        if KUWO_CUT.search(name) and not KUWO_CUT.search(title):
            continue
        lead, any_of = _same_artist(singer, artist)
        any_of = any_of or _billed_apart(name, title, dur, want, singer, artist)
        if not (_same_song(name, title) and _near(dur, want) and any_of):
            continue
        # An exact title and no extra names before a nearer length: Kuwo files
        # the 194s Justin Bieber remix as plain "bad guy" too; the album cut is 192s.
        extra = bool(set(_who(singer)) - set(_who(artist))) if _who(artist) else False
        out.append((0 if lead else 1, 0 if _norm(name) == _norm(title) else 1, extra,
                    abs(dur - want) if want > 0 else 0.0, str(row["MUSICRID"]), name, singer))
    out.sort()
    return [(rid, name, singer) for *_rank, rid, name, singer in out]


def _kuwo_xor(raw: bytes) -> bytes:
    return bytes(b ^ KUWO_KEY[i % len(KUWO_KEY)] for i, b in enumerate(raw))


def _kuwo_text(rid: str) -> str:
    """The lyric filed against one recording, decoded; "" where there is none.

    Asked for as LRCX. The body is zlib, then base64 and XOR, whether the
    answer is word-timed or not.
    """
    import base64
    import zlib

    ask = f"user=12345,web,web,web&requester=localhost&req=1&rid={rid}&lrcx=1"
    raw = _get(f"{KUWO_LYRIC}?{base64.b64encode(_kuwo_xor(ask.encode())).decode()}")
    head, _, body = (raw or b"").partition(b"\r\n\r\n")
    if not body or not head.startswith(b"tp=content"):
        return ""
    try:
        text = zlib.decompress(body)
        if not text.lstrip().startswith(b"["):
            text = _kuwo_xor(base64.b64decode(text))
        return text.decode("gb18030", "replace")
    except Exception:                                    # noqa: BLE001
        return ""


def _kuwo_krc(text: str) -> str:
    """LRCX as KRC: `<a,b>` decoded with the [kuwo:] key, translation lines dropped.

    k = the key read as octal; offset = |a+b| / 2(k // 10), length = |a-b| / 2(k % 10).
    A translation line is all `<0,0>`, stamped where the next line starts.
    """
    m = re.search(r"\[kuwo:(\d+)\]", text)
    try:
        k1, k2 = divmod(int(m.group(1), 8), 10) if m else (0, 0)
    except ValueError:
        return ""
    if not (k1 and k2):
        return ""
    out = []
    for raw in text.splitlines():
        m = KUWO_LINE.match(raw)
        toks = KUWO_TOK.findall(raw[m.end():]) if m else []
        if not toks or all(a == "0" and b == "0" for a, b, _w in toks):
            continue
        at = ((int(m.group(1)) * 60 + int(m.group(2))) * 1000
              + int((m.group(3) or "0").ljust(3, "0")[:3]))
        syls = [(abs(int(a) + int(b)) // (2 * k1), abs(int(a) - int(b)) // (2 * k2), w)
                for a, b, w in toks]
        out.append(f"[{at},{max(o + d for o, d, _w in syls)}]"
                   + "".join(f"<{o},{d},0>{w}" for o, d, w in syls))
    return "\n".join(out)


def _kuwo_doc(text: str, name: str, artist: str) -> dict | None:
    """One Kuwo lyric as a document: word-timed from LRCX, else line or plain LRC."""
    krc = _kuwo_krc(text) if KUWO_TOK.search(text) else ""
    if krc:
        items, wrote = _krc_items(krc)
        items = _furniture(_qq_head(items, name, artist, wrote), name, artist)
        if not items or _instrumental(items):
            return None
        doc = {"Type": "Syllable", "Content": _destamp(items),
               "HasTransliterations": False}
        if wrote:
            doc["SongWriters"] = wrote
        return doc
    doc = parse_lrc("\n".join(l for l in text.splitlines() if not KUWO_NOTE.search(l)))
    if not doc:
        return None
    key = "Lines" if doc["Type"] == "Static" else "Content"
    doc[key] = _furniture(_qq_head(doc[key], name, artist), name, artist)
    if not doc[key] or _instrumental(doc[key]):
        return None
    return doc


# --------------------------------------------------------------------------
MXM_BASE ="https://apic-appmobile.musixmatch.com/ws/1.1/"
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
MXM_HAS = ("has_richsync", "has_subtitles", "has_lyrics")
MXM_SID = re.compile(r"[A-Za-z0-9]{22}")
MXM_HEX = re.compile(r"[0-9a-f]{22}")


def _mxm_get(path: str, **kw):
    """One call at Musixmatch's door, as the parsed `message`, or None.

    Everything here answers HTTP 200 and puts the real answer in the
    envelope's own header, so the status that matters is the inner one and
    the caller is the one that has to read it.
    """
    kw.setdefault("app_id", MXM_APP)
    kw.setdefault("format", "json")
    url = MXM_BASE + path + "?" + _qs(**kw)
    if _hushed(url):
        _blamed("asked to wait")
        return None
    req = urllib.request.Request(url, headers=MXM_HEAD)
    wait = _patience(url)
    with _gate(url):
        try:
            with urllib.request.urlopen(req, timeout=wait) as r:
                got = json.loads(r.read())
        except Exception as e:                           # noqa: BLE001
            _hush_from(url, e)
            if not isinstance(e, urllib.error.HTTPError) or e.code not in MISSED:
                _blamed(_why(e, wait))
            return None
    msg = got.get("message") if isinstance(got, dict) else None
    return msg if isinstance(msg, dict) else None


def _mxm_code(msg) -> int:
    return int(((msg or {}).get("header") or {}).get("status_code") or 0)


def _mxm_token(force: bool = False) -> str:
    """Musixmatch's app token, kept on disk until a call comes back
    unauthorised (never Spicetify's shared one)."""
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


def _mxm_ask(tid: str, meta: dict, token: str, common: int = 0):
    """Everything Musixmatch has for one track in one macro request, richsync
    asked for by name, matched by `track_spotify_id` with the name as
    fallback."""
    dur = float(meta.get("length") or 0)
    if common:
        return _mxm_get(
            "macro.subtitles.get", usertoken=token,
            namespace="lyrics_richsynched", subtitle_format="lrc",
            optional_calls="track.richsync", richsync_compact_type="words",
            commontrack_id=common, f_subtitle_length=int(round(dur)) or None)
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
    """One richsync line's words with the ends its space entries give;
    zero-length words are left for _mxm_spans to repair."""
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
    """Musixmatch's word ends made visible: zero-length words get their line's
    median length, and gaps under MXM_GAP are closed."""
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
    """Musixmatch's flag for this recording: "explicit", "clean" or ""
    (common); second to the player's own, memoised with from_musixmatch."""
    key = _mxm_key(tid, meta)
    if key not in _MXM_EXPLICIT:
        from_musixmatch(tid, meta)
    got = _MXM_EXPLICIT.get(key)
    return "" if got is None else ("explicit" if got else "clean")


def _musixmatch(tid: str, meta: dict) -> dict | None:
    """Musixmatch's own door, ranked next to last: for songs nobody above has
    word-timed."""
    sid = tid if _mxm_sid(tid) else ""
    token = _mxm_token()
    msg = _mxm_ask(sid, meta, token) if token else None
    if _mxm_code(msg) == 401:
        token = _mxm_token(force=True)
        msg = _mxm_ask(sid, meta, token) if token else None
    calls = _mxm_calls(msg)
    if calls:
        track = _mxm_body(calls, "matcher.track.get").get("track") or {}
        if track.get("track_id") and track.get("explicit") is not None:
            with _ONCE_LOCK:
                for gone in [k for k in _MXM_EXPLICIT if k not in _ONCE]:
                    _MXM_EXPLICIT.pop(gone, None)
                _MXM_EXPLICIT[_mxm_key(tid, meta)] = int(track["explicit"] or 0)
    # A matched row with no words: a reissue's id, or the matcher's own empty
    # copy of the song. See the 2026-10-24 Musixmatch section of
    # docs/notes/mild-lyrics/lyric_sources.md.
    if sid and token and _mxm_empty(calls):
        calls = _mxm_calls(_mxm_ask("", meta, token)) or calls
    if token and _mxm_empty(calls):
        common = _mxm_search(meta, token)
        if common:
            calls = _mxm_calls(_mxm_ask("", meta, token, common)) or calls
    return _mxm_doc(calls) if calls else None


def _mxm_sid(tid: str) -> bool:
    """Whether `tid` is a Spotify id, not a local song's sha1 key (lowercase hex)."""
    return bool(MXM_SID.fullmatch(tid or "")) and not MXM_HEX.fullmatch(tid)


def _mxm_calls(msg) -> dict | None:
    body = (msg or {}).get("body")
    return body.get("macro_calls") if isinstance(body, dict) else None


def _mxm_empty(calls) -> bool:
    """Whether the macro matched a track that has no words of any kind."""
    track = _mxm_body(calls, "matcher.track.get").get("track") or {}
    return bool(track.get("track_id")) and not any(track.get(k) for k in MXM_HAS)


def _mxm_search(meta: dict, token: str) -> int:
    """The commontrack_id of the catalogue's likeliest worded copy, or 0."""
    title, artist = (meta.get("title") or "").strip(), (meta.get("artist") or "").strip()
    if not title:
        return 0
    want = float(meta.get("length") or 0)
    msg = _mxm_get("track.search", usertoken=token, q_track=title,
                   q_artist=artist or None, page_size=10)
    out = []
    for row in ((msg or {}).get("body") or {}).get("track_list") or []:
        t = (row or {}).get("track") or {}
        if not t.get("commontrack_id") or t.get("instrumental") or t.get("restricted") \
                or not any(t.get(k) for k in MXM_HAS):
            continue
        lead, any_of = _same_artist(str(t.get("artist_name") or ""), artist)
        if not (_same_song(str(t.get("track_name") or ""), title)
                and _near(t.get("track_length"), want) and (any_of or not artist)):
            continue
        out.append((0 if lead else 1, -int(t.get("has_richsync") or 0),
                    -int(t.get("has_subtitles") or 0),
                    abs(float(t.get("track_length") or 0) - want) if want > 0 else 0.0,
                    int(t["commontrack_id"])))
    return min(out)[-1] if out else 0


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
    """Songwriters from the copyright line Musixmatch returns."""
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
    """The Genius token from the player's settings file or its .bak."""
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
    """Genius' words, untimed: wins only songs nobody else has; needs the
    user's token and answers nothing without one."""
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
    """One Genius ask, filing a shut door through `genius_doc.last_error`."""
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
             "netease": ["netease"], "kugou": ["kugou"], "kuwo": ["kuwo"],
             "lrcmodel": ["lrcmodel"],
             "mxm": ["mxm"],
             "lrclib": ["lrclib"],
             "genius": ["genius"]}
BLENDS = {"blend": ("apple", "qq"), "kublend": ("apple", "kugou"),
          "neblend": ("apple", "netease"),
          "triblend": ("apple", "netease", "qq"),
          "kutriblend": ("apple", "netease", "kugou"),
          "kwblend": ("apple", "kuwo"),
          "kwtriblend": ("apple", "netease", "kuwo")}
BLEND_OF = "apple"
BLEND_KEY = {"blend": "blend_qq", "kublend": "blend_kugou",
             "neblend": "blend_netease", "triblend": "blend_ne_qq",
             "kutriblend": "blend_ne_kugou",
             "kwblend": "blend_kuwo", "kwtriblend": "blend_ne_kuwo"}
PROVIDER_SRC = {p: n for n, parts in SRC_PARTS.items() for p in parts}
PROVIDER_SRC.update({b: BLEND_OF for b in BLENDS})
WAS_SRC = {"bini": "apple", "blend": "apple",
           "kublend": "apple", "neblend": "apple", "triblend": "apple"}


SOURCES = ["spicy", "apple", "amll", "unison", "netease",
           "kugou", "qq", "kuwo", "lrcmodel", "lrclib", "mxm", "genius"]

# Settings ▸ Sources ▸ Syncs: each source's word-by-word ("@w"), line-by-line ("@l") and
# unsynced ("@u") answers, switched on or off and ordered within their sync. Quality still
# outranks the order (any word sync beats any line sync); the order decides between answers
# timed alike. Blends are not in it (the Blends tab governs blends).
SYNC_OF = {"syllable": "w", "line": "l", "static": "u"}
SRC_SYNCS = {"spicy": "wlu", "apple": "wlu", "amll": "wl", "unison": "wlu", "netease": "wlu",
             "kugou": "w", "qq": "w", "kuwo": "wu", "lrcmodel": "w", "lrclib": "lu",
             "mxm": "wlu", "genius": "u"}
SYNC_OFF: set = set()
SYNC_ORDER: list = []                 # [] = word entries, then line entries, in the sources' order


def sync_entries(order) -> list:
    """Every "source@w/l/u" entry, word entries first, each in the sources' `order`."""
    return [f"{n}@{k}" for k in "wlu" for n in order if k in SRC_SYNCS.get(n, "")]


def set_syncs(off=(), order=()) -> None:
    """Which syncs are refused, and the order within a sync ([] = the sources' order)."""
    global SYNC_OFF, SYNC_ORDER
    SYNC_OFF = {str(x) for x in off}
    SYNC_ORDER = [str(x) for x in order]


def syncs_key() -> str:
    """The sync rules as a stored answer remembers them; "" while left as they come."""
    if not SYNC_OFF and not SYNC_ORDER:
        return ""
    return ",".join(sorted(SYNC_OFF)) + "|" + ",".join(SYNC_ORDER)


def sync_entry(name: str, doc) -> str:
    """The Syncs entry a provider's answer falls under, or "" (a blend, or empty)."""
    k = SYNC_OF.get(quality(doc) if doc else "none")
    if not k or name in BLENDS:
        return ""
    return f"{PROVIDER_SRC.get(name, name)}@{k}"


def sync_off(name: str, doc) -> bool:
    """Whether this answer's source and sync are switched off in Syncs."""
    e = sync_entry(name, doc)
    return bool(e) and e in SYNC_OFF


def sync_place(name: str, rank: int, fallback: float) -> float:
    """Where an answer of this rank from this provider sits in the Syncs order (lower
    wins a tie); `fallback` (its place in the walk) while the order is left alone.
    A blend sits just above the first of its donors' word entries, as in provider_order."""
    if not SYNC_ORDER:
        return fallback
    k = {RANK["syllable"]: "w", RANK["line"]: "l", RANK["static"]: "u"}.get(rank, "")
    if name in BLENDS:
        at = [SYNC_ORDER.index(f"{p}@w") for p in BLENDS[name]
              if p != BLEND_OF and f"{p}@w" in SYNC_ORDER]
        return min(at) - 0.5 if at and k == "w" else len(SYNC_ORDER) + fallback
    e = f"{PROVIDER_SRC.get(name, name)}@{k}"
    return SYNC_ORDER.index(e) if e in SYNC_ORDER else len(SYNC_ORDER) + fallback


def ahead_of(src: str, have: str, order: list) -> list:
    """The providers ranked above `src` for a document of quality `have` (see fallback's
    `ahead`): the walk order before it, or the Syncs order when one is set."""
    plain = order[:order.index(src)] if src in order else []
    k = SYNC_OF.get(have)
    if not SYNC_ORDER or not k or f"{src}@{k}" not in SYNC_ORDER:
        return plain
    above = {e.split("@")[0] for e in SYNC_ORDER[:SYNC_ORDER.index(f"{src}@{k}")] if e.endswith("@" + k)}
    return [n for n in order if (n in BLENDS and n in plain) or
            (n not in BLENDS and PROVIDER_SRC.get(n, n) in above)]


def blend_rank(order: list, name: str) -> tuple:
    """Where a blend sits, from the ranking of its timing donor; a filler wins
    a tie and breaks what is left of it."""
    uses = [u for u in BLENDS[name] if u != BLEND_OF]
    at = [order.index(u) if u in order else len(order) for u in uses]
    return (at[0], -len(at), at[1:])


def blend_order(order: list) -> list:
    """Every blend, in the order that ranking puts them in."""
    return sorted(BLENDS, key=lambda b: blend_rank(order, b))


def provider_order(order: list, on, blend_on=None) -> list:
    """The providers in source-ranking order, each source expanded; a blend
    goes just above the highest-ranked source it borrows from. Only donors
    must be on."""
    blend_on = blend_on or (lambda _b: True)
    live = [b for b in blend_order(order)
            if blend_on(b) and all(on(u) for u in BLENDS[b] if u != BLEND_OF)]
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
    """A saved running order with sources it predates placed behind their
    SOURCES neighbours (a typed --src-order is not touched)."""
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
    """A saved order with Musixmatch moved behind LRCLIB, only where the two
    are still side by side as the old default had them."""
    out = list(order)
    for i in range(len(out) - 1):
        if out[i] == "mxm" and out[i + 1] == "lrclib":
            out[i], out[i + 1] = out[i + 1], out[i]
            break
    return out


# --------------------------------------------------------------------------
UNNAMED = "an unnamed contributor"


def shown_name(name) -> str:
    """A display name without control, format, unassigned or orphan combining
    characters; "" where nothing was left."""
    out = []
    for ch in unicodedata.normalize("NFC", str(name or "")):
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Cn", "Co", "Cs"):
            continue
        if cat.startswith("M") and not (out and not out[-1].isspace()):
            continue
        out.append(ch)
    got = re.sub(r"\s+", " ", "".join(out)).strip()
    return got if any(unicodedata.category(c)[0] in "LNSP" for c in got) else ""


def people_of(v) -> list[dict]:
    """A credit slot as people: [{name, id, url}] from an object, list or bare
    name; the id is what follows a rename."""
    if isinstance(v, (dict, str)):
        v = [v]
    out: list[dict] = []
    for one in v if isinstance(v, list) else []:
        if isinstance(one, dict):
            name = shown_name(one.get("username") or one.get("name") or "")
            uid = str(one.get("id") or "").strip()
            url = str(one.get("url") or "").strip()
            face = str(one.get("avatar") or one.get("avatarUrl") or "").strip()
        else:
            name, uid, url, face = str(one or "").strip(), "", "", ""
        if not name and not uid:
            continue
        if not name:
            name = UNNAMED
        got = {"name": name, "id": uid, "url": url}
        if face:
            got["avatar"] = face
        if not any(same_person(got, had) for had in out):
            out.append(got)
    return out


def people(v) -> list[str]:
    """The same slot as bare names, for everything that only prints them."""
    return [p["name"] for p in people_of(v) if p["name"]]


def maker_slot(doc: dict):
    """`_maker` with `_maker_id` and `_maker_avatar` put back together as one
    person."""
    name = doc.get("_maker") if isinstance(doc, dict) else None
    if not isinstance(name, str) or not name.strip():
        return name
    uid = str(doc.get("_maker_id") or "").strip()
    face = str(doc.get("_maker_avatar") or "").strip()
    if not uid and not face:
        return name
    return {"name": name, "id": uid, "avatar": face}


def credits_of(body) -> list[dict]:
    """Everybody a document credits with its timing, best claim first, across
    Spicy, amll, Unison and SyncedBy. Not songwriters."""
    doc = SL.payload(body or {})
    meta = doc.get("TTMLUploadMetadata")
    meta = meta if isinstance(meta, dict) else {}
    out: list[dict] = []
    for slot in (meta.get("Maker"), meta.get("Uploader"),
                 maker_slot(doc), doc.get("SyncedBy")):
        for one in people_of(slot):
            if not any(same_person(one, had) for had in out):
                out.append(one)
    return out


def makers_of(body) -> list[dict]:
    """Whoever made the timing, the uploader only where nobody else is named."""
    doc = SL.payload(body or {})
    meta = doc.get("TTMLUploadMetadata")
    meta = meta if isinstance(meta, dict) else {}
    out: list[dict] = []
    for slot in (meta.get("Maker"), maker_slot(doc), doc.get("SyncedBy")):
        for one in people_of(slot):
            if not any(same_person(one, had) for had in out):
                out.append(one)
    return out or people_of(meta.get("Uploader"))


def credited(body) -> list[str]:
    """The same credits as bare names, best claim first."""
    return [c["name"] for c in credits_of(body) if c["name"]]


def whose(name: str) -> str:
    """One credited name as compared: case and spacing folded, a leading @
    dropped."""
    return re.sub(r"\s+", " ", str(name or "").strip().lstrip("@")).casefold()


def match_key(who) -> str:
    """The one handle an entry is matched by: its id, or its name until then."""
    uid = _uid(who)
    if uid:
        return "#" + uid
    return whose(who.get("name") if isinstance(who, dict) else who)


def _uid(who) -> str:
    """One person's stable id, casefolded, or "" where there is none."""
    if not isinstance(who, dict):
        return ""
    return str(who.get("id") or "").strip().casefold()


def same_person(a, b) -> bool:
    """Whether two credits are one person: the ids decide where both have one,
    else the names."""
    one, two = _uid(a), _uid(b)
    if one and two:
        return one == two
    left, right = whose(a.get("name") if isinstance(a, dict) else a), \
        whose(b.get("name") if isinstance(b, dict) else b)
    return bool(left) and left == right


def answers_to(entry, credit) -> bool:
    """Whether a credit is somebody a roster entry means: an entry with an id
    means that account only; one without matches by name (see Roster.met)."""
    uid = _uid(entry)
    if uid:
        return uid == _uid(credit)
    left = whose(entry.get("name") if isinstance(entry, dict) else entry)
    right = whose(credit.get("name") if isinstance(credit, dict) else credit)
    return bool(left) and left == right


def person_list(raw) -> list[dict]:
    """One person list from any stored, typed or passed shape (comma-separated
    names); id-only entries kept."""
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
    """`want` as typed, given the ids the old list knew for the same names."""
    knew = {whose(p["name"]): p["id"] for p in person_list(had)
            if p["id"] and whose(p["name"])}
    out = []
    for one in person_list(want):
        uid = one["id"] or knew.get(whose(one["name"]), "")
        out.append({"name": one["name"], "id": uid})
    return out


class Roster:
    """Whose syncs to refuse (SKIP, by maker) and whose win a tie (PICK),
    matched by id or name; matches noted in `met`."""

    __slots__ = ("skip", "pick", "skip_people", "pick_people", "_met", "_lock")

    def __init__(self, skip=(), pick=()) -> None:
        self.skip_people = person_list(skip)
        self.pick_people = [p for p in person_list(pick)
                            if not any(same_person(p, q) for q in self.skip_people)]
        self.skip = frozenset(match_key(p) for p in self.skip_people)
        self.pick = frozenset(match_key(p) for p in self.pick_people)
        self._met: dict = {}
        self._lock = threading.Lock()

    def __bool__(self) -> bool:
        return bool(self.skip_people or self.pick_people)

    def _hit(self, key: str, people: list, credits: list) -> bool:
        """Whether any credit answers to any entry, noting each that does."""
        hit = False
        for p in people:
            for c in credits:
                if not answers_to(p, c):
                    continue
                hit = True
                if _uid(c) and c.get("name") != UNNAMED:
                    with self._lock:
                        self._met.setdefault((key, match_key(p)), {}) \
                            .setdefault(_uid(c), {"name": c.get("name") or "",
                                                  "id": str(c["id"]).strip()})
        return hit

    def blocks(self, body) -> bool:
        """Whether this document is somebody's the user has refused."""
        return bool(self.skip_people) and self._hit(
            "people_skip", self.skip_people, makers_of(body))

    def likes(self, body) -> bool:
        """Whether this document is somebody's the user asked for by name."""
        if not self.pick_people or self.blocks(body):
            return False
        return self._hit("people_pick", self.pick_people, credits_of(body))

    def fork(self) -> "Roster":
        """The same lists with a `met` of their own, for one track's walk --
        so what a walk ahead met is not mistaken for the song playing."""
        out = Roster.__new__(Roster)
        for k in ("skip", "pick", "skip_people", "pick_people"):
            setattr(out, k, getattr(self, k))
        out._met, out._lock = {}, threading.Lock()
        return out

    def met(self) -> dict:
        """Who each entry was matched to so far, with an id: {(list, entry
        key): {id: {name, id}}}. More than one id under a waiting entry means
        two accounts share the name, which the caller has to settle."""
        with self._lock:
            return {k: dict(v) for k, v in self._met.items()}

    def key(self) -> str:
        """The lists as one string of match keys for the cache key; empty for
        an empty roster. "m" marks maker-only skips."""
        if not self:
            return ""
        return ("m-" + ",".join(sorted(self.skip))
                + "+" + ",".join(sorted(self.pick)))


PROVIDERS = [("spicy", from_spicy), ("amll", from_amll), ("blend", from_blend),
             ("kublend", from_kublend), ("neblend", from_neblend),
             ("triblend", from_triblend), ("kutriblend", from_kutriblend),
             ("kwblend", from_kwblend), ("kwtriblend", from_kwtriblend),
             ("bini", from_apple), ("unison", from_unison),
             ("lrcmodel", from_lrcred_model),
             ("qq", from_qq), ("kugou", from_kugou), ("kuwo", from_kuwo),
             ("netease", from_netease),
             ("mxm", from_musixmatch),
             ("lrclib", from_lrclib),
             ("genius", from_genius)]
from_amll.credits_people = True
from_unison.credits_people = True


def _rejoin(mora: str, worded: str) -> str:
    """NetEase's mora-spaced readings re-cut into the segmenter's words where
    the two agree letter for letter."""
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


def netease_roman(meta: dict) -> list[tuple[str, str]]:
    """(lyric line, romanisation) from NetEase in song order, for a track it
    did not supply. The caller matches them to its own lines by text, then
    aligns the rest (see the window's on_ne_roman)."""
    doc = from_netease("", meta or {})
    if not doc:
        return []
    items = doc.get("Content") or doc.get("Lines") or []
    kks = SL._kakasi()
    out = []
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
        out.append((text, roman))
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
    """The stored answer for a track, or None: a miss ages from when it was
    taken (six hours), a hit from when it was last read."""
    path = _cache_path(tid)
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if rec.get("rev") != PICK_REVISION or wordless(rec.get("doc")):
        return None
    if rec.get("source") in BLENDS and unblended(rec.get("doc")):
        return None
    if rec.get("source") in CJK_SOURCES and rec.get("doc") and _translations(
            _items(SL.payload(rec["doc"]))):
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
    """Delete cache entries nothing asked for in a month (both caches), at most
    once a day unless forced. Returns how many."""
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


def _drop_path(tid: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", tid or "unknown")[:64]
    return DROP_DIR / f"{safe}.json"


def save_dropped(tid: str, doc: dict, name: str = "") -> bool:
    """Keep a file dropped on the window for this track. True if it went down."""
    if not tid or not isinstance(doc, dict):
        return False
    try:
        DROP_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"rev": DROP_REV, "at": time.time(), "name": str(name),
               "doc": doc}
        _drop_path(tid).write_text(json.dumps(rec), encoding="utf-8")
        return True
    except Exception:
        return False


def dropped_for(tid: str) -> tuple[dict, str] | None:
    """The file dropped for this track, and the name it came in under."""
    try:
        rec = json.loads(_drop_path(tid).read_text(encoding="utf-8"))
    except Exception:
        return None
    if int(rec.get("rev") or 0) != DROP_REV or not isinstance(rec.get("doc"), dict):
        return None
    return rec["doc"], str(rec.get("name") or "")


def forget_dropped(tid: str) -> bool:
    """Let go of the file dropped for this track. True if one went."""
    try:
        _drop_path(tid).unlink()
        return True
    except OSError:
        return False


def stored(tid: str):
    """The document last stored for this track, asking nobody, whatever
    providers it came from."""
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
           people: str = "", missed=(), kinds=None) -> None:
    """Remember the answer with its question: `names`, `bar`, `people`, and the
    `missed` providers."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(tid).write_text(
            json.dumps({"rev": PICK_REVISION, "at": time.time(), "source": source,
                        "names": list(names), "bar": int(bar),
                        "people": str(people or ""),
                        "missed": list(missed),
                        "kinds": dict(kinds or {}),
                        "bases": bases_key(), "syncs": syncs_key(), "doc": doc}),
            encoding="utf-8")
    except Exception:
        pass


def _settled(rec: dict, names: list) -> bool:
    """Whether a stored answer stands, or a source that failed could beat it.

    Only word timing from a source ranked above every failed one stands.
    """
    missed = [n for n in rec.get("missed") or () if n in names]
    if not missed:
        return True
    was = str(rec.get("source") or "")
    if quality(rec.get("doc")) != "syllable" or was not in names:
        return False
    return all(names.index(n) > names.index(was) for n in missed)


def refresh(tid: str) -> None:
    """Forget a track and make its sources answer afresh: Spicy asked once on
    the next walk, the _ONCE memo dropped."""
    forget(tid)
    if tid:
        _spicy_fresh.add(tid)
    with _ONCE_LOCK:
        _ONCE.clear()


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
    """Ask an upstream once however many callers want it: later callers wait on
    the first; kept ONCE_TTL; each gets a copy."""
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
    """Run {key: thunk} at once and return {key: result} (None for a raise);
    `each(key, value)` hears each as it lands."""
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
    """Jobs already running and what they have answered so far, so a round can
    be read early and stragglers collected later."""

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
    """`jobs` started at once and returned still running; the caller closes the
    pool (see _Fan.all)."""
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
    """Whether a source ranked in front of a blend's donors (Spicy by `local`)
    has the song word-timed already, so the blend is not built."""
    uses = [u for u in BLENDS.get(name, ()) if u != BLEND_OF]
    if not uses:
        return False
    at = min([names.index(u) for u in uses if u in names] or [len(names)])
    front = [got.get(n) for n in names[:at]]
    if not any(u in (ahead or ()) for u in uses) and name not in (ahead or ()):
        front.append(local)
    return any(RANK.get(quality(d), 0) >= RANK["syllable"] for d in front if d)


def _beaten_to_it(name: str, above: dict, ahead, bar: int) -> bool:
    """Whether something ranked above this costly door has come back word-timed
    (Spicy read off `bar`, unless `ahead` ranks this above it)."""
    best = max([RANK.get(quality(d), 0) for d in above.values() if d] or [0])
    if name not in (ahead or ()):
        best = max(best, bar)
    return best >= RANK["syllable"]


def _answered_already(above: dict, bar: int) -> bool:
    """Whether an untimed source (Genius) still has anything to answer for: any
    answer from the round before, or a `bar` above static, settles it."""
    if any(RANK.get(quality(d), 0) >= RANK["static"] for d in above.values() if d):
        return True
    return bar >= RANK["line"]


def _gather(known: dict, names: list, tid: str, meta: dict, local=None,
            each=None, ahead=(), bar: int = 0, rule=None) -> dict:
    """Every named provider at once, the blends and Genius in a second round
    fed the first's answers; the second round reads after ROUND_HOLD (Genius
    waits all)."""
    later = [n for n in names if getattr(known[n], "wants_above", False)]
    first = [n for n in names if n not in later]
    jobs = {n: (lambda fn=known[n], n=n:
                _asks(n, lambda: fn(tid, meta, local=local), tid))
            for n in first}
    if not later:
        return _parallel(jobs, each)
    fan = _fan(jobs, each)

    def second(who: list, got: dict) -> dict:
        """The ones of `who` still worth asking given `got`, with refused
        documents counted as absent."""
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
                      _asks(n, lambda: fn(tid, meta, local=local, above=above),
                            tid))
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
    """Best document the chain can offer, or None to keep what we have: beats
    `have` on quality (rank breaks ties, `ahead` first). `alive`, `order`,
    `people`, `note`."""
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


VIA_SRC = {"QQ Music": "qq", "Kugou": "kugou", "Kuwo": "kuwo", "NetEase": "netease"}


def made_as(name: str, doc) -> str:
    """The blend an answer really is, read off whose timing it used (a
    three-way with no filler line is the two-way); else its provider's name."""
    if name not in BLENDS or not isinstance(doc, dict):
        return name
    via = str(SL.payload(doc).get("_via") or doc.get("_via") or "")
    if " + " not in via:
        return name
    used = {VIA_SRC.get(p.strip(), p.strip()) for p in via.split(" + ")[1:]}
    return next((b for b, parts in BLENDS.items()
                 if set(parts) - {BLEND_OF} == used), name)


def _walk(tid: str, meta: dict, have: str, enabled, force: bool,
          order, ahead, local, report, people=None):
    """The walk itself, with the caller's cancel token already installed."""
    if instrumental_cut(str((meta or {}).get("title") or "")):
        return None
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

    mine, lead_name = False, ""
    if local is None:
        for name in [n for n, fn in PROVIDERS if getattr(fn, "leads", False)]:
            if enabled is not None and name not in enabled:
                continue
            got = _asks(name, lambda: known[name](tid, meta or {}), tid)
            if not isinstance(got, dict) or rule.blocks(got) or sync_off(name, got):
                continue
            local, mine, lead_name = got, True, name
            bar = max(bar, RANK.get(quality(got), 0))
            _told(report, got, name)
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
    names = [n for n in walk if (enabled is None or n in enabled)
             and not getattr(known[n], "leads", False)]
    if bar >= RANK["syllable"]:
        names = [n for n in names if n in ahead or n in (hunt or ())]
    if not names:
        return nothing()

    def beats(rank: int, name: str, doc=None) -> bool:
        """Whether this answer beats what the caller holds: on rank, or on a
        tie by a source ranked above it or a preferred maker."""
        if rank <= 0 or rank < bar:
            return False
        if rank > bar:
            return True
        return name in ahead or (doc is not None and rule.likes(doc))

    if not force:
        rec = _cached(tid)
        if rec is not None and str(rec.get("people") or "") != rule.key():
            rec = None
        if rec is not None and str(rec.get("bases", ALL_BASES)) != bases_key():
            rec = None
        if rec is not None and str(rec.get("syncs") or "") != syncs_key():
            rec = None
        if rec is not None and not _settled(rec, names):
            rec = None
        if (rec is not None and _cjk_made(str(rec.get("source") or ""), rec.get("doc"))
                and other_song(rec.get("doc"), local, native=True)):
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
        """The best answer so far, handed over as it lands and overtaken only
        on the final pick's own rules (timing first, then order)."""
        if report is None or not isinstance(doc, dict) or not _walking():
            return
        rank = RANK.get(quality(doc), 0)
        if (not beats(rank, name, doc) or rule.blocks(doc) or sync_off(name, doc)
                or not (enabled is None or made_as(name, doc) in enabled)
                or (_cjk_made(name, doc) and other_song(doc, local, native=True))):
            return
        at, liked = sync_place(name, rank, names.index(name)), rule.likes(doc)
        with said:
            was = told[0] if told else None
            if was and (rank, liked, -at) <= (was[1], was[2], -was[0]):
                return
            told[:] = [(at, rank, liked)]
        _told(report, doc, name)

    docs = _gather(known, names, tid, meta or {}, local,
                   landed if report is not None else None, ahead, bar, rule)
    ref = _reference(docs, local)
    docs = {n: d for n, d in docs.items()
            if not (_cjk_made(n, d) and other_song(d, ref, native=ref is local))}

    tied = []
    for name in names:
        doc = docs.get(name)
        if not doc:
            continue
        rank = RANK.get(quality(doc), 0)
        if (not beats(rank, name, doc) or rule.blocks(doc) or sync_off(name, doc)
                or not (enabled is None or made_as(name, doc) in enabled)):
            continue
        if not tied or rank > tied[0][2]:
            tied = [(doc, name, rank)]
        elif rank == tied[0][2]:
            tied.append((doc, name, rank))
    if SYNC_ORDER:
        tied.sort(key=lambda row: sync_place(row[1], row[2], names.index(row[1])))
    liked = [row for row in tied if rule.likes(row[0])]
    best = _fullest(_steadiest(liked or tied))
    if not _walking():
        return None
    if best:
        best = (_credited(best[0], docs, names, ahead, local, meta),
                best[1], best[2])
    faults = getattr(_WALK, "faults", None) or {}
    # What each source had (for the Song page's Sources): its sync, or why nothing.
    kinds = {n: (quality(docs[n]) if docs.get(n) else ("failed" if n in faults else "none"))
             for n in names}
    _store(tid, best[0] if best else None, best[1] if best else "", names, bar,
           rule.key(), [n for n in names if n in faults], kinds)
    return (best[0], best[1]) if best else nothing()


def _steadiest(tied: list):
    """The tied answers with a meaningfully steadier blend moved forward within
    its run of blends (see BLEND_PICK)."""
    out, k = list(tied), 0
    while k < len(out):
        end = k
        while end < len(out) and out[end][1] in BLENDS:
            end += 1
        if end == k:
            k += 1
            continue
        out[k:end] = _steadier_first(out[k:end])
        k = end
    return out


def _steadier_first(run: list) -> list:
    """One run of blends with the steadiest moved to its front, where it
    beats the first measured one by BLEND_PICK or BLEND_PICK_SHARE of it."""
    marks = [(k, SL.payload(c[0]).get("_steady")) for k, c in enumerate(run)]
    marks = [(k, v) for k, v in marks if isinstance(v, (int, float))]
    if len(marks) < 2:
        return run
    at, best = min(marks, key=lambda kv: kv[1])
    first = marks[0][1]
    if first - best <= max(BLEND_PICK, BLEND_PICK_SHARE * first):
        return run
    out = list(run)
    out.insert(0, out.pop(at))
    return out


def _fullest(tied: list):
    """Of the answers ranked equal, the first that is not missing a section
    against the fullest one (order then decides, not length)."""
    if len(tied) < 2:
        return tied[0] if tied else None
    full = max(tied, key=lambda c: len(_said(c[0])))
    return next((c for c in tied if c is full or not (
        _shorter(c[0], full[0]) and _gapped(c[0], full[0]))), full)


# How far either side of its own lines a document counts as singing, for
# _gapped: lines meet with a breath between them, and two transcriptions of
# one chorus do not split it at the same instants. 1s held Beat It's Apple
# copy whole against Musixmatch, QQ Music and Kugou; 2s also hid a section of
# one-second lines (test_fetcher's) that really was missing.
GAP_PAD = 1.0


def _spans(doc) -> list | None:
    """(start, end, letters) for each line, or None where a line has no time
    -- a static lyric says nothing about where it is silent."""
    out = []
    for i in _items(SL.payload(doc or {})):
        lead = i.get("Lead") or {}
        s, e = lead.get("StartTime", i.get("StartTime")), lead.get("EndTime", i.get("EndTime"))
        if s is None or e is None:
            return None
        out.append((float(s), float(e), len(_key(SL.line_text(i)))))
    return out


def _gapped(doc, full) -> bool:
    """Whether `doc` is silent where `full` sings a section's worth of letters,
    by letters and, where both have clocks, by time."""
    mine, theirs = _spans(doc), _spans(full)
    if not mine or not theirs:
        return True
    lost = sum(n for s, e, n in theirs
               if not any(a - GAP_PAD <= (s + e) / 2 <= b + GAP_PAD
                          for a, b, _n in mine))
    return lost > (1 - BLEND_SHORT) * sum(n for _s, _e, n in theirs)


def _credited(doc: dict, docs: dict, names: list, ahead, local, meta=None) -> dict:
    """The winning document credited to the songwriters the top-ranked source
    names, Apple's catalogue credit as the last resort. Nothing written is
    replaced."""
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
    """Drop a leading line that is a credit, not a lyric: it equals the known
    writers, or is unsingably fast and capitalised like names."""
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
    """Recover the second-voice flag from amll-ttml-db for documents with no
    flags at all; a list of bools, or None."""
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
    """A line reduced to its letters and digits, for comparing by text; cached
    (8192), since the matching loops ask the same strings repeatedly."""
    return "".join(c for c in (s or "").lower() if c.isalnum())


LIKE_LEN = 0.65
FRAGMENT = 0.95


def _fragment(one: str, other: str) -> bool:
    """Whether the shorter of two lines is a contiguous piece cut out of the
    longer."""
    from difflib import SequenceMatcher

    short, long = sorted((one, other), key=len)
    if not short:
        return False
    block = SequenceMatcher(None, short, long, autojunk=False)\
        .find_longest_match(0, len(short), 0, len(long))
    return block.size >= FRAGMENT * len(short)


def _ratio_over(a: str, b: str, bar: float, tie: bool = False):
    """SequenceMatcher(...).ratio(), or None where difflib's cheap bounds show
    it cannot clear `bar` (at it, with `tie`)."""
    from difflib import SequenceMatcher

    sm = SequenceMatcher(None, a, b, autojunk=False)
    for bound in (sm.real_quick_ratio, sm.quick_ratio):
        top = bound()
        if top < bar or (top == bar and not tie):
            return None
    return sm.ratio()


def _near_pairs(a: list[str], b: list[str], mate: dict, floor: float = 0.75) -> dict:
    """Line pairings the exact match missed, taken on length then similarity,
    only inside the window matched neighbours leave."""
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
            r = _ratio_over(key, b[j], score)
            if r is not None and r > score:
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
    """Time lines the two sides cut differently (one to several, several to
    one) as {base index: (start, end, syllables)}, inside matched windows."""
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
                r = _ratio_over(key, acc, REGROUP_LIKE)
                if r is not None and r > REGROUP_LIKE:
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
                r = _ratio_over(joined, b[j], REGROUP_LIKE, tie=True)
                if r is not None and r >= REGROUP_LIKE:
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


@functools.lru_cache(maxsize=1024)
def _letter_ops(theirs: str, ours: str, floor: float):
    """The opcodes aligning `theirs` with `ours`, or None if not alike enough
    (cheap bounds first); per pair."""
    from difflib import SequenceMatcher

    sm = SequenceMatcher(None, theirs, ours, autojunk=False)
    if sm.real_quick_ratio() < floor or sm.quick_ratio() < floor:
        return None
    if sm.ratio() < floor:
        return None
    return tuple(sm.get_opcodes())


def _recut(theirs: str, ours: str, bounds: list[int], breaks: set[int],
           floor: float = RELAY_LIKE) -> list[int] | None:
    """Cut positions in the donor's letters moved onto ours; `breaks` decides
    which side of an inserted run a cut goes."""
    ops = _letter_ops(theirs, ours, floor)
    if ops is None:
        return None
    at = [0] * (len(theirs) + 1)
    lo, hi = list(at), list(at)
    loose = None
    for tag, i1, i2, j1, j2 in ops:
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
    """Pieces of one word cut at an apostrophe put back together, where the
    word runs on."""
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


TAIL_ASIDE = re.compile(r"\s*[(（\[【][^)）\]】]{1,60}[)）\]】]\s*$")


def _relay(text: str, syls: list[dict],
           floor: float = RELAY_LIKE) -> list[dict] | None:
    """_cut_along, or failing that the line without a trailing bracket the
    donor does not sing, the bracket riding on the last word as a guess.
    See lyric_sources.md, 2026-10-24 (LUV U NEED U's "Okay (oh-ooh)")."""
    got = _cut_along(text, syls, floor)
    tail = None if got is not None else TAIL_ASIDE.search(text or "")
    if tail is None or not _key(text[:tail.start()]):
        return got
    got = _cut_along(text[:tail.start()], syls, floor)
    if not got:
        return None
    got[-1] = {**got[-1], "Text": got[-1]["Text"] + text[tail.start():].rstrip()}
    return _unlump(got)


def _cut_along(text: str, syls: list[dict],
               floor: float = RELAY_LIKE) -> list[dict] | None:
    """Re-cut `text` along `syls`' boundaries by letter alignment, keeping our
    characters; `floor` is how alike they must be (see RECUT_LIKE)."""
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
        if 0 < at < len(idx):
            lo, j = idx[at - 1] + 1, stop
            while j > lo and (text[j - 1].isspace()
                              or text[j - 1] in OPENS and text[j - 2].isspace()):
                j -= 1
            while j < stop and text[j].isspace():
                j += 1
            stop = j
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

WORD_MARKS = re.compile(r"^[&+/@$%#=€£¥]$")


def _mark_only(text) -> bool:
    """Whether a syllable is nothing but punctuation. A mask is not, and
    neither is a symbol that is really a word -- see WORD_MARKS."""
    text = SL.canon(str(text or ""))
    return (not _key(text) and not MASKED.search(text)
            and not WORD_MARKS.match(text.strip()))


SPOKEN_MARKS = set("./:")


def _spoken_mark(prev, y, nxt) -> bool:
    """Whether a punctuation syllable is said: a SPOKEN_MARKS mark welded to
    word material on both sides."""
    if nxt is None or not set(str(y.get("Text") or "").strip()) <= SPOKEN_MARKS:
        return False
    if not str(y.get("Text") or "").strip():
        return False
    before = str((prev or {}).get("Text") or "").rstrip(SL.ZWSP)
    after = str((nxt or {}).get("Text") or "").lstrip(SL.ZWSP)
    return ((bool((prev or {}).get("IsPartOfWord")) or bool(y.get("IsPartOfWord")))
            and bool(before) and before[-1].isalnum()
            and bool(after) and after[0].isalnum())


HOLE_GAP = 0.35


def close_holes(doc):
    """Close the gaps inside a line (lead and backing groups separately) onto
    the next word's start; never across lines."""
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
    """No line drawn past the next line's start where that part is slack, never
    below what it sings. Blends only; one source's overlaps are
    measurements."""
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
    """Timing taken off a punctuation-only syllable, its text riding on a
    neighbour; masked words, spoken marks and marks-only lines excepted."""
    def fixed(group):
        syls = (group or {}).get("Syllables") or []
        if len(syls) < 2 or all(_mark_only(y.get("Text")) for y in syls):
            return group
        out = []
        for i, y in enumerate(syls):
            nxt = syls[i + 1] if i + 1 < len(syls) else None
            if (not _mark_only(y.get("Text")) or not out
                    or _spoken_mark(out[-1], y, nxt)):
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
    """Every group in a document with no syllable holding two words (see
    _unlump)."""
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
    """One timing covering several words shared out among them by character
    count, within the group's span."""
    out = []
    for y in syls:
        text = y.get("Text") or ""
        parts = re.findall(r"[^\s\u200b]+[\s\u200b]*", text)
        s, e = y.get("StartTime"), y.get("EndTime")
        if len(parts) < 2 or not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            out.append(y)
            continue
        joined: list[str] = []
        opened = ""
        for piece in parts:
            if not any(c.isalnum() for c in piece) and set(piece.strip()) <= set(OPENS):
                opened += piece
            elif opened or not joined or any(c.isalnum() for c in piece):
                joined.append(opened + piece)
                opened = ""
            else:
                joined[-1] += piece
        if opened:
            if joined:
                joined[-1] += opened
            else:
                joined.append(opened)
        parts = joined
        if len(parts) < 2:
            out.append(y)
            continue
        span = max(0.0, float(e) - float(s))
        total = sum(len(p.strip()) for p in parts) or 1
        at = float(s)
        # The lump's reading is cut where its words are, when it has as many
        # words as they do. Otherwise there is no telling which letters are
        # whose, and copying the whole reading onto every word drew Spicy's
        # "esu" for 「エエ ス」 twice -- under エエ, and again under ス -- so
        # each word goes without and is read from its own text instead.
        said = str(y.get("TransliteratedText") or "").split()
        for k, piece in enumerate(parts):
            body = piece.rstrip()
            last = k == len(parts) - 1
            end = float(e) if last else at + span * len(body) / total
            made = {**y, "Text": body if last else piece,
                    "StartTime": at, "EndTime": max(end, at),
                    "IsPartOfWord": bool(y.get("IsPartOfWord")) if last
                    else piece == body}
            if "TransliteratedText" in y:
                if len(said) == len(parts):
                    made["TransliteratedText"] = said[k]
                else:
                    made.pop("TransliteratedText")
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
    """Lines that are an ad-lib filed as a line of its own: all CRIES, short,
    repeated, between full lines, not first or last."""
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


CJK_MAKERS = ("qq", "kugou", "kuwo", "netease")
CJK_SOURCES = set(CJK_MAKERS) | set(BLENDS)
_CJK_VIA = re.compile("|".join(CJK_MAKERS), re.I)


def lrc_shaped(doc) -> bool:
    """Whether NetEase, QQ Music or Kugou had a hand in this document
    (`_source`, `_alone`, `_via`); grafts are not counted."""
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
    """Whether these lines were line-synced until a donor lent them words
    (`_lifted`)."""
    for d in (doc if isinstance(doc, dict) else {}, SL.payload(doc or {})):
        if d.get("_lifted"):
            return True
    return False


def blended(doc) -> bool:
    """Whether this document's timings were stitched from more than one source
    (`_via` parts, `_lifted`); `_alone` answers no."""
    for d in (doc if isinstance(doc, dict) else {}, SL.payload(doc or {})):
        if str(d.get("_alone") or ""):
            return False
        if d.get("_lifted") or " + " in str(d.get("_via") or ""):
            return True
    return False


def needs_adlibs(doc) -> bool:
    """Whether this document's ad-libs are still written into its lyric
    (lrc_shaped or lifted)."""
    return lrc_shaped(doc) or lifted(doc)


def split_asides(doc):
    """Bracketed ad-libs inside a line made backing groups on the line's own
    timing; a lone bracket line joins the line before; runs of them stay
    unless all shouts."""
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
    """Take the brackets off what an ad-lib leaves behind, one neighbour each
    side; empty marks are dropped."""
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
    """Let a word end where the ad-lib that was finishing it went (restore the
    IsPartOfWord flag)."""
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
    """Why the masks in this document should be left alone (a clean recording,
    or somebody's own typing), or "". Never answered from silence."""
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
    """Whether a word has had letters taken out (two or more characters, not
    *wrapped* in stars)."""
    core = _bare(word)[1]
    if MASK not in core or len(core) < 2:
        return False
    lead, tail = core[:1] == MASK, core[-1:] == MASK
    return not (lead and tail and core.strip(MASK))


def _blank(mask: str) -> bool:
    """Whether a mask says nothing about the word (stars only, standing in for
    it)."""
    return not _bare(mask)[1].strip(MASK)


def _fill(mask: str, word: str) -> str:
    """`mask` with its hidden letters filled from `word`, or "" if the lengths
    or visible letters disagree."""
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
    """(where, text) for every word in one group, located by character range
    (syllable, from, to)."""
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
    """`word` cut into as many pieces as the mask it replaces, in the mask's
    own proportions."""
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
    """One line's groups as (where, holder): its lead's syllables, or the
    line's Text."""
    lead = it.get("Lead")
    syls = lead.get("Syllables") if isinstance(lead, dict) else None
    out = [(("lead", i), lead if isinstance(syls, list) and syls else it)]
    for k, g in enumerate(it.get("Background") or []):
        if isinstance(g, dict):
            out.append((("bg", i, k), g))
    return out


def _word_slots(items: list) -> list[tuple]:
    """Every word in a document in sung order, as (where, which, text)."""
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


def _slot_key(at: int, text: str) -> str:
    """One word as the aligner compares it; masked and letterless words get
    keys that never match."""
    key = _key(text)
    return key if key and not _hidden(text) else f"\x00{at}"


def _stand_in(mask: str, word: str) -> str:
    """The word a blank mask stands in for, when the donor has exactly one word
    between the same two neighbours."""
    lo, _core, hi = _bare(mask)
    said = _bare(word)[1]
    if len(said) < 2 or MASK in said or not any(c.isalnum() for c in said):
        return ""
    return lo + said + hi


def _spine(a: list, b: list) -> list:
    """Anchor pairs (i, j) for two tellings of one song: words unique on both
    sides, longest forward run (patience diff)."""
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
    """Undo a mask glued to its neighbour ("the*****") against the donor's two
    words."""
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
    """Whether a donor word could be what a damaged mask was written over (its
    letters appear in order)."""
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
    """`got` with a capital from the donor's line break taken off, only where
    every condition for that holds."""
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
    """The word the donor hides when it knows only one that fits (unanimous
    across the donor)."""
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
    """`doc` with every mask this donor can fill filled, and how many, aligned
    as one stream of words."""
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
    """A document with its masked words put back from the enabled donors in
    order; `doc` itself when there are none or clean_edit says no
    (`on_skip`)."""
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
    """Lend a word-timed document's timings to a line-timed one's lines; the
    whole result goes on the donor's clock."""
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
    # Lines still bare: the donor's stream cut at our breaks, as the blends do
    # (Hurricane's "And when you shoot", and two lines split at another word).
    held = [(s[0]["StartTime"], s[-1]["EndTime"]) for _a, _e, s in take.values()]

    def sung(got, lent):
        """Whether the relay kept to the donor's own onsets: the first two words
        on them, and under a quarter of the words cut out of another's."""
        at = {round(y["StartTime"], 3) for y in lent}
        new = [round(y["StartTime"], 3) not in at for y in got]
        return not any(new[:2]) and sum(new) < len(new) / 4
    for i, got in enumerate((_on_clock(bit, dit, mate,
                                       _restream(bit, dit) or [None] * len(bit))
                             if len(take) < len(bit) else None) or []):
        if i in take or not got:
            continue
        free = [y for y in got["Lead"]["Syllables"]
                if not any(s <= y["StartTime"] < e - 0.05 for s, e in held)]
        syls = _relay(SL.line_text(bit[i]), free, RECUT_LIKE) if free else None
        nxt = SL.line_start(bit[i + 1]) if i + 1 < len(bit) else None
        if not syls or not sung(syls, free) or not _fits(syls, SL.line_start(bit[i]), nxt) or any(min(e, syls[-1]["EndTime"]) - max(s, syls[0]["StartTime"])
                           > 0.05 for s, e in held):
            continue
        take[i] = (got["StartTime"], got["EndTime"], syls)
        held.append((syls[0]["StartTime"], syls[-1]["EndTime"]))
    # An echo written as a line of its own, where the donor files it as a
    # backing group: "(All I want)" on Conro's All I Want.
    clock = sorted((SL.line_start(bit[i]), s) for i, (s, _e, _y) in take.items()
                   if isinstance(SL.line_start(bit[i]), (int, float))
                   and isinstance(s, (int, float)))
    groups = [g["Syllables"] for it in dit for g in (it.get("Background") or [])
              if isinstance(g, dict) and g.get("Syllables")]
    for i, it in enumerate(bit):
        b_s = SL.line_start(it)
        if i in take or not clock or not isinstance(b_s, (int, float)) \
                or not BRACKETED.fullmatch(SL.line_text(it) or ""):
            continue
        want = _between(clock, b_s)
        for gs in groups:
            if not gs[0]["StartTime"] - BLEND_JUMP <= want <= gs[-1]["EndTime"]:
                continue
            syls = _relay(SL.line_text(it), gs)
            nxt = SL.line_start(bit[i + 1]) if i + 1 < len(bit) else None
            if not syls or not sung(syls, gs) or not _fits(syls, b_s, nxt) or any(min(e, syls[-1]["EndTime"]) - max(s, syls[0]["StartTime"])
                               > 0.05 for s, e in held):
                continue
            take[i] = (syls[0]["StartTime"], syls[-1]["EndTime"], syls)
            held.append((syls[0]["StartTime"], syls[-1]["EndTime"]))
            break
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
    """Give every ad-lib the side its line hangs off."""
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
    """Copy their per-line flag onto ours by text alignment, ad-libs left out
    and given their line's answer."""
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
