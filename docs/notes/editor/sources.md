# `editor/sources.py`

Comments lifted out of `editor/sources.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 129** — before `_apple_token = LS._apple_token`

> Apple's catalogue API, borrowed whole from the chain: it needs a developer
> token scraped out of the web player's own JavaScript, and lyric_sources
> already gets one there to look up the ISRC BiniLyrics files by. Two copies
> of that meant two token files, two scrapes of a three-megabyte bundle, and
> two chances to drift apart on how the token is checked.

**line 169** — before `WROTE_IT = ("composition", "lyrics", "writing")`

> What Apple calls the part of the credits that is the SONG rather than the
> recording. Everything under it wrote the thing; everything else played it,
> produced it or engineered it.


## `apple_credits`

**line 221** — before `writer = (any(any(w in r for w in WROTE) for r in roles)`

> By the ROLE, not by the heading it is filed under: the
> composition section also holds arrangers and the band name,
> and neither wrote the song. The heading is only consulted
> when Apple lists no role at all.


## module level

**line 239** — before `_split_names = LS.apple_names`

> One credit line as the people in it. The chain cuts Apple's credits apart
> for the same reason and on the same three separators, so it is read from
> there rather than written twice -- two spellings of "who counts as a name"
> would put different <songwriter> tags in a file depending on which button
> filled them in.


## `chain_doc`

**line 355** — before `try:`

> Not where one source was asked for BY NAME. The roster is about what
> gets played, and this window is where a sync gets fixed: naming the
> source is asking to see what it has, and a refusal that answered
> "nothing found" to a question that specific would read as the door
> being down.

**line 365** — before `raise RuntimeError(f"{', '.join(want) or 'the chain'}: "`

> Not swallowed. A chain that threw and a chain that found nothing
> both came back as "nothing found", so the one fault worth knowing
> about -- a provider erroring, a missing key, no network -- was
> indistinguishable from a song simply not being in any database.
> The window runs this on a worker that turns a raising job into a
> message, which is where this belongs.


## `detect_roles`

**line 455** — before `counts = [len(M.words_in(text)) for text, _ in want]`

> words_in, not split(). The document's words are cut with words_in,
> which keeps French's spaced punctuation on its word -- "Pourquoi ?"
> is ONE word there and two to split(). The counts then disagreed,
> the line was skipped, and "Find ad-libs" silently did nothing on
> every line with a ? ! : ; or « » in it.


## `fetch_audio`

**line 559** — before `kept = LA._kept(key)`

> Kept before the `with` closes, because that is what deletes it.


---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/sources.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 46** — before `# --------------------------------------------------------------------------`

> Genius: the words, and who sings them


### `genius_doc`

**line 94** — before `ln.lead, ln.bg = ln.bg[0], ln.bg[1:]`

> A line that is nothing but an ad-lib is a backing LINE. Left as
> a lead with no words it would render as an empty <p>.


### module level

**line 131** — before `# --------------------------------------------------------------------------`

> Apple Music: songwriters, through the web player's own key


### `apple_songwriters`

**line 221** — before `if want_t and want_t not in L._akey(at.get("name") or ""):`

> Apple's search is generous in the same way Genius' is; a cover or a
> karaoke version credits different people, so the hit has to look
> like the song that was asked for.


### module level

**line 262** — before `# --------------------------------------------------------------------------`

> the player's own chain

**line 367** — before `# --------------------------------------------------------------------------`

> roles, for documents that arrive without them


### `detect_roles`

**line 390** — before `want = ([(b, True) for b in head] + [(lead, None)]`

> One group per bracketed run, not one group per END. "(ooh) (aah)"
> is two answering voices and a player draws them as two rows; run
> together they came out as a single group spelling "ooh) (aah".

**line 397** — on `            continue`

> the words do not add up; leave it be
