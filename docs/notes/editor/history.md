# `editor/history.py`

## Why old undo steps are pickled (2026-10-17)

Measured with a headless tap bench (a thread posting "key presses" at the true
syllable starts of `RapGod_final.ttml`, the editor's own `fire()` stamping
them from an exact stand-in clock, every event dispatch and every GC pass
timed). Dense stretch from 64 s, 60 s, 311 taps, alternating runs:

|                         | 80 live clones | 8 live + pickled |
|-------------------------|----------------|------------------|
| tracked objects at end  | 242k           | 76k              |
| worst gen-2 GC pause    | 43-46 ms (74 once) | 18-22 ms     |
| worst `fire()`          | 44-46 ms       | 24-28 ms         |
| median `fire()`         | 3.0 ms         | 5.4 ms           |

Each clone of a long song is ~2.3k GC-tracked objects; eighty of them made
every full collection walk ~185k extra objects. A key that lands during one
waits it out, and the stamp is read when `fire()` runs, so it is stamped that
late. Pickled bytes are not tracked. The median cost (+2.4 ms per tap) is
after the position has been read, so it moves no stamp.

Collab edits every snapshot in place (`_remote`); a pickled one keeps the ops
in `later` and applies them in order when it is taken back.

Stamp lateness itself, outside GC pauses: median 0.2 ms, p99 6-7 ms, worst
~10-25 ms, all of it a key waiting behind a paint or a push. Back-dating from
the key event's timestamp was considered and left: QShortcut does not carry
it, and the error is under a person's own tap spread. The constant part is
what Tap lag is for.
