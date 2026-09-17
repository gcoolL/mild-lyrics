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
