# `editor/start.py`

Comments lifted out of `editor/start.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `StartPage`

**line 59** — before `loaded = pyqtSignal(object, str, bool, str)`

> doc, what happened, append?, and the file it came from ("" if none).
> The path travels WITH the document: a window holding song B must not be
> still pointing at song A's file, which is how a finished sync gets
> overwritten by the next one.


## `StartPage.__init__`

**line 67** — on `        self.owner = owner`

> the window: player, run(), say()


## `StartPage._build`

**line 73** — before `outer = QHBoxLayout(self)`

> The content sits in a column of its own rather than being stretched
> across whatever the window happens to be: a text box two thousand
> pixels wide is not easier to paste into, only emptier.

**line 146** — before `pick = QPushButton("▾")`

> The chain answers with whichever source ranks highest in
> the player's own order, which is usually what is wanted and
> occasionally not -- this is how to ask a particular one.


## `StartPage.fetch_from_player.answered`

**line 300** — on `                return`

> a later request won


## `StartPage.fetch_chain`

**line 334** — before `if not only and not force_chain and self.owner.link.alive():`

> The player first: it has the community document and its own
> alignments, and neither is reachable any other way.
