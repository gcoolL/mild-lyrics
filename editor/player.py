"""What the words are timed against, a local file or Spotify, behind one
interface. Times written for Spotify are lyric times (clock minus offset)."""
from __future__ import annotations

import math
import pathlib
import sys
import os
import time

import queue
import threading

# The clock a local file is carried on: perf_counter (monotonic steps 15.6ms on
# older Windows CPython), the same clock as the player's mono().
_now = time.perf_counter

from PyQt6.QtCore import QObject, QThread, QTimer, QUrl, pyqtSignal

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "mild-lyrics", _HERE.parent)
                if str(p) not in sys.path]


class Player(QObject):
    """The shape both ends share. Times are always seconds, always lyric time."""

    changed = pyqtSignal()

    kind = "none"

    def position(self) -> float:
        return 0.0

    def duration(self) -> float:
        return 0.0

    def playing(self) -> bool:
        return False

    def seek(self, sec: float) -> None:
        pass

    def toggle(self) -> None:
        pass

    def set_rate(self, rate: float) -> None:
        pass

    def rate(self) -> float:
        return 1.0

    def volume(self) -> float:
        return 1.0

    def set_volume(self, v: float) -> None:
        pass

    def can_volume(self) -> bool:
        return False

    def heard(self) -> str:
        return self.audio_path()

    def hear(self, path: str) -> bool:
        return False

    def can_hear(self) -> bool:
        return False

    def title(self) -> str:
        return ""

    def artist(self) -> str:
        return ""

    def track_id(self) -> str:
        return ""

    def audio_path(self) -> str:
        """A file the aligner can read, when there is one."""
        return ""

    def nudge(self, delta: float) -> None:
        self.seek(max(0.0, self.position() + delta))


# --------------------------------------------------------------------------
class LocalPlayer(Player):
    """A file on disk, through Qt's own audio output."""

    kind = "local"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
        self.out = QAudioOutput(self)
        self.mp = QMediaPlayer(self)
        self.mp.setAudioOutput(self.out)
        self._vol = 0.9
        self._apply_volume()
        self.path = self._heard = ""
        self._resume_at, self._resume_going = None, False
        self._rate = 1.0
        self._restart(0.0)
        self.mp.positionChanged.connect(self._moved)
        self.mp.playbackStateChanged.connect(lambda *_: self._moved(
            self.mp.position()))
        self.mp.durationChanged.connect(lambda *_: self.changed.emit())
        self.mp.errorOccurred.connect(lambda *_: self.changed.emit())

    def open(self, path: str) -> bool:
        p = pathlib.Path(path).expanduser()
        if not p.exists():
            return False
        self.path = self._heard = str(p)
        self.mp.setSource(QUrl.fromLocalFile(self.path))
        self._restart(0.0)
        self.changed.emit()
        return True

    # ------------------------------------------------------ what is heard
    def heard(self) -> str:
        return getattr(self, "_heard", "") or self.path

    def hear(self, path: str) -> bool:
        """Play this rendering instead, from where we already are: swapped
        under GRACE, position and play state put back once the media is
        ready."""
        p = pathlib.Path(path).expanduser()
        if not p.exists():
            return False
        if str(p) == self.heard():
            return True
        was, going = self.position(), self.playing()
        self._heard = str(p)
        self._resume_at, self._resume_going = was, going
        self.mp.setSource(QUrl.fromLocalFile(self._heard))
        self.mp.setPlaybackRate(self._rate)
        self._restart(was)
        self._place()
        return True

    def _place(self) -> None:
        """Put the new source where the old one was, once it will take it."""
        from PyQt6.QtMultimedia import QMediaPlayer
        at, going = getattr(self, "_resume_at", None), getattr(
            self, "_resume_going", False)
        if at is None:
            return
        st = self.mp.mediaStatus()
        if st in (QMediaPlayer.MediaStatus.LoadingMedia,
                  QMediaPlayer.MediaStatus.NoMedia):
            QTimer.singleShot(20, self._place)
            return
        self._resume_at = None
        self._restart(at, wait=going)
        self.mp.setPosition(int(at * 1000))
        if going:
            self.mp.play()
        self.changed.emit()

    # -------------------------------------------------------------- the clock
    # Each Qt reading pulls our own clock toward it (time constant LOCK), and
    # after a seek or resume the clock waits for the file to move (WAIT).
    JUMP = 0.25
    GRACE = 0.5
    LOCK = 0.25
    WAIT = 0.3

    def _restart(self, pos: float, wait: bool = False) -> None:
        """Set the clock; only a move of ours calls this. `wait` holds at `pos`
        until the file is heard to move (or WAIT passes): for resumes and
        seeks while playing."""
        self._pos = max(0.0, float(pos))
        self._at = self._set_at = _now()
        self._waiting = self._at + self.WAIT if wait else None
        self._read_at = None

    def _moved(self, ms: int) -> None:
        got = max(0.0, ms / 1000.0)
        now = _now()
        if not self.playing():
            # Paused: Qt's word is the position, except in the moment after
            # our own seek, when it can still be reporting where it was.
            if now - self._set_at >= self.GRACE or abs(got - self._pos) < 0.05:
                self._pos, self._at = got, now
            self._waiting = None
            return
        if self._waiting is not None:
            # Held at _pos until the file moves off it. Readings from before
            # a seek (anywhere else) and the echo of the seek itself (exactly
            # _pos) are neither of them the sound starting.
            ahead = got - self._pos
            if 0.0005 < ahead <= (now - self._set_at) * self._rate + 0.15:
                self._pos, self._at = got, now
                self._waiting = None
                self._read_at = now
            return
        err = got - self._reading(now)
        if abs(err) > self.JUMP:
            if now - self._set_at < self.GRACE:
                return
            try:                                        # TEMPORARY follow log
                import lyrics_gui as L
                L.follow_log("editor", "file-clock-jump", reported=got,
                             reading=round(self._reading(now), 3))
            except Exception:                           # noqa: BLE001
                pass
            self._restart(got)
            return
        dt = (now - self._read_at) if self._read_at is not None else 0.05
        self._read_at = now
        self._pos += err * (1.0 - math.exp(-min(dt, 1.0) / self.LOCK))

    def _reading(self, now: float) -> float:
        return self._pos + (now - self._at) * self._rate

    def held(self) -> bool:
        """Playing, but holding still until the file is heard to move (a
        seek or a resume -- see WAIT)."""
        return (self.playing() and self._waiting is not None
                and _now() < self._waiting)

    def position(self) -> float:
        if not self.playing():
            return self._pos
        now = _now()
        if self._waiting is not None:
            if now < self._waiting:
                return self._pos
            # Nothing heard to move in WAIT: run from here and let the
            # readings pull it in.
            self._at, self._waiting = self._waiting, None
        return min(self.duration() or 1e9, self._reading(now))

    def duration(self) -> float:
        return max(0.0, self.mp.duration() / 1000.0)

    def playing(self) -> bool:
        from PyQt6.QtMultimedia import QMediaPlayer
        return self.mp.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def seek(self, sec: float) -> None:
        sec = max(0.0, float(sec))
        going = self.playing()
        # The clock first: Qt answers setPosition with a positionChanged of
        # its own before it returns, and that has to find the clock already
        # moved, or it reads as the file jumping away from it.
        self._restart(sec, wait=going)
        self.mp.setPosition(int(sec * 1000))

    def toggle(self) -> None:
        if self.playing():
            # Frozen where the clock says, before Qt reports its own reading
            # of the pause -- which is within a few milliseconds of it now.
            self._pos, self._at = self.position(), _now()
            self._waiting = None
            self.mp.pause()
        else:
            self._restart(self._pos, wait=True)
            self.mp.play()
        self.changed.emit()

    def set_rate(self, rate: float) -> None:
        here = self.position()
        self._rate = max(0.1, float(rate))
        self._pos, self._at = here, _now()
        self.mp.setPlaybackRate(self._rate)

    def rate(self) -> float:
        return self._rate

    def _apply_volume(self) -> None:
        """Set Qt's output amplitude from the slider's loudness, through Qt's
        own conversion."""
        from PyQt6.QtMultimedia import QAudio
        self.out.setVolume(QAudio.convertVolume(
            self._vol, QAudio.VolumeScale.LogarithmicVolumeScale,
            QAudio.VolumeScale.LinearVolumeScale))

    def volume(self) -> float:
        return self._vol

    def set_volume(self, v: float) -> None:
        self._vol = max(0.0, min(1.0, float(v)))
        self._apply_volume()

    def can_volume(self) -> bool:
        return True

    def can_hear(self) -> bool:
        return True

    def title(self) -> str:
        return pathlib.Path(self.path).stem if self.path else ""

    def audio_path(self) -> str:
        return self.path


# --------------------------------------------------------------------------
class _Pump(QThread):
    """The one thread allowed to wait for Spotify: polls and commands go
    through it, so the GUI thread never blocks; a seek is believed at once
    (`_assume`)."""

    read = pyqtSignal()

    EVERY = 0.25

    def __init__(self, clock, parent=None) -> None:
        super().__init__(parent)
        self.clock = clock
        self._say: queue.Queue = queue.Queue()
        self._wake = threading.Event()
        self._going = True

    def tell(self, what: str, arg=None) -> None:
        """Ask the player for something, from any thread. Never blocks."""
        self._say.put((what, arg))
        self._wake.set()

    def stop(self) -> None:
        self._going = False
        self._wake.set()
        self.wait(2000)

    def _due(self) -> list:
        """Everything asked for since the last pass, minus volumes another
        volume follows; seeks and commands are all kept."""
        got = []
        while True:
            try:
                got.append(self._say.get_nowait())
            except queue.Empty:
                break
        last = max((i for i, (what, _) in enumerate(got) if what == "volume"),
                   default=-1)
        return [m for i, m in enumerate(got) if m[0] != "volume" or i == last]

    def run(self) -> None:                                  # pragma: no cover
        while self._going:
            for what, arg in self._due():
                try:
                    if what == "seek":
                        self.clock.seek(float(arg))
                    elif what == "command":
                        self.clock.command(str(arg))
                    elif what == "volume":
                        self.clock.set_volume(float(arg))
                except Exception:               # noqa: BLE001
                    pass
                if not self._going:
                    return
            try:
                want_vol = self.clock.wants_volume()
                got = self.clock.io.read(want_vol)
            except Exception as e:              # noqa: BLE001
                self.clock._drop()
                self.clock.status = "Error"
                self.clock.last_error = str(e) or e.__class__.__name__
                got = None
            except BaseException:
                self.clock.status = "Error"
                got = None
            if got is not None:
                self.clock.apply(got, want_vol, pin_pause=False)
            if self._going:
                self.read.emit()
            self._wake.wait(self.EVERY)
            self._wake.clear()


# --------------------------------------------------------------------------
class SpotifyPlayer(Player):
    """Whatever Spotify is playing, on Mild Lyrics' own clock. Only the global
    offset applies: per-track corrections belong to another document."""

    kind = "spotify"

    def __init__(self, port: int = 9222, link=None, parent=None) -> None:
        super().__init__(parent)
        import lyrics_gui as L
        self._L = L
        self.link = link
        self.clock = L.Clock(L.make_transport(port))
        self.settings = L.load_settings()
        self._last = None
        self._assumed: tuple = (None, 0.0, False)
        self.pump = _Pump(self.clock)
        self.pump.read.connect(self._poll)
        self.pump.start()

    def _mild(self) -> dict:
        """The player's state while Mild Lyrics' OWN player is the one playing (fresh), else {}.
        That player is on no bus or service this clock can read: the link is the only way in."""
        got = (self.link.last_state if self.link else {}) or {}
        if self.link is not None and got.get("mine") and got.get("tid") \
                and time.monotonic() - self.link.last_at < self.LINK_STALE:
            return got
        return {}

    def _poll(self) -> None:
        now = (self.track_id(), self.clock.status if not self._mild() else self._mild().get("status"),
               round(self.duration(), 2))
        if now != self._last:
            self._last = now
            self.changed.emit()

    def close(self) -> None:
        self.pump.stop()

    def offset(self) -> float:
        """The global offset alone: the player's `base`, since its `offset` sum
        changes with what is on screen."""
        got = (self.link.last_state if self.link else {}) or {}
        if got.get("tid") and (got.get("tid") == self.clock.tid or self._mild()) and "base" in got:
            return float(got["base"])
        try:
            return float(self.settings.get("offset", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    LINK_STALE = 1.2
    CARRY = LINK_STALE
    ASSUME = 1.5

    def position(self) -> float:
        """Where the sound is, in lyric time: from the running player when
        linked, so there is one clock, else this process's own."""
        now = time.monotonic()
        got = (self.link.last_state if self.link else {}) or {}
        fresh = self.link is not None and (
            now - self.link.last_at) < self.LINK_STALE
        live = fresh and got.get("tid") and (got.get("tid") == self.clock.tid or got.get("mine"))
        where = None
        if live:
            where = float(got.get("pos", 0.0)) - self.offset()
            if str(got.get("status")) == "Playing":
                since = now - float(got.get("at", 0.0) or (now - 0.0))
                if not 0.0 <= since <= self.CARRY:
                    since = max(0.0, min(self.CARRY, now - self.link.last_at))
                where += since
        else:
            where = self.clock.position() - self.offset()
        mine = self._assumption(now, got)
        return max(0.0, mine if mine is not None else where)

    def _assume(self, pos: float, playing: bool) -> None:
        self._assumed = (float(pos), time.monotonic(), bool(playing))

    def _assumption(self, now: float, got: dict):
        """Where this window believes the song is, or None to trust the player.

        Dropped the moment the player samples AFTER the action -- by its own
        timestamp, not by comparing positions, because a seek that lands a
        little off is still a seek that happened.
        """
        pos, at, playing = self._assumed
        if pos is None:
            return None
        sampled = float(got.get("at", 0.0) or 0.0)
        settled = sampled > at + 0.02 and (
            (str(got.get("status")) == "Playing") == playing)
        if settled or now - at > self.ASSUME:
            self._assumed = (None, 0.0, False)
            return None
        return pos + (now - at if playing else 0.0)

    def following_player(self) -> bool:
        """Whether the clock above is the player's rather than ours."""
        got = (self.link.last_state if self.link else {}) or {}
        return bool(self.link is not None
                    and (time.monotonic() - self.link.last_at) < self.LINK_STALE
                    and got.get("tid") and (got.get("tid") == self.clock.tid or got.get("mine")))

    def duration(self) -> float:
        mild = self._mild()
        return float((mild.get("length") if mild else self.clock.meta.get("length", 0.0)) or 0.0)

    def playing(self) -> bool:
        """The PLAYER's answer where there is one -- the two disagree for a
        poll or two around a pause, and this is the flag that decides whether
        a position is carried forward."""
        if self._assumed[0] is not None:
            return bool(self._assumed[2])
        got = (self.link.last_state if self.link else {}) or {}
        if self.following_player() and got.get("status"):
            return str(got["status"]) == "Playing"
        return self.clock.status == "Playing"

    def seek(self, sec: float) -> None:
        sec = max(0.0, float(sec))
        was = self.playing()
        self._assume(sec, was)
        mild = self._mild()
        if mild:            # the window adds its track offset back: send its clock less that
            self.link.seek(sec + self.offset() - float(mild.get("offset", 0.0) or 0.0))
        else:
            self.pump.tell("seek", sec + self.offset())
        if self.link is not None:
            self.link.ask_state()

    def toggle(self) -> None:
        at = self.position()
        going = not self.playing()
        self._assume(at, going)
        if self._mild():
            self.link.control("PlayPause")
        else:
            self.pump.tell("command", "PlayPause")
        if self.link is not None:
            self.link.ask_state()

    def volume(self) -> float:
        """Spotify's own volume, as the pump last read it."""
        got = self.clock.volume
        state = (self.link.last_state if self.link else {}) or {}
        if (self.following_player() and state.get("volume") is not None
                and self.clock.wants_volume()):
            # The player's word where there is a player: it may be holding
            # Spotify muted under a take, and the level that counts is the
            # one it goes back to.
            got = state["volume"]
        return 1.0 if got is None else max(0.0, min(1.0, float(got)))

    def set_volume(self, v: float) -> None:
        """Spotify's volume, set through the running player where there is one
        (it owns the level), else straight to Spotify."""
        v = max(0.0, min(1.0, float(v)))
        with self.clock.lock:
            self.clock.volume, self.clock._vol_set_at = v, self._L.mono()
        if (self.link is not None and self.link.alive()
                and self.following_player() and self.link.volume(v)):
            return
        self.pump.tell("volume", v)

    def can_volume(self) -> bool:
        """Whether the way in to this player carries a volume at all: only the
        session bus and the debug port do. No slider otherwise."""
        return bool(getattr(self.clock.io, "HAS_VOLUME", False)) and not self._mild()

    def title(self) -> str:
        mild = self._mild()
        return str((mild.get("title") if mild else self.clock.meta.get("title")) or "")

    def artist(self) -> str:
        mild = self._mild()
        return str((mild.get("artist") if mild else self.clock.meta.get("artist")) or "")

    def track_id(self) -> str:
        return str(self._mild().get("tid") or self.clock.tid or "")

    def audio_path(self) -> str:
        """The copy the aligner keeps for this track in `fetched/`, if it has
        one."""
        own = str(self._mild().get("audio") or "")
        if own and "://" not in own and os.path.exists(own):
            return own                      # Mild Lyrics is playing a file: that very file
        tid = self.track_id()
        if not tid:
            return ""
        try:
            import local_align as LA
            got = LA._kept(tid)
        except Exception:
            got = None
        return str(got) if got else ""
