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

Beside these there is one note that is not a mirror of anything:
[TODO.md](TODO.md), which is the list of things reported and not yet fixed,
with what is known about each and what would settle it.

| module | notes | entries | of those, earlier |
| --- | --- | ---: | ---: |
| `aligner/lyrics_gui.py` | [aligner/lyrics_gui.md](aligner/lyrics_gui.md) | 992 | 530 |
| `aligner/lyric_sources.py` | [aligner/lyric_sources.md](aligner/lyric_sources.md) | 372 | 145 |
| `aligner/local_align.py` | [aligner/local_align.md](aligner/local_align.md) | 278 | 273 |
| `aligner/renderers.py` | [aligner/renderers.md](aligner/renderers.md) | 170 |  |
| `aligner/spicy_lyrics.py` | [aligner/spicy_lyrics.md](aligner/spicy_lyrics.md) | 96 | 58 |
| `editor/app.py` | [editor/app.md](editor/app.md) | 83 | 29 |
| `editor/lineview.py` | [editor/lineview.md](editor/lineview.md) | 58 | 36 |
| `aligner/review.py` | [aligner/review.md](aligner/review.md) | 50 |  |
| `editor/waveform.py` | [editor/waveform.md](editor/waveform.md) | 41 | 28 |
| `aligner/genius_roman.py` | [aligner/genius_roman.md](aligner/genius_roman.md) | 39 | 29 |
| `editor/ops.py` | [editor/ops.md](editor/ops.md) | 37 | 11 |
| `aligner/run_pipeline.py` | [aligner/run_pipeline.md](aligner/run_pipeline.md) | 35 |  |
| `aligner/macplayer.py` | [aligner/macplayer.md](aligner/macplayer.md) | 28 |  |
| `editor/vocalmap.py` | [editor/vocalmap.md](editor/vocalmap.md) | 26 |  |
| `editor/player.py` | [editor/player.md](editor/player.md) | 21 | 10 |
| `editor/model.py` | [editor/model.md](editor/model.md) | 18 | 11 |
| `aligner/spotify_dom.py` | [aligner/spotify_dom.md](aligner/spotify_dom.md) | 17 | 10 |
| `editor/theme.py` | [editor/theme.md](editor/theme.md) | 17 | 16 |
| `editor/sources.py` | [editor/sources.md](editor/sources.md) | 16 | 8 |
| `aligner/eval_sources.py` | [aligner/eval_sources.md](aligner/eval_sources.md) | 13 |  |
| `aligner/doctor.py` | [aligner/doctor.md](aligner/doctor.md) | 12 | 4 |
| `editor/autotime.py` | [editor/autotime.md](editor/autotime.md) | 12 | 10 |
| `aligner/build_dataset.py` | [aligner/build_dataset.md](aligner/build_dataset.md) | 10 |  |
| `editor/start.py` | [editor/start.md](editor/start.md) | 10 | 6 |
| `aligner/eval_blends.py` | [aligner/eval_blends.md](aligner/eval_blends.md) | 9 |  |
| `editor/keys.py` | [editor/keys.md](editor/keys.md) | 9 | 4 |
| `aligner/align_song.py` | [aligner/align_song.md](aligner/align_song.md) | 8 |  |
| `aligner/bench.py` | [aligner/bench.md](aligner/bench.md) | 8 |  |
| `editor/link.py` | [editor/link.md](editor/link.md) | 8 | 7 |
| `editor/syllables.py` | [editor/syllables.md](editor/syllables.md) | 8 | 6 |
| `aligner/caches.py` | [aligner/caches.md](aligner/caches.md) | 7 | 4 |
| `editor/syncbar.py` | [editor/syncbar.md](editor/syncbar.md) | 7 |  |
| `aligner/language.py` | [aligner/language.md](aligner/language.md) | 6 |  |
| `aligner/ttml.py` | [aligner/ttml.md](aligner/ttml.md) | 5 |  |
| `aligner/sweep.py` | [aligner/sweep.md](aligner/sweep.md) | 4 |  |
| `aligner/learn.py` | [aligner/learn.md](aligner/learn.md) | 3 |  |
| `editor/ribbon.py` | [editor/ribbon.md](editor/ribbon.md) | 3 |  |
| `editor/settings.py` | [editor/settings.md](editor/settings.md) | 3 |  |
| `editor/wordsplit.py` | [editor/wordsplit.md](editor/wordsplit.md) | 3 |  |
| `aligner/copytest.py` | [aligner/copytest.md](aligner/copytest.md) | 2 |  |
| `aligner/eval_aligner.py` | [aligner/eval_aligner.md](aligner/eval_aligner.md) | 2 |  |
| `editor/backups.py` | [editor/backups.md](editor/backups.md) | 1 |  |
| `aligner/offload.py` | [aligner/offload.md](aligner/offload.md) | 7 |  |

2554 entries across 43 modules.
