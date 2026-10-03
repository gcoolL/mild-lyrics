"""Two editors finding each other with no server between them.

    host                                   joiner
    ----                                   ------
    asks STUN where it is                  .
    makes an invite code  ---- chat ---->  pastes it, asks STUN where it is
    .                     <--- chat -----  makes a reply code
    pastes the reply
    both send small punch packets at every address the other gave, at once,
    so each router sees its own side speak first and lets the answer in
    joiner opens QUIC to whichever address answered; TLS 1.3 against the
    certificate the invite carried; the token from the invite goes first

WHAT IS TRUSTED, AND WHY. The invite is the password: it carries a
certificate made for this session alone, which the joiner pins as the ONLY one
it accepts, and a random token the host checks before a joiner is anything at
all. Everything after the handshake is QUIC -- encrypted, authenticated,
ordered and retransmitted by aioquic, a maintained library, not by anything
written here. What is written here is the punching, a STUN client, and the
framing; each checks lengths before it reads and drops what it does not
recognise without answering, so the port looks closed to anyone without a
code.

WHAT IS NOT PROMISED. Hole punching works between most home routers. It does
not work when both sides' routers give a new port for every destination (a
"symmetric" NAT — some mobile networks and carrier-grade NAT), and nothing
here pretends otherwise: STUN is asked twice, from the same socket, and if
the two answers disagree the window says so before anybody pastes a code.

Driven entirely by Qt's own loop -- aioquic is used through its sans-IO API,
so there is no asyncio and no thread.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import ssl
import struct
import time
import sys
import traceback
import zlib

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import (
    QAbstractSocket, QHostAddress, QHostInfo, QNetworkInterface, QUdpSocket,
)

try:
    from aioquic.buffer import Buffer
    from aioquic.quic import events as QE
    from aioquic.quic.configuration import QuicConfiguration
    from aioquic.quic.connection import QuicConnection
    from aioquic.quic.packet import pull_quic_header
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.x509.oid import NameOID
    MISSING = ""
except ImportError as exc:                       # pragma: no cover
    MISSING = getattr(exc, "name", "") or "aioquic"

from . import collab as C
from . import collab_turn as TURN

ALPN = "mild-lyrics-collab/1"
SNI = "mild-lyrics.invalid"
STUN_SERVERS = ["stun.l.google.com:19302", "stun.cloudflare.com:3478"]
INVITE_TTL = 1800.0
JOIN_WAIT = 600.0         # how long a joiner keeps knocking
PUNCH_MS = 100
PUNCH_FOR = 20.0
GATHER_FOR = 2.5
# A relay (collab_turn) is answered through only once a direct path has had
# this long to answer and has not: pairs that can connect directly still do.
RELAY_AFTER = 3.0
RELAY_WAIT = 8.0          # how long gathering waits for a relay to be made
KEEPALIVE_MS = 10000
IDLE = 45.0
MAX_FRAME = 4 << 20
MAX_RATE = 200            # messages a second from one peer
MAX_CODE = 8192
MAX_CANDS = 12
TOKEN_TRIES = 3

PUNCH = b"\x00MLP"
STUN_MAGIC = 0x2112A442


def log(text: str) -> None:
    """One line to the terminal, as collab_ui's: what was seen and allowed,
    for the next time a connection does not happen."""
    print(f"[multiplayer] {text}", file=sys.stderr, flush=True)


def available() -> str:
    """'' if multiplayer can run here, else the missing package."""
    return MISSING


# ------------------------------------------------------------------- STUN
def stun_request() -> tuple[bytes, bytes]:
    tx = os.urandom(12)
    return tx, struct.pack("!HHI12s", 0x0001, 0, STUN_MAGIC, tx)


def stun_parse(data: bytes, tx: bytes) -> tuple[str, int] | None:
    """The address a STUN server saw us at, from its answer to `tx`. Every
    length is checked before it is used; anything off is None."""
    if not 20 <= len(data) <= 1500:
        return None
    kind, length, magic, got = struct.unpack("!HHI12s", data[:20])
    if kind != 0x0101 or magic != STUN_MAGIC or got != tx \
            or length % 4 or 20 + length > len(data):
        return None
    found = {}
    off, end = 20, 20 + length
    while off + 4 <= end:
        at, alen = struct.unpack("!HH", data[off:off + 4])
        val = data[off + 4:off + 4 + alen]
        if len(val) != alen:
            return None
        if at in (0x0001, 0x0020) and alen >= 4:
            fam, port = val[1], struct.unpack("!H", val[2:4])[0]
            raw = val[4:]
            if at == 0x0020:
                port ^= STUN_MAGIC >> 16
                mask = struct.pack("!I", STUN_MAGIC) + (tx if fam == 2 else b"")
                raw = bytes(a ^ b for a, b in zip(raw, mask))
            if fam == 1 and len(raw) == 4:
                found[at] = (str(ipaddress.IPv4Address(raw)), port)
            elif fam == 2 and len(raw) == 16:
                found[at] = (str(ipaddress.IPv6Address(raw)), port)
        off += 4 + alen + (-alen % 4)
    return found.get(0x0020) or found.get(0x0001)


# ------------------------------------------------------------------ codes
class BadCode(ValueError):
    pass


def _pack(kind: str, obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode().rstrip("=")
    return f"mild1{kind}.{body}"


def _unpack(kind: str, code: str) -> dict:
    code = "".join(str(code or "").split()).strip("`'\"<>")
    if len(code) > MAX_CODE:
        raise BadCode("that is far too long to be a code")
    other = {"i": "r", "r": "i"}[kind]
    if code.startswith(f"mild1{other}."):
        raise BadCode("that is a reply code — it goes in the host's window"
                      if other == "r" else
                      "that is an invite — it goes in the joiner's window")
    head = f"mild1{kind}."
    if not code.startswith(head):
        raise BadCode("that is not a Mild Lyrics code")
    try:
        body = code[len(head):]
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        z = zlib.decompressobj()
        text = z.decompress(raw, 65536)
        if z.unconsumed_tail or not z.eof:
            raise ValueError("does not unpack")
        obj = json.loads(text)
    except Exception:                            # noqa: BLE001
        raise BadCode("that code is cut short or mistyped") from None
    if not isinstance(obj, dict) or obj.get("v") != C.PROTO:
        raise BadCode("that code is from a different version of the editor")
    return obj


def _hex(x, n: int) -> bytes:
    if not isinstance(x, str) or len(x) != 2 * n:
        raise BadCode("that code is damaged")
    try:
        return bytes.fromhex(x)
    except ValueError:
        raise BadCode("that code is damaged") from None


def _cands(raw, loopback: bool) -> list[tuple[str, int]]:
    if not isinstance(raw, list) or len(raw) > MAX_CANDS:
        raise BadCode("that code is damaged")
    out = []
    for c in raw:
        if not (isinstance(c, list) and len(c) == 2 and isinstance(c[0], str)
                and len(c[0]) <= 45 and isinstance(c[1], int)
                and not isinstance(c[1], bool) and 0 < c[1] < 65536):
            raise BadCode("that code is damaged")
        try:
            ip = ipaddress.ip_address(c[0])
        except ValueError:
            raise BadCode("that code is damaged") from None
        if ip.is_multicast or ip.is_unspecified or ip.is_link_local \
                or (ip.is_loopback and not loopback):
            continue
        out.append((str(ip), c[1]))
    return out


def _reply_mac(token: bytes, iid: str, cands, name: str, sym) -> str:
    body = json.dumps([iid, cands, name, sym], separators=(",", ":"))
    return hmac.new(token, b"reply" + body.encode(), hashlib.sha256).hexdigest()[:32]


def _punch(role: bytes, iid: bytes, token: bytes) -> bytes:
    nonce = os.urandom(8)
    mac = hmac.new(token, b"punch" + role + iid + nonce, hashlib.sha256).digest()[:16]
    return PUNCH + role + iid + nonce + mac


def _punch_ok(data: bytes, role: bytes, iid: bytes, token: bytes) -> bool:
    if len(data) != 37 or data[4:5] != role or data[5:13] != iid:
        return False
    want = hmac.new(token, b"punch" + role + iid + data[13:21],
                    hashlib.sha256).digest()[:16]
    return hmac.compare_digest(want, data[21:37])


# ------------------------------------------------------------- certificate
def make_cert():
    """A certificate for this session only: made now, thrown away at the end,
    pinned by the joiner as the one certificate it will accept."""
    key = ed25519.Ed25519PrivateKey.generate()
    now = datetime.datetime.now(datetime.timezone.utc)
    who = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, SNI)])
    cert = (x509.CertificateBuilder().subject_name(who).issuer_name(who)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(hours=1))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(SNI)]),
                           critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                           critical=True)
            .sign(key, None))
    return key, cert


# ------------------------------------------------------------------- port
def _addr(qaddr: QHostAddress) -> str:
    text = qaddr.toString().split("%")[0]
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return text
    if ip.version == 6 and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ip)


class UdpPort(QObject):
    """One UDP socket, for STUN, punching and QUIC alike — it has to be the
    same one, because the router's opening is for this port and no other."""

    got = pyqtSignal(bytes, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.sock = QUdpSocket(self)
        self.v6 = self.sock.bind(QHostAddress(QHostAddress.SpecialAddress.Any), 0)
        if not self.v6:
            # No IPv6 on this machine at all: IPv4 alone, measured, not assumed.
            self.sock = QUdpSocket(self)
            if not self.sock.bind(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), 0):
                raise OSError(self.sock.errorString())
        # Room for a burst: the default is about two hundred datagrams on
        # Linux, however small each one is.
        self.sock.setSocketOption(
            QAbstractSocket.SocketOption.ReceiveBufferSizeSocketOption, 1 << 20)
        self.sock.readyRead.connect(self._read)

    def port(self) -> int:
        return int(self.sock.localPort())

    def _read(self) -> None:
        # Bound, checked every time round: a datagram can end the session,
        # and the session ending closes this socket mid-loop.
        while self.sock.state() == QAbstractSocket.SocketState.BoundState \
                and self.sock.hasPendingDatagrams():
            dg = self.sock.receiveDatagram(65536)
            if not dg.isValid():
                continue
            self.got.emit(bytes(dg.data()), (_addr(dg.senderAddress()),
                                             int(dg.senderPort())))

    def send(self, data: bytes, addr) -> None:
        ip = addr[0]
        if not self.v6 and ":" in ip:
            return
        self.sock.writeDatagram(data, QHostAddress(ip), int(addr[1]))

    def close(self) -> None:
        self.sock.close()


def local_candidates(port: int, v6: bool) -> list[tuple[str, int]]:
    """Every address someone could reach this socket at without STUN: the
    LAN, any VPN (Tailscale's 100.x is one), and global IPv6."""
    out = []
    F = QNetworkInterface.InterfaceFlag
    for nif in QNetworkInterface.allInterfaces():
        flags = nif.flags()
        if not (flags & F.IsUp and flags & F.IsRunning) or flags & F.IsLoopBack:
            continue
        for entry in nif.addressEntries():
            try:
                ip = ipaddress.ip_address(entry.ip().toString().split("%")[0])
            except ValueError:
                continue
            if ip.is_loopback or ip.is_link_local or ip.is_multicast \
                    or ip.is_unspecified:
                continue
            if ip.version == 6 and (not v6 or not (
                    ip.is_global or ip in ipaddress.ip_network("fc00::/7"))):
                continue
            out.append((str(ip), port))
    # IPv4 first: it is what most pairs end up on, and the list is capped.
    out.sort(key=lambda a: ":" in a[0])
    return out[:MAX_CANDS - 1]


# ---------------------------------------------------------------- the peer
class _Conn:
    def __init__(self, cid: int, quic, addr, invite=None) -> None:
        self.cid = cid
        self.quic = quic
        self.addr = addr
        self.invite = invite
        self.buf = b""
        self.ready = False          # host: token checked. joiner: handshake done
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.window_at = 0.0
        self.window_n = 0
        self.stream = 0


class _Invite:
    """One code, good for `seats` people.

    The count is the host's, never the code's: nothing a joiner holds says
    how many it lets in, so nothing a joiner does can change it. A place is
    spent when somebody comes in and is not given back when they leave --
    one code cannot be turned over and over to let a crowd through.
    """

    def __init__(self, seats: int = 1, watch: bool = False) -> None:
        self.watch = bool(watch)          # lets people watch, not edit
        self.resume_of: int | None = None  # a joiner's own way back in
        self.iid = secrets.token_bytes(8)
        self.token = secrets.token_bytes(16)
        self.made = time.monotonic()
        self.seats = max(1, min(C.MAX_PEERS, int(seats)))
        self.joined = 0
        self.burnt = False
        self.fails = 0
        self.replies: list[dict] = []     # {targets, from, before, name}
        self.heard: set = set()

    def why_shut(self) -> str:
        """'' while the invite still lets people in, else why not."""
        if self.burnt:
            return "that invite was shut after wrong tokens — make another"
        if self.joined >= self.seats:
            return (f"that invite has let in the {self.seats} "
                    f"{'person' if self.seats == 1 else 'people'} it was for "
                    "— make another")
        if time.monotonic() - self.made > INVITE_TTL:
            return (f"that invite is more than {INVITE_TTL / 60:.0f} minutes "
                    "old — make another")
        return ""


class Endpoint(QObject):
    """One side of a session's network: the host's or a joiner's.

    Speaks in dicts. `message(cid, msg)` is one checked JSON object from a
    peer; `send(cid, msg)` is the other way. Who may do what with them is
    collab.py's business, not this one's.
    """

    status = pyqtSignal(str)
    nat = pyqtSignal(dict)
    code = pyqtSignal(str, str)          # "invite" | "reply", the code
    joined = pyqtSignal(int, dict)       # cid, the joiner's hello (host only)
    connected = pyqtSignal()             # joiner: in, and the hello has gone
    message = pyqtSignal(int, object)
    left = pyqtSignal(int, str)
    failed = pyqtSignal(str)

    def __init__(self, role: str, name: str, stun=None, parent=None, *,
                 loopback: bool = False, extra=(), port_factory=None,
                 turn=None, relay_only: bool = False) -> None:
        super().__init__(parent)
        if MISSING:
            raise RuntimeError(f"multiplayer needs {MISSING}")
        self.role = role
        self.name = C.clean_name(name)
        self.stun = list(STUN_SERVERS if stun is None else stun)
        self._stun_given = list(self.stun)
        self.loopback = loopback
        self.extra = list(extra)
        self.port = (port_factory or UdpPort)(self)
        self.port.got.connect(self._got)
        self.conns: dict[int, _Conn] = {}
        self.by_cid: dict[bytes, int] = {}
        self._next = 1
        self.invites: dict[bytes, _Invite] = {}
        self.cands: list = []
        self.verdict: dict = {}
        self._stun_tx: dict[bytes, tuple] = {}
        self._mapped: dict[str, tuple] = {}
        self._gathered = False
        self._after_gather = None
        self.key = self.cert = None
        self.peer_invite: dict | None = None
        self.closed = False
        self.seats = 1
        self.watch = False
        self.latest = None
        self.gone_resume: dict = {}       # cid -> (last address, its invite)
        # A relay of our own: (server, username, password) for a TURN server,
        # or a callable making a TurnClient (tests). Made when this side
        # gathers.
        self.turn_cfg = turn
        self.turn = None
        self.turn_why = ""
        # Relay only: this side's own addresses never leave it -- not in the
        # code, not as the source of anything sent to the other side. Every
        # datagram to a peer goes out through the relay, so all they ever
        # learn is the relay's address. No STUN either: nothing to find out.
        self.relay_only = bool(relay_only and turn)
        if self.relay_only:
            self.stun = []
        self._peer_relays: set = set()    # the other side's relay, from its code
        self.host_relay_only = False      # joiner: the host's relay is the path

        self.punch_timer = QTimer(self)
        self.punch_timer.timeout.connect(self._punch_tick)
        self.keepalive = QTimer(self)
        self.keepalive.timeout.connect(self._ping)
        self.keepalive.start(KEEPALIVE_MS)
        self._closing: list = []
        self._closing_timer = QTimer(self)
        self._closing_timer.timeout.connect(self._flush_closing)

    # -------------------------------------------------------- gathering
    def _gather(self, then) -> None:
        self._after_gather = then
        self.status.emit("asking where this connection is on the internet…")
        self._gather_from = time.monotonic()
        self._start_relay()
        if not self.stun:
            QTimer.singleShot(0, self._gather_done)
            return
        for entry in self.stun:
            host, _, port = entry.rpartition(":")
            try:
                port = int(port)
            except ValueError:
                continue
            QHostInfo.lookupHost(host, lambda info, e=entry, p=port:
                                 self._resolved(e, info, p))
        QTimer.singleShot(int(GATHER_FOR * 1000), self._gather_done)

    def _resolved(self, entry: str, info, port: int) -> None:
        if self.closed:
            return
        v4 = [a for a in info.addresses()
              if a.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol]
        if not v4:
            return
        addr = (_addr(v4[0]), port)
        tx, req = stun_request()
        self._stun_tx[tx] = (entry, addr)
        for ms in (0, 400, 1000):
            QTimer.singleShot(ms, lambda r=req, a=addr: None if self.closed
                              else self._tx(r, a))

    def _gather_done(self) -> None:
        if self._gathered or self.closed:
            return
        if self.turn is not None and self.turn.relayed is None and \
                not self.turn_why and \
                time.monotonic() - self._gather_from < RELAY_WAIT:
            # The relay is still being made: a code without it would
            # be a code a symmetric NAT cannot use.
            QTimer.singleShot(200, self._gather_done)
            return
        self._gathered = True
        seen = list(self._mapped.values())
        cands = local_candidates(self.port.port(), self.port.v6) + list(self.extra)
        if self.loopback:
            cands.insert(0, ("127.0.0.1", self.port.port()))
        public = seen[0] if seen else None
        # Every one, not just the first: a mobile network can show a
        # different public address to each server, and a relay lets in only
        # the addresses the reply names -- which must include the one the
        # relay's own network sees (asked of the host's TURN server: "ts").
        for got in sorted(set(seen), key=seen.index):
            if got not in cands:
                cands.append(got)
        if seen:
            log(f"{self.role}: STUN saw this computer at "
                + ", ".join(f"{a[0]}:{a[1]} ({e})" for e, a in self._mapped.items()))
        sym = None
        if len(seen) >= 2:
            sym = len(set(seen)) > 1
        relayed = self.turn.relayed if self.turn is not None else None
        if self.relay_only:
            if relayed is None:
                # Not quietly direct instead: that would put the very
                # addresses this mode keeps private into the code.
                self.verdict = {"answers": 0, "symmetric": None, "relay": False,
                                "relay_why": self.turn_why or "it did not start",
                                "relay_only": True, "port": self.port.port()}
                self.nat.emit(dict(self.verdict))
                self._after_gather = None
                self.failed.emit(
                    f"the relay did not start ({self.turn_why or 'no answer'}), "
                    "so no code was made — check Relay on the first page, or "
                    "choose Direct, only with people you trust")
                return
            cands = []          # the relay's address alone, added below
        if relayed is not None:
            # Last, and always kept: it is the address that works when no
            # other does.
            self.cands = cands[:MAX_CANDS - 1] + [relayed]
        else:
            self.cands = cands[:MAX_CANDS]
        self.verdict = {"public": public, "answers": len(seen), "symmetric": sym,
                        "v6": any(":" in c[0] for c in self.cands),
                        "port": self.port.port(),
                        "relay": relayed is not None,
                        "relay_why": self.turn_why if self.turn_cfg else "",
                        "relay_only": self.relay_only}
        self.nat.emit(dict(self.verdict))
        then, self._after_gather = self._after_gather, None
        if then:
            then()

    # ------------------------------------------------------------ relay
    def _start_relay(self) -> None:
        if self.turn is not None or not self.turn_cfg:
            return
        try:
            if callable(self.turn_cfg):
                self.turn = self.turn_cfg(self)
            else:
                server, user, password = self.turn_cfg
                self.turn = TURN.TurnClient(server, user, password, self,
                                            local=self.loopback)
        except Exception as exc:                 # noqa: BLE001
            self.turn_why = f"the relay could not start — {exc}"
            self.turn = None
            return
        # Relay only: every peer is behind the relay, so there is nothing to
        # tell apart and the plain address is the one QUIC keeps throughout.
        self.turn.got.connect(lambda d, a: self._got(
            d, (a[0], a[1]) if self.relay_only else ("r:" + a[0], a[1])))
        self.turn.failed.connect(self._relay_failed)

    def _relay_failed(self, why: str) -> None:
        self.turn_why = why
        self.status.emit(f"no relay this time: {why}")

    @staticmethod
    def relayed(addr) -> bool:
        """An address reached through our relay rather than directly: the
        peer's own address, marked "r:" -- so QUIC, the invites and the
        punching can tell the two paths apart while knowing nothing else
        about the relay."""
        return isinstance(addr[0], str) and addr[0].startswith("r:")

    def _tx(self, data: bytes, addr) -> None:
        if self.relay_only:
            # Never from our own address: through the relay, or not at all.
            if self.turn is not None:
                ip = addr[0][2:] if self.relayed(addr) else addr[0]
                self.turn.send(data, (ip, addr[1]))
            return
        if self.relayed(addr):
            if self.turn is not None:
                self.turn.send(data, (addr[0][2:], addr[1]))
            return
        self.port.send(data, addr)

    def _permit(self, targets) -> None:
        """Let the other side's addresses through our relay -- each of them,
        since which one their packets will come from is not known yet."""
        if self.turn is not None:
            self.turn.permit({t[0] for t in targets})

    def _relay_ok(self, since: float, direct: bool) -> bool:
        """Whether to answer through the relay yet: only once a direct path
        has had its chance (RELAY_AFTER) and not been heard."""
        return (self.turn is not None and self.turn.relayed is not None
                and not direct and time.monotonic() - since >= RELAY_AFTER)

    def path(self, cid: int) -> str:
        """"relay" or "direct" for a connection, "" if there is none: shown
        beside each person, so whoever set a relay up can see it in use."""
        conn = self.conns.get(cid)
        if conn is None:
            return ""
        if self.relay_only or self.relayed(conn.addr) \
                or tuple(conn.addr) in self._peer_relays:
            return "relay"
        return "direct"

    def _turn_server(self):
        """Where our TURN server listens (not the relay itself): a joiner
        asks it, like any STUN server, what address it sees them at -- the
        address our relay will see their packets come from."""
        if self.turn is None or self.turn.server is None or self.turn.relayed is None:
            return None
        return list(self.turn.server)

    def _my_relay(self):
        relayed = self.turn.relayed if self.turn is not None else None
        return list(relayed) if relayed else None

    def _their_relay(self, raw) -> None:
        """The other side's relay address, as its code says -- only for
        telling the paths apart."""
        try:
            got = _cands([raw], True) if raw else []
        except BadCode:
            got = []
        self._peer_relays.update(tuple(a) for a in got)

    # ------------------------------------------------------------- host
    def host(self, invite: bool = True) -> None:
        """Start hosting. `invite` False when taking a session over: the
        invites are then one per person moving across (invite_for), made
        once `nat` says this side knows where it is."""
        self.key, self.cert = make_cert()
        self._gather(self.new_invite if invite else None)

    def new_invite(self) -> str:
        inv = _Invite(self.seats, self.watch)
        self.invites[inv.iid] = inv
        self.latest = inv
        code = self._code_for(inv)
        self.status.emit("invite ready — send it, then paste their reply")
        self.code.emit("invite", code)
        return code

    def invite_for(self, who: int) -> str:
        """A one-person invite that brings `who` back as who they were --
        for a session moving to a new host, where everybody comes across
        on one of these, handed to them by the old host."""
        inv = _Invite(1, False)
        inv.resume_of = who
        self.invites[inv.iid] = inv
        return self._code_for(inv)

    def _code_for(self, inv: _Invite) -> str:
        der = self.cert.public_bytes(serialization.Encoding.DER)
        return _pack("i", {"v": C.PROTO, "i": inv.iid.hex(), "k": inv.token.hex(),
                           "c": base64.b64encode(der).decode(),
                           "a": [list(c) for c in self.cands], "n": self.name,
                           "s": self.verdict.get("symmetric"),
                           "r": self._my_relay(), "ts": self._turn_server()})

    def take_reply(self, code: str) -> str:
        """Start punching towards the joiner this reply describes. Returns
        their name, or raises BadCode with something to show."""
        obj = _unpack("r", code)
        iid = _hex(obj.get("i"), 8)
        inv = self.invites.get(iid)
        if inv is None:
            raise BadCode("that reply is for an invite from another session")
        if inv.why_shut():
            raise BadCode(inv.why_shut())
        name = obj.get("n") if isinstance(obj.get("n"), str) else ""
        sym = obj.get("s") if obj.get("s") in (True, False, None) else None
        mac = obj.get("m")
        raw = obj.get("a")
        if not isinstance(mac, str) or not hmac.compare_digest(
                mac, _reply_mac(inv.token, obj["i"], raw, name, sym)):
            raise BadCode("that reply does not belong to this invite")
        reply = {"targets": _cands(raw, self.loopback), "name": C.clean_name(name),
                 "sym": sym, "from": time.monotonic(), "before": inv.joined}
        inv.replies.append(reply)
        self._their_relay(obj.get("r"))
        self._permit(reply["targets"])
        if self.turn is not None:
            reply["let_in"] = sorted({t[0] for t in reply["targets"]
                                      if TURN.TurnClient._permittable(t[0], self.loopback)})
            log(f"host: the relay lets in {reply['name'] or 'the joiner'} from "
                + (", ".join(reply["let_in"]) or "no address at all — their "
                   "reply had no public IPv4"))
        if not self.punch_timer.isActive():
            self.punch_timer.start(PUNCH_MS)
        self.status.emit(f"reaching {reply['name']}…")
        QTimer.singleShot(int(PUNCH_FOR * 1000) + 500,
                          lambda i=inv, r=reply: self._gave_up(i, r))
        return reply["name"]

    # ------------------------------------------------------- coming back
    def make_resume(self, cid: int) -> tuple[str, str]:
        """Host: a one-person invite for this joiner alone, to come back
        with if the connection drops. Handed to them over the encrypted
        session, never shown -- nobody else ever has it."""
        inv = _Invite(1, False)
        inv.resume_of = cid
        self.invites[inv.iid] = inv
        conn = self.conns.get(cid)
        if conn is not None:
            conn.resume = inv
        return inv.iid.hex(), inv.token.hex()

    def reopen(self, conn_addr, inv: _Invite) -> None:
        """Host: a joiner dropped. Keep their way back open from now, and
        knock at where they last were while they knock here."""
        inv.made = time.monotonic()
        inv.replies.append({"targets": [conn_addr], "name": "", "sym": None,
                            "from": time.monotonic(), "before": inv.joined})
        if not self.punch_timer.isActive():
            self.punch_timer.start(PUNCH_MS)

    def resume(self, iid_hex: str, token_hex: str) -> None:
        """Joiner: knock again, with the resume invite, at the host's same
        addresses, under the same pinned certificate."""
        p = self.peer_invite
        if p is None:
            return
        p["iid"] = _hex(iid_hex, 8)
        p["token"] = _hex(token_hex, 16)
        p["heard"] = set()
        p["from"] = time.monotonic()
        p["ticks"] = 0
        self.punch_timer.start(PUNCH_MS)
        self._attempt = getattr(self, "_attempt", 0) + 1
        QTimer.singleShot(int(JOIN_WAIT * 1000),
                          lambda a=self._attempt: self._join_gave_up(a))

    def set_seats(self, n: int) -> None:
        """How many the newest invite lets in, changed after it was made --
        the code itself does not change, since it never said."""
        self.seats = max(1, min(C.MAX_PEERS, int(n)))
        if getattr(self, "latest", None) is not None:
            self.latest.seats = self.seats

    def set_watch(self, on: bool) -> None:
        """Whether the newest invite brings people in to watch only. Like
        the number of places, the host's to say and not the code's."""
        self.watch = bool(on)
        if getattr(self, "latest", None) is not None:
            self.latest.watch = self.watch

    def invite_state(self) -> tuple[int, int, str]:
        """(joined, seats, why shut) for the newest invite."""
        inv = getattr(self, "latest", None)
        if inv is None:
            return 0, self.seats, ""
        return inv.joined, inv.seats, inv.why_shut()

    def _gave_up(self, inv: _Invite, reply: dict) -> None:
        if self.closed or inv.joined > reply["before"]:
            return
        why = self._why_not(bool(inv.heard), reply.get("sym"))
        if self.turn is not None and not inv.heard:
            why += (". The relay was letting in " + (", ".join(reply.get("let_in") or [])
                    or "no address — their reply named no public IPv4")
                    + "; if their network shows the relay another address, "
                    "nothing of theirs gets through")
        log(f"host: gave up — {why}")
        self.failed.emit(why)

    # ------------------------------------------------------------ joiner
    def join(self, code: str) -> None:
        """Read an invite and start making the reply. Raises BadCode."""
        obj = _unpack("i", code)
        iid = _hex(obj.get("i"), 8)
        token = _hex(obj.get("k"), 16)
        try:
            der = base64.b64decode(obj.get("c") or "", validate=True)
            if len(der) > 2048:
                raise ValueError
            cert = x509.load_der_x509_certificate(der)
            if not isinstance(cert.public_key(), ed25519.Ed25519PublicKey):
                raise ValueError
        except Exception:                        # noqa: BLE001
            raise BadCode("that invite's certificate is damaged") from None
        sym = obj.get("s") if obj.get("s") in (True, False, None) else None
        self.peer_invite = {"iid": iid, "token": token, "cert": cert,
                            "targets": _cands(obj.get("a"), self.loopback),
                            "name": C.clean_name(obj.get("n")), "sym": sym,
                            "heard": set(), "from": 0.0}
        self._their_relay(obj.get("r"))
        try:
            ts = _cands([obj.get("ts")], self.loopback) if obj.get("ts") else []
        except BadCode:
            ts = []
        if self.relay_only and obj.get("r"):
            # The host has a relay: that one carries the session. Ours would
            # make it relay to relay, which a TURN service will not carry
            # between its own allocations -- measured on ExpressTURN, where
            # it sat silent until "no answer". So ours stands down, and our
            # reply (to the host alone, never posted) carries our address.
            self.relay_only = False
            self.turn_cfg = None
            self.stun = list(self._stun_given)
            self.host_relay_only = True
        if ts and not self.relay_only:
            # The host's relay lets in our address as ITS network sees it:
            # ask its server, as a STUN server, alongside the others.
            entry = f"{ts[0][0]}:{ts[0][1]}"
            if entry not in self.stun:
                self.stun.append(entry)
        self._gather(self._reply)
        self._permit(self.peer_invite["targets"])

    def host_name(self) -> str:
        return (self.peer_invite or {}).get("name", "")

    def _reply(self) -> None:
        p = self.peer_invite
        cands = [list(c) for c in self.cands]
        sym = self.verdict.get("symmetric")
        code = _pack("r", {"v": C.PROTO, "i": p["iid"].hex(), "a": cands,
                           "n": self.name, "s": sym, "r": self._my_relay(),
                           "m": _reply_mac(p["token"], p["iid"].hex(), cands,
                                           self.name, sym)})
        self.code.emit("reply", code)
        self.status.emit(f"send the reply to {p['name']} — connecting as soon "
                         "as they paste it")
        p["from"] = time.monotonic()
        self.punch_timer.start(PUNCH_MS)
        # The host may take a while to paste: punch for as long as an invite
        # lives, not just PUNCH_FOR after the reply was made.
        self._attempt = getattr(self, "_attempt", 0) + 1
        QTimer.singleShot(int(JOIN_WAIT * 1000),
                          lambda a=self._attempt: self._join_gave_up(a))

    def _join_gave_up(self, attempt: int = 0) -> None:
        if attempt and attempt != getattr(self, "_attempt", 0):
            return                      # an earlier try's clock, not this one's
        if not self.closed and not self.conns:
            p = self.peer_invite or {}
            self.failed.emit(self._why_not(bool(p.get("heard")), p.get("sym")))

    def _why_not(self, heard: bool, theirs) -> str:
        mine = self.verdict.get("symmetric")
        if self.verdict.get("relay"):
            return ("no answer, even through the relay — check the other "
                    "window is still open and the code was the latest; on "
                    "Windows, the firewall must let Python in")
        if heard:
            return ("the two editors heard each other but could not finish "
                    "connecting — try again, and if it repeats, a firewall "
                    "is in the way")
        relay = ("A relay (a TURN server, e.g. a free ExpressTURN account) in "
                 "Multiplayer's first page, on the hosting side, connects anyone"
                 + (f" (this time the relay failed: {self.verdict['relay_why']})"
                    if self.verdict.get("relay_why") else "") + ".")
        if mine and theirs:
            return ("both connections give a new port for every destination "
                    "(symmetric NAT), which nothing can punch through. " + relay)
        if mine or theirs:
            who = "yours" if mine else "theirs"
            return (f"no answer — {who} is a connection that gives a new port "
                    "for every destination (symmetric NAT). It works against "
                    "some routers and not others. " + relay)
        if not self.verdict.get("answers"):
            return ("no answer, and the STUN servers did not answer either, so "
                    "UDP may be blocked on this network (or, on Windows, by the "
                    "firewall prompt for Python)")
        return ("no answer from the other side. Check both windows are still "
                "open; on Windows, the firewall must let Python in")

    # ---------------------------------------------------------- punching
    def _punch_tick(self) -> None:
        if self.closed:
            self.punch_timer.stop()
            return
        now = time.monotonic()
        busy = False
        if self.role == "host":
            for inv in self.invites.values():
                if inv.why_shut():
                    continue
                for reply in inv.replies:
                    if now - reply["from"] > PUNCH_FOR + RELAY_AFTER \
                            or reply.get("in"):
                        continue
                    busy = True
                    for t in reply["targets"]:
                        self._tx(_punch(b"H", inv.iid, inv.token), t)
                    if self._relay_ok(reply["from"], reply.get("direct")):
                        # Through the relay: to where they said they are,
                        # and to wherever they were heard knocking from.
                        ips = {t[0] for t in reply["targets"]}
                        for t in reply["targets"]:
                            self._tx(_punch(b"H", inv.iid, inv.token),
                                     ("r:" + t[0], t[1]))
                        for a in inv.heard:
                            if self.relayed(a) and a[0][2:] in ips:
                                self._tx(_punch(b"H", inv.iid, inv.token), a)
        else:
            p = self.peer_invite
            if p and not self.conns and now - p["from"] < JOIN_WAIT:
                busy = True
                # Fast while the host is likely to be punching back, then
                # once a second: a router's opening lasts far longer, and
                # the host may take minutes to paste the reply.
                p["ticks"] = p.get("ticks", 0) + 1
                if now - p["from"] < PUNCH_FOR or p["ticks"] % 10 == 0:
                    for t in p["targets"]:
                        self._tx(_punch(b"J", p["iid"], p["token"]), t)
                    if self._relay_ok(p["from"], p.get("direct")):
                        for t in p["targets"]:
                            self._tx(_punch(b"J", p["iid"], p["token"]),
                                     ("r:" + t[0], t[1]))
        if not busy:
            self.punch_timer.stop()

    # ---------------------------------------------------------- datagrams
    def _got(self, data: bytes, addr) -> None:
        """Every datagram. A slot that raises aborts the editor, so nothing
        a datagram can cause is allowed out of here."""
        if self.closed or not data:
            return
        try:
            self._sort(data, addr)
        except Exception:                        # noqa: BLE001
            traceback.print_exc()

    def _sort(self, data: bytes, addr) -> None:
        if data[:4] == PUNCH:
            self._punched(data, addr)
        elif len(data) >= 20 and data[0] == 0x01 and \
                data[4:8] == struct.pack("!I", STUN_MAGIC):
            self._stun_answer(data, addr)
        elif data[0] & 0x40:
            self._quic(data, addr)

    def _stun_answer(self, data: bytes, addr) -> None:
        tx = data[8:20]
        asked = self._stun_tx.get(tx)
        if asked is None or asked[1] != addr:
            return
        got = stun_parse(data, tx)
        if got:
            self._mapped[asked[0]] = got

    def _punched(self, data: bytes, addr) -> None:
        if self.role == "host":
            inv = self.invites.get(data[5:13])
            if inv is None or inv.why_shut() or not _punch_ok(
                    data, b"J", inv.iid, inv.token):
                return
            via = self.relayed(addr)
            ip = addr[0][2:] if via else addr[0]
            mine = [r for r in inv.replies if ip in {t[0] for t in r["targets"]}]
            if not via:
                for r in mine:
                    r["direct"] = True
            if addr not in inv.heard:
                inv.heard.add(addr)
                if via or self.relay_only:
                    log(f"host: heard a joiner through the relay, from "
                        f"{ip}:{addr[1]}")
                if via:
                    pass            # their reply is what lets them through
                elif not any(addr in r["targets"] for r in inv.replies):
                    # Their router picked a port STUN did not see -- or they
                    # came straight here without a reply at all: answer where
                    # they actually are, for as long as a reply would get.
                    inv.replies.append({"targets": [addr], "name": "",
                                        "sym": None, "from": time.monotonic(),
                                        "before": inv.joined})
                    if not self.punch_timer.isActive():
                        self.punch_timer.start(PUNCH_MS)
            if via and not any(self._relay_ok(r["from"], r.get("direct"))
                               for r in mine):
                return              # direct still has its chance; the tick answers
            self._tx(_punch(b"H", inv.iid, inv.token), addr)
        else:
            p = self.peer_invite
            if not p or not _punch_ok(data, b"H", p["iid"], p["token"]):
                return
            p["heard"].add(addr)
            if self.relayed(addr):
                if not self._relay_ok(p["from"], p.get("direct")):
                    return          # direct still has its chance
            else:
                p["direct"] = True
            self._tx(_punch(b"J", p["iid"], p["token"]), addr)
            if not self.conns:
                self._dial(addr)

    # --------------------------------------------------------------- QUIC
    def _dial(self, addr) -> None:
        p = self.peer_invite
        cfg = QuicConfiguration(is_client=True, alpn_protocols=[ALPN],
                                server_name=SNI, verify_mode=ssl.CERT_REQUIRED,
                                idle_timeout=IDLE)
        cfg.cadata = p["cert"].public_bytes(serialization.Encoding.PEM)
        quic = QuicConnection(configuration=cfg)
        quic.connect(addr, now=time.monotonic())
        conn = self._adopt(quic, addr)
        conn.stream = quic.get_next_available_stream_id()
        self.status.emit(f"found {p['name']} — checking it is really them…")
        self._pump(conn)

    def _adopt(self, quic, addr, invite=None) -> _Conn:
        cid = self._next
        self._next += 1
        conn = _Conn(cid, quic, addr, invite)
        conn.timer.timeout.connect(lambda c=conn: self._timer(c))
        self.conns[cid] = conn
        return conn

    def _quic(self, data: bytes, addr) -> None:
        if self.role == "member":
            for conn in list(self.conns.values()):
                if conn.cid not in self.conns:
                    continue
                conn.quic.receive_datagram(data, addr, now=time.monotonic())
                self._pump(conn)
            return
        try:
            head = pull_quic_header(Buffer(data=data), host_cid_length=8)
        except Exception:                        # noqa: BLE001
            return
        cid = self.by_cid.get(head.destination_cid)
        if cid is None:
            # A new connection: only an Initial, only full size, and only from
            # an address that has already proved it holds an invite's token.
            if head.packet_type is None or len(data) < 1200 \
                    or getattr(head.packet_type, "name", "") != "INITIAL":
                return
            inv = next((i for i in self.invites.values()
                        if addr in i.heard and not i.why_shut()), None)
            if inv is None or len(self.conns) >= C.MAX_PEERS:
                return
            cfg = QuicConfiguration(is_client=False, alpn_protocols=[ALPN],
                                    idle_timeout=IDLE)
            cfg.certificate, cfg.private_key = self.cert, self.key
            quic = QuicConnection(
                configuration=cfg,
                original_destination_connection_id=head.destination_cid)
            conn = self._adopt(quic, addr, inv)
            self.by_cid[head.destination_cid] = conn.cid
            self.by_cid[quic.host_cid] = conn.cid
            cid = conn.cid
        conn = self.conns.get(cid)
        if conn is None:
            return
        conn.quic.receive_datagram(data, addr, now=time.monotonic())
        self._pump(conn)

    def _timer(self, conn: _Conn) -> None:
        if conn.cid not in self.conns:
            return
        conn.quic.handle_timer(now=time.monotonic())
        self._pump(conn)

    def _pump(self, conn: _Conn) -> None:
        """Send what QUIC wants sent, handle what it has to say, and set the
        clock for when it next needs a word."""
        now = time.monotonic()
        for data, addr in conn.quic.datagrams_to_send(now=now):
            self._tx(data, addr)
        while True:
            ev = conn.quic.next_event()
            if ev is None:
                break
            if not self._event(conn, ev):
                return
        for data, addr in conn.quic.datagrams_to_send(now=now):
            self._tx(data, addr)
        when = conn.quic.get_timer()
        if when is None:
            conn.timer.stop()
        else:
            conn.timer.start(max(0, int((when - now) * 1000) + 1))

    def _event(self, conn: _Conn, ev) -> bool:
        if isinstance(ev, QE.ConnectionIdIssued):
            self.by_cid[ev.connection_id] = conn.cid
        elif isinstance(ev, QE.ConnectionIdRetired):
            self.by_cid.pop(ev.connection_id, None)
        elif isinstance(ev, QE.HandshakeCompleted):
            if self.role == "member":
                conn.ready = True
                self._write(conn, self._hello_msg())
                self.punch_timer.stop()
                self.connected.emit()
        elif isinstance(ev, QE.StreamDataReceived):
            if ev.stream_id != conn.stream:
                return True             # one stream is all this protocol has
            conn.buf += ev.data
            return self._frames(conn)
        elif isinstance(ev, QE.ConnectionTerminated):
            self._gone(conn, ev.reason_phrase or "the connection closed")
            return False
        return True

    def _hello_msg(self) -> dict:
        return {"t": "hello", "proto": C.PROTO,
                "token": self.peer_invite["token"].hex(), "name": self.name}

    def _frames(self, conn: _Conn) -> bool:
        while len(conn.buf) >= 4:
            n = struct.unpack("!I", conn.buf[:4])[0]
            if n > MAX_FRAME:
                self.drop(conn.cid, "sent a message far too large")
                return False
            if len(conn.buf) < 4 + n:
                if len(conn.buf) > MAX_FRAME + 4:
                    self.drop(conn.cid, "sent too much")
                    return False
                break
            raw, conn.buf = conn.buf[4:4 + n], conn.buf[4 + n:]
            now = time.monotonic()
            if now - conn.window_at > 1.0:
                conn.window_at, conn.window_n = now, 0
            conn.window_n += 1
            if conn.window_n > MAX_RATE:
                self.drop(conn.cid, "sent too many messages")
                return False
            try:
                msg = json.loads(raw.decode("utf-8"))
            except (ValueError, RecursionError, UnicodeDecodeError):
                self.drop(conn.cid, "sent something that is not a message")
                return False
            if not conn.ready:
                if not self._hello(conn, msg):
                    return False
                continue
            self.message.emit(conn.cid, msg)
            if conn.cid not in self.conns:
                return False
        return True

    def _hello(self, conn: _Conn, msg) -> bool:
        """The host's door: the token from an invite, or nothing.

        Which invite is settled HERE, by the token, not by which one first
        heard this address: one person can be heard on two -- the invite
        they came in on, still with places left, and the resume invite they
        are coming back on -- and taking the first of those turned a
        returning joiner away for not having its token.
        """
        token = msg.get("token") if isinstance(msg, dict) else None
        inv = None
        if isinstance(token, str):
            for cand in self.invites.values():
                if conn.addr in cand.heard and hmac.compare_digest(
                        token, cand.token.hex()):
                    inv = cand
                    break
        if inv is None:
            inv = conn.invite              # charge the failure to this one
            good = False
        else:
            conn.invite = inv
            good = msg.get("t") == "hello" and msg.get("proto") == C.PROTO
        if not good:
            if inv is not None:
                inv.fails += 1
                if inv.fails >= TOKEN_TRIES:
                    inv.burnt = True         # make another
            proto = msg.get("proto") if isinstance(msg, dict) else None
            self.drop(conn.cid, "is a different version of the editor"
                      if isinstance(proto, int) and proto != C.PROTO
                      else "did not have the invite's token")
            return False
        # Counted here, at the door, and nowhere earlier: two joiners racing
        # for the last place both get this far, and only one goes through.
        shut = inv.why_shut()
        if shut:
            self.drop(conn.cid, "the invite is full or out of date — ask "
                      "the host for another")
            return False
        inv.joined += 1
        conn.ready = True
        # What the invite allows, said by the host's own record of it --
        # written over anything the joiner's hello claimed.
        msg = dict(msg)
        msg["_watch"] = inv.watch
        msg["_resume"] = inv.resume_of
        # They are in: stop knocking at every address they could be at. Left
        # running, twenty seconds of punches at ten a second per address
        # piled up unread behind the session and filled their socket's
        # buffer, until the operating system dropped what came after --
        # the host's "session ended" among it.
        ip = conn.addr[0][2:] if self.relayed(conn.addr) else conn.addr[0]
        for reply in inv.replies:
            if conn.addr in reply["targets"] or any(
                    a in inv.heard and a[0] == conn.addr[0]
                    for a in reply["targets"]) or (
                    self.relayed(conn.addr)
                    and ip in {t[0] for t in reply["targets"]}):
                reply["in"] = True
        self.joined.emit(conn.cid, msg)
        return True

    # ------------------------------------------------------------ sending
    def _write(self, conn: _Conn, msg: dict) -> None:
        raw = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode()
        if len(raw) > MAX_FRAME:
            return
        conn.quic.send_stream_data(conn.stream, struct.pack("!I", len(raw)) + raw)
        self._pump(conn)

    def send(self, cid: int | None, msg: dict) -> None:
        """To one peer, or with cid None to every peer that is in."""
        for conn in list(self.conns.values()):
            if (cid is None or conn.cid == cid) and conn.ready:
                self._write(conn, msg)

    def _ping(self) -> None:
        for conn in list(self.conns.values()):
            conn.quic.send_ping(int(time.monotonic()))
            self._pump(conn)

    def drop(self, cid: int, why: str) -> None:
        conn = self.conns.get(cid)
        if conn is None:
            return
        conn.quic.close(error_code=0, reason_phrase=why[:100])
        self._send_all(conn)
        self._gone(conn, why)
        # QUIC paces what it sends: the goodbye -- and whatever message went
        # just before it -- can still be waiting a few milliseconds on. Keep
        # sending for this connection a little longer, or the other side
        # only finds out at the idle timeout, 45 seconds later.
        self._closing.append((conn, time.monotonic() + 1.0))
        if not self._closing_timer.isActive():
            self._closing_timer.start(15)

    def _send_all(self, conn: _Conn) -> None:
        for data, addr in conn.quic.datagrams_to_send(now=time.monotonic()):
            self._tx(data, addr)

    def _flush_closing(self) -> None:
        now = time.monotonic()
        keep = []
        for conn, until in self._closing:
            if self.closed:
                break
            self._send_all(conn)
            if now < until:
                keep.append((conn, until))
        self._closing = keep
        if not keep:
            self._closing_timer.stop()

    def _gone(self, conn: _Conn, why: str) -> None:
        if self.conns.pop(conn.cid, None) is None:
            return
        self.last_addr = conn.addr
        if self.role == "host" and getattr(conn, "resume", None) is not None:
            self.gone_resume[conn.cid] = (conn.addr, conn.resume)
        conn.timer.stop()
        for k in [k for k, v in self.by_cid.items() if v == conn.cid]:
            del self.by_cid[k]
        self.left.emit(conn.cid, why)

    def close(self) -> None:
        """End everything and let the port go. Safe to call twice.

        Blocks for at most a quarter of a second, on purpose: the last
        message sent -- "the session ended" -- and the close after it are
        paced, and a port closed at once loses them. A joiner told nothing
        sits in a dead session until the idle timeout. This also runs on the
        way out of the window, where there is no event loop left to wait in.
        """
        if self.closed:
            return
        live = list(self.conns.values())
        end = time.monotonic() + 0.15
        while live and time.monotonic() < end:         # what was already said
            for conn in live:
                self._send_all(conn)
            time.sleep(0.01)
        for cid in list(self.conns):
            self.drop(cid, "left")
        closing = [c for c, _u in self._closing]
        end = time.monotonic() + 0.1
        while closing and time.monotonic() < end:      # and the goodbye
            for conn in closing:
                self._send_all(conn)
            time.sleep(0.01)
        self.closed = True
        self._closing = []
        self._closing_timer.stop()
        self.punch_timer.stop()
        self.keepalive.stop()
        if self.turn is not None:
            self.turn.close()
        self.port.close()
