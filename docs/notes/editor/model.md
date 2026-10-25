# `editor/model.py`

Comments lifted out of `editor/model.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `from_body`

**line 162** — before `ln.lead = Group([Syl(w) for w in words_in(_clean_line(item.get("Text")))])`

> Line-timed sources -- NetEase and QQ Music among them -- give
> a whole line and no syllables, and that line comes with its own
> invisible characters. Cleaned before it is cut, or every word
> cut off it keeps one and carries it back out on export.

**line 187** — before `if doc.get("_maker") and not meta.get("SyncedBy"):`

> Whoever timed this copy, under the one name the editor writes back out.
> The parser files it as `_maker` because that is what the player's credit
> line reads; keeping it under both would put the name in the file twice.


## module level

**line 197** — before `TAIL_MARKS = "?!:;»"`

> French sets its high punctuation off with a space before it -- "Pourquoi ?",
> never "Pourquoi?" -- and stands its guillemets off the same way, « like so ».
> Cut a line on whitespace alone and that space ends a word, so the mark
> becomes a word in its own right: a chip of its own to click, a span of its
> own to time, and a highlight that crawls across a lone question mark while
> the singer is already a word further on. It belongs to the word it follows.
>
> The mark rarely stands alone. A question asked inside quotation marks ends
> `Pourquoi ?"`, and one asked inside an ad-lib ends `Pourquoi ?)`: the chunk
> the space cut off carries the mark that closes the quote or the bracket too,
> and it is no more a word than the bare `?` was. So what is asked of it is
> that it OPEN with a spaced-away mark and hold no word at all -- `:"bon"`
> opens a quotation and is a word, and must not be dragged back a word.


## `_group_in`

**line 281** — before `part = bool(y.get("IsPartOfWord")) and not SL.word_ends(y.get("Text", ""), nxt)`

> Some sources spell the word break in the syllable's own padding --
> "Did \u200b", "we" -- and mark it part-of-word anyway. The padding
> is cleaned off here, so the break is read out of it first or the
> words arrive glued: "Didwe".

**line 299** — before `got.lead_in = bool(g.get("LeadIn"))`

> Nothing timed to read it off, so the file's own word for it: the
> parser sets this from where the ad-lib is written inside the <p>.


## `to_body`

**line 310** — before `if ln.lead.syls:`

> Whether or not a single syllable of it has a time yet. A line still
> being written is the ordinary state of a document in this editor --
> every autosave and every backup is one -- and a lead written out as
> its line text alone came back with its words joined up again, all
> the splits gone.

**line 332** — before `word = any(isinstance(y.get("StartTime"), (int, float))`

> Timed syllables, not merely syllables: since an untimed lead is written
> out too, the shape no longer says whether anything was word-synced, and
> a document claiming Word timing over spans that carry none is a lie both
> to this project's renderer and to anything else that reads the file.


---

## Lift — 2026-10-25

Docstrings shortened in `editor/model.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The document being edited, and every operation that changes it.
>
> The shape is the one the rest of the project already speaks -- a line holds a
> Lead group of syllables and any number of Background groups, and a syllable
> carries its text, its times and whether the next syllable is glued to it
> (`part`, the document's IsPartOfWord). A *word* is not stored anywhere: it is
> the maximal run of syllables joined by that flag, which is what makes
> "split this word into syllables" a change to one flag rather than a change of
> representation.
>
> Nothing here knows about Qt, audio or the network, so the operations can be
> tested on their own and the undo stack can be a plain list of snapshots.

### `Group`

**line 41** — from the docstring, `class Group:`

> One voice inside a line: the lead, or one backing run.
>
> `lead_in` marks a backing run that comes in BEFORE the words it answers --
> "(Promise I like it like—) Promise I like it like that". The player
> already reads those first (spicy_lyrics.timeline, BG_LEAD), so the editor
> has to remember which they are or a round trip through the text tab would
> move the ad-lib to the end of the line it opens.

### `Doc`

**line 128** — from the docstring, `class Doc:`

> A whole lyric: the lines, and what the file says about the song.
>
> `parts` are the runs of lines grouped to be timed as one -- a chorus, a
> hook sung over and over -- each kept as the words its lines sing, one
> tuple of word keys per line (see ops.line_key), never as line numbers.
> Words survive every edit that moves lines about; numbers would have to be
> kept right by each of them. A part holding ops.LIKE is two blocks, the
> second sung like the first in other words (ops.make_alike). The editor's
> own: never written to the file.

### `Doc.clone`

**line 136** — from the docstring, `def clone(self) -> "Doc":`

> An independent copy: every syllable, group and line built afresh.
>
> Taken before every tap, edit and drag, and up to eighty are kept
> each way. `copy.deepcopy` walks the dataclasses through the generic
> machinery -- 10.6ms and 479KB for a hundred lines of sixteen hundred
> syllables, against 1.0ms and 236KB for building them directly.
> Falls back to it if a field has been added that `_CLONED` does not
> know about, rather than quietly leaving it out of every undo.

### `_clean`

**line 257** — from the docstring, `def _clean(text) -> str:`

> A syllable's text, without the invisible characters.
>
> A zero-width space does nothing a reader can see and everything a reader
> cannot: it survives copy and paste, it defeats a word match, and it turns
> up in files nobody put it in. Out it goes.
>
> The player's own rule, borrowed rather than copied, so a document cannot
> read one way here and another way there.

### `_clean_line`

**line 263** — from the docstring, `def _clean_line(text) -> str:`

> A whole line of it, where a zero-width space stands in for a real one.
>
> A line is written with spaces already, so one that is invisible is there
> to hold two words apart -- unlike inside a syllable, where the same mark
> is glue. `SL.unzwsp` knows the difference; it just has to be told which
> of the two it is looking at.

### `timed_only`

**line 352** — from the docstring, `def timed_only(doc: Doc) -> Doc:`

> The document as the player can actually draw it.
>
> A player sweeps syllables; a line with no times has nothing to sweep, and
> a document where NOTHING has times is not a lyric being timed but a block
> of static text -- which is what the reader got, because that is what the
> file said. So the untimed lines are held back until they have times, and
> what goes over is a document that is entirely synced, however little of it
> there is yet.
>
> Not a filter on the way out of the editor: the editor keeps every line,
> timed or not. This is only what the player is shown.

### `from_text`

**line 374** — from the docstring, `def from_text(text: str) -> Doc:`

> Plain pasted lyrics as an untimed document.
>
> The two conventions the editor writes are read back here so a round trip
> through the text tab keeps what the timing tab knows: a line beginning
> `>` is the answering voice, and a (parenthesised) run at either end is a
> backing vocal rather than words the lead sings.
>
> A row that is NOTHING but brackets is the ad-lib of the line above it --
> "Line" and then "(Ad-lib)" under it, the way lyrics are often written --
> and goes onto that line as a backing voice. Only on the first row, with
> no line above, is it a line of its own.

### `_peel_backing`

**line 439** — from the docstring, `def _peel_backing(row: str) -> tuple[str, list[str], list[str]]:`

> Split a line into (lead, ad-libs before it, ad-libs after it).
>
> Both ends, not just the trailing one. Genius writes an answering voice at
> whichever end it sounds -- "(Promise I like it like—) Promise I like it
> like that" is 21 lines of one song -- and taking only the trailing ones
> left those ad-libs sitting inside the lead, sung by the wrong voice.
>
> A bracket in the MIDDLE is still left alone: there it is far more often
> part of the lyric than an ad-lib, and a wrong guess silently moves words
> out of the line the singer sings.

### `ensure_unique`

**line 510** — from the docstring, `def ensure_unique(doc: Doc) -> int:`

> Give every line that shares a uid with an earlier one a fresh uid.
>
> Splitting and duplicating copy a line with `copy.deepcopy`, uid and all,
> and two lines with one uid are one line to a shared session. The first
> keeps it -- that is the line that was there -- and the copy is new.
> Returns how many were renamed.

---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/model.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### `Line`

**line 95** — before `agent: str = "v1"`

> "v1" is the voice that opens the song and "v2" is the answering one,
> which is what a player mirrors to the other side of the screen. Kept as
> the TTML agent id rather than a bool so a third voice can be added
> without changing the shape of everything that reads it.

**line 100** — before `start: float | None = None`

> Only used while a line has no timed syllables at all: a line-synced
> document still has to remember where its line goes.


### module level

**line 155** — before `# --------------------------------------------------------------------------`

> document <-> the shape everything else in the project passes around


### `from_body`

**line 169** — before `text = str(item.get("Text") or "")`

> Line-timed or unsynced: the words are one untimed run, so every
> editing operation still works on them and timing them later is
> the same job as re-timing anything else.


### `_group_in`

**line 224** — before `syls.append(Syl(_clean(y.get("Text")),`

> Trimmed on the way in: a syllable that carries its own trailing
> space is spelled with a double one, because the space between words
> comes from `part`. Only the edges -- a piece holding two words
> keeps the space in the middle of it.

**line 235** — on `        syls[-1].part = False`

> nothing follows the last one to join

**line 237** — before `first = next((s.start for s in syls if s.timed), None)`

> Read off the times, the same way the player decides which ad-libs to
> print above their line rather than below it.


### `to_body`

**line 254** — before `item["Lead"] = {"Syllables": [], "StartTime": ln.start,`

> No syllable carries a time, but the line does: still a usable
> line-synced line, and the words ride on it untimed.


### `as_text`

**line 361** — before `row = (piece + " " + row) if g.lead_in else (`

> An ad-lib that opens the line is written where it sounds, or a
> trip through this box would move it to the end.


### module level

**line 369** — before `PAIRS = {"(": ")", "（": "）"}`

> The bracket pairs an ad-lib may be written in, matching the ones the TTML
> parser peels off community files (lyric_sources.PAIRS).


### `_peel_backing`

**line 399** — before `if cut < 0 or not lead[cut + 1:].strip():`

> Only when something follows it. A line that is nothing but a
> bracketed run is a backing LINE, and promoting it here would leave
> an empty lead behind.
