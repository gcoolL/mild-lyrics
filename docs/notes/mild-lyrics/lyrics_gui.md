# `mild-lyrics/lyrics_gui.py`

Comments lifted out of `mild-lyrics/lyrics_gui.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 158** — before `POLL_MS, POLL_MS_EDGE = 250, 60`

> How often the WINDOW looks at itself: the fetcher, the artwork, the queue,
> the track it thinks is playing. None of that is the clock, and none of it is
> urgent -- a track change reaches it the moment the clock sees one anyway,
> because the sampler pokes it. The edge rate is for a screen still waiting on
> a lyric, which is the one thing here worth retrying quickly.

**line 164** — before `SAMPLE_MS = 16`

> How often the PLAYER is asked where it is -- every frame, near enough, and
> on a thread of its own. See Pump.
>
> This is the whole of the delay on anything the player does that cannot be
> predicted from here. A seek made in Spotify's own window is invisible until
> the next reading: the clock carries the old position forward at 1x straight
> through it, so the gap between readings is exactly how long the wrong line
> stays up. It also sets how long after an unpause the words move at all --
> the audio is back 46ms after the play command and resumes ~0.16s beyond the
> parked reading, and at 250ms that left them 0.31s behind the voice with a
> visible flicker as they caught up.
>
> Spicy Lyrics samples every frame and that is the reason a seek never shows
> there. The number is affordable for the same reason it is affordable inside
> the page: a reading is 0.28ms down the debug port (median of 200, an idle
> renderer), so sixty a second is under 2% of one core, and none of it is on
> the thread that draws.

**line 182** — before `WARM_LOOK = 0.25`

> How often the look-ahead looks up to see whether the fetcher is free, and
> how long it will wait there before deciding its queue has gone stale. The
> patience matches the queue scan's own minute: waiting longer than the thing
> that rebuilds the list cannot buy anything.

**line 189** — before `RESUME_SETTLE = 1.0`

> How long after an unpause the player is still settling; see the slew
> guard in Clock.poll for what arrives inside this window.

**line 192** — before `RESUME_STEP_FLOOR = 0.06`

> Under this, a forward step across a resume is the measurement, not a leap:
> the poll interval, the status arriving a moment after the audio did, the
> engine's own few ms of quantisation. Charging those to the words puts them
> permanently behind the voice, which is the whole failure this guards. A
> player that really does step its clock at an unpause steps it a quarter of a
> second -- Spotify's own is 0.253s over the control state -- so there is an
> order of magnitude between the two and nothing that matters is lost by
> insisting a leap clear this first.

**line 265** — before `RESUME_MEASURE = 2.0`

> How long the leap goes on being measured for. Longer than RESUME_SETTLE,
> which is what the SEEK test and the slew are timed against and must not move:
> this is only the window the displacement is read over. Measured on Spotify
> over the debug port the leap does not always arrive promptly -- on two
> unpauses in seven it was still climbing at 0.7s and had not finished by 1.0s,
> so the old window shut on a half-measured leap and carried that instead.
> Safe to run long only because what it reads is a displacement from the resume
> and not a running total: past the leap it stops changing, and a seek in here
> is caught by `jumped` and clears the bias outright.

**line 276** — before `FRAME_IDLE_HZ = 10.0`

> The frame rate while the window is not on a screen -- minimised, or on
> another virtual desktop. Not zero: the clock still has to drift, the settings
> still have to be written, and a SIGTERM arriving at a hidden window still has
> to close it. Nothing here is drawn, so this only has to be often enough that
> those three stay responsive.

**line 284** — before `UNPAUSE_DELAY = 0.25`

> A ceiling, not a duration. Spotify's reported position leaps forward when it
> is unpaused -- measured at 0.253s, within 30ms of the command, sd 0.005 over
> 24 unpauses -- and then advances with the clock and never gives it back. The
> leap is read from the player each time rather than assumed, and carried for
> as long as that stretch of playback lasts; this is as much of it as will be
> taken. Over the session bus there is no leap and nothing is subtracted, so
> the number only bites where it applies.
>
> 0.25 covers the measured leap with nothing to spare. Lower it and the words
> keep some of the leap and run ahead of the voice; 0 disables the correction
> entirely. Unlike the duration this replaces, a wrong value here lasts until
> the next seek or track change rather than a quarter second, so it is worth
> setting by ear on a song you know well.

**line 303** — before `SAY_DRIFT = 0.25`

> How the live link keeps the editor's clock: say something whenever the song
> moves in a way the far end cannot have predicted, and say something anyway
> this often, so the reading over there never goes stale enough to be dropped.

**line 310** — before `GENIUS_TYPED_MS = 150`

> How long the search box waits after the last keystroke before it asks
> Genius. The local index answers on every letter -- it is a dictionary
> lookup -- but Genius is a request over the network, and a query typed
> at speed would send one per letter and be answered out of order.

**line 315** — before `TROUBLE_QUIET = 3600.0`

> How long a source that could not be reached is left unmentioned after
> it has been mentioned once. See on_source_trouble.

**line 318** — before `FOLLOW_DRIFT = 0.35`

> Walking Spotify along with an editor that is timing against a local copy of
> the song. See follow_editor. How far Spotify may drift from the file before
> it is put back; how long a transport command is given to take effect before
> another is sent; how long the editor may go quiet before this window
> decides it has gone and hands the player back; how long a SEEK is given
> before another is sent, which is a shorter wait than a command gets and
> _follow_to says why; and how many times the same place is asked for before
> the player is taken at its word that it will not go there.

**line 328** — before `RETRY_MAX = 30.0`

> How far the retry backs off, doubling from RETRY_FIRST each time a walk
> comes back with nothing.
>
> It was two seconds, which is the right pace for the case it was written for
> -- a lyric that is about to exist, a page that has not finished loading --
> and the wrong one for the case it lands in most: a song nobody has a lyric
> for at all. That was a full walk every two seconds for the length of the
> track, ten doors each time, LyricsPlus' twenty-second one among them, to
> ask a question that had been answered the same way every time since the
> song started.
>
> Doubling to half a minute keeps the first few retries where they were --
> 0.3, 0.6, 1.2, 2.4, 4.8 -- so a lyric that shows up shortly is still picked
> up within a second or two of appearing, and a song that genuinely has none
> settles down instead of hammering.

**line 344** — before `SPICY_GRACE = 25.0`

> Spicy Lyrics fetches its own copy inside the Spotify page, and on a song it
> has not seen before that can land a second or two after this window has
> already asked everybody else and put a perfectly good answer up -- and it
> lands twice, a line-level copy first and the word-timed one after it. Keep
> looking for the word timing, so the source the user ranked first is not lost
> to a race it was always going to lose on a cold song.
>
> The looking used to stop after SPICY_GRACE and the song was then stuck with
> somebody else's document until it was played again: Spicy Lyrics' own copy
> can land a good deal later than that -- a slow fetch, a line-level copy it
> upgrades in its own time, or a lyrics view the user only opens halfway
> through -- and every one of those cases ended with two different lyrics on
> two halves of the same screen. So the grace now only sets the PACE: quick
> looks while the copy is most likely to arrive, one every SPICY_SLOW for as
> long as the track stays up. It is a read from the page over a socket this
> thread already holds, which is what makes keeping it up all song cheap.

**line 363** — before `SPICY_HOLD = 1.5`

> ...and how long a load will hold the CREDIT for it before writing somebody
> else's name under the lyrics. The walk is not a race Spicy Lyrics lost, it
> is one it was never in: the chain answers off the disk in a millisecond on
> any song it has been asked about in the last month, while Spicy Lyrics'
> own copy needs one request inside the page -- and it needs it on nearly
> every song, because its cache holds a track for three days and most songs
> are not played twice in three days. So the answer the walk brings back is
> shown at once, as it always was, and then this much is spent looking again
> before it is allowed to be the answer. Nothing waits on screen for it.
>
> Long enough to cover the page's own request -- a few hundred milliseconds,
> and the load is already a beat behind the track change when it starts
> counting -- and no longer, because everything else the fetcher hands over
> on a new song, the artists and the beat among them, waits behind this.

**line 461** — before `SAVE_HOME = _HERE.parent`

> Where saved lyrics go unless somebody says otherwise: the folder holding
> this program, which is the parent of aligner/ -- the checkout, beside the
> two launchers and the editor. It is a real answer on a machine nobody has
> configured, and the same answer whether the window was started from a
> terminal, a .desktop file, a Start-menu shortcut or a double-clicked .pyw.

**line 504** — before `PEOPLE_KEYS = {"people_skip": "whose syncs to refuse",`

> The running order is a list of SOURCES -- who wrote the lyrics -- and not
> of the doors this program knocks on to reach them. Those are two different
> lists, and the old menu was the second one: it offered "Lyrics+", which is
> a scraper that answers from Apple Music, Musixmatch, QQ Music or its own
> submissions depending on the day, and "Apple+QQ", which is not a source at
> all but a reconciliation of two. Ranking those means ranking a route, and a
> route cannot be ranked: whoever put Lyrics+ second was putting Apple Music
> second on one song and Musixmatch second on the next.
>
> So the ten below are the catalogues the words actually come from, and the
> providers underneath are arranged to serve them (see SRC_PARTS).
> The two settings that name PEOPLE instead of sources, and what each list
> is called where it is being typed into. Keyed by the settings key, which is
> also the menu row's key and the editor mode it opens -- one name for one
> thing, so a row cannot open the editor for the other list.

**line 530** — before `TROUBLE_MUTE = {"lyricsplus"}`

> Sources whose failures are never announced, because for them a failure is
> not news.
>
> LyricsPlus is the only one. Its door says "I have not got it" by TIMING OUT
> rather than by 404 -- it is given twenty seconds (LS._HOST_PATIENCE) because
> it takes eight to seventeen to answer anything at all -- so its ordinary
> miss, which is most songs, arrives here indistinguishable from the host
> being down. A "could not reach LyricsPlus" on most tracks is not a warning,
> it is weather, and there is nothing in the answer to tell the two apart.
>
> Only what is SAID is muted. The fault is still recorded and still reaches
> eval_sources, and every document the door does hand over reaches the screen
> exactly as before.

**line 577** — before `SRC_PARTS, BLENDS, BLEND_OF = LS.SRC_PARTS, LS.BLENDS, LS.BLEND_OF`

> The mapping from a source to the providers that answer for it lives with
> the providers themselves, in lyric_sources, because eval_sources has to
> read this same list without dragging a window in behind it.

**line 582** — before `BLEND_LABEL = {"blend": "Apple+QQ", "kublend": "Apple+Kugou",`

> A blend is not a catalogue and cannot be ranked as one -- it is Apple Music's
> lines with somebody else's clock under them -- so it gets a section of its
> own rather than a slot among the sources. Written short because the menu
> sizes its label column from the LITERAL strings in MENU, and the Sources
> rows carry "" there: a long label here would run under the value column
> instead of widening the panel. See _paint_menu.

**line 594** — before `"word_glow": 0.0, "panel": True,`

> The steady halo behind every word, off by default: the glow this
> window has always had is the one the voice carries, and lighting the
> whole column is a different look rather than more of that one.

**line 599** — before `"mesh_style": "blobs", "mesh_tint": 1.0, "mesh_spread": 1.0,`

> How the mesh spends the album's colours. Defaults are the mesh as it
> was: four blobs, at the strength and size they have always had.

**line 608** — before `"merge_ms": 0.0,`

> Off: a document's own splits are shown exactly as it wrote them until
> somebody says otherwise. See merge_flat_splits.
>
> MILLISECONDS, and the key is spelled differently from the fraction it
> replaces on purpose: both are small numbers and a stored 0.14 is a
> perfectly plausible value under either reading, so there is no way to
> tell one from the other by looking. A settings file written before this
> is migrated once, by _merge_ms, rather than guessed at every load.

**line 619** — before `"any_player": False, "song_max": 15.0,`

> Follow whatever is playing rather than Spotify alone -- a song on
> YouTube in a browser, a file in mpv. song_max is the longest a track
> may be, in minutes, and still be taken for a song: see
> looks_like_a_song, which is the cheap half of telling one from a film.

**line 632** — before `**{key: True for key in BLEND_KEY.values()},`

> On, all five. They were off by default when each one was a rankable row
> of its own; folded into Apple Music they have been on for everybody
> since, and switching them off now would quietly change what is on
> screen for anyone who never knew they had come back.

**line 638** — before `"review_marks": False,`

> Off. It marks a document's faults on the words while the song plays,
> which is the right thing to be looking at while you are going through a
> lyric and the wrong thing to be looking at while you are listening to
> one. Any document, not only a file of your own -- what the marks say
> about a catalogue's copy is true as well, and the review page's tabs and
> weights narrow them where a copy is full of the same small thing. See
> LyricsView.marking.

**line 646** — before `"people_skip": "",`

> Nobody, on either list. Names, comma separated, of whoever timed a sync
> -- refused wherever they turn up, or preferred wherever they turn up.
> See LS.Roster.

**line 666** — before `"offsets_device": {},`

> The global offset, per output AND per player -- "firefox@alsa_output..."
> -- with a bare output name for the ones set before the player was part
> of the key. See offset_key, audio_sink, on_device and on_player.
> Settings only: there is no switch for it on argv, because the thing it
> is keyed by is not known until the window has looked.

**line 673** — before `DEVICE_POLL = 2.0`

> How often the window looks at which output the sound is coming out of. Two
> short subprocesses, on a thread of their own; the thing being watched for is
> somebody reaching for their headphones, so seconds is the right unit.

**line 677** — before `DEVICE_APP = "spotify"`

> Whose stream to follow, matched loosely against the names PipeWire files a
> playback stream under.

**line 684** — before `MESH_STYLES = ["blobs", "wash", "veil"]`

> What the mesh draws with the palette it is given.
>
> blobs: the drifting Lissajous circles, which is what mesh has always been.
> wash: one colour laid down the window from the top edge, a second coming
> back up from the bottom -- the flat album-coloured gradient a Genius album
> page has, which reads as a tinted room rather than as lights moving in a
> dark one. veil: that with no gradient at all, the whole window one tint.

**line 692** — before `VIZ_IN_KEY = 8`

> Where viz_live() sits in scene_layer's cache key. Named because scene_mix has
> to tell a change of THAT field from a change of any other, and counting the
> tuple out by hand at the far end of the file is how the two drift apart.

**line 696** — before `VIZ_MODES = ["bloom", "pulse", "bars", "tide"]`

> bloom: the drifting blobs, sized by the chord sounding. pulse: a ring per
> beat, off the grid alone and so the one that holds up on a track with no
> chords in it. bars: the twelve pitch classes as columns. tide: slow water,
> rising with the loudness and answering nothing else.

**line 702** — before `RENDER_MODES = RD.RENDER_MODES`

> How the lyric column itself is drawn. See renderers.py; the window only
> ever asks the one it is holding to paint, and knows nothing else about it.

**line 705** — before `UNPAUSE_MODES = ["measured", "fixed"]`

> measured: unpause_delay is the ceiling on the leap read off the player.
> fixed: it IS the hold, taken whole at every unpause. See Clock._apply.

**line 709** — before `ART_SIDES = ["left", "right"]`

> Which edge the album art panel hangs off. Not the same question as
> ALIGNMENTS, which is where the WORDS sit inside whatever column is left
> over -- the two are set independently and both are worth having: art on
> the right with the lyrics still ranged left is a different picture from
> art on the right with them ranged right against it.


## `ckpt_facts`

**line 784** — on `        except Exception:`

> not a zipfile save, or old torch

**line 792** — on `        return got`

> not remembered: try again later

**line 794** — before `for gone in [k for k in _CKPT_FACTS`

> Only this file's older readings go; another machine's rows in a synced
> copy are none of our business.


## `_sync_ckpt`

**line 853** — before `pinned = ""`

> AN EXPLICIT CHOICE WINS OVER A MEASURED ONE. `align_ckpt` names a
> checkpoint outright, and it is obeyed without being scored against
> anything -- because the benchmark cannot see everything a person cares
> about. Its 43 songs contain no Dutch at all, and the Dutch-tuned
> checkpoint measures worse on them precisely because they are not what it
> was tuned for. A number taken where a model was not aimed is not a reason
> to overrule the person who aimed it.

**line 877** — before `got = ckpt_facts(path)`

> What the checkpoint SAYS it was trained on, and only then the name.
> The name is a convention two models have already broken: both were
> trained on separated vocals and called "-lines" and "-vox", so they
> read as mixture models and were saved from being chosen only by
> having fewer steps than the incumbent.

**line 883** — on `        if not got.get("read"):`

> unreadable: not a candidate

**line 892** — before `want = "stem" if stems else "mix"`

> WHICH MEASUREMENT MAY DECIDE. A score taken on a separated vocal says
> nothing about a mixture, and a mean over seventeen songs is not
> comparable with a mean over forty-three -- so only checkpoints measured
> on the SAME input and the SAME set may be ranked against each other.
> The set chosen is the one the most candidates share, largest first;
> anything not measured on it ranks as unmeasured and falls back to step
> count, which is where this started.

**line 916** — before `clean = row.get("clean")`

> ON CLEAN SONGS, NOT ON THE MEAN. They disagree, and the disagreement
> is the point: over 43 songs one checkpoint came out 1.177s against
> another's 1.484s while having FEWER songs free of a mess-up, 17
> against 19. It made its catastrophes smaller rather than rarer, and
> rarer is what a person notices. The mean only breaks ties.


## module level

**line 1014** — before `("Readings above",    "furigana",     "bool",   None),`

> Still `furigana` in the settings file, because that is what it was
> called when it only did kana over kanji and renaming a key throws
> away everybody's answer to it. What it does now is a reading over
> whatever script the line is in.

**line 1024** — before `("Merge flat splits", "merge_ms",     "num",    (0.0, 120.0, 5.0, "{:.0f} ms")),`

> At 0 every split the source wrote is drawn. Turned up, a word whose
> syllable boundaries land where a plain letter-count would have put
> them anyway is drawn whole, because that split is not telling the
> eye anything and is three more fragments to carry. The number is how
> far off the letter-count a boundary may be and still count as
> saying nothing.

**line 1033** — before `("Unpause delay",     "unpause_delay", "num",   (-1.0, 1.0, 0.01, "{:+.2f}s")),`

> A hundredth, not a twentieth: what this trims is the gap between the
> leap the player is measured to make and the one it really makes, and
> that gap is tens of milliseconds. At 0.05 the only settings either
> side of the default were 0.20 and 0.30, which overshoot it by more
> than the error being corrected.

**line 1053** — before `("Fetch ahead",       "fetch_ahead",  "num",    (0, 7, 1, "{:.0f} tracks")),`

> After the slots, not before them: src_move addresses the running
> order as MENU_SPANS' first row plus the position moved to, so a row
> of any other kind at the top of this section puts the cursor one out
> on every reorder.

**line 1059** — before `("Refuse syncs by",   "people_skip",  "text",   None),`

> The two rows that talk about PEOPLE rather than databases. Here
> because this is the section about which sync you end up with, and
> because what they overrule is the ranking directly above them.

**line 1082** — before `("Off by one",        "off_by_one",   "num",    (0.0, 1.0, 0.05, "{:.0%}")),`

> A chance per line of GOING wrong, not a share of the song: once it
> has gone wrong it stays wrong for a few lines, the way a real
> off-by-one does, so 15% lands on the wrong line about one line in
> three. Measured over twelve plays of "NF - Time": 228 lines of 756.

**line 1113** — before `SECTION_NOTE = {`

> A line under the tab strip, for a section whose rows cannot say what they
> are on their own. Kept beside MENU_SECTIONS rather than inside it: three
> places unpack those entries as two-tuples, and a third element would break
> every one of them.

**line 1139** — before `HELP_SECTIONS = [`

> THE KEYS PANEL, in sections.
>
> It is a painted overlay rather than a scrolling widget, so it has exactly
> the room the window has -- and at thirty-five keys in two columns it was
> taller than a 768-line laptop screen, drawn centred, which put the first
> rows and the last rows off the top and bottom with no way to reach them.
>
> So it fits itself to the window (see help_layout): as many columns as the
> width allows, a smaller size before anything is hidden, and only when even
> that will not do does it show one section at a time with the tab strip to
> move between them. On a screen where the whole list fits, the whole list is
> what is drawn, exactly as before.

**line 1189** — before `HELP_MARGIN = 26.0`

> The room kept clear between the panel and the edge of the window. Whatever
> is left is what the panel has to fit inside.

**line 1276** — before `PIX_BUDGET = 96 << 20`

> What the drawn-line and glow caches are allowed to hold, in bytes.
>
> They used to be one dict with one rule: over 400 entries, THROW IT ALL
> AWAY. Two things are wrong with that and they compound. Counting entries
> is not counting memory -- a line pixmap on a wide window is around 700 KB
> and a glow is a few KB, so 400 of them is anywhere between 2 MB and 280 MB
> -- and emptying the whole thing means every line in the column has to be
> re-rasterised at once, blurred ones through soft_scale, on the frame that
> happened to tip it over.
>
> Measured by sweeping the clock through three songs at eight times speed
> with the window painting every frame: the cache reached 401 and was dumped
> two to three times per song, each dump costing a frame of up to 23ms on
> this machine and more on a slower text rasteriser. That is the "shaky for
> a moment, at random" -- and the same clearing is done deliberately when a
> better source arrives mid-song, which is why a refresh both caused it and
> then cured it for a while.
>
> So: a byte budget, and the LEAST RECENTLY USED entry goes when it is
> reached. The working set is what is on screen -- a dozen lines at one or
> two blur levels, well under 20 MB -- so the budget below holds it several
> times over and evictions come off the cold end where nobody is looking.
>
> Separate budgets because the two are not interchangeable. A glow is keyed
> by word, size and radius, so a song full of long words mints hundreds of
> them; sharing one budget let that flood evict the lines, which are the
> expensive ones to rebuild.

**line 1306** — before `PIX_PER_FRAME = 2`

> How many line pixmaps one frame is allowed to BUILD.
>
> The cost of a drawn line is not spread evenly over a song: 3900 frames of
> "NF - Time" measured here built nothing at all on 3861 of them and six to
> eleven pixmaps on twenty-one, which are exactly the frames a line changes
> on. A line's blur is a function of how far it is from the one being sung and
> of how far through its fade-in it is, so a line switch moves EVERY line in
> the column to a new blur level -- and each level is its own picture. Those
> frames measured 11 to 17ms against a 2.2ms median, which is the whole 60fps
> budget gone on an idle machine and rather more than that on a busy one.
>
> So the work is rationed instead. A frame that wants more pictures than this
> draws the rest at the nearest blur it already has and asks again next frame;
> a burst of eleven is paid off over six frames, none of which anybody can
> feel. What it costs is that a far-off line can be a blur level stale for a
> tenth of a second, on lines that are faint and out of focus to begin with.

**line 1332** — before `_DWMWA_CORNER = 33`

> DwmSetWindowAttribute, the two attributes that decide whether Windows 11
> draws its own decoration over a window it has already been told to make
> fullscreen. Both were added in Windows 11 and both are refused with
> E_INVALIDARG on Windows 10, which is a perfectly good answer and is
> ignored. Numbers rather than names because there is no Python binding for
> this and there is no reason to grow one.

**line 1338** — on `_DWMWA_CORNER = 33`

> DWMWA_WINDOW_CORNER_PREFERENCE

**line 1339** — on `_DWMWA_BORDER = 34`

> DWMWA_BORDER_COLOR


## `windows_output`

**line 1664** — on `        dev = MediaDevice.get_default_audio_render_id(0)`

> AudioDeviceRole.DEFAULT


## module level

**line 1711** — before `MERGE_WAS_ON = 40.0`

> What a fraction of the word's span was worth, as a flat number of
> milliseconds. Measured over the 1267 multi-syllable words in the folder this
> was written in: 14% of the span merged 783 words and 40ms merges 408, which
> is the closest a flat figure comes to the old setting on the words where the
> old setting was doing something defensible -- the short and middling ones.
> It is not a conversion, because there is none: the two rules disagree most
> exactly where the old one was wrong.


## `save_settings`

**line 1788** — before `values = dict(values, offsets={k: float(v) for k, v in offsets.items()`

> Zero included. It is a correction like any other -- "this track
> is right as it stands, do not measure it" -- and dropping it
> here would restore the measured offset on the next launch.


## module level

**line 1859** — before `RD.TEXT, RD._smooth = TEXT, _smooth`

> The two names the renderers need from this module, handed over rather than
> imported back: `import lyrics_gui` from there would load a second copy of
> this module whenever the window is started as a script, which is how the
> .desktop file starts it.

**line 1901** — before `BRIDGE_PLAYERS = ("plasma-browser-integration",)`

> The desktop's own bridge to what a browser is playing, which on KDE is the
> Plasma browser extension. It is not a second player -- it is the same media
> session, published by something that can see the page -- and where both are
> on the bus it is by some distance the better one to read. Measured on this
> machine against Firefox's own MPRIS, the same YouTube Music track:
>
>            Firefox                     the bridge
>   title    'The Taste | YouTube Music'  'The Taste'
>   artist   (empty)                      the artist
>   length   217.0                        217.941
>   position 0, 0, 0, 1, 1, 1, 2, 2       0.011 0.283 0.574 1.114 1.395
>
> The browser publishes the WINDOW TITLE and a position rounded to the
> second; the bridge publishes what the page told the MediaSession API and a
> position that moves. A second-wide clock is the whole of "the lyrics lag
> and keep re-timing", and a title with the site's name welded on is why the
> lookup that decides whether a track is a song could not find one.

**line 1920** — before `VIDEO_SITES = ("netflix.", "twitch.tv", "vimeo.", "disneyplus.", "hulu.",`

> WHAT COUNTS AS A SONG, on a player that is not Spotify.
>
> MPRIS has no field that says whether the thing playing is a song or a film.
> Firefox and Chromium publish the same half-dozen xesam keys either way --
> title, artist, album, art, whatever the page handed to the MediaSession API
> -- so the question has to be answered from what is there, and the answer is
> a guess. These are the shapes it is made of:
>
>   the address, where the player gives one. Chromium publishes the page's
>   url and a local player publishes the file's, and that is the one signal
>   here that is not circumstantial: .mkv is a video and .flac is not, and a
>   tab on a film service is not playing a single.
>
>   the length. A song is minutes long; a film, a set, a lecture or an
>   episode is not. Only applied where the player actually says -- a browser
>   often does not, and "no length" has to mean "no idea" rather than "not a
>   song", or the very thing this was added for is refused every time.
>
> None of it can answer YouTube, which is the site anybody turns this on for:
> the songs are there and so is everything else, under the same six fields,
> and no shape in the metadata tells the two apart. So the guess does not have
> to -- a LOOKUP does, and the lookup is about the thing being asked rather
> than about its packaging. A track from another player is looked up before it
> is shown and takes the window over on either of two answers (see
> SessionTransport._worth and LyricsView.vet_pending):
>
>   a MUSIC CATALOGUE has the record. Apple Music and SoundCloud are asked
>   about it anyway, for the cover and the label's spelling of the name, and
>   a sure match is that record found in a catalogue of records. This is the
>   one that reaches the songs nobody has written words for -- an
>   instrumental, a remix with no vocal, a track too new for any provider --
>   every one of which the words test refused, for as long as it played;
>
>   or a PROVIDER has the words, which is the older test and is still the
>   answer for a song no catalogue has heard of.
>
> The film and television services are on the list all the same. Not because
> the length test would miss them -- it mostly would not -- but because they
> are never the answer, and the cheapest search is the one not made.

**line 1969** — before `VIDEO_APPS = ("kodi", "plex", "jellyfin", "stremio", "mpvpaper", "obs")`

> Players there is no point asking: they publish MPRIS, and none of what they
> publish is ever a song. mpv and VLC are NOT here -- both play albums.

**line 1972** — before `SONG_SHORT = 20.0`

> Shorter than this and it is a clip, a trailer or an advert rather than a
> track. Interludes exist and some of them are shorter; they are also the
> thing nobody is reading lyrics to.

**line 1976** — before `SONG_MAX = DEFAULTS["song_max"]`

> The other end, in minutes, as the setting states it. Fifteen clears the
> longest thing anybody sings and cuts off below a film, a DJ set or an
> episode of a podcast. It IS the setting -- taken from DEFAULTS rather than
> written twice, since everything here is only its default.

**line 1981** — before `STILL_FOR = 2.0`

> How long a player may claim to be playing without its position moving
> before it is taken not to have a clock at all. MPRIS makes Position a
> required property and a player with nothing to put there publishes a zero
> that never moves -- which does not read as a fault anywhere: the song plays
> and the words sit at the top of it for the whole song. Two seconds is long
> enough not to catch a buffering stall on the way past.

**line 1988** — before `LOOK_EVERY = 0.5`

> How often the bus is asked who else is there, while what it is following is
> not playing. Twice a second is far below the poll rate and far above the
> rate at which somebody starts a song.

**line 1992** — before `SMTC_CARRY = 10.0`

> How far a Windows timeline may be carried forward from the moment it says
> it was written. It is not a budget -- a session that is playing rewrites it
> about once a second -- it is the guard on a stamp that turns out to be
> nonsense: a session that never sets it reports a moment in 1601, and a
> machine whose clock has just been corrected reports one in the future.
> Anything outside this falls back to _tick, which needs no timestamps.

**line 1999** — before `SMTC_LIST_FOR = 1.0`

> How long the list of Windows sessions is trusted before it is asked for
> again. Enumerating it is a property read per session, and the sampler reads
> sixty times a second -- which would be a few hundred COM calls a second
> spent finding out that the same three programs are still open. Nobody starts
> a player in under a second, and a session that goes away inside the window
> is noticed anyway: reading it raises, which clears this.

**line 2006** — before `VET_AGAIN = 5.0`

> How long before a track held back for vetting is asked about again. The
> fetcher has one slot for the track it is looking up, so a lookup started
> here can be overwritten by the song on screen wanting one of its own -- and
> an answer that never comes is a song that never appears. Asking again is
> nearly free: the fetcher is already sitting on its own backoff for a track
> it found nothing for, and a repeat inside that costs a dictionary lookup.

**line 2056** — before `VIDEO_NOISE = {`

> WHAT A VIDEO IS CALLED, AND WHAT THE SONG IN IT IS CALLED.
>
> Spotify hands over a song's title and its artist in two fields. A browser
> hands over whatever the page put in the MediaSession card, and on YouTube
> that is the name of the video: "Allure - Moon and Sun // OFFICIAL", by a
> channel that is as often a label as an artist. Every provider here searches
> by name, and measured against Musixmatch -- which has the song -- the video
> name finds nothing and "Moon and Sun" by "Allure" finds it, so this is the
> difference between the setting working and not.
>
> Three things are done, and nothing else. The decorations come off; a
> "Artist - Title" name is split into the two fields it is really two fields
> of; and YouTube's own channel suffixes come off the artist.
>
> It is deliberately shy. A bracket is only dropped when EVERY word in it is
> packaging -- so (Official Video) and [Lyrics] go and (feat. Rina), (Remix),
> (Radio Edit) and (Live at Wembley) stay, because those name a different
> recording and searching without them finds the wrong one. A name that comes
> out empty is put back as it was.

**line 2082** — before `"youtube", "yt", "spotify", "soundcloud", "bandcamp", "vimeo", "deezer",`

> A browser that publishes its WINDOW title rather than the page's media
> session says "The Taste | YouTube Music". The site's name is not part
> of the song's, and it is the difference between finding the words and
> finding nothing.

**line 2089** — before `VERSION_ONLY = re.compile(`

> The other half of a "Artist - Title" name is sometimes not an artist at all
> but the version: "Rise Up - Radio Edit" is one song with one name. Splitting
> that gives the artist "Rise Up" and the song "Radio Edit", and the search
> that follows finds nothing at all. So a right-hand side that is only a
> version word is not a title and the name is left whole.

**line 2099** — before `TRAILING_NOISE = re.compile(`

> The same packaging worn without brackets, which only ever appears at the
> end: "... Official Video", "... HD". Kept to a short list on purpose -- a
> word that could be the last word of a song's actual name is not on it.

**line 2106** — before `r"|youtube(?:\s+music)?|apple\s+music|soundcloud|bandcamp|vimeo"`

> The site, which is how a browser publishing its WINDOW title ends every
> one of them: "... - YouTube". Only names no song ends on -- "music",
> "play" and "apple" are not here, because Big Apple is a song and this
> would take the apple off it.

**line 2112** — before `TAB_COUNT = re.compile(r"^\s*\(\s*\d+\s*\)\s*")`

> What Firefox puts in FRONT of its window title when tabs want attention:
> "(27) Song Name - YouTube". Digits only, so a song whose name opens with a
> bracket keeps it.


## `_packaging`

**line 2134** — before `if len(words) <= 3 and words[-1] in ("release", "premiere", "exclusive"):`

> "[NCS Release]", "[Monstercat Release]": a label's name is not on any
> list here and never will be, but a short bracket that ENDS in one of
> these words is the upload being announced, not the song being named.


## `song_from_video`

**line 2152** — before `artist = re.sub(r"\s*-\s*topic$", "", artist, flags=re.I).strip()`

> YouTube's auto-generated channels are "<artist> - Topic", and the
> official ones are "<artist>VEVO". Both are the artist plus a suffix.

**line 2157** — before `while True:`

> Everything after a // or a | that is only packaging: "// OFFICIAL",
> "| Official Music Video". A chunk with anything else in it stays --
> "| Live at Wembley" is where the recording is from.

**line 2171** — before `halves = re.split(r"\s+[-–—]\s+", title, maxsplit=1)`

> "Artist - Title", which is how a video says what Spotify says in two
> fields. The name in the title wins over the channel: the channel is a
> label as often as it is the artist, and the title is where whoever
> uploaded it wrote who it is by.

**line 2179** — before `return title or was, artist`

> A name that came out empty was all packaging, and a song with no name
> cannot be looked up at all. Whatever it was called is better than that.


## `SessionTransport`

**line 2242** — before `LABEL = "player"`

> What the window calls this way in, and the session whose playback is
> taken on trust -- whatever is playing THERE was picked in a music
> player. Both are the subclass's to name.

**line 2247** — before `HAS_VOLUME = False`

> WHETHER THIS WAY IN CARRIES A VOLUME, which of the five here only the
> bus and the debug port do. It is a statement about the PROTOCOL rather
> than about the player, so it is a class attribute and not a reading:
> Windows' media transport has no volume in it at all, and a Mac's
> now-playing has none that belongs to the player rather than to the
> machine. The window already hides its slider when a reading brings back
> no volume; this is for the editor, which has to decide whether to draw
> one before any reading has arrived.

**line 2256** — before `WHERE = "this machine"`

> Where to say a search came up empty. Named rather than built from LABEL
> because it is prose in a message a person reads.


## `SessionTransport.__init__`

**line 2263** — before `self.who = self.HOME`

> Whose clock is being read. Fixed at the music player unless asked
> otherwise, which is what makes the default path below identical to
> what it has always been: one session, resolved once, no scanning.

**line 2269** — before `self.vetting = False`

> WHETHER SOMEBODY IS CHECKING THE TRACKS BEFORE THEY GO ON SCREEN.
>
> Nothing any of these services publishes says whether what is
> playing is a song or a film, and on YouTube -- which is the whole
> reason anybody turns this on -- both are there under the same six
> fields. So the window gets to answer the question the metadata
> cannot: it looks the track up, and a track no music catalogue and no
> provider knows anything about never becomes the track. Set by
> whoever can do the looking (see LyricsView.follow_players); off, the
> guess above stands on its own.

**line 2280** — before `self.pending: dict | None = None`

> The song-shaped track being asked about, {tid, meta}, or None. The
> window reads this, fetches for it, and calls allow() if the answer
> is words.

**line 2284** — before `self._swept = False`

> Whether THIS round got as far as sweeping the other players.
> See _read_any, where it is what tells a question nobody answered
> from a question nobody was asked.

**line 2289** — before `self._dressed: dict = {}`

> What a catalogue knows about a track that the player could not say
> -- the cover, the album, the rating -- by track id. Written by
> dress(), worn by every reading after it. Kept here rather than in
> the window because the window has one card, `clock.meta`, and it is
> rewritten sixty times a second from what the player says.

**line 2296** — before `self._clocks: dict = {}`

> What each player's position last read, and when it last changed.
> See _tick, which turns a position that steps into one that moves,
> and _moving, which is the same state asked a different question.

**line 2300** — before `self.trouble = ""`

> Something worth saying out loud about the player being read, or "".
> The window toasts it once; nothing else looks.

**line 2303** — before `self._last: dict | None = None`

> The last reading that was a song. What the window is shown while
> something is playing that is not one -- the song it had, standing
> still -- rather than an empty card or an error.

**line 2307** — before `self._gate = threading.RLock()`

> One caller at a time on the service. Unlike the debug port -- whose
> socket sorts out who asked for what -- none of these makes such a
> promise, and the sampler now reads from its own thread while the
> window seeks from the one it draws on. Every call under this lock is
> a millisecond or so, so waiting for one costs nothing worth having.


## `SessionTransport`

**line 2314** — before `def _sessions(self) -> list:`

> -- what the service is, for a subclass to answer --------------------

**line 2341** — before `@property`

> -- the part that is the same everywhere ------------------------------


## `SessionTransport._read_any`

**line 2380** — before `self._forget(self.who)`

> It has gone: closed, or never arrived. Whatever was cached for
> it is stale either way, and somebody else may be playing.

**line 2388** — before `better = self._look(want_volume, outrank=True)`

> Following a player that something else can describe better: the
> browser itself, while the desktop's bridge is publishing the
> same session with the song's own name on it and a clock that
> moves. Asked at the same rare interval as anything else, and
> only while that is what is being read.

**line 2396** — before `if self._held is not None:`

> WHATEVER IS BEING HELD BACK, and it stands until it is answered.
>
> Spotify paused in one window while a song waits to be vouched for in
> another is the ordinary case, not an edge -- so this is set whether
> or not there was also something to return.
>
> It used to be `self.pending = self._held` outright, and that made it
> a flicker rather than a question. `_held` is only filled on a round
> that actually READS the other player, and where the followed player
> is not the held one that happens in `_look`, at LOOK_EVERY -- while
> the sampler comes through here sixty times a second. Measured on the
> bus alone with a song playing in Firefox: the track was on offer for
> 3.3% of readings, and the window -- which looks four times a second,
> sixteen at the edge rate -- first caught it after a median 0.52s,
> 1.57s at worst, and MISSED IT FOR A WHOLE MINUTE in five runs of
> thirty. That is the whole of "it does not always pick the song up".
>
> So it is dropped only on an answer: allow() clears it when the track
> is let through, and a round that did ask everybody and found nobody
> holding anything clears it as the player having moved on. A round
> that did not get as far as asking leaves the question where it was.

**line 2424** — before `if self._last is not None:`

> Nothing anybody should be shown is playing: a video, a track still
> being asked about, or silence.

**line 2427** — before `return dict(self._last, status="Paused", at=time.monotonic())`

> Hold the song that was there, stopped where it stopped. The
> window goes on showing what it was showing, which is what "do
> not pick up videos" looks like from the other side.


## `SessionTransport._tick`

**line 2495** — before `gaps = (was or {}).get("gaps") or []`

> HOW OFTEN THIS PLAYER ANSWERS SOMETHING NEW, which is its
> resolution, kept as the middle of the last few gaps. The middle
> rather than the smallest: one gap can be short because a reading
> landed either side of an update, and one can be long because the
> sampler was busy, and neither is what the player does. It is
> read by _step_floor, where a step smaller than this is not
> allowed to count as the player's clock having leapt.


## `SessionTransport.allow`

**line 2573** — before `self._looked = 0.0`

> And look NOW rather than at the next turn of LOOK_EVERY. The player
> holding this track is not the one being followed -- that is what
> holding it back means -- so it is only reached through `_look`, and
> waiting out that throttle is half a second of a song that has just
> been cleared to go on screen sitting behind the one before it.


## `MprisTransport._read_one`

**line 2742** — before `"who": who,`

> Whose reading this is. Read by _worth, by the frozen stand-in in
> _read_any, and by nothing in the clock, which has never cared
> where a reading came from.

**line 2746** — before `"grain": grain,`

> How coarse this player's clock is. See Clock._step_floor: it is
> what stops an update interval being mistaken for a leap.


## `MprisTransport._song_of`

**line 2779** — before `"url": str(meta.get("xesam:url", "")),`

> Not shown anywhere. It is here because it is the best thing on
> the bus for telling a song from a video, and because a player
> that gives one gives it in the same breath as the rest of this.
> See looks_like_a_song.


## `MprisTransport`

**line 2789** — before `CAN = {"Next": "CanGoNext", "Previous": "CanGoPrevious",`

> Which property says whether a player will take an instruction. MPRIS
> has one for each and they are not decoration: a player that answers
> false does nothing when told, silently.


## `MprisTransport._able`

**line 2823** — before `return self.who`

> It did not say. Telling it anyway is what this always did.


## `MprisTransport.seek`

**line 2862** — before `self._clocks.pop(who, None)`

> THE ANCHOR IS NOW A LIE, and it has to go before the next
> reading is taken against it.
>
> _tick carries the player's last answer forward at 1x while it
> repeats itself, which is what makes a clock that steps once a
> second usable. The last answer is from before this seek: carried
> forward it describes where the song WAS, walking on from the old
> place, and the clock -- which cannot tell that from the song
> having jumped there -- follows it back. That is a seek that
> lands and then unlands, and the words never recover, because
> every reading until the player updates says the same wrong
> thing more confidently.
>
> Dropped rather than set to the target: the anchor tracks what
> the PLAYER says, and what it will say next is its own business.
> With nothing to carry forward the next answer is news and is
> taken whole, which is exactly right for the one reading after a
> seek.


## module level

**line 2894** — before `ENGINE_WAIT_MS = 400`

> How long the playback engine is given to say where it is before the reading
> goes ahead without it. Measured on this machine it answers in 0.35ms and is
> under 3.5ms at the 99th percentile, so this is not a budget -- it is the
> difference between degrading in half a second and hanging until the socket's
> own fifteen. Generous on purpose: around a seek Spotify's renderer is busy
> and a slow answer is still the right one, where falling back to the control
> state mid-song is a step in the clock.

**line 2903** — before `BEAT_SOON_MS = 700`

> How long the page is given to hand over Spotify's analysis of the track.
>
> Asked twice. BEFORE the lyric walk, because the visualizer is drawn from this
> and nothing else, and it had no reason to wait on ten providers -- the walk
> it used to sit behind is seconds on a cold song, so the wall stayed dark for
> all of them and then lit up with the words. Spicetify memoises the analysis
> per track inside the page, so the common case is a track already fetched and
> the answer is immediate.
>
> It is the one call here that waits on a promise the page has to go and get,
> so it is also the one most likely to hang, and in front of the lyrics that
> would be the words waiting on the wallpaper. Hence the short deadline: miss
> it and the walk starts anyway, and it is asked again AFTER the lyrics are up,
> where waiting costs nothing anybody is looking at.

**line 2919** — before `ENGINE_TAU, ENGINE_SNAP = 0.30, 0.50`

> The engine says where the audio is, but not smoothly: measured here at 60Hz
> against real time, its steps scatter with a standard deviation of 63ms and
> individual ones land 200ms out. That is the audio pipeline reporting itself
> in chunks, not the song stuttering, and passed on raw it is a word sweep
> that visibly shakes -- the clock's own slew does not take it out, because
> that was built for a source which is smooth and occasionally drifts, not one
> which is ragged every frame.
>
> So the engine is used as an ANCHOR, not as the position: a clock that runs
> at 1x on its own and is pulled towards the anchor. TAU is how hard --
> alpha = 1 - exp(-elapsed/TAU) per reading, which is a pull rather than a
> deadband, so it settles with no standing error and adds no lag of its own.
> SNAP is where a difference stops being scatter and becomes a real move (a
> seek, a hand-off) and is taken whole instead. Both are Spicy Lyrics'
> numbers, from the same problem on the same builds.


## `CdpTransport`

**line 3006** — before `name = "Spotify"`

> What the window calls it. Spicetify is the door -- an extension loaded
> into the client -- and the player on the other side of it is Spotify,
> which is the answer to "what is this playing on".


## `CdpTransport.__init__`

**line 3016** — before `self.source = "engine"`

> Which clock the last reading came from, and how long the engine has
> been saying the same thing. The sampler takes nearly every reading,
> but not quite all of them -- resync() takes one on the thread it is
> called from -- and a stall is counted across readings, so the count
> is kept straight rather than left to whichever arrives first.

**line 3025** — before `self._eng_show: float | None = None`

> The smoothed engine clock: where it is, when that was, and whose
> song it is. See _smooth.


## `CdpTransport._pick`

**line 3124** — before `if engine != self._eng_pos or not playing:`

> The stall is looked for in the RAW reading. The smoothed one
> goes on advancing by construction, so asking it whether the
> engine has stopped would never get an answer.


## `CdpTransport.read`

**line 3159** — before `if not str(got.get("title") or "").strip():`

> A reading carrying a uri and NOTHING else, counted rather than
> guarded against.
>
> This is the one field the guard above tests; every other one below
> is `or ""` / `or 0.0`. So an item with a uri and no title would be
> accepted, would name the same track -- reset_track never fires --
> and would overwrite clock.meta with blanks. The art panel is four
> separate truthiness tests on four of those fields, so all four
> would stop drawing at once and the window would lose its whole left
> side with the lyric column still scrolling.
>
> That is exactly what was seen once and it was NOT this: it was a
> TypeError out of paintEvent losing everything drawn after the
> lyrics. Nothing has ever been observed handing back a skeletal
> item, so nothing is CHANGED here -- keeping the last meta that said
> something was written once and taken out again, because it is a
> change to the clock justified by a fault that turned out to be
> somewhere else.
>
> What was missing was any way to find out. This is that: it costs a
> dict lookup on a reading that is already being parsed, and over a
> session with track changes, ads and a Connect handover in it, it
> either never prints or it names the case. If it does print, the fix
> is four lines and the shape is the same as the guard above.

**line 3198** — before `"source": self.source,`

> Which of the two clocks _pick just settled on. The resume hold
> is only meaningful over one of them; see Clock._apply.

**line 3208** — before `"explicit": (None if got.get("explicit") is None`

> None where the player did not say, which every other
> transport also means: MPRIS and the Windows session hand
> over a title and an album and no flags at all.


## module level

**line 3228** — before `AUMID_NAMES = {`

> What a Windows session calls itself, and what it is really called.
>
> The AUMID is an application's identity to the shell, and for most of them it
> reads well enough once the packaging is off: "Spotify.exe" and the Store
> build's "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify" are both Spotify.
> Firefox is the exception -- it registers a HASH, and the hash is the only
> thing the media transport ever hands over for it, so the names are written
> down here. Nothing depends on the list being complete: an id that is not on
> it is cleaned up and used as it stands, which is what every browser but that
> one already gives.

**line 3245** — before `SPOTIFY_AUMID = "spotify"`

> Which id is Spotify's, either build. Matched rather than compared for the
> reason above: the Store build's id is a publisher, a package, a hash and an
> application, and only the last word of it says what it is.


## `SmtcTransport.__init__`

**line 3291** — before `self._seen: dict = {}`

> The session list, and when it was taken. See SMTC_LIST_FOR.

**line 3294** — before `self._art: dict = {}`

> Covers already pulled off the transport, by track id. A thumbnail is
> a stream to open, read and close -- worth doing once a song and not
> four times a second, which is what asking on every reading would be.


## `SmtcTransport.drop`

**line 3324** — before `self._mgr = None`

> The manager too, not only what was cached under it. A session
> list survives a player closing and goes on handing out a session
> that answers nothing; re-requesting it is one call.


## `SmtcTransport`

**line 3336** — before `@staticmethod`

> -- the service ------------------------------------------------------


## `SmtcTransport._key`

**line 3347** — before `got = got.split("!")[-1]`

> The Store form is publisher.package_hash!app, and it is the app on
> the far side of the bang that names the program.


## `SmtcTransport`

**line 3417** — before `def _read_one(self, want_volume: bool, who=None) -> dict:`

> -- one reading ------------------------------------------------------


## `SmtcTransport._read_one`

**line 3430** — before `try:`

> The session that answered, which is not always the one that was
> asked for: see _session, which falls back to whatever is current.

**line 3444** — before `anchored = self._tick(who, tid, raw, at, "Playing" if playing else "Paused")`

> THE POSITION, AND WHY IT IS NOT SIMPLY WHAT THE TIMELINE SAYS.
>
> A session writes its timeline when something happens to it, not
> continuously: a browser rewrites it about once a second and Spotify
> only on a transport change, so `position` read at the sampler's rate
> is a clock that stands still and then jumps. Windows' own flyout does
> not draw it that way, and neither does this -- the timeline carries
> the moment it was written, so where that moment is usable the reading
> is carried forward against it and the result moves smoothly.
>
> _tick is still fed, with the RAW figure. It answers the other
> question -- whether this player's clock is going at all (see
> _moving) -- and a carried position would answer that yes forever,
> including for a session stuck at zero, which is the one failure here
> that looks like success.

**line 3470** — before `"url": "",`

> Windows has no field for the address, so the guess that reads
> one is working with less here than it is on the bus. See
> looks_like_a_song, and `kind` just below, which is what this
> service has instead.

**line 3483** — before `"kind": _kind_of(pb),`

> Whether Windows was told this session is music or video. Only
> ever read as a yes -- see looks_like_a_song.


## `SmtcTransport`

**line 3520** — before `def seek(self, seconds: float) -> None:`

> -- telling it things -------------------------------------------------


## `SmtcTransport.seek`

**line 3531** — before `self._clocks.pop(self.who, None)`

> The anchor describes where the song was. Carried forward past a
> seek it walks on from the old place and the clock follows it
> back, which is a seek that lands and then unlands. See
> MprisTransport.seek, which drops it for the same reason.


## `_since`

**line 3589** — before `secs = float(stamp) / 1e7 - 11644473600.0`

> A raw FILETIME: hundred-nanosecond ticks since 1601-01-01.


## module level

**line 3665** — before `MAC_PROCS = {`

> What `ps` calls each of them, so the transport can find out who is running
> without asking anybody's permission. System Events would answer the same
> question and would raise the Automation prompt to do it -- for a list of
> process names, which is on the machine already.

**line 3675** — before `MAC_EVERY = 0.25`

> How often a player that has to be asked over Apple Events is asked. Every
> other transport here reads at the sampler's rate, because a bus property or
> a COM call is microseconds; an osascript is a process, and sixty of them a
> second is not a lyrics window, it is a fork bomb. So the readings are taken
> in the background at this interval and handed over from a slot -- which is
> exactly the shape _tick was written for, and it turns them into a clock that
> moves the same way it turns Firefox's into one.

**line 3683** — before `MAC_APPS_FOR = 5.0`

> How long the list of running applications is trusted. Nobody opens a browser
> in the middle of a bar.

**line 3686** — before `MR_DOUBT = 3.0`

> How long MediaRemote may answer "nothing is playing" before the other doors
> are opened alongside it. Apple shut the framework to unentitled callers in
> macOS 15.4 and it does not say so -- it answers, politely, with an empty
> card, which is indistinguishable from a quiet machine. So it is given this
> long to be telling the truth, and after that somebody else is asked too; if
> THEY have a song, the framework is shut and is not asked again.


## `MacTransport.__init__`

**line 3724** — before `self._mr_quiet = 0.0`

> When MediaRemote first said nothing was playing, and has said it
> ever since. See MR_DOUBT.

**line 3729** — before `self._slots: dict = {}`

> One slot per player that has to be asked over Apple Events: the last
> answer, when it landed, and whether somebody is out getting the next
> one. Read from the sampler's thread, written from the background
> ones; a dict assignment is what crosses between them, so there is
> nothing here to lock.


## `MacTransport.usable`

**line 3745** — before `return bool(MacTransport._open_apps())`

> No framework, so it comes down to whether anything is even there to
> ask. A Mac with neither music player open and no browser running is
> not a Mac this can read -- and saying so is what lets make_transport
> fall back to the debug port rather than installing a door that will
> never open.


## `MacTransport`

**line 3765** — before `@staticmethod`

> -- who is even here --------------------------------------------------

**line 3805** — before `def _doubted(self) -> bool:`

> -- MediaRemote -------------------------------------------------------

**line 3839** — before `def _slot(self, who: str) -> dict | None:`

> -- Apple Events, at their own pace -----------------------------------

**line 3872** — before `def _read_one(self, want_volume: bool, who=None) -> dict:`

> -- one reading -------------------------------------------------------


## `MacTransport._read_one`

**line 3881** — before `if got.get("playing"):`

> MediaRemote says the machine is silent and somebody here is
> playing. That is the shut framework, not a quiet Mac. It is
> not asked again this session; a new one is built whenever
> the settings change, so nothing is lost permanently.


## `MacTransport._shape`

**line 3903** — before `"volume": None,`

> No door on a Mac carries a volume that is the PLAYER's: Spotify
> and Music have one over Apple Events, but the browsers do not
> and MediaRemote has none at all, so the slider would appear and
> disappear with the player. It stays hidden.


## `MacTransport`

**line 3944** — before `def _tell(self, what: str) -> None:`

> -- telling it things -------------------------------------------------
>
> Only the music players take instructions. A browser tab has no transport
> to speak of -- the page draws its own -- and MediaRemote's command call
> is behind the same entitlement as the rest of it, so there is no route
> that would work where the reading route does not.


## `MacTransport.seek`

**line 3961** — before `self._clocks.pop(self.who, None)`

> The anchor is from before the seek; carried forward it walks on
> from where the song was and the clock follows it back. See
> MprisTransport.seek.


## `BackupTransport`

**line 3995** — before `LOOK = 0.5`

> How often the OTHER side is asked whether anything is playing on it,
> while the side being read has nothing. Twice a second: far under the
> sampler's rate, far over the rate at which somebody starts a song. A
> side that FAILED is knocked on at RETRY instead -- a dead debug port
> answers no faster for being asked ten times as often.


## `BackupTransport.__init__`

**line 4006** — before `self.handover = handover`

> Whether an IDLE primary hands over, or only a broken one.
>
> Off -- what this class has always done -- the primary is preferred
> whatever it is doing, and the stand-in only covers for it being
> down. That is right when both sides are reading the same player:
> Spotify paused is Spotify paused, whichever way you ask.
>
> On, the two sides are no longer the same player, and the question
> becomes which of them the listening is happening on. So whoever is
> PLAYING wins: the debug port while Spotify plays, the session bus
> while something else does and Spotify does not. See make_transport.


## `BackupTransport.allow`

**line 4058** — before `self._next_look = 0.0`

> Look at the other side on the very next reading. A track being
> vouched for is by definition on the side NOT being followed, and
> the answer arriving is the one moment its reading can change what
> is on screen -- so this is exactly when not to be waiting out LOOK.


## `BackupTransport._follow`

**line 4108** — before `got = None`

> Answered, and the answer is no. Nothing to drop and nothing to
> stand off from; the other side is simply asked below.

**line 4119** — before `return got`

> Playing on the stand-in, and not yet time to look at the other
> one. Below, the primary is glanced at even while this one plays
> -- see why there.

**line 4127** — before `other = None`

> Nothing playing over THERE, which is an answer rather than a
> failure: that side is up, it has been asked, and it has
> nothing. Knocked on again at LOOK, not stood off from at
> RETRY -- see NothingPlaying. What that cost while the two
> were confused: a track held back for vetting makes the bus
> raise, the bus was then written off for five seconds, and a
> song whose lookup had ALREADY come back yes waited a
> measured 3.5s for the screen. It is 0.5s at worst now, and
> nothing at all where allow() is what cleared it.

**line 4144** — before `if other is not None and (got is None`

> Back to the primary the moment it is playing again, even while
> the stand-in is playing too. BOTH SIDES CAN BE THE SAME PLAYER:
> Spotify is on the session bus as well as on the debug port, so
> one hiccup down the port used to hand the window to the bus for
> as long as the song lasted -- reading Spotify a second, worse
> way, and telling the user it was following MPRIS. Where they are
> different players this is the same rule as ever, since the
> primary is the one preferred when both are playing.
>
> PLAYING is the whole of the question, and a stand-in that has
> merely STOPPED does not answer it. Handing back on a pause is
> what this used to do, and what that did to a listener was: pause
> whatever they were playing and the window jumps to Spotify and
> whatever is sitting there paused in it -- another track id, so
> poll() sees a new song and throws the lyric away to fetch that
> one. Anything that reads not-Playing for a single round did it
> twice, out and back: a seek over the bus reports the old status
> with the new position, and so does the moment between tracks. So
> the stand-in is kept until it is GONE or the primary is really
> playing, and a pause now leaves the words where they were.


## module level

**line 4183** — before `def session_transport():`

> The platform's own way of knowing what is playing, whichever one this is:
> the session bus, the Windows media transport, or whatever door is open on a
> Mac. Named once so everything that has to ask "is there one of those here"
> -- make_transport, the settings menu, the doctor -- asks it the same way.


## `Clock.__init__`

**line 4252** — before `self.lock = threading.RLock()`

> Held across `apply`, `position` and the assignments in `seek` -- the
> three that read and write the same half-dozen floats. A window that
> polls off its GUI thread would otherwise be able to read `_pos` from
> before a reading and `_at` from after it, which is a position wrong
> by the whole poll interval and would be stamped into a lyric.

**line 4271** — before `self.unpause_fixed = False`

> Whether unpause_delay is the CEILING on a measured leap or the hold
> itself. Measuring needs the player to be honest about where it
> stopped, and where the same unpause reads 0.13s one time and 0.50s
> the next, a number set by ear is the better one. See _apply.

**line 4278** — before `self._resume_pos = 0.0`

> Where the position was when playback resumed, and how far it had
> already stepped by then. The window after a resume measures itself
> against these rather than against the reading before it -- see
> _apply, and why a sum of forward steps is not a measurement.

**line 4284** — before `self._bias_tid: str | None = None`

> Which track the carried unpause leap belongs to. Its own field
> rather than a reading of `_pos_tid`, because resync() clears that
> one deliberately -- to stop the reading after a resync being eased
> into -- and the bias was being dropped as a side effect of that,
> which is the opposite of what resync asks for by passing keep_hold.


## `Clock._apply`

**line 4328** — before `engine = str(got.get("source") or "") == "engine"`

> WHOSE CLOCK THIS READING IS, and it decides whether there is
> anything to undo at a resume at all.
>
> The control state is what Spotify PUBLISHES about itself, and
> it is published when a transition is decided rather than when
> it is heard -- so on resume it steps forward to where playback
> is about to be while the sound has not started. That step is
> the thing the hold below measures and takes back off.
>
> The engine's position is not that. It is where the audio
> actually is, which is why _pick prefers it and why Spicy
> Lyrics -- which reads the same thing and has no resume
> correction whatsoever -- needs none. A step in it on resume is
> the sound having moved. Subtracting it holds the words back by
> exactly the amount the music went forward, for the rest of the
> track, which is "after a resume the lyrics are behind".

**line 4349** — before `resumed = (status == "Playing" and not was_playing`

> A RESUME IS A TRACK THAT WAS PAUSED AND IS NOW PLAYING. The
> track is half of that and used to be left out, so the FIRST
> reading of any track arrived here as an unpause: the window had
> just opened, `_pos_tid` was None and `_raw` was 0, and the
> measurement below read the whole of the song's position as a
> leap the player had just made. Capped at the ceiling, that is a
> quarter of a second of hold put on a track nobody had paused --
> and it is CARRIED, so it sat there for the rest of the song.
>
> Measured on a simulated Firefox 95s into "Clocks", the window
> opening on it cold: the words came up 0.283s behind the audio
> and stayed there. With the track in the test, 0.0.
>
> It costs nothing where a resume is real: pausing and unpausing
> is the same track either side, which is exactly what this asks.
> Skipping while paused and then playing is not -- and there is
> no leap to read across a track change anyway, since the
> position either side of one describes two different songs.

**line 4369** — before `jumped = (not resumed and status == "Playing" and was_playing`

> How far the player's own clock jumped when it unpaused, which is
> how far it is now ahead of the sound. Spotify leaps 0.253s at the
> unpause and then keeps it -- it never comes back -- so cancelling
> it for a quarter second and letting go put the words back ahead
> of the voice for the rest of the song. It is carried instead,
> until something re-establishes where playback is: a seek, a
> resync, a new track, or the next pause.
>
> Taken from the player rather than assumed, because it is the
> player's habit and not every one has it -- over the session bus
> there is no leap at all, `pos - held` is nothing, and this
> subtracts nothing. unpause_delay is the ceiling on it.
> A jump this clock did not make itself: the scrubber in Spotify's
> own window, a keyboard skip, another Connect device. A seek made
> from HERE is written into `_pos`/`_raw` as it is sent, so the
> reading that follows one is continuous with it and does not land
> here -- which is what leaves resync's kept hold alone.
>
> The leap is a statement about a stretch of playback that has now
> been thrown away. The pipeline is flushed by the seek, the audio
> is back with the clock, and going on subtracting a quarter second
> holds the words behind a voice that no longer leads them.
>
> SLEW_MAX is the boundary the clock already draws between drift it
> will ease and a difference it takes whole; a difference too big to
> ease is exactly what "went somewhere else" means, so there is no
> second threshold to keep in step with this one. Inside RESUME_
> SETTLE the same test would fire on the unpause leap arriving late,
> which is the one forward step that is not a seek.

**line 4407** — before `free = self._resume_pos + (at - self._resumed_at)`

> It does not always land in the first reading; take it when
> it does.
>
> Measured from where the resume left off, NOT summed reading
> by reading. The engine's position does not advance smoothly
> -- it jitters a few milliseconds either side of free-running
> and comes back -- and adding up only the forward halves of
> that rectifies the noise into a bias. Sixty readings a second
> for a second, at the +-8ms measured on this machine, made
> tens of milliseconds of hold out of a player that had not
> moved at all: the words sat that far behind the voice for the
> rest of the song, every time, which is exactly steady enough
> to be mistaken for a constant somewhere else.
>
> The displacement since the resume is the same measurement for
> a real leap -- which lands and stays, so it shows here whole
> however late it arrives -- and averages to nothing for jitter.

**line 4426** — before `read = (_within(want, _measured_cap(self.unpause_delay))`

> Both directions. This used to be max(0.0, ...) and that is
> what made the setting look inert to somebody whose words
> come back BEHIND the audio: the only correction on offer
> pushed them further behind, so nought did nothing and
> anything else did the wrong thing. The displacement is an
> unbiased measurement -- that is the whole argument for
> measuring it this way rather than summing readings -- so
> rectifying the answer threw away half of what it knew.
> The floor is on the SIZE now, for the same reason it was
> ever there: to keep jitter from becoming a bias.

**line 4440** — before `self._resume_lead = self.unpause_delay`

> Stated, not measured. Nothing to read off the player and
> nothing to accumulate: the hold is the setting, every
> unpause, which is what makes it tunable by ear at all --
> each 0.01 moves the words 10ms against the voice, in one
> direction, every time.

**line 4450** — before `self._resume_lead = (pos - held) - max(0.0, at - self._at)`

> Only the part of the step that real time cannot account for.
> A position further on than it was is not by itself a clock
> that has jumped: between the last reading and this one the
> song was allowed to play, and on the debug port the engine's
> position is the sound's own -- it is SUPPOSED to have moved.
> Spotify does not announce itself playing at the instant the
> audio starts, so by the first reading that says "Playing"
> the sound has often been running for a few tens of ms, and
> taking the whole step held the words back by exactly that,
> for the rest of the track. What a leap means is a position
> that has moved further than the clock on the wall.

**line 4469** — before `stale = (not resumed and status == "Playing" and tid == self._pos_tid`

> The hold this replaces was a DURATION: subtract the delay, run it
> out over the next quarter second, let go. That is the right shape
> for a player whose audio is late coming back -- a thing that ends
> -- and the wrong one for a clock that has stepped ahead and
> stays there, because letting go is what puts the words back in
> front of the voice. Same number, carried instead of spent.

**line 4479** — before `if (tid == self._pos_tid and status == "Playing"`

> Only across CONTINUOUS playback. The slew is here to absorb
> the drift between the player's clock and this one without the
> words visibly stepping, and drift is something that happens
> while a song runs. A resume is not drift: the words were
> parked where the song stopped, the audio has already started
> somewhere ahead of them, and there is no continuity left to
> protect -- so easing the difference in holds them at the
> parked position for the whole of the first poll and then
> slides them forward, which is the lurch this exists to
> prevent, produced on purpose.
> ...and not while the player is still settling from one.
> It does not finish unpausing in a single reading: it can
> report itself playing BEFORE it applies the forward leap its
> position makes, and then the leap lands on the next poll --
> by which time playback is already running, `was_playing` is
> true, and the test above no longer recognises it as part of
> the unpause. Measured over ten unpauses it arrived late on
> four of them, +0.263s, and was eased in over the following
> third of a second: the words start correct and then slide,
> which is worse than a step and much harder to place. The
> smaller one is this clock's own doing -- the hold running out
> is a step in `held_back` too, and easing that is easing a
> correction it just made on purpose.
>
> Everything arriving in this window is the unpause completing,
> so it goes on immediately and whole.


## `Clock.seek`

**line 4616** — before `self._at = began + (time.monotonic() - began) / 2`

> Where the song went is known exactly; WHEN it went there is not.
> The player takes the command somewhere inside the round trip, so
> the middle of it is the honest anchor -- the same correction the
> readings get, and for the same reason: this timestamp is what
> every position between now and the next reading is measured from.


## `Pump.__init__`

**line 4712** — before `self.pin_pause = pin_pause`

> Either a flag or something to ask. The window's is a SETTING, and
> the settings menu rebinds the attribute rather than writing through
> it, so a copy taken here would go on pinning after it was switched
> off -- and, worse, stop when it was switched back on.

**line 4717** — before `self.last_tid: str | None = None`

> The track the last reading reported, as the PLAYER gave it. Not the
> same question as `clock.tid`, which --track overwrites after the
> fact: a watcher comparing against that sees the override and the
> reading disagree and thinks the song changed, twice per poll,
> forever. This is only ever written here, once per reading.


## `Pump.run`

**line 4742** — before `self.clock.status = "Error"`

> `spotify_dom.connect` calls sys.exit when the debug port has
> gone. SystemExit is not an Exception, and raised on the GUI
> thread it used to take the window down with it; here it ends
> nothing but the reading it arrived in.

**line 4755** — before `self._wake.wait(self.every if self.clock.status != "Error"`

> A player that is not answering is not worth asking sixty times a
> second: back off to the old rate until it does. Nothing is
> moving while it is down, so there is nothing to be late for.


## module level

**line 4765** — before `HAVE_IT = 0.25`

> What a song already on this machine is worth beside one only Genius knows
> about. It stands in for the popularity Genius supplies and a local index
> cannot -- pitched at the top of that range on purpose, so an equally good
> match the user already has, and has probably timed by hand, takes the tie.


## `Beat`

**line 4868** — before `JS = "Promise.race([Spicetify.getAudioData(%s).then(d => ({" \`

> Raced against a deadline, so a page that is slow to fetch the analysis
> costs that and not the socket's own fifteen seconds. null means "not in
> time", which every caller reads as no answer -- see Fetcher._audio, which
> asks twice with two different deadlines.


## module level

**line 5061** — before `EST_MAX = 0.25`

> The two gates on the SIZE of a measured correction, as against how confident
> the reading was.
>
> Confidence says the winning shift beat the runner-up; it does not say the
> winner was the right one. The way this fails is a latch: the true alignment
> is weak -- a soft entry, a lyric whose first line is early, an analysis that
> cut no clean edge under the voice -- and some other shift wins the curve
> outright. Confidence is then HIGH, because there really was one clear peak,
> and the number under it is nonsense. Those land big: half a second and more,
> which no community lyric sheet is actually out by.
>
> So a correction past EST_MAX is refused however well it scored. Scored
> against the tracks on this machine that have been tuned by ear -- the only
> truth there is -- the estimate's own median error runs 0.06s where it reads
> under 0.15s, 0.19s in the 0.15-0.25 band, 0.28s in 0.25-0.35, and 0.46s
> beyond that. Past a quarter of a second the error is as big as the
> correction it is offering, so the reading has stopped saying anything: not a
> worse fix, no fix at all.
>
> Nor is much given up by refusing them. Of 140 corrections made by ear here
> only five are bigger than 0.35s and the median is 0.03s, so songs genuinely
> out by half a second barely exist -- while readings CLAIMING half a second
> are common, twenty of them sitting exactly on the ±EST_RANGE rail, which is
> a curve with no peak in it running out of room rather than a song out by
> three quarters of a second.

**line 5087** — before `EST_AGREE = 0.12`

> ...and the same reading taken twice, once on each half of the song, has to
> come back with the same answer. A real offset is a property of the recording
> and holds from the first line to the last; a latch is usually the doing of
> one stretch of the song and the other half does not agree with it. Neither
> half is asked to be confident on its own -- half the anchors is a noisier
> curve and the peak can be a close-run thing -- only to point the same way.
>
> Over the same hand-tuned tracks the halves' disagreement sorts the readings
> better than confidence does: under 0.05s apart the median error is 0.085s,
> between 0.05 and 0.12 it is 0.21s, past 0.25 it is 0.43s. Set where this and
> EST_MAX between them stop the disasters -- the worst correction any of those
> tracks would now be given is 0.20s out, against 3.04s under the confidence
> gate alone -- and no tighter, because tightening it further only refuses
> tracks the size gate has already made safe.

**line 5299** — before `JS_ARTISTS = """(() => {`

> There was a calibrate() here, and why it is gone is worth keeping.
>
> It took the median of (what the estimator read) - (what the track was tuned
> to by hand) over every track that had both, and subtracted that from every
> other reading. The argument was that estimate_offset does not return the sync
> error: it returns the sync error plus a standing difference between what a
> lyric timestamp marks (a word starting) and what a segment edge marks (the
> spectrum changing), and on a hand-tuned track the hand correction is the
> truth, so the difference between the two is that standing error "and nothing
> else".
>
> It is not "and nothing else". A hand correction absorbs whatever the DOCUMENT
> got wrong as well as whatever the estimator does -- somebody tuning a track
> by ear is correcting the lyric sheet in front of them, not calibrating an
> instrument. So every reference point was the standing bias plus that
> document's own error, and there is nothing in the median that separates
> them. docs/notes/TODO.md measures the size of what was being mixed in: the
> per-document spread on QQ alone is 0.191s, against a standing bias small
> enough that it took a hundred tracks to see. The signal was under the noise
> it was being averaged with, and no amount of hand-tuning fixes that -- more
> tracks add more document error, not less.
>
> The global offset is the correction for a standing, every-song difference,
> and it is set by the person who can hear it. That is the job calibration was
> being asked to do automatically from evidence that could not support it.

**line 5527** — before `ART_TRIES = 3`

> HOW HARD A COVER IS TRIED. Three goes inside one fetch, a moment apart,
> then the fetch itself worth three: a cover that did not arrive used to be
> gone for the whole song, because art_url is set before the thread starts
> and the poll will not ask twice for the same url. So one timeout, one
> refused connection, one proxy having a bad second, and the song played
> through with the last song's picture on it -- silently, since the failure
> was caught and dropped. Which is how it turns up on a machine behind
> whatever Windows has in front of its sockets, on a song Spotify itself is
> showing perfectly well out of its own cache.

**line 5899** — before `MOTION_BUDGET = 192 << 20`

> The most an animated cover may occupy once it is decoded and sitting in
> pixmaps, in bytes.
>
> It used to have no ceiling at all, only a per-frame width, and the two are
> not the same thing: 30fps for up to 35 seconds is a thousand frames, and a
> thousand frames at 720px is 2.1GB of pixmap. That is the whole of the
> reported "2GB while a song with animated artwork is playing", and it is
> arithmetic rather than a leak. Even the ordinary case is not small -- the
> covers cached on this machine run 80 to 120 frames, which is 250MB on a 4K
> screen.
>
> When a cover will not fit, FRAMES are dropped and the picture is left
> alone: an animation played at 15fps instead of 30 is barely remarked on
> and a cover at half the resolution is the first thing anybody sees. See
> on_motion, which works out the stride and slows the clock to match.


## `MotionArt._work`

**line 6145** — before `with self._lock:`

> Off the in-flight list either way, so the same album can be
> asked for again when it comes round.


## module level

**line 6289** — before `_people = LS.people`

> Who a credit slot names. It lives in lyric_sources now, because the chain
> has to read the same field to know whose sync it is holding (see Roster) and
> two readings of one convention is how the name printed here and the name
> refused there drift apart.


## `Fetcher.__init__`

**line 6326** — before `self._doing: tuple | None = None`

> The latest thing the player has been told to do -- a play or a
> skip -- and whether a thread is already seeing to it. See `_act`.

**line 6332** — before `self._card: tuple | None = None`

> (tid, meta) for a track whose cover and album are being asked of
> Apple Music. One slot, last one wins: it is the track playing.

**line 6361** — before `self._kept: dict = {}`

> Why a track's masks were left standing, per track id. One entry a
> song and only for the songs that had masks at all, so it is a handful
> of strings over a session and not worth a sweep.

**line 6365** — before `self._wake = threading.Event()`

> Set when a TRACK is asked for, so the loop starts on it instead of
> finishing whatever is left of its idle sleep. See run().


## `Fetcher.request`

**line 6373** — before `with self._lock:`

> Woken at the end, because this is the one request with somebody
> watching a clock on it. The loop sleeps POLL_IDLE between rounds, so
> a track asked for a moment after a sleep began waited out the rest
> of it before anything was fetched at all -- measured at 415ms on a
> launch, between the window knowing the song and the first ask going
> out. Everything else queued here is background work that nobody is
> timing, and the idle pace is right for it.


## `Fetcher._gsearch_loop`

**line 6548** — before `self.gsearch_ready.emit(q, got)`

> Emitted whatever has been typed since: the window knows
> which query is on screen and drops an answer to any other.


## `Fetcher.request_ahead`

**line 6570** — before `self._ahead_gen += 1`

> Bumped whoever is warming out of putting a track back on a list
> that is no longer the list it took it from; see _warm.


## `Fetcher._warm`

**line 6622** — before `with self._lock:`

> Longer than the scan that would rebuild this. Whatever
> was coming up when the list was written is not evidence
> about what is coming up now.

**line 6638** — before `got = LS.fallback(tid, meta, "none", enabled=want, order=order,`

> Yields to a real request the moment one arrives, and not
> only between tracks: warming the next song while the user
> waits on this one is the exact trade this thread exists to
> avoid, and a walk takes seconds.
> Under the roster too: the answer is stored keyed by it
> (see LS._store), so warming a track without it would file
> the entry under a question the real walk never asks, and
> every warmed song would be walked again from cold.

**line 6652** — before `if (got is None and self._want is not None`

> Cut short part way: fallback stores nothing from a walk it
> gave up on, so the track has to go back or the look-ahead
> has quietly dropped it. Only onto the list it came off --
> a scan since then has replaced it with what is coming up
> now, and this one is not that.


## `Fetcher.run`

**line 6681** — before `beat_tid = ""`

> The track whose analysis has already gone to the window, so the
> patient ask after the lyrics is only made where the quick one before
> them came back with nothing, and so the retries a cold song spends in
> this loop do not each cost a round trip.
>
> ONE id, not the set of every id seen. The window drops its analysis
> on every track change -- reset_track calls Beat.clear -- so a song
> played a second time in the same session needs sending it again, and
> a memo that remembered forever answered "already sent" to a window
> that no longer had it. What that looked like: play a song, get a
> visualizer; come back to it later in the same run and get none, for
> the whole play. Nothing said so, because a track Spotify never
> analysed looks exactly the same from the window -- and the beat
> pulse, the section the palette rotates on and the measured offset
> (see estimate_offset, which reads beat.segs) went with it.

**line 6711** — before `self._wake.clear()`

> Under the same lock request() sets it under, so a track
> arriving after this point sets it again and the wait below
> falls straight through. The worst that costs is one round of
> the loop with nothing to do.

**line 6718** — before `if tid != beat_tid:`

> Before the walk, not after it. The visualizer reads this and
> nothing else, so sending it behind the lyrics meant the wall
> stayed dark for however long ten providers took and then lit
> up along with the words. It answers at once for a track the
> page has already fetched, and BEAT_SOON_MS is what stops a
> track it has not from costing the lyrics anything.

**line 6748** — before `if tid != beat_tid and not self.stop:`

> Only where the quick ask came back with nothing. Given a
> long deadline now, because the words are already up and
> nobody is waiting on this.
>
> Not gated on `lines` any more: a track nobody has a lyric for
> still has a wall, and it used to be the one case that never
> got one.

**line 6763** — before `with self._lock:`

> Asked for, but still inside the backoff from a load that
> came back empty. The request has to be put back: it was
> taken off _want at the top of the loop, and nothing else
> here would ever ask again. What covered for that was the
> window's own poll, which re-requests four times a second --
> but only while the screen is EMPTY, so the retry that
> matters least is the only one that survived.

**line 6816** — before `self._wake.wait(POLL_WAITING if tid and tid in pending else POLL_IDLE)`

> A wait rather than a sleep, so a track change does not have to
> outlast it. It still times out at the same pace, which is what
> the periodic work in here -- the Spicy Lyrics watch, the index
> batches -- is paced by.


## `Fetcher._interim`

**line 6104** — before `rank = LS.RANK.get(LS.quality(body), 0)`

> Reported: a track finds the right source, is replaced by a worse one for
> about a second, and then goes back to the right one.
>
> Every early answer comes through here -- the page's own copy, the last-known
> document that stands in while the walk runs, and each report the walk makes
> as a provider lands -- and each of them knows what IT is worth and nothing
> about what is already on screen.
>
> The stand-in is the one that showed. _load reads `have` off the page's body,
> so a track whose Spicy page could not be reached computes `have = "none"`
> and hands the walk a bar of 0 -- while, two lines further down, it has just
> put a perfectly good stored document on the screen. `beats` is then true for
> anything at all, so the first line-timed provider to land takes the screen
> from a syllable-timed document, and the walk's own pick puts it back at the
> end. Right, wrong, right.
>
> Fixed here rather than by raising `have`, because `have` is also what
> decides whether the walk runs at all and how wide -- a bar of "syllable"
> skips it -- and the stand-in is not a reason to stop looking. This is only
> about what reaches the screen. Equal ranks still go up: between two
> documents timed alike the running order decides, and that is `landed`'s job,
> not this one's.


## `Fetcher._watch_spicy`

**line 6840** — before `watch[tid] = (grace, now + SPICY_SLOW)`

> A read that did not get through says nothing about what
> Spicy Lyrics has. Dropping the watch on it ended the
> looking for good on one dropped socket, and left the song
> on somebody else's document for the rest of its play; hang
> on and ask again at the slow pace.


## `Fetcher._drop`

**line 6941** — before `return`

> The connection this call failed on has already been thrown
> away, and what is up now is somebody else's fresh one.
> Dropping that is how one thread's timeout came to cost
> every other thread its working socket, in a round nobody
> can win: each of them drops the last one made.


## `Fetcher._genius_match`

**line 7110** — before `title = re.sub(r"[\(\[\{].*?[\)\]\}]", "", raw).strip() or raw`

> "(Romanized)", "[Live]" and the rest are Genius's own bookkeeping and
> match nothing in the catalogue -- but a title that is ALL brackets is
> the song's actual name, so the trim is only kept if it leaves one.

**line 7116** — on `            artist = ""`

> "Genius Romanizations" is not who recorded it


## `Fetcher._spicy_hold`

**line 7211** — before `return None`

> Asked before the round trip, not after it, or the deadline
> is only honoured once it has already been overrun. This is
> the case the docstring above describes -- a walk that really
> went to the network -- and it was still paying for one more
> read of the page, on the connection that walk had just spent
> several seconds not using.


## `Fetcher._load`

**line 7243** — before `self._late = tid if self._page_seen else ""`

> The page did not answer -- the socket dropped, Spotify is still
> starting. That is not Spicy Lyrics saying it has nothing, so the
> song must not spend the rest of its play on whoever the chain
> finds instead: mark it late, and the watch below asks again for
> as long as the track is up.
>
> Only where the page has answered before. On Linux the clock
> comes off MPRIS, so the whole window runs against a Spotify
> started without the debug port -- and there the watch would be
> a failed connection every SPICY_SLOW, all day, for an answer
> that is never coming.

**line 7256** — before `refused = bool(body) and rule.blocks(body)`

> A refused sync is not an answer. Dropped here rather than inside
> _spicy_body, because the two are different silences: the page having
> nothing YET is what the watch below keeps asking about, and this is
> settled -- the document is in hand, it is somebody's the user has
> said no to, and no amount of asking again will make it somebody
> else's. See LS.Roster.

**line 7266** — before `self._late = "" if have == "syllable" or refused else tid`

> Nothing from Spicy Lyrics -- or nothing WORD-TIMED from it -- is not
> the same answer as there being nothing to have. It fetches inside
> the page, and on a cold song it lands late and it lands twice: a
> line-level copy first and the word-timed one after. Say so, so the
> walk's answer can be shown now and handed back when Spicy's own
> arrives, which is what the order asks for.

**line 7273** — before `shaped = None`

> Whatever is already here goes up first, before anybody is asked
> anything. Spicy Lyrics has usually cached the song before the window
> even knows the track changed, and the walk that might improve on it
> can take seconds across ten providers -- there is no reason to spend
> them looking at an empty screen holding a document that is very
> probably the one that wins anyway. If Spicy has nothing, the last
> answer stored for this track on disk stands in: it was good enough
> to keep, so it is good enough to read while a better one is fetched.
> Shaped once, and the same object handed to the interim and to the
> answer below. Shaping twice made two documents that say exactly the
> same thing, and the window compares an arriving answer with the one
> it holds by identity -- so the second of them read as a NEW lyric
> for the same song and cost a full rebuild: every line laid out
> again, every pixmap dropped, the offset re-measured on the drawing
> thread. Once per track, every track, in the second after the words
> first appear.

**line 7296** — before `self._interim(tid, None if rule.blocks(was) else was)`

> Stored under an older roster, in all likelihood: the walk below
> will not hand back a refused document, and neither should the
> one held over from last time to read while it runs.

**line 7300** — before `liked = rule.likes(body)`

> Nobody outranks a name the user asked for. `ahead` is what lets a
> source they put above Spicy Lyrics take an equally good document off
> it, and that is exactly the ranking a preferred sync is meant to be
> heard over -- so where this copy is one of theirs, the sources above
> have to beat it on timing or not at all.

**line 7308** — before `hunt = bool(rule.pick) and not liked`

> AND A NAME THEY ASKED FOR IS WORTH GOING TO LOOK FOR. Spicy Lyrics
> has word timing for most songs and is ranked first by default, and
> that combination used to end the load right here: nothing further
> down the list can beat word timing on quality, so nothing further
> down was asked -- and a sync by somebody the user named, sitting on
> Unison or amll, was never fetched at all. Preferring them means
> exactly that their document wins that tie, so it has to be
> fetched. The walk narrows itself to the sources where a name can
> be found for what asking them costs -- amll, Unison and this
> machine's own files; see LS._walk and credits_people.

**line 7322** — before `if better is not None and not ahead and have != "syllable" and not refused:`

> Keep asking Spicy Lyrics until SPICY_HOLD is up, before taking
> anybody else's answer. Asking exactly once here was not enough: the
> walk it was meant to outlast usually never went to the network at
> all -- a month of answers sits on disk, so `better` comes back in a
> millisecond -- and Spicy Lyrics' own fetch was still a few hundred
> of them away. So the song was credited to NetEase or Apple Music
> and put right a second later, on nearly every song whose three-day
> cache entry had aged out. The watch below would still catch it;
> this stops the wrong name going up at all. Not where the user has
> ranked something above Spicy Lyrics: then the walk's answer is the
> one they asked for.


## `Fetcher._shaped`

**line 7372** — before `if LS.lrc_shaped(body):`

> Before the ad-lib repair rather than after it: split_asides cuts a
> bracketed run out of the lead, and a hole closed across the place
> that run used to be is a word held over an ad-lib somebody else
> sang. Closing them first means every hole is closed between two
> syllables that really are neighbours.

**line 7379** — before `body = LS.quiet_marks(body)`

> After the unlump, so a mark that was glued into a lumped syllable
> has been cut out of it and can be seen for what it is.


## module level

**line 7530** — before `DASHES = "-\u2010\u2011\u2012\u2013\u2014"`

> Every dash a lyric uses to write a word's own split into it: the plain
> hyphen, the typographic and non-breaking ones, and the two long dashes that
> get used the same way ("Oh—oh—oh").

**line 7535** — before `JOIN_AT_MOST = 2`

> How many fragments one merge may fold together. Two: a seam is a statement
> about the two pieces either side of it, and that is the whole of what this
> rule can honestly test. See _join_flat for what raising it does and why the
> damage falls on long words.


## `_flat_group`

**line 7561** — on `        if abs(run[k][1] - at) > tol:`

> the boundary says something

**line 7563** — on `        if abs(run[k + 1][0] - run[k][1]) > tol:`

> a rest inside the word


## `_join_flat`

**line 7651** — before `walls = {k for k, (a, b) in enumerate(zip(cores, cores[1:]))`

> Boundaries no run may be taken across, whatever the clock says. A dash
> sitting ON a boundary, rather than anywhere in the word: a dash trailing
> the LAST syllable is punctuation between words ("B-O-Y—") and says
> nothing about how this one is cut.
>
> And a piece with no letter or digit in it at all -- a full stop, a
> comma, an apostrophe timed on its own. Nothing invents one of those: the
> splitter cuts at vowels and hyphenation cuts between letters, so a
> standalone "." is always somebody's own decision, and the test cannot
> see that because it measures CHARACTERS. "7", ".", "0" are one character
> each and equally long, which is as proportional as three pieces can be,
> so the guess matched perfectly and a hand-timed "7.0" was drawn "7." and
> "0" -- the one thing this rule must never do, done to the one kind of
> split it knows least about.


## `prepare`

**line 7885** — before `"opposite": bool(ln.get("opposite")),`

> The side the dots hang off is the side of the line they lead
> INTO, not the window's default. In a duet the two voices sit
> against opposite edges, and dots pinned to the left through
> an eight-bar gap in front of a right-hand line count down on
> the wrong side of the screen -- they are that singer's
> count-in, so they wait where that singer will arrive.


## `LiveLink._accept`

**line 7963** — before `sock.disconnected.connect(self._maybe_let_go)`

> An editor that was walking Spotify along with it and then went
> away -- closed, crashed, unplugged -- must not leave the player
> muted and running. Nobody is timing against it any more.


## `LiveLink._maybe_announce`

**line 8023** — before `self._was = (pos, now, state)`

> Measured from what was last SAID, not from the last tick. Anchored
> on the tick, a drift that comes on slowly is never more than a
> fiftieth of a second at a time, so it was never announced at all --
> and the editor was extrapolating from a reading that had quietly
> stopped describing the song.


## `LiveLink._handle`

**line 8081** — before `base=float(v.offset),`

> The two halves, apart. `offset` is a sum whose meaning
> changes with `live` -- it drops the per-track part the
> moment an editor's document is on screen -- so anyone
> stamping times against this clock has to be told which
> number is which. An editor wants `base` and only
> `base`: the per-track correction describes how far the
> SONG'S OWN lyric sits out of true, and the document
> being written is a different document.

**line 8104** — before `v = self.view`

> Two different questions, and they had one answer between them.
> `doc` is "what is on screen"; while an editor is pushing, that
> is the editor's own file, handed straight back to it. Anybody
> asking a PLAYER for lyrics means the other question -- what this
> song's own document is -- so `source_doc` answers that from the
> copy kept aside when the push landed.

**line 8124** — before `out = {"ok": False, "why": why}`

> Always an answer. A reply that is neither a document nor a
> refusal tells the asker nothing, so it sits out its timeout
> and reports "the player did not answer" -- which is untrue
> and hides the only useful part.

**line 8142** — before `if msg.get("stop"):`

> Where the editor's own audio is, for a file being timed against
> a local copy rather than against Spotify. See follow_editor.


## `Aligner._align`

**line 8320** — before `got = (LS.fallback(tid, meta, "none", set(names), order=names,`

> The roster counts here too: a song whose only word timing is
> somebody's the user has refused is a song this machine is not
> going to be shown word timing for, which is precisely when
> aligning it here is worth the GPU.


## module level

**line 8391** — before `SEARCH_MAX = 300`

> How much a hand-drawn text box will hold. Every one of them is bounded,
> because none of them is a document: what goes in is a search, a name or a
> token, and there is no length past these at which a box is doing its job.
>
> Unbounded, they were a way to hang the window. Everything a box costs is
> paid per FRAME and most of it grows with the text -- measuring it to place
> the caret, measuring it again to scroll it, drawing it, and, for the two
> searches, walking every cached lyric for it and sending it to Spotify and
> to Genius on every keystroke. A held-down Ctrl+V appends a copy per press,
> so the cost climbs with the number of presses and does not come back down.
>
> 300 for a search because the longest line in a lyric in this folder is 251
> characters, and pasting a whole line to find the song it came from is the
> thing the search is for. 2000 for the editor because the longest thing it
> ever holds is a comma-separated list of people -- around 130 names, against
> the handful anybody actually lists -- and a Genius token is sixty.


## `Field.__init__`

**line 8428** — before `self.clipped = False`

> Set whenever something had to be dropped to fit, and cleared by
> whoever says so. A paste that silently keeps its first N characters
> looks exactly like a paste that went wrong; see LyricsView.field_key.

**line 8434** — before `self.sel: int | None = None`

> The other end of the selection, or None when there is none. The
> caret is always one of the two ends, so a shifted arrow only ever
> has to move the caret.


## `Field`

**line 8442** — before `def set_text(self, text: str) -> None:`

> -- the text --------------------------------------------------------


## `Field.replace_at`

**line 8459** — before `room = self.limit - len(self.text) + (hi - lo)`

> What is being taken out makes room for what is going in, so a
> full box can still be typed into over a selection.


## `Field`

**line 8482** — before `def word(self, at: int, step: int) -> int:`

> -- moving about ----------------------------------------------------


## `Field.key`

**line 8537** — before `at = lo if back else hi`

> An unshifted arrow against a selection collapses it to the
> edge it points at rather than moving one place from there.

**line 8559** — before `if ev.text() and ev.text().isprintable() and (alt or not ctrl):`

> AltGr arrives as Ctrl+Alt and is how half of Europe types a
> character, so only Ctrl on its own means "this is not text".


## `Field`

**line 8566** — before `def laid_out(self, at: float, fm, rect) -> None:`

> -- where it was drawn, and what a click in it means ------------------


## `Field.pick_word`

**line 8626** — before `if self.text[at].isspace() and at > 0 and not self.text[at - 1].isspace():`

> A click in the gap AFTER a word belongs to that word, the way it
> does in every other text box -- otherwise the end of a line picks
> nothing at all.


## `LyricsView`

**line 8646** — before `query = property(lambda s: s.q_field.text,`

> The three text boxes this window draws by hand. Everything that only
> wants to know what was typed goes on reading `query`, `bq` and
> `edit_text` as the plain strings they have always been; the caret and
> the selection live on the Field beside them, which is also what a
> click and a drag are answered from. See Field.


## `LyricsView.__init__`

**line 8694** — before `self.field_drag: Field | None = None`

> Which text box the mouse is dragging a selection out of, if any.

**line 8722** — before `self.renderer = (args.renderer if args.renderer in RD.RENDERERS`

> An unknown name in gui.json falls back rather than taking the window
> down on the way up: a settings file can outlive the renderer it names.

**line 8729** — before `self._focus_on = args.focus or 2`

> What O turns focus back on to: the width it had when it was last
> switched off, so the key returns the setting rather than a default.

**line 8740** — before `self.vet_at: dict[str, float] = {}`

> When each track off another player was last looked up, to find out
> whether it was a song at all. Not a set of the ones already asked
> about: an ask can be lost -- see VET_AGAIN -- and a song nobody
> ever answered for is a song that never reaches the screen.

**line 8745** — before `self.vet_body: tuple | None = None`

> The document a vetting fetched, for the track it let through. The
> words are already here when the song arrives; see poll().

**line 8748** — before `self._said_player = ""`

> The last thing said out loud about a player, so it is said once and
> not four times a second for as long as it goes on being true.

**line 8751** — before `self.card_asked: set[str] = set()`

> Tracks Apple Music has been asked to describe. Once each: the
> answer is remembered on the transport and by LS itself, and a miss
> is a miss for as long as the track is called what it is called.

**line 8755** — before `self.card_len: dict[str, float] = {}`

> How long the RECORDING is, by track, where a catalogue has said.
> Only ever used to ask about a song -- see fetch_meta.

**line 8758** — before `self.vet_meta: dict[str, dict] = {}`

> The card a held-back track was offered with, and whether it has
> been put to the providers yet. See vet_pending and ask_lyrics.

**line 8762** — before `self.card_done: set[str] = set()`

> Tracks whose stored answer has already been thrown away once for a
> better question. Once is the whole of it: the second telling is the
> same card again, and a walk a track does not need is ten providers
> asked for nothing.

**line 8787** — before `self.troll_skew = 0`

> Which way the scroll is currently one line out, and the line it
> was decided on. Nothing else in the view reads them: the words are
> drawn at the real time either way. See troll_aim.

**line 8792** — before `self.search_until = 0.0`

> The searching fit: when the next one starts, when this one ends,
> and the leg being travelled while it does -- where it is heading,
> how fast, and when it was last moved. See troll_search.

**line 8808** — before `self.reloading: str | None = None`

> The track whose lyrics R has asked for again, with the ones it is
> replacing still on screen. See reset_track and on_lyrics.

**line 8811** — before `self._drawn: list = []`

> What the lines on screen say, as they arrived. See same_lyric.

**line 8836** — before `self.focus_idx = -1`

> The line the column has scrolled to, which with `scroll_lead` set is
> the line ABOUT to be sung rather than the one sounding. See tick and
> Flow._paint_line: it is read by the blur as well as by the scroll.

**line 8847** — before `self.vol_want: float | None = None`

> What the wheel has asked for and the player has not been told yet,
> and when it was last told anything. See `flush_volume`: the bar is
> drawn from this the moment it changes, so the level on screen is
> the hand's and not the backlog's.

**line 8855** — before `self.help_tab = 0`

> Which section of the Keys panel is on show, where the window is too
> small to show them all at once. -1 until anybody pages.

**line 8860** — before `self.info_rects: list = []`

> (rect, key, value) per row of the song-info panel, for the click
> that copies one. See _paint_info and copy_info_row.

**line 8884** — before `self.review = None`

> The review of the document on screen, built when that screen is
> opened and not before: it costs a pass over the whole document and
> loads pyphen's patterns, and the great majority of plays never ask
> for it. `review_at` is what it was built from; see review_key_of.

**line 8892** — before `self.review_tab = "all"`

> Which of review.TABS is being read. The findings divide into three
> questions a person asks separately -- is the text right, is it cut
> in the right places, is it in the right place in time -- and reading
> a document for one of them at a time is how anybody actually goes
> through one.

**line 8898** — before `self.review_level = ""`

> Which weight is being read, or "" for all three at once. The tab
> says what a finding is about and this says how much it matters --
> two questions, asked separately, and the page can be narrowed by
> either or by both.

**line 8905** — before `self.review_open: set = set()`

> Which folded entries have been opened out, by (line number, kind) --
> a Row object is rebuilt with every read of the document, and what
> somebody opened is a line of the song rather than an object.

**line 8912** — before `self.review_lang = ""`

> Empty means the tag the document carries. It is often wrong -- every
> Dutch file in this folder is tagged `en` -- and the splitters are
> only as right as the language they are asked in, so the page can be
> told; see review_cycle_lang.

**line 8959** — before `self._scene_old: QPixmap | None = None`

> The wall being changed into another one. `_scene_old` is what was on
> screen before, held only for as long as the fade lasts; `_scene_from`
> is when it started. See scene_layer and scene_mix.

**line 8964** — before `self._scene_viz: bool | None = None`

> True/False when the change under way is the visualizer arriving or
> leaving, naming which side is the lit one; None for every other kind
> of change. See scene_mix, which drives those two off the visualizer's
> own fade instead of off the clock.

**line 8969** — before `self._viz_mix = 0.0`

> How far in the visualizer is, 0 to 1, and the last picture it drew.
> The picture is held so the way OUT has something to fade: viz_live
> goes false the moment the analysis is dropped, and rebuilding the
> layer without it would draw an empty one rather than the last full.

**line 8977** — before `self._font_memo: dict = {}`

> (family, size, weight) -> (font, its name, its metrics). See
> _lyric_face: the key is complete, so nothing empties this.

**line 8980** — before `self._ink_gen = 0`

> Moves when a line's romanisation is rewritten under it, which is the
> one thing that changes a drawn line after it was prepared. See
> line_ink, whose memo has this in its key.

**line 8984** — before `self.pix_cache: OrderedDict = OrderedDict()`

> Two caches, not one, and both of them least-recently-used. See
> PIX_BUDGET: a shared dict emptied wholesale is where the stutter
> was.

**line 8990** — before `self._pix_left = PIX_PER_FRAME`

> This frame's remaining ration of new line pixmaps. See PIX_PER_FRAME.

**line 8996** — before `self._art_fails: dict = {}`

> How many fetches each cover url has already cost, so a url that
> cannot be had is dropped rather than asked for forever. See on_art.

**line 9004** — before `self.motion_fps = float(MOTION_FPS)`

> Frames a second AS KEPT, which is MOTION_FPS divided by whatever
> stride the budget forced. See on_motion.

**line 9019** — before `self._viz_tone = 1.0`

> Open, not shut: a track opening on a chord should answer to it from
> the first frame, and one opening on drums closes the gate inside a
> second anyway.

**line 9028** — before `self._viz_was = 0.0`

> The strength the visualizer had when V switched it off, so switching
> it back on restores it. A NAME OF ITS OWN: this used to be spelled
> _viz_last, which is the last picture the visualizer drew, and the two
> were set from either side -- viz_face writing a QPixmap over the
> remembered strength every frame it is live, V writing a float over
> the picture. Either way round the next paint reads the wrong kind:
> `got.width()` on a float, which is an AttributeError inside
> paintEvent and so a half-drawn window rather than a crash.

**line 9038** — before `self.device = self.device_name = ""`

> Which output the sound is coming out of, WHO is playing into it,
> and what the global offset was set to on each pairing of the two
> seen so far. See offset_key, on_device and on_player.

**line 9102** — before `threading.Thread(target=LS.sweep, daemon=True).start()`

> Nothing else ages the lyric cache out, and a document is kept for as
> long as the song is still being played, so the only pass over it is
> this one: once a day, off the startup path, drop what has gone a
> month unheard.

**line 9121** — before `self._seen_tid: str | None = None`

> One reading before the pump starts, so the window comes up already
> knowing the song rather than showing an empty frame for a sixtieth
> of a second. It is also the only reading taken on this thread.

**line 9126** — before `self._read_tid = self.clock.tid or None`

> What the last reading the window ACTED on said. Compared against the
> sampler's own record rather than the clock, so that --track, which
> overwrites the clock's id after every poll, cannot look like the
> song changing back and forth. See on_reading.


## `LyricsView`

**line 9154** — before `def retune_frames(self, *_) -> None:`

> -- the frame rate follows the screen the window is actually on -----


## `LyricsView._frame`

**line 9213** — before `period = 1.0 / max(1.0, self.eff_hz if self.showing() else FRAME_IDLE_HZ)`

> In a finally because the old repeating timer would have carried
> on through a raised frame and this one would not: one traceback
> out of tick would leave the window alive but permanently frozen.

**line 9220** — before `self._frame_due = time.monotonic() + period`

> A long stall: a slow fetch on this thread, a resize, the
> machine suspended. Start the cadence again from here rather
> than firing a burst of frames chasing a moment that has gone.


## `LyricsView`

**line 9254** — before `def lyric_px(self) -> float:`

> -- fonts sized off the window, like the web view -------------------


## `LyricsView._lyric_face`

**line 9397** — before `if len(self._font_memo) > 16:`

> A resize walks the size through every pixel on the way, so this
> would otherwise grow a face per pixel of window width. The
> working set is two -- the lyric size and the backing-vocal one.


## `LyricsView`

**line 9410** — before `def on_reading(self) -> None:`

> -- data ------------------------------------------------------------


## `LyricsView.vet_pending`

**line 9516** — before `self.want_card(tid, m, True)`

> THE CATALOGUE FIRST, and the providers when it answers.
>
> What it knows that the player cannot is how long the RECORD is,
> and that number goes into the question all ten of them are about
> to be asked -- an upload runs a few seconds longer than the
> release it is of, and those seconds decide matches. See
> fetch_meta. Asked together instead, the first walk goes out with
> the upload's length in it and has to be made again: a walk
> wasted, and an answer to the wrong question drawn in the
> meantime. It also spells the name, which is the other half of
> what the providers are searching on.


## `LyricsView.on_card`

**line 9589** — before `self.ask_lyrics(tid)`

> Nothing, or nothing to go on: a title alone matches anybody's
> song of the same name, and a cover is as wrong as a name when
> it is the wrong record's. See LS._apple_card. A track waiting on
> this answer still goes out -- it was waiting for the best
> question available, and this is it.

**line 9600** — before `dress(tid, {"art": card.get("art") or "",`

> NOT the rating. It reads like the flag Spotify hands over with the
> track it has open, and it is nothing like it: that one names the
> RECORDING the player is playing, while this is a search result --
> and Apple carries the clean edition of a song beside the explicit
> one. Measured: Apple's first answer for "peekaboo" is the clean
> cut, so passing its rating on told clean_edit this recording was
> clean and quietly switched uncensoring off for a song that is not.
> The player cannot say, and a catalogue guessing is worse than the
> honest silence that sends the question to Musixmatch instead.

**line 9611** — before `"title": card.get("title") or "",`

> The catalogue's spelling of both, which is the point of
> asking: "ALLURE" is how YouTube writes Allure.

**line 9615** — before `if tid in self.vet_meta:`

> The release's own length, for asking about it with. Kept apart from
> the card: the bar and the clock belong to the audio that is
> actually playing. See fetch_meta.
> The spelling goes into the question as well as onto the screen: it
> is half of what every provider searches on.

**line 9627** — before `if tid in self.vet_at and tid != self.clock.tid:`

> AND THE CATALOGUE HAS ANSWERED THE OTHER QUESTION TOO.
>
> Whether the thing playing is a song used to be decided by whether
> anybody had WORDS for it, because that was the only test available
> that asked about the thing rather than about its packaging. It is a
> good test and it is the wrong question, and what it costs is the
> songs nobody writes lyrics for: an instrumental, a remix with no
> vocal, a track too new or too small for any of the ten providers.
> Every one of those is a song, and every one of them was refused --
> the window went on showing the song before it, for the whole of the
> one actually playing.
>
> A music catalogue answers the question directly: Apple Music and
> SoundCloud are asked in the same breath, about a RECORD, and a
> `sure` match is that record found. It is already being asked, for
> the cover and the spelling, so this costs no request.
>
> `sure` is what makes it safe to believe -- see LS._apple_card. A
> title alone matches anybody's song of the same name, so a match is
> only sure when somebody on the byline agrees or the two durations
> do, which is not something a film clip named after a song clears.
> And the cheap gate still runs in front of all of it: a film service
> or a .mkv never gets as far as being looked up. See
> looks_like_a_song and SessionTransport._worth.
>
> The lyric test is not replaced, it is no longer the only door. A
> track no catalogue has heard of goes on waiting for words exactly
> as it did -- see vet_answer, which is the other one.

**line 9660** — before `LS.forget(tid)`

> WHAT WAS ASKED BEFORE WAS THE WRONG QUESTION, and the answer to
> it is on the disk under this track's id. The cache is keyed by
> the track and not by the question, so asking again on its own
> hands back the same answer -- measured on FE!N, where a walk
> made with the player's own "FE!N" had settled for line timing
> while Apple's catalogue, asked for "FE!N (feat. Playboi Carti)",
> has the word-synced copy. So the stored answer is let go of
> first. Only the fetched one: a document dropped on the window
> or aligned on this machine is not the chain's to forget.

**line 9675** — before `self.drop_pixmaps()`  *(the call is gone; see below)*

> The cover is picked up by poll() on its own -- it watches the
> url and reloads when it changes. Nothing watches the album.

> **Since:** the call this was written against has been removed, and the
> reasoning above is why it could be. on_card emptied every drawn line and
> every glow whenever the catalogue came back with an album or a title for
> the song already playing. That is the invalidation drop_pixmaps says at
> length was the stall, wearing a different hat -- and worse placed than the
> one that was taken out, because a card lands a second or two into a track,
> which is inside the window a track change gets complained about.
>
> A card is not a different track. It is the catalogue agreeing with the
> player about the song that is already up, and nothing it carries is in
> either cache's key -- those are the words, the width, the blur, the size,
> the alignment, the script, the font and the pen. So every picture it threw
> away was asked for again on the next frame and rebuilt from nothing, at the
> 26ms-on-the-landing-frame and 48ms-over-the-six-after that drop_pixmaps
> already prices. Art that moves the palette moves the pen, and a moved pen
> misses on its own account without anything having to be dropped.


## `LyricsView.closeEvent`

**line 15492** — before `LS.offload.shutdown()`

> concurrent.futures already joins its workers at a normal exit, so this is
> for the other kind. A window that goes down hard leaves its pool forked and
> parentless -- seen while measuring, where a harness that called os._exit
> left two workers running after everything that knew about them had gone.


## `Clock.resync_soon`

**line 3611** — before `def resync_soon(self) -> None:`

> Both of the round trips resync makes are the question Pump exists to keep
> off the thread that draws, and resync was making them on it -- 800ms after
> every automatic hand-over, which is to say in the middle of the few seconds
> a track change is complained about.
>
> Measured across a real hand-over on this machine, timing io.read at 60Hz
> either side of the change:
>
>     while the song simply plays     median 1.00ms   p95 1.41   worst 7.10
>     the first second after it       median 0.99ms   p95 111     worst 263
>     t+1s onwards                    median 0.97ms   p95 1.51    worst 1.60
>
> Five reads over a frame's budget in that first second and the worst of them
> 263ms, which is sixteen frames from one call -- and resync makes two calls,
> the read and then the seek. The Pump's own docstring had already said this
> would happen and named the state it happens in; what was missing was that
> resync was exempt from it.
>
> Threaded rather than handed to the Pump, because the Pump is a loop with a
> cadence and this is one errand. One at a time, because a reading that is
> taking most of a second must not be answered by starting another, and a
> resync that raises is swallowed: it is a correction worth 0.2s of sync, not
> something to take a thread down over.
>
> The scheduling stays a QTimer in poll(), where the `handed_over` and
> `self.resync` tests already live -- a manual skip inside three seconds is
> still not resynced, and neither is a paused player.


## `LyricsView.poll`

**line 9734** — before `self.on_player(getattr(self.clock.io, "app", DEVICE_APP))`

> Who is playing, for the standing offset. A string already on the
> transport, so this is a comparison and nearly always nothing; the
> output beside it costs two subprocesses and is watched on a thread
> for that reason. See on_player.

**line 9758** — before `self.on_lyrics(*self.vet_body)`

> Fetched a moment ago to find out whether this was a song at
> all. Putting it straight up is not an optimisation of the
> request reset_track just made -- it is the words being there
> the instant the song is, having already been waited for once.

**line 9773** — before `want = (POLL_MS_EDGE if left < 3.0`

> Both of the rates this used to run at while paused were about the
> CLOCK -- how long after an unpause the words move at all, and how
> long the leap took to arrive. The sampler answers both of those in a
> sixtieth of a second now, whatever this timer is doing. What is left
> to hurry for is a screen still waiting on a lyric.

**line 9805** — before `self.motion_key, self.motion_frames = "", []`

> A track with no album and no title to look one up by, or the
> setting switched off. The frames belonged to the song before it
> and are a couple of hundred megabytes; letting go of them was
> only ever done on the way IN to another animated cover, so a
> song without one kept the last one resident for as long as it
> played.


## `LyricsView.apply_romaji_fixes`

**line 9833** — before `self._ink_gen += 1`

> The pieces a drawn line is keyed by have just changed under
> it. See line_ink.


## `LyricsView.rebuild_lines`

**line 9945** — before `self.layout_cache.clear()`

> Same words, re-folded: every line that survives the new gap keeps
> its picture. See line_pixmap.


## `LyricsView.show_dropped_lyric`

**line 10020** — before `LS.forget(tid)`

> The stored lookup would otherwise answer for this track before
> anybody asks the local slot, and the drop would come back only
> until the cache aged out.


## `LyricsView.restore_dropped`

**line 10062** — before `return False`

> The drop path says so out loud, because somebody is standing at
> the window watching for it. Nothing asked for this one, so a
> track that cannot be read falls back to the song's own lyrics
> without a word about a file the user has not thought about
> since yesterday.


## `LyricsView.show_live_lyric`

**line 10097** — before `self.own_body = self.body`

> The song's own document, kept aside before the editor's takes
> the screen. Without it "fetch what the player is showing"
> answers with whatever the editor last pushed -- which is the
> editor's own file, handed back to it as if it were a source.


## `LyricsView.follow_editor`

**the unmute** — before `self._unmute_for_editor()`

> Once the player has stopped, not once THEY have. The pause is a command
> and `_transport` only sends one every FOLLOW_STEADY, so unmuting on their
> pause alone put Spotify back to its own volume while it was still playing
> -- up to six tenths of a second of the song out loud, every time somebody
> stopped to fix a word. Staying muted is the safer way round to be wrong:
> a muted player that should be audible is handed back by the next tick, or
> by `unfollow_editor` when the editor goes.


## `LyricsView._follow_to`

**the whole of it** — why the seeking is rationed

> TWO REASONS, and the second one is what made the link look as though it
> had cut in the middle of a sync.
>
> A seek is not finished when it returns. `Clock.seek` writes the target
> straight into its own reading, because it knows where it sent the song and
> nothing else does until the sampler brings the player's answer back -- so
> the drift reads zero for a poll or two whatever actually happened. Asking
> again inside that window is asking before the answer to the first question
> has arrived, which is the same thing `_transport` says about its own
> command.
>
> It waits FOLLOW_AGAIN and not the FOLLOW_STEADY that command waits,
> because the two are behind different things: a play state takes Spotify a
> poll or two to report, where a seek shows up in the very next reading the
> sampler takes. Rationed at the longer figure, following somebody scrubbing
> their own waveform would lag half a second behind the pointer.
>
> AND WHERE THE PLAYER WILL NOT GO, THE DRIFT NEVER CLOSES. A paused Spotify
> ignores SetPosition, and so does a position outside the track it has open.
> This is reached eight times a second off the editor's follow --
> `LiveLink.follow` is a direct connection to a QObject on the GUI thread --
> and every seek is three round trips on the session bus (CanSeek, Metadata,
> SetPosition), made from the thread that draws the words and taken under
> `SessionTransport._gate`, which is the lock the sampler reads through.
>
> So a target the player would not take was an unbounded stall on the one
> thread that has to keep drawing. All three of the symptoms reported fall
> out of that single fact: the sweep stops, the editor's pushes stop being
> read off the socket and land late in a lump, and the clock is left
> anchored at a moment that has gone, so the words are drawn at times
> nobody stamped. Somebody timing a song by ear sits paused for most of a
> session, which is exactly when the two sit still at different places and
> never converge -- and why it showed up partway through rather than at the
> start.
>
> The same place is therefore asked for FOLLOW_TRIES times and then left
> alone until the editor asks for somewhere else. A moving target -- their
> file playing on, a line being dragged -- is a new question every time and
> is never given up on. `tests/test_livelink.py` pins both halves.


## `LyricsView.unfollow_editor`

**line 10205** — before `self.clock.command("PlayPause")`

> Not player_do: this is the window tidying up after the editor,
> not a key somebody pressed, and there is nobody to tell.


## `LyricsView.show_dropped_art`

**line 10250** — before `self.on_art("", (img, blurred, palette_of(img)), dropped=True)`

> Said outright rather than left to the order of the two lines below
> it: a second picture dropped on a song already wearing one is still
> a picture somebody dropped, and reading it off dropped_art would
> have this refuse it.


## `LyricsView.reset_track`

**line 10273** — before `self.unfollow_editor(pause=False)`

> Whatever was being timed, it was being timed against the song that
> was playing. Hand the player back rather than leaving it muted on
> the next one -- but leave it PLAYING, since the track changing is
> somebody listening to something, not somebody stopping.

**line 10301** — before `self.restore_dropped()`

> Before the request, not after it: a document already on this
> disk is the one the window can draw this instant, and the walk
> it is about to start cannot beat it -- it is not allowed to draw
> over it at all. See restore_dropped. The request still goes out,
> because the song's own lyric is what R and the editor ask for
> and what on_lyrics files away as `own_body` when it lands.


## `LyricsView.on_art`

**line 10369** — before `self._art_fails[url] = self._art_fails.get(url, 0) + 1`

> The download gave up. Nothing would ever ask again: art_url is
> set to the wanted url before the thread starts, so the poll's
> own "have we already asked for this one" is what kept the song
> on the last song's cover for the rest of its play. Handing the
> url back is what lets the next poll ask afresh -- a few times,
> and then no more, because a url that is genuinely gone should
> not be asked for four times a second until the track changes.


## `LyricsView._swap_offset`

**line 10487** — before `self.offset = round(float(self.dev_offsets[self.device]), 3)`

> A player heard for the first time out of an output that HAS
> been tuned. The output's own number is the better guess than
> zero and than whatever the last player wanted -- most of what
> is being corrected is the speaker -- and it is also every
> settings file written before the player was part of the key, so
> a corpus tuned by ear on a headset carries over rather than
> being thrown away the first time a browser plays into it.

**line 10497** — before `self.dev_offsets[key] = round(self.offset, 3)`

> Neither the pairing nor the output has been heard from. Inherit
> what is set now: a guess, but the guess that changes nothing,
> and the first nudge on it writes the real number.


## `LyricsView.on_device`

**line 10552** — before `if was:`

> The output has gone -- no pactl, another platform, the sink
> closing under us. Put the live number away under the pairing it
> belonged to, since there is nothing to take out in its place and
> losing it would cost whatever was tuned by ear on that output.

**line 10560** — before `if was:`

> Nothing is said about the output the window came up on: that is not
> a change, it is where it started.


## `LyricsView.unpause_delay`

**line 10644** — before `self.clock.unpause_delay = max(-1.0, min(1.0, float(v)))`

> Held inside the range the menu offers, and that range reaches below
> zero. It used to be max(0.0, ...), which is what the setting meant
> when the only correction was a hold; with the measurement able to
> push the words forward as well, that clamp was silently throwing
> away everything the menu let anybody dial in on the negative side
> -- the row read -0.20s and the clock got 0.


## `LyricsView.on_lyrics`

**line 10715** — before `if body is not None and self.own_body is None:`

> An editor's document is on screen, so this one is not drawn --
> but it IS kept. It is the song's own copy, which is what the
> editor asks for with source_doc and what R was pressed to go
> and fetch; dropping it on the floor here is how a reload made
> under a live document came to have no effect anybody could see.

**line 10725** — before `return`

> Nothing to put up and something already up: keep what is there.
> The one exception is a reload that has now been answered with
> nothing -- R is how somebody shakes a bad answer loose, and a
> window that went on showing the old one would have said the key
> did nothing at all. `done` is the fetcher saying it has finished
> asking, so the empty first pass of a walk still does not count.

**line 10736** — before `self.body = body if body is not None else self.body`

> The same words at the same times, arriving again. It happens on
> nearly every song and more than once: the interim goes up off
> Spicy Lyrics' copy, the walk reports its best answer as it
> lands, and then the load returns that same answer as its own --
> three handovers, two of which draw exactly what is already
> there. Keep the newer document, because it is the one carrying
> the credit, and leave the screen alone.

**line 10751** — before `self.japanese = any(SL.KANA.search(ln.get("text") or "")`

> Asked of the whole document, not of the line being drawn: a Japanese
> lyric has lines that are all kanji, and one of those is not a Chinese
> song. One of THESE is.

**line 10762** — before `self.layout_cache.clear()`

> The LAYOUT goes, because it carries the times and this is a
> document that disagrees about them. The drawn lines stay: they
> are keyed by their ink, and a better answer mid-song is nearly
> always the same words with a better clock under them. Throwing
> them away here is what made a refresh stall the window.


## `LyricsView.say_alignment_outranked`

**line 10835** — before `return`

> What is held for this track is the file on screen. Nothing has
> outranked anything, and saying so under somebody's own document
> would send them to the Sources menu to fix a running order that
> is not deciding this.


## `LyricsView.source_name`

**line 10935** — before `was_really = {"apple": "apple", "qaple": "blend", "qq": "qq",`

> The same names as this program's own source keys, for the reading
> below: a door is not a catalogue, and where the two disagree it is
> the catalogue that gets printed.

**line 10941** — before `if self.dropped is not None and self.dropped == self.clock.tid:`

> A document somebody is writing here is not a document from a
> source. Its payload carries no `_source` at all, so this used to
> fall all the way through to "Spicy Lyrics" and credit the work to a
> database that has never seen it.

**line 10949** — before `upstream = was_really.get(str(doc.get("_via") or "").lower())`

> LyricsPlus' server has no filter for its own submissions: asked for
> them by name it hands back its Apple+QQ reconciliation instead
> about a third of the time, and a document of Apple's words with
> QQ's clock is that, whichever door it came through. It is refused
> at the door now (see _honoured in lyric_sources), but the ones
> fetched before that are still in the cache, so the reading is put
> right here as well -- every copy this program has filed under
> lyricsplus is one of them.

**line 10990** — before `return f"{name} · {was}" if was and was != name else name`

> Pinned to one upstream, the "via" only repeats the name already
> printed -- "Apple Music · Apple Music", and a blend's name already
> spells out everything its makeup would.


## `LyricsView.made_by`

**line 11015** — before `words = str(doc.get("_words_by") or "").strip()`

> Who vouched for the WORDS, which is a different credit and is why
> it is a different field. A Genius document is timed here, off the
> audio -- nobody named in `_words_by` made this sync, and LS.credited
> does not read it, so judge_sync cannot enrol them in a roster about
> timing. See genius_roman.credit_of. Printed last because the line
> reads best from this copy outwards: who timed it, then what the
> source says about the words underneath.


## `LyricsView.credit_rows`

**line 11039** — before `if str(doc.get("_source") or "") == "unison":`

> Unison asks to be named with its address wherever its words are
> shown, and this footer is the one place the window names a source to
> somebody who is reading the song rather than choosing where it comes
> from. Its lines also reach the screen under a blend's clock, and
> there the blend's own name says nothing about who wrote them: `_via`
> names the document they were taken from (see LS._blend), so the
> credit is added beside the blend's name instead of replacing it.

**line 11052** — before `got = getattr(self, "fetcher", None)`

> A mask left standing is a decision, and a decision nobody is told
> about reads as a source that failed quietly. See LS.clean_edit.
>
> Except where the decision was somebody's own: a hand-typed sync's
> masks are that person's reading of what they heard, nothing has
> gone wrong, and there is nothing here for the reader to do about it
> -- the names would only be printed twice, once as the reason and
> again on the credit under it.


## `LyricsView.set_people`

**line 11127** — before `keep = [n for n in getattr(self, other)`

> Nobody is on both lists: Roster would drop them from the pick side
> anyway (a refusal is the stronger statement), and a name sitting in
> a list that is being quietly ignored is a setting that lies.

**line 11139** — before `self.reset_track("Reloading…", keep=True)`

> reset_track rather than reload_lyrics, for the one thing it adds:
> it marks the track as reloading, which is what lets on_lyrics
> take an empty answer over what is up. Refusing the only person
> who had the song has to be able to clear the screen -- otherwise
> their sync sits there, refused and still being read, until the
> track changes.


## `LyricsView.fetch_meta`

**line 11345** — before `"explicit": m.get("explicit")}`

> Not for finding the song -- nothing searches on it. It rides
> along because this dict is what reaches LS.clean_edit, and it
> is the best answer there is to "is the cut being played the
> clean one". None where the player did not say.


## `LyricsView`

**line 11433** — before `def troll_aim(self, idx: int) -> int:`

> -- trolls ----------------------------------------------------------


## `LyricsView.troll_aim`

**line 11460** — before `at = (idx, lines[idx].get("start") if idx < len(lines) else None)`

> Which line, and which line's start: the index alone would carry a
> skew decided on one song into line 12 of the next one, and there is
> no moment between those two documents when this is asked and the
> index has changed.

**line 11473** — before `want = [-1, 1]`

> Which way, out of the two it can actually go: at either end
> of the song only one of them is there, and a skew off the
> end of the list is no skew.
>
> A run mostly carries on the way it was going -- a column
> that is a line behind stays a line behind for a while -- but
> it is re-asked every line rather than fixed when the run
> starts. Fixing it meant the FIRST roll of a song decided the
> direction for the whole of it, and the first roll lands on
> line 0 about as often as not, where -1 does not exist. So
> every play came out one line ahead, all the way through,
> and the other half of the joke was never seen.


## `LyricsView.searching_now`

**line 11527** — before `self.search_goal = self.scroll_target`

> No leg yet and no previous frame: the first frame of the bout picks
> one and takes the nominal step, where `now` would mean a first frame
> of no elapsed time and so no movement.


## `LyricsView.troll_search`

**line 11581** — before `self._search_leg()`

> Nothing has ever been hunted for on this window: there is no
> pace yet to work the frame's step out from, and a step of zero
> would stand still for the one frame a bout can least afford it.

**line 11587** — before `left = self.search_goal - self.scroll_target`

> Arrived, and gone again on the same frame: whatever is left of
> the step is spent on the next leg, so the pace does not stutter
> at the turn. Bounded rather than a while, because a leg can be
> shorter than one frame's travel near an end of the document and
> a run of them must not be able to hold the frame.


## `LyricsView`

**line 11603** — before `def instrumental(self) -> bool:`

> -- geometry --------------------------------------------------------


## `LyricsView.wrap_pieces`

**line 11701** — before `adv = [advance(fm, pc[2]) for pc in word]`

> Measured once and kept. The loop below needs the width of every
> one of these again, and for all but the last of them it is the
> identical question -- only the fragment that carries the trailing
> space has to be asked afresh, because the space is inside the
> measurement rather than added to it. Text measurement IS the cost
> of a cold layout: two calls a fragment, eleven thousand fragments
> in a long song, and it is the one thing in here that goes out to
> the font. A word too wide to fit is re-cut and the measurements
> go with the pieces they were taken from, so that branch drops
> them and asks again.


## `wrap_shape`

**line 1104** — before `def wrap_shape(pieces, fm: QFontMetricsF, width: float, align: str):`

> The geometry, split out of the clock. Where a word goes is decided by its
> text, the face and the width; when it is sung is decided by the document.
> Those were one loop, so a better source arriving mid-song -- the same words
> with a better clock -- threw away every row in the column and worked out
> again, from nothing, that nothing about the shape had changed.
>
> Shapes are kept on the QFontMetricsF for the reason advance() is kept there
> and with the same working set: one song's distinct lines at the widths it
> has been shown at. It needs no invalidating, because a new face is a new
> object and _lyric_face is what holds them.
>
> A row entry carries the piece it came from and, where the piece had to be
> cut up, which chunk of it -- that is all stamp_rows needs to put the times
> back. The chunk LENGTHS are kept rather than the times, because the cut is
> made on characters and split_to_fit interpolates across them, so the same
> lengths give the same spans under any clock.
>
> Held to the old loop line for line: tests/test_layout.py keeps a copy of
> wrap_pieces as it stood and lays every line of all 58 documents here out
> both ways, at three sizes, three widths and three alignments -- 97794
> layouts, and then 4020 more with the clock moved underneath, which is the
> case this is for. Every one identical.


## `stamp_rows`

**line 1187** — before `def stamp_rows(shape, pieces):`

> The times, written onto a shape. The arithmetic for a cut-up piece is
> split_to_fit's own, and the untimed case falls out the same way it does
> there: the first chunk carries the whole span and the rest sit empty at the
> end of it. That is not a decision made here, it is the old behaviour kept.


## `LyricsView.layout_line`

**line 10063** — before `fm = self.lyric_fm(ln["background"])`

> This built a QFontMetricsF of its own -- `QFontMetricsF(self.lyric_font(...))`
> -- which quietly undid the two memos that hang on a face. Both advance() and
> wrap_shape keep what they know on the QFontMetricsF object, exactly so that
> emptying the layout cache does not empty them; a fresh object every line of
> every layout meant they started empty every line of every layout.
>
> It showed up in a profile rather than in a reading: a whole-document re-plan
> with both memos supposedly warm was still making 945 calls to
> horizontalAdvance, which is very nearly one per fragment -- the number a
> completely cold layout makes. lyric_fm hands back the metrics _lyric_face
> already built for that font, which is the same metrics this was
> constructing, so nothing about the numbers changes.
>
> Measured over the 63 lines of "NF - Time", laying the whole column out with
> layout_cache emptied each time:
>
>     a first cold plan                  30.9ms  ->  26.1ms
>     a re-time, everything else warm     3.39ms ->   0.34ms
>
> 0.34ms is what the open half of the TODO entry was asking for. It says
> "3.7ms is not the cost of laying a document out, it is the cost of
> discovering that nothing about it changed", and that is now a third of a
> millisecond.

**line 11805** — before `rows = [(n, r) for n, row in enumerate(ln["credits"])`

> Each wrapped row remembers WHICH of the credits it came out of.
> The block is a few separate things -- the songwriters, then where
> the copy came from, then who timed it -- and only the first of
> them is the song's own credit and drawn bright. Flattened to
> plain rows the painter had nothing to go on but the row number,
> so a list of songwriters long enough to wrap went dim halfway
> through: the second line of one credit was being drawn as though
> it were the next credit down.


## `LyricsView.ruby_rows`

**line 11850** — before `if not self.furigana or not rows or self.roman == "instead":`

> Which reading goes over which script is `SL.ruby`'s decision, not
> this one's: kana over kanji, pinyin over hanzi, Revised
> Romanization over a Hangul block. What this has to pass on is
> whether the DOCUMENT is Japanese, because Han characters are shared
> and nothing in a line of them says which language they are being
> read in -- pykakasi read 低音吉他, Chinese for "bass guitar", as
> ていおん・きち and set that over the credits.


## `LyricsView`

**line 11885** — before `def drift_of(self, key, x0: float, y0: float, w: float, h: float):`

> -- animation -------------------------------------------------------


## `LyricsView.tick`

**line 11947** — before `self.step_drift()`

> None of the easing below reaches a screen, so only the three
> things that have to go on running do. The quit path is one of
> them: a SIGTERM sets quit_requested and nothing else reads it,
> so skipping it here would leave a minimised window ignoring it.
> The animation resumes from wherever it left off.

**line 11974** — before `hunting = self.searching_now()`

> Asked before the browse ease rather than beside the scroll, because
> a bout reads as somebody scrolling and has to LOOK like it: the
> lines going past are lifted out of the distance fade exactly as they
> are for a hand on the wheel, or the whole bout is a dark smear
> through a song nobody can see.

**line 11988** — before `self.focus_idx = SL.focus_index(self.lines, pos, self.scroll_lead)`

> Worked out whether or not the column is free to follow it: the
> blur reads this too, and a reader who has scrolled away by hand
> still gets the song's own line drawn sharp when they come back.

**line 11995** — before `self.troll_search()`

> The column has lost the words and is looking for them, so it
> is not taking direction from the song for the moment. The ease
> is nearly off underneath it as well: the hunt is already a
> speed, and easing toward a target that is itself moving at that
> speed only adds lag to it.

**line 12004** — before `want = self.troll_aim(self.focus_idx)`

> Asked once a frame and only here: the answer is where the
> column stops, and nothing else in the view is entitled to it.


## `LyricsView`

**line 12077** — before `def drop_pixmaps(self) -> None:`

> -- text pixmaps, so distant lines can be blurred cheaply -----------


## `LyricsView.tick` — the scroll spring

**line 10244** — before `if (abs(gap) > self.height() and self.synced and not hunting`

> A jump the length of the window is not a scroll anybody follows, and easing
> across one costs a picture for every line it passes.
>
> reset_track puts `scroll` back to 0, so when the lyrics land a second or two
> into a track the column springs from the top down to wherever the song has
> already got to -- at 0.12 a frame, which is a lot of frames. Every line it
> sweeps past is drawn, and each is far from the one being sung, so each wants
> its own picture at or near MAX_BLUR, and each is a line no picture exists for
> at any blur. Caught in the act, offscreen, with the sung line at 57: pictures
> being built for lines 3, 4, 5, 6, 9, 10 ... 42, all at blur 9, twenty-four of
> them inside a seventh of a second.
>
> Snapping instead took the forced builds over a 50s run from 26 to 9 and the
> frames that build more than the ration from 10 to 2. Ordinary line-to-line
> easing is untouched -- that is a fraction of a screen and it is the part that
> looks like anything. Guarded on `synced` and on `user_scroll_until` so a
> wheel is still a wheel, and left alone while `hunting`, which has its own
> faster spring and means to sweep.


## `LyricsView.line_pixmap`

**line 10351** — before `if self._new_left <= 0:`

> The ration has an escape hatch -- a line with no picture at ANY blur has no
> substitute to hand back, so it is built whatever the ration says -- and the
> hatch had no bound. On the frames where it matters that is every visible
> line at once: when a document lands, nothing has been drawn yet, so eight or
> nine lines are all first sightings and all go through on one frame.
>
> Measured over a cold 2400-frame sweep, the worst frame against the size of
> this allowance:
>
>     allowance   median   p95    p99    worst
>     unbounded    2.10ms  3.78   5.65   46.20
>     4            1.93    3.45   5.72    9.70
>     2            1.49    2.92   4.93    8.47
>     1            1.37    2.33   4.02    5.63
>
> Two, because the ration builds two as well: four pictures a frame fills a
> cold column of eight in two frames, which is 33ms, and nobody sees a column
> arrive a frame late. They do see a 46ms frame.
>
> What the bound costs is that line_pixmap can now hand back None, and a line
> with no picture draws nothing for a frame. Every caller that draws one
> checks -- there are four, in _paint_line twice, the unsynced path and
> all_glow. _warm_next does not, because it only ever calls with ration in
> hand.

**line 12105** — before `pen = self.base_color(self.lines[idx]) if pen is None else pen`

> The pen is in the key. It is the one thing here that can change
> without the cache being cleared: the palette a duet's second voice
> is tinted from arrives with the album art, a moment after the lines
> are already on screen and drawn in the placeholder colours.
>
> It is also an argument, because the ink is the only thing that
> separates a picture of the line from a picture of its LIGHT. The
> column wants the line in its own base colour; Flow.all_glow wants
> the same line, same width, same type, in the sung colour, to blur
> into a halo. Two pens, one builder, one cache -- a glow that is only
> ever a colour away from a picture already being kept is not worth a
> second cache, a second budget and a second thing to empty.

**line 12118** — before `key = (self.line_ink(self.lines[idx]), int(width), blur,`

> Keyed by what is DRAWN, not by which line it is. A pixmap here is
> glyphs and nothing else -- the fill, the rise and the glow are all
> painted live over the top -- so two lines that read the same are
> the same picture, and, far more usefully, a line is still the same
> picture after a better source arrives.
>
> That is the whole point. A better answer mid-song is normally the
> same WORDS with a better clock under them, and keying on the line
> number threw away every drawn line in the column for that: the
> refresh cost 26ms on the frame it landed and 48ms over the six
> after it, measured here, which is the stall that showed up as "it
> lags when it finds a better source". Keyed on the ink, a document
> that only re-times the song rebuilds nothing at all.
> The font is in the key by name rather than by "the family changed,
> so empty the cache": it is the last thing about a drawn line that
> was not, and putting it in is what lets the invalidations below go
> away entirely.

**line 12143** — before `near = self._nearest_blur(key, blur)`

> Out of ration for this frame. The same line at a neighbouring
> blur is the same words at very nearly the same softness, and one
> frame of it is not a thing anybody can see -- whereas building
> the eleventh picture on a line switch is. Nothing is cached
> under the wrong key: this hands back a substitute for one frame
> and the real one is built on a later one. See PIX_PER_FRAME.

**line 12152** — before `rows, fm, h, rrows, rfm, ruby, rufm = self.layout_line(idx, width)`

> Nothing of this line at any blur, so there is no substitute and
> it has to be built: a line with no picture at all draws nothing.


## `LyricsView.glow_pixmap`

**line 12217** — before `key = (txt, font.toString(), radius)`

> The whole font, not just its size: the family and the weight change
> the shape being blurred, and a key that forgets them hands back the
> last font's glow. See drop_pixmaps, which is allowed to leave these
> alone precisely because the key is complete.


## `LyricsView.scene_layer`

**line 12285** — before `key = (W, H, tuple(c.rgb() for c in self.palette), self.art_gen,`

> The mesh fields go on the END, past viz_live(), because VIZ_IN_KEY
> is an index into this tuple and scene_mix counts on it.

**line 12296** — before `if (self.bg_fade > 0 and self._scene_pm is not None`

> A KEY change is a different wall -- another cover, another section,
> another mode, the visualizer arriving. The same key coming round
> again is only the drift being redrawn, and that is already smooth.
> So the one is worth fading and the other must not be, or every
> fifteenth of a second would start one.

**line 12305** — before `old_key = self._scene_key`

> Whether this change is ONLY the visualizer coming or going. In
> mesh mode the two walls either side of that are not independent
> pictures: the still mesh is left out of the lit one precisely
> because the visualizer is about to draw it driven, and painting
> both doubles every blob. Crossfading them on a clock of its own
> while the visualizer fades on another put the two out of step
> and the overlap is a flash of light between two dark walls.
>
> So a change of this one field is handed to the visualizer's own
> mix below, and the two are then exactly complementary.

**line 12326** — before `self._paint_mesh(p, W, H, t)`

> The live mesh IS this, driven -- painting both would double every
> blob and leave the still copy showing through the moving one.
> Only bloom, though: the other modes leave most of the window
> theirs to fill, and dropping it under those empties the wall.
>
> And only blobs. bloom draws blobs whatever this is set to, so
> under a wash or a veil the two are not the same picture at all
> and standing the wash down would leave the window black behind
> the driven lights, which is the opposite of what a wash is for.


## `LyricsView.viz_face`

**line 12410** — before `d = self.VIZ_DIVS.get(self.viz_mode, self.VIZ_DIV)`

> The layer is built at a REDUCED size -- VIZ_DIVS -- and blown back up
> by the painter, so it is never the size of the window and must not be
> compared against it. What matters is that it still matches the
> divisor this window width would use; anything else is a picture from
> before a resize, and the new one arrives next frame anyway.


## `LyricsView.scene_mix`

**line 12435** — before `k = self._viz_mix if self._scene_viz else 1.0 - self._viz_mix`

> The visualizer arriving or leaving. How much of the new wall to
> show is how far the visualizer is in -- or out, when the new wall
> is the still one -- so the light the wall gives up is exactly the
> light the visualizer takes over, and the two never overlap.

**line 12449** — before `k = max(0.0, k)`

> Smoothstep, so it leaves and arrives at rest. A linear crossfade
> between two full-window pictures reads as a wipe with a hard start.


## `LyricsView`

**line 12458** — before `VIZ_DIV = 3`

> -- visualizer ------------------------------------------------------

**line 12459** — on `    VIZ_DIV = 3`

> paint at a third size, then blow it back up

**line 12460** — before `VIZ_DIVS = {"bloom": 3, "tide": 3, "pulse": 2, "bars": 1}`

> Per mode, because the divisor is only free where the shape has no detail
> in it. Blobs and water are gradients a few cycles across the window and
> lose nothing; a column with an edge on it would come back as a smear.

**line 12464** — on `    VIZ_ALPHA = 124`

> per blob at full strength, before the track scales it

**line 12465** — on `    VIZ_SAT = 0.52`

> saturation floor for the blobs; 0 keeps the palette

**line 12466** — before `VIZ_NEEDS = {"bloom": "pitch", "bars": "pitch", "pulse": "beats", "tide": "segs"}`

> What each mode cannot draw a frame without. Chroma is the part of an
> analysis most often missing, and the part worth least on a track built
> out of drums -- a mode reading only the grid still has all it needs there.


## `LyricsView.viz_layer`

**line 12603** — before `bands = self.viz_bands(dt)`

> Eased every frame whoever is painting, so switching mode mid-song
> arrives at chroma already settled rather than climbing from nothing.


## `LyricsView._viz_bloom`

**line 12635** — before `share = 2.5 / max(2.5, n)`

> These are added, not laid over, so the blobs share one budget: four
> of them at a weight that suits one puts a wall of light on the
> window wherever two overlap, and the album art under it is gone.

**line 12643** — before `reach = max(lifts) - min(lifts)`

> Distortion smears chroma across every class at once, so on a loud
> guitar all four slices read alike and the blobs move as one lump.
> Pulling them apart by their own spread keeps them telling apart
> there; material with real harmonic contrast is already spread and
> comes back barely touched. Only where the vector is pitched at all,
> though: on drums this is a noise amplifier, and the gate in
> viz_bands is undone by exactly the step that follows it.

**line 12659** — before `kick = self.viz_kick() * (1.0 - 0.18 * i)`

> Staggered so the kick travels across the blobs rather than
> flashing the whole window at once.
> Staggered off the eased envelope, so the beat still travels
> across the blobs but arrives at each of them as a rise.

**line 12668** — before `a = self._viz_a(share * (0.55 + 0.30 * loud) * (0.70 + 0.30 * lift))`

> Swing kept narrow on purpose. The eye reads a change in light
> far more readily than a change in size, so the loudness is spent
> mostly on the radius and only a little on the alpha -- a blob
> that halves in brightness twice a bar is a flash, not a pulse.


## `LyricsView`

**line 12679** — on `    VIZ_RING = 1.35`

> seconds a ring takes to cross the window and go out


## `LyricsView._viz_pulse`

**line 12699** — before `a = self._viz_a(1.9 * (1.0 - age) ** 1.7 * strength`

> A ring is a thin band where a blob is half the window, so it
> needs the weight a blob does not: the same alpha spread over
> a twentieth of the area reads as nothing at all.

**line 12720** — before `core = tint[self._section % n]`

> A core under the rings, so a bar's rest still has something standing
> in the middle rather than an empty window between beats.


## `LyricsView._viz_bars`

**line 12752** — before `v = (bands[cls] if cls < len(bands) else 0.0) ** 2`

> Squared, because the twelve arrive normalised to their own
> peak and sit high: read straight, a triad differs from the nine
> classes it is not by a few pixels of column.


## `LyricsView`

**line 12908** — before `def paintEvent(self, _ev) -> None:`

> -- painting --------------------------------------------------------


## `LyricsView._paint_window`

**line 12977** — before `p.setOpacity(self._viz_mix)`

> Rides the beat zoom with the scene under it: they are one wall.


## `LyricsView._paint_panel`

**line 13040** — before `px0 = self.panel_x()`

> Every x below is measured from the panel's own left edge, which is
> the window's unless the art has been sent to the other side.


## `LyricsView._paint_volume`

**line 13144** — before `vol = (self.vol_drag if self.vol_drag is not None else`

> The drag first, then what the wheel has asked for and the player
> has not been told yet, then the player's own. Anything still owed
> is drawn as though it had landed -- it is what the hand asked for,
> a frame or two of round trip is not something anybody should watch
> the bar wait out, and `flush_volume` makes it true directly.


## `LyricsView`

**line 13479** — before `# -------------------------------------------------------- browse painting`

> -- search ----------------------------------------------------------

**line 13481** — before `ROW_PAD = 8.0`

> What a list row keeps clear above and below its two lines of text.


## `LyricsView.browse_metrics`

**line 13490** — before `r_t = QFontMetricsF(self.ui_font(max(11, W * 0.0105))).height()`

> A row is as tall as what goes in it. It was a flat 56 while the two
> fonts inside it were sized off the window, so on a big enough screen
> the pair no longer fit: the name sat mid-row and the artist under it
> spilled out of the bottom, landing against the next row's name and
> reading as if it belonged to THAT song. These are the same two fonts
> _paint_browse_search and _paint_browse_queue ask for.


## `LyricsView._paint_hit_row`

**line 13991** — before `nh, sh = fmt_.height() * 1.2, fms.height() * 1.3`

> Centred as a pair rather than hung off the top of the row, so
> the name and the artist under it stay one block whatever the
> row is worth on this window. See browse_metrics for the height.


## `LyricsView`

**line 14094** — before `REV_INK = {"error": QColor(255, 104, 104),`

> What a finding is drawn in. Three colours for the three weights, and
> nothing else on the page is coloured, so a page with no red in it is a
> document with nothing wrong that this knows how to see.

**line 14101** — before `REV_SEAM = QColor(112, 222, 192, 205)`

> The seam between two pieces of one word. A colour of its own, and
> deliberately not one of the three above: a seam is not a finding, it is
> the document's own structure being shown, and drawn in the blue a note
> is drawn in it would read as one.


## `LyricsView.build_review`

**line 14166** — before `title=str(self.clock.meta.get("title") or ""),`

> What the service says the song is. The file itself mostly
> cannot say: an Apple-style head carries the songwriters and
> nothing else, so "(feat. Somebody)" is known here and
> nowhere in the document. See review._check_credits.

**line 14173** — before `self.review = self.review_at = self.review_body = None`

> A screen that cannot be built is not a reason to lose the
> window: this is a reader, and the thing it is reading came off
> somebody's disk.


## `LyricsView.review_plan`

**line 14247** — before `key = (self.review, int(W), self.review_all, self.review_rule,`

> The REPORT itself sits in the key, not its id(). A plan holds the
> rows and chips of the report it was laid out from, so handing back
> one built for another report is the page showing a review of a
> document that is not on screen -- and an id is exactly the kind of
> thing that can be right for the wrong reason: the old report is
> freed the moment `self.review` is reassigned, and the next one is
> entitled to be allocated at the same address. Keeping the object in
> the key both compares honestly (Report has no __eq__, so this is
> identity) and keeps the address from being handed out again while
> the plan is still alive.

**line 14290** — before `open_ = bool(also) and (row.n, row.kind) in self.review_open`

> The repeats are drawn by the painter, not written into `notes`:
> closed they are one line, open they are one line each and every
> one of them is somewhere to click. All this has to settle is how
> much room to leave.


## `LyricsView._paint_review`

**line 14321** — before `sepw = fm.horizontalAdvance("·")`

> The gap the plan left between two pieces of one word, so the tick
> drawn in it stands in the middle of the space it was measured for.

**line 14325** — before `self.review_sel = max(0, min(self.review_sel, len(plan) - 1))`

> The selection is kept in range HERE rather than wherever the list
> changed under it, because this is the one place that knows how long
> the list came out -- and everything that can shorten it (another
> tab, a document pushed from the editor, the filter) goes through
> here on the next frame anyway.

**line 14334** — before `view_h = max(40.0, H - top - 12)`

> The scroll is CLAMPED here rather than where it is changed, because
> this is the only place that knows how tall the page came out. The
> easing toward it is tick's, like every other ease in the window, so
> that a page being scrolled asks for frames at the rate an animation
> needs rather than at the rate an idle window gets.

**line 14347** — before `p.setFont(f)`

> Nothing to list. Two quite different reasons, and the difference
> is the only useful thing that can be said here.

**line 14376** — before `p.setFont(fn)`

> -- the gutter: which line, and when it starts

**line 14395** — before `p.setFont(f)`

> -- the words, with their seams and their marks

**line 14420** — before `tick = max(1.5, fm.height() * 0.055)`

> The seam itself, and the whole of "make the splits
> obvious": a document that cuts for-e-ver and one
> that cuts fore-ver draw the same words in the lyrics
> view, and here they do not.
>
> Drawn as a rule standing between the letters rather
> than as a middle dot. A dot is a character the size
> of a full stop sitting in a line of full stops and
> commas, on black, and it disappeared into them --
> the one thing on this screen that has to be legible
> at a glance was the least legible thing on it. A
> tick is not a character, is nothing else on the
> line, and reads as a cut.

**line 14443** — before `ny = y + len(item["placed"]) * item["lineh"]`

> -- and what was found in it

**line 14463** — before `frac = self.review_scroll / max(1.0, total - view_h)`

> Where in the document this is, as the one thing a long review
> cannot say for itself.


## `LyricsView._paint_review_head`

**line 14494** — before `p.setFont(fa)`

> The counts, in the three colours the marks below use. Of the TAB
> being read, not of the document: the number beside a tab's name is
> how much is under it, and a second set of totals next to those would
> be two different numbers for the same word.
> Each of the three is a filter as well as a count: a document is gone
> through by weight as much as by subject -- the things that are wrong
> first, the things worth a look when there is time -- and reading one
> of them at a time is the difference between a list and a job of
> work. Clicking the one already picked puts all three back.


## `LyricsView`

**line 14606** — before `REVIEW_NEAR = 2`

> How far from the line being sung a mark is still drawn IN THE WORDS.
> The margin bar goes on every line on screen, because its whole job is to
> say what is coming; the underlines are for the line you are reading, and
> a column of them all the way down is the thing this is trying not to be.


## `LyricsView.review_spans`

**line 14653** — before `self.build_review()`

> Asked every time, not only the first. `build_review` returns on
> three comparisons unless the document, the split rule or the
> language changed, and it is the only thing that notices a document
> swapped under the marks -- a song changing, a file dropped, the
> editor pushing another keystroke down the live link. Reading it
> once and keeping it meant the map went on describing a document
> that was no longer on screen, and because the map is keyed by TIME
> the marks did not land somewhere wrong: they stopped landing at
> all, which is the shape the bug had.

**line 14675** — before `for c in row.chips:`

> EVERY timed piece goes in, not only the faulty ones. What is
> being built is a map from a moment to the piece of the document
> sounding at it, and a map with holes in it answers a fragment
> with whichever earlier piece it is nearest -- which underlined
> the syllable AFTER a bad seam as well as the seam itself, the
> two of them touching exactly at the millisecond in question.

**line 14688** — before `said = _worst_told(rep, row, self.review_tab, self.review_level)`

> Two rows can share one key -- a line with two ad-lib groups
> that start together -- so the heaviest of them wins the bar.


## `LyricsView._mark_level`

**line 14720** — before `found = True`

> The worst of them where several begin together, the way the
> bar in the margin takes the worst thing said about a line:
> "your" timed y·o·ur with a zero-length o puts three pieces
> on two instants, and the one a reader needs to see is the
> heaviest -- a letter with no vowel in it, not the note
> about the piece it happens to share a millisecond with.


## `LyricsView._paint_review_marks`

**line 14806** — before `if dist > self.REVIEW_NEAR and self.browse < 0.2:`

> Near the voice, or anywhere at all while somebody is scrolling.
> A hand on the wheel is somebody READING the column rather than
> listening to it, and the line they have scrolled to is a long
> way from the one being sung by definition -- so the rule that
> keeps the underlines off the far half of the screen was the rule
> that took them off every line a reader went looking at. The
> column does the same thing with the distance fade, and for the
> same reason: see `browse` in tick.

**line 14836** — before `fade = max((215, 130, 80)[min(dist, 2)]`

> Fading with distance the way the words themselves do.
> A rule at full strength under a line the column has
> already blurred reads as the sharpest thing on screen,
> which is the wrong order of importance by two lines --
> and while the column is being scrolled the distance
> stops meaning that, so the marks come up with the words.


## `LyricsView`

**line 14856** — before `REVIEW_LOUD = 60`

> Past this many findings a document is not being reviewed so much as
> papered over, and the toast says how to read it instead. It is what a
> catalogue's copy looks like -- they write a zero-width space between
> every pair of words, which is one finding per word for the whole song.


## `LyricsView._paint_review_fold`

**line 14919** — before `for other in [item["row"]] + list(also):`

> The line being shown is the first of them and belongs in the list:
> a dropdown that says "3 times" and offers two places to go is a list
> with a hole in it where the line you are looking at should be.


## `LyricsView.review_press`

**line 15138** — before `self.clock.seek(max(0.0, other.start) + self.track_offset())`

> One of the repeats, picked out of an opened fold: the song
> is played from THAT one rather than from the first.


## `LyricsView.on_gsearch`

**line 15319** — on `            return`

> answered a query the user has already typed past


## `LyricsView.genius_rows`

**line 15334** — before `if not self.gq_query or not typed.startswith(self.gq_query):`

> Kept up while the query is still being extended, so refining a line
> does not blink the Genius rows out and back on every letter; a
> backspace or a different query drops them, since those are no longer
> answers to what the box says.


## `LyricsView.merge_hits`

**line 15363** — before `line = g.get("line") or ""`

> Where Genius matched a LINE, the row reads like every other one:
> the line above, the song under it. Where it matched the name,
> the name is already the line above -- so the row under it is the
> artist alone, rather than the same words a second time.


## `LyricsView.activate_hit`

**line 15382** — before `self.gq_matching = hit["genius"]`

> Genius named a song; Spotify has to be asked which recording
> that is, and only for the one actually picked -- matching all
> eight would be eight catalogue searches per keystroke's worth
> of results, for seven nobody asked about.


## `LyricsView`

**line 15494** — before `def info_rows(self) -> list[tuple[str, str]]:`

> -- song info + share ----------------------------------------------


## `LyricsView.info_rows`

**line 15499** — before `rows = [(name, value) for name, value in`

> A row that says nothing is a row in the way. Everything here is
> added only where there is something to add, and the sweep at the
> end catches whatever still came out empty -- see the return.

**line 15507** — before `("Lyrics", {"syllable": "word-synced", "line": "line-synced",`

> LS.quality, not the Type the document claims. NetEase, QQ
> Music and Kugou all stamp "Syllable" on whatever they hand
> over, and the line under the lyrics has always read the
> data instead -- so the two panels disagreed, and this was
> the one that could be talked into "word-synced" by a
> document with no word timing in it.

**line 15547** — before `if hold:`

> Said as a total, because the two corrections are independent and
> the question anybody asks of this panel is where the words are, not
> which of the two put them there. The hold is a correction to the
> PLAYER'S CLOCK and is cleared by anything that re-establishes where
> playback is; the offset is a correction to the DOCUMENT and stays.
> Both are subtracted from what is drawn, so the sum is the answer.
> Only when one is being carried. Nothing is held on the debug port
> -- a step in the engine's position is the sound having moved, so
> there is nothing to take back (see Clock._apply) -- and a row that
> has said "none" on every song for months is a row nobody reads.

**line 15568** — before `spread = float(self.est.get("spread", EST_RANGE * 2.0))`

> A reading old enough to predate the agreement check has not
> passed it, and says so rather than raising on a missing key.

**line 15588** — before `if self.device:`

> There was a "Calibration" row under this one, and a reason on the
> row above saying how many more songs had to be tuned by ear before
> the measurement would be applied at all. Both are gone with the
> calibration; what the row shows now is what the words are actually
> moved by, which is what it looked like it was saying all along.
> Which output the global offset above belongs to. Worth saying: the
> number changes on its own when the sound moves to another device,
> and a number that changes on its own is worth being able to see the
> reason for.
> ...and WHO it belongs to, which is the other half of the key. The
> number is per output and per player both -- see offset_key -- so a
> row naming only the output would be answering half the question a
> number that changes on its own raises.

**line 15606** — before `if self.any_player:`

> Only with the setting on: without it there is one answer, it has
> been Spotify since the first version, and a row saying so every time
> is a row nobody is reading.

**line 15613** — before `return [(k, v) for k, v in rows`

> Whatever came out empty anyway. Said once here rather than guarded
> at a dozen call sites, and it is the same question at each of them:
> is there anything to read.


## `LyricsView._paint_info`

**line 15621** — before `self.info_rects = []`

> Where each row is, so a click can take its value. Rebuilt every
> frame because the panel's contents are: a row appears the moment
> there is something to put in it.


## `LyricsView.share_card`

**line 15739** — before `wrote = pm.save(str(path))`

> QPixmap.save answers False rather than raising, so a card that
> never reached the disk was announced as copied.


## `LyricsView`

**line 15750** — before `def open_editor(self, mode: str = "romaji", idx: int | None = None) -> None:`

> -- romaji correction ------------------------------------------------


## `LyricsView.open_editor`

**line 15789** — before `self.said_clipped(self.edit_field)`

> Only ever fires on a value that was already too long to be one --
> and says so rather than quietly handing back a shortened copy of
> it, which is what saving the field would then write down.


## `LyricsView._paint_field`

**line 15873** — before `shift = max(0.0, before - (wide - 12))`

> Scrolled only as far as it takes to keep the caret off the right
> edge; a field whose text fits is not scrolled at all.


## `LyricsView`

**line 15968** — before `def menu_section(self) -> int:`

> -- settings menu ---------------------------------------------------


## `LyricsView.src_move`

**line 16038** — before `self.toast("the blends follow the sources' order — reorder those")`

> Silently doing nothing here reads as a broken key. The blends
> are ordered by where their donors sit in Sources, on purpose --
> say which list to go and move.

**line 16053** — before `self.toast(" → ".join(SRC_LABEL[n] for n in self.src_order`

> The SOURCES that were just reordered, not the providers they expand
> to. source_order() returns the expansion -- "bini", "triblend" -- and
> SRC_LABEL is keyed by source, so reading it through this raised
> KeyError on every reorder.


## `LyricsView.menu_set`

**line 16129** — before `setattr(self, BLEND_KEY[blend], value)`

> Nothing to fire. source_order() reads the attribute on its next
> call, and the chain's stored answer is keyed by the list of
> providers it asked, so a changed list re-walks on its own.

**line 16140** — before `self.layout_cache.clear()`

> The pinned renderers set type at their own sizes, and none of
> them wants the column where the last one left it.

**line 16156** — before `self.follow_players(say=key == "any_player")`

> The ceiling is read at the top of every reading, so a rebuild is
> not what carries it -- but it is where the transport learns it,
> and it is one line rather than two ways of saying the same
> thing. Only the switch itself is worth a toast.

**line 16168** — before `self.rebuild_lines()`

> Both of these re-cut the lines that get drawn out of the same
> document, which is what rebuild_lines is for.


## `LyricsView.menu_value`

**line 16210** — before `return ("nobody" if not v else v[0] if len(v) == 1`

> A count past one name. The value column is the width of
> "album tint" and the text is drawn centred and clipped, so
> three usernames end mid-letter and say less than a number
> does -- the list itself is a keystroke away, in the field
> this row opens.

**line 16221** — before `off = [u for u in BLENDS[blend] if not self.src_on(u)]`

> Switched on and still never asked. Every source it draws on
> has to be on too -- and Apple Music above all, since with
> that off the whole blend run is skipped -- which is not
> visible from this section otherwise.


## `LyricsView._paint_menu`

**line 16295** — before `note = SECTION_NOTE.get(MENU_SECTIONS[tab][0], "")`

> A section whose rows cannot say what they are on their own gets a
> line under the tabs. It is drawn in the slack a short section leaves
> under its last row -- the box is sized to the TALLEST section -- so
> a section already at full height silently gets none rather than
> overflowing the panel.


## `LyricsView`

**line 16368** — before `def flip_view(self) -> None:`

> -- helpers ---------------------------------------------------------


## `LyricsView.save_lyrics`

**line 16472** — before `self.toast(f"saved {path.name}" if asked else f"saved {path}")`

> The whole path where it is not the one they asked for. "saved
> song.ttml" is all anybody needs when they said where it goes;
> when this program picked, it owes them the place.


## `LyricsView`

**line 16485** — before `def on_thumb(self, url: str, img) -> None:`

> -- input -----------------------------------------------------------


## `LyricsView.on_motion`

**line 16506** — before `fits = max(1, MOTION_BUDGET // max(1, cap * cap * 4))`

> How many of these the budget can hold at that size, and hence how
> many to skip. Thinning rather than shrinking -- see MOTION_BUDGET.


## `LyricsView._take_motion`

**line 14314** — before `def _take_motion(self) -> None:`

> The scale and the convert have to happen on the thread that draws, because
> QPixmap can only be built there, and they used to happen all at once. At a
> 720px cap the budget fits 97 frames and converting them measured 67ms in a
> single turn of the event loop -- four frames' worth, on a track change,
> which is the one moment there is nothing spare.
>
> Filled a slice of a frame at a time instead, re-arming itself with a zero
> timer until the queue is empty. Measured the same way afterwards: five
> slices, worst 4.2ms, and the same 90 pixmaps at the end of it.
>
> motion_frame already reads `i % len(self.motion_frames)`, so a list that is
> still filling simply loops shorter -- the animation starts on the first
> slice rather than waiting for the last, and the short loop is over within
> about as long as it took to notice.
>
> The key is captured when the fill starts and checked on every slice, so an
> album changing under it abandons whatever is still queued rather than
> spending the window's time on frames nobody will see. poll() clears
> motion_key the moment the album moves, which is what that test reads.


## `LyricsView.browse_key`

**line 16571** — before `used, changed = self.field_key(self.bq_field, ev)`

> The box gets the rest before the transport does, so Left and
> Right walk the caret through what was typed rather than seeking
> the song. Up and Down are taken above, where they still pick a
> result; the transport keys are still there on the other tabs.


## `LyricsView.browse_activate`

**line 16663** — before `self.gq_matching = payload["genius"]`

> Genius named a song, not a recording; ask Spotify which one it
> is, and only for the row actually picked. See on_gmatch.


## `LyricsView.refresh_browse_hits`

**line 16696** — before `self.wind_genius(self.bq)`

> Genius once the typing stops, same as the overlay; see ask_genius.


## `LyricsView.merge_browse_hits`

**line 16712** — before `for g in self.genius_rows(self.bq.strip(), known):`

> The catalogue's own order is Spotify's ranking and is left alone;
> what is sorted here is the tail this window adds to it.

**line 16720** — before `"art": art_url(g.get("art") or ""), "ms": 0,`

> Through art_url like every other cover, which is
> also what keeps anything but http out of the
> fetcher's hands.


## `LyricsView.wheelEvent`

**line 16851** — before `if (self.view == "lyrics" and self.lines`

> A renderer that pins its lines gets first refusal: view.scroll means
> nothing to it, so without this the wheel did nothing at all. The one
> that takes it (the amll column) moves its own offset instead. See
> Renderer.wheel.


## `LyricsView`

**line 16863** — before `VOL_NOTCH = 0.05`

> How far one notch of the wheel moves the volume. Twenty notches from
> silent to full, which is a flick of the finger for a big change and
> still fine enough to settle on a level. The editor's own volume takes
> the same five points over its slider -- see its VOL_NOTCH, which is
> this number written down a second time rather than imported, because
> the editor does not pull the player in at import and should not start
> to for one float.

**line 16871** — before `VOL_GAP = 0.065`

> The least time between two volumes actually being SENT. Every send is a
> round trip -- a D-Bus Set, or an evaluate down the debug port -- and it
> blocks the thread this window draws on, so the wheel cannot be allowed
> one per event: notches arrive far faster than the player answers, and
> what that bought was the sound climbing for as long as the backlog took
> after the hand had stopped. A sixteenth of a second is about fifteen
> sends a second, which is smooth to the ear and bounded to one per
> frame, and nothing is lost by dropping the rest -- a volume that
> another volume follows is never heard.


## `LyricsView.vol_wheel`

**line 16916** — before `at = self.vol_want if self.vol_want is not None else self.clock.volume`

> Counted from what has been ASKED for rather than from what the
> player has been told, or every notch turned inside `VOL_GAP` would
> be measured from the same stale level and a fast turn would move
> the volume by one notch however far it went.


## `LyricsView.mouseMoveEvent`

**line 16933** — before `self.field_drag.drag_to(pos)`

> Above every view's own move handling, and not hit-tested: a
> selection dragged past the end of the box should go on growing
> rather than stop at the edge the pointer left.


## `LyricsView.keyPressEvent`

**line 17262** — before `if k == Qt.Key.Key_F11:`

> Before the views get a look in. F11 means the same thing on every
> screen, and it is the one key that can never be part of what is
> being typed, so it is safe to take even mid-word in a search box --
> which is the whole point, since browse, review and the editor each
> used to swallow it. The bare F stays below, where it is only a
> shortcut when nothing is listening for letters.

**line 17291** — before `self.paste_into_edit()`

> Ahead of the field's own paste, which knows nothing about a
> prefilled token being replaced rather than added to.

**line 17308** — before `if self.field_key(self.q_field, ev)[1]:`

> Everything else is the box's: the caret keys, the clipboard
> keys, and the typing. Only a key that CHANGED the text is
> worth another search.

**line 17343** — before `self.help_tab_step(`

> Only while the panel is up, and only these four: everything else
> still reaches the player, so the song can be driven with the keys
> in front of you, which is most of what having them up is for.

**line 17355** — on `        elif k == Qt.Key.Key_F:`

> F11 is taken at the top, for every view

**line 17409** — before `if not self.viz:`

> Cycling to a mode while it is switched off would report a change
> nothing on the window shows, so asking for a mode turns it on.

**line 17415** — before `if self.viz:`

> Remembered rather than taken from the flag, because the flag
> defaults to 0 -- reading it back would silently reset a strength
> set in the menu to 1.0 every time this was switched off and on.

**line 17425** — before `self.toast("visualizer: on, no analysis for this track")`

> Say so rather than leave them staring at an unchanged
> background wondering whether the key did anything.

**line 17486** — before `whose = (self.dropped_from or "the editor"`

> Who was drawing, before reset_track forgets. A live document
> is not something R takes away: the editor pushing it is
> still open and still ticked, and it puts it back within the
> second -- so say what this actually did, which is to go and
> fetch the song's own copy underneath it.


## `LyricsView.set_on_top`

**line 17515** — before `self.on_top = on`

> on_top is set below, and enter_fullscreen reads it to carry the
> hint over the window it re-creates; tell it now.


## `LyricsView.resizeEvent`

**line 17527** — before `self.layout_cache.clear()`

> Not drop_pixmaps: the width a line was drawn at is in its key, so
> the old ones are simply not asked for again, and a drag across the
> desktop delivers a resize a frame -- each of which would otherwise
> have thrown away the column and rebuilt it before the next one
> arrived.


## `LyricsView.closeEvent`

**line 17634** — before `self.unfollow_editor(pause=False)`

> Before anything else: a muted player is this window's doing and
> must not outlive it.

**line 17639** — before `self.pump.stop()`

> Before the signals are pulled: the sampler emits on every reading,
> and one landing in a half-dismantled window is a slot running
> against objects that have gone.


## `main`

**line 18231** — before `if not hasattr(args, attr):`

> Not every setting is a flag. `align_ckpt` names a checkpoint to obey
> for good, which is a decision that outlives one launch -- it is read
> from the settings file at the point of use and has no business on
> argv, so there is no attribute here to fill in. Filling in only what
> the parser actually declared lets a settings-only key exist without
> taking the whole window down on the way up.


## `main._fixture`

**line 18258** — before `w.pump.stop()`

> After the first poll, not before it: poll() reconciles the
> window with whatever the player last said, and a document put on
> screen ahead of that is the first thing it clears away.

**line 18266** — before `w.clock.meta = {"title": pathlib.Path(args.fixture).stem,`

> poll() calls reset_track on a track it has not seen before, and
> the document below would be the first thing that cleared.


---

## Earlier lift — 2026-08-23

Comments lifted out of `mild-lyrics/lyrics_gui.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 81** — before `sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]`

> spotify_dom.py may sit next to this file or one level up -- offer both, or the
> import below fails depending on where the scripts were dropped.

**line 92** — before `raise SystemExit(`

> A bare ImportError traceback is a poor way to learn that one file of five
> was left behind -- and it is the easy one to leave behind, being the only
> one that may live a directory up rather than beside the rest.

**line 126** — before `TEXT = QColor(234, 234, 234)`

> Matches the Spicy Lyrics view: rgb(234,234,234) at weight 700.

**line 128** — before `FONT_STACK = ["Outfit", "Inter", "Poppins", "Noto Sans", "Cantarell",`

> In preference order, falling through to whatever the platform actually has:
> the first three are the look this was designed around, the rest are the
> stock UI faces on Linux, Windows and macOS respectively.

**line 134** — before `try:`

> The OpenType weight axis, when this Qt can address it (6.7+). None elsewhere,
> where setWeight is all there is.

**line 144** — before `STALE_HOLD = 2.0`

> how long to keep interpolating from an older anchor when Position stops moving

**line 146** — before `SETTLE = 7.0`

> How long a track is given to produce lyrics before it is taken as having none.
> Longer than the fetcher's own retry gap, so the retries finish first.

**line 149** — before `RESYNC_NUDGE = 0.25`

> How far back a resync seeks. Enough that the player cannot mistake it for a
> request to stay put, little enough that the repeated audio passes unnoticed.

**line 152** — before `POLL_MS, POLL_MS_EDGE = 250, 60`

> Position is polled this often normally, and this often near a track boundary,
> where the id has to be noticed fast or the first lines land against the old clock

**line 155** — before `POLL_MS_PAUSED = 110`

> Paused, there is no position to track -- but a resume has to be NOTICED, and
> at 250ms the lyrics sat frozen for a quarter second and then corrected in one
> jump. Nothing else is happening while paused, so this is cheap.

**line 159** — before `SLEW_MAX, SLEW_TIME = 0.6, 0.35`

> Pausing costs about 0.2s of sync. Spotify's reported position stops short of
> where the sound actually stopped -- the audio already handed to the sink keeps
> playing for a fraction of a second after the command -- and on resume the
> reported position carries that shortfall forward while the audio does not. The
> clock then runs a fifth of a second behind the sound for the rest of the song,
> and pausing again does not make it worse: the error is taken once, at the first
> unpause, and kept.
>
> Measured against the sink's own output, by cross-correlating what came out of
> it with a clean pass over the same stretch of the song: the clock is dead on
> (1ms) until the first pause, -0.20s after it, and -0.26s after a seek made
> while playing. A seek made WHILE PAUSED and then resumed comes back at -0.001s,
> which is what Clock._pin does -- it asks the player to go to the position it
> just said it was at, which is a no-op to anyone listening, and puts its clock
> and its audio back on the same instant.
>
> Corrections smaller than SLEW_MAX are eased in rather than jumped; anything
> larger is a real seek and should land immediately.

**line 178** — before `PIN_EDGE = 1.0`

> How close to either end of the track is too close to pin. Seeking next to the
> end can tip a player into rolling over to the next track, and neither end is
> worth the risk for a correction that only matters mid-song.

**line 184** — before `UNPAUSE_DELAY = 0.25`

> Spotify's audio comes out of the speaker a little after its clock says it
> does, so the lyrics run ahead. It is real and it is measurable -- against the
> sink's own monitor this machine reads a couple of hundred milliseconds --
> but measuring it live turned out to cost far more than it was worth: the
> figure had to be ramped in as the buffer refilled, which made the clock crawl
> for a third of a second after every jump, and it had to be kept out of every
> seek target, which it was not always.
>
> So this is a plain number instead. Unpausing holds the words back by it and
> nothing else in the program knows about it. It cannot be exactly right --
> the player is not sending anything that says what it should be -- but a
> fixed delay that looks right beats a measured one that keeps introducing
> problems elsewhere, and it is a setting, so it can be tuned by ear.

**line 201** — before `OLD_SLUG = "spicy-lyrics"`

> What the directories used to be called. Renaming the app should not lose
> anybody's settings, so the old one is moved across the first time it is seen.

**line 205** — before `POLL_IDLE = 0.4`

> How often the worker asks Spotify what is playing, and how long it waits
> before asking Spicy Lyrics again for a song whose cache entry was not there
> yet. The retry doubles from FIRST up to MAX, because the usual reason to be
> waiting is a fetch already in flight rather than a song with no lyrics -- a
> flat two seconds spent that wait on almost every track change.

**line 250** — before `SRC_LABEL = {"spicy": "Spicy Lyrics", "amll": "amll-ttml-db",`

> The lyric providers, and the attribute holding each one's on/off switch.
> Priority is a setting now rather than the order they happen to be written in,
> so this map says nothing about which is consulted first -- src_order does.

**line 260** — before `SRC_DEFAULT = ["spicy", "amll", "blend", "youly", "netease", "lrclib", "local"]`

> "local" sits last on purpose. fallback() will not let one word-synced answer
> replace another unless the user has ranked it above Spicy Lyrics, so from
> down here an alignment made on this machine is used exactly where it is worth
> using: songs nobody else has word timing for. Drag it up in the menu to have
> your own measurements outrank theirs.

**line 273** — before `"fps_cap": 60.0,`

> Ceiling on the animation rate. The frame timer follows the refresh rate of
> whatever screen the window is on, divided down to the first integer step
> at or under this: 60Hz runs every refresh, 240Hz every fourth. Both then
> cost the same, and an integer divisor keeps the cadence even where a
> free-running timer beats against vsync. Raise it to spend the fast panel.

**line 282** — before `"src_blend": False, "ne_graft": True,`

> Off by default: it costs three lookups where every other provider costs
> one, and it only pays for itself on tracks the cheap ones read badly.

**line 285** — before `"align_on": True,`

> Whether this machine aligns at all. Off closes both ways in -- Shift+A
> and the queued-ahead jobs -- and leaves every song on whatever timing the
> providers gave it, which is what a laptop without a card worth spending
> three minutes of wants.

**line 290** — before `"align_model": "sync", "align_stems": False,`

> What align_song.py is allowed to do to this machine. Separation on,
> because it is what makes the timings worth having; the device on auto,
> because a card with a game on it is not ours to fill.
> THE SYNC MODEL, and no separation with it. The model this project
> trained is what runs by default now: measured against gc's own
> hand-timed songs it places the median word inside 62 ms, where the
> older chain measured in tenths of a second. Separation is off because
> it is slow, inconsistent, and this default has to be one that works on
> a machine also being used for something else -- ask for it per song if
> a song needs it.

**line 302** — before `"align_free": True,`

> Drop the three models when an alignment finishes rather than keeping them
> loaded for the next song. Keeping them saves about half a minute of
> loading and costs several gigabytes for as long as the window is open --
> measured at 9.7 GB resident and 4.1 GB of VRAM on a player that had
> aligned one song, which is most of a card that the next song's stages
> then decide they have no room on. The reload is once per song and the
> alignment it precedes takes longer than it does.

**line 310** — before `"align_ahead": 1,`

> How many tracks ahead in the queue to align before they are reached.
> One by default: the work is speculative and a skipped song wastes a
> download and a few GPU-minutes, so this errs towards doing less of it.

**line 322** — before `VIEW_MODES = ["regular", "compact"]`

> What the now-playing chrome looks like. "regular" is the big side panel;
> "compact" is the top strip, which used to be simply what you got with the art
> panel switched off -- the two were one setting doing two jobs. Split apart,
> the panel toggle keeps meaning "show me the cover" in either layout.

**line 330** — before `DUET_MODES = ["off", "album tint"]`

> The second voice in a duet. "off" is what it has always done -- the same fill
> as everyone else, told apart only by sitting on the other side of the screen.

**line 333** — before `ALIGN_DEVICES = ["auto", "gpu", "cpu"]`

> Where the local aligner is allowed to run. "auto" means the GPU when the card
> has room beside whatever else is using it, and the CPU when it does not --
> which is the answer nearly always, since the alternative is a stall or an
> out-of-memory error in something the user cares about more than this.

**line 338** — before `def _sync_available() -> bool:`

> "sync" is this project's own model, reading the waveform and placing every
> word itself. "whisper" is the older chain -- transcribe, then match the
> transcript to the words -- kept because it needs no checkpoint on disk and
> because it is the fallback when there is none.

**line 358** — before `SYNC_HOME = app_dir("cache") / "sync"`

> Where the trained model lives, and which of them to prefer: the newest with
> a boundary head, the same rule sync.sync uses to pick a default.


### `_sync_ckpt`

**line 386** — on `            continue`

> a mid-run copy, not a finished model

**line 387** — before `made_on_stems = any(k in path.name for k in ("-stem", "-pitch"))`

> syncnet-w2v.pt is the mixture one; -stem and -pitch were both trained
> on separated vocals.


### module level

**line 403** — before `MENU_SECTIONS = [`

> label, attribute, kind, spec -- spec is the choice list, or (lo, hi, step, fmt)
> Grouped so the menu can show one page at a time -- twenty rows in a single
> column meant hunting for the one you wanted every time.

**line 442** — before `("Auto timing",       "auto_time",    "bool",   None),`

> Measures each song against Spotify's analysis of it and corrects what
> it finds. Never overrules a track tuned by hand, and stays out of the
> way until enough of those exist to calibrate it -- see auto_offset().

**line 446** — before `("Unpause delay",     "unpause_delay", "num",   (0.0, 1.0, 0.05, "{:.2f}s")),`

> How long the words hold still after an unpause, covering the moment
> the player's output takes to spin back up. Set by ear -- nothing
> reports what it should be.

**line 451** — before `("Local aligning",    "align_on",     "bool",   None),`

> Forced alignment against the song itself, on this machine's own card.
> Read by align_song.py rather than by anything in here -- see
> local_align.py for what the three of them cost. "Local aligning" off
> is the switch for machines that should not be spending that at all,
> and the rows below it do nothing while it is. "Isolate vocals" is
> the expensive one and the one that decides how good the answer is;
> "Align device" on auto uses the GPU only when there is honestly room
> for it, and "Keep VRAM free" is how much is left for everything else.

**line 465** — before `("Align ahead",       "align_ahead",  "num",    (0, 7, 1, "{:.0f} tracks")),`

> Speculative work on songs coming up in the queue. 0 turns it off and
> leaves Shift+A as the only way in. It skips anything already
> word-synced, already aligned, or that would land on the CPU.

**line 469** — before `("NetEase word sync", "ne_graft",     "bool",   None),`

> Only ever applies where the source above NetEase in the running order
> has the words but no word timing; off leaves that song line-synced.

**line 473** — before `("Sources", [`

> In priority order, Spicy Lyrics included: whoever sits highest and has
> something word-synced decides the song, and a source lower down only gets
> a say when the ones above it have nothing as good. Filled from src_order
> at paint time, so the rows sit in the order they are actually consulted.
> The entries here are placeholders that only fix how many rows there are.

**line 515** — before `MENU = [row for _, rows in MENU_SECTIONS for row in rows]`

> flat view, so a row is still addressed by one index everywhere else

**line 517** — before `MENU_SPANS = []`

> section index -> (first flat row, count)


### `palette_of`

**line 588** — before `if any(min(abs(h - o.hue()), 360 - abs(h - o.hue())) < 18 for o in out):`

> Neighbouring buckets of one gradient are near-identical, and four
> shades of the same brown make the mesh look like a single flat wash.

**line 592** — before `out.append(QColor.fromHsv(h, min(255, int(s * 1.35)), max(70, min(205, v))))`

> Keep real brightness spread: clamping everything into a narrow band
> (what the single accent colour needed) is what flattened the palette.

**line 595** — on `    if not out:`

> monochrome cover: fall back to its average


### module level

**line 685** — before `HAND_FIX_MAX = 3`

> Below this many corrected lines on one track, the entries were typed by hand;
> above it, they are a whole Genius alignment. Only matters once, for files
> written before the two were stored apart.


### `save_settings`

**line 800** — before `values = dict(values, offsets={k: v for k, v in offsets.items() if v})`

> keep only the tracks that actually needed correcting

**line 812** — before `if CONFIG.exists():`

> Keep one generation back. This file now holds hand-made work -- per
> track timing offsets and typed-out romaji corrections -- and it is
> rewritten whenever anything changes, so a single bad write or an
> outside deletion should not be the end of it.


### `kwin_keep_above`

**line 856** — before `_kwin_seq += 1`

> A name that is already loaded is refused, and this runs on every
> toggle, so make each one unique.

**line 859** — before `iface.loadScript(str(path), f"spicy-keepabove-{os.getpid()}-{_kwin_seq}",`

> loadScript is overloaded (s and ss); without an explicit signature
> python-dbus picks the one-argument form and the call fails outright


### `wrap_rows`

**line 894** — on `                cur = joined`

> no rows left; elided below


### module level

**line 908** — before `# --------------------------------------------------------------------------`

> talking to the player
>
> Two ways in, because the platforms do not agree on there being one. MPRIS is
> how a Linux desktop asks any player what it is doing; Windows has no such bus,
> but Spotify's own debug port is already open -- it is how the rest of this app
> reads the queue, the search and the artist list. Either one answers the same
> four questions, so Clock takes whichever is there and does not care which.


### `MprisTransport.read`

**line 967** — before `again = props.Get(MPRIS, "Metadata")`

> Metadata and Position are separate round-trips, so a track change
> can land between them and pair the new track's id with the old
> track's position. Re-read: if the id moved, so did everything else.


### module level

**line 1000** — before `JS_STATE = """(() => {`

> One eval per poll, so unlike MPRIS there is no window for a track change to
> land between two reads -- everything below is sampled from one page state.


### `SmtcTransport._mod`

**line 1110** — before `try:`

> winsdk and its successor winrt expose the same namespace


### `SmtcTransport.read`

**line 1153** — before `playing = int(getattr(pb.playback_status, "value", pb.playback_status)) == 4`

> 4 is PLAYING in the SMTC enum; anything else is not advancing

**line 1156** — on `                          else float(d) / 1e7)`

> timedelta or 100ns ticks

**line 1163** — on `            "volume": None,`

> not part of the protocol

**line 1167** — on `                "art": "",`

> a stream, not a url -- see docstring


### `SmtcTransport.seek`

**line 1176** — on `        if s is not None:`

> position is in 100-nanosecond ticks


### `make_transport`

**line 1258** — on `        return MprisTransport()`

> asked for explicitly; fail loudly


### module level

**line 1270** — before `# --------------------------------------------------------------------------`

> player clock -- poll rarely, interpolate in between so the fill is smooth


### `Clock.__init__`

**line 1277** — before `self._pos = 0.0`

> Where the SOUND is, once the lag has been taken off the player's
> reading. Interpolated at 1x, because that is the only rate audio ever
> plays at.

**line 1281** — before `self._raw = 0.0`

> The player's last raw reading, kept beside it for the two questions
> that are about the player rather than the sound.

**line 1287** — on `        self._slew = 0.0`

> correction still being eased out

**line 1289** — before `self._pinned: str | None = None`

> Track whose pause point has already been pinned, so it happens once per
> pause and not on every poll for as long as the song sits there.

**line 1292** — before `self.volume: float | None = None`

> None until the player has been asked once, so the slider can tell
> "muted" apart from "we have not heard yet" and stay hidden until then

**line 1296** — before `self.unpause_delay = UNPAUSE_DELAY`

> How long the words are held back after an unpause, and how much of
> that hold is currently in force. The second is cleared by anything
> that moves the song deliberately -- a seek knows exactly where it is
> going and must land there.


### `Clock.poll`

**line 1309** — before `held = self._raw`

> The player's own last reading, not our corrected anchor: this is
> compared against the next raw reading to spot a frozen property
> and to settle the pause point, and both are questions about what
> the player said rather than about where the sound is.

**line 1314** — before `want_vol = time.monotonic() - self._vol_set_at > 1.0`

> Spotify takes a moment to report a volume we just set, and reading
> the old value back mid-drag makes the handle jump backwards under
> the cursor. Ours stands until the player has had time to agree.

**line 1325** — before `resumed = status == "Playing" and not was_playing`

> Spotify stops refreshing Position for the last second of a track.
> Re-anchoring on a value that has not moved drags the anchor forward
> under a frozen reading, which stalls the lyrics right at the end of
> every song. A repeated value means the property is stale, not that
> playback stopped -- keep the older anchor and let it interpolate.
> ...except on the poll that first sees playback resume. There the
> position matching is not a stale reading, it is the true one: the
> song resumes exactly where it was paused, so `pos == self._pos`
> holds by definition and the guard fired every single time.
>
> Holding the old anchor then means counting forward from the last
> poll taken while paused -- a moment before the user pressed play,
> and before Spotify's own audio had spun up. The lyrics came back
> already ahead of the sound and stayed there until the player got
> round to publishing a fresh Position, which the guard allows it up
> to STALE_HOLD to do. Re-anchoring here starts the clock at the
> first instant we know playback is running, and the slew above
> eases out whatever the player says a poll or two later.

**line 1345** — before `self._delay = max(0.0, self.unpause_delay)`

> The whole of the unpause correction, in one place: start the
> clock `unpause_delay` in the past, so the words sit still for
> that long and then run, which is what the sound is doing while
> the player's output spins back up. Nothing else in the program
> is aware of it -- no ramp, no rebasing, no adjusted seeks.

**line 1356** — before `held_back = pos - self._delay`

> The delay lives in the anchor, so position() stays a plain
> interpolation and the words always advance at 1x. Holding it
> here rather than re-deriving it per frame is what keeps the
> clock from crawling: a correction that grows between polls
> outruns an anchor carried forward at 1x, and the words stall.

**line 1362** — before `if tid == self._pos_tid and status == "Playing" and self._at:`

> Ease small corrections instead of stepping to them. The step
> is most obvious on unpause, but the same jitter shows up on
> any poll, and a word-level fill makes 0.2s visible.

**line 1366** — before `shown = self._pos + (at - self._at) if was_playing else self._pos`

> what the screen is showing right now: interpolated if it
> was already playing, frozen if it was paused

**line 1374** — before `if status == "Playing" or tid != self._pinned:`

> Settle the pause point while it is still paused. Deliberately not
> on the poll that first sees "Paused" -- that reading can be taken
> mid-stop, and pinning to a position the player is about to revise
> would move the song. Reading the same value twice costs one poll
> and says the player has finished stopping.

**line 1386** — before `self._drop()`

> keep the last known tid: clearing it makes the next successful poll
> look like a track change and reloads the lyrics on every hiccup

**line 1390** — before `self.last_error = str(e) or e.__class__.__name__`

> kept for the status line: "Error" alone tells nobody that Spotify
> simply is not listening on the debug port, which is the usual cause
> and needs a flag on the Spotify shortcut to put right


### `Clock.position`

**line 1406** — before `length = self.meta.get("length", 0.0)`

> Nothing is subtracted here. Whatever the clock is holding back sits in
> the anchor already, so this stays a plain interpolation and the words
> always move at the rate the music does.


### `Clock.seek`

**line 1451** — on `        self._slew = 0.0`

> a deliberate jump must land, not glide


### `Clock.resync`

**line 1488** — before `self.seek(max(0.0, fresh - RESYNC_NUDGE), keep_hold=True)`

> A hair back rather than to the same value. Asking a player to seek to
> the position it is already at is a request to do nothing, and it is
> free to treat it that way -- which would explain a resync that
> sometimes changed nothing at all. A quarter second of repeated audio
> is below noticing, and it guarantees the pipeline is actually flushed.
> keep_hold: the words are held back by the same output lag before and
> after this. See seek() -- a resync is not a jump anyone asked for.

**line 1496** — before `self._pos_tid = None`

> The seek anchored us on the value we asked for. Spotify lands where it
> lands -- it snaps to what it has buffered -- so the next poll has to
> believe the player over us, without easing into it the way an ordinary
> correction would.


### module level

**line 1511** — before `# --------------------------------------------------------------------------`

> lyrics fetcher -- CDP blocks, so it lives on its own thread with its own socket


### `LyricIndex`

**line 1520** — before `V = 2`

> Bumped when a per-song field is added. An older file still LOADS -- the
> titles in it are hand-won and must not be thrown away -- but the missing
> facts are refilled from the cache in the background.


### `LyricIndex.__init__`

**line 1526** — on `        self.songs: list[dict] = []`

> {id, lines[], lang, title, artist}

**line 1527** — on `        self.stale = False`

> loaded, but from an older schema


### `LyricIndex.search`

**line 1570** — before `if q in (s.get("title", "") + " " + s.get("artist", "")).lower():`

> By name first. This only became worth doing once the browse view
> backfilled the titles -- before that almost nothing had one, and
> lyric text was the only thing here worth matching against.

**line 1582** — before `"next": s["lines"][i + 1] if i + 1 < len(s["lines"]) else "",`

> until a song has played once we have no title
> for it, and the next line identifies it far
> better than a 22-character id would

**line 1587** — on `                    break`

> one hit per song keeps the list scannable

**line 1590** — before `hits.sort(key=lambda h: (not h["here"], not h["title"]))`

> lines from what is already playing are almost always what you meant


### `Beat`

**line 1607** — before `JS = "Spicetify.getAudioData(%s).then(d => ({" \`

> Rounded in the page, not here: pitches are already 0..1 and timbre
> coefficients are meaningful to about a whole number, so full float
> precision is a couple of hundred KB of digits nobody reads. Timestamps
> are never rounded -- they are the whole point.


### `Beat.clear`

**line 1633** — before `self.pitch: list[list[float]] = []`

> 12 bins each, one row per segment: chroma and a timbre basis. Spotify's
> own spectral summary of the track, at whatever rate it cut segments.


### `Beat.load`

**line 1655** — before `for name in ("pitch", "timbre"):`

> Both are only ever read by segment index, so a batch that does not line
> up with the segments is not partially useful -- it is unusable. Older
> Spicetify builds send neither, which lands here as empty and is fine.

**line 1665** — before `self.beats = [`

> Bake each beat's strength from the loudness AT ITS ONSET. Sampling the
> envelope at playback position instead let a loud moment mid-beat drag
> the peak off the beat -- measured 330ms late, which defeats the point.


### `Beat.energy`

**line 1701** — before `span = (self.beats[i + 1][0] - start) if i + 1 < len(self.beats) else 0.5`

> decay across roughly one beat; faster songs get a tighter pulse


### module level

**line 1725** — before `# Bumped when anything below changes. Stored measurements carry the revision`

> measuring a track's timing offset
>
> What this can and cannot do, because it decides the shape of everything below.
> Nothing in this program ever hears the song: the position comes off a bus and
> the lyrics come out of a cache. The only description of the actual sound
> anywhere near it is Spotify's own analysis -- the segment list in Beat above --
> and Beat.grain() is the standing note that its edges are a couple of hundred
> milliseconds apart. A single edge therefore cannot place a tenth of a second,
> and any measurement that leans on one is noise wearing a number.
>
> What survives that is the average. Segment edges scatter around the true
> instant a phrase begins, but they scatter either side of it, so the mean of
> forty of them is worth about forty times less scatter than any one -- tens of
> milliseconds, which is the range that matters here. Everything below exists to
> make that average trustworthy: pick anchors where an edge should genuinely
> exist, weight the edges by how much they look like a voice arriving rather
> than another snare, and correlate the two rather than pairing each anchor with
> its nearest edge, which would quietly pull every estimate toward zero.
>
> What it still cannot do is tell its own systematic error from the song's. A
> line start marks a word; a segment edge marks a spectral change, and the gap
> between those two definitions is real, consistent, and nothing to do with
> whether the lyrics are in sync. That part is not solved here. It is solved by
> calibrate(), which measures the gap against the tracks the user has already
> corrected by ear and subtracts it.

**line 1751** — before `EST_REVISION = 1`

> Bumped when anything below changes. Stored measurements carry the revision
> that made them and anything older is dropped and taken again, the same bargain
> the Genius alignments get: derived data should never outlive the code that
> derived it.

**line 1756** — before `ANCHOR_GAP = 0.35`

> A line only anchors the estimate if this much silence precedes it. A line
> starting mid-verse is a breath inside a phrase that is already sounding and
> has no acoustic edge under it to measure against; one that starts after a bar
> of nothing does, and that edge is the voice coming back.
>
> Set from the songs on disk rather than by taste. A second of silence is the
> cleanest possible anchor and almost nothing qualifies -- at 0.6s only six of
> the fourteen cached tracks had enough anchors to say anything at all, because
> a rapped or heavily stacked verse runs its lines together and never pauses
> that long. Dropping to 0.35s covers nine of them, and costs nothing
> measurable: admitting mid-phrase lines that have no edge under them leaves the
> median error where it was, even when NONE of them do. Anchors with nothing to
> say scatter their contribution flat across the whole curve, while the ones
> with an edge pile onto the same shift, so the peak survives being outnumbered.

**line 1771** — before `EST_RANGE = 0.75`

> Widest correction worth looking for. Past this it is not an offset, it is the
> wrong lyrics file, and shifting them further only finds a coincidence.

**line 1775** — before `EST_SIGMA = 0.08`

> How close an anchor has to sit to an edge to count as landing on it. About a
> third of the segment spacing: tight enough to resolve, wide enough that a
> single anchor's scatter does not drop it out of the sum entirely.

**line 1779** — before `MIN_ANCHORS = 8`

> Fewer anchors than this and the average has not had a chance to do the work
> described above, so no estimate is offered at all.

**line 1782** — before `EST_CONF_MIN = 0.18`

> How far the best alignment must stand above the next-best one, as a fraction
> of itself. Segment edges are quasi-periodic, so a rival peak one beat away is
> the normal failure and this is what refuses it.

**line 1786** — before `CAL_MIN = 5`

> How many tracks corrected by ear before the estimator's standing error is
> considered known and its readings are acted on. Nothing is applied below this,
> because a raw reading is the sync error and the standing error added together
> and there is no way to tell which is which from one song. Five is few enough
> to reach in an evening and enough that one badly judged correction cannot
> carry the median on its own.


### `onsets_of`

**line 1815** — before `cols: list[float] = []`

> Put the timbre coefficients on comparable footing first. They are a basis,
> not a spectrum: the first coefficient runs into the hundreds and the last
> rarely leaves single figures, so an unweighted distance between two rows is
> the first coefficient and nothing else -- which is loudness again, already
> counted separately below.

**line 1834** — before `shape = math.sqrt(sum(((rows[i][c] - rows[i - 1][c]) / cols[c]) ** 2`

> Coefficient 0 is skipped on purpose: it is the loudness the rise
> above already measures, and counting it twice turns this back into
> a loudness detector.

**line 1851** — before `out = [(t, 0.65 * shapes[i] + 0.35 * rises[i] if cols else rises[i])`

> Shape carries most of the weight where it exists; where the analysis came
> back without timbre there is only the loudness rise, which is worse but is
> not nothing.

**line 1856** — before `mid = sorted(w for _, w in out)[len(out) // 2]`

> Keep the upper half. Weak edges are dense and nearly uniform in time, and
> summing over them adds a flat pedestal to the correlation that buries the
> peak the whole thing is looking for.


### `estimate_offset`

**line 1903** — before `reach = EST_SIGMA * 3.0`

> Past this an edge contributes less than about 1% and is not worth the visit

**line 1920** — before `rival = max((v for d, v in curve if abs(d - best_d) > EST_SIGMA * 2.0),`

> The nearest rival, measured outside the winning peak's own shoulders --
> inside them every sample is the same peak and would always "win".

**line 1924** — before `return {"delta": round(best_d, 3), "conf": round((best - rival) / best, 3),`

> Sign convention, which is easy to get backwards: best_d is how far the
> lyric times had to be pushed FORWARD to sit on the sound, so the sound is
> that much later than the file claims. track_offset() is subtracted from
> the playback position before the lines are looked up, so the same number
> unmodified is what makes the lines appear that much later. Positive means
> the lyrics are running early and need holding back.


### `calibrate`

**line 1953** — before `diffs = sorted(raw[t] - hand[t] for t in raw.keys() & hand.keys())`

> A correction of exactly zero counts, and is not the same thing as a track
> nobody has judged. It says the timing was already right, which pins the
> standing error at that track's raw reading exactly -- the most informative
> reference point there is. Ordinary use never stores one, because nudging
> back to zero drops the entry, but a config edited by hand can carry one
> and it would be perverse to throw away the clearest evidence in the file.


### module level

**line 1967** — before `JS_ARTISTS = """(() => {`

> Spotify's MPRIS metadata carries only ONE artist -- a track credited to three
> people comes over the bus as the first of them and nothing else. The page has
> the full list, so ask it. metadata["artist_name:N"] is the older shape and is
> still the only one populated on some builds, hence both.

**line 1998** — before `FEAT_SPLIT = re.compile(r"\s*(?:,|&|\bx\b|\band\b)\s*", re.I)`

> "A, B & C" and "A x B" are all the same list written differently


### `split_artists`

**line 2025** — before `how_of[n] = "with" if word.lower() == "with" else "feat"`

> "with" is a collaboration, "feat." is a guest -- the title
> said which, so there is no need to guess


### `split_artists.same`

**line 2034** — before `return bool(ka) and bool(kb) and (`

> containment, not equality: "hayleywilliamsofparamore" contains
> "hayleywilliams", which is the whole reason this is not a set lookup


### `split_artists`

**line 2044** — before `hit = next((n for n in named if same(a["name"], n)), None) if i else None`

> never the first name on the credit: a title that says "feat." is
> naming a guest, not renaming whose song it is

**line 2051** — before `if not any(same(n, a["name"]) for a in artists) and key(n) not in seen:`

> in the title but not on the credit list at all -- keep the title's
> wording, since it is the only wording there is


### module level

**line 2061** — before `FONT_UA = "Mozilla/4.0"`

> Google serves woff2 to anything that looks like a browser, and Qt does not
> read woff2. An old User-Agent gets plain TrueType, which it does read.

**line 2064** — before `FONT_REV = 2`

> Bumped when what gets downloaded changes shape. v1 came from the CSS endpoint
> and was a single weight-400 file with no axis in it, so a font cached then
> ignores every weight asked of it -- including the one it was cached for.


### `split_font`

**line 2096** — before `head, _, tail = spec.rpartition(" ")`

> trailing weight word, so "Outfit Black" reads the way it is written


### `_font_file.rank`

**line 2130** — before `ital = 1 if "italic" in n else 0`

> Italic sorts alphabetically before the upright file and carries
> the same wght axis, so without this "Montserrat" arrived slanted.


### module level

**line 2212** — before `JS_ALBUM = """(async () => {`

> Spotify's own search, through the client's persisted GraphQL operation. All
> four include* flags are load-bearing: drop any one and the call fails with
> HttpResponseError rather than degrading. Flattened in the page so only a small
> list crosses CDP.
> One album, with its track list. tracksV2 wraps each row twice -- {track:...}
> around the real thing -- and older builds spell it `tracks`, so both are
> unwrapped rather than assuming whichever this Spotify happens to ship.

**line 2246** — before `JS_ARTIST = """(async () => {`

> One artist, in the same shape JS_ALBUM returns, so the page can paint either
> without asking which it is holding.

**line 2330** — before `JS_QUEUE = """(async () => {`

> PlayerAPI.getQueue() gives {current, queued, nextUp}. `queued` is what you
> put there by hand and `nextUp` is what the context will play anyway -- Spotify
> shows them as two sections and so do we.

**line 2358** — before `JS_SUGGEST = """(async () => {`

> Everything the home screen suggests, in one round trip. Each block is wrapped
> on its own: these are separate backend services and any one of them can be
> unavailable without the others being worth throwing away.

**line 2428** — before `JS_DISCOVER = """(async () => {`

> Recommendations from listening history rather than from whatever happens to
> be playing. Spotify's own "made for you" shelves live behind the `home`
> persisted query, whose variable shape is not reachable from here -- but the
> raw material is: the play history carries artist uris, so the weighting can be
> done locally and only the "who is like this" lookup has to be asked for.

**line 2523** — before `MOTION_FPS = 30`

> Apple serves the animated cover as an HLS stream, which is a playlist of
> segments rather than a file -- nothing Qt can draw. ffmpeg turns it into
> frames, which is exactly what this app's painter already knows how to blit.

**line 2528** — before `MOTION_PX = 720`

> What lands on disk. Deliberately larger than the panel usually draws: this is
> the master copy, kept once and scaled down per window, and re-fetching a
> stream to gain back detail thrown away at decode time is not worth the round
> trip. The pixmaps actually held in memory are sized to the panel, not to this.

**line 2533** — before `MOTION_MEMO = MOTION_DIR / "known.json"`

> What Apple has already been asked, so it need not be asked again. The frames
> themselves are cached under _dir(key) and cost nothing to reuse; it is the
> SEARCH that repeats -- an album with no animation was looked up again on every
> restart, and that is now up to three requests apiece with the web-search
> fallback behind it. Hits remember the stream's URL too, which skips the search
> on a record whose frames have been cleared.

**line 2540** — before `MOTION_MISS_TTL = 30 * 86400`

> A miss is not remembered for ever: Apple does add animations to older records,
> and a month is soon enough to notice without asking on every play.

**line 2544** — before `HLS_VARIANT = re.compile(r"^#EXT-X-STREAM-INF:.*?RESOLUTION=(\d+)x(\d+)", re.M)`

> RESOLUTION=1080x1080 on the variant line, whose URL is the line after it


### `best_variant`

**line 2581** — before `for nxt in lines[i + 1:i + 4]:`

> the URL is the next line that is not itself a tag


### module level

**line 2604** — before `EDITION = re.compile(`

> The bits Apple hangs an edition off: "(Deluxe Edition)", "- EP", "- Single".
> They belong in the match -- a deluxe is not the plain record -- but not in the
> search term, which is where they do damage.

**line 2612** — before `AM_ALBUM = re.compile(r"music\.apple\.com/[a-z]{2}/album/[^/\"?]+/(\d+)")`

> Album links on music.apple.com's own search page, which is how records the
> Search API has not indexed are found at all.


### `_plain`

**line 2620** — on `    for _ in range(2):`

> "... (Deluxe Edition) [Explicit]"


### `_web_albums`

**line 2653** — on `        if len(ids) >= 12:`

> the page also lists songs, playlists, artists


### `motion_url`

**line 2682** — before `single = not album or _loose(_plain(album), _plain(title))`

> A single is filed under the song: either the player gives no album at all,
> or it gives the song's name back (sometimes as "Title - Single").

**line 2703** — before `if not (_loose(name, theirs) and _loose(artist, by)):`

> Both must agree. Neither alone is enough: the title alone lets
> another artist's record through, and the artist alone lets any
> of their other records through -- the search returns four of
> NF's on this very query.

**line 2710** — before `rank = 2`

> An exact title beats an edition of it, so a plain album is
> preferred to its deluxe when both are the right artist's --
> and the record asked for beats a near-namesake of it.

**line 2720** — on `            break`

> the API answered; no need for the web page


### `MotionArt._memo`

**line 2782** — on `                self._known = {}`

> absent, or written by a crash


### `MotionArt._remember`

**line 2796** — on `            tmp.replace(MOTION_MEMO)`

> never a half-written file

**line 2798** — on `            pass`

> a cache that cannot be written is


### `MotionArt`

**line 2799** — before `def _decode(self, url: str, out: pathlib.Path) -> list:`

> slower, not broken


### `MotionArt._decode`

**line 2808** — before `"-q:v", "2",`

> default jpeg quality is visibly soft on a cover this size,
> and the frames are cached once and read many times

**line 2813** — before `flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0`

> Without this a console window blinks up on Windows every time an
> album is fetched, in front of whatever the user was doing.

**line 2821** — on `            return []`

> no ffmpeg here; still covers carry on


### `MotionArt._frames`

**line 2833** — on `                return []`

> asked lately; this record has no animation

**line 2834** — before `url = memo.get("url") or ""`

> A remembered URL is tried first and the search skipped entirely.
> If it has expired since -- Apple's asset URLs do -- the search
> still stands behind it, so a stale entry costs a decode, not a
> blank cover.

**line 2844** — before `imgs = []`

> QPixmap is GUI-thread-only; QImage is not, so the conversion waits


### `ArtCache._work`

**line 2929** — before `if max(img.width(), img.height()) > self.size:`

> scaled before it ever reaches the GUI: a 640px cover kept at full
> size for a 160px card is how you spend 100MB on thumbnails


### `Fetcher.__init__`

**line 2999** — before `self.done: str = ""`

> The last track a lookup ran to completion for, so the view can tell
> "this song has no lyrics" from "the answer is not back yet". Plain
> attribute on purpose: written here, read from the GUI thread, and one
> frame late is not worth a lock on every paint.


### `Fetcher.request`

**line 3018** — before `if meta:`

> title/artist/length, for the fallback providers that search by name


### `Fetcher.request_catsearch`

**line 3057** — before `with self._lock:`

> last-wins on purpose: this is called on every keystroke, and the run
> loop only picks it up every 0.4s, so typing throttles itself


### `Fetcher.run`

**line 3080** — before `pending: dict[str, float] = {}      # track id -> when to ask again`

> Emitting into a half-destroyed widget as the process exits is a
> segfault; the view sets this before it goes away.

**line 3082** — on `        pending: dict[str, float] = {}`

> track id -> when to ask again

**line 3083** — on `        backoff: dict[str, float] = {}`

> track id -> how long it waited last

**line 3098** — before `if tid and pending.get(tid, 0) <= time.monotonic():`

> The lyrics first, before any of the rest of it.
>
> This pass is one thread doing every job that was asked for since
> the last one, and the lyrics used to be the LAST of them -- behind
> an artist overview (measured at 240-420ms), a NetEase
> romanisation over the network, a queue read, a discover shelf, and
> a hundred-entry page of the cache index (~180ms). None of those is
> being waited on by anybody; the words on screen are. A track
> change that happened to land in a pass with a few of them queued
> waited out all of them first, which is where the half second that
> comes and goes was coming from.
>
> Nothing below depends on any of this having run, so the order is
> free -- it was simply the order the jobs were added in.

**line 3113** — before `asked = tid in pending`

> Spicy Lyrics gets a second chance before anything else is
> asked: a track it has not fetched yet looks identical to one
> it has nothing for, and going out to the network on the first
> miss would step in front of it every single track change.

**line 3119** — before `if asked or lines:`

> Only now is "no lyrics" a verdict rather than a wait. The
> chain can spend the better part of a minute -- an amll index
> refresh, then YouLy+, then three NetEase releases -- and the
> view used to call the song instrumental seven seconds in and
> rearrange the window around that, only to undo it when the
> lyrics landed. `asked` is the pass that consulted everything;
> before it, an empty answer means only that Spicy Lyrics has
> not written its cache yet.

**line 3133** — before `step = backoff.get(tid)`

> Spicy Lyrics writes its cache only after fetching a song,
> so a fresh track often is not there yet -- ask again soon.
> Soon, and then less often: the usual reason to be here is
> that its fetch is still in flight and will land within a
> moment, which a flat two-second wait turned into two
> seconds of blank screen on most track changes.
>
> The interval is kept, not the deadline. `pending` holds
> when to ask next and is always in the past by the time it
> is read here, so doubling it doubles nothing.

**line 3189** — before `self._backfill_batch()`

> one page per pass, exactly like _index_batch -- a 1900-track
> sweep done inline would starve every track change for a minute

**line 3195** — before `self._index_batch()`

> One batch per pass, not the whole sweep: a full ~1850-song
> build takes ~9s, and doing it inline meant a track change
> during it got no lyrics until it finished.

**line 3199** — before `time.sleep(POLL_WAITING if tid and tid in pending else POLL_IDLE)`

> Idle, this asks Spotify what is playing two and a half times a
> second, which is often enough for a window nobody is looking at
> and is where up to 0.4s of every track change went. While THIS
> song is still waiting for its words it looks more often -- the
> wait is the one moment the interval is visible.
>
> `tid in pending`, not `pending`: entries are only removed when a
> song's lyrics finally arrive, so a couple of instrumentals early
> in a session leave the dict permanently non-empty, and asking it
> whether anything is outstanding would hold the fast poll on for
> the rest of the run.


### `Fetcher._index_batch`

**line 3246** — on `        if not batch:`

> done, or the page went away

**line 3258** — before `items = doc.get("Content") or doc.get("Lines") or []`

> cheap per-song facts the browse shelves group by; captured
> here because re-reading 2000 cache entries later is not


### `Fetcher._catsearch`

**line 3349** — before `rank = {"Track": 0, "Album": 1, "Artist": 2}`

> JS_SEARCH already says what each hit is; heading them by that beats one
> "On Spotify" pile where a track, its album and its artist all look
> alike. Sorted by kind because Spotify returns them in relevance order,
> interleaved -- and the painter starts a new heading every time the
> section changes, so unsorted rows would repeat the same three headings
> all the way down.


### `Fetcher._load`

**line 3406** — before `ahead = order[:order.index("spicy")] if "spicy" in order else []`

> Whoever the user put above Spicy Lyrics. They are asked even when it
> has word timing of its own, and they win a tie -- being asked only
> after it had already failed is what made moving them up do nothing.

**line 3411** — before `return self._only_fallback(tid)`

> Nothing to wait for, so do not sit through the "the cache may not
> be written yet" retry that only makes sense when we are asking it.

**line 3431** — before `return self._only_fallback(tid)`

> Spicy Lyrics lives inside Spotify and is only reachable
> over the debug port. Where that port is shut -- a Windows
> box driven by the system media transport, most of all --
> giving up here meant no lyrics at all, when amll, NetEase
> and LRCLIB were sitting right there needing nothing but a
> title. Carry on without it rather than without anything.

**line 3440** — before `self._interim(tid, body)`

> Put what we already have on screen before going out to the
> network. Spicy Lyrics has answered by now and the chain is about
> to spend seconds looking for something better -- seconds the song
> is already playing through. Showing its lines meanwhile costs
> nothing and is very often the answer anyway; if the chain does
> come back with better, the final emit below replaces them.

**line 3447** — before `better = self._fallback(tid, have, ahead, local=body)`

> Spicy Lyrics' own document goes along: the blend wants Apple
> Music for its lines, and this usually IS Apple Music, fetched
> already and often a better copy than the scrape it would
> otherwise settle for.

**line 3453** — before `merged = None`

> The one case where the words on screen and the clock behind
> them are worth taking from different places: Spicy Lyrics' own
> lines, timed by NetEase.
>
> Only ever downwards, though. Ranking NetEase above Spicy
> Lyrics says NetEase is the one to believe about this song, and
> answering that by handing its timings to the source it was
> ranked above is the opposite of what was asked for -- the
> words come back from Spicy Lyrics and NetEase is left holding
> the clock. Ranked above, it is simply the answer.
>
> `_source` names the provider that won the walk, which is not
> always the source the document came from: a blend that found
> nothing to blend hands one source's copy straight back and
> records which in `_alone`. Reading only `_source` meant that
> turning the blend on quietly turned this off -- on Koven's
> "Light Up" the blend had nothing of its own to say, passed
> NetEase's document through under its own name, and the graft
> never saw it. What reached the screen was NetEase's own
> transcription, which is missing the "High, high, yeah" hook
> the song opens on.


### `Fetcher._fallback`

**line 3540** — before `doc["_source"] = name`

> ride along in the document, so nothing else needs a new signal


### `retime_roman`

**line 3594** — before `theirs, gword, gchar = [], [], []`

> their letters, each remembering the word and the offset it came from

**line 3602** — before `mine, syl = [], []`

> our letters, each remembering its syllable

**line 3612** — before `at: list[int | None] = [None] * len(theirs)`

> where each of their letters sits in ours; unmatched letters stay None

**line 3617** — before `anchored = {gword[c] for c in range(len(theirs)) if at[c] is not None}`

> a word none of whose letters matched anything is a word the sync has no
> room for -- noted before the gaps get filled in below, or every word ends
> up looking matched

**line 3621** — before `owner: list[int | None] = [syl[p] if p is not None else None for p in at]`

> an unmatched letter belongs with whatever its neighbours matched, or the
> syllable boundaries land inside a spelling difference

**line 3637** — before `atoms = []          # (word, text, syllable or None)`

> cut each word where its syllable changes

**line 3638** — on `    atoms = []`

> (word, text, syllable or None)

**line 3642** — on `        if not n:`

> nothing but punctuation

**line 3658** — before `out = []`

> times, sharing a syllable out between everything that landed inside it

**line 3672** — before `total = sum(len(a[1]) for a in run) or 1`

> several words inside ONE timed syllable -- 「目にも止まらん」 is a
> single token Genius writes as "Me ni mo tomaran" -- so share it
> out by length rather than lighting them all up together

**line 3686** — before `for i in range(1, len(out)):`

> keep the fill moving forwards, one piece at a time

**line 3695** — before `timed = {w for s, e, w, _ in out if s is not None} & anchored`

> A word the sync has no room for stays on screen and stays untimed, which
> leaves it in the dim base layer and out of the fill -- there, but visibly
> not being sung. Genius prints backing vocals inline, so a lead line can
> come back carrying a "(Hey! Hey!)" that is sung by someone else entirely.

**line 3702** — on `         i + 1 < len(out) and out[i + 1][2] == w)`

> part-of-word: no space yet


### `prepare`

**line 3710** — before `if ln["end"] is None and ln["start"] is not None:`

> A line with no EndTime never stops being "active", which pins the
> auto-scroll to it for the rest of the song. Clamp to the next start.

**line 3713** — before `nxt = next(`

> the next start that is actually later -- a concurrent voice below
> this one can begin earlier, and clamping to it ends the line
> before it starts

**line 3722** — before `ln["pieces_roman"] = ln.get("syls_roman") or (`

> Line-level lyrics have no syllables to hang a romanisation on, but the
> source still carries one for the whole line -- split it the same way
> the original text gets split so it can still fill in sync.


### module level

**line 3750** — before `# --------------------------------------------------------------------------`

> live link -- the editor pushes what it is working on, and it appears here


### `LiveLink`

**line 3773** — before `clear = pyqtSignal()`

> No signal for the document itself: _handle calls the view directly, so
> the reply can say whether it could be drawn. See there.


### `LiveLink.__init__`

**line 3791** — before `app.aboutToQuit.connect(self.close)`

> Close the door before the interpreter goes: a listening socket
> whose event loop has been torn down aborts the process, which
> would turn a clean exit into a crash dialog.

**line 3796** — before `self.error = self.server.errorString()`

> Nearly always a second copy of the app already holding the port.
> Not fatal and not worth a dialog: everything else still works,
> and the editor will simply say it cannot reach a player.


### `LiveLink._watch`

**line 3834** — before `self._pulse.start(50)`

> 20 times a second, and only while an editor is connected: it is two
> float comparisons, and it is the difference between a tap landing
> where the song is and where it was before you dragged the scrubber.


### `LiveLink._handle`

**line 3897** — before `pos=float(v.position()),`

> Two clocks, because they are two different times.
> `pos` is where the PLAYER is; `offset` is what this
> app takes off it before matching a lyric to it. The
> editor stamps pos - offset, so a time it writes is
> the time the player will light it at.

**line 3904** — before `at=time.monotonic(),`

> WHEN that reading was taken, on this machine's
> monotonic clock. The editor is another process on the
> same machine, so it can extrapolate from the same
> instant this app does instead of from whenever the
> answer happened to arrive -- which is what made a
> time stamped just after a seek or an unpause land
> somewhere else.

**line 3918** — before `ok = self.view.show_live_lyric(`

> Called rather than emitted: the reply has to carry whether
> the document could actually be drawn, and a signal has
> nothing to hand back. Same thread either way -- the server
> runs on the GUI one.

**line 3928** — before `body = self.view.body`

> What the player is SHOWING, whatever produced it: the Spicy
> Lyrics community document, a provider from the chain, or an
> alignment this machine made. None of those is reachable from
> the editor's own fetch -- the chain has no "spicy" provider in
> it, and an alignment lives only here -- so the editor asks the
> thing that has it rather than trying to find it again.

**line 3950** — before `try:`

> In LYRIC time, like everything else the editor sends -- the
> offset is put back on here, where it is known.


### `Aligner`

**line 3983** — on `    finished_track = pyqtSignal(str, bool, str)`

> track id, worked, message


### `Aligner.__init__`

**line 3988** — on `        self._settings = view_settings`

> a callable, read per job

**line 3990** — on `        self._done: set = set()`

> tried this session, right or wrong

**line 3991** — on `        self.busy: str = ""`

> the track being worked on

**line 3993** — before `self._abort = False`

> Set to abandon the job in hand. Read by the worker between pieces of
> work, cleared as the next job starts -- see cancel().


### `Aligner.request`

**line 4005** — before `if not asked and tid in self._done:`

> A speculative job is offered once per session. The manual key is
> allowed to insist -- that is what pressing it means.


### `Aligner.run`

**line 4075** — on `            except Exception as exc:`

> a worker thread must not die

**line 4079** — before `if not stopped:`

> A job that was abandoned was not tried. Remembering it as
> tried would mean the track it was taken off never got
> another offer this session, which is the opposite of what
> interrupting it was for.


### `Aligner._sync_align`

**line 4104** — before `keep=not cfg.get("free"))`

> "Free models after aligning" off means keep it
> loaded: 4.0s of every song, for 1.11 GB.

**line 4108** — before `LA_err = f"the sync model: {type(exc).__name__}: {exc}"`

> Saying which model failed matters: the two fail for entirely
> different reasons and the message is all the user gets.


### `Aligner._align`

**line 4118** — on `            return True, ""`

> already measured, nothing to do

**line 4121** — before `where, _win, why = LA.room(cfg["device"], LA.ALIGN_COST,`

> Speculative work does not get to be expensive. If the aligner
> would land on the CPU there is no room for it right now, and a
> song that may well be skipped is not worth ten minutes of it.

**line 4128** — on `                    self._done.discard(tid)`

> ask again when the card frees

**line 4130** — before `if not asked:`

> What the chain has for this song, asked for one thing only: whether
> anyone has already word-synced it. It used to be the aligner's anchor
> donor as well, and that is gone -- the chain finds a document by title
> and artist, and on "LOSE MY NUMBER" it found a different song of the
> same name and offered its line times. The anchors are heard from the
> audio now. See local_align._model_points.

**line 4137** — before `names = [n for n in cfg["order"] if n in cfg["sources"] and n != "local"]`

> Already word-synced by somebody? Then there is nothing to add:
> "local" sits below them in the running order, so an alignment
> could not be shown even if it were better. See SRC_DEFAULT.

**line 4145** — before `doc = LA.genius_doc(cfg["token"], meta)`

> The words come from Genius and from nowhere else. The player's chain
> ranks documents by how well they are TIMED, which is the wrong
> question when the timing is about to be measured from the audio: it
> will take a line-synced document of the wrong song over an unsynced
> one of the right song. FE!N was that -- NetEase name-matched a Chinese
> beat listing, "BPM：150 / KEY： / -音名：D", and being line-synced it
> won, and the aligner faithfully timed somebody's sales notes.

**line 4161** — before `return False, (f"no copy of {title}: {LA.fetched.last_error}"`

> The reason matters and used to be invented here: every way
> of not getting a copy was reported as the length being
> wrong, including a download the far end simply refused.

**line 4174** — before `LA.release()`

> Whatever happened. A run that failed halfway has loaded just as
> much as one that finished, and the window may now sit untouched
> for an album's worth of songs holding all of it.

**line 4179** — before `if self._abort:`

> Stopping was asked for, so it is not news and not a failure.
> run() already knows not to remember an abandoned track.

**line 4186** — before `LS.forget(tid)`

> The chain remembers which provider won and would go on saying so.
> This is the one thing that can change that answer after the fact, so
> it is also the one thing that has to clear it.


### `LyricsView.__init__`

**line 4205** — before `self.est_raw: dict[str, dict] = {} if args.no_persist else load_est()`

> What the estimator read on each track, before calibration. Kept raw on
> purpose: the correction subtracted from it moves as more tracks are
> fixed by hand, and storing the corrected figure would freeze each one
> against whatever the calibration happened to be the day it was taken.

**line 4210** — before `self.est: dict = {}`

> This track's measurement, and the tid it belongs to -- so a reading
> cannot outlive a track change and be shown against the next song.

**line 4214** — before `self._said_outranked: str = ""`

> The last track we explained an outranked alignment for, so it is
> said once rather than on every answer the fetcher sends.

**line 4217** — before `self._cal_gen = 0`

> Bumped by anything that moves `offsets` or `est_raw`; calibration()
> recomputes when it sees a number it has not answered for yet.

**line 4224** — before `self.ne_fix: dict[str, dict] = {}`

> Not persisted, unlike the Genius map: this one is cheap to ask for
> again and comes from a source whose own cache already expires.

**line 4228** — before `self.align_on = getattr(args, "align_on", DEFAULTS["align_on"])`

> Held here, acted on by align_song.py. Nothing in the window aligns
> anything itself: these say what that tool may do to the card when it
> is run, and are in the menu because that is where every other setting
> about this song's timing already lives.

**line 4243** — before `self.artists: dict[str, list] = {}`

> tid -> [{name, uri}] for everyone credited, straight from the page

**line 4245** — on `        self.albums: dict[str, dict] = {}`

> tid -> {name, uri}

**line 4246** — before `self.detail: dict | None = None`

> {kind, uri, data} for the page being shown, and the pages behind it

**line 4251** — on `        self.editing = False`

> text-entry overlay

**line 4252** — on `        self.edit_mode = "romaji"`

> or "token", or "font"

**line 4254** — on `        self.edit_caret = 0`

> where typing lands

**line 4255** — on `        self.edit_sel: int | None = None`

> the other end of a selection, if any

**line 4256** — on `        self.edit_pristine = True`

> nothing typed yet, so a paste replaces

**line 4258** — on `        self.edit_for = ""`

> original line the correction belongs to

**line 4295** — before `self.drift: dict = {}`

> word key -> [dx, dy, vx, vy, angle, spin], in screen space

**line 4297** — on `        self.cloudy: dict = {}`

> word key -> [born, ex, ey, xx, xy, phase, seen]

**line 4299** — on `        self.source = ""`

> which provider the current lyrics came from

**line 4300** — before `self.genius_tried: set[str] = set()`

> tracks already asked about this session, so a failed lookup is not
> retried on every poll

**line 4306** — before `self._duet_rgb = (None if self.duet_color in DUET_MODES`

> a literal #rrggbb from the config wins; the named modes derive theirs

**line 4310** — on `        self.raw: list[dict] = []`

> timeline before interludes were folded in

**line 4313** — before `self.dropped: str | None = None`

> A lyric or a cover dropped on the window, held for the song it was
> dropped on and nothing else. Neither is ever written anywhere.

**line 4325** — on `        self.browse = 0.0`

> 0 = following along, 1 = reading around freely

**line 4327** — before `self.line_rects: list[tuple[int, float, float, float, float]] = []`

> (index, top, height, click_x_min, click_x_max)

**line 4334** — before `self.hot: list = []`

> (rect, kind, payload) for the chrome that can be clicked -- the title,
> the artists, the album. line_rects covers the lyrics and nothing else,
> and these are not lines.

**line 4350** — before `self.view = "lyrics"              # "lyrics" | "browse"`

> -- browse view (home / search). `view` is a peer of the window, not a
> sixth overlay flag: it swaps out the whole base layer.

**line 4352** — on `        self.view = "lyrics"`

> "lyrics" | "browse"

**line 4353** — on `        self.browse_tab = "home"`

> "home" | "search"

**line 4356** — on `        self.browse_rects: list[tuple] = []`

> (kind, payload, QRectF), each paint

**line 4359** — on `        self.bq = ""`

> browse search query

**line 4360** — on `        self.bq_hits: list[dict] = []`

> flattened, catalogue + local

**line 4361** — on `        self.bq_cat: list[dict] = []`

> from Spotify

**line 4362** — on `        self.bq_local: list[dict] = []`

> from the lyric index

**line 4374** — on `        self.suggest_for = ""`

> artist uri the suggestions are for

**line 4400** — before `self._marq: dict = {}`

> per-text-slot start time for the title/artist scroll, and whether any
> of them moved on the last frame -- tick() needs that to keep painting

**line 4404** — before `self.palette = [QColor(120, 60, 80), QColor(70, 60, 120), QColor(120, 90, 60)]`

> stand-in until the cover loads and palette_of() replaces it

**line 4414** — before `_disk = {} if args.no_persist else load_settings()`

> Seed with what is already on disk so an instance that changes nothing
> never writes -- otherwise every launch stomps the file and two open
> windows fight over it. A CLI flag that differs still gets saved.

**line 4429** — before `self.setWindowTitle(f"{APP_NAME} — {os.getpid()}")`

> Distinctive enough for the KWin script in keep_above() to match on:
> under Wayland the only handle it gets is the caption, and a bare
> "Lyrics" would also match a browser tab or a file manager window.

**line 4434** — before `self.setAcceptDrops(True)`

> Files may be dropped straight onto the window: a TTML to watch it
> against the audio, a picture to stand in for the cover.

**line 4438** — before `self.src_order = [n for n in raw_order if n in SRC_LABEL]`

> anything unknown dropped, anything missing appended: a hand-edited or
> older config must not be able to lose a provider outright

**line 4446** — before `threading.Thread(target=self._font_later, daemon=True).start()`

> Configured but not installed here, and startup must not sit on a
> download -- so fetch it behind the window and swap it in when it
> lands. Until then the built-in stack draws, which is the same
> thing that happens if the name turns out not to exist at all.

**line 4477** — before `self.aligner = Aligner(self.align_settings)`

> Its own thread, not the fetcher's: an alignment takes minutes and
> every track change would queue behind it. Idle until something asks.

**line 4486** — before `self.link = LiveLink(self)`

> The editor's way in. Made before the timers so a document pushed
> during startup is not answered by a half-built window.

**line 4496** — on `        self.eff_hz = 60.0`

> until the window is mapped and has a screen

**line 4500** — before `self.frame_timer.setTimerType(Qt.TimerType.PreciseTimer)`

> a coarse timer is allowed to drift 5%, which at these intervals is a
> whole frame either way


### `LyricsView.retune_frames`

**line 4519** — on `        if hz <= 0:`

> some Wayland outputs report 0 before mapping


### `LyricsView.showEvent`

**line 4528** — before `super().showEvent(ev)`

> A window has no QScreen until the compositor has mapped it, so the
> value read in __init__ is a guess and this is the first honest one.


### `LyricsView.follow_screen`

**line 4550** — on `                    pass`

> already gone, e.g. the output was unplugged


### `LyricsView.load_cached_fonts`

**line 4584** — before `for stale in FONT_DIR.glob("*.ttf"):`

> nothing reads the older shapes again; leaving them costs a
> download's worth of disk and confuses the next person to look


### `LyricsView.resolve_font.pick`

**line 4611** — before `fold = {f.lower(): f for f in have}`

> case is the usual slip -- "segoe ui" for "Segoe UI"


### `LyricsView.resolve_font`

**line 4622** — before `self.family = min(fams, key=len)`

> A variable file registers its base family and a named
> instance beside it -- ["Outfit", "Outfit Thin"] -- and the
> instance is the one that ignores setWeight. Take the
> shortest name, which is the base every time.


### `LyricsView.lyric_font`

**line 4667** — on `        return self._weigh(f, self._weight(QFont.Weight.Black))`

> Outfit 900


### `LyricsView.ui_font`

**line 4671** — before `return self._weigh(f, self._weight(weight)`

> only the heaviest UI text follows a pin; labels stay readable


### `LyricsView.poll`

**line 4678** — before `self.clock.poll(self.resync)`

> Both things this setting governs are the app nudging the player to keep
> the words on the sound: the seek after a hand-off, and the pin on pause.

**line 4681** — before `if (self.align_on and self.align_ahead and self.clock.status == "Playing"`

> Look at what is coming up, now and then. Only while something is
> actually playing and nothing is being aligned already -- a paused
> player is not about to need the next song, and one round trip a
> minute is nothing against a job that takes three.
> Asked for whether or not a job is running. It used to wait for the
> worker to be free, which meant the queue on file was the one from
> before a three-minute alignment started -- so the pruning below had
> nothing fresher to compare against, and the worker went on to songs
> that had been skipped past long ago.

**line 4698** — before `handed_over = prev is not None and time.monotonic() - self.skip_at > 3.0`

> A track we did not ask for means Spotify rolled over on its own,
> which is the case where its output drifts from its clock.

**line 4706** — before `length = self.clock.meta.get("length", 0.0)`

> Approaching the end of a track, poll hard: the id has to be noticed
> promptly or the new song's first lines render against the old clock.

**line 4716** — before `if self.clock.tid and self.clock.meta.get("title") and self.index.songs:`

> whatever plays teaches the search index its own title, for free

**line 4721** — before `self._browse_tid = self.clock.tid`

> The track moved on under the browse screen: the now-playing card,
> the suggestions (which are keyed off the artist) and the queue are
> all about what is playing, so all three follow it.

**line 4733** — before `album = self.clock.meta.get("album", "")`

> Keyed by album, not by track: every song on a record shares one
> animation, so a whole album plays through on a single fetch.

**line 4737** — before `if self.motion_art and (album or title):`

> A player that reports no album at all leaves the song to stand for the
> release, which is what a single is anyway.

**line 4740** — before `lead = (split_artists(title, self.credits())[0]`

> the lead artist, not the whole credit: iTunes files a record under
> whoever released it, so "Kendrick Lamar, SZA" finds nothing that
> plain "Kendrick Lamar" would have found


### `LyricsView.apply_romaji_fixes`

**line 4757** — before `auto = self.genius_fix.get(tid, {})`

> Genius underneath, anything you typed on top -- a hand correction is
> the last word on a line and must survive the next re-fetch.

**line 4761** — before `ne = self.ne_fix.get(tid, {})`

> Below Genius, not beside it: where both have a line, Genius wrote it
> as words and NetEase one mora at a time, and words read better.

**line 4770** — before `fix = auto.get(text) or ne.get(text)`

> A line already in Latin script has nothing to romanise, and
> Genius sends one back for it anyway -- the alignment is fed
> every line so the ordering holds, and English matches English.
> Applying that put a second, near-identical row under every
> English line ("I won't give up the fight in my life" under
> "I won't give ​up the fight in my life"), which on a mostly
> English song is the whole screen. Typed corrections still go
> through: if you asked for one on a line, you meant it.


### `LyricsView.fetch_genius`

**line 4830** — before `if not self.ne_fix.get(self.clock.tid or ""):`

> Asked for at the same time, not as a rescue after Genius fails. Genius
> can come back having matched most of a song and left a handful of
> lines behind -- an alignment that scored under the threshold, or a
> line its page never had -- and those gaps are invisible from here.
> Having NetEase's answer already in hand means they simply fill.


### `LyricsView.on_genius`

**line 4844** — before `if not quiet:`

> NetEase was asked at the same time and may still answer, so this
> is not the end of the road for the track.


### `LyricsView`

**line 4904** — before `def dragEnterEvent(self, ev) -> None:            # noqa: N802 (Qt name)`

> A TTML dropped on the window is shown straight away, and only shown: it
> is never written to the cache, never saved as an alignment, and it lasts
> until the song changes. That is the point of it -- a file being worked on
> can be watched against the audio without being installed anywhere first.


### `LyricsView.show_dropped_lyric`

**line 4945** — before `if pathlib.Path(path).suffix.lower() in (".lrc", ".elrc"):`

> By what it is, not by hoping: parse_ttml on an LRC returns
> nothing at all and the drop would look broken rather than
> unsupported.

**line 4959** — before `self.dropped = self.clock.tid`

> Held against the fetcher, which answers every few seconds and would
> otherwise put the song's own lyric back over this within a breath.


### `LyricsView.show_live_lyric`

**line 4987** — before `self.toast(f"following {name}")`

> First push of a session. Say it once, so it is clear the words
> on screen are now coming from somewhere else.


### `LyricsView.show_dropped_art`

**line 5014** — before `self.on_art((img, blurred, palette_of(img)))`

> on_art rather than art_ready: this is already the GUI thread, and
> QPixmap may only be touched here.


### `LyricsView.reset_track`

**line 5022** — before `self.dropped = self.dropped_art = None`

> A dropped file belongs to the song it was dropped on. Both go here so
> the next song gets its own lyric and its own cover back.

**line 5026** — before `self.track_at = time.monotonic()`

> when this track came up, so "still looking" can be told from "nothing
> to find" without the two flapping at each other

**line 5029** — before `self.beat.clear()`

> ...and the palette rotation that came with it, or a track with no
> analysis inherits the last song's colours

**line 5032** — before `self.est, self.est_tid = {}, None`

> The stored reading in est_raw stays; this is only the copy held for
> display, which would otherwise caption the new song with the old
> song's measurement until the replacement arrived.

**line 5040** — before `self.line_rects = []`

> stale rects outlive the lines they describe, and line_at() indexes
> self.lines with them -- a mouse move right after a track change threw

**line 5043** — before `self._marq.clear()`

> a new song's title should start from rest, not halfway through the
> last one's pass


### `LyricsView._load_art`

**line 5062** — before `blurred = img.scaled(`

> cheap gaussian: shrink hard, then upscale in doubling passes


### `LyricsView.nudge_offset`

**line 5100** — before `base = self.offsets.get(tid, self.auto_offset(tid))`

> Start from the total in force, measurement included, so the first
> press nudges what is on screen rather than jumping back to the raw
> timing and stepping from there.


### `LyricsView.measure_offset`

**line 5162** — before `self.est_tid = tid`

> Claimed before the work, not after: measuring a long track walks a
> 300-step curve over a few hundred anchors, and the paint timer will
> call back in here several times before the first pass returns.

**line 5170** — before `self.est = self.est_raw.get(tid, {})`

> Mirror what is actually stored rather than what this pass returned.
> A track measured on an earlier play keeps that reading, and it goes on
> being applied, so a pass that comes back with nothing -- a thinner
> document from a different source, say -- must not leave the panel
> reporting there is no measurement while one is still in force.


### `LyricsView`

**line 5180** — before `@property`

> The setting lives on the clock, which is the only thing that acts on it,
> but the menu reads and writes every row by attribute name on this object.


### `LyricsView.on_beat`

**line 5206** — before `self.measure_offset()`

> Whichever of the analysis and the lyrics arrives second is the one that
> completes the pair, so both call in and the first one is a no-op.


### `LyricsView.on_lyrics`

**line 5220** — before `if not force and self.dropped == tid and body is not self.body:`

> A file dropped on this song wins over anything found for it, until
> the song changes. Without this the fetcher's next answer -- and it
> answers every couple of seconds -- would wipe it off the screen.
>
> `force` is how the file itself gets to change. Every push from the
> editor is a NEW document -- it is re-parsed from the TTML each time
> -- so without this the test below threw away every version after the
> first, and the screen sat on whatever the first edit happened to
> say. The rule being enforced here is "the FETCHER may not overwrite
> a dropped file", and the fetcher never sets this.

**line 5232** — before `if not lines and self.lines:`

> A miss is not news about a song already on screen. The fetcher answers
> every request, including the ones that failed -- a CDP hiccup, a cache
> read that came back short -- and it re-asks a couple of seconds later.
> Taken at face value that empty answer wiped the lyrics, put "waiting…"
> in their place, and left them to reappear on the retry: the flicker.
> Only a track change clears the screen now, and reset_track does that.

**line 5240** — before `same = body is not None and body is self.body and len(lines) == len(self.raw)`

> The same document arriving twice is the ordinary case now: the fetcher
> shows what it has while it looks for better, and most of the time
> there is no better. The second answer still carries something the
> first could not (the duet flags, which cost a network call), so it is
> taken -- but the laid-out text has not changed, and throwing the
> caches away would re-wrap and re-render every line for nothing.

**line 5247** — before `self.raw = lines or []`

> keep the pre-interlude timeline: prepare() builds a new list rather than
> mutating this one, so the gap setting can be re-applied at any time

**line 5250** — before `self.body = body`

> Both before the lines are built: the credit row under them is read
> off the document, and a row built against the last song's document
> would name the wrong writers for one frame.

**line 5258** — before `if not same:`

> A different document is a different timeline -- the fetcher shows what
> it has and keeps looking for better -- so a reading taken against the
> one it replaces no longer describes what is on screen.


### `LyricsView.say_alignment_outranked`

**line 5294** — before `if str(SL.payload(self.body or {}).get("_timing") or "") == "align":`

> Ours would carry the aligner's own provenance -- see to_document.

**line 5298** — before `whose = self.source_name(SL.payload(self.body)) or "another source"`

> Name the source to get above, not just "up". The running order is not
> the ranking it looks like: for a song Spicy Lyrics has already
> word-synced, only the providers listed ABOVE Spicy Lyrics are asked
> at all (see fallback's `ahead`), so "Aligned here" in second place
> behaves exactly like "Aligned here" in last place. Being told to move
> it up, having already moved it up, is no help at all.


### `LyricsView.source_name`

**line 5370** — before `via = {"apple": "Apple Music", "musixmatch": "Musixmatch",`

> Keys lowercased on both sides: the field is spelled "Musixmatch" on
> some answers and "musixmatch-word" on others, and an exact-match table
> quietly fell through to printing the raw value.

**line 5374** — before `"musixmatch-word": "Musixmatch", "qq": "QQ Music",`

> not "(word)" any more -- whatever it called them, those timings
> are read as line timings before they ever reach this label

**line 5378** — before `"qaple": "Apple Music with QQ"}`

> Their own blend label, not a source: word timings from one
> side reconciled against the other. Undocumented, and it does
> not appear in the sourcesStatus list either -- other clients
> render it "Apple with QQ", which is the reading I follow here.

**line 5384** — before `alone = str(doc.get("_alone") or "")`

> A blend nothing could be blended into is just its base source's
> document, and it reads better -- and truer -- under that source's own
> name. `_alone` says which one, and the document was given whatever
> `_via` that source would have set, so the rest of this needs no
> special case: "Blend · Apple Music" becomes the plain "Spicy Lyrics ·
> Apple Music" or "YouLy+ · Apple Music" it really is.

**line 5396** — before `"local": SRC_LABEL["local"]}.get(src)`

> Measured on this machine against the song's own audio. It was
> missing from this table while being a provider like any other
> below, so an alignment that had won the walk fell through to
> the Spicy Lyrics branch and was credited to the one source it
> certainly did not come from -- and the words are not even
> Spotify's, they are Genius'. SRC_LABEL has always called it
> this in the menu; there is no reason for two names.

**line 5405** — before `was = {"spl": "community", "aml": "Apple Music",`

> Spicy Lyrics names its own upstream in three letters. Same form as
> the YouLy+ label below it and the same meaning: one document, from
> one source, which got it from there. Nothing is combined -- the
> "with" spelling above is what a genuine mix looks like.
>
> "aml" is Apple Music, not amll-ttml-db. Worth spelling out because
> the abbreviation invites exactly that misreading, and amll-ttml-db
> is a provider in our own chain, so guessing it here claimed a mix
> of two sources that had never met.

**line 5418** — before `clock = {"netease": "NetEase Cloud Music"}.get(str(doc.get("_timing") or ""))`

> The words are one source's, the clock another's -- say so, rather than
> crediting whichever half the _source field happened to name.


### `LyricsView.made_by`

**line 5440** — before `makers = _people(meta.get("Maker")) or _people(doc.get("_maker"))`

> `_maker` is the same fact off a TTML source -- amll's GitHub login,
> LyricsPlus' curator -- which have an author but no uploader.


### `LyricsView.align_now`

**line 5499** — before `self.toast("local aligning is off")`

> The one refusal the key is allowed: asking for it is normally the
> answer to every other check, but not to having been switched off.

**line 5511** — before `self.toast("already aligned — press again to redo")`

> Re-measuring is what the key is for once one exists, so say what
> is there and let a second press replace it.

**line 5518** — before `gave_way = self.aligner.cancel()`

> Whatever is running is a track the user is not listening to -- this
> key only ever means the song in front of them, and the worker takes
> one job at a time because the card holds one model at a time. So the
> queued-ahead job gives way rather than the request being refused,
> which is what it used to do: press the key while the aligner was two
> minutes into the next song and nothing happened at all.


### `LyricsView.align_ahead_scan`

**line 5546** — before `self.aligner.keep_only({tid for tid, _m in want})`

> What is queued has to match what is coming up, and this is the only
> place that knows both. Pruning first, and doing it whether or not a
> job is running: a queue that has been replaced while the worker was
> busy is exactly the case where the stale jobs would otherwise be
> waiting to run the moment it frees up.


### `LyricsView.on_aligned`

**line 5560** — before `if ok and tid == self.clock.tid:`

> The document on screen was chosen before this existed, so it has to be
> asked for again -- the aligner has already cleared the chain's memory
> of who won. Only for the song actually playing; anything else was
> queued ahead and will be picked up when it comes round.


### `LyricsView.maybe_auto_genius`

**line 5587** — before `if tid in self.genius_tried or self.genius_fix.get(tid):`

> a cached alignment from THIS matcher revision is good; an older one
> was dropped at load, so the track gets looked up again


### `LyricsView.sounding`

**line 5608** — before `held, held_end = -1, None`

> The line to hold is the one that finished LAST, not the one that
> started last: an interjection nested inside a longer line starts
> later but stops sounding first, and holding it dropped the reading
> onto the backing vocal while the line around it was still the one
> being read.

**line 5615** — before `if ln["start"] is None or ln["start"] > pos:`

> scan the lot rather than stopping at the first line past pos:
> concurrent voices mean starts are not strictly ascending

**line 5624** — before `return [0] if self.lines else []`

> before the first line: anchor on it rather than on nothing, or the
> opening of every song is an unreadable smear


### `LyricsView.vfade`

**line 5641** — on `        f = max(0.0, 1.0 - t * t * (3 - 2 * t))`

> smoothstep out

**line 5642** — before `return f + (0.62 - f) * self.browse if f < 0.62 else f`

> this alone takes the bottom of the viewport to zero, so while browsing
> keep a floor or the lines you scrolled to are still not there


### `LyricsView.wrap_pieces`

**line 5717** — before `words: list[list] = []`

> IsPartOfWord means "joins the next syllable with no space", so a run of
> them is ONE word. Group first and wrap only between groups -- wrapping
> per syllable split words across lines ("mo" / "ment").

**line 5736** — before `word = [sub for pc in word for sub in split_to_fit(pc, fm, width)]`

> A group wider than the whole column can never be placed as a
> unit. Japanese and Chinese have no spaces, so the entire line
> arrives as one group and used to run off the right edge --
> break inside it, per character if a single piece is oversized.

**line 5748** — before `if not atomic and x + w > width and rows[-1]:`

> Only the oversized case may break mid-group. The group above
> was measured and placed as a unit, but the check below is per
> piece and the LAST piece carries a trailing space the group
> width never counted -- so a word that fits could still have
> its tail pushed onto the next row by an invisible space, and
> a source that splits at the apostrophe ("Y" + "'all", one word
> by IsPartOfWord) came out as "...Y" / "'all...".


### `LyricsView.layout_line`

**line 5792** — before `out = (rows, cfm, cfm.height() * (1.4 * len(rows) + 1.6),`

> a clear gap above, so the credits read as a footer rather than as
> one more verse nobody sang

**line 5802** — before `rrows, rfm = [], None`

> a romanisation set UNDER the original: smaller, same timings, and its
> height folded in here so scrolling and click extents stay honest


### `LyricsView.drift_of`

**line 5874** — before `if (y0 + h < 0 or y0 > self.height()`

> A word only comes loose once it is actually on screen. Seeding one
> from a line that is still below the fold would clamp it straight
> onto the window edge, leaving a row of words pinned to the bottom.

**line 5887** — on `        st[6] = (w, h)`

> drawn this frame, and how big


### `LyricsView.step_drift`

**line 5905** — on `                continue`

> not on screen this frame; leave it be

**line 5910** — before `if st[0] < 0.0 or st[0] > W - w:`

> Bounce off the window itself -- the word is loose in the whole
> frame now. Reflect and pin, so nothing can tunnel out and be gone.

**line 5918** — before `if len(self.drift) > 400:`

> A song's worth of words would accumulate as the lyrics scroll past, so
> anything that has not been drawn for a few seconds is let go. It gets
> a fresh launch if its line ever comes back.


### `LyricsView.tick`

**line 5939** — before `goal = 1.0 if time.monotonic() < self.user_scroll_until else 0.0`

> Scrolling away means the reader wants to READ over there, but those
> lines are far from the active one, which the depth model renders at
> 10% opacity under maximum blur -- i.e. invisible. Ease into a browsing
> state that lifts the falloff while they are looking around.

**line 5956** — before `self.scroll_target = max(`

> without a clamp the wheel scrolls forever into empty space

**line 5972** — on `        if self.quit_requested:`

> a signal asked us to stop; this is a safe point

**line 5986** — before `self.browse_scroll_target = max(`

> ease the browse scroll on the same timer as the lyric one

**line 5996** — before `if (self.browse_hover is not None`

> a static browse screen should not pin the CPU at 60fps, so this is
> busy only while it scrolls, hovers or is still fetching thumbnails

**line 6003** — before `busy = (moving or self.clock.status == "Playing" or self._marq_live`

> 60fps is only worth paying for while something actually animates
> clouds bob and drift on their own clock, so they animate even paused
> a title too long for its box keeps scrolling whether or not anything
> is playing, and at 10fps that reads as a stutter rather than a slide

**line 6012** — before `if busy or self._idle_frames % max(1, round(self.eff_hz / 10)) == 0:`

> the idle path is a rate, not a frame count: every sixth frame only
> meant 10fps back when the timer was pinned to 60


### `LyricsView.line_pixmap`

**line 6019** — before `key = (idx, int(width), blur, int(self.lyric_px()), self.align, self.roman)`

> `roman` belongs here too: it changes the glyphs that get drawn, not
> just where they land, so leaving it out served the previous script

**line 6038** — before `p.setFont(rufont)`

> the readings sit in the gap reserved above this row

**line 6049** — before `y += fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent()`

> -ruh as well as -ascent: the cursor is sitting on the baseline of
> a row that does not exist, so it carries one more furigana gap
> than there are rows. Without it the romanisation is pushed past
> the height reserved for the line and clipped off the bottom.


### `LyricsView.glow_layer`

**line 6098** — before `spots = ((0.72, 0.30, 0.85, 100), (0.16, 0.86, 0.66, 58), (0.86, 0.80, 0.55, 44))`

> dimmer than the mesh: this only tints a cover that is already there

**line 6101** — before `a = self.palette[(i + self._section) % len(self.palette)]`

> each section of the song leads with a different palette colour


### `LyricsView.scene_layer`

**line 6130** — before `p.setOpacity(0.55)`

> already blurred to mush, so the default (fast) transform is fine


### `LyricsView._paint_mesh`

**line 6147** — on `            ph = i * 2.399`

> golden angle: never in step


### `LyricsView.paintEvent`

**line 6182** — before `self._marq_live = False`

> Re-earned every frame by whichever text is actually still moving; the
> next tick reads it to decide whether to keep the frames coming.

**line 6186** — before `if self.view == "browse":`

> Browse is a sibling VIEW, not an overlay: it replaces the lyrics
> entirely rather than dimming them and sitting on top. So none of the
> scene wash, lyric layout, viewport fade or art panel below runs at all
> -- which is both the look that was asked for and a cheaper frame.

**line 6195** — on `            if ov in ("help", "menu"):`

> the only two that make sense here

**line 6199** — before `if self.view == "detail":`

> Same reasoning as browse: a page about the song replaces the song's
> lyrics rather than floating over them.

**line 6210** — before `e = self.beat_energy()`

> Beat punch: the composed background is cached at 15fps, so pulse it by
> blitting the SAME pixmap into a slightly larger rect. One drawPixmap,
> no extra rasterising, and it lands exactly on Spotify's own beat grid.

**line 6216** — before `p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)`

> the scene is a blurred wash, so smooth-scaling it is a full-window
> resample for no visible gain -- it doubled the punch's frame cost

**line 6229** — on `            pass`

> the panel has the window; nothing goes beside it

**line 6238** — before `why = getattr(self.clock, "last_error", "")`

> Say what actually went wrong. "…" forever, with the real reason
> sitting unread on the clock, is the worst of both: the app looks
> broken and gives no clue that Spotify simply is not listening.

**line 6254** — before `p.drawPixmap(0, 0, self.fade_layer())`

> Full width on purpose: restricting this to the lyrics column left a hard
> vertical seam where its dark top/bottom met the art panel. The panel and
> the HUD are painted after it so they keep their own brightness.


### `LyricsView._paint_lines`

**line 6294** — before `ox = self.line_ox(ln, fm, x0)`

> Clicking to seek used to hit anywhere on the row, so the dead space
> past the end of a short line was live. Record the ink extent (plus
> a forgiving margin) and hit-test against that instead.

**line 6300** — before `lo = hi = ox`

> rows here are plain strings, not laid-out pieces, and there is
> no moment in the song to seek to anyway

**line 6311** — before `nxt_bg = i + 1 < len(self.lines) and self.lines[i + 1]["background"]`

> A loose word travels far from the line it came from, so the line
> has to stay in play well after it has scrolled off -- culled at
> the normal margin, words popped in and out at the edges.
> A backing vocal belongs to the line it sits against, so the space
> between the two is tighter than the space between verses -- it
> used to sit almost as far from its own line as from the next one.

**line 6320** — before `far = (self.clouds > 0 and live`

> Clouds are placed by the live line, not by the scroll, so the whole
> cull window would otherwise home onto the middle of the screen at
> once -- dozens of lines fading in only to fade straight back out.

**line 6327** — before `if self.clouds > 0 and (i in live`

> Clouds wander over each other, so the line being sung has to be
> painted last or a later line drifting across can bury it. Hold
> the live ones back and lay them on top after the rest.


### `LyricsView._paint_panel`

**line 6341** — before `unit = min(panel, self.width() * 0.42)`

> `panel` says where to centre; `unit` says how big to draw. They are
> the same in the ordinary layout, and part company when a track with no
> lyrics hands the panel the whole window: sized off that, the title
> came out twice the size it should be and the artist ran out of box.

**line 6362** — before `block = side`

> Size the block from real metrics, then centre it -- fixed offsets
> clipped descenders and drifted off-centre at other window sizes.

**line 6393** — before `self._scroll_text(p, row, QRectF(bx, y, boxw, fm_t.height() * 1.12),`

> wrap_rows piles the overflow onto its last row rather than
> cutting it, so that is the row with anything left to show

**line 6408** — before `fg = self.ui_font(unit * 0.028, QFont.Weight.Normal)`

> a line of its own, dimmer and smaller: a guest is part of the
> credit but not the answer to "who is this by"


### `LyricsView._paint_volume`

**line 6456** — on `            return`

> not heard from the player yet


### `LyricsView._scroll_text`

**line 6496** — on `        if at < hold:`

> resting at the start

**line 6500** — on `        elif at < 2.0 * hold + travel:`

> resting at the far end

**line 6504** — on `        u = u * u * (3.0 - 2.0 * u)`

> ease in and out of both stops


### `LyricsView._paint_header`

**line 6526** — before `scrim = QLinearGradient(0, 0, 0, 96)`

> lyrics scroll up behind the header -- give it something to sit on

**line 6535** — before `thumb_pm = self.motion_frame() or self.art_full`

> The cover, small, beside the song rather than in a panel of its own.
> Sized to the two rows of text so the block reads as one object, and
> taken from art_full -- already in memory for this track, so there is
> nothing to fetch and nothing to cache.

**line 6581** — before `if self.show_volume:`

> Off to the right of the strip, clear of the title's scrolling box


### `LyricsView.spin_frag`

**line 6601** — before `box = QRectF(ox + x - 2, ry - fm.ascent() - ruh - 2,`

> generous, so antialiased edges and descenders go with it


### `LyricsView.cloud_pixmap`

**line 6622** — before `lobes = ((0.50, 0.50, 0.44), (0.24, 0.56, 0.34), (0.76, 0.56, 0.34),`

> A ring of overlapping lobes along the middle, so a wide stretch reads
> as a bank of cloud rather than one blown-up blob with a soft edge.


### `LyricsView.cloud_of`

**line 6653** — on `            far = max(W, H) * 1.15`

> comfortably outside, whatever the shape

**line 6658** — before `(((n >> 17) % 200) / 100.0 - 1.0),`

> where in the column this line likes to sit, so they do not
> all pile onto the same spot


### `LyricsView._paint_cloud`

**line 6695** — before `st = self.cloud_of((idx, ln.get("text", "")), W, H)`

> how far out of the way this line has drifted: 0 while it is current,
> 1 once it is several lines behind and should be gone

**line 6698** — before `span = 3.2 / max(0.4, k)`

> Arrival and departure are timed, not tied to how far the line is: tying
> them to line distance made them step rather than glide. Distance only
> decides WHEN to leave; the leaving itself runs on its own clock.

**line 6705** — on `            st[7] = 0.0`

> came back before it finished going

**line 6709** — on `            return`

> gone; nothing left to draw

**line 6711** — before `colw = colw or float(W)`

> Home is independent of the scroll. Anchoring to the scrolled position
> meant every cloud slid up the screen as the song advanced -- a second
> motion competing with the drifting, which is what made it look wrong.
> The scroll still decides WHICH lines are in play; it no longer decides
> where they sit.

**line 6720** — before `t, ph = now * 0.055 * k, st[5]`

> A slow wander right across the window. Two sine terms per axis at
> unrelated rates, so the path never visibly repeats, phase-shifted per
> line so no two move together.

**line 6728** — before `dx = (home_x + st[1]) + (dx - home_x - st[1]) * tin`

> come in from off-screen, settle onto the wander, then leave

**line 6734** — before `if out <= 0.0 and tin >= 1.0 and not ln.get("dots"):`

> Keep the words on screen even at the extremes of the wander -- only
> once it is actually leaving is it allowed to sail off the edge.

**line 6741** — before `left = x0 + 8.0`

> the album-art panel is painted after the lyrics, so a line that
> wandered left disappeared underneath it -- stay in the column

**line 6756** — before `if row:`

> one bank of cloud behind the whole row, not per word: the words
> travel together, so the cloud they sit in should too

**line 6764** — before `size = mh * 2.6`

> A bank of overlapping round puffs along the row rather
> than one pixmap stretched over it -- stretched, the
> lobes smear into a lozenge and stop reading as cloud.

**line 6774** — before `bob = math.sin(f * 3.1 + ph * 2.0) * mh * 0.22`

> ride a shallow arc and jitter per puff, so the top
> edge is lumpy instead of a straight line


### `LyricsView._paint_loose`

**line 6835** — before `p.setOpacity(1.0)`

> once, not per word: everything below carries its alpha in the pen, so
> a value left behind by whatever painted last must not leak in

**line 6859** — before `key = (idx, is_rom, r_i, round(x, 1), txt)`

> Keyed on where the word sits WITHIN its line, never on
> screen position: the latter changes with every scroll,
> which would hand the word a fresh state each frame and
> leave it twitching in place instead of drifting.

**line 6867** — on `                        continue`

> its line has not reached the screen

**line 6868** — before `px, py = st[0], st[1] + met.ascent()`

> st holds the box top-left in window space; the baseline is
> an ascent below it

**line 6871** — before `if (px + w < 0 or px > W or py < -mh or py - mh > H):`

> The line cull has to be generous (a loose word travels far
> from its line), which drags in a lot of lines whose words
> are nowhere near the window. Rejecting those here, before
> any painter state is touched, is what keeps the frame rate
> up -- drawText on off-screen text is not free.

**line 6884** — before `p.setPen(QColor(TEXT.red(), TEXT.green(), TEXT.blue(),`

> No viewport fade at all here. It exists to hold the eye in
> a reading band around 0.40H, which is meaningless once the
> words are loose -- and worse than meaningless, because it
> falls to nothing at the edges, so it dimmed a word for
> drifting exactly where this setting is meant to send it
> and left the bottom of the window permanently empty.
> Depth still comes from the line-distance falloff in alpha.
> Alpha goes in the PEN, never through setOpacity. Qt
> implements setOpacity under a transform by compositing
> through a temporary buffer, which measured at 13.2ms per
> frame for these words against 7.8ms with the same alpha
> carried in the colour -- the single biggest cost here.


### `LyricsView._paint_line`

**line 6926** — before `p.setOpacity(0.82)`

> Nothing to activate or scroll to, so the depth model has no focus
> line and rendered every line as a distant blur at 10% opacity.
> Show them plainly and let the viewport gradient do the fading.

**line 6935** — before `if self.focus and live and self.browse < 0.5:`

> Focus mode: keep a fixed window around the active line and let the rest
> go, for a reading view with no periphery at all. Only while something is
> actually live -- with no anchor every line is "far" and the view blanks.
> ...but not while browsing, or scrolling out of the window shows nothing.

**line 6944** — before `blur = 0.0 if dist == 0 else min(9.0, 1.4 * dist**1.35)`

> Depth comes from blur + opacity, never scale (matches the web view).
> Ramps harder than a linear falloff so distant lines recede properly.

**line 6948** — before `falloff = max(0.10, 0.32 - 0.055 * max(0, dist - 1))`

> Base layer is the UNSUNG text, so it must stay dim even when the line is
> active -- the sung overlay is what brightens. Letting this reach 1.0 made
> the whole line read as already-sung.

**line 6954** — before `falloff += (0.60 - falloff) * self.browse if falloff < 0.60 else 0.0`

> browsing: bring distant lines up to something you can actually read

**line 6959** — before `alpha_free = alpha`

> fade toward the top/bottom of the viewport as well as by line distance
> (kept unfaded too: loose words are re-faded per word, where they land)

**line 6963** — before `y = y + (1.0 - act) * 7.0 * (1 if idx in live else 0)`

> lines rise into focus as they activate

**line 6967** — before `self._paint_dots(p, ln, fm, ox, y, pos, act,`

> not `alpha`: that is the deliberately dim UNSUNG text level, and
> dots have no sung overlay to brighten them back up

**line 6973** — before `lo = int(blur)`

> Blur levels have to be whole numbers to be cacheable, so a line coming
> into focus used to step 9-7-5-3-0 in visible jumps. Cross-fade the two
> neighbouring levels by the fractional part instead -- the same trick
> mip-mapping uses -- so the ramp is continuous.

**line 6979** — before `if self.clouds > 0:`

> Zero-g takes over the whole line: the base layer is one flat pixmap of
> the line as laid out, which cannot be pulled apart per word. Draw the
> words individually instead -- see _paint_loose for what that costs.

**line 6990** — before `spin = self.spin_frag(rows, fm, ox, y, self.ruby_h(rufm), pos)`

> Word spin: the base layer holds an upright copy of every word, so a
> word turning in the overlay would drag a motionless twin behind it.
> Cut that one word out of the base and redraw it, turning, below.

**line 7009** — before `p.save()`

> sung portion painted sharp on top of the dim base layer

**line 7021** — before `p.setFont(rufont)`

> a reading brightens with the kanji under it, so the two read
> as one thing rather than the kana lagging behind

**line 7042** — before `if self.glow_scale > 0 and singing and held > 0.02:`

> Halo belongs to the syllable being sung RIGHT NOW, not to
> everything already sung. It grows with how long the note is
> held AND with how much word there is to light up -- a drawn-out
> "gooooone" should bloom far harder than a clipped "at".

**line 7050** — on `                    radius = max(1, int(2 + 8 * strength))`

> quantised: it keys the cache

**line 7052** — before `swell = math.sin(math.pi * frac) ** 0.7`

> Animate rather than sit at one brightness: a swell that
> peaks mid-note, plus a shimmer keyed off the syllable's own
> start so neighbouring words never pulse in lockstep.

**line 7071** — before `gate = 1.0 if self.pop_min <= 0 else min(1.0, (e - s - self.pop_min) / 0.2)`

> Word pop: the syllable in the mouth right now lifts and swells,
> peaking mid-vowel. Anchored on the glyph's own centre so it
> grows in place instead of sliding along the line.
> Short syllables are the majority (median hold is under 0.3s), and
> popping every one of them reads as jitter -- gate on how long the
> note is actually held, easing in just above the threshold so two
> near-identical words do not behave completely differently.

**line 7086** — before `if spin is not None and (r_i, x) == (spin[0], spin[1]):`

> Troll: one full turn over exactly the life of the word, so it
> comes back upright at the moment the note ends.

**line 7093** — before `p.setPen(TEXT)`

> the unsung half of the word, cut out of the base layer
> above, turns with it instead of standing still

**line 7098** — before `if frac >= 1.0:`

> A hard clip at the fill boundary chops glyphs mid-stroke. Paint
> the text with a gradient pen instead: opaque behind the boundary,
> transparent past it, so the edge rides across the letterform.
> (It also drops the old left-clip hack -- nothing is masked now,
> so descenders keep their ink.)

**line 7117** — before `rfont = self.roman_font(ln)`

> the romanisation fills from the same timings, so it tracks the
> original word for word without any effects of its own


### `LyricsView._paint_credits`

**line 7160** — before `p.setPen(QColor(234, 234, 234, 120 if i == 0 else 88))`

> the writers lead and get a touch more presence than the provenance


### `LyricsView._paint_dots`

**line 7203** — on `        run = gap * 2`

> centre-to-centre span of the three

**line 7208** — before `cue = max(0.0, (t - 0.88) / 0.12) if t > 0.88 else 0.0`

> the last beat of the gap swells all three together, like a cue

**line 7211** — before `e = self.beat_energy()`

> An instrumental break is exactly where the beat should show, so pulse
> these on the real beat grid and fall back to breathing when there is
> no analysis for the track.


### `LyricsView._paint_help`

**line 7247** — before `keyw = max(fmk.horizontalAdvance(k) for k, _ in HELP_KEYS) + 20`

> size both columns off their own widest entry, or the descriptions of
> the long rows get clipped


### `LyricsView.browse_metrics`

**line 7280** — before `t_h = QFontMetricsF(self.ui_font(max(10, cw * 0.098))).height()`

> card height = art + title + subtitle, measured rather than guessed:
> a fixed 46px allowance was right at the small end and let the next
> shelf's header land on top of the subtitle at the large end


### `LyricsView._paint_browse`

**line 7291** — before `p.drawPixmap(0, 0, self.scene_layer())`

> The same living background as the lyrics view -- the drifting cover
> wash or mesh, already composited and cached at 15fps by scene_layer.
> Over it goes a scrim, because that wash was tuned to sit behind a
> dozen words rather than a grid of small text and thumbnails.

**line 7299** — before `p.save()`

> Content first, so the bar is painted over it and -- because hit-testing
> walks the list backwards -- also wins any overlapping click.


### `LyricsView._paint_browse_bar`

**line 7341** — before `label = "♪  Lyrics"`

> The way back. Accented and always drawn, whatever is underneath.

**line 7357** — before `frac = min(1.0, self.backfill_n / max(1, self.backfill_total))`

> thin progress hairline under the bar while names are being filled


### `LyricsView._shelf_label`

**line 7369** — before `title = (item.get("lines") or [""])[0][:40] or item.get("id", "")`

> no name yet -- show the opening lyric, which is at least a clue


### `LyricsView._paint_shelves`

**line 7395** — on `            if y + 40 > m["bar_h"] and y < H:`

> header


### `LyricsView._paint_card`

**line 7430** — before `p.setClipPath(path, Qt.ClipOperation.IntersectClip)`

> Intersect, never replace: the default replaces the viewport clip set
> by _paint_browse, which let card art paint up over the top bar.


### `LyricsView._paint_detail`

**line 7518** — before `is_album = d.get("kind") in ("album", "artist")`

> album and artist are the same page: a cover, a name, and a list of
> tracks under it. Only the song page differs.

**line 7575** — before `label = album.get("name") or self.clock.meta.get("album", "")`

> The album, as the way on rather than a label. Everything else on
> this page describes the song; this is the one line that leads off it.


### `LyricsView._paint_hit_row`

**line 7769** — before `box = QRectF(tx, r.y(), tw, r.height())`

> One line, artist trailing the title. Stacked, the artist sat in the
> gap between two rows and read as a caption for the NEXT track --
> which in a queue is exactly the wrong thing to imply.

**line 7782** — before `sw = min(fms.horizontalAdvance(sub), max(60.0, tw * 0.45))`

> the title gets first claim on the row; the artist is capped so
> a long credit list cannot squeeze the song name out


### `LyricsView.open_browse`

**line 7821** — before `self.editing = self.show_info = self.show_search = False`

> These three have no meaning over a browse screen; the menu and help do,
> so they are deliberately left alone.

**line 7832** — before `self.indexing = True`

> an index from before the browse view: it has the names but not the
> per-song facts the shelves group by, so refill it in the background

**line 7843** — before `songs = self.index.songs or []`

> names first, or every library shelf shows raw 22-character ids


### `LyricsView.build_home`

**line 7921** — before `seed = (self.discover.get("seed") or "").strip()`

> Suggestions, keyed off whoever is playing. Named after the artist so
> it is obvious WHY a shelf is being suggested rather than looking like
> an arbitrary pick.

**line 7941** — before `synced = [s for s in songs if s.get("synced")]`

> Library shelves, from the local index -- these need no network at all.


### `LyricsView.on_index`

**line 7973** — before `old = self.index.by_id`

> Carry the names across. A rebuild re-reads the lyric cache, which has
> no idea what anything is CALLED -- the titles were won one network
> round-trip at a time by the backfill, so replacing the list wholesale
> would silently throw all of that away.


### `LyricsView.activate_hit`

**line 8006** — before `for ln in self.lines:`

> already playing it -- seek to the line rather than restarting


### `LyricsView._paint_search`

**line 8025** — before `rows_shown = 10`

> Only ROWS rows fit, but the selection can run the length of the hit
> list, so slide the window to keep it on screen -- otherwise Enter
> plays something that was never drawn.


### `LyricsView.info_rows`

**line 8104** — before `writers = [str(w) for w in (doc.get("SongWriters") or []) if str(w).strip()]`

> Credits last and together: who wrote the song, then where this
> copy of it came from and who timed it. Songwriters lead because
> they are a fact about the song; the other two are facts about the
> file, and reading them first makes the song's own credit look
> like part of the provenance.

**line 8126** — before `have = [n for n, v in (("pitch", self.beat.pitch),`

> Named individually so a build that sends one and not the other says
> so, and the grain because it is the number that decides what any of
> this can be used for.

**line 8137** — before `bias, cal_n = self.calibration()`

> What the estimator read, and -- when it is not being applied -- which
> of the gates stopped it. An estimate that silently does nothing is
> indistinguishable from a broken one, and this is the only place the
> difference can be seen.

**line 8162** — before `rows.append(("Track id", tid or "—"))`

> Not per-song, but this is where somebody looks when the timing feels
> off, and it is the largest single correction in the stack.


### `LyricsView.share_card`

**line 8200** — before `live = SL.active_indices(self.lines, self.position() - self.track_offset())`

> Backing vocals are concurrent lines with their own timings, so more
> than one can be live at once. Taking only the first dropped whatever
> was being sung underneath -- keep every voice that is sounding.

**line 8237** — before `blocks = [(fl, fml, wrap_rows(fml, t, tw, 4), TEXT, 0.0) for t in lead]`

> smaller and dimmer, and parenthesised the way the watch view marks
> them -- on a still image there is no other cue that it is a backing part


### `LyricsView`

**line 8326** — before `def edit_span(self) -> tuple[int, int]:`

> A caret and a selection anchor, so the field behaves the way every other
> text box does. It used to only append and backspace: correcting the middle
> of a token meant deleting back to it, and there was no way to select at all.


### `LyricsView.edit_move`

**line 8346** — on `            self.edit_sel = self.edit_caret`

> start selecting from here

**line 8356** — before `lo, hi = self.edit_span()`

> collapse to the edge you moved toward, not to where the caret was


### `LyricsView.commit_edit`

**line 8371** — before `if self.font_name:`

> the one place a lookup may go to the network: the user has just
> typed a name and is waiting to be told whether it took

**line 8378** — before `self.layout_cache.clear()`

> every cached glyph run was measured in the old family

**line 8390** — before `self.genius_tried.clear()`

> a new token deserves a fresh go at whatever was skipped under the
> old one

**line 8403** — on `            fixes.pop(self.edit_for, None)`

> emptying it reverts to derived


### `LyricsView._paint_editor`

**line 8415** — before `rowh = max(20.0, fms.height() * 1.35)`

> Sized from the metrics rather than pinned at 210: the fonts scale with
> the window and the fixed rects did not, so on a large window the
> descenders of "paste your Genius API token" were cut off by the box.

**line 8447** — before `before = self.edit_text[:self.edit_caret]`

> The field scrolls to keep the caret in view, so the tail of a long
> token is reachable rather than merely elided away.


### `LyricsView.src_move`

**line 8543** — before `first, _count = MENU_SPANS[self.menu_section()]`

> follow the row that moved, so a held key keeps moving the same one


### `LyricsView._cache_size`

**line 8553** — before `n = sum(r["bytes"] for r in got.values()`

> What "clear all" would ACTUALLY free: it skips the kept ones,
> so counting them here would promise back more than it frees.


### `LyricsView.clear_cache`

**line 8580** — before `try:`

> The art and font caches are read through memories of their own; a
> cleared directory they still hold paths into draws nothing at all.


### `LyricsView.menu_get`

**line 8606** — on `            return None`

> an action has no value to read


### `LyricsView.menu_set`

**line 8621** — before `self._duet_rgb = (None if value in DUET_MODES`

> stepping the row past a hand-configured #rrggbb drops it; the
> named modes derive their colour and carry no literal of their own

**line 8626** — before `self.aligner.clear()`

> Switching it off means now, not from the next song: the job in
> hand is several GPU-minutes of exactly what was just refused, and
> what is queued behind it was only ever speculative.

**line 8633** — before `self.maybe_auto_genius()`

> turning it on should act on what is playing, not only on the next
> track to come along


### `LyricsView.menu_step`

**line 8649** — on `            return`

> nothing to step through; Enter opens the editor

**line 8651** — before `fn = getattr(self, key)`

> a row that DOES something rather than holds a value. `spec`
> names which one, where a single handler serves several rows.


### `LyricsView.menu_value`

**line 8682** — before `return "\u2022" * 10 if v else "not set"`

> shown blanked once set -- it is a credential, not a setting to read

**line 8685** — before `return str(v) if v else f"auto ({self.family})"`

> what is actually in use, not just what was asked for, so a name
> Qt could not find does not look as though it took


### `LyricsView._paint_menu`

**line 8706** — before `gap = 6.0`

> Sized before the box, because the strip can be the widest thing in the
> panel -- with only a few sections it never was, and the tabs hung out
> over both rounded edges as soon as more were added.

**line 8713** — before `tall = max(n for _, n in MENU_SPANS)`

> the box follows the tallest section, so switching tabs does not make
> the panel jump around under the cursor

**line 8717** — on `        if box.width() > W - 24:`

> narrow window: tighten the tabs

**line 8740** — before `self.tab_rects = []`

> -- section strip

**line 8754** — on `            if on:`

> underline the live one

**line 8784** — on `                at_lo = at_hi = True`

> chevrons do nothing; Enter edits

**line 8794** — on `            if kind == "num":`

> a hairline showing where in range we are


### `LyricsView.seek_line`

**line 8866** — before `j = idx.index(here[-1]) if here else -1`

> -1, not 0, during the intro: "the line before the first one". Sitting
> at 0 there meant the first press of Down went to 0 + 1 -- the SECOND
> line -- and the first line could not be reached from the intro at all.

**line 8870** — before `if step < 0 and here and pos - self.lines[here[-1]]["start"] > 2.0:`

> "previous" restarts the current line first, like a track-skip button

**line 8874** — on `            return`

> nothing sung yet, so nothing to go back to


### `LyricsView.on_motion`

**line 8942** — before `self.update()`

> No toast: the cover starting to move is its own announcement, and it
> arrives mid-song rather than on any action you took.


### `LyricsView.browse_key`

**line 8966** — before `if self.browse_tab == "search" and self.bq:`

> NEVER fall through: Esc quits the app in the lyrics view, and a
> browse screen that exits on Esc would be a trap.

**line 9001** — before `if ev.text() and ev.text().isprintable() and ev.text() != " ":`

> typing on the home tab jumps straight into a search, as it does
> everywhere else that has a search box

**line 9008** — before `self.transport_key(k, shift)`

> anything left over is transport, so music keeps working from here


### `LyricsView.browse_activate`

**line 9079** — before `self.fetcher.request_skip(uri, payload.get("uid") or "")`

> Skipping keeps the queue intact; playUri would replace the whole
> context with this one track and throw away everything after it.

**line 9084** — before `self.skip_at = time.monotonic()`

> Mandatory: poll() uses skip_at to tell a deliberate jump apart from
> Spotify's own gapless hand-off, and resyncs the clock if it guesses
> wrong.


### `LyricsView.refresh_browse_hits`

**line 9102** — before `"sub": (h.get("artist", "") if named`

> a name match shows the artist; a lyric match
> shows the line that matched, which is the point


### `LyricsView.on_catsearch`

**line 9121** — on `            return`

> a later keystroke already superseded it


### `LyricsView.on_backfill_progress`

**line 9144** — before `if done and done % 500 < 25:`

> a full rewrite is 5MB, so save periodically rather than per batch --
> but often enough that being killed mid-sweep does not throw it away


### `LyricsView.on_backfill`

**line 9150** — on `        if rows is None:`

> sweep finished


### `LyricsView.wheelEvent`

**line 9230** — on `            return`

> or the lyrics scroll away behind the overlay

**line 9232** — before `hit = self.menu_hit(ev.position())`

> scrolling over a row nudges that row, which is what people try first


### `LyricsView.mouseMoveEvent`

**line 9250** — before `self.vol_drag = max(`

> sent as it moves, not on release: volume is the one control where
> you are listening for the result rather than looking for it


### `LyricsView.mousePressEvent`

**line 9299** — before `btn = ev.button()`

> Right and middle never seek, never dismiss an overlay, never do any of
> what follows -- they are their own gestures, handled and finished with
> here so the left-button path below reads exactly as it always did.

**line 9328** — on `            return`

> a stray click must not throw away what was typed

**line 9340** — on `                self.show_menu = False`

> click outside the panel dismisses it

**line 9360** — before `kind, payload = self.hot_at(pos)`

> The title, opening the page about the song. Checked before the lyric
> hit test so the chrome wins where the two overlap.


### `LyricsView.middle_click`

**line 9397** — before `q = urllib.parse.quote(text.strip())`

> The line and nothing else. Adding the artist looked like it would
> narrow the search; Genius matches it against its own lyric text,
> so the name became just more words to find and pushed the actual
> line down the results.


### `LyricsView.right_click`

**line 9413** — before `menu = QMenu(self)`

> The one child widget in an otherwise fully custom-painted app. A menu
> has to sit above the window and survive the mouse leaving it, which is
> exactly what a painted overlay cannot do.


### `LyricsView.mouseReleaseEvent`

**line 9441** — before `self.vol_drag = None`

> already sent on every move; letting go just hands the reading back to
> the player, so an adjustment made anywhere else shows up again


### `LyricsView.mouseDoubleClickEvent`

**line 9449** — before `if ev.position().x() < self.panel_width():`

> only over the art panel -- double-clicking a lyric already means "seek"


### `LyricsView.keyPressEvent`

**line 9464** — before `if self.view == "detail" and not self.overlay():`

> Esc quits the app from the lyrics view, so like browse this must never
> fall through -- a page you cannot back out of is a trap.

**line 9495** — on `                    self.edit_replace("")`

> a selection goes whole

**line 9508** — before `self.edit_replace(ev.text())`

> typing over a selection replaces it, which is the whole point

**line 9530** — before `if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \`

> swallow everything: arrows drive the menu here, not the transport

**line 9539** — before `self.src_move(-1) if shift else self.menu_move(-1)`

> Shift carries the provider with you instead of stepping past
> it, which is how every other reorderable list behaves

**line 9559** — before `self.open_browse("search") if not shift else self.open_search()`

> `/` now lands on the browse Search tab, which searches Spotify's
> catalogue AND your cached lyrics; the old lyrics-only overlay is
> still there on Shift+/ for anyone who preferred it.

**line 9584** — before `self.nudge_offset(-0.01 if shift else -0.05)`

> Shift steps by 10ms. 50ms is a sensible stride for finding roughly
> where a song sits, and too coarse to stop on once you are there --
> the errors worth chasing are a tenth of a second, so the coarse
> step cannot land nearer than half of one.

**line 9592** — before `if shift:`

> [ and ] tune this track, so 0 clears this track. Shift+0 is the
> only way back to a clean global baseline without the menu.

**line 9600** — before `rest = self.track_offset()`

> Clearing the hand correction hands the track back to the
> measurement, which may well be non-zero -- say so rather than
> implying it has gone back to the raw timing.

**line 9674** — before `if self.clock.tid:`

> Deliberately here and not in reset_track, which also runs on
> every ordinary track change -- clearing there would leave the
> cache holding nothing it was built to hold. Asking again is
> the whole point of pressing this key, so the cached answer,
> and the duet flags derived from it, both go first.


### `LyricsView.set_on_top`

**line 9695** — before `ok = kwin_keep_above(self.windowTitle(), on)`

> Deliberately NOT touching the window flag here. It is ignored by
> the compositor, but setting it still forces Qt to destroy and
> recreate the surface -- asynchronously -- so the script below
> would mark the OLD window and the replacement would arrive
> without it. That was the whole bug: the D-Bus call succeeded and
> the setting still did not stick.

**line 9703** — on `            full = self.isFullScreen()`

> re-showing drops the fullscreen state


### `LyricsView.settings_dict`

**line 9738** — before `"sung_color": ("auto" if self._sung is None else`

> write back the name it was configured with, or a default
> instance reads as changed ("white" in, "#ffffff" out) and
> rewrites the file on every launch


### `LyricsView.autosave`

**line 9790** — before `if state == self._saved and CONFIG.exists():`

> Also write when the file has gone missing. Since the baseline is seeded
> from disk, an instance that changed nothing would otherwise never
> restore a settings file deleted underneath it -- everything would be
> silently lost at the next launch.


### `LyricsView.closeEvent`

**line 9800** — before `self.frame_timer.stop()`

> Stop painting FIRST. The crash seen at shutdown is on the main thread
> in QBackingStore::endPaint inside the Wayland plugin -- a repaint being
> flushed onto a surface that is going away. No timer, no repaint.

**line 9808** — before `self.aligner.stop = True`

> The alignment thread can be minutes from finishing and is a daemon,
> so it is not waited for -- but it must not emit into a widget that is
> going away, which is what disconnecting below is for.

**line 9826** — before `self.fetch_thread.join(timeout=0.6)   # one loop cycle is 0.4s`

> Then actually wait for it. Severing the signals alone still left the
> interpreter tearing down while the worker sat in a socket read, which
> segfaulted about one run in five.

**line 9829** — on `        self.fetch_thread.join(timeout=0.6)`

> one loop cycle is 0.4s


### `hide_own_console`

**line 9858** — on `            return`

> somebody else's console; leave it be

**line 9861** — on `            ctypes.windll.user32.ShowWindow(wnd, 0)`

> SW_HIDE


### module level

**line 9866** — before `EXC_REPEATS, EXC_SUMMARY = 3, 500`

> How many copies of one recurring fault to print in full before folding it into
> a count, and how often to report the count after that.


### `install_excepthook.hook`

**line 9889** — before `if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):`

> Ctrl+C and a deliberate exit are not faults to be survived


### `main`

**line 9914** — before `install_excepthook()`

> before anything else: until this is in place, any slip aborts the process

**line 10085** — before `al = ap.add_argument_group("local forced alignment (align_song.py)")`

> Read by align_song.py, which does the aligning; kept here so there is one
> place that says what this machine is willing to spend on it.

**line 10149** — before `for key in DEFAULTS:`

> every one of these defaults to None so an unspecified flag falls through to
> the saved value, and only then to the built-in default

**line 10161** — before `QTimer.singleShot(600, lambda: w.set_on_top(True))`

> deferred: on Wayland the compositor is asked by window caption, which
> does not exist until the window has actually been mapped

**line 10166** — before `def _bye(*_):`

> Ctrl+C from the terminal, or a SIGTERM from the session manager, used to
> kill the process outright and lose whatever had just been set.
>
> The handler must not touch Qt. Python delivers it at an arbitrary bytecode
> boundary, which can be *inside* paintEvent -- closing the window from there
> tears the surface down mid-paint and segfaults in QBackingStore::endPaint.
> Set a flag; tick() acts on it from a safe point in the event loop.

**line 10176** — before `if hasattr(signal, "SIGTERM") and os.name != "nt":`

> Windows has no SIGTERM worth speaking of; asking for it raises there
