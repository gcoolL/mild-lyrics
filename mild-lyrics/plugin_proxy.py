"""The only way out to the network a plugin has: an HTTPS CONNECT proxy on
127.0.0.1, which lets each plugin through to the sites its plugin.json lists.

A plugin is told who it is by the login in its proxy URL (HTTPS_PROXY), a
token made fresh each time it starts. Only port 443, and never to this
machine or the local network, whatever a name resolves to.
"""

from __future__ import annotations

import base64
import ipaddress
import secrets
import select
import socket
import socketserver
import sys
import threading

HEAD_MAX = 8192
IDLE_S = 120.0

_lock = threading.Lock()
_who: dict = {}             # token -> (plugin id, (site patterns...), on_refusal)
_server = None


def _log(*bits) -> None:
    print("[plugin proxy]", *bits, file=sys.stderr, flush=True)


def allowed(host: str, patterns) -> bool:
    """host against 'example.com' (it alone) or '*.example.com' (its subdomains)."""
    host = host.lower().rstrip(".")
    for p in patterns:
        p = p.lower().rstrip(".")
        if p.startswith("*."):
            if host.endswith(p[1:]) and host != p[2:]:
                return True
        elif host == p:
            return True
    return False


def public(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


class _Handler(socketserver.BaseRequestHandler):
    def _say(self, code: int, text: str) -> None:
        body = text.encode()
        self.request.sendall(f"HTTP/1.1 {code} {text}\r\nContent-Length: {len(body)}\r\n"
                             f"Connection: close\r\n\r\n".encode() + body)

    def handle(self) -> None:
        conn = self.request
        conn.settimeout(10)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = conn.recv(4096)
            if not chunk or len(head) > HEAD_MAX:
                return
            head += chunk
        lines = head.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
        parts = lines[0].split()
        token = ""
        for line in lines[1:]:
            name, _, value = line.partition(":")
            if name.strip().lower() == "proxy-authorization":
                kind, _, cred = value.strip().partition(" ")
                if kind.lower() == "basic":
                    try:
                        token = base64.b64decode(cred).decode().partition(":")[2]
                    except ValueError:
                        token = ""
        with _lock:
            who = _who.get(token)
        if who is None:
            self._say(407, "Proxy Authentication Required")
            return
        pid, patterns, refused = who
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            self._say(405, "Only HTTPS")
            return
        host, _, port = parts[1].rpartition(":")
        host = host.strip("[]")
        if port != "443" or not allowed(host, patterns):
            refused(f"{host}:{port} is not one of the sites it lists")
            self._say(403, "Forbidden")
            return
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            self._say(502, "Bad Gateway")
            return
        addrs = [i for i in infos if public(i[4][0])]
        if not addrs or len(addrs) < len(infos):
            refused(f"{host} resolves to this machine or the local network")
            self._say(403, "Forbidden")
            return
        try:
            up = socket.create_connection(addrs[0][4][:2], timeout=10)
        except OSError:
            self._say(502, "Bad Gateway")
            return
        conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        rest = head.split(b"\r\n\r\n", 1)[1]
        if rest:
            up.sendall(rest)
        self._pipe(conn, up)

    @staticmethod
    def _pipe(a: socket.socket, b: socket.socket) -> None:
        a.settimeout(None)
        b.settimeout(None)
        try:
            while True:
                ready, _, _ = select.select([a, b], [], [], IDLE_S)
                if not ready:
                    return
                for s in ready:
                    data = s.recv(65536)
                    if not data:
                        return
                    (b if s is a else a).sendall(data)
        except OSError:
            return
        finally:
            b.close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False


def port() -> int:
    """Start the proxy if it is not running; its port."""
    global _server
    with _lock:
        if _server is None:
            _server = _Server(("127.0.0.1", 0), _Handler)
            threading.Thread(target=_server.serve_forever, daemon=True,
                             name="plugin-proxy").start()
        return _server.server_address[1]


def admit(pid: str, patterns, on_refusal=None) -> str:
    """A fresh token for a plugin starting; its HTTPS_PROXY URL."""
    token = secrets.token_urlsafe(24)
    said: set = set()

    def refused(why: str) -> None:
        if why not in said:
            said.add(why)
            _log(pid, "refused:", why)
            if on_refusal:
                on_refusal(why)
    with _lock:
        _who[token] = (pid, tuple(patterns), refused)
    return f"http://{pid}:{token}@127.0.0.1:{port()}"


def forget(url: str) -> None:
    token = url.split("@", 1)[0].rsplit(":", 1)[-1]
    with _lock:
        _who.pop(token, None)
