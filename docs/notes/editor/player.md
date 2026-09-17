# `editor/player.py`

Comments lifted out of `editor/player.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `Player`

**line 61** — before `def volume(self) -> float:`

> How loud the song is, 0..1, on the perceived scale rather than the
> amplitude one -- the number a slider is holding. Both ends have a
> volume, so unlike the rate this is not a local-only thing, and it is
> asked of the player rather than kept in the window because Spotify's
> is the system's and can be moved from outside this program.

**line 75** — before `def heard(self) -> str:`

> Which RENDERING of the song is coming out of the speakers, as against
> `audio_path`, which is the song itself. Only a local file can be told
> to play something else; Spotify plays what Spotify has.


## `LocalPlayer`

**line 139** — before `def heard(self) -> str:`

> The song and the RENDERING of the song are two different questions.
> `path` is the file this window is timing against: it is what the model
> listens to, what the waveform is drawn from, and what every cache is
> keyed by. `_heard` is whichever rendering of it is coming out of the
> speakers -- the mixture, the separated vocal, or a blend of the two.
>
> They have to be separable because the vocal is an aid to the EAR and
> nothing else. A word placed while listening to the stem is placed at
> the time it is sung in the song, and a document that came out different
> depending on what the person timing it happened to be listening to
> would be worthless. So nothing downstream is allowed to see `_heard`:
> `audio_path` keeps answering with the song. See Editor._vocal_mix.

**line 197** — before `JUMP = 0.25`

> `where we put it, plus how long ago`. That is the whole of it.
>
> A local file has no second party. Nothing moves this song except this
> window: it starts where we opened it, it goes where we seek it, and in
> between it advances at the rate we asked for. So the clock is a
> straight line from an anchor this window sets -- on open, on a seek, on
> a resume, on a rate change -- and between those it is not touched by
> anything at all. That is the one thing a clock people tap syllables
> against has to be, and everything below is about NOT doing things to it.
>
> It used to be steered. The backend's reports do not tick with the wall
> -- they arrive every 100ms or so carrying a position that has advanced
> about 93, and then make the difference up in one 44ms lurch -- and the
> clock chased them, re-anchoring on each one and working the error off
> by running up to three per cent fast or slow. Three per cent is 30ms in
> a second, so the same syllable tapped at the same moment of the same
> song was stamped differently depending on where in the correction the
> tap fell, and every resume started a fresh correction from a fresh
> error.
>
> Then it WAITED for them, which was worse to use: half a second of
> frozen playhead on every seek and every resume, bought in exchange for
> measuring something a local file cannot get wrong.
>
> And then it disciplined its own rate against them -- the sound card
> counts in its own crystal, this process counts in the system's, and the
> two are tens of parts per million apart. That one at least was arguable,
> and it was still wrong: fitted over a minute of reports the slope came
> out about 30ppm noisy, which is the same size as the drift it was there
> to remove, so on a card that was already perfect it pulled the rate
> 30ppm off and swung the clock 34ms across six minutes. A correction no
> better than its own error is not a correction. What is left of that
> drift is tens of milliseconds over many unbroken minutes, and it starts
> again from nothing at every seek and every pause -- which, timing a
> song by hand, is constantly.
>
> So the reports are read for exactly one thing: a position further out
> than JUMP, which is not wobble. The file has ended, the pipeline has
> stalled, or the song has moved in a way this window did not ask for --
> and the anchor is set again there. For GRACE after a move of our own
> they are not consulted even for that, because the pipeline goes on
> reporting where it WAS for a moment after a seek. Nothing waits on
> GRACE; the clock is already running, from the position we just set.
>
> What is left is a constant: the sound of a given moment leaves the
> speakers a little after the clock says so, by however long the device
> takes to fill. It is the same on every seek and every resume because it
> is a property of the device -- and a constant offset is exactly what
> the tap lag box takes out.

**line 246** — on `    JUMP = 0.25`

> further out than this and the song has been moved

**line 247** — on `    GRACE = 0.5`

> after a move of ours, before the reports are believed


## `LocalPlayer._moved`

**line 258** — before `self._pos, self._at = got, now`

> Paused. The backend's own position is the honest answer, and
> it is where it will resume from -- so it is what the resume
> anchors on. Taking anything else would have the clock and the
> sound disagree from the first instant of the next stretch.


## `LocalPlayer.toggle`

**line 293** — before `self._restart(self._pos)`

> From wherever it was paused, which is where the backend will
> resume from -- and running from this instant, not from
> whenever the reports get round to confirming it.


## `_Pump.run`

**line 433** — before `self.clock.status = "Error"`

> `spotify_dom.connect` calls sys.exit when the debug port has
> gone -- a SystemExit, which is not an Exception and which,
> raised on the GUI thread, used to take the editor and its
> unsaved lyric with it. It stops here.


## `SpotifyPlayer`

**line 512** — before `CARRY = LINK_STALE`

> As far as a reading is carried forward before this stops believing it.
> It has to be the whole of the window in which the reading is used at
> all: shorter, and every gap between two words from the player leaves a
> stretch where the position is pinned at last + CARRY and the clock
> simply stops -- the song runs on, the number does not, and everything
> tapped inside it is stamped at the same time. The player says something
> twice a second and the moment anything jumps (see SAY_EVERY there), so
> a reading this old means the link is gone, and gone is what LINK_STALE
> already decides.


## `SpotifyPlayer.set_volume`

**line 626** — before `with self.clock.lock:`

> Believed here and sent from the pump, the way a seek is: the
> slider must not spring back to the last reading in the quarter
> second before the player answers. `wants_volume` reads this same
> stamp, and is what stops a reading taken inside that window from
> arguing with what has just been asked for.


---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/player.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### `Player`

**line 33** — on `    changed = pyqtSignal()`

> track, length or play state moved


### `LocalPlayer.position`

**line 113** — before `if not self.playing():`

> Interpolated between Qt's updates, which arrive a few times a second.
> A playhead that only moves when they do reads as stuttering, and a
> tapped time taken from a stale reading is late by however long ago
> the last update was.


### `SpotifyPlayer._poll`

**line 186** — before `self.clock.poll(pin_pause=False)`

> No pause pinning: that seeks the player to where it already is,
> which is right for a lyric view holding sync over a long pause
> and wrong here, where a pause is usually somebody about to
> scrub a syllable into place.


### `SpotifyPlayer`

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


### `SpotifyPlayer.position`

**line 249** — before `since = now - float(got.get("at", 0.0) or (now - 0.0))`

> From the instant the PLAYER sampled, not from when its
> answer reached here.

**line 257** — before `mine = self._assumption(now, got)`

> Anything this window did to the song, until the player has looked
> again and seen it.


### `SpotifyPlayer.seek`

**line 310** — on `            self.link.ask_state()`

> confirm it as soon as possible


### `SpotifyPlayer.toggle`

**line 313** — before `at = self.position()`

> Where the song is at the instant of the press, and which way it is
> about to go. Without this the position kept advancing for a quarter
> of a second after a pause -- the player's poll interval -- and
> anything stamped in that window was late by however long it took.
