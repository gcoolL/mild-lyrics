# `editor/ops.py`

Comments lifted out of `editor/ops.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## 2026-10-19 — Genius readings no longer pile onto one kana (`correct_reading`)

Reported with screenshots: 愛あらわに結局は only you, じゃん gave じゃん "Aiarawanikekkyokuwajan"; うんー、POP IN gave "Unpop"/"Untwo"; どこそこ? Loco Moco? gave こ? "koLokomoko". Two causes:
- Guide: when ANY syllable already had a reading, the others' empty readings were the guide, so the whole line was shared over the one read syllable. Now each unread syllable takes the romaniser's reading (`group_readings`) as its guide.
- Latin words: they were dropped from Genius' text by exact match only, so "Lokomoko" (Loco Moco) and "two" (2) stayed in and went to the nearest kana. Now the whole line is aligned against the whole reading with the Latin syllables standing for themselves (`_share` over every syllable, Latin pieces discarded after). Digits are no anchor (14 is sung "juushi"). A seam one letter off a Genius word break moves onto it (`_snap_to_words`), unless both sides already read as the guide ("nattei|ta" stays).
- The word-for-word path is only taken when the Latin words line up exactly (どこそこ? / Loco / Moco? against three Genius words had matched by count alone: "D|o|k|o").
Measured on the 2,047 Genius-romaji lines with Spicy word syncs in the cache (gui.json `genius` × spicy/): 79 lines change, all for the better by eye ("akumanoparty" → "akumano", "storyw|o" → "story|wo", "wakarep|poi" → "wakare|ppoi"). Test: tests/test_roman_share.py.

## 2026-10-14 — readings survive a cut

`_spread` makes new syllables from text and time only, so cutting a piece (syllabify, split_at, cut_syllable, split_everywhere) dropped its reading, and a Genius reading taken before splitting stayed on the line alone. `_deal_roman` shares the cut piece's reading over the new pieces with `_share`, seamed where the romaniser reads them; when no syllable has a reading and the line has one, it is shared out with `correct_reading`. Ctrl+F also matches a row's romanisation, spaces ignored (app `_read_has`).

## Lift — 2026-10-25

Docstrings shortened in `editor/ops.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Every edit the buttons make, as plain functions over a Doc.
>
> Each one takes the document and returns a short sentence saying what it did,
> or None when it could not do anything -- the window turns the first into a
> toast and an undo entry, and the second into a quiet no-op. Keeping them out
> of the widgets is what makes them testable and what makes undo a snapshot of
> one call rather than of whatever the UI happened to touch.
>
> Two rules hold throughout:
>
>   * the last syllable of a group is never `part` -- there is nothing after it
>     to be joined to, and a stray flag there spells the next line's first word
>     onto the end of this one;
>   * times are never invented. An operation that cannot know a time leaves it
>     None, and the timing tab shows untimed pieces as untimed.

### `split_word`

**line 31** — from the docstring, `def split_word(doc: Doc, idx: int, voice: int, syl: int, cut: int) -> str | None:`

> Cut one syllable in two at character `cut`, keeping them one word.
>
> This is the manual half of syllable splitting: the automatic one guesses
> from spelling, and this is for the times it guesses wrong or for a word
> sung across a boundary no dictionary knows about.
>
> The time is split in proportion to the letters, which is a guess -- but a
> guess that puts the new boundary inside the word rather than at one end,
> so nudging it is a nudge and not a rescue.

### `split_at`

**line 52** — from the docstring, `def split_at(doc: Doc, idx: int, voice: int, syl: int,`

> Cut one syllable at the given character offsets, all at once.
>
> The offsets are into the syllable as WRITTEN, which is what a person
> points at. Times are shared out by letters, so the new boundaries land
> inside the word rather than at one end -- close enough that nudging one
> is a nudge and not a rescue.

### `split_everywhere`

**line 115** — from the docstring, `def split_everywhere(doc: Doc, word: str, pieces: list[str],`

> Spell every other copy of this word the same way. Returns how many.
>
> The same word is sung the same way all through a song, so a split made
> once is a decision about the word rather than about the line it happens
> to be on. Matched without regard to case and re-cased onto whatever each
> line actually says, so "Somethin'" follows "somethin'".
>
> Without regard to the punctuation around it either: the word at the end
> of a line wears a comma and the same word in the middle of one does not,
> and a singer does not sing them differently. So "fallin'," is matched by
> a split made on "fallin'", and the marks each copy wears go back on the
> pieces they came off.
>
> A copy that is already split is glued back together first and cut again,
> keeping its span: "apply this everywhere" means everywhere.

### `syllabify`

**line 161** — from the docstring, `def syllabify(doc: Doc, idx: int, voice: int, words: list[int] | None = None,`

> Cut whole words into syllables.
>
> `method` picks the rule -- see editor/syllables.py, which also carries the
> measurement that decided the default. Whatever it answers, the pieces
> rejoin to the word: the split may be wrong, but the lyric cannot change.
>
> Words already cut into pieces are left alone unless `resplit` is asked
> for, because those pieces may have been placed by hand or measured from
> the audio, and re-cutting them throws that away. `resplit` glues them back
> together first, keeping the span, and cuts again.

### `_spread`

**line 265** — from the docstring, `def _spread(pieces: list[str], s: Syl) -> list[Syl]:`

> One syllable's text and time shared out over the pieces it spells.
>
> A piece ending in whitespace is a WORD ending, not a syllable one: the
> space goes, and the flag says so, which is how the line still reads "do
> your" rather than "doyour". A zero-width space means the same boundary
> drawn without a gap, so it stays in the text and the flag does not
> change -- the files this reads use it to hold two words in one timing.

### `merge_syllables`

**line 287** — from the docstring, `def merge_syllables(doc: Doc, idx: int, voice: int, lo: int, hi: int) -> str | None:`

> Glue syllables lo..hi (inclusive) back into one timed piece.
>
> Inside a word the pieces run straight together -- that is what a syllable
> boundary is. ACROSS one the space comes with them, into the text of the
> single piece this becomes: "Est-ce" and "que" sung on one note is
> "Est-ce que", not "Est-ceque", and the lyric may not change just because
> the timing did. Group.text and the TTML writer both keep a syllable's own
> text whole, and absorb_marks has been storing a space inside one since
> French's "Pourquoi ?" -- so this is a shape the document already has.

### `absorb_marks`

**line 320** — from the docstring, `def absorb_marks(doc: Doc, indices=None, gap: str = " ") -> str | None:`

> Take every lone ? ! : ; » back onto the word in front of it.
>
> The repair for a lyric read in before the splitting knew about French --
> "Pourquoi ?" arrives as two words, so the mark gets a chip of its own to
> click and a span of its own to time. This puts it back where it belongs,
> with the space between them kept, so the line still reads "Pourquoi ?" and
> not "Pourquoi?". « takes the word after it the same way.
>
> Not join_words, which is the other thing: that makes two words into one
> word of two timed pieces and takes the space OUT, which is right for a
> word sung across a boundary and wrong for this.
>
> The mark's time is folded into the word's rather than dropped, so nothing
> that was timed comes back untimed.

### `join_run`

**line 382** — from the docstring, `def join_run(doc: Doc, picks) -> str | None:`

> Take the spaces out between the selected words.
>
> They become one word of several timed pieces, which is what join_words
> does for two -- this is the same statement about a whole run. Only words
> that are next to each other can be joined, so a selection with a gap in
> it joins each unbroken stretch and leaves the gaps alone.

### `break_words`

**line 444** — from the docstring, `def break_words(doc: Doc, picks) -> str | None:`

> Put the spaces back inside each selected word -- the inverse of join_run.
>
> Every join WITHIN the word goes, not just the one after it. Breaking only
> after the last syllable is a no-op on a word that already ends a word,
> which is exactly the word somebody has just joined and wants back --
> so "Join words" and "Break word" on the same selection have to be each
> other's undo, and this is what makes them so.

### `end_word`

**line 482** — from the docstring, `def end_word(doc: Doc, idx: int, voice: int, syl: int) -> str | None:`

> Put a space back after this syllable: two words where there was one.
>
> The inverse of join_words, and addressed by SYLLABLE rather than by word
> on purpose -- the boundary being restored is inside a word, so there is no
> word index that names it. Splitting "thereworld" back apart means ending
> the word after "there", and only the syllable knows where that is.

### `set_text`

**line 492** — from the docstring, `def set_text(doc: Doc, idx: int, voice: int, syl: int, text: str) -> str | None:`

> Rewrite one syllable, keeping its times.
>
> Typing a space inside it means two words, so it is taken as such rather
> than stored as a syllable with a space in it -- which no player would
> space correctly. The exception is the space French puts BEFORE a mark
> like ? or !, which belongs to the word in front of it and is kept there;
> see model.words_in.

### `duplicate_rows`

**line 581** — from the docstring, `def duplicate_rows(doc: Doc, rows) -> str | None:`

> Copy what is selected, in place.
>
> Same rule as deleting: a selected backing voice is copied on its own, a
> selected lead copies its whole line. Times come with the copy -- a
> duplicated line is nearly always about to be moved somewhere else in
> time, and starting from the times it had is a shorter trip than starting
> from nothing.

### `delete_rows`

**line 612** — from the docstring, `def delete_rows(doc: Doc, rows) -> str | None:`

> Delete what is selected -- rows, not lines.
>
> A backing voice is its own row and its own selection, so deleting one has
> to remove that voice and nothing else. Sending its LINE number to
> delete_lines took the words it was answering with it, which is not what
> anybody pointing at an ad-lib meant.
>
> A line goes only when its lead is what was selected. Selecting a lead
> takes the whole line, ad-libs and all, because they belong to it.

### `swap_agents`

**line 693** — from the docstring, `def swap_agents(doc: Doc, indices=None) -> str | None:`

> Put every line on the other side: main becomes duet, duet becomes main.
>
> A swap, not a stripe. Striping every other line was a CONVENTION applied
> to a song nobody had read -- it says nothing true about who sings what,
> and on a lyric that already had its sides marked it threw that reading
> away. Swapping keeps the reading and only mirrors it, which is the thing
> anybody actually wants when the two voices came in the wrong way round.

### `sweep`

**line 752** — from the docstring, `def sweep(doc: Doc, idx: int, voice: int, frm: int, to: int,`

> Stamp the syllables crossed between two moments of one drag.
>
> The pointer was on `frm` at `t_from` and is on `to` at `t_to`; everything
> between them was crossed on the way and nobody can say exactly when. The
> boundaries are shared out evenly over the interval, which is the only
> honest answer -- and over one mouse move it is a few milliseconds wide, so
> the guess is only visible on a flick that skips half a line.
>
> `to` is left OPEN: it starts at `t_to` and ends there too, until the drag
> either crosses out of it or lets go. A syllable under the pointer has not
> finished being sung yet.
>
> Backwards is not this function's job -- see `untime`.

### `untime`

**line 769** — from the docstring, `def untime(doc: Doc, idx: int, voice: int, syls) -> str | None:`

> Forget the times of named syllables, leaving the rest of the row alone.
>
> `clear_times` is the whole-row version. This one exists for a drag that
> is wound back over its own tracks: only what that pass stamped is given
> up, so backing up over words that were timed before the drag started does
> not quietly throw their times away.

### `spread`

**line 813** — from the docstring, `def spread(doc: Doc, idx: int, voice: int = 0) -> str | None:`

> Share a line's span out evenly over its syllables.
>
> A starting point for hand timing, and the honest thing to do with a line
> that is line-synced and has to become word-synced: every syllable gets an
> equal slice, which is wrong everywhere and wrong by a little, rather than
> right at the start and drifting.

### `snap_line_ends`

**line 856** — from the docstring, `def snap_line_ends(doc: Doc) -> str | None:`

> Stop every LEAD line before the next one starts.
>
> Two lines lit at once is the fault a reader notices first, and it is easy
> to make by hand: a line held open runs into the line after it. Nothing is
> moved except an end that was already too late.
>
> Ad-libs are left exactly where they are. A backing vocal ringing on past
> the line it answers -- into the next line, and sometimes through it -- is
> not a mistake to be tidied away; it is what the singer did, and it is
> half the reason a document has backing groups at all. This used to walk
> ln.groups(), which is the lead AND every ad-lib, so one press cropped
> every held answer in the song back to the next line's first word.
>
> The next line's LEAD start is the boundary, for the same reason: an
> ad-lib that opens the next line early must not drag this line's end back
> with it.

### `insert_syllable`

**line 878** — from the docstring, `def insert_syllable(doc: Doc, idx: int, voice: int, at: int,`

> A new untimed syllable at position `at`, its own word.
>
> Untimed on purpose: a word that was not sung has no time, and giving it
> one borrowed from a neighbour would put a syllable on screen at a moment
> nobody sang it. The timing tab shows it in the loose row until it is
> given one.

### `move_word`

**line 920** — from the docstring, `def move_word(doc: Doc, idx: int, voice: int, word: int, delta: int) -> str | None:`

> Send a word to the end of the line above, or the start of the one below.
>
> The times go with it, because they are still when it was sung -- moving a
> word between lines is a statement about which line it BELONGS to, not
> about when it happened. It only ever moves between the leads: an ad-lib
> that wants to be in another line is a different operation (to_lead, then
> this, then to_background).

### `adlib_to_line`

**line 1016** — from the docstring, `def adlib_to_line(doc: Doc, line: int, voice: int) -> str | None:`

> Make a backing voice an ordinary line of its own.
>
> Not split_off_backing, which is the other half of the pair: that gives it
> a row of its own and leaves it a backing voice, which is right for an
> ad-lib that only ever answers. This is for the case where a run was read
> as an ad-lib and is not one -- a second singer's line, a hook, a bracket
> in the source that meant something else. It becomes a lead, so it is sung
> rather than answered, and it keeps its times because when it sounds is a
> measurement either way.

### `split_backing_on`

**line 1038** — from the docstring, `def split_backing_on(doc: Doc, line: int, voice: int,`

> Cut one backing voice into several, wherever it is punctuated.
>
> `Lyric (Lyric; Lyric)` is two answers written in one bracket, and read in
> as one it is one run of words with one span -- so the two get a single
> highlight sweeping across both, and no way to time them apart. This
> separates them into a backing voice each, so each has its own span.
>
> Times come with the words. The separator itself goes: it was punctuation
> between two things, and once they are two things there is nothing left
> for it to separate.

### `merge_runs`

**line 1131** — from the docstring, `def merge_runs(doc: Doc, lines) -> str | None:`

> Run each unbroken stretch of the selected lines together.
>
> Not the span from the first to the last: a selection with a gap in it
> used to swallow the lines nobody had picked, which is the one mistake
> here that cannot be seen at a glance afterwards. Each run is merged on
> its own, exactly like join_run does for words.

### `move_rows`

**line 1151** — from the docstring, `def move_rows(doc: Doc, rows, delta: int) -> str | None:`

> Move what is selected, up or down.
>
> A selection made only of backing voices moves among its line's own
> voices, because that is the only direction an ad-lib has; anything with
> a lead in it moves whole lines. The ribbon's arrows have always done
> this and the menu's had not, so the same two words meant two things
> depending on which one was used.

### `lines_to_backing`

**line 1202** — from the docstring, `def lines_to_backing(doc: Doc, lines, delta: int) -> str | None:`

> Make each selected LEAD line an ad-lib of its neighbour.
>
> Walked from the neighbour outwards -- upwards for the line above,
> downwards for the line below -- so a block of four selected lines all
> end up answering the one line outside the block, rather than the second
> disappearing into the first the moment the first stops being a line.

### `_nearest`

**line 1319** — from the docstring, `def _nearest(marks: list[float], t: float, floor: float | None = None):`

> The mark closest to `t`, ignoring any before `floor`.
>
> The floor is applied by starting the search at it rather than by throwing
> candidates away afterwards -- a filter over the two marks either side of
> `t` returns nothing when both are behind the floor, and the answer was
> the next one along.

### `vocal_bias`

**line 1335** — from the docstring, `def vocal_bias(doc: Doc, indices, starts: list[float],`

> How far this document's words sit from the landmarks, and how many voted.
>
> A file has a house style. This one's words sit about 0.03 s AHEAD of the attack, every
> one of them, on every setting the measurement was run at -- that is not an
> error to be corrected, it is where this person puts a word, and a snap
> that ignored it would drag the whole song 30 ms late in the name of
> tidiness. So the median is measured and then preserved: what gets removed
> is the scatter around it, not the offset itself.

### `claims`

**line 1374** — from the docstring, `def claims(doc: Doc, indices, starts: list[float],`

> Which mark belongs to which syllable, where that is not in doubt.
>
> THE MISTAKE THIS EXISTS TO STOP. In "I'm goin' insane, she might", the
> document has `sane,` at 20.322 and `she` at 20.387, and the vocal offers
> ONE mark, at 20.387. Both syllables are within a breath of it. The old
> rule handed it to whichever was nearer and moved that word onto it, which
> put `she` on an attack that a listener can hear is the /s/ of `sane` --
> reported, correctly, as "it decided to snap to she".
>
> No rule over unlabelled attacks can tell those two apart; that needs the
> lyric, which is what the sync model is for. What a rule CAN do is notice
> that the mark has two claimants and decline to use it for either. A mark
> is kept only when exactly one timed syllable in the document lies within
> `contest` of it -- and then it belongs to that syllable and to nothing
> else.
>
> Marks with NO syllable near them are dropped too. Those are real events
> in the audio -- a breath, a hi-hat leaking through the separation, a
> consonant in a word nobody has timed yet -- and a word reaching out to
> one is reaching for something the document has no account of.
>
> Returns {"owner": {biased mark: the syllable start it belongs to},
>          "contested": [...], "orphan": [...], "bias": the offset used,
>          "usable": {the ORIGINAL, unbiased marks that are owned}}.
>
> Both keyings are handed back on purpose. Snapping works in biased time,
> because that is where the answer has to land; the strip draws the marks
> it was given by `vocalmap`, which are unbiased. Returning one and letting
> the caller derive the other is how the strip came to draw every mark as
> contested -- the membership test compared two different numbers and was
> quietly never true.

### `consistency`

**line 1400** — from the docstring, `def consistency(doc: Doc, indices, starts: list[float],`

> How much this song's marks can be trusted, measured on the song itself.
>
> A song repeats itself. When the same word is sung again, the vocal ought
> to put a mark in the same place relative to it -- and where it does not,
> the marks are telling you about this delivery of this line rather than
> about where the word is.
>
> That is the number somebody needs before believing any of this, and it
> can only be had per song. On `MaKE ME FAMOUSS >_<`: of 32 words sung
> three or more times, twelve agree across their repeats to within 20 ms,
> the median spread is 25 ms, and the worst is `famous` at 130 ms -- sung
> six times, marked four, at +100, -30, +100 and +0 ms. `might` and `drive`
> are +0 every time. Same song, same picture, and no threshold separates
> the two groups, because the difference is in how the line was sung.
>
> Returns {"covered": share of word heads with a mark of their own,
>          "words": [(word, times sung, offsets in ms, spread in ms)],
>          "tight": how many of those agree within TIGHT,
>          "spread": the median spread}.

### `fill_gaps`

**line 1440** — from the docstring, `def fill_gaps(doc: Doc, indices, max_gap: float = MAX_GAP) -> str | None:`

> Close the small holes between words; leave the rests alone.
>
> No audio in this one, which is why it outlived the snapping it was built
> beside. A hand-timed document is contiguous inside a phrase --
> the file this was measured against has 301 syllable-to-syllable gaps and
> 293 of them are exactly zero -- so a hole of a few tens of milliseconds is
> almost always an artefact of how the times were made rather than something
> somebody sang. Above `max_gap` it is a rest, and filling a rest lights a
> word through a bar nobody is singing in.
>
> A pair that already overlapped keeps its overlap: a syllable held over the
> ones after it is the singer's doing, and this is not the place to tidy it.

### `stranded`

**line 1458** — from the docstring, `def stranded(doc: Doc, indices, starts: list[float], reach: float = 0.15,`

> The words sitting further than `reach` from anything the vocal does.
>
> This is what the measurement actually supports, and it is deliberately a
> QUESTION rather than an edit. Against the hand timing of `MaKE ME FAMOUSS
> >_<`, the nearest landmark puts a word within 0.028 s of where they put it
> and chance alone manages 0.040 s -- real information, and nowhere near
> enough to move a word by. What survives that is the other end of the
> distribution: a word 0.15 s from every attack and every entrance in
> earshot is a word worth listening to again, and pointing at it costs
> nothing if it turns out to be fine.
>
> Returns (line, voice, word, distance), worst first.

### `_walk_dp`

**line 1496** — from the docstring, `def _walk_dp(guesses: list[float], cands: list[list[tuple[float, float]]],`

> Pick one candidate per word, in order, for the least total cost.
>
> A greedy nearest-landmark pass cannot do this: the attack nearest word
> three may be the one word two has to have, and a greedy walk takes it and
> then has nowhere to put word two but after it. Choosing all of them at
> once is a shortest path over at most a few dozen states either way, so it
> costs nothing to be right about.

### `_bound`

**line 1528** — from the docstring, `def _bound(doc: Doc, idx: int, a: float, ends, least: float):`

> When the line starting at `a` has to be over by.
>
> Three answers and the earliest of them wins, because each is a real limit
> and a line spread past any of them is spread over something else:
>
>   * the line's own end, where the document has one;
>   * the next timed line's start, where there is one;
>   * where the VOCAL stops, which is the one that works on a song being
>     timed from the top. That is the case the first two have nothing to
>     say about -- nothing after the line is timed yet, because the line is
>     the furthest anybody has got -- and it is exactly the case somebody
>     pressing this button is in.
>
> The vocal's answer is worth having even when a document bound exists. An
> activity exit is where the singing stopped; the next line's start is
> where the next singing began, and the rest in between belongs to neither.
> Spreading a line across it hangs its last words in silence.
>
> `least` is how much room the words need, so an activity exit a fraction
> of a second after the anchor -- the singer taking a breath inside the
> first word -- is not read as the end of the line.

### `_room`

**line 1537** — from the docstring, `def _room(doc: Doc, idx: int, a: float) -> float | None:`

> The hard end: the next timed line, or what the document already says.
>
> No vocal in it. An activity exit is evidence about where the SINGING
> stopped and it is read as that below, once there is a guess at where the
> last word starts; this is the other kind of limit, the one that says a
> line may not be spread over the line after it however the singing goes.

### `_sung_syls`

**line 1550** — from the docstring, `def _sung_syls(g: Group, run: list[int]) -> int:`

> How many syllables the singer has to get through in this word.
>
> A word somebody has already cut into pieces is that many, because that is
> a person's answer to this question and it beats a rule. An uncut one goes
> to `syllables.split`, the project's own sung rule -- 86% agreement with
> the splits in this folder's hand-timed files, and its errors are cuts
> where a person left a word whole, which costs a fraction of a syllable
> here rather than a wrong word.

### `speed`

**line 1563** — from the docstring, `def speed(doc: Doc, idx: int, voice: int = 0,`

> How long a syllable takes in this file, measured nearest to line `idx`.
>
> Returns (seconds per syllable, how many words voted), or (None, 0) when
> nothing in the document is timed enough to say.
>
> WHAT IS MEASURED. The STEP from one word's start to the next word's
> start, divided by the syllables in the first -- not the word's own
> length. It is the step that gets extrapolated, and a step carries the
> small rest after a word with it, which a duration does not. Measured
> across fourteen songs it is worth 0.010 s of median error.
>
> The LAST word of a line is never counted. A line-final word is held --
> across those same songs it takes a median 23% of its line, and on the
> slower ones (`C U Again`, `Eternal`, `bipolar`) 38 to 41% -- and letting
> that into the average would slow every other word down to pay for it.
>
> Lines are read outwards from `idx` and the search stops as soon as `want`
> words have voted, so a chorus is timed at the speed of the lines around
> it. A song is not one speed: across the fourteen the median sits between
> 0.14 s a syllable (`one of wun`, `FE!N`) and 0.41 s (`bipolar`), and it
> moves that far WITHIN a song when a verse gives way to a drop.

### `rate_from_marks`

**line 1594** — from the docstring, `def rate_from_marks(a: float, need: list[int], marks: list[float],`

> How fast this ONE line is sung, read off the vocal's own landmarks.
>
> For the case `speed` cannot answer: the first line of a fresh file, where
> nothing else in the document is timed and there is no house speed to
> measure. That case fell back to an even share of the room by letter
> count, which is the worst thing in this module -- 0.470 s of median error
> against the 0.140 s the speed gets -- and it is also the case somebody
> meets FIRST, on every song they open.
>
> The landmarks can answer it. Lay the words out at every speed from a
> sixteenth to a slow half-second a syllable, ask how near each speed's
> word starts fall to a mark, and keep the best: a ruler laid along a row
> of ticks, where the ticks are the places the singing does something.
> Measured over fourteen songs with everything stripped but each line's
> first word, which is what that case looks like:
>
>                          median   within 50ms   within 100ms
>     even share           0.470s        7%            14%
>     speed off the marks  0.283s       11%            24%
>
> Better on twelve of the fourteen. It is still not a timing anybody would
> keep; what it is is a first pass whose words sit in roughly the right
> places rather than spread evenly across a line nobody sang evenly.
>
> The cost is per word rather than per line, or a slow speed would win by
> covering less ground and being judged on fewer words. A mark further away
> than `reach` is not offered at all, so a speed is scored on the words it
> puts right and not punished twice over for the ones it misses.

### `from_first`

**line 1631** — from the docstring, `def from_first(doc: Doc, idx: int, voice: int = 0,`

> Time the rest of a line from its first word and the speed it is sung at.
>
> WHAT THIS IS AND IS NOT. It is a better starting point than an even share.
> It is not a placement, and if there is a trained checkpoint on the machine
> the model is the thing to use instead -- this is for the case where there
> is not, or where somebody wants a first pass to drag into shape.
>
> THE SHAPE. Lay the words forward from the anchor at the speed the file is
> sung at -- `speed`, seconds per syllable, measured on the timed lines
> nearest this one -- and then let the vocal move each of them to the
> nearest thing it actually does, in order and never past its neighbours.
> The last word gets whatever is left, because a line-final word is held.
>
> Measured against fourteen hand-timed files that have a copy of their
> recording on this machine, each line in turn stripped back to its first
> word and re-timed with the rest of the document left as it is, every
> other word compared with where it really is -- 4161 words:
>
>                          median   within 50ms   within 100ms
>     even share           0.467s       9%            15%
>     at the file's speed  0.140s      27%            41%
>
> It is better on all fourteen, from 0.288 -> 0.182 on `Love Blur` to
> 1.198 -> 0.111 on `bipolar`, and the line's own end comes with it: the
> last word now stops a median 0.260 s from where it should against 1.236 s
> before.
>
> WHY THE EVEN SHARE WAS THAT BAD is worth saying plainly, because it had a
> measurement of its own and that measurement was not wrong -- it was taken
> on two songs that happen not to do either of these things. Dividing the
> room between the words by their letter counts gets two things wrong at
> once:
>
>   * A LINE-FINAL WORD IS HELD. Across these fourteen it takes a median
>     23% of its line, and 40% on the slow ones. Four letters of `line` out
>     of the twenty-five in "I'll stay till the finish line" ask for 16% of
>     the line where it really takes 35%, and every word before it is
>     pushed late to pay the difference.
>   * THE ROOM WAS WRONG. Its end was the first place the vocal stops after
>     the line starts, which on a line with a breath in it is the breath.
>     Ten of the twenty-six lines of `C U Again` are cut short that way,
>     one of them by 4.7 s, and the whole line is squashed into the part of
>     itself before the singer breathed. Asking that question at the top of
>     a line is what makes it unanswerable; once the words are laid out
>     there IS a last word, and the exit to look for is the first one after
>     THAT. Only the next timed line is a limit from the start, and it is
>     the only one still applied before the walk.
>
> WHAT THE PIECES ARE WORTH, each changed on its own, same 4161 words:
>
>     as written                   0.140s      27%
>     weighed by letters           0.159s      24%
>     weighed per word             0.201s      21%
>     speed over the whole song    0.160s      24%
>     speed from word lengths      0.150s      26%
>     without the vocal snap       0.138s      24%
>
> So nearly all of it is the speed, and the marks are worth three points of
> words landing exactly right for a hair of median -- which is the trade
> `vocalmap` describes and the reason the snap stays.
>
> The reason the marks are worth no more than that is in `vocalmap`'s own
> numbers. The nearest landmark to a hand-placed word is 0.033s away and
> 60% of them are within 50ms, so the marks know where the words are --
> what is missing is which mark belongs to which word. Choosing that from
> the words' letter counts was tried three ways (absolute, squared and log
> duration cost) at three mark densities, and the best of the nine is
> 0.193s against that 0.033s ceiling. The information is there and the
> letter counts cannot get at it. Whatever improves this will be a better
> model of how long a word takes, not more marks: dropping the flux floor
> from 0.45 to 0.25 nearly triples the marks, lifts the ceiling to 0.020s,
> and makes the answer WORSE. That was written before there was a speed to
> measure, and the speed is exactly the better model it asks for.
>
> A landmark further than `reach` from where the speed put a word is not
> offered at all, which is what keeps a fifth of a second from becoming a
> second. The first word is the anchor and is never moved -- it is the one
> time in the line somebody placed by ear, and it is also what tells this
> where the line begins.
>
> A document with nothing else timed in it has no speed to measure, and
> then this is the even share it always was, bound and all. That is the
> first line of a fresh file and not much else: by the second line there is
> something to measure.
>
> Reading the bias rather than removing it, for the reason `vocal_bias`
> gives: this file's words sit a consistent 0.03 s ahead of the attack they
> belong to, that is where their author puts a word, and the landmarks are
> aimed accordingly.
>
> Words are laid end to end, because a hand-timed line is contiguous inside
> a phrase -- but only where the join is a join. A hole longer than `gap` is
> a rest somebody is not singing in, and the word before it keeps its own
> length rather than being held open across it. That is `fill_gaps`'
> threshold and the same judgement.

### `line_reading`

**line 1798** — from the docstring, `def line_reading(g: Group, ja: bool) -> str:`

> A whole voice's reading, spaced into words.
>
> Japanese is not spaced, so the player's read_line -- which reads a line
> a spaced word at a time -- runs a whole line together: "kiminokoegamada".
> A Japanese line is read a pykakasi segment at a time instead, which is
> the nearest thing to a word the romaniser knows about, with the
> particles read the way they are sung.

### `repeat_source`

**line 1932** — from the docstring, `def repeat_source(doc: Doc, idx: int) -> int | None:`

> The nearest EARLIER line that sings the same words and is timed.
>
> The same words, not the same syllables: a chorus split by hand the first
> time and still whole the second is still the chorus, and fill_from_repeat
> cuts the second one the way the first was cut. Every syllable of the
> earlier lead has to have a time -- half a chorus is not something to copy
> a whole one from. None where there is no such line.

### `fill_from_repeat`

**line 1989** — from the docstring, `def fill_from_repeat(doc: Doc, idx: int) -> str | None:`

> Time a line that repeats an earlier one from ONE syllable of its own.
>
> A chorus is sung the same way every time it comes round, near enough that
> the earlier timing, moved to where this one starts, is the answer or a
> nudge away from it. So what this line needs is one time: the first of its
> syllables that has one -- usually the one just tapped. Everything else in
> the line, times it already had included, is the earlier line's, shifted
> by however far apart the two anchors are; with more than one syllable
> timed, only the first counts.
>
> Only from a line that is ALREADY timed, and earlier in the song: see
> repeat_source. The backing voices come along where the earlier line has
> the same ones, in the same order.

### `_units`

**line 2112** — from the docstring, `def _units(doc: Doc, g: Group, ja: bool | None = None,`

> A voice's sung syllables, in order: (its chip, where the syllable
> starts in it, where it ends), as fractions of the chip by letters.
>
> A chip that is a whole word nobody has cut holds as many as the
> syllable rule cuts it into -- a song not split yet still knows that
> "shadow" is two. Any other chip is one: a syllable, a word cut by hand,
> words sung as one.

### `_reach`

**line 2234** — from the docstring, `def _reach(doc: Doc, keys: tuple, at: int, shape: list, counts: list,`

> How many of the group's lines, from its first, are sung from line at.
>
> The first by its words. After it a line also counts where its words are
> others but it is sung in as many syllables as the group's line (`shape`):
> the last chorus that sings "fighting with" where the others sang "hiding
> like" is sung the same, and is still the chorus. Such a line at the END
> of the run has to keep half the group's line's words, though: after it
> there is nothing in the group's words to say the singer is still in the
> chorus, and a chorus cut short is often followed by a verse line that
> only happens to be as long.

### `part_runs`

**line 2287** — from the docstring, `def part_runs(doc: Doc) -> list:`

> Every place a group is sung, as (part, first line, how many lines).
>
> From the group's FIRST line, all of it or the start of it: a chorus cut
> short at the end of a verse, or the intro that is its first three lines,
> is still the chorus. Two lines at least, where the group has two -- one
> line sung again is a repeat, which repeat_source already answers, and a
> hook sung three times running would otherwise be a run of its own on
> every line of it. A line inside may sing other words in as many
> syllables (see _reach and by_syllables).
>
> A group of lines sung alike (LIKE) is sung wherever any of its blocks
> is, each by its own words or in the syllables of any of them.
>
> The longest runs are taken first, and no line is in two. That is what a
> run of identical lines needs: grouped as "hook, hook, then the answer",
> four hooks and the answer is ONE run, on the last three hooks -- taken
> from the left, the first two hooks would match the start of the group,
> claim it, and leave the answer stranded on a line nothing groups.

### `part_source`

**line 2341** — from the docstring, `def part_source(doc: Doc, n: int, at: int, size: int) -> int | None:`

> Where to copy a run of group n at line `at`, `size` lines long, from.
>
> Another run of the same group, at least as long, with every lead syllable
> of its first `size` lines timed -- the place it was grouped, or a run
> already filled. A run, and its START: three identical lines at the end of
> a chorus sing the same words as three at its beginning, but not with the
> same gaps, and a run copies the gaps too. The nearest one before it first,
> as repeat_source does: a singer drifts over a song, and the last chorus is
> the best guess at the next. Then the nearest after, for the intro that
> only the first chorus can time.
>
> For lines sung alike, anywhere any of the group's blocks is sung as
> well, run or not: lines sung like two lines of the chorus have those two
> inside the chorus's run to copy from.

### `make_alike`

**line 2526** — from the docstring, `def make_alike(doc: Doc, lines: list, q: int) -> str | None:`

> The lines from the first of `lines` to the last, sung like the as
> many lines from q: other words, the same tune, a syllable for each
> syllable.
>
> Lines sung alike are a group with a block for each stretch of them, all
> alike: any of them timed times the others, one tap on a first syllable
> each, gaps and all, as a chorus is. So picking adds to what is there --
> lines already sung like others keep them, and two groups the pick joins
> become one. Lines sung like the start of a chorus join the chorus. Lines
> that carry on two stretches already paired, both of them, grow those
> stretches (line 19 like line 3, under lines 17–18 like 1–2, is lines
> 17–19 like 1–3); lines that cover a stretch sung like others take its
> place. A stretch that has had its first syllable tapped and nothing
> else is timed there and then.

### `auto_parts`

**line 2700** — from the docstring, `def auto_parts(doc: Doc) -> str | None:`

> Lines ▸ Group, for the whole song at once: every block of two or more
> lines that is sung again becomes a group -- the choruses, a refrain, a
> pre-chorus that comes back -- so each is timed once. A line of a block
> that comes back in other words, sung in as many syllables, is still in
> it, and said to be.
>
> The block that saves the most lines goes first (its length times the
> times it comes back), and no line is in two: a chorus whose last two
> lines are also the end of the bridge is the chorus. Groups already made
> by hand are kept, and nothing is grouped across them.

### `fill_part`

**line 2816** — from the docstring, `def fill_part(doc: Doc, idx: int) -> str | None:`

> Time a whole run of a group from ONE syllable in it.
>
> fill_from_repeat for a chorus at once: the first timed lead syllable in
> the run, in line order, is where the run is; every line of it -- before
> that syllable's line as well as after -- takes the times of the same
> line where the group was last sung, moved by the same amount. One shift
> for the run, not one per line: the gaps between the lines are the
> source's, and those are as much the chorus as the words.
>
> A line that cannot be cut into the source line's syllables is left as it
> was and named; the run is filled round it.

### `correct_reading`

**line 2875** — from the docstring, `def correct_reading(doc: Doc, idx: int, voice: int, text: str) -> str | None:`

> Put a voice's reading right from a better one (Genius'), in place.
>
> A voice read syllable by syllable keeps being read that way: the new
> reading is shared out over the SAME syllables. Word by word first, where
> the new reading has as many words as the line -- a seam between words is
> then never in doubt -- and inside a word by lining the old reading up
> against the new one letter by letter: where they agree the seam stays
> exactly where it was, where they do not it moves in proportion. So
> "to|kyo he" put right by "Toukyou e" is "Tou|kyou e", and nothing about
> which syllable carries what is guessed afresh. A voice with only a line
> reading has that replaced. Where the new reading cannot be shared out --
> fewer letters than syllables to give them to -- it becomes the line
> reading and the syllables are left alone.

### `gather_adlibs`

**line 3050** — from the docstring, `def gather_adlibs(doc: Doc, idx: int, how: str = "gather") -> str | None:`

> Take a line's bracketed runs out of its lead and make them ad-libs.
>
> `how` is "gather" -- ONE ad-lib after the line, "Okay, uh, your mind": a
> comma between each run's words, and each run after the first lowercased
> because it is now the middle of a phrase -- or "separate", one ad-lib per
> run as written. An ad-lib the line already had joins the gathered one.
> The times ride along on the syllables.

### `rewrite_line`

**line 3109** — from the docstring, `def rewrite_line(doc: Doc, idx: int, text: str) -> str | None:`

> Replace a line with what was typed for it, keeping the times of every
> word that is still there.
>
> The text is read the way the text tab reads it -- brackets at the ends are
> ad-libs -- and each word takes the times of the same word in the old line,
> in order. A word whose spelling only changed in case or punctuation keeps
> them too; one that is really new comes back untimed.

### module level (comment)

**line 1737** — before `PARTICLES_WRITTEN = {"は": "ha", "へ": "he", "を": "wo"}`

> ------------------------------------------------------------- romanisation
> How a line is read, for a lyric in a script that needs one. Each syllable
> can carry its own reading (Syl.roman), swept along with it in the player,
> and each voice can carry one for the whole line (Group.roman), which is how
> amll-ttml-db keeps them. The readings a person types are never replaced by
> the romaniser; the romaniser only ever fills in what is missing.
>
> The romaniser is the player's own -- spicy_lyrics.readings, pykakasi for
> Japanese, pypinyin for Chinese, its own tables for Korean and the
> alphabets -- so a reading filled in here is the one the player would have
> derived on its own, and the two cannot disagree about a lyric.

### module level (comment)

**line 2089** — before `LIKE = ("~",)`

> ----------------------------------------------- lines grouped as one
> A part with this line in it holds lines sung alike in other words (see
> make_alike): the block before the first LIKE is timed, each block after
> one is sung the same way. A line's key is letters and digits only, so no
> line ever has this one -- and an editor from before it, reading such a
> part, sees the first block grouped and a line after it nothing sings.

---

## Lift — 2026-09-26

Comments lifted out of `editor/ops.py` on 2026-09-26; the line numbers are that day's.

### `syllabify`

**line 183** — before `if SY.is_accepted(g.word_text(run), [g.syls[i].text for i in run]):`

> Already cut one of the ways kept as right: re-cutting it to
> the usual one would throw the hand timing away for nothing.


---

## Lift — 2026-09-17

### `split_everywhere`

**line 120** — before `bits = SY.bare_pieces(word, list(pieces))`

> The same peel the kept corrections are stored under -- see
> editor.syllables, which owns that store and the reasoning.


### module level

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


### `set_text`

**line 504** — before `was, old.text = old.text, parts[0]`

> Compared against what it WAS. Assigning first and comparing after
> made the test always true, so a real rewrite reported "nothing
> happened" -- the signal the window reads as a no-op, which pops the
> undo entry it had just pushed and skips the dirty flag and the push
> to the player.


### module level

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


### `move_words`

**line 1385** — before `runs = dest.words()`

> Where the destination's own syllables are, before anything moves.

**line 1395** — on `            anchor -= len(run)`

> it is coming out from before the mark


### module level

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


### `from_first`

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
