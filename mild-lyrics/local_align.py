"""Word timings measured on this machine against the song's own audio: Demucs
takes out the vocal, MMS_FA places our words in it; `room()` shares the GPU."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import concurrent.futures
import contextlib
import json
import os
import pathlib
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse

import genius_roman as GR
import lyric_sources as LS
import noconsole
import spicy_lyrics as SL

MIN_SCORE = 0.005
PACKED_UNDER = 0.1
ONSET_HOP = 160
ONSET_NEAR = 25
ONSET_OVER = 1.4
ONSET_WINDOW = 0.12
ONSET_FORWARD = 0.4
ONSET_DOUBT = 2.0
ONSET_BACK = 5
ONSET_LATE = 0.06
ONSET_LEAD_KEPT = False
HEARD_SHARE = 0.35
HEARD_MARGIN = 0.15
NULL_FLOOR = 0.05
VERIFY_MODEL = "openai/whisper-base"
COMMON = frozenset("""
a an the and or but if so as at by for from in into of off on to up with
i im ive id you youre your yours we were us our they them their he him his
she her it its me my mine myself this that these those there here
is are was were be been being am do does did done doing have has had
will would can could should shall may might must not no nor never
all any both each few more most other some such only own same than too very
what which who whom whose when where why how all just now then out over under
again once about above after before below down during
oh ooh ah aah yeah yea ya na la da uh huh mm hmm ay aye woo
like get got go going gone come came know knows knew let lets
""".split())


MAX_WORD = 4.0


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
UNSPACED = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿가-힣]")
KANA = re.compile(r"[぀-ゟ゠-ヿ]")
ASCII_OK = re.compile(r"^[a-z']+$")

_uroman = None
_kakasi = None
_reading: dict[str, str] = {}


def _romanise(text: str) -> str:
    """`text` in Latin letters: pykakasi where it applies, uroman otherwise."""
    global _uroman, _kakasi
    if _kakasi is None:
        try:
            import pykakasi
            _kakasi = pykakasi.kakasi()
        except Exception:
            _kakasi = False
    if _kakasi and KANA.search(text):
        try:
            return " ".join(p.get("hepburn") or "" for p in _kakasi.convert(text))
        except Exception:
            pass
    if _uroman is None:
        try:
            import uroman as _u
            _uroman = _u.Uroman()
        except Exception:
            _uroman = False
    if _uroman:
        try:
            return _uroman.romanize_string(text)
        except Exception:
            pass
    return text


def _units(text: str) -> list[tuple[str, bool]]:
    """One line cut into (text, joins the one before) units: spaces, else
    pykakasi words, else characters. `_fill` turns the flag into
    IsPartOfWord."""
    out: list[tuple[str, bool]] = []
    for word in text.split():
        if not UNSPACED.search(word):
            out.append((word, False))
            continue
        if _kakasi and KANA.search(word):
            try:
                got = list(_kakasi.convert(word))
            except Exception:
                got = []
            parts = [p.get("orig") or "" for p in got]
            reads = {p["orig"]: p["hepburn"] for p in got
                     if p.get("orig") and p.get("hepburn")}
            parts = [p for p in parts if p]
            if len(parts) > 1 and "".join(parts) == word:
                _reading.update(reads)
                out += [(p, i > 0) for i, p in enumerate(parts)]
                continue
            _reading.update(reads)
        if len(word) > 1:
            out += [(ch, i > 0) for i, ch in enumerate(word)]
        else:
            out.append((word, False))
    return out


def words_of(doc: dict) -> tuple[list[str], list[tuple[int, int, bool]]]:
    """Every unit in the document, and where each came from.

    The second list is (line index, index within the line, joins the previous),
    so timings can be put back exactly where they were taken from -- which is
    the only reason this can return our own wording rather than the aligner's.
    """
    _reading.clear()
    words: list[str] = []
    where: list[tuple[int, int, bool]] = []
    for li, item in enumerate(LS._items(SL.payload(doc))):
        text = SL.line_text(item) or ""
        _romanise("")
        wi, group = 0, 0
        for chunk, bg in _voices(text):
            at = None
            if bg:
                at = group
                group += 1
            for w, joined in _units(chunk):
                words.append(w)
                where.append((li, wi, joined, at))
                wi += 1
    return words, where


ADLIB = re.compile(r"\(([^()]*)\)")


def _voices(text: str) -> list[tuple[str, bool]]:
    """One line cut into (text, is an ad-lib) runs, so ad-libs are timed apart;
    a line that is only an ad-lib keeps it as the lead."""
    out: list[tuple[str, bool]] = []
    at = 0
    for m in ADLIB.finditer(text):
        if text[at:m.start()].strip():
            out.append((text[at:m.start()], False))
        if m.group(1).strip():
            out.append((m.group(1), True))
        at = m.end()
    if text[at:].strip():
        out.append((text[at:], False))
    if not any(not bg for _t, bg in out):
        return [(text, False)]
    return out or [(text, False)]


TRANSLATION = re.compile(
    r"(\btranslat|\btradu|\bübersetz|\bubersetz|\bvertaling|çeviri|ceviri"
    r"|tłumacz|tlumacz|fordítás|forditas|prijevod|превод|перевод|переклад"
    r"|翻訳|번역|翻译|譯|ترجمة|תרגום)", re.I)


def _same_artist(theirs: str, who: str) -> bool:
    """Two normalised names judged as one account or not; short names must
    match exactly, long ones may be fragments."""
    if not theirs or not who:
        return False
    if theirs == who:
        return True
    shorter, longer = (theirs, who) if len(theirs) <= len(who) else (who, theirs)
    if len(shorter) >= 3 and shorter in longer:
        return True
    # A short name passes when the rest is only account dressing: NF is
    # "NFrealmusic", whose Topic release was being sorted down as a cover.
    if longer.startswith(shorter):
        return _dressing(longer[len(shorter):])
    if longer.endswith(shorter):
        return _dressing(longer[:-len(shorter)])
    return False


ACCOUNT_WORDS = ("official", "offical", "real", "music", "vevo", "tv", "band",
                 "the", "channel", "hq", "records", "iam", "its", "thisis")


def _dressing(rest: str) -> bool:
    """Whether `rest` is nothing but ACCOUNT_WORDS run together."""
    if not rest:
        return True
    return any(rest.startswith(w) and _dressing(rest[len(w):])
               for w in ACCOUNT_WORDS)


def _bare(name: str) -> str:
    """A title without the parenthetical Spotify hangs off the end of it.

    "FE!N (feat. Playboi Carti)" searches worse than "FE!N" does, and the
    feature is in the artist field anyway.
    """
    out = re.sub(r"\s*[\(\[\{][^\)\]\}]*[\)\]\}]\s*", " ", name or "")
    out = re.sub(r"\s+-\s+(remaster|remastered|single|radio|album)\b.*$", "", out, flags=re.I)
    return out.strip() or (name or "").strip()


GENIUS_TRIES = 3
GENIUS_WAIT = 0.6


def _genius_hits(token: str, title: str, artist: str, timeout: float) -> list[dict]:
    """Genius search results for a song, plainly (not GR.search's romanisation
    hunt). `last_error` is set only when no query got through."""
    got, seen, spoke, bad = [], set(), False, ""
    first = _bare(title)
    lead = _bare(re.split(r"\s*[,&]\s*|\s+(?:feat|ft|with)\.?\s+", artist or "",
                          maxsplit=1)[0])
    for query in (f"{lead} {first}".strip(), f"{first} {lead}".strip(),
                  f"{first} {_bare(artist)}".strip(), first):
        url = f"{GR.API}/search?{urllib.parse.urlencode({'q': query})}"
        head = {"Authorization": f"Bearer {token}"} if token else {}
        hits = []
        for attempt in range(GENIUS_TRIES):
            try:
                js = json.loads(GR._get(url, head, timeout).decode("utf-8", "replace"))
                hits = (js.get("response") or {}).get("hits") or []
                spoke = True
            except Exception as exc:                     # noqa: BLE001
                hits, bad = [], GR.why(exc, timeout)
            if hits:
                break
            if attempt + 1 < GENIUS_TRIES:
                time.sleep(GENIUS_WAIT * (attempt + 1))
        for hit in hits:
            res = hit.get("result")
            if isinstance(res, dict) and res.get("id") and res["id"] not in seen:
                seen.add(res["id"])
                got.append(res)
    _genius_hits.last_error = "" if spoke else bad
    return got


_genius_hits.last_error = ""


# How many yt-dlp searches run at once. Each is a Python process of 50-100MB
# and a search used to start one per ask -- up to six -- for the few seconds
# it took. pool.map hands the answers back in the order they were asked, so
# holding the pool to three changes how long the searches take and nothing
# about what they find.
YTDLP_AT_ONCE = 3
ARTIST_MIN = 0.55
TITLE_MIN = 0.55


def _who(hit: dict) -> list[str]:
    """Every name Genius credits on a hit, whichever field it files them in."""
    out = [str((hit.get("primary_artist") or {}).get("name") or ""),
           str(hit.get("artist_names") or "")]
    for field in ("primary_artists", "featured_artists"):
        for who in hit.get(field) or []:
            if isinstance(who, dict) and who.get("name"):
                out.append(str(who["name"]))
    return [x for x in out if x.strip()]


def _artist_alike(artist: str, hit: dict) -> float:
    """How well the credits on `hit` match the artist Spotify names. 0..1.

    Every one of ours against every one of theirs, best pair wins. Ours are
    split too: Spotify hands over the whole credit as one string, and a song
    filed on Genius under the second name of four still is that song.
    """
    ours = [artist, _bare(artist)]
    ours += [p for p in re.split(r"\s*[,&]\s*|\s+(?:feat|ft|with)\.?\s+",
                                 artist, flags=re.I) if p.strip()]
    best = 0.0
    for mine in ours:
        for theirs in _who(hit):
            best = max(best, GR.similar(GR.key(_bare(mine)),
                                        GR.key(_bare(theirs))))
    return best


def _translation(hit: dict) -> bool:
    """Is this Genius' translation of the song rather than the song?"""
    if not isinstance(hit, dict):
        return False
    who = str((hit.get("primary_artist") or {}).get("name") or "")
    if re.match(r"\s*genius\b", who, re.I):
        return True
    fields = (str(hit.get("title") or ""), str(hit.get("full_title") or ""),
              str(hit.get("title_with_featured") or ""), who)
    return any(TRANSLATION.search(f) for f in fields)


def genius_doc(token: str, meta: dict, timeout: float = 8.0) -> dict | None:
    """An untimed document of Genius' words for this song, or None; the text
    only has to be right here. `last_error` tells a miss from a shut door."""
    genius_doc.last_error = ""
    title = str(meta.get("title") or "").strip()
    artist = str(meta.get("artist") or "").strip()
    if not title:
        return None
    try:
        hits = _genius_hits(token, title, artist, timeout)
    except Exception as exc:                             # noqa: BLE001
        genius_doc.last_error = GR.why(exc, timeout)
        return None
    genius_doc.last_error = _genius_hits.last_error
    best = None
    for hit in hits or []:
        if not GR.is_song(hit) or GR.is_romanisation(hit):
            continue
        got = hit.get("result") if isinstance(hit.get("result"), dict) else hit
        if _translation(got):
            continue
        sid = got.get("id")
        if not sid:
            continue
        tsim = GR.similar(GR.key(_bare(title)),
                          GR.key(_bare(str(got.get("title") or ""))))
        if tsim < TITLE_MIN:
            continue
        if not LS._same_cut(f"{got.get('title') or ''} "
                            f"{got.get('full_title') or ''}", title):
            continue
        asim = 1.0
        if artist:
            asim = _artist_alike(artist, got)
            if asim < ARTIST_MIN:
                continue
        score = tsim + asim
        if best is None or score > best[0]:
            best = (score, int(sid))
    if best is None:
        return None
    credit, links = "", []
    try:
        song = GR.song_of(token, best[1], timeout)
        credit, links = GR.credit_of(song), GR.credit_links(song)
    except Exception:                                    # noqa: BLE001
        credit, links = "", []
    try:
        marked = GR.voiced_lines(GR.lyrics_for(best[1], timeout=timeout,
                                               markup=True))
    except Exception:
        marked = []
    if not marked:
        try:
            plain = GR.clean_lines(GR.lyrics_for(best[1], timeout=timeout))
        except Exception as exc:                         # noqa: BLE001
            genius_doc.last_error = GR.why(exc, timeout)
            return None
        genius_doc.last_error = GR.lyrics_for.last_error
        marked = [{"text": ln, "who": ""} for ln in plain]
    if len(marked) < 2:
        return None
    flags = GR.sides(marked, main=artist)
    content = []
    for line, opposite in zip(marked, flags):
        item = {"Text": line["text"], "Type": "Vocal"}
        if opposite:
            item["OppositeAligned"] = True
        if line.get("who"):
            item["_who"] = line["who"]
        content.append(item)
    out = {"Type": "Static", "_timing": "genius", "Content": content}
    if credit:
        out["_words_by"] = credit
        if links:
            out["_words_links"] = links
    genius_doc.last_error = ""
    return out


genius_doc.last_error = ""


HOLD = 0.6

MIN_SYL = 0.02

# What a fetched copy is written at. It was the separator's rate, and the
# separator has gone; it stays because a file on disk has to be written at
# something and everything cached was written at this.
SEP_RATE = 44100

# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
LENGTH_TOL = 3.0
LENGTH_TOL_MINE = 10.0
ALT_VERSION = re.compile(
    r"\b(live|acoustic|cover|remix|instrumental|karaoke|nightcore|demo|"
    r"tribute|rehearsal|session|mashup|parody|sped[\s-]?up|slowed)\b", re.I)


FETCH_TRIES = 5
PIN_TRIES = 3


class Missing(RuntimeError):
    """A program this needs is not on the machine, said in the user's words."""


YTDLP_MISSING = ("yt-dlp is not installed — run setup, which offers it "
                 "(or: python -m pip install yt-dlp)")


def ytdlp() -> list[str]:
    """How to run yt-dlp here, as a command prefix: PATH, then this Python's
    Scripts folders, then the module. Raises Missing."""
    got = _ytdlp_cache.get("cmd")
    if got:
        return list(got)
    import importlib.util
    import sysconfig
    found = shutil.which("yt-dlp")
    if found:
        cmd = [found]
    else:
        cmd = []
        names = ("yt-dlp.exe", "yt-dlp") if os.name == "nt" else ("yt-dlp",)
        schemes = [None] + [x for x in sysconfig.get_scheme_names()
                            if x.endswith("_user")]
        for scheme in schemes:
            try:
                folder = (sysconfig.get_path("scripts", scheme) if scheme
                          else sysconfig.get_path("scripts"))
            except KeyError:
                continue
            hit = next((pathlib.Path(folder) / n for n in names
                        if folder and (pathlib.Path(folder) / n).is_file()), None)
            if hit:
                cmd = [str(hit)]
                break
        if not cmd:
            spec = importlib.util.find_spec("yt_dlp")
            if spec is None or not spec.origin:
                raise Missing(YTDLP_MISSING)
            # Wherever it was found -- site-packages, or this project's pylibs
            # -- the child is told, since it starts with neither path of ours.
            home = str(pathlib.Path(spec.origin).resolve().parent.parent)
            cmd = [_console_python(), "-c",
                   f"import sys; sys.path.insert(0, {home!r}); "
                   "import yt_dlp; yt_dlp.main()"]
    _ytdlp_cache["cmd"] = cmd
    return list(cmd)


_ytdlp_cache: dict = {}


def _console_python() -> str:
    """This Python, but the console one: the app runs under pythonw.exe on
    Windows, which has no standard streams of its own to hand yt-dlp's
    output back on."""
    exe = pathlib.Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        twin = exe.with_name("python.exe")
        if twin.is_file():
            return str(twin)
    return str(exe)


SEARCHES = ("scsearch", "ytsearch")
PREVIEW = 30.0
# YouTube's results page, videos only, most viewed first: it finds Topic
# releases a relevance search leaves out.
YT_BY_VIEWS = "https://www.youtube.com/results?search_query={}&sp=CAMSAhAB"


def find(query: str, length: float, tries: int = 8,
         artist: str = "", title: str = "") -> list[tuple[str, float]]:
    """Every search hit whose length matches, best first, metadata only: the
    artist's own uploads (looser tolerance), then SoundCloud, then YouTube.
    `find.near`."""
    find.near, find.seen, find.all, find.gated = None, 0, [], []
    find.missing = ""
    try:
        run = ytdlp()
    except Missing as e:
        find.missing = str(e)
        find.mine = {}
        return []
    who = GR.key(_bare(artist)) if artist else ""
    seen_urls: set[str] = set()
    rows: list[tuple[str, str]] = []
    bare = query.split(" ", 1)[1] if " " in query else ""
    asks = [("ytsearch", query, "views")]
    for where in SEARCHES:
        asks.append((where, query))
        if bare:
            asks.append((where, bare))
        if where == "ytsearch":
            asks.append((where, f"{query} audio"))
            if title and artist:
                # The release as streaming services carry it is "<artist> -
                # Topic"; this form, with "Topic" quoted, finds it.
                asks.append((where, f'{_bare(title)} - {artist} - "Topic"'))

    def ask_for(job: tuple) -> list[tuple[str, str]]:
        where, ask = job[0], job[1]
        if job[2:] == ("views",):
            opts = ["--playlist-end", str(tries)]
            what = YT_BY_VIEWS.format(urllib.parse.quote_plus(ask))
        else:
            opts, what = [], f"{where}{tries}:{ask}"
        cmd = [*run, "--dump-json", "--no-warnings", "--skip-download",
               "--no-playlist", "--flat-playlist", *opts,
               "--socket-timeout", str(int(SOCKET_WAIT)), "--", what]
        try:
            got = noconsole.run(cmd, capture_output=True, text=True,
                                timeout=120)
        except Exception:
            return []
        return [(where, row, job[2:] == ("views",))
                for row in got.stdout.splitlines()]

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(asks), YTDLP_AT_ONCE)) as pool:
        for got in pool.map(ask_for, asks):
            rows.extend(got)
    ids = []
    # Sorted by plays, the results page is the artist's biggest songs as much
    # as this one -- So Far So Fake is 237s too. Whatever ONLY that search
    # found has to name the song.
    by_views = {}
    for where, row, views in rows:
        with contextlib.suppress(ValueError, AttributeError):
            u = json.loads(row).get("webpage_url")
            by_views[u] = by_views.get(u, True) and views
    rows = [(where, row) for where, row, _views in rows]
    for where, row in rows:
        if where == "scsearch":
            with contextlib.suppress(ValueError, AttributeError):
                ids.append(str(json.loads(row).get("id") or ""))
    gated = _sc_gated(ids)
    want = GR.key(_bare(title)) if title else ""
    keep, near = [], None
    # Which uploads are Topic releases, from whichever search said so: the
    # same video can come back from several of the asks, and not every copy
    # of it carries the description that gives it away.
    released = set()
    for where, row in rows:
        try:
            hit = json.loads(row)
        except json.JSONDecodeError:
            continue
        if (where == "ytsearch" and str(hit.get("description") or "")
                .startswith("Provided to YouTube by")):
            released.add(hit.get("webpage_url"))
    for where, row in rows:
        try:
            hit = json.loads(row)
        except json.JSONDecodeError:
            continue
        dur = float(hit.get("duration") or 0)
        url = hit.get("webpage_url")
        if not dur or not url:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        if by_views.get(url) and want and want not in GR.key(
                _bare(str(hit.get("title") or ""))):
            continue
        if where == "scsearch" and str(hit.get("id") or "") in gated:
            find.gated.append((url, gated[str(hit.get("id"))]))
            continue
        if (where == "scsearch" and abs(dur - PREVIEW) < 0.5
                and length > PREVIEW * 1.5):
            continue
        find.seen += 1
        gap = abs(dur - length) if length else 0.0
        uploader = str(hit.get("uploader") or hit.get("channel") or "")
        # A Topic upload rarely says so in a flat search result -- the
        # uploader reads "slayr", not "slayr - Topic" -- but its description
        # is YouTube's own, and that always opens the same way.
        topic = where == "ytsearch" and (uploader.endswith(" - Topic")
                                         or url in released)
        # A Topic upload's title is the release's and nothing else, so here
        # a title that differs is a different song -- and the Topic search
        # brings back the artist's others: "Memories" at 206s, next to House
        # of Memories at 209s, on the same account, inside the tolerance.
        if topic and want and GR.key(_bare(str(hit.get("title") or ""))) != want:
            continue
        theirs = GR.key(_bare(re.sub(r" - Topic$", "", uploader)))
        mine = _same_artist(theirs, who)
        tol = LENGTH_TOL_MINE if mine else LENGTH_TOL
        # Somebody else's RELEASE of a song by this name is a cover, or a
        # different song: the Topic search brings back NateWantsToBattle's
        # King for a Day, at 236s like the original, for Pierce The Veil's.
        other = bool(topic and who and not mine)
        plays = hit.get("view_count") or hit.get("playback_count") or 0
        plays = plays if isinstance(plays, int) and plays > 0 else 0
        find.all.append({
            "url": url, "dur": dur, "where": where, "mine": mine,
            "topic": topic,
            "title": str(hit.get("title") or ""),
            "uploader": str(hit.get("uploader") or hit.get("channel") or ""),
            "alt": bool(ALT_VERSION.search(str(hit.get("title") or "")))
            or other, "plays": plays,
            "fits": not (length and gap > tol), "gap": gap})
        if length and gap > tol:
            if near is None or gap < near[0]:
                near = (gap, dur, str(hit.get("title") or "")[:60])
            continue
        alt = bool(ALT_VERSION.search(str(hit.get("title") or ""))) or other
        keep.append((gap, url, dur, mine, alt, where, topic and mine, plays))

    def rank(k):
        gap, url, _dur, mine, alt, where, topic, plays = k
        # The artist's Topic upload outranks everything; then far more plays,
        # counted in powers of ten so similar counts go by length.
        tier = -len(str(plays)) if plays else 0
        return (1 if alt else 0, 0 if mine else 1, 0 if topic else 1,
                SEARCHES.index(where), tier, round(gap, 1), gap, url)

    keep.sort(key=rank)
    if near:
        find.near = (near[1], near[2])
    find.mine = {k[1]: k[3] for k in keep}
    return [(k[1], k[2]) for k in keep]


find.near: tuple | None = None
find.missing = ""
find.seen = 0
find.all: list = []
find.mine: dict = {}
find.gated: list = []


GO_PLUS = "SoundCloud Go+ only"


def _sc_gated(ids: list[str]) -> dict[str, str]:
    """Which of these SoundCloud tracks cannot be downloaded (Go+), in one
    request; {} when the lookup fails."""
    ids = list(dict.fromkeys(i for i in ids if i.isdigit()))
    if not ids:
        return {}
    got = None
    with contextlib.suppress(Exception):
        got = LS._json(f"{LS.SC_API}/tracks?"
                       + LS._qs(ids=",".join(ids),
                                client_id=LS._sc_client_id()))
    if not isinstance(got, list):
        return {}
    out = {}
    for track in got:
        if not isinstance(track, dict):
            continue
        tid = str(track.get("id") or "")
        if track.get("policy") == "BLOCK":
            out[tid] = "blocked in this country"
            continue
        usable = [
            t for t in (track.get("media") or {}).get("transcodings") or []
            if isinstance(t, dict) and t.get("url")
            and not str(t.get("preset") or "").startswith("abr")
            and not str((t.get("format") or {}).get("protocol") or "")
            .startswith(("ctr-", "cbc-"))
            and not t.get("snipped") and "/preview/" not in str(t["url"])]
        if not usable:
            out[tid] = GO_PLUS
    return out


def why_none(length: float) -> str:
    """Why `find` came back empty, in the user's words.

    Reads what the last `find` left behind. Go+ copies are named, since a
    search that found the song only behind SoundCloud's paywall and one that
    found nothing at all send somebody to look in quite different places.
    """
    if find.missing:
        return find.missing
    go = sum(1 for _url, why in find.gated if why == GO_PLUS)
    gated = (f"{go} on SoundCloud {'was' if go == 1 else 'were'} Go+ only, "
             f"which nothing here can download" if go else "")
    if not find.seen:
        if go:
            return (f"the only copies found were on SoundCloud Go+, which "
                    f"nothing here can download ({go} of them), and YouTube "
                    f"had none")
        if find.gated:
            return f"the only copies found were {find.gated[0][1]}"
        return "nothing found for that search"
    if find.near:
        said = (f"nothing at the right length — wanted {length:.0f}s, and the "
                f"closest of {find.seen} was {find.near[0]:.0f}s "
                f"({find.near[1]})")
    else:
        said = (f"nothing at the right length — wanted {length:.0f}s, out of "
                f"{find.seen} found")
    return f"{said}; {gated}" if gated else said


AUDIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "fetched"
AUDIO_CAP_GB = 8.0
YT_CLIENTS = ("tv_simply", "android_vr")
HARD = (
    ("Sign in to confirm", "YouTube wants a sign-in for this one (bot check "
                           "— set $MILD_COOKIES to a browser to pass one)"),
    ("not a bot", "YouTube wants a sign-in for this one (bot check "
                  "— set $MILD_COOKIES to a browser to pass one)"),
    ("DRM protected", "SoundCloud streams this one through Go+ only — "
                       "signed in or not, yt-dlp cannot decrypt it"),
    ("Go+ song", "SoundCloud streams this one through Go+ only — "
                 "signed in or not, yt-dlp cannot decrypt it"),
    # Not a refusal, but just as final: yt-dlp needs ffmpeg to make a wav.
    ("ffmpeg not found", "ffmpeg is not installed — run setup, which offers it"),
    ("ffprobe and ffmpeg not found", "ffmpeg is not installed — run setup, "
                                     "which offers it"),
)
FETCH_RETRIES = 4
RETRY_WAIT = 2.0


def _kept(tid: str):
    """The copy kept for this track, touched so it counts as recently used."""
    got = AUDIO_DIR / f"{tid}.wav"
    if got.exists() and got.stat().st_size > 1024:
        with contextlib.suppress(Exception):
            os.utime(got)
        return got
    return None


def _keep(tid: str, path: str) -> None:
    """Keep this copy for next time, and stay under the cap."""
    with contextlib.suppress(Exception):
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, AUDIO_DIR / f"{tid}.wav")
        files = sorted(AUDIO_DIR.glob("*.wav"), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        while files and total > AUDIO_CAP_GB * 2**30:
            gone = files.pop(0)
            total -= gone.stat().st_size
            gone.unlink(missing_ok=True)


def _hard(said: str) -> str:
    """A refusal there is no point knocking twice on, in plain words."""
    return next((why for x, why in HARD if x in said), "")


LYRICS_DIR = pathlib.Path(__file__).resolve().parent.parent / "lyrics"
DECOY_MIN_WORDS = 20


def _cookies() -> list[str]:
    """What $MILD_COOKIES says to sign in with: a browser name or a cookies.txt
    path. Fixes YouTube's bot check, not SoundCloud Go+."""
    said = os.environ.get("MILD_COOKIES", "").strip()
    if not said:
        return []
    return (["--cookies", said] if os.path.exists(said)
            else ["--cookies-from-browser", said])


def _place(url: str) -> str:
    return "soundcloud" if "soundcloud.com" in url else "youtube"


def _named(url: str) -> str:
    """Short enough for a one-line reason, and still says which upload.

    A YouTube id is what comes after the `=`; a SoundCloud one is the last two
    path parts, account and slug, which is the readable half of the URL.
    """
    if _place(url) == "soundcloud":
        return "/".join(url.rstrip("/").split("/")[-2:])
    return url.rsplit("=", 1)[-1]


def _candidates(hits: list[tuple[str, float]],
                tries: int = FETCH_TRIES) -> list[tuple[str, float]]:
    """The few candidates to try, with one hit from whichever site is missing
    added at the end."""
    picked = list(hits[:tries])
    seen = {_place(url) for url, _dur in picked}
    for url, dur in hits[tries:]:
        if _place(url) not in seen:
            picked.append((url, dur))
            break
    return picked


def fetch(url: str, path: str) -> str | None:
    """Audio from `url` as 44.1kHz stereo wav at `path`, or None; `last_error`
    says why. Bot checks are not retried (YouTube gets one IPv4 try)."""
    fetch.last_error = ""
    # The url goes after "--", where nothing can read it as a flag. It comes
    # from yt-dlp's own search output or from the pins file, so it has never
    # arrived starting with a dash -- and the one place that would matter is
    # exactly the place nobody checks, because it takes a hostile search result
    # rather than a bug to get there.
    try:
        run = ytdlp()
    except Missing as e:
        fetch.last_error = str(e)
        return None
    base = ([*run, "-f", "bestaudio/best", "--no-playlist",
             "--no-warnings", "--quiet", "-x", "--audio-format", "wav",
             "--socket-timeout", str(int(SOCKET_WAIT)),
             "--postprocessor-args", f"ffmpeg:-ac 2 -ar {SEP_RATE}",
             "-o", path.rsplit(".", 1)[0] + ".%(ext)s"] + _cookies()
            + ["--", url])
    tube = "youtube.com" in url or "youtu.be" in url
    v4 = False
    try:
        for attempt in range(FETCH_RETRIES):
            # Extra flags go before the "--", or yt-dlp takes them for urls.
            extra = []
            if tube and attempt >= FETCH_RETRIES // 2:
                extra += ["--extractor-args",
                          "youtube:player_client=" + ",".join(YT_CLIENTS)]
            if v4:
                extra.append("--force-ipv4")
            cmd = base[:-2] + extra + base[-2:]
            try:
                _run_watched(cmd, path.rsplit(".", 1)[0])
                break
            except subprocess.CalledProcessError as again:
                said = (again.stderr or b"").decode("utf-8", "replace")
                # The bot check is scored per address, and yt-dlp prefers
                # IPv6: behind Cloudflare WARP the v6 exit was walled for every
                # video while the v4 one passed. One knock over IPv4 is worth it.
                if (tube and not v4 and attempt + 1 < FETCH_RETRIES
                        and any(x in said for x in ("Sign in to confirm",
                                                    "not a bot"))):
                    v4 = True
                    continue
                if _hard(said):
                    raise
                if attempt + 1 < FETCH_RETRIES and any(
                        x in said for x in ("403", "429", "Forbidden",
                                            "Too Many Requests", "timed out",
                                            "not available", "reloaded")):
                    time.sleep(RETRY_WAIT * (attempt + 1))
                    continue
                raise
    except subprocess.CalledProcessError as exc:
        said = (exc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        fetch.last_error = (said[-1].replace("ERROR: ", "") if said
                            else f"yt-dlp exited {exc.returncode}")
        fetch.last_error = _hard(fetch.last_error) or fetch.last_error
        return None
    except Exception as exc:
        fetch.last_error = f"{type(exc).__name__}: {exc}"
        return None
    if os.path.exists(path):
        return path
    fetch.last_error = "yt-dlp reported success but wrote nothing"
    return None


fetch.last_error = ""

# yt-dlp waits on a silent connection for as long as the system lets it,
# which is forever: a SoundCloud fragment that never arrives left the fetch
# "downloading…" until the ten-minute cap. These two turn that into an error
# that says what happened, in about a minute.
SOCKET_WAIT = 20.0
STALL_WAIT = 60.0


def _run_watched(cmd: list[str], stem: str, cap: float = 600.0) -> None:
    """Run a download, and stop it once nothing it writes has grown for a while.

    Raises CalledProcessError the way `run(check=True)` does, with the reason
    on stderr, so the caller's retry and reporting read it the same way.
    """
    import glob
    import tempfile
    with tempfile.TemporaryFile() as err:
        proc = noconsole.popen(cmd, stdout=subprocess.DEVNULL, stderr=err)
        began = moved = time.monotonic()
        size = -1
        why = ""
        while proc.poll() is None:
            time.sleep(0.5)
            now = time.monotonic()
            have = 0
            for f in glob.glob(glob.escape(stem) + ".*"):
                try:
                    have += os.path.getsize(f)
                except OSError:
                    pass
            if have != size:
                size, moved = have, now
            if now - moved > STALL_WAIT:
                why = (f"ERROR: the download stopped -- nothing arrived for "
                       f"{STALL_WAIT:.0f}s")
            elif now - began > cap:
                why = f"ERROR: the download took longer than {cap:.0f}s"
            if why:
                proc.kill()
                proc.wait()
                break
        err.seek(0)
        said = err.read()
    if why:
        raise subprocess.CalledProcessError(-9, cmd, stderr=said + why.encode())
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=said)


@contextlib.contextmanager
def fetched(query: str, length: float, where: str | None = None,
            artist: str = "", tid: str = "",
            words: list[str] | None = None,
            decoys: list[list[str]] | None = None,
            say: Callable[[str], None] | None = None):
    """A copy of the song for the `with` block, deleted after; yields a path or
    None. `last_error` says why; `words`/`decoys` are unused. `say` hears
    progress."""
    tmp = where or os.path.join(tempfile.gettempdir(),
                                f"mild-align-{os.getpid()}.wav")
    tell = say or (lambda _msg: None)
    got = None
    fetched.last_error = ""
    fetched.url = ""
    fetched.swapped = None
    fetched.margin = None
    fetched.doubted = None
    fetched.unverified = None
    try:
        saved = _kept(tid) if tid else None
        if saved:
            yield str(saved)
            return
        pinned = LS.pinned_source(tid) if tid else ""
        if pinned:
            for _try in range(PIN_TRIES):
                got = fetch(pinned, tmp)
                if not got:
                    continue
                fetched.url = pinned
                yield got
                return
            if got is None and not fetched.swapped:
                fetched.swapped = (pinned, fetch.last_error or "download failed")
                LS.pin_source(tid, "")
        tell("searching SoundCloud and YouTube…")
        title = (query[len(artist):].strip()
                 if artist and query.lower().startswith(artist.lower()) else "")
        hits = find(query, length, artist=artist, title=title)
        if not hits:
            fetched.last_error = why_none(length)
        why = []
        candidates = _candidates(hits)
        for n, (url, _dur) in enumerate(candidates, 1):
            tell(f"trying copy {n}/{len(candidates)} — {_named(url)}…")
            got = fetch(url, tmp)
            if not got:
                why.append(fetch.last_error or "download failed")
                continue
            if not find.mine.get(url, False):
                fetched.unverified = (
                    url, "not on the artist's own account, and nothing here "
                         "can listen to it to be sure")
            fetched.url = url
            if tid:
                LS.pin_source(tid, url)
                _keep(tid, got)
            break
        if hits and not got:
            fetched.last_error = (
                f"{len(hits)} copies at the right length, and "
                f"{'none of the ' + str(len(why)) if len(why) > 1 else 'the one'} "
                f"tried would download — "
                f"{'; '.join(dict.fromkeys(why))[:160] or 'no reason given'}")
        yield got
    finally:
        stem = tmp.rsplit(".", 1)[0]
        for leftover in (tmp, stem + ".webm", stem + ".m4a",
                         stem + ".mp3", stem + ".opus"):
            try:
                os.remove(leftover)
            except OSError:
                pass


fetched.last_error = ""
fetched.url = ""        # which upload the copy came from, when one did
fetched.swapped = None
fetched.margin = None
fetched.doubted = None


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
