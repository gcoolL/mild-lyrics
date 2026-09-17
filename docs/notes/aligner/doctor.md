# `aligner/doctor.py`

Comments lifted out of `aligner/doctor.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 40** — before `ROOT = HERE.parent`

> The launchers -- both .desktop files and both .pyw stubs -- live one level
> up, beside the editor package. This was looking for them in aligner/, said
> "mild-lyrics.desktop is missing", and installed nothing; which is why
> neither program was ever in the applications menu.

**line 66** — before `def check_python() -> None:`

> -- the checks -------------------------------------------------------------

**line 545** — before `LAUNCHERS = [("mild-lyrics", HERE / "lyrics_gui.py"),`

> -- the shortcut -----------------------------------------------------------


## `make_shortcut`

**line 596** — before `done = []`

> Both of them. The editor has had a .desktop of its own all along and
> nothing ever copied it anywhere a menu looks.

**line 610** — before `if ln.startswith("#!"):`

> A shebang in a .desktop is decoration; KDE reads the file,
> it never execs it.

**line 626** — before `for cmd in (["update-desktop-database", str(apps)], ["kbuildsycoca6"],`

> KDE reads its menu from a cache; a file appearing underneath it is not
> noticed until something says so.


## module level

**line 637** — before `MAC_PLIST = """<?xml version="1.0" encoding="UTF-8"?>`

> What a Mac needs to treat a folder as a program. The shortest Info.plist
> that Finder, Spotlight and the Dock all accept: a name, an identifier, and
> the name of the file inside MacOS/ to run.

**line 699** — before `PROBE = ("Clocks", "Coldplay", 307.0)`

> A song every catalogue in the running order carries, word-timed, so a
> source answering nothing for it is the source and not the song.


---

## Earlier lift — 2026-08-23

Comments lifted out of `aligner/doctor.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### `check_qt`

**line 62** — before `if hasattr(G.QFont, "setVariableAxis"):`

> Variable-font weights need this; without it a font like Roboto can only
> be drawn regular or bold, whatever weight is asked for.


### `check_files`

**line 81** — before `editor = HERE.parent / "editor"`

> The editor is a second program in the same tree and ships with it. It
> is not required -- the player runs perfectly well alone -- so a copy
> without it is worth saying out loud rather than failing over.


### `check_align`

**line 269** — before `plan = [f"{what} on {LA.room('auto', cost, win)[0]}"`

> Asked of the planner rather than guessed at, so this says what would
> actually happen if the tool were run at this moment -- which depends on
> what else is on the card right now, not on what the card is.


### `make_shortcut`

**line 320** — before `pyw = pathlib.Path(sys.executable).with_name("pythonw.exe")`

> Built by a temp .ps1 rather than -Command: the paths carry spaces and
> the nested quoting needed to survive one line of PowerShell is where
> this failed before. The Desktop path is asked of Windows rather than
> assumed, because OneDrive moves it and %USERPROFILE%\Desktop is then
> a folder that does not exist.
