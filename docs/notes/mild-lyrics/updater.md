# `mild-lyrics/updater.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/updater.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Finding, installing and announcing new releases of Mild Lyrics.
>
> Everything comes from GitHub, which is the only place a release exists: the
> latest release says which version is current, its notes are the changelog,
> and its tag names the source to install. No login is needed for any of it --
> the public API allows sixty unauthenticated requests an hour, and this makes
> one on startup.
>
> Two kinds of install, updated two different ways:
>
>   - a copy downloaded as a zip. The release's own source archive is fetched
>     and its files are written over the program's. Only files that are IN the
>     release are touched; the settings, caches and lyrics live elsewhere or
>     are not part of a release, so they are left exactly as they were.
>
>   - a git checkout. It is moved to the release tag with a fast-forward, and
>     only when that is safe: nothing uncommitted, and nothing committed that
>     the release does not already contain. A checkout somebody is working in
>     is never touched -- the caller is told an update exists instead.
>
> Qt is deliberately not imported here, so this can be driven and tested
> without a window.

### `_open`

**line 49** — from the docstring, `def _open(req, timeout: float):`

> urlopen, with certifi's certificates where the system's are missing.
>
> Python from python.org on macOS ships without a certificate store until
> its "Install Certificates" script has been run, and every HTTPS request
> then fails verification. certifi, where it is installed, is the same
> bundle that script would have put there.
