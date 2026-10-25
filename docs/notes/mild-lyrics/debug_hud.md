# `mild-lyrics/debug_hud.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/debug_hud.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The debug overlay: what the window is doing, drawn in a corner of it.
>
> Three levels past off, each the one before it with more added:
>
>     minimal    the frame rate, what a frame costs, and how long this song's
>                lyrics took and whose they are
>     standard   every source the walk asked, what each one said and how long
>                it took; the phases of the load; the player and the offset
>     full       the frame timer's own target, the caches, memory and threads,
>                the cover's load time, startup, recent loads, and what the
>                look-ahead had already fetched before the song came on
>
> Two halves, on two sides of a thread line. TRACE is filled in by the fetcher
> and by the walk's own threads as a load happens -- it is a lock and a few
> dicts, and costs nothing anyone could measure next to the network request
> each entry stands for, so it records whether the overlay is up or not and a
> song that is already playing has its story when the overlay is turned on.
> Hud is the GUI-thread half: it times the paints and draws the box, and does
> nothing at all while the level is off.
>
> The box is drawn into a pixmap four times a second and blitted every frame,
> so the overlay's own cost stays out of the paint cost it reports.

### `Trace`

**line 85** — from the docstring, `class Trace:`

> What each song's load did, written from any thread.
>
> A load is begun and ended by the fetcher. Between the two, every provider
> the walk asks reports in through `asked` -- on the walk's own threads,
> which is why everything here is under one lock. Asks that land for a song
> with no load begun are the look-ahead warming it; they are kept apart, in
> `ahead`, so the load that follows can say its answer was already on disk
> rather than look as if it asked nobody.
