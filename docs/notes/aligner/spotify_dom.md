# `aligner/spotify_dom.py`

Comments lifted out of `aligner/spotify_dom.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 41** — before `# --------------------------------------------------------------------------`

> Minimal RFC 6455 websocket client (CDP only ever sends text frames)


## `WebSocket.__init__`

**line 49** — before `self.sock.sendall(`

> No Origin header on purpose: Chromium rejects cross-origin DevTools
> websockets unless it was launched with --remote-allow-origins.


## `WebSocket.recv`

**line 111** — on `            if opcode == 0x9:`

> ping

**line 114** — on `            if opcode == 0xA:`

> pong

**line 116** — on `            if opcode == 0x8:`

> close


## module level

**line 131** — before `# --------------------------------------------------------------------------`

> Chrome DevTools Protocol


## `CDP.call`

**line 144** — on `                continue`

> an event we didn't subscribe to


## `connect`

**line 197** — before `pages.sort(key=lambda t: ("xpui" not in t.get("url", ""), t.get("url", "")))`

> The main app window is the xpui bundle; prefer it, else take the first page.


## module level

**line 203** — before `# --------------------------------------------------------------------------`

> JS snippets

**line 206** — before `JS_TESTIDS = """`

> Spotify's CSS class names are hashed and change every release. The
> data-testid attributes are the only selectors worth depending on.
