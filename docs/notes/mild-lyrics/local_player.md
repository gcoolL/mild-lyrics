# `mild-lyrics/local_player.py`

## 2026-10-27 — songs listed twice on Windows

Bug: "On this computer" showed some songs twice on Windows (not real
duplicate files). The scan walked each chosen folder on its own and keyed
rows by the path as spelled, so overlapping entries listed every file twice:
the folder picker's `C:/…` beside `C:\…`, a case difference, a folder and
one inside it, or a junction into a folder already walked. The cache kept
every spelling, so the list from it at startup doubled too. Now the walk
skips any directory whose `realpath` (normcased) it has already walked,
`set_dirs` keeps one row per `_norm` path, and `_inside` needs a separator
after the folder (`D:\Music2` is not inside `D:\Music`). Fixed without
seeing the Windows laptop's folder list (unreachable that night); tested
with overlapping, re-spelled and symlinked folders here.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/local_player.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Songs on this computer, played by Mild Lyrics itself.
>
> LocalLibrary scans the chosen folders (tags through mutagen when it is
> installed, the file name when it is not); LocalPlayer plays them with
> QtMultimedia; LocalOverlay puts it in front of the usual transport, so the
> clock follows it like any other player while it is the one in use.
> Notes: docs/notes/mild-lyrics/home_page.md.

## 2026-10-30 — following the default audio output

A Windows report: one song played with the video and lyrics moving and no
sound. `QAudioOutput` is made on the default device of the moment and stays
there, so a default switch (headset, Bluetooth, HDMI) leaves Mild Lyrics
playing to a device nobody hears until a restart. `_make` now holds a
`QMediaDevices` (held so its signal is not lost), and `_outputs_changed` moves
the output onto the new default and writes `local-output`. A song that has
buffered with no audio track writes `local-silent`. Untested on Windows. Here
the null device maps to the default, so only the no-change path ran.

## 2026-10-30 — one track id per play, where the window had its own

A stream that starts before its Spotify id is found is reported under its name
key (`_key`). When the resolver's id turned up 75 seconds into
M@GICAL CURE! LOVE SHOT!, the tid changed, the window reloaded the song
(`reset_track(keep=True)`), and the new id (the 2026 album copy) had only
Apple's line sync on Spicy Lyrics. The first load had used the window's own
find (`_spotify_id`, the 2024 single), which held the community sync.

That late switch is also how a song with no id at load gets Spicy at all
(3 of the 6 in a day of follow.log went lrcmodel → `spl` that way), so it is
not dropped. `reading` holds the first id (`_tid_held`, the item object, by
`is`) only where `LS.spotify_id_known(<name key>)` names a different id: the
window asked Spicy with one already. `keep_for_lyrics` no longer overwrites
that entry, except where it holds the resolver's own previous id. A new item
in `_load` clears the hold, so the next play takes the resolver's id.

## 2026-11-02 — Identify songs (`local_identify.py`)

Settings ▸ Home ▸ Your files ▸ Identify songs (`home_identify`, off by default).
When it is on, each file is matched to a released song on Deezer, and the file is
listed, played and fetched for as that song.

- **What is asked.** The file's tags if it has a title and artist of its own;
  otherwise its file name with downloader noise removed (`[11-char id]`,
  `(Official …)`, `(Lyrics …)`, `[HQ]`, a leading track number) and split on
  " - " by the window's video cleaner. One Deezer search per file.
- **What counts as a match (`pick`).** With an artist: the same normalised title,
  the artist contained either way, and the same version words (`SS.versions`).
  From a bare name: the row's title and artist both appear inside the name. The
  length must be within `DURATION_SLACK` (3s). A bare name with no length is
  never taken.
- **What changes.** `LocalLibrary.relist` runs the scanned rows through
  `Identifier.overlay`. That makes a copy with Deezer's title, artist and album,
  its ISRC, a tid from those names (`_key`), and Deezer's cover where the file
  has no embedded picture. A folder picture or a yt-dlp thumbnail is replaced.
  The file's own row stays under `_file`, so turning the setting off shows the
  file as it was. `local.json` never holds the catalogue's answers.
- **Lyrics.** `LocalPlayer.reading` reads the overlay copy, so the window
  fetches by the identified name and tid. The Spotify id comes the usual way:
  the window's own `_spotify_id`, and the resolver's `look_spotify` with the
  ISRC, for the song playing once it is identified and for the next ones
  through `_prefetch_quiet`. While a played file is first being identified,
  `reading` gives no tid for up to `IDENT_WAIT` (4s). This avoids reloading
  the lyrics a second later under another id, the same reasoning as an
  unresolved stream.
- **When it asks.** Played files and the next one go urgent (foreground
  Deezer lane). The whole library is walked in the background lane, one ask
  per `WALK_GAP` (1s), after each scan and when the setting is turned on.
  Answers are kept in `cache/local-ids.json` by path and mtime. A miss is
  asked again after 7 days. A failed ask (offline, quota) is not kept.
- **Plays.** An identified file has a new tid, so its plays before the
  setting was turned on stay under the tags' tid.
- **Live check, 2026-11-02.** Typical downloaded names, one search each:
  4/5 found with album, cover and ISRC ("Artist - Title (Official Video)
  [id]", a numbered name, plain tags, "(Lyrics)"). `track01.mp3` has nothing
  to go on by name. A file like that needs an audio fingerprint, which was
  not built.
- Tests: scratchpad `t_ident.py`, 20 checks, Deezer faked and sockets
  blocked. `test_home_page` gives 173 ok / 2 failed, the same two with and
  without this change.
- **Length slack, later 2026-11-02.** A downloaded "Metro Boomin - Space
  Cadet feat. Gunna.mp3" is 214.3s; Deezer's Space Cadet is 205s, so the
  3s `DURATION_SLACK` threw the right row away (found through the MusicBee
  plugin, which uses the same `pick`). With an artist and an exact title, a
  file may now be off by `NAMED_SLACK` (15s) or `NAMED_SLACK_SHARE` (8% of
  its length), whichever is more. Version words still have to agree, the
  closest length still wins, and a bare name with no artist keeps 3s.
  Misses are kept with `v`; those from before (`PICK_V` 2) are asked again.
  Five downloaded files on the Windows laptop: 5/5 now, 4/5 before.
  Test: `test_identify_pick.py` (8, no network).
