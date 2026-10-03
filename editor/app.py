"""The TTML Editor's window: the lyric line per line, and the audio under it.

The shape is AMLL's, because AMLL's is right: a ribbon across the top for what
you can do, and under it the whole lyric as a list of lines you can point at,
one under the other. A word is a chip; a chip carries its own time; the same
click that selects a word to rewrite selects it to time.

    ribbon      Edit | Timing | Drag sync | Preview, and the mode's buttons
    transport   play, clock, speed, and what the player is doing
    waveform    a strip that folds away when it is not wanted
    the bar     in drag sync only: the armed row as slices to drag across
    the lyric   line per line, chips per syllable, times down the right

There are four modes and they only decide what is SHOWN. The timing keys work
while writing words and the word menu works while timing -- a mode that took
things away would just be the two small tabs again with bigger buttons. Drag
sync is the one exception, and only over the mouse: the left button there is
the gesture, so it cannot also be picking rows up and carrying them about.

Everything that changes the document goes through `do()`, so undo is one stack
of snapshots and the live push to Mild Lyrics happens in exactly one place.
"""
from __future__ import annotations

import pathlib
import sys
import time
import traceback

from PyQt6.QtCore import QObject, QPoint, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QScrollArea, QSizePolicy,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSlider, QStackedWidget,
    QVBoxLayout, QWidget,
)

PUSH_MS = 180
CHROME_HZ = 30.0

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path[:0] = [str(p) for p in (_ROOT / "mild-lyrics", _ROOT)
                if str(p) not in sys.path]

import saves  # noqa: E402  (mild-lyrics/saves.py, on the path above)
from frame_clock import FrameClock  # noqa: E402  (mild-lyrics/frame_clock.py)
from . import (backups, collab_ui, keys as K,                 # noqa: E402
               lineview as lineview_mod, model as M, ops, settings, sources,
               syncbar as syncbar_mod, vocalmap, waveform)
from .lineview import LineList                                        # noqa: E402
from .link import Link                                                # noqa: E402
from .player import LocalPlayer, Player, SpotifyPlayer                # noqa: E402
from .ribbon import Ribbon                                            # noqa: E402
from .syncbar import SyncBar                                          # noqa: E402
from .start import AudioPick, StartPage, _reason, read_lyric           # noqa: E402

AUDIO = "Audio (*.wav *.flac *.mp3 *.m4a *.ogg *.opus *.aac *.webm);;All files (*)"
from . import theme as T
from . import glass as G
from . import gpu as GPU
import interface as IFACE  # noqa: E402  (mild-lyrics/interface.py)
import spicy_lyrics as SL  # noqa: E402
import lyric_formats as F  # noqa: E402  (mild-lyrics/lyric_formats.py)


def _fmt(t: float | None) -> str:
    if t is None:
        return "—"
    return f"{int(t) // 60}:{int(t) % 60:02d}.{int(round(t * 1000)) % 1000:03d}"


class Work(QObject):
    """One background errand, on a thread of its own.

    Everything slow here is either the network or the timing model, and both
    would freeze a window whose whole job is following audio in real time.
    """

    done = pyqtSignal(object, str)
    said = pyqtSignal(str)

    def __init__(self, fn) -> None:
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            got = self.fn(self.said.emit)
        except Exception as exc:                        # noqa: BLE001
            traceback.print_exc()
            self.done.emit(None, f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(got, "")


def _confirm(parent, row: dict) -> bool:
    """Ask before clearing one of the caches that is not merely derived.

    Only these get a question. Everything else on that dialogue comes back by
    itself and asking about it would train people to click through the one
    that matters.
    """
    return QMessageBox.question(
        parent, "Clear " + row["label"].lower() + "?",
        f"{row['label']} — {row['human']}\n\n{row['note']}\n\n"
        "This one is not just re-fetched. Clear it?") == \
        QMessageBox.StandardButton.Yes


# --------------------------------------------------------------------------
class Editor(QMainWindow):
    def __init__(self, args) -> None:
        super().__init__()
        self.setWindowTitle("Mild Lyrics TTML Editor")
        _fit_screen(self, 1340, 880)
        saves.ensure()
        self.args = args
        self.doc = M.Doc()
        self.path: pathlib.Path | None = None
        self.dirty = False
        self._undo: list = []
        self._redo: list = []
        self._lanes: dict = {}
        self._jobs: list = []
        self._chore = None
        self._chore_worker = None
        self.song_id: int | None = None
        self.audio_url = ""      # where the open audio was downloaded from
        self.meta_extra: dict = {}
        self._said_untimed = False
        self._sweeping: dict | None = None

        self.link = Link(self)
        self.link.connected.connect(self._linked)
        self.link.state.connect(self._player_state)
        self._repush_at = 0.0
        self._following = False
        self._follow_sent = None
        self.link.refused.connect(
            lambda why: self.say(f"the player did not take that — {why}"))
        self.link.asked.connect(self._player_asked)
        self.player: Player = Player(self)
        # Multiplayer (collab_ui.py). Before _build: the ribbon names it.
        self.collab = collab_ui.Controller(self)

        self._build()
        self.set_source(args.source)

        # Once per refresh while anything moves -- see frame_clock -- and the
        # thirty a second the editor always ran at while nothing does.
        self._chrome_at = 0.0
        self.frames = FrameClock(self, self._frame, busy=self._moving)
        self.frames.start()
        self.push_timer = QTimer(self)
        self.push_timer.setSingleShot(True)
        self.push_timer.timeout.connect(self._push)
        self.save_timer = QTimer(self)
        self.save_timer.timeout.connect(self._autosave)
        self.save_timer.start(30000)
        self.state_timer = QTimer(self)
        self.state_timer.timeout.connect(self.link.flush)
        self.state_timer.timeout.connect(self.link.ask_state)
        self.state_timer.timeout.connect(self._follow_tick)
        self.state_timer.start(120)

        if args.open:
            self.open_lyric(args.open)
        if args.audio:
            self.open_audio(args.audio)

    # ------------------------------------------------------------- building
    def _build(self) -> None:
        T.scale()
        T.accent()
        T.set_look(IFACE.get())
        self._repalette()
        app = QApplication.instance()
        if app is not None:
            app.setFont(T.font(13, 500))
        self.setStyleSheet(self._sheet())
        self.backdrop = G.Backdrop()
        self.setCentralWidget(self.backdrop)
        floor = QVBoxLayout(self.backdrop)
        floor.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        floor.addWidget(self.stack)

        self.start = StartPage(self)
        self.start.loaded.connect(self.take_doc)
        self.stack.addWidget(self.start)
        self.keys = K.Keys(self, self._key_handlers(), self.key_possible)
        self.stack.addWidget(self._editor_page())
        self.stack.setCurrentIndex(0)
        self.drawer = G.Drawer(self.keys,
                               lambda: settings.sections(classic=False),
                               self.backdrop)
        self.drawer.changed.connect(self.apply_settings)
        self.drawer.interface.connect(self.set_interface)
        self.toast = G.Toast(self.backdrop)
        # Both come up over the waveform and the list -- see gpu.overlay.
        GPU.overlay(self.drawer)
        GPU.overlay(self.toast)
        self.backdrop.installEventFilter(self)
        self._iface_watch = IFACE.Watch(self, self._iface_from_player)
        self.set_mode("edit")
        self._file_actions()
        self._lay_page()

    @staticmethod
    def _sheet() -> str:
        return T.sheet_new() if T.LOOK == "new" else T.sheet()

    def classic(self) -> bool:
        return T.LOOK != "new"

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802 (Qt name)
        if obj is getattr(self, "backdrop", None) and ev.type() == ev.Type.Resize:
            if self.drawer.isVisible():
                self.drawer.place()
        return False

    def _editor_page(self) -> QWidget:
        """The editing page: the same widgets in either interface.

        Built once. `_lay_page` puts them in the classic arrangement -- the
        ribbon, the long transport row, the strip, the list -- or the new one,
        which is the player's: a slim toolbar, the transport as a pane of
        glass, and the strip and the list as panes of their own.
        """
        page = QWidget()
        self.page_box = QVBoxLayout(page)
        self.page_box.setSpacing(0)

        self.ribbon = Ribbon(self._ribbon_spec())
        self.ribbon.mode_changed.connect(self.set_mode)
        self._tips = {label: b.toolTip()
                      for g, _modes in self.ribbon.groups
                      for label, b in g.buttons.items()}
        self.keys.changed.connect(self.retip)
        self.retip()
        self.ribbon.setMinimumWidth(self.ribbon.sizeHint().width())
        self.ribbon_scroll = _scroller(self.ribbon)
        for name in ("Save", "Time selection"):
            b = self.ribbon.button(name)
            if b is not None:
                b.setProperty("primary", "1")
        self.ribbon_rule = _hrule()
        self._transport()
        self.transport_holder = QWidget()
        self.tc_lay = QHBoxLayout(self.transport_holder)
        self.transport_scroll = _scroller(self.transport_holder)
        self.transport_new = G.glass()
        # Wraps where the window is narrower than the bar -- see G.Wrap.
        self.tn_lay = G.Wrap(self.transport_new)
        self.nudge_well = QFrame()
        self.nudge_well.setProperty("well", "1")
        self.nw_lay = QHBoxLayout(self.nudge_well)
        self.link_frame = QFrame()
        self.link_frame.setProperty("splitl", "1")
        self.lf_lay = QHBoxLayout(self.link_frame)
        self.toolbar = self._toolbar()

        self.strip_w = QWidget()
        strip = self.strip_lay = QHBoxLayout(self.strip_w)
        self.wave_box = QFrame()
        wl = self.wave_lay = QVBoxLayout(self.wave_box)
        wl.setSpacing(2)
        head = self.wave_head = QHBoxLayout()
        self.wave_cap = QLabel("Waveform")
        self.wave_cap.setProperty("caption", "1")
        self.wave_cap.setFont(T.font(10, 600, caps=True))
        head.addWidget(self.wave_cap)
        head.addStretch(1)
        self.roman_wave_sw = G.Switch("Reading only")
        self.roman_wave_sw.setToolTip("Label the blocks with the romanisation "
                                      "instead of the words")
        self.roman_wave_sw.setChecked(bool(settings.roman("roman_wave")))
        self.roman_wave_sw.toggled.connect(
            lambda on: self.apply_settings(self._keep(roman_wave=bool(on))))
        head.addWidget(self.roman_wave_sw)
        self.lanes_note = QLabel("")
        self.lanes_note.setProperty("faint", "1")
        head.addWidget(self.lanes_note)
        self.lanes_btn = QPushButton("")
        self.lanes_btn.setProperty("ghost", "1")
        self.lanes_btn.setToolTip("Voices that overlap get a lane each")
        self.lanes_btn.clicked.connect(self.toggle_lanes)
        head.addWidget(self.lanes_btn)
        self.fold_btn = QPushButton("fold ▲")
        self.fold_btn.setProperty("ghost", "1")
        self.fold_btn.clicked.connect(self.toggle_fold)
        head.addWidget(self.fold_btn)
        wl.addLayout(head)
        self.wave = waveform.Wave()
        self.wave.lanes_all = bool(K.config().get("lanes_all", True))
        self.wave.show_loose = bool(K.config().get("wave_loose", True))
        self.wave.setMinimumHeight(T.px(120))
        self.wave.setMaximumHeight(
            T.px(float(K.config().get("wave_height", 210.0))))
        self.wave.seeked.connect(self.seek)
        self.wave.follow_changed.connect(
            lambda on: self.follow_box.setChecked(on))
        self.wave.moved.connect(self._dragged)
        self.wave.picked.connect(self._wave_picked)
        wl.addWidget(self.wave, 1)
        strip.addWidget(self.wave_box, 1)

        self.sync_pad = K.SyncPad(self.keys)
        self.sync_pad.fired.connect(self.fire)
        self.sync_pad.setFixedWidth(max(T.px(300),
                                        self.sync_pad.sizeHint().width()))
        strip.addWidget(self.sync_pad, 0, Qt.AlignmentFlag.AlignBottom)

        self.bar = SyncBar()
        self.bar.ok = self._sweep_ok
        self.bar.begin.connect(self._sweep_begin)
        self.bar.moved.connect(self._sweep_to)
        self.bar.done.connect(self._sweep_done)
        self.bar.cancelled.connect(self._sweep_cancelled)
        self._dress_bar()
        self.bar_box = QFrame()
        bl = QVBoxLayout(self.bar_box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.bar)
        self.bar_box.setVisible(False)

        self.list = LineList()
        self.list.auto_split = self.auto_split_args
        self.list.tap_mode = self._tap_mode()
        self.list.will_edit.connect(self.push_undo)
        self.list.edited.connect(self._list_edited)
        self.list.cursor_changed.connect(self._cursor_moved)
        self.list.word_changed.connect(self.remember_word)
        self.list.selection_changed.connect(self._selection_changed)
        self.list.seek_to.connect(self.seek)
        self.list.armed.connect(lambda _i, _v: self.fill_bar())
        self.list.roman_edited.connect(self._roman_typed)
        self.list_box = QFrame()
        ll = self.list_lay = QVBoxLayout(self.list_box)
        ll.setContentsMargins(0, 0, 0, 0)
        self._find_bar(ll)
        ll.addWidget(self.list)

        self.status = QLabel("")
        self.status.setProperty("hint", "1")
        _shrinkable(self.status, 16777215)
        self.status_row = QWidget()
        self.sr_lay = QHBoxLayout(self.status_row)
        self._roman_look()

        if K.config().get("wave_folded"):
            self.toggle_fold()
        return page

    # ------------------------------------------------------ the new toolbar
    NEW_BAR = {
        "edit": ([("Lines", "Split"), ("Lines", "Merge")],
                 [("Lines", ["Lines"]), ("Words", ["Words"]),
                  ("Voices", ["Voices"]), ("Romanisation", ["Romanisation"])]),
        "timing": ([("Timing", "Spread"), ("Timing", "−0.05s"),
                    ("Timing", "+0.05s")],
                   [("Lines", ["Lines"]), ("Timing", ["Timing", "Timing 2"]),
                    ("Vocal", ["Vocal"])]),
        "drag": ([("Drag sync", "Play the row"), ("Drag sync", "Skip it")],
                 [("Drag sync", ["Drag sync"]), ("Lines", ["Lines"]),
                  ("Timing", ["Timing"])]),
        "preview": ([("Preview", "From the top"),
                     ("Preview", "From this line")], []),
    }
    ACT_KEYS = {"Split": "split_line", "Merge": "merge_lines",
                "Duplicate": "duplicate", "Main / duet": "flip_agent",
                "Start": "sync_start", "Commit": "sync_next",
                "End": "sync_end", "Play the row": "drag_replay",
                "Skip it": "drag_skip"}
    DANGER = {"Delete", "Clear", "Clear the row", "Clear romanisation"}

    def _groups_by_name(self) -> dict:
        """The ribbon's groups by name; a second group of the same name is
        "Timing 2"."""
        out: dict = {}
        for name, _modes, items in self._ribbon_spec():
            key = name if name not in out else f"{name} 2"
            out[key] = items
        return out

    def _item(self, label: str, fn, tip: str) -> dict:
        key = ""
        act = self.ACT_KEYS.get(label)
        if act:
            key = self.keys.label(act)
        elif label in ("Import…", "Save"):
            key = {"Import…": "Ctrl+I", "Save": "Ctrl+S"}[label]
        toggle = {"Vocal view": lambda: bool(self.wave.show_vocal),
                  "Marks": lambda: bool(self.wave.show_marks),
                  "Show romanisation": lambda: bool(
                      settings.roman("roman_show"))}.get(label)
        first = tip.split("\n\n")[0]
        return {"label": {"↑": "Move up", "↓": "Move down"}.get(label, label),
                "tip": first, "fn": fn, "key": key, "toggle": toggle,
                "danger": label in self.DANGER}

    def _toolbar(self) -> QWidget:
        bar = QWidget()
        # Wraps where the window is narrower than the bar -- see G.Wrap.
        lay = G.Wrap(bar, T.px(10))
        groups = self._groups_by_name()

        def file_items():
            skip = {"Save", "Save as / export…", "Keys…", "Settings…"}
            return [self._item(label, fn, tip)
                    for label, fn, tip in groups["File"] if label not in skip]
        self.file_btn = G.MenuButton("File", file_items, 380)
        lay.add(self.file_btn)
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("primary", "1")
        self.save_btn.setToolTip("Write the TTML.  (Ctrl+S)")
        self.save_btn.clicked.connect(lambda: self.save())
        # One split button: Save is still one click, and everything else
        # about saving is under its ▾ -- the two halves of one pill.
        self.save_more = QPushButton("▾")
        self.save_more.setProperty("primary", "1")
        self.save_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_more.setToolTip("Save as, save a copy in another format, "
                                  "and how the TTML is written")
        self.save_more.clicked.connect(lambda: self._pop(self._save_items()))
        self.save_btn.setProperty("split", "left")
        self.save_more.setProperty("split", "right")
        split = QWidget()
        sl = QHBoxLayout(split)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.addWidget(self.save_btn)
        sl.addWidget(self.save_more)
        lay.add(split, glue=True)
        lay.add(G.rule(), sep=True)
        from .ribbon import MODES
        self.mode_seg = G.Segmented([k for k, _l, _t in MODES], "edit", big=True,
                                    labels={k: l for k, l, _t in MODES})
        for k, _l, tip in MODES:
            self.mode_seg.buttons[k].setToolTip(tip)
        self.mode_seg.picked.connect(self.ribbon.set_mode)
        lay.add(self.mode_seg, glue=True)
        lay.add(G.rule(), sep=True)
        self.tool_inline = QStackedWidget()
        lay.add(self.tool_inline, glue=True)
        who_w = QWidget()
        who = QVBoxLayout(who_w)
        who.setContentsMargins(0, 0, 0, 0)
        who.setSpacing(1)
        # One line each, cut short with an ellipsis and whole in the tooltip.
        # The artists used to wrap, and squeezed they went a word to a line
        # down the side of the toolbar, which grew to fit them.
        self.title_lbl = Caption("", floor=T.px(160))
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.title_lbl.setStyleSheet(f"font-size:{T.px(15)}px; font-weight:700;")
        self.artist_lbl = Caption("", floor=T.px(160))
        self.artist_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.artist_lbl.setStyleSheet(f"font-size:{T.px(13)}px; font-weight:500;"
                                      " color: rgba(234,234,234,153);")
        for w in (self.title_lbl, self.artist_lbl):
            w.setMaximumWidth(T.px(560))
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Policy.Preferred,
                            QSizePolicy.Policy.Preferred)
            who.addWidget(w)
        lay.add(who_w, right=True)
        lay.add(G.rule(), glue=True)
        self.keys_btn = QPushButton("Keys")
        self.keys_btn.setProperty("quiet", "1")
        self.keys_btn.clicked.connect(lambda: self.drawer.open("Keys"))
        lay.add(self.keys_btn, glue=True)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setProperty("quiet", "1")
        self.settings_btn.clicked.connect(lambda: self.drawer.open("Settings"))
        lay.add(self.settings_btn, glue=True)
        return bar

    def _fill_toolbar(self) -> None:
        """The two or three commands each mode uses most, and ▾ for the rest.

        Every mode's set is built at once, a page each in a stack, and the
        mode only turns the page. A stack is as wide as its widest page, so
        the toolbar asks for the same room in every mode: built afresh for
        each, Edit's seven controls set a wider floor under the window than
        Preview's two, and picking a mode resized the window.
        """
        stack = self.tool_inline
        while stack.count():
            page = stack.widget(0)
            stack.removeWidget(page)
            page.hide()
            page.deleteLater()
        groups = self._groups_by_name()
        for mode in self.NEW_BAR:
            stack.addWidget(self._tool_page(mode, groups))
        self._show_tools()

    def _tool_page(self, mode: str, groups: dict) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.px(10))
        inline, menus = self.NEW_BAR[mode]
        shown = set()
        for group, label in inline:
            got = next(((lb, fn, tip) for lb, fn, tip in groups.get(group, [])
                        if lb == label), None)
            if got is None:
                continue
            lb, fn, tip = got
            b = QPushButton(lb)
            b.setToolTip(tip.split("\n\n")[0] + self._hint(
                self.ACT_KEYS.get(lb, "")) if self.ACT_KEYS.get(lb) else tip)
            b.clicked.connect(lambda _c=False, f=fn: f())
            lay.addWidget(b)
            shown.add(lb)
        for name, parts in menus:
            def items(parts=parts, mode=mode):
                out = []
                for part in parts:
                    for lb, fn, tip in groups.get(part, []):
                        if lb in shown:
                            continue
                        if mode != "edit" and lb in ("Start", "Commit", "End"):
                            continue
                        out.append(self._item(lb, fn, tip))
                return out
            lay.addWidget(G.MenuButton(name, items))
        lay.addStretch(1)
        return page

    def _show_tools(self) -> None:
        mode = self.list.mode if hasattr(self, "list") else "edit"
        modes = list(self.NEW_BAR)
        if mode in modes and self.tool_inline.count() == len(modes):
            self.tool_inline.setCurrentIndex(modes.index(mode))

    # --------------------------------------------------------- arrangement
    def _lay_transport(self) -> None:
        """Put the transport's controls where this interface wants them."""
        for lay in (self.tc_lay, self.tn_lay, self.nw_lay, self.lf_lay,
                    self.sr_lay):
            while lay.count():
                it = lay.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.setParent(None)
        new = not self.classic()
        hide = (self.lag_lbl, self.lag_box, self.preroll_lbl,
                self.preroll_box, self.tap_box, *self.size_btns)
        if not new:
            self.tc_lay.setContentsMargins(8, 5, 8, 5)
            self.tc_lay.setSpacing(7)
            for it in self._classic_items:
                if isinstance(it, tuple):
                    if it[0] == "space":
                        self.tc_lay.addSpacing(it[1])
                    else:
                        self.tc_lay.addStretch(1)
                else:
                    self.tc_lay.addWidget(it)
                    it.show()
            self.tapping_lbl.setText("tapping")
            self.speed_lbl.setText("speed")
            self.voc_lbl.setText("vocal")
            self.vol_word.setText("volume")
            self.tap_lbl.setSizePolicy(QSizePolicy.Policy.Ignored,
                                       QSizePolicy.Policy.Preferred)
            self.tap_lbl.setMaximumWidth(260)
            self.tap_lbl.setStyleSheet("")
            for b in self.nudge_btns:
                b.setProperty("seg", "")
                G.restyle(b)
            self.tap_seg.setParent(None)
            self.sr_lay.setContentsMargins(T.EDGE // 2, 5, T.EDGE // 2, 6)
            self.sr_lay.addWidget(self.status, 1)
            self.status.setStyleSheet("")
            self.status_row.setStyleSheet(
                f"background:{T.INK_2}; color:{T.MUTE};")
            self.status.setWordWrap(False)
            self.collab.place(self.sr_lay)
            self._set_mode_bits()
            self.fit_bars()
            return
        L = self.tn_lay
        L.setContentsMargins(T.px(14), T.px(10), T.px(14), T.px(10))
        L.setSpacing(T.px(16))
        self.play_btn.setMinimumHeight(T.px(42))
        L.add(self.play_btn)
        L.add(self.clock_lbl, glue=True)
        self.nw_lay.setContentsMargins(T.px(3), T.px(3), T.px(3), T.px(3))
        self.nw_lay.setSpacing(T.px(2))
        for b in self.nudge_btns:
            b.setProperty("seg", "1")
            G.restyle(b)
            self.nw_lay.addWidget(b)
            b.show()
        L.add(self.nudge_well, glue=True)
        self.speed_lbl.setText("Speed")
        self.voc_lbl.setText("Vocal")
        self.vol_word.setText("Volume")
        self.tapping_lbl.setText("Tapping")
        self.tap_lbl.setSizePolicy(QSizePolicy.Policy.Preferred,
                                   QSizePolicy.Policy.Preferred)
        self.tap_lbl.setMaximumWidth(T.px(900))
        # Each label stays with its control when the bar wraps.
        for w in (self.speed_lbl, self.rate_slider, self.rate_lbl):
            L.add(w, glue=w is not self.speed_lbl)
            w.show()
        L.add(self.vol_strip)
        for w in (self.voc_lbl, self.voc_slider, self.voc_amt):
            L.add(w, glue=w is not self.voc_lbl)
        L.add(self.tapping_lbl)
        L.add(self.tap_seg, glue=True)
        L.add(self.follow_box)
        self.lf_lay.setContentsMargins(T.px(16), 0, 0, 0)
        self.lf_lay.setSpacing(T.px(14))
        for w in (self.live, self.link_dot, self.offset_lbl):
            self.lf_lay.addWidget(w)
            w.show()
        L.add(self.link_frame, right=True)
        for w in hide + (self.track,):
            w.hide()
        self.sr_lay.setContentsMargins(T.px(4), T.px(8), T.px(4), T.px(10))
        self.sr_lay.setSpacing(T.px(16))
        self.status_row.setStyleSheet("")
        self.status.setStyleSheet(f"font-size:{T.px(14)}px; font-weight:500;"
                                  " color: rgba(234,234,234,166);")
        self.tap_lbl.setStyleSheet(f"font-size:{T.px(14)}px; font-weight:500;"
                                   " color: rgba(234,234,234,128);")
        self.sr_lay.addWidget(self.status, 1)
        self.sr_lay.addWidget(self.tap_lbl)
        self.tap_lbl.show()
        self.collab.place(self.sr_lay)
        self._set_mode_bits()

    def _lay_page(self) -> None:
        """The whole editing page, in whichever interface is on."""
        box = self.page_box
        while box.count():
            it = box.takeAt(0)
            if it.widget() is not None:
                it.widget().setParent(None)
        new = not self.classic()
        self._lay_transport()
        for f, on in ((self.wave_box, new), (self.list_box, new),
                      (self.bar_box, new)):
            f.setProperty("glass", "1" if on else "")
            G.restyle(f)
        self.link_dot.setStyleSheet(self.link_dot.styleSheet())
        self.roman_wave_sw.setVisible(new and self._doc_japanese())
        self.wave_cap.setFont(T.font(12 if new else 10, 700 if new else 600,
                                     caps=True))
        if new:
            box.setContentsMargins(T.px(24), T.px(16), T.px(24), 0)
            box.setSpacing(T.px(12))
            self.wave_lay.setContentsMargins(0, 0, 0, T.px(4))
            self.wave_head.setContentsMargins(T.px(14), T.px(4), T.px(8), 0)
            self.list_lay.setContentsMargins(0, T.px(6), 0, T.px(6))
            self.bar_box.layout().setContentsMargins(T.px(6), T.px(6),
                                                     T.px(6), T.px(6))
            self.strip_lay.setContentsMargins(0, 0, 0, 0)
            self.strip_lay.setSpacing(T.px(16))
            box.addWidget(self.toolbar)
            box.addWidget(self.transport_new)
            box.addWidget(self.strip_w)
            box.addWidget(self.bar_box)
            box.addWidget(self.list_box, 1)
            box.addWidget(self.status_row)
            # Again, now the transport is back inside the window: measured
            # out of it, the tapping choice had none of the window's style
            # sheet and came up short of the room it really takes.
            self._set_mode_bits()
            self.clock_lbl.setFont(T.font(22, 700, mono=True))
            self.clock_lbl.setStyleSheet("background: transparent; border: none;"
                                         " padding: 0;")
            self.play_btn.setStyleSheet("")
            self.play_btn.setProperty("play", "1")
            G.restyle(self.play_btn)
            self._fill_toolbar()
        else:
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(0)
            self.wave_lay.setContentsMargins(0, 0, 0, 0)
            self.wave_head.setContentsMargins(0, 0, 0, 0)
            self.list_lay.setContentsMargins(0, 0, 0, 0)
            self.bar_box.layout().setContentsMargins(0, 0, 0, 0)
            self.strip_lay.setContentsMargins(T.EDGE // 2, 4, T.EDGE // 2, T.GAP)
            self.strip_lay.setSpacing(T.GROUP)
            box.addWidget(self.ribbon_scroll)
            box.addWidget(self.ribbon_rule)
            box.addWidget(self.transport_scroll)
            box.addWidget(self.strip_w)
            box.addWidget(self.bar_box)
            box.addWidget(self.list_box, 1)
            box.addWidget(self.status_row)
            self.clock_lbl.setFont(T.font(15, 500, mono=True))
            self.clock_lbl.setStyleSheet(
                f"background:{T.INK_1}; border:1px solid {T.LINE};"
                f" border-radius:{T.R_BUTTON}px; padding:6px 8px; color:{T.TEXT};")
            self.play_btn.setStyleSheet("")
            self.play_btn.setProperty("play", "")
            G.restyle(self.play_btn)
            self.play_btn.setMinimumHeight(T.px(34))
        self.sync_pad.set_look(new)
        self.sync_pad.setFixedWidth(max(T.px(360 if new else 300),
                                        self.sync_pad.sizeHint().width()))
        folded = self.wave.isHidden()
        self.fold_btn.setText(("Show ▼" if folded else "Hide ▲") if new
                              else ("unfold ▼" if folded else "fold ▲"))
        self._lane_note()
        self.fit_bars()

    def _set_mode_bits(self) -> None:
        """What the mode decides in the transport: the tapping choice, the
        drag run-up, and -- in the new look -- whether the vocal slider shows."""
        mode = self.list.mode if hasattr(self, "list") else "edit"
        new = not self.classic()
        tapping = mode in ("timing", "drag")
        if new:
            # The transport wraps (G.Wrap), and its floor is its widest run,
            # which the tapping choice is not: Timing no longer widens the
            # window the moment it is picked.
            for w in (self.tapping_lbl, self.tap_seg):
                w.setVisible(tapping)
            vocal = self.wave.vocal is not None and self.wave.show_vocal
            for w in (self.voc_lbl, self.voc_slider, self.voc_amt):
                w.setVisible(vocal)
        else:
            for w in (self.preroll_lbl, self.preroll_box):
                w.setVisible(mode == "drag")

    # ------------------------------------------------------------ interface
    def set_interface(self, value: str) -> None:
        """Flip the switch both programs share, and redraw in the other look."""
        if value not in IFACE.CHOICES:
            return
        if value == IFACE.get() and value == T.LOOK:
            return
        IFACE.put(value)
        self._iface_watch.seen(value)
        self.apply_interface(value)
        self.notify("classic interface — Settings… ▸ Look ▸ Interface switches "
                    "back" if value == "classic" else "new interface")

    def _iface_from_player(self, value: str) -> None:
        self.apply_interface(value)
        self.notify(f"{value} interface — switched in Mild Lyrics")

    def apply_interface(self, value: str) -> None:
        self.drawer.hide()
        T.set_look(value)
        self._repalette()
        app = QApplication.instance()
        if app is not None:
            app.setFont(T.font(13, 500))
        self.setStyleSheet(self._sheet())
        self.ribbon.apply()
        self.list.restyle()
        self.bar.restyle()
        self.backdrop.update()
        self.start.relook()
        self._lay_page()
        self.wave._pix = None
        self.wave.update()
        self.drawer.iface.set_value(value)

    def notify(self, text: str) -> None:
        """A toast in the new look; the status line in the classic one."""
        if self.classic():
            self.say(text)
        else:
            self.toast.say(text)

    @staticmethod
    def _keep(**values) -> dict:
        K.remember(**values)
        return values

    def _ribbon_spec(self) -> list:
        ALL = ["edit", "timing", "drag", "preview"]
        return [
            ("File", ALL, [
                ("Import…", self.show_import, "Fetch or paste words — replacing "
                 "this lyric or adding to the end of it."),
                ("Save", self.save, "Write the TTML."),
                ("Save as / export…", self.save_menu, "Save the TTML as "
                 "another file, save a copy as LRC, ASS, KRC, QRC, YRC, LYS, "
                 "SRT or plain text, and choose how the TTML is written: on "
                 "one line, and with brackets around the ad-libs."),
                ("Song info…", self.info_dialogue, "Title, artist, language and "
                 "the songwriters that go in the file's header."),
                ("Edit as text…", self.text_dialogue, "The whole lyric as plain "
                 "text. Lines you do not change keep their timing."),
                ("Fetch audio…", self.fetch_audio, "Go and find a copy of "
                 "this song to time against — searched by name AND length, "
                 "then checked by listening to it for the words in this "
                 "lyric. Kept afterwards, so it is downloaded once."),
                ("Keys…", self.keys_dialogue, "Rebind anything."),
                ("Settings…", self.settings_dialogue, "Everything the editor "
                 "remembers about how you like it: the type scale and the "
                 "accent colour, the tap lag, how wide a drag sync slice is "
                 "and whether a longer word gets a wider one, which rule "
                 "words are cut into syllables with."),
                ("Recover…", self.recover_dialogue, "Copies the editor keeps by "
                 "itself: unsaved work, whatever a fetch replaced, and every "
                 "file that was written over."),
                ("Multiplayer…", self.collab.open, "Time this lyric together "
                 "with somebody else, editor to editor with no server: host "
                 "and send an invite, or join with one."),
                ("Storage…", self.cache_dialogue, "What this app has left on the "
                 "disk, how much of it there is, and how to be rid of it."),
            ]),
            ("Drag sync", ["drag"], [
                ("Play the row", self.replay_row, "Play the line of the row "
                 "on the bar again, from a little before it starts — the "
                 "run-up is the “replay from” box on the transport."),
                ("Clear the row", self.d_clear, "Forget the times of the row "
                 "on the bar and put it back, for a pass that went wrong."),
                ("◀ row", lambda: self.d_step(-1), "Put the row above on the "
                 "bar — the line's ad-lib, or the line before it."),
                ("row ▶", lambda: self.d_step(1), "Put the row below on it."),
                ("Skip it", self.d_skip, "Leave this row as it is and take up "
                 "the next one that still wants times."),
                ("Where I left off", self.d_resume, "Put the first row in the "
                 "song that still has a syllable without a time on the bar."),
            ]),
            ("Lines", ["edit", "timing", "drag"], [
                ("Split", self.b_split_line, "Break the line before the "
                 "selected word."),
                ("Merge", self.b_merge_lines, "Run the selected lines together."),
                ("Duplicate", self.b_duplicate, "Copy them, times and all."),
                ("Delete", self.b_delete, "Remove them."),
                ("Insert", self.b_insert, "A new empty line below."),
                ("↑", lambda: self.b_move(-1), "Move up."),
                ("↓", lambda: self.b_move(1), "Move down."),
                ("Group", self.b_group, "Group the selected lines — a chorus "
                 "timed once — so that wherever they are sung again, all "
                 "of them or the start of them, one tap on the first word "
                 "times the lot. Grouped lines get a bar down the left. "
                 "On one line of a group: ungroup it."),
            ]),
            ("Words", ["edit"], [
                ("Syllabify", self.b_syllabify, "Cut every word of the "
                 "selected lines into syllables, with whatever the automatic "
                 "split is set to."),
                ("Auto split…", self.split_dialogue, "Cut the whole song — or "
                 "the selection — into syllables, choosing the rule and "
                 "seeing what it would do before it does it."),
                ("Split word", self.b_split_word, "Point at where the word "
                 "comes apart. Any number of cuts, and by default the same "
                 "split is applied to every copy of the word."),
                ("Join words", self.b_join, "Take the space out between this "
                 "word and the next: one word, still two timings."),
                ("Sung as one", self.b_join_one, "The other way round: keep "
                 "the space, lose the boundary. This word and the next become "
                 "ONE timing that still reads as two words — “Est-ce que” "
                 "sung on a single note. Works over a selection too."),
                ("Break word", self.b_end_word, "Put the space back after this "
                 "syllable."),
                ("Merge syllables", self.b_merge_syls, "Glue this syllable to "
                 "the one after it."),
                ("Marks → word", self.b_absorb_marks, "French spaces its ? ! "
                 ": ; and « » off the word — put every one that came in as a "
                 "word of its own back on the word it belongs to, keeping "
                 "the space. Whole song."),
            ]),
            ("Voices", ["edit"], [
                ("Main / duet", self.b_flip_agent, "Move the selected lines to "
                 "the other side of the screen. Same as Swap voices, on "
                 "the selection only."),
                ("→ backing", self.b_to_bg, "From the selected syllable on is "
                 "a backing vocal."),
                ("→ lead", self.b_to_lead, "Fold this line's first backing "
                 "vocal into the words it sings."),
                ("Find ad-libs", self.detect, "Move bracketed "
                 "runs at the end of a line into a backing vocal of their own."),
                ("Swap voices", self.b_swap_agents, "Put every line on the "
                 "other side — main becomes duet and duet becomes main. The "
                 "selection if there is one, the whole song if not."),
            ]),
            ("Romanisation", ["edit"], [
                ("Show romanisation", self.b_roman_show, "A second row under "
                 "every line with how each syllable is read."),
                ("Fill in missing", self.b_roman_fill, "Give every syllable "
                 "with no reading one from the romaniser. Readings you typed "
                 "are kept."),
                ("From Genius…", self.b_roman_genius, "Take Genius' romanised "
                 "lyric for this song and line it up with these words, "
                 "showing what would change first — readings for lines "
                 "without one, and corrections where a reading already here "
                 "(usually the romaniser's) disagrees with it."),
                ("Clear romanisation", self.b_roman_clear, "Take every "
                 "reading off the lyric."),
            ]),
            ("Timing", ["timing", "drag"], [
                ("Start", lambda: self.fire("sync_start"), "This word starts "
                 "at the playhead."),
                ("Commit", lambda: self.fire("sync_next"), "End it, start the "
                 "next one here, and step on — the tapping key."),
                ("End", lambda: self.fire("sync_end"), "This word ends at the "
                 "playhead."),
                ("Spread", self.b_spread, "Share the line's span out over its "
                 "syllables by length."),
                ("From a repeat", self.b_repeat, "A line that repeats one "
                 "already timed earlier — a chorus coming round again — timed "
                 "from that one, moved to wherever this line's first timed "
                 "syllable is. Time one syllable, then this: everything "
                 "else in the line follows it. On a grouped run, the whole "
                 "run follows it."),
                ("−0.05s", lambda: self.b_shift(-0.05), "Nudge the selected "
                 "lines back."),
                ("+0.05s", lambda: self.b_shift(0.05), "Nudge them on."),
                ("Clear", self.b_clear, "Forget their times."),
                ("Tidy ends", self.b_snap, "Stop every line before the next "
                 "one starts."),
            ]),
            ("Vocal", ["timing"], [
                ("Vocal view", self.b_vocal_view, "Separate the vocal with "
                 "demucs and draw its spectrogram behind the words, with a "
                 "tick everywhere the singing starts or stops. The first "
                 "time costs a separation; after that it is read back.\n\n"
                 "It also unlocks the vocal slider in the bar above, which "
                 "plays the separated vocal instead of the mixture — the "
                 "same stem, for the ear rather than the eye.\n\n"
                 "Needs torch, torchaudio and demucs. Without them the "
                 "waveform stays and this says what is missing."),
                ("Marks", self.b_vocal_marks, "Show or hide the ticks on "
                 "their own."),
                ("What it says…", self.vocal_report, "How far this song's "
                 "marks can be trusted, which of them are too ambiguous to "
                 "read, and which words sit nowhere near anything the singer "
                 "did. Changes nothing — it is a reading list."),
            ]),
            ("Timing", ["timing"], [
                ("Close gaps", self.b_fill_gaps, "Hold each word open until "
                 "the next one starts, but only across the small holes — "
                 "anything longer than the gap in Snap… is a rest and is "
                 "left alone."),
                ("From the first word", self.b_from_first, "Time a line "
                 "you have placed the first word of: lay the rest out at the "
                 "speed the lines around it are sung at, and hold the last "
                 "word to where the line ends. A first pass to drag into "
                 "shape, not a placement."),
            ]),
            ("Preview", ["preview"], [
                ("From the top", lambda: self.seek(0.0), "Play from the start."),
                ("From this line", self.play_from_line, "Play from the "
                 "selected line."),
            ]),
        ]

    def _transport(self):
        """Every control on the transport bar, made once.

        Made once and laid out twice: the classic interface puts them in one
        long scrolling row, as it always has, and the new one puts the
        playback controls in a pane of their own and moves what is set once
        -- the tap lag, the replay run-up, the text size -- into Settings.
        `_classic_items` is the classic row, in order; `_lay_transport` is
        what puts them, or the new arrangement, on screen.
        """
        items: list = []
        put = items.append
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setProperty("primary", "1")
        self.play_btn.setMinimumHeight(T.px(34))
        self.play_btn.setMinimumWidth(T.px(104))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(self.toggle)
        put(self.play_btn)
        self.clock_lbl = QLabel("0:00.000")
        self.clock_lbl.setFont(T.font(15, 500, mono=True))
        self.clock_lbl.setMinimumWidth(T.px(108))
        self.clock_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_lbl.setStyleSheet(
            f"background:{T.INK_1}; border:1px solid {T.LINE};"
            f" border-radius:{T.R_BUTTON}px; padding:6px 8px; color:{T.TEXT};")
        put(self.clock_lbl)
        put(("space", 6))
        speed = self.speed_lbl = QLabel("speed")
        speed.setProperty("hint", "1")
        put(speed)
        self.rate_slider = QSlider(Qt.Orientation.Horizontal)
        self.rate_slider.setRange(int(RATE_MIN * 100), int(RATE_MAX * 100))
        self.rate_slider.setSingleStep(5)
        self.rate_slider.setPageStep(25)
        self.rate_slider.setValue(int(round(100 * max(RATE_MIN, min(
            RATE_MAX, float(K.config().get("rate", 1.0)))))))
        self.rate_slider.setFixedWidth(T.px(118))
        self.rate_slider.setTickInterval(25)
        self.rate_slider.setTickPosition(QSlider.TickPosition.NoTicks)
        self.rate_slider.setToolTip(
            "How fast the song is played, from a quarter speed to double. "
            "Local audio only — Spotify plays at one speed and so does "
            "everything timed against it.\n\nIt changes nothing that is "
            "written: a word placed at half speed is placed at the time it "
            "is sung, not at half of it.")
        self.rate_slider.valueChanged.connect(self._rate)
        put(self.rate_slider)
        self.rate_lbl = QLabel("1.00×")
        self.rate_lbl.setProperty("hint", "1")
        self.rate_lbl.setMinimumWidth(T.px(44))
        self.rate_lbl.setFont(T.font(12, 500, mono=True))
        put(self.rate_lbl)
        put(("space", 6))
        vol = self.vol_word = QLabel("volume")
        vol.setProperty("hint", "1")
        self._vol_quiet = False
        self._vol_save = QTimer(self)
        self._vol_save.setSingleShot(True)
        self._vol_save.setInterval(500)
        self._vol_save.timeout.connect(self._keep_volume)
        self.vol_slider = VolumeSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setFixedWidth(T.px(104))
        self.vol_slider.setValue(int(round(
            float(K.config().get("volume", 0.9)) * 100)))
        self.vol_slider.setToolTip(
            "How loud the song is played, on the scale ears use rather than "
            "the amplitude one. A local file is turned down here and "
            "nowhere else; with Spotify this is Spotify's own volume, so "
            "moving it there moves this.\n\nScroll anywhere on it — the word "
            "and the number count — to change it without taking aim.\n\nIt "
            "changes nothing that is written — the times are the times "
            "however loud it was.")
        self.vol_slider.valueChanged.connect(self._volume)
        self.vol_lbl = QLabel(f"{self.vol_slider.value()}%")
        self.vol_lbl.setProperty("hint", "1")
        self.vol_lbl.setMinimumWidth(T.px(44))
        self.vol_lbl.setFont(T.font(12, 500, mono=True))
        self.vol_strip = VolumeStrip(self.vol_slider, [vol, self.vol_lbl])
        self.vol_strip.setSizePolicy(QSizePolicy.Policy.Fixed,
                                     QSizePolicy.Policy.Preferred)
        self.vol_strip.setToolTip(self.vol_slider.toolTip())
        put(self.vol_strip)
        put(("space", 6))
        self.voc_lbl = QLabel("vocal")
        self.voc_lbl.setProperty("hint", "1")
        put(self.voc_lbl)
        self.voc_slider = QSlider(Qt.Orientation.Horizontal)
        self.voc_slider.setRange(0, 100)
        self.voc_slider.setSingleStep(5)
        self.voc_slider.setPageStep(25)
        self.voc_slider.setFixedWidth(T.px(104))
        self.voc_slider.setValue(0)
        self.voc_slider.valueChanged.connect(self._vocal_mix)
        put(self.voc_slider)
        self.voc_amt = QLabel("mix")
        self.voc_amt.setProperty("hint", "1")
        self.voc_amt.setMinimumWidth(T.px(40))
        self.voc_amt.setFont(T.font(12, 500, mono=True))
        put(self.voc_amt)
        self._voc_render = QTimer(self)
        self._voc_render.setSingleShot(True)
        self._voc_render.setInterval(350)
        self._voc_render.timeout.connect(self._vocal_apply)
        self._voc_busy = False
        self.nudge_btns: list = []
        for label, fn in (("−5s", lambda: self.player.nudge(-5)),
                          ("−1s", lambda: self.player.nudge(-1)),
                          ("+1s", lambda: self.player.nudge(1)),
                          ("+5s", lambda: self.player.nudge(5))):
            b = QPushButton(label)
            b.setProperty("ghost", "1")
            b.clicked.connect(fn)
            self.nudge_btns.append(b)
            put(b)
        put(("space", 6))
        lag = self.lag_lbl = QLabel("tap lag")
        lag.setProperty("hint", "1")
        put(lag)
        self.lag_box = QDoubleSpinBox()
        self.lag_box.setRange(-500.0, 500.0)
        self.lag_box.setSingleStep(10.0)
        self.lag_box.setDecimals(0)
        self.lag_box.setSuffix(" ms")
        self.lag_box.setValue(float(K.config().get("tap_lag_ms", 0.0)))
        self.lag_box.setToolTip(
            "How late your taps land. Everything stamped with the timing "
            "keys (or the pad) is moved back by this much, so a consistent "
            "reaction time stops being baked into the file. Dragging an edge "
            "on the strip is not touched — that is placed by eye, not by "
            "reflex.")
        self.lag_box.valueChanged.connect(
            lambda v: K.remember(tap_lag_ms=float(v)))
        put(self.lag_box)
        self.preroll_lbl = QLabel("replay from")
        self.preroll_lbl.setProperty("hint", "1")
        put(self.preroll_lbl)
        self.preroll_box = QDoubleSpinBox()
        self.preroll_box.setRange(0.0, 10.0)
        self.preroll_box.setSingleStep(0.5)
        self.preroll_box.setDecimals(1)
        self.preroll_box.setSuffix(" s before")
        self.preroll_box.setValue(float(K.config().get("drag_preroll", 1.5)))
        self.preroll_box.setToolTip(
            "How far ahead of a line the replay drops you in — for the run "
            "back over a line to catch its ad-lib, and for the Play the row "
            "button. An ad-lib that comes in BEFORE the words it answers gets "
            "three times this, because it has to be heard before the line "
            "starts at all.")
        self.preroll_box.valueChanged.connect(
            lambda v: K.remember(drag_preroll=float(v)))
        put(self.preroll_box)
        put(("space", 6))
        self.size_btns: list = []
        for label, delta, tip in (("A−", -0.1, "Smaller text.  (Ctrl+−)"),
                                  ("A+", 0.1, "Bigger text.  (Ctrl+=)")):
            b = QPushButton(label)
            b.setProperty("ghost", "1")
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, d=delta: self.bump_scale(d))
            self.size_btns.append(b)
            put(b)
        tapping = self.tapping_lbl = QLabel("tapping")
        tapping.setProperty("hint", "1")
        put(tapping)
        self.tap_box = QComboBox()
        for label in TAP_LABELS.values():
            self.tap_box.addItem(label)
        self.tap_box.setCurrentText(TAP_LABELS[self._tap_mode()])
        self.tap_box.setToolTip(
            "Which voices the timing keys walk through.\n\n"
            "Lines and ad-libs — a line with an ad-lib is tapped in the order "
            "it sounds: the opener, then the words, then the answer.\n"
            "Lines only — tapping stays on the lead voices.\n"
            "Ad-libs only — nothing but the backing voices, for timing them "
            "in a pass of their own.\n\n"
            "Whichever it is, everything stays editable by clicking it.")
        self.tap_box.currentTextChanged.connect(self._tapping)
        put(self.tap_box)
        self.follow_box = G.Switch("follow")
        self.follow_box.setChecked(True)
        self.follow_box.setToolTip("Keep the strip — and, in preview, the "
                                   "lyric — on the playhead.")
        self.follow_box.toggled.connect(self._follow)
        put(self.follow_box)
        put(("stretch",))
        self.tap_lbl = QLabel("")
        self.tap_lbl.setProperty("hint", "1")
        _shrinkable(self.tap_lbl, 260)
        self.tap_lbl.setAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
        put(self.tap_lbl)
        put(("space", 14))
        self.track = QLabel("—")
        self.track.setProperty("hint", "1")
        _shrinkable(self.track, 320)
        put(self.track)
        put(("space", 10))
        self.live = G.Switch("Show in Mild Lyrics")
        self.live.setChecked(True)
        self.live.setToolTip(
            "Push every edit to the running player, so the file being timed "
            "is drawn over the song it is playing. Only the lines that have "
            "times are sent. Against Spotify the player's own clock sweeps "
            "them; with a local file the player follows this window's clock "
            "instead, speed and all.")
        self.live.toggled.connect(self._live_toggled)
        put(self.live)
        self.link_dot = Caption("● no player")
        self.link_dot.setProperty("hint", "1")
        put(self.link_dot)
        self.offset_lbl = Caption("")
        self.offset_lbl.setProperty("hint", "1")
        self.offset_lbl.setToolTip(
            "The global offset the player is set to. Times are stamped in "
            "lyric time -- this is taken off before anything is written, so "
            "the file never carries it. Change it mid-song and the halves "
            "stop agreeing, which this will say.")
        put(self.offset_lbl)
        self._classic_items = items
        self.tap_seg = G.Segmented(list(TAP_LABELS), self._tap_mode(),
                                   labels=TAP_LABELS)
        self.tap_seg.setToolTip(self.tap_box.toolTip())
        self.tap_seg.picked.connect(
            lambda k: self.tap_box.setCurrentText(TAP_LABELS[k]))
        self.tap_box.currentTextChanged.connect(
            lambda t: self.tap_seg.set_value(next(
                (k for k, v in TAP_LABELS.items() if v == t), "all")))

    def _file_actions(self) -> None:
        """The file shortcuts, with no menu bar to hang them off.

        A menu bar here would be exactly the thing the ribbon replaced: four
        words in nine-point type in the top-left corner, holding the same
        commands the ribbon already shows at a size that can be read and hit.
        The keys still work, because a shortcut nobody can see is still worth
        having.
        """
        does = {
            "Bigger text": lambda: self.bump_scale(0.1),
            "Smaller text": lambda: self.bump_scale(-0.1),
            "Text back to its own size": lambda: (T.set_scale(1.0),
                                                  self.apply_scale()),
            "New lyric": self.new_doc,
            "Open a lyric": lambda: self.open_lyric(""),
            "Import words": self.show_import,
            "Save": self.save,
            "Save a copy": lambda: self.save(True),
            "Open audio": lambda: self.open_audio(""),
            "Undo": self.undo,
            "Redo": self.redo,
            "Find lyrics": self.find_open,
        }
        for keyseq, what in K.FIXED:
            fn = does.get(what)
            if fn is None:
                continue
            act = QAction(what, self)
            act.setShortcut(QKeySequence(keyseq))
            act.triggered.connect(fn)
            self.addAction(act)

    # ----------------------------------------------------------------- find
    def _find_bar(self, lay) -> None:
        """Ctrl+F: a bar over the list that walks every row matching a phrase.

        Lyrics repeat -- a chorus is the same words on many lines -- so a
        match is a ROW, not a phrase: each row that holds it is its own hit,
        counted "3 of 9", and Enter steps to the next one in document order.
        """
        self.find_box = QFrame()
        row = QHBoxLayout(self.find_box)
        row.setContentsMargins(6, 4, 6, 4)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find in lyrics")
        self.find_count = QLabel("")
        self.find_count.setProperty("hint", "1")
        prev, nxt, close = (QPushButton(t) for t in ("↑", "↓", "✕"))
        prev.setToolTip("Previous match (Shift+Enter)")
        nxt.setToolTip("Next match (Enter)")
        close.setToolTip("Close (Esc)")
        for w in (self.find_edit, self.find_count, prev, nxt, close):
            row.addWidget(w, 1 if w is self.find_edit else 0)
        prev.clicked.connect(lambda: self.find_step(-1))
        nxt.clicked.connect(lambda: self.find_step(1))
        close.clicked.connect(self.find_close)
        self.find_edit.textChanged.connect(lambda _t: self.find_run())
        self.find_edit.installEventFilter(self)
        self.find_hits: list = []
        self.find_box.setVisible(False)
        lay.addWidget(self.find_box)

    @staticmethod
    def _fold(text: str) -> str:
        """Case, accents and punctuation set aside, so `don't` finds `Dont`."""
        import unicodedata
        t = unicodedata.normalize("NFKD", text.casefold())
        t = "".join(c for c in t if not unicodedata.combining(c)
                    and c not in "'’‘`")
        return " ".join("".join(c if c.isalnum() else " " for c in t).split())

    def find_open(self) -> None:
        self.find_box.setVisible(True)
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self.find_run(jump=False)

    def find_close(self) -> None:
        self.find_box.setVisible(False)
        self.list.finds, self.list.found = set(), None
        self.find_hits = []
        self.list.viewport().update()
        self.list.setFocus()

    def find_run(self, jump: bool = True) -> None:
        """Re-scan every row (leads and backing voices alike)."""
        want = self._fold(self.find_edit.text())
        hits = []
        if want:
            for i, ln in enumerate(self.list.doc.lines):
                for v, g in enumerate(ln.groups()):
                    if want in self._fold(g.text()):
                        hits.append((i, v))
        self.find_hits = hits
        self.list.finds = set(hits)
        self.list.found = None
        if not hits:
            self.find_count.setText("no matches" if want else "")
            self.list.viewport().update()
            return
        if jump:
            # From where the cursor is, so typing more of a phrase does not
            # throw you to the top of the song.
            here = self.list.cursor[:2]
            at = next((n for n, h in enumerate(hits) if h >= here), 0)
            self._find_go(at)
        else:
            self.find_count.setText(f"{len(hits)} rows")
            self.list.viewport().update()

    def _find_go(self, n: int) -> None:
        self._find_at = n % len(self.find_hits)
        line, voice = self.find_hits[self._find_at]
        self.list.found = (line, voice)
        self.find_count.setText(f"{self._find_at + 1} of {len(self.find_hits)}")
        self.list.set_cursor(line, voice, 0)
        self.list.viewport().update()

    def find_step(self, d: int) -> None:
        if not self.find_hits:
            self.find_run()
            return
        cur = self.list.found
        at = self.find_hits.index(cur) if cur in self.find_hits else -1 if d > 0 else 0
        self._find_go(at + d)

    def eventFilter(self, obj, ev):                       # noqa: N802 (Qt name)
        if obj is getattr(self, "find_edit", None) and ev.type() == ev.Type.KeyPress:
            k = ev.key()
            if k == Qt.Key.Key_Escape:
                self.find_close()
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.find_step(-1 if ev.modifiers()
                               & Qt.KeyboardModifier.ShiftModifier else 1)
                return True
        return super().eventFilter(obj, ev)

    # ----------------------------------------------------------------- keys
    def _key_handlers(self) -> dict:
        return {
            "sync_start": lambda: self.fire("sync_start"),
            "sync_next": lambda: self.fire("sync_next"),
            "sync_end": lambda: self.fire("sync_end"),
            "prev_word": lambda: self.list.step(-1),
            "next_word": lambda: self.list.step(1),
            "prev_word_play": lambda: self.step_play(-1),
            "next_word_play": lambda: self.step_play(1),
            "prev_line": lambda: self.list.step_line(-1),
            "next_line": lambda: self.list.step_line(1),
            "play_pause": self.toggle,
            "seek_back": lambda: self.player.nudge(-0.25),
            "seek_fwd": lambda: self.player.nudge(0.25),
            "rate_down": lambda: self.bump_rate(-1),
            "rate_up": lambda: self.bump_rate(1),
            "rate_reset": lambda: self.bump_rate_to(1.0),
            "nudge_back": lambda: self.b_nudge_syl(-0.02),
            "nudge_on": lambda: self.b_nudge_syl(0.02),
            "split_line": self.b_split_line,
            "merge_lines": self.b_merge_lines,
            "duplicate": self.b_duplicate,
            "flip_agent": self.b_flip_agent,
            "drag_replay": self.replay_row,
            "drag_skip": self.d_skip,
        }

    TIP_KEYS = {"Play the row": "drag_replay",
                "Skip it": "drag_skip",
                "Split": "split_line",
                "Merge": "merge_lines",
                "Duplicate": "duplicate",
                "Save": "Ctrl+S"}

    def _hint(self, name: str) -> str:
        """`  (R)`, or nothing at all if that action has no key."""
        key = self.keys.label(name)
        return f"  ({key})" if key else ""

    def retip(self) -> None:
        """Put today's keys back into the buttons that name one.

        `TIP_KEYS` is the buttons whose tooltip ends in a key. They used to
        name the key in the text itself, so a button went on saying (R)
        long after R had been given to something else -- a tooltip that is
        wrong about the one fact it exists to carry is worse than one that
        carries no key at all. The names in it are actions; a spelling like
        `Ctrl+S` is one of the window's own, which cannot be rebound.
        """
        for label, name in self.TIP_KEYS.items():
            b = self.ribbon.button(label)
            if b is None:
                continue
            tip = self._tips.get(label, "")
            key = name if name not in K.DEFAULTS else self.keys.label(name)
            b.setToolTip(f"{tip}  ({key})" if key else tip)
        if hasattr(self, "tool_inline") and not self.classic():
            self._fill_toolbar()

    def key_possible(self, name: str) -> tuple:
        if name in ("rate_up", "rate_down", "rate_reset"):
            if getattr(getattr(self, "player", None), "kind", "") != "local":
                return False, "speed is for local audio — Spotify plays at 1×"
        if name in ("drag_replay", "drag_skip"):
            if getattr(getattr(self, "list", None), "mode", "") != "drag":
                return False, "drag sync only — switch the mode to Drag sync"
        return True, ""

    def bump_scale(self, delta: float) -> None:
        T.set_scale(T.SCALE + delta)
        self.apply_scale()

    def apply_scale(self, quiet: bool = False) -> None:
        """Re-dress the whole window at the current zoom and palette."""
        app = QApplication.instance()
        if app is not None:
            app.setFont(T.font(13, 500))
        self.setStyleSheet(self._sheet())
        self.list.restyle()
        self.bar.restyle()
        self.wave._pix = None
        self.wave.update()
        self.ribbon.apply()
        self.backdrop.update()
        if not self.classic():
            self._lay_page()
        self.fit_bars()
        if not quiet:
            self.notify(f"text at {T.SCALE * 100:.0f}%")

    @staticmethod
    def _repalette() -> None:
        """Push the palette into the modules that cached it.

        The painted widgets take their colours once, at import, because they
        are asked for per chip and a dictionary lookup per chip is not free.
        That is the right trade and it costs this: a colour somebody has just
        chosen has to be handed to them.
        """
        for mod in (waveform, lineview_mod, syncbar_mod):
            inks = getattr(mod, "_inks", None)
            if inks is not None:
                inks()

    def keys_dialogue(self) -> None:
        if not self.classic():
            self.drawer.open("Keys")
            return
        K.KeyDialogue(self.keys, self).exec()

    def settings_dialogue(self) -> None:
        """Everything the editor remembers about how you like it."""
        if not self.classic():
            self.drawer.open("Settings")
            return
        changed = settings.ask(self)
        if changed is None:
            return
        self.apply_settings(changed)

    def apply_settings(self, changed: dict) -> None:
        """Put the settings on screen. Only what actually changed.

        Some of these are cheap and some re-dress the whole window, and the
        dialogue is a place somebody opens to change one thing -- so a run
        through it that altered nothing should cost nothing.
        """
        cfg = K.config()
        if "interface" in changed:
            self.set_interface(str(changed["interface"]))
        if {"roman_show", "roman_detail", "roman_wave"} & set(changed):
            self._roman_look()
            self.roman_wave_sw.blockSignals(True)
            self.roman_wave_sw.setChecked(bool(settings.roman("roman_wave")))
            self.roman_wave_sw.blockSignals(False)
        if {"accent", "accent_new"} & set(changed):
            T.accent()
            self._repalette()
            self.wave._pix = None
        if "scale" in changed:
            T.set_scale(float(cfg.get("scale", 1.0)))
        if {"accent", "accent_new", "scale"} & set(changed):
            self.apply_scale(quiet="scale" not in changed)
        if "wave_height" in changed:
            self.wave.setMaximumHeight(T.px(float(cfg.get("wave_height",
                                                          210.0))))
            self._lane_note()
        if "lanes_all" in changed:
            self.wave.lanes_all = bool(cfg.get("lanes_all", True))
            self._lane_note()
            self.wave.update()
        if "wave_loose" in changed:
            self.wave.show_loose = bool(cfg.get("wave_loose", True))
            self.wave.update()
        if "tap_lag_ms" in changed:
            self.lag_box.setValue(float(cfg.get("tap_lag_ms", 0.0)))
        if "drag_preroll" in changed:
            self.preroll_box.setValue(float(cfg.get("drag_preroll", 1.5)))
        if "tap_adlibs" in changed:
            K.remember(tap_mode="all" if cfg.get("tap_adlibs", True) else "lead")
            self.tap_box.setCurrentText(TAP_LABELS[self._tap_mode()])
            self.list.tap_mode = self._tap_mode()
        if {"bar_cell", "bar_stretch"} & set(changed):
            self._dress_bar()
            self.fill_bar()
        if "rate" in changed and not self.rate_slider.isSliderDown():
            self.bump_rate_to(float(cfg.get("rate", 1.0)))
        if "gpu" in changed:
            # After the click that changed it has been handled: turning it
            # on throws the native window away.
            QTimer.singleShot(0, lambda: GPU.relay(self))
        if changed and self.classic():
            self.say("settings saved")

    def _dress_bar(self) -> None:
        """The drag bar's own two settings, on the widget that draws it."""
        cfg = K.config()
        self.bar.cell = float(cfg.get("bar_cell", syncbar_mod.CELL_W))
        self.bar.stretch = float(cfg.get("bar_stretch", 0.0))
        self.bar.restyle()

    def fire(self, action: str) -> None:
        """One of the three timing actions, wherever it was asked for."""
        if action in ("prev_word", "next_word"):
            self.list.step(-1 if action == "prev_word" else 1)
            return
        line, voice, k = self.list.settle_cursor()
        g = self.doc.group(line, voice)
        if g is None or not 0 <= k < len(g.syls):
            self.say("nothing to time — click a word first")
            return
        if not self.list.taps(voice):
            # Not even a start: the tapping choice says this voice is not
            # being timed, and a word half-timed by a stray key is worse
            # than one not timed at all. The colours say what to switch.
            self._tap_refused(voice, g.syls[k].text)
            return
        self.stamp_offset()
        pos = max(0.0, self.player.position() - self.tap_lag())
        self.push_undo()
        s = g.syls[k]
        # Committing a word that never started has nothing to end: it is
        # the first tap of a run -- after a line filled from a repeat, the
        # cursor waits on the next line's first word -- so it starts it.
        if action == "sync_next" and not s.timed:
            action = "sync_start"
        started = None
        if action == "sync_start":
            ops.set_time(self.doc, line, voice, k, pos, max(pos, s.end or pos))
            said = f"{s.text} starts at {_fmt(pos)}"
            started = (line, voice, k)
        else:
            ops.set_time(self.doc, line, voice, k, None, pos)
            said = f"{s.text} ends at {_fmt(pos)}"
            moved = self.list.step(1)
            if action == "sync_next" and moved:
                i2, v2, k2 = self.list.cursor
                nxt = self.doc.group(i2, v2).syls[k2]
                ops.set_time(self.doc, i2, v2, k2, pos,
                             max(pos, nxt.end or pos))
                said += f", {nxt.text} starts"
                started = (i2, v2, k2)
            elif action == "sync_end":
                pass
        if started is not None:
            said = self._repeat_after_tap(*started) or said
        self.do(said, structural=False)

    def _repeat_after_tap(self, line: int, voice: int, k: int) -> str | None:
        """A tap that opened a line sung earlier: time the rest from there.

        Only the lead's FIRST syllable, and only while nothing else in that
        lead has a time -- tapping through a line somebody is correcting by
        hand must never have the correction swept away under them. The
        cursor then goes on to the first thing after the line that still
        wants a time, so the next Commit starts it.
        """
        if voice != 0 or k != 0 or not bool(K.config().get("repeat_fill",
                                                            True)):
            return None
        said = self._run_after_tap(line)
        if said:
            return said
        lead = self.doc.lines[line].lead
        if any(s.timed for s in lead.syls[1:]):
            return None
        said = ops.fill_from_repeat(self.doc, line)
        if not said:
            return None
        self.list.relayout(force=True)
        order = self.list.walk()
        after = [n for n, (i, _v, _k) in enumerate(order) if i == line]
        start = (after[-1] + 1) if after else len(order)
        for i, v, kk in order[start:] + [c for c in order[:start] if c[0] == line]:
            g = self.doc.group(i, v)
            if g is not None and kk < len(g.syls) and not g.syls[kk].timed:
                self.list.set_cursor(i, v, kk)
                break
        else:
            if start < len(order):
                self.list.set_cursor(*order[start])
        return said + " — the next tap starts what comes after it"

    def _run_after_tap(self, line: int) -> str | None:
        """A tap that opened a line of a grouped run: time the whole run.

        The same guard as a single line's, over the run: nothing in it timed
        but the syllable just tapped, ad-libs included. Any line of the run
        will do, not only its first -- a tap that missed the opening line
        still knows where the run is, and the lines before it are filled from
        the same shift. The cursor then goes to the first thing in the run
        that is still untimed -- an ad-lib this chorus has and the one it was
        copied from did not -- and past the run where there is none.
        """
        run = ops.run_at(self.doc, line)
        if run is None:
            return None
        _n, at, size = run
        for o in range(size):
            for v, g in enumerate(self.doc.lines[at + o].groups()):
                for kk, s in enumerate(g.syls):
                    if s.timed and (at + o, v, kk) != (line, 0, 0):
                        return None
        said = ops.fill_part(self.doc, line)
        if not said:
            return None
        self.list.relayout(force=True)
        order = self.list.walk()
        last = at + size - 1
        inside = [c for c in order if at <= c[0] <= last
                  and not self.doc.group(c[0], c[1]).syls[c[2]].timed]
        after = [c for c in order if c[0] > last]
        if inside:
            self.list.set_cursor(*inside[0])
            g = self.doc.group(inside[0][0], inside[0][1])
            return (said + f" — the next tap times “{g.text()}” on line "
                    f"{inside[0][0] + 1}, which the copy did not have")
        if after:
            self.list.set_cursor(*after[0])
        return said + " — the next tap starts what comes after it"

    def b_repeat(self) -> None:
        """Timing ▸ From a repeat: the same, by hand, over the selection."""
        sel = self.selected() or [self.list.cursor[0]]
        self.push_undo()
        done, why, runs = [], "", set()
        for i in sel:
            run = ops.run_at(self.doc, i)
            if run is not None:
                if run[1] in runs:
                    continue
                got = ops.fill_part(self.doc, i)
                if got:
                    runs.add(run[1])
                    done.append(got)
                    continue
            if ops.repeat_source(self.doc, i) is None:
                why = why or (f"line {i + 1} repeats no line timed before it")
                continue
            got = ops.fill_from_repeat(self.doc, i)
            if got:
                done.append(got)
            else:
                why = why or (f"line {i + 1} needs one syllable timed first "
                              f"— tap its first word, then this")
        if not done:
            self.say(why or "nothing to do")
            return
        self.do(done[0] if len(done) == 1
                else f"{len(done)} lines and runs timed from earlier repeats",
                structural=True)

    def b_group(self) -> None:
        """Lines ▸ Group: the selected lines, to be timed as one wherever
        they are sung again. Again on a line of a group: ungroup it."""
        sel = self.selected() or [self.list.cursor[0]]
        self.push_undo()
        if len(sel) == 1 and ops.run_at(self.doc, sel[0]) is not None:
            self.do(ops.drop_parts(self.doc, sel))
            return
        if len(sel) < 2:
            self.do(None)
            self.say("select the lines to group — the chorus, timed once — "
                     "then Group")
            return
        said = ops.make_part(self.doc, sel)
        if said is None:
            self.do(None)
            self.say("those lines are grouped already" if tuple(
                ops.line_key(self.doc.lines[i])
                for i in range(min(sel), max(sel) + 1)) in self.doc.parts
                else "a line with no words in it cannot be grouped")
            return
        self.do(said)

    # ------------------------------------------------------------ drag sync
    def _sweep_ok(self) -> bool:
        """Whether a drag has a clock to be stamped against at all."""
        if self.player.duration() <= 0:
            self.say("nothing to drag against — open or fetch the audio first")
            return False
        return True

    def now(self) -> float:
        """The moment a gesture just happened, in lyric time."""
        return max(0.0, self.player.position() - self.tap_lag())

    def preroll(self) -> float:
        try:
            return float(self.preroll_box.value())
        except Exception:                                    # noqa: BLE001
            return float(K.config().get("drag_preroll", 1.5))

    def fill_bar(self) -> None:
        """Put the armed row on the bar, with the line's span behind it.

        Only in drag sync. It is called from refresh(), which is every edit
        there is, and laying the bar out again on each of them in a mode
        where it is not even on screen is work for nobody. Entering the mode
        fills it, and so does arming a row.
        """
        if not hasattr(self, "bar") or self.list.mode != "drag":
            return
        row = self.list.next_row
        g = self.doc.group(*row) if row else None
        if g is None:
            self.bar.show_row([], "")
            return
        line, voice = row
        left = sum(1 for s in g.syls if not s.timed)
        self.bar.show_row(
            g.syls,
            f"{'ad-lib of ' if voice else ''}line {line + 1}"
            + (f"  ·  {left} of {len(g.syls)} without times" if left
               else "  ·  all timed"),
            self.doc.lines[line].span())

    def _sweep_begin(self, k: int) -> None:
        row = self.list.next_row
        if row is None:
            return
        line, voice = row
        if not self.player.playing():
            self.toggle()
        self.stamp_offset()
        now = self.now()
        self.push_undo()
        self._sweeping = {"row": row, "at": k, "t": now, "stamped": {k}}
        ops.set_time(self.doc, line, voice, k, now, now)
        self.list.show_pass(row, k, {k})
        self.do("", structural=False)

    def _sweep_to(self, k: int) -> None:
        s = self._sweeping
        if not s:
            return
        line, voice = s["row"]
        now, at = self.now(), s["at"]
        if k > at:
            ops.sweep(self.doc, line, voice, at, k, s["t"], now)
            s["stamped"].update(range(at, k + 1))
        else:
            gone = [j for j in range(k + 1, at + 1) if j in s["stamped"]]
            ops.untime(self.doc, line, voice, gone)
            s["stamped"].difference_update(gone)
            ops.set_time(self.doc, line, voice, k, None, now)
        s["at"], s["t"] = k, now
        self.list.show_pass(s["row"], k, s["stamped"])
        self.do("", structural=False)

    def _sweep_done(self, k: int) -> None:
        s, self._sweeping = self._sweeping, None
        self.list.show_pass(None)
        if not s:
            return
        line, voice = s["row"]
        ops.set_time(self.doc, line, voice, k, None, self.now())
        n = len(s["stamped"])
        said = f"dragged {n} syllable{'' if n == 1 else 's'}"
        self.do(said, structural=False)
        self.advance_drag(line, voice, said)

    def _sweep_cancelled(self) -> None:
        """Escape mid-drag: the row goes back to what it was before the press."""
        self.list.show_pass(None)
        if self._sweeping is None:
            return
        self._sweeping = None
        self.undo()
        self.say("drag dropped — the row is as it was")

    def advance_drag(self, line: int, voice: int, said: str = "") -> None:
        """Arm whatever wants timing next, and play the line again if what
        wants it is inside the line just finished.

        This is the whole ad-lib answer in a handful of lines. The drawn order
        puts a line's backing voices directly after the words they answer, so
        the next row wanting times after a lead IS that line's ad-lib -- and a
        row inside the line just finished can only be asking for seconds that
        have already gone by, so they are played again.

        Past the last row it starts again from the top rather than stopping,
        because "nothing after this" and "nothing left to do" are different
        answers and only one of them is worth saying.

        A row the pass did not finish keeps the bar, so that letting go
        early -- which is how a drag is corrected -- carries on where it
        stopped instead of abandoning the line.
        """
        def tail(text: str) -> None:
            self.say(f"{said} — {text}" if said else text)

        g = self.doc.group(line, voice)
        left = sum(1 for s in g.syls if not s.timed) if g else 0
        if left:
            self.list.arm(line, voice)
            tail(f"{left} still without times in this row — drag on from the "
                 f"mark, or play the row again{self._hint('drag_replay')}")
            return
        nxt = self.list.next_to_time((line, voice)) or self.list.next_to_time()
        if nxt is None:
            self.list.arm(line, voice)
            tail("every row has times now")
            return
        self.list.arm(*nxt)
        if nxt[0] == line:
            self.replay_row()
            tail(f"the {'ad-lib' if nxt[1] else 'line'} next — playing the "
                 f"line again, drag it when it comes")
        else:
            tail(f"next: {'ad-lib of ' if nxt[1] else ''}line {nxt[0] + 1}")

    def replay_row(self) -> None:
        """Play the armed row's line from a little before it starts."""
        row = self.list.next_row or self.list.cursor[:2]
        line, voice = row
        if not 0 <= line < len(self.doc.lines):
            return
        a, _b = self.doc.lines[line].span()
        if a is None:
            self.say("nothing in this line is timed yet — play on and drag "
                     "the bar where the words fall")
            return
        g = self.doc.group(line, voice)
        lead_in = bool(voice and getattr(g, "lead_in", False))
        self.seek(max(0.0, a - self.preroll() * (3.0 if lead_in else 1.0)))
        if not self.player.playing():
            self.toggle()

    def armed_row(self) -> tuple:
        return self.list.next_row or self.list.cursor[:2]

    def d_clear(self) -> None:
        row = self.armed_row()
        self.push_undo()
        self.do(ops.clear_times(self.doc, [row]))
        self.list.arm(*row)

    def d_skip(self) -> None:
        """Leave this row and take up the next that wants times.

        Round the end of the song as well, the same way finishing a row does:
        past the last row the work left over is at the top, and stopping dead
        there would be a button that does nothing on a song with holes in it.
        """
        row = self.armed_row()
        nxt = self.list.next_to_time(row) or self.list.step_row(1, row)
        wrapped = False
        if nxt is None:
            nxt, wrapped = self.list.next_to_time(), True
        if nxt is None or nxt == row:
            self.say("that is the last row, and nothing before it wants times")
            return
        self.list.arm(*nxt)
        self.say(("back round to " if wrapped else "")
                 + f"{'the ad-lib of ' if nxt[1] else ''}line {nxt[0] + 1}")

    def d_step(self, delta: int) -> None:
        nxt = self.list.step_row(delta, self.armed_row())
        if nxt is None:
            self.say("no row that way")
            return
        self.list.arm(*nxt)

    def d_resume(self) -> None:
        nxt = self.list.next_to_time()
        if nxt is None:
            self.say("every row has times")
            return
        self.list.arm(*nxt)
        self.say(f"line {nxt[0] + 1}" + (" (ad-lib)" if nxt[1] else "")
                 + " is the first without times")

    def stamp_offset(self) -> float:
        """The offset the clock is running on, remembering what it has been.

        Every time placed in this session is stamped against `position()`,
        which is already lyric time -- the offset has been taken off. So the
        document never carries it, which is the whole point. What CAN go wrong
        is the number changing while a song is half timed: the two halves are
        then stamped against different clocks, and no single shift puts the
        file right again. That cannot be repaired after the fact, so it is
        reported the moment it happens.
        """
        got = round(float(getattr(self.player, "offset", lambda: 0.0)()), 3)
        seen = getattr(self, "_offsets_seen", None)
        if seen is None:
            seen = self._offsets_seen = set()
        if got not in seen:
            if seen and self.doc.timed_lines():
                was = ", ".join(f"{x:+.3f}s" for x in sorted(seen))
                self.say(f"⚠ the player's offset moved to {got:+.3f}s (was "
                         f"{was}) — times placed before and after this are "
                         f"stamped against different clocks")
            seen.add(got)
        return got

    def tap_lag(self) -> float:
        """Seconds to take off a tapped time, from the transport's box."""
        try:
            return float(self.lag_box.value()) / 1000.0
        except Exception:
            return float(K.config().get("tap_lag_ms", 0.0)) / 1000.0

    def step_play(self, delta: int) -> None:
        if self.list.step(delta):
            line, voice, k = self.list.cursor
            s = self.doc.group(line, voice).syls[k]
            if s.timed:
                self.seek(s.start)

    def bump_rate(self, delta: int) -> None:
        """The speed keys, a step of the slider at a time."""
        self.rate_slider.setValue(
            self.rate_slider.value() + delta * self.rate_slider.singleStep())

    # ---------------------------------------------------------------- modes
    def fit_bars(self) -> None:
        if not self.classic():
            return
        holder = self.transport_scroll.widget()
        if holder is not None:
            holder.setMinimumWidth(holder.sizeHint().width())
            self.transport_scroll.setFixedHeight(
                holder.sizeHint().height() + 4)
        self.fit_ribbon()

    def fit_ribbon(self) -> None:
        """Give the scroller exactly the ribbon's height, and no more.

        Recomputed rather than fixed: the height follows the zoom, and a
        scroller left at last size clips the captions after Ctrl+=.
        """
        want = self.ribbon.sizeHint().height()
        bar = self.ribbon_scroll.horizontalScrollBar()
        if bar is not None and bar.isVisible():
            want += bar.sizeHint().height()
        self.ribbon.setMinimumWidth(self.ribbon.sizeHint().width())
        self.ribbon_scroll.setFixedHeight(want + 2)

    def set_mode(self, mode: str) -> None:
        if mode != "drag":
            self.bar.cancel()
        self.list.set_mode(mode)
        self.sync_pad.setVisible(mode == "timing")
        self.bar_box.setVisible(mode == "drag")
        self.mode_seg.set_value(mode)
        self._set_mode_bits()
        self._tap_hint()
        if not self.classic():
            self._show_tools()
        self.fit_bars()
        if mode == "preview":
            self.list.follow = self.follow_box.isChecked()
        if mode == "drag":
            row = self.list.next_row or self.list.next_to_time()
            if row is not None:
                self.list.arm(*row)
            self.fill_bar()
            self.say("drag sync — press at the left of the bar and drag "
                     "across it as the row is sung, one slice per syllable. "
                     "Click a line to put it on the bar; ad-libs are rows of "
                     "their own and get the line played again.")
        self.list.viewport().update()

    def _tap_mode(self) -> str:
        """Which voices tapping walks, from the settings.

        The old boolean is read where the new key is missing, so a session
        that had ad-libs switched off keeps them off.
        """
        got = K.config()
        want = str(got.get("tap_mode") or "")
        if want in TAP_LABELS:
            return want
        return "all" if got.get("tap_adlibs", True) else "lead"

    def _tapping(self, label: str) -> None:
        mode = next((k for k, v in TAP_LABELS.items() if v == label), "all")
        self.list.tap_mode = mode
        K.remember(tap_mode=mode, tap_adlibs=(mode != "lead"))
        self.say(f"tapping: {label.lower()}")
        self._tap_hint()

    def _tap_hint(self) -> None:
        """Amber, while the cursor is on a word the tapping choice leaves out:
        the timing keys (which will not time it), and the tapping choices
        that would. Put back the moment it is on a word that is tapped, or
        the choice is switched."""
        if not hasattr(self, "sync_pad"):
            return
        voice = self.list.cursor[1]
        off = (self.list.mode in ("timing", "drag") and self.doc.lines
               and not self.list.taps(voice))
        want = {"all"} | ({"bg"} if voice else {"lead"})
        marks = [(b, off) for name, (b, _l) in self.sync_pad.buttons.items()
                 if name.startswith("sync_")]
        marks += [(b, off and mode in want)
                  for mode, b in self.tap_seg.buttons.items()]
        marks.append((self.tap_box, off))
        for w, on in marks:
            if (w.property("warn") == "1") != bool(on):
                w.setProperty("warn", "1" if on else "")
                G.restyle(w)

    def _tap_refused(self, voice: int, text: str) -> None:
        """A timing key on a word the tapping choice leaves out: nothing
        stamped, a line saying why, and the tapping choice flashed amber --
        the thing to change, where the eye will find it."""
        kind = "an ad-lib" if voice else "a line word"
        now = TAP_LABELS.get(self.list.tap_mode, "")
        self.say(f"not timed — “{text}” is {kind}, and tapping is set to "
                 f"{now}. Switch Tapping (amber) to time it.")
        self._tap_hint()
        for w in (self.tap_seg, self.tap_box):
            w.setProperty("flash", "1")
            G.restyle(w)

        def done():
            for w in (self.tap_seg, self.tap_box):
                w.setProperty("flash", "")
                G.restyle(w)
        QTimer.singleShot(1200, done)

    def _follow(self, on: bool) -> None:
        self.wave.follow = on
        self.list.follow = on

    def toggle_fold(self) -> None:
        folded = not self.wave.isHidden()
        self.wave.setVisible(not folded)
        self.fold_btn.setText(("Show ▼" if folded else "Hide ▲")
                              if not self.classic() else
                              ("unfold ▼" if folded else "fold ▲"))
        K.remember(wave_folded=folded)

    # -------------------------------------------------------------- sources
    def set_source(self, kind: str) -> None:
        """Swap what the words are being timed against.

        A no-op when nothing changes, because rebuilding a player throws away
        everything it holds -- the file it has open, where it is in it,
        whether it is playing. The import window was doing exactly that by
        accident: a fresh StartPage's combo starts on "Spotify", so telling
        it which source is really in use fired currentTextChanged, and the
        local audio was silently unloaded while the waveform stayed on screen
        looking fine.
        """
        old = getattr(self, "player", None)
        if old is not None and getattr(old, "kind", None) == kind:
            self._rate_enabled(kind == "local")
            return
        if isinstance(old, (LocalPlayer, SpotifyPlayer)):
            try:
                if hasattr(old, "close"):
                    old.close()
                old.deleteLater()
            except Exception:
                pass
        if kind == "local":
            self.player = LocalPlayer(self)
        else:
            try:
                self.player = SpotifyPlayer(self.args.port, self.link, self)
            except Exception as exc:                    # noqa: BLE001
                self.say(f"cannot reach Spotify — {exc}")
                self.player = Player(self)
        self._rate_enabled(kind == "local")
        if kind == "local":
            self.player.set_volume(float(K.config().get("volume", 0.9)))
        self.sync_volume()
        self.sync_vocal_mix()
        self.player.changed.connect(self._track_changed)
        self._track_changed()

    def _track_changed(self) -> None:
        name = " — ".join(x for x in (self.player.artist(), self.player.title()) if x)
        self.track.setText(name or "nothing playing")
        self._who()
        self.start.refresh_track()
        self.wave.length = self.player.duration()
        if self.player.kind == "spotify":
            got = self.player.audio_path()
            if got and got != getattr(self.wave, "_from", ""):
                self.load_envelope(got)
        self.collab.song_changed()

    def open_audio(self, path: str) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open audio", "", AUDIO)
        if not path:
            return
        # Where it was downloaded from, if it is a copy this app kept: those
        # are named by the key their upload is pinned under. Anything else is
        # a file of one's own, and fetch_audio says otherwise when it opens one.
        self.audio_url = sources.kept_source(path)
        if self.player.kind != "local":
            self.set_source("local")
        if not self.player.open(path):
            self.say(f"could not open {path}")
            return
        self.load_envelope(path)
        self._track_changed()
        if bool(K.config().get("vocal_on", False)) and self.wave.vocal is None:
            self.b_vocal_view()

    def fetch_audio(self, then=None) -> None:
        """Find a copy of this song to time against, and open it.

        The one job the editor could not do for itself. Everything it needs
        is already to hand -- the title and artist off the document or the
        player, the length, and the WORDS, which is what turns a search into
        a check: `sources.fetch_audio` plays each candidate to a speech model
        and throws away the ones that are not saying this lyric.

        `then` is called when the errand is over, with the path or "" --
        both ways, not only when it works. A caller that greys a button out
        for the duration has to get it back when there was no copy to be
        found, which is the commoner of the two outcomes.
        """
        meta = self._audio_meta()
        if not meta["title"]:
            self.say("name the song first — Song info…, or type a title")
            return
        words = [w for ln in self.doc.lines for g in ln.groups()
                 for w in g.text().split()]
        tid = self.player.track_id() if self.player.kind == "spotify" else ""
        against = "Spotify" if self.player.kind == "spotify" else "the lyric"
        kept = sources.LA._kept(tid or sources.audio_key(meta["artist"], meta["title"]))

        def done(path, err=None):
            if err or not path:
                why = _reason(err) or "nothing came back"
                self.say(f"no copy could be fetched — {why}")
                # A dialogue and not only the status line: the line is cut
                # to one row on the editor page, and a fetch started from the
                # start page used to end with the button coming back and not
                # a word about why.
                QMessageBox.warning(
                    self, "Could not fetch the song",
                    f"No copy of “{meta['title']}” could be fetched.\n\n"
                    f"{why[:1].upper() + why[1:]}.")
                if then is not None:
                    then("")
                return
            self.open_audio(path)
            # Which upload it is, for multiplayer to hand the others.
            self.audio_url = sources.source_of(meta["title"], meta["artist"],
                                               tid)
            self.collab.song_changed()
            self.say(f"opened {pathlib.Path(path).name}")
            if then is not None:
                then(path)

        def job(say):
            say(f"searching SoundCloud and YouTube for “{meta['title']}”…")
            return sources.audio_hits(meta["title"], meta["artist"],
                                      meta["length"])

        def got(hits, err):
            if err or not (hits or kept):
                done("", err or "nothing found for that search")
                return
            gated = [u for u, why in sources.audio_hits.gated
                     if why == sources.LA.GO_PLUS]
            dlg = AudioPick(hits or [], meta["length"], against, kept, self,
                            gated=len(gated))
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.chosen():
                if then is not None:
                    then("")
                return
            pick = dlg.chosen()
            if pick.get("kept"):
                done(pick["kept"])
                return

            def job2(say):
                say(f"downloading {pick.get('title') or pick['url']}…")
                return sources.fetch_audio_url(pick["url"], meta["title"],
                                               meta["artist"], tid)

            if (not self.run(job2, lambda p, e: done(p, e), lane="audio")
                    and then is not None):
                then("")

        self.say(f"looking for “{meta['title']}”…")
        if not self.run(job, got, lane="audio") and then is not None:
            then("")

    def _audio_meta(self) -> dict:
        """Which song to go looking for.

        Three places, in order of how much they are worth: what the file says
        about itself, what the player is playing, and the FILENAME. The last
        one is not a fallback nobody hits -- most of the lyrics in this
        project carry no Title or Artist at all in their header, and are
        named `Artist - Title.ttml` on disk, which is exactly the two fields
        a search wants. `_song_name` already reads it that way for the
        backups; this reads it the same way and splits it.
        """
        title = str(self.doc.meta.get("Title") or self.player.title() or "")
        artist = str(self.doc.meta.get("Artist") or self.player.artist() or "")
        if not title.strip() and self.path:
            stem = self.path.stem
            artist, _, rest = stem.partition(" - ") if " - " in stem \
                else ("", "", stem)
            title = rest or stem
        return {"title": title.strip(), "artist": artist.strip(),
                "length": self.player.duration() or self._doc_length()}

    def _doc_length(self) -> float:
        """How long the song is, as far as the timed document knows.

        Not nothing: `fetched` searches by length as well as by name, and a
        document that has been timed to the end knows that number even when
        no player is running to say it.
        """
        ends = [s.end for ln in self.doc.lines for g in ln.groups()
                for s in g.syls if s.timed and s.end is not None]
        return max(ends) if ends else 0.0

    def load_envelope(self, path: str) -> None:
        if path != getattr(self.wave, "_from", ""):
            self.wave.vocal = None
            self.wave.show_vocal = self.wave.show_marks = False
            self.wave.claimed = None
            self.wave._pix = None
        self.wave._from = path
        self.sync_vocal_mix()
        self.say("reading the audio…")

        def job(_say):
            return waveform.envelope(path)

        def got(res, err):
            if err or not res or res[0] is None:
                self.say(f"no waveform for that file{' — ' + err if err else ''}")
                return
            self.wave.env, length = res
            self.wave.length = length or self.player.duration()
            self.wave.update()
            self.say(f"waveform ready — {self.wave.length:.0f}s")
            self.collab.envelope_ready()

        self.run(job, got)

    # ---------------------------------------------------------------- files
    def ask_inline_adlibs(self, doc) -> None:
        """Ask what to do with ad-libs written between a line's words.

        "You (Okay) must (Uh) find (Your mind)" is one line whose ad-libs are
        sung in the gaps; the editor keeps a line's ad-libs as voices of their
        own, and there is no telling where the person wants them. So each such
        line is shown with a box holding the usual answer -- one ad-lib at the
        end, "You must find (Okay, uh, your mind)" -- to keep or retype.
        """
        import copy
        found = [i for i in range(len(doc.lines)) if ops.inline_adlibs(doc, i)]
        if not found:
            return
        from PyQt6.QtWidgets import (QDialogButtonBox, QLabel, QLineEdit,
                                     QVBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle("Ad-libs inside lines")
        box = QVBoxLayout(dlg)
        head = QLabel(
            f"{len(found)} line(s) have words in brackets between the others. "
            "Type each line the way it should be — brackets at the end "
            "become ad-libs.")
        head.setWordWrap(True)
        box.addWidget(head)
        # a song can have dozens of these; the rows scroll, the buttons stay
        rows = QWidget()
        lines = QVBoxLayout(rows)
        lines.setContentsMargins(0, 0, 0, 0)
        boxes = []
        for i in found:
            was = M.as_text(M.Doc([doc.lines[i]]))
            tmp = M.Doc([copy.deepcopy(doc.lines[i])])
            ops.gather_adlibs(tmp, 0)
            usual = M.as_text(tmp)
            lab = QLabel(f"{i + 1}.  {was}")
            lab.setWordWrap(True)
            lines.addWidget(lab)
            edit = QLineEdit(usual)
            edit.setMinimumWidth(int(T.px(520)))
            lines.addWidget(edit)
            boxes.append((i, was, usual, edit))
        lines.addStretch(1)
        area = _rows_scroller(rows)
        box.addWidget(area, 1)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        box.addWidget(btn)
        edge = box.contentsMargins()
        bar = area.verticalScrollBar().sizeHint().width()
        _fit_screen(dlg, rows.sizeHint().width() + bar + edge.left()
                    + edge.right(),
                    dlg.sizeHint().height() - area.sizeHint().height()
                    + rows.sizeHint().height())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        for i, was, usual, edit in boxes:
            text = edit.text().strip()
            if not text or text == was:
                continue
            if text == usual:
                ops.gather_adlibs(doc, i)
            else:
                ops.rewrite_line(doc, i, text)

    def take_doc(self, doc, said: str, append: bool = False,
                 path: str = "") -> None:
        """A document from the start screen or the import window.

        Replacing the lyric replaces everything that belonged to the old one:
        the file it was saved to, its title and artist, its songwriters, and
        the Genius song it was matched to. None of that describes the new
        song, and two of them do real damage -- a stale path means Ctrl+S
        overwrites a finished sync with a different song's words, and
        inherited songwriters put the wrong names in the file.
        """
        if not (append and self.doc.lines) and not self.collab.may_replace(
                "this lyric"):
            return
        self.ask_inline_adlibs(doc)
        if append and self.doc.lines:
            self.push_undo()
            self.doc.lines.extend(doc.lines)
            self.do(f"{said}, added to the end")
        else:
            if self.dirty and self.doc.lines:
                backups.stash(self.doc, self._song_name(), "replaced")
            self.push_undo()
            self.doc = doc
            self.path = pathlib.Path(path) if path else None
            self.song_id = None
            from . import syllables as SY
            SY.let_go_all()
            self._undo.clear()
            self._redo.clear()
            self.do(said)
            self.dirty = not path
            self.refresh(relayout=False)
            self._check_language()
        self.show_editor()
        self._fill_writers()
        win = getattr(self, "_import_window", None)
        if win is not None:
            QTimer.singleShot(0, win.accept)

    def _check_language(self) -> None:
        """Overrule a provider's language guess where the words disagree.

        These arrive wrong in one specific way and it is always the same:
        an English lyric filed under a small Latin-script language. It is not
        cosmetic -- it chooses the hyphenation patterns words are cut into
        syllables with, and it goes into the file as xml:lang.
        """
        claimed = str(self.doc.meta.get("LanguageISO2")
                      or self.doc.meta.get("Language") or "")
        if not claimed:
            return
        try:
            import language as LANG
        except Exception:
            return
        said = " ".join(ln.text() for ln in self.doc.lines[:80])
        got, why = LANG.check(claimed, said)
        if got == claimed or not why:
            return
        for key in ("LanguageISO2", "Language"):
            if self.doc.meta.get(key):
                self.doc.meta[key] = got
        self.say(f"language set to {got} — {why}")

    def _fill_writers(self, tries: int = 0) -> None:
        """Look the songwriters up as soon as there is a song to look up.

        They are part of the file and they never change, so there is no
        reason to make somebody open a dialogue and press a button for them at
        the end of an hour's work. Nothing already in the file is touched:
        a name a writer typed, or one the source carried, is the answer.

        The worker takes one errand at a time and the fetch that brought this
        document in may still be winding down, so this waits its turn rather
        than being refused.
        """
        if not self.doc.lines:
            return
        import lyrics_gui as L
        token = L.load_token()
        meta = {"title": str(self.doc.meta.get("Title") or self.player.title()),
                "artist": str(self.doc.meta.get("Artist") or self.player.artist()),
                "length": self.player.duration()}
        if not meta["title"]:
            return
        want = list(self.doc.lines)

        have = bool(self.doc.meta.get("SongWriters"))
        self._apple_writers = None

        def job(_say):
            try:
                apple = sources.apple_writers(meta)
            except Exception:
                apple = ([], "")
            if have or apple[0]:
                return apple, apple
            return sources.songwriters(meta, token, self.song_id), apple

        def got(res, err):
            if err or not res or self.doc.lines is not want:
                return
            res, apple = res
            if apple and apple[0]:
                self._apple_writers = (want, apple)
            if not res or not res[0] or self.doc.meta.get("SongWriters"):
                return
            names, who = res
            self.doc.meta["SongWriters"] = names
            self.dirty = True
            self.say(f"{len(names)} songwriter(s) from {who}")

        if not self.run_quiet(job, got) and tries < 8:
            QTimer.singleShot(600, lambda: self._fill_writers(tries + 1))

    def show_editor(self) -> None:
        self.stack.setCurrentIndex(1)
        self.list.setFocus()

    def show_import(self) -> None:
        """The start screen again -- as a page when there is nothing to lose,
        and in a window of its own when there is."""
        if not self.doc.lines:
            self.stack.setCurrentIndex(0)
            self.start.refresh_track()
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Import lyrics")
        dlg.resize(720, 620)
        page = StartPage(self, standalone=True, parent=dlg)
        page.loaded.connect(self.take_doc)
        page.refresh_track()
        box = QVBoxLayout(dlg)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(page)
        self._import_window = dlg
        dlg.exec()
        gone, self._import_window = self._import_window, None
        if gone is not None:
            gone.setParent(None)
            gone.deleteLater()

    def _stash_current(self, why: str) -> None:
        """Keep unsaved work before something replaces it.

        take_doc has always done this and these two never did, so Ctrl+N and
        Ctrl+O -- one key away from Ctrl+B and Ctrl+P -- threw away an
        afternoon with no prompt and nothing to recover.
        """
        if self.dirty and self.doc.lines:
            backups.stash(self.doc, self._song_name(), why)

    def new_doc(self) -> None:
        if not self.collab.may_replace("an empty lyric"):
            return
        self._stash_current("replaced")
        self.doc = M.Doc()
        from . import syllables as SY
        SY.let_go_all()
        self.path = None
        self.song_id = None
        self._undo.clear()
        self._redo.clear()
        self.refresh()
        self.stack.setCurrentIndex(0)

    def open_lyric(self, path: str) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open lyric", "",
                "Lyrics (" + " ".join("*" + e for e in F.READS)
                + ");;All files (*)")
        if not path:
            return
        doc, said = read_lyric(path)
        if doc is None:
            self.say(said)
            return
        if not self.collab.may_replace(pathlib.Path(path).name):
            return
        self.ask_inline_adlibs(doc)
        self._stash_current("replaced")
        self.doc, self.path = doc, pathlib.Path(path)
        self.song_id = None
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        self.refresh()
        self.show_editor()
        self.say(said)

    @staticmethod
    def _flash(btn) -> None:
        """Show a button pressed for a moment when its key did the work.

        Ctrl+S saved without a flicker anywhere, so a save by key looked no
        different from a key that did nothing. A click already shows itself.
        """
        if btn is None or btn.isDown() or not btn.isVisible():
            return
        btn.setDown(True)
        QTimer.singleShot(150, lambda: btn.setDown(False))

    def save(self, ask: bool = False) -> bool:
        """Write the TTML. Returns whether anything reached the disk.

        The answer matters to closeEvent, which used to close regardless:
        "Save before closing?" -> Save -> cancel the file picker -> the
        window shut anyway and the work went with it.
        """
        self._flash(getattr(self, "save_btn", None))
        if ask or self.path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save TTML",
                                                  self._suggest(), "TTML (*.ttml)")
            if not path:
                self.say("not saved — no file chosen")
                return False
            self.path = pathlib.Path(path)
        elif not self._same_song(self.path):
            other = self._names(self.path) or self.path.name
            got = QMessageBox.warning(
                self, "That file holds a different song",
                f"{self.path.name} currently holds {other}.\n\n"
                f"Save this lyric over it?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.SaveAll
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if got == QMessageBox.StandardButton.Cancel:
                self.say("not saved — nothing was overwritten")
                return False
            if got == QMessageBox.StandardButton.SaveAll:
                return self.save(ask=True)
        backups.keep_copy(self.path)
        try:
            self.path.write_text(self.ttml_out() + "\n", encoding="utf-8")
        except Exception as exc:                        # noqa: BLE001
            self.say(f"could not save — {exc}")
            return False
        self.dirty = False
        self.refresh()
        self.say(f"saved {self.path}")
        return True

    def ttml_out(self) -> str:
        """The TTML Save writes: as it always was, or on one line and/or with
        brackets around the ad-libs, as the Saving settings say. Either reads
        back the same -- see lyric_formats.ttml."""
        cfg = K.config()
        return F.ttml(M.to_body(self.doc), bool(cfg.get("save_compact", False)),
                      bool(cfg.get("save_parens", False)))

    def _save_items(self) -> list:
        """The ▾ beside Save."""
        def flip(key):
            return lambda: K.remember(**{key: not bool(K.config().get(key, False))})
        items = [{"label": "Save as…", "fn": lambda: self.save(ask=True),
                  "tip": "Write the TTML to another file, and go on working "
                         "in that one."}, None]
        items.append({"label": "Save a copy as", "key": "▸",
                      "sub": self._format_items,
                      "tip": "LRC, ASS, KRC, QRC, YRC, LYS, SRT or plain text. "
                             "The TTML stays the file you are working on."})
        items += [None,
                  {"label": "TTML on one line", "fn": flip("save_compact"),
                   "toggle": lambda: bool(K.config().get("save_compact", False)),
                   "tip": "No line break after each line's tag. The words, "
                          "their spaces and their times are the same."},
                  {"label": "Brackets around ad-libs", "fn": flip("save_parens"),
                   "toggle": lambda: bool(K.config().get("save_parens", False)),
                   "tip": "“(oh yeah)” in the file, the way Apple writes them; "
                          "still ad-libs. Also for LYS and ASS."}]
        return items

    def _format_items(self) -> list:
        """The second dropdown: a copy in each of the other formats."""
        return [{"label": f"{label}…", "key": ext, "tip": what,
                 "fn": lambda k=key: self.export(k)}
                for key, label, ext, what in F.FORMATS]

    def _pop(self, items: list) -> None:
        """A save menu under the split button where it is on screen, else
        under the mouse (the classic ribbon)."""
        from PyQt6.QtGui import QCursor
        btn = getattr(self, "save_btn", None)
        menu = G.rich_menu(self, items, 420)
        if btn is not None and btn.isVisible():
            at = btn.mapToGlobal(btn.rect().bottomLeft()) + QPoint(0, T.px(8))
            more = self.save_more
            more.setDown(True)
            menu.exec(at)
            more.setDown(False)
        else:
            menu.exec(QCursor.pos())

    def save_menu(self) -> None:
        """The same menu, from the classic ribbon."""
        self._pop(self._save_items())

    def export(self, fmt: str) -> bool:
        """Save a copy of the lyric in another format. The TTML stays the file
        being worked on: a copy in a format that cannot hold everything the
        TTML does is not somewhere to go on saving to."""
        label, ext = F.LABEL[fmt], F.SUFFIX[fmt]
        start = pathlib.Path(str(self.path) if self.path else self._suggest())
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save a copy as {label}", str(start.with_suffix(ext)),
            f"{label} (*{ext});;All files (*)")
        if not path:
            self.say("not saved — no file chosen")
            return False
        target = pathlib.Path(path)
        if not target.suffix:
            target = target.with_suffix(ext)
        try:
            data, said = F.write(M.to_body(self.doc), fmt,
                                 parens=bool(K.config().get("save_parens", False)))
            if self.doc.lines and said["lines"] >= len(self.doc.lines):
                # An empty file is not a copy of anything.
                self.say(f"not saved — no line has times yet, and {label} "
                         f"has no place for words without them")
                return False
            if isinstance(data, bytes):
                target.write_bytes(data)
            else:
                target.write_text(data, encoding="utf-8")
        except Exception as exc:                        # noqa: BLE001
            self.say(f"could not save the {label} — {exc}")
            return False
        gone = F.left_out(said)
        self.say(f"saved a {label} copy to {target}"
                 + (f" — {gone} left out: {label} has no place for "
                    f"words without times" if gone else ""))
        return True

    def _names(self, path: pathlib.Path) -> str:
        """What a file on disk says it holds, for saying so out loud."""
        try:
            doc = M.from_ttml(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return ""
        if doc is None or not doc.lines:
            return ""
        who = " — ".join(x for x in (str(doc.meta.get("Artist") or ""),
                                     str(doc.meta.get("Title") or "")) if x)
        return who or f"“{doc.lines[0].text()[:40]}…”"

    def _same_song(self, path: pathlib.Path) -> bool:
        """Whether the file at `path` holds what is open here.

        By the words, not by the metadata: a document fetched from one source
        and a file saved from another often disagree about the title while
        being the same song, and the words never do.
        """
        if not path.exists():
            return True
        try:
            doc = M.from_ttml(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return True
        if doc is None or not doc.lines or not self.doc.lines:
            return True
        def head(d):
            return [ln.text().strip().lower() for ln in d.lines
                    if ln.text().strip()][:6]
        theirs, ours = head(doc), head(self.doc)
        if not theirs or not ours:
            return True
        shared = len(set(theirs) & set(ours))
        return shared >= max(1, min(len(theirs), len(ours)) // 2)

    def _song_name(self) -> str:
        who = " - ".join(x for x in (str(self.doc.meta.get("Artist") or ""),
                                     str(self.doc.meta.get("Title") or "")) if x)
        return (who or (self.path.stem if self.path else "")
                or f"{self.player.artist()} - {self.player.title()}".strip(" -")
                or "untitled")

    def _autosave(self) -> None:
        if not self.dirty or not self.doc.lines:
            return
        stamp = (len(self.doc.lines), self.doc.timed_lines(),
                 round(self.doc.duration(), 2), self.collab.stamp())
        if stamp == getattr(self, "_saved_stamp", None):
            return
        self._saved_stamp = stamp
        backups.stash(self.doc, self._song_name(), "working")

    def recover_dialogue(self) -> None:
        """Everything the editor has kept, and a way back to any of it."""
        from PyQt6.QtWidgets import QComboBox, QListWidget, QListWidgetItem
        got = backups.entries()
        dlg = QDialog(self)
        dlg.setWindowTitle("Recover")
        dlg.resize(820, 520)
        box = QVBoxLayout(dlg)
        head = QLabel(
            "Copies the editor kept by itself: unsaved work every half "
            "minute, whatever a fetch replaced, and every file written over. "
            f"They're held for two weeks in {backups.home()}.")
        head.setProperty("hint", "1")
        head.setWordWrap(True)
        box.addWidget(head)
        songs: dict[str, list[dict]] = {}
        for e in got:                       # newest first, so songs are too
            songs.setdefault(e["name"], []).append(e)
        picker = QComboBox()
        for name, rows in songs.items():
            picker.addItem(f"{name}  ({len(rows)})", name)
        if songs:
            box.addWidget(picker)
        listing = QListWidget()
        listing.setFont(T.font(12, 500, mono=True))

        def fill() -> None:
            listing.clear()
            for e in songs.get(picker.currentData(), []):
                when = time.strftime("%d %b %H:%M:%S",
                                     time.localtime(e["when"]))
                it = QListWidgetItem(
                    f"{when}  {e['why']:<9} {e['lines']:>3} lines, "
                    f"{e['timed']:>3} timed   {e['first']}")
                it.setData(Qt.ItemDataRole.UserRole, str(e["path"]))
                listing.addItem(it)
            if listing.count():
                listing.setCurrentRow(0)

        picker.currentIndexChanged.connect(lambda _i: fill())
        fill()
        box.addWidget(listing, 1)
        if not got:
            box.addWidget(QLabel("Nothing kept yet."))
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Open
                               | QDialogButtonBox.StandardButton.Cancel)
        open_btn = btn.button(QDialogButtonBox.StandardButton.Open)
        open_btn.setText("Open this copy")
        open_btn.setProperty("primary", "1")
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        box.addWidget(btn)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        it = listing.currentItem()
        if it is None:
            return
        doc, said = read_lyric(str(it.data(Qt.ItemDataRole.UserRole)))
        if doc is None:
            self.say(said)
            return
        self.take_doc(doc, f"recovered — {said}", False)

    def _suggest(self) -> str:
        name = " - ".join(x for x in (str(self.doc.meta.get("Artist") or ""),
                                      str(self.doc.meta.get("Title") or "")) if x)
        name = name or (f"{self.player.artist()} - {self.player.title()}".strip(" -")
                        or "lyrics")
        safe = "".join(c for c in name if c not in '/\\:*?"<>|').strip()
        return str(saves.from_editor() / f"{safe}.ttml")

    # ----------------------------------------------------------------- undo
    def do(self, said: str | None, *, structural: bool = True) -> None:
        """Finish an edit: remember it, redraw it, and show it in the player."""
        if said is None:
            if self._undo:
                self._undo.pop()
            return
        self.dirty = True
        self.refresh(relayout=structural)
        if said:
            self.say(said)

    def _list_edited(self, said: str) -> None:
        if said and settings.roman("roman_auto"):
            rows = set(self.list.selected()) | {self.list.cursor[0]}
            ops.fill_roman(self.doc, settings.roman("roman_detail"),
                           settings.roman("roman_particles"), sorted(rows))
        self.do(said or None)
        if said and self.find_box.isVisible():
            self.find_run(jump=False)

    def _relearn(self) -> None:
        """After an undo, the word is whatever it is now -- so is the store."""
        at = getattr(self, "_last_word", None)
        if at is None:
            return
        line, voice, syl = at
        g = self.doc.group(line, voice)
        if g is None or not g.syls:
            return
        self.remember_word(line, voice, min(syl, len(g.syls) - 1))

    def push_undo(self) -> None:
        self._undo.append(self.doc.clone())
        del self._undo[:-80]
        self._redo.clear()

    def undo(self) -> None:
        if not self._undo:
            self.say("nothing to undo")
            return
        self._redo.append(self.doc.clone())
        self.doc = self._undo.pop()
        self.dirty = True
        self.refresh()
        self.say("undone")
        self._relearn()

    def redo(self) -> None:
        if not self._redo:
            return
        self._undo.append(self.doc.clone())
        self.doc = self._redo.pop()
        self.refresh()
        self.say("redone")
        self._relearn()

    # ------------------------------------------------------------- painting
    def refresh(self, relayout: bool = True) -> None:
        """Redraw, and tell the player about it.

        The push lives here rather than in do(), because do() is only ONE of
        the ways the document changes. Opening a file, undoing and redoing all
        came through refresh() and never reached the player -- so the words on
        screen there were whatever the last edit had been, and it looked like
        the link dropping messages at random.
        """
        self.list.doc = self.doc
        self.wave.doc = self.doc
        self.fill_bar()
        if relayout:
            self.list.relayout(force=True)
        self.list.viewport().update()
        self.wave.shown = self.list.selected_rows()
        self.wave.cursor = self.list.cursor
        if relayout:
            self._mark_words()
        self._mark_claims()
        self.wave.update()
        self._who()
        self._roman_note = self._roman_count()
        self.roman_wave_sw.setVisible(not self.classic() and self._doc_japanese())
        self._lane_note()
        who = " — ".join(x for x in (str(self.doc.meta.get("Artist") or ""),
                                     str(self.doc.meta.get("Title") or "")) if x)
        self.setWindowTitle(
            f"{'*' if self.dirty else ''}"
            f"{self.path.name if self.path else 'unsaved'}"
            + (f"   ({who})" if who else "")
            + "   —   Mild Lyrics TTML Editor")
        self.schedule_push()
        self.collab.after_refresh()

    def schedule_push(self) -> None:
        """Ask for a push soon, without ever putting one off.

        This used to restart push_timer on every edit, which is a debounce --
        and a debounce starves under precisely the work this window exists
        for. Tapping syllables through a fast line puts an edit in every
        120ms or so, and each one pushed the send another 180ms into the
        future, so nothing at all reached the player until the writer stopped
        to breathe. The sync was updating in real time everywhere except on
        the screen it was being watched on.

        A countdown already running is therefore left alone: the push goes at
        the end of it and carries whatever the document says by then, so the
        player is never more than PUSH_MS behind however fast the tapping is.
        """
        if self.live.isChecked() and not self.push_timer.isActive():
            self.push_timer.start(PUSH_MS)

    def say(self, text: str) -> None:
        self.status.setText(text)
        note = getattr(getattr(self, "start", None), "note", None)
        if note is not None:
            note.setText(text)
            note.setVisible(bool(text))

    def _moving(self) -> bool:
        """Whether the frames have anything to animate: the song, or a drag."""
        return (self.player.playing() or self.bar.dragging()
                or self.list.mode == "preview")

    def frame_pos(self) -> float:
        """Where the song is at the time of the frame being drawn -- see
        frame_clock -- rather than at whatever moment this was asked. The
        playhead, the preview and the sync bar move by the same amount every
        refresh, which is what makes a stamp's place readable against them."""
        pos = self.player.position()
        if self.player.playing():
            rate = float(getattr(self.player, "_rate", 1.0) or 1.0)
            pos = max(0.0, pos + self.frames.lag() * rate)
        return pos

    def _frame(self) -> None:
        pos = self.frame_pos()
        self.wave.set_pos(pos, self.player.playing())
        if self.list.mode == "drag":
            self.bar.set_pos(pos)
        if self.list.mode == "preview" or self.player.playing():
            self.list.set_pos(pos)
        # Everything else at the thirty a second it always had: a label set
        # every refresh is a relayout and a repaint of the glass under it,
        # and the clock's milliseconds change on every one.
        now = time.perf_counter()
        if now - self._chrome_at < 1.0 / CHROME_HZ:
            return
        self._chrome_at = now
        self._follow_tick(moved_only=True)
        self.clock_lbl.setText(_fmt(pos))
        self.play_btn.setText("❚❚  Pause" if self.player.playing() else "▶  Play")
        i, v, k = self.list.cursor
        g = self.doc.group(i, v)
        if self.list.mode == "drag":
            self.tap_lbl.setText(self._drag_hint())
        elif g and 0 <= k < len(g.syls):
            self.tap_lbl.setText(f"next: “{g.syls[k].text}”  "
                                 f"(line {i + 1}, syllable {k + 1}/{len(g.syls)})"
                                 + getattr(self, "_roman_note", ""))
        else:
            self.tap_lbl.setText(getattr(self, "_roman_note", "").lstrip(" ·"))
        off = float(getattr(self.player, "offset", lambda: 0.0)())
        self.offset_lbl.setText(f"offset {off:+.2f}s" if abs(off) >= 0.005 else "")
        if self.player.kind == "spotify" and not self.vol_slider.isSliderDown():
            self.sync_volume()

    def _drag_hint(self) -> str:
        """What the corner says in drag sync: the word under the pointer while
        one is running, and which row is up next while none is."""
        row = self.list.next_row
        if self.bar.dragging():
            g = self.doc.group(*row) if row else None
            k = self.bar.at
            return (f"dragging: “{g.syls[k].text}”"
                    if g and 0 <= k < len(g.syls) else "dragging")
        if row is None:
            return ""
        g = self.doc.group(*row)
        if g is None:
            return ""
        left = sum(1 for s in g.syls if not s.timed)
        return (f"next: {'ad-lib of ' if row[1] else ''}line {row[0] + 1}  "
                + (f"({left} of {len(g.syls)} untimed)" if left
                   else "(all timed — drag it again to redo it)"))

    def _linked(self, on: bool) -> None:
        _flog("link", on=on)
        following = (on and self.player.kind == "spotify"
                     and getattr(self.player, "following_player", bool)())
        self.link_dot.setText("● Mild Lyrics' clock" if following else
                              "● Mild Lyrics" if on else "● no player")
        self.link_dot.setToolTip(
            "Times are stamped against the player's own clock, so what you "
            "place here is where it draws it." if following else
            "The editor's own clock. Connect a player and time against "
            "Spotify to share one.")
        self.link_dot.setStyleSheet("color: #6fd08c" if on else "color: #8b8f9c")
        if on:
            self.link.flush()
            self._push()

    def _rate(self, v: int) -> None:
        """The speed slider moved. Snaps to 1x so full speed is one flick."""
        rate = v / 100.0
        if abs(rate - 1.0) < RATE_DETENT and v != 100:
            self.rate_slider.setValue(100)
            return
        self.rate_lbl.setText(f"{rate:.2f}×")
        self.player.set_rate(rate)
        if bool(K.config().get("rate_keep", False)):
            K.remember_soon(rate=round(rate, 3))

    def _rate_enabled(self, on: bool) -> None:
        self.rate_slider.setEnabled(on)
        self.rate_lbl.setEnabled(on)

    def bump_rate_to(self, rate: float) -> None:
        """Put the slider at a speed, clamped to what it can say."""
        self.rate_slider.setValue(
            int(round(max(RATE_MIN, min(RATE_MAX, rate)) * 100)))

    def _volume(self, v: int) -> None:
        """The slider was moved -- unless it was this window that moved it."""
        self.vol_lbl.setText(f"{v}%")
        if self._vol_quiet:
            return
        self.player.set_volume(v / 100.0)
        if self.player.kind == "local" and bool(
                K.config().get("volume_keep", True)):
            self._vol_save.start()

    def _keep_volume(self) -> None:
        """Write the volume down, whenever the delay above has run out.

        Reads the slider rather than taking a number, so whatever fires it --
        the timer, or `closeEvent` on the way out -- keeps the same thing:
        where the slider was left.
        """
        if self.player.kind == "local" and bool(
                K.config().get("volume_keep", True)):
            K.remember(volume=self.vol_slider.value() / 100.0)

    def sync_volume(self) -> None:
        """Put the slider where the player really is, without answering back."""
        on = self.player.can_volume()
        self.vol_slider.setEnabled(on)
        self.vol_lbl.setEnabled(on)
        if not on:
            return
        want = int(round(self.player.volume() * 100))
        if want != self.vol_slider.value():
            self._vol_quiet = True
            self.vol_slider.setValue(want)
            self._vol_quiet = False

    FOLLOW_SLIP = 0.08

    def _follow_tick(self, moved_only: bool = False) -> None:
        """Tell the player where the local file is, so it draws the words there.

        Mild Lyrics draws against SPOTIFY's clock unless it is told
        otherwise, so a file timed against a local copy of the song swept
        past wherever Spotify happened to be sitting, which is usually nought.
        The one screen meant to show the work in place was the one screen
        that could not. The player now takes this as the clock for the
        document this window pushed -- see its follow_editor -- and walks its
        own Spotify along underneath, muted, where it can.

        Only for a local file: timing against Spotify, the player IS the
        clock and there is nothing to tell it. And only while the document is
        being shown there at all, since this asks it to take hold of
        somebody's playback and that is not a thing to do unasked.

        The stop is sent as deliberately as the rest. The player hands the
        playback back on its own if this window goes silent, but that costs
        it a second or two of muted playing first, and switching to Spotify
        or unticking the box is not a crash.

        `moved_only` is the frame timer's call, between the regular ticks:
        it says something only when the file has gone somewhere the last
        message would not have carried the player to -- a seek, a nudge, a
        pause, a change of speed. Left to the tick, the player drew the old
        place for up to a tenth of a second after every jump, which is the
        whole of what a writer nudging a syllable is watching.
        """
        want = self.live.isChecked() and self.player.kind == "local"
        if not want:
            if self._following:
                self._following = False
                self._follow_sent = None
                _flog("unfollow-sent", live=self.live.isChecked(),
                      kind=self.player.kind)
                self.link.unfollow()
            return
        pos, going = self.player.position(), self.player.playing()
        rate = float(getattr(self.player, "rate", lambda: 1.0)() or 1.0)
        now = time.monotonic()
        was = self._follow_sent
        if moved_only and was is not None:
            w_pos, w_going, w_rate, w_at = was
            guess = w_pos + ((now - w_at) * w_rate if w_going else 0.0)
            if (going == w_going and rate == w_rate
                    and abs(pos - guess) < self.FOLLOW_SLIP):
                return
        self._following = True
        self._follow_sent = (pos, going, rate, now)
        sent = self.link.follow(pos, going, rate)
        _flog("follow-sent", pos=round(pos, 3), playing=going, rate=rate,
              moved=moved_only, sent=sent,
              queued=int(getattr(getattr(self.link, "sock", None),
                                 "bytesToWrite", lambda: -1)()))

    def _player_state(self, got: dict) -> None:
        """Put this document back when the player has stopped showing it.

        The player lets a pushed document go whenever it reloads its own -- R
        does that, and so does anything else that calls reset_track -- and it
        has no way to ask for it back. Left to the next edit, the screen sat
        on the song's own lyrics for as long as the writer happened not to
        type, which reads as the link having quietly died. Every state row
        says whether what is up there is ours, so this notices within one.

        The checkbox is still the switch: turn "Show in Mild Lyrics" off and
        nothing here pushes anything, which is the way to hand the song back
        for good.
        """
        if not self.live.isChecked() or got.get("live"):
            return
        tid = self.player.track_id() if self.player.kind == "spotify" else ""
        if tid and str(got.get("tid") or "") != tid:
            return
        now = time.monotonic()
        if now - self._repush_at < 1.0:
            return
        self._repush_at = now
        _flog("repush", state_tid=got.get("tid"), state_live=got.get("live"),
              state_pos=got.get("pos"))
        self._push()

    def _player_asked(self, got: dict) -> None:
        """A seek or a pause made in Mild Lyrics, for the file timed here.

        While it draws this window's document against this window's file, the
        player's own controls -- clicking a line, the bar, the arrow keys,
        space -- are about THIS file, and it says so rather than moving a
        Spotify nobody is listening to. Timing against Spotify it never asks:
        it moves Spotify, and this window follows Spotify.
        """
        if self.player.kind != "local":
            return
        ev = str(got.get("ev") or "")
        if ev == "seek":
            try:
                to = float(got.get("to"))
            except (TypeError, ValueError):
                return
            self.seek(max(0.0, min(to, self.player.duration() or to)))
        elif ev == "toggle":
            self.toggle()

    def _live_toggled(self, on: bool) -> None:
        _flog("live-toggled", on=on)
        if on:
            self._push()
        else:
            self.link.release()

    def _push(self) -> None:
        """Show the player what has been timed so far.

        Only the timed lines go: see model.timed_only for why. Nothing at all
        goes while nothing is timed -- a static block over the song's own
        lyrics is worse than not touching the player, and there is nothing to
        watch sweep yet either.

        The track id travels only when timing against Spotify. That is what
        lets the player refuse a document meant for a different song; from a
        local file there is no id to check against, and the player takes it
        for whatever it has open, which is the point of pushing at all.
        """
        if not self.live.isChecked() or not self.doc.lines:
            return
        shown = M.timed_only(self.doc)
        if not shown.lines:
            if not self._said_untimed:
                self._said_untimed = True
                self.say("nothing timed yet — the player keeps its own lyrics "
                         "until something is")
            return
        self._said_untimed = False
        tid = self.player.track_id() if self.player.kind == "spotify" else ""
        sent = self.link.push(M.to_ttml(shown), tid,
                              self.path.name if self.path else "unsaved")
        _flog("push", sent=sent, lines=len(shown.lines), tid=tid)

    # ------------------------------------------------------------ selection
    def selected(self) -> list[int]:
        return self.list.selected()

    def _selection_changed(self) -> None:
        self.wave.shown = self.list.selected_rows()
        self._mark_words()
        self.wave.update()
        self.collab.moved()

    def _mark_words(self) -> None:
        """Tell the strip which syllables belong to the picked words, so a
        run picked in the lyric is picked on the strip as well -- and can be
        dragged there as one."""
        got = set()
        picks = self.list.selected_words()
        if len(picks) > 1:
            for line, voice, w in picks:
                g = self.doc.group(line, voice)
                runs = g.words() if g is not None else []
                if 0 <= w < len(runs):
                    got.update((line, voice, k) for k in runs[w])
        self.wave.chosen = got

    def _wave_picked(self, i: int, v: int, k: int) -> None:
        """A block pressed on the strip: the same choosing as in the lyric.

        Ctrl adds the word to the words picked or takes it away; a press on
        a word already among several keeps them all, since that is how a run
        is picked up to drag; anything else picks the one word.
        """
        w = self.list.word_at(i, v, k)
        sel = self.list.word_sel
        if w is not None:
            if self.wave.press_mods & Qt.KeyboardModifier.ControlModifier:
                self.list.word_sel = sel ^ {w}
                self.list._word_anchor = w
            elif not (w in sel and len(sel) > 1):
                self.list.word_sel = {w}
                self.list._word_anchor = w
        self.list.set_cursor(i, v, k)
        self._mark_words()
        self.list.viewport().update()
        self.wave.update()

    def _cursor_moved(self, i: int, v: int, k: int) -> None:
        self.collab.moved()
        self._mark_words()
        self._tap_hint()
        self.wave.cursor = (i, v, k)
        s = self.doc.group(i, v).syls[k] if self.doc.group(i, v) else None
        if s is not None and s.timed and not self.player.playing():
            self.wave.centre(s.start)
        self.wave.update()

    def _dragged(self, i: int, v: int, k: int, a: float, b: float) -> None:
        if self.wave._grab and not getattr(self, "_dragging", False):
            self._dragging = True
            self.push_undo()
        elif not self.wave._grab:
            self._dragging = False
        grab = self.wave._grab
        if grab is not None and grab[3] == "body" and (i, v, k) in self.wave.chosen:
            # One of several picked words, taken by its middle: they all go,
            # by the same amount, so what was sung against what stays put.
            s = self.doc.group(i, v).syls[k]
            if s.start is not None:
                delta = float(a) - s.start
                syls = [self.doc.group(li, vo).syls[kk]
                        for li, vo, kk in self.wave.chosen
                        if self.doc.group(li, vo) is not None
                        and kk < len(self.doc.group(li, vo).syls)]
                timed = [x for x in syls if x.timed]
                if timed:
                    delta = max(delta, -min(x.start for x in timed))
                    for x in timed:
                        x.start += delta
                        if x.end is not None:
                            x.end += delta
                self.do("", structural=False)
                return
        ops.set_time(self.doc, i, v, k, a, b)
        self.do("", structural=False)

    def play_from_line(self) -> None:
        sel = self.selected()
        if not sel:
            return
        a, _b = self.doc.lines[sel[0]].span()
        if a is not None:
            self.seek(max(0.0, a - 0.3))
            if not self.player.playing():
                self.toggle()

    # ------------------------------------------------------------- dialogues
    def info_dialogue(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Song info")
        dlg.resize(520, 240)
        box = QVBoxLayout(dlg)
        grid = QGridLayout()
        fields = {}
        for r, (key, label) in enumerate((("Title", "Title"), ("Artist", "Artist"),
                                          ("SongWriters", "Songwriters"),
                                          ("LanguageISO2", "Language"))):
            grid.addWidget(QLabel(label), r, 0)
            ed = QLineEdit()
            got = self.doc.meta.get(key)
            if got is None and key == "LanguageISO2":
                got = self.doc.meta.get("Language")
            ed.setText(", ".join(str(x) for x in got) if isinstance(got, list)
                       else str(got or ""))
            grid.addWidget(ed, r, 1)
            fields[key] = ed
        fields["SongWriters"].setToolTip(
            "Comma separated; written as one <songwriter> each.")
        box.addLayout(grid)
        row = QHBoxLayout()
        look = QPushButton("Look up songwriters")
        look.setToolTip("Genius' credits, or Apple Music's where Genius has no "
                        "page for the song. These are the names its editors "
                        "credit — usually the names the artists go by.")
        look.clicked.connect(lambda: self.fetch_writers(fields["SongWriters"]))
        row.addWidget(look)
        legal = QPushButton("…as Apple credits them")
        legal.setToolTip(
            "Apple Music's own writer credits, taken from the publishing. "
            "Where the publishing uses a legal name, that is what comes back "
            "— luther gives “Roshwita Larisha Bacha” and “Mark Anthony "
            "Spears” where Genius gives “Ink” and “Sounwave”. On a "
            "self-released track the two agree.")
        legal.clicked.connect(
            lambda: self.fetch_writers(fields["SongWriters"], apple=True))
        row.addWidget(legal)
        take = QPushButton("Title and artist from the player")
        take.clicked.connect(lambda: (fields["Title"].setText(self.player.title()),
                                      fields["Artist"].setText(self.player.artist())))
        row.addWidget(take)
        box.addLayout(row)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", "1")
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        box.addWidget(btn)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.push_undo()
        for key, ed in fields.items():
            text = ed.text().strip()
            if key == "SongWriters":
                names = [w.strip() for w in text.split(",") if w.strip()]
                if names:
                    self.doc.meta["SongWriters"] = names
                else:
                    self.doc.meta.pop("SongWriters", None)
            elif key == "LanguageISO2":
                for both in ("LanguageISO2", "Language"):
                    if text:
                        self.doc.meta[both] = text
                    else:
                        self.doc.meta.pop(both, None)
            elif text:
                self.doc.meta[key] = text
            else:
                self.doc.meta.pop(key, None)
        self.do("song info saved", structural=False)

    def fetch_writers(self, field: QLineEdit, apple: bool = False) -> None:
        import lyrics_gui as L
        token = L.load_token()
        meta = {"title": str(self.doc.meta.get("Title") or self.player.title()),
                "artist": str(self.doc.meta.get("Artist") or self.player.artist()),
                "length": self.player.duration()}

        pre = getattr(self, "_apple_writers", None)
        if apple and pre and pre[0] is self.doc.lines:
            names, who = pre[1]
            field.setText(", ".join(names))
            self.say(f"{len(names)} songwriter(s) from {who}")
            return

        def job(say):
            say("looking up the credits…")
            if apple:
                return sources.apple_writers(meta)
            return sources.songwriters(meta, token, self.song_id)

        def got(res, err):
            if err or not res or not res[0]:
                self.say(f"nobody found{' — ' + err if err else ''}")
                return
            names, who = res
            field.setText(", ".join(names))
            self.say(f"{len(names)} songwriter(s) from {who}")

        self.run(job, got)

    def text_dialogue(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit as text")
        dlg.resize(720, 640)
        box = QVBoxLayout(dlg)
        hint = QLabel("Lines you do not change keep their timing, and so do "
                      "the words of the ones you do.   <b>&gt;</b> = the "
                      "answering voice,   <b>(brackets)</b> at either end, or "
                      "on the row under a line = its backing vocals.")
        hint.setWordWrap(True)
        hint.setProperty("hint", "1")
        box.addWidget(hint)
        ed = QPlainTextEdit(M.as_text(self.doc))
        ed.setFont(QFont("monospace", 11))
        box.addWidget(ed, 1)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", "1")
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        box.addWidget(btn)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.apply_text(ed.toPlainText())

    def apply_text(self, text: str) -> None:
        """Take edited text back into the document, keeping what still fits.

        Compared ROW by row, the whole row -- voice mark and brackets
        included. Matching on the lead's words alone read "Line" turned into
        "Line (Ad-lib)" as no change at all, kept the old line, and the
        ad-lib that had just been typed was thrown away.

        A row that did not change is the old line exactly as it was: its
        times, and its shape -- an ad-lib given a row of its own stays one.
        A row that did is read afresh, and each of its words takes the times
        of the same word in the rows it replaced, so adding an ad-lib to a
        timed line costs the line nothing. A row of brackets alone that was
        typed or changed is the ad-lib of the line above it.
        """
        from difflib import SequenceMatcher

        def key(row: str) -> str:
            return " ".join(row.split())

        old = [key(M.text_row(ln)) for ln in self.doc.lines]
        rows = [r for r in text.replace("\r\n", "\n").split("\n")
                if r.strip()]
        new = [key(r) for r in rows]
        if old == new:
            self.say("nothing changed")
            return
        self.push_undo()
        out, kept = [], 0
        for tag, i1, i2, j1, j2 in SequenceMatcher(
                None, old, new, autojunk=False).get_opcodes():
            if tag == "equal":
                out.extend(self.doc.lines[i1:i2])
                kept += i2 - i1
                continue
            was = self.doc.lines[i1:i2]
            pool = ops.time_pool(was)
            for n, row in enumerate(rows[j1:j2]):
                ln = M.parse_row(row)
                if ln is None:
                    continue
                ops.take_times(pool, ln, prefer=n)
                own = n < len(was) and not was[n].lead.syls
                if not ln.lead.syls and out and not own:
                    M.under(out[-1], ln.bg)
                else:
                    out.append(ln)
        self.doc.lines = out
        self.do(f"{len(out)} lines — {kept} unchanged")

    def detect(self, alternate: bool = False) -> None:
        self.push_undo()
        self.do(sources.detect_roles(self.doc, alternate))

    def b_swap_agents(self) -> None:
        """The selection, or the whole song when nothing is picked."""
        sel = self.selected()
        self.push_undo()
        self.do(ops.swap_agents(self.doc, sel or None))

    def run(self, job, done, lane: str = "main") -> bool:
        """An errand on a thread that cleans itself up; one per `lane`.

        Returns whether it started, the way `run_quiet` already does. A
        caller that greys a button out for the duration needs to know it was
        turned away, or the button never comes back.

        The lanes are kinds of errand that have nothing to wait for from each
        other. There used to be one slot for everything, so a download of the
        song -- a minute or more -- turned away "From Genius" and every other
        lyric lookup with "still busy with the last one" until it was done.
        Fetching the words and fetching the audio now go side by side: "audio"
        and "lyrics", and "main" for the rest. Two of the same kind still
        queue behind each other, which is the point of having a slot at all.

        The lane is given back BEFORE `done` runs, not when the thread gets
        round to stopping. `quit` only asks; a follow-up started from inside
        `done` -- the download done, so read the file it made -- found the
        thread still winding down and was refused.
        """
        if lane in self._lanes:
            self.say("still busy with the last one")
            return False
        thread = QThread(self)
        worker = Work(job)
        worker.moveToThread(thread)
        worker.said.connect(self.say)
        thread.started.connect(worker.run)
        held = (thread, worker)
        self._lanes[lane] = held
        self._jobs.append(held)

        def finish(res, err):
            if self._lanes.get(lane) is held:
                del self._lanes[lane]
            thread.quit()
            done(res, err)

        def gone():
            if held in self._jobs:
                self._jobs.remove(held)

        worker.done.connect(finish)
        thread.finished.connect(gone)
        thread.start()
        return True

    def run_quiet(self, job, done) -> bool:
        """A background chore, on a slot of its own. Returns whether it started.

        Nothing here was asked for, so it must never be in the way: taking
        the one worker thread would mean somebody pressing "From Genius" a
        second after importing got "still busy with the last one" for an
        errand they did not ask for and cannot see. It also says nothing on
        the way -- a chore that narrates itself is just noise over the
        status line somebody is reading for their own work.
        """
        got = getattr(self, "_chore", None)
        if got is not None and got.isRunning():
            return False
        self._chore = QThread(self)
        self._chore_worker = Work(job)
        self._chore_worker.moveToThread(self._chore)
        self._chore.started.connect(self._chore_worker.run)

        def finish(res, err):
            self._chore.quit()
            done(res, err)

        self._chore_worker.done.connect(finish)
        self._chore.start()
        return True

    # -------------------------------------------------------------- editing
    def _cursor_word(self):
        """(line, voice, syllable, word) for wherever the cursor is."""
        i, v, k = self.list.cursor
        g = self.doc.group(i, v)
        if g is None or not 0 <= k < len(g.syls):
            return None
        for w, run in enumerate(g.words()):
            if k in run:
                return i, v, k, w
        return None

    def b_split_line(self) -> None:
        got = self._cursor_word()
        if not got:
            self.say("click a word first")
            return
        i, _v, _k, w = got
        self.push_undo()
        self.do(ops.split_line(self.doc, i, w))

    def b_merge_lines(self) -> None:
        """Run the selected lines together -- each unbroken run of them.

        Not the span from the first to the last. A selection with a gap in
        it used to swallow the lines nobody had picked, and a merged line is
        the one edit here whose damage cannot be seen at a glance afterwards.
        """
        sel = self.selected()
        if len(sel) < 2:
            self.say("select two or more lines (ctrl or shift-click)")
            return
        self.push_undo()
        self.do(ops.merge_runs(self.doc, sel))

    def b_duplicate(self) -> None:
        self.push_undo()
        self.do(ops.duplicate_rows(self.doc, self.list.selected_rows()
                                   or [self.list.cursor[:2]]))

    def b_delete(self) -> None:
        """Delete what is selected: a syllable, the words, else the rows."""
        self.push_undo()
        one = self.list.picked_syllable()
        if one:
            self.list.word_sel = set()
            self.do(ops.delete_syllables(self.doc, *one, one[2]))
            return
        words = self.list.selected_words()
        if words:
            self.list.word_sel = set()
            self.do(ops.delete_words(self.doc, words))
            return
        self.do(ops.delete_rows(self.doc, self.list.selected_rows()
                                or [self.list.cursor[:2]]))

    def b_insert(self) -> None:
        """A new line, with the cursor already in it waiting for the words.

        One implementation, in the list, so the ribbon and the right-click
        menu cannot drift apart -- which they had: the menu inserted a line
        and stopped, leaving an empty one and no way to type into it.
        """
        sel = self.selected()
        self.list.insert_below((sel[-1] + 1) if sel else len(self.doc.lines))

    def b_move(self, delta: int) -> None:
        """Up and down. On a backing voice that means among its neighbours.

        The moved lines stay selected, and the cursor goes with them. They
        did not before, so the selection sat still while the lines slid past
        it: pressing ↑ twice moved one line up and then a DIFFERENT line up,
        which is never what anybody means by pressing it twice.
        """
        rows = self.list.selected_rows() or [self.list.cursor[:2]]
        self.push_undo()
        if rows and all(v for _i, v in rows):
            self.do(ops.move_rows(self.doc, rows, delta))
            return
        lines = sorted({i for i, _v in rows})
        said = ops.move_rows(self.doc, rows, delta)
        if said:
            moved = {i + delta for i in lines}
            self.list.select(sorted(moved))
            i, v, k = self.list.cursor
            if i in lines:
                self.list.set_cursor(i + delta, v, k, reveal=True)
        self.do(said)

    @staticmethod
    def split_learn() -> bool:
        """Whether a split corrected or made by hand is written down for the
        word -- the automatic split's "Remember corrections"."""
        return bool(K.config().get("split_learn", True))

    def split_settings(self) -> tuple[str, str, bool]:
        got = K.config()
        return (str(got.get("split_method") or "sung"),
                str(got.get("split_lang") or self._lang()),
                bool(got.get("split_resplit")))

    def auto_split_args(self):
        """What to cut a typed word with, or None when the setting is off."""
        if not K.config().get("split_auto", False):
            return None
        method, lang, _again = self.split_settings()
        return {"method": method, "lang": lang, "unit": self.split_unit()}

    @staticmethod
    def split_unit() -> str:
        """How a script that is not the Latin alphabet is cut: "syllable",
        "mora" or "word" -- see syllables.UNITS."""
        got = str(K.config().get("split_unit") or "syllable")
        return got if got in ("syllable", "mora", "word") else "syllable"

    def _lang(self):
        """The document's own language, where it says, else English.

        A file that says it is Dutch should not be cut by English patterns,
        and pyphen has the patterns for both.
        """
        from . import syllables as SY
        want = str(self.doc.meta.get("LanguageISO2")
                   or self.doc.meta.get("Language") or "").replace("-", "_")
        try:
            import language as LANG
            want = LANG.check(want, " ".join(ln.text() for ln in
                                             self.doc.lines[:80]))[0] or want
        except Exception:
            pass
        if not want:
            return SY.DEFAULT_LANG
        have = SY.languages()
        for name in (want, want.split("_")[0]):
            for cand in have:
                if cand.lower() == name.lower() or cand.lower().startswith(
                        name.lower() + "_"):
                    return cand
        return SY.DEFAULT_LANG

    def b_syllabify(self, lines=None, method=None, lang=None,
                    resplit=None, unit=None) -> None:
        want_m, want_l, want_r = self.split_settings()
        method = method or want_m
        lang = lang or want_l
        resplit = want_r if resplit is None else resplit
        unit = unit or self.split_unit()
        picked = self._picked_words() if lines is None else []
        if picked:
            self.push_undo()
            done = 0
            for (i, v), words in ops._by_group(self.doc, picked).items():
                if ops.syllabify(self.doc, i, v, words, method=method,
                                 lang=lang, resplit=resplit, unit=unit):
                    done += 1
            self.do(f"cut the selected words in {done} voice(s)"
                    if done else None)
            return
        sel = lines if lines is not None else (
            self.selected() or [self.list.cursor[0]])
        self.push_undo()
        done = 0
        for i in sel:
            if not 0 <= i < len(self.doc.lines):
                continue
            for v in range(len(self.doc.lines[i].groups())):
                if ops.syllabify(self.doc, i, v, method=method, lang=lang,
                                 resplit=resplit, unit=unit):
                    done += 1
        self.do(f"split {done} voice(s) across {len(sel)} line(s)"
                if done else None)

    def split_dialogue(self) -> None:
        """Choose the rule, see what it would do, then do it."""
        from . import syllables as SY
        from PyQt6.QtWidgets import (QButtonGroup, QRadioButton, QTableWidget,
                                     QTableWidgetItem, QHeaderView)
        method, lang, resplit = self.split_settings()
        dlg = QDialog(self)
        dlg.setWindowTitle("Automatic split")
        _fit_screen(dlg, 680, 800)
        box = QVBoxLayout(dlg)

        group = QButtonGroup(dlg)
        for key, label, why in SY.METHODS:
            b = QRadioButton(label)
            b.setProperty("key", key)
            b.setToolTip(why)
            b.setChecked(key == method)
            if key == "hyphen" and not SY.available():
                b.setEnabled(False)
                b.setText(label + "  (needs pyphen)")
            group.addButton(b)
            box.addWidget(b)
            note = QLabel(why)
            note.setProperty("hint", "1")
            note.setWordWrap(True)
            note.setContentsMargins(22, 0, 0, 6)
            box.addWidget(note)

        units = QButtonGroup(dlg)
        head = QLabel("Japanese, Chinese, Korean, Cyrillic, Greek")
        head.setProperty("caption", "1")
        head.setContentsMargins(0, 6, 0, 0)
        box.addWidget(head)
        urow = QHBoxLayout()
        for key, label, why in SY.UNITS:
            b = QRadioButton(label)
            b.setProperty("key", key)
            b.setToolTip(why)
            b.setChecked(key == self.split_unit())
            units.addButton(b)
            urow.addWidget(b)
        urow.addStretch(1)
        box.addLayout(urow)
        unote = QLabel("")
        unote.setProperty("hint", "1")
        unote.setWordWrap(True)
        unote.setContentsMargins(22, 0, 0, 6)
        box.addWidget(unote)

        def unit():
            b = units.checkedButton()
            return str(b.property("key")) if b else "syllable"

        def unit_note():
            why = ("as sung in English: ん, っ, ー and long vowels kept on "
                   "their syllable (がっ | こう, せん | せい); a kanji, hanzi or "
                   "hangul block each — Cyrillic and Greek by their vowels"
                   if unit() == "syllable" else
                   "Japanese a kana at a time (が | っ | こ | う); otherwise "
                   "as by syllable" if unit() == "mora" else
                   "Japanese kept whole with its endings and particles "
                   "(君の | 聞こえる); Korean, Cyrillic, Greek at their spaces")
            if unit() == "word" and not SY.chinese_words_complete():
                why += ("; Chinese only roughly — install jieba (setup.sh "
                        "offers it) for proper words")
            unote.setText(why)

        row = QHBoxLayout()
        row.addWidget(QLabel("Language"))
        langs = QComboBox()
        langs.addItems(SY.languages())
        langs.setCurrentText(lang if lang in SY.languages() else SY.DEFAULT_LANG)
        langs.setToolTip("Hyphenation only — the sung rule is written for "
                         "English and the languages that spell like it.")
        row.addWidget(langs)
        row.addStretch(1)
        whole = QCheckBox("the whole song")
        whole.setChecked(not self.selected() or len(self.selected()) < 2)
        row.addWidget(whole)
        again = QCheckBox("re-split words already split")
        again.setToolTip("Off by default: those pieces may have been placed "
                         "by hand or measured from the audio.")
        again.setChecked(resplit)
        row.addWidget(again)
        box.addLayout(row)
        learn = QCheckBox("Remember corrections")
        learn.setToolTip(
            "On: a split you correct here — or make by hand in the lyric — is "
            "kept for that word, in this song and every song after it.\n\n"
            "Off: corrections hold for this song only and nothing is written "
            "down. For a song you do not want cut all the way through — a "
            "word timed whole on purpose, a name sung its own way this once — "
            "without teaching the rule that for good.")
        learn.setChecked(self.split_learn())
        box.addWidget(learn)

        shown = QLabel("")
        shown.setProperty("hint", "1")
        box.addWidget(shown)
        hint = QLabel("Type over a split to correct it — pieces separated by "
                      "<b>|</b>, Enter to keep. A correction wins over the "
                      "rule for that word; leave one piece to say “never "
                      "split this”. Sung more than one way? Put <b>/</b> "
                      "between them, the usual one first — "
                      "<b>lone|lier / lone|li|er</b>. Case and the word's "
                      "punctuation can be left off.")
        hint.setProperty("hint", "1")
        hint.setWordWrap(True)
        box.addWidget(hint)
        preview = QTableWidget(0, 3)
        preview.setHorizontalHeaderLabels(["word", "split", ""])
        preview.verticalHeader().setVisible(False)
        preview.setFont(T.font(13, 500, mono=True))
        preview.horizontalHeader().setStretchLastSection(False)
        preview.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        preview.setColumnWidth(0, 190)
        preview.setColumnWidth(2, 74)
        box.addWidget(preview, 1)
        note = QLabel("")
        note.setProperty("hint", "1")
        box.addWidget(note)

        def scope():
            return (list(range(len(self.doc.lines))) if whole.isChecked()
                    else (self.selected() or [self.list.cursor[0]]))

        def chosen():
            b = group.checkedButton()
            return str(b.property("key")) if b else "sung"

        def refresh():
            words = []
            for i in scope():
                if not 0 <= i < len(self.doc.lines):
                    continue
                for g in self.doc.lines[i].groups():
                    for run in g.words():
                        if len(run) > 1 and not again.isChecked():
                            continue
                        words.append(g.word_text(run))
            seen, uniq = set(), []
            for w in words:
                if SY.key(w) not in seen:
                    seen.add(SY.key(w))
                    uniq.append(w)
            kept = SY.overrides()
            unsaved = SY.held()
            rows = []
            ja = ops.japanese(self.doc)
            for w in uniq:
                pieces = SY.split(w, chosen(), langs.currentText(), unit(), ja)
                if len(pieces) > 1 or SY.key(w) in kept:
                    rows.append((w, pieces))
            ways = {}
            for w, pieces in rows:
                more = SY.ways_for(w)[1:]
                if more:
                    ways[w] = "|".join(pieces) + "".join(
                        " / " + "|".join(m) for m in more)
                if len(rows) >= 400:
                    break
            preview.blockSignals(True)
            preview.setRowCount(len(rows))
            for r, (w, pieces) in enumerate(rows):
                first = QTableWidgetItem(w)
                first.setFlags(Qt.ItemFlag.ItemIsEnabled
                               | Qt.ItemFlag.ItemIsSelectable)
                first.setForeground(T.q(T.MUTE))
                preview.setItem(r, 0, first)
                cell = QTableWidgetItem(ways.get(w, "|".join(pieces)))
                cell.setData(Qt.ItemDataRole.UserRole, w)
                preview.setItem(r, 1, cell)
                mark = QTableWidgetItem(
                    "this song" if SY.key(w) in unsaved
                    else "kept" if SY.key(w) in kept else "")
                if SY.key(w) in unsaved:
                    mark.setToolTip("Held for this song only — not written "
                                    "down, because Remember corrections is "
                                    "off.")
                mark.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
                mark.setForeground(T.q(T.LEAD))
                preview.setItem(r, 2, mark)
            preview.blockSignals(False)
            cut = sum(1 for _w, p in rows if len(p) > 1)
            saved = len(kept) - sum(1 for k in unsaved if k not in SY._kept())
            shown.setText(f"{cut} of {len(uniq)} words would be cut, across "
                          f"{len(scope())} line(s)"
                          + (f" — {saved} correction(s) remembered"
                             if saved else "")
                          + (f", {len(unsaved)} for this song only"
                             if unsaved else ""))

        def corrected(item):
            if item.column() != 1:
                return
            word = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if not word:
                return
            ways, bad = SY.parse_ways(word, item.text())
            if bad or not ways:
                note.setText(f"“{bad or item.text()}” does not spell {word} "
                             f"— a split may be wrong, the lyric may not "
                             f"change")
                QTimer.singleShot(0, refresh)
                return
            said = " / ".join("|".join(w) for w in ways)
            if learn.isChecked():
                SY.let_go(word)
                SY.remember_split(word, ways[0], also=ways[1:])
                note.setText(f"remembered: {word} → {said}")
            else:
                SY.hold(word, ways)
                note.setText(f"for this song only: {word} → {said}")
            QTimer.singleShot(0, refresh)

        preview.itemChanged.connect(corrected)

        for w in (whole, again):
            w.toggled.connect(refresh)
        learn.toggled.connect(lambda on: K.remember(split_learn=bool(on)))
        langs.currentTextChanged.connect(refresh)
        group.buttonClicked.connect(refresh)
        units.buttonClicked.connect(lambda _b: (unit_note(), refresh()))
        unit_note()
        refresh()

        under = QHBoxLayout()
        forget = QPushButton("Forget this correction")
        forget.setProperty("ghost", "1")
        forget.setToolTip("Put the selected word back under the rule. One "
                          "held for this song only goes first, and the kept "
                          "one — if there is one — answers again.")

        def drop():
            items = preview.selectedItems()
            if not items:
                return
            word = str(preview.item(items[0].row(), 0).text())
            if SY.let_go(word):
                note.setText(f"let go: {word} is back under "
                             + ("its kept split" if SY.key(word) in SY._kept()
                                else "the rule"))
                QTimer.singleShot(0, refresh)
            elif SY.forget_split(word):
                note.setText(f"forgotten: {word}")
                QTimer.singleShot(0, refresh)

        forget.clicked.connect(drop)
        under.addWidget(forget)
        under.addStretch(1)
        box.addLayout(under)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        ok = btn.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Split")
        ok.setProperty("primary", "1")
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        box.addWidget(btn)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        K.remember(split_method=chosen(), split_lang=langs.currentText(),
                   split_resplit=again.isChecked(), split_unit=unit())
        self.b_syllabify(scope(), chosen(), langs.currentText(),
                         again.isChecked(), unit())

    def remember_word(self, line: int, voice: int, syl: int) -> None:
        """Keep how this word was split, so the next song spells it the same.

        A split made by hand is a decision about the word, not about this one
        line of this one song -- the automatic split learns it the same way a
        correction typed into its dialogue does. A word taken back apart, or
        undone, forgets it again: the store always says what the word looks
        like now, never what it looked like once.
        """
        from . import syllables as SY
        g = self.doc.group(line, voice)
        if g is None or not 0 <= syl < len(g.syls):
            return
        run = next((r for r in g.words() if syl in r), None)
        if not run:
            return
        word = g.word_text(run)
        pieces = [g.syls[i].text for i in run]
        self._last_word = (line, voice, run[0])
        also, self.list.split_also = getattr(self.list, "split_also",
                                             False), False
        if not self.split_learn():
            # Remember corrections is off: the split is this song's alone.
            # Held rather than dropped, so Syllabify and the automatic split
            # answer the same way for the rest of the song -- and nothing in
            # the store is added to or taken away.
            if len(pieces) > 1:
                low = [x.lower() for x in pieces]
                ways = [w for w in SY.ways_for(word)
                        if [x.lower() for x in w] != low]
                SY.hold(word, ways + [pieces] if also else [pieces] + ways)
            else:
                SY.let_go(word)
            return
        if len(pieces) > 1:
            if SY.is_accepted(word, pieces):
                return
            if also:
                if SY.add_also(word, pieces):
                    self.say(f"remembered: {word} → {'|'.join(pieces)}, "
                             f"as well as the usual way")
            elif SY.remember_split(word, pieces):
                self.say(f"remembered: {word} → {'|'.join(pieces)}")
        elif SY.forget_split(word):
            self.say(f"forgotten: {word} is one piece again")

    def b_split_word(self) -> None:
        i, v, k = self.list.cursor
        self.push_undo()
        self.do(self.list._split_prompt(i, v, k))
        self.remember_word(i, v, k)

    def b_absorb_marks(self) -> None:
        """Whole song, not the selection: it is a repair, not an edit."""
        self.push_undo()
        self.do(ops.absorb_marks(self.doc)
                or "no marks standing on their own")

    def _picked_words(self) -> list:
        """The words that are selected — more than one, or nothing.

        One selected word is the ordinary case and stays the cursor's job:
        the word operations mean subtly different things on a single word
        (join with the NEXT one) than on a run (join these together), and
        quietly changing which one a single click gets would be worse than
        the bug this fixes.
        """
        got = self.list.selected_words()
        return got if len(got) > 1 else []

    def b_join(self) -> None:
        picked = self._picked_words()
        if picked:
            self.push_undo()
            self.do(ops.join_run(self.doc, picked))
            return
        got = self._cursor_word()
        if not got:
            return
        i, v, _k, w = got
        self.push_undo()
        self.do(ops.join_words(self.doc, i, v, w))
        self.remember_word(i, v, _k)

    def b_join_one(self) -> None:
        glued: list[str] = []
        picked = self._picked_words()
        if picked:
            self.push_undo()
            self.do(ops.join_run_as_one(self.doc, picked, note=glued.extend))
            self.keep_whole(glued)
            return
        got = self._cursor_word()
        if not got:
            return
        i, v, _k, w = got
        self.push_undo()
        self.do(ops.join_as_one(self.doc, i, v, w, note=glued.extend))
        self.keep_whole(glued)

    def keep_whole(self, phrases: list[str]) -> None:
        """Keep these phrases from being cut back up by the automatic split.

        Not remember_word, which is about where a word comes apart -- this is
        the other kind of decision the same store holds: a kept split of ONE
        piece, which says leave it alone. Without it, "Syllabify" would undo
        every glue on the line, because a piece spelling two words is exactly
        what it exists to cut apart when a SOURCE hands one over ("do your",
        "let 'em"). Deliberate here, incidental there, and only the person who
        pressed the button knows which.

        It carries to the next song for the same reason a hand split does:
        "Est-ce que" is sung as one wherever it is sung.
        """
        from . import syllables as SY
        if not self.split_learn():
            for p in phrases:
                SY.hold(p, [[p]])
            return
        kept = [p for p in phrases if SY.remember_split(p, [p])]
        if kept:
            self.say(f"sung as one: {kept[0]}"
                     + (f" (+{len(kept) - 1} more)" if len(kept) > 1 else "")
                     + " — remembered, so the automatic split leaves it")

    def b_end_word(self) -> None:
        picked = self._picked_words()
        if picked:
            self.push_undo()
            self.do(ops.break_words(self.doc, picked))
            return
        i, v, k = self.list.cursor
        self.push_undo()
        self.do(ops.end_word(self.doc, i, v, k))
        self.remember_word(i, v, k)

    def b_merge_syls(self) -> None:
        picked = self._picked_words()
        if picked:
            self.push_undo()
            self.do(ops.merge_words(self.doc, picked))
            return
        i, v, k = self.list.cursor
        self.push_undo()
        self.do(ops.merge_syllables(self.doc, i, v, k, k + 1))
        self.remember_word(i, v, k)

    def b_flip_agent(self) -> None:
        sel = self.selected()
        if not sel:
            return
        now = self.doc.lines[sel[0]].agent
        self.push_undo()
        self.do(ops.set_agent(self.doc, sel, "v2" if now == "v1" else "v1"))

    def b_to_bg(self) -> None:
        i, v, k = self.list.cursor
        if v != 0:
            self.say("that is already a backing vocal")
            return
        g = self.doc.group(i, 0)
        if g is None:
            return
        self.push_undo()
        self.do(ops.to_background(self.doc, i, k, len(g.syls) - 1))

    def b_to_lead(self) -> None:
        rows = self.list.selected_rows() or [self.list.cursor[:2]]
        self.push_undo()
        self.do(ops.to_leads(self.doc, rows))

    def b_spread(self) -> None:
        """Every selected row, not the one the cursor is in."""
        rows = self.list.selected_rows() or [self.list.cursor[:2]]
        self.push_undo()
        self.do(ops.spread_rows(self.doc, rows))

    def b_shift(self, delta: float) -> None:
        sel = self.list.selected_rows() or [self.list.cursor[:2]]
        self.push_undo()
        self.do(ops.shift(self.doc, sel, delta), structural=False)

    def b_nudge_syl(self, delta: float) -> None:
        i, v, k = self.list.cursor
        g = self.doc.group(i, v)
        if g is None or not 0 <= k < len(g.syls) or not g.syls[k].timed:
            return
        s = g.syls[k]
        self.push_undo()
        self.do(ops.set_time(self.doc, i, v, k, s.start + delta,
                             (s.end or s.start) + delta), structural=False)

    def b_clear(self) -> None:
        self.push_undo()
        self.do(ops.clear_times(self.doc, self.list.selected_rows()
                                or [self.list.cursor[:2]]))

    def b_snap(self) -> None:
        self.push_undo()
        self.do(ops.snap_line_ends(self.doc))

    def seek(self, t: float) -> None:
        _flog("seek", to=round(t, 3), was=round(self.player.position(), 3),
              caller=__import__("lyrics_gui")._flog_caller())
        self.player.seek(t)
        self.wave.pos = t
        self.wave.update()

    def toggle(self) -> None:
        self.player.toggle()

    # ---------------------------------------------------------------- storage
    def cache_dialogue(self) -> None:
        """Every cache, its size, and a button to clear it.

        The sizes are the whole point. A cache nobody can see is a cache
        nobody clears, and the animated covers alone reach three quarters of
        a gigabyte on a machine that has done nothing unusual.

        The two the inventory marks `keep` are shown with a warning and are
        left out of "clear everything": one is work this machine did and the
        other is the backup net under this very editor.
        """
        import caches
        dlg = QDialog(self)
        dlg.setWindowTitle("Storage")
        _fit_screen(dlg, 720, 520)
        box = QVBoxLayout(dlg)
        head = QLabel("")
        head.setProperty("hint", "1")
        head.setWordWrap(True)
        box.addWidget(head)
        page = QWidget()
        stack = QVBoxLayout(page)
        stack.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        stack.addLayout(grid)
        stack.addStretch(1)
        box.addWidget(_rows_scroller(page), 1)

        def fill(refresh: bool = True) -> None:
            while grid.count():
                w = grid.takeAt(0).widget()
                if w is not None:
                    w.setParent(None)
            got = caches.sizes(refresh=refresh)
            rows = [r for r in got.values() if not r.get("training")]
            rows.sort(key=lambda r: -r["bytes"])
            for i, row in enumerate(rows):
                name = QLabel(row["label"] + ("  *" if row.get("keep") else ""))
                name.setToolTip(row["note"])
                grid.addWidget(name, i, 0)
                amount = QLabel(row["human"])
                amount.setAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
                grid.addWidget(amount, i, 1)
                btn = QPushButton("Clear")
                btn.setEnabled(row["bytes"] > 0)
                btn.clicked.connect(
                    lambda _c=False, k=row["key"]: one(k))
                grid.addWidget(btn, i, 2)
            spare = sum(r["bytes"] for r in rows if not r.get("keep"))
            head.setText(
                f"{caches.cache_dir()}\n\n"
                f"{caches.human(sum(r['bytes'] for r in rows))} in total, of "
                f"which {caches.human(spare)} can go without losing anything "
                f"this machine made. Rows marked * are the exception — "
                f"alignments made here, the copies this editor keeps for you, "
                f"and which recording each timing was made against — so they "
                f"are cleared only one at a time.")

        def one(key: str) -> None:
            row = caches.sizes().get(key) or {}
            if row.get("keep") and not _confirm(dlg, row):
                return
            _ok, _freed, why = caches.clear(key)
            self.say(why)
            fill()

        def everything() -> None:
            freed, said = caches.clear_all(include_kept=False)
            self.say(f"{caches.human(freed)} freed" if said
                     else "the caches were already empty")
            fill()

        bar = QHBoxLayout()
        creds = QPushButton("Forget credentials")
        creds.setToolTip("The Genius token you typed in, and the Apple Music "
                         "key this app fetched for itself.")
        creds.clicked.connect(lambda: self._forget_creds(dlg))
        bar.addWidget(creds)
        bar.addStretch(1)
        allbtn = QPushButton("Clear everything safe")
        allbtn.clicked.connect(everything)
        bar.addWidget(allbtn)
        done = QPushButton("Done")
        done.clicked.connect(dlg.accept)
        bar.addWidget(done)
        box.addLayout(bar)
        fill()
        dlg.exec()

    def _forget_creds(self, parent) -> None:
        import caches
        held = [c["label"] for c in caches.credentials() if c["present"]]
        if not held:
            self.say("nothing stored to forget")
            return
        if QMessageBox.question(
                parent, "Forget credentials",
                "Forget " + " and ".join(held) + "?\n\n"
                "The Apple key re-fetches itself. The Genius token is yours "
                "and would have to be typed in again.") != \
                QMessageBox.StandardButton.Yes:
            return
        _n, said = caches.forget()
        self.say("; ".join(said))

    # ------------------------------------------------------------ the model
    def _vocal_ready(self) -> str:
        """The song whose separated vocal is on disk, or "".

        Both halves have to be true. `wave.vocal` says this window has the
        separation open -- the answer to "when vocals are separated" -- and
        the stem file says the audio of it was kept, which a map made before
        this existed did not do. A song separated by an older build has its
        picture and no sound, and turning the vocal view on again is what
        gets it; `VocalMap._read` refuses such a map so that happens by
        itself.
        """
        wave = getattr(self, "wave", None)
        if wave is None or wave.vocal is None or not self.player.can_hear():
            return ""
        path = self.player.audio_path()
        if not path:
            return ""
        try:
            return path if vocalmap.stem_path(path).exists() else ""
        except Exception:                                # noqa: BLE001
            return ""

    def sync_vocal_mix(self) -> None:
        """Offer the control, or explain why it is not on offer."""
        path = self._vocal_ready()
        on = bool(path)
        for w in (self.voc_slider, self.voc_amt, self.voc_lbl):
            w.setEnabled(on)
        tip = ("Time against the separated vocal instead of the mixture. At "
               "0% you hear the song as it is; at 100% the demucs vocal on "
               "its own; in between the backing is turned down by that "
               "much.\n\nIt changes nothing that is written — a word placed "
               "with the band off is placed at the time it is sung in the "
               "song.\n\nThe first mix at a given position takes a moment to "
               "render; both ends are instant, because both are already on "
               "disk.")
        if not on:
            if not self.player.can_hear():
                tip = ("Local audio only — Spotify plays what Spotify has.\n\n"
                       "Open the audio file to time against the separated "
                       "vocal.")
            elif getattr(getattr(self, "wave", None), "vocal", None) is None:
                tip = ("Turn the vocal view on first — this plays the stem it "
                       "separates, and there is nothing separated yet.")
            else:
                tip = ("This song was separated before the stem was kept as "
                       "audio. Turn the vocal view off and on again to "
                       "separate it once more, and it will be here.")
            if self.voc_slider.value():
                self.voc_slider.setValue(0)
        for w in (self.voc_slider, self.voc_amt, self.voc_lbl):
            w.setToolTip(tip)
        self._vocal_label()

    def _restore_vocal_mix(self) -> None:
        """Put the slider back where it was left, now that it can move.

        Only on a song that has just been separated, and only where the
        setting is not 0 -- so somebody who timed a hard verse with the band
        at a quarter gets it back on the next song without asking, and
        somebody who has never touched it sees nothing happen. It is said out
        loud either way: what is coming out of the speakers is not what the
        file sounds like, and that is not a thing to change silently.
        """
        want = int(K.config().get("vocal_mix", 0) or 0)
        want = max(0, min(100, want))
        if not want or not self.voc_slider.isEnabled():
            return
        if self.voc_slider.value() == want:
            self._vocal_apply()
        else:
            self.voc_slider.setValue(want)

    def _vocal_label(self) -> None:
        v = self.voc_slider.value()
        self.voc_amt.setText("mix" if not v else
                             ("stem" if v >= 100 else f"{v}%"))

    def _vocal_mix(self, v: int) -> None:
        """The slider moved. The render waits for the hand to stop."""
        self._vocal_label()
        if not self.voc_slider.isEnabled():
            return
        K.remember_soon(vocal_mix=int(v))
        if v <= 0 or v >= 100:
            self._voc_render.stop()
            self._vocal_apply()
            return
        self._voc_render.start()

    def _vocal_apply(self) -> None:
        """Put the mix the slider is asking for onto the speakers."""
        path = self._vocal_ready()
        if not path or self._voc_busy:
            return
        level = self.voc_slider.value() / 100.0
        want = str(path)
        if level > 0:
            try:
                if level >= 1.0:
                    want = str(vocalmap.stem_path(path))
                else:
                    ready = vocalmap.blend_path(path, level)
                    if not ready.exists():
                        self._vocal_render(path, level)
                        return
                    want = str(ready)
            except Exception as exc:                     # noqa: BLE001
                self.say(f"could not use the separated vocal — {exc}")
                return
        if self.player.heard() != want:
            self.player.hear(want)
        self.say("the song as it is" if level <= 0 else
                 ("the separated vocal alone" if level >= 1.0 else
                  f"the vocal up, the backing at {100 - self.voc_slider.value()}%"))

    def _vocal_render(self, path: str, level: float) -> None:
        """Mix one off the main thread, then come back and play it."""
        self._voc_busy = True

        def job(say):
            return vocalmap.blend(path, level, say)

        def got(res, err):
            self._voc_busy = False
            if err or not res:
                self.say(f"could not mix the vocal — {err or 'nothing came back'}")
                return
            if abs(self.voc_slider.value() / 100.0 - level) > 1e-6:
                self._vocal_apply()
                return
            self.player.hear(str(res))
            self.say(f"the vocal up, the backing at "
                     f"{100 - self.voc_slider.value()}%")

        self.run(job, got)

    def b_vocal_view(self) -> None:
        """Put the separated vocal's spectrogram behind the words.

        The separation is the slow part and it is done once per song, kept on
        disk by `vocalmap` -- so this is a minute the first time somebody
        opens a song and nothing the second.
        """
        if self.wave.vocal is not None:
            self.wave.show_vocal = not self.wave.show_vocal
            self.wave.show_marks = self.wave.show_vocal
            self.wave.update()
            self.say("vocal view on" if self.wave.show_vocal
                     else "back to the envelope")
            return
        path = self.player.audio_path() or getattr(self.wave, "_from", "")
        if not path:
            self.say("open the audio file first — there is nothing to separate")
            return
        from . import stem
        ok, why = stem.available()
        if not ok:
            self.say(why)
            return

        def job(say):
            got = vocalmap.VocalMap.build(path, stems=True, say=say)
            # Worked out here, off the window's thread: the marks are a
            # second of pitch tracking, and asked for first by the strip's
            # paint they froze the editor for that second the moment the
            # view came on.
            got.marks()
            got.flux()
            return got

        def got(res, err):
            if err or res is None:
                self.say(f"no vocal view — {err or 'nothing came back'}")
                return
            spans = self._sung_spans()
            fit = res.agrees(spans)
            if spans and not fit.get("trusted"):
                ask = QMessageBox.question(
                    self, "This may not be the same recording",
                    f"The audio open here does not look like the recording "
                    f"this lyric was timed against, so the marks behind the "
                    f"words may land nowhere in particular.\n\n"
                    f"{fit.get('why') or ''}\n\n"
                    f"Show it anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if ask != QMessageBox.StandardButton.Yes:
                    self.wave.vocal = None
                    self.sync_vocal_mix()
                    self.say(f"vocal view not shown — "
                             f"{fit.get('why') or 'wrong song'}")
                    return
                self.say("vocal view — shown at your say-so; the audio and "
                         "the lyric do not agree")
            self.wave.vocal = res
            self.wave.show_vocal = self.wave.show_marks = True
            self.wave._pix = None
            self._mark_claims()
            self.wave.update()
            self.sync_vocal_mix()
            self._restore_vocal_mix()
            marks = res.marks()
            agree = fit.get("separation")
            self.say(f"vocal view — {len(marks['starts'])} place(s) the "
                     f"singing starts, {len(marks['entrances'])} of them out "
                     f"of silence"
                     + (f"; the audio agrees with the lyric by {agree} points"
                        if agree is not None else ""))

        self.say("separating the vocal…")
        self.run(job, got)

    def b_vocal_marks(self) -> None:
        if self.wave.vocal is None:
            self.say("nothing to mark yet — turn the vocal view on first")
            return
        self.wave.show_marks = not self.wave.show_marks
        self._mark_claims()
        self.wave.update()
        self.say("marks on" if self.wave.show_marks else "marks off")

    def _mark_claims(self) -> None:
        """Work out which marks the document can account for, for the strip.

        Recomputed with the document because moving one word changes which
        marks are contested -- a mark that two syllables were both near stops
        being contested the moment one of them moves away. Cheap enough to do
        on every edit (a few hundred marks against a few hundred syllables)
        and only done while the marks are on screen.
        """
        if self.wave.vocal is None or not self.wave.show_marks:
            self.wave.claimed = None
            return
        rows = list(range(len(self.doc.lines)))
        got = ops.claims(self.doc, rows, self.wave.vocal.marks()["starts"])
        self.wave.claimed = got["usable"]

    def _sung_spans(self) -> list:
        """Every stretch the document says somebody is singing in."""
        return [(s.start, s.end if s.end is not None else s.start + 0.1)
                for ln in self.doc.lines for g in ln.groups()
                for s in g.syls if s.timed]

    def vocal_report(self) -> None:
        """What the vocal does and does not say about this document.

        This used to offer to move words onto the marks, and it should not
        have. The marks are not consistent enough to edit with: on the file
        this was built against, the same word sung again gets a mark in some
        repeats and not others, and where it does the offset varies by up to
        130 ms -- see `ops.consistency`, which is measured here per song and
        put at the top of this window rather than buried in a docstring.

        So nothing in this dialogue changes a timing. It answers three
        questions instead, which is what the picture is actually good for:
        how far can the marks be trusted on THIS song, which marks are too
        ambiguous to read, and which words are sitting nowhere near anything
        the singer did. The tool for moving words is Time selection, which
        knows the lyric and can therefore tell a `sane` from a `she`.
        """
        if self.wave.vocal is None:
            self.say("separate the vocal first — Vocal view")
            return
        vm = self.wave.vocal
        rows = self._timing_scope()
        marks = vm.marks()
        dlg = QDialog(self)
        dlg.setWindowTitle("What the vocal says")
        dlg.resize(720, 560)
        box = QVBoxLayout(dlg)
        head = QLabel("")
        head.setProperty("hint", "1")
        head.setWordWrap(True)
        box.addWidget(head)

        row = QHBoxLayout()
        row.addWidget(QLabel("count a word as near a mark within"))
        reach = QDoubleSpinBox()
        reach.setRange(0.02, 1.0)
        reach.setSingleStep(0.01)
        reach.setDecimals(2)
        reach.setSuffix(" s")
        reach.setValue(float(K.config().get("snap_reach", ops.RADIUS)))
        row.addWidget(reach)
        row.addStretch(1)
        box.addLayout(row)

        report = QLabel("")
        report.setWordWrap(True)
        report.setFont(QFont("monospace", 10))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(report)
        box.addWidget(scroll, 1)

        def measure():
            far = reach.value()
            got = ops.claims(self.doc, rows, marks["starts"])
            fit = ops.consistency(self.doc, rows, marks["starts"])
            bias, voted = ops.vocal_bias(self.doc, rows, marks["starts"], far)
            head.setText(
                f"{len(marks['starts'])} place(s) the vocal starts something, "
                f"{len(marks['entrances'])} of them out of real silence. "
                f"{voted} of your words sit within {far:.2f}s of one, "
                f"{bias * 1000:+.0f} ms from it on average. Nothing here "
                f"changes a timing — to move words, use Time selection, "
                f"which knows what the words are.")
            out = [
                "HOW FAR THE MARKS CAN BE TRUSTED ON THIS SONG",
                f"  {fit['covered'] * 100:.0f}% of your words have a mark of "
                f"their own ({fit['heads']} words)",
                f"  of {len(fit['words'])} words sung three times or more, "
                f"{fit['tight']} agree across their repeats to within "
                f"{ops.TIGHT} ms",
                f"  median spread between repeats: {fit['spread']:.0f} ms",
                "",
            ]
            if fit["words"]:
                out.append("  the least repeatable, worst first —")
                for word, n, offs, sp in fit["words"][:8]:
                    shown = " ".join("  —  " if o is None else f"{o:+4d}"
                                     for o in offs[:8])
                    out.append(f"    {word:<10} sung {n:>2}   {shown}"
                               f"   spread {sp:>3} ms")
                out.append("")
            out += [
                "WHICH MARKS ARE READABLE",
                f"  {len(got['owner'])} belong to one syllable and no other",
                f"  {len(got['contested'])} have two syllables near them — "
                f"drawn dotted, and read as evidence for neither",
                f"  {len(got['orphan'])} have no timed syllable near them at "
                f"all — a breath, a leak, or a word not timed yet",
                "",
            ]
            adrift = ops.stranded(self.doc, rows, marks["starts"], reach=far,
                                  bias=bias)
            if adrift:
                out.append(f"WORDS SITTING MORE THAN {far:.2f}s FROM ANYTHING "
                           f"THE VOCAL DOES  ({len(adrift)})")
                out.append("  worth another listen; nothing has been moved —")
                for i, v, w, d in adrift[:14]:
                    g = self.doc.group(i, v)
                    runs = g.words() if g else []
                    text = g.word_text(runs[w]) if g and w < len(runs) else "?"
                    out.append(f"    line {i + 1:<4} {text:<16} {d:.2f}s away")
                if len(adrift) > 14:
                    out.append(f"    … and {len(adrift) - 14} more")
            report.setText("\n".join(out))

        reach.valueChanged.connect(lambda _v: measure())
        measure()
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn.rejected.connect(dlg.reject)
        btn.accepted.connect(dlg.reject)
        box.addWidget(btn)
        dlg.exec()
        K.remember(snap_reach=reach.value())

    def _timing_scope(self):
        """The lines a timing command applies to: the selection, or all."""
        return self.selected() or list(range(len(self.doc.lines)))

    def b_from_first(self) -> None:
        """Time the lines whose first word somebody has already placed.

        Only those. A line with nothing timed has no anchor to work from and
        a fully timed line has nothing to ask for, so both are passed over
        rather than refused -- the selection is usually a verse and this is
        the one thing in it that applies.
        """
        rows = self._timing_scope()
        vocal = self.wave.vocal
        starts = ends = notes = bias = None
        voted = 0
        if vocal is not None:
            marks = vocal.marks()
            starts, ends = marks["starts"], marks["ends"]
            notes = set(vocal.notes())
            bias, voted = ops.vocal_bias(self.doc, list(range(len(self.doc.lines))),
                                         starts)
        self.push_undo()
        said, done = [], 0
        for i in rows:
            got = (ops.from_first(self.doc, i, 0, starts, bias, ends=ends, weak=notes)
                   if vocal is not None else ops.from_first(self.doc, i, 0))
            if got:
                done += 1
                said.append(got)
        if not done:
            self.say("no line here has its first word timed and the rest not")
            return
        self.do(said[0] if done == 1 else
                f"timed {done} line(s) from their first words"
                + (f", aimed {bias:+.3f}s off the attack the way this file "
                   f"does ({voted} words voted)" if voted >= 8 else ""),
                structural=False)

    def b_fill_gaps(self) -> None:
        rows = self._timing_scope()
        self.push_undo()
        self.do(ops.fill_gaps(self.doc, rows,
                              float(K.config().get("snap_gap", ops.MAX_GAP))),
                structural=False)

    def _take_times(self, timed: M.Doc, indices) -> int:
        """Take the model's TIMES onto the live document, not its document.

        The model runs on a clone, and the window is not frozen while it does
        -- it takes a minute or two. Assigning the clone back over the top
        threw away every edit made in the meantime, silently. Only the lines
        that still say what they said are updated, because a line whose words
        have changed is a line those times no longer describe.

        Returns how many lines were left alone for that reason, so the window
        can say so rather than leaving somebody to notice.
        """
        skipped = 0
        for i in indices:
            if not (0 <= i < len(self.doc.lines) and 0 <= i < len(timed.lines)):
                continue
            mine, theirs = self.doc.lines[i], timed.lines[i]
            if mine.text() != theirs.text() or len(mine.bg) != len(theirs.bg):
                skipped += 1
                continue
            mine.lead, mine.bg = theirs.lead, theirs.bg
            mine.start, mine.end = theirs.start, theirs.end
        return skipped

    # ------------------------------------------------------------- shutdown
    # -------------------------------------------------------- romanisation
    def _doc_japanese(self) -> bool:
        return bool(self.doc.lines) and ops.japanese(self.doc)

    def _roman_look(self) -> None:
        """Hand the romanisation settings to the widgets that draw them."""
        self.list.roman_show = bool(settings.roman("roman_show"))
        self.list.roman_detail = str(settings.roman("roman_detail"))
        self.wave.roman_only = bool(settings.roman("roman_wave"))
        self.list.relayout(force=True)
        self.wave.update()

    def _roman_count(self) -> str:
        if not settings.roman("roman_show") or not ops.needs_roman(self.doc):
            return ""
        have, want = ops.roman_count(self.doc)
        if settings.roman("roman_detail") == "per line":
            lines = [g for ln in self.doc.lines for g in ln.groups()
                     if SL.needs_roman(g.text())]
            done = sum(1 for g in lines if g.roman_text())
            return f"  ·  {done} of {len(lines)} lines romanised"
        return f"  ·  {have} of {want} syllables romanised" if want else ""

    def _roman_typed(self, line: int, voice: int, syl: int, text: str) -> None:
        """A reading typed into the list: -1 as `syl` is the whole line's."""
        self.push_undo()
        said = (ops.set_line_roman(self.doc, line, voice, text) if syl < 0
                else ops.set_roman(self.doc, line, voice, syl, text))
        if said is None and self._undo:
            self._undo.pop()
            return
        self.do(said, structural=True)

    def b_roman_show(self) -> None:
        on = not settings.roman("roman_show")
        self.apply_settings(self._keep(roman_show=on))
        self.say("romanisation shown under the words" if on
                 else "romanisation hidden")

    def b_roman_fill(self) -> None:
        if not ops.needs_roman(self.doc):
            self.say("nothing in this lyric needs a reading")
            return
        self.push_undo()
        said = ops.fill_roman(self.doc, settings.roman("roman_detail"),
                              settings.roman("roman_particles"))
        if said is None:
            if self._undo:
                self._undo.pop()
            import spicy_lyrics as SLx
            words = [s.text for ln in self.doc.lines for g in ln.groups()
                     for s in g.syls]
            self.say("every syllable already has a reading" if
                     SLx.can_read(words, ops.japanese(self.doc)) else
                     "the romaniser for this script is not installed — "
                     "pykakasi for Japanese, pypinyin for Chinese")
            return
        self.do(said)

    def b_roman_clear(self) -> None:
        if not any(g.roman or any(s.roman for s in g.syls)
                   for ln in self.doc.lines for g in ln.groups()):
            self.say("there is no romanisation to take off")
            return
        if self.classic():
            ok = QMessageBox.question(
                self, "Clear romanisation?",
                "Take every reading off the lyric — the ones you typed "
                "too?") == QMessageBox.StandardButton.Yes
            if not ok:
                return
        self.push_undo()
        self.do(ops.clear_roman(self.doc))

    def b_roman_genius(self) -> None:
        """Genius' romanised lyric, lined up with these words, shown first.

        Found the way the player finds it (genius_roman.find_romanisation),
        and lined up by the same alignment: each of our lines is read with
        the romaniser, and the Genius lines are matched against those, in
        order, so a line is never given another line's reading. What would
        change is listed before anything is taken, one tick each.

        A line that already HAS a reading is not passed over any more. That
        reading is usually the romaniser's, and the romaniser is exactly what
        Genius is better than -- a particle read as written, a long vowel
        lost, a word run into the next. Where the two disagree (past case,
        spacing, punctuation and accents) the line is listed as a correction,
        and taking it puts the reading right in place: see
        ops.correct_reading, which keeps each syllable carrying its own piece.
        Readings typed by hand are listed the same way and can be unticked.
        """
        import genius_roman as GR
        import lyrics_gui as L
        token = L.load_token()
        title = str(self.doc.meta.get("Title") or self.player.title() or "")
        artist = str(self.doc.meta.get("Artist") or self.player.artist() or "")
        if not token:
            self.say("From Genius needs a Genius token — set one in Mild "
                     "Lyrics' Settings ▸ Romanisation")
            return
        if not title:
            self.say("From Genius needs the song's title — Song info… first")
            return
        ja = ops.japanese(self.doc)
        rows = [(i, v, g) for i, ln in enumerate(self.doc.lines)
                for v, g in enumerate(ln.groups()) if SL.needs_roman(g.text())]
        if not rows:
            self.say("nothing in this lyric needs a reading")
            return
        ours = [ops.line_reading(g, ja) or g.text() for _i, _v, g in rows]

        def job(say):
            say("looking for a romanised lyric on Genius…")
            return GR.find_romanisation(token, title, artist)

        def got(res, err):
            if err or not res:
                self.say(f"Genius has no romanised lyric for this song"
                         f"{' — ' + err if err else ''}")
                return
            lines, hit = res
            mapping = GR.align(ours, lines)
            change = []
            for n, text in sorted(mapping.items()):
                if not text:
                    continue
                was = rows[n][2].roman_text()
                if was and ops.reading_key(was) == ops.reading_key(text):
                    continue
                change.append((rows[n], text, was))
            if not change:
                self.say(f"Genius' “{hit.get('full_title', 'romanisation')}” "
                         f"agrees with every reading already here")
                return
            picked = self._pick_readings(hit.get("full_title", "Genius"),
                                         change)
            if not picked:
                return
            self.push_undo()
            new = fixed = 0
            for (i, v, _g), text, was in picked:
                done = bool(ops.correct_reading(self.doc, i, v, text))
                if was:
                    fixed += done
                else:
                    new += done
            self.do(", ".join(x for x in (
                f"{new} reading(s) from Genius" if new else "",
                f"{fixed} put right from Genius" if fixed else "") if x)
                or "nothing changed")

        self.run(job, got, lane="lyrics")

    def _pick_readings(self, title: str, change: list) -> list:
        """Every reading Genius would give or put right, one tick each.

        New readings and corrections both start ticked -- the corrections
        are what was asked for -- and untick whatever was typed by hand and
        should stay. Returns the ticked rows of `change`.
        """
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        dlg = QDialog(self)
        dlg.setWindowTitle("Romanisation from Genius")
        dlg.resize(720, 520)
        box = QVBoxLayout(dlg)
        adds = sum(1 for *_x, was in change if not was)
        head = QLabel(f"{title}: {adds} line(s) with no reading yet, "
                      f"{len(change) - adds} where Genius reads it "
                      f"differently. Untick any to leave as it is.")
        head.setWordWrap(True)
        box.addWidget(head)
        lst = QListWidget()
        lst.setFont(T.font(13, 500))
        for (_i, _v, g), text, was in change:
            label = (f"{g.text()}\n    was  {was}\n    now  {text}" if was
                     else f"{g.text()}\n    new  {text}")
            it = QListWidgetItem(label)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            lst.addItem(it)
        box.addWidget(lst, 1)
        row = QHBoxLayout()
        for label, on in (("Tick all", True), ("Untick all", False)):
            b = QPushButton(label)
            b.setProperty("ghost", "1")
            b.clicked.connect(lambda _c=False, on=on: [
                lst.item(n).setCheckState(Qt.CheckState.Checked if on
                                          else Qt.CheckState.Unchecked)
                for n in range(lst.count())])
            row.addWidget(b)
        row.addStretch(1)
        box.addLayout(row)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        take = btn.button(QDialogButtonBox.StandardButton.Ok)
        take.setText("Take them")
        take.setProperty("primary", "1")
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        box.addWidget(btn)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return []
        return [c for n, c in enumerate(change)
                if lst.item(n).checkState() == Qt.CheckState.Checked]

    # --------------------------------------------------------------- lanes
    def toggle_lanes(self) -> None:
        self.wave.lanes_all = not self.wave.lanes_all
        K.remember(lanes_all=self.wave.lanes_all)
        self._lane_note()
        self.wave.update()

    def _lane_note(self) -> None:
        """"+1 hidden · Show all 4 voices", or nothing when all of them fit."""
        total, shown = self.wave.lane_counts()
        cap = self.wave.MAX_LANES
        many = total > cap
        self.lanes_btn.setVisible(many)
        self.lanes_note.setVisible(many and not self.wave.lanes_all
                                   and not self.classic())
        self.lanes_note.setText(f"+{total - cap} hidden")
        self.lanes_btn.setText(f"Show {cap} voices" if self.wave.lanes_all
                               else f"Show all {total} voices")
        want = self.wave.want_height()
        base = T.px(float(K.config().get("wave_height", 210.0)))
        self.wave.setMaximumHeight(max(base, want))
        self.wave.setMinimumHeight(max(T.px(120), min(want, T.px(420))))

    def _who(self) -> None:
        """The song's name at the right of the new toolbar."""
        title = str(self.doc.meta.get("Title") or self.player.title() or "")
        artist = str(self.doc.meta.get("Artist") or self.player.artist() or "")
        album = str(self.doc.meta.get("Album") or "")
        self.title_lbl.setText(title or "untitled")
        self.artist_lbl.setText(" · ".join(x for x in (artist, album) if x))

    def closeEvent(self, ev) -> None:                    # noqa: N802 (Qt name)
        if self.dirty:
            got = QMessageBox.question(
                self, "Unsaved changes", "Save before closing?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if got == QMessageBox.StandardButton.Cancel:
                ev.ignore()
                return
            if got == QMessageBox.StandardButton.Save and not self.save():
                ev.ignore()
                return
        if self._vol_save.isActive():
            self._vol_save.stop()
            self._keep_volume()
        K.flush()
        # Before the player is let go: leaving must not redraw and push again.
        self.collab.leave(closing=True)
        if self._following:
            self.link.unfollow()
        if self.live.isChecked():
            self.link.release()
            self.link.wait_sent()
        if hasattr(self.player, "close"):
            self.player.close()
        ev.accept()


def _scroller(widget) -> QScrollArea:
    """A widget that keeps its natural width and scrolls when there is less.

    A layout's minimum width is a hard floor under the window in Qt; putting
    a bar inside one of these takes the floor away without squashing the bar.
    """
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    area.setStyleSheet(f"QScrollArea {{ background: {T.INK_0}; }}")
    return area


def _rows_scroller(widget) -> QScrollArea:
    """Rows that scroll up and down when there are more than the screen holds.

    The other way round from `_scroller`: a window whose rows come from the
    song or the disk has no height of its own, and a layout's minimum height
    is a floor Qt will put below the bottom of the screen, buttons and all.
    """
    area = QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area


def _fit_screen(dlg, width: int, height: int) -> None:
    """Size a window as asked, but no bigger than the screen it opens on."""
    # not shown yet, the dialog only knows its parent's screen
    scr = (dlg.parentWidget() or dlg).screen() or QApplication.primaryScreen()
    if scr is None:
        dlg.resize(width, height)
        return
    room = scr.availableGeometry()
    # leave the window manager its title bar and a little air
    dlg.resize(min(width, room.width() - 40), min(height, room.height() - 80))


RATE_MIN, RATE_MAX, RATE_DETENT = 0.25, 2.0, 0.05

VOL_NOTCH = 5.0


class VolumeStrip(QWidget):
    """The word "volume", the slider and the readout, as one wheel target.

    Together rather than the slider alone because a wheel is aimed no better
    than a click is, and the slider is a hundred pixels inside a bar that runs
    the width of the window. The player hit-tests its own volume bar with
    eight pixels of slack around it for the same reason.

    Neither half of that relies on Qt walking an ignored wheel up the parent
    chain, because it does not do that for widgets the way it does for a key:
    a wheel stops on whatever it lands on. So the labels are made transparent
    to the mouse -- they are decoration and have no use for one -- and the
    slider, which still has to be dragged, hands it over by name.
    """

    def __init__(self, slider: QSlider, parts: list, parent=None) -> None:
        super().__init__(parent)
        self.slider = slider
        self._owed = 0.0
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)
        for w in parts[:1] + [slider] + parts[1:]:
            if w is not slider:
                w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(w)

    def wheelEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        if not self.slider.isEnabled():
            return
        self._owed += VOL_NOTCH * ev.angleDelta().y() / 120.0
        step = int(self._owed)
        self._owed -= step
        if step:
            self.slider.setValue(self.slider.value() + step)
        ev.accept()


class VolumeSlider(QSlider):
    """The volume slider, with the wheel handed to the strip around it.

    By name rather than by ignoring it: an ignored wheel does not walk up to
    the parent, so leaving it to Qt would mean the gesture did nothing over
    the one part of the strip everybody aims at. Qt's own handling is not
    wanted either -- it is wheelScrollLines x singleStep, three units a notch
    here and fifteen on the speed slider beside it -- so there is one place
    that decides what a notch is worth, and this is not it.
    """

    def wheelEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        strip = self.parent()
        if isinstance(strip, VolumeStrip):
            strip.wheelEvent(ev)
        else:
            super().wheelEvent(ev)


TAP_LABELS = {"all": "Lines and ad-libs", "lead": "Lines only",
              "bg": "Ad-libs only"}


def _shrinkable(label: QLabel, most: int) -> None:
    """Let a label give up its width when the window is narrow.

    A QLabel's minimum size hint is the width of its text, and every such
    hint adds up into a floor under the window -- which is how a tool whose
    largest control is a lyric ended up refusing to be less than 1450px wide.
    These are all captions; clipping one costs nothing.
    """
    label.setMinimumWidth(0)
    label.setMaximumWidth(most)
    label.setSizePolicy(QSizePolicy.Policy.Ignored,
                        QSizePolicy.Policy.Preferred)


class Caption(QLabel):
    """A one-line label that says what it can and is never a floor.

    For text that changes while the window is open -- the song's title, what
    the link is connected to. A plain QLabel's minimum is its whole text, so
    each new song or link state could push the window wider, and a window
    never shrinks by itself: it only ever grew. `_shrinkable` answers the
    same thing with an Ignored policy, which beside a stretch can squeeze a
    label down to nothing; this one still asks for its full width and is
    cut short with an ellipsis only when there is not that much to give.
    """

    def __init__(self, text: str = "", parent=None, floor: int = 0) -> None:
        super().__init__(parent)
        self._full, self._tip = "", ""
        self._floor = floor or T.px(24)
        self.setText(text)

    def text(self) -> str:                               # noqa: D102
        return self._full

    def setText(self, text) -> None:                     # noqa: N802 (Qt name)
        """Nothing at all for the same text: the offset is set thirty times a
        second, and a relayout of the window with every one is a stutter."""
        text = str(text or "")
        if text == self._full and QLabel.text(self):
            return
        self._full = text
        self._fit()
        self.updateGeometry()

    def _fit(self) -> None:
        fm = self.fontMetrics()
        room = self.contentsRect().width()
        shown = self._full
        if room > 0 and fm.horizontalAdvance(shown) > room:
            shown = fm.elidedText(shown, Qt.TextElideMode.ElideRight, room)
        QLabel.setText(self, shown)
        cut = shown != self._full
        QLabel.setToolTip(self, "\n\n".join(x for x in (
            self._full if cut else "", self._tip) if x))

    def sizeHint(self):                                  # noqa: N802 (Qt name)
        got = super().sizeHint()
        fm = self.fontMetrics()
        got.setWidth(got.width() + fm.horizontalAdvance(self._full)
                     - fm.horizontalAdvance(QLabel.text(self)))
        return got

    def minimumSizeHint(self):                           # noqa: N802 (Qt name)
        """Measured on the whole text, never on what is showing: that is
        shorter whenever the label is squeezed, and a floor that moves with
        the squeezing moves the window."""
        got = super().minimumSizeHint()
        whole = self.sizeHint().width()
        got.setWidth(min(whole, self._floor))
        return got

    def setToolTip(self, tip: str) -> None:              # noqa: N802 (Qt name)
        """The caller's own tip, shown whenever the text is not cut short."""
        self._tip = str(tip or "")
        self._fit()

    def resizeEvent(self, ev) -> None:                   # noqa: N802 (Qt name)
        super().resizeEvent(ev)
        self._fit()

    def changeEvent(self, ev) -> None:                   # noqa: N802 (Qt name)
        super().changeEvent(ev)
        if ev.type() in (ev.Type.FontChange, ev.Type.StyleChange):
            self._fit()


def _flog(event: str, **kw) -> None:
    """TEMPORARY: the editor's half of lyrics_gui.follow_log."""
    try:
        import lyrics_gui as L
        L.follow_log("editor", event, **kw)
    except Exception:                                   # noqa: BLE001
        pass


def _hrule() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color:#2c2f39;")
    return f


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("open", nargs="?", default="", help="a lyric file to open")
    ap.add_argument("--audio", default="", help="the song to time against")
    ap.add_argument("--source", default="spotify", choices=["spotify", "local"])
    ap.add_argument("--port", type=int, default=9222,
                    help="Spotify's debug port, as the player uses it")
    args = ap.parse_args(argv)
    import lyrics_gui as L
    L.install_excepthook()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Mild Lyrics TTML Editor")
    win = Editor(args)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
