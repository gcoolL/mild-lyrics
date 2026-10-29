# `editor/app.py`

Comments lifted out of `editor/app.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## 2026-10-19 — in the media controls while timing a file (`editor/mpris.py`)

While a local audio file is open the editor is on the session bus as org.mpris.MediaPlayer2.ttml_editor, "TTML Editor" (DesktopEntry ttml-editor): title/artist as `_audio_meta` finds them, play/pause, seek, volume, the playback rate. It is `mpris_player.Mpris` with an adapter shaped like the player's LocalPlayer; `Mpris` now takes a name/identity/desktop, `skips=False` (no Next/Previous), reports `Rate`, and says `Seeked` when the position jumps inside the app (a line click). The player never follows that name (`mpris_player.OWN`). Not published offscreen or with MILD_NO_MPRIS=1. Checked on a `dbus-run-session` bus driven from a second process.
Also: `--title`, `--artist`, `--fetch` on the command line, for "Time in the editor" from the player's Song page.

## Lift — 2026-10-25

Docstrings shortened in `editor/app.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The TTML Editor's window: the lyric line per line, and the audio under it.
>
> The shape is AMLL's, because AMLL's is right: a ribbon across the top for what
> you can do, and under it the whole lyric as a list of lines you can point at,
> one under the other. A word is a chip; a chip carries its own time; the same
> click that selects a word to rewrite selects it to time.
>
>     ribbon      Edit | Timing | Drag sync | Preview, and the mode's buttons
>     transport   play, clock, speed, and what the player is doing
>     waveform    a strip that folds away when it is not wanted
>     the bar     in drag sync only: the armed row as slices to drag across
>     the lyric   line per line, chips per syllable, times down the right
>
> There are four modes and they only decide what is SHOWN. The timing keys work
> while writing words and the word menu works while timing -- a mode that took
> things away would just be the two small tabs again with bigger buttons. Drag
> sync is the one exception, and only over the mouse: the left button there is
> the gesture, so it cannot also be picking rows up and carrying them about.
>
> Everything that changes the document goes through `do()`, so undo is one stack
> of snapshots and the live push to Mild Lyrics happens in exactly one place.

### `Editor._editor_page`

**line 227** — from the docstring, `def _editor_page(self) -> QWidget:`

> The editing page: the same widgets in either interface.
>
> Built once. `_lay_page` puts them in the classic arrangement -- the
> ribbon, the long transport row, the strip, the list -- or the new one,
> which is the player's: a slim toolbar, the transport as a pane of
> glass, and the strip and the list as panes of their own.

### `Editor._fill_toolbar`

**line 487** — from the docstring, `def _fill_toolbar(self) -> None:`

> The two or three commands each mode uses most, and ▾ for the rest.
>
> Every mode's set is built at once, a page each in a stack, and the
> mode only turns the page. A stack is as wide as its widest page, so
> the toolbar asks for the same room in every mode: built afresh for
> each, Edit's seven controls set a wider floor under the window than
> Preview's two, and picking a mode resized the window.

### `Editor._transport`

**line 993** — from the docstring, `def _transport(self):`

> Every control on the transport bar, made once.
>
> Made once and laid out twice: the classic interface puts them in one
> long scrolling row, as it always has, and the new one puts the
> playback controls in a pane of their own and moves what is set once
> -- the tap lag, the replay run-up, the text size -- into Settings.
> `_classic_items` is the classic row, in order; `_lay_transport` is
> what puts them, or the new arrangement, on screen.

### `Editor._file_actions`

**line 1216** — from the docstring, `def _file_actions(self) -> None:`

> The file shortcuts, with no menu bar to hang them off.
>
> A menu bar here would be exactly the thing the ribbon replaced: four
> words in nine-point type in the top-left corner, holding the same
> commands the ribbon already shows at a size that can be read and hit.
> The keys still work, because a shortcut nobody can see is still worth
> having.

### `Editor.retip`

**line 1395** — from the docstring, `def retip(self) -> None:`

> Put today's keys back into the buttons that name one.
>
> `TIP_KEYS` is the buttons whose tooltip ends in a key. They used to
> name the key in the text itself, so a button went on saying (R)
> long after R had been given to something else -- a tooltip that is
> wrong about the one fact it exists to carry is worse than one that
> carries no key at all. The names in it are actions; a spelling like
> `Ctrl+S` is one of the window's own, which cannot be rebound.

### `Editor._repalette`

**line 1440** — from the docstring, `def _repalette() -> None:`

> Push the palette into the modules that cached it.
>
> The painted widgets take their colours once, at import, because they
> are asked for per chip and a dictionary lookup per chip is not free.
> That is the right trade and it costs this: a colour somebody has just
> chosen has to be handed to them.

### `Editor._repeat_after_tap`

**line 1586** — from the docstring, `def _repeat_after_tap(self, line: int, voice: int, k: int) -> str | None:`

> A tap that opened a line sung earlier: time the rest from there.
>
> Only the lead's FIRST syllable, and only while nothing else in that
> lead has a time -- tapping through a line somebody is correcting by
> hand must never have the correction swept away under them. The
> cursor then goes on to the first thing after the line that still
> wants a time, so the next Commit starts it.

### `Editor._run_after_tap`

**line 1616** — from the docstring, `def _run_after_tap(self, line: int) -> str | None:`

> A tap that opened a line of a grouped run: time the whole run.
>
> The same guard as a single line's, over the run: nothing in it timed
> but the syllable just tapped, ad-libs included. Any line of the run
> will do, not only its first -- a tap that missed the opening line
> still knows where the run is, and the lines before it are filled from
> the same shift. The cursor then goes to the first thing in the run
> that is still untimed -- an ad-lib this chorus has and the one it was
> copied from did not -- and past the run where there is none.

### `Editor.fill_bar`

**line 1734** — from the docstring, `def fill_bar(self) -> None:`

> Put the armed row on the bar, with the line's span behind it.
>
> Only in drag sync. It is called from refresh(), which is every edit
> there is, and laying the bar out again on each of them in a mode
> where it is not even on screen is work for nobody. Entering the mode
> fills it, and so does arming a row.

### `Editor.advance_drag`

**line 1807** — from the docstring, `def advance_drag(self, line: int, voice: int, said: str = "") -> None:`

> Arm whatever wants timing next, and play the line again if what
> wants it is inside the line just finished.
>
> This is the whole ad-lib answer in a handful of lines. The drawn order
> puts a line's backing voices directly after the words they answer, so
> the next row wanting times after a lead IS that line's ad-lib -- and a
> row inside the line just finished can only be asking for seconds that
> have already gone by, so they are played again.
>
> Past the last row it starts again from the top rather than stopping,
> because "nothing after this" and "nothing left to do" are different
> answers and only one of them is worth saying.
>
> A row the pass did not finish keeps the bar, so that letting go
> early -- which is how a drag is corrected -- carries on where it
> stopped instead of abandoning the line.

### `Editor.stamp_offset`

**line 1895** — from the docstring, `def stamp_offset(self) -> float:`

> The offset the clock is running on, remembering what it has been.
>
> Every time placed in this session is stamped against `position()`,
> which is already lyric time -- the offset has been taken off. So the
> document never carries it, which is the whole point. What CAN go wrong
> is the number changing while a song is half timed: the two halves are
> then stamped against different clocks, and no single shift puts the
> file right again. That cannot be repaired after the fact, so it is
> reported the moment it happens.

### `Editor.set_source`

**line 2052** — from the docstring, `def set_source(self, kind: str) -> None:`

> Swap what the words are being timed against.
>
> A no-op when nothing changes, because rebuilding a player throws away
> everything it holds -- the file it has open, where it is in it,
> whether it is playing. The import window was doing exactly that by
> accident: a fresh StartPage's combo starts on "Spotify", so telling
> it which source is really in use fired currentTextChanged, and the
> local audio was silently unloaded while the waveform stayed on screen
> looking fine.

### `Editor.fetch_audio`

**line 2113** — from the docstring, `def fetch_audio(self, then=None, ask=None) -> None:`

> Find a copy of this song to time against, and open it.
>
> The one job the editor could not do for itself. Everything it needs
> is already to hand -- the title and artist off the document or the
> player, the length, and the WORDS, which is what turns a search into
> a check: `sources.fetch_audio` plays each candidate to a speech model
> and throws away the ones that are not saying this lyric.
>
> `then` is called when the errand is over, with the path or "" --
> both ways, not only when it works. A caller that greys a button out
> for the duration has to get it back when there was no copy to be
> found, which is the commoner of the two outcomes.
>
> `ask` is what somebody typed to search for -- the start page's Title
> and Artist boxes -- and wins over what the lyric says about itself.
> It used to be written into the lyric only where the lyric said
> nothing, so a TTML that named its song (every multiplayer one does:
> the host's names come with it) searched for its own names whatever
> the boxes said.

### `Editor._audio_meta`

**line 2227** — from the docstring, `def _audio_meta(self) -> dict:`

> Which song to go looking for.
>
> Three places, in order of how much they are worth: what the file says
> about itself, what the player is playing, and the FILENAME. The last
> one is not a fallback nobody hits -- most of the lyrics in this
> project carry no Title or Artist at all in their header, and are
> named `Artist - Title.ttml` on disk, which is exactly the two fields
> a search wants. `_song_name` already reads it that way for the
> backups; this reads it the same way and splits it.

### `Editor.ask_inline_adlibs`

**line 2288** — from the docstring, `def ask_inline_adlibs(self, doc) -> None:`

> Ask what to do with ad-libs written between a line's words.
>
> "You (Okay) must (Uh) find (Your mind)" is one line whose ad-libs are
> sung in the gaps; the editor keeps a line's ad-libs as voices of their
> own, and there is no telling where the person wants them. So each such
> line is shown with a box holding the usual answer -- one ad-lib at the
> end, "You must find (Okay, uh, your mind)" -- to keep or retype.

### `Editor.take_doc`

**line 2349** — from the docstring, `def take_doc(self, doc, said: str, append: bool = False,`

> A document from the start screen or the import window.
>
> Replacing the lyric replaces everything that belonged to the old one:
> the file it was saved to, its title and artist, its songwriters, and
> the Genius song it was matched to. None of that describes the new
> song, and two of them do real damage -- a stale path means Ctrl+S
> overwrites a finished sync with a different song's words, and
> inherited songwriters put the wrong names in the file.

### `Editor._check_language`

**line 2382** — from the docstring, `def _check_language(self) -> None:`

> Overrule a provider's language guess where the words disagree.
>
> These arrive wrong in one specific way and it is always the same:
> an English lyric filed under a small Latin-script language. It is not
> cosmetic -- it chooses the hyphenation patterns words are cut into
> syllables with, and it goes into the file as xml:lang.

### `Editor._fill_writers`

**line 2401** — from the docstring, `def _fill_writers(self, tries: int = 0) -> None:`

> Look the songwriters up as soon as there is a song to look up.
>
> They are part of the file and they never change, so there is no
> reason to make somebody open a dialogue and press a button for them at
> the end of an hour's work. Nothing already in the file is touched:
> a name a writer typed, or one the source carried, is the answer.
>
> The worker takes one errand at a time and the fetch that brought this
> document in may still be winding down, so this waits its turn rather
> than being refused.

### `Editor.refresh`

**line 2851** — from the docstring, `def refresh(self, relayout: bool = True) -> None:`

> Redraw, and tell the player about it.
>
> The push lives here rather than in do(), because do() is only ONE of
> the ways the document changes. Opening a file, undoing and redoing all
> came through refresh() and never reached the player -- so the words on
> screen there were whatever the last edit had been, and it looked like
> the link dropping messages at random.

### `Editor.schedule_push`

**line 2880** — from the docstring, `def schedule_push(self) -> None:`

> Ask for a push soon, without ever putting one off.
>
> This used to restart push_timer on every edit, which is a debounce --
> and a debounce starves under precisely the work this window exists
> for. Tapping syllables through a fast line puts an edit in every
> 120ms or so, and each one pushed the send another 180ms into the
> future, so nothing at all reached the player until the writer stopped
> to breathe. The sync was updating in real time everywhere except on
> the screen it was being watched on.
>
> A countdown already running is therefore left alone: the push goes at
> the end of it and carries whatever the document says by then, so the
> player is never more than PUSH_MS behind however fast the tapping is.

### `Editor._follow_tick`

**line 3032** — from the docstring, `def _follow_tick(self, moved_only: bool = False) -> None:`

> Tell the player where the local file is, so it draws the words there.
>
> Mild Lyrics draws against SPOTIFY's clock unless it is told
> otherwise, so a file timed against a local copy of the song swept
> past wherever Spotify happened to be sitting, which is usually nought.
> The one screen meant to show the work in place was the one screen
> that could not. The player now takes this as the clock for the
> document this window pushed -- see its follow_editor -- and walks its
> own Spotify along underneath, muted, where it can.
>
> Only for a local file: timing against Spotify, the player IS the
> clock and there is nothing to tell it. And only while the document is
> being shown there at all, since this asks it to take hold of
> somebody's playback and that is not a thing to do unasked.
>
> The stop is sent as deliberately as the rest. The player hands the
> playback back on its own if this window goes silent, but that costs
> it a second or two of muted playing first, and switching to Spotify
> or unticking the box is not a crash.
>
> `moved_only` is the frame timer's call, between the regular ticks:
> it says something only when the file has gone somewhere the last
> message would not have carried the player to -- a seek, a nudge, a
> pause, a change of speed. Left to the tick, the player drew the old
> place for up to a tenth of a second after every jump, which is the
> whole of what a writer nudging a syllable is watching.

### `Editor._player_state`

**line 3067** — from the docstring, `def _player_state(self, got: dict) -> None:`

> Put this document back when the player has stopped showing it.
>
> The player lets a pushed document go whenever it reloads its own -- R
> does that, and so does anything else that calls reset_track -- and it
> has no way to ask for it back. Left to the next edit, the screen sat
> on the song's own lyrics for as long as the writer happened not to
> type, which reads as the link having quietly died. Every state row
> says whether what is up there is ours, so this notices within one.
>
> The checkbox is still the switch: turn "Show in Mild Lyrics" off and
> nothing here pushes anything, which is the way to hand the song back
> for good.

### `Editor._player_asked`

**line 3083** — from the docstring, `def _player_asked(self, got: dict) -> None:`

> A seek or a pause made in Mild Lyrics, for the file timed here.
>
> While it draws this window's document against this window's file, the
> player's own controls -- clicking a line, the bar, the arrow keys,
> space -- are about THIS file, and it says so rather than moving a
> Spotify nobody is listening to. Timing against Spotify it never asks:
> it moves Spotify, and this window follows Spotify.

### `Editor._push`

**line 3108** — from the docstring, `def _push(self) -> None:`

> Show the player what has been timed so far.
>
> Only the timed lines go: see model.timed_only for why. Nothing at all
> goes while nothing is timed -- a static block over the song's own
> lyrics is worse than not touching the player, and there is nothing to
> watch sweep yet either.
>
> The track id travels only when timing against Spotify. That is what
> lets the player refuse a document meant for a different song; from a
> local file there is no id to check against, and the player takes it
> for whatever it has open, which is the point of pushing at all.

### `Editor.apply_text`

**line 3358** — from the docstring, `def apply_text(self, text: str) -> None:`

> Take edited text back into the document, keeping what still fits.
>
> Compared ROW by row, the whole row -- voice mark and brackets
> included. Matching on the lead's words alone read "Line" turned into
> "Line (Ad-lib)" as no change at all, kept the old line, and the
> ad-lib that had just been typed was thrown away.
>
> A row that did not change is the old line exactly as it was: its
> times, and its shape -- an ad-lib given a row of its own stays one.
> A row that did is read afresh, and each of its words takes the times
> of the same word in the rows it replaced, so adding an ad-lib to a
> timed line costs the line nothing. A row of brackets alone that was
> typed or changed is the ad-lib of the line above it.

### `Editor.run`

**line 3408** — from the docstring, `def run(self, job, done, lane: str = "main") -> bool:`

> An errand on a thread that cleans itself up; one per `lane`.
>
> Returns whether it started, the way `run_quiet` already does. A
> caller that greys a button out for the duration needs to know it was
> turned away, or the button never comes back.
>
> The lanes are kinds of errand that have nothing to wait for from each
> other. There used to be one slot for everything, so a download of the
> song -- a minute or more -- turned away "From Genius" and every other
> lyric lookup with "still busy with the last one" until it was done.
> Fetching the words and fetching the audio now go side by side: "audio"
> and "lyrics", and "main" for the rest. Two of the same kind still
> queue behind each other, which is the point of having a slot at all.
>
> The lane is given back BEFORE `done` runs, not when the thread gets
> round to stopping. `quit` only asks; a follow-up started from inside
> `done` -- the download done, so read the file it made -- found the
> thread still winding down and was refused.

### `Editor.run_quiet`

**line 3438** — from the docstring, `def run_quiet(self, job, done) -> bool:`

> A background chore, on a slot of its own. Returns whether it started.
>
> Nothing here was asked for, so it must never be in the way: taking
> the one worker thread would mean somebody pressing "From Genius" a
> second after importing got "still busy with the last one" for an
> errand they did not ask for and cannot see. It also says nothing on
> the way -- a chore that narrates itself is just noise over the
> status line somebody is reading for their own work.

### `Editor.b_move`

**line 3523** — from the docstring, `def b_move(self, delta: int) -> None:`

> Up and down. On a backing voice that means among its neighbours.
>
> The moved lines stay selected, and the cursor goes with them. They
> did not before, so the selection sat still while the lines slid past
> it: pressing ↑ twice moved one line up and then a DIFFERENT line up,
> which is never what anybody means by pressing it twice.

### `Editor.remember_word`

**line 3925** — from the docstring, `def remember_word(self, line: int, voice: int, syl: int) -> None:`

> Keep how this word was split, so the next song spells it the same.
>
> A split made by hand is a decision about the word, not about this one
> line of this one song -- the automatic split learns it the same way a
> correction typed into its dialogue does. A word taken back apart, or
> undone, forgets it again: the store always says what the word looks
> like now, never what it looked like once.

### `Editor._picked_words`

**line 3977** — from the docstring, `def _picked_words(self) -> list:`

> The words that are selected — more than one, or nothing.
>
> One selected word is the ordinary case and stays the cursor's job:
> the word operations mean subtly different things on a single word
> (join with the NEXT one) than on a run (join these together), and
> quietly changing which one a single click gets would be worse than
> the bug this fixes.

### `Editor.keep_whole`

**line 4013** — from the docstring, `def keep_whole(self, phrases: list[str]) -> None:`

> Keep these phrases from being cut back up by the automatic split.
>
> Not remember_word, which is about where a word comes apart -- this is
> the other kind of decision the same store holds: a kept split of ONE
> piece, which says leave it alone. Without it, "Syllabify" would undo
> every glue on the line, because a piece spelling two words is exactly
> what it exists to cut apart when a SOURCE hands one over ("do your",
> "let 'em"). Deliberate here, incidental there, and only the person who
> pressed the button knows which.
>
> It carries to the next song for the same reason a hand split does:
> "Est-ce que" is sung as one wherever it is sung.

### `Editor.cache_dialogue`

**line 4114** — from the docstring, `def cache_dialogue(self) -> None:`

> Every cache, its size, and a button to clear it.
>
> The sizes are the whole point. A cache nobody can see is a cache
> nobody clears, and the animated covers alone reach three quarters of
> a gigabyte on a machine that has done nothing unusual.
>
> The two the inventory marks `keep` are shown with a warning and are
> left out of "clear everything": one is work this machine did and the
> other is the backup net under this very editor.

### `Editor._vocal_ready`

**line 4213** — from the docstring, `def _vocal_ready(self) -> str:`

> The song whose separated vocal is on disk, or "".
>
> Both halves have to be true. `wave.vocal` says this window has the
> separation open -- the answer to "when vocals are separated" -- and
> the stem file says the audio of it was kept, which a map made before
> this existed did not do. A song separated by an older build has its
> picture and no sound, and turning the vocal view on again is what
> gets it; `VocalMap._read` refuses such a map so that happens by
> itself.

### `Editor._restore_vocal_mix`

**line 4258** — from the docstring, `def _restore_vocal_mix(self) -> None:`

> Put the slider back where it was left, now that it can move.
>
> Only on a song that has just been separated, and only where the
> setting is not 0 -- so somebody who timed a hard verse with the band
> at a quarter gets it back on the next song without asking, and
> somebody who has never touched it sees nothing happen. It is said out
> loud either way: what is coming out of the speakers is not what the
> file sounds like, and that is not a thing to change silently.

### `Editor._mark_claims`

**line 4509** — from the docstring, `def _mark_claims(self) -> None:`

> Work out which marks the document can account for, for the strip.
>
> Recomputed with the document because moving one word changes which
> marks are contested -- a mark that two syllables were both near stops
> being contested the moment one of them moves away. Cheap enough to do
> on every edit (a few hundred marks against a few hundred syllables)
> and only done while the marks are on screen.

### `Editor.vocal_report`

**line 4525** — from the docstring, `def vocal_report(self) -> None:`

> What the vocal does and does not say about this document.
>
> This used to offer to move words onto the marks, and it should not
> have. The marks are not consistent enough to edit with: on the file
> this was built against, the same word sung again gets a mark in some
> repeats and not others, and where it does the offset varies by up to
> 130 ms -- see `ops.consistency`, which is measured here per song and
> put at the top of this window rather than buried in a docstring.
>
> So nothing in this dialogue changes a timing. It answers three
> questions instead, which is what the picture is actually good for:
> how far can the marks be trusted on THIS song, which marks are too
> ambiguous to read, and which words are sitting nowhere near anything
> the singer did. The tool for moving words is Time selection, which
> knows the lyric and can therefore tell a `sane` from a `she`.

### `Editor.b_from_first`

**line 4630** — from the docstring, `def b_from_first(self) -> None:`

> Time the lines whose first word somebody has already placed.
>
> Only those. A line with nothing timed has no anchor to work from and
> a fully timed line has nothing to ask for, so both are passed over
> rather than refused -- the selection is usually a verse and this is
> the one thing in it that applies.

### `Editor.b_roman_genius`

**line 4742** — from the docstring, `def b_roman_genius(self) -> None:`

> Genius' romanised lyric, lined up with these words, shown first.
>
> Found the way the player finds it (genius_roman.find_romanisation),
> and lined up by the same alignment: each of our lines is read with
> the romaniser, and the Genius lines are matched against those, in
> order, so a line is never given another line's reading. What would
> change is listed before anything is taken, one tick each.
>
> A line that already HAS a reading is not passed over any more. That
> reading is usually the romaniser's, and the romaniser is exactly what
> Genius is better than -- a particle read as written, a long vowel
> lost, a word run into the next. Where the two disagree (past case,
> spacing, punctuation and accents) the line is listed as a correction,
> and taking it puts the reading right in place: see
> ops.correct_reading, which keeps each syllable carrying its own piece.
> Readings typed by hand are listed the same way and can be unticked.
>
> Which page is read is asked first (GeniusRomanFind): the automatic
> pick as before, a page searched for by hand, or a pasted link -- for
> when the automatic pick is the wrong song or the wrong version.

### `VolumeStrip`

**line 4992** — from the docstring, `class VolumeStrip(QWidget):`

> The word "volume", the slider and the readout, as one wheel target.
>
> Together rather than the slider alone because a wheel is aimed no better
> than a click is, and the slider is a hundred pixels inside a bar that runs
> the width of the window. The player hit-tests its own volume bar with
> eight pixels of slack around it for the same reason.
>
> Neither half of that relies on Qt walking an ignored wheel up the parent
> chain, because it does not do that for widgets the way it does for a key:
> a wheel stops on whatever it lands on. So the labels are made transparent
> to the mouse -- they are decoration and have no use for one -- and the
> slider, which still has to be dragged, hands it over by name.

### `VolumeSlider`

**line 5018** — from the docstring, `class VolumeSlider(QSlider):`

> The volume slider, with the wheel handed to the strip around it.
>
> By name rather than by ignoring it: an ignored wheel does not walk up to
> the parent, so leaving it to Qt would mean the gesture did nothing over
> the one part of the strip everybody aims at. Qt's own handling is not
> wanted either -- it is wheelScrollLines x singleStep, three units a notch
> here and fifteen on the speed slider beside it -- so there is one place
> that decides what a notch is worth, and this is not it.

### `_shrinkable`

**line 5033** — from the docstring, `def _shrinkable(label: QLabel, most: int) -> None:`

> Let a label give up its width when the window is narrow.
>
> A QLabel's minimum size hint is the width of its text, and every such
> hint adds up into a floor under the window -- which is how a tool whose
> largest control is a lyric ended up refusing to be less than 1450px wide.
> These are all captions; clipping one costs nothing.

### `Caption`

**line 5041** — from the docstring, `class Caption(QLabel):`

> A one-line label that says what it can and is never a floor.
>
> For text that changes while the window is open -- the song's title, what
> the link is connected to. A plain QLabel's minimum is its whole text, so
> each new song or link state could push the window wider, and a window
> never shrinks by itself: it only ever grew. `_shrinkable` answers the
> same thing with an Ignored policy, which beside a stretch can squeeze a
> label down to nothing; this one still asks for its full width and is
> cut short with an ellipsis only when there is not that much to give.

---

## Lift — 2026-10-11

Comments lifted out of `editor/app.py` on 2026-10-11, from PR #2 as it was reviewed; the line numbers are that day's.

### `Editor.b_merge_lines`

**line 3611** — before `self.do(self.list.merge_selected(sel))`

> Through the list, which also moves the selection onto the merged
> line -- ops.merge_runs on its own left the old (line, voice) pairs
> naming whatever slid into those indices. See LineList.merge_selected.


---

## Lift — 2026-09-26

Comments lifted out of `editor/app.py` on 2026-09-26; the line numbers are that day's.

### `Editor.__init__`

**line 112** — before `saves.ensure()`

> Both rooms of the lyrics folder, made now rather than at the first
> save: somebody who opens this and goes looking for where their work
> will land should find the folder already there, and empty.


### `Editor._transport`

**line 494** — before `self.vol_strip.setSizePolicy(QSizePolicy.Policy.Fixed,`

> Never narrower than its parts: squeezed, the bar laid the readout
> over the slider's groove rather than beside it.


### `Editor._fill_writers.job`

**line 1431** — before `try:`

> Apple's credits are the ones applied; Genius only stands in
> for a song Apple has none for.


### `Editor.split_dialogue.corrected`

**line 2510** — before `parts = [x.strip() for x in item.text().split(" / ") if x.strip()]`

> More than one right way: "bat|tlin' / bat|t|lin'", the usual
> one first. A word keeps its punctuation, so read back loosely.


### `Editor.b_vocal_view.got`

**line 3034** — before `if spans and not fit.get("trusted"):`

> Nothing timed yet is nothing to disagree with: a song opened to
> be timed from scratch is exactly when the view is wanted most.


### `Editor.b_from_first`

**line 3231** — before `vocal = self.wave.vocal`

> With the vocal view open, each word is then moved to the nearest
> thing the vocal actually does; without it the words are only laid
> forward at the speed the lines around this one are sung at, and the
> last one held to where the line ends.


---

## Lift — 2026-09-17

### module level

**line 40** — before `PUSH_MS = 180`

> The most the player is ever left behind what is being typed here. It is a
> rate limit, not a delay -- see schedule_push, which is where the difference
> turned out to matter.


### `Editor.__init__`

**line 128** — before `self._sweeping: dict | None = None`

> The drag in progress, as the WINDOW sees it: where the pointer was
> last, when it was there, and which syllables this pass has stamped.
> The list widget keeps the same pass in chips; this half keeps it in
> seconds. See _sweep_begin.


### `Editor._build`

**line 168** — before `T.scale()`

> Both of these are read from the settings file, and both have to be
> read BEFORE anything is dressed: every metric in the window is
> T.px(), which multiplies by the scale, and every painted colour is
> taken from the palette once at import. The scale was being written
> down and never read back -- the A+ buttons moved it for the rest of
> the session and the next run started at 100% again.


### `Editor._editor_page`

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


### `Editor._ribbon_spec`

**line 326** — before `("◀ row", lambda: self.d_step(-1), "Put the row above on the "`

> In this order because the group fills column by column:
> the two arrows want to be one above the other.


### `Editor._transport`

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


### `Editor`

**line 750** — before `def key_possible(self, name: str) -> tuple:`

> What cannot be done in the window as it stands, and why. The keys ask
> before firing and the Keys dialogue greys the row; the toolbar widgets for
> the same things are disabled beside them, so the two never disagree.
>
> Only real impossibilities belong here -- things the machine or the
> player cannot do at all. "Nothing is selected" is not one of them: those
> actions answer for themselves, with a line saying what to select, which
> is more use than a key that does nothing.


### `Editor.key_possible`

**line 760** — before `if getattr(getattr(self, "player", None), "kind", "") != "local":`

> Spotify plays at one speed and there is no API to ask it for
> another. The slider beside these keys has always been greyed
> for it; the keys went round the back of it and changed the
> speed of nothing.

**line 771** — before `if getattr(getattr(self, "list", None), "mode", "") != "drag":`

> Both act on the row a drag has armed, and outside drag sync
> there is no such thing. Pressed there they would seek the song
> for reasons nothing on screen explains.


### `Editor.fire`

**line 864** — before `line, voice, k = self.list.settle_cursor()`

> The line that is selected has the last word on where this lands.
> See settle_cursor: the cursor and the selection can be in different
> lines, and when they are it is the selection the user is looking at.


### `Editor`

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


### `Editor._sweep_begin`

**line 965** — before `if not self.player.playing():`

> A drag against a stopped song would stamp the whole row at one
> instant, so pressing starts the music. The press itself is the
> first syllable's start, which is why the position is read after.


### `Editor._sweep_to`

**line 988** — before `gone = [j for j in range(k + 1, at + 1) if j in s["stamped"]]`

> Wound back over its own tracks. Only what this pass stamped is
> given up: a row being dragged a second time is full of times
> already, and backing up must not quietly throw those away.


### `Editor.set_mode`

**line 1195** — before `self.fit_bars()`

> After the widgets, not before: the transport is a fixed height taken
> from what it holds, and asking for it while two of them are still
> the wrong visibility leaves a gap or a clipped box.


### `Editor.set_source`

**line 1259** — on `                    old.close()`

> stop its polling thread first


### `Editor.open_audio`

**line 1302** — before `self.b_vocal_view()`

> Separating is half a minute the first time and nothing after,
> so this is only a good default for somebody who always wants it
> -- which is why it is a setting and not the behaviour.


### `Editor.load_envelope`

**line 1387** — before `self.wave.vocal = None`

> The separation belongs to the file it was made from. It was
> being left behind on a change of song, which drew one song's
> vocal behind another song's words -- and now that the stem can
> also be PLAYED, a stale one would be a song you could listen to
> that is not the song you are timing.


### `Editor._fill_writers.got`

**line 1502** — on `                return`

> quietly: nobody asked for this

**line 1504** — on `                return`

> a different song is open now


### `Editor._frame`

**line 1851** — before `if self.player.kind == "spotify" and not self.vol_slider.isSliderDown():`

> Spotify's volume is the system's: a media key or the player's own
> slider moves it while this window is open, so this one follows.


### `Editor._linked`

**line 1888** — before `self._push()`

> A player that has just come up is showing the song's own lyrics,
> whatever this window was doing before it went away. flush() only
> re-sends a push that FAILED, and the one before the restart
> succeeded, so without this the screen stayed on the song's own
> copy until the next keystroke happened to push again.


### `Editor._rate`

**line 1899** — on `            self.rate_slider.setValue(100)`

> comes back here, at 1.00

**line 1903** — before `if bool(K.config().get("rate_keep", False)):`

> Only where somebody asked for it: a speed is usually a thing you
> set for one difficult line, and coming back tomorrow to a song
> playing at 0.6x with no memory of asking is worse than setting it
> again.


### `Editor._volume`

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


### `Editor._vocal_ready`

**line 1977** — before `wave = getattr(self, "wave", None)`

> The transport bar is built before the strip it sits above, and it
> asks this on the way up to decide whether to offer the control.


### `Editor._restore_vocal_mix`

**line 2039** — on `            self.voc_slider.setValue(want)`

> comes back through _vocal_mix


### `Editor._vocal_mix`

**line 2052** — before `if v <= 0 or v >= 100:`

> Both ends are files that already exist, so there is nothing to wait
> for and nothing to say -- the swap is immediate and the delay would
> only be felt as lag.


### `Editor._vocal_render.got`

**line 2099** — before `if abs(self.voc_slider.value() / 100.0 - level) > 1e-6:`

> The slider may have moved on while this was rendering, in which
> case this file is not what is being asked for any more -- it is
> kept (it is cached by level, and going back to it is now free)
> and the position now wanted is asked for instead.


### `Editor._player_state`

**line 2158** — before `return`

> A different song is up. The push would be refused, and refused
> once a second for as long as it stayed up.


### `Editor._push`

**line 2197** — before `self.link.push(M.to_ttml(shown), tid,`

> The name the player will credit the words to. It says the file
> where there is one, because that is what the writer is looking at.


### `Editor.info_dialogue`

**line 2249** — before `got = self.doc.meta.get(key)`

> A language read back off xml:lang arrives as Language, not as
> the LanguageISO2 the box writes -- so the box showed nothing for
> a file that plainly has one.


### `Editor.b_syllabify`

**line 2574** — before `self.push_undo()`

> just the words that are selected, grouped by the voice they are in


### `Editor.split_dialogue.refresh`

**line 2687** — before `seen, uniq = set(), []`

> One row per WORD, not per word per closing mark: "fallin'" and
> "fallin'," are the same word and get the same split, so showing
> both is asking the same question twice and inviting two answers.


### `Editor.b_vocal_view.got`

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


### `Editor._mark_claims`

**line 3361** — before `self.wave.claimed = got["usable"]`

> The UNBIASED keys: the strip draws the marks vocalmap gave it.


### `Editor.b_from_first`

**line 3388** — before `notes = set(self.wave.vocal.notes())`

> Every note, not only the ones `marks` offers as starts: `from_first`
> reads a speed off them where the document cannot give it one, and
> for that a note beside an attack still says where a syllable is.

**line 3405** — before `self.say("no line here has its first word timed and the rest not"`

> Two different noes, and they send somebody to two different
> places: nothing to work FROM, or nothing to work TOWARDS.


### `Editor.closeEvent`

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


### module level

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


### `VolumeStrip.__init__`

**line 3657** — before `self._owed = 0.0`

> What the wheel has turned so far and not yet spent. A notch is 120
> eighths of a degree and a trackpad sends a handful at a time, so
> without somewhere to keep the remainder a two-finger drag rounds to
> nothing on every event and the volume never moves at all.


### `VolumeStrip.wheelEvent`

**line 3674** — on `        step = int(self._owed)`

> towards zero, so the change keeps its sign


### module level

**line 3700** — before `TAP_LABELS = {"all": "Lines and ad-libs", "lead": "Lines only",`

> Which voices the timing keys walk through, and what each is called.


### `main`

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

> Deferred for the same reason: accept() unwinds the dialogue's
> event loop, and this is running inside a signal emitted by a
> widget that dialogue owns.


### `Editor.show_import`

**line 764** — before `gone, self._import_window = self._import_window, None`

> Kept alive past exec() and dropped on the next turn of the loop.
> Letting Python drop the last reference here destroys the dialogue --
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


### `Editor.recover_dialogue`

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


### `Editor.split_dialogue.corrected`

**line 1511** — before `if item.column() != 1:`

> Deferred, every path out: this runs from itemChanged, and
> refresh() rebuilds the very rows the signal came from. Doing it
> inline deletes the item mid-signal, which is a segfault, not an
> exception.


### `Editor.b_split_word`

**line 1598** — before `self.push_undo()`

> The snapshot comes first because _split_prompt applies the split
> itself; do(None) drops it again if the dialogue was cancelled.


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

## 2026-10-23 — The editor follows Mild Lyrics' own player

Goal: the TTML editor follows what Mild Lyrics' own player is playing. The editor's "player" source (SpotifyPlayer) kept its own transport, so it saw Spotify, MPRIS or SMTC, and took the window's clock only when both sides agreed on the tid. Mild Lyrics' own player is on none of those. The window keeps it off MPRIS as its own, and Windows has no SMTC for it. So the editor never saw a song played in Mild Lyrics.

- The window's LiveLink `state` now carries `mine` (its own player is the one followed) and `audio` (the current file's path, or the stream link it plays), from `LyricsView.own_player_state`. A new `control` message (PlayPause/Next/Previous) goes through `player_do`, the same way in as the window's keys.
- `SpotifyPlayer._mild()` is that state while it is fresh (LINK_STALE) and `mine`. Then title, artist, track id, length, play state, the clock and the global `base` offset all come from the window. Seek goes over the link as `sec + base − offset`, because the window adds its track offset back. Play/pause goes as `control`. There is no volume slider. `audio_path` is the window's file when it plays one.
- `fetch_audio`: when the window is streaming, the editor saves that very stream (`stream_source.save_stream`, moved from home_page) into AUDIO_DIR's sibling `from-mild-lyrics`, instead of searching. If that fails, it searches as before. A typed search (`ask`) still searches.

Test: tests/test_editor_follows_mild.py (16). test_livelink 78, test_players 167/3 (the known reds), test_time_in_editor 9.

## Hyphens cut on every import (2026-10-26)

With Split after hyphens on, `take_doc` and `open_lyric` cut every import's untimed words after their hyphens. That covers TTML and the other formats, Genius, the player, the chain, pasted text and the import window. It used to be only pasted text and `.txt`. The status line says how many words were cut, and a file opened with cuts is marked unsaved, since it no longer matches the file. Timed words are never cut (`cut_hyphens`). A recovered backup (`cut=False`) is your own work and comes back as it was.

## Tap lag test: built and removed (2026-10-26)

A Settings ▸ Timing button had you tap along to clicks played through the editor's own output, and set Tap lag from the median lateness. It measured key taps placed 70/131/−19/86ms late to within 1ms. In use it gave a different answer every run, and it was taken out. Tapping to a metronome tends to land ahead of it, by more when the clicks are hard to hear, and a metronome is not a singer. Tap lag stays a number set by hand.
