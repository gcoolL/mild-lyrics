"""A song's music video behind the lyrics (Background "video"): found on YouTube, played muted at
up to 720p, kept in step with the audio by the caption shift map. Notes: docs/notes/mild-lyrics/music_video.md.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import threading
import time

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal

import noconsole
import yt_captions as YC

FMT = "bestvideo[height<=720][vcodec^=avc1]/bestvideo[height<=720]/best[height<=720]"
WIDE = 640                 # frames are kept this wide: the wall is drawn smaller still, and soft
KEEP_FOR = 7 * 86400       # which video a song has, kept this long
KEEP_NONE = 86400          # ...and that it has none: a wrong "none" heals in a day
PICK_V = 10                # picks made by an older pick() are asked again (v1 took fan lyric videos,
                           # v2 a still cover with audio under it: Take Me To The Beach; v3 kept a
                           # failed check as "no video" for a week: The Search; v5 took a channel
                           # only named like the artist: "NFRealMuic" for Mansion; v6 passed over
                           # collab uploads, label and artist: Heathens; v7 a visualiser, one picture
                           # with a pulse over it: One Night Only; v8 a longer title holding the
                           # song's words: LOST IN THE ECHO for Lost; v9 an album's track uploaded
                           # under a title card: "Minecraft Volume Alpha - 11 - Mice on Venus")
STILL_SHARE = 0.6          # this share of a video's storyboard frames looking alike: a still picture, not a video
STILL_OFF = 8.0            # ...where alike is a mean difference under this, 0-255, frames shrunk to 8x8
DRIFT = 0.35               # the picture is shown while it is this near the audio
LEAD = 5.0                 # a seek aims this far ahead at first (it stalls while it fetches); learnt after
# Settings ▸ Background ▸ Video cuts. What editors use (2026-10-22, docs notes): a flash to white
# (music videos, cuts on the beat), a dip to black, a zoom punch, a glitch, a cross-fade, a hard cut.
CUT_EFFECTS = ["flash", "dip", "zoom", "glitch", "fade", "cut"]
FX = {"flash": (0.04, 0.40), "dip": (0.22, 0.35), "zoom": (0.04, 0.35), "glitch": (0.03, 0.30)}
#     (rise to its height, fall from the switch); dip rises before the switch, the rest peak at it
FADE = 0.6                 # fade: a cut cross-fades, and the picture fades in and out, over this long
CUT_LEAD = 0.35            # a cut the map knows of is noticed this far ahead (one poll is 250ms)
DISK_LAND = 0.1            # ...and, from a file, sought this long before the song gets there (a seek's landing)
LAND = 8.0                 # the longest a seek is waited for before it is tried again
SONG_LEAD = 0.1            # a song-clock file's seek aims this far on at first; learnt from its frames
STILL_PART = 0.45          # a visualiser: this share of the picture (bars trimmed) alike in all three previews
SAME_LEN = 3.0             # no captions: a video this near the song's length runs on its clock
NOT_IT = re.compile(r"\b(lyrics?|audio|visuali[sz]er|live|cover|remix|slowed|sped|reverb|karaoke|reaction|"
                    r"8d|nightcore|instrumental|teaser|trailer|behind the scenes|making of|"
                    r"dance practice|choreograph\w*|performance|acoustic|tutorial|letra|legendad\w*|"
                    r"sessions?|songline|unplugged|tiny desk|interview|commentary|rehearsal|in studio|"
                    r"traduc\w*|paroles|vietsub|engsub|eng sub|sub espa\w*|перевод|текст)\b"
                    r"|가사|해석|歌詞|和訳|翻訳|中字|中文|翻译|字幕", re.I)    # lyric videos, also as fans title them
FILLER = {"official", "music", "video", "videoclip", "clip", "mv", "m", "v", "hd", "hq", "4k", "uhd", "remastered",
          "remaster", "feat", "ft", "featuring", "prod", "explicit", "clean"}
TRACK_NO = re.compile(r"(?:^|[-–—|:]\s*)(?:track\s*)?#?\d{1,2}\s*(?:[-–—|:.]\s|$)", re.I)  # "Album - 11 - Song"
OFFICIAL = re.compile(r"official\s+(?:music\s+)?video|music\s+video|\bm/?v\b", re.I)
FILM = re.compile(r"official\s+(?:[\w-]+\s+){0,2}video|short\s+film", re.I)   # "Thriller (Official 4K Video)"
FILM_MAX = 45 * 60         # a short film the song is in (Thriller's is 13:42), matched by its sound
LOG: list = [None]         # the window's follow_log("video", …), so a report can be read off follow.log


def log(ev: str, **kw) -> None:
    if LOG[0] is not None:
        try:
            LOG[0](ev, **kw)
        except Exception:                                # noqa: BLE001
            pass


def _squash(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").casefold())


def _words(s: str) -> list[str]:
    return re.findall(r"[^\W_]+", re.sub(r"['’]", "", (s or "").casefold()))


def _titled(raw: str, need: list[str], people: set[str]) -> bool:
    """Whether the song's words stand on their own in a video title: "Linkin Park - Lost (Official…)",
    not "LOST IN THE ECHO". Beside them only punctuation, the artist's words or FILLER."""
    toks = re.findall(r"[^\W_]+|[^\w\s]", re.sub(r"(?<=\w)['’](?=\w)", "", (raw or "").casefold()))
    n = len(need)
    for i in range(len(toks) - n + 1):
        if toks[i:i + n] != need:
            continue
        near = [toks[i - 1] if i else "", toks[i + n] if i + n < len(toks) else ""]
        if all(not t or not re.match(r"[^\W_]", t) or t in people or t in FILLER for t in near):
            return True
    return False


def pick(rows: list, title: str, artist: str, length: float) -> str:
    """The best of ranked()."""
    got = ranked(rows, title, artist, length)
    return got[0] if got else ""


def ranked(rows: list, title: str, artist: str, length: float, why: list | None = None,
           long_ok: bool = False) -> list[str]:
    """The official video among YouTube's results: this song by this artist, not a lyric video,
    a live cut or a cover, and a length the song fits in (videos add intros, not minutes; with
    `long_ok`, when its sound can be matched, a short film calling itself one comes last). Only
    from the artist's own channel (named for them, with the ♪ Official Artist Channel badge, or
    their verified VEVO), or a verified one that calls it the official video: a fan's upload
    titled "(Official Video)" is still a fan's upload. Never a "- Topic" channel (audio), nor an
    album's track numbered in its title (an upload of the record under a title card).
    `why` gets (id, reason) for each result turned down."""
    no = (lambda r, reason: why.append((r.get("id"), reason))) if why is not None else (lambda r, reason: None)
    name = re.sub(r"\s*[\(\[].*$", "", title or "").strip() or title
    need = _words(name)
    people = [_squash(a) for a in re.split(r",|&|\bfeat\.?|\bft\.?|\bwith\b|\bx\b", artist or "") if _squash(a)]
    named = set(_words(artist))
    scored = []
    for r in rows:
        raw, channel, dur = r.get("title") or "", r.get("channel") or "", float(r.get("duration") or 0)
        film = bool(length and long_ok and length + 240 < dur <= FILM_MAX and FILM.search(raw))
        if not r.get("id") or dur < 60 or (length and not (length - 10 <= dur <= length + 240) and not film):
            no(r, f"length {dur:.0f}s")
            continue
        if re.search(r"-\s*Topic$", channel):
            no(r, "topic")
            continue
        if not need or not _titled(raw, need, named):
            no(r, "title")
            continue
        if NOT_IT.search(raw) and not NOT_IT.search(title or ""):
            no(r, "not-it:" + NOT_IT.search(raw).group(0).lower())
            continue
        if TRACK_NO.search(raw) and not TRACK_NO.search(title or ""):
            no(r, "track-number")
            continue
        where = _squash(raw + " " + channel)
        if people and not any(p in where for p in people):
            no(r, "artist")
            continue
        owners = r.get("collab") or [{"channel": channel, "artist": r.get("artist"), "verified": r.get("verified")}]
        own = any(_own(o, people) for o in owners)    # a collab upload (label and artist): each co-owner
        if not own and not (any(o.get("verified") for o in owners) and OFFICIAL.search(raw)):
            no(r, f"channel:{channel[:30]}")
            continue
        scored.append(((not film, own, bool(OFFICIAL.search(raw)), int(r.get("view_count") or 0)), r["id"]))
    return [vid for _s, vid in sorted(scored, key=lambda x: x[0], reverse=True)]


def _own(o: dict, people: list) -> bool:
    """A channel named for the artist with the ♪ badge, or its verified VEVO."""
    name = _squash(o.get("channel"))
    named = bool(people) and any(name.startswith(p) for p in people)   # FettyWapVEVO too
    badge = o.get("artist")              # None: yt-dlp gave no badges to read, so the ✓ has to do
    return named and bool(badge or (badge is None and o.get("verified")) or (o.get("verified") and name.endswith("vevo")))


def still_share(data: bytes, cols: int, rows: int, n: int) -> float:
    """The share of a storyboard sheet's frames that look like its most usual frame."""
    from PyQt6.QtGui import QImage
    img = QImage.fromData(data)
    if img.isNull() or n < 2:
        return 0.0
    small = img.scaled(cols * 8, rows * 8, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB888)
    raw, bpl = small.constBits().asstring(small.sizeInBytes()), small.bytesPerLine()
    tiles = []
    for k in range(min(n, rows * cols)):
        r, c = divmod(k, cols)
        tiles.append([raw[(r * 8 + y) * bpl + c * 24 + x] for y in range(8) for x in range(24)])
    usual = [sorted(t[i] for t in tiles)[len(tiles) // 2] for i in range(192)]
    off = [sum(abs(a - b) for a, b in zip(t, usual)) / 192 for t in tiles]
    return sum(o < STILL_OFF for o in off) / len(off)


def moving(info: dict) -> bool | None:
    """Whether a video's picture moves, read off its storyboard (YouTube's frame previews across
    the whole video, one small image); None where there is none to read, which is not a no."""
    import urllib.request
    boards = [f for f in info.get("formats") or [] if str(f.get("format_id", "")).startswith("sb")
              and f.get("fragments") and f.get("rows") and f.get("columns")]
    if not boards:
        return None
    f = next((b for b in boards if b["format_id"] == "sb2"), boards[0])
    n = int(round(float(info.get("duration") or 0) * float(f.get("fps") or 0)))
    try:
        req = urllib.request.Request(f["fragments"][0]["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
    except Exception:                                    # noqa: BLE001
        return None
    return still_share(data, int(f["columns"]), int(f["rows"]), n or int(f["rows"]) * int(f["columns"])) < STILL_SHARE


BLOCKED = [0.0]            # until when YouTube is not asked (it answered "confirm you're not a bot")


def _block_file() -> pathlib.Path:
    import lyric_sources as LS
    return LS.cache_root() / "youtube-blocked.json"


V4_ONLY = [0.0]            # until when YouTube is asked over IPv4 only (it flagged the IPv6 address)


def _blocked(e: Exception, v4: bool = False) -> bool:
    """Take a refusal in. True when it is worth asking once more, now over IPv4: YouTube flags
    addresses one at a time, and on 2026-10-22 it flagged an IPv6 address while IPv4 still answered."""
    if "not a bot" not in str(e):
        return False
    again = not v4                          # `v4`: that ask went out over IPv4 (asks run at once)
    if again:
        V4_ONLY[0] = max(V4_ONLY[0], time.time() + 1800.0)
    else:
        BLOCKED[0] = time.time() + 1800.0
    try:                        # kept across restarts: each start used to ask again (2026-10-22)
        _block_file().parent.mkdir(parents=True, exist_ok=True)
        _block_file().write_text(json.dumps({"until": BLOCKED[0], "v4_until": V4_ONLY[0]}))
    except Exception:                                    # noqa: BLE001
        pass
    return again


def _load_block() -> None:
    try:
        got = json.loads(_block_file().read_text())
    except Exception:                                    # noqa: BLE001
        return
    for box, key in ((BLOCKED, "until"), (V4_ONLY, "v4_until")):
        try:
            until = float(got.get(key) or 0.0)
        except (TypeError, ValueError):
            continue
        if time.time() < until < time.time() + 1800.0:
            box[0] = until


_load_block()


def still_thumbs(vid: str) -> bool | None:
    """Whether a video is one still picture, or one with a little motion over it (a visualiser), by
    YouTube's three preview frames (1/2/3.jpg, from about a quarter, half and three quarters in):
    plain images, no page lookup, no bot check. None where they cannot be read."""
    import urllib.request
    from PyQt6.QtGui import QImage
    frames = []
    for n in (1, 2, 3):
        try:
            req = urllib.request.Request(f"https://i.ytimg.com/vi/{vid}/mq{n}.jpg", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                img = QImage.fromData(r.read())
        except Exception:                                # noqa: BLE001
            return None
        if img.isNull():
            return None
        frames.append(img)
    return still_part(frames) >= STILL_PART


def still_part(frames: list, w: int = 32, h: int = 18) -> float:
    """The share of the picture alike in every frame, letterbox and pillarbox bars trimmed first.
    Measured 2026-10-23: real music videos 0.00-0.37, a still cover 1.0, visualisers 0.46-1.00."""
    import itertools
    from PyQt6.QtGui import QImage
    px = []
    for img in frames:
        img = img.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB888)
        raw, bpl = img.constBits().asstring(img.sizeInBytes()), img.bytesPerLine()
        px.append([[raw[y * bpl + x * 3:y * bpl + x * 3 + 3] for x in range(w)] for y in range(h)])
    same = [[max(abs(a[c] - b[c]) for a, b in itertools.combinations([f[y][x] for f in px], 2) for c in range(3)) < 12
             for x in range(w)] for y in range(h)]

    def bar(pts) -> bool:                    # a plain line that never changes, whatever its colour
        cols = [px[0][y][x] for y, x in pts]
        return all(same[y][x] for y, x in pts) and all(max(p[c] for p in cols) - min(p[c] for p in cols) < 30
                                                       for c in range(3))
    top, bot, lef, rig = 0, h, 0, w
    while bot - top > 1 and bar([(top, x) for x in range(lef, rig)]):
        top += 1
    while bot - top > 1 and bar([(bot - 1, x) for x in range(lef, rig)]):
        bot -= 1
    while rig - lef > 1 and bar([(y, lef) for y in range(top, bot)]):
        lef += 1
    while rig - lef > 1 and bar([(y, rig - 1) for y in range(top, bot)]):
        rig -= 1
    inner = [same[y][x] for y in range(top, bot) for x in range(lef, rig)]
    return sum(inner) / len(inner)


_STILL: dict = {}           # vid -> still_thumbs(vid), once an answer is had


def picture_of(upload: str) -> str:
    """The song's own upload as its video, or "" where that is one still picture (YouTube Music's
    art tracks, which autoplay's radio queues): its music video is then searched for."""
    if upload and _STILL.get(upload) is None:
        _STILL[upload] = still_thumbs(upload)
    return upload if upload and _STILL[upload] is not True else ""


def _read_artist_badge() -> None:
    """Have yt-dlp's search results say whether the channel is an Official Artist Channel
    (`channel_is_artist`): it files that badge and the plain ✓ both as "verified"."""
    try:
        from yt_dlp.extractor.youtube import _tab
        cls = _tab.YoutubeTabBaseInfoExtractor
        orig = cls._extract_video
    except Exception:                                    # noqa: BLE001
        return
    if getattr(orig, "_mild", False):
        return

    def read(self, renderer):
        e = orig(self, renderer)
        if isinstance(e, dict) and isinstance(renderer, dict):
            marks = [b.get("metadataBadgeRenderer") or {} for b in renderer.get("ownerBadges") or [] if isinstance(b, dict)]
            e["channel_is_artist"] = any(m.get("style") == "BADGE_STYLE_TYPE_VERIFIED_ARTIST"
                                         or (m.get("icon") or {}).get("iconType") == "OFFICIAL_ARTIST_BADGE" for m in marks)
            e["collab"] = _collab(renderer)
        return e
    read._mild = True
    cls._extract_video = read


def _collab(renderer: dict) -> list:
    """A collab upload's co-owners ("Fueled By Ramen and twenty one pilots"), each with its own
    badge: the upload has none of its own, so they sit in the byline's Collaborators dialog."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            item = x.get("listItemViewModel")
            if isinstance(item, dict) and isinstance(item.get("title"), dict):
                icons = {((s.get("clientResource") or {}).get("imageName") or "")
                         for a in item["title"].get("attachmentRuns") or [] if isinstance(a, dict)
                         for s in ((((a.get("element") or {}).get("type") or {}).get("imageType") or {})
                                   .get("image") or {}).get("sources") or [] if isinstance(s, dict)}
                artist = bool(icons & {"AUDIO_BADGE", "OFFICIAL_ARTIST_BADGE"})
                out.append({"channel": item["title"].get("content") or "", "artist": artist,
                            "verified": artist or "CHECK_CIRCLE_FILLED" in icons})
                return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk((renderer.get("longBylineText") or {}).get("runs") or [])
    return out


def find(title: str, artist: str, length: float) -> str:
    """Ask YouTube for the song's music video; its id, or "". The best three are looked at in
    turn, and one whose picture barely moves (a still cover under the audio) is passed over."""
    import stream_source as SS
    if time.time() < BLOCKED[0]:
        raise RuntimeError("YouTube asked to confirm we are not a bot: not asked for a while")
    _read_artist_badge()
    with SS._ytdl({"extract_flat": "in_playlist"}) as y:
        lead = re.split(r",|&|\bfeat\.?|\bft\.?|\bwith\b|\bx\b", artist or "")[0].strip()
        name = re.sub(r"\s*[\(\[].*$", "", title or "").strip() or title     # not "(feat. …)" or a cut's name
        got = y.extract_info(f"ytsearch8:{lead} {name} official music video", download=False) or {}
    rows = [{"id": e.get("id"), "title": e.get("title"), "duration": e.get("duration"),
             "view_count": e.get("view_count"), "verified": bool(e.get("channel_is_verified")),
             "artist": e.get("channel_is_artist"),
             "collab": e.get("collab") or [],
             "channel": e.get("channel") or e.get("uploader") or ""}
            for e in got.get("entries") or []]
    if not rows:
        raise RuntimeError("YouTube's search came back empty")     # not "no video": asked again
    why: list = []
    import audio_analysis as AA
    best = ranked(rows, title, artist, length, why, long_ok=can_build() and not AA.usable())
    for vid in best[:3]:
        if still_thumbs(vid) is not True:  # (2026-10-22: a page lookup each got the IP bot-checked)
            return vid
        why.append((vid, "still picture"))
    log("no-video", title=title, artist=artist, length=round(length, 1), results=len(rows),
        why=[f"{v}:{r}" for v, r in why][:8])
    return ""


_STREAMS: dict = {}         # vid -> (link, seconds, when the link stops working): one lookup per video
AUDIO: dict = {}            # vid -> its smallest sound-only link, from the same lookup (audio_map)
_STREAM_LOCK = threading.Lock()


def stream(vid: str, fresh: bool = False) -> tuple[str, float]:
    """(picture-only stream link, seconds long) for a video; its caption links go to YC.LINKS.
    Kept until ten minutes before the link expires, so the player and the Store share one lookup
    (each is a page YouTube counts towards its bot check); `fresh` for a link that has gone stale."""
    with _STREAM_LOCK:                                   # (the Store and the next song's map at once: one lookup)
        kept = _STREAMS.get(vid)
        if kept and not fresh and kept[2] - time.time() > 600:
            return kept[0], kept[1]
        import stream_source as SS
        if time.time() < BLOCKED[0]:
            raise RuntimeError("YouTube asked to confirm we are not a bot: not asked for a while")
        v4 = time.time() < V4_ONLY[0]
        try:
            with SS._ytdl({"format": FMT}) as y:
                info = y.extract_info("https://www.youtube.com/watch?v=" + vid, download=False) or {}
        except Exception as e:                           # noqa: BLE001
            if not _blocked(e, v4):
                raise
            try:
                with SS._ytdl({"format": FMT}) as y:     # once more, over IPv4
                    info = y.extract_info("https://www.youtube.com/watch?v=" + vid, download=False) or {}
            except Exception as e2:                      # noqa: BLE001
                _blocked(e2, True)
                raise
        YC.LINKS[vid] = YC.links_of(info)
        sound = [f for f in info.get("formats") or [] if f.get("url") and f.get("vcodec") == "none"
                 and f.get("acodec") not in (None, "none") and str(f.get("protocol") or "https").startswith("http")]
        if sound:
            AUDIO[vid] = min(sound, key=lambda f: float(f.get("abr") or f.get("tbr") or 1e9))["url"]
        url, length = info.get("url") or "", float(info.get("duration") or 0)
        exp = re.search(r"[?&]expire=(\d+)", url)
        if url:
            _STREAMS[vid] = (url, length, float(exp.group(1)) if exp else time.time() + 3600)
    return url, length


class Finder:
    """Which video a song has, kept on disk (an empty answer too, for KEEP_FOR)."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path, self._lock = path, threading.Lock()
        try:
            self.known = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            self.known = {}

    def video_of(self, key: str, title: str, artist: str, length: float) -> str | None:
        """`key` is song_key(title, artist)."""
        """Its id, "" for none; None where YouTube could not be asked (asked again next time)."""
        got = self.known.get(key)
        if got and got.get("v") == PICK_V and \
                time.time() - float(got.get("at") or 0) < (KEEP_FOR if got.get("vid") else KEEP_NONE):
            return got.get("vid") or ""
        try:
            vid = find(title, artist, length)
        except Exception:                                # noqa: BLE001
            return None
        with self._lock:
            self.known[key] = {"vid": vid, "at": time.time(), "v": PICK_V}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.known), encoding="utf-8")
            except OSError:
                pass
        return vid


def clock_map(body, vid: str, video_len: float, song_len: float, cache: pathlib.Path,
              song_src: str = "") -> list | None:
    """Stretches mapping the song's seconds onto the video's; None where they cannot be told.
    By its sound against the song's (`song_src`, what our player plays), else by its captions,
    which are less exact (uploaded subtitles lead by ~0.2s)."""
    try:
        runs = audio_map(vid, song_src, song_len, cache) if song_src else []
    except Exception:                                    # noqa: BLE001
        runs = []                                        # (no lookup to be had: the bot check)
    if runs:
        return runs
    caps = YC.captions(vid, cache)
    base = YC._base_words(YC._items(YC.SL.payload(body))) if body else []
    runs = YC.stretches(base, caps) if base and (caps.get("words") or caps.get("lines")) else []
    if runs:
        return runs
    if video_len and song_len and abs(video_len - song_len) <= SAME_LEN:
        return [(0.0, float("inf"), 0.0)]
    return None


def kept_map(vid: str, song_len: float, cache: pathlib.Path) -> list | None:
    """The sound map audio_map() kept for this video and song length, read with no lookup."""
    try:
        got = json.loads((cache / f"{vid}.audio.json").read_text(encoding="utf-8")).get(f"{song_len:.0f}")
    except Exception:                                    # noqa: BLE001
        return None
    if got and time.time() - float(got.get("at") or 0) < KEEP_FOR:
        return [tuple(r) for r in got["runs"]]
    return None


def video_len(vid: str) -> float:
    """A video's length, from a stream() lookup already made (0 where none was)."""
    kept = _STREAMS.get(vid)
    return float(kept[1]) if kept else 0.0


def audio_map(vid: str, song_src: str, song_len: float, cache: pathlib.Path) -> list:
    """The video's sound found in the song's (2026-10-22: Leave a Light On's video has no
    captions and a 12.5s intro). Kept on disk per song length; a miss is not kept, since the
    player's source may still have been the last song's."""
    import audio_analysis as AA
    path, at = cache / f"{vid}.audio.json", f"{song_len:.0f}"
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        kept = {}
    got = kept.get(at)
    if got and time.time() - float(got.get("at") or 0) < KEEP_FOR:
        return [tuple(r) for r in got["runs"]]
    if AA.usable():
        return []
    if vid not in AUDIO:
        stream(vid)                                      # (a video played from disk: one lookup, kept)
    if not AUDIO.get(vid):
        return []
    t0, took, got = time.monotonic(), {}, {}

    def dec(name, src):                                  # (both at once: each is mostly waiting on the network)
        got[name] = AA.decode(src, AA.MATCH_SR)
        took[name] = round(time.monotonic() - t0, 2)
    th = threading.Thread(target=dec, args=("video", AUDIO[vid]), daemon=True)
    th.start()
    dec("song", song_src)
    th.join()
    song, sound = got.get("song"), got.get("video")
    t1 = time.monotonic()
    runs = AA.match(song, sound) if song is not None and sound is not None else []
    log("audio-map", vid=vid, song=took.get("song"), video=took.get("video"),
        match=round(time.monotonic() - t1, 2), found=len(runs))
    if runs:
        kept[at] = {"at": time.time(), "runs": runs}
        try:
            cache.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(kept), encoding="utf-8")
        except OSError:
            pass
    return runs


_NP: list = []


def _np():
    """numpy, or None (it is optional: Settings' visualiser for other players brings it)."""
    if not _NP:
        try:
            import numpy
            _NP.append(numpy)
        except Exception:                                # noqa: BLE001
            _NP.append(None)
    return _NP[0]


def _rgb(kind: str, w: int, h: int, planes: list):
    """NV12 / I420 planes as a QImage, BT.709 limited range (what HD video is); halved when
    wider than WIDE (a song-clock file is WIDE already)."""
    from PyQt6.QtGui import QImage
    np = _np()
    s, hc, wc = (2 if w > WIDE else 1), (h + 1) // 2, (w + 1) // 2
    (yb, ys) = planes[0]
    y = np.frombuffer(yb, np.uint8)[: ys * h].reshape(h, ys)[:h:s, :w:s].astype(np.float32)
    h2, w2 = y.shape
    if kind == "nv12":
        ub, us = planes[1]
        uv = np.frombuffer(ub, np.uint8)[: us * hc].reshape(hc, us)[:, : wc * 2]
        u, v = uv[:, 0::2], uv[:, 1::2]
    else:
        (ub, us), (vb, vs) = planes[1], planes[2]
        u = np.frombuffer(ub, np.uint8)[: us * hc].reshape(hc, us)[:, :wc]
        v = np.frombuffer(vb, np.uint8)[: vs * hc].reshape(hc, vs)[:, :wc]
    if s == 1:                                           # chroma is half size: each sample twice
        u, v = (c.repeat(2, 0).repeat(2, 1) for c in (u, v))
    u, v = u[:h2, :w2].astype(np.float32), v[:h2, :w2].astype(np.float32)
    y, u, v = (y - 16.0) * 1.164, u - 128.0, v - 128.0
    rgb = np.empty((h2, w2, 3), np.float32)
    rgb[..., 0] = y + 1.793 * v
    rgb[..., 1] = y - 0.213 * u - 0.533 * v
    rgb[..., 2] = y + 2.112 * u
    out = np.ascontiguousarray(np.clip(rgb, 0, 255).astype(np.uint8))
    return QImage(out.data, w2, h2, w2 * 3, QImage.Format.Format_RGB888).copy()


class MusicVideo(QObject):
    """The muted player and its newest frame, as a QImage at most WIDE across."""

    changed = pyqtSignal()
    _done = pyqtSignal(object, int, float)

    def __init__(self) -> None:
        super().__init__()
        self.player = self.sink = None
        self.image = None           # the newest frame, None while there is nothing to show
        self.prev = None            # the picture before a cut (held, then faded under the new one) or
        self.prev_at = None         # ...fading out to the wall; when its fade began (None: still held)
        self.in_at = None           # when the picture appeared over the wall (fades in from then)
        self._outside = False       # the song is in a part the video lacks: late frames are not shown
        self.fx_start = None        # when the cut's effect began rising (None: no effect)
        self.fx_switch = None       # when the picture changed under it (it falls from there)
        self.effect = "flash"       # how a cut looks (CUT_EFFECTS)
        self._cut_b = None          # the song's second a known cut is at, once it is coming up
        self._cut_sent = False      # ...and whether the picture has been sent to its far side yet
        self.gen = 0                # bumped with every frame, for the wall's key
        self.key = None
        self.runs: list | None = None
        self.length = 0.0
        self._next = None           # (planes, n): the newest frame for the worker; older ones are dropped
        self._slow_at = 0.0         # the last frame converted on the GUI thread (no numpy)
        self._cv = threading.Condition()
        self._sought = None         # (when, where) a seek went, until the picture moves on from it
        self.leads = {False: LEAD, True: 0.3, "song": SONG_LEAD}   # learnt per kind: YouTube takes seconds, a file ~0.1s
        self._disk = False
        self._rolling = False       # a frame has come since show(): only then does a seek land
        self._steady = False        # the picture is where the audio is: its frames are shown
        self._holding = False       # paused here to let the audio catch up
        self.song = None            # a song-clock file playing: {"covered": [(a, b)], "cuts": [t]}
        self.now_fn = None          # () -> (song position, playing): set by the window
        self.frame_dt = 1 / 30      # seconds between the video's frames, from their own times
        self._last_ts = -1.0
        self._cut_at = None         # song-clock file: the cut a frame at or past switches the picture
        self._n = 0
        self._rest = None           # resting (hidden in the tray): the show() to make again on wake()
        self._done.connect(self._took)
        threading.Thread(target=self._convert, daemon=True, name="music-video").start()

    def _make(self) -> bool:
        if self.player is not None:
            return True
        try:
            from PyQt6.QtMultimedia import QMediaPlayer, QVideoSink
        except Exception:                                # noqa: BLE001
            return False
        self.player, self.sink = QMediaPlayer(self), QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.player.errorOccurred.connect(lambda *_a: self.stop())
        return True

    def show(self, key, url: str, length: float, runs: list, song: dict | None = None) -> None:
        """`song`: the file is a song-clock one (Store.build), on the song's own seconds."""
        if self._rest is not None:               # resting: opened on wake()
            self._rest = (key, url, length, runs, song)
            return
        if not self._make():
            return
        self.key, self.runs, self.length = key, runs, length
        self._set_song(song)
        self._disk = isinstance(url, QUrl) and url.isLocalFile()
        self._n += 1
        self._rolling = self._steady = self._holding = False
        self._sought = None
        self.player.setSource(url if isinstance(url, QUrl) else QUrl(url))

    def swap(self, url: QUrl, song: dict | None = None) -> None:
        """The same video from somewhere else (its file, once built): the picture up now stays
        until the new source's frames are at the song's moment."""
        if self._rest is not None:
            self._rest = self._rest[:1] + (url,) + self._rest[2:4] + (song,)
            return
        if self.player is None or self.key is None:
            return
        self._set_song(song)
        self._n += 1
        self._rolling = self._steady = self._holding = False
        self._sought = None
        self._disk = url.isLocalFile()
        self.player.setSource(url)

    def _set_song(self, song: dict | None) -> None:
        self.song, self._cut_at, self._cut_b, self._cut_sent = song, None, None, False
        if song is not None:
            self.runs, self.length = [(0.0, float("inf"), 0.0)], float(song.get("length") or 0.0)
            self.frame_dt = 1.0 / max(1.0, float(song.get("fps") or 30.0))

    def stop(self) -> None:
        if self._rest is not None:
            self._rest = ()                      # still resting, with nothing to open
        self.key = self.runs = self.song = None
        self._n += 1
        if self.player is not None:
            self.player.stop()
            self.player.setSource(QUrl())
        self.prev = None
        if self.image is not None:
            self.image = None
            self.gen += 1
            self.changed.emit()

    def rest(self) -> None:
        """Let go of the decoder while nothing is drawn (the tray); the last picture stays."""
        if self._rest is not None:
            return
        self._rest = ((self.key, self.player.source(), self.length, self.runs, self.song)
                      if self.player is not None and self.key is not None else ())
        self._n += 1
        if self.player is not None:
            p, s = self.player, self.sink
            self.player = self.sink = None
            p.stop()
            p.setSource(QUrl())
            p.deleteLater()
            s.deleteLater()
        self.prev = None

    def hold(self) -> None:
        """Paused where it is, not kept at the song: a paused sync() seeks after the clock."""
        if self.player is not None:
            from PyQt6.QtMultimedia import QMediaPlayer
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()

    def wake(self) -> None:
        """Out of rest: the same source opened again; sync() seeks it to the song."""
        got, self._rest = self._rest, None
        if got:
            self.show(*got)

    def _switched(self, now: float) -> None:
        """The picture changed (a cut landed, or it came or went): the effect peaks here."""
        if self.effect in FX:
            rise = FX[self.effect][0]                    # (at its height by the switch, even if it began late)
            self.fx_start = min(self.fx_start, now - rise) if self.fx_start is not None else now - rise
            self.fx_switch = now

    def _fade_out(self) -> None:
        """No picture for this part of the song: the last one goes, under the cut's effect."""
        if self.image is not None:
            now = time.monotonic()
            self.prev, self.prev_at, self.image = self.image, now, None
            self._switched(now)
            self.gen += 1
            self.changed.emit()

    def layers(self, now: float) -> list:
        """What the wall shows, bottom first, as [(image, opacity)]. Across a cut the picture
        before it is held until the new one has landed. Then, by `effect`: flash, dip, zoom or glitch (fx()) cover
        the change; fade cross-fades it, and fades the picture in and out; cut just changes."""
        fade = self.effect == "fade"
        if self.prev is not None:
            if self.prev_at is None:
                return [(self.prev, 1.0)]                 # held until the cut has landed
            k = (now - self.prev_at) / FADE if fade else 1.0
            if k < 1.0:
                return [(self.prev, 1.0), (self.image, k)] if self.image is not None else [(self.prev, 1.0 - k)]
            self.prev = None
        if self.image is None:
            return []
        a = min(1.0, (now - self.in_at) / FADE) if fade and self.in_at is not None else 1.0
        return [(self.image, a)]

    def fx(self, now: float) -> float:
        """How strong the cut's effect is, 0-1: rising to the switch, falling after it."""
        if self.fx_start is None or self.effect not in FX:
            return 0.0
        rise, fall = FX[self.effect]
        if self.fx_switch is None:                        # held at its height until the switch
            if now - self.fx_start > 3.0:                 # a cut that never landed
                self.fx_start = None
                return 0.0
            return min(1.0, (now - self.fx_start) / rise)
        k = (now - self.fx_switch) / fall
        if k >= 1.0:
            self.fx_start = self.fx_switch = None
            return 0.0
        return min(1.0, (self.fx_switch - self.fx_start) / rise) * (1.0 - max(0.0, k))

    def fading(self, now: float) -> bool:
        return (self.fx(now) > 0.0 or (self.prev is not None and self.prev_at is not None)
                or (self.effect == "fade" and self.in_at is not None and now - self.in_at < FADE))

    def _frame(self, frame) -> None:
        """Copy the frame's planes out here, convert them on the worker.

        toImage() off this thread read a buffer the decoder had moved on from (a crash, 2026-10-22);
        on it, 2.6ms a frame at 720p. Copying the planes costs ~0.3ms. Without numpy, or for an
        odd pixel format, it is toImage() here after all, at most 15 times a second."""
        if self.key is None:
            return
        from PyQt6.QtMultimedia import QVideoFrame, QVideoFrameFormat
        F = QVideoFrameFormat.PixelFormat
        fmt = frame.pixelFormat()
        ts = frame.startTime() / 1e6 if frame.startTime() >= 0 else -1.0    # the frame's own second
        if _np() is not None and fmt in (F.Format_NV12, F.Format_YUV420P) \
                and frame.map(QVideoFrame.MapMode.ReadOnly):
            try:
                planes = []
                for i in range(frame.planeCount()):
                    ptr = frame.bits(i)
                    ptr.setsize(frame.mappedBytes(i))
                    planes.append((bytes(ptr), frame.bytesPerLine(i)))
                job = ("nv12" if fmt == F.Format_NV12 else "i420", frame.width(), frame.height(), planes)
            finally:
                frame.unmap()
            with self._cv:
                self._next = (job, self._n, ts)
                self._cv.notify()
            return
        now = time.monotonic()
        if now - self._slow_at < 1 / 15:
            return
        self._slow_at = now
        img = frame.toImage()
        if not img.isNull():
            self._took(img.scaledToWidth(WIDE, Qt.TransformationMode.SmoothTransformation)
                       if img.width() > WIDE else img, self._n, ts)

    def _convert(self) -> None:
        """YUV planes to a half-size RGB image, off the GUI thread, one worker for good."""
        while True:
            with self._cv:
                while self._next is None:
                    self._cv.wait()
                job, n, ts = self._next
                self._next = None
            try:
                img = _rgb(*job)
                if img is not None and img.width() > WIDE:
                    img = img.scaledToWidth(WIDE, Qt.TransformationMode.SmoothTransformation)
            except Exception:                            # noqa: BLE001
                img = None
            self._done.emit(img, n, ts)

    def _took(self, img, n: int, ts: float = -1.0) -> None:
        if n != self._n:
            return
        if not self._rolling:
            self._rolling = True
            if self.song is not None and self.now_fn is not None:
                QTimer.singleShot(0, lambda: self._resync(n))     # to the song's moment now, not a poll on
        if ts >= 0.0:
            if self._last_ts >= 0.0 and 0.005 < ts - self._last_ts < 0.2:
                self.frame_dt += 0.2 * (ts - self._last_ts - self.frame_dt)
            self._last_ts = ts
        if self.song is not None and not self._song_frame(ts):
            return
        if img is not None and self.key is not None and self._steady and not self._outside:
            now = time.monotonic()
            if self.image is None and self.prev is None:
                self.in_at = now                          # out of the wall: its effect, or a fade in
                self._switched(now)
            if self.prev is not None and self.prev_at is None:
                self.prev_at = now                        # the cut has landed: the new picture shows
                self._switched(now)
            self.image = img
            self.gen += 1
            self.changed.emit()

    def _song_frame(self, ts: float) -> bool:
        """Song-clock file: whether a frame is at the song's moment (shown, else dropped); it also
        tells a seek's landing and a cut's switch, by the frame's own time."""
        if ts < 0.0 or self.now_fn is None:              # no frame times: by the seek alone
            self._steady = self._sought is None
            return True
        pos, _playing = self.now_fn()
        if self._sought is not None and abs(ts - self._sought[1]) < 0.25:
            took = time.monotonic() - self._sought[0]
            self.leads["song"] = max(0.03, min(1.0, 0.5 * self.leads["song"] + 0.5 * took))
            self._sought = None
            log("landed", took=round(took, 3), lead=round(self.leads["song"], 3))
        self._steady = abs(ts - pos) <= DRIFT
        if self._steady and self._cut_at is not None and ts >= self._cut_at - 0.01:
            self._cut_at = None
            if self.image is not None:                   # the picture before the cut, held under it
                self.prev, self.prev_at = self.image, None
        return self._steady

    def _resync(self, n: int) -> None:
        if n == self._n and self.now_fn is not None and self.key is not None:
            self.sync(*self.now_fn())

    def _cut_fx(self, n: int, c: float) -> None:
        """Song-clock file: a cut is coming up; its effect rises, and the frame at it switches."""
        if n != self._n or self._cut_b != c:
            return
        if self.effect in FX:
            self.fx_start, self.fx_switch = time.monotonic(), None
        self._cut_at = c

    def _sync_song(self, pos: float, playing: bool) -> None:
        """sync() on a song-clock file: its seconds are the song's, its cuts already in it. Seeks
        aim `lead` on and keep playing; frames show once at the song's moment (_song_frame)."""
        from PyQt6.QtMultimedia import QMediaPlayer
        P = QMediaPlayer.PlaybackState
        if not any(a - 0.01 <= pos < b for a, b in self.song.get("covered") or []):
            if self.player.playbackState() == P.PlayingState:
                self.player.pause()                      # a part of the song the video does not have
            self._outside = True
            self._fade_out()
            return
        self._outside = False
        now, have = time.monotonic(), self.player.position() / 1000.0
        if not playing:                                  # paused: the picture is where the audio is
            self._sought, self._cut_b, self._cut_at = None, None, None
            if self.player.playbackState() == P.PlayingState:
                self.player.pause()
            if abs(pos - have) > 0.05:
                self.player.setPosition(int(pos * 1000))
            return
        if self.player.playbackState() != P.PlayingState:
            self.player.play()
        if self._sought is not None and now - self._sought[0] < LAND:
            return                                       # landing is told by its frame (_song_frame)
        self._sought = None
        if self._cut_b is not None and not (self._cut_b - 2.0 < pos < self._cut_b + 1.0):
            self._cut_b = self._cut_at = None
        if self._cut_b is None and self.image is not None:
            c = next((c for c in self.song.get("cuts") or [] if pos < c <= pos + CUT_LEAD), None)
            if c is not None:
                self._cut_b, n = c, self._n
                rise = FX[self.effect][0] if self.effect in FX else 0.0
                QTimer.singleShot(int(max(0.0, c - pos - rise) * 1000), lambda: self._cut_fx(n, c))
        if abs(pos - have) > DRIFT:
            target = pos + self.leads["song"]
            self._sought, self._cut_b, self._cut_at = (now, target), None, None
            self.player.setPosition(int(target * 1000))
            log("seek", pos=round(pos, 2), was=round(have, 2), to=round(target, 2))

    @property
    def lead(self) -> float:
        return self.leads[self._disk]

    def _let_go(self, n: int) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer
        if n == self._n and self._holding and self.player is not None:
            self._holding, self._steady = False, True
            if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                self.player.play()

    def _cut_go(self, n: int, b: float) -> None:
        """A known cut, from a file: to its far side now, landing as the song gets to it."""
        if n != self._n or self._cut_b != b or self.player is None or self.key is None:
            return
        target = b + YC.shift_at(self.runs, b + 0.01) + DISK_LAND
        if self.image is not None:
            self.prev, self.prev_at = self.image, None
        if self.effect in FX and self.effect != "dip":
            self.fx_start, self.fx_switch = time.monotonic(), None   # up now, over the ~0.1s the seek
        self._steady = self._holding = False                         # takes: no still frame before it
        self._cut_sent = True
        self._sought = (time.monotonic(), target)
        self.player.setPosition(int(target * 1000))
        self.player.play()

    def _dip_go(self, n: int, b: float) -> None:
        if n == self._n and self._cut_b == b and self.effect == "dip":
            self.fx_start, self.fx_switch = time.monotonic(), None     # dark by the cut

    def sync(self, pos: float, playing: bool) -> None:
        """Keep the picture at the video's moment for the song's `pos`."""
        if self.key is None or not self.runs or self.player is None:
            return
        from PyQt6.QtMultimedia import QMediaPlayer
        P = QMediaPlayer.PlaybackState
        if not self._rolling:            # a seek before the first frame is dropped, or stalls it
            if self.player.playbackState() != P.PlayingState:
                self.player.play()
            return
        if self.song is not None:
            self._sync_song(pos, playing)
            return
        now = time.monotonic()
        if playing and self._cut_b is None and len(self.runs) > 1 and self.image is not None:
            soon = pos + CUT_LEAD        # a cut the map knows of, about to come
            if abs(YC.shift_at(self.runs, soon) - YC.shift_at(self.runs, pos)) > DRIFT:
                lo, hi = pos, soon       # the second it changes at
                for _ in range(12):
                    mid = (lo + hi) / 2
                    lo, hi = (lo, mid) if abs(YC.shift_at(self.runs, mid) - YC.shift_at(self.runs, pos)) > DRIFT else (mid, hi)
                b, n = hi, self._n
                self._cut_b, self._cut_sent = b, False
                if self._disk:           # a file: sought on time by a timer, so it lands at the cut itself
                    QTimer.singleShot(int(max(0.0, b - pos - DISK_LAND) * 1000), lambda: self._cut_go(n, b))
                    if self.effect == "dip":
                        rise = FX["dip"][0]
                        QTimer.singleShot(int(max(0.0, b - pos - rise) * 1000), lambda: self._dip_go(n, b))
                else:                    # YouTube: seeks take seconds; now, and held (see below)
                    self._cut_sent = True
                    if self.effect == "dip":
                        self.fx_start, self.fx_switch = now, None
        if self._cut_b is not None and not (self._cut_b - 2.0 < pos < self._cut_b + 1.0):
            self._cut_b, self._cut_sent = None, False
        if self._cut_b is not None and self._cut_sent:    # sent to the far side of the cut
            at = pos + YC.shift_at(self.runs, self._cut_b + 0.01)
        else:
            at = pos + YC.shift_at(self.runs, pos)
        if at < 0 or (self.length and at > self.length):
            if self.player.playbackState() == P.PlayingState:
                self.player.pause()      # a part of the song the video does not have: the wall shows
            self._outside = True
            self._fade_out()
            return
        self._outside = False
        now, have = time.monotonic(), self.player.position() / 1000.0
        if not playing:                  # paused: the picture stops where the audio is, and follows a scrub
            self._sought, self._holding = None, False   # (nothing moves while paused: nothing to wait for)
            if self.player.playbackState() == P.PlayingState:
                self.player.pause()
            if abs(at - have) > DRIFT:
                self.player.setPosition(int(at * 1000))
            self._steady = True
            return
        if self._sought is not None:     # a seek re-sent before it lands stalls it again, for good
            when, where = self._sought
            if self.player.playbackState() != P.PlayingState:
                self.player.play()       # landing is told by moving; a paused picture never would
            if abs(have - where) < 0.05 and now - when < LAND:
                return
            self._sought = None
            lo = 0.3 if self._disk else 1.0
            self.leads[self._disk] = max(lo, min(6.0, 0.5 * self.lead + 0.5 * (now - when + 0.5)))
        off = at - have                  # > 0: the picture is behind
        if off > DRIFT or -off > self.lead + 1.0:     # behind, or a seek back: aim past the audio by
                                                      # how long a seek takes to land, then hold
            self._steady = self._holding = False
            if self.image is not None:   # a cut (the video's extra part, a seek): hold the last
                self.prev, self.prev_at = self.image, None     # picture, cross-fade once landed
            self._sought = (now, at + self.lead)
            self.player.setPosition(int((at + self.lead) * 1000))
            self.player.play()
            return
        if off < -DRIFT or (self._holding and off < -0.05):
            self._holding = True         # a little ahead (a seek's lead): held until the audio is there,
            if self.player.playbackState() == P.PlayingState:      # not merely within DRIFT of it
                self.player.pause()
            if -off < 0.3:               # nearer than the next poll: let go on time, not up to 250ms late
                n = self._n
                QTimer.singleShot(int(-off * 1000), lambda: self._let_go(n))
            return
        self._holding, self._steady = False, True
        if self.player.playbackState() != P.PlayingState:
            self.player.play()


# ------------------------------------------------------------ whole videos on disk
SPEED = 2.0                # MB/s a download may take (Settings ▸ Background ▸ Video download speed)
KEEP_BYTES = 600 * 2 ** 20 # the videos folder is kept under this, oldest first, never the wanted ones
CHUNK = 2 ** 20            # one ranged request; googlevideo cuts long unranged reads short


FEAT = re.compile(r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s[^\)\]]*[\)\]]|\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.I)


def song_key(title: str, artist: str) -> str:
    """What a song's pick is kept under: its name, since the next song has no track id yet. Not its
    credits: the queue says "Mansion", and once playing the catalogue's "Mansion (feat. Fleurie)"."""
    return f"{_squash(FEAT.sub('', title or '') or title)}|{_squash((artist or '').split(',')[0])}"


# ------------------------------------------------------------ the video on the song's clock
SONG_W = 640               # song-clock files are this wide at most (frames are kept WIDE anyway)
REFILL = 1.5               # a hole between stretches this short is filled with footage shown twice, not faded
HEAD = 64 * 1024           # first ask for a video's head: its moov and segment index (sidx)
GROUP = 8 * 2 ** 20        # needed segments next to each other are asked for together, up to this


def index_of(head: bytes):
    """A fragmented MP4's segments, read off its head's sidx: [(t0, t1, byte0, byte1)]. An int
    when the head must be that long to hold it; None when there is no index to read."""
    off = 0
    while off + 8 <= len(head):
        size, typ = struct.unpack(">I4s", head[off:off + 8])
        hdr = 8
        if size == 1:
            if off + 16 > len(head):
                return off + 16
            size, hdr = struct.unpack(">Q", head[off + 8:off + 16])[0], 16
        if size < hdr or typ in (b"moof", b"mdat"):
            return None
        if typ == b"sidx":
            if off + size > len(head):
                return off + size
            b = head[off + hdr:off + size]
            scale = struct.unpack(">I", b[8:12])[0]
            if b[0] == 0:
                early, first = struct.unpack(">II", b[12:20])
                p = 20
            else:
                early, first = struct.unpack(">QQ", b[12:28])
                p = 28
            count = struct.unpack(">H", b[p + 2:p + 4])[0]
            p += 4
            if not scale or len(b) < p + 12 * count:
                return None
            at, t, segs = off + size + first, early / scale, []
            for _ in range(count):
                ref, dur, _sap = struct.unpack(">III", b[p:p + 12])
                p += 12
                if ref >> 31:                            # an index of indexes: not read
                    return None
                n = ref & 0x7FFFFFFF
                segs.append((t, t + dur / scale, at, at + n))
                t, at = t + dur / scale, at + n
            return segs or None
        off += size
    return off + 8 + 4096


def pieces(runs: list, song_len: float, video_len: float) -> list:
    """The song's seconds in order as [(a, b, shift)], shift None where the video has nothing.
    Between two stretches it switches half way, as shift_at() does, but fills only with footage
    no stretch shows itself (a short film's re-edit), unless that leaves a hole under REFILL."""
    rs = sorted(runs, key=lambda r: r[0])
    spans, a = [], 0.0                                   # [a, b, shift, its own first, last]
    for r, b in zip(rs, [(r[1] + q[0]) / 2 for r, q in zip(rs, rs[1:])] + [song_len]):
        b = min(b, song_len)
        if b > a:
            if spans and abs(spans[-1][2] - r[2]) < 1e-3:
                spans[-1][1], spans[-1][4] = b, r[1]
            else:
                spans.append([a, b, r[2], r[0], r[1]])
            a = b
    own = [(f + d, l + d) for _a, _b, d, f, l in spans]
    shown, heads = [], []                                # fills given out so far: lead-ins first, in song order
    for i, s in enumerate(spans):                        # (a film's run into a verse is that verse's, not
        a, d, f = s[0], s[2], min(max(s[3], s[0]), s[1])  # the last one's tail: Thriller 2:26)
        for v0, v1 in [v for k, v in enumerate(own) if k != i] + shown:
            if v0 < f + d and v1 > a + d:
                a = max(a, min(f, v1 - d))
        heads.append(a)
        shown.append((a + d, f + d))
    for i, s in enumerate(spans):
        b, d, l = s[1], s[2], max(min(s[4], s[1]), s[0])
        for v0, v1 in [v for k, v in enumerate(own) if k != i] + shown[:i] + shown[i + 1:]:
            if v0 < b + d and v1 > l + d:
                b = min(b, max(l, v0 - d))
        s.append((heads[i], b))
        shown.append((l + d, b + d))
    for p, q in zip([None] + spans, spans + [None]):     # a short hole is filled after all
        lo, hi = (p[5][1] if p else 0.0), (q[5][0] if q else song_len)
        if 0.0 < hi - lo < REFILL:
            if p:
                p[5] = (p[5][0], p[1])
            if q:
                q[5] = (q[0], q[5][1])
    out: list = []

    def put(a, b, d):
        if b - a <= 1e-3:
            return
        if out and d is None and out[-1][2] is None:
            out[-1] = (out[-1][0], b, None)
        else:
            out.append((a, b, d))
    for a0, b0, d, _f, _l, (a, b) in spans:
        put(a0, a, None)
        lo, hi = max(a, -d), (min(b, video_len - d) if video_len else b)
        if hi - lo < 0.1:
            put(a, b, None)
        else:
            put(a, lo, None)
            put(lo, hi, d)
            put(hi, b, None)
        put(b, b0, None)
    return [(round(a, 3), round(b, 3), None if d is None else round(d, 3)) for a, b, d in out]


def covered(ps: list) -> list:
    return [(a, b) for a, b, d in ps if d is not None]


def cuts_of(ps: list) -> list:
    """Where the picture jumps (two stretches meet, more than DRIFT apart): an effect goes there."""
    return [p[1] for p, q in zip(ps, ps[1:]) if p[2] is not None and q[2] is not None and abs(p[2] - q[2]) > DRIFT]


def needed(segs: list, ps: list) -> list[int]:
    """Which segments hold the video the song uses."""
    spans = [(a + d - 0.05, b + d + 0.05) for a, b, d in ps if d is not None]
    return [i for i, (t0, t1, _b0, _b1) in enumerate(segs) if any(t0 < hi and t1 > lo for lo, hi in spans)]


def song_order(segs: list, ps: list, idx: list, start: float = 0.0) -> list[int]:
    """Segments `idx` in the order the song reaches them from `start` on; those it has passed last."""
    end = ps[-1][1] if ps else 0.0

    def when(i):
        t0, t1 = segs[i][0], segs[i][1]
        spans = [(max(a, t0 - d - 0.05), min(b, t1 - d + 0.05)) for a, b, d in ps if d is not None]
        spans = [(lo, hi) for lo, hi in spans if hi > lo]                  # (as needed() reaches)
        later = [max(lo, start) for lo, hi in spans if hi > start]
        return min(later) if later else end + min((lo for lo, _hi in spans), default=0.0)
    return sorted(idx, key=when)


HEAD_GAIN = 12.0           # a head file only when the whole one is further off than this (seconds)
HEAD_PAST = 10.0           # ...and it runs this far past where the song should be once the whole one is up


def head_plan(segs: list, ps: list, want: list, start: float, rate: float, build_rate: float) -> float | None:
    """The song's second a head file should end at, so the whole file is built before the song gets
    there, at `rate` bytes/s and `build_rate` build seconds per song second; None: not worth one."""
    end = ps[-1][1] if ps else 0.0
    whole = sum(segs[i][3] - segs[i][2] for i in want) / max(1.0, rate) + build_rate * end
    stop = start + 1.25 * whole + HEAD_PAST
    return round(stop, 3) if whole >= HEAD_GAIN and stop < end - HEAD_PAST else None


def clip(ps: list, a: float, b: float) -> list:
    """`ps` cut to the song's [a, b], black before `a` (a song-clock file starts at the song's 0)."""
    out = [(0.0, round(a, 3), None)] if a > 1e-3 else []
    for p, q, d in ps:
        lo, hi = max(p, a), min(q, b)
        if hi - lo > 1e-3:
            out.append((round(lo, 3), round(hi, 3), d))
    return out


def plan_key(vid: str, ps: list) -> str:
    return f"{vid}-" + hashlib.sha1(json.dumps(ps).encode()).hexdigest()[:8]


_TOOLS: dict = {}


def _tool(name: str) -> str | None:
    if name not in _TOOLS:
        _TOOLS[name] = shutil.which(name)
    return _TOOLS[name]


def can_build() -> bool:
    """ffmpeg and ffprobe at hand (Windows may have neither): else whole videos, sought at cuts."""
    return bool(_tool("ffmpeg") and _tool("ffprobe"))


def _quiet() -> dict:
    """Low priority and no console window, for ffmpeg."""
    if sys.platform == "win32":
        return {"creationflags": 0x00004000 | 0x08000000}     # BELOW_NORMAL, NO_WINDOW
    import os
    return {"preexec_fn": lambda: os.nice(19)}


RATES = ["24000/1001", "24/1", "25/1", "30000/1001", "30/1", "48/1", "50/1", "60000/1001", "60/1"]


def probe(path, at: float = 0.0) -> tuple[int, int, str] | None:
    """(width, height, frame rate as ffmpeg writes it) of a video file. A parts file has no rate
    to read up front, so it is told from frame times one second at `at` (a part it has)."""
    def ask(*args) -> list[str]:
        return subprocess.run([_tool("ffprobe"), "-v", "error", "-select_streams", "v:0", *args, "-of", "csv=p=0",
                               noconsole.real_path(path)], capture_output=True, text=True, timeout=30, **_quiet()).stdout.split()
    try:
        w, h, fps = ask("-show_entries", "stream=width,height,avg_frame_rate")[0].split(",")[:3]
        w, h = int(w), int(h)
        if fps.startswith("0/") or not 1.0 <= _rate(fps) <= 121.0:
            ts = sorted(float(t.strip(",")) for t in ask("-read_intervals", f"{at:.3f}%+1", "-show_entries", "frame=pts_time")
                        if t.strip(","))
            gaps = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
            if not gaps:
                return None
            fps = min(RATES, key=lambda r: abs(_rate(r) - 1.0 / gaps[len(gaps) // 2]))
        return (w, h, fps) if w > 0 and h > 0 else None
    except Exception:                                    # noqa: BLE001
        return None


def _rate(fps: str) -> float:
    n, _s, d = fps.partition("/")
    return float(n) / float(d or 1)


def build_args(src, ps: list, out, w: int, h: int, fps: str, codec: str = "libx264") -> list[str]:
    """ffmpeg's arguments for a song-clock file: each stretch cut exactly out of `src`, black
    where the video has nothing, one after the other for the song's whole length."""
    ow = max(2, min(SONG_W, w) // 2 * 2)
    oh = max(2, round(h * ow / w / 2) * 2)
    args, graph, labels, k = [_tool("ffmpeg") or "ffmpeg", "-v", "error", "-y"], [], [], 0
    for i, (a, b, d) in enumerate(ps):
        if d is None:
            graph.append(f"color=c=black:s={ow}x{oh}:r={fps}:d={b - a:.3f}[p{i}]")
        else:
            args += ["-ss", f"{a + d:.3f}", "-t", f"{b - a:.3f}", "-i", noconsole.real_path(src)]
            graph.append(f"[{k}:v]scale={ow}:{oh},fps={fps},setsar=1,format=yuv420p,setpts=PTS-STARTPTS[p{i}]")
            k += 1
        labels.append(f"[p{i}]")
    graph.append("".join(labels) + f"concat=n={len(ps)}:v=1:a=0[o]")
    enc = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"] if codec == "libx264"
           else ["-c:v", "mpeg4", "-q:v", "5"])
    return args + ["-filter_complex", ";".join(graph), "-map", "[o]", *enc,
                   "-g", str(max(1, round(_rate(fps)))), "-an", "-threads", "2",
                   "-movflags", "+faststart", "-f", "mp4", noconsole.real_path(out)]


def build(src, ps: list, out) -> bool:
    """Write the song-clock file (a keyframe a second, so a seek lands at once)."""
    got = probe(src, next((a + d for a, b, d in ps if d is not None), 0.0))
    if got is None or not covered(ps):
        log("build-error", why="probe" if got is None else "not covered")
        return False
    for codec in ("libx264", "mpeg4"):                   # (an ffmpeg built without x264)
        try:
            r = subprocess.run(build_args(src, ps, out, *got, codec=codec), capture_output=True,
                               timeout=600, **_quiet())
        except Exception:                                # noqa: BLE001
            continue
        if r.returncode == 0 and pathlib.Path(out).exists() and pathlib.Path(out).stat().st_size > 0:
            return True
        log("build-error", codec=codec, code=r.returncode,
            err=(r.stderr or b"").decode("utf-8", "replace").strip()[-300:])
    return False


TRIES = 3                  # a fetch or build that failed this often is not tried again this run


class Store(QObject):
    """The current song's video and the next one's on disk, fetched at a capped speed. A job
    (vid, pieces) fetches only the segments the song uses and builds a song-clock file; a bare vid
    (no ffmpeg) downloads the whole video. `ready(key)` once one is done: plan_key(), or the vid.
    The current song's parts come in the song's order from where it is, and `head(key)` says a
    file of its next stretch is up while the rest is fetched (notes 2026-10-28)."""

    ready = pyqtSignal(str)
    head = pyqtSignal(str)

    def __init__(self, folder: pathlib.Path) -> None:
        super().__init__()
        self.folder = folder
        self.speed = SPEED
        self.want: list = []
        self.tries: dict = {}            # key -> failed attempts; given up on at TRIES
        self.at = None                   # (song position, monotonic, playing) of the current song: set by the window
        self.seen = None                 # bytes/s fetches have been getting
        self.build_rate = 0.06           # build seconds per song second (measured 0.03-0.05 here, 10-28)
        self._heads: dict = {}           # key -> the thread building its head file
        self._cv = threading.Condition()
        try:
            self.lengths = json.loads((folder / "index.json").read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            self.lengths = {}
        threading.Thread(target=self._run, daemon=True, name="video-store").start()

    def path(self, vid: str) -> pathlib.Path | None:
        p = self.folder / f"{vid}.mp4"
        return p if vid and p.exists() else None

    def length(self, vid: str) -> float:
        return float(self.lengths.get(vid) or 0.0)

    def song_path(self, key: str, kind: str = "song") -> pathlib.Path | None:
        """`kind` "head": the file of the stretch played while the whole one is fetched."""
        p = self.folder / f"{key}.{kind}.mp4"
        return p if key and p.exists() and (self.folder / f"{key}.{kind}.json").exists() else None

    def song_info(self, key: str, kind: str = "song") -> dict | None:
        """A built song-clock file's {"covered", "cuts", "fps", "length"}, or None."""
        if self.song_path(key, kind) is None:
            return None
        try:
            return json.loads((self.folder / f"{key}.{kind}.json").read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            return None

    def _pos(self) -> float:
        at = self.at
        if not at:
            return 0.0
        return max(0.0, at[0] + (time.monotonic() - at[1] if at[2] else 0.0))

    def _current(self, key: str) -> bool:
        with self._cv:
            return bool(self.want) and self._key(self.want[0]) == key

    @staticmethod
    def _key(item) -> str:
        return item if isinstance(item, str) else plan_key(*item)

    def wish(self, items: list) -> None:
        """These, in this order (current first): a vid, or a job (vid, pieces). Anything else being
        fetched stops (what it has is kept)."""
        keys = [self._key(i) if i else "" for i in items]
        items = [i for k, i in enumerate(items) if i and keys[k] not in keys[:k]]
        with self._cv:
            if [self._key(i) for i in items] != [self._key(i) for i in self.want]:
                self.want = items
                self._cv.notify_all()

    def _wanted(self, key: str) -> bool:
        with self._cv:
            return key in [self._key(i) for i in self.want]

    def _done(self, item) -> bool:
        return bool(self.path(item) if isinstance(item, str) else self.song_path(plan_key(*item)))

    def _run(self) -> None:
        while True:
            with self._cv:
                todo = next((i for i in self.want if not self._done(i)
                             and self.tries.get(self._key(i), 0) < TRIES), None)
                if todo is None:
                    self._cv.wait(5.0)
                    continue
            try:
                ok = self._fetch(todo) if isinstance(todo, str) else self._job(*todo)
            except Exception as e:                       # noqa: BLE001
                log("store-error", item=self._key(todo), err=repr(e)[:200])
                ok = False
            if ok:
                self._tidy()
                self.ready.emit(self._key(todo))
                continue
            if self._wanted(self._key(todo)):      # (stopped because no longer wanted: not a failure)
                self.tries[self._key(todo)] = self.tries.get(self._key(todo), 0) + 1
                time.sleep(10.0)         # failed: not straight back at it (stopped: on to what is wanted)

    def _job(self, vid: str, ps: list) -> bool:
        """The segments the song uses (or a whole file already here), then the song-clock file."""
        key = plan_key(vid, ps)
        src = self.path(vid) or self._fetch_parts(vid, ps, key)
        if src is None or not self._wanted(key):
            return False
        th = self._heads.pop(key, None)
        if th is not None:
            th.join()                    # (it reads the parts file, which goes once this is built)
        t0 = time.monotonic()
        tmp = self.folder / f"{key}.tmp.mp4"
        if not self._build(src, ps, tmp, key, "song"):
            log("build-failed", key=key)
            return False
        secs = time.monotonic() - t0
        self.build_rate = 0.5 * self.build_rate + 0.5 * secs / max(1.0, ps[-1][1])
        if src.name.endswith(".frags"):                  # its parts are in the song file now
            src.unlink(missing_ok=True)
            src.with_name(src.name + ".json").unlink(missing_ok=True)
        log("built", key=key, secs=round(secs, 2), size=(self.folder / f"{key}.song.mp4").stat().st_size)
        return True

    def _build(self, src, ps: list, tmp: pathlib.Path, key: str, kind: str) -> bool:
        """build() into `tmp`, then kept as `<key>.<kind>.mp4` with its info beside it."""
        if not build(src, ps, tmp):
            tmp.unlink(missing_ok=True)
            return False
        info = {"covered": covered(ps), "cuts": cuts_of(ps), "length": ps[-1][1],
                "fps": round(_rate((probe(tmp) or (0, 0, "30/1"))[2]), 3)}
        (self.folder / f"{key}.{kind}.json").write_text(json.dumps(info), encoding="utf-8")
        tmp.replace(self.folder / f"{key}.{kind}.mp4")
        return True

    def _head(self, src: pathlib.Path, ps: list, key: str) -> None:
        """The head file built beside the fetch (its parts are all in), then head(key)."""
        def run():
            t0 = time.monotonic()
            if self._build(src, ps, self.folder / f"{key}.head.tmp.mp4", key, "head"):
                log("head-built", key=key, start=covered(ps)[0][0], end=ps[-1][1], secs=round(time.monotonic() - t0, 2))
                if self.song_path(key) is None:
                    self.head.emit(key)
            else:
                log("build-failed", key=key, kind="head")
        th = threading.Thread(target=run, daemon=True, name="video-head")
        self._heads[key] = th
        th.start()

    def _get(self, url: str, a: int, b: int):
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": f"bytes={a}-{b}"})
        return urllib.request.urlopen(req, timeout=20)

    def _fetch_parts(self, vid: str, ps: list, key: str) -> pathlib.Path | None:
        """The needed segments, written where they sit in the video (`<vid>.frags`, the rest left
        empty): ffmpeg reads it as the video, by its own index. Resumed from `.frags.json`."""
        url, length = stream(vid)
        if not url:
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        frags, meta_p = self.folder / f"{vid}.frags", self.folder / f"{vid}.frags.json"
        itag = (re.search(r"[?&]itag=(\d+)", url) or [None, ""])[1]
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            meta = {}
        if meta.get("itag") != itag or not frags.exists():
            meta = {}
        if not meta.get("segs"):
            head, size = b"", HEAD
            for _ in range(4):
                with self._get(url, 0, size - 1) as r:
                    head = r.read()
                got = index_of(head)
                if not isinstance(got, int) or got <= size:
                    break
                size = got
            if not isinstance(got, list):                # not an indexed file: the whole video
                log("fetch-whole", vid=vid)
                return self.path(vid) if self._fetch(vid, key) else None
            with open(frags, "wb") as out:
                out.write(head[:got[0][2]])
                out.truncate(got[-1][3])                 # its whole length (left sparse): else ffmpeg will not seek it
            meta = {"itag": itag, "segs": got, "held": []}
            meta_p.write_text(json.dumps(meta), encoding="utf-8")
        segs, held = meta["segs"], set(meta["held"])
        current = self._current(key)
        start = max(0.0, self._pos() - 1.0) if current else 0.0          # (where a head file would start)
        want = song_order(segs, ps, [i for i in needed(segs, ps) if i not in held], start)
        rate = min(self.seen or float("inf"), self.speed * 2 ** 20)
        end = (head_plan(segs, ps, want, start, rate, self.build_rate)
               if current and self.song_path(key, "head") is None and key not in self._heads else None)
        hps = clip(ps, start, end) if end else None
        hneed = set(needed(segs, hps)) if hps and covered(hps) else None
        log("fetch", vid=vid, segs=len(want), bytes=sum(segs[i][3] - segs[i][2] for i in want),
            whole=segs[-1][3], held=len(held), start=round(start, 1), head=end)
        groups: list[list[int]] = []
        for i in want:
            if groups and groups[-1][-1] == i - 1 and segs[i][3] - segs[groups[-1][0]][2] <= GROUP:
                groups[-1].append(i)
            else:
                groups.append([i])
        if hneed is not None and hneed <= held:          # (its parts in from before)
            self._head(frags, hps, key)
            hneed = None
        retried = False
        with open(frags, "r+b") as out:
            for g in groups:
                a, b = segs[g[0]][2], segs[g[-1]][3]
                while a < b:
                    if not self._wanted(key):
                        return None
                    try:
                        r = self._get(url, a, b - 1)
                    except Exception:                    # noqa: BLE001
                        if retried:
                            return None
                        retried = True                   # a link gone stale on a slow fetch: one fresh one
                        url, length = stream(vid, fresh=True)
                        continue
                    with r:
                        if getattr(r, "status", 206) != 206:
                            return None                  # not the range asked for: never written in place
                        out.seek(a)
                        t0, got = time.monotonic(), 0
                        while a < b:
                            if not self._wanted(key):
                                meta_p.write_text(json.dumps({**meta, "held": sorted(held)}), encoding="utf-8")
                                return None
                            block = r.read(min(64 * 1024, b - a))
                            if not block:
                                break
                            out.write(block)
                            a += len(block)
                            got += len(block)
                            held.update(i for i in g if segs[i][3] <= a)
                            if hneed is not None and hneed <= held:
                                out.flush()              # (ffmpeg reads the file as it is on disk)
                                self._head(frags, hps, key)
                                hneed = None
                            ahead = got / (self.speed * 2 ** 20) - (time.monotonic() - t0)
                            if ahead > 0:
                                time.sleep(ahead)        # the cap: never faster than speed MB/s
                    if got > 2 ** 18:
                        r_now = got / max(1e-3, time.monotonic() - t0)
                        self.seen = r_now if self.seen is None else 0.5 * self.seen + 0.5 * r_now
                    if not got:                          # an empty answer: once more, then given up
                        if retried:
                            return None
                        retried = True
                meta_p.write_text(json.dumps({**meta, "held": sorted(held)}), encoding="utf-8")
        self.lengths[vid] = length
        try:
            (self.folder / "index.json").write_text(json.dumps(self.lengths), encoding="utf-8")
        except OSError:
            pass
        return frags

    def _fetch(self, vid: str, key: str = "") -> bool:
        import urllib.request
        key = key or vid
        url, length = stream(vid)
        if not url:
            return False
        self.folder.mkdir(parents=True, exist_ok=True)
        part = self.folder / f"{vid}.part"
        have = part.stat().st_size if part.exists() else 0
        total, retried = None, False
        with open(part, "ab") as out:
            while total is None or have < total:
                if not self._wanted(key):
                    return False         # no longer current or next: kept for later, not finished
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                           "Range": f"bytes={have}-{have + CHUNK - 1}"})
                try:
                    r = urllib.request.urlopen(req, timeout=20)
                except Exception:                        # noqa: BLE001
                    if retried:
                        return False
                    retried = True       # a link gone stale on a slow fetch: one fresh one
                    url, length = stream(vid, fresh=True)
                    continue
                with r:
                    span = r.headers.get("Content-Range") or ""
                    if "/" in span and span.rsplit("/", 1)[1].isdigit():
                        total = int(span.rsplit("/", 1)[1])
                    elif total is None:
                        total = have + int(r.headers.get("Content-Length") or 0)
                    t0, got = time.monotonic(), 0
                    while True:
                        if not self._wanted(key):
                            return False
                        block = r.read(64 * 1024)
                        if not block:
                            break
                        out.write(block)
                        have += len(block)
                        got += len(block)
                        ahead = got / (self.speed * 2 ** 20) - (time.monotonic() - t0)
                        if ahead > 0:
                            time.sleep(ahead)    # the cap: never faster than speed MB/s
                if have >= (total or 0) and total:
                    break
        part.rename(self.folder / f"{vid}.mp4")
        self.lengths[vid] = length
        try:
            (self.folder / "index.json").write_text(json.dumps(self.lengths), encoding="utf-8")
        except OSError:
            pass
        return True

    def _tidy(self) -> None:
        """The folder kept under KEEP_BYTES, oldest first, never what is wanted (its parts neither)."""
        def used(p):                                     # a .frags file is sparse: its blocks, not its length
            st = p.stat()
            return st.st_blocks * 512 if getattr(st, "st_blocks", None) is not None else st.st_size
        for p in self.folder.glob("*.head.mp4"):         # a head is spent once its whole file is built
            key = p.name[:-len(".head.mp4")]
            if self.song_path(key) is not None:
                try:
                    p.unlink()
                    p.with_name(key + ".head.json").unlink(missing_ok=True)
                except OSError:                          # (Windows: still open in the player; next time)
                    pass
        files = sorted((p for p in self.folder.iterdir() if p.name.endswith((".mp4", ".frags", ".part"))
                        and not p.name.endswith(".tmp.mp4")), key=lambda p: p.stat().st_mtime)
        size = sum(used(p) for p in files)
        with self._cv:
            keep = {self._key(i) for i in self.want} | {i if isinstance(i, str) else i[0] for i in self.want}
        for p in files:
            if size <= KEEP_BYTES:
                break
            stem = p.name.split(".")[0]
            if stem not in keep:
                size -= used(p)
                p.unlink(missing_ok=True)
                for side in (p.with_name(p.name + ".json"), p.with_name(stem + ".song.json"),
                             p.with_name(stem + ".head.json")):
                    if p.name.endswith((".frags", ".song.mp4", ".head.mp4")):
                        side.unlink(missing_ok=True)
