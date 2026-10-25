# `editor/ribbon.py`

Comments lifted out of `editor/ribbon.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `Ribbon.__init__`

**line 66** — before `well = QWidget()`

> One well holding three segments, rather than three buttons floating
> side by side: it is a single choice and should look like one.


## `Ribbon.apply`

**line 111** — before `for b in self.mode_buttons.buttons():`

> Painted here rather than left to a :checked selector. Qt only
> re-evaluates a stylesheet when it is set, and the checked segment
> came out looking disabled -- the one control that must always be
> legible is the one saying which mode you are in.

**line 124** — before `rule = self._rule_before(g)`

> The rule before a hidden group would be a stray line, so it
> travels with it.

## Lift — 2026-10-25

Docstrings shortened in `editor/ribbon.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The bar across the top: what mode you are in, and what you can do in it.
>
> A ribbon rather than a menu because this is a tool with about forty verbs in
> it, and forty verbs behind a File/Edit/View menu is forty things nobody finds.
> The mode buttons are deliberately large -- they are the most-used control in
> the window and the one it is worst to miss.
>
> Modes decide what is SHOWN, never what is possible. The timing keys work while
> writing words and the word menu works while timing; the ribbon only puts away
> the buttons that have nothing to say in the mode you are in.
