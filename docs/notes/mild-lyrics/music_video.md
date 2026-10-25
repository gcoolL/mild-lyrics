# `mild-lyrics/music_video.py`

## 2026-10-22 (night) — the video on the song's clock; seek freezes; 60 Hz

Bugs:
- videos lagged after a seek or a skipped section: the picture froze, then jumped.
- the one-video pre-fetch seemed to do nothing.
- on a 60 Hz monitor videos ran at a much lower frame rate than on a 240 Hz one.

Direction: map the video onto the song, so it is known which parts actually need fetching. Decided: re-encode (rather than seek at cuts) and, while a file is not ready, stream and then swap.

**Why it froze.** With a whole file played on `runs`, a seek's landing was only noticed at the next 250 ms poll, and the learnt lead added `+0.5`. So the disk lead settled near 0.75s, and the picture was then held paused while the audio caught up. `swap()` also restarted a just-downloaded file from 0 and waited for a poll. Measured with `memory/bench/mvbench.py` (real `MusicVideo`, real file, offscreen, real time):

| From a whole file (before) | worst gap between frames | first frame |
|---|---|---|
| seek forward / back / forward | 0.77 / 0.91 / 0.94s | — |
| through a mapped cut (`_cut_go`) | 0.16s | — |
| start | — | 0.57–1.2s |

**Why the pre-fetch did little.**
- The map waited for the lyrics (`self.body`).
- The next song's map gave up after 2 minutes without its link.
- At the change of song, `wish()` dropped the new current video until `_mv_find` returned.
- A half-downloaded next video was streamed whole from YouTube.
- Whole videos were fetched even when no map existed (and so nothing was shown).

**60 Hz.** A new frame rebuilt the wall only when `now − _scene_at ≥ 1/30`. At 60 Hz, steps are 16.7 ms apart, so that passed on the 2nd step only when jitter fell the right way; otherwise it waited for the 3rd. Simulated with ±0.6 ms jitter: about 20 fps at 60 Hz, against 30 at 240 Hz. Every 60 fps video was halved everywhere.

**Now: song-clock files.** YouTube's video-only formats are fragmented MP4s whose head carries a `sidx`: segments of 4–7s, each starting on a keyframe.
- `index_of` reads the head (64 KB).
- `pieces(runs, song_len, video_len)` lays the song's seconds out in order as `(a, b, shift)`, with `None` where the video has nothing. It switches half way between stretches, as `shift_at` does.
- `needed` picks the segments those cover.
- `Store` jobs `(vid, pieces)` fetch only those segments into `<vid>.frags`, written where they sit in the video and left sparse. The file must keep its whole length (`truncate`), or ffmpeg will not seek it.
- `build` cuts each stretch exactly (`-ss/-t` per input), puts black where the video has nothing, and concatenates to the song's length. It writes 640 wide, libx264 veryfast crf 26, a keyframe a second, at `nice 19`, threads 2. The result is `<vid>-<hash>.song.mp4` plus `.song.json` (covered, cuts, fps, length). The frags are deleted after the build.
- A parts file has no frame rate to read up front, so `probe` tells it from one second of frame times.
- With no ffmpeg/ffprobe (some Windows installs), the Store downloads whole videos and plays them on `runs` as before.

Checked on `tsmPCi7NKrg` (303s video), song 186s with an intro and a cut:
- fetched 19.2 of 26.2 MB, built in 6.6s, 6.9 MB;
- a 75s file took 2.2s to build;
- frames land within one frame of the source moment (testsrc's clock in the test: exact).

**Playing one** (`_sync_song`):
- Seeks aim `leads["song"]` on (starting at 0.1s, learnt) and keep playing, with no hold.
- `QVideoFrame.startTime()` rides with each frame. A frame shows only within `DRIFT` of the song, and the one at the seek's target is its landing.
- A cut is in the file: its effect goes on a timer and the frame at the cut switches the picture. `_switched` now puts an effect at full height by the switch even if its timer fired late.
- The first frame of a new source re-syncs at once (`_resync`), not at the next poll.

| Song-clock file (after) | worst gap between frames | first frame |
|---|---|---|
| seek forward / back / forward | 0.069 / 0.067 / 0.067s | — |
| through the cut | 0.046s | — |
| start | — | 0.17–0.20s |

**Window.**
- The order is pick → map → job.
- The sound map runs as soon as there is a song source. Captions wait for the lyrics, and with no lyrics yet, "no map" waits instead of stopping the video.
- `_mv_map_next` waits for the next link for as long as that song is next, then queues its job (`mv_next_mapped`).
- At a change of song whose key and length match the pre-fetched next, its job carries straight over.
- `_mv_find` shows a built song file without any lookup when `kept_map` and the Store's length give its plan.
- Events go to follow.log as `who: "video"`: `pick`, `map`, `next-pick`, `next-map`, `fetch` (segments, bytes against the whole), `built` (seconds, size), `shown` (song/file/stream, seconds after the change), `seek`, `landed`, `store-error`, `build-failed`.

**Frame rate.** `video_period`: one rebuild per new frame, at the video's own frame time (learnt from frame times, ≥1/60) less half a refresh. Fades rebuild at 1/60. In the simulation: 30 at 60 Hz and at 240 Hz for a 30 fps video, 60 for a 60 fps one at 60 Hz. `_rgb` halves only frames wider than `WIDE` (1.0 ms a frame at 720p, 2.6 ms full size at 640).

Not done: a real-window run in the headless KWin at 60 Hz (the gate is checked by simulation). Captions-only videos still can't be pre-fetched, since their map needs the next song's lyrics.

Tests: test_music_video (102), test_mv_window (10).

## 2026-10-22 — music videos behind the lyrics

Goal: music videos in Mild Lyrics. Decided: as the background; Mild Lyrics' own player only; up to 720p.

It is Settings ▸ Background ▸ **Music video** (`music_video`, off by default). It is not a Background mode. At first it was one (`bg: "video"`, the art wall under it); the same day it became a setting, so the chosen Background (art, mesh, solid…) shows whenever there is no frame. That covers Spotify playing, no video found, no way to keep it in step, and the parts of the song the video lacks. `video_wall()` says when a frame is the wall, and `scene_flat` is false then, so a lean solid wall is not a one-pixel fill. It is off in the clear modes, and its row is hidden there. A saved `bg: "video"` loads as `art` with Music video on.

**Finding the video.** `find` does a yt-dlp flat search for "<artist> <title> official music video"; `pick` takes:
- the song's own words (the title before any bracket);
- a length from the song's −10s to +240s (videos add intros, not minutes);
- no lyric, audio, visualiser, live, cover or remix uploads, nor fan lyric/translation uploads in other languages (가사, 해석, 歌詞, letra, legendado, paroles, vietsub…);
- never a "- Topic" channel (YouTube's audio-only uploads);
- the artist's own channel first; otherwise only a verified channel (`channel_is_verified`) that titles it the official video.

The first version took any channel naming the artist, and the screen showed TURN UP OR DIE over a fan's Korean lyric video (`ev9ceMMxAFE`, channel "현"). A fan's "(Official Video)" upload (Harlem Fetty's Trap Queen) is still a fan's. Picks are kept per track in `~/.cache/mild-lyrics/home/videos.json` for a week, with `v: PICK_V`, so the first version's picks are made again. Checked live: TURN UP OR DIE → none (its only own upload is "(audio)"); Dreamflasher, Superhero, Shape of You, Hello → the official videos; Trap Queen → `bKq4L5vLtsY`, not the fan upload.

When the playing track is itself a hand-picked upload (`meta["upload"]`: YouTube tab, pasted link), that upload is the video and its clock is the audio's.

**A still picture is no video (later the same day).** Goal: notice when most frames are the same, e.g. Take Me To The Beach, whose pick (`p7DnxRRuqzM`, ImagineDragons' own channel) is its cover for 167s. `moving(info)` reads the video's storyboard: YouTube's frame previews across the whole video, the `sb2` level being one 10×10 sheet, a frame every ~2s. `still_share` shrinks each frame to 8×8 with Qt (no numpy needed) and counts the frames within `STILL_OFF` (8/255) of the most usual one. At `STILL_SHARE` (60%) or more, the upload is passed over. `find` now looks at `ranked()`'s best three in turn. No storyboard, or one that cannot be fetched, is not a no.

Measured on sb2:

| Upload | Frames like the usual one | Usual distance |
|---|---|---|
| Take Me To The Beach (still) | 100% | 3.6 |
| Superhero | 0% | 25.7 |
| Dreamflasher | 1% | 14.3 |
| Shape of You | 0% | 20.2 |

The next candidate for that song was its "Amazon Music Songline" live session, so sessions, Songline, unplugged, Tiny Desk, interviews, commentary, rehearsals and "in studio" uploads are now refused too. Take Me To The Beach → none (the chosen Background shows); Believer, Hello, Shape of You unchanged. `PICK_V` 3 asks earlier picks again.

**Keeping it in step.** Album time maps to video time through `yt_captions.stretches`: the same caption anchors that move lyrics onto a video's clock, read off the lyrics on screen. With no captions, a video within `SAME_LEN` (3s) of the song runs on its clock; otherwise there is no video, rather than a picture that drifts. The muted player (`QMediaPlayer` + `QVideoSink`, no audio output) is kept in step from `LyricsView.poll` → `mv_step` → `MusicVideo.sync`. Measured on 720p googlevideo streams, offscreen:
- A seek sent before the first frame is dropped.
- A seek takes 2–5s to land; re-sending before it lands stalled the picture for good (one frame in 12s).
- `setPlaybackRate` on video-only playback jumped the position (+2.3s in one second), so it is not used.

So:
- `sync` seeks once, aimed `lead` past the audio. `lead` starts at 5s and is learnt from how long seeks take, carried over between songs.
- It waits for the seek to land (`LAND`), then pauses the picture while it is ahead and plays it when the audio reaches it.
- Frames are shown only while the picture is within `DRIFT` (0.35s), so the wrong moment never shows.

Superhero on the real window offscreen: map +40.9s from its uploaded subtitles, first frame 9.4s after the song started (search + link + one seek), then 0.3s from the audio.

**Seeking and pausing (later the same day).** Bug: sometimes after a seek or pause the video stopped playing entirely.
- A seek's landing was told by the picture moving again, but a seek made while the picture was paused (you paused, or it was held ahead) never moved. So it waited `LAND` (8s), sought again, and waited again, for good.
- A seek back while playing left the picture far ahead. It was held there until the audio caught up, which could be a minute of a still picture.

Now:
- Paused, the picture seeks straight to the audio's moment and waits for nothing.
- Playing, every seek also plays, so its landing can be seen.
- Only a seek's own lead is held. Anything further ahead is sought like anything behind.
- A hold lasts until the audio is within 0.05s, not within `DRIFT` (playing picture still pauses only past `DRIFT`, so small wobbles don't stutter). When the audio is nearer than the next 250ms poll, a timer lets go on time.

Scripted on a real 720p stream (pause, seek while paused, play, seeks forward and back), it ended 0.02–0.07s from the audio every time. A seek took 5–10s to settle on that connection, with the last good frame showing meanwhile. Tests: a fake player that, like Qt's, only moves while playing (test_music_video, 4 more).

**Frames.** `QVideoFrame.toImage()` off the GUI thread crashed in `qImageFromVideoFrame`: the decoder moves on from the buffer. On the GUI thread it costs 2.6ms at 720p. So `_frame` maps the frame there and copies its NV12/I420 planes (~0.3ms), and one worker converts them with numpy at half size (BT.709 limited range; 640×360 is all the wall uses). numpy is the lyrics app's optional "liveviz" dependency. Without it, or for another pixel format, it is `toImage()` on the GUI thread, at most 15 times a second.

**The wall.** `scene_layer` draws the newest frame, cover-cropped, at 0.75 opacity under the usual veil and glow. A new frame rebuilds the wall at most 30 times a second (`_scene_vgen`). Measured at 1280×720 on the CPU (scene_div 1): 1.36ms per build with a frame, 0.33ms with the cover.

Tests: tests/test_music_video.py (21).

## 2026-10-22 (later) — pre-fetching, cuts, the visualiser, and start-of-track stutters

**One video ahead** (asked: "be 1 music video ahead at all times, with the entirety of the current and next one loaded, limit the network speed"):
- `Store` downloads whole videos to `~/.cache/mild-lyrics/videos/`: the current song's first, then the next one's (`_mv_next_song`, from Mild Lyrics' queue; picked ahead by `_mv_find_next`).
- Downloads use 1MB ranged requests, capped at Settings ▸ Background ▸ **Video download speed** (`mv_speed`, default 2 MB/s). A stopped download keeps its `.part` and resumes from it. The folder is kept under 600MB, oldest first, never the wanted ones.
- Picks are now kept by `song_key` (name), since the next song has no track id yet.
- A video on disk plays from the file. One still downloading plays from YouTube, and `on_mv_stored` swaps it to the file when it finishes (`MusicVideo.swap`).
- Measured from disk: first frame 0.13s, a seek playing again after 0.09s (YouTube: 2–5s). Seek leads are learnt per kind (`leads[disk]`, 0.3s floor on disk).
- On the real window offscreen (6 MB/s for the test): both videos were on disk 17s into Superhero, and the next song's video showed 0.94s after the track changed, in step, with no frame over 16ms (about 10s before this).

**Cuts** (asked: an effect where the video has a part the song does not, NF – HOPE at 2:55). Their feedback, in order: a cross-fade was not enough; "some sort of zap/static effect"; "make it a setting"; the static was "too static-y — search up what good video cuts could be used here" (five sources, at least); and pauses before the video carried on, then a small pause before the effect.

Settings ▸ Background ▸ **Video cuts** (`mv_cuts`): `flash` (default), `dip`, `zoom`, `glitch`, `fade`, `cut`. What the sources say:
- Cuts and dissolves are most of what editors use; restraint is the advice, and "exploded zooms" distract (Music Connection, Synthesia).
- Dip to black/white marks a scene or time change, and a flash marks "a big change" (Neil Chase Film).
- Glitch suits music clips, zoom energetic edits, a fade sincere ones (Submagic).
- A music-video editor's flash/strobe cut alternates the two clips for ~20 frames on the beat (Creative COW). The strobe was left out: rapid flashing behind lyrics is hard on photosensitive viewers.

So the effects, all short: a white flash, a dip to black, a 14% zoom punch settling back, a glitch (the picture torn in a few bands with red/cyan fringes, no noise). `FX` holds (rise, fall). Dip is dark by the switch; the others go up as the seek is sent, stay up until the new picture lands (`fx_switch`), and fall from there.

The pauses, and what fixed them:
- **Seeking only once the song had crossed the cut.** Now `sync` notices a known cut `CUT_LEAD` (0.35s) ahead and bisects for the exact second (`_cut_b`).
- **The poll is 250ms.** From a file, a `QTimer` sends the seek (`_cut_go`) `DISK_LAND` (0.1s) before the cut, aimed 0.1s past it, so it lands at the cut with no hold. Until then the picture keeps the old shift (`_cut_sent`). From YouTube, it seeks at once and holds, as before.
- **A frozen frame before the effect.** The effect now starts with the seek, not when the new frame arrives.

Measured on the real window offscreen, Shape of You from its file through its cut (album ~178.8s, +6.27s → +7.44s), then a 2s pause: no gap between new frames over 150ms except the pause itself. After resuming, the first new frame came at 63ms, and the picture was 0.13s from the audio.

Where the video has no picture for a part of the song (`_outside`), late frames are ignored and the picture goes out (and comes back) under the same effect.

Sources: musicconnection.com/do-it-yourself-videos/5/; neilchasefilm.com/?p=11504; submagic.co/da/blog/6-best-video-transitions-that-famous-creators-use; synthesia.io/post/video-transitions; creativecow.net/?p=165666.

**Visualiser over video** (`viz_on_video`, default off): `viz_live()` is false while a video is the wall.

**Stutters at a track's start** (reported even with no video). Measured on the real window offscreen with a 4ms paint loop and a watchdog grabbing the GUI thread's stack:
- numpy was imported on the GUI thread by `live_audio.want` → `audio_analysis.usable` (~45ms). It is now imported on a thread 2s after the window opens.
- The rest happened inside Qt calls while background Python threads (yt-dlp: video searches, page checks, the resolver's next songs) held the GIL, which the GUI thread waited up to the 5ms default switch interval for every time a paint called back into Python. No Qt player call took over 2ms.

| `sys.setswitchinterval` | frames over 16ms, first 25s | video shown after |
|---|---|---|
| 5ms | 15–17 | 16–19s |
| 2ms | 10–11 | 13–18s |
| 1ms | 6 | 12s |
| 0.5ms | 4–5 | not within 25s |
| Music video off, 5ms | 3 | — |

`main()` sets 1ms.

Tests: test_music_video (49).

## 2026-10-22 — "it doesn't find a music video for a lot of songs, e.g. The Search by NF"

The Search does have one (`fnlJw9H0xAM`, NF's own channel, with uploaded subtitles), and `find` picks it today. Their videos.json had `thesearch|nf` kept as "" from 03:57. `find` skipped a candidate whose page lookup raised (YouTube's bot check or a dropped connection), and with every candidate skipped it returned "", which the Finder kept for a week. Now:
- a lookup that failed is raised, not returned as "";
- the Finder keeps nothing for it;
- the window tries again 30s later (`_mv_retry_at`);
- `PICK_V` 4 asks every earlier pick again once.

The rest of their 24 "none" picks looked at were right. Change and Nate by NF have no video, only NF's "(Audio)" uploads and fan-made ones. Alien (Lucidious) and To My Younger Self (Britton) have only lyric videos on their own channels. Scared of the Dark's top results are a fan edit and a lyric video. "Be the Same" is by NF!, not NF.

The search now asks for the first credited artist and the title without its brackets ("(feat. …)", "[with …]"), not every artist and the whole title; `pick` still checks the full credit.

Test: test_music_video (50).

## 2026-10-22 (late) — YouTube's bot check; The Kill (Bury Me)

The Kill's official video (`8yvGCAvOAfM`, the band's channel) is found by the search. The page lookup that came next answered "Sign in to confirm you're not a bot", and then so did every video, even ones that worked earlier (Superhero, Shape of You), on every player client. This IP was flagged, from that night's test runs plus the app's own count: a search, up to three candidate page lookups, the stream lookup twice (player and Store), caption lookups, and the same again for the next song.

Done, kept small on purpose (end of session):
- `find` no longer fetches each candidate's page. `still_thumbs` compares YouTube's three preview frames (`i.ytimg.com/vi/<id>/mq1..3.jpg`): a still cover differs by 0.0, Superhero/Dreamflasher/Shape of You/The Kill by 18–65.
- A "not a bot" answer stops music-video lookups for 30 minutes (`BLOCKED`).
- A failed lookup is retried after 10 minutes, not 30s.
- `PICK_V` 5.

Next session (done):
- `stream()` keeps its answer per video until ten minutes before the link expires (`_STREAMS`), so the player and the `Store` share one lookup. The Store asks `fresh=True` for a link that went stale mid-download.
- `yt_captions.captions` uses only links a lookup already gave (`LINKS`). `_asked`, which fetched a page of its own, is gone. With none in hand nothing is kept, so a later play looks again.

Still open:
- `MILD_COOKIES` for `_ytdl`, for using a browser's cookies.
- While flagged, Mild Lyrics' own audio streaming fails too: the resolver's `_audio` is the same lookup.

Tests: test_music_video (52).

## 2026-10-22 — videos with no captions, by their sound (Leave a Light On)

Bug: some music videos never played because they could not be matched, those without subtitles, e.g. Leave a Light On. Tom Walker's pick (`nqnkBdExjws`, his own channel) was right, but it has no captions, uploaded or automatic, and runs 208s against the song's 186s. With nothing to anchor on and more than `SAME_LEN` of difference, `clock_map` gave None, so the chosen Background showed.

Now `audio_map` finds the video's sound in the song's (at first only when captions gave no stretches; see the end of this section):
- `stream()` keeps the smallest sound-only link from the lookup it already makes (`AUDIO`), so this asks YouTube for no extra page. A video played from disk, picked in an earlier session, costs one `stream()` lookup the first time (memoised, and blocked while `BLOCKED`).
- ffmpeg decodes that link (1.3MB for this one, 0.4s, not under `mv_speed`) and the song from `own_source()` (what our player plays: a file or its stream), both mono at 11025 Hz.
- `audio_analysis.match`: chroma rows every 46ms (log, centred, unit length). Each 12s of the song, every 4s, is compared against every place in the video by FFT. Each window's best three places become candidate shifts, and a Viterbi pass picks one per window, or "not here" (`MATCH_MIN`), paying `MATCH_JUMP` per change. Without that, choruses repeated in the song pull windows to the wrong one (they score 0.9+ there too). A stretch has to cover three windows (20s). Each stretch's shift is refined to a fraction of a row over its whole span, and where two meet, the cut is the row where the later shift starts matching better.
- The map is kept in `youtube-captions/<vid>.audio.json` per song length, for `KEEP_FOR`. A miss is not kept, since the player's source may still have been the last song's. The window maps again when the player's source changes, and a result read off an old source is dropped (`mv_mapped` carries `(body, source)`).

Measured, real audio:

| Pair | Best score per window (median / max) |
|---|---|
| Leave a Light On, song vs its video | 0.973 / 0.986 |
| Song vs three other songs, and those against each other | 0.10–0.27 / ≤0.32 |

So `MATCH_MIN` is 0.6. Leave a Light On → one stretch, the whole song, +12.505s, 1.1s from the two links. The same audio spliced as tests: an inserted 6s break gives two stretches with the cut within 50ms; a removed 20s gives the earlier shift less 20; another song's talk as an intro and as a skit is skipped; another song gives nothing.

Known limit: when the part a video lacks ends inside a chorus the song repeats, that stretch can match an identical later chorus instead (right sound, wrong footage until the next cut).

At first captions came first and the sound was asked for only when they said nothing. The same day the sound became the default: `clock_map` now tries the sound first, then captions (where it is not found, or there is no song source), then the same-length rule. Uploaded subtitles lead by ~0.2s, so the sound is the more exact of the two, at one small download per video. Not yet compared against captions on a video that has both.

Tests: test_music_video (67).

## 2026-10-22 — the next video was not really ready (Mansion, Medicine)

Bug: the next video did not seem to be fully pre-fetched. From videos.json and the videos folder's file times:
- **Two keys for one song.** The next song is picked under its queue title. Once it plays, the catalogue's name has been merged in ("Mansion" → "Mansion (feat. Fleurie)", "Medicine" → "Medicine (feat. Conor Maynard)"), so the current-song pick missed the kept answer and searched YouTube again at the change of song. For Medicine both searches gave `2uRgIkytZRw`, already on disk, so only the search showed (a few seconds). For Mansion they differed.
- **Two lengths.** The next song's pick used the queue's length (323s). The current one used `meta["length"]`, the player's duration, which for a moment after a change is the last song's (or 0, which turns the length rule off). So the prefetch refused the 294s `w899-JWhPtQ` (more than 10s short), kept "none", and fetched nothing. The current pick took it, and it downloaded as the current video (done 11s after the change).
- **The sound map** (earlier today) decoded the video's sound and the song's at the change of song, about a second more.

Now:
- `song_key` leaves out credits ("(feat. …)", "[with …]", "ft. …"), so both picks share one answer. Version names ("(Acoustic)") stay in.
- The pick and the map use the queue item's own `ms`, so the current-song pick asks what the prefetch asked.
- `_mv_find_next` also makes the next song's sound map (`_mv_map_next`): its link from the resolver (it fetches songs coming up, so this waits up to 2 minutes for one) or its file. `audio_map` keeps the map on disk, so the change of song reads it.
- `stream()` holds a lock around the lookup, so the Store and the next song's map, asking at once, share one lookup (checked: two threads, one lookup).

With one length, Mansion now gets no video, since its 294s video is more than `length − 10s` short of the 323s song. That rule predates sound matching (loosening it is still open).

Tests: test_music_video (68); the window side checked on the real `LyricsView` methods with stand-ins (the queue's length used, the next song's map made with its link and length).

## 2026-10-22 — "own channel" means the Official Artist Channel (Mansion)

Mansion's pick, `w899-JWhPtQ` "NF- Mansion (music video)", was on "NFRealMuic". That is not NF's channel (confirmed). NF's is NFrealmusic. It was taken as NF's own only because its name starts with "nf".

Before deciding, the 29s it is short were checked (asked: "ends/starts may be left out if there's absolutely no lyrics, or (barely) even audio there"). By the sound match it is the song from +0.04s, stopping at song time 291.6s of 323.3s. The missing end holds five lyric lines ("Is that me or the fear talking?…" cut off, "It's lonely" ×2, "Oh, yeah, it's lonely", "Inside this mansion" at 318.3s), at −6 to −10 dB against the song's −7 dB average. Only the last 2s are silent.

yt-dlp files both the ♪ Official Artist Channel badge (`BADGE_STYLE_TYPE_VERIFIED_ARTIST`, icon `OFFICIAL_ARTIST_BADGE`) and the plain ✓ as `channel_is_verified`. `_read_artist_badge` wraps its `_extract_video` so each search entry also carries `channel_is_artist`, read off the renderer's `ownerBadges`. That is the same search, with no extra lookups. `ranked` takes a channel as the artist's own only when it is named for a credited artist and:
- has the ♪ badge; or
- is a ✓ VERIFIED channel ending "vevo" (FettyWapVEVO);
- with no badges to read at all (a later yt-dlp), the ✓ stands in. A name alone never counts.

A verified label calling it the official video is still taken as before.

Search for "NF Mansion official music video", live: NFrealmusic ✓♪ has only "(Audio)" and other songs. Everything else is unbadged (the NFRealMuic upload, a lyric video, an "[Unofficial Music Video]", a fanmade one, a reaction). So Mansion → none. Leave a Light On: Tom Walker ✓♪, while 7clouds and BBC Music are ✓ only, so → `nqnkBdExjws` as before. `PICK_V` 6 asks earlier picks again.

Tests: test_music_video (74).

## 2026-10-22: autoplay's art tracks are no video

Bug: HIGHEST IN THE ROOM showed one picture, a ladder in the clouds, for the whole song. It had come from autoplay's YouTube Music radio. That radio only queues `MUSIC_VIDEO_TYPE_ATV` rows (`stream_source`), which are YouTube Music's art tracks: the release audio under a still cover. Each one carries its `yt` id, so the queue item looked like a hand-picked upload, and `_mv_find`/`_mv_find_next` used it as the video directly. That skipped the search, and with it the still check. In follow.log the pick was `Gs5WlUzk_Ec` with one stretch covering all 176s, and the whole download was 1.4 MB, against 37 MB for ZEZE's real video. `still_thumbs` reports it as still.

Now `picture_of(upload)` keeps the song's own upload only when its preview frames move; otherwise the Finder searches as for any other song, and the sound map puts that video on the art track's clock. Each answer is kept in memory for the rest of the run, except an unreadable one, which is asked again. A hand-picked "(Audio)" upload with a still cover is now searched past in the same way.

## 2026-10-22: collab uploads (Heathens)

Bug: Heathens got no video, though `UprcpdwuwCg` is the official one and came first in the search. It is a YouTube collab upload. yt-dlp gives its channel as "Fueled By Ramen and twenty one pilots" with no badges at all (`channel_is_verified` None, no `ownerBadges`), so it was neither the artist's own channel nor a ✓ calling itself official. The co-owners are in the byline's Collaborators dialog (`longBylineText` → `showDialogCommand` → `listItemViewModel`s), and each has its own badge as an `attachmentRuns` image: `AUDIO_BADGE` for the ♪ Official Artist Channel, `CHECK_CIRCLE_FILLED` for the ✓. `_collab` reads that list into `collab`, and `ranked` checks each co-owner with the same own-channel rule (`_own`) a single uploader gets. A ✓ on any co-owner counts for the "official" fallback. PICK_V 7, so the week-long "none" picks are asked again.

## 2026-10-22: lower-Hz panels still showed fewer frames

Bug, again: videos rendered at a lower frame rate on a lower-refresh monitor, even where the refresh was not below the video's rate. The first fix (the gate below) did not fix it. Measured with a run of the real app on Understand (BoyWithUke, `T2fjQrsKbAM`, 23.976 fps song-clock file).

**Measured: the real window in the headless KWin at 60 Hz** with a real-use gui.json (GPU auto = on, mesh, amll), offline, scratch XDG dirs, and a fake own-player clock. The window found and showed the built file itself. Harness: `memory/bench/mv60/` (`run.sh OUT SECONDS START`, `an.py OUT`).

| frames/s | before | after |
|---|---|---|
| decoder (sink) | 24.0 | 24.0 |
| converted to pictures | 11–14 | 24.0 |
| on screen (distinct) | 11–14 | 24.0 (3,2,3,2 refreshes each) |
| one conversion, wall (CPU 2.7 ms) | 70–84 ms | 4.2 ms |
| GIL held by others (probe thread) | 86% | 1% |
| GUI thread CPU | 18% | 18% |

With GPU drawing off, the same run already gave 24.0, at 1.7 ms a conversion.

**Cause: the GIL was held through the swap.** `LyricsView.event()` was a Python override ending in `super().event(ev)`. The window's UpdateRequest arrives through it, so Qt's whole repaint ran inside that call with the GIL held. On the GPU canvas that includes the swap, which waits for the next refresh: about 14 ms of every 16.7 at 60 Hz, against about 4 at 240 Hz. `_rgb` lets go of the GIL around each numpy operation and then needs it back, so the converter got about one turn per refresh. At 60 Hz that is more than a frame's time, and `_next` was overwritten. py-spy `--gil --nonblocking`: 56% of the GIL-holding samples were at that `super().event` line. Every other Python thread (yt-dlp, layout-ahead, audio analysis) waited the same way.

**Fix:** the override's work is now `saw_event`, called from `_WakeFilter`, an event filter on the window. A filter returns before Qt delivers the event, so the delivery and the swap run with the GIL released. Mouse moves and activation still wake the frames (checked in the same harness). Test: test_music_video, "the window leaves event() to Qt".

**The gate, changed first, kept.** `video_period` waited a whole frame time less half a refresh. On the refresh grid that rounds up to whole refreshes and leaves no room to catch up after a late step. It also learnt its frame time from converted frames, so with the drops above it read 69–81 ms instead of 42. It is now half a frame time less half a refresh. Simulated with arrivals jittered 4 ms and steps up to 4 ms late, frames lost per second, old → new:

| | 60 Hz | 144 Hz | 240 Hz |
|---|---|---|---|
| 23.976 fps, learnt exact | 1.1 → 0 | 0 → 0 | 0.2 → 0 |
| 23.976 fps, 10% long | 4.0 → 0 | 2.5 → 0 | 2.3 → 0 |
| 29.97 fps, 10% long | 0 → 0 | 2.3 → 0 | 2.9 → 0 |
| 59.94 fps, 10% long | — | 8.3 → 0 | 6.8 → 0 |

Test: "no frames lost under 2x the refresh".

## 2026-10-22 — The bot-check block survives restarts

`BLOCKED` lived only in memory, so every start asked YouTube again: four "confirm you're not a bot" errors per launch on the Windows laptop, which they had to restart many times that evening because of the soundcard crash. Each of those asks keeps the flag up. `_blocked` now writes `{"until": …}` to `<cache>/youtube-blocked.json`, and `_load_block` reads it back at import. A value more than 30 minutes ahead is ignored. Checked across two runs with the cache in scratch.

## 2026-10-22 — The flag was on the IPv6 address only

Songs still did not play on the Windows laptop after the flag "should have lifted". A probe from the desktop for the same video: IPv4 (shared by both machines) answered, IPv6 ("Sign in to confirm you're not a bot") did not. Both machines have their own IPv6 address in the same /64. Python and yt-dlp try IPv6 first, so every ask went out on the flagged address. An earlier probe that "passed" had gone out over IPv4.

`_blocked` now returns True on the first refusal and sets `V4_ONLY` for 30 minutes. `stream_source._ytdl` then passes `source_address: "0.0.0.0"`, and `_audio_cli` passes `-4`. `_audio` and `stream()` ask once more straight away. A refusal over IPv4 sets `BLOCKED` as before. Both are kept in youtube-blocked.json (`until`, `v4_until`). The audio link is signed for the IPv4 address (`ip=` in sparams), but googlevideo served it over IPv6 too (206 both ways), so the player needs nothing. Checked with a fake yt-dlp (none / IPv6 flagged / both, plus a restart) and for real: 5QqXXjDKNP4 was refused over IPv6, then answered over IPv4 in 3.1s total. test_music_video 111, test_autoplay 38, test_home_page 184/1 (the known cache check).

Same evening, a race in that fallback: the window asks for up to three songs at once (current plus prefetch). All three were refused over IPv6 together. The first refusal set `V4_ONLY`, and the second then read as a refusal over IPv4 and set `BLOCKED`, 0.3 s later, before IPv4 had been tried. `_blocked(e, v4)` now takes whether that ask itself went out over IPv4 (read before the ask). Checked with a fake yt-dlp and three concurrent asks: all three played over IPv4, nothing blocked. They confirmed playback works on the laptop afterwards.

## 2026-10-22 — No song-clock videos on Windows: the Store's redirected AppData

On the Windows laptop every build failed: 53 `build-failed` in half an hour, the same key every 10 s, no reason given. ffmpeg itself is fine there (winget Gyan 9.0.1; a 30 s build of the same parts ran in 2.6 s with exit 0). Mild Lyrics runs on the Microsoft Store's Python, and new files it makes under AppData go into `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_…\LocalCache\Local\`. Python sees them at the usual path. ffprobe and ffmpeg do not: `…\AppData\Local\mild-lyrics\videos` does not exist for them. Fix: `noconsole.real_path` (`os.path.realpath`, which Python's docs give for exactly this; for a file not made yet, its folder's) on everything handed to ffprobe/ffmpeg here, in `audio_analysis.decode`, on the animated-cover frames folder, and when a folder is opened in the shell. The Store also stops after `TRIES` (3) failed attempts per item, counted only while the item is still wanted. A failure now logs `build-error` with the reason (probe, not covered, or ffmpeg's stderr). Not yet seen working on Windows: the next build there will show it.

## 2026-10-23 — "It's not finding a lot of music videos"

Their example was Sign of the Times (Harry Styles). Here, home/videos.json held 149 "none" against 194 picks, and follow.log had 61 of 129 songs with no video. One search each, as `find` makes it, for Sign of the Times, See You Again, Stressed Out and Treat You Better: all four are found by today's `ranked`. Each turned-down result is a live cut, an audio or lyric upload, or a TV/fan channel, as intended. Of the 149 cached "none", 113 came from older picker versions (PICK_V 2–6), so they are asked again when the song next plays. Only 36 came from v7.

- `ranked(..., why)` records why each result was turned down (length, topic, title, not-it:<word>, artist, channel:<name>, or still picture). A miss logs `no-video` with the result count and reasons, so the next one explains itself.
- An empty search raises instead of returning "": that is "couldn't ask", not "no video".
- A "none" is kept `KEEP_NONE` (1 day), a pick `KEEP_FOR` (7 days).

Also limiting videos that night: YouTube had flagged both their addresses, so even a picked video could not be streamed (`stream()` is a player-page lookup). Videos show only for Mild Lyrics' own player, by design. Test: test_mv_misses.py (10; real search results in tests/fixtures).

## 2026-10-23 — Visualisers are no video

Reported with a screenshot: One Night Only (Trivecta) had a "music video" that is a visualiser. The picture is black with a logo, a dotted ring that pulses, and the cover in a corner. It is `InKdCj_4BZs` on Trivecta's own verified channel, titled with nothing but the song's name, so `NOT_IT`'s "visuali[sz]er" never saw it. `still_thumbs` passed it because it only turned down a picture that is identical in all three previews (mean difference under 4), and the ring and the corner cover changed between them.

`still_part` measures instead the share of the picture (32x18 cells) that is alike (every channel within 12) in all three previews. First it trims letterbox and pillarbox bars: edge rows and columns that never change and are one colour, black or not (Three Days Grace's Animal I Have Become has red bars). Measured on preview frames only, with no page lookups. The 150 current picks in their videos.json plus 12 "official music video" results score 0.00–0.37; the top is The Living Tombstone's animated lyric video at 0.37, and Portishead's Roads, a performance in a very wide frame, is 0.25 once trimmed. Visualisers: One Night Only 0.83, three more among their picks (Soma 0.77, I Don't Trust Nobody 0.61, Space Flute 0.50), and 7 of 12 "official visualizer" results at 0.46–1.00. The other five visualizer results are footage (0.00–0.43) and look like a video anyway. `STILL_PART = 0.45`, and `still_thumbs` is True from there. That covers `find`'s top three, and `picture_of` for a song's own upload. PICK_V 7→8, so every saved pick is asked again on its next play. test_music_video 112/112 (with made-up frames: a visualiser, plain footage, footage in black bars and in red bars), test_mv_window 10/10.

## 2026-10-24 — A longer title is another song

Reported with a screenshot: Lost (Linkin Park) showed "Lost IN THE ECHO" as its name, and the video pick for it was `co4YpHTqmfQ`, the LOST IN THE ECHO official video. The sound match refused the video, so it never showed, but the pick was saved. `ranked` took any upload whose title held every word of the song's, in any place. `_titled` now wants the words as one run with only punctuation, the artist's words or `FILLER` ("official", "video", "mv", "hd", "feat"…) on either side. Apostrophes are dropped only inside a word, so 'Dynamite' and 'Sign Of The Times' keep their quotes as separators. Checked: Linkin Park - Lost (Official Music Video), BTS 'Dynamite' Official MV, PSY GANGNAM STYLE(강남스타일) M/V, YOASOBI「夜に駆ける」, Calvin Harris - Feels … ft. Pharrell pass; LOST IN THE ECHO for Lost and Blur - Song 2 for "Song" do not. PICK_V 8→9. test_music_video 112/112, test_mv_misses all passed, test_mv_window 10/10.

The name came from the same flaw in two other places, in `stream_source` and `lyric_sources`; see lyric_sources.md, 2026-10-24.
