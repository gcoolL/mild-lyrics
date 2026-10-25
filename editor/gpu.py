"""The editor's moving parts (waveform, sync bar, line list) drawn on GL
canvases laid over them; see mild-lyrics/gpu_canvas. Setting "gpu"."""
from __future__ import annotations

import weakref

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect
from PyQt6.QtWidgets import QLineEdit, QWidget

from . import keys as K  # first: it puts mild-lyrics/ on the path

import gpu_canvas as GC  # noqa: E402  (mild-lyrics/gpu_canvas.py)


def mode() -> str:
    got = str(K.config().get("gpu", "auto"))
    return got if got in GC.MODES else "auto"


def wanted() -> bool:
    return GC.GpuCanvas is not None and GC.wanted(mode())


def live(canvas) -> bool:
    """Whether a widget's drawing is going to this canvas right now."""
    return canvas is not None and canvas.isVisibleTo(canvas.parentWidget())


def lay_over(view, paint=None, owner=None, partial: bool = False):
    """A canvas over `view`, or None where the GPU is not wanted. Made with
    the widget, before the window is shown -- a QOpenGLWidget added to a
    window that is already up never reaches the screen on KWin Wayland.

    How to lay it is kept on the owner either way, so the setting can be
    changed with the window up -- see relay."""
    owner = owner or view
    owner._gpu_lay = (weakref.ref(view), paint, partial)
    _owners.add(owner)
    if not wanted():
        return None
    # Straight alpha: the editor's widgets are glass, mostly see-through,
    # and see-through is what Qt's compositing gets wrong -- see GpuCanvas.
    canvas = GC.GpuCanvas(view, paint, owner, partial=partial, straight=True)
    canvas.aside = set()
    canvas.failed.connect(lambda: give_up(owner))
    _canvases.add(canvas)
    return canvas


# Every canvas laid, every widget that could have one, and every panel that
# can come up over one.
_canvases: "weakref.WeakSet" = weakref.WeakSet()
_owners: "weakref.WeakSet" = weakref.WeakSet()
_overlays: list = []


def relay(win: QWidget) -> None:
    """The setting changed with `win` up. Off gives each canvas up; on remakes
    the native window with them in it, since KWin never shows one added
    later."""
    mine = []
    for owner in list(_owners):
        try:
            if owner.window() is win:
                mine.append(owner)
        except RuntimeError:                        # its C++ side is gone
            continue
    if not wanted():
        for owner in mine:
            if owner.gl_canvas is not None:
                give_up(owner)
        return
    todo = [o for o in mine if o.gl_canvas is None]
    if not todo:
        return
    shown, full, maxed = win.isVisible(), win.isFullScreen(), win.isMaximized()
    geo = win.normalGeometry() if (full or maxed) else win.geometry()
    win.destroy()
    for owner in todo:
        ref, paint, partial = owner._gpu_lay
        view = ref()
        if view is not None:
            owner.gl_canvas = lay_over(view, paint, owner, partial)
    win.create()
    win.setGeometry(geo)
    if shown:
        (win.showFullScreen if full else
         win.showMaximized if maxed else win.show)()
    settle()


def step_aside(canvas, why: str, aside: bool) -> None:
    """Hide a canvas for a reason, or let one reason go; it is shown again
    once it has none. The CPU draws the widget while it is hidden."""
    if canvas is None or not hasattr(canvas, "aside"):
        return
    (canvas.aside.add if aside else canvas.aside.discard)(why)
    want = not canvas.aside
    if want != canvas.isVisibleTo(canvas.parentWidget()):
        canvas.setVisible(want)
        QWidget.update(canvas.owner)


class _Overlay(QObject):
    """Watches a panel laid over the page (drawer, toast); a canvas it touches
    steps aside while it is up, since canvases composite over every sibling."""

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt name)
        if ev.type() in (QEvent.Type.Show, QEvent.Type.Hide,
                         QEvent.Type.Move, QEvent.Type.Resize):
            settle()
        return False


_watch = None


def overlay(panel: QWidget) -> None:
    """Make `panel` one that canvases step aside for while it is up."""
    global _watch
    if _watch is None:
        _watch = _Overlay()
    _overlays.append(weakref.ref(panel))
    panel.installEventFilter(_watch)


def _box(w: QWidget) -> QRect:
    return QRect(w.mapTo(w.window(), QPoint(0, 0)), w.size())


def settle() -> None:
    """Hide each canvas a visible panel overlaps, show the rest again."""
    up = []
    for ref in list(_overlays):
        panel = ref()
        if panel is None:
            _overlays.remove(ref)
        elif panel.isVisible():
            up.append(panel)
    for canvas in list(_canvases):
        try:
            win = canvas.window()
            hit = any(p.window() is win and _box(p).intersects(_box(canvas))
                      for p in up)
        except RuntimeError:                        # its C++ side is gone
            continue
        step_aside(canvas, "overlay", hit)


def give_up(owner) -> None:
    """The canvas never painted, or froze in a swap: the CPU draws this
    widget again."""
    canvas, owner.gl_canvas = owner.gl_canvas, None
    if canvas is not None:
        _canvases.discard(canvas)
        canvas.hide()
        canvas.deleteLater()
    QWidget.update(owner)


class GlViewport(QWidget):
    """A scroll area's viewport whose repaints go to the canvas over it; the
    canvas steps aside while a line edit is open in it."""

    gl_canvas = None

    def update(self, *a) -> None:
        if live(self.gl_canvas):
            self.gl_canvas.update(*a)
        else:
            super().update(*a)

    def childEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        super().childEvent(ev)
        canvas = self.gl_canvas
        if canvas is None or ev.type() not in (QEvent.Type.ChildPolished,
                                               QEvent.Type.ChildRemoved):
            return
        gone = ev.child() if ev.type() == QEvent.Type.ChildRemoved else None
        typing = any(isinstance(c, QLineEdit) and c is not gone
                     for c in self.children())
        step_aside(canvas, "typing", typing)
