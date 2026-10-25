# `mild-lyrics/review.py`

Comments lifted out of `mild-lyrics/review.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/review.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Reading a timed lyric back for the things that are wrong with it.
>
> Everything here answers one question: if somebody sat down with this document
> and went through it line by line, what would they stop at? It is for the files
> that come in from OUTSIDE the player -- one dropped on the window, one pushed
> over the live link from the editor -- because those are the ones somebody is
> still working on. See LyricsView.open_review for the screen it draws on.
>
> The player is the wrong instrument for this on its own, and that is the whole
> reason this exists. It is built to make a document look right: `_trim` takes
> the invisible characters out of every syllable before it is drawn, `unzwsp`
> takes them out of a line, `prepare` clamps an open end, and `last_moment`
> quietly plays a line to the end of its longest word whatever the line said. A
> zero-width space, a no-break space, a Cyrillic e, a line that runs a tenth of
> a second into the next one -- none of them show. They are all still in the
> file, and the file is what gets published.
>
> WHAT IS CHECKED, and why each one is worth a person's attention:
>
>   characters   Anything invisible (ZWSP, the joiners, a BOM, a soft hyphen),
>                any space that is not a plain one, any bidi control, any
>                apostrophe that is not ', and any letter sitting in a word
>                written in another alphabet -- the Cyrillic e in "be" being the
>                one everybody has met. These travel: they come in with a copy
>                and paste out of a browser and they ride into everything the
>                file is ever turned into.
>
>                And the punctuation a page writes that a singer cannot sing:
>                an ellipsis, a slash, a backslash. Nothing is sung there, and
>                in a timed document the words either side of one have times of
>                their own, so there is nothing for it to stand for. With a
>                comma hung off an em dash, “—,”, which is the dash saying the
>                phrase breaks and then the comma saying it again -- the dash
>                on its own is the whole mark.
>
>   how it reads Whether a line is in capitals throughout, has no capital in it
>                anywhere, or is capitalised word by word the way a title is --
>                all three being what a transcript looks like rather than what
>                a lyric looks like. Said once about the document where it is
>                how the whole document is written, because writing a lyric in
>                lower case is a thing people do on purpose. See _check_case,
>                and mind the exemptions: a word spelled out B-O-Y is not a
>                line in capitals, and Korean has no capitals to leave out.
>
>   splits       The document's own syllable seams, against the rule the editor
>                splits by -- `editor.syllables.split`, which is this project's
>                sung rule plus every correction the person using it has kept,
>                so a word they have already ruled on is never raised again.
>                Both of the editor's rules are asked and a seam is only raised
>                where BOTH refuse it, because they are wrong in different
>                places: the sung rule reads "nosebleeds" as no-seb-leeds and
>                hyphenation has it as it was timed.
>
>                And three seams that are wrong whatever the rules say: a
>                hyphen with nothing to join -- the word stopping after it,
>                drawn "Wha- wha- what", gap and all; a space typed after it;
>                or the line ending on it (_check_hyphens); a hyphen at the
>                head of a piece rather than the tail of the one before it,
>                shake|-up for shake-|up, which lights the hyphen up with the
>                wrong syllable (_check_hyphen_side); and a word spelled out
>                loud cut halfway, "PVA" timed PV|A, which is timed whole or a
>                letter at a time and nothing in between.
>
>                Only one direction is reported. A word the rules would cut and
>                the document times whole is NOT a fault: timing a word whole is
>                a choice, and editor/syllables.py measures that direction at 41
>                of 349 -- it is the common case, not the mistake. A cut neither
>                rule would make is the other way round, and is nearly always a
>                slip of the hand.
>
>                Nearly always, which is why each of those three findings --
>                split, split-digraph, split-whole -- carries its own answer:
>                the word and the arrangement the document has, ready to be
>                kept as the rule for it (see _kept_of and keep_split). The
>                rules are wrong about a word often enough that a page with no
>                way to say so is a page that gets read past, and the store it
>                is kept in is the editor's own, so saying it once settles the
>                word for both windows and for every song after this one. The
>                other three -- a hyphen with nothing to join, a hyphen on the
>                wrong side, a word spelled out and cut halfway -- carry no
>                answer, because they are wrong whatever any rule thinks.
>
>   timing       Two things running through each other, at any amount at all:
>                syllables, words and lines. A millisecond of overlap is not a
>                rounding error in a document written in milliseconds, and it is
>                exactly what a player hides -- a line is drawn from whenever it
>                starts until whenever its words stop, so nothing on screen ever
>                shows it.
>
>                Weighed differently depending on what is crossing what, and
>                by how much. Inside a line a short clip is a fault -- one voice
>                cannot sing two words at once, and nothing about a performance
>                is decided at four milliseconds -- while a long one is a word
>                held over the one after it, which somebody may have meant, so
>                past CLIP_SLIP it is only doubtful. Between lines it is never
>                more than worth a look: singers trade lines and a line rings on
>                under the next, so the amount is measured and shown and nothing
>                is called wrong. See _check_between.
>
>                And where a line's WORDS stopped before the next line began
>                and only its written end crosses, that is what is said: the
>                number is in the <p> end rather than in the singing, and the
>                sentence points at the end rather than describing an overlap
>                nobody performed.
>
>                Also the arithmetic that cannot be right whoever is singing: an
>                end before its start, a syllable outside its own line, times
>                out of order, a hole in the middle of a word.
>
>   the document Whether a line's own Text spells what its syllables spell,
>                whether anything is timed past the end of the recording, and
>                the small print -- empty chips, a line with times and no words,
>                and a bracket or a quotation mark opened and never closed.
>                That last one is counted over the whole document rather than
>                over a line, because a quotation in a lyric is routinely opened
>                on one line and closed two lines later; see _check_pairs.
>
>                And an ad-lib typed into the line instead of written as one: a
>                word-timed document has a Background group to put "(Huh)" in,
>                and a lead line that spells it out has two characters nobody
>                sings inside the singer's own words. See _check_parens.
>
>   the header   Whether anybody is credited with writing the song, and whether
>                a song with a guest on it has a second voice anywhere in it.
>                Neither shows in the words however carefully they are read --
>                the first is a field nobody filled in, the second is every
>                line of a duet filed as the same singer. The second is a note
>                and only ever a note, and it is asked in one direction: a
>                feature with no second voice is worth a look, a second voice
>                with no feature is just a duet. See _check_credits.
>
> What is DRAWN from all this is the page's business, not this file's -- it
> keeps every finding it made, and the page folds the repeats, hides the clean
> lines and narrows by tab and by weight. A song repeats itself and its faults
> repeat with it; see LyricsView.review_folded.
>
> Nothing here edits a DOCUMENT. It reads one and says what it saw; the fixing
> is the editor's job, and a file the player holds is not the file on disk
> anyway. The one thing it will write is a correction to the RULE -- keep_split
> and forget_split, straight into the editor's store of kept splits -- which is
> a statement about a word rather than about this file, and is what makes a
> wrong finding about a seam answerable on the screen that made it.
>
> Run it over a folder of TTMLs from the command line to see what it makes of
> them:
>
>     python3 mild-lyrics/review.py *.ttml

### `_around`

**line 151** — from the docstring, ``

> The word one character sits in, for quoting it back.
>
> Asked of the word rather than of the chip because a chip is not always a
> syllable: a line-timed document is one chip holding the whole line, and
> "a Cyrillic e, in <the entire line>" is a sentence that hides the thing it
> is pointing at.

### `Chip.shows`

**line 209** — from the docstring, ``

> (the marks to draw, the weight of the piece itself) under one tab.
>
> A tab is a question being asked of the document, and the answer has to
> be the same in the list and on the words: reading the Sync tab with
> red boxes round the brackets still on the line is being shown the
> answer to a question nobody asked. See group_of.

### `Chip.flagged`

**line 217** — from the docstring, ``

> The heaviest thing said about the chip AS A WHOLE.
>
> Not the same question as `worst`, and the page asks both: a mark sits
> on the characters it is about and needs no underline under the rest of
> the piece, while a flag -- a bad split, an overlap, no length -- is
> about the piece itself and has nothing smaller to point at. Reading
> one for the other put a red rule under the entire line of a
> line-timed document because one letter in it was Cyrillic.

### `Row.first`

**line 267** — from the docstring, ``

> When this row's first word starts, whatever the row says.
>
> The moment the lyric column lights the line -- SL.timeline dates a
> line from its words, not from its <p> -- and so the one to show, to
> follow and to play from. A <p> is routinely widened to hold an ad-lib
> that comes in ahead of the words (see SL._covering), and the review
> read that as the line starting, so its times and its "now" ran ahead
> of the lyrics for every line with an early ad-lib. `start` is still
> the document's own statement, and is what the checks read.

### `Report.say`

**line 299** — from the docstring, ``

> File one finding, and hand back where it went.
>
> `fix` is how the finding can be ANSWERED, where it can be: for a
> seam, the word and the arrangement the document already has, which
> keep_split files as a correction and the rule then defers to. It is
> the only thing in a finding that is not a description of the
> document, and it is still not a change to one -- a correction says
> what the RULE should think of a word, here and in the next song.

### `Report.told`

**line 333** — from the docstring, ``

> What to print under one row: (level, kind, sentence, how many more).
>
> One line of a song can hold eight zero-width spaces and eight
> sentences about them, which is a wall rather than a review. So each
> kind is one line, naming every one of them, separated by semicolons.
> "How many more" is always 0 now and kept for the callers' sake.
>
> Splits are the exception: each is a different word with its own
> answer, and each is listed so each can be corrected -- once. The same
> word cut the same wrong way twice in a line is one answer, and the
> sentence is judged on the word without its punctuation (see _inside),
> so "wachten" and "wachten," two words apart say the same thing and
> are listed as one -- and so do "Actin'" and "actin'", capitals being
> no part of where a word is cut.

### `Report.in_group`

**line 361** — from the docstring, ``

> The findings under one tab, in the order they are listed.
>
> `level` narrows to one weight -- the wrong things on their own, or the
> doubtful ones on their own. The two questions are independent and
> somebody going through a document asks both: what is this about, and
> how much does it matter.

### `Report.as_text`

**line 389** — from the docstring, ``

> The whole review as something that can go in a clipboard.
>
> A line, then what is wrong with it, a sentence to a line:
>
>     **Line 23, 0:45.524:** The tenacity
>     *Tenacity* is split as *ten**|**acity*. Correct split: *te**|**na**|**ci**|**ty*
>
> in Discord's markdown, with a line that repeats written once:
> **Lines 3, 9, 0:10.000, 0:52.000:** and the rest.
>
> No heading and no level names. The review said who it was for and
> how the splits were judged at the top of every copy, which is two
> lines of the reviewer describing itself to somebody who wanted the
> list; the weights are in the window, where they can be filtered on.

### `_check_pairs`

**line 579** — from the docstring, ``

> Brackets and quotation marks, counted over the whole document.
>
> Over the whole document because that is the unit they are written in. A
> quotation in a lyric routinely opens on one line and closes two lines
> later --
>
>     Mama said, "Where you been at?
>     Make sure you're doin' good"
>
> -- and asked a line at a time both of those lines are wrong and the song
> is right. That was every single one of the thirteen this raised over the
> 53 TTMLs in this folder: not one real fault among them.
>
> So the state is carried down the lead lines, and what is reported is a
> bracket or a quotation that is still open when the song ends, filed
> against the line that opened it. An ad-lib is checked on its own: it is a
> few words sung over somebody else's line rather than the next thing in the
> sentence, and threading it through the same walk would have it closing the
> lead line's quotation.

### `_check_hyphen_side`

**line 704** — from the docstring, ``

> Which side of a seam the hyphen ends up on.
>
> It goes on the piece BEFORE the cut -- shake-|up, not shake|-up -- and
> that is not a matter of taste. The player draws a piece at a time and
> fills it as it is sung, so a hyphen sitting at the head of the next piece
> is a hyphen that lights up with the syllable AFTER the one it belongs to;
> it is the tail of "shake" and it should darken and light with "shake".
> Everything else in this project already agrees: SL.syllabify hands the
> mark to the chunk in front of it, `editor.syllables._hyphenate` does the
> same, and the kept splits hold Oh-|woah and Yeah-|yeah-|yeah.
>
> Three of these over the 53 TTMLs in this folder, all in one song, all of
> them a word cut zy|-bizz where it should read zy-|bizz.

### `_check_hyphens`

**line 732** — from the docstring, ``

> A hyphen with nothing to join: three ways to write the same fault.
>
> A hyphen says the word carries on. The document then says it does not,
> and the reader is shown a mark hanging off the end of a word with a gap,
> or the end of the line, after it:
>
>     the piece ends in one and the next piece is a new word. The player
>     believes the boundary -- it is the thing that decides whether a space
>     is drawn -- so the line comes out "Wha- wha- what", with the gap
>     sitting after a hyphen that promised there would not be one. Two ways
>     to arrive at THAT, and they are fixed differently, so the sentence
>     says which: the piece carries a space of its own inside its text
>     (which `word_ends` reads as the end of the word however the flag is
>     set), or IsPartOfWord was simply not set on it. Six of these over the
>     53 TTMLs in this folder, all in one song, all of the second kind --
>     and the first kind is what a hyphen with a real space typed after it
>     produces, which is the one people write by hand;
>
>     the hyphen sits inside a piece with a space after it, which is the
>     same line written without a seam at the hyphen at all: a line-timed
>     document, a word timed whole, or a dash used as punctuation with air
>     either side of it. Marked on the character rather than flagged on the
>     piece, because the piece can be the whole line;
>
>     the line ends on one. Nothing follows it in the row, so there is
>     nothing for it to carry the word into -- a word cut off at the end of
>     a line is written with the letters it got to and no mark, or with an
>     em dash, which is punctuation rather than a joiner and is left alone
>     here.
>
> Only these three, and only the hyphens: an em dash is not in JOINERS.

### `_spelled`

**line 792** — from the docstring, ``

> Whether this piece is a letter being SAID rather than a syllable sung.
>
> "B-", "f-", "P-": a letter with a dash hanging off it, which is how
> everybody writes a stutter and how everybody writes a word spelled out
> loud. There is no vowel in "B", and the person timing it cut there on
> purpose, one tap per letter. Without this exemption the vowel test finds
> 89 pieces across the 53 TTMLs in this folder rather than 59.
>
> The dash is what says so, not the length. A single letter on its own is
> only being spelled when the whole word is (see _initialism): the "w" of
> know, timed kn|o|w, is a piece of a word with no vowel in it and is
> exactly what this check is for.

### `_tail`

**line 804** — from the docstring, ``

> A word in capitals with a small ending stuck on it: ("SSRI", "s").
>
> SSRIs, CDs, IDs, TVs. The capitals are the word and the ending is the
> grammar, and it is timed with the letter in front of it: S|S|R|Is.
> Without this an initialism stopped being one the moment somebody made it
> plural, and every letter of it was then a piece with no vowel in it.
>
> ("", "") for anything else, which includes a word that is all capitals --
> that is _capitals' question -- and a word like "Apple" whose one leading
> capital is just a capital.

### `_initialism`

**line 830** — from the docstring, ``

> Whether this whole word is being spelled out rather than sung.
>
> "O-D", "V-V-S", "F-R-I-E-N-D-S": every piece a single letter. Neither
> splitter has anything to say about these, and the kept splits are
> full of them, which is where the shape of this test comes from. Worth 15
> of the vowel findings and 9 of the split ones over this folder's 53. A
> plural counts as one: SSRIs cut S|S|R|Is is the same word said the same
> way with an ending on it, and the ending is timed with the letter in front
> of it. See _tail.

### `_kept_of`

**line 849** — from the docstring, ``

> The word these chips spell and how the document cuts it.
>
> What a finding about a seam carries so that the finding can be ANSWERED
> rather than only read: hand it to keep_split and the arrangement the
> document already has becomes the rule for that word.
>
> Two liberties are taken with the text, both of them the store's own. The
> zero-width spaces come out -- one is a word boundary drawn without a gap
> rather than part of the spelling, and a correction filed with one in it
> could never be looked up again -- and the punctuation stays ON, because
> `editor.syllables` peels it off itself and puts it back on whichever
> marks the word wears the next time it turns up. See bare_pieces there.
>
> None where the pieces cannot be stored as a split of the word at all: a
> piece that was nothing but a zero-width space, or a "word" that is all
> punctuation and has no spelling to rule on.

### `corrections`

**line 859** — from the docstring, ``

> Every split correction kept by hand, filed by the bare word.
>
> The editor's store, read through the editor -- the player has no store
> of its own and must not grow one, because the whole value of a
> correction is that the rule answers the same way in both windows and in
> the next song. Empty where the editor cannot be imported at all, which
> is also where _cutter falls back to the uncorrected sung rule.

### `keep_split`

**line 922** — from the docstring, ``

> Rule that this is how the word is cut. "" if it was kept, else why not.
>
> The answer to a seam the rules refused and the person stands by. It goes
> into the same store the editor's Syllabify dialogue writes, which _cutter
> reads before either rule is consulted -- so the seam stops being raised
> here, in the editor, and in the next document that cuts the word this
> way. A kept arrangement of ONE piece is the other thing it can say:
> leave this word alone.

### `_kept_here`

**line 948** — from the docstring, ``

> The words in this document a kept correction already answers for.
>
> Said on the page because a review that has been corrected looks exactly
> like one that never had anything to say, and the two are worth telling
> apart -- especially on somebody else's machine, where the corrections
> are somebody else's.

### `_check_splits`

**line 964** — from the docstring, ``

> The document's own seams inside a word, against the editor's rule.
>
> Held to the sung rule only. Hyphenation used to be a second opinion
> that excused any seam it would break at, and a printer's break is not a
> sung one: weath|er, noth|ing and moth|er all went unraised. The cost is
> the false alarms it used to take out (the sung rule reads "nosebleeds"
> as no-seb-leeds); K keeps a split that is right, and it is never raised
> again.
>
> A word the person has already ruled on is not raised at all, whichever
> splitter is asked: a kept correction wins inside `editor.syllables.split`
> before either rule is consulted, so both of them hand back the arrangement
> that person chose. See override_for.

### `_inside`

**line 1073** — from the docstring, ``

> The word as its seams are judged, and where a seam lands in it.
>
> (core, where): `core` is the word with the punctuation round it and every
> zero-width space taken out -- SL.peel's answer, which is the splitter's
> own -- and `where(offset)` turns an offset into the word as the document
> spells it into an offset into `core`, or None for a seam that is not
> inside the letters at all.
>
> That second case is the one worth having. "wachten," timed wach|ten|,
> has a seam before its comma, and a comma is not a syllable: nothing is
> sung there and no rule would ever cut there, so the seam was raised as a
> wrong split -- and "wachten," then read as a different word from the
> "wachten" two lines up, the same fault said twice.

### `_same_size`

**line 1117** — from the docstring, ``

> The rule's split, or another right one with as many pieces as the file.
>
> A word with a vowel hiatus in it has more than one right split, and the
> answer to a file that cut it into four is the right split in four:
> Ver|mil|i|on is corrected to Ver|mi|li|on, not to Ver|mi|lion. Of those,
> the one keeping the most of the file's own seams.

### `_check_between`

**line 1154** — from the docstring, ``

> Lines running through each other, and lines out of order.
>
> An ad-lib is written inside its line and is SUNG over it, so a backing
> group crossing the lead it belongs to is the format working as intended
> and is not reported at all.
>
> Two LEAD lines crossing is reported, at any amount -- the first
> millisecond of it counts, and the amount is in the sentence -- but only as
> something worth a look. It is not necessarily wrong: two singers trade
> lines that overlap, a line is held under the one that follows it, and a
> word left ringing over the start of the next line is a real thing a real
> recording does. What it is, always, is a decision somebody should have
> made on purpose, which is exactly what this screen is for showing them.
>
> Inside one line the same crossing IS a fault and is filed as one, because
> there the two things are one voice singing two words at once. See
> _check_times.
>
> Two sentences, because there are two different things to see. Where the
> WORDS of one line are still going when the next begins, that is two
> voices crossing and the line is what runs long. Where they stopped in
> time and only the line's stated end crosses, nothing was sung over
> anything: the number lives in the <p> end, an exporter wrote it, and the
> finding says so rather than describing an overlap a reader will not find
> in the words. It is the same fault as line-end-short from the other side
> -- a stated end that disagrees with the singing -- and it is only ever
> worth a look, because the player plays to the end of the words anyway.

### `_worded`

**line 1195** — from the docstring, ``

> Whether this document is timed word by word rather than line by line.
>
> Asked of the document itself rather than of the Type it claims to be:
> NetEase, QQ Music and Kugou all stamp "Syllable" on whatever they hand
> over, and the rest of this program has read the data instead for exactly
> that reason (see LS.quality, and the note in info_rows).

### `_check_parens`

**line 1205** — from the docstring, ``

> Ad-libs typed into the line, in a document that can hold them properly.
>
> A word-timed document has somewhere for a backing vocal to go: a
> Background group, sung over its line, drawn in the smaller type hanging
> off it and timed on its own. A line that spells one out instead --
> "You're not who I love (Huh)" -- is a line whose words include two
> brackets nobody sings, and every one of them is then timed as part of the
> lead: the singer's line is stretched over an ad-lib they are not singing,
> and the ad-lib cannot be drawn where ad-libs go.
>
> Only where the document IS word-timed. A line-timed source has no
> Background groups to put anything in and writes its ad-libs in brackets
> because that is the only thing it can do, and telling somebody their
> LRCLIB copy is wrong helps nobody.
>
> Measured over the 53 TTMLs in this folder: 78 lead lines across 12
> word-timed documents, and not one ad-lib group with a bracket in it --
> so this says something about the lead groups only, and there is no
> exemption to write for the other side.

### `_case_of`

**line 1232** — from the docstring, ``

> How a line is cased: "upper", "lower", "title", or "" for ordinary.
>
> Three things are deliberately not asked about. A word spelled out is not
> evidence of anything -- "Like B-O-Y" is not a line in capitals -- and nor
> is a script with no capitals to use: Hangul and kana have no case at all,
> and counting them as "no capital anywhere" would put a warning on every
> line of every Korean song. And the first word of a line is capitalised
> because it is the first word, so title case is judged on the rest.
>
> Title case wants four words before it will say anything, because the
> shape it is looking for -- a scrape that took the styling of a song title
> with it -- is a whole line of capitals, and at two or three words it is
> also the shape of an ordinary line that happens to name something. "In
> New York" is three words, every one of them capitalised, and perfectly
> written.

### `_check_i`

**line 1276** — from the docstring, ``

> A lower-case "i" standing on its own, in an English lyric.
>
> English capitalises the pronoun wherever it falls, which is why this is a
> spelling rather than a matter of taste: "yesterday i was" is wrong in a
> way "yesterday Was" is not, and a transcript typed in a hurry is full of
> them.
>
> Only where the document says it is English, because "i" is an ordinary
> word in Italian, a letter in Dutch and Danish compounds, and a pronoun
> that is not capitalised in most of the languages this reads. A document
> with no tag is taken at its default, which is English.
>
> THE TAG IS NOT ALWAYS "en", and refusing anything else would have left a
> third of this library unchecked. Of 400 documents here, 110 are tagged
> `pcm` -- Nigerian Pidgin -- and 17 `sco`, Scots, and they are Dua Lipa,
> Queen, Eminem and the SpongeBob theme: the catalogues guess the language
> and guess it badly on anything sung with an accent. Both of those, and
> Jamaican Patois with them, are English-lexifier and write the pronoun the
> same way, so a wrong guess costs nothing here and refusing them costs the
> check.
>
> Softened to a note where the whole lyric is written in lower case, on the
> same grounds _check_case softens itself: somebody who typed forty lines
> without a capital did not miss this one, and forty warnings about a style
> are forty ways of saying nothing. Still said line by line, though, because
> unlike a line's case this one has a place in the words -- it is a mark on
> a syllable, and it is the mark that makes it findable and fixable.

### `_check_case`

**line 1304** — from the docstring, ``

> Lines shouting, whispering, or dressed as titles.
>
> Said once about the document where it is how the document is written --
> plenty of people write a whole lyric in lower case on purpose, and a
> warning on all forty lines of one of those is forty ways of saying
> nothing.

### `_check_credits`

**line 1373** — from the docstring, ``

> The header, against what the song is: who wrote it, and who sings it.
>
> Two things a document can be complete as a lyric and still be missing,
> neither of which any amount of reading the words will show.
>
> The songwriters, because <songwriters> is the one field in an Apple-style
> <head> that says anything about the song at all, and a file published
> without it credits nobody. The editor can look them up (editor.sources
> .songwriters), which is why this is worth saying rather than shrugging
> at: it is a field somebody forgot, not a fact nobody has. An LRC has
> nowhere to put them and will always be told so, which is true.
>
> And a guest with nothing to sing. Where the song is credited "(feat.
> Somebody)" and every line in the document is written for the one voice,
> either the guest's lines are filed as the lead singer's -- which is what
> the second agent exists to say, and what a player draws on the other side
> of the screen -- or the guest really is only on the hook. Both happen, so
> it is a note and never a fault.
>
> ONE WAY ONLY. A duet with no feature in its title is not raised and must
> not be: a song by two credited artists is sung by two of them and names
> neither as a guest, which is the ordinary shape of half the duets there
> are, and "why is there a second voice here" is a question with an obvious
> answer and no fix.

### `_cutter`

**line 1392** — from the docstring, `# ----------------------------------------------------------------- the whole`

> Who says where a word comes apart: (rule, cut, other rule, cut).
>
> The editor's splitter, wherever the editor can be imported -- that is the
> whole point of using it rather than SL.syllabify, which is the same sung
> rule without any of the corrections: `editor.syllables` checks the kept
> splits first, so a word the person has already ruled on comes back the way
> they ruled and is never raised with them again.
>
> The second opinion is the OTHER method, and it is what makes this check
> quiet enough to read (see _check_splits). It is left out where pyphen is
> not installed or has no patterns for this language -- then a seam is
> judged on one rule, which is stricter, and the screen says so.

### `_cutter.name`

**line 1407** — from the docstring, ``

> What to call a splitter, with the patterns named where they differ.
>
> A document tagged `pcm` held to en-us patterns is being held to
> somebody else's language, and the screen has to say so -- it is the
> difference between "the rule disagrees" and "an English rule
> disagrees with your Dutch".

### `_hyphens_for`

**line 1423** — from the docstring, ``

> The pattern set to hyphenate this language with, or "" for none.
>
> English is the last resort rather than a refusal. A tag pyphen has never
> heard of is usually a language written in the Latin alphabet with an
> English-shaped lexicon behind it -- files here are tagged `pcm`,
> Nigerian Pidgin, and are full of English words -- and the second opinion
> is only ever used to EXCUSE a seam the first rule refused. Consulting the
> wrong patterns can therefore let a real slip through; it cannot invent a
> fault, which is the failure worth avoiding here.

### `_rule_for`

**line 1466** — from the docstring, ``

> Which splitter to hold the document to.
>
> "auto" is the editor's own measured advice, applied: the sung rule for
> English, where it was written and where it agrees with the hand splits in
> this folder 90% of the time -- and hyphenation for a language whose rules
> this project has never encoded, where pyphen ships patterns and the sung
> rule is guessing. See the table at the top of editor/syllables.py.

### `_list_seams`

**line 1478** — from the docstring, `# ------------------------------------------------ seams, ignores, own flags`

> Every word the document splits, as it is split, one to a finding.
>
> Not a judgement -- see LISTED. The splits tab shows the seams a rule
> refused; this shows all of them, down a column under each line, so a
> whole song's splitting can be read at a glance and a bad one corrected
> wherever it is, whether or not a rule would have raised it.
>
> Listed at the weight the splits tab gave the word where it raised it --
> doubtful or wrong -- so the ones to read first stand out in the column,
> and as worth a look otherwise. Still never counted.

### `ignored`

**line 1564** — from the docstring, ``

> Whether a rule the person made keeps this finding off the page.
>
> Four sizes of rule: one finding on one line of one song; every finding
> saying the same thing, anywhere (a kind and its sentence); every finding
> of that kind, anywhere ("runs Xms into the next line", all of them); and
> every finding at a level ("worth a look", all of them).

### `review`

**line 1649** — from the docstring, ``

> Read a document and say everything that looks wrong with it.
>
> `title` and `artist` are what the PLAYER knows about the song, which is
> more than the file does: an Apple-style <head> carries the songwriters
> and nothing else, so a document that is credited "(feat. Somebody)" on
> the service it came from says so nowhere in itself. Where they are not
> given, whatever the document does carry is used -- an amll:meta title or
> artist, and the name this copy is being reviewed under.

---

## Lift — 2026-09-26

Comments lifted out of `mild-lyrics/review.py` on 2026-09-26; the line numbers are that day's.

### module level

**line 220** — before `SEAM = "|"`

> Where a word is cut, written the way the page DRAWS it: the review puts a
> little upright bar in the gap between two pieces of one word, and what the
> note underneath says has to be the same mark or the reader is left matching
> one notation against another. It used to be the middle dot, which on this
> page already means something else -- an invisible character, see DOT -- so
> "wi·thout" was a seam and "or·am" was a zero-width space, in the same type,
> two lines apart.

**line 246** — before `"seams": ("seam",),`

> Not findings: every split word, listed so the splits can be read down
> a column. Only ever shown under their own tab, and never counted.


### `Report.say`

**line 472** — before `"says": says if kind in ("seam", "custom") else sentence(says),`

> A seam listed and a flag somebody wrote are printed as they are.


### `Report.told`

**line 552** — before `first, more = out[at][2].rstrip("."), f["says"].rstrip(".")`

> The rest of the kind go into the same line, each named.


### `sentence`

**line 671** — before `if says[:1].isalpha():`

> Only a sentence that opens on a word of its own. One that opens on a
> quote is quoting the lyric, and "i" capitalised there is no longer
> the "i" the finding is about.


### `_check_splits`

**line 1321** — before `sung = _same_size(word, sung, mine)`

> Judged on the sung rule alone. Hyphenation used to excuse any seam
> it would print a break at, and that is how weath|er, noth|ing and
> moth|er went unraised: a printer's break is not a sung one.

**line 1329** — before `bare = []`

> A split with a piece that has no vowel in it is a split like any
> other, and answered the same way: K keeps it or corrects it.

**line 1377** — before `k = bad[0][0]`

> One finding for the word, however many of its seams are wrong: the
> answer is one split of the whole word.


### module level

**line 1405** — before `HIATUS = ("ia", "io", "iu", "eo", "ua", "uo")`

> Two vowels sung apart or together, as the singer likes: li|on or lion,
> ra|di|o or ra|dio. The rule reads each run of vowels as one syllable.


### `_check_between`

**line 1495** — before `ends = [c.end for r in rows if r.group == a.group`

> Everything sung in the line counts, its ad-libs as well as its lead:
> "It's way too late for you to leave now (Get ready)" stops its lead
> at 0:33.466 and sings "Get ready" to 0:34.287, and "nothing is sung
> in that time" was said of the ad-lib still going.

**line 1504** — before `rep.say(a, NOTE, "line-end-long", says)`

> Only the <p> end crosses: an exporter wrote it, and nothing is
> sung over anything. Filed apart so it can be ignored apart.


### `_case_of`

**line 1608** — before `return "lower" if first.isupper() or first.islower() else ""`

> A line that opens in a script with no capitals -- 愛してる baby,
> 私は you and me -- has no start to capitalise, and what follows it
> in Latin letters is the middle of a sentence.


### module level

**line 1639** — before `ENGLISH_ENOUGH = {"en", "eng", "pcm", "sco", "jam"}`

> The pronoun, and the contractions that are the same word with something
> hung on the end of it. "i" is the one English word whose capital is not
> optional and not a style: it is how the word is spelled.
> The tags the catalogues hand out for songs sung in English; see _check_i.


### `_check_case`

**line 1718** — before `style.discard("upper")`

> A line in capitals is flagged on its own however many there are: it
> is the one of these that is almost never the document's style and
> almost always a line pasted from somewhere that shouts.


### module level

**line 1979** — before `STORE: pathlib.Path | None = None`

> Where what the person has said about reviews is kept: what to leave out,
> and flags of their own. Set by whoever hosts the review (the window points
> it into its config directory); None keeps everything in memory, which is
> what the tests and the command line want.


---

## Lift — 2026-09-17

### module level

**line 142** — before `ERROR, WARN, NOTE = "error", "warn", "note"`

> The three weights a finding can carry. `error` is something that cannot be
> right whatever the song is -- an end before its start, a letter from the
> wrong alphabet, a character nobody sings. `warn` is something that is wrong
> in every document this has been run against but could conceivably be meant:
> a word held over the one after it, a line shouted in capitals. `note` is a
> measurement worth seeing, not an accusation.

**line 151** — before `EPS = 0.0005`

> Overlap has to be measured against SOMETHING, and the honest number here is
> below anything a document can express: TTML times are written to the
> millisecond, so a half-millisecond floor catches the smallest overlap that
> can exist while leaving no room for the float arithmetic that read it.
> "Any amount at all" is the rule, and this is what any amount means.

**line 158** — before `CLIP_SLIP = 0.050`

> Where a clip stops being a slip. Two words in one line crossing by a
> handful of milliseconds cannot be anything but a mistake -- nothing about a
> performance is decided at that scale, and nobody taps a boundary meaning to
> put it four milliseconds inside the word before. Past this, it is a word
> held over the one after it, which is a thing singers do and a thing somebody
> may have meant; it is still shown, and it is no longer called wrong.

**line 167** — before `INVISIBLE = {`

> Invisible, and in a lyric for no reason anybody can defend. The player takes
> all of them out before drawing (SL._trim), which is precisely why nobody
> notices they are there.

**line 178** — before `ZWSP = "​"`

> Not an exception, though it was written as one at first. A zero-width space
> is how several sources -- Apple's export, NetEase, QQ Music -- write a word
> boundary that is not drawn as a gap, and `word_ends` reads it as one, so
> there is a sense in which the format uses it. That is not a reason to be
> gentle about it: it is a boundary the document already spells with
> IsPartOfWord and with real spaces, the player strips every one of them
> before drawing (SL._trim), and what they actually do is ride out into every
> file this is ever turned into. In the words of a lyric it is wrong.

**line 204** — before `APOSTROPHES = {`

> Everything that gets used where a plain ' was meant. The typographic one is
> the common case by a distance -- it is what a word processor and every phone
> keyboard produce -- and the acute and grave accents are what a keyboard
> without an apostrophe key produces.

**line 227** — before `SHOWN = {"\t": "→", "\n": "↵", "\r": "↵"}`

> What an invisible character is drawn as on the review screen. The point is
> only that the eye can land on it; the name of the character is in the
> finding underneath.

**line 234** — before `CONFUSABLE = ("CYRILLIC", "GREEK")`

> The two alphabets whose letters are drawn the same as Latin ones. Everything
> else that "mixes scripts" in a lyric mixes them for a reason -- a Japanese
> line runs kana straight into Latin with no space anywhere, and a Korean one
> does the same -- so the confusable test is kept to the pair of alphabets
> where a mix really is somebody's keyboard or somebody's paste.

**line 245** — before `DIGRAPHS = ("sch", "th", "ch", "sh", "ph", "wh", "gh", "ck", "qu", "ij")`

> The letter pairs that spell one sound and are never cut through. This is
> SL.syllabify's own list, which is what makes the check agree with the rule
> it is checking against, plus the two Dutch ones -- and pointedly NOT "ng":
> the sung rule cuts sin-gin' and lan-ge itself, so calling that a fault
> here would be this file disagreeing with the splitter it is quoting.

**line 253** — before `GROUPS = {`

> What each kind of finding is ABOUT, which is how the page divides them into
> tabs. Three questions a person asks separately and fixes separately: is the
> text right, is it cut in the right places, and is it in the right place in
> time. A kind that is not named here falls in with the words, which is where
> anything about the document as a written thing belongs.

**line 261** — before `"sync": ("syl-overlap", "word-overlap", "line-overlap", "adlib-overlap",`

> `parens` is about the words, not about the shape of the document: what
> it says is that two characters nobody sings are in the lyric.
> The case of a line, the ellipses and the slashes are all about the words
> as written, so they fall in with the words by default; only the two
> groups below are named.

**line 303** — before `stamp = _fmt`

> The same time format everywhere it is written down -- the report, the
> screen, the clipboard. Public because the page draws it too.


### `_around`

**line 334** — before `return shown_text(text).strip() or got`

> The character is standing on its own -- a zero-width space between
> two words is the usual case -- and "in ·" points at nothing. The
> piece it is written in does point at something.


### `Chip.__init__`

**line 369** — before `self.part = part`

> IsPartOfWord as the document wrote it. `glue` is what it MEANS once
> the text has been read as well -- a syllable carrying its own space
> ends the word whatever the flag says -- and the difference between
> the two is the whole of what _check_hyphens is about.

**line 376** — on `        self.flags: list[tuple[str, str]] = []`

> (kind, level) for the whole chip


### `Row.__init__`

**line 450** — on `        self.found: list[int] = []`

> indices into Report.findings


### `Report.__init__`

**line 472** — before `self.second = ""`

> The other splitter, where there is one to ask. A seam has to be
> refused by both before it is raised, so whether this is empty
> changes how strict the split check was -- and the screen says which.


### `_check_text`

**line 631** — before `rep.say(row, WARN, "blank-chip",`

> A chip of pure whitespace still holds a place in the line and
> still takes time off the clock.

**line 678** — before `rep.say(row, WARN, "ellipsis",`

> Nobody sings an ellipsis. It is what a transcript writes where
> it stopped listening -- a line trailing off, a verse the page
> did not have -- and in a timed document the words on either
> side of it have times, so there is nothing for it to stand for.

**line 690** — before `rep.say(row, WARN, "slash",`

> A slash is a page's punctuation: the line break in "one / two",
> the both-ways of "and/or", the date in a scraped header. A
> singer has no sound for it.

**line 706** — before `rep.say(row, NOTE, "double-space",`

> The player adds the space between two words itself, from the
> flag; a syllable carrying one as well is drawn with a gap twice
> the width of every other. See SL.syllables_text.


### module level

**line 716** — before `ELLIPSIS = re.compile(r"\.{2,}|\u2026+")`

> Two or more full stops in a row, or the single character that means the
> same. Both are written by hand and both come in with a scrape.


### `_check_times`

**line 826** — before `weight = ERROR if row.kind == "lead" else WARN`

> An ad-lib group is the one place in the format where two things really
> can be sounding at once: a backing group holding two voices is written
> as one run of syllables, so its times are not in one order and were
> never meant to be -- see SL.last_moment, which exists because of it. The
> crossings are still shown, because at any amount they are still worth a
> look in a file being written by hand, and they are still said out loud
> as what they are rather than as a fault.

**line 850** — before `heavy = weight if over <= CLIP_SLIP else WARN`

> A short clip is wrong; a long one is a decision. See CLIP_SLIP.

**line 865** — before `rep.say(row, NOTE, "hole",`

> Inside one word the pieces are one continuous sound; a hole in
> the middle of it is a tap that landed late. Between words a gap
> is just a gap, and says nothing.

**line 880** — before `rep.say(row, NOTE, "line-end-short",`

> A note, and the weakest thing said here, because the player is
> built to tolerate exactly this: `last_moment` takes whichever of
> the two is later and plays the line to the end of its words. It
> is worth SEEING -- the stated end is what an exporter writes out
> -- and it is not worth calling a fault on its own. Where the
> words run into the next line as well, _check_between says so in
> the sentence that matters and this one is dropped; see `review`.


### module level

**line 893** — before `JOINERS = "-\u2010\u2011"`

> The hyphens that mean "this word goes on", as against the dashes that are
> punctuation. Only these are checked below: an em dash at the end of a piece
> is a sound cut off -- Jane Remover's "Y— Y— Y— Y—" is written that way on
> purpose, 44 times in this folder -- and a gap after one of those is how a
> dash is written. A gap after a plain hyphen is never anything but a mistake.

**line 985** — before `DASHES = "-‐‑‒–—"`

> Every dash a lyric writes a stutter or a spelled-out word with. The same
> list the player splits words on; see lyrics_gui.DASHES.


### `_initialism`

**line 1067** — before `pieces = pieces[:-1] + [pieces[-1][:-len(tail)]]`

> The ending rides on the last letter: S, S, R, Is. Taken off, what is
> left has to be the letters themselves, like any other initialism.


### `_check_splits`

**line 1106** — before `continue`

> The same gate `editor.syllables.split` puts on itself: neither
> rule has anything to say about a word written in another script,
> so neither is asked. It matters most where it is least obvious --
> in Korean and Japanese one character IS one syllable, so a line
> of them cut character by character is the document being exactly
> right. It was raising 70 of those over this folder's 53 files:
> 173 split findings without this gate, 103 with it.

**line 1116** — before `continue`

> Already answered for, and answered better. A word whose hyphen
> is on the wrong side of a seam is not a word the rules disagree
> with about where to cut -- they would cut in the very same
> place -- and saying both is saying one thing twice with the
> second sentence pointing somewhere else.

**line 1125** — before `continue`

> A number is said, not spelled, and neither rule has an opinion
> about how: "30K" is thirty-kay and is cut 30·K, "00CACTUS" is
> double-oh and is cut 00·CAC·TUS, "#0000FF" is read out letter by
> letter. Both splitters hand a word like that straight back, so
> every seam in it looks like a seam they refused -- and the
> pieces have no vowels in them because they are not spelled with
> any. Neither test has anything true to say here.

**line 1144** — before `continue`

> Cut exactly where the splitter says, which for a word the person
> has kept a correction for means cut exactly the way they chose
> -- an override wins inside `editor.syllables.split` before
> either rule is consulted. Nothing below may then contradict it,
> the vowel test included: the kept splits hold be·la·ng·rijk,
> and "ng" having no vowel in it is not news to whoever put it
> there. See override_for.

**line 1155** — before `if piece and any(ch.isalpha() for ch in piece) \`

> A piece with no LETTERS in it is not a piece with no vowel in
> it -- it is a number, and numbers are said out loud: the "00" of
> 00·CAC·TUS is sung "double oh" and is timed on its own for
> exactly that reason. The test is about spelling, so it is only
> asked of pieces that are spelled.
>
> Two more kinds are not mistakes either. An apostrophe
> is standing where a vowel was -- should-n't, they-'ll, go-in' --
> which is how everybody times a contraction, the hand timings here included (the
> kept splits hold di·dn't and coul·dn't). And a letter with a
> dash on it is being spelled or stuttered rather than sung; see
> _spelled. Between them they are the difference between 59 of
> these over this folder's 53 files and 73.

**line 1174** — before `rep.say(row, ERROR, "half-spelled",`

> A word in capitals holding a piece with no vowel in it
> is an initialism cut halfway: PVA timed PV·A, with two
> of its letters sung as one sound. Saying "PV has no
> vowel in it" is true of every piece of every initialism
> and is not the reason this one is wrong -- there are
> exactly two ways to time a word that is spelled out, and
> the sentence names both of them.

**line 1195** — before `continue`

> The same complaint about the same word twice. The seams are
> already being reported; that a rule would have put them
> elsewhere adds nothing to a piece with no vowel in it.


### `_check_between`

**line 1278** — before `rep.say(a, NOTE, "line-end-long",`

> Nothing is sung over the next line at all: the words stopped
> before it started and what crosses is the line's own written
> end. "This line runs into the next one" describes a performance
> that did not happen, and a reader who looks at the words to
> find the 269ms finds nothing there -- the number is not in the
> singing, it is in the <p>, and that is also the thing to fix.

**line 1303** — before `rep.say(r, NOTE, "adlib-overlap",`

> The same judgement as two lead lines crossing, for the
> same reason: an ad-lib sung over somebody else's line is
> how half of all backing vocals work. Worth seeing, not
> worth calling wrong.


### `_case_of`

**line 1398** — before `return "lower"`

> Asked of EVERY word, spelled-out ones included. A word spelled out
> says nothing about whether a line is being shouted, which is why it
> is left out below -- but its letters are still capitals, and a line
> holding one is not a line with no capital in it. "I-I-I-I-I can see
> a future in you and me" was being reported as having none.

**line 1410** — before `rest = [w for w in words[1:] if not _spelled_word(w)]`

> The first word of a line is capitalised because it is the first word, so
> the question is about the rest -- and the rest with the spelled-out
> words taken out, since B-O-Y starts with a capital whatever the line is.


### module level

**line 1420** — before `CASE_SAYS = {`

> What each case reads as, and what to say about one line of it.

**line 1432** — before `CASE_STYLE_AT = 0.5`

> How much of a document has to be written one way before it is that
> document's style rather than a fault in the lines that are. Half: below it
> the odd line out is the odd line out, and above it the odd line out is the
> one written the ordinary way.

**line 1498** — before `FEAT = re.compile(r"[\(\[]\s*(?:feat|ft|featuring|with)\.?\s+([^\)\]]+)[\)\]]",`

> Who a title says is a guest on the song. An explicit bracket and nothing
> else: Spotify, Apple and every file in this folder hand their artists over
> as one flat list with no mark on which of them is featured, so the brackets
> are the only evidence there is -- and being second on the credit is not
> evidence. "Die With A Smile" is by both of them, and reading the credit
> order as billing would call every duet a guest spot. The same reasoning,
> and the same pattern, as lyrics_gui.split_artists.


### `_cutter`

**line 1584** — before `return "not checked", None, "", None`

> Asked for outright. A document written in a language neither rule
> knows is a document where every seam is a disagreement, and a
> review of it is unreadable until the split check is out of the way.

**line 1611** — before `return "the sung rule", (lambda word: SY.split(word, "sung", lang)), "", None`

> Hyphenation cannot be had here at all: no pyphen, or no patterns.
> The primary falls back to the sung rule if that is what was asked
> for, and the second opinion is simply missing -- which makes the
> split check stricter, and is said on screen rather than hidden.


### module level

**line 1645** — before `PREFER = {"en": "en_US"}`

> pyphen's bare "en" is the British pattern set, and it refuses words the
> American one breaks -- "nosebleeds" among them, which is a word timed by hand as
> nose-bleeds and would otherwise be raised as a bad split. en-us is the set
> the editor loads by default and the set AMLL's own English split loads, so
> it is the one a document tagged plain "en" is held to here as well.

**line 1659** — before `LANGUAGES = ("en_US", "nl", "fr", "de", "es", "it", "pt", "sv", "pl", "ru",`

> The languages the review can be told to read a document in, when the tag on
> the document is wrong -- and it often is: every Dutch file in this folder is
> tagged `en`, and held to English rules a Dutch lyric disagrees with the
> splitter on nearly every word (al-les, da-mes, lan-ge are all correct Dutch
> and none of them are English). Short on purpose, because it is cycled with a
> key: the ones pyphen ships that a lyric in this collection is actually
> written in, commonest first.


### `review`

**line 1756** — before `crossed = {f["row"] for f in rep.findings if f["kind"] == "line-overlap"}`

> One fact, said once. A line whose words run past its own stated end and
> on into the line below produces both findings, with the same number in
> them; the one about the next line is the one that matters, and the other
> is a way of saying it that does not mention what it collides with.

**line 1761** — before `typed = {f["row"] for f in rep.findings if f["kind"] == "parens"}`

> And the same for the brackets: a line that spells its ad-lib out has
> just been told so in a sentence that says what to do about it, and
> "( opened and never closed" underneath it is the same bracket again.

**line 1771** — before `rep.findings.sort(key=lambda f: (f["row"] if f["row"] is not None else 1 << 30,`

> In reading order, and worst first inside one row: the findings list is
> what the page walks with the arrow keys, and what a person wants next is
> the next thing wrong further down the song, not the next thing of this
> kind somewhere else in it.
