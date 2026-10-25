# `mild-lyrics/home_data.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/home_data.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Spotify's library, feed, charts and pages for the home page, through Spicetify.
>
> Reads go through one worker thread of their own (keyed, deduplicated and
> kept for a while); writes -- like, queue, playlist edits -- through another,
> in order. Nothing here waits on the lyric fetcher's loop.
> Notes: docs/notes/mild-lyrics/home_page.md.
