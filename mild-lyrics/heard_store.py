"""Songs heard from YouTube, kept on disk so playing one again needs no lookup.
Notes: docs/notes/mild-lyrics/stream_source.md 2026-11-03."""
from __future__ import annotations

import json
import pathlib
import re
import threading
import time

HEARD_AFTER = 20.0           # seconds played before a song is kept
SIZES = ["off", "1 GB", "2 GB", "5 GB", "10 GB"]
DEFAULT = "2 GB"
_VID = re.compile(r"[\w-]{11}")


def cap_of(choice: str) -> int:
    """Bytes the store may hold for a SIZES choice (0: keep nothing)."""
    m = re.match(r"(\d+)\s*GB", str(choice or ""))
    return int(m.group(1)) * 2 ** 30 if m else 0


class Store:
    """{vid: {"file", "len", "size", "at"}} in `index.json` beside the files; the least
    recently played go first past the cap."""

    def __init__(self, folder: pathlib.Path) -> None:
        self.folder = folder
        self.index_p = folder / "index.json"
        self._lock = threading.Lock()
        self.busy: set[str] = set()
        self.log = None                 # log(event, **fields): the local player's follow.log
        try:
            self.index = json.loads(self.index_p.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            self.index = {}

    def path(self, vid: str, lens: tuple = (), touch: bool = True) -> str | None:
        """The kept file of `vid`, or None; with `lens`, only while it is within the slack of one.
        `touch` marks it played (the shedding order)."""
        import stream_source as SS
        with self._lock:
            got = self.index.get(vid)
        if not got:
            return None
        p = self.folder / got["file"]
        if not p.exists():
            self.drop(vid)
            return None
        want = [x for x in lens if x]
        if want and not any(abs(float(got.get("len") or 0) - x) <= SS.DURATION_SLACK for x in want):
            return None                 # the song's length moved off this upload: the resolver decides
        if touch:
            with self._lock:
                got["at"] = time.time()
            self._write()
        return str(p)

    def keep(self, vid: str, url: str, length: float, cap: int) -> None:
        """Saves the link's whole body on a thread, then sheds the oldest past `cap`."""
        if cap <= 0 or not _VID.fullmatch(vid or "") or not url.startswith("https://"):
            return
        with self._lock:
            if vid in self.index or vid in self.busy:
                return
            self.busy.add(vid)
        threading.Thread(target=self._keep, args=(vid, url, length, cap), daemon=True,
                         name="heard-store").start()

    def _keep(self, vid: str, url: str, length: float, cap: int) -> None:
        import stream_source as SS
        t0 = time.monotonic()
        try:
            p = pathlib.Path(SS.save_stream(url, self.folder, f"yt_{vid}_a"))   # (it strips "-" off the ends)
        except Exception as e:                           # noqa: BLE001
            self._note("heard-keep-failed", vid=vid, err=repr(e)[:160])
            return
        finally:
            with self._lock:
                self.busy.discard(vid)
        size = p.stat().st_size
        with self._lock:
            self.index[vid] = {"file": p.name, "len": round(float(length or 0), 2), "size": size,
                               "at": time.time()}
        self._note("heard-kept", vid=vid, size=size, took=round(time.monotonic() - t0, 2))
        self.shed(cap, spare=vid)

    def shed(self, cap: int, spare: str = "") -> None:
        """Oldest first until the files fit in `cap` (all of them at 0)."""
        with self._lock:
            order = sorted(self.index, key=lambda v: float(self.index[v].get("at") or 0))
            total = sum(int(e.get("size") or 0) for e in self.index.values())
            gone = []
            for v in order:
                if total <= cap:
                    break
                if v != spare:
                    total -= int(self.index[v].get("size") or 0)
                    gone.append(v)
        for v in gone:
            self.drop(v, write=False)
        self._write()

    def drop(self, vid: str, write: bool = True) -> None:
        with self._lock:
            got = self.index.pop(vid, None)
        if got:
            (self.folder / got["file"]).unlink(missing_ok=True)
        if write:
            self._write()

    def vid_of_path(self, path: str) -> str:
        name = pathlib.Path(path).name
        with self._lock:
            return next((v for v, e in self.index.items() if e.get("file") == name), "")

    def _write(self) -> None:
        with self._lock:
            body = json.dumps(self.index)
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.index_p.with_suffix(f".{threading.get_ident()}.tmp")
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(self.index_p)
        except OSError:
            pass

    def _note(self, event: str, **kw) -> None:
        try:
            if self.log is not None:
                self.log(event, **kw)
        except Exception:                                # noqa: BLE001
            pass
