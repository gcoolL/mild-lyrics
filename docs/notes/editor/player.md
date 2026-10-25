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

## Lift — 2026-10-25

Docstrings shortened in `editor/player.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> What the words are being timed against: a file on disk, or Spotify.
>
> Both ends answer the same four questions -- where are you, how long are you,
> are you playing, and go here -- so the timing tab never asks which it has.
> The differences are real but small, and each is dealt with here:
>
>   * a local file can be played at half speed, which is the single most useful
>     thing there is for placing syllables by hand; Spotify cannot;
>   * a local file's clock is this process's own, so it is exact. Spotify's is
>     read over MPRIS or the debug port a few times a second and interpolated
>     in between, which is what the player does too;
>   * the times written for Spotify are LYRIC times, which is the player's
>     clock minus whatever offset it applies to this track. Getting that wrong
>     puts every syllable in the file a fifth of a second out and makes the
>     editor and the player disagree about a document they are both showing.

### `LocalPlayer.hear`

**line 131** — from the docstring, `def hear(self, path: str) -> bool:`

> Play this rendering instead, from where we already are.
>
> The clock is not restarted anywhere in here. Qt loads the new source
> asynchronously and reports position 0 while it does, which is exactly
> the reading `_moved` is built to ignore -- so the swap is done under
> GRACE, with the position and the playing state put back the moment
> the media is ready.

### `LocalPlayer._restart`

**line 193** — from the docstring, `def _restart(self, pos: float, wait: bool = False) -> None:`

> Set the clock. Only a move of ours calls this.
>
> `wait`: hold still at `pos` until the file is heard to move off it
> (or WAIT has gone by), rather than starting to run now. For a resume
> and for a seek while playing -- the two moments the sound does not
> start when asked.

### `LocalPlayer._apply_volume`

**line 296** — from the docstring, `def _apply_volume(self) -> None:`

> Qt's output takes an AMPLITUDE; a slider is a loudness.
>
> Setting the amplitude straight from the slider makes the top third
> of the travel do almost nothing and the bottom third do everything,
> which is why halving a slider that behaves that way barely helps
> anybody whose ears are being taken off. Qt has the conversion --
> the same one its own volume widgets use.

### `_Pump`

**line 325** — from the docstring, `class _Pump(QThread):`

> The one thread allowed to wait for Spotify.
>
> Every question put to the player is a round-trip -- a D-Bus call over the
> session bus, or a CDP evaluate down the debug port -- and the socket is
> given fifteen seconds to answer. Spotify does not always answer promptly:
> around a resume or a seek its renderer is busy, and a reply that normally
> takes a millisecond can take most of a second. Asked from the GUI thread
> four times a second, that is a window which stops drawing and stops taking
> keys in exactly the moment somebody is tapping syllables into it -- and a
> tap that lands late is a syllable placed late.
>
> So the waiting happens here. The reading is arithmetic, done under the
> clock's lock; the window reads a position between readings and never
> blocks. Commands go the same way: a seek is BELIEVED immediately (see
> `_assume`) and sent from here, so the transport being slow to take it
> costs the display nothing.

### `_Pump._due`

**line 351** — from the docstring, `def _due(self) -> list:`

> Everything asked for since the last pass, with the dead dropped.
>
> A VOLUME that another volume follows was out of date before it was
> sent, and sending it anyway costs a whole round trip to the player.
> That is what made a wheel over the volume lag: forty notches queue
> forty messages, this drained them one at a time, and the sound went
> on climbing for as long as the round trips took -- a fifth of a
> second over D-Bus and two seconds over the debug port -- after the
> hand had stopped. Only the last one was ever going to be audible.
>
> Volume only. A seek is a place somebody asked to hear and passing
> over one changes what they heard; a command is an act. Volume is the
> one thing here that is a LEVEL, where the last word is the whole
> answer and the ones before it are not even played.

### `SpotifyPlayer`

**line 398** — from the docstring, `class SpotifyPlayer(Player):`

> Whatever Spotify is playing, over the same transports the player uses.
>
> The clock is Mild Lyrics' own, so pausing, seeking and the interpolation
> between polls all behave exactly as they do there. The offset is the
> GLOBAL one and only that -- taken from the running player when one is on
> the other end of the live link, and read off the same settings file when
> there is not, which comes to the same number either way.
>
> Not the per-track correction, and not the measured one. Both of those
> describe how far the song's OWN lyric sits out of true; the document
> being written here is a different document, and its times are whatever
> they are being set to. Adding a correction meant for another file shifts
> the clock a syllable is stamped against, so a syllable placed dead on is
> written wrong by exactly the offset -- and the writer, seeing it late,
> corrects for a shift that then really is in the file.

### `SpotifyPlayer.offset`

**line 436** — from the docstring, `def offset(self) -> float:`

> The global offset, exactly -- see the class docstring for why only.
>
> `base` and not `offset`, because the player's `offset` is a SUM whose
> meaning changes underneath us: track_offset() drops the per-track
> correction as soon as a live document is on screen, and carries it
> before that. Reading it meant every syllable stamped before the first
> push carried the per-track correction and every one after it did not --
> a step in the middle of a session, in the middle of a song, which is
> the worst shape an offset error can have. `base` is the global and
> only the global, whatever else is happening.

### `SpotifyPlayer.position`

**line 451** — from the docstring, `def position(self) -> float:`

> Where the SOUND is, in lyric time.
>
> Taken from the running player when one is on the other end of the
> link, and only from this process's own clock when there is not.
>
> Two programs polling MPRIS independently do NOT agree: each
> interpolates between its own polls, each applies its own smoothing,
> and the pair drift tens of milliseconds apart -- which is exactly the
> size of the disagreement between a time stamped here and where the
> player then draws it. Reading the position off the player itself
> removes the second clock entirely, offset and all.

### `SpotifyPlayer.volume`

**line 538** — from the docstring, `def volume(self) -> float:`

> Spotify's own, as the pump last read it.
>
> Read rather than remembered: this is the player's volume, and the
> person timing against it can move it in Spotify or with a media key
> while this window is open. `wants_volume` already stops a reading
> taken during our own set from arguing with it.

### `SpotifyPlayer.set_volume`

**line 550** — from the docstring, `def set_volume(self, v: float) -> None:`

> Spotify's volume -- through the running player where there is one.
>
> Set straight to Spotify from here, it argued with the player: one
> that had muted Spotify for a take muted it again on its next follow,
> or put its own remembered level back when it let go, and the slider
> here jumped back to where it had been. The player owns the level;
> this asks it. With no player on the link, straight to Spotify.

### `SpotifyPlayer.can_volume`

**line 561** — from the docstring, `def can_volume(self) -> bool:`

> Whether the way in to this player carries a volume at all.
>
> Only the session bus and the debug port do. Windows' media transport
> has no volume in the protocol and no door on a Mac publishes one that
> belongs to the player rather than to the machine -- so asking for it
> there raises, which Clock.set_volume catches by dropping the
> connection. A slider that silently reconnects the player every time it
> is dragged is worse than no slider, so it is not drawn.

### `SpotifyPlayer.audio_path`

**line 577** — from the docstring, `def audio_path(self) -> str:`

> The copy the aligner keeps for this track, if it has fetched one.
>
> Auto-timing needs a waveform, and Spotify will not give one out. The
> project already downloads a copy to align against and keeps it in
> `fetched/`, so if this song has been aligned before, the audio is
> already here.

### module level (comment)

**line 14** — before `_now = time.perf_counter`

> The clock a local file is carried forward on. perf_counter and not
> time.monotonic: on Windows under CPython 3.12 and earlier monotonic moves in
> 15.6ms steps, and a clock read thirty times a second to say where a
> syllable is was rounded to a sixteenth of a second there. It is also the
> clock the player's mono() reads, so a time sent across the link means the
> same thing at both ends.

### `LocalPlayer` (comment)

**line 167** — before `JUMP = 0.25`

> -------------------------------------------------------------- the clock
> Qt says where the file is in coarse steps -- a reading every 50ms or so,
> each a frame's worth of rounding -- so the position is carried forward
> between readings on a clock of our own and held to Qt's readings.
>
> It used to be held only loosely: a reading was acted on only when it
> disagreed by more than JUMP, a quarter of a second, and not at all for
> GRACE after a seek or a resume. Whatever the clock was out by at that
> moment -- the audio device taking its time to start, a seek landing on
> the frame before -- it stayed out by, until the next pause. Measured
> off the follow log: every pause snapped the words by anything from -130
> to +100ms, which is the clock and Qt parting company that far in
> between. A syllable tapped during a take was stamped that far out, by a
> different amount after every pause.
>
> Now every reading pulls the clock toward it (a first-order lock with
> time constant LOCK, so a reading's rounding is averaged out rather than
> drawn), and after a seek or a resume the clock WAITS for the file to
> actually move before it runs -- a resume used to run the words ahead of
> the sound by however long the device took to open.

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
