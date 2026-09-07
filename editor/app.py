"""The synchroniser's window: the lyric line per line, and the audio under it.

The shape is AMLL's, because AMLL's is right: a ribbon across the top for what
you can do, and under it the whole lyric as a list of lines you can point at,
one under the other. A word is a chip; a chip carries its own time; the same
click that selects a word to rewrite selects it to time.

    ribbon      Edit | Timing | Preview, and the buttons for the mode
    transport   play, clock, speed, and what the player is doing
    waveform    a strip that folds away when it is not wanted
    the lyric   line per line, chips per syllable, times down the right

There are three modes and they only decide what is SHOWN. The timing keys work
while writing words and the word menu works while timing -- a mode that took
things away would just be the two small tabs again with bigger buttons.

Everything that changes the document goes through `do()`, so undo is one stack
of snapshots and the live push to Mild Lyrics happens in exactly one place.
"""
from __future__ import annotations

import pathlib
import sys
import time
import traceback

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QScrollArea, QSizePolicy,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSlider, QStackedWidget,
    QVBoxLayout, QWidget,
)

# The most the player is ever left behind what is being typed here. It is a
# rate limit, not a delay -- see schedule_push, which is where the difference
# turned out to matter.
PUSH_MS = 180

_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path[:0] = [str(p) for p in (_ROOT / "aligner", _ROOT)
                if str(p) not in sys.path]

from . import (autotime, backups, keys as K, model as M, ops, sources,  # noqa: E402
               vocalmap, waveform)
from .lineview import LineList                                        # noqa: E402
from .link import Link                                                # noqa: E402
from .player import LocalPlayer, Player, SpotifyPlayer                # noqa: E402
from .ribbon import Ribbon                                            # noqa: E402
from .start import StartPage, read_lyric                              # noqa: E402

AUDIO = "Audio (*.wav *.flac *.mp3 *.m4a *.ogg *.opus *.aac *.webm);;All files (*)"
from . import theme as T


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

    Only these get a question. Everything else on that dialog comes back by
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
        self.setWindowTitle("Mild Lyrics — TTML synchroniser")
        self.resize(1340, 880)
        self.args = args
        self.doc = M.Doc()
        self.path: pathlib.Path | None = None
        self.dirty = False
        self._undo: list = []
        self._redo: list = []
        self.engine: autotime.Engine | None = None
        self._thread = None
        self._worker = None
        self._chore = None
        self._chore_worker = None
        self.song_id: int | None = None
        self.meta_extra: dict = {}
        self._said_untimed = False

        self.link = Link(self)
        self.link.connected.connect(self._linked)
        self.link.state.connect(self._player_state)
        self._repush_at = 0.0
        self._following = False
        self.link.refused.connect(
            lambda why: self.say(f"the player did not take that — {why}"))
        self.player: Player = Player(self)

        self._build()
        self.set_source(args.source)

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._frame)
        self.ui_timer.start(33)
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
        app = QApplication.instance()
        if app is not None:
            app.setFont(T.font(13, 500))
        self.setStyleSheet(T.sheet())
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.start = StartPage(self)
        self.start.loaded.connect(self.take_doc)
        self.stack.addWidget(self.start)
        self.keys = K.Keys(self, self._key_handlers(), self.key_possible)
        self.stack.addWidget(self._editor_page())
        self.stack.setCurrentIndex(0)
        self.set_mode("edit")
        self._file_actions()

    def _editor_page(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        self.ribbon = Ribbon(self._ribbon_spec())
        self.ribbon.mode_changed.connect(self.set_mode)
        self.ribbon.setMinimumWidth(self.ribbon.sizeHint().width())
        self.ribbon_scroll = _scroller(self.ribbon)
        for name in ("Save", "Time selection"):
            b = self.ribbon.button(name)
            if b is not None:
                b.setProperty("primary", "1")
        box.addWidget(self.ribbon_scroll)
        box.addWidget(_hrule())
        strip_holder = QWidget()
        strip_holder.setLayout(self._transport())
        self.transport_scroll = _scroller(strip_holder)
        self.transport_scroll.setFixedHeight(
            strip_holder.sizeHint().height() + 4)
        box.addWidget(self.transport_scroll)

        strip = QHBoxLayout()
        strip.setContentsMargins(T.EDGE // 2, 4, T.EDGE // 2, T.GAP)
        strip.setSpacing(T.GROUP)
        self.wave_box = QWidget()
        wl = QVBoxLayout(self.wave_box)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(2)
        head = QHBoxLayout()
        cap = QLabel("Waveform")
        cap.setProperty("caption", "1")
        cap.setFont(T.font(10, 600, caps=True))
        head.addWidget(cap)
        head.addStretch(1)
        self.fold_btn = QPushButton("fold ▲")
        self.fold_btn.setProperty("ghost", "1")
        self.fold_btn.clicked.connect(self.toggle_fold)
        head.addWidget(self.fold_btn)
        wl.addLayout(head)
        self.wave = waveform.Wave()
        self.wave.setMinimumHeight(120)
        self.wave.setMaximumHeight(210)
        self.wave.seeked.connect(self.seek)
        self.wave.follow_changed.connect(
            lambda on: self.follow_box.setChecked(on))
        self.wave.moved.connect(self._dragged)
        self.wave.picked.connect(lambda i, v, k: self.list.set_cursor(i, v, k))
        wl.addWidget(self.wave, 1)
        strip.addWidget(self.wave_box, 1)

        self.sync_pad = K.SyncPad(self.keys)
        self.sync_pad.fired.connect(self.fire)
        self.sync_pad.setFixedWidth(300)
        strip.addWidget(self.sync_pad)
        box.addLayout(strip)

        self.list = LineList()
        self.list.tap_mode = self._tap_mode()
        self.list.will_edit.connect(self.push_undo)
        self.list.edited.connect(self._list_edited)
        self.list.cursor_changed.connect(self._cursor_moved)
        self.list.word_changed.connect(self.remember_word)
        self.list.selection_changed.connect(self._selection_changed)
        self.list.seek_to.connect(self.seek)
        box.addWidget(self.list, 1)

        self.status = QLabel("")
        self.status.setProperty("hint", "1")
        _shrinkable(self.status, 16777215)
        self.status.setContentsMargins(T.EDGE // 2, 5, T.EDGE // 2, 6)
        self.status.setStyleSheet(f"background:{T.INK_2}; color:{T.MUTE};")
        box.addWidget(self.status)

        if K.config().get("wave_folded"):
            self.toggle_fold()
        return page

    def _ribbon_spec(self) -> list:
        ALL = ["edit", "timing", "preview"]
        return [
            ("File", ALL, [
                ("Import…", self.show_import, "Fetch or paste words — replacing "
                 "this lyric or adding to the end of it."),
                ("Save", self.save, "Write the TTML.  (Ctrl+S)"),
                ("Song info…", self.info_dialog, "Title, artist, language and "
                 "the songwriters that go in the file's header."),
                ("Edit as text…", self.text_dialog, "The whole lyric as plain "
                 "text. Lines you do not change keep their timing."),
                ("Fetch audio…", self.fetch_audio, "Go and find a copy of "
                 "this song to time against — searched by name AND length, "
                 "then checked by listening to it for the words in this "
                 "lyric. Kept afterwards, so it is downloaded once."),
                ("Keys…", self.keys_dialog, "Rebind anything."),
                ("Recover…", self.recover_dialog, "Copies the editor keeps by "
                 "itself: unsaved work, whatever a fetch replaced, and every "
                 "file that was written over."),
                ("Storage…", self.cache_dialog, "What this app has left on the "
                 "disk, how much of it there is, and how to be rid of it."),
            ]),
            ("Lines", ["edit", "timing"], [
                ("Split", self.b_split_line, "Break the line before the "
                 "selected word."),
                ("Merge", self.b_merge_lines, "Run the selected lines together."),
                ("Duplicate", self.b_duplicate, "Copy them, times and all."),
                ("Delete", self.b_delete, "Remove them."),
                ("Insert", self.b_insert, "A new empty line below."),
                ("↑", lambda: self.b_move(-1), "Move up."),
                ("↓", lambda: self.b_move(1), "Move down."),
            ]),
            ("Words", ["edit"], [
                ("Syllabify", self.b_syllabify, "Cut every word of the "
                 "selected lines into syllables, with whatever the automatic "
                 "split is set to."),
                ("Auto split…", self.split_dialog, "Cut the whole song — or "
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
            ("Timing", ["timing"], [
                ("Start", lambda: self.fire("sync_start"), "This word starts "
                 "at the playhead."),
                ("Commit", lambda: self.fire("sync_next"), "End it, start the "
                 "next one here, and step on — the tapping key."),
                ("End", lambda: self.fire("sync_end"), "This word ends at the "
                 "playhead."),
                ("Spread", self.b_spread, "Share the line's span out over its "
                 "syllables by length."),
                ("−0.05s", lambda: self.b_shift(-0.05), "Nudge the selected "
                 "lines back."),
                ("+0.05s", lambda: self.b_shift(0.05), "Nudge them on."),
                ("Clear", self.b_clear, "Forget their times."),
                ("Tidy ends", self.b_snap, "Stop every line before the next "
                 "one starts."),
            ]),
            ("The vocal", ["timing"], [
                ("Vocal view", self.b_vocal_view, "Separate the vocal with "
                 "demucs and draw its spectrogram behind the words, with a "
                 "tick everywhere the singing starts or stops. The first "
                 "time costs a separation; after that it is read back."),
                ("Marks", self.b_vocal_marks, "Show or hide the ticks on "
                 "their own."),
                ("Close gaps", self.b_fill_gaps, "Hold each word open until "
                 "the next one starts, but only across the small holes — "
                 "anything longer than the gap in Snap… is a rest and is "
                 "left alone. No audio needed."),
                ("What it says…", self.vocal_report, "How far this song's "
                 "marks can be trusted, which of them are too ambiguous to "
                 "read, and which words sit nowhere near anything the singer "
                 "did. Changes nothing — it is a reading list."),
            ]),
            *([("The sync model", ["timing"], [
                ("Time selection", lambda: self.b_auto(False), "Let the model "
                 "place the selected lines, inside the gap the lines around "
                 "them leave."),
                ("Time whole song", lambda: self.b_auto(True), "One alignment "
                 "over everything — the right choice when nothing is timed "
                 "yet, and the only one that gets repeated choruses right."),
                ("Model…", self.model_dialog, "Which trained checkpoint to "
                 "run, and whether to separate the vocal first. Follows the "
                 "player's own setting unless told otherwise."),
            ])] if autotime.available()[0] else []),
            ("Preview", ["preview"], [
                ("From the top", lambda: self.seek(0.0), "Play from the start."),
                ("From this line", self.play_from_line, "Play from the "
                 "selected line."),
            ]),
        ]

    def _transport(self):
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 5, 8, 5)
        bar.setSpacing(7)
        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setProperty("primary", "1")
        self.play_btn.setMinimumHeight(34)
        self.play_btn.setMinimumWidth(104)
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(self.toggle)
        bar.addWidget(self.play_btn)
        self.clock_lbl = QLabel("0:00.000")
        self.clock_lbl.setFont(T.font(15, 500, mono=True))
        self.clock_lbl.setMinimumWidth(108)
        self.clock_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_lbl.setStyleSheet(
            f"background:{T.INK_1}; border:1px solid {T.LINE};"
            f" border-radius:{T.R_BUTTON}px; padding:6px 8px; color:{T.TEXT};")
        bar.addWidget(self.clock_lbl)
        bar.addSpacing(6)
        speed = QLabel("speed")
        speed.setProperty("hint", "1")
        bar.addWidget(speed)
        self.rate_box = QComboBox()
        self.rate_box.addItems(["0.5×", "0.75×", "1×", "1.25×", "1.5×"])
        self.rate_box.setCurrentText("1×")
        self.rate_box.currentTextChanged.connect(
            lambda t: self.player.set_rate(float(t.rstrip("×"))))
        self.rate_box.setToolTip("Local audio only — Spotify plays at one speed "
                                 "and so does everything timed against it.")
        bar.addWidget(self.rate_box)
        bar.addSpacing(6)
        vol = QLabel("volume")
        vol.setProperty("hint", "1")
        bar.addWidget(vol)
        # Timing is done at the volume the singing can be HEARD at, which is
        # louder than anybody wants a song for four minutes at a stretch --
        # and a local file arrived at whatever the system was set to, with
        # nothing in this window to turn it down but leaving it. Both ends
        # have a volume, so both get this one control: Qt's output for a
        # file, and Spotify's own for Spotify.
        self._vol_quiet = False
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setFixedWidth(T.px(104))
        self.vol_slider.setValue(int(round(
            float(K.config().get("volume", 0.9)) * 100)))
        self.vol_slider.setToolTip(
            "How loud the song is played, on the scale ears use rather than "
            "the amplitude one. A local file is turned down here and "
            "nowhere else; with Spotify this is Spotify's own volume, so "
            "moving it there moves this.\n\nIt changes nothing that is "
            "written — the times are the times however loud it was.")
        self.vol_slider.valueChanged.connect(self._volume)
        bar.addWidget(self.vol_slider)
        self.vol_lbl = QLabel(f"{self.vol_slider.value()}%")
        self.vol_lbl.setProperty("hint", "1")
        self.vol_lbl.setMinimumWidth(T.px(34))
        bar.addWidget(self.vol_lbl)
        for label, fn in (("−5s", lambda: self.player.nudge(-5)),
                          ("−1s", lambda: self.player.nudge(-1)),
                          ("+1s", lambda: self.player.nudge(1)),
                          ("+5s", lambda: self.player.nudge(5))):
            b = QPushButton(label)
            b.setProperty("ghost", "1")
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addSpacing(6)
        lag = QLabel("tap lag")
        lag.setProperty("hint", "1")
        bar.addWidget(lag)
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
        bar.addWidget(self.lag_box)
        bar.addSpacing(6)
        for label, delta, tip in (("A−", -0.1, "Smaller text.  (Ctrl+−)"),
                                  ("A+", 0.1, "Bigger text.  (Ctrl+=)")):
            b = QPushButton(label)
            b.setProperty("ghost", "1")
            b.setToolTip(tip)
            b.clicked.connect(lambda _c=False, d=delta: self.bump_scale(d))
            bar.addWidget(b)
        tapping = QLabel("tapping")
        tapping.setProperty("hint", "1")
        bar.addWidget(tapping)
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
        bar.addWidget(self.tap_box)
        self.follow_box = QCheckBox("follow")
        self.follow_box.setChecked(True)
        self.follow_box.setToolTip("Keep the strip — and, in preview, the "
                                   "lyric — on the playhead.")
        self.follow_box.toggled.connect(self._follow)
        bar.addWidget(self.follow_box)
        bar.addStretch(1)
        self.tap_lbl = QLabel("")
        self.tap_lbl.setProperty("hint", "1")
        _shrinkable(self.tap_lbl, 260)
        self.tap_lbl.setAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.tap_lbl)
        bar.addSpacing(14)
        self.track = QLabel("—")
        self.track.setProperty("hint", "1")
        _shrinkable(self.track, 320)
        bar.addWidget(self.track)
        bar.addSpacing(10)
        self.live = QCheckBox("Show in Mild Lyrics")
        self.live.setChecked(True)
        self.live.setToolTip(
            "Push every edit to the running player, so the file being timed "
            "is drawn over the song it is playing. Only the lines that have "
            "times are sent — and the player's own clock sweeps them, so "
            "with a local file it follows the player, not this window.")
        self.live.toggled.connect(self._live_toggled)
        bar.addWidget(self.live)
        self.link_dot = QLabel("● no player")
        self.link_dot.setProperty("hint", "1")
        bar.addWidget(self.link_dot)
        # The offset every tap is stamped against, in the open. It is a number
        # that decides where each syllable lands and it used to be invisible,
        # which is how a file came to carry a correction meant for the
        # player's setup rather than for the song.
        self.offset_lbl = QLabel("")
        self.offset_lbl.setProperty("hint", "1")
        self.offset_lbl.setToolTip(
            "The global offset the player is set to. Times are stamped in "
            "lyric time -- this is taken off before anything is written, so "
            "the file never carries it. Change it mid-song and the halves "
            "stop agreeing, which this will say.")
        bar.addWidget(self.offset_lbl)
        return bar

    def _file_actions(self) -> None:
        """The file shortcuts, with no menu bar to hang them off.

        A menu bar here would be exactly the thing the ribbon replaced: four
        words in nine-point type in the top-left corner, holding the same
        commands the ribbon already shows at a size that can be read and hit.
        The keys still work, because a shortcut nobody can see is still worth
        having.
        """
        for keyseq, fn in (("Ctrl+=", lambda: self.bump_scale(0.1)),
                           ("Ctrl++", lambda: self.bump_scale(0.1)),
                           ("Ctrl+-", lambda: self.bump_scale(-0.1)),
                           ("Ctrl+0", lambda: (T.set_scale(1.0),
                                               self.apply_scale())),
                           ("Ctrl+N", self.new_doc),
                           ("Ctrl+O", lambda: self.open_lyric("")),
                           ("Ctrl+I", self.show_import),
                           ("Ctrl+S", self.save),
                           ("Ctrl+Shift+S", lambda: self.save(True)),
                           ("Ctrl+Shift+O", lambda: self.open_audio("")),
                           ("Ctrl+Z", self.undo),
                           ("Ctrl+Shift+Z", self.redo),
                           ("Ctrl+Y", self.redo)):
            act = QAction(self)
            act.setShortcut(QKeySequence(keyseq))
            act.triggered.connect(fn)
            self.addAction(act)

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
            "rate_reset": lambda: self.rate_box.setCurrentText("1×"),
            "nudge_back": lambda: self.b_nudge_syl(-0.02),
            "nudge_on": lambda: self.b_nudge_syl(0.02),
            "split_line": self.b_split_line,
            "merge_lines": self.b_merge_lines,
            "duplicate": self.b_duplicate,
            "flip_agent": self.b_flip_agent,
            "auto_section": lambda: self.b_auto(False),
        }

    # What cannot be done in the window as it stands, and why. The keys ask
    # before firing and the Keys dialog greys the row; the toolbar widgets for
    # the same things are disabled beside them, so the two never disagree.
    #
    # Only real impossibilities belong here -- things the machine or the
    # player cannot do at all. "Nothing is selected" is not one of them: those
    # actions answer for themselves, with a line saying what to select, which
    # is more use than a key that does nothing.
    def key_possible(self, name: str) -> tuple:
        if name in ("rate_up", "rate_down", "rate_reset"):
            # Spotify plays at one speed and there is no API to ask it for
            # another. The combo beside these keys has always been greyed
            # for it; the keys went round the back of it and changed the
            # speed of nothing.
            if getattr(getattr(self, "player", None), "kind", "") != "local":
                return False, "speed is for local audio — Spotify plays at 1×"
        if name == "auto_section":
            ok, why = autotime.available()
            if not ok:
                return False, f"no model timing here — {why}"
        return True, ""

    def bump_scale(self, delta: float) -> None:
        T.set_scale(T.SCALE + delta)
        self.apply_scale()

    def apply_scale(self) -> None:
        """Re-dress the whole window at the current zoom."""
        app = QApplication.instance()
        if app is not None:
            app.setFont(T.font(13, 500))
        self.setStyleSheet(T.sheet())
        self.list.restyle()
        self.wave.update()
        self.ribbon.apply()
        self.fit_bars()
        self.say(f"text at {T.SCALE * 100:.0f}%")

    def keys_dialog(self) -> None:
        K.KeyDialog(self.keys, self).exec()

    def fire(self, action: str) -> None:
        """One of the three timing actions, wherever it was asked for."""
        if action in ("prev_word", "next_word"):
            self.list.step(-1 if action == "prev_word" else 1)
            return
        # The line that is selected has the last word on where this lands.
        # See settle_cursor: the cursor and the selection can be in different
        # lines, and when they are it is the selection the user is looking at.
        line, voice, k = self.list.settle_cursor()
        g = self.doc.group(line, voice)
        if g is None or not 0 <= k < len(g.syls):
            self.say("nothing to time — click a word first")
            return
        self.stamp_offset()
        pos = max(0.0, self.player.position() - self.tap_lag())
        self.push_undo()
        s = g.syls[k]
        if action == "sync_start":
            ops.set_time(self.doc, line, voice, k, pos, max(pos, s.end or pos))
            said = f"{s.text} starts at {_fmt(pos)}"
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
            elif action == "sync_end":
                pass
        self.do(said, structural=False)

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
        i = self.rate_box.currentIndex() + delta
        if 0 <= i < self.rate_box.count():
            self.rate_box.setCurrentIndex(i)

    # ---------------------------------------------------------------- modes
    def fit_bars(self) -> None:
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
        self.list.set_mode(mode)
        self.fit_bars()
        self.sync_pad.setVisible(mode == "timing")
        if mode == "preview":
            self.list.follow = self.follow_box.isChecked()
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

    def _follow(self, on: bool) -> None:
        self.wave.follow = on
        self.list.follow = on

    def toggle_fold(self) -> None:
        folded = self.wave.isVisible()
        self.wave.setVisible(not folded)
        self.fold_btn.setText("unfold ▼" if folded else "fold ▲")
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
            self.rate_box.setEnabled(kind == "local")
            return
        if isinstance(old, (LocalPlayer, SpotifyPlayer)):
            try:
                if hasattr(old, "close"):
                    old.close()          # stop its polling thread first
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
        self.rate_box.setEnabled(kind == "local")
        if kind == "local":
            self.player.set_volume(float(K.config().get("volume", 0.9)))
        self.sync_volume()
        self.player.changed.connect(self._track_changed)
        self._track_changed()

    def _track_changed(self) -> None:
        name = " — ".join(x for x in (self.player.artist(), self.player.title()) if x)
        self.track.setText(name or "nothing playing")
        self.start.refresh_track()
        self.wave.length = self.player.duration()
        if self.player.kind == "spotify":
            got = self.player.audio_path()
            if got and got != getattr(self.wave, "_from", ""):
                self.load_envelope(got)

    def open_audio(self, path: str) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open audio", "", AUDIO)
        if not path:
            return
        if self.player.kind != "local":
            self.set_source("local")
        if not self.player.open(path):
            self.say(f"could not open {path}")
            return
        self.load_envelope(path)
        self._track_changed()

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

        def job(say):
            return sources.fetch_audio(meta["title"], meta["artist"],
                                       meta["length"], tid, words, say)

        def got(res, err):
            if err or not res:
                self.say(f"no copy could be fetched — "
                         f"{err or 'nothing came back'}")
                if then is not None:
                    then("")
                return
            path, warn = res
            self.open_audio(path)
            self.say(f"opened {pathlib.Path(path).name}"
                     + (f" — ⚠ {warn}" if warn else ""))
            if warn:
                QMessageBox.warning(self, "Check this recording", warn)
            if then is not None:
                then(path)

        self.say(f"looking for “{meta['title']}”…")
        if not self.run(job, got) and then is not None:
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
        self.wave._from = path
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

        self.run(job, got)

    # ---------------------------------------------------------------- files
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
        reason to make somebody open a dialog and press a button for them at
        the end of an hour's work. Nothing already in the file is touched:
        a name a writer typed, or one the source carried, is the answer.

        The worker takes one errand at a time and the fetch that brought this
        document in may still be winding down, so this waits its turn rather
        than being refused.
        """
        if not self.doc.lines or self.doc.meta.get("SongWriters"):
            return
        import lyrics_gui as L
        token = L.load_token()
        meta = {"title": str(self.doc.meta.get("Title") or self.player.title()),
                "artist": str(self.doc.meta.get("Artist") or self.player.artist()),
                "length": self.player.duration()}
        if not meta["title"]:
            return
        want = list(self.doc.lines)

        def job(_say):
            return sources.songwriters(meta, token, self.song_id)

        def got(res, err):
            if err or not res or not res[0]:
                return                       # quietly: nobody asked for this
            if self.doc.lines is not want or self.doc.meta.get("SongWriters"):
                return                       # a different song is open now
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
        self._stash_current("replaced")
        self.doc = M.Doc()
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
                "Lyrics (*.ttml *.xml *.lrc *.txt);;All files (*)")
        if not path:
            return
        doc, said = read_lyric(path)
        if doc is None:
            self.say(said)
            return
        self._stash_current("replaced")
        self.doc, self.path = doc, pathlib.Path(path)
        self.song_id = None
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        self.refresh()
        self.show_editor()
        self.say(said)

    def save(self, ask: bool = False) -> bool:
        """Write the TTML. Returns whether anything reached the disk.

        The answer matters to closeEvent, which used to close regardless:
        "Save before closing?" -> Save -> cancel the file picker -> the
        window shut anyway and the work went with it.
        """
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
            self.path.write_text(M.to_ttml(self.doc) + "\n", encoding="utf-8")
        except Exception as exc:                        # noqa: BLE001
            self.say(f"could not save — {exc}")
            return False
        self.dirty = False
        self.refresh()
        self.say(f"saved {self.path}")
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
                 round(self.doc.duration(), 2))
        if stamp == getattr(self, "_saved_stamp", None):
            return
        self._saved_stamp = stamp
        backups.stash(self.doc, self._song_name(), "working")

    def recover_dialog(self) -> None:
        """Everything the editor has kept, and a way back to any of it."""
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        got = backups.entries()
        dlg = QDialog(self)
        dlg.setWindowTitle("Recover")
        dlg.resize(820, 520)
        box = QVBoxLayout(dlg)
        head = QLabel(
            "Copies the editor kept by itself: unsaved work every half "
            "minute, whatever a fetch replaced, and every file written over. "
            f"The last {backups.KEEP} are held, in {backups.home()}.")
        head.setProperty("hint", "1")
        head.setWordWrap(True)
        box.addWidget(head)
        listing = QListWidget()
        listing.setFont(T.font(12, 500, mono=True))
        for e in got:
            when = time.strftime("%d %b %H:%M:%S", time.localtime(e["when"]))
            it = QListWidgetItem(
                f"{when}  {e['why']:<9} {e['lines']:>3} lines, "
                f"{e['timed']:>3} timed   {e['name'][:34]:<36} {e['first']}")
            it.setData(Qt.ItemDataRole.UserRole, str(e["path"]))
            listing.addItem(it)
        if got:
            listing.setCurrentRow(0)
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
        return str(_ROOT / "lyrics" / f"{safe}.ttml")

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
        self.do(said or None)

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
        if relayout:
            self.list.relayout(force=True)
        self.list.viewport().update()
        self.wave.shown = self.list.selected_rows()
        self.wave.cursor = self.list.cursor
        self._mark_claims()
        self.wave.update()
        who = " — ".join(x for x in (str(self.doc.meta.get("Artist") or ""),
                                     str(self.doc.meta.get("Title") or "")) if x)
        self.setWindowTitle(
            f"{'*' if self.dirty else ''}"
            f"{self.path.name if self.path else 'unsaved'}"
            + (f"   ({who})" if who else "")
            + "   —   Mild Lyrics TTML synchroniser")
        self.schedule_push()

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

    def _frame(self) -> None:
        pos = self.player.position()
        self.wave.set_pos(pos, self.player.playing())
        if self.list.mode == "preview" or self.player.playing():
            self.list.set_pos(pos)
        self.clock_lbl.setText(_fmt(pos))
        self.play_btn.setText("❚❚  Pause" if self.player.playing() else "▶  Play")
        i, v, k = self.list.cursor
        g = self.doc.group(i, v)
        if g and 0 <= k < len(g.syls):
            self.tap_lbl.setText(f"next: “{g.syls[k].text}”  "
                                 f"(line {i + 1}, syllable {k + 1}/{len(g.syls)})")
        else:
            self.tap_lbl.setText("")
        off = float(getattr(self.player, "offset", lambda: 0.0)())
        self.offset_lbl.setText(f"offset {off:+.2f}s" if abs(off) >= 0.005 else "")
        # Spotify's volume is the system's: a media key or the player's own
        # slider moves it while this window is open, so this one follows.
        if self.player.kind == "spotify" and not self.vol_slider.isSliderDown():
            self.sync_volume()

    def _linked(self, on: bool) -> None:
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
            # A player that has just come up is showing the song's own lyrics,
            # whatever this window was doing before it went away. flush() only
            # re-sends a push that FAILED, and the one before the restart
            # succeeded, so without this the screen stayed on the song's own
            # copy until the next keystroke happened to push again.
            self._push()

    def _volume(self, v: int) -> None:
        """The slider was moved -- unless it was this window that moved it."""
        self.vol_lbl.setText(f"{v}%")
        if self._vol_quiet:
            return
        self.player.set_volume(v / 100.0)
        # Remembered for a local file only. Spotify's volume is the system's
        # and belongs to whatever else is using it; writing it down here and
        # restoring it on the next run would be this editor reaching out and
        # changing something it does not own.
        if self.player.kind == "local":
            K.remember(volume=v / 100.0)

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

    def _follow_tick(self) -> None:
        """Keep the player's Spotify walking along with the local file.

        Mild Lyrics draws the document being pushed to it against SPOTIFY's
        clock -- it has no other -- so a file timed against a local copy of
        the song swept past wherever Spotify happened to be sitting, which is
        usually nought. The one screen meant to show the work in place was
        the one screen that could not.

        Only for a local file: timing against Spotify, the player IS the
        clock and there is nothing to tell it. And only while the document is
        being shown there at all, since this asks it to take hold of
        somebody's playback and that is not a thing to do unasked.

        The stop is sent as deliberately as the rest. The player hands the
        playback back on its own if this window goes silent, but that costs
        it a second or two of muted playing first, and switching to Spotify
        or unticking the box is not a crash.
        """
        want = self.live.isChecked() and self.player.kind == "local"
        if not want:
            if self._following:
                self._following = False
                self.link.unfollow()
            return
        self._following = True
        self.link.follow(self.player.position(), self.player.playing())

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
            # A different song is up. The push would be refused, and refused
            # once a second for as long as it stayed up.
            return
        now = time.monotonic()
        if now - self._repush_at < 1.0:
            return
        self._repush_at = now
        self._push()

    def _live_toggled(self, on: bool) -> None:
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
        # The name the player will credit the words to. It says the file
        # where there is one, because that is what the writer is looking at.
        self.link.push(M.to_ttml(shown), tid,
                       self.path.name if self.path else "unsaved")

    # ------------------------------------------------------------ selection
    def selected(self) -> list[int]:
        return self.list.selected()

    def _selection_changed(self) -> None:
        self.wave.shown = self.list.selected_rows()
        self.wave.update()

    def _cursor_moved(self, i: int, v: int, k: int) -> None:
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

    # ------------------------------------------------------------- dialogs
    def info_dialog(self) -> None:
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

    def text_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Edit as text")
        dlg.resize(720, 640)
        box = QVBoxLayout(dlg)
        hint = QLabel("Lines you do not change keep their timing.   "
                      "<b>&gt;</b> = the answering voice,   "
                      "<b>(brackets)</b> = backing vocals.")
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

        Lines that did not change keep their timings, because they are the
        same lines -- only the ones edited, added or moved come back untimed.
        Without this, fixing one word in a finished file would cost the whole
        sync.
        """
        want = M.from_text(text)
        from difflib import SequenceMatcher
        old = [ln.text() for ln in self.doc.lines]
        new = [ln.text() for ln in want.lines]
        if old == new:
            changed = 0
            for a, b in zip(self.doc.lines, want.lines):
                if a.agent != b.agent:
                    a.agent, changed = b.agent, changed + 1
            self.do(f"{changed} voice(s) moved" if changed else None)
            return
        self.push_undo()
        out, kept = [], 0
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new).get_opcodes():
            if tag == "equal":
                for n in range(i2 - i1):
                    keep = self.doc.lines[i1 + n]
                    keep.agent = want.lines[j1 + n].agent
                    out.append(keep)
                    kept += 1
            elif tag in ("replace", "insert"):
                out.extend(want.lines[j1:j2])
        self.doc.lines = out
        self.do(f"{len(out)} lines — {kept} kept their timing")

    def detect(self, alternate: bool = False) -> None:
        self.push_undo()
        self.do(sources.detect_roles(self.doc, alternate))

    def b_swap_agents(self) -> None:
        """The selection, or the whole song when nothing is picked."""
        sel = self.selected()
        self.push_undo()
        self.do(ops.swap_agents(self.doc, sel or None))

    def run(self, job, done) -> bool:
        """One errand at a time, on a thread that cleans itself up.

        Returns whether it started, the way `run_quiet` already does. A
        caller that greys a button out for the duration needs to know it was
        turned away, or the button never comes back.
        """
        if self._thread is not None and self._thread.isRunning():
            self.say("still busy with the last one")
            return False
        self._thread = QThread(self)
        self._worker = Work(job)
        self._worker.moveToThread(self._thread)
        self._worker.said.connect(self.say)
        self._thread.started.connect(self._worker.run)

        def finish(res, err):
            self._thread.quit()
            done(res, err)

        self._worker.done.connect(finish)
        self._thread.start()
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
        """Delete what is selected: the words if any are, else the rows."""
        self.push_undo()
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

    def split_settings(self) -> tuple[str, str, bool]:
        got = K.config()
        return (str(got.get("split_method") or "sung"),
                str(got.get("split_lang") or self._lang()),
                bool(got.get("split_resplit")))

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
                    resplit=None) -> None:
        want_m, want_l, want_r = self.split_settings()
        method = method or want_m
        lang = lang or want_l
        resplit = want_r if resplit is None else resplit
        picked = self._picked_words() if lines is None else []
        if picked:
            # just the words that are selected, grouped by the voice they are in
            self.push_undo()
            done = 0
            for (i, v), words in ops._by_group(self.doc, picked).items():
                if ops.syllabify(self.doc, i, v, words, method=method,
                                 lang=lang, resplit=resplit):
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
                                 resplit=resplit):
                    done += 1
        self.do(f"split {done} voice(s) across {len(sel)} line(s)"
                if done else None)

    def split_dialog(self) -> None:
        """Choose the rule, see what it would do, then do it."""
        from . import syllables as SY
        from PyQt6.QtWidgets import (QButtonGroup, QRadioButton, QTableWidget,
                                     QTableWidgetItem, QHeaderView)
        method, lang, resplit = self.split_settings()
        dlg = QDialog(self)
        dlg.setWindowTitle("Automatic split")
        dlg.resize(620, 560)
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

        shown = QLabel("")
        shown.setProperty("hint", "1")
        box.addWidget(shown)
        hint = QLabel("Type over a split to correct it — pieces separated by "
                      "<b>|</b>, Enter to keep. A correction is remembered "
                      "for that word and wins over the rule from then on; "
                      "leave one piece to say “never split this”.")
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
                if w.lower() not in seen:
                    seen.add(w.lower())
                    uniq.append(w)
            kept = SY.overrides()
            rows = []
            for w in uniq:
                pieces = SY.split(w, chosen(), langs.currentText())
                if len(pieces) > 1 or w.lower() in kept:
                    rows.append((w, pieces))
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
                cell = QTableWidgetItem("|".join(pieces))
                cell.setData(Qt.ItemDataRole.UserRole, w)
                preview.setItem(r, 1, cell)
                mark = QTableWidgetItem("kept" if w.lower() in kept else "")
                mark.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
                mark.setForeground(T.q(T.LEAD))
                preview.setItem(r, 2, mark)
            preview.blockSignals(False)
            cut = sum(1 for _w, p in rows if len(p) > 1)
            shown.setText(f"{cut} of {len(uniq)} words would be cut, across "
                          f"{len(scope())} line(s)"
                          + (f" — {len(kept)} correction(s) remembered"
                             if kept else ""))

        def corrected(item):
            if item.column() != 1:
                return
            word = str(item.data(Qt.ItemDataRole.UserRole) or "")
            pieces = [p for p in item.text().split("|")]
            if not word:
                return
            if "".join(pieces) != word or not all(pieces):
                note.setText(f"“{item.text()}” does not spell {word} — a split "
                             f"may be wrong, the lyric may not change")
                QTimer.singleShot(0, refresh)
                return
            SY.remember_split(word, pieces)
            note.setText(f"remembered: {word} → {'|'.join(pieces)}")
            QTimer.singleShot(0, refresh)

        preview.itemChanged.connect(corrected)

        for w in (whole, again):
            w.toggled.connect(refresh)
        langs.currentTextChanged.connect(refresh)
        group.buttonClicked.connect(refresh)
        refresh()

        under = QHBoxLayout()
        forget = QPushButton("Forget this correction")
        forget.setProperty("ghost", "1")
        forget.setToolTip("Put the selected word back under the rule.")

        def drop():
            items = preview.selectedItems()
            if not items:
                return
            word = str(preview.item(items[0].row(), 0).text())
            if SY.forget_split(word):
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
                   split_resplit=again.isChecked())
        self.b_syllabify(scope(), chosen(), langs.currentText(),
                         again.isChecked())

    def remember_word(self, line: int, voice: int, syl: int) -> None:
        """Keep how this word was split, so the next song spells it the same.

        A split made by hand is a decision about the word, not about this one
        line of this one song -- the automatic split learns it the same way a
        correction typed into its dialog does. A word taken back apart, or
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
        if len(pieces) > 1:
            if SY.remember_split(word, pieces):
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
        self.player.seek(t)
        self.wave.pos = t
        self.wave.update()

    def toggle(self) -> None:
        self.player.toggle()

    # ---------------------------------------------------------------- storage
    def cache_dialog(self) -> None:
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
        dlg.resize(720, 520)
        box = QVBoxLayout(dlg)
        head = QLabel("")
        head.setProperty("hint", "1")
        head.setWordWrap(True)
        box.addWidget(head)
        grid = QGridLayout()
        box.addLayout(grid)
        box.addStretch(1)

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
    def model_settings(self) -> dict:
        """What to run: the player's choice, unless this window overrides it."""
        got = autotime.player_choice()
        mine = K.config()
        if mine.get("ckpt"):
            got["ckpt"] = str(mine["ckpt"])
        if "stems" in mine:
            got["stems"] = bool(mine["stems"])
            if not mine.get("ckpt"):
                got["ckpt"] = autotime.checkpoint(got["stems"])
        return got

    def model_dialog(self) -> None:
        """Say which model is about to run, and let it be changed.

        This window and the player were picking their checkpoints
        independently and neither said which -- so a model trained in another
        session could be sitting on disk, in use by the player, and quietly
        not the one timing anything here.
        """
        ok, why = autotime.available()
        if not ok:
            self.say(f"no model to choose — {why}")
            return
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        dlg = QDialog(self)
        dlg.setWindowTitle("The sync model")
        dlg.resize(800, 480)
        box = QVBoxLayout(dlg)
        head = QLabel("")
        head.setProperty("hint", "1")
        head.setWordWrap(True)
        box.addWidget(head)
        listing = QListWidget()
        listing.setFont(QFont("monospace", 10))
        box.addWidget(listing, 1)
        cut = QCheckBox("cut words into syllables while timing")
        cut.setToolTip(
            "What the player does when it times a song by itself: a word you "
            "have not split is cut from the model's own character path, which "
            "is better than cutting it afterwards by letter count. Words you "
            "have already split are never re-cut.")
        cut.setChecked(bool(K.config().get("model_cut", True)))
        box.addWidget(cut)
        stems = QCheckBox("separate the vocal first")
        stems.setToolTip(
            "About nine seconds a song, and it decides which model is the "
            "right one: a network trained on separated vocals comes apart on "
            "a guitar. Following the player means following its setting too.")
        box.addWidget(stems)

        def fill(rescan: bool = False):
            now = self.model_settings()
            stems.setChecked(bool(now["stems"]))
            listing.clear()
            first = QListWidgetItem("follow the player  "
                                    f"({pathlib.Path(now['ckpt']).name or 'none'})")
            first.setData(Qt.ItemDataRole.UserRole, "")
            listing.addItem(first)
            chosen = str(K.config().get("ckpt") or "")
            for c in autotime.checkpoints(rescan):
                when = time.strftime("%d %b %H:%M", time.localtime(c["mtime"]))
                bits = [f"{c['name']:28}", f"step {str(c['step'] or '?'):>7}",
                        "stem " if c["stems"] else "mix  ",
                        "boundary" if c["boundary"] else "no bounds",
                        f"calib {c['calibration']}" if c["calibration"] else
                        "uncalibrated",
                        when]
                if c["draft"]:
                    bits.append("(mid-run copy)")
                it = QListWidgetItem("  ".join(bits))
                it.setData(Qt.ItemDataRole.UserRole, c["path"])
                listing.addItem(it)
                if c["path"] == chosen:
                    listing.setCurrentItem(it)
            if not chosen:
                listing.setCurrentRow(0)
            head.setText(
                f"The player is set to {'separate the vocal' if now['stems'] else 'the mixture'}"
                f", on {now['device']}, sparing {now['spare']:.1f} GB — so it "
                f"runs <b>{pathlib.Path(now['ckpt']).name or 'nothing'}</b>. "
                f"Pick a row to run something else here.")

        fill()
        row = QHBoxLayout()
        again = QPushButton("Rescan")
        again.setToolTip("Look again — a model that finished training while "
                         "this window was open is not otherwise noticed.")
        again.clicked.connect(lambda: fill(True))
        row.addWidget(again)
        row.addStretch(1)
        box.addLayout(row)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", "1")
        btn.accepted.connect(dlg.accept)
        btn.rejected.connect(dlg.reject)
        box.addWidget(btn)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        it = listing.currentItem()
        K.remember(ckpt=str(it.data(Qt.ItemDataRole.UserRole) or "") if it else "",
                   stems=stems.isChecked(), model_cut=cut.isChecked())
        self.engine = None
        now = self.model_settings()
        self.say(f"timing with {pathlib.Path(now['ckpt']).name or 'nothing'}")

    def b_auto(self, whole: bool) -> None:
        ok, why = autotime.available()
        if not ok:
            self.say(f"no model timing here — {why}. Time it by hand.")
            return
        sel = list(range(len(self.doc.lines))) if whole else (
            self.selected() or [self.list.cursor[0]])
        if not self.doc.lines:
            self.say("no words to time")
            return
        path = self.player.audio_path()
        meta = {"title": str(self.doc.meta.get("Title") or self.player.title()),
                "artist": str(self.doc.meta.get("Artist") or self.player.artist()),
                "length": self.player.duration()}
        tid = self.player.track_id()
        cfg = self.model_settings()
        stems, ckpt = bool(cfg["stems"]), str(cfg["ckpt"])
        device = "cpu" if self.args.device == "cpu" else (
            "cpu" if cfg["device"] == "cpu" else "auto")
        want_cut = bool(K.config().get("model_cut", True))
        if (self.engine is None or self.engine.stems != stems
                or self.engine.ckpt != ckpt or self.engine.cut != want_cut):
            self.engine = autotime.Engine(stems=stems, device=device,
                                          spare=float(cfg["spare"]), ckpt=ckpt,
                                          cut=bool(K.config().get("model_cut",
                                                                  True)))
        engine = self.engine
        doc = self.doc.clone()
        window = None if whole else autotime.bounds(
            doc, sel, self.player.duration() or self.wave.length)

        def job(say):
            audio = path
            if not audio:
                if self.player.kind != "spotify":
                    raise RuntimeError("open the audio file first")
                say("fetching a copy to listen to…")
                import local_align as LA
                words = [w for ln in doc.lines for g in ln.groups()
                        for w in g.text().split()]
                with LA.fetched(f"{meta['artist']} {meta['title']}",
                                float(meta.get("length") or 0),
                                artist=meta["artist"], tid=tid,
                                words=words, say=say) as got:
                    if not got:
                        raise RuntimeError(f"no copy could be fetched — "
                                           f"{LA.fetched.last_error}")
                    warn = None
                    if LA.fetched.swapped:
                        say(f"the copy last time was wrong "
                           f"({LA.fetched.swapped[1]})")
                    if LA.fetched.unverified:
                        url, why = LA.fetched.unverified
                        warn = f"using {LA._named(url)} unchecked — {why}"
                        say(f"⚠ {warn}")
                    engine.load(got, say)
                    return engine.time_lines(doc, sel, window, say) + (got, warn)
            engine.load(audio, say)
            return engine.time_lines(doc, sel, window, say) + (audio, None)

        def got(res, err):
            if err or not res:
                self.say(f"could not time it — {err or 'nothing came back'}")
                return
            placed, asked, audio, warn = res
            self.push_undo()
            kept = self._take_times(doc, sel)
            if kept:
                warn = ((warn + "; ") if warn else "") + (
                    f"{kept} line(s) were edited while the model ran and "
                    f"kept the words you gave them")
            if audio and audio != getattr(self.wave, "_from", ""):
                self.load_envelope(audio)
            span = "" if window is None else (f" between {_fmt(window[0])} and "
                                              f"{_fmt(window[1])}")
            self.do(f"placed {placed}/{asked} words across "
                    f"{len(sel)} line(s){span}"
                    + (f" — ⚠ {warn}, listen before trusting this" if warn else ""))

        self.say(f"timing with {pathlib.Path(ckpt).name or 'the sync model'}"
                 f"{' on a separated vocal' if stems else ''}…")
        self.run(job, got)

    # ------------------------------------------------------- the vocal view
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
        cfg = self.model_settings()
        device = "cpu" if self.args.device == "cpu" else str(cfg["device"])

        def job(say):
            return vocalmap.VocalMap.build(path, stems=True, device=device,
                                           spare=float(cfg["spare"]), say=say)

        def got(res, err):
            if err or res is None:
                self.say(f"no vocal view — {err or 'nothing came back'}")
                return
            # Before anything is drawn: is this audio even this song? The
            # view is only worth having if it can be believed, so a picture
            # that does not match the lyric is refused rather than shown
            # with a caveat nobody reads.
            fit = res.agrees(self._sung_spans())
            if not fit.get("trusted"):
                self.wave.vocal = None
                QMessageBox.warning(
                    self, "That is not this song",
                    f"The audio open here does not look like the recording "
                    f"this lyric was timed against, so drawing it behind the "
                    f"words would only mislead.\n\n{fit.get('why') or ''}\n\n"
                    f"Open the right audio and try again.")
                self.say(f"vocal view refused — {fit.get('why') or 'wrong song'}")
                return
            self.wave.vocal = res
            self.wave.show_vocal = self.wave.show_marks = True
            self.wave._pix = None
            self._mark_claims()
            self.wave.update()
            marks = res.marks()
            self.say(f"vocal view — {len(marks['starts'])} place(s) the "
                     f"singing starts, {len(marks['entrances'])} of them out "
                     f"of silence; the audio agrees with the lyric by "
                     f"{fit.get('separation')} points")

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
        # The UNBIASED keys: the strip draws the marks vocalmap gave it.
        self.wave.claimed = got["usable"]

    def _sung_spans(self) -> list:
        """Every stretch the document says somebody is singing in."""
        return [(s.start, s.end if s.end is not None else s.start + 0.1)
                for ln in self.doc.lines for g in ln.groups()
                for s in g.syls if s.timed]

    def _timing_scope(self):
        """The lines a timing command applies to: the selection, or all."""
        return self.selected() or list(range(len(self.doc.lines)))

    def b_fill_gaps(self) -> None:
        rows = self._timing_scope()
        self.push_undo()
        self.do(ops.fill_gaps(self.doc, rows,
                              float(K.config().get("snap_gap", ops.MAX_GAP))),
                structural=False)

    def vocal_report(self) -> None:
        """What the vocal does and does not say about this document.

        This used to offer to move words onto the marks, and it should not
        have. The marks are not consistent enough to edit with: on the file
        this was built against, the same word sung again gets a mark in some
        repeats and not others, and where it does the offset varies by up to
        130 ms -- see `ops.consistency`, which is measured here per song and
        put at the top of this window rather than buried in a docstring.

        So nothing in this dialog changes a timing. It answers three
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
                # the picker was cancelled, or the write failed -- either way
                # the work is still only in this window
                ev.ignore()
                return
        if self._following:
            # Give the playback back before the words: this window muted it.
            self.link.unfollow()
        if self.live.isChecked():
            # Hand the song back to the player, or it goes on showing a
            # document whose editor has closed. Flushed rather than pumped:
            # processEvents() here re-enters Qt while this window is being
            # taken apart, which aborts the process instead of ending it.
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


# Which voices the timing keys walk through, and what each is called.
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
    ap.add_argument("--device", default="auto", choices=["auto", "cpu"])
    ap.add_argument("--spare", type=float, default=0.4,
                    help="GB of VRAM to leave for everything else")
    args = ap.parse_args(argv)
    # Before anything else. PyQt turns an unhandled exception inside a slot
    # into qFatal(), which aborts the process outright -- so one undefined
    # name in paintEvent takes the whole editor down, with a lyric in it and
    # no message. The player has had this guard for the same reason; the
    # editor holds unsaved work, so it needs it more.
    import lyrics_gui as L
    L.install_excepthook()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Mild Lyrics TTML synchroniser")
    win = Editor(args)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
