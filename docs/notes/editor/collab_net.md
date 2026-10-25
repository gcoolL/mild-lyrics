# `editor/collab_net.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/collab_net.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Two editors finding each other with no server between them.
>
>     host                                   joiner
>     ----                                   ------
>     asks STUN where it is                  .
>     makes an invite code  ---- chat ---->  pastes it, asks STUN where it is
>     .                     <--- chat -----  makes a reply code
>     pastes the reply
>     both send small punch packets at every address the other gave, at once,
>     so each router sees its own side speak first and lets the answer in
>     joiner opens QUIC to whichever address answered; TLS 1.3 against the
>     certificate the invite carried; the token from the invite goes first
>
> WHAT IS TRUSTED, AND WHY. The invite is the password: it carries a
> certificate made for this session alone, which the joiner pins as the ONLY one
> it accepts, and a random token the host checks before a joiner is anything at
> all. Everything after the handshake is QUIC -- encrypted, authenticated,
> ordered and retransmitted by aioquic, a maintained library, not by anything
> written here. What is written here is the punching, a STUN client, and the
> framing; each checks lengths before it reads and drops what it does not
> recognise without answering, so the port looks closed to anyone without a
> code.
>
> WHAT IS NOT PROMISED. Hole punching works between most home routers. It does
> not work when both sides' routers give a new port for every destination (a
> "symmetric" NAT — some mobile networks and carrier-grade NAT), and nothing
> here pretends otherwise: STUN is asked twice, from the same socket, and if
> the two answers disagree the window says so before anybody pastes a code.
>
> Driven entirely by Qt's own loop -- aioquic is used through its sans-IO API,
> so there is no asyncio and no thread.

### `_Invite`

**line 486** — from the docstring, `class _Invite:`

> One code, good for `seats` people.
>
> The count is the host's, never the code's: nothing a joiner holds says
> how many it lets in, so nothing a joiner does can change it. A place is
> spent when somebody comes in and is not given back when they leave --
> one code cannot be turned over and over to let a crowd through.

### `Endpoint._hello`

**line 1581** — from the docstring, `def _hello(self, conn: _Conn, msg) -> bool:`

> The host's door: the token from an invite, or nothing.
>
> Which invite is settled HERE, by the token, not by which one first
> heard this address: one person can be heard on two -- the invite
> they came in on, still with places left, and the resume invite they
> are coming back on -- and taking the first of those turned a
> returning joiner away for not having its token.

### `Endpoint.close`

**line 1735** — from the docstring, `def close(self) -> None:`

> End everything and let the port go. Safe to call twice.
>
> Blocks for at most a quarter of a second, on purpose: the last
> message sent -- "the session ended" -- and the close after it are
> paced, and a port closed at once loses them. A joiner told nothing
> sits in a dead session until the idle timeout. This also runs on the
> way out of the window, where there is no event loop left to wait in.

### module level (comment)

**line 303** — before `def _seal_key(secret: bytes, iid: bytes) -> bytes:`

> A reply is sealed to the host: the invite carries an X25519 key made for
> this session, the joiner seals the reply's contents (its addresses, its
> name) to it with a key of its own made for that one reply, and only the
> host's editor can open it. So a reply can be posted where the invite was
> -- a server's channel -- and everyone else reading sees only that a reply
> exists. The host still learns the joiner's address: it has to, to let
> them in.
