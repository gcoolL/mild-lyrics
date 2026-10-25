# `editor/backups.py`

Comments lifted out of `editor/backups.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 29** — on `KEEP = 60`

> how many copies to hold, newest first

## Lift — 2026-10-25

Docstrings shortened in `editor/backups.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Copies of work, kept without being asked.
>
> A lyric is hours of listening. It should not be possible to lose one to a
> keystroke, a stale path or a fetch into the wrong window -- and it was: a
> document replaced in the editor was simply gone, and a file written over was
> gone with it.
>
> So two nets, both silent:
>
>   * before anything is written over, the file that was there is copied here;
>   * while there is unsaved work, it is written here every half minute, and
>     whenever it is about to be replaced by something else.
>
> Kept beside the player's own cache, for two weeks, and never in the way. Nothing
> here is a substitute for saving -- it is what is left when saving did not
> happen, or happened to the wrong file.

### `_index`

**line 86** — from the docstring, `def _index(root: pathlib.Path) -> dict:`

> What is known about each copy without opening it: {file name:
> [mtime_ns, size, lines, timed, first line]}.
>
> Reading them back means parsing every one -- 21ms for a 91KB copy, so
> about six seconds for three hundred, all on the thread the window draws
> on. A copy is never changed once it is written, so what was seen of it
> then is what it is: written when the copy is, and worked out once for
> any that predate it.
