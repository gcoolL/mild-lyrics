# The Android port: what is left

The plan the port was built from is finished down to the viewer, the sources,
the clock, the renderers and a working built-in player. This is the rest of it:
the player as it ought to be, the editor, and the debts and extras around them.

Nothing here is a rewrite of the original plan. It is what that plan has not
reached yet, written down while the reasons are still in hand, plus everything
learned since that changes what the remaining work should be.

Line numbers are the desktop's at the time of writing and drift like every
other citation in this folder; the enclosing name is the durable part.

---

## Where the port stands

| module | state |
| --- | --- |
| `core/document` | done — parse, render, ZWSP, model, goldened against 84 TTMLs |
| `core/syllables` | done but for `syllabify`, so `timeline(split=)` only takes `"none"` |
| `core/clock` | done — slew, jump, stale hold, unpause bias, `song_key`, video unpacking |
| `core/sources` | nine providers, five blends, the shaping passes, the on-disk cache; debts below |
| `core/render` | all seven renderers, springs, emphasis, glow, blur |
| `media` | session reading, notification listener, song vetting, player picking |
| `feature/viewer` | header, backgrounds, gestures, settings, empty states |
| `player` | library, ExoPlayer + session, radio with every term, queue, transport, streaming seam |
| `feature/editor` | **empty** — a directory with a `src/main/kotlin` and nothing in it |
| `app` | shell, navigation, permissions, the lyric cache |

Two verification facts worth keeping beside that table: every JVM suite passes,
and the whole of it has only ever been run on an emulator. No hardware has
opened this app except gc's phone, and that only from an installed APK.

---

## 1. The player, as an actual player

What exists is a player in the sense that it plays: a flat list of every track
on the phone, four ways to start it, a radio that keeps going, a queue you can
reorder, and a transport. What it is not yet is something to browse.

**Browsing.** `MediaStore.Audio` already answers albums, artists, genres and
playlists; `Library.tracks()` reads the tracks table and nothing else. The
work is four more queries and the screens to show them:

- albums, as a grid of covers (`albumart` content URIs, 160 px thumbs — the
  artwork budget in the plan's §7 stands: nothing above 640 px on a phone)
- artists, and an artist page that is their albums then their loose tracks
- genres and playlists, which are a join away and are what most phones
  actually have in them
- a search over all of it, because a library of four thousand tracks is not a
  list you scroll

**A now-playing screen.** The viewer IS the now-playing screen for whatever is
playing, which is the point of the app — but there is nowhere to see the
artwork large, scrub with a thumb on a real bar, or reach shuffle and repeat.
The desktop has no equivalent to port from: it follows a player, it is not one.
So this is design work, and the shape that fits is Apple Music's: the cover
big, the transport under it, a swipe up for the queue, a swipe down for the
lyrics. `queue.player` already exposes everything it needs.

**Shuffle and repeat** are `Player.setShuffleModeEnabled` and
`setRepeatMode` — two lines each, and nowhere to put them yet.

**A browse tree.** `MildPlayer` extends `MediaSessionService`, which publishes
a session and nothing else. Android Auto, Wear and "play my music" from
Assistant want a `MediaLibraryService` with `onGetLibraryRoot` and
`onGetChildren` — the browsing above, expressed once more as `MediaItem`s. The
change of base class is small; the tree is the work.

**Downloads.** The plan wants `Music/Mild Lyrics` for anything fetched, with a
cap the reader sets (2 GB by default, replacing the desktop's `AUDIO_CAP_GB =
8.0`). Media3's `DownloadManager` does the work; what has to be written is the
policy and the screen that shows what is held.

**The radio's remaining term.** Every term in the plan's list is in, including
the audio-feature proximity the `Feel` measurements feed. What is not there is
a way to SEE why a track was chosen — a line under the queue row saying "same
tempo, and you always play it after this one" would make the radio arguable
instead of magic. `Radio.score` computes every term in one place and returns
only the sum, so what it costs is a second return type.

**Streaming past the library** works and is off by default. What is missing
around it: a search screen that reaches the streamer (the interface has
`search` and nothing calls it), and caching of what has been streamed so a
track that came from the network twice does not cost the network twice.

---

## 2. The editor

This is the largest remaining piece and the most mechanical: `editor/model.py`
(457 lines) and `editor/ops.py` (2059 lines, 76 functions) are Qt-free,
network-free pure data work, and everything in them is goldenable the same way
`core/document` was.

**Order, because the middle of this is where the risk is:**

1. **`model.py` → `core/document`.** Most of it is already there — `Syl`,
   `Group`, `Line`, `Doc`, `fromBody`, `toBody`, `words()` — because the viewer
   needed it. What is not: `from_text :360`, `as_text :389`, `timed_only :328`,
   `_peel_backing :405`. Half a day.

2. **`ops.py`.** All 76, ported as pure functions returning the same `String?`
   "what happened" or null, because that return value IS the undo protocol:
   `do(said)` at `app.py:1646` pops the entry it just pushed when a function
   answers null. Port them in the desktop's own order and golden each one
   against the corpus — the desktop can be driven to dump before/after
   documents for every op the same way `dump_goldens.py` already dumps passes.
   The ones with teeth: `sweep :733` and `untime :763` (drag sync's own two),
   `split_everywhere :98`, `syllabify :156`, `snap_line_ends :861`,
   `move_backing :998` and the four ad-lib movers after it.

3. **Undo.** Snapshot-based, not command-based: `push_undo :1671` keeps 80 deep
   copies (`del self._undo[:-80]`) and `do :1646` is the one funnel. On a phone
   80 copies of a 300-line document is a few megabytes — measure it, and if it
   bites, keep the same 80 but store `toBody` JSON rather than object graphs.

4. **The line list.** `lineview.py` is 1301 lines of Qt item view; on Android it
   is a `LazyColumn` with selection, tap-to-arm, long-press-drag to reorder.
   What must come over is the SELECTION MODEL — multi-select across lines and
   backing rows, because a third of the ops take `picks` rather than an index.

5. **Drag sync, which is the point.** `syncbar.py` is the most port-ready file
   in the project and its own docstring is a mobile argument written before the
   fact: timing on the word chips themselves failed because *"'cannot' is
   eighty pixels and 'I' is eighteen — and the syllables you most need to place
   accurately are, without fail, the short ones."* Hence one equal-width slice
   per syllable. Port whole: `_share :82`, `cell_at :309` (the gap between two
   slices belongs to the slice AFTER it, so a drag can never stall), the
   wrapped-row band resolution, and the four-signal protocol
   `begin/moved/done/cancelled` on a widget that knows nothing about audio.
   Then the window half: `_sweep_ok :851`, `_sweep_begin :892`, `_sweep_to
   :907`, `_sweep_done :925`, `_sweep_cancelled :937`, and `advance_drag :946`
   — the row-to-row automaton that makes drag sync work without a keyboard.
   Raise `MIN_CELL` from 38 px (`syncbar.py:79`) to 48 dp, and add a haptic
   tick per cell change: on a phone that tick replaces the visual feedback a
   mouse user gets free.

6. **`SyncPad`** (`keys.py:525`) — *"the same three actions, big enough to hit
   with a mouse"* — becomes the primary bottom bar, and on a phone it is the
   whole tap-timing interface. The action registry comes with it: `ACTIONS
   :45` is already `(name, label, default_key, group)` and `key_possible`
   already returns a REASON an action is unavailable, so a touch UI binds by
   name and gets its grey-out text free.

7. **The waveform.** Replace `envelope()` (`waveform.py:76`, soundfile→ffmpeg)
   with a `MediaCodec` decode at the same 100 Hz RMS-per-block, peak-normalised
   — the decode is already written and measured for the radio, in
   `player/Analysis.kt`, and wants lifting into a shared place. Keep `Wave`'s
   `_hit :723` → `moved(i,v,k,a,b)` → `_dragged` editing path; pinch → `zoom`.

8. **Files.** SAF once, `Documents/Mild Lyrics/{Lyrics,Backups,Exports}`, with
   the 30-second autosave from `backups.py` as a `WorkManager` job. Export
   through `core/document`'s renderer, which already produces ttml/elrc/lrc/
   json/text byte-for-byte.

**What the editor does NOT get:** autotime, vocal maps, forced alignment. The
brief said no SyncNet and no acoustic model, and drag sync is the answer
instead — which is also why `editor/autotime.py` and `editor/vocalmap.py` are
not in the list above.

---

## 3. The viewer's debts

- **Motion artwork.** The one piece of the plan's liveliness that is unported,
  and the honest answer to "the background is not as lively as the desktop":
  the desktop's lively background is `viz`/bloom, which reads Spotify's audio
  analysis and cannot be had on a phone, but motion covers can. Keep the
  discovery half (`motion_url :5112`, `_itunes_albums :5072`, the `AMP_VIDEO`
  m3u8 regex `:4997`, `best_variant :5015`, the `known.json` memo with
  `MOTION_MISS_TTL = 30 d`) and hand the chosen HLS variant to ExoPlayer into a
  `SurfaceTexture`, capped at 480×480/24 fps, looping `MOTION_SECS = 35`. What
  lands on disk is a few MB of segments, not the desktop's 1.4 GB of JPEG
  frames. Cap the cache at 256 MB LRU.
- **The artwork budgets** from the plan's §7 are half-done: covers are fetched
  and a 40×40 wall is built, but there is no disk LRU, no 96 px thumb tier and
  no `onTrimMemory` handling.
- **The settings that are named but not built** — the screen lists them under
  "Not on the phone yet" rather than showing switches that lie: motion artwork,
  background fade, volume bar, view modes, review marks, uncensoring, rejoining
  split words (`merge_ms`), asking Genius for a romanisation, filling untimed
  lines, resync, fetch-ahead, NetEase grafting. Each is a small feature; the
  list is the order they are worth doing in.
- **Landscape and tablets** use the panel layout already, but nothing has ever
  been looked at on a screen that wide.
- **Accessibility.** No content descriptions, no TalkBack pass, no reduced-
  motion honouring. A lyrics app that cannot be read aloud is a poor joke.

---

## 4. The sources' debts

- **`split_asides`** and its five helpers — the one unported step of
  `Fetcher._shaped`. 9 of 282 fixture runs depend on it, and those 9 are
  excluded from the comparison rather than passing.
- **Genius romanisation.** `findRomanization` is ported and has no caller. It
  needs `align`, `unmerge` and `rebalance` from `genius_roman.py`, and wiring
  behind `genius_auto`.
- **`Roster`** is a stub (`OpenRoster`): the prefer/refuse lists are stored,
  read into the cache key, and change nothing. The desktop's `Roster :5951` is
  what they are for.
- **The header's other fetchers:** `apple_card :4189`, `soundcloud_card :4261`,
  `track_card :4317`, `apple_writers :4345`, `netease_roman :5996`.
- **`from_local`** — the plan's repurposing of the local source, reading TTML
  the reader imported into `Documents/Mild Lyrics/Lyrics`. It is in the source
  list in the settings and answers nothing.
- **`sweep`** exists on `DocCache` and nothing calls it; it wants a daily
  `WorkManager` job.
- **Four goldens are written and unread:** `quality.json`, `roundtrip.json`,
  `readings.json`, `syllabify.json`. The last two are the interesting ones —
  they are where the Kuromoji/pykakasi divergence would be MEASURED rather than
  described.

---

## 5. Packaging and release

- icon and splash (there is neither; the launcher shows the default)
- release signing, and a keystore that is not in the repo
- `bundleRelease` and an AAB, since an APK is 17 MB shrunk and a bundle is less
- a baseline profile — Compose start-up on a mid-range phone wants it
- crash reporting that is not `Log.e`, or at least a "copy the trouble" button
- a licence screen: Outfit is OFL, NewPipeExtractor is GPLv3, and the second of
  those has consequences for how this can be distributed. **Decide before
  release, not after.**
- the licence itself (2026-10-09): the desktop is now AGPL-3.0-or-later, with
  the AMLL ports AGPL-3.0-only (see the desktop's README and
  `THIRD_PARTY_NOTICES.md`). If the port carries the AMLL or Spicy renderers
  over, it is bound the same way; check which of them it ports, ship `LICENSE`
  and the notices in the app, and list both on the licence screen next to
  Outfit and NewPipeExtractor (both compatible with the AGPL)

---

## 6. What will not close

Written down so nobody re-opens them expecting a fix:

- **Kuromoji is not pykakasi.** 二人 is ふたり on the desktop and に・にん here,
  and the romaji follows the split. Two dictionaries, one substitution, made
  because pykakasi has no JVM equivalent. A per-word override table would close
  the common cases and never close the class.
- **No Spicy Lyrics Community**, by the brief. `fallback(have=…)` is therefore
  always `"none"` and the credit string for `source == "spl"` never appears.
- **No visualiser.** Four `viz` modes read Spotify's audio analysis, which a
  phone cannot ask for. The measured tempo and loudness in `player/Feel.kt`
  could drive something similar for the BUILT-IN player only, where the audio
  is ours to read — that is a new feature, not a port.
- **No forced alignment, ever**, per the brief: no SyncNet, no demucs, no
  Whisper, no torch.

---

## 7. Extras, in case

None of these is in the brief. They are the things a phone makes obvious that a
desktop did not, kept here so they are not re-invented from scratch each time
one comes up.

- **Per-output offsets.** The desktop already keeps `offsets_device` — one
  correction per audio sink, so the HDMI output can sit 0.45 s out while the
  headset sits at zero. A phone needs this MORE than a desktop does:
  Bluetooth adds 150–250 ms and every pair of earbuds adds a different amount.
  `AudioManager.getDevices` names the route; the rest is the desktop's own
  table, keyed by device instead of by sink.
- **The live link.** `editor/link.py` pushes a document from the editor into the
  running player and follows its clock. Ported, it would let the phone's viewer
  follow the desktop editor over the LAN while somebody times a lyric at their
  desk — and it is the one way the two halves of this project could be used
  together rather than as two copies of the same thing.
- **A home-screen widget** showing the line being sung, and a **Quick Settings
  tile** that toggles following. Both are small; both are the kind of thing
  that makes an app feel like it belongs to the phone.
- **Share a line as an image** — the line, the cover, the artist, rendered by
  the renderer that is already drawing it. People do this by screenshot
  anyway, and a screenshot of this app is 40% status bar.
- **Take a TTML by share intent**, so a file arriving from anywhere opens here.
  It is the import half of the `from_local` source and the same code path.
- **Back up the settings**, as JSON the desktop can read. The two halves share a
  settings vocabulary exactly because the Android defaults were lifted from
  `gui.json`; a round trip would make that vocabulary worth something.
- **A "why is this wrong" button.** The viewer knows the source, the blend, the
  quality and every fault the walk collected. One tap that copies all of it
  would turn "the lyrics are off" into a report worth acting on.
- **Themes beyond dark.** Everything is drawn against #07070A today. The
  palette work is already there in `Palette.kt`; a light mode is a colour table
  and an honest afternoon.

---

## 8. Suggested order

1. the editor's `model`/`ops` port with goldens — the largest, most mechanical,
   least risky chunk, and it unblocks everything else in the editor
2. drag sync end to end: SyncBar, the sweep protocol, `advance_drag`, SyncPad
3. the line list and undo
4. files: SAF, autosave, export
5. the player's browsing screens and the now-playing screen
6. motion artwork
7. packaging, signing, the licence decision
8. the sources' debts, in the order above
9. accessibility and a tablet pass

Steps 1–3 are testable on the JVM with no device, which is where the risk lives
and where the golden harness already pays for itself.

---

## Done since (2026-09-27)

JVM suites: 155 tests, all passing; `assembleDebug` builds. **Nothing below has
been run on a device or emulator yet.**

- **Editor core** (`core/edit`): 53 ops, model gaps (`toBody`, `fromText`,
  `asText`, `timedOnly`, `peelBacking`), sung-rule `syllabify` + `peel`, undo
  (`History`), drag-sync automaton (`share`, `Bar.cellAt`, `Sweep`,
  `advanceDrag`), tap timing, action registry with reasons. Goldened: ops.json
  (1108 cases, 0 faults; `dump_goldens.py --only edit`, needs
  `MILD_DESKTOP=/home/gc/mild-lyrics`), syllabify 3772/3772, toBody/asText 62/62.
  Autotime/vocal-snapping ops deliberately not ported.
- **Editor UI** (`feature/editor`): edit/tap/drag/text modes, SyncBar with
  haptics and two-finger cancel, SyncPad, waveform (built-in player files
  only; decode lifted to `player/Decode.kt`), 30 s autosave, export via
  save-as. Edits save as the "This phone" source.
- **Player**: browse (songs/albums/artists/genres/playlists/search incl.
  streamer), Now Playing (seek, shuffle, repeat, speed, sleep timer), mini
  player, stats, `MediaLibraryService` tree + search, radio reasons.
- **Sources**: `split_asides` (282/282 shaping runs), document-level people
  roster, blend-base toggles wired, local source + share/open import, daily
  sweep job.
- **Viewer**: hide_gaps, focus_height, merge_ms, presets, rebuilt settings
  (pages, search, live preview, reset, backup/restore), onboarding, quick
  sheet, per-output + per-song offsets, share line as image, report copy,
  manual search with kept aliases, widget, QS tile, TalkBack live region,
  reduced motion, cover halo, wallpaper colours.

Still open: uncensor, motion artwork, light theme, translations (dropped by
request), search-by-lyric, pitch control, downloads, release packaging, the
fixed `Documents/Mild Lyrics` SAF tree.

---

## Parity round (2026-09-27, overnight)

JVM suites: 168 tests, all passing; `assembleDebug` builds; smoke-tested on the
`mild` emulator (onboarding, lyrics screen, settings with live preview, the
Spicy renderer) with no crash. Not device-tested; no song was played, so the
line-sync fix, fetching, the radio and the editor are verified by tests only.

- **Fixed: line-synced lyrics were invisible.** `render_pieces` and the open-end
  clamp of `prepare` were never ported; `Column.kt` `prepared()` now spreads a
  line's words over its span (also fixes roman on line sync, vanishing untimed
  ad-libs and fake interlude dots).
- **Spicy Lyrics** is a source (`Spicy.kt`, api.spicylyrics.org, shipped key,
  Spotify ids only), first in the order, and a renderer (`render/Spicy.kt`).
- **Fetching:** failed walks are no longer cached as misses; the walk runs all
  sources in parallel under a 20 s deadline and stops when the song changes;
  per-host Retry-After hush; one shared OkHttp client; BiniLyrics 1.0.6 (lrc.red
  host, storage mirror, merged ISRC pressings); Apple token fetched once with a
  remembered failure; the walk waits briefly for the duration.
- **Player/radio:** plays are recorded against the track that ENDED (they were
  filed under the next one); history, radio and measuring live in the service
  (`Station.kt`) so they survive the UI; softmax sampling fixes the cold start
  always drawing from the first twelve tracks; smoothed Markov, skip penalties,
  exploration and seed terms; shuffle-aware queue; streamed links resolved at
  play time; atomic history writes.
- **Settings made real:** credits on top, sync makers' faces, background fade,
  volume bar, compact view, frame cap, fetch-ahead, NetEase graft, auto resync,
  Genius romanisation, uncensor, review marks (+ renderer), animated covers.
- **Viewer:** full line menu (copy / with time / all, prefer or refuse the
  maker, edit romanisation, song info with Apple/SoundCloud card, reload, save
  .ttml), keep-screen-on, fullscreen, keyboard keys, storage management,
  copy/paste settings, search by lyric text.

Since then: the **light theme** (Settings → Look → Theme: dark, light,
system; the chrome follows it, the lyrics screen stays on the cover's own
colours, as Apple Music does) and review's **split checks**, held to the sung
rule alone as the desktop holds them (split, split-digraph, split-whole,
no-vowel, half-spelled).

Still open: `start_backfill` (it reads Spotify's page, no phone
equivalent); `auto_time` (no aligner, by the brief); pitch; downloads; release
packaging. Cosmetic: the header volume bar uses the thick Material slider.

### Follow-up (2026-09-27)

- **Radio fixed:** YouTube Music streams failed to resolve ("The page needs to
  be reloaded") on NewPipeExtractor v0.24.6; now v0.26.5. A track that will not
  play is now reported on Now Playing and the mini player, and skipped.
- **Streaming radio:** Songs tab → Streaming radio (or ⋯ on a network search
  result): plays only from YouTube Music, related song after related song; no
  library needed. Needs "Radio past the library" on.
- **Lyrics scroll:** the gesture handler was bound to the first column built, so
  after any size change dragging did nothing; now re-keyed. Pinned renderers
  (amll, spicy, karaoke…) now scroll by hand too and ease back after 4 s.
- **Gestures sheet:** ⋯ → Gestures, or the Aa sheet; every gesture and key.
- **Spicy Lyrics for any player:** with a Spotify refresh token (Settings →
  Sources), a song's Spotify id is looked up and Spicy asked. Spotify only
  refreshes a token together with the Client ID that issued it, so that field
  is there too (plus the secret, under More, if that app has one). Rotated
  refresh tokens are saved back.
- **Spotify login button** (Settings → Sources, top): opens Spotify's login in
  the browser, catches `mildlyrics://spotify-callback` and stores the refresh
  token itself, as Lyricify does (PKCE, no secret). Needs a Client ID of the
  reader's own with that redirect URI added. Tested: the button opens Spotify's
  page and a callback is handled; a real login was not run (no Client ID).

- **Spotify login, Lyricify's way:** "Log in with Spotify" opens Spotify's own
  login page in the app (`SpotifyWebLogin`), picks up the `sp_dc` cookie it
  leaves, and exchanges it for web-player tokens (`SpotifyWebPlayer`: TOTP
  from the published secretDict, server time from the Date header). No
  developer app needed; the Client ID browser login stays as a fallback. Not
  tested with a real account. "Continue with Google" is likely refused in an
  embedded page by Google.
- **Scroll fix:** pinned renderers (amll, spicy) skipped lines that the reader
  dragged into view; their culling now adds the drag offset.

## Round: Spicy off-Spotify, radio, resize
- Spicy via Spotify login: a Spotify search refusal is now a fault, so it is never saved as "no id". Only ids that were found are kept. The name match falls back to the lead artist and a looser length check. Held answers are dropped when the login changes.
- Radio: a streamed song keeps the radio streaming, whether it is started from the app or from anywhere else.
- Pinch-resize previews with a canvas scale. The view is rebuilt once, on release, so the lyrics no longer vanish.

## Spotify search (2026-09-27)
- The public Web API refuses the web player's token (429 from the first request; its quota is shared by every web player) and refuses a development-mode developer app's search (403).
- Song → Spotify id now goes through the web player's own search (`searchSuggestions` persisted query on api-partner.spotify.com), `core/sources/SpotifyPartner.kt`. Its query id is read from the web player's script on open.spotify.com when first needed, with the id shipped as a fallback.
- The token comes from `app/SpotifySession.kt`: open.spotify.com is loaded in a hidden WebView and its own `/api/token` request is made on its behalf, and the token is kept. It works logged out, and everything goes to Spotify hosts only.
- ISRC searches still go to the Web API (the search box does not take `isrc:`).
- Removed `SpotifyWebPlayer.kt` (the sp_dc + TOTP token, whose secrets came from GitHub). Rule: Spotify features talk to Spotify hosts only. The Web API (now-playing on other devices, ISRC search) now needs the Client ID login; the in-app page login only makes the hidden web player logged in.
