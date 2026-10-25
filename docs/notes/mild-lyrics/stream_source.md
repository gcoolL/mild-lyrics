# `mild-lyrics/stream_source.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/stream_source.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### `spotify_id`

**line 946** — from the docstring, `def spotify_id(title: str, artist: str, album: str = "", ms: float = 0, page=None,`

> A Spotify track id for a song known by name, asked of each source in turn; whatever
> one names is checked against Spotify's public page (version, length) before it is taken.
>
> The song's own ISRC first where it has one (spotify_by_isrc). Then Spotify's own
> search while it is open (`page`); its Web API on the kept token (ISRC first); ListenBrainz; MusicBrainz by name, then by Apple's ISRC; the artist's public
> Spotify page; Genius.
>
> `trouble` is told every step that could not be asked (refused, timed out): an
> empty answer with trouble is "not known yet", not "not on Spotify".
