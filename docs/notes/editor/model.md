# `editor/model.py`

Comments lifted out of `editor/model.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `Line`

**line 95** — before `agent: str = "v1"`

> "v1" is the voice that opens the song and "v2" is the answering one,
> which is what a player mirrors to the other side of the screen. Kept as
> the TTML agent id rather than a bool so a third voice can be added
> without changing the shape of everything that reads it.

**line 100** — before `start: float | None = None`

> Only used while a line has no timed syllables at all: a line-synced
> document still has to remember where its line goes.


## module level

**line 155** — before `# --------------------------------------------------------------------------`

> document <-> the shape everything else in the project passes around


## `from_body`

**line 169** — before `text = str(item.get("Text") or "")`

> Line-timed or unsynced: the words are one untimed run, so every
> editing operation still works on them and timing them later is
> the same job as re-timing anything else.


## `_group_in`

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


## `to_body`

**line 254** — before `item["Lead"] = {"Syllables": [], "StartTime": ln.start,`

> No syllable carries a time, but the line does: still a usable
> line-synced line, and the words ride on it untimed.


## `as_text`

**line 361** — before `row = (piece + " " + row) if g.lead_in else (`

> An ad-lib that opens the line is written where it sounds, or a
> trip through this box would move it to the end.


## module level

**line 369** — before `PAIRS = {"(": ")", "（": "）"}`

> The bracket pairs an ad-lib may be written in, matching the ones the TTML
> parser peels off community files (lyric_sources.PAIRS).


## `_peel_backing`

**line 399** — before `if cut < 0 or not lead[cut + 1:].strip():`

> Only when something follows it. A line that is nothing but a
> bracketed run is a backing LINE, and promoting it here would leave
> an empty lead behind.
