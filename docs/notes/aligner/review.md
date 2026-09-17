# `aligner/review.py`

Comments lifted out of `aligner/review.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

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


## `_around`

**line 334** — before `return shown_text(text).strip() or got`

> The character is standing on its own -- a zero-width space between
> two words is the usual case -- and "in ·" points at nothing. The
> piece it is written in does point at something.


## `Chip.__init__`

**line 369** — before `self.part = part`

> IsPartOfWord as the document wrote it. `glue` is what it MEANS once
> the text has been read as well -- a syllable carrying its own space
> ends the word whatever the flag says -- and the difference between
> the two is the whole of what _check_hyphens is about.

**line 376** — on `        self.flags: list[tuple[str, str]] = []`

> (kind, level) for the whole chip


## `Row.__init__`

**line 450** — on `        self.found: list[int] = []`

> indices into Report.findings


## `Report.__init__`

**line 472** — before `self.second = ""`

> The other splitter, where there is one to ask. A seam has to be
> refused by both before it is raised, so whether this is empty
> changes how strict the split check was -- and the screen says which.


## `_check_text`

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


## module level

**line 716** — before `ELLIPSIS = re.compile(r"\.{2,}|\u2026+")`

> Two or more full stops in a row, or the single character that means the
> same. Both are written by hand and both come in with a scrape.


## `_check_times`

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


## module level

**line 893** — before `JOINERS = "-\u2010\u2011"`

> The hyphens that mean "this word goes on", as against the dashes that are
> punctuation. Only these are checked below: an em dash at the end of a piece
> is a sound cut off -- Jane Remover's "Y— Y— Y— Y—" is written that way on
> purpose, 44 times in this folder -- and a gap after one of those is how a
> dash is written. A gap after a plain hyphen is never anything but a mistake.

**line 985** — before `DASHES = "-‐‑‒–—"`

> Every dash a lyric writes a stutter or a spelled-out word with. The same
> list the player splits words on; see lyrics_gui.DASHES.


## `_initialism`

**line 1067** — before `pieces = pieces[:-1] + [pieces[-1][:-len(tail)]]`

> The ending rides on the last letter: S, S, R, Is. Taken off, what is
> left has to be the letters themselves, like any other initialism.


## `_check_splits`

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
> the vowel test included: gc's kept splits hold be·la·ng·rijk,
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
> which is how everybody times a contraction, gc included (the
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


## `_check_between`

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


## `_case_of`

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


## module level

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


## `_cutter`

**line 1584** — before `return "not checked", None, "", None`

> Asked for outright. A document written in a language neither rule
> knows is a document where every seam is a disagreement, and a
> review of it is unreadable until the split check is out of the way.

**line 1611** — before `return "the sung rule", (lambda word: SY.split(word, "sung", lang)), "", None`

> Hyphenation cannot be had here at all: no pyphen, or no patterns.
> The primary falls back to the sung rule if that is what was asked
> for, and the second opinion is simply missing -- which makes the
> split check stricter, and is said on screen rather than hidden.


## module level

**line 1645** — before `PREFER = {"en": "en_US"}`

> pyphen's bare "en" is the British pattern set, and it refuses words the
> American one breaks -- "nosebleeds" among them, which is a word gc timed as
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


## `review`

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
