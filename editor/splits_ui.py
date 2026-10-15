"""The shared splitting dictionary's page, and the question asked when a word
has more than one right way. See docs/notes/editor/shared_splits.md."""
from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton,
    QVBoxLayout, QWidget,
)

from . import keys as K
from . import shared_splits as SH
from . import theme as T
from . import syllables as SY


# ------------------------------------------------------------ the question
def ask_ways(parent, words: list[str], lang: str) -> bool:
    """Ask which way to use for each word here with several, once per word
    per song. False if the person backed out."""
    seen: set = set()
    for word in words:
        k = SY.key(word)
        if not k or k in seen:
            continue
        seen.add(k)
        if SY.chosen(word):
            continue
        ways = SY.ways_known(word, lang)
        if len(ways) < 2:
            continue
        pick = ask_one(parent, SY.SL.peel(word)[1] or word, ways)
        if pick is None:
            return False
        SY.choose(k, pick)
    return True


def ask_one(parent, word: str, ways: list[list[str]]) -> list[str] | None:
    """One word's ways as choices; the picked one, or None."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Which split?")
    box = QVBoxLayout(dlg)
    say = QLabel(f"“{word}” can be split more than one way. "
                 "Which one does this song use?")
    say.setWordWrap(True)
    box.addWidget(say)
    group = QButtonGroup(dlg)
    for n, way in enumerate(ways):
        b = QRadioButton("|".join(way))
        b.setChecked(n == 0)
        group.addButton(b, n)
        box.addWidget(b)
    btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                           | QDialogButtonBox.StandardButton.Cancel)
    btn.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", "1")
    btn.accepted.connect(dlg.accept)
    btn.rejected.connect(dlg.reject)
    box.addWidget(btn)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return list(ways[max(0, group.checkedId())])


# ---------------------------------------------------------------- the page
class _Relay(QObject):
    """Hands a background request's answer back to the GUI thread."""
    done = pyqtSignal(object, object)


class SplitsPage(QWidget):
    """Browse the shared list for a language, add to it, and lock entries
    with the owner's secret."""

    def __init__(self, current_lang=None, parent=None) -> None:
        super().__init__(parent)
        self.current_lang = current_lang
        self._relay = _Relay(self)
        self._relay.done.connect(self._deliver)
        self._busy = False
        box = QVBoxLayout(self)
        box.setContentsMargins(T.px(28), T.px(16), T.px(28), T.px(16))

        top = QHBoxLayout()
        self.lang = QComboBox()
        for code in self._langs():
            self.lang.addItem(f"{SY.language_name(code)} ({code})", code)
        self.lang.currentIndexChanged.connect(lambda _i: self.refresh())
        top.addWidget(self.lang, 1)
        self.again = QPushButton("Refresh")
        self.again.clicked.connect(lambda: self.refresh(ask=True))
        top.addWidget(self.again)
        box.addLayout(top)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the shared list")
        self.search.textChanged.connect(lambda _t: self._fill())
        box.addWidget(self.search)
        self.mine = QPushButton("Show my own corrections")
        self.mine.setCheckable(True)
        self.mine.toggled.connect(self._mine_toggled)
        box.addWidget(self.mine)
        self.rows = QListWidget()
        # Shift+click picks a run, Ctrl+click adds or drops one: Lock, Unlock
        # and Remove then act on every picked word, and Share on every row.
        self.rows.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.rows.currentItemChanged.connect(self._picked)
        self.rows.itemClicked.connect(self._picked)
        self.rows.itemSelectionChanged.connect(self._say_picked)
        box.addWidget(self.rows, 1)

        self.ways = QLineEdit()
        self.ways.setPlaceholderText(
            "pro|cess   (several ways: pro|cess / proc|ess; never split: process)")
        self.ways.returnPressed.connect(self._share)
        box.addWidget(self.ways)
        acts = QHBoxLayout()
        self.share = QPushButton("Share")
        self.share.setProperty("primary", "1")
        self.share.clicked.connect(self._share)
        self.remove = QPushButton("Remove")
        self.remove.clicked.connect(self._remove)
        acts.addWidget(self.share)
        acts.addWidget(self.remove)
        acts.addStretch(1)
        box.addLayout(acts)

        own = QHBoxLayout()
        self.secret = QLineEdit(str(K.config().get("splits_owner") or ""))
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText("owner secret (only to lock entries)")
        self.secret.editingFinished.connect(
            lambda: K.remember(splits_owner=self.secret.text().strip()))
        own.addWidget(self.secret, 1)
        self.lock_btn = QPushButton("Lock")
        self.lock_btn.clicked.connect(lambda: self._lock(True))
        self.unlock_btn = QPushButton("Unlock")
        self.unlock_btn.clicked.connect(lambda: self._lock(False))
        own.addWidget(self.lock_btn)
        own.addWidget(self.unlock_btn)
        box.addLayout(own)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self._pick_lang()

    # ------------------------------------------------------------- plumbing
    @staticmethod
    def _langs() -> list[str]:
        out = []
        for code in SY.languages():
            base = SH.lang_of(code)
            if base and base not in out:
                out.append(base)
        return out

    def _pick_lang(self) -> None:
        want = SH.lang_of(self.current_lang() if self.current_lang else SY.DEFAULT_LANG)
        i = self.lang.findData(want)
        if i >= 0 and i != self.lang.currentIndex():
            self.lang.setCurrentIndex(i)
        else:
            self.refresh()

    def code(self) -> str:
        return str(self.lang.currentData() or "")

    def showEvent(self, ev) -> None:                       # noqa: N802 (Qt name)
        super().showEvent(ev)
        self._pick_lang()

    def _deliver(self, fn, got) -> None:
        fn(got)

    def _bg(self, work, then) -> None:
        """Run `work` off the GUI thread and `then(answer)` back on it."""
        if self._busy:
            return
        self._busy = True
        self._enable()

        def run():
            try:
                got = work()
            except Exception as e:                          # noqa: BLE001
                got = str(e)
            self._relay.done.emit(self._finish(then), got)

        threading.Thread(target=run, name="shared-splits-ui", daemon=True).start()

    def _finish(self, then):
        def go(got):
            self._busy = False
            then(got)
            self._fill()
            self._enable()
        return go

    def _enable(self) -> None:
        owner = bool(self.secret.text().strip())
        for b in (self.share, self.remove, self.again):
            b.setEnabled(not self._busy)
        for b in (self.lock_btn, self.unlock_btn):
            b.setEnabled(owner and not self._busy)

    # --------------------------------------------------------------- the list
    def refresh(self, ask: bool = False) -> None:
        lang = self.code()
        if not K.config().get("split_shared", True):
            self.status.setText("The shared dictionary is off (Settings ▸ Splitting).")
        self._fill()
        if ask:
            self.status.setText("Asking…")
            self._bg(lambda: SH.fetch(lang),
                     lambda err: self.status.setText(
                         f"Could not ask: {err}" if err else "Up to date."))

    def _entries(self) -> list[tuple[str, list[list[str]], bool]]:
        if self.mine.isChecked():
            got = SY.overrides()
            alts = SY.also_right()
            return sorted((k, [v] + alts.get(k, []), False) for k, v in got.items())
        words = SH.words(self.code())
        return sorted((k, list(v.get("ways") or []), bool(v.get("locked")))
                      for k, v in words.items())

    def _mine_toggled(self, on: bool) -> None:
        self.mine.setText("Show the shared list" if on else "Show my own corrections")
        self.search.setPlaceholderText("Search my own corrections" if on
                                       else "Search the shared list")
        self._fill()

    def _fill(self) -> None:
        """Refill the list. Quietly: the box being typed in is left alone,
        and the word that was picked stays picked if it is still there."""
        q = self.search.text().strip().lower()
        was = self.rows.currentItem()
        was = was.data(Qt.ItemDataRole.UserRole)[0] if was is not None else None
        picked = {w for w, _ways, _l in self._picked_rows()}
        self.rows.blockSignals(True)
        self.rows.clear()
        shown = 0
        for word, ways, locked in self._entries():
            if q and q not in word:
                continue
            text = f"{word}    {' / '.join('|'.join(w) for w in ways) or '(left whole)'}"
            it = QListWidgetItem(("🔒 " if locked else "") + text)
            it.setData(Qt.ItemDataRole.UserRole, (word, ways, locked))
            self.rows.addItem(it)
            if word == was:
                self.rows.setCurrentItem(it)
            it.setSelected(word in picked)
            shown += 1
            if shown >= 2000:
                break
        self.rows.blockSignals(False)
        self._enable()

    def _picked(self, it, _was=None) -> None:
        if it is None:
            return
        word, ways, _locked = it.data(Qt.ItemDataRole.UserRole)
        self.ways.setText(" / ".join("|".join(w) for w in ways) or word)

    def _picked_rows(self) -> list:
        """(word, ways, locked) of every picked row, in list order."""
        items = sorted(self.rows.selectedItems(), key=self.rows.row)
        return [it.data(Qt.ItemDataRole.UserRole) for it in items]

    def _say_picked(self) -> None:
        n = len(self.rows.selectedItems())
        if n > 1:
            self.status.setText(f"{n} picked — Share, Remove, Lock and Unlock "
                                "act on all of them")

    def _each(self, verb: str, doing: str, n: int, many, same_word: str) -> None:
        """Run `many(lang)` -> (done, same, {word: why}) off the GUI thread,
        one request a batch, then say how it went."""
        lang = self.code()

        def said(got):
            if isinstance(got, str):
                self.status.setText(f"Not {verb.lower()}: {got}")
                return
            done, same, bad = got
            bits = [f"{verb} {len(done)} word{'s' if len(done) != 1 else ''}."]
            if same:
                bits.append(f"{len(same)} {same_word}.")
            if bad:
                rows = [f"{w} ({why})" for w, why in bad.items()]
                bits.append("Not: " + ", ".join(rows[:6]) + (" …" if len(rows) > 6 else ""))
            self.status.setText(" ".join(bits))

        self.status.setText(f"{doing} {n} words…")
        self._bg(lambda: many(lang), said)

    def _one(self, verb: str, word: str, err: str) -> None:
        if err == SH.UNCHANGED:
            self.status.setText(f"No change: {word} already is that way.")
        elif err == SH.ALREADY:
            self.status.setText(f"No change: {word} already is {verb.lower()}.")
        elif err:
            self.status.setText(f"Not {verb.lower()}: {err}")
        else:
            self.status.setText(f"{verb} {word}.")

    # ---------------------------------------------------------------- acting
    def _word(self) -> str:
        """The word the box is about: its first way with the seams taken out."""
        first = self.ways.text().split(SY.WAYS)[0]
        return "".join(ch for ch in first if ch not in SY.SEAMS).strip().lower()

    def _typed(self) -> tuple[str, list[list[str]], str]:
        word = self._word()
        if not word:
            return "", [], "type a word, cut with | (pro|cess)"
        ways, bad = SY.parse_ways(word, self.ways.text())
        if bad:
            return word, [], f"“{bad}” is not another way of {word}"
        return word, [[b.lower() for b in w] for w in ways], ""

    def _share(self) -> None:
        rows = self._picked_rows()
        if len(rows) > 1:
            plan = {w: ways for w, ways, _l in rows if ways}
            self._each("Shared", "Sharing", len(plan),
                       lambda lang: SH.submit_many(lang, plan), "already were")
            return
        word, ways, bad = self._typed()
        if bad or not ways:
            self.status.setText(bad or "type how it is split")
            return
        lang = self.code()
        self.status.setText(f"Sharing {word}…")
        self._bg(lambda: SH.submit(lang, word, ways),
                 lambda err: self._one("Shared", word, err))

    def _remove(self) -> None:
        rows = self._picked_rows()
        if len(rows) > 1:
            plan = {w: [] for w, _ways, _l in rows}
            self._each("Removed", "Removing", len(plan),
                       lambda lang: SH.submit_many(lang, plan), "were not there")
            return
        word = self._word()
        if not word:
            self.status.setText("type a word")
            return
        lang = self.code()
        self._bg(lambda: SH.submit(lang, word, []),
                 lambda err: self.status.setText(f"No change: {word} is not in the list.")
                 if err == SH.UNCHANGED else self._one("Removed", word, err))

    def _lock(self, on: bool) -> None:
        word = self._word()
        secret = self.secret.text().strip()
        rows = self._picked_rows()
        K.remember(splits_owner=secret)
        verb = "Locked" if on else "Unlocked"
        if len(rows) > 1:
            words = [w for w, _ways, _l in rows]
            self._each(verb, "Locking" if on else "Unlocking", len(words),
                       lambda lang: SH.lock_many(lang, words, on, secret),
                       f"already were {verb.lower()}")
            return
        if not word:
            self.status.setText("pick a word")
            return
        lang = self.code()
        self._bg(lambda: SH.lock(lang, word, on, secret),
                 lambda err: self._one(verb, word, err))


def dialogue(parent, current_lang) -> None:
    """The page as a window, for the classic interface."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Shared splits")
    box = QVBoxLayout(dlg)
    box.addWidget(SplitsPage(current_lang, dlg))
    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.rejected.connect(dlg.reject)
    box.addWidget(close)
    dlg.resize(560, 620)
    dlg.exec()
