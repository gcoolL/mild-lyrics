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

## Lift — 2026-10-25

Docstrings shortened in `editor/settings.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Everything the editor remembers about how you like it, in one window.
>
> WHY THIS EXISTS. The settings were all already here; they were just kept
> wherever the thing they affect happens to be drawn. The type scale was two
> buttons on the transport bar, the tap lag was a spin box beside them, the
> syllable rule was inside the Automatic split dialogue, and which of them were
> remembered between runs was not something the window ever said. That is fine
> for a control you reach for mid-take -- the speed and the volume stay on the
> bar, because they are part of playing the song -- and wrong for the ones you
> set once and forget, which is most of them.
>
> So: a tab per kind, a row per setting, and the same vocabulary the player's
> own menu uses -- "bool", "choice", "num", "text" -- because the two programs
> are one program to whoever is using them, and a setting that reads one way in
> the player and another way here is two things to learn.
>
> WHAT IS NOT HERE. Anything that is a measurement rather than a preference.
> The snap reach lives in What the vocal says, next to the numbers that tell
> you what to set it to; which checkpoint to run lives in the Model dialogue,
> next to what each one scored. Moving those in here would put a number in
> front of somebody with nothing to judge it by.

### `sections`

**line 49** — from the docstring, `def sections(classic: bool = True) -> list[tuple[str, list[tuple]]]:`

> The settings, in tabs. A function because two of the choice lists are
> only known once the machine has been looked at -- which hyphenation
> dictionaries are installed, and what the accents are called.
>
> `classic` is which interface is asking. The classic dialogue has an
> Interface row, because it has nowhere else to put one; the new drawer
> has the switch at its foot and says of the accent that it has none.
