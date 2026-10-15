# Still to do

Reported and not yet fixed. Some of it is blocked on evidence -- a song
nobody has named, a question only the person who asked can answer -- and
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


## The background layer rebuilds 13 times a second

**The biggest single cost left in a frame.** `scene_layer` rebuilds 13
times a second. Its docstring says "composited at 15fps and blitted at the
frame rate", and that is exactly what it does -- but the cap is the only
thing holding it, because the freshness test fires on the CLOCK
whenever `bg_motion` is on, whatever the key says. Measured over 30s of
full-window painting, 1811 frames:

    scene_layer rebuilds   398   median 3.63ms   worst 9.36ms

So roughly every fourth frame carries an extra 3.6ms, and that is most of the
difference between the lyric column's median (~1.3ms) and the whole window's
(~3.0ms).

What makes it worth looking at rather than accepting is the rate the drift
actually moves: `t = now * 0.06 * bg_motion`, so between two rebuilds 1/15s
apart `t` advances by 0.004, which for most `bg_mode`/`mesh_style` settings is
well under a pixel. A large share of those 398 rebuilds are painting the same
picture again.

Two ways, and they are not the same:

  * **Quantise the drift into the key.** No visual change at all -- the
    rebuild is skipped only where it would have produced the same pixels. It
    needs the step that corresponds to a pixel of movement, which has to come
    out of `_paint_mesh` and `_art_src` rather than be guessed at.
  * **Lower the cap.** One number, and it trades against how smoothly the
    background drifts, so it is the user's call and not a free win.

Not done here because the first needs measuring per bg_mode and the second is
a matter of taste, not a bug.


## What the window still does to itself on a cold track

**Left over from the first-line stall**, which is fixed (see closed.md). Of
the 17 late ticks that remain on a cold track, the largest things are the
window's own: `on_lyrics` at 47ms worst, `say_alignment_outranked` at 34ms
and `measure_offset` at 20ms. On the walk threads, `duet_flags` at 59ms. All
an order of magnitude below what was there, and none of them measured
further.


## Following a browser on Windows

**Reported 2026-10-15:** the Output and Player rows appear (the bindings are
installed), and following Firefox half works -- it is followed for a second
or three, then the sync stops and the window goes back to Spotify.

**Found, and fixed blind.** A Windows session hands over its position with
the moment it was written; the window carried that forward for at most
`SMTC_CARRY` (10s), on the belief that a playing session rewrites it about
once a second, and `_moving` ignored the stamp altogether and watched the raw
position. A player that writes its timeline only on play, pause and seek
stands still to `_moving`, so after `STILL_FOR` (2s) it was dropped with
"firefox is playing but will not say where — not following it". A stamp
that lands inside the track now counts as a running clock (`clocked`), and
`tests/test_platforms.py` reproduces the drop on the old code.

**To confirm, on that machine:** play a song in Firefox and see whether it
stays followed. If it still drops, run
`python mild-lyrics\doctor.py --no-shortcut` while it plays: a Firefox
session line saying "timeline has no usable stamp" means Firefox gives no
position at all, which no change here can follow; "timeline written Ns ago"
with N growing means the fix should have held, and something else is wrong.

**Still open from before:** whether the window should say when it is only
looking at Spotify (Any media player off), since "no player here but
Spotify" and "not looking at anything but Spotify" read the same from
outside.


## Stretched last words on QQ syncs

**Reported:** "For the Glory" (All Good Things) is a bad QQ sync. The other
half of that report, the holes mid-phrase ("sudden ends" on "Omen"), is fixed
-- see `close_holes`.

**What is left:** a line's LAST syllable stretched to the line's own end.
"For the Glory" writes `royalty[32.82-35.03]`, 2.2 seconds for one word in a
line whose median syllable is 0.3, with the next line at 35.29, so every line
crawls to a stop.

**Where to start.** Nothing inside the document separates this from a real
sustain -- a ratio rule was measured against the hand-timed files and refused
(closed.md has the table) -- so the fix has to come from outside it: a second
source's line sync, or the audio, saying the voice stopped. The blend already
does this ("Where the base says the singing stops, believe it"); the raw QQ
path does not.


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
    answers from title text today.


## Move the commentary out of the code and into /docs

**Decided 2026-10-12, by the person whose code it is:** keep comments and
docstrings short, and put anything long in `docs/notes/<module>.md` -- new
docstrings one to three lines, the reasoning in a dated section the code can
point to. Whether to move the prose is no longer the question; the question
is the backlog.

**What is left, counted 2026-10-15.** The `#` comments are mostly short now;
the essays moved into docstrings, which the August lift (`8afab08`) did not
count:

    module                        # comment lines   docstring lines
    mild-lyrics/lyrics_gui.py           346              5226
    mild-lyrics/lyric_sources.py        141              3749
    mild-lyrics/renderers.py            241              1792
    editor/app.py                       116               705

`docs/notes/mild-lyrics/renderers.md` exists now (2122 lines), so renderers
has somewhere to send its prose that it did not have when this was written.

**What still holds from before.** A note drifting from its code is worse than
none, and the line-number anchors in `docs/notes/README.md` were stale before
this pass; what belongs in /docs is the argument, and what stays by the code
is the consequence and a pointer to it. So it is not a cut-and-paste job: take
one self-contained argument at a time -- the rise schedule (RISE_LEAD, the
`word_lifts` docstring and `FLOAT_MIN` making one case three times) is the
best first one -- write it once in the module's note, and leave each site a
line and a reference.


## Overlapping lines on "LUV U NEED U" - Slushii

**Reported 2026-10-15:** a lot of lines overlap that should not. Not looked
at yet. There is no copy of the song in the cache here, so the first step is
fetching it (when last seen it was a Kugou blend on Apple's lines) and seeing
whether the overlap is in a donor or made by the blend. Reshaping passes run
on blends only -- one source's own overlaps are measurements -- so which it
is decides whether the fix is ours.

An older entry about one word boundary on this song landing inside
"moments" is in closed.md; it was not what the report meant.


## Apple Music, off a browser, when the upload is long and has no artist

**Reported** as Apple Music lyrics often failing to fetch, narrowed to a
browser, Firefox. The half where `from_bini` refused any lookup without an
artist is fixed (see the commit log and `tests/test_trouble.py`).

**What is left, re-probed 2026-10-15** through `LS.from_bini` directly:

    song                  artist+record  no artist+record  no artist, +12s  artist, +12s
    Coldplay - Clocks        syllable        syllable           none            none
    Radiohead - Creep        syllable        syllable           none            static
    Baby Keem - HONEST       syllable        syllable           none            none
    NF - Time                line            line               none            static

Every door is gated on the duration at NEAR (6.0s), so a length more than six
seconds off answers nothing at all. With an artist the window gets round it:
`_apple_card` matches on the artist, `card_len` takes the record's length and
`better_question` re-walks. With NO artist and an upload longer than NEAR --
Firefox's MPRIS gives the window title and no `xesam:artist`, and
`song_from_video` recovers one only from "Artist - Title" -- the card is not
matched either, and the song gets nothing from Apple.

**Where to start.** BiniLyrics answers `?q=<text>` with no artist; `limit=50`
is the only way past the first ten rows, and `duration=` filters server side
with the same cliff, so leave it out. Each row has `isrc`, `artist_name`,
`duration`, `timing_type` and `lyricsUrl`. The candidate is
`q=<title>&limit=50` ranked locally against the upload's length on a slack
wide enough for an intro and narrow enough to refuse Pink Floyd's "Time"
(425.9s against NF's 240.4s). Measure first how many title-only answers
survive, say, thirty seconds of slack and how often the first is right -- one
probe over ./lyrics -- and leave NEAR itself alone; every source leans on
it.


## The card's length is the earliest pressing's, not the one playing

`_apple_card` reads every field off `_cover_cut`'s row, the earliest release,
which is right for the cover and not obviously right for the LENGTH, which
`card_len` hands every provider from then on. Sweater Weather: the EP at
240.04s against the album cut at 240.4s being played.

**No longer urgent:** `from_bini.by_isrc` now reads every pressing up to the
first word-timed one, so the third of a second cannot cost a word sync any
more. **Left to decide, by measuring:** whether `card_len` should be the
best-matching hit's duration instead. Everything downstream gates on it at
NEAR, so it only ever mattered as a tie-break, and `card_len` is load-bearing
for the browser case above.

Do not read `hasTimeSyncedLyrics` as a word-sync signal: it is true for line
timing too.


## CPU work proposed and not done

From the CPU and RAM pass of 2026-09-29 (what it measured and left alone
is in closed.md).

  * MPRIS reads its player with four D-Bus round trips a reading (`Metadata`
    twice); one `GetAll` would do. Windows SMTC makes three COM calls a
    reading, and `asyncio.run` per call where the projection has no `.get()`.
    macOS starts a thread and an `osascript` process every 0.25s per player.
    None of the three can be run here; only the CDP transport was ever
    measured.
  * A banded dynamic programme for `genius_roman.align`. It is O(lines x
    theirs x 4) and would cut that, but it could change an alignment where a
    section is missing, and there is no corpus here to say it does not.
  * `Cards.paint` walks every card and draws the dim ones live; a cached plan
    like `Flow.layout_plan` would help (4.6ms median against 1.6). `line_pixmap`
    could be cut to the ink `layout_plan` already knows, and Spicy's `_put`
    could cache a word drawn in a solid fill. All three are large changes to
    paths that have to stay pixel-exact, for a gain that was not shown.
  * `Editor.refresh()` runs in full on every drag and tap event. Coalescing it
    to once a frame would cost up to 33ms of lag on the labels it also sets.
  * The drawer is built eagerly at start-up, and the editor imports the whole
    player module for `app_dir` and two helpers. Neither was measured.

**One thing noticed and not looked into.** Under the offscreen platform,
resizing the window every frame while grabbing it segfaults now and then: one
run in eight, on the starting commit as well as on this one. It may be a
harness artefact, and it may not.


## Revamp the home page

**Asked for 2026-10-15:** the home page wants a revamp. Nothing more is
written down yet -- what is wrong with it today, and what it should become,
is the first thing to get from whoever asked. Not started.

**What it should become (2026-10-15):** more usable -- right now there is
nothing all too interesting on it. No design yet; this is "at some point",
not now.

**What is there now**, so the revamp starts from the real thing.
`open_browse("home")` swaps the lyrics for `view = "browse"`, and
`_paint_browse` draws a tab bar (Home, Search, Queue) over the scene with
`_paint_shelves` under it. The shelves come from `build_home`, in this order,
each shown only when it has rows:

    Now playing                    show_now_card and a track up
    Recently played, Jump back in  recents, re-asked after 120s
    Songs you might like,
      Because you played <seed>    discover, re-asked after 600s
    Popular by / <artist> playlists /
      More like <artist> / Your playlists   suggest, for the artist playing
    Word-by-word in your library,
      Romanisable                  a sample of 12 from the lyric index
    From your cache                the rest of the index

Opening it also does work: it starts the lyric index if there is none, a
refresh if it is stale, and a title backfill when under a quarter of the
index has titles. A revamp that changes what is shown should keep those
triggers somewhere, or the index stops being built.

The only ways in are two keys -- `browse` (Home) and `search` (/) through
`do_action`. Nothing on screen opens it.


## The Home key opens the home page

**Asked for 2026-10-15:** Home is a weird key for it. Not changed yet.

Why it reads as weird, from the tree: Home means "go to the start"
everywhere else, and it does here too -- the review list's Home jumps to the
first row, and the text fields' Home goes to the start of the text. On many
laptop keyboards it is Fn+Left, so it is not one key at all. And since the
page has no button, a key nobody guesses is the only way in.

The key is a slot, so it can be rebound already: `keymap.TABLE`, row
"browse, search & queue", slot `browse`, default `"Home"`. Changing the
default is one string, but whoever has not rebound it loses the key they
learnt, so pick the new one together with the revamp above, and decide
whether the page should also get something on screen to open it.


## Keyboard layouts other than QWERTY

**Reported 2026-10-15, by somebody on AZERTY:** the keys are shown the
QWERTY way, which is very confusing.

**The naming bugs are fixed** (2026-10-15, `tests/test_keymap.py`). A key's
name is the character the layout produced; Shift is part of it only on
letters and named keys, and `)` `{` `}` are "Shift+0" and "Shift+[/]" only
when Shift was held on the key US puts them on (checked by scan code, so
QWERTZ's Shift+9 is `)`, not Shift+0). Dead keys (`^`, `´`, `¨`) are named by
their mark and bind with one press. So on AZERTY `0` clears the track's
offset again, the unshifted `)` no longer clears the global one, `/` and `.`
work, and AltGr's `{` `}` reach the fine offset by alias. On QWERTZ and
AZERTY the global clear (Shift+0) has no key at all until it is rebound.
Non-Latin layouts (Cyrillic, Greek) report their own letters, so the letter
keys do not fire while one is active; that was so before, and is untried.

**Left: the labels and defaults.** `[` `]` still need AltGr on AZERTY, and the
Keys tab prints US names. Either keep matching by character and pick defaults
every common layout types without AltGr, or match the PHYSICAL key
(`nativeScanCode`) and print each key as the current layout labels it. The
second is what was asked for, but Qt has no public call that names a scan
code in the active layout: it needs xkbcommon on Linux and
`MapVirtualKey`/`ToUnicode` on Windows, and only Linux can be tried here.
Also untried: Windows reports AltGr as Ctrl+Alt, so AltGr keys arrive there
as `Ctrl+Alt+[` and fire nothing.


## Deploy the shared splitting dictionary

**Built 2026-10-16, not live yet.** The editor's Splits tab, the question for
words with several ways and the Worker's `Splits` object are done and tested
against `wrangler dev`. Until the Worker is deployed the tab answers
"HTTP 404" and every split comes from your own corrections and the rule.
From `docs/discord-cover-worker`: `npx wrangler deploy` (adds migration v4),
then `npx wrangler secret put SPLITS_OWNER` and type the same secret into the
Splits tab to lock entries.


## Loose ends

- `_paint_dots` reads `ln["end"] - ln["start"]` and raises on a dots block
  with no times on it. The DIVISION is safe -- the span is
  `max(1e-6, end - start)`, so a zero-length marker is drawn rather than
  dividing by nothing -- and what is left is the read itself: a missing key
  or a None on either side, which is a KeyError or a TypeError before the
  guard is reached. Not reachable today: `prepare` refuses to insert
  interlude markers into a document with no timings at all, so every marker
  that exists has real ones. Written down because a paint fault here is
  silent -- it half-draws the window rather than crashing -- so if a path
  ever does hand one over, what it looks like is the window losing everything
  below the column and nothing saying why.
- `tests/test_blends.full.py` fails on this branch and is not a regression.
  It calls `LS._same_clock`, which exists on `blends-full` (`c6f6b50`) and has
  never been an ancestor of this branch; here the same question is `in_order`.
  The suite is outside the repository, so a test file does not change with
  the branch, and `test_blends.py` superseded this one long ago. Delete it or
  keep it for that branch; it says nothing about this code.
