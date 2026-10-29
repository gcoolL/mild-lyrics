# voice.py

## 2026-10-29 — voice chat, in multiplayer and beside listen along

Goal: talk while timing a lyric together in the TTML Editor, and while
listening along. Every join, and every time the microphone is switched on,
goes through a pop-up first; nothing is remembered between times.

**Where the audio goes.** No paid Cloudflare service (Calls/Realtime needs a
payment method on the account), and no direct path (the direct route was
removed so nobody learns anybody's address). So voice rides the relay that
is already deployed: the Worker's `Room`, unchanged. It is a star around one
hub, the session's host. A member sends to the hub alone, and the hub passes
each speaker on to everyone else in voice.
- Editor: the datagrams go beside QUIC on the session's own link
  (`Endpoint.send_voice`, `Endpoint.voice`), prefixed `\x00MLV`. No QUIC
  packet starts that way (the fixed bit is clear), and neither does a punch
  or a STUN answer, so an editor that knows nothing of voice drops them. The
  key (32 random bytes, made by the host) goes to each joiner inside QUIC as
  `{"t": "voice", "k"}`, and only to editors whose hello lists `voice` in
  `can`. A hand-over makes a new key, and people join again.
- Listen along: the Listen room has listeners send nothing, so voice cannot
  go there. The sharer opens a `Room` of its own and puts its id in the
  sealed state as `vc` (34 bytes, inside STATE_MAX). The key is
  `_derive(secret, "voice")`, so it never travels at all. Locking ends voice:
  the old secret, which the invite out there still gives, made its key.

**Sealing.** `seal`: nonce, then a BLAKE2b keystream, then a BLAKE2b tag,
the same construction as listen_along's (stdlib only, so the player needs no
`cryptography`). The relay sees sizes and timing, never sound. A datagram
under another key is dropped; the hub in the editor also drops any peer the
session does not have (`names`).

**What it costs the free plan.** Nothing is sent while you are quiet:
energy over a floating noise floor (`SENSES`), held `HANG` (300 ms) and with
`PREROLL` (40 ms) from just before. Speech goes in `PACKET_MS` (100 ms)
packets, so one person speaking is ~10 incoming room messages a second
(measured over fake_room: 6–20 in a second of speech, 0 in silence). The hub
batches everything it passes on until its next tick, so each listener costs
one message per tick however many speak. An hour of one person talking is
~36k messages, ~1.8k requests at the 20:1 rate, against 100k a day for
everyone. Room limits still hold: 1,200 messages/minute a socket (the hub's
cap grows with its sockets) and 12 sockets a room.

**Sound.** 16 kHz mono, 20 ms frames. Opus (libopus through ctypes, 24 kbps,
VOIP) when everyone in voice has it, else a µ-law of our own (128 kbps).
The hub picks for all and says which in the roster. Windows rarely ships
libopus, so a Windows person in voice puts everyone on µ-law. Playback holds
a speaker until 140 ms is queued (or 250 ms passed), cuts back past 500 ms,
and keeps 120 ms in the sink. No echo cancellation: the pop-up says to use
headphones.

**Level, both ends (2026-10-29, after the first real try: "very silent").**
Sent: automatic gain (`_lift`). It follows the speech level (speech frames
only, `LEVEL_EASE`) and moves it toward `TARGET_DB` (-18 dBFS), by -6 to
+24 dB at most 0.5 dB a frame (the first words jump straight there), then
peak-limits to `PEAK`. A -42 dBFS microphone arrives at -18. Heard:
`_limit`, after the volume. No 20 ms frame goes past `HEAR_RMS` (-14 dBFS)
or a sample past `HEAR_PEAK` (about -4 dBFS). It acts at once and lets go
at 15 dB/s, whatever a peer sends (an older or altered sender, a full-scale
blast) and with the volume at 2×. Ordinary speech passes untouched (within
1 dB). The OS volume still sits on top; only full scale is ours to cap.

**Noise, and asking (2026-10-29, second round).**
- `Denoiser`: spectral subtraction on 40 ms square-root-Hann windows at half
  overlap (20 ms late, exact where left alone). The noise is each band's
  lowest smoothed power over the last 1.5–2 s (minimum statistics, `DN_*`),
  so speech never teaches it. Spread over five bands before the gain is
  taken, cut by at most -20 dB, with gains that fall at once and rise at
  `DN_RISE`. Tuned on synthetic hiss plus pitch-wandering harmonics: noise
  -18 dB, speech -0.1 dB, error -27 dB. A tone held over ~2 s goes the way of
  a fan's hum. Key clicks: a frame `CLICK_JUMP` over the recent energy and
  noise-like (`CLICK_FLAT`) is cut to `CLICK_CUT`. Setting
  `voice_denoise` (default on), in the editor and in Listen along.
- `ONSET`: three loud frames in a row before it counts as speech, and
  `PREROLL` 4 sends them anyway. One click or tap never opens the mic.
- The microphone asks once per time in voice (`mic_ok`): joining with it, or
  the first "turn it on", allows it until leaving. Muting and unmuting after
  that ask nothing. Joining always asks.

**Echo, and typing (2026-10-29, third round: two machines in one room heard
a continuous echo and the key clicks).**
- Cause of the loop: a far end's voice came out of the speakers, the
  microphone heard it as speech (VAD open, auto gain up to +24 dB), and sent
  it back. Key clicks kept the mic open because any loud frame re-armed the
  300 ms hang.
- `EchoCanceller`: partitioned frequency-domain NLMS (overlap-save), 16 × 20
  ms partitions (320 ms of path), step evened out by a share of the mean
  power (`AEC_REG`). Without that, bands between harmonics blew up. The
  reference is what `mix()` gave the speakers, stamped with when it will play
  (`Devices._push`: now plus what is queued) in `FarEnd`. Mic frames are
  stamped when read, so the path it learns is causal. Both talking is judged
  from its own ERLE (error far over the expected residual), and only once it
  has learnt 6 dB. A "both" lasting 2 s is a changed room, learnt slowly. The
  divergence reset only looks at frames louder than about -40 dBFS: quiet
  frames at the end of a burst are all leftover, and once threw away a learnt
  path.
- What is left goes out with the noise (`Denoiser(echo=…)`, `ECHO_OVER`, down
  to -30 dB). While the speakers play, a frame counts as a voice here only
  within `ECHO_GATE` (15 dB) of the echo estimate, after `ONSET_FAR` (100 ms),
  and only once the canceller has cut 12 dB (`AEC_OPEN`), as a speakerphone
  does. Measured on a synthetic room (direct path at 30/90/200 ms plus a 15 ms
  decaying tail, pitch-wandering harmonics): echo -25 to -40 dB once learnt
  (~1 s), nothing sent back after 3.2 s, at most one ~0.4 s blip while
  learning. A voice here under the far end, 8 dB below its echo, still goes
  (90/90 frames), about 6 dB softer. 0.2 ms a frame here.
- Clicks: only speech lasting `ONSET` (or `ONSET_FAR`) opens or holds the mic,
  so typing after speaking closes it after the 300 ms tail. A click mid-speech
  is cut when it jumps over the frame before it, as well as over the recent
  level.
- What no canceller here can remove: two machines in one room hear each
  other's speakers. A's microphone hears B's speakers playing A's own voice,
  which is in nobody's reference. Testing side by side needs headphones on at
  least one of them.

**Not tried:** real devices and two real machines. The suites stub the
devices (`Devices` is swapped out) and never open a microphone or the
speakers: `test_voice.py` (engine, 24), `test_collab_voice.py` (two editors
over fake_room, 19), `test_listen_voice.py` (a sharer and two listeners, 17).

## 2026-10-29 — the editor and the app, side by side

- Microphone sensitivity (`voice_sense`: low/normal/high, `SENSES`) was an
  editor setting only; Listen along now has the same row, `--voice-sense`,
  applied live like volume and noise removal.
- The editor's join pop-up came up every time somebody opened voice while you
  were out, so "Not now" did not hold. It now comes up by itself once a voice
  chat (once per key: a host hand-over is a new chat); after that the session
  row's "Join voice…" asks. Listen along already asked once per room.
- Kept apart on purpose: listen along asks for a name and only the sharer can
  open it, and the sharer leaving closes it; the editor uses the session's
  names, and its host, already the hub, can step out of voice without ending it.
