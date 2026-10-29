# `install.ps1`, `install.sh`, `install.cmd`

## 2026-10-29 — choosing what to install

Goal: an install that says up front what it will put on the machine and lets
each part be left out. The installers used to run `mild-setup.py --yes --for
both`, which installed everything but the vocal separation with no choice.

**One list, three ways to show it.** `mild-setup.py --catalogue` prints what
an install can include on this machine: the two apps, then categories (the
setup groups, plus Programs it runs, Spotify through Spicetify and
Shortcuts), each with a one-line `use`, the longer `why`, the app it belongs
to, and items that are on by default (the vocal separation is off). Groups
with the same title and app are one category (`liveviz` + `liveviz-win`).
`core` is `locked`: it cannot be unticked anywhere. ffmpeg is listed only
when it is missing and the package manager needs no password (winget,
Homebrew); the Spotify category only when Spicetify is on PATH.

- Windows: a WinForms window (`Show-Checklist`). App checkboxes on top; a
  TreeView with checkboxes below, a bold row per category, whose tick sets
  all its items and follows them (on while any item is). The selected row's
  `use` and `why` show underneath. The tree's own font is the
  bold one: TreeView measures every row in it, so bold `NodeFont`s on a plain
  tree were clipped.
- Linux from a file manager: zenity, a radio list for the apps and then one
  flat checklist (zenity has no tree), categories and their items as rows.
  A category row unticked leaves all of it out; ticked with none of its
  items ticked, it means all of them (`resolve_picks`).
- Apps and categories move together in the window and the terminal list
  (`app_tick`, mirrored as `$appTick`): ticking an app sets its own
  categories back to their defaults (the vocal separation stays off),
  unticking it clears them, and shared categories follow only while the
  other app is off. Ticking anything in an unticked app's category ticks
  that app and leaves its other rows alone. zenity asks for the apps first
  and lists only their categories, which comes to the same.
- A terminal (`install.sh`, and `install.ps1` when no window can be shown,
  e.g. over SSH where WinForms refuses a modal dialog): `--choose FILE`,
  numbered checkboxes (`a`/`b` the apps, `3` a category, `3.1` an item).

**Order.** Folder, Python, download into a temp folder, checklist, then copy
into the folder and run setup with `--pick`. Cancelling leaves nothing (a
first install's empty folder is removed). The checklist comes from the
downloaded release's own `mild-setup.py`, so it always matches what is
installed; a release from before `--catalogue` installs everything, as
before. On Windows a missing Python is now asked about before it is
installed.

**`--pick`.** Exactly the ids picked are installed, without further
questions (the vocal separation included when ticked); the rest is printed
as "left out". Installers make only the picked apps' shortcuts, and on a
repair remove the ones that point at this install and are no longer picked.
`.install-picks.json` in the install keeps what was offered and picked, so a
repair starts from the last choice. Only rows that were on the list count as
offered: an app switched off last time keeps its defaults when switched on.

**Finding the install with no menu entries.** `install.sh` looked for the
install through `mild-lyrics.desktop`. It now tries the editor's entry too,
then the default folder. An install in another folder with no menu entries
can only be found with `--dir`. Windows always has its Settings ▸ Apps entry.

Tested: the terminal and zenity paths end to end in a sandbox HOME (a stand-in
zenity answering from a plan; pip kept offline); the window on the Windows
laptop through a timer that ticks, unticks and presses Install, run modelessly
because SSH is not UserInteractive; the console fallback there with a folder
path containing spaces.

## 2026-10-27 — install.sh from a file manager

Opened from a file manager, a script has no terminal: `/dev/tty` can't be
opened, so it used to run silently on the defaults with nothing on screen.
Now, with no terminal and a display (`DISPLAY` or `WAYLAND_DISPLAY`):

- **zenity, if it is installed** (GNOME has it; on this KDE machine other
  apps pulled it in), runs the same flow as dialogs. The folder question
  offers Install / Choose folder... / Cancel, with a GTK folder chooser. The
  long part (download, `mild-setup.py`, menu entries) runs in the background
  under a pulsating `--progress` window whose label is the log's latest line.
  At the end comes Start Mild Lyrics / Close, or, if the install failed, the
  whole log in a `--text-info` window. Opening it on an existing install
  offers Repair / Uninstall / Cancel. Password prompts go through `pkexec`
  instead of `sudo`, which needs a terminal. All output goes to
  `~/.cache/mild-lyrics-install.log`.
- **Without zenity**, it reopens itself in a terminal emulator:
  `xdg-terminal-exec` first, then the desktop's own (konsole, kgx/ptyxis/
  gnome-terminal, xfce4-terminal, mate-terminal), then the common rest. Each
  needs its own way of being handed a command. `MILD_HOLD=1` keeps the window
  open at the end with "Press Enter to close". On macOS, Terminal is asked
  through `osascript`, which has not been run on a Mac.
- **With neither**, it shows a notification (`notify-send`, else `xmessage`)
  saying which command to run.
- `--gui` forces the dialogs from a terminal. `MILD_NO_GUI` turns them off.
  `curl | sh` always has a terminal, so it is unchanged.
- The script can't fix the one remaining obstacle: browsers save it without
  execute permission, so a double-click opens it in a text editor until it is
  allowed to run. The README says how.
- POSIX `sh` details: the progress job is `( cmd ) &` followed by
  `wait $pid`, which returns the job's status. That avoids `pipefail`, which
  `sh` doesn't have. `install_files` checks each step itself, because
  `set -e` is suspended inside a function called from an `||` list.
  Subshells don't inherit the EXIT trap, so the background job doesn't
  delete `$tmp`.
- Tested 2026-10-27, with no dialog on the real screen:
  - The real zenity ran in a headless `kwin_wayland --virtual --xwayland` on
    a private bus with no service activation (see the headless KWin bench
    memory).
  - It was driven by a zenity shim in PATH that shows each real dialog,
    screenshots it through Xwayland (`import -window`) and answers from a
    plan. xdotool keys and clicks don't reach Xwayland there, because newer
    Xwayland sends XTEST through a portal.
  - The runs covered: a fresh install with Choose folder → an unwritable
    folder → the error → Install; the real progress window closing itself on
    the final `100`; the done dialog; the Repair/Uninstall dialog; and an
    uninstall that kept settings.
  - The no-zenity relaunch (konsole) and the notification fallback were
    tested with stand-ins on PATH, and the Enter hold under `script(1)`.

## 2026-10-27 — release assets, and choosing the folder

- **Release assets.** `.github/workflows/release-installers.yml` runs when a
  release is published. Releases are made with `gh release create`, which
  uses a user token and so triggers workflows, unlike `GITHUB_TOKEN`. It
  uploads `install.cmd`, `install.ps1` and `install.sh` from the tag, so
  each one can be downloaded alone from the release page, and from
  `releases/latest/download/<name>`, the address the README commands use.
  The checkout applies `.gitattributes`, so `install.cmd` is uploaded with
  CRLF line endings. When `install.cmd` is run on its own, it fetches the
  latest release's `install.ps1` with `WebClient.DownloadString`, which
  always returns a string (assets are served as octet-stream), and falls back
  to `main` for releases from before the workflow.
- **The folder.** A first install asks: Enter for the default, a typed path
  (`~` and `%VARS%` expanded), or, on Windows, B for Explorer's folder
  picker. If the picker throws, the prompt falls back to typing. A folder
  that already holds other things gets a `mild-lyrics` folder inside it,
  because uninstalling deletes the install folder whole. A folder that
  cannot be written to (Program Files without administrator rights) is
  refused before anything downloads. `-Dir`/`--dir`/`MILD_DIR` skip the
  question.
- **Trying a build before release.** `MILD_ZIP` names a zipball on disk
  (one top folder, as GitHub's) to install in place of the latest release,
  which may predate flags the installer passes (`--no-doctor`).
- **Finding it again.** No extra state is written. A re-run or an uninstall
  reads the location from what the install already left: the
  `InstallLocation` of the Settings > Apps key on Windows, the `Path=` line
  of `mild-lyrics.desktop` on Linux, and the `cd "…"` line in
  `Mild Lyrics.app` on macOS. The latter two are written by
  `doctor.make_shortcut`. A location that is a git checkout does not count,
  since a dev checkout's own `.desktop` points at it. A re-run updates in
  place. Moving an install means uninstalling it first.
- Tested on Linux in the sandbox: a typed `~/…` path into a non-empty folder
  (the `mild-lyrics` folder was made inside it, and uninstall left the other
  file), a re-run found by `.desktop`, `--dir` into an unwritable folder
  refused, and an unknown flag. The Windows side has not been run.

## 2026-10-27 — one-line installers

Before these, installing meant downloading the repository, opening a terminal
inside it and running `setup.sh` or `setup.cmd` there. The app then ran out of
whatever folder the download had landed in, often Downloads. The installers
take that path out of people's hands:

- **Where it goes.** `%LOCALAPPDATA%\Programs\mild-lyrics` on Windows (the
  per-user Programs folder, no administrator needed),
  `${XDG_DATA_HOME:-~/.local/share}/mild-lyrics` on Linux, and
  `~/Library/Application Support/Mild Lyrics` on macOS. `MILD_DIR` (or
  `-Dir` on Windows) picks another folder. None of these overlap the settings
  and cache folders (`lyric_sources.config_root`/`cache_root` + `mild-lyrics`),
  so uninstalling can keep those or delete them separately.
- **What goes there.** The latest release's zipball, the same archive the
  updater installs from. With no `.git` folder, `updater.is_checkout()` is
  false, so later updates are written over the folder as zip installs, and
  `.venv` is left alone because no release contains one. A folder that
  *is* a git checkout is refused and pointed at `setup.*`.
- **Packages.** The installer runs `mild-setup.py --venv --yes --for both
  --no-doctor` from the downloaded release, so every check, venv rule and
  install stays in one place. `--yes` takes each default answer, which leaves
  out the heavy torch/demucs group. `--no-doctor` was added for the
  installers. A release older than the flag runs doctor at the end instead,
  which is harmless; the installers look for the flag in the file before
  passing it. Success is judged by whether `.venv`'s Python imports
  `PyQt6.QtWidgets`, not by setup's exit code: a warning there (no
  Spicetify, no display) is not a failed install.
- **Re-running** repairs: the files are written again, the existing `.venv`
  is reused, and only missing packages are installed.

### Windows

- **The command is `irm … | iex`**, the same form Spicetify's own installer
  uses, which this app's users have already run once. It needs no execution
  policy change. `install.cmd` wraps it for a double-click: it runs the
  `install.ps1` next to it, or fetches the latest one.
- **Store Python is skipped.** It redirects new files under AppData into its
  package's LocalCache (see `noconsole.real_path`). A `.venv` it made in
  `%LOCALAPPDATA%\Programs` could then be invisible to Explorer, and the
  shortcuts would point at nothing. The `WindowsApps` `python.exe` stub is
  never run, since running it opens the Store.
- **Python choice.** The candidates come from `py -0p`, `python`/`python3`
  on PATH and `%LOCALAPPDATA%\Programs\Python\Python3*`. 3.12 is preferred,
  then 3.13, 3.11, 3.14, 3.10, so that every dependency has a wheel rather
  than a source build. If none is found, python.org's 3.12.10 installer
  (the last 3.12 with a binary installer) runs per user and quietly, without
  the py launcher. The launcher is left out because a machine-wide launcher
  that is already installed can make a per-user one fail.
- Shortcuts go straight at `.venv\Scripts\pythonw.exe` + the `.pyw`, so no
  `usevenv` hop is needed. They go in the Start menu (both programs) and on
  the desktop (Mild Lyrics). An `HKCU\…\Uninstall\MildLyrics` key puts the
  app in Settings > Apps. Its UninstallString runs the folder's own
  `install.ps1 -Uninstall`. A release from before the installer has no copy,
  so one is fetched from `main`. No DisplayVersion is written, because the
  updater would leave it stale.
- **Session hygiene under `iex`.** The script runs in the caller's session,
  so nothing sits at the top level except `param()`, functions and `Main`.
  Preferences are set inside functions, and nothing calls `exit`, which
  would close the caller's window.
- **Windows PowerShell 5.1 traps** that shaped the code: a native program's
  redirected stderr turns into terminating errors under `Stop`, so probes
  run with `Continue`. Double quotes inside native arguments arrive
  unescaped, so the `-c` probe uses none. The download progress bar slows
  `Invoke-WebRequest` down badly. `Copy-Item -Recurse` can nest a folder
  inside an existing one, so the release is merged with `robocopy`.
- **Uninstall** offers to close a running copy, matched by the install path
  in a python process's command line. It removes shortcuts only when they
  point into the folder, and the `mild-lyrics://` handler only when its
  command does. Settings and caches are asked about, defaulting to keep.
  Spicetify's flag and the "Spotify (debug port)" shortcut stay.
- Not run on Windows yet: the laptop was asleep when this was written. The
  `param()` + `iex` form is the one Chocolatey's and Scoop's installers use.

### Linux and macOS

- **`curl | sh` means stdin is the script.** Everything sits inside `main`,
  so a download that breaks off partway runs nothing. Every child gets
  `/dev/tty` or `/dev/null` as stdin, never the pipe, because pip or setup
  reading stdin would swallow the rest of the script.
- **Python choice.** `python3` is used when it is 3.10–3.14, so a
  distribution's own PyQt6 is shared through the `--system-site-packages`
  venv. Otherwise the versioned names are tried in the same preference
  order as on Windows. If none is found, the installer prints the package
  manager command and offers to run it (sudo). On macOS it offers Homebrew,
  or else python.org's pkg followed by its `Install Certificates.command`.
  Debian's separate `python3-venv` is checked and offered too.
- Unpacking is done in Python's `zipfile`, since `unzip` is often missing.
  The menu entries come from `doctor.make_shortcut` (`.desktop` files, or
  `.app` bundles in `~/Applications`), run in the venv's Python so that
  `Exec` names it.
- Tested 2026-10-27 on Arch, in a throwaway `HOME`, against a fake `curl`
  serving this tree as the release: a fresh install, a re-run and
  `--uninstall`. macOS was not run.
