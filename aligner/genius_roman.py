#!/usr/bin/env python3
"""
Fetch a human-made romanisation from Genius and line it up with timed lyrics.

Genius hosts romanised versions of Japanese/Korean/Chinese songs, usually under
the "Genius Romanizations" account or with "Romanized" in the title. Those are
written by people, so they carry the invented readings (運命 sung "sadame") that
no romanizer can infer from the text.

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
import json
import math
import re
import sys
import unicodedata
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

        if any(is_romanization(h) for h in hits):
            break

    hits.sort(key=lambda h: not is_romanization(h))
    return hits


def is_song(hit: dict) -> bool:
    """A song entry, not an album or artist.

    The web multi-search top_hit section returns albums too, and an album for
    "<song> (Romanized)" has a romanisation-shaped title and passes every check
    below. Its id then went to /songs/<id>/embed, which is a different id space
    -- so KICK BACK imported the lyrics of whatever song happened to hold that
    number, and put them on the track as its romanisation.
    """
    t = hit.get("_type") or hit.get("type")
    return t is None or t == "song"


def is_romanization(hit: dict) -> bool:
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
    """The one lyric line Genius says it matched, out of the snippet it sends.

    A lyric hit carries a few lines of context with the matched characters
    marked by offset, and the line worth showing is the one holding most of
    those marks -- the first and last lines of a snippet are usually cut
    mid-phrase, so the longest or the first would both often be a fragment.
    """
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
    """Genius's pageview count, flattened to 0..1.

    The difference that matters here is between three million and five
    thousand -- the original against somebody's bedroom cover of it -- and on
    a straight count that difference would swamp every other signal, so it is
    read as its order of magnitude.
    """
    try:
        views = int(((hit.get("stats") or {}).get("pageviews")) or 0)
    except (TypeError, ValueError):
        return 0.0
    if views <= 0:
        return 0.0
    return min(1.0, math.log10(views) / 7.0)


def score_song(query: str, title: str, artist: str, line: str = "",
               pop: float = 0.0) -> tuple[float, str]:
    """How well a song answers what was typed, and on which of its two halves.

    One query gets asked two different questions -- is this the song's NAME,
    or a LINE from inside it -- and the good answer looks different for each,
    so both are scored and the better one is taken. Which one won is worth
    knowing beyond the number: it is the difference between a row that should
    read "In the End -- Linkin Park" and one that should read "But in the end,
    it doesn't even matter".

    Popularity settles what the words cannot. "In the End" by Linkin Park and
    "In The End (Linkin Park Cover)" by RADIO TAPOK are near enough identical
    as text, and three million pageviews against five thousand is the whole
    difference between them.
    """
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
    """Songs that answer `query`, whether it is a name or a line, best first.

    The web multi-search is the endpoint that reads the lyrics: its `lyric`
    section matches a phrase inside the song rather than in its name, and
    hands back the snippet it matched with the matching characters marked, so
    the line the user half-remembered can be shown back to them.

    Section order is NOT taken as ranking. Genius returns each kind of match
    in its own section and the one that answers the question depends on what
    was asked -- "in the end linkin park" put a DJ set's track list and a
    Jay-Z mashup above Linkin Park, because those are what the LYRIC section
    had and the lyric section was read first. Everything is scored against
    what was typed instead; see rank_hit.

    The API search is a fallback rather than a supplement, for the same
    reason: it matches names only, has no idea which of them is the record
    everybody means, and on a query the web search already answered it adds
    nothing but other people's covers.

    Never raises: this runs behind a keystroke, and a search that cannot reach
    Genius should leave the local hits alone rather than take the screen down.
    """
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


def lyrics_for(song_id: int, timeout: float = 6.0, markup: bool = False) -> str:
    """Plain text for a song id, via the embed endpoint.

    With `markup`, the italic and bold tags survive. They are how Genius says
    who is singing, and the section headers say what each style means -- see
    legend(). Everything else is still stripped.
    """
    try:
        js = _get(f"https://genius.com/songs/{song_id}/embed", timeout=timeout).decode(
            "utf-8", "replace")
    except Exception:
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


STYLE_TAGS = {"i": "i", "em": "i", "b": "b", "strong": "b"}


def _styled(line: str, open_now: list[str] | None = None) -> tuple[str, str]:
    """(the words, which style carries most of them).

    "" for unstyled, "i", "b", "bi" or "star". A line is usually wrapped whole,
    but a part of one can be styled on its own; the style that covers the most
    characters is the line's, because that is the voice the line belongs to.

    `open_now` is the styling still open where this line begins, and it is
    left holding the styling still open where it ends -- so a caller reading a
    whole lyric threads one list through every line of it. Genius wraps a RUN
    of lines in one tag, opening it on the first and closing it on the last:

        <i>Si je vous gêne, bah c'est la même

        Si je vous gêne, bah c'est la même</i>

    Read a line at a time and the second of those comes back unstyled, so the
    two halves of one couplet went to two different singers -- which is
    exactly what somebody watching the screen sees, one line answered and the
    next one not.
    """
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
    """Who a line in this style belongs to, or "" where the song never said.

    A header that names ONE artist names them for the whole of their section,
    whatever the styling does inside it. "[Pont : Maître Gims]" with the
    stanza in italics is emphasis, not a second singer -- and reading that
    italic as somebody the header did not name left four lines to whoever
    happened to sing last, which was the other man.

    Where the header names two, an unlisted style is still nobody: telling
    them apart is the whole of what the mapping is for, and guessing between
    them would undo it.
    """
    if style in mapping:
        return mapping[style]
    named = set(mapping.values())
    return next(iter(named)) if len(named) == 1 else ""


def voiced_lines(text: str) -> list[dict]:
    """Lyric lines with who sings each, read from the styling and the headers.

    [{"text", "who", "style"}] -- `who` is "" where the song never said.
    Headers are consumed rather than returned: they are the legend, not lyrics.

    The styling is threaded through the lines rather than read afresh on each
    one, because Genius spells a run of lines as one tag around all of them;
    see _styled. A section header starts it over, since Genius closes its tags
    before one and a tag left open across a header is a slip in the markup --
    bounded to its own section, it costs a stanza rather than the rest of the
    song.
    """
    out, mapping = [], {}
    open_now: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        bare = re.sub(r"<[^>]+>", "", line).strip()
        if not out and _boilerplate(bare):
            continue
        if _annotation(bare):
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
    """True where a line belongs to the second voice, by gc's rules.

    The most-sung artist takes the first voice and the second-most takes the
    other. Anyone else alternates: each line by somebody else takes the side
    the line before it did not. A line two artists share goes to the first
    voice if the first voice is one of them, and otherwise alternates too.

    If that cannot be held -- if an artist would have to appear on both sides
    -- the whole song falls back to alternating on every change of singer,
    which at least stays legible: the contrast is then between consecutive
    voices rather than between named people.
    """
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
    """Is the whole line one bracketed run -- "(Ooh, ooh)" and nothing else?

    The test used to be "starts with ( and ends with )", which is not the same
    question. Jane Remover's "Dancing with your eyes closed" is 21 lines of
    "(Promise I like it like—) Promise I like it like that": they open with an
    ad-lib and go on with the words the singer sings, and every one of them
    was thrown away before it reached the aligner or the editor -- 68 rows in,
    34 lines out.
    """
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


def _annotation(line: str) -> bool:
    """A bracketed run on its own, short enough to be a note rather than a
    lyric: "(x2)", "(Ooh)". A long one is an ad-lib line and is kept."""
    return _wrapped(line) and len(line.strip()) <= 12


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


def key(s: str) -> str:
    """Comparison form: letters only, accents folded, case dropped."""
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


def similar(a: str, b: str) -> float:
    ka, kb = key(a), key(b)
    if not ka or not kb:
        return 0.0
    return SequenceMatcher(None, ka, kb).ratio()


MAX_JOIN = 4

REVISION = 3


def align(ours: list[str], theirs: list[str], min_score: float = 0.55,
          max_join: int = MAX_JOIN) -> dict[int, str]:
    """Map our line indexes onto Genius lines, in order.

    A plain nearest-match would happily pair line 3 with line 40 and scramble a
    whole song, so this is a monotonic alignment: matches must advance through
    both sequences. Weak pairings are dropped rather than forced, since leaving a
    line alone beats replacing it with someone else's words.

    One of ours may take a RUN of consecutive Genius lines. Genius breaks for
    the page, not for the vocal, so a single sung line is often printed as two:
    「くわばら くわばら くわばら目にも止まらん速さ」 is "Kuwabara, kuwabara,
    kuwabara" + "Me ni mo tomaran hayasa, hey". Pairing one-to-one kept the
    first half and silently dropped the rest, which is why romanised lines came
    out shorter than the original underneath them -- six of the first thirteen
    lines of Otonoke lost a piece that way.
    """
    n, m = len(ours), len(theirs)
    if not n or not m:
        return {}
    kt = [key(t) for t in theirs]
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
                sm.set_seq1(joined)
                if sm.real_quick_ratio() < min_score or sm.quick_ratio() < min_score:
                    continue
                s = sm.ratio()
                if s < min_score:
                    continue
                take = score[i - 1][j - k] + (s - min_score)
                if take > best:
                    best, move, run = take, 1, k
            score[i][j] = best
            back[i][j] = (move, run)
    out: dict[int, str] = {}
    i, j = n, m
    while i > 0 and j > 0:
        move, run = back[i][j]
        if move == 1:
            out[i - 1] = " ".join(theirs[j - run:j])
            i, j = i - 1, j - run
        elif move == 2:
            i -= 1
        else:
            j -= 1
    return rebalance(unmerge(out, ours, min_score), ours)


def rebalance(mapping: dict[int, str], ours: list[str]) -> dict[int, str]:
    """Slide the boundary between two neighbouring lines to where it belongs.

    Genius does not break where the vocal does, in either direction, so a run
    taken for one line can end with words that belong to the next -- 「今日も嘘
    をつくの」 came out as "Kyou mo uso wo tsuku no kono kotoba ga", carrying off
    the opening of the line below -- and the mirror leaves 「なんてないわけがない」
    without its "Wake ga nai", which turns up on the following line instead.

    Neither is a matching failure as such: the words are present, just on the
    wrong side of one boundary. So for each adjacent pair, try every cut of
    their combined text and keep the one that reads best against both lines.
    """
    idx = sorted(mapping)
    for a, b in zip(idx, idx[1:]):
        if any(ours[x].strip() and x not in mapping for x in range(a + 1, b)):
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
            if s > best[0]:
                best = (s, cut)
        cut = best[1]
        if cut != len(left):
            mapping[a] = " ".join(words[:cut])
            mapping[b] = " ".join(words[cut:])
    return mapping


def unmerge(mapping: dict[int, str], ours: list[str],
            min_score: float = 0.55, max_split: int = 3) -> dict[int, str]:
    """Undo the opposite mistake: one Genius line covering several of ours.

    Genius prints 「今日何食べた？」「好きな本は？」 as one line, "Kyou nani
    tabeta? Suki na hon wa?". The alignment can only give that to one of the
    two, so the first line showed a romanisation with a whole extra question in
    it and the second showed none. Cut it back apart on a word boundary, and
    only where both halves stand on their own -- a bad cut would put half a
    sentence under each line, which is worse than the merge.
    """
    base = dict(mapping)
    for i in sorted(base):
        words = base[i].split()
        if len(words) < 2:
            continue

        def free(x):
            return 0 <= x < len(ours) and x not in mapping and ours[x].strip()

        spans = []
        for lo in range(i - max_split + 1, i + 1):
            for size in range(2, max_split + 1):
                rows = list(range(lo, lo + size))
                if i in rows and all(r == i or free(r) for r in rows):
                    spans.append(rows)
        whole = similar(ours[i], base[i])
        best, cuts, where = whole, None, None
        for rows in spans:
            for split in _cut_sets(len(words), len(rows)):
                segs = [" ".join(words[a:b])
                        for a, b in zip((0,) + split, split + (len(words),))]
                scores = [similar(ours[r], seg) for r, seg in zip(rows, segs)]
                if min(scores) < min_score:
                    continue
                total = sum(scores) / len(scores)
                if total > best:
                    best, cuts, where = total, segs, rows
        if cuts:
            for r, seg in zip(where, cuts):
                mapping[r] = seg
    return mapping


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


def find_romanization(token: str, title: str, artist: str,
                      timeout: float = 6.0) -> tuple[list[str], dict] | None:
    """(lines, chosen hit) for the best romanised match, or None."""
    for hit in search(token, title, artist, timeout):
        if not is_romanization(hit):
            continue
        lines = clean_lines(lyrics_for(hit.get("id"), timeout))
        if len(lines) >= 4:
            return lines, hit
    return None


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    got = find_romanization(sys.argv[1], sys.argv[2], sys.argv[3])
    if not got:
        sys.exit("no romanised version found")
    lines, hit = got
    print(f"{hit.get('full_title')}  (id {hit.get('id')}) -- {len(lines)} lines")
