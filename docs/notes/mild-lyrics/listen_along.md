# listen_along.py

## 2026-10-29 — the cover goes with the song

Bug: a listener playing in Mild Lyrics' own player kept the previous song's
cover. `_play` built the stream item from the state, which carried no cover,
and the view only loads a cover when the song names one (`art_url`), so the
old picture stayed. The sharer now puts `art` (https only, at most `ART_MAX`
characters) in the state, and the queue is cut to fit as before. A cover that
lands after the song was sent is sent by itself. `_play` puts it on the item.
A sharer on an older build still sends none.

## 2026-10-16 — the sharer picks every song; no autoplay blip

Goal: skips blocked while listening along, twice to stop; anything else
that changes the song goes back to the sharer's; and the listener's own
autoplay was heard for a moment at each song change.

- `ListenAlong.holds()`: Next/Previous (`player_do`) and picking a song in
  the window (search, browse, detail rows, Ctrl+V) are refused with a toast;
  the same again within `SKIP_AGAIN` (5s) stops listening and goes through.
  Pause and seeking stay the listener's (seeks are stepped back anyway).
- A different song on the listener is now always taken back, not only within
  `HOLD` -- replacing "the listener's pick is left alone" below. Not while
  the sharer is gone: then there is nobody to follow.
- Song end: with the sharer's song within `END_NEAR` (2s) of its end, the
  listener's copy is paused `END_LEAD` (0.25s) before its own end
  (`_arm_end`, a single-shot timer, as the 500ms tick is too coarse), and
  waits paused for the sharer's next song. An autoplay that gets in anyway is
  paused, and the ended song is not started again. Costs the last 0.25s,
  usually silence.
- The per-song "listening along — title" toast is gone.

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

Added after the first real use (Worker deployed and working; not yet
tried with two Spotify accounts).

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
Removed the same day. Discord refuses buttons beside a join
secret ("secrets cannot currently be sent with buttons"), so Join cost the
Spotify button while sharing, and the buttons are worth more. Only
the web link below remains. Join stays out unless that trade changes.

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

## 2026-10-19 — the session menu: lock, new invite, end

Clicking the "N listening along" badge (lyrics view; `listen_badge_rect`) or
the listen line at the foot of the home page's sidebar opens
`LyricsView.listen_menu`. Sharing: who/since/locked header, Copy invite
link, Lock/Unlock, the Discord card's button (discord_listen), Drop
everyone and make a new invite, End. Listening: header, Copy invite link,
Stop listening along.

**Lock without a Worker change.** There is no telling listeners apart, and
the server only knows "a key hash and some sockets", so `ListenAlong.lock`
does it in the sealed channel: a fresh secret and host key, a room for them,
and once that room is up `{"move": <new secret hex>}` goes out through the
old one; listeners `_hop` into the new room keeping their song as it is
(`want` kept, no toast), and MOVE_GRACE_MS (4s) later the old room gets
`{"end": true}` and is closed -- so the invite that is out there (Discord,
chats) now leads to an ended room, and a late joiner in the grace window
follows the move too. While locked: no invite is copied, `discord_url()` is
"" (the card shows no button). Unlock only allows the current room's invite
to be shared again. An app too old to know "move" is ended with the old room.
**Drop everyone** is `restart`: end (listeners told) and share again.
Tested against wrangler dev: test_listen_along_actions (lock keeps both
listeners, they follow the next song, the old invite gets nobody in, unlock
+ new joiner, drop everyone).

## 2026-10-19 — the lyrics view's badge: clickable only where drawn, and a hover

Bug: the "N listening along" badge could be clicked where it was not shown, with no hover. `listen_badge_rect` was set when the panel drew the badge and never cleared, so the card, dock and backdrop layouts (which do not draw it) kept a live click area. It is reset every frame beside `bar_rect`/`vol_rect`. While the badge opens a menu (`listen.role`), it gets the gear's hover: a soft pill, brighter text, the hand cursor.

## 2026-10-22 — Listening along through Mild Lyrics' own player

Goal: listening along works when the listener plays in Mild Lyrics. The listener could only start the sharer's song in Spotify (`request_play` by id, or Spotify's catalogue search), so a listener who plays in Mild Lyrics got nothing. Also checked: the Worker answers from both machines (Linux `websockets` and Windows' ClientWebSocket got `{"t":"you"}`), and the laptop's `mild-lyrics://` registration is real and runnable.

- `_play` now starts the song wherever this window plays songs, by the home page's own rule (`Home.play_in()`, the Settings ▸ Home "Play songs in" choice). For "mild" it calls `Home.play_stream` with name, artist, album, length, Spotify uri, YouTube id and ISRC. `can_play`/`holds` are bypassed because this is the sharer's pick.
- The sharer's state carries `yt`, `isrc` and `album` (and the own player's Spotify id when the clock has none) while its own player is the one followed (`_own_track`), so a listener streams the same recording. They are optional keys, so older listeners ignore them.
- `_asked` gained a fourth field (started in Mild Lyrics). The listener's own key for the song (a name key or another id) is taken as the song (`_mine`) whenever it was started here, also when the sharer sent a Spotify id.
- The listener's autoplay does not fill while listening along.

Test: test_listen_along_mild.py (11, wrangler dev on 8799). The other six listen-along tests are unchanged and pass. test_listen_along_door prints nothing useful with XDG_RUNTIME_DIR/TMPDIR pointed at a scratch dir; run it with the defaults (it uses its own door name).

## 2026-10-24 — listeners get the sharer's queue

Goal: listeners get the sharer's queue, so their fetch ahead works too. A listener only ever knew the song playing, so its fetch ahead, stream prefetch and next-song video worked from its own queue, which had nothing to do with what would play next.

- The sharer's state carries `q`: its next songs (`UPCOMING`, 7, fetch ahead's own most), from Mild Lyrics' own queue when that is the player followed, else from Spotify's (`queue_items`, Spotify songs only). A leading copy of the song playing (a queue read before it started) is dropped.
- **Ids where there are some, names otherwise**: a song with an ISRC goes as `{"i": isrc, "s": spotify id, "y": youtube id}`, and the listener names it from Deezer (`track/isrc:`, one ask a code, on a thread, kept for the session; checked live: USUG11904206 -> Blinding Lights / The Weeknd / 200s). Any other song goes as `{"t", "a", "l"}` plus whichever ids it has, title and artist cut to `CUT` (80), with a featured name the artists already carry said once (`stream_source.drop_credited_feat`: "Feels (feat. Pharrell Williams, Katy Perry & Big Sean)" by Calvin Harris, Pharrell Williams, ... -> "Feels"). Spotify's queue rows carry no ISRC, so a sharer in Spotify always sends names.
- **Size**: the Worker drops a state over `STATE_MAX` (1024 bytes, sealed) without a word, so `_state` fits the queue to it, dropping songs from the end, and states are UTF-8 JSON, not `\u` escapes. Measured with Feels-length names everywhere: all 7 as ISRCs (696 bytes); 5 by name (880). Raising STATE_MAX in worker.js would fit 7 names too; that needs a Worker deploy.
- **Order on the listener**: `upnext()` stops at the first song still being named, so the queue is never out of order, and fills in when `named` fires. A code Deezer does not know (None) is left out unless it has a Spotify or YouTube id; a failure to ask is asked again with the next queue.
- **Kept picks and names**: fetch ahead's kept pick now carries the title and first artist it was made under (`_pick_names`, squashed, credited featured names cut), and the load drops it when the song plays under other names. Spotify's and Deezer's names for Feels agree; "Bohemian Rhapsody - Remastered 2011" against Deezer's plain title does not, and that song is simply loaded as usual.
- The queue's change test is by who the songs are, not how they are sent: an ISRC found for a queued song later is no new message (tested).
- **Cost**: the queue rides on the song's own message. A change to the queue alone (a song added, autoplay topping up) is sent once it holds `SETTLE_TICKS` and `QUEUE_GAP` (3s) after the last send: a burst of edits is one message (tested: three edits, one send).
- **Listener in Mild Lyrics' player**: `_play` starts the song with the sharer's queue after it, shuffle held off for that call. Later changes go in with `replace_after` (`_follow_queue`) once the song playing is the sharer's; a queue that came while it was starting is put in when it starts. A queue-only state changes nothing else: no new HOLD, no new seeks.
- **Listener in Spotify**: Spotify's queue cannot be set from here, so the window's `queue_items` (what fetch ahead, covers and motion ahead read) becomes the sharer's, and `on_queue` keeps it that way (`spotify_queue`). Stopping asks Spotify for the real queue again.
- An older sharer sends no `q` (`upnext()` is None): the listener keeps its own queue, as before. Older listeners ignore `q`.

Test: test_listen_along_queue.py (32, wrangler dev on 8799; Deezer faked). The other seven listen-along tests pass unchanged.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/listen_along.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Listen along: one player shares what it plays, others follow in their own.
>
> Through a `Listen` room on Mild Lyrics' Worker (docs/discord-cover-worker).
> Only the sharer ever sends, and only when the song, the pause or the place
> changes; listeners send nothing and keep in step locally. The state is
> encrypted under a key that only the invite carries. See
> docs/notes/mild-lyrics/listen_along.md.
