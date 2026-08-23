# `editor/app.py`

Comments lifted out of `editor/app.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## `Editor.__init__`

**line 129** — before `self.push_timer = QTimer(self)`

> Debounced rather than sent per keystroke: a chorus being dragged
> emits a change per mouse move, and the player would spend the drag
> re-laying-out a document that is about to change again.

**line 135** — before `self.save_timer = QTimer(self)`

> Unsaved work, kept every half minute. Cheap -- a few tens of
> kilobytes -- and the difference between losing a session and not.

**line 141** — before `self.state_timer.timeout.connect(self.link.flush)`

> flush first: a push made while the player was away is held, and this
> is the tick that notices the player is back.

**line 145** — before `self.state_timer.start(120)`

> Often enough that the position taken from the player is never more
> than a frame or two old: it is the clock times are stamped against.


## `Editor._build`

**line 166** — before `self.keys = K.Keys(self, self._key_handlers())`

> Before the page, because the pad and the ribbon both label
> themselves with the keys. The handlers are late-bound lambdas, so
> they may name widgets the page has not built yet.


## `Editor._editor_page`

**line 183** — before `self.ribbon.setMinimumWidth(self.ribbon.sizeHint().width())`

> In a scroller, because a layout's minimum width is a HARD floor in
> Qt: the Edit mode's groups want 1473px, so switching to it from a
> 1200px window shoved the window wider every time. Inside a scroll
> area the ribbon keeps its natural width -- and scrolls sideways on
> a narrow screen -- while the window is free to be any size.

**line 190** — before `for name in ("Save", "Time selection"):`

> The two that get pressed most, marked so the eye lands on them.

**line 197** — before `strip_holder = QWidget()`

> The transport gets the same treatment as the ribbon and for the same
> reason: a row of controls is a floor under the window otherwise, and
> this one is 1100px of buttons. Scrolls only when it has to.


## `Editor._transport`

**line 439** — before `_shrinkable(self.tap_lbl, 260)`

> It may take room when there is room and give it all back when there
> is not. A minimum here is a floor under the whole WINDOW -- that is
> what a layout minimum means in Qt -- and this label is the least
> important thing in the bar.


## `Editor.fire`

**line 551** — before `pos = max(0.0, self.player.position() - self.tap_lag())`

> The lag comes off here and nowhere else: this is the path a REFLEX
> takes. A time dragged on the strip is placed by eye and needs no
> correction; taking it off there too would move the same times twice.

**line 565** — before `i2, v2, k2 = self.list.cursor`

> The commit key: this word's end IS the next word's start, so
> a line tapped through comes out with no holes in it.


## `Editor.take_doc`

**line 719** — before `if self.dirty and self.doc.lines:`

> Whatever is being replaced goes to the history first. A fetch
> into the wrong window used to end an hour's work in silence.

**line 730** — before `self.dirty = not path`

> A document read from a file is not unsaved work; one fetched
> from anywhere else is, and the title bar should say so.

**line 737** — before `QTimer.singleShot(0, win.accept)`

> Deferred for the same reason: accept() unwinds the dialog's
> event loop, and this is running inside a signal emitted by a
> widget that dialog owns.


## `Editor.show_import`

**line 764** — before `gone, self._import_window = self._import_window, None`

> Kept alive past exec() and dropped on the next turn of the loop.
> Letting Python drop the last reference here destroys the dialog --
> and the StartPage inside it -- while that page's own `loaded` signal
> is still on the stack, which is a use-after-free, not an exception:
> "Replace the lyric" took the whole application down with it.


## `Editor.save`

**line 811** — before `other = self._names(self.path) or self.path.name`

> The last line of defence. Even with the path cleared on every
> import, a window can end up pointing at a file that holds a
> different song -- and a lyric that took an hour to time is not
> something to overwrite on a keystroke without a word.

**line 827** — on `            if got == QMessageBox.StandardButton.SaveAll:`

> "Save as…"


## `Editor._same_song`

**line 864** — on `            return True`

> unreadable: not our business


## `Editor._autosave`

**line 889** — on `            return`

> nothing has moved since the last one


## `Editor.recover_dialog`

**line 935** — before `doc, said = read_lyric(str(it.data(Qt.ItemDataRole.UserRole)))`

> Opened WITHOUT its path: a recovered copy is not the file it came
> from, and saving it should ask where it goes.


## `Editor.do`

**line 956** — on `                self._undo.pop()`

> nothing happened; drop the snapshot


## `Editor._dragged`

**line 1111** — before `if self.wave._grab and not getattr(self, "_dragging", False):`

> One undo entry per drag, not per mouse move: the snapshot is taken
> when the grab starts and the moves after it fold into it.


## `Editor.split_dialog.corrected`

**line 1511** — before `if item.column() != 1:`

> Deferred, every path out: this runs from itemChanged, and
> refresh() rebuilds the very rows the signal came from. Doing it
> inline deletes the item mid-signal, which is a segfault, not an
> exception.


## `Editor.b_split_word`

**line 1598** — before `self.push_undo()`

> The snapshot comes first because _split_prompt applies the split
> itself; do(None) drops it again if the dialog was cancelled.


## `Editor.model_dialog`

**line 1892** — on `        self.engine = None`

> a different model, loaded fresh


## `Editor.b_auto`

**line 1913** — before `device = "cpu" if self.args.device == "cpu" else (`

> The device the player is set to, not this window's argparse default:
> they were disagreeing about the machine as well as the model.


## `Editor.b_auto.job`

**line 1934** — before `say("fetching a copy to listen to…")`

> Spotify will not hand over the sound, so the aligner's own
> copy is fetched -- the same one, kept in the same place, as
> when the player aligns a song by itself.


## `Editor.closeEvent`

**line 1981** — before `self.link.release()`

> Hand the song back to the player, or it goes on showing a
> document whose editor has closed.


## `_scroller`

**line 2000** — before `area.setStyleSheet(f"QScrollArea {{ background: {T.INK_0}; }}")`

> Type-scoped, or it lands on every child: an unselectored rule is
> applied to descendants too, which repainted the primary buttons inside
> these bars with the window's background and left their dark labels
> invisible on it.
