# `mild-lyrics/sweep.py`

Comments lifted out of `mild-lyrics/sweep.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 26** — before `ROOT = HERE.parent`

> Data lives beside the code's folder, not inside it.


## `snap`

**line 60** — before `for word, start, end, *_rest in before:`

> Rows carry a CTC score too, on runs recorded since that was added.


## `main`

**line 122** — before `print("\n  replaying the shipping settings:")`

> Self-check. If replaying the shipping settings does not reproduce what
> was measured on the card, the flux or the word starts were not captured
> faithfully and every number below is fiction.

**line 155** — before `rows.append((min(per), sum(per) / len(per), per, how, len(every)))`

> Ranked on the WORST song, not the pooled average: a setting that
> wins by helping the long song while hurting the short one is not an
> improvement to the aligner, it is an improvement to the average.
