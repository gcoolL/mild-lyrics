# `mild-lyrics/interface.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/interface.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Which interface both programs are drawn in: the new one, or the classic.
>
> One switch for the two of them, because they are one program to whoever is
> using them: the player and the TTML Editor were redesigned together, and a
> person who did not like the result should be able to put both back with one
> setting rather than hunting for two. So it is not kept in either program's
> own settings file -- gui.json and editor.json each have a schema and a
> history of their own -- but in a file of its own beside them, which each
> program reads when it starts and watches while it runs. Flipping it in one
> redraws the other.
>
>     new       the settings drawer, the slim toolbar, the in-window dialogues
>     classic   the centred menu, the ribbon, the system's own dialogues
>
> Anything unreadable is "new", which is the default.
