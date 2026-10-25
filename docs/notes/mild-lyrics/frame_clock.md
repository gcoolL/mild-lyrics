# `mild-lyrics/frame_clock.py`

## 2026-10-24 — `mono()`: perf_counter, not monotonic

The one elapsed-time clock, here since the 2026-10-24 cleanup; it used to be defined separately in lyrics_gui, renderers, frame_trace, live_audio and local_player, and the last two read `time.monotonic` -- live_audio's rows were then placed on the window's perf_counter clock by `Clock.position(t)`, two clocks in one subtraction on Windows before 3.13. Each module binds `mono` from here (`mono = FCK.mono`), so a test can still wind `L.mono` / `RD.mono`.

The reasoning, as it stood in lyrics_gui.mono's docstring:

This program's clock for how much time has passed.

NOT time.monotonic, and on Windows that is the difference between smooth
and not. Under CPython 3.12 and earlier, time.monotonic on Windows is
GetTickCount64, which moves in steps of 15.625ms -- so every reading of
elapsed time in this program was rounded down to the nearest sixteenth of
a second there, on a clock read sixty times a second to decide where a
word has been sung to and how far a spring has travelled.

Three things read it every frame and all three reach the eye. _frame asks
how much of the period is left, and against a 15.6ms grain asked the timer
for the wrong number in a fresh direction every frame -- measured at a
20ms period, the interval smeared from 6ms to 34ms around a 20ms peak, and
on perf_counter it lands in four buckets, 19 to 21, with nothing over 1.5x
the period. Clock.position carries the song forward from the last reading,
so the fill sweeping through a word advances in 15.6ms lurches. And
Amll._step takes the difference between two of these readings as the
timestep it integrates every spring in the column with, which comes out
15.6, 15.6, 15.6, 31.2 where it should have been a flat 20.

THE FRAME RATE IS NOT THE REFRESH RATE, and the difference decides how bad
that last one gets. retune_frames never runs above fps_cap whatever the
panel does -- and at the default cap of 60 that puts the period at 16.7ms
or longer, ALWAYS longer than the 15.625ms grain. A screen slower than the
cap only makes it longer still. That is why the step merely alternated
rather than stopping.

Raise --fps-cap past 64 and it stops. Once the period is shorter than the
grain, consecutive frames read the same tick and the step is zero -- a
frame the column does not move on at all. Over 2000 frames of Amll._step,
by the rate the frames are actually DRAWN at:

    50 fps   0.0% of frames a zero step     step 15.6-31.2ms
    60 fps   0.0%                           step 15.6-31.2ms
    75 fps  14.7%                           step  0.0-15.6ms
   120 fps  46.7%                           step  0.0-15.6ms
   144 fps  55.6%                           step  0.0-15.6ms
   240 fps  73.3%                           step  0.0-15.6ms

On perf_counter every one of those is a flat step at the period. So the
default cap is what keeps the frame rate out of the bottom four rows, and
anyone who had raised it to match a fast panel was in them.

perf_counter is QueryPerformanceCounter on Windows and the same
clock_gettime(CLOCK_MONOTONIC) that monotonic already is everywhere else,
so this is a Windows fix that changes nothing elsewhere. CPython 3.13
moved monotonic onto QPC too, which is why this was only ever felt on some
machines.

Used for EVERY elapsed-time reading in this program rather than only the
three that showed, because the danger in a half-done change is mixing two
clocks in one subtraction -- Clock.position differences `now` against a
stamp the transports wrote, and those are not the same lines of code. One
clock everywhere cannot be mixed. Nothing here is ever serialised, sent or
saved, so no reading outlives the process that took it.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/frame_clock.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> A window's animation, stepped once per refresh of the screen it is on.
>
> The same pacing LyricsView does for itself (see its _vsync_frame), made a
> thing a window can hold, for the TTML Editor. Two halves:
>
> When it steps. Where the platform paces frames -- Wayland, whose compositor
> answers QWindow.requestUpdate from its frame callback -- each step asks for
> the next, and so runs once per refresh. Everywhere else, and whenever the
> window is idle or hidden, a PreciseTimer re-armed against a deadline carried
> in float seconds. The timer alone was measured at 240Hz sending frames 6.5,
> 4, 3, 3ms apart to a panel that shows one every 4.17: right on average and
> wrong every frame, which reads as a vibration on anything moving.
>
> What time a step is for. `now()` is the frame's time, on the refresh grid --
> the last frame's plus a whole number of periods -- rather than whenever the
> callback happened to arrive, so everything read off it moves by the same
> amount every refresh. Never earlier than it has said before.

### `grid_step`

**line 35** — from the docstring, `def grid_step(ft, last_cb, now: float, period: float) -> tuple:`

> The time of the frame a callback arriving at `now` makes, and the
> callback to count the next one from: (frame time, last callback).
>
> Counted in whole refreshes from the gap since the LAST CALLBACK -- not
> from the last frame's time, which once it ran ahead of the wall clock
> read as no gap at all and was thrown back: measured in the editor at two
> refreshes a frame, a fifth of its frames stood still and the rest moved
> a fraction. At least one refresh a frame, so time never runs back; a
> period added or held back whenever the frame time strays from the wall
> clock, so it cannot wander off.
>
> Except a callback with no refresh behind it, which counts nothing and
> is not counted from. Qt answers a requestUpdate AT ONCE when no frame is
> in flight -- a step that drew nothing commits nothing, so the compositor
> owes no callback -- and counting each of those as a refresh ran the frame
> time away: measured on a paused window, 20,000 steps in its last second
> before going idle and the frame time 338s ahead, which on play put the
> song at its end. And however the count comes out, the frame time is
> pulled back to within a refresh and a half of the wall clock.

### `heard_refresh`

**line 59** — from the docstring, `def heard_refresh(gaps, rates, current: float) -> float | None:`

> The refresh the compositor is calling back at, where that is plainly
> not `current`; None where it agrees, or the gaps do not say.
>
> Qt's idea of the screen is not the compositor's. On Wayland a window
> knows nothing of where it is, only which outputs it has entered, and Qt
> names the one entered FIRST until the window has left it entirely; KWin
> sends the frame callbacks from the output holding most of the window.
> Dragged from a 60Hz panel mostly onto a 240Hz one, the window was called
> back 240 times a second while everything here -- the debug overlay, the
> frame grid, the check that gives up drawing ahead -- worked to 60. So
> the callbacks are listened to: `gaps` between them, `rates` of the
> screens there are.
>
> The gap taken is the mean of the middle half. Single callbacks wander
> 3.5-6.5ms apart at 240Hz, a late one followed by an early one, and a
> frame that missed its refresh waits a whole one more; the middle half
> leaves both tails out and averages what wobble is left.
>
> A screen whose period that gap is wins outright. Failing one, a gap
> SHORTER than the current screen's period means it cannot be that one --
> no compositor calls back faster than it refreshes -- and the slowest
> screen that could be is taken. A longer gap than the period, on its
> own, is only frames missing their refresh, and says nothing.

### `FrameClock.eventFilter` (comment)

**line 226** — before `return True`

> Ours, so it stops here. Let through, Qt's widget window
> answers a window's UpdateRequest by repainting the WHOLE
> top-level widget: measured in the editor, the backdrop at
> full window size, the line list and everything else on
> every frame, 70 times a second, for a step that had moved
> the playhead. What the step changed asked for its own
> repaint, and that goes the ordinary way.
