# `mild-lyrics/language.py`

Comments lifted out of `mild-lyrics/language.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 24** — before `ENGLISH = frozenset("""`

> The commonest English function words. Function words are the right thing to
> count: they are what a language repeats regardless of subject matter, and a
> lyric about anything at all is full of them.

**line 37** — before `NEAR_ENGLISH = frozenset({"sco", "pcm", "jam", "gd", "ga", "cy", "af", "fy",`

> Codes that are English by another name, or so close to it that a lyric in
> plain English is regularly filed under them. These are the ones worth
> overruling; a genuine Scots or Pidgin lyric does not read as English here.


## `english_share`

**line 74** — on `        return 0.0`

> too little to say anything about


## module level

**line 78** — before `ENGLISH_AT = 0.20`

> Below this a lyric is not English. Measured against the files in this
> repo: English ones sit well above it and the non-English ones well below,
> with nothing in between -- see tests/test_editor.py.


## `check`

**line 99** — before `return want, ""`

> `want` unchanged, never `want or "en"`. A file that claims no
> language is not claiming the wrong one, and inventing a code
> for it would put a guess into a field that was honestly empty.

**line 107** — before `if short == "en" and script not in ("latin", ""):`

> A claim of English over a script English is not written in.
