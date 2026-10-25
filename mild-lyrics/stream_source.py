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

import home_data as HD
import lyric_sources as LS
import yt_captions as YC

UA = "MildLyrics/1.2 (+https://github.com/gcoolL/mild-lyrics)"
DZ = "https://api.deezer.com"
LB = "https://labs.api.listenbrainz.org/spotify-id-from-metadata/json"
EMBED = "https://open.spotify.com/embed/track/"
DURATION_SLACK = 3.0          # seconds a stream may differ from the catalogue's length
NO_SESSION = "no-spotify-session"   # in `trouble`: Spotify's search was not there to ask (not trouble)
DZ_PACE = (40, 5.0)           # Deezer allows 50 asks in 5s per address: at most this many, then wait
NET_HOSTS = (("api.deezer.com", 443), ("1.1.1.1", 443))   # any of these answering = a connection

_dz_sent: collections.deque = collections.deque()
_dz_lock = threading.Lock()


def _dz_pace() -> None:
    """Wait until one more Deezer ask stays under its quota (one autoplay fill was 41 in 4s)."""
    n, span = DZ_PACE
    while True:
        with _dz_lock:
            now = time.monotonic()
            while _dz_sent and now - _dz_sent[0] > span:
                _dz_sent.popleft()
            if len(_dz_sent) < n:
                _dz_sent.append(now)
                return
            wait = span - (now - _dz_sent[0])
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
    year = (a.get("release_date") or "")[:4]
    return {"uri": f"deezer:album:{a['id']}", "kind": "album", "name": a.get("title", ""),
            "sub": ar.get("name", "") + (f" · {year}" if year and ar.get("name") else year), "year": year,
            "art": a.get("cover_xl") or a.get("cover_big") or "", "type": (a.get("record_type") or "").lower()}


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
        ft = ex.submit(_get, f"{DZ}/search?q={qq}&limit=25")
        fa = ex.submit(_get, f"{DZ}/search/artist?q={qq}&limit=12")
        fb = ex.submit(_get, f"{DZ}/search/album?q={qq}&limit=12")
        tracks = [x for x in (_dz_track(t) for t in (ft.result().get("data") or [])) if x]
        artists = [_dz_artist(a) for a in (fa.result().get("data") or []) if a.get("id")]
        albums = [_dz_album(a) for a in (fb.result().get("data") or []) if a.get("id")]
    tracks = _plain_before_versions(q, tracks)
    top = ""
    named = best_artist(artists, q)
    if named is not None:
        top = named["uri"]
        if sum(any(a.get("uri") == named["uri"] for a in t.get("artists") or []) for t in tracks[:5]) >= 2:
            tracks = _own_songs_first(tracks, named)
    elif tracks:
        tracks, artists = _title_points_to_artists(q, tracks, artists)
        top = tracks[0]["uri"]
    return {"tracks": tracks, "artists": artists, "albums": albums, "playlists": [], "top": top}


VERSION_TAG = re.compile(r"^(.*?\S)\s*(?:[\(\[]([^\)\]]*)[\)\]]|\s-\s(.*))$")


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
    with CF.ThreadPoolExecutor(4) as ex:
        fa, ft = ex.submit(_get, f"{DZ}/artist/{i}"), ex.submit(_get, f"{DZ}/artist/{i}/top?limit=10")
        fb, fr = ex.submit(_get, f"{DZ}/artist/{i}/albums?limit=30"), ex.submit(_get, f"{DZ}/artist/{i}/related?limit=12")
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
        found = list(ex.map(lambda s: _dz_song(*s), songs))
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

    def __init__(self, art_url=lambda u: u) -> None:
        super().__init__(lambda js: js(), art_url)

    def feed(self):
        self.want("feed", dz_feed, keep=3600)

    def liked(self, n: int = 0, keep=None):
        pass

    def shelf(self, which: str):
        pass

    def playlist(self, uri: str, keep: float = 600):
        self.want("pl:" + uri, lambda: dz_playlist(uri), keep=keep, first=True)

    def album(self, uri: str):
        self.want("album:" + uri, lambda: dz_album(uri), keep=1800, first=True)

    def artist(self, uri: str):
        self.want("artist:" + uri, lambda: dz_artist(uri), keep=1800, first=True)

    def chart_uri(self, which: str) -> str:
        """Without Spotify: Deezer's global and country charts, and Shazam's rising songs for Viral 50."""
        return {"Your country": "deezer:playlist:country", "Viral 50": "deezer:playlist:viral"}.get(
            which, "deezer:playlist:chart")

    def chart(self, which: str):
        self.playlist(self.chart_uri(which), keep=3600)

    def search(self, q: str):
        self.want_only("search:" + q, lambda: dz_search(q), keep=600)

    def lookup(self, q: str):
        self.want("search:" + q, lambda: dz_search(q), keep=86400)

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
    for a in (((found.get("results") or {}).get("artists") or {}).get("data") or []):
        if norm((a.get("attributes") or {}).get("name", "")) == norm(name):
            got = ask(f"/artists/{a['id']}/view/top-songs?limit=30")
            return tuple(_song_title_key((s.get("attributes") or {}).get("name", "")) for s in got.get("data") or [])
    return ()


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
            self._pool.submit(self._look, name)
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
            self._pool.submit(self._look, k, dict(t))
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
        self.want("radio:youtube:" + vid, lambda: yt_radio(vid), keep=1800)

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


def mb_isrc_spotify(codes: list) -> str:
    """MusicBrainz's Spotify link for the recording with this ISRC: the exact recording,
    whatever either side calls it."""
    for code in codes[:2]:
        try:
            got = _mb(f"isrc/{urllib.parse.quote(code)}?fmt=json&inc=url-rels")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue                     # not in MusicBrainz: an answer, not a refusal
            raise
        for rec in got.get("recordings") or []:
            for rel in rec.get("relations") or []:
                m = SPOTIFY_TRACK.search(((rel.get("url") or {}).get("resource")) or "")
                if m:
                    return m.group(1)
    return ""


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


def artist_page_spotify(title: str, artist: str, album: str = "", ms: float = 0) -> str:
    """The song on its artist's public Spotify page: their top tracks, then the releases it
    lists (newest five albums and eight singles), the one named like the song's album first."""
    aid = ""
    for who in [a for a in re.split(r"\s*(?:,|&| feat\.? | x )\s*", artist or "") if a][:2]:
        aid = spotify_artist_id(who)
        if aid:
            break
    if not aid:
        return ""
    d = (((_sp_state("artist/" + aid).get("entities") or {}).get("items") or {})
         .get("spotify:artist:" + aid) or {}).get("discography") or {}
    base = lambda s: norm(re.split(r"\s+-\s+", s or "")[0])      # Spotify's "Song - X Remix"
    want, alb, ver = base(title), norm(album), versions(title)
    near = lambda got: not ms or not got or abs(float(got) - ms) <= DURATION_SLACK * 1000
    same = lambda name, dur: base(name) == want and versions(name) == ver and near(dur)
    for it in (d.get("topTracks") or {}).get("items") or []:
        tr = it.get("track") or {}
        if same(tr.get("name", ""), (tr.get("duration") or {}).get("totalMilliseconds")):
            return (tr.get("uri") or "").rsplit(":", 1)[-1]
    rels = []
    for sec in ("popularReleasesAlbums", "albums", "singles", "compilations"):
        for r in (d.get(sec) or {}).get("items") or []:
            for x in ((r.get("releases") or {}).get("items") if "releases" in r else [r]) or []:
                if x.get("uri") and all(y["uri"] != x["uri"] for y in rels):
                    rels.append(x)
    rels.sort(key=lambda x: norm(x.get("name", "")) not in (alb, want) and base(x.get("name", "")) != want)
    for x in rels[:6]:
        for tr in _embed("album", x["uri"].rsplit(":", 1)[-1]).get("trackList") or []:
            if same(tr.get("title", ""), tr.get("duration")):
                return (tr.get("uri") or "").rsplit(":", 1)[-1]
    return ""


def _compilation(release: dict) -> bool:
    return "Compilation" in ((release.get("release-group") or {}).get("secondary-types") or [])


def mb_spotify(title: str, artist: str, ms: float = 0, compilations: bool = False) -> str:
    """MusicBrainz's Spotify link for the recording, or for the release it is on (then the
    track is found in that album's public embed page). Compilations only when asked: their
    copy is another Spotify id, and "C U Again" took NCS: The Best of 2016's, which Spicy
    has no sync for, where the single's (found by the artist page) has the community's."""
    who = norm(artist.split(",")[0].split("&")[0])
    plain = re.sub(r"\s*[\(\[].*?[\)\]]", "", title).strip() or title    # "Muffin (feat. …)" -> "Muffin"
    q = f'recording:"{plain}" AND artist:"{artist.split(",")[0].split("&")[0].strip()}"'
    got = _mb("recording?fmt=json&limit=8&query=" + urllib.parse.quote(q))
    want = norm(title)
    for rec in got.get("recordings") or []:
        names = [norm(c.get("name", "")) for c in rec.get("artist-credit") or [] if isinstance(c, dict)]
        if norm(rec.get("title", "")) != want or (who and not any(who in n or n in who for n in names if n)):
            continue
        if ms and rec.get("length") and abs(rec["length"] - ms) > DURATION_SLACK * 1000:
            continue
        full = _mb(f"recording/{rec['id']}?fmt=json&inc=url-rels+releases+release-groups")
        for rel in full.get("relations") or []:
            m = SPOTIFY_TRACK.search(((rel.get("url") or {}).get("resource")) or "")
            if m:
                return m.group(1)
        own = sorted((r for r in full.get("releases") or [] if _compilation(r) == compilations),
                     key=lambda r: (r.get("status") != "Official", r.get("date") or "9999"))
        for release in own[:3]:
            rels = _mb(f"release/{release['id']}?fmt=json&inc=url-rels").get("relations") or []
            for rel in rels:
                m = SPOTIFY_ALBUM.search(((rel.get("url") or {}).get("resource")) or "")
                if not m:
                    continue
                for t in (_embed("album", m.group(1)).get("trackList") or []):
                    if norm(t.get("title", "")) == want and (
                            not ms or abs(float(t.get("duration") or 0) - ms) <= DURATION_SLACK * 1000):
                        return (t.get("uri") or "").rsplit(":", 1)[-1]
        break       # the best matching recording only: the rest are other songs or other cuts
    return ""


def genius_spotify(title: str, artist: str) -> str:
    """Genius's own Spotify link for the song, where its page has one."""
    plain = re.sub(r"\s*[\(\[].*?[\)\]]", "", title).strip() or title
    got = _get("https://genius.com/api/search/multi?q=" + urllib.parse.quote(f"{artist.split(',')[0]} {plain}"))
    want, who = norm(title), norm(artist.split(",")[0].split("&")[0])
    for sec in (got.get("response") or {}).get("sections") or []:
        if sec.get("type") != "song":
            continue
        for h in sec.get("hits") or []:
            r = h.get("result") or {}
            by = norm(((r.get("primary_artist") or {}).get("name")) or r.get("artist_names") or "")
            if norm(r.get("title", "")) != want or (who and who not in by):
                continue
            song = (_get(f"https://genius.com/api/songs/{r['id']}").get("response") or {}).get("song") or {}
            for m in song.get("media") or []:
                if m.get("provider") == "spotify":
                    sid = (m.get("native_uri") or "").rsplit(":", 1)[-1] or \
                        (SPOTIFY_TRACK.search(m.get("url") or "") or [None, ""])[1]
                    if sid:
                        return sid
            return ""
    return ""


VERSION_WORDS = re.compile(r"\b(remix|mix|edit|live|acoustic|instrumental|sped|slowed|extended|"
                           r"demo|cover|karaoke|unplugged|reprise|nightcore|8d)\b")


def versions(title: str) -> set:
    """The words that make a cut another version of the song: "(LUCA LUSH Remix)" is not "Alone"."""
    return set(VERSION_WORDS.findall((title or "").lower()))


def fits_spotify(sid: str, title: str, ms: float) -> bool:
    """Spotify's public page for `sid` agrees: the same version, and the length within slack."""
    ent = _embed("track", sid)
    if versions(ent.get("name") or ent.get("title") or "") != versions(title):
        return False
    return not ms or not ent.get("duration") or abs(float(ent["duration"]) - ms) <= DURATION_SLACK * 1000


def _track_page(sid: str) -> dict:
    """The track behind Spotify's public page for `sid`: name, artists, playability, albumOfTrack."""
    return ((_sp_state("track/" + sid).get("entities") or {}).get("items") or {}).get("spotify:track:" + sid) or {}


def album_of(sid: str) -> dict:
    """The album Spotify files `sid` on (name, type); {} where not known."""
    try:
        return _track_page(sid).get("albumOfTrack") or {}
    except Exception:                                        # noqa: BLE001
        return {}


def on_compilation(sid: str) -> bool:
    """Whether Spotify files `sid` on a compilation. MusicBrainz links a recording to such a copy
    as readily as to the artist's own: Notion's ISRC named Viral Rock Hits' (2026-10-24)."""
    return album_of(sid).get("type") == "COMPILATION"       # not known: taken, as before the check


def song_key(title: str, artist: str) -> str:
    """The id a song with no Spotify id is known by: the window's song_key, local_player._key."""
    return hashlib.sha1(f"{title} {artist}".encode("utf-8")).hexdigest()[:22]


def dz_isrc(title: str, artist: str, ms: float = 0) -> str:
    """The recording's ISRC found by name on Deezer, whose search rows carry one: same
    title, same first artist, the length to DURATION_SLACK where there is one."""
    who = artist.split(",")[0].strip()
    q = f"{who} {title}".strip()             # plain: Deezer's artist:"" filter answers nothing (2026-10)
    rows = _get(f"{DZ}/search?q={urllib.parse.quote(q)}&limit=15").get("data") or []
    want_t, want_a = norm(title), norm(who)
    best = None
    for r in rows:
        if not r.get("isrc") or want_t not in (norm(r.get("title", "")), norm(r.get("title_short", ""))):
            continue
        if want_a and want_a not in norm((r.get("artist") or {}).get("name", "")):
            continue
        gap = abs(float(r.get("duration") or 0) * 1000 - ms) if ms else 0.0
        if ms and gap > DURATION_SLACK * 1000:
            continue
        rank = (gap, bool(r.get("title_version")))       # no length: the plain release before a version
        if best is None or rank < best[0]:
            best = (rank, r["isrc"])
    return best[1] if best else ""


def spotify_by_isrc(isrcs: list, title: str, ms: float = 0, trouble: list | None = None,
                    album: str = "", spare: list | None = None) -> str:
    """The Spotify track with this ISRC: the same recording by its registration code, asked of
    Spotify's Web API (where a token is kept), then MusicBrainz; checked like any other find.
    A compilation's copy goes to `spare` where one is given, else is the answer last."""
    import lyric_sources as LS
    codes = [c for c in isrcs or [] if c][:2]
    if not codes:
        return ""
    held = spare if spare is not None else []

    def by_web() -> str:
        rows = LS.spotify_web_search({"isrcs": codes})
        if rows is None and LS.spotify_session_left() > 60:
            raise OSError("Spotify refused the search")              # (trouble, below)
        if rows is None and trouble is not None:
            trouble.append(NO_SESSION)
        return _match_rows([r for r in rows or [] if r.get("isrc")], title, "", ms, album)

    for name, step in (("spotify-web-isrc", by_web), ("musicbrainz-own-isrc", lambda: mb_isrc_spotify(codes))):
        try:
            sid = step()
        except Exception:                                    # noqa: BLE001
            if trouble is not None:
                trouble.append(name)
            continue
        if sid and fits_spotify(sid, title, ms):
            if not on_compilation(sid):
                return sid
            held.append(sid)
    return held[0] if held and spare is None else ""


def spotify_id(title: str, artist: str, album: str = "", ms: float = 0, page=None,
               trouble: list | None = None, isrcs: list | None = None) -> str:
    """A Spotify track id for a song known by name, asked of each source in
    turn and checked against Spotify's public page; with `trouble` set,
    empty means "not known yet", not "not on Spotify"."""
    trouble = trouble if trouble is not None else []
    import lyric_sources as LS
    spare: list = []                    # a compilation's copy: taken only when no step names the own
    if isrcs:
        sid = spotify_by_isrc(isrcs, title, ms, trouble, album, spare)
        if sid:
            return sid

    def by_page() -> str:
        return _match_rows(page(f"{artist.split(',')[0]} {title}") or [], title, artist, ms, album) if page else ""

    def by_web() -> str:
        rows = LS.spotify_web_search({"title": title, "artist": artist, "length": ms / 1000.0})
        if rows is None:
            # Refused (429): not asked, "not known yet". No session from the desktop app at all:
            # not trouble (no Spotify would mean asking forever), but marked to ask once it has one.
            trouble.append("spotify-web" if LS.spotify_session_left() > 60 else NO_SESSION)
        return _match_rows(rows or [], title, artist, ms, album)

    def by_lb() -> str:
        q = [{"artist_name": artist.split(",")[0].strip(), "release_name": album or "", "track_name": title}]
        got = _get(LB, json.dumps(q).encode(), timeout=8)
        want_t, want_a = norm(title), norm(artist.split(",")[0])
        # Unordered: Notion's came as the Acoustic single's copy, two TikTok compilations, ...,
        # the Notion single ninth. The copy on the song's own album first, then any not on a compilation.
        ok = []
        for tid in (((got or [{}])[0] or {}).get("spotify_track_ids") or [])[:10]:
            try:
                tr = _track_page(tid)
            except Exception:                                # noqa: BLE001
                continue
            who = [norm(((a.get("profile") or {}).get("name")) or "")
                   for k in ("firstArtist", "otherArtists") for a in (tr.get(k) or {}).get("items") or []]
            if norm(tr.get("name", "")) != want_t or (want_a and want_a not in who) \
                    or (tr.get("playability") or {}).get("playable") is False:
                continue
            al = tr.get("albumOfTrack") or {}
            own = al.get("type") != "COMPILATION"
            if own and (not album or norm(al.get("name", "")) == norm(album)
                        and versions(al.get("name", "")) == versions(album)):      # not "Notion (Acoustic)"
                return tid
            ok.append((not own, len(ok), tid))
        return min(ok)[2] if ok else ""

    def by_isrc() -> str:
        return mb_isrc_spotify(LS.apple_isrcs({"title": title, "artist": artist, "length": ms / 1000.0}) or [])

    for name, step in (("page", by_page), ("spotify-web", by_web), ("listenbrainz", by_lb),
                       ("musicbrainz", lambda: mb_spotify(title, artist, ms)),
                       ("musicbrainz-isrc", by_isrc),
                       ("artist-page", lambda: artist_page_spotify(title, artist, album, ms)),
                       ("genius", lambda: genius_spotify(title, artist)),
                       ("musicbrainz-compilation", lambda: mb_spotify(title, artist, ms, compilations=True))):
        try:
            sid = step()
        except Exception as e:                               # noqa: BLE001
            trouble.append(name)
            _said(f"[spotify id] {title} / {name}: {e!r}"[:300])
            continue
        if not sid:
            continue
        try:
            if not fits_spotify(sid, title, ms):
                continue
        except Exception as e:                               # noqa: BLE001
            trouble.append("embed")
            _said(f"[spotify id] {title} / embed {sid}: {e!r}"[:300])
            continue
        if sid in spare or on_compilation(sid):
            spare.append(sid)
            continue
        return sid
    return spare[0] if spare else ""


_SAID: set = set()


def _said(msg: str) -> None:
    """A lookup step that could not ask, once per kind of error, to the log (stderr)."""
    kind = msg.split(": ", 1)[-1][:60]
    if kind not in _SAID:
        _SAID.add(kind)
        print(msg, file=sys.stderr, flush=True)


def spotify_id_of(t: dict, page=None, trouble: list | None = None) -> str:
    """spotify_id by the song's own catalogue name first (Spotify writes what the label sent,
    as Deezer does), then by Apple's where that differs."""
    names = [(t.get("src_title") or t.get("title", ""), t.get("src_artist") or t.get("artist", "")),
             (t.get("title", ""), t.get("artist", ""))]
    seen = set()
    isrcs = t.get("isrcs")
    for title, artist in names:
        k = (norm(title), norm(artist.split(",")[0]))
        if not title or k in seen:
            continue
        seen.add(k)
        sid = spotify_id(title, artist, t.get("album", ""), t.get("ms") or 0, page, trouble, isrcs)
        if sid:
            return sid
        isrcs = None                         # the codes do not depend on the name: asked once
    return ""


def _ytdl(opts: dict):
    import yt_dlp
    import music_video as MV
    base = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    if time.time() < MV.V4_ONLY[0]:
        base["source_address"] = "0.0.0.0"              # IPv4: YouTube flagged the IPv6 address
    return yt_dlp.YoutubeDL({**base, **opts})


AUDIO_FMT = "bestaudio[ext=m4a]/bestaudio[protocol^=http]/bestaudio"


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
        with _ytdl({"format": AUDIO_FMT}) as y:
            info = y.extract_info(url, download=False)
    except ImportError:
        return _audio_cli(url)
    except Exception as e:                               # noqa: BLE001
        if not MV._blocked(e, v4):
            raise
        try:
            with _ytdl({"format": AUDIO_FMT}) as y:      # once more, over IPv4 (see MV._blocked)
                info = y.extract_info(url, download=False)
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
    out = noconsole.run(local_align.ytdlp() + v4 + ["-f", AUDIO_FMT, "--print", "url",
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
YTM_CLIENT = {"clientName": "WEB_REMIX", "clientVersion": "1.20241023.01.00", "hl": "en"}
OTHER_CUT = re.compile(r"\b(live|acoustic|remix|instrumental|karaoke|demo|slowed|sped up|reverb|"
                       r"version|edit|mix|cover|nightcore|8d)\b", re.I)
# somebody else's recording of it, said in the artist or the album: "METEORA: Tribute to Linkin Park"
NOT_THEIRS = re.compile(r"\b(tribute|karaoke|in the style of|originally performed|made famous|"
                        r"cover(?:s|ed)?|lullaby|lullabies|piano versions?|string quartet|8[- ]?bit)\b", re.I)
# what may follow a release's name: "Song - 2011 Remaster" is the song, "Song 2" is not
TAG_TAIL = re.compile(r"\s+[-–—~～/|]\s.*$")
PICK_V = 4                  # saved uploads picked before an earlier rule are picked again (v2 took a tribute act,
                            # v3 a clean copy over the explicit one)


def _credited(who: str, artists: str) -> bool:
    """Whether `who` is one of the credited names, not merely inside one ("...Tribute to Linkin Park")."""
    names = [norm(x) for x in re.split(r",|&|\bfeat\.?|\bft\.?|\bwith\b|\bx\b|\band\b", artists or "")]
    return who in names or who == norm(artists)


def _ytm_rows(q: str) -> list[dict]:
    body = json.dumps({"context": {"client": YTM_CLIENT}, "query": q, "params": YTM_SONGS}).encode()
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
                    "explicit": "MUSIC_EXPLICIT_BADGE" in json.dumps(it)})
    return out


YTM_NEXT = "https://music.youtube.com/youtubei/v1/next?prettyPrint=false"


def yt_radio(vid: str) -> dict:
    """YouTube Music's radio for one song (its "Start radio", RDAMVM<id>): about 50 songs
    from co-listening, no account. Art Tracks only, the song itself left out."""
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
        if not v or v == vid or "MUSIC_VIDEO_TYPE_ATV" not in json.dumps(it.get("navigationEndpoint") or {}):
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
        tracks.append({"uri": f"youtube:video:{v}", "uid": "", "name": title, "sub": by,
                       "song": title, "song_by": by, "artists": [{"name": a, "uri": ""} for a in artists],
                       "album": album, "album_uri": "",
                       "art": thumbs[-1].get("url", "") if thumbs else f"https://i.ytimg.com/vi/{v}/hqdefault.jpg",
                       "ms": secs * 1000, "plays": 0, "kind": "track", "yt": v})
    return {"uri": "youtube:radio:" + vid, "tracks": tracks}


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
    bid = ""
    for it in _find(_ytm(YTM_SEARCH, {"query": name, "params": YTM_ARTISTS}), "musicResponsiveListItemRenderer", []):
        c = cols(it)
        b = ((it.get("navigationEndpoint") or {}).get("browseEndpoint") or {}).get("browseId", "")
        if c and b.startswith("UC") and norm(text(c[0])) == norm(name):
            bid = b
            break
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


def release_of(title: str, artist: str, length: float = 0, album: str = "", clean: bool = False) -> list[str]:
    """The release itself on YouTube Music: same name, same artist, same length to 2s.

    A cut the catalogue did not ask for (live, remix, sped up...) is refused. The explicit copy
    comes before a clean one unless the catalogue's track is the clean edit; then the album
    breaks a tie between the single and the album's copy."""
    who = norm(artist.split(",")[0])
    want = norm(title)
    asks_cut = bool(OTHER_CUT.search(title))
    try:
        rows = _ytm_rows(f"{artist.split(',')[0]} {title}")
    except Exception:                                        # noqa: BLE001
        return []
    keep = []
    for r in rows:
        if not r["atv"]:
            continue
        if norm(TAG_TAIL.sub("", r["title"])) != want or (norm(r["title"]) != want and OTHER_CUT.search(r["title"])):
            continue
        if who and not _credited(who, r["artist"]):
            continue
        if NOT_THEIRS.search(r["artist"] + " " + r["album"]) and not NOT_THEIRS.search(title + " " + album):
            continue
        if not asks_cut and OTHER_CUT.search(r["title"] + " " + r["album"]) and not OTHER_CUT.search(album):
            continue
        gap = abs(r["secs"] - length) if length and r["secs"] else 0.0
        if length and gap > 2.0:
            continue
        keep.append((r["explicit"] == clean, gap - (0.5 if album and norm(album) == norm(r["album"]) else 0.0),
                     r["id"]))
    keep.sort()
    return [vid for _e, _g, vid in keep]


def _candidates(title: str, artist: str, length: float = 0, album: str = "", clean: bool = False) -> list[str]:
    """Uploads of this recording, best first.

    local_align.find is the editor's own search -- YouTube by plays and as
    Topic releases, and SoundCloud, judged by length and against live and
    remix cuts. YouTube Music's own release (release_of) comes first: it is
    the master the streaming services carry, and found in half a second."""
    got = release_of(title, artist, length, album, clean)
    if got:
        return got
    try:
        import local_align as LA
        a = artist.split(",")[0].strip()
        found = [u for u, _d in LA.find(f"{a} {title}", length, artist=a, title=title)]
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
        for e in (got.get("entries") or [])[:4]:
            if e.get("id") and norm(e.get("title", "")).startswith(norm(title)[:12]):
                out.append(e["id"])
    except ImportError:
        pass
    except Exception:                                        # noqa: BLE001
        pass
    try:
        with _ytdl({"extract_flat": "in_playlist"}) as y:
            got = y.extract_info(f"ytsearch5:{q} audio", download=False)
        out += [e["id"] for e in (got.get("entries") or []) if e.get("id") and e["id"] not in out]
    except Exception:                                        # noqa: BLE001
        pass
    return out


class Resolver(QObject):
    """Track -> {"url", "expires", "spotify", "yt", "len"} on a thread; `ready(key, info|None)`."""

    ready = pyqtSignal(str, object)
    found_spotify = pyqtSignal(str)         # a song's Spotify id, found after it was already playable
    SP_V = 3                                # 3: ids found before compilations were told apart: checked once
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
        self._jobs: dict[str, tuple[CF.Future, bool]] = {}     # key -> (job, asked to play now)
        self._sp_jobs: dict[str, CF.Future] = {}
        self.page = None        # Spotify's own search while its page answers: q -> rows with uri/name/sub/ms
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
        return f"{norm(title)}|{norm(artist)}|{int((t.get('ms') or 0) // 4000)}"

    def known(self, t: dict) -> dict | None:
        """A resolution still good to play, or None."""
        got = self.live.get(self.key(t))
        return got if got and got["expires"] - time.time() > 300 else None

    def spotify_of(self, t: dict) -> str:
        """The song's Spotify id: the item's own, unless it is a copy of one this lookup replaced."""
        saved = self.ids.get(self.key(t)) or {}
        own = t.get("spotify", "")
        return saved.get("spotify", "") if not own or own == saved.get("sp_was") else own

    def yt_of(self, t: dict) -> str:
        return t.get("yt") or (self.ids.get(self.key(t)) or {}).get("yt", "")

    def sp_due(self, saved: dict) -> bool:
        """Whether to look for a song's Spotify id (again); a found one is only checked, once."""
        if saved.get("spotify"):
            return saved.get("sp_v") != self.SP_V
        if saved.get("sp_v") != self.SP_V:
            return True
        if saved.get("sp_nosession") and LS.spotify_session_left() > 60:
            return True                     # looked up while Spotify's search was not there: it is now
        n = int(saved.get("sp_n") or 1)
        wait = min(self.SP_AGAIN, self.SP_RETRY * 2 ** (n - 1)) if saved.get("sp_unsure") else self.SP_AGAIN
        return time.time() - float(saved.get("sp_tried") or 0) > wait

    def sp_note(self, saved: dict, sid: str, trouble: list) -> None:
        saved["spotify"] = sid
        saved["sp_v"] = self.SP_V
        if not sid:
            real = [t for t in trouble if t != NO_SESSION]
            saved["sp_tried"] = time.time()
            saved["sp_unsure"] = bool(real)
            saved["sp_nosession"] = NO_SESSION in trouble       # asked again once a session is there
            saved["sp_n"] = int(saved.get("sp_n") or 0) + 1 if real else 0   # unsure again: wait twice as long

    def look_spotify(self, t: dict, k: str = "") -> CF.Future | None:
        """Look for a song's Spotify id on the side; the lookup already running if there is one."""
        k = k or self.key(t)
        kept = (self.ids.get(k) or {}).get("spotify", "")
        if (t.get("spotify") and t["spotify"] != kept) or not self.sp_due(self.ids.get(k) or {}):
            return None                      # (the same id as kept: a queue item's copy of this lookup's)
        with self._lock:
            if ("sp|" + k) in self.busy:
                return self._sp_jobs.get(k)
            self.busy.add("sp|" + k)

        def run() -> str:
            trouble: list = []
            sid = kept if kept and not on_compilation(kept) else ""
            try:
                sid = sid or spotify_id_of(dict(t, isrcs=self.isrcs_of(t, k)), self.page, trouble) or kept
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
                self.keep_for_lyrics(t, sid)
                self.found_spotify.emit(k)
            return sid
        with self._lock:
            f = self._sp_jobs[k] = self._sp.submit(run)
        return f

    def isrcs_of(self, t: dict, k: str) -> list[str]:
        """The song's ISRCs, best first: the one its catalogue gave, else Apple Music's (the
        same answer _apple's card came in), else Deezer's by name (dz_isrc). Kept with the
        song once asked; [] where none is known."""
        if t.get("isrc"):
            return [t["isrc"]]
        saved = self.ids.get(k) or {}
        if "isrcs" in saved:
            return list(saved["isrcs"])
        import lyric_sources as LS
        codes, asked = [], True
        try:
            codes = list(LS.apple_isrcs(self._apple_meta(t)) or [])[:2]
        except Exception:                                    # noqa: BLE001
            asked = False
        if not codes:
            try:
                code = dz_isrc(t.get("src_title") or t.get("title", ""),
                               t.get("src_artist") or t.get("artist", ""), t.get("ms") or 0)
                codes = [code] if code else []
            except Exception:                                # noqa: BLE001
                asked = False
        if codes or asked:                    # neither answering is not kept as "none"
            with self._lock:
                self.ids.setdefault(k, {})["isrcs"] = codes
        return codes

    @staticmethod
    def keep_for_lyrics(t: dict, sid: str) -> None:
        """A Spotify id found for a song is kept under the song's name key too, where the lyric
        fetch for a player with no Spotify id of its own looks (LS.spotify_id_known): it goes
        to Spicy Lyrics straight away instead of walking the rest first."""
        import lyric_sources as LS
        for title, artist in {(t.get("title", ""), t.get("artist", "")),
                              (t.get("src_title") or "", t.get("src_artist") or "")}:
            if title:
                try:
                    LS.spotify_id_keep(song_key(title, artist), sid)
                except Exception:                            # noqa: BLE001
                    pass

    def want(self, t: dict, now: bool = False) -> None:
        """Resolve a song; `now` for the one asked to play, which goes before any coming up."""
        k = self.key(t)
        with self._lock:
            if self.known(t):
                return
            if k in self.busy:
                f, urgent = self._jobs.get(k) or (None, True)
                if not now or urgent or not f.cancel():
                    return                   # running already, or already first in line
            self.busy.add(k)
            self._jobs[k] = ((self._now if now else self._pool).submit(self._run, k, dict(t)), now)

    def _run(self, k: str, t: dict) -> None:
        info = None
        try:
            info = self._resolve(k, t)
        except Exception as e:                               # noqa: BLE001
            info = {"error": str(e)[:200]}
        with self._lock:
            self.busy.discard(k)
            self._jobs.pop(k, None)
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
        return {"title": t.get("title", ""), "artist": t.get("artist", ""),
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
               "ms": t.get("ms") or int((card.get("length") or 0) * 1000)}
        out["src_title"] = t.get("src_title") or t.get("title", "")      # what lookups ask by first
        out["src_artist"] = t.get("src_artist") or t.get("artist", "")
        out["src_album"] = t.get("src_album") or t.get("album", "")
        names = card.get("artists") or []
        if names:
            had = {norm(a.get("name", "")): a.get("uri", "") for a in t.get("artists") or [] if isinstance(a, dict)}
            out["artist"] = ", ".join(names)
            out["artists"] = [{"name": n, "uri": had.get(norm(n), "")} for n in names]
        return out

    @staticmethod
    def _named(meta: dict) -> bool:
        """Whether a kept Apple name is still the song asked for (2026-10-24: "Lost" was kept as LOST IN THE ECHO)."""
        return not meta.get("src_title") or LS._same_song(meta.get("title", ""), meta["src_title"])

    META_V = 1                              # Apple's name kept in streams.json: bump to ask again

    def _resolve(self, k: str, t: dict) -> dict:
        kept = self.ids.get(k) or {}
        meta = kept["meta"] if kept.get("meta_v") == self.META_V and self._named(kept["meta"]) else self._apple(t)
        if meta.get("title"):
            meta = dict(meta, title=drop_credited_feat(meta["title"], meta.get("artist") or t.get("artist", "")))
        if meta:
            t = dict(t, **{x: v for x, v in meta.items()
                           if v and (x != "art" or not t.get("art") or "ytimg.com/" in t.get("art", ""))})
        title, artist = t.get("title", ""), t.get("artist", "")
        want_len = (t.get("ms") or 0) / 1000.0
        sp = self.look_spotify(t, k)         # the whole chain can take 20s: it goes on after the song starts
        saved = dict(self.ids.get(k) or {})
        if t.get("yt"):
            saved["yt"] = t["yt"]            # a YouTube result: that upload, as picked
        tried = [saved["yt"]] if saved.get("yt") else []
        url = length = exp = None
        if saved.get("yt") and saved.get("v", 0) < PICK_V and not t.get("yt"):
            tried = []                       # picked before the release search existed: pick again
        def uploads():
            yield from tried                 # the upload picked before: no search unless it fails
            yield from [c for c in _candidates(title, artist, want_len, t.get("album", ""), bool(t.get("clean")))
                        if c not in tried][:5]
        blocked = False
        for vid in uploads():
            try:
                url, length, exp = _audio(vid)
            except YouTubeBlocked:
                blocked = True               # the rest would only be asked the same, and keep the flag up
                break
            except Exception:                                # noqa: BLE001
                continue
            if not want_len or abs(length - want_len) <= DURATION_SLACK or vid == t.get("yt"):
                saved["yt"], saved["v"] = vid, PICK_V
                break
            url = None
        if sp is not None:
            try:
                sp.result(timeout=self.SP_GRACE)             # a quick find starts the song with its id
            except Exception:                                # noqa: BLE001
                pass
        with self._lock:
            mine = self.ids.setdefault(k, {})
            if saved.get("yt"):
                mine["yt"], mine["v"] = saved["yt"], saved.get("v", 0)
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
