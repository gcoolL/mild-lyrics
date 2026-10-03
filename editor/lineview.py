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

There are two ways to put times on it. The timing keys walk a cursor along
and stamp one chip per press; drag sync drags across a bar of slices under
the lyric and stamps a syllable per slice -- see `editor/syncbar.py`. The
gesture is not here, because a chip is as wide as the word it says with no
floor under it and a one-letter word is a sliver; what IS here is the row a
drag is armed on and the lighting up of the words as one goes over them,
which is where anybody doing it is actually looking.

Painted rather than assembled out of widgets. A four-minute song is a couple
of thousand chips, and two thousand QPushButtons would cost more to lay out
than the audio costs to decode; painting a laid-out list is what the player
already does with the same data. Only the rows in view are drawn, and the
layout is cached until the width or the document changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import QPointF, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractScrollArea, QApplication, QDialog, QLineEdit, QMenu,
)

from . import model as M, ops

from . import gpu as GPU
from . import theme as T
import spicy_lyrics as SL  # noqa: E402  (on the path model.py sets up)

def _inks() -> None:
    """The palette, re-read. Called at import and again whenever the
    accent changes -- these are module-level because they are asked for
    once per painted element and a lookup per chip is not free, which
    means a colour somebody has just chosen has to be pushed into them
    rather than picked up by itself."""
    global BG, ROW_SEL, RULE, TEXT, DIM, NUM, CHIP, CHIP_HOVER
    global CHIP_CURSOR, CHIP_LIVE, CHIP_PLAYING, CHIP_SUNG, CHIP_SWEEP
    global CHIP_SWEPT, LEAD_INK, BACK_INK, DUET, BADGE_BG, ON_ACCENT
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
    CHIP_PLAYING = T.q(T.LEAD_DIM)
    CHIP_SUNG = T.q(T.SUNG)
    CHIP_SWEEP = T.q(T.LEAD)
    CHIP_SWEPT = T.q(T.LEAD_DIM)
    LEAD_INK = T.q(T.TEXT)
    BACK_INK = T.q(T.BACK)
    DUET = T.q(T.DUET)
    BADGE_BG = T.q(T.BACK)
    ON_ACCENT = QColor("#0b1020")


_inks()

PLACEHOLDER = "…"

GUTTER = 92.0
TIMES = 168.0
PAD_X, PAD_Y = 8.0, 6.0
WORD_GAP = 22.0
BG_INDENT = 26.0
ROW_GAP = 10.0
LYRIC_PX = 18
TIME_PX = 13
NUM_PX = 13
# One per group, in the order they were made. Their own hues rather than the
# theme's: the accent, the duet green and the backing orange each already
# mean something in this list, and a group drawn in one would read as that.
PART_HUES = ("#8fb8ff", "#f2a7e1", "#f5d06f", "#8fe0c0", "#f59f8f")


@dataclass
class Row:
    """One drawn row: a line's lead, or one of its backing voices."""
    line: int
    voice: int
    top: float = 0.0
    height: float = 0.0
    chips: list = field(default_factory=list)
    lines_used: int = 1
    roman: str = ""
    rline: QRectF | None = None
    plus: QRectF | None = None


class LineList(QAbstractScrollArea):
    """The document, laid out and clickable."""

    will_edit = pyqtSignal()
    edited = pyqtSignal(str)
    cursor_changed = pyqtSignal(int, int, int)
    word_changed = pyqtSignal(int, int, int)
    selection_changed = pyqtSignal()
    seek_to = pyqtSignal(float)
    armed = pyqtSignal(int, int)
    roman_edited = pyqtSignal(int, int, int, str)

    # Asked when a word is typed: kwargs for ops.syllabify, or None for "off".
    auto_split = None
    # (line, voice) while a word is being typed onto the end of a row: it is
    # not in the document until it is written.
    _adding = None
    # The region a CPU repaint is for, while paintEvent runs -- see _clip_of.
    _paint_region = None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # First, so everything below that sets the viewport up sets this one
        # up: its repaints go to the GPU canvas over it -- see gpu.
        self.setViewport(GPU.GlViewport())
        vp = self.viewport()
        vp.gl_canvas = GPU.lay_over(vp, paint=self.paint_onto, owner=vp,
                                    partial=True)
        self.doc: M.Doc = M.Doc()
        self.mode = "edit"
        self.pos = 0.0
        self.follow = True
        self.cursor = (0, 0, 0)
        self.tap_mode = "all"
        self.selection: set = set()
        # Rows the find bar matches, as (line, voice); `found` is the one
        # it is on. Drawn, never saved.
        self.finds: set = set()
        self.found: tuple | None = None
        self._anchor: tuple = (0, 0)
        self.word_sel: set = set()
        self._word_anchor: tuple | None = None
        self.rows: list[Row] = []
        # line -> (group, first line of its run, last line), from _layout.
        self.runs: dict = {}
        self._key = None
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.viewport().setBackgroundRole(self.backgroundRole())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self.viewport().update())
        self.setFont(T.font(LYRIC_PX, 500))
        self.m = self._metrics()
        self.editor: QLineEdit | None = None
        self._drag: dict | None = None
        self.next_row: tuple | None = None
        # Multiplayer (collab_ui): lines other people hold, line -> (colour,
        # claimed), and where their cursors are, (line, voice) -> (syl, colour).
        self.held: dict = {}
        self.held_at: dict = {}
        # ...and notes: line -> (how many, the text shown on hover), the
        # pill each was drawn in, and more items for the line menu.
        self.noted: dict = {}
        self._note_at: dict = {}
        # What a click on a note pill opens: (line) -> None, set by the
        # multiplayer controller. The pill's own text is only a count.
        self.on_note = None
        self.menu_extra = None
        self._lit_row: tuple | None = None
        self._lit_at = -1
        self._lit_set: set = set()
        self.roman_show = False
        self.roman_detail = "per syllable"
        self.reditor: QLineEdit | None = None
        self._redit_at: tuple | None = None
        self._rom_h = 0.0

    @property
    def tap_adlibs(self) -> bool:
        """The old two-way switch, in terms of the three-way one."""
        return self.tap_mode != self.TAP_LEAD

    @tap_adlibs.setter
    def tap_adlibs(self, on) -> None:
        self.tap_mode = self.TAP_ALL if on else self.TAP_LEAD

    # ------------------------------------------------------------- outside
    def set_doc(self, doc: M.Doc) -> None:
        self.doc = doc
        self.relayout()

    def set_mode(self, mode: str) -> None:
        if mode != "drag":
            self.show_pass(None)
        self.mode = mode
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if mode == "drag"
            else Qt.CursorShape.ArrowCursor)
        self.relayout()

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
        if self.mode != "preview":
            # Outside preview the playhead shows here only as which chips
            # are being sung, and that changes a few times a second, not
            # thirty. Repainting every row on every frame anyway was the
            # largest part of each frame while the song played.
            key = (self.mode, self._live_at(t))
            if key == getattr(self, "_live_key", None):
                return
            self._live_key = key
        else:
            # In preview every frame moves the fill, but only through the
            # rows it is in: the rest look exactly as they did. Repainting
            # all of them was 5ms a frame, which held the editor to about
            # 110 frames a second on a 240Hz screen.
            was, self._drawn_pos = getattr(self, "_drawn_pos", None), t
            rect = self._chips_between(was, t)
            if rect is not None:
                if not rect.isEmpty():
                    self.viewport().update(rect)
                return
        self.viewport().update()

    def _chips_between(self, a, b) -> QRect | None:
        """Where the list looks different at `b` than it did at `a`: the rows
        with a chip whose time overlaps the stretch between them, as one
        rect. Exact, because a chip is drawn by where the playhead is against
        its own start and end only -- one that does not overlap the stretch
        was ahead of it, or behind it, at both. None when that stretch is no
        frame's worth -- a seek, a jump -- and everything should be redrawn."""
        if a is None or not 0.0 <= b - a < 0.5:
            return None
        off = self.verticalScrollBar().value()
        W = self.viewport().width()
        out = QRect()
        for r in self.rows:
            g = self.doc.group(r.line, r.voice)
            if g is None:
                continue
            for s in g.syls:
                if s.timed and s.start <= b and (s.end or s.start) >= a:
                    out = out.united(QRect(0, int(r.top - off) - 6, W,
                                           int(r.height) + 12))
                    break
        return out

    def _live_at(self, t: float) -> tuple:
        """Every syllable `_chip` would draw as being sung at `t`."""
        out = []
        for r in self.rows:
            g = self.doc.group(r.line, r.voice)
            if g is None:
                continue
            for k, s in enumerate(g.syls):
                if s.timed and s.start <= t <= (s.end or s.start):
                    out.append((r.line, r.voice, k))
        return tuple(out)

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
               id(self.doc), self._doc_stamp(), tuple(self.doc.parts))
        if key == self._key:
            return
        self.runs = {i: (n, at, at + size - 1)
                     for n, at, size in ops.part_runs(self.doc)
                     for i in range(at, at + size)}
        fm = QFontMetricsF(self.font())
        m = self.m = self._metrics()
        chip_h = fm.height() + m["pad_y"] * 2
        rfm = QFontMetricsF(self.roman_font())
        rom_h = self._rom_h = rfm.height() + T.px(6)
        rom_on = self.roman_show and self.mode != "preview"
        room = max(120.0, width - m["gutter"] - m["indent"] - 16.0
                   - (m["times"] if self.mode != "edit" else 0.0))
        rows: list[Row] = []
        y = 4.0
        for i, ln in enumerate(self.doc.lines):
            for v, g in enumerate(ln.groups()):
                row = Row(i, v, y)
                need = rom_on and SL.needs_roman(g.text())
                row.roman = ("" if not need else
                             "line" if self.roman_detail == "per line" else "syl")
                ch = chip_h + (rom_h if row.roman == "syl" else 0.0)
                left = m["gutter"] + (m["indent"] if v else 0.0)
                x, used = 0.0, 1

                def wide_of(k):
                    w = fm.horizontalAdvance(g.syls[k].text) + m["pad_x"] * 2
                    if row.roman == "syl" and SL.needs_roman(g.syls[k].text):
                        r = g.syls[k].roman.strip() or "+"
                        w = max(w, rfm.horizontalAdvance(r) + m["pad_x"] * 2
                                + T.px(6))
                    return w
                for word in g.words():
                    wide = sum(wide_of(k) for k in word)
                    if x and x + wide > room:
                        x, used = 0.0, used + 1
                    for k in word:
                        w = wide_of(k)
                        row.chips.append(QRectF(
                            left + x, y + (used - 1) * (ch + 3), w, ch))
                        x += w
                    x += WORD_GAP
                if not g.syls:
                    row.chips = []
                else:
                    pw = max(T.px(24), ch * 0.9)
                    if x and x + pw > room:
                        x, used = 0.0, used + 1
                    row.plus = QRectF(left + x, y + (used - 1) * (ch + 3),
                                      pw, ch)
                row.lines_used = used
                row.height = used * (ch + 3) + m["row_gap"]
                # A line reading with syllables still unread is shown in the
                # per-syllable view as well; otherwise it is there and
                # nothing on screen says so.
                show_line = row.roman == "line" or (
                    row.roman == "syl" and g.roman.strip() and any(
                        SL.needs_roman(s.text) and not s.roman.strip()
                        for s in g.syls))
                if show_line:
                    said = g.roman_text() or "+ reading for this line"
                    lw = min(room, rfm.horizontalAdvance(said) + T.px(24))
                    row.rline = QRectF(left, y + used * (ch + 3), lw, rom_h)
                    row.height += rom_h + T.px(4)
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
        rom = self.roman_show and self.mode != "preview"
        return (rom, self.roman_detail) + tuple(
            (ln.agent, len(ln.bg),
             tuple(tuple(s.text for s in g.syls) for g in ln.groups()),
             tuple((g.roman, tuple(s.roman for s in g.syls))
                   for g in ln.groups()) if rom else ())
            for ln in self.doc.lines)

    def roman_font(self) -> QFont:
        return T.font(13 if T.LOOK == "new" else 12, 600 if T.LOOK == "new"
                      else 500)

    def resizeEvent(self, ev) -> None:                    # noqa: N802 (Qt name)
        super().resizeEvent(ev)
        self._key = None
        self._layout()
        self._place_editor()
        self._place_reditor()

    # -------------------------------------------------------------- drawing
    def _note_pill(self, p, r: Row, off: float, n: int) -> None:
        """'✎ n' just past the line's last word: somebody left a note."""
        end = r.plus if r.plus is not None else (r.chips[-1] if r.chips else None)
        if end is None:
            return
        box = QRectF(end.right() + T.px(8), end.top() - off + 2,
                     T.px(34), end.height() - 4)
        self._note_at[r.line] = box.translated(0, off)
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 212, 94, 210))
        p.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        p.setPen(QPen(QColor(20, 20, 24), 1))
        p.setFont(T.font(11, 700))
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), f"✎ {n}")
        p.restore()

    def viewportEvent(self, ev) -> bool:                  # noqa: N802 (Qt name)
        from PyQt6.QtCore import QEvent
        if ev.type() == QEvent.Type.ToolTip and self.noted:
            y = ev.pos().y() + self.verticalScrollBar().value()
            for line, box in self._note_at.items():
                if line in self.noted and box.contains(float(ev.pos().x()), float(y)):
                    from PyQt6.QtWidgets import QToolTip
                    QToolTip.showText(ev.globalPos(), self.noted[line][1], self)
                    return True
        return super().viewportEvent(ev)

    def paintEvent(self, _ev) -> None:                    # noqa: N802 (Qt name)
        canvas = self.viewport().gl_canvas
        if GPU.live(canvas):
            # Asked by Qt itself -- a scroll, an expose -- rather than by an
            # update, which goes straight to the canvas.
            canvas.update()
            return
        self._paint_region = _ev.region()
        try:
            self.paint_onto(QPainter(self.viewport()))
        finally:
            self._paint_region = None

    def paint_onto(self, p: QPainter) -> None:
        """The list, into `p` -- the viewport's own painter or its GPU
        canvas's -- which is ended here."""
        try:
            self._paint(p)
        finally:
            p.end()

    def _clip_of(self, p: QPainter) -> QRectF | None:
        """The part of the viewport this paint can change, or None for all
        of it: the canvas's clip on the GPU, the repaint region on the CPU.
        Rows wholly outside it are not drawn -- they would be clipped away."""
        if p.hasClipping():
            return p.clipBoundingRect()
        reg = self._paint_region
        if reg is None or reg.isEmpty():
            return None
        return QRectF(reg.boundingRect())

    def _paint(self, p: QPainter) -> None:
        self._layout()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        W, H = self.viewport().width(), self.viewport().height()
        p.fillRect(0, 0, W, H, BG)
        off = self.verticalScrollBar().value()
        fm = QFontMetricsF(self.font())
        small = T.font(11, 500)
        clip = self._clip_of(p)
        for r in self.rows:
            top = r.top - off
            if top + r.height < -20 or top > H + 20:
                continue
            if clip is not None and (top + r.height < clip.top() - 6
                                     or top > clip.bottom() + 6):
                continue
            self._row(p, r, top, W, fm, small)
        if not self.rows:
            p.setPen(QPen(DIM, 1))
            p.drawText(QRectF(0, 0, W, H), int(Qt.AlignmentFlag.AlignCenter),
                       "no lines yet")
        spot = (self._drag or {}).get("spot")
        if spot and (self._drag or {}).get("live"):
            off = self.verticalScrollBar().value()
            if spot.get("mark"):
                x, top, tall = spot["mark"]
                p.setPen(QPen(T.q(T.LEAD), 2))
                p.drawLine(QPointF(x, top - off - 3),
                           QPointF(x, top - off + tall + 3))
                p.setBrush(T.q(T.LEAD))
                p.drawEllipse(QPointF(x, top - off - 4), 3.0, 3.0)
                p.setBrush(Qt.BrushStyle.NoBrush)
            else:
                y = spot["y"] - off
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
            p.fillRect(QRectF(0, top - 2, 3, r.height), T.q(T.LEAD))
        key = (r.line, r.voice)
        if key in self.finds:
            p.fillRect(QRectF(0, top - 2, W, r.height),
                       T.q(T.LEAD, 90 if key == self.found else 40))
        hold = self.held.get(r.line)
        if hold is not None:
            # Somebody else's: their colour across it and down its right edge,
            # stronger where they claimed it than where they are just on it.
            hue = QColor(hold[0])
            hue.setAlpha(46 if hold[1] else 24)
            p.fillRect(QRectF(0, top - 2, W, r.height), hue)
            hue.setAlpha(230)
            p.fillRect(QRectF(W - 4, top - 2, 4, r.height), hue)
        p.setPen(QPen(RULE, 1))
        p.drawLine(QPointF(0, top + r.height - 3), QPointF(W, top + r.height - 3))
        self._run_bar(p, r, top, ln)

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
        for w, run in enumerate(g.words()):
            run = [k for k in run if k < len(r.chips)]
            if not run:
                continue
            self._word(p, r, g, run, off, ink, fm)
            if (r.line, r.voice, w) in self.word_sel and len(self.word_sel) > 1:
                box = r.chips[run[0]].translated(0, -off)
                for k in run[1:]:
                    box = box.united(r.chips[k].translated(0, -off))
                p.setPen(QPen(T.q(T.LEAD), 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(box.adjusted(-1.5, -1.5, 1.5, 1.5),
                                  T.R_CHIP + 1, T.R_CHIP + 1)

        theirs = self.held_at.get((r.line, r.voice))
        if theirs is not None and 0 <= theirs[0] < len(r.chips):
            p.setPen(QPen(QColor(theirs[1]), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.chips[theirs[0]].translated(0, -off)
                              .adjusted(-3, -3, 3, 3), T.R_CHIP + 2, T.R_CHIP + 2)

        if (r.plus is not None and self.mode != "preview"
                and self._adding != (r.line, r.voice)):
            self._plus(p, r.plus.translated(0, -off))

        if r.voice == 0 and r.line in self.noted:
            self._note_pill(p, r, off, self.noted[r.line][0])

        if r.rline is not None:
            self._line_reading(p, r, g, off)

        if (self.mode == "drag" and self._lit_row is None
                and (r.line, r.voice) == self.next_row and r.chips):
            box = r.chips[0].translated(0, -off)
            for c in r.chips[1:]:
                box = box.united(c.translated(0, -off))
            pen = QPen(T.q(T.LEAD), 1.6)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(-4, -3, 4, 3),
                              T.R_CHIP + 3, T.R_CHIP + 3)

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

    def _run_bar(self, p, r: Row, top: float, ln) -> None:
        """The bracket down the gutter beside a run of a group.

        One unbroken bar from the run's first row to its last, in the group's
        colour -- bright where the line is timed, faint where it is still
        waiting for its one tap, so the choruses left to do can be seen from
        a scroll down the song.
        """
        run = self.runs.get(r.line)
        if run is None:
            return
        n, first, last = run
        hue = QColor(PART_HUES[n % len(PART_HUES)])
        hue.setAlpha(230 if ops._full(ln) else 110)
        y0 = top - 2 + (T.px(6) if (r.line, r.voice) == (first, 0) else 0)
        y1 = top + r.height - 2
        if r.line == last and r.voice == len(ln.bg):
            y1 -= T.px(9)
        p.fillRect(QRectF(T.px(42), y0, T.px(3), max(1.0, y1 - y0)), hue)

    def _plus(self, p, box: QRectF) -> None:
        """The end-of-line "+": a new word on this line, no menu needed."""
        p.save()
        pen = QPen(T.q(T.FAINT), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box.adjusted(0, 1, 0, -1), T.R_CHIP, T.R_CHIP)
        p.setFont(self.font())
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), "+")
        p.restore()

    def _plus_at(self, x: float, y: float):
        yy = y + self.verticalScrollBar().value()
        pt = QPointF(x, yy)
        for r in self.rows:
            if r.plus is not None and r.plus.contains(pt):
                return r
        return None

    def add_word_at_end(self, r: Row) -> None:
        """Open a box where the "+" was. The word joins the row on commit."""
        g = self.doc.group(r.line, r.voice)
        if g is None or r.plus is None:
            return
        self.commit_edit()
        self._edit_wide = False
        self._adding = (r.line, r.voice)
        self._edit_at = (r.line, r.voice, len(g.syls))
        self.cursor = (r.line, r.voice, max(0, len(g.syls) - 1))
        ed = _WordBox("", self.viewport())
        ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ed.setFont(self.font())
        ed.setStyleSheet(_box_style(self.font()))
        ed.done.connect(self._word_done)
        ed.editingFinished.connect(self.commit_edit)
        self.editor = ed
        self._place_editor()
        ed.show()
        ed.setFocus()
        self.viewport().update()

    def _commit_added(self, text: str) -> None:
        line, voice = self._adding
        self._adding = None
        g = self.doc.group(line, voice)
        if g is None or not text.strip():
            return
        k = len(g.syls)
        self.will_edit.emit()
        said = ops.insert_syllable(self.doc, line, voice, k, text)
        if said is None:
            return
        # insert_syllable makes it a word of its own; typed text may hold
        # spaces, which set_text turns into words.
        ops.set_text(self.doc, line, voice, k, text)
        said = self._auto_cut(line, voice, k, len(g.syls) - k - 1) or said
        self.edited.emit(said)

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
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(RULE, 1))
            p.drawRoundedRect(whole, T.R_CHIP, T.R_CHIP)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for n, (k, box) in enumerate(part):
                self._chip(p, box, g.syls[k],
                           (r.line, r.voice, k) == self.cursor, ink, fm,
                           inside=len(part) > 1,
                           lit=self._lit(r.line, r.voice, k),
                           roman=r.roman == "syl",
                           reads=SL.needs_roman(g.syls[k].text))
                if n < len(part) - 1:
                    p.setPen(QPen(RULE if T.LOOK == "new" else BG, 1))
                    p.drawLine(QPointF(box.right(), box.top() + 3),
                               QPointF(box.right(), box.bottom() - 3))

    def show_pass(self, row: tuple | None, at: int = -1, lit=()) -> None:
        """Light a row up as the bar is dragged over it.

        The words are where the eye is during a pass -- not on the bar, which
        is under the hand and needs no reading. So the bar says where the
        pointer has got to and the lyric shows it, which is the only reason
        this widget knows a drag is happening at all.
        """
        self._lit_row = tuple(row) if row else None
        self._lit_at = at
        self._lit_set = set(lit)
        self.viewport().update()

    def _lit(self, line: int, voice: int, k: int) -> int:
        """How a chip is showing in a drag: 2 under the pointer, 1 behind it."""
        if self._lit_row != (line, voice):
            return 0
        if k == self._lit_at:
            return 2
        return 1 if k in self._lit_set else 0

    def _chip(self, p, box: QRectF, s: M.Syl, is_cursor: bool, ink, fm,
              inside: bool = False, lit: int = 0, roman: bool = False,
              reads: bool = True) -> None:
        full = box
        if roman:
            box = QRectF(box.x(), box.y(), box.width(),
                         box.height() - self._rom_h)
        live = s.timed and s.start <= self.pos <= (s.end or s.start)
        sung = s.timed and (s.end or s.start) < self.pos
        # The word being sung and the word selected used to be the same solid
        # accent, so while the song played the selection could not be told
        # from the voice going past it. The selection keeps the solid fill --
        # it is what the keys act on -- and the playing word is the dim ink
        # with an accent rim round it.
        fill = (CHIP_CURSOR if is_cursor else CHIP_PLAYING if live else None)
        playing = (live and not is_cursor and not lit
                   and self.mode != "preview")
        if self.mode == "preview":
            fill = CHIP_SUNG if sung else (CHIP_LIVE if live else None)
        if lit:
            fill = CHIP_SWEEP if lit == 2 else CHIP_SWEPT
            ink = ON_ACCENT if lit == 2 else ink
        if fill is not None:
            p.setBrush(fill)
            p.setPen(Qt.PenStyle.NoPen)
            radius = 0 if inside else 3
            p.drawRoundedRect(box, radius, radius)
            p.setBrush(Qt.BrushStyle.NoBrush)
        if playing:
            p.setPen(QPen(CHIP_LIVE, 1.4))
            p.drawRoundedRect(box.adjusted(0.7, 0.7, -0.7, -0.7), 3, 3)
        if is_cursor:
            p.setPen(QPen(QColor(255, 255, 255, 110), 1.4))
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        if self.mode == "preview" and live and s.end and s.end > s.start:
            k = (self.pos - s.start) / (s.end - s.start)
            p.setBrush(CHIP_SUNG)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(box.left(), box.top(),
                                     box.width() * max(0.0, min(1.0, k)),
                                     box.height()), 3, 3)
            p.setBrush(Qt.BrushStyle.NoBrush)
        if fill is not None and roman:
            p.setBrush(fill)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(QRectF(full.x(), box.bottom() - 1, full.width(),
                              full.bottom() - box.bottom() + 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
        on_fill = T.LOOK == "new" and fill is not None and (
            is_cursor or lit == 2 or fill is CHIP_LIVE)
        p.setPen(QPen(ON_ACCENT if on_fill else
                      ink if s.timed or self.mode == "edit" else DIM, 1))
        p.drawText(box, int(Qt.AlignmentFlag.AlignCenter), s.text)
        if roman and reads:
            self._reading(p, QRectF(full.x(), box.bottom(), full.width(),
                                    full.bottom() - box.bottom()),
                          s.roman.strip(), on_fill or (
                              fill is not None and T.LOOK != "new"
                              and is_cursor))

    def _reading(self, p, box: QRectF, text: str, dark: bool) -> None:
        """A syllable's reading under it, or a dashed + where it has none."""
        p.save()
        p.setFont(self.roman_font())
        inner = box.adjusted(T.px(3), 0, -T.px(3), -T.px(3))
        if text:
            p.setPen(QPen(ON_ACCENT if dark else T.q(T.MUTE), 1))
            p.drawText(inner, int(Qt.AlignmentFlag.AlignCenter), text)
        else:
            pen = QPen(ON_ACCENT if dark else T.q(T.FAINT), 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            fm = QFontMetricsF(p.font())
            w = max(fm.horizontalAdvance("+") + T.px(10), T.px(20))
            pill = QRectF(inner.center().x() - w / 2, inner.y(), w,
                          inner.height())
            p.drawRoundedRect(pill, 3, 3)
            p.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), "+")
        p.restore()

    def _line_reading(self, p, r: Row, g, off: float) -> None:
        """The whole line's reading, under its words, as amll-ttml-db keeps
        them -- or an invitation to type one."""
        box = r.rline.translated(0, -off)
        said = g.roman_text()
        p.save()
        p.setFont(self.roman_font())
        if said:
            p.setPen(QPen(T.q(T.MUTE), 1))
            p.drawText(box.adjusted(T.px(8), 0, 0, 0),
                       int(Qt.AlignmentFlag.AlignVCenter
                           | Qt.AlignmentFlag.AlignLeft), said)
        else:
            pen = QPen(T.q(T.FAINT), 1)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(box.adjusted(0, 1, 0, -1), 6, 6)
            p.drawText(box, int(Qt.AlignmentFlag.AlignCenter),
                       "+ reading for this line")
        p.restore()

    # ----------------------------------------------------------- readings
    def _roman_hit(self, x: float, y: float):
        """(row, syllable index or -1 for the line's reading), or None."""
        yy = y + self.verticalScrollBar().value()
        pt = QPointF(x, yy)
        for r in self.rows:
            if not r.top - 2 <= yy <= r.top + r.height:
                continue
            if r.rline is not None and r.rline.contains(pt):
                return r, -1
            if r.roman == "syl":
                g = self.doc.group(r.line, r.voice)
                for k, rect in enumerate(r.chips):
                    if (rect.contains(pt) and g is not None
                            and k < len(g.syls)
                            and SL.needs_roman(g.syls[k].text)
                            and pt.y() >= rect.bottom() - self._rom_h):
                        return r, k
            return None
        return None

    def roman_order(self) -> list:
        """Every place a reading can be typed, in the order they are drawn."""
        out = []
        for r in self.rows:
            if r.roman == "line":
                out.append((r.line, r.voice, -1))
            elif r.roman == "syl":
                g = self.doc.group(r.line, r.voice)
                if g is not None:
                    out += [(r.line, r.voice, k) for k in range(len(g.syls))
                            if SL.needs_roman(g.syls[k].text)]
        return out

    def edit_roman(self, line: int, voice: int, k: int) -> None:
        """A box where the reading is, for typing it. Enter keeps it, Tab
        keeps it and moves to the next one, Esc leaves it as it was."""
        self.commit_roman()
        g = self.doc.group(line, voice)
        if g is None or (k >= 0 and not 0 <= k < len(g.syls)):
            return
        ed = _ReadingBox(g.roman_text() if k < 0 else g.syls[k].roman,
                         self.viewport())
        ed.setFont(self.roman_font())
        ed.setStyleSheet(_box_style(self.roman_font()))
        ed.setAlignment(Qt.AlignmentFlag.AlignLeft if k < 0
                        else Qt.AlignmentFlag.AlignCenter)
        ed.selectAll()
        ed.done.connect(self._roman_done)
        self.reditor, self._redit_at = ed, (line, voice, k)
        self._place_reditor()
        ed.show()
        ed.setFocus()

    def _place_reditor(self) -> None:
        if not self.reditor or not self._redit_at:
            return
        line, voice, k = self._redit_at
        off = self.verticalScrollBar().value()
        for r in self.rows:
            if (r.line, r.voice) != (line, voice):
                continue
            if k < 0 and r.rline is not None:
                box = r.rline.translated(0, -off)
                self.reditor.setGeometry(int(box.x()), int(box.y()),
                                         max(T.px(320), int(self.viewport()
                                             .width() * 0.6)), int(box.height()))
            elif 0 <= k < len(r.chips):
                box = r.chips[k].translated(0, -off)
                self.reditor.setGeometry(int(box.x()) - T.px(4),
                                         int(box.bottom() - self._rom_h),
                                         max(T.px(64), int(box.width()) + T.px(8)),
                                         int(self._rom_h))
            return

    def _roman_done(self, how: str) -> None:
        ed, at = self.reditor, self._redit_at
        if ed is None or at is None:
            return
        self.reditor, self._redit_at = None, None
        text = ed.text()
        ed.deleteLater()
        self.setFocus()
        if how != "cancel":
            line, voice, k = at
            g = self.doc.group(line, voice)
            was = (g.roman_text() if k < 0 else g.syls[k].roman) if g else ""
            if g is not None and text.strip() != (was or "").strip():
                self.roman_edited.emit(line, voice, k, text)
        if how in ("next", "back"):
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._roman_step(at, how == "back"))

    def _roman_step(self, at: tuple, back: bool) -> None:
        self._layout()
        order = self.roman_order()
        if at not in order:
            return
        n = order.index(at) + (-1 if back else 1)
        if 0 <= n < len(order):
            line, voice, k = order[n]
            row = self.row_for(line, voice)
            if row is not None:
                self.reveal_row(row)
            self.edit_roman(line, voice, k)

    def commit_roman(self) -> None:
        if self.reditor is not None:
            self._roman_done("keep")

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
    def word_order(self) -> list:
        """Every word in the document, in the order it is drawn."""
        out = []
        for r in self.rows:
            g = self.doc.group(r.line, r.voice)
            if g is None:
                continue
            out += [(r.line, r.voice, w) for w in range(len(g.words()))]
        return out

    def word_at(self, line: int, voice: int, syl: int):
        """Which word a syllable belongs to."""
        g = self.doc.group(line, voice)
        if g is None:
            return None
        for w, run in enumerate(g.words()):
            if syl in run:
                return (line, voice, w)
        return None

    def selected_words(self) -> list:
        return sorted(p for p in self.word_sel
                      if 0 <= p[0] < len(self.doc.lines))

    def picked_syllable(self):
        """(line, voice, k) when what is picked is one syllable of a word.

        A click on a syllable picks its word as well, for dragging -- so
        Delete read that as the word, and pointing at "mance" to take it out
        took "romance" with it. One word picked, with the cursor on one of
        several syllables in it, is that syllable. A word picked on its own
        is still the whole of it, and so is any run of words.
        """
        if len(self.word_sel) != 1:
            return None
        line, voice, k = self.cursor
        if self.word_at(line, voice, k) not in self.word_sel:
            return None
        g = self.doc.group(line, voice)
        run = next((r for r in g.words() if k in r), []) if g else []
        return (line, voice, k) if len(run) > 1 else None

    def _word_drop_at(self, x: float, y: float):
        """Where a dragged word would go: (row, index among that row's words)."""
        spot = self._drop_at(y)
        if spot is None:
            return None
        row = spot["row"]
        g = self.doc.group(row.line, row.voice)
        if g is None:
            return None
        runs = g.words()
        best, at, mark = 1e9, len(runs), None
        for w, run in enumerate(runs):
            if run[0] >= len(row.chips):
                break
            box = row.chips[run[0]]
            for edge, index in ((box.left(), w),
                                (row.chips[min(run[-1], len(row.chips) - 1)]
                                 .right(), w + 1)):
                if abs(x - edge) < best:
                    best, at, mark = abs(x - edge), index, (edge, box.top(),
                                                           box.height())
        if mark is None and row.chips:
            mark = (row.chips[-1].right(), row.chips[-1].top(),
                    row.chips[-1].height())
        return {"row": row, "at": at, "mark": mark}

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
        if drag.get("words"):
            row = spot["row"]
            self._edit(lambda: ops.move_words(self.doc, drag["words"],
                                              row.line, row.voice, spot["at"]))
            self.word_sel = set()
            return
        line, voice = drag["row"]
        row, after = spot["row"], spot["after"]
        if voice == 0:
            to = row.line + (1 if after else 0)
            self._edit(lambda: ops.reorder_lines(self.doc, [line], to))
            return
        if row.voice == 0:
            self._edit(lambda: ops.move_backing(
                self.doc, line, voice, row.line,
                None if after else 0))
            return
        at = (row.voice - 1) + (1 if after else 0)
        if row.line == line and at > voice - 1:
            at -= 1
        self._edit(lambda: ops.move_backing(self.doc, line, voice,
                                            row.line, at))

    # ---------------------------------------------------------- hit testing
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

    # ------------------------------------------------------------ drag sync
    def row_for(self, line: int, voice: int):
        self._layout()
        for r in self.rows:
            if (r.line, r.voice) == (line, voice):
                return r
        return None

    def row_order(self) -> list:
        """Every row, as (line, voice), in the order it is drawn."""
        self._layout()
        return [(r.line, r.voice) for r in self.rows]

    def row_full(self, line: int, voice: int) -> bool:
        """Has every syllable of this row a time? An empty row counts."""
        g = self.doc.group(line, voice)
        if g is None:
            return True
        return all(s.timed for s in g.syls)

    def step_row(self, delta: int, frm: tuple | None = None) -> tuple | None:
        order = self.row_order()
        if not order:
            return None
        here = frm or self.next_row or self.cursor[:2]
        try:
            at = order.index(here)
        except ValueError:
            at = 0
        want = at + delta
        return order[want] if 0 <= want < len(order) else None

    def next_to_time(self, after: tuple | None = None) -> tuple | None:
        """The first row past `after` that still has a syllable without a time.

        What "next" means once a row is done. It walks the DRAWN order, which
        puts a line's ad-libs directly after the words they answer -- so a
        line with a backing vocal hands the drag straight back to the same
        line, which is the cue to play it again. Everything already timed is
        stepped over, so picking the work back up after a break lands where it
        was left rather than at the top.
        """
        order = self.row_order()
        if not order:
            return None
        start = 0
        if after is not None and after in order:
            start = order.index(after) + 1
        for row in order[start:]:
            if not self.row_full(*row):
                return row
        return None

    def arm(self, line: int, voice: int) -> bool:
        """Say which row the next drag is for, and put the cursor in it."""
        g = self.doc.group(line, voice)
        if g is None:
            return False
        self.next_row = (line, voice)
        self.select([(line, voice)])
        if g.syls:
            self.set_cursor(line, voice, 0)
        else:
            row = self.row_for(line, voice)
            if row is not None:
                self.reveal_row(row)
        self.armed.emit(line, voice)
        self.viewport().update()
        return True

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, ev) -> None:                # noqa: N802 (Qt name)
        self.commit_edit()
        self.commit_roman()
        if (self.noted and self.on_note is not None
                and ev.button() == Qt.MouseButton.LeftButton):
            x = float(ev.position().x())
            y = float(ev.position().y()) + self.verticalScrollBar().value()
            for line, box in self._note_at.items():
                if line in self.noted and box.contains(x, y):
                    self.on_note(line)
                    return
        got = self._roman_hit(ev.position().x(), ev.position().y())
        if got is not None and ev.button() == Qt.MouseButton.LeftButton:
            r, k = got
            self.select([(r.line, r.voice)])
            self.edit_roman(r.line, r.voice, k)
            self.viewport().update()
            return
        if (ev.button() == Qt.MouseButton.LeftButton
                and self.mode != "preview"):
            plus = self._plus_at(ev.position().x(), ev.position().y())
            if plus is not None:
                self.select([(plus.line, plus.voice)])
                self.add_word_at_end(plus)
                return
        r, k = self._hit(ev.position().x(), ev.position().y())
        if r is None:
            return
        if self.mode == "drag" and ev.button() == Qt.MouseButton.LeftButton:
            self.arm(r.line, r.voice)
            if k is not None:
                self.set_cursor(r.line, r.voice, k)
            return
        alt = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
        if (ev.button() == Qt.MouseButton.LeftButton
                and self.mode != "preview" and (k is None or alt)):
            self._drag = {"row": (r.line, r.voice), "y0": ev.position().y(),
                          "live": False, "spot": None}
        mods = ev.modifiers()
        here = (r.line, r.voice)
        word_here = (self.word_at(r.line, r.voice, k) if k is not None
                     else None)
        # Pressing on a word that is already one of several picked keeps
        # them all, the way every list does -- it is how a run of words is
        # picked UP. It used to drop everything but the one pressed on, so a
        # selection could be made and acted on from the keys but never
        # dragged. A press that turns out not to be a drag still narrows it
        # to the one word, on release.
        keep = (word_here is not None and len(self.word_sel) > 1
                and word_here in self.word_sel
                and not mods & (Qt.KeyboardModifier.ShiftModifier
                                | Qt.KeyboardModifier.ControlModifier)
                and not alt)
        if keep:
            self.cursor = (r.line, r.voice, k)
            self.cursor_changed.emit(*self.cursor)
            if ev.button() == Qt.MouseButton.LeftButton:
                self._drag = {"words": self.selected_words(),
                              "row": here, "y0": ev.position().y(),
                              "x0": ev.position().x(), "live": False,
                              "spot": None, "narrow": word_here}
            elif ev.button() == Qt.MouseButton.RightButton:
                self.chip_menu(ev.globalPosition().toPoint())
            self.viewport().update()
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
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
        if k is None:
            self.word_sel = set()
            if here in self.selection:
                g = self.doc.group(r.line, r.voice)
                if g is not None and g.syls:
                    self.cursor = (r.line, r.voice, 0)
                    self.cursor_changed.emit(*self.cursor)
        if k is not None:
            self.cursor = (r.line, r.voice, k)
            here = self.word_at(r.line, r.voice, k)
            if here is not None and ev.button() == Qt.MouseButton.LeftButton:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    order = self.word_order()
                    try:
                        a = order.index(self._word_anchor or here)
                        b = order.index(here)
                    except ValueError:
                        a = b = order.index(here)
                    lo, hi = sorted((a, b))
                    self.word_sel = set(order[lo:hi + 1])
                elif mods & Qt.KeyboardModifier.ControlModifier:
                    self.word_sel ^= {here}
                    self._word_anchor = here
                elif alt:
                    self.word_sel = {here}
                    self._word_anchor = here
                else:
                    self.word_sel = {here}
                    self._word_anchor = here
                    self._drag = {"words": sorted(self.word_sel),
                                  "row": (r.line, r.voice), "y0":
                                  ev.position().y(), "x0": ev.position().x(),
                                  "live": False, "spot": None}
                if not alt and mods & (Qt.KeyboardModifier.ShiftModifier
                                       | Qt.KeyboardModifier.ControlModifier):
                    self._drag = {"words": sorted(self.word_sel),
                                  "row": (r.line, r.voice),
                                  "y0": ev.position().y(),
                                  "x0": ev.position().x(),
                                  "live": False, "spot": None}
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
        moved = max(abs(y - self._drag["y0"]),
                    abs(ev.position().x() - self._drag.get("x0", 0.0))
                    if self._drag.get("words") else 0.0)
        if not self._drag["live"] and moved > 6:
            self._drag["live"] = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._drag["live"]:
            self._drag["spot"] = (
                self._word_drop_at(ev.position().x(), y)
                if self._drag.get("words") else self._drop_at(y))
            self.viewport().update()

    def mouseReleaseEvent(self, _ev) -> None:             # noqa: N802 (Qt name)
        drag, self._drag = self._drag, None
        if drag is None:
            return
        self.unsetCursor()
        if drag["live"] and drag["spot"]:
            self._apply_drop(drag, drag["spot"])
        elif drag.get("narrow") is not None:
            line, voice, _w = drag["narrow"]
            self.word_sel = {drag["narrow"]}
            self._word_anchor = drag["narrow"]
            self.select([(line, voice)])
        self.viewport().update()

    def mouseDoubleClickEvent(self, ev) -> None:          # noqa: N802 (Qt name)
        r, k = self._hit(ev.position().x(), ev.position().y())
        if r is None:
            return
        if self.mode == "drag":
            s = (self.doc.group(r.line, r.voice) or M.Group()).syls
            when = (s[k].start if k is not None and k < len(s)
                    and s[k].timed else self._span(r)[0])
            if when is not None:
                self.seek_to.emit(when)
            return
        if k is None:
            a, _b = self._span(r)
            if a is not None:
                self.seek_to.emit(a)
            return
        self.edit_chip(r, k)

    def wheelEvent(self, ev) -> None:                     # noqa: N802 (Qt name)
        self.commit_edit()
        self.commit_roman()
        super().wheelEvent(ev)

    # -------------------------------------------------------- inline editing
    def edit_chip(self, r: Row, k: int, wide: bool = False) -> None:
        """A text box over the chip, committing on Enter and on losing focus."""
        g = self.doc.group(r.line, r.voice)
        if g is None or not 0 <= k < len(g.syls):
            return
        self.commit_edit()
        self._edit_wide = bool(wide)
        self.cursor = (r.line, r.voice, k)
        ed = _WordBox(g.syls[k].text, self.viewport())
        if wide:
            ed.setPlaceholderText("type the line — spaces make the words")
        else:
            ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ed.setFont(self.font())
        ed.setStyleSheet(_box_style(self.font()))
        ed.selectAll()
        ed.done.connect(self._word_done)
        ed.editingFinished.connect(self.commit_edit)
        self.editor = ed
        self._edit_at = (r.line, r.voice, k)
        self._place_editor()
        ed.show()
        ed.setFocus()

    def _place_editor(self) -> None:
        """Sit the box over the chip -- or across the row, for a whole line.

        A chip-wide box is right for correcting one syllable and useless for
        typing a line into: it is sixty-odd pixels, and a lyric line is not.
        `_edit_wide` says which this is, and a new line always asks for the
        wide one, because there is nothing there yet to be narrow about.
        """
        if not self.editor:
            return
        line, voice, k = self._edit_at
        if self._adding:
            for r in self.rows:
                if (r.line, r.voice) == self._adding and r.plus is not None:
                    box = r.plus.translated(0, -self.verticalScrollBar().value())
                    self.editor.setGeometry(int(box.left()), int(box.top()),
                                            max(90, int(box.width()) + 60),
                                            int(box.height()))
                    return
            return
        for r in self.rows:
            if (r.line, r.voice) == (line, voice) and k < len(r.chips):
                box = r.chips[k].translated(0, -self.verticalScrollBar().value())
                if getattr(self, "_edit_wide", False):
                    room = (self.viewport().width() - int(box.left())
                            - int(self.m["times"] if self.mode != "edit" else 0)
                            - 16)
                    self.editor.setGeometry(int(box.left()), int(box.top()),
                                            max(240, room), int(box.height()))
                else:
                    self.editor.setGeometry(int(box.left()), int(box.top()),
                                            max(60, int(box.width()) + 40),
                                            int(box.height()))
                return

    def edit_line(self, line: int, voice: int = 0) -> None:
        """Open a line-wide box on a line's first chip, everything selected.

        Wide, because what goes in here is a LINE. Spaces in it make the
        words, so the whole thing can be typed in one go -- which is the
        point of the box appearing by itself when a line is inserted.
        """
        self.relayout()
        for r in self.rows:
            if r.line == line and r.voice == voice and r.chips:
                self.edit_chip(r, 0, wide=True)
                if self.editor is not None:
                    self.editor.selectAll()
                return

    def _word_done(self, how: str) -> None:
        """Enter keeps what was typed and Esc does not; either way the box
        goes, and the keys come back to the list."""
        if how == "cancel" and self.editor is not None:
            ed, self.editor = self.editor, None
            self._edit_wide = False
            self._adding = None
            ed.hide()
            ed.deleteLater()
        else:
            self.commit_edit()
        self.setFocus()
        self.viewport().update()

    def commit_edit(self) -> None:
        ed, self.editor = self.editor, None
        self._edit_wide = False
        if ed is None:
            return
        text = ed.text()
        # Hidden now, not when the deferred delete comes round: until then it
        # sat over the chip it had just rewritten, the old text in the box
        # and the new one on the chip beside it.
        ed.hide()
        ed.deleteLater()
        if self._adding:
            self._commit_added(text)
            self.viewport().update()
            return
        line, voice, k = self._edit_at
        g = self.doc.group(line, voice)
        if g is None or not 0 <= k < len(g.syls) or text == g.syls[k].text:
            return
        self.will_edit.emit()
        before = len(g.syls)
        said = ops.set_text(self.doc, line, voice, k, text) or "edited"
        said = self._auto_cut(line, voice, k, len(g.syls) - before) or said
        if 0 <= line < len(self.doc.lines):
            ln = self.doc.lines[line]
            if voice and 0 < voice <= len(ln.bg) and not ln.bg[voice - 1].syls:
                del ln.bg[voice - 1]
                said = "empty ad-lib removed"
            if not ln.lead.syls and not ln.bg:
                del self.doc.lines[line]
                said = "empty line removed"
        self.edited.emit(said)

    def _auto_cut(self, line: int, voice: int, k: int, added: int):
        """Cut the words just typed into syllables, if the setting is on."""
        ask = self.auto_split() if self.auto_split else None
        g = self.doc.group(line, voice)
        if not ask or g is None or not 0 <= k < len(g.syls):
            return None
        runs = g.words()
        first = next((w for w, run in enumerate(runs) if k in run), None)
        last = next((w for w, run in enumerate(runs)
                     if k + max(0, added) in run), first)
        if first is None:
            return None
        return ops.syllabify(self.doc, line, voice,
                             list(range(first, (last or first) + 1)), **ask)

    # ---------------------------------------------------------------- menus
    def _run(self, said) -> None:
        """An op has already been applied -- tell the window about it."""
        if said:
            self.edited.emit(said)

    def chip_menu(self, at) -> None:
        """The word commands -- only the ones that can do something here.

        Every item used to be offered on every word: merging the last
        syllable with a next one there is not, moving the first line up,
        joining the last word to nothing. Each did nothing when picked, which
        reads as the editor being broken. So an item is offered only where it
        would act. "Sing it with the next word, as one" is gone from here: on
        a word of one syllable it is exactly "Merge with the next syllable",
        and the ribbon's Sung as one still does the whole-word version.

        With several words picked and the menu opened on one of them, the
        commands that make sense over a selection act on all of them.
        """
        line, voice, k = self.cursor
        g = self.doc.group(line, voice)
        if g is None or not 0 <= k < len(g.syls):
            return
        runs = g.words()
        word = next((w for w, run in enumerate(runs) if k in run), 0)
        run = runs[word]
        n_lines = len(self.doc.lines)
        ln = self.doc.lines[line]
        menu = QMenu(self)
        menu.setSeparatorsCollapsible(True)
        add = menu.addAction

        def act(label, fn, tip=""):
            a = add(label)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(lambda _c=False: self._edit(fn))
            return a

        def act_word(label, fn, tip=""):
            """An edit that changes how a word is split -- remembered."""
            a = menu.addAction(label)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(lambda _c=False: self._edit(fn, word=True))

        picks = self.selected_words()
        here = (line, voice, word)
        if len(picks) > 1 and here in picks:
            self._picks_menu(menu, act, picks)
            menu.exec(at)
            return

        menu.addAction("Edit text…").triggered.connect(
            lambda _c=False: self._edit_current())
        menu.addSeparator()
        from . import syllables as SY
        if len(run) == 1 and len(SY.split(g.syls[k].text)) > 1:
            act_word("Cut this word into syllables",
                     lambda: ops.syllabify(self.doc, line, voice, [word]))
        if len(g.word_text(run)) > 1:
            act_word("Split this word…",
                     lambda: self._split_prompt(line, voice, k))
        if k + 1 < len(g.syls):
            act_word("Merge with the next syllable",
                     lambda: ops.merge_syllables(self.doc, line, voice, k,
                                                 k + 1))
        menu.addSeparator()
        if word + 1 < len(runs):
            act_word("Join with the next word",
                     lambda: ops.join_words(self.doc, line, voice, word))
        if g.syls[k].part and k + 1 < len(g.syls):
            act_word("Break the word after this syllable",
                     lambda: ops.end_word(self.doc, line, voice, k))
        menu.addSeparator()
        act("Insert a word before",
            lambda: ops.insert_syllable(self.doc, line, voice, k))
        act("Insert a word after",
            lambda: ops.insert_syllable(self.doc, line, voice, k + 1))
        if len(run) > 1:
            act("Delete this syllable", lambda: ops.delete_syllables(
                self.doc, line, voice, k, k))
        act("Delete this word", lambda: ops.delete_syllables(
            self.doc, line, voice, run[0], run[-1]))
        menu.addSeparator()
        if line > 0:
            act("Move the word up a line",
                lambda: ops.move_word(self.doc, line, voice, word, -1))
        if line + 1 < n_lines:
            act("Move the word down a line",
                lambda: ops.move_word(self.doc, line, voice, word, 1))
        menu.addSeparator()
        if voice:
            if line > 0:
                act("Move this ad-lib to the line above",
                    lambda: ops.move_backing(self.doc, line, voice, line - 1))
            if line + 1 < n_lines:
                act("Move this ad-lib to the line below",
                    lambda: ops.move_backing(self.doc, line, voice, line + 1))
            if voice > 1:
                act("Move it up among this line's ad-libs",
                    lambda: ops.move_backing(self.doc, line, voice, line,
                                             voice - 2))
            if voice < len(ln.bg):
                act("Move it down among them",
                    lambda: ops.move_backing(self.doc, line, voice, line,
                                             voice))
            act("Give it a line of its own",
                lambda: ops.split_off_backing(self.doc, line, voice))
            act("Make it an ordinary line",
                lambda: ops.adlib_to_line(self.doc, line, voice))
            if ";" in "".join(s.text for s in g.syls):
                act("Split it at the ; into separate ad-libs",
                    lambda: ops.split_backing_on(self.doc, line, voice))
        else:
            if line > 0:
                act("Make this line an ad-lib of the line above",
                    lambda: ops.to_backing(self.doc, line, voice, line - 1))
            if line + 1 < n_lines:
                act("Make it an ad-lib of the line below",
                    lambda: ops.to_backing(self.doc, line, voice, line + 1))
        menu.addSeparator()
        if voice == 0 and word > 0:
            act("Split the line here",
                lambda: ops.split_line(self.doc, line, word))
        if voice == 0:
            act("From here on is a backing vocal",
                lambda: ops.to_background(self.doc, line, k, len(g.syls) - 1))
        else:
            act("Fold this backing vocal into the lead",
                lambda: ops.to_lead(self.doc, line, voice - 1))
        self._repeat_item(menu, act, [line])
        menu.exec(at)

    def _picks_menu(self, menu, act, picks) -> None:
        """The commands that act on every picked word at once."""
        n = len(picks)
        groups = ops._by_group(self.doc, picks)

        def cut():
            done = 0
            for (i, v), words in groups.items():
                if ops.syllabify(self.doc, i, v, words):
                    done += 1
            return f"cut the picked words in {done} voice(s)" if done else None

        def untime():
            hit = 0
            for (i, v), words in groups.items():
                g = self.doc.group(i, v)
                runs = g.words()
                syls = [k for w in words if w < len(runs) for k in runs[w]]
                if ops.untime(self.doc, i, v, syls):
                    hit += 1
            return f"forgot the times of {n} words" if hit else None

        from . import syllables as SY
        whole = [(i, v, w) for (i, v), words in groups.items()
                 for w in words
                 if len(self.doc.group(i, v).words()[w]) == 1]
        split = [p for p in picks if p not in whole]
        timed = any(self.doc.group(i, v).syls[k].timed
                    for (i, v), words in groups.items() for w in words
                    for k in self.doc.group(i, v).words()[w])
        if any(len(SY.split(self.doc.group(i, v).word_text(
                self.doc.group(i, v).words()[w]))) > 1 for i, v, w in whole):
            act(f"Cut these {n} words into syllables", cut)
        adjacent = any((i, v, w + 1) in picks for i, v, w in picks)
        if adjacent:
            act(f"Join these {n} words", lambda: ops.join_run(self.doc, picks))
        if split:
            act("Break the picked words apart",
                lambda: ops.break_words(self.doc, picks))
        menu.addSeparator()
        if timed:
            act(f"Clear the times of these {n} words", untime)
        act(f"Delete these {n} words",
            lambda: ops.delete_words(self.doc, picks))

    def _repeat_item(self, menu, act, lines) -> None:
        """"Time from line N" where a line repeats one already timed -- and
        "time lines A–B as one" where it is in a run of a group that has a
        syllable timed and somewhere timed to copy from."""
        runs = []
        for i in lines:
            run = ops.run_at(self.doc, i)
            if run is None or run in runs:
                continue
            n, at, size = run
            src = ops.part_source(self.doc, n, at, size)
            if src is not None and any(
                    s.timed for o in range(size)
                    for s in self.doc.lines[at + o].lead.syls):
                runs.append(run)
        if runs:
            menu.addSeparator()
            n, at, size = runs[0]
            src = ops.part_source(self.doc, n, at, size)
            label = (f"Time lines {at + 1}–{at + size} as one, from lines "
                     f"{src + 1}–{src + size}" if len(runs) == 1 else
                     f"Time {len(runs)} grouped runs, each as one")

            def go_runs():
                said = [ops.fill_part(self.doc, at) for _n, at, _s in runs]
                said = [x for x in said if x]
                return (said[0] if len(said) == 1 else
                        f"{len(said)} grouped runs timed" if said else None)

            a = menu.addAction(label)
            a.setToolTip("Every line of the run takes the times of the same "
                         "line where the group was last sung, all moved by "
                         "one amount, so the first timed syllable stays "
                         "where it is.")
            a.triggered.connect(lambda _c=False: self._edit(go_runs))
            grouped = {at + o for _n, at, size in runs for o in range(size)}
            lines = [i for i in lines if i not in grouped]
        fill = []
        for i in lines:
            j = ops.repeat_source(self.doc, i)
            if j is None:
                continue
            if any(s.timed for s in self.doc.lines[i].lead.syls):
                fill.append((i, j))
        if not fill:
            return
        menu.addSeparator()
        label = (f"Time it from line {fill[0][1] + 1}, as sung there"
                 if len(fill) == 1 else
                 f"Time {len(fill)} lines from the lines they repeat")

        def go():
            said = [ops.fill_from_repeat(self.doc, i) for i, _j in fill]
            said = [x for x in said if x]
            return (said[0] if len(said) == 1 else
                    f"{len(said)} lines timed from earlier repeats"
                    if said else None)

        a = menu.addAction(label)
        a.setToolTip("Everything in the line is taken from the earlier one, "
                     "moved so its first timed syllable stays where it is.")
        a.triggered.connect(lambda _c=False: self._edit(go))

    def line_menu(self, at) -> None:
        self.lines_menu().exec(at)

    def lines_menu(self) -> QMenu:
        """The line commands, over the SELECTION.

        Every item here reads the rows that are picked out, not the one the
        pointer happens to be over. Half of them used to read the cursor
        instead, so selecting four lines and asking for them to be spread --
        or made into ad-libs -- answered about one of them and left the other
        three alone, with nothing on screen to say the selection had been
        ignored. With nothing selected the row under the pointer stands in
        for one, which is what clicking it has just made true anyway.

        The labels count, for the same reason: "Delete (4 rows)" is the only
        warning there is that the pointer is not what is about to happen.
        """
        rows = self.selected_rows() or [self.cursor[:2]]
        sel = sorted({i for i, _v in rows})
        bgs = [p for p in rows if p[1]]
        leads = [p for p in rows if not p[1]]
        many = f" ({len(rows)} rows)" if len(rows) > 1 else ""
        lines_many = f" ({len(sel)} lines)" if len(sel) > 1 else ""
        menu = QMenu(self)
        menu.setSeparatorsCollapsible(True)

        def act(label, fn):
            menu.addAction(label).triggered.connect(
                lambda _c=False: self._edit(fn))

        n_lines = len(self.doc.lines)
        groups = [self.doc.group(i, v) for i, v in rows]
        groups = [g for g in groups if g is not None]
        timed = any(s.timed for g in groups for s in g.syls)
        only_bg = bool(rows) and all(v for _i, v in rows)
        if only_bg:
            line, voice = rows[0]
            n_bg = len(self.doc.lines[line].bg)
            can_up, can_down = voice > 1, voice < n_bg
        else:
            can_up, can_down = sel[0] > 0, sel[-1] + 1 < n_lines
        act("Duplicate" + many, lambda: ops.duplicate_rows(self.doc, rows))
        act("Delete" + many, lambda: ops.delete_rows(self.doc, rows))
        menu.addAction("Insert a line below…").triggered.connect(
            lambda _c=False: self.insert_below(sel[-1] + 1))
        menu.addAction("Insert an ad-lib below…").triggered.connect(
            lambda _c=False: self.insert_adlib_below(sel[-1]))
        menu.addSeparator()
        if len(sel) > 1:
            act(f"Merge these {len(sel)} lines",
                lambda: ops.merge_runs(self.doc, sel))
        if can_up:
            act("Move up" + many, lambda: ops.move_rows(self.doc, rows, -1))
        if can_down:
            act("Move down" + many, lambda: ops.move_rows(self.doc, rows, 1))
        menu.addSeparator()
        act("Swap main / duet" + lines_many,
            lambda: ops.swap_agents(self.doc, sel))
        menu.addSeparator()
        if timed:
            act("Spread the times evenly" + many,
                lambda: ops.spread_rows(self.doc, rows))
            act("Clear the times" + many,
                lambda: ops.clear_times(self.doc, rows))
        self._repeat_item(menu, act, sel)
        menu.addSeparator()
        span = list(range(sel[0], sel[-1] + 1))
        keys = tuple(ops.line_key(self.doc.lines[i]) for i in span)
        if (len(sel) > 1 and all(any(k) for k in keys)
                and keys not in self.doc.parts):
            act(f"Group lines {sel[0] + 1}–{sel[-1] + 1}, to time as one"
                + ("" if sel == span else " (and the lines between)"),
                lambda: ops.make_part(self.doc, sel))
        if any(i in self.runs for i in sel):
            act("Ungroup", lambda: ops.drop_parts(self.doc, sel))
        menu.addSeparator()
        if bgs:
            n = f" ({len(bgs)})" if len(bgs) > 1 else ""
            act(("Make these ad-libs ordinary lines" if len(bgs) > 1
                 else "Make this ad-lib an ordinary line") + n,
                lambda: ops.adlibs_to_lines(self.doc, bgs))
            act(("Give them rows of their own" if len(bgs) > 1
                 else "Give it a row of its own") + n,
                lambda: ops.split_off_backings(self.doc, bgs))
            if any(";" in "".join(y.text for y in (self.doc.group(i, v) or
                                                   M.Group()).syls)
                   for i, v in bgs):
                act("Split at the ; into separate ad-libs" + n,
                    lambda: ops.split_backings_on(self.doc, bgs))
        if leads:
            n = f" ({len(leads)})" if len(leads) > 1 else ""
            if any(i > 0 for i, _v in leads):
                act(("Make these lines ad-libs of the line above"
                     if len(leads) > 1
                     else "Make this line an ad-lib of the line above") + n,
                    lambda: ops.lines_to_backing(self.doc, leads, -1))
            if any(i + 1 < n_lines for i, _v in leads):
                act(("Make them ad-libs of the line below" if len(leads) > 1
                     else "Make it an ad-lib of the line below") + n,
                    lambda: ops.lines_to_backing(self.doc, leads, 1))
        if self.menu_extra is not None:
            self.menu_extra(menu, sel)
        return menu

    def insert_below(self, at: int) -> None:
        """A new line, with the box already open across it.

        Inserting from the menu used to leave an empty line and nothing
        else: no box, no cursor in it, and a line whose only chip is a
        placeholder somebody then has to find and double-click. Asking for a
        line IS asking for the words in it, so this is the ribbon's Insert --
        the same placeholder, the same line-wide box, selected ready to be
        typed over, and the same rule that an abandoned line goes away again.
        """
        self.will_edit.emit()
        said = ops.insert_line(self.doc, at, PLACEHOLDER)
        self.edited.emit(said or "")
        if not said:
            return
        self.set_cursor(at, 0, 0)
        self.edit_line(at)

    def insert_adlib_below(self, line: int) -> None:
        """A new ad-lib on this line, with the box open across it, as Insert."""
        self.will_edit.emit()
        said = ops.insert_adlib(self.doc, line, PLACEHOLDER)
        self.edited.emit(said or "")
        if not said:
            return
        voice = len(self.doc.lines[line].bg)
        self.set_cursor(line, voice, 0)
        self.edit_line(line, voice)

    def _edit(self, fn, word: bool = False) -> None:
        self.will_edit.emit()
        said = fn()
        if said:
            self.edited.emit(said)
            if word:
                self.word_changed.emit(*self.cursor)
        else:
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
        from .wordsplit import SplitDialogue
        g = self.doc.group(line, voice)
        if g is None or not 0 <= k < len(g.syls):
            return None
        run = next((r for r in g.words() if k in r), None)
        if not run:
            return None
        if len(run) > 1:
            ops.merge_syllables(self.doc, line, voice, run[0], run[-1])
            run = [run[0]]
        k = run[0]
        word = g.syls[k].text
        if len(word) < 2:
            return None
        from . import syllables as SY
        ways = ["|".join(w) for w in SY.ways_for(word)]
        guess, at = [], 0
        for piece in SY.split(word)[:-1]:
            at += len(piece)
            guess.append(at)
        dlg = SplitDialogue(word, cuts=guess, everywhere=bool(
            K.config().get("split_everywhere", True)), parent=self,
            ways=ways)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        K.remember(split_everywhere=dlg.everywhere.isChecked())
        self.split_also = bool(ways) and dlg.also.isChecked()
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
    TAP_ALL, TAP_LEAD, TAP_BG = "all", "lead", "bg"

    def taps(self, voice: int) -> bool:
        """Whether the tapping choice times this voice: 0 the lead, 1.. an
        ad-lib. "Ad-libs only" leaves the leads alone and "Lines only" the
        ad-libs; the timing keys refuse what it leaves out."""
        if voice == 0:
            return self.tap_mode != self.TAP_BG
        return self.tap_mode != self.TAP_LEAD

    def walk(self) -> list:
        """Every chip in the order it is tapped.

        In the order things SOUND, not the order they are drawn: an ad-lib
        that opens its line is tapped before the words it opens, one that
        answers is tapped after them. Where the times are already known they
        decide; where they are not -- which is most of the time, since this is
        what puts them there -- the lead_in flag does.

        The sentinels for an untimed group have to sort on the RIGHT SIDE of
        the lead rather than at some fixed clock time. A plain 1.0 for "an
        untimed answer" is only later than the lead for the first second of a
        song; a line 32 seconds in sorted its untimed ad-lib in front of its
        freshly timed lead, so committing the lead's last syllable walked
        straight into the next line and the ad-lib was never reached at all.
        The order also has to hold STILL as syllables get times, because the
        cursor steps through it one tap at a time.

        `tap_mode` decides which voices are visited: everything, the leads
        only, or the ad-libs only. Most lines have no ad-lib, and on the ones
        that do it is often timed in a pass of its own -- which is the whole
        reason for the third mode.
        """
        mode = self.tap_mode
        out = []
        for i, ln in enumerate(self.doc.lines):
            groups = []
            if mode != self.TAP_BG:
                groups.append((0, ln.lead))
            if mode != self.TAP_LEAD:
                groups += [(v, g) for v, g in enumerate(ln.groups()) if v]

            def when(pair):
                v, g = pair
                a = g.span()[0]
                if v == 0:
                    return (a if a is not None else 0.0, 0)
                if getattr(g, "lead_in", False):
                    return (float("-inf"), v)
                return (a if a is not None else float("inf"), v)

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
            near = [n for n, (i, v, _k) in enumerate(order)
                    if (i, v) == (line, voice)]
            if not near:
                near = [n for n, (i, _v, _k) in enumerate(order) if i == line]
            if not near:
                return False
            at = min(near, key=lambda n: abs(order[n][2] - k))
            self.set_cursor(*order[at])
            if order[at][2] == k:
                return True
        want = at + delta
        if not 0 <= want < len(order):
            return False
        if not over_lines and order[want][0] != line:
            return False
        self.set_cursor(*order[want])
        return True

    def settle_cursor(self) -> tuple:
        """The cursor, brought back to the line that is actually selected.

        The last guard for the same mistake the click and the line keys each
        made on their own: an action addressed at "this line" reading a word
        cursor left behind in another one. Every path that moves the selection
        without moving the cursor ends up here, so a timing key can only ever
        stamp a word inside the line the user can see is picked.

        A selection of several lines is left alone -- with a run of them
        picked there is no one line the cursor ought to be in, and the word it
        is on is as good an answer as any.
        """
        rows = self.selected_rows()
        if len(rows) != 1 or self.cursor[:2] in self.selection:
            return self.cursor
        line, voice = rows[0]
        g = self.doc.group(line, voice)
        if g is None or not g.syls:
            return self.cursor
        self.set_cursor(line, voice, 0)
        return self.cursor

    def step_line(self, delta: int) -> bool:
        """The next LINE, stepped from the line that is selected.

        From the SELECTION, not from the word cursor. They are usually the
        same row and they are not always: clicking a line in the strip,
        selecting a run of them, an edit that moves the selection, or the
        cursor being left in a line the eye has long since moved on from --
        in every one of those, stepping from the cursor walked off from a
        line nobody had selected, which is not what a key called "next line"
        can mean.

        From the FAR END of a run of them, in the direction of travel, so
        that stepping on out of a multi-line selection carries on past it
        rather than landing back inside it.

        And it lands on the line, not on a word inside the old one: whatever
        words were picked out belonged to the line being left, so they are
        let go, and the selection becomes the one line arrived at. A line key
        that quietly kept hold of a word selection made the next word-level
        edit act somewhere off screen.
        """
        rows = self.selected_rows()
        at = ((max if delta > 0 else min)(i for i, _v in rows) if rows
              else self.cursor[0])
        line = at + delta
        if not 0 <= line < len(self.doc.lines):
            return False
        self.word_sel = set()
        self._word_anchor = None
        self.select([(line, 0)])
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
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            one = self.picked_syllable()
            if one:
                line, voice, k = one
                self._edit(lambda: ops.delete_syllables(self.doc, line, voice,
                                                        k, k))
                self.word_sel = set()
            elif self.word_sel:
                picks = self.selected_words()
                self._edit(lambda: ops.delete_words(self.doc, picks))
                self.word_sel = set()
            else:
                rows = self.selected_rows() or [self.cursor[:2]]
                self._edit(lambda: ops.delete_rows(self.doc, rows))
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


def _box_style(font) -> str:
    """An inline box that hides what it is drawn over.

    The new look's line edits are smoked glass -- rgba(0,0,0,70) -- which is
    right in a dialogue and wrong here: the chip's own text showed through the
    box, a second copy of the word under the one being typed. Solid, in the
    list's own ink, at the list's own size (the sheet's 15px beat setFont),
    and with the padding taken out so a chip-high box has room for its text.
    """
    size = font.pixelSize()
    size = f"{size}px" if size > 0 else f"{max(1.0, font.pointSizeF()):.1f}pt"
    return (f"QLineEdit {{ background: {BG.name()}; color: {TEXT.name()}; "
            f"border: 1px solid {CHIP_CURSOR.name()}; border-radius: 3px; "
            f"padding: 0 3px; margin: 0; font-size: {size}; }}")


class _WordBox(QLineEdit):
    """The box a word is typed into.

    Enter is TAKEN here. A plain QLineEdit reports Enter and then lets the key
    go on to its parent, and the parent is the lyric list, whose Enter means
    "edit the word under the cursor" -- so every Enter that closed the box
    opened it again on the same word, and it never went away.
    """

    done = pyqtSignal(str)

    def keyPressEvent(self, ev) -> None:                  # noqa: N802 (Qt name)
        k = ev.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            ev.accept()
            self.done.emit("keep")
            return
        if k == Qt.Key.Key_Escape:
            ev.accept()
            self.done.emit("cancel")
            return
        super().keyPressEvent(ev)


class _ReadingBox(QLineEdit):
    """The box a reading is typed into. Tab is taken here rather than moving
    the focus, because the next thing to type is the next reading."""

    done = pyqtSignal(str)

    def keyPressEvent(self, ev) -> None:                  # noqa: N802 (Qt name)
        k = ev.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.done.emit("keep")
        elif k == Qt.Key.Key_Escape:
            self.done.emit("cancel")
        elif k == Qt.Key.Key_Tab:
            self.done.emit("next")
        elif k == Qt.Key.Key_Backtab:
            self.done.emit("back")
        else:
            super().keyPressEvent(ev)

    def event(self, ev) -> bool:                          # noqa: A003
        from PyQt6.QtCore import QEvent
        if ev.type() == QEvent.Type.KeyPress and ev.key() in (
                Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.keyPressEvent(ev)
            return True
        return super().event(ev)

    def focusOutEvent(self, ev) -> None:                  # noqa: N802 (Qt name)
        super().focusOutEvent(ev)
        if self.isVisible():
            self.done.emit("keep")
