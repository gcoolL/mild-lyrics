# `editor/syllables.py`

Comments lifted out of `editor/syllables.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## 2026-10-16 — Split after hyphens

On by default: "brand-new car" -> brand-|new car without the whole
syllable split. `hyphen_cut` cuts after a hyphen with a letter or digit on
both sides (so "-ing" and "Off-" stay whole); `ops.cut_hyphens` applies it to
UNTIMED whole words only, where text comes in: typing (when Split words as I
type is off -- on, the syllable rule already cuts at hyphens), the import
page, a .txt, Edit as text and a rewritten line. Setting `split_hyphens`.
Test: `test_hyphen_cut.py`.

## 2026-10-15 — `_segment_marks` with Sudachi

Cuts (where vowels may not join) come from the word-level segments, and the last kana of each kanji's reading from the finest ones -- Sudachi's words are long, and only the LAST kanji of 吸い取って was read, so 吸|い split. A segment that is one bare vowel (どうだ|い, ざま|あ) does not cut: it draws the word out. Without Sudachi this changed 10 of 782 lines, all to fewer pieces where they belong (見|たい, 得|ない, 踊|ろう).

## 2026-10-14 — いっそ, お似合い

pykakasi leaves long hiragana runs as one segment (てないならいっそ), so `_ja_syllables` joined ら+い in ならいっそ (な|らいっ|そ) and と+お in きっとお似合い. A vowel followed by っ opens its own syllable, and お before a kanji is a prefix, not a long vowel: な|ら|いっ|そ, きっ|と|お|似|合い. 思|い|出 is still cut so (as it was before).

## Lift — 2026-10-25

Docstrings shortened in `editor/syllables.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Cutting a word into the pieces a singer sings it in.
>
> Two ways, because they disagree and the disagreement is the point.
>
> `sung` is this project's own rule, the one the player already spells words
> with: a vowel group per syllable, and a single consonant between two of them
> opens the NEXT one -- ne-ver, wai-tin', ti-ckin' -- because that is where a
> singer puts it. Digraphs count as one sound and are never cut through, which
> is what tells tea-cher from wach-ten.
>
> `hyphen` is Liang hyphenation, the TeX patterns, through pyphen -- the same
> thing the AMLL tool uses for its automatic English split (it loads
> `hyphen/en-us`, the same pattern set). It knows far more words than any rule
> can, and it is answering a different question: where may a TYPESETTER break
> this word at the end of a line. Print refuses breaks that leave one or two
> letters stranded and prefers morphological seams, so it gives nev-er, want-ed,
> wait-in', and refuses to break "against" or "gonna" at all.
>
> Measured against the syllable splits already in this folder's TTMLs -- 431
> words that a person cut (or deliberately did not cut) the same way every time
> they appear, across five songs including a hand-timed Love Blur:
>
>                       exact agreement    cut a word         refused a cut
>                         with the hand    left whole         made by hand
>       sung                      86%      41 of 349          7 of 82
>       hyphen (pyphen)           78%      41 of 349         28 of 82
>
> Read that "cut a word left whole" column carefully: it counts every word the
> person timed as one piece and the rule would divide -- Away, listen, Forever
> -- and those are genuinely two and three syllables. Timing a word whole is a
> choice, not a claim that it has one syllable, and no measurement here can
> tell the two apart. The automatic split shows every cut it proposes before it
> makes any of them, and a word can be pinned whole for good.
>
> They fail differently, which matters more than the totals. `sung` errs by
> cutting -- and most of what it "gets wrong" are words like Candy, Listen and
> atmosphere that are genuinely polysyllabic and were simply timed as one
> piece, which is a choice rather than a mistake. `hyphen` errs by refusing:
> "against", "gonna" and "singin'" it will not break at all, because print does
> not break them.
>
> Two faults in the sung rule turned up in that measurement and are fixed in
> spicy_lyrics.syllabify rather than worked around here: punctuation defeated
> the silent-e test ("Home," came back "Ho-me,"), and a silent e stayed silent
> under an inflection nobody sings ("saved" was "sa-ved"). That took it from
> 79% to 90%, and the player's own word-splitting gets the same repair.
>
> Hyphenation is still the better answer for a language whose rules this
> project has never encoded -- pyphen ships patterns for eighty-odd of them,
> and on Dutch the two agree almost everywhere (wach-ten, let-ter-gre-pen),
> disagreeing only where each is characteristically wrong: hyphenation will not
> strand the "o" of o-gen-blik, and the sung rule will not cut meis-je.
>
> A piece holding more than one word is cut at the words first and then by the
> rule, so "do your" and "let 'em" come apart -- they were being refused
> outright, which left a line of them with nothing to split at all. The
> separator rides on the piece before it, so the pieces still spell what went
> in; what it MEANS is read back when the syllables are built (a space is a
> word boundary and goes, a zero-width one is a boundary drawn without a gap
> and stays).
>
> Punctuation around a word is not part of it in either rule, nor in the store
> of kept corrections: it is peeled off before the spelling is read and put
> back on the pieces it came off, so "fallin'", "fallin'," and "fallin'!" are
> one word asked about once and answered once. Where that peel is exactly is
> spicy_lyrics.peel, which the player's own splitting uses for the same reason.
> It was worth doing: the store had grown a second entry for "alkmaar," beside
> "alkmaar" and a third for "boyfriend?", each of them the same decision typed
> again because the first one could not be found.
>
> Whatever the method, the pieces ALWAYS rejoin to exactly the word that went
> in. That is not a nicety: a split that loses an apostrophe or a comma changes
> the lyric, and the lyric is the one thing an editor may never quietly edit.

### `bare_pieces`

**line 103** — from the docstring, `def bare_pieces(word: str, pieces: list[str]) -> list[str] | None:`

> `pieces` re-cut as a split of `word` without the punctuation around it.
>
> A correction is a decision about the WORD, and a comma is not part of the
> word -- so it is stored, looked up and applied with the punctuation off.
> A cut that fell inside the punctuation is dropped rather than kept: there
> is nothing there to cut.

### `_kept`

**line 218** — from the docstring, `def _kept() -> dict:`

> Every kept correction, filed by the bare word.
>
> Corrections kept before this was filed by the bare word are folded in on
> the way past -- "alkmaar," carries the same decision as "alkmaar" and
> always did -- and the fold is written back the next time anything is
> remembered or forgotten, so the store settles into one entry per word
> instead of one per word per closing mark.
>
> Rebuilt only when the store changed, which `keys.config` says by handing
> back the same object -- it was rebuilt for every word of a document, 1.5ms
> at 500 kept and 5.5 at 3000. The dict is the caller's to change; the lists
> in it are shared, so they are not.

### `also_right`

**line 238** — from the docstring, `def also_right() -> dict:`

> The other arrangements kept as right for a word, filed by the bare word.
>
> A word can be sung more than one way -- "battlin'" is bat|tlin' or
> bat|t|lin' depending on the singer -- and a file cut either way is cut
> right. The first arrangement, in `overrides`, is still the one the rule
> hands out; these are only ones a review should not raise. Kept apart from
> "splits" so everything that reads that store keeps reading one
> arrangement per word.

### `parse_ways`

**line 307** — from the docstring, `def parse_ways(word: str, text: str) -> tuple[list[list[str]], str]:`

> What somebody typed about how `word` is cut, as arrangements of it.
>
> ([pieces, ...], "") -- or ([], the part that would not do). Pieces are
> marked off with | (or ·), and more than one right way with /, the usual
> one first. A - marks a seam too, in a word that has none of its own.
>
> Typed the way a person types, not the way the word is stored: the case
> need not match ("Lone|lier" for "lonelier"), the punctuation the word is
> wearing in this line may be left off ("lone|lier" for "lonelier,"), and
> the spaces round a / are nobody's business. Every one of those used to be
> turned away with "does not spell", which is how "lone|lier / lone|li|er"
> could not be kept for a "Lonelier" -- the pieces come back spelled as the
> word is, so nothing about the lyric can change.

### `override_for`

**line 427** — from the docstring, `def override_for(word: str, lang: str | None = None) -> list[str] | None:`

> The kept arrangement for this word, re-cased onto it, or None.
>
> Kept for the word itself, so it answers for "fallin'", "fallin'," and
> "fallin'!" alike: the punctuation is set aside, the arrangement is read
> onto what is left, and the marks go back on the pieces they came off.
> The way chosen for this song wins, then your own, then (with `lang`)
> the shared dictionary's.

### `split`

**line 449** — from the docstring, `def split(word: str, method: str = "sung", lang: str = DEFAULT_LANG,`

> `word` in pieces. Always rejoins; never fewer than one piece.
>
> A correction kept for this word wins over every rule -- including the
> correction "leave it alone", which is a kept split of one piece.
>
> `unit` is for the scripts that are not the Latin alphabet (see UNITS):
> "syllable", "mora" or "word". A Latin word is cut by `method` either way.
> `japanese` says a run of kanji alone is Japanese rather than Chinese --
> the document's language, which the characters cannot tell apart.

### `_hyphenate`

**line 955** — from the docstring, `def _hyphenate(word: str, lang: str) -> list[str]:`

> Liang hyphenation, mapped back onto the word as it is written.
>
> The patterns are fed the LETTERS only -- an apostrophe or a trailing
> comma is not part of any pattern and derails them -- and the cuts they
> return are then made in the original string, so every character the word
> had comes back in the piece it belongs to.
>
> The punctuation comes off first, for the same reason it does in the sung
> rule: a hyphen is a seam and a comma is not, so "Bed-," was coming back
> as "Bed-" and a comma standing alone as a syllable of its own.

### module level (comment)

**line 128** — before `_HELD: dict[str, list[list[str]]] = {}`

> Corrections that hold for this session and are never written down: the
> automatic split's "Remember corrections" turned off. A song somebody does
> not want cut all the way through -- a word timed whole on purpose, a name
> sung its own way this once -- still has to be told to the rule, and telling
> it used to mean teaching it for good. {bare word: [arrangement, ...]}, the
> usual one first, exactly the shape the store has.

### module level (comment)

**line 521** — before `SMALL_KANA = set("ぁぃぅぇぉゃゅょゎゕゖァィゥェォャュョヮヵヶㇰㇱㇲㇳㇴㇵㇶㇷㇸㇹㇺㇻㇼㇽㇾㇿー゛゜ゝゞヽヾ"`

> --------------------------------------------------------------------------
> Scripts that are not written in words of the Latin alphabet.
>
> Japanese and Chinese are not spaced into words at all, so a line of either
> comes in as ONE word, and the rule above -- which reads Latin vowels --
> handed it back whole. That was the half of the automatic split that did not
> work: a Japanese line could be timed only as a single block, or cut by hand
> one character at a time.
>
> The pieces here are the ones a singer's timing is made of, and the ones the
> hand-made amll-ttml-db files are cut into: a kana is a mora and a syllable
> of its own; a small kana (ゃ ゅ ょ ぁ ...) and the long mark ー belong to the
> kana in front of them -- きょ is one sound, not two; っ and ん are morae in
> their own right and stand alone; a kanji is one piece; a hangul block is a
> syllable by construction; a hanzi is a syllable by definition. Punctuation
> rides on the piece before it, as it does in the Latin rules, and a Latin
> word inside the run is cut by the Latin rule.
>
> Cyrillic and Greek are alphabets with vowels and get the sung rule's shape
> -- a vowel group per syllable, one consonant opening the next -- with their
> own vowels, which the Latin rule did not know were vowels.

### module level (comment)

**line 628** — before `_VOWEL_ROWS = {`

> --------------------------------------------------------------------------
> Japanese by syllable rather than by mora.
>
> A mora is the beat Japanese is sung on, but it is not a syllable: きょう is
> one syllable (kyō) and two morae, がっこう is gak-kō, せんせい sen-sei. Cut a
> kana at a time, a line came apart into pieces no English singer would hear
> as separate -- ん and っ alone, the second half of every long vowel alone.
> So, over the morae: ん, っ and ー always close the syllable before them (none
> of them can start one), and a bare vowel kana joins a syllable that is still
> a single open mora when the two make a long vowel (aa ii uu ee oo, ou, ei)
> or a diphthong (ai, oi, ui) -- unless it is about to make a long vowel
> with the kana after it, which it keeps for that (か|わ|いい, not か|わい|い).
> The joined syllable is closed; nothing else joins it but ん, っ and ー.
>
> The vowel join is the one that can be wrong, at a word boundary: この|うた
> is not "nou". So it never crosses a pykakasi segment, and a lone particle
> straight after a kanji or katakana word (君は|いつも, 家に|いる) does not
> take the vowel after it. pykakasi does not segment a run of hiragana, so
> inside one the join is a guess, and a kept correction is the way out.

### module level (comment)

**line 779** — before `PARTICLES = {`

> --------------------------------------------------------------------------
> By word, for the scripts a reading is written for.
>
> Japanese is not spaced, and pykakasi's segments are the nearest thing to
> words there is to hand -- but they are cut for READING, not for singing:
> 聞こえる comes back 聞こ + える and 続けたい as 続け + たい, and a particle is a
> segment of its own. So a segment of hiragana is put back on the one before
> it where that one holds kanji or katakana (the verb's ending, the particle
> after a noun), and a particle is put back on whatever it follows: the unit
> is the bunsetsu, 君の / 声が / 聞こえる, which is also where a singer breathes.

---

## Lift — 2026-09-26

Comments lifted out of `editor/syllables.py` on 2026-09-26; the line numbers are that day's.

### `add_also.onto`

**line 259** — before `out, at = [], 0`

> Stored as they were first typed; re-cased onto this spelling.


---

## Lift — 2026-09-17

### `split`

**line 250** — before `if out and is_tail(chunk):`

> French's spaced ? ! : ; » is not a piece of its own, and the
> space in front of it is not a word ending -- _spread reads a
> piece that ends in whitespace as one. Both belong to the word
> already in hand, and « takes the word after it the same way.

**line 257** — before `if (out and out[-1].endswith("\u200b")`

> Nor is the comma in "Away\u200b,". A zero-width space is a word
> boundary drawn without a gap, so what follows one is a chunk of
> its own here -- and a chunk with no word in it, standing after
> a boundary nobody can see, is punctuation on the word in hand
> rather than a word to be timed on its own.


---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/syllables.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 119** — before `# --------------------------------------------------------------------------`

> corrections, kept

**line 121** — before `def overrides() -> dict:`

> No rule gets every word right, and the ones it gets wrong it gets wrong
> every time -- so a correction made once is worth keeping. They are stored
> by the lowercased word, which is why a piece list can be re-cased onto
> whatever the line actually says: "Somethin'" and "somethin'" are the same
> decision, spelled differently.


### `split`

**line 177** — before `if not any(c.isascii() and c.isalpha() for c in word):`

> Nothing here understands a script with no letters in it. CJK is cut by
> the reading, which is spicy_lyrics' job and needs the whole line for
> context -- so it is left alone rather than guessed at.

**line 182** — before `if any(c.isspace() or c == "\u200b" for c in word):`

> A piece holding more than one word is cut at the words first, and each
> of them by the rule. "do your" and "let 'em" are two words apiece and
> nothing was finding them, because this used to refuse any piece with a
> space in it -- which left a line like "It's a vibe, do your dance, let
> 'em watch" with nothing to split at all.
>
> The separator rides on the piece BEFORE it, exactly as a hyphen does,
> so the pieces still spell the word that went in. What the separator
> MEANS -- a word boundary, drawn with a space, or a zero-width one drawn
> without -- is read back off it when the syllables are built.


### `_hyphenate`

**line 229** — before `if len(word) > 1 and any(h in word[:-1] for h in HYPHENS):`

> A written hyphen outranks the patterns and keeps the same rule as the
> sung split: it ends the piece it sits on. Each side is then hyphenated
> by itself, or "tea-cher" comes back "tea-ch-er".

**line 287** — before `return out if joined == word and all(out) else [word]`

> The invariant, checked rather than trusted: any mapping slip hands back
> the word untouched instead of a corrupted lyric.
