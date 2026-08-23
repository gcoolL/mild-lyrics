# `editor/keys.py`

Comments lifted out of `editor/keys.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 38** — before `ACTIONS = [`

> (name, what it is called on screen, default key, group)


## `remember`

**line 88** — on `        pass`

> a settings file that will not write is not


## module level

**line 89** — before `def bindings() -> dict:`

>                         a reason to stop editing


## `Keys.install`

**line 123** — before `sc.setContext(Qt.ShortcutContext.WindowShortcut)`

> WindowShortcut, not WidgetWithChildren: the strip, the list and
> the ribbon are all children of the window and a tap has to work
> wherever the focus happens to be sitting -- except in a text
> box, which swallows it first because it has focus.
