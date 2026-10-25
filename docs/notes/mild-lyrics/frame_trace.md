# `mild-lyrics/frame_trace.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/frame_trace.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> A per-frame record of the player's pacing, for reading afterwards.
>
> Off unless MILD_FRAME_TRACE names a file. Then every frame step, paint and
> GPU buffer swap is stamped on the mono clock, with what the window was at
> the time -- fullscreen or not, its size, CPU or GPU -- and the lot is written
> to that file as JSON lines when the program exits. The debug overlay gives
> averages over a second; a slipped refresh, two frames shown in one, or a
> paint that started late is only visible frame by frame, which is what this
> keeps.
>
> Cheap enough to leave hooked: off, every hook is one attribute test.
