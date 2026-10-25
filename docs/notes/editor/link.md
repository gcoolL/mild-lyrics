# `editor/link.py`

Comments lifted out of `editor/link.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `Link._read`

**line 102** — before `self._want_doc = False`

> A refused DOC request goes to whoever asked for it, not to
> the toast. Sent to the toast it read as an unrelated
> complaint while the asker sat waiting out its timeout and
> then said "the player did not answer" -- which was untrue
> and hid the reason.


---

## Lift — 2026-10-25

Docstrings shortened in `editor/link.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The editor's end of the live link to a running Mild Lyrics.
>
> One socket, five messages, and a reconnect timer. Everything is asynchronous:
> the player is a GUI too, and an editor that blocks on it would stutter exactly
> when the user is tapping times.
>
> What travels over it is the whole document, every time. TTML for a long song
> is some tens of kilobytes over loopback, which is nothing next to the cost of
> being clever -- a patch protocol would have to agree with the player about
> what a line is, and the two would drift the first time either changed.

### `Link._read`

**line 64** — from the docstring, `def _read(self) -> None:`

> Whole lines only, and decoded only once they are whole.
>
> The buffer holds BYTES. A reply is split across TCP segments -- the
> player's document arrives in three -- and decoding each chunk as it
> came turned any multi-byte character caught on a boundary into U+FFFD.
> The row then stopped being JSON and was dropped silently, so the
> answer never arrived and the request timed out with no reason given.
> Pure ASCII lyrics never showed it; anything else would.

### `Link.ask_doc`

**line 109** — from the docstring, `def ask_doc(self, own: bool = True) -> bool:`

> Ask the player for lyrics.
>
> `own` asks for the SONG'S own document rather than whatever is on
> screen. While this editor is pushing, those are two different things
> and the second one is us: asking for what is on screen handed our own
> file straight back, which looked exactly like the fetch failing.
>
> An older player answers `unknown command` to `source_doc`, so the
> caller falls back to `doc` when it is refused.

### `Link.push`

**line 116** — from the docstring, `def push(self, ttml: str, tid: str = "", name: str = "the editor") -> bool:`

> Put this document on the player's screen.
>
> A document that could not be sent is kept, not dropped: the player is
> usually a second away from being back, and the next push -- or the
> reconnect -- carries the newest version of the file rather than
> leaving the screen a few edits behind.

### `Link.follow`

**line 127** — from the docstring, `def follow(self, pos: float, playing: bool, rate: float = 1.0,`

> Tell the player where the local audio being timed against is.
>
> Only sent while timing against a FILE. Timing against Spotify, the
> player is already the clock and has nothing to be told. What it does
> with this is its own business -- see the player's follow_editor -- and
> it is told often, because a position is only worth anything fresh.
>
> The speed goes with it: the player carries the position forward
> between messages, and a file played at half speed carried forward at
> full speed runs the words ahead of it and snaps them back every tick.
>
> And the moment it was true, on perf_counter -- the clock the player's
> mono() reads, and one clock for the whole machine -- so the player
> carries it forward from when it was said rather than from when it
> arrived, and a busy frame over there does not land the words late.

### `Link.flush`

**line 182** — from the docstring, `def flush(self) -> None:`

> Send whatever a lost connection left behind.
>
> Called on every state tick as well as on reconnect: a push that could
> not go out is the one thing here the user cannot see has failed, and
> waiting for the next edit to carry it is how a document ends up on
> screen one version behind.

---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/link.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### `Link`

**line 27** — on `    state = pyqtSignal(dict)`

> the player's answer to `state`

**line 28** — on `    refused = pyqtSignal(str)`

> ...and why it would not take one

**line 29** — on `    doc = pyqtSignal(dict)`

> the document the player is showing


### `Link.__init__`

**line 41** — on `        self._pending = ""`

> the last document, still unsent

**line 43** — before `self.last_at = 0.0`

> When it arrived, so a reading can be interpolated forward rather
> than used stale -- see player.SpotifyPlayer.position.

**line 50** — before `app = QCoreApplication.instance()`

> A socket still trying to connect when the interpreter tears down
> takes the process with it -- Qt aborts on a notifier whose event
> loop has gone. Shutting it down while there is still an application
> to shut it down with is the whole fix.


### `Link._read`

**line 96** — before `self.refused.emit(str(got.get("why") or "refused"))`

> A push the player would not show. Worth saying out loud: a
> document that stopped appearing and an editor that stopped
> sending look the same from this end.
