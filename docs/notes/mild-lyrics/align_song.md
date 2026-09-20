# `mild-lyrics/align_song.py`

Comments lifted out of `mild-lyrics/align_song.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `report`

**line 147** — before `espeak = shutil.which("espeak-ng") or shutil.which("espeak")`

> Stage three, all of it optional. Without any of it the words are timed
> as words, which is what this did before syllables existed -- so these
> are notes rather than warnings, and only ever about English.

**line 170** — before `("anchors   ", LA.ASR_COST, LA.ASR_WINDOW, "of song"),`

> Not "at a time". The anchor stage holds the whole song, so what
> the card affords it is a LENGTH OF SONG -- see local_align.ASR_COST.


## `main`

**line 237** — before `saved = L.load_settings()`

> The GUI holds these, as it held the Space and its token before it, so the
> two agree about what this machine is willing to do to itself. A flag on
> the command line still wins.

**line 269** — before `print("no words in that document to align")`

> Said here rather than blamed on the aligner. align() returns None for
> several unrelated reasons and the first version reported all of them
> as "no answer", which pointed at the network for a document that had
> simply been read wrongly.

**line 307** — before `with LA.fetched(query, m["length"] or 0.0,`

> The copy exists only inside this block. Whatever happens in it --
> a refusal, a timeout, Ctrl+C -- the file is gone on the way out.

**line 322** — before `LA.release()`

> The weights outlive the stage that wanted them, which is right for
> the player and wasteful for one run of this. Dropped here rather than
> inside align(), because whether a second song is coming is the
> caller's question and not the aligner's.

**line 338** — before `spoke = int(SL.payload(out).get("_heard_only") or 0)`

> The rest are not necessarily dark. A line the aligner could not place but
> the speech model heard is line-timed, which lights on cue without its
> words lighting one by one -- worth distinguishing from a line with no
> timing at all, and the two used to be reported as one number.

**line 349** — before `name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_",`

> Written as TTML, named the way the S key names its files, so an aligned
> song lands beside the rest and can be opened, diffed or re-read by
> anything that already understands them. The JSON goes alongside it only
> because it is what the player's own loader reads back.
