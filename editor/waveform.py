"""The strip of audio the syllables are dragged around on.

Two rows, because a line has two kinds of voice in it: the lead across the
middle and any backing groups under it. Everything in view is drawn from the
document, so a block is never a copy of a syllable that can fall out of step
with the one being edited -- it IS the syllable, painted where its times say.

The envelope behind them is a mono RMS at 100 Hz, which is enough to see a
vocal attack and cheap enough to compute on a whole song at once. It is here
to show WHERE the singing is, not to be traced.

There is a second picture behind them now, off until it is asked for: the mel
spectrogram of the DEMUCS VOCAL, from `vocalmap`. This module used to say a
spectrogram was the wrong picture on principle, because gc's timings do not
sit on the attack a spectrogram shows. That was measured on the MIXTURE, and
on the mixture it is right -- the loudest attack in a bar is a snare. On the
separated vocal it is not: 251 hand-placed word starts sit a consistent
-0.028 s from the stem's flux attacks with a spread of 0.040 s, against
0.070 s on the mixture. So the vocal view is offered.

What is NOT offered is snapping to it. That was built, measured and taken
out: the same word sung again in the same song gets a mark in some repeats
and not others, and where it does the offset moves by up to 130 ms. See
`ops.consistency`. The picture is here to be READ -- by somebody who knows
which of two adjacent syllables an attack belongs to, which no rule over
unlabelled attacks does.
"""
from __future__ import annotations

import pathlib
import tempfile

import noconsole

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap)
from PyQt6.QtWidgets import QWidget

from . import theme as T

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
ANCHOR = 0.35
# How many rows the lead voices and the backing voices each get before
# everything past the last one has to share it. Backing voices need more, not
# fewer: a song answers itself with two or three ad-libs at once far more
# readily than it sings two lead lines at once.
LANES = 4
BG_LANES = 4
SUBROWS = 3


def _rgb(hexcode: str) -> tuple[int, int, int]:
    c = QColor(hexcode)
    return c.red(), c.green(), c.blue()


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
        # A name of its own. A fixed one meant two editors decoding at the
        # same time read each other's half-written file.
        fd, name = tempfile.mkstemp(prefix="mild-editor-peaks-", suffix=".wav")
        import os
        os.close(fd)
        tmp = pathlib.Path(name)
        try:
            noconsole.run(["ffmpeg", "-v", "quiet", "-y", "-i", str(path),
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


def _corner(r) -> tuple[float, float]:
    """The corner radius for a word's block, as (x, y).

    One radius for every block in the strip -- the same one the chips in the
    line list use, so a word is the same shape wherever it is drawn -- and
    never more than half the block, because a block is as wide as its word is
    long and a sixteenth-note "a" is a few pixels. Asking for a fixed radius
    on those is what made the corners look uneven: Qt quietly clamps it to
    what fits, so a long word came out square and a short one came out a
    pill, from the same number. Clamping it here means every block is as
    round as it can be up to one limit, which is what reads as even.
    """
    rad = min(float(T.R_CHIP), r.width() / 2.0, r.height() / 2.0)
    return rad, rad


class Wave(QWidget):
    """Audio, syllables, and the playhead, in one scrollable strip."""

    seeked = pyqtSignal(float)
    follow_changed = pyqtSignal(bool)
    moved = pyqtSignal(int, int, int, float, float)
    picked = pyqtSignal(int, int, int)
    scrubbed = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(T.px(150))
        self.setFont(T.font(12, 500))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.env = None
        # The vocal view: a picture of the separated stem, the landmarks it
        # offers, and whether either is on. All three are None until somebody
        # asks -- separating a song is half a minute, and the strip has to be
        # useful before then.
        self.vocal = None
        self.show_vocal = False
        self.show_marks = False
        # Which marks the document can account for, from `ops.claims`. Set by
        # the window, because deciding it needs the document and this widget
        # only draws. None means "not worked out": everything is drawn as
        # though it were usable, which is what the strip did before there was
        # a distinction to draw.
        self.claimed = None
        self._vpix = None
        self._vkey = None
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
        self._pix = None
        self._pix_at = None
        self._pix_shape = None

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

    def _columns(self, W: int, at: float | None = None,
                 span: float | None = None):
        """One loudness per pixel column, cached until the view moves.

        The strip is repainted thirty times a second to move the playhead, and
        the picture behind it only changes when the view scrolls or zooms --
        so it is worked out once per view rather than once per frame. Taken as
        the LOUDEST reading inside each column, so zooming out cannot hide a
        short attack between two samples.
        """
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

    # How many viewport-widths of audio the cached picture covers. Following
    # the playhead scrolls the view every frame, so a picture drawn to fit
    # the viewport exactly is stale the moment it exists; one drawn wider is
    # blitted at an offset until the view walks off the end of it.
    OVERDRAW = 3

    def _envelope(self, p, W: int, H: int) -> None:
        """The picture behind the blocks, drawn once per view and then blitted.

        It is one line per pixel column -- upwards of twelve hundred of them
        on a wide window -- and it was being redrawn on every one of thirty
        frames a second to move a playhead that does not touch it. The
        picture only changes when the view scrolls or zooms or the window
        resizes, so that is when it is drawn; the rest of the time this is a
        single blit, which is the difference between the strip keeping up and
        not.
        """
        have_vocal = self.show_vocal and self.vocal is not None
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
                 self.vocal is not None)
        at = getattr(self, "_pix_at", None)
        stale = (self._pix is None or getattr(self, "_pix_shape", None) != shape
                 or at is None or self.view_at < at
                 or self.view_at + self.span > at + span)
        if stale:
            # Centre the strip on the view, so scrolling either way has room.
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
        if self.show_vocal and self.vocal is not None:
            self._paint_vocal(p, W, H, at, span)
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

    # The band the picture lives in: under the time labels, down to the rule
    # the blocks hang off. The same room the envelope uses, so turning the
    # vocal view on does not move a single syllable on screen.
    TOP, BOTTOM = 0.055, 0.385

    def _paint_vocal(self, p, W: int, H: int, at: float | None,
                     span: float | None) -> None:
        """The separated vocal's spectrogram, and what it offers to snap to.

        Drawn straight out of the QImage `vocalmap` built once for the song --
        one column per 10 ms of audio, scaled to whatever the view is showing.
        Qt does the resampling, which at a two-minute zoom means columns are
        dropped; that is the right trade here, because the picture is being
        read for its shape rather than measured, and the landmark ticks on top
        of it are the thing that must not move.
        """
        at = self.view_at if at is None else at
        span = self.span if span is None else span
        img = self._vimage()
        y0, y1 = H * self.TOP, H * self.BOTTOM
        # A gutter under the picture for the ticks. They used to be stubs off
        # the floor of the band, drawn over the low mel bands -- which are
        # the loudest part of a vocal and so the brightest part of the
        # picture, and a thin orange line over that is invisible. Given a
        # strip of their own they are always readable, and the picture loses
        # eight pixels it was not using for anything.
        gut = max(6.0, (y1 - y0) * 0.13)
        y1 -= gut
        if img is not None and span > 0:
            hz = self.vocal.rate()
            sx0, sx1 = at * hz, (at + span) * hz
            # Only the part of the song that exists; the rest stays background
            # rather than being smeared out of the first or last column.
            cx0, cx1 = max(0.0, sx0), min(float(img.width()), sx1)
            if cx1 > cx0:
                dx0 = (cx0 - sx0) / (sx1 - sx0) * W
                dx1 = (cx1 - sx0) / (sx1 - sx0) * W
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                                (sx1 - sx0) > W)
                p.drawImage(QRectF(dx0, y0, dx1 - dx0, y1 - y0), img,
                            QRectF(cx0, 0.0, cx1 - cx0, float(img.height())))
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                                False)
        self._paint_flux(p, W, at, span, y0, y1)
        if self.show_marks:
            self._paint_marks(p, W, at, span, y0, y1 + gut, gut)
        p.setPen(QPen(T.q(T.LINE), 1))
        p.drawLine(QPointF(0, y1 + gut), QPointF(W, y1 + gut))

    def _paint_flux(self, p, W: int, at: float, span: float,
                    y0: float, y1: float) -> None:
        """Energy arriving, drawn over the picture as a trace.

        The spectrogram is a picture of LOUDNESS and a word start is not
        loudness, it is a change in it -- which is why word starts are so much
        less obvious in it than line starts, where the vocal goes from nothing
        to something. `vocalmap.flux` is the same audio differenced and read
        against its own neighbourhood, and it stands three times above its
        background at a hand-placed word start where the picture manages 1.4.

        MAX over the columns a pixel covers, not their mean. A whole song in
        the strip is twenty columns to the pixel and an attack is one or two
        of them; averaging is how you make a trace that is smooth and says
        nothing. The peak is the whole point, so the peak is what is drawn.

        Over the mel rather than in a lane of its own: the two are the same
        moment in the same audio and reading them side by side means looking
        away from one to check the other. Kept faint, and only as high as a
        third of the band, so the picture underneath is still legible.
        """
        if self.vocal is None or span <= 0 or W < 2:
            return
        trace = self.vocal.flux()
        if trace is None or not len(trace):
            return
        import numpy as np
        hz = self.vocal.rate()
        edge = (np.arange(W + 1) / W * span + at) * hz
        lo = np.clip(edge[:-1].astype("int64"), 0, len(trace))
        hi = np.clip(np.maximum(edge[1:].astype("int64"), lo + 1), 0, len(trace))
        # Hung from the TOP of the band, not stood on the floor of it. A sung
        # vocal puts nearly all of its energy in the low mel bands, which are
        # the bottom of this picture and the brightest part of it, so a thin
        # line drawn there is competing with the loudest thing on screen. The
        # top bands are almost empty; a trace hanging into that space is
        # legible without anything having to be dimmed to make room for it.
        tall = (y1 - y0) * 0.42
        path = QPainterPath()
        path.moveTo(0.0, y0)
        for x in range(W):
            a, b = int(lo[x]), int(hi[x])
            v = float(trace[a:b].max()) if b > a else 0.0
            path.lineTo(float(x), y0 + v * tall)
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
        """Ticks where the vocal starts and stops something.

        Four distinctions, because the marks are not equally believable and
        the eye is the only thing here that can tell a `sane` from a `she`:

          * an ENTRANCE -- the vocal arriving out of real silence -- gets a
            full-height line. It is the only kind founded on silence rather
            than on a jump in the spectrum.
          * an attack the document can account for gets a solid stub.
          * an attack that TWO syllables are both near, or that none is,
            gets a dotted stub -- see `ops.claims`. Drawn apart so that a
            mark sitting between `sane` and `she` looks like the ambiguity
            it is rather than like evidence.
          * a NOTE -- the pitch stepping rather than energy arriving -- gets
            a short, dim stub. There are more of these than of anything else
            and they are the least founded of the three kinds, so they are
            drawn as the hint they are; on a chopped vocal they are also the
            only marks there are, and then the row of them is the picture.
        """
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
                # An entrance earns a line up through the picture as well:
                # it is the only mark founded on silence rather than on a
                # jump in the spectrum, and it is usually the one somebody
                # is actually looking for.
                p.setPen(QPen(T.q(T.BACK, 150 if spoken else 60), 1))
                p.drawLine(QPointF(x, y0), QPointF(x, top))

    def _vimage(self):
        """The song's spectrogram as a QImage, built once per song.

        `vocalmap` colours it, because doing it here meant opening a QPainter
        on an image while the strip already had two open on the widget and its
        cache, and Qt treats a third as fatal rather than as a mistake.
        """
        if self.vocal is None:
            return None
        if self._vkey is self.vocal and self._vpix is not None:
            return self._vpix
        self._vpix = self.vocal.image(
            ramp=(_rgb(T.INK_1), _rgb(T.LEAD), _rgb(T.TEXT)))
        self._vkey = self.vocal
        return self._vpix

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
        """Enough of the document to know when the packing is stale.

        The times and the shape, nothing else. Packing the whole song is not
        expensive once; it was expensive because it ran on every one of
        thirty frames a second, along with everything else this used to
        recompute per frame.
        """
        if self.doc is None:
            return None
        return tuple((ln.span(), len(ln.bg)) for ln in self.doc.lines)

    def _packing(self) -> dict:
        """A lane for every voice: leads in their rows, ad-libs in theirs.

        Two separate packings, and that is the point. There used to be one
        row for every backing voice in the SONG, so a track with two ad-libs
        sounding at once drew them on top of each other -- unreadable and
        ungrabbable, which is the state Music Baby's bar was in. And that row
        was reserved whether or not the song had a single ad-lib in it, so
        every lead line was drawn half as tall as it needed to be to leave
        space for nothing.

        Packed over the WHOLE song rather than over what is in view: a lane
        worked out from the visible lines changes as you scroll, and a block
        that jumps to another row while you are reaching for it is worse than
        one drawn a little lower than it needs to be.

        Overlapping voices are not a rarity to be tolerated -- a duet answers
        before the other singer stops, and one of gc's files has twenty-five
        of them -- so they are packed the way a calendar packs appointments.
        """
        key = self._stamp()
        if key is not None and getattr(self, "_pack_key", None) == key:
            return self._pack
        got = {"lead": {}, "bg": {}, "leads": 1, "bgs": 0}
        if self.doc is not None:
            got["lead"], got["leads"] = self._pack_rows(
                [(i, self.doc.lines[i].lead.span(), i)
                 for i in range(len(self.doc.lines))], LANES)
            bg = []
            for i, ln in enumerate(self.doc.lines):
                for v, g in enumerate(ln.groups()):
                    if v:
                        bg.append(((i, v), g.span(), i))
            got["bg"], got["bgs"] = self._pack_rows(bg, BG_LANES)
        self._pack_key, self._pack = key, got
        return got

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
                    # Everything past the cap shares the last lane. It is a
                    # floor, not a choice -- the strip scrolls instead, so
                    # the cap only bites on songs that would need more rows
                    # than a screen has pixels for.
                    lanes[k] = cap - 1
                    ends[cap - 1] = max(ends[cap - 1], b)
                else:
                    lanes[k] = len(ends)
                    ends.append(b)
        return lanes, max(1, len(ends)) if timed else 0

    def _bands(self, H: int, leads: int, bgs: int) -> tuple:
        """(y per lead lane, lead height, y per backing lane, backing height).

        The backing rows take room only when there ARE backing rows. A song
        with no ad-libs used to give up a row's worth of height to hold one
        anyway, which is why an ad-lib anywhere in a song appeared to push
        every line down.
        """
        top = H * 0.40
        room = max(24.0, H - top - 6)
        rows = max(1, leads) + max(0, bgs)
        h = room / rows
        ys = [top + n * h for n in range(max(1, leads))]
        base = top + max(1, leads) * h
        backs = [base + n * h for n in range(max(0, bgs))]
        return ys, h * 0.78, backs, h * 0.66

    def _blocks(self, p, H: int) -> None:
        if self.doc is None:
            return
        fm = QFontMetricsF(self.font())
        vis = self._visible()
        pack = self._packing()
        ys, h, backs, back_h = self._bands(H, pack["leads"], pack["bgs"])
        self._drawn = []
        want = {tuple(x) if isinstance(x, tuple) else (x, 0) for x in self.shown}
        for i in vis:
            ln = self.doc.lines[i]
            for voice, g in enumerate(ln.groups()):
                if voice == 0:
                    lane = pack["lead"].get(i, 0)
                    y, hh = ys[min(lane, len(ys) - 1)], h
                else:
                    if not backs:
                        continue
                    lane = pack["bg"].get((i, voice), 0)
                    y, hh = backs[min(lane, len(backs) - 1)], back_h
                self._group(p, i, voice, g, y, hh, (i, voice) in want,
                            ln.agent != "v1", fm)
        if self.cursor is not None and 0 <= self.cursor[0] < len(self.doc.lines):
            i = self.cursor[0]
            lane = pack["lead"].get(i, 0)
            self._untimed(p, i, self.doc.lines[i],
                          ys[min(lane, len(ys) - 1)], h, fm)

    def _rows(self, g) -> dict:
        """A row per syllable that is still sounding when the next begins.

        The same packing the lines get, one level down. Syllables inside a
        line overlap on purpose -- a word held over the ones after it, a
        rapped line whose breath carries through -- and drawn on one row the
        held word is buried under the words it rings over: it cannot be read,
        and its right edge cannot be grabbed to say how far it rings, because
        the chip on top of it answers the pointer first.
        """
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
            fill = lit if (on or live) else base
            if not chosen and not (on or live):
                fill = T.q(T.CHIP if voice == 0 else T.BACK, 90)
            p.setBrush(fill)
            p.setPen(QPen(T.q(T.LEAD) if on else
                          T.q(T.DUET, 150) if duet and voice == 0 else
                          T.q(T.LINE), 1))
            p.drawRoundedRect(r, *_corner(r))
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
            p.drawRoundedRect(r, *_corner(r))
            p.setPen(QPen(T.q(T.MUTE), 1))
            p.drawText(r.adjusted(4, 0, -1, 0),
                       int(Qt.AlignmentFlag.AlignVCenter), s.text)
            x += w + 3

    # --------------------------------------------------------------- mouse
    def _syl(self, i: int, voice: int, k: int):
        """The syllable a grab names, or None if it is no longer there.

        A grab is held across mouse moves, and the document can change under
        it -- an undo, a line the model just retimed, a word deleted from
        another pane. Indexing doc.lines[i].groups()[v].syls[k] raw then
        raises inside a Qt slot, which takes the drag down with it and leaves
        the edit half applied.
        """
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
                s = self._syl(i, v, k)
                if s is None or s.start is None:
                    self._grab = None
                    return
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
        s = self._syl(i, v, k)
        if s is None:
            self._grab = None      # the document moved out from under it
            self.unsetCursor()
            return
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
