# `mild-lyrics/saves.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/saves.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Where the TTMLs this program writes are kept, and who wrote them.
>
> One folder beside the program, with two rooms in it:
>
>     lyrics/fetched/   what the player saved off a song it fetched
>     lyrics/made/      what somebody timed themselves, in the editor
>
> They are split because they are not the same thing, and the difference is
> only obvious while you are holding them. A file the player wrote is a copy of
> a document somebody else made -- a community sync, Apple Music's, a blend --
> kept because it was worth keeping. A file the editor wrote is the reader's
> own work, and it is the one that cannot be fetched again. Left in one heap,
> and both named "Artist - Title.ttml", the only way to tell them apart is to
> open them and look at the timings.
>
> They used to land loose in the program folder, which is how this checkout
> came to have eighty TTMLs sitting next to lyrics_gui.py.
>
> Both rooms are made when the editor starts and again whenever either program
> saves, rather than once at install: a folder somebody deleted between runs is
> not a reason for a save to fail.
>
> The player's room can be moved from Settings ▸ Storage; the editor's cannot,
> because where timed work goes is decided with Save as when it is saved.
