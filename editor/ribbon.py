"""The bar across the top: what mode you are in, and what you can do in it.

A ribbon rather than a menu because this is a tool with about forty verbs in
it, and forty verbs behind a File/Edit/View menu is forty things nobody finds.
The mode buttons are deliberately large -- they are the most-used control in
the window and the one it is worst to miss.

Modes decide what is SHOWN, never what is possible. The timing keys work while
writing words and the word menu works while timing; the ribbon only puts away
the buttons that have nothing to say in the mode you are in.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from . import theme as T

MODES = [("edit", "Edit", "Write and arrange the words"),
         ("timing", "Timing", "Place them against the audio"),
         ("preview", "Preview", "Watch it play, the way the player draws it")]


class Group(QWidget):
    """One captioned cluster of buttons, two rows deep."""

    def __init__(self, name: str, items: list, parent=None) -> None:
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(T.GAP, 6, T.GAP, 4)
        box.setSpacing(4)
        grid = QGridLayout()
        grid.setSpacing(5)
        self.buttons: dict = {}
        for i, (label, fn, tip) in enumerate(items):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if fn is not None:
                b.clicked.connect(lambda _c=False, f=fn: f())
            grid.addWidget(b, i % 2, i // 2)
            self.buttons[label] = b
        box.addLayout(grid)
        cap = QLabel(name)
        cap.setFont(T.font(10, 600, caps=True))
        cap.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        cap.setStyleSheet(f"color:{T.MUTE};")
        box.addWidget(cap)


class Ribbon(QWidget):
    mode_changed = pyqtSignal(str)

    def __init__(self, spec: list, parent=None) -> None:
        """`spec` is [(group name, [modes it belongs to], [(label, fn, tip)])]."""
        super().__init__(parent)
        self.mode = "edit"
        bar = QHBoxLayout(self)
        bar.setContentsMargins(T.EDGE // 2, T.GAP, T.EDGE // 2, 0)
        bar.setSpacing(T.GROUP)

        # One well holding three segments, rather than three buttons floating
        # side by side: it is a single choice and should look like one.
        well = QWidget()
        well.setStyleSheet(f"background:{T.INK_1}; border:1px solid {T.LINE};"
                           f" border-radius:{T.R_BUTTON + 2}px;")
        wl = QHBoxLayout(well)
        wl.setContentsMargins(3, 3, 3, 3)
        wl.setSpacing(2)
        self.mode_buttons = QButtonGroup(self)
        self.mode_buttons.setExclusive(True)
        for key, label, tip in MODES:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setToolTip(tip)
            b.setProperty("mode", key)
            b.setProperty("mode", "1")
            b.setProperty("which", key)
            b.setMinimumHeight(40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
            self.mode_buttons.addButton(b)
            wl.addWidget(b)
        self.mode_buttons.buttons()[0].setChecked(True)
        bar.addWidget(well)

        self.groups: list = []
        for name, modes, items in spec:
            bar.addWidget(_rule())
            g = Group(name, items)
            self.groups.append((g, set(modes)))
            bar.addWidget(g)
        bar.addStretch(1)
        self.apply()

    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            self.apply()
            return
        self.mode = mode
        for b in self.mode_buttons.buttons():
            b.setChecked(b.property("which") == mode)
        self.apply()
        self.mode_changed.emit(mode)

    def apply(self) -> None:
        # Painted here rather than left to a :checked selector. Qt only
        # re-evaluates a stylesheet when it is set, and the checked segment
        # came out looking disabled -- the one control that must always be
        # legible is the one saying which mode you are in.
        for b in self.mode_buttons.buttons():
            on = b.property("which") == self.mode
            b.setStyleSheet(
                f"background:{T.LEAD if on else 'transparent'};"
                f"color:{'#0b1020' if on else T.MUTE};"
                f"border:none; border-radius:{T.R_BUTTON}px;"
                f"padding:10px 20px; font-size:13px; font-weight:600;")
        for g, modes in self.groups:
            g.setVisible(self.mode in modes)
            # The rule before a hidden group would be a stray line, so it
            # travels with it.
            rule = self._rule_before(g)
            if rule is not None:
                rule.setVisible(self.mode in modes)

    def _rule_before(self, widget):
        lay = self.layout()
        for i in range(lay.count()):
            if lay.itemAt(i).widget() is widget and i:
                return lay.itemAt(i - 1).widget()
        return None

    def button(self, label: str):
        for g, _modes in self.groups:
            if label in g.buttons:
                return g.buttons[label]
        return None


def _rule() -> QFrame:
    """A hairline that stops short of floor and ceiling."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedWidth(1)
    f.setContentsMargins(0, 10, 0, 10)
    f.setStyleSheet(f"background:{T.LINE}; border:none; margin:10px 0;")
    return f
