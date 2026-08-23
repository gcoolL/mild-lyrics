# `editor/syllables.py`

Comments lifted out of `editor/syllables.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 119** — before `# --------------------------------------------------------------------------`

> corrections, kept

**line 121** — before `def overrides() -> dict:`

> No rule gets every word right, and the ones it gets wrong it gets wrong
> every time -- so a correction made once is worth keeping. They are stored
> by the lowercased word, which is why a piece list can be re-cased onto
> whatever the line actually says: "Somethin'" and "somethin'" are the same
> decision, spelled differently.


## `split`

**line 177** — before `if not any(c.isascii() and c.isalpha() for c in word):`

> Nothing here understands a script with no letters in it. CJK is cut by
> the reading, which is spicy_lyrics' job and needs the whole line for
> context -- so it is left alone rather than guessed at.

**line 182** — before `if any(c.isspace() or c == "\u200b" for c in word):`

> A piece holding more than one word is cut at the words first, and each
> of them by the rule. "do your" and "let 'em" are two words apiece and
> nothing was finding them, because this used to refuse any piece with a
> space in it -- which left a line like "It's a vibe, do your dance, let
> 'em watch" with nothing to split at all.
>
> The separator rides on the piece BEFORE it, exactly as a hyphen does,
> so the pieces still spell the word that went in. What the separator
> MEANS -- a word boundary, drawn with a space, or a zero-width one drawn
> without -- is read back off it when the syllables are built.


## `_hyphenate`

**line 229** — before `if len(word) > 1 and any(h in word[:-1] for h in HYPHENS):`

> A written hyphen outranks the patterns and keeps the same rule as the
> sung split: it ends the piece it sits on. Each side is then hyphenated
> by itself, or "tea-cher" comes back "tea-ch-er".

**line 287** — before `return out if joined == word and all(out) else [word]`

> The invariant, checked rather than trusted: any mapping slip hands back
> the word untouched instead of a corrupted lyric.
