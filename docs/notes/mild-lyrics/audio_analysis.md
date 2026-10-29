# `mild-lyrics/audio_analysis.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/audio_analysis.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The visualiser's readings worked out from audio: loudness, twelve pitch
> classes and beats, in the shape Spotify's analysis has (see Beat).
>
> `Analyser` takes samples as they are heard (live_audio); `analyse` takes a
> whole song, for Mild Lyrics' own player, which has the file. No Qt here.
> Notes: docs/notes/mild-lyrics/live_audio.md.

## The lyrics' offset heard from the song — 2026-10-26

`song_vocals` / `lyric_offset`, used by the window's `steer_own_offset` for songs in Mild
Lyrics' own player, which has the whole recording. The older estimate (`estimate_from` in
lyrics_gui) reads Spotify's analysis of the album, looks ±0.75s and trusts 0.25s at most;
hand corrections on own-player songs ran to 0.9-2.5s (community syncs, blends) besides the
many small ones (median 0.035s), so it could not reach the ones that mattered.

**Signal.** Stereo at 11025Hz, 1024-point frames every 128 samples. Per bin, centre =
|L+R|/2 - |L-R|/2 (clipped at 0): what is panned out drops, a mono file is all centre.
150-4000Hz, log, summed: `level`; its growth a row: `rise`.

**Score.** Two cross-correlations over ±6s, z-scored and added: the level (smoothed 0.25s,
less its own 8s average) against the sung spans, and the rise (less its 2s average) against
the vocal entries (`anchors_of`, Gaussian 0.05s).

**Gates** (all needed for `sure`): best shift past 0.3s; peak over the best 0.5s away from
it ≥1.5; over the best within 0.3s of zero ≥1.0 sd; each half of the lyrics peaks within
0.15s of it and over its own zero region ≥0.5 sd.
- The zero-region lead is what stops whole-bar aliases: Bat Country scored -2.86s (two bars
  at its tempo), with both halves agreeing, against a reference that is right.
- Within 0.3s nothing is used: on the release the answers scatter about ±0.15s by song
  (median +0.02), so a small reading would mostly add noise to a sync that is right.

**Bench.** The 17 held-out songs (~/mild-lyrics-archive/held-out wavs with bench/*.raw.json
reference word starts). The references were checked against the old sync model's
alignments: within ±0.15s wherever the model aligned cleanly, so 0 is the truth there. Each
song at ten known shifts (0 to ±4s, lyrics moved, which equals moving the audio) and under
another song's lyrics. Prototype: 40 of 170 sure, 0 wrong, 0 on wrong lyrics. Shipping code
(11025Hz, real anchors): 23 sure, 22 of 91 shifts past 0.3s found, 0 wrong, 0 on wrong
lyrics; remaining error after a correction is the same per-song ±0.15s. Peak ratios of the
wrong answers that passed every other gate were 1.25 and 1.34, the lowest right one 1.62.

Tried and dropped: harmonic/percussive median split (no better, costly); a ridge regression
on log-mel centre/side bands, leave-one-out (frame AUC 0.5-0.9, no better offsets: the sung
spans it learns from fill 90% of a rap song).

**Window.** Kept in `est_raw` as `own:<hand key>|<yt or url>` with a fingerprint of the
anchors (`lyric_fit`): other timings on screen are measured again from the kept voice rows,
without a second fetch. A hand offset wins; the 0 key clears it; nothing under memory use
minimal; not before 5s into the song. Info panel row "Heard". Bench scripts:
~/.claude/projects/-home-gc-mild-lyrics/memory/bench/offset/ (real.py is the shipping-code run).
