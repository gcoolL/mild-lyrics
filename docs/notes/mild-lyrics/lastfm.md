# lastfm.py — Last.fm scrobbling

## 2026-10-22 — built

Looked into 2026-10-19, built
2026-10-22 once the API account was registered (key + shared secret in
`lastfm.py`; no callback URL, desktop sign-in doesn't use one).

- **Sign-in:** Settings ▸ Last.fm ▸ Account. `auth.getToken` (signed), the
  browser opens `last.fm/api/auth/?api_key=…&token=…`, and `auth.getSession`
  is asked every 4 s for up to 5 min (error 14 = not allowed yet). The session
  key goes in `<config>/lastfm.json`, mode 0600, and is listed under Storage ▸
  Forget credentials.
- **Now playing** once 3 s of a play have been heard while playing.
- **Scrobble** once half the song or 4 minutes has been heard (Last.fm's
  rule), never for songs of 30 s or less; unknown length = 4 minutes. Sent at
  that point, not when the song ends, so quitting mid-song still counts. The
  timestamp is the play's start (`Tracker.cur["t"]`). Autoplay's picks are sent
  with `chosenByUser=0`.
- **Artist:** the player's first `artists` entry when the metadata has the
  list (MPRIS), else the whole artist string. Never split on commas
  ("Tyler, The Creator").
- **Spotify plays are left out** unless "Spotify plays too" is on: Spotify
  scrobbles them itself when the account is connected.
- **Queue:** `<config>/lastfm-queue.json`. No answer or codes 8/11/16/29
  keep it and wait 1, 5, 15, then 60 min; a new scrobble asks again at once.
  Up to 50 per request. Older than 14 days is dropped (Last.fm ignores it).
  Any other refusal drops that batch. Code 9 (session revoked) signs out and
  keeps the queue for the next sign-in; signing out by hand clears it.
- `--no-persist` and fixture runs never read the session or send.

Fed from `Home.observe` right after the play tracker, so it sees exactly the
plays the play log sees. Credit: scrobbling shows no Last.fm data, so the API
terms' "powered by AudioScrobbler" credit (2.7) only becomes due if Last.fm
data (similar tracks, charts) is ever shown.

Test: `~/mild-lyrics-archive/tests/test_lastfm.py` (local fake server, 57).

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/lastfm.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> Last.fm scrobbling: what plays here goes to the listener's Last.fm profile.
>
> Desktop sign-in (a token they allow in the browser, then a session key kept in
> lastfm.json), "now playing" once a song has been heard a moment, and a
> scrobble once half of it or 4 minutes has. Spotify plays are left out by
> default: Spotify scrobbles them itself when the account is connected. Notes:
> docs/notes/mild-lyrics/lastfm.md.
