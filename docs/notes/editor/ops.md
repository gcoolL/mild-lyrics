# `editor/ops.py`

Comments lifted out of `editor/ops.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `merge_lines`

**line 314** — before `lead = Group([s for ln in run for s in ln.lead.syls])`

> Each line's last syllable already ends a word -- that is the invariant
> _tidy keeps -- so running them together cannot glue the last word of one
> onto the first word of the next.


## `delete_rows`

**line 410** — before `if not ln.lead.syls and not ln.bg:`

> A line that was only ever its backing voices has nothing left.


## `to_background`

**line 471** — before `if not ln.lead.syls and len(ln.bg) == 1:`

> A line whose every word was an ad-lib is a backing line, not an empty
> one with a passenger: promoting it back keeps the file readable.


## `spread`

**line 557** — before `weights = [max(len(s.text), 1) for s in g.syls]`

> By letters, not by count: "I" and "everything" do not take the same
> time, and length is the only thing known here that says so.


## module level

**line 614** — before `def insert_syllable(doc: Doc, idx: int, voice: int, at: int,`

> What the word menu in the line list needs beyond the operations above. Each
> one is addressed the way the list addresses things -- a line, a voice, and a
> syllable or a word index -- so the menu can hand its own coordinates over
> unchanged.


## `insert_syllable`

**line 632** — on `        g.syls[at - 1].part = False`

> the word before it ends there


## `delete_syllables`

**line 656** — on `            ln.lead = ln.bg.pop(0)`

> a backing voice becomes the line


## module level

**line 700** — before `def reorder_lines(doc: Doc, indices: list[int], to: int) -> str | None:`

> A backing voice belongs to a line, and sometimes to the wrong one: an ad-lib
> that answers the line below, or two of them written in the order they were
> typed rather than the order they are sung. None of that was reachable --
> there was no way to move a backing voice at all.


## `reorder_lines`

**line 718** — on `        return None`

> dropped where it already was


## `move_backing`

**line 743** — before `if not ln.lead.syls and not ln.bg and line != to_line:`

> A line that was nothing but that voice has nothing left in it.


## `split_off_backing`

**line 766** — before `doc.lines.insert(line if g.lead_in else line + 1, made)`

> Before the line if it opens it, after if it answers it.
