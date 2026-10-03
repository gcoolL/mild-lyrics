"""A relay for when two editors cannot reach each other directly.

Hole punching (collab_net) connects most pairs. It cannot connect a joiner
behind a "symmetric" NAT -- some mobile networks, campus and carrier-grade
NAT -- to a host whose router is fussy about who may answer, and nothing
connects two such networks to each other without something in the middle.
This is the something: a TURN allocation (RFC 8656) on a TURN server of the
host's choosing -- a free account at ExpressTURN or Metered's Open Relay, or
a coturn of their own -- with the username and password it gives, kept in
the host's settings. Nothing is shipped in the app.

ONLY ONE SIDE NEEDS ONE. A TURN server forwards to the allocation's owner
whatever arrives at the relayed address from an IP the owner has given
permission to, and forwards the owner's own sends out from that address. So
the host puts its relayed address among the invite's candidates, permits the
IPs the joiner's reply lists, and a joiner on any network reaches it by
sending plain UDP at the relay's address -- which no NAT stops.

WHAT THE RELAY SEES. Ciphertext. The session is QUIC, encrypted end to end
and authenticated against the certificate pinned by the invite (collab_net);
the relay carries those datagrams and can read none of them. It does see
both public IP addresses and how much was sent.

WHEN IT IS USED. Last. collab_net only answers through the relay once a
direct path has had RELAY_AFTER seconds to answer and has not, so pairs that
can connect directly still do, and the relay costs nothing for them.

Runs on Qt's loop like the rest, on its own UDP socket, so nothing the
relay sends can be mistaken for a punch or QUIC on the session's socket.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import struct
import sys
import time
import zlib

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QAbstractSocket, QHostAddress, QHostInfo, QUdpSocket

PORT = 3478                      # TURN's own port, where none is given

MAGIC = 0x2112A442
# methods, already shifted into the class bits they are sent and answered in
BINDING, BINDING_OK = 0x0001, 0x0101
ALLOCATE, REFRESH, CREATE_PERMISSION = 0x0003, 0x0004, 0x0008
SEND_IND, DATA_IND = 0x0016, 0x0017
OK, ERR = 0x0100, 0x0110
# attributes
USERNAME, INTEGRITY, ERROR_CODE, LIFETIME = 0x0006, 0x0008, 0x0009, 0x000D
PEER, DATA, REALM, NONCE, RELAYED = 0x0012, 0x0013, 0x0014, 0x0015, 0x0016
TRANSPORT, MAPPED, SOFTWARE, FINGERPRINT = 0x0019, 0x0020, 0x8022, 0x8028

LIFETIME_S = 600                 # what is asked for; refreshed at half of it
PERMIT_EVERY = 240               # permissions last 300s
RETRY_MS = (0, 500, 1500, 3500)  # a request is sent again until answered
ALLOC_WAIT = 8.0
# A home router forgets an idle UDP mapping in tens of seconds, and refreshes
# come minutes apart. Once it has, the next packet leaves from a new port, the
# server knows no allocation there (437), and whatever the relay forwards is
# dropped at the router -- the host's relay died every two minutes on
# 2026-10-03 while invites waited. So the server hears from us this often.
KEEPALIVE_S = 15


def log(text: str) -> None:
    """As collab_net's: one line to the terminal. Never an address."""
    print(f"[multiplayer] relay: {text}", file=sys.stderr, flush=True)


# ------------------------------------------------------------- messages
def _attr(kind: int, value: bytes) -> bytes:
    return struct.pack("!HH", kind, len(value)) + value + b"\0" * (-len(value) % 4)


def _xaddr(ip: str, port: int, tx: bytes) -> bytes:
    """An XOR-…-ADDRESS value."""
    a = ipaddress.ip_address(ip)
    xp = port ^ (MAGIC >> 16)
    if a.version == 4:
        raw = bytes(x ^ y for x, y in zip(a.packed, struct.pack("!I", MAGIC)))
        return struct.pack("!BBH", 0, 1, xp) + raw
    mask = struct.pack("!I", MAGIC) + tx
    return struct.pack("!BBH", 0, 2, xp) + bytes(x ^ y for x, y in zip(a.packed, mask))


def _unxaddr(val: bytes, tx: bytes):
    if len(val) < 8:
        return None
    fam, xp = val[1], struct.unpack("!H", val[2:4])[0]
    port = xp ^ (MAGIC >> 16)
    if fam == 1 and len(val) >= 8:
        raw = bytes(x ^ y for x, y in zip(val[4:8], struct.pack("!I", MAGIC)))
        return str(ipaddress.IPv4Address(raw)), port
    if fam == 2 and len(val) >= 20:
        mask = struct.pack("!I", MAGIC) + tx
        raw = bytes(x ^ y for x, y in zip(val[4:20], mask))
        return str(ipaddress.IPv6Address(raw)), port
    return None


def build(kind: int, tx: bytes, attrs: list, key: bytes | None = None,
          fingerprint: bool = True) -> bytes:
    """A STUN/TURN message; signed with MESSAGE-INTEGRITY when `key` is given,
    then FINGERPRINT. Both are computed over the header with its length
    already counting themselves, as RFC 8489 has it."""
    body = b"".join(_attr(k, v) for k, v in attrs)
    if key is not None:
        head = struct.pack("!HHI12s", kind, len(body) + 24, MAGIC, tx)
        mac = hmac.new(key, head + body, hashlib.sha1).digest()
        body += _attr(INTEGRITY, mac)
    if fingerprint:
        head = struct.pack("!HHI12s", kind, len(body) + 8, MAGIC, tx)
        crc = (zlib.crc32(head + body) ^ 0x5354554E) & 0xFFFFFFFF
        body += _attr(FINGERPRINT, struct.pack("!I", crc))
    return struct.pack("!HHI12s", kind, len(body), MAGIC, tx) + body


def parse(data: bytes):
    """(type, transaction id, {attribute: value}) or None. Every length is
    checked before it is read; the first of a repeated attribute counts."""
    if len(data) < 20:
        return None
    kind, length, magic, tx = struct.unpack("!HHI12s", data[:20])
    if magic != MAGIC or kind & 0xC000 or length % 4 or 20 + length > len(data):
        return None
    attrs, off, end = {}, 20, 20 + length
    while off + 4 <= end:
        at, alen = struct.unpack("!HH", data[off:off + 4])
        val = data[off + 4:off + 4 + alen]
        if len(val) != alen or off + 4 + alen > end:
            return None
        attrs.setdefault(at, val)
        off += 4 + alen + (-alen % 4)
    return kind, tx, attrs


def long_term_key(username: str, realm: str, password: str) -> bytes:
    return hashlib.md5(f"{username}:{realm}:{password}".encode()).digest()


def error_of(attrs: dict) -> tuple[int, str]:
    val = attrs.get(ERROR_CODE, b"")
    if len(val) < 4:
        return 0, ""
    # Some servers end the reason with a newline or NULs: one log line each.
    return (val[2] & 7) * 100 + val[3], \
        val[4:].decode("utf-8", "replace").strip("\0 \r\n\t")


# ---------------------------------------------------------------- server
def server_of(text: str) -> tuple[str, int] | None:
    """(host, port) from what a provider shows: "relay1.expressturn.com:3478",
    "turn:openrelay.metered.ca:80?transport=udp", or a bare host. Only UDP:
    TURN over TCP or TLS would need a stream socket this module does not
    have, so a "turns:" or "transport=tcp" address is refused, not misused."""
    text = str(text or "").strip()
    if not text or text.startswith("turns:") or "transport=tcp" in text:
        return None
    text = text.removeprefix("turn:").split("?")[0].strip("/")
    host, sep, port = text.rpartition(":")
    if not sep or host.endswith(":") or "]" in port:   # bare host, or bare IPv6
        host, port = text, ""
    host = host.strip("[]")
    if not host or (port and not port.isdigit()):
        return None
    port = int(port) if port else PORT
    return (host, port) if 0 < port < 65536 else None


# ----------------------------------------------------------------- client
class TurnClient(QObject):
    """One allocation on one TURN server, for one session.

    `ready(relayed address)` once allocated; `failed(why)` if it never is.
    `got(data, peer address)` for every datagram a permitted peer sent to
    the relayed address. `send(data, peer)` sends from it.
    """

    ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    # The allocation is gone after it was made: a refresh refused or not
    # answered. Its relayed address carries nothing any more.
    lost = pyqtSignal(str)
    got = pyqtSignal(bytes, object)

    def __init__(self, server: str, user: str, password: str, parent=None, *,
                 local: bool = False) -> None:
        super().__init__(parent)
        self.local = local          # a test's server on this machine: permit LAN IPs
        self.closed = False
        self.relayed = None
        self.mapped = None          # where the server sees our socket, at allocation
        self.server = None          # (ip, port), resolved
        self.user, self.password = str(user or ""), str(password or "")
        self.realm = self.nonce = b""
        self.key = None
        self.pending: dict[bytes, dict] = {}
        self.permitted: set = set()
        self.refused: set = set()   # the server will not let these in; not asked again
        self._asking: set = set()   # a permission request for these is out
        self._permit_queue: set = set()
        self._binds: dict[bytes, float] = {}
        self.sock = QUdpSocket(self)
        if not self.sock.bind(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), 0):
            raise OSError(self.sock.errorString())
        self.sock.readyRead.connect(self._read)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh)
        self.permit_timer = QTimer(self)
        self.permit_timer.timeout.connect(self._repermit)
        self.keep_timer = QTimer(self)
        self.keep_timer.timeout.connect(self._keepalive)
        where = server_of(server)
        if where is None:
            QTimer.singleShot(0, lambda: self._fail(
                "the relay's address is not a TURN server over UDP "
                "(host:port, e.g. relay1.expressturn.com:3478)"))
        else:
            QTimer.singleShot(0, lambda: self._lookup(*where))
        QTimer.singleShot(int(ALLOC_WAIT * 1000), self._too_slow)

    def _lookup(self, host: str, port: int) -> None:
        try:
            ipaddress.ip_address(host)
            self._resolved(port, [host])
            return
        except ValueError:
            pass
        QHostInfo.lookupHost(host, lambda info, p=port: self._resolved(
            p, [a.toString() for a in info.addresses()
                if a.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol]))

    def _resolved(self, port: int, ips: list) -> None:
        if self.closed:
            return
        if not ips:
            self._fail("the TURN server's name did not resolve")
            return
        self.server = (ips[0], port)
        self._request(ALLOCATE, [(TRANSPORT, struct.pack("!BBBB", 17, 0, 0, 0)),
                                 (LIFETIME, struct.pack("!I", LIFETIME_S))])

    # -- requests
    def _request(self, method: int, attrs: list, then=None, tries: int = 0) -> bytes:
        tx = os.urandom(12)
        self.pending[tx] = {"method": method, "attrs": attrs, "then": then,
                            "tries": tries}
        self._send_request(tx)
        return tx

    def _send_request(self, tx: bytes) -> None:
        job = self.pending.get(tx)
        if job is None or self.closed or self.server is None:
            return
        attrs = list(job["attrs"])
        key = None
        if self.realm:
            attrs += [(USERNAME, self.user.encode()), (REALM, self.realm),
                      (NONCE, self.nonce)]
            key = self.key
        msg = build(job["method"], tx, attrs, key)
        for ms in RETRY_MS:
            QTimer.singleShot(ms, lambda m=msg, t=tx: self._resend(t, m))
        if job["method"] != ALLOCATE:          # _too_slow covers that one
            QTimer.singleShot(int(ALLOC_WAIT * 1000), lambda t=tx: self._unanswered(t))

    def _unanswered(self, tx: bytes) -> None:
        job = self.pending.pop(tx, None)
        if job is None or self.closed:
            return
        if job["method"] == REFRESH:
            self._lose("the TURN server stopped answering")
        else:
            self._asking.discard(job.get("ip"))
            log("a permission request went unanswered")

    def _resend(self, tx: bytes, msg: bytes) -> None:
        if tx in self.pending and not self.closed:
            self.sock.writeDatagram(msg, QHostAddress(self.server[0]), self.server[1])

    def _read(self) -> None:
        while self.sock.state() == QAbstractSocket.SocketState.BoundState \
                and self.sock.hasPendingDatagrams():
            dg = self.sock.receiveDatagram(65536)
            if not dg.isValid() or self.server is None:
                continue
            frm = (dg.senderAddress().toString().split("%")[0].removeprefix("::ffff:"),
                   int(dg.senderPort()))
            if frm != self.server:
                continue            # only the TURN server talks to this socket
            try:
                self._answer(bytes(dg.data()))
            except Exception:                        # noqa: BLE001
                import traceback
                traceback.print_exc()

    def _answer(self, data: bytes) -> None:
        got = parse(data)
        if got is None:
            return
        kind, tx, attrs = got
        if kind == BINDING_OK:
            self._bound(tx, attrs)
            return
        if kind == DATA_IND:
            peer = _unxaddr(attrs.get(PEER, b""), tx)
            if peer is not None and DATA in attrs:
                self.got.emit(attrs[DATA], peer)
            return
        job = self.pending.get(tx)
        if job is None or kind & 0x3EEF != job["method"]:
            return
        if kind & 0x0110 == ERR:
            code, why = error_of(attrs)
            if code in (401, 438) and REALM in attrs and NONCE in attrs \
                    and job["tries"] < 2:
                # The first ask is always 401 (here are the realm and nonce);
                # 438 is a nonce gone stale. Either way: sign and ask again.
                self.realm, self.nonce = attrs[REALM], attrs[NONCE]
                self.key = long_term_key(self.user, self.realm.decode("utf-8", "replace"),
                                         self.password)
                del self.pending[tx]
                again = self._request(job["method"], job["attrs"], job["then"],
                                      tries=job["tries"] + 1)
                if "ip" in job:
                    self.pending[again]["ip"] = job["ip"]
                return
            del self.pending[tx]
            if job["method"] == ALLOCATE:
                self._fail(("the relay refused the username or password"
                            if code == 401 else
                            f"the relay refused: {code} {why}").strip())
            elif job["method"] == REFRESH or code == 437:
                # 437: the server no longer has this allocation at all.
                self._lose(f"the TURN server dropped it ({code} {why})".strip())
            else:
                # One address, refused on its own (permit asks one at a
                # time): a forbidden one no longer keeps the others out.
                ip = job.get("ip")
                self._asking.discard(ip)
                if ip is not None:
                    self.refused.add(ip)
                    self.permitted.discard(ip)
                log(f"one address was refused ({code} {why}); "
                    f"{len(self.permitted)} let in".strip())
            return
        if kind & 0x0110 != OK:
            return
        del self.pending[tx]
        if job["method"] == ALLOCATE:
            relayed = _unxaddr(attrs.get(RELAYED, b""), tx)
            if relayed is None:
                self._fail("the TURN server gave no relayed address")
                return
            self.relayed = relayed
            self.mapped = _unxaddr(attrs.get(MAPPED, b""), tx)
            self._lifetime(attrs)
            self.permit_timer.start(PERMIT_EVERY * 1000)
            self.keep_timer.start(KEEPALIVE_S * 1000)
            queued, self._permit_queue = self._permit_queue, set()
            if queued:
                self.permit(queued)
            self.ready.emit(relayed)
        elif job["method"] == REFRESH:
            self._lifetime(attrs)
        elif job["method"] == CREATE_PERMISSION and job.get("ip") is not None:
            self._asking.discard(job["ip"])
            if job["ip"] not in self.refused:
                self.permitted.add(job["ip"])
        if job["then"]:
            job["then"]()

    # -- the allocation's life
    def _lifetime(self, attrs: dict) -> None:
        """Refresh well inside what the server GRANTED, which may be less
        than LIFETIME_S asked for: refreshing on our own clock let a
        shorter allocation lapse under a live session."""
        val = attrs.get(LIFETIME, b"")
        granted = struct.unpack("!I", val)[0] if len(val) == 4 else LIFETIME_S
        every = max(15, min(granted // 2, granted - 60))
        if getattr(self, "_granted", None) != granted:
            log(f"granted for {granted}s, renewed every {every}s")
            self._granted = granted
        self.refresh_timer.start(every * 1000)

    def _lose(self, why: str) -> None:
        if self.closed or self.relayed is None:
            return
        log(f"lost — {why}")
        self.relayed = None
        self.refresh_timer.stop()
        self.permit_timer.stop()
        self.keep_timer.stop()
        self.pending.clear()
        self._binds.clear()
        self.lost.emit(why)

    def _keepalive(self) -> None:
        """A plain STUN Binding to the server: keeps the router's mapping for
        this socket alive, and its answer says whether the router has moved
        us anyway. No auth: TURN servers answer it as any STUN server does."""
        if self.closed or self.relayed is None or self.server is None:
            return
        now = time.monotonic()
        self._binds = {t: at for t, at in self._binds.items() if now - at < 2 * KEEPALIVE_S}
        tx = os.urandom(12)
        self._binds[tx] = now
        self.sock.writeDatagram(build(BINDING, tx, [], fingerprint=False),
                                QHostAddress(self.server[0]), self.server[1])

    def _bound(self, tx: bytes, attrs: dict) -> None:
        if self._binds.pop(tx, None) is None or self.relayed is None:
            return
        seen = _unxaddr(attrs.get(MAPPED, b""), tx)
        if seen is None or self.mapped is None or seen == self.mapped:
            return
        # The router gave this socket a new port: the allocation belongs to
        # the old one, so nothing reaches us through it any more. Say so now
        # rather than at the next refresh's 437, minutes later.
        self._lose("this router moved the relay's socket to a new port")

    def permit(self, ips) -> None:
        """Let datagrams from these IPs through to us (ports do not matter:
        a permission is for an address, which is what lets a symmetric NAT,
        whose port is new for every destination, through)."""
        ips = {ip for ip in ips if self._permittable(ip, self.local)}
        if self.relayed is None:
            self._permit_queue |= ips
            return
        # One request per address: a server refuses a whole request when any
        # one address in it is forbidden (the joiner's own relay, say), and
        # then none of them got in.
        for ip in sorted(ips - self.permitted - self.refused - self._asking):
            self._ask_permission(ip)

    def _ask_permission(self, ip: str) -> None:
        self._asking.add(ip)
        tx = self._request(CREATE_PERMISSION, [(PEER, _xaddr(ip, 0, b"\0" * 12))])
        self.pending[tx]["ip"] = ip

    @staticmethod
    def _permittable(ip: str, local: bool = False) -> bool:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if a.version != 4 or a.is_multicast or a.is_unspecified:
            return False
        # is_global, not just "not private": 100.64/10 (carrier NAT, and
        # Tailscale's addresses) is neither, and a TURN server forbids it.
        return local or a.is_global

    def _repermit(self) -> None:
        if not self.closed:
            for ip in sorted(self.permitted - self._asking):
                self._ask_permission(ip)

    def _refresh(self) -> None:
        if not self.closed:
            self._request(REFRESH, [(LIFETIME, struct.pack("!I", LIFETIME_S))])

    def send(self, data: bytes, peer) -> None:
        if self.relayed is None or self.closed:
            return
        tx = os.urandom(12)
        msg = build(SEND_IND, tx, [(PEER, _xaddr(peer[0], int(peer[1]), tx)),
                                   (DATA, data)], fingerprint=False)
        self.sock.writeDatagram(msg, QHostAddress(self.server[0]), self.server[1])

    def _too_slow(self) -> None:
        if self.relayed is None and not self.closed:
            self._fail("the TURN server did not answer in time")

    def _fail(self, why: str) -> None:
        if self.closed or getattr(self, "_failed", False):
            return
        self._failed = True
        self.failed.emit(why)

    def close(self) -> None:
        """Give the allocation back (a Refresh of lifetime 0) and stop."""
        if self.closed:
            return
        if self.relayed is not None and self.server is not None and self.key:
            msg = build(REFRESH, os.urandom(12),
                        [(LIFETIME, struct.pack("!I", 0)), (USERNAME, self.user.encode()),
                         (REALM, self.realm), (NONCE, self.nonce)], self.key)
            self.sock.writeDatagram(msg, QHostAddress(self.server[0]), self.server[1])
            self.sock.waitForBytesWritten(50)
        self.closed = True
        self.pending.clear()
        self.refresh_timer.stop()
        self.permit_timer.stop()
        self.keep_timer.stop()
        self.sock.close()
