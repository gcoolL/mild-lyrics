# `editor/ops.py`

Comments lifted out of `editor/ops.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `split_everywhere`

**line 120** — before `bits = SY.bare_pieces(word, list(pieces))`

> The same peel the kept corrections are stored under -- see
> editor.syllables, which owns that store and the reasoning.


## module level

**line 325** — before `def _by_group(doc: Doc, picks):`

> A person who has picked out four words and presses "Join words" means those
> four. Every one of these used to read the CURSOR and ignore the selection
> entirely, so the answer was about one word the user had stopped pointing at.

**line 360** — before `def join_as_one(doc: Doc, idx: int, voice: int, word: int,`

> join_words makes two words ONE WORD of two timings; this makes them one
> TIMING that still reads as two words. "Est-ce que" is sung on a single note
> in about half the French songs that use it, and until now the only way to
> say so was to take the space out -- so the timing was right and the lyric
> was wrong, or the other way about.
>
> The space lives inside the syllable's own text, which is a shape this
> document has had since French's spaced marks: Group.text keeps a syllable
> whole, spicy_lyrics writes it into one <span> and trims only its ends, and
> reading that TTML back gives the same one piece. The player draws the whole
> span as it sweeps, which is what "sung as one" looks like.
>
> The ZERO-WIDTH space does the same job where the words are sung with no gap
> heard between them -- see _spread. This is that with the gap still drawn.
> `note` is handed what was glued, the way the source walk is handed the
> doors that would not open. The window keeps those phrases so the automatic
> split leaves them alone -- see Editor.keep_whole -- and that is the window's
> business rather than the document's, exactly as remembering a hand-made
> split is.


## `set_text`

**line 504** — before `was, old.text = old.text, parts[0]`

> Compared against what it WAS. Assigning first and comparing after
> made the test always true, so a real rewrite reported "nothing
> happened" -- the signal the window reads as a no-op, which pops the
> undo entry it had just pushed and skips the dirty flag and the push
> to the player.


## module level

**line 1171** — before `def _rows_now(doc: Doc, rows) -> list:`

> The word commands learned this a while ago (see _by_group above); the LINE
> commands had not. Every one of them read the CURSOR, so picking out four
> lines and asking for them to be spread, or made into ad-libs, answered
> about one line the user had stopped pointing at and left the other three
> alone -- with no hint that the selection had been ignored.
>
> The catch is that half of these move lines around, so a (line, voice) pair
> noted before the first one runs names a different row by the time the
> second one does. They are addressed by IDENTITY here and looked up again
> each time round, which is the only thing that stays true across an insert.

**line 1333** — before `def _word_syls(doc: Doc, line: int, voice: int, word: int):`

> A word is what a person points at. A syllable is a piece of one, and moving
> or deleting a piece on its own would leave the word spelled wrong -- so
> everything below addresses words, and takes the syllables with them.


## `move_words`

**line 1385** — before `runs = dest.words()`

> Where the destination's own syllables are, before anything moves.

**line 1395** — on `            anchor -= len(run)`

> it is coming out from before the mark


## module level

**line 1421** — before `RADIUS = 0.18`

> How far to look for the landmark a word belongs to. Wider than this and a
> word starts finding the attack of the word after it.

**line 1424** — before `MAX_GAP = 0.35`

> Gaps up to this get closed; anything longer is a silence somebody meant.
> The file this was built against has 301 syllable-to-syllable gaps inside its
> groups and 293 of them are exactly zero, so the rule is not a preference --
> it is what a hand-timed document already looks like. Its line-to-line gaps
> are bimodal with nothing between 0.66 s and 1.40 s, which is where a
> default of a third of a second sits comfortably clear of both.

**line 1496** — before `CONTEST = 0.10`

> How close a second syllable has to be before a mark stops being evidence
> for the first. Measured on `MaKE ME FAMOUSS >_<`: at 0.10 s, 236 of 337
> marks have exactly one syllable near them and 33 have two or more. Widening
> it to 0.18 flips that -- 153 contested against 135 clean -- because the
> marks are denser than the words are. This is the width at which a contest
> is a real ambiguity rather than an artefact of the reach.

**line 1617** — on `TIGHT = 20`

> ms: two marks this close are saying the same thing

**line 1683** — before `WALK_REACH = 0.15`

> How far from the even-share guess a landmark may be and still be taken as
> where that word starts; see `from_first`. The same figure `stranded` calls
> a word worth listening to again, and for the same reason: the measurement
> in `vocalmap` puts a hand-placed word 0.028 s from its nearest landmark
> against 0.040 s for chance, so what a landmark can be trusted to settle is
> a placement that is otherwise a guess, over a radius wide enough to catch
> the right attack and narrow enough to miss the next word's.

**line 1691** — before `WEAK = 0.5`

> What a note onset costs on top of its distance, as a fraction of the reach.
> It is not that the notes are wrong -- on a chopped vocal they are the only
> marks there are -- it is that where an attack is also in range the attack is
> the better answer, and at equal price the walk cannot tell.

**line 1696** — before `WALK_STEP = 0.06`

> The least a word may run for. Two words on the same attack is not a
> timing, and audio.FRAME is 0.02 s, so this is three frames.

**line 1791** — before `SPEED_WORDS = 24`

> How many words the speed is measured over before the search for more of
> them stops. Fewer than this and a line or two of unusual writing -- one
> held note, one run of sixteenths -- moves the median; many more and the
> measurement stops being LOCAL, which is the thing that makes it work on a
> song whose verse and chorus are sung at different speeds. Measured over
> the fourteen songs in `from_first`: 12 and 24 and 48 words all land on the
> same 0.140 s median, and the whole song at once is 0.160 s.

**line 1800** — before `LAST_WORD = 0.12`

> The least the last word of a line may run for, and so how close to the
> hard end the word before it may be put.


## `from_first`

**line 2056** — before `rate = rate_from_marks(`

> Nothing else in the document is timed, so the file has no speed to
> be measured. The vocal still has one -- see `rate_from_marks`. The
> notes are worth having here even where they sit beside an attack,
> because this is a ruler being laid along them rather than a word
> being snapped to one.

**line 2067** — before `return None`

> There is no room for this line before the next one starts, whatever
> it is to be filled with. The same refusal as before.

**line 2072** — before `share = [rate * _sung_syls(g, r) for r in runs]`

> Forward from the anchor at this file's own speed. Nothing here
> divides the room up, so a bound that is really a breath cannot
> squash the line, and a held last word cannot stretch the rest.

**line 2080** — before `if hard is not None and guess and guess[-1] > hard - LAST_WORD:`

> The one limit that still applies: a line may not be laid over the
> line after it, whatever the speed says.

**line 2093** — before `b = _bound(doc, idx, a, exits, least)`

> Nothing in the document is timed enough to say how fast it is sung.
> The even share, which is what this did before there was a speed to
> measure, and the bound it needs.

**line 2109** — before `hurt = {round(m + (bias or 0.0), 6) for m in (weak or ())}`

> A note onset is a landmark of the third kind -- see `vocalmap.marks` --
> and it is not worth what an attack is worth. Measured over the fourteen
> songs: offering every note at the same price as an attack moved three
> points of words out of the 50 ms band, because the walk then takes
> whichever is nearer and there are twice as many of them. `marks` keeps
> that from arising by offering a note only where no attack is within
> `ALONE`; this is the other half of the same judgement, for the notes
> that survive that and still land beside one.

**line 2124** — before `cands.append(sorted(near + [(want, reach)]))`

> The guess itself, priced at the reach: any landmark inside the reach
> is preferred to it, and nothing outside the reach was ever offered.

**line 2130** — before `stops = [t for t in exits if t >= picked[-1] + LAST_WORD`

> Now that there is a guess at where the LAST word starts, the
> question an activity exit answers is a well-posed one: where did
> the singing stop after that? Asked at the top of the line instead
> -- which is all `_bound` can do -- the answer is the first breath
> inside the line, and the line gets squashed into the part of
> itself before somebody took a breath.

**line 2143** — before `share[-1] = max(share[-1], b - picked[-1])`

> The singing goes on to there, so the last word is held to
> there: a line-final word IS held -- a median 23% of its line
> across the songs this was measured on, and 40% on the slow
> ones. Where the only end is the next line, it is not: nothing
> says the singer is still going, and the gap rule below leaves
> the rest as the rest it is.


---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/ops.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### `merge_lines`

**line 314** — before `lead = Group([s for ln in run for s in ln.lead.syls])`

> Each line's last syllable already ends a word -- that is the invariant
> _tidy keeps -- so running them together cannot glue the last word of one
> onto the first word of the next.


### `delete_rows`

**line 410** — before `if not ln.lead.syls and not ln.bg:`

> A line that was only ever its backing voices has nothing left.


### `to_background`

**line 471** — before `if not ln.lead.syls and len(ln.bg) == 1:`

> A line whose every word was an ad-lib is a backing line, not an empty
> one with a passenger: promoting it back keeps the file readable.


### `spread`

**line 557** — before `weights = [max(len(s.text), 1) for s in g.syls]`

> By letters, not by count: "I" and "everything" do not take the same
> time, and length is the only thing known here that says so.


### module level

**line 614** — before `def insert_syllable(doc: Doc, idx: int, voice: int, at: int,`

> What the word menu in the line list needs beyond the operations above. Each
> one is addressed the way the list addresses things -- a line, a voice, and a
> syllable or a word index -- so the menu can hand its own coordinates over
> unchanged.


### `insert_syllable`

**line 632** — on `        g.syls[at - 1].part = False`

> the word before it ends there


### `delete_syllables`

**line 656** — on `            ln.lead = ln.bg.pop(0)`

> a backing voice becomes the line


### module level

**line 700** — before `def reorder_lines(doc: Doc, indices: list[int], to: int) -> str | None:`

> A backing voice belongs to a line, and sometimes to the wrong one: an ad-lib
> that answers the line below, or two of them written in the order they were
> typed rather than the order they are sung. None of that was reachable --
> there was no way to move a backing voice at all.


### `reorder_lines`

**line 718** — on `        return None`

> dropped where it already was


### `move_backing`

**line 743** — before `if not ln.lead.syls and not ln.bg and line != to_line:`

> A line that was nothing but that voice has nothing left in it.


### `split_off_backing`

**line 766** — before `doc.lines.insert(line if g.lead_in else line + 1, made)`

> Before the line if it opens it, after if it answers it.
