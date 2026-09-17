# `editor/keys.py`

Comments lifted out of `editor/keys.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 58** — before `("seek_back", "Back a quarter second", "Shift+Left", "Transport"),`

> Not the bare arrows: those belong to the cursor, and binding them here
> took them away from it -- pressing Left in the lyric moved the SONG a
> quarter second instead of moving to the previous word.


## `Keys.__init__`

**line 120** — before `self.can = can or (lambda _name: (True, ""))`

> `can(name)` answers (whether this action can be done at all right
> now, and why not). Asked at the moment the key is pressed rather
> than when it is bound, because the answer changes under the window:
> the rate keys mean nothing while Spotify is the player and mean
> something again the moment a local file is opened. Left off,
> everything is always possible, which is what a caller with no
> opinion means.


## `KeyDialog.__init__`

**line 204** — before `groups: list = []`

> By group name, not by runs of it: ACTIONS lists the two nudge keys
> under Timing well after Transport, and reading it as runs made a
> second tab called Timing with two rows in it.

**line 220** — before `cap = QLabel(escape(label) if ok or not why else`

> The reason on its own line under the action, rather than run
> on after a dash: these read as sentences and two of them in
> a row read as neither.

**line 250** — before `self.resize(460, 420)`

> Small enough for a laptop screen, and resizable from there. Sizing
> itself to its contents is what put the buttons out of reach.


---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/keys.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 38** — before `ACTIONS = [`

> (name, what it is called on screen, default key, group)


### `remember`

**line 88** — on `        pass`

> a settings file that will not write is not


### module level

**line 89** — before `def bindings() -> dict:`

>                         a reason to stop editing


### `Keys.install`

**line 123** — before `sc.setContext(Qt.ShortcutContext.WindowShortcut)`

> WindowShortcut, not WidgetWithChildren: the strip, the list and
> the ribbon are all children of the window and a tap has to work
> wherever the focus happens to be sitting -- except in a text
> box, which swallows it first because it has focus.
