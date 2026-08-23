# `aligner/caches.py`

Comments lifted out of `aligner/caches.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 43** — before `def entries() -> list[dict]:`

> key, what it is called on screen, the path under the cache root, and
> whether it is a directory. `keep` marks the ones worth a second thought.


## `entries`

**line 81** — before `for key, label, sub, note in (`

> The training side, listed only where it exists: a copy shipped without
> the sync tree has none of it, and four rows reading 0 B would be four
> rows of noise.


## module level

**line 107** — before `# --------------------------------------------------------------------------`

> credentials, which are not caches even though one of them is cached


## `forget`

**line 172** — before `for cfg in _config_files():`

> The settings file AND the generation behind it. The player rotates
> gui.json to gui.json.bak on every write and reads the backup when the
> live file will not parse -- so clearing only the first leaves a copy of
> the token on the disk, and one corrupted save away from coming back.
