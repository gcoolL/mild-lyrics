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

## Hand picks stay with their item — 2026-10-26

A pasted music video (Superhero, 41s of intro, 188.6s against the release's 182s) went on
playing whenever the song was replayed by name. The play log kept the video's length, a
replay built from that row (`home_pages._row_of`) carried 188600ms, which made the same
streams key and passed the length check against the kept pick.

Now: a pick that was the item's own `yt` is kept with `hand`, and an item without a `yt`
searches past it. Items known by name only (no Spotify id, ISRC, yt or uri) are measured
against Apple's length for the song (`card_ms`), not their own, so older picks without the
mark are caught too. The tid of such a song is a name hash, shared by every cut, so a hand
offset typed for the wrong cut has to be cleared once the right one plays.

## A music video's "With <guest>" — 2026-10-27

Autoplay's radio gives an official video as the song it is of, with no id or length. "Tacones
Rojos With John Legend (Official Video)" became "Tacones Rojos With John Legend", which no
Art Track is called (YouTube Music has "Tacones Rojos" by "Sebastián Yatra & John Legend"),
so `release_of` found nothing. With no length to check, `local_align.find` then took the
biggest upload of the name: the solo Spanish original's video, played under the remix's
bilingual lyrics.

`release_of` now reads "<song> with <name>" as the release `<song>` crediting `<name>`, only
when that row credits them ("Stay With Me" is untouched), and ranks copies crediting someone
not asked for after the others, so plain "Tacones Rojos" keeps the solo one. The window's
video length for such a row comes from its resolved upload, not the last song's.
