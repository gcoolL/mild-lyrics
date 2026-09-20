# `mild-lyrics/bench.py`

Comments lifted out of `mild-lyrics/bench.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 48** — before `ROOT = HERE.parent`

> Data lives beside the code's folder, not inside it.


## `measure`

**line 99** — before `refdoc = cached(cdp, tid)`

> The same again per syllable, which is the unit the display moves on,
> and again for the ad-libs, which nothing had ever looked at.

**line 106** — before `pairs = paired(mine, ref)`

> Kept alongside the numbers: which words missed is the whole question, and
> re-running an alignment to find out costs a minute.

**line 120** — before `(OUT / f"{T.safe(name)}.{tag}.ttml").write_text(`

> The document itself, beside its own numbers. A share of words inside
> 0.1s does not tell you what a song FEELS like, and the fastest way to
> find out what a run actually did is to put the file on and watch it --
> which is how the ad-libs were caught, and how the 0.2s tail was.

**line 127** — before `flux = getattr(LA._onsets, "flux", None)`

> The raw material for sweep.py: everything the onset stage decided FROM,
> so a hundred settings can be tried without a hundred alignments.


## `every_referenced`

**line 314** — before `doc = cached(cdp, tid)`

> Community uploads only, matching build_dataset: the cache also holds
> Apple Music's own word-synced lyrics under source `aml`, and for a
> while nothing here told the two apart.


## `main`

**line 389** — before `how["decoys"] = T.decoys(cdp)`

> Fetched once, not per song: without a floor of unrelated songs to
> compare against, "the model heard 40% of the words" is a number with
> no scale on it, and a heavily produced song scores like a wrong one.

**line 407** — before `print(f"  {song}: {type(exc).__name__}: {exc}")`

> One bad song must not cost the other twenty-nine: this runs
> unattended for an hour or more.
