# `mild-lyrics/doctor.py`

Comments lifted out of `mild-lyrics/doctor.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


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

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/doctor.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### `check_player`

**line 223** — from the docstring, `def check_player() -> None:`

> Whether this machine has a way of being asked what is playing.
>
> One question, three services. Each is the platform's own -- the session
> bus, the Windows media transport, whatever a Mac will still answer -- and
> each is what the any-media-player setting reads, so a machine where this
> is missing is a machine where the window can only follow Spotify over the
> debug port.

### `winrt_whole`

**line 335** — from the docstring, `def winrt_whole() -> tuple[str, list[str]]:`

> Which projection can answer for every namespace, and what is missing.
>
> ("winsdk"|"winrt", []) where one of them is complete, ("", [missing...])
> where winrt is present but partial, and ("", []) where neither is
> installed at all. The three are different problems with different
> answers, and the middle one used to report as the first.

### `check_windows_output`

**line 387** — from the docstring, `def check_windows_output(pkg: str) -> None:`

> Whether the window can name the output device.
>
> A different pair of namespaces from the media transport, and installable
> without them, so this is asked separately -- the symptom of having the
> transport and not these is the Output row simply not being in the song
> panel, with nothing anywhere to say why.
>
> The two halves are not equal. Media.Devices gives the id, which is what
> the per-output timing offset is keyed by: without it every output shares
> one number again. Devices.Enumeration only gives the name, and the window
> has two more ways to come by one, so its absence costs a label at worst.

### `check_windows_players`

**line 456** — from the docstring, `def check_windows_players() -> None:`

> Who has a session open, and whether their clock is worth following.
>
> The same question check_other_players asks the bus, asked the Windows way.
> A session publishes a timeline and the moment it was written, so unlike
> the bus there is no need to sample twice to see whether it moves -- a
> stamp that is old is a session that has stopped writing.

### `check_mac_player`

**line 507** — from the docstring, `def check_mac_player() -> None:`

> Which of a Mac's three doors is open, and what to do about the shut ones.
>
> None of them is guaranteed, and which are available depends on the version
> of macOS and on two settings inside the browsers, so this is the check
> that most needs to say what it found -- "it does not follow my browser" is
> otherwise unanswerable from the outside.

### `check_other_players`

**line 571** — from the docstring, `def check_other_players() -> None:`

> Who else is on the bus, and whether the window could follow them.
>
> For the any-media-player setting. What that needs from a player is a
> position that MOVES: MPRIS makes the property required, a player with
> nothing to put there publishes a zero that never changes, and that is the
> one failure here which looks like success -- the song plays and the words
> sit at 0:00 for the whole of it. It cannot be read off one sample, so a
> player that says it is playing is asked twice, a third of a second apart.
>
> Nothing here is a failure. Nobody has to have a second player, and a
> player that is merely paused is not being judged.

### `check_caches`

**line 637** — from the docstring, `def check_caches() -> None:`

> What the app has left on the disk, and what it would take to get back.
>
> A warning at worst, and usually not even that -- a large cache is the
> app working, not the app broken. It is here because it is the one thing
> on this list nobody discovers on their own: art and animated covers
> accumulate one song at a time, and the first anybody knows of it is a
> full disk.

### `check_token`

**line 659** — from the docstring, `def check_token() -> None:`

> Credentials this copy is holding, and how to be rid of them.
>
> They are not the same kind of thing. The Genius token is typed in by a
> person and is theirs, and a Spicy Lyrics secret key is its application's;
> the Apple and Musixmatch ones are lifted from a web player's own bundle
> and belong to nobody. All of them are worth naming before a copy of this
> goes to somebody else.

### `make_mac_apps`

**line 809** — from the docstring, `def make_mac_apps(launchers=None) -> None:`

> A double-clickable bundle in ~/Applications for each program.
>
> A bundle rather than a .command file on the Desktop, for two reasons that
> are both about how a Mac treats a program rather than about tidiness. A
> bundle appears in Spotlight and the Dock and can be given permissions,
> which matters here more than anywhere: every Apple Events door this app
> reads is granted to an APPLICATION, and permissions granted to a bare
> script are granted to whichever terminal happened to run it.
>
> Written by hand rather than through a tool: this is four small files, and
> the alternative is asking somebody to install one.

### `trace_genius`

**line 842** — from the docstring, `def trace_genius(title: str, artist: str) -> None:`

> The editor's "From Genius" button, one step at a time.
>
> Its own path rather than the chain's provider, because the button does not
> use the provider: the editor asks for a LIST of songs and lets somebody
> pick, where the chain picks one by name and length and hands back a
> document. Two searches, two ways to fail, and the one people press is this
> one.
>
> Three doors, and each of them fails differently. The token is read out of
> the settings file the player writes, and on a machine where the player has
> never been opened there is none. api.genius.com wants it and answers 401
> without one. genius.com/songs/<id>/embed wants nothing and is a different
> host, so a proxy or an antivirus doing TLS interception can shut one and
> leave the other standing -- which is the shape of this on Windows, and why
> the two are asked separately here instead of being called good on the
> first answer.

### `trace_source`

**line 935** — from the docstring, `def trace_source(name: str, title: str, artist: str, length: float) -> None:`

> Ask one source for one song and say how far it got.
>
> Here because "the lyrics do not appear" is not a report anybody can act
> on -- the walk runs ten providers wide on a worker thread and swallows
> every failure by design, so a source that is reachable, finds the song
> and then hands back nothing looks exactly like one that is blocked. This
> puts each step of the walk on the screen in turn.
>
> QQ Music gets its stages named because its path is the longest of them:
> a search, then a download, then a triple-DES its own client implements
> wrongly and a deflate, then the furniture -- a title card and the
> speaker labels -- taken off. Any of those can be the one that fails and
> they fail differently.

### module level (comment)

**line 260** — before `WINRT_NEEDS = ("winrt-runtime", "winrt-Windows.Foundation",`

> EVERY NAMESPACE BY NAME. winrt ships one distribution per namespace, and
> `pip install winrt-Windows.Media.Control` brings only winrt-runtime with
> it: everything that namespace itself imports -- Windows.Foundation, where
> the async operation lives, Windows.Foundation.Collections, where the
> session list lives, Windows.Media, Windows.Storage.Streams -- has to be
> asked for too. Without them the control module still imports, which is
> what made this so hard to see: every probe passed and the first real call
> died on a namespace nobody had named. The `[all]` extra would fetch them,
> but it fetches everything THEY reference as well, recursively -- hundreds
> of packages, most of the Windows API -- and people took the endless
> download for a hang. So the eight that are used are named instead.

### module level (comment)

**line 683** — before `LAUNCHERS = [("mild-lyrics", ROOT / "mild-lyrics.pyw"),`

> Both entries point at the .pyw beside the checkout rather than into it.
> The player's used to name mild-lyrics/lyrics_gui.py directly, and a shortcut
> that names a file inside the tree breaks the day that tree is rearranged --
> which is how renaming aligner/ to mild-lyrics/ left a menu entry running a
> path that no longer existed, silently, because that is what a .desktop file
> does when its Exec is gone. The launchers are the stable door: they are at
> the top, they are what the README tells people to run, and they do their own
> sys.path work.

---

## Earlier lift — 2026-08-23

Comments lifted out of `mild-lyrics/doctor.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

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
