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
