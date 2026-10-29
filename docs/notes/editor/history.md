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

## Through the real key path (2026-10-26)

The same bench with each tap sent as a real `G` press through the window
(`QTest.keyClick` on the QWindow: shortcut map, `Keys._fire`, `fire`) instead
of calling `fire()`: 68 taps over 25 s, stamp late median 0.2 ms, p99 4.9 ms,
written starts against truth median +0.2 ms. With Tap lag at 60 ms the
written starts are 59.7 ms early, which is the box and nothing else. The
shortcut dispatch adds no offset of its own.

The file clock under it (`LocalPlayer`, Qt run with no audio output so the
media goes on Qt's own timer): readings every 50 ms, our smoothed clock
within ±0.2 ms of Qt's line, and 37 ms held after a seek before it moves.
Not measured: Qt's position against the sound actually leaving the speakers
(sink and device latency); that needs a real output.

## Lift — 2026-10-25

Docstrings shortened in `editor/history.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Undo snapshots the garbage collector does not have to walk.
>
> The newest LIVE stay as documents; older ones are kept as pickled bytes.
> Eighty live copies of a long song are ~185k objects, and every full
> collection walked them all: 40-75 ms pauses while tapping. See
> docs/notes/editor/history.md.
