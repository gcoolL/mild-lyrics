# `mild-lyrics/yt_captions.py`

## 2026-10-22 — lyrics on a YouTube video's clock, from its captions

Goal: time YouTube videos' lyrics from the subtitles YouTube provides. Decided: re-time the lyrics, don't show the captions as lyrics; and use uploaded subtitles and automatic captions both.

**What YouTube has.** Measured on six videos with yt-dlp:
- Official music videos usually have uploaded subtitles (one per line, timed by a person, about 0.2s early, with ♪ and "(somber music)"), automatic captions (speech recognition, json3 with `tOffsetMs` per word, cut into chunks that cross lyric lines), or both.
- Fan uploads and the YouTube Music tracks normal streaming picks mostly have neither (3 of 4 checked).

So this mostly helps videos played from the YouTube tab or a pasted link. Those are the ones whose cut (intro, skit, edit) differs from the album timing every lyric source has. Dreamflasher's automatic captions show the recogniser filling gaps with "Heat. Heat." and "[Music]". Only real phrases ("complete destruction by shadow") match lyric words.

**The design.** A video's audio is the album recording with things added or cut. So the captions do not supply the timing; they say where each stretch of the song sits in the video.
- Pairs of words (the lyric word and the next one) that also appear in the captions become anchors (album time, video time).
- `_chain` picks the best in-order chain and pays `JUMP` for every change of shift over `TOL`. Plain left-to-right matching pairs the first lyric chorus with the second sung one when the recogniser missed the first (a 20s error, in the made-up test).
- `stretches` splits the chain where the shift changes. It drops stretches with too little behind them (`MIN_WEIGHT`: a caption word counts 1, a subtitle line's first word 2) and merges neighbours within `TOL/2`.
- `retime` moves each line, its words and background vocals with it, by its stretch's shift. A line outside every stretch takes the nearest one. The words keep the source's own timing, so a word sync stays a word sync.
- When every stretch is under `SHIFT_MIN` (0.5s), nothing is moved, since subtitles' habitual lead is not a cut.
- Unsynced lyrics are left alone.

Only real times anchor. For a line-synced source (LRCLIB), a line's later words have no time of their own. They help the matching but never become anchors: an even spread over the line was a guess, and it pulled a made-up 0s shift to -0.6s.

**Where it runs.**
- The resolver's own `extract_info` already lists the caption tracks. `_audio` saves their json3 links in `YC.LINKS`, so no extra YouTube call is made.
- A stream link kept from before asks yt-dlp once (`_asked`). Captions, or the fact a video has none, are kept for a week in `~/.cache/mild-lyrics/youtube-captions/<id>.json`.
- `links_of` takes the uploaded track in the video's own language (else English) and the recogniser's `-orig` track, never a machine translation.
- `LocalPlayer.reading()` puts the upload's id in `meta["yt"]`.
- `LyricsView.on_fetched` (and the held-back `vet_body` answer) shows the lyrics as they come. `yt_retime` then works on a thread, and `on_yt_ready` swaps the moved copy in, only while the same song and the same lyrics are on screen.
- The moved copy is never written to the song's record, so the same song on Spotify keeps the album clock.

**Measured.** Fixtures in tests/fixtures/yt_captions:

| Video | Captions | Shift |
|---|---|---|
| Superhero (Metro Boomin & Future) | uploaded | +40.9s (first line 1.54 → 42.44; subtitle 42.57) |
| Shape of You | both | +6.3s, +7.4s from the album's 3:10 ("The club" heard 16.00 against LRCLIB 9.65) |
| Dreamflasher (Jane Remover) | automatic | +2.2s ("complete" heard 56.24 against LRCLIB 54.03) |

On the real window offscreen (scratch config and cache, no network), Superhero's lines showed on the video's clock with one more row (the interlude for the 42s intro), and without a video id they stayed as they were.

Not done: a video whose lyrics only come unsynced (Genius) gets nothing, though its uploaded subtitles could line-time it.

Tests: tests/test_yt_captions.py (14).
