# `editor/glass.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/glass.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The pieces the new interface is built from.
>
> The new look is the player's, carried over: the album colours blurred behind
> everything, panes of dark glass over them, white ink, and one control per
> kind of choice -- a switch for on/off, side-by-side buttons for a short list,
> a ▾ list for a long one, a slider for a number, a labelled button for
> something that happens once. These are those controls, and the drawer the
> settings and the keys live in.
>
> The classic look keeps the ribbon, the transport as it was and the dialogues;
> nothing here is used by it except the Switch, which draws as the ordinary
> check box it replaces whenever the classic palette is on.

### `Wrap`

**line 25** — from the docstring, `class Wrap(QLayout):`

> A row of controls that goes onto a second row when the window is
> narrower than the row, instead of holding the window that wide.
>
> A box layout's minimum width is a hard floor under the window: the
> toolbar and the transport, one row each, held the editor at 1741px
> wide in the new look -- wider than a laptop's screen. Here the floor is
> the widest RUN: an item added with `glue` stays on the row of the one
> before it, so a slider keeps its label and its readout, and the breaks
> fall only between runs. A run added with `right` goes to the right end
> of whatever row it lands on, as a stretch before it would put it.

### `Backdrop`

**line 174** — from the docstring, `class Backdrop(QWidget):`

> The window's floor: the album colours, blurred and dimmed.
>
> Painted rather than a picture, and cheap: four soft radial washes on a
> dark ground and a dim over them, the way the player's own "art" wall
> looks when the cover behind it is out of focus. `colours` can be handed
> the cover's palette; without one it uses the player's default wash.

### `Drawer`

**line 474** — from the docstring, `class Drawer(QFrame):`

> Settings and keys, in a panel that slides in from the right.
>
> The same two things the classic interface opens as dialogues, drawn the way
> the player draws its own: a tab per section down the left, a row per
> setting, and the control for each one right there -- nothing to OK. A
> change is kept the moment it is made and put on screen with it.
