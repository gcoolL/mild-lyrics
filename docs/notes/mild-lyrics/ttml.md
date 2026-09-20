# `mild-lyrics/ttml.py`

Comments lifted out of `mild-lyrics/ttml.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 39** — before `ROOT = HERE.parent`

> Data lives beside the code's folder, not inside it.


## `index`

**line 103** — before `if n % 25 == 0 or n == len(fresh):`

> Written as it goes, not at the end: the first run asks Spotify
> about six hundred songs one at a time, and losing all of it to an
> interrupted run means starting from nothing every time.


## `look_up`

**line 141** — before `return best if score >= max(1, len(want) - 1) else None`

> Every word but one has to land, so "wordle freestyle" is not answered
> with some other freestyle.


## `decoys`

**line 170** — before `import random`

> Sampled, not the first few: the cache is in the order songs were played,
> so taking the front of it can hand back six songs by the same artist --
> a floor made of the very vocabulary being tested for.


## `main`

**line 238** — before `if args.url and tid:`

> A copy named on the command line is believed and remembered: the search
> matches on title and length, and a different recording of the right
> length is exactly the failure it cannot see.
