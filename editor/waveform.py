"""The strip of audio the syllables are dragged around on.

Two rows, because a line has two kinds of voice in it: the lead across the
middle and any backing groups under it. Everything in view is drawn from the
document, so a block is never a copy of a syllable that can fall out of step
with the one being edited -- it IS the syllable, painted where its times say.

The envelope behind them is a mono RMS at 100 Hz, which is enough to see a
vocal attack and cheap enough to compute on a whole song at once. It is not a
spectrogram on purpose: gc's own timings sit about 90 ms after the attack a
spectrogram would show, so a picture that invites snapping to the attack
would be inviting the wrong answer. It is here to show WHERE the singing is,
not to be traced.
"""
from __future__ import annotations

import pathlib
import subprocess
import tempfile

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient,
                         QPainter, QPen)
from PyQt6.QtWidgets import QWidget

from . import theme as T

BG = T.q(T.INK_1)
WAVE = T.q(T.LEAD)
GRID = T.q(T.LINE)
LEAD = T.q(T.CHIP)
LEAD_ON = T.q(T.LEAD)
BACK = T.q(T.BACK, 150)
BACK_ON = T.q(T.BACK)
UNTIMED = T.q(T.INK_3)
HEAD = T.q(T.LEAD)
TEXT = T.q(T.TEXT)
ON_ACCENT = QColor("#0b1020")
EDGE = 4.0
ANCHOR = 0.35
LANES = 3


def envelope(path: str, hz: int = 100):
    """A song as `hz` loudness readings a second, or None.

    soundfile first because it is in-process and reads what this project
    already keeps (wav, flac); ffmpeg after it, for everything else. Both
    are cheap next to what the timing model does with the same file.
    """
    import numpy as np
    data = rate = None
    try:
        import soundfile
        data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
        data = data.mean(axis=1)
    except Exception:
        tmp = pathlib.Path(tempfile.gettempdir()) / "mild-editor-peaks.wav"
        try:
            subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-i", str(path),
                            "-ac", "1", "-ar", "16000", str(tmp)], check=True)
            import soundfile
            data, rate = soundfile.read(str(tmp), dtype="float32", always_2d=True)
            data = data.mean(axis=1)
        except Exception:
            return None, 0.0
        finally:
            tmp.unlink(missing_ok=True)
    if data is None or rate is None or not len(data):
        return None, 0.0
    step = max(1, int(rate // hz))
    n = len(data) // step
    if n < 1:
        return None, 0.0
    block = data[:n * step].reshape(n, step)
    env = np.sqrt((block ** 2).mean(axis=1))
    peak = float(env.max()) or 1.0
    return (env / peak).astype("float32"), len(data) / float(rate)


class Wave(QWidget):
    """Audio, syllables, and the playhead, in one scrollable strip."""

    seeked = pyqtSignal(float)
    follow_changed = pyqtSignal(bool)
    moved = pyqtSignal(int, int, int, float, float)
    picked = pyqtSignal(int, int, int)
    scrubbed = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setFont(T.font(12, 500))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.env = None
        self.length = 0.0
        self.view_at = 0.0
        self.span = 12.0
        self.pos = 0.0
        self.follow = True
        self.doc = None
        self.shown: list = []
        self._drawn: list = []
        self.cursor: tuple[int, int, int] | None = None
        self.region: tuple[float, float] | None = None
        self._grab = None

    # ------------------------------------------------------------ geometry
    def x_of(self, t: float) -> float:
        return (t - self.view_at) / max(self.span, 0.01) * self.width()

    def t_of(self, x: float) -> float:
        return self.view_at + x / max(self.width(), 1) * self.span

    def centre(self, t: float) -> None:
        """Put `t` on the anchor. Deliberately not clamped at zero.

        Clamping would slide the playhead off the anchor for the first few
        seconds of every song -- which is the drift this exists to remove.
        Before the song starts there is simply nothing drawn.
        """
        self.view_at = t - self.span * ANCHOR
        self.update()

    def set_pos(self, t: float, playing: bool) -> None:
        self.pos = t
        if self.follow and self._grab is None:
            self.view_at = t - self.span * ANCHOR
        self.update()

    def zoom(self, factor: float, at: float | None = None) -> None:
        """Zoom about the playhead while following, about the pointer if not."""
        pivot = self.pos if (at is None or self.follow) else at
        self.span = max(0.6, min(180.0, self.span * factor))
        self.view_at = pivot - self.span * ANCHOR
        if not self.follow:
            self.view_at = max(0.0, self.view_at)
        self.update()

    # -------------------------------------------------------------- drawing
    def paintEvent(self, _ev) -> None:                    # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, BG)
        self._grid(p, W, H)
        self._envelope(p, W, H)
        if self.region:
            a, b = self.region
            p.fillRect(QRectF(self.x_of(a), 0, self.x_of(b) - self.x_of(a), H),
                       QColor(80, 200, 140, 28))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._blocks(p, H)
        x = self.x_of(self.pos)
        if -2 <= x <= W + 2:
            for width, alpha in ((7.0, 26), (4.0, 46)):
                p.setPen(QPen(T.q(T.LEAD, alpha), width))
                p.drawLine(QPointF(x, 0), QPointF(x, H))
            p.setPen(QPen(HEAD, 1.6))
            p.drawLine(QPointF(x, 0), QPointF(x, H))

    def _grid(self, p, W: int, H: int) -> None:
        step = 1.0 if self.span <= 20 else (5.0 if self.span <= 60 else 15.0)
        p.setFont(T.font(10, 500, mono=True))
        for a, b in ((self.view_at, 0.0),
                     (self.length, self.view_at + self.span)):
            if self.length and b > a:
                x0, x1 = self.x_of(max(a, self.view_at)), self.x_of(b)
                if x1 > x0:
                    p.fillRect(QRectF(x0, 0, x1 - x0, H), T.q("#000000", 60))
        t = step * int(self.view_at / step)
        while t < self.view_at + self.span:
            x = self.x_of(t)
            p.setPen(QPen(GRID, 1))
            p.drawLine(QPointF(x, 0), QPointF(x, H))
            if t >= 0 and (not self.length or t <= self.length):
                p.setPen(QPen(T.q(T.FAINT), 1))
                p.drawText(QPointF(x + 4, 12),
                           f"{int(t) // 60}:{int(t) % 60:02d}")
            t += step
        p.setPen(QPen(GRID, 1))
        p.drawLine(0, int(H * 0.40), W, int(H * 0.40))

    def _columns(self, W: int):
        """One loudness per pixel column, cached until the view moves.

        The strip is repainted thirty times a second to move the playhead, and
        the picture behind it only changes when the view scrolls or zooms --
        so it is worked out once per view rather than once per frame. Taken as
        the LOUDEST reading inside each column, so zooming out cannot hide a
        short attack between two samples.
        """
        import numpy as np
        step = self.span / max(W, 1)
        key = (round(self.view_at / step), round(self.span, 4), W,
               len(self.env))
        if getattr(self, "_col_key", None) == key:
            return self._cols
        hz = len(self.env) / max(self.length, 0.001)
        times = self.view_at + np.arange(W + 1) / W * self.span
        raw = (times * hz).astype("int64")
        edges = np.clip(raw, 0, len(self.env))
        starts = edges[:-1]
        ends = np.maximum(edges[1:], starts + 1)
        ends = np.minimum(ends, len(self.env))
        inside = (raw[:-1] >= 0) & (raw[:-1] < len(self.env))
        keep = (starts < ends) & inside
        cols = np.zeros(W, dtype="float32")
        if keep.any():
            got = np.maximum.reduceat(self.env, starts[keep])
            cols[keep] = got
        self._col_key, self._cols = key, cols
        return cols

    def _envelope(self, p, W: int, H: int) -> None:
        if self.env is None or not len(self.env) or W < 2:
            p.setPen(QPen(T.q(T.FAINT), 1))
            p.setFont(T.font(12, 500))
            p.drawText(QRectF(0, H * 0.06, W, H * 0.3),
                       int(Qt.AlignmentFlag.AlignCenter),
                       "no audio open — the times still work, "
                       "but there is nothing to see them against")
            return
        cols = self._columns(W)
        mid, amp = H * 0.22, H * 0.19
        grad = QLinearGradient(0.0, mid - amp, 0.0, mid + amp)
        grad.setColorAt(0.0, T.q(T.LEAD, 40))
        grad.setColorAt(0.5, T.q(T.LEAD, 115))
        grad.setColorAt(1.0, T.q(T.LEAD, 40))
        pen = QPen(grad, 1)
        p.setPen(pen)
        for x in range(W):
            v = float(cols[x])
            if v <= 0.0:
                continue
            p.drawLine(QPointF(x, mid - v * amp), QPointF(x, mid + v * amp))
        p.setPen(QPen(T.q(T.LEAD, 70), 1))
        p.drawLine(QPointF(0, mid), QPointF(W, mid))

    def _visible(self) -> list[int]:
        """Every line with anything to draw inside the view."""
        if self.doc is None:
            return []
        a, b = self.view_at, self.view_at + self.span
        out = []
        for i, ln in enumerate(self.doc.lines):
            s, e = ln.span()
            if s is None:
                continue
            if (e if e is not None else s) >= a and s <= b:
                out.append(i)
        return out

    def _lanes(self) -> dict:
        """A lane per line, so lines sounding at once are drawn apart.

        Packed over the WHOLE song, not over what happens to be in view: a
        lane worked out from the visible lines changes as you scroll, and a
        block that jumps to another row while you are reaching for it is
        worse than one drawn a little lower than it needs to be.

        Overlapping lines are not a rarity to be tolerated -- a duet answers
        before the other singer stops, and one of gc's files has twenty-five
        of them. Stacked on one row they draw over each other and neither can
        be read or grabbed, so they are packed into lanes the way a calendar
        packs overlapping appointments.
        """
        lanes: dict = {}
        ends: list[float] = []
        timed = [i for i, ln in enumerate(self.doc.lines)
                 if ln.span()[0] is not None]
        for i in sorted(timed, key=lambda n: self.doc.lines[n].span()[0] or 0.0):
            s, e = self.doc.lines[i].span()
            s = s or 0.0
            e = e if e is not None else s
            for n, last in enumerate(ends):
                if s >= last - 0.001:
                    lanes[i], ends[n] = n, e
                    break
            else:
                if len(ends) >= LANES:
                    lanes[i] = LANES - 1
                    ends[LANES - 1] = max(ends[LANES - 1], e)
                else:
                    lanes[i] = len(ends)
                    ends.append(e)
        return lanes

    def _bands(self, H: int, lanes: int) -> tuple:
        """(y per lead lane, lane height, y of the backing row, its height)."""
        top = H * 0.40
        room = H - top - 6
        rows = max(1, lanes) + 1
        h = room / rows
        return ([top + n * h for n in range(max(1, lanes))],
                h * 0.78, top + max(1, lanes) * h, h * 0.66)

    def _blocks(self, p, H: int) -> None:
        if self.doc is None:
            return
        fm = QFontMetricsF(self.font())
        vis = self._visible()
        lanes = self._lanes()
        ys, h, back_y, back_h = self._bands(H, (max(lanes.values()) + 1)
                                            if lanes else 1)
        self._drawn = []
        want = {tuple(x) if isinstance(x, tuple) else (x, 0) for x in self.shown}
        for i in vis:
            ln = self.doc.lines[i]
            lane = lanes.get(i, 0)
            for voice, g in enumerate(ln.groups()):
                y = ys[min(lane, len(ys) - 1)] if voice == 0 else back_y
                hh = h if voice == 0 else back_h
                self._group(p, i, voice, g, y, hh, (i, voice) in want,
                            ln.agent != "v1", fm)
        if self.cursor is not None and 0 <= self.cursor[0] < len(self.doc.lines):
            i = self.cursor[0]
            self._untimed(p, i, self.doc.lines[i],
                          ys[min(lanes.get(i, 0), len(ys) - 1)], h, fm)

    def _group(self, p, i: int, voice: int, g, y: float, h: float,
               chosen: bool, duet: bool, fm) -> None:
        base = LEAD if voice == 0 else BACK
        lit = LEAD_ON if voice == 0 else BACK_ON
        for k, s in enumerate(g.syls):
            if not s.timed:
                continue
            a, b = s.start, max(s.end or s.start, s.start + 0.03)
            x0, x1 = self.x_of(a), self.x_of(b)
            if x1 < -40 or x0 > self.width() + 40:
                continue
            on = (i, voice, k) == self.cursor
            live = a <= self.pos <= b
            r = QRectF(x0, y, max(2.0, x1 - x0), h)
            self._drawn.append((i, voice, k, r))
            fill = lit if (on or live) else base
            if not chosen and not (on or live):
                fill = T.q(T.CHIP if voice == 0 else T.BACK, 90)
            p.setBrush(fill)
            p.setPen(QPen(T.q(T.LEAD) if on else
                          T.q(T.DUET, 150) if duet and voice == 0 else
                          T.q(T.LINE), 1))
            p.drawRoundedRect(r, T.R_BADGE, T.R_BADGE)
            p.setBrush(Qt.BrushStyle.NoBrush)
            if r.width() > fm.horizontalAdvance(s.text) + 6:
                p.setPen(QPen(ON_ACCENT if (on or live) else
                              (TEXT if chosen else T.q(T.MUTE)), 1))
                p.drawText(r.adjusted(3, 0, -1, 0),
                           int(Qt.AlignmentFlag.AlignVCenter), s.text)

    def _untimed(self, p, i: int, ln, top: float, hgt: float, fm) -> None:
        loose = [(v, k) for v, g in enumerate(ln.groups())
                 for k, s in enumerate(g.syls) if not s.timed]
        if not loose:
            return
        a, _b = ln.span()
        x = self.x_of(a if a is not None else self.pos)
        for v, k in loose[:40]:
            s = ln.groups()[v].syls[k]
            w = fm.horizontalAdvance(s.text) + 10
            r = QRectF(x, top - hgt * 1.4, w, hgt * 0.9)
            on = (i, v, k) == self.cursor
            self._drawn.append((i, v, k, r))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(T.q(T.LEAD) if on else T.q(T.LINE), 1))
            p.drawRoundedRect(r, T.R_BADGE, T.R_BADGE)
            p.setPen(QPen(T.q(T.MUTE), 1))
            p.drawText(r.adjusted(4, 0, -1, 0),
                       int(Qt.AlignmentFlag.AlignVCenter), s.text)
            x += w + 3

    # --------------------------------------------------------------- mouse
    def _hit(self, x: float, y: float):
        """What is under the pointer: (line, voice, syl, part), or None.

        Read off the rectangles the last paint actually drew, so a block can
        never be somewhere the pointer disagrees with -- and so every line on
        the strip is grabbable, not only the selected one.
        """
        if self.doc is None:
            return None
        point = QPointF(x, y)
        for i, voice, k, r in reversed(getattr(self, "_drawn", [])):
            if not r.adjusted(-1, -1, 1, 1).contains(point):
                continue
            g = self.doc.group(i, voice)
            if g is None or not 0 <= k < len(g.syls):
                continue
            if not g.syls[k].timed:
                return (i, voice, k, "loose")
            if abs(x - r.left()) <= EDGE:
                return (i, voice, k, "start")
            if abs(x - r.right()) <= EDGE:
                return (i, voice, k, "end")
            return (i, voice, k, "body")
        return None

    def mousePressEvent(self, ev) -> None:                # noqa: N802 (Qt name)
        x, y = ev.position().x(), ev.position().y()
        hit = self._hit(x, y)
        if ev.button() == Qt.MouseButton.RightButton:
            self.seeked.emit(max(0.0, self.t_of(x)))
            return
        if hit:
            i, v, k, part = hit
            self.cursor = (i, v, k)
            self.picked.emit(i, v, k)
            if part in ("start", "end"):
                self._grab = (i, v, k, part, 0.0)
            elif part == "body":
                s = self.doc.lines[i].groups()[v].syls[k]
                self._grab = (i, v, k, "body", self.t_of(x) - s.start)
            else:
                self._grab = (i, v, k, "place", 0.0)
            self.update()
            return
        self.seeked.emit(max(0.0, self.t_of(x)))
        self.update()

    def mouseMoveEvent(self, ev) -> None:                 # noqa: N802 (Qt name)
        x = ev.position().x()
        if self._grab is None:
            hit = self._hit(x, ev.position().y())
            shape = Qt.CursorShape.ArrowCursor
            if hit and hit[3] in ("start", "end"):
                shape = Qt.CursorShape.SizeHorCursor
            elif hit and hit[3] == "body":
                shape = Qt.CursorShape.OpenHandCursor
            self.setCursor(shape)
            return
        i, v, k, part, off = self._grab
        s = self.doc.lines[i].groups()[v].syls[k]
        t = max(0.0, self.t_of(x))
        if part == "start":
            self.moved.emit(i, v, k, t, s.end if s.end is not None else t)
        elif part == "end":
            self.moved.emit(i, v, k, s.start, max(t, s.start + 0.02))
        else:
            span = (s.end - s.start) if (s.timed and s.end) else 0.3
            a = max(0.0, t - off)
            self.moved.emit(i, v, k, a, a + span)
        self.update()

    def mouseReleaseEvent(self, _ev) -> None:             # noqa: N802 (Qt name)
        self._grab = None

    def wheelEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        step = ev.angleDelta().y()
        if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self.follow:
                self.follow = False
                self.follow_changed.emit(False)
            self.view_at = max(0.0, self.view_at - self.span * 0.2 * (step / 120.0))
        else:
            self.zoom(0.8 if step > 0 else 1.25, self.t_of(ev.position().x()))
        self.update()
