# `editor/player.py`

Comments lifted out of `editor/player.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `Player`

**line 33** — on `    changed = pyqtSignal()`

> track, length or play state moved


## `LocalPlayer.position`

**line 113** — before `if not self.playing():`

> Interpolated between Qt's updates, which arrive a few times a second.
> A playhead that only moves when they do reads as stuttering, and a
> tapped time taken from a stale reading is late by however long ago
> the last update was.


## `SpotifyPlayer._poll`

**line 186** — before `self.clock.poll(pin_pause=False)`

> No pause pinning: that seeks the player to where it already is,
> which is right for a lyric view holding sync over a long pause
> and wrong here, where a pause is usually somebody about to
> scrub a syllable into place.


## `SpotifyPlayer`

**line 209** — before `LINK_STALE = 1.2`

> How stale a reading from the player may be before its own clock is
> trusted again. The editor asks several times a second, so this only
> trips when the player has gone away.

**line 213** — before `CARRY = 0.4`

> How far a reading may be carried forward. Both clocks run at 1x from
> the same instant, so this is exact while it lasts -- but after a seek
> the player re-samples and eases the correction in, and carrying an old
> reading through that is how the two drift apart. Past this, hold still
> and wait for the next reading rather than inventing more of one.

**line 219** — before `ASSUME = 1.5`

> An action taken HERE is believed until the player confirms it. The
> player polls the transport every 250 ms (110 while paused), so for that
> long after a seek or a pause made in this window its clock still
> describes the song as it was -- and the editor, which mirrors it, would
> stamp against a position the song has already left. This is the ceiling
> on how long that belief may last if the player never confirms.


## `SpotifyPlayer.position`

**line 249** — before `since = now - float(got.get("at", 0.0) or (now - 0.0))`

> From the instant the PLAYER sampled, not from when its
> answer reached here.

**line 257** — before `mine = self._assumption(now, got)`

> Anything this window did to the song, until the player has looked
> again and seen it.


## `SpotifyPlayer.seek`

**line 310** — on `            self.link.ask_state()`

> confirm it as soon as possible


## `SpotifyPlayer.toggle`

**line 313** — before `at = self.position()`

> Where the song is at the instant of the press, and which way it is
> about to go. Without this the position kept advancing for a quarter
> of a second after a pause -- the player's poll interval -- and
> anything stamped in that window was late by however long it took.
