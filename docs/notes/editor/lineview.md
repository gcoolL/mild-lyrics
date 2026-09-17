# `editor/lineview.py`

Comments lifted out of `editor/lineview.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `_inks`

**line 64** — before `CHIP_SWEEP = T.q(T.LEAD)`

> The two states a chip has while it is being dragged over: the one under the
> pointer, which is the syllable sounding right now, and the ones this pass
> has already laid down behind it. Bright and half-bright, so a glance at the
> row says how far along the drag is.


## module level

**line 79** — before `PLACEHOLDER = "…"`

> What a brand-new line holds until somebody types over it. It has to be
> SOMETHING: a line with no words has no chip to click and nowhere to put a
> cursor. Left untouched, it is thrown away again -- see commit_edit.


## `LineList.__init__`

**line 127** — before `self.word_sel: set = set()`

> Selected WORDS, as (line, voice, word). A word is what a person
> points at; a syllable is a piece of one, and pointing at a piece
> means pointing at the word it belongs to.

**line 143** — before `self.next_row: tuple | None = None`

> Drag sync: which row is up next, and -- while the bar is being
> dragged -- which of its syllables the pass has reached. Shown here,
> driven from there; see `show_pass`.


## `LineList.paintEvent`

**line 328** — before `x, top, tall = spot["mark"]`

> a word is being carried: the caret goes between two words


## `LineList._row`

**line 375** — before `box = r.chips[run[0]].translated(0, -off)`

> Only worth outlining once more than one word is picked: a
> single one is already shown by the cursor on its chip.

**line 387** — before `box = r.chips[0].translated(0, -off)`

> The row the bar is showing. Dashed, and around the words
> rather than the whole row, so it reads as "this is the one on
> the bar" and not as another kind of selection -- which the row
> already has.


## `LineList._chip`

**line 488** — before `fill = CHIP_SWEEP if lit == 2 else CHIP_SWEPT`

> A drag beats every other reason a chip could be filled: while
> one is running it is the only thing being looked at.


## `LineList`

**line 628** — before `def row_for(self, line: int, voice: int):`

> Which row the bar is holding, and how to walk from one row to the next.
>
> A pass is one row, and that is the whole answer to ad-libs: a backing
> voice is a row of its own, so it goes on the bar by itself, over a
> replay of the line it answers. Nothing has to decide whether a drag
> across the words "meant" the ad-lib too.


## `LineList.mousePressEvent`

**line 710** — before `self.arm(r.line, r.voice)`

> A click here PICKS THE ROW, nothing more: it goes on the bar,
> and the bar is where it is dragged. Rows and words are not
> carried about in this mode -- being one careless drag away from
> reordering the song while timing it is not a trade worth having.
> The right button still opens the menus, because a bad split is
> most often noticed here.

**line 720** — before `alt = bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)`

> Anywhere on the row that is not a word picks the ROW up -- the
> number, the badge, the space after the last word. Aiming at the
> number was the only way before, which is a small target for the
> most ordinary thing there is to do to a line.
>
> A word still picks up the word, since that has to be reachable too;
> holding Alt over one takes the line instead, so "anywhere" really
> is anywhere.

**line 751** — before `if here in self.selection:`

> Picking a line up moves the cursor into it. It did not, and the
> cursor is what the timing keys act on -- so clicking a row to
> choose it and then pressing the start key stamped a word in
> whatever line was clicked last, which could be anywhere. The
> line looked chosen, the key looked ignored, and the edit landed
> off screen. Not on a ctrl-click that has just DESELECTED the
> row: nothing was picked up there.

**line 781** — on `                    self._word_anchor = here`

> the ROW drag armed above

**line 785** — before `self._drag = {"words": sorted(self.word_sel),`

> ...and it can be dragged from here, whole


## `LineList.mouseDoubleClickEvent`

**line 834** — before `s = (self.doc.group(r.line, r.voice) or M.Group()).syls`

> No box over the chip here: nothing is being typed in this mode,
> and a text editor opening under a hand that is timing a song is
> nobody's idea of what a second click means. Going to the word
> is, so that is what it does.


## `LineList.commit_edit`

**line 931** — before `if 0 <= line < len(self.doc.lines):`

> A line typed into and left empty -- or a new one abandoned -- goes
> away again rather than sitting there with nothing in it.


## `LineList.lines_menu`

**line 1066** — before `act(f"Merge these {len(sel)} lines",`

> Each unbroken run on its own -- a gapped selection used to
> swallow the lines in between, which nothing on screen showed.

**line 1073** — before `act("Swap main / duet" + lines_many,`

> One item, not two. There are exactly two sides, so "make it the
> one it is already" was never a thing to want.


## `LineList`

**line 1199** — before `TAP_ALL, TAP_LEAD, TAP_BG = "all", "lead", "bg"`

> How the tapping cursor treats the backing voices.


## `LineList.walk.when`

**line 1240** — on `                    return (float("-inf"), v)`

> always before what it opens


## `LineList.step`

**line 1257** — before `near = [n for n, (i, v, _k) in enumerate(order)`

> The cursor is somewhere this walk does not go -- an ad-lib
> clicked while the mode stays on the leads, or a chip that an
> edit has since removed. Falling back to the START of the song
> meant the next commit key stamped a time onto line 1, which is
> the worst possible answer. Take the nearest chip of the same
> row, and if the row is not walked at all do nothing: a no-op
> the user can see is right, a silent jump is not.


## `LineList.keyPressEvent`

**line 1349** — before `if self.word_sel:`

> What Delete deletes is whatever is selected -- the words if any
> are, the rows otherwise. It did nothing at all before.


---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/lineview.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

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


### `Row`

**line 77** — on `    chips: list = field(default_factory=list)`

> QRectF per syllable


### `LineList`

**line 84** — on `    will_edit = pyqtSignal()`

> take an undo snapshot now

**line 85** — on `    edited = pyqtSignal(str)`

> an op ran; here is what it did

**line 87** — on `    word_changed = pyqtSignal(int, int, int)`

> a word was split or rejoined


### `LineList.__init__`

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


### `LineList.set_mode`

**line 125** — on `        self.relayout()`

> the times column comes and goes


### `LineList._layout`

**line 219** — before `if x and x + wide > room:`

> A word wraps whole. Splitting one across two rows would
> put half of "everything" at the end of a line and the
> rest at the start of the next, which reads as two words.


### `LineList.paintEvent`

**line 274** — on `                continue`

> not in view; do not draw it


### `LineList._row`

**line 295** — before `p.fillRect(QRectF(0, top - 2, 3, r.height), T.q(T.LEAD))`

> A bar down the edge rather than a wash over everything: the wash
> competed with the chips, which are the thing being looked at.

**line 301** — before `if r.voice == 0:`

> gutter: the number once per line, then what kind of voice this is


### `LineList._word`

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


### `LineList._chip`

**line 394** — before `if fill is not None:`

> The word's own block is already painted underneath; a syllable only
> paints over it when it has something of its own to say.

**line 406** — before `k = (self.pos - s.start) / (s.end - s.start)`

> The sweep: the chip fills left to right across the syllable, the
> way the player draws it, so a preview shows the same thing a
> listener will see rather than a chip merely lighting up.


### `LineList._apply_drop`

**line 448** — before `line, voice = drag["row"]`

> The drag dict is handed in rather than read off self: the release
> clears it first, so that a drop which opens a dialog cannot be
> re-entered by a second release.

**line 458** — before `self._edit(lambda: ops.move_backing(`

> onto the words of a line: the end of its answers, or the front
> if dropped above them

**line 466** — on `            at -= 1`

> it is coming out of this list first


### `LineList.mousePressEvent`

**line 488** — before `if (ev.button() == Qt.MouseButton.LeftButton`

> The number and the badge are the handle: pressing there and moving
> picks the row up. Anywhere else in the row still selects and edits,
> so a drag can never start by accident on a word.

**line 499** — before `order = [(x.line, x.voice) for x in self.rows]`

> Over the ROWS as drawn, so a range can start on a lead and end
> on a backing voice without swallowing the ones between.


### `LineList.mouseDoubleClickEvent`

**line 548** — before `a, _b = self._span(r)`

> Double-clicking the empty part of a row is "take me there",
> which is what double-clicking a line meant in the old table.


### `LineList._edit`

**line 723** — before `self.edited.emit("")`

> Nothing happened, so the snapshot taken above is noise. The
> window drops it when it hears nothing back.


### `LineList._split_prompt`

**line 751** — before `if len(run) > 1:`

> The whole WORD is what is being split, not one piece of it: cutting
> a piece that is already part of a split word can only ever add a
> boundary, and the picture has to show the word to be pointed at.


### `LineList.walk.when`

**line 821** — before `return ((-1.0, v) if getattr(g, "lead_in", False)`

> untimed: an opener comes first, the lead next, the rest
> after it
