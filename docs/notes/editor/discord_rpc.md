# `editor/discord_rpc.py`

## Lift — 2026-10-25

Docstrings shortened in `editor/discord_rpc.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The editor's Discord status: which song is being synced, how far along
> it is, where in the song you are, and whether it is a multiplayer session.
>
> The same pipe and the same pacing as the player's card (discord_presence):
> Discord takes five changes in twenty seconds, a new song or a pause goes
> ahead of the rest, and a card that differs only in its times is not sent
> again. "Playing Mild Lyrics", where the player's says "Listening to": the
> application is the same one, and it is syncing that is being done.
>
>     Syncing The Mystic — Adam Jensen
>     62% synced · at 1:23 · hosting a session with 2 others
>
> While the song plays at its own speed the time is Discord's own bar, which
> counts on by itself; paused, or slowed down, it is said in words, kept up
> with as far as the pacing lets it.
