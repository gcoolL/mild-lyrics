# `editor/settings.py`

Comments lifted out of `editor/settings.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 33** — before `def sections() -> list[tuple[str, list[tuple]]]:`

> (label, key, kind, spec, default, note). A "num" spec is
> (low, high, step, decimals, suffix); a "choice" spec is the list of values.


## `SettingsDialogue.__init__`

**line 153** — before `self.resize(T.px(560), T.px(460))`

> The same size the Keys dialogue settled on, and for the same reason:
> a dialogue that sizes itself to its contents puts its Ok button off
> the bottom of a short screen.


## `SettingsDialogue._control`

**line 176** — before `w.setKeyboardTracking(False)`

> Off, so a half-typed number is not read as a setting on its way
> past: "5" is not what somebody typing "52" meant.

## 2026-10-17 — Search, and the Spectrogram setting

Both settings windows filter as you type: the drawer (glass.Drawer.find) lists
every matching row across sections under their section names; the classic
dialogue hides rows and empty tabs. A row matches when every word of the query
is in its section, label, note or choice names. Picking a section clears the
query; Esc clears it before it closes the drawer. Rows are still only defined
in `sections()`, so new ones are searchable with no extra work.

`spec_on` (Look ▸ Spectrogram) is the mixture spectrogram, kept across songs
and restarts. The Vocal ▸ Spectrogram toggle writes it too. A song opening
(`load_envelope`) builds it without taking the strip from Vocal view, and
turning Vocal view off brings it back.
