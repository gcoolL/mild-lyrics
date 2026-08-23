# `editor/lineview.py`

Comments lifted out of `editor/lineview.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 53** — before `GUTTER = 92.0                 # number and badges`

> All of these are at scale 1 and go through T.px(), so the zoom moves the
> whole layout together -- a bigger word in the same slot would just collide
> with the times column.

**line 56** — on `GUTTER = 92.0`

> number and badges

**line 57** — on `TIMES = 168.0`

> start -> end, in timing mode

**line 58** — on `PAD_X, PAD_Y = 8.0, 6.0`

> inside a chip

**line 59** — before `WORD_GAP = 22.0`

> Wider than the padding inside a chip, and it has to be: a word cut into
> syllables must read as ONE word with seams in it, not as two words. The gap
> between words is therefore bigger than anything inside one.

**line 63** — on `BG_INDENT = 26.0`

> a backing voice sits in from its lead

**line 65** — on `LYRIC_PX = 18`

> the words themselves -- the point of the tool


## `Row`

**line 77** — on `    chips: list = field(default_factory=list)`

> QRectF per syllable


## `LineList`

**line 84** — on `    will_edit = pyqtSignal()`

> take an undo snapshot now

**line 85** — on `    edited = pyqtSignal(str)`

> an op ran; here is what it did

**line 87** — on `    word_changed = pyqtSignal(int, int, int)`

> a word was split or rejoined


## `LineList.__init__`

**line 94** — on `        self.mode = "edit"`

> edit | timing | preview

**line 98** — before `self.tap_adlibs = True`

> Whether tapping walks into the backing voices or stays on the lead.

**line 100** — before `self.selection: set = set()`

> (line, voice) pairs, not line numbers: a backing voice is its own
> row with its own times, and selecting the words a singer sings
> should not drag the voice answering them along with it.

**line 104** — on `        self._anchor: tuple = (0, 0)`

> for shift-click ranges

**line 106** — on `        self._key = None`

> what the layout was made for

**line 115** — before `self._drag: dict | None = None`

> A row being dragged by its number, and where it would land.


## `LineList.set_mode`

**line 125** — on `        self.relayout()`

> the times column comes and goes


## `LineList._layout`

**line 219** — before `if x and x + wide > room:`

> A word wraps whole. Splitting one across two rows would
> put half of "everything" at the end of a line and the
> rest at the start of the next, which reads as two words.


## `LineList.paintEvent`

**line 274** — on `                continue`

> not in view; do not draw it


## `LineList._row`

**line 295** — before `p.fillRect(QRectF(0, top - 2, 3, r.height), T.q(T.LEAD))`

> A bar down the edge rather than a wash over everything: the wash
> competed with the chips, which are the thing being looked at.

**line 301** — before `if r.voice == 0:`

> gutter: the number once per line, then what kind of voice this is


## `LineList._word`

**line 355** — before `rows = {}`

> A word can wrap mid-way only if it was laid out that way, which it
> never is -- but a defensive check beats a rectangle spanning two
> rows if that ever changes.

**line 370** — before `p.setBrush(Qt.BrushStyle.NoBrush)`

> Absence should look like absence: an untimed word is an
> outline, not a differently-shaded fill.

**line 381** — before `p.setPen(QPen(BG, 1))`

> the seam: the surface below showing through, not a
> black line drawn over the top


## `LineList._chip`

**line 394** — before `if fill is not None:`

> The word's own block is already painted underneath; a syllable only
> paints over it when it has something of its own to say.

**line 406** — before `k = (self.pos - s.start) / (s.end - s.start)`

> The sweep: the chip fills left to right across the syllable, the
> way the player draws it, so a preview shows the same thing a
> listener will see rather than a chip merely lighting up.


## `LineList._apply_drop`

**line 448** — before `line, voice = drag["row"]`

> The drag dict is handed in rather than read off self: the release
> clears it first, so that a drop which opens a dialog cannot be
> re-entered by a second release.

**line 458** — before `self._edit(lambda: ops.move_backing(`

> onto the words of a line: the end of its answers, or the front
> if dropped above them

**line 466** — on `            at -= 1`

> it is coming out of this list first


## `LineList.mousePressEvent`

**line 488** — before `if (ev.button() == Qt.MouseButton.LeftButton`

> The number and the badge are the handle: pressing there and moving
> picks the row up. Anywhere else in the row still selects and edits,
> so a drag can never start by accident on a word.

**line 499** — before `order = [(x.line, x.voice) for x in self.rows]`

> Over the ROWS as drawn, so a range can start on a lead and end
> on a backing voice without swallowing the ones between.


## `LineList.mouseDoubleClickEvent`

**line 548** — before `a, _b = self._span(r)`

> Double-clicking the empty part of a row is "take me there",
> which is what double-clicking a line meant in the old table.


## `LineList._edit`

**line 723** — before `self.edited.emit("")`

> Nothing happened, so the snapshot taken above is noise. The
> window drops it when it hears nothing back.


## `LineList._split_prompt`

**line 751** — before `if len(run) > 1:`

> The whole WORD is what is being split, not one piece of it: cutting
> a piece that is already part of a split word can only ever add a
> boundary, and the picture has to show the word to be pointed at.


## `LineList.walk.when`

**line 821** — before `return ((-1.0, v) if getattr(g, "lead_in", False)`

> untimed: an opener comes first, the lead next, the rest
> after it
