"""The visualiser's analysis, heard live, for songs Spotify has not analysed:
our own player's decoded audio, or another player's off the mixer. Notes:
docs/notes/mild-lyrics/live_audio.md."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import warnings

from PyQt6.QtCore import QObject, pyqtSignal

import audio_analysis as AA
import frame_clock as FCK
from audio_analysis import HOP, SR, Analyser, usable

PV_BYTES = 24                   # sizeof(PROPVARIANT) on 64-bit Windows; soundcard declares 16

mono = FCK.mono     # stamps rows the window reads on its own clock


# Bus names whose sound the mixer files under another name.
ALIASES = {"chromium": ("chrome", "chromium"), "brave": ("brave",),
           "vivaldi": ("vivaldi",), "edge": ("edge", "msedge")}


def mixer_stream(app: str) -> int | None:
    """The sink-input index of `app`'s sound, playing ones first; else the one
    stream playing at all (a browser seen through plasma-browser-integration
    is not named for it), else None."""
    try:
        got = subprocess.run(("pactl", "-f", "json", "list", "sink-inputs"),
                             capture_output=True, text=True, timeout=2.0)
        rows = json.loads(got.stdout or "[]") if got.returncode == 0 else []
    except Exception:                                       # noqa: BLE001
        return None
    names = ALIASES.get(app, (app,)) if app else ()
    hits, playing = [], []
    for row in rows if isinstance(rows, list) else []:
        props = (row or {}).get("properties") or {}
        if (str(props.get("application.process.id")) == str(os.getpid())
                or props.get("node.name") == "Mild Lyrics"):   # Qt's stream has no pid on it
            continue
        who = " ".join(str(props.get(k) or "") for k in
                       ("application.name", "application.process.binary")).lower()
        corked = bool(row.get("corked"))
        if any(n in who for n in names):
            hits.append((corked, row.get("index")))
        if not corked:
            playing.append(row.get("index"))
    hits.sort(key=lambda h: h[0])
    if hits:
        return hits[0][1]
    return playing[0] if len(playing) == 1 else None


def soundcard():
    """soundcard, with its PROPVARIANT allocated at Windows' size and zeroed. Its own 16 bytes
    let GetValue write 8 past the end on every device name: the heap corruption (2026-10-25)."""
    import soundcard as sc
    mf = sys.modules.get("soundcard.mediafoundation")
    pv = getattr(mf, "_PropVariant", None)
    if pv is None or getattr(pv, "mild_sized", False):
        return sc

    def init(self) -> None:
        p = mf._ole32.CoTaskMemAlloc(PV_BYTES)
        if p == mf._ffi.NULL:
            raise MemoryError("CoTaskMemAlloc")
        mf._ffi.memmove(p, bytes(PV_BYTES), PV_BYTES)
        self.ptr = mf._ffi.cast("PROPVARIANT *", p)

    def gone(self) -> None:
        mf._ole32.PropVariantClear(self.ptr)
        mf._ole32.CoTaskMemFree(self.ptr)       # soundcard's own never freed it
    pv.__init__, pv.__del__, pv.mild_sized = init, gone, True
    warn = getattr(mf, "SoundcardRuntimeWarning", None)
    if warn is not None:            # "data discontinuity" whenever a hop runs late: stderr noise
        warnings.filterwarnings("ignore", category=warn)
    return sc


class _ScHome:
    """The one thread soundcard runs on. Its import puts that thread in COM's MTA; a tap
    made on any later thread failed CO_E_NOTINITIALIZED (measured on Windows, 2026-10-25)."""

    def __init__(self) -> None:
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def run(self, job, stop: threading.Event) -> None:
        """job(stop) on the home thread, after any job before it; returns once it has ended."""
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="soundcard", daemon=True)
                self._thread.start()
        done = threading.Event()
        self._jobs.put((job, stop, done))
        done.wait()

    def _loop(self) -> None:
        try:
            soundcard()                 # first, on a thread with no COM yet: S_FALSE fails its import
        except Exception:                                   # noqa: BLE001
            pass                        # the job says why
        while True:
            job, stop, done = self._jobs.get()
            try:
                if not stop.is_set():
                    job(stop)
            except Exception:                               # noqa: BLE001
                pass
            finally:
                done.set()


SC_HOME = _ScHome()


class Live(QObject):
    """Runs at most one tap: our own player's decoder, or the mixer for `app`.

    `heard(domain, rows, tempo)`: domain "pos" stamps rows with the media
    position, "mono" with mono()."""

    heard = pyqtSignal(str, object, float)
    analysed = pyqtSignal(str, object)      # (source, Beat.load's dict or {})

    def __init__(self) -> None:
        super().__init__()
        self.what: tuple = (None, "")
        self.why = ""                   # why nothing is heard, when that is known
        self._stop: threading.Event | None = None
        self._buf_out = None
        self._player = None
        self._q: queue.Queue | None = None
        self._said = set()

    def want(self, what: str | None, app: str = "", player=None) -> None:
        """"mine" (with the QMediaPlayer), "mixer" (with the app's name), or None."""
        key = (what, app if what == "mixer" else "")
        if key == self.what and (what != "mine" or player is self._player):
            return
        self.stop()
        self.what = key
        if what is None:
            return
        self.why = usable()
        if self.why:
            return
        if what == "mine":
            self._tap_player(player)
        elif what == "mixer":
            self._stop = threading.Event()
            threading.Thread(target=self._mixer, args=(app, self._stop),
                             name="live-audio", daemon=True).start()

    def whole(self, src: str) -> None:
        """Analyse the whole song at `src` (a file or a stream URL) on a thread;
        ffmpeg decodes it in its own process, the numpy lets the GIL go."""
        if usable():
            return
        def job() -> None:
            try:
                got = AA.song(src)
            except Exception as e:                          # noqa: BLE001
                self._log(f"whole song: {e!r}")
                got = {}
            self.analysed.emit(src, got)
        threading.Thread(target=job, name="song-analysis", daemon=True).start()

    def stop(self) -> None:
        self.what = (None, "")
        if self._stop is not None:
            self._stop.set()
            proc = getattr(self._stop, "proc", None)   # a paused stream blocks its read
            if proc is not None:
                try:
                    proc.kill()
                except Exception:                           # noqa: BLE001
                    pass
            self._stop = None
        if self._player is not None:
            try:
                self._player.setAudioBufferOutput(None)
                self._buf_out.deleteLater()     # while the player is still there
            except Exception:                               # noqa: BLE001
                pass
        if self._q is not None:
            self._q.put(None)
            self._q = None
        self._player = self._buf_out = None

    def _log(self, msg: str) -> None:
        if msg not in self._said:
            self._said.add(msg)
            print(f"[live audio] {msg}", file=sys.stderr)

    # ------------------------------------------------------- our own player
    def _tap_player(self, player) -> None:
        try:
            from PyQt6.QtMultimedia import QAudioBufferOutput, QAudioFormat
        except Exception:                                   # noqa: BLE001
            self.why = "this Qt has no QAudioBufferOutput"
            return
        if player is None:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(SR)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        # The player's child: its destructor reaches back into the player.
        out = QAudioBufferOutput(fmt, player)
        q: queue.Queue = queue.Queue(maxsize=256)
        out.audioBufferReceived.connect(lambda b, q=q: self._buffer(b, q))
        player.setAudioBufferOutput(out)
        self._player, self._buf_out, self._q = player, out, q
        threading.Thread(target=self._analyse, args=(q,), name="live-audio",
                         daemon=True).start()

    def _buffer(self, buf, q: queue.Queue) -> None:
        """GUI thread: copy the samples out and hand them to the analyser."""
        try:
            fmt = buf.format()
            raw = bytes(buf.constData().asstring(buf.byteCount()))
            item = (raw, fmt.sampleFormat(), fmt.channelCount(), fmt.sampleRate(),
                    buf.startTime() / 1e6)
            q.put_nowait(item)
        except queue.Full:
            pass
        except Exception as e:                              # noqa: BLE001
            self._log(f"buffer: {e!r}")

    def _analyse(self, q: queue.Queue) -> None:
        import numpy as np
        from PyQt6.QtMultimedia import QAudioFormat
        F = QAudioFormat.SampleFormat
        kinds = {F.Float: (np.float32, 1.0), F.Int16: (np.int16, 32768.0),
                 F.Int32: (np.int32, 2147483648.0), F.UInt8: (np.uint8, 128.0)}
        an, at = None, None
        while True:
            item = q.get()
            if item is None:
                return
            raw, kind, ch, sr, start = item
            dt, scale = kinds.get(kind, (None, 0))
            if dt is None or not sr or not ch:
                continue
            x = np.frombuffer(raw, dt).astype(np.float32)
            if kind == F.UInt8:
                x -= 128.0
            x = x[: len(x) - len(x) % ch].reshape(-1, ch).mean(axis=1) / scale
            k = max(1, round(sr / SR))
            if k > 1:
                x = x[: len(x) - len(x) % k].reshape(-1, k).mean(axis=1)
            rate = sr / k
            end = start + len(x) / rate
            if an is None or an.sr != rate or at is None or abs(start - at) > 0.25:
                an = Analyser(int(rate))          # first, or sought: a fresh start
            at = end
            rows = an.feed(x, end)
            if rows:
                self.heard.emit("pos", rows, an.tempo)

    # ------------------------------------------------------------ the mixer
    def _mixer(self, app: str, stop: threading.Event) -> None:
        if os.name == "nt":
            self._loopback(stop)
            return
        if not sys.platform.startswith("linux"):
            self.why = "not on this system"
            return
        if not shutil.which("parec"):
            self.why = "needs parec (PulseAudio or pipewire-pulse)"
            return
        while not stop.is_set():
            idx = mixer_stream(app)
            if idx is None:
                stop.wait(1.0)
                continue
            try:
                proc = subprocess.Popen(
                    ["parec", f"--monitor-stream={idx}", "--raw", "--format=float32le",
                     f"--rate={SR}", "--channels=1", "--latency-msec=30",
                     "--client-name=Mild Lyrics", "--stream-name=Visualiser"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except Exception as e:                          # noqa: BLE001
                self._log(f"parec: {e!r}")
                stop.wait(5.0)
                continue
            stop.proc = proc
            if not stop.is_set():
                self._read(proc, stop)
            try:
                proc.kill()
                proc.wait(1.0)
            except Exception:                               # noqa: BLE001
                pass
            stop.wait(0.3)

    def _read(self, proc, stop: threading.Event) -> None:
        import numpy as np
        an = Analyser()
        want = HOP * 4
        while not stop.is_set():
            data = proc.stdout.read(want)
            if not data:
                return
            t = mono()
            x = np.frombuffer(data[: len(data) - len(data) % 4], np.float32)
            rows = an.feed(x, t)
            if rows and not stop.is_set():
                self.heard.emit("mono", rows, an.tempo)

    def _loopback(self, stop: threading.Event) -> None:
        """_loopback_held on soundcard's one thread (SC_HOME), until it ends."""
        SC_HOME.run(self._loopback_held, stop)

    def _loopback_held(self, stop: threading.Event) -> None:
        """Windows: everything the default output plays (soundcard)."""
        try:
            import numpy as np
            sc = soundcard()
            mic = sc.get_microphone(sc.default_speaker().id, include_loopback=True)
        except Exception as e:                              # noqa: BLE001
            self.why = "needs the soundcard package"
            self._log(f"loopback: {e!r}")
            return
        an = Analyser()
        try:
            with mic.recorder(samplerate=SR, channels=1, blocksize=HOP) as rec:
                while not stop.is_set():
                    x = np.asarray(rec.record(numframes=HOP), np.float32)
                    t = mono()
                    rows = an.feed(x.reshape(-1), t)
                    if rows and not stop.is_set():
                        self.heard.emit("mono", rows, an.tempo)
        except Exception as e:                              # noqa: BLE001
            self.why = "the output could not be recorded"
            self._log(f"loopback: {e!r}")
