"""Everything the editor remembers about how you like it, in one window.

WHY THIS EXISTS. The settings were all already here; they were just kept
wherever the thing they affect happens to be drawn. The type scale was two
buttons on the transport bar, the tap lag was a spin box beside them, the
syllable rule was inside the Automatic split dialog, and which of them were
remembered between runs was not something the window ever said. That is fine
for a control you reach for mid-take -- the speed and the volume stay on the
bar, because they are part of playing the song -- and wrong for the ones you
set once and forget, which is most of them.

So: a tab per kind, a row per setting, and the same vocabulary the player's
own menu uses -- "bool", "choice", "num", "text" -- because the two programs
are one program to whoever is using them, and a setting that reads one way in
the player and another way here is two things to learn.

WHAT IS NOT HERE. Anything that is a measurement rather than a preference.
The snap reach lives in What the vocal says, next to the numbers that tell
you what to set it to; which checkpoint to run lives in the Model dialog,
next to what each one scored. Moving those in here would put a number in
front of somebody with nothing to judge it by.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QGridLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
)

from . import keys as K, syllables as SY, theme as T


def sections() -> list[tuple[str, list[tuple]]]:
    """The settings, in tabs. A function because two of the choice lists are
    only known once the machine has been looked at -- which hyphenation
    dictionaries are installed, and what the accents are called."""
    langs = SY.languages() or ["en"]
    return [
        ("Look", [
            ("Text size", "scale", "num", (0.7, 2.2, 0.05, 2, "×"), 1.0,
             "Everything in the window, together. Ctrl+= and Ctrl+− do this "
             "from the keyboard."),
            ("Accent", "accent", "choice", list(T.ACCENTS), "blue",
             "The bright colour: the lead voice, the playhead, the word the "
             "cursor is on."),
            ("Waveform height", "wave_height", "num",
             (110.0, 320.0, 10.0, 0, " px"), 210.0,
             "How much room the strip gets before it starts scrolling the "
             "words off the bottom."),
        ]),
        ("Timing", [
            ("Tap lag", "tap_lag_ms", "num",
             (-500.0, 500.0, 10.0, 0, " ms"), 0.0,
             "How late your taps land. Everything stamped with the timing "
             "keys is moved back by this much."),
            ("Replay from", "drag_preroll", "num",
             (0.0, 10.0, 0.5, 1, " s before"), 1.5,
             "How far ahead of a line drag sync drops you in."),
            ("Ad-libs get their own pass", "tap_adlibs", "bool", None, True,
             "A line with a backing vocal is played twice: once for the "
             "words, once for the ad-lib."),
        ]),
        ("Drag sync", [
            ("Slice width", "bar_cell", "num", (32.0, 160.0, 2.0, 0, " px"),
             52.0,
             "How wide one syllable's target is on the bar. Wider is easier "
             "to hit and wraps a long line onto more rows."),
            ("Width by word length", "bar_stretch", "num",
             (0.0, 2.0, 0.1, 1, "× the word"), 0.0,
             "At 0 every slice is the same width, whatever its word says, so "
             "the hand's step is the same all the way along. Turned up, a "
             "longer word gets a wider slice and the bar takes the shape of "
             "the line above it -- at 1 the slice grows by the width the "
             "word is actually drawn at."),
        ]),
        ("Audio", [
            ("Speed", "rate", "num", (0.25, 2.0, 0.05, 2, "×"), 1.0,
             "What the speed slider opens at. Local audio only."),
            ("Remember the speed", "rate_keep", "bool", None, False,
             "Put the slider back where you left it next time, instead of "
             "at full speed."),
            ("Remember the volume", "volume_keep", "bool", None, True,
             "For a local file. Spotify's volume is the system's and is "
             "never written down here."),
        ]),
        ("Words", [
            ("Syllable rule", "split_method", "choice", ["sung", "hyphen"],
             "sung", "`sung` is this project's own rule and the one the "
             "player spells words with; `hyphen` is TeX hyphenation, which "
             "knows more words and answers a different question."),
            ("Language", "split_lang", "choice", langs, "en",
             "Which hyphenation dictionary, for the `hyphen` rule."),
            ("Re-split after an edit", "split_resplit", "bool", None, True,
             "Cut a word again when its text changes."),
            ("Split every word", "split_everywhere", "bool", None, False,
             "Rather than only the ones long enough to be worth it."),
        ]),
    ]


class SettingsDialog(QDialog):
    """The settings, and nothing that needs a measurement to choose.

    Shaped like the Keys dialog on purpose -- tabs, one scrolling grid each,
    a way back to the defaults, Ok and Cancel -- because it is the same kind
    of window and there is no reason for a person to learn two.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.rows: dict = {}
        self.spec: dict = {}
        got = K.config()
        box = QVBoxLayout(self)
        tabs = QTabWidget()
        for group, rows in sections():
            page = QWidget()
            grid = QGridLayout(page)
            grid.setColumnStretch(0, 1)
            for r, (label, key, kind, spec, default, note) in enumerate(rows):
                self.spec[key] = (kind, spec, default)
                cap = QLabel(f"{label}<br><span style='color:{T.FAINT}'>"
                             f"{note}</span>" if note else label)
                cap.setWordWrap(True)
                grid.addWidget(cap, r, 0)
                grid.addWidget(self._control(key, kind, spec, default,
                                             got.get(key, default)), r, 1)
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
        btn.button(QDialogButtonBox.StandardButton.Ok).setProperty(
            "primary", "1")
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        box.addWidget(btn)
        self.resize(T.px(560), T.px(460))

    def _control(self, key, kind, spec, default, value):
        if kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
        elif kind == "choice":
            w = QComboBox()
            w.addItems([str(x) for x in spec])
            w.setCurrentText(str(value))
            if w.currentIndex() < 0:
                w.setCurrentText(str(default))
        elif kind == "num":
            low, high, step, places, suffix = spec
            w = QDoubleSpinBox()
            w.setRange(float(low), float(high))
            w.setSingleStep(float(step))
            w.setDecimals(int(places))
            w.setSuffix(str(suffix))
            w.setValue(float(value))
            w.setKeyboardTracking(False)
        else:
            w = QLineEdit(str(value or ""))
        self.rows[key] = w
        return w

    def _defaults(self) -> None:
        for key, (kind, _spec, default) in self.spec.items():
            w = self.rows[key]
            if kind == "bool":
                w.setChecked(bool(default))
            elif kind == "choice":
                w.setCurrentText(str(default))
            elif kind == "num":
                w.setValue(float(default))
            else:
                w.setText(str(default or ""))

    def values(self) -> dict:
        """What the window says, in the types the config file keeps."""
        out = {}
        for key, (kind, _spec, _default) in self.spec.items():
            w = self.rows[key]
            if kind == "bool":
                out[key] = bool(w.isChecked())
            elif kind == "choice":
                out[key] = w.currentText()
            elif kind == "num":
                out[key] = round(float(w.value()), 4)
            else:
                out[key] = w.text().strip()
        return out


def ask(parent) -> dict | None:
    """Run the dialog. Returns what changed, or None if it was cancelled."""
    dlg = SettingsDialog(parent)
    before = dict(K.config())
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    got = dlg.values()
    K.remember(**got)
    return {k: v for k, v in got.items() if before.get(k) != v}
