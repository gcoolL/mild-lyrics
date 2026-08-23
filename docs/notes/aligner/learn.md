# `aligner/learn.py`

Comments lifted out of `aligner/learn.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 37** — before `ROOT = HERE.parent`

> Data lives beside the code's folder, not inside it.


## `main`

**line 124** — before `if not spotify_is_up():`

> Both remaining stages need Spotify: the lyrics come out of its cache and
> the track lengths out of its API. Failing here is much kinder than
> failing in twenty minutes with half a dataset.

**line 146** — before `env_steps = ["--steps", str(args.steps)] if args.steps != 3000 else []`

> run_pipeline does stages 2-5 in one process on purpose: the model it
> trains has to be in memory to be measured, and writing it to disk and
> reading it back was one more thing that could quietly differ.
