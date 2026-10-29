"""Everything the editor remembers about how you like it, in one window: a tab
per kind, a row per setting. Measurements stay beside their numbers."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QGridLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
)

from . import keys as K, theme as T


ROMAN = [
    ("Show under the words", "roman_show", "bool", None, True,
     "A second row under every line with how it is read. Only lines in a "
     "script that needs one."),
    ("Detail", "roman_detail", "choice", ["per syllable", "per line"],
     "per syllable",
     "Per syllable is swept along with the words in the player. Per line is "
     "one reading for the whole line, as amll-ttml-db keeps it."),
    ("Particles", "roman_particles", "choice", ["as said", "as written"],
     "as said",
     "は, へ and を read as wa, e and o, the way they are sung, or as ha, he "
     "and wo, the way they are spelt."),
    ("Waveform shows the reading only", "roman_wave", "bool", None, False,
     "Label the blocks on the waveform with the romanisation instead of the "
     "words. The list below keeps both."),
    ("Fill in as you type", "roman_auto", "bool", None, True,
     "A syllable with no reading gets one from the romaniser when its text "
     "changes. Readings you typed are never replaced."),
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
             IFACE.get(), "Shared with Mild Lyrics. The classic interface is "
             "the ribbon and dialogues; the new one takes on the player's look.")
            ] if classic else []
    accent_note = ("The bright colour: the lead voice, the playhead, the word "
                   "the cursor is on." if classic else
                   "The bright colour: the playhead, the word being sung and "
                   "the word the cursor is on. White is the player's own ink; "
                   "the classic interface keeps an accent of its own.")
    return [
        ("Look", head + [
            ("Text size", "scale", "num", (0.7, 2.2, 0.05, 2, "×"), 1.0,
             "Everything in the window, together. Ctrl+= and Ctrl+− do this "
             "from the keyboard."),
            (("Accent", "accent", "choice", list(T.ACCENTS), "blue",
              accent_note) if classic else
             ("Accent", "accent_new", "choice", list(T.NEW_ACCENTS), "white",
              accent_note)),
            ("Waveform height", "wave_height", "num",
             (110.0, 320.0, 10.0, 0, " px"), 210.0,
             "How much room the strip gets before it starts scrolling the "
             "words off the bottom."),
            ("Every voice on the waveform", "lanes_all", "bool", None, True,
             "A lane for every voice the song needs, however many overlap. "
             "Off, the strip keeps to three and says how many are hidden. "
             "The button above the strip switches it too."),
            ("Unsynced words on the waveform", "wave_loose", "bool", None,
             True,
             "The words of the line being timed that have no time yet, laid "
             "out above the lanes where the line starts. Dragging one drags "
             "the whole line into place, at the song's pace. Off, the strip "
             "shows only what has a time; the list still shows everything."),
        ]),
        ("Spectrogram", [
            ("Show the spectrogram", "spec_on", "bool", None, False,
             "The song's own spectrogram behind the words, unseparated, kept "
             "on from song to song. Needs no torch or demucs. Vocal view "
             "takes its place while that is on. Vocal ▸ Spectrogram "
             "switches it too."),
            ("Start with the vocal view on", "vocal_on", "bool", None, False,
             "Separates the vocal as soon as a song is opened and shows its "
             "spectrogram. Half a minute on a GPU the first time, instant "
             "after that. Needs demucs."),
            ("Brightness", "voc_bright", "num", (0.0, 100.0, 5.0, 0, "%"),
             50.0,
             "How much of the picture is lit, the spectrogram's or the "
             "vocal view's. Lower hides the quiet parts; higher brings up "
             "breaths and the tails of words."),
            ("Contrast", "voc_contrast", "num", (0.0, 100.0, 5.0, 0, "%"),
             50.0,
             "Higher leaves only the strongest parts of the voice bright."),
            ("Lowest pitch", "voc_low_hz", "num",
             (40.0, 6000.0, 10.0, 0, " Hz"), 40.0,
             "Raise it to cut the hum and bass bleed under the voice."),
            ("Highest pitch", "voc_high_hz", "num",
             (150.0, 20000.0, 50.0, 0, " Hz"), 20000.0,
             "Lower it to drop the hiss; keep it high to see the consonants, "
             "which reach past 10 kHz on loud parts. The attack trace is "
             "read from this range too, up to 7600 Hz."),
            ("Levels", "voc_levels", "choice", ["Each band", "Whole song"],
             "Each band",
             "Each band runs dark to bright on its own, so quiet high "
             "tones and consonants show beside the loud low ones. Whole "
             "song frames every band the same, the way the bass sets it."),
            ("Colours", "voc_colours", "choice",
             ["Accent", "Heat", "Ice", "Grey"], "Accent",
             "The picture's colours, dark to bright."),
            ("Attack trace", "voc_trace", "num", (0.0, 100.0, 5.0, 0, "%"),
             42.0,
             "How tall the line of where sound arrives stands over the "
             "picture. 0 hides it."),
        ]),
        ("Timing", [
            ("Drag timings on the waveform", "wave_drag", "bool", None, True,
             "Grab a block's edges or body to retime it, or drag an unsynced "
             "word into place. An edge two words share moves both; drag it "
             "with the right button to move only the word on your side, or "
             "with Ctrl held to move only the word you drag it into. Times "
             "snap to the playhead when near it; hold Shift to place freely. "
             "Off, a click on a block only picks it, so a slip of the mouse "
             "cannot move a time."),
            ("Beats behind the words", "beat_on", "bool", None, True,
             "A line on the strip for every beat, found from the audio when "
             "a song opens, with fainter ones on the half beats while drags "
             "snap to them."),
            ("Snap to beats", "beat_snap", "choice",
             ["Off", "Beats", "Half beats"], "Half beats",
             "A dragged time within a few pixels of a beat lands on it, as it "
             "does on the playhead; hold Shift to place it freely. Words land "
             "on the beat about twice as often as chance, not always: about a "
             "quarter of hand-timed starts sit within 30 ms of a beat, and "
             "nearly half within 30 ms of a half beat."),
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
            ("Repeated lines from one tap", "repeat_fill", "bool", None, True,
             "Tapping the first word of a line that repeats one already "
             "timed earlier in the song — a chorus coming round again — "
             "times the whole line from the earlier one, moved to where "
             "this tap landed, and steps on past it. On a line of a grouped "
             "run (Lines → Group) the tap times the whole run. Timing → From "
             "a repeat does the same by hand, from whichever syllable has a "
             "time."),
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
        ("Romanisation", list(ROMAN)),
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
        ("Saving", [
            ("TTML on one line", "save_compact", "bool", None, False,
             "No line break after each line's tag. The words, the spaces "
             "between them and every time are the same; the file is just "
             "one line long."),
            ("Brackets around ad-libs", "save_parens", "bool", None, False,
             "Write an ad-lib's words as “(oh yeah)”, the way Apple's files "
             "do. It is still an ad-lib, and the player and this editor take "
             "the brackets back off when they read it. Also for a copy saved "
             "as LYS or ASS; the other formats always bracket them, having "
             "no other way to mark one."),
            ("Readings in the file", "save_roman", "bool", None, True,
             "Off, the romanisation is left out of the saved TTML: it stays "
             "on screen while the song is open here, and is gone when the "
             "file is opened again. The editor's own backups keep it."),
        ]),
        ("Display", [
            ("GPU drawing", "gpu", "choice", ["auto", "on", "off"], "auto",
             "Draw the waveform, the sync bar and the line list with "
             "OpenGL, so they keep up with a fast screen. `auto` does where "
             "it has been tested (Wayland), `on` tries it anywhere, and "
             "either goes back to the CPU by itself if it does not start. "
             "Switches at once; turning it on remakes the window."),
        ]),
        ("Discord", discord_rows()),
        ("Voice chat", [
            ("Voice volume", "voice_volume", "num", (0.0, 2.0, 0.1, 1, "×"), 1.0,
             "How loud the others are, in a multiplayer session's voice chat."),
            ("Microphone sensitivity", "voice_sense", "choice", ["low", "normal", "high"],
             "normal",
             "How soft a voice still counts as speaking. Nothing is sent while "
             "you are quiet; low suits a noisy room, high a quiet voice."),
            ("Remove background noise", "voice_denoise", "bool", None, True,
             "Takes steady noise (a fan, hiss, hum) out of what you send, and "
             "turns key clicks down. A single click never opens the microphone."),
        ]),
        ("Words", [
            ("Syllable rule", "split_method", "choice", ["sung", "hyphen"],
             "sung", "`sung` is this project's own rule and the one the "
             "player spells words with; `hyphen` is TeX hyphenation, which "
             "knows more words and answers a different question."),
            ("Other scripts", "split_unit", "choice",
             ["syllable", "mora", "word"],
             "syllable", "How Japanese, Chinese, Korean, Cyrillic and Greek "
             "are cut: a piece per syllable as sung in English (きょう, "
             "がっ|こう), per mora (Japanese a kana at a time), or per word."),
            ("Language", "split_lang", "lang", None, "en",
             "Japanese or Chinese says how kanji are read; the others are "
             "the hyphenation dictionary, for the `hyphen` rule. Type to "
             "search."),
            ("Split words as I type them", "split_auto", "bool", None, False,
             "A word typed or pasted into a line is cut into syllables "
             "straight away, by the rule below. Words already cut are left "
             "alone."),
            ("Split after hyphens", "split_hyphens", "bool", None, True,
             "A word typed, pasted or imported (a file, Genius, the player) "
             "is cut after each hyphen inside it, as soon as it comes in: "
             "brand-new becomes brand-|new. An imported word that already has "
             "a time is split too, its time shared out by letters as Split "
             "does; a timed word you edit later, and recovered backups, are "
             "left alone."),
            ("Re-split after an edit", "split_resplit", "bool", None, True,
             "Cut a word again when its text changes."),
            ("Split every word", "split_everywhere", "bool", None, False,
             "Rather than only the ones long enough to be worth it."),
            ("Type --- as an em dash", "em_dash", "bool", None, True,
             "Three hyphens in a row become — as you type, in a word, a "
             "line, the import page and Edit as text. Ctrl+Z takes it "
             "back."),
            ("Remember corrections", "split_learn", "bool", None, True,
             "A split corrected in the automatic split, or made by hand, is "
             "kept for that word in every song after this one. Off, it holds "
             "for this song only."),
            ("Shared dictionary", "split_shared", "bool", None, True,
             "Splits from the dictionary everyone can add to (the Splits tab) "
             "replace the rule for the words it has. Your own corrections "
             "still win. Off, nothing is fetched."),
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
