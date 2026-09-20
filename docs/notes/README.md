# Notes

The prose that used to sit in `#` comments in the code, moved out and
kept here. Nothing was discarded.

Each note mirrors its module's path, and each entry is anchored to the
line it came from, the enclosing function or class, and the line of code
it was written against — so a comment can be read back to where it lived.

**Line numbers are the ones the code had when the comments were lifted.**
They drift as the code changes; the enclosing name and the quoted line of
code are the durable part of the anchor.

There have been two lifts. The entries at the top of a note are the ones
taken on 2026-09-17, and their line numbers are that day's; under an
**Earlier lift** heading at the foot of the note are the ones taken on
2026-08-23, left exactly as they were written. The older ones were not
re-anchored, because the code they were written against is mostly gone —
re-pointing them at today's lines would be a guess dressed up as a
citation. Nothing from either lift was discarded.

What stayed in the code:

- **docstrings**, untouched — several are read at runtime (`doctor.py`
  and `caches.py` both feed `__doc__` to `argparse`)
- **tool directives** — `noqa`, `pragma`, `type:`, shebangs, coding lines.
  They instruct other programs; removing them changes what those do.
- **section separators** — `# ---- painting ----`. They are navigation,
  and mean nothing away from the code they divide.

Beside these there are two notes that are not mirrors of anything:
[TODO.md](TODO.md), which is the list of things reported and not yet fixed,
with what is known about each and what would settle it; and
[android-remaining.md](android-remaining.md), which is what the Android port
has not reached yet — the player as an actual player, the editor, and the
debts and extras around them.

| module | notes | entries | of those, earlier |
| --- | --- | ---: | ---: |
| `mild-lyrics/lyrics_gui.py` | [mild-lyrics/lyrics_gui.md](mild-lyrics/lyrics_gui.md) | 992 | 530 |
| `mild-lyrics/lyric_sources.py` | [mild-lyrics/lyric_sources.md](mild-lyrics/lyric_sources.md) | 372 | 145 |
| `mild-lyrics/local_align.py` | [mild-lyrics/local_align.md](mild-lyrics/local_align.md) | 278 | 273 |
| `mild-lyrics/renderers.py` | [mild-lyrics/renderers.md](mild-lyrics/renderers.md) | 170 |  |
| `mild-lyrics/spicy_lyrics.py` | [mild-lyrics/spicy_lyrics.md](mild-lyrics/spicy_lyrics.md) | 96 | 58 |
| `editor/app.py` | [editor/app.md](editor/app.md) | 83 | 29 |
| `editor/lineview.py` | [editor/lineview.md](editor/lineview.md) | 58 | 36 |
| `mild-lyrics/review.py` | [mild-lyrics/review.md](mild-lyrics/review.md) | 50 |  |
| `editor/waveform.py` | [editor/waveform.md](editor/waveform.md) | 41 | 28 |
| `mild-lyrics/genius_roman.py` | [mild-lyrics/genius_roman.md](mild-lyrics/genius_roman.md) | 39 | 29 |
| `editor/ops.py` | [editor/ops.md](editor/ops.md) | 37 | 11 |
| `mild-lyrics/run_pipeline.py` | [mild-lyrics/run_pipeline.md](mild-lyrics/run_pipeline.md) | 35 |  |
| `mild-lyrics/macplayer.py` | [mild-lyrics/macplayer.md](mild-lyrics/macplayer.md) | 28 |  |
| `editor/vocalmap.py` | [editor/vocalmap.md](editor/vocalmap.md) | 26 |  |
| `editor/player.py` | [editor/player.md](editor/player.md) | 21 | 10 |
| `editor/model.py` | [editor/model.md](editor/model.md) | 18 | 11 |
| `mild-lyrics/spotify_dom.py` | [mild-lyrics/spotify_dom.md](mild-lyrics/spotify_dom.md) | 17 | 10 |
| `editor/theme.py` | [editor/theme.md](editor/theme.md) | 17 | 16 |
| `editor/sources.py` | [editor/sources.md](editor/sources.md) | 16 | 8 |
| `mild-lyrics/eval_sources.py` | [mild-lyrics/eval_sources.md](mild-lyrics/eval_sources.md) | 13 |  |
| `mild-lyrics/doctor.py` | [mild-lyrics/doctor.md](mild-lyrics/doctor.md) | 12 | 4 |
| `editor/autotime.py` | [editor/autotime.md](editor/autotime.md) | 12 | 10 |
| `mild-lyrics/build_dataset.py` | [mild-lyrics/build_dataset.md](mild-lyrics/build_dataset.md) | 10 |  |
| `editor/start.py` | [editor/start.md](editor/start.md) | 10 | 6 |
| `mild-lyrics/eval_blends.py` | [mild-lyrics/eval_blends.md](mild-lyrics/eval_blends.md) | 9 |  |
| `editor/keys.py` | [editor/keys.md](editor/keys.md) | 9 | 4 |
| `mild-lyrics/align_song.py` | [mild-lyrics/align_song.md](mild-lyrics/align_song.md) | 8 |  |
| `mild-lyrics/bench.py` | [mild-lyrics/bench.md](mild-lyrics/bench.md) | 8 |  |
| `editor/link.py` | [editor/link.md](editor/link.md) | 8 | 7 |
| `editor/syllables.py` | [editor/syllables.md](editor/syllables.md) | 8 | 6 |
| `mild-lyrics/caches.py` | [mild-lyrics/caches.md](mild-lyrics/caches.md) | 7 | 4 |
| `editor/syncbar.py` | [editor/syncbar.md](editor/syncbar.md) | 7 |  |
| `mild-lyrics/language.py` | [mild-lyrics/language.md](mild-lyrics/language.md) | 6 |  |
| `mild-lyrics/ttml.py` | [mild-lyrics/ttml.md](mild-lyrics/ttml.md) | 5 |  |
| `mild-lyrics/sweep.py` | [mild-lyrics/sweep.md](mild-lyrics/sweep.md) | 4 |  |
| `mild-lyrics/learn.py` | [mild-lyrics/learn.md](mild-lyrics/learn.md) | 3 |  |
| `editor/ribbon.py` | [editor/ribbon.md](editor/ribbon.md) | 3 |  |
| `editor/settings.py` | [editor/settings.md](editor/settings.md) | 3 |  |
| `editor/wordsplit.py` | [editor/wordsplit.md](editor/wordsplit.md) | 3 |  |
| `mild-lyrics/copytest.py` | [mild-lyrics/copytest.md](mild-lyrics/copytest.md) | 2 |  |
| `mild-lyrics/eval_aligner.py` | [mild-lyrics/eval_aligner.md](mild-lyrics/eval_aligner.md) | 2 |  |
| `editor/backups.py` | [editor/backups.md](editor/backups.md) | 1 |  |
| `mild-lyrics/offload.py` | [mild-lyrics/offload.md](mild-lyrics/offload.md) | 7 |  |

2554 entries across 43 modules.
