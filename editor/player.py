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

import queue
import threading

from PyQt6.QtCore import QObject, QThread, QTimer, QUrl, pyqtSignal

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

    # How loud the song is, 0..1, on the perceived scale rather than the
    # amplitude one -- the number a slider is holding. Both ends have a
    # volume, so unlike the rate this is not a local-only thing, and it is
    # asked of the player rather than kept in the window because Spotify's
    # is the system's and can be moved from outside this program.
    def volume(self) -> float:
        return 1.0

    def set_volume(self, v: float) -> None:
        pass

    def can_volume(self) -> bool:
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
        self.path = ""
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
        self.path = str(p)
        self.mp.setSource(QUrl.fromLocalFile(self.path))
        self._restart(0.0)
        self.changed.emit()
        return True

    # -------------------------------------------------------------- the clock
    # `where we put it, plus how long ago`. That is the whole of it.
    #
    # A local file has no second party. Nothing moves this song except this
    # window: it starts where we opened it, it goes where we seek it, and in
    # between it advances at the rate we asked for. So the clock is a
    # straight line from an anchor this window sets -- on open, on a seek, on
    # a resume, on a rate change -- and between those it is not touched by
    # anything at all. That is the one thing a clock people tap syllables
    # against has to be, and everything below is about NOT doing things to it.
    #
    # It used to be steered. The backend's reports do not tick with the wall
    # -- they arrive every 100ms or so carrying a position that has advanced
    # about 93, and then make the difference up in one 44ms lurch -- and the
    # clock chased them, re-anchoring on each one and working the error off
    # by running up to three per cent fast or slow. Three per cent is 30ms in
    # a second, so the same syllable tapped at the same moment of the same
    # song was stamped differently depending on where in the correction the
    # tap fell, and every resume started a fresh correction from a fresh
    # error.
    #
    # Then it WAITED for them, which was worse to use: half a second of
    # frozen playhead on every seek and every resume, bought in exchange for
    # measuring something a local file cannot get wrong.
    #
    # And then it disciplined its own rate against them -- the sound card
    # counts in its own crystal, this process counts in the system's, and the
    # two are tens of parts per million apart. That one at least was arguable,
    # and it was still wrong: fitted over a minute of reports the slope came
    # out about 30ppm noisy, which is the same size as the drift it was there
    # to remove, so on a card that was already perfect it pulled the rate
    # 30ppm off and swung the clock 34ms across six minutes. A correction no
    # better than its own error is not a correction. What is left of that
    # drift is tens of milliseconds over many unbroken minutes, and it starts
    # again from nothing at every seek and every pause -- which, timing a
    # song by hand, is constantly.
    #
    # So the reports are read for exactly one thing: a position further out
    # than JUMP, which is not wobble. The file has ended, the pipeline has
    # stalled, or the song has moved in a way this window did not ask for --
    # and the anchor is set again there. For GRACE after a move of our own
    # they are not consulted even for that, because the pipeline goes on
    # reporting where it WAS for a moment after a seek. Nothing waits on
    # GRACE; the clock is already running, from the position we just set.
    #
    # What is left is a constant: the sound of a given moment leaves the
    # speakers a little after the clock says so, by however long the device
    # takes to fill. It is the same on every seek and every resume because it
    # is a property of the device -- and a constant offset is exactly what
    # the tap lag box takes out.
    JUMP = 0.25         # further out than this and the song has been moved
    GRACE = 0.5         # after a move of ours, before the reports are believed

    def _restart(self, pos: float) -> None:
        """Set the clock. Only a move of ours calls this."""
        self._pos = max(0.0, float(pos))
        self._at = self._set_at = time.monotonic()

    def _moved(self, ms: int) -> None:
        got = max(0.0, ms / 1000.0)
        now = time.monotonic()
        if not self.playing():
            # Paused. The backend's own position is the honest answer, and
            # it is where it will resume from -- so it is what the resume
            # anchors on. Taking anything else would have the clock and the
            # sound disagree from the first instant of the next stretch.
            self._pos, self._at = got, now
            return
        if now - self._set_at < self.GRACE:
            return
        if abs(got - self._reading(now)) > self.JUMP:
            self._restart(got)

    def _reading(self, now: float) -> float:
        return self._pos + (now - self._at) * self._rate

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
        self._restart(sec)

    def toggle(self) -> None:
        if self.playing():
            self.mp.pause()
        else:
            # From wherever it was paused, which is where the backend will
            # resume from -- and running from this instant, not from
            # whenever the reports get round to confirming it.
            self._restart(self._pos)
            self.mp.play()
        self.changed.emit()

    def set_rate(self, rate: float) -> None:
        here = self.position()
        self._rate = max(0.1, float(rate))
        self.mp.setPlaybackRate(self._rate)
        self._restart(here)

    def rate(self) -> float:
        return self._rate

    def _apply_volume(self) -> None:
        """Qt's output takes an AMPLITUDE; a slider is a loudness.

        Setting the amplitude straight from the slider makes the top third
        of the travel do almost nothing and the bottom third do everything,
        which is why halving a slider that behaves that way barely helps
        anybody whose ears are being taken off. Qt has the conversion --
        the same one its own volume widgets use.
        """
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

    def title(self) -> str:
        return pathlib.Path(self.path).stem if self.path else ""

    def audio_path(self) -> str:
        return self.path


# --------------------------------------------------------------------------
class _Pump(QThread):
    """The one thread allowed to wait for Spotify.

    Every question put to the player is a round-trip -- a D-Bus call over the
    session bus, or a CDP evaluate down the debug port -- and the socket is
    given fifteen seconds to answer. Spotify does not always answer promptly:
    around a resume or a seek its renderer is busy, and a reply that normally
    takes a millisecond can take most of a second. Asked from the GUI thread
    four times a second, that is a window which stops drawing and stops taking
    keys in exactly the moment somebody is tapping syllables into it -- and a
    tap that lands late is a syllable placed late.

    So the waiting happens here. The reading is arithmetic, done under the
    clock's lock; the window reads a position between readings and never
    blocks. Commands go the same way: a seek is BELIEVED immediately (see
    `_assume`) and sent from here, so the transport being slow to take it
    costs the display nothing.
    """

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
        """Everything asked for since the last pass, with the dead dropped.

        A VOLUME that another volume follows was out of date before it was
        sent, and sending it anyway costs a whole round trip to the player.
        That is what made a wheel over the volume lag: forty notches queue
        forty messages, this drained them one at a time, and the sound went
        on climbing for as long as the round trips took -- a fifth of a
        second over D-Bus and two seconds over the debug port -- after the
        hand had stopped. Only the last one was ever going to be audible.

        Volume only. A seek is a place somebody asked to hear and passing
        over one changes what they heard; a command is an act. Volume is the
        one thing here that is a LEVEL, where the last word is the whole
        answer and the ones before it are not even played.
        """
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
                # `spotify_dom.connect` calls sys.exit when the debug port has
                # gone -- a SystemExit, which is not an Exception and which,
                # raised on the GUI thread, used to take the editor and its
                # unsaved lyric with it. It stops here.
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
        self.pump = _Pump(self.clock)
        self.pump.read.connect(self._poll)
        self.pump.start()

    def _poll(self) -> None:
        now = (self.clock.tid, self.clock.status,
               round(self.clock.meta.get("length", 0.0), 2))
        if now != self._last:
            self._last = now
            self.changed.emit()

    def close(self) -> None:
        self.pump.stop()

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
    # As far as a reading is carried forward before this stops believing it.
    # It has to be the whole of the window in which the reading is used at
    # all: shorter, and every gap between two words from the player leaves a
    # stretch where the position is pinned at last + CARRY and the clock
    # simply stops -- the song runs on, the number does not, and everything
    # tapped inside it is stamped at the same time. The player says something
    # twice a second and the moment anything jumps (see SAY_EVERY there), so
    # a reading this old means the link is gone, and gone is what LINK_STALE
    # already decides.
    CARRY = LINK_STALE
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
        self._assume(sec, was)
        self.pump.tell("seek", sec + self.offset())
        if self.link is not None:
            self.link.ask_state()

    def toggle(self) -> None:
        at = self.position()
        going = not self.playing()
        self._assume(at, going)
        self.pump.tell("command", "PlayPause")
        if self.link is not None:
            self.link.ask_state()

    def volume(self) -> float:
        """Spotify's own, as the pump last read it.

        Read rather than remembered: this is the player's volume, and the
        person timing against it can move it in Spotify or with a media key
        while this window is open. `wants_volume` already stops a reading
        taken during our own set from arguing with it.
        """
        got = self.clock.volume
        return 1.0 if got is None else max(0.0, min(1.0, float(got)))

    def set_volume(self, v: float) -> None:
        v = max(0.0, min(1.0, float(v)))
        # Believed here and sent from the pump, the way a seek is: the
        # slider must not spring back to the last reading in the quarter
        # second before the player answers. `wants_volume` reads this same
        # stamp, and is what stops a reading taken inside that window from
        # arguing with what has just been asked for.
        with self.clock.lock:
            self.clock.volume, self.clock._vol_set_at = v, time.monotonic()
        self.pump.tell("volume", v)

    def can_volume(self) -> bool:
        return True

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
