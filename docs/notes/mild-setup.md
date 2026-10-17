# mild-setup.py

## 2026-10-17 — `--uninstall`

Asked for: a way to take back out what setup installed "in case you don't
actually need it". It walks the same list as the install, per feature, and
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
