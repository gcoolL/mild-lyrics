# `mild-lyrics/autoplay.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/autoplay.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> What Mild Lyrics' own player plays after its queue: songs like the one playing.
>
> `fuse` merges the sources' lists (YouTube Music's song radio, Spotify's when it
> answers, Deezer's artist radio) by rank; `pick` makes a varied run of them: no
> other version of a title already heard or queued, a cap per artist, never the
> same artist twice in a row. Notes: docs/notes/mild-lyrics/home_page.md.

### `pick`

**line 70** — from the docstring, `def pick(cands: list[dict], n: int, seed_artist: str, heard_titles: set[str], heard_songs: set[str],`

> Up to `n` songs out of `cands` (best source first), varied and new.
>
> heard_titles: normalised titles playing, queued or played lately -- another
> version of one of those is never picked. heard_songs / banned / liked are
> "title|artist" keys; "*|artist" in banned leaves out the artist. favourite_artists maps a normalised artist to a weight
> (from the play log). Fused candidates (`_fused`) are ranked by it, the nudges kept below one
> source's agreement; skipped_artists counts this session's autoplay skips per artist.
