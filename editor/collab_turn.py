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
import zlib

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QAbstractSocket, QHostAddress, QHostInfo, QUdpSocket

PORT = 3478                      # TURN's own port, where none is given

MAGIC = 0x2112A442
# methods, already shifted into the class bits they are sent and answered in
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
    return (val[2] & 7) * 100 + val[3], val[4:].decode("utf-8", "replace")


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
    got = pyqtSignal(bytes, object)

    def __init__(self, server: str, user: str, password: str, parent=None, *,
                 local: bool = False) -> None:
        super().__init__(parent)
        self.local = local          # a test's server on this machine: permit LAN IPs
        self.closed = False
        self.relayed = None
        self.server = None          # (ip, port), resolved
        self.user, self.password = str(user or ""), str(password or "")
        self.realm = self.nonce = b""
        self.key = None
        self.pending: dict[bytes, dict] = {}
        self.permitted: set = set()
        self._permit_queue: set = set()
        self.sock = QUdpSocket(self)
        if not self.sock.bind(QHostAddress(QHostAddress.SpecialAddress.AnyIPv4), 0):
            raise OSError(self.sock.errorString())
        self.sock.readyRead.connect(self._read)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh)
        self.permit_timer = QTimer(self)
        self.permit_timer.timeout.connect(self._repermit)
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
                self._request(job["method"], job["attrs"], job["then"],
                              tries=job["tries"] + 1)
                return
            del self.pending[tx]
            if job["method"] == ALLOCATE:
                self._fail(("the relay refused the username or password"
                            if code == 401 else
                            f"the relay refused: {code} {why}").strip())
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
            self.refresh_timer.start(LIFETIME_S * 1000 // 2)
            self.permit_timer.start(PERMIT_EVERY * 1000)
            queued, self._permit_queue = self._permit_queue, set()
            if queued:
                self.permit(queued)
            self.ready.emit(relayed)
        if job["then"]:
            job["then"]()

    # -- the allocation's life
    def permit(self, ips) -> None:
        """Let datagrams from these IPs through to us (ports do not matter:
        a permission is for an address, which is what lets a symmetric NAT,
        whose port is new for every destination, through)."""
        ips = {ip for ip in ips if self._permittable(ip, self.local)}
        if self.relayed is None:
            self._permit_queue |= ips
            return
        new = ips - self.permitted
        if not new:
            return
        self.permitted |= new
        self._request(CREATE_PERMISSION,
                      [(PEER, _xaddr(ip, 0, b"\0" * 12)) for ip in sorted(new)])

    @staticmethod
    def _permittable(ip: str, local: bool = False) -> bool:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if a.version != 4 or a.is_multicast or a.is_unspecified:
            return False
        return local or not (a.is_private or a.is_loopback or a.is_link_local)

    def _repermit(self) -> None:
        if self.permitted and not self.closed:
            self._request(CREATE_PERMISSION,
                          [(PEER, _xaddr(ip, 0, b"\0" * 12))
                           for ip in sorted(self.permitted)])

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
        self.sock.close()
