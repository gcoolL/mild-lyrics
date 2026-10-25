# `editor/mpris.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/mpris.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The TTML Editor in the system's media controls (MPRIS) while it times a local file.
>
> mpris_player.Mpris, fed by an adapter that answers what it asks of Mild Lyrics' own
> player. On the bus as org.mpris.MediaPlayer2.ttml_editor, "TTML Editor", only while a
> local audio file is open; the player never follows that name (mpris_player.OWN).
> Not published offscreen or with MILD_NO_MPRIS=1, so tests never put it on the bus.
