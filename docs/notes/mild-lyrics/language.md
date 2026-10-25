# `mild-lyrics/language.py`

Comments lifted out of `mild-lyrics/language.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/language.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> What language a lyric is actually in, when the file's own answer is wrong.
>
> Every provider stamps a language code on its documents and a good share of
> them are guesses made by a machine on a few hundred words. The failure mode
> is specific and it is always the same shape: an English lyric comes back as
> some other Latin-script language with a small corpus behind it -- `pcm`
> (Nigerian Pidgin), `sco` (Scots), `nl`, `af`. Music Baby arrives as `pcm`.
>
> That code is not decoration. It goes into the file as `xml:lang`, it picks
> the hyphenation patterns a word is cut into syllables with, and it is what a
> reader is told the song is. A wrong one is wrong three times over.
>
> So the claim is CHECKED rather than trusted, and only overruled when the text
> disagrees with it clearly. The test is deliberately blunt -- script first,
> then how much of the text is made of English function words -- because a
> subtle detector that is right nine times in ten would introduce a new way to
> be wrong for songs whose code was fine all along.

### `check`

**line 62** — from the docstring, `def check(claimed: str, text: str) -> tuple[str, str]:`

> The language to use, and why -- `claimed` unless the text says otherwise.
>
> Returns (code, reason). The reason is empty when the claim stands, and a
> sentence worth showing when it does not: a code being quietly rewritten
> is exactly as unhelpful as a code being quietly wrong.
>
> Remembered for the last few texts: the info panel asks about the same
> lyric on every frame it is open, and each answer is a pass over every
> character of it -- about a millisecond for a song.

### `is_rtl`

**line 101** — from the docstring, `def is_rtl(text: str) -> bool:`

> Whether a line reads right to left.
>
> Counted rather than taken from the first strong character: a song like
> C'est la vie puts French and Arabic in the same line, and one borrowed
> word should not turn the line round. More right-to-left letters (Arabic,
> Hebrew, Syriac, Thaana, N'Ko) than left-to-right ones, and it is RTL.

### `joins`

**line 141** — from the docstring, `def joins(a: str, b: str) -> bool:`

> Whether the end of syllable `a` is written joined to the start of `b`.
>
> A word sung in several syllables is drawn as several texts, and Arabic
> letters take a different form in the middle of a word from the one they
> take alone. Drawn apart, كلمة in three syllables would read as three
> unconnected pieces. Where this says they join, each side is given a ZWJ
> so the shaper picks the connected forms.

---

## Lift — 2026-09-26

Comments lifted out of `mild-lyrics/language.py` on 2026-09-26; the line numbers are that day's.

### module level

**line 127** — before `_RIGHT_JOINING = set("ءآأؤإاةدذ"`

> Arabic letters that join to the letter before them but never to the one
> after: a syllable ending in one of these starts the next syllable afresh.


---

## Lift — 2026-09-17

### module level

**line 24** — before `ENGLISH = frozenset("""`

> The commonest English function words. Function words are the right thing to
> count: they are what a language repeats regardless of subject matter, and a
> lyric about anything at all is full of them.

**line 37** — before `NEAR_ENGLISH = frozenset({"sco", "pcm", "jam", "gd", "ga", "cy", "af", "fy",`

> Codes that are English by another name, or so close to it that a lyric in
> plain English is regularly filed under them. These are the ones worth
> overruling; a genuine Scots or Pidgin lyric does not read as English here.


### `english_share`

**line 74** — on `        return 0.0`

> too little to say anything about


### module level

**line 78** — before `ENGLISH_AT = 0.20`

> Below this a lyric is not English. Measured against the files in this
> repo: English ones sit well above it and the non-English ones well below,
> with nothing in between -- see tests/test_editor.py.


### `check`

**line 99** — before `return want, ""`

> `want` unchanged, never `want or "en"`. A file that claims no
> language is not claiming the wrong one, and inventing a code
> for it would put a guess into a field that was honestly empty.

**line 107** — before `if short == "en" and script not in ("latin", ""):`

> A claim of English over a script English is not written in.
