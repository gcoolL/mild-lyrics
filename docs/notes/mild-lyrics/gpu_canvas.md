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
