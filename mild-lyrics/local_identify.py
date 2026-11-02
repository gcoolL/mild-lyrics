"""Which released song a file on this computer is (Settings ▸ Home ▸ Identify songs):
its tags or file name matched on Deezer, the length checked. Notes:
docs/notes/mild-lyrics/local_player.md."""
from __future__ import annotations

import collections
import json
import pathlib
import re
import threading
import time
import urllib.parse

from PyQt6.QtCore import QObject, pyqtSignal

import stream_source as SS

MISS_KEPT = 7 * 86400       # s a file Deezer had no match for waits before it is asked again
PICK_V = 2                  # misses kept by an older pick() are asked again
NAMED_SLACK = 15.0          # s a file may be off when its title and artist match exactly
NAMED_SLACK_SHARE = 0.08    # ...or this share of its length, if more (downloads carry intros)
WALK_GAP = 1.0              # s between background asks while the whole library is walked
SAVE_EVERY = 25             # answers between writes of the kept file during a walk
NAME_NOISE = re.compile(r"\s*(?:\[[\w-]{11}\]|[\[(](?:official[^\])]*|lyrics?[^\])]*|audio|hq|hd|4k|mv|m/v|"
                        r"visuali[sz]er|music video|video)[\])])", re.I)


def _file_name(path: str) -> str:
    """A file's stem without what downloaders add: "[dQw4w9WgXcQ]", "(Official Video)", "01 "."""
    stem = pathlib.Path(path).stem
    stem = NAME_NOISE.sub(" ", stem)
    stem = re.sub(r"^\d{1,3}[\s.\-_]+", "", stem).replace("_", " ")
    return " ".join(stem.split())


def asked_as(t: dict, clean=None) -> tuple[str, str, str]:
    """(title, artist, query): the file's own tags, else its cleaned name."""
    import local_player as LP
    path = pathlib.Path(t.get("path", ""))
    title, artist = t.get("title", ""), t.get("_id_artist") or t.get("artist", "")
    if (title, artist) != LP._from_name(path) and title and artist:
        return title, artist, f"{artist.split(',')[0].strip()} {title}"
    name = _file_name(str(path))
    if clean is not None and " - " in name:
        try:
            title, artist = clean(name, "")
        except Exception:                                    # noqa: BLE001
            pass
    elif " - " in name:
        artist, title = (x.strip() for x in name.split(" - ", 1))
    else:
        title, artist = name, ""
    return title, artist, (f"{artist} {title}" if artist else name)


def pick(rows: list, title: str, artist: str, ms: float, query: str) -> dict | None:
    """The Deezer row that is this file: same title and artist (or both inside the file
    name when it has no artist), same version words, the length within slack."""
    want_t, want_a, q = SS.norm(title), SS.norm(artist.split(",")[0]), f" {SS.norm(query)} "
    wanted_cut = SS.versions(title)
    best = None
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        rt = SS.norm(r.get("title_short") or r.get("title") or "")
        ra = SS.norm((r.get("artist") or {}).get("name", ""))
        if not rt or not ra:
            continue
        if want_a:
            if rt != want_t or not (want_a in ra or ra in want_a):
                continue
        elif f" {rt} " not in q or f" {ra} " not in q:
            continue
        if SS.versions(r.get("title", "")) != wanted_cut:
            continue
        gap = abs(float(r.get("duration") or 0) * 1000 - ms) if ms else 0.0
        slack = SS.DURATION_SLACK * 1000
        if want_a:                           # title and artist both matched: allow extra seconds
            slack = max(NAMED_SLACK * 1000, NAMED_SLACK_SHARE * ms, slack)
        if ms and gap > slack:
            continue
        if not ms and not want_a:            # a bare name and no length: too little to be sure of
            continue
        rank = (gap, bool(r.get("title_version")), -int(r.get("rank") or 0))
        if best is None or rank < best[0]:
            best = (rank, r)
    if best is None:
        return None
    r = best[1]
    al = r.get("album") or {}
    return {"title": r.get("title") or "", "artist": (r.get("artist") or {}).get("name", ""),
            "album": al.get("title", ""), "art": al.get("cover_xl") or al.get("cover_big") or "",
            "ms": int(r.get("duration") or 0) * 1000, "isrc": r.get("isrc") or "",
            "deezer": str(r["id"])}


def look(t: dict, clean=None) -> dict | None:
    """One file asked of Deezer: its card, or None. Raises when Deezer could not be asked."""
    title, artist, q = asked_as(t, clean)
    if not q.strip():
        return None
    rows = SS._get(f"{SS.DZ}/search?q={urllib.parse.quote(SS.dz_query(q))}&limit=15").get("data") or []
    return pick(rows, title, artist, float(t.get("ms") or 0), q)


class Identifier(QObject):
    """Files' answers, kept on disk by path and mtime; one worker asks, played songs first."""

    found = pyqtSignal(str)          # a path whose answer landed

    def __init__(self, path: pathlib.Path, clean=None) -> None:
        super().__init__()
        self.path, self.clean = path, clean
        self.on = False
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._urgent: collections.deque = collections.deque()
        self._walk: collections.deque = collections.deque()
        self._asking: set[str] = set()
        self._thread: threading.Thread | None = None
        self._unsaved = 0
        try:
            self._kept: dict = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            self._kept = {}

    # ------------------------------------------------------------ answers
    def _entry(self, t: dict) -> dict | None:
        """The kept answer for this file as it now is, or None (not asked, changed, or a stale miss)."""
        e = self._kept.get(t.get("path", ""))
        if not e or e.get("mt") != t.get("mt"):
            return None
        if e.get("hit") is None and (time.time() - e.get("at", 0) > MISS_KEPT
                                     or e.get("v", 1) < PICK_V):
            return None
        return e

    def hit(self, t: dict) -> dict | None:
        if not self.on or t.get("stream") or not t.get("path"):
            return None
        with self._lock:
            e = self._entry(t.get("_file") or t)
        return (e or {}).get("hit")

    def pending(self, t: dict) -> bool:
        """Being asked for, with no answer yet: the player waits on it rather than switch ids."""
        if not self.on or t.get("stream") or not t.get("path"):
            return False
        with self._lock:
            return t["path"] in self._asking and self._entry(t.get("_file") or t) is None

    def overlay(self, t: dict) -> dict:
        """The row as the song it was found to be: a copy, the file's own fields under `_file`."""
        import local_player as LP
        base = t.get("_file") or t
        got = self.hit(base)
        if got is None:
            return base
        out = dict(base)
        out["_file"] = base
        out.update(title=got["title"], artist=got["artist"], album=got["album"] or base.get("album", ""),
                   isrc=got.get("isrc", ""), tid=LP._key(got["title"], got["artist"]))
        if got.get("art") and not base.get("tag_art"):          # the file's own picture stays
            out["art"] = got["art"]
        out.pop("_id_artist", None)
        return out

    # ------------------------------------------------------------ asking
    def want(self, t: dict, now: bool = False) -> None:
        if not self.on or t.get("stream") or not t.get("path"):
            return
        base = t.get("_file") or t
        with self._lock:
            if self._entry(base) is not None or (not now and base["path"] in self._asking):
                return
            if now:
                self._urgent.append(base)
            else:
                self._walk.append(base)
            self._asking.add(base["path"])
            self._start()
            self._wake.notify()

    def walk(self, tracks: list[dict]) -> None:
        """Every file not answered yet, in the background, one at a time."""
        for t in tracks:
            self.want(t)

    def stop_walk(self) -> None:
        with self._lock:
            for t in self._walk:
                self._asking.discard(t["path"])
            self._walk.clear()

    def _start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="local-identify", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._urgent and not self._walk:
                    if self._unsaved:
                        self._save_locked()
                    if not self._wake.wait(60):
                        self._thread = None
                        return
                urgent = bool(self._urgent)
                t = (self._urgent or self._walk).popleft()
                if self._entry(t) is not None:              # asked for twice: answered already
                    continue
            try:
                hit = SS.in_lane(not urgent, look, t, self.clean)
            except Exception:                                # noqa: BLE001
                with self._lock:                             # not asked (offline, quota): asked again later
                    self._asking.discard(t["path"])
                self.found.emit(t["path"])
                time.sleep(WALK_GAP)
                continue
            with self._lock:
                self._kept[t["path"]] = {"mt": t.get("mt"), "at": time.time(), "hit": hit, "v": PICK_V}
                self._asking.discard(t["path"])
                self._unsaved += 1
                if self._unsaved >= SAVE_EVERY or urgent:
                    self._save_locked()
            self.found.emit(t["path"])
            if not urgent:
                time.sleep(WALK_GAP)

    def _save_locked(self) -> None:
        self._unsaved = 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._kept), encoding="utf-8")
        except OSError:
            pass
