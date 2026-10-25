# `mild-lyrics/gpu_canvas.py`

## 2026-10-16 — Windows: no wait for vsync, and a swap that freezes gives up

**Reported** from somebody else's Windows PC with GPU drawing "on": slow, or
crashing, and while recording the window freezes until they tab out. Nothing
else is known about the machine.

**What the code did there.** The canvas never set a swap interval, so Windows
presented with the default of 1, and its OpenGL `SwapBuffers` blocks the GUI
thread until vblank. `frameSwapped`, which the player paints its next frame
from (`_ahead_frame`), only fires after that call returns (Qt's QOpenGLWidget
docs). Qt's own multi-window manual test (`tests/manual/qopenglwindow/
multiwindow`) records about 20fps on Intel's opengl32 driver with blocking
swaps, and 60 with interval 0. Screen recorders hook OpenGL presentation, and
reports of OpenGL apps freezing under capture until focus moves exist. None
gives a confirmed fix.

**Two changes, kept apart on purpose:**

- `no_vsync_wait()` asks for swap interval 0 on Windows (`NO_VSYNC_WAIT`)
  through the default format, before the QApplication in both the player and
  the editor, and on the canvas's own format. The window paces itself with
  its timer there. This is the guess at the mechanism.
- Independent of that guess, every canvas times its swap: paint end to
  `frameSwapped`. Over `STALL_S` (1s) with the window showing, it sets `why`
  and emits `failed`, and the CPU draws until restart, with the reason in a
  toast and in the follow log ("gpu fell-back"). A hide or a minimise in
  between voids the measurement. Off on the verified platforms (`TESTED`,
  Wayland), where a long legitimate wait must not cost a working GPU.

Neither has run on Windows. Offscreen Qt does not composite, so no swap ever
completes here (one paint, no `frameSwapped`). `tests/test_gpu_stall.py`
drives the bookkeeping with a fake clock. To confirm on that PC: the debug
overlay's fps row with GPU on, then a recording. A freeze should now last
about a second and end with "GPU drawing froze for Ns — drawing on the CPU
until restart". If it freezes for good instead, the GUI thread is not coming
back from the swap at all, and only "off" helps there.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/gpu_canvas.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The window drawn on the GPU.
>
> Every frame of the player is QPainter calls, and on the raster engine every
> one of them is the CPU filling pixels: at 1920x1080 a frame cost about 11ms,
> which is 90 frames a second on a 240Hz panel however the timer is set. The
> same calls made on a QOpenGLWidget go to Qt's OpenGL paint engine instead --
> a cached picture becomes a texture drawn as a quad, text comes from a glyph
> atlas, a scaled or sub-pixel blit is the texture unit's filtering -- so the
> drawing code does not change and the pixels move to the GPU.
>
> The canvas is a child laid over the whole window, not the window itself.
> The window keeps everything it is: its translucency, the native surface
> apply_clear throws away and makes again, the backdrop, every event -- the
> canvas is see-through to the mouse and never takes focus, so input lands on
> the window exactly as before. The window just stops painting and hands its
> painter to the canvas instead; see LyricsView.paint_onto.
>
> What it does not move is the drawing INTO pictures -- the scene, the
> visualiser's layer, the cached lines -- which is still raster, onto
> QPixmaps, and then uploaded. Those are cached, or small, or both.

### `GpuCanvas`

**line 94** — from the docstring, `class GpuCanvas(QOpenGLWidget):`

> A widget's paint, on a GL surface laid over all of it.
>
> `view` is the widget covered; `paint(p)` draws into the canvas's
> painter and ends it, and defaults to `view.paint_onto`. The canvas
> keeps the view's size by itself. The TTML Editor lays one over a
> widget that only hosts the drawing -- a scroll area's viewport -- and
> hands the paint in from the scroll area; see editor/gpu.py.

### `GpuCanvas._paint_straight`

**line 223** — from the docstring, `def _paint_straight(self) -> None:`

> Paint into a multisampled framebuffer of our own, resolve it,
> and copy it into the widget's through _FRAG.
>
> Our own because the widget's is multisampled and cannot be read
> from, and kept between frames because a partial canvas repaints
> only its dirty rect into it -- the rest is the last frame's, as
> PartialUpdate keeps it on the direct path. The whole of it is
> copied over every frame: a quad is nothing to the GPU.

### `GpuCanvas.__init__` (comment)

**line 103** — before `self.straight = straight`

> With `straight`, the frame is handed over with straight alpha.
> QPainter paints premultiplied, but Qt composites a
> QOpenGLWidget into the window as straight alpha, so whatever
> is see-through is multiplied by its alpha twice: the TTML
> Editor's glass -- chips at alpha 20, row rules, the waveform's
> grid -- all but vanished on screen while every FBO grab here
> looked right. The player's canvas is opaque where it matters
> and keeps the direct path. See _paint_straight.
