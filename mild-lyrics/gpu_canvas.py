"""The window drawn on the GPU.

Every frame of the player is QPainter calls, and on the raster engine every
one of them is the CPU filling pixels: at 1920x1080 a frame cost about 11ms,
which is 90 frames a second on a 240Hz panel however the timer is set. The
same calls made on a QOpenGLWidget go to Qt's OpenGL paint engine instead --
a cached picture becomes a texture drawn as a quad, text comes from a glyph
atlas, a scaled or sub-pixel blit is the texture unit's filtering -- so the
drawing code does not change and the pixels move to the GPU.

The canvas is a child laid over the whole window, not the window itself.
The window keeps everything it is: its translucency, the native surface
apply_clear throws away and makes again, the backdrop, every event -- the
canvas is see-through to the mouse and never takes focus, so input lands on
the window exactly as before. The window just stops painting and hands its
painter to the canvas instead; see LyricsView.paint_onto.

What it does not move is the drawing INTO pictures -- the scene, the
visualiser's layer, the cached lines -- which is still raster, onto
QPixmaps, and then uploaded. Those are cached, or small, or both.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QSurfaceFormat, QVector2D
from PyQt6.QtWidgets import QApplication

try:
    from PyQt6.QtOpenGLWidgets import QOpenGLWidget
    from PyQt6.QtOpenGL import (QOpenGLFramebufferObject,
                                QOpenGLFramebufferObjectFormat,
                                QOpenGLPaintDevice, QOpenGLShader,
                                QOpenGLShaderProgram,
                                QOpenGLVersionFunctionsFactory,
                                QOpenGLVersionProfile)
except ImportError:                                      # no QtOpenGL built
    QOpenGLWidget = None

# The last step of a `straight` canvas's frame: the painted picture, its
# colours divided back out of their alpha.
_VERT = """
attribute highp vec2 pos;
varying highp vec2 uv;
void main() { uv = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }
"""
_FRAG = """
uniform sampler2D tex;
varying highp vec2 uv;
void main() {
    vec4 c = texture2D(tex, uv);
    gl_FragColor = c.a > 0.0 ? vec4(c.rgb / c.a, c.a) : vec4(0.0);
}
"""
GL_BLEND, GL_SCISSOR_TEST, GL_TEXTURE_2D, GL_TEXTURE0 = (
    0x0BE2, 0x0C11, 0x0DE1, 0x84C0)
GL_TRIANGLE_STRIP = 0x0005

MODES = ["auto", "on", "off"]

# Where "auto" turns it on: the platforms it has been run on -- KWin Wayland,
# on an NVIDIA card, 2026-10-02. X11, Windows and macOS have not been, so
# there it waits for "on", and falls back by itself if that fails.
TESTED: tuple = ("wayland",)

# Multisampling. Qt's GL engine only antialiases the edges of shapes -- the
# rounded art, the progress bar, every circle -- through it; without it they
# come out stair-stepped where the raster engine had them smooth.
SAMPLES = 4

# How long a new canvas has, while the window is on screen, to paint its
# first frame before it is taken for broken and the CPU draws again.
PROBATION_MS = 3000


def wanted(mode: str) -> bool:
    """Whether this setting asks for the GPU on the platform we are on."""
    if QOpenGLWidget is None or mode == "off":
        return False
    plat = QApplication.platformName() or ""
    if plat in ("offscreen", "minimal", "vnc", "linuxfb"):
        return False
    if mode == "on":
        return True
    return bool(TESTED) and plat.startswith(TESTED)


if QOpenGLWidget is not None:
    class GpuCanvas(QOpenGLWidget):
        """A widget's paint, on a GL surface laid over all of it.

        `view` is the widget covered; `paint(p)` draws into the canvas's
        painter and ends it, and defaults to `view.paint_onto`. The canvas
        keeps the view's size by itself. The TTML Editor lays one over a
        widget that only hosts the drawing -- a scroll area's viewport -- and
        hands the paint in from the scroll area; see editor/gpu.py.
        """

        failed = pyqtSignal()

        def __init__(self, view, paint=None, owner=None,
                     partial: bool = False, straight: bool = False) -> None:
            super().__init__(view)
            # With `straight`, the frame is handed over with straight alpha.
            # QPainter paints premultiplied, but Qt composites a
            # QOpenGLWidget into the window as straight alpha, so whatever
            # is see-through is multiplied by its alpha twice: the TTML
            # Editor's glass -- chips at alpha 20, row rules, the waveform's
            # grid -- all but vanished on screen while every FBO grab here
            # looked right. The player's canvas is opaque where it matters
            # and keeps the direct path. See _paint_straight.
            self.straight = straight
            self._ms = self._flat = self._prog = None
            self.view = view
            self.paint = paint or view.paint_onto
            # Who decides whether this canvas is still wanted: whatever holds
            # it as `gl_canvas`.
            self.owner = owner or view
            view.installEventFilter(self)
            # With `partial`, update(rect) repaints only that rect and keeps
            # the rest of the last frame -- see paintGL.
            self.partial = partial
            self._full = True
            self._dirty = None
            if partial:
                self.setUpdateBehavior(
                    QOpenGLWidget.UpdateBehavior.PartialUpdate)
            fmt = QSurfaceFormat()
            # A straight canvas multisamples its own framebuffer instead.
            fmt.setSamples(0 if straight else SAMPLES)
            fmt.setAlphaBufferSize(8)
            self.setFormat(fmt)
            # Drawn over the window's own surface rather than under it, so
            # the alpha in it reaches the desktop in clear mode.
            self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.painted = 0
            self.setGeometry(view.rect())
            self.show()
            QTimer.singleShot(PROBATION_MS, self._probation)

        def update(self, *a) -> None:
            """A repaint; of only the rect given, on a partial canvas. Any
            update without one, anywhere in the frame, makes it a full one."""
            if self.partial and a and not self._full:
                rect = QRect(a[0]) if len(a) == 1 else QRect(*a)
                self._dirty = rect if self._dirty is None else self._dirty.united(rect)
            else:
                self._full = True
            super().update()

        def resizeGL(self, w: int, h: int) -> None:        # noqa: N802 (Qt name)
            self._full = True

        def showEvent(self, ev) -> None:                   # noqa: N802 (Qt name)
            super().showEvent(ev)
            self._full = True

        def paintGL(self) -> None:
            if self.straight:
                try:
                    self._paint_straight()
                except Exception:                        # noqa: BLE001
                    # No shaders, or no framebuffers: drawn wrong is worse
                    # than drawn by the CPU, so give the widget back.
                    import traceback
                    traceback.print_exc()
                    self.straight = False
                    QTimer.singleShot(0, self.failed.emit)
                return
            self._paint_into(QPainter(self))

        def _paint_into(self, p: QPainter) -> None:
            clip = None if self._full else self._dirty
            self._full, self._dirty = False, None
            if clip is not None:
                # Everything outside is last frame's, kept by PartialUpdate;
                # the painter is clipped, so the paint can skip the rest.
                p.setClipRect(clip)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(clip if clip is not None else self.rect(),
                       Qt.GlobalColor.transparent)
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver)
            self.paint(p)
            self.painted += 1

        def initializeGL(self) -> None:                    # noqa: N802 (Qt name)
            """A new context -- on first show, and every time the window is
            made again (gpu.relay). What _paint_straight made lived in the
            old one, so it goes, and is made again in this one; the old
            context takes its own down with it when it goes."""
            self._drop_gl()
            self.context().aboutToBeDestroyed.connect(self._drop_gl)

        def _drop_gl(self) -> None:
            self._ms = self._flat = self._prog = None
            self._full = True

        def _paint_straight(self) -> None:
            """Paint into a multisampled framebuffer of our own, resolve it,
            and copy it into the widget's through _FRAG.

            Our own because the widget's is multisampled and cannot be read
            from, and kept between frames because a partial canvas repaints
            only its dirty rect into it -- the rest is the last frame's, as
            PartialUpdate keeps it on the direct path. The whole of it is
            copied over every frame: a quad is nothing to the GPU."""
            dpr = self.devicePixelRatioF()
            size = QSize(max(1, round(self.width() * dpr)),
                         max(1, round(self.height() * dpr)))
            if self._ms is None or self._ms.size() != size:
                fmt = QOpenGLFramebufferObjectFormat()
                fmt.setSamples(SAMPLES)
                fmt.setAttachment(
                    QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
                self._ms = QOpenGLFramebufferObject(size, fmt)
                self._flat = QOpenGLFramebufferObject(size)
                self._full = True
            if self._prog is None:
                prog = QOpenGLShaderProgram(self)
                if not (prog.addShaderFromSourceCode(
                            QOpenGLShader.ShaderTypeBit.Vertex, _VERT)
                        and prog.addShaderFromSourceCode(
                            QOpenGLShader.ShaderTypeBit.Fragment, _FRAG)
                        and prog.link()):
                    raise RuntimeError("straight-alpha shader: " + prog.log())
                self._prog = prog
            # Asked for every frame: they are the CONTEXT's, and a
            # QOpenGLWidget's context is replaced whenever its window is
            # made again -- on first show, and by gpu.relay. Kept from the
            # frame before, the next call went through a dead one and
            # crashed the editor. The factory caches them; this is a lookup.
            prof = QOpenGLVersionProfile()
            prof.setVersion(2, 0)
            gl = QOpenGLVersionFunctionsFactory.get(prof, self.context())
            if gl is None:
                raise RuntimeError("no OpenGL 2.0 functions")
            self._ms.bind()
            dev = QOpenGLPaintDevice(size)
            dev.setDevicePixelRatio(dpr)
            self._paint_into(QPainter(dev))
            QOpenGLFramebufferObject.blitFramebuffer(self._flat, self._ms)
            # The widget's own: inside a QOpenGLWidget Qt points the
            # context's default framebuffer at it.
            QOpenGLFramebufferObject.bindDefault()
            gl.glViewport(0, 0, size.width(), size.height())
            gl.glDisable(GL_BLEND)
            gl.glDisable(GL_SCISSOR_TEST)
            gl.glActiveTexture(GL_TEXTURE0)
            gl.glBindTexture(GL_TEXTURE_2D, self._flat.texture())
            self._prog.bind()
            self._prog.setUniformValue("tex", 0)
            at = self._prog.attributeLocation("pos")
            self._prog.enableAttributeArray(at)
            self._prog.setAttributeArray(at, [QVector2D(-1, -1), QVector2D(1, -1),
                                              QVector2D(-1, 1), QVector2D(1, 1)])
            gl.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
            self._prog.disableAttributeArray(at)
            self._prog.release()
            gl.glBindTexture(GL_TEXTURE_2D, 0)

        def eventFilter(self, obj, ev) -> bool:           # noqa: N802 (Qt name)
            if obj is self.view and ev.type() == QEvent.Type.Resize:
                self.setGeometry(self.view.rect())
            return False

        def _showing(self) -> bool:
            showing = getattr(self.owner, "showing", None)
            if callable(showing):
                return showing()
            wh = self.view.window().windowHandle()
            return (self.view.isVisible() and self.isVisible()
                    and wh is not None and wh.isExposed())

        def _probation(self) -> None:
            """No frame yet: wait while there is nothing to show, give up
            once there was and none came."""
            if self.painted or getattr(self.owner, "gl_canvas", None) is not self:
                return
            if not self._showing():
                QTimer.singleShot(PROBATION_MS, self._probation)
                return
            self.failed.emit()
else:
    GpuCanvas = None
