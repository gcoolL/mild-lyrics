"""What the words are being timed against: a file on disk, or Spotify.

Both ends answer the same four questions -- where are you, how long are you,
are you playing, and go here -- so the timing tab never asks which it has.
The differences are real but small, and each is dealt with here:

  * a local file can be played at half speed, which is the single most useful
    thing there is for placing syllables by hand; Spotify cannot;
  * a local file's clock is this process's own, so it is exact. Spotify's is
    read over MPRIS or the debug port a few times a second and interpolated
    in between, which is what the player does too;
  * the times written for Spotify are LYRIC times, which is the player's
    clock minus whatever offset it applies to this track. Getting that wrong
    puts every syllable in the file a fifth of a second out and makes the
    editor and the player disagree about a document they are both showing.
"""
from __future__ import annotations

import pathlib
import sys
import time

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "aligner", _HERE.parent)
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
        self.out.setVolume(0.9)
        self.path = ""
        self._pos = 0.0
        self._at = time.monotonic()
        self._rate = 1.0
        self._trim = 0.0
        self.mp.positionChanged.connect(self._moved)
        self.mp.playbackStateChanged.connect(lambda *_: self._moved(
            self.mp.position()))
        self.mp.durationChanged.connect(lambda *_: self.changed.emit())
        self.mp.errorOccurred.connect(lambda *_: self.changed.emit())

    def open(self, path: str) -> bool:
        p = pathlib.Path(path).expanduser()
        if not p.exists():
            return False
        self.path = str(p)
        self.mp.setSource(QUrl.fromLocalFile(self.path))
        self._pos, self._at, self._trim = 0.0, time.monotonic(), 0.0
        self.changed.emit()
        return True

    SNAP = 0.25
    TAU = 1.5
    TRIM = 0.03

    def _moved(self, ms: int) -> None:
        """Take the backend's word for it, but never in one step.

        The clock read here does not tick with the wall: it comes in every
        100ms or so, having advanced about 93, and then makes the difference
        up in one 44ms lurch. Snapping to each report -- which is what
        re-anchoring on it does -- hands that sawtooth straight to whoever
        taps a syllable, and the two halves of a word come out 45ms apart in
        the wrong order. So the reports steer the clock instead of setting
        it: the anchor is moved to where this clock already says it is, and
        the error is worked off by running a few per cent fast or slow until
        it is gone. Only a real discontinuity -- a seek, a stall, a track
        change -- is large enough to be worth a jump.
        """
        got = max(0.0, ms / 1000.0)
        now = time.monotonic()
        if not self.playing():
            self._pos, self._at, self._trim = got, now, 0.0
            return
        here = self._reading(now)
        err = got - here
        if abs(err) > self.SNAP:
            self._pos, self._at, self._trim = got, now, 0.0
            return
        self._pos, self._at = here, now
        self._trim = max(-self.TRIM, min(self.TRIM, err / self.TAU))

    def _reading(self, now: float) -> float:
        return self._pos + (now - self._at) * self._rate * (1.0 + self._trim)

    def position(self) -> float:
        if not self.playing():
            return self._pos
        return min(self.duration() or 1e9, self._reading(time.monotonic()))

    def duration(self) -> float:
        return max(0.0, self.mp.duration() / 1000.0)

    def playing(self) -> bool:
        from PyQt6.QtMultimedia import QMediaPlayer
        return self.mp.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def seek(self, sec: float) -> None:
        sec = max(0.0, float(sec))
        self.mp.setPosition(int(sec * 1000))
        self._pos, self._at, self._trim = sec, time.monotonic(), 0.0

    def toggle(self) -> None:
        if self.playing():
            self.mp.pause()
        else:
            self.mp.play()
        self.changed.emit()

    def set_rate(self, rate: float) -> None:
        self._pos, self._at, self._trim = self.position(), time.monotonic(), 0.0
        self._rate = max(0.1, float(rate))
        self.mp.setPlaybackRate(self._rate)

    def rate(self) -> float:
        return self._rate

    def title(self) -> str:
        return pathlib.Path(self.path).stem if self.path else ""

    def audio_path(self) -> str:
        return self.path


# --------------------------------------------------------------------------
class SpotifyPlayer(Player):
    """Whatever Spotify is playing, over the same transports the player uses.

    The clock is Mild Lyrics' own, so pausing, seeking and the interpolation
    between polls all behave exactly as they do there. The offset is the
    GLOBAL one and only that -- taken from the running player when one is on
    the other end of the live link, and read off the same settings file when
    there is not, which comes to the same number either way.

    Not the per-track correction, and not the measured one. Both of those
    describe how far the song's OWN lyric sits out of true; the document
    being written here is a different document, and its times are whatever
    they are being set to. Adding a correction meant for another file shifts
    the clock a syllable is stamped against, so a syllable placed dead on is
    written wrong by exactly the offset -- and the writer, seeing it late,
    corrects for a shift that then really is in the file.
    """

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
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll)
        self.poll_timer.start(250)
        self._poll()

    def _poll(self) -> None:
        try:
            self.clock.poll(pin_pause=False)
        except Exception:
            return
        now = (self.clock.tid, self.clock.status,
               round(self.clock.meta.get("length", 0.0), 2))
        if now != self._last:
            self._last = now
            self.changed.emit()

    def offset(self) -> float:
        """The global offset, exactly -- see the class docstring for why only.

        `base` and not `offset`, because the player's `offset` is a SUM whose
        meaning changes underneath us: track_offset() drops the per-track
        correction as soon as a live document is on screen, and carries it
        before that. Reading it meant every syllable stamped before the first
        push carried the per-track correction and every one after it did not --
        a step in the middle of a session, in the middle of a song, which is
        the worst shape an offset error can have. `base` is the global and
        only the global, whatever else is happening.
        """
        got = (self.link.last_state if self.link else {}) or {}
        if got.get("tid") and got.get("tid") == self.clock.tid and "base" in got:
            return float(got["base"])
        try:
            return float(self.settings.get("offset", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    LINK_STALE = 1.2
    CARRY = 0.4
    ASSUME = 1.5

    def position(self) -> float:
        """Where the SOUND is, in lyric time.

        Taken from the running player when one is on the other end of the
        link, and only from this process's own clock when there is not.

        Two programs polling MPRIS independently do NOT agree: each
        interpolates between its own polls, each applies its own smoothing,
        and the pair drift tens of milliseconds apart -- which is exactly the
        size of the disagreement between a time stamped here and where the
        player then draws it. Reading the position off the player itself
        removes the second clock entirely, offset and all.
        """
        now = time.monotonic()
        got = (self.link.last_state if self.link else {}) or {}
        fresh = self.link is not None and (
            now - self.link.last_at) < self.LINK_STALE
        live = fresh and got.get("tid") and got.get("tid") == self.clock.tid
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
                    and got.get("tid") and got.get("tid") == self.clock.tid)

    def duration(self) -> float:
        return float(self.clock.meta.get("length", 0.0) or 0.0)

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
        self.clock.seek(sec + self.offset())
        self._assume(sec, was)
        if self.link is not None:
            self.link.ask_state()

    def toggle(self) -> None:
        at = self.position()
        going = not self.playing()
        self.clock.command("PlayPause")
        self._assume(at, going)
        if self.link is not None:
            self.link.ask_state()

    def title(self) -> str:
        return str(self.clock.meta.get("title") or "")

    def artist(self) -> str:
        return str(self.clock.meta.get("artist") or "")

    def track_id(self) -> str:
        return self.clock.tid or ""

    def audio_path(self) -> str:
        """The copy the aligner keeps for this track, if it has fetched one.

        Auto-timing needs a waveform, and Spotify will not give one out. The
        project already downloads a copy to align against and keeps it in
        `fetched/`, so if this song has been aligned before, the audio is
        already here.
        """
        tid = self.track_id()
        if not tid:
            return ""
        try:
            import local_align as LA
            got = LA._kept(tid)
        except Exception:
            got = None
        return str(got) if got else ""
