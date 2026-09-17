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
