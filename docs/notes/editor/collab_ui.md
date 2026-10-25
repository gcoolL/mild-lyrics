# `editor/collab_ui.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/collab_ui.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Multiplayer in the window: the Multiplayer dialogue, the people strip, and
> the glue between the editor's document and a session.
>
> The editor knows almost nothing about any of this. It calls four things:
>
>     after_refresh()      the document may have changed: share it
>     moved()              the cursor or the selection moved: tell people
>     may_replace(what)    a whole new lyric is about to replace this one
>     leave()              the window is closing
>
> and everything else -- what to send, what came in, which lines are whose --
> is here and in collab.py.
>
> WHAT A REMOTE CHANGE TOUCHES. The document on screen, and every undo and redo
> snapshot: so that undoing rewinds YOUR work and never puts back a line
> somebody else has since changed. While a hand is mid-gesture -- a drag, a
> sweep, a word being typed -- changes that arrive wait until it lets go, so
> nothing moves under it.
