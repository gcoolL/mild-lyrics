# The home page (1.2.0)

`home_page.py` (state, chrome, input), `home_pages.py` (the pages),
`home_data.py` (Spotify through Spicetify), `play_log.py` (listening
history), `local_player.py` (files played here), `home_icons.py` (Lucide).
Built from the "Mild Lyrics Home Redesign" design, v4.

## 2026-10-29 — Show on screen hides the sidebar's listen line too

Listen along ▸ Show on screen (`listen_badge`) only gated the lyrics view's
badge. Home's sidebar line ("N listening along", "Sharing · nobody yet")
showed whenever a share or listen was on, so on Home the switch seemed to do
nothing. It follows the switch now. The session menu is still under
Settings ▸ Listen along.

## 2026-10-29 — "Like this song" followed Spotify's player

Bug: with Spotify open but another player playing (Mild Lyrics' own,
say), "Like this song" listed "Same artist" songs by whoever Spotify's own
player last had: NF, under "NyxTheShield feat. GatoPaint". `JS_SUGGEST` with
no uri reads Spotify's current item, and `v.suggest` was used whenever
Spotify was online. Now `suggest_fits` keeps it only when one of its top
tracks credits one of the playing song's artists; otherwise the credited
artists' own pages are used, as without Spotify. A suggestion that lands
after the shelf was built clears the shelf's 30s hold (`on_suggest`).

## 2026-10-27 — release countdown on upcoming albums

An album Spotify holds as a pre-release shows "Releases on <day>" and a
Days/Hours/Minutes/Seconds box in place of Play/Shuffle/Add to queue; the
artist page's tile says "Out <day>". The moment is `preReleaseEndDateTime`
on getAlbum's albumUnion (what Spotify's own album page counts down to),
and `isPreRelease` + the same field on the artist overview's releases;
both read from the xpui bundle, not seen live. Deezer and Apple did not
list the album checked (Cove Grove, The Shadow, due 2026-10-31) at all;
Genius had its date and nothing else. With Spotify away, a Spotify album
Deezer has no match for is read from its public embed page
(`stream_source.sp_album`): `isPreRelease`, `releaseDate.isoString`
(2026-10-31T21:00:00Z for that one) and the track list, where
unannounced tracks are unplayable "Track 3" rows with no length; those
rows are `locked`, drawn dim and take no click. `Home.tick` asks one
frame per new second while the box is up. Past the moment the album is
asked for again once (`Pages.released`), for its now playable tracks.

Upcoming releases on the artist page (same day, later): the first Albums
tiles, read by `stream_source.upcoming` through `Deezer.upcoming` whatever
player leads, kept six hours. Measured on 12 albums due 2026-10-30 to
2027-03-05 (from MusicBrainz's future-dated release groups) plus Cove Grove:
Spotify's public artist page had all 13 in `preReleaseV2` (name, uri, cover,
`preReleaseEndDateTime`; 10 of 12 were absent from its discography, so the
discography is not where to look); Apple had 11 (`isPrerelease`, a day; one
request on `/artists/{id}/albums?sort=-releaseDate`); Deezer had 5, as plain
albums with a future `release_date`. So: Spotify's page (artist id from the
Spotify uri, else MusicBrainz), Apple when there is no Spotify page, and
Deezer albums dated ahead get `release` at local midnight. Apple's have no
uri: the album page finds them on Deezer by name, else counts down with
"Its songs show here once it is out". Tiles carry `by`, since their `sub`
says when and the album page used to read the artist from `sub`.

Home's Coming soon shelf (setting `home_shelf_soon`, on): `Pages.soon_rows`
takes followed artists (Mild Lyrics' library, then Spotify's), then the
most played of 90 days, at most 30, and lists their releases still ahead,
soonest first, captioned "Artist · Out 31 Oct" (`out_on`: the year only
when it is not this one). Hidden when none. Each artist goes through
`upcoming_kept`, which asks at most once a day per artist and keeps the
answers in the cache's home/upcoming.json across starts; the shelf
re-asks the in-memory source at most once a minute, not per frame. The
first start with an unknown artist takes 2-6s (Spotify artist id from
MusicBrainz; 0.15s once known), so these asks run on a source of their
own, `Home.ups`, not on `Home.dz`: on dz, with its general reader busy on
a slow background read, a page-first lookup held the page reader and an
album clicked meanwhile waited 2.8s (0.01s on its own source). The
artist page still asks `first=True`, which only reorders `ups`.

## 2026-10-18 — how it is put together

**One view, handed over.** The window keeps `view == "browse"`; with the New
interface `_paint_window` and every input handler pass to `LyricsView.homep()`.
The Classic interface still gets the old `_paint_browse` shelves, untouched.
Mouse presses reach the home page before the window's own right-click menu,
or right-clicking a song would open the lyric menu instead.

**Hit rects, immediate mode.** Every paint rebuilds `Home.hits` as
`(kind, payload, rect)`; the topmost (last painted) wins. A background hit
(`note_bg`, `ctx_bg`, `pop_bg`) must be registered *before* the buttons on
it, or it swallows their clicks — the toast's Undo did exactly that. Drop
targets (Queue, playlists in the sidebar) live in `Home.drops`, not in
`hits`, so they never shadow the nav row they sit on.

**Spotify, on its own threads.** `home_data.Spot` has one reader thread
(keyed, deduplicated, answers kept `KEEP` seconds) and one writer thread (in
order). Nothing waits on the lyric fetcher's loop. Scripts and what they read:

| key | source |
| --- | --- |
| `feed` | GraphQL `home` (`INTEGRATION_WEB_PLAYER`) — "Made For …" and "Your top mixes" feed Top picks |
| `liked` | `LibraryAPI.getTracks`, 200 a page, up to 2000 |
| `albums` / `artists` / `playlists` | `LibraryAPI.getContents`, filters "0", "1", "2" |
| `pl:<uri>` | `PlaylistAPI.getMetadata` + `getContents` (charts are playlists too) |
| `album:<uri>` / `artist:<uri>` | GraphQL `getAlbum` / `queryArtistOverview` |
| `search:<q>` | GraphQL `searchDesktop` |

Writes: `LibraryAPI.add/remove({uris})` (like, follow), `PlayerAPI.addToQueue`,
"play next" = `insertIntoQueue(items, {before: first queued or next-up item})`,
`clearQueue`, `PlaylistAPI.add(pl, uris, {after: "end"})`, `remove(pl, rows)`,
`move`, `RootlistAPI.createPlaylist`. The shapes were read off the functions'
own source on 2026-10-18 (`fn.toString()`), not called: **none of the writes
has been run against a real account yet.**

**Country charts.** Spotify's search does not return its own chart
playlists, so "Your country" is a table of the Top 50 ids
(`home_data.COUNTRY_TOP`, 32 countries, each checked by name on 2026-10-18)
keyed by `ProductStateAPI` country; anything else falls back to Global.

**Lyric badges.** The lyric index held 4 songs here, so it cannot say what a
song has. `home_data.Kinds` scans `~/.cache/mild-lyrics/sources/*.json` on a
thread (≈4000 records), runs `LS.quality` on each record's `doc`, and keeps
`tid -> w/l/r/n` in `cache/home/kinds.json` with mtimes, so later scans read
only what changed. Unknown songs get no badge rather than a guess.
2026-10-22: word-by-word is badged too (it was left blank as in the design,
which made the queue's column look never filled). Local-player rows are
looked up under the ids fetch-ahead keeps them by (Spotify id via the
resolver, else the name key: `Home.track_kind`), and every
`Fetcher.ahead_ready` rescans, so the next "Fetch ahead" songs fill in as
they are warmed. Songs further down stay blank until they come within reach.

**Listening history.** `play_log.Tracker` is fed from the window's poll
(`Home.observe`): one row per song, written when it ends, with seconds
actually heard, lines reached, player, lyric kind, and `skip` (left inside
30s of a song over a minute, not near its end). A play counts at 30s or
half the song. `plays.jsonl` sits beside gui.json, never leaves the machine,
and `--no-persist` keeps it read-only. Settings ▸ Home ▸ Forget listening
history deletes it.

**Suggestions** (`Pages.build_recs`), three modes:
- *Your listening*: top artists over `home_look` days from the log, their
  top tracks from the artist page, with the log's own numbers as the reason;
  then one track from two related artists of each of the top three. With no
  log yet it falls back to the window's `discover` (Spotify's play history).
- *This song*: the playing artist's top tracks, then related artists'.
- *Something new*: related artists of the top artists that the log has never
  heard.
Skipped-twice songs, hidden songs (`home_hidden`) and, when asked, songs
never played are left out; "prefer word-by-word" sorts known line-only songs
last. Rebuilt from `build_home`, which every data arrival already calls.

**The local player.** `LocalOverlay` wraps whatever `make_player` builds, so
the clock follows the local player while it is `active` and the usual
transport otherwise. It reads `LocalPlayer.reading()` from the pump thread
(a snapshot taken on the GUI thread, extrapolated), and commands cross back
to the GUI thread by a queued signal — QMediaPlayer is not thread-safe.
Paused here for 2s while the inner player says Playing: it hands back.
Local songs are keyed `song_key(title, artist)`, the same id any non-Spotify
player's song gets, so their lyrics are fetched by name like a browser's.
`has_port` and the state's `player` look through the overlay (`.inner`).
Not tested with real audio here: it would play out of the speakers.

**Keys.** `browse` moved to B; depth blur moved to Shift+B; `Home` stays an
alias. "Keep Home" (on the one-time note, or onboarding) binds browse=Home
and blur=B in the user's keymap. Q stays quit, so the design's Q-for-Queue
was not taken.

**Not built from the design.** Per-song source switching on the Song page
(the window has no such override; the card says what is in use and what was
asked); "Mix from this artist" (Follow instead); the This song tab's
"never suggest" / "count its plays" switches (the right-click menu has
"Never suggest this song"); coverage-percent badges on album and artist
tiles (only known after an album page is opened).

**Testing.** Offscreen screenshots and a 40-check interaction run, both
with every network host blocked but localhost and Spotify's image CDN, and
every play/queue/like/playlist call stubbed and recorded. Scripts were in the
session scratchpad: a real `LyricsView`, `--no-persist`, synthetic
QMouseEvent/QKeyEvent through the window's own handlers, and
`processEvents()` between steps (without it no Spotify answer lands).

## 2026-10-18 — streaming, without Spotify

**Songs that are not on this computer play in Mild Lyrics' own player.**
`stream_source.py`. Settings ▸ Home ▸ Play songs in: auto (Spotify while its
page answers, Mild Lyrics otherwise), Spotify, or Mild Lyrics. The right-click
menu always offers the other one.

- **Catalogue without Spotify:** Deezer's public API (`stream_source.Deezer`,
  same keys and shapes as `home_data.Spot`): search, artist, album, chart,
  "Popular playlists" for Top picks. No account, no key. Measured 110-260ms
  a page here. A `deezer:` uri always goes to Deezer, a `spotify:` one to
  Spotify, whichever is the default catalogue (`Home.src`).
- **Audio:** `Resolver` asks YouTube Music's Songs results (the label's own
  uploads) first, then YouTube, and takes the first copy whose length is
  within 3s of the catalogue's — so a live or extended cut is not played.
  The video id is kept in `cache/home/streams.json`; stream URLs expire
  (`expire=` in them, ~6h) and are re-resolved, never stored.
  The next song in the queue is resolved while this one plays.
- **Spicy Lyrics:** it is asked by Spotify id, so a stream needs one. A
  Spotify catalogue song already has it. Otherwise: ListenBrainz labs
  `spotify-id-from-metadata` names candidates, and Spotify's public
  `open.spotify.com/embed/track/<id>` page (its `__NEXT_DATA__`) confirms
  name, artist and length for the first few. Kept with the video id. No id
  found: the song is keyed `song_key(title, artist)` like any non-Spotify
  player's and the name-searching providers answer.
  End to end, measured offscreen with no audio output: Skillet – Monster
  picked from Deezer, playing after 4.7s, tid 5XQNN3…, Spicy community
  syllable sync, clock following the stream at 1x.
- **The overlay** hands back to Spotify only after the local player has
  *played and then sat paused* for 2s; it used to count from startup and
  handed back while a stream was still resolving.

**Search** asks `searchModalResults` first (~0.33s, mixed top results) and
`searchDesktop` (~0.75-1s, full tabs) after it, on a `Spot` of its own so a
page load never queues in front of it; a newer query drops any not yet sent.
Songs already here (liked, logged, local) show while it is out.

**Mini player** is its own frameless window now (`home_page.MiniWindow`):
drag anywhere to move, the corner to size; the big window is minimised in
place and restored there. Its line is laid out and filled syllable by
syllable from `render_pieces` (line-synced lyrics get the same interpolated
word sweep as the main view), reading the clock directly because the
minimised window stops painting. Ad-libs (background lines between this lead
and the next) show under it, smaller; Settings ▸ Home ▸ Ad-libs in the mini
player.

**Open lyrics** on a song that is not playing opens a read-through page
(`page_words`) fetched through the same `LS.fallback` walk the fetch-ahead
uses, instead of playing it.

**Not done:** liking, playlists and the library pages still need Spotify;
without it they are empty, and the heart does nothing on Deezer songs.

## 2026-10-18 — the library in Mild Lyrics, YouTube, autoplay

**Library** (`library.py`, `library.json` beside gui.json; read-only under
`--no-persist`). Liked songs, playlists, followed artists, saved albums, for
any song: Spotify, Deezer, YouTube or a file. A song is the same song across
catalogues by `song_key` (normalised name + first artist), so liking it on
Deezer shows it liked in Spotify's list too.
- A like always goes to Mild Lyrics; to Spotify as well when it is a Spotify
  song and Spotify is there. Unliking a song only Spotify has, while Spotify
  is away, says so rather than pretending.
- New playlist always makes a Mild Lyrics playlist (`mild:playlist:<id>`):
  add from the song menu or by dragging onto it in the sidebar; Edit shows ×,
  drag-to-reorder (drops on the table's `row_rects`), Rename, Delete — each
  with Undo. Spotify's own playlists still take Spotify songs while it is there.
- **Spotify's library is mirrored** (`mirror` in library.json): liked,
  playlists, albums, artists, and the contents of your playlists as last
  opened. Loaded into `Spot.data` at an age that forces a refresh, so the
  sidebar and pages are full while Spotify is closed and playing goes to
  Mild Lyrics. A Spotify album or artist never opened shows "opens when
  Spotify is connected".
- Mixed lists play mixed: a file stays a file (`stream_of`), the rest stream.

**Audio search** is `local_align.find` now — the editor's tuned YouTube and
SoundCloud search (by plays, Topic releases, the artist's own uploads, against
live and remix cuts), ~3.7s; YouTube Music's Songs results are the fallback.
**YouTube tab** in search: anything uploaded (covers, remixes), played by its
own video id. The row shows the video's title and channel as uploaded; the
song and artist cleaned out of them (`song_of_video`: the window's
`song_from_video`, then cover/remix brackets and "by …" tails) are what the
lyrics and the Spotify id are looked up by.

**Autoplay** (Settings ▸ Home ▸ Autoplay, on): when Mild Lyrics' own queue
starts its last song, the last three artists' Deezer radios
(`/artist/<id>/radio`, no account) are interleaved into ten more songs,
leaving out what was played in the last 60 plays, what is queued, hidden and
twice-skipped songs. Marked `_auto`; songs added by hand go before them; the
Queue page shows them as "Autoplay · songs like these". If the queue ends
before they arrive, the first plays when they do. Spotify's own autoplay is
Spotify's business and untouched.

## 2026-10-18 — autoplay, second version

Bug: "Feels" playing, and the next three songs all called "Feels". That
was not autoplay: a song clicked in search started a queue of *every* search
result. Search results and Recently played now start one song (`context=[]`
on their tables), and autoplay follows it, as Spotify does.

Autoplay itself (`autoplay.py`):
- **Candidates.** With Spotify there: Spotify's own song radio for the song
  playing and the one before -- `inspiredby-mix/v2/seed_to_playlist/<track>`
  through `Spicetify.CosmosAsync`, a ~50-song mix (`Spot.radio`). A streamed
  song has its Spotify id from the resolver, so it seeds this too. Without
  Spotify: Deezer's artist radio for the last three artists, round-robin with
  the top four songs of up to six related artists each.
- **Ranking** (`pick`): no other version of a title playing, queued or among
  the last 80 plays (titles normalised: brackets, " - Remastered",
  "feat." dropped); no song from the last 300 plays; hidden and twice-skipped
  songs out; liked songs and artists you play most (over the Look back
  window) nudged up; line-only lyrics nudged down when word-by-word is
  preferred; a little randomness. Then at most 2 songs per artist per top-up,
  the seed's own artist at most once in 5, never the same artist twice in a
  row (the cap is never eased; a short top-up is filled by the next one).
- **Length.** About 25 autoplay songs are kept queued (`AHEAD`), topped up
  whenever fewer than 10 are left (`near_end` fires on every song now).
- Live check, "Feels" (Calvin Harris…) as seed, read-only: Spotify radio gave
  Feel Good Inc., Don't Start Now, Light It Up, Watermelon Sugar…; the Deezer
  path gave We Got That Cool, By Your Side, Moonlight, Don't You Worry Child…;
  25 each, no "Feels".

## 2026-10-18 — the right recording, and no wait on skips

Bug: In the End played a cut the community sync was off against, and a
clicked line started "slightly before" itself. Measured: QMediaPlayer lands
exactly on the seek target on these streams, so both were the recording --
`local_align.find` ranks by plays, and the most played upload of a big song
is its music video, with its own intro. Now `stream_source.release_of`
asks YouTube Music's own search first (`youtubei/v1/search`, WEB_REMIX,
"Songs" filter, ~0.5s): Art Tracks only (MUSIC_VIDEO_TYPE_ATV -- the label's
upload of the streaming release), same name, artist in the byline, length
within 2s of the catalogue's, live/remix/sped-up cuts refused unless asked
for, the catalogue's album breaking ties. In the End → BLZWkjBXfN8, Hybrid
Theory, 217s for Spotify's 216s. `find` stays as the fallback. Video picks
saved before this (no `"v": 2`) are picked again.

Bug: skipping a few times in a row, each song was plainly a fresh
fetch. Now the next three songs are resolved while one plays (4 threads),
and stream URLs are kept in cache/home/stream-urls.json until 10 min before
their `expire=`; a stream that errors (URL stale, IP changed) is fetched
again once. Measured silent, five Linkin Park songs: first 3.0s from cold,
then three skips 1-2s apart each playing within 0.1-0.2s.

Mini player fill: each word is drawn once with a gradient pen (soft edge
about one "n" wide) instead of dim-then-lit-clipped, which left a grey
fringe round lit glyphs; lit is white unless Text ▸ Sung colour is album tint.

## 2026-10-19 — pinning, your own Top picks, Apple's names

**Pinning did nothing until now**: the popover set a `pinned` field no
transport read. Now `LocalOverlay.pin(who)` ("mild", "spotify", or a session's
name) sets `SessionTransport.pinned` (read only that player, playing or
paused -- no `_look`, no `_home` hand-back) and `BackupTransport.pin_side`
(read only that side, so Spotify playing over the port no longer takes the
window back), and the local player's 2s hand-back is skipped when pinned to
Mild Lyrics. A pinned player that closes is unpinned (`pin_lost`, said once).
Picking something to play in the app releases a pin on another player. Not
kept across restarts (bus names change).

**Top picks without Spotify are yours** (`Pages.my_mixes`): On Repeat (top
songs of the month, from the play log), a mix per most-played artist (your
songs by them, interleaved one-to-two with their Deezer radio ranked by
`autoplay.pick`), Something New (related artists you have not played). Your
artists come from the play log, then liked songs. Deezer's own "popular
playlists" are no longer shown as picks. `mild:mix:<key>` playlists, built
once a session (`_mixes`), shown and played like any playlist.

**Apple Music's names for streamed songs.** Deezer and YouTube often leave
featured artists off ("Muffin" by Badboyhalo; Apple and Spotify have "Muffin
(feat. Skeppy & CaptainPuffy)" by BadBoyHalo, CG5 & Hyper Potions). A stream
without a Spotify id now asks `LS.apple_card` (the lyrics' own Apple lookup,
matched on name, byline and length, cached per song) and takes its title,
credits, album and length before the release search; ~0.3s.
Spotify id for a stream, in order: Spotify's in-app search through the page
while Spotify is open (`Resolver.page`, no Web API quota); the kept token's
Web API by Apple's ISRC (`LS.spotify_web_search`) -- answered 429 all of
2026-10-19 morning, so not to be relied on; ListenBrainz + embed. A miss is
retried after a day (`sp_tried`), not never. Muffin is in neither
ListenBrainz nor MusicBrainz (ISRC QZPEW2000423), so with Spotify closed it
gets the name-searching providers and no Spicy sync.

## 2026-10-19 later — Spotify ids from MusicBrainz and Genius; stream drops

Spotify id for a streamed song, whole chain (`stream_source.spotify_id`):
Spotify's in-app search (open) → kept token's Web API by Apple's ISRC →
ListenBrainz + embed → **MusicBrainz** → **Genius**.
- MusicBrainz (`mb_spotify`): recording search by the plain title (brackets
  dropped: "Muffin (feat. …)" finds nothing) and first artist, length within
  3s; the recording's own open.spotify.com/track link, else each release's
  open.spotify.com/album link, whose public embed page
  (`/embed/album/<id>`, `__NEXT_DATA__` trackList) names the track. One
  request a second, as MusicBrainz asks (`_mb`, a lock and a 1.05s gap).
  Muffin: release 399eed66… → album 23AQbzkTQHvqn5v5dCRIiW → track
  0w9SSLVuq8ZlCdrfEuqQ6z, 224040ms like Apple's; ~3-4s.
- Genius (`genius_spotify`): its public `api/search/multi`, then
  `api/songs/<id>` media, provider "spotify". Numb → 2nLtzopw…; Muffin has
  only SoundCloud and YouTube there.
The whole lookup is waited for before a stream starts (so the track id does
not change mid-song), so an obscure song's first play can take a few seconds
more; the answer is kept in streams.json and queued songs are looked up ahead.

Bug: playing in Mild Lyrics, the song stopped, went back to 0:00,
then played on as if nothing happened. The stream-error path did that: `_error`
fetched a fresh URL and `_load` started it from 0, and `reading()` said 0
while it did. Now the position is kept (`_resume_at`), reported while the
fresh URL is fetched, and sought to once the media has loaded; up to three
retries a song. An EndOfMedia more than 5s before the song's length is a cut
stream, not the song ending, and goes the same way instead of skipping.

## 2026-10-19 — end of song, stalls, and the lyrics view's pages

A whole song played silently (In the End, no audio output) ran clean -- no
error, no jump -- but at 216.9s QMediaPlayer neither said EndOfMedia nor
stopped: the position sat at the end while `reading()` went on extrapolating
(218, 238…) and the next song never came. Now `_sample` notes when the
position last moved: playing but unmoved for `STALL` (0.6s) and the clock
holds where the audio is instead of running on (a buffering stall would have
run the lyrics ahead); at the end and unmoved for `END_STUCK` (1.5s), the song
is over and the queue steps on. (Without an audio output may be why it never
said so; either way it is handled.)

The Song, Artist and Album pages were only reachable from the home page;
clicks on the song, an artist or the album in the lyrics view still opened the
old `_paint_detail` screen. Under the New interface `open_detail` now opens
the home page's pages (`Home.open_from_lyrics`), with the back link reading
"Lyrics" and Esc going straight back. While Spotify is away, a Spotify artist
or album (or one known only by name) is found by name in the catalogue in use
(`Pages.by_name`).

## 2026-10-19 — surviving a restart

**Apple's names for every Mild Lyrics stream** (decided: streams only,
not songs playing in Spotify). The resolver asks `LS.apple_card` for every
stream now; the Spotify id, the catalogue's length and cover are kept, Apple's
title, credits and album are taken.

**Listen along across a restart** (`listen_along.py`). The Worker already
allowed it -- a room keeps the sharer's key hash while any listener is still
in it -- but the app sent `{"end": true}` on quit and threw the key away.
Now `ListenAlong.suspend` (from closeEvent, not under --no-persist) sends
`{"bye": 60}` instead and writes role, secret, host key and the auto flag to
config/listen-resume.json (0600); `resume` at the next start, if under
RESUME_WITHIN (60s), reconnects as the same sharer (or rejoins as the same
listener) and deletes the file. A listener told "bye" waits that plus
BYE_MARGIN (15s) instead of HOST_WAIT (15 min, still used for network drops)
and the server's "gone" that follows does not reset it. No Worker change.
Tested against `wrangler dev` on 8799 (test_listen_along_resume, 13 checks:
resume, listener follows the resumed sharer's new song without rejoining,
not-back ends after the minute, stale file refused, listener rejoin); the
other listen tests unchanged.

**Mild Lyrics' own queue across a restart** (`LocalPlayer.state/save/
restore`). config/player.json: the queue (up to 500), the place in it, the
position, shuffle/repeat, whether it was the player in use. Saved every 15s
while there is a queue and on close. Restored at startup *cued*: nothing is
loaded or fetched, the reading says Paused at the saved position (so its
lyrics load), and its pause counts as long-standing so a player already
playing keeps the window. Play (or Next/Previous) loads it and carries on
from there. Measured silently: saved at 30s, restored, played from 30.0s.

## 2026-10-19 — showing up as "Mild Lyrics"

`mpris_player.py`: while the local player has a queue, it is on the session
bus as org.mpris.MediaPlayer2.mild_lyrics -- Identity "Mild Lyrics",
DesktopEntry mild-lyrics -- so Plasma's media controls, the lock screen, media
keys and KDE Connect show it and can drive it (play/pause/next/previous,
Seek/SetPosition, Volume, Shuffle, LoopStatus; Raise brings the window back,
out of the mini player). dbus-python as a *service* on a private bus
connection with `DBusGMainLoop` -- Qt's dispatcher here is
QPAEventDispatcherGlib, so its callbacks run in the GUI thread. Diffed
PropertiesChanged on the player's `changed` and once a second; Seeked on a
seek. `MprisTransport._on` leaves the name out: the window must not follow its
own player as somebody else's. Not published under --no-persist, --fixture or
MILD_NO_MPRIS=1, so tests never put a player on the real bus; tested on a
`dbus-run-session` bus, driven from a second process.
The sound: `PULSE_PROP_application.name=Mild Lyrics` (and the icon) before
QApplication, so the mixer names the local player's stream "Mild Lyrics"
instead of python; the overlay's `app` is "mild lyrics" to match it in
audio_sink. `setDesktopFileName("mild-lyrics")` ties the window to its
.desktop file. Windows (SMTC) and macOS (Now Playing) have no equivalent yet.

## 2026-10-19 — clicks, unlikes, mixes, and the local player's sync

**Clicks on list rows were dropped in the real app.** Every table row holds
its list (`_list`, for "play from here"), so a row contained itself; press and
release compared hits *by value*, and in the app the page redraws between the
two (the progress bar), so the comparison walked two copies of a cycle and
raised RecursionError -- the click (queue rows, hearts, playlist rows) did
nothing. The tests pressed and released without a redraw between, which
hid it; `mouse()` in test_home_page now grabs between the two. Hits are
compared with `hit_key` (kind + uri/name/sub/path/_qi/_pi/_n/_i/head), and the
row's list is a `Ctx` (identity equality and hash).

**Unlike with Spotify away** used to be refused for a song only Spotify had
liked. Now it is done here at once and kept in library.json `sp_pending`
(uri -> liked?), told to Spotify by `flush_pending` when Spotify's liked list
next arrives. Also: `load_mirror` was never called, so Spotify's library was
not shown from the kept copy while Spotify was away; it is now, at the end of
Home's setup. `--no-persist` now neither reads nor writes library.json.

**Something New reshuffled on every frame** while its data came in: it was
rebuilt per paint with an unseeded pick. Mixes now pick with a seed per mix
and day, and Something New is not shown half-built -- "Putting it together…"
until its lookups are in or MIX_PATIENCE (8s), then kept.

**Sync with Mild Lyrics' own player depended on where you paused, and the
first click moved it.** Clock._apply measured a "resume lead" on every
unpause and added the unpause-delay setting (+0.25s here) -- the hold built
for Spotify, whose reported position lags its audio on resume -- and a seek
(a clicked line) reset it to zero. The local player's position is the
decoder's (decoded audio measured within 13ms of it after seeks, via
QAudioBufferOutput), so for readings with source "local" the hold is now
always 0. Measured silently: three pause/plays, bias 0 throughout. What is
left is the audio device's own buffer, constant per device -- the per-device
offset, which is still the one tuned against Spotify's path.

## 2026-10-19 — the Song page: its lyrics, sources, singles, a queue from it

- A song's page fetches its lyrics as it opens (`song_lines` → `fetch_words`, the
  same walk as playing). Every line is listed; right-click copies a line or all of
  them, and "Copy lyrics" copies all, with background lines indented. A click on a
  line seeks only while that song is playing.
- Sources: `_walk` now stores `kinds` (each provider's sync, or "none"/"failed") in
  the cache record. `source_rows_for_home(tid)` reads it. Records made before this
  have no `kinds`, so their other sources just say "asked".
- Singles: Apple's "X - Single"/"X - EP" album names are cut to the release name in
  `Resolver._apple`. `is_single` shows " · Single" instead of an album link. Artist
  pages and "More by" drop `type == "single"` (Spotify's release type, Deezer's
  `record_type`). Compilations and EPs stay.
- Artists and the album are always links, even with no uri; the page then finds
  them by name.
- "Make a queue from this song" (`song_radio`) replaces the queue. In Spotify mode
  it plays Spotify's song radio from that song. In Mild Lyrics mode it plays the
  song, then autoplay's picks seeded by it alone, marked `_auto`.
- Sidebar footer: the listen-along and "Playing here" dots now sit on the Settings
  icon's centre, and their text starts at its label.
- A queue made from the song already playing keeps it playing. In Mild Lyrics'
  player, `LocalPlayer.replace_after` swaps only what follows it, whatever "Play
  songs in" says. In Spotify, the radio starts at that track with `seekTo` the
  current position (`request_play_in(..., seek_ms)`); Spotify still switches
  context, so a short gap is possible. Not tried against live Spotify.

## 2026-10-19 — a line click in Mild Lyrics' player no longer resyncs once

Cause: after a seek the stream refills for a moment. Qt sends no
`positionChanged` while it does, so `reading()` kept extrapolating from the seek
for up to STALL (0.6s). The words ran ahead, then slewed back once the audio
started: the visible "redo". A held position also counted as stale in
`Clock._apply` for STALE_HOLD (2s), so the STALL hold never stopped the words
either.

Fix: `LocalPlayer` keeps `_seek = [to, when, landed]` until the position is seen
stepping forward from where the seek landed (near `to`), or SEEK_WAIT (3s)
passes. Until then, and during a stall, its readings carry `"held": True`.
`Clock` freezes `position()` on a held reading (`_audio_held`), skips the stale
rule and the slew for it, and holds straight from `seek()` when the transport
`holds_seeks`. Readings without `held` (Spotify and the other players) are
unchanged. test_local_seek drives a fake QMediaPlayer that refills for 0.4s.
Before the fix the words went 0.26s ahead and were pulled back; now they wait
at 80.0 exactly and never step back.

## 2026-10-19 — artists one by one, Apple's casing, comparing sources

- Apple's search now asks `include[songs]=artists`, so each credited artist comes
  back on its own. "Jennifer Lopez & David Guetta" is two; "Simon & Garfunkel"
  stays one. `Resolver._apple` stores them as the stream's `artists` and writes
  `artist` as "A, B". The local player's reading carries `meta.artists`. Streams
  resolved before this keep the old credit until their cached url expires.
- Casing: Apple title-cases everything; wifiskeleton's "ugly" is "Ugly" there
  and "ugly" on Deezer and YouTube Music. `SS.recase` keeps Apple's words in the
  song's own casing (title and album) wherever the two agree apart from case.
- Display: `who(it)` shows "A, B & C" only when the row's `artists` list
  rebuilds its "A, B" sub exactly, so "Tyler, The Creator" is left alone. The
  data keeps "A, B" because `song_key` and `artist_of` read the first name
  before a comma.
- Now-playing pill: the song opens its Song page, not the lyrics. Each artist
  (`np_artist`, hit only on the name's own height) opens its page.
- Song page sources: a click on a source row shows that source's lyrics
  (`fetch_source`: the provider in `LS.PROVIDERS`, through `_asks`). It is
  marked "Showing" and has no effect on what is in use. A click on the in-use row
  goes back. Line clicks and Copy use the lines shown (`_song_shown`).
- Line clicks use `is_current` (uri or track id), the same test the page paints
  with. Before, the click used `is_playing` alone and read the playing song's
  lines, so whether a click worked depended on how the song's id matched. A line
  of a song not playing starts it, and `observe` seeks once it plays
  (`_seek_when`, 30s).
- Autoplay: `play_stream` runs `autoplay_fill` at once, so the queue is there
  from the first song.
- Radio: `dz_artist_of` tries each credited artist (`credit_names`, lookups
  only), then the artist on Deezer's own copy of the song. If nothing answers
  online, `song_radio` builds the queue from liked and played songs and says so.
  The old code took the whole credit as one Deezer artist and gave "No songs
  like this one were found".
- `play_by_name` (saved lyric files, Genius rows): streams here when "Play songs
  in" is Mild Lyrics or Spotify is away. Otherwise it asks Spotify by title and
  first artist, through `home_q` and `found_by_name`. Spotify finding nothing
  now streams the song instead of the lyrics view's "kept what was playing"
  toast over the home page's.

## 2026-10-19 — Spicy missed on streams: a refused lookup was filed as "not on Spotify"

Case: "i must b retarded (feat. witchbox)" by wifiskeleton, streamed here. It
played under a stand-in key (`c8c02b85…`), so Spicy, which is keyed by Spotify
id, was never asked. streams.json had `spotify: ""` and `sp_tried` set. Asked
again later, `mb_spotify` found `34ukSEvDQJNSDpScxONSxH` (the embed confirms
title, both artists, 2:00). At play time MusicBrainz had refused: its limit is
one request a second, and the prefetch and autoplay resolve songs four at a time.
`spotify_id` swallowed the error, and the resolver filed it as "not on Spotify"
for a day.

- `_mb` retries a 429/503 once after 2.5s.
- `spotify_id(..., trouble=[])` names every step that could not be asked.
  `Resolver.sp_note` files "" with trouble as `sp_unsure` (asked again after
  SP_RETRY, 10 min), and "" without trouble as not there (SP_AGAIN, a day).
  Entries without `sp_v == 2` (written before this) are asked again once.
- A song playing from a kept link (stream-urls.json) skipped `_resolve`
  entirely, so its id was never looked for again. `LocalPlayer._load` now calls
  `Resolver.look_spotify` on the side. When the id turns up, `reading()` reports
  it (`spotify_of`), and the lyrics are fetched again with Spicy in the walk.
- `Tracker.observe` keeps one play when the id changes mid-song (same title and
  artist, position carrying on), so the switch is not logged as a skip plus a
  new play.

test_spotify_id (offline) covers all of this.

### Later the same night — "isnt it obvious" (wifiskeleton): two more ways to lose the id

- Spotify's Web API refused the kept token (429, Retry-After 42), and
  `spotify_web_search` returns None for that just as for "no token".
  `spotify_id` now counts None with a live token as trouble. `LS._WEB_WAIT`
  honours Retry-After, so nothing is asked again inside it.
- The lookups asked by Apple's title "Isn't It Obvious". The song is
  "isnt it obvious" on Spotify (confirmed by the user), Deezer and YouTube Music.
  `norm` turned "isn't" into "isn t", so no name ever matched. Now:
  - `norm` (and `LIB._norm`, `AP.norm`) drop apostrophes.
  - `recase` keeps the catalogue title whole when the two differ only in case
    and punctuation.
  - `_apple` records `src_title`/`src_artist`; `spotify_id_of` asks by those
    first, then by Apple's.
  - `Resolver.key` uses `src_title`, so a song keeps one key before and after
    the merge. streams.json had held it under two.
- MusicBrainz counts requests per address. The user's running app and a test run
  together drew a 503 even after one retry, so `_mb` now retries twice (2.5s,
  then 5s).
- Live: Deezer's "isnt it obvious" → `3xs8mxJv9I7pqRnBdmg4aa` (embed: same title,
  wifiskeleton, 1:48), title kept lower-case. test_spotify_id: 14.

## 2026-10-19 — more ways to a Spotify id, and every find checked

Measured on the 27 streamed songs in plays.jsonl that had no id (bench scripts in
the session scratchpad; the Web API step stubbed, since it is 429 nearly always):

- The chain as fixed above (refusals retried, own titles): 15.
- MusicBrainz by ISRC (Apple's ISRCs, `isrc/<code>?inc=url-rels`; a 404 means
  not in MusicBrainz): 11.
- The artist's public Spotify page. `open.spotify.com/artist/<id>` carries an
  `initialState` (base64 JSON): top tracks, the newest 5 albums and 8 singles
  (name and uri), and popular releases, all without a token. The release named
  like the song's album is opened first (album embed `trackList`). The artist id
  comes from MusicBrainz's artist url-rels, kept in spotify-artists.json (a
  missing link is asked again after a week): 13.
- Together, unchecked: 22. The search page and `/discography/all` are not
  server-rendered, and album pages' `moreAlbumsByArtist` adds nothing. Last.fm
  pages carry no Spotify links. song.link now needs an API key (401).
- Checked: 3 of the 22 were the wrong cut. "Alone (LUCA LUSH Remix)" and
  "Beautiful Now (KDrew Remix)" got the originals, because `norm` drops brackets
  and MusicBrainz recordings often have no length. "Moth To A Flame" got the
  3:54 single for a 4:41 stream. So `spotify_id` is now a list of steps, and
  every id any step names must pass `fits_spotify`: Spotify's embed for it has
  the same `versions()` words (remix, edit, live, sped, extended, …) and a
  length within DURATION_SLACK. A rejected find falls through to the next step.
  Result: 19 of 27, all checked right.
- Still missing: those three plus "Just Monika (cover …)", "Polark", "Moondance"
  (Saxsquatch), "Disco Night" (Kungs) and "Corridor" (wifiskeleton): older
  releases beyond what the artist page lists, or artists without a Spotify link
  in MusicBrainz.
- An uncertain miss (`sp_unsure`) now waits 10 min × 2^(n−1), up to a day
  (`sp_n`), since the Web API's 429 would otherwise make every real miss
  "unsure" forever.
- Ids found before this check (106 in streams.json) were not re-checked.
- Queue suggestions put their reason ("New to you · near GIMS") into `sub`, and
  playing one sent that reason as the artist. The reason now rides in `_shown`.

## 2026-10-19 — previews read as playback does, sources to compare, artists, banners, keys

**Song page / read-through lyrics didn't match the song.** Two causes. The bare walk the preview ran (`LS.fallback(..., "none")`) never asked Spicy Lyrics, never offered your own files (`local=`) and never shaped the answer, so NetEase/QQ/Kugou lines showed lumped with their ad-libs inside. Now `Fetcher.preview_body(tid, meta)` runs `_load_words`' picks (Spicy, the walk with `have`/`ahead`/`local`, the NetEase graft) and `_shaped` + uncensor, without touching the screen. Compared sources are shaped too (`shaped_copy`). And on the playing song the "now" line was found by TEXT, so a repeated chorus lit its first copy and dimmed everything before it; it is found by time now.
**Every source can be fetched to compare**, on the Song page and the read-through page: `source_rows_for_home` adds every provider not asked yet ("not asked · click to fetch", blends last), drawn one line each.
**Time in the editor** (Song page, song menu): the lyrics go to cache/home/editor/"Artist - Title.ttml" (a Spicy Lyrics sync never does: Apple's via `LS.apple_instead`, or none), and ttml-editor.pyw starts with `--title/--artist` and `--audio` (a file here), `--source spotify` (playing in Spotify), or `--fetch` (the editor finds the audio). Editor flags added for it.
**Artists:** "Mix from <artist>" (artist page, artist menu) plays `mild:mix:artist:<name>`. "Don't suggest this artist" is kept in `home_hidden` as `*|<norm artist>`; `banned_keys()` hands songs and artists to `autoplay.pick` (which reads `*|artist`), mixes and song radio; `build_recs` skips the artist. Settings ▸ Home ▸ Start suggestions over clears every dismissed song and artist (with Undo). Album menu: Go to artist.
**Main player** (Settings ▸ Home: Spotify / Mild Lyrics / Another player) decides the banner: "Spotify isn't connected" only for Spotify (with "I don't use Spotify", which sets Mild Lyrics), "No player found" for another player with nothing playing. Mild Lyrics also makes "Play songs in: auto" play here.
**Top songs chart** (Settings ▸ Home): Global / Viral 50 / Your country for the shelf and the Charts page's first pick; Deezer has Global only.
**Keys:** Q opens the Queue, Ctrl+Q quits (was Q). On the home page Q is taken before type-to-search.
**Onboarding step 3:** "Your sources" opens Settings ▸ Sources at the new Syncs list (lyric_sources.md).
Tested offscreen with test_home_page's setup (no network, writes stubbed): 40 checks, screenshots of the Song page, banners, drawer and onboarding.

## 2026-10-19 — skips no longer wait for the Spotify id

Bug: skipping in Mild Lyrics' player often meant more than ten seconds
of waiting. Measured on cold songs with a scratch cache: the audio was ready in
2-2.5s (Apple 0.4s, YouTube Music release 0.6s, yt-dlp URL 1.2s), but `_resolve`
waited for the whole `spotify_id_of` chain, and its `with ThreadPoolExecutor`
block waited past the 20s timeout too. Head Down 7.2s, Polark 8.7s, Corridor 18.5s
(the artist page alone 15s; MusicBrainz 503s retried at 2.5s and 5s). Also, a song
skipped to queued behind the prefetches in the same four threads.

- The id lookup is `look_spotify`'s job now, on a pool of its own (`_sp`). The
  stream waits for it only `SP_GRACE` (1.5s) past its audio, so a quick find still
  starts with Spicy. A later find is filed in streams.json and `live`, and
  `found_spotify` fires. The reading picks it up through `spotify_of`, the lyrics
  are fetched again with Spicy, and `Tracker` keeps it as one play. This reverses
  the 10-19 "whole lookup waited for" rule for slow songs: an obscure song can now
  switch from the name-searched lyrics to Spicy part way in.
- `want(t, now=True)` (from `LocalPlayer._load`) runs on `_now` (2 threads). A
  prefetch of the same song still queued is cancelled and moved there.
- `_resolve` merges only `yt`/`v` into `ids[k]`, so the side lookup's `sp_*` fields
  are not overwritten by a stale copy.
- Measured after: four prefetches plus a skip to Corridor, all cold: Corridor
  playable 3.5s after the skip (was 18.5s). Moondance's id came at 12s and Disco
  Night's at 17s, both filed. test_spotify_id: 28 (the priority check fails on the
  old FIFO pool).

Player row in the info overlay: while Mild Lyrics' own player is the one read
(`io.mine()`), it says "Mild Lyrics" with no Spotify debug-port error after it.

## 2026-10-19 — "Moves Like Jagger (feat. Christina Aguilera) [Studio Recording From "The Voice" Performance]" on "Tween Party"

The long title is real: Deezer's track 12724819 is "Moves Like Jagger (Studio
Recording From "The Voice" Performance)" on Hands All Over (Revised International
Deluxe), as on Spotify. Apple has the same ISRC (USUM71109132) on eight albums,
every one dated 2010-09-15, because Apple dates a compilation's copy by the
recording. `LS._cover_cut` ties on date and then takes Apple's order, so it picked
"Tween Party", whose copy has the longest title. The cover stayed Deezer's Hands
All Over, so the card disagreed with itself.

- `_cover_cut(rows, album)`: a copy on the album the caller names (editions and
  " - Single" dropped, `_album_of`) goes before date and order. `apple_song`
  passes `meta["album"]` and includes it in its `_once` key.
- `Resolver._apple` asks with the catalogue's album, kept as `src_album`, because
  `_load` merges Apple's album into the queued track. A track merged before this
  (it has `src_title` but no `src_album`) asks with no album, not with Apple's.
- Now: "Moves Like Jagger (feat. Christina Aguilera)", Hands All Over (Deluxe
  Edition). Hymn for the Weekend and Numb unchanged.

## 2026-10-19 — play on a restored queue no longer shows 0:00 first

Bug: opening the player went back to 0s for a second, then to the
real position. `start_cued` loaded the media and called `play()`, and
the saved place was sought only at LoadedMedia (`_status`). Until then `_sample`
read QMediaPlayer's 0:00 as Playing, and the clock, the bar and the lyrics
followed it. A stream-error reload (`_error`) went the same way, and a 15s save
during the load wrote 0.
- While `_resume_at` is pending, `reading()` reports it, `held` while playing,
  and `state()` saves it.
- At LoadedMedia the resume goes through `_do("seek")`, so it is held like a
  clicked line until the audio is heard moving there.
- test_local_seek: 10. Its new restore checks fail on the old code ("never shows
  0:00", "a save while it loads keeps the place").

## 2026-10-19 — suggestions without Spotify

"Like this song" said "Suggestions need Spotify's catalogue" whenever Spotify's
page was away. Now:
- **This song**: Spotify's `v.suggest` while online. Otherwise the playing song's
  credited artists (`meta.artists`, else `credit_names`, up to 3) are found in the
  catalogue in use (Deezer), and their top songs ("Same artist") and four related
  artists' top two ("Similar to …") are used, the same shape as Spotify's.
- `artist_uri` ignores remembered `spotify:` artist ids while offline (the
  mirrored library and liked songs carry them), so **Your listening** and
  **Something new** look the artists up on Deezer instead of asking a Spotify that
  is not there. Offline the reason reads "Near X", not "Spotify's pick near X".
- The playing song is left out of its own suggestions by name, since a Deezer
  copy has no Spotify uri to compare.
- With no play log, offline, Your listening says "Nothing logged yet" instead of
  waiting on Spotify's play history for ever.
- test_home_page: 154 (an offline This song check on stubbed Deezer data). Live:
  Lukas Graham on Deezer gives Mama Said, Love Someone…, related Christopher,
  Ed Sheeran, Dermot Kennedy, Tom Walker.

## 2026-10-19 — Pasted links

`mild-lyrics/pasted_links.py` reads a link from Spotify, YouTube, SoundCloud,
Apple Music, TIDAL, Bandcamp or Deezer without Spotify and without signing in.
The results have the same shape as a catalogue search's, plus a `top_item`, so
the search page and `play()` use them as they are.

**Where a paste lands**
- **Ctrl+V on the lyrics** (`paste_to_play`):
  - A Spotify song or album link, with Spotify there, takes the old route
    straight to Spotify.
  - Any other link goes to `Home.play_link`. That covers Spotify artists and
    playlists (the old regex never read them), any Spotify link while Spotify
    is away, and every other service.
- **Ctrl+V on the home page** (any page but search) opens Search with the
  clipboard in the box.
- **The search box**: a link is read by `Home.links`, a `Links(HD.Spot)` that
  `search_src(q)` picks, instead of being searched. A link that can't be read
  shows its reason in place of "Nothing found".

**Where it plays**
- `play()` as for anything picked on the home page, so the Play-in setting is
  followed.
- **Spotify there and the player:** a catalogue song from Apple Music, TIDAL
  or Deezer is first looked up with Spotify's own search (`on_spotify`,
  `_match_rows`). When found, its uri becomes the Spotify one.
- **Uploads** (YouTube, SoundCloud, Bandcamp) are never swapped. They carry
  `yt` (the video id or page URL), so the Resolver streams exactly that upload
  and doesn't search for a copy.
- `play()` now also plays an item with no uri but with `tracks` (an Apple or
  Bandcamp album, a YouTube playlist or SoundCloud set) in Mild Lyrics' player.
- The playlist page shows a pasted playlist's own `tracks` when `pl_data` has
  nothing for it.

**What each service is read from**
- **Spotify:** the embed page (`SS._embed`), the same one the Resolver uses.
  Song, album, artist (top 10), playlist (first 50). Short links (spotify.link,
  spoti.fi) are followed.
- **YouTube:** oEmbed for one video (title, channel; no length). yt-dlp, flat,
  for a playlist (up to 100). `song_of_video` names the song, as the YouTube
  tab does.
- **SoundCloud:** yt-dlp for one song (about 0.8s, and it gives the length).
  A set is read flat by yt-dlp, then each song's name comes from oEmbed, six
  at a time.
- **Apple Music:** the public iTunes lookup API, with the link's own
  storefront. An artist lookup also brings songs they only feature on, so the
  songs are filtered by `artistId`. Playlists need a signed-in token: refused
  with a message.
- **TIDAL:** the share page's tags.
  - Song: `og:description` "Listen to X on TIDAL" is the title, `og:title`
    "Artist - X" the artist, and the `description` tag's "from the album Y"
    the album. There is no length.
  - Album or artist: the page only names it, so its songs come from the same
    release on Deezer, found by name.
  - Playlists are refused.
  - Not used: gqlapi.tidal.com, which no longer resolves, and the v1 API,
    which needs a token.
- **Bandcamp:** the mobile API `api/mobile/25/tralbum_details`, keyed by the
  page's `bc-page-properties` and `data-band-id`.
  - The installed yt-dlp (2026.08.19) fails on every Bandcamp page ("Unable
    to extract tralbum data").
  - So `SS._audio` sends a `.bandcamp.com/track/` URL to
    `pasted_links.bandcamp_audio`. That reads the mp3-128 `stream_redirect`
    fresh each time and follows the redirect once.
- **Deezer:** its public API, through the existing `dz_*`. Short links
  (link.deezer.com, deezer.page.link) are followed.
- **Not tried:** Odesli (song.link), which now answers 401 without a key.

Tests:
- `~/mild-lyrics-archive/tests/test_pasted_links.py` (61 checks, offline),
  from answers recorded into `fixtures/pasted_links.json`.
- `test_home_page.py` "pasted links" (13 checks, real window offscreen). These
  cover Spotify away and there, a Spotify artist link, an Apple song swapped
  to Spotify, a YouTube upload kept, a Bandcamp album with no uri, an
  unreadable link, and Ctrl+V into search.

### Pasted ids and album-page links (same day)

- **Bare ids** (`bare()`): the whole paste is the id. Inside a sentence it is
  not one.
  - Spotify's 22 characters (digit, upper and lower case all present) are read
    from the embed as a song, else as an album. With Spotify there, they keep
    the old `request_play_id` route.
  - YouTube's 11 characters (upper, lower and a digit or `-`/`_`) are read as
    that video.
  - **A number of 6 to 12 digits** (`numbered()`) is asked of Apple Music
    (lookup: song, album or artist), TIDAL (song page) and Deezer (song) at
    once.
    - One answers: that is it.
    - Several name the same song: the first.
    - Several name different things: they come back with `choices`. Ctrl+V
      then opens Search on the number to pick from, each row saying which
      service it is.
    - Numbers under 6 digits stay searches ("1999", "22").
- **Prefixed ids**: `tidal:track:<id>`, `deezer:album:<id>`,
  `youtube:video:<id>`, and the like.
- **A song picked on its album's page is that song**:
  - TIDAL `album/<id>/track/<id>` (listen.tidal.com and tidal.com/browse).
  - Spotify `album/<id>?highlight=spotify:track:<id>`.
  - Before this, the TIDAL form was read as the whole album.
- **A TIDAL album's songs** (`_on_deezer`):
  - It required Deezer to have the album under exactly the same name, by
    exactly the first artist, and gave an album with no songs when it didn't.
    That album played nothing, which is the likeliest form of their "doesn't
    work".
  - Now: the same name, else one name starting with the other (Remastered and
    Deluxe), by the first credited artist; then Apple's album search; then a
    message.

Tests: test_pasted_links has 90 checks (fixtures re-recorded with the ids),
test_home_page 172.

### Qobuz (same day)

**Links read:**
- `open.qobuz.com` and `play.qobuz.com`: `track`, `album`, `artist` and
  `playlist` links.
- The store's `/<cc-ll>/album/<slug>/<id>` and
  `/<cc-ll>/interpreter/<slug>/<id>` (an artist).
- `qobuz:track:<id>`.

**How it reads them:** through Qobuz's JSON API (`www.qobuz.com/api.json/0.2/`,
`track/get`, `album/get`, `artist/get`, `playlist/get`). The API wants only an
`app_id`: no sign-in, and not the app secret.
- `qobuz_app()` reads that id from open.qobuz.com's own `main.js` once a run,
  as the Apple key is read off music.apple.com. It was 712109809 on
  2026-10-19.
- On a 400 or 401 it is read once more.
- The store pages also list an album's tracks, but `open.qobuz.com` and
  `play.qobuz.com` are empty React shells, and a single track has no page at
  all.

**Artists:** `artist/get` has no top tracks (`extra=top_tracks` is a 400). The
songs are taken from `tracks_appears_on`, filtered to those whose performer is
the artist, and the artist page itself is found by name, as Apple's is.

**Bare numbers now ask Qobuz too.** Its ids share the range with TIDAL's, and
both real ids tried collide:
- 58990516 is Karma Police on TIDAL and "ЭГО" on Qobuz.
- 33933722 is Karma Police on Qobuz and "Si Vas a Calatayud" on TIDAL.

A bare number from either service is therefore often offered as a choice
rather than played. Links never are.

Tests: test_pasted_links has 104 checks, with the Qobuz answers recorded
(main.js cut to its `app_id`).

## 2026-10-20 — Matching by ISRC (SpotiFLAC's matching, not its downloading)

They asked what github.com/spotbye/spotiflac does.
- **Its matching:** Spotify's internal metadata for the ISRC, then the same
  ISRC looked up on Tidal, Qobuz, Amazon and Deezer.
- **Its downloading:** "community" proxy servers, whose addresses are
  AES-encrypted in the binary, hand out FLAC links or Tidal manifests from
  other people's accounts. For Amazon it also gets the decryption keys and
  strips the protection locally.
- **Decided:** keep the matching, never the downloading. Nothing of its
  code is used.

**What was built:** an ISRC names the exact recording, so where Mild Lyrics
streams a song it now finds the song's Spotify id by ISRC before any name.
This matters for Spicy Lyrics and for playing it in Spotify.
- **Where the code comes from:**
  - The song's own catalogue: Deezer's search rows carry `isrc`, and so does
    every Qobuz track (`_qb_row`). `Home.stream_of` passes it on.
  - Else Deezer's search by name (`SS.dz_isrc`): same title, same first
    artist, the length to `DURATION_SLACK`; with no length, the plain release
    before a `title_version`.
  - Deezer's `artist:"…" track:"…"` advanced search answers nothing for any
    artist (2026-10-20), so the query is plain "artist title" and the row
    checks do the matching.
- **Where it is used:**
  - `Resolver.look_spotify` (on the side pool, off the playback path) calls
    `isrcs_of`, which keeps the code in streams.json beside the song: `""` for
    none found. A Deezer error is not kept, so it is asked again.
  - `spotify_id(…, isrcs)` asks `spotify_by_isrc` first: Spotify's Web API
    `isrc:` search (where a token is kept), then MusicBrainz's link for the
    ISRC. Each find is checked with `fits_spotify`, as before.
  - `spotify_id_of` asks the codes once, not again for each spelling of the
    name.
  - `LS.spotify_web_search(meta)` asks `meta["isrcs"]` instead of Apple's
    when given.
  - **Pasted links** (`on_spotify`): when Spotify's search names nothing, the
    song's own ISRC or Deezer's is asked.
- **Measured live:**
  - Karma Police, Blinding Lights and Bohemian Rhapsody each go from name to
    ISRC to Spotify id in about 1-2s.
  - Bohemian Rhapsody at a wrong length (300s) finds no code, so nothing is
    taken.
  - Never Gonna Give You Up gets GB5KW1903177, which MusicBrainz has no
    Spotify link for, so the name steps run as before.
- **Not done:** Spotify's own ISRC for its tracks. SpotiFLAC reads it from
  `spclient` metadata with an anonymous web-player token made by a
  reverse-engineered TOTP (`spotify_totp.go`), which is not something to copy.

Tests: `~/mild-lyrics-archive/tests/test_isrc_match.py` (23 checks, offline),
`test_pasted_links` (106), `test_spotify_id` (29, unchanged),
`test_home_page` (172).

## 2026-10-20 — mini player: whole words, the rest of the song, credits

`sweep` wrapped a syllable at a time, so "toge|ther" broke across rows. It now
wraps a word at a time (pieces joined to the next one stay together) and only
cuts inside a word wider than the row. A tall mini window was mostly empty
below the next line: the sung line now takes up to 3 rows (by room), and the
lines after it follow, up to 2 rows each, as far as the controls. The credit
block follows the Credits on top setting: with it on, it stands above the
first line until that line starts; with it off, it follows the last line in
the list and stands alone once the singing ends (`mini_credit_due`).

## 2026-10-20 — prefetch depth from your skipping, warm restarts, saved volume

The lyrics fetch-ahead for Mild Lyrics' own queue is mild-lyrics-bf's work
(`local_ahead`, `ahead_soon`; lyrics_gui.md). This section is the audio side only.

- **How far ahead streams resolve** (`LocalPlayer.AHEAD`, a property now):
  the longest of the last `BURSTS_KEPT` (20) runs of quick skips, clamped to
  `AHEAD_MIN`..`AHEAD_MAX` (3..10). A skip (`step(+1)`, not an end) within `QUICK`
  (10s) of the song changing, on a song reached by a skip, lengthens the current run;
  anything else starts a new run of 1. `_changed_at` moves only when the track
  object changes, so a stream-error reload is not a song change. The runs are kept
  in player.json (`bursts`).
- **The restored queue is warmed**: `restore` schedules `_warm` after `WARM_AFTER`
  (4s). It makes the resolver (`ensure`) and resolves the cued song plus `AHEAD`
  more. Nothing is loaded into QMediaPlayer and no audio output is made, so no
  sink stream appears at startup. This replaces the 10-19 "nothing is loaded or
  fetched" rule: links, yes; media, no.
- **Re-resolving a known song is just yt-dlp now.** `_resolve` tried the saved
  upload first, but built the candidate list (YouTube Music search, and
  `local_align.find` when that failed, up to ~4s) before trying it. Now the
  candidates are a generator, searched only if the saved upload fails. Apple's
  name is kept in streams.json (`meta`, `meta_v` = `META_V`) and reused; an empty
  answer (maybe Apple unreachable) is not kept. So a link that expired overnight
  costs ~1.2s, during the warm-up rather than after Play.
- **Volume** is saved in player.json with the queue, or alone when there is no
  queue (`state()` always returns the volume and runs; `save` no longer deletes the
  file), and restored at startup. The 15s saver still runs only while there is a
  queue, so a volume change with an empty queue is written at close.
- Tests: test_local_seek 17 (runs → depth, cap, forgetting, volume without a queue,
  warm-up), test_spotify_id 31 (cached upload and name, searched again when the
  upload is gone), test_home_page 183, test_isrc_match 30.

## 2026-10-20 — Apple's ISRCs; Spotify id, lyrics and romanisation fetched ahead

**ISRCs:** `Resolver.isrcs_of` takes the song's own code first, then Apple
Music's (`LS.apple_isrcs`, best first, two at most), then Deezer's by name.
- Apple's are asked with `_apple_meta(t)`, the meta `_apple`'s card is asked
  with, so within `ONCE_TTL` (25s) it is the same answer and not a second
  request.
- Kept as `ids[k]["isrcs"]`, `[]` when nothing anywhere had one. When neither
  service answered nothing is kept, so it is asked again.

**Spotify id ahead, for songs not played through Spotify:**
- `LocalPlayer._prefetch_quiet` now also calls `resolver.look_spotify(t)` for
  queued **files**; streams already got it through `want`.
- A found id is kept under the song's name keys (`keep_for_lyrics`, both the
  catalogue's and Apple's spelling).
- `Fetcher._load_words` reads such a kept id (`LS.spotify_id_known`) even with
  Spotify lookup off. That setting gates searching through the reader's
  signed-in Spotify app, and these ids came from public sources.
- So a name-keyed song (a local file, or a stream whose id came late) goes to
  Spicy Lyrics on its first walk instead of walking the rest and then again
  once the id lands.

**Lyrics ahead from Mild Lyrics' own queue:**
- `fetch_ahead_scan` takes `local_ahead()` while the local player is the one
  in use (active with a current song, as `LocalOverlay.mine`), and Spotify's
  queue otherwise.
- Each row is under the id the song will be read by when it plays
  (`LocalPlayer.reading`).
  - Stream: its Spotify id when known, else the name key.
  - File: `t["tid"]` or the name key.
  - A name-keyed row carries its found Spotify id as `meta["_spotify"]`.
    `Fetcher._warm` pops it and asks Spicy by it once (disk-cached), and the
    walk itself is by name.
- `ahead_soon()` (a 600ms single-shot) rescans on `player.changed` and on
  `resolver.found_spotify`.

**Spicy is never asked by a name key now** (`from_spicy`, `SONG_KEY_HEX`):
- A name key is 22 lowercase hex, which passes `SPICY_ID`.
- Every new song from a player with no Spotify id spent a request that could
  only come back empty. That predates this work.

**Romanisation ahead** (Use Genius on):
- `Fetcher.ahead_ready` also feeds `roman_ahead(tid, raw)`. It builds the
  coming song's lines and, where any line needs romanising, asks
  `request_roman_ahead`.
- The `_romans` worker (thread `roman-ahead`) waits out a song being loaded,
  as `_warm` does, then asks Genius (`find_romanisation`, then `align` through
  offload) and NetEase (`netease_roman` + `fit_pairs`).
- `on_roman_ahead` keeps the answer as the live path keeps it:
  - Genius's mapping becomes `genius_fixes(..., lines)`, stored in
    `genius_fix[tid]`. `genius_fits` is cleared, so it is judged again on the
    lines it is drawn on.
  - NetEase's goes into `ne_fix[tid]`.
  - Nothing found goes into `genius_tried`.
- `maybe_auto_genius` skips a song whose ask is still pending
  (`roman_pending`).
- `genius_fixes`, `line_readings`, `own_readings` and `drop_echoed_adlibs`
  take `lines=` for a song that is not on screen. `on_genius` uses
  `genius_fixes` and behaves as before.
- This covers Spotify's queue too, not only the local player's.

**Concurrent work:** another session (mild-lyrics-98) changed `LocalPlayer.AHEAD`
to follow skip bursts (3 to 10) and added restore-time warming and
`_resolve`'s cached upload and meta. The resolver lookahead follows `AHEAD`;
lyrics and romanisation ahead follow Settings ▸ Fetch ahead.

Tests:
- `test_isrc_match` (30): Apple first, Deezer second, kept, name keys,
  Spicy skip.
- `test_home_page` (183): local queue rows and ids, back to Spotify's queue,
  romanisation asked once, kept, misses remembered, nothing asked when nothing
  needs romanising, the worker end to end with Genius and NetEase stubbed.
- `test_spotify_id` (31), `test_pasted_links` (106), `test_genius_adlibs`
  (20), `test_adlib` (12) pass.
- `test_roman_review` (25/1) and `test_players` (161/3) are the baseline reds.

## 2026-10-20: artist page fixes, names in the lyrics view

- Top songs wrote each row's album into `sub`, which is the artist: the table
  showed albums where artists go ("other artists' songs"), and a row opened as
  a song page carried the album as its artist, so the page missed the playing
  song and looked its lyrics up under the wrong name. Rows now keep `sub`.
- Deezer rows have no Spotify id, so `kind_of` knew nothing about them ("none
  of the top songs has lyrics" while one played). `tid_by_name` maps
  (title, first artist), normalised as autoplay does, to the playing song's
  tid or the one the play log heard; `is_current` uses it too.
- The header band is snapped to device pixels: at a fractional edge the clip
  let one more row of the photo through than the fade covered.
- Middle-click autoscroll (the `middle_scroll` setting) works on every
  browse page; `hot` there would be the lyrics view's, so it is not read.
- Lyrics view: every credited name is a hit region; one with no Spotify uri
  carries `name:<Name>` and opens the artist page by catalogue lookup.
  Credits fall back to the player's own artist list (`meta["artists"]`: the
  local player's, Spotify MPRIS's xesam:artist) before the one artist line.
- Artist names are spelt the player's way: Deezer capitalises "shambles" as
  "Shambles". `spelt` takes the playing song's credits, else the play log's
  spelling (case-insensitive match), for the page title and the Top songs
  credit line (`_shown` only; `sub` keeps the catalogue's). The Deezer fan
  count is gone from the line under the name; Spotify's monthly listeners stay.

## 2026-10-22: covers load faster

ArtCache had two workers taking urls first in, first out, each fetching and
decoding the full-size picture: scrolling Liked songs queued every row passed,
the rows on screen waited behind them, and an artist grid filled one tile at a
time. Now: six workers; a LIFO queue; a url not drawn for STALE (2s) is dropped
from the queue and asked again if it comes back. `cover()` passes the size it
draws at, and `sized_art` asks Spotify's 64/300/640 (covers) or 160/320/640
(artists) copy, Deezer's 250/500, measured 1.8KB for a row's cover against
~100KB. A full-size copy already on disk is used before fetching a small one.
Memory pressure clearing the pixmaps now clears `seen` too; before, every card
it let go of stayed blank.

Artists tab, same day: its tiles for artists only in the play log had no
picture until `artist_face` ran a full catalogue search per name, all on the
pages' single reader thread (Spot._reads; through Spotify when it is up), and
held only in memory. Now `SS.Faces`: one Deezer `/search/artist` per name,
four at a time, kept in cache/home/artist-faces.json (a miss is asked again
after a week; "A & B" credits fall back to A). Measured on their top 24:
0.9s together, against ~0.2s each one after another through Deezer before.
With Spotify up, the tile's uri is still Spotify's where `artist_uris` knows
it; otherwise the page is found by name when clicked.

Same day, decided: Apple Music first, Deezer second (`apple_face`, with the
lyrics' own catalogue key from LS._apple_token, asked directly rather than via
LS._amp so a miss is not filed against Apple's lyrics). On their top 24: all 24
from Apple in 1.7s, including VALORANT Music, which Deezer lacks. The file
carries `_v` 2; Deezer-only entries from v1 are asked again. `sized_art` also
sizes Apple's mzstatic urls (120/250/500/1000): a row's picture is ~5KB.
TIDAL was not added: its search needs registered developer credentials.

## 2026-10-22: a restored queue plays at once

Bug: after playing in Mild Lyrics, the song took about a second to play
after reopening the app. Measured: the first QMediaPlayer made in a process
costs ~0.7s on the GUI thread, nearly all of it Qt's FFmpeg backend probing
hardware video decoders (py-spy: ioctls). `local_player` now sets
QT_FFMPEG_DECODING/ENCODING_HW_DEVICE_TYPES to "," (setdefault) before any
player exists: 717 -> 21ms bare, 38ms through `_make`; audio-only, so nothing
lost (three stream links still play). And when the queue was last played here
(`active`), `restore` warms its links after `WARM_ACTIVE` (0.5s, not 4s).

Tried and removed the same day: loading the song before Play into a player
with NO audio output (no sink stream at startup), adding the output at Play.
Play to moving went 0.2 -> 0.05s silently, but its first form ran the 0.7s
init at startup (froze the lyrics), and with it the lyrics jumped back and
forth while playing. Not proven to be the cause (that needs audio through
their speakers), but it was the one change to how the player keeps time, and
attaching an output to an already-loaded FFmpeg player may switch its clock.
If it is tried again: attach the output before setSource and check for a
corked sink stream at startup.
Tests: test_local_seek 18, test_home_page 183.

## 2026-10-22: a dropped stream really carries on now

Reported again: "randomly into some songs, the song just stops and goes back to 0 seconds". The 2026-10-19 fix never worked. Reproduced with a real Qt 6.11 QMediaPlayer, a local HTTP server that cuts the connection at 25%, and a QVideoSink on a small video so playback depends on the data arriving. That way nothing reaches the speakers; with no output at all, Qt runs the position off a timer and never notices the drop.

What Qt does on a cut stream: no reconnect. It fires `errorOccurred(ResourceError, "Demuxing failed")` every ~100ms while the buffer plays out, with the position still right. So `_error` gets the true place. Then `_load` calls `player.stop()` on the dead stream, and that stop reports `LoadedMedia` at once. `_status` took that as the fresh link having loaded, and spent `_resume_at` seeking the stopped player. While the link was fetched again, `reading()` said 0:00, and the fresh link then played from 0:00.

Now `_load` notes the source it sets (`_resume_src`, local files included, since a restored queue resumes the same way). `_status` only spends `_resume_at` once `player.source()` is that source.

At the user's ask, a drop no longer stops anything. `_error` asks the resolver for a fresh link once (`_refetch`; the repeats every 100ms are ignored). What Qt has buffered plays on, about 4s in the harness. `on_resolved` then calls `_switch`, which loads the fresh link at `_heard`, the last position seen while playing. When the buffer runs dry first, Qt sits in PlayingState with the position frozen, with no EndOfMedia and no reset to 0. The reading holds there, after the usual 0.6s STALL run-on. Measured on the harness: a link back in 1.5s switched at 5.0s with ~0.25s of silence; one back in 6s held at 7.7s and carried on from 7.7s. An EndOfMedia cut short holds `_heard` the same way. The retry count also starts over once a song has played 30s since its last drop (`_failed_at`, kept out of the saved queue), so a long song with a few drops is not given up on.
Tests: test_local_seek 21. test_home_page is 142 ok, 2 failed, the same with or without this change ("20 Min" turns up from something live).

## 2026-10-22: YouTube rows name the song, and producer credits are packaging

Screenshots: a YouTube-tab row read "Fetty Wap - Trap Queen (Official Video) Prod. By Tony Fadd" / "Harlem Fetty", and it played as "Trap Queen Prod.". `song_from_video` had no rule for producer credits. `song_of_video` then cut at " By ", which left "Prod." and, on a bracketed credit, half a bracket ("Superhero [prod"). Now `PROD` / `TRAILING_PROD` in lyrics_gui drop "(Prod. By X)", "[prod by X]", "(Produced By X)" and a trailing "Prod. By X" / "prod. X". A bare "prod" is left alone, so The Prodigy and "Product of Me" stand. The rule is shared with the bus players' cards. With the right title, the stream resolver's Apple and Spotify lookups can match; the old record was keyed "trap queen prod" with no Spotify id.

`yt_search` rows now show the song (`name`) and its artist (`sub`), the way every other row does. The uploader follows as "Fetty Wap · Harlem Fetty" when it isn't the artist (compared without spaces, so FettyWapVEVO counts as Fetty Wap). The raw title stays in `video`.
Tests: test_players (cleaner cases added; 3 handover checks fail with or without this change), test_home_page 185.

## 2026-10-22: YouTube picks get the release's cover and the right way round

Screenshots:
- Dreamflasher, played from the YouTube tab, showed the video thumbnail (`i.ytimg.com/.../hq720.jpg`, a 16:9 frame cropped square) as its cover. Apple's square cover was in the resolution's `meta`, but `_take` (and `_resolve`'s merge) kept any art the track already had. A `ytimg.com/` thumbnail now gives way to the release's cover.
- In The End showed as "Linkin Park" by "In The End". Its official upload is titled "In The End [Official HD Music Video] - Linkin Park", song first. `song_from_video` always read "A - B" as artist - song. Now, when the channel names the right half and not the left, it is read song first ("Hello - Adele" on AdeleVEVO too). With the names backwards, the Spotify id lookup failed, so the Spicy Lyrics Community sync (asked by Spotify id) never came, and Musixmatch (asked by name) won.

Tests: test_players (two song-first cases).

## 2026-10-22: somebody else's recording, and somebody else called NF

From the Inside played a tribute act's cover (`r3hKbooHp5w`, artist "METEORA: Tribute to Linkin Park", 175s). `release_of` asked only that "linkin park" appear somewhere in the artist, and the tribute was a second nearer the length than Linkin Park's own 176s copies. Now:
- The artist must be one of the credited names (`_credited`).
- Tribute, karaoke, "in the style of", lullaby and similar releases are refused (`NOT_THEIRS`), unless the song asks for one.
- Saved uploads below `PICK_V` 3 are picked again once.

Autoplay went from NF's HOPE to "Be the Same" by NF!. Deezer lists "NF!" (48 fans) before NF (661,122) for "NF", and `dz_artist_of` took the first name that matched once punctuation was ignored. `best_artist` (stream_source) now takes an exact name first, then the most fans. It is also used by `dz_search`'s top hit, `dz_face` and `artist_found`.

## 2026-10-22: autoplay when nothing online answers

Bug: "Not Like Us" did not autoplay, and making a queue from it gave Linkin Park, Slipknot and Architects. That queue was not autoplay's choice. It was `song_radio`'s fallback to "your own songs" (Mild Lyrics' likes, then Spotify's, then recent plays), which ran when `auto_candidates` came back empty and not waiting. Decided: never make a queue out of nothing. When nothing online answers, check whether there is a connection at all. If there is none, say so and wait for it.

Why it came back empty:

- **Deezer's quota became a cached "no songs".** Deezer allows 50 asks in 5 seconds per address and refuses past that with HTTP 200 and `{"error": {"code": 4, "message": "Quota limit exceeded"}}`. `_get` returned that body, and `dz_radio` / `dz_artist` / `dz_search` turned it into empty lists that were kept: 30 minutes for radio and artists, a day for searches. One autoplay fill for one seed made 41 asks in 3.9s (four per artist page, one page for each of six related artists), and a fill can have up to three seeds. A restart cleared it, which is why it worked again after one.
- **Spotify's song radio returned null.** The client had been updated that day (`searchDesktop` is gone from its GraphQL definitions), and a null read is not stored. Every `got(key, None)` re-ran `autoplay_fill`, which asked again, so the app looped against Spotify.

Now:

- `stream_source._get` raises on a Deezer error body and paces Deezer asks to `DZ_PACE` (40 in 5s), across every caller.
- `Spot` (and `Deezer`) remembers a failed read in `fails` for `FAIL_WAIT` (30s) and does not ask it again in that time. `failed(key)` says so. `want_only` (a search typed again) and `drop` clear it.
- `auto_candidates` returns `(cands, waiting, failed)`. Related artists come from `related:` and their songs from `top:`, one ask each, unless an artist page is already held. One seed is now 14 asks.
- Nothing found, nothing waiting, something failed: `when_online(then, offline, gave_up)`. `NetCheck` tries a TCP connection to api.deezer.com, then 1.1.1.1 (in case only DNS is down).
  - Offline: say so, poll every `NET_POLL`, and once it is back clear the failures and run `then`. The queue page shows "AUTOPLAY · OFFLINE, WAITING FOR A CONNECTION…".
  - Connected but the sources failed: say so once, retry `NET_RETRIES` times `NET_RETRY` apart, then say it gave up.
- Nothing found and nothing failed: autoplay says "Autoplay found no songs like this one" (only when nothing is queued after), and song radio says "No songs like this one were found". The own-songs fallback is gone.

Tested offline on the real `Home` methods, with a stand-in player: Spotify silent (25 queued from Deezer, the radio held), every connection refused (the offline message, nothing queued, 25 queued once connections were allowed again), Deezer's quota body (raised, nothing kept, retried and then given up), and `song_radio` with failed or empty sources (no queue). `tests/test_home_page.py` stubs updated to the three-value returns: 185 ok.

Same day: "Psychoboost feat danny brown" by Jane Remover, Danny Brown. Apple's card writes the title that way, and `recase` only restores the capital. `drop_credited_feat` (stream_source) now removes a feat/ft/featuring clause, or a bracketed "with", when every name in it is already in the artist line. Otherwise the clause stays ("Medicine (feat. Conor Maynard)" by ANTH). It is applied in `Resolver._resolve`, so names already saved in streams.json are fixed without asking Apple again.

Same day: searching "underscores" with Spotify closed (Deezer answers) listed "harvest sky" (Oklou's song, underscores featured), then Bodyfeeling, The Peace and Wish U Well. Deezer's search order and its own popularity both put harvest sky first (`rank` 595,519 against 337,185 for "Spoiled little brat"), so Deezer has no better order to sort by. When the best-matching artist is credited on at least 2 of the first 5 songs, `dz_search` now leads with songs where they are the lead artist (`_own_songs_first`), ordered by Apple Music's top songs for them (`apple_top_songs`, two asks, cached per name). Titles are compared by `_song_title_key`, which drops a feat clause but keeps "(Yves Remix)", so a remix does not take the original's place. A second release of a title already in that block goes back with the rest. Everything else follows in Deezer's order, and when Apple cannot be asked the artist's own songs still come first. Underscores now starts The Peace, Music, Do It, Wish U Well. "believer" is untouched, because the band named Believer is not on Deezer's first five songs.

Same day, decided: search should not depend on Spotify. The Spotify client had lost `searchDesktop`, so with Spotify open the full search failed and only the quick search's mixed list of 12 answered. `Home.cat_q` now searches Deezer (with the artist ordering above) whether or not Spotify is open. It searches Spotify only when Settings ▸ Home "Play in" is set to Spotify, where every pick has to land in Spotify. Deezer rows always play in Mild Lyrics' own player, and Deezer artists and albums open Deezer's pages. `JS_SEARCH` is left as it is and is unused under the default settings.

Same day: search should match by meaning, not only by text. Searching "nastywerk" should bring up ISSBROKIE, because one song is called that. Deezer's answer had no ISSBROKIE at all: "NASTYWERKKKK!" is filed under femtanyl, with ISSBROKIE a second main artist only in the track's contributors, followed by "Nasty Word", "Nasty Work" and others by unrelated artists. No learned embedding was built: it would need a model and a catalogue to embed. The catalogue's own data does the job instead (`_title_points_to_artists`):

- A song counts as a match when its title, by `_song_title_key`, starts with everything typed and the typed text is at least 60% of the title. Matching the other way, a title that is a prefix of the query, let "Harvest" by three artists match "harvest sky".
- If the matches have at most `TITLE_ARTISTS` (2) lead artists, the most-played match is the anchor. Its full credits come from `/track/<id>` contributors.
- The results become the matches, then the credited artists' Deezer top songs taken in turn, then the rest. The credited artists go first in the artist list.
- It costs up to 4 extra Deezer asks, under `DZ_PACE`, and it only runs when the query is not itself an artist's name.

Measured: "nastywerk" gives femtanyl and ISSBROKIE, with NASTYWERKKKK! then their songs. "harvest sky" gives Oklou and underscores. "bodyfeeling" leads into underscores. "believer", "love", "blinding lights", "mansion" and "nasty" are unchanged, because too many artists have a song called that.

## 2026-10-22: autoplay follows the song you chose

Bug: autoplay keeps playing illogical queues, after every fix. Measured
(player.json and plays.jsonl, read-only): from underscores' "The Peace" every
pick was a `deezer:track` (Spotify's radio has answered null since the client
update), and five of the first six played were skipped. Four causes:

- **Seeds drifted.** It seeded from the song playing and the two before it, soon
  autoplay's own picks, skipped ones included.
- **Nothing was song-level.** Deezer's path was the artist radio of the last three
  artists, round-robin with the top 4 songs of six related artists each: up to 21
  lists, 18 of them other artists' hits. NF's related list has David Kushner 4th,
  which is how "Outro" went into "Daylight".
- **Rank barely counted.** `-rank + uniform(0, 4)` over that interleave.
- **Skips were not heard.** Only songs skipped twice were left out.

Now:
- **Anchor** (`auto_seeds`): the last song without `_auto` at or before the one
  playing. Up to two of autoplay's songs after it seed too, once heard past
  `SKIP_BEFORE` (`_heard`, set in `observe`). A skipped song never seeds. "Make a
  queue" on a song playing clears its `_auto`, so it becomes the anchor.
- **YouTube Music's song radio** (`SS.yt_radio`, the `next` endpoint with
  `RDAMVM<videoId>`, WEB_REMIX, no account). Art Tracks only; the video id is the
  resolver's (`Resolver.yt_of`). Probed with five seeds: 50 rows each, ~1s, all
  answered. An answer with no rows fails rather than being kept as "no songs".
- **Fusion** (`AP.fuse`): reciprocal rank fusion, k = 8 (morelike's finding:
  k = 60 makes a short list's 1st and 20th equal). Weights: the anchor's YTM radio
  and Spotify radio 1.0, heard seeds' 0.5, Deezer artist radio of the anchor 0.5.
  Related artists' hits (0.25) only when the rest give fewer than `AHEAD`.
  `autoplay_fill` waits while any ask is on its way, unless the queue has
  ended, so the sources fuse rather than the first to land deciding.
- **pick** on fused songs: `_fused × 100` is the score. Likes, favourite artists
  and word-by-word are scaled to 0.35, and noise is under 0.5, so they tip ties
  and do not lead. Callers with no `_fused` (the mixes in home_pages.py) get
  exactly the old run (test). "Make a queue" in Mild Lyrics' player goes through
  the same fusion, and waits for every source before it builds the queue.
- **Skips** (`auto_heard`, from the tracker's new `on_row`; play rows carry
  `auto`). An autoplay skip costs its artist 3 points for as long as the anchor
  leads, two skips leave the artist out, and the artist's other queued picks go.
  Two autoplay skips in a row clear autoplay's tail (hand-queued songs stay) and
  fill it again.

Replayed offline from the probe (seed 0): The Peace → PinkPantheress, Jane
Remover, slayr, shteppi, Tiffany Day, femtanyl, K/DA, Frost Children, 100 gecs,
Ninajirachi. Daylight → Tom Odell, Lord Huron, Vance Joy, Gigi Perez. HOPE →
Post Malone, NF, Chris Grey, Masked Wolf, Imagine Dragons, Eminem, with Kushner
gone, but YouTube's own mix still carries "7 Years" and "Beautiful Things"
(TODO, "Autoplay ignores how songs sound"). Tests:
`~/mild-lyrics-archive/tests/test_autoplay.py` (fixtures `autoplay_radios.json`,
`ytm_radio_hope.json.gz`).

## 2026-10-22 — "a seek takes a random time to carry on playing": not reproduced yet

Measured silently (own QMediaPlayer, volume 0, app name "mild-seekbench"; In the End,
itag 140): Qt resumes 0.35-0.45s after a seek, even after 20-90s idle. LocalPlayer's
held reading lets go 0.05s after a seek on a local file, 0.10-0.15s on the stream
(the same with a QAudioBufferOutput tap), 0.2s under a full-line download (one
0.95s). Clock over LocalOverlay moves again within one poll (0.25s). A second seek
0.03-0.3s after the first does not stall audio the way it stalls the video player.
A plain one-request download of that stream ran at 32KB/s (googlevideo throttles
after the first burst); Qt's seeks open a fresh range each time and never hit it.

So it lives in the running app: Music video on (Store downloads, audio_map's ffmpeg
on the same song link, the video player's own seek), or something else. LocalPlayer
now logs to follow.log (`who: "local"`): local-seek, local-seek-heard (`after`, and
`why` = moving / gave up / paused), local-status while a seek or stall is open,
local-stall / local-stall-end (`lasted`), local-error.

## 2026-10-22: a bot check no longer skips the whole queue

Bug: nearly every song was skipped for want of audio, songs that do have audio.
follow.log 19:04:39–19:05:25: a new song every 2–3 s. Cause: YouTube answered "Sign in to confirm
you're not a bot" for every video (default, tv, web_music, android_vr, web_embedded clients alike,
so it is the address, not a client; YouTube Music search still answered). `_resolve` swallowed it as
one bad upload and tried up to five more, returned "no copy with the right length", and
`on_resolved` stepped to the next song, which did the same. Each skip asked YouTube about six
more pages, which keeps the flag up.

Now `_audio` shares music_video's `BLOCKED` (30 min, one flag per address): a "not a bot" answer
raises `YouTubeBlocked`, `_resolve` stops at it and returns `blocked`, and the player stays on
the song with "YouTube is asking to confirm this is not a bot; trying again in N min". While
blocked, nothing asks YouTube for a stream. Faked check: the first song sent one request and
the next song none. Cookies (`--cookies-from-browser`) would get past the check, but that signs
the lookups in as their account; not built.

## 2026-10-22 — Time in the editor hands over the stream that is playing

Goal: Time in the editor uses the song already loaded in Mild Lyrics. A song streaming in Mild Lyrics used to go to the editor as `--fetch`. The editor then searched YouTube itself: another lookup counted toward the bot check, and maybe another upload with other timing than the one heard. Now `time_in_editor` takes `LocalPlayer.loaded_url()` (the QMediaPlayer's http(s) source) when the current song is a stream. The work thread saves it whole with `save_stream` into cache/editor beside the TTML, named "Artist - Title" with the extension from the link's `mime`. That needs no YouTube lookup, because the googlevideo link is already signed and is served over IPv6 too. The editor gets `--audio <file>`. A save that fails falls back to `--fetch`, with a note saying why. Paths handed to the editor go through `noconsole.real_path` (Store Python). Test: tests/test_time_in_editor.py (9, a local HTTP server, no YouTube). Not tried on a real googlevideo link: YouTube had flagged IPv4 as well by then.

## 2026-10-23 — Vluchtstrook's Sound Rush Remix: no Spotify id

The song: "Vluchtstrook (feat. Antoon & Sigourney K) (Sound Rush Remix)", Kris Kross Amsterdam, 2:58, ISRC NLS242200081. Traced lookup:
- ListenBrainz and MusicBrainz (name, ISRC) have nothing, and neither does Genius.
- The artist page lists the original "Vluchtstrook" (2:28) as a top track with no duration, so `near()` passed it. `artist_page_spotify` returned the original, `fits_spotify` turned it down, and the step ended there. The remix single (2022) is not among the newest releases the page lists.
- Only Spotify's own search (ISRC or name) can name the remix. Its token is the one kept from the desktop app, and it had run out 110 min earlier (Spotify closed), so `spotify_web_search` returned None. That counted as no trouble, so the song was filed as "not on Spotify", asked again tomorrow.

Fixes:
- `artist_page_spotify` takes a track only of the same version (`versions()`), compares names with Spotify's " - X Remix" form cut (`base`), and sorts releases named like the song first.
- No session is still not trouble: that rule is kept, because without Spotify every unmatched song would be asked every 10–80 min forever. It is now marked instead: `NO_SESSION` in trouble becomes `sp_nosession`, and `sp_due` makes the song due the moment `spotify_session_left() > 60`. That applies to the ISRC search too.

test_spotify_id 35 (4 new checks), test_isrc_match 30. Records made before this have no `sp_nosession`, so their next ask is still "tomorrow".

## 2026-10-23 — Mild Lyrics' sound as an application (Vesktop)

Goal: Mild Lyrics should show up as an audio source in Vesktop (screen-share audio, via venmic). `pactl list sink-inputs` while it played: Vesktop's streams carry application.name, process.binary and process.id (client.api pipewire-pulse). Mild Lyrics' carried only node.name/media.name "Mild Lyrics". Qt 6.10+ plays through PipeWire itself, so the `PULSE_PROP_application.*` set in main() never reach it, and venmic lists sources by application.name.

main() now sets `PIPEWIRE_PROPS` (`pipewire_props`: application.name, icon_name, process.binary "mild-lyrics", process.id). It is set after `offload.warm()`, so the workers do not inherit it. The TTML Editor sets its own ("Mild Lyrics TTML Editor", "ttml-editor") before its QApplication, so one started from the player does not carry the player's name and pid. Checked with a throwaway QAudioSink playing zeros at volume 0: its stream had application.name, icon_name and process.binary, from PIPEWIRE_PROPS. Not checked in Vesktop's picker itself. Does nothing on Windows (no venmic there).

## 2026-10-23 — a typed lyric line leads with its song

Bug: "just stop your cryin' it's a sign of the times..." had Everything Suxxx (Deja the Optimist) as Top result and only song; without the "..." Sign of the Times led. Probed Deezer's /search directly: its parser treats an ellipsis (… or two or more dots) as a word, quotes as a phrase and a lone dash as "not" — each of those returned Everything Suxxx alone (1 result), the bare line returned Harry Styles first. A "?" or "!" or a single trailing dot is harmless. And it matches the words against names only, so "stop your crying baby it's a sign of the times" gets three covers and no Harry Styles.

Two changes. `SS.dz_query` drops quotes, ellipses and lone dashes and straightens curly apostrophes before Deezer is asked (P!nk, AC/DC, a leading -word untouched). `Pages.line_song`: a query of 4+ words whose first In-lyrics hit (saved lyrics, then Genius, top 4 looked at) scores as a line match (`GR.score_song` why "line", ≥ `LINE_LIFT` 0.5) puts that song first in Songs and makes it the Top result — from the catalogue's own rows when it is there, else from a `lookup` of "title artist" (kept a day, so asked once). Not done when a catalogue song is named exactly what was typed. Checked against live Genius + Deezer: the reported line (with and without "..."), the cover-only line → Harry Styles via lookup, "is this the real life…" → Queen, "tell me why ain't nothin' but a heartache" → Backstreet Boys; "in the end linkin park" and "the sound of silence" left alone. Not checked in the window.

## 2026-10-23: Windows streams go through a loopback relay

Reported from the laptop: playback "randomly stops for a second". Its follow.log had `local-error "Demuxing failed"` about every 27s of every song (25-34s after each load), each followed by the refetch and `_switch` of 2026-10-22: the gap heard was that reload. Linux has had a handful of real drops a day.

Measured on the laptop over SSH, same signed links (VISIONOS, itag 140, bound to its IPv6): curl.exe at 20KB/s for 75s, .NET HttpClient read in bursts every 2.5s for 79s, and Gyan's ffmpeg 9.0.1 (`-re`, GnuTLS) for 70s all read through without a cut. Qt's own FFmpeg there is 7.1 (avformat-61) and does HTTPS with SChannel (`Secur32.dll`, "TLS Listen Sockets with SChannel"); Linux's uses OpenSSL. Not proven inside Qt on Windows (Store Python cannot run from SSH), but it is the one reader that differs.

`stream_relay.py`: on Windows (`ON`), `wrap()` gives Qt `http://127.0.0.1:<port>/s/<token>` for an https stream, and the request is made here with urllib (OpenSSL). A body that ends short of its Content-Range/Length is opened again with `Range: bytes=<at>-<end>`, up to `RESUMES` (5) per request, logged as `local relay-resume`; beyond that, or on a refused reopening (`relay-resume-failed`), the connection is closed and Qt's error reaches the old refetch path. A stale link's 403 is passed through the same way. `loaded_url()` unwraps, so the editor's save still gets the real link. Audio now needs Python threads to run: a frozen GUI thread that holds the GIL starves the relay after Qt's ~4s buffer.

Measured here with a real Qt 6.11 QMediaPlayer and a QVideoSink (no sound), against an origin that cuts every connection after a quarter of the file: direct, "Demuxing failed" 74 times and stuck at 4.0s; relayed, 3 resumes, 0 errors, 22s played in 22s; a seek to 30s ran to the end; a real googlevideo link loaded (180.3s), sought to 120s, 0 errors. Not yet heard on Windows.
Tests: test_stream_relay 12 (new), test_local_seek 21 (also with `ON` forced).

## 2026-10-23: "Time in the editor" waited for a throttled download

Bug: the editor takes a while to open after "Time in the editor". When the song plays through Mild Lyrics' own player, `time_in_editor` saves the playing stream (`save_stream`) before it launches the editor, and that took 102s for 3.3MB. googlevideo paces a request with no Range to ~32KB/s, about playback speed. Measured on fresh links: plain 32KB/s on both songs tried; with `Range: bytes=0-<end>` 5.7-8.6MB/s; open-ended `bytes=0-` 0.65s and 1.29s for a whole song. `save_stream` now sends `Range: bytes=0-`: 0.47s. The editor itself was ready 0.5s after it was started (headless, real arguments), and its launcher took 0.3s up to argument parsing, so the download was the whole wait. Music video downloads (`_get`, `_fetch_parts`) already asked by range. Qt's FFmpeg sends `Range: bytes=0-` itself, so playback was never throttled.

## 2026-10-23 — Sources: Spicy listed twice; Use another source's sync

Bug: the Song page's Sources showed "Spicy Lyrics · community — In use" and, under it, "Spicy Lyrics Community — Fetch". When nothing beats Spicy, the walk stores its record with source "" and no doc (Spicy is the lead, its document is not in the walk's record), so `source_rows_for_home` keyed the in-use row "" and listed "spicy" again as not asked. The playing song's in-use row is now keyed by what is on screen (`self.source`, "" read as "spicy"). A song that isn't playing and was left to Spicy still shows no in-use row and Spicy as Fetch, since its record does not say whether Spicy had anything.

Goal: a button to use another provider's sync for a song. A row that is Showing (fetched to compare, with lines) gets a **Use** button beside the badge. It writes `LS.pick_for_song(tid, name)` to `picks.json` in the cache root. `Fetcher._load_words` and `preview_body` ask the picked source alone first (`Fetcher._picked`, through `LS._asks`). If it has nothing now, the usual walk decides. A pick of "spicy" skips the walk after Spicy answers. The playing song reloads (`reset_track(keep=True)`). For any other song, the page's copy is dropped and asked again. Follow-up the same day: every asked row that had word or line timing gets Use as well, without showing it first (an unasked row only once it is Showing with lines). Once a song has a pick, the header reads "your pick · back to auto", which forgets it. The pick ignores the source order, the people lists and sync_off: it is the user's explicit choice for that song. Checked offline with the sockets blocked: rows for the playing song (Spicy once; a pick in use), rows for another song with a pick; `_load_words` with a pick asks only that provider (Spicy not asked), and without one asks Spicy. Not seen in the window.

## 2026-10-23 (later): the stream relay is on everywhere

Reported on Linux: "ministutters" under a second while a song plays. follow.log had 9 `local-error "Demuxing failed"` from 22:39 on, none before. Each was followed by a refetch and `_switch`, which is the gap. Some came 47.6s of song apart (103.9→151.5, 196.5→244.1). This is not the Windows TLS fault. Paced reads (20KB/s) of the playing song's link from this machine, over the same ISP IPv6 the link is bound to: curl was reset by the server 4 times out of 4. One run without Range was cut at 164s and one with `bytes=0-` at 128s. Two side by side were both cut at 144.8s. Python's urllib, reading the same link at the same pace (via stream_relay), got the whole 3.38MB 3 times out of 3, with no resume needed. Why curl and FFmpeg are cut and urllib is not was not found. Either way the relay helps: Qt's connection becomes loopback, and the upstream one is Python's, which resumes with a Range if it is cut (the laptop has logged 3 `relay-resume` rows since the relay went on there). `ON = True` on all platforms. The trade-off from above (audio depends on Python threads once Qt's buffer runs out) now applies to Linux too. test_stream_relay 12/12, test_local_seek 21/21.

## 2026-10-23: the explicit copy before the clean one

Bug: songs sometimes play as their clean version. YouTube Music's song search returns both copies of a release as Art Tracks: same title, same artist, same length. `release_of` ranked them by length and album only, so the clean one often came first. An audit of the last 40 songs played (scratchpad explicit/audit.py) found Did It Again (Lil Tecca) on its clean copy while two explicit ones matched. YouTube Music marks the explicit copy with `MUSIC_EXPLICIT_BADGE`. `_ytm_rows` now reads it as `explicit`, and `release_of` puts the explicit copy first unless the track is the clean edit. Deezer marks that as `explicit_content_lyrics == 3` ("edited"), and `_dz_track` keeps it as `clean`. PICK_V 3→4, so saved picks are made again, and links in stream-urls.json from an older pick are dropped at load. Every song resolves afresh once on its next play. The other fallbacks (local_align.find, yt-dlp search) cannot see the badge and are unchanged. test_release_pick 6/6. Live: Did It Again → McAV_kekygY (explicit), and clean=True → 3d4JYY6kQ-s.

## 2026-10-24 — C U Again took a compilation's Spotify id, and so no community sync

Bug: C U Again (Cartoon, Jéja, Mikk Mäe, Futuristik) played here showed "Apple Music with NetEase and Kuwo"; they suspected Spicy withholding the community sync. Not so: asked once directly, the API gave `aml` Line for 4zsxBgPkUFYEoOGDncGIBd, the id the song was matched to. The community sync (TetoX26, Syllable) is on 5Q9FURN7nsQLKeAqoOrvcA, the 2016-11-15 single credited to all four. 4zsx is the track on NCS: The Best of 2016 (2016-12-16, no Jéja), and it came from `mb_spotify`. Spotify's Web search was refused (429) and ListenBrainz had nothing. MusicBrainz's recording has no Spotify link of its own, so the code tried its first three releases: all three were copies of the compilation, one with Spotify album links. The single is listed fourth and has no Spotify link in MusicBrainz at all.

`mb_spotify` now looks through the song's own releases only (official first, then oldest). Compilations are asked last, as a step of their own (`musicbrainz-compilation`, after Genius), so a song MusicBrainz links only through a compilation still gets that id. With it, the artist-page step finds 5Q9F for this song. Already-matched songs keep their kept id (`spotify-ids.json`; this one under two song keys). The running player holds that map in memory and rewrites the whole file, so those entries can only be dropped while it is closed. `mb_isrc_spotify` still takes the first link. (This once said it was a decision of 10-23; no such decision was made, 10-24.)

## 2026-10-24 — Notion (The Rare Occasions) took Viral Rock Hits' Spotify id

Bug: Notion was linked to a Various Artists album. Its ISRC (USHM21617726) is in MusicBrainz, and the recording's only Spotify link is 04MLXFyTp6NsKESPeVIMHp. That is the track on Viral Rock Hits (2023, X5). `mb_isrc_spotify` returned it as the first step, and nothing after it was asked. The ISRC is right: a compilation's copy carries the artist's ISRC, under another track id.

Spotify's public track page names the album with its type (`albumOfTrack.type == "COMPILATION"`; the embed page does not). `on_compilation` reads it. `spotify_id` (and `spotify_by_isrc`) now hold a compilation's copy as a spare while the steps after it look for the artist's own release. The spare is the answer only when none is found. `mb_isrc_spotify` itself is unchanged: it still takes the first link, and its answer is checked.

ListenBrainz then gave ten ids in no useful order: the "Notion (Acoustic)" single's copy of the original, two TikTok compilations, …, and the "Notion" single ninth. `by_lb` now reads up to ten on the track page. It takes the first on the song's own album (`norm` and `versions` both equal, so "(Acoustic)" is not "Notion"), else the first not on a compilation. Live: Notion → 0sTlGEld0h8kIPZaKDYUf4 (the Notion single). A re-run of 18 saved songs found 4 more on compilations: Miserable Man, Mask Off, Tunnel Vision, The Fire. All four now land on their own albums. Dusk Till Dawn moved from its single to Icarus Falls (the same Radio Edit, the album Apple names). The other 13 were unchanged.

Saved ids: SP_V 2→3. A found id is checked once, on the track page, the next time its song comes up. Only a compilation's copy is looked up again. The old id goes in `sp_was`. A queue item still carrying it takes the new one in `_resolve`, and `look_spotify` treats an item id equal to the kept id as its own copy, not the catalogue's. test_spotify_id 37 ok / 5 failed. The 5 are older reds: its `mb_spotify` stubs predate the `compilations=` step. That test had also been writing to the real spotify-ids.json ("Corridor" → "SLOWID", now removed); it uses a temp file now.

Then Counting Stars (OneRepublic) was still on Party Until The End (3W5EcY5IXpUaBkHo4N8hvA, a compilation), with the player restarted on the new code. Its stream link was still live (5.5h left). On that path `_load` asked for an id only when neither the item nor the link had one, so the check never ran. Separately, every reader of a playing song's id took the item's own copy first (`t.get("spotify") or resolver.spotify_of(t)`). `_take` had copied the old id onto the queue item, so a replaced id would never have been read. Now `_load` calls `look_spotify` on every kept link; it returns at once when nothing is due. `spotify_of` is the one place an id is read: the item's own id, unless it equals the `sp_was` id this lookup replaced. local_player's reading(), home_page's track_kind and radio, and local_ahead all go through it. On a scratch resolver with the real queue item: Counting Stars → 2tpWsVSb9UEmDRxAl1zhX1 (Native), read as such from the item, whose field still holds the old id. test_local_seek 21/21, test_autoplay 38/38, test_home_page 186/186; the listen-along tests skip (no local Worker).

## 2026-10-24 — "No album called Oxymoron (Deluxe Version) in the catalogue"

An album page opened by name (from the play log, or Spotify's while it is away) searched the catalogue with the full name and artist. Deezer matches every word, and it calls the edition "Oxymoron (Deluxe)", so "Version" left nothing. The page now asks with the brackets stripped ("Oxymoron ScHoolboy Q"). Of the albums with that name it takes the artist's, then the same edition words (`edition_words`: bracket words less version/edition/the), then the most of them in common. Checked live: Oxymoron (Deluxe Version) → Oxymoron (Deluxe); Oxymoron → Oxymoron; good kid, m.A.A.d city (Deluxe) and Hybrid Theory (Bonus Edition) → their own editions, not the plain or 20th-anniversary ones.

## 2026-10-24 — autoplay keeps a song from coming in much quieter than the one before

This follows from TODO "Autoplay ignores how songs sound". First, it was measured on plays.jsonl, read-only, plus Deezer lookups: 227 autoplay plays straight after another song, 68 of them skipped. Skips were shuffled within each anchor's run, because the anchor decides most of it (Riot 0/36 skipped, Demons 13/31). Songs with no genre in common with the song before: 16/43 skipped, p 0.51. No genre in common with the anchor: p 0.82. BPM 15+ apart: 3/12, p 0.47, and Deezer gives a BPM for only 74 of 177 songs. 2dB+ quieter than the song before: 13/23 skipped against 9.1 expected, p 0.04. Getting louder made no difference. Switching into rap from something else: 6/7, p 0.009, too few to build on. That was seven tests, so the p-values are weak. Deezer's `gain` reads as loudness in dB (Revenge −16, "Let's Get Weird" −4). That reading is inferred from the songs; Deezer doesn't document it.

So there is no genre penalty. Instead `AP.smooth` reorders autoplay's songs still to come. Each place takes, of the next `SMOOTH_SPAN` (6), the song with the lowest cost. The cost is how early the song would come against pick's order, plus `DROP_STEP` (6) per dB it is quieter than the song before beyond `DROP_FREE` (2dB). That penalty is capped at `SMOOTH_SPAN`, so a quiet song waits at most that many places instead of sinking to the end. Unknown loudness costs nothing, so with none known the order is pick's. It never puts the same artist twice in a row. `Home.auto_smooth` runs it on each run of `_auto` songs after the one playing, sorted by `_ord` (numbered as they arrive, left out of player.json). Each pass therefore starts from pick's order and lands on the same result. Songs queued by hand never move. It runs after a fill, after "Make a queue", on every song change (`near_end`), and 0.4s after loudness lands. Listeners in listen-along are left alone.

Loudness: `SS.Loudness` (cache/loudness.json, kept for good; a miss is asked again after 30 days, an unreachable Deezer not kept). It calls `SS.dz_gain`, which is the only ask that carries `gain`, since radio, top and search rows don't: /track/<id> for a Deezer song, /track/isrc:<isrc>, else one search by name and first artist with the same cut to `DURATION_SLACK`. That is one or two asks per song, under the shared Deezer pace. Nothing waits for it.

Replayed on the 29 autoplay runs in plays.jsonl with the session's Deezer data (scratch, not kept). DROP_STEP 1.5 took the 23 drops of 2dB+ to 20; 6 took them to 15, and the skipped songs that came in on a drop from 13 to 8, with 84 of 254 songs moving, at most 5 places. A wider span barely helped (10: 14 drops). A third of transitions have a song Deezer lacks, which bounds it. Next: measure again from plays.jsonl after a week of listening. Tests: test_autoplay "loudness order", "Deezer's loudness" (59/59). test_home_page 194/194.

## 2026-10-24 — a new song starting where the last one was

Bug: a song sometimes starts more than halfway through, "literally instantly". follow.log: 03:48:07, 17:56:45, 18:30:43, 18:31:19. Each time the song changed, `local-error` "Could not open file" came 0.25s later with `pos` = the previous song's last place, and then `local-seek` to that same place at LoadedMedia (`to` == `was`: 199.773, 228.146, 187.508, 188.245). The new song's kept link had gone stale. `_error` fetched a fresh one, and `_switch` resumed it from `_heard`, which the new song had never moved off the old song's position.

Now `_load`, on a new song (not a reload of the same one), clears `_heard`, `_resume_at` and `_seek`, and resets `_snap` to (0, now, paused, length 0). A restored queue still resumes, because `start_cued` sets `_resume_at` after `_load`. This also fixes the play log and the clock taking the previous song's length until Qt reports the new one (FEAR logged as 129.8s, Story of a Warrior's length). Silent repro (two silent files, the kept link failing before any play, the fresh one landing at once): B went to 20.0, A's end, before the fix, and to 0.0 after. test_local_seek 21, test_home_page 194, test_autoplay 59.

## 2026-10-24 — Volume: the bar is the desktop mixer's per-app volume

Bug: everything above 5–10% on the bar was loud. Qt's `QAudioOutput.setVolume` is a plain amplitude, so 10% was −20dB and 50% only −6dB. The saved volume was 0.023 (−33dB). They also asked for the bar to use the system's per-app volume, the one KDE's applet shows, as Spotify's does.

On Linux with `pactl`, `mixer_volume.StreamVolume` sets this process's sink-inputs (`application.process.id`, set through PIPEWIRE_PROPS) to the bar's value as mixer percent. The mixer's scale is cubic. Once one stream holds it (`placed`), Qt's own gain stays at 1. A `pactl subscribe` thread re-applies the volume to each new stream of ours. It also reads a `change` on ours that came more than `QUIET` (0.4s) after our own set, and moves the bar (`heard` → `LocalPlayer._mixer_moved`). Sets go through one worker, with the latest value winning, at most one every 30ms. Without a mixer (Windows, macOS, no pactl), or until the first stream is found, Qt's gain is `MV.gain(v)` = v³, the same curve. player.json now carries `volume_scale: "cubic"`. An older file's amplitude is converted with v^(1/3) to the same loudness, so 0.023 becomes 28%. WirePlumber's stream-restore remembers the last value against "Mild Lyrics", which matches what we save.

Tested on my own silent stream under another name (state.restore-props=false), never theirs: set 0.3 → 30% in pactl. A five-step drag landed on 52%. An outside `set-sink-input-volume 20%` → heard 0.2, and `reading()["volume"]` 0.2. Qt gain 1.0. The subscribe process is gone after exit. test_local_seek 21/21. Windows per-app (WASAPI session) volume is not done; there it is the cubic gain.

## 2026-10-25 — autoplay wandered off the song you chose

Bug: K-pop mixed into other music, and ADÉLA, who never comes up on Spotify. In player.json the anchor was underscores "Do It", followed by 87 autoplay songs. It went hyperpop → LE SSERAFIM/ILLIT/KATSEYE → The Weeknd → Post Malone, Metro Boomin and A Boogie. Only 6 of the first 70 picks are in the anchor's YouTube Music radio as it reads today (49 songs, 48 of them unplayed). One ADÉLA song ("SexOnTheBeat") is in that radio, so one ADÉLA song is a fair pick for this anchor. The run of girl groups is not.

The run drifted step by step for two reasons. Each top-up was seeded by the anchor plus the two newest songs heard, and those songs were heard because they had been picked, so it was a random walk. Fusion also ranked songs that were already played or queued, so the anchor's lists only had their tail ranks left (1/(8+20) against a fresh seed's 0.5/8), and the newest seeds won.

Now:
- `fuse(..., drop=)` leaves out what pick would refuse anyway (heard titles, songs in the last 300 plays) before ranking. What the anchor's lists still hold keeps their top ranks.
- `auto_candidates` tags each song `_hop`: 1 for the first seed's lists (YouTube Music, Spotify, Deezer artist radio and related artists), 2 for a later seed's. Fusion keeps the smaller value. The tag is saved with the queue.
- `auto_seeds` lets a heard song seed only when `_hop <= AP.SEED_HOPS` (1). Songs with no `_hop`, which is everything queued before this, don't seed. So the run stays within two steps of the song you chose.

When the anchor's lists run out, the run ends with "found no songs like this one" rather than wandering further. YouTube Music re-asks after 30 minutes and gives a different mix. Tests: test_autoplay "fusion" and "seeds" (65/65), test_home_page 194, test_local_seek 21.

## 2026-10-25 — "Of Mice & Men" became the band MEN

Their queue after Of Mice & Men "Second & Sebring": songs 16–32 were metalcore, but 1–15 were French electro (JD Samson & MEN, Midnight Juggernauts, Chateau Marmont). `dz_artist_of` tries the credited names, then the credit cut at every joiner ("Of Mice & Men", "Of Mice", "Men"). All three were asked at once, and the loop took the first name that had answered with a match. "Men" (Deezer's MEN, 839 fans) answered before "Of Mice & Men" (180k), so autoplay got MEN's Deezer artist radio as an anchor list. Now it waits on each name in order, and only moves to the pieces once the whole name has answered with no artist by that name. Joint credits ("Jennifer Lopez & David Guetta") still fall through to the pieces. test_home_page: "one band with '&' in its name".

test_home_page reads the live session bus (the running app's MPRIS), so "a click on the song playing" fails while they are playing. Run it with `env -u DBUS_SESSION_BUS_ADDRESS`: 197/197.

## 2026-10-25 — artist Top songs: YouTube Music's order and plays

Bug: the artist page's Top songs made no sense next to Spotify's Popular. Deezer's /artist/top put the new single "Back To Me" first and left out Second & Sebring, and Deezer has no play counts (its `rank` is a score). They chose YouTube Music's counts over Last.fm's scrobbles (exact, but about 40× smaller) and over order only.

`SS.yt_artist_top(name)` does an artist search (filter `YTM_ARTISTS`) and takes the hit spelt `name` (norm), else nothing. It browses the artist page's "Top songs" shelf (five songs with "35M plays"), then the shelf's playlist (bottomEndpoint) for the order past them, each song's plays and its length. Art Tracks only, up to 20 songs. That is three asks per artist through `SS.YouTube.artist_top`, kept a day. `Pages.artist_tops` puts YouTube's order first, using the catalogue's copy of a song when it has one (art, lyrics, tid) with `plays_text` added, then the catalogue's other top songs. The table's extra column (`PLAYS`, `_x`) shows the count. The right-hand column is still your plays, else the length. The lookup uses the catalogue's name, not the spelling shown on screen ("LINKIN PARK" from the player's credits missed the fixture). For Of Mice & Men: Second & Sebring 35M, Would You Still Be There 29M, Bones Exposed 29M, Feels Like Forever 20M. That is Spotify's order apart from Obsolete. Narrow layouts (S/XS) drop extra columns, so no count is shown there.

The artist page's "Top songs" heading (with a › after it, underlined on hover; hit `top_songs`) opens page `artist_top`: Play, Shuffle, and all of `artist_tops` (up to 20 from YouTube Music, then the catalogue's own) with PLAYS and ALBUM columns. Decided: that page is sorted by plays, most first (stable, so YouTube's order breaks ties between rounded counts; songs without a count last). The artist page keeps YouTube's order, which weights recent listening as Spotify's Popular does. `want_page` loads the artist for it as it does for `artist`. test_home_page 199/199 (bus cut).

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/home_page.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The 1.2.0 home page: a sidebar library, search, pages for songs, albums,
> artists and playlists, the local player, stats, the mini player and the
> first-run setup -- all painted by hand like the rest of the window.
>
> The window keeps `view == "browse"` for all of it and hands paint and input
> here (LyricsView.home). The pages themselves are in home_pages.py.
> Notes: docs/notes/mild-lyrics/home_page.md.

## 2026-10-25 — charts without Spotify: Deezer per country, Shazam for Viral 50

Reported: Viral 50 and Your country did not work without Spotify. Without it, the page showed Deezer's global chart only, with no filters. Now `SS.Deezer.chart_uri` maps all three, and `dz_playlist` resolves the special ids:
- "Global" → `deezer:playlist:chart` (Deezer /chart/0, as before).
- "Your country" → `deezer:playlist:country`. The country comes from Deezer's `/infos` (country_iso/country, no account). It then loads the "Top <Country>" playlist kept by the "Deezer Charts" account, matched by exact title and owner, since fans name playlists the same ("Top France"). A country with none gets the global chart, and `sub` says so.
- "Viral 50" → `deezer:playlist:viral` = `sz_rising`: Shazam's Discovery chart for the country, `https://www.shazam.com/services/charts/csv/discovery/<country-slug>/` (CSV rank,artist,title, songs rising by lookups over 7 days, no key). There is no global discovery chart (404), so it is per country. Some countries list only 10. Each song becomes Deezer's copy through `_dz_song`: one search, first artist, norm title, and no OTHER_CUT word the chart's title lacks ("Shotta's (Remix)" came first for "Shotta's."). Songs Deezer lacks are left out and counted in `sub`. A missing chart raises, so the page says it could not be loaded rather than keeping an empty chart.
Shazam chosen (a new outside service, approved 2026-10-25) over hiding Viral 50 or using a Deezer editor's playlist. The filters now show without Spotify, the page subtitle is the chart's own `sub`, and the home shelf names Deezer or Shazam. Kept an hour like the other charts. Live 2026-10-25: the country chart loaded 100 songs; Shazam rising found 9 of 10. Tests: test_charts 6/6.

## 2026-10-25 — a click in the toolbar's empty space went to the song under it

Page content is painted clipped to `self.content`, but its hit rects were not clipped. A tile scrolled up under the toolbar took clicks in the toolbar's gaps. `Home.paint` now clips the page's hits and drops to `self.content` right after painting the page. The side bar, toolbar, bar and popovers are added after that and are unaffected. test_home_page "page hits stay inside the page" (201/201, bus cut).

## 2026-10-27 — autoplay from "CAN'T STOP THE FEELING!" played children's songs

After "CAN'T STOP THE FEELING!" (Justin Timberlake, the Trolls cut) autoplay queued KIDZ BOP, The Wiggles, Mini Pop Kids and Disney covers. All of it was hop 1, from the anchor's own lists. YouTube Music's radio for the song's Art Track (`6p3E7OMw52g`) was 48 rows of children's music. Co-listening on that upload comes from the film's audience. The radio of the song's official video (`ru0K8uYEZWw`) was ordinary pop: P!nk, Ed Sheeran, Maroon 5, Mark Ronson.

Measured on eight anchors (HOPE, Black Parade, As It Was, Dreamflasher, Do It, Cake By The Ocean, Second & Sebring, this one): the rows of each YouTube Music radio whose first artist is in the anchor artist's Deezer radio. Art Track and video radio alike gave 12–25 of 49. Only this Art Track's gave 1, against 11 for its video's. The five probe seeds in test_autoplay's fixtures give 12–30.

Now:
- `AP.stray(radio, artist_radio)`: fewer than `AGREE_MIN` (5) rows by the artist radio's artists, with both lists at least `AGREE_ROWS` (20) long.
- In `auto_candidates`, when the anchor's radio is stray, its weight drops to `STRAY_W` (0.25). The song's official video is looked up (`SS.yt_video_of`, YouTube Music's video search: an OMV credited to the first artist whose cleaned title is the song's, kept a day), and its radio joins at weight 1.0. With no video, the Art Track's radio stays behind Deezer's.
- `yt_radio(vid, clean)` keeps official videos as the song they are of (cleaned by `song_of_video`), with no video id and no length, so the resolver finds the Art Track by name. A video's radio is all videos and an Art Track's all Art Tracks, so Art Track radios are unchanged. Before this, the radio of a song played from a pasted music video came back empty.

Replayed offline on the saved answers: the first 25 picks are the video radio's pop with Deezer's Timberlake radio (Rihanna, Craig David), and none of the children's list. Tests: test_autoplay "another audience's radio" and the video radio fixture (77/77), test_home_page 201/201.

## 2026-10-27 — an album opened by name stayed on "Loading…"

Albums with no catalogue link to read open by name: a song's album from the play log, or a Spotify album while Spotify is away. Measured on the real window offscreen, scratch config with a copy of the play log, only api.deezer.com reachable:
- **The album was never asked for.** `by_name("album")` and `page_album` each looked the album up, in a different word order (6 Deezer requests instead of 3). `by_name` answered first and swapped in Deezer's link without asking for the album. `page_album`'s lookup, which does ask, then saw a Deezer link and skipped. Nothing asked again until the next `want_page` (a page change). Discovery from a Spotify link was still on "Loading…" 17s after opening.
- **The lookup waited behind the home page.** `lookup` appended to the page source's queue, behind about 20 artist asks the home page makes for its mixes: 5.4s.

Now `by_name` only clears a Spotify artist's link. `page_album` does the one lookup, and it also keeps a Spotify album that is still held. Page lookups pass `first=True` (`Deezer.lookup`, `Spot.lookup`), and `Spot.want(first=True)` moves a key that is already queued to the front. Same run: Discovery from a Spotify link loads 0.65s after opening while the home page is busy, and Hybrid Theory with no link 0.4s.

The home page's opening burst also reached Deezer's quota (next section). Tests: test_home_page "an album known by a Spotify link…", "a page waiting on a queued ask…" (204/204).

## 2026-10-27 — the page you look at no longer waits on the home page's Deezer asks

The home page's suggestions open 12 Deezer artist pages (4 asks each) and 5 name searches (3 each): 63 asks in about 5s against `DZ_PACE` (40 in 5s). Every Deezer ask then waited, a page's included. Two changes:
- **Lanes.** A thread-local `_lane.bg` marks background asks. `_dz_pace` stops them at `DZ_BG` (30), leaving 10 per 5s for pages. `Deezer.want` puts any ask not made `first` in the background lane (suggestions, mixes, autoplay, feed and charts, non-page lookups). `_laned` carries the lane into `dz_search`'s, `dz_artist`'s and the Shazam chart's pool threads. Loudness, artist pictures and the resolver's look-ahead are background; the song asked to play is not. Suggestion and mix artist pages now ask with `artist(uri, first=False)`.
- **A reader for pages.** Each Spot read its queue on one thread, so a background ask sleeping for its share held up the page ask queued behind it (the album came 1.4–1.6s after opening instead of 1.0s). Deezer sources (`PAGE_READER`) now have a second reader that takes only keys asked with `first`. `want(first=True)` on a key that is already queued marks it for that reader and replaces its ask with the page's.

Measured (real window offscreen, play log copy, only api.deezer.com, album opened 5.5s after the home page and an artist page 0.5s later, at the height of the burst; five runs new and four old): the album 0.13–0.14s after asking (old 0.63–1.05s), the artist page 0.23–0.30s (old 0.30–0.71s). Page asks never waited on the quota (old: up to 0.57s). The cost is that the home page's suggestions finish filling at 11.6s instead of 7.9s. Tests: test_home_page "Deezer's quota…", "a page's ask is read while a background one is stuck" (208/208).

## Relay: a paused player's unsent bytes — 2026-10-27

Upstream is often faster than playback, so the relay handed a whole song to the kernel and closed
its end. The closed socket's unsent bytes then waited on a paused Qt; after about 6 minutes without
reads the kernel dropped the orphan with a reset. Measured through the relay on a live link: pauses
of 1, 3 and 5 minutes read whole, 7 and 10 minutes lost the last 570KB of 2.6MB. In the player that
was "Demuxing failed" a few seconds after resuming, from what Qt had buffered.

`_Handler._linger` now holds a fully sent body open, half-closed (SHUT_WR), until the player hangs
up, for up to `LINGER`. An 8-minute pause read whole after the change.

## 2026-10-28 — the queue emptied after two quick skips

Seen in follow.log and plays.jsonl. A queue of autoplay songs was clicked through:
Haru wo Tsugeru after 5 s, then 青のすみか, which hit "Could not open file" at 0:00
and was left after 15 s. The Tracker counted those 15 s as heard, because it counted
time while the status said Playing, so the song was logged as a second skip. Two skips in
a row dropped autoplay's whole run before the rebuild had picked anything. The rebuild
found nothing new, so the queue sat empty with no "finding" header. Next on the
last song then stopped it, which rewound it to 0:00.

- `Tracker.observe` counts seconds only while the position moves forward. A song stuck
  loading writes no row (under 5 s), so it is not a skip.
- Two skips set `auto_rebuild` instead of emptying the run. `autoplay_fill` then counts
  only hand-queued songs as ahead, leaves out the old run's songs (they are in the
  queue), and `replace_after(hand + new)` once picks land. If none come, the old run
  plays on. With TOP_UP_BELOW or more hand-queued songs it still just drops the run.
- Next on the last song while `can_grow()` (autoplay on, not listening along) keeps the
  song playing, sets `wants_next`, and emits `ran_out`. `resume_after_end` moves on
  when songs land. `wants_next` counts as urgent in `autoplay_fill`, as `ended` does,
  so it fills without waiting for every source.

Why that rebuild came back empty is not known: the candidates lived only in memory.
