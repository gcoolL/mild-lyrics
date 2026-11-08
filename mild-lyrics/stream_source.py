"""Songs Mild Lyrics plays itself without having the file: a catalogue for when
Spotify is not there (Deezer's public API), and a resolver that turns a track
into a stream (YouTube, through yt-dlp) and a Spotify id (for Spicy Lyrics).

Notes: docs/notes/mild-lyrics/home_page.md, "streaming".
"""
from __future__ import annotations

import base64
import collections
import concurrent.futures as CF
import csv
import functools
import hashlib
import io
import json
import pathlib
import re
import socket
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from PyQt6.QtCore import QObject, pyqtSignal

import autoplay as AP
import genres as GENRES
import home_data as HD
import lyric_sources as LS
import yt_captions as YC

UA = "MildLyrics/1.2 (+https://github.com/gcoolL/mild-lyrics)"
DZ = "https://api.deezer.com"
EMBED = "https://open.spotify.com/embed/track/"
DURATION_SLACK = 3.0          # seconds a stream may differ from the catalogue's length
DZ_PACE = (40, 5.0)           # Deezer allows 50 asks in 5s per address: at most this many, then wait
DZ_BG = 30                    # ...background asks stop here, so a page being looked at never waits (2026-10-27)
# any of these answering = a connection (YouTube Music too: the streams come from there)
NET_HOSTS = (("api.deezer.com", 443), ("1.1.1.1", 443), ("music.youtube.com", 443))

_dz_sent: collections.deque = collections.deque()
_dz_lock = threading.Lock()
_lane = threading.local()             # .bg: this thread's Deezer asks are background (home shelves, autoplay)


def in_lane(bg: bool, fn, *a, **k):
    """fn(*a, **k) with this thread's Deezer asks in the background lane or not."""
    was = getattr(_lane, "bg", False)
    _lane.bg = bg
    try:
        return fn(*a, **k)
    finally:
        _lane.bg = was


def _laned(fn):
    """fn for a pool thread, on the calling thread's lane."""
    bg = getattr(_lane, "bg", False)
    return lambda *a, **k: in_lane(bg, fn, *a, **k)


def _dz_pace() -> None:
    """Wait until one more Deezer ask stays under its quota (one autoplay fill was 41 in 4s);
    a background ask while it leaves DZ_PACE - DZ_BG for the page."""
    n, span = DZ_PACE
    if getattr(_lane, "bg", False):
        n = DZ_BG
    while True:
        with _dz_lock:
            now = time.monotonic()
            while _dz_sent and now - _dz_sent[0] > span:
                _dz_sent.popleft()
            if len(_dz_sent) < n:
                _dz_sent.append(now)
                return
            wait = span - (now - _dz_sent[-n])
        time.sleep(wait + 0.01)


def _get(url: str, data: bytes | None = None, timeout: float = 10.0, raw: bool = False):
    dz = url.startswith(DZ)
    if dz:
        _dz_pace()
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA if not raw else "Mozilla/5.0", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    if raw:
        return body.decode("utf-8", "replace")
    got = json.loads(body)
    if dz and isinstance(got, dict) and isinstance(got.get("error"), dict):
        # Deezer refuses (quota, bad id) with a 200: a failure, not an empty answer to keep
        raise OSError("Deezer: " + str(got["error"].get("message") or got["error"]))
    return got


def net_up(timeout: float = 4.0) -> bool:
    """Whether any connection out works at all (a bare address too, in case only DNS is down)."""
    for host in NET_HOSTS:
        try:
            socket.create_connection(host, timeout).close()
            return True
        except OSError:
            continue
    return False


class NetCheck(QObject):
    """net_up off the GUI thread; `done(up)` lands on the GUI thread."""
    done = pyqtSignal(bool)

    def ask(self) -> None:
        threading.Thread(target=lambda: self.done.emit(net_up()), daemon=True).start()


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = re.sub(r"[\u0300-\u036f]", "", s)              # "vämpp" is "vampp", not "va mpp"
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)
    s = re.sub(r"\b(feat|ft)\.?\b.*", " ", s)
    s = re.sub(r"['’‘ʼ`]", "", s)                     # "isn't" is "isnt", not "isn t"
    return re.sub(r"[^\w]+", " ", s).strip()


# ================================================================ Deezer
def _dz_track(t: dict, album: dict | None = None) -> dict | None:
    if not isinstance(t, dict) or not t.get("id"):
        return None
    al = t.get("album") or album or {}
    ar = t.get("artist") or {}
    names = [c.get("name") for c in (t.get("contributors") or []) if c.get("name")] or [ar.get("name", "")]
    return {"uri": f"deezer:track:{t['id']}", "uid": "", "name": t.get("title") or "",
            "sub": ", ".join(n for n in names if n),
            "artists": [{"name": ar.get("name", ""), "uri": f"deezer:artist:{ar['id']}" if ar.get("id") else ""}],
            "album": al.get("title", ""), "album_uri": f"deezer:album:{al['id']}" if al.get("id") else "",
            "art": al.get("cover_xl") or al.get("cover_big") or "", "ms": int(t.get("duration") or 0) * 1000,
            "plays": int(t.get("rank") or 0), "isrc": t.get("isrc") or "", "kind": "track",
            "clean": t.get("explicit_content_lyrics") == 3}     # Deezer's 3: the edited (clean) cut


def _dz_album(a: dict, artist: dict | None = None) -> dict:
    ar = a.get("artist") or artist or {}
    day = a.get("release_date") or ""
    year = day[:4]
    return {"uri": f"deezer:album:{a['id']}", "kind": "album", "name": a.get("title", ""),
            "sub": ar.get("name", "") + (f" · {year}" if year and ar.get("name") else year), "year": year,
            "art": a.get("cover_xl") or a.get("cover_big") or "", "type": (a.get("record_type") or "").lower(),
            "release": f"{day}T00:00:00" if day > time.strftime("%Y-%m-%d") else ""}   # out at local midnight


def _dz_artist(a: dict) -> dict:
    return {"uri": f"deezer:artist:{a['id']}", "kind": "artist", "name": a.get("name", ""), "sub": "Artist",
            "art": a.get("picture_xl") or a.get("picture_big") or "", "fans": int(a.get("nb_fan") or 0)}


def best_artist(artists: list, name: str):
    """The artist called `name`: spelt exactly that first, then the best-known of the names that
    only match without punctuation. Deezer lists "NF!" (48 fans) before NF (661k) for "NF"."""
    same = [a for a in artists if norm(a.get("name", "")) == norm(name)]
    if not same:
        return None
    return max(same, key=lambda a: (a.get("name", "").casefold() == (name or "").casefold(),
                                    int(a.get("fans") or 0)))


def spelt_like(hits: list, name: str, said):
    """The hit named `name`: spelt exactly, then differing in case or accents, then only without
    punctuation. YouTube Music's "Yves" came before "Yves!" for "Yves!", and norm() made them one."""
    def bare(s: str) -> str:
        s = unicodedata.normalize("NFKD", s or "").casefold()
        return " ".join("".join(ch for ch in s if not unicodedata.combining(ch)).split())
    for same in (lambda s: s == name, lambda s: bare(s) == bare(name), lambda s: norm(s) == norm(name)):
        got = next((h for h in hits if same(said(h))), None)
        if got is not None:
            return got
    return None


def _id(uri: str) -> str:
    return uri.rsplit(":", 1)[-1]


DZ_NOISE = re.compile(r"[\"“”]|…|\.{2,}|(?<!\S)-+(?!\S)")


def dz_query(q: str) -> str:
    """What Deezer is asked for a typed search: its parser reads quotes as a phrase, a lone dash as
    "not", and an ellipsis as a word, so "…a sign of the times..." matched Everything Suxxx alone."""
    q = re.sub(r"[’‘ʼ]", "'", q)
    return " ".join(DZ_NOISE.sub(" ", q).split()) or q


def dz_search(q: str) -> dict:
    q = dz_query(q)
    qq = urllib.parse.quote(q)
    with CF.ThreadPoolExecutor(3) as ex:
        get = _laned(_get)
        ft = ex.submit(get, f"{DZ}/search?q={qq}&limit=25")
        fa = ex.submit(get, f"{DZ}/search/artist?q={qq}&limit=12")
        fb = ex.submit(get, f"{DZ}/search/album?q={qq}&limit=12")
        tracks = [x for x in (_dz_track(t) for t in (ft.result().get("data") or [])) if x]
        artists = [_dz_artist(a) for a in (fa.result().get("data") or []) if a.get("id")]
        albums = [_dz_album(a) for a in (fb.result().get("data") or []) if a.get("id")]
    tracks = _plain_before_versions(q, _guests_of_twins(tracks))
    top = ""
    named = best_artist(artists, q)
    genre = genre_of(q)
    if genre and (named is None or named.get("fans", 0) < GENRE_OVER_FANS):
        got = dz_genre(genre, q)
        if got["tracks"]:
            if len(got["artists"]) < 4:                 # too few of its own: the names Deezer found
                got["artists"] += [a for a in artists if a["uri"] not in got["uris"]]
            return {"tracks": got["tracks"] + [t for t in tracks if t["uri"] not in got["uris"]],
                    "artists": got["artists"], "albums": albums, "playlists": [], "top": got["uri"],
                    "top_item": got["item"]}
    if named is not None:
        top = named["uri"]
        if sum(any(a.get("uri") == named["uri"] for a in t.get("artists") or []) for t in tracks[:5]) >= 2:
            tracks = _own_songs_first(tracks, named)
    elif tracks:
        said = _title_and_artist(q, tracks) or _catalogue_song(q, tracks)
        if said is not None:
            tracks = [t for t in tracks if t["uri"] != said["uri"]]
            tracks = [said] + [t for t in tracks if t is not said]
            have = {a["uri"] for a in artists}
            artists = [dict(a, kind="artist", sub="Artist", art=f"{DZ}/artist/{_id(a['uri'])}/image?size=xl")
                       for a in said.get("artists") or [] if a.get("uri") and a["uri"] not in have] + artists
        else:
            tracks, artists = _title_points_to_artists(q, tracks, artists)
        top = tracks[0]["uri"]
    return {"tracks": tracks, "artists": artists, "albums": albums, "playlists": [], "top": top}


GENRE_OVER_FANS = 200_000   # an artist named like the genre leads only past this many fans ("Metal" has 16k)
GENRE_LISTS = 3             # playlists fused into a genre's songs
GENRE_SONGS = 50


def genre_of(q: str) -> str:
    """The genre `q` names, as Deezer's playlists are asked for it, else ""."""
    k = " ".join(q.casefold().replace("’", "'").split())
    if k in GENRES.EXTRA:
        return GENRES.EXTRA[k]
    return k if k in GENRES.MUSICBRAINZ else ""


def dz_genre(genre: str, typed: str) -> dict:
    """A genre's songs: the Deezer playlists named for it (its editors' first), fused by rank so
    the songs several agree on lead. Searching "rock" found songs titled Rock, not rock."""
    words = norm(genre).split()
    got = _get(f"{DZ}/search/playlist?q={urllib.parse.quote(genre)}&limit=25").get("data") or []
    named = [p for p in got if p.get("id") and all(w in norm(p.get("title", "")).split() for w in words)
             and int(p.get("nb_tracks") or 0) >= 15]
    named.sort(key=lambda p: "deezer" not in ((p.get("user") or {}).get("name") or "").casefold())
    lists = []
    for p in named[:GENRE_LISTS]:
        try:
            lists.append(dz_playlist(f"deezer:playlist:{p['id']}")["tracks"][:GENRE_SONGS])
        except (OSError, ValueError, KeyError):
            continue
    tracks = [{k: v for k, v in t.items() if k != "_fused"} for t in AP.fuse(lists)][:GENRE_SONGS]
    count: dict = {}
    for t in tracks:
        for a in t.get("artists") or []:
            if a.get("uri"):
                count[a["uri"]] = count.get(a["uri"], (0, a))[0] + 1, a
    artists = [dict(a, kind="artist", sub="Artist", art=f"{DZ}/artist/{_id(a['uri'])}/image?size=xl")
               for n, a in sorted(count.values(), key=lambda x: -x[0]) if n >= 2][:12]
    name = typed.strip() if typed.strip().casefold() == genre else genre
    uri = "genre:" + genre
    item = {"uri": uri, "kind": "genre", "name": name[:1].upper() + name[1:], "sub": f"{len(tracks)} songs",
            "art": (tracks[0].get("art") if tracks else ""), "tracks": tracks}
    return {"uri": uri, "item": item, "tracks": tracks, "artists": artists,
            "uris": {t["uri"] for t in tracks} | {a["uri"] for a in artists}}


VERSION_TAG = re.compile(r"^(.*?\S)\s*(?:[\(\[]([^\)\]]*)[\)\]]|\s-\s(.*))$")


TWIN_READS = 12    # songs re-read per search to tell same-named versions apart


def _guests_of_twins(tracks: list) -> list:
    """Same title by the same lead: each re-read whole for its guests, which Deezer's search leaves out.
    Imagine Dragons' Take Me to the Beach came back four times, with Ado, Baker Boy, Jungeli and alone."""
    seen: dict = {}
    for t in tracks:
        k = (_song_title_key(t.get("name", "")), (t.get("artists") or [{}])[0].get("uri"))
        seen[k] = seen.get(k, 0) + 1
    twins = [t for t in tracks if seen[(_song_title_key(t.get("name", "")),
                                       (t.get("artists") or [{}])[0].get("uri"))] > 1][:TWIN_READS]
    if not twins:
        return tracks
    get = _laned(_get)
    try:
        with CF.ThreadPoolExecutor(4) as ex:
            full = dict(zip((t["uri"] for t in twins), ex.map(lambda t: get(f"{DZ}/track/{_id(t['uri'])}"), twins)))
    except (OSError, ValueError):
        return tracks
    out = []
    for t in tracks:
        got = _dz_track(full[t["uri"]]) if isinstance(full.get(t["uri"]), dict) else None
        out.append(dict(t, sub=got["sub"]) if got and got["sub"] else t)
    return out


def _plain_before_versions(q: str, tracks: list) -> list:
    """A remix or other version nobody typed goes after the plain song by the same artist.
    Deezer put "Do It (Yves Remix)" before underscores' own "Do It" for "do it underscores"."""
    typed = set(re.findall(r"\w+", q.casefold()))

    def split(t) -> tuple:
        name = re.sub(r"\s*[\(\[]\s*(?:feat|ft|featuring|with)\.?\s[^\)\]]*[\)\]]", "", t.get("name", ""), flags=re.I)
        m = VERSION_TAG.match(name)
        lead = (t.get("artists") or [{}])[0].get("uri")
        if m and not set(re.findall(r"\w+", (m.group(2) or m.group(3) or "").casefold())) <= typed:
            return _song_title_key(m.group(1)), lead, True
        return _song_title_key(name), lead, False
    keys = [split(t) for t in tracks]
    plain = {k[:2] for k in keys if not k[2]}
    out = [t for t, k in zip(tracks, keys) if not (k[2] and k[:2] in plain)]
    for t, k in zip(tracks, keys):
        if k[2] and k[:2] in plain:
            at = next(i for i, x in enumerate(out) if split(x) == (k[0], k[1], False))
            while at + 1 < len(out) and split(out[at + 1])[:2] == k[:2]:
                at += 1
            out.insert(at + 1, t)
    return out


def _title_and_artist(q: str, tracks: list):
    """The song `q` names as its title and one of its artists, in either order, best played first.
    "without you the kid laroi" led with Descape's "Without You (The Kid Laroi Cover)"."""
    qk = _song_title_key(q)
    best = None
    for t in tracks:
        name = _song_title_key(t.get("name", ""))
        m = VERSION_TAG.match(t.get("name", ""))
        names = {name, _song_title_key(m.group(1))} if m else {name}
        for a in t.get("artists") or []:
            ak = _song_title_key(a.get("name", ""))
            if ak and any(n and qk in (n + ak, ak + n) for n in names):
                if best is None or t.get("plays", 0) > best.get("plays", 0):
                    best = t
                break
    return best


CATALOGUE_RELEASES = 30   # releases read when a typed song is missing from Deezer's search


def _catalogue_song(q: str, tracks: list):
    """The song `q` names by an artist among the hits, read off that artist's releases: Deezer's
    index can miss a song outright ("lost al3jandro" found Loca; Lost is on Bury Me with My Gold)."""
    words = norm(q).split()
    seen = set()
    for t in tracks[:10]:
        ar = (t.get("artists") or [{}])[0]
        aw = norm(ar.get("name", "")).split()
        if not ar.get("uri") or ar["uri"] in seen or not aw or len(aw) >= len(words):
            continue
        seen.add(ar["uri"])
        if words[-len(aw):] == aw:
            rest = words[:-len(aw)]
        elif words[:len(aw)] == aw:
            rest = words[len(aw):]
        else:
            continue
        want = _song_title_key(" ".join(rest))
        if any(want in (_song_title_key(x.get("name", "")), _song_title_key(x.get("album", "")))
               for x in tracks if (x.get("artists") or [{}])[0].get("uri") == ar["uri"]):
            continue        # the index has it, or the words name one of its albums: nothing to look for
        try:
            albums = (_get(f"{DZ}/artist/{_id(ar['uri'])}/albums?limit=100").get("data") or [])
            albums = [a for a in albums if a.get("id")][:CATALOGUE_RELEASES]
            get = _laned(_get)
            with CF.ThreadPoolExecutor(4) as ex:
                lists = list(ex.map(lambda a: (a, get(f"{DZ}/album/{a['id']}/tracks?limit=100")), albums))
        except (OSError, ValueError):
            continue
        hits = []
        for a, got in lists:
            for x in got.get("data") or []:
                m = VERSION_TAG.match(x.get("title", ""))
                if _song_title_key(x.get("title", "")) == want:
                    hits.append((0, -int(x.get("rank") or 0), x, a))
                elif m and _song_title_key(m.group(1)) == want:
                    hits.append((1, -int(x.get("rank") or 0), x, a))
        if hits:
            _, _, x, a = min(hits, key=lambda h: h[:2])
            return _dz_track(x, a)
    return None


TITLE_ARTISTS = 2     # a name matched by songs of at most this many lead artists is one song's


def _title_points_to_artists(q: str, tracks: list, artists: list) -> tuple[list, list]:
    """A search that is one song's name ("nastywerk": "NASTYWERKKKK!" by femtanyl & ISSBROKIE):
    that song, then its artists' top songs, before the songs that only share a word with it.
    Only where few artists have a song called that, so "believer" is left alone."""
    qk = _song_title_key(q)
    if len(qk) < 4:
        return tracks, artists

    def close(t) -> bool:
        k = _song_title_key(t.get("name", ""))
        return k.startswith(qk) and len(qk) >= 0.6 * len(k)     # all that was typed, and most of the name
    hits = sorted((t for t in tracks if close(t)), key=lambda t: -t.get("plays", 0))
    leads = {(t.get("artists") or [{}])[0].get("uri") for t in hits}
    if not hits or len(leads) > TITLE_ARTISTS:
        return tracks, artists
    anchor = hits[0]
    try:
        full = _get(f"{DZ}/track/{_id(anchor['uri'])}")
        credited = [_dz_artist(c) for c in full.get("contributors") or [] if c.get("id")]
    except Exception:                                        # noqa: BLE001
        credited = []
    credited = credited or [dict(a, kind="artist", sub="Artist") for a in anchor.get("artists") or [] if a.get("uri")]
    lists = []
    for a in credited[:3]:
        try:
            lists.append(dz_top(a["uri"])["tracks"])
        except Exception:                                    # noqa: BLE001
            pass
    more = [x[i] for i in range(max([len(x) for x in lists] or [0])) for x in lists if i < len(x)]
    out, seen = [], set()
    for t in hits + more + tracks:
        k = (_song_title_key(t.get("name", "")), (t.get("artists") or [{}])[0].get("uri"))
        if t["uri"] not in seen and k not in seen:
            seen |= {t["uri"], k}
            out.append(t)
    have = {a["uri"] for a in credited}
    return out, credited + [a for a in artists if a.get("uri") not in have]


def _own_songs_first(tracks: list, artist: dict) -> list:
    """A search for an artist: their own songs first, by Apple Music's top songs, then the rest
    as Deezer had them. Deezer ranked "harvest sky" (Oklou's, underscores featured) first."""
    try:
        order = apple_top_songs(artist.get("name", ""))
    except Exception:                                        # noqa: BLE001
        order = []
    at = {t: i for i, t in reversed(list(enumerate(order)))}
    own, seen = [], set()
    for t in tracks:
        k = _song_title_key(t.get("name", ""))
        if (t.get("artists") or [{}])[0].get("uri") == artist["uri"] and k not in seen:
            seen.add(k)                  # another release of a title already led with goes with the rest
            own.append(t)
    own.sort(key=lambda t: at.get(_song_title_key(t.get("name", "")), len(at)))   # stable: Deezer's otherwise
    ids = {id(t) for t in own}
    return own + [t for t in tracks if id(t) not in ids]


def _song_title_key(title: str) -> str:
    """A title to compare across catalogues: a feat clause dropped, a remix or version kept."""
    t = re.sub(r"\s*[\(\[]\s*(?:feat|ft|featuring|with)\.?\s[^\)\]]*[\)\]]|\s+(?:feat|ft)\.?\s.*$", "",
               title or "", flags=re.I)
    return re.sub(r"[\W_]+", "", t.casefold())


def dz_album(uri: str) -> dict:
    a = _get(f"{DZ}/album/{_id(uri)}")
    out = _dz_album(a)
    ar = a.get("artist") or {}
    out.update(type=(a.get("record_type") or "album").lower(), label=a.get("label", ""),
               artists=[{"name": ar.get("name", ""), "uri": f"deezer:artist:{ar['id']}" if ar.get("id") else ""}],
               tracks=[x for x in (_dz_track(t, a) for t in ((a.get("tracks") or {}).get("data") or [])) if x])
    return out


def dz_artist(uri: str) -> dict:
    i = _id(uri)
    get = _laned(_get)
    with CF.ThreadPoolExecutor(4) as ex:
        fa, ft = ex.submit(get, f"{DZ}/artist/{i}"), ex.submit(get, f"{DZ}/artist/{i}/top?limit=10")
        fb, fr = ex.submit(get, f"{DZ}/artist/{i}/albums?limit=30"), ex.submit(get, f"{DZ}/artist/{i}/related?limit=12")
        a = fa.result()
        out = _dz_artist(a)
        out.update(header=out["art"], listeners=int(a.get("nb_fan") or 0), saved=False,
                   tracks=[x for x in (_dz_track(t) for t in (ft.result().get("data") or [])) if x],
                   albums=[_dz_album(x, a) for x in (fb.result().get("data") or []) if x.get("id")],
                   related=[_dz_artist(x) for x in (fr.result().get("data") or []) if x.get("id")])
    return out


def dz_country() -> dict:
    """Where Deezer places this connection, {"iso": "FR", "name": "France"}: no account, no Spotify."""
    got = _get(f"{DZ}/infos")
    return {"iso": got.get("country_iso") or "", "name": got.get("country") or ""}


def dz_country_chart() -> dict:
    """Deezer's chart for this country: the "Top France" playlist its Deezer Charts account keeps.
    A country without one gets the global chart, said in `sub`."""
    c = dz_country()
    want = f"Top {c['name']}"
    got = _get(f"{DZ}/search/playlist?q={urllib.parse.quote(want)}&limit=25")
    p = next((x for x in got.get("data") or [] if (x.get("title") or "").casefold() == want.casefold()
              and (x.get("user") or {}).get("name") == "Deezer Charts"), None)
    if p is None:
        return dict(dz_playlist("deezer:playlist:chart"), uri="deezer:playlist:country",
                    sub=f"Deezer’s global chart: it keeps none for {c['name'] or 'this country'}")
    return dict(dz_playlist(f"deezer:playlist:{p['id']}"), uri="deezer:playlist:country", name=want,
                sub=f"Deezer’s chart for {c['name']}")


SZ_RISING = "https://www.shazam.com/services/charts/csv/discovery/{}/"


def _dz_song(artist: str, title: str) -> dict | None:
    """Deezer's copy of one song known by name: same title (norm, a tag after it allowed), first artist,
    and no other cut (remix, live...) than the name says."""
    who = norm(re.split(r",|&|\bfeat\.?|\bx\b", artist)[0])
    got = _get(f"{DZ}/search?q={urllib.parse.quote(dz_query(f'{artist} {title}'))}&limit=10")
    want, named = norm(title), {w.lower() for w in OTHER_CUT.findall(title)}
    for t in (_dz_track(x) for x in got.get("data") or []):
        if not t or who not in norm(t["sub"]) or {w.lower() for w in OTHER_CUT.findall(t["name"])} - named:
            continue                    # a remix or live cut the chart did not name is another song
        if norm(t["name"]) == want or norm(TAG_TAIL.sub("", t["name"])) == want:
            return t
    return None


def sz_rising() -> dict:
    """Shazam's Discovery chart for this country (songs rising by Shazam lookups over 7 days;
    no global one), each as Deezer's copy. Songs Deezer lacks are left out, said in `sub`."""
    c = dz_country()
    slug = re.sub(r"[^a-z]+", "-", norm(c["name"])).strip("-")
    text = _get(SZ_RISING.format(slug), raw=True)
    songs = [(r[1], r[2]) for r in csv.reader(io.StringIO(text.lstrip("\ufeff")))
             if len(r) >= 3 and r[0].strip().isdigit()][:50]
    if not songs:
        raise ValueError("no Shazam chart for " + (c["name"] or "this country"))
    with CF.ThreadPoolExecutor(3) as ex:
        found = list(ex.map(_laned(lambda s: _dz_song(*s)), songs))
    tracks = [t for t in found if t]
    gone = len(songs) - len(tracks)
    return {"uri": "deezer:playlist:viral", "name": "Rising on Shazam", "owner": "Shazam", "mine": False, "art": "",
            "sub": f"Shazam’s rising songs in {c['name']}" + (f" ({gone} not on Deezer left out)" if gone else ""),
            "total": len(tracks), "tracks": tracks}


def dz_playlist(uri: str) -> dict:
    i = _id(uri)
    if i == "country":
        return dz_country_chart()
    if i == "viral":
        return sz_rising()
    if i == "chart":
        got = _get(f"{DZ}/chart/0/tracks?limit=50")
        return {"uri": uri, "name": "Top songs", "sub": "Deezer’s global chart", "owner": "Deezer", "mine": False,
                "art": "", "total": len(got.get("data") or []),
                "tracks": [x for x in (_dz_track(t) for t in (got.get("data") or [])) if x]}
    p = _get(f"{DZ}/playlist/{i}")
    return {"uri": uri, "name": p.get("title", ""), "sub": p.get("description", ""),
            "owner": (p.get("creator") or {}).get("name", ""), "mine": False,
            "art": p.get("picture_xl") or "", "total": int(p.get("nb_tracks") or 0),
            "tracks": [x for x in (_dz_track(t) for t in ((p.get("tracks") or {}).get("data") or [])) if x]}


def dz_radio(uri: str) -> dict:
    """Deezer's radio for an artist: their songs and ones like them, about 25."""
    got = _get(f"{DZ}/artist/{_id(uri)}/radio?limit=40")
    return {"uri": uri, "tracks": [x for x in (_dz_track(t) for t in (got.get("data") or [])) if x]}


def dz_top(uri: str) -> dict:
    """An artist's top songs alone: one ask, where the artist page is four."""
    got = _get(f"{DZ}/artist/{_id(uri)}/top?limit=10")
    return {"uri": uri, "tracks": [x for x in (_dz_track(t) for t in (got.get("data") or [])) if x]}


def dz_related(uri: str) -> dict:
    """The artists Deezer relates to this one: one ask."""
    got = _get(f"{DZ}/artist/{_id(uri)}/related?limit=12")
    return {"uri": uri, "related": [_dz_artist(x) for x in (got.get("data") or []) if x.get("id")]}


def dz_feed() -> list:
    got = _get(f"{DZ}/chart/0/playlists?limit=8")
    items = [{"uri": f"deezer:playlist:{p['id']}", "kind": "playlist", "name": p.get("title", ""),
              "sub": f"By {(p.get('user') or {}).get('name') or 'Deezer'} · {p.get('nb_tracks', 0)} songs",
              "art": p.get("picture_xl") or "", "colour": ""} for p in (got.get("data") or []) if p.get("id")]
    return [{"title": "Popular playlists", "picks": True, "items": items}] if items else []


class Deezer(HD.Spot):
    """The same keys and shapes as Spot, answered from Deezer. Reads only."""
    PAGE_READER = True

    def __init__(self, art_url=lambda u: u) -> None:
        super().__init__(lambda js: js(), art_url)

    def want(self, key: str, js, keep: float | None = None, first: bool = False) -> None:
        """An ask no page is waiting on (not `first`) goes in the background lane."""
        super().want(key, lambda: in_lane(not first, js), keep=keep, first=first)

    def feed(self):
        self.want("feed", dz_feed, keep=3600)

    def liked(self, n: int = 0, keep=None):
        pass

    def shelf(self, which: str):
        pass

    def playlist(self, uri: str, keep: float = 600):
        self.want("pl:" + uri, lambda: dz_playlist(uri), keep=keep, first=True)

    def album(self, uri: str):
        fn = sp_album if uri.startswith("spotify:") else dz_album
        self.want("album:" + uri, lambda: fn(uri), keep=1800, first=True)

    def artist(self, uri: str, first: bool = True):
        self.want("artist:" + uri, lambda: dz_artist(uri), keep=1800, first=first)

    def upcoming(self, name: str, aid: str = "", first: bool = False):
        self.want("upcoming:" + norm(name), lambda: upcoming_kept(name, aid), keep=6 * 3600, first=first)

    def chart_uri(self, which: str) -> str:
        """Without Spotify: Deezer's global and country charts, and Shazam's rising songs for Viral 50."""
        return {"Your country": "deezer:playlist:country", "Viral 50": "deezer:playlist:viral"}.get(
            which, "deezer:playlist:chart")

    def chart(self, which: str):
        self.playlist(self.chart_uri(which), keep=3600)

    def search(self, q: str):
        self.want_only("search:" + q, lambda: dz_search(q), keep=600)

    def lookup(self, q: str, first: bool = False):
        self.want("search:" + q, lambda: dz_search(q), keep=86400, first=first)

    def radio(self, uri: str):
        self.want("radio:" + uri, lambda: dz_radio(uri), keep=1800)

    def top(self, uri: str):
        self.want("top:" + uri, lambda: dz_top(uri), keep=1800)

    def related(self, uri: str):
        self.want("related:" + uri, lambda: dz_related(uri), keep=1800)


def apple_face(name: str) -> dict:
    """An artist's picture on Apple Music by name, {} when it has no one called that.
    Asked directly, not through LS._amp, so a miss here is not blamed on Apple's lyrics."""
    tok = LS._apple_token()
    if not tok:
        raise OSError("no Apple Music key")
    req = urllib.request.Request(
        f"{LS.APPLE_AMP}/search?types=artists&limit=5&term={urllib.parse.quote(name)}",
        headers={"Authorization": "Bearer " + tok, "Origin": "https://music.apple.com",
                 "Referer": "https://music.apple.com/", "User-Agent": LS.APPLE_UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        got = json.loads(r.read())
    for a in (((got.get("results") or {}).get("artists") or {}).get("data") or []):
        at = a.get("attributes") or {}
        if norm(at.get("name", "")) == norm(name) and (at.get("artwork") or {}).get("url"):
            return {"art": LS.apple_art(at["artwork"], 1000)}
    return {}


@functools.lru_cache(maxsize=64)
def apple_top_songs(name: str) -> tuple:
    """The artist's top songs on Apple Music, as _song_title_key titles, most played first; () if Apple
    has no one called that. Raises when Apple cannot be asked."""
    tok = LS._apple_token()
    if not tok:
        raise OSError("no Apple Music key")
    head = {"Authorization": "Bearer " + tok, "Origin": "https://music.apple.com",
            "Referer": "https://music.apple.com/", "User-Agent": LS.APPLE_UA}

    def ask(path: str) -> dict:
        req = urllib.request.Request(LS.APPLE_AMP + path, headers=head)
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    found = ask(f"/search?types=artists&limit=5&term={urllib.parse.quote(name)}")
    a = spelt_like(((found.get("results") or {}).get("artists") or {}).get("data") or [], name,
                   lambda a: (a.get("attributes") or {}).get("name", ""))
    if a is None:
        return ()
    got = ask(f"/artists/{a['id']}/view/top-songs?limit=30")
    return tuple(_song_title_key((s.get("attributes") or {}).get("name", "")) for s in got.get("data") or [])


def dz_face(name: str) -> dict:
    """An artist's picture and Deezer page by name, {} when Deezer has no one called that."""
    got = _get(f"{DZ}/search/artist?q={urllib.parse.quote(name)}&limit=5")
    a = best_artist([_dz_artist(a) for a in got.get("data") or [] if a.get("id")], name)
    return {k: v for k, v in a.items() if k in ("uri", "art")} if a else {}


class Faces(QObject):
    """Artist pictures for names known only from the play log, kept on disk:
    Apple Music's, else Deezer's.

    The Artists tab asked a full catalogue search per name through the pages' one
    reader thread, so two dozen pictures arrived one by one, and again every start.
    """
    done = pyqtSignal()
    MISS_KEEP = 7 * 86400          # s: a name neither knew is asked again after this
    V = 2                          # 1 was Deezer only

    def __init__(self, path: pathlib.Path) -> None:
        super().__init__()
        self.path = path
        try:
            self.known: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.known = {}
        if self.known.get("_v") != self.V:
            self.known = {"_v": self.V}
        self._asked: set[str] = set()
        self._pool = CF.ThreadPoolExecutor(4)
        self._lock = threading.Lock()

    def get(self, name: str) -> dict | None:
        """{"uri", "art"}, {} if there is none, None while it is looked for."""
        k = name.lower()
        got = self.known.get(k)
        if got is not None and (got.get("art") or time.time() - got.get("t", 0) < self.MISS_KEEP):
            return got
        if k not in self._asked:
            self._asked.add(k)
            self._pool.submit(in_lane, True, self._look, name)
        return None

    def _look(self, name: str) -> None:
        first = re.split(r"\s+(?:&|x|and|with)\s+", name, maxsplit=1, flags=re.I)[0]
        got, failed = {}, 0
        for who in dict.fromkeys((name, first)):            # "Jennifer Lopez & David Guetta", logged as one
            for look in (apple_face, dz_face):
                try:
                    got = look(who)
                except Exception:                            # noqa: BLE001
                    failed += 1
                    continue
                if got:
                    break
            if got:
                break
        if not got and failed:
            return                                          # not a miss, unreachable: asked again next start
        with self._lock:
            self.known[name.lower()] = dict(got, t=time.time())
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.known), encoding="utf-8")
            except OSError:
                pass
        self.done.emit()


def dz_gain(t: dict) -> float | None:
    """Deezer's `gain` for a player track: its loudness in dB (about -16 quiet to -4 loud), None if
    Deezer has no such song. Only /track/<id> carries it, not radio, top or search rows."""
    title, artist = t.get("title") or "", (t.get("artist") or "").split(",")[0].strip()
    uri = t.get("uri") or ""
    paths = [f"/track/{uri.rsplit(':', 1)[-1]}"] if uri.startswith("deezer:track:") else []
    if t.get("isrc"):
        paths.append(f"/track/isrc:{t['isrc']}")
    for path in paths:
        try:
            got = _get(DZ + path)
        except OSError as e:
            if "no data" not in str(e):
                raise
            continue
        return float(got["gain"]) if got.get("gain") else None
    if not title or not artist:
        return None
    q = urllib.parse.quote(f'artist:"{artist}" track:"{title}"')
    ms = float(t.get("ms") or 0)
    for r in _get(f"{DZ}/search?limit=10&q={q}").get("data") or []:
        if norm(r.get("title_short") or r.get("title") or "") == norm(title) \
                and norm(artist) in norm((r.get("artist") or {}).get("name", "")) \
                and (not ms or abs(float(r.get("duration") or 0) * 1000 - ms) <= DURATION_SLACK * 1000):
            got = _get(f"{DZ}/track/{r['id']}")
            return float(got["gain"]) if got.get("gain") else None
    return None


class Loudness(QObject):
    """Songs' loudness (dz_gain) for autoplay's order, kept on disk; `done` when one lands."""
    done = pyqtSignal()
    MISS_KEEP = 30 * 86400         # s: a song Deezer did not have is asked again after this

    def __init__(self, path: pathlib.Path) -> None:
        super().__init__()
        self.path = path
        try:
            self.known: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.known = {}
        self._asked: set[str] = set()
        self._pool = CF.ThreadPoolExecutor(2)
        self._lock = threading.Lock()

    @staticmethod
    def key(t: dict) -> str:
        return norm(t.get("title") or "") + "|" + norm((t.get("artist") or "").split(",")[0])

    def get(self, t: dict) -> float | None:
        """dB, or None while it is looked for or when Deezer has none."""
        k = self.key(t)
        got = self.known.get(k)
        if got is not None and (got.get("g") is not None or time.time() - got.get("t", 0) < self.MISS_KEEP):
            return got.get("g")
        if k not in self._asked and k != "|":
            self._asked.add(k)
            self._pool.submit(in_lane, True, self._look, k, dict(t))
        return None

    def _look(self, k: str, t: dict) -> None:
        try:
            g = dz_gain(t)
        except Exception:                                    # noqa: BLE001
            self._asked.discard(k)                           # unreachable, not a miss: asked again later
            return
        with self._lock:
            self.known[k] = {"g": g, "t": round(time.time())}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.known), encoding="utf-8")
            except OSError:
                pass
        if g is not None:
            self.done.emit()


# ================================================================ YouTube
def yt_search(q: str, clean) -> dict:
    """YouTube's own results, as songs: anything uploaded, not only what a catalogue carries."""
    with _ytdl({"extract_flat": "in_playlist"}) as y:
        got = y.extract_info(f"ytsearch20:{q}", download=False)
    tracks = []
    for e in got.get("entries") or []:
        vid, dur = e.get("id"), float(e.get("duration") or 0)
        if not vid or not dur or dur > 20 * 60:
            continue
        raw, channel = e.get("title") or "", re.sub(r"\s*-\s*Topic$|VEVO$", "", e.get("channel") or e.get("uploader") or "")
        title, artist = song_of_video(raw, channel, clean)
        thumbs = e.get("thumbnails") or []
        # the song and its artist, as every other row shows them; the uploader too where it isn't the artist
        same = re.sub(r"\W", "", norm(channel)) == re.sub(r"\W", "", norm(artist))
        sub = artist if not channel or same else f"{artist} · {channel}"
        tracks.append({"uri": f"youtube:video:{vid}", "uid": "", "name": title, "sub": sub,
                       "song": title, "song_by": artist,
                       "artists": [{"name": artist, "uri": ""}], "album": "", "album_uri": "",
                       "art": (thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"),
                       "ms": int(dur * 1000), "plays": int(e.get("view_count") or 0), "kind": "track", "yt": vid,
                       "video": e.get("title") or ""})
    return {"tracks": tracks, "artists": [], "albums": [], "playlists": [], "top": ""}


COVER_BITS = re.compile(r"\s*[\(\[][^)\]]*\b(cover|remix|version|live|lyrics?|audio|video|visuali[sz]er|"
                        r"official|mv|m/v|ft\.?|feat\.?)\b[^)\]]*[\)\]]", re.I)


def song_of_video(raw: str, channel: str, clean) -> tuple[str, str]:
    """The song a video is of, for its lyrics: the window's cleaner, then what covers add."""
    title, artist = clean(raw, channel)
    title = COVER_BITS.sub("", title)
    title = re.sub(r"\s+(by|ft\.?|feat\.?)\s+.*$", "", title, flags=re.I)
    title = re.sub(r"\s*\|.*$", "", title).strip(" -–|")
    title = re.sub(r"\s+(cover|remix|acoustic|live)$", "", title, flags=re.I).strip() or raw
    return title, artist


class YouTube(HD.Spot):
    """YouTube searches for the search page's YouTube tab."""

    def __init__(self, clean) -> None:
        super().__init__(lambda js: js(), lambda u: u)
        self.clean = clean

    def search(self, q: str):
        self.want_only("search:" + q, lambda: yt_search(q, self.clean), keep=1800)

    def radio(self, vid: str):
        self.want("radio:youtube:" + vid, lambda: yt_radio(vid, self.clean), keep=1800)

    def video_of(self, title: str, artist: str):
        self.want(f"mv:{title}|{artist}", lambda: yt_video_of(title, artist, self.clean), keep=86400)

    def artist_top(self, name: str):
        self.want("top:youtube:" + name, lambda: yt_artist_top(name), keep=86400)


# ============================================================== resolver
def _match_rows(rows: list, title: str, artist: str, ms: float, album: str = "") -> str:
    """The search row that is this song: by ISRC, or by name and first artist, within DURATION_SLACK.
    Of those, ISRC rows first, then the song's own album before a compilation carrying the same
    recording -- 1-800-273-8255 came back on a Various Artists album before Logic's."""
    want_t, want_a, want_al = norm(title), norm(artist.split(",")[0]), norm(album)
    best = None
    for n, r in enumerate(rows):
        tid = (r.get("uri") or "").rsplit(":", 1)[-1]
        if not tid or not (r.get("uri") or "").startswith("spotify:track:"):
            continue
        if ms and r.get("ms") and abs(r["ms"] - ms) > DURATION_SLACK * 1000:
            continue
        if not r.get("isrc") and not (norm(r.get("name", "")) == want_t and want_a in norm(r.get("sub", ""))):
            continue
        other_album = bool(want_al) and norm(r.get("album", "")) != want_al
        rank = (not r.get("isrc"), bool(r.get("compilation")), other_album, n)
        if best is None or rank < best[0]:
            best = (rank, tid)
    return best[1] if best else ""


MB = "https://musicbrainz.org/ws/2"
MB_UA = "MildLyrics/1.2 (https://github.com/gcoolL/mild-lyrics)"
_mb_lock = threading.Lock()
_mb_last = [0.0]
SPOTIFY_TRACK = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?track/([A-Za-z0-9]{22})")
SPOTIFY_ALBUM = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?album/([A-Za-z0-9]{22})")
SPOTIFY_ARTIST = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?artist/([A-Za-z0-9]{22})")
ARTISTS_FILE: pathlib.Path | None = None     # name -> Spotify artist id, kept (the Resolver sets where)
_artist_ids: dict = {}
_artist_lock = threading.Lock()
ARTIST_AGAIN = 7 * 86400.0                   # an artist MusicBrainz has no Spotify link for: ask in a week
UPCOMING_FILE: pathlib.Path | None = None   # artist -> its upcoming releases (the home page sets where)
UPCOMING_AGAIN = 86400.0                     # each artist asked once a day
_upcoming: dict = {}
_upcoming_lock = threading.Lock()


def _mb(path: str) -> dict:
    """One MusicBrainz request, never more than one a second (its rate limit)."""
    with _mb_lock:
        wait = 1.05 - (time.monotonic() - _mb_last[0])
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(f"{MB}/{path}", headers={"User-Agent": MB_UA, "Accept": "application/json"})
        try:
            for attempt in (0, 1, 2):
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        return json.loads(r.read())
                except urllib.error.HTTPError as e:
                    if e.code not in (429, 503) or attempt == 2:
                        raise
                    time.sleep(2.5 * (attempt + 1))    # busy (counted per address, not per app): pause, again
        finally:
            _mb_last[0] = time.monotonic()


def _embed(kind: str, sid: str) -> dict:
    html = _get(f"https://open.spotify.com/embed/{kind}/{sid}", timeout=8, raw=True)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]


def sp_album(uri: str) -> dict:
    """A Spotify album from its public embed page, for while Spotify is away; it carries
    a pre-release's moment, and its unannounced tracks as locked "Track 3" rows."""
    e = _embed("album", uri.rsplit(":", 1)[-1])
    imgs = [i for i in (e.get("visualIdentity") or {}).get("image") or [] if i.get("url")]
    art = max(imgs, key=lambda i: i.get("maxWidth") or 0)["url"] if imgs else ""
    by = (e.get("subtitle") or "").replace("\xa0", " ")
    when = ((e.get("releaseDate") or {}).get("isoString") or "")
    tracks = [{"uri": t["uri"], "uid": "", "name": t.get("title", ""), "sub": t.get("subtitle", "") or by,
               "artists": [{"name": n.strip(), "uri": ""} for n in (t.get("subtitle") or by).split(",") if n.strip()],
               "album": e.get("name", ""), "album_uri": e.get("uri", uri), "art": art,
               "ms": int(t.get("duration") or 0), "locked": not t.get("isPlayable") and not t.get("duration")}
              for t in e.get("trackList") or [] if (t.get("uri") or "").startswith("spotify:track:")]
    return {"uri": e.get("uri", uri), "name": e.get("name", ""), "year": when[:4], "type": e.get("type", "album"),
            "label": "", "art": art, "release": when if e.get("isPreRelease") else "",
            "artists": [{"name": n.strip(), "uri": ""} for n in by.split(",") if n.strip()], "tracks": tracks}


def upcoming(name: str, aid: str = "") -> list[dict]:
    """An artist's announced releases not out yet, as album tiles with `release`: Spotify's public
    artist page (the exact moment), else Apple Music's pre-releases (a day, so local midnight)."""
    try:
        aid = aid or spotify_artist_id(name)
        it = (((_sp_state("artist/" + aid).get("entities") or {}).get("items") or {})
              .get("spotify:artist:" + aid) or {}) if aid else {}
    except Exception:                                        # noqa: BLE001
        it = {}
    if it:
        d = ((it.get("preReleaseV2") or {}).get("data")) or {}
        when = (d.get("preReleaseEndDateTime") or {}).get("isoString") or ""
        if not (d.get("uri") and when):
            return []
        srcs = [s for s in (d.get("coverArt") or {}).get("sources") or [] if s.get("url")]
        return [{"uri": d["uri"], "kind": "album", "name": d.get("name", ""), "sub": name, "by": name, "release": when,
                 "art": max(srcs, key=lambda s: s.get("width") or 0)["url"] if srcs else "",
                 "type": (d.get("contentTypeName") or "album").lower()}]
    return apple_upcoming(name)


def upcoming_kept(name: str, aid: str = "") -> list[dict]:
    """upcoming(), kept a day on disk: the home page's Coming soon asks about many artists at each start."""
    key = norm(name)
    with _upcoming_lock:
        if not _upcoming and UPCOMING_FILE is not None:
            try:
                _upcoming.update(json.loads(UPCOMING_FILE.read_text(encoding="utf-8")))
            except Exception:                                # noqa: BLE001
                pass
        was = _upcoming.get(key)
    if was and time.time() - float(was.get("t") or 0) < UPCOMING_AGAIN:
        return was.get("rows") or []
    rows = upcoming(name, aid)
    with _upcoming_lock:
        _upcoming[key] = {"t": time.time(), "rows": rows}
        if UPCOMING_FILE is not None:
            try:
                UPCOMING_FILE.parent.mkdir(parents=True, exist_ok=True)
                UPCOMING_FILE.write_text(json.dumps(_upcoming), encoding="utf-8")
            except OSError:
                pass
    return rows


def apple_upcoming(name: str) -> list[dict]:
    """Apple Music's pre-releases by the artist called `name`; Apple has no page here, so no uri."""
    hdr = {"Authorization": "Bearer " + LS._apple_token(), "Origin": "https://music.apple.com",
           "Referer": "https://music.apple.com/", "User-Agent": LS.APPLE_UA}
    amp = lambda path: json.loads(urllib.request.urlopen(urllib.request.Request(LS.APPLE_AMP + path, headers=hdr),
                                                         timeout=10).read())
    got = amp(f"/search?types=artists&limit=5&term={urllib.parse.quote(name)}")
    who = next((a for a in ((got.get("results") or {}).get("artists") or {}).get("data") or []
                if norm((a.get("attributes") or {}).get("name", "")) == norm(name)), None)
    if who is None:
        return []
    today = time.strftime("%Y-%m-%d")
    out = []
    for a in amp(f"/artists/{who['id']}/albums?limit=25&sort=-releaseDate").get("data") or []:
        at = a.get("attributes") or {}
        day = at.get("releaseDate") or ""
        if at.get("isPrerelease") and day > today:
            out.append({"uri": "", "kind": "album", "name": re.sub(r" - (Single|EP)$", "", at.get("name", "")),
                        "sub": name, "by": name, "release": f"{day}T00:00:00", "type": "album",
                        "art": LS.apple_art(at["artwork"], 600) if at.get("artwork") else ""})
    return out


def _sp_state(path: str) -> dict:
    """The data behind one of Spotify's public pages (its initialState), no token needed."""
    html = _get("https://open.spotify.com/" + path, timeout=10, raw=True)
    m = re.search(r'<script id="initialState" type="text/plain">([^<]+)</script>', html)
    return json.loads(base64.b64decode(m.group(1))) if m else {}


def spotify_artist_id(name: str) -> str:
    """An artist's Spotify id: kept from before, else MusicBrainz's link for the artist
    (artists carry it far more often than recordings do)."""
    key = norm(name)
    if not key:
        return ""
    with _artist_lock:
        if not _artist_ids and ARTISTS_FILE is not None:
            try:
                _artist_ids.update(json.loads(ARTISTS_FILE.read_text(encoding="utf-8")))
            except Exception:                                # noqa: BLE001
                pass
        known = _artist_ids.get(key)
    if known and (known.get("id") or time.time() - float(known.get("t") or 0) < ARTIST_AGAIN):
        return known.get("id", "")
    aid = ""
    got = _mb("artist?fmt=json&limit=5&query=" + urllib.parse.quote(f'artist:"{name}"'))
    for a in got.get("artists") or []:
        if norm(a.get("name", "")) != key:
            continue
        for rel in _mb(f"artist/{a['id']}?fmt=json&inc=url-rels").get("relations") or []:
            m = SPOTIFY_ARTIST.search(((rel.get("url") or {}).get("resource")) or "")
            if m:
                aid = m.group(1)
                break
        break
    with _artist_lock:
        _artist_ids[key] = {"id": aid, "t": time.time()}
        if ARTISTS_FILE is not None:
            try:
                ARTISTS_FILE.write_text(json.dumps(_artist_ids), encoding="utf-8")
            except OSError:
                pass
    return aid


TWIN_SLACK = 1.0     # seconds: a sync carried to another pressing must still line up


def wants_clean(t: dict) -> bool:
    """Whether a song is asked as its clean cut: Deezer's mark, or the title saying so."""
    return bool(t.get("clean")) or bool(LS.CLEAN_MARK.search(t.get("title", "")))


def explicit_twin(sid: str) -> str:
    """The explicit Spotify pressing of `sid` (same name, same length) where `sid` is not one;
    "" where it is, or none is found. Its own album's name first, then the artist page's order."""
    tr = _track_page(sid)
    if ((tr.get("contentRating") or {}).get("label") or "") == "EXPLICIT":
        return ""
    name, ms = (tr.get("name") or "").strip().lower(), (tr.get("duration") or {}).get("totalMilliseconds") or 0
    aid = ((((tr.get("firstArtist") or {}).get("items") or [{}])[0]).get("uri") or "").rsplit(":", 1)[-1]
    if not (name and ms and aid):
        return ""
    same = lambda n, dur: (n or "").strip().lower() == name and abs(float(dur or 0) - ms) <= TWIN_SLACK * 1000
    d = (((_sp_state("artist/" + aid).get("entities") or {}).get("items") or {})
         .get("spotify:artist:" + aid) or {}).get("discography") or {}
    for it in (d.get("topTracks") or {}).get("items") or []:
        t = it.get("track") or {}
        if same(t.get("name"), (t.get("duration") or {}).get("totalMilliseconds")) \
                and (t.get("contentRating") or {}).get("label") == "EXPLICIT":
            return (t.get("uri") or "").rsplit(":", 1)[-1]
    own = ((tr.get("albumOfTrack") or {}).get("uri") or "")
    stem = re.sub(r"\W+", " ", ((tr.get("albumOfTrack") or {}).get("name") or "").lower()).split()[:1]
    rels: list = []
    for sec in ("popularReleasesAlbums", "albums", "singles"):
        for r in (d.get(sec) or {}).get("items") or []:
            for x in ((r.get("releases") or {}).get("items") if "releases" in r else [r]) or []:
                if x.get("uri") and x["uri"] != own and x.get("type") != "COMPILATION" \
                        and all(y["uri"] != x["uri"] for y in rels):
                    rels.append(x)
    rels.sort(key=lambda x: re.sub(r"\W+", " ", (x.get("name") or "").lower()).split()[:1] != stem)
    for x in rels[:8]:
        for t in _embed("album", x["uri"].rsplit(":", 1)[-1]).get("trackList") or []:
            if t.get("isExplicit") and same(t.get("title"), t.get("duration")):
                return (t.get("uri") or "").rsplit(":", 1)[-1]
    return ""


def _compilation(release: dict) -> bool:
    return "Compilation" in ((release.get("release-group") or {}).get("secondary-types") or [])


VERSION_WORDS = re.compile(r"\b(remix|mix|edit|live|acoustic|instrumental|sped|slowed|extended|"
                           r"demo|cover|karaoke|unplugged|reprise|nightcore|8d|a[\s-]?capp?ella)\b")


def versions(title: str) -> set:
    """The words that make a cut another version of the song: "(LUCA LUSH Remix)" is not "Alone"."""
    return set(VERSION_WORDS.findall((title or "").lower()))


def _track_page(sid: str) -> dict:
    """The track behind Spotify's public page for `sid`: name, artists, playability, albumOfTrack."""
    return ((_sp_state("track/" + sid).get("entities") or {}).get("items") or {}).get("spotify:track:" + sid) or {}


def song_key(title: str, artist: str) -> str:
    """The id a song with no Spotify id is known by: the window's song_key, local_player._key."""
    return hashlib.sha1(f"{title} {artist}".encode("utf-8")).hexdigest()[:22]


def spotify_id(title: str, artist: str, album: str = "", ms: float = 0, trouble: list | None = None,
               clean: bool = False, look_ahead: bool = False) -> str:
    """The Spotify track id Spicy Lyrics' search names `exact` for a song known by name; with
    `trouble` set, empty means "not known yet", not "not on Spotify". One request a song."""
    import lyric_sources as LS
    try:
        return LS.spicy_track_id(title, artist, album, (ms or 0) / 1000.0, clean, look_ahead)
    except LS.SpicyError as e:
        if trouble is not None:
            trouble.append("spicy")
        _said(f"[spotify id] {title}: {e}"[:300])
        return ""


_SAID: set = set()


def _said(msg: str) -> None:
    """A lookup step that could not ask, once per kind of error, to the log (stderr)."""
    kind = msg.split(": ", 1)[-1][:60]
    if kind not in _SAID:
        _SAID.add(kind)
        print(msg, file=sys.stderr, flush=True)


def spotify_id_of(t: dict, trouble: list | None = None, clean: bool = False,
                  look_ahead: bool = False) -> str:
    """spotify_id by the song's own catalogue name first, then by Apple's where that differs.
    Only the catalogue's own album is sent: Apple's can be a compilation's, which the search
    then picks (Empire Ants on Cupid's Playlist, 2026-11-05)."""
    trouble = trouble if trouble is not None else []
    names = [(t.get("src_title") or t.get("title", ""), t.get("src_artist") or t.get("artist", ""),
              t.get("src_album") or ""),
             (t.get("title", ""), t.get("artist", ""), "")]
    seen = set()
    for title, artist, album in names:
        k = (norm(title), norm(artist.split(",")[0]))
        if not title or k in seen:
            continue
        seen.add(k)
        sid = spotify_id(title, artist, album, t.get("ms") or 0, trouble, clean, look_ahead)
        if sid or trouble:
            return sid                       # refused: not asked again by the other name
    return ""


def _ytdl(opts: dict):
    import yt_dlp
    import music_video as MV
    base = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    if time.time() < MV.V4_ONLY[0]:
        base["source_address"] = "0.0.0.0"              # IPv4: YouTube flagged the IPv6 address
    return yt_dlp.YoutubeDL({**base, **opts})


AUDIO_FMT = "bestaudio[ext=m4a]/bestaudio[protocol^=http]/bestaudio"
# no HLS/DASH manifests: audio plays from the https file, and the m3u8 alone took ~1.1s a lookup
AUDIO_OPTS = {"format": AUDIO_FMT, "extractor_args": {"youtube": {"skip": ["hls", "dash"]}}}
_AUDIO_YDL = threading.local()


def _audio_ytdl():
    """This thread's kept YoutubeDL for audio lookups: its extractor keeps YouTube's player
    script, which a new one downloads again each lookup (0.5-1.1s, measured 2026-11-03)."""
    import music_video as MV
    v4 = time.time() < MV.V4_ONLY[0]
    kept = getattr(_AUDIO_YDL, "y", None)
    if kept is None or kept[0] != v4:
        if kept is not None:
            try:
                kept[1].close()
            except Exception:                            # noqa: BLE001
                pass
        kept = _AUDIO_YDL.y = (v4, _ytdl(AUDIO_OPTS))
    return kept[1]


def recase(theirs: str, ours: str) -> str:
    """Apple's words in the song's own casing: Apple title-cases everything ("Ugly"), where
    the artist's release, Deezer and YouTube Music all write "ugly"."""
    if not ours or not theirs:
        return theirs or ours
    squash = lambda s: re.sub(r"[\W_]+", "", s.casefold())
    if squash(theirs) == squash(ours):
        return ours                     # only case and punctuation differ ("Isn't It Obvious"): the release's
    own = {squash(w): w for w in re.findall(r"\w[\w'’]*", ours)}
    return re.sub(r"\w[\w'’]*", lambda m: own.get(squash(m.group(0)), m.group(0)), theirs)


_FEAT = re.compile(r"\s*[\(\[]\s*(?:feat|ft|featuring|with)\.?\s+([^\)\]]+)[\)\]]"
                   r"|\s+(?:feat|ft|featuring)\.?\s+(.+)$", re.I)


def drop_credited_feat(title: str, artist: str) -> str:
    """"Psychoboost feat danny brown" by "Jane Remover, Danny Brown" -> "Psychoboost": a featured
    name the credits already carry is said once. Kept when any name in it is not credited."""
    credited = {norm(a) for a in re.split(r",|&", artist or "") if norm(a)}

    def cut(m):
        names = [norm(n) for n in re.split(r",|&|\band\b", m.group(1) or m.group(2)) if norm(n)]
        return "" if names and all(n in credited for n in names) else m.group(0)
    return _FEAT.sub(cut, title or "").strip() or title


class YouTubeBlocked(RuntimeError):
    """YouTube answered "confirm you're not a bot": every upload fails alike until it lifts."""


def yt_blocked() -> float:
    """Seconds until YouTube is asked again (0 when it may be); shared with music videos."""
    import music_video as MV
    return max(0.0, MV.BLOCKED[0] - time.time())


def _audio(video: str) -> tuple[str, float, float]:
    """(stream url, seconds long, unix time it stops working)."""
    url = video if video.startswith("http") else "https://music.youtube.com/watch?v=" + video
    if ".bandcamp.com/track/" in url:
        import pasted_links                  # yt-dlp no longer reads Bandcamp's pages (2026-10)
        return pasted_links.bandcamp_audio(url)
    import music_video as MV
    if yt_blocked():
        raise YouTubeBlocked("YouTube asked to confirm we are not a bot")
    v4 = time.time() < MV.V4_ONLY[0]
    try:
        info = _audio_ytdl().extract_info(url, download=False)
    except ImportError:
        return _audio_cli(url)
    except Exception as e:                               # noqa: BLE001
        if not MV._blocked(e, v4):
            raise
        try:
            info = _audio_ytdl().extract_info(url, download=False)   # once more, over IPv4 (see MV._blocked)
        except Exception as e2:                          # noqa: BLE001
            MV._blocked(e2, True)
            if yt_blocked():
                raise YouTubeBlocked("YouTube asked to confirm we are not a bot") from e2
            raise
    if info.get("id"):
        YC.LINKS[info["id"]] = YC.links_of(info)      # its captions, for the lyrics on its clock
    stream = info.get("url") or ""
    exp = re.search(r"[?&]expire=(\d+)", stream)
    return stream, float(info.get("duration") or 0), float(exp.group(1)) if exp else time.time() + 3600


def save_stream(url: str, folder: pathlib.Path, name: str) -> str:
    """The stream Mild Lyrics is playing, saved whole into `folder` for the editor: the same
    recording as heard, and no YouTube lookup (the link is already signed). Its path."""
    import urllib.parse
    mime = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("mime", [""])[0]
    ext = {"audio/mp4": ".m4a", "audio/webm": ".webm", "audio/mpeg": ".mp3"}.get(mime, ".m4a")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip(" -"))[:120] or "song")
    path = path.with_name(path.name + ext)
    tmp = path.with_name(path.name + ".part")
    # googlevideo paces a request with no Range to ~32KB/s (100s a song); "bytes=0-" comes at full speed
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-"})
    with urllib.request.urlopen(req, timeout=20) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    if tmp.stat().st_size < 32 * 1024:
        tmp.unlink(missing_ok=True)
        raise OSError("the stream came back nearly empty")
    tmp.replace(path)
    return str(path)


def _audio_cli(url: str) -> tuple[str, float, float]:
    import local_align
    import noconsole
    import music_video as MV
    v4 = ["-4"] if time.time() < MV.V4_ONLY[0] else []
    out = noconsole.run(local_align.ytdlp() + v4 + ["-f", AUDIO_FMT, "--extractor-args", "youtube:skip=hls,dash", "--print", "url",
                                               "--print", "duration", "--", url],
                        capture_output=True, text=True, timeout=60).stdout.split()
    if len(out) < 2:
        raise RuntimeError("yt-dlp found no audio")
    exp = re.search(r"[?&]expire=(\d+)", out[0])
    return out[0], float(out[1] or 0), float(exp.group(1)) if exp else time.time() + 3600


# YouTube Music's own search, "Songs" only: Art Tracks, the label's upload of the
# release the streaming services carry (MUSIC_VIDEO_TYPE_ATV), not a music video.
YTM_SEARCH = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"
YTM_SONGS = "EgWKAQIIAWoMEA4QChADEAQQCRAF"
YTM_VIDEOS = "EgWKAQIQAWoMEA4QChADEAQQCRAF"
YTM_CLIENT = {"clientName": "WEB_REMIX", "clientVersion": "1.20241023.01.00", "hl": "en"}
OTHER_CUT = re.compile(r"\b(live|acoustic|remix|instrumental|karaoke|demo|slowed|sped up|reverb|"
                       r"version|edit|mix|cover|nightcore|8d|a[\s-]?capp?ella)\b", re.I)
# somebody else's recording of it, said in the artist or the album: "METEORA: Tribute to Linkin Park"
NOT_THEIRS = re.compile(r"\b(tribute|karaoke|in the style of|originally performed|made famous|"
                        r"cover(?:s|ed)?|lullaby|lullabies|piano versions?|string quartet|8[- ]?bit)\b", re.I)
# what may follow a release's name: "Song - 2011 Remaster" is the song, "Song 2" is not
TAG_TAIL = re.compile(r"\s+[-–—~～/|]\s.*$")
PICK_V = 7                  # saved uploads picked before an earlier rule are picked again (v2 took a tribute act,
                            # v3 a clean copy over the explicit one, v4 live uploads at heard lengths, v5 an a cappella cut,
                            # v6 the clean copy where the explicit one was off the first page)
# Uploads that are not the recording, for audio: unlike the music video's NOT_IT, "audio" and
# "lyrics" uploads stay (they carry the studio track). A word the asked title has is allowed.
NOT_RECORDING = ("live", "acoustic", "cover", "remix", "instrumental", "karaoke", "nightcore", "demo",
                 "tribute", "rehearsal", "sessions?", "mashup", "parody", r"sped[\s-]?up", "slowed", "reverb",
                 "8d", "reaction", "performance", "unplugged", "tiny desk", "concert", "festival", "tour",
                 "big weekend", "live lounge", "bbc", "radio 1", "glastonbury", "coachella", "lollapalooza",
                 "in studio", "interview", "teaser", "trailer", r"choreograph\w*", "dance practice", r"a[\s-]?capp?ella")


def _credits(artists: str) -> set[str]:
    return {n for n in (norm(x) for x in re.split(r",|&|\bfeat\.?|\bft\.?|\bwith\b|\bx\b|\band\b", artists or "")) if n}


def _feat_credits(title: str) -> set[str]:
    """The names a title's "(feat. X)" credits, as _credits spells them."""
    return {n for m in LS.FEATURING.finditer(title or "") for n in _credits(m.group(1) or m.group(2))}


def _credited(who: str, artists: str) -> bool:
    """Whether `who` is one of the credited names, not merely inside one ("...Tribute to Linkin Park")."""
    return who in _credits(artists) or who == norm(artists)


def _ytm_rows(q: str, params: str = YTM_SONGS) -> list[dict]:
    body = json.dumps({"context": {"client": YTM_CLIENT}, "query": q, "params": params}).encode()
    req = urllib.request.Request(YTM_SEARCH, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
        "Origin": "https://music.youtube.com", "Referer": "https://music.youtube.com/"})
    with urllib.request.urlopen(req, timeout=10) as r:
        got = json.loads(r.read())
    found = []

    def walk(o):
        if isinstance(o, dict):
            if "musicResponsiveListItemRenderer" in o:
                found.append(o["musicResponsiveListItemRenderer"])
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(got)
    out = []
    for it in found:
        vid = (it.get("playlistItemData") or {}).get("videoId") or ""
        cols = [((c.get("musicResponsiveListItemFlexColumnRenderer") or {}).get("text") or {}).get("runs") or []
                for c in it.get("flexColumns") or []]
        if not vid or len(cols) < 2:
            continue
        title = "".join(r.get("text", "") for r in cols[0])
        parts = [r.get("text", "") for r in cols[1]]
        segs = "".join(parts).split(" • ")
        dur = segs[-1].strip() if segs and re.fullmatch(r"\d+:\d{2}(:\d{2})?", segs[-1].strip()) else ""
        secs = 0
        for x in dur.split(":") if dur else []:
            secs = secs * 60 + int(x)
        out.append({"id": vid, "title": title, "artist": segs[0] if segs else "",
                    "album": segs[1] if len(segs) > 2 else "", "secs": secs,
                    "atv": "MUSIC_VIDEO_TYPE_ATV" in json.dumps(it),
                    "omv": "MUSIC_VIDEO_TYPE_OMV" in json.dumps(it),
                    "explicit": "MUSIC_EXPLICIT_BADGE" in json.dumps(it)})
    return out


YTM_NEXT = "https://music.youtube.com/youtubei/v1/next?prettyPrint=false"


def yt_radio(vid: str, clean=None) -> dict:
    """YouTube Music's radio for one song (its "Start radio", RDAMVM<id>): about 50 songs
    from co-listening, no account, the song itself left out. Art Tracks, and with `clean` official
    videos as the song they are of, with no video id, for the resolver to find its Art Track."""
    body = json.dumps({"context": {"client": YTM_CLIENT}, "videoId": vid, "playlistId": "RDAMVM" + vid,
                       "isAudioOnly": True}).encode()
    req = urllib.request.Request(YTM_NEXT, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
        "Origin": "https://music.youtube.com", "Referer": "https://music.youtube.com/"})
    with urllib.request.urlopen(req, timeout=10) as r:
        got = json.loads(r.read())
    rows = []

    def walk(o):
        if isinstance(o, dict):
            if "playlistPanelVideoRenderer" in o:
                rows.append(o["playlistPanelVideoRenderer"])
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(got)
    if not rows:
        raise ValueError("no radio")            # a refusal or a changed page: not kept as "no songs"

    def page(run: dict) -> str:
        return (((run.get("navigationEndpoint") or {}).get("browseEndpoint") or {})
                .get("browseEndpointContextSupportedConfigs") or {}) \
            .get("browseEndpointContextMusicConfig", {}).get("pageType", "")
    tracks = []
    for it in rows:
        v = it.get("videoId") or ""
        kind = json.dumps(it.get("navigationEndpoint") or {})
        mv = clean is not None and "MUSIC_VIDEO_TYPE_OMV" in kind
        if not v or v == vid or not (mv or "MUSIC_VIDEO_TYPE_ATV" in kind):
            continue
        runs = (it.get("longBylineText") or {}).get("runs") or []
        artists = [r.get("text", "") for r in runs if page(r) == "MUSIC_PAGE_TYPE_ARTIST"] \
            or ["".join(r.get("text", "") for r in runs).split(" • ")[0]]
        album = next((r.get("text", "") for r in runs if page(r) == "MUSIC_PAGE_TYPE_ALBUM"), "")
        title = "".join(r.get("text", "") for r in (it.get("title") or {}).get("runs") or [])
        secs = 0
        for x in "".join(r.get("text", "") for r in (it.get("lengthText") or {}).get("runs") or []).split(":"):
            secs = secs * 60 + int(x) if x.strip().isdigit() else secs
        thumbs = (it.get("thumbnail") or {}).get("thumbnails") or []
        by = ", ".join(a for a in artists if a)
        if mv:
            title = song_of_video(title, artists[0], clean)[0]
            v, secs = "", 0                     # the video's length is not the song's
        tracks.append({"uri": f"youtube:video:{v}" if v else "", "uid": "", "name": title, "sub": by,
                       "song": title, "song_by": by, "artists": [{"name": a, "uri": ""} for a in artists],
                       "album": album, "album_uri": "",
                       "art": thumbs[-1].get("url", "") if thumbs else f"https://i.ytimg.com/vi/{v}/hqdefault.jpg",
                       "ms": secs * 1000, "plays": 0, "kind": "track", "yt": v})
    return {"uri": "youtube:radio:" + vid, "tracks": tracks}


def yt_video_of(title: str, artist: str, clean) -> dict:
    """{"vid": the song's official music video on YouTube Music, or ""}."""
    want, who = norm(title), norm(artist.split(",")[0])
    for r in _ytm_rows(f"{title} {artist}", YTM_VIDEOS):
        if r["omv"] and _credited(who, r["artist"]) and norm(song_of_video(r["title"], r["artist"], clean)[0]) == want:
            return {"vid": r["id"]}
    return {"vid": ""}


YTM_ARTISTS = "EgWKAQIgAWoKEAkQChAFEAMQBA%3D%3D"
YTM_BROWSE = "https://music.youtube.com/youtubei/v1/browse?prettyPrint=false"


def _ytm(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(dict(body, context={"client": YTM_CLIENT})).encode(), headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0",
        "Origin": "https://music.youtube.com", "Referer": "https://music.youtube.com/"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _find(o, key: str, out: list) -> list:
    """Every `key` object in a YouTube Music answer, in order."""
    if isinstance(o, dict):
        if key in o:
            out.append(o[key])
            return out
        for v in o.values():
            _find(v, key, out)
    elif isinstance(o, list):
        for v in o:
            _find(v, key, out)
    return out


def plays_of(text: str) -> int:
    """'35M plays' -> 35000000; YouTube Music rounds its counts."""
    m = re.match(r"\s*([\d.,]+)\s*([KMB]?)", text or "", re.I)
    if not m:
        return 0
    n = float(m.group(1).replace(",", "") or 0)
    return int(n * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2).upper()])


def yt_artist_top(name: str) -> dict:
    """An artist's top songs on YouTube Music, most played first: the artist page's five carry
    their plays ("35M plays", in `plays_text`), and its Top songs playlist gives the order past
    them and each song's length. The artist is the search hit spelt `name`, else none."""
    def cols(it):
        return [((c.get("musicResponsiveListItemFlexColumnRenderer") or {}).get("text") or {}).get("runs") or []
                for c in it.get("flexColumns") or []]

    def text(runs):
        return "".join(r.get("text", "") for r in runs)
    hits = []
    for it in _find(_ytm(YTM_SEARCH, {"query": name, "params": YTM_ARTISTS}), "musicResponsiveListItemRenderer", []):
        c = cols(it)
        b = ((it.get("navigationEndpoint") or {}).get("browseEndpoint") or {}).get("browseId", "")
        if c and b.startswith("UC"):
            hits.append((text(c[0]), b))
    bid = (spelt_like(hits, name, lambda h: h[0]) or ("", ""))[1]
    if not bid:
        return {"uri": "youtube:top:" + name, "tracks": []}
    page = _ytm(YTM_BROWSE, {"browseId": bid})
    shelf = next((sh for sh in _find(page, "musicShelfRenderer", [])
                  if text((sh.get("title") or {}).get("runs") or []).lower() in ("top songs", "songs")), None)
    if shelf is None:
        return {"uri": "youtube:top:" + name, "tracks": []}

    def row(it) -> dict | None:
        vid = (it.get("playlistItemData") or {}).get("videoId") or ""
        c = cols(it)
        if not vid or len(c) < 2 or "MUSIC_VIDEO_TYPE_ATV" not in json.dumps(it.get("overlay") or c[0]):
            return None
        artists = [r.get("text", "") for r in c[1] if (r.get("navigationEndpoint") or {}).get("browseEndpoint")] \
            or [text(c[1]).split(" • ")[0]]
        rest = [text(x) for x in c[2:]]
        plays = next((x for x in rest if x.lower().endswith(("plays", "play"))), "")
        album = next((x for x in rest if x and x != plays), "")
        fixed = (it.get("fixedColumns") or [{}])[0].get("musicResponsiveListItemFixedColumnRenderer") or {}
        dur = text((fixed.get("text") or {}).get("runs") or []).strip()
        secs = 0
        for x in dur.split(":") if re.fullmatch(r"\d+:\d{2}(:\d{2})?", dur) else []:
            secs = secs * 60 + int(x)
        thumbs = ((it.get("thumbnail") or {}).get("musicThumbnailRenderer") or {}).get("thumbnail", {}).get("thumbnails") or []
        art = re.sub(r"=w\d+-h\d+", "=w544-h544", thumbs[-1].get("url", "")) if thumbs else ""
        by = ", ".join(a for a in artists if a)
        return {"uri": f"youtube:video:{vid}", "uid": "", "name": text(c[0]), "sub": by, "song": text(c[0]),
                "song_by": by, "artists": [{"name": a, "uri": ""} for a in artists], "album": album,
                "album_uri": "", "art": art or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", "ms": secs * 1000,
                "plays": plays_of(plays), "plays_text": plays, "kind": "track", "yt": vid}
    top = [r for r in (row(it["musicResponsiveListItemRenderer"]) for it in shelf.get("contents") or []
                       if "musicResponsiveListItemRenderer" in it) if r]
    more = ((shelf.get("bottomEndpoint") or {}).get("browseEndpoint") or {}).get("browseId", "")
    if more:
        try:
            full = [r for r in (row(it) for it in _find(_ytm(YTM_BROWSE, {"browseId": more}),
                                                        "musicResponsiveListItemRenderer", [])) if r]
        except (OSError, ValueError):
            full = []
        seen = {t["yt"]: t for t in top}
        for t in full:
            got = seen.get(t["yt"])
            if got is not None:
                got["ms"] = got["ms"] or t["ms"]
            elif len(top) < 20:
                top.append(t)
    return {"uri": "youtube:top:" + name, "tracks": top}


def release_of(title: str, artist: str, length: float = 0, album: str = "", clean: bool = False,
               also: float = 0) -> list[str]:
    """The release itself on YouTube Music: same name, same artist, same length to 2s.

    A cut the catalogue did not ask for (live, remix, sped up...) is refused. The explicit copy
    comes before a clean one unless the catalogue's track is the clean edit; then the album
    breaks a tie between the single and the album's copy."""
    who = norm(artist.split(",")[0])
    want = norm(title)
    # A music video's "Tacones Rojos With John Legend" is the release "Tacones Rojos" crediting him.
    m = re.match(r"(.+?)\s+with\s+(.+)$", title, re.I)
    plain, guest = (norm(m.group(1)), norm(re.split(r",|&", m.group(2))[0])) if m else ("", "")
    asks_cut = bool(OTHER_CUT.search(title))
    asked = (_credits(artist) | _feat_credits(title)) - {who}
    queries, keep, seen = [f"{artist.split(',')[0]} {title}"], [], set()
    for q in queries:                        # one more, naming the guests, if no row credits them
        try:
            rows = _ytm_rows(q)
        except Exception:                                      # noqa: BLE001
            break
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            if not r["atv"]:
                continue
            name = norm(TAG_TAIL.sub("", r["title"]))
            guested = bool(plain) and name == plain and _credited(guest, r["artist"])
            if (name != want and not guested) or (norm(r["title"]) != want and OTHER_CUT.search(r["title"])):
                continue
            if who and not _credited(who, r["artist"]):
                continue
            if NOT_THEIRS.search(r["artist"] + " " + r["album"]) and not NOT_THEIRS.search(title + " " + album):
                continue
            if not asks_cut and OTHER_CUT.search(r["title"] + " " + r["album"]) and not OTHER_CUT.search(album):
                continue
            gap = abs(r["secs"] - length) if length and r["secs"] else 0.0
            if length and gap > 2.0:
                if not (also and r["secs"] and abs(r["secs"] - also) <= 2.0):
                    continue
                gap = 1.5 + abs(r["secs"] - also)        # at Apple's length: after any copy at the asked one
            # a copy crediting someone not asked for is the guest version: "Tacones Rojos" with John Legend;
            # YouTube Music names guests in the title ("Take Me to the Beach (feat. Ado)"), one single per guest
            theirs, ours = _credits(r["artist"]) | _feat_credits(r["title"]), _credits(artist) | _feat_credits(title)
            extra = bool(theirs - ours - {guest})
            keep.append((extra, bool(ours - theirs - {who}), r["explicit"] == clean,
                         gap - (0.5 if album and norm(album) == norm(r["album"]) else 0.0), r["id"]))
        if len(queries) == 1 and asked and not any(not k[1] for k in keep):
            queries.append(f"{queries[0]} {' '.join(sorted(asked))}")   # the Jungeli single was past the first page
        elif len(queries) == 1 and not clean and keep and all(k[2] for k in keep) \
                and any(r["explicit"] and _credited(who, r["artist"]) for r in rows):
            queries.append(f"{queries[0]} explicit")   # a page shows one of a clean/explicit pair (Popular)
    keep.sort()
    return [vid for *_rank, vid in keep]


def isrc_release(isrc: str) -> str:
    """The release with this ISRC on YouTube Music, or "". Its search finds an ISRC as the first
    row, then unrelated songs, so a row counts only with Deezer's name, artist and length for it."""
    try:
        dz = _get(f"{DZ}/track/isrc:{isrc}")
        rows = _ytm_rows(isrc)
    except Exception:                                          # noqa: BLE001
        return ""
    if not isinstance(dz, dict) or not dz.get("title"):
        return ""
    want = {norm(dz.get("title_short") or ""), norm(dz["title"])} - {""}
    who = norm((dz.get("artist") or {}).get("name", ""))
    secs = float(dz.get("duration") or 0)
    for r in rows[:3]:
        if r["atv"] and norm(TAG_TAIL.sub("", r["title"])) in want and (not who or _credited(who, r["artist"])) \
                and (not secs or not r["secs"] or abs(r["secs"] - secs) <= 2.0):
            return r["id"]
    return ""


def not_recording(title: str):
    """A pattern for uploads that are not the recording `title` names (see NOT_RECORDING)."""
    asked = title.casefold()
    words = [w for w in NOT_RECORDING if not re.search(rf"\b{w}\b", asked)]
    return re.compile(rf"\b({'|'.join(words)})\b", re.I)


def _candidates(title: str, artist: str, length: float = 0, album: str = "", clean: bool = False,
                also: float = 0, isrc: str = "") -> list[str]:
    """Uploads of this recording, best first.

    local_align.find is the editor's own search -- YouTube by plays and as
    Topic releases, and SoundCloud, judged by length and against live and
    remix cuts. YouTube Music's own release (release_of) comes first: it is
    the master the streaming services carry, and found in half a second. With an ISRC,
    that very pressing before it (isrc_release)."""
    exact = isrc_release(isrc) if isrc else ""
    got = release_of(title, artist, length, album, clean, also)
    if exact or got:
        return [exact] * bool(exact) + [v for v in got if v != exact]
    try:
        import local_align as LA
        a = artist.split(",")[0].strip()
        found = [u for u, _d in LA.find(f"{a} {title}", length, artist=a, title=title, refuse=not_recording(title))]
        if found:
            return found[:5]
    except Exception:                                        # noqa: BLE001
        pass
    q = f"{artist.split(',')[0]} {title}"
    out = []
    try:
        with _ytdl({"extract_flat": "in_playlist", "playlistend": 4}) as y:
            got = y.extract_info("https://music.youtube.com/search?q=" + urllib.parse.quote_plus(q) + "#songs",
                                 download=False)
        refuse = not_recording(title)
        for e in (got.get("entries") or [])[:4]:
            if e.get("id") and norm(e.get("title", "")).startswith(norm(title)[:12]) \
                    and not refuse.search(e.get("title") or ""):
                out.append(e["id"])
    except ImportError:
        pass
    except Exception:                                        # noqa: BLE001
        pass
    try:
        with _ytdl({"extract_flat": "in_playlist"}) as y:
            got = y.extract_info(f"ytsearch5:{q} audio", download=False)
        out += [e["id"] for e in (got.get("entries") or []) if e.get("id") and e["id"] not in out
                and not not_recording(title).search(e.get("title") or "")]
    except Exception:                                        # noqa: BLE001
        pass
    return out


class _Passed(Exception):
    """A song asked to play now was skipped past while it was being looked for."""


class Resolver(QObject):
    """Track -> {"url", "expires", "spotify", "yt", "len"} on a thread; `ready(key, info|None)`."""

    ready = pyqtSignal(str, object)
    found_spotify = pyqtSignal(str)         # a song's Spotify id, found after it was already playable
    SP_V = 6                                # 5: Spicy's search (misses asked again); 6: kept ids with no community sync too
    SP_AGAIN, SP_RETRY = 86400.0, 600.0     # not on Spotify: ask tomorrow; could not ask: in ten minutes
    SP_GRACE = 1.5                          # once the audio is ready, how much longer the id is waited for

    def __init__(self, keep: pathlib.Path) -> None:
        super().__init__()
        self.keep = keep
        self.ids: dict[str, dict] = {}
        self.busy: set[str] = set()
        self._lock = threading.Lock()
        self._pool = CF.ThreadPoolExecutor(4)       # songs coming up
        self._now = CF.ThreadPoolExecutor(2)        # the song asked to play: never behind the prefetches
        self._sp = CF.ThreadPoolExecutor(4)         # Spotify ids, which can take 20s: never held up for
        self._sp_now = CF.ThreadPoolExecutor(1)     # the playing song's id: never behind the prefetches' lookups
        self._jobs: dict[str, tuple[CF.Future, bool]] = {}     # key -> (job, asked to play now)
        self._current = ""                          # the last song asked to play now; older asks give way
        self.log = None                             # log(event, **fields): the local player's follow.log
        self._sp_jobs: dict[str, CF.Future] = {}
        self.urls = keep.with_name("stream-urls.json")
        global ARTISTS_FILE
        ARTISTS_FILE = keep.with_name("spotify-artists.json")
        try:
            self.ids = json.loads(keep.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            self.ids = {}
        try:
            now = time.time()
            self.live = {k: v for k, v in json.loads(self.urls.read_text(encoding="utf-8")).items()
                         if v.get("expires", 0) - now > 600
                         and (self.ids.get(k) or {}).get("v", 0) >= PICK_V}   # an older pick's link: pick again
        except Exception:                                    # noqa: BLE001
            self.live = {}

    @staticmethod
    def key(t: dict) -> str:
        """The song by its catalogue name: the same key before and after Apple's name is merged in."""
        title, artist = t.get("src_title") or t.get("title", ""), t.get("src_artist") or t.get("artist", "")
        # norm() drops "(feat. X)": the Ernia cut of Take Me to the Beach was kept as the solo's
        feat = sorted(LS._featured(title) - set(LS._who(artist)))
        return f"{norm(title)}{' ft ' + ' '.join(feat) if feat else ''}|{norm(artist)}|" \
               f"{int((t.get('ms') or 0) // 4000)}"

    def known(self, t: dict) -> dict | None:
        """A resolution still good to play, or None."""
        k = self.key(t)
        got = self.live.get(k)
        if got and self._stray_guest((self.ids.get(k) or {}).get("meta") or {}):
            return None                      # another guest's cut: _resolve checks it (the kept link skipped that)
        if self._other_pressing(t, self.ids.get(k) or {}):
            return None
        return got if got and got["expires"] - time.time() > 300 else None

    @staticmethod
    def _other_pressing(t: dict, saved: dict) -> bool:
        """Whether the kept upload was picked by name, or for another ISRC, while this song asks for
        its ISRC's own pressing (`pressing`: a listener given a sharer's file; Deezer's rows may be clean edits)."""
        isrc = str(t.get("isrc") or "") if t.get("pressing") else ""
        return bool(isrc) and not t.get("yt") and saved.get("isrc") != isrc

    def spotify_of(self, t: dict) -> str:
        """The song's Spotify id: the item's own, unless it is a copy of one this lookup replaced."""
        saved = self.ids.get(self.key(t)) or {}
        own = t.get("spotify", "")
        if own and (saved.get("x") or {}).get(own):
            return saved["x"][own]               # a clean pressing's explicit one (see explicit_of)
        return saved.get("spotify", "") if not own or own == saved.get("sp_was") else own

    def yt_of(self, t: dict) -> str:
        return t.get("yt") or (self.ids.get(self.key(t)) or {}).get("yt", "")

    def pick_of(self, t: dict) -> dict | None:
        """The upload a song would play with no search, live link or not: {"yt", "spotify",
        "meta", "lens"}; None where _resolve would pick it again."""
        saved = self.ids.get(self.key(t)) or {}
        vid = t.get("yt") or saved.get("yt", "")
        if not vid or (not t.get("yt") and (saved.get("v", 0) < PICK_V or saved.get("hand"))):
            return None
        meta = saved.get("meta") or {}
        if self._stray_guest(meta):
            return None
        lens = () if t.get("yt") else ((t.get("ms") or 0) / 1000.0, (meta.get("card_ms") or 0) / 1000.0)
        return {"yt": vid, "spotify": self.spotify_of(t), "meta": meta, "lens": lens}

    def sp_due(self, saved: dict) -> bool:
        """Whether to look for a song's Spotify id (again); a found one is only checked, once."""
        if saved.get("spotify"):
            return saved.get("sp_v") != self.SP_V
        if saved.get("sp_v") != self.SP_V:
            return True
        n = int(saved.get("sp_n") or 1)
        wait = min(self.SP_AGAIN, self.SP_RETRY * 2 ** (n - 1)) if saved.get("sp_unsure") else self.SP_AGAIN
        return time.time() - float(saved.get("sp_tried") or 0) > wait

    def sp_note(self, saved: dict, sid: str, trouble: list) -> None:
        saved["spotify"] = sid
        saved["sp_v"] = self.SP_V
        if not sid:
            saved["sp_tried"] = time.time()
            saved["sp_unsure"] = bool(trouble)
            saved.pop("sp_nosession", None)
            saved["sp_n"] = int(saved.get("sp_n") or 0) + 1 if trouble else 0   # unsure again: wait twice as long

    def look_spotify(self, t: dict, k: str = "", now: bool = False) -> CF.Future | None:
        """Look for a song's Spotify id on the side; the lookup already running if there is one.
        `now` for the song playing: queued behind 8 prefetch lookups, Loca's id took 36s (2026-11-02)."""
        k = k or self.key(t)
        kept = (self.ids.get(k) or {}).get("spotify", "")
        if t.get("spotify") and t["spotify"] != kept:
            return self.explicit_of(t, k, now)
        if not self.sp_due(self.ids.get(k) or {}):
            return None                      # (the same id as kept: a queue item's copy of this lookup's)
        with self._lock:
            if ("sp|" + k) in self.busy:
                f = self._sp_jobs.get(k)
                if not (now and f is not None and f.cancel()):
                    return f                 # running already: that one
            self.busy.add("sp|" + k)

        def run() -> str:
            trouble: list = []
            old = int((self.ids.get(k) or {}).get("sp_v") or 0)
            try:
                # A kept id from the old chain is searched once unless its held Spicy doc is a
                # community sync (beamer boy: a duplicate EP copy, Apple's sync only, 2026-11-05).
                # A search's id is explicit-aware already (spicy_track_id).
                if kept and old < 6 and not LS.community_sync(LS.spicy_held(kept)):
                    sid = spotify_id_of(t, trouble, wants_clean(t), look_ahead=not now) or kept
                else:
                    sid = kept or spotify_id_of(t, trouble, wants_clean(t), look_ahead=not now)
                if sid == kept and kept and old < 4 and not wants_clean(t):
                    sid = LS.explicit_twin(kept) or kept
            except Exception:                                # noqa: BLE001
                sid, trouble = kept, ["?"]
            with self._lock:
                self.busy.discard("sp|" + k)
                self._sp_jobs.pop(k, None)
                saved = self.ids.setdefault(k, {})
                if kept and sid != kept:
                    saved["sp_was"] = kept                   # queue items holding it take the new one
                self.sp_note(saved, sid, trouble)            # not found: tomorrow; not asked: soon
                if sid and k in self.live:
                    self.live[k]["spotify"] = sid
            self._save()
            if sid and sid != kept:
                self.keep_for_lyrics(t, sid, kept)
                self.found_spotify.emit(k)
            return sid
        with self._lock:
            f = self._sp_jobs[k] = (self._sp_now if now else self._sp).submit(run)
        return f

    def explicit_of(self, t: dict, k: str, now: bool = False) -> CF.Future | None:
        """A catalogue's own id on the item (a library's clean pressing) checked once for its
        explicit one, kept per id in saved["x"]; the audio pick is explicit too."""
        own = t["spotify"]
        if own in ((self.ids.get(k) or {}).get("x") or {}) or wants_clean(t):
            return None
        with self._lock:
            if ("x|" + k) in self.busy:
                return None
            self.busy.add("x|" + k)

        def run() -> str:
            ex = LS.explicit_twin(own)
            with self._lock:
                self.busy.discard("x|" + k)
                self.ids.setdefault(k, {}).setdefault("x", {})[own] = ex
            self._save()
            if ex:
                self.keep_for_lyrics(t, ex, own)
                self.found_spotify.emit(k)
            return ex or own
        return (self._sp_now if now else self._sp).submit(run)

    @staticmethod
    def keep_for_lyrics(t: dict, sid: str, was: str = "") -> None:
        """A Spotify id found for a song is kept under the song's name key too, where the lyric
        fetch for a player with no Spotify id of its own looks (LS.spotify_id_known): it goes
        to Spicy Lyrics straight away instead of walking the rest first. One the window found
        itself stays: local_player holds a playing song on it (2026-10-30)."""
        import lyric_sources as LS
        for title, artist in {(t.get("title", ""), t.get("artist", "")),
                              (t.get("src_title") or "", t.get("src_artist") or "")}:
            if title:
                try:
                    key = song_key(title, artist)
                    if LS.spotify_id_known(key) in (None, "", was):
                        LS.spotify_id_keep(key, sid)
                except Exception:                            # noqa: BLE001
                    pass

    def want(self, t: dict, now: bool = False) -> None:
        """Resolve a song; `now` for the one asked to play, which goes before any coming up."""
        k = self.key(t)
        with self._lock:
            if now:
                self._current = k
                self._drop_passed(k)
            if self.known(t):
                return
            if k in self.busy:
                f, urgent = self._jobs.get(k) or (None, True)
                if not now or urgent or not f.cancel():
                    return                   # running already, or already first in line
            self.busy.add(k)
            self._jobs[k] = ((self._now if now else self._pool).submit(in_lane, not now, self._run, k, dict(t), now),
                             now)

    def _drop_passed(self, k: str) -> None:
        """Songs asked to play now and skipped past before their turn: dropped, so the song
        landed on is not queued behind them (13 quick skips once kept it 45s). Under _lock."""
        for k2, (f, urgent) in list(self._jobs.items()):
            if urgent and k2 != k and f.cancel():
                self._jobs.pop(k2, None)
                self.busy.discard(k2)

    def _passed(self, k: str, urgent: bool) -> bool:
        """An ask to play now whose song has since been skipped past: it stops at its next step."""
        return urgent and self._current != k

    def _run(self, k: str, t: dict, urgent: bool = False) -> None:
        info = None
        t0 = time.monotonic()
        steps: dict = {}
        try:
            info = self._resolve(k, t, urgent, steps)
        except _Passed:
            info = None
        except Exception as e:                               # noqa: BLE001
            info = {"error": str(e)[:200]}
        with self._lock:
            self.busy.discard(k)
            self._jobs.pop(k, None)
        if self.log is not None:
            try:
                self.log("resolve", key=k[:60], now=urgent, took=round(time.monotonic() - t0, 2),
                         ok=bool(info and info.get("url")), **steps)
            except Exception:                                # noqa: BLE001
                pass
        if info is None:
            return                           # skipped past: nobody is waiting for it
        if info and info.get("url"):
            self.live[k] = info
            with self._lock:
                try:
                    now = time.time()
                    keep = {k2: v for k2, v in self.live.items() if v.get("expires", 0) - now > 600}
                    self.urls.write_text(json.dumps(keep), encoding="utf-8")
                except OSError:
                    pass
        self.ready.emit(k, info)

    @staticmethod
    def _apple_meta(t: dict) -> dict:
        # the catalogue's own name: a queue item carries the last card merged in, and a wrong
        # card ("(feat. Ernia)" on the LOOM solo) was asked for again by its own title
        return {"title": t.get("src_title") or t.get("title", ""), "artist": t.get("src_artist") or t.get("artist", ""),
                "album": t.get("src_album") or ("" if t.get("src_title") else t.get("album", "")),
                "length": (t.get("ms") or 0) / 1000.0}

    @staticmethod
    def _apple(t: dict) -> dict:
        """Apple Music's own name, credits and album for every song Mild Lyrics streams:
        Spotify, Deezer and YouTube often credit only the main artist. Its length too,
        where the song came with none."""
        try:
            import lyric_sources as LS
            card = LS.apple_card(Resolver._apple_meta(t))
        except Exception:                                    # noqa: BLE001
            return {}
        if not card.get("sure") or not card.get("title"):
            return {}
        album = card.get("album") or t.get("album", "")
        if re.search(r"\s-\s(single|ep)$", album, re.I):
            album = album[:album.rfind(" - ")]           # "LV Sandals - Single": the single's own name
        out = {"title": recase(card["title"], t.get("title", "")),
               "artist": card.get("artist") or t.get("artist", ""),
               "album": recase(album, t.get("album", "")), "art": card.get("art") or "",
               "ms": t.get("ms") or int((card.get("length") or 0) * 1000),
               "card_ms": int((card.get("length") or 0) * 1000)}
        out["src_title"] = t.get("src_title") or t.get("title", "")      # what lookups ask by first
        out["src_artist"] = t.get("src_artist") or t.get("artist", "")
        out["src_album"] = t.get("src_album") or t.get("album", "")
        out["gv"] = 2              # asked under the guest rules, by the catalogue's name: see _stray_guest
        names = card.get("artists") or []
        if names:
            bare = lambda n: re.sub(r"^the ", "", norm(n))        # Deezer's "The Black Eyed Peas"
            had = {bare(a.get("name", "")): a.get("uri", "") for a in t.get("artists") or [] if isinstance(a, dict)}
            out["artist"] = ", ".join(names)
            out["artists"] = [{"name": n, "uri": had.get(bare(n), "")} for n in names]
        return out

    @staticmethod
    def _named(meta: dict) -> bool:
        """Whether a kept Apple name is still the song asked for (2026-10-24: "Lost" was kept as LOST IN THE ECHO)."""
        if not meta.get("src_title"):
            return True
        # and still names the guest asked for: "Levitating (feat. DaBaby)" was kept as the solo's card
        return LS._same_song(meta.get("title", ""), meta["src_title"]) \
            and not (LS._featured(meta["src_title"]) and not LS._guests(meta.get("title", ""), meta.get("artist", "")))

    META_V = 2                              # Apple's name kept in streams.json: bump to ask again

    @staticmethod
    def _stray_guest(meta: dict) -> bool:
        """Whether a card kept from before the guest rules credits a guest the song asked lacks:
        its upload and Spotify id are that cut's too (the solo Take Me to the Beach played Ernia's)."""
        return bool(meta.get("src_title")) and meta.get("gv", 0) < 2 and LS._guest_halves(
            meta.get("title", ""), meta.get("artist", ""), meta["src_title"], meta.get("src_artist", ""))[0]

    def _resolve(self, k: str, t: dict, urgent: bool = False, steps: dict | None = None) -> dict:
        steps = {} if steps is None else steps
        t0 = time.monotonic()

        def step(name: str, check: bool = True) -> None:
            steps[name] = round(time.monotonic() - t0, 2)    # seconds from the start, as each step ends
            if check and self._passed(k, urgent):
                steps["passed"] = True
                raise _Passed
        kept = self.ids.get(k) or {}
        if self._stray_guest(kept.get("meta") or {}):
            fresh = self._apple(t)           # asked once more: most such cards are Apple naming a real guest
            with self._lock:
                was = kept["meta"]
                if fresh and not kept.get("hand") and LS._guests(fresh.get("title", ""), fresh.get("artist", "")) \
                        != LS._guests(was.get("title", ""), was.get("artist", "")):
                    self.ids.pop(k, None)    # picked for another cut: upload and ids resolved again
                    kept = {}
                elif fresh:
                    kept = self.ids[k] = dict(kept, meta=fresh, meta_v=self.META_V)
        # Known by name only, or by a play-log row: its length is whatever upload played last time,
        # and searching by it drifts (High Hopes 190.9s -> 210.7 -> 243: a slowed copy, 2026-10-31).
        by_name = bool(t.get("heard")) or not (t.get("spotify") or t.get("isrc") or t.get("yt") or t.get("uri"))
        meta = kept["meta"] if kept.get("meta_v") == self.META_V and self._named(kept["meta"]) \
            and not (by_name and "card_ms" not in kept["meta"]) else self._apple(t)
        step("apple")
        if meta.get("title"):
            meta = dict(meta, title=drop_credited_feat(meta["title"], meta.get("artist") or t.get("artist", "")))
        if meta:
            t = dict(t, **{x: v for x, v in meta.items()
                           if v and (x != "art" or not t.get("art") or "ytimg.com/" in t.get("art", ""))})
        title, artist = t.get("title", ""), t.get("artist", "")
        want_len = ((meta.get("card_ms") if by_name else 0) or t.get("ms") or 0) / 1000.0
        # Apple's length too, where it differs: a length heard from an earlier upload reaches the
        # queue by more ways than `heard` marks (ZEZE at 219.9s found nothing, 2026-11-01)
        alt_len = (meta.get("card_ms") or 0) / 1000.0
        alt_len = alt_len if want_len and alt_len and abs(alt_len - want_len) > DURATION_SLACK else 0.0
        sp = self.look_spotify(t, k, now=urgent)   # the whole chain can take 20s: it goes on after the song starts
        saved = dict(self.ids.get(k) or {})
        if t.get("yt"):
            saved["yt"] = t["yt"]            # a YouTube result: that upload, as picked
        tried = [saved["yt"]] if saved.get("yt") else []
        url = length = exp = None
        if saved.get("yt") and not t.get("yt") and (saved.get("v", 0) < PICK_V or saved.get("hand")):
            tried = []                       # picked before the release search existed, or by hand: pick again
        if tried and alt_len and not t.get("yt"):
            tried = []                       # the asked length and Apple's disagree: the release decides
        if tried and self._other_pressing(t, saved):
            tried = []                       # picked by name: the ISRC's own release may be another
        def uploads():
            yield from tried                 # the upload picked before: no search unless it fails
            found = _candidates(title, artist, want_len, t.get("album", ""), bool(t.get("clean")), also=alt_len,
                                isrc=str(t.get("isrc") or "") if t.get("pressing") else "")
            step("search")
            yield from [c for c in found if c not in tried][:5]
        blocked = False
        tries = 0
        for vid in uploads():
            if tries:
                step(f"try{tries}")
            tries += 1
            try:
                url, length, exp = _audio(vid)
            except YouTubeBlocked:
                blocked = True               # the rest would only be asked the same, and keep the flag up
                break
            except Exception:                                # noqa: BLE001
                continue
            if not want_len or abs(length - want_len) <= DURATION_SLACK or vid == t.get("yt") \
                    or (alt_len and abs(length - alt_len) <= DURATION_SLACK):
                saved["yt"], saved["v"], saved["hand"] = vid, PICK_V, vid == t.get("yt")
                break
            url = None
        step("audio", check=False)           # a link already found is kept, skipped past or not
        if sp is not None and url and not self._passed(k, urgent):
            try:
                sp.result(timeout=self.SP_GRACE)             # a quick find starts the song with its id
            except Exception:                                # noqa: BLE001
                pass
            steps["spotify"] = round(time.monotonic() - t0, 2)
        with self._lock:
            mine = self.ids.setdefault(k, {})
            if saved.get("yt"):
                mine["yt"], mine["v"] = saved["yt"], saved.get("v", 0)
                mine["hand"] = bool(saved.get("hand"))
                if url and t.get("isrc") and t.get("pressing"):
                    mine["isrc"] = str(t["isrc"])      # picked with it in hand: not picked again for it
            if url and meta:                 # {} may be Apple unreachable: asked again next time
                mine["meta"], mine["meta_v"] = meta, self.META_V
            spot = self.spotify_of(t)        # (key keeps the catalogue's name: the same k)
        self._save()
        if blocked:
            mins = max(1, round(yt_blocked() / 60))
            return {"error": f"YouTube is asking to confirm this is not a bot; trying again in {mins} min",
                    "blocked": True, "spotify": spot, "meta": meta}
        if not url:
            return {"error": "no copy of this song with the right length was found", "spotify": spot,
                    "meta": meta}
        return {"url": url, "expires": exp, "len": length, "yt": saved.get("yt", ""), "spotify": spot,
                "meta": meta}

    def _save(self) -> None:
        try:
            self.keep.parent.mkdir(parents=True, exist_ok=True)
            self.keep.write_text(json.dumps(self.ids), encoding="utf-8")
        except OSError:
            pass

    def close(self) -> None:
        for pool in (self._pool, self._now, self._sp):
            pool.shutdown(wait=False, cancel_futures=True)
