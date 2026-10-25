# `editor/collab_turn.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/collab_turn.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> A relay for when two editors cannot reach each other directly.
>
> Hole punching (collab_net) connects most pairs. It cannot connect a joiner
> behind a "symmetric" NAT -- some mobile networks, campus and carrier-grade
> NAT -- to a host whose router is fussy about who may answer, and nothing
> connects two such networks to each other without something in the middle.
> This is the something: a TURN allocation (RFC 8656) on a TURN server of the
> host's choosing -- a free account at ExpressTURN or Metered's Open Relay, or
> a coturn of their own -- with the username and password it gives, kept in
> the host's settings. Nothing is shipped in the app.
>
> ONLY ONE SIDE NEEDS ONE. A TURN server forwards to the allocation's owner
> whatever arrives at the relayed address from an IP the owner has given
> permission to, and forwards the owner's own sends out from that address. So
> the host puts its relayed address among the invite's candidates, permits the
> IPs the joiner's reply lists, and a joiner on any network reaches it by
> sending plain UDP at the relay's address -- which no NAT stops.
>
> WHAT THE RELAY SEES. Ciphertext. The session is QUIC, encrypted end to end
> and authenticated against the certificate pinned by the invite (collab_net);
> the relay carries those datagrams and can read none of them. It does see
> both public IP addresses and how much was sent.
>
> WHEN IT IS USED. Last. collab_net only answers through the relay once a
> direct path has had RELAY_AFTER seconds to answer and has not, so pairs that
> can connect directly still do, and the relay costs nothing for them.
>
> Runs on Qt's loop like the rest, on its own UDP socket, so nothing the
> relay sends can be mistaken for a punch or QUIC on the session's socket.
