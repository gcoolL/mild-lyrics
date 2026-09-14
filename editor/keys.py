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

Drag sync does the same job with the mouse -- see `editor/syncbar.py` -- and
has two keys of its own for the parts of it a hand holding the mouse cannot
reach: play this row's line again, and leave this row for the next.

Settings live beside the player's own, in the same directory and a different
file: `editor.json` next to `gui.json`. The player's settings have a schema
and a migration history and there is no reason for this to be inside it.
"""
from __future__ import annotations

import json
import pathlib
import sys
from html import escape

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QKeySequenceEdit, QLabel,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from . import theme as T

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "aligner", _HERE.parent)
                if str(p) not in sys.path]

ACTIONS = [
    ("sync_start", "Start this word here", "F", "Timing"),
    ("sync_next", "Commit: end it and start the next", "G", "Timing"),
    ("sync_end", "End this word here", "H", "Timing"),
    ("drag_replay", "Drag sync: play this row's line again", "R", "Timing"),
    ("drag_skip", "Drag sync: leave this row, arm the next", "E", "Timing"),
    ("prev_word", "Previous word", "A", "Moving"),
    ("next_word", "Next word", "S", "Moving"),
    ("prev_word_play", "Previous word, and play from it", "Shift+A", "Moving"),
    ("next_word_play", "Next word, and play from it", "Shift+S", "Moving"),
    ("prev_line", "Previous line", "W", "Moving"),
    ("next_line", "Next line", "X", "Moving"),
    ("play_pause", "Play / pause", "Space", "Transport"),
    # Not the bare arrows: those belong to the cursor, and binding them here
    # took them away from it -- pressing Left in the lyric moved the SONG a
    # quarter second instead of moving to the previous word.
    ("seek_back", "Back a quarter second", "Shift+Left", "Transport"),
    ("seek_fwd", "On a quarter second", "Shift+Right", "Transport"),
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
        pass


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

    def __init__(self, widget: QWidget, handlers: dict, can=None) -> None:
        super().__init__(widget)
        self.widget = widget
        self.handlers = handlers
        # `can(name)` answers (whether this action can be done at all right
        # now, and why not). Asked at the moment the key is pressed rather
        # than when it is bound, because the answer changes under the window:
        # the rate keys mean nothing while Spotify is the player and mean
        # something again the moment a local file is opened. Left off,
        # everything is always possible, which is what a caller with no
        # opinion means.
        self.can = can or (lambda _name: (True, ""))
        self.map = bindings()
        self._live: list = []
        self.install()

    def possible(self, name: str) -> tuple:
        try:
            got = self.can(name)
        except Exception:                                # noqa: BLE001
            return True, ""
        return (bool(got[0]), str(got[1])) if isinstance(got, tuple) else (bool(got), "")

    def install(self) -> None:
        for sc in self._live:
            sc.setParent(None)
        self._live = []
        for name, fn in self.handlers.items():
            key = self.map.get(name) or ""
            if not key:
                continue
            sc = QShortcut(QKeySequence(key), self.widget)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(lambda name=name, fn=fn: self._fire(name, fn))
            self._live.append(sc)

    def _fire(self, name: str, fn) -> None:
        """The action, or the reason it is not one right now.

        A key that silently does nothing reads as a key that is broken. A
        greyed-out button says why by being grey; a keyboard has no way to be
        grey, so it says it out loud instead -- once, on the press.
        """
        ok, why = self.possible(name)
        if not ok:
            say = getattr(self.widget, "say", None)
            if callable(say) and why:
                say(why)
            return
        fn()

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
    """Rebind anything, or put it all back.

    A tab per group, and each one scrolls. It was one grid of every action
    with the group names as captions inside it -- thirty rows in a dialog
    that cannot be scrolled and sizes itself to its contents, so on a short
    screen the buttons at the bottom were off the bottom and there was no way
    to reach the OK. Four short tabs fit anywhere, and they are also how
    anybody thinks about these: the timing keys are learnt together and the
    editing ones are looked up one at a time.

    An action that cannot be done in the window as it stands is shown greyed
    with the reason beside it -- the rate keys while Spotify is the player,
    the model key on a machine with no model. It is still rebindable: what is
    impossible now is not impossible, and a key you cannot press today is
    still a key you may want on a different button.
    """

    def __init__(self, keys: Keys, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keys")
        self.keys = keys
        box = QVBoxLayout(self)
        tabs = QTabWidget()
        self.edits: dict = {}
        # By group name, not by runs of it: ACTIONS lists the two nudge keys
        # under Timing well after Transport, and reading it as runs made a
        # second tab called Timing with two rows in it.
        groups: list = []
        where: dict = {}
        for name, label, _default, group in ACTIONS:
            if group not in where:
                where[group] = len(groups)
                groups.append((group, []))
            groups[where[group]][1].append((name, label))
        for group, rows in groups:
            page = QWidget()
            grid = QGridLayout(page)
            grid.setColumnStretch(0, 1)
            for r, (name, label) in enumerate(rows):
                ok, why = keys.possible(name)
                # The reason on its own line under the action, rather than run
                # on after a dash: these read as sentences and two of them in
                # a row read as neither.
                cap = QLabel(escape(label) if ok or not why else
                             f'{escape(label)}<br>'
                             f'<span style="color:#7f8496">{escape(why)}</span>')
                cap.setWordWrap(True)
                cap.setEnabled(ok)
                grid.addWidget(cap, r, 0)
                ed = QKeySequenceEdit(QKeySequence(keys.map.get(name, "")))
                ed.setMaximumSequenceLength(1)
                if not ok and why:
                    ed.setToolTip(why)
                grid.addWidget(ed, r, 1)
                self.edits[name] = ed
            grid.setRowStretch(len(rows), 1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            tabs.addTab(scroll, group)
        box.addWidget(tabs)
        back = QPushButton("Back to the defaults")
        back.clicked.connect(self._defaults)
        box.addWidget(back)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._save)
        btn.rejected.connect(self.reject)
        box.addWidget(btn)
        # Small enough for a laptop screen, and resizable from there. Sizing
        # itself to its contents is what put the buttons out of reach.
        self.resize(460, 420)

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
                b.setMinimumHeight(T.px(34) if r else T.px(26))
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
