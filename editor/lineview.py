"""The lyric, line per line, with every syllable as something you can hit.

This is the whole editor really: a vertical list of lines, each one a row of
chips, and the chips are the syllables the file is actually made of. Words
show as their chips butted together with no gap between them and a space
between words, so a word cut into syllables looks like a word coming apart --
which is what it is, and what no list of times can show.

    12  ▸duet  [The][lights] [go] [out], [and] [I]   0:32.99 → 0:36.19
        ↳bg    [(ooh)]                               0:35.10 → 0:36.02

A backing voice gets a row under the line it answers, the way a player draws
it, rather than a footnote inside the row: it is a concurrent voice with its
own timings and it has to be as clickable as the lead.

Painted rather than assembled out of widgets. A four-minute song is a couple
of thousand chips, and two thousand QPushButtons would cost more to lay out
than the audio costs to decode; painting a laid-out list is what the player
already does with the same data. Only the rows in view are drawn, and the
layout is cached until the width or the document changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractScrollArea, QApplication, QDialog, QLineEdit, QMenu,
)

from . import model as M, ops

from . import theme as T

BG = T.q(T.INK_1)
ROW_SEL = T.q(T.INK_2)
RULE = T.q(T.LINE)
TEXT = T.q(T.TEXT)
DIM = T.q(T.MUTE)
NUM = T.q(T.FAINT)
CHIP = T.q(T.CHIP)
CHIP_HOVER = T.q(T.CHIP_HOVER)
CHIP_CURSOR = T.q(T.LEAD)
CHIP_LIVE = T.q(T.LEAD)
CHIP_SUNG = T.q(T.SUNG)
LEAD_INK = T.q(T.TEXT)
BACK_INK = T.q(T.BACK)
DUET = T.q(T.DUET)
BADGE_BG = T.q(T.BACK)
ON_ACCENT = QColor("#0b1020")

# All of these are at scale 1 and go through T.px(), so the zoom moves the
# whole layout together -- a bigger word in the same slot would just collide
# with the times column.
GUTTER = 92.0                 # number and badges
TIMES = 168.0                 # start -> end, in timing mode
PAD_X, PAD_Y = 8.0, 6.0       # inside a chip
# Wider than the padding inside a chip, and it has to be: a word cut into
# syllables must read as ONE word with seams in it, not as two words. The gap
# between words is therefore bigger than anything inside one.
WORD_GAP = 22.0
BG_INDENT = 26.0              # a backing voice sits in from its lead
ROW_GAP = 10.0
LYRIC_PX = 18                 # the words themselves -- the point of the tool
TIME_PX = 13
NUM_PX = 13


@dataclass
class Row:
    """One drawn row: a line's lead, or one of its backing voices."""
    line: int
    voice: int
    top: float = 0.0
    height: float = 0.0
    chips: list = field(default_factory=list)      # QRectF per syllable
    lines_used: int = 1


class LineList(QAbstractScrollArea):
    """The document, laid out and clickable."""

    will_edit = pyqtSignal()                   # take an undo snapshot now
    edited = pyqtSignal(str)                   # an op ran; here is what it did
    cursor_changed = pyqtSignal(int, int, int)
    word_changed = pyqtSignal(int, int, int)   # a word was split or rejoined
    selection_changed = pyqtSignal()
    seek_to = pyqtSignal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.doc: M.Doc = M.Doc()
        self.mode = "edit"                     # edit | timing | preview
        self.pos = 0.0
        self.follow = True
        self.cursor = (0, 0, 0)
        # Whether tapping walks into the backing voices or stays on the lead.
        self.tap_adlibs = True
        # (line, voice) pairs, not line numbers: a backing voice is its own
        # row with its own times, and selecting the words a singer sings
        # should not drag the voice answering them along with it.
        self.selection: set = set()
        self._anchor: tuple = (0, 0)           # for shift-click ranges
        self.rows: list[Row] = []
        self._key = None                       # what the layout was made for
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.viewport().setBackgroundRole(self.backgroundRole())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self.viewport().update())
        self.setFont(T.font(LYRIC_PX, 500))
        self.m = self._metrics()
        self.editor: QLineEdit | None = None
        # A row being dragged by its number, and where it would land.
        self._drag: dict | None = None

    # ------------------------------------------------------------- outside
    def set_doc(self, doc: M.Doc) -> None:
        self.doc = doc
        self.relayout()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.relayout()                        # the times column comes and goes

    def set_pos(self, t: float) -> None:
        """Move the playhead, and follow it if asked.

        Only in preview, and only when something is actually sounding: an
        editor that scrolled away from the line being worked on every time the
        song moved would be unusable, which is why following is a preview
        behaviour and a deliberate one everywhere else.
        """
        self.pos = t
        if self.mode == "preview" and self.follow:
            for r in self.rows:
                a, b = self._span(r)
                if a is not None and b is not None and a <= t <= b:
                    self.reveal_row(r)
                    break
        self.viewport().update()

    def selected(self) -> list[int]:
        """The LINES touched by the selection -- what a line operation acts on."""
        return sorted({i for i, _v in self.selection
                       if 0 <= i < len(self.doc.lines)})

    def selected_rows(self) -> list:
        """The rows themselves, as (line, voice) -- what a voice operation
        acts on, and what the strip lights up."""
        return sorted(p for p in self.selection
                      if 0 <= p[0] < len(self.doc.lines))

    def select(self, rows, anchor: bool = True) -> None:
        """`rows` may be line numbers or (line, voice) pairs."""
        want = set()
        for row in rows:
            line, voice = row if isinstance(row, tuple) else (row, 0)
            if 0 <= line < len(self.doc.lines):
                want.add((line, voice))
        self.selection = want
        if anchor and want:
            self._anchor = min(want)
        self.selection_changed.emit()
        self.viewport().update()

    def set_cursor(self, line: int, voice: int, syl: int, reveal: bool = True) -> None:
        g = self.doc.group(line, voice)
        if g is None or not 0 <= syl < len(g.syls):
            return
        self.cursor = (line, voice, syl)
        if (line, voice) not in self.selection:
            self.select([(line, voice)])
        if reveal:
            self.reveal_cursor()
        self.cursor_changed.emit(line, voice, syl)
        self.viewport().update()

    def _metrics(self) -> dict:
        return {"gutter": T.px(GUTTER), "times": T.px(TIMES),
                "pad_x": T.px(PAD_X), "pad_y": T.px(PAD_Y),
                "word_gap": T.px(WORD_GAP), "indent": T.px(BG_INDENT),
                "row_gap": T.px(ROW_GAP)}

    def restyle(self) -> None:
        """Take a new zoom. Everything here is sized from the font."""
        self.setFont(T.font(LYRIC_PX, 500))
        self.m = self._metrics()
        self.relayout(force=True)

    # --------------------------------------------------------------- layout
    def relayout(self, force: bool = False) -> None:
        self._key = None if force else self._key
        self._layout()
        self.viewport().update()

    def _layout(self) -> None:
        width = self.viewport().width()
        key = (width, self.mode, len(self.doc.lines), T.SCALE,
               id(self.doc), self._doc_stamp())
        if key == self._key:
            return
        fm = QFontMetricsF(self.font())
        m = self.m = self._metrics()
        chip_h = fm.height() + m["pad_y"] * 2
        room = max(120.0, width - m["gutter"] - m["indent"] - 16.0
                   - (m["times"] if self.mode != "edit" else 0.0))
        rows: list[Row] = []
        y = 4.0
        for i, ln in enumerate(self.doc.lines):
            for v, g in enumerate(ln.groups()):
                row = Row(i, v, y)
                left = m["gutter"] + (m["indent"] if v else 0.0)
                x, used = 0.0, 1
                for word in g.words():
                    wide = sum(fm.horizontalAdvance(g.syls[k].text)
                               + m["pad_x"] * 2 for k in word)
                    # A word wraps whole. Splitting one across two rows would
                    # put half of "everything" at the end of a line and the
                    # rest at the start of the next, which reads as two words.
                    if x and x + wide > room:
                        x, used = 0.0, used + 1
                    for k in word:
                        w = fm.horizontalAdvance(g.syls[k].text) + m["pad_x"] * 2
                        row.chips.append(QRectF(
                            left + x, y + (used - 1) * (chip_h + 3), w, chip_h))
                        x += w
                    x += WORD_GAP
                if not g.syls:
                    row.chips = []
                row.lines_used = used
                row.height = used * (chip_h + 3) + m["row_gap"]
                y += row.height
                rows.append(row)
        self.rows = rows
        self._key = key
        total = int(y + 8)
        bar = self.verticalScrollBar()
        bar.setPageStep(max(1, self.viewport().height()))
        bar.setSingleStep(int(chip_h))
        bar.setRange(0, max(0, total - self.viewport().height()))

    def _doc_stamp(self):
        """Enough of the document to know when the layout is stale.

        The texts and the shape, not the times: a syllable moved in time does
        not change where its chip is drawn, and re-laying the whole song out
        on every frame of a drag would be the most expensive thing here.
        """
        return tuple((ln.agent, len(ln.bg),
                      tuple(tuple(s.text for s in g.syls) for g in ln.groups()))
                     for ln in self.doc.lines)

    def resizeEvent(self, ev) -> None:                    # noqa: N802 (Qt name)
        super().resizeEvent(ev)
        self._key = None
        self._layout()
        self._place_editor()

    # -------------------------------------------------------------- drawing
    def paintEvent(self, _ev) -> None:                    # noqa: N802 (Qt name)
        self._layout()
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        W, H = self.viewport().width(), self.viewport().height()
        p.fillRect(0, 0, W, H, BG)
        off = self.verticalScrollBar().value()
        fm = QFontMetricsF(self.font())
        small = T.font(11, 500)
        for r in self.rows:
            top = r.top - off
            if top + r.height < -20 or top > H + 20:
                continue                       # not in view; do not draw it
            self._row(p, r, top, W, fm, small)
        if not self.rows:
            p.setPen(QPen(DIM, 1))
            p.drawText(QRectF(0, 0, W, H), int(Qt.AlignmentFlag.AlignCenter),
                       "no lines yet")
        spot = (self._drag or {}).get("spot")
        if spot and (self._drag or {}).get("live"):
            y = spot["y"] - self.verticalScrollBar().value()
            p.setPen(QPen(T.q(T.LEAD), 2))
            p.drawLine(QPointF(4, y), QPointF(W - 4, y))
            p.setBrush(T.q(T.LEAD))
            p.drawEllipse(QPointF(6, y), 3.5, 3.5)
            p.setBrush(Qt.BrushStyle.NoBrush)

    def _row(self, p, r: Row, top: float, W: float, fm, small) -> None:
        ln = self.doc.lines[r.line]
        g = self.doc.group(r.line, r.voice)
        chosen = (r.line, r.voice) in self.selection
        if chosen:
            p.fillRect(QRectF(0, top - 2, W, r.height), ROW_SEL)
            # A bar down the edge rather than a wash over everything: the wash
            # competed with the chips, which are the thing being looked at.
            p.fillRect(QRectF(0, top - 2, 3, r.height), T.q(T.LEAD))
        p.setPen(QPen(RULE, 1))
        p.drawLine(QPointF(0, top + r.height - 3), QPointF(W, top + r.height - 3))

        # gutter: the number once per line, then what kind of voice this is
        if r.voice == 0:
            p.setFont(T.font(NUM_PX, 500, mono=True))
            p.setPen(QPen(NUM, 1))
            p.drawText(QRectF(T.px(6), top, T.px(34),
                              fm.height() + self.m["pad_y"] * 2),
                       int(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter), str(r.line + 1))
            if ln.agent != "v1":
                self._badge(p, T.px(48), top + 4, "duet", DUET)
        else:
            self._badge(p, T.px(48), top + 4, "bg", BADGE_BG)
        p.setFont(self.font())

        ink = LEAD_INK if r.voice == 0 else BACK_INK
        off = self.verticalScrollBar().value()
        for run in g.words():
            run = [k for k in run if k < len(r.chips)]
            if not run:
                continue
            self._word(p, r, g, run, off, ink, fm)

        if self.mode != "edit":
            a, b = self._span(r)
            p.setFont(T.font(TIME_PX, 500, mono=True))
            p.setPen(QPen(TEXT if chosen else DIM, 1))
            p.drawText(QRectF(W - self.m["times"], top, self.m["times"] - 8,
                              fm.height() + self.m["pad_y"] * 2),
                       int(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter),
                       f"{_fmt(a)} → {_fmt(b)}")
            p.setFont(self.font())

    def _badge(self, p, x: float, y: float, text: str, colour: QColor) -> None:
        """A small filled pill. Dark ink on it, because the fills are bright."""
        p.setFont(T.font(12, 600))
        fm = QFontMetricsF(p.font())
        box = QRectF(x, y, fm.horizontalAdvance(text) + 12, fm.height() + 3)
        p.setBrush(colour)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(box, T.R_BADGE, T.R_BADGE)
        p.setPen(QPen(ON_ACCENT, 1))
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _word(self, p, r: Row, g, run: list, off: float, ink, fm) -> None:
        """One word: a single block, with a seam per syllable inside it.

        Drawn as a whole rather than as a row of separate chips because that
        is what it is. A word cut into three syllables is still the word --
        the seams say where the timings change, and the block says the reader
        is looking at one thing.
        """
        boxes = [r.chips[k].translated(0, -off) for k in run]
        # A word can wrap mid-way only if it was laid out that way, which it
        # never is -- but a defensive check beats a rectangle spanning two
        # rows if that ever changes.
        rows = {}
        for k, box in zip(run, boxes):
            rows.setdefault(round(box.top()), []).append((k, box))
        for _top, part in rows.items():
            whole = part[0][1]
            for _k, b in part[1:]:
                whole = whole.united(b)
            timed = all(g.syls[k].timed for k, _b in part)
            if timed:
                p.setBrush(CHIP)
                p.setPen(Qt.PenStyle.NoPen)
            else:
                # Absence should look like absence: an untimed word is an
                # outline, not a differently-shaded fill.
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(RULE, 1))
            p.drawRoundedRect(whole, T.R_CHIP, T.R_CHIP)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for n, (k, box) in enumerate(part):
                self._chip(p, box, g.syls[k],
                           (r.line, r.voice, k) == self.cursor, ink, fm,
                           inside=len(part) > 1)
                if n < len(part) - 1:
                    # the seam: the surface below showing through, not a
                    # black line drawn over the top
                    p.setPen(QPen(BG, 1))
                    p.drawLine(QPointF(box.right(), box.top() + 3),
                               QPointF(box.right(), box.bottom() - 3))

    def _chip(self, p, box: QRectF, s: M.Syl, is_cursor: bool, ink, fm,
              inside: bool = False) -> None:
        live = s.timed and s.start <= self.pos <= (s.end or s.start)
        sung = s.timed and (s.end or s.start) < self.pos
        fill = (CHIP_CURSOR if is_cursor else CHIP_LIVE if live else None)
        if self.mode == "preview":
            fill = CHIP_SUNG if sung else (CHIP_LIVE if live else None)
        # The word's own block is already painted underneath; a syllable only
        # paints over it when it has something of its own to say.
        if fill is not None:
            p.setBrush(fill)
            p.setPen(Qt.PenStyle.NoPen)
            radius = 0 if inside else 3
            p.drawRoundedRect(box, radius, radius)
            p.setBrush(Qt.BrushStyle.NoBrush)
        if is_cursor:
            p.setPen(QPen(QColor(255, 255, 255, 110), 1.4))
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        if self.mode == "preview" and live and s.end and s.end > s.start:
            # The sweep: the chip fills left to right across the syllable, the
            # way the player draws it, so a preview shows the same thing a
            # listener will see rather than a chip merely lighting up.
            k = (self.pos - s.start) / (s.end - s.start)
            p.setBrush(CHIP_SUNG)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(box.left(), box.top(),
                                     box.width() * max(0.0, min(1.0, k)),
                                     box.height()), 3, 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(ink if s.timed or self.mode == "edit" else DIM, 1))
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), s.text)

    def _span(self, r: Row):
        g = self.doc.group(r.line, r.voice)
        if g is None:
            return None, None
        a, b = g.span()
        if a is None and r.voice == 0:
            ln = self.doc.lines[r.line]
            return ln.start, ln.end
        return a, b

    # ---------------------------------------------------------- dragging rows
    def _drop_at(self, y: float):
        """What a drop at `y` would mean, as a dict, or None.

        Rows, not lines: dropping among a line's backing voices puts the
        dragged one in that place, and dropping on a lead moves a whole line.
        """
        if not self.rows:
            return None
        y += self.verticalScrollBar().value()
        row, lower = self.rows[-1], True
        for r in self.rows:
            if y <= r.top + r.height:
                row, lower = r, y > r.top + r.height / 2
                break
        return {"row": row, "after": lower,
                "y": row.top + (row.height if lower else 0)}

    def _apply_drop(self, drag: dict, spot: dict) -> None:
        # The drag dict is handed in rather than read off self: the release
        # clears it first, so that a drop which opens a dialog cannot be
        # re-entered by a second release.
        line, voice = drag["row"]
        row, after = spot["row"], spot["after"]
        if voice == 0:
            to = row.line + (1 if after else 0)
            self._edit(lambda: ops.reorder_lines(self.doc, [line], to))
            return
        if row.voice == 0:
            # onto the words of a line: the end of its answers, or the front
            # if dropped above them
            self._edit(lambda: ops.move_backing(
                self.doc, line, voice, row.line,
                None if after else 0))
            return
        at = (row.voice - 1) + (1 if after else 0)
        if row.line == line and at > voice - 1:
            at -= 1                      # it is coming out of this list first
        self._edit(lambda: ops.move_backing(self.doc, line, voice,
                                            row.line, at))

    # --------------------------------------------------------------- mouse
    def _hit(self, x: float, y: float):
        """(row, chip index or None) under the pointer, or (None, None)."""
        y += self.verticalScrollBar().value()
        for r in self.rows:
            if not r.top - 2 <= y <= r.top + r.height:
                continue
            for k, rect in enumerate(r.chips):
                if rect.adjusted(-1, -1, 1, 1).contains(QPointF(x, y)):
                    return r, k
            return r, None
        return None, None

    def mousePressEvent(self, ev) -> None:                # noqa: N802 (Qt name)
        self.commit_edit()
        r, k = self._hit(ev.position().x(), ev.position().y())
        if r is None:
            return
        # The number and the badge are the handle: pressing there and moving
        # picks the row up. Anywhere else in the row still selects and edits,
        # so a drag can never start by accident on a word.
        if (ev.button() == Qt.MouseButton.LeftButton
                and ev.position().x() < self.m["gutter"] + self.m["indent"]
                and self.mode != "preview"):
            self._drag = {"row": (r.line, r.voice), "y0": ev.position().y(),
                          "live": False, "spot": None}
        mods = ev.modifiers()
        here = (r.line, r.voice)
        if mods & Qt.KeyboardModifier.ShiftModifier:
            # Over the ROWS as drawn, so a range can start on a lead and end
            # on a backing voice without swallowing the ones between.
            order = [(x.line, x.voice) for x in self.rows]
            try:
                a, b = order.index(self._anchor), order.index(here)
            except ValueError:
                a = b = order.index(here)
            lo, hi = sorted((a, b))
            self.select(order[lo:hi + 1], anchor=False)
        elif mods & Qt.KeyboardModifier.ControlModifier:
            self.selection ^= {here}
            self._anchor = here
            self.selection_changed.emit()
        else:
            self.select([here])
        if k is not None:
            self.cursor = (r.line, r.voice, k)
            self.cursor_changed.emit(*self.cursor)
            if ev.button() == Qt.MouseButton.RightButton:
                self.chip_menu(ev.globalPosition().toPoint())
        elif ev.button() == Qt.MouseButton.RightButton:
            self.line_menu(ev.globalPosition().toPoint())
        self.viewport().update()

    def mouseMoveEvent(self, ev) -> None:                 # noqa: N802 (Qt name)
        if self._drag is None:
            return
        y = ev.position().y()
        if not self._drag["live"] and abs(y - self._drag["y0"]) > 4:
            self._drag["live"] = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._drag["live"]:
            self._drag["spot"] = self._drop_at(y)
            self.viewport().update()

    def mouseReleaseEvent(self, _ev) -> None:             # noqa: N802 (Qt name)
        drag, self._drag = self._drag, None
        if drag is None:
            return
        self.unsetCursor()
        if drag["live"] and drag["spot"]:
            self._apply_drop(drag, drag["spot"])
        self.viewport().update()

    def mouseDoubleClickEvent(self, ev) -> None:          # noqa: N802 (Qt name)
        r, k = self._hit(ev.position().x(), ev.position().y())
        if r is None:
            return
        if k is None:
            # Double-clicking the empty part of a row is "take me there",
            # which is what double-clicking a line meant in the old table.
            a, _b = self._span(r)
            if a is not None:
                self.seek_to.emit(a)
            return
        self.edit_chip(r, k)

    def wheelEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        self.commit_edit()
        super().wheelEvent(ev)

    # -------------------------------------------------------- inline editing
    def edit_chip(self, r: Row, k: int) -> None:
        """A text box over the chip, committing on Enter and on losing focus."""
        g = self.doc.group(r.line, r.voice)
        if g is None or not 0 <= k < len(g.syls):
            return
        self.commit_edit()
        self.cursor = (r.line, r.voice, k)
        ed = QLineEdit(g.syls[k].text, self.viewport())
        ed.setFont(self.font())
        ed.selectAll()
        ed.returnPressed.connect(self.commit_edit)
        ed.editingFinished.connect(self.commit_edit)
        self.editor = ed
        self._edit_at = (r.line, r.voice, k)
        self._place_editor()
        ed.show()
        ed.setFocus()

    def _place_editor(self) -> None:
        if not self.editor:
            return
        line, voice, k = self._edit_at
        for r in self.rows:
            if (r.line, r.voice) == (line, voice) and k < len(r.chips):
                box = r.chips[k].translated(0, -self.verticalScrollBar().value())
                self.editor.setGeometry(int(box.left()), int(box.top()),
                                        max(60, int(box.width()) + 40),
                                        int(box.height()))
                return

    def commit_edit(self) -> None:
        ed, self.editor = self.editor, None
        if ed is None:
            return
        text = ed.text()
        ed.deleteLater()
        line, voice, k = self._edit_at
        g = self.doc.group(line, voice)
        if g is None or not 0 <= k < len(g.syls) or text == g.syls[k].text:
            return
        self.will_edit.emit()
        self.edited.emit(ops.set_text(self.doc, line, voice, k, text) or "edited")

    # ---------------------------------------------------------------- menus
    def _run(self, said) -> None:
        """An op has already been applied -- tell the window about it."""
        if said:
            self.edited.emit(said)

    def chip_menu(self, at) -> None:
        line, voice, k = self.cursor
        g = self.doc.group(line, voice)
        if g is None or not 0 <= k < len(g.syls):
            return
        word = next((w for w, run in enumerate(g.words()) if k in run), 0)
        menu = QMenu(self)
        add = menu.addAction

        def act(label, fn, tip=""):
            a = add(label)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(lambda _c=False: self._edit(fn))
            return a

        act("Edit text…", None).triggered.disconnect()
        menu.actions()[-1].triggered.connect(
            lambda _c=False: self._edit_current())
        menu.addSeparator()
        def act_word(label, fn, tip=""):
            """An edit that changes how a word is split -- remembered."""
            a = menu.addAction(label)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(lambda _c=False: self._edit(fn, word=True))

        act_word("Cut this word into syllables",
                 lambda: ops.syllabify(self.doc, line, voice, [word]))
        act_word("Split this word…",
                 lambda: self._split_prompt(line, voice, k))
        act_word("Merge with the next syllable",
                 lambda: ops.merge_syllables(self.doc, line, voice, k, k + 1))
        menu.addSeparator()
        act_word("Join with the next word",
                 lambda: ops.join_words(self.doc, line, voice, word))
        act_word("Break the word after this syllable",
                 lambda: ops.end_word(self.doc, line, voice, k))
        menu.addSeparator()
        act("Insert a word before",
            lambda: ops.insert_syllable(self.doc, line, voice, k))
        act("Insert a word after",
            lambda: ops.insert_syllable(self.doc, line, voice, k + 1))
        act("Delete this word", lambda: ops.delete_syllables(
            self.doc, line, voice, g.words()[word][0], g.words()[word][-1]))
        menu.addSeparator()
        act("Move the word up a line",
            lambda: ops.move_word(self.doc, line, voice, word, -1))
        act("Move the word down a line",
            lambda: ops.move_word(self.doc, line, voice, word, 1))
        menu.addSeparator()
        if voice:
            act("Move this ad-lib to the line above",
                lambda: ops.move_backing(self.doc, line, voice, line - 1))
            act("Move this ad-lib to the line below",
                lambda: ops.move_backing(self.doc, line, voice, line + 1))
            act("Move it up among this line's ad-libs",
                lambda: ops.move_backing(self.doc, line, voice, line,
                                         voice - 2))
            act("Move it down among them",
                lambda: ops.move_backing(self.doc, line, voice, line, voice))
            act("Give it a line of its own",
                lambda: ops.split_off_backing(self.doc, line, voice))
        else:
            act("Make this line an ad-lib of the line above",
                lambda: ops.to_backing(self.doc, line, voice, line - 1))
            act("Make it an ad-lib of the line below",
                lambda: ops.to_backing(self.doc, line, voice, line + 1))
        menu.addSeparator()
        act("Split the line here", lambda: ops.split_line(self.doc, line, word))
        if voice == 0:
            act("From here on is a backing vocal",
                lambda: ops.to_background(self.doc, line, k, len(g.syls) - 1))
        else:
            act("Fold this backing vocal into the lead",
                lambda: ops.to_lead(self.doc, line, voice - 1))
        menu.exec(at)

    def line_menu(self, at) -> None:
        sel = self.selected() or [self.cursor[0]]
        menu = QMenu(self)

        def act(label, fn):
            menu.addAction(label).triggered.connect(
                lambda _c=False: self._edit(fn))

        act("Duplicate", lambda: ops.duplicate_rows(
            self.doc, self.selected_rows() or [self.cursor[:2]]))
        act("Delete", lambda: ops.delete_rows(
            self.doc, self.selected_rows() or [self.cursor[:2]]))
        act("Insert a line below", lambda: ops.insert_line(self.doc, sel[-1] + 1))
        menu.addSeparator()
        act("Merge these lines", lambda: ops.merge_lines(
            self.doc, sel[0], sel[-1] - sel[0] + 1))
        act("Move up", lambda: ops.move_lines(self.doc, sel, -1))
        act("Move down", lambda: ops.move_lines(self.doc, sel, 1))
        menu.addSeparator()
        act("Main voice", lambda: ops.set_agent(self.doc, sel, "v1"))
        act("Duet voice", lambda: ops.set_agent(self.doc, sel, "v2"))
        menu.addSeparator()
        act("Spread the times evenly",
            lambda: ops.spread(self.doc, self.cursor[0], self.cursor[1]))
        act("Clear the times", lambda: ops.clear_times(self.doc, sel))
        menu.exec(at)

    def _edit(self, fn, word: bool = False) -> None:
        self.will_edit.emit()
        said = fn()
        if said:
            self.edited.emit(said)
            if word:
                self.word_changed.emit(*self.cursor)
        else:
            # Nothing happened, so the snapshot taken above is noise. The
            # window drops it when it hears nothing back.
            self.edited.emit("")

    def _edit_current(self) -> None:
        line, voice, k = self.cursor
        for r in self.rows:
            if (r.line, r.voice) == (line, voice):
                self.edit_chip(r, k)
                return

    def _split_prompt(self, line: int, voice: int, k: int):
        """Ask where the word comes apart, by pointing at it.

        Cuts, plural: a word sung in three used to need splitting, finding
        the new piece, and splitting again. And the same word is sung the
        same way wherever it appears, so by default the answer is applied to
        every copy of it in the song -- and kept for the next one, like any
        other correction.
        """
        from . import keys as K
        from .wordsplit import SplitDialog
        g = self.doc.group(line, voice)
        if g is None or not 0 <= k < len(g.syls):
            return None
        run = next((r for r in g.words() if k in r), None)
        if not run:
            return None
        # The whole WORD is what is being split, not one piece of it: cutting
        # a piece that is already part of a split word can only ever add a
        # boundary, and the picture has to show the word to be pointed at.
        if len(run) > 1:
            ops.merge_syllables(self.doc, line, voice, run[0], run[-1])
            run = [run[0]]
        k = run[0]
        word = g.syls[k].text
        if len(word) < 2:
            return None
        dlg = SplitDialog(word, everywhere=bool(
            K.config().get("split_everywhere", True)), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        K.remember(split_everywhere=dlg.everywhere.isChecked())
        pieces = dlg.pieces()
        said = ops.split_at(self.doc, line, voice, k, dlg.cuts())
        if said is None:
            return None
        if dlg.everywhere.isChecked():
            n = ops.split_everywhere(self.doc, word, pieces,
                                     skip=(line, voice, k))
            if n:
                said += f", and {n} more like it"
        return said

    # ------------------------------------------------------------ scrolling
    # ------------------------------------------------------------ scrolling
    def reveal_row(self, r: Row) -> None:
        bar = self.verticalScrollBar()
        top, bottom = r.top - bar.value(), r.top + r.height - bar.value()
        H = self.viewport().height()
        if top < H * 0.2:
            bar.setValue(int(r.top - H * 0.2))
        elif bottom > H * 0.85:
            bar.setValue(int(r.top + r.height - H * 0.85))

    def reveal_cursor(self) -> None:
        line, voice, _k = self.cursor
        for r in self.rows:
            if (r.line, r.voice) == (line, voice):
                self.reveal_row(r)
                return

    # ------------------------------------------------------- moving the cursor
    def walk(self) -> list:
        """Every chip in the order it is tapped.

        In the order things SOUND, not the order they are drawn: an ad-lib
        that opens its line is tapped before the words it opens, one that
        answers is tapped after them. Where the times are already known they
        decide; where they are not -- which is most of the time, since this is
        what puts them there -- the lead_in flag does.

        With `tap_adlibs` off the walk stays on the lead voices. Most lines
        have no ad-lib at all, and on the ones that do it is often timed in a
        pass of its own; a cursor that wanders into a backing voice
        mid-verse costs more than it saves.
        """
        out = []
        for i, ln in enumerate(self.doc.lines):
            groups = [(0, ln.lead)]
            if self.tap_adlibs:
                groups += [(v, g) for v, g in enumerate(ln.groups()) if v]

                def when(pair):
                    v, g = pair
                    a = g.span()[0]
                    if a is not None:
                        return (a, v)
                    # untimed: an opener comes first, the lead next, the rest
                    # after it
                    return ((-1.0, v) if getattr(g, "lead_in", False)
                            else ((0.0, 0) if v == 0 else (1.0, v)))

                groups.sort(key=when)
            for v, g in groups:
                out += [(i, v, n) for n in range(len(g.syls))]
        return out

    def step(self, delta: int, over_lines: bool = True) -> bool:
        """The next chip, walking into the next voice and the next line."""
        line, voice, k = self.cursor
        order = self.walk()
        if not order:
            return False
        try:
            at = order.index((line, voice, k))
        except ValueError:
            at = 0
        want = at + delta
        if not 0 <= want < len(order):
            return False
        if not over_lines and order[want][0] != line:
            return False
        self.set_cursor(*order[want])
        return True

    def step_line(self, delta: int) -> bool:
        line = self.cursor[0] + delta
        if not 0 <= line < len(self.doc.lines):
            return False
        self.set_cursor(line, 0, 0)
        return True

    def keyPressEvent(self, ev) -> None:                  # noqa: N802 (Qt name)
        key = ev.key()
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Right):
            self.step(1)
        elif key in (Qt.Key.Key_Backtab, Qt.Key.Key_Left):
            self.step(-1)
        elif key == Qt.Key.Key_Down:
            self.step_line(1)
        elif key == Qt.Key.Key_Up:
            self.step_line(-1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_F2):
            self._edit_current()
        elif key == Qt.Key.Key_A and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.select([(r.line, r.voice) for r in self.rows])
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()


def _fmt(t) -> str:
    if t is None:
        return "—"
    return f"{int(t) // 60}:{int(t) % 60:02d}.{int(round(t * 1000)) % 1000:03d}"
