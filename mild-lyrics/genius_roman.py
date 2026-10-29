#!/usr/bin/env python3
"""
Fetch a human-made romanisation from Genius and line it up with timed lyrics.

Genius hosts romanised versions of Japanese/Korean/Chinese songs, usually under
the "Genius Romanizations" account or with "Romanized" in the title. Those are
written by people, so they carry the invented readings (運命 sung "sadame") that
no romaniser can infer from the text.

The hard part is not fetching them, it is deciding which Genius line corresponds
to which timed line. They come from different sources: Genius has section
headers, may repeat a chorus the timed version elides, and splits lines
differently. So we align the two sequences against our own derived reading as a
bridge, keep the ordering monotonic, and accept only matches we are confident
about -- a wrong match silently puts the wrong words on a line, which is worse
than leaving it alone.

Standalone:
    ./genius_roman.py <token> "<title>" "<artist>"
"""

from __future__ import annotations

import html
import functools
import json
import math
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

API = "https://api.genius.com"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}

ROMAN_HINT = re.compile(r"romani[sz]ed|romani[sz]ation|\bromaji\b", re.I)


def _get(url: str, headers: dict | None = None, timeout: float = 6.0) -> bytes:
    req = urllib.request.Request(url, headers={**HEADERS, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def why(exc: BaseException, limit: float = 0.0) -> str:
    """One short line for what a request to Genius did instead of answering:
    401, 403 and 429 spelled out, a URLError unwrapped to its inner reason."""
    if isinstance(exc, urllib.error.HTTPError):
        said = {401: "401, the token was refused",
                403: "403, Genius would not take the request",
                429: "429, too many requests -- wait and ask again"}
        return "HTTP " + said.get(exc.code, str(exc.code))
    inner = getattr(exc, "reason", None)
    if isinstance(inner, BaseException):
        exc, inner = inner, getattr(inner, "reason", None)
    if isinstance(exc, TimeoutError):
        return f"timed out after {limit:g}s" if limit else "timed out"
    return str(inner or exc).strip() or type(exc).__name__


def search(token: str, title: str, artist: str, timeout: float = 6.0) -> list[dict]:
    """Search Genius using both API and site web endpoints."""
    hits = []
    seen_ids = set()

    clean_title = re.sub(r"[\(\[\{].*?[\)\]\}]", "", title).strip()
    clean_artist = re.sub(r"[\(\[\{].*?[\)\]\}]", "", artist).strip()

    candidate_queries = [
        f"{title} {artist}",
        f"{clean_title} {clean_artist} Romanized",
        f"{clean_title} Romanized",
        f"{title} Genius Romanizations",
    ]

    for query_text in candidate_queries:
        if not query_text.strip():
            continue

        q = urllib.parse.quote(query_text.strip())

        if token:
            try:
                raw = _get(
                    f"{API}/search?q={q}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=timeout,
                )
                data = json.loads(raw)
                for item in data.get("response", {}).get("hits", []):
                    res = item.get("result") or {}
                    if res.get("id") and res["id"] not in seen_ids:
                        seen_ids.add(res["id"])
                        hits.append(res)
            except Exception:
                pass

        try:
            web_url = f"https://genius.com/api/search/multi?q={q}"
            raw_web = _get(web_url, timeout=timeout)
            web_data = json.loads(raw_web)

            sections = web_data.get("response", {}).get("sections", [])
            for sec in sections:
                if sec.get("type") in ("top_hit", "song"):
                    for hit in sec.get("hits", []):
                        res = hit.get("result") or {}
                        if res.get("id") and res["id"] not in seen_ids and is_song(res):
                            seen_ids.add(res["id"])
                            hits.append(res)
        except Exception:
            pass

        if any(is_romanisation(h) for h in hits):
            break

    hits.sort(key=lambda h: not is_romanisation(h))
    return hits


def is_song(hit: dict) -> bool:
    """A song entry, not an album or artist (album ids are a different id
    space)."""
    t = hit.get("_type") or hit.get("type")
    return t is None or t == "song"


def is_romanisation(hit: dict) -> bool:
    """Only accept entries that actually claim to be romanisations.

    Genius search happily returns the original Japanese version first, and
    importing that as "romaji" would be worse than useless.
    """
    if not hit:
        return False
    if (hit.get("language") or "").lower() in ("romanization", "romanized"):
        return True
    fields = (hit.get("title") or "", hit.get("full_title") or "",
              hit.get("title_with_featured") or "",
              (hit.get("primary_artist") or {}).get("name") or "")
    return any(ROMAN_HINT.search(f) for f in fields)


def _snippet(hit: dict) -> str:
    """The one lyric line Genius says it matched: the snippet line holding most
    of the marked characters."""
    for h in (hit.get("highlights") or []):
        if h.get("property") != "lyrics":
            continue
        value = str(h.get("value") or "")
        marks = [int(r.get("start", -1)) for r in (h.get("ranges") or [])
                 if isinstance(r, dict)]
        best, best_score, at = "", 0, 0
        for line in value.split("\n"):
            end = at + len(line)
            score = sum(1 for m in marks if at <= m < end)
            if score > best_score and line.strip():
                best, best_score = line.strip(), score
            at = end + 1
        if best:
            return best
        rest = [ln.strip() for ln in value.split("\n") if ln.strip()]
        if rest:
            return max(rest, key=len)
    return ""


NOT_A_SONG = re.compile(r"\b(track ?list|tracklist|album art|booklet|credits|"
                        r"liner notes|snippets?)\b", re.I)
A_VERSION = re.compile(r"\b(cover|remix|demo|live|acapp?ella|a cappella|"
                       r"instrumental|karaoke|mashup|edit|sped ?up|slowed|"
                       r"reverb|reprise|interlude|snippet|traducci|translation|"
                       r"romani[sz])", re.I)


GENIUS_ACCOUNT = re.compile(r"genius\s*(users|translations?|romani[sz]ations?|"
                            r"[a-z]+\s+translations?)|traducc|перевод", re.I)

MIN_HIT = 0.55


def _pop(hit: dict) -> float:
    """Genius's pageview count flattened to 0..1 by order of magnitude."""
    try:
        views = int(((hit.get("stats") or {}).get("pageviews")) or 0)
    except (TypeError, ValueError):
        return 0.0
    if views <= 0:
        return 0.0
    return min(1.0, math.log10(views) / 7.0)


def score_song(query: str, title: str, artist: str, line: str = "",
               pop: float = 0.0) -> tuple[float, str]:
    """How well a song answers what was typed, as a name or as a line from it;
    the better is taken, popularity settling near-identical text."""
    q = (query or "").strip()
    kq = key(q)
    named = max(similar(q, f"{title} {artist}"),
                similar(q, f"{artist} {title}"),
                similar(q, title))
    if kq and kq == key(title):
        named = 1.0
    said = 0.0
    if line:
        kl = key(line)
        said = (min(1.0, 0.55 + 0.03 * len(kq)) if kq and kq in kl
                else similar(q, line))
    return 0.75 * max(named, said) + 0.25 * pop, ("name" if named >= said
                                                  else "line")


def rank_hit(hit: dict, query: str, line: str = "") -> tuple[float, str]:
    """score_song for a Genius search result: (score, which half matched).

    Everything Genius knows about a hit and a song file does not gets applied
    here -- what kind of page it is, and who it is filed under.
    """
    title = hit.get("title") or ""
    artist = (hit.get("primary_artist") or {}).get("name") or ""
    if NOT_A_SONG.search(title):
        return 0.0, "name"
    score, why = score_song(query, title, artist, line, _pop(hit))
    if hit.get("instrumental"):
        score -= 0.15
    if GENIUS_ACCOUNT.search(artist):
        score -= 0.15
    if A_VERSION.search(title) and not A_VERSION.search(query or ""):
        score -= 0.10
    return score, why


def search_lyrics(query: str, token: str = "", limit: int = 6,
                  timeout: float = 6.0) -> list[dict]:
    """Songs that answer `query`, name or line, best first: web multi-search
    scored against the query (section order ignored), the API only as
    fallback. Never raises."""
    q = (query or "").strip()
    if len(q) < 3:
        return []
    found: dict[int, tuple[float, dict]] = {}

    def take(res: dict, hit: dict | None = None) -> None:
        sid = res.get("id")
        if not sid or not is_song(res):
            return
        line = _snippet(hit or {})
        score, why = rank_hit(res, q, line)
        was = found.get(sid)
        if was is not None:
            score = max(score, was[0])
            line = line or was[1]["line"]
        if why == "name":
            line = ""
        artist = ((res.get("primary_artist") or {}).get("name")
                  or res.get("artist_names") or "")
        found[sid] = (score, {
            "id": sid,
            "title": res.get("title") or "",
            "artist": artist,
            "full_title": res.get("full_title") or "",
            "url": res.get("url") or (("https://genius.com" + res["path"])
                                      if res.get("path") else ""),
            "art": res.get("song_art_image_thumbnail_url") or "",
            "line": line,
            "why": why,
            "score": round(score, 3),
        })

    enc = urllib.parse.quote(q)
    try:
        raw = _get(f"https://genius.com/api/search/multi?q={enc}", timeout=timeout)
        data = json.loads(raw)
        for sec in data.get("response", {}).get("sections", []):
            if sec.get("type") not in ("top_hit", "song", "lyric"):
                continue
            for hit in sec.get("hits") or []:
                take(hit.get("result") or {}, hit)
    except Exception:
        pass

    if token and len(found) < 3:
        try:
            raw = _get(f"{API}/search?q={enc}",
                       headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
            data = json.loads(raw)
            for item in data.get("response", {}).get("hits", []):
                take(item.get("result") or {})
        except Exception:
            pass

    best = sorted((r for r in found.values() if r[0] >= MIN_HIT),
                  key=lambda row: -row[0])
    return [row for _, row in best][:limit]


def _user_name(one) -> str:
    """A Genius user's display name (`name` over `login`)."""
    if not isinstance(one, dict):
        return ""
    return str(one.get("name") or one.get("login") or "").strip()


def _user_url(one) -> str:
    """A Genius user's profile page, or "".

    The user object carries it as `url`; where it does not, the login is the
    page's address. Only ever a page on genius.com -- this is put under a
    click.
    """
    if not isinstance(one, dict):
        return ""
    url = str(one.get("url") or "").strip()
    if url.startswith("https://genius.com/"):
        return url
    login = str(one.get("login") or "").strip()
    if login and re.fullmatch(r"[\w.-]+", login):
        return "https://genius.com/" + login
    return ""


def credit_links(song: dict) -> list[list[str]]:
    """The names credit_of prints, each beside its profile page.

    [[name, url], ...], the shape lyrics_gui.made_by_linked hands the credit
    row: a name with no page to go to is left out rather than linked nowhere.
    One entry per time the line prints it, in order, so a repeat links too.
    """
    if not isinstance(song, dict):
        return []
    people = [song.get("lyrics_marked_complete_by"),
              song.get("lyrics_marked_staff_approved_by")]
    seen = set()
    for one in song.get("verified_lyrics_by") or []:
        name = _user_name(one)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            people.append(one)
    out = []
    for one in people:
        name, url = _user_name(one), _user_url(one)
        if name and url:
            out.append([name, url])
    return out


def credit_of(song: dict) -> str:
    """Who vouched for this Genius lyric, as one line, or "": marked complete,
    staff approved, verified. Never the lyric state, and never `_maker`."""
    if not isinstance(song, dict):
        return ""
    bits = []
    done = _user_name(song.get("lyrics_marked_complete_by"))
    if done:
        bits.append(f"Marked complete by {done}")
    staff = _user_name(song.get("lyrics_marked_staff_approved_by"))
    if staff:
        bits.append(f"Staff approved by {staff}")
    seen, verified = set(), []
    for one in song.get("verified_lyrics_by") or []:
        name = _user_name(one)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        role = str((one or {}).get("human_readable_role_for_display") or "").strip()
        verified.append(f"{name} ({role})"
                        if role and "verified" not in role.lower() else name)
    if verified:
        bits.append("Verified by " + ", ".join(verified))
    return " · ".join(bits)


def song_of(token: str, song_id: int, timeout: float = 6.0) -> dict:
    """One song's full record from the API, or {}; asked once per document."""
    if not song_id:
        return {}
    head = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        js = json.loads(_get(f"{API}/songs/{song_id}", head,
                             timeout).decode("utf-8", "replace"))
    except Exception:
        return {}
    got = (js.get("response") or {}).get("song")
    return got if isinstance(got, dict) else {}


def lyrics_for(song_id: int, timeout: float = 6.0, markup: bool = False) -> str:
    """Plain text for a song id via the embed endpoint; `markup` keeps italic
    and bold (who sings). `lyrics_for.last_error` says why it came back
    empty."""
    lyrics_for.last_error = ""
    try:
        js = _get(f"https://genius.com/songs/{song_id}/embed", timeout=timeout).decode(
            "utf-8", "replace")
    except Exception as exc:                             # noqa: BLE001
        lyrics_for.last_error = why(exc, timeout)
        return ""
    chunk = js
    m = re.search(r"JSON\.parse\('(.*)'\)", js, re.S)
    if m:
        raw = re.sub(r"\\(.)", lambda e: {"n": "\n", "t": "\t"}.get(e.group(1), e.group(1)),
                     m.group(1))
        try:
            chunk = json.JSONDecoder().raw_decode(raw)[0]
        except Exception:
            chunk = raw
    body = re.search(r'<div[^>]+class="[^"]*rg_embed_body[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
    if body:
        chunk = body.group(1)
    chunk = re.sub(r"<br\s*/?>", "\n", chunk, flags=re.I)
    chunk = re.sub(r"</(p|div)>", "\n", chunk, flags=re.I)
    if markup:
        chunk = re.sub(r"<(?!/?(?:i|b|em|strong)\b)[^>]+>", "", chunk)
    else:
        chunk = re.sub(r"<[^>]+>", "", chunk)
    return html.unescape(chunk)


lyrics_for.last_error = ""


STYLE_TAGS = {"i": "i", "em": "i", "b": "b", "strong": "b"}


def _styled(line: str, open_now: list[str] | None = None) -> tuple[str, str]:
    """(the words, the style covering most of them): "", "i", "b", "bi" or
    "star". `open_now` threads tags left open across lines."""
    spend: dict[str, int] = {}
    if open_now is None:
        open_now = []
    plain, at = [], 0
    for m in re.finditer(r"<(/?)(\w+)[^>]*>", line):
        chunk = line[at:m.start()]
        if chunk:
            plain.append(chunk)
            spend["".join(sorted(set(open_now)))] = (
                spend.get("".join(sorted(set(open_now))), 0) + len(chunk.strip()))
        at = m.end()
        tag = STYLE_TAGS.get(m.group(2).lower())
        if tag:
            if m.group(1):
                if tag in open_now:
                    open_now.remove(tag)
            else:
                open_now.append(tag)
    rest = line[at:]
    if rest:
        plain.append(rest)
        spend["".join(sorted(set(open_now)))] = (
            spend.get("".join(sorted(set(open_now))), 0) + len(rest.strip()))
    words = "".join(plain)
    style = max(spend, key=lambda k: spend[k]) if spend else ""
    if not style and re.fullmatch(r"\s*\*[^*]+\*\s*", words):
        style = "star"
        words = words.strip().strip("*")
    return words, style


def _runs(part: str) -> list[tuple[str, str]]:
    """A fragment split into (words, style) at every change of styling.

    One legend entry can name two artists in two styles -- "NF & <i>Cordae</i>"
    means NF is the plain voice and Cordae the italic one -- so an entry cannot
    be reduced to a single style the way a lyric line can.
    """
    out, open_now, at = [], [], 0
    def add(text: str) -> None:
        style = "".join(sorted(set(open_now)))
        words = text.strip().strip("&,").strip()
        if words:
            out.append((words, style))
    for m in re.finditer(r"<(/?)(\w+)[^>]*>", part):
        add(part[at:m.start()])
        at = m.end()
        tag = STYLE_TAGS.get(m.group(2).lower())
        if tag:
            if m.group(1):
                if tag in open_now:
                    open_now.remove(tag)
            else:
                open_now.append(tag)
    add(part[at:])
    return out


def legend(head: str) -> dict[str, str]:
    """{style: who} from a section header's artist list, {} if it has none."""
    head = head.strip()
    if head.startswith("["):
        head = head[1:]
    if head.endswith("]"):
        head = head[:-1]
    if ":" not in head:
        return {}
    out: dict[str, str] = {}
    depth, at, parts = 0, 0, []
    body = head.split(":", 1)[1]
    for n, ch in enumerate(body):
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(0, depth - 1)
        elif ch == "," and not depth:
            parts.append(body[at:n]); at = n + 1
    parts.append(body[at:])
    for part in parts:
        for who, style in _runs(part):
            who = re.sub(r"\s*\([^)]*\)\s*$", "", who).strip()
            if who.startswith("*") and who.endswith("*"):
                who, style = who.strip("*").strip(), "star"
            if who and style not in out:
                out[style] = who
    return out


def _who(mapping: dict, style: str) -> str:
    """Who a line in this style belongs to, or "": a header naming one artist
    names them for the whole section; with two, an unlisted style is nobody."""
    if style in mapping:
        return mapping[style]
    named = set(mapping.values())
    return next(iter(named)) if len(named) == 1 else ""


def voiced_lines(text: str) -> list[dict]:
    """Lyric lines with who sings each, [{"text", "who", "style"}], styling
    threaded through lines and reset at each section header."""
    out, mapping = [], {}
    open_now: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        bare = re.sub(r"<[^>]+>", "", line).strip()
        if not out and _boilerplate(bare):
            continue
        if _note(bare):
            continue
        if bare.startswith("["):
            got = legend(line)
            if got:
                mapping = got
            open_now.clear()
            continue
        if re.fullmatch(r"\d+\s*(embed|contributors?).*", bare, re.I):
            continue
        words, style = _styled(line, open_now)
        words = re.sub(r"\d*embed$", "", words, flags=re.I).strip()
        if words:
            out.append({"text": words, "who": _who(mapping, style),
                        "style": style})
    return out


def sides(lines: list[dict], main: str = "") -> list[bool]:
    """True where a line belongs to the second voice: most-sung artist first,
    second other, the rest alternating; plain alternation if that cannot
    hold."""
    who = [ln.get("who", "") for ln in lines]
    counts: dict[str, int] = {}
    for name in who:
        if name:
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return [False] * len(lines)
    order = sorted(counts, key=lambda k: (-counts[k], k))
    first = order[0]
    second = order[1] if len(order) > 1 else ""
    seen: dict[str, bool] = {}
    out, last = [], False
    steady = True
    for name in who:
        if not name:
            side = last
        elif name == first:
            side = False
        elif name == second:
            side = True
        elif _shares(name, first):
            side = False
        else:
            side = not last
        if name:
            if name in seen and seen[name] != side:
                steady = False
            seen[name] = side
        out.append(side)
        last = side
    if steady:
        return out
    out, last, prev = [], False, None
    for name in who:
        if name and prev is not None and name != prev:
            last = not last
        if name:
            prev = name
        out.append(last)
    return out


def _shares(name: str, other: str) -> bool:
    """Is `other` one of the artists in a shared credit like "A & B"?"""
    if not other:
        return False
    parts = re.split(r"\s*(?:&|,|and|with|feat\.?|ft\.?)\s*", name, flags=re.I)
    return any(key(p) == key(other) for p in parts if p.strip())


BOILER_FIRST = re.compile(r"^\s*songtekst\s+van\b", re.I)


def _wrapped(line: str) -> bool:
    """Is the whole line one bracketed run, "(Ooh, ooh)" and nothing else?"""
    line = (line or "").strip()
    if not line.startswith("("):
        return False
    depth = 0
    for i, ch in enumerate(line):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i == len(line) - 1
    return False


BRACKETS = re.compile(r"[()（）]")


def unbracketed(line: str) -> str:
    """A reading with its round brackets taken out. Genius keeps them on
    ad-libs, which a background line already draws as an ad-lib."""
    return re.sub(r"\s{2,}", " ", BRACKETS.sub("", line or "")).strip()


def asides(words: list[str], text: str, reading: str) -> set[int]:
    """Which of a reading's `words` are a bracketed run the line does not
    sing: in it more often than in the line's `text` and own `reading`. A
    line with brackets of its own has none."""
    if re.search(r"[(\[（]", text or ""):
        return set()
    runs, cur, depth = [], [], 0
    for w, word in enumerate(words):
        opens = word.count("(") + word.count("[")
        if depth or opens:
            cur.append(w)
        elif cur:
            runs.append(cur)
            cur = []
        depth = max(0, depth + opens - word.count(")") - word.count("]"))
    if cur:
        runs.append(cur)
    said, whole = key(f"{reading} {text}"), key(" ".join(words))
    out: set[int] = set()
    for run in runs:
        k = key(" ".join(words[w] for w in run))
        if k and whole.count(k) > said.count(k):
            out |= set(run)
    return out


def unsung(reading: str, text: str, own: str) -> str:
    """A Genius reading without the ad-libs it writes into the line they
    answer, which the player draws as a backing line of their own. Kept
    whole when that would leave nothing; unwrapped when all of it is one."""
    words = (reading or "").split()
    gone = asides(words, text, own)
    left = " ".join(w for i, w in enumerate(words) if i not in gone)
    left = left if key(left) else reading
    if _wrapped(left) and not re.search(r"[(\[（]", text or ""):
        return unbracketed(left)
    return left


def _annotation(line: str) -> bool:
    """A bracketed run on its own, short enough to be a note rather than a
    lyric: "(x2)", "(Ooh)". A long one is an ad-lib line and is kept."""
    return _wrapped(line) and len(line.strip()) <= 12


_NOTE = re.compile(
    r"[x×]\s*\d+|\d+\s*[x×]|\d+|repeat\b.*|instrumental\b.*"
    r"|(?:pre-?)?(?:chorus|hook|verse|bridge|intro|outro|refrain)(?:\s*\d+)?",
    re.I)


def _note(line: str) -> bool:
    """A bracketed run on its own that tells the reader something -- "(x2)",
    "(Repeat chorus)" -- rather than a voice singing. _annotation's length
    rule is right for matching readings, where a stray "(Ooh)" only gets in
    the way, but read as a lyric that rule throws away standalone ad-libs:
    One For the Money's "(Woah)" never reached the editor."""
    if not _wrapped(line):
        return False
    return bool(_NOTE.fullmatch(line.strip()[1:-1].strip()))


def _boilerplate(line: str) -> bool:
    return bool(BOILER_FIRST.match(re.sub(r"<[^>]+>", "", line or "")))


def clean_lines(text: str) -> list[str]:
    """Lyric lines only -- no [Verse 1] headers, no blanks, no boilerplate."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not out and _boilerplate(line):
            continue
        if not line or line.startswith("[") or _annotation(line):
            continue
        if re.fullmatch(r"\d+\s*(embed|contributors?).*", line, re.I):
            continue
        line = re.sub(r"\d*embed$", "", line, flags=re.I).strip()
        if line:
            out.append(line)
    return out


@functools.lru_cache(maxsize=8192)
def key(s: str) -> str:
    """Comparison form: letters only, accents folded, case dropped.

    Remembered: a song is aligned against the same few hundred strings over
    and over, and this is a Unicode normalisation of each -- 9,000 calls and a
    tenth of one align."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def key_map(s: str) -> tuple[str, list[int]]:
    """key(), plus where each surviving letter came from in the original.

    Needed to cut a romanised word back up at the right place: "hibiiteiru" is
    one Genius word covering three sung syllables, and to fill it in step with
    them you have to know which letters belong to which.
    """
    out, idx = [], []
    for i, ch in enumerate(s or ""):
        for c in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(c):
                continue
            c = c.lower()
            if c.isascii() and (c.isalpha() or c.isdigit()):
                out.append(c)
                idx.append(i)
    return "".join(out), idx


@functools.lru_cache(maxsize=4096)
def similar(a: str, b: str) -> float:
    """How alike two lines read. Remembered, because rebalance, unmerge and
    _left_over all ask about the same line and the same text again for every
    candidate they try -- 43% of the ratios over a song with a repeated chorus
    were ones already worked out."""
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return 0.0
    return SequenceMatcher(None, ka, kb).ratio()


MAX_JOIN = 4
REBALANCE_GAIN = 0.05

# The stored romanisations' own revision, counted from one at 1.0.0 with the
# rest. A mismatch re-asks Genius for the song, which is one request.
REVISION = 6


def align(ours: list[str], theirs: list[str], min_score: float = 0.55,
          max_join: int = MAX_JOIN, asides=()) -> dict[int, str]:
    """Map our line indexes onto Genius lines monotonically, weak pairs
    dropped; one of ours may take a run of Genius lines. `asides` are
    stepped over."""
    n, m = len(ours), len(theirs)
    if not n or not m:
        return {}
    kt = [key(t) for t in theirs]
    seen: dict[tuple[str, str], float] = {}
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[(2, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        ko = key(ours[i - 1])
        sm = SequenceMatcher(None, "", ko, autojunk=False)
        lb = len(ko)
        for j in range(1, m + 1):
            drop_a, drop_b = score[i - 1][j], score[i][j - 1]
            best, move, run = (drop_a, 2, 0) if drop_a >= drop_b else (drop_b, 3, 0)
            joined = ""
            for k in range(1, min(max_join, j) + 1):
                joined = kt[j - k] + joined
                if not joined or not lb:
                    continue
                la = len(joined)
                if la > lb and 2 * lb < min_score * (la + lb):
                    break
                s = seen.get((ko, joined))
                if s is None:
                    sm.set_seq1(joined)
                    if (sm.real_quick_ratio() < min_score
                            or sm.quick_ratio() < min_score):
                        s = -1.0
                    else:
                        s = sm.ratio()
                    seen[(ko, joined)] = s
                if s < min_score:
                    continue
                take = score[i - 1][j - k] + (s - min_score)
                if take > best:
                    best, move, run = take, 1, k
            score[i][j] = best
            back[i][j] = (move, run)
    out: dict[int, str] = {}
    used: set = set()
    i, j = n, m
    while i > 0 and j > 0:
        move, run = back[i][j]
        if move == 1:
            out[i - 1] = " ".join(theirs[j - run:j])
            used.update(range(j - run, j))
            i, j = i - 1, j - run
        elif move == 2:
            i -= 1
        else:
            j -= 1
    asides = set(asides)
    got = rebalance(unmerge(out, ours, min_score, asides=asides), ours, asides)
    return _left_over(got, ours, theirs, used)


def fit_pairs(pairs: list[tuple[str, str]], texts: list[str],
              readings: list[str]) -> dict[str, str]:
    """{"text#nth" (and "text" for exact matches) -> romanisation} for our
    lines, from another source's (text, romanisation) pairs. Equal text after
    normalising wins; the rest are aligned by reading like a Genius page, and
    kept only if that alignment is believable."""
    import lyric_sources as LS
    keyed: dict[str, str] = {}
    for text, rom in pairs:
        keyed.setdefault(LS._rkey(text), rom)
    out: dict[str, str] = {}
    seen: dict[str, int] = {}
    rest: dict[int, tuple[str, int]] = {}
    for i, text in enumerate(texts):
        t = (text or "").strip()
        if not t:
            continue
        nth = seen[t] = seen.get(t, 0) + 1
        rom = keyed.get(LS._rkey(t))
        if rom:
            out[f"{t}#{nth}"] = rom
            out.setdefault(t, rom)
        else:
            rest[i] = (t, nth)
    if rest and pairs:
        readings = [_latin(r, LS.SL) for r in readings]
        import offload                  # the GIL, on long songs; see align
        mapping = offload.call(align, readings, [r for _, r in pairs])
        got = [(i, mapping[i]) for i in rest if mapping.get(i)]
        if got and believable((readings[i], r) for i, r in got):
            for i, r in got:
                t, nth = rest[i]
                out[f"{t}#{nth}"] = r
    return out


def _latin(reading: str, SL) -> str:
    """A reading with Latin letters to align on: kakasi's where it has none."""
    if not reading or re.search(r"[A-Za-z]", reading):
        return reading
    kks = SL._kakasi()
    if kks is None:
        return reading
    try:
        return " ".join(x.get("hepburn", "") for x in kks.convert(reading))
    except Exception:
        return reading


MAP_FLOOR = 0.65


def believable(pairs) -> bool:
    """Whether a whole song's mapping reads like the song, judged on the median
    pair's score."""
    sims = sorted(similar(a, b) for a, b in pairs if key(a) and key(b))
    if not sims:
        return True
    return sims[len(sims) // 2] >= MAP_FLOOR


def _left_over(mapping: dict[int, str], ours: list[str], theirs: list[str],
               used: set) -> dict[int, str]:
    """Put a Genius line nothing took onto the nearby line of ours that sings
    it, where it reads clearly better."""
    if not used:
        return mapping
    lo, hi = min(used), max(used)
    for j in range(lo + 1, hi):
        if j in used or not key(theirs[j]):
            continue
        best, where = 0.0, None
        for i, text in mapping.items():
            if not text:
                continue
            gain = similar(ours[i], f"{text} {theirs[j]}") - similar(ours[i], text)
            if gain > best:
                best, where = gain, i
        if where is not None and best >= 0.05:
            mapping[where] = f"{mapping[where]} {theirs[j]}"
    return mapping


def rebalance(mapping: dict[int, str], ours: list[str],
              asides=frozenset()) -> dict[int, str]:
    """Slide the boundary between two neighbouring lines to the cut of their
    joined text that reads best against both."""
    idx = sorted(i for i in mapping if i not in asides)
    for a, b in zip(idx, idx[1:]):
        if any(ours[x].strip() and x not in mapping and x not in asides
               for x in range(a + 1, b)):
            continue
        left, right = mapping[a].split(), mapping[b].split()
        words = left + right
        if len(words) < 2:
            continue
        best = (similar(ours[a], mapping[a]) + similar(ours[b], mapping[b]), len(left))
        for cut in range(1, len(words)):
            if cut == len(left):
                continue
            s = (similar(ours[a], " ".join(words[:cut]))
                 + similar(ours[b], " ".join(words[cut:])))
            # Only for a real gain. A word that reads like nothing on either
            # side -- "fuu" under 風, which the dictionary reads "kaze" --
            # moves the score by the odd shared vowel, and slid on that it
            # walked from the end of every God-ish line to the start of the
            # next.
            if s > best[0] + REBALANCE_GAIN:
                best = (s, cut)
        cut = best[1]
        if cut != len(left):
            mapping[a] = " ".join(words[:cut])
            mapping[b] = " ".join(words[cut:])
    return mapping


def unmerge(mapping: dict[int, str], ours: list[str],
            min_score: float = 0.55, max_split: int = 3,
            asides=frozenset()) -> dict[int, str]:
    """Cut one Genius line covering several of ours back apart on a word
    boundary, only where both halves stand on their own."""
    base = dict(mapping)
    leads = [x for x in range(len(ours)) if x not in asides]
    at = {x: n for n, x in enumerate(leads)}
    for i in sorted(base):
        words = _words(base[i])
        if len(words) < 2:
            continue

        def free(x):
            return 0 <= x < len(ours) and x not in mapping and ours[x].strip()

        spans = []
        for lo in range(i - max_split + 1, i + 1):
            for size in range(2, max_split + 1):
                runs = [list(range(lo, lo + size))]
                n = at.get(i, -1) - (i - lo)
                if i in at and n >= 0:
                    runs.append(leads[n:n + size])
                for rows in runs:
                    if (len(rows) == size and i in rows and rows not in spans
                            and all(r == i or free(r) for r in rows)):
                        spans.append(rows)
        whole = similar(ours[i], base[i])
        best, cuts, where = whole, None, None
        for rows in spans:
            for split in _cut_sets(len(words), len(rows)):
                segs = [_join(words[a:b])
                        for a, b in zip((0,) + split, split + (len(words),))]
                scores = [similar(ours[r], seg) for r, seg in zip(rows, segs)]
                if min(scores) < min_score and not _carried(scores, min_score):
                    continue
                total = sum(scores) / len(scores)
                if total > best:
                    best, cuts, where = total, segs, rows
        if cuts:
            for r, seg in zip(where, cuts):
                mapping[r] = seg
    return mapping


_FOREIGN = re.compile(r"[^\W\d_A-Za-zÀ-ɏḀ-ỿ]")


def misses_script(text: str, reading: str, theirs: str) -> bool:
    """Whether a Genius line says nothing for the non-Latin part of ours (it
    matched on the English alone)."""
    latin: dict[str, int] = {}
    for w in (text or "").split():
        if not _FOREIGN.search(w) and key(w):
            latin[key(w)] = latin.get(key(w), 0) + 1

    def rest(s: str) -> str:
        left = dict(latin)
        out = []
        for w in (s or "").split():
            k = key(w)
            if left.get(k):
                left[k] -= 1
            else:
                out.append(k)
        return "".join(out)

    if not any(_FOREIGN.search(w) for w in (text or "").split()) or not latin:
        return False
    return bool(rest(reading)) and not rest(theirs)


def _words(text: str) -> list[str]:
    """Where a Genius line may be cut apart: at spaces, after hyphens and
    commas; a word-ending piece keeps its trailing space."""
    out = []
    for w in (text or "").split():
        bits = [b for b in re.split(r"(?<=[-、，,])", w) if b]
        out += bits[:-1] + [bits[-1] + " "]
    return [w for w in out if w.strip(" -")]


def _join(pieces: list[str]) -> str:
    """_words back into text, without a hyphen left hanging at a cut."""
    return "".join(pieces).strip().rstrip("-")


def _carried(scores: list[float], min_score: float) -> bool:
    """Whether a cut is good enough overall though one piece reads badly
    (English standing for katakana)."""
    weak = [s for s in scores if s < min_score]
    return (len(weak) == 1 and weak[0] >= 0.35
            and all(s >= 0.85 for s in scores if s >= min_score))


def _cut_sets(n_words: int, parts: int):
    """Every way to cut n_words into `parts` non-empty runs, in order."""
    if parts <= 1 or n_words < parts:
        return
    if parts == 2:
        for a in range(1, n_words):
            yield (a,)
        return
    for a in range(1, n_words - parts + 2):
        for rest in _cut_sets(n_words - a, parts - 1):
            yield (a,) + tuple(a + r for r in rest)


def page_artist(title: str) -> str:
    """Who a Genius romanisation page says the song is by (the title before the
    dash), or ""."""
    bare = ROMAN_HINT.sub("", title or "").strip(" -()[]")
    return bare.split(" - ", 1)[0].strip() if " - " in bare else ""


def by_us(hit: dict, artist: str) -> bool:
    """Whether a romanisation page is for the artist asked about, matched with
    `_norm` so artists in their own script count."""
    if not artist:
        return True
    head = page_artist(hit.get("title") or "")
    if not head:
        return True
    ours, theirs = LS_norm(artist), LS_norm(head)
    if not ours or not theirs:
        return True
    return ours in theirs or theirs in ours or names_meet(head, artist)


_PAREN = re.compile(r"\s*[(\[（【][^()\[\]（）【】]*[)\]）】]")


def name_keys(credit: str) -> list[set[str]]:
    """Each name in a credit as every key it goes by: whole, outside its
    brackets, and each bracket alone ("CV:" dropped). See
    docs/notes/mild-lyrics/genius_roman.md."""
    import lyric_sources as LS
    out = []
    for name in LS.NAMES_APART.split(credit or ""):
        keys = {LS_norm(name)}
        bare, inner = name, []
        while True:
            m = _PAREN.search(bare)
            if not m:
                break
            inner.append(m.group(0).strip(" ()[]（）【】"))
            bare = bare[:m.start()] + " " + bare[m.end():]
        keys.add(LS_norm(bare))
        for part in inner:
            keys.add(LS_norm(re.sub(r"^\s*CV[.:：]?\s*", "", part, flags=re.I)))
        keys = {k for k in keys if k}
        if keys:
            out.append(keys)
    return out


def names_meet(a: str, b: str) -> bool:
    """Whether two credits share a name by any key; containment only for
    keys of 3+ characters."""
    left, right = name_keys(a), name_keys(b)
    for x in (k for ks in left for k in ks):
        for y in (k for ks in right for k in ks):
            if x == y or (min(len(x), len(y)) >= 3 and (x in y or y in x)):
                return True
    return False


def LS_norm(s: str) -> str:
    """`lyric_sources._norm`, imported late.

    This module is imported BY lyric_sources, so it cannot import it back at
    the top of the file; by the time any of this runs both are loaded.
    """
    import lyric_sources
    return lyric_sources._norm(s)


def linked_romanisation(token: str, song_id, timeout: float = 6.0) -> dict | None:
    """The romanisation Genius itself links to a song, if any; one request,
    asked only after searching came up empty."""
    song = song_of(token, song_id, timeout)
    for tr in song.get("translation_songs") or []:
        if not isinstance(tr, dict):
            continue
        if str(tr.get("language") or "").lower() in ("romanization", "romanized"):
            return tr
    return None


def ours(hit: dict, title: str, artist: str) -> bool:
    """Whether a search hit is the song asked for: the byline must match, the
    title test looser than `_same_song`, `_same_cut` still applied."""
    import lyric_sources as LS
    theirs = str(hit.get("title") or "")
    who = str((hit.get("primary_artist") or {}).get("name") or "")
    if (artist and who and not LS._same_artist(who, artist)[1]
            and not names_meet(who, artist)):
        return False
    if not (LS._same_cut(theirs, title) and LS._same_cut(title, theirs)):
        return False
    a, b = LS._norm(theirs), LS._norm(title)
    return bool(a and b) and (a == b or a in b or b in a)


def song_page(token: str, title: str, artist: str,
              timeout: float = 6.0) -> str:
    """The Genius page of the song itself, or "" where none is clearly it.

    One query rather than search's four: those are after romanisations, and
    this wants the original, so a romanised or translated page never answers
    and neither does a hit `ours` turns away.
    """
    q = urllib.parse.quote(f"{title} {artist}".strip())
    if not q:
        return ""
    hits = []
    if token:
        try:
            data = json.loads(_get(f"{API}/search?q={q}", timeout=timeout,
                                   headers={"Authorization": f"Bearer {token}"}))
            hits += [h.get("result") or {}
                     for h in data.get("response", {}).get("hits", [])]
        except Exception:
            pass
    if not hits:
        try:
            data = json.loads(_get(f"https://genius.com/api/search/multi?q={q}",
                                   timeout=timeout))
            for sec in data.get("response", {}).get("sections", []):
                if sec.get("type") in ("top_hit", "song"):
                    hits += [h.get("result") or {} for h in sec.get("hits", [])]
        except Exception:
            pass
    for hit in hits:
        if (is_song(hit) and not is_romanisation(hit)
                and ours(hit, title, artist)):
            return hit.get("url") or (("https://genius.com" + hit["path"])
                                      if hit.get("path") else "")
    return ""


def find_romanisation(token: str, title: str, artist: str,
                      timeout: float = 6.0, texts=()) -> tuple[list[str], dict] | None:
    """(lines, chosen hit) for the best romanised match, or None: a
    romanisation page by the right artist, else the song's linked one, else
    by_lyrics (`texts`)."""
    hits = list(search(token, title, artist, timeout))
    for hit in hits:
        if not is_romanisation(hit) or not by_us(hit, artist):
            continue
        lines = clean_lines(lyrics_for(hit.get("id"), timeout))
        if len(lines) >= 4:
            return lines, hit
    for hit in hits:
        if is_romanisation(hit) or not ours(hit, title, artist):
            continue
        tr = linked_romanisation(token, hit.get("id"), timeout)
        if not tr:
            continue
        lines = clean_lines(lyrics_for(tr.get("id"), timeout))
        if len(lines) >= 4:
            return lines, tr
    return by_lyrics(token, texts, timeout) if texts else None


LYRIC_ASKS = 3


def by_lyrics(token: str, texts, timeout: float = 6.0) -> tuple[list[str], dict] | None:
    """The romanisation of the song Genius finds by our own lines, for a track
    whose names it files differently ("SIGN IS B" for サインはB). The caller's
    `believable` check still has the last word."""
    asks = sorted({t.strip() for t in texts if t and t.strip()},
                  key=len, reverse=True)[:LYRIC_ASKS]
    votes: dict = {}
    seen: list[dict] = []
    for line in asks:
        try:
            data = json.loads(_get("https://genius.com/api/search/multi?q="
                                   + urllib.parse.quote(line[:100]), timeout=timeout))
        except Exception:
            continue
        for sec in data.get("response", {}).get("sections", []):
            if sec.get("type") != "lyric":
                continue
            for hit in sec.get("hits") or []:
                res = hit.get("result") or {}
                if not res.get("id") or not is_song(res):
                    continue
                if res["id"] not in votes:
                    seen.append(res)
                votes[res["id"]] = votes.get(res["id"], 0) + 1
    # Two lines have to find it: one alone can be a quote, and Genius files
    # several pages under one title (アイドル), so three may not all agree.
    need = min(2, len(asks))
    for res in sorted((r for r in seen if votes[r["id"]] >= need),
                      key=lambda r: -votes[r["id"]])[:3]:
        tr = res if is_romanisation(res) else linked_romanisation(token, res["id"], timeout)
        if not tr:
            continue
        lines = clean_lines(lyrics_for(tr.get("id"), timeout))
        if len(lines) >= 4:
            return lines, tr
    return None


_LINK = re.compile(r"^(?:https?://)?(?:www\.)?genius\.com/(\S+)$", re.I)


def is_link(text: str) -> bool:
    """Whether what was typed is a genius.com address rather than a search."""
    return bool(_LINK.match((text or "").strip()))


def song_from_link(link: str, timeout: float = 6.0) -> int | None:
    """The song id behind a genius.com address, or None.

    A /songs/<id> address says it outright. A song page's own address is a
    slug, so the page is read for the `genius://songs/<id>` link it carries
    for the app. Nothing but genius.com is ever fetched.
    """
    m = _LINK.match((link or "").strip())
    if not m:
        return None
    path = m.group(1).split("?")[0].split("#")[0]
    sid = re.match(r"songs/(\d+)", path)
    if sid:
        return int(sid.group(1))
    raw = _get("https://genius.com/" + path, timeout=timeout).decode(
        "utf-8", "replace")
    sid = re.search(r"genius://songs/(\d+)", raw)
    return int(sid.group(1)) if sid else None


def romanisation_of(token: str, song_id: int,
                    timeout: float = 6.0) -> tuple[list[str], dict] | None:
    """(lines, hit) for one song picked by hand, by search or by link.

    A romanised page is read as it is. The original's page is asked for the
    romanisation Genius files against it, and read itself only where it has
    none -- somebody pasting it may know its lyric is in Latin letters.
    """
    song = song_of(token, song_id, timeout) or {"id": song_id}
    if not is_romanisation(song):
        for tr in song.get("translation_songs") or []:
            if (isinstance(tr, dict) and tr.get("id") and str(
                    tr.get("language") or "").lower() in ("romanization",
                                                         "romanized")):
                song = tr
                break
    lines = clean_lines(lyrics_for(song.get("id"), timeout))
    return (lines, song) if lines else None


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    got = find_romanisation(sys.argv[1], sys.argv[2], sys.argv[3])
    if not got:
        sys.exit("no romanised version found")
    lines, hit = got
    print(f"{hit.get('full_title')}  (id {hit.get('id')}) -- {len(lines)} lines")
