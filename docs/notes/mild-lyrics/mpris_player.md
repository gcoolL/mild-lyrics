# `mild-lyrics/mpris_player.py`

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/mpris_player.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Mild Lyrics' own player on the session bus (MPRIS), so the desktop's media controls,
> lock screen, media keys and KDE Connect show it as "Mild Lyrics".
>
> Linux only. On the bus only while the local player has a queue, under
> org.mpris.MediaPlayer2.mild_lyrics; the window's own player-following leaves
> that name out (it is not somebody else's player). Uses its own private bus
> connection with GLib's main loop, which is what Qt runs on here.
> Notes: docs/notes/mild-lyrics/home_page.md.
