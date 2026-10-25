# `editor/wordsplit.py`

Comments lifted out of `editor/wordsplit.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## Lift — 2026-10-25

Docstrings shortened in `editor/wordsplit.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Splitting a word by pointing at it.
>
> Typing the first half was the wrong question to ask. It made the user spell
> the word back to prove where the cut goes, it refused anything that was not a
> prefix, and it could only ever make ONE cut -- so a word sung in three had to
> be split, re-selected and split again.
>
> Here the word is drawn as its letters with a gap between each pair, and the
> gaps are what you click. Click one, it becomes a cut; click it again, it is
> not. Any number of them, in any order, and the pieces are spelled out
> underneath as they will be.

---

## Lift — 2026-09-26

Comments lifted out of `editor/wordsplit.py` on 2026-09-26; the line numbers are that day's.

### `SplitDialogue.__init__`

**line 159** — before `self.also = QCheckBox(`

> A word can be sung more than one way ("bat|tlin'" or
> "bat|t|lin'"). With a way already kept, this one can be kept
> beside it rather than over it.


---

## Lift — 2026-09-17

### module level

**line 23** — on `GAP = 16.0`

> the clickable space between two letters


### `Letters._slots`

**line 49** — before `wide = max(fm.horizontalAdvance(ch),`

> a space has next to no width in most faces; give it enough to
> aim at, since it is a cut point like any other


### `Letters.paintEvent`

**line 89** — before `p.setPen(QPen(T.q(T.FAINT), 1))`

> A space is a letter here too -- it is where "do your" comes
> apart -- so it has to be visible to be aimed at.
