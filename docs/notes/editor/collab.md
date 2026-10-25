# `editor/collab.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/collab.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Timing one lyric together: what travels, who holds what, and who decides.
>
> Nothing here knows about Qt or the network. The window hands it documents and
> messages; it hands back messages to send and changes to apply. That is what
> lets two and three people be tested in one process with a list for a wire.
>
> THE SHAPE. One person hosts and is the authority. Everybody else's edits go
> to the host, which checks them against who holds what, applies them to the
> one true document and tells everyone -- the sender too -- what happened.
>
> WHAT AN EDIT IS. The editor changes its document in place, in some three
> thousand lines of operations, and nothing about that is going to grow a patch
> format. So an edit here is a DIFF: the document now against the document as
> last agreed (`shared`), line by line, by each line's uid. A line that changed
> is sent whole. A song is a few hundred lines at most, and comparing them is
> dataclass equality, which costs less than one repaint.
>
>     set    {o:"set", u:uid, l:line}   a line, new or changed, whole
>     del    {o:"del", u:uid}
>     order  {o:"order", u:[uid...]}    every line, in order -- only on a move
>     meta   {o:"meta", m:{...}}        the header: title, artist, writers
>     parts  {o:"parts", p:[...]}       the grouped runs (Doc.parts)
>
> WHO HOLDS WHAT. A line is held by whoever's cursor or selection is on it, and
> by whoever has claimed it (a chorus, say) until they let it go. A held line
> can only be changed by its holder. An edit that would change anyone else's
> line is not partly applied: it is undone whole, here and at the host, so
> nobody is ever left with half of a merge.
>
> WHY NOTHING BUT JSON. A peer is somebody else's program. What arrives is
> checked field by field against hard limits before it becomes a single
> syllable; there is no TTML on the wire, so no XML parser ever sees a peer's
> bytes, and there is no message that names a file, a setting, the audio or the
> player. The worst a peer can do is change the lines nobody else holds.

### `song_url`

**line 257** — from the docstring, `def song_url(url) -> str:`

> A link a joiner's editor may download the song from, rebuilt from its
> bare id -- or '' for anything else.
>
> Only a YouTube video or a SoundCloud track, and never the string the
> host sent: a host is somebody else's program, and what the joiner's
> downloader is pointed at must not be theirs to choose. Everything that
> is not one of these two shapes is dropped, and the joiner searches for
> the song by name and length instead.

### `adopt`

**line 410** — from the docstring, `def adopt(shared: M.Doc, doc: M.Doc) -> None:`

> Give a line rebuilt as a new object its old uid back, if it is word
> for word and time for time the line it replaced.
>
> Some operations build every line afresh rather than change the ones
> there. Without this, each of those reads as every line deleted and made
> again -- which touches every line anyone holds, and is refused.

### `Locks`

**line 633** — from the docstring, `class Locks:`

> Who holds which line, first come first served.
>
> `presence` is where each person IS -- cursor and selection -- and moves
> with them. `claims` are lines somebody asked to keep, and stay theirs
> until they let go or leave. A line held either way by one person is not
> given to another until it is free.

### `Member.on_message`

**line 1381** — from the docstring, `def on_message(self, msg) -> dict:`

> Handle one message from the host. Returns what the window must do:
>
>     {"doc": Doc}            take this document whole (joining)
>     {"ops": [...]}          apply these to the screen and the undo
>     {"fix": [...], "why"}   my edit was refused: put these back
>     {"who": True}           people or locks changed
>     {"end": why}            the session is over
>     {}                      nothing to do
>
> Raises Bad if the host sent something no host would.
