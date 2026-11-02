# Still to do

Reported and not yet fixed. Some of it is blocked on evidence -- a song
nobody has named, a question only the reporter can answer -- and
some is work that is understood and simply has not been done. Each entry
says which, what is already measured, and where to start.

Only what is open is listed. Fixed items are in the commit log, which says
what the measurement was. What was measured and refused, and every entry
taken off this list, is in [closed.md](closed.md), word for word, so nobody
re-derives it.

**Where things are.** The test suite, `bench/`, `sync/`, `eval_blends.py` and
the `tools_*.py` probes are not in this repository any more: they are in
`~/mild-lyrics-archive/` (`tests/`, `bench/`, `sync/`, `aligner/eval_blends.py`,
`tools_*.py`). A `tests/test_x.py` below means
`~/mild-lyrics-archive/tests/test_x.py`. The player's modules, `doctor.py`
included, are in `mild-lyrics/`; there is no `aligner/` in the repository.


## What the Genius credit left open

The credit is done (`genius_roman.credit_of`; see closed.md). Two things it
turned up:

  * whether `lyrics_marked_complete_by`, `lyrics_marked_staff_approved_by`
    and `verified_lyrics_by` are on `/songs/<id>` for songs nobody has
    verified, and how often the line is simply absent. Watch the first real
    fetch against a token.
  * a search hit carries fields nothing reads yet: `apple_music_id`, and a
    `media` list with a Spotify `native_uri`. The Spotify id is a second
    opinion on WHICH RECORDING a Genius page is about, which `_same_cut`
    answers from title text today. Blocked on seeing the fields: on
    2026-10-30 a plain request to `genius.com/api/search/multi` got an HTML
    challenge page, so this waits for a real fetch through the app.


## CPU work left: the Windows and macOS player reads

What is left of the 2026-09-29 list (the rest was done or measured and closed
2026-10-16; see closed.md). Windows SMTC makes three COM calls a reading, and
an `asyncio.run` per call where the projection has no `.get()`. macOS starts a
thread and an `osascript` process every 0.25s per player. Neither can be run
here, and both are Windows-or-Mac-only paths, so they wait for somebody who
can measure them. (MPRIS, the one that could be measured, is one GetAll now.)

**Windows measured 2026-10-25** on the Windows laptop while following Firefox:
the `mild-winrt` thread (named by a py-spy dump) used 2.7% of one core over
30s, about 2.3% across the run. The whole process used 92%, about 80 of it
drawing (the main thread in DrvSwapBuffers, plus two Intel driver threads),
with GPU on and the bloom visualiser. The reads are not worth trimming before
the drawing is. macOS is still unmeasured.

**Noticed and not looked into.** Under the offscreen platform,
resizing the window every frame while grabbing it segfaulted now and then: one
run in eight, on 2026-09-29, with a harness that was not kept. Tried again
2026-10-30 on the real window offscreen, with the network refused and a random
size on every frame for 300 frames, lyrics view then Home, 12 runs (3,600
resize-and-grabs): no crash. The one offscreen segfault seen that day was an
exit race, fixed (lyrics_gui.md, 2026-10-30), and the 09-29 runs may have been
that one too. Open only until it is seen again; then keep the core
(`coredumpctl dump`) and the harness.


## Keyboard layouts other than QWERTY

Windows AZERTY is done (confirmed on the Windows laptop 2026-10-25), and so
are non-Latin layouts (2026-10-30; closed.md has both entries as they stood).
**Left:** macOS reads no layout and keeps the US names. A Cyrillic or Greek
layout there falls back on the US letter at each key (`keymap.US_LETTERS`),
which is right for a US board and off for AZERTY; unverified, no Mac here.


## Windows: one song played with no sound at all

Blocked on evidence. On another person's Windows machine the music video played
and the lyrics ran, so the local player's clock was moving, but nothing was
heard. Clearing "Fetched audio" was followed by working sound. That cache
(`fetched/<tid>.wav`, `local_align._kept`) is only read by alignment: nothing
in `local_player` plays from it. So whatever fixed it was probably something
else that happened at the same time: a fresh resolve, or a restart dropping the
kept link in `stream-urls.json` (`Resolver.live`, kept while `expires` is more
than 10 minutes off).

**Shipped blind 2026-10-30, the likeliest cause.** `QAudioOutput` stays on the
device that was the default when it was made, so a headset, Bluetooth or HDMI
switch leaves the song playing (clock, video and lyrics moving) where nobody
hears it; a restart picks the new default. `LocalPlayer._outputs_changed` now
moves onto the default whenever `QMediaDevices.audioOutputsChanged` fires, and
writes `local-output` to `follow.log`. A loaded song with no audio track writes
`local-silent`. Wanted from that machine, if it happens again: the song, and the
`follow.log` rows around it (`local-output`, `local-silent`, `local-error`, the
resolver's pick) plus `stalls.log`.


## Windows: the window freezes while the mouse moves over it

Probably fixed in 1.2.1; which version the reports came from is not known.
Reported on some Windows machines: moving the pointer over the window freezes
it, keeping the pointer still does not, and it recovers after a while. That is
the shape of the 1.2.0 fault fixed on 2026-10-29 (lyrics_gui.md, "Hover polled
the output device once per mouse move"): every move woke `_watch_device`, and
on Windows each poll is a WinRT call that holds the GIL. 1.2.1 polls at most
every DEVICE_POLL, and STALL_AFTER is 2s, so a hover stall now leaves a stack
in `stalls.log`.

Measured offscreen 2026-10-30 on 1.2.1 (real LyricsView, 1500 synthetic
moves): a move costs ~0.13ms in the lyrics view and on Home, and p99 2-3ms
with a GIL-busy Python thread beside it. Still a suspect on Windows:
`_FrameFilter`, which runs Python, and so takes the GIL, for every Windows
message while `win_material` is on (clear background + mica/acrylic/tabbed).
Trimmed 2026-10-30 to read the message id alone first (0.18us a message
against 0.78us). Wanted: whether it still happens on 1.2.1, and if so
`stalls.log` and the Background and Backdrop settings.
