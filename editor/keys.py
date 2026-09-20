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
sys.path[:0] = [str(p) for p in (_HERE.parent / "mild-lyrics", _HERE.parent)
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
LABELS = {name: label for name, label, _key, _group in ACTIONS}
GROUPS = {name: group for name, _label, _key, group in ACTIONS}
ORDER = {name: i for i, (name, _l, _k, _g) in enumerate(ACTIONS)}

FIXED = [
    ("Ctrl+=", "Bigger text"),
    ("Ctrl++", "Bigger text"),
    ("Ctrl+-", "Smaller text"),
    ("Ctrl+0", "Text back to its own size"),
    ("Ctrl+N", "New lyric"),
    ("Ctrl+O", "Open a lyric"),
    ("Ctrl+I", "Import words"),
    ("Ctrl+S", "Save"),
    ("Ctrl+Shift+S", "Save a copy"),
    ("Ctrl+Shift+O", "Open audio"),
    ("Ctrl+Z", "Undo"),
    ("Ctrl+Shift+Z", "Redo"),
    ("Ctrl+Y", "Redo"),
]


# --------------------------------------------------------------------------
def canon(key) -> str:
    """The one spelling of a key, so that two of them can be compared.

    `f`, `F` and `Ctrl+s` are the same keys as `F`, `F` and `Ctrl+S`, and
    a clash that is only spelt differently is still a clash. Anything Qt
    cannot read back -- a hand-edited `editor.json` saying `zzz` -- comes
    back empty, which is the same as no key at all.
    """
    try:
        seq = QKeySequence(str(key or ""))
    except Exception:                                    # noqa: BLE001
        return ""
    if seq.isEmpty():
        return ""
    for i in range(seq.count()):
        if seq[i].key() == Qt.Key.Key_unknown:
            return ""
    return seq.toString()


def fixed() -> dict:
    """The keys the window keeps for itself: spelling -> what it does."""
    got = {}
    for key, what in FIXED:
        seq = canon(key)
        if seq:
            got.setdefault(seq, what)
    return got


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
        self.can = can or (lambda _name: (True, ""))
        self.map = bindings()
        self.clashes: dict = {}
        self._live: list = []
        self.install()

    def possible(self, name: str) -> tuple:
        try:
            got = self.can(name)
        except Exception:                                # noqa: BLE001
            return True, ""
        return (bool(got[0]), str(got[1])) if isinstance(got, tuple) else (bool(got), "")

    def _order(self) -> list:
        """The handlers in the order the list of actions puts them.

        Which of two actions sharing a key gets to keep it has to be the
        same answer every time the window opens, and a dictionary's order
        is the order a handler happened to be written down in.
        """
        return sorted(self.handlers, key=lambda n: ORDER.get(n, len(ORDER)))

    def install(self) -> None:
        """Bind every action to its key -- one action per key.

        Qt will take two shortcuts on one key, match both and then call
        neither: the press arrives as `activatedAmbiguously`, which nothing
        was listening to. So the two keys that clashed both went dead, which
        is the worst of the three possible outcomes and the one that reads
        as the whole window being broken. A key is given to one action here
        -- the first that asks for it -- and the other is left unbound and
        remembered in `clashes`, to be said out loud rather than discovered.
        """
        for sc in self._live:
            sc.setParent(None)
            sc.deleteLater()
        self._live = []
        self.clashes = {}
        taken = fixed()
        for name in self._order():
            fn = self.handlers[name]
            key = canon(self.map.get(name))
            if not key:
                continue
            if key in taken:
                self.clashes[name] = taken[key]
                continue
            taken[key] = LABELS.get(name, name)
            sc = QShortcut(QKeySequence(key), self.widget)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(lambda name=name, fn=fn: self._fire(name, fn))
            sc.activatedAmbiguously.connect(
                lambda name=name: self._ambiguous(name))
            self._live.append(sc)
        self._complain()

    def _say(self, text: str) -> None:
        """Put something in the window's status line, if it has one yet.

        The first `install` happens while the window is still being built,
        before there is a status line to say anything into.
        """
        say = getattr(self.widget, "say", None)
        if not callable(say):
            return
        try:
            say(text)
        except Exception:                                # noqa: BLE001
            pass

    def _complain(self) -> None:
        """Name a key that was asked for twice, rather than losing it."""
        if not self.clashes:
            return
        name, holder = min(self.clashes.items(),
                           key=lambda kv: ORDER.get(kv[0], len(ORDER)))
        rest = len(self.clashes) - 1
        more = f", and {rest} more" if rest else ""
        self._say(f"“{LABELS.get(name, name)}” has no key: "
                  f"{canon(self.map.get(name))} is “{holder}”{more} — "
                  f"File ▸ Keys… to give it one")

    def _ambiguous(self, name: str) -> None:
        self._say(f"that key is on more than one thing — "
                  f"“{LABELS.get(name, name)}” is one of them; "
                  f"File ▸ Keys… to sort it out")

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

    def set(self, mapping: dict) -> dict:
        """Take a new layout, keep it, and say what had to give way.

        One key, one action. A key asked for twice goes to whichever of the
        two is being CHANGED -- that is the one the hand at the dialog just
        typed, and the other is the one it meant to take it from -- and the
        loser is handed nothing and named in what comes back, so the caller
        can say whose key has just gone. A key the window keeps for itself
        cannot be taken at all: Ctrl+S is Save, and an action bound to it
        used to kill Save and itself together.
        """
        want = dict(DEFAULTS)
        want.update({k: v for k, v in mapping.items() if k in DEFAULTS})
        same = {n: canon(want[n]) == canon(self.map.get(n)) for n in want}
        order = sorted(want, key=lambda n: (same[n], ORDER.get(n, len(ORDER))))
        taken, lost = fixed(), {}
        for name in order:
            key = canon(want[name])
            if not key:
                want[name] = ""
            elif key in taken:
                lost[name] = taken[key]
                want[name] = ""
            else:
                taken[key] = LABELS.get(name, name)
                want[name] = key
        self.map = want
        remember(keys={k: v for k, v in want.items()
                       if v != canon(DEFAULTS.get(k))})
        self.install()
        self.changed.emit()
        return lost

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

    A key is taken off whatever held it the moment it is typed, and that row
    says so. Typing over a key you have already used is the ordinary way to
    move one -- you go to the action you want it on, not to the one you want
    it off -- and leaving both rows holding it is what killed them both.
    """

    NOTE = '<span style="color:%s">%s</span>'

    def __init__(self, keys: Keys, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Keys")
        self.keys = keys
        self.edits: dict = {}
        self.notes: dict = {}
        self.why: dict = {}
        self._seen: dict = {}
        self._quiet = False
        box = QVBoxLayout(self)
        tabs = QTabWidget()
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
                cap = QLabel(label)
                cap.setTextFormat(Qt.TextFormat.PlainText)
                cap.setWordWrap(True)
                cap.setEnabled(ok)
                grid.addWidget(cap, r * 2, 0)
                note = QLabel("")
                note.setTextFormat(Qt.TextFormat.RichText)
                note.setWordWrap(True)
                note.setVisible(False)
                note.setContentsMargins(0, 0, 0, 4)
                grid.addWidget(note, r * 2 + 1, 0, 1, 3)
                ed = QKeySequenceEdit(QKeySequence(canon(keys.map.get(name))))
                ed.setMaximumSequenceLength(1)
                if not ok and why:
                    ed.setToolTip(why)
                ed.keySequenceChanged.connect(
                    lambda _s, n=name: self._typed(n))
                grid.addWidget(ed, r * 2, 1)
                off = QPushButton("✕")
                off.setProperty("ghost", "1")
                off.setFixedWidth(T.px(28))
                off.setToolTip("No key for this")
                off.clicked.connect(lambda _c=False, n=name: self._off(n))
                grid.addWidget(off, r * 2, 2)
                self.edits[name] = ed
                self.notes[name] = note
                self.why[name] = why if not ok else ""
                self._seen[name] = canon(keys.map.get(name))
            grid.setRowStretch(len(rows) * 2, 1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            tabs.addTab(scroll, group)
        box.addWidget(tabs)
        self.told = QLabel("")
        self.told.setTextFormat(Qt.TextFormat.RichText)
        self.told.setWordWrap(True)
        self.told.setContentsMargins(2, 2, 2, 2)
        box.addWidget(self.told)
        back = QPushButton("Back to the defaults")
        back.clicked.connect(self._defaults)
        box.addWidget(back)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self._save)
        btn.rejected.connect(self.reject)
        box.addWidget(btn)
        self.resize(460, 420)
        self._retell()

    # ------------------------------------------------------------- the rows
    def _typed(self, name: str) -> None:
        """A key has just been typed into one of the boxes.

        The dialog used to take whatever was typed and hand the lot to
        `Keys.set` at OK, so a key typed onto a second action left it on
        the first as well and both stopped working -- with the dialog
        showing the same key twice and saying nothing about it. Here the
        row that held it gives it up as you type, in front of you.

        `_seen` is what each box last said, because Qt reports a box that
        has not changed: a second after the key lands, the edit finishes
        itself and says so again, and a run of that wiped the line saying
        where the key had just gone.
        """
        if self._quiet:
            return
        key = canon(self.edits[name].keySequence().toString())
        if self._seen.get(name) == key:
            return
        self._seen[name] = key
        held = fixed().get(key, "")
        if key and held:
            self._put(name, self.keys.map.get(name))
            self._note(name, f"{key} is “{held}” — the window keeps that one",
                       T.WARN)
            self._announce(f"{key} is “{held}” — the window keeps that one",
                           T.WARN)
            return
        took = set()
        for other, ed in self.edits.items():
            if other != name and key and canon(ed.keySequence().toString()) == key:
                self._put(other, "")
                self._note(other, f"{key} has gone to “{LABELS[name]}”")
                took.add(other)
        self._retell(skip={name} | took)
        if took:
            first = min(took, key=lambda n: ORDER.get(n, len(ORDER)))
            rest = len(took) - 1
            self._announce(
                f"{key} taken off “{LABELS[first]}”"
                + (f" and {rest} more" if rest else "")
                + f" — the {GROUPS.get(first, '')} tab has a row"
                  " with no key now")
        else:
            self._announce("")

    def _off(self, name: str) -> None:
        self._put(name, "")
        self._retell()
        self._announce(f"“{LABELS[name]}” has no key now")

    def _announce(self, text: str, colour: str = T.BACK) -> None:
        """The dialog's own line, for what happened on a tab you cannot see.

        Taking a key off another action is the right thing to do and an
        invisible one when that action is on one of the other three tabs,
        so it is also said here, under all four of them.
        """
        self.told.setText(self.NOTE % (colour, escape(text)) if text else "")

    def _put(self, name: str, key) -> None:
        """Set a box without it reading as something somebody typed."""
        was, self._quiet = self._quiet, True
        try:
            self._seen[name] = canon(key)
            self.edits[name].setKeySequence(QKeySequence(self._seen[name]))
        finally:
            self._quiet = was

    def _note(self, name: str, text: str, colour: str = T.BACK) -> None:
        note = self.notes[name]
        note.setText(self.NOTE % (colour, escape(text)))
        note.setVisible(bool(text))

    def _retell(self, skip=()) -> None:
        """What every row says when it has no news of its own.

        Either what that action cannot do in the window as it stands, or
        that it has no key at all. An action with no key is a real thing
        to want and an invisible thing to have -- an empty box reads as a
        box nobody has got to yet -- so it is written down.
        """
        for name, ed in self.edits.items():
            if name in skip:
                continue
            if not canon(ed.keySequence().toString()):
                self._note(name, "no key", T.MUTE)
            elif self.why.get(name):
                self._note(name, self.why[name], T.MUTE)
            else:
                self._note(name, "")

    # ------------------------------------------------------------- the deed
    def _defaults(self) -> None:
        for name in self.edits:
            self._put(name, DEFAULTS[name])
        self._retell()
        self._announce("every key back where it started")

    def _save(self) -> None:
        """Keep the layout, and say on the way out what has no key.

        An action with no key is a thing somebody may well have meant, and
        a thing nobody can see from the window -- the button still works and
        the key just does nothing. So the window says which, once.
        """
        want = {name: ed.keySequence().toString()
                for name, ed in self.edits.items()}
        self.keys.set(want)
        bare = [n for n in self.keys.map if not canon(self.keys.map[n])]
        if bare:
            first = min(bare, key=lambda n: ORDER.get(n, len(ORDER)))
            rest = len(bare) - 1
            self.keys._say(f"“{LABELS[first]}” has no key"
                           + (f", and {rest} more" if rest else "")
                           + " — File ▸ Keys… to give it one")
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
