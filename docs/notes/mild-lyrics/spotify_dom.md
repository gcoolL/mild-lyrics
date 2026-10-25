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

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/spotify_dom.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### `CDP`

**line 162** — from the docstring, `class CDP:`

> One DevTools socket, usable from more than one thread.
>
> It has to be. The window asks the page for the lyrics, the artists and the
> audio analysis on its fetcher loop, searches Genius on a thread of its
> own, and searches Spotify's catalogue on another -- all down this one
> socket, because there is one page.
>
> It used to be a bare `send` and then a loop reading until an answer with
> the right id turned up, DISCARDING everything else. Everything else
> included the other thread's answer. So two calls in flight was a coin
> toss: one of them got its reply, the other one's was thrown away by the
> first, and it sat in recv() until the socket's fifteen-second timeout gave
> up -- for a query that had already been answered. That is why a catalogue
> search sometimes took an age and usually did not: it depended on whether
> anything else happened to be asking at the same moment, and the search box
> asks Genius at the same moment by design.
>
> So every answer now goes to whoever asked for it. There is no reader
> thread: whichever caller is waiting takes the socket and reads, files each
> answer under its id, and wakes the thread that wanted it -- then carries on
> reading until its own arrives. If a different caller already holds the
> socket, this one waits to be woken instead. Whoever is reading is doing it
> for everybody, so a slow answer no longer holds up a quick one behind it.
>
> A read that fails takes everybody down with it, rather than leaving the
> others waiting on a socket nobody is reading any more.

### `CDP.close`

**line 233** — from the docstring, `def close(self) -> None:`

> Shut the socket, and tell everyone waiting on it that it is gone.
>
> Waking the reader is not enough on its own: a caller that never got
> as far as holding the read lock is sitting on its own event with no
> deadline, waiting to be handed an answer by a reader that has now
> left. It is told here instead, so a dropped connection ends every
> call on it rather than only the one that noticed.

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
