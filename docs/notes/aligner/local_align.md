# `aligner/local_align.py`

Comments lifted out of `aligner/local_align.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 53** — before `MIN_SCORE = 0.005`

> How confident a word has to be before its timing is used.
>
> This is set for SINGING, not speech, and the difference is large. The aligner
> is a speech model; over a dense mix its confidence collapses even where it is
> placing words correctly. Measured against a track whose word timings were
> already known: the median score was 0.048 while the median placement was
> within 0.14s of the known answer. A speech-shaped threshold of 0.3 kept 2
> words in 607 and threw away timings that were right.
>
> Separating the vocal first lifts those scores considerably -- that measurement
> was taken on the full mix -- but the floor stays where it is, because it was
> never doing the work of telling a good timing from a bad one. It only drops
> the truly hopeless. A check that the words run forwards was tried and removed,
> because CTC forced alignment is monotonic by construction: it dropped 0 of 166
> words, and the raw output stepped backwards 0 times in 186. The errors that
> remain are stretch and squeeze, where the text says more than the audio sings,
> and neither order nor confidence can see those. See the note at the foot.

**line 71** — before `PACKED_UNDER = 0.1`

> Neighbouring words closer together than this are not being sung, they are
> being caught up with. See _packed, where a song's share of them is the
> stretch-and-squeeze detector the note above says confidence cannot be.

**line 75** — before `ONSET_HOP = 160           # 10ms at 16kHz, finer than a CTC frame`

> Onset snapping (experimental, off by default -- see _onsets).

**line 76** — on `ONSET_HOP = 160`

> 10ms at 16kHz, finer than a CTC frame

**line 77** — on `ONSET_NEAR = 25`

> frames of neighbourhood a peak must stand above

**line 78** — on `ONSET_OVER = 1.4`

> and by how much

**line 79** — on `ONSET_WINDOW = 0.12`

> how far BACK a word start may be moved, in seconds

**line 80** — on `ONSET_FORWARD = 0.4`

> and forward, as a fraction of that

**line 81** — on `ONSET_DOUBT = 2.0`

> how much a later peak is doubted against an earlier

**line 82** — before `ONSET_BACK = 5            # frames a peak may walk back to the foot of its rise`

> Where the word's beginning is EXPECTED to be, relative to where CTC put it.
> CTC emits a token once it has heard enough of it, so the frame it fires on
> sits a few frames past the sound that started it -- measured at +0.060s on
> SHOWSTOPPER (438 words) and +0.064s on bipolar (114 words), flat across the
> thirds of both songs, so it is the model's habit and not either song's.
>
> This only AIMS the search; it never moves a word by itself. Scoring peaks by
> their distance from the model's own guess made the lateness self-sustaining:
> the true onset sits 0.06s behind and scores 0.06, while any spurious peak up
> to 0.03s AHEAD scores less and wins. That is why snapping used to remove only
> a seventh of the error -- it was measuring from the wrong point.

**line 93** — on `ONSET_BACK = 5`

> frames a peak may walk back to the foot of its rise

**line 94** — before `ONSET_LATE = 0.06`

> Both of the above, replayed over five songs with word-synced references --
> the share of words landing within 0.1s of one, before and after:
>
>   Havana                34% -> 51%      Deftones, Passenger    9% -> 19%
>   SHOWSTOPPER           78% -> 86%      bipolar               68% -> 75%
>   Phantom               90% -> 87%
>
> Phantom is the price and it is worth naming: CTC was already unbiased on it
> (+0.020s), so a fixed expectation of lateness overshoots and costs three
> points. Four songs gain seven to seventeen. A per-song estimate would be
> better than a constant and was tried -- measure the median distance from each
> word's guess back to the nearest onset -- but it answered 0.017 to 0.022 for
> every song alike, on songs whose real lateness ran from 0.030 to 0.224. It
> measures how dense the onsets are, not how late the model is.

**line 109** — before `ONSET_LEAD_KEPT = False`

> Whether a word that found no onset gets that lateness taken off anyway -- a
> narrower version of the flat lead below, which never touches a word an onset
> already spoke for. OFF: it moved SHOWSTOPPER two points and bipolar not at
> all, and of 384 settings swept offline none beat the shipping ones on both
> songs at once. Two points is inside the run-to-run spread measured on this
> machine, so this is "not shown to help", not "shown not to".

**line 116** — before `HEARD_SHARE = 0.35`

> What is NOT here: a flat lead. Every song measures +0.07 to +0.13s late
> against the references, and snapping back to onsets only removes about a
> seventh of it, so subtracting the rest as a constant is the obvious next move.
> It was built, rendered three ways and listened to: on a fast syllabic run
> ("yabba-dabba-doo" and the lines after it) the version with 72ms taken off is
> audibly WORSE than the version without. A constant cannot be right when the
> error it is correcting is not constant -- dense syllables need the timing the
> model gives them. The remaining lateness is left alone deliberately.
> Below this share of the lyric's words heard anywhere in the audio, the
> recording is doubted rather than the alignment.

**line 127** — before `HEARD_MARGIN = 0.15`

> How far above the unrelated-songs floor a recording must sit to be believed.
> Provisional: seven songs is not a calibration, and every song played from
> here carries these numbers, so the distribution will say where this belongs.

**line 131** — before `NULL_FLOOR = 0.05`

> Below this, the unrelated songs share so little with the transcript that
> there is no scale left to measure a margin on -- a language mismatch, not
> a wrong recording.

**line 135** — before `VERIFY_MODEL = "openai/whisper-base"`

> The verifier only has to recognise words, not time them, so it uses a model
> small enough to fit beside everything else on the card.

**line 138** — before `COMMON = frozenset("""`

> Ignored when asking whether a transcript is of these words: every English
> lyric contains them, so they raise the floor and the ceiling together and
> leave less room between the two.

**line 157** — before `MAX_WORD = 4.0`

> A word cannot sensibly run longer than this. The aligner will stretch one word
> across an instrumental break if the text says a word is there and the audio
> disagrees, and the result is a syllable that fills for eight seconds.

**line 164** — before `# --------------------------------------------------------------------------`

> the text frontend
>
> MMS_FA's entire vocabulary is 29 symbols: a-z, apostrophe, hyphen, star. It is
> multilingual not because it knows other alphabets but because it expects the
> text to arrive ROMANISED -- that is what uroman is for, and it is the half of
> the model's own design this file used to skip. `_flat` simply deleted anything
> outside [a-z'], so 無敵の笑顔 became "" and every Japanese, Korean, Cyrillic and
> Greek word was silently dropped before the aligner ever saw it.
>
> Romanising is only half of it, though. Japanese and Chinese lines carry no
> spaces, so `text.split()` hands back the whole line as one token, and one
> token gets one span -- which is line timing wearing a word's clothing. The
> line has to be cut into units first, and each unit romanised on its own so
> the timing can be put back on the characters it came from.

**line 179** — before `UNSPACED = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿가-힣]")`

> Kana, CJK ideographs and Hangul: the scripts that do not put spaces between
> words. SL.CJK covers the first two; Hangul is added because uroman handles it
> and the same segmentation problem applies.

**line 183** — before `KANA = re.compile(r"[぀-ゟ゠-ヿ]")`

> Kana, and only kana, is what says a line is Japanese rather than Chinese.
> pykakasi reads hanzi as if they were kanji, so 你好世界 came back "sekai" with
> 好 dropped on the floor -- a Japanese reading of a Chinese line, missing a
> character. Hanzi without kana goes to uroman, which gives pinyin.

**line 192** — before `_reading: dict[str, str] = {}`

> Readings worked out while cutting a line up, kept for _flat to find later.
>
> The context is in the LINE, not the unit: 無敵 alone carries no kana, so asked
> on its own it romanises as Chinese and comes back "wudi" -- but the line it
> came from was 無敵の笑顔, plainly Japanese, and pykakasi already said "muteki"
> while segmenting it. Recomputing per unit threw that away. This is the one
> piece of state in the file; it is filled by words_of and only ever read.


## `_units`

**line 255** — before `try:`

> One conversion, read twice. This asked pykakasi the same
> question twice over -- once for the segmentation and once for
> the readings -- and they come back in the same objects.

**line 266** — before `if len(parts) > 1 and "".join(parts) == word:`

> Only trust the segmentation if it accounts for every character.
> pykakasi silently drops what its dictionary does not recognise,
> and a unit list that does not rebuild the line would put the
> timings on the wrong characters.


## `words_of`

**line 289** — before `_reading.clear()`

> `_reading` belongs to the document being read, not to the process. It
> was filled and never emptied, which is harmless for one song and is not
> what this program does: the window aligns whatever plays, for as long as
> it is open. Cleared here because this is the one place that fills it,
> and _flat reads it back within the same alignment.

**line 297** — before `for li, item in enumerate(LS._items(SL.payload(doc))):`

> _items, not payload["Content"]: an unsynced document keeps its lines under
> "Lines" and leaves "Content" empty, and reading the wrong one found no
> words at all -- on precisely the documents this is most worth doing, since
> a song with no timing anywhere has everything to gain from an alignment.

**line 303** — on `        _romanise("")`

> make sure _kakasi is decided

**line 306** — before `at = None`

> None for the lead, and a NUMBER for an ad-lib -- not a flag.
> "(Baow) (What the fuck are you doing, Toxi?)" is two answering
> voices, written apart and sung apart, and one flag folded them
> into a single group that read as one long ad-lib.


## module level

**line 321** — before `ADLIB = re.compile(r"\(([^()]*)\)")`

> An ad-lib, as everybody writing lyrics down marks one: in round brackets,
> beside the line it answers. "(What?)", "(Huh?)", "(Facts)". Square brackets
> are section headings and are not this -- _flat already reduces "[Chorus]" to
> nothing, so they never reach the aligner either way.

**line 357** — before `TRANSLATION = re.compile(`

> Genius keeps translations as separate songs, credited to a "Genius <language>
> Translations" account and titled with the language's own word for it. They
> search exactly as well as the original does -- asking for FE!N returned the
> Russian page, and the aligner timed "Просто выйди на улицу" against Travis
> Scott. is_romanization() does not catch these: a translation is not a
> transliteration, and its `language` field is the language it was translated
> INTO, which looks perfectly ordinary.
>
> Matching the artist credit is the reliable half -- that account naming is
> Genius' own convention and holds across every language. The title words are
> the second net, for hits that arrive without artist fields attached.

**line 385** — before `GENIUS_TRIES = 3`

> How many times one search query is worth asking before its silence is
> believed, and how long to wait between -- see the note inside _genius_hits.


## `_genius_hits`

**line 401** — before `lead = _bare(re.split(r"\s*[,&]\s*|\s+(?:feat|ft|with)\.?\s+", artist or "",`

> The primary artist alone, first. Spotify hands over every credited name
> and searching all of them is actively worse: "FE!N Travis Scott, Playboi
> Carti" returned a listening log, a guided meditation and four translation
> pages, because those pages carry the whole credit in their titles and the
> song itself does not. "FE!N Travis Scott" returns the song, first hit.

**line 408** — before `for query in (f"{lead} {first}".strip(), f"{first} {lead}".strip(),`

> The primary artist FIRST, before any of the title-led forms. Genius'
> search weighs the leading words hardest, so on a song only its own
> audience has heard of, the title in front buries it under famous songs
> that share the word: "SHOWSTOPPER ToxiPlays" found the song 0 times out
> of 10 while "ToxiPlays SHOWSTOPPER" found it 10 out of 10, same minute,
> same token. Case makes no difference; the order makes all of it.
>
> Added to the ladder rather than replacing it. The title-led forms are
> there for a measured reason of their own -- see the note below on FE!N --
> and every hit from every query still has to pass the proof further down,
> so an extra query can only add candidates, never promote a wrong one.

**line 423** — before `hits = []`

> Asked more than once, because giving up on one query silently
> promotes the next, and the queries are not alternatives of equal
> standing: the first two name the artist, the last is the bare title.
> A dropped connection on an artist-led query leaves the bare title
> answering for it -- other people's songs, none of which can pass the
> proof below -- and a song whose Genius page exists reads as having no
> lyrics at all.
>
> An empty answer is retried alongside a thrown one. That is cheap
> insurance, not a measured failure mode: asked twenty times across
> four spellings, this search never once disagreed with itself. What it
> does do is answer a differently-ORDERED query differently, which is
> handled above and not here.


## module level

**line 455** — before `ARTIST_MIN = 0.55`

> How alike two names have to be before they are the same act, and two titles
> before they are the same song. Both are needed now -- see genius_doc.


## `_translation`

**line 502** — before `if re.match(r"\s*genius\b", who, re.I):`

> The reliable rule, and the reason this is not just a word list: Genius
> files every translation and every romanisation under a house account
> called "Genius <something>" -- Genius Russian Translations, Genius Brasil
> Traduções, Genius Romanizations. No artist releases under that name.
> "Traduções" is what showed the word list alone was not enough; it does not
> contain "traduz", and the German and Turkish pages were caught while the
> Brazilian one sailed through.


## `genius_doc`

**line 542** — before `if not GR.is_song(hit) or GR.is_romanization(hit):`

> A romanisation is somebody else's transliteration of the song, not
> the words it is sung in -- right for the romaji panel, wrong here.

**line 552** — before `tsim = GR.similar(GR.key(_bare(title)),`

> Genius search is generous; make it prove the hit is this song rather
> than a remix, a cover or a track that merely shares a word.
>
> BOTH halves, where this used to take whichever agreed. "Either is
> enough" was written for features -- Genius puts them in the title on
> some songs and in the artist on others -- and what it actually meant
> was that one perfect half excused any other. Searching ToxiPlays'
> "LOSE MY NUMBER" scored a stranger's "bop it" at 1.00 on the title
> and ToxiPlays' own "wordle freestyle" at 1.00 on the artist, so a
> dozen hits tied at the top and the one that won was whichever the
> search happened to return first. The feature problem is real and is
> answered where it arises: _artist_alike reads every name Genius
> credits, and _bare takes the feature back out of the title.

**line 572** — before `if asim < ARTIST_MIN:`

> The whole point. A song this artist does not have on Genius is a
> song with no lyrics here -- not an invitation to take a more
> popular one that happens to share a name.

**line 577** — before `score = tsim + asim`

> Ranked on the two together so a near-miss on one has to be carried by
> a real match on the other, rather than ignored.

**line 584** — before `try:`

> WHO SINGS EACH LINE, while we are here. Genius marks the singer with type
> styling and declares what each style means in the section header --
> "[Verse 1: RM, <i>RM & Jung Kook</i>, <b>j-hope</b>]" -- and no other
> source in this program knows that at all. It costs nothing extra: the
> same page, read without throwing the tags away.
>
> The WORDS are identical either way; only the credit is added. That is
> checked rather than assumed -- voiced_lines applies clean_lines' filters
> -- because a change to the text here would silently change what the
> aligner times.

**line 608** — before `content = []`

> The shape an unsynced document takes here: lines with Text and nothing
> else. words_of() reads them through line_text(), and to_document() puts
> the measured timings back onto these same items.

**line 617** — on `            item["_who"] = line["who"]`

> for anyone reading, not rendered


## module level

**line 622** — before `HOLD = 0.6`

> How long a word may be held past the frames the aligner was sure about.
>
> CTC does not say when a word stops sounding. It says which frames it was
> confident carried that word's characters, and over a sung vowel most of the
> frames in between are blank -- so the span it reports is the consonants, and
> the held note falls outside it. Measured over two aligned songs, 40% of the
> time inside a line landed in a gap between one word's end and the next one's
> start, with a median gap of 0.10s. On screen that is every word snapping shut
> early and the fill stuttering between them.
>
> So a word runs on until the next one starts. This cap is what stops that
> turning a genuine pause into an eight-second held syllable: past it, the word
> ends and the rest of the gap is silence, which is what it is. 85% of the
> real word-to-word gaps measured were under 0.3s, and the ones above this cap
> were instrumental breaks of 4 to 20 seconds.

**line 639** — before `MIN_SYL = 0.02`

> The narrowest a syllable may be drawn, in seconds -- one frame's worth of
> the aligner's own 20ms resolution, rounded up. Nothing on screen can be
> shorter than this and still be seen, and a zero-width piece would put two
> syllables on the same instant. Used by _fill, by to_document's overlap trim
> and by the syllable splitter, which is why it is here rather than repeated
> as a literal in the three of them.

**line 648** — before `# --------------------------------------------------------------------------`

> how long the singer actually held it
>
> HOLD above is a guess, and it was always described as one: CTC does not say
> when a word stops sounding, so every word is run on by a flat 0.6s and the
> real answer -- somewhere between 0.02s and eight seconds -- is not consulted.
> It cannot be consulted from the emission either. That is the shape of the
> model: a three-second "ahhh" is the letter a for a frame or two and then
> blank, blank, blank, because blank is what CTC emits when nothing NEW is
> being said. The vowel is still sounding and the model has stopped mentioning
> it.
>
> But we are holding the answer already. demucs has just separated the vocal
> and the stem is in memory, and a stem is loud exactly while somebody is
> singing. So the aligner is used for what it is good at -- finding the edge
> of a consonant, which it does to about a fifth of a second -- and the
> waveform is used for what it is good at, which is knowing whether there is
> still a voice there.
>
> Thresholds are taken from the song rather than fixed. A stem carries bleed
> and a mastered track can sit anywhere, so "quiet" means quiet FOR THIS
> RECORDING: the level a short way up from its own floor towards its own
> loudness, both read off percentiles of its own frames.

**line 671** — on `VOICE_HOP = 0.01`

> seconds per energy frame

**line 672** — before `VOICE_LEVEL = 0.15`

> Where the line between silence and singing sits, as a fraction of the way
> from this stem's quiet level to its loud one, in dB.

**line 675** — before `VOICE_QUIET = 0.08`

> How long it has to stay down to count as stopped. Shorter than this and a
> stop consonant's own closure -- the silent moment inside "back" -- would end
> the word early.

**line 679** — before `VOICE_MAX = 2.5`

> The cap that HOLD used to be. Far more generous, because the energy is doing
> the work now and this only has to stop a runaway where the stem never goes
> quiet: a fade-out, a held pad bleeding through, a bad separation.

**line 685** — before `LEAD_MIN = 0.35`

> A copy has to be this much longer than the track, AND open with this much
> silence, before the difference is treated as padding rather than as noise in
> somebody's encoder. Below it there is nothing worth correcting and a wrong
> correction is worse than none.

**line 691** — before `SUNG_MIN = 0.8`

> A word is only asked to justify its length past this, so ordinary words --
> which are a sixth of a second here, median -- are never questioned.

**line 694** — before `SUNG_SHARE = 0.5`

> ...and it justifies it by being sung through. Half, not all: the VAD trims
> the quiet head and tail of a phrase, so a word that ends on a decaying note
> is legitimately part silence.

**line 698** — before `SUNG_LATE = 0.15`

> How much silence has to sit in FRONT of a long word before its start is
> moved to where the singing actually begins. Small, but not zero: the VAD
> clips the quiet attack of a phrase, so every word looks slightly late into
> its own span and moving on that would make everything start late.


## `lead_in`

**line 738** — before `thr = quiet + (loud - quiet) * VOICE_LEVEL`

> The same threshold Voice uses, for the same reason: read off this
> recording's own levels rather than an absolute dBFS, because a
> quietly mastered song is not a silent one.


## module level

**line 810** — before `# --------------------------------------------------------------------------`

> where the singing actually is
>
> Voice above reads an RMS envelope off the stem and calls anything above a
> threshold "voice". It is cheap and it is right most of the time, and it is
> fooled by exactly what a vocal stem is full of: demucs' bleed, a reverb tail,
> a breath, the ring of a snare that did not separate cleanly. All of those are
> energy, none of them is a word, and a word held until the energy stops is
> held through all of them.
>
> Silero says whether a frame is SPEECH rather than whether it is loud. It is
> 463k parameters and runs on the processor in well under a second, which is
> the only reason it can be asked about every song -- the rest of this file is
> careful about the card precisely because nothing else here is that small.
>
> This is the piece WhisperX has that we did not. WhisperX itself will not
> install on this interpreter -- every release since 3.3.0 caps at Python 3.12
> or 3.13, and the one version pip can reach pins a ctranslate2 with no 3.14
> wheel -- and it would be the wrong shape anyway: it segments audio in order
> to run ASR on the pieces, and our words come from Genius rather than from
> ASR. What transfers is the idea that a forced alignment should not be free to
> put a word where nobody is singing.

**line 832** — before `VAD_MIN_QUIET = 0.20`

> Silence shorter than this inside a phrase is not a gap -- it is a plosive, a
> breath, or the closure in the middle of a held word.

**line 835** — before `VAD_MIN_SPEECH = 0.10`

> A region shorter than this is not a phrase.


## `Speech.of`

**line 878** — before `x = x / peak`

> Silero expects something like a normal recording level, and a
> separated stem is usually well below one.


## `Speech.until`

**line 901** — before `return start`

> `start` is in a gap: the singing has already stopped.


## `_fill`

**line 956** — before `def spread(idx: list[int], lo: float, hi: float) -> None:`

> A run of untimed words at either end has only one side to lean on, so it
> borrows HOLD's worth of room outside the anchor and shares that. Pinning
> them to the anchor instead -- which is what this did first -- gave every
> one of them the same instant and a 20ms width, so a line beginning "And I
> know" flashed its first word and vanished. Line-initial words are exactly
> the ones CTC tends to miss, so this is the common case, not the corner.

**line 991** — before `limit = rows[i + 1]["t"][0] if i + 1 < len(rows) else end + VOICE_MAX`

> How far this word may run on: to the next one at the most, and
> otherwise until the singer stops. Without a stem to listen to this
> is the flat HOLD it always was.

**line 998** — before `end = max(end, min(limit, end + HOLD))`

> Run on to the next word, but never past the cap and never
> backwards -- a neighbour that starts before this one ends is left
> exactly as the aligner placed it.

**line 1004** — before `joins = bool(rows[i + 1].get("joined")) if i + 1 < len(rows) else False`

> IsPartOfWord means "joins the NEXT syllable with no space" -- see
> spicy_lyrics.line_words and the renderer in lyrics_gui. This file
> tracked the opposite fact, "follows the previous one", which is what
> `where` carries and what the frontend knows while it is cutting a
> line up. The two are the same information shifted by one, and not
> shifting it put every space one place early: "Jafar's staff" was
> drawn "Jaf ar'sstaff".
>
> Whole words hid this, because a document of whole words has the flag
> false everywhere and the two readings agree. It showed the moment a
> word was cut into syllables -- and it was already showing on every
> Japanese line, as a stray space after the first unit.

**line 1021** — before `got["_measured"] = round(max(r["t"][1], start + MIN_SYL), 3)`

> Where this word was MEASURED to end, before the hold ran it on.
> to_document needs the difference: a hold may run over a gap that
> is merely quiet, and must not run over one that another line's
> words are sitting in. Private, and taken off again there.


## `_unoverlap`

**line 1061** — before `return None`

> Not "keep the part that fits". Timing half a line and dropping the
> rest is the same loss in miniature -- the renderer draws a timed line
> from its syllables and an untimed one from its text, so a line with
> three syllables out of fourteen reaches the screen as those three
> words and nothing else. That is "name" where the song sings "First
> off, I love me a real nigga sayin' nothing that ain't on his name".
> Whole or untimed, never part.


## `_syllables`

**line 1094** — before `parts = (t or {}).get("parts")`

> A word stage three divided arrives as several pieces rather than
> one. The first piece inherits the word's own joining flag and the
> rest are joined to it, which is exactly what the frontend already
> does for an unspaced Japanese line -- so _fill, the hold, and the
> document below need to know nothing about any of this.

**line 1109** — before `return _fill(rows, voice, tail=want_bg is None) or None`

> The lead's last word is held on past where it was measured, because the
> line stays lit until the next one starts and a word that blinks out
> early looks wrong. An ad-lib is not lit that way -- it is a short thing
> thrown over somebody else's line and then gone -- so it ends where it was
> measured to end. On a one-syllable "(Uh)" the hold was most of it.


## `_share_gaps`

**line 1156** — before `stretches = [(a, b, at(a, "EndTime") or at(a, "StartTime"), at(b, "StartTime"))`

> (first index, last index, when the stretch starts, when it ends). The
> middle pairs are two measured lines; the ends are one measured line and
> the edge of the song.


## `to_document`

**line 1211** — before `if isinstance(voice, Speech) and end - start > SUNG_MIN:`

> A flat cap is the wrong instrument here, and measuring said so: on
> these songs nothing came near MAX_WORD, and the one word held past
> two seconds was "Tox" sung across the end of a line -- which a
> tighter cap would have thrown away for being exactly what it is.
> Length cannot tell a sustained note from a stretched mistake.
>
> Silence can. A word is doubted for the part of itself that nobody is
> singing through, so a held note keeps its length and a word smeared
> across an instrumental loses the smear. Only with a VAD to ask --
> the envelope is too easily fooled by bleed to be trusted with this.

**line 1224** — before `began = voice.since(start, end)`

> Both ends, not just the back. A long word that is mostly not
> sung has one of two faults: it is being held through silence
> that comes after it, which `until` fixes, or it was placed
> before anyone started singing and stretched to reach them,
> which only moving the START can fix. The second is what an
> instrumental flourish in an intro does to a first line, and
> it is invisible from the numbers alone -- a word held through
> an intro and a genuinely screamed note are the same shape,
> 85% of their line either way, and differ only in whether
> there is a voice inside them.

**line 1241** — before `if row.get("parts"):`

> The score floor and the word cap are asked about the WORD, before
> its pieces are looked at: a word that failed either of them has
> nothing worth dividing, and a word that passed does not become
> doubtful because it has three syllables in it.

**line 1254** — before `raw = {li: _syllables(words, where, timed, li, voice)`

> Every line's syllables, before any of them is compared with its
> neighbours. Built in full first because the repair below is about PAIRS
> of lines, and a loop that has only ever seen the lines above it cannot
> make it: it does not know where the next line starts.

**line 1261** — before `lit = [li for li in sorted(raw) if raw[li]]`

> Give the last word of each line back the room the hold took from the next
> one. _fill runs every word on until the singer stops, up to VOICE_MAX,
> and caps it at the next WORD -- but the last word of a line has no next
> word to be capped by, so it runs on into the line below. That is a hold,
> not a measurement: the aligner placed the word where it placed it, and
> everything past that is the envelope being generous.
>
> Left alone it costs whole lines. The overrun pushes `floor` past the next
> line's start, _unoverlap finds no room, and the line is dropped to
> untimed -- five of them on this song, all of them lines the aligner had
> placed perfectly well. Measured: 49 of 64 lines word-timed with the hold
> unbounded, 54 with it capped here.

**line 1276** — before `stop_at = head if b == a + 1 else min(head, tail.get("_measured", head))`

> Where the hold may reach. Normally the next line's first syllable --
> but if lines the aligner never placed sit in between, their words are
> somewhere in this gap, and a hold that fills it leaves them nowhere
> to go. "Nigga, me too" was squeezed out exactly so: the line above it
> was held right up to the line below, and _share_gaps then found a gap
> of zero to put it in. Against a gap with lines waiting in it, the
> holding line falls back to where it was measured to stop.

**line 1290** — before `floor = 0.0`

> Where the line before this one stopped sounding. A line whose first words
> were untimed borrows room before its first anchor (see _fill), and without
> this that borrowing can reach back into the line above and leave two lines
> lit at once.

**line 1308** — before `groups = []`

> The ad-libs of this line, as their own voice. Not held against
> `floor`: it is there to stop two LEADS being lit at once, and an
> ad-lib overlapping the line it answers is the whole point of it.
> Only ever alongside a lead -- a Background group under a line
> with no timing of its own has nothing to be background to.
> No `voice` for an ad-lib, deliberately. The envelope says when
> the STEM stops sounding, and the stem is one signal with both
> voices in it -- so asked when a "(Uh)" has finished it answers
> with the moment the lead finishes the line over the top of it.
> Every ad-lib on this song ran on to within a breath of its
> line's end that way: "Uh" held 3.8 seconds under a 2.0 second
> line. Without it _fill runs the last word on by its own length
> instead, which is a guess bounded by the word rather than by
> somebody else's phrase.

**line 1328** — on `                        s.pop("_measured", None)`

> private to the hold cap

**line 1334** — before `new["StartTime"] = min([new["StartTime"]]`

> The line has to contain what is inside it.
>
> StartTime and EndTime were taken from the LEAD alone, a few
> lines up, before the ad-libs of this line existed. That was
> harmless while _asides could only place an ad-lib inside the
> lead's own frames -- it could not stick out of a range it was
> cut from. ADLIB_REACH gives it three seconds past the line's
> end, and nothing widened the line to match: over 278 songs,
> 3135 ad-libs ended up sounding after the <p> they belong to
> had declared itself finished, by a median of 1.53s. A player
> lighting a line and then sweeping its syllables has no
> sensible reading of that.

**line 1350** — before `lead_text = ADLIB.sub(" ", SL.line_text(item) or "")`

> The lead's own text, with the ad-libs taken out of it: the
> renderer puts them back in brackets from the group above, and
> leaving them here as well printed each one twice.

**line 1355** — before `new["Text"] = re.sub(r"\s+([,.!?;:])", r"\1", lead_text).strip()`

> An ad-lib taken out of the MIDDLE of a line leaves its space
> behind against the punctuation that followed it: "Caveman
> drop on them niggas (Brr), yabba-dabba-doo" came back as
> "niggas , yabba". The ad-lib is gone from the lead's text, so
> the gap it sat in should close too.

**line 1362** — before `lo, hi = spoken[li]`

> CTC placed nothing here, and the speech model did. Take its
> times for the LINE -- not for the words, which it never had, so
> this line is line-timed in a word-timed document and the renderer
> already draws that: a <p> with times and plain text inside it.
>
> A measurement from the other model, not a guess between
> neighbours. Worth taking because the alternative is a line that
> never lights at all, and the two disagree by a syllable or so
> where both of them answer.

**line 1387** — before `doc2["_timing"] = "align"`

> Provenance splits the same way the graft's does: our words, their clock.

**line 1389** — before `doc2["_heard_only"] = heard_only`

> How many lines are line-timed rather than word-timed, for the caller to
> say so out loud. A document that is 90% word-timed and 10% line-timed is
> not the same thing as one that is 90% word-timed and 10% dark, and the
> count is the only way to tell them apart from outside.

**line 1395** — before `marks = sorted(t for t in (row.get("start") for row in got)`

> Whether this walk was pinned, and on how many lines. An unanchored walk
> is stretched around anything it cannot skip -- it starts tens of seconds
> late and converges by the end -- so a document that does not carry this
> cannot be told apart later from one that simply aligned badly.
> Two numbers that need no reference, computed from what is already here.
>
> The per-word floor above only drops the hopeless; its own comment says the
> errors left are stretch and squeeze, "and neither order nor confidence can
> see those". Individually, no -- but a song's WORTH of them is visible.
>
> `_packed` is the share of neighbouring words placed under a tenth of a
> second apart. Nobody sings ten words a second, so a walk that has stretched
> early and must catch up shows as a crowd of impossible durations at the
> end. Measured: healthy songs 2-10%, damaged ones 19-42%.
>
> `_score` is the median CTC score across the song. The floor uses it per
> word and the aggregate was computed and thrown away, which is why none of
> tonight's failures could be re-examined for it.

**line 1423** — before `doc2["_snapped"] = getattr(_snap, "found", None)`

> How many words an onset spoke for, which is the difference between "the
> detector works on this mix" and "this mix has no attacks in it" -- and
> those two want opposite fixes.

**line 1428** — before `agree = getattr(_phone_spans, "gap", None) or []`

> Where the two models disagree about a word. `_phone_apart` is the strong
> form -- the phoneme pass put the word somewhere that barely overlaps
> where the character pass put it -- and `_phone_gap` is how far apart they
> are on the words they do agree overlap.


## module level

**line 1445** — before `# --------------------------------------------------------------------------`

> fitting in the card
>
> Two numbers decide everything below: how much VRAM is free right now, and how
> much of it a stage would want. Neither model has a fixed appetite -- both work
> through the song a window at a time, and the window is what costs. So the
> question is never "does this fit", it is "how much may this hold at once, and
> is that still enough to be worth doing on the GPU at all".

**line 1455** — before `DEMUCS_COST = (1.1, 0.02)`

> (fixed GB, GB per second of the window) for each stage.
>
> Measured rather than guessed, on an RTX 4060 with torch 2.13/cu130, against
> what the DRIVER says this process holds -- not what the allocator reserved,
> which is about 0.12 GB short of it and is not the number the rest of the
> machine feels:
>
>     demucs htdemucs   2.0s segment  0.84 GB     7.8s segment  0.88 GB
>     MMS_FA            8.0s window   1.81 GB    30.0s window   3.36 GB
>
> The surprise is demucs, and it is worth writing down: its appetite barely
> moves with the segment at all -- 0.007 GB per second -- because with split=True
> the GPU only ever holds one segment while the assembled output stays on the
> CPU. An earlier guess of 0.35 GB per second was four times over, which cost
> nothing in safety and quite a lot in usefulness: it sent demucs to the CPU on
> any card with under 3.6 GB spare, when it would have fitted in under one.
>
> What is here is the measurement plus about a quarter for margin, since these
> are one card and one version of torch. `_shrinking()` is the safety net for
> where that margin is not enough.

**line 1478** — before `DEMUCS_WINDOW = (2.0, 7.8)`

> The longest and shortest window each stage may work in, in seconds of audio.
> Demucs' ceiling is htdemucs' own training segment; going past it is not a
> memory question but a quality one, and the model's own figure wins if it
> disagrees. The aligner's ceiling is chosen rather than given: attention is
> quadratic in the window, so past about half a minute the cost climbs faster
> than the benefit, and the seam between windows is handled by overlapping them.

**line 1487** — before `SPARE = 1.0`

> What is left on the card for everybody else, whatever we work out we need.
> A desktop with a compositor, a browser and a music player on it is already
> holding a few hundred megabytes and will ask for more without warning.

**line 1491** — before `CAP_FLOOR = 0.5`

> The least _cap will ever reserve for us, in GB and as a share of the card.
> A card so busy that `free - SPARE` comes out at nothing would otherwise have
> us set a ceiling of zero and fail on the first allocation, when what we want
> is to try small and let _shrinking() take us to the CPU if it will not go.

**line 1498** — on `MODEL = "htdemucs"`

> demucs' own default, and the best of them

**line 1499** — on `RATE = 16000`

> what the aligner works at

**line 1500** — on `SEP_RATE = 44100`

> what demucs works at

**line 1508** — before `_LOUD = False`

> Whether to narrate. Read by _emission, which otherwise reports one window in
> four -- fine for a progress line, useless for watching where a stage is.

**line 1513** — before `# --------------------------------------------------------------------------`

> not taking the machine down with us
>
> Every stage here has a CPU path, and the CPU path is not merely slower -- it
> is slower AND it takes the whole processor while it is being slower. Whisper
> on the CPU ran a 124s song for 374 seconds at full tilt on every core and
> 7.5 GB resident, on a machine that was also running the player. That is not
> a fallback, it is a denial of service against the person who asked for it,
> and it took a desktop down.
>
> Two limits, both deliberately blunt. Leave the machine some cores, and do not
> put the OPTIONAL stage on the processor at all unless asked: anchors improve
> an alignment that already works, so "no anchors" is a real answer and six
> minutes of full load is not.

**line 1527** — before `SPARE_CORES = 2`

> Cores left for everything else -- the desktop, the player, the browser the
> user is reading this in.
>
> Worth knowing what this does and does not do. torch already holds itself to
> the PHYSICAL cores, which on a 16-thread machine is 8 -- the "50% CPU" a
> stage on the processor shows is that, working exactly as intended. So this
> only bites where a build would take more, and it is not what keeps the
> machine alive. The opt-in below is.

**line 1536** — before `CPU_RAM_NEEDED = 9.0`

> What a stage on the processor needs free before it is allowed to start, in
> GB. Whisper on the CPU measured 7.5 GB resident on a 124s song; this is that
> with room to be wrong, and it is checked against MemAvailable rather than
> free memory because the page cache is not an obstacle.


## `_threads`

**line 1572** — before `if torch.get_num_threads() > want:`

> Never raise it -- torch's own default is already a considered figure
> on most builds, and this exists to take cores away, not to add them.


## `survey`

**line 1662** — before `return None`

> A driver that is present but wedged, a card that has fallen off the
> bus, CUDA built against another driver version. All of them mean the
> same thing here, which is: use the CPU.


## `_shrinking`

**line 1774** — before `_say(log, f"  {what}: out of VRAM at {lo:.1f}s — finishing on the "`

> These two stages are not optional the way the anchors are -- there
> is no alignment at all without them -- so the CPU stays their last
> resort. It is held to most of the cores rather than all of them,
> so the machine it is running on stays usable while it works.


## module level

**line 1784** — before `# --------------------------------------------------------------------------`

> audio in

**line 1845** — before `# --------------------------------------------------------------------------`

> stage one: the vocal on its own


## `separate`

**line 1866** — before `window = min(window, float(getattr(model, "segment", DEMUCS_WINDOW[1]) or`

> The model's own segment is the ceiling: asking for more than it was
> trained on is a quality question rather than a memory one, and this is
> only ever trying to use less.

**line 1871** — before `ref = wave.mean(dim=0)`

> Demucs is trained on loudness-normalised input and separates visibly worse
> without this; the same scaling is undone on the way out so the stem comes
> back at the level it went in at.


## `separate.work`

**line 1884** — before `with contextlib.suppress(Exception):`

> Older demucs takes the segment off the model rather than the call.


## `separate`

**line 1899** — before `del model`

> Order matters: the model has to be unreferenced before the cache is
> emptied, or its weights are still resident and the aligner starts a
> gigabyte down.


## module level

**line 1942** — before `# --------------------------------------------------------------------------`

> stage two: where our words land in it

**line 1944** — before `KEEP = re.compile(r"[^a-z']")`

> What the aligner's dictionary can actually take. Everything else has to be
> folded into it or dropped, and dropped words still have to keep their place in
> the caller's list -- the timings are matched back up by index.


## `_flat`

**line 1960** — before `plain = unicodedata.normalize("NFKD", _reading.get(word) or _romanise(word))`

> Nothing survived, so this is not written in the alphabet the model reads.
> Romanise it rather than dropping it -- that is what the model expects and
> is the difference between timing a Japanese song and timing none of it.


## `_w2v.aligner`

**line 2021** — before `spans = torchaudio.functional.merge_tokens(got[0], scores[0].exp(),`

> Back to probabilities before they are merged. forced_align scores
> a token by its LOG probability, and MMS_FA's own aligner hands
> back the exponent of that -- so leaving these as logs gives every
> word a negative score, and to_document's floor (0.005) then
> rejects the entire song as "most likely the wrong recording".
> The old program exponentiates at the same point, for the same
> reason.


## `_emission`

**line 2071** — before `per = (hi - lo) / max(1, got.shape[0])`

> Frames per sample for THIS window rather than a constant: the
> convolutional front end drops a fraction of a frame at each edge, and
> the last window is a different length from the rest.

**line 2079** — before `if len(parts) % (1 if _LOUD else 4) == 0:`

> One window in four is a progress line. Every window is a trace, and
> the difference matters when the question is which window is slow.


## module level

**line 2088** — before `# --------------------------------------------------------------------------`

> anchoring -- OFF BY DEFAULT since it was measured
>
> Seventeen songs, each aligned twice, once with this stage and once without:
> anchors won 0, tied 17, lost 0. Six of those songs were failing badly, which
> is the case this stage exists for, and it rescued none of them. Thinning one
> song's 32 anchors down to 1 changed its error by 0.028s -- in the free walk's
> favour -- so even good anchors were not doing work.
>
> The harm was not symmetric. Papa Roach sat at 22-30s in every measurement of
> a long day and aligns at 0.168s with the stage off; wifiskeleton went 14.628s
> to 0.099s. In both, the speech model placed a whole set of anchors tens of
> seconds from where the words are, and a monotonic walk has to reach them.
>
> The evidence that justified this stage (below) was collected when anchors
> came from a donor document, and the donor is gone -- see _anchor_points. The
> argument was never re-measured against _model_points, and does not survive it.
>
> Left in, reachable with anchors=True, because the reasoning below is sound
> for a source of anchors that is actually right, which a donor sometimes was.
>
> CTC forced alignment is monotonic and must consume every word it is given.
> That is what makes it trustworthy where the text and the recording agree,
> and it is exactly what breaks where they do not: hand it a line the song
> does not sing at that moment -- an instrumental drop, a repeated chorus
> taken from the wrong repeat -- and it cannot skip. It stretches the words
> around the hole to cover it, confidently, and one line ends up spanning
> twenty-four seconds of a track that is not singing any of it.
>
> Measured on "Fading Wind" against a line-synced copy of the same song: 53%
> of the scorable lines sat more than a second from the song's own median
> offset, 38% more than three, with single lines held across 10 to 24 seconds
> while the median line ran 2.2s. The median offset itself was +0.09s, so this
> is not the wrong recording and not a clock that needs shifting -- it is the
> alignment wandering inside a song it is otherwise placed correctly in.
>
> So: do not walk the whole song in one pass. Walk it between points already
> known to be right. A line pinned at both ends cannot be stretched across a
> break, because the frames either side of it are not the segment's to spend.
>
> The points come from a document somebody has already line-synced -- the same
> NetEase and LRCLIB entries the chain reads anyway, and which exist for
> precisely the songs this aligner is used on, since a song with word timing
> already does not come here. Their clock is not ours: they are timed against
> the streaming master and this is timed against a copy fetched from
> elsewhere. That is what the first pass is for. It is run exactly as before,
> its line starts are compared with the donor's, and the median of those
> differences is the constant between the two clocks -- measured rather than
> assumed, from our own reading of this very audio.
>
> Then the median is the thing to trust and the individual lines are not. A
> line the first pass put sixteen seconds out drags its own difference far
> from the median and no further: a median over dozens of lines does not move.
> Which is the whole trick -- the first pass is wrong in a minority of places
> and right about the offset, so it can be used to calibrate the donor without
> being believed line by line.

**line 2144** — before `ANCHOR_MIN = 6`

> Enough matched lines to believe two documents are the same performance and
> to take a median offset from. Below this the median is not a median.

**line 2147** — before `ANCHOR_TOL = 1.5`

> ...and matching by TEXT is not enough to say so. This is the check that
> cost the most to learn and the one that matters:
>
> NetEase has a line-synced "Fading Wind" whose words are this song's exactly
> -- all 37 lines pair -- and whose times belong to a different, shorter edit
> of it. Its first line sits at 44.4s where this recording sings it at 9.3s,
> and its last at 216.8s where this one is still going at 282s. Anchored on
> that, every line was dragged into the back half of the song and the result
> was far worse than no anchoring at all.
>
> Two clocks for one recording differ by a constant. Two clocks for different
> edits do not, and that is visible without knowing which is which: take the
> difference for every matched line and see whether they agree. Measured over
> sixteen aligned tracks, the split is not close --
>
>     a real line-synced copy of this recording   79, 81, 84, 86, 89%
>     the same lyrics timed against another edit   3, 7%
>
> -- so the gate goes between them, and the one ambiguous case (42%) is
> refused, which costs a single pass and no more.

**line 2169** — before `ANCHOR_AGREE = 0.75       # seconds an anchor may differ from the consensus`

> How much faster than its own average a stretch of song may be asked to be
> sung before the anchor around it is disbelieved.
>
> Anchors pin the lines the donor HAS. Lines it does not have -- a repeated
> verse it writes once and Genius writes twice -- fall between two anchors and
> have to fit in the gap, and if the gap is not big enough they are crushed
> into nothing and lost. "Gravity" lost thirteen lines that way: the donor has
> 51 where Genius has 62, and the missing ones landed in a gap sized for one.
>
> So a segment must have room to be SUNG, not merely room to hold one frame
> per character. The pace comes from the song's own first pass rather than a
> constant, because a rapper and a ballad differ by more than any figure that
> could be written here. Where the room is not there the anchor is dropped and
> the segments either side become one, which is where this started.

**line 2183** — on `ANCHOR_AGREE = 0.75`

> seconds an anchor may differ from the consensus

**line 2184** — on `ANCHOR_SHIFT = 2.0`

> how far the whole set may sit from the walk

**line 2185** — on `ANCHOR_AGREE_MIN = 3`

> anchors that must agree before any is believed


## `_anchor_points`

**line 2217** — before `try:`

> Whether these two are the same song at all is _pair's question, and it
> already answers it properly -- sequence matching over the lines, so a
> donor that splits or merges them differently still lines up, and a
> rejection when too little of it matches. A chorus sung four times is
> matched in order, which is the one way text alone can tell repeats apart.

**line 2243** — before `agree = sum(1 for x in delta if abs(x - shift) <= ANCHOR_TOL)`

> Do these two clocks differ by a constant? If they do not, this is a
> different edit of the song and its line times mean nothing here.

**line 2251** — before `return sorted((i, when[i] - shift) for i in when)`

> Every matched line becomes an anchor, not just the ones the first pass
> agreed with. Dropping the disagreements is what the graft does, because
> there a disagreement means the pairing is suspect -- here, past the gate
> above, it usually means the first pass is wrong just there, which is the
> case this exists to repair. The median is what makes that safe.


## module level

**line 2260** — before `# --------------------------------------------------------------------------`

> anchors from a model, rather than from somebody else's document
>
> _anchor_points above needs a stranger to have line-synced this exact song,
> and asks a provider chain for one by title and artist. On "LOSE MY NUMBER"
> that chain returned a different song of the same name -- NetEase's, credited
> to five songwriters none of whom are the artist -- and the words did not
> pair, so anchoring was refused and the whole song went through in one
> monotonic pass. Which is the failure this was built to prevent, arriving by
> the route that was supposed to prevent it.
>
> The premise was wrong. A donor is a guess about who else has timed this
> recording; the recording itself is right here, and a speech model will say
> where the words are in it without being asked about anybody's metadata. So
> the anchors come from listening now, and the only document in the run is
> Genius' -- which is the one that is reliably about the right song.
>
> Two things fall away with the donor, and both were only ever there to cope
> with it. The median shift: a donor is timed against the streaming master and
> we align a copy fetched from elsewhere, so the two clocks differ by a
> constant that had to be measured. ASR runs on OUR audio, so there is no
> constant -- what it heard at 41.8s was sung at 41.8s. And the clock-agreement
> gate, which existed to catch a donor timed against a different edit: there is
> no other edit here, only this file.
>
> What does NOT fall away is that the model mishears. It is asked for times
> and never for words -- the same discipline the donor was held to -- and its
> words are used only to find which of OUR words it was hearing. A mishearing
> fails to match and yields no anchor, which costs one pin out of dozens.
> Measured on this song: 332 of 485 words matched, giving 55 anchors across 64
> lines, monotonic throughout.

**line 2291** — before `ASR_MODEL = "openai/whisper-small"`

> Small is enough and is the largest that fits beside everything else. medium
> was tried first and ran the card out of memory on the cross-attentions that
> word timestamps are read from -- they are the expensive part, not the
> weights, so this is not a size that can be bought back with a smaller batch.

**line 2296** — before `ASR_COST = (1.9, 0.021)`

> Measured on the same machine as the three above, and read differently from
> any of them:
>
>     whisper-small, word timestamps    30s  2.35 GB   60s  2.46 GB   124s  4.19 GB
>
> The others are billed per WINDOW, because a window is what they hold and the
> window is ours to choose. This one is billed per SONG. Whisper chunks the
> audio itself, at 30s, and that is not where the memory goes: word timestamps
> are read from the cross-attentions, and those are kept for the whole decode.
> So the figure to fit on the card is set by the length of the track, and a
> window would say a six-minute song costs what a thirty-second one does.
>
> Which is why align() passes the song's own duration as the window. The pair
> below is a straight line through the ends of that measurement -- the middle
> point sits under it, so the fit is generous where it is wrong -- plus a few
> per cent. Small next to the quarter the CTC stages carry, and it can afford
> to be: this stage has a CPU to fall back to and nothing depends on it.

**line 2314** — before `ASR_WINDOW = (30.0, 120.0)`

> A window again, now that the decode is chunked: the least and most audio
> worth holding at once. room() picks the size from what the card actually has,
> the same as the two CTC stages -- a fixed 120s asked for 4.4 GB and was
> refused on a card with 3, which is a chunk size the machine could have
> managed twice over at 60.

**line 2320** — before `ASR_CHUNK = 120.0`

> How much song to decode at once.
>
> The cost above is per SECOND OF SONG, and it is real: word timestamps are
> read from the cross-attentions and those are kept for the whole decode. Left
> whole, a six-minute track asks for 9.5 GB and is refused by a card that could
> have done it in pieces -- "Rap God" is 364s, which is where this was noticed.
> So the song is decoded in chunks and the cost is per chunk, which makes the
> longest track cost the same as this one.
>
> The overlap is thrown away from the LATER chunk, so a word straddling a seam
> is kept once, at the reading of whichever chunk saw its beginning.


## `_asr`

**line 2353** — before `_asr_built[name] = pipeline("automatic-speech-recognition",`

> device=-1: build it on the CPU, always, and let heard() move it.
>
> Left to itself the pipeline puts the weights straight on the card
> while it builds -- and by the time this is called _cap() has
> already held our allocator down to what room() budgeted for the
> STAGE, which is less than a gigabyte on a busy card. Loading then
> failed against our own ceiling, the whole model was written off
> as unavailable, and every song went through unanchored with one
> line in the log to say so. Building here costs nothing: the model
> has to be moved per call regardless, because it must not sit on
> the card while demucs and MMS_FA are using it.


## `heard`

**line 2408** — before `_say(log, f"  {name} could not be loaded ({_asr.last_error or 'no reason given'})"`

> With the reason. "Could not be loaded" on its own sent this looking
> at the network for what turned out to be our own VRAM ceiling.

**line 2418** — before `ladder = [device]`

> The card, and the CPU only if the caller has said it may.
>
> This used to fall back on its own, on the reasoning that slow and right
> beats fast and unanchored. That was wrong about the cost. A 244M-parameter
> seq2seq decoding a whole song for word timestamps took 374 seconds on the
> processor against 22 on the card -- seventeen times, at full load on every
> core and 7.5 GB resident, while the player it was meant to be helping was
> still running. It crashed the machine it was running on. Whatever else
> this stage is, it is optional: without it the aligner does what it did
> before anchors existed, which is a complete answer.
>
> So the CPU is opt-in and says how long it will take when it is taken.

**line 2434** — on `        ladder.append(None)`

> a marker: say why, and stop

**line 2440** — before `heard.why = heard.why or "no room on the card for the speech model"`

> Only if nothing was actually tried. This marker is the LAST rung
> of the ladder, so it is reached both when the card was never an
> option and when the card was tried and failed -- and it used to
> overwrite the real reason with a guess about room, which sent me
> looking at VRAM while 3.3 GB was free.

**line 2447** — before `if dev == "cpu":`

> Asked for the processor is not the same as there being room for it.
> The run this guard exists for took the machine down rather than
> itself: a stage that will not fit is refused here, where refusing
> costs the anchors, instead of by the kernel, where it costs the
> session.

**line 2461** — before `pipe.model.to(dev)`

> Both, or neither. The pipeline keeps its OWN idea of where the
> work happens and moves the audio there; move the weights alone
> and it feeds a CUDA tensor to a CPU convolution. That is what the
> CPU fallback did on its first outing -- the retry that exists for
> when the card is full could never itself run.

**line 2496** — before `start = float(ts[0]) + edge`

> Everything is on the chunk's own clock; put it back on
> the song's, and drop what the previous chunk already saw.

**line 2527** — before `heard.why = heard.why or "the speech model did not run"`

> Distinct from hearing nothing. An empty list used to mean both "this
> audio has no words in it" and "the model never ran", and the verify
> check below reads the second as evidence about the recording -- five
> songs were reported as possibly-wrong when the card was simply full.


## `_model_lines`

**line 2576** — before `first: dict[int, float] = {}`

> A line is pinned by the first of its words the model actually caught,
> not by its first word: line-initial words are exactly the ones both this
> and CTC tend to miss, and a line pinned by its second word is pinned a
> syllable late rather than not at all.

**line 2583** — before `if n not in pairs or bg is not None:`

> A line is pinned by its lead. An ad-lib often comes in before the
> line it answers, so pinning on one puts the anchor early and the
> whole segment with it.


## `_model_points`

**line 2617** — before `out: list[tuple[int, float]] = []`

> Monotonic or it is not usable: _anchored walks segments between these and
> a pair that goes backwards would make two segments overlap. Whisper
> occasionally hands back a timestamp behind the one before it around a
> chunk seam, and one such pin is not worth losing the rest over.


## module level

**line 2636** — before `# --------------------------------------------------------------------------`

> one line at a time, and then the pairs that argued
>
> The walk above is one pass over the whole song, and its strength is also its
> weakness: CTC must consume every word in order, so the lines cannot come out
> in the wrong order -- and a line placed badly pushes the error into the next
> one, which pushes it into the one after. Anchors bound how far that can
> travel; they do not stop it.
>
> The other way round: time each line on its own, in a window around where it
> is expected, and nothing that happens to one line can reach another. What is
> lost is the guarantee. Two lines timed separately can overlap, or swap.
>
> So the overlaps are repaired afterwards, and only they: where two lines argue
> about the same audio, the pair is timed AGAIN as one piece, which puts them
> back in order because a single walk cannot do otherwise. One pass of that,
> not a loop -- lines really can overlap in a song (a phrase begun over the tail
> of the one before it), and a loop would keep pulling those apart until
> something else broke.

**line 2655** — before `LINE_PAD = 1.5`

> How much room a line is given around where it is expected, in seconds.

**line 2657** — before `LINE_TOUCH = 5`

> How much two lines may overlap before they are considered to disagree, in
> FRAMES. A seam is not an argument.

**line 2662** — before `ADLIB_REACH = 3.0`

> How far past its own line's end an ad-lib may be looked for, in seconds, and
> how much worse than the walk's answer the new placement may score before it
> is refused.
> How far PAST its own line's end an ad-lib may be looked for, in seconds.
>
> Nothing, until this was measured. _asides walks each ad-lib inside exactly
> the frames its lead occupies, so an ad-lib could not be placed after its line
> ended however plainly it was sung there -- and an ad-lib that answers the
> line it follows is the ordinary case, not the exception. With nowhere later
> to go, CTC put them as early as the window allowed: across 18 songs the
> ad-libs came in a median 0.90s EARLY, 84% of them more than 0.3s early
> against 10% late, and only 6% landed within 0.3s.
>
> Forward only. The measurement says early, so reaching backwards as well
> would widen the search in the one direction that is already wrong.


## `_per_line`

**line 2697** — before `est: dict[int, int] = {}`

> Where each line is expected. The speech model where it heard one, the
> walk otherwise -- two estimates of the same thing, and the one that did
> not come from the walk is the better bound on the walk's own mistakes.

**line 2708** — before `lit = [sp for sp in spans if sp]`

> Expected pace, for how much room a line's own characters need.

**line 2735** — before `nxt = est[order[k + 1]] if k + 1 < len(order) else frames`

> Up to the next line's own estimate, so a line is not asked to find
> itself inside the one after it.

**line 2739** — before `f1 = min(max(nxt, f0 + need), est[li] + int(need * pace * 2) + pad)`

> Up to where the NEXT line is expected, and no further. Reaching past
> it -- which the first version of this did, by a padding -- lets the
> line spread into its neighbour: every pair in the song then overlaps,
> every pair is re-timed together, and what comes out is the whole walk
> again in pieces. Enough room for the line's own characters at twice
> the song's pace, whichever is smaller.

**line 2756** — before `fixed = 0`

> One pass over the pairs that now argue. Timed together, which is the only
> thing that reliably puts two lines back in order.

**line 2765** — before `if left[-1][-1].end <= right[0][0].start + LINE_TOUCH:`

> By more than a hair. Two lines timed apart will touch at the seam
> almost every time -- the end of one word and the start of the next
> are the same instant, give or take a frame -- and treating that as a
> disagreement re-times every pair in the song, which is the whole walk
> again in pieces and worse than either.

**line 2771** — on `            continue`

> they agree; nothing to settle


## `_anchored`

**line 2804** — before `_say(log, f"  the anchors could not be worked out "`

> Said out loud, and at some cost to learn why. This swallowed a
> NameError in _model_points for a while and the only symptom was that
> every song quietly went through in one unanchored pass -- lines
> drifting seconds out with nothing in the log to say the anchors had
> never arrived. A stage that silently does nothing is the hardest kind
> of bug in this file, and this is the second time: see _anchor_points.

**line 2818** — before `apart = [(line, at, at - mine[line]) for line, at in pts if line in mine]`

> Anchors are checked against each other before any of them is trusted.
>
> One anchor 25s wrong is enough to wreck a song -- wifiskeleton lands at
> 14.6s on a single bad point, where the same song walked free lands at
> 0.116s -- and thinning a good song from 32 anchors to 1 changed nothing,
> so numbers do not protect a walk and sparsity does not endanger it. Only
> being wrong does.
>
> `mine` is where the free walk already put each line. An anchor that moves
> a line is either correcting real drift, in which case its neighbours are
> moving the same way, or it is simply misplaced, in which case it is alone.
> Keep the ones that agree with the crowd; a point that corroborates only
> itself is not evidence.

**line 2834** — before `_anchored.why = (f"anchors sit {middle:+.1f}s from the walk as a body "`

> The whole set agrees, and agrees on something impossible. When
> anchors came from a donor this was legitimate -- a stranger timed a
> different master and the offset had to be absorbed -- but the speech
> model heard THIS file. There is no clock left to differ by, so a
> consensus 25s from where the walk heard the words is not a correction
> to apply, it is the whole set being wrong together. Four such anchors
> agreed perfectly with each other and cost the song 7.8 seconds.

**line 2858** — before `bounds = [(0, 0)]`

> Strictly increasing in both, or the segments would overlap and the walk
> would stop being monotonic -- which is the property being preserved here,
> not discarded: inside a segment this is the same aligner it always was.

**line 2871** — before `lit = [sp for sp in spans if sp]`

> A segment has to have room for its own characters. Where an anchor would
> leave less than that -- a donor line landing late, a stretch of text
> denser than the audio under it -- the anchor is dropped and the two
> segments either side become one, which is no worse than not anchoring.
> This song's own pace, in frames per character, as the first pass read it.


## `_anchored.room`

**line 2884** — before `return max(n, n * pace * ANCHOR_SQUEEZE)`

> The hard floor is CTC's own -- a character cannot occupy less than a
> frame -- and the soft one is this song's pace, allowing for a stretch
> sung faster than its average.


## `_anchored`

**line 2897** — before `_anchored.why = "no anchor left its segment room for its own characters"`

> This is the path that saved wifiskeleton: it threw away anchors that
> left their segments no room, and the free walk that followed came out
> at 0.116s where three surviving anchors gave 14.628s. It was the only
> thing working correctly and it had no name.

**line 2914** — before `_anchored.last = (len(ok) - 2, len(ok) - 1)`

> Kept on the function so the finished document can carry it. Whether
> a walk was anchored is the difference between a word 0.1s out and a
> word 30s out, and it used to be knowable only by watching the log.

**line 2918** — before `at_line = {n: line for line, n in first.items()}`

> WHERE they are, not just how many. Three anchors evenly spread and three
> bunched in the first verse score the same by count and do entirely
> different things to a monotonic walk, and the gap between neighbours is
> what the stretching actually depends on.


## `_onsets`

**line 2981** — before `pad = ONSET_NEAR`

> A peak has to stand above its own neighbourhood, not above a constant:
> a quiet verse and a loud chorus have very different flux.

**line 2989** — before `_onsets.flux, _onsets.step = flux.tolist(), step`

> Walked back down the rise, because the peak of the flux is not the
> beginning of the sound -- it is the middle of the attack, a few frames
> after the sound started. Taking the top of the hill as the onset builds
> that delay into every word that snaps to it, and on a soft-attacked mix
> the hill is long. So each peak reports the foot of its own rise instead.
>
> Capped, so a peak sitting on a long swell reports the top of the swell
> rather than wherever the flux last happened to dip.
> Kept so the peak-picking and the snapping can be re-run over a grid of
> settings without a GPU: everything after this point is arithmetic on
> these numbers, and an alignment costs minutes on a card shared with
> whatever else is training.


## `_snap`

**line 3041** — before `_snap.before = [[str(r.get("word") or ""),`

> What CTC said, before any of this touched it -- the starting point every
> replayed setting has to begin from. See the note in _onsets.
> The CTC score rides along because it is the only thing this file knows
> about a word that might predict whether the word is in the right place.
> If it does, the wrong ones can be found without a reference and repaired;
> if it does not, that is worth knowing before anything is built on it.

**line 3064** — before `d = aim - marks[k]`

> Distance from where the sound that made the model fire is
> expected to be, and a peak after even THAT is doubted: it is
> more likely the next syllable than this word's beginning.

**line 3077** — before `row["start"] = round(max(floor, row["start"] - ONSET_LATE), 3)`

> No peak stands behind this word, so there is nothing to snap to
> -- but the model's lateness does not go away just because the
> onset detector missed. Take the measured amount off, and never
> past the word before it.

**line 3082** — before `if prev is not None and prev["end"] > row["start"]:`

> The end of the word before follows the start of this one.
>
> `floor` is the previous word's START, so the monotonic guard above
> only stops the two STARTS crossing -- it lets a start move back past
> where the previous word was said to END, and then two words are lit
> at once. Measured over 278 songs: CTC alone leaves 6.3% of adjacent
> words overlapping, and snapping raised that to 35.0%, in every song.
> Aiming the search earlier is what made it visible; the hole was
> always there.
>
> The end gives way rather than the start, because a start here was
> measured against a peak in the audio and an end mostly was not --
> seven ends in ten are simply the next word's start already.


## `timings`

**line 3115** — before `w2v = acoustic == "w2v"`

> Which acoustic model reads the audio -- see _w2v() for why there are two.
>
> MMS_FA is the one that is always there: it is a forced-alignment bundle
> and has been in torchaudio for as long as this file has existed, where
> wav2vec2's ASR bundle is asked for by name and may not answer on an older
> build. So a missing wav2vec2 costs the choice, not the alignment.

**line 3131** — before `wave = _resample(_channels(wave, 1), rate, bundle.sample_rate)`

> Downmix before resampling, not after: it is the same answer for half the
> arithmetic, and on a four-minute stereo stem that is a real second.

**line 3135** — before `aside = {n for n, w in enumerate(where or ()) if len(w) > 3`

> The lead's words are the walk. Ad-libs are a second voice singing at the
> same time, so they are held back here and timed against the same frames
> afterwards -- see _asides. Without `where` there is nothing marking them
> and this is the single stream it always was.
> `is not None`, not truthiness: the first ad-lib group on a line is
> numbered 0, and a plain `if w[3]` puts it back in the lead's stream.


## `timings.work`

**line 3156** — before `return _emission(_logits(moved) if w2v else moved, wave, dev, win,`

> An ASR head answers in logits; MMS_FA answers in log
> probabilities and needs no wrapping.

**line 3161** — before `moved.to("cpu")`

> Straight back to the CPU: the emission is the answer and the
> weights are a gigabyte in the way of whatever runs next.


## `timings`

**line 3175** — before `spans = aligner(emission, tokenizer(flat))`

> Alignment itself stays on the CPU. It is a walk over a frames-by-tokens
> grid rather than a matrix multiply, it takes about a second on a song, and
> keeping it here means the peak that mattered was the emission above.

**line 3179** — before `if where is not None and anchor is not None:`

> The first pass is also the calibration for the second: see _anchored.
> The emission is not recomputed for it -- that is the expensive half, and
> the walk over it is about a second on a song.

**line 3201** — before `if len(span) == len(flat[n]):`

> The span the aligner returns is per TOKEN, and a token here is one
> CHARACTER of the flattened word -- so the middle of that list, which
> this used to drop on the floor, is sub-word timing that has been
> free all along. Stage three cuts words up with it.
>
> Only kept where the two lists line up. The tokenizer is free to fold
> a character away, and a mismatched list would put a syllable
> boundary on the wrong letter without ever looking wrong.


## `_spread_frames`

**line 3238** — before `end = min(start + MAX_WORD, (at + take) * per_frame + offset)`

> MAX_WORD is to_document's other floor, and a long line under one
> short ad-lib would sail straight past it.


## `_asides`

**line 3279** — before `continue`

> A line with no lead to sing under -- nothing places it, and a
> guess would be a guess about which part of the song it is in.

**line 3283** — before `f1 = min(emission.shape[0], f1 + max(1, int(ADLIB_REACH / per_frame)))`

> Reaching past the line's end, which is the whole fix -- see the note
> on ADLIB_REACH. The lead's own span decides where to START looking;
> it has no business deciding where to stop.

**line 3291** — before `got = None`

> An ad-lib cannot be given fewer frames than it has characters, so a
> short line under a long ad-lib is CTC asking for the impossible. Not
> a reason to drop the words: they are sung, and a "(Woah)" that cannot
> be walked is still a "(Woah)" the page has to show. Share the line's
> own frames out between them instead -- the same last resort
> _share_gaps applies to whole lines, for the same reason.


## module level

**line 3328** — before `# --------------------------------------------------------------------------`

> stage three: dividing the words, for English
>
> The spans above are per character, so cutting a word into syllables at its
> own letters costs nothing and was demonstrated before any of this was
> written. The cuts come out acoustically good -- "another" divides at the
> same two places on both occurrences in a line -- and linguistically wrong in
> four ways that no rule over letters can fix, because English spelling does
> not say how many syllables a word has:
>
>     hope      ends in a letter nobody sings, and got a 20ms syllable
>     dumbed    ends in -ed that is one consonant, and got a syllable for it
>     packaged  ends in -ed that genuinely is a syllable, spelt the same way
>     around    came out ar-ound, since a letter rule cannot move the r on
>
> A pronunciation says all four outright, because there are no silent letters
> in one: count the vowels and that is the number of syllables. So the number
> of pieces and where the word divides come from espeak, and only the letters
> shown on screen come from the spelling.
>
> This is additive twice over, and both halves matter.
>
> MMS_FA still places the WORDS. That is the alignment measured at a median of
> +0.12s with 67 of 69 lines inside a quarter second, and it is not being
> replaced by a model nobody here has scored -- every word keeps the start and
> the end it already had, and this only divides the inside of it.
>
> And English is the only language that comes down here at all. espeak's
> phoneme sets are per language, while MMS_FA is multilingual precisely
> because it reads romanised text in 29 symbols -- which is what makes the
> Japanese, Korean and Chinese songs work, and what would be thrown away by
> making the phoneme path the general one. _english() has to be sure, and on
> anything it is not sure about the words stay whole exactly as before.
>
> Three tiers, each falling back to the one below it:
>
>   1. no phonemizer        words stay whole -- what this file did before
>   2. phonemizer           the count and the cut are right, and the boundary
>                           TIMES come from MMS_FA's own character spans
>   3. + the phoneme model  the boundary times are measured against a model
>                           whose vocabulary is phonemes instead of letters
>
> Tier 2 is what fixes the four words above, and it costs one G2P call for the
> song -- the whole of the linguistic argument is settled before any audio is
> involved. Tier 3 is a second 1.2 GB CTC model and a second pass over the
> song, and it buys one thing: where the boundary falls in the audio. Tier 2
> has to ask a letter model when a LETTER was sung and use that as the edge of
> a sound; tier 3 asks a model that was trained on the sounds themselves. The
> cut is in the same place on the page either way.

**line 3379** — before `PHONE_COST = (1.6, 0.08)`

> What tier 3 costs on the card, measured the same way and on the same machine
> as the two above:
>
>     wav2vec2-lv-60-espeak-cv-ft   8.0s window  1.81 GB   30.0s  3.36 GB
>
> Which is MMS_FA's figure to the hundredth, twice over, and worth writing
> down because it looks like a coincidence and is not: both are wav2vec2-large
> and what costs is the emission, not the head. 392 output symbols against 29
> is four frames' worth of floats on a song and disappears into the rounding.
>
> So this is ALIGN_COST, and the margin is the same quarter over the
> measurement. It is kept as its own name rather than aliased because the two
> are equal by measurement rather than by construction, and a different model
> here would move one and not the other.

**line 3396** — before `IPA_VOWEL = frozenset("iɪyʏeøɛœæaɶɑɒɔoʊuʉɯɤʌɐəɚɜɝɞɵɘɨᵻᵿ" "ːˑ̩̈")`

> Every vowel espeak writes, and the marks it hangs off them. A run of these
> inside a phone is a nucleus and a nucleus is a syllable -- the same rule the
> character version applied to letters, where it is a guess, and here it is
> simply what the notation means. Syllabic consonants come through carrying
> their own schwa ("little" is l ɪ ɾ əl), so they need nothing special.
> ᵻ and ᵿ are espeak's own, for the reduced vowels English writes with i and u
> and does not really say -- the second vowel of "addicted" is one, and leaving
> them out cost that word a syllable.

**line 3405** — before `DIPHTHONG = frozenset({"aɪ", "aʊ", "eɪ", "oʊ", "ɔɪ", "əʊ", "ɪə", "eə", "ʊə",`

> Two vowels next to each other are two syllables -- "chaos" is k eɪ ɑː s --
> unless espeak split a diphthong it usually writes as one phone.

**line 3409** — before `ONSET = frozenset("""bl br ch cl cr dr dw fl fr gl gn gr kl kn kr ph pl pr ps`

> What an English word is allowed to begin with, in LETTERS rather than
> sounds, since this decides where the spelling divides and not where the
> sound does. Any single consonant, plus these.

**line 3416** — before `DIGRAPH = frozenset({"th", "sh", "ch", "ph", "wh", "gh", "ng", "qu", "zh"})`

> Two letters for one sound. Maximal onset may hand the whole of one to the
> next syllable or leave the whole of it behind, and must never cut it in
> half: an-oth-er, never a-not-her.

**line 3420** — before `CHECKED = frozenset({"ɪ", "ɛ", "æ", "ʌ", "ʊ", "ɒ", "ᵻ", "ᵿ", "e"})`

> The vowels English will not end a syllable on -- the "checked" ones, which
> have to be closed by a consonant. This is the correction that stops maximal
> onset from running away with itself, and it is the clearest thing the
> phonemes buy that letters could not have said:
>
>     around    ɐ    free, so the r goes forward       a-round
>     distant   ɪ    checked, so the s stays behind    dis-tant
>     living    ɪ    checked, and there is only a v    liv-ing
>     another   ɐ ʌ  one of each                       a-noth-er
>
> Without it "distant" came out Di-stant and "pistol" pi-stol, because st is
> a perfectly legal thing for a word to begin with and nothing else was
> arguing. A long vowel or a diphthong is free and keeps the plain rule.

**line 3435** — before `ENGLISH = frozenset("""a all am an and are as at be been but by can can't come`

> Words a song in English is very unlikely to do without. The test is not "is
> this the Latin alphabet": Spanish, German, Dutch and Indonesian all pass
> that, and espeak asked for en-us would read them aloud in English --
> confidently, and as nonsense. It is not the alphabet that has to be
> recognised, it is the language.

**line 3447** — before `ENGLISH_SHARE = 0.12`

> How many of a document's words have to be on that list. English lyrics run
> well above this; the point of the floor is the languages that share the
> alphabet and score a handful of coincidences ("in", "so", "was" are German
> words too), not the ones that share nothing.

**line 3452** — before `ENGLISH_MIN = 25`

> Enough words to ask the question of at all. A four-line fragment can hit any
> share by accident.

**line 3457** — before `SPOKEN_MAX = 20000`

> Pronunciations, memoised the way _reading is and for the same reason: this
> is asked once per distinct word and a song repeats itself heavily.
> Bounded for the same reason _reading is cleared: a window left open for a
> week would otherwise accumulate every word of every English song it saw.
> Cleared wholesale rather than evicted one at a time -- this is a pure
> function of the word, so the only cost of forgetting is asking espeak again.


## `_english`

**line 3470** — before `if sum(1 for w in words if UNSPACED.search(w)) > 0.02 * max(1, len(words)):`

> An unspaced script is decided before the word list is even looked at.
> _flat romanises those, so a Japanese document arrives here as plausible
> Latin text and only the vocabulary test would be standing between it and
> an English pronunciation of romaji.


## `_speaker`

**line 3494** — before `if _g2p is False:`

> False is "there is no espeak on this machine", whoever set it -- the
> cache below is per language, and that answer is not.

**line 3506** — before `head = (lang or "").split("-")[0]`

> espeak's own spelling of a language is not always the obvious one:
> French is "fr-fr" and plain "fr" is not a voice it has, so asking for
> it failed silently and the words stayed whole. Try what was asked,
> then the doubled form, then the bare prefix.

**line 3521** — before `_g2p[lang] = EspeakBackend(name, with_stress=False)`

> Older phonemizer, fewer knobs. The defaults are the same
> answer for text already in the language asked for.


## `_pronounce`

**line 3541** — before `want = sorted({w for w in words if w and (lang, w) not in _spoken})`

> Keyed by LANGUAGE and word, not by word. "hermosa" is a different sound
> in Spanish and in English, and a cache that cannot tell them apart hands
> back whichever was asked for first -- which was invisible while this only
> ever spoke English and is a wrong answer the moment it does not.

**line 3556** — before `for w in want:`

> Asked and answered: remember the silence too, or every song retries
> a backend that is not going to start.

**line 3562** — before `_spoken[(lang, w)] = [p for p in str(said).replace("|", " ").split() if p]`

> espeak reads some tokens as several words -- "1999" comes back as
> nineteen|ninety|nine -- and for this purpose it is all one word's
> worth of sound.


## `_nuclei`

**line 3581** — on `                continue`

> the back half of one vowel, not a new one


## `_vowel_runs`

**line 3653** — before `if flat[i] in VOWEL_LETTER and not (flat[i] == "y" and i == 0):`

> A leading y is a consonant ("you"), anywhere else it is a vowel
> ("rhythm", "very"). It is the only letter that has to be asked.


## module level

**line 3667** — before `# --------------------------------------------------------------------------`

> where a written word divides, from a dictionary rather than from rules
>
> _cut_letters below works out where English spelling divides, from the letters
> up: vowel runs, maximal onset, doubled consonants, digraphs that may not be
> halved, checked vowels that need a coda. It is careful and it is documented
> and it is still a set of rules approximating a thing that is really a
> per-word fact -- it says "beau-tif-ul" where a dictionary says "beau-ti-ful".
> And it is English: applied to French it would be confidently wrong, which is
> why divide() would only ever run on English.
>
> pyphen is those facts, as hyphenation dictionaries, for 85 languages. It is
> what an old version of this program used, and asking it is a lookup rather
> than an argument.
>
> It does not replace the phonemes. The pronunciation still says HOW MANY
> pieces a word has and where they fall in the audio; this only says where the
> spelling divides to match. Where the two disagree about the count, the rules
> below are used instead -- a dictionary that wants three pieces where the
> sounds say two cannot be laid over the audio at all.


## `_speller`

**line 3697** — before `want = (lang or "en-us").replace("-", "_")`

> espeak's names are not pyphen's: en-us against en_US, and pyphen has
> some languages only as a bare code. Try the exact name, then the
> language without its region.


## `_cut_letters`

**line 3759** — before `while len(runs) > want:`

> Too many candidates: merge the neighbours with the least between them,
> rightmost first. A final silent e is separated from the vowel before it
> by one consonant at most, so it is the first to go.

**line 3770** — before `pair = next((i for i in range(len(cluster) - 1)`

> A doubled consonant is two letters for one sound, and English has
> always divided between them -- lit-tle, run-ning. ck is the same
> thing spelt differently, so pack-aged rather than pac-kaged. This
> is asked before maximal onset because it beats it: "tl" is not
> something a word may begin with, so the onset rule alone would have
> handed over only the l and written litt-le.
> ck differs from tt in where the cut goes, not whether: a doubled
> letter divides between its halves (lit-tle) and ck is a digraph that
> is never split, so the whole of it stays behind (pack-aged).

**line 3790** — before `closed = any(c not in VOWEL_LETTER`

> The syllable ending here may not be able to end on its vowel. Leave
> it a consonant -- but a digraph cannot be halved to find one, so
> where the only letter available is the back of a th or a ng, the
> whole cluster stays behind instead: a-noth-er, not a-not-her.
> A merged candidate has swallowed the consonant between its two
> halves -- "some" is one piece here, and the m inside it is already
> the coda a checked vowel needs. Without asking, "something" divided
> someth-ing, having gone looking for a coda it had all along.

**line 3807** — before `return cuts if all(b > a for a, b in zip(cuts, cuts[1:])) else [0]`

> A piece with no letters in it cannot be shown or timed. This should not
> happen -- every piece keeps its own vowel -- but a cut list that is not
> strictly increasing would put a zero-width syllable on screen.


## `_pieces`

**line 3828** — on `        return None`

> romanised, or folded: not ours to cut

**line 3829** — before `cuts = (_dict_cuts(flat, len(syl), lang)`

> The dictionary first, the rules where it has nothing to say. Same shape
> of answer either way: the index each piece starts at.

**line 3836** — before `if end - start < MIN_SYL * len(syl):`

> A word has to be long enough to hold the pieces it is about to be cut
> into. Nothing stops the aligner returning a 30ms word, and three
> syllables inside one of those would have to run backwards to fit --
> a syllable that ends before it starts is worse than an undivided word.

**line 3845** — before `at = [float(spans[syl[k][0]][0]) for k in range(1, len(syl))]`

> The measured edge of the first phone of each syllable after the
> first. Only when the letters could supply exactly as many pieces as
> the sounds asked for -- with any other count there is no saying
> which boundary is which, and the characters below are the safer
> answer than a guess dressed up as a measurement.

**line 3855** — before `got, prev = [], start`

> Word edges are MMS_FA's and stay MMS_FA's. Everything inside is pushed
> into the interval it measured, in order, leaving each piece the 20ms
> _fill treats as the narrowest a syllable may be -- so a phoneme pass
> that has wandered off cannot move a word, only divide it badly, and a
> bad division costs one word rather than the line it sits in.
>
> Nothing else is imposed. An honestly short first syllable is common in
> exactly the words this was built for -- the schwa of "a-round" is a
> fraction of the rest of it -- so a measurement is only overruled when
> keeping it would put the pieces out of order.

**line 3879** — before `if "".join(t for t, _a, _b in out) != word:`

> The invariant the frontend holds itself to as well: the pieces have to
> rebuild the word exactly, or the line on screen is no longer the line
> that was in the document.


## `_ids`

**line 3927** — on `                i += 1`

> a mark this model does not carry


## `_phone_spans`

**line 3942** — before `_phone_spans.gap, _phone_spans.apart = [], []`

> Cleared per song: last song's disagreements on this song's document
> would be worse than none.

**line 3986** — before `per, k = [], at`

> Back from the model's symbols to espeak's phones: one phone can have
> taken more than one symbol, so a phone runs from the start of its
> first to the end of its last.

**line 3998** — before `for i, item in enumerate(per):`

> A phone the vocabulary did not carry borrows the edge beside it,
> so the list stays one entry per phone and _pieces can index it.

**line 4005** — before `row = rows[n]`

> The guard against a phoneme pass that has drifted off the words:
> if what it says about this word does not overlap where MMS_FA put
> the word, none of its boundaries inside that word mean anything.

**line 4012** — before `_phone_spans.apart.append(`

> A SECOND OPINION, not just a reject. Two models read this word:
> the character head, which matches letters, and the phoneme head,
> which matches sounds. Where they disagree this violently is
> where the letters and the sound part company -- a reduced vowel,
> a word run into the next one, a syllable held past its spelling.
> Thrown away silently until now; kept so it can be looked at.


## `_logits.run`

**line 4043** — before `got = out[0] if isinstance(out, tuple) else getattr(out, "logits", None)`

> A tuple, an object with .logits, or a mapping that indexes like
> both -- transformers has answered in all three shapes across its
> versions, and the first field is the logits in every one of them.


## `divide`

**line 4067** — before `if lang:`

> Which language to pronounce this in, and whether to at all.
>
> Asked for explicitly, or English by detection, and nothing else -- which
> is a smaller promise than "espeak speaks a hundred languages" and is the
> honest one. espeak gives PHONEMES for all hundred, and the phonemes are
> not the hard part: _pieces() has to lay the syllables it finds back over
> the WRITTEN word, because the written word is what is on screen, and the
> rules it uses to do that -- ONSET, DIGRAPH, the checked vowels -- are
> English spelling. They are close to right for a transparent orthography
> (Spanish, Italian) and wrong for French, and this file has no way to know
> which it is being handed.
>
> So: `lang` is a switch for somebody who knows what their song is and can
> look at the result, not a detector. Left alone, nothing changes.

**line 4111** — before `_say(log, f"  phoneme timing unavailable ({type(exc).__name__}) — "`

> Tier 3 is the half that can fail on somebody else's model
> download, and tier 2 is a complete answer without it. Say so
> and carry on rather than losing the syllables altogether.


## module level

**line 4135** — before `# --------------------------------------------------------------------------`

> the whole of it

**line 4137** — before `heard.why = ""`

> Set by heard()/_anchored() during a run and read when the document is
> built: how many lines the walk was pinned on, or why it was not.


## `align`

**line 4168** — before `_snap.found = _snap.total = None`

> Cleared, not left over: these ride on the document, and last song's
> count on this song's answer is worse than no count at all.

**line 4187** — before `heard.why = ""`

> Cleared per run: these are read when the document is built, and a stale
> value from the previous song would claim anchors this one never had.

**line 4205** — before `def step(make) -> None:`

> Says nothing at all unless --debug asked for it, so the ordinary run
> keeps the four lines it has always printed.
>
> Takes a CALLABLE, not a string. Passing the message directly builds it
> whether or not anyone will read it -- which is waste on every ordinary
> run, and was a crash on one: a debug line asking a tensor its
> element_size() ran against a test double that had no such method, and
> took the whole alignment down through a path that is supposed to be off.

**line 4223** — before `if target and target > 0:`

> How much of this copy is silence the track does not have. Worked out
> on the mix, before separation, and applied to every time measured
> below -- see lead_in(). Only when the copy is actually longer than the
> track: silence at the head of a copy that is the RIGHT length is the
> master's own, and subtracting it would put every line early.

**line 4243** — before `mix, mix_rate = (wave.clone(), rate) if emit_from == "mix" else (None, 0)`

> Kept before demucs touches it, for `emit_from="mix"`.
>
> Separation is not free of consequence for the acoustic model: demucs
> is a mask over a spectrogram, and what it leaves behind on a loud
> mix is a vocal with holes and smeared transients where the mask was
> wrong. wav2vec2 was trained on neither -- it read clean speech. So
> "the stem is easier to hear" and "the stem is a distribution the
> model has never seen" are both true, and which one wins is a
> question about this library, not a thing to reason out. This lets
> the emission be taken from the untouched mix while everything that
> genuinely needs a separated vocal -- the VAD, the onsets, the
> syllable split -- still gets one.

**line 4262** — before `voice = Speech.of(wave, rate)`

> Built here, from the stem, before anything downsamples it. Silero
> first -- it answers "is this a word" where the envelope answers
> "is this loud", and a vocal stem is full of loud things that are
> not words. The envelope stays as the fallback for a machine
> without it.

**line 4281** — before `voice = None`

> The full mix is loud all the way through, so its energy says
> nothing about whether a voice is still there.

**line 4290** — before `pin, spoken, heard_lines = None, None, None`

> Where the lines start, heard from this very audio, used only to pin
> the walk -- never for a word of its text. `mine` is what the first
> pass measured and is not wanted: the donor this replaced needed it to
> work out the constant between two clocks, and there is only one clock
> here. Without anchors this is the single monotonic pass it always was.

**line 4297** — before `adev, achunk, awhy = room(want, ASR_COST, ASR_WINDOW, spare)`

> How much audio the card can hold at once, not how long the song
> is: the decode is chunked, so a six-minute track costs whatever
> one chunk costs. room() sizes the chunk to what is free.

**line 4304** — before `said = list(anchors_from) if anchors_from else heard(`

> Supplied from outside, or heard here. The parameter exists so a
> different speech model can be compared on equal terms: everything
> downstream is identical and only the anchors differ, which is the
> only way to tell an aligner apart from the pipeline around it.

**line 4323** — before `adev, achunk, awhy = room(want, ASR_COST, ASR_WINDOW, spare)`

> The anchors are gone -- they never won a timing -- but the speech
> model is still the only thing here that listens to the audio
> without being told what it should say. Kept as a WITNESS.
>
> It is the only check that can catch the wrong recording. Every
> timing statistic conflates "bad anchors on the right song" with
> "the right anchors on the wrong song": Papa Roach's anchors sat
> +61s out and the song was fine, while Labyrinth's audio was not
> this song at all and every per-word score cleared the floor,
> because CTC will confidently place something anywhere.
>
> Whether the words match is a different question from where they
> are, and only this can answer it.

**line 4339** — before `release()`

> The separation is finished and its stem is in memory, but the
> model that made it is still on the card. Nothing below needs it,
> and holding it means the check that catches a wrong recording is
> the first thing to be squeezed out -- on a desktop with a player
> running, that was every time.

**line 4346** — before `said = heard(wave, rate, adev, log, stop, model=asr or VERIFY_MODEL,`

> A smaller model on purpose. Anchoring needed accurate word
> timestamps; this only needs to know WHICH words are in the audio,
> and the small model's 1.9 GB is the difference between the check
> running and not running on a card that also has a player, a
> browser and a desktop on it.


## `align.met`

**line 4362** — before `want = {_flat(w) for w in text} - COMMON`

> Words that mean something. Any two English lyrics share
> "the", "you", "and", so counting them measures English
> rather than this song -- wordle freestyle scored 46%
> against a floor of 42%, and almost all of both was
> furniture.


## `align`

**line 4373** — before `if decoys:`

> Against a null, not against a threshold.
>
> "How much of the lyric did it hear" measures how well the
> speech model hears THIS GENRE, which is the confound: a
> correct lo-fi recording scored 42% and a wrong one 34%. But
> unrelated lyrics share function words with any transcript, so
> the same question asked of songs this is definitely NOT gives
> the floor for this recording and this model. A correct song
> sits far above its own floor; a wrong one sits on it. When the
> model hears the genre badly both fall together and the margin
> survives.

**line 4387** — before `_say(log, f"  the speech model heard {len(said)} words, "`

> The floor is the point. Unrelated English lyrics share
> function words with any English transcript, so a null
> near zero means the transcript and the decoys have no
> common vocabulary to share -- a different language or
> script, not a verdict about this recording. Two
> Japanese songs were flagged as wrong recordings this
> way, on nulls of exactly 0%.

**line 4415** — before `pick = acoustic`

> Which model reads the audio, when the caller has not insisted.
>
> wav2vec2 is an ENGLISH ASR head and MMS_FA is multilingual, so the
> choice is really about what the words are: wav2vec2 sounded better on
> an English track, and it has nothing to say about a Japanese one that
> MMS_FA romanises and reads. The same test the syllable stage already
> uses decides it, so a document is judged once and both stages agree.

**line 4437** — before `try:`

> On by default since it was measured: 6 songs better, 2 unchanged,
> 0 worse, against a noise floor of exactly zero -- and better by
> ear on the songs that have no reference to measure against.
>
> It is the only stage that sees a spectrogram. wav2vec2 reads the
> waveform directly, so where a sound BEGINS is not something it
> was ever told; spectral flux is information the aligner does not
> otherwise have, rather than a second opinion on what it has.

**line 4457** — before `try:`

> Stage three is decoration on a finished answer, so it is inside
> the try but must not be able to spend it: anything at all going
> wrong here leaves `got` exactly as the aligner returned it.

**line 4470** — before `align.stopped = True`

> Asked for, so not an error and not worth a traceback. The caller
> knows it stopped this; align.stopped is for anyone downstream who
> has only the None to go on.

**line 4481** — before `torch = _torch()`

> Hand back what the card is holding but no longer using. Every stage moves
> its weights off the card when it finishes, and the allocator keeps the
> freed blocks anyway -- so a player that has aligned one song sits on
> gigabytes of reserve it will not touch again until the next one. Measured
> on the running player: 4.1 GB held, which left 2.0 GB free and sent every
> stage of the next run to the CPU for want of room that was already ours.

**line 4495** — before `align.last_error = (`

> Distinct from every failure above: the models ran and answered, and
> nothing they said survived MIN_SCORE and MAX_WORD. Saying so beats
> the bare None that used to make this look like a network fault.


## module level

**line 4512** — before `# --------------------------------------------------------------------------`

> getting the audio in the first place
>
> Spotify's stream is not a file this program can open, so a copy has to come
> from somewhere else for the few minutes the alignment takes. Fetched to a
> temporary file, converted to what demucs wants, and deleted -- see `fetched()`,
> which does the deleting whether the alignment worked or not.
>
> The duration check is the part that matters technically. A search will happily
> return a live take, a remix, a sped-up upload or an hour-long compilation, and
> an alignment against the wrong recording does not fail -- it returns confident
> timings for a performance nobody is listening to. Anything that is not the
> same length as the track being played is refused.

**line 4525** — before `LENGTH_TOL = 3.0`

> How far a copy's length may sit from the track's before it is a different
> recording. Wide enough for a trailing silence or a faded outro, far short of
> an extended mix.

**line 4531** — before `FETCH_TRIES = 3`

> How many acceptable copies to try downloading before giving up.
>
> More than one because being findable and being fetchable are different
> questions, and the second one is answered by somebody else's server. Of the
> four uploads of one track that all matched its length exactly, the one this
> picked answered 403 to every request while the artist's own copy of the same
> recording downloaded in a second. Trying one and reporting failure meant a
> song that could plainly be aligned simply was not.

**line 4540** — before `PIN_TRIES = 3`

> A pinned copy is worth insisting on: giving up on it silently swaps the
> recording, which moves a song's measured error by tens of seconds.


## `find`

**line 4561** — before `seen_urls: set[str] = set()`

> More than one way of asking, because one is demonstrably not enough.
>
> "ToxiPlays i wish it was me (after all)" returns the official video
> (212s), a live take (224s) and a remix (163s), and never the album track
> at 202s -- not in the first eight results, and not in twenty either, so
> searching deeper does not reach it. The same query with "audio" on the
> end returns it first. Which shape works is a fact about YouTube's ranking
> rather than about the song, so all of them are asked and the results are
> pooled; the length test below decides between them as it always did.

**line 4576** — before `def ask_for(ask: str) -> list[str]:`

> ALL AT ONCE, AND WITHOUT EXTRACTING EACH VIDEO. Two separate costs were
> being paid here, and neither bought anything:
>
>   * yt-dlp was asked for full metadata on every hit, which makes it visit
>     each video in turn. Measured on one search: 10.3s against 1.1s with
>     --flat-playlist, for the same eight results. Everything this function
>     reads -- duration, webpage_url, uploader -- is in the flat answer;
>     nothing else was ever looked at.
>   * the three phrasings were asked one after another, so the whole thing
>     cost the sum of them.
>
> Together: 31.6s to choose a copy, before a byte of audio is fetched.

**line 4602** — before `keep, near = [], None`

> Closest length first, not search order. Search order has nothing to do
> with which upload is the right recording, and a live take three seconds
> under can easily be listed above the album cut that matches exactly --
> taking the first acceptable hit picked the live one.

**line 4611** — before `continue`

> yt-dlp writes one object per line and a progress note now and
> then. A line that is not JSON is not an error worth hearing
> about -- anything else raising here would be our own bug.

**line 4619** — on `        if url in seen_urls:`

> the same upload from two of the searches

**line 4629** — before `who = GR.key(_bare(artist)) if artist else ""`

> Length alone cannot choose between uploads of the same song, and asking
> it to was a real fault: "Illegal" had FOUR copies at +0.33s, the sort put
> them in whatever order the searches happened to return, and one of them
> is an edit whose vocals begin nine seconds later than the album's. The
> song scored 0.08s against a reference on one run and 8.98s on the next,
> with nothing in this program changed between them.
>
> So: near-ties are grouped, and inside a group the artist's own upload
> wins. An official channel is far likelier to be the master than a
> re-upload, and "who put this here" is metadata the search already
> returned and this used to throw away. Failing that the URL decides --
> arbitrary, but the same arbitrary answer every time, which is the part
> that was actually missing.


## `find.rank`

**line 4649** — before `mine = 0 if (who in theirs or theirs in who) else 1`

> "- Topic" channels are YouTube's own auto-uploads of the release.


## module level

**line 4664** — before `AUDIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "fetched"`

> Copies fetched for alignment, in the project rather than the cache so
> they are visible and removable without hunting through ~/.cache.

**line 4667** — before `AUDIO_CAP_GB = 8.0`

> What the kept copies may take up. Old ones go first, and "old" is when they
> were last USED, not fetched: the songs played often are the ones worth having.

**line 4670** — before `YT_CLIENTS = ("tv_simply", "android_vr")`

> Tried in order. Measured 2026-08-14: default 403s, web_safari has no audio
> format, these two both download. Worth re-checking when fetches start
> failing again -- YouTube changes which clients it will serve. Leaving the
> default IN the list is not harmless: yt-dlp then picks its format (251) and
> 403s on it, so the working clients never get asked.

**line 4676** — before `FETCH_RETRIES = 4`

> How many times a download is retried before the copy is given up on, and
> how long to wait between (multiplied by the attempt number).


## `fetch`

**line 4722** — before `cmd = list(base)`

> Which client yt-dlp claims to be, and WHY this is now a fallback rather
> than the first thing tried.
>
> These two clients were pinned because the default was getting "403:
> Forbidden" on the media URL -- half of one evening's fetches. That was
> true of the yt-dlp of the day. It is now the other way round: on
> 2026.08.19 the default clients serve and `android_vr` is the one that
> 403s, so the workaround had become the fault. Six songs of a nine-song
> benchmark could not be fetched because of it, which read as YouTube
> blocking us and was our own flag.
>
> So: default first, these second. Whichever way the far end turns next,
> one of the two is likely to work, and neither is baked in as the truth.

**line 4736** — before `try:`

> Retried, because the far end is unreliable rather than unwilling. The
> SAME command against the SAME video fails about half the time with a 403
> and succeeds on the next attempt seconds later. Without this the failure
> does not look like a failed download: the pinned copy is abandoned, the
> search runs again, and a different recording is aligned and pinned in its
> place. That cost three songs their copies in one evening, one of them
> ending up twenty times worse, and it looked like the aligner regressing.

**line 4745** — before `cmd = list(base) if attempt < FETCH_RETRIES // 2 else list(base) + [`

> Half the attempts as yt-dlp sees fit, half as the pinned clients.

**line 4763** — before `fetch.last_error = (said[-1].replace("ERROR: ", "") if said`

> yt-dlp puts the useful line last and a stack of context above it.


## `fetched`

**line 4803** — before `saved = _kept(tid) if tid else None`

> The copy this track was aligned against before, if there is one. The
> search is not asked again: it would not return the same candidates
> anyway, which is the whole reason this is remembered.
> The copy itself, if it was kept. A pinned URL only promises the same
> recording while YouTube will still serve it -- and tonight it would
> not: three songs lost their pin to failed downloads and were silently
> re-fetched as worse copies, one of them twenty times worse. Keeping
> the audio makes the promise real, and makes a measurement repeatable
> a week later.

**line 4823** — before `fetched.swapped = (pinned, fetch.last_error or "download failed")`

> Gone, or the far end refused, PIN_TRIES times over. Fall through
> and choose again -- a pin is a preference, not a requirement.
>
> But say so. Swapping the recording under a measurement is the
> difference between 6s of error and 23s on the same song, and it
> used to happen in silence: the numbers moved and nothing said why.

**line 4852** — before `mark = _sounds_like(got, words, decoys)`

> Listen before accepting it. Length and title agreeing is what
> got us somebody else's track under ACHOO!'s name and a
> stranger's recording under Labyrinth's -- both the right
> length, both wrong, and both silently aligned for hours.
> A transcript costs ~15s and settles it.

**line 4866** — before `if tid:`

> Remembered before it is used, so the next run of this track
> measures the same recording whatever the search says then.

**line 4873** — before `got = fetch(best[1], tmp)`

> Nothing passed. The least-wrong copy beats no copy at all, and
> the caller is told what it is getting rather than guessing.


## module level

**line 4895** — on `fetched.swapped = None`

> (url, why) when a pinned copy was abandoned

**line 4896** — on `fetched.margin = None`

> how well the copy taken matched the words

**line 4897** — on `fetched.doubted = None`

> set when every copy failed and the best was kept

**line 4901** — before `# --------------------------------------------------------------------------`

> Where this stands, measured rather than hoped.
>
> The old Space, aligning against the full mix, placed every line of a control
> track but landed only 56% of them within half a second, with the worst tenth
> around 18 seconds out.
>
> Separating the vocal first was aimed squarely at the first half of that, and
> it worked. Scored against a song whose own word timings were already known
> (Red Hot Chili Peppers, "Can't Stop" -- 269s, 74 lines, 523 words, syllable
> -timed from Spicy Lyrics and used here as the answer key):
>
>     all 523 words placed          median error   +0.12s
>     69 lines comparable           mean |error|    0.37s
>     within 0.25s   67/69  (97%)   within 0.50s   68/69  (99%)
>
> That is the aligner no longer competing with the drums for the frames it is
> scoring. Two things are worth being plain about, though.
>
> The first is that a like-for-like figure is not available: the 56% above was a
> different track. What this shows is that a vocal-only alignment can be right
> to a fifth of a second across a whole song, not the size of the improvement.
>
> The second is the outlier, and it is the same outlier as before. One line --
> "Can't stop, addicted to the shindig", which the song sings several times --
> came out 16.4 seconds early, matched to the wrong repetition. Separation does
> nothing for this and no filter can see it. Forced alignment maps the text onto
> the audio monotonically and must consume every word it is given, so wherever
> the text says something the recording does not sing there, it stretches or
> squeezes the surrounding words to cover the gap, confidently.
>
> What fixes that is anchoring, and it is built: see _anchored. Measured on
> two songs where the single pass was visibly wrong --
>
>     Gravity      worst line 22.3s -> 4.6s, 3 lines over 8s -> 2, and ten
>                  lines Genius lists that the recording does not sing lost
>                  their invented timings instead of keeping them
>     Fading Wind  no trustworthy anchor exists, so it is left alone
>
> The second is the important one. A line-synced copy of the same WORDS is not
> a line-synced copy of the same RECORDING, and NetEase's "Fading Wind" is the
> proof: all 37 lines pair by text and its times belong to a shorter edit.
> Anchored on it, every line was dragged into the back half of the song --
> far worse than the problem being fixed. ANCHOR_SHARE is what refuses it, and
> nothing here matters more than that it keeps refusing it.
>
> So anchoring is not a filter and not a repair: it is a second walk over the
> same emission, between points a human already agreed on. Where those points
> do not exist, or do not agree about the clock, this is the same single pass
> it always was -- which is most of a library, since a song somebody has
> already line-synced well is not always the song that comes here.
>
> Stage three does not touch any of the above, and is worth being exact about
> for that reason. It divides words the aligner had already placed; it cannot
> move one, and the guard in _pieces exists to keep it that way. So the figures
> stand as they are -- the same words in the same places, with the boundaries
> inside them drawn where the pronunciation says rather than where the spelling
> does. On the control track it divided 146 of 669 syllables out of the middle
> of a word, and every line still read as the line in the document.
>
> What it fixed was linguistic rather than acoustic, and the four words this
> was built for are the whole list: hope stays whole, dumbed and trapped stay
> whole, packaged divides, around divides in front of the r. What it did not
> fix, and what no amount of it will: a chorus matched to the wrong repetition
> is still 16.4 seconds out, and now it is 16.4 seconds out in syllables.
