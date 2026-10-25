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
    answers from title text today.


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

**Noticed and not looked into.** Under the offscreen platform, resizing the
window every frame while grabbing it segfaults now and then: one run in
eight. It may be a harness artefact, and it may not.


## Keyboard layouts other than QWERTY

Windows AZERTY is done: labels, defaults, and dead keys in one press,
confirmed on the Windows laptop 2026-10-25 (closed.md has the entry as it stood).
**Left:**

  * macOS reads no layout and keeps the US names.
  * Non-Latin layouts (Cyrillic, Greek) report their own letters, so the
    letter keys do not fire while one is active. Untried.
