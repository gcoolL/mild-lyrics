# `editor/collab_ws.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/collab_ws.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The way through Mild Lyrics' relay: one WebSocket to a room on the Worker.
>
> Nobody in a session learns anybody else's IP address this way. Every editor
> connects to the room (docs/discord-cover-worker/worker.js, class Room) and
> the room passes datagrams between the host and each joiner; all anyone sees
> of the others is a member number. What travels is the editors' own QUIC,
> encrypted end to end under the certificate the invite pins: the room, and
> Cloudflare under it, carry bytes they cannot read.
>
> To collab_net this is just another way to send a datagram. A joiner's only
> peer is the host, at ("w:host", 0); the host's peers are ("w:<n>", 0), one
> per joiner's member number. Datagrams sent within FLUSH_MS of each other go
> in one WebSocket message -- the free plan counts incoming messages, and a
> burst of QUIC packets is many datagrams with nothing between them.
>
> Frames, both ways, are a run of [2-byte length][datagram]; the host's
> outgoing ones and every one it receives have the member's number (4 bytes,
> big-endian) in front. Driven by Qt's loop, like collab_net: no thread.

### `RoomLink`

**line 52** — from the docstring, `class RoomLink(QObject):`

> One editor's WebSocket to one room.
>
> `ready` once the room has said who we are; `got(datagram, addr)` for each
> datagram that arrives; `failed(why)` if it never opened; `lost(why)` if
> it closed under a session, after which it tries again by itself (a host
> keeps its room, a joiner gets a new number, which QUIC follows); `gone
> (addr)` when the room says somebody else's socket closed -- a joiner's to
> the host, the host's to its joiners.
