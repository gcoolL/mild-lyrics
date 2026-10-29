"""The strip of audio the syllables are dragged around on: lead and backing
lanes over a 100 Hz RMS envelope, optionally the vocal stem's spectrogram,
with the beat grid drags snap to. No snapping to the vocal's marks; see
`ops.consistency`."""
from __future__ import annotations

import pathlib
import tempfile
import time

import noconsole

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap)
from PyQt6.QtWidgets import QWidget

from . import gpu as GPU
from . import theme as T
from . import vocal_look as VL
import spicy_lyrics as SL  # noqa: E402  (on the path model.py sets up)

def _inks() -> None:
    """The palette, re-read. Called at import and again whenever the
    accent changes -- these are module-level because they are asked for
    once per painted element and a lookup per chip is not free, which
    means a colour somebody has just chosen has to be pushed into them
    rather than picked up by itself."""
    global BG, WAVE, GRID, LEAD, LEAD_ON, BACK, BACK_ON
    global UNTIMED, HEAD, TEXT, ON_ACCENT
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


_inks()
EDGE = 4.0
SNAP = 8.0          # px from the playhead that a dragged time lands on it
LINK = 2.0          # px apart that two edges count as one shared edge
BEAT, BEAT_ELSE = "#2fb8b0", "#9a7bff"   # beat lines: teal, violet on a teal accent
SHORTEST = 0.02     # s: no drag leaves a syllable shorter than this
ANCHOR = 0.35
SUBROWS = 3
PACE = 0.3          # s a placed syllable lasts, when nothing is timed yet


def _levels(path: str, hz: int):
    """(rms readings, frames, rate) of a file, decoded a block at a time; same
    result as decoding the whole song at once."""
    import numpy as np
    import soundfile
    rows, frames = [], 0
    with soundfile.SoundFile(str(path)) as f:
        rate = f.samplerate
        step = max(1, int(rate // hz))
        for chunk in f.blocks(blocksize=step * 2048, dtype="float32",
                              always_2d=True):
            frames += len(chunk)
            mono = chunk.mean(axis=1)
            n = len(mono) // step
            if n:
                rows.append(np.sqrt((mono[:n * step].reshape(n, step) ** 2)
                                    .mean(axis=1)))
    return rows, frames, rate


def envelope(path: str, hz: int = 100):
    """A song as `hz` loudness readings a second, or None.

    soundfile first because it is in-process and reads what this project
    already keeps (wav, flac); ffmpeg after it, for everything else. Both
    are cheap next to what the timing model does with the same file.
    """
    import numpy as np
    try:
        rows, frames, rate = _levels(path, hz)
    except Exception:
        fd, name = tempfile.mkstemp(prefix="mild-editor-peaks-", suffix=".wav")
        import os
        os.close(fd)
        tmp = pathlib.Path(name)
        try:
            noconsole.run(["ffmpeg", "-v", "quiet", "-y", "-i", str(path),
                           "-ac", "1", "-ar", "16000", str(tmp)], check=True)
            rows, frames, rate = _levels(tmp, hz)
        except Exception:
            return None, 0.0
        finally:
            tmp.unlink(missing_ok=True)
    if not frames or not rate or not rows:
        return None, 0.0
    env = np.concatenate(rows)
    peak = float(env.max()) or 1.0
    return (env / peak).astype("float32"), frames / float(rate)


def _peaks(trace, lo, hi):
    """The largest reading in trace[lo[i]:hi[i]] for every i, 0 where empty, in
    one reduceat (the ranges may overlap)."""
    import numpy as np
    out = np.zeros(len(lo), dtype="float64")
    good = lo < hi
    if not good.any():
        return out
    pad = np.append(trace, trace[-1:])
    idx = np.empty(2 * int(good.sum()), dtype="int64")
    idx[0::2], idx[1::2] = lo[good], hi[good]
    out[good] = np.maximum.reduceat(pad, idx)[0::2]
    return out


def _corner(r) -> tuple[float, float]:
    """The corner radius for a word's block as (x, y): the line list's radius,
    clamped to half the block so short and long words look equally round."""
    rad = min(float(T.R_CHIP), r.width() / 2.0, r.height() / 2.0)
    return rad, rad


class Wave(QWidget):
    """Audio, syllables, and the playhead, in one scrollable strip."""

    seeked = pyqtSignal(float)
    follow_changed = pyqtSignal(bool)
    retimed = pyqtSignal(list)          # [(line, voice, syl, start, end)]
    let_go = pyqtSignal()
    picked = pyqtSignal(int, int, int)
    scrubbed = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(T.px(150))
        self.setFont(T.font(12, 500))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.env = None
        self.vocal = None
        self.show_vocal = False
        self.spec = None            # the mixture's own picture, no stem
        self.show_spec = False
        self.show_marks = False
        self.beats = None           # beat times (see beats.py), or None
        self.show_beats = True
        self.beat_snap = 2          # drags land on 1 beats, 2 half beats, 0 neither
        self._beat_serial = 0
        self._beat_hit = None       # the beat a drag has landed on, to light it
        self.claimed = None
        self._vpix = None
        self._vkey = None
        self.look = VL.look(VL.DEFAULT)
        self.length = 0.0
        self.view_at = 0.0
        self.span = 12.0
        self.pos = 0.0
        self.follow = True
        self.doc = None
        self.shown: list = []
        self._drawn: list = []
        self.cursor: tuple[int, int, int] | None = None
        self.chosen: set = set()
        self.press_mods = Qt.KeyboardModifier.NoModifier
        self.region: tuple[float, float] | None = None
        self._grab = None
        self._run = None
        self._lean = None           # Ctrl on a shared edge: (press x,) until it moves
        self._keep = None           # ...then (-1 or 1, the edge's time): its side
        self._seek_on_release = None
        self._snapped = False
        self._pix = None
        self._pix_at = None
        self._pix_shape = None
        self.roman_only = False
        self.lanes_all = True
        self.show_loose = True
        self.drag_edit = True
        self.gl_canvas = GPU.lay_over(self)

    def update(self, *a) -> None:
        """A repaint is the canvas's while there is one -- see gpu."""
        if GPU.live(self.gl_canvas):
            self.gl_canvas.update()
        else:
            super().update(*a)

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

    STILL_REPAINT = 0.25
    _painted_at = 0.0

    def set_pos(self, t: float, playing: bool) -> None:
        """Move the playhead and repaint if that moved anything; an unmoved
        strip still repaints every STILL_REPAINT seconds."""
        was, view = self.pos, self.view_at
        self.pos = t
        if self.follow and self._grab is None:
            self.view_at = t - self.span * ANCHOR
        if (t == was and self.view_at == view
                and time.perf_counter() - self._painted_at < self.STILL_REPAINT):
            return
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
        if GPU.live(self.gl_canvas):
            return
        self.paint_onto(QPainter(self))

    def paint_onto(self, p: QPainter) -> None:
        """The strip, into `p` -- the widget's own painter or its GPU
        canvas's -- which is ended here."""
        try:
            self._paint(p)
        finally:
            p.end()

    def _paint(self, p: QPainter) -> None:
        self._painted_at = time.perf_counter()
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
            p.setPen(QPen(HEAD, 3.0 if self._snapped and self._beat_hit is None
                          else 1.6))
            p.drawLine(QPointF(x, 0), QPointF(x, H))
        if self._beat_hit is not None:
            bx = self.x_of(self._beat_hit)
            hue = BEAT if T.q(T.LEAD).name() != BEAT else BEAT_ELSE
            p.setPen(QPen(T.q(hue, 230), 2.0))
            p.drawLine(QPointF(bx, 0), QPointF(bx, H))

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

    def _columns(self, W: int, at: float | None = None,
                 span: float | None = None):
        """One loudness per pixel column (the loudest reading in it), cached
        until the view moves."""
        import numpy as np
        at = self.view_at if at is None else at
        span = self.span if span is None else span
        step = span / max(W, 1)
        key = (round(at / step), round(span, 4), W, len(self.env))
        if getattr(self, "_col_key", None) == key:
            return self._cols
        hz = len(self.env) / max(self.length, 0.001)
        times = at + np.arange(W + 1) / W * span
        raw = (times * hz).astype("int64")   # noqa: E501
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

    OVERDRAW = 3

    def _envelope(self, p, W: int, H: int) -> None:
        """The envelope behind the blocks, drawn once per view and blitted
        every frame."""
        have_vocal = self._picture() is not None
        if W < 2 or (not have_vocal and (self.env is None or not len(self.env))):
            p.setPen(QPen(T.q(T.FAINT), 1))
            p.setFont(T.font(12, 500))
            p.drawText(QRectF(0, H * 0.06, W, H * 0.3),
                       int(Qt.AlignmentFlag.AlignCenter),
                       "no audio open — the times still work, "
                       "but there is nothing to see them against")
            return
        wide, span = W * self.OVERDRAW, self.span * self.OVERDRAW
        env_n = len(self.env) if self.env is not None else 0
        shape = (W, H, round(self.span, 4), env_n, round(self.length, 3),
                 bool(self.show_vocal), bool(self.show_marks),
                 self.vocal is not None, bool(self.show_spec),
                 self.spec is not None, self._beat_serial,
                 bool(self.show_beats), int(self.beat_snap))
        at = getattr(self, "_pix_at", None)
        stale = (self._pix is None or getattr(self, "_pix_shape", None) != shape
                 or at is None or self.view_at < at
                 or self.view_at + self.span > at + span)
        if stale:
            at = self.view_at - (span - self.span) / 2.0
            ratio = float(self.devicePixelRatioF() or 1.0)
            pix = QPixmap(int(wide * ratio), int(H * ratio))
            pix.setDevicePixelRatio(ratio)
            pix.fill(Qt.GlobalColor.transparent)
            q = QPainter(pix)
            q.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            self._paint_envelope(q, wide, H, at, span)
            q.end()
            self._pix, self._pix_at, self._pix_shape = pix, at, shape
        p.drawPixmap(int(round(-(self.view_at - at) / self.span * W)), 0,
                     self._pix)

    def _paint_envelope(self, p, W: int, H: int, at: float | None = None,
                        span: float | None = None) -> None:
        if self._picture() is not None:
            self._paint_vocal(p, W, H, at, span)
            self._paint_beats(p, W, H, at, span)
            return
        cols = self._columns(W, at, span)
        mid, amp = H * 0.22, H * 0.19
        grad = QLinearGradient(0.0, mid - amp, 0.0, mid + amp)
        grad.setColorAt(0.0, T.q(T.LEAD, 40))
        grad.setColorAt(0.5, T.q(T.LEAD, 115))
        grad.setColorAt(1.0, T.q(T.LEAD, 40))
        p.setPen(QPen(grad, 1))
        for x in range(W):
            v = float(cols[x])
            if v <= 0.0:
                continue
            p.drawLine(QPointF(x, mid - v * amp), QPointF(x, mid + v * amp))
        p.setPen(QPen(T.q(T.LEAD, 70), 1))
        p.drawLine(QPointF(0, mid), QPointF(W, mid))
        self._paint_beats(p, W, H, at, span)

    def set_beats(self, beats) -> None:
        """The song's beat grid, or None while there is none."""
        self.beats = beats
        self._beat_serial += 1
        self._pix = None
        self.update()

    def _paint_beats(self, p, W: int, H: int, at: float | None,
                     span: float | None) -> None:
        """A line a beat, and fainter ones on the half beats while drags snap
        to them; none once they would crowd closer than a few pixels."""
        if not self.show_beats or self.beats is None or len(self.beats) < 2:
            return
        import numpy as np
        at = self.view_at if at is None else at
        span = self.span if span is None else span
        b = self.beats
        lo, hi = np.searchsorted(b, [at - 1.0, at + span + 1.0])
        seen = b[max(0, lo - 1):hi + 1]
        if len(seen) < 2 or np.median(np.diff(seen)) / span * W < 5:
            return
        x = (seen - at) / span * W
        hue = BEAT if T.q(T.LEAD).name() != BEAT else BEAT_ELSE
        if self.beat_snap == 2 and np.median(np.diff(x)) >= 12:
            p.setPen(QPen(T.q(hue, 34), 1))
            for m in (x[:-1] + x[1:]) / 2:
                p.drawLine(QPointF(m, 0), QPointF(m, H))
        p.setPen(QPen(T.q(hue, 90), 1))
        for v in x:
            p.drawLine(QPointF(v, 0), QPointF(v, H))

    TOP, BOTTOM = 0.055, 0.385

    def _paint_vocal(self, p, W: int, H: int, at: float | None,
                     span: float | None) -> None:
        """The separated vocal's spectrogram, scaled from `vocalmap`'s QImage,
        with its landmark ticks."""
        at = self.view_at if at is None else at
        span = self.span if span is None else span
        vm = self._picture()
        img = self._vimage()
        y0, y1 = H * self.TOP, H * self.BOTTOM
        gut = max(6.0, (y1 - y0) * 0.13)
        y1 -= gut
        if img is not None and span > 0:
            hz = vm.pic_rate()
            sx0, sx1 = at * hz, (at + span) * hz
            cx0, cx1 = max(0.0, sx0), min(float(img.width()), sx1)
            if cx1 > cx0:
                dx0 = (cx0 - sx0) / (sx1 - sx0) * W
                dx1 = (cx1 - sx0) / (sx1 - sx0) * W
                tall = (y1 - y0) * float(self.devicePixelRatioF() or 1.0)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                                (sx1 - sx0) > W or img.height() > tall)
                p.drawImage(QRectF(dx0, y0, dx1 - dx0, y1 - y0), img,
                            QRectF(cx0, 0.0, cx1 - cx0, float(img.height())))
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                                False)
        if vm is not self.vocal:
            return                  # the mixture: a picture, nothing on it
        self._paint_flux(p, W, at, span, y0, y1)
        if self.show_marks:
            self._paint_marks(p, W, at, span, y0, y1 + gut, gut)
        p.setPen(QPen(T.q(T.LINE), 1))
        p.drawLine(QPointF(0, y1 + gut), QPointF(W, y1 + gut))

    def _paint_flux(self, p, W: int, at: float, span: float,
                    y0: float, y1: float) -> None:
        """Energy arriving (`vocalmap.flux`), drawn as a faint trace over the
        mel, the max of each pixel's columns."""
        if self.vocal is None or span <= 0 or W < 2:
            return
        lift = VL.trace(self.look)
        trace = self.vocal.flux(VL.bands(self.look)) if lift > 0 else None
        if trace is None or not len(trace):
            return
        import numpy as np
        hz = self.vocal.rate()
        edge = (np.arange(W + 1) / W * span + at) * hz
        lo = np.clip(edge[:-1].astype("int64"), 0, len(trace))
        hi = np.clip(np.maximum(edge[1:].astype("int64"), lo + 1), 0, len(trace))
        tall = (y1 - y0) * lift
        peaks = _peaks(trace, lo, hi)
        path = QPainterPath()
        path.moveTo(0.0, y0)
        for x in range(W):
            path.lineTo(float(x), y0 + float(peaks[x]) * tall)
        path.lineTo(float(W), y0)
        path.closeSubpath()
        p.save()
        c = QColor(T.q(T.BACK))
        p.setPen(QPen(QColor(c.red(), c.green(), c.blue(), 190), 1.0))
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 55))
        p.drawPath(path)
        p.restore()

    def _paint_marks(self, p, W: int, at: float, span: float,
                     y0: float, y1: float, gut: float = 8.0) -> None:
        """Ticks where the vocal starts or stops something: entrances full
        height, accounted attacks solid, ambiguous ones dotted
        (`ops.claims`), notes dim."""
        marks = self.vocal.marks()
        entrances = set(marks.get("entrances") or ())
        usable = self.claimed
        lo, hi = at, at + span
        floor, top = y1, y1 - gut
        p.fillRect(QRectF(0, top, W, gut), T.q(T.INK_0))
        p.setPen(QPen(T.q(T.DUET, 200), 1))
        for t in marks.get("ends") or ():
            if lo <= t <= hi:
                x = (t - at) / span * W
                p.drawLine(QPointF(x, top + gut * 0.45), QPointF(x, floor))
        dotted = QPen(T.q(T.BACK, 120), 1, Qt.PenStyle.DotLine)
        notes = set(marks.get("notes") or ())
        for t in marks.get("starts") or ():
            if not lo <= t <= hi:
                continue
            x = (t - at) / span * W
            spoken = usable is None or t in usable
            if t in notes:
                p.setPen(QPen(T.q(T.BACK, 110 if spoken else 55), 1))
                p.drawLine(QPointF(x, floor - gut * 0.55), QPointF(x, floor))
                continue
            p.setPen(QPen(T.q(T.BACK, 235), 1) if spoken else dotted)
            p.drawLine(QPointF(x, top), QPointF(x, floor))
            if t in entrances:
                p.setPen(QPen(T.q(T.BACK, 150 if spoken else 60), 1))
                p.drawLine(QPointF(x, y0), QPointF(x, top))

    def _vimage(self):
        """The song's spectrogram as a QImage, built once per song.

        `vocalmap` colours it, because doing it here meant opening a QPainter
        on an image while the strip already had two open on the widget and its
        cache, and Qt treats a third as fatal rather than as a mistake.
        """
        vm = self._picture()
        if vm is None:
            return None
        lk = self.look
        ramp = VL.ramp(lk)
        want = (ramp, VL.floor_pct(lk), VL.gamma(lk), VL.bands(lk),
                VL.hz(lk), VL.per_band(lk))
        if (self._vkey is vm and self._vpix is not None
                and getattr(self, "_vramp", None) == want):
            return self._vpix
        self._vpix = vm.image(ramp=ramp, floor_pct=want[1],
                              gamma=want[2], bands=want[3], hz=want[4],
                              per_band=want[5])
        self._vkey, self._vramp = vm, want
        return self._vpix

    def _picture(self):
        """The map drawn behind the words: the vocal's, the mixture's, or None."""
        if self.show_vocal and self.vocal is not None:
            return self.vocal
        if self.show_spec and self.spec is not None:
            return self.spec
        return None

    def set_look(self, lk: dict) -> None:
        """Draw the vocal view the way `lk` says -- see vocal_look."""
        self.look = dict(lk)
        self._pix = None
        self.update()

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

    def _stamp(self):
        """Enough of the document (times and shape) to know when the packing is
        stale: every voice's own span, since an ad-lib timed inside its line
        leaves the line's span as it was."""
        if self.doc is None:
            return None
        return tuple(tuple(g.span() for g in ln.groups())
                     for ln in self.doc.lines)

    MAX_LANES = 3
    KINDS = (("lead", "lead"), ("duet", "duet"), ("bg", "backing"))

    def _packing(self) -> dict:
        """A lane for every voice (lead, duet, backing), packed like a calendar
        with no ceiling, over the whole song so lanes do not change as you
        scroll."""
        if self._grab is not None and getattr(self, "_pack", None) is not None:
            return self._pack       # a block being dragged keeps its lane
        key = (self._stamp(), tuple(ln.agent for ln in self.doc.lines)
               if self.doc is not None else ())
        if getattr(self, "_pack_key", None) == key:
            return self._pack
        where: dict = {}
        lanes: list = []
        if self.doc is not None:
            items = {"lead": [], "duet": [], "bg": []}
            for i, ln in enumerate(self.doc.lines):
                for v, g in enumerate(ln.groups()):
                    kind = "bg" if v else ("lead" if ln.agent == "v1"
                                           else "duet")
                    items[kind].append(((i, v), g.span(), i))
            for kind, name in self.KINDS:
                got, n = self._pack_rows(items[kind], 1 << 30)
                if not n:
                    continue
                base = len(lanes)
                for k in range(n):
                    lanes.append((kind, f"{name} {k + 1}" if n > 1 else name))
                for key2, lane in got.items():
                    where[key2] = base + lane
        if not lanes:
            lanes = [("lead", "lead")]
        self._pack_key, self._pack = key, {"where": where, "lanes": lanes}
        return self._pack

    def lane_counts(self, pack: dict | None = None) -> tuple[int, int]:
        """(lanes the song needs, lanes drawn). `pack` is `_packing` if the
        caller already has it, which saves working out that the document has
        not changed a second time."""
        n = len((pack or self._packing())["lanes"])
        return n, n if self.lanes_all else min(self.MAX_LANES, n)

    def want_height(self) -> int:
        """How tall the strip has to be for every lane drawn to be legible."""
        _n, shown = self.lane_counts()
        return int((shown * T.px(24) + 6) / 0.60)

    @staticmethod
    def _pack_rows(items, cap: int) -> tuple[dict, int]:
        """Interval-pack (key, (start, end), order) into as few lanes as fit."""
        lanes: dict = {}
        ends: list[float] = []
        timed = [(k, a, b if b is not None else a, n)
                 for k, (a, b), n in items if a is not None]
        for k, a, b, _n in sorted(timed, key=lambda r: (r[1], r[3])):
            for lane, last in enumerate(ends):
                if a >= last - 0.001:
                    lanes[k], ends[lane] = lane, b
                    break
            else:
                if len(ends) >= cap:
                    lanes[k] = cap - 1
                    ends[cap - 1] = max(ends[cap - 1], b)
                else:
                    lanes[k] = len(ends)
                    ends.append(b)
        return lanes, max(1, len(ends)) if timed else 0

    def _bands(self, H: int, shown: int) -> tuple[float, float]:
        """(top of the first lane, lane height): the lanes share what is
        under the envelope, and get thinner the more of them are drawn."""
        top = H * 0.40
        room = max(24.0, H - top - 6)
        return top, room / max(1, shown)

    def _blocks(self, p, H: int) -> None:
        if self.doc is None:
            return
        fm = QFontMetricsF(self.font())
        vis = self._visible()
        pack = self._packing()
        total, shown = self.lane_counts(pack)
        top, lane_h = self._bands(H, shown)
        self._drawn = []
        want = {tuple(x) if isinstance(x, tuple) else (x, 0) for x in self.shown}
        for i in vis:
            ln = self.doc.lines[i]
            for voice, g in enumerate(ln.groups()):
                lane = pack["where"].get((i, voice), 0)
                if lane >= shown:
                    continue
                hh = lane_h * (0.86 if voice == 0 else 0.78)
                y = top + lane * lane_h + (lane_h - hh) / 2
                self._group(p, i, voice, g, y, hh, (i, voice) in want,
                            ln.agent != "v1", fm)
        if (self.show_loose and self.cursor is not None
                and 0 <= self.cursor[0] < len(self.doc.lines)):
            i = self.cursor[0]
            self._untimed(p, i, self.doc.lines[i], top)
        if total > 1:
            self._lane_tags(p, pack["lanes"][:shown], top, lane_h)

    def _lane_tags(self, p, lanes, top: float, lane_h: float) -> None:
        """Which voice each lane is, in a small tag at its left edge."""
        f = T.font(11.5 if T.LOOK == "new" else 10, 700)
        fm = QFontMetricsF(f)
        p.save()
        p.setFont(f)
        for n, (_kind, name) in enumerate(lanes):
            h = min(lane_h - 3, fm.height() + T.px(6))
            w = fm.horizontalAdvance(name) + T.px(14)
            r = QRectF(T.px(6), top + n * lane_h + (lane_h - h) / 2, w, h)
            p.setPen(QPen(T.q(T.LINE), 1))
            p.setBrush(QColor(14, 14, 18, 225))
            p.drawRoundedRect(r, T.px(6), T.px(6))
            p.setPen(QPen(T.q(T.MUTE), 1))
            p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), name)
        p.restore()

    def _rows(self, g) -> dict:
        """A row per syllable still sounding when the next begins, so a held
        word can be read and its end grabbed."""
        rows: dict = {}
        ends: list[float] = []
        for k, s in enumerate(g.syls):
            if not s.timed:
                continue
            a = s.start
            b = max(s.end or a, a + 0.03)
            for n, last in enumerate(ends):
                if a >= last - 0.001:
                    rows[k], ends[n] = n, b
                    break
            else:
                if len(ends) >= SUBROWS:
                    rows[k] = SUBROWS - 1
                    ends[SUBROWS - 1] = max(ends[SUBROWS - 1], b)
                else:
                    rows[k] = len(ends)
                    ends.append(b)
        return rows

    def _group(self, p, i: int, voice: int, g, y: float, h: float,
               chosen: bool, duet: bool, fm) -> None:
        base = LEAD if voice == 0 else BACK
        lit = LEAD_ON if voice == 0 else BACK_ON
        rows = self._rows(g)
        deep = (max(rows.values()) + 1) if rows else 1
        hh = h / deep
        f = self._block_font
        bfm = QFontMetricsF(f)
        for k, s in enumerate(g.syls):
            if not s.timed:
                continue
            a, b = s.start, max(s.end or s.start, s.start + 0.03)
            x0, x1 = self.x_of(a), self.x_of(b)
            if x1 < -40 or x0 > self.width() + 40:
                continue
            on = (i, voice, k) == self.cursor
            live = a <= self.pos <= b
            r = QRectF(x0, y + rows.get(k, 0) * hh, max(2.0, x1 - x0), hh)
            self._drawn.append((i, voice, k, r))
            new = T.LOOK == "new"
            fill = lit if (on or live) else base
            playing = live and not on
            if playing:
                fill = QColor(lit)
                fill.setAlpha(110)
            if new and not (on or live):
                fill = QColor(234, 234, 234, (84 if chosen else 56) if voice == 0
                              else (60 if chosen else 40))
            elif not chosen and not (on or live):
                fill = T.q(T.CHIP if voice == 0 else T.BACK, 150)
            p.setBrush(fill)
            p.setPen(QPen(lit, 1.4) if playing else
                     QPen(T.q(T.LEAD) if on else
                          T.q(T.DUET, 150) if duet and voice == 0 and not new else
                          QColor(234, 234, 234, 110 if chosen else 72) if new else
                          T.q(T.LINE), 1))
            p.drawRoundedRect(r, *_corner(r))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if (i, voice, k) in self.chosen and not on:
                p.setPen(QPen(T.q(T.LEAD), 1.8))
                p.drawRoundedRect(r.adjusted(0.9, 0.9, -0.9, -0.9),
                                  *_corner(r))
            label = s.text
            if self.roman_only and s.roman.strip() and SL.needs_roman(s.text):
                label = s.roman.strip()
            if r.width() > bfm.horizontalAdvance(label) + 6:
                p.setFont(f)
                p.setPen(QPen(ON_ACCENT if on else
                              TEXT if (chosen or new) else
                              T.q(T.TEXT, 215), 1))
                p.drawText(r.adjusted(4, 0, -1, 0),
                           int(Qt.AlignmentFlag.AlignVCenter), label)
                p.setFont(self.font())

    @property
    def _block_font(self):
        """The words on the blocks: a size up and a weight heavier than the
        strip's own labels, so a timed word reads at a glance."""
        return T.font(13, 650 if T.LOOK == "new" else 600)

    def _untimed(self, p, i: int, ln, top: float) -> None:
        """The line's words with no time yet, as a row of chips above all
        the lanes (`top`), each voice's run apart, where the line starts (or at the
        playhead), kept on the strip."""
        groups = ln.groups()
        runs = [(v, [k for k, s in enumerate(g.syls) if not s.timed])
                for v, g in enumerate(groups)]
        runs = [(v, ks[:40]) for v, ks in runs if ks]
        if not runs:
            return
        f = self._block_font
        bfm = QFontMetricsF(f)
        h = bfm.height() + 6
        y = max(2.0, top - h - 4)
        gap, apart = 3.0, 12.0
        widths = [[bfm.horizontalAdvance(groups[v].syls[k].text) + 10
                   for k in ks] for v, ks in runs]
        total = (sum(sum(ws) + gap * (len(ws) - 1) for ws in widths)
                 + apart * (len(runs) - 1))
        a, _b = ln.span()
        x = self.x_of(a if a is not None else self.pos)
        x = max(4.0, min(x, self.width() - total - 4))
        p.setFont(f)
        for (v, ks), ws in zip(runs, widths):
            for k, w in zip(ks, ws):
                r = QRectF(x, y, w, h)
                on = (i, v, k) == self.cursor
                self._drawn.append((i, v, k, r))
                p.setBrush(QColor(14, 14, 18, 225))
                p.setPen(QPen(T.q(T.LEAD) if on else
                              T.q(T.BACK) if v else T.q(T.LINE), 1))
                p.drawRoundedRect(r, *_corner(r))
                p.setPen(QPen(TEXT, 1))
                p.drawText(r.adjusted(5, 0, -1, 0),
                           int(Qt.AlignmentFlag.AlignVCenter),
                           groups[v].syls[k].text)
                x += w + gap
            x += apart - gap
        p.setFont(self.font())

    def _pace(self) -> float:
        """How long a syllable of this song lasts, from what is timed; what
        a line dropped onto the strip is laid out at."""
        got = sorted(s.end - s.start for ln in self.doc.lines
                     for g in ln.groups() for s in g.syls
                     if s.timed and s.end is not None and s.end > s.start)
        if not got:
            return PACE
        return max(0.08, min(0.8, got[len(got) // 2]))

    # --------------------------------------------------------------- mouse
    def _syl(self, i: int, voice: int, k: int):
        """The syllable a grab names, or None if the document changed under it."""
        if self.doc is None:
            return None
        g = self.doc.group(i, voice)
        if g is None or not 0 <= k < len(g.syls):
            return None
        return g.syls[k]

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

    def _partner(self, i: int, v: int, k: int, part: str):
        """(line, voice, syl) of the block sharing this edge -- one that ends
        where this starts, or starts where it ends, touching it in the same
        lane, whichever line it is in -- or None."""
        s = self._syl(i, v, k)
        at = None if s is None else (s.start if part == "start" else s.end)
        drawn = getattr(self, "_drawn", [])
        mine = next((r for li, vo, kk, r in drawn if (li, vo, kk) == (i, v, k)),
                    None)
        if at is None or mine is None:
            return None
        for li, vo, kk, r in drawn:
            if (li, vo, kk) == (i, v, k) or abs(r.center().y()
                                                - mine.center().y()) > 1:
                continue
            n = self._syl(li, vo, kk)
            if n is None or not n.timed:
                continue
            other = n.end if part == "start" else n.start
            if other is None or not (abs(other - at) <= 0.001 or abs(
                    self.x_of(other) - self.x_of(at)) <= LINK):
                continue
            if (n.start < at) if part == "start" else (
                    n.end is None or n.end > at):
                return (li, vo, kk)
        return None

    def _snap(self, t: float, free: bool) -> float:
        """`t`, or the playhead's time when it is within SNAP pixels, else the
        nearest beat (or half beat, see beat_snap) within them."""
        if free:
            return t
        if abs(self.x_of(t) - self.x_of(self.pos)) <= SNAP:
            self._snapped = True
            return self.pos
        b = self._beat_near(t)
        if b is not None:
            self._snapped, self._beat_hit = True, b
            return b
        return t

    def _beat_near(self, t: float) -> float | None:
        """The grid point nearest `t` when it is within SNAP pixels."""
        if not self.beat_snap or self.beats is None or len(self.beats) < 2:
            return None
        import bisect
        key = (self._beat_serial, self.beat_snap)
        if getattr(self, "_grid_key", None) != key:
            from . import beats as B
            self._grid_pts = B.grid(self.beats, self.beat_snap).tolist()
            self._grid_key = key
        g = self._grid_pts
        k = bisect.bisect_left(g, t)
        near = min((g[c] for c in (k - 1, k) if 0 <= c < len(g)),
                   key=lambda v: abs(v - t))
        return near if abs(self.x_of(near) - self.x_of(t)) <= SNAP else None

    def mousePressEvent(self, ev) -> None:                # noqa: N802 (Qt name)
        x, y = ev.position().x(), ev.position().y()
        hit = self._hit(x, y)
        right = ev.button() == Qt.MouseButton.RightButton
        edge = bool(hit and self.drag_edit and hit[3] in ("start", "end"))
        if right and not edge:
            self.seeked.emit(max(0.0, self.t_of(x)))
            return
        if hit:
            i, v, k, part = hit
            partner = self._partner(i, v, k, part) if edge else None
            if right and partner is not None:
                # Right: the shared edge comes apart, and only the word on
                # the pointer's side of it moves.
                s = self._syl(i, v, k)
                at = s.start if part == "start" else s.end
                if part == "start" and x < self.x_of(at):
                    (i, v, k), part = partner, "end"
                elif part == "end" and x >= self.x_of(at):
                    (i, v, k), part = partner, "start"
                partner = None
            self.cursor = (i, v, k)
            self.press_mods = ev.modifiers()
            self._lean = self._keep = None
            ctrl = Qt.KeyboardModifier.ControlModifier
            if partner is not None and self.press_mods & ctrl:
                # Ctrl on a shared edge: only the word it is dragged into
                # moves, decided by the first move -- not a pick.
                self._lean = x
                self.press_mods &= ~ctrl
            self.picked.emit(i, v, k)
            s = self._syl(i, v, k)
            if not self.drag_edit or s is None:
                self._grab = None
            elif part in ("start", "end"):
                at = s.start if part == "start" else s.end
                off = self.t_of(x) - at if at is not None else 0.0
                self._grab = (i, v, k, part, off, partner)
                self._seek_on_release = self.t_of(x) if right else None
            elif part == "body":
                if s.start is None:
                    self._grab = None
                    return
                self._grab = (i, v, k, "body", self.t_of(x) - s.start, None)
            else:
                # An unsynced word takes its voice's whole unsynced run
                # with it, laid out at the song's pace from the word held.
                g = self.doc.group(i, v)
                run = [kk for kk, w in enumerate(g.syls) if not w.timed]
                self._run = (run, run.index(k), self._pace())
                self._grab = (i, v, k, "place", 0.0, None)
            self.update()
            return
        self.seeked.emit(max(0.0, self.t_of(x)))
        self.update()

    def mouseMoveEvent(self, ev) -> None:                 # noqa: N802 (Qt name)
        x = ev.position().x()
        if self._grab is None:
            hit = self._hit(x, ev.position().y())
            shape = Qt.CursorShape.ArrowCursor
            if not self.drag_edit:
                hit = None
            if hit and hit[3] in ("start", "end"):
                shape = (Qt.CursorShape.SplitHCursor
                         if self._partner(*hit) is not None
                         else Qt.CursorShape.SizeHorCursor)
            elif hit and hit[3] == "body":
                shape = Qt.CursorShape.OpenHandCursor
            self.setCursor(shape)
            return
        if self._lean is not None and not self._choose_side(x):
            return
        i, v, k, part, off, partner = self._grab
        s = self._syl(i, v, k)
        n = self._syl(*partner) if partner is not None else None
        if s is None or (partner is not None and n is None):
            self._grab = None
            self.unsetCursor()
            return
        self._seek_on_release = None
        self._snapped, self._beat_hit = False, None
        free = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        t = self._snap(max(0.0, self.t_of(x) - off), free)
        out = []
        if self._keep is not None:
            # Into its own word only: never past the edge it came from.
            side, edge = self._keep
            t = min(t, edge) if side < 0 else max(t, edge)
            if part == "start" and s.end is not None:
                t = min(t, s.end - SHORTEST)
        if part == "start":
            if n is not None:
                t = max(t, n.start + SHORTEST)
                out.append((*partner, n.start, t))
            out.append((i, v, k, t, s.end if s.end is not None else t))
        elif part == "end":
            t = max(t, s.start + SHORTEST)
            if n is not None and n.end is not None:
                t = min(t, n.end - SHORTEST)
            out.append((i, v, k, s.start, t))
            if n is not None:
                out.append((*partner, t, n.end if n.end is not None else t))
        elif part == "place":
            run, at, pace = self._run
            a = max(0.0, t - at * pace)
            if not self._snapped:
                a = max(0.0, self._snap(a, free))
            out += [(i, v, kk, a + j * pace, a + (j + 1) * pace)
                    for j, kk in enumerate(run)]
        else:
            span = (s.end - s.start) if (s.timed and s.end) else 0.3
            a = t
            if not self._snapped:
                a = self._snap(a + span, free) - span
            out.append((i, v, k, max(0.0, a), max(0.0, a) + span))
        self.retimed.emit(out)
        self.update()

    def _choose_side(self, x: float) -> bool:
        """A Ctrl-held shared edge, once moved a few pixels: the grab becomes
        the edge of the word on the side it moves to. False while undecided."""
        if abs(x - self._lean) < 3:
            return False
        i, v, k, part, off, partner = self._grab
        left = (partner, "end") if part == "start" else ((i, v, k), "end")
        right = ((i, v, k), "start") if part == "start" else (partner, "start")
        (i, v, k), part = left if x < self._lean else right
        s = self._syl(i, v, k)
        if s is None:
            self._grab = self._lean = None
            return False
        edge = s.start if part == "start" else s.end
        self._grab = (i, v, k, part, off, None)
        self._keep = (-1 if part == "end" else 1, edge)
        self._lean = None
        self.cursor = (i, v, k)
        self.picked.emit(i, v, k)
        return True

    def mouseReleaseEvent(self, _ev) -> None:             # noqa: N802 (Qt name)
        was, self._grab, self._snapped = self._grab, None, False
        self._beat_hit = None
        self._lean = self._keep = None
        if self._seek_on_release is not None:
            self.seeked.emit(max(0.0, self._seek_on_release))
            self._seek_on_release = None
        if was is not None:
            self.let_go.emit()
        self.update()

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
