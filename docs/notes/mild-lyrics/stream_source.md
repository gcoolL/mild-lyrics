# `mild-lyrics/stream_source.py`

## 2026-11-02 — the playing song's Spotify id, and songs Deezer's search misses

Loca's Spotify id reached the player 36s after its stream resolved, so its first lyric walk ran without Spicy. Asked on its own, the chain finds the id in 4.7s (MusicBrainz). It was waiting in `_sp` (4 workers) behind eight prefetch lookups still running from the batch resolved a minute earlier. `look_spotify(now=True)` now uses `_sp_now`, one worker, and takes a queued prefetch lookup for the same song out of `_sp`. The urgent resolve, the kept-link start and a just-identified file pass it.

"Lost - AL3JANDRO" led with Loca. Deezer's index lacks Lost (on Bury Me with My Gold): even `artist:"AL3JANDRO" track:"Lost"` comes back empty, and the artist's top list stops at 5. `_catalogue_song` reads it off the artist's releases, at most `CATALOGUE_RELEASES` (30). It runs only when the query is a hit's artist plus words that none of that artist's hits are titled. An exact title is preferred over a tagged version, and then the most played. Words that name one of that artist's albums among the hits skip it too (2026-11-08): a pasted album's lookup ("Radiohead OK Computer") had made 31 Deezer requests through it.

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

## 2026-11-02 — guest versions of one song kept apart

Imagine Dragons' Take Me to the Beach has a solo cut (LOOM) and singles with Ado, Baker Boy,
Jungeli and Ernia, all titled alike. The solo played Ernia's single. Four causes:

- Deezer's search rows carry no contributors, so the versions showed as identical rows.
  `_guests_of_twins` re-reads each same-title, same-lead hit (`TWIN_READS` at most) for its
  credits, only when a search has such twins. The Songs tab now fills its Album column.
- `Resolver.key` ran the title through `norm()`, which drops "(feat. X)", so the Ernia cut
  saved its pick under the solo's key. Guests named in the title now go into the key;
  titles without one keep the key they had.
- That entry's Apple card ("(feat. Ernia)") predates the guest rules and `_named` only
  refused the other way round. A kept card crediting a guest the asked song lacks
  (`_stray_guest`) is asked of Apple once more; if the fresh card's guests differ, the
  entry (upload, Spotify id) is resolved again, else the card is kept and marked `gv`.
  295 of 3648 entries are asked again; most keep their pick (Payphone, All The Stars).
- `release_of` judged guests by the artist field only. YouTube Music puts them in the
  title ("(feat. Ado)"), so every single looked alike and the album name picked Ernia's.
  Title credits now count on both sides, a missing asked guest ranks just below an extra
  one, and when no row credits the asked guests a second search names them (the Jungeli
  single was not on the first page).
- `PICK_V` was raised to 6 and put back to 5 the same evening: re-picking every saved upload
  sent a burst of YouTube asks as the queue prefetched, and at 20:51-21:05 every freshly
  issued link (any video, IPv4 and IPv6) answered 403 while older links still played.
  Whether the burst caused it is not known; the `known()` check below covers the bad entry.
- `_apple_meta` asks by `src_title`/`src_artist`. A queue item carries the last card merged
  into its title, so the LOOM solo's item read "(feat. Ernia)", Apple was asked for Ernia,
  answered Ernia, and the re-ask found nothing amiss and marked it. The mark is `gv` 2;
  marks given before this are checked again. The solo entry's Spotify id was Ado's single.
- `known()` refuses a kept link whose entry fails `_stray_guest`. The check sat in
  `_resolve` only, and the kept link plays without it: the solo had been re-saved at v6
  with Ernia's link, so no resolve row was ever logged for it.

## 2026-11-03 — new links refused for their first ~1.6s; faster lookups

- A link straight out of `_audio` (c=TVHTML5, yt-dlp 2026.10.26) answers 403 until 1.4-2.1s after
  it is made (two probes at 0.25s steps), then 206. The relay passed the 403 to Qt ("Could not
  open file"), `_error` asked for a new link, which was refused alike: three retries, then
  `failed`. Every song not resolved ahead hit it (4 `local-error` rows per cold start on 11-02).
  This is also the 20:51 "every freshly issued link answered 403" above: not the burst.
- `expire=` is the moment the link was made plus 6h (matched against resolve rows), so
  `stream_relay.age()` reads a link's age from it. `open_new` waits out a 403 on a link under
  10s old for up to 6s (`relay-wait` row; one link was refused until 4.3s after it was made); the video Store's `_get` uses it too (its first
  fetch of each new video 403'd and slept 10s). Qt waits for a slow first answer (4s checked).
- Lookup time, one verbose run: webpage 0.75s, two player API calls 0.3s, player script
  0.5-1.1s, deno challenge 0.85s, HLS m3u8 1.1s. Audio lookups now skip hls/dash manifests
  (the m4a https file is still picked) and keep one YoutubeDL per worker thread, whose
  extractor keeps the player script: 3.2s → 2.0s on a thread's second lookup.
- deno is CPU-bound: with several resolves at once (fast skips widen the look-ahead) beside
  another heavy process, the challenge took up to 9.8s and resolve rows read 10-17s.
- Qt asks with `Range: bytes=0-`; googlevideo paces a request with no Range to ~33KB/s, so
  that does not apply to playback.

### Heard songs kept on disk (`heard_store.py`)

- plays.jsonl 10-18..11-03: 1815 streamed plays, 1153 songs; 36% of plays (45% in the last week)
  were songs heard before. Those now start from a file with no lookup.
- A song playing from a link past 20s is saved whole (`save_stream`, `bytes=0-`, ~0.3s for 3MB)
  into `home/heard/` by its YouTube id; `index.json` keeps length, size, last played. Over the
  cap (Home ▸ Keep heard songs, off/1/2/5/10 GB, 2 GB default) the least recently played go.
- `Resolver.pick_of` gives the upload `_resolve` would keep with no search: none for picks
  under PICK_V, hand picks, a stray guest's cut. A file whose length is off both the queue's and
  Apple's (DURATION_SLACK) is not played, so a song whose length moved is picked again.
- The queue's look-ahead skips the lookup for kept songs (Spotify id only). A kept file that
  will not open is dropped and a link fetched, as for a stale link.
- End to end (silent QMediaPlayer, scratch cache): first play 5.8s from Play, replay 0.35s.

### Seeks before the song has loaded

- A seek while the song was looked up (or its link not yet served) went to an empty player and
  was lost: sought to 60s during the lookup, it started at 0.6s. `_do` now holds it as
  `_resume_at`, which `_status` spends on LoadedMedia (as after a stream error): started at 60.0.
- Seeks once loaded were never slow: 776 in follow.log landed in median 0.12s, max 0.57s, and
  the same from a link and a file (Qt ~0.05s to land).

## Explicit Spotify pressing for streamed songs (2026-11-03)

The audio pick already ranks YouTube Music's explicit badge first unless Deezer marks the track clean, but the Spotify id found for the same song was whichever pressing a lookup step named first. FE!N resolved to the UTOPIA clean edit (`3KEMjT3QVfKIl4E9DIcrmF`, contentRating NONE, Spicy text with 19 masked words) while the explicit cut played; the explicit pressing is `42VsgItocQwOQC3XWZ8JNA`. The masked-document swap in `LS.from_spicy` never ran, because the window asks Spicy with the id directly.

`look_spotify` now takes `LS.explicit_twin(sid)` when the item is not `clean` and its title has no `CLEAN_MARK`. `SP_V` 3 → 4 re-checks every kept id once. `keep_for_lyrics` moves the name-key entries that held the clean id along with it. Tests: test_spotify_id "the explicit pressing" checks; `LS.explicit_twin` is stubbed there so the suite stays off the network and the real twin cache.

The first fix did not reach FE!N. The song was in the Spotify library as the clean pressing, and a queue item carrying its own id was never looked up (`spotify_of` returns it). `look_spotify` now hands such items to `explicit_of`. It checks the own id once with `LS.explicit_twin` (skipped where `wants_clean`) and keeps the answer per id in `saved["x"]` ("" = no twin). `spotify_of` reads `x` first. `found_spotify` reloads a playing song's lyrics; local_player lets the new id through, because a library id is not a name key in `spotify_id_known`. Dry run on a copy of the real streams.json with the real queue item: before, 3KEMj…; after, 42Vsg….

## Spotify ids from Spicy Lyrics' track search (2026-11-05)

The id chain (Spotify's page and Web API, ListenBrainz, MusicBrainz by name and by ISRC, the artist page, Genius, then the compilation pass) is gone. `spotify_id` is now one `GET /v1/tracks/search` through `LS.spicy_track_id`. The chain took 3.5s median and 5.2s p90 over 322 resolves in follow.log. The search takes 0.25s median and 0.32s p90 over 51 songs.

- Only a first result of tier `exact` is taken. Among the other `exact` results, one at the same cut (within `SPICY_SAME_CUT`, 2s) is preferred when it is explicit, or when it is clean and the song `wants_clean`. Variants carry no explicit flag.
- `spotify_id_of` sends only the catalogue's own `src_album`. Apple's album can be a compilation's, and `album` picks which release comes back: Empire Ants with "Cupid's Playlist" came back as the compilation's copy, which has no community sync. With no album it came back as Plastic Beach, which has one.
- A song coming up asks with `look_ahead`. That is refused while fewer than `SPICY_RESERVE` (10) requests are left in the window, so lyrics keep their share; the key allows 30 per ~30s per IP. A refusal is `trouble` and is asked again after `SP_RETRY`. A failed search is remembered for `SPICY_FAIL_WAIT` and never retried at once.
- `SP_V` 6: a kept id from the old chain is searched once unless its held Spicy doc is a community sync, and the find replaces it (`sp_was`). beamer boy had been kept as `4nja3Ec7…`, a duplicate CALIFORNIA GIRLS EP copy that the search does not list and that has only Apple's line sync. The search's `exact` pick, `1Rt5f1Ck…` (the single), and the EP copy listed under it both have the community syllable sync. Kept ids with a community sync are never searched again, and misses are searched again as they come up. An id kept before v4 that the search leaves in place still gets its `explicit_twin` check.
- The pasted-link swap (`pasted_links.on_spotify`) and the window's id for other players (`Fetcher._spotify_id`) use the same search. The latter no longer needs the Spotify lookup setting, since no account is used.
- ISRC ids are not sent to `/v1/lyrics`: that lost the community sync on 3 of 11 songs.

Measured on 51 real songs (39 with held Spicy docs, 12 without an id). 25 of 39 got the same id. 14 got another release, and its lyrics had the same source and type in 12 of those 14. One was better (Never Go Down: line → syllable), and one lost its sync (DARE, below). Of the 12 without an id, 10 were found and 8 of those have lyrics (5 community). The two not found were a Japanese-titled song and Adele's Hello at the music video's length (`version`).

DARE: Demon Days comes in two pressings, 244.999s (the community sync) and 244.306s (Apple's length, which is what is sent). The search rightly puts the 244.306 one first and lists the other under it. `spicy_swap` now finds twins the same way: `LS.spicy_twins` reads how the search groups releases, nearest length first within `TWIN_SLACK` (1s), from a search made this run or one asked by name as a look-ahead. It tries at most `TWIN_TRIES` (2) of them and keeps the result a week under `s:` keys in spicy-twins.json. `most_played_twin`, which scraped the artist page, is gone. Live: DARE now gets the community syllable sync from `4Hff…` in 0.77s (3 requests: search, own lyrics, twin lyrics). One caveat: that sync's first line is at 1.04s, while Apple's sync for the 244.306 pressing starts at 0.28s, and the two lengths differ by 0.69s. If the extra length is lead-in, the carried sync runs about 0.7s late on that cut. The heard-offset measurement corrects that for the program's own player (see heard_lyric_offset); a Spotify-played 2WEe keeps it uncorrected.

Tests: test_spotify_id (rewritten for the search), test_spicy_search (replaces test_isrc_match), test_pasted_links' swap section.
