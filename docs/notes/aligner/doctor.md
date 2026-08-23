# `aligner/doctor.py`

Comments lifted out of `aligner/doctor.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `check_qt`

**line 62** — before `if hasattr(G.QFont, "setVariableAxis"):`

> Variable-font weights need this; without it a font like Roboto can only
> be drawn regular or bold, whatever weight is asked for.


## `check_files`

**line 81** — before `editor = HERE.parent / "editor"`

> The editor is a second program in the same tree and ships with it. It
> is not required -- the player runs perfectly well alone -- so a copy
> without it is worth saying out loud rather than failing over.


## `check_align`

**line 269** — before `plan = [f"{what} on {LA.room('auto', cost, win)[0]}"`

> Asked of the planner rather than guessed at, so this says what would
> actually happen if the tool were run at this moment -- which depends on
> what else is on the card right now, not on what the card is.


## `make_shortcut`

**line 320** — before `pyw = pathlib.Path(sys.executable).with_name("pythonw.exe")`

> Built by a temp .ps1 rather than -Command: the paths carry spaces and
> the nested quoting needed to survive one line of PowerShell is where
> this failed before. The Desktop path is asked of Windows rather than
> assumed, because OneDrive moves it and %USERPROFILE%\Desktop is then
> a folder that does not exist.
