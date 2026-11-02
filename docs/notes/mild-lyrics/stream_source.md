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

## 2026-10-30 — artist page top tracks on another album

`artist_page_spotify` took the first top track with the song's name and
length. For SAWTOWNE's M@GICAL CURE! LOVE SHOT! that was the copy on the 2026
album CHECKPOiNT!, not the 2024 single the song's catalogue names (and the one
Spicy Lyrics holds a community sync for). With an album given, a top track
whose `albumOfTrack` is named differently is now kept as the fallback; the
releases named like the song's album or title are scanned first, and the scan
stops at the first release not so named.

## 2026-10-31 — skip storms queued the landed song behind the skipped ones

follow.log 23:02:13–15: 13 skips in ~2s, the song landed on took ~45s to load
while its video was shown in 4s. Every skip that found no kept link called
`Resolver.want(now=True)`, and the "now" lane is a two-worker FIFO pool: the
landed song sat behind every song skipped past, each a YouTube Music search
plus a yt-dlp extraction. The video side has its own pick cache and threads,
so it was never in that line.

Now `want(now=True)` marks the song as `_current` and cancels urgent jobs that
have not started (`_drop_passed`); a running one checks `_passed` after Apple,
after the search and before each further upload, and stops (`_Passed`, no
`ready`). A link already found when the check comes is kept. The Spotify grace
is no longer waited for on a failed or skipped-past resolve.

Each resolve now writes a `resolve` row: `took`, `now`, `ok`, and seconds from
its start as each step ended (`apple`, `search`, `tryN`, `audio`, `spotify`),
`passed` when it stopped. Slow single loads (no skipping) can be read off these
rows next time; this change only removes the queueing.

## 2026-10-31 — heard lengths drifted High Hopes onto a slowed copy

plays.jsonl had High Hopes (Spotify 190.9s) at len 190.9, 190.0, 210.7, then
243.0, and the last pick was a 243s SoundCloud reupload, slowed. Play-log rows
(`_row_of`) and the playing song as an item (`np_item`) take their length from
the upload that played, but carry the Spotify uri, so `_resolve` took that
length as the catalogue's: the YouTube Music release (190s) was refused on
length and `local_align.find` returned the upload that fitted. Each play then
logged the new length, and the next search drifted from there.

Those items now carry `heard: True` (kept by `stream_of`), and `_resolve`
treats them like a song known by name: Apple's card length is searched. A kept
pick for the drifted key is retried, refused on length and searched again.
Queue items saved before this have no flag and keep their length.
Queues saved before the flag are marked on restore (`LocalPlayer._heard_before_mark`):
YouTube art, `card_ms` present and more than DURATION_SLACK off `ms`. On the saved queue
that day it marked High Hopes and Hymn for the Weekend (245.8s against Apple's 258.8s,
which had played a BBC Radio 1 live upload, 243s, found by the fallback search) and
nothing else.

## 2026-11-01 — Apple's length beside the asked one

ZEZE failed on every resolve after a restart (12 in a row, ~7.5s each): its queue item had
Spotify art, no `card_ms` and a heard 219.9s (the release is 228s), so neither `heard` nor
the restore mark caught it, and YouTube Music's release was refused on length. Heard
lengths reach the queue by more ways than can be marked, so `_resolve` now asks with
Apple's card length too whenever it is more than DURATION_SLACK off the asked one
(`alt_len`): `release_of(..., also=)` keeps a release at either length, ranking one at the
asked length first; an upload at either length is accepted; and a saved pick is not reused
while the two disagree, so a pick made at a heard length (the BBC live Hymn for the
Weekend) is searched past. Live check: ZEZE at 219.9 finds no release, with Apple's 228.8
beside it finds ghiSpmZu6tk, the one played before.

## 2026-11-01 — live uploads refused by title; every pick made again once

Just Pretend played "Bad Omens | Just Pretend | Live From Germany" (4pmM5zNIiUQ). The pick
was made at 00:38:54 by a build without `alt_len`; the app restarted at 00:39:37 and played
the kept link from stream-urls.json, which no rule looks at again. Two changes:

- `PICK_V` 5: every saved pick (and its kept link) is made again once under the current rules.
- The fallback search refuses uploads that are not the recording by title (`NOT_RECORDING`,
  `not_recording(title)`, passed to `local_align.find(refuse=)` and used on the two
  yt-dlp searches): live/festival/session/BBC/acoustic/remix/slowed and the like. Unlike
  the music video's NOT_IT, "audio" and "lyrics" uploads stay, and a word the song's own
  title has is allowed (Live Forever). `ALT_VERSION` there only ranked these last, and
  "Radio 1's Big Weekend" matched nothing.
