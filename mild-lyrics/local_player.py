"""Songs on this computer, played by Mild Lyrics itself: LocalLibrary scans,
LocalPlayer plays, LocalOverlay fronts the transport. Notes:
docs/notes/mild-lyrics/home_page.md."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import random
import re
import threading
import time

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal

import frame_clock as FCK
import mixer_volume as MV
import stream_relay as SR

# Qt's FFmpeg backend probes every hardware video decoder the first time any player is
# made: 0.7s on the GUI thread here (froze the lyrics), for audio that never uses one.
# Before any QMediaPlayer exists; a value set by hand still wins.
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", ",")
os.environ.setdefault("QT_FFMPEG_ENCODING_HW_DEVICE_TYPES", ",")

AUDIO = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".mp4", ".aac", ".wav", ".wma", ".aiff", ".aif"}
APP = "Mild Lyrics"


_mono = FCK.mono


def _key(title: str, artist: str) -> str:
    """The id a local song is known by: the same one other players' songs get."""
    return hashlib.sha1(f"{title} {artist}".encode("utf-8")).hexdigest()[:22]


def _from_name(path: pathlib.Path) -> tuple[str, str]:
    """(title, artist) out of "Artist - Title.ext", or the bare stem."""
    stem = re.sub(r"^\d{1,3}[\s.\-_]+", "", path.stem)
    if " - " in stem:
        a, t = stem.split(" - ", 1)
        return t.strip(), a.strip()
    return stem.strip(), ""


def read_tags(path: pathlib.Path, art_dir: pathlib.Path) -> dict:
    """One file's card. Never raises; a file mutagen cannot read keeps its name."""
    title, artist = _from_name(path)
    row = {"path": str(path), "title": title, "artist": artist, "album": "",
           "ms": 0, "fmt": path.suffix[1:].upper(), "art": "", "n": 0}
    try:
        import mutagen
    except ImportError:
        return row
    try:
        f = mutagen.File(str(path))
    except Exception:                                    # noqa: BLE001
        f = None
    if f is None:
        return row
    info = getattr(f, "info", None)
    if info is not None:
        row["ms"] = int(float(getattr(info, "length", 0) or 0) * 1000)
        br = int(getattr(info, "bitrate", 0) or 0) // 1000
        if br and row["fmt"] in ("MP3", "OGG", "OPUS", "M4A", "AAC"):
            row["fmt"] += f" {br}"
    tags = getattr(f, "tags", None) or {}

    def first(*keys):
        for k in keys:
            try:
                v = tags.get(k)
            except Exception:                            # noqa: BLE001
                v = None
            if v is None:
                continue
            v = getattr(v, "text", v)
            if isinstance(v, (list, tuple)):
                v = v[0] if v else ""
            v = str(v).strip()
            if v:
                return v
        return ""

    row["title"] = first("TIT2", "title", "TITLE", "\xa9nam") or row["title"]
    row["artist"] = first("TPE1", "artist", "ARTIST", "\xa9ART") or row["artist"]
    row["album"] = first("TALB", "album", "ALBUM", "\xa9alb")
    try:
        row["n"] = int(re.split(r"[/\s]", first("TRCK", "tracknumber", "TRACKNUMBER") or "0")[0] or 0)
    except ValueError:
        row["n"] = 0
    raw = None
    try:
        pics = getattr(f, "pictures", None)
        if pics:
            raw = pics[0].data
        elif hasattr(tags, "getall"):
            got = tags.getall("APIC")
            raw = got[0].data if got else None
        elif "covr" in tags:
            raw = bytes(tags["covr"][0])
        elif "metadata_block_picture" in tags:
            import base64
            from mutagen.flac import Picture
            raw = Picture(base64.b64decode(tags["metadata_block_picture"][0])).data
    except Exception:                                    # noqa: BLE001
        raw = None
    if raw:
        out = art_dir / (hashlib.sha1(str(path).encode()).hexdigest() + ".img")
        try:
            if not out.exists():
                art_dir.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)
            row["art"] = out.as_uri()
        except OSError:
            pass
    return row


def _norm(path) -> str:
    """One spelling per path: Windows' case and either slash."""
    return os.path.normcase(os.path.normpath(str(path)))


class LocalLibrary(QObject):
    """What is in the chosen folders. `changed` fires when a scan lands."""

    changed = pyqtSignal()

    def __init__(self, cache: pathlib.Path) -> None:
        super().__init__()
        self.cache = cache / "local.json"
        self.art_dir = cache / "local-art"
        self.dirs: list[str] = []
        self.tracks: list[dict] = []
        self.scanning = False
        self.scanned_at = 0.0
        self._known: dict[str, dict] = {}
        try:
            d = json.loads(self.cache.read_text(encoding="utf-8"))
            self._known = {r["path"]: r for r in d.get("rows", []) if isinstance(r, dict)}
        except Exception:                                # noqa: BLE001
            self._known = {}

    def set_dirs(self, dirs: list[str]) -> None:
        self.dirs = [d for d in dirs if d]
        rows = {}
        for p, r in self._known.items():           # the cache may hold one file under two spellings
            if self._inside(p):
                rows.setdefault(_norm(p), r)
        self.tracks = sorted(rows.values(), key=self._order)

    def _inside(self, path: str) -> bool:
        p = _norm(path)
        for d in self.dirs:
            d = _norm(pathlib.Path(d).expanduser())
            if p == d or p.startswith(d.rstrip(os.sep) + os.sep):
                return True
        return False

    @staticmethod
    def _order(r: dict):
        return (r.get("artist", "").lower(), r.get("album", "").lower(), r.get("n", 0),
                r.get("title", "").lower())

    def scan(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        threading.Thread(target=self._scan, args=(list(self.dirs),), daemon=True).start()

    def _scan(self, dirs: list[str]) -> None:
        rows, known, walked = [], dict(self._known), set()
        for d in dirs:
            root = pathlib.Path(d).expanduser()
            for base, subs, files in os.walk(root):
                real = _norm(os.path.realpath(base))
                if real in walked:                  # overlapping folders, other spellings, junctions
                    subs[:] = []
                    continue
                walked.add(real)
                for name in files:
                    p = pathlib.Path(base) / name
                    if p.suffix.lower() not in AUDIO:
                        continue
                    try:
                        mt = p.stat().st_mtime
                    except OSError:
                        continue
                    was = known.get(str(p))
                    if was is None or was.get("mt") != mt:
                        was = read_tags(p, self.art_dir)
                        was["mt"] = mt
                        was["tid"] = _key(was["title"], was["artist"])
                        known[str(p)] = was
                    rows.append(was)
        self._known = known
        self.tracks = sorted((r for r in rows if self._inside(r["path"])), key=self._order)  # minus folders removed meanwhile
        self.scanned_at = time.time()
        try:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_text(json.dumps({"rows": list(known.values())}), encoding="utf-8")
        except OSError:
            pass
        self.scanning = False
        self.changed.emit()


class LocalPlayer(QObject):
    """QtMultimedia underneath; made the first time something is played.

    A track is a file (`path`) or a stream (`stream`: title, artist, ms, maybe
    `spotify`), which `resolver` turns into a URL before it can start."""

    changed = pyqtSignal()
    failed = pyqtSignal(str)
    near_end = pyqtSignal()       # a song has started: autoplay checks how much is queued after it
    ran_out = pyqtSignal()        # it has ended and there is nothing after it
    _cmd = pyqtSignal(str, float)

    def __init__(self) -> None:
        super().__init__()
        self.player = None
        self.out = None
        self.queue: list[dict] = []
        self.idx = -1
        self.active = False
        self.shuffle = False
        self.repeat = "off"
        self.volume = 0.8           # the bar: mixer percent, cubic in amplitude (mixer_volume)
        self.mixer = MV.StreamVolume()
        self.mixer.heard.connect(self._mixer_moved)
        self.mixer.placed.connect(self._mixer_holds)
        self._gain_one = False      # the mixer holds our volume, so Qt's own gain stays at 1
        self.resolver = None
        self.ensure = None          # makes the resolver on demand (the home page holds it)
        self._cued = False          # restored after a restart: nothing loaded until play
        self.bursts: list[int] = []            # songs skipped in a row, quickly, run by run (kept across restarts)
        self._changed_at = _mono()             # when the song last changed
        self._last_t: dict | None = None
        self._by_skip = False                  # this song was reached by a skip
        self.loading: str | None = None
        self._resume_at: float | None = None   # a reload after a stream error goes back here
        self._resume_src = None                # ...once this source has loaded (not the old one stopping)
        self._refetch: str | None = None       # a fresh link being fetched while the buffered audio plays on
        self._heard = 0.0                      # where the audio last was while playing
        self._moved_at = _mono()               # when the position last changed (a stall, otherwise)
        self._paused_at: float | None = None
        self._seek: list | None = None         # [to, when, landed]: sought, not heard moving there yet
        self._stalled_at: float | None = None  # playing but not moving since then
        self.log = None                        # log(event, **fields): the window's follow.log
        self.ended = False
        self.can_grow = None                   # () -> bool: something (autoplay) will add songs after the last
        self.wants_next = False                # Next on the last song: play on, move on when songs land
        self._lock = threading.Lock()
        self._snap = (0.0, _mono(), False, 0.0)      # pos, at, playing, length
        self._cmd.connect(self._do)
        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._sample)

    # ------------------------------------------------------------ GUI side
    def _make(self) -> bool:
        if self.player is not None:
            return True
        try:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
        except Exception:                                # noqa: BLE001
            return False
        self.player = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self._apply_volume()
        self.mixer.start()
        self.player.setAudioOutput(self.out)
        self.player.mediaStatusChanged.connect(self._status)
        self.player.playbackStateChanged.connect(lambda _s: self._sample())
        self.player.positionChanged.connect(lambda _p: self._sample())
        self.player.errorOccurred.connect(self._error)
        SR.LOG[0] = self._note
        return True

    def _error(self, _err, why: str) -> None:
        """A stream that will not play: its URL has gone stale (or dropped). A fresh link is
        fetched while what Qt already buffered plays on; _switch moves onto it from there."""
        t = self.current
        if self._refetch is None:
            self._note("local-error", why=why, pos=round(self._heard, 3))
        if t is None or not t.get("stream") or self.resolver is None:
            self.failed.emit(why or "it would not play")
            return
        k = self.resolver.key(t)
        if self._refetch == k:
            return                              # already fetching (Qt says this every 100ms)
        if _mono() - t.get("_failed_at", 0.0) > 30.0:
            t["_retries"] = 0                   # it played on fine since the last one
        if t.get("_retries", 0) >= 3:
            self.failed.emit(why or "it would not play")
            return
        t["_retries"], t["_failed_at"] = t.get("_retries", 0) + 1, _mono()
        self._refetch = k
        self.resolver.live.pop(k, None)
        self.resolver.want(t, now=True)

    def _switch(self, got: dict) -> None:
        """Onto a fresh link, at the place the dropped one had played up to."""
        with self._lock:
            if self._resume_at is None:
                self._resume_at = self._heard
        self._resume_src = QUrl(SR.wrap(got["url"]))
        self.player.setSource(self._resume_src)
        self.player.play()
        self._tick.start()
        self._sample()

    @property
    def current(self) -> dict | None:
        return self.queue[self.idx] if 0 <= self.idx < len(self.queue) else None

    def loaded_url(self) -> str:
        """The http(s) link the current song is playing from (a stream), or ""."""
        try:
            u = self.player.source().toString() if self.player is not None else ""
        except Exception:                                   # noqa: BLE001
            return ""
        u = SR.unwrap(u)
        return u if u.startswith(("http://", "https://")) else ""

    def playing(self) -> bool:
        return self._snap[2]

    def paused_for(self) -> float:
        """How long it has sat paused after playing; 0 while loading or before it first plays."""
        if self.loading or self._paused_at is None:
            return 0.0
        return _mono() - self._paused_at

    def play(self, tracks: list[dict], i: int = 0) -> bool:
        if not tracks or not self._make():
            return False
        self.queue = list(tracks)
        self._paused_at = None
        self._resume_at = None
        self._by_skip = False
        self._cued = False
        self.ended = False
        self.idx = max(0, min(i, len(tracks) - 1))
        if self.shuffle:
            first = self.queue.pop(self.idx)
            random.shuffle(self.queue)
            self.queue.insert(0, first)
            self.idx = 0
        self.active = True
        self._load()
        return True

    # ------------------------------------------------------------ across a restart
    KEEP_OUT = ("_retries", "_retried", "_failed_at", "_ord")

    def state(self) -> dict:
        """What to come back to: the volume, how you skip, the queue, where in it, and where in the song."""
        kept = {"volume": round(self.volume, 3), "volume_scale": "cubic", "bursts": self.bursts[-self.BURSTS_KEPT:]}
        if not self.queue:
            return kept
        with self._lock:
            pos, at, on, length = self._snap
        if self._resume_at is not None:
            pos = self._resume_at           # still loading to there
        elif on:
            pos += _mono() - at
        return {**kept, "queue": [{k: v for k, v in t.items() if k not in self.KEEP_OUT} for t in self.queue[:500]],
                "idx": self.idx, "pos": round(max(0.0, pos), 2), "len": length,
                "shuffle": self.shuffle, "repeat": self.repeat, "active": self.active, "at": time.time()}

    def save(self, path) -> None:
        st = self.state()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(st), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def restore(self, path) -> bool:
        """The queue as it was when the app last closed, paused where it was; its songs are
        resolved after WARM_AFTER, so Play starts at once. Another player already playing
        keeps the window (HAND_BACK)."""
        try:
            st = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        try:
            v = max(0.0, min(1.0, float(st.get("volume", self.volume))))
            # saved before 1.2: an amplitude; the same loudness on the bar's cubic scale
            self.volume = v if st.get("volume_scale") == "cubic" else v ** (1 / 3)
        except (TypeError, ValueError):
            pass
        self.bursts = [int(n) for n in st.get("bursts") or [] if isinstance(n, int) and n > 0][-self.BURSTS_KEPT:]
        q = [t for t in st.get("queue") or [] if isinstance(t, dict) and (t.get("path") or t.get("stream"))]
        if not q:
            return False
        self.queue = q
        self.idx = max(0, min(int(st.get("idx") or 0), len(q) - 1))
        self.shuffle = bool(st.get("shuffle"))
        self.repeat = st.get("repeat") if st.get("repeat") in ("off", "all", "one") else "off"
        pos = float(st.get("pos") or 0.0)
        length = float(st.get("len") or 0.0) or (q[self.idx].get("ms") or 0) / 1000.0
        if length and pos > length - 3:
            pos = 0.0
        self._resume_at = pos
        self._cued = True
        self.active = bool(st.get("active"))
        now = _mono()
        with self._lock:
            self._snap = (pos, now, False, length)
        self._paused_at = now - 3600          # long paused: a player that is playing keeps the window
        if any(t.get("stream") for t in q[self.idx:self.idx + 1 + self.AHEAD]):
            QTimer.singleShot(int((self.WARM_ACTIVE if self.active else self.WARM_AFTER) * 1000), self._warm)
        return True

    WARM_AFTER = 4.0     # after startup settles: resolve the restored song and the next few
    WARM_ACTIVE = 0.5    # the queue last played here: its links at once, so Play does not wait

    def _warm(self) -> None:
        """The restored queue's links, fetched before Play is pressed (no audio, nothing loaded).
        Loading the song itself as well was tried and taken out; see home_page.md, 2026-10-22."""
        if not self._cued:
            return
        if self.resolver is None and self.ensure is not None:
            self.ensure()
        t = self.current
        if self.resolver is None or t is None:
            return
        if t.get("stream"):
            self.resolver.want(t)
        self._prefetch_quiet()

    def start_cued(self) -> None:
        """Play pressed on a restored queue: load where it was and carry on from there."""
        if not self._make():
            self.failed.emit("Qt Multimedia is not available")
            return
        self._cued = False
        self.active = True
        at = self._resume_at
        self._load()
        self._resume_at = at

    def replace_after(self, tracks: list[dict]) -> None:
        """Everything after the song playing becomes `tracks`; the song plays on."""
        self.queue[self.idx + 1:] = list(tracks)
        self.changed.emit()
        self._prefetch_quiet()

    def enqueue(self, tracks: list[dict], next_: bool = False) -> None:
        if not self.queue:
            self.play(tracks)
            return
        if next_:
            at = self.idx + 1
        else:
            # added by hand: after the other songs added by hand, before what autoplay found
            at = next((i for i in range(self.idx + 1, len(self.queue)) if self.queue[i].get("_auto")),
                      len(self.queue))
        self.queue[at:at] = list(tracks)
        self.changed.emit()
        self._prefetch_quiet()

    def _prefetch_quiet(self) -> None:
        """The next few: a stream resolved (its Spotify id looked for with it), a file's
        Spotify id looked for by its tags, so its lyrics can go to Spicy Lyrics at once."""
        if self.resolver is None:
            return
        for t in self.queue[self.idx + 1:self.idx + 1 + self.AHEAD]:
            if t.get("stream"):
                self.resolver.want(t)
            elif t.get("title") and not t.get("spotify"):
                self.resolver.look_spotify(t)

    def resume_after_end(self) -> None:
        """Songs were added after the queue ran out: go on with the first of them."""
        if (self.ended or self.wants_next) and self.idx + 1 < len(self.queue):
            self.ended = self.wants_next = False
            self.idx += 1
            self._load()

    def _load(self) -> None:
        t = self.current
        if t is None or self.player is None:
            return
        if t is not self._last_t:           # a new song, not the same one reloaded after a stream error
            self._last_t, self._changed_at = t, _mono()
            self._refetch = None
            self.wants_next = False
            # The last song's place is not this one's: a stale link reloaded from _heard
            # started the new song where the old one was (2026-10-24, "Could not open file").
            self._heard, self._resume_at, self._seek = 0.0, None, None
            with self._lock:
                self._snap = (0.0, self._changed_at, False, 0.0)
        self.loading = None
        if t.get("stream") and self.resolver is None and self.ensure is not None:
            self.ensure()
        if t.get("stream"):
            got = self.resolver.known(t) if self.resolver else None
            if got is not None:
                self.resolver.look_spotify(t)        # from a kept link: its id is still looked for (or checked)
            if got is None:
                self.player.stop()
                if self.resolver is None:
                    self.failed.emit("streaming is not set up")
                    return
                self.loading = self.resolver.key(t)
                self.resolver.want(t, now=True)
                self._sample()
                self.changed.emit()
                return
            self._take(t, got)
            self._resume_src = QUrl(SR.wrap(got["url"]))
        else:
            self._resume_src = QUrl.fromLocalFile(t["path"])
        self.player.setSource(self._resume_src)
        self.player.play()
        self._tick.start()
        self._sample()
        self.changed.emit()
        self._prefetch()

    @staticmethod
    def _take(t: dict, got: dict) -> None:
        """A resolution's Spotify id and Apple's fuller name and credits, onto the track."""
        t["spotify"] = got.get("spotify") or t.get("spotify", "")
        for x, v in (got.get("meta") or {}).items():
            # a YouTube pick's thumbnail is a video frame cropped square: the release's cover beats it
            if v and (x != "art" or not t.get("art") or "ytimg.com/" in t.get("art", "")):
                t[x] = v

    AHEAD_MIN, AHEAD_MAX = 3, 10
    QUICK = 10.0         # a skip within this long of the song changing continues a run of skips
    BURSTS_KEPT = 20     # runs remembered: the longest of these sets how far ahead to resolve

    @property
    def AHEAD(self) -> int:                              # noqa: N802
        """Songs resolved ahead: the longest recent run of quick skips, so its last song is ready."""
        return max(self.AHEAD_MIN, min(self.AHEAD_MAX, max(self.bursts[-self.BURSTS_KEPT:], default=0)))

    def _note_skip(self) -> None:
        now = _mono()
        if self._by_skip and self.bursts and now - self._changed_at < self.QUICK:
            self.bursts[-1] += 1
        else:
            self.bursts.append(1)
            del self.bursts[:-self.BURSTS_KEPT]

    STALL = 0.6         # playing but not moving for this long: the clock waits instead of running on
    SEEK_WAIT = 3.0      # longest a seek holds the clock before the position is trusted again
    END_STUCK = 1.5      # at the end and not moving for this long: the song is over

    def _prefetch(self) -> None:
        """Resolve the next few streams while this one plays, so skipping does not wait."""
        self.near_end.emit()          # every song: autoplay keeps the queue topped up
        self._prefetch_quiet()

    def on_resolved(self, key: str, info) -> None:
        t = self.current
        if t is not None and key == self._refetch:
            self._refetch = None
            if info and info.get("url"):
                self._switch(info)
            else:
                self.failed.emit((info or {}).get("error") or "the stream dropped")
            return
        if t is None or self.loading != key:
            return
        self.loading = None
        if not info or not info.get("url"):
            self.failed.emit((info or {}).get("error") or "this song could not be found to stream")
            # blocked: the next song fails alike, and skipping through the queue asks YouTube again each time
            if self.idx + 1 < len(self.queue) and not (info or {}).get("blocked"):
                self.step(1)
            return
        self._load()

    def _note(self, event: str, **kw) -> None:
        if self.log is not None:
            try:
                self.log(event, **kw)
            except Exception:                            # noqa: BLE001
                pass

    def _status(self, st) -> None:
        from PyQt6.QtMultimedia import QMediaPlayer
        S = QMediaPlayer.MediaStatus
        if self.log is not None and (self._seek is not None or self._stalled_at is not None):
            self._note("local-status", st=st.name, pos=round(self.player.position() / 1000.0, 3))
        if (self._resume_at is not None and st in (S.LoadedMedia, S.BufferedMedia)
                and self._resume_src is not None and self.player.source() == self._resume_src):
            # The old stream's stop() reports LoadedMedia too; spending the place on it
            # started the new link at 0:00.
            at, self._resume_at = self._resume_at, None
            self._do("seek", at)            # held like a clicked line until the audio is heard there
            return
        if st == S.EndOfMedia:
            length = self.player.duration() / 1000.0
            if length and self._snap[0] < length - 5 and self.current and self.current.get("stream"):
                # the stream was cut short, not the song over: fetch it again and carry on
                with self._lock:
                    self._resume_at = self._heard   # stopped: hold the place, not Qt's
                self._error(None, "the stream ended early")
                return
            self.step(1, ended=True)

    def step(self, d: int, ended: bool = False) -> None:
        if not self.queue:
            return
        if self.log is not None:            # who moved the queue: Next/Previous, a song's end, a failed find
            import traceback
            who = " < ".join(f"{f.name}:{f.lineno}" for f in reversed(traceback.extract_stack()[:-1][-4:]))
            self._note("local-step", d=d, ended=ended, at=self.idx, of=len(self.queue),
                       song=(self.current or {}).get("title", "")[:40], caller=who)
        skip = d > 0 and not ended
        if skip:
            self._note_skip()
        self._by_skip = skip
        if self._cued:                     # Next/Previous on a restored queue: start it moving
            if not self._make():
                return
            self._cued, self.active = False, True
            self.idx = max(0, min(len(self.queue) - 1, self.idx + d))
            self._resume_at = None
            self._load()
            return
        self._resume_at = None
        if ended and self.repeat == "one":
            self.player.setPosition(0)
            self.player.play()
            return
        if d < 0 and self._snap[0] > 3.0:
            self.player.setPosition(0)
            return
        n = self.idx + d
        if n >= len(self.queue):
            if self.repeat != "all" and skip and self.can_grow is not None and self.can_grow():
                # autoplay is still finding songs: stopping rewound this one to 0:00 (2026-10-28)
                self.wants_next = True
                self.ran_out.emit()
                return
            if self.repeat != "all":
                self.player.stop()
                self.ended = True
                self._sample()
                self.changed.emit()
                self.ran_out.emit()
                return
            n = 0
        self.idx = max(0, n)
        self._load()

    def toggle(self) -> None:
        if self._cued:
            self.start_cued()
            return
        if self.player is None:
            return
        from PyQt6.QtMultimedia import QMediaPlayer
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()
            self.active = True
        self._sample()

    def pause(self) -> None:
        if self.player is not None:
            self.player.pause()
            self._sample()

    def stand_down(self) -> None:
        """Another player is wanted now: pause, and stop being followed."""
        self.pause()
        self.active = False

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, v))
        self._apply_volume()

    def _apply_volume(self) -> None:
        """Into the mixer where there is one (the desktop's per-app volume shows it), else as
        Qt's gain on the mixer's cubic scale -- straight amplitude puts all the quiet under 10%."""
        self.mixer.set(self.volume)
        if self.out is not None:
            self.out.setVolume(1.0 if self._gain_one else MV.gain(self.volume))

    def _mixer_holds(self) -> None:
        if not self._gain_one:
            self._gain_one = True
            self._apply_volume()

    def _mixer_moved(self, v: float) -> None:
        """Moved from the desktop's mixer: the bar follows."""
        self.volume = v
        self.changed.emit()

    def _do(self, what: str, arg: float) -> None:
        if what == "seek" and self.player is not None:
            to, now = max(0.0, arg), _mono()
            if self.log is not None:
                self._note("local-seek", to=round(to, 3), was=round(self._heard, 3),
                           st=self.player.mediaStatus().name, stream=bool((self.current or {}).get("stream")))
            self._seek = [to, now, None]
            with self._lock:
                self._snap = (to, now, self._snap[2], self._snap[3])
            self.player.setPosition(int(to * 1000))
            self._sample()
        elif what == "PlayPause":
            self.toggle()
        elif what == "Next":
            self.step(1)
        elif what == "Previous":
            self.step(-1)
        elif what == "volume":
            self.set_volume(arg)

    def _sample(self) -> None:
        if self.player is None:
            return
        from PyQt6.QtMultimedia import QMediaPlayer
        on = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if on:
            self._paused_at = None
        elif self._snap[2] and self._paused_at is None:
            self._paused_at = _mono()
        pos, length = self.player.position() / 1000.0, self.player.duration() / 1000.0
        now = _mono()
        if self._seek is not None:
            to, when, landed = self._seek
            if not on or now - when > self.SEEK_WAIT or (
                    landed is not None and abs(landed - to) < 1.0 and 0.001 < pos - landed < 1.0):
                self._seek = None              # heard moving on from where it landed (or given up on)
                self._note("local-seek-heard", to=round(to, 3), after=round(now - when, 3), pos=round(pos, 3),
                           why="paused" if not on else "gave up" if now - when > self.SEEK_WAIT else "moving")
            else:
                if landed is None or abs(pos - landed) >= 1.0:
                    self._seek[2] = pos        # the old place, then where the seek landed
                pos = to                       # refilling: the words wait at the line
        if on:
            self._heard = pos
        if abs(pos - self._snap[0]) > 0.001 or not on:
            if self._stalled_at is not None:
                self._note("local-stall-end", lasted=round(now - self._stalled_at, 3), pos=round(pos, 3),
                           playing=on)
                self._stalled_at = None
            self._moved_at = now
        elif self._stalled_at is None and now - self._moved_at > self.STALL:
            self._stalled_at = self._moved_at
            if self.log is not None:
                self._note("local-stall", pos=round(pos, 3), st=self.player.mediaStatus().name)
        with self._lock:
            self._snap = (pos, now, on, length)
        if not on and self.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            self._tick.stop()
        elif on and length and pos >= length - 1.0 and now - self._moved_at > self.END_STUCK:
            # at the end and not moving, but never said EndOfMedia: it has finished
            self._moved_at = now
            self.step(1, ended=True)

    # ------------------------------------------------------------ any thread
    def reading(self) -> dict:
        t = self.current or {}
        with self._lock:
            pos, at, on, length = self._snap
        now = _mono()
        held = False
        if self._resume_at is not None:
            pos, at, held = self._resume_at, now, on      # loading to carry on from here: not Qt's 0:00
        elif on and self._seek is not None:
            pos, at, held = self._seek[0], now, True     # sought: words wait for the audio there
        elif on and now - self._moved_at < self.STALL:
            pos, at = pos + (now - at), now
        elif on:
            at, held = now, True            # stalled (buffering): hold where the audio is
        if t.get("stream"):
            sid = self.resolver.spotify_of(t) if self.resolver else t.get("spotify", "")
            # Unresolved, with no Spotify id yet: no track, rather than one id now and another in a second.
            tid = sid or (None if self.loading else _key(t.get("title", ""), t.get("artist", "")))
            if self.loading:
                pos, on, length = (self._resume_at or 0.0), False, (t.get("ms") or 0) / 1000.0
        else:
            tid = t.get("tid") or _key(t.get("title", ""), t.get("artist", ""))
        return {"tid": tid,
                "status": "Playing" if on else "Paused", "pos": pos, "at": at, "held": held,
                "volume": self.volume, "source": "local", "who": APP,
                "meta": {"title": t.get("title", ""), "artist": t.get("artist", ""),
                         "artists": [a.get("name", "") for a in t.get("artists") or [] if isinstance(a, dict)],
                         "album": t.get("album", ""), "album_artist": "",
                         "art": t.get("art", ""), "length": length or t.get("ms", 0) / 1000.0,
                         # the YouTube upload the audio is: its captions put the lyrics on its clock
                         "yt": (t.get("yt") or ((self.resolver.known(t) or {}).get("yt", "")
                                if self.resolver is not None else "")) if t.get("stream") else "",
                         # an upload picked by hand (YouTube tab, a pasted link): its own recording, its own offset
                         "upload": t.get("yt", "") if t.get("stream") else "",
                         "url": (QUrl.fromLocalFile(t["path"]).toString() if t.get("path") else "")}}

    def tell(self, what: str, arg: float = 0.0) -> None:
        self._cmd.emit(what, float(arg))


class LocalOverlay:
    """The window's transport with the local player in front while it is in use."""

    HAND_BACK = 2.0

    def __init__(self, inner, local: LocalPlayer) -> None:
        self.inner, self.local = inner, local
        self.pinned: str | None = None      # "mild", "spotify", a session's name, or None
        self.pin_name = ""
        self.pin_lost = ""                  # set when a pinned player went away (for a toast)

    def _session(self):
        """The part that lists every player (bus / media transport / now-playing), if any."""
        for part in (self.inner, getattr(self.inner, "backup", None)):
            if part is not None and hasattr(part, "_sessions"):
                return part
        return None

    def pin(self, who: str | None, name: str = "") -> None:
        """Follow only this player until unpinned: "mild", "spotify", or a session's name."""
        sess, inner = self._session(), self.inner
        if sess is not None:
            sess.pinned = None
        if hasattr(inner, "pin_side"):
            inner.pin_side = None
        self.pinned, self.pin_name, self.pin_lost = who, name if who else "", ""
        if who is None or who == "mild":
            if who == "mild" and self.local.current is not None:
                self.local.active = True
            return
        self.local.stand_down() if self.local.active else None
        home = getattr(sess, "HOME", "") if sess is not None else ""
        if who == "spotify" or (home and who == home):
            if hasattr(inner, "pin_side"):
                inner.pin_side = "primary"
            elif sess is not None and home:
                sess.pinned = home
        elif sess is not None:
            sess.pinned = who
            sess.who = who
            if hasattr(inner, "pin_side"):
                inner.pin_side = "backup"

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def mine(self) -> bool:
        return self.local.active and self.local.current is not None

    @property
    def name(self) -> str:
        return APP if self.mine() else getattr(self.inner, "name", "")

    @property
    def app(self) -> str:
        # as its sound is named in the mixer (PULSE_PROP application.name), for audio_sink
        return "mild lyrics" if self.mine() else getattr(self.inner, "app", "spotify")

    @property
    def HAS_VOLUME(self) -> bool:                       # noqa: N802
        return True if self.mine() else bool(getattr(self.inner, "HAS_VOLUME", False))

    def read(self, want_volume: bool) -> dict:
        if self.pinned not in (None, "mild", "spotify"):
            sess = self._session()
            if sess is not None and sess.pinned is None:
                # the pinned player went away: follow whoever plays again
                self.pin_lost, self.pinned = self.pin_name or "the pinned player", None
                if hasattr(self.inner, "pin_side"):
                    self.inner.pin_side = None
        if self.mine():
            if (self.pinned != "mild" and not self.local.playing()
                    and self.local.paused_for() > self.HAND_BACK):
                # paused here and something started elsewhere: follow that again
                try:
                    got = self.inner.read(want_volume)
                except Exception:                            # noqa: BLE001
                    got = None
                if got is not None and got.get("status") == "Playing":
                    self.local.active = False
                    return got
            return self.local.reading()
        return self.inner.read(want_volume)

    @property
    def holds_seeks(self) -> bool:
        """Its readings say "held" until a seek is heard: the clock waits from the seek on."""
        return self.mine()

    def seek(self, seconds: float) -> None:
        if self.mine():
            self.local.tell("seek", seconds)
        else:
            self.inner.seek(seconds)

    def set_volume(self, v: float) -> None:
        if self.mine():
            self.local.tell("volume", v)
        else:
            self.inner.set_volume(v)

    def command(self, name: str) -> None:
        if self.mine():
            self.local.tell(name)
        else:
            self.inner.command(name)

    def drop(self) -> None:
        self.inner.drop()
