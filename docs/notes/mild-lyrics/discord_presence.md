# `mild-lyrics/discord_presence.py`

## 2026-10-29 — "for 0:12" before the time bar

Bug: a new song's card said "listening for 0:12", then became "00:22 / 03:06"
a while later. A card with no `timestamps` gets Discord's own count from when
the card arrived. Mild Lyrics' own player reports Paused while a track loads
(`LocalPlayer.reading`), and a length can come late from the catalogue for
other players. Either way, the first card of a song went without a bar, and
the bar's arrival counted as a mere line change. That waited behind GAP and
the three paced sends in WINDOW, up to 20s. Fixed: `bar_moved` makes a time
bar coming, going or seeking (start off by SEEK_SLACK) urgent, like a new
song. Test: `test_discord_timebar.py` (the old pacing fails it).

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/discord_presence.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Discord Rich Presence: the song, and the line being sung, on a profile.
>
> Discord's desktop app listens on a local socket -- a Unix socket under the
> runtime directory, a named pipe on Windows -- and anything on the machine may
> say "this is what I am doing" over it. Nothing goes over the network from
> here: Discord itself carries the activity to everyone else.
>
> Spoken by hand rather than through pypresence. The protocol is five opcodes
> and a JSON body, and this program is installed by people with no pip of their
> own (see setup.sh), so one module less to fetch is one way less to break.
>
> Everything the activity says comes from `activity()`, which is pure: the
> settings preview draws exactly what would be sent, from the same function.

### `activity`

**line 167** — from the docstring, `def activity(state: dict, cfg: dict) -> dict | None:`

> What Discord is told, or None to show nothing.
>
> `state`: title, artist, album, line, next, art (a cover URL), playing,
> pos and length (seconds), spotify (a track id, or ""), listen (the
> listen-along page while sharing, or ""), paused_for (seconds this pause
> has lasted). `cfg`: the discord_* settings.

### `Covers`

**line 548** — from the docstring, `class Covers:`

> Animated covers on the Worker, album by album, from a thread of its own.
>
> `want()` names an album; the first time, Apple is asked for its animated
> cover (`find`), the Worker is asked whether it already has the GIF, and if
> not one is made here with ffmpeg and put there. `url()` is then the
> address to give Discord, or "" while there is none -- the still cover
> stands in until then, and for every album with no animation at all.
>
> What has been learnt is kept in `memo` (a JSON file), so an album is only
> ever looked up once and a GIF only ever uploaded once.

### `paint_preview`

**line 715** — from the docstring, `def paint_preview(p, rect, act: dict | None, state: dict, cfg: dict,`

> A Discord profile card showing `act`, drawn into `rect`.
>
> Drawn from the same activity that would be sent, so what it says is what
> Discord is told; the look is Discord's dark card, approximately -- the
> client lays it out, and it does not lay every version out the same.
> `cover` is the album art as a QPixmap, or None. `font(px, weight)` makes
> a QFont.

### module level (comment)

**line 33** — before `WINDOW, LIMIT = 20.0, 5`

> Discord takes five activity changes in twenty seconds and drops the rest
> without a word. Lines take three of the five, spaced GAP apart, and the
> rest are kept for a change of song, which goes the moment it is seen --
> held behind a line's gap it reached the profile seconds late. A line
> shorter than GAP can be passed over: what goes is always the newest, never
> a queue of stale ones.
