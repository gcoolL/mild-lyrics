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


## GPU drawing on Windows: confirm the swap fix

**Reported 2026-10-16** from somebody else's PC: GPU "on" is slow or crashes,
and freezes while recording until they tab out. Shipped blind: swap interval
0 on Windows, and a canvas whose swap blocks over 1s falls back to the CPU
with a toast (docs/notes/mild-lyrics/gpu_canvas.md).

**To ask them:** the fps row of the debug overlay with GPU on, before and after
this build; whether recording still freezes, and for how long; which
recorder (OBS game, window or display capture, Game Bar, Discord); and the
GPU. "Crashes" was not described: a crash log or the last lines of the
console would say whether it is a crash or the freeze.


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


## "Okay (oh-ooh)" lit for a tenth of a second on LUV U NEED U

**Found 2026-10-16** while fixing that song's overlaps, and older than the
fix: in the NetEase blends the line runs 37.84-37.95. Kugou and QQ sing
"Okay" 38.10-39.38, and NetEase writes it as "O-o-o-Okay" 38.57-39.32. Not
looked into. The real inputs are in `tests/fixtures/luv_u_need_u.json`.


## eval_blends cannot run as it stands

`eval_blends.songs` reads its track list from the cache's `tracks.json`,
which no longer exists, and `build` has no `WHOSE` entry for the Kuwo blends
(`--only` without them works). On 2026-10-16 it was run through a scratch
wrapper that rebuilds the list from the reference filenames, with each length
from the Apple card, and keeps Spicy out of the donors
(docs/notes/mild-lyrics/lyric_sources.md). Either give it that list itself
or point it at a list the player still writes.


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


## CPU work left: the Windows and macOS player reads

What is left of the 2026-09-29 list (the rest was done or measured and closed
2026-10-16; see closed.md). Windows SMTC makes three COM calls a reading, and
an `asyncio.run` per call where the projection has no `.get()`. macOS starts a
thread and an `osascript` process every 0.25s per player. Neither can be run
here, and both are Windows-or-Mac-only paths, so they wait for somebody who
can measure them. (MPRIS, the one that could be measured, is one GetAll now.)

**Noticed and not looked into.** Under the offscreen platform, resizing the
window every frame while grabbing it segfaults now and then: one run in
eight. It may be a harness artefact, and it may not.


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

**Reported 2026-10-15, by somebody on AZERTY.** The labels and defaults are
done (2026-10-16, docs/notes/mild-lyrics/keymap.md): `[` `]` and `0` sit by
position and are printed as the layout prints them, read from the
compositor's xkb keymap on Linux and measured on Belgian AZERTY here.

**Left:**

  * Windows is written blind: `kblayout._windows` (ToUnicodeEx) and the
    AltGr-as-Ctrl+Alt fix. On a Windows AZERTY machine the Keys tab should
    read `^ / $` for the offsets; if it still says `[ / ]`, the layout was
    either not read or dropped after three presses Qt named differently.
  * macOS reads no layout and keeps the US names.
  * Non-Latin layouts (Cyrillic, Greek) report their own letters, so the
    letter keys do not fire while one is active. Untried.
