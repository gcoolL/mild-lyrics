"""What was listened to here, from every player the window follows.

One JSON line per play in plays.jsonl beside gui.json. Nothing leaves the
machine. Feeds Your stats, Recently played and the home page's reasons.
Notes: docs/notes/mild-lyrics/home_page.md.
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
from collections import Counter, defaultdict

COUNTS_AT = 30.0        # seconds before a play counts, as Spotify counts it
SKIP_BEFORE = 30.0      # a song left within this is a skip
PERIODS = {"Week": 7, "Month": 30, "Year": 365}
KINDS = {"syllable": "w", "line": "l", "static": "l"}


def artists_of(text: str) -> list[str]:
    return [a.strip() for a in (text or "").split(",") if a.strip()]


class PlayLog:
    """The log on disk and in memory; appends are cheap, reads are in memory."""

    def __init__(self, path: pathlib.Path, write: bool = True) -> None:
        self.path = pathlib.Path(path)
        self.write = write
        self.rows: list[dict] | None = None
        self._lock = threading.Lock()
        self.rev = 0

    def load(self) -> list[dict]:
        if self.rows is not None:
            return self.rows
        rows = []
        try:
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(r, dict) and r.get("title"):
                        rows.append(r)
        except OSError:
            pass
        self.rows = rows
        return rows

    def add(self, row: dict) -> None:
        self.load().append(row)
        self.rev += 1
        if not self.write:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def forget(self) -> None:
        self.rows = []
        self.rev += 1
        if not self.write:
            return
        try:
            self.path.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------ queries
    def since(self, days: float) -> list[dict]:
        cut = time.time() - days * 86400
        return [r for r in self.load() if r.get("t", 0) >= cut]

    @staticmethod
    def counted(r: dict) -> bool:
        return not r.get("skip") and r.get("s", 0) >= min(COUNTS_AT, 0.5 * (r.get("len") or 60))

    def recent(self, n: int = 50) -> list[dict]:
        """Newest first, one row per play, repeats of the same song in a row kept."""
        out = []
        for r in reversed(self.load()):
            if r.get("s", 0) < 5:
                continue
            out.append(r)
            if len(out) >= n:
                break
        return out

    def top_artists(self, days: float, n: int = 6) -> list[tuple[str, int]]:
        c: Counter = Counter()
        for r in self.since(days):
            if self.counted(r):
                for a in artists_of(r.get("artist", ""))[:1]:
                    c[a] += 1
        return c.most_common(n)

    def top_songs(self, days: float, n: int = 5) -> list[tuple[dict, int]]:
        c: Counter = Counter()
        last: dict = {}
        for r in self.since(days):
            if self.counted(r):
                k = (r.get("title", "").lower(), r.get("artist", "").lower())
                c[k] += 1
                last[k] = r
        return [(last[k], m) for k, m in c.most_common(n)]

    def plays_of(self, title: str = "", artist: str = "", days: float = 3650) -> int:
        t, a = title.lower(), artist.lower()
        n = 0
        for r in self.since(days):
            if not self.counted(r):
                continue
            if t and r.get("title", "").lower() != t:
                continue
            if a and a not in [x.lower() for x in artists_of(r.get("artist", ""))]:
                continue
            n += 1
        return n

    def days_played(self, artist: str, days: int = 14) -> int:
        a = artist.lower()
        got = set()
        for r in self.since(days):
            if self.counted(r) and a in [x.lower() for x in artists_of(r.get("artist", ""))]:
                got.add(time.strftime("%Y-%m-%d", time.localtime(r["t"])))
        return len(got)

    def skipped(self, times: int = 2) -> set[str]:
        """Song keys (title|artist lower) left early at least `times` times."""
        c: Counter = Counter()
        for r in self.load():
            if r.get("skip"):
                c[(r.get("title", "").lower() + "|" + r.get("artist", "").lower())] += 1
        return {k for k, m in c.items() if m >= times}

    def heard(self) -> set[str]:
        return {r.get("title", "").lower() + "|" + r.get("artist", "").lower()
                for r in self.load()}

    def heard_artists(self) -> set[str]:
        return {a.lower() for r in self.load() for a in artists_of(r.get("artist", ""))}

    def stats(self, period: str) -> dict:
        days = PERIODS.get(period, 30)
        rows = self.since(days)
        secs = sum(r.get("s", 0) for r in rows)
        played = [r for r in rows if self.counted(r)]
        artists = {a for r in played for a in artists_of(r.get("artist", ""))[:1]}
        hours = [0.0] * 24
        players: Counter = Counter()
        kinds: Counter = Counter()
        for r in rows:
            s = r.get("s", 0)
            hours[time.localtime(r.get("t", 0)).tm_hour] += s
            players[r.get("player") or "Spotify"] += s
            kinds[r.get("kind") or "n"] += s
        return {"secs": secs, "plays": len(played), "artists": len(artists),
                "lines": sum(r.get("lines", 0) for r in rows),
                "top_artists": self.top_artists(days), "top_songs": self.top_songs(days),
                "hours": hours, "players": players, "kinds": kinds}


class Tracker:
    """Turns the window's readings into rows: one row per song, written when it ends."""

    def __init__(self, log: PlayLog) -> None:
        self.log = log
        self.cur: dict | None = None
        self.on_row = None              # called with each row written: autoplay hears its skips
        self._last_at = 0.0
        self._lines: set = set()

    def observe(self, tid: str | None, meta: dict, playing: bool, pos: float,
                player: str, kind: str, line: int | None, uri: str = "", auto: bool = False) -> None:
        now = time.monotonic()
        title = (meta or {}).get("title") or ""
        if not tid or not title:
            self.flush()
            return
        cur = self.cur
        if cur is not None and cur["tid"] != tid and cur["title"] == title and \
                cur["artist"] == (meta.get("artist") or "") and -1.0 <= pos - cur["pos"] < 5.0:
            cur["tid"] = tid            # the same play, its Spotify id found mid-song: not a skip and a new play
        if self.cur is None or self.cur["tid"] != tid:
            self.flush()
            self.cur = {"tid": tid, "t": round(time.time(), 1), "title": title,
                        "artist": meta.get("artist") or "", "album": meta.get("album") or "",
                        "art": meta.get("art") or "", "len": round(float(meta.get("length") or 0), 1),
                        "path": meta.get("path") or "",
                        "player": player or "Spotify", "uri": uri, "s": 0.0, "pos": pos,
                        "kind": KINDS.get(kind, "n")}
            if auto:
                self.cur["auto"] = True         # autoplay's pick, not the listener's
            self._lines = set()
            self._last_at = now
            return
        cur = self.cur
        if playing:
            step = now - self._last_at
            # only while the audio moves: a song stuck loading counted as heard, then as a skip (2026-10-28)
            if 0 < step < 5 and pos > cur["pos"]:
                cur["s"] += step
            if line is not None and line >= 0:
                self._lines.add(line)
        cur["pos"] = pos
        if kind:
            cur["kind"] = KINDS.get(kind, cur["kind"])
        self._last_at = now

    def flush(self) -> None:
        cur, self.cur = self.cur, None
        if not cur or cur["s"] < 5:
            return
        length = cur.get("len") or 0
        cur["skip"] = bool(cur["s"] < SKIP_BEFORE and length > 60
                           and cur.get("pos", 0) < length - 10)
        cur["lines"] = len(self._lines)
        cur["s"] = round(cur["s"], 1)
        cur.pop("pos", None)
        self.log.add(cur)
        if self.on_row is not None:
            self.on_row(cur)


def by_day(rows: list[dict]) -> dict[str, list[dict]]:
    """Rows grouped as Today / Yesterday / a date, newest first."""
    out: dict[str, list[dict]] = defaultdict(list)
    today = time.strftime("%Y-%m-%d")
    yday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    for r in rows:
        d = time.strftime("%Y-%m-%d", time.localtime(r.get("t", 0)))
        label = "TODAY" if d == today else "YESTERDAY" if d == yday else \
            time.strftime("%A %d %B", time.localtime(r.get("t", 0))).upper()
        out[label].append(r)
    return out
