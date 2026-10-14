"""Three hyphens typed in a row become an em dash, in the boxes words are
typed into. The setting is Words ▸ "Type --- as an em dash"."""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QLineEdit, QPlainTextEdit

from . import keys as K

KEY = "em_dash"
DASH = "—"
_CHORD = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
          | Qt.KeyboardModifier.MetaModifier)


def on() -> bool:
    return bool(K.config().get(KEY, True))


def swap(w) -> bool:
    """The third hyphen is being typed: put a dash where the two before it
    are, as one edit. False (and nothing done) where it does not apply."""
    if w.isReadOnly():
        return False
    if isinstance(w, QLineEdit):
        c = w.cursorPosition()
        if w.hasSelectedText() or w.text()[max(0, c - 2):c] != "--":
            return False
        w.setSelection(c - 2, 2)
        w.insert(DASH)
        return True
    if isinstance(w, QPlainTextEdit):
        cur = w.textCursor()
        if cur.hasSelection():
            return False
        cur.movePosition(QTextCursor.MoveOperation.Left,
                         QTextCursor.MoveMode.KeepAnchor, 2)
        if cur.selectedText() != "--":
            return False
        cur.insertText(DASH)
        w.setTextCursor(cur)
        return True
    return False


class _Dashes(QObject):
    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt name)
        return (ev.type() == QEvent.Type.KeyPress and ev.text() == "-"
                and not ev.modifiers() & _CHORD and on() and swap(obj))


def watch(w):
    """Turn --- into — as it is typed into `w` (a QLineEdit or
    QPlainTextEdit). The filter is the widget's child, so it lives as
    long as the widget does."""
    w.installEventFilter(_Dashes(w))
    return w
