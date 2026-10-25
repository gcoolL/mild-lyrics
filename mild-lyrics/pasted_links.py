"""A pasted Spotify, YouTube, SoundCloud, Apple Music, TIDAL, Bandcamp, Deezer or
Qobuz link, read without Spotify or any sign-in: the song, album, artist or playlist it
is, as the home page's search results.

Notes: docs/notes/mild-lyrics/home_page.md, "Pasted links".
"""
from __future__ import annotations

import concurrent.futures as CF
import html as HTML
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple

import home_data as HD
import stream_source as SS

NAMES = {"spotify": "Spotify", "youtube": "YouTube", "soundcloud": "SoundCloud",
         "apple": "Apple Music", "tidal": "TIDAL", "bandcamp": "Bandcamp", "deezer": "Deezer", "qobuz": "Qobuz"}
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Safari/537.36")
SHORT = ("spotify.link", "spoti.fi", "on.soundcloud.com", "link.deezer.com", "deezer.page.link")
URL = re.compile(r"(?:https?://|(?<![\w.])(?=(?:[\w-]+\.)*(?:spotify|youtube|youtu|soundcloud|apple|tidal|"
                 r"bandcamp|deezer|spoti|qobuz)\.[a-z]+/))[^\s<>\"']+", re.I)
SP_URI = re.compile(r"spotify:(track|album|artist|playlist):([A-Za-z0-9]{22})")
YT_ID = re.compile(r"[A-Za-z0-9_-]{11}")
URI = re.compile(r"\b(tidal|deezer|youtube|apple|applemusic|music|qobuz):(track|song|video|album|artist|playlist):"
                 r"([A-Za-z0-9_-]+)\b", re.I)


class Link(NamedTuple):
    service: str         # or "number": a bare number, which Apple, TIDAL, Deezer and Qobuz all use
    kind: str            # track, album, artist, playlist; "short" (a short link); "id" (a bare id)
    id: str
    url: str
    cc: str = ""         # Apple's storefront, from the link


def find(text: str) -> Link | None:
    """The first link in `text` this module reads, or None. Short links come back
    as kind "short"; resolve() follows them."""
    text = text or ""
    m = SP_URI.search(text)
    if m:
        return Link("spotify", m.group(1), m.group(2), f"https://open.spotify.com/{m.group(1)}/{m.group(2)}")
    for raw in URL.findall(text):
        got = parse(raw.rstrip(").,;!?"))
        if got:
            return got
    m = URI.search(text)
    if m:
        service = {"applemusic": "apple", "music": "apple"}.get(m.group(1).lower(), m.group(1).lower())
        kind = {"song": "track", "video": "track"}.get(m.group(2).lower(), m.group(2).lower())
        return parse({"tidal": f"https://tidal.com/browse/{kind}/{m.group(3)}",
                      "deezer": f"https://www.deezer.com/{kind}/{m.group(3)}",
                      "youtube": f"https://youtu.be/{m.group(3)}",
                      "qobuz": f"https://open.qobuz.com/{kind}/{m.group(3)}",
                      "apple": f"https://music.apple.com/us/{'song' if kind == 'track' else kind}/{m.group(3)}"}[service])
    return bare(text)


def bare(text: str) -> Link | None:
    """A pasted id with nothing round it: Spotify's 22 characters, YouTube's 11, or a
    number of six digits or more (shorter ones are song names: "1999", "22")."""
    t = text.strip()
    if re.fullmatch(r"[A-Za-z0-9]{22}", t) and re.search(r"\d", t) and re.search(r"[A-Z]", t) \
            and re.search(r"[a-z]", t):
        return Link("spotify", "id", t, f"https://open.spotify.com/track/{t}")
    if YT_ID.fullmatch(t) and re.search(r"[A-Z]", t) and re.search(r"[a-z]", t) and re.search(r"[\d_-]", t):
        return Link("youtube", "track", t, f"https://www.youtube.com/watch?v={t}")
    if re.fullmatch(r"\d{6,12}", t):
        return Link("number", "id", t, t)
    return None


def parse(url: str) -> Link | None:
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    parts = [p for p in u.path.split("/") if p]
    qs = urllib.parse.parse_qs(u.query)
    if host in SHORT and parts:
        service = "spotify" if "spoti" in host else "soundcloud" if "soundcloud" in host else "deezer"
        return Link(service, "short", "", url)
    if host in ("open.spotify.com", "play.spotify.com"):
        if parts and parts[0].startswith("intl-"):
            parts = parts[1:]
        lit = SP_URI.fullmatch((qs.get("highlight") or [""])[0])
        if parts[:1] == ["album"] and lit and lit.group(1) == "track":      # a song picked on its album's page
            return Link("spotify", "track", lit.group(2), f"https://open.spotify.com/track/{lit.group(2)}")
        if len(parts) >= 2 and parts[0] in ("track", "album", "artist", "playlist") \
                and re.fullmatch(r"[A-Za-z0-9]{22}", parts[1]):
            return Link("spotify", parts[0], parts[1], url)
        return None
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "youtube-nocookie.com"):
        vid = ""
        if host == "youtu.be" and parts:
            vid = parts[0]
        elif parts[:1] == ["watch"]:
            vid = (qs.get("v") or [""])[0]
        elif len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
            vid = parts[1]
        if YT_ID.fullmatch(vid or ""):
            return Link("youtube", "track", vid, f"https://www.youtube.com/watch?v={vid}")
        lst = (qs.get("list") or [""])[0]
        if parts[:1] == ["playlist"] and re.fullmatch(r"[A-Za-z0-9_-]{10,}", lst):
            return Link("youtube", "playlist", lst, f"https://www.youtube.com/playlist?list={lst}")
        return None
    if host in ("soundcloud.com", "m.soundcloud.com"):
        if len(parts) >= 3 and parts[1] == "sets":
            return Link("soundcloud", "playlist", "/".join(parts[:3]), f"https://soundcloud.com/{'/'.join(parts[:3])}")
        if len(parts) == 2 and parts[1] not in ("tracks", "albums", "sets", "reposts", "likes", "followers",
                                                 "following", "popular-tracks", "comments"):
            return Link("soundcloud", "track", "/".join(parts), f"https://soundcloud.com/{parts[0]}/{parts[1]}")
        return None
    if host in ("music.apple.com", "itunes.apple.com", "geo.music.apple.com"):
        cc = parts[0] if parts and re.fullmatch(r"[a-z]{2}", parts[0]) else ""
        rest = parts[1:] if cc else parts
        if len(rest) < 2 or rest[0] not in ("album", "song", "artist", "playlist"):
            return None
        last = rest[-1]
        num = re.fullmatch(r"(?:id)?(\d+)", last)
        track = (qs.get("i") or [""])[0]
        if rest[0] == "album" and track.isdigit():
            return Link("apple", "track", track, url, cc or "us")
        if rest[0] == "playlist":
            return Link("apple", "playlist", last, url, cc or "us")
        if num:
            return Link("apple", {"song": "track"}.get(rest[0], rest[0]), num.group(1), url, cc or "us")
        return None
    if host in ("tidal.com", "listen.tidal.com", "embed.tidal.com"):
        if parts[:1] == ["browse"]:
            parts = parts[1:]
        if len(parts) >= 4 and parts[0] == "album" and parts[2] == "track":   # album/<id>/track/<id>: that song
            parts = parts[2:]
        if len(parts) >= 2 and parts[0].rstrip("s") in ("track", "album", "artist", "playlist"):
            kind = parts[0].rstrip("s")
            ok = r"[0-9a-f-]{36}" if kind == "playlist" else r"\d+"
            if re.fullmatch(ok, parts[1]):
                return Link("tidal", kind, parts[1], f"https://tidal.com/browse/{kind}/{parts[1]}")
        return None
    if host.endswith(".bandcamp.com") and len(parts) >= 2 and parts[0] in ("track", "album"):
        return Link("bandcamp", parts[0], parts[1], f"https://{host}/{parts[0]}/{parts[1]}")
    if host in ("open.qobuz.com", "play.qobuz.com", "qobuz.com"):
        if parts and re.fullmatch(r"[a-z]{2}-[a-z]{2}", parts[0]):
            parts = parts[1:]                   # the store: /us-en/album/<slug>/<id>, /us-en/interpreter/<slug>/<id>
            if len(parts) == 3 and parts[0] in ("album", "interpreter"):
                parts = [{"interpreter": "artist"}.get(parts[0], parts[0]), parts[2]]
        if len(parts) >= 2 and parts[0] in ("track", "album", "artist", "playlist") \
                and re.fullmatch(r"[A-Za-z0-9]+", parts[1]):
            return Link("qobuz", parts[0], parts[1], f"https://open.qobuz.com/{parts[0]}/{parts[1]}")
        return None
    if host == "deezer.com" or host.endswith(".deezer.com"):
        if parts and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", parts[0]):
            parts = parts[1:]
        if len(parts) >= 2 and parts[0] in ("track", "album", "artist", "playlist") and parts[1].isdigit():
            return Link("deezer", parts[0], parts[1], url)
    return None


# ================================================================ reading
def _page(url: str, timeout: float = 10.0) -> tuple[str, str]:
    """(where it ended up, the page), as a browser asks for it."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def _json(url: str, timeout: float = 10.0):
    return json.loads(_page(url, timeout)[1])


def _meta(page: str, name: str) -> str:
    m = re.search(r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"' % re.escape(name), page)
    return HTML.unescape(m.group(1)).strip() if m else ""


def follow(link: Link) -> Link | None:
    """A short link's long one: where the redirect lands, else the first link its page names."""
    final, page = _page(link.url)
    got = parse(final)
    if got and got.kind != "short":
        return got
    for m in URL.finditer(page):
        got = parse(HTML.unescape(m.group(0)))
        if got and got.kind != "short":
            return got
    return None


def track(name: str, artist: str, uri: str = "", art: str = "", ms: float = 0, album: str = "",
          artists: list | None = None, **extra) -> dict:
    """One song, the way the home page's rows are written."""
    return {"kind": "track", "uri": uri, "uid": "", "name": name, "sub": artist, "song": name,
            "song_by": artist, "artists": artists or [{"name": a.strip(), "uri": ""}
                                                       for a in artist.split(",") if a.strip()],
            "album": album, "album_uri": "", "art": art, "ms": int(ms or 0), **extra}


def _out(top: dict, tracks: list | None = None) -> dict:
    k = top.get("kind")
    return {"tracks": tracks if tracks is not None else ([top] if k == "track" else top.get("tracks") or []),
            "albums": [top] if k == "album" else [], "artists": [top] if k == "artist" else [],
            "playlists": [top] if k == "playlist" else [], "top": top.get("uri", ""), "top_item": top}


def _big(images) -> str:
    imgs = [i for i in images or [] if isinstance(i, dict) and i.get("url")]
    return max(imgs, key=lambda i: i.get("maxWidth") or i.get("width") or 0)["url"] if imgs else ""


def spotify(link: Link) -> dict:
    e = SS._embed(link.kind, link.id)
    art = _big((e.get("visualIdentity") or {}).get("image")) or _big((e.get("coverArt") or {}).get("sources"))
    if link.kind == "track":
        ars = [{"name": a.get("name", ""), "uri": a.get("uri", "")} for a in e.get("artists") or []]
        return _out(track(e.get("name", ""), ", ".join(a["name"] for a in ars), e.get("uri", ""), art,
                          e.get("duration") or 0, artists=ars))
    rows = [track(t.get("title", ""), re.sub(r",\s+", ", ", (t.get("subtitle") or "").replace("\xa0", " ")),
                  t.get("uri", ""), art if link.kind == "album" else "", t.get("duration") or 0,
                  album=e.get("name", "") if link.kind == "album" else "")
            for t in e.get("trackList") or [] if (t.get("uri") or "").startswith("spotify:track:")]
    item = {"kind": link.kind, "uri": e.get("uri", ""), "name": e.get("name", ""),
            "sub": "" if link.kind == "artist" else e.get("subtitle", ""), "art": art, "tracks": rows}
    return _out(item, rows)


def deezer(link: Link) -> dict:
    uri = f"deezer:{link.kind}:{link.id}"
    if link.kind == "track":
        t = SS._dz_track(_json(f"{SS.DZ}/track/{link.id}"))
        if not t:
            raise LookupError("Deezer has no such song")
        return _out(dict(t, kind="track"))
    got = {"album": SS.dz_album, "artist": SS.dz_artist, "playlist": SS.dz_playlist}[link.kind](uri)
    rows = [dict(t, kind="track") for t in got.get("tracks") or []]
    return _out(dict(got, kind=link.kind, uri=uri), rows)


def apple(link: Link) -> dict:
    if link.kind == "playlist":
        raise LookupError("Apple Music playlists can only be read signed in")
    entity = "" if link.kind == "track" else "&entity=song" + ("&limit=10" if link.kind == "artist" else "")
    got = _json(f"https://itunes.apple.com/lookup?id={link.id}&country={link.cc}{entity}").get("results") or []
    songs = [r for r in got if r.get("wrapperType") == "track" and r.get("kind") == "song"]
    if link.kind == "artist":                # an artist's lookup also brings songs they only feature on
        songs = [r for r in songs if str(r.get("artistId")) == link.id] or songs
    rows = [track(r.get("trackName", ""), r.get("artistName", ""), "", _apple_art(r), r.get("trackTimeMillis") or 0,
                  r.get("collectionName", "")) for r in songs]
    if link.kind == "track":
        if not rows:
            raise LookupError("Apple Music has no such song here")
        return _out(rows[0])
    head = next((r for r in got if r.get("wrapperType") in ("collection", "artist")), {})
    if link.kind == "album":
        item = {"kind": "album", "uri": "", "name": head.get("collectionName", ""),
                "sub": head.get("artistName", ""), "art": _apple_art(head), "tracks": rows}
    else:
        item = {"kind": "artist", "uri": "", "name": head.get("artistName", ""), "sub": "",
                "art": rows[0]["art"] if rows else "", "tracks": rows}
    if not item["name"]:
        raise LookupError("Apple Music has no such " + link.kind)
    return _out(item, rows)


def _apple_art(r: dict) -> str:
    return re.sub(r"/\d+x\d+bb\.", "/600x600bb.", r.get("artworkUrl100") or "")


def tidal(link: Link) -> dict:
    """TIDAL's share page: its tags name the song or release. An album or artist's songs
    come from the same release on Deezer; a playlist's are not on the page."""
    if link.kind == "playlist":
        raise LookupError("TIDAL playlists can only be read signed in")
    _final, page = _page(link.url)
    og, desc = _meta(page, "og:title"), _meta(page, "description")
    art = _meta(page, "og:image")
    if not og:
        raise LookupError("TIDAL has no such " + link.kind)
    if link.kind == "artist":
        return _on_deezer("artist", og, "", art)
    name = re.sub(r"^Listen to (.*) on TIDAL$", r"\1", _meta(page, "og:description"))
    artist = og[:-len(name)].rstrip(" -") if name and og.endswith(name) else og.split(" - ")[0]
    if link.kind == "album":
        return _on_deezer("album", name, artist, art)
    m = re.search(r"from the album (.*) on TIDAL$", desc)
    return _out(track(name, artist.replace(" & ", ", "), "", art, album=m.group(1) if m else ""))


def _on_deezer(kind: str, name: str, artist: str, art: str) -> dict:
    """The release or artist a page only names, found on Deezer by that name."""
    got = _try(SS.dz_search, f"{artist} {name}".strip()) or {}
    rows = got.get(kind + "s") or []
    who = SS.norm(re.split(r"\s*(?:&|,| and )\s*", artist)[0]) if artist else ""
    by = [a for a in rows if not who or who in SS.norm(a.get("sub", "") or a.get("name", ""))]
    want = SS.norm(name)
    hit = (next((a for a in by if SS.norm(a.get("name", "")) == want), None)       # the same name
           or next((a for a in by if want and (SS.norm(a.get("name", "")).startswith(want)
                                               or want.startswith(SS.norm(a.get("name", "")) or "\0"))), None))
    if hit is not None:
        return deezer(Link("deezer", kind, SS._id(hit["uri"]), ""))
    if kind == "album":                     # not on Deezer by that name: Apple's catalogue
        found = _try(_json, "https://itunes.apple.com/search?entity=album&limit=10&term="
                     + urllib.parse.quote(f"{artist} {name}")) or {}
        for r in found.get("results") or []:
            if SS.norm(r.get("collectionName", "")).startswith(want) and (
                    not who or who in SS.norm(r.get("artistName", ""))):
                return apple(Link("apple", "album", str(r["collectionId"]), "", "us"))
    raise LookupError(f"couldn’t find the songs of “{name}” anywhere that can be read")


QOBUZ_API = "https://www.qobuz.com/api.json/0.2/"
_qobuz_app: list = [""]
_qobuz_lock = threading.Lock()


def qobuz_app(fresh: bool = False) -> str:
    """The app id open.qobuz.com's own page asks Qobuz with, read from its script once a
    run (the way the Apple key is read off music.apple.com). No sign-in, no secret."""
    with _qobuz_lock:
        if _qobuz_app[0] and not fresh:
            return _qobuz_app[0]
        _final, page = _page("https://open.qobuz.com/track/1")
        src = re.search(r'src="(/resources/[^"]+/main\.js)"', page)
        if not src:
            raise LookupError("Qobuz's page has changed")
        m = re.search(r'app_id:"(\d+)"', _page("https://open.qobuz.com" + src.group(1), 20)[1])
        if not m:
            raise LookupError("Qobuz's page has changed")
        _qobuz_app[0] = m.group(1)
        return _qobuz_app[0]


def _qobuz(path: str, **args) -> dict:
    for fresh in (False, True):
        q = urllib.parse.urlencode(dict(args, app_id=qobuz_app(fresh)))
        try:
            return _json(f"{QOBUZ_API}{path}?{q}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise LookupError("Qobuz has nothing with that id") from e
            if e.code not in (400, 401) or fresh:     # an app id Qobuz no longer takes: read it again
                raise
    raise LookupError("Qobuz did not answer")


def _qb_row(t: dict, album: dict | None = None) -> dict:
    al = album or t.get("album") or {}
    name = t.get("title") or ""
    if t.get("version") and t["version"].lower() not in name.lower():
        name += f" ({t['version']})"
    who = (t.get("performer") or {}).get("name") or (al.get("artist") or {}).get("name") or ""
    return track(name, who, "", ((al.get("image") or {}).get("large") or ""), (t.get("duration") or 0) * 1000,
                 al.get("title") or "", isrc=t.get("isrc") or "")


def qobuz(link: Link) -> dict:
    if link.kind == "track":
        return _out(_qb_row(_qobuz("track/get", track_id=link.id)))
    if link.kind == "album":
        a = _qobuz("album/get", album_id=link.id)
        rows = [_qb_row(t, a) for t in (a.get("tracks") or {}).get("items") or []]
        item = {"kind": "album", "uri": "", "name": a.get("title", ""), "sub": (a.get("artist") or {}).get("name", ""),
                "art": (a.get("image") or {}).get("large", ""), "tracks": rows}
        return _out(item, rows)
    if link.kind == "playlist":
        p = _qobuz("playlist/get", playlist_id=link.id, extra="tracks", limit=100)
        rows = [_qb_row(t) for t in (p.get("tracks") or {}).get("items") or []]
        item = {"kind": "playlist", "uri": "", "name": p.get("name", ""), "sub": (p.get("owner") or {}).get("name", ""),
                "art": ((p.get("images300") or [""])[0]), "tracks": rows}
        return _out(item, rows)
    a = _qobuz("artist/get", artist_id=link.id, extra="tracks_appears_on", limit=25)
    own = [t for t in (a.get("tracks_appears_on") or {}).get("items") or []
           if str((t.get("performer") or {}).get("id")) == str(a.get("id"))]
    rows = [_qb_row(t) for t in own][:10]
    item = {"kind": "artist", "uri": "", "name": a.get("name", ""), "sub": "",
            "art": ((a.get("image") or {}).get("large") or ""), "tracks": rows}
    return _out(item, rows)


BC_API = "https://bandcamp.com/api/mobile/25/tralbum_details?band_id={}&tralbum_type={}&tralbum_id={}"


def _bandcamp(url: str) -> dict:
    _final, page = _page(url)
    m = re.search(r'name="bc-page-properties" content="([^"]+)"', page)
    band = re.search(r'data-band-id="(\d+)"', page) or re.search(r'band_id&quot;:(\d+)', page)
    if not m or not band:
        raise LookupError("not a Bandcamp song or album page")
    props = json.loads(HTML.unescape(m.group(1)))
    return _json(BC_API.format(band.group(1), props["item_type"], props["item_id"]))


def bandcamp(link: Link) -> dict:
    d = _bandcamp(link.url)
    art = f"https://f4.bcbits.com/img/a{d['art_id']}_10.jpg" if d.get("art_id") else ""
    host = urllib.parse.urlsplit(link.url).hostname
    album = d.get("title", "") if link.kind == "album" else (d.get("album_title") or "")
    rows = []
    for t in d.get("tracks") or []:
        page = t.get("track_url") or (
            f"https://{host}/track/{t['title_link'].rsplit('/', 1)[-1]}" if t.get("title_link") else
            link.url if link.kind == "track" else "")
        if page:
            rows.append(track(t.get("title", ""), t.get("band_name") or d.get("tralbum_artist", ""), "", art,
                              (t.get("duration") or 0) * 1000, album, yt=page))
    if link.kind == "track":
        if not rows:
            raise LookupError("this Bandcamp song cannot be streamed")
        return _out(rows[0])
    item = {"kind": "album", "uri": "", "name": d.get("title", ""), "sub": d.get("tralbum_artist", ""),
            "art": art, "tracks": rows}
    return _out(item, rows)


def bandcamp_audio(url: str) -> tuple[str, float, float]:
    """(stream, seconds, when it stops working) for a Bandcamp song page; read fresh each
    time, the stream link is signed and short-lived."""
    d = _bandcamp(url)
    t = next((t for t in d.get("tracks") or [] if (t.get("streaming_url") or {}).get("mp3-128")), None)
    if t is None:
        raise LookupError("no stream for this Bandcamp song")
    req = urllib.request.Request(t["streaming_url"]["mp3-128"], headers={"User-Agent": UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=10) as r:           # the redirect, followed here once
        url = r.geturl()
    return url, float(t.get("duration") or 0), time.time() + 1800


def _oembed(base: str, url: str) -> dict:
    return _json(f"{base}?format=json&url={urllib.parse.quote(url, safe='')}")


def youtube(link: Link, clean) -> dict:
    if link.kind == "track":
        o = _oembed("https://www.youtube.com/oembed", link.url)
        raw = o.get("title") or ""
        channel = re.sub(r"\s*-\s*Topic$|VEVO$", "", o.get("author_name") or "")
        title, artist = SS.song_of_video(raw, channel, clean)
        return _out(track(raw, channel, f"youtube:video:{link.id}", f"https://i.ytimg.com/vi/{link.id}/hqdefault.jpg",
                          0, song=title, song_by=artist, yt=link.id, video=raw))
    with SS._ytdl({"extract_flat": "in_playlist", "noplaylist": False, "playlistend": 100}) as y:
        got = y.extract_info(link.url, download=False)
    rows = []
    for e in got.get("entries") or []:
        vid = e.get("id") or ""
        if not YT_ID.fullmatch(vid):
            continue
        raw = e.get("title") or ""
        channel = re.sub(r"\s*-\s*Topic$|VEVO$", "", e.get("channel") or e.get("uploader") or "")
        title, artist = SS.song_of_video(raw, channel, clean)
        rows.append(track(raw, channel, f"youtube:video:{vid}", f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                          float(e.get("duration") or 0) * 1000, song=title, song_by=artist, yt=vid, video=raw))
    item = {"kind": "playlist", "uri": "", "name": got.get("title") or "YouTube playlist",
            "sub": got.get("channel") or got.get("uploader") or "", "art": rows[0]["art"] if rows else "",
            "tracks": rows}
    return _out(item, rows)


def soundcloud(link: Link) -> dict:
    if link.kind == "track":
        with SS._ytdl({}) as y:
            e = y.extract_info(link.url, download=False, process=False)
        return _out(_sc_row(e, link.url))
    with SS._ytdl({"extract_flat": "in_playlist", "noplaylist": False, "playlistend": 100}) as y:
        got = y.extract_info(link.url, download=False)
    urls = [e.get("url") for e in got.get("entries") or [] if e.get("url")]
    with CF.ThreadPoolExecutor(6) as ex:
        heads = list(ex.map(lambda u: _try(_oembed, "https://soundcloud.com/oembed", u), urls))
    rows = []
    for u, o in zip(urls, heads):
        if not o:
            continue
        who = o.get("author_name") or ""
        name = re.sub(r"\s+by\s+%s$" % re.escape(who), "", o.get("title") or "") if who else o.get("title", "")
        rows.append(track(name, who, "", o.get("thumbnail_url") or "", 0, got.get("title", ""), yt=u))
    item = {"kind": "playlist", "uri": "", "name": got.get("title") or "SoundCloud set",
            "sub": got.get("uploader") or "", "art": rows[0]["art"] if rows else "", "tracks": rows}
    return _out(item, rows)


def _sc_row(e: dict, url: str) -> dict:
    thumbs = e.get("thumbnails") or []
    art = e.get("thumbnail") or (thumbs[-1].get("url") if thumbs else "")
    return track(e.get("title") or "", e.get("uploader") or e.get("artist") or "", "", art,
                 float(e.get("duration") or 0) * 1000, yt=url)


def _try(fn, *a):
    try:
        return fn(*a)
    except Exception:                                        # noqa: BLE001
        return None


def resolve(link: Link, clean=lambda t, a: (t, a)) -> dict:
    """The results a link stands for; raises with a reader's message when it cannot be read."""
    if link.kind == "short":
        long = follow(link)
        if long is None:
            raise LookupError(f"that {NAMES[link.service]} short link leads nowhere this can read")
        link = long
    if link.service == "number":
        return numbered(link.id)
    if link.service == "spotify" and link.kind == "id":
        try:
            return spotify(link._replace(kind="track"))
        except Exception:                                    # noqa: BLE001
            return spotify(link._replace(kind="album", url=f"https://open.spotify.com/album/{link.id}"))
    if link.service == "spotify":
        return spotify(link)
    if link.service == "youtube":
        return youtube(link, clean)
    if link.service == "soundcloud":
        return soundcloud(link)
    return {"apple": apple, "tidal": tidal, "bandcamp": bandcamp, "deezer": deezer,
            "qobuz": qobuz}[link.service](link)


def numbered(num: str) -> dict:
    """A bare number: asked of Apple Music, TIDAL, Deezer and Qobuz at once. One that answers is
    the song; more than one, and they are all offered, `choices` set, to be picked from."""
    asks = {"deezer": Link("deezer", "track", num, f"https://www.deezer.com/track/{num}"),
            "tidal": Link("tidal", "track", num, f"https://tidal.com/browse/track/{num}"),
            "apple": Link("apple", "id", num, "", "us"),
            "qobuz": Link("qobuz", "track", num, f"https://open.qobuz.com/track/{num}")}
    with CF.ThreadPoolExecutor(4) as ex:
        jobs = {k: ex.submit(apple_id if k == "apple" else resolve, l) for k, l in asks.items()}
        got = {k: _try(j.result) for k, j in jobs.items()}
    got = {k: g for k, g in got.items() if g and g.get("top_item")}
    if not got:
        raise LookupError(f"no song on Apple Music, TIDAL, Deezer or Qobuz has the id {num}")
    if len(got) == 1:
        return next(iter(got.values()))
    same = {(SS.norm(g["top_item"].get("name", "")), SS.norm(g["top_item"].get("sub", "").split(",")[0]))
            for g in got.values()}
    if len(same) == 1:
        return next(iter(got.values()))
    tops = [dict(g["top_item"], sub=f"{g['top_item'].get('sub') or g['top_item'].get('kind', '').title()}"
                                    f" · {NAMES[k]}") for k, g in got.items()]
    of = lambda kind: [t for t in tops if t.get("kind") == kind]
    return {"tracks": of("track"), "albums": of("album"), "artists": of("artist"), "playlists": [], "top": "",
            "top_item": None, "choices": True}


def apple_id(link: Link) -> dict:
    """An Apple id with no link round it: whatever it is, a song, an album or an artist."""
    got = _json(f"https://itunes.apple.com/lookup?id={link.id}&country={link.cc}").get("results") or []
    kind = {"track": "track", "collection": "album", "artist": "artist"}.get((got or [{}])[0].get("wrapperType"))
    if kind is None:
        raise LookupError("Apple Music has nothing with that id")
    return apple(link._replace(kind=kind))


def on_spotify(got: dict, search) -> dict:
    """A catalogue song from elsewhere, swapped for the same song's Spotify uri where
    Spotify finds it, so it plays where Spotify songs play. Uploads stay as they are."""
    top = got.get("top_item") or {}
    if top.get("kind") != "track" or top.get("yt") or (top.get("uri") or "").startswith("spotify:"):
        return got
    title, artist = top.get("song") or top.get("name", ""), (top.get("song_by") or top.get("sub", ""))
    ms = top.get("ms") or 0
    rows = search(f"{title} {artist.split(',')[0]}") or []
    sid = SS._match_rows(rows, title, artist, ms)
    if not sid:                              # Spotify's search did not name it: by the recording's ISRC
        code = top.get("isrc") or _try(SS.dz_isrc, title, artist, ms)
        sid = _try(SS.spotify_by_isrc, [code], title, ms) if code else ""
    if not sid:
        return got
    hit = dict(top, uri=f"spotify:track:{sid}")
    return dict(got, tracks=[hit], top=hit["uri"], top_item=hit)


class Links(HD.Spot):
    """Pasted links, answered with the same keys and shapes as a catalogue's search."""

    def __init__(self, clean, spotify_search=None, wants_spotify=lambda: False) -> None:
        super().__init__(lambda job: job(), lambda u: u)
        self.clean = clean
        self.spotify_search = spotify_search
        self.wants_spotify = wants_spotify

    def answer(self, q: str) -> dict:
        link = find(q)
        if link is None:
            return {"tracks": [], "artists": [], "albums": [], "playlists": [], "top": "",
                    "error": "not a link this can read"}
        try:
            got = resolve(link, self.clean)
        except Exception as e:                               # noqa: BLE001
            msg = str(e) if isinstance(e, LookupError) else f"{NAMES[link.service]} did not answer"
            return {"tracks": [], "artists": [], "albums": [], "playlists": [], "top": "", "error": msg,
                    "service": link.service}
        if self.spotify_search is not None and self.wants_spotify():
            got = _try(on_spotify, got, self.spotify_search) or got
        return dict(got, service=link.service if link.service != "number" else "")

    def search(self, q: str):
        self.want_only("search:" + q, lambda: self.answer(q), keep=600)

    def lookup(self, q: str):
        self.want("search:" + q, lambda: self.answer(q), keep=600)

    def found(self, q: str) -> dict | None:
        return self.get("search:" + q)
