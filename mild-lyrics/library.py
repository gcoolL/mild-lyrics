"""Mild Lyrics' own library (liked songs, playlists, artists, albums) in
library.json, for songs from any catalogue. Notes:
docs/notes/mild-lyrics/home_page.md."""
from __future__ import annotations

import json
import pathlib
import re
import time
import unicodedata
import uuid

KEEP = ("kind", "uri", "name", "sub", "art", "ms", "album", "album_uri", "artists", "path", "tid",
        "title", "artist", "year", "isrc", "spotify")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)
    s = re.sub(r"\s+-\s+(remaster|live|edit|from|version).*$", " ", s)
    s = re.sub(r"['’‘ʼ`]", "", s)                     # "isn't" and "isnt" are one song
    return re.sub(r"[^\w]+", " ", s).strip()


def song_key(item: dict) -> str:
    """The same song whichever catalogue it came from: its name and first artist."""
    name = item.get("name") or item.get("title") or ""
    who = (item.get("sub") or item.get("artist") or "").split(",")[0]
    return _norm(name) + "|" + _norm(who)


def entity_key(item: dict) -> str:
    """An album or an artist: its name (and an album's artist)."""
    if item.get("kind") == "artist":
        return "artist|" + _norm(item.get("name", ""))
    return "album|" + _norm(item.get("name", "")) + "|" + _norm((item.get("sub") or "").split("·")[0])


def slim(item: dict) -> dict:
    """What is worth keeping of an item: enough to show it, play it and find its lyrics."""
    out = {k: item[k] for k in KEEP if item.get(k) not in (None, "", [])}
    if item.get("_track"):
        out.setdefault("path", item["_track"].get("path", ""))
    out["kind"] = {"local": "local", "artist": "artist", "album": "album"}.get(item.get("kind"), "track")
    return out


class Library:
    def __init__(self, path: pathlib.Path, write: bool = True) -> None:
        """`write` False (--no-persist) neither reads nor writes the file: an empty library."""
        self.path = pathlib.Path(path)
        self.write = write
        self.rev = 0
        self.d = {"liked": [], "playlists": [], "artists": [], "albums": [], "mirror": {}, "sp_pending": {}}
        try:
            if not write:
                raise OSError("not read under --no-persist")
            got = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                for k in self.d:
                    if isinstance(got.get(k), type(self.d[k])):
                        self.d[k] = got[k]
        except Exception:                                    # noqa: BLE001
            pass
        self._index()

    def _index(self) -> None:
        self._liked = {song_key(x) for x in self.d["liked"]}
        self._ents = {entity_key(x) for x in self.d["artists"] + self.d["albums"]}

    def save(self) -> None:
        self.rev += 1
        self._index()
        if not self.write:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    # ------------------------------------------------------------ liked songs
    def liked(self) -> list[dict]:
        return self.d["liked"]

    def is_liked(self, item: dict) -> bool:
        return song_key(item) in self._liked

    def like(self, item: dict, on: bool) -> None:
        k = song_key(item)
        self.d["liked"] = [x for x in self.d["liked"] if song_key(x) != k]
        if on:
            self.d["liked"].insert(0, dict(slim(item), added=time.time()))
        self.save()

    # -------------------------------------------------------------- playlists
    def playlists(self) -> list[dict]:
        return self.d["playlists"]

    def playlist(self, pid: str) -> dict | None:
        return next((p for p in self.d["playlists"] if p["id"] == pid), None)

    def create(self, name: str, items: list | None = None) -> dict:
        pl = {"id": uuid.uuid4().hex[:12], "name": name.strip() or "My playlist", "created": time.time(),
              "items": [slim(x) for x in items or []]}
        self.d["playlists"].insert(0, pl)
        self.save()
        return pl

    def rename(self, pid: str, name: str) -> None:
        pl = self.playlist(pid)
        if pl and name.strip():
            pl["name"] = name.strip()
            self.save()

    def delete(self, pid: str) -> dict | None:
        pl = self.playlist(pid)
        if pl:
            self.d["playlists"].remove(pl)
            self.save()
        return pl

    def restore(self, pl: dict, at: int = 0) -> None:
        self.d["playlists"].insert(at, pl)
        self.save()

    def add(self, pid: str, items: list[dict]) -> int:
        """Adds the songs not already in it; returns how many were added."""
        pl = self.playlist(pid)
        if not pl:
            return 0
        have = {song_key(x) for x in pl["items"]}
        new = [slim(x) for x in items if song_key(x) not in have]
        pl["items"].extend(new)
        self.save()
        return len(new)

    def remove(self, pid: str, index: int) -> dict | None:
        pl = self.playlist(pid)
        if not pl or not 0 <= index < len(pl["items"]):
            return None
        gone = pl["items"].pop(index)
        self.save()
        return gone

    def insert(self, pid: str, index: int, item: dict) -> None:
        pl = self.playlist(pid)
        if pl:
            pl["items"].insert(max(0, min(index, len(pl["items"]))), item)
            self.save()

    def move(self, pid: str, src: int, dst: int) -> None:
        pl = self.playlist(pid)
        if not pl or not 0 <= src < len(pl["items"]):
            return
        it = pl["items"].pop(src)
        pl["items"].insert(max(0, min(dst, len(pl["items"]))), it)
        self.save()

    # ------------------------------------------------------ artists and albums
    def follows(self, item: dict) -> bool:
        return entity_key(item) in self._ents

    def follow(self, item: dict, on: bool) -> None:
        bucket = "artists" if item.get("kind") == "artist" else "albums"
        k = entity_key(item)
        self.d[bucket] = [x for x in self.d[bucket] if entity_key(x) != k]
        if on:
            self.d[bucket].insert(0, dict(slim(item), kind=item.get("kind"), added=time.time()))
        self.save()

    def artists(self) -> list[dict]:
        return self.d["artists"]

    def albums(self) -> list[dict]:
        return self.d["albums"]

    # ------------------------------------- Spotify likes changed while it was away
    def pending(self) -> dict:
        """Spotify track uri -> liked (True) or unliked (False), not yet told to Spotify."""
        return self.d.setdefault("sp_pending", {})

    def pend(self, uri: str, on: bool) -> None:
        self.pending()[uri] = on
        self.save()

    def told(self, uri: str) -> None:
        if self.pending().pop(uri, None) is not None:
            self.save()

    # ----------------------------------------------------- Spotify's, kept
    def mirror(self, key: str, value) -> None:
        """Keep Spotify's last answer for a library key, to show while Spotify is away."""
        if self.d["mirror"].get(key) == value:
            return
        self.d["mirror"][key] = value
        self.save()

    def mirrored(self, key: str):
        return self.d["mirror"].get(key)
