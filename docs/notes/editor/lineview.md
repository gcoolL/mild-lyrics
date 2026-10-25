# `editor/lineview.py`

Comments lifted out of `editor/lineview.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## 2026-10-14 — splitting one piece of a Japanese line

An unspaced Japanese line is one word, so "Split this word…" glued the whole line into one piece (its splits and times gone) before asking where to cut, and "Cut this word into syllables" only showed for a word of one piece. On a CJK piece of a longer run (`_cjk_piece`) the menu now offers "Cut this piece into syllables" (`ops.cut_syllable`, with the split settings via `split_args`) and "Split this piece…", which works on that piece only, guesses with Japanese/the settings, and starts with "apply to every copy" off. "Delete this word" still means the whole run.

## Lift — 2026-10-25

Docstrings shortened in `editor/lineview.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The lyric, line per line, with every syllable as something you can hit.
>
> This is the whole editor really: a vertical list of lines, each one a row of
> chips, and the chips are the syllables the file is actually made of. Words
> show as their chips butted together with no gap between them and a space
> between words, so a word cut into syllables looks like a word coming apart --
> which is what it is, and what no list of times can show.
>
>     12  ▸duet  [The][lights] [go] [out], [and] [I]   0:32.99 → 0:36.19
>         ↳bg    [(ooh)]                               0:35.10 → 0:36.02
>
> A backing voice gets a row under the line it answers, the way a player draws
> it, rather than a footnote inside the row: it is a concurrent voice with its
> own timings and it has to be as clickable as the lead.
>
> There are two ways to put times on it. The timing keys walk a cursor along
> and stamp one chip per press; drag sync drags across a bar of slices under
> the lyric and stamps a syllable per slice -- see `editor/syncbar.py`. The
> gesture is not here, because a chip is as wide as the word it says with no
> floor under it and a one-letter word is a sliver; what IS here is the row a
> drag is armed on and the lighting up of the words as one goes over them,
> which is where anybody doing it is actually looking.
>
> Painted rather than assembled out of widgets. A four-minute song is a couple
> of thousand chips, and two thousand QPushButtons would cost more to lay out
> than the audio costs to decode; painting a laid-out list is what the player
> already does with the same data. Only the rows in view are drawn, and the
> layout is cached until the width or the document changes.

### `LineList.set_pos`

**line 199** — from the docstring, `def set_pos(self, t: float) -> None:`

> Move the playhead, and follow it if asked.
>
> Only in preview, and only when something is actually sounding: an
> editor that scrolled away from the line being worked on every time the
> song moved would be unusable, which is why following is a preview
> behaviour and a deliberate one everywhere else.

### `LineList._run_bar`

**line 685** — from the docstring, `def _run_bar(self, p, r: Row, top: float, ln) -> None:`

> The bracket down the gutter beside a run of a group.
>
> One unbroken bar from the run's first row to its last, in the group's
> colour -- bright where the line is timed, faint where it is still
> waiting for its one tap, so the choruses left to do can be seen from
> a scroll down the song. Broken into dashes beside a line that is in
> the run by its syllables alone: other words, sung in as many.

### `LineList._word`

**line 779** — from the docstring, `def _word(self, p, r: Row, g, run: list, off: float, ink, fm) -> None:`

> One word: a single block, with a seam per syllable inside it.
>
> Drawn as a whole rather than as a row of separate chips because that
> is what it is. A word cut into three syllables is still the word --
> the seams say where the timings change, and the block says the reader
> is looking at one thing.

### `LineList.show_pass`

**line 810** — from the docstring, `def show_pass(self, row: tuple | None, at: int = -1, lit=()) -> None:`

> Light a row up as the bar is dragged over it.
>
> The words are where the eye is during a pass -- not on the bar, which
> is under the hand and needs no reading. So the bar says where the
> pointer has got to and the lyric shows it, which is the only reason
> this widget knows a drag is happening at all.

### `LineList.picked_syllable`

**line 1072** — from the docstring, `def picked_syllable(self):`

> (line, voice, k) when what is picked is one syllable of a word.
>
> A click on a syllable picks its word as well, for dragging -- so
> Delete read that as the word, and pointing at "mance" to take it out
> took "romance" with it. One word picked, with the cursor on one of
> several syllables in it, is that syllable. A word picked on its own
> is still the whole of it, and so is any run of words.

### `LineList.next_to_time`

**line 1197** — from the docstring, `def next_to_time(self, after: tuple | None = None) -> tuple | None:`

> The first row past `after` that still has a syllable without a time.
>
> What "next" means once a row is done. It walks the DRAWN order, which
> puts a line's ad-libs directly after the words they answer -- so a
> line with a backing vocal hands the drag straight back to the same
> line, which is the cue to play it again. Everything already timed is
> stepped over, so picking the work back up after a break lands where it
> was left rather than at the top.

### `LineList._place_editor`

**line 1456** — from the docstring, `def _place_editor(self) -> None:`

> Sit the box over the chip -- or across the row, for a whole line.
>
> A chip-wide box is right for correcting one syllable and useless for
> typing a line into: it is sixty-odd pixels, and a lyric line is not.
> `_edit_wide` says which this is, and a new line always asks for the
> wide one, because there is nothing there yet to be narrow about.

### `LineList.chip_menu`

**line 1574** — from the docstring, `def chip_menu(self, at) -> None:`

> The word commands -- only the ones that can do something here.
>
> Every item used to be offered on every word: merging the last
> syllable with a next one there is not, moving the first line up,
> joining the last word to nothing. Each did nothing when picked, which
> reads as the editor being broken. So an item is offered only where it
> would act. "Sing it with the next word, as one" is gone from here: on
> a word of one syllable it is exactly "Merge with the next syllable",
> and the ribbon's Sung as one still does the whole-word version.
>
> With several words picked and the menu opened on one of them, the
> commands that make sense over a selection act on all of them.

### `LineList.lines_menu`

**line 1985** — from the docstring, `def lines_menu(self) -> QMenu:`

> The line commands, over the SELECTION.
>
> Every item here reads the rows that are picked out, not the one the
> pointer happens to be over. Half of them used to read the cursor
> instead, so selecting four lines and asking for them to be spread --
> or made into ad-libs -- answered about one of them and left the other
> three alone, with nothing on screen to say the selection had been
> ignored. With nothing selected the row under the pointer stands in
> for one, which is what clicking it has just made true anyway.
>
> The labels count, for the same reason: "Delete (4 rows)" is the only
> warning there is that the pointer is not what is about to happen.
>
> With more than one line picked, the items that only make sense for one
> line are left out.

### `LineList.insert_below`

**line 2082** — from the docstring, `def insert_below(self, at: int) -> None:`

> A new line, with the box already open across it.
>
> Inserting from the menu used to leave an empty line and nothing
> else: no box, no cursor in it, and a line whose only chip is a
> placeholder somebody then has to find and double-click. Asking for a
> line IS asking for the words in it, so this is the ribbon's Insert --
> the same placeholder, the same line-wide box, selected ready to be
> typed over, and the same rule that an abandoned line goes away again.

### `LineList._split_prompt`

**line 2127** — from the docstring, `def _split_prompt(self, line: int, voice: int, k: int):`

> Ask where the word comes apart, by pointing at it.
>
> Cuts, plural: a word sung in three used to need splitting, finding
> the new piece, and splitting again. And the same word is sung the
> same way wherever it appears, so by default the answer is applied to
> every copy of it in the song -- and kept for the next one, like any
> other correction.

### `LineList.walk`

**line 2202** — from the docstring, `def walk(self) -> list:`

> Every chip in the order it is tapped.
>
> In the order things SOUND, not the order they are drawn: an ad-lib
> that opens its line is tapped before the words it opens, one that
> answers is tapped after them. Where the times are already known they
> decide; where they are not -- which is most of the time, since this is
> what puts them there -- the lead_in flag does.
>
> The sentinels for an untimed group have to sort on the RIGHT SIDE of
> the lead rather than at some fixed clock time. A plain 1.0 for "an
> untimed answer" is only later than the lead for the first second of a
> song; a line 32 seconds in sorted its untimed ad-lib in front of its
> freshly timed lead, so committing the lead's last syllable walked
> straight into the next line and the ad-lib was never reached at all.
> The order also has to hold STILL as syllables get times, because the
> cursor steps through it one tap at a time.
>
> `tap_mode` decides which voices are visited: everything, the leads
> only, or the ad-libs only. Most lines have no ad-lib, and on the ones
> that do it is often timed in a pass of its own -- which is the whole
> reason for the third mode.

### `LineList.settle_cursor`

**line 2256** — from the docstring, `def settle_cursor(self) -> tuple:`

> The cursor, brought back to the line that is actually selected.
>
> The last guard for the same mistake the click and the line keys each
> made on their own: an action addressed at "this line" reading a word
> cursor left behind in another one. Every path that moves the selection
> without moving the cursor ends up here, so a timing key can only ever
> stamp a word inside the line the user can see is picked.
>
> A selection of several lines is left alone -- with a run of them
> picked there is no one line the cursor ought to be in, and the word it
> is on is as good an answer as any.

### `LineList.step_line`

**line 2269** — from the docstring, `def step_line(self, delta: int) -> bool:`

> The next LINE, stepped from the line that is selected.
>
> From the SELECTION, not from the word cursor. They are usually the
> same row and they are not always: clicking a line in the strip,
> selecting a run of them, an edit that moves the selection, or the
> cursor being left in a line the eye has long since moved on from --
> in every one of those, stepping from the cursor walked off from a
> line nobody had selected, which is not what a key called "next line"
> can mean.
>
> From the FAR END of a run of them, in the direction of travel, so
> that stepping on out of a multi-line selection carries on past it
> rather than landing back inside it.
>
> And it lands on the line, not on a word inside the old one: whatever
> words were picked out belonged to the line being left, so they are
> let go, and the selection becomes the one line arrived at. A line key
> that quietly kept hold of a word selection made the next word-level
> edit act somewhere off screen.

### `_box_style`

**line 2329** — from the docstring, `def _box_style(font) -> str:`

> An inline box that hides what it is drawn over.
>
> The new look's line edits are smoked glass -- rgba(0,0,0,70) -- which is
> right in a dialogue and wrong here: the chip's own text showed through the
> box, a second copy of the word under the one being typed. Solid, in the
> list's own ink, at the list's own size (the sheet's 15px beat setFont),
> and with the padding taken out so a chip-high box has room for its text.

### `_WordBox`

**line 2339** — from the docstring, `class _WordBox(QLineEdit):`

> The box a word is typed into.
>
> Enter is TAKEN here. A plain QLineEdit reports Enter and then lets the key
> go on to its parent, and the parent is the lyric list, whose Enter means
> "edit the word under the cursor" -- so every Enter that closed the box
> opened it again on the same word, and it never went away.

### `LineList.mousePressEvent` (comment)

**line 1273** — before `keep = (word_here is not None and len(self.word_sel) > 1`

> Pressing on a word that is already one of several picked keeps
> them all, the way every list does -- it is how a run of words is
> picked UP. It used to drop everything but the one pressed on, so a
> selection could be made and acted on from the keys but never
> dragged. A press that turns out not to be a drag still narrows it
> to the one word, on release.

---

## Lift — 2026-10-11

Comments lifted out of `editor/lineview.py` on 2026-10-11, from PR #2 as it was reviewed; the line numbers are that day's.

### `LineList.mousePressEvent`

**line 1346** — before `keep_rows = (ev.button() == Qt.MouseButton.RightButton`

> A right-click inside a run of picked lines keeps the run, the way
> the word press above keeps a run of picked words. It used to fall
> through to the plain select below, which dropped everything but the
> row under the pointer -- so the line menu, which already reads the
> whole selection (see lines_menu), only ever saw the one line the
> pointer happened to be over. A right-click on a row that is NOT in
> the selection still starts a new one, which is what picking a
> different line means.

### `LineList.merge_selected`

**line 1991** — from the docstring, `def merge_selected(self, sel=None) -> str | None:`

> Five lines become one, so the old selection -- five (line, voice)
> pairs -- went on naming whatever now sat at those indices, which is
> the next few lines lit up as though they had been chosen. The runs
> are found the same way ops.merge_runs finds them (an unbroken stretch
> of picked lines each merges on its own), and each collapses to its
> first line, which is the index that survives. Merged from the last
> run back, so an earlier run's first line is still where it was.

Corrected on review: ops.merge_runs going last-to-first keeps an earlier
run's line in place, but a later run's merged line still moves up by the
lines the runs before it gave up, so its kept index is shifted by that.

### `LineList.lines_menu`

**line 2014** — from the docstring, `def lines_menu(self) -> QMenu:`

> The single-line items left out of a multi-line menu are: inserting
> beside one, stepping one up or down, spreading one's times, giving one
> ad-lib a row of its own, and turning a line into its neighbour's ad-lib.
> Each of them asks "this line" about a selection there is no one line to
> answer for, and the bulk answers -- Duplicate, Delete, Merge -- are the
> ones above.


---

## Lift — 2026-09-26

Comments lifted out of `editor/lineview.py` on 2026-09-26; the line numbers are that day's.

### `LineList._split_prompt`

**line 1128** — before `self.split_also = bool(ways) and dlg.also.isChecked()`

> Read by remember_word, which keeps the cut once it is made.


---

## Lift — 2026-09-17

### `_inks`

**line 64** — before `CHIP_SWEEP = T.q(T.LEAD)`

> The two states a chip has while it is being dragged over: the one under the
> pointer, which is the syllable sounding right now, and the ones this pass
> has already laid down behind it. Bright and half-bright, so a glance at the
> row says how far along the drag is.


### module level

**line 79** — before `PLACEHOLDER = "…"`

> What a brand-new line holds until somebody types over it. It has to be
> SOMETHING: a line with no words has no chip to click and nowhere to put a
> cursor. Left untouched, it is thrown away again -- see commit_edit.


### `LineList.__init__`

**line 127** — before `self.word_sel: set = set()`

> Selected WORDS, as (line, voice, word). A word is what a person
> points at; a syllable is a piece of one, and pointing at a piece
> means pointing at the word it belongs to.

**line 143** — before `self.next_row: tuple | None = None`

> Drag sync: which row is up next, and -- while the bar is being
> dragged -- which of its syllables the pass has reached. Shown here,
> driven from there; see `show_pass`.


### `LineList.paintEvent`

**line 328** — before `x, top, tall = spot["mark"]`

> a word is being carried: the caret goes between two words


### `LineList._row`

**line 375** — before `box = r.chips[run[0]].translated(0, -off)`

> Only worth outlining once more than one word is picked: a
> single one is already shown by the cursor on its chip.

**line 387** — before `box = r.chips[0].translated(0, -off)`

> The row the bar is showing. Dashed, and around the words
> rather than the whole row, so it reads as "this is the one on
> the bar" and not as another kind of selection -- which the row
> already has.


### `LineList._chip`

**line 488** — before `fill = CHIP_SWEEP if lit == 2 else CHIP_SWEPT`

> A drag beats every other reason a chip could be filled: while
> one is running it is the only thing being looked at.


### `LineList`

**line 628** — before `def row_for(self, line: int, voice: int):`

> Which row the bar is holding, and how to walk from one row to the next.
>
> A pass is one row, and that is the whole answer to ad-libs: a backing
> voice is a row of its own, so it goes on the bar by itself, over a
> replay of the line it answers. Nothing has to decide whether a drag
> across the words "meant" the ad-lib too.


### `LineList.mousePressEvent`

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


### `LineList.mouseDoubleClickEvent`

**line 834** — before `s = (self.doc.group(r.line, r.voice) or M.Group()).syls`

> No box over the chip here: nothing is being typed in this mode,
> and a text editor opening under a hand that is timing a song is
> nobody's idea of what a second click means. Going to the word
> is, so that is what it does.


### `LineList.commit_edit`

**line 931** — before `if 0 <= line < len(self.doc.lines):`

> A line typed into and left empty -- or a new one abandoned -- goes
> away again rather than sitting there with nothing in it.


### `LineList.lines_menu`

**line 1066** — before `act(f"Merge these {len(sel)} lines",`

> Each unbroken run on its own -- a gapped selection used to
> swallow the lines in between, which nothing on screen showed.

**line 1073** — before `act("Swap main / duet" + lines_many,`

> One item, not two. There are exactly two sides, so "make it the
> one it is already" was never a thing to want.


### `LineList`

**line 1199** — before `TAP_ALL, TAP_LEAD, TAP_BG = "all", "lead", "bg"`

> How the tapping cursor treats the backing voices.


### `LineList.walk.when`

**line 1240** — on `                    return (float("-inf"), v)`

> always before what it opens


### `LineList.step`

**line 1257** — before `near = [n for n, (i, v, _k) in enumerate(order)`

> The cursor is somewhere this walk does not go -- an ad-lib
> clicked while the mode stays on the leads, or a chip that an
> edit has since removed. Falling back to the START of the song
> meant the next commit key stamped a time onto line 1, which is
> the worst possible answer. Take the nearest chip of the same
> row, and if the row is not walked at all do nothing: a no-op
> the user can see is right, a silent jump is not.


### `LineList.keyPressEvent`

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
> clears it first, so that a drop which opens a dialogue cannot be
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
