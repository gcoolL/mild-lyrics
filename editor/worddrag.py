"""Double-click and drag in a QLineEdit selects by whole words.

Qt's line edit anchors the drag at the start of the double-clicked word and
moves by letters, so dragging back drops the word. QTextEdit already does
this right; this gives every QLineEdit in the app the same behaviour.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, QTextBoundaryFinder
from PyQt6.QtWidgets import QApplication, QLineEdit

_WORD = QTextBoundaryFinder.BoundaryType.Word


def reach(text: str, at: int, forward: bool) -> int:
    """The word boundary at or past `at`, in the direction of the drag."""
    f = QTextBoundaryFinder(_WORD, text)
    f.setPosition(max(0, min(at, len(text))))
    if f.isAtBoundary():
        return f.position()
    got = f.toNextBoundary() if forward else f.toPreviousBoundary()
    return got if got >= 0 else (len(text) if forward else 0)


class _Filter(QObject):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.box: QLineEdit | None = None
        self.word: tuple[int, int] | None = None

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt name)
        kind = ev.type()
        if kind == QEvent.Type.MouseButtonDblClick:
            if isinstance(obj, QLineEdit) and ev.button() == Qt.MouseButton.LeftButton:
                self.box, self.word = obj, None     # Qt picks the word itself
        elif kind == QEvent.Type.MouseMove:
            if obj is self.box and ev.buttons() & Qt.MouseButton.LeftButton:
                if self.word is None:
                    a = obj.selectionStart()
                    if a < 0:
                        self.box = None
                        return False
                    self.word = (a, a + len(obj.selectedText()))
                self._extend(obj, obj.cursorPositionAt(ev.position().toPoint()))
                return True
        elif kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonPress):
            if obj is self.box:
                self.box = None
        return False

    def _extend(self, box: QLineEdit, at: int) -> None:
        lo, hi = self.word
        text = box.text()
        if at > hi:
            box.setSelection(lo, reach(text, at, True) - lo)
        elif at < lo:
            box.setSelection(hi, reach(text, at, False) - hi)
        else:
            box.setSelection(lo, hi - lo)


_installed: _Filter | None = None


def install() -> None:
    """Put the filter on the application, once."""
    global _installed
    app = QApplication.instance()
    if app is None or _installed is not None:
        return
    _installed = _Filter(app)
    app.installEventFilter(_installed)
