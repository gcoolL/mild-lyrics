# `mild-lyrics/caches.py`

Comments lifted out of `mild-lyrics/caches.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `entries`

**line 88** — before `dict(key="audio", label="Fetched audio", path=_audio_dir(),`

> Not `root / "audio"`: the copies land in `local_align.AUDIO_DIR`,
> which is `fetched/` beside the code, and always have. This row was
> pointing at a directory nothing writes, so the largest thing on the
> disk -- eight gigabytes on this machine -- was the one thing the
> Storage dialog could not see or clear.

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
