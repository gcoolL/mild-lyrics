# mild-setup.py

## 2026-10-17 — `--uninstall`

A way to take back out what setup installed, for when it turns out not
to be needed. It walks the same list as the install, per feature, and
every question defaults to no; `--yes` only removes things named on the line.

What it will and will not touch:

- **Packages** are classed by where they live: the venv, `pylibs/`, the user
  site-packages, or the system. System ones (the distribution's, e.g. Arch's
  PyQt6, numpy, aioquic, dbus-python) are only reported. User-site ones get an
  extra line saying other programs on that Python can use them.
- **Dependencies** go along only if nothing that stays requires them, checked
  over every distribution the interpreter can see, not just this project's.
  On this machine `soundfile` and `torch` are held by `audio-separator`, so
  removing the waveform or the vocal group leaves them. A root another
  feature names (numpy, for the waveform) is never taken as someone else's
  dependency unless that feature was removed earlier in the same run.
  Requirements behind `extra ==` markers are skipped: a plain install never
  pulled them in.
- **pylibs** is cleaned from each dist's RECORD by hand, since pip will not
  uninstall from a `--target` folder and refuses outright on a PEP 668
  Python. `--target` moves console scripts into `pylibs/bin`, but RECORD
  still names them `../../bin/<name>`; those are mapped back.
- **User site** removal on an externally-managed Python needs
  `--break-system-packages` even for pip uninstall; it is passed only for
  dists that live in the user site.
- **Shortcuts** are deleted only when they point at this checkout (or, for the
  Spotify one, at spicetify), so a packaged `mild-lyrics.desktop` from
  elsewhere is left alone. The app shortcuts are doctor.py's, offered here
  because setup offers to run doctor.
- **demucs weights** are matched by demucs' `<8 hex>-<8 hex>.th` names in
  torch's hub cache; other checkpoints there stay.
- **ffmpeg / a non-pip yt-dlp** are never removed: other programs use them.
  On brew/winget, the only managers setup ever runs, the uninstall line is
  printed.
- **The debug port** is removed from Spicetify's flags keeping the rest. It
  may well have been there before setup.

Tested in a sandbox copy (own `.venv`, `pylibs`, HOME, fake dists for the
dependency rules). The debug-port and open-spotify paths were not run against
the real Spicetify config, and the Windows `.lnk` path is untested.

## Lift — 2026-10-25

Docstrings shortened in `mild-setup.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### `wrap`

**line 89** — from the docstring, `def wrap(text: str, first: str = "    ", rest: str = "    ") -> None:`

> A paragraph at a width a terminal will not fold for us.
>
> The prose here is the point -- a missing package is only useful named
> next to what it is for -- and prose the terminal wraps itself breaks
> wherever the window happens to end, which is never where a sentence
> does.

### `spawn`

**line 95** — from the docstring, `def spawn(cmd: list[str]) -> int:`

> Run a child that prints for itself, after emptying our own buffer.
>
> Our output is block-buffered the moment this is piped into anything --
> a log file, a pager, a bug report -- while a child writes to the same
> place immediately. Without the flush, every line pip and doctor print
> lands AHEAD of the lines here that introduce them, and the report reads
> back in an order nothing actually happened in.

### `Dep`

**line 123** — from the docstring, `class Dep:`

> One importable package, and how to tell whether it really works.
>
> `module` is what the code imports and `pip` is what pip is asked for;
> they differ often enough (`soundfile`, `silero-vad`, `dbus-python`) that
> keeping one field for both would be a bug waiting in the install line.
>
> `smoke` is an expression run in the child with the imported module bound
> to `m`. It exists for the packages whose import proves the least: a
> compiled extension that loaded is not a library that found the shared
> object it wraps.
>
> `instead` is a second module that answers the same question, and the row
> is satisfied by either. One thing needs it -- Windows publishes its media
> bindings under two package names, and the older one is what this
> project's own instructions used to ask for, so a machine that followed
> them has everything it needs under a name that is not in the `pip`
> field.

### `Group`

**line 135** — from the docstring, `class Group:`

> A feature, and the packages without which it is simply not there.
>
> Grouped by what is lost rather than by size, because that is the only
> form in which the question "do I want this" can be answered by somebody
> who has not read the source. `need` is what a missing one means:
>
>     required  the window and the editor will not start
>     wanted    a visible feature goes missing, and the cost is small
>     optional  a nicety; most machines are fine without it
>     heavy     gigabytes, and the group that can make a machine worse

### `died`

**line 372** — from the docstring, `def died(code: int) -> str:`

> How a child interpreter ended, said in words rather than in a number.
>
> Worth the lookup: the two codes that matter here are the two that an
> install can be wrong in a way no import error will ever mention. An
> illegal instruction is a wheel built for a newer CPU than this one; an
> access violation or segmentation fault is usually a compiled extension
> meeting a shared library it was not built against.

### `probe`

**line 395** — from the docstring, `def probe(python: pathlib.Path, deps: tuple[Dep, ...]) -> dict[str, dict]:`

> Import each of `deps` in one child, and say what happened to each.
>
> One child rather than one per package, because importing torch four
> times over costs more than the rest of this script put together -- and
> one child is all it takes to attribute a crash, as long as the child
> prints as it goes. The row for a package that never printed is filled in
> here from how the child died, which is the only way a wheel that is
> wrong for this CPU ever gets a name printed next to it.

### `old_winrt`

**line 446** — from the docstring, `def old_winrt() -> str:`

> The abandoned `winrt` distribution's version, or "" if it is not here.
>
> A different project owns the bare name `winrt` on PyPI. Its last release
> was 2021 and its newest wheel is for CPython 3.9, and it installs a
> regular `winrt` package -- the same name the real projection hangs its
> namespaces under. While it is there nothing can import
> winrt.windows.anything, and on 3.10 and newer pip usually cannot install
> it at all: no wheel, so it tries to build it and wants a C++ toolchain.
>
> `pip install winrt` is the obvious thing to type and it is the wrong
> package. The real one is winrt-runtime plus a winrt-Windows.* per
> namespace, which is what the winmedia group above asks for.

### `report`

**line 458** — from the docstring, `def report(group: Group, rows: dict[str, dict]) -> list[Dep]:`

> Print a line per package and hand back the ones that are not working.
>
> A package that imported and then failed its own smoke test is returned
> with the missing ones. Reinstalling it is not certain to help, and it is
> certainly not working, so it belongs on the same list rather than in a
> footnote under a line that says OK.

### `machine`

**line 537** — from the docstring, `def machine() -> dict:`

> What this machine is, for the one line that says so.
>
> It used to be a verdict as well: the memory, the CPU's instruction set and
> the card were what decided whether to offer the heavy group, which could
> leave a machine worse than it found it. Nothing installed here is heavy
> any more, so this is only ever printed.

### `managed`

**line 543** — from the docstring, `def managed(python: pathlib.Path) -> bool:`

> Whether this interpreter belongs to the operating system.
>
> PEP 668: a distribution that manages its own site-packages drops an
> EXTERNALLY-MANAGED file next to the stdlib, and pip refuses to write
> there -- including `pip install --user`, which is the line most
> instructions still give. Worth knowing BEFORE an install is offered,
> because on those machines the honest options are a virtual environment
> or the distribution's own packages, and neither is pip's default.

### `make_venv`

**line 578** — from the docstring, `def make_venv(venv: pathlib.Path) -> pathlib.Path | None:`

> Build a virtual environment at `venv` and hand back its interpreter.
>
> --system-site-packages on purpose. On a machine where the distribution
> already ships PyQt6 or numpy, a bare environment would have this project
> download its own copies of both and then run against them; inheriting
> what is already there means the environment holds only what is actually
> missing, which on the machines that need a venv at all is usually two or
> three small packages rather than a second Qt.

### `Asker`

**line 603** — from the docstring, `class Asker:`

> Every yes/no in one place, so --check and a pipe cannot be got wrong.
>
> A prompt that nobody is there to answer must not be a prompt. With
> --check the answer is always no and nothing is installed; with no
> terminal on the other end the default stands, so this can be run from a
> script or a first-boot image without hanging on a question.

### `package_manager`

**line 682** — from the docstring, `def package_manager() -> tuple[str, list[str]] | None:`

> This platform's own installer, as (name, command prefix).
>
> Only the user-level ones are ever offered to be RUN. A Linux install
> needs root, and a script that decides on its own to ask for root is a
> script that has taken a decision that was not its to take -- so those
> are printed instead.

### `spicetify_port`

**line 719** — from the docstring, `def spicetify_port(ask: "Asker") -> None:`

> Put the debug port in Spicetify's launch flags, keeping the rest.
>
> The window reads the player through that port -- on Windows it is the only
> way in, and everywhere it is what the search, the queue, the visualiser
> and the now-playing come from. It is a one-line setting that nobody would
> guess, and doctor.py used to do nothing but print the line and ask the
> reader to paste it in.
>
> THROUGH THE CLI, WHICH IS THE THING THAT WAS SUPPOSED NOT TO WORK. The
> advice was to edit config-xpui.ini by hand because PowerShell mangles an
> argument starting with a dash -- but that is PowerShell's parsing, not
> spicetify's, and nothing here goes through a shell: subprocess hands the
> arguments to the process as a list. The flag arrives exactly as written.
>
> Kept rather than replaced. Spicetify joins its flags with "|", and this
> machine's were --remote-debugging-port, --ozone-platform=wayland and
> --enable-features=..., which is somebody's working Wayland setup. Writing
> the port on its own would have taken the other two with it.
>
> Never in --check mode: a check that changes a setting is not a check.

### `spotify_shortcut`

**line 765** — from the docstring, `def spotify_shortcut(ask: "Asker") -> None:`

> Offer a launcher that starts Spotify through `spicetify auto`.
>
> The launch flags only apply when Spicetify starts Spotify, so the
> ordinary Spotify icon opens it with no debug port and the window quietly
> loses the search, the queue and the visualiser. This is the icon to
> click instead. Asked only where spicetify is there to run.

### `open_spotify_setting`

**line 858** — from the docstring, `def open_spotify_setting(ask: "Asker") -> None:`

> Ask whether Mild Lyrics should start Spotify, and write the answer.
>
> The setting (Player -> Open Spotify) runs `spicetify auto` when the
> window opens and Spotify is not running, which is what guarantees the
> debug port. Written straight into the window's settings file, keeping
> everything else in it; asked only where spicetify is there to run.

### `check_programs`

**line 898** — from the docstring, `def check_programs(python: pathlib.Path, extra: list[str],`

> The programs this project runs rather than imports.
>
> None of them is a pip package by nature, so the line printed here is the
> package manager's rather than pip's. It is only OFFERED to be run where
> running it needs nobody's password: brew and winget install for the
> person who asked, while every Linux manager here wants root, and a
> script that decides on its own to ask for root has taken a decision that
> was not its to take.
>
> yt-dlp is the exception and gets offered through pip as well. It is pure
> Python, and it is the one program on this list that goes stale on a
> schedule somebody else sets -- when a site changes, a yt-dlp from the
> distribution can be months behind a working one.

### `check_qt_opens`

**line 970** — from the docstring, `def check_qt_opens(python: pathlib.Path) -> None:`

> Whether Qt can start here, which importing PyQt6 does not answer.
>
> The failure this is for is the commonest one there is on Linux and the
> least self-explanatory: PyQt6 imports perfectly and then "could not load
> the Qt platform plugin xcb", because the plugin is there and the system
> libraries it links against are not. Nothing is shown -- a QApplication
> with no window on it draws nothing -- so this costs a second and puts no
> window over anybody's screen.

### `choose_python`

**line 1001** — from the docstring, `def choose_python(args, ask: Asker) -> pathlib.Path | None:`

> Which interpreter everything below is checked and installed against.
>
> Four ways this can go, and the order matters. Already inside a virtual
> environment: use it, that is what it is for. Asked for one: make it.
> Found one sitting in the project: offer it, because a check run against
> the system Python on a machine that keeps its packages in .venv reports
> a pile of missing packages that are not missing. Otherwise this Python,
> whatever it is.

### `install_plan`

**line 1040** — from the docstring, `def install_plan(python: pathlib.Path, args,`

> The extra pip arguments this machine needs, or None if it cannot.
>
> The externally-managed case is the whole of this function. On Arch,
> Debian, Fedora and the rest, the system Python's site-packages belongs
> to the distribution, pip refuses to write into it, and --user is refused
> with it -- so the two honest answers are a virtual environment or the
> distribution's own packages. --break-system-packages is the third, and
> is not offered here without being asked for by name, because what it
> breaks is the machine's own tools rather than this project.

### module level (comment)

**line 1028** — before `TARGETABLE = {"words", "multiplayer", "japanese"}`

> Pure Python, so they can live in PYLIBS rather than in a venv: what a
> system-Python install that declines the venv can still have. Multiplayer
> counts: aioquic and pylsqpack ship abi3 wheels, one build for every Python
> from 3.10 on, so an upgraded system Python does not strand them -- and the
> one version-bound thing pip puts beside them (cffi's backend) is shadowed
> by the distribution's own, which the app's path puts first. Sudachi too:
> sudachipy is an abi3 wheel and its dictionary is data.
