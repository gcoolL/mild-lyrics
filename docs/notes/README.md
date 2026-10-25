# Notes

The prose that used to sit in `#` comments in the code, moved out and
kept here. Nothing was discarded.

Each note mirrors its module's path, and each entry is anchored to the
line it came from, the enclosing function or class, and the line of code
it was written against — so a comment can be read back to where it lived.

**Line numbers are the ones the code had when the comments were lifted.**
They drift as the code changes; the enclosing name and the quoted line of
code are the durable part of the anchor.

There have been five lifts. The newest, on 2026-10-25, took the long
docstrings: every one over six lines was cut to one to three, and its full
text moved under **Lift — 2026-10-25** in the module's note, filed by the
function's qualified name (`### \`Class.method\``) with the line it now sits
on. Comment blocks of six lines or more went the same way, as
`### ... (comment)` entries. So the long version of any docstring is found by
searching the module's note for the function's name. Before that, on
2026-10-11, the comments PR #2 added went under **Lift — 2026-10-11**. Below it, the 2026-09-26 one sits under its own
**Lift** heading; below that, under **Lift — 2026-09-17**, are the ones taken that day, and
under an **Earlier lift** heading at the foot of the note are the ones taken
on 2026-08-23, left exactly as they were written. Each set carries the line
numbers its own day's code had. The older ones were not
re-anchored, because the code they were written against is mostly gone —
re-pointing them at today's lines would be a guess dressed up as a
citation. Nothing from either lift was discarded.

What stayed in the code:

- **short docstrings** -- one to three lines, saying what a function does
  and the one fact that is not obvious. Docstrings of four to six lines
  were left as they were. The module docstrings that are `--help` text
  (`doctor.py`, `spotify_dom.py`, `spicy_lyrics.py`, `genius_roman.py`,
  `lyrics_gui.py`, `mild-setup.py`) stayed whole; `caches.py`, `review.py`
  and `editor/app.py` print only the first line, which was kept.
- **tool directives** — `noqa`, `pragma`, `type:`, shebangs, coding lines.
  They instruct other programs; removing them changes what those do.
- **section separators** — `# ---- painting ----`. They are navigation,
  and mean nothing away from the code they divide.

Beside these there are three notes that are not mirrors of anything:
[TODO.md](TODO.md), which is the list of things reported and not yet fixed,
with what is known about each and what would settle it;
[closed.md](closed.md), the entries taken off that list, word for word --
fixes kept for what they measured, and suspects measured and refused; and
[android-remaining.md](android-remaining.md), which is what the Android port
has not reached yet — the player as an actual player, the editor, and the
debts and extras around them.

| module | notes | entries | of those, earlier |
| --- | --- | ---: | ---: |
| `mild-lyrics/lyrics_gui.py` | [mild-lyrics/lyrics_gui.md](mild-lyrics/lyrics_gui.md) | 1111 | 530 |
| `mild-lyrics/lyric_sources.py` | [mild-lyrics/lyric_sources.md](mild-lyrics/lyric_sources.md) | 410 | 145 |
| `mild-lyrics/local_align.py` | [mild-lyrics/local_align.md](mild-lyrics/local_align.md) | 278 | 273 |
| `mild-lyrics/renderers.py` | [mild-lyrics/renderers.md](mild-lyrics/renderers.md) | 214 |  |
| `mild-lyrics/spicy_lyrics.py` | [mild-lyrics/spicy_lyrics.md](mild-lyrics/spicy_lyrics.md) | 121 | 58 |
| `editor/app.py` | [editor/app.md](editor/app.md) | 90 | 29 |
| `editor/lineview.py` | [editor/lineview.md](editor/lineview.md) | 62 | 36 |
| `mild-lyrics/review.py` | [mild-lyrics/review.md](mild-lyrics/review.md) | 65 |  |
| `editor/waveform.py` | [editor/waveform.md](editor/waveform.md) | 41 | 28 |
| `mild-lyrics/genius_roman.py` | [mild-lyrics/genius_roman.md](mild-lyrics/genius_roman.md) | 39 | 29 |
| `editor/ops.py` | [editor/ops.md](editor/ops.md) | 38 | 11 |
| `mild-lyrics/macplayer.py` | [mild-lyrics/macplayer.md](mild-lyrics/macplayer.md) | 28 |  |
| `editor/vocalmap.py` | [editor/vocalmap.md](editor/vocalmap.md) | 26 |  |
| `editor/player.py` | [editor/player.md](editor/player.md) | 21 | 10 |
| `editor/model.py` | [editor/model.md](editor/model.md) | 18 | 11 |
| `mild-lyrics/spotify_dom.py` | [mild-lyrics/spotify_dom.md](mild-lyrics/spotify_dom.md) | 17 | 10 |
| `editor/theme.py` | [editor/theme.md](editor/theme.md) | 17 | 16 |
| `editor/sources.py` | [editor/sources.md](editor/sources.md) | 16 | 8 |
| `mild-lyrics/doctor.py` | [mild-lyrics/doctor.md](mild-lyrics/doctor.md) | 12 | 4 |
| `editor/start.py` | [editor/start.md](editor/start.md) | 10 | 6 |
| `editor/keys.py` | [editor/keys.md](editor/keys.md) | 9 | 4 |
| `editor/link.py` | [editor/link.md](editor/link.md) | 8 | 7 |
| `editor/syllables.py` | [editor/syllables.md](editor/syllables.md) | 9 | 6 |
| `mild-lyrics/caches.py` | [mild-lyrics/caches.md](mild-lyrics/caches.md) | 7 | 4 |
| `editor/syncbar.py` | [editor/syncbar.md](editor/syncbar.md) | 7 |  |
| `mild-lyrics/language.py` | [mild-lyrics/language.md](mild-lyrics/language.md) | 7 |  |
| `editor/ribbon.py` | [editor/ribbon.md](editor/ribbon.md) | 3 |  |
| `editor/settings.py` | [editor/settings.md](editor/settings.md) | 3 |  |
| `editor/wordsplit.py` | [editor/wordsplit.md](editor/wordsplit.md) | 4 |  |
| `editor/backups.py` | [editor/backups.md](editor/backups.md) | 1 |  |
| `mild-lyrics/offload.py` | [mild-lyrics/offload.md](mild-lyrics/offload.md) | 7 |  |

2445 entries across 31 modules. The notes for the scripts moved out to ~/mild-lyrics-archive (the aligner and its evaluations, editor/autotime) went with them, to its notes/.
