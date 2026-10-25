# `editor/syncbar.py`

Comments lifted out of `editor/syncbar.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 78** — before `CELL_W = 52.0`

> What a slice is drawn at when the row has room for it, and the narrowest it
> may be squeezed to before the row wraps instead. The floor is the number
> that matters: below it a syllable is crossed by accident at the speed a
> hand moves through a fast line, which is what the whole widget is for. The
> wanted width is only comfort, so it gives way first.


## `SyncBar.__init__`

**line 131** — before `self.cell = CELL_W`

> Set from the settings; see the module docstring. Kept on the widget
> rather than read from the config here, because this file draws and
> the window is what knows what anybody has chosen.

**line 145** — before `self.ok = lambda: True`

> Asked the moment a drag would start, and expected to say out loud
> why not when the answer is no -- the same contract the list has.


## `SyncBar._relayout`

**line 197** — before `need = [max(floor, w) for w in want]`

> Packed by what a slice will END UP taking, floor included, or a row
> could be filled with words too short to honour the floor in.

**line 216** — before `drawn = sum(widths) - gap`

> Centred, not stretched. A row of equal slices stretched to the
> edges would make the last row of a wrapped line -- three words,
> say -- into three enormous ones, and the hand would have to
> learn a different step for it. The gap after the last slice is
> not part of the row, so it is taken off before centring.


## `SyncBar._cell`

**line 317** — before `p.setPen(QPen(T.q(T.LEAD), 1.8))`

> Where a pass would sensibly begin: the first syllable with no
> time on it. Half a row already timed is the ordinary state
> after a drag that stopped short, and hunting for the seam by
> eye is exactly the work this mark saves.


## `SyncBar.mouseMoveEvent`

**line 375** — before `k = max(k, self._from)`

> Never behind where the pass began: winding back is for taking back
> what this drag laid down, and carried past that it would stamp
> earlier syllables with a later clock -- times in the wrong order,
> with nothing to say so.

## Lift — 2026-10-25

Docstrings shortened in `editor/syncbar.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The bar you drag across to time a row.
>
> Drag sync began on the words themselves, and on the words it does not work.
> The thing you are aiming at is a chip drawn the width of what it says, so
> "cannot" is eighty pixels and "I" is eighteen -- and the syllables you most
> need to place accurately are, without fail, the short ones. A line of
> one-syllable words is a row of slivers, and the drag misses them at speed.
>
> So the bar is the row laid out again, and by default EVERY SLICE IS THE SAME
> WIDTH.
>
> That is the second answer to the same complaint, and the one that is on. The
> first was proportional: a slice as wide as its word, floored so that "I" was
> still hittable, which kept the bar the same shape as the line above it --
> pleasant to read, and it meant the hand had to travel a different distance for
> every syllable. What a drag mostly wants is a rhythm: one width, one step, no
> word worth more room than any other, because the drag is spacing syllables in
> TIME and the widths were saying something about spelling instead.
>
> Both are settings now, because which one helps is a question about the hand
> doing the dragging and not one this file can answer. `cell` is what a slice is
> drawn at and `stretch` is how much of the word's own drawn width is added to
> it: at 0 they are all the same, at 1 a long word gets about as much extra room
> as it takes to write, which is the old proportional bar. Anything between is
> between.
>
> They are also smaller than they were, and the row is centred rather than
> stretched to the edges. A slice only has to be wide enough that it cannot be
> crossed by accident at the speed a hand moves through a fast line -- that is
> `MIN_CELL`, and it is the one width that is not a preference.
>
> A row that will not fit WRAPS, the way the lyric does, rather than shrinking
> its slices to make room: the width is a choice somebody made and a bar that
> quietly halves it on a long line is a different step for the same drag. The
> one thing that is shared down is a slice too wide for the bar on its own,
> which has nowhere else to go. The drag carries on from the end of one line to
> the start of the next.
>
> Nothing in here knows what time it is. It says which syllable the pointer is
> on and the window turns that into seconds, exactly as the list does -- see
> `Editor._sweep_begin`.

### `_share`

**line 45** — from the docstring, `def _share(want: list, room: float, floor: float) -> list:`

> Fit the wanted widths into `room` without any falling under `floor`.
>
> Scaling them all by one factor is nearly right and fails on exactly the
> case this widget exists for: the factor that makes a long line fit is the
> factor that takes "I" back down to a sliver. So the ones that would go
> under the floor are pinned there and taken out of the sum, and the rest
> are scaled into whatever room is left over -- repeatedly, because pinning
> one takes room away from the others and can push the next one under.
>
> It ends: each pass either pins at least one slice or returns, and there
> are only so many slices to pin.

### `SyncBar._relayout`

**line 125** — from the docstring, `def _relayout(self) -> None:`

> Where every slice goes: `cell` wide, `stretch` of the word added.
>
> Worked in PITCH -- what a slice takes up including the gap drawn after
> it -- rather than in the drawn width, so the sums come out right and
> the gap never has to be accounted for twice. `cell` and MIN_CELL are
> drawn widths, so a pitch is one gap more.

### `SyncBar._progress`

**line 222** — from the docstring, `def _progress(self, p, W: float, pad: float) -> None:`

> A hairline saying where the song is inside this row's LINE.
>
> The slices are an index, not a clock, so there is nowhere on them for
> a playhead to be. This is the one thing the bar can honestly show
> about time, and on a replay for an ad-lib it is the thing being
> waited for: the line is running, and this is how far through.

### `SyncBar.cell_at`

**line 272** — from the docstring, `def cell_at(self, x: float, y: float):`

> Which slice the pointer is on, never falling between two.
>
> The gaps drawn between the slices are not holes: each one belongs to
> the slice AFTER it, so the syllable changes the instant the pointer
> leaves the one it was on and there is nowhere on the bar where a drag
> stalls. Which row of a wrapped bar is decided first, by the nearest;
> left of everything on a row means that row's first slice, which is
> what a drag carrying on from the row above looks like.
