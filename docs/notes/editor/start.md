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

## Lift — 2026-10-25

Docstrings shortened in `editor/start.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Where a session begins: getting the words in.
>
> Importing is the one thing that happens once per song and then never again,
> so it is not a tab competing for room with the work -- it is the screen the
> window opens on, and it gets out of the way the moment there is a lyric to
> edit. Asked for again later it comes back in a window of its own, where it
> can also add to what is already there instead of replacing it.
>
> Everything here hands back a Doc and a sentence about where it came from. The
> fetching itself is `sources.py`; this is the part that asks.

### `_reason`

**line 21** — from the docstring, `def _reason(err: str) -> str:`

> A worker's error, as a sentence to put on the status line.
>
> The worker labels everything it catches with its class, which is what you
> want for the ones nobody expected -- an AttributeError names a bug here.
> A RuntimeError from a fetch is not one of those: it was raised on purpose
> and its message IS the reason, so the label in front of it is noise where
> the line has to be read at a glance.

### `GeniusRomanFind`

**line 55** — from the docstring, `class GeniusRomanFind(QDialog):`

> Which Genius romanisation to read: the automatic pick, one searched
> for here, or a genius.com link pasted in.
>
> The automatic pick is the first row and starts selected, so Enter on a
> dialog nobody touched does what the button always did. Enter in the box
> searches, or takes a link straight away. `choice()` answers
> ("auto", None), ("link", address) or ("hit", search hit).

### `StartPage._scrolled`

**line 240** — from the docstring, `def _scrolled(self) -> QWidget:`

> The page's content, in a scroll area that fills the page.
>
> The page is one of the editor window's stack, and a stack is as big
> as its biggest page: this one's card -- 720px of it at the least,
> and the title, the tiles and the paste box one under another -- held
> the editor at 768x682 at the smallest. Scrolled, it holds nothing,
> and a small screen gets a scroll bar on this page instead of a
> window that runs off it.

### `StartPage.fetch_audio`

**line 547** — from the docstring, `def fetch_audio(self) -> None:`

> Find the song these words belong to, without leaving the window.
>
> The title and artist boxes on this page are the point: they are
> filled in before the words arrive, so the song can be fetched first
> and the lyric written against it -- which is the order somebody
> timing an unreleased track works in, and the order this page could
> not support at all until now.

### `StartPage.fetch_from_player`

**line 704** — from the docstring, `def fetch_from_player(self, fall_back: bool = False, own: bool = True) -> None:`

> Ask the running player for this song's own document.
>
> The only way to reach an alignment the player made on this machine,
> which exists nowhere else. A document from Spicy Lyrics is refused
> by the player, and Apple Music asked in its place.
>
> `own` asks for the song's OWN lyrics rather than whatever is on
> screen. While "Show in Mild Lyrics" is on, those differ and the second
> one is this editor's own file -- asking for the screen handed our
> document straight back, which is indistinguishable from the fetch
> doing nothing. An older player does not know `source_doc` and says so;
> that answer retries with the plain one.

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
