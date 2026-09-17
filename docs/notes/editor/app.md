# `editor/app.py`

Comments lifted out of `editor/app.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 40** — before `PUSH_MS = 180`

> The most the player is ever left behind what is being typed here. It is a
> rate limit, not a delay -- see schedule_push, which is where the difference
> turned out to matter.


## `Editor.__init__`

**line 128** — before `self._sweeping: dict | None = None`

> The drag in progress, as the WINDOW sees it: where the pointer was
> last, when it was there, and which syllables this pass has stamped.
> The list widget keeps the same pass in chips; this half keeps it in
> seconds. See _sweep_begin.


## `Editor._build`

**line 168** — before `T.scale()`

> Both of these are read from the settings file, and both have to be
> read BEFORE anything is dressed: every metric in the window is
> T.px(), which multiplies by the scale, and every painted colour is
> taken from the palette once at import. The scale was being written
> down and never read back -- the A+ buttons moved it for the rest of
> the session and the next run started at 100% again.


## `Editor._editor_page`

**line 248** — before `self.sync_pad.setFixedWidth(max(T.px(300),`

> Wide enough for its own labels before it is any particular width:
> the pad is a grid of buttons whose text grows with the type scale
> and with whatever key each one is bound to, and a width fixed in
> raw pixels cut "previous word  (A)" in half the moment either
> changed.

**line 258** — before `self.bar = SyncBar()`

> Between the strip and the words: near enough to the lyric that the
> eye can be on the words while the hand is on the bar, which is the
> whole way this is used.


## `Editor._ribbon_spec`

**line 326** — before `("◀ row", lambda: self.d_step(-1), "Put the row above on the "`

> In this order because the group fills column by column:
> the two arrows want to be one above the other.


## `Editor._transport`

**line 468** — before `self.rate_slider = QSlider(Qt.Orientation.Horizontal)`

> A slider rather than a list of five speeds. Timing a fast line is
> done by finding the slowest speed the words are still WORDS at, and
> that is a different number for every song -- a list makes you try
> 0.75 and then 0.5 and settle for whichever is less wrong, where a
> slider lets you land on the one that works. It detents at 1x,
> because coming back to full speed to listen is the other half of
> the same job and 0.95x by accident is a silent wrong answer.

**line 500** — before `self._vol_quiet = False`

> Timing is done at the volume the singing can be HEARD at, which is
> louder than anybody wants a song for four minutes at a stretch --
> and a local file arrived at whatever the system was set to, with
> nothing in this window to turn it down but leaving it. Both ends
> have a volume, so both get this one control: Qt's output for a
> file, and Spotify's own for Spotify.

**line 507** — before `self._vol_save = QTimer(self)`

> The delay the volume is written down behind. Long enough that a
> turn of the wheel is one write rather than forty, short enough that
> it has happened by the time anybody who moved the slider has
> noticed they did. `closeEvent` fires it early, so a window shut
> inside the delay still keeps where it was left.

**line 537** — before `self.voc_lbl = QLabel("vocal")`

> THE VOCAL, as a thing to listen to rather than a thing to look at.
> Half speed is called the single most useful thing there is for
> placing syllables by hand, a few lines up, and it is useful for one
> reason: it gives the ear more of the consonant to aim at. Taking
> the band away does the same job from the other side. A word start
> buried under a snare at full tempo is plain on the stem, and the
> two compose -- a hard line goes at 0.6x with the backing down.
>
> A slider and not a switch, because the backing is not only noise:
> it is the beat the singer is singing against, and a vocal stripped
> all the way out of its song leaves nothing to place it relative to.
> Where between those two a given line wants to be is a question
> about that line, exactly as the speed is.

**line 566** — before `self._voc_render = QTimer(self)`

> Rendering a blend reads the whole song twice and writes it once, so
> a slider dragged across the bar must not ask for forty of them. It
> renders where the hand STOPS, the way the volume is written down.

**line 602** — before `self.preroll_lbl = QLabel("replay from")`

> Drag sync only: how far before a line the replay starts. An ad-lib
> is caught on a second pass over the same line, so the run-up is the
> difference between hearing it coming and having it already gone.

**line 679** — before `self.offset_lbl = QLabel("")`

> The offset every tap is stamped against, in the open. It is a number
> that decides where each syllable lands and it used to be invisible,
> which is how a file came to carry a correction meant for the
> player's setup rather than for the song.


## `Editor`

**line 750** — before `def key_possible(self, name: str) -> tuple:`

> What cannot be done in the window as it stands, and why. The keys ask
> before firing and the Keys dialog greys the row; the toolbar widgets for
> the same things are disabled beside them, so the two never disagree.
>
> Only real impossibilities belong here -- things the machine or the
> player cannot do at all. "Nothing is selected" is not one of them: those
> actions answer for themselves, with a line saying what to select, which
> is more use than a key that does nothing.


## `Editor.key_possible`

**line 760** — before `if getattr(getattr(self, "player", None), "kind", "") != "local":`

> Spotify plays at one speed and there is no API to ask it for
> another. The slider beside these keys has always been greyed
> for it; the keys went round the back of it and changed the
> speed of nothing.

**line 771** — before `if getattr(getattr(self, "list", None), "mode", "") != "drag":`

> Both act on the row a drag has armed, and outside drag sync
> there is no such thing. Pressed there they would seek the song
> for reasons nothing on screen explains.


## `Editor.fire`

**line 864** — before `line, voice, k = self.list.settle_cursor()`

> The line that is selected has the last word on where this lands.
> See settle_cursor: the cursor and the selection can be in different
> lines, and when they are it is the selection the user is looking at.


## `Editor`

**line 894** — before `def _sweep_ok(self) -> bool:`

> The other way to put times on a row, and the one most people already
> know: play the song and drag across the row as it is sung. Every
> syllable the pointer enters starts there, and the one it leaves ends
> there, so a whole line is timed in one gesture with no holes in it --
> the same guarantee the commit key gives, made with the hand that is not
> on the transport.
>
> What is dragged is the BAR, not the words. A chip is as wide as the word
> it says, and the syllables that most need placing accurately are the
> short ones; the bar gives every syllable the same slice of travel, so an
> even hand makes even timings. The words still light up as the pass goes
> over them -- see `LineList.show_pass` -- because that is where the eye
> is. See `editor/syncbar.py`.
>
> The two halves are split on purpose. The bar knows about slices and says
> which syllable the pointer is on; this half knows about the clock and
> turns that into times. Everything a tapped time goes through applies
> here unchanged: the offset is stamped and watched, the tap lag comes
> off, one undo entry covers the whole pass.
>
> Ad-libs are timed in a pass of their own because a backing voice is a
> row of its own, and only one row is on the bar at a time -- which is
> right, since they overlap in time. Finishing a line that has one arms
> the ad-lib and plays the line AGAIN, so the second pass hears the same
> seconds over and catches the answer where it actually falls.


## `Editor._sweep_begin`

**line 965** — before `if not self.player.playing():`

> A drag against a stopped song would stamp the whole row at one
> instant, so pressing starts the music. The press itself is the
> first syllable's start, which is why the position is read after.


## `Editor._sweep_to`

**line 988** — before `gone = [j for j in range(k + 1, at + 1) if j in s["stamped"]]`

> Wound back over its own tracks. Only what this pass stamped is
> given up: a row being dragged a second time is full of times
> already, and backing up must not quietly throw those away.


## `Editor.set_mode`

**line 1195** — before `self.fit_bars()`

> After the widgets, not before: the transport is a fixed height taken
> from what it holds, and asking for it while two of them are still
> the wrong visibility leaves a gap or a clipped box.


## `Editor.set_source`

**line 1259** — on `                    old.close()`

> stop its polling thread first


## `Editor.open_audio`

**line 1302** — before `self.b_vocal_view()`

> Separating is half a minute the first time and nothing after,
> so this is only a good default for somebody who always wants it
> -- which is why it is a setting and not the behaviour.


## `Editor.load_envelope`

**line 1387** — before `self.wave.vocal = None`

> The separation belongs to the file it was made from. It was
> being left behind on a change of song, which drew one song's
> vocal behind another song's words -- and now that the stem can
> also be PLAYED, a stale one would be a song you could listen to
> that is not the song you are timing.


## `Editor._fill_writers.got`

**line 1502** — on `                return`

> quietly: nobody asked for this

**line 1504** — on `                return`

> a different song is open now


## `Editor._frame`

**line 1851** — before `if self.player.kind == "spotify" and not self.vol_slider.isSliderDown():`

> Spotify's volume is the system's: a media key or the player's own
> slider moves it while this window is open, so this one follows.


## `Editor._linked`

**line 1888** — before `self._push()`

> A player that has just come up is showing the song's own lyrics,
> whatever this window was doing before it went away. flush() only
> re-sends a push that FAILED, and the one before the restart
> succeeded, so without this the screen stayed on the song's own
> copy until the next keystroke happened to push again.


## `Editor._rate`

**line 1899** — on `            self.rate_slider.setValue(100)`

> comes back here, at 1.00

**line 1903** — before `if bool(K.config().get("rate_keep", False)):`

> Only where somebody asked for it: a speed is usually a thing you
> set for one difficult line, and coming back tomorrow to a song
> playing at 0.6x with no memory of asking is worse than setting it
> again.


## `Editor._volume`

**line 1925** — before `if self.player.kind == "local" and bool(`

> Remembered for a local file only. Spotify's volume is the system's
> and belongs to whatever else is using it; writing it down here and
> restoring it on the next run would be this editor reaching out and
> changing something it does not own.
>
> Written behind a delay rather than on the spot. A setting is only
> ever read at the next start, so what it has to be right about is
> where the slider was LEFT -- and `remember` re-serialises the whole
> file, 2.4ms of an editor.json that also holds every syllable split
> anybody has made by hand. A wheel turned across the bar asked for
> forty of those in a second, all but the last of them already
> overwritten.


## `Editor._vocal_ready`

**line 1977** — before `wave = getattr(self, "wave", None)`

> The transport bar is built before the strip it sits above, and it
> asks this on the way up to decide whether to offer the control.


## `Editor._restore_vocal_mix`

**line 2039** — on `            self.voc_slider.setValue(want)`

> comes back through _vocal_mix


## `Editor._vocal_mix`

**line 2052** — before `if v <= 0 or v >= 100:`

> Both ends are files that already exist, so there is nothing to wait
> for and nothing to say -- the swap is immediate and the delay would
> only be felt as lag.


## `Editor._vocal_render.got`

**line 2099** — before `if abs(self.voc_slider.value() / 100.0 - level) > 1e-6:`

> The slider may have moved on while this was rendering, in which
> case this file is not what is being asked for any more -- it is
> kept (it is cached by level, and going back to it is now free)
> and the position now wanted is asked for instead.


## `Editor._player_state`

**line 2158** — before `return`

> A different song is up. The push would be refused, and refused
> once a second for as long as it stayed up.


## `Editor._push`

**line 2197** — before `self.link.push(M.to_ttml(shown), tid,`

> The name the player will credit the words to. It says the file
> where there is one, because that is what the writer is looking at.


## `Editor.info_dialog`

**line 2249** — before `got = self.doc.meta.get(key)`

> A language read back off xml:lang arrives as Language, not as
> the LanguageISO2 the box writes -- so the box showed nothing for
> a file that plainly has one.


## `Editor.b_syllabify`

**line 2574** — before `self.push_undo()`

> just the words that are selected, grouped by the voice they are in


## `Editor.split_dialog.refresh`

**line 2687** — before `seen, uniq = set(), []`

> One row per WORD, not per word per closing mark: "fallin'" and
> "fallin'," are the same word and get the same split, so showing
> both is asking the same question twice and inviting two answers.


## `Editor.b_vocal_view.got`

**line 3291** — before `fit = res.agrees(self._sung_spans())`

> Before anything is drawn: is this audio even this song? A
> picture that is confidently wrong is worse than no picture,
> because the whole point of it is to be believed.
>
> It used to refuse outright. That is the program deciding, and
> it is not the program's to decide: the check is a statistic
> over where the vocal sounds against where the lyric says it
> should, and it is wrong in both directions -- a document timed
> for a radio edit against the album cut disagrees honestly, and
> a lyric with almost nothing timed yet cannot be checked at all
> and gets refused for having nothing to check. So it asks, says
> what it measured, and lets the answer be no.


## `Editor._mark_claims`

**line 3361** — before `self.wave.claimed = got["usable"]`

> The UNBIASED keys: the strip draws the marks vocalmap gave it.


## `Editor.b_from_first`

**line 3388** — before `notes = set(self.wave.vocal.notes())`

> Every note, not only the ones `marks` offers as starts: `from_first`
> reads a speed off them where the document cannot give it one, and
> for that a note beside an attack still says where a syllable is.

**line 3405** — before `self.say("no line here has its first word timed and the rest not"`

> Two different noes, and they send somebody to two different
> places: nothing to work FROM, or nothing to work TOWARDS.


## `Editor.closeEvent`

**line 3577** — before `ev.ignore()`

> the picker was cancelled, or the write failed -- either way
> the work is still only in this window

**line 3582** — before `self._vol_save.stop()`

> Shut inside the write delay. Where the slider was left is still
> only in the window at this point -- see `_volume`.

**line 3587** — before `self.link.unfollow()`

> Give the playback back before the words: this window muted it.

**line 3590** — before `self.link.release()`

> Hand the song back to the player, or it goes on showing a
> document whose editor has closed. Flushed rather than pumped:
> processEvents() here re-enters Qt while this window is being
> taken apart, which aborts the process instead of ending it.


## module level

**line 3617** — before `RATE_MIN, RATE_MAX, RATE_DETENT = 0.25, 2.0, 0.05`

> What the speed slider covers, in multiples of the recording's own speed, and
> how close to 1x counts as 1x. A quarter speed is slow enough to hear the
> front of a consonant in a rapped line and still recognisable as speech;
> double is for skimming an outro nobody is timing. The detent is a twentieth,
> one step of the slider, because full speed is where the ear checks the work
> and 0.95x reached by accident is a wrong answer that makes no sound.

**line 3625** — before `VOL_NOTCH = 5.0`

> How far one notch of the wheel moves the volume, on the 0..100 the slider is
> drawn in. Qt's own answer for a slider is wheelScrollLines x singleStep --
> three units a notch here and fifteen on the speed slider beside it, neither
> of them a number anybody chose. Five is twenty notches from silent to full:
> a flick for a big change, fine enough to settle on a level.
>
> The player moves its own volume bar by the same five points -- see
> LyricsView.VOL_NOTCH -- because it is one gesture, and somebody who has
> learnt it in one window should not find it coarser in the other. Written
> down twice rather than imported: this module does not pull the player in at
> import, and should not start to for one float.


## `VolumeStrip.__init__`

**line 3657** — before `self._owed = 0.0`

> What the wheel has turned so far and not yet spent. A notch is 120
> eighths of a degree and a trackpad sends a handful at a time, so
> without somewhere to keep the remainder a two-finger drag rounds to
> nothing on every event and the volume never moves at all.


## `VolumeStrip.wheelEvent`

**line 3674** — on `        step = int(self._owed)`

> toward zero, so the change keeps its sign


## module level

**line 3700** — before `TAP_LABELS = {"all": "Lines and ad-libs", "lead": "Lines only",`

> Which voices the timing keys walk through, and what each is called.


## `main`

**line 3738** — before `import lyrics_gui as L`

> Before anything else. PyQt turns an unhandled exception inside a slot
> into qFatal(), which aborts the process outright -- so one undefined
> name in paintEvent takes the whole editor down, with a lyric in it and
> no message. The player has had this guard for the same reason; the
> editor holds unsaved work, so it needs it more.


---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/app.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### `Editor.__init__`

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


### `Editor._build`

**line 166** — before `self.keys = K.Keys(self, self._key_handlers())`

> Before the page, because the pad and the ribbon both label
> themselves with the keys. The handlers are late-bound lambdas, so
> they may name widgets the page has not built yet.


### `Editor._editor_page`

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


### `Editor._transport`

**line 439** — before `_shrinkable(self.tap_lbl, 260)`

> It may take room when there is room and give it all back when there
> is not. A minimum here is a floor under the whole WINDOW -- that is
> what a layout minimum means in Qt -- and this label is the least
> important thing in the bar.


### `Editor.fire`

**line 551** — before `pos = max(0.0, self.player.position() - self.tap_lag())`

> The lag comes off here and nowhere else: this is the path a REFLEX
> takes. A time dragged on the strip is placed by eye and needs no
> correction; taking it off there too would move the same times twice.

**line 565** — before `i2, v2, k2 = self.list.cursor`

> The commit key: this word's end IS the next word's start, so
> a line tapped through comes out with no holes in it.


### `Editor.take_doc`

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


### `Editor.show_import`

**line 764** — before `gone, self._import_window = self._import_window, None`

> Kept alive past exec() and dropped on the next turn of the loop.
> Letting Python drop the last reference here destroys the dialog --
> and the StartPage inside it -- while that page's own `loaded` signal
> is still on the stack, which is a use-after-free, not an exception:
> "Replace the lyric" took the whole application down with it.


### `Editor.save`

**line 811** — before `other = self._names(self.path) or self.path.name`

> The last line of defence. Even with the path cleared on every
> import, a window can end up pointing at a file that holds a
> different song -- and a lyric that took an hour to time is not
> something to overwrite on a keystroke without a word.

**line 827** — on `            if got == QMessageBox.StandardButton.SaveAll:`

> "Save as…"


### `Editor._same_song`

**line 864** — on `            return True`

> unreadable: not our business


### `Editor._autosave`

**line 889** — on `            return`

> nothing has moved since the last one


### `Editor.recover_dialog`

**line 935** — before `doc, said = read_lyric(str(it.data(Qt.ItemDataRole.UserRole)))`

> Opened WITHOUT its path: a recovered copy is not the file it came
> from, and saving it should ask where it goes.


### `Editor.do`

**line 956** — on `                self._undo.pop()`

> nothing happened; drop the snapshot


### `Editor._dragged`

**line 1111** — before `if self.wave._grab and not getattr(self, "_dragging", False):`

> One undo entry per drag, not per mouse move: the snapshot is taken
> when the grab starts and the moves after it fold into it.


### `Editor.split_dialog.corrected`

**line 1511** — before `if item.column() != 1:`

> Deferred, every path out: this runs from itemChanged, and
> refresh() rebuilds the very rows the signal came from. Doing it
> inline deletes the item mid-signal, which is a segfault, not an
> exception.


### `Editor.b_split_word`

**line 1598** — before `self.push_undo()`

> The snapshot comes first because _split_prompt applies the split
> itself; do(None) drops it again if the dialog was cancelled.


### `Editor.model_dialog`

**line 1892** — on `        self.engine = None`

> a different model, loaded fresh


### `Editor.b_auto`

**line 1913** — before `device = "cpu" if self.args.device == "cpu" else (`

> The device the player is set to, not this window's argparse default:
> they were disagreeing about the machine as well as the model.


### `Editor.b_auto.job`

**line 1934** — before `say("fetching a copy to listen to…")`

> Spotify will not hand over the sound, so the aligner's own
> copy is fetched -- the same one, kept in the same place, as
> when the player aligns a song by itself.


### `Editor.closeEvent`

**line 1981** — before `self.link.release()`

> Hand the song back to the player, or it goes on showing a
> document whose editor has closed.


### `_scroller`

**line 2000** — before `area.setStyleSheet(f"QScrollArea {{ background: {T.INK_0}; }}")`

> Type-scoped, or it lands on every child: an unselectored rule is
> applied to descendants too, which repainted the primary buttons inside
> these bars with the window's background and left their dark labels
> invisible on it.
