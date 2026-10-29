# `mild-lyrics/local_player.py`

## 2026-10-27 — songs listed twice on Windows

Bug: "On this computer" showed some songs twice on Windows (not real
duplicate files). The scan walked each chosen folder on its own and keyed
rows by the path as spelled, so overlapping entries listed every file twice:
the folder picker's `C:/…` beside `C:\…`, a case difference, a folder and
one inside it, or a junction into a folder already walked. The cache kept
every spelling, so the list from it at startup doubled too. Now the walk
skips any directory whose `realpath` (normcased) it has already walked,
`set_dirs` keeps one row per `_norm` path, and `_inside` needs a separator
after the folder (`D:\Music2` is not inside `D:\Music`). Fixed without
seeing the Windows laptop's folder list (unreachable that night); tested
with overlapping, re-spelled and symlinked folders here.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/local_player.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Songs on this computer, played by Mild Lyrics itself.
>
> LocalLibrary scans the chosen folders (tags through mutagen when it is
> installed, the file name when it is not); LocalPlayer plays them with
> QtMultimedia; LocalOverlay puts it in front of the usual transport, so the
> clock follows it like any other player while it is the one in use.
> Notes: docs/notes/mild-lyrics/home_page.md.
