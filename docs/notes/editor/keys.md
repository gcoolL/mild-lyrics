# `editor/keys.py`

Comments lifted out of `editor/keys.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 58** — before `("seek_back", "Back a quarter second", "Shift+Left", "Transport"),`

> Not the bare arrows: those belong to the cursor, and binding them here
> took them away from it -- pressing Left in the lyric moved the SONG a
> quarter second instead of moving to the previous word.


## `Keys.__init__`

**line 120** — before `self.can = can or (lambda _name: (True, ""))`

> `can(name)` answers (whether this action can be done at all right
> now, and why not). Asked at the moment the key is pressed rather
> than when it is bound, because the answer changes under the window:
> the rate keys mean nothing while Spotify is the player and mean
> something again the moment a local file is opened. Left off,
> everything is always possible, which is what a caller with no
> opinion means.


## `KeyDialogue.__init__`

**line 204** — before `groups: list = []`

> By group name, not by runs of it: ACTIONS lists the two nudge keys
> under Timing well after Transport, and reading it as runs made a
> second tab called Timing with two rows in it.

**line 220** — before `cap = QLabel(escape(label) if ok or not why else`

> The reason on its own line under the action, rather than run
> on after a dash: these read as sentences and two of them in
> a row read as neither.

**line 250** — before `self.resize(460, 420)`

> Small enough for a laptop screen, and resizable from there. Sizing
> itself to its contents is what put the buttons out of reach.


---

## Lift — 2026-10-25

Docstrings shortened in `editor/keys.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The editor's keys, and the little file that remembers them.
>
> Timing a lyric by hand is a keyboard job -- one hand on three keys, the other
> on the transport -- so the three that matter are the ones AMLL's tool uses and
> they are rebindable, because everybody who does this has already learned a
> layout somewhere else:
>
>     start   (F)   put this chip's start at the playhead, stay put
>     commit  (G)   end this chip AND start the next one here, step on
>     end     (H)   end this chip here, step on without starting the next
>
> The middle one is the whole trick: tapped in time with the singing it walks a
> line from beginning to end leaving no holes, because every tap closes the
> piece before it. The other two are for the edges -- a first word coming out of
> silence, a last word that rings on after it.
>
> Drag sync does the same job with the mouse -- see `editor/syncbar.py` -- and
> has two keys of its own for the parts of it a hand holding the mouse cannot
> reach: play this row's line again, and leave this row for the next.
>
> Settings live beside the player's own, in the same directory and a different
> file: `editor.json` next to `gui.json`. The player's settings have a schema
> and a migration history and there is no reason for this to be inside it.

### `canon`

**line 74** — from the docstring, `def canon(key) -> str:`

> The one spelling of a key, so that two of them can be compared.
>
> `f`, `F` and `Ctrl+s` are the same keys as `F`, `F` and `Ctrl+S`, and
> a clash that is only spelt differently is still a clash. Anything Qt
> cannot read back -- a hand-edited `editor.json` saying `zzz` -- comes
> back empty, which is the same as no key at all.

### `config`

**line 122** — from the docstring, `def config() -> dict:`

> Every setting kept, as a copy that can be changed freely.
>
> Read again only when the file has changed. Every refresh asks for it a
> few times, and each ask was a read and a parse of a file that holds every
> hand-made split -- about 1.6ms at 3000 of them, per ask, on every tap,
> edit and drag.

### `remember_soon`

**line 154** — from the docstring, `def remember_soon(**values) -> None:`

> Keep a setting a moment from now, for a slider that is being dragged.
>
> Every tick of a drag was a write of the whole file -- it holds every hand
> split, so about 4ms at 3000 of them -- a hundred times over. What is
> asked for here is seen at once by `config`, so whatever reads it back to
> apply the change still can, and one write follows LATER_MS after the hand
> stops. `flush` puts it down early: on the way out of the window, and at
> exit if it never got that far.

### `Keys.install`

**line 220** — from the docstring, `def install(self) -> None:`

> Bind every action to its key -- one action per key.
>
> Qt will take two shortcuts on one key, match both and then call
> neither: the press arrives as `activatedAmbiguously`, which nothing
> was listening to. So the two keys that clashed both went dead, which
> is the worst of the three possible outcomes and the one that reads
> as the whole window being broken. A key is given to one action here
> -- the first that asks for it -- and the other is left unbound and
> remembered in `clashes`, to be said out loud rather than discovered.

### `Keys.set`

**line 292** — from the docstring, `def set(self, mapping: dict) -> dict:`

> Take a new layout, keep it, and say what had to give way.
>
> One key, one action. A key asked for twice goes to whichever of the
> two is being CHANGED -- that is the one the hand at the dialogue just
> typed, and the other is the one it meant to take it from -- and the
> loser is handed nothing and named in what comes back, so the caller
> can say whose key has just gone. A key the window keeps for itself
> cannot be taken at all: Ctrl+S is Save, and an action bound to it
> used to kill Save and itself together.

### `KeyDialogue`

**line 322** — from the docstring, `class KeyDialogue(QDialog):`

> Rebind anything, or put it all back.
>
> A tab per group, and each one scrolls. It was one grid of every action
> with the group names as captions inside it -- thirty rows in a dialogue
> that cannot be scrolled and sizes itself to its contents, so on a short
> screen the buttons at the bottom were off the bottom and there was no way
> to reach the OK. Four short tabs fit anywhere, and they are also how
> anybody thinks about these: the timing keys are learnt together and the
> editing ones are looked up one at a time.
>
> An action that cannot be done in the window as it stands is shown greyed
> with the reason beside it -- the rate keys while Spotify is the player,
> the model key on a machine with no model. It is still rebindable: what is
> impossible now is not impossible, and a key you cannot press today is
> still a key you may want on a different button.
>
> A key is taken off whatever held it the moment it is typed, and that row
> says so. Typing over a key you have already used is the ordinary way to
> move one -- you go to the action you want it on, not to the one you want
> it off -- and leaving both rows holding it is what killed them both.

### `KeyDialogue._typed`

**line 404** — from the docstring, `def _typed(self, name: str) -> None:`

> A key has just been typed into one of the boxes.
>
> The dialogue used to take whatever was typed and hand the lot to
> `Keys.set` at OK, so a key typed onto a second action left it on
> the first as well and both stopped working -- with the dialogue
> showing the same key twice and saying nothing about it. Here the
> row that held it gives it up as you type, in front of you.
>
> `_seen` is what each box last said, because Qt reports a box that
> has not changed: a second after the key lands, the edit finishes
> itself and says so again, and a run of that wiped the line saying
> where the key had just gone.

### `KeyDialogue._retell`

**line 467** — from the docstring, `def _retell(self, skip=()) -> None:`

> What every row says when it has no news of its own.
>
> Either what that action cannot do in the window as it stands, or
> that it has no key at all. An action with no key is a real thing
> to want and an invisible thing to have -- an empty box reads as a
> box nobody has got to yet -- so it is written down.

---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/keys.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 38** — before `ACTIONS = [`

> (name, what it is called on screen, default key, group)


### `remember`

**line 88** — on `        pass`

> a settings file that will not write is not


### module level

**line 89** — before `def bindings() -> dict:`

>                         a reason to stop editing


### `Keys.install`

**line 123** — before `sc.setContext(Qt.ShortcutContext.WindowShortcut)`

> WindowShortcut, not WidgetWithChildren: the strip, the list and
> the ribbon are all children of the window and a tap has to work
> wherever the focus happens to be sitting -- except in a text
> box, which swallows it first because it has focus.
