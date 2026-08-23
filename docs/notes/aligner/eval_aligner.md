# `aligner/eval_aligner.py`

Comments lifted out of `aligner/eval_aligner.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `reference`

**line 68** — before `word, at = "", None`

> Syllables of one word are glued back together: this aligner and
> whoever made the reference do not divide words the same way, and a
> word is the largest unit both of them agree exists.


## `shape`

**line 123** — before `order = ([e for _t, e in sorted(zip(times, errs))] if times and`

> By position in the song if we have times, by order otherwise: both answer
> "does the error move as the song goes on", which is the question.
