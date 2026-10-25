# `mild-lyrics/caches.py`

Comments lifted out of `mild-lyrics/caches.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `entries`

**line 88** — before `dict(key="audio", label="Fetched audio", path=_audio_dir(),`

> Not `root / "audio"`: the copies land in `local_align.AUDIO_DIR`,
> which is `fetched/` beside the code, and always have. This row was
> pointing at a directory nothing writes, so the largest thing on the
> disk -- eight gigabytes on this machine -- was the one thing the
> Storage dialogue could not see or clear.

**line 97** — before `dict(key="vocal-view", label="Separated vocals", path=root / "vocal-view",`

> Audio as well as pictures since the editor learned to PLAY the
> separated vocal, which makes this the one row here that grows by
> tens of megabytes a song rather than by kilobytes. Not `keep`:
> every byte of it is re-derivable from the audio, at the cost of a
> separation per song.


## module level

**line 138** — before `CONFIG, GENIUS_KEY = LS.GENIUS_CONFIG, LS.GENIUS_KEY`

> The file and key from_genius reads its token out of. Named there because
> that is where a provider needs them, and taken from there here so the two
> readers of one credential cannot drift apart.


---

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/caches.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 2** — the module docstring

> What this app has left on the disk, and how to get rid of it.
>
> Everything here is derived. Nothing in the cache is the only copy of
> anything -- art is re-fetched, lookups are re-asked, alignments are
> re-run -- which is what makes clearing any of it safe, and is also why it
> grows without anybody noticing: 900 MB of album art and animated covers
> accumulates one song at a time and is never once in the way.
>
> Two of the entries are the exception, and they are marked `keep`:
>
>   * `aligned` is work this machine did. Re-running it costs minutes per
>     song and a GPU, and on a machine without one it may not be repeatable
>     at all.
>   * `editor-history` is the backup net -- the copies taken before a
>     document was replaced or a file written over. It is the one thing here
>     that exists precisely because something else was lost.
>
> `sources.json` is a third, quieter case: it pins WHICH copy of a track an
> alignment was made against, so clearing it does not lose a timing but does
> lose the reason two runs agreed. It is marked `keep` for that reason.
>
> Qt is deliberately not imported. The player, the editor, doctor.py and the
> command line all need this answer, and only two of them are a GUI.
>
>     python3 caches.py              what is on the disk, and how big
>     python3 caches.py --clear art  clear one by name

### `_config_files`

**line 94** — from the docstring, `def _config_files() -> tuple[pathlib.Path, ...]:`

> The settings file and the generation behind it.
>
> The player rotates gui.json to gui.json.bak on every write and reads the
> backup when the live file will not parse. A token cleared from one and
> left in the other is still a token on the disk, and one corrupted save
> away from coming back.

### `_token_in`

**line 104** — from the docstring, `def _token_in(path: pathlib.Path) -> str:`

> The Genius token a settings file holds, read again only if it changed.
>
> The Storage row in the settings asks for the credentials on every frame
> it is on screen, and each ask parsed both generations of the file --
> which also holds every hand fix and offset. Raises where the file is
> missing or does not parse, as reading it does.

### `credentials`

**line 119** — from the docstring, `def credentials() -> list[dict]:`

> What this copy is holding that identifies somebody.
>
> Four, and they are different in kind. The Genius token is typed in by a
> person, is theirs, and unlocks their account's rate limit -- handing a
> copy of this to somebody else hands them that. A Spicy Lyrics SECRET key
> is the same in kind and worse in degree: it is the application's, it is
> shown once when it is made, and anything holding it can spend that
> application's whole request budget. The Apple one is lifted out of the web
> player's own JavaScript, is the same key every visitor to music.apple.com
> is given, and belongs to nobody; it is here because it expires and
> re-fetching it means downloading three megabytes. Musixmatch's is the
> same kind of nobody's.
>
> None of them is ever written into the program files, so a checkout of
> this repository has never carried one. They are on the machine, which is
> exactly where a copy being passed on will not look. The exception, and it
> is not one of these, is a PUBLISHABLE Spicy Lyrics key: it is public by
> design and ships in the source, which is why a secret one must not.

### `forget`

**line 165** — from the docstring, `def forget() -> tuple[int, list[str]]:`

> Drop every stored credential. Returns (how many, what happened).
>
> The Genius token is removed from the settings file rather than the file
> being deleted -- everything else in there is preferences somebody spent
> time on, and losing a font size to clear a token is not a trade anybody
> asked for.

### `measure`

**line 202** — from the docstring, `def measure(path: pathlib.Path) -> tuple[int, int]:`

> (bytes, files) under a directory, or for one file. Never raises.
>
> One walk for both. `survey` used to ask `size` and then `count`, which
> walked every cache twice -- tens of thousands of files, on the thread the
> window draws on -- and built a Path for each file on the first of them.
> Counted the way os.walk counts: a link to a directory is not descended
> into and is not a file, and a file that cannot be read is counted and
> adds nothing.

---

## Earlier lift — 2026-08-23

Comments lifted out of `mild-lyrics/caches.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 43** — before `def entries() -> list[dict]:`

> key, what it is called on screen, the path under the cache root, and
> whether it is a directory. `keep` marks the ones worth a second thought.


### `entries`

**line 81** — before `for key, label, sub, note in (`

> The training side, listed only where it exists: a copy shipped without
> the sync tree has none of it, and four rows reading 0 B would be four
> rows of noise.


### module level

**line 107** — before `# --------------------------------------------------------------------------`

> credentials, which are not caches even though one of them is cached


### `forget`

**line 172** — before `for cfg in _config_files():`

> The settings file AND the generation behind it. The player rotates
> gui.json to gui.json.bak on every write and reads the backup when the
> live file will not parse -- so clearing only the first leaves a copy of
> the token on the disk, and one corrupted save away from coming back.
