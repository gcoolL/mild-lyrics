"""Splitting a word by pointing at it.

Typing the first half was the wrong question to ask. It made the user spell
the word back to prove where the cut goes, it refused anything that was not a
prefix, and it could only ever make ONE cut -- so a word sung in three had to
be split, re-selected and split again.

Here the word is drawn as its letters with a gap between each pair, and the
gaps are what you click. Click one, it becomes a cut; click it again, it is
not. Any number of them, in any order, and the pieces are spelled out
underneath as they will be.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget,
)

from . import theme as T

GAP = 16.0
PAD = 18.0


class Letters(QWidget):
    """The word, with a cut-here slot between every pair of letters."""

    changed = pyqtSignal()

    def __init__(self, word: str, cuts=(), parent=None) -> None:
        super().__init__(parent)
        self.word = word
        self.cuts = set(int(c) for c in cuts if 0 < int(c) < len(word))
        self.hover = None
        self.setMouseTracking(True)
        self.setFont(T.font(30, 600))
        self.setMinimumHeight(int(T.px(84)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ------------------------------------------------------------ geometry
    def _slots(self) -> list:
        """(x of each gap, index) and the x each letter starts at."""
        fm = QFontMetricsF(self.font())
        xs, x = [], PAD
        for i, ch in enumerate(self.word):
            xs.append((x, i))
            wide = max(fm.horizontalAdvance(ch),
                       10.0 if (ch.isspace() or ch == "\u200b") else 0.0)
            x += wide + (GAP if i < len(self.word) - 1 else 0)
        return xs, x

    def sizeHint(self):                                   # noqa: N802 (Qt name)
        from PyQt6.QtCore import QSize
        _xs, end = self._slots()
        return QSize(int(end + PAD), int(T.px(84)))

    def _at(self, px: float):
        """The gap index nearest the pointer, or None if it is not near one."""
        xs, _end = self._slots()
        fm = QFontMetricsF(self.font())
        best, near = None, 1e9
        for x, i in xs:
            if i == 0:
                continue
            edge = x - GAP / 2
            if abs(px - edge) < near and abs(px - edge) <= GAP:
                best, near = i, abs(px - edge)
        return best

    # ------------------------------------------------------------- drawing
    def paintEvent(self, _ev) -> None:                    # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, T.q(T.INK_1))
        p.setPen(QPen(T.q(T.LINE), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), T.R_BUTTON, T.R_BUTTON)
        xs, _end = self._slots()
        fm = QFontMetricsF(self.font())
        mid = H / 2
        p.setFont(self.font())
        for x, i in xs:
            ch = self.word[i]
            if ch.isspace() or ch == "\u200b":
                p.setPen(QPen(T.q(T.FAINT), 1))
                w = max(fm.horizontalAdvance(ch), 6.0)
                p.drawEllipse(QPointF(x + w / 2, mid), 2.0, 2.0)
                continue
            p.setPen(QPen(T.q(T.TEXT), 1))
            p.drawText(QPointF(x, mid + fm.capHeight() / 2), ch)
            if i == 0:
                continue
            edge = x - GAP / 2
            cut, over = i in self.cuts, self.hover == i
            if cut or over:
                p.setPen(QPen(T.q(T.LEAD if cut else T.FAINT),
                              3.0 if cut else 1.5))
                p.drawLine(QPointF(edge, mid - fm.capHeight()),
                           QPointF(edge, mid + fm.capHeight() * 0.8))
        p.setPen(QPen(T.q(T.MUTE), 1))
        p.setFont(T.font(11, 500))
        p.drawText(QRectF(0, H - T.px(20), W, T.px(16)),
                   int(Qt.AlignmentFlag.AlignCenter),
                   "click between the letters")

    # --------------------------------------------------------------- mouse
    def mouseMoveEvent(self, ev) -> None:                 # noqa: N802 (Qt name)
        want = self._at(ev.position().x())
        if want != self.hover:
            self.hover = want
            self.update()

    def leaveEvent(self, _ev) -> None:                    # noqa: N802 (Qt name)
        self.hover = None
        self.update()

    def mousePressEvent(self, ev) -> None:                # noqa: N802 (Qt name)
        want = self._at(ev.position().x())
        if want is None:
            return
        self.cuts ^= {want}
        self.changed.emit()
        self.update()

    # -------------------------------------------------------------- result
    def pieces(self) -> list[str]:
        out, prev = [], 0
        for c in sorted(self.cuts):
            out.append(self.word[prev:c])
            prev = c
        out.append(self.word[prev:])
        return out


class SplitDialog(QDialog):
    """Where does this word come apart, and does it come apart everywhere?"""

    def __init__(self, word: str, cuts=(), everywhere: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Split a word")
        box = QVBoxLayout(self)
        box.setContentsMargins(T.EDGE, T.EDGE, T.EDGE, T.GAP * 2)
        box.setSpacing(T.GAP)
        self.letters = Letters(word, cuts)
        box.addWidget(self.letters)
        self.preview = QLabel("")
        self.preview.setFont(T.font(15, 500, mono=True))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self.preview)
        self.everywhere = QCheckBox(f"apply to every “{word}” in this song")
        self.everywhere.setChecked(bool(everywhere))
        self.everywhere.setToolTip(
            "A word is sung the same way wherever it appears, so this is "
            "normally what you want. It is remembered for the next song too.")
        box.addWidget(self.everywhere)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        ok = btn.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Split")
        ok.setProperty("primary", "1")
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        box.addWidget(btn)
        self.letters.changed.connect(self._show)
        self._show()
        self.resize(max(420, self.letters.sizeHint().width() + T.EDGE * 2), 260)

    def _show(self) -> None:
        pieces = self.letters.pieces()
        self.preview.setText(" | ".join(pieces) if len(pieces) > 1
                             else "no cuts — the word stays whole")

    def cuts(self) -> list[int]:
        return sorted(self.letters.cuts)

    def pieces(self) -> list[str]:
        return self.letters.pieces()
