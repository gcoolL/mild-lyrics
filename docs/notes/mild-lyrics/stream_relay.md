# `mild-lyrics/stream_relay.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/stream_relay.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Stream links handed to Qt over loopback plain HTTP, fetched here.
>
> Qt's FFmpeg cannot resume a dropped stream ("Demuxing failed"). On Windows (7.1, SChannel TLS)
> it lost YouTube links about every 30s, and googlevideo itself resets slow long reads too (Linux,
> 2026-10-23). Python fetches the link, and a body cut short is picked up again with a Range from
> the byte it stopped at. Notes: docs/notes/mild-lyrics/home_page.md.
