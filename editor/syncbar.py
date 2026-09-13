"""The bar you drag across to time a row.

Drag sync began on the words themselves, and on the words it does not work.
The thing you are aiming at is a chip drawn the width of what it says, so
"cannot" is eighty pixels and "I" is eighteen -- and the syllables you most
need to place accurately are, without fail, the short ones. A line of
one-syllable words is a row of slivers, and the drag misses them at speed.

So the bar is the row laid out again, with two rules rather than one.

A slice is as wide as the word is long, so the bar has the same shape as the
line above it: the eye can find "extraordinarily" on the bar without reading
anything, and a hand that already knows the line knows how far along it is.
That much is just the lyric.

What the lyric cannot do is the second rule: NO SLICE IS EVER NARROWER THAN
`MIN_CELL`, whatever its word says. "I" gets the floor, and so does "a", and
so does a comma sung on its own. Below that width a syllable is crossed by
accident at the speed a hand moves through a fast line, which was the whole
complaint. Everything above the floor is shared out by length -- see `_share`,
which pins the short ones and scales the rest into what is left, so the row
still ends exactly at the right-hand edge.

A row whose slices will not fit at those widths wraps, the way the lyric does,
rather than shrinking them back down to slivers. The drag carries on from the
end of one line to the start of the next.

Nothing in here knows what time it is. It says which syllable the pointer is
on and the window turns that into seconds, exactly as the list does -- see
`Editor._sweep_begin`.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from . import theme as T

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

PAD = 10.0
GAP = 3.0
CAP_H = 15.0
CELL_H = 44.0
TEXT_PX = 13
# Room around the word inside its slice. Generous, because a slice is a
# target before it is a label: this is most of what a short word's width is.
TEXT_PAD = 30.0
# The narrowest a slice is allowed to get, however short its word. Wide enough
# that a syllable cannot be crossed by accident at the speed a hand moves
# through a fast line, which is what the whole widget is for.
MIN_CELL = 58.0


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
        """Where every slice goes: by the length of its word, with a floor.

        Worked in PITCH -- what a slice takes up including the gap drawn after
        it -- rather than in the drawn width, so the sums come out on the
        edge of the bar and the gap never has to be accounted for twice.
        MIN_CELL is the drawn width, so the floor on a pitch is one gap more.
        """
        self.cells = []
        self._rows = 1
        n = len(self.syls)
        if not n:
            self.updateGeometry()
            return
        pad, gap = T.px(PAD), T.px(GAP)
        cell_h = T.px(CELL_H)
        floor = T.px(MIN_CELL) + gap
        room = max(floor, self.width() - pad * 2)
        fm = QFontMetricsF(T.font(TEXT_PX, 600))
        # What each slice would like to be: its word as it is actually drawn,
        # with room around it. NOT floored yet -- flooring here would make "I"
        # and "the" the same width before anything was shared out, and they
        # are not the same length. The floor is applied on the way out, by
        # `_share`, to whichever slices the sharing would actually have taken
        # under it.
        #
        # The padding is most of a short word's width on purpose. Without it
        # "I" would be a twentieth of "extraordinarily", which is proportional
        # and unusable; with it the spread is about four to one, which reads
        # as the shape of the line and still leaves every word a target.
        want = [fm.horizontalAdvance(s.text) + T.px(TEXT_PAD) + gap
                for s in self.syls]
        # Packing goes by what a slice will END UP taking, floor included, or
        # a row could be filled with words too short to honour the floor in.
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
            # Every row is stretched to the full width so that the end of the
            # bar is the end of the row -- except the last of several, which
            # is a remainder and would be stretched out of all proportion to
            # the rows above it. One row on its own is not a remainder.
            widths = ([need[k] for k in row]
                      if r == len(rows) - 1 and len(rows) > 1
                      else _share([want[k] for k in row], room, floor))
            x = pad
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
        top = min(bands, key=lambda t: abs(y - (t + T.px(CELL_H) / 2)))
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
