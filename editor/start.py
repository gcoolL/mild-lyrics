"""Where a session begins: getting the words in.

Importing is the one thing that happens once per song and then never again,
so it is not a tab competing for room with the work -- it is the screen the
window opens on, and it gets out of the way the moment there is a lyric to
edit. Asked for again later it comes back in a window of its own, where it
can also add to what is already there instead of replacing it.

Everything here hands back a Doc and a sentence about where it came from. The
fetching itself is `sources.py`; this is the part that asks.
"""
from __future__ import annotations

import pathlib

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
    QFrame, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from . import model as M, sources, theme as T

LYRIC = "Lyrics (*.ttml *.xml *.lrc *.txt);;All files (*)"


def _reason(err: str) -> str:
    """A worker's error, as a sentence to put on the status line.

    The worker labels everything it catches with its class, which is what you
    want for the ones nobody expected -- an AttributeError names a bug here.
    A RuntimeError from a fetch is not one of those: it was raised on purpose
    and its message IS the reason, so the label in front of it is noise where
    the line has to be read at a glance.
    """
    got = str(err or "").strip()
    return got[len("RuntimeError: "):] if got.startswith("RuntimeError: ") else got


class GeniusPick(QDialog):
    """Which Genius song this is, when the search is not sure."""

    def __init__(self, hits: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Which song?")
        self.resize(520, 320)
        box = QVBoxLayout(self)
        self.list = QListWidget()
        for h in hits:
            it = QListWidgetItem(h["title"] or h["artist"])
            it.setData(Qt.ItemDataRole.UserRole, h)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        box.addWidget(self.list)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        box.addWidget(btn)

    def chosen(self) -> dict | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None


class GeniusRomanFind(QDialog):
    """Which Genius romanisation to read: the automatic pick, one searched
    for here, or a genius.com link pasted in.

    The automatic pick is the first row and starts selected, so Enter on a
    dialog nobody touched does what the button always did. Enter in the box
    searches, or takes a link straight away. `choice()` answers
    ("auto", None), ("link", address) or ("hit", search hit).
    """

    def __init__(self, owner, query: str, token: str, parent=None) -> None:
        super().__init__(parent or owner)
        import genius_roman as GR
        self.GR, self.owner, self.token = GR, owner, token
        self.setWindowTitle("Romanisation from Genius")
        self.resize(620, 420)
        box = QVBoxLayout(self)
        row = QHBoxLayout()
        self.query = QLineEdit(query)
        self.query.setPlaceholderText("Search Genius, or paste a genius.com link")
        self.query.returnPressed.connect(self._enter)
        go = QPushButton("Search")
        go.setAutoDefault(False)
        go.clicked.connect(self._search)
        row.addWidget(self.query, 1)
        row.addWidget(go)
        box.addLayout(row)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        box.addWidget(self.list, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.button(QDialogButtonBox.StandardButton.Ok).setText("Use")
        btn.button(QDialogButtonBox.StandardButton.Ok).setAutoDefault(False)
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        box.addWidget(btn)
        self._fill([])

    def _fill(self, hits: list) -> None:
        self.list.clear()
        auto = QListWidgetItem("Best match, found automatically")
        auto.setData(Qt.ItemDataRole.UserRole, ("auto", None))
        self.list.addItem(auto)
        for h in hits:
            name = h.get("full_title") or h.get("title") or str(h.get("id"))
            tag = "   (romanised)" if self.GR.is_romanisation(h) else ""
            it = QListWidgetItem(name + tag)
            it.setData(Qt.ItemDataRole.UserRole, ("hit", h))
            self.list.addItem(it)
        self.list.setCurrentRow(1 if hits else 0)

    def _enter(self) -> None:
        if self.GR.is_link(self.query.text()):
            self.accept()
        else:
            self._search()

    def _search(self) -> None:
        q = self.query.text().strip()
        if not q or self.GR.is_link(q):
            return
        self.note.setText("searching Genius…")

        def job(_say):
            return [h for h in self.GR.search(self.token, q, "")
                    if self.GR.is_song(h)]

        def got(hits, err):
            if err:
                self.note.setText(f"could not ask Genius — {_reason(err)}")
                return
            self._fill(hits or [])
            self.note.setText(f"{len(hits or [])} result(s) — romanised "
                              f"pages first" if hits else "Genius found nothing")

        if not self.owner.run(job, got, lane="lyrics"):
            self.note.setText("still busy with the last lookup")

    def choice(self) -> tuple:
        if self.GR.is_link(self.query.text()):
            return ("link", self.query.text().strip())
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else ("auto", None)


def _clock(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class AudioPick(QDialog):
    """Which recording to time against, out of everything the search found.

    Each row gives the length next to the one being matched -- Spotify's,
    where the song is playing there -- because the length is what tells a
    radio edit, a live take or a video cut from the record.
    """

    def __init__(self, hits: list[dict], length: float = 0.0,
                 against: str = "Spotify", kept: str = "",
                 parent=None, gated: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Which recording?")
        self.resize(760, 420)
        box = QVBoxLayout(self)
        if length:
            head = QLabel(f"{against}: {_clock(length)}")
            head.setProperty("hint", "1")
            box.addWidget(head)
        if gated:
            left = QLabel(f"Left out: {gated} SoundCloud "
                          f"upload{'' if gated == 1 else 's'} that "
                          f"{'is' if gated == 1 else 'are'} Go+ only, which "
                          f"cannot be downloaded.")
            left.setProperty("hint", "1")
            box.addWidget(left)
        self.list = QListWidget()
        if kept:
            it = QListWidgetItem(f"the copy kept from last time — "
                                 f"{pathlib.Path(kept).name}")
            it.setData(Qt.ItemDataRole.UserRole, {"kept": kept})
            self.list.addItem(it)
        for h in hits:
            place = "YouTube" if h.get("where") == "ytsearch" else "SoundCloud"
            dur = float(h.get("dur") or 0)
            gap = (f"  ({dur - length:+.0f}s vs {against})"
                   if length and dur else "")
            who = h.get("uploader") or "?"
            tags = [t for t, on in (("streaming release", h.get("topic")),
                                    ("artist's own", h.get("mine")),
                                    ("other version", h.get("alt")),
                                    ("length off", not h.get("fits", True)))
                    if on]
            text = (f"{_clock(dur) if dur else '?:??'}{gap}   "
                    f"{h.get('title') or h.get('url')}  —  {who} · {place}"
                    + (f"   [{', '.join(tags)}]" if tags else ""))
            it = QListWidgetItem(text)
            it.setToolTip(h.get("url") or "")
            it.setData(Qt.ItemDataRole.UserRole, h)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        box.addWidget(self.list)
        btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        btn.accepted.connect(self.accept)
        btn.rejected.connect(self.reject)
        box.addWidget(btn)

    def chosen(self) -> dict | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None


class StartPage(QWidget):
    """The landing screen, and the import window -- the same widget both times."""

    loaded = pyqtSignal(object, str, bool, str)

    def __init__(self, owner, standalone: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.standalone = standalone
        self.song_id: int | None = None
        self._build()

    def relook(self) -> None:
        """Rebuild in the interface that is on, keeping what was typed."""
        keep = (self.f_title.text(), self.f_artist.text(),
                self.text.toPlainText())
        lay = self.layout()
        if lay is not None:
            while lay.count():
                it = lay.takeAt(0)
                if it.widget() is not None:
                    it.widget().setParent(None)
            QWidget().setLayout(lay)
        self._build()
        self.f_title.setText(keep[0])
        self.f_artist.setText(keep[1])
        self.text.setPlainText(keep[2])
        self.refresh_track()

    def _scrolled(self) -> QWidget:
        """The page's content, in a scroll area that fills the page.

        The page is one of the editor window's stack, and a stack is as big
        as its biggest page: this one's card -- 720px of it at the least,
        and the title, the tiles and the paste box one under another -- held
        the editor at 768x682 at the smallest. Scrolled, it holds nothing,
        and a small screen gets a scroll bar on this page instead of a
        window that runs off it.
        """
        shell = QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setStyleSheet("QScrollArea { background: transparent;"
                           " border: none; }")
        area.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setAutoFillBackground(False)
        area.setWidget(inner)
        shell.addWidget(area)
        return inner

    def _build(self) -> None:
        if T.LOOK == "new":
            self._build_new()
            return
        outer = QHBoxLayout(self._scrolled())
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        middle = QWidget()
        middle.setMaximumWidth(T.px(920))
        if not self.standalone:
            T.card(middle)
        outer.addWidget(middle, 6)
        outer.addStretch(1)
        box = QVBoxLayout(middle)
        box.setContentsMargins(24, 22, 24, 22)
        box.setSpacing(10)
        if not self.standalone:
            title = QLabel("Mild Lyrics TTML Editor")
            title.setFont(T.font(26, 600))
            title.setStyleSheet("background:transparent;")
            box.addWidget(title)
            sub = QLabel("Get the words in, then time them against the song.")
            sub.setProperty("hint", "1")
            box.addWidget(sub)
            box.addSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel("Timing against"))
        self.source_box = QComboBox()
        self.source_box.addItems(["Spotify", "Local file"])
        self.source_box.currentTextChanged.connect(
            lambda t: self.owner.set_source("spotify" if t == "Spotify" else "local"))
        row.addWidget(self.source_box)
        self.audio_btn = QPushButton("Open audio…")
        self.audio_btn.clicked.connect(lambda: self.owner.open_audio(""))
        row.addWidget(self.audio_btn)
        self.fetch_btn = QPushButton("Fetch audio")
        self.fetch_btn.setToolTip(
            "Go and find a copy of this song to time against. Searched by "
            "name and by length, then checked by listening to it — if the "
            "words are already in, a candidate that is not singing them is "
            "thrown out, which is the mistake a length check cannot catch. "
            "Kept afterwards, so it is downloaded once.")
        self.fetch_btn.clicked.connect(self.fetch_audio)
        row.addWidget(self.fetch_btn)
        self.track = QLabel("—")
        self.track.setProperty("hint", "1")
        row.addWidget(self.track, 1)
        box.addLayout(row)
        box.addWidget(self._note())

        grid = QGridLayout()
        self.f_title, self.f_artist = QLineEdit(), QLineEdit()
        grid.addWidget(QLabel("Title"), 0, 0)
        grid.addWidget(self.f_title, 0, 1)
        grid.addWidget(QLabel("Artist"), 0, 2)
        grid.addWidget(self.f_artist, 0, 3)
        take = QPushButton("From the player")
        take.setToolTip("Whatever is playing right now.")
        take.clicked.connect(self.from_player)
        grid.addWidget(take, 0, 4)
        box.addLayout(grid)

        row = QHBoxLayout()
        for label, fn, tip in (
                ("From Genius", self.fetch_genius,
                 "Genius' own text, with its section headers read for who "
                 "sings what and its brackets read as ad-libs."),
                ("From Mild Lyrics", self.fetch_chain,
                 "What the player is showing right now, if it is running — "
                 "the Spicy Lyrics community document, or whatever its own "
                 "chain or aligner produced. Falls back to asking the chain "
                 "itself (amll-ttml-db, LRCLIB, NetEase…) when the player "
                 "has nothing."),
                ("Open a file…", self.open_file,
                 "A TTML, LRC or plain text file from disk."),
        ):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setMinimumHeight(T.px(44))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            row.addWidget(b)
            if label == "From Mild Lyrics":
                pick = QPushButton("▾")
                pick.setToolTip("Ask one source by name instead.")
                pick.setMaximumWidth(T.px(34))
                pick.setMinimumHeight(T.px(44))
                pick.clicked.connect(self.source_menu)
                row.addWidget(pick)
        box.addLayout(row)

        hint = QLabel("…or paste the words below.   "
                      "<b>&gt;</b> at the start of a line = the answering "
                      "voice (duet).   <b>(brackets)</b> at the end = backing "
                      "vocals.")
        hint.setProperty("hint", "1")
        box.addWidget(hint)
        self.text = QPlainTextEdit()
        self.text.setFont(QFont("monospace", 11))
        self.text.setMinimumHeight(T.px(180))
        box.addWidget(self.text, 1)

        row = QHBoxLayout()
        self._multiplayer(row)
        row.addStretch(1)
        if self.standalone:
            add = QPushButton("Add to the end")
            add.setToolTip("Keep what is open and put these lines after it.")
            add.clicked.connect(lambda: self.take_text(append=True))
            row.addWidget(add)
            go = QPushButton("Replace the lyric")
        else:
            go = QPushButton("Start editing  →")
        go.setMinimumHeight(T.px(38))
        go.setProperty("primary", "1")
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setDefault(True)
        go.clicked.connect(lambda: self.take_text(append=False))
        row.addWidget(go)
        box.addLayout(row)

    def _build_new(self) -> None:
        """The start page in the new interface: two steps, the song and then
        its words, each saying what the choices on it do."""
        from . import glass as G
        outer = QHBoxLayout(self._scrolled())
        outer.setContentsMargins(T.px(24), T.px(24), T.px(24), T.px(24))
        outer.addStretch(1)
        card = G.glass()
        card.setMaximumWidth(T.px(980))
        card.setMinimumWidth(min(T.px(720), T.px(980)))
        outer.addWidget(card, 8)
        outer.addStretch(1)
        box = QVBoxLayout(card)
        box.setContentsMargins(T.px(36), T.px(30), T.px(36), T.px(28))
        box.setSpacing(T.px(12))

        def caps(text):
            lab = QLabel(text.upper())
            lab.setStyleSheet(f"font-size:{T.px(13)}px; font-weight:800;"
                              " letter-spacing:1px; color:rgba(234,234,234,150);"
                              f" padding-top:{T.px(8)}px;")
            return lab

        def note(text):
            lab = QLabel(text)
            lab.setWordWrap(True)
            lab.setStyleSheet(f"font-size:{T.px(13.5)}px; font-weight:500;"
                              " color:rgba(234,234,234,150);")
            return lab

        if not self.standalone:
            title = QLabel("Mild Lyrics TTML Editor")
            title.setStyleSheet(f"font-size:{T.px(30)}px; font-weight:800;")
            box.addWidget(title)
            box.addWidget(note("Get the words in, then time them against the "
                               "song. Both steps can be done in either order."))

        box.addWidget(caps("1 · The song"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(T.px(12))
        grid.setVerticalSpacing(T.px(6))
        self.f_title, self.f_artist = QLineEdit(), QLineEdit()
        self.f_title.setPlaceholderText("Title")
        self.f_artist.setPlaceholderText("Artist")
        grid.addWidget(self.f_title, 0, 0)
        grid.addWidget(self.f_artist, 0, 1)
        take = QPushButton("From the player")
        take.setProperty("quiet", "1")
        take.setToolTip("Whatever is playing right now.")
        take.clicked.connect(self.from_player)
        grid.addWidget(take, 0, 2)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        box.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(T.px(12))
        lab = QLabel("Timing against")
        lab.setStyleSheet(f"font-size:{T.px(14)}px; font-weight:600;"
                          " color:rgba(234,234,234,166);")
        row.addWidget(lab)
        self.source_box = QComboBox()
        self.source_box.addItems(["Spotify", "Local file"])
        self.source_box.currentTextChanged.connect(
            lambda t: self.owner.set_source("spotify" if t == "Spotify" else "local"))
        self.source_box.hide()
        self.source_seg = G.Segmented(["Spotify", "Local file"], "Spotify")
        self.source_seg.picked.connect(self.source_box.setCurrentText)
        self.source_box.currentTextChanged.connect(self.source_seg.set_value)
        row.addWidget(self.source_seg)
        self.audio_btn = QPushButton("Open audio…")
        self.audio_btn.clicked.connect(lambda: self.owner.open_audio(""))
        row.addWidget(self.audio_btn)
        self.fetch_btn = QPushButton("Fetch audio")
        self.fetch_btn.setToolTip(
            "Go and find a copy of this song to time against, by name and "
            "length, checked by listening to it. Kept afterwards.")
        self.fetch_btn.clicked.connect(self.fetch_audio)
        row.addWidget(self.fetch_btn)
        row.addStretch(1)
        self.track = QLabel("—")
        self.track.setStyleSheet(
            f"padding:{T.px(5)}px {T.px(12)}px; border-radius:{T.px(13)}px;"
            " border:1px solid rgba(234,234,234,41);"
            f" font-size:{T.px(13.5)}px; font-weight:600;"
            " color:rgba(234,234,234,191);")
        row.addWidget(self.track)
        box.addLayout(row)
        box.addWidget(self._note())

        box.addWidget(caps("2 · The words"))
        tiles = QHBoxLayout()
        tiles.setSpacing(T.px(12))
        for label, fn, tip in (
                ("From Genius", self.fetch_genius,
                 "Genius' text, with who sings what read from its headers "
                 "and brackets read as ad-libs."),
                ("From Mild Lyrics", self.fetch_chain,
                 "What the player is showing now, or what its sources "
                 "find: amll-ttml-db, LRCLIB, NetEase…"),
                ("Open a file…", self.open_file,
                 "A TTML, LRC or plain text file from disk."),
        ):
            tile = G.Tile(label, tip)
            tile.clicked.connect(fn)
            if label == "From Mild Lyrics":
                pick = QPushButton("One source ▾")
                pick.setProperty("ghost", "1")
                pick.setToolTip("Ask one source by name instead.")
                pick.clicked.connect(self.source_menu)
                tile.head.addWidget(pick)
            tiles.addWidget(tile, 1)
        box.addLayout(tiles)

        self.text = QPlainTextEdit()
        self.text.setFont(T.font(15, 500))
        self.text.setPlaceholderText(
            "…or paste the words here.\n\n"
            "> at the start of a line is the answering voice (a duet).\n"
            "(brackets) at the end of a line are backing vocals.")
        self.text.setMinimumHeight(T.px(170))
        box.addWidget(self.text, 1)

        row = QHBoxLayout()
        self._multiplayer(row)
        row.addStretch(1)
        if self.standalone:
            add = QPushButton("Add to the end")
            add.setToolTip("Keep what is open and put these lines after it.")
            add.clicked.connect(lambda: self.take_text(append=True))
            row.addWidget(add)
            go = QPushButton("Replace the lyric")
        else:
            go = QPushButton("Start editing  →")
        go.setProperty("primary", "1")
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setDefault(True)
        go.clicked.connect(lambda: self.take_text(append=False))
        row.addWidget(go)
        box.addLayout(row)

    def _multiplayer(self, row) -> None:
        """Host or join a session from here too: a joiner has no lyric of
        their own to open first, so the File menu was one screen too far."""
        if self.standalone or not hasattr(self.owner, "collab"):
            return
        b = QPushButton("Multiplayer…")
        b.setToolTip("Time this lyric together with other people, editor to "
                     "editor with no server: host and send an invite, or "
                     "join with one.")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(self.owner.collab.open)
        row.addWidget(b)

    def _note(self) -> QLabel:
        """The page's own status line.

        The editor's is on the editor page, so everything said while this
        page was showing -- the fetch's progress, why it failed, why Genius
        had nothing -- went to a line nobody could see.
        """
        self.note = QLabel("")
        self.note.setProperty("hint", "1")
        self.note.setWordWrap(True)
        self.note.hide()
        return self.note

    # ----------------------------------------------------------------- audio
    def fetch_audio(self) -> None:
        """Find the song these words belong to, without leaving the window.

        The title and artist boxes on this page are the point: they are
        filled in before the words arrive, so the song can be fetched first
        and the lyric written against it -- which is the order somebody
        timing an unreleased track works in, and the order this page could
        not support at all until now.
        """
        meta = self.meta()
        if not meta["title"]:
            self.owner.say("type a title first, or take one from the player")
            return
        # What was typed wins over the lyric's own names. A box that only
        # repeats the player (refresh_track fills an empty one from it, and
        # a fetched copy's "title" is its file name) is not something typed.
        player = self.owner.player
        ask = {k: box.text().strip() for k, box, said in
               (("title", self.f_title, player.title()),
                ("artist", self.f_artist, player.artist()))
               if box.text().strip() and box.text().strip() != said}
        # A lyric with no names takes these -- but never a file name.
        named = meta if player.kind != "local" else ask
        if named.get("title"):
            self.owner.doc.meta.setdefault("Title", named["title"])
        if named.get("artist"):
            self.owner.doc.meta.setdefault("Artist", named["artist"])
        self.fetch_btn.setEnabled(False)
        self.owner.fetch_audio(then=lambda _p: self._fetched(), ask=ask)

    def _fetched(self) -> None:
        self.fetch_btn.setEnabled(True)
        self.refresh_track()

    # ------------------------------------------------------------------ meta
    def from_player(self) -> None:
        self.f_title.setText(self.owner.player.title())
        self.f_artist.setText(self.owner.player.artist())

    def refresh_track(self) -> None:
        """Show what is playing, and which source it is coming from.

        The combo is set with its signal blocked: this is REPORTING the
        current source, not choosing one, and letting it fire tore down the
        live player and dropped the audio file with it.
        """
        from PyQt6.QtCore import QSignalBlocker
        name = " — ".join(x for x in (self.owner.player.artist(),
                                      self.owner.player.title()) if x)
        self.track.setText(name or "nothing playing")
        with QSignalBlocker(self.source_box):
            self.source_box.setCurrentText(
                "Local file" if self.owner.player.kind == "local" else "Spotify")
        self.fetch_btn.setEnabled(True)
        if not self.f_title.text() and self.owner.player.title():
            self.from_player()

    def meta(self) -> dict:
        return {"title": self.f_title.text().strip() or self.owner.player.title(),
                "artist": self.f_artist.text().strip() or self.owner.player.artist(),
                "length": self.owner.player.duration()}

    # --------------------------------------------------------------- sources
    def take_text(self, append: bool) -> None:
        raw = self.text.toPlainText().strip()
        doc = M.from_text(raw) if raw else M.Doc()
        self._hand(doc, f"{len(doc.lines)} lines typed in"
                   if doc.lines else "an empty lyric", append)

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open lyric", "", LYRIC)
        if not path:
            return
        doc, said = read_lyric(path)
        if doc is None:
            self.owner.say(said)
            return
        self._hand(doc, said, False, path)

    def fetch_genius(self) -> None:
        import lyrics_gui as L
        token = L.load_token()
        if not token:
            self.owner.say(f"no Genius token — put one in the player's "
                           f"settings, which are {L.CONFIG}")
            return
        meta = self.meta()
        if not meta["title"]:
            self.owner.say("name the song first")
            return

        def job(say):
            say("searching Genius…")
            return sources.genius_hits(token, meta["title"], meta["artist"])

        def got(hits, err):
            if err:
                self.owner.say(f"could not ask Genius — {_reason(err)}")
                return
            if not hits:
                self.owner.say("Genius has nothing for that")
                return
            pick = hits[0]
            if len(hits) > 1:
                dlg = GeniusPick(hits, self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return
                pick = dlg.chosen() or hits[0]
            self.song_id = pick["id"]
            self.owner.song_id = pick["id"]

            def job2(say):
                say("reading the lyrics…")
                return sources.genius_doc(token, pick["id"])

            def got2(doc, err2):
                if err2:
                    self.owner.say(f"could not read that page — "
                                   f"{_reason(err2)}")
                    return
                if doc is None:
                    self.owner.say("that page has no lyrics on it yet")
                    return
                self._hand(doc, f"{len(doc.lines)} lines from Genius", False)

            self.owner.run(job2, got2, lane="lyrics")

        self.owner.run(job, got, lane="lyrics")

    def source_menu(self) -> None:
        from PyQt6.QtWidgets import QMenu
        order, on = sources.player_sources()
        menu = QMenu(self)
        live = menu.addAction("what the player is showing now")
        live.setEnabled(self.owner.link.alive())
        live.triggered.connect(lambda _c=False: self.fetch_from_player())
        menu.addSeparator()
        for name in [n for n in order if n in sources.providers()]:
            act = menu.addAction(name + ("" if name in on else "   (off in the "
                                                              "player)"))
            act.triggered.connect(lambda _c=False, n=name: self.fetch_chain(n))
        at = self.sender()
        menu.exec(at.mapToGlobal(at.rect().bottomLeft())
                  if isinstance(at, QPushButton)
                  else self.mapToGlobal(self.rect().center()))

    def fetch_from_player(self, fall_back: bool = False, own: bool = True) -> None:
        """Ask the running player for this song's own document.

        This is the only way to reach two of them: the Spicy Lyrics community
        document, which is not a provider in the chain at all, and an
        alignment the player made on this machine, which exists nowhere else.

        `own` asks for the song's OWN lyrics rather than whatever is on
        screen. While "Show in Mild Lyrics" is on, those differ and the second
        one is this editor's own file -- asking for the screen handed our
        document straight back, which is indistinguishable from the fetch
        doing nothing. An older player does not know `source_doc` and says so;
        that answer retries with the plain one.
        """
        link = self.owner.link
        if not link.alive():
            if fall_back:
                self.fetch_chain(force_chain=True)
            else:
                self.owner.say("no player to ask — is Mild Lyrics running?")
            return
        self._asked = getattr(self, "_asked", 0) + 1
        token = self._asked

        def finish():
            """Stop listening. Any later answer to this question is stale."""
            self._asked += 1
            try:
                link.doc.disconnect(answered)
            except Exception:
                pass

        def give_up(why: str):
            self.owner.say(why + (" — asking the sources instead"
                                  if fall_back else ""))
            if fall_back:
                self.fetch_chain(force_chain=True)

        def answered(got: dict):
            if token != self._asked:
                return
            why = str(got.get("why") or "")
            if got.get("ok") is False:
                finish()
                if own and "unknown command" in why:
                    self.fetch_from_player(fall_back=fall_back, own=False)
                    return
                give_up(f"the player could not: {why or 'refused'}")
                return
            if got.get("live"):
                finish()
                give_up("the player is showing this editor's own document")
                return
            doc = M.from_ttml(str(got.get("ttml") or ""))
            if doc is None or not doc.lines:
                finish()
                give_up("the player could not hand its lyrics over")
                return
            finish()
            where = str(got.get("source") or "the player")
            self._hand(doc, f"{len(doc.lines)} lines from {where} — what the "
                            f"player has for this song", False)

        def gave_up():
            if token != self._asked:
                return
            finish()
            give_up("the player did not answer")

        link.doc.connect(answered)
        QTimer.singleShot(1200, gave_up)
        link.ask_doc(own=own)

    def fetch_chain(self, only: str = "", force_chain: bool = False) -> None:
        import lyrics_gui as L
        if not only and not force_chain and self.owner.link.alive():
            self.fetch_from_player(fall_back=True)
            return
        meta = self.meta()
        tid = self.owner.player.track_id()

        trouble = []

        def job(say):
            say(f"asking {only}…" if only
                else "asking the sources the player is set to…")
            return sources.chain_doc(tid, meta, only=only, note=trouble.extend)

        def got(res, err):
            missed = L.unreached(trouble)
            missed = f" — could not reach {missed}" if missed else ""
            if err:
                self.owner.say(f"the lookup failed — {err}")
                return
            if not res or res[0] is None:
                asked = only or "the sources the player is set to"
                self.owner.say(f"{asked} had nothing for "
                               f"“{meta['artist']} — {meta['title']}”".strip()
                               + missed)
                return
            doc, name = res
            self._hand(doc, f"{len(doc.lines)} lines from "
                            f"{name or only or 'the chain'} "
                            f"({sources.quality(doc)}-timed){missed}", False)

        self.owner.run(job, got, lane="lyrics")

    def _hand(self, doc, said: str, append: bool, path: str = "") -> None:
        for key, w in (("Title", self.f_title), ("Artist", self.f_artist)):
            if w.text().strip():
                doc.meta.setdefault(key, w.text().strip())
        self.loaded.emit(doc, said, append, path)


def read_lyric(path: str):
    """A file from disk as a document, or (None, why not)."""
    import lyric_formats as F
    p = pathlib.Path(path)
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:                        # noqa: BLE001
        return None, f"could not read it — {exc}"
    end = p.suffix.lower()
    if end == ".txt":
        doc = M.from_text(raw)
    elif end in (".ttml", ".xml"):
        doc = M.from_ttml(raw)
    else:
        # LRC, enhanced LRC, ASS, KRC, QRC, YRC, LYS, SRT -- see lyric_formats.
        try:
            body = F.read(p)
        except Exception as exc:                    # noqa: BLE001
            return None, f"could not read it — {type(exc).__name__}: {exc}"
        doc = M.from_body(body) if body else None
    if doc is None or not doc.lines:
        return None, "nothing readable in that file"
    return doc, (f"{p.name} — {len(doc.lines)} lines, "
                 f"{doc.timed_lines()} timed")
