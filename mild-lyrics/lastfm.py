"""Last.fm scrobbling: desktop sign-in, "now playing", and a scrobble at half
the song or 4 minutes. Notes: docs/notes/mild-lyrics/lastfm.md."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices

# Mild Lyrics' own API account; desktop scrobblers ship both, the session
# key each listener allows is what speaks for them.
API_KEY = "f0b2729db92fcf514849073979e816ba"
SECRET = "d66f1cb1775f9c61d59c037d4df7b097"
API = "https://ws.audioscrobbler.com/2.0/"
AUTH_PAGE = "https://www.last.fm/api/auth/"

DEFAULTS = {"lastfm_scrobble": True, "lastfm_spotify": False}
KEYS = ("lastfm_account",)
MENU_ROWS = [
    ("Account",              "lastfm_account",  "action", None),
    ("Scrobble",             "lastfm_scrobble", "bool",   None),
    ("Spotify plays too",    "lastfm_spotify",  "bool",   None),
]

NP_AFTER = 3.0            # heard seconds before "now playing" is sent
SCROBBLE_MAX = 240.0      # Last.fm's rule: half the song, or 4 minutes
SHORTEST = 30.0           # songs this short are never scrobbled
BATCH = 50                # track.scrobble takes at most 50 at once
TOO_OLD = 14 * 86400      # Last.fm ignores scrobbles older than this
POLL_MS = 4000            # asking whether the browser sign-in was allowed
POLL_FOR = 300.0          # seconds of asking before giving up
BACK_OFF = (60, 300, 900, 3600)
TRANSIENT = {8, 11, 16, 29}   # try again later; anything else is final
NOT_YET = 14              # auth.getSession: the token isn't allowed yet
BAD_SESSION = 9


def clean(values: dict) -> dict:
    """Saved settings, each the type its default is."""
    return {k: bool(values.get(k, d)) for k, d in DEFAULTS.items()}


def sign(params: dict) -> str:
    """api_sig: md5 of the sorted name/value pairs, then the secret."""
    raw = "".join(k + str(params[k]) for k in sorted(params) if k not in ("format", "callback"))
    return hashlib.md5((raw + SECRET).encode("utf-8")).hexdigest()


class Failed(Exception):
    def __init__(self, code: int, text: str) -> None:
        super().__init__(text)
        self.code = code


def call(method: str, params: dict | None = None, signed: bool = True,
         post: bool = False, ua: str = "Mild Lyrics") -> dict:
    """One API call; raises Failed (code 0 = no answer from Last.fm)."""
    p = {"method": method, "api_key": API_KEY, **(params or {})}
    if signed:
        p["api_sig"] = sign(p)
    p["format"] = "json"
    body = urllib.parse.urlencode(p).encode()
    req = urllib.request.Request(API if post else f"{API}?{body.decode()}",
                                 data=body if post else None, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            got = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            got = json.loads(exc.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            raise Failed(0 if exc.code >= 500 else -exc.code, f"HTTP {exc.code}") from None
    except (OSError, ValueError) as exc:
        raise Failed(0, str(exc)) from None
    if isinstance(got, dict) and got.get("error"):
        raise Failed(int(got["error"]), str(got.get("message") or ""))
    return got if isinstance(got, dict) else {}


def track_of(cur: dict, meta: dict) -> dict:
    """The fields Last.fm takes, from a tracker play and the player's metadata."""
    names = [str(a).strip() for a in (meta or {}).get("artists") or [] if str(a).strip()]
    t = {"artist": names[0] if names else cur.get("artist", ""), "track": cur.get("title", "")}
    if cur.get("album"):
        t["album"] = cur["album"]
    if cur.get("len"):
        t["duration"] = int(cur["len"])
    return t


class Scrobbler(QObject):
    """The account, the plays sent and the scrobbles waiting to go."""

    changed = pyqtSignal()
    say = pyqtSignal(str)
    _opened = pyqtSignal(str)

    def __init__(self, folder: pathlib.Path, ua: str, live: bool = True) -> None:
        super().__init__()
        self.path = pathlib.Path(folder) / "lastfm.json"
        self.qpath = pathlib.Path(folder) / "lastfm-queue.json"
        self.ua, self.live = ua, live
        self.user = self.sk = ""
        self.waiting: list[dict] = []
        self.note = ""                       # the last failure, in words
        self._lock = threading.Lock()
        self._jobs: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._play = None                    # (start, title) of the play being followed
        self._np = self._done = False
        self._sending = False
        self._retry_at = 0.0
        self._tries = 0
        self._token = ""
        self._asking = False
        self._token_until = 0.0
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._check_token)
        self._opened.connect(self._open_page)
        if live:
            self._load()

    # ------------------------------------------------------------ storage
    def _load(self) -> None:
        try:
            got = json.loads(self.path.read_text(encoding="utf-8"))
            self.user, self.sk = str(got.get("user") or ""), str(got.get("key") or "")
        except (OSError, ValueError, AttributeError):
            self.user = self.sk = ""
        try:
            got = json.loads(self.qpath.read_text(encoding="utf-8"))
            self.waiting = [s for s in got if isinstance(s, dict)] if isinstance(got, list) else []
        except (OSError, ValueError):
            self.waiting = []

    def _save_session(self) -> None:
        if not self.sk:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"user": self.user, "key": self.sk}, f)

    def _save_queue(self) -> None:
        if not self.live:
            return
        # The GUI thread and the worker both save: the write is held under the
        # lock too, so neither replaces the file with the other's half-written tmp.
        with self._lock:
            try:
                rows = list(self.waiting)
                if not rows:
                    self.qpath.unlink(missing_ok=True)
                    return
                self.qpath.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.qpath.with_suffix(".tmp")
                tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.qpath)
            except OSError:
                pass

    # -------------------------------------------------------------- worker
    def _run(self, job) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._work, daemon=True, name="lastfm")
            self._worker.start()
        self._jobs.put(job)

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception as exc:                        # noqa: BLE001
                self.note = str(exc)
            self.changed.emit()

    def _call(self, method: str, params: dict | None = None, **kw) -> dict:
        return call(method, params, ua=self.ua, **kw)

    # ------------------------------------------------------------- sign-in
    def signed_in(self) -> bool:
        return bool(self.sk)

    def account(self) -> None:
        """The Account row's button: sign in, open the page again, or sign out."""
        if self.sk:
            self.sign_out()
        elif self._token and time.time() < self._token_until:
            self._open_page(self._token)
        else:
            self.sign_in()

    def sign_in(self) -> None:
        if not self.live:
            return
        self.note = ""

        def job() -> None:
            try:
                tok = self._call("auth.getToken").get("token") or ""
            except Failed as exc:
                self.note = f"Last.fm refused: {exc}" if exc.code else "Last.fm didn't answer"
                return
            self._opened.emit(tok)
        self._run(job)

    def _open_page(self, token: str) -> None:
        self._token, self._token_until = token, time.time() + POLL_FOR
        QDesktopServices.openUrl(QUrl(f"{AUTH_PAGE}?api_key={API_KEY}&token={token}"))
        self._poll.start()
        self.changed.emit()

    def _check_token(self) -> None:
        if self.sk or not self._token or time.time() > self._token_until:
            if not self.sk and self._token:
                self.note = "sign-in timed out"
            self._token = ""
            self._poll.stop()
            self.changed.emit()
            return
        if self._asking:
            return
        self._asking = True
        tok = self._token

        def job() -> None:
            try:
                got = self._call("auth.getSession", {"token": tok}).get("session") or {}
            except Failed as exc:
                if exc.code not in (NOT_YET, 0):
                    self._token = ""
                    self.note = f"sign-in failed: {exc}"
                return
            finally:
                self._asking = False
            if got.get("key"):
                self.user, self.sk, self._token = str(got.get("name") or ""), str(got["key"]), ""
                self._save_session()
                self.note = ""
                self.say.emit(f"Scrobbling to Last.fm as {self.user}")
        self._run(job)

    def sign_out(self) -> None:
        self.user = self.sk = self._token = ""
        with self._lock:
            self.waiting = []
        if self.live:
            self._save_session()
            self._save_queue()
        self.note = ""
        self.changed.emit()

    def forget(self) -> None:
        """lastfm.json went (Forget credentials): drop the session held in memory too."""
        self.user = self.sk = ""
        self.changed.emit()

    # ------------------------------------------------------------ playing
    def observe(self, cur: dict | None, meta: dict, playing: bool,
                on: bool, spotify_too: bool) -> None:
        """Called on every poll with the tracker's play in progress."""
        if not self.sk or not self.live:
            return
        self._flush_due()
        if not cur or not on or not cur.get("title"):
            return
        key = (cur.get("t"), cur.get("title"))
        if key != self._play:
            self._play, self._np, self._done = key, False, False
        if not spotify_too and "spotify" in (cur.get("player") or "").lower():
            return
        heard = cur.get("s", 0.0)
        length = cur.get("len") or 0
        if length and length <= SHORTEST:
            return
        if not self._np and playing and heard >= NP_AFTER:
            self._np = True
            t = track_of(cur, meta)
            self._run(lambda: self._send_np(t))
        if not self._done and heard >= (min(SCROBBLE_MAX, length / 2) if length else SCROBBLE_MAX):
            self._done = True
            row = {**track_of(cur, meta), "timestamp": int(cur.get("t") or time.time())}
            if cur.get("auto"):
                row["chosenByUser"] = 0
            with self._lock:
                self.waiting.append(row)
            self._save_queue()
            self._retry_at = 0.0
            self._flush_due()

    def _send_np(self, t: dict) -> None:
        try:
            self._call("track.updateNowPlaying", {**t, "sk": self.sk}, post=True)
        except Failed as exc:
            self._failed(exc)

    def _flush_due(self) -> None:
        if self._sending or not self.waiting or time.time() < self._retry_at:
            return
        self._sending = True
        self._run(self._send_waiting)

    def _send_waiting(self) -> None:
        try:
            with self._lock:
                cut = time.time() - TOO_OLD
                self.waiting = [s for s in self.waiting if s.get("timestamp", 0) > cut]
                batch = self.waiting[:BATCH]
            if not batch or not self.sk:
                return
            p = {"sk": self.sk}
            for i, s in enumerate(batch):
                p.update({f"{k}[{i}]": v for k, v in s.items()})
            try:
                self._call("track.scrobble", p, post=True)
            except Failed as exc:
                if exc.code == 0 or exc.code in TRANSIENT:
                    self._retry_at = time.time() + BACK_OFF[min(self._tries, len(BACK_OFF) - 1)]
                    self._tries += 1
                    self.note = f"{len(self.waiting)} waiting: {exc or 'no answer'}"
                    return
                self._failed(exc)
                if self.sk:             # refused for good: these never go
                    with self._lock:
                        del self.waiting[:len(batch)]
                    self._save_queue()
                return
            with self._lock:
                del self.waiting[:len(batch)]
            self._tries, self._retry_at, self.note = 0, 0.0, ""
            self._save_queue()
        finally:
            self._sending = False

    def _failed(self, exc: Failed) -> None:
        if exc.code == BAD_SESSION:
            self.user = self.sk = ""
            self._save_session()
            self.note = "Last.fm signed you out; sign in again"
            self.say.emit("Last.fm signed you out: sign in again in Settings ▸ Last.fm")
        elif exc.code:
            self.note = f"Last.fm: {exc}"

    # --------------------------------------------------------------- menu
    def said(self) -> str:
        if self.sk:
            n = len(self.waiting)
            return f"{self.user or 'signed in'}" + (f" · {n} waiting" if n else "") + \
                (f" · {self.note}" if self.note and not n else "")
        if self._token:
            return "allow Mild Lyrics in the page that opened"
        return self.note or "not signed in"

    def look(self) -> tuple[str, bool]:
        """(verb on the button, dimmed)."""
        if self.sk:
            return "Sign out", False
        if self._token:
            return "Open again", False
        return "Sign in…", not self.live
