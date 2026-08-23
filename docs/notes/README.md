# Notes

The prose that used to sit in `#` comments in the code, moved out and
kept here. Nothing was discarded.

Each note mirrors its module's path, and each entry is anchored to the
line it came from, the enclosing function or class, and the line of code
it was written against — so a comment can be read back to where it lived.

**Line numbers are the ones the code had when the comments were lifted.**
They drift as the code changes; the enclosing name and the quoted line of
code are the durable part of the anchor.

What stayed in the code:

- **docstrings**, untouched — several are read at runtime (`doctor.py`
  and `caches.py` both feed `__doc__` to `argparse`)
- **tool directives** — `noqa`, `pragma`, `type:`, shebangs, coding lines.
  They instruct other programs; removing them changes what those do.
- **section separators** — `# ---- painting ----`. They are navigation,
  and mean nothing away from the code they divide.

| module | notes | entries |
| --- | --- | ---: |
| `aligner/lyrics_gui.py` | [aligner/lyrics_gui.md](aligner/lyrics_gui.md) | 530 |
| `aligner/local_align.py` | [aligner/local_align.md](aligner/local_align.md) | 273 |
| `aligner/lyric_sources.py` | [aligner/lyric_sources.md](aligner/lyric_sources.md) | 145 |
| `aligner/spicy_lyrics.py` | [aligner/spicy_lyrics.md](aligner/spicy_lyrics.md) | 58 |
| `editor/lineview.py` | [editor/lineview.md](editor/lineview.md) | 36 |
| `aligner/run_pipeline.py` | [aligner/run_pipeline.md](aligner/run_pipeline.md) | 35 |
| `aligner/genius_roman.py` | [aligner/genius_roman.md](aligner/genius_roman.md) | 29 |
| `editor/app.py` | [editor/app.md](editor/app.md) | 29 |
| `editor/waveform.py` | [editor/waveform.md](editor/waveform.md) | 28 |
| `editor/theme.py` | [editor/theme.md](editor/theme.md) | 16 |
| `editor/model.py` | [editor/model.md](editor/model.md) | 11 |
| `editor/ops.py` | [editor/ops.md](editor/ops.md) | 11 |
| `aligner/build_dataset.py` | [aligner/build_dataset.md](aligner/build_dataset.md) | 10 |
| `aligner/spotify_dom.py` | [aligner/spotify_dom.md](aligner/spotify_dom.md) | 10 |
| `editor/autotime.py` | [editor/autotime.md](editor/autotime.md) | 10 |
| `editor/player.py` | [editor/player.md](editor/player.md) | 10 |
| `aligner/align_song.py` | [aligner/align_song.md](aligner/align_song.md) | 8 |
| `aligner/bench.py` | [aligner/bench.md](aligner/bench.md) | 8 |
| `editor/sources.py` | [editor/sources.md](editor/sources.md) | 8 |
| `editor/link.py` | [editor/link.md](editor/link.md) | 7 |
| `editor/start.py` | [editor/start.md](editor/start.md) | 6 |
| `editor/syllables.py` | [editor/syllables.md](editor/syllables.md) | 6 |
| `aligner/ttml.py` | [aligner/ttml.md](aligner/ttml.md) | 5 |
| `aligner/caches.py` | [aligner/caches.md](aligner/caches.md) | 4 |
| `aligner/doctor.py` | [aligner/doctor.md](aligner/doctor.md) | 4 |
| `aligner/sweep.py` | [aligner/sweep.md](aligner/sweep.md) | 4 |
| `editor/keys.py` | [editor/keys.md](editor/keys.md) | 4 |
| `aligner/learn.py` | [aligner/learn.md](aligner/learn.md) | 3 |
| `editor/ribbon.py` | [editor/ribbon.md](editor/ribbon.md) | 3 |
| `editor/wordsplit.py` | [editor/wordsplit.md](editor/wordsplit.md) | 3 |
| `aligner/copytest.py` | [aligner/copytest.md](aligner/copytest.md) | 2 |
| `aligner/eval_aligner.py` | [aligner/eval_aligner.md](aligner/eval_aligner.md) | 2 |
| `editor/backups.py` | [editor/backups.md](editor/backups.md) | 1 |

1319 entries across 33 modules.
