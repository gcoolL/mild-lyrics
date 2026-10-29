"""Voice chat over a session's own datagrams: a star around one hub (the
session's host), sealed under a key only the session holds, sent only while
someone speaks. Notes: docs/notes/mild-lyrics/voice.md."""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import hmac
import json
import math
import os
import re
import struct
import sys
import time
from collections import deque

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

MAGIC = b"\x00MLV"        # never a QUIC packet (fixed bit clear), a punch or STUN
RATE = 16000
FRAME = 320               # 20 ms at RATE
PACKET_MS = 100           # through the relay every packet is a counted message
PACKET_FRAMES = PACKET_MS * RATE // 1000 // FRAME
PACKET_BYTES = 1000       # audio in one datagram at most: under a UDP path's MTU
HANG = 15                 # frames still sent after the voice drops (300 ms)
PREROLL = 6               # frames from just before it rose (covers ONSET_FAR)
ONSET = 3                 # frames in a row loud enough before it counts as speech:
                          # a key click or a tap on the desk is one or two
START_FRAMES = 7          # a speaker waits for this much before playing (140 ms)
START_WAIT = 0.25         # ... or for this long after their first frame
MAX_FRAMES = 25           # more than this queued: cut back to START_FRAMES
TALK_HOLD = 0.35          # seconds someone shows as talking after their last frame
MAX_PEOPLE = 12           # the relay's own limit on a room
MAX_NAME = 32
HELLO_AGAIN = 5.0         # a member missing from the hub's roster says hello again
SENSES = {"low": 15.0, "normal": 10.0, "high": 6.0}   # dB over the noise floor
FLOOR_RISE = 0.01         # dB per frame the noise floor creeps up
QUIET_DB = -55.0          # never counted as speech under this
TARGET_DB = -18.0         # speech is lifted (or lowered) to about this level
GAIN_DB = (-6.0, 24.0)    # ... by no more than this
LEVEL_EASE = 0.05         # how fast the speech level follows, per speech frame
GAIN_STEP = 0.5           # dB the gain may move per frame
PEAK = 29000              # loudest sample sent, after the gain
# What is heard, whatever was sent and wherever the volume is: no frame louder
# than HEAR_RMS, no sample past HEAR_PEAK. Down at once, back up slowly.
HEAR_RMS = -14.0          # dBFS
HEAR_PEAK = 20000         # about -4 dBFS
HEAR_RISE = 0.3           # dB per frame the limiter lets go (15 dB/s)
# Noise removal (Denoiser): spectral subtraction over 40 ms windows.
DN_FLOOR = 0.1            # no band is cut by more than this (-20 dB)
DN_OVER = 2.5             # how much more than the noise is taken off
DN_RISE = 0.6             # how fast a band's gain may come back up, per frame
DN_SMOOTH = 0.2           # how fast a band's power is followed, per frame
DN_BLOCK = 25             # frames in one block of the noise's minimum (0.5 s)
DN_BLOCKS = 3             # blocks the minimum is taken over (1.5-2 s)
DN_BIAS = 5.0             # a minimum sits well under the noise's peaks: lifted back by this
CLICK_JUMP = 8.0          # a frame this many times the recent energy...
CLICK_FLAT = 0.45         # ...and this noise-like (spectral flatness) is a click
CLICK_CUT = 0.15          # ...and is let through at this
ONSET_FAR = 5             # ...and while the speakers play: the canceller's slips are shorter
# Echo: what this end plays is subtracted from what its microphone hears
# (EchoCanceller), and what is left of it is taken out with the noise.
AEC_PARTS = 16            # 20 ms blocks of echo path learnt: 320 ms of delay and room
AEC_MU = 1.0              # how fast it learns, while only the far end speaks
AEC_REG = 0.1             # each band's step is evened out by this share of the mean power
AEC_DT_MU = 0.03          # ...and while both speak (so the near voice is not learnt)
AEC_LEARNT = 4.0          # echo cut 6 dB: from then on, both speaking is looked for
AEC_TALK = 6.0            # the error this far over the residual it learnt to expect: both speak
AEC_OPEN = 16.0           # echo cut 12 dB: only then may a voice here speak over the far end
AEC_LOUD = 1e5            # mean square (about -40 dBFS): a frame quieter holds nothing to judge
AEC_STUCK = 100           # frames of "both" in a row (2 s): the room changed, learn anyway
FAR_QUIET = -60.0         # dBFS: a far end under this is silence, nothing to learn
ECHO_OVER = 3.0           # how much of the echo estimate is taken off again, as noise
ECHO_FLOOR = 0.03         # bands may go down to this for echo (-30 dB)
ECHO_GATE = 15.0          # dB under the echo that still counts as a voice here, while it plays
FAR_KEEP = 1.5            # seconds of what was played kept to cancel against

ULAW, OPUS = 1, 2
CODECS = {"ulaw": ULAW, "opus": OPUS}
NAME_OUT = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁦-⁩<>&]")


def clean_name(raw) -> str:
    """A name someone gave, safe for a label that reads markup."""
    return " ".join(NAME_OUT.sub("", str(raw or "")).split())[:MAX_NAME]


# ------------------------------------------------------------------ sealing
def _sub(key: bytes, what: bytes) -> bytes:
    return hashlib.blake2b(key=key, digest_size=32, person=b"ml-voice-" + what).digest()


def seal(key: bytes, kind: bytes, body: bytes) -> bytes:
    """MAGIC | kind | nonce | body under a BLAKE2b keystream | tag."""
    nonce = os.urandom(12)
    ct = _xor(body, _stream(_sub(key, b"enc"), nonce, len(body)))
    tag = hashlib.blake2b(MAGIC + kind + nonce + ct, key=_sub(key, b"mac"),
                          digest_size=16).digest()
    return MAGIC + kind + nonce + ct + tag


def unseal(key: bytes, data: bytes) -> tuple[bytes, bytes] | None:
    """(kind, body), or None for anything not sealed under `key`."""
    if len(data) < 4 + 1 + 12 + 16 or data[:4] != MAGIC:
        return None
    kind, nonce, ct, tag = data[4:5], data[5:17], data[17:-16], data[-16:]
    want = hashlib.blake2b(MAGIC + kind + nonce + ct, key=_sub(key, b"mac"),
                           digest_size=16).digest()
    if not hmac.compare_digest(tag, want):
        return None
    return kind, _xor(ct, _stream(_sub(key, b"enc"), nonce, len(ct)))


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    return b"".join(hashlib.blake2b(nonce + i.to_bytes(4, "big"), key=key).digest()
                    for i in range((n + 63) // 64))[:n]


def _xor(a: bytes, b: bytes) -> bytes:
    if not a:
        return b""
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")


# ------------------------------------------------------------------- codecs
_OPUS = None


def _opus():
    """libopus through ctypes, or None where it is not installed."""
    global _OPUS
    if _OPUS is not None:
        return _OPUS or None
    names = [ctypes.util.find_library("opus")]
    names += (["opus.dll", "libopus-0.dll"] if os.name == "nt"
              else ["libopus.so.0", "libopus.0.dylib", "/opt/homebrew/lib/libopus.dylib"])
    lib = None
    for name in filter(None, names):
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if lib is None:
        _OPUS = False
        return None
    try:
        P, I = ctypes.c_void_p, ctypes.c_int
        lib.opus_encoder_create.restype = P
        lib.opus_encoder_create.argtypes = [ctypes.c_int32, I, I, ctypes.POINTER(I)]
        lib.opus_decoder_create.restype = P
        lib.opus_decoder_create.argtypes = [ctypes.c_int32, I, ctypes.POINTER(I)]
        lib.opus_encode.restype = ctypes.c_int32
        lib.opus_encode.argtypes = [P, ctypes.POINTER(ctypes.c_int16), I,
                                    ctypes.c_char_p, ctypes.c_int32]
        lib.opus_decode.restype = I
        lib.opus_decode.argtypes = [P, ctypes.c_char_p, ctypes.c_int32,
                                    ctypes.POINTER(ctypes.c_int16), I, I]
        lib.opus_encoder_destroy.argtypes = [P]
        lib.opus_decoder_destroy.argtypes = [P]
    except AttributeError:
        _OPUS = False
        return None
    _OPUS = lib
    return lib


def codecs_here() -> list[str]:
    return ["opus", "ulaw"] if _opus() is not None else ["ulaw"]


class Encoder:
    """20 ms frames of RATE mono int16 in, bytes out."""

    def __init__(self, codec: int) -> None:
        self.codec = codec
        self._enc = None
        if codec == OPUS:
            lib, err = _opus(), ctypes.c_int(0)
            self._enc = lib.opus_encoder_create(RATE, 1, 2048, ctypes.byref(err))  # VOIP
            if not self._enc or err.value:
                raise RuntimeError("opus encoder")
            lib.opus_encoder_ctl(ctypes.c_void_p(self._enc), ctypes.c_int(4002),
                                 ctypes.c_int(24000))                      # bitrate
            self._out = ctypes.create_string_buffer(1000)

    def encode(self, pcm: np.ndarray) -> bytes:
        if self.codec == OPUS:
            buf = np.ascontiguousarray(pcm, dtype=np.int16)
            n = _opus().opus_encode(self._enc, buf.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                                    FRAME, self._out, len(self._out))
            return self._out.raw[:n] if n > 0 else b""
        x = pcm.astype(np.float32) / 32768.0
        y = np.sign(x) * np.log1p(255.0 * np.abs(x)) / math.log(256.0)
        return np.clip(np.round(y * 127.0), -127, 127).astype(np.int8).tobytes()

    def __del__(self) -> None:
        if self._enc and _OPUS:
            _OPUS.opus_encoder_destroy(self._enc)


class Decoder:
    def __init__(self, codec: int) -> None:
        self.codec = codec
        self._dec = None
        if codec == OPUS:
            lib, err = _opus(), ctypes.c_int(0)
            if lib is None:
                raise RuntimeError("no opus here")
            self._dec = lib.opus_decoder_create(RATE, 1, ctypes.byref(err))
            if not self._dec or err.value:
                raise RuntimeError("opus decoder")
            self._pcm = np.zeros(FRAME * 6, np.int16)

    def decode(self, data: bytes) -> np.ndarray | None:
        if self.codec == OPUS:
            n = _opus().opus_decode(self._dec, data, len(data),
                                    self._pcm.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
                                    len(self._pcm), 0)
            return self._pcm[:n].copy() if n == FRAME else None
        if len(data) != FRAME:
            return None
        q = np.frombuffer(data, np.int8).astype(np.float32) / 127.0
        x = np.sign(q) * (np.power(256.0, np.abs(q)) - 1.0) / 255.0
        return (x * 32767.0).astype(np.int16)

    def __del__(self) -> None:
        if self._dec and _OPUS:
            _OPUS.opus_decoder_destroy(self._dec)


# -------------------------------------------------------------------- voice
class Voice(QObject):
    """One person's end of a voice chat. The hub (`hub=True`) keeps the roster
    and passes every speaker on to everyone else in; a member talks to the hub
    alone. `send(peer, datagram)`: peer is the hub's handle for a member, None
    for a member's hub. Joining and the microphone are the caller's to ask
    permission for: nothing here starts by itself."""

    changed = pyqtSignal()          # who is in, who is talking, our own state
    opened = pyqtSignal(str)        # someone opened voice while we are out: who
    ended = pyqtSignal(str)         # it closed under us, and why
    failed = pyqtSignal(str)        # a device could not be used

    def __init__(self, key: bytes, hub: bool, send, name: str = "",
                 batch: bool = True, devices: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.hub = hub
        self._send = send
        self.name = clean_name(name) or "someone"
        self.batch = batch
        self.on = False
        self.mic = False
        self.volume = 1.0
        self.sense = "normal"
        self.codecs = codecs_here()
        self.closed = False
        # the hub's
        self.people: dict = {}      # peer -> {"s", "n", "mic", "c"} (in voice)
        self.names: dict | None = None   # peer -> name the session gives them
        self.known: set = set()     # peers told the roster even when out of voice
        self._sids = 1
        self._out: dict = {}        # peer -> datagrams waiting for the next flush
        # a member's
        self.sid = 0
        self.roster: list = []      # [{"s", "n", "mic"}], as the hub says
        self.codec = ULAW
        self._hello_at = 0.0
        self._open_seen = False
        # audio
        self._enc: Encoder | None = None
        self._seq = 0
        self._buf = np.zeros(0, np.int16)
        self._frames: list[bytes] = []
        self._pre: deque = deque(maxlen=PREROLL)
        self._hang = 0
        self._floor = -60.0
        self._level: float | None = None     # speech level heard, dBFS
        self._gain = 0.0                     # dB applied to what is sent
        self._hear = 1.0                     # the listening limiter's gain
        self.denoise = True
        self.mic_ok = False                  # the microphone was allowed once this time in
        self._den = Denoiser()
        self._far = FarEnd()
        self._aec = EchoCanceller()
        self._run = 0                        # loud frames in a row
        self._dec: dict = {}
        self._jit: dict = {}        # sid -> deque of frames
        self._first: dict = {}      # sid -> when its waiting audio began
        self._playing: set = set()
        self._heard: dict = {}      # sid -> when last heard
        self._last_seq: dict = {}
        self.sent = self.received = 0
        self.dev = Devices(self) if devices else None
        self.timer = QTimer(self)
        self.timer.setInterval(PACKET_MS)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    # ------------------------------------------------------------- choices
    def join(self, mic: bool) -> None:
        """In, after the person said yes; `mic` only if they allowed it."""
        if self.closed:
            return
        self.on = True
        self.mic = self.mic_ok = bool(mic)
        self._restart_audio()
        self._say_state()

    def set_mic(self, on: bool) -> None:
        """Turning it on is only ever done after asking, the first time in a voice chat."""
        if not self.on or self.mic == bool(on):
            return
        self.mic = bool(on)
        self.mic_ok = self.mic_ok or self.mic
        self._restart_audio()
        self._say_state()

    def leave(self) -> None:
        if not self.on:
            return
        self.on = self.mic = self.mic_ok = False
        self._restart_audio()
        if self.hub:
            self._roster_out()
        else:
            self._tx(None, seal(self.key, b"B", b""))
        self._drop_audio()
        self.changed.emit()

    def close(self, why: str = "") -> None:
        """The session is over: tell the others (hub) and let go of devices."""
        if self.closed:
            return
        if self.hub:
            for peer in set(self.people) | self.known:
                self._send(peer, seal(self.key, b"E", why.encode()[:120]))
        elif self.on:
            self._send(None, seal(self.key, b"B", b""))
        self.on = self.mic = False
        self.closed = True
        self.timer.stop()
        if self.dev is not None:
            self.dev.stop()
        self.changed.emit()

    def set_peers(self, names: dict) -> None:
        """Hub: everyone the session has and can hear voice, peer -> name."""
        self.names = dict(names)
        gone = [p for p in self.people if p not in names]
        for p in gone:
            self.people.pop(p, None)
        new = set(names) - self.known
        self.known = set(names)
        renamed = False
        for p in self.people:
            n = clean_name(names[p]) or self.people[p]["n"]
            renamed = renamed or n != self.people[p]["n"]
            self.people[p]["n"] = n
        if gone or new or renamed:
            self._roster_out()

    def peer_gone(self, peer) -> None:
        """Hub: a member's connection closed."""
        self.known.discard(peer)
        if self.people.pop(peer, None) is not None:
            self._roster_out()

    # ------------------------------------------------------------- reading
    def who(self) -> list[dict]:
        """Everyone in voice: {"n", "mic", "talk", "me"}."""
        now = time.monotonic()
        talk = {s for s, at in self._heard.items() if now - at < TALK_HOLD}
        if self.hub:
            rows = ([{"s": 1, "n": self.name, "mic": self.mic}] if self.on else []) + \
                list(self.people.values())
        else:
            rows = self.roster
        mine = 1 if self.hub else self.sid
        return [{"n": r["n"], "mic": r["mic"], "me": r["s"] == mine and self.on,
                 "talk": (r["s"] in talk) or (r["s"] == mine and self.on and self._hang > 0)}
                for r in rows]

    def open_now(self) -> bool:
        """Whether anyone is in voice."""
        return bool(self.who())

    def talking(self) -> bool:
        return self.on and self.mic and self._hang > 0

    # --------------------------------------------------------------- wires
    def got(self, peer, data: bytes) -> None:
        """Any voice datagram; anything not sealed under the key is dropped."""
        if self.closed:
            return
        try:
            opened = unseal(self.key, data)
            if opened is None:
                return
            self.received += 1
            kind, body = opened
            (self._hub_got if self.hub else self._member_got)(peer, kind, body)
        except Exception:                        # noqa: BLE001 -- a peer cannot crash us
            import traceback
            traceback.print_exc()

    def _hub_got(self, peer, kind: bytes, body: bytes) -> None:
        if self.names is not None and peer not in self.names:
            return
        if kind == b"H":
            msg = json.loads(body.decode("utf-8"))
            if not isinstance(msg, dict):
                return
            p, first = self.people.get(peer), False
            if not msg.get("on"):
                if p is not None:
                    self.people.pop(peer)
                    self._roster_out()
                return
            if p is None:
                if len(self.people) + 1 >= MAX_PEOPLE:
                    return
                self._sids = self._sids + 1 if self._sids < 250 else 2
                p = self.people[peer] = {"s": self._sids, "n": "", "mic": False, "c": ["ulaw"]}
                first = len(self.people) == 1 and not self.on
            named = (self.names or {}).get(peer)
            p["n"] = clean_name(named) or clean_name(msg.get("n")) or f"someone {p['s'] - 1}"
            p["mic"] = msg.get("mic") is True
            c = msg.get("c")
            p["c"] = [x for x in c if x in CODECS][:4] if isinstance(c, list) else ["ulaw"]
            self.known.add(peer)
            self._roster_out()
            if first:
                self.opened.emit(p["n"])
        elif kind == b"B":
            if self.people.pop(peer, None) is not None:
                self._roster_out()
        elif kind == b"A":
            p = self.people.get(peer)
            if p is None or not p["mic"] or len(body) < 4:
                return
            body = bytes([p["s"]]) + body[1:]
            if self.on:
                self._play_packet(body)
            for q in self.people:
                if q != peer:
                    self._queue(q, seal(self.key, b"A", body))

    def _member_got(self, _peer, kind: bytes, body: bytes) -> None:
        if kind == b"R":
            msg = json.loads(body.decode("utf-8"))
            if not isinstance(msg, dict):
                return
            rows = []
            for r in msg.get("p") or []:
                if isinstance(r, dict) and isinstance(r.get("s"), int) and len(rows) < MAX_PEOPLE:
                    rows.append({"s": r["s"], "n": clean_name(r.get("n")) or "someone",
                                 "mic": r.get("mic") is True})
            self.roster = rows
            you = msg.get("you")
            self.sid = you if isinstance(you, int) and not isinstance(you, bool) else 0
            c = CODECS.get(str(msg.get("codec")), ULAW)
            if c != self.codec:
                self.codec = c
                self._enc = None
            others = [r for r in rows if r["s"] != self.sid]
            if not self.on and others and not self._open_seen:
                self.opened.emit(others[0]["n"])
            self._open_seen = bool(others) or self.on
            if self.on and not self.sid and time.monotonic() - self._hello_at > HELLO_AGAIN:
                self._say_state()
            self.changed.emit()
        elif kind == b"A":
            if self.on and len(body) >= 4 and body[0] != self.sid:
                self._play_packet(body)
        elif kind == b"E":
            was = self.on
            self.on = self.mic = False
            self.roster, self.sid, self._open_seen = [], 0, False
            self._restart_audio()
            self._drop_audio()
            self.changed.emit()
            if was:
                self.ended.emit(body.decode("utf-8", "replace")[:120] or "voice chat ended")

    def _tx(self, peer, datagram: bytes) -> None:
        self.sent += 1
        self._send(peer, datagram)

    def _queue(self, peer, datagram: bytes) -> None:
        if self.batch:
            self._out.setdefault(peer, []).append(datagram)
        else:
            self._tx(peer, datagram)

    def _tick(self) -> None:
        """Every PACKET_MS: the hub's batched sends go out together, so the
        relay sees one message per person per tick however many speak."""
        if not self.hub and self.on and not self.sid \
                and time.monotonic() - self._hello_at > HELLO_AGAIN:
            self._say_state()                    # the hello went unanswered
        out, self._out = self._out, {}
        for peer, grams in out.items():
            if peer in self.people:
                for g in grams:
                    self._tx(peer, g)
        if self._heard and any(time.monotonic() - at < TALK_HOLD + 0.2
                               for at in self._heard.values()):
            self.changed.emit()

    def _say_state(self) -> None:
        if self.hub:
            self._roster_out()
            self.changed.emit()
            return
        self._hello_at = time.monotonic()
        body = json.dumps({"n": self.name, "on": self.on, "mic": self.mic,
                           "c": self.codecs}).encode()
        self._tx(None, seal(self.key, b"H", body))
        self.changed.emit()

    def _roster_out(self) -> None:
        """Hub: everyone known is told who is in, and which codec all can use."""
        rows = ([{"s": 1, "n": self.name, "mic": self.mic}] if self.on else []) + \
            [{"s": p["s"], "n": p["n"], "mic": p["mic"]} for p in self.people.values()]
        can = set(self.codecs) if self.on else {"opus", "ulaw"}
        for p in self.people.values():
            can &= set(p["c"])
        codec = "opus" if "opus" in can else "ulaw"
        if CODECS[codec] != self.codec:
            self.codec = CODECS[codec]
            self._enc = None
        for peer in set(self.people) | self.known:
            you = self.people.get(peer, {}).get("s", 0)
            body = json.dumps({"p": rows, "you": you, "codec": codec}).encode()
            self._tx(peer, seal(self.key, b"R", body))
        self.changed.emit()

    # --------------------------------------------------------------- audio
    def capture(self, pcm: np.ndarray, at: float | None = None) -> None:
        """Microphone audio at RATE, any length, its last sample heard at `at`
        (monotonic); sent while it is speech."""
        if not (self.on and self.mic):
            return
        at = time.monotonic() if at is None else at
        self._buf = np.concatenate([self._buf, pcm.astype(np.int16)])
        while len(self._buf) >= FRAME:
            frame, self._buf = self._buf[:FRAME], self._buf[FRAME:]
            self._frame(frame, at - len(self._buf) / RATE)

    def played(self, pcm: np.ndarray, at: float) -> None:
        """What the speakers play from `at` on: the echo to take back out."""
        self._far.add(pcm, at)

    def _frame(self, frame: np.ndarray, at: float | None = None) -> None:
        echo = None
        if at is not None and self._far.t0 is not None:
            far = self._far.window(at, (AEC_PARTS + 1) * FRAME)
            if far is not None:
                frame, echo = self._aec(frame, far)
        if self.denoise or echo is not None:
            frame = self._den(frame, echo, noise=self.denoise)
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        db = 20.0 * math.log10(rms / 32768.0 + 1e-9)
        self._floor = db if db < self._floor else self._floor + FLOOR_RISE
        loud = db > max(QUIET_DB, self._floor + SENSES.get(self.sense, 10.0))
        if echo is not None and loud:
            # while the speakers play, what is left must be near the echo's own level
            # to be a voice here: the cancelled echo sits ECHO_GATE and more under it
            echo_db = 20.0 * math.log10(float(np.sqrt(np.mean(echo ** 2))) / 32768.0 + 1e-9)
            # and until the room has been learnt, the far end's voice and one here
            # cannot be told apart: as a speakerphone does, it waits its turn
            loud = db > echo_db - ECHO_GATE and self._aec.erle >= AEC_OPEN
        self._run = self._run + 1 if loud else 0
        # Only speech that lasts opens it or holds it open: a key click is a frame
        # or two, so typing never keeps the microphone sending.
        speech = loud and self._run >= (ONSET if echo is None else ONSET_FAR)
        if speech:
            self._level = db if self._level is None else \
                self._level + LEVEL_EASE * (db - self._level)
            if self._hang == 0:
                for old in self._pre:
                    self._add(old)
                self._pre.clear()
                self.changed.emit()
            self._hang = HANG
        if self._hang > 0:
            self._add(frame)
            self._hang -= 1
            if self._hang == 0:
                self._flush_own()
                self.changed.emit()
        else:
            self._pre.append(frame)

    def _lift(self, frame: np.ndarray) -> np.ndarray:
        """Automatic gain: speech at about TARGET_DB whatever the microphone's own level."""
        if self._level is None:
            return frame
        want = max(GAIN_DB[0], min(GAIN_DB[1], TARGET_DB - self._level))
        if self._gain == 0.0 and self._hang == HANG:
            self._gain = want                    # the first words: no slow climb
        self._gain += max(-GAIN_STEP, min(GAIN_STEP, want - self._gain))
        y = frame.astype(np.float32) * (10.0 ** (self._gain / 20.0))
        peak = float(np.abs(y).max())
        if peak > PEAK:
            y *= PEAK / peak
        return y.astype(np.int16)

    def _add(self, frame: np.ndarray) -> None:
        frame = self._lift(frame)
        if self._enc is None or self._enc.codec != self.codec:
            try:
                self._enc = Encoder(self.codec)
            except Exception:                    # noqa: BLE001
                self._enc = Encoder(ULAW)
        got = self._enc.encode(frame)
        if not got:
            return
        if sum(len(f) + 2 for f in self._frames) + len(got) + 2 > PACKET_BYTES:
            self._flush_own()
        self._frames.append(got)
        if len(self._frames) >= PACKET_FRAMES:
            self._flush_own()

    def _flush_own(self) -> None:
        if not self._frames:
            return
        frames, self._frames = self._frames, []
        self._seq = (self._seq + 1) & 0xFFFF
        body = struct.pack("!BHB", 1 if self.hub else 0, self._seq, self._enc.codec) + \
            b"".join(struct.pack("!H", len(f)) + f for f in frames)
        sealed = seal(self.key, b"A", body)
        if self.hub:
            for peer in self.people:
                self._queue(peer, sealed)
        else:
            self._tx(None, sealed)

    def _play_packet(self, body: bytes) -> None:
        sid, seq, codec = struct.unpack("!BHB", body[:4])
        last = self._last_seq.get(sid)
        if last is not None and 0 < (last - seq) & 0xFFFF < 0x8000:
            return                               # old or repeated
        self._last_seq[sid] = seq
        dec = self._dec.get((sid, codec))
        if dec is None:
            try:
                dec = self._dec[(sid, codec)] = Decoder(codec)
            except Exception:                    # noqa: BLE001
                return
        q = self._jit.setdefault(sid, deque())
        at = 4
        while at + 2 <= len(body):
            n = struct.unpack("!H", body[at:at + 2])[0]
            pcm = dec.decode(body[at + 2:at + 2 + n])
            at += 2 + n
            if pcm is not None:
                if not q and sid not in self._playing:
                    self._first[sid] = time.monotonic()
                q.append(pcm)
        if len(q) > MAX_FRAMES:
            for _ in range(len(q) - START_FRAMES):
                q.popleft()
        self._heard[sid] = time.monotonic()

    def mix(self, frames: int) -> np.ndarray:
        """The next `frames` 20 ms of everyone heard, mixed, at RATE."""
        out = np.zeros(frames * FRAME, np.float32)
        now = time.monotonic()
        for i in range(frames):
            for sid, q in list(self._jit.items()):
                if sid not in self._playing:
                    if q and (len(q) >= START_FRAMES or now - self._first.get(sid, now) >= START_WAIT):
                        self._playing.add(sid)
                    else:
                        continue
                if q:
                    out[i * FRAME:(i + 1) * FRAME] += q.popleft()
                else:
                    self._playing.discard(sid)
        out *= self.volume
        return self._limit(out)

    def _limit(self, out: np.ndarray) -> np.ndarray:
        """Cap what reaches the ears, frame by frame, before it is heard."""
        rise = 10.0 ** (HEAR_RISE / 20.0)
        for i in range(0, len(out), FRAME):
            f = out[i:i + FRAME]
            rms = float(np.sqrt(np.mean(f ** 2))) + 1e-9
            peak = float(np.abs(f).max()) + 1e-9
            cap = min(1.0, 32768.0 * 10.0 ** (HEAR_RMS / 20.0) / rms, HEAR_PEAK / peak)
            self._hear = cap if cap < self._hear else min(cap, self._hear * rise)
            f *= self._hear
        return np.clip(out, -HEAR_PEAK, HEAR_PEAK).astype(np.int16)

    def _drop_audio(self) -> None:
        self._jit.clear()
        self._playing.clear()
        self._heard.clear()
        self._frames.clear()
        self._buf = np.zeros(0, np.int16)
        self._hang = 0

    def _restart_audio(self) -> None:
        if self.dev is None:
            return
        why = self.dev.apply(self.on, self.on and self.mic)
        if why:
            if self.mic:
                self.mic = False
                self._say_state()
            self.failed.emit(why)


# -------------------------------------------------------------------- noise
class Denoiser:
    """Background noise off and key clicks down, 20 ms in, 20 ms out (20 ms late).
    The noise is the lowest each band has been lately (minimum statistics), so
    speech never teaches it; square-root Hann windows at half overlap, so what
    is left alone comes back exact."""

    N = 2 * FRAME

    def __init__(self) -> None:
        n = np.arange(self.N)
        self.win = np.sqrt(0.5 - 0.5 * np.cos(2 * np.pi * n / self.N)).astype(np.float32)
        self.prev = np.zeros(FRAME, np.float32)
        self.tail = np.zeros(FRAME, np.float32)
        self.smooth: np.ndarray | None = None      # each band's power, smoothed
        self.mins: deque = deque(maxlen=DN_BLOCKS)  # each past block's lowest
        self.low: np.ndarray | None = None          # this block's lowest so far
        self.count = 0
        self.gain = np.ones(self.N // 2 + 1, np.float32)
        self.energy = 0.0
        freqs = np.fft.rfftfreq(self.N, 1.0 / RATE)
        self.band = (freqs >= 1000) & (freqs <= 7000)
        self.spread = np.array([1, 2, 3, 2, 1], np.float32) / 9.0
        self.prev_echo = np.zeros(FRAME, np.float32)
        self.last = 0.0

    def __call__(self, frame: np.ndarray, echo: np.ndarray | None = None,
                 noise: bool = True) -> np.ndarray:
        x = frame.astype(np.float32)
        spec = np.fft.rfft(np.concatenate([self.prev, x]) * self.win)
        self.prev = x
        power = (spec.real ** 2 + spec.imag ** 2) + 1e-3
        e = np.zeros(FRAME, np.float32) if echo is None else echo.astype(np.float32)
        es = np.fft.rfft(np.concatenate([self.prev_echo, e]) * self.win)
        self.prev_echo = e
        echo_pow = es.real ** 2 + es.imag ** 2
        self.smooth = power.copy() if self.smooth is None else \
            self.smooth + DN_SMOOTH * (power - self.smooth)
        self.low = self.smooth.copy() if self.low is None else np.minimum(self.low, self.smooth)
        self.count += 1
        if self.count >= DN_BLOCK:
            self.mins.append(self.low)
            self.low, self.count = None, 0
        noise_on = noise
        noise = np.minimum.reduce([*self.mins, self.smooth if self.low is None else self.low])
        # over neighbouring bands as well: one bin of noise swings far more than five
        k = self.spread
        noise = np.convolve(noise, k, "same") * DN_BIAS
        heard = np.convolve(self.smooth, k, "same")
        gain = (np.maximum(DN_FLOOR, 1.0 - DN_OVER * noise / heard) if noise_on
                else np.ones_like(heard))
        # what is left of the echo: its estimate, against this frame alone
        gain = np.minimum(gain, np.maximum(ECHO_FLOOR, 1.0 - ECHO_OVER * np.convolve(echo_pow, k, "same")
                                           / np.convolve(power, k, "same")))
        # falls at once, rises over a few frames: a band of noise that spikes for
        # a frame stays down, which is most of the warble subtraction leaves
        gain = np.where(gain > self.gain, self.gain + DN_RISE * (gain - self.gain), gain)
        self.gain = gain.astype(np.float32)
        energy = float(power.sum())
        b = power[self.band]
        flat = float(np.exp(np.mean(np.log(b))) / np.mean(b))
        # a click: far over the recent level, or over the frame just before, and noise-like
        if noise_on and flat > CLICK_FLAT and self.energy and (
                energy > CLICK_JUMP * self.energy or energy > CLICK_JUMP * self.last):
            gain = gain * CLICK_CUT
        self.energy = energy if not self.energy else self.energy + 0.2 * (energy - self.energy)
        self.last = energy
        out = np.fft.irfft(spec * gain, self.N).astype(np.float32) * self.win
        y = self.tail + out[:FRAME]
        self.tail = out[FRAME:]
        return np.clip(y, -32767, 32767).astype(np.int16)


# --------------------------------------------------------------------- echo
class FarEnd:
    """What was played, on the monotonic clock: a running stretch of samples
    and the time its first one left the speakers."""

    def __init__(self) -> None:
        self.buf = np.zeros(0, np.float32)
        self.t0: float | None = None

    def end(self) -> float:
        return (self.t0 or 0.0) + len(self.buf) / RATE

    def add(self, pcm: np.ndarray, at: float) -> None:
        x = pcm.astype(np.float32)
        if self.t0 is None or at < self.end() - 0.05:
            self.buf, self.t0 = x, at            # first, or the clock jumped back: start again
        else:
            gap = int(round((at - self.end()) * RATE))
            if gap > int(0.05 * RATE):            # the speakers ran dry: they played silence
                self.buf = np.concatenate([self.buf, np.zeros(min(gap, int(FAR_KEEP * RATE)), np.float32)])
            self.buf = np.concatenate([self.buf, x])
        keep = int(FAR_KEEP * RATE)
        if len(self.buf) > keep:
            self.t0 += (len(self.buf) - keep) / RATE
            self.buf = self.buf[-keep:]

    def window(self, at: float, n: int) -> np.ndarray | None:
        """The `n` samples played up to `at`, zeros where nothing was; None when all silent."""
        end = int(round((at - self.t0) * RATE))
        lo = end - n
        out = np.zeros(n, np.float32)
        a, b = max(0, lo), min(len(self.buf), end)
        if b <= a:
            return None
        out[a - lo:b - lo] = self.buf[a:b]
        tail = out[-FRAME * 4:]
        if 20.0 * math.log10(float(np.sqrt(np.mean(out ** 2))) / 32768.0 + 1e-12) < FAR_QUIET \
                and not tail.any():
            return None
        return out


class EchoCanceller:
    """A partitioned frequency-domain NLMS filter (overlap-save): learns the path from
    what was played to what the microphone hears, and subtracts its estimate."""

    B = FRAME

    def __init__(self, parts: int = AEC_PARTS) -> None:
        self.P = parts
        self.W = np.zeros((parts, self.B + 1), np.complex64)
        self.px: np.ndarray | None = None
        self.bad = 0
        self.erle = 1.0                           # echo in over echo left, as learnt so far
        self.both = 0

    def __call__(self, frame: np.ndarray, far: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        B, P = self.B, self.P
        d = frame.astype(np.float32)
        # partition k sees the 2B samples ending k blocks before this one
        idx = np.arange(2 * B)[None, :] + (len(far) - 2 * B - B * np.arange(P))[:, None]
        X = np.fft.rfft(far[idx], axis=1)
        y = np.fft.irfft((self.W * X).sum(axis=0), 2 * B)[B:].astype(np.float32)
        e = d - y
        far_db = 20.0 * math.log10(float(np.sqrt(np.mean(far ** 2))) / 32768.0 + 1e-12)
        if far_db < FAR_QUIET:
            return np.clip(e, -32767, 32767).astype(np.int16), y
        # Both speaking: the mic holds far more than the echo the filter has
        # learnt to expect leaves (its ERLE). Not judged until it has learnt some;
        # a "both" that lasts is the room changing, learnt again slowly.
        pd, pe = float(np.mean(d ** 2)) + 1.0, float(np.mean(e ** 2)) + 1.0
        talk = self.erle > AEC_LEARNT and pe / pd > AEC_TALK / self.erle
        self.both = self.both + 1 if talk else 0
        mu = AEC_MU if not talk else (AEC_DT_MU if self.both < AEC_STUCK else AEC_MU * 0.3)
        if not talk:
            self.erle += 0.05 * (min(pd / pe, 1e4) - self.erle)
        now = (np.abs(X) ** 2).sum(axis=0)
        self.px = now if self.px is None else 0.7 * self.px + 0.3 * now
        # a band between the voice's harmonics has next to no power: without a
        # share of the whole, its step would be enormous and the filter blows up
        den = self.px + AEC_REG * float(self.px.mean()) + 1e3
        E = np.fft.rfft(np.concatenate([np.zeros(B, np.float32), e]))
        self.W += (mu * np.conj(X) * (E / den)[None, :]).astype(np.complex64)
        w = np.fft.irfft(self.W, 2 * B, axis=1)
        w[:, B:] = 0.0                            # keep it a linear filter (the overlap-save constraint)
        self.W = np.fft.rfft(w, axis=1).astype(np.complex64)
        # learning the wrong thing makes it louder, not quieter: start over
        # (only on a frame that holds something: a quiet one is all leftover)
        self.bad = self.bad + 1 if pd > AEC_LOUD and pe > 2.0 * pd else 0
        if self.bad > 10:
            self.W[:] = 0
            self.bad, self.erle = 0, 1.0
        return np.clip(e, -32767, 32767).astype(np.int16), y


# ------------------------------------------------------------------ devices
class _Resample:
    """Streaming linear resampling, with a box filter ahead of a big step down."""

    def __init__(self, src: int, dst: int) -> None:
        self.step = src / dst
        self.pos = 0.0
        self.tail = np.zeros(1, np.float32)
        self.k = int(self.step) if self.step >= 2 else 1

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.k > 1:
            x = np.convolve(x, np.full(self.k, 1.0 / self.k, np.float32), "same")
        buf = np.concatenate([self.tail, x.astype(np.float32)])
        n = len(buf)
        idx = np.arange(self.pos, n - 1, self.step)
        out = np.interp(idx, np.arange(n), buf).astype(np.float32)
        self.pos = (idx[-1] + self.step if len(idx) else self.pos) - (n - 1)
        self.tail = buf[-1:]
        return out


class Devices(QObject):
    """The default microphone and speakers, through Qt Multimedia."""

    OUT_AHEAD = 0.12      # seconds kept queued in the speakers

    def __init__(self, voice: Voice) -> None:
        super().__init__(voice)
        self.voice = voice
        self.src = self.src_io = self.sink = self.sink_io = None
        self._feed = QTimer(self)
        self._feed.setInterval(10)
        self._feed.timeout.connect(self._push)

    def apply(self, hear: bool, speak: bool) -> str:
        """Open or close each side; returns why something could not be used."""
        why = ""
        if hear and self.sink is None:
            why = self._open_out()
        elif not hear:
            self._close_out()
        if speak and self.src is None:
            why = self._open_in() or why
        elif not speak:
            self._close_in()
        return why

    def stop(self) -> None:
        self._close_in()
        self._close_out()

    @staticmethod
    def _format(dev):
        from PyQt6.QtMultimedia import QAudioFormat
        fmt = dev.preferredFormat()
        want = QAudioFormat()
        want.setSampleRate(fmt.sampleRate() or 48000)
        want.setChannelCount(max(1, min(2, fmt.channelCount() or 1)))
        want.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not dev.isFormatSupported(want):
            want.setSampleFormat(QAudioFormat.SampleFormat.Float)
            if not dev.isFormatSupported(want):
                return fmt
        return want

    def _open_in(self) -> str:
        try:
            from PyQt6.QtMultimedia import QAudioSource, QMediaDevices
        except ImportError:
            return "the microphone needs PyQt6's QtMultimedia"
        dev = QMediaDevices.defaultAudioInput()
        if dev.isNull():
            return "no microphone was found — joined to listen only"
        fmt = self._format(dev)
        self.src = QAudioSource(dev, fmt, self)
        self.in_fmt = fmt
        self.in_rs = _Resample(fmt.sampleRate(), RATE)
        self.src_io = self.src.start()
        if self.src_io is None:
            self._close_in()
            return ("the microphone could not be opened — is another app using it, "
                    "or is it blocked in the system's privacy settings?")
        self.src_io.readyRead.connect(self._pull)
        return ""

    def _close_in(self) -> None:
        if self.src is not None:
            self.src.stop()
            self.src.deleteLater()
        self.src = self.src_io = None

    def _pull(self) -> None:
        if self.src_io is None:
            return
        raw = bytes(self.src_io.readAll())
        x = self._samples(raw, self.in_fmt)
        if len(x):
            self.voice.capture((self.in_rs(x) * 32767.0).astype(np.int16), time.monotonic())

    @staticmethod
    def _samples(raw: bytes, fmt) -> np.ndarray:
        from PyQt6.QtMultimedia import QAudioFormat
        ch = max(1, fmt.channelCount())
        if fmt.sampleFormat() == QAudioFormat.SampleFormat.Float:
            x = np.frombuffer(raw[:len(raw) // 4 * 4], np.float32)
        elif fmt.sampleFormat() == QAudioFormat.SampleFormat.Int32:
            x = np.frombuffer(raw[:len(raw) // 4 * 4], np.int32).astype(np.float32) / 2 ** 31
        elif fmt.sampleFormat() == QAudioFormat.SampleFormat.UInt8:
            x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            x = np.frombuffer(raw[:len(raw) // 2 * 2], np.int16).astype(np.float32) / 32768.0
        n = len(x) // ch * ch
        return x[:n].reshape(-1, ch).mean(axis=1) if ch > 1 else x[:n]

    def _open_out(self) -> str:
        try:
            from PyQt6.QtMultimedia import QAudioSink, QMediaDevices
        except ImportError:
            return "voice chat needs PyQt6's QtMultimedia"
        dev = QMediaDevices.defaultAudioOutput()
        if dev.isNull():
            return "no speakers or headphones were found"
        fmt = self._format(dev)
        self.sink = QAudioSink(dev, fmt, self)
        self.out_fmt = fmt
        self.out_rs = _Resample(RATE, fmt.sampleRate())
        self.sink.setBufferSize(int(fmt.bytesForDuration(400_000)))
        self.sink_io = self.sink.start()
        if self.sink_io is None:
            self._close_out()
            return "the speakers could not be opened"
        self._feed.start()
        return ""

    def _close_out(self) -> None:
        self._feed.stop()
        if self.sink is not None:
            self.sink.stop()
            self.sink.deleteLater()
        self.sink = self.sink_io = None

    def _push(self) -> None:
        if self.sink is None or self.sink_io is None:
            return
        from PyQt6.QtMultimedia import QAudioFormat
        fmt = self.out_fmt
        queued = self.sink.bufferSize() - self.sink.bytesFree()
        want = int(fmt.bytesForDuration(int(self.OUT_AHEAD * 1e6))) - queued
        per = fmt.bytesForDuration(int(FRAME / RATE * 1e6))
        if want < per or per <= 0:
            return
        frames = max(1, want // per)
        pcm = self.voice.mix(int(frames))
        # plays once what is queued ahead of it has: the echo it will make, and when
        self.voice.played(pcm, time.monotonic() + fmt.durationForBytes(queued) / 1e6)
        x = self.out_rs(pcm.astype(np.float32) / 32768.0)
        if fmt.channelCount() > 1:
            x = np.repeat(x[:, None], fmt.channelCount(), axis=1).ravel()
        if fmt.sampleFormat() == QAudioFormat.SampleFormat.Float:
            raw = x.astype(np.float32).tobytes()
        else:
            raw = (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()
        self.sink_io.write(raw)


def log(text: str) -> None:
    print(f"[voice] {text}", file=sys.stderr, flush=True)
