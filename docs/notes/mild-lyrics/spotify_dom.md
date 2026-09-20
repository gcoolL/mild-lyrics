# `mild-lyrics/spotify_dom.py`

Comments lifted out of `mild-lyrics/spotify_dom.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `WebSocket._frame`

**line 89** — before `hdr = bytearray([0x80 | opcode])`

> One frame on the wire at a time. Two half-written frames interleaved
> is a stream neither end can read again, and there are two writers in
> the ordinary case: whoever is sending a command, and the pong that
> recv() answers a ping with on the reading thread.


## `WebSocket.close`

**line 141** — before `self.sock.shutdown(socket.SHUT_RDWR)`

> SHUT_RDWR before close, because there is usually somebody else
> in recv() on this socket and close() does not reliably wake
> them: the fd goes away and the blocked reader is left waiting
> for bytes that are never coming -- measured at three and a half
> seconds here, bounded only by the socket's own fifteen-second
> timeout. That wait lands on whichever thread was reading, which
> is routinely the one fetching the lyrics for the song on
> screen, and it is spent on a read that had already failed on
> somebody else's thread. shutdown ends it at once.


## `CDP.__init__`

**line 190** — on `        self._lock = threading.Lock()`

> the id, and the waiting list

**line 191** — on `        self._read = threading.Lock()`

> who is reading the socket


## `CDP.call`

**line 210** — before `slot["ev"].wait(0.05)`

> Somebody else has the socket and will wake us with our
> answer when it comes past. Waited on in short steps so a
> reader that finishes and leaves is taken over from
> promptly rather than after its whole timeout.

**line 225** — on `                            continue`

> an event, not an answer

**line 229** — before `with self._lock:`

> The socket is gone. Everyone waiting on it is waiting
> for nothing, and one of them would otherwise take over
> the reading and hit the same wall in turn.


---

## Earlier lift — 2026-08-23

Comments lifted out of `mild-lyrics/spotify_dom.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 41** — before `# --------------------------------------------------------------------------`

> Minimal RFC 6455 websocket client (CDP only ever sends text frames)


### `WebSocket.__init__`

**line 49** — before `self.sock.sendall(`

> No Origin header on purpose: Chromium rejects cross-origin DevTools
> websockets unless it was launched with --remote-allow-origins.


### `WebSocket.recv`

**line 111** — on `            if opcode == 0x9:`

> ping

**line 114** — on `            if opcode == 0xA:`

> pong

**line 116** — on `            if opcode == 0x8:`

> close


### module level

**line 131** — before `# --------------------------------------------------------------------------`

> Chrome DevTools Protocol


### `CDP.call`

**line 144** — on `                continue`

> an event we didn't subscribe to


### `connect`

**line 197** — before `pages.sort(key=lambda t: ("xpui" not in t.get("url", ""), t.get("url", "")))`

> The main app window is the xpui bundle; prefer it, else take the first page.


### module level

**line 203** — before `# --------------------------------------------------------------------------`

> JS snippets

**line 206** — before `JS_TESTIDS = """`

> Spotify's CSS class names are hashed and change every release. The
> data-testid attributes are the only selectors worth depending on.
