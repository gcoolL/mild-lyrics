# `mild-lyrics/spicy_lyrics.py`

Comments lifted out of `mild-lyrics/spicy_lyrics.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## 2026-10-15 — Sudachi, and readings fitted to Genius

pykakasi reads a word it does not know a kanji at a time: お人好し o|nin|kou|shi, 解ってる kaitteru, 疼いて touite (Overcast Skies), 相も変わらず sou. Two fixes, which stack.

**Sudachi (optional).** `_segments` reads through `_sudachi_segments` when sudachipy + sudachidict_core are installed (mild-setup.py offers them, ~200 MB; on a distribution-managed Python with the venv declined they go into `pylibs/`, which is safe because sudachipy is an abi3 wheel -- the group is in TARGETABLE, without which it was reported missing and never offered), pykakasi otherwise. Its morphemes are grouped the way romanised lyrics space words (`_joins`: endings and auxiliaries on, particles and a noun's copula apart) for spacing, word starts and furigana; `line_readings` shares readings over syllables by its finest units (`fine=True`, split mode A: 飛び|乗っ), since one long word's reading shared by characters landed seams badly (to|binot). Readings from Sudachi's katakana go through pykakasi, so ー and とぅ/うぉ still romanise. `LYRIC_KANA`/`LYRIC_RUNS` and two rendaku rules keep the readings lyrics use, each counted in the saved Genius romaji: 私 watashi, 貴女/貴方 anata, 良い ii (14 to 2), 言う iu (Sudachi yuu; 5 to 1), 金 kane, 一回 ikkai, 一歩 ippo, 手はずっと te wa zutto (Sudachi found 手はず), 方 gata after a pronoun (あなた方; kata elsewhere, 8 to 5), 通り doori after a noun (8 to 2); 何 before を/が/も/か/に is nani. 明日 is left to Sudachi (asu 5 to ashita 1). Of the lines still missed, the largest share is Genius writing the sung contraction (している shiteru, していく shiteku) and words sung other than written (瞬間 toki, 真実 uso), which no dictionary has. A number with a leading 0 is read a digit at a time (`_digits_read`: Ado's 00 is zero zero), in `reading` as well as `line_readings`. Compared: unidic-lite via fugashi (260 MB) 81% vs Sudachi 82% after the same fixes; Sudachi chosen. Loads in 0.05 s, 0.015 ms a line.

**`fit_readings` (no install needed).** Where a line has Genius romaji, the pieces whose reading disagrees with it are read again from pykakasi's own dictionary (`_kanji_kana`: the word, the word with okurigana 解っ わかっ, a verb's stem from any listed form 疼く うず, else a kanji at a time with rendaku and a final っ), taking the one that spells exactly what Genius has. Used by the player's `retime_roman` and the editor's `correct_reading` on the guide they line Genius' letters up against. The same search (`_fit_span`) also cuts a word's own reading at its pieces' dictionary readings inside `line_readings` (生き|様 iki|sama, 始|ま|っ haji|ma|t) before falling back to sharing by characters.

Measured over the saved Genius romaji (2221 Japanese lines, letters folded by `_sound`): derived romaji equal to Genius 73.0% with pykakasi, 82.7% with Sudachi; with Genius' bracketed ad-libs taken out 74.2% / 83.8%, and 85.1% after the lyric readings above. Placing Genius on the syllables of the cached word syncs (11.8k syllables), syllables whose placed letters are a reading they can have: 73.5% before, 74.5% after (either reader; for these lines Genius fixes the guide anyway). Editor split over 782 Japanese lines: with Sudachi, 34 lines differ from pykakasi, all better or neutral (vowels no longer joined across words: きっ|と|い|つ; 思い, 疼い kept whole). Pop share unchanged (46% -> 45% of lines).

## 2026-10-14 — romaji seams on Readymade (Ado)

Their syllable split of Readymade showed readings in the wrong pieces and some empty. Causes in `line_readings`, each now fixed:

- `_convert` puts a っ's consonant on the next segment ("tteiro" after 黙っ); an all-kana segment cut into pieces read each piece alone and dropped it, so 黙っ|てい read dama|tei. The lead consonant is kept and the existing っ pass moves it: damat|tei, ukagat|ten.
- `mora_cut` took any n as ん: お似合い went n|iai. `_seam_ok` allows n only before a consonant, and never cuts inside a doubled consonant: 発火 hak|ka (was ha|kka).
- Kana at either end of a segment were anchored, but the result was used only when one piece was left: 寝転ぶ shared "nekorobu" by characters, ne|ko|robu. The kanji in between now share only what the kana leave: ne|koro|bu.
- X々 (`_kasane`) is one sound twice, the second maybe voiced: 赤裸々 seki|ra|ra, 鼻高々 hana|taka|daka, 人々 hito|bito.
- A っ ending a piece before a vowel or a pause is a stop and unwritten: まっ|いっか ma|ik|ka, あっ a, えっ？ e (were matsu, atsu, etsu).
- A X々 pykakasi's dictionary does not know (燦々) came back as X + 々 alone, read by the mark's name, "(kurikaesi)". `_segments` now gives such a 々 its kanji's reading again (san|san). Furigana reads 々 too, and X々 is cut as one sound twice in kana (`_kana_twice`: せき|ら|ら, たか|だか), not by character share (せ|きら|ら).
- 々/〆 were not in SCRIPTED, so the editor's `group_readings` blanked 々's reading.

A reading written in brackets after kanji (異端傾(かぶ)けば, `ruby_blocks`; the kanji are the last pykakasi word before the bracket) is the kanji's, said once: a piece holding both reads as the kana ("kabu", not "kei(kabu)"); split apart, the kana carry it and the kanji read nothing; and `furigana` puts nothing over those kanji. The editor's split keeps it one piece (`_with_ruby`), a plain Automatic split glues an old 傾|(か|ぶ) back keeping its span (`ops._join_ruby`), and `lyric_sources._apart` no longer forces a word break around such a bracket -- that was why the file read back as three words.

In the editor, `ops._share` gave every letter Genius adds at a seam to the syllable before (meant for long vowels, tou|kyou). A consonant now starts the next syllable (Ki|dzui, Hoo|dzue), except the first of a double or an ん; and no seam falls inside a doubled consonant.

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/spicy_lyrics.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### `current_track_id`

**line 118** — from the docstring, `def current_track_id(cdp=None) -> str | None:`

> The playing track's id, off the page where there is one to ask.
>
> `cdp` is a connection this caller already has open, and where it is given
> it is preferred: it is the only route on Windows and macOS, and every
> command in this tool that wants a track id has one in its hand already.
> The session bus is the fallback, for a caller with no connection.

### `peel`

**line 196** — from the docstring, `def peel(word: str) -> tuple[str, str, str]:`

> `word` as (punctuation in front, the word itself, punctuation after).
>
> The one place this project decides what "the punctuation around a word"
> is, because every rule that reads a word's spelling has to set the same
> characters aside and put them back, and a comma that counts as part of
> the word in one of them and not in another is how "fallin'" and
> "fallin'," come to be split two different ways.
>
> An apostrophe is the one mark that is not peeled: it is the word's own
> spelling rather than punctuation around it, and fallin', don't and rock
> 'n' roll are cut with it in.
>
> A space and a zero-width space peel too. They are not punctuation, but
> they are not part of the spelling either -- a zero-width one is a word
> boundary drawn without a gap -- and a word that ends in one was being
> read as ending in something that is not an e, which is how "have​"
> came back ha|ve.
>
> head + core + tail is always exactly the word that went in.

### `syllabify`

**line 215** — from the docstring, `def syllabify(word: str) -> list[str]:`

> Heuristic English syllable split. Pieces always re-join to the input.
>
> Punctuation is set aside before the spelling is read and put back after,
> so a word is cut the same way wherever it stands in a line: "fallin'",
> "fallin'," and "fallin'!" all come back fal|lin'. It is not part of any
> word's sound, and leaving it in defeated the silent-e rule below on every
> word that happened to end a phrase: "Home," came back "Ho-me," and
> "cure?" as "cu-re?", because the test asked whether the last CHARACTER
> was an e.
>
> It is peeled BEFORE the hyphen is looked for, because a hyphen is where
> the word comes apart and punctuation is not: read the other way round,
> "Bed-," was cut into "Bed-" and a comma -- a syllable made of nothing,
> which is a syllable the singer never sings.

### `split_syllables`

**line 317** — from the docstring, `def split_syllables(syls: list[tuple], mode: str = "none", threshold: float = 0.7) -> list[tuple]:`

> Optionally subdivide whole words, interpolating timings by length.
>
> mode "none" -- use the sync's own splits only. Whatever IsPartOfWord marks is
>                real measured data; nothing is invented. This is the default.
> mode "long" -- additionally subdivide only words held longer than `threshold`
>                seconds, where a static highlight is most visible.
> mode "all"  -- subdivide every standalone word.
>
> Entries already flagged IsPartOfWord are never touched in any mode.
> Interpolated boundaries are ESTIMATES, not measurements.

### `foreign`

**line 359** — from the docstring, `def foreign(text) -> bool:`

> Whether anything here is written in a script a romanisation is for.
>
> Wider than CJK on purpose -- Cyrillic, Greek, Hangul, Thai, Arabic and
> the rest all have romanisations and none of them are in that pattern --
> and asked by script rather than by code point, because a range wide
> enough to catch Vietnamese's diacritics catches Vietnamese, which is
> written in the Latin alphabet and needs nothing done to it.

### `strays_only`

**line 375** — from the docstring, `def strays_only(text) -> bool:`

> Whether the only non-Latin letters here are look-alikes in Latin words.
>
> "bе" with a Cyrillic е is an English word with a wrong key in it -- the
> review page calls it a homoglyph -- and not a line to romanise. Only
> Cyrillic and Greek, the alphabets that share letters with Latin; a word
> has to hold a Latin letter too for its odd one to be a stray.

### `canon`

**line 405** — from the docstring, `def canon(text: str) -> str:`

> Fold look-alike codepoints onto the real kanji.
>
> Some lyric sources spell 二人 with KANGXI RADICAL TWO (U+2F46) rather than
> U+4E8C. It renders identically, so nobody notices, but no romaniser or
> dictionary matches it. NFKC per character maps them back without changing
> the length, which the offset arithmetic below depends on.

### `_segments`

**line 725** — from the docstring, `def _segments(text: str, fine: bool = False) -> tuple:`

> pykakasi's segments for `text`, kept for the last few hundred.
>
> Every layout of a Japanese lyric sent every line to the dictionary again,
> and the layout is thrown away whenever the window is resized -- so a drag
> was one conversion of the whole song per step -- and `timeline` reads each
> line twice besides. The segments are only ever read or copied, so the same
> tuple can go to every caller. A conversion that fails is not kept.
>
> Read by Sudachi instead where it is installed (`_sudachi_segments`).

### `_quotes`

**line 753** — from the docstring, `def _quotes(orig: str, rom: str) -> str:`

> `rom` with the brackets pykakasi made of 「」『』 written as quotes.
>
> Those are Japanese quotation marks, and pykakasi reads every one of them
> as "(" or ")", so 「好き」と言った came out "(suki) to itta" -- which reads
> as an aside, the way a background vocal is written. Each bracket in the
> reading is matched to the mark it was made from, in order, so a real
> （） beside them stays a parenthesis.

### `particle_rom`

**line 819** — from the docstring, `def particle_rom(src: str, rom: str, at_start: bool = False) -> str:`

> A segment's reading, with は/へ/を read as the particles they are.
>
> pykakasi is a dictionary and gives these their spelling every time: は is
> `ha`, へ is `he`, を is `wo`. As grammatical particles they are said `wa`,
> `e` and `o`, and which one it is depends on the sentence, which pykakasi
> has no model of.
>
> This is applied where the reading is CUT rather than after it, and that is
> the whole of the fix. The correction used to sit in the last loop of
> line_readings, testing each SYLLABLE against the table, so it fired only
> when the lyric happened to time the particle as a syllable of its own. Over
> the 13 Japanese documents in bench/ and lyrics/ -- 143 particle characters:
>
>      76  are a segment of their own          を, は
>      44  are the last character of theirs    には -> niha, では -> deha
>      23  are buried inside one               はない, あなたはかわいい
>
> The syllable rule reached 46 of the 143. A segment is a much better place
> to ask, because the segmenter has already decided where the words are: a
> lone particle segment, or a trailing は/へ/を on an all-kana one, reaches
> 120. A line-timed Japanese lyric got none of them right before this and
> gets all of those now.
>
> The remaining 23 are left alone on purpose. はない really is "wa nai" and
> only grammar says so -- they are the OTHER fault (pykakasi having no
> morphological analyser) wearing this one's clothes, and chasing them with
> a longer table would start guessing. All-kana is the guard that keeps this
> honest: where the segmenter has bound a particle into a word with a kanji
> in it, it has made a judgement, and 今日は read as the greeting is that
> judgement being wrong in a way no table here can see.
>
> `at_start` carries the one case where は opening the text is not a
> particle -- nothing can be the topic before the topic is named.

### `kana_cut`

**line 891** — from the docstring, `def kana_cut(read: str, cut: int, low: int) -> int:`

> Nudge a split point in a KANA reading onto a mora boundary.
>
> mora_cut above works on romaji, where a mora ends on a vowel. In kana the
> rule is the other way round: small kana and the long mark belong to the
> character in front of them, so 直結 = ちょっけつ divides ちょっ / けつ and
> never ちょ / っけつ.

### `number_reading`

**line 913** — from the docstring, `def number_reading(n: int) -> str:`

> A number as it is said in Japanese, in Hepburn, up to 9999.
>
> With the sound changes that are part of the number itself -- sanbyaku,
> roppyaku, sanzen -- and none of a counter's after it (4時 is yoji, not
> yonji), which depends on the word that follows and is Genius's to spell.
> Bigger numbers are left as digits.

### `line_readings`

**line 1146** — from the docstring, `def line_readings(texts: list[str]) -> list[str]:`

> Readings for a whole line, handed back per syllable, plus the index of
> the romaniser word each syllable came from.
>
> A reading belongs to the WORD, not to its characters: romanising 明日 as
> 明 + 日 gives "mei nichi" rather than "ashita", and 二人 gives "ni nin"
> rather than "futari". Measured over unambiguous cases, per-fragment scored
> 0/14 and whole-line 9/14. So romanise the joined line for context and split
> the result back out -- where one word spans several syllables its reading is
> divided by character share, which can land the boundary a mora out inside
> that word but never gets the word itself wrong.

### `furigana`

**line 1355** — from the docstring, `def furigana(texts: list[str]) -> list[list[tuple[int, int, str]]]:`

> Kana readings for the kanji in each piece of a line.
>
> Returns, per piece, a list of (first char, last char + 1, reading) so the
> view can set each reading over exactly the characters it belongs to. The
> whole line goes to the segmenter at once, for the same reason the
> romanisation does: 明日 read character by character is "mei nichi", and only
> in context is it あした.

### `arabic_reading`

**line 1539** — from the docstring, `def arabic_reading(text: str) -> str:`

> Arabic script in Latin letters, a letter at a time.
>
> و and ي are the two letters that are sometimes a consonant and sometimes
> a long vowel, and which one is guessed from where they are: w and y at
> the start of a piece, between vowels or before one; u and i after a
> consonant. The article comes out "al-", and a shadda doubles the letter
> it sits on. Anything written in harakat is read as written.

### `hebrew_reading`

**line 1594** — from the docstring, `def hebrew_reading(text: str) -> str:`

> Hebrew in Latin letters, a letter at a time.
>
> Unpointed Hebrew writes few vowels, so this reads the consonants, the
> matres lectionis (ו as o or u, י as i) and any niqqud there is. ב כ פ
> are hard with a dagesh or at the start of a word, soft elsewhere; ש with
> a sin dot is s; a geresh makes ג צ ז the sounds borrowed words need.

### `hangul_pieces`

**line 1725** — from the docstring, `def hangul_pieces(text: str) -> list[str]:`

> Revised Romanisation, one string per character of `text`.
>
> Per character rather than per line because a reading has to be drawable
> over the block it belongs to, and because the timed pieces of a Korean
> lyric are usually single blocks -- so this is the shape both callers want
> and `hangul_reading` is the join of it.
>
> Korean is the one script here that needs no dictionary. Hangul is an
> alphabet written in syllable blocks, so a reading is the letters plus the
> rules for what happens where two of them meet -- which is why this is
> fifty lines where the Japanese reading is a package.
>
> The sound changes it does are the ones a reader would hear: a final
> sliding onto a following ㅇ (한국어 hangugeo), assimilation across a
> boundary (신라 silla, 백마 baengma, 왕십리 wangsimni), and ㅎ aspirating
> what it touches (좋고 joko, 놓다 nota). Checked against the thirteen
> worked examples the standard itself gives.
>
> What it does NOT do is palatalisation (같이 comes out gati where a Korean
> reads gachi) or the tensing a native compound puts in without writing it,
> because both need to know where the word boundaries are and nothing here
> does. A source that ships its own romanisation still wins; this is for the
> songs where none does.

### `_pypinyin`

**line 1782** — from the docstring, `def _pypinyin():`

> pypinyin if it is installed, else None -- optional, like pykakasi.
>
> Han characters cannot be read one at a time: 行 is xíng in 银行 and háng
> in 一行, 了 is le or liǎo, and the difference is the word around them. That
> is a segmenter and a dictionary, which is a package rather than a table,
> and a person who never plays a Chinese song should not have to carry it.

### `pinyin_reading`

**line 1795** — from the docstring, `def pinyin_reading(text: str, tones: bool = True) -> list[str]:`

> Pinyin per CHARACTER, one entry each, with the line for context.
>
> Handed the whole line, because that is the only way the polyphones come
> out right, and handed back per character so a reading can be set over
> exactly the character it belongs to. Anything that is not Han comes back
> as itself.

### `script_of`

**line 1817** — from the docstring, `def script_of(text, japanese: bool = False) -> str:`

> Which romanisation this text wants: "ja", "zh", "ko", one of the
> LETTERWISE alphabets, or "".
>
> Hangul and kana say whose script they are outright. Han characters do not
> -- they are shared -- so `japanese` carries what the document as a whole
> said, which is the only place that question can be answered: a Japanese
> lyric has lines that are all kanji, and one of those is not a Chinese
> song.

### `readings`

**line 1834** — from the docstring, `def readings(texts: list[str], japanese: bool = False, cont=None):`

> Romanisation per piece for a line in any script this can read.
>
> The same shape `line_readings` returns -- (readings, owner) -- because it
> IS `line_readings` where the line is Japanese. Korean and Chinese have no
> equivalent of its owner index: a reading there belongs to the character,
> so every piece answers for itself and owner stays -1, which is what tells
> `roman_of` there is no word grouping to carry over.
>
> A mixed line is read a run at a time. Songs that put an English chorus on
> a Korean verse are ordinary, and so are Japanese lines with a Chinese
> place name in them; asking the LINE what language it is gets one of them
> wrong, so the question is asked of each run of one script instead.

### `_runs`

**line 1875** — from the docstring, `def _runs(texts: list[str], japanese: bool = False):`

> The pieces of a line grouped into runs of one script, in order.
>
> A mixed line is read a run at a time. Songs that put an English chorus on
> a Korean verse are ordinary, and so are Japanese lines with a Chinese
> place name in them; asking the LINE what language it is gets one of them
> wrong, so the question is asked of each run instead. A piece with no
> script of its own -- a comma, a space, "baby" -- joins the run it is
> inside rather than breaking it in two.

### `read_line`

**line 1888** — from the docstring, `def read_line(text: str, japanese: bool = False) -> str:`

> A whole line's romanisation derived from its text, or "".
>
> For lines with no syllables to hang a reading on. Read a word -- a run
> between spaces -- at a time through `readings`, so each script is read
> the way it is on a syllable-timed line and kanji keep enough of their
> neighbours to be read in context. A word nothing here can read is kept
> as it is, which is what a Latin word in a Korean line wants.

### `can_read`

**line 1902** — from the docstring, `def can_read(texts: list[str], japanese: bool = False) -> bool:`

> Whether this machine can derive a reading for anything in `texts`.
>
> Korean always; Japanese and Chinese only where their package is
> installed, because neither can be read without a dictionary. Asked before
> a line is romanised at all, so a song in a script nothing here reads is
> left alone instead of being drawn a second time in the same letters.

### `ruby`

**line 1916** — from the docstring, `def ruby(texts: list[str], japanese: bool = False,`

> Readings to set OVER the text, per piece, for every script that has one.
>
> Furigana is the Japanese case and `furigana` is still the thing that does
> it. This is the same answer for the other two: pinyin over the hanzi it
> reads, Revised Romanisation over a Hangul block. Same shape -- per piece,
> a list of (first character, last character + 1, reading) -- so the view
> that already draws kana over kanji draws these without knowing which
> script it is looking at.
>
> Read a RUN at a time, not a piece at a time, for the reason the
> romanisation is: the pieces handed in here are whatever the wrapper laid
> out, which on a syllable-timed lyric is one character each, and 적 and 인
> read apart come out "jeok in" where 적인 together is "jeo gin". Cutting
> the run's reading back up per character puts the liaison in the right
> place and keeps the ruby saying the same thing as the row underneath.
>
> Hangul is annotated whole-block: a block IS a syllable, so there is
> nothing to line up inside it, and a reading over each one is what a reader
> who does not have the alphabet actually needs.
>
> `scripts` narrows which of the three get a reading. The player asks for
> "ja" alone: a Japanese song with a Korean verse wanted furigana over its
> kanji, not romanisation stacked over every Hangul block it already has
> in the row underneath.

### `geminate`

**line 1952** — from the docstring, `def geminate(cur: str, nxt: str) -> tuple[str, str] | None:`

> っ is a gemination mark, not the syllable "tsu".
>
> The source romanises 立っ as "tatsu" and 思いっ as "omoi tsu"; both should
> end in a doubled consonant carried onto the next syllable -- "tat"+"ta",
> "omoik"+"kiri". Hepburn doubles ch as t, so まっちゃ is "matcha".
>
> Returns the corrected pair, because the doubling may already be there.
> Where a source spells one syllable なっ instead of な + っ, the reading is
> cut into "nat" / "tte" and BOTH halves carry the consonant; adding a third
> spells "nattte". So this normalises to exactly one, wherever it sits.

### `_timeline.roman_text`

**line 2092** — from the docstring, `def roman_text(group, item=None):`

> The line's romanisation, where the line is in a script that has one.
>
> The document is not believed about this. Spicy Lyrics files a
> TransliteratedText against plenty of lines that are already in the
> Latin alphabet -- femtanyl's LOVESICK, CANNIBAL! carries "Go, go, go.
> go!" as the "romanisation" of "Go, go, go!" -- and with Romanisation
> set to "under" that draws a second row beneath a line that needed
> nothing doing to it, in the small indented type an ad-lib is drawn in.
>
> roman_of already refuses to romanise a line with nothing foreign in
> it. This is the same refusal, one level up, where it was missing.

### `_timeline.first_sung`

**line 2108** — from the docstring, `def first_sung(g):`

> When a group's own words start, which is not always when it begins.
>
> The counterpart to last_sung, and the rarer of the two: measured over
> the 527 documents in lyrics/, 114 of 25,994 lines have a first
> syllable that starts after the line says it does, by 0.83s at the
> median and by as much as 6.45s. Those are lines that light up, scroll
> into place and then sit there with nothing being sung in them.
>
> A line is its words. Where they say when it starts, they are believed.

### `_timeline.last_sung`

**line 2115** — from the docstring, `def last_sung(g):`

> When a group's own words stop, which is not when it ends.
>
> A line's EndTime is routinely stretched over the ad-libs written
> inside it -- Stronger pads every one of them out to the end of its
> backing vocal, three seconds after the singer has finished the line
> and a second after the NEXT line has started. Anything asking "is
> this line done" has to ask the syllables, not the group.

### `_timeline.bounds`

**line 2121** — from the docstring, `def bounds(group, said_start, said_end):`

> A line runs from its first word to its last one.
>
> Both ends are the group's own syllables wherever it has any, and the
> times the document states only where it has none -- a plain LRC line,
> or the 668 lines in lyrics/ that carry no syllable timing at all.
>
> The stated times are not a second opinion to be reconciled with the
> words; they are the line's packaging. 4.6% of the lines measured
> there end somewhere other than their last syllable, most of them
> LATER, because a source pads a line out over the ad-lib written
> inside it -- Stronger ends every line a second after the next one has
> started. Reading those as the line still being sung is what kept a
> finished line lit, and max(stated, sung) could never take it back.

### `same_words`

**line 2194** — from the docstring, `def same_words(text: str, rom: str) -> bool:`

> Whether a romanisation only repeats the line it is under.
>
> All Night Radio opens on a line that is already in Latin letters bar its
> punctuation, and "romanised" it came back letter for letter the same --
> so the screen showed the one line twice. Compared on letters and digits
> alone, folded for width and case: a full-width ！ is not a reading.

### `last_moment`

**line 2204** — from the docstring, `def last_moment(ln: dict):`

> The last moment anything in this line is still being sung.
>
> For a line `timeline` built this is already its end -- `bounds` settled
> that question there, out of the syllables -- and the two readings below
> agree. It stays because not every line dict comes from there: the window
> makes its own for the instrumental dots, and a caller can hand in
> anything with a `syls` in it.
>
> Both directions the stated end used to be wrong in are worth keeping
> written down, because they are why `bounds` exists. It is routinely
> LATER: a source pads a line out over the ad-lib written inside it -- see
> _sung_to, which is that direction. And it can be EARLIER: an ad-lib
> holding two voices at once is written as one group, so its syllables are
> not in time order, and the group's end tends to follow the LAST of them
> rather than the one that ends last. Marshmello's FRIENDS has it at 3:01:
> "I made it very clear;" runs to 3:05.416 and four "Ooh"s are written
> after it, the last ending at 3:04.729, which is what the group calls its
> end. Believing that stops the whole ad-lib while a word of it is still
> being sung.
>
> So the words decide, as they do everywhere else here: the line is going
> until the last of them is done, however the group was written.

### `_sung_to`

**line 2231** — from the docstring, `def _sung_to(ln: dict):`

> When this line stops being sung, which is now when it ends.
>
> It was not always: a line's end used to be whatever the source stated,
> and that is stretched over the ad-libs written inside it wherever the
> source felt like it -- every line in Stronger ends a second after the
> line AFTER it has started, because that is when its backing vocal stops.
> `bounds` settles it at the last syllable when the line is built, so for
> anything out of `timeline` the two are the same number. The preference is
> left in for line dicts made elsewhere, and because it says which of the
> two is the measurement.

### `focus_index`

**line 2254** — from the docstring, `def focus_index(lines: list[dict], pos: float, lead: float = 0.0) -> int:`

> The line the view should sit on at `pos`.
>
> Walked forward from the top rather than taken as "the newest thing
> sounding", because whether the view has earned the next line is a question
> about the line it is leaving. It moves down from a line only when
>
>   * that line is DONE -- everything it had to sing has been sung -- or
>   * that line outlasts the one after it, which makes the next line
>     something sung across the tail of this one (the second voice of a
>     trade, a line answered before it is finished). Following it is the
>     whole point; it will be over before this one is.
>
> and never otherwise, so two lines overlapping by a word no longer drag the
> view down to the second one while the first is still being sung.
>
> An ad-lib never takes the focus itself -- it is drawn beside the line it
> belongs to, not read on to -- but it does carry the view to that line. A
> chorus answered by its own backing vocals sounds the ad-lib first and the
> line a beat later, and a view that waited for the line would be showing
> the wrong part of the song while something in it was being sung. So an
> ad-lib sounding while its line has not started is enough to step down to
> that line, on the same terms as everything else here: only once the line
> being left has finished.
>
> `lead` moves the view early: with it set, the view may step down to a line
> that has not started yet, but only within `lead` seconds of its start and
> only once the line before it has finished singing. A line still sounding
> is never scrolled away from to make room for the next one.

### `payload`

**line 2308** — from the docstring, `def payload(body):`

> The lyrics document itself.
>
> The API hands one over already unwrapped, and so does everything that
> passes one around inside this program. What this still unwraps is the old
> Spicetify cache envelope -- {ExpiresAt, CacheVersion, Content: {...}} --
> because snapshots taken while that was the source are still on disk and
> are still read back by sync/ and the benchmarks.

### `unzwsp`

**line 2321** — from the docstring, `def unzwsp(text, spaced: bool = False) -> str:`

> `text` with the zero-width spaces taken out.
>
> They come in with several sources -- Spicy Lyrics' own cache writes
> "go! ​", NetEase and QQ Music mark word breaks with them -- and they
> are drawn as nothing, but they still hold a place in the string: they
> defeat a word match, and they ride out into every file written from here.
>
> `spaced` is for text that is already written with spaces in it: a whole
> line. There a zero-width space standing between two letters is the only
> thing holding two words apart, so a real space takes its place. Within a
> single syllable it is the opposite -- sources write it as GLUE, "my-" then
> "​​self", "run-" then "​n​ing" -- and a space there
> would cut a word in half. So the substitution is asked for, never assumed.
>
> Never between Chinese or Japanese characters either, which are written
> with no space between words at all. There the mark IS the whole boundary,
> and widening it into a space would respell the line.

### `unzwsp_body`

**line 2343** — from the docstring, `def unzwsp_body(body):`

> A whole document with every zero-width space gone from it.
>
> Plain removal, never the substitution `unzwsp(spaced=True)` makes, and
> that is the difference worth stating: in a document from Apple Music or
> NetEase a zero-width space standing between two letters is the only thing
> holding two words apart, so widening it into a real space is the only way
> to read the line. Spicy Lyrics' own copy is not that. It writes them in
> itself, over a line that already spells its gaps with real spaces and with
> IsPartOfWord, so there is no boundary in one to preserve -- a lumped
> "or​am" is a mark inside one word as far as anything here can tell,
> and it comes back "oram".
>
> Every string in the document, not only the syllables' Text. A zero-width
> space in a title or a songwriter's name rides out into an export exactly
> as far as one in a word does, and it is no more anybody's spelling.
>
> The document itself comes back where there was nothing to take out, rather
> than a copy of it that says the same thing. The lyric window decides
> whether an answer is NEW by asking whether it is the document it already
> has, so rebuilding an untouched one would make every redraw look like a
> fresh lyric; see LyricsView.on_lyrics, and lyric_sources.unlump, which
> has always worked this way.

### `word_ends`

**line 2365** — from the docstring, `def word_ends(text, nxt) -> bool:`

> Whether the word ends after `text`, whatever IsPartOfWord says.
>
> Some sources carry the word break in the syllable text instead of in the
> flag: Apple Music writes "I ​", "saw ​", "the ​", "signs"
> with every one of them marked part-of-word, and amll-ttml-db has lines
> where the space simply rides along at the end of a span. Both spell the
> line correctly as long as the text is kept whole -- which is why the TTML
> those documents export reads perfectly, and why reading that export back
> puts the same line on screen with its spaces.
>
> The player does not keep the text whole. It trims each syllable, because
> a syllable's own padding would otherwise be drawn twice over the space the
> flag already asks for, and the trimmed text then has nothing left to say
> the word ended -- so "I saw the signs" was drawn "Isawthesigns".
>
> So the separator is read before it is trimmed away, from either side of
> the join: a trailing one on this syllable or a leading one on the next.
> Only where both sides have something left afterwards -- a syllable that is
> nothing but a separator is padding, not a word.

### `syllables_text`

**line 2374** — from the docstring, `def syllables_text(syls) -> str:`

> The words a run of syllables spells.
>
> The space between two words is added HERE, from IsPartOfWord -- so a
> syllable that also carries one of its own inside its text spells the line
> with a double space in it. Plenty of documents do carry one: Spicy
> Lyrics' own cache writes "The " where the flag already says the word
> ends, and every one of those lines was drawn with a gap twice as wide as
> the rest. Only the EDGES are trimmed; a syllable holding two words really
> does have a space in the middle of it.

### `line_text`

**line 2386** — from the docstring, `def line_text(item, background: bool = False) -> str:`

> The words a line spells, from its own Text or from its syllables.
>
> A line that carries its own Text is written as it stands, minus anything
> invisible: line-timed sources hand back whole lines, and NetEase's are
> full of zero-width spaces where a word ends -- which is a boundary the
> line already spells with a real space, so it says nothing here and only
> rides along into whatever this line is written into.

### `_covering`

**line 2503** — from the docstring, `def _covering(item, lead, background: bool, until=None) -> dict:`

> A line's times, widened to hold every voice actually drawn inside it.
>
> The <p> used to be timed from the Lead alone. That was right while an
> ad-lib could only be placed inside the lead's own frames, and wrong the
> moment one could be placed after the line it answers: over 278 songs, 3135
> ad-libs ended up sounding after the <p> containing them had declared itself
> finished, by a median of 1.53s. A player lights a line and then sweeps its
> syllables; a syllable outside the line it belongs to has no reading.
>
> Done here rather than only on the document, so it holds for the cache's own
> documents too -- they carry the same shape and are drawn by the same code.

### `_spans`

**line 2542** — from the docstring, `def _spans(group) -> str:`

> Syllables -> <span> run, spaced per IsPartOfWord.
>
> The text is written trimmed, because a syllable's own padding would draw
> twice over the gap the flag already asks for -- and because the invisible
> half of that padding would otherwise be copied into every document written
> out of here. `word_ends` reads the break out of the padding first, so a
> source that spells the gap in the text instead of the flag still exports
> with its words apart.

### `_roman_spans`

**line 2556** — from the docstring, `def _roman_spans(group) -> str:`

> The same run of <span>s as `_spans`, carrying each syllable's reading.
>
> One span per syllable whether or not it has a reading, with the same
> times, so a reader can pair them up by position -- which is how Apple's
> own <transliterations> are laid out. A syllable with no reading is an
> empty span rather than a missing one: leaving it out would shift every
> reading after it onto the wrong syllable.

### `join_readings`

**line 2577** — from the docstring, `def join_readings(texts: list[str], readings: list[str], parts: list[bool],`

> Per-syllable readings as one line, spaced where the words part.
>
> A space goes where the lyric has one -- a syllable that is not part of
> the next one's word. Japanese has none, so a line of it is one "word"
> and its readings ran together: 夜明け前の街を歩く read back as
> "yoakemaenomachiaruku". There the romaniser's own segments say where
> the words are, and the readings are spaced there too -- "yoake mae no
> machi o aruku", which is how a romanised lyric is written.

### `_worth_spans`

**line 2647** — from the docstring, `def _worth_spans(group) -> bool:`

> Whether this group has anything the flat line text cannot say.
>
> A timing, or a word cut into pieces. Without either, spans would only be
> the whitespace between the words written a second way -- and a line-timed
> document that spelled every line out in untimed spans would no longer look
> like the line-timed document it is. With either, writing the flat text
> instead throws the work away: an unsynced lyric already cut into syllables
> came back out of a save as whole words again.

### `_player`

**line 2798** — from the docstring, `def _player(a):`

> A connection to the running Spotify, or None.
>
> Only the two commands that ask what is playing want one, and neither of
> them needs it on Linux, where the session bus answers the same question.
> Every other command here talks to the API and to the disk, so a player
> that is not running is no longer a reason to refuse to run.

### `_sources`

**line 2810** — from the docstring, `def _sources():`

> lyric_sources, imported when a command actually needs it.
>
> Not at the top, and it cannot be: lyric_sources imports THIS module, so
> the two would be a cycle. That is the shape of the stack rather than an
> accident -- this file is the document, its timeline and its renderers, and
> the fetching of every source including Spicy Lyrics lives over there with
> the others. The commands below are a front door onto it.

---

## Lift — 2026-09-26

Comments lifted out of `mild-lyrics/spicy_lyrics.py` on 2026-09-26; the line numbers are that day's.

### module level

**line 104** — before `JS_WHERE = """(() => {`

> What is playing. Still the player's own question, and the only thing here
> that wants Spotify to be running.

**line 197** — before `SAID_SYMBOLS = "$%#€£¥&"`

> Symbols that are read out as words, and so are the end of a word rather
> than punctuation after it where they touch one: bbno$ is "baby no money",
> 100% is a hundred percent. Peeled like a comma, bb|no|$ lost its last cut.

**line 477** — before `PYLIBS = pathlib.Path(__file__).resolve().parent.parent / "pylibs"`

> Where setup puts the pure-Python readers on a Python the distribution
> manages (PEP 668), beside the program rather than in the system's
> site-packages. Appended, so a real install still wins.

**line 498** — before `_COMBOS = {`

> Kana pairs pykakasi reads a character at a time. It has no entry for the
> small vowels written after another kana to spell sounds Japanese borrowed,
> so とぅ came out "tou" and ウォ "uo": God-ish's とぅとぅる read "toutouru"
> against Genius's "tu-turu", and アイウォンチュー "aiuonchuu" against "I want
> you" -- too far apart for the lines to be matched at all.


### `_hep`

**line 536** — before `run = len(piece) - len(piece.lstrip("ー"))`

> A long mark after a pair lengthens its vowel: ティー is "tii".


### module level

**line 659** — before `SMALL_VOWELS = "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮー"`

> The ones among them that carry a vowel of their own; っ does not.


### `line_readings`

**line 755** — before `for i in touched:`

> This segment needed no transliteration -- its reading IS its
> text -- so every character can be pointed at exactly, and the
> share below has nothing to guess at. Dividing it by share
> anyway moves letters across the syllable boundaries: on a line
> of Japanese with English in it the segmenter hands the whole
> English run over as one segment, and "Hell yeah yeah yeah yeah"
> timed a word at a time came out "Hell ye / a / h yea / h yea /
> h yeah" on the screen. mora_cut makes it worse rather than
> better there, because it is looking for Japanese mora in
> somebody's chorus.

**line 769** — before `pieces = [src[max(a, spans[i][0]) - a:min(b, spans[i][1]) - a]`

> Kana is read the same a piece at a time as it is whole, so
> there is nothing to share out: read each syllable's own kana.
> Sharing by character count gave てここまでおいで's お an empty
> slice, and an empty slice fell back to showing the kana itself
> -- "kokomade おoide". Only trusted when the pieces add back up
> to the whole, which a particle or a small kana can upset.

**line 780** — before `nxt = read[j + 1]`

> っ at the end of a syllable is the consonant it doubles --
> a syllable of its own, or the tail of one: だけ|だっ|た is
> dake|dat|ta. Read alone, だっ was "datsu", the pieces no longer
> added up to the whole, and the character-count fallback put
> "ke" on the wrong syllable.

**line 792** — before `lead = len(pieces[j]) - len(pieces[j].lstrip(SMALL_VOWELS))`

> A syllable that opens on a small vowel or a long mark -- と|ぅ,
> チュ|ー -- is the second half of the sound before it. Read the
> two together and give this one the vowel it ends on.

**line 804** — before `if (rom != "".join(read) and rom.startswith(head)`

> particle_rom only ever rewrites the end of the segment, so
> its reading of the last piece is what is left of `rom`.
> Where the pieces do not add up to the whole, they are still
> the better answer: kana read a syllable at a time is exact,
> and the share below can only guess.

**line 822** — before `cut = max(cut, min(cut_prev + 1, len(rom) - left))`

> Every syllable gets at least one letter while there are letters
> to give; an empty one would be drawn as its unread text.

**line 833** — before `if not re.search(r"\d", t):`

> Numbers are read, not copied: pykakasi hands "3〜6" back as it is,
> so Genius's "san kara roku" had nothing to line up against and was
> squeezed onto the syllables either side.

**line 845** — before `nxt = out[i + 1]`

> A syllable that is only っ sounds as the doubled consonant after it,
> which _convert moved onto the next syllable: 眠|っ|ちゃ|う shared out as
> ne|mu|ccha|u, and reads ne-mu|c|cha|u.


### module level

**line 941** — before `CYR_LATIN = {`

> Russian as a reader without the alphabet would spell it (BGN/PCGN-ish,
> without the diacritics), plus the Ukrainian, Belarusian and Serbian
> letters a Russian table leaves as they are. Needs no package, like Korean.

**line 972** — before `GREEK = re.compile("[Ͱ-Ͽἀ-῾]")`

> Alphabets read a letter at a time, like Cyrillic above: no dictionary, no
> package. Greek is ELOT 743 without the diacritics. Arabic and Hebrew are
> abjads -- the short vowels are only written where a text carries harakat
> or niqqud, which lyrics mostly do not -- so they come out as the letters
> say and the long vowels, "n'ish" for نعيش: a guide to the sound, as an
> Arabizi reader would write it, not a scholarly transliteration.


### `greek_reading`

**line 1004** — before `base = unicodedata.normalize("NFD", ch)`

> Drop accents and breathings but keep the diaeresis: it is what
> says αϊ is two vowels and not the digraph αι.


### module level

**line 1048** — before `"پ": "p", "چ": "ch", "ژ": "zh", "گ": "g", "ک": "k", "ڤ": "v", "ڨ": "g",`

> Persian, Urdu and the Maghrebi letters


### `georgian_reading`

**line 1226** — before `low = chr(ord(ch) - 0x0BC0) if "Ა" <= ch <= "Ჿ" else ch`

> Mtavruli capitals are the same letters 0x0BC0 further on.


### module level

**line 1233** — before `LETTERWISE = {"ru": cyrillic_reading, "el": greek_reading,`

> Scripts read a letter at a time, by script_of's name for them.


### `readings`

**line 1450** — before `word = word + texts[i] if cont and cont[i] and word else texts[i]`

> A syllable inside a word is read with the rest of the word
> in front of it: و alone starts a word and is "w", after
> نعيش it ends one and is "u". `cont[i]` says piece i carries
> on the word piece i-1 was in.


### `timeline.roman_of`

**line 1671** — before `same = ((owner[i] >= 0 and owner[i] == owner[i + 1])`

> An alphabet is read letter for letter, so a word the source
> split into syllables is still one word once it is in Latin.


### `timeline.roman_text`

**line 1716** — before `return got or read_line(raw, japanese)`

> A line-timed or static document has no syllables to read, which
> left every LRC, NetEase and QQ line of a Chinese or Korean song
> without a romanisation unless the source shipped one: read the
> line's own text instead.


### `main.load`

**line 2674** — before `if str(exc) not in said:`

> Said once. A key that is missing or refused is one fault,
> not one per song.


### `main`

**line 2708** — before `if not lines and track and time.monotonic() >= retry_at:`

> Only ever a retry after trouble: a track the API has
> answered about is settled, and a miss is held for hours by
> the cache, so this costs nothing where there is nothing.


---

## Lift — 2026-09-17

### module level

**line 88** — before `CACHE_PREFIX = "SpicyLyrics_LyricsStore"`

> WHERE SPICY LYRICS KEEPS WHAT IT HAS FETCHED, as a prefix rather than a
> name. The bucket carries a generation in its own name and the extension
> bumps it: the Marketplace build today opens "SpicyLyrics_LyricsStore_g1",
> and the builds before it opened "SpicyLyrics_LyricsStore" plainly. Pinned
> to one generation this read an empty store on every other build -- and an
> empty store is indistinguishable from Spicy Lyrics having nothing for any
> song, which is what it looked like. Every store whose name starts with this
> is read, newest generation first.
>
> It is a PREFIX everywhere it is passed, and it has to be: caches.open()
> CREATES a store that is not there, so a name guessed wrong does not fail,
> it quietly makes an empty one and reads that.

**line 101** — before `IDB_NAME, IDB_STORE = "spicylyrics", "lyricsStore"`

> ...and the IndexedDB the builds before those used, matched by prefix for
> the same reason. Only databases the page actually lists are opened, so a
> miss here cannot conjure one either.

**line 106** — before `_JS_STORES = """`

> Resolving both, in front of every snippet below that reads them.

**line 123** — before `JS_WHERE = """(() => {`

> What the page says about itself. The same two facts MPRIS publishes, asked
> of Spotify's own renderer instead -- which is the only route that exists on
> Windows and on a Mac, and is the more accurate of the two everywhere: the
> position here is the player's own rather than a property sampled off a bus.

**line 203** — before `JS_IDS = """`

> The same question with nothing but the ids wanted, which is what every tool
> here that walks the whole cache asks. It was six copies of one snippet that
> opened the store by name -- and so six more places that read an empty cache
> on a build whose generation had moved on, and made one each while they were
> at it.

**line 322** — before `# --------------------------------------------------------------------------`

> READING SPICY LYRICS' CACHE. Every route in this project that opens that
> cache comes through here, and the reason is the zero-width spaces: Spicy
> Lyrics puts them in itself, so not one of them is the lyric's own and not
> one of them should survive being read. Taking them out at the door is the
> only way that stays true -- `unzwsp` can only clean the string in front of
> it, and it was being asked in some places and not others, which is how six
> of the .ttml files here came to be written with a zero-width space sitting
> after every word.

**line 603** — before `SCRIPTED = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿ᄀ-ᇿㄱ-ㆎ가-힣ힰ-ퟻ]")`

> Every script here that a romanisation is FOR. CJK on its own leaves Hangul
> out, and Hangul is the case where a source hands us a perfectly good reading
> and nothing ever draws it: QQ Music files "na eo ddeo kae" against KiiiKiii's
> 나 어떡해 and the gate below threw it away for not being Chinese or Japanese.

**line 686** — before `_PARTICLE_SAID = {"は": ("ha", "wa"), "へ": ("he", "e"), "を": ("wo", "o")}`

> The same three, as (what pykakasi spells them, what they are read) for a
> particle sitting at the END of a segment rather than alone in one.


### `line_readings`

**line 806** — before `rom = particle_rom(src, rom, at_start=(a == 0))`

> Before the cut, not after it. See particle_rom: a segment is where
> the segmenter has already said what the words are, and a syllable is
> not -- correcting per syllable reached 46 of this collection's 143
> particles and this reaches 120.


### module level

**line 836** — before `KANA = re.compile(r"[぀-ゟ゠-ヿ]")`

> Han characters are shared; kana are not. This is what tells a Japanese
> lyric from a Chinese one, and pykakasi will read Chinese as Japanese all day
> without ever saying it cannot -- 电吉他 came back furigana'd ていおん・きち.

**line 917** — before `# --------------------------------------------------------------------------`

> Hangul and Han, which pykakasi cannot read and used to be given up on.

**line 922** — before `KO_LEAD = ("g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",`

> Revised Romanisation, by the arithmetic the code points are laid out with: a
> syllable block is (lead * 21 + vowel) * 28 + tail counted from U+AC00, so the
> jamo come back out with two divisions and no table of 11,172 syllables.

**line 929** — before `KO_TAIL = ("", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l",`

> A final consonant is not pronounced the way the same jamo is pronounced at
> the front of a block -- it is unreleased, so ㄱ ㄲ ㅋ all come out k and ㅅ ㅆ
> ㅈ ㅊ ㅌ ㅎ all come out t.

**line 935** — before `KO_MOVE = ("", "g", "kk", "ks", "n", "nj", "n", "d", "r", "lg", "lm", "lb",`

> ...except in front of a silent ㅇ, where it slides into the next block as an
> onset instead and is released after all: 한국어 is han-gu-geo, not han-guk-eo.
> The pair finals split, one letter to each side.

**line 941** — before `KO_BLEND = {("k", "n"): ("ng", "n"), ("k", "m"): ("ng", "m"),`

> Where a final and the consonant after it change each other. Each value spells
> BOTH sounds, because that is what assimilation means -- 신라 is silla, not
> sil-ra -- so the onset it swallows is not written again.
> Written as (what the block keeps, what the next block starts with), so a
> reading can still be cut up a block at a time for ruby.


### `hangul_pieces`

**line 1005** — on `            head = KO_ASPIRATE[head]`

> ㅎ before g/d/j/b: 좋고 joko

**line 1013** — on `        if nlead == 11:`

> ㅇ, silent: the final moves over

**line 1015** — before `if len(move) > 1 and KO_TAIL[tail] == move[:1]:`

> A pair final splits, one letter staying and one going across.

**line 1022** — on `        if nlead == 18:`

> ㅎ: aspirated by the final

**line 1025** — on `        if tail == 27:`

> ㅎ final: taken by the onset

**line 1034** — on `            carried = blend[1]`

> the onset the blend swallowed


### `pinyin_reading`

**line 1084** — before `if len(out) < len(text) and HAN.match(text[len(out)]):`

> A Han character yields one reading; a run of anything else comes
> back whole and is spread over the characters it came from.


### `readings`

**line 1141** — before `joined = "".join(canon(texts[i]) for i in run)`

> Both of the others are read a run at a time for the same reason the
> Japanese one is: 银行 is a bank and 一行 is a line, and a syllable
> timed on its own has lost the word that says which. Then the reading
> is cut back up by the characters each piece brought to it.


### `timeline`

**line 1283** — before `japanese = any(KANA.search(line_text(i) or "") for i in items)`

> Asked of the whole document rather than of a line: a Japanese lyric has
> lines that are all kanji, and one of those is not a Chinese song.


### `timeline.roman_of`

**line 1314** — before `if not any(y.get("TransliteratedText") for y in syls):`

> A source that carries no romanisation at all used to end the matter,
> because there was nothing to fall back on but pykakasi and pykakasi
> is only right about one of these scripts. Now there is: a reading
> can be DERIVED for any run `can_read` says this machine can read, so
> a Korean lyric nobody has ever romanised, or a Chinese one on a
> machine with pypinyin installed, gets one here rather than being
> drawn twice in its own script.

**line 1324** — before `derived, owner = readings(texts, japanese)`

> pykakasi answers for any Han character put in front of it and never
> says it could not -- it reads Chinese as Japanese, and Korean not at
> all. `readings` is what decides which script each run of the line is
> actually in and reads it with the right thing: kana and the kanji of
> a document that HAS kana through pykakasi, Hangul by the Revised
> Romanisation rules, and the rest of the Han through pypinyin where
> it is installed. The source's own romanisation still wins wherever
> it gave one.

**line 1358** — before `if all(SCRIPTED.search(r[2] or "") or not (r[2] or "").strip()`

> A "romanisation" still written in the script it was meant to leave is
> not one -- it is the line again, drawn a second time in the smaller
> type. That is what a Chinese lyric produced here before `readings`
> could read one, and it is still what a script nothing here handles
> produces, so the refusal stays: showing the line twice is worse than
> showing it once.


### `timeline`

**line 1424** — before `"group": group,`

> The line this one belongs to. An ad-lib is written as part of
> its line and is drawn hanging off it, so the two have to stay
> findable from each other after the list is flattened and a
> backing group that starts early is moved ahead of its lead.

**line 1429** — before `"sung": last_sung(lead),`

> When the singing stops, as opposed to when the line ends.


### `_finished`

**line 1535** — before `return True`

> An interlude marker: breathing dots over an instrumental gap, with
> nothing in it to sing. It is never mid-word, so it never has a claim
> on the view -- without this the marker's end IS the next line's
> start, and a scroll-ahead into a line that follows a gap could not
> begin until the moment it was too late to be ahead of anything.


### `focus_index`

**line 1581** — before `started = [i for i, ln in enumerate(lines)`

> A document of nothing but ad-libs: there is no line to read on to,
> so the newest thing that has started is as good as it gets.

**line 1586** — before `opened: dict = {}`

> When each line's ad-libs first open their mouths. Taken as "has begun"
> rather than "is sounding now": a two-word ad-lib can be over before the
> line it announces starts, and a view that followed it there and came
> back would have scrolled twice to arrive where it already was.


### module level

**line 1901** — before `LABELS = (("Title", "musicName"), ("Artist", "artists"), ("Album", "album"),`

> What a song is, as amll-ttml-db files it -- the only convention here that has
> anywhere to put a title. Apple's <head> names the writers and nothing else,
> so a document saved out of the editor with a title and an artist typed into
> its Song info box came back from disk anonymous, and the "that file holds a
> different song" guard had nothing left to compare.


### `_covering`

**line 1934** — before `if not isinstance(b, (int, float)):`

> The lead's stamps where it has them, the line's where it has not: a
> group whose syllables are still untimed carries no stamps of its own,
> and reading the pair off it alone unstamped every line-timed <p> in a
> document that had any word timing at all.


### `render_ttml`

**line 2044** — before `inner = _spans(lead) if _worth_spans(lead) else escape(line_text(item))`

> A Lead holding no syllables is not a lead -- it is a line-timed line
> wearing the word-timed shape, which every mixed document has some of.
> Written out of its own (empty) spans the words went with them: 13 of
> the 62 lines of NF's "Time" came back out of a save as empty <p>s.

**line 2053** — before `if g.get("LeadIn") and not isinstance(g.get("StartTime"), (int, float)):`

> An untimed ad-lib that opens its line is written where it
> sounds, because nothing else in the file can say so: a timed one
> is placed by its stamps whichever end it is written at, and one
> with no stamps has only its position left. Written after the
> lead like the rest, "(Promise I like it like—) Promise I like it
> like that" came back as an answer instead of a call.

**line 2066** — before `if lang:`

> Checked against the words before it is written. Providers guess this
> from a few hundred words and the guess goes wrong the same way every
> time -- an English lyric filed under a small Latin-script language.
> Music Baby ships as `pcm`, Creep as `sco`. It picks the hyphenation a
> word is cut with and it is what a reader is told the song is, so a
> wrong one is not cosmetic.

**line 2093** — before `writers = "".join(`

> A credit is a name, not a lyric, and one of them arrived with a
> zero-width space in front of it -- which is invisible in the tag and
> not invisible at all to anything matching the name.


---

## Earlier lift — 2026-08-23

Comments lifted out of `mild-lyrics/spicy_lyrics.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 78** — before `sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]`

> spotify_dom.py may sit next to this file or one level up -- offer both, or the
> import below fails depending on where the scripts were dropped.

**line 88** — before `# --------------------------------------------------------------------------`

> current track id, straight off D-Bus (no CDP needed)

**line 109** — before `# --------------------------------------------------------------------------`

> JS payloads

**line 228** — before `# --------------------------------------------------------------------------`

> player clock (D-Bus, no CDP round-trips)

**line 257** — before `HYPHENS = "-\u2011\u2013"`

> Written boundaries: a hyphen, a non-breaking hyphen, an en dash.

**line 259** — before `DIGRAPHS = ("th", "ch", "sh", "ph", "wh", "gh", "ck", "qu")`

> Only true digraphs -- one sound, never split. Ordinary onset clusters (st, tr,
> bl...) must stay splittable or VCCV words break: ques-tion, not que-stion.


### `syllabify`

**line 273** — before `if len(word) > 1 and any(h in word[:-1] for h in HYPHENS):`

> A hyphen already IS a syllable boundary -- somebody wrote it there --
> and it belongs to the piece before it: "Ten-time" is sung "Ten-" then
> "time", never "Ten" then "-time". Split on it first and syllabify each
> part on its own, so the rule below never has to reason about a word with
> two halves in it.

**line 293** — before `if pieces:`

> the chunk was a bare hyphen; it rides on whatever is there

**line 301** — before `while len(pieces) > 1 and all(c in HYPHENS for c in pieces[0]):`

> ...and a leading bare hyphen has nothing before it to ride on

**line 334** — before `final_le = (`

> word-final consonant + "le" is a syllable of its own (lit-tle, im-pos-si-ble)

**line 338** — before `silent = -1`

> otherwise a trailing silent 'e' is not its own syllable -- and it stays
> silent with an inflection stuck on it: saved, named, missed, Tides.
> Those came back "sa-ved", "na-med", "mis-sed", "Ti-des", which is a
> second syllable nobody sings.
>
> It is only silent where English actually swallows it. After t or d the
> -ed IS a syllable (wan-ted, nee-ded), and after a sibilant so is the -es
> (wish-es, ra-ces, pa-ges) -- hence the two exception sets.

**line 362** — before `units, at = [], end_v + 1`

> Count the consonants between two vowels in UNITS, where a digraph
> is one unit -- "ch" is a single sound and cannot be cut through.
>
> Doing it this way, rather than counting letters and then shoving the
> cut off a digraph, is what tells "tea-cher" from "wach-ten". Both
> contain "ch"; in the first it is the entire cluster, so it opens the
> next syllable, and in the second a "t" follows it, so the "ch" closes
> this one. The old code moved the cut LEFT whenever it landed inside a
> digraph, which gave "wa-chten" -- an onset no language has.

**line 379** — on `            cut = units[0]`

> one consonant: it opens the next syllable

**line 385** — before `cuts = [c for c in cuts if c < n - 3] + [n - 3]`

> the last syllable is consonant + "le", so cut before that consonant

**line 393** — before `out: list[str] = []`

> a piece with no vowel is not a syllable -- fold it into its neighbour


### module level

**line 447** — before `CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")`

> kana, radicals/compat forms, ext-A, unified

**line 464** — on `SOKUON = re.compile(r"[っッ]\s*$")`

> small tsu, っ / ッ

**line 491** — before `PARTICLES = {"は": "wa", "へ": "e", "を": "o"}`

> Standalone particles are written one way and read another. Romanising them
> per-character gives "watashi ha" / "kimi wo", which is simply wrong.

**line 512** — before `TRAILING_KANA = "っゃゅょぁぃぅぇぉゎーッャュョァィゥェォヮ"`

> kana that never begin a mora: they lean on the character before them


### `line_readings`

**line 542** — on `    owner = [-1] * len(texts)`

> which romaniser word each syllable fell in

**line 583** — before `if stripped in PARTICLES and (i or stripped != "は"):`

> a syllable that is nothing but は/へ/を is the particle, not the kana


### `furigana`

**line 645** — before `touched = [i for i, (x, y) in enumerate(spans) if x < hi and y > lo]`

> A reading can straddle two timed pieces, since the syllable split and
> the word split are different things. Divide it by character share
> rather than dropping it or hanging it off one side.


### `geminate`

**line 686** — on `        return None`

> gemination before a vowel is not a thing

**line 689** — on `        head = head[1:]`

> already doubled on the far side


### module level

**line 695** — before `BG_LEAD = 0.4`

> How far ahead of its line a backing vocal must start before it is read as
> leading the line rather than opening with it.
>
> Not any amount: a backing vocal sung WITH the line is routinely stamped a
> hair early. On "No More Sorrow" the ad-libs lead by 0.01-0.02s, which is
> jitter, and lifting those above the line they answer just scattered it. The
> same track's genuine early entries lead by ~3.3s, so there is a lot of room
> between the two. Of the 416 early backing vocals in a 2323-song library, 288
> clear this and 128 are the near-simultaneous kind.


### `timeline.syls_of`

**line 721** — before `_trim(y.get(key) or y.get("Text", "")),`

> some syllables carry an empty romanisation; showing the
> original there beats rendering a hole in the line
>
> Trimmed at the edges: the layout puts its own gap
> between two pieces that are not part of one word, so
> a piece carrying a trailing space of its own is drawn
> with two. See syllables_text.

**line 733** — before `return s`

> A romanisation is already one token per sung syllable; re-splitting
> it would interpolate boundaries inside "sayonara" for no gain.


### `timeline.roman_of`

**line 741** — before `syls = [y for y in (group or {}).get("Syllables") or []`

> must use the SAME filter syls_of does, or the zip below pairs each
> romanisation with the wrong original

**line 745** — before `if not any(CJK.search(y.get("Text", "") or "") for y in syls):`

> A line with no CJK in it is already readable, so it gets no second
> row -- some sources hand back a "transliteration" for the English
> lines of a mixed song that is just the English again.

**line 750** — before `if not any(y.get("TransliteratedText") for y in syls):`

> Some tracks flag transliterations at the top but leave whole lines
> without one. Derive those rather than showing a blank under every
> other romanised line.

**line 757** — before `texts = [y.get("Text", "") or "" for y in syls]`

> derived readings come from the whole line at once, for the context

**line 766** — before `broken = {owner[i] for i, y in enumerate(syls) if failed(y) and owner[i] >= 0}`

> If any syllable of a word needs deriving, derive the whole word. Mixing
> a derived "shi" for 沈 with the source's "mu" for む spells "shi mu";
> taking both halves of the derived reading spells "shizumu".

**line 773** — before `if failed(y) or owner[i] in broken:`

> The source is kept wherever it holds up -- it is community-curated
> and handles the invented readings lyrics are full of, which nothing
> can infer from the text.

**line 779** — before `for i in range(len(rows) - 1):`

> Syllables that fall inside one romaniser word are one word on screen:
> "shizu" + "mu" reads as "shizumu", and 諦めの悪い輩 reads "taime no
> warui tomogara" rather than "tai me no waru i tomogara".
>
> It takes BOTH signals to agree. The romaniser alone lumps a whole kana
> run into one segment, which glued "sayonara dake datta" into a blob;
> IsPartOfWord alone is Japanese orthography, which happily runs a
> entire phrase together because the script has no spaces. Where the
> word segmentation and the source's own word flag say the same thing,
> the join is safe.

**line 793** — before `for i in range(len(rows) - 1):`

> っ geminates onto the next syllable, so those two do join

**line 800** — before `return [tuple(r) for r in rows]`

> Note every token is spaced (part=False) except those joins: IsPartOfWord
> encodes Japanese orthography, which is right for かな but would glue the
> romanisation into "sayonaradakedatsuta".


### `timeline`

**line 819** — on `        here = len(out)`

> where this line's own row begins

**line 827** — before `"text_roman": roman_text(lead, item),`

> line-level lyrics carry the romanisation on the item, not on a
> Lead group -- passing `lead` twice never looked there

**line 834** — before `bg = item.get("Background")`

> Backing vocals are a concurrent voice with their own timings, not part
> of the lead line -- emit them as separate entries so they overlap it.

**line 837** — before `lead_syls = [y.get("StartTime") for y in (lead or {}).get("Syllables") or []`

> When the lead is actually SUNG, not when its group nominally opens.
> Lead.StartTime is padded ahead of the first syllable, and comparing
> against it found no early ad-libs at all in the whole cache -- while
> 416 backing vocals do come in before the lead's first syllable, which
> is the moment a listener hears the line begin.

**line 854** — before `at = len(out)`

> An ad-lib that comes in BEFORE the line it belongs to should be
> read before it, not under it. Anything starting at or after the
> lead stays below, which is the common case (an answering vocal).

**line 861** — on `                here += 1`

> the lead has moved down a row

**line 878** — before `return synced`

> Deliberately NOT sorted by start. The source lists lines in reading order,
> and sorting broke that wherever two voices overlap: a backing vocal whose
> own StartTime falls after the NEXT lead line's got lifted away from the
> line it answers and dropped a row lower ("critics I turn to" / "Crickets"
> landing under the following line), and an ad-lib that comes in a beat
> before the lead it sits under jumped above it. Across the whole local
> cache that hit 64 of 1988 songs; only one had source order genuinely
> wrong, and that one has stale timestamps no ordering can rescue.


### `focus_index`

**line 935** — on `    while moved:`

> walk out to the outermost container


### module level

**line 975** — before `# --------------------------------------------------------------------------`

> formatting


### `syllables_text`

**line 1019** — before `out += text if s.get("IsPartOfWord") else _trim(text) + " "`

> Both edges: a leading space doubles the gap just as a trailing one
> does, and the piece before it has already ended its word.


### `line_text`

**line 1042** — before `text = (text + " " + " ".join(f"({p})" for p in parts)).strip()`

> One pair of brackets per GROUP, not one pair around all of them.
> Two answering voices written apart -- "(Baow) (What the fuck are
> you doing, Toxi?)" -- came back as "(Baow What the fuck are you
> doing, Toxi?)", which is every word in the wrong shape and reads
> as one long ad-lib rather than two short ones.


### `syllable_group`

**line 1073** — before `out.append(tag + s.get("Text", "") + ("" if s.get("IsPartOfWord") else " "))`

> IsPartOfWord means "joins the next syllable with no space"


### `elrc_line`

**line 1088** — on `        body = line_text(item)`

> Line/Static types carry no syllable data


### `_covering`

**line 1155** — before `own = e`

> What the line sings on its own, before any ad-lib widens it. The clamp
> below may not cut into this.

**line 1170** — before `floor = own if isinstance(own, (int, float)) else None`

> ...but not so far that two lines are lit at once.
>
> Widening a line to hold its ad-libs and stopping there traded one visible
> fault for another: containment went perfect and a quarter of the lines
> began overlapping the next, which is the fault a reader actually notices.
> So the line reaches as far as it must and no further than the next line's
> start. What is being cut is an ad-lib's END, which was mostly the hold
> rather than a measurement -- and a line that has to be truncated here is
> really telling you its ad-lib is mistimed, which is a different bug.
>
> ONLY the ad-lib's end. That is what this always said it did, and not
> what it did: `e` is the widened end, and where nothing had widened it,
> the line's own singing was cut instead. A duet answering before the
> other singer has finished -- two voices overlapping on purpose, which
> is the whole point of two agents -- came out of a save with its <p>
> ending where the answer began, and the rest of the line outside the
> element that carries it. Hence `own`: the clamp may take back the hold
> an ad-lib added and no more.


### `render_ttml`

**line 1239** — on `        nxt = items[n] if n < len(items) else None`

> n is 1-based


### `render`

**line 1300** — before `return render_ttml(body, True)`

> x-bg is how TTML natively carries backing vocals -- always emit them,
> unlike the text/lrc formats where they are an opt-in inline annotation.

**line 1304** — before `items = next(`

> synced types (Syllable/Line) use "Content"; unsynced "Static" uses "Lines"


### `main`

**line 1448** — on `                pos -= a.offset`

> positive offset shows lines later

**line 1457** — before `head += "(not cached yet -- waiting)"`

> Spicy Lyrics writes the cache only after it fetches a
> song, so a just-started track is often not there yet.
> Keep re-checking instead of going silent for the song.

**line 1506** — before `while region and region[0] not in cur:`

> live region = every currently-sounding line, redrawn in place.
> Lines that stop sounding drop out of the region and stay on
> screen above it as history.
