"""The editor's keys, and the little file that remembers them.

Timing a lyric by hand is a keyboard job -- one hand on three keys, the other
on the transport -- so the three that matter are the ones AMLL's tool uses and
they are rebindable, because everybody who does this has already learned a
layout somewhere else:

    start   (F)   put this chip's start at the playhead, stay put
    commit  (G)   end this chip AND start the next one here, step on
    end     (H)   end this chip here, step on without starting the next

The middle one is the whole trick: tapped in time with the singing it walks a
line from beginning to end leaving no holes, because every tap closes the
piece before it. The other two are for the edges -- a first word coming out of
silence, a last word that rings on after it.

Settings live beside the player's own, in the same directory and a different
file: `editor.json` next to `gui.json`. The player's settings have a schema
and a migration history and there is no reason for this to be inside it.
"""
from __future__ import annotations

import json
import pathlib
import sys

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QKeySequenceEdit, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "aligner", _HERE.parent)
                if str(p) not in sys.path]

# (name, what it is called on screen, default key, group)
ACTIONS = [
    ("sync_start", "Start this word here", "F", "Timing"),
    ("sync_next", "Commit: end it and start the next", "G", "Timing"),
    ("sync_end", "End this word here", "H", "Timing"),
    ("prev_word", "Previous word", "A", "Moving"),
    ("next_word", "Next word", "S", "Moving"),
    ("prev_word_play", "Previous word, and play from it", "Shift+A", "Moving"),
    ("next_word_play", "Next word, and play from it", "Shift+S", "Moving"),
    ("prev_line", "Previous line", "W", "Moving"),
    ("next_line", "Next line", "X", "Moving"),
    ("play_pause", "Play / pause", "Space", "Transport"),
    ("seek_back", "Back a quarter second", "Left", "Transport"),
    ("seek_fwd", "On a quarter second", "Right", "Transport"),
    ("rate_down", "Slower", "[", "Transport"),
    ("rate_up", "Faster", "]", "Transport"),
    ("rate_reset", "Back to full speed", "\\", "Transport"),
    ("nudge_back", "Nudge this word back 20 ms", ",", "Timing"),
    ("nudge_on", "Nudge it on 20 ms", ".", "Timing"),
    ("split_line", "Split the line here", "Ctrl+Return", "Editing"),
    ("merge_lines", "Merge the selected lines", "Ctrl+M", "Editing"),
    ("duplicate", "Duplicate the selected lines", "Ctrl+D", "Editing"),
    ("flip_agent", "Main voice / duet voice", "Ctrl+T", "Editing"),
    ("auto_section", "Let the model time the selection", "Ctrl+R", "Editing"),
]
DEFAULTS = {name: key for name, _label, key, _group in ACTIONS}


# --------------------------------------------------------------------------
def _path() -> pathlib.Path:
    import lyrics_gui as L
    return L.app_dir("config") / "editor.json"


def config() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def remember(**values) -> None:
    """Keep a setting, leaving everything else in the file alone."""
    got = config()
    got.update(values)
    try:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(got, indent=1), encoding="utf-8")
    except Exception:
        pass                    # a settings file that will not write is not
        #                         a reason to stop editing


def bindings() -> dict:
    got = dict(DEFAULTS)
    for name, key in (config().get("keys") or {}).items():
        if name in got and isinstance(key, str):
            got[name] = key
    return got


# --------------------------------------------------------------------------
class Keys(QObject):
    """The bound shortcuts, rebuildable without restarting the window."""

    changed = pyqtSignal()

    def __init__(self, widget: QWidget, handlers: dict) -> None:
        super().__init__(widget)
        self.widget = widget
        self.handlers = handlers
        self.map = bindings()
        self._live: list = []
        self.install()

    def install(self) -> None:
        for sc in self._live:
            sc.setParent(None)
        self._live = []
        for name, fn in self.handlers.items():
            key = self.map.get(name) or ""
            if not key:
                continue
            sc = QShortcut(QKeySequence(key), self.widget)
            # WindowShortcut, not WidgetWithChildren: the strip, the list and
            # the ribbon are all children of the window and a tap has to work
            # wherever the focus happens to be sitting -- except in a text
            # box, which swallows it first because it has focus.
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(fn)
            self._live.append(sc)

    def set(self, mapping: dict) -> None:
        self.map = dict(DEFAULTS)
        self.map.update({k: v for k, v in mapping.items() if k in DEFAULTS})
        remember(keys={k: v for k, v in self.map.items()
                       if v != DEFAULTS.get(k)})
        self.install()
        self.changed.emit()

    def label(self, name: str) -> str:
        return self.map.get(name, "")


class KeyDialog(QDialog):
    """Rebind anything, or put it all back."""

    def __init__(self, keys: Keys, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keys")
        self.keys = keys
        box = QVBoxLayout(self)
        grid = QGridLayout()
        self.edits: dict = {}
        row, seen = 0, ""
        for name, label, _default, group in ACTIONS:
            if group != seen:
                seen = group
                cap = QLabel(group.upper())
                cap.setStyleSheet("color:#7f8496; margin-top:8px;")
                grid.addWidget(cap, row, 0, 1, 2)
                row += 1
            grid.addWidget(QLabel(label), row, 0)
            ed = QKeySequenceEdit(QKeySequence(keys.map.get(name, "")))
            ed.setMaximumSequenceLength(1)
            grid.addWidget(ed, row, 1)
            self.edits[name] = ed
            row += 1
        box.addLayout(grid)
        back = QPushButton("Back to the defaults")
        back.clicked.connect(self._defaults)
        box.addWidget(back)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._save)
        btn.rejected.connect(self.reject)
        box.addWidget(btn)

    def _defaults(self) -> None:
        for name, ed in self.edits.items():
            ed.setKeySequence(QKeySequence(DEFAULTS[name]))

    def _save(self) -> None:
        self.keys.set({name: ed.keySequence().toString()
                       for name, ed in self.edits.items()})
        self.accept()


class SyncPad(QWidget):
    """The same three actions, big enough to hit with a mouse.

    Not everybody times with two hands on the keyboard, and the labels double
    as the documentation for what the three keys actually do -- which is the
    part that is hard to guess.
    """

    fired = pyqtSignal(str)

    def __init__(self, keys: Keys, parent=None) -> None:
        super().__init__(parent)
        self.keys = keys
        self.buttons: dict = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        rows = [(0, [("prev_word", "◀  previous word", 3),
                     ("next_word", "next word  ▶", 3)]),
                (1, [("sync_start", "start", 2),
                     ("sync_next", "commit", 2),
                     ("sync_end", "end", 2)])]
        for r, items in rows:
            col = 0
            for name, label, span in items:
                b = QPushButton(label)
                b.setMinimumHeight(34 if r else 26)
                b.clicked.connect(lambda _c=False, n=name: self.fired.emit(n))
                grid.addWidget(b, r, col, 1, span)
                self.buttons[name] = (b, label)
                col += span
        keys.changed.connect(self.relabel)
        self.relabel()

    def relabel(self) -> None:
        for name, (b, label) in self.buttons.items():
            key = self.keys.label(name)
            b.setText(f"{label}   ({key})" if key else label)
