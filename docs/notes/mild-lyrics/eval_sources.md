# `mild-lyrics/eval_sources.py`

Comments lifted out of `mild-lyrics/eval_sources.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `settings`

**line 74** — before `got = LS.provider_order(order, lambda n: n in live,`

> Sources in, providers out -- the walk is asked in the same terms the
> player asks it in, or this measures a chain nobody is running. The
> blends carry their own switches, so they are read too.


## `drawn`

**line 101** — before `fold = fold and LS.needs_adlibs(dict(doc, _source=who))`

> Only the documents whose ad-libs are still in their lyric, exactly as
> the player decides it -- and the name has to be put on the document
> first, because that is what the player is holding by the time it asks.


## module level

**line 198** — before `# --------------------------------------------------------------------------`

> what the donors are actually doing

**line 200** — before `TILED = 0.002`

> Two milliseconds. Every one of these sources writes its stamps to the
> millisecond, so anything at this distance was written as the same number.

**line 203** — before `AGREE = 0.070`

> Seventy, because that is the figure from_kublend already quotes for QQ and
> Kugou agreeing "syllable for syllable" -- reused so the two claims can be
> read against each other.


## `filler_lines`

**line 371** — before `if key and b.get(key) and not a.get(key, False):`

> Not in the two-way at all counts too: either way the filler is
> speaking for a line the first donor did not.


## `donors_report`

**line 430** — before `body = spicy(cdp, tid)`

> H5 needs a reference and both three-way shapes of the same song.
> Spicy Lyrics' own copy goes in as `local` either way, because that
> is what the player hands a blend -- and where it is also the
> reference, the words on both sides are the same words, which leaves
> the clock as the only thing being measured.

**line 442** — before `two = alone(tid, meta, "neblend", None, fold)`

> Not `body`. A blend keeps the base's own word timings where the
> relay fails, so building on the community sync leaves no holes to
> find -- the base already timed every line. Apple's own document is
> both the honest base here and the one a blend really gets, since a
> blend only reaches the screen where Spicy Lyrics has no word sync.

**line 456** — before `"pairs": {f"{x}-{y}": acc for (x, y), acc in pairs.items()},`

> Written out with a string key, so the whole report is one
> json.dump away -- a tuple key is not a thing JSON has.


## `main`

**line 591** — before `key = f"{LS._norm(meta['title'])}\x00{LS._norm(meta['artist'])}"`

> The reference first, so a song without one is not fetched at all
> when there would be nothing to say about it.

**line 598** — before `if ref_doc is None:`

> No community sync, nothing to score against, and a walk of ten
> providers is too expensive to spend on a song that could only
> ever contribute a coverage number. --against refs is the mode
> that measures everything.

**line 606** — before `if only:`

> Head to head, or whatever the running order settles on. Either way
> one line per document measured, so the two read the same.

**line 609** — before `base = None if args.against == "spicy" else body`

> Not `body`, where `body` is also the reference. A blend lays a
> donor's timings over a base and keeps the base's own where the
> relay fails (see _blend), so handing it the very document it is
> about to be scored against lets it copy the answer: Apple+QQ
> came back "median +0.000s scatter 0.000s" on two songs here,
> which is not a good blend, it is no blend at all.
>
> Nothing is lost by withholding it. A blend only ever reaches
> the screen on a song Spicy Lyrics has NOT word-synced, which is
> exactly the case this now measures.
