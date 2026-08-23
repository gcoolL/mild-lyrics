# `editor/wordsplit.py`

Comments lifted out of `editor/wordsplit.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 23** — on `GAP = 16.0`

> the clickable space between two letters


## `Letters._slots`

**line 49** — before `wide = max(fm.horizontalAdvance(ch),`

> a space has next to no width in most faces; give it enough to
> aim at, since it is a cut point like any other


## `Letters.paintEvent`

**line 89** — before `p.setPen(QPen(T.q(T.FAINT), 1))`

> A space is a letter here too -- it is where "do your" comes
> apart -- so it has to be visible to be aimed at.
