# `editor/settings.py`

Comments lifted out of `editor/settings.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 33** — before `def sections() -> list[tuple[str, list[tuple]]]:`

> (label, key, kind, spec, default, note). A "num" spec is
> (low, high, step, decimals, suffix); a "choice" spec is the list of values.


## `SettingsDialog.__init__`

**line 153** — before `self.resize(T.px(560), T.px(460))`

> The same size the Keys dialog settled on, and for the same reason:
> a dialog that sizes itself to its contents puts its Ok button off
> the bottom of a short screen.


## `SettingsDialog._control`

**line 176** — before `w.setKeyboardTracking(False)`

> Off, so a half-typed number is not read as a setting on its way
> past: "5" is not what somebody typing "52" meant.
