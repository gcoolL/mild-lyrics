# `mild-lyrics/lyric_formats.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/lyric_formats.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Lyric file formats other than TTML: written by the TTML Editor's Save menu,
> read by the player when one is dropped on its window and by the editor's Open.
>
> Everything here speaks the document both programs already pass between them
> -- the Spicy Lyrics shape, a "Content" list of items with a Lead group of
> Syllables and any Background groups -- so a format is one writer and one
> reader, and neither program needs to know the formats exist.
>
>     format   timing      backing vocals              duets
>     LRC      line        inline, in brackets         --
>     ELRC     word (A2)   inline, in brackets         --
>     SRT      line        inline, in brackets         --
>     ASS      word (\k)   a Dialogue of their own     the Name field, v1/v2
>     KRC      word        inline, in brackets         --
>     QRC      word        inline, in brackets         --
>     YRC      word        inline, in brackets         --
>     LYS      word        a line of their own         the line's property
>     TXT      none        inline, in brackets         --
>
> "Inline, in brackets" is how those formats' own apps write a backing vocal,
> and how every reader here (and the KRC/QRC/YRC sources in lyric_sources)
> lifts one back out: see lyric_sources._ne_bg. Where a format has a place of
> its own for one, the brackets are a choice -- `parens` -- as they are for
> TTML, whose reader peels Apple's "(For" ... "you)" back off (_unwrap).
>
> A line with no times at all has nowhere to go in a format that is nothing
> but times; writers leave those out and say how many.

### `_tokens`

**line 69** — from the docstring, `def _tokens(group, text: str = "", at=(None, None)):`

> A voice as (text, start, end) pieces, the space after a word kept on
> it; or None where it has no times at all.
>
> One piece per syllable where every syllable is timed; one for the whole
> voice where only the voice is -- a line-timed document, or a line part
> way through being timed. A syllable is never given a time it was not
> given: the voice's span is the only time there is.
