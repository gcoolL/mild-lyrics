"""Everything the editor remembers about how you like it, in one window: a tab
per kind, a row per setting. Measurements stay beside their numbers."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QGridLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
)

from . import keys as K, theme as T
from . import player as _player  # noqa: F401  (puts mild-lyrics on the path)
import out_delay as OD  # noqa: E402


ROMAN = [
    ("Show under the words", "roman_show", "bool", None, True,
     "Only for lines in a non-Latin script."),
    ("Detail", "roman_detail", "choice", ["per syllable", "per line"],
     "per syllable",
     "Per line is how amll-ttml-db stores it."),
    ("Particles", "roman_particles", "choice", ["as said", "as written"],
     "as said",
     "は, へ, を as wa, e, o (said) or ha, he, wo (written)."),
    ("Waveform shows the reading only", "roman_wave", "bool", None, False,
     ""),
    ("Fill in as you type", "roman_auto", "bool", None, True,
     "Your own readings are never replaced."),
]
ROMAN_DEFAULTS = {key: default for _l, key, _k, _s, default, _n in ROMAN}


def roman(key: str):
    """One romanisation setting, as it is now."""
    return K.config().get(key, ROMAN_DEFAULTS[key])


def discord_rows() -> list[tuple]:
    """discord_rpc's rows -- imported here, not at the top, as that module
    needs the player's folder on the path, which the editor puts there."""
    from . import discord_rpc
    return list(discord_rpc.SETTINGS)


def sections(classic: bool = True) -> list[tuple[str, list[tuple]]]:
    """The settings, in tabs; a function because some choices depend on the
    machine. `classic` is which interface is asking."""
    import interface as IFACE
    head = [("Interface", "interface", "choice", list(IFACE.CHOICES),
             IFACE.get(), "Shared with Mild Lyrics.")
            ] if classic else []
    accent_note = ""
    return [
        ("Look", head + [
            ("Text size", "scale", "num", (0.7, 2.2, 0.05, 2, "×"), 1.0,
             "Ctrl+= and Ctrl+−"),
            (("Accent", "accent", "choice", list(T.ACCENTS), "blue",
              accent_note) if classic else
             ("Accent", "accent_new", "choice", list(T.NEW_ACCENTS), "white",
              accent_note)),
            ("Waveform height", "wave_height", "num",
             (110.0, 320.0, 10.0, 0, " px"), 210.0, ""),
            ("Every voice on the waveform", "lanes_all", "bool", None, True,
             "Off shows at most three lanes."),
            ("Untimed words on the waveform", "wave_loose", "bool", None,
             True,
             "Drag one to place the whole line."),
        ]),
        ("Spectrogram", [
            ("Show the spectrogram", "spec_on", "bool", None, False,
             "The full mix. No demucs needed."),
            ("Start with the vocal view on", "vocal_on", "bool", None, False,
             "Isolates the vocal when a song opens. Needs demucs."),
            ("Brightness", "voc_bright", "num", (0.0, 100.0, 5.0, 0, "%"),
             50.0, ""),
            ("Contrast", "voc_contrast", "num", (0.0, 100.0, 5.0, 0, "%"),
             50.0, ""),
            ("Lowest pitch", "voc_low_hz", "num",
             (40.0, 6000.0, 10.0, 0, " Hz"), 40.0,
             "Raise to hide bass."),
            ("Highest pitch", "voc_high_hz", "num",
             (150.0, 20000.0, 50.0, 0, " Hz"), 20000.0,
             "Lower to hide hiss."),
            ("Levels", "voc_levels", "choice", ["Each band", "Whole song"],
             "Each band",
             "Each band shows quiet highs better."),
            ("Colours", "voc_colours", "choice",
             ["Accent", "Heat", "Ice", "Grey"], "Accent", ""),
            ("Onset line", "voc_trace", "num", (0.0, 100.0, 5.0, 0, "%"),
             42.0,
             "Height of the line marking where sounds start. 0 hides it."),
        ]),
        ("Timing", [
            ("Drag timings on the waveform", "wave_drag", "bool", None, True,
             "Right-drag or Ctrl-drag a shared edge to move one side only. "
             "Shift turns off snapping."),
            ("Show beats", "beat_on", "bool", None, True, ""),
            ("Snap to beats", "beat_snap", "choice",
             ["Off", "Beats", "Half beats"], "Half beats",
             "Hold Shift to place freely."),
            ("Tap lag", "tap_lag_ms", "num",
             (-500.0, 500.0, 10.0, 0, " ms"), 0.0,
             "Your reaction time. Tapped times are moved earlier by this "
             "much."),
            ("Output delay", "out_delay", "choice", list(OD.MODES), "auto",
             f"Audio latency of local files. Auto: {OD.said()}."),
            ("Replay lead-in", "drag_preroll", "num",
             (0.0, 10.0, 0.5, 1, " s before"), 1.5,
             "How long before a line a replay starts."),
            ("Ad-libs get their own pass", "tap_adlibs", "bool", None, True,
             "Lines with a backing vocal are played twice."),
            ("Repeated lines from one tap", "repeat_fill", "bool", None, True,
             "Tapping the first word of a repeated line times the whole "
             "line like the earlier one."),
            ("Commit starts a line", "commit_starts_line", "bool", None,
             False,
             "On an untimed first word, Commit only starts it."),
        ]),
        ("Drag sync", [
            ("Slice width", "bar_cell", "num", (32.0, 160.0, 2.0, 0, " px"),
             52.0, ""),
            ("Width by word length", "bar_stretch", "num",
             (0.0, 2.0, 0.1, 1, "× the word"), 0.0,
             "0 = every slice the same width."),
        ]),
        ("Romanisation", list(ROMAN)),
        ("Audio", [
            ("Speed", "rate", "num", (0.25, 2.0, 0.05, 2, "×"), 1.0,
             "Local audio only."),
            ("Remember the speed", "rate_keep", "bool", None, False, ""),
            ("Remember the volume", "volume_keep", "bool", None, True,
             "Local files only."),
        ]),
        ("Saving", [
            ("TTML on one line", "save_compact", "bool", None, False, ""),
            ("Brackets around ad-libs", "save_parens", "bool", None, False,
             "Like Apple's files: “(oh yeah)”."),
            ("Save romanisation", "save_roman", "bool", None, True, ""),
        ]),
        ("Display", [
            ("GPU drawing", "gpu", "choice", ["auto", "on", "off"], "auto",
             "Auto uses the GPU on Wayland."),
        ]),
        ("Discord", discord_rows()),
        ("Voice chat", [
            ("Voice volume", "voice_volume", "num", (0.0, 2.0, 0.1, 1, "×"), 1.0,
             ""),
            ("Microphone sensitivity", "voice_sense", "choice", ["low", "normal", "high"],
             "normal",
             "Low for noisy rooms, high for quiet voices."),
            ("Remove background noise", "voice_denoise", "bool", None, True,
             ""),
        ]),
        ("Words", [
            ("Syllable rule", "split_method", "choice", ["sung", "hyphen"],
             "sung", "Sung matches the player. Hyphen is TeX hyphenation."),
            ("Other scripts", "split_unit", "choice",
             ["syllable", "mora", "word"],
             "syllable", "Japanese, Chinese, Korean, Cyrillic and Greek."),
            ("Language", "split_lang", "lang", None, "en", ""),
            ("Split words as I type them", "split_auto", "bool", None, False,
             ""),
            ("Split after hyphens", "split_hyphens", "bool", None, True,
             "brand-new → brand-|new"),
            ("Re-split after an edit", "split_resplit", "bool", None, True,
             ""),
            ("Split every word", "split_everywhere", "bool", None, False,
             "Not just the longer ones."),
            ("Type --- as an em dash", "em_dash", "bool", None, True, ""),
            ("Remember corrections", "split_learn", "bool", None, True,
             "Use your split corrections in future songs."),
            ("Shared dictionary", "split_shared", "bool", None, True,
             "Use the shared splits. Your corrections still win."),
        ]),
    ]


class SettingsDialogue(QDialog):
    """The settings, and nothing that needs a measurement to choose.

    Shaped like the Keys dialogue on purpose -- tabs, one scrolling grid each,
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
        self.find = QLineEdit()
        self.find.setPlaceholderText("Search the settings")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._filter)
        box.addWidget(self.find)
        self._words: list = []          # (tab, caption, control, text)
        self.tabs = tabs = QTabWidget()
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
                ctl = self._control(key, kind, spec, default,
                                    got.get(key, default))
                grid.addWidget(ctl, r, 1)
                said = [group, label, note or "",
                        *(map(str, spec) if kind == "choice" else ())]
                self._words.append((tabs.count(), cap, ctl,
                                    " ".join(said).casefold()))
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

    def _filter(self, query: str) -> None:
        """Show only the rows holding every word of `query`, and their tabs."""
        words = query.casefold().split()
        shown = set()
        for tab, cap, ctl, text in self._words:
            hit = all(w in text for w in words)
            cap.setVisible(hit)
            ctl.setVisible(hit)
            if hit:
                shown.add(tab)
        for i in range(self.tabs.count()):
            self.tabs.setTabVisible(i, i in shown or not shown)
        if shown and self.tabs.currentIndex() not in shown:
            self.tabs.setCurrentIndex(min(shown))

    def _control(self, key, kind, spec, default, value):
        if kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(value))
        elif kind == "lang":
            from .langpick import LangBox
            w = LangBox(str(value or default))
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
            elif kind == "lang":
                w.set_code(str(default))
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
            elif kind == "lang":
                out[key] = w.code()
            elif kind == "choice":
                out[key] = w.currentText()
            elif kind == "num":
                out[key] = round(float(w.value()), 4)
            else:
                out[key] = w.text().strip()
        return out


def ask(parent, section: str = "") -> dict | None:
    """Run the dialogue. Returns what changed, or None if it was cancelled.

    The interface is not the editor's to keep -- it is shared with the
    player, in a file of its own -- so it is handed back as a change and
    written by whoever acts on it, not stored in editor.json."""
    import interface as IFACE
    dlg = SettingsDialogue(parent)
    for i in range(dlg.tabs.count()):
        if dlg.tabs.tabText(i) == section:
            dlg.tabs.setCurrentIndex(i)
    before = dict(K.config())
    before["interface"] = IFACE.get()
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    got = dlg.values()
    iface = got.pop("interface", before["interface"])
    K.remember(**got)
    got["interface"] = iface
    return {k: v for k, v in got.items() if before.get(k) != v}
