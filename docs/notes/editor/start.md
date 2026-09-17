# `editor/start.py`

Comments lifted out of `editor/start.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `StartPage.fetch_audio`

**line 199** — before `self.owner.doc.meta.setdefault("Title", meta["title"])`

> The document's own name wins in `owner.fetch_audio`, so a title
> typed here has to reach it. Nothing else on this page is touched.


## `StartPage.fetch_from_player.answered`

**line 360** — before `self.fetch_from_player(fall_back=fall_back, own=False)`

> an older player: ask it the only way it knows

**line 366** — before `finish()`

> what is on screen is our own push coming back


## `StartPage.fetch_chain`

**line 398** — before `trouble = []`

> A source that timed out or was refused, kept until there is a line
> to say it on. It belongs beside the answer rather than in front of
> it: "had nothing for it" is what a walk says both when a song is in
> no database and when the database would not answer the door.


---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/start.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### `StartPage`

**line 59** — before `loaded = pyqtSignal(object, str, bool, str)`

> doc, what happened, append?, and the file it came from ("" if none).
> The path travels WITH the document: a window holding song B must not be
> still pointing at song A's file, which is how a finished sync gets
> overwritten by the next one.


### `StartPage.__init__`

**line 67** — on `        self.owner = owner`

> the window: player, run(), say()


### `StartPage._build`

**line 73** — before `outer = QHBoxLayout(self)`

> The content sits in a column of its own rather than being stretched
> across whatever the window happens to be: a text box two thousand
> pixels wide is not easier to paste into, only emptier.

**line 146** — before `pick = QPushButton("▾")`

> The chain answers with whichever source ranks highest in
> the player's own order, which is usually what is wanted and
> occasionally not -- this is how to ask a particular one.


### `StartPage.fetch_from_player.answered`

**line 300** — on `                return`

> a later request won


### `StartPage.fetch_chain`

**line 334** — before `if not only and not force_chain and self.owner.link.alive():`

> The player first: it has the community document and its own
> alignments, and neither is reachable any other way.
