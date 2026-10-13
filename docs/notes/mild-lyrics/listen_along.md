# listen_along.py

## 2026-10-13 — the badge in the main view

Listen along ▸ **Show on screen** (`listen_badge`, default on, saved like
volume_bar): a green dot and "N listening along" under the volume slider
(panel: centred under it; compact: under the top-right slider), drawn by
`_paint_listen_badge` from `ListenAlong.badge()`. Sharing shows it only once
somebody listens -- an automatic share with nobody would otherwise always
say "0". Following someone: "Listening along" (grey "· waiting" while the
sharer is gone or the room is not up). Card, bar and backdrop layouts do not
draw it yet. The archive tests SKIP when nothing listens on :8799.

Reported the same night: a listener closing Mild Lyrics "doesn't function
properly". Measured, local workerd and the deployed Worker alike: a listener
quitting through closeEvent, killed -9, or a real LyricsView window closed
-> the sharer's count reaches 0 within the same poll (<0.5s), and the
process exits. What was missing: nothing asked the window to repaint when
the count or state changed, so a paused sharer kept showing "1 listening
along". `_changed()` now calls view.update() on every such change. If the
report recurs, ask which side and what stayed wrong.

## 2026-10-13 — shares by itself with the Discord button; links join at once

Asked for after the first real use (Worker deployed by them, "seems to
work"; not yet tried with two Spotify accounts).

- `keep_auto`, from discord_tick: while Discord status AND its Listen along
  button are on, a share is started by itself (at startup too), with no
  toast or clipboard, and stopped when either goes off. A share started from
  the menu is left alone by the toggle. Stop by hand holds it off until the
  button is toggled; a failed automatic share is quiet and tries again after
  AUTO_RETRY (300s). Never in `--no-persist` runs. The button's default is
  now OFF (new setups): on means your listening is followable by anyone who
  sees your profile, so it is a choice, not a default.
- Quiet when alone: the sharer sends nothing while the room counts no
  listeners, and sends the current state when the count goes up. An
  always-on share therefore costs one connection per start (plus
  reconnects), not one message per song.
- A joiner ignores what it hears for FIRST_SETTLE (0.8s) after connecting:
  the room's kept state can be from before the sharer went quiet, and the
  fresh one follows at once (tested: never asks for the stale song).
- A mild-lyrics:// link (the Discord button's page, or Door) joins with no
  dialogue: the click was the yes. The menu's Paste invite still asks.

## 2026-10-13 — Discord's Join: built, then removed

Tried so a click would reach Mild Lyrics with no browser: party +
`secrets.join` on the card, ACTIVITY_JOIN heard over the presence pipe.
Removed the same day at their call. Discord refuses buttons beside a join
secret ("secrets cannot currently be sent with buttons"), so Join cost the
Spotify button while sharing, and they would rather keep the buttons. Only
the web link below remains. Don't rebuild Join without asking.

## 2026-10-13 — joining from Discord

While sharing (and Discord status on), the card's first button is
**Listen along** (setting `discord_listen`, default on; Discord shows two
buttons at most, so it can push "Get Mild Lyrics" off). It links to
`<Worker>/l#<invite code>`: the code is after `#`, never sent to the Worker.
That page (static, browser-cached a day: one Worker request per click)
opens `mild-lyrics://listen/<code>` and otherwise shows the invite with a
Copy button and where to paste it.

- **Link registration**, at every non-`--no-persist` start, on a thread
  (`register()`): Linux writes `~/.local/share/applications/
  mild-lyrics-listen.desktop` (NoDisplay, `--listen %u`) and runs `xdg-mime
  default` if it is not already the handler; Windows writes
  `HKCU\Software\Classes\mild-lyrics` (pythonw, untested here); macOS has no
  handler (needs a bundle), so the page's copy-and-paste is the way there.
- **Hand-over**: `--listen <link>` first tries the running window's
  QLocalServer (`Door`, per-user name, UserAccessOption); if one answers the
  new process exits. Otherwise it starts and asks itself 1.5s in.
- A link never joins by itself: it brings the window up with the join
  dialogue filled in, so a stray link cannot start playing anything.
- Anyone who can see the sharer's Discord profile can use the button. That is
  the point of it, but it means the invite is as public as the profile.
- Discord never shows you your own buttons; the settings preview does. It
  shows Listen along whenever the setting is on (reported missing
  2026-10-13: it used to appear only while sharing, and sharing cannot
  start before the Worker is deployed), with a note while it is a stand-in.
- Not yet seen on real Discord: whether Discord keeps the `#` part of a
  button URL is unverified (a valid URL, so expected).

## 2026-10-13 — built: listen along, with as few Cloudflare requests as possible

Settings ▸ **Listen along**: *Share what I play* starts a share and copies
an invite (`ml-listen:<43 chars>`); *Listen along* takes one (prefilled from
the clipboard); *Stop* ends either.

### What goes through Cloudflare

A `Listen` Durable Object in the Worker (`docs/discord-cover-worker/worker.js`,
binding `LISTENS`, migration `v3`), at `/listen/<room>?as=host&k=…` or
`?as=hear`. The free plan bills a WebSocket upgrade as a request and each
*incoming* WebSocket message as 1/20 of one; messages *out* of a DO, protocol
pings, and hibernated time cost nothing. So:

- **Listeners send nothing, ever.** One that sends is closed with 4029 and
  does not come back. Everything a listener does to keep in step (drift
  checks, play/pause, seeking) is local, against its own player.
- **The sharer sends only on a change**: a different song, play↔pause, or a
  place more than `JUMP` (2s) off where the last message said it would be
  (a seek). Nothing periodic. A song change has to hold for `SETTLE_TICKS`
  and sends are at least `SEND_GAP` apart, so skipping through five songs is
  not five messages. The DO closes a sharer over 60 messages a minute.
- **A late joiner needs nothing from the sharer**: the DO keeps the last
  state in the sharer's socket attachment (no storage write) and hands it
  to whoever connects.
- **Clock**: the DO's `{"t":"you","now":ms}` on connect gives each side
  the server-minus-local offset; the sharer stamps `at` in server time, so a
  listener's expected place is `pos + (server now − at)` with no exchange.
- Listener counts and "the sharer dropped" come from the DO (outgoing, free).

Measured against `wrangler dev`: a test session of 6 changes (seek, pause,
play, two songs, a non-Spotify song) plus the opening state was 7 sharer
messages; 6s of plain playing, 0 sent; listeners 0. Rough real use: one
connect each, plus ~1–2 messages a song for the sharer, so a two-hour share
with three listeners is ~4 requests + ~50 messages (≈2.5 requests).

### Privacy

The invite is 32 random bytes. The room id is a BLAKE2b of it, so the
Worker only ever sees the id. States are sealed under keys derived from the
secret: BLAKE2b keystream (CTR-style, 16-byte random nonce) then a keyed
BLAKE2b tag over nonce+ciphertext (encrypt-then-MAC), stdlib only so the
player needs no `cryptography`. The Worker relays bytes it cannot read; a
listener cannot inject (only the sharer's socket is relayed, and only a
holder of the separate host key `k` can be the sharer).

### Following

- Spotify id (or `spotify_match` from Spotify lookup) → `request_play`.
  Otherwise a catalogue search of "title artist" through the window's own
  paste path (`paste_q`), and the first track it starts is taken as it.
- For `HOLD` (10s) after each change from the sharer, play/pause follows
  theirs. After that the listener's own pause or pick is left alone until
  the sharer's next change. Drift over `DRIFT` (1s) is corrected while both
  are playing the same song, at most `SEEKS_PER_EVENT` times per change.
- Playing a song needs the Spotify page link (the debug port); off it, the
  listener is told once per song.

### Not yet seen

Not deployed to the real Worker as of writing (`npx wrangler deploy` from
docs/discord-cover-worker, which adds the `v3` migration). Not tried between
two real machines. Tests: `~/mild-lyrics-archive/tests/test_listen_along.py`
and `test_listen_along_drop.py`, against `npx wrangler dev --port 8799` of a
scratch copy of the Worker folder (fake players, no real playback).
