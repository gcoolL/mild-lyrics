"""The bar you drag across to time a row.

Drag sync began on the words themselves, and on the words it does not work.
The thing you are aiming at is a chip drawn the width of what it says, so
"cannot" is eighty pixels and "I" is eighteen -- and the syllables you most
need to place accurately are, without fail, the short ones. A line of
one-syllable words is a row of slivers, and the drag misses them at speed.

So the bar is the row laid out again, and by default EVERY SLICE IS THE SAME
WIDTH.

That is the second answer to the same complaint, and the one that is on. The
first was proportional: a slice as wide as its word, floored so that "I" was
still hittable, which kept the bar the same shape as the line above it --
pleasant to read, and it meant the hand had to travel a different distance for
every syllable. What a drag mostly wants is a rhythm: one width, one step, no
word worth more room than any other, because the drag is spacing syllables in
TIME and the widths were saying something about spelling instead.

Both are settings now, because which one helps is a question about the hand
doing the dragging and not one this file can answer. `cell` is what a slice is
drawn at and `stretch` is how much of the word's own drawn width is added to
it: at 0 they are all the same, at 1 a long word gets about as much extra room
as it takes to write, which is the old proportional bar. Anything between is
between.

They are also smaller than they were, and the row is centred rather than
stretched to the edges. A slice only has to be wide enough that it cannot be
crossed by accident at the speed a hand moves through a fast line -- that is
`MIN_CELL`, and it is the one width that is not a preference.

A row that will not fit WRAPS, the way the lyric does, rather than shrinking
its slices to make room: the width is a choice somebody made and a bar that
quietly halves it on a long line is a different step for the same drag. The
one thing that is shared down is a slice too wide for the bar on its own,
which has nowhere else to go. The drag carries on from the end of one line to
the start of the next.

Nothing in here knows what time it is. It says which syllable the pointer is
on and the window turns that into seconds, exactly as the list does -- see
`Editor._sweep_begin`.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from . import theme as T

def _inks() -> None:
    """The palette, re-read. Called at import and again whenever the
    accent changes -- these are module-level because they are asked for
    once per painted element and a lookup per chip is not free, which
    means a colour somebody has just chosen has to be pushed into them
    rather than picked up by itself."""
    global BG, CELL, CELL_TIMED, CELL_LIVE, CELL_SWEPT, CELL_AT
    global RULE, TEXT, MUTE, ON_ACCENT
    BG = T.q(T.INK_1)
    CELL = T.q(T.INK_2)
    CELL_TIMED = T.q(T.CHIP)
    CELL_LIVE = T.q(T.LEAD_DIM)
    CELL_SWEPT = T.q(T.LEAD_DIM)
    CELL_AT = T.q(T.LEAD)
    RULE = T.q(T.LINE)
    TEXT = T.q(T.TEXT)
    MUTE = T.q(T.MUTE)
    ON_ACCENT = QColor("#0b1020")


_inks()

PAD = 10.0
GAP = 3.0
CAP_H = 15.0
CELL_H = 34.0
TEXT_PX = 13
# What a slice is drawn at when the row has room for it, and the narrowest it
# may be squeezed to before the row wraps instead. The floor is the number
# that matters: below it a syllable is crossed by accident at the speed a
# hand moves through a fast line, which is what the whole widget is for. The
# wanted width is only comfort, so it gives way first.
CELL_W = 52.0
MIN_CELL = 38.0


def _share(want: list, room: float, floor: float) -> list:
    """Fit the wanted widths into `room` without any falling under `floor`.

    Scaling them all by one factor is nearly right and fails on exactly the
    case this widget exists for: the factor that makes a long line fit is the
    factor that takes "I" back down to a sliver. So the ones that would go
    under the floor are pinned there and taken out of the sum, and the rest
    are scaled into whatever room is left over -- repeatedly, because pinning
    one takes room away from the others and can push the next one under.

    It ends: each pass either pins at least one slice or returns, and there
    are only so many slices to pin.
    """
    out = list(want)
    free = list(range(len(want)))
    space = room
    while free:
        total = sum(want[i] for i in free)
        if total <= 0:
            break
        scale = space / total
        small = [i for i in free if want[i] * scale < floor]
        if not small:
            for i in free:
                out[i] = want[i] * scale
            break
        for i in small:
            out[i] = floor
            space -= floor
        free = [i for i in free if i not in set(small)]
    return out


class SyncBar(QWidget):
    """One row of a lyric as slices to aim at, and the drag across them."""

    begin = pyqtSignal(int)
    moved = pyqtSignal(int)
    done = pyqtSignal(int)
    cancelled = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.syls: list = []
        # Set from the settings; see the module docstring. Kept on the widget
        # rather than read from the config here, because this file draws and
        # the window is what knows what anybody has chosen.
        self.cell = CELL_W
        self.stretch = 0.0
        self.caption = ""
        self.pos = 0.0
        self.span: tuple = (None, None)
        self.at: int = -1
        self.lit: set = set()
        self.cells: list[QRectF] = []
        self._from = 0
        self._live = False
        self._hover = -1
        # Asked the moment a drag would start, and expected to say out loud
        # why not when the answer is no -- the same contract the list has.
        self.ok = lambda: True
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ------------------------------------------------------------- outside
    def show_row(self, syls: list, caption: str, span=(None, None)) -> None:
        """Put a row on the bar. Called whenever the document or the armed
        row changes, so it is cheap and it never interrupts a pass."""
        if self._live:
            return
        self.syls = list(syls)
        self.caption = caption
        self.span = span
        self.at, self.lit, self._from = -1, set(), 0
        self._relayout()
        self.update()

    def set_pos(self, t: float) -> None:
        self.pos = t
        if self.syls:
            self.update()

    def dragging(self) -> bool:
        return self._live

    # -------------------------------------------------------------- layout
    def _relayout(self) -> None:
        """Where every slice goes: `cell` wide, `stretch` of the word added.

        Worked in PITCH -- what a slice takes up including the gap drawn after
        it -- rather than in the drawn width, so the sums come out right and
        the gap never has to be accounted for twice. `cell` and MIN_CELL are
        drawn widths, so a pitch is one gap more.
        """
        self.cells = []
        self._rows = 1
        n = len(self.syls)
        if not n:
            self.updateGeometry()
            return
        pad, gap = T.px(PAD), T.px(GAP)
        cell_h = T.px(CELL_H)
        self._cell_h = cell_h
        floor = T.px(MIN_CELL) + gap
        fm = QFontMetricsF(T.font(TEXT_PX, 600))
        base = max(floor, T.px(self.cell) + gap)
        stretch = max(0.0, float(self.stretch))
        want = [base + stretch * fm.horizontalAdvance(s.text) for s in self.syls]
        room = max(floor, self.width() - pad * 2)
        # Packed by what a slice will END UP taking, floor included, or a row
        # could be filled with words too short to honour the floor in.
        need = [max(floor, w) for w in want]
        rows: list = []
        cur: list = []
        used = 0.0
        for k, w in enumerate(need):
            if cur and used + w > room:
                rows.append(cur)
                cur, used = [], 0.0
            cur.append(k)
            used += w
        if cur:
            rows.append(cur)
        top = pad + T.px(CAP_H)
        for r, row in enumerate(rows):
            widths = [need[k] for k in row]
            if sum(widths) > room:
                widths = _share([want[k] for k in row], room, floor)
            # Centred, not stretched. A row of equal slices stretched to the
            # edges would make the last row of a wrapped line -- three words,
            # say -- into three enormous ones, and the hand would have to
            # learn a different step for it. The gap after the last slice is
            # not part of the row, so it is taken off before centring.
            drawn = sum(widths) - gap
            x = pad + max(0.0, (room - drawn) / 2.0)
            for k, w in zip(row, widths):
                self.cells.append(QRectF(x, top + r * (cell_h + gap),
                                         max(1.0, w - gap), cell_h))
                x += w
        self._rows = len(rows)
        self.updateGeometry()

    def sizeHint(self) -> QSize:                          # noqa: N802 (Qt name)
        rows = getattr(self, "_rows", 1)
        return QSize(400, int(T.px(PAD) * 2 + T.px(CAP_H)
                              + rows * (T.px(CELL_H) + T.px(GAP))))

    def minimumSizeHint(self) -> QSize:                   # noqa: N802 (Qt name)
        return self.sizeHint()

    def resizeEvent(self, ev) -> None:                    # noqa: N802 (Qt name)
        super().resizeEvent(ev)
        self._relayout()

    def restyle(self) -> None:
        self._relayout()
        self.update()

    # ------------------------------------------------------------- drawing
    def paintEvent(self, _ev) -> None:                    # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, BG)
        pad = T.px(PAD)
        p.setFont(T.font(10, 600, caps=True))
        p.setPen(QPen(MUTE, 1))
        p.drawText(QRectF(pad, pad * 0.4, W - pad * 2, T.px(CAP_H)),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   self.caption or "drag sync")
        if not self.syls:
            p.setFont(T.font(12, 500))
            p.setPen(QPen(MUTE, 1))
            p.drawText(QRectF(0, 0, W, H), int(Qt.AlignmentFlag.AlignCenter),
                       "click a line above to put it on the bar")
            return
        self._progress(p, W, pad)
        first = next((k for k, s in enumerate(self.syls) if not s.timed), -1)
        fm = QFontMetricsF(T.font(TEXT_PX, 600))
        p.setFont(T.font(TEXT_PX, 600))
        for k, box in enumerate(self.cells):
            self._cell(p, k, box, fm, first)

    def _progress(self, p, W: float, pad: float) -> None:
        """A hairline saying where the song is inside this row's LINE.

        The slices are an index, not a clock, so there is nowhere on them for
        a playhead to be. This is the one thing the bar can honestly show
        about time, and on a replay for an ad-lib it is the thing being
        waited for: the line is running, and this is how far through.
        """
        a, b = self.span
        if a is None or b is None or b <= a:
            return
        k = (self.pos - a) / (b - a)
        y = pad * 0.4 + T.px(CAP_H) - 2
        p.setPen(QPen(RULE, 2))
        p.drawLine(QPointF(pad, y), QPointF(W - pad, y))
        if not 0.0 <= k <= 1.0:
            return
        p.setPen(QPen(T.q(T.LEAD), 2))
        p.drawLine(QPointF(pad, y),
                   QPointF(pad + (W - pad * 2) * k, y))

    def _cell(self, p, k: int, box: QRectF, fm, first: int) -> None:
        s = self.syls[k]
        live = (not self._live and s.timed
                and s.start <= self.pos <= (s.end if s.end is not None
                                            else s.start))
        if k == self.at:
            fill, ink = CELL_AT, ON_ACCENT
        elif k in self.lit:
            fill, ink = CELL_SWEPT, TEXT
        elif live:
            fill, ink = CELL_LIVE, TEXT
        elif s.timed:
            fill, ink = CELL_TIMED, TEXT
        else:
            fill, ink = CELL, MUTE
        p.setBrush(fill)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(box, T.R_CHIP + 1, T.R_CHIP + 1)
        if k == self._hover and not self._live:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(T.q(T.LEAD), 1.4))
            p.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7),
                              T.R_CHIP + 1, T.R_CHIP + 1)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if k == first and not self._live:
            # Where a pass would sensibly begin: the first syllable with no
            # time on it. Half a row already timed is the ordinary state
            # after a drag that stopped short, and hunting for the seam by
            # eye is exactly the work this mark saves.
            p.setPen(QPen(T.q(T.LEAD), 1.8))
            p.drawLine(QPointF(box.left() + 2, box.top() + 4),
                       QPointF(box.left() + 2, box.bottom() - 4))
        p.setPen(QPen(ink, 1))
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter),
                   fm.elidedText(s.text, Qt.TextElideMode.ElideRight,
                                 box.width() - T.px(6)))

    # --------------------------------------------------------------- mouse
    def cell_at(self, x: float, y: float):
        """Which slice the pointer is on, never falling between two.

        The gaps drawn between the slices are not holes: each one belongs to
        the slice AFTER it, so the syllable changes the instant the pointer
        leaves the one it was on and there is nowhere on the bar where a drag
        stalls. Which row of a wrapped bar is decided first, by the nearest;
        left of everything on a row means that row's first slice, which is
        what a drag carrying on from the row above looks like.
        """
        if not self.cells:
            return None
        bands: dict = {}
        for k, c in enumerate(self.cells):
            bands.setdefault(round(c.top()), []).append(k)
        cell_h = getattr(self, "_cell_h", T.px(CELL_H))
        top = min(bands, key=lambda t: abs(y - (t + cell_h / 2)))
        band = bands[top]
        best = None
        for k in band:
            if x >= self.cells[k].left() - T.px(GAP):
                best = k
        return band[0] if best is None else best

    def mousePressEvent(self, ev) -> None:                # noqa: N802 (Qt name)
        if ev.button() != Qt.MouseButton.LeftButton or not self.syls:
            return
        k = self.cell_at(ev.position().x(), ev.position().y())
        if k is None or not self.ok():
            return
        self._live = True
        self.at, self._from, self.lit = k, k, set()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.begin.emit(k)
        self.update()

    def mouseMoveEvent(self, ev) -> None:                 # noqa: N802 (Qt name)
        k = self.cell_at(ev.position().x(), ev.position().y())
        if not self._live:
            if k != self._hover:
                self._hover = -1 if k is None else k
                self.update()
            return
        if k is None:
            return
        # Never behind where the pass began: winding back is for taking back
        # what this drag laid down, and carried past that it would stamp
        # earlier syllables with a later clock -- times in the wrong order,
        # with nothing to say so.
        k = max(k, self._from)
        if k == self.at:
            return
        if k > self.at:
            self.lit.update(range(self.at, k))
        else:
            self.lit.difference_update(range(k, self.at + 1))
        self.at = k
        self.moved.emit(k)
        self.update()

    def mouseReleaseEvent(self, _ev) -> None:             # noqa: N802 (Qt name)
        if not self._live:
            return
        self._live = False
        self.unsetCursor()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        at, self.at, self.lit = self.at, -1, set()
        self.done.emit(at)
        self.update()

    def leaveEvent(self, _ev) -> None:                    # noqa: N802 (Qt name)
        if self._hover != -1:
            self._hover = -1
            self.update()

    def cancel(self) -> None:
        """Let go of a pass without keeping it -- Escape, or leaving the mode."""
        if not self._live:
            return
        self._live = False
        self.at, self.lit = -1, set()
        self.unsetCursor()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancelled.emit()
        self.update()

    def keyPressEvent(self, ev) -> None:                  # noqa: N802 (Qt name)
        if ev.key() == Qt.Key.Key_Escape and self._live:
            self.cancel()
            ev.accept()
            return
        super().keyPressEvent(ev)
