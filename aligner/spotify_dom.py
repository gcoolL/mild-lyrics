#!/usr/bin/env python3
"""
Read the live DOM out of the running Spotify desktop app.

Spotify desktop is a CEF/Chromium app, so its UI is real HTML. Start it with a
DevTools port and you can query it over the Chrome DevTools Protocol:

    pkill -x spotify
    spotify --remote-debugging-port=9222 >/dev/null 2>&1 &

Then:

    ./spotify_dom.py targets                       # what pages are attached
    ./spotify_dom.py testids                       # discover stable selectors
    ./spotify_dom.py now                           # scrape the now-playing bar
    ./spotify_dom.py now --watch 2                 # ...every 2 seconds
    ./spotify_dom.py html '[data-testid="now-playing-widget"]'
    ./spotify_dom.py text '[data-testid="context-item-link"]'
    ./spotify_dom.py eval 'document.title'

Stdlib only (plus nothing). No pip install required.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import threading
import sys
import time
import urllib.request
from urllib.parse import urlparse

DEFAULT_PORT = 9222


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
class WebSocket:
    """A minimal client. Writes are serialised; reading is the caller's to
    serialise, and CDP does it -- see there."""

    def __init__(self, url: str, timeout: float = 15.0):
        self._wlock = threading.Lock()
        u = urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        path = u.path + (f"?{u.query}" if u.query else "")
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {u.hostname}:{u.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n".encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("connection closed during websocket handshake")
            buf += chunk
        head, _, self._buf = buf.partition(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b" 101" not in status:
            raise ConnectionError(f"handshake refused: {head.decode(errors='replace')}")

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("websocket closed by peer")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _frame(self, opcode: int, data: bytes) -> None:
        n = len(data)
        # One frame on the wire at a time. Two half-written frames interleaved
        # is a stream neither end can read again, and there are two writers in
        # the ordinary case: whoever is sending a command, and the pong that
        # recv() answers a ping with on the reading thread.
        hdr = bytearray([0x80 | opcode])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 1 << 16:
            hdr.append(0x80 | 126)
            hdr += struct.pack(">H", n)
        else:
            hdr.append(0x80 | 127)
            hdr += struct.pack(">Q", n)
        mask = os.urandom(4)
        hdr += mask
        with self._wlock:
            self.sock.sendall(
                bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def send(self, text: str) -> None:
        self._frame(0x1, text.encode())

    def recv(self) -> str:
        payload = b""
        while True:
            b0, b1 = self._read(2)
            fin, opcode, masked, n = b0 & 0x80, b0 & 0x0F, b1 & 0x80, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if masked else None
            data = self._read(n) if n else b""
            if mask:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if opcode == 0x9:
                self._frame(0xA, data)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                raise ConnectionError("websocket closed by peer")
            payload += data
            if fin:
                return payload.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self._frame(0x8, b"")
        except OSError:
            pass
        self.sock.close()


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
class CDP:
    """One DevTools socket, usable from more than one thread.

    It has to be. The window asks the page for the lyrics, the artists and the
    audio analysis on its fetcher loop, searches Genius on a thread of its
    own, and searches Spotify's catalogue on another -- all down this one
    socket, because there is one page.

    It used to be a bare `send` and then a loop reading until an answer with
    the right id turned up, DISCARDING everything else. Everything else
    included the other thread's answer. So two calls in flight was a coin
    toss: one of them got its reply, the other one's was thrown away by the
    first, and it sat in recv() until the socket's fifteen-second timeout gave
    up -- for a query that had already been answered. That is why a catalogue
    search sometimes took an age and usually did not: it depended on whether
    anything else happened to be asking at the same moment, and the search box
    asks Genius at the same moment by design.

    So every answer now goes to whoever asked for it. There is no reader
    thread: whichever caller is waiting takes the socket and reads, files each
    answer under its id, and wakes the thread that wanted it -- then carries on
    reading until its own arrives. If a different caller already holds the
    socket, this one waits to be woken instead. Whoever is reading is doing it
    for everybody, so a slow answer no longer holds up a quick one behind it.

    A read that fails takes everybody down with it, rather than leaving the
    others waiting on a socket nobody is reading any more.
    """

    def __init__(self, ws_url: str):
        self.ws = WebSocket(ws_url)
        self._id = 0
        self._lock = threading.Lock()          # the id, and the waiting list
        self._read = threading.Lock()          # who is reading the socket
        self._waiting: dict = {}

    def _post(self, mid, msg=None, exc=None) -> None:
        slot = self._waiting.get(mid)
        if slot is not None:
            slot["msg"], slot["exc"] = msg, exc
            slot["ev"].set()

    def call(self, method: str, **params):
        with self._lock:
            self._id += 1
            mine = self._id
            slot = self._waiting[mine] = {"ev": threading.Event(),
                                          "msg": None, "exc": None}
        self.ws.send(json.dumps({"id": mine, "method": method, "params": params}))
        try:
            while not slot["ev"].is_set():
                if not self._read.acquire(timeout=0.05):
                    # Somebody else has the socket and will wake us with our
                    # answer when it comes past. Waited on in short steps so a
                    # reader that finishes and leaves is taken over from
                    # promptly rather than after its whole timeout.
                    slot["ev"].wait(0.05)
                    continue
                try:
                    while not slot["ev"].is_set():
                        raw = self.ws.recv()
                        try:
                            msg = json.loads(raw)
                        except Exception:            # noqa: BLE001
                            continue
                        got = msg.get("id")
                        if got is None:
                            continue                 # an event, not an answer
                        with self._lock:
                            self._post(got, msg=msg)
                except Exception as exc:             # noqa: BLE001
                    # The socket is gone. Everyone waiting on it is waiting
                    # for nothing, and one of them would otherwise take over
                    # the reading and hit the same wall in turn.
                    with self._lock:
                        for other in list(self._waiting):
                            self._post(other, exc=exc)
                finally:
                    self._read.release()
        finally:
            with self._lock:
                self._waiting.pop(mine, None)
        if slot["exc"] is not None:
            raise slot["exc"]
        msg = slot["msg"] or {}
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error'].get('message')}")
        return msg.get("result", {})

    def evaluate(self, expression: str):
        r = self.call(
            "Runtime.evaluate",
            expression=expression,
            returnByValue=True,
            awaitPromise=True,
        )
        if "exceptionDetails" in r:
            exc = r["exceptionDetails"]
            raise RuntimeError(
                exc.get("exception", {}).get("description") or exc.get("text", "JS error")
            )
        return r.get("result", {}).get("value")

    def close(self) -> None:
        self.ws.close()


def list_targets(port: int) -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as resp:
            return json.load(resp)
    except OSError as e:
        if os.name == "nt":
            how = ("Close Spotify, then start it with the debug port -- either "
                   "from a terminal:\n"
                   f'    "%APPDATA%\\Spotify\\Spotify.exe" '
                   f"--remote-debugging-port={port}\n"
                   "or by adding that switch to the Target field of the "
                   "Spotify shortcut's Properties.")
        else:
            how = ("Restart Spotify with the debug port:\n"
                   "    pkill -x spotify\n"
                   f"    spotify --remote-debugging-port={port} >/dev/null 2>&1 &")
        sys.exit(
            f"Can't reach the DevTools endpoint on 127.0.0.1:{port} ({e}).\n{how}"
        )


def connect(port: int, match: str | None = None) -> CDP:
    pages = [
        t for t in list_targets(port)
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
    ]
    if match:
        pages = [t for t in pages if match in t.get("url", "") or match in t.get("title", "")]
    if not pages:
        sys.exit("No matching page target. Run `spotify_dom.py targets` to see what's there.")
    pages.sort(key=lambda t: ("xpui" not in t.get("url", ""), t.get("url", "")))
    return CDP(pages[0]["webSocketDebuggerUrl"])


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------

JS_TESTIDS = """
(() => {
  const seen = new Map();
  for (const el of document.querySelectorAll('[data-testid]')) {
    const id = el.getAttribute('data-testid');
    if (!seen.has(id)) {
      seen.set(id, {
        testid: id,
        tag: el.tagName.toLowerCase(),
        text: (el.textContent || '').trim().slice(0, 60),
        aria: el.getAttribute('aria-label'),
      });
    }
  }
  return [...seen.values()];
})()
"""

JS_NOW_PLAYING = """
(() => {
  const q  = (s, r = document) => r.querySelector(s);
  const t  = (s) => { const e = q(s); return e ? e.textContent.trim() : null; };
  const bar = q('[data-testid="now-playing-widget"]');
  const play = q('[data-testid="control-button-playpause"]');
  return {
    title:     t('[data-testid="context-item-link"]'),
    artists:   [...document.querySelectorAll('[data-testid="context-item-info-artist"]')]
                 .map(e => e.textContent.trim()),
    position:  t('[data-testid="playback-position"]'),
    duration:  t('[data-testid="playback-duration"]'),
    playing:   play ? /pause/i.test(play.getAttribute('aria-label') || '') : null,
    art:       (q('[data-testid="cover-art-image"]') || {}).src || null,
    liked:     (() => { const b = q('[data-testid="add-button"]');
                        return b ? b.getAttribute('aria-checked') === 'true' : null; })(),
    href:      (q('[data-testid="context-item-link"]') || {}).href || null,
    raw_text:  bar ? bar.innerText.replace(/\\n+/g, ' | ') : null,
  };
})()
"""


def js_query(selector: str, prop: str) -> str:
    sel = json.dumps(selector)
    return f"[...document.querySelectorAll({sel})].map(e => e.{prop})"


# --------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--target", help="only use targets whose URL/title contains this")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("targets", help="list attachable pages")
    sub.add_parser("testids", help="dump every data-testid currently in the DOM")

    s = sub.add_parser("now", help="scrape the now-playing bar")
    s.add_argument("--watch", type=float, metavar="SECS", help="poll forever")

    s = sub.add_parser("html", help="outerHTML of every match")
    s.add_argument("selector")

    s = sub.add_parser("text", help="textContent of every match")
    s.add_argument("selector")

    s = sub.add_parser("attr", help="one attribute from every match")
    s.add_argument("selector")
    s.add_argument("name")

    s = sub.add_parser("eval", help="run arbitrary JS in the Spotify window")
    s.add_argument("expression")

    a = p.parse_args()

    if a.cmd == "targets":
        for t in list_targets(a.port):
            print(f"[{t.get('type')}] {t.get('title')}\n    {t.get('url')}")
        return

    cdp = connect(a.port, a.target)
    try:
        if a.cmd == "testids":
            for row in sorted(cdp.evaluate(JS_TESTIDS) or [], key=lambda r: r["testid"]):
                extra = row["text"] or row["aria"] or ""
                print(f"{row['testid']:<44} {row['tag']:<8} {extra}")

        elif a.cmd == "now":
            while True:
                print(json.dumps(cdp.evaluate(JS_NOW_PLAYING), indent=2, ensure_ascii=False))
                if not a.watch:
                    break
                time.sleep(a.watch)

        elif a.cmd == "html":
            for h in cdp.evaluate(js_query(a.selector, "outerHTML")) or []:
                print(h)

        elif a.cmd == "text":
            for t in cdp.evaluate(js_query(a.selector, "textContent.trim()")) or []:
                print(t)

        elif a.cmd == "attr":
            expr = js_query(a.selector, f"getAttribute({json.dumps(a.name)})")
            for v in cdp.evaluate(expr) or []:
                print(v)

        elif a.cmd == "eval":
            out = cdp.evaluate(a.expression)
            print(out if isinstance(out, str) else json.dumps(out, indent=2, ensure_ascii=False))
    finally:
        cdp.close()


if __name__ == "__main__":
    main()
