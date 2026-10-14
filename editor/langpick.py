"""A language box you can type into: "jap", "germ" or "de_AT" all find
theirs, anywhere in the name. Holds the code; shows the name."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QCompleter

from . import syllables as SY


def choices() -> list[tuple[str, str]]:
    """(code, label), the script languages first, then by name."""
    codes = SY.languages()
    head = [c for c in SY.SCRIPT_LANGS if c in codes]
    rest = sorted((c for c in codes if c not in head),
                  key=lambda c: SY.language_name(c).casefold())
    return [(c, f"{SY.language_name(c)}  ·  {c}") for c in head + rest]


class LangBox(QComboBox):
    picked = pyqtSignal(str)

    def __init__(self, code: str = SY.DEFAULT_LANG, parent=None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(16)
        for c, label in choices():
            self.addItem(label, c)
        done = QCompleter(self.model(), self)
        done.setFilterMode(Qt.MatchFlag.MatchContains)
        done.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        done.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(done)
        self.lineEdit().setPlaceholderText("type a language…")
        self.set_code(code)
        self._last = self.code()
        self.currentIndexChanged.connect(self._changed)
        self.lineEdit().editingFinished.connect(self._settle)

    def code(self) -> str:
        return str(self.currentData() or SY.DEFAULT_LANG)

    def set_code(self, code: str) -> None:
        i = self.findData(code)
        self.setCurrentIndex(i if i >= 0 else
                             max(0, self.findData(SY.DEFAULT_LANG)))

    def _changed(self, _i: int) -> None:
        if self.code() != self._last:
            self._last = self.code()
            self.picked.emit(self._last)

    def _settle(self) -> None:
        """Text that names no language goes back to the one picked."""
        txt = self.currentText().strip().casefold()
        hit = next((i for i in range(self.count())
                    if txt and txt in self.itemText(i).casefold()), -1)
        if hit >= 0 and self.itemText(self.currentIndex()).casefold() != txt:
            self.setCurrentIndex(hit)
        self.setEditText(self.itemText(self.currentIndex()))
