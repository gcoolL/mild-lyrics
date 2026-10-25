# `editor/gpu.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/gpu.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The editor's moving parts drawn on the GPU -- see mild-lyrics/gpu_canvas.
>
> Three widgets repaint while the song plays: the waveform under its playhead,
> the sync bar in drag sync, and the line list in preview. In the new look
> all three are glass over the painted backdrop, so every raster repaint of
> any of them also repainted the backdrop beneath -- four full-window washes,
> clipped to the widget. Measured at 1741x880 in preview, each refresh cost
> the list 5.4ms, the waveform 3.3 and the backdrop 2.0: about 90 frames a
> second at most, where the editor asked for thirty.
>
> Each gets a GL canvas laid over it instead. A canvas is composited over the
> window rather than painted into it, so the backdrop under a widget is
> painted once and blended through, and the widget's own drawing runs on the
> GPU. The widgets' paint code is unchanged: `paint_onto(p)` is what their
> paintEvent always did, handed the canvas's painter.
>
> The setting is the editor's "gpu" (auto/on/off), as for the player.

### `relay`

**line 58** — from the docstring, `def relay(win: QWidget) -> None:`

> The setting changed with `win` up: its canvases come off, or go on.
>
> Off is give_up for each, which is what a canvas that never painted
> already does. On cannot just lay them: a canvas added to a window on
> screen never reaches it on KWin Wayland (see lay_over), so the native
> window is thrown away and made again with them already in it -- what
> the player's _remake_window does for its own canvas. The editor's frame
> clock follows the new handle by itself (FrameClock._hook).

### `_Overlay`

**line 105** — from the docstring, `class _Overlay(QObject):`

> Watches a panel laid over the page -- the settings drawer, the toast.
>
> A canvas is composited over the whole window (WA_AlwaysStackOnTop, so
> the glass under it shows through), which puts it over every sibling as
> well: the drawer slid in under the waveform and the list, and the toast
> under the list, with their own drawing showing through the gaps. So
> while a panel is up, each canvas it touches steps aside.

### `GlViewport`

**line 162** — from the docstring, `class GlViewport(QWidget):`

> A scroll area's viewport whose repaints go to the canvas over it.
>
> And which steps aside while it has a line edit in it -- the list's
> word and reading boxes open right on the rows -- because a canvas is
> composited over everything in the window, children included, and would
> hide the box being typed in. The CPU draws the list until it closes.
