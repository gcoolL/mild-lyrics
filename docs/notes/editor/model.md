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
