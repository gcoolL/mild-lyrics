# `editor/autotime.py`

Comments lifted out of `editor/autotime.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 36** — before `BG_TAIL = 2.0`

> How far past the NEXT line's start an ad-lib may still be ringing. The
> aligner allows itself two seconds to find one after the line it answers
> (generate._window); this is the matching allowance for keeping it.


## `checkpoints`

**line 141** — before `stems=any(k in path.name for k in ("-stem", "-pitch")),`

> the same reading _sync_ckpt uses to pair a model with
> the audio it was trained on


## `Engine.__init__`

**line 163** — before `self.ckpt = str(ckpt or "")`

> "" means whichever the player would pick for this stems setting.

**line 165** — before `self.cut = bool(cut)`

> Cut a whole word into syllables from the model's character path, as
> the player does. Off leaves the words whole and times them as one
> piece each; a word the user has already split is never re-cut
> either way.


## `Engine.time_lines`

**line 260** — before `runs: list[tuple[int, Group]] = []`

> The lead voices of the selection are ONE sequence, in the order they
> are written: that is what stops line two being timed before line one.

**line 282** — before `for i in idx:`

> Backing voices are not in that sequence, because they are not sung
> in it: an ad-lib answers its line from inside or just after it. Each
> is searched inside its own line's span, exactly as the whole-song
> aligner does.

**line 298** — before `prev = next((doc.lines[j].span()[1] for j in range(i - 1, -1, -1)`

> How far back an ad-lib may be found. An answering voice usually
> comes in over the end of the line it answers -- but one marked
> as opening its line sounds BEFORE it, and searching from the
> lead's own start means it can only ever be placed after the
> words it precedes.


## `polish`

**line 420** — before `items, back = [], []`

> ...then settle, over the whole document: it is a cross-line guard, and
> the lines around a re-timed section are part of what it checks.

**line 427** — on `                continue`

> settle cannot read an untimed run

**line 429** — before `continue`

> Backing voices are ordered below instead of by settle.
>
> settle clamps every backing run inside its LEAD's span. An
> ad-lib that opens the line collapses onto the lead's first
> syllable (9.0-10.0s became 10.5-10.5 under a line starting
> at 10.5), and one that answers after the line ends collapses
> onto its last. Neither is what an ad-lib does, and the
> renderer already disagrees with it: _covering widens the <p>
> precisely to hold voices that sound outside the lead.
>
> So they are put in order against the lines around them
> rather than squeezed into the line above them.
