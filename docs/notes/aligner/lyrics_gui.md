# `aligner/lyrics_gui.py`

Comments lifted out of `aligner/lyrics_gui.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

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


## `_sync_ckpt`

**line 386** — on `            continue`

> a mid-run copy, not a finished model

**line 387** — before `made_on_stems = any(k in path.name for k in ("-stem", "-pitch"))`

> syncnet-w2v.pt is the mixture one; -stem and -pitch were both trained
> on separated vocals.


## module level

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


## `palette_of`

**line 588** — before `if any(min(abs(h - o.hue()), 360 - abs(h - o.hue())) < 18 for o in out):`

> Neighbouring buckets of one gradient are near-identical, and four
> shades of the same brown make the mesh look like a single flat wash.

**line 592** — before `out.append(QColor.fromHsv(h, min(255, int(s * 1.35)), max(70, min(205, v))))`

> Keep real brightness spread: clamping everything into a narrow band
> (what the single accent colour needed) is what flattened the palette.

**line 595** — on `    if not out:`

> monochrome cover: fall back to its average


## module level

**line 685** — before `HAND_FIX_MAX = 3`

> Below this many corrected lines on one track, the entries were typed by hand;
> above it, they are a whole Genius alignment. Only matters once, for files
> written before the two were stored apart.


## `save_settings`

**line 800** — before `values = dict(values, offsets={k: v for k, v in offsets.items() if v})`

> keep only the tracks that actually needed correcting

**line 812** — before `if CONFIG.exists():`

> Keep one generation back. This file now holds hand-made work -- per
> track timing offsets and typed-out romaji corrections -- and it is
> rewritten whenever anything changes, so a single bad write or an
> outside deletion should not be the end of it.


## `kwin_keep_above`

**line 856** — before `_kwin_seq += 1`

> A name that is already loaded is refused, and this runs on every
> toggle, so make each one unique.

**line 859** — before `iface.loadScript(str(path), f"spicy-keepabove-{os.getpid()}-{_kwin_seq}",`

> loadScript is overloaded (s and ss); without an explicit signature
> python-dbus picks the one-argument form and the call fails outright


## `wrap_rows`

**line 894** — on `                cur = joined`

> no rows left; elided below


## module level

**line 908** — before `# --------------------------------------------------------------------------`

> talking to the player
>
> Two ways in, because the platforms do not agree on there being one. MPRIS is
> how a Linux desktop asks any player what it is doing; Windows has no such bus,
> but Spotify's own debug port is already open -- it is how the rest of this app
> reads the queue, the search and the artist list. Either one answers the same
> four questions, so Clock takes whichever is there and does not care which.


## `MprisTransport.read`

**line 967** — before `again = props.Get(MPRIS, "Metadata")`

> Metadata and Position are separate round-trips, so a track change
> can land between them and pair the new track's id with the old
> track's position. Re-read: if the id moved, so did everything else.


## module level

**line 1000** — before `JS_STATE = """(() => {`

> One eval per poll, so unlike MPRIS there is no window for a track change to
> land between two reads -- everything below is sampled from one page state.


## `SmtcTransport._mod`

**line 1110** — before `try:`

> winsdk and its successor winrt expose the same namespace


## `SmtcTransport.read`

**line 1153** — before `playing = int(getattr(pb.playback_status, "value", pb.playback_status)) == 4`

> 4 is PLAYING in the SMTC enum; anything else is not advancing

**line 1156** — on `                          else float(d) / 1e7)`

> timedelta or 100ns ticks

**line 1163** — on `            "volume": None,`

> not part of the protocol

**line 1167** — on `                "art": "",`

> a stream, not a url -- see docstring


## `SmtcTransport.seek`

**line 1176** — on `        if s is not None:`

> position is in 100-nanosecond ticks


## `make_transport`

**line 1258** — on `        return MprisTransport()`

> asked for explicitly; fail loudly


## module level

**line 1270** — before `# --------------------------------------------------------------------------`

> player clock -- poll rarely, interpolate in between so the fill is smooth


## `Clock.__init__`

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


## `Clock.poll`

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


## `Clock.position`

**line 1406** — before `length = self.meta.get("length", 0.0)`

> Nothing is subtracted here. Whatever the clock is holding back sits in
> the anchor already, so this stays a plain interpolation and the words
> always move at the rate the music does.


## `Clock.seek`

**line 1451** — on `        self._slew = 0.0`

> a deliberate jump must land, not glide


## `Clock.resync`

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


## module level

**line 1511** — before `# --------------------------------------------------------------------------`

> lyrics fetcher -- CDP blocks, so it lives on its own thread with its own socket


## `LyricIndex`

**line 1520** — before `V = 2`

> Bumped when a per-song field is added. An older file still LOADS -- the
> titles in it are hand-won and must not be thrown away -- but the missing
> facts are refilled from the cache in the background.


## `LyricIndex.__init__`

**line 1526** — on `        self.songs: list[dict] = []`

> {id, lines[], lang, title, artist}

**line 1527** — on `        self.stale = False`

> loaded, but from an older schema


## `LyricIndex.search`

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


## `Beat`

**line 1607** — before `JS = "Spicetify.getAudioData(%s).then(d => ({" \`

> Rounded in the page, not here: pitches are already 0..1 and timbre
> coefficients are meaningful to about a whole number, so full float
> precision is a couple of hundred KB of digits nobody reads. Timestamps
> are never rounded -- they are the whole point.


## `Beat.clear`

**line 1633** — before `self.pitch: list[list[float]] = []`

> 12 bins each, one row per segment: chroma and a timbre basis. Spotify's
> own spectral summary of the track, at whatever rate it cut segments.


## `Beat.load`

**line 1655** — before `for name in ("pitch", "timbre"):`

> Both are only ever read by segment index, so a batch that does not line
> up with the segments is not partially useful -- it is unusable. Older
> Spicetify builds send neither, which lands here as empty and is fine.

**line 1665** — before `self.beats = [`

> Bake each beat's strength from the loudness AT ITS ONSET. Sampling the
> envelope at playback position instead let a loud moment mid-beat drag
> the peak off the beat -- measured 330ms late, which defeats the point.


## `Beat.energy`

**line 1701** — before `span = (self.beats[i + 1][0] - start) if i + 1 < len(self.beats) else 0.5`

> decay across roughly one beat; faster songs get a tighter pulse


## module level

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


## `onsets_of`

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


## `estimate_offset`

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


## `calibrate`

**line 1953** — before `diffs = sorted(raw[t] - hand[t] for t in raw.keys() & hand.keys())`

> A correction of exactly zero counts, and is not the same thing as a track
> nobody has judged. It says the timing was already right, which pins the
> standing error at that track's raw reading exactly -- the most informative
> reference point there is. Ordinary use never stores one, because nudging
> back to zero drops the entry, but a config edited by hand can carry one
> and it would be perverse to throw away the clearest evidence in the file.


## module level

**line 1967** — before `JS_ARTISTS = """(() => {`

> Spotify's MPRIS metadata carries only ONE artist -- a track credited to three
> people comes over the bus as the first of them and nothing else. The page has
> the full list, so ask it. metadata["artist_name:N"] is the older shape and is
> still the only one populated on some builds, hence both.

**line 1998** — before `FEAT_SPLIT = re.compile(r"\s*(?:,|&|\bx\b|\band\b)\s*", re.I)`

> "A, B & C" and "A x B" are all the same list written differently


## `split_artists`

**line 2025** — before `how_of[n] = "with" if word.lower() == "with" else "feat"`

> "with" is a collaboration, "feat." is a guest -- the title
> said which, so there is no need to guess


## `split_artists.same`

**line 2034** — before `return bool(ka) and bool(kb) and (`

> containment, not equality: "hayleywilliamsofparamore" contains
> "hayleywilliams", which is the whole reason this is not a set lookup


## `split_artists`

**line 2044** — before `hit = next((n for n in named if same(a["name"], n)), None) if i else None`

> never the first name on the credit: a title that says "feat." is
> naming a guest, not renaming whose song it is

**line 2051** — before `if not any(same(n, a["name"]) for a in artists) and key(n) not in seen:`

> in the title but not on the credit list at all -- keep the title's
> wording, since it is the only wording there is


## module level

**line 2061** — before `FONT_UA = "Mozilla/4.0"`

> Google serves woff2 to anything that looks like a browser, and Qt does not
> read woff2. An old User-Agent gets plain TrueType, which it does read.

**line 2064** — before `FONT_REV = 2`

> Bumped when what gets downloaded changes shape. v1 came from the CSS endpoint
> and was a single weight-400 file with no axis in it, so a font cached then
> ignores every weight asked of it -- including the one it was cached for.


## `split_font`

**line 2096** — before `head, _, tail = spec.rpartition(" ")`

> trailing weight word, so "Outfit Black" reads the way it is written


## `_font_file.rank`

**line 2130** — before `ital = 1 if "italic" in n else 0`

> Italic sorts alphabetically before the upright file and carries
> the same wght axis, so without this "Montserrat" arrived slanted.


## module level

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


## `best_variant`

**line 2581** — before `for nxt in lines[i + 1:i + 4]:`

> the URL is the next line that is not itself a tag


## module level

**line 2604** — before `EDITION = re.compile(`

> The bits Apple hangs an edition off: "(Deluxe Edition)", "- EP", "- Single".
> They belong in the match -- a deluxe is not the plain record -- but not in the
> search term, which is where they do damage.

**line 2612** — before `AM_ALBUM = re.compile(r"music\.apple\.com/[a-z]{2}/album/[^/\"?]+/(\d+)")`

> Album links on music.apple.com's own search page, which is how records the
> Search API has not indexed are found at all.


## `_plain`

**line 2620** — on `    for _ in range(2):`

> "... (Deluxe Edition) [Explicit]"


## `_web_albums`

**line 2653** — on `        if len(ids) >= 12:`

> the page also lists songs, playlists, artists


## `motion_url`

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


## `MotionArt._memo`

**line 2782** — on `                self._known = {}`

> absent, or written by a crash


## `MotionArt._remember`

**line 2796** — on `            tmp.replace(MOTION_MEMO)`

> never a half-written file

**line 2798** — on `            pass`

> a cache that cannot be written is


## `MotionArt`

**line 2799** — before `def _decode(self, url: str, out: pathlib.Path) -> list:`

> slower, not broken


## `MotionArt._decode`

**line 2808** — before `"-q:v", "2",`

> default jpeg quality is visibly soft on a cover this size,
> and the frames are cached once and read many times

**line 2813** — before `flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0`

> Without this a console window blinks up on Windows every time an
> album is fetched, in front of whatever the user was doing.

**line 2821** — on `            return []`

> no ffmpeg here; still covers carry on


## `MotionArt._frames`

**line 2833** — on `                return []`

> asked lately; this record has no animation

**line 2834** — before `url = memo.get("url") or ""`

> A remembered URL is tried first and the search skipped entirely.
> If it has expired since -- Apple's asset URLs do -- the search
> still stands behind it, so a stale entry costs a decode, not a
> blank cover.

**line 2844** — before `imgs = []`

> QPixmap is GUI-thread-only; QImage is not, so the conversion waits


## `ArtCache._work`

**line 2929** — before `if max(img.width(), img.height()) > self.size:`

> scaled before it ever reaches the GUI: a 640px cover kept at full
> size for a 160px card is how you spend 100MB on thumbnails


## `Fetcher.__init__`

**line 2999** — before `self.done: str = ""`

> The last track a lookup ran to completion for, so the view can tell
> "this song has no lyrics" from "the answer is not back yet". Plain
> attribute on purpose: written here, read from the GUI thread, and one
> frame late is not worth a lock on every paint.


## `Fetcher.request`

**line 3018** — before `if meta:`

> title/artist/length, for the fallback providers that search by name


## `Fetcher.request_catsearch`

**line 3057** — before `with self._lock:`

> last-wins on purpose: this is called on every keystroke, and the run
> loop only picks it up every 0.4s, so typing throttles itself


## `Fetcher.run`

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


## `Fetcher._index_batch`

**line 3246** — on `        if not batch:`

> done, or the page went away

**line 3258** — before `items = doc.get("Content") or doc.get("Lines") or []`

> cheap per-song facts the browse shelves group by; captured
> here because re-reading 2000 cache entries later is not


## `Fetcher._catsearch`

**line 3349** — before `rank = {"Track": 0, "Album": 1, "Artist": 2}`

> JS_SEARCH already says what each hit is; heading them by that beats one
> "On Spotify" pile where a track, its album and its artist all look
> alike. Sorted by kind because Spotify returns them in relevance order,
> interleaved -- and the painter starts a new heading every time the
> section changes, so unsorted rows would repeat the same three headings
> all the way down.


## `Fetcher._load`

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


## `Fetcher._fallback`

**line 3540** — before `doc["_source"] = name`

> ride along in the document, so nothing else needs a new signal


## `retime_roman`

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


## `prepare`

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


## module level

**line 3750** — before `# --------------------------------------------------------------------------`

> live link -- the editor pushes what it is working on, and it appears here


## `LiveLink`

**line 3773** — before `clear = pyqtSignal()`

> No signal for the document itself: _handle calls the view directly, so
> the reply can say whether it could be drawn. See there.


## `LiveLink.__init__`

**line 3791** — before `app.aboutToQuit.connect(self.close)`

> Close the door before the interpreter goes: a listening socket
> whose event loop has been torn down aborts the process, which
> would turn a clean exit into a crash dialog.

**line 3796** — before `self.error = self.server.errorString()`

> Nearly always a second copy of the app already holding the port.
> Not fatal and not worth a dialog: everything else still works,
> and the editor will simply say it cannot reach a player.


## `LiveLink._watch`

**line 3834** — before `self._pulse.start(50)`

> 20 times a second, and only while an editor is connected: it is two
> float comparisons, and it is the difference between a tap landing
> where the song is and where it was before you dragged the scrubber.


## `LiveLink._handle`

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


## `Aligner`

**line 3983** — on `    finished_track = pyqtSignal(str, bool, str)`

> track id, worked, message


## `Aligner.__init__`

**line 3988** — on `        self._settings = view_settings`

> a callable, read per job

**line 3990** — on `        self._done: set = set()`

> tried this session, right or wrong

**line 3991** — on `        self.busy: str = ""`

> the track being worked on

**line 3993** — before `self._abort = False`

> Set to abandon the job in hand. Read by the worker between pieces of
> work, cleared as the next job starts -- see cancel().


## `Aligner.request`

**line 4005** — before `if not asked and tid in self._done:`

> A speculative job is offered once per session. The manual key is
> allowed to insist -- that is what pressing it means.


## `Aligner.run`

**line 4075** — on `            except Exception as exc:`

> a worker thread must not die

**line 4079** — before `if not stopped:`

> A job that was abandoned was not tried. Remembering it as
> tried would mean the track it was taken off never got
> another offer this session, which is the opposite of what
> interrupting it was for.


## `Aligner._sync_align`

**line 4104** — before `keep=not cfg.get("free"))`

> "Free models after aligning" off means keep it
> loaded: 4.0s of every song, for 1.11 GB.

**line 4108** — before `LA_err = f"the sync model: {type(exc).__name__}: {exc}"`

> Saying which model failed matters: the two fail for entirely
> different reasons and the message is all the user gets.


## `Aligner._align`

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


## `LyricsView.__init__`

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


## `LyricsView.retune_frames`

**line 4519** — on `        if hz <= 0:`

> some Wayland outputs report 0 before mapping


## `LyricsView.showEvent`

**line 4528** — before `super().showEvent(ev)`

> A window has no QScreen until the compositor has mapped it, so the
> value read in __init__ is a guess and this is the first honest one.


## `LyricsView.follow_screen`

**line 4550** — on `                    pass`

> already gone, e.g. the output was unplugged


## `LyricsView.load_cached_fonts`

**line 4584** — before `for stale in FONT_DIR.glob("*.ttf"):`

> nothing reads the older shapes again; leaving them costs a
> download's worth of disk and confuses the next person to look


## `LyricsView.resolve_font.pick`

**line 4611** — before `fold = {f.lower(): f for f in have}`

> case is the usual slip -- "segoe ui" for "Segoe UI"


## `LyricsView.resolve_font`

**line 4622** — before `self.family = min(fams, key=len)`

> A variable file registers its base family and a named
> instance beside it -- ["Outfit", "Outfit Thin"] -- and the
> instance is the one that ignores setWeight. Take the
> shortest name, which is the base every time.


## `LyricsView.lyric_font`

**line 4667** — on `        return self._weigh(f, self._weight(QFont.Weight.Black))`

> Outfit 900


## `LyricsView.ui_font`

**line 4671** — before `return self._weigh(f, self._weight(weight)`

> only the heaviest UI text follows a pin; labels stay readable


## `LyricsView.poll`

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


## `LyricsView.apply_romaji_fixes`

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


## `LyricsView.fetch_genius`

**line 4830** — before `if not self.ne_fix.get(self.clock.tid or ""):`

> Asked for at the same time, not as a rescue after Genius fails. Genius
> can come back having matched most of a song and left a handful of
> lines behind -- an alignment that scored under the threshold, or a
> line its page never had -- and those gaps are invisible from here.
> Having NetEase's answer already in hand means they simply fill.


## `LyricsView.on_genius`

**line 4844** — before `if not quiet:`

> NetEase was asked at the same time and may still answer, so this
> is not the end of the road for the track.


## `LyricsView`

**line 4904** — before `def dragEnterEvent(self, ev) -> None:            # noqa: N802 (Qt name)`

> A TTML dropped on the window is shown straight away, and only shown: it
> is never written to the cache, never saved as an alignment, and it lasts
> until the song changes. That is the point of it -- a file being worked on
> can be watched against the audio without being installed anywhere first.


## `LyricsView.show_dropped_lyric`

**line 4945** — before `if pathlib.Path(path).suffix.lower() in (".lrc", ".elrc"):`

> By what it is, not by hoping: parse_ttml on an LRC returns
> nothing at all and the drop would look broken rather than
> unsupported.

**line 4959** — before `self.dropped = self.clock.tid`

> Held against the fetcher, which answers every few seconds and would
> otherwise put the song's own lyric back over this within a breath.


## `LyricsView.show_live_lyric`

**line 4987** — before `self.toast(f"following {name}")`

> First push of a session. Say it once, so it is clear the words
> on screen are now coming from somewhere else.


## `LyricsView.show_dropped_art`

**line 5014** — before `self.on_art((img, blurred, palette_of(img)))`

> on_art rather than art_ready: this is already the GUI thread, and
> QPixmap may only be touched here.


## `LyricsView.reset_track`

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


## `LyricsView._load_art`

**line 5062** — before `blurred = img.scaled(`

> cheap gaussian: shrink hard, then upscale in doubling passes


## `LyricsView.nudge_offset`

**line 5100** — before `base = self.offsets.get(tid, self.auto_offset(tid))`

> Start from the total in force, measurement included, so the first
> press nudges what is on screen rather than jumping back to the raw
> timing and stepping from there.


## `LyricsView.measure_offset`

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


## `LyricsView`

**line 5180** — before `@property`

> The setting lives on the clock, which is the only thing that acts on it,
> but the menu reads and writes every row by attribute name on this object.


## `LyricsView.on_beat`

**line 5206** — before `self.measure_offset()`

> Whichever of the analysis and the lyrics arrives second is the one that
> completes the pair, so both call in and the first one is a no-op.


## `LyricsView.on_lyrics`

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


## `LyricsView.say_alignment_outranked`

**line 5294** — before `if str(SL.payload(self.body or {}).get("_timing") or "") == "align":`

> Ours would carry the aligner's own provenance -- see to_document.

**line 5298** — before `whose = self.source_name(SL.payload(self.body)) or "another source"`

> Name the source to get above, not just "up". The running order is not
> the ranking it looks like: for a song Spicy Lyrics has already
> word-synced, only the providers listed ABOVE Spicy Lyrics are asked
> at all (see fallback's `ahead`), so "Aligned here" in second place
> behaves exactly like "Aligned here" in last place. Being told to move
> it up, having already moved it up, is no help at all.


## `LyricsView.source_name`

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


## `LyricsView.made_by`

**line 5440** — before `makers = _people(meta.get("Maker")) or _people(doc.get("_maker"))`

> `_maker` is the same fact off a TTML source -- amll's GitHub login,
> LyricsPlus' curator -- which have an author but no uploader.


## `LyricsView.align_now`

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


## `LyricsView.align_ahead_scan`

**line 5546** — before `self.aligner.keep_only({tid for tid, _m in want})`

> What is queued has to match what is coming up, and this is the only
> place that knows both. Pruning first, and doing it whether or not a
> job is running: a queue that has been replaced while the worker was
> busy is exactly the case where the stale jobs would otherwise be
> waiting to run the moment it frees up.


## `LyricsView.on_aligned`

**line 5560** — before `if ok and tid == self.clock.tid:`

> The document on screen was chosen before this existed, so it has to be
> asked for again -- the aligner has already cleared the chain's memory
> of who won. Only for the song actually playing; anything else was
> queued ahead and will be picked up when it comes round.


## `LyricsView.maybe_auto_genius`

**line 5587** — before `if tid in self.genius_tried or self.genius_fix.get(tid):`

> a cached alignment from THIS matcher revision is good; an older one
> was dropped at load, so the track gets looked up again


## `LyricsView.sounding`

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


## `LyricsView.vfade`

**line 5641** — on `        f = max(0.0, 1.0 - t * t * (3 - 2 * t))`

> smoothstep out

**line 5642** — before `return f + (0.62 - f) * self.browse if f < 0.62 else f`

> this alone takes the bottom of the viewport to zero, so while browsing
> keep a floor or the lines you scrolled to are still not there


## `LyricsView.wrap_pieces`

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


## `LyricsView.layout_line`

**line 5792** — before `out = (rows, cfm, cfm.height() * (1.4 * len(rows) + 1.6),`

> a clear gap above, so the credits read as a footer rather than as
> one more verse nobody sang

**line 5802** — before `rrows, rfm = [], None`

> a romanisation set UNDER the original: smaller, same timings, and its
> height folded in here so scrolling and click extents stay honest


## `LyricsView.drift_of`

**line 5874** — before `if (y0 + h < 0 or y0 > self.height()`

> A word only comes loose once it is actually on screen. Seeding one
> from a line that is still below the fold would clamp it straight
> onto the window edge, leaving a row of words pinned to the bottom.

**line 5887** — on `        st[6] = (w, h)`

> drawn this frame, and how big


## `LyricsView.step_drift`

**line 5905** — on `                continue`

> not on screen this frame; leave it be

**line 5910** — before `if st[0] < 0.0 or st[0] > W - w:`

> Bounce off the window itself -- the word is loose in the whole
> frame now. Reflect and pin, so nothing can tunnel out and be gone.

**line 5918** — before `if len(self.drift) > 400:`

> A song's worth of words would accumulate as the lyrics scroll past, so
> anything that has not been drawn for a few seconds is let go. It gets
> a fresh launch if its line ever comes back.


## `LyricsView.tick`

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


## `LyricsView.line_pixmap`

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


## `LyricsView.glow_layer`

**line 6098** — before `spots = ((0.72, 0.30, 0.85, 100), (0.16, 0.86, 0.66, 58), (0.86, 0.80, 0.55, 44))`

> dimmer than the mesh: this only tints a cover that is already there

**line 6101** — before `a = self.palette[(i + self._section) % len(self.palette)]`

> each section of the song leads with a different palette colour


## `LyricsView.scene_layer`

**line 6130** — before `p.setOpacity(0.55)`

> already blurred to mush, so the default (fast) transform is fine


## `LyricsView._paint_mesh`

**line 6147** — on `            ph = i * 2.399`

> golden angle: never in step


## `LyricsView.paintEvent`

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


## `LyricsView._paint_lines`

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


## `LyricsView._paint_panel`

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


## `LyricsView._paint_volume`

**line 6456** — on `            return`

> not heard from the player yet


## `LyricsView._scroll_text`

**line 6496** — on `        if at < hold:`

> resting at the start

**line 6500** — on `        elif at < 2.0 * hold + travel:`

> resting at the far end

**line 6504** — on `        u = u * u * (3.0 - 2.0 * u)`

> ease in and out of both stops


## `LyricsView._paint_header`

**line 6526** — before `scrim = QLinearGradient(0, 0, 0, 96)`

> lyrics scroll up behind the header -- give it something to sit on

**line 6535** — before `thumb_pm = self.motion_frame() or self.art_full`

> The cover, small, beside the song rather than in a panel of its own.
> Sized to the two rows of text so the block reads as one object, and
> taken from art_full -- already in memory for this track, so there is
> nothing to fetch and nothing to cache.

**line 6581** — before `if self.show_volume:`

> Off to the right of the strip, clear of the title's scrolling box


## `LyricsView.spin_frag`

**line 6601** — before `box = QRectF(ox + x - 2, ry - fm.ascent() - ruh - 2,`

> generous, so antialiased edges and descenders go with it


## `LyricsView.cloud_pixmap`

**line 6622** — before `lobes = ((0.50, 0.50, 0.44), (0.24, 0.56, 0.34), (0.76, 0.56, 0.34),`

> A ring of overlapping lobes along the middle, so a wide stretch reads
> as a bank of cloud rather than one blown-up blob with a soft edge.


## `LyricsView.cloud_of`

**line 6653** — on `            far = max(W, H) * 1.15`

> comfortably outside, whatever the shape

**line 6658** — before `(((n >> 17) % 200) / 100.0 - 1.0),`

> where in the column this line likes to sit, so they do not
> all pile onto the same spot


## `LyricsView._paint_cloud`

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


## `LyricsView._paint_loose`

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


## `LyricsView._paint_line`

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


## `LyricsView._paint_credits`

**line 7160** — before `p.setPen(QColor(234, 234, 234, 120 if i == 0 else 88))`

> the writers lead and get a touch more presence than the provenance


## `LyricsView._paint_dots`

**line 7203** — on `        run = gap * 2`

> centre-to-centre span of the three

**line 7208** — before `cue = max(0.0, (t - 0.88) / 0.12) if t > 0.88 else 0.0`

> the last beat of the gap swells all three together, like a cue

**line 7211** — before `e = self.beat_energy()`

> An instrumental break is exactly where the beat should show, so pulse
> these on the real beat grid and fall back to breathing when there is
> no analysis for the track.


## `LyricsView._paint_help`

**line 7247** — before `keyw = max(fmk.horizontalAdvance(k) for k, _ in HELP_KEYS) + 20`

> size both columns off their own widest entry, or the descriptions of
> the long rows get clipped


## `LyricsView.browse_metrics`

**line 7280** — before `t_h = QFontMetricsF(self.ui_font(max(10, cw * 0.098))).height()`

> card height = art + title + subtitle, measured rather than guessed:
> a fixed 46px allowance was right at the small end and let the next
> shelf's header land on top of the subtitle at the large end


## `LyricsView._paint_browse`

**line 7291** — before `p.drawPixmap(0, 0, self.scene_layer())`

> The same living background as the lyrics view -- the drifting cover
> wash or mesh, already composited and cached at 15fps by scene_layer.
> Over it goes a scrim, because that wash was tuned to sit behind a
> dozen words rather than a grid of small text and thumbnails.

**line 7299** — before `p.save()`

> Content first, so the bar is painted over it and -- because hit-testing
> walks the list backwards -- also wins any overlapping click.


## `LyricsView._paint_browse_bar`

**line 7341** — before `label = "♪  Lyrics"`

> The way back. Accented and always drawn, whatever is underneath.

**line 7357** — before `frac = min(1.0, self.backfill_n / max(1, self.backfill_total))`

> thin progress hairline under the bar while names are being filled


## `LyricsView._shelf_label`

**line 7369** — before `title = (item.get("lines") or [""])[0][:40] or item.get("id", "")`

> no name yet -- show the opening lyric, which is at least a clue


## `LyricsView._paint_shelves`

**line 7395** — on `            if y + 40 > m["bar_h"] and y < H:`

> header


## `LyricsView._paint_card`

**line 7430** — before `p.setClipPath(path, Qt.ClipOperation.IntersectClip)`

> Intersect, never replace: the default replaces the viewport clip set
> by _paint_browse, which let card art paint up over the top bar.


## `LyricsView._paint_detail`

**line 7518** — before `is_album = d.get("kind") in ("album", "artist")`

> album and artist are the same page: a cover, a name, and a list of
> tracks under it. Only the song page differs.

**line 7575** — before `label = album.get("name") or self.clock.meta.get("album", "")`

> The album, as the way on rather than a label. Everything else on
> this page describes the song; this is the one line that leads off it.


## `LyricsView._paint_hit_row`

**line 7769** — before `box = QRectF(tx, r.y(), tw, r.height())`

> One line, artist trailing the title. Stacked, the artist sat in the
> gap between two rows and read as a caption for the NEXT track --
> which in a queue is exactly the wrong thing to imply.

**line 7782** — before `sw = min(fms.horizontalAdvance(sub), max(60.0, tw * 0.45))`

> the title gets first claim on the row; the artist is capped so
> a long credit list cannot squeeze the song name out


## `LyricsView.open_browse`

**line 7821** — before `self.editing = self.show_info = self.show_search = False`

> These three have no meaning over a browse screen; the menu and help do,
> so they are deliberately left alone.

**line 7832** — before `self.indexing = True`

> an index from before the browse view: it has the names but not the
> per-song facts the shelves group by, so refill it in the background

**line 7843** — before `songs = self.index.songs or []`

> names first, or every library shelf shows raw 22-character ids


## `LyricsView.build_home`

**line 7921** — before `seed = (self.discover.get("seed") or "").strip()`

> Suggestions, keyed off whoever is playing. Named after the artist so
> it is obvious WHY a shelf is being suggested rather than looking like
> an arbitrary pick.

**line 7941** — before `synced = [s for s in songs if s.get("synced")]`

> Library shelves, from the local index -- these need no network at all.


## `LyricsView.on_index`

**line 7973** — before `old = self.index.by_id`

> Carry the names across. A rebuild re-reads the lyric cache, which has
> no idea what anything is CALLED -- the titles were won one network
> round-trip at a time by the backfill, so replacing the list wholesale
> would silently throw all of that away.


## `LyricsView.activate_hit`

**line 8006** — before `for ln in self.lines:`

> already playing it -- seek to the line rather than restarting


## `LyricsView._paint_search`

**line 8025** — before `rows_shown = 10`

> Only ROWS rows fit, but the selection can run the length of the hit
> list, so slide the window to keep it on screen -- otherwise Enter
> plays something that was never drawn.


## `LyricsView.info_rows`

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


## `LyricsView.share_card`

**line 8200** — before `live = SL.active_indices(self.lines, self.position() - self.track_offset())`

> Backing vocals are concurrent lines with their own timings, so more
> than one can be live at once. Taking only the first dropped whatever
> was being sung underneath -- keep every voice that is sounding.

**line 8237** — before `blocks = [(fl, fml, wrap_rows(fml, t, tw, 4), TEXT, 0.0) for t in lead]`

> smaller and dimmer, and parenthesised the way the watch view marks
> them -- on a still image there is no other cue that it is a backing part


## `LyricsView`

**line 8326** — before `def edit_span(self) -> tuple[int, int]:`

> A caret and a selection anchor, so the field behaves the way every other
> text box does. It used to only append and backspace: correcting the middle
> of a token meant deleting back to it, and there was no way to select at all.


## `LyricsView.edit_move`

**line 8346** — on `            self.edit_sel = self.edit_caret`

> start selecting from here

**line 8356** — before `lo, hi = self.edit_span()`

> collapse to the edge you moved toward, not to where the caret was


## `LyricsView.commit_edit`

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


## `LyricsView._paint_editor`

**line 8415** — before `rowh = max(20.0, fms.height() * 1.35)`

> Sized from the metrics rather than pinned at 210: the fonts scale with
> the window and the fixed rects did not, so on a large window the
> descenders of "paste your Genius API token" were cut off by the box.

**line 8447** — before `before = self.edit_text[:self.edit_caret]`

> The field scrolls to keep the caret in view, so the tail of a long
> token is reachable rather than merely elided away.


## `LyricsView.src_move`

**line 8543** — before `first, _count = MENU_SPANS[self.menu_section()]`

> follow the row that moved, so a held key keeps moving the same one


## `LyricsView._cache_size`

**line 8553** — before `n = sum(r["bytes"] for r in got.values()`

> What "clear all" would ACTUALLY free: it skips the kept ones,
> so counting them here would promise back more than it frees.


## `LyricsView.clear_cache`

**line 8580** — before `try:`

> The art and font caches are read through memories of their own; a
> cleared directory they still hold paths into draws nothing at all.


## `LyricsView.menu_get`

**line 8606** — on `            return None`

> an action has no value to read


## `LyricsView.menu_set`

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


## `LyricsView.menu_step`

**line 8649** — on `            return`

> nothing to step through; Enter opens the editor

**line 8651** — before `fn = getattr(self, key)`

> a row that DOES something rather than holds a value. `spec`
> names which one, where a single handler serves several rows.


## `LyricsView.menu_value`

**line 8682** — before `return "\u2022" * 10 if v else "not set"`

> shown blanked once set -- it is a credential, not a setting to read

**line 8685** — before `return str(v) if v else f"auto ({self.family})"`

> what is actually in use, not just what was asked for, so a name
> Qt could not find does not look as though it took


## `LyricsView._paint_menu`

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


## `LyricsView.seek_line`

**line 8866** — before `j = idx.index(here[-1]) if here else -1`

> -1, not 0, during the intro: "the line before the first one". Sitting
> at 0 there meant the first press of Down went to 0 + 1 -- the SECOND
> line -- and the first line could not be reached from the intro at all.

**line 8870** — before `if step < 0 and here and pos - self.lines[here[-1]]["start"] > 2.0:`

> "previous" restarts the current line first, like a track-skip button

**line 8874** — on `            return`

> nothing sung yet, so nothing to go back to


## `LyricsView.on_motion`

**line 8942** — before `self.update()`

> No toast: the cover starting to move is its own announcement, and it
> arrives mid-song rather than on any action you took.


## `LyricsView.browse_key`

**line 8966** — before `if self.browse_tab == "search" and self.bq:`

> NEVER fall through: Esc quits the app in the lyrics view, and a
> browse screen that exits on Esc would be a trap.

**line 9001** — before `if ev.text() and ev.text().isprintable() and ev.text() != " ":`

> typing on the home tab jumps straight into a search, as it does
> everywhere else that has a search box

**line 9008** — before `self.transport_key(k, shift)`

> anything left over is transport, so music keeps working from here


## `LyricsView.browse_activate`

**line 9079** — before `self.fetcher.request_skip(uri, payload.get("uid") or "")`

> Skipping keeps the queue intact; playUri would replace the whole
> context with this one track and throw away everything after it.

**line 9084** — before `self.skip_at = time.monotonic()`

> Mandatory: poll() uses skip_at to tell a deliberate jump apart from
> Spotify's own gapless hand-off, and resyncs the clock if it guesses
> wrong.


## `LyricsView.refresh_browse_hits`

**line 9102** — before `"sub": (h.get("artist", "") if named`

> a name match shows the artist; a lyric match
> shows the line that matched, which is the point


## `LyricsView.on_catsearch`

**line 9121** — on `            return`

> a later keystroke already superseded it


## `LyricsView.on_backfill_progress`

**line 9144** — before `if done and done % 500 < 25:`

> a full rewrite is 5MB, so save periodically rather than per batch --
> but often enough that being killed mid-sweep does not throw it away


## `LyricsView.on_backfill`

**line 9150** — on `        if rows is None:`

> sweep finished


## `LyricsView.wheelEvent`

**line 9230** — on `            return`

> or the lyrics scroll away behind the overlay

**line 9232** — before `hit = self.menu_hit(ev.position())`

> scrolling over a row nudges that row, which is what people try first


## `LyricsView.mouseMoveEvent`

**line 9250** — before `self.vol_drag = max(`

> sent as it moves, not on release: volume is the one control where
> you are listening for the result rather than looking for it


## `LyricsView.mousePressEvent`

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


## `LyricsView.middle_click`

**line 9397** — before `q = urllib.parse.quote(text.strip())`

> The line and nothing else. Adding the artist looked like it would
> narrow the search; Genius matches it against its own lyric text,
> so the name became just more words to find and pushed the actual
> line down the results.


## `LyricsView.right_click`

**line 9413** — before `menu = QMenu(self)`

> The one child widget in an otherwise fully custom-painted app. A menu
> has to sit above the window and survive the mouse leaving it, which is
> exactly what a painted overlay cannot do.


## `LyricsView.mouseReleaseEvent`

**line 9441** — before `self.vol_drag = None`

> already sent on every move; letting go just hands the reading back to
> the player, so an adjustment made anywhere else shows up again


## `LyricsView.mouseDoubleClickEvent`

**line 9449** — before `if ev.position().x() < self.panel_width():`

> only over the art panel -- double-clicking a lyric already means "seek"


## `LyricsView.keyPressEvent`

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


## `LyricsView.set_on_top`

**line 9695** — before `ok = kwin_keep_above(self.windowTitle(), on)`

> Deliberately NOT touching the window flag here. It is ignored by
> the compositor, but setting it still forces Qt to destroy and
> recreate the surface -- asynchronously -- so the script below
> would mark the OLD window and the replacement would arrive
> without it. That was the whole bug: the D-Bus call succeeded and
> the setting still did not stick.

**line 9703** — on `            full = self.isFullScreen()`

> re-showing drops the fullscreen state


## `LyricsView.settings_dict`

**line 9738** — before `"sung_color": ("auto" if self._sung is None else`

> write back the name it was configured with, or a default
> instance reads as changed ("white" in, "#ffffff" out) and
> rewrites the file on every launch


## `LyricsView.autosave`

**line 9790** — before `if state == self._saved and CONFIG.exists():`

> Also write when the file has gone missing. Since the baseline is seeded
> from disk, an instance that changed nothing would otherwise never
> restore a settings file deleted underneath it -- everything would be
> silently lost at the next launch.


## `LyricsView.closeEvent`

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


## `hide_own_console`

**line 9858** — on `            return`

> somebody else's console; leave it be

**line 9861** — on `            ctypes.windll.user32.ShowWindow(wnd, 0)`

> SW_HIDE


## module level

**line 9866** — before `EXC_REPEATS, EXC_SUMMARY = 3, 500`

> How many copies of one recurring fault to print in full before folding it into
> a count, and how often to report the count after that.


## `install_excepthook.hook`

**line 9889** — before `if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):`

> Ctrl+C and a deliberate exit are not faults to be survived


## `main`

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
