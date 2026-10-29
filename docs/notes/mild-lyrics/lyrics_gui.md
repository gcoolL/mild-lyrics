# `mild-lyrics/lyrics_gui.py`

Comments lifted out of `mild-lyrics/lyrics_gui.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).

## 2026-10-29 — Font applies to: lyrics or everywhere

`font_where` (Text, under Font; default everywhere, the old behaviour).
`family` stays the Font setting's and draws the lyrics: `_lyric_face`, ruby,
romanisation, credits, the renderers' `face_font`. `ui_family` is what the
rest is drawn in (`ui_font`, `dr_font`, Home's `font`, the share card's
footer), and under "lyrics" that is the built-in stack's first installed
face, with no pinned weight (`ui_weight`).

## 2026-10-24 — Settings opens in its search; Esc closes at once

Goal: the search should already be focused when Settings opens, and Esc should close the drawer instead of first leaving the search. `show_menu` is now a property; going from closed to open empties `dr_query`, sets `dr_searching` and clears `dr_sel`, so every way in (M, the gear, the home page, H/I) gets it. Esc in `dr_key` closes in one press, clearing any query. Since the search has focus, every printable key types into it — M, H and ? no longer switch tabs or close from the Settings tab (Esc and the tab bar do); arrows, Enter, Tab and Ctrl+ keys behave as before. The results note says "Esc closes the settings.".

## 2026-10-22 — a hand-picked upload has its own offset

Bug: Superhero's music video (YouTube tab) and its streaming copy used the same per-song offset. Hand corrections were keyed `tid@origin` (song and sync), and both versions share the Spotify id. `LocalPlayer.reading()` now gives `meta["upload"]`: the YouTube id when the track was picked as that upload (YouTube tab, pasted link), "" when the resolver chose the release itself, which is the recording Spotify plays. `hand_key` appends `#<upload>`. For an upload, the old bare-tid fallback is skipped and nothing is measured or applied from `est_raw`: `auto_offset`, `heard_as_measured` and `measure_offset` all check `upload()`, because Spotify's analysis is of the album, not of a video's cut. Test: test_offset (4 more checks).

## 2026-10-22 — the lyrics search plays where songs play

Bug: with a song playing in Mild Lyrics, picking a song in the lyrics search started it in Spotify. A screenshot showed "Finding it on Spotify…" and then "not on Spotify: Trap Queen — Fetty Wap". `activate_hit` and `on_gmatch` always called `fetcher.request_play`, whatever Settings ▸ Home said. Now, when `homep().play_in()` is "mild", a hit plays in Mild Lyrics' player. A cached hit with a real Spotify id goes through `Home.play` with that uri, so the id is kept. A Genius hit, or one without an id, goes through `play_by_name`, so a local file wins. In Spotify mode, a song Spotify doesn't have now streams here instead of only saying so. Auto in `play_in` also picks Mild Lyrics while its player is active, whatever Main player says. The drawer's "auto · …" now shows `play_in()`'s own answer, not whether the debug port is up. The classic browse search (`browse_activate`), pasted Spotify links and plugin `open` still go straight to Spotify.

## 2026-10-19 — True black

A black cover could not reach 0 at any dim. Four things held the wall up: the (9,9,12) ink under the cover (drawn at 0.55 opacity, so 45% of the ink shows through), the (6,6,9) veil, the accent wash's `GLOW_FLOOR` (a pure-black cover has no palette and falls back to a grey, so the whole window was washed grey at a fifth), and the vignette and title scrim, which fade to (7,7,10). Raising the dim only darkened everything else along with it.

`true_black` (Background, off by default) makes the ink, veil, vignette and scrim pure black, drops the wash's floor, and in art mode masks the wash with `light_mask`: the blurred cover's luma at 64px, 0 on black and whole from `BLACK_KNEE` (0.15) up, drawn at the same `_art_src` crop so it drifts with the cover. Measured offscreen on the real window (fixture, pinned covers, dim 0.65): pure-black cover min 9 / median 11 → 86% of pixels at exactly 0, the rest text (GL canvas the same); half-black, half-red cover: black half 0, red side 72 → 67. A teal cover drops ~4-7/255, which is the ink no longer under it.

## 2026-10-16 — Memory

A real-use player showed 1138MB after 86 minutes, with no animated cover on screen. VmRSS equalled VmHWM: it had reached its peak and was holding it. About 940MB was malloc: a 300MB main heap plus seven full 64MB arenas belonging to worker threads.

**Freed but kept.** Animated covers are decoded on MotionArt's worker (up to ~97 frames, 190MB) and scaled on the GUI thread. `motion_frames = []` freed them, but glibc keeps freed chunks in its arenas: its dynamic mmap threshold rises after the first big free, so later frame-sized buffers land in the heaps. A script mimicking `_frames` + `_take_motion` over that session's seven covers went 128 → 447MB, sat at 360MB once all were dropped, and fell to 41MB after `malloc_trim(0)`. On the live player, `malloc_trim` through gdb took it from 1.1GB to about 600MB. The player now calls `trim_heap_soon()` (memory_mode.py) when the motion key changes and when a decode has been taken in: a `threading.Timer` calls `malloc_trim(0)` after TRIM_AFTER_S, debounced, Linux only. Each trim takes 2–17ms and keeps the script at one cover's worth (88–128MB). `mallopt(M_MMAP_THRESHOLD, 256K)` did the same, but it would mmap and fault every big temporary in a paint, so it was not used.

**What was live** (`sys.remote_exec` on a player 12 minutes old, 731MB): malloc 278MB, 148MB of it free. `spicy_lyrics._KKS` held 69MB in 883k objects: pykakasi unpickles its whole kanji table, ~100MB of RSS, on the first Japanese line, and keeps it. Now packed per first kanji (`_PackedKanwa`, spicy_lyrics.py): about 16MB, identical output on all 472 kanji lines in lyrics/fetched. Sudachi's system.dic is an 82MB file mapping, so the page cache can reclaim it. Pixels held by the view came to about 30MB.

**Floor.** A fresh player (headless KWin, NVIDIA GL canvas, real-use settings, an English song) settles at 353MB, of which ~170MB is shared libraries. On a Japanese song, 393MB fell to 313MB with the packed table.

**Later the same day.** MotionArt's worker held the last album's frames in its locals until the next album (fixed in `_job`), and the Memory use setting was added: see memory_mode.md.

## 2026-10-16 — the wall's drift in steps; MPRIS in one GetAll; Genius alignment out of process

**`scene_t`.** The moving walls (album art, mesh blobs, mesh wash) rebuilt 15 times a second (`scene_layer`), each rebuild repainting nearly the same picture. Measured on the real window offscreen at 1920x1020, with the largest per-pixel change between rebuilds a given drift time apart (one 15fps rebuild = 0.003 in `t` at motion 0.75):

    gap (rebuilds)   1     8     16    32    64    128
    art   max/255    2     3     3     4     6     10    (8 covers at x8: max 3, p99.9 <= 2)
    blobs max/255    2     2     2     3     5     8     (spread 1.5; at x8: 0.3 -> 8, 0.6 -> 5, 1.0 -> 3)
    wash  max/255    0     0     0     1     1     1

`t` is now held in steps of `SCENE_STEP` (art 0.024, blobs 0.024 x spread capped at 1.5, wash 0.192), sized so one rebuild changes no pixel by more than 3/255. The 1/15s cap stays as a ceiling for high motion. The step is not part of the key, so a step never starts a crossfade. Rebuilds a second: art 15 -> 2.3 (5.4ms each), blobs 15 -> 1.5, wash 15 -> 0.5. Their own wall (mesh, veil) was already still.

**MPRIS.** `_read_one` asks `GetAll` once: Metadata, Position, PlaybackStatus and Volume from one moment, so the second Metadata read is not needed. On their Spotify that is 0.15ms against 0.44 for the Gets, and 0.06ms of CPU against 0.15. A player whose GetAll fails or leaves a field out goes to `_no_getall` and is read a property at a time, as before.

**Genius alignment.** `GR.align` took 85ms median over 80 songs and 1.3s on the longest, all of it holding the GIL on the fetcher thread. `_genius_lookup` and `fit_pairs` send it through `offload.call`: identical on all 80, and the caller holds the GIL 0.1ms. The editor called it inside `got`, on its GUI thread; it runs in the job now.

## 2026-10-16 — the offset estimate off the GUI thread; the phone's mirror; offsets in ms

**`measure_offset` off the GUI thread.** Timed in the real window offscreen over 60 cached documents, each against a Spotify-sized analysis (about 4 segments a second): `on_lyrics` took a median of 15.6ms and 41.1ms at worst, 90% of it `estimate_offset` (`onsets_of` and `_est_curves`). It now takes its anchors on the GUI thread, at the same moment as before (the lines are mutated afterwards, so they cannot be read later), and runs `estimate_from` through `offload.call` on a thread. The result comes back as `measured`, dropped if `_est_gen` or the track has moved on. `on_lyrics` is now 1.2ms median, 3.4 worst. Results land 12–31ms later and are identical, field for field, on all 115 cached documents. `say_alignment_outranked`, the other suspect, no longer exists. `duet_flags` was 59ms of wall time, but it is network: about 8ms CPU, 16 at worst.

**KDE Connect's mirror of the phone.** It relays the phone's Spotify (a Connect remote for the same session) as an MPRIS player with the same song, "Playing", position 0 for good. On a pause, after HOLD, `_read_any` followed it to 0:00 until STILL_FOR dropped it. `_moving` now refuses a player that has only ever said exactly 0 and names the song the window is already on (`_same_song`, against `_here` and `_last`). A different song starting at 0 is still followed at once, and the mirror is followed once its clock moves. Test: `tests/test_phone_mirror.py`. It fails 3 of 5 on the old code.

**Offsets in milliseconds where they are.** 109 of their 245 track offsets are off the 10ms grid, taken from a measurement by `nudge_offset`'s "arrives at the measurement" rule. Shown at `+.2f`, a 10ms nudge read as nothing or as 20ms (-0.015 to -0.025 showed -0.01 to -0.03). `off_s` shows hundredths on the grid and milliseconds off it.

## 2026-10-15 — Genius romaji seams in the player (`retime_roman`)

The player places a Genius line by matching its letters against its own derived romaji, so the 2026-10-14 romaniser fixes (spicy_lyrics.md) reached it already. What was left was the editor's `_share` fault: letters only Genius has, between two syllables of one word, were forward-filled onto the syllable before -- Kid|zui, Hood|zue, waraig|oe. Now a vowel, the first of a doubled consonant, a "t" before "ch", or an ん closes the syllable before, and any other consonant opens the next (Ki|dzui, warai|goe). Over the 2101 lines of saved Genius romaji with a cached word sync: 14 change, all to the right seam (rendaku: oouna|bara, Iki|zama, kori|gori, majo|gari). Words pykakasi does not know (お人好し read onin|koushi) are now read again from Genius first (`SL.fit_readings`, spicy_lyrics.md 2026-10-15).

## 2026-10-13 — Genius ask lost to a skip

`maybe_auto_genius` marked a track as tried before `fetch_genius` found Genius still busy with the previous track and returned. NetEase was skipped too, since it is asked after that return. The previous track's answer was then dropped for the wrong tid, and the new track was never asked that session. This happened on HoneyWorks' 可愛くてごめん, skipped to 1.5s after the track before it. A busy Genius now leaves the track untried, and `on_genius` calls `maybe_auto_genius` again when a stale answer lands.

## 2026-10-13 — more Battery rows

All machine-specific (`BATTERY_KEYS`, in SHARE_SKIP), shown in the drawer only where there is a battery and Power saving is not off.

- **Save below** (`battery_below`, default 100): auto saves on battery only at or under this charge. `power.read()` now also returns the charge (sysfs `capacity` averaged over batteries, `BatteryLifePercent`, pmset's `NN%`; 100 where unknown). The battery saver still turns it on at any charge.
- **Unfocused frame cap** (`battery_unfocused`, default 20): while saving and the window is not the active one. Retuned on WindowActivate/Deactivate. Being covered is still invisible (see `showing`), but not being the active window can be seen.
- **While saving**, each costly extra has a Keep row, read through `kept(what)`: depth blur (`blur_now`, kept by default; pixmaps dropped when it flips), background motion (`motion_now`, so the scene freezes and stops rebuilding at 15fps), visualiser plus the art halo (`viz_live`/`halo_live`, fading out through `step_viz_mix`), animated cover (`motion_frame` returns None, the still cover shows, and it stops keeping the frame loop busy). **Fetch ahead while saving** (`battery_ahead`, default 1) caps `ahead_now()`.

Checked offscreen with `power.read` faked. Not run on a real laptop.

## 2026-10-12 — NetEase without a token, power, engine hold

**NetEase romanisation** is asked whether or not a Genius token is set (`ask_netease_roman`), and fitted by `GR.fit_pairs` on the fetcher thread. Its fixes are keyed "text#nth" like Genius's.

**Power saving** (laptops: the rows show only where `power.has_battery()`): auto saves on battery or with the system battery saver on. While saving, the frame cap is `battery_fps` (default 60) and the player is read every POWER_SAMPLE_MS (50) instead of SAMPLE_MS (16). Checked every power.TTL (15s). Not run on Windows or macOS here.

**ENGINE_HOLD_GAP.** A missed engine reading (the 400ms race timing out on a busy renderer) used to swap to the control clock, which sits an audio latency away, and back on the next good read. That is the shake after a seek. It is now carried on the engine clock for up to STALE_HOLD, while the control clock agrees within 1s.

**Measured 2026-10-12 (offscreen, real-use settings, 1.1.4+):** first paint 0.48s, 0.16–0.22s of it imports. GC pauses of 12–35ms happen only in the first 1.5s, so freezing or tuning GC buys nothing in playback. A debug-port read costs 0.11ms of Python CPU. Paint median 7.4ms, p95 10ms. GPU "auto" is CPU everywhere but Wayland (gpu_canvas.TESTED).

## Lift — 2026-10-25

Docstrings shortened in `mild-lyrics/lyrics_gui.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### `connect`

**line 154** — from the docstring, `def connect(port: int, match: str | None = None):`

> spotify_dom.connect, but as a function that fails rather than one that
> ends the process.
>
> It is written for a command line, where exiting with an explanation is the
> right answer to "Spotify is not listening". Here it is called from poll(),
> four times a second, on the GUI thread -- and SystemExit is a BaseException,
> so `except Exception` around the caller does not stop it. On Linux this
> never showed: MPRIS carries the clock and only the worker thread ever
> connected, where an exit merely ends that thread. Drive the clock over CDP,
> as Windows must, and the first poll takes the whole window down with it.

### `_step_floor`

**line 202** — from the docstring, `def _step_floor(got: dict) -> float:`

> How large a step has to be, on THIS player, to mean anything.
>
> RESUME_STEP_FLOOR is the floor for a player that answers continuously:
> below it, a forward step at a resume is the poll interval and the status
> arriving a moment late, not a clock that leapt.
>
> A player that answers in steps needs a bigger one. A browser publishes a
> position four times a second at best -- Firefox's own MPRIS once a second
> -- so the first reading after an unpause can be a whole update interval
> further on than the last one while nothing whatsoever has leapt. Measured
> on the bus: a 0.28s step, which is exactly plasma-browser-integration's
> refresh, was being read as a 0.244s leap and held against the words for
> the rest of the track.
>
> So the transport says what its player's resolution is (see
> SessionTransport._tick, which learns it by watching when the answer
> changes) and a step smaller than that is not evidence of anything. Zero
> or missing for a transport that does not know, which is every one that
> reads a clock rather than a series of answers.

### `_stated_push`

**line 226** — from the docstring, `def _stated_push(setting: float) -> float:`

> How far to move the words on top of whatever was measured.
>
> Only the negative half of `unpause_delay`, and only because that half
> cannot be measured at all.
>
> A player whose clock LEAPS forward on resume gives itself away: the
> position moves further than the wall clock did, and that difference is
> the whole correction. A player whose AUDIO leads its own reported clock
> does not: every reading it gives is self-consistent, the position simply
> starts from an origin a tenth of a second behind the sound. Nothing in a
> sequence of honest readings can reveal it, so it has to be told -- and a
> setting that is only ever a ceiling has no way to be told anything.
>
> So in measured mode a positive setting caps what is read, which is what
> it has always done, and a negative one is added to it. Both directions of
> the number now move the words in the direction somebody dialling it in
> expects, which the ceiling alone did not: dialled negative it did nothing
> whatever, because a ceiling has no sign.

### `_writable`

**line 300** — from the docstring, `def _writable(path: pathlib.Path) -> bool:`

> Whether a file can really be made in this directory.
>
> Asked by making one and taking it away again, because that is the only
> form of the question with a reliable answer. os.access reads the
> permission bits, and on Windows those are not what decides it -- an ACL,
> a read-only attribute, a folder redirected into OneDrive while it is
> signed out, or a directory like C:\Windows\System32 that looks readable
> to everyone and writable to nobody.

### `save_dir`

**line 316** — from the docstring, `def save_dir(want: str) -> tuple[pathlib.Path, bool]:`

> Where a file the user asked to keep actually goes, and whether that is
>     where they asked for it.
>
> --save-dir defaults to SAVE_HOME, which is lyrics/fetched beside
>     the program -- the same place on both platforms and whoever started it,
>     and kept apart from what the editor writes because they are not the same
>     kind of file; see saves.py.
>
>     It used to default to the folder the program lives in, and before that to
>     the working directory. That is the right answer when the program was
>     started from a terminal and no answer at all when it was not, and the two
>     platforms then disagreed for no reason anybody chose: running `python
>     mild-lyrics/lyrics_gui.py` from the checkout puts the files in the
>     checkout, and a Windows shortcut with no "Start in" set leaves the working
>     directory at C:\Windows\System32, where every save is "[Errno 13]
>     Permission denied" -- reported as a save that failed, on a machine where
>     nothing was wrong except that nobody had said where to put the file.
>
>     So a directory that cannot be written to is not an error here, it is a
>     question nobody answered, and the answer is the user's own Music folder.
>     The caller is told it moved so it can say so -- silently writing
>     somewhere else is its own kind of failure -- and --save-dir still means
>     exactly what it says wherever it can be honoured.
>

### `unreached`

**line 347** — from the docstring, `def unreached(bad) -> str:`

> The sources a walk could not reach, named the way the user ranked them.
>
> By catalogue rather than by provider, because that is what they ordered
> and what the failure actually costs them -- and deduped through the same
> map, since a source can be more than one door and either of them going
> down is one thing to say. One reason for the lot of them: an outage takes
> a host down, not a source, and the second line would say what the first
> one said.

### `_storage_rows`

**line 898** — from the docstring, `def _storage_rows() -> list:`

> Where saved TTMLs go, then one row per cache, plus the two that act on
> all of them.
>
> Built from caches.entries() rather than written out here, so a cache
> added later cannot end up with no way to clear it. The training caches
> are left out: they belong to whoever ran the training, are measured in
> tens of gigabytes, and the command line is the right place for them.

### `luma_of`

**line 989** — from the docstring, `def luma_of(img: QImage) -> float:`

> How bright the cover actually is, 0 to 1.
>
> Deliberately the plain average, black pixels and all. palette_of throws
> those away on purpose -- it is looking for the colours -- and that is
> exactly why it cannot answer this: a cover that is nine tenths black with
> a bright orange burst in it has a vivid orange palette and is a dark
> picture, and the accent wash needs to know the second thing.

### `palette_of`

**line 1017** — from the docstring, `def palette_of(img: QImage, want: int = 4) -> list[QColor]:`

> Dominant colours, coarse-histogram style.
>
> A single averaged pixel (what the accent glow used to be) turns any cover
> with more than one hue into the same brown-grey, so bucket by hue/sat/value
> instead and keep the biggest clusters. Near-black and near-grey pixels are
> dropped: they carry no colour and would swamp the histogram on dark art.

### `_dwm_backdrop`

**line 1114** — from the docstring, `def _dwm_backdrop(wid: int, kind: str) -> bool:`

> Put one of Windows 11's own materials behind our window. True if it took.
>
> This is what MicaForEveryone does to other people's windows from the
> outside, asked for from the inside instead: DwmSetWindowAttribute with
> DWMWA_SYSTEMBACKDROP_TYPE, documented from Windows 11 22H2 (build
> 22621) on. The compositor then draws the wallpaper, blurred and
> tinted, in every pixel we leave transparent -- so it is the difference
> between the clear background being a frosted pane and being a hole.
>
> Mica samples the desktop once and barely moves; acrylic blurs whatever is
> actually behind the window and follows it; tabbed is mica a shade darker.
> Dark mode is set alongside, because the material takes its tint from that
> and a light one under our white lyrics is unreadable.
>
> Anything older than 22621 refuses the attribute with E_INVALIDARG and gets
> plain transparency, which is still see-through -- MicaForEveryone can put
> a material behind us there through the undocumented accent API, and that
> is deliberately left to it rather than reimplemented here.

### `soft_scale`

**line 1313** — from the docstring, `def soft_scale(pm: QPixmap, factor: float, keep_half: bool = False) -> QPixmap:`

> Blur a pixmap by shrinking and regrowing it through a mip chain.
>
> Collapsing straight to 1/10th and stretching back in one step is a bilinear
> upscale of a tiny image, which reads as blocky pixels rather than blur.
> Halving and doubling repeatedly keeps every step near 2:1, where smooth
> scaling actually behaves, and lands on something genuinely soft.

### `advance`

**line 1332** — from the docstring, `def advance(fm: QFontMetricsF, txt: str) -> float:`

> fm.horizontalAdvance, remembered per face.
>
> Text measurement is the whole cost of a cold layout -- wrap_pieces says
> so where it takes care to ask only once per fragment, and measured over
> "NF - Time" it is 985 calls and about half the milliseconds of laying the
> document out from nothing.
>
> The memo hangs on the QFontMetricsF rather than on the window, and that is
> what makes it worth having. A cold layout is not a rare event: layout_cache
> is emptied by every resize and by every track change, and -- the case this
> is really for -- by a better source arriving mid-song, which is the same
> words with a better clock. The fragments are IDENTICAL across a re-time, so
> the second cold layout is asking the font exactly what it asked the first
> time. Hanging the memo off the face means it survives the cache being
> emptied, and dies by itself when the type changes, because a new face is a
> new object and _lyric_face is what keeps them.
>
> The ration is generous and the clear is blunt because the working set is
> one song's distinct fragments -- 219 on that document, and a long one runs
> to a few thousand.

### `_glues_back`

**line 1406** — from the docstring, `def _glues_back(word) -> bool:`

> Whether a word is drawn against the one before it, without the space.
>
> Only a word that is NOTHING but marks: a comma timed as a chip of its
> own ("no" "," "I") is a source that cut it off its word, and reads
> "no, I". A word that merely starts with one is still a word, and the
> space in front of it is the lyric's -- "dnomaid ,dnomaiD" sung backwards,
> "this .40" -- which gluing drew as "dnomaid,dnomaiD" and "this.40".
>
> Nor ? ! : ; -- French spaces those away from the word on purpose, and
> "Pourquoi ?" is how the line is written (the editor's model.TAIL_MARKS).

### `wrap_shape`

**line 1414** — from the docstring, `def wrap_shape(pieces, fm: QFontMetricsF, width: float, align: str):`

> Where the words go, with no clock in it.
>
> Rows of (x, advance, text, piece, chunk), plus the character lengths of
> every piece that had to be split -- which is everything wrap_pieces used
> to work out except WHEN each fragment is sung. Nothing here reads a time:
> the wrapping is decided by the text, the face and the width, and a split
> piece is cut on characters.
>
> Remembered on the QFontMetricsF for the same reason advance() is, and it
> is the same working set: one song's distinct lines at the widths it has
> been shown at. A better source arriving mid-song is the SAME words with a
> better clock, so it asks for shapes this has already worked out and pays
> only for stamping the new times onto them.

### `rtl_row`

**line 1499** — from the docstring, `def rtl_row(row, fm: QFontMetricsF, width: float, align: str) -> list:`

> A row laid out left to right, turned round for a right-to-left line.
>
> The words run from the right edge, and a word sung in syllables has its
> syllables run from the right too. Three things come with that:
>
>   * The space after a word moves in front of its text, " word" rather
>     than "word ", so that drawn from its left edge the space sits on the
>     left, which is where the next word is. The last fragment of a word is
>     still the one carrying the space, so words_of still finds the words.
>   * Syllables of an Arabic word that are written joined get a ZWJ on each
>     side of the join, so each one drawn alone keeps its connected forms.
>   * A run of left-to-right words inside the line -- "la vie" in an Arabic
>     line of C'est la vie -- keeps its own order, as the bidi algorithm
>     would lay it out.
>
> Alignment is mirrored with it: "left" is the start of the line, which for
> these is the right edge.

### `load_romaji`

**line 1613** — from the docstring, `def load_romaji() -> dict:`

> Per-track romaji corrections, keyed by the original line text so a
> repeated line is fixed everywhere it appears.
>
> Genius alignments used to land in here too, which made them permanent: a
> track fixed up by an early version of the matcher kept that version's
> mistakes forever. They live in their own store now, so anything here that
> is plainly a whole-song alignment is dropped and re-fetched rather than
> treated as your own work.

### `load_genius`

**line 1621** — from the docstring, `def load_genius() -> tuple[dict, dict]:`

> Cached Genius alignments, and the matcher revision each was made with.
>
> Kept apart from the hand-typed corrections above because these are derived
> and therefore disposable: when the matcher improves, anything from an older
> revision is dropped so the next play re-fetches it. Everything the older
> code got wrong stayed on screen otherwise, since a track that already had
> an entry was never looked up again.

### `load_offsets`

**line 1646** — from the docstring, `def load_offsets() -> dict:`

> Per-track corrections, undoing a rebase a previous version applied.
>
> That version measured how far the player's clock ran ahead of its own audio
> and subtracted it centrally. Corrections made by ear already contained that
> lead, so it took the same amount back off each stored one to stop them being
> counted twice, and wrote the figure to `lag`.
>
> Nothing subtracts it centrally any more, so those corrections are short by
> exactly that much and adding it back restores them. This applies to every
> entry, including any tuned while the rebase was in force -- those were
> settled against a clock already holding the lead back, so they need the same
> correction to mean the same thing now.
>
> One-shot: `lag` is no longer written, so the next save drops it and this
> stops firing. Re-running it before that save is harmless, because it reads
> the stored figures fresh each time rather than compounding.

### `_sinks`

**line 1670** — from the docstring, `def _sinks() -> None:`

> Index -> (id, name) for every output there is.
>
> Read only when an index turns up that is not in it. Sinks are made and
> destroyed when a device is plugged in or a profile switched, not while
> something is playing through one, so this is a handful of calls a day
> rather than one every DEVICE_POLL.

### `audio_sink`

**line 1685** — from the docstring, `def audio_sink(app: str = DEVICE_APP) -> tuple[str, str]:`

> Where the song's sound is actually coming out: (id, name to show).
>
> `app` is whoever is playing it, which is not always Spotify -- see
> SessionTransport.app and the any-media-player setting. The delay being
> corrected belongs to the output, so following the wrong application's
> stream means reading the wrong output's offset.
>
> The PLAYER's own stream, not the desktop's default output. Moving one
> application to another device is a thing people do, and the delay this is
> asked for belongs to the device the song comes out of rather than to
> whatever would play a notification beep. The default sink stands in while
> nothing is playing, so the window still knows where it is between tracks.
>
> ("", "") where there is nothing to ask -- no pactl, no PipeWire or
> PulseAudio, no answer from the platform. Everything then shares one
> offset, which is what it did before there was more than one.
>
> THE OTHER TWO PLATFORMS ANSWER A SLIGHTLY SMALLER QUESTION, because they
> have a smaller one to answer: both name the default output rather than the
> player's own stream. On macOS that is the same question -- there is no way
> for a person to send one application to a different speaker, so the
> default IS where the sound comes out. On Windows there is such a way (App
> volume and device preferences), and finding what it did for one process
> means a COM interface per audio session; the default device is what is
> read instead, which is right for everybody who has not gone into that
> page. Both are worth having: the offset this exists for is a bluetooth
> headset against a monitor's speakers, and that is a change of default.

### `winrt_projection`

**line 1738** — from the docstring, `def winrt_projection() -> str:`

> "winsdk", "winrt", or "" -- whichever answers for every namespace.
>
> Both projections are the same API under two names, so the only question
> is which one is installed, and the answer has to be the same at every
> call site or half the transport comes from one and half from the other.
>
> All of them or none of them, deliberately. Asking for the one module we
> import by name is what let a half install past the probe; asking for the
> set means a machine missing a namespace reports no transport at all and
> the window quietly uses the debug port instead, which works.
>
> Cached because the miss is the expensive case -- a failed import re-walks
> the path every time -- and because installing a package under a running
> window does not make it importable there anyway.

### `_win_reg_name`

**line 1845** — from the docstring, `def _win_reg_name(dev: str) -> str:`

> An output's friendly name, read off the registry rather than asked for.
>
> Second way round for when the device-information lookup will not answer --
> it is a packaged call and it is the first thing to go when the
> Devices.Enumeration half of the projection is missing, while the registry
> is there on every Windows and costs nothing.
>
> The interface path carries the endpoint's own guid in it, which is what
> the MMDevices key is named by, so the two need no lookup between them.

### `_win_short`

**line 1869** — from the docstring, `def _win_short(dev: str) -> str:`

> A label for an output that will not give a name, short enough to read.
>
> Last resort, and the point of it is what it is NOT: the interface path is
> ninety characters of guid and it is the id, not a name -- putting it in a
> toast or in the song panel says nothing except that something went wrong
> upstream of the label. The endpoint's first block is stable, is different
> for two identical headsets, and fits.

### `_windows_output`

**line 1884** — from the docstring, `def _windows_output() -> tuple[str, str]:`

> Windows' current output device: (a stable id, a name to show).
>
> The id is the device interface path, which is what Windows itself keys a
> device by -- it survives a rename and it is different for two identical
> headsets, which a friendly name is not. It is also not a name: nothing
> shown to the user is ever the path, which is what the two fallbacks below
> the lookup are for.
>
> Cached for a few seconds because the name costs a device-information
> lookup and this is asked on a timer. The id alone is a cheap call, so the
> cache is checked against it rather than against the clock: plug something
> in and the change is picked up on the next poll, not the next minute.

### `load_est`

**line 1915** — from the docstring, `def load_est() -> dict:`

> Measured timing offsets, dropped when the estimator that made them moves on.
>
> Same bargain as the Genius alignments above and for the same reason: these
> are derived, so a track measured once by an older revision would otherwise
> keep that revision's answer forever and never be looked at again. Anything
> stamped with a different revision is discarded and re-measured on the next
> play. The hand corrections in `offsets` are never touched by this -- those
> are the user's own work and outrank anything computed here.

### `_fps_cap`

**line 1948** — from the docstring, `def _fps_cap(got: dict) -> dict:`

> A settings file written before the frame rate cap was a setting.
>
> Its 0 was not a choice: it is what the cap defaulted to, and it was written
> out to every file, so carrying it over would keep the new default from
> reaching anybody who already has one. Without the `fps_cap_set` mark, 0
> means "never picked" and becomes FPS_CAP_DEFAULT; anything else somebody
> typed, like 144, is theirs and stays. The mark is written by settings_dict,
> so from the first save on a 0 is what it says.

### `_merge_ms`

**line 1963** — from the docstring, `def _merge_ms(got: dict) -> dict:`

> A settings file that still measures the merge as a fraction.
>
> The tolerance is now a flat number of milliseconds rather than a fraction
> of the word (see _join_flat for why). Both are small numbers and a stored
> 0.14 reads perfectly well as either, so the key was renamed and this is
> what carries the old one over -- once, on the first load, after which the
> old key is dropped by load_settings like any other.
>
> The number cannot survive, only the intent: somebody who had it on gets it
> on at MERGE_WAS_ON, and somebody who had it off gets it off. Anyone who had
> tuned the fraction will want to look at the slider again, which is the
> honest outcome -- it is now measuring a different thing.

### `_upgrade_sources`

**line 1974** — from the docstring, `def _upgrade_sources(got: dict) -> dict:`

> A settings file written when the list was one of providers.
>
> It named things this program no longer has -- "youly", "bini" and the four
> blends -- and there is no honest way to read that order as an order of
> sources: it ranked Apple Music in six places at once, in a list where it
> now has one. So the switches are carried across, on if anything that
> spoke for the source was on, and the ORDER is taken fresh from the
> default. It is the one setting that cannot survive the change, and it is
> a dozen keystrokes to put back.
>
> What is deliberately NOT carried across is `src_blend` and its three
> fellows onto the new `blend_*` switches, though that looks like the
> obvious thing to do. Those defaulted to false and were written out to
> every settings file whether or not anybody had thought about them, so
> inheriting them would ship a version that brings the blends back and then
> switches them off again for everyone who ever ran the old one. The new
> keys ask a different question -- "do you want this blend at all", where
> the old ones asked "where does it rank" -- so they start from their own
> default. The old keys are dropped on the next save, by load_settings.

### `kwin_keep_above`

**line 2025** — from the docstring, `def kwin_keep_above(title: str, on: bool) -> bool:`

> Ask KWin to keep our window above the rest. True if it took.
>
> Wayland deliberately refuses to let a client set its own stacking, so
> Qt::WindowStaysOnTopHint is silently ignored there -- the window flag is
> set, nothing happens, and the app used to report success anyway. The
> compositor will do it if asked directly, and on KWin that means loading a
> one-shot script over D-Bus. Nothing here is fatal: if any of it is missing
> we say so and the caller tells the truth instead.

### `x11_composited`

**line 2054** — from the docstring, `def x11_composited() -> bool:`

> Whether anything on this X display is blending windows together.
>
> Asked afresh every time rather than cached: a compositor can be started
> and stopped under a running window, and a stale yes is the one answer
> that matters, since it is what the warning is for.
>
> Without a compositing manager an ARGB window is not see-through, it is
> undefined: X hands the toolkit a visual with an alpha channel and then
> nobody reads it, so the clear background comes out as whatever was in
> that memory. The manager announces itself by owning the _NET_WM_CM_S0
> selection, which is two calls into libX11 and the only honest way to ask.
>
> Wayland never needs this -- every surface there is composited -- and a
> display we cannot open at all is answered False, so the caller warns
> instead of promising.

### `wrap_parts`

**line 2109** — from the docstring, `def wrap_parts(fm: QFontMetricsF, parts, sep: str, width: float,`

> Wrap a line that is a row of parts, keeping the parts apart.
>
> wrap_rows would do this if the parts were words, but they are not: the
> wide gaps between them are what groups the words INSIDE them, and a
> greedy wrap over `text.split()` hands every one of those gaps back as a
> single space. So the parts are wrapped rather than the words, and the
> last row is left over-long rather than elided -- a key spelled "Esc ba…"
> is worse than one drawn past the edge.

### `looks_like_a_song`

**line 2226** — from the docstring, `def looks_like_a_song(meta: dict, who: str = "", longest: float = SONG_MAX,`

> Whether this reading is a song rather than something being watched.
>
> See the lists above for what the guess is made of and what it cannot see.
> `who` is the player's name, `longest` the ceiling in MINUTES -- the
> setting's own unit, so the number in the menu is the number compared.
>
> `kind` is the one field the bus does not have and the other two services
> do: Windows and macOS both carry what the player called this session,
> music or video. It is read ONE WAY ONLY. "music" is taken as a yes,
> because a player that bothered to say so is describing a song and it is
> the only positive signal here that is a statement rather than a shape.
> "video" is ignored, and that is deliberate: a browser sets it from the
> element the page is playing, and YouTube plays its music through a <video>
> like everything else -- so believing a no there would refuse the exact
> case this whole setting exists for. What decides those is the lookup (see
> SessionTransport._worth), which asks whether a music catalogue has the
> record or a provider has the words.

### `_version_only`

**line 2277** — from the docstring, `def _version_only(text: str) -> bool:`

> Whether the far side of a dash names a version rather than a song.
>
> A year on its own does not count, or The Smashing Pumpkins' "1979" is a
> remaster of something by a band called The Smashing Pumpkins. It only
> counts alongside a word -- "2011 Remaster" -- which is why the test is
> for a letter and not for a match.

### `song_from_video`

**line 2294** — from the docstring, `def song_from_video(title: str, artist: str) -> tuple[str, str]:`

> The song's name and its artist, out of what a video was called.
>
> Returns the pair unchanged where there is nothing to do, which is every
> player that files its music properly and most of the ones that do not.
>
> Remembered, because a player that is not Spotify is asked about the same
> two strings twice on every one of sixty readings a second.

### `song_key`

**line 2345** — from the docstring, `def song_key(title: str, artist: str) -> str:`

> An id for a player that has no Spotify track id to give.
>
> Twenty-two characters, like Spotify's, so everything downstream that only
> wants "some id for this song" is satisfied -- and hex rather than base62,
> so nothing takes it for a real one. Made from what is on the card, which
> is all the name-searching providers ever needed.

### `_titles_of`

**line 2384** — from the docstring, `def _titles_of(title: str, artists: set) -> set:`

> The names a player's title could be giving the song as.
>
> A browser playing a video hands over the VIDEO's title, which is the
> song's with the artist in front: "slayr - Eyesight (Official
> Visualizer)" names Eyesight, and compared whole it matched nothing on
> Spotify -- so Spicy Lyrics was never asked about a song it had.

### `_spotify_match`

**line 2396** — from the docstring, `def _spotify_match(rows: list, meta: dict) -> str | None:`

> The one Spotify track among search rows that is this song, or None.
>
> It has to agree on the name, share an artist, and -- where both sides
> know it -- run within four seconds of the same length. A row found by
> the recording's ISRC needs only the length: the code already says which
> recording it is, whatever either side calls it. Of those that pass, the
> ISRC rows win, then the artist's own album over a compilation carrying the
> same recording, then the closest length, so exactly one id comes back
> and Spicy Lyrics is asked about that one only.

### `NothingPlaying`

**line 2552** — from the docstring, `class NothingPlaying(RuntimeError):`

> No player here has a song to hand over.
>
> Not a fault, and the difference matters to whoever is holding two ways in
> at once. BackupTransport reads an exception as "that side is down" and
> stands off it for RETRY seconds; this says "that side is fine and has
> nothing for you", which is what a paused desktop -- or a track still
> waiting to be vouched for -- looks like from the outside. Standing off a
> working bus for five seconds because a video was playing on it is how a
> song that HAS been cleared waits three and a half seconds for the screen.

### `SessionTransport`

**line 2557** — from the docstring, `class SessionTransport:`

> Whoever is playing, off a service that knows about every player.
>
> Three platforms have one of these and they are the same thing three ways:
> the session bus on Linux, the system media transport on Windows, the
> now-playing service on macOS. Each hands over a list of sessions, each
> session answers what it is playing and where it has got to, and the
> problems that come with reading them are not the platform's -- they are
> the same six problems every time.
>
> What is here is those six, and nothing about any particular service:
>
>   * WHICH SESSION TO FOLLOW. Whoever is playing wins, the music player
>     first among equals. One is followed until it stops, so pausing does
>     not hand the window to a tab with a video paused in it, and the
>     others are only looked at while what is being followed has stopped.
>   * WHAT IS A SONG. None of these services says whether the thing playing
>     is a song or a film -- see looks_like_a_song for the guess, and
>     `vetting` for the window's better answer.
>   * WHAT THE SONG IS CALLED, which off a browser is the name of a video
>     rather than the name of a song. See song_from_video.
>   * A CLOCK THAT STEPS. A browser publishes a position rounded to the
>     second on every one of these services, and taken at face value that
>     is a clock which stalls and jumps. See _tick.
>   * A CLOCK THAT DOES NOT MOVE AT ALL, which is the one failure that
>     looks like success. See _moving.
>   * WHAT THE PLAYER LEFT OUT, filled in from a catalogue. See dress.
>
> A subclass supplies the service: HOME, the player never second-guessed;
> `_sessions`, who is there; `_read_one`, one reading off one of them;
> `_app_of`, what to call it; `_forget`, drop whatever was cached for it;
> and `_rank`, which of two sessions saying the same thing to believe.

### `SessionTransport._read_any`

**line 2667** — from the docstring, `def _read_any(self, want_volume: bool) -> dict:`

> The same reading, off whichever player is worth following.
>
> The one being followed is asked first and every time: while it is
> playing a song there is no question to answer and nobody else is
> disturbed. Only when it has stopped, gone, or turned out to be
> playing a video is anybody else asked -- and at LOOK_EVERY, not at the
> sampler's rate.

### `SessionTransport._home`

**line 2706** — from the docstring, `def _home(self, want_volume: bool, got: dict | None, now: float):`

> Spotify again, once whatever else was followed has stopped.
>
> A browser that has been paused for HOME_AFTER, or closed, is not
> worth the window: with nothing playing anywhere, the window is
> Spotify's, paused where it was. It used to stay on the last player
> that had played for good -- a paused video tab owned the screen
> until something else started.
>
> Only on a round that looked round everybody and found nobody
> playing, so this is asked at LOOK_EVERY rather than at the sampler's
> rate, and only where Spotify is actually there to answer.

### `SessionTransport._worth`

**line 2719** — from the docstring, `def _worth(self, got: dict) -> bool:`

> Whether this reading is one to hand over. Two questions.
>
> Is it a song at all -- looks_like_a_song, and only for a player that
> is not the music player; what plays THERE was picked in a music
> player and is not second-guessed here.
>
> And, where somebody is vetting, has this track been cleared yet. One
> that has not is remembered in `pending` instead of being returned, so
> the window can go and look it up -- in a music catalogue, and at the
> providers -- and until it says yes the reading is not handed over, so
> a video never reaches the screen at all.

### `SessionTransport._tick`

**line 2739** — from the docstring, `def _tick(self, who, tid, pos: float, at: float, status: str) -> float:`

> Where the song is, from a player that only says now and then.
>
> Spotify answers this question with a clock. A browser answers it with
> whatever it last wrote down: Firefox's own MPRIS publishes a position
> rounded to the second, so the same 3.000 comes back sixty times and
> then becomes 4.000 all at once. Taken at face value that is a clock
> which stands still for a second and then jumps one, and the words
> above it stall and race -- which is what "laggy, and it keeps
> re-timing" is.
>
> So the reading is used the way CdpTransport uses the engine: as an
> ANCHOR rather than as the position. When the player's answer CHANGES,
> that is news and it is taken whole -- and it is news that arrived
> just now, so it is accurate to the poll rather than to the player's
> step. When the answer repeats, the player has not moved on, not the
> song, and the last anchor carries forward at 1x.
>
> Measured on the machine this was written on: Firefox's step to N
> appears while the audio is at N-0.1 or so, so anchoring on the change
> lands within about a tenth of a second where taking the number as it
> stands is out by up to half of one.
>
> Inert where it is not needed. Spotify's own position over the bus
> differs on every read, so every read is an anchor and this returns
> exactly what it was given -- and so does a service that stamps its
> readings itself, which is what Windows' timeline does. The carry is
> capped at STILL_FOR, which is where a player that has stopped
> answering is dropped anyway.

### `SessionTransport._moving`

**line 2759** — from the docstring, `def _moving(self, got: dict) -> bool:`

> Whether this player's clock is actually running.
>
> A player is not followed on its word that it is playing -- it is
> followed once its position has been SEEN to move, because a position
> that never moves is the one failure here that looks like success (see
> STILL_FOR). Judged only while it claims to be playing: a paused player
> standing still is a paused player.
>
> The reading is the one _tick kept: when the player last said something
> new. Self-healing, since that is rewritten every time the player does
> move, so one that stalls and comes back is followed again at once and
> nothing is remembered against it.

### `SessionTransport.dress`

**line 2794** — from the docstring, `def dress(self, tid: str, extra: dict) -> None:`

> Fill in what the player left out, for this track.
>
> Only the empty fields are filled -- except the cover and the name,
> which are replaced. The cover because a browser's is a video's
> thumbnail, sixteen by nine with the channel's lettering across it,
> where the album's own square is what the window is built to draw.
> The name because an upload is titled by whoever uploaded it: YouTube
> shouts the artist in capitals and writes the song's name with the
> label's tag on the end, and a catalogue spells it the way the record
> does. See LyricsView.on_card, which is what decides there is enough
> agreement to rename anything at all.

### `MprisTransport`

**line 2861** — from the docstring, `class MprisTransport(SessionTransport):`

> Spotify over the session bus. Linux and the other freedesktop platforms.
>
> With `any_player` it is every player on the bus instead: a song playing on
> YouTube in Firefox, a file in mpv, anything that publishes MPRIS at all.
>
> That is a setting and not the behaviour, because the bus does not only
> carry songs. A film has a title and an artist on it exactly as a single
> does, and a window that followed whatever last made a noise would throw
> away the lyrics it is showing to say nothing about an episode of
> something. So the other players are filtered -- see looks_like_a_song --
> and Spotify is not: whatever is playing THERE was chosen in a music
> player, and a podcast picked there is still what is being listened to.
>
> Everything in that paragraph is SessionTransport's, and so is the rest of
> what it takes to follow a stranger's player. What is left here is the bus:
> proxies, the xesam field names, and the two things MPRIS has that the
> other platforms' services do not -- a volume, and a per-player statement
> of what it is willing to be told (see _able).

### `MprisTransport._rank`

**line 2886** — from the docstring, `def _rank(who: str) -> int:`

> Which of two players saying the same thing to believe.
>
> Spotify first: it is the one with the better clock and the one the
> rest of this program is built around, so where two things are playing
> at once -- a tab left running under a song -- it is the one to
> believe. Then the desktop's bridge, then the players themselves. See
> BRIDGE_PLAYERS for what that middle rank is and what it is worth.

### `MprisTransport._read_gets.position`

**line 2956** — from the docstring, `def position() -> tuple[float, float]:`

> The position, and the middle of the call that asked for it.
>
> A property read is a round trip over the session bus, and the
> answer describes where the song was somewhere inside it. See
> CdpTransport.read for why the middle is the honest stamp; the bus
> is slower than the debug port, so there is rather more of it here.

### `MprisTransport._song_of`

**line 2988** — from the docstring, `def _song_of(meta, who: str) -> tuple[dict, str | None]:`

> The card as the window wants it, and the id to key it by.
>
> Off Spotify the card is not a song's -- it is a video's, and the
> title is the name of an upload rather than the name of a song. It is
> cleaned up here, at the edge, so that everything after this point is
> looking at the song: the search, the card on screen, the offsets, the
> id. See song_from_video for what that means and what it leaves alone.
>
> The id is Spotify's own where there is one. There is nothing to use
> off Spotify -- a browser's trackid counts tabs and mpv's counts the
> playlist -- so the words on the card become the id, which is the
> bargain the Windows media transport already makes. Made from the
> CLEANED words, so the same song uploaded twice with two different
> decorations is one track and not two.

### `MprisTransport._able`

**line 3014** — from the docstring, `def _able(self, what: str) -> str:`

> Which player to tell, for something the followed one may not do.
>
> The bridge and the browser publish the SAME playback -- see
> BRIDGE_PLAYERS -- and they do not publish the same powers over it.
> Measured here on one YouTube Music tab: the bridge has the position
> and the pause and says CanGoNext false, while Firefox's own MPRIS,
> describing that same tab, will skip. Following the better clock is
> right and losing the skip key over it is not, so an instruction goes
> to whoever can carry it out rather than to whoever is being read.
>
> Only to a player that is on the SAME thing, matched by the address it
> is playing or by the words on its card. Nothing weaker: Spotify sits
> on the bus paused, saying it can skip, and a Next that woke it up
> would be the wrong song playing out loud.

### `CdpTransport`

**line 3152** — from the docstring, `class CdpTransport:`

> Spotify over its own debug port -- the same connection the rest of the
> app already uses. Works anywhere Spotify runs, and is the only way in on
> Windows, which has no session bus to ask.
>
> Two threads use this at once: the sampler reading sixty times a second,
> and whoever seeks. The socket underneath was built for that (see
> spotify_dom.CDP -- every answer goes to whoever asked for it), so only
> the lazy connect needs guarding, and only the connect: holding a lock
> across a READ would put the seek back on the caller's thread to wait out,
> which is the whole thing the sampler exists to avoid.

### `CdpTransport._smooth`

**line 3196** — from the docstring, `def _smooth(self, raw: float, at: float, tid: str | None,`

> The engine's position, with the shake taken out of it.
>
> A clock of our own that advances at 1x and is pulled towards each
> reading, rather than the reading itself. See ENGINE_TAU for why, and
> for the two numbers.
>
> Re-anchored outright on a new song, on the first reading, and whenever
> the song is not playing -- a paused position is meant to stand still,
> and a clock that went on advancing towards it would drift off the end
> of a pause. A long gap between readings re-anchors by itself: alpha
> goes to 1 as the gap grows, which is exactly what should happen to a
> prediction nobody has checked in a while.

### `CdpTransport._pick`

**line 3213** — from the docstring, `def _pick(self, engine: float | None, control: float, playing: bool,`

> Which of the player's two clocks to believe.
>
> The engine's, whenever it is there. The control state is what Spotify
> has PUBLISHED about itself -- position as of a timestamp -- and it is
> published when a transition is decided, not when it is heard: at a
> gapless hand-off the new track is announced at position zero while the
> device is still draining the last seconds of the old one. A clock
> anchored on that is ahead of the sound for the top of every
> automatically-played track, which is what resync() has been flushing
> the pipeline to undo. The engine's position is where the audio
> actually is, so it never gets ahead of it and there is nothing to
> undo. Spicy Lyrics reads it for the same reason and has no resync.
>
> The control state is the backup, for two ways the engine can go:
>
> Gone -- not local playback, an internal renamed, the call throwing or
> timing out. `engine` arrives as None and there is nothing to decide.
>
> Stopped -- the nastier one, and the reason this holds a clock. Spicy
> Lyrics' own source warns that not every client refreshes
> getPositionState continuously: on some builds it only moves when the
> player emits a state change, so the same value comes back for hundreds
> of polls. That is indistinguishable from a song that has stopped, and
> believing it would freeze the words mid-line with the music playing.
>
> A brief stall is not a failure, though, and switching source is a step
> in the clock -- the two do not agree to the millisecond -- so it is
> worth waiting out. STALE_HOLD is exactly how long the clock goes on
> extrapolating an unchanged reading before it stops believing it, so
> using the same number here means the backup takes over at the moment
> the hold would otherwise expire and the words would stall. Not a
> coincidence to be kept in step by hand: they are the same question.
>
> Paused, the position is meant to stand still, so the wait restarts on
> every reading and a long pause never counts as a stall.

### `CdpTransport.read`

**line 3251** — from the docstring, `def read(self, want_volume: bool) -> dict:`

> A position, and the moment it was TRUE rather than the moment it
> arrived.
>
> The page computes the position when it runs the script; this side only
> hears about it once the answer has come back down the socket. Stamping
> the reading on arrival says the song was there at a moment it had
> already passed, so every word is late by the return leg -- and the
> anchor is what the clock then extrapolates from, so the error does not
> wash out, it is carried until the next reading replaces it.
>
> Charging half the round trip is the best available guess at when the
> page actually looked, and is the same correction Spicy Lyrics makes
> inside the page for its own IPC. Idle it is worth a fifth of a
> millisecond and no one could hear it. It is not idle that matters:
> around a seek or a resume Spotify's renderer is busy and an answer
> that normally takes 0.3ms can take most of a second -- exactly the
> moments the words are being watched hardest.

### `SmtcTransport`

**line 3311** — from the docstring, `class SmtcTransport(SessionTransport):`

> Windows' own now-playing service.
>
> Windows has had a system media transport since 8 -- the thing that draws
> the little now-playing card on the volume flyout -- and Spotify feeds it
> like every other player. It is the true equivalent of MPRIS, and unlike the
> debug port it needs nothing configured: no launch flag, no Spicetify, and it
> works with the Microsoft Store build, which cannot be given a flag at all.
>
> IT IS ALSO WHERE THE BROWSERS ARE. Chrome, Edge and Firefox each publish a
> session for whatever their pages are playing -- the same MediaSession card
> the page filled in -- so "follow whoever is playing" is one list here, the
> way it is one bus on Linux. Everything that decides which of them to
> follow, what is a song and what a song is called is SessionTransport's and
> is the same code the bus runs.
>
> Three things this service has that the bus does not. Its timeline carries
> the moment it was WRITTEN, so a position can be carried forward against a
> real timestamp instead of being inferred from when it last changed -- see
> _read_one, and _tick, which stays behind it to answer the other question.
> It says whether a session is playing music or video, which is worth
> something and not much -- see looks_like_a_song. And its covers come as
> bytes rather than as an address, so they are put on the disk and handed
> over as one.
>
> Two things it does not carry. There is no volume in the protocol, so the
> slider stays hidden. And there is no Spotify track id -- only the words on
> the card -- so one is made up from the title and artist, which is stable for
> a song and is all the name-searching providers need. Spicy Lyrics is asked
> by the real Spotify id, which nothing here knows, so it cannot answer for
> these sessions; the name-searching providers carry the lyrics instead.

### `SmtcTransport._mod`

**line 3328** — from the docstring, `def _mod():`

> The session manager, out of whichever projection is whole here.
>
> Raises with WINRT_FIX rather than with the name of some namespace
> nobody asked for. This used to reach the window as "No module named
> 'winrt.windows.foundation'", painted across the middle of it, which
> says nothing about what to install.

### `SmtcTransport._live`

**line 3403** — from the docstring, `def _live(self) -> dict:`

> Short name -> session, for everything the transport has open.
>
> Keyed by the short name rather than by the session object, because a
> session object is handed out fresh on every call and nothing that
> remembers a player -- the clocks, the covers, the offsets -- could be
> keyed by one.

### `SmtcTransport._session`

**line 3423** — from the docstring, `def _session(self, who=None):`

> The session to read, or None.
>
> Asked for Spotify and without it there, the answer is whatever Windows
> calls the current session -- which is what this has always done, and
> is what makes the plain Spotify-only setting keep working when
> somebody is listening in a browser instead.

### `SmtcTransport._cover`

**line 3491** — from the docstring, `def _cover(self, tid, info) -> str:`

> The cover as an address, having first made it into a file.
>
> Every other way in hands over a url and the window fetches it. This one
> hands over a stream, so it is read once per track, written into the
> same cache the fetched covers live in, and named as a file -- after
> which nothing downstream can tell the difference.

### `_allows`

**line 3594** — from the docstring, `def _allows(session, what: str) -> bool:`

> Whether the session says it will take this instruction.
>
> Windows publishes a flag per control exactly as MPRIS does, and it means
> the same thing: a session that answers false does nothing when told,
> silently. Unlike MPRIS there is no second session describing the same
> playback to ask instead -- the browser publishes its own and that is the
> only one -- so this is a yes or a message, not a redirection.

### `_thumb_bytes`

**line 3606** — from the docstring, `def _thumb_bytes(ref) -> bytes:`

> A cover's bytes, off the stream the transport hands over.
>
> Written twice on purpose. The buffer is what the projection is happiest
> with and what the newer bindings support the Python buffer protocol for;
> the reader is the older shape and is there because these bindings are two
> packages with one API and they do not agree on this corner of it. Either
> failing is not a failure -- it is a song without a cover.
> Runs on the WinRT thread (_WinrtHome); a stream that stalls is kept, never freed.

### `MacTransport`

**line 3651** — from the docstring, `class MacTransport(SessionTransport):`

> Whoever is playing on a Mac.
>
> macOS is the platform with no single answer to this question, so this one
> holds three doors and prefers whichever is open -- see macplayer, which is
> where each of them lives and why. What the doors have in common is exactly
> what SessionTransport wants: a name, an artist, a length, a position and
> whether it is going. Everything about choosing between players, telling a
> song from a film and making a stepping clock move is the same code the
> session bus and the Windows transport run.
>
> The one thing that is different in kind is the COST of a reading. A bus
> property is a round trip and a Windows session is a COM call; an Apple
> Event is a process, and the sampler asks sixty times a second. So the
> Apple Events doors are read in the background at MAC_EVERY and handed over
> from a slot, which makes them a player with a coarse clock -- and a player
> with a coarse clock is what _tick has always been for. MediaRemote, where
> it is open, is read inline: it is a function call, it carries the moment
> its position was true, and it needs none of this.

### `MacTransport._open_apps`

**line 3693** — from the docstring, `def _open_apps() -> list:`

> The players that are running, off the process table.
>
> `ps` rather than System Events on purpose: this is asked every few
> seconds from a program that has not yet been given permission to
> automate anything, and asking the wrong way would raise a consent
> prompt to find out whether Safari is open.

### `BackupTransport`

**line 3875** — from the docstring, `class BackupTransport:`

> Primary, with a stand-in for while the primary is down.
>
> SMTC answers over a COM call per read and is noticeably slower than either
> the debug port or the bus, so it should not be what drives the clock merely
> because Spotify happened to start second. This keeps asking the primary --
> at a sensible interval, not four times a second at a dead port -- and hands
> back over the moment it answers. The stand-in is what you get in between,
> rather than nothing.
>
> `handover` changes what counts as "down" -- see the flag itself. It is on
> when the stand-in is reading a DIFFERENT player rather than the same one
> a second way, which is what the any-media-player setting makes of it.

### `BackupTransport._follow`

**line 3980** — from the docstring, `def _follow(self, want_volume: bool):`

> Read whoever is playing; glance at the other one in the silences.
>
> The side already being followed is read every time, at the sampler's
> full rate, so a song playing costs exactly the one reading it always
> did. The other side is only asked while THIS one has nothing playing
> -- which is the only moment its answer could change anything -- and
> then no more often than LOOK.
>
> A side that raises hands over at once: that is the old stand-in rule,
> and it is the same rule, since a player that is not there is not
> playing either.

### `make_transport`

**line 4108** — from the docstring, `def make_transport(port: int, prefer: str = "auto", any_player: bool = False,`

> Whichever way in is actually available here.
>
> The debug port leads on all three platforms, because it is quick, because
> it is the one that also brings the search, the browser and the queue with
> it, and -- the reason it leads on Linux too -- because it is the clock
> Spotify itself is drawn from.
>
> The session bus is not that clock. Spotify publishes a position on it that
> freezes across its own transport changes and catches up a moment later,
> which nobody notices while a track simply plays and everybody notices the
> instant one does not. Measured against Spicetify's progress over the bus,
> 4x/second: a seek made in Spotify's own window reports the seek target for
> the first read after it, so the position comes back 0.5-0.6s behind the
> audio; an unpause reports the paused position, 0.3s behind. Both are right
> again within two polls, which is exactly long enough to throw a word-synced
> line and then snap it back. A seek made from HERE has neither problem: the
> clock is told where it went and does not have to ask.
>
> So the bus becomes the stand-in rather than the primary -- what drives the
> clock when Spotify was started without the port open, which is the case it
> was really there for. --player mpris still pins it.
>
> THE OTHER TWO PLATFORMS ARE THE SAME ARRANGEMENT with a different stand-in
> -- Windows' media transport, or the Mac's now-playing -- and they are the
> same arrangement because they now answer the same question. Each is a list
> of every player on the machine and each can be followed the same way, so
> `any_player` does on all three what it used to do on one: the pair follows
> whoever is actually PLAYING rather than always preferring the port (that
> is BackupTransport's `handover`), and the stand-in is every player rather
> than a second view of Spotify. Spotify still wins while Spotify is
> playing, and still over the port rather than the platform.
>
> Off, both ways in read Spotify and the better one leads, which is what
> each platform did before any of this.

### `Clock.poll`

**line 4158** — from the docstring, `def poll(self, pin_pause: bool = True) -> None:`

> Ask the player where it is, and take the answer.
>
> Split in two so a window that cannot afford to block has somewhere to
> put the waiting: `read` is the round-trip to the player, `apply` is
> arithmetic. The editor runs the first on a thread of its own and the
> second under `lock` -- see editor/player.py. Everything that polls on
> the thread it draws on keeps calling this and notices no difference.

### `Clock.resume_hold`

**line 4266** — from the docstring, `def resume_hold(self) -> float:`

> How far the words are being moved for the last unpause.
>
> The displacement the player made when it resumed and did not come back
> from, carried until something re-establishes where playback is. Worth
> having where it can be read: it is the one correction in here with no
> visible cause, and the difference between "the setting does nothing"
> and "the setting is doing exactly what it says and the fault is
> elsewhere" is this number.
>
> POSITIVE HOLDS THE WORDS BACK, which is the common case -- the player
> leaps forward on resume and the sound has not caught up. Negative
> pushes them on, for the other one: the audio was already running by
> the time the player admitted to playing, so the position it reports is
> behind its own sound and the words are late for the rest of the track.
> Nothing in a position reading can tell you that has happened, which is
> why `unpause_delay` reaches below zero and can simply be set.

### `Clock._pin`

**line 4292** — from the docstring, `def _pin(self, pos: float) -> None:`

> Ask the paused player to go where it already says it is.
>
> Silent, because nothing is playing: the position does not move, the
> progress bar does not move, and there is no audio to interrupt. What it
> does move is the player's idea of where its own audio is -- see SLEW_MAX
> above for how far that has drifted by the time it stops, and what it
> costs the rest of the song not to put it right.
>
> Failure is nothing to report. This corrects a fifth of a second on a
> track that is not playing; a player that will not take the seek simply
> keeps the sync it would have had anyway.

### `Clock.seek`

**line 4305** — from the docstring, `def seek(self, seconds: float, keep_hold: bool = False) -> None:`

> Send the player somewhere. `keep_hold` leaves the carried unpause
> leap alone.
>
> A seek asked for by hand drops the hold: clicking a line asks for that
> line's own timestamp, the anchor is that timestamp exactly, and
> adjusting a seek target by a correction was what put the song too far
> in.
>
> A resync is not that. Nothing stopped, nobody asked to go anywhere, and
> the sound carries straight on -- the seek is this program correcting
> itself, and dropping the hold across it left a track that handed over
> running earlier than the same track skipped to, for no reason anyone
> listening could name. Measured against the sink's own output: after a
> resync lands, the player's clock reads 0.054-0.058s AHEAD of the audio
> coming out (two hand-offs, each steady to a millisecond over half a
> minute), which is the same 0.045s the clock sits ahead in any flushed
> state. That is exactly what the hold is for, so the hold stays.

### `Clock.resync`

**line 4332** — from the docstring, `def resync(self) -> None:`

> Seek to where we already are. Spotify's audio output can lag its own
> clock after a gapless hand-off, which shows up as lyrics running early;
> a seek flushes the pipeline and realigns them. This is the manual
> workaround (nudge the scrubber) done automatically.
>
> The position is re-read from the player rather than taken from
> position(), which is an interpolation from the last poll plus whatever
> slew is still easing out. Seeking to an estimate does not correct a
> drift -- it writes the estimate into the player and makes it true, which
> is how a resync could leave the timing worse than it found it.

### `Clock.resync_soon`

**line 4345** — from the docstring, `def resync_soon(self) -> None:`

> The same resync, on a thread of its own, and one at a time.
>
> Nothing about the correction moves: this runs resync itself, so the
> position is still re-read from the player and seek()'s arithmetic is
> the same arithmetic. Only the waiting happens somewhere the window is
> not.

### `Clock.command`

**line 4361** — from the docstring, `def command(self, name: str) -> bool:`

> PlayPause / Next / Previous. False where the player would not.
>
> Not every player can do all three. A browser tab with one song in it
> has nothing to skip to, and MPRIS says so in a property rather than
> by failing -- see MprisTransport._able, which is what turns that into
> the exception caught here. Passed back rather than swallowed, because
> silence is the wrong answer to a key that did nothing.

### `Pump`

**line 4373** — from the docstring, `class Pump(QThread):`

> The thread that asks Spotify where it is, as often as a frame.
>
> A seek made in Spotify's OWN window is the one move this program cannot
> know about until it asks. Between asking, the clock does the only sane
> thing and carries the last reading forward at 1x -- straight through a
> jump that has already happened. So the words are wrong for as long as the
> gap between readings, and asked four times a second that is a quarter of a
> second of the wrong line, every time the scrubber is touched.
>
> Spicy Lyrics has no such gap: it lives inside the page, so it re-reads the
> position every frame and a seek is stale for one. The same rate is
> affordable here, but not on the thread that draws. Every reading is a
> round trip -- 0.28ms median down the debug port, measured over 200 of them
> -- and that is the quiet case; around a resume or a seek the renderer is
> busy and the same question can take most of a second. Sixty of those a
> second on the GUI thread would stall the window exactly when the song is
> doing something worth watching.
>
> So the waiting happens here and the arithmetic happens under the clock's
> lock, which is what that lock has always been for. The window reads an
> interpolated position between readings and never blocks on the player.
> This is the editor's `_Pump` (see editor/player.py) doing the same job for
> the same reason; the window simply never had one.
>
> Only reads. Transport WRITES still go from whoever wants them -- the
> socket underneath is explicitly usable from more than one thread (see
> spotify_dom.CDP), and a seek asked for here is one call, not sixty a
> second.

### `Pump._news`

**line 4396** — from the docstring, `def _news(self) -> bool:`

> Whether the reading just taken is something the window has to hear.
>
> Sixty of these a second were queued to the GUI thread whether or not
> anything had changed, and on_reading did nothing with all but the
> ones that changed the track. What it has to hear is the track or the
> status changing, and a position that moved while the song is not
> playing -- a seek on a paused player, which nothing else would repaint
> at once. While it plays the frames are already running and already
> read the clock.

### `LyricIndex`

**line 4447** — from the docstring, `class LyricIndex:`

> Every held song's lines, so you can find one by any phrase in it.
>
> The songs are the ones Spicy Lyrics has been asked about from here, which
> on a machine that has been listening is well over a thousand; pulling them
> is one batched pass over the cache on disk and the result is small enough
> to keep beside it.

### `LyricIndex._blob`

**line 4462** — from the docstring, `def _blob(self, s: dict) -> tuple:`

> One song's text as `search` reads it: (lines, title, artist, "title
> artist" lower-cased, all its lines lower-cased and joined by SEP -- or
> None if a line has SEP in it).
>
> Every keystroke lower-cased every line of every song to look for what
> was typed in it, about 110,000 calls at eighteen hundred songs. This
> is done once for a song and again only if its lines or its name are
> not the ones it was made from. The whole is held as one string, which
> costs the text again and no more: the first line with the phrase in
> it is found by counting the separators before it.

### `Beat`

**line 4542** — from the docstring, `class Beat:`

> Spotify's own analysis of the playing track.
>
> Spicetify hands over the same beat/bar/section/segment breakdown the web
> player uses, so the visuals can land on the beat without ever touching audio.
>
> The metrical grid drives the pulse; `pitch` and `timbre` are a coarse
> spectral summary of the track that nothing reads yet, kept because they
> arrive in the same round trip and are the only description of the actual
> sound available anywhere in this program.

### `Beat.chroma`

**line 4660** — from the docstring, `def chroma(self, pos: float) -> list[float]:`

> The twelve pitch-class strengths sounding at `pos`, or nothing.
>
> Spotify normalises each vector so the loudest class in it reads 1.0.
> That makes the SHAPE comparable between segments but not the level --
> a near-silent segment still reports a peak of 1.0 -- so anything
> sizing itself from this has to take its scale from `loudness`.

### `Beat.voiced`

**line 4668** — from the docstring, `def voiced(self, pos: float) -> float:`

> How much of a pitch there is to answer to at `pos`, 0..1.
>
> Chroma arrives normalised so the loudest class always reads 1.0,
> which means an unpitched segment comes back looking exactly as
> confident as a chord -- just flatter. A snare, a hi-hat and a spoken
> consonant all report a spread of twelve middling classes, and anything
> sizing itself from the SHAPE of that is sizing itself from noise: it
> is why a beat-driven track scatters the visualiser where a sung one
> moves it. The flatness is the tell, so it is what gets measured, and
> the peakier the vector the more the shape is worth reading.

### `Beat.recent`

**line 4677** — from the docstring, `def recent(self, pos: float, span: float) -> list[tuple[int, float, float]]:`

> (index, start, strength) for every beat landing in the `span`
> seconds up to `pos`, oldest first.
>
> `energy` gives the one beat under way, which is all a pulse on the
> window needs; anything drawing a beat as something that TRAVELS needs
> the ones still crossing, so they are handed over whole.

### `Beat.level`

**line 4686** — from the docstring, `def level(self, pos: float) -> float:`

> Loudness again, but normalised over the tenth to the ninetieth
> percentile instead of the full range.
>
> `loudness` spans min to max, and every track has a near-silent segment
> somewhere in a fade or a gap -- measured across a dozen tracks, that
> floor sits 43 to 61dB under the body of the song, which leaves the
> whole song crushed into the top sliver of the scale. It reads out at a
> standard deviation of 0.08: a constant, near enough, and anything
> modulated by it does not move.
>
> Rock suffers this worst, being compressed and wide at once: its middle
> eighty percent covers about 13% of its full range where a sparser mix
> covers 25%. Cutting the tails brings the variation back to 0.33 and,
> more to the point, brings it back EQUALLY -- the gap between genres
> closes to nothing. The tails are what differed, never the music.
>
> `loudness` is left as it was because the beat strengths are weighted
> with it at load, and those are read by the offset estimator.

### `onsets_of`

**line 4741** — from the docstring, `def onsets_of(beat: Beat) -> list[tuple[float, float]]:`

> Where the sound changes, and by how much it looks like a voice doing it.
>
> Spotify cuts a new segment at every acoustic edge it finds, so the segment
> starts already ARE an onset list. The trouble is that it cuts for a kick
> drum as readily as for a singer, and on a dense record most edges are the
> kit -- correlating against them unweighted measures the drummer.
>
> What distinguishes the two is not loudness, which a snare has plenty of, but
> whether the spectrum either side of the edge has a different SHAPE. Another
> snare in a bar of snares is louder than its neighbour and otherwise
> identical; a voice entering over the same bar changes the timbre. Weighting
> by that change does not identify anybody -- nothing available here could --
> but it stops the estimate being decided by whichever percussion happened to
> fall nearest the line.

### `anchors_of`

**line 4782** — from the docstring, `def anchors_of(lines: list[dict]) -> list[float]:`

> Moments a vocal entry should be audible under.
>
> Only the ones that follow real silence in the lyrics, for the reason given
> at ANCHOR_GAP, and only from the untouched timeline -- interlude markers are
> inserted by prepare() at times nobody sang, so they anchor to nothing.
>
> WORDS AS WELL AS LINES, which is most of what this now finds. The test an
> anchor has to pass is that the edge in the sound near it can only be this
> word's own entry, and a break before it is what makes that true -- the
> singer stopped, then started again. Nothing about that is a property of
> being a LINE start: a word that follows the same silence inside a line is
> the same event at a smaller scale, and one that runs straight on from the
> word before it is no good as either, because there is no entry to find --
> the spectrum simply changes and the edge belongs as much to what came
> before. Line starts alone meant the run-on ones were counted and the clean
> ones inside a line were thrown away.
>
> Measured over the 55 documents in this directory: 839 anchors to 1102, a
> median of 10 a song to 16, and the songs with too few to measure AT ALL
> (see MIN_ANCHORS) from 15 down to 10. Five of those become measurable, and
> the extreme is the lyric written without a gap between one line and the
> next -- "Sexion d'Assaut - Ma direction" had ONE anchor in the whole song
> and has 13.
>
> The word pass advances its `prev_end` over a line that has no syllable
> times of its own, and that is worth a sentence because getting it wrong
> flatters the numbers: a line-timed line still occupies the time it covers,
> and skipping it leaves the next word looking like it follows half a bar of
> silence when the singer never stopped. Counting those put this at 1228
> rather than 1102, and every one of the difference was an anchor with no
> entry under it.
>
> A UNION, and deliberately: the word pass carries its own `prev_end`, which
> runs to the last word's end rather than to whatever the line claims for
> its own, so a line whose words overrun it would lose a line start that the
> line-level rule was happy with. Nothing here may take an anchor away.
>
> Sorted, because estimate_offset splits this list down the middle to get a
> second opinion from each half of the SONG, and a set is not in any order.

### `_est_curve`

**line 4810** — from the docstring, `def _est_curve(anchors: list[float], onsets: list[tuple[float, float]],`

> How well these anchors sit on the sound, at every shift in range.
>
> The sum is over every edge near an anchor rather than the nearest one to it.
> Pairing with the nearest looks equivalent and is not: whichever side of the
> anchor an edge falls, "nearest" picks the closer, so the residuals are
> pulled towards zero and so is every estimate made from them -- the bias is
> worst exactly where the offset is small, which is the case this exists for.

### `_est_curves`

**line 4831** — from the docstring, `def _est_curves(anchors: list[float], onsets: list[tuple[float, float]],`

> `_est_curve` of every anchor, of the first `mid`, and of the rest.
>
> The three are sums over the same terms, and were worked out from scratch
> one after the other -- the whole song and then each half, which is twice
> the work there is. Here every term is worked out once and added to the
> totals it belongs to, in the order each of them was added before, so the
> three curves are the same to the last bit.

### `estimate_offset`

**line 4875** — from the docstring, `def estimate_offset(lines: list[dict], beat: Beat) -> dict:`

> How far the lyrics sit from the sound, by correlating one against the other.
>
> Returns {} when there is not enough to say, which is the common answer and
> not a failure. Otherwise `delta` is how much LATER the lyrics should be
> played than they claim, `conf` is how far the winning alignment stood above
> its nearest rival, and `n` is how many anchors voted.
>
> `spread` is the second opinion: the same measurement made again on each
> half of the song alone, and how far the two halves' answers sit apart. It
> asks something confidence cannot, because confidence is a fact about one
> curve and this is a fact about the song -- an offset the recording really
> has is there in both halves, while a shift that won on the strength of one
> stretch of it is not. See EST_AGREE. A half that correlates with nothing at
> all reports the widest disagreement there is rather than no disagreement:
> an answer that could not be checked has not passed a check.

### `split_artists`

**line 4937** — from the docstring, `def split_artists(title: str, artists: list) -> tuple[list, list]:`

> Everyone credited, split into who the song is by and who guests on it.
>
> Spotify says nothing about which of a track's artists is featured -- they
> arrive as one flat list, primary first -- so the title is the only evidence
> there is, and no evidence means no guest. Being second on the credit is not
> a demotion: "Die With A Smile" is by both of them, and reading position as
> billing would call every duet a guest spot.
>
> Where the title does name someone, they are matched against the credit list
> loosely and in both directions, because the two rarely spell it the same --
> "Airplanes (feat. Hayley Williams of Paramore)" is credited to plain "Hayley
> Williams". Where they agree the credit-list spelling wins, being the
> canonical one and the only one carrying a uri, and that artist leaves the
> primary side so nobody is named twice.

### `fetch_font`

**line 5048** — from the docstring, `def fetch_font(name: str, weight: int | None = None) -> pathlib.Path | None:`

> Download a font family, or None. Cached, so it is fetched once.
>
> The repo is tried first because it serves complete TrueType, variable where
> the family has one. The CSS endpoint is the fallback: it always answers, but
> with an old User-Agent -- the only way to get TrueType rather than woff2 out
> of it -- it hands back a single weight-400 file with no axis at all, which
> is why a page drawn at Black came out looking thin.

### `art_bytes`

**line 5098** — from the docstring, `def art_bytes(url: str, tries: int = ART_TRIES):`

> One cover: off the disk if it has ever been fetched, off the network
> if it has not, and None if it could not be had at all.
>
> KEPT ON THE DISK, which is the strongest half of this. A cover that was
> fetched once is never fetched again, so a machine that drops one request
> in twenty stops mattering the second time a song comes round -- and the
> browse grid has worked that way all along. It was only the big cover
> behind the lyrics that went back to the network every play.
>
> It also asks as this program rather than as Python's urllib, which is
> what the grid has always done and what the panel never did. A default
> User-Agent is the first thing an interfering proxy declines.

### `art_url`

**line 5172** — from the docstring, `def art_url(u: str) -> str:`

> Normalise whatever a Spotify API hands back into a fetchable URL.
>
> Three spellings turn up for the same kind of asset: plain https, the
> `spotify:image:<hash>` form RecentlyPlayedAPI uses, and `spotify:mosaic:`
> followed by the four covers a playlist collage is built from. There is no
> endpoint that renders the collage, so the first cover stands in for it --
> better than the empty square that a playlist would otherwise get.

### `best_variant`

**line 5524** — from the docstring, `def best_variant(master_url: str) -> str:`

> The highest-resolution rendition in an HLS master playlist.
>
> Handed the master, ffmpeg sees every rendition at once -- twenty-odd streams
> from 360x360 up -- and picks among them by its own reckoning, interleaving
> segments from several as it goes. That is where both the softness and the
> "Invalid NAL unit" complaints came from. Choosing one rendition here and
> passing ffmpeg that leaves it nothing to guess at.

### `_web_albums`

**line 5585** — from the docstring, `def _web_albums(term: str) -> list:`

> The same, from music.apple.com's search page.
>
> The Search API's index runs years behind for some records -- "Linkin Park
> From Zero" returns Meteora, Hybrid Theory and Living Things and never the
> 2024 album at all, deluxe or not. The web page finds it. It carries no
> usable metadata for matching, though, so its album ids go back through the
> lookup endpoint to come out in the same shape as a search hit.

### `motion_url`

**line 5609** — from the docstring, `def motion_url(artist: str, album: str, title: str = "") -> str:`

> The animated cover's stream for this record, or "".
>
> Two steps because the two halves live in different places: the search knows
> which album this is and nothing about its video, and the music.apple.com
> page carries the video but cannot be found without the id.
>
> The animation belongs to the record, never to the track, so the album name
> is what is searched. A single is the one case where the two coincide -- the
> release is the song -- and there the song's title stands in for it.
>
> The artist is checked as hard as the title is. Album names are nowhere near
> unique -- searching "NF NO NAME" returns NF's own single, three unrelated NF
> records, and Jack White's "No Name" -- and since a page without an animation
> is skipped rather than fatal, matching on the title alone walked straight
> past NF and hung Jack White's video on his record.

### `MotionArt`

**line 5662** — from the docstring, `class MotionArt(QObject):`

> The animated cover, as frames, fetched and decoded off the GUI thread.
>
> Everything about this is best-effort: the album may have no animation, the
> page format is Apple's and undocumented, and ffmpeg may not be installed.
> Every failure ends the same way -- no frames, and the still cover carries on
> exactly as it did before.

### `MotionArt.want`

**line 5686** — from the docstring, `def want(self, key: str, artist: str, album: str, title: str = "",`

> Ask for this album's animation, unless it is already being fetched.
> `cap` is the widest a frame will be drawn, which is what says how many
> of them there is room to keep.
>
> `seen` means IN FLIGHT, not "ever asked". It used to mean the second,
> which is why skipping a song and coming back to it left the cover
> still: the view drops its frames when the key changes, and this then
> refused to send them again, so the animation was gone until the app
> restarted.
>
> Asking twice is cheap. The frames are decoded to disk the first time,
> so a repeat is a handful of JPEG reads -- no network, no ffmpeg -- and
> an album with no animation is remembered as a miss and answered
> without either.

### `MotionArt._frames`

**line 5836** — from the docstring, `def _frames(self, key: str, artist: str, album: str, title: str = "",`

> The animation's frames, only as many as the screen has room for,
> each decoded no wider than `cap`; a MotionStream over the files on
> disk where `stream` (Memory use "low").
>
> Every frame on disk used to be decoded and handed over, and the window
> then threw away all but a twelfth of them: a 35 second cover is up to
> 1,050 frames of 2MB each, over two gigabytes for a moment on every
> track change, against the 192MB the window ever keeps. The ones it
> would keep are worked out here, from the same budget and the same
> arithmetic, and only they are read.

### `ArtCache`

**line 5874** — from the docstring, `class ArtCache(QObject):`

> Thumbnails for the browse grid.
>
> _load_art spawns a thread per image and blurs it four times over -- right for
> one full-size cover behind the lyrics, hopeless for forty 160px cards. This
> is a small fixed pool with a disk cache instead.
>
> Workers emit QImage, never QPixmap: QPixmap is main-thread only and is a
> documented crash here.

### `ArtCache.put`

**line 5918** — from the docstring, `def put(self, url: str, img) -> None:`

> GUI thread only -- QPixmap conversion has to happen here.
>
> Held to BUDGET bytes, the least recently drawn going first. It was
> held to a count of 250, which is 100MB of 320px pictures for a grid
> that shows forty, and what it let go of was never asked for again: the
> url stayed in `seen`, so that card stayed blank for good.

### `Fetcher._beat_for`

**line 6096** — from the docstring, `def _beat_for(self, tid: str) -> None:`

> Ask for the track's audio analysis, on a thread of its own.
>
> The visualiser -- the wall's modes and the halo where the cover sits --
> is drawn from this and nothing else, and it used to be asked from the
> loop: a quick ask before the lyric walk and a patient one after it.
> Whenever the page took longer than the quick one allowed, which is any
> track it had not fetched yet, the wall and the halo waited out the
> whole walk and came up with the words. Nothing about the analysis
> depends on the walk or the walk on it, and the socket answers several
> callers at once, so it has no business being in the queue; see `_act`.
>
> One id remembered, not every id seen: the window drops its analysis on
> every track change, so a song come back to needs sending again. The
> window re-asks for the track on screen four times a second while it
> has no words, and those are the ones this stops.
>
> A thread per track rather than one slot, because an ask cannot be
> called back once it is out: a slot would hold a skipped-to song's
> analysis behind the deadline of the song skipped past.

### `Fetcher._beat_ask`

**line 6106** — from the docstring, `def _beat_ask(self, tid: str) -> None:`

> One ask, and one more where the first failed before the page
> could have answered.
>
> The page answers null only at its deadline, so nothing back well
> inside it is the socket or the call failing -- a dropped connection
> being dialled again, typically -- and the second ask is on a fresh
> one. That is the case the old ask after the walk used to cover.

### `Fetcher.request_card`

**line 6119** — from the docstring, `def request_card(self, tid: str, meta: dict) -> None:`

> Ask Apple Music what this track looks like.
>
> For the players that cannot say. A browser hands over a video's
> thumbnail or nothing at all, and the catalogue this already asks
> about the words has the cover, the album and the rating -- see
> LS.apple_song, which answers all of it out of one request and
> remembers the answer.

### `Fetcher.request_play_id`

**line 6140** — from the docstring, `def request_play_id(self, sid: str) -> None:`

> Play a bare Spotify id, as whichever of a track or an album it is.
>
> Asked of the page, track first: a pasted id with nothing around it
> could be either, and only the catalogue knows. The answer comes back
> on id_played -- {kind, name}, or None when it is neither -- so a miss
> can be said rather than a "playing" that never plays.

### `Fetcher._act`

**line 6157** — from the docstring, `def _act(self, what: tuple) -> None:`

> Make the player do something, on a thread of its own.
>
> THE TWO THINGS IN HERE SOMEBODY IS WAITING TO HEAR, and the reason
> they are not in the fetcher's queue with everything else: that queue
> is served one pass at a time and a pass contains the lyric walk. A
> song picked out of a search therefore started playing when ten
> providers had finished answering about the song playing BEFORE it.
>
> Usually that is quick. Sometimes it is not: a door that answers
> slowly holds the whole pass, so picking a song could sit in silence
> for most of that, and whether it did depended on what the loop
> happened to be doing when you clicked. LyricsPlus was the worst of
> them at eight to seventeen seconds, hits and misses alike, and it is
> gone -- but nothing here should depend on that staying true.
> Moving these to the front of the pass is not the fix, because the
> pass is usually already running: it has to leave the queue.
>
> Nothing waits on it and nothing it waits on -- it is one round trip
> to the page -- so it belongs on a thread, exactly as the catalogue
> search does and for the same reason. See `request_catsearch`.
>
> One slot for both, last one wins. A play and a skip are the same
> question about what to hear next and only the last answer is wanted;
> two picks in the same moment are one pick, the way two volumes in the
> same moment are one volume. The thread is started on demand and ends
> when the slot is empty, so an idle window is not holding one.

### `Fetcher.request_catsearch`

**line 6202** — from the docstring, `def request_catsearch(self, q: str) -> None:`

> On a thread of its own, like the Genius search beside it.
>
> It is one round trip to the page and it used to sit at the END of the
> fetcher's loop, behind the lyric walk, the artists, the audio analysis
> -- the slowest call in the window, and the one right in front of this
> -- and then Genius and the NetEase romanisation. A query typed while a
> song was changing waited for all of it, which is why searching
> sometimes took an age and usually did not: it depended entirely on
> what the loop happened to be doing.
>
> Nothing waits on it and nothing it waits on, so it belongs on a thread
> rather than in a queue. A query typed while one is out replaces it;
> the window knows which query is on screen and drops an answer to any
> other.

### `Fetcher._warm`

**line 6276** — from the docstring, `def _warm(self) -> None:`

> The coming tracks' picks, made by the load's own code (_pick_ahead) before
> anybody is looking at them; see the 2026-10-24 note in lyrics_gui.md.
>
> On a thread of its own rather than in this object's own loop, which
> would be self-defeating: that loop is what answers the track the user
> just skipped to, and holding it for somebody else's lookup is exactly
> the wait this is here to remove. Nothing below touches the page -- that
> socket belongs to the fetcher thread, and _load is the only thing
> allowed to speak on it -- so this is network and disk and no more.
>
> Spicy Lyrics is warmed with the rest, and that is new: it used to be
> unwarmable, because it fetched inside the Spotify page and only for
> the track that was playing. It is a provider in the chain now and the
> one the walk leads with, so a track warmed here has its copy on disk
> before the load asks for it. Nothing is said about a failure -- nobody
> is looking at this song yet, and the load that follows will make the
> same request and say so then.
>
> The question asked is the widest one -- `have="none"`, nothing ranked
> ahead -- because that is the form whose answer satisfies the narrower
> one the real load asks later, whatever Spicy Lyrics turns out to have
> by then. fallback() stores the question beside the answer and will not
> read back a walk that was allowed to skip providers; asking the whole
> thing here is what keeps the stored answer usable.
>
> A track being loaded is waited out, not taken as a reason to forget
> what is coming up. Binning the queue there is what stopped this
> working at all: the window re-requests the track it is on every
> POLL_MS_EDGE for as long as its screen is empty, which is precisely
> the stretch after a track change -- so the list built by the scan on
> that change was thrown away a moment later, and nothing rebuilt it
> until the next scan a minute on. The look-ahead was armed exactly
> when it could not run, and the song it had been asked to warm was the
> one already playing by then.

### `Fetcher._busy`

**line 6381** — from the docstring, `def _busy(self) -> bool:`

> Whether a track the user is waiting on needs the network now.
>
> A NEW track only: one being loaded for the first time, or asked for
> and not yet taken. The track already on screen does not count, and
> counting it is what starved the look-ahead: the window re-asks for it
> every POLL_MS_EDGE while its screen is empty, and run() puts it back
> itself on every backoff, so a song with no lyrics held `_want` set for
> its whole length -- nothing ahead was warmed, WARM_PATIENCE then threw
> the list away, and the next skip or two landed cold.

### `Fetcher.run`

**line 6456** — from the docstring, `def run(self) -> None:`

> Lyric requests, and nothing else. Each walk on a thread of its own.
>
> The loop used to do everything in one pass -- the walk, then the
> album page, the queue, the card, Genius, the index -- so any of those
> asked during a walk waited out all ten providers, and a skip landed
> behind the last song's walk however hopeless that walk had become.
> Now the rest is serve()'s, on another thread, and this one only hands
> tracks out: a new one gets a walk at once while the one it replaced
> notices (see _alive) and winds itself down.
>
> The same track asked again while its walk is out does not get a second
> walk alongside it. It is remembered, and asked once more when the walk
> ends, which is what the one loop did: a reload with new settings still
> gets a pass. The window's empty-screen poll does not ask while one is
> out (see `walking`).

### `Fetcher._walk`

**line 6489** — from the docstring, `def _walk(self, tid: str, no: int, asked: bool, meta: dict) -> None:`

> One track's lyric walk, start to finish. See run().
>
> A walk that has been overtaken still finishes and still says what it
> found -- the window drops an answer for a track it is not on, and a
> track held out for vetting is answered this way. What it may not do is
> speak for the screen: the shown rank, the stand-in, `done`, what is
> loaded, and the retry are all the newest walk's to set.

### `Fetcher._alive`

**line 6614** — from the docstring, `def _alive(self, tid: str, no: int | None = None) -> bool:`

> Whether anybody is still waiting on this track's walk.
>
> run() takes _want off the slot before it loads, so None there means
> "this is still the one". A different id in it is the user having
> skipped: the walk in hand is then several seconds of requests for a
> screen that has moved on, and the walk they ARE waiting on is queued
> behind it at somebody's host gate. See LS.fallback's `alive`.
>
> The same id is not a reason to stop -- the window re-requests the
> track it is on four times a second while the screen is empty, and
> every one of those means "still want it", not "start again".
>
> Nor is an empty slot proof any more: run() empties it the moment it
> hands the next track a walk of its own, so a walk that has been
> overtaken is told by its number (see _mine).

### `Fetcher._mine`

**line 6622** — from the docstring, `def _mine(self, no: int | None = None) -> bool:`

> Whether walk `no` -- the calling walk's, by default -- is the newest.
>
> True off a walk altogether: what is asked from anywhere else is not
> a walk anybody has overtaken. The provider threads LS.fallback runs
> its asks on are not the walk's own, so what it calls back with hands
> the number over itself (see _fallback).

### `Fetcher._conn`

**line 6644** — from the docstring, `def _conn(self):`

> The page connection, made if there is not one.
>
> Under the lock, and only one of them: this is called from the loop,
> from the catalogue search's thread and from Genius's, so two threads
> finding it empty at the same moment would build two sockets and one
> of them would be dropped by the next failure -- taking the other
> thread's live connection with it.
>
> connect() ends the PROCESS when the port cannot be reached, which is
> the right answer for the command line this module also is and the
> wrong one on a worker thread: SystemExit is not an Exception, so it
> goes straight past every guard here and quietly kills whichever
> thread asked -- the fetcher's loop, usually, after which the window
> never loads another song. Turned back into the failure it is.

### `Fetcher._drop`

**line 6663** — from the docstring, `def _drop(self, cdp=None) -> None:`

> Let go of the page connection. After ANY failed call, not some.
>
> A read that timed out did not merely fail. It left the socket halfway
> through a frame, and the bytes still to come are the tail of a reply
> nobody is waiting for any more -- so the next call reads them as its
> own, gets nonsense, and fails too. Everything after one timeout on
> that socket is garbage until somebody throws it away.
>
> Throwing it away used to be the lyric read's private business, and it
> was the only caller that did it. Every other read -- the artists, the
> audio analysis, the queue, the recents -- swallowed its exception and
> left the poisoned socket in place for whoever asked next. That is the
> shape of the complaint: one song's extras will not load while the one
> before it loaded fine. The lyrics themselves no longer come this way
> at all (see _spicy_body), but everything else here still does.

### `Fetcher._index_batch`

**line 6706** — from the docstring, `def _index_batch(self) -> None:`

> One page of the lyrics held on disk per call, so the loop keeps
> serving lyric requests while a full index is being built.
>
> The songs it can offer are the ones Spicy Lyrics has been asked about
> from this machine. The API answers about one track and does not list
> its catalogue, so "every song in the cache" now means every song
> fetched here, and it fills up as things are played.

### `Fetcher._genius_match`

**line 6835** — from the docstring, `def _genius_match(self, hit: dict):`

> The Spotify track a Genius hit is about, or None if it is not clear.
>
> Genius names a song, Spotify holds the recording, and nothing joins the
> two but the words -- so this asks the catalogue for the name and keeps
> the track only if it really answers to it. A near miss played the wrong
> song, which is worse than saying so, hence the floor.

### `Fetcher._audio`

**line 6892** — from the docstring, `def _audio(self, tid: str, wait_ms: int = BEAT_WAIT_MS):`

> Audio analysis -- one round trip, and Spicetify memoises it per
> track inside the page.
>
> The one call here that waits on a promise the page has to fetch, so it
> is the one most likely to time out -- and the reason _drop matters:
> whatever it leaves behind is what the next read on that socket gets.
> `wait_ms` is how long the PAGE is given before it answers null. Asked
> from `_beat_for`'s thread, never the loop's.
>
> It dials if there is no socket yet, which it used to refuse to do --
> the analysis was an optional extra asked once the lyrics were already
> up, and paying a connect for it alone would have been the tail wagging
> the dog. Now it is asked the moment the track is, and it is this ask
> that makes the connection, since the lyrics no longer come through it
> at all. Refusing to make it is what left the FIRST track of a session
> with no visualiser until the words arrived -- measured at +462ms into
> a run, socket not yet up, the ask back in 0ms with nothing, and the
> wall dark for the whole walk.

### `Fetcher._grab_spotify_token`

**line 6897** — from the docstring, `def _grab_spotify_token(self) -> None:`

> Keep the desktop app's own access token, while Spotify is open.
>
> Only with Spotify lookup on, which the reader agreed to knowing this
> is what it does. Taken again once the kept one is within ten minutes
> of expiring -- Spotify gives them for about an hour and only the
> running app can renew one, so a kept token outlives the app closing
> by at most that long.

### `Fetcher._spotify_id`

**line 6909** — from the docstring, `def _spotify_id(self, tid: str) -> str | None:`

> The Spotify track a non-Spotify player's song is, or None.
>
> Only ever called with "Spotify lookup" on: it searches Spotify's
> catalogue through the desktop client, signed in as the reader, and
> that is theirs to allow. A match has to agree on the name, share an
> artist, and -- where both sides know it -- run within four seconds
> of the same length; anything less is no match, because the wrong
> song's sync is worse than the next source's.

### `Fetcher._spicy_body`

**line 6958** — from the docstring, `def _spicy_body(self, tid: str):`

> Spicy Lyrics' copy of a track, and whether the service answered.
>
> None with reached=True is the whole answer: Spicy Lyrics has nothing
> for this track, and nothing is what it will have until somebody
> uploads a sync. That used to be the uncertain case -- the copy came
> out of the Spotify page's own cache, which filled in behind the user
> while the song played, so "not there" meant "not there YET" and the
> window kept asking for half a minute. The API has no such state: one
> request, one final answer, and the ask is not made twice.
>
> reached=False is the service being unreachable, out of requests, or
> refusing the key. The caller falls through to the rest of the chain
> exactly as it does for any other source that is down, and the window
> says which one it was.

### `Fetcher._load_words`

**line 6987** — from the docstring, `def _load_words(self, tid: str, settled: bool = True):`

> The song's words, Spicy Lyrics first and then whoever else.
>
> Spicy Lyrics is a request like every other source's now, and its
> answer is final when it lands: what used to be here as well was a
> hold, a grace period and a watch, all of them waiting on the Spotify
> page's cache to finish filling in behind the user. There is nothing
> left to wait for -- the API has either got the sync or it has not --
> so the walk goes straight on to the chain when the answer is thin,
> and never comes back to ask again.

### `Fetcher._shaped`

**line 7074** — from the docstring, `def _shaped(self, body):`

> The document as it is drawn: unlumped, its ad-libs put back.
>
> The ad-lib repair is only run over a document that still has its
> ad-libs written into its lyric -- NetEase, QQ Music and Kugou, whose
> shape has nowhere else to put them, and any document that was
> line-synced until a donor lent it word timing. See LS.needs_adlibs().
> Everything else is handed on as its source wrote it, which is what
> keeps a Spicy Lyrics or amll document on this screen line for line the
> same as the one Spicy Lyrics draws itself.

### `Fetcher._uncensored`

**line 7089** — from the docstring, `def _uncensored(self, tid: str, body):`

> The letters a clean edit masked out, put back into the document.
>
> After _shaped and not before it: the walk reads the words out of the
> syllables, and until the unlump has run a syllable can be holding two
> of them. Handed back unchanged -- the very same object -- when there
> was nothing masked or nobody could fill it, because the window tells a
> new lyric from the one it is already drawing by identity, and a
> document that says exactly what the last one said should not cost a
> rebuild.
>
> Never on the interim: this goes to the network, and the interim's
> whole job is to reach the screen before anything does.

### `Fetcher._interim`

**line 7115** — from the docstring, `def _interim(self, tid: str, body, shaped: bool = False,`

> Show a document now, while a better one is still being looked for.
>
> Deliberately skips _duet: that goes to the network too, and the whole
> point of this emit is to reach the screen before any of that happens.
> The duet flags arrive with the final answer a moment later.
>
> `shaped` says the caller has already run _shaped over this one and is
> handing over the very object it means to keep -- see _load. The walk's
> own reports have not, and are shaped here.
>
> Never backwards. Every early answer for a track comes through here --
> the page's own copy, the last-known one that stands in while the walk
> runs, and each report the walk makes as a provider lands -- and each
> of those knows only what IT is worth, not what is already on screen.
> The stand-in is the one that showed: _load reads `have` off the page's
> body, so a track whose page could not be reached walks with a bar of
> "none" while a perfectly good stored document is up, and the first
> line-timed answer to land replaces it. It goes back at the end, when
> the walk's own pick lands, which is the flicker.
>
> Only from the newest walk (`no`, when the caller is not on the walk's
> own thread). An overtaken one's early answers are for a screen that
> has moved on, and letting them set the shown rank would hold the
> newer walk's next answer back as "backwards".

### `Fetcher._fallback`

**line 7243** — from the docstring, `def _fallback(self, tid: str, have: str, ahead=(), local=None):`

> Ask the other sources, in order, for something better than `have`.
>
> Whatever comes back first and beats what is on screen goes up while
> the rest are still being asked -- see the report callback below. The
> walk is ten providers wide now and only as fast as its slowest
> server; there is no reason to hold a good answer back for it.
>
> A source that could not be reached is passed up to the window rather
> than swallowed. The chain is built to carry on without any one of
> them, which is right, but it means a source the user ranked first can
> be quietly skipped for the length of an outage and the only evidence
> is somebody else's name under the lyric.

### `render_pieces`

**line 7287** — from the docstring, `def render_pieces(ln: dict) -> list[tuple]:`

> Timed fragments to lay out and fill for one line.
>
> Syllable lyrics already carry them. Line-level lyrics carry one blob of
> text, which leaves the wrapper nothing to break on -- long lines then run
> straight off the right edge -- so split into words and interpolate their
> timings, which also turns the fill into a word-by-word sweep.

### `_flat_group`

**line 7313** — from the docstring, `def _flat_group(run: list[tuple], widths: list[float], i: int, j: int,`

> How far run[i..j] drawn as one fragment strays from it drawn as many.
>
> What is compared is the thing on screen: the edge of the fill. The
> renderer moves it across a fragment by time fraction times the
> fragment's DRAWN width, so the edge of the split word is a line through
> each piece's (start, left) and (end, right), standing still through any
> gap, and the edge of the joined word is one straight line across all of
> it. Both are straight between those corners, so the corners are the only
> places they can be furthest apart.
>
> At each corner a seam is invisible if EITHER the edge is within `px`
> (in whatever units `widths` are: ems, from the view) of where it would have been OR it gets there within `tol` seconds
> of when it would have. A 60ms error on a word gone by in a flash moves
> the edge a fraction of a pixel; a 30ms one on a wide held syllable does
> not. `px` of 0 is the letter-count model, where pixels mean nothing.
>
> Returns the worst pixel error when the group passes, None when it does
> not.

### `_join_flat`

**line 7347** — from the docstring, `def _join_flat(run: list[tuple], tol: float, width=None,`

> One word's syllables, with the splits that tell us nothing taken out.
>
> A split earns its keep by changing what is drawn. If the word's fill
> would sweep across it the same -- within a pixel, or within `tol` in
> time, at every corner (see _flat_group) -- the split is only another
> fragment to lay out, wrap, cache, light and lift. The syllables of a
> joined group lift together; that is accepted, and only the fill judged.
>
> It is judged in the widths the renderer draws, from `width` (the lyric
> font's advance, in line heights). The old guess put each boundary by LETTER count, which
> is the fill's own rule only for a font where every letter is as wide as
> every other -- and a one-letter piece is exactly where they are not:
> "I" against "W", "i" against "ー". Without `width` (headless callers)
> it still counts letters, and time alone decides.
>
> No cap on how many are joined. The old letter test got easier the more
> of a word it was asked about -- equal letter counts put the guess on the
> midpoint -- so it was held to pairs. Comparing the whole drawn curve does
> not get easier with size, so an evenly-sung "ba·na·na" is one fragment,
> and the partition taken is the one with the fewest fragments, the
> smallest worst error breaking ties.
>
> A split the text SPELLS OUT is never joined -- "B-A-B-Y", "Oh-oh-oh":
> the reader can see where the word comes apart, and it should come apart
> there as it fills. Nor is a seam beside a piece with no letter or digit
> in it: no splitter guesses a standalone full stop, so "7.0" timed by
> hand is a person's own decision.

### `merge_flat_splits`

**line 7401** — from the docstring, `def merge_flat_splits(pieces: list[tuple], tol: float, width=None) -> list[tuple]:`

> Fragments with the uninformative splits taken back out.
>
> Word by word -- the last fragment of a word is the one NOT flagged as part
> of one, which is how everything else here finds word boundaries too. See
> _join_flat for what makes a split worth keeping; `width` is the drawn
> width of a piece of text, when the caller has a font to ask.
>
> Returns the list it was given, unchanged and uncopied, when the setting is
> off, so nothing about the default path is different from before.

### `retime_roman`

**line 7423** — from the docstring, `def retime_roman(ln: dict, text: str, _thin: bool | None = None) -> list[tuple]:`

> Hang a replacement romanisation on the line's real syllable timings.
>
> A Genius romanisation is one blob of text, so it used to go through
> render_pieces and get its timings by spreading the words evenly across the
> line -- which meant every corrected line filled at a constant rate instead
> of following the voice, and the fill drifted away from the original above
> it. The line already carries per-syllable times; the job is only to work out
> which syllable each piece of the new text belongs to.
>
> That is done letter by letter, not word by word. Genius writes 響いている as
> one word, "hibiiteiru", where the source times 響い / て / いる separately: as
> a single piece it fills at one flat rate across all three and visibly lags
> the original above it. Cut at the letters where the syllable changes and
> each fragment fills on its own syllable's clock, so the two lines stay in
> step. Fragments are marked part-of-word, so nothing is drawn any differently.

### `_level_of`

**line 7707** — from the docstring, `def _level_of(chip, tab: str, level: str) -> str:`

> What the column should mark one piece of the document with.
>
> The review page's own two filters, applied to the marks in the words: the
> tab says what is being read for, and `level` which weight of it. A
> catalogue's copy carries a zero-width space between every pair of words,
> so the difference between this reading the filters and ignoring them is
> the difference between a legible screen and an underlined one.

### `prepare`

**line 7729** — from the docstring, `def prepare(lines: list[dict], min_gap: float, merge: float = 0.0,`

> Clamp open-ended lines and insert interlude markers between the rest.
>
> `merge` takes the uninformative syllable splits back out of what gets
> DRAWN. It is applied to the pieces and never to `syls`, which stays the
> document's own account of itself: seeking, the redraw signature, the
> editor and everything exported still see every syllable the source timed.
> See merge_flat_splits. `width(text, background)` is the drawn width of
> some lyric text, so the merge judges what the fill really does.

### `LiveLink`

**line 7840** — from the docstring, `class LiveLink(QObject):`

> A loopback socket the TTML editor talks to.
>
> The point of it is that a file being timed can be watched against the
> real player, on the real track, without being saved, installed or
> dropped on the window again after every keystroke. It is the drop path
> with the file left out: the editor sends the document it currently has,
> this puts it on screen for the song that is playing, and nothing is
> written anywhere.
>
> Loopback only, and only ever four messages -- there is no reason for this
> to be reachable from another machine and no reason for it to grow a
> vocabulary. `state` is what the editor listens to: it needs the track and
> the play position the *player* believes in, complete with the offset this
> app applies, or every time it takes would be a few tenths out from what a
> listener actually hears.

### `LiveLink._accept`

**line 7876** — from the docstring, `def _accept(self) -> None:`

> Take the editor's connection -- and HOLD it.
>
> A socket handed out by nextPendingConnection was made by Qt, not by
> Python, and the only Python references to it used to be the lambdas
> wired to its own signals. That is a cycle nothing else points into,
> and Python's cycle collector is entitled to free it: the wrapper went,
> and with it every connection made through it. The socket itself stayed
> open underneath and went on filling its buffer, with nobody told --
> so this window stopped hearing the editor for the rest of the session,
> at whatever moment the collector happened to run. That is "it stops
> following at some point": seeking and editing only made it sooner, by
> giving Python more to allocate. One gc.collect() after the editor
> connects reproduced it every time.
>
> So each socket is kept in `_conns`, as the key to its own read buffer,
> until it closes.

### `LiveLink._watch`

**line 7939** — from the docstring, `def _watch(self) -> None:`

> Tell the editor when the song MOVES, rather than waiting to be asked.
>
> An editor polling this every tenth of a second is exact while the song
> plays -- both clocks run at 1x from the same instant -- and wrong for
> one poll after a jump, because it is still carrying the last reading
> forward through a seek that has already happened. One poll is 120 ms,
> and a time tapped inside it lands wherever the song used to be.
>
> There is no need to guess: this side knows the moment it happens.
>
> A word is still said every SAY_EVERY even when nothing has happened.
> The editor carries the last reading forward and will only do so for
> as long as it can believe it, so a state that stops arriving is a
> clock that stops moving over there -- see SpotifyPlayer.position.
> Two lines a second down a loopback socket costs nothing next to that.

### `LiveLink._read`

**line 7990** — from the docstring, `def _read(self, sock) -> None:`

> Whole lines only, and decoded only once they are whole.
>
> A reply is split across TCP segments -- a 90 KB document arrives in
> three -- and a multi-byte character lands across a boundary sooner or
> later. Decoding each chunk as it comes turned that character into
> U+FFFD, the row it was in stopped being JSON, and it was dropped
> without a word: the request simply timed out. Pure ASCII lyrics never
> showed it; Dutch, Korean and Japanese ones would.

### `_spread`

**line 8126** — from the docstring, `def _spread(marks: list, rufm, edge: float, gap: float = 2.0) -> list:`

> Push readings apart where they would sit on top of each other.
>
> A kana reading is narrower than the kanji under it and this never has
> anything to do. A Latin one is not: "gyeok" set over one Hangul block is
> most of the block's width, and two of them centred on neighbouring blocks
> touch. So each reading is nudged right off the one before it, and if that
> walks the last one off the end of the line the whole run is pushed back
> from the right -- which spreads the crowding over the row instead of
> piling it all up at the end.
>
> Each reading still starts as centred on its own characters, so where
> there is room nothing moves at all.
>
> It lives out here, next to nothing in particular, because that is where
> it was when the forced aligner was taken out: it sat directly under the
> Aligner's last method and went with the block, and nothing noticed until
> a song with readings was played, because ruby_rows is the only caller and
> it returns before this unless furigana is on AND the line has a reading.

### `Field`

**line 8149** — from the docstring, `class Field:`

> One line of editable text, drawn by hand.
>
> This window paints its own text boxes -- a QLineEdit laid over the lyrics
> would bring its own frame, palette and font with it -- so everything a
> text box does has to be written down once: where the caret is, what is
> selected, what the clipboard keys mean, and where the last frame put the
> characters, because a box that only ever gets painted has no other way to
> answer a click.
>
> `at`, `fm` and `rect` are filled in by the painter on every frame; see
> LyricsView._paint_field. A click arrives between frames and is placed
> against what was last drawn, which is the geometry the hand aimed at.

### `Field.index_at`

**line 8285** — from the docstring, `def index_at(self, x: float) -> int:`

> The gap between characters nearest this x, in the geometry the
> last frame drew.
>
> Measured on PREFIXES, because a prefix is what the painter advances
> by -- adding up one character at a time drifts from the drawn text
> wherever the font kerns. Found by halving, though, not by walking: a
> prefix is never shorter than a shorter one, so the widths are in
> order, and walking them measured the string once per character. That
> is a click costing 50ms on a long token and eleven seconds on a
> pasted page, which is most of what made a long paste look like a
> hang. The last few are still checked one at a time, so a kerned pair
> that makes one prefix a hair shorter than the one before it cannot
> put the caret in the wrong gap.

### `LyricsView.retune_frames`

**line 9130** — from the docstring, `def retune_frames(self, *_) -> None:`

> Settle the frame rate: the cap, or the refresh if that is slower.
>
> A fixed 16ms matches no real panel. On a 60Hz output it asks for 62.5
> frames the compositor will only present 60 of, and the leftover shows
> up in a word sweep as a stutter every few seconds. So the rate is
> `min(cap, refresh)` -- the refresh alone when the cap is 0 -- and where
> a whole divisor of the refresh lands on that (120 and 240Hz at a cap
> of 60, or 119.88Hz, which is 59.94) the divisor is used, so every step
> is the same length. Where none does (75, 90, 100, 144, 165Hz) the rate
> is the cap itself, flat: the compositor then shows some frames for two
> refreshes and some for three, which is what a cap under the panel's
> rate costs, and is the choice made over the 48fps that stepping down to
> the next whole divisor gave on a 144Hz panel.
>
> The rate never goes above the cap, which is what keeps the period
> longer than the coarse-clock grain -- see mono.
>
> Only the rate is settled here. The interval is not, because a whole
> number of milliseconds cannot express it -- see _frame.
>
> The screen is the one the compositor's callbacks have been heard
> coming from, where that is not the one Qt names -- see _listen.

### `LyricsView.showing`

**line 9213** — from the docstring, `def showing(self) -> bool:`

> Whether the frames being painted actually reach a screen.
>
> A wall-clock timer has no idea the window is gone: minimised, this went
> on painting the whole window sixty times a second and handing every one
> of them to the compositor. isExposed is the accurate answer under
> Wayland -- the compositor stops exposing a surface it is not showing --
> and the widget flags cover the platforms and the startup moment where
> it is not yet.
>
> Being covered by another window is NOT this. No compositor tells a
> client it has been occluded, so a buried window still reports itself
> exposed and still pays in full; only the damage itself could be made
> cheaper there.

### `LyricsView.frame_rate`

**line 9221** — from the docstring, `def frame_rate(self) -> float:`

> How often the next step is due: the full rate while anything moves,
> FRAME_STRETCH_HZ once nothing has for IDLE_STRETCH_AFTER, and
> FRAME_IDLE_HZ when the frames reach no screen at all.
>
> A settled window still ran its bookkeeping at the full rate, sixty
> times a second, to find nothing to do sixty times a second. What it
> finds is unchanged by the stretch, because easing only advances on a
> step that finds something moving. The cost is at most one stretched
> period before a change is noticed, and wake_frames takes that away for
> everything that comes from outside.

### `LyricsView._frame`

**line 9274** — from the docstring, `def _frame(self) -> None:`

> One animation step, then re-arm for the next one.
>
> Single-shot and re-armed against a deadline carried in float seconds,
> rather than left running at a fixed interval, because setInterval takes
> whole milliseconds and no whole number of them divides a real refresh.
> 59.913Hz wants 16.691ms; the 17 it used to be rounded to runs 1.09Hz
> slow, which lands as one duplicated frame every 0.92s -- exactly the
> stutter the divisor in retune_frames is there to remove, put back by
> the last line of it. Carrying the deadline forward keeps the long-run
> rate exact and leaves only sub-millisecond dither, which is well inside
> one refresh and so never reaches the eye.
>
> Except at the refresh itself, where it reaches the eye as judder. At
> 240Hz the deadline was met on average and missed on every frame: the
> timer is armed before the paint runs and fires in whole milliseconds,
> so frames went out 6.5, 4, 3, 3ms apart, over and over, to a panel
> that shows one every 4.17. A line sliding into place moved 6.9px in
> one frame and 3.2 in the next -- the vibration on every line change.
> There the compositor paces the frames instead; see _vsync_frame.

### `LyricsView.vsync_ok`

**line 9313** — from the docstring, `def vsync_ok(self) -> bool:`

> Whether the next step can wait for the compositor's frame callback.
>
> Wayland only: there QWindow.requestUpdate is answered from the frame
> callback, once per refresh -- measured at 239.65Hz, frames 4.0-5.2ms
> apart where the timer gave 2.2-9.5. Only at the refresh rate itself,
> and only while something moves: a cap below it, a settled window and
> a hidden one stay on the timer.
>
> And only after a step that asked for a frame (_idle_frames 0): one
> that drew nothing commits nothing, the compositor owes no callback,
> and Qt answers requestUpdate at once -- measured on a paused window,
> 20,000 steps in the second before the stretch, each counted a refresh.

### `LyricsView._vsync_frame`

**line 9330** — from the docstring, `def _vsync_frame(self) -> None:`

> One step on the frame callback, at the time the frame is SHOWN.
>
> The callback itself still arrives half a millisecond either side of
> the refresh, and every clock read in a step -- the springs, the
> easing, the song -- would carry that wobble onto the screen. But a
> frame drawn here is shown on a refresh, so the step is timed on the
> refresh grid instead: the last frame's time plus the whole number of
> refreshes since the last callback, never fewer than one -- a frame
> the compositor held for two refreshes counts two, and time never runs
> backwards. Measured 2026-10-02, the grid read 4.17 or 8.35ms a frame
> where the callbacks themselves arrived anywhere from 3.5 to 6.5. See
> frame_clock.grid_step for how it is kept near the wall clock.

### `LyricsView.ahead_ok`

**line 9344** — from the docstring, `def ahead_ok(self) -> bool:`

> Whether to draw a frame ahead -- see _ahead_frame. Only on the GPU
> canvas, whose swap is what waits. Fullscreen too: it started as a
> window-only fix, since fullscreen already had about 5ms, but there it
> took them from 92% of frames on time to practically locked at 240.
>
> 'auto' where it has been run (gpu_canvas.TESTED, as for GPU drawing),
> 'on' anywhere: on Windows and macOS a GL swap waits for the display
> too, which is all this needs, and where one does not the rate check
> in _ahead_frame gives it up.

### `LyricsView._ahead_frame`

**line 9365** — from the docstring, `def _ahead_frame(self) -> None:`

> One step as soon as the last frame has been swapped, for the
> refresh after the one it was swapped for.
>
> Measured 2026-10-02 at 240Hz, windowed, KWin composites about 2ms
> after it sends the frame callback, and a frame committed later than
> that waits a whole refresh: 31% of frames at 2-3ms, 60% at 3-4ms. Ours
> took 2.8, a step and a paint started AT the callback, so 40% of them
> slipped. Fullscreen there is about 5ms, which is why it was smooth.
>
> So the frame is made beforehand. The canvas's swap waits in Qt's GL
> for the frame callback of the frame before, so a frame painted now is
> committed the moment the next callback comes, already finished. It is
> shown a refresh later than one made at that callback, so it is timed
> a refresh later: the grid kept on the swaps, plus one period.

### `LyricsView.apply_gpu`

**line 9458** — from the docstring, `def apply_gpu(self) -> None:`

> Lay the GPU canvas over the window, or take it away, to match the
> setting -- see gpu_canvas. Once one has failed this session the CPU
> draws until the program is started again.
>
> The canvas has to be there BEFORE the native window is made. Qt
> settles a window's surface when it creates it, and a QOpenGLWidget
> added to one already up switches the QWindow to OpenGL -- but on KWin
> Wayland nothing it draws is ever presented. Measured 2026-10-02:
> paintGL at 60 a second, its framebuffer advancing, and the screen
> frozen on the last frame the CPU drew. So a change on a window that
> exists goes through _remake_window, which swaps the canvas while
> there is no native window at all.

### `LyricsView.resolve_font`

**line 9564** — from the docstring, `def resolve_font(self, online: bool = False) -> bool:`

> Settle on a family: the one asked for, else the first stocked one.
>
> Returns whether the requested name was actually found. Qt substitutes
> silently for a family it does not have, so a typo would otherwise look
> like the setting had simply been ignored.
>
> `online` allows one trip to Google Fonts for a name this machine does
> not have. Off by default so startup never waits on the network -- a font
> fetched once is cached and registered locally from then on.

### `LyricsView._weigh`

**line 9607** — from the docstring, `def _weigh(f: QFont, w) -> QFont:`

> Set a weight in both of the ways Qt needs to be told.
>
> setWeight alone is enough for an ordinary family, and enough for a
> single-axis variable file. On a multi-axis one -- Roboto ships as
> Roboto[wdth,wght] -- it collapses to two steps: 100 and 400 draw
> identically, and so do 700 and 900. Driving the wght axis directly gives
> the range back. Fonts without the axis ignore it.

### `LyricsView.lyric_font_key`

**line 9629** — from the docstring, `def lyric_font_key(self) -> str:`

> The lyric font as a string, for the drawn-line cache's key.
>
> The font is in that key by name rather than by emptying the cache when
> the family changes -- see line_pixmap -- which means serialising a
> QFont twice per visible line per frame. It is the same string every
> time until somebody changes the type, so it is worked out with the
> face and kept with it.

### `LyricsView._lyric_face`

**line 9634** — from the docstring, `def _lyric_face(self, background: bool):`

> (font, its name, its metrics) for the lyric type, memoised.
>
> Everything the face is built from is in the key -- the family, the
> size, the pinned weight -- so this cannot hand back a stale one and
> nothing has to remember to empty it. What it saves is the building: a
> QFont and a QFontMetricsF were being constructed forty thousand times
> over a forty-second sweep, all but a handful of them identical.
>
> The same object goes back to every caller. Nothing here mutates a font
> it was given -- the painters copy it, the metrics copy it, and the one
> place that wanted a bigger one takes a copy first.

### `LyricsView.on_reading`

**line 9653** — from the docstring, `def on_reading(self) -> None:`

> A reading has landed. Almost always there is nothing to do.
>
> The clock has already taken it -- that happened on the sampler's
> thread, under the lock -- and the words are drawn from the clock, so
> sixty of these a second would otherwise be sixty chances to do no
> work. The exception is a track change, which the rest of the window
> does have to hear about: the lyric on screen belongs to a song that
> has stopped playing, and waiting up to a quarter second for the next
> bookkeeping tick to notice is a quarter second of the wrong song's
> words. That was what the old 60ms poll near the end of a track was
> buying, and this buys it everywhere instead -- a track change reaches
> the window as fast as the clock sees one.

### `LyricsView.seek_song`

**line 9679** — from the docstring, `def seek_song(self, to: float) -> None:`

> Go to `to` in the song, whoever's copy of it that is.
>
> Following the TTML Editor's own audio, the words are drawn against
> the editor's clock, and a seek here used to move only Spotify -- which
> the editor then walked straight back, so clicking a line, dragging the
> bar or the arrow keys did nothing anyone could see. It is the editor's
> file that has to move: it is told to, and the words go there at once
> rather than after the round trip.

### `LyricsView.player_do`

**line 9694** — from the docstring, `def player_do(self, name: str) -> None:`

> Tell the player, and say so where it will not.
>
> Every one of these works on Spotify, so nothing ever had to report
> that a key had done nothing. Off Spotify they are not all there: a
> single video in a tab has nothing to skip to, and the desktop's
> bridge does not offer next and previous even where the page does --
> which is why the instruction is sent to whoever can take it before
> anybody gives up on it. See MprisTransport._able.

### `LyricsView.make_player`

**line 9715** — from the docstring, `def make_player(self) -> object:`

> The way in to the player, as the settings have it.
>
> `vetting` is set here rather than inside make_transport because it is
> a statement about the CALLER and not about the bus: this window can go
> and look a track up before showing it, so the transport is entitled to
> hold an unknown one back and wait to be told. Everything else that
> builds a transport -- the editor -- cannot do the looking,
> and gets the plain guess.

### `LyricsView.launch_spotify`

**line 9759** — from the docstring, `def launch_spotify(self) -> None:`

> With "Open Spotify" on, start Spotify through `spicetify auto`.
>
> Through Spicetify rather than Spotify's own launcher because that is
> what puts the debug port in its flags -- see mild-setup.py's
> spicetify_port -- and the port is how this window reads the player.
> Only when Spotify is not running at all: `spicetify auto` restarts a
> running one, and that would cut off whatever was playing. A Spotify
> already up without the port is said so instead.
>
> The transport is chosen at startup by whether the port answers -- so
> once it does, the player is rebuilt to take it (follow_players), here
> within a second and after that by watch_port.

### `LyricsView.check_debug_flag`

**line 9901** — from the docstring, `def check_debug_flag(self) -> None:`

> Say, as the window opens, whether Spotify's debug port flag is set.
>
> Read from Spicetify's own launch flags, which is where the port has
> to be: Spotify started any other way does not open it. Not set, a
> window says how to put it there
> -- the config file to open, the flag to copy -- because nothing else
> on screen would explain why the search, the queue and the visualiser
> are missing. Set, nothing is said: it would be a message on every
> start.

### `LyricsView.watch_port`

**line 9939** — from the docstring, `def watch_port(self) -> None:`

> Take Spotify's debug port up whenever it starts answering.
>
> make_transport only pairs the port with the platform's player when
> the port answers at startup. Spotify opened after this window, or
> slower to come up than _await_spotify waits for, left the window on
> the platform's stand-in for good -- "Windows media" in This song,
> with no Spotify track id and so no Spicy Lyrics. So while the player
> has no port in it, the port is asked every PORT_LOOK_MS, on a thread
> (a refused connect costs Windows seconds), and the player is rebuilt
> once it answers. What it said otherwise is kept for the Player row.

### `LyricsView.follow_players`

**line 9970** — from the docstring, `def follow_players(self, say: bool = True) -> None:`

> Take up the setting's new answer, mid-session.
>
> A rebuild rather than a flag flipped in place: with the setting on,
> the bus is a different player and the pair has to be wired differently
> for it -- see make_transport, and BackupTransport.handover. The old
> one is let go of afterwards, since a swap mid-reading leaves the
> sampler holding it for one more round trip.

### `LyricsView.vet_pending`

**line 9988** — from the docstring, `def vet_pending(self) -> None:`

> Look up a track another player is holding out, without showing it.
>
> The transport will not hand over a track off anything but Spotify
> until it is told the track is a song, and there are two ways to be
> told. The catalogue is asked first and answers first -- it is one
> request and it is being made anyway -- and a record it is sure of is
> the track vouched for outright; see on_card. The providers answer the
> same question with words, for a song no catalogue has; that one is
> fetched here exactly as the playing track would be, while the window
> goes on showing what it was showing, and lands in vet_answer.
>
> Not on every poll: the fetcher retries a track it found nothing for on
> its own backoff, and asking again on top of that would be a second
> walk for the length of whatever is playing. Not once and for all
> either -- see VET_AGAIN.

### `LyricsView.ask_lyrics`

**line 10008** — from the docstring, `def ask_lyrics(self, tid: str) -> None:`

> Put a held-back track to the providers, once.
>
> With whatever is known by now: the catalogue's spelling and the
> record's length where it answered, the player's own card where it did
> not. Called from vet_pending when there is nothing to wait for, and
> from on_card when there was.

### `LyricsView.want_card`

**line 10025** — from the docstring, `def want_card(self, tid: str, meta: dict, other: bool | None = None) -> None:`

> Ask a catalogue what a track looks like, for a player that cannot.
>
> Spotify says what is playing and hands over the cover it belongs to.
> A browser hands over a video's thumbnail -- sixteen by nine, the
> channel's lettering across it, and sometimes nothing at all -- and an
> album field with the site's name in it or nothing. Apple Music has
> the same song filed properly, and this app is already asking it about
> the words, so the cover comes out of a request it was making anyway.
>
> Only for the other players. Nothing is asked about a Spotify track:
> its card is already right, and a lookup could only make it wrong.
> `other` says whether this track is one of theirs, for a caller that
> knows -- a track being vetted belongs to a player that is NOT the one
> being followed, so the transport cannot be asked about it.

### `LyricsView.vet_answer`

**line 10090** — from the docstring, `def vet_answer(self, tid: str, lines, body=None) -> bool:`

> Words came back for a track being held out. So it is a song.
>
> The OTHER answer to that question is on_card's, which does not come
> through here: a catalogue sure of the record vouches for the track
> without waiting to hear whether anybody wrote its words down. This one
> is what still answers for a song no catalogue has heard of, and for
> one whose card came back with nothing to go on.
>
> True means this answer was about a track that is not on screen and has
> now been dealt with, so the caller should stop. A hit lets the track
> through -- the next reading a sixtieth of a second later carries it,
> poll() sees a new song, and the words are already fetched and cached
> by the time it asks for them.
>
> A miss is not final here: the fetcher goes on retrying a track it
> found nothing for, and the next answer comes back through this same
> door. What settles it is the video ending.

### `LyricsView.poll`

**line 10129** — from the docstring, `def poll(self) -> None:`

> Everything the window has to keep up with EXCEPT the clock.
>
> The player is not asked anything here any more -- the sampler does
> that, sixty times a second on its own thread, and this runs on the
> readings it has already taken. So `prev` cannot be read off the clock
> either: it used to be the value from before this method's own reading,
> and there is no longer a reading here to be before. It is the track
> this method last SAW, which is the same thing said in a way that does
> not depend on who took the reading.

### `LyricsView.record_artist`

**line 10483** — from the docstring, `def record_artist(self) -> str:`

> Who the record this track is on is by -- the animated cover's owner.
>
> The animation belongs to the album, EP or single, never to the track,
> and it used to be asked for under the TRACK's first artist. On most
> records the two are the same person; on a collaboration, a feature
> billed first or a compilation they are not, and each track on one
> record then went looking for a different animation -- a new search, a
> new download, and a cover that started again from its first frame at
> every track change, or that could not be found at all because Apple
> files the record under somebody else.
>
> The player's own answer where it gives one (Spotify's album artist,
> MPRIS's xesam:albumArtist, Windows' album artist); the track's lead
> artist where it does not, which is what it always was.

### `LyricsView._untimed_to_the_end`

**line 10566** — from the docstring, `def _untimed_to_the_end(self) -> None:`

> Move the untimed words a romanisation opens with onto the line before.
>
> Genius writes an ad-lib the file does not time at the head of the line
> it follows -- "(Dandan, da-da-dan) Hen ni iroke…" -- and drawn there it
> greyed out the start of a line that is about to be sung. It belongs
> after what came before it, where it is still untimed and still grey
> but no longer stands in front of the words. The first line keeps its
> own, having nothing before it.

### `LyricsView.line_readings`

**line 10589** — from the docstring, `def line_readings(self, lines=None) -> list[str]:`

> Current romaji per line, indexed to match self.lines (or `lines`: a coming song's).
>
> A line already in Latin script has no romanisation, and sending an empty
> string left a hole in the sequence Genius is aligned against -- so
> 「鬼とチャンバラ」+ "the lyrical chainsaw massacre", which Genius prints
> as one line, had only the first half to match on and fell under the
> threshold. Such a line is its own reading.

### `LyricsView.drop_echoed_adlibs`

**line 10707** — from the docstring, `def drop_echoed_adlibs(self, mapping: dict, lines=None) -> dict:`

> Take out a bracketed ad-lib Genius wrote into a line whose ad-lib
> the lyric already has as a background line of its own.
>
> God-ish has ユ! as a background vocal beside 「ドクター・キドリです…」, and
> Genius prints the pair as "(Yu) Dokutaa kidori desu…". Both got drawn:
> "(Yu)" at the head of the main line's romanisation and again under the
> background line, which reads it off its own text.

### `LyricsView.build_lines`

**line 10746** — from the docstring, `def build_lines(self, raw=None) -> list[dict]:`

> The timeline as it is actually drawn: interludes folded in, and the
> credits sitting under the last line the way Spicy Lyrics puts them.
>
> The credits ride as one more row rather than as chrome painted over the
> bottom of the window, so they scroll with the song and stop where it
> stops. Empty `text` on purpose -- every place that walks the lines
> looking for something to copy, search, seek to or correct already skips
> a row with no words in it, so none of them need to learn about this.

### `LyricsView.timeline_of`

**line 10809** — from the docstring, `def timeline_of(self, body):`

> A parsed document as drawable lines, split the way the app is set.
>
> The syllable-splitting settings live on the FETCHER, not here -- it is
> the thing that was given them at startup and the thing that normally
> builds timelines. Reading them off `self` silently raised
> AttributeError inside the two `except Exception` blocks below, so a
> dropped file reported "could not read that file" whatever was in it.

### `LyricsView.show_dropped_lyric`

**line 10815** — from the docstring, `def show_dropped_lyric(self, path: str) -> bool:`

> Put a lyric file from disk on screen -- TTML, or any format
> lyric_formats reads -- and keep it for this track.
>
> It is kept on disk and put back the next time the song comes round
> (see restore_dropped). R takes it off, which is the same gesture that
> already means "that answer was wrong, go and ask again".

### `LyricsView.restore_dropped`

**line 10842** — from the docstring, `def restore_dropped(self) -> bool:`

> Put the file dropped on this track back up, on coming back to it.
>
> Asked outside the running order on purpose: a dropped file is not a
> source competing for the song, it is what was on screen last time.
> It goes up the way it did the first time, marked dropped, which keeps
> the chain's own answer from drawing over it.

### `LyricsView.show_live_lyric`

**line 10863** — from the docstring, `def show_live_lyric(self, xml: str, name: str = "the editor") -> bool:`

> A document pushed over the live link, shown the way a drop is.
>
> Quiet on purpose: this arrives on every edit, and a toast per
> keystroke would cover the words being edited. The one thing it does
> say is when it could not read what it was sent, because an editor
> that has stopped updating the screen and an editor whose file no
> longer parses look identical from the other end.

### `LyricsView.show_live_lyric_soon`

**line 10874** — from the docstring, `def show_live_lyric_soon(self, xml: str, name: str = "the editor") -> None:`

> show_live_lyric with the reading done off this thread.
>
> Reading a pushed song was 12-13ms here, every push -- up to five a
> second while tapping, three dropped frames each at 240Hz. A thread
> alone still held the GIL for ~5ms a push, so the reading goes to the
> offload pool; it can wait behind a long job there (a Genius
> alignment, once a song). Only the newest push waits: one arriving
> while another is read replaces it.
> A document that cannot be read is said here and to the editor
> ("push-failed"), a moment after the push was answered.

### `LyricsView.auto_review`

**line 10948** — from the docstring, `def auto_review(self, why: str = "") -> None:`

> Start reviewing, the way the settings say to, unless it already is.
>
> For "Review when the TTML Editor opens" and "Review when a TTML is
> loaded": a document from outside is one being worked on, and the
> review is the screen for that -- turned on here so it does not have
> to be remembered every time.

### `LyricsView.live_shown`

**line 10965** — from the docstring, `def live_shown(self) -> bool:`

> Whether the words on screen came from outside -- the editor, or a
> file dropped on the window -- for the track that is playing.
>
> The editor's copy counts with no track at all. Timing against a file
> on disk, the player may have nothing playing, and its document is
> then pinned to no track id; asked as `dropped == tid` alone, that
> read as "yes" before anything had been pushed.

### `LyricsView.editor_position`

**line 10971** — from the docstring, `def editor_position(self, now: float | None = None) -> float | None:`

> Where the editor's own audio is, as this window's clock, or None.
>
> Only while the editor's document is on screen and the editor is still
> saying where it is. Carried forward from the last message at the
> speed the file is playing at, the same way the clock carries a
> reading forward from the player.
>
> This is what the words are drawn against while a file is being timed
> against a local copy of the song, instead of Spotify walked along to
> match it. Walking Spotify is still done -- see follow_editor -- but it
> was never going to be close enough to draw by: it is kept within
> FOLLOW_DRIFT, a third of a second, lags every seek by a round trip,
> cannot play at the editor's half speed, and is not there at all when
> Spotify is not running or is playing another song.

### `LyricsView.follow_editor`

**line 10993** — from the docstring, `def follow_editor(self, pos: float, playing: bool,`

> Walk Spotify along with the editor's own copy of the song.
>
> Somebody timing against a local file is watching THIS window draw
> their document -- and this window draws against Spotify's clock. So
> the words they had just placed swept past at whatever point Spotify
> happened to be sitting at, which is usually nought and sometimes
> another song entirely: the one screen that was supposed to show them
> their work in place was the one screen that could not.
>
> So Spotify is put where their file is and kept there: seeked when
> it drifts more than FOLLOW_DRIFT -- see _follow_to -- playing while
> their file plays, paused when they pause. Muted the whole time it is
> playing, because two copies of one song a fraction of a second apart
> is not something anybody can time against, and unmuted once it has
> actually stopped, so what is handed back is a player sitting where
> they are, audible.
>
> Only while their document is the one on screen. The editor sends this
> only when it is timing against a local file, but "there is an editor
> attached" is not on its own a reason for this window to take hold of
> somebody's playback.
>
> THE WORDS DO NOT WAIT FOR SPOTIFY. The position is kept as a clock of
> its own and drawn against directly -- see editor_position -- so what
> is walked here is only the rest of the window: the progress bar, the
> visualiser. Spotify is walked where there is a Spotify to walk, and
> left paused at the place while the file plays at another speed,
> because a muted copy racing ahead at 1x only earns a seek every
> FOLLOW_AGAIN.
>
> And never off the end of its own track. The file being timed is often
> not Spotify's cut -- a few seconds longer, an extended mix -- and past
> Spotify's end is Spotify's NEXT song: a track change, which drops the
> editor's document, which the editor pushes back, which the next seek
> skips again. So within FOLLOW_END of the end Spotify is parked, paused
> where it is, and the words go on by the editor's clock. It stays muted
> while parked with the file still playing -- unmuted only once the
> editor itself has stopped -- or every seek in and out of that last
> stretch would say "muted" and "unmuted" once each.

### `LyricsView._follow_to`

**line 11041** — from the docstring, `def _follow_to(self, want: float) -> None:`

> Put the player where the editor's audio is -- rationed, and not
> for ever. One seek every FOLLOW_AGAIN, and a place that will not be
> reached let go of after FOLLOW_TRIES.
>
> WHAT COUNTS AS A REFUSAL is the whole of this. A seek is not answered
> the instant it is sent: it goes out, the player moves, and the
> position read here catches up a poll or two later -- longer than
> FOLLOW_AGAIN, comfortably. Counting every seek SENT as a try that
> failed therefore ran the count out on a player that was behaving
> perfectly, and the way to see it is to nudge a timestamp: each nudge
> asks for somewhere a few hundredths further on, none of them far
> enough from the last to read as a new place, and four of them in a
> row spent the budget. What followed was a stretch of the editor being
> ignored -- until the nudges added up to more than FOLLOW_DRIFT, which
> started the count again, and then stopped it again four nudges later.
> Timing a line, which is small nudges and nothing else, is exactly the
> case it broke on.
>
> So a try is only a failure where the player has NOT MOVED since the
> last one: a player travelling towards where it was sent is following,
> however far behind the count it is.
>
> And giving up is giving up for FOLLOW_REST, not for good. The editor
> goes on saying where it is several times a second; something that has
> stopped listening to that has to have a way back, or a single bad
> minute -- the player buffering, a track loading -- costs the rest of
> the session. Said once per stretch of not following, though: the
> toast belongs to the first refusal, not to every retry.

### `LyricsView.volume_from_editor`

**line 11109** — from the docstring, `def volume_from_editor(self, v: float) -> None:`

> The editor's volume slider, timing against Spotify.
>
> Through here rather than straight to Spotify, because this window may
> be holding Spotify muted under the editor's own file -- then the new
> level is the one it will be unmuted TO, and setting Spotify directly
> would either be muted again on the next follow or unmute it mid-take.

### `LyricsView._mute_for_editor`

**line 11119** — from the docstring, `def _mute_for_editor(self) -> None:`

> Silence Spotify, remembering what it was set to.
>
> Its own volume, not the system's: this is the one knob that belongs
> to the player rather than to whatever else is making noise, and it is
> put back exactly as it was. Where the transport carries no volume at
> all -- Windows' media controls do not -- nothing is muted and nothing
> is claimed to have been.

### `LyricsView.check_editor_gone`

**line 11140** — from the docstring, `def check_editor_gone(self) -> None:`

> Hand the playback back if the editor walking it has gone quiet.
>
> Closed on a crash, its socket dropped without a word, its checkbox
> turned off by somebody who then went to lunch. It says where it is
> several times a second while it means it, so silence for FOLLOW_GONE
> is silence for good -- and a muted player running on by itself is the
> one state nobody asked for.

### `LyricsView.unfollow_editor`

**line 11149** — from the docstring, `def unfollow_editor(self, pause: bool = True) -> None:`

> Give the player back. Called when the editor says it has stopped,
> when it goes away without saying, and when the track changes under it.
>
> Paused as well as unmuted where this window is what set it playing:
> an editor that has closed is not timing anything, and a muted song
> running on by itself is the one state nobody asked for.

### `LyricsView.drop_live_lyric`

**line 11164** — from the docstring, `def drop_live_lyric(self) -> None:`

> Let go of the editor's document and put the song's own back.
>
> The asking matters as much as the letting go. Clearing `body` only
> says what is NOT on screen; nothing then goes and gets what should
> be, so the song sat with no lyrics at all until the track changed --
> which is what the editor closing, or its checkbox being turned off,
> looked like from here. reset_track has always re-requested; this is
> the same request, for the track that is already playing.

### `LyricsView.reset_track`

**line 11213** — from the docstring, `def reset_track(self, status: str, keep: bool = False) -> None:`

> Start this track's lyrics again, and say what is being waited for.
>
> `keep` is the same song asked for a second time -- R -- rather than a
> new one, and it leaves the words where they are. Blanking them means
> the window shows nothing at all for as long as the answer takes, and
> the answer is not always the page read it ought to be: one wedged
> socket, one provider on a long timeout, and a reload of a song whose
> document is sitting in the page a tenth of a second away is ten
> seconds of "Reloading…" over an empty screen. What is on screen is
> this song's lyric until a better one lands, so it stays up and is
> replaced rather than removed first; see on_lyrics, which takes an
> empty answer over it once the fetcher says it has finished asking.

### `LyricsView._load_art`

**line 11252** — from the docstring, `def _load_art(self, url: str) -> None:`

> Runs off the GUI thread, so it may only touch QImage -- QPixmap is
> documented as main-thread only and crashes under some Qt backends.
>
> The url it was fetching goes back with the picture, because by the
> time it lands it may not be the picture anybody wants; see on_art.
> None goes back where there is no picture, for the same reason: a
> failure nobody is told about is a failure nobody retries.

### `LyricsView.on_art`

**line 11270** — from the docstring, `def on_art(self, url: str, triple, dropped: bool = False) -> None:`

> A cover to draw. `dropped` means it came off the window, by hand.
>
> ONLY IF IT IS STILL THE COVER BEING ASKED FOR. Every track change
> starts a download of its own on a thread of its own, and they finish
> in whatever order the network hands them over -- so skipping quickly
> through three songs raced three downloads, and whichever one happened
> to land LAST won, however long ago the song it belonged to had gone.
> The cover on screen was then somebody else's album, and so were the
> two things drawn out of it: the blurred plate behind the words, and
> the palette every other colour in the window is lifted from. That is
> why an animated cover taking the picture's place did not put it right
> -- the picture was only one of the three, and the other two are the
> background.
>
> `art_url` is what the last track change asked for, so a picture that
> does not answer to it is a picture for a song that is no longer
> playing. The same guard on_motion has always had, one signal along.
>
> A picture dropped on a song holds until the song changes -- including
> against the cover this app is still downloading for it, which used to
> arrive a moment later and quietly put itself back.

### `LyricsView.on_motion_look`

**line 11291** — from the docstring, `def on_motion_look(self, key: str, look) -> None:`

> What the animated cover's wall is drawn from, for the record it is.
>
> The wall, the palette and the wash used to come off the STILL cover
> whatever was playing in its square, and the two are often not the
> same picture: an animation is its own artwork, a different crop or a
> different colour altogether, and the window framed it in the still's.
> One frame from the middle stands for all of them -- the first is
> usually the still again, and following every frame would pulse the
> whole window thirty times a second.

### `LyricsView.nudge_offset`

**line 11320** — from the docstring, `def nudge_offset(self, delta: float) -> None:`

> [ and ] tune the TRACK you are listening to. A song that is mastered
> a little late needs its own correction, not a global one that then
> breaks every other song.
>
> Correcting a track by hand also retires the measured offset for it. Not
> because the measurement was wrong, but because it has been superseded by
> somebody who can actually hear the song, and two corrections stacking on
> one track would be twice the intended fix. The measurement is kept --
> it is still what the menu shows -- but clearing the track (0) retires
> it too (clear_measured).
>
> A hand correction of ZERO is one of those statements and is kept as
> one. It used to be deleted as if it had never been made -- which
> handed the track straight back to the measured offset it had just been
> tuned off, and made any track whose measurement is an exact multiple
> of the step impossible to tune past: BABY I'M BACK measures +0.05,
> every press of [ landed on 0.00, the entry was dropped, +0.05 came
> back, and the offset sat at -0.05 (with a -0.10 global) however many
> times the key went down. Clearing a track and setting it to nothing
> are different requests, and 0 is the key that does the first.
>
> A press that ARRIVES at the measurement takes it. The gates in
> auto_offset throw out most readings, and plenty of the thrown-out
> ones were right: tuned by ear, the track lands a step short of or a
> step past the very number that was ignored. Landing within EST_EAR of
> it, the same way round, is the ear agreeing with the reading -- and
> the reading is the finer of the two, since the ear only moves in
> steps -- so the measured value is what gets kept. See
> heard_as_measured for what does not count.
>
> Only arriving, never leaving: a press made FROM the measured value,
> whether auto_offset applied it or an earlier press took it, is a
> statement that it is wrong, and snapping that back onto it would make
> the key do nothing. Nor from a correction already inside the band,
> which would turn a step into a two-hundredths shuffle.

### `LyricsView.heard_as_measured`

**line 11347** — from the docstring, `def heard_as_measured(self, tid: str, hand: float) -> float | None:`

> The measured offset, where a hand correction of `hand` says it was
> right; None where it does not.
>
> Right means within EST_EAR of it AND the same way round. The second
> is not implied by the first near zero: a reading of +0.02 and a
> correction of -0.03 are close, and are the ear saying the lyrics were
> early where the reading said late. A correction of exactly zero
> agrees with nothing -- it is the track being put back, not moved.
>
> None of auto_offset's gates apply, because this is the check they
> stand in for. They exist to guess, with nobody listening, whether a
> reading is one of the badly wrong ones; somebody listening has just
> answered that. What still does not count is a reading railed at the
> edge of the search, which is not an offset but the place the search
> stopped looking -- and auto timing switched off, which is a request
> not to be moved by measurements at all.

### `LyricsView._watch_device`

**line 11360** — from the docstring, `def _watch_device(self) -> None:`

> Which output the sound is coming out of, asked off the GUI thread.
>
> Two short subprocesses per look, which is two too many for the thread
> that draws. Polled rather than subscribed to: pactl will hold a
> subscription open, but that is a process kept alive for the life of
> the window to learn something that changes when somebody picks up
> their headphones.

### `LyricsView.offset_key`

**line 11373** — from the docstring, `def offset_key(self) -> str:`

> Which standing offset applies here: the output, and who is playing.
>
> TWO REASONS THE SAME SONG ARRIVES LATE, and they are independent.
>
> The output is the one this was built for: a headset two hundred
> milliseconds behind the monitor it was tuned on is not the lyrics
> being wrong, it is the sound having further to go.
>
> The PLAYER is the other, and it is what the any-media-player setting
> made reachable. Spotify's clock and a browser's do not sit the same
> distance from their own sound: the browser publishes a position it
> rounds to the second, through a pipeline of its own, and whatever
> standing difference that leaves is a property of the program and not
> of the speaker it comes out of. Tuning YouTube by ear used to move
> Spotify with it, on the same headset, because there was one number
> for the pair -- so the two could not both be right and the second one
> tuned undid the first.
>
> The key is the pairing. Written player-first so a settings file reads
> as what it is -- `firefox@alsa_output.usb-046d_G435.iec958-stereo` --
> and a bare output name, which is every settings file written before
> this, is still a key: see _swap_offset, where it is what a player
> heard for the first time on a known output starts from.

### `LyricsView._swap_offset`

**line 11380** — from the docstring, `def _swap_offset(self, was: str) -> bool:`

> Put the live offset away under `was` and take out the one for now.
>
> Answers whether the number actually moved, which is not the same
> question as whether the pairing changed: whoever is playing can flip
> back and forth in a silence, and a toast per flip is chatter about
> nothing. See on_player.

### `LyricsView.on_player`

**line 11398** — from the docstring, `def on_player(self, app: str) -> None:`

> Somebody else is playing; take their own standing offset out.
>
> The same swap on_device makes, for the other half of the key. Called
> off poll() rather than watched for: it is a string already on the
> transport, and reading it costs nothing next to the two subprocesses
> the output costs.
>
> Said out loud only where the number MOVED. An output changing is
> worth a line whatever it does to the timing -- see on_device, the
> number now belongs somewhere else and that is worth knowing -- but
> who is playing flips about on its own in the silences between songs,
> and a toast on each of those is noise about nothing that changed.

### `LyricsView.on_device`

**line 11409** — from the docstring, `def on_device(self, dev: str, name: str) -> None:`

> The sound has moved to another output; take its timing with it.
>
> A headset two hundred milliseconds behind the monitor it was tuned on
> is not the lyrics being wrong, it is the sound arriving late -- and
> the correction for that belongs to the device. It is the same song,
> the same document and the same window; the only thing that changed is
> how far the audio has to travel. So the global offset is kept per
> output and swapped when the output does, while the per-track
> corrections and the measured ones -- which are statements about the
> LYRIC -- carry over untouched.
>
> An output heard from for the first time inherits whatever is set now
> rather than snapping to zero. It is a guess, but it is the guess that
> changes nothing, and the first nudge on it writes the real number.
>
> The output is half the key now, not the whole of it -- see offset_key
> for the other half and why it is there. Nothing about THIS method's
> behaviour changed with it: what is put away and what is taken out are
> the same two acts, against a key that also names whoever is playing.

### `LyricsView.device_offsets`

**line 11425** — from the docstring, `def device_offsets(self) -> dict:`

> Every output's offset, with the one in use kept up to date.
>
> The live value lives in `offset` -- the menu, the keys and the reset
> all write there and know nothing about outputs -- so it is folded in
> here rather than mirrored on every path that could touch it.
>
> Every OTHER key is written back exactly as it was read, bare output
> names included. Those are what a player heard for the first time on a
> known output starts from (see _swap_offset), so dropping them because
> nothing writes them any more would throw away the tuning that is the
> whole reason somebody has a settings file with offsets in it.

### `LyricsView.sync_origin`

**line 11434** — from the docstring, `def sync_origin(self, doc: dict) -> str:`

> Which sync this is: where it came from, and who made and uploaded it.
>
> A hand correction is a statement about one sync of a song, not about
> the song. Two people timing the same recording land in different
> places, and a blend is out by however its donors were, so the +0.15
> that put one copy dead on pushed the next one off -- and nothing said
> which copy it had been tuned against.

### `LyricsView.hand_key`

**line 11442** — from the docstring, `def hand_key(self, tid: str | None = None) -> str:`

> Where this track's hand correction is kept for the sync on screen.
>
> `tid@origin` -- see sync_origin. A correction from before that, under
> the bare track id, does not say which sync it was made against, so it
> goes on applying to whichever is up until the track is tuned again,
> and that tuning moves it to the sync it was tuned on. Taking a guess
> at its owner sooner would pin it on the stand-in that is drawn while
> the real lyric is looked for, as often as not.

### `LyricsView.auto_offset`

**line 11469** — from the docstring, `def auto_offset(self, tid: str, key: str | None = None) -> float:`

> The measured correction for a track, or 0.0 where there is none to
> apply -- no reading, not a confident one, or nothing to calibrate it
> against yet. A hand correction on the track beats all of it.
>
> The gates are doing real work here and are deliberately strict. A wrong
> offset applied silently is worse than no offset at all: the lyrics were
> merely out before, and now they are out and the program is insisting
> otherwise. Three of them, asking three different questions -- was the
> reading clear (conf), did the song say the same thing twice (spread),
> and is the answer a size a lyric sheet is ever actually out by
> (EST_MAX) -- because the readings that are badly wrong pass the first
> one comfortably. See EST_MAX.
>
> The reading is applied as it stands. There used to be a calibration
> subtracted from it first, worked out from the tracks that had been
> tuned by hand -- see the note where calibrate() was, which is about why
> those tracks could not answer the question they were being asked. What
> it also did, while it was there, was gate this: with fewer than five
> hand-tuned tracks carrying a reading the answer was 0.0 whatever the
> measurement said, and a fresh install has none, so the feature could
> not start working until somebody had tuned five songs by ear that it
> had also happened to measure. Nothing said so except a line in a menu.

### `LyricsView.measure_offset`

**line 11482** — from the docstring, `def measure_offset(self) -> None:`

> Read this track's timing against Spotify's analysis of it, once.
>
> Both halves have to have arrived -- the lines and the analysis land from
> different requests on different threads -- so this is called from both
> and does nothing until it has the pair. The result is cached against the
> track id, so it survives a pause, a scrub, and the next thousand frames.

### `LyricsView.track_offset`

**line 11546** — from the docstring, `def track_offset(self) -> float:`

> Global offset plus whatever this particular track needed.
>
> The per-track part is the hand correction where there is one and the
> measured one otherwise -- never both, or a track fixed by ear would be
> fixed twice. auto_offset() enforces that; this stays a plain sum so that
> everywhere already subtracting it keeps working unchanged.
>
> A document that is not this song's own gets the global offset and
> NOTHING else -- one pushed over the live link from the editor, or
> dropped in as a file. Both of those are somebody timing a lyric
> against this recording and watching the result here, and both
> per-track corrections are statements about a DIFFERENT document: the
> hand one says how far the song's own lyric sits out, the measured one
> was read off it. Applying either to a lyric being written puts the
> editor and the player at different times for the same file, so a
> syllable placed dead on lands late on screen -- and the writer then
> corrects for a shift the file does not contain, baking it in.

### `LyricsView.on_fetched`

**line 11625** — from the docstring, `def on_fetched(self, tid: str, lines, body) -> None:`

> A lyric answer off the fetcher. Two questions it could be about.
>
> Nearly always the song on screen, and those go straight through. The
> other kind is a track some other player is holding out, looked up only
> to find out whether it is a song at all -- that answer is taken by
> vet_answer and never drawn. It is caught HERE rather than in
> on_lyrics, which is the window putting words up and is called by
> everything that has words to put up.

### `LyricsView.lyric_key`

**line 11924** — from the docstring, `def lyric_key(lines) -> list:`

> What a document draws, as plain values.
>
> Taken as the lines ARRIVE, before prepare() fills each of them in --
> it clamps an open end and hangs the laid-out pieces on the same dicts,
> so `raw` a moment later no longer equals the list it was made from and
> cannot be compared against the next one.
>
> `pieces` are left out for the same reason and a better one: they are
> derived from the timings already here, so a document that agrees on
> every start, end and syllable cannot disagree on them.

### `LyricsView.same_lyric`

**line 11932** — from the docstring, `def same_lyric(self, lines, body) -> bool:`

> Whether an arriving answer draws exactly what is on screen already.
>
> Asked of the LINES, not of the document. The document cannot answer
> it: the same lyric reaches here as a different object every time --
> the walk reports a copy of what it is about to return, _shaped builds
> a repaired document rather than editing one, and every re-read of the
> page hands back a freshly parsed dict. Comparing those by identity
> said "new lyric" to every one of them, and a new lyric costs the whole
> screen: every line laid out again, every pixmap dropped, the offset
> measured again on the drawing thread. Three handovers on an ordinary
> song, two of them drawing what was already there.
>
> The lines are what gets drawn, so they are the honest question, and
> they are cheap to ask it of -- a tuple per line, against a re-layout
> of the window.

### `LyricsView.song_title`

**line 11965** — from the docstring, `def song_title(self) -> str:`

> The title with its guest credit taken out.
>
> "(feat. AzChike)" is not part of the song's name, it is a credit that
> happens to be written in the name field -- and it is already shown, in
> full, on its own line underneath. Left in the title it is said twice,
> and it is the half of the title most likely to push the rest out of the
> box. Removed only when it was actually understood: if nobody came out
> of the parse, the title stands as written.

### `LyricsView._hot_names`

**line 11974** — from the docstring, `def _hot_names(self, people, rect: QRectF, fm, prefix: str = "",`

> One clickable region per artist on a line of "A, B" names.
>
> The line is drawn as one string, and it used to be one region
> pointing at whoever was first -- so a click (or a middle click) on
> the second artist opened the first. Each name is measured where it
> actually lands: after `prefix` ("feat. ", "with ") and centred the
> way the text is when it fits. True if the mouse is over one.

### `LyricsView._said_language`

**line 12004** — from the docstring, `def _said_language(self, doc: dict) -> str:`

> What language this is.
>
> The ANSWER, not the argument. Providers guess this and guess it wrong
> the same way every time -- an English lyric filed under a small
> Latin-script code -- and showing "pcm (reads as en, the words are
> English)" put the wrong code first and made a plain fact into a
> paragraph. The panel says en, because it is en.

### `LyricsView.source_name`

**line 12019** — from the docstring, `def source_name(self, doc: dict) -> str:`

> Where the lyrics on screen actually came from.
>
> The catalogue, never the door: a document fetched through a proxy that
> holds several catalogues is its catalogue's, and naming the proxy
> instead left the reader no wiser about who wrote the words. The
> upstream is still printed where it says something the name does not --
> a blend reports its whole makeup -- and dropped where it only repeats
> it.
>
> Where the words and the clock come from different places the label says
> both. A NetEase-timed document used to report as plain "Spicy Lyrics",
> which credits the half of it that could not do the thing you are
> watching it do.

### `LyricsView.made_by_linked`

**line 12075** — from the docstring, `def made_by_linked(self, doc: dict, gap: str = "") -> tuple:`

> The same line, and the pages the names in it point at.
>
> Spicy Lyrics distinguishes the person who made the sync from the person
> who uploaded it, and often only knows the second -- Maker comes back as
> an empty {} on two thirds of the community entries here. Its own UI
> credits the uploader as the maker in that case, which is the right call:
> with nobody else named, they are who made it, and "uploaded by" credits
> them for less than they did.
>
> Each of them carries the address of their own page, and the credit is
> required to LINK there rather than only name them -- that is section 6
> of the terms this lyric arrived under, not a flourish. The link is
> [(the words to underline, where they go), ...]; a contributor with no
> page of their own contributes no entry, which is everybody the other
> sources credit, and is why this comes back empty rather than dead.

### `LyricsView.credit_rows`

**line 12101** — from the docstring, `def credit_rows(self) -> tuple:`

> The block that sits under the last line: who wrote the song, where
> this copy came from, and who timed it -- in that order.
>
> Two lists, the second one the shape of the first: for each row, the
> stretches of it that are links and where they lead. Empty for every
> row that has none, which is most of them. What is linked is what the
> sources asked to have linked -- a Spicy Lyrics contributor's own page,
> and Unison's address, which was already written out in full here and
> is now worth clicking as well as reading.

### `LyricsView.roster`

**line 12183** — from the docstring, `def roster(self) -> LS.Roster:`

> Whose syncs to refuse and whose to prefer, as the chain wants it.
>
> Built fresh rather than kept, for the same reason source_order() is:
> both lists can change under a menu row or a key while a walk is out,
> and the walk that has already been handed one is the walk that should
> finish under it.

### `LyricsView.judge_sync`

**line 12200** — from the docstring, `def judge_sync(self, prefer: bool) -> None:`

> Refuse or prefer whoever timed the document on screen.
>
> The credit line under the lyrics is where anybody forms this opinion
> -- you read a name, and you know whether their syncs have been good --
> so the two lists can be written from there without typing it out and
> without spelling it the way the settings file wants. It is also the
> only route by which a Spicy Lyrics id ever reaches the lists: the
> document has it, the credit line does not print it, and nobody could
> type it. Written from here, the entry goes on meaning this person
> after they rename themselves; typed into the settings row, it means
> whoever is called that until a playing song is synced by them, and
> that account after. See on_people_met and LS.answers_to.
>
> Pressing it again on somebody who is already on the list takes them
> off, because there is nowhere else to undo this from with the
> document in front of you.

### `LyricsView.judge_into_edit`

**line 12231** — from the docstring, `def judge_into_edit(self) -> None:`

> This sync's maker into the line being typed, or out of it again.
>
> The one thing typing cannot do, which is why the button is here and
> not only on the K keys: a Spicy Lyrics id is in the document and is
> printed nowhere, so a name reaching the list this way brings the id
> with it and goes on meaning this person after they rename themselves.
> The ids ride in `edit_ids` until the box is saved -- the line itself
> is names, because a line of ids is not something anybody can read.

### `LyricsView.set_people`

**line 12249** — from the docstring, `def set_people(self, key: str, names, knew=()) -> None:`

> Write one of the two lists and act on it now, not next track.
>
> The song on screen is the one the user is making this decision ABOUT
> -- they have just read a name under the lyrics and had an opinion
> about it -- so the ask goes out again straight away. It is not a
> second walk in practice: the chain's stored answer is keyed by the
> roster it was picked under (see LS._store), so this re-walk is the
> first ask of a question that has just changed, and every other track's
> answer is still on the disk where it was.
>
> Whatever ids the old list had are carried onto the new one, because
> the settings row hands this a line of typed text and typed text has
> no ids in it -- see LS.with_ids. Fixing a spelling should not quietly
> turn a refusal that follows somebody through a rename into one that
> does not.

### `LyricsView.on_people_met`

**line 12267** — from the docstring, `def on_people_met(self, tid: str, met: dict) -> None:`

> Give typed entries the id of whoever they turned out to mean.
>
> A name typed into the settings row has no id, and nobody could type
> one; it matches by name until the walk for a song that is PLAYING
> meets somebody of that name who has an id -- a walk ahead does not
> count -- and from then on it is that account. See LS.answers_to.
>
> Two accounts behind one name in the same walk are settled by the
> document on screen where it credits one of them, and otherwise left
> waiting: guessing would refuse somebody the user never named.
>
> An entry that already has an id takes the display name its person
> goes by now, so the box shows who they are today -- unless the box
> is open on that list, where the typed line is matched back by name.

### `LyricsView.source_order`

**line 12303** — from the docstring, `def source_order(self) -> list:`

> The providers to consult, in the order the SOURCES were ranked.
>
> The chain below still speaks in providers, and it has more of them
> than there are sources: two doors on Apple Music, and four blends that
> put Apple's words on somebody else's clock. Each source expands to the
> providers that answer for it, in its own place in the order, so moving
> Apple Music up the list moves everything that speaks for Apple Music
> with it.
>
> Each blend goes in immediately above the highest-ranked source it
> borrows from -- Apple+NetEase above NetEase, Apple+Kugou above Kugou
> -- rather than up at Apple Music's own slot, which is where they sat
> before. A blend is two sources' work and has no claim on a place in
> front of a third that lent it nothing; where it really is the better
> document it still wins, because quality outranks order. Among
> themselves they follow the donors' ranking, which is what the Blends
> section is showing.

### `LyricsView.fetch_ahead_scan`

**line 12308** — from the docstring, `def fetch_ahead_scan(self) -> None:`

> Look the next few queued tracks up before they are reached.
>
> The bet is that a track thirty seconds away can be fetched now, for nothing, instead of being
> waited on at the moment it starts. The chain is ten providers wide and
> a cold song takes seconds to walk, which is the "Loading lyrics…" the
> first bars of a song are read through.
>
> Handed over whole every time rather than added to. The queue is re-read
> every minute and after every track change, and the user reorders it:
> what was coming up a minute ago is no evidence about what is coming up
> now, and warming it would spend requests on a song nobody will hear.

### `LyricsView.covers_ahead`

**line 12388** — from the docstring, `def covers_ahead(self) -> None:`

> Make the Discord card's animated cover for the next queued track
> (DP.AHEAD_TRACKS of them, never more than Fetch ahead). A GIF just
> put on the Worker is kept from Discord for GIF_SETTLE (90s) -- see
> discord_presence -- so one made when its album starts playing leaves
> the still cover up for a minute and a half; made while the track
> before it plays, that wait has passed by then.
>
> Keyed as discord_state keys the playing track, record artist first,
> so the album found here is the one asked for when it plays. Only
> while the card would show an animated cover at all.

### `LyricsView.on_source_trouble`

**line 12405** — from the docstring, `def on_source_trouble(self, tid: str, bad) -> None:`

> A source that could not be reached, said once and then left alone.
>
> Only for the track on screen. The look-ahead walks other songs on a
> thread of its own, and a toast about one of those would be about a
> song the user cannot see and has not asked for yet.
>
> And once per source, not once per song. A host that is down is down
> for every track, so what was meant as "you are not getting what you
> ranked second, and here is why" arrived on every song change instead
> -- which is how a single unreachable source became a notification
> that would not stop. It is worth repeating only if it is still true
> much later, hence the hour: long enough not to nag, short enough
> that an outage which outlives a listening session says so again.

### `LyricsView.searched`

**line 12421** — from the docstring, `def searched(self) -> bool:`

> Whether the chain has finished looking for THIS song and found none.
>
> `done` is the fetcher saying it has been all the way round for a
> track, which `on_lyrics` already reads the same way.
>
> It is asked because a screen with no words on it used to re-ask on
> every poll -- and the poll runs at POLL_MS_EDGE precisely because
> there are no words, so a song nobody has a lyric for was asking
> sixteen times a second, for as long as it played. The fetcher's own
> backoff kept that from being sixteen WALKS a second, but every one of
> them still woke its loop, and the walks that did get through knocked
> on every door again, the slowest of them included. What that
> looks like from the front is the screen going back to looking for
> lyrics over and over on a song that has none.
>
> Nor does the fetcher retry once a settled walk has come back empty:
> that is the answer, and the song is shown as instrumental.

### `LyricsView.fetch_meta`

**line 12426** — from the docstring, `def fetch_meta(self) -> dict:`

> What the name-based providers need to find the song.
>
> The length is the RECORDING's where a catalogue has said what that is,
> and the player's otherwise. They are not the same number off a
> browser: an upload runs a few seconds longer than the release it is
> of, and those few seconds are load-bearing here. Every provider
> weighs the duration, and measured on Conro's "Thrill of It" -- 200.4s
> released, 206 as uploaded -- the five-second difference dropped the
> song out of NetEase's "near" and let a stranger's song of the same
> name, a second closer to the upload, outrank it. Nothing about what
> is DRAWN uses this: the progress bar belongs to the audio actually
> playing, which is the upload. See on_card.

### `LyricsView.sounding`

**line 12505** — from the docstring, `def sounding(self, pos: float) -> list[int]:`

> Lines to treat as current.
>
> Between two lines nothing is strictly active, which used to leave every
> line six steps from an anchor that did not exist -- so the whole view
> went to maximum blur at 10% opacity in every gap between lines. Hold the
> line that just finished instead, the way the web view keeps it lit until
> the next one starts: the reading stays put and only real distance blurs.

### `LyricsView.focus_line`

**line 12522** — from the docstring, `def focus_line(self, pos: float) -> int:`

> The line the song is ON at `pos`, as opposed to everything audible.
>
> sounding() answers a different question -- it hands back every line
> covering `pos`, which is what the stack needs, because it draws all of
> them. A renderer that draws ONE line has to choose, and the choice is
> not "the first of them": a line whose end has been stretched over the
> ad-lib written into it goes on covering `pos` for as long as that
> ad-lib lasts, which on a chorus with a tail is well into the line
> after it. Taking the first live line there kept the view on a line
> whose words were finished while the next one sang.
>
> The same answer the scroll uses, so a pinned renderer and the stack
> agree about where the song is -- but with no scroll-ahead, since
> nothing here is moving and there is nothing to be early for.

### `LyricsView.troll_aim`

**line 12587** — from the docstring, `def troll_aim(self, idx: int) -> int:`

> Which line the column scrolls to for the one being sung.
>
> The song is drawn at the real time throughout -- the right line is
> lit, and it fills word by word exactly as it would with this off. All
> that is wrong is where the COLUMN has stopped: the reading band holds
> the line above or below, so the words being sung sit a row out of
> place and the line you are reading at is one nobody is singing.
>
> That is the off-by-one worth having. Lying to the clock instead lights
> the wrong line and fills THAT, which is a different fault and reads as
> a broken document rather than as a view that has miscounted -- and it
> would put the lie in front of the seek, the measurement and the
> clipboard, none of which have anything to do with scrolling.
>
> Re-rolled when the column moves to a new line, because a skew that
> changed mid-line would be seen as a jump. Once it has gone wrong it
> tends to STAY wrong -- a real off-by-one does not fix itself every
> other line -- so a skew already running is kept more often than one is
> started, with the stickiness a floor under the knob and never a cap on
> it: a knob turned past it is asking for more wrongness, not less.

### `LyricsView.searching_now`

**line 12612** — from the docstring, `def searching_now(self) -> bool:`

> Whether the column is currently hunting for the lyrics.
>
> Bouts come at random and end on their own. The knob sets how often
> and how long: at 1.0 there is six to twenty seconds of ordinary
> scrolling between them and each one runs three or four, which came
> out at a bout every seventeen seconds over a hundred seconds of
> frames; at 3.0 the gaps are a third as long and the bouts twice as
> long, and it spends more of the song hunting than following it.
>
> Nothing starts while the reader is scrolling by hand -- being fought
> for the scrollbar is a different feeling from watching the app lose
> its place, and only one of them is funny -- and nothing starts under a
> pinned renderer, which has no scroll to lose.

### `LyricsView._search_leg`

**line 12637** — from the docstring, `def _search_leg(self) -> None:`

> Somewhere else to look, and the pace it is gone after at.
>
> The places are over the WHOLE lyric, not around wherever the bout
> happened to start, and each one is across the middle of the document
> from where the column is now, so a leg is the length of the song and
> not a nudge. One in four ignores that and lands anywhere, because a
> hunt that alternates perfectly is a pattern and a pattern looks
> deliberate.
>
> The pace is measured in windows a second rather than in pixels, so it
> means the same thing on a laptop panel and on a television: three to
> seven of them, and half as many again at the top of the knob. Nothing
> can be read at that speed, which is the point.

### `LyricsView.troll_search`

**line 12651** — from the docstring, `def troll_search(self) -> float:`

> Travel between the places, without ever stopping at one.
>
> Somewhere to look is picked the way a hunt picks: a long way off,
> usually the other side of the song. What the column does about it is
> SCROLL there -- at a few windows a second, continuously, the words
> going past too fast to read -- and the moment it arrives it is already
> leaving for the next place at a fresh pace. It never comes to rest
> between legs, so a bout is one unbroken run up and down the lyric
> rather than a series of stops.
>
> Driven as a velocity rather than as a destination for exactly that
> reason: an eased approach decelerates into every place it looks, and a
> column that keeps slowing down and setting off again reads as a series
> of decisions. tick() leaves the ease nearly off underneath this, or
> the lag would put a curve back on both ends of every leg.

### `LyricsView.instrumental`

**line 12671** — from the docstring, `def instrumental(self) -> bool:`

> Nothing to show for this track, and nothing still coming.
>
> The fetch chain answers more than once -- a miss, then a retry a couple
> of seconds later -- so a verdict reached on the first empty answer would
> rearrange the window and then undo it. Waiting the retries out costs a
> few seconds of "…" and gets it right.
>
> The clock alone was not enough. A lookup that goes out to every provider
> can outlast SETTLE several times over, and the window would rearrange
> itself around a song with perfectly good word timing that simply had not
> arrived yet. So the fetcher says when it has actually finished asking,
> and until then this is a wait, however long it runs.

### `LyricsView.panel_width`

**line 12679** — from the docstring, `def panel_width(self) -> float:`

> Left art panel; collapses on narrow windows so lyrics get the space.
>
> Compact mode collapses it at any width -- that is what compact means --
> and the cover it would have shown reappears small beside the title.
>
> A track with no lyrics gives the whole width to the panel instead. The
> column exists to hold words; with none to hold, an empty two-thirds of
> the window pushing the cover into a corner is just a layout waiting for
> something that is not coming.

### `LyricsView.panel_x`

**line 12695** — from the docstring, `def panel_x(self) -> float:`

> The panel's left edge. 0 unless it has been sent to the other side.
>
> Everything in the panel is laid out from this rather than from the
> window, so switching sides is one number and not a second layout: the
> cover, the title block, the progress bar and the volume slider all
> keep the arithmetic they had.
>
> A panel filling the whole window -- which is what an instrumental
> gets -- starts at 0 whichever side it is nominally on, and falls out
> of the same subtraction.

### `LyricsView.line_ink`

**line 12753** — from the docstring, `def line_ink(self, ln: dict):`

> Everything about a line that changes the glyphs, and nothing else.
>
> Deliberately no times. The cached pixmap is the un-sung text; when it
> is sung is decided every frame by the painter reading the line itself,
> so a line re-timed to the millisecond draws the identical picture.
>
> Deliberately no line number either -- see line_pixmap.
>
> Kept on the line, because line_pixmap asks for this before it can look
> anything up and it is asked twice per visible line per frame -- once
> for each of the two blur levels a line is blitted at. What it builds is
> a tuple per syllable, and a long song has eleven thousand of them.
>
> The three things it depends on that are not the line itself are all in
> the memo's own key: which script is being laid out, whether the
> readings are drawn, and a counter that moves when a romanisation is
> corrected in place. Everything else about a line is settled before it
> is ever painted -- `prepare` writes the pieces and the duet flags
> arrive with the document.

### `LyricsView.ruby_rows`

**line 12931** — from the docstring, `def ruby_rows(self, ln: dict, rows, fm: QFontMetricsF):`

> Readings placed over the characters they belong to, row by row.
>
> The wrapper hands back the text fragments it actually laid out, and they
> join back up into the line, so the readings are worked out against those
> rather than against the timed pieces -- no need to track which fragment
> came from which syllable, and a fragment the wrapper had to break mid-word
> still gets the part of the reading that sits over it.

### `LyricsView.drift_of`

**line 12988** — from the docstring, `def drift_of(self, key, x0: float, y0: float, w: float, h: float):`

> Physics state for one word, seeded where it was when it came loose.
>
> The position is ABSOLUTE in the window, not an offset from the line.
> Holding an offset meant the line kept scrolling out from under the word
> and dragged it along, so pinning the scroll was the only way to stop
> everything migrating to a corner -- and pinning the scroll stopped the
> lyrics following the song at all. Once a word is loose it belongs to the
> window; where its line has got to no longer concerns it.
>
> The launch direction comes from a hash of the key rather than random, so
> a word that leaves and comes back keeps its heading instead of jumping.

### `LyricsView.per_frame`

**line 13040** — from the docstring, `def per_frame(self, k: float) -> float:`

> How far an ease that covers `k` of the way each frame at EASE_HZ
> gets over the frame just gone.
>
> The tick's easings were written as a fixed share per step, and a step
> is a frame, so their speed was the frame rate's: a line dropped into
> place in 45ms at 240fps and 180ms at 60, and the column took four
> times as long to reach a clicked line. Taking the share to the power
> of the frames' worth that really passed makes them one speed at any
> rate.
>
> Which speed is EASE_HZ, and it is 240 because that is the one these
> were actually watched at -- uncapped on a 240Hz panel. Pinning them
> to sixty instead made a click on that panel wait a fifth of a second
> before the column went anywhere.

### `LyricsView.drop_pixmaps`

**line 13192** — from the docstring, `def drop_pixmaps(self) -> None:`

> Let go of every drawn line and every glow.
>
> This is about MEMORY, not about correctness. Both keys say everything
> about the picture they stand for -- the ink, the width, the blur, the
> size, the alignment, the script and the font -- so nothing here is
> ever needed to stop a stale picture being drawn. A key that no longer
> matches is simply never asked for again and falls off the cold end of
> its own budget.
>
> That is why the invalidations went away. They were the stall: a
> better source arriving mid-song threw away every drawn line in the
> column and paid 26ms on the frame it landed and 48ms over the six
> after it, for pictures it almost always still wanted -- a better
> answer is usually the same WORDS with a better clock under them, and
> the clock is not in this picture.
>
> What is left is the honest case: a different track. The old song's
> lines will never be asked for again, and there is no reason to hold
> a hundred megabytes of them until the budget notices.

### `LyricsView._nearest_blur`

**line 13435** — from the docstring, `def _nearest_blur(self, key: tuple, blur: int):`

> The same line at the closest blur already in hand, or None.
>
> The key carries the blur at a known place and everything else about
> the picture -- the words, the width, the type, the pen -- so the
> family of levels for one line is reached by swapping that one field
> rather than by keeping a second index beside the cache. Ten probes of
> a dict is nothing next to building a picture, which is the thing being
> avoided.
>
> Searched outwards from the level actually wanted, so the substitute is
> the least wrong one available.

### `LyricsView.glow_layer`

**line 13473** — from the docstring, `def glow_layer(self) -> QPixmap:`

> Accent wash over the cover, cached -- rasterising radial gradients
> every frame was the single most expensive thing in paintEvent.
>
> Scaled by how bright the cover is, which is not the same question as
> what colour it is. The palette is built by throwing the black pixels
> away, so femtanyl's BODY THE PISTOL -- a near-black square with a
> white-hot burst in the middle of it -- hands back a vivid ochre, and
> the wash then lit the window to a brightness the cover never reaches:
> measured off the screen, patches of background at 0.25 and 0.33
> against a cover averaging 0.205. A dark cover now gets a wash in
> proportion, down to a fifth of it, and a bright one is untouched.

### `LyricsView.scene_moves`

**line 13501** — from the docstring, `def scene_moves(self) -> bool:`

> Whether the wall is different from one moment to the next.
>
> Only where `t` reaches the painter: the mesh's blobs and wash, and a
> cover drifting under its crop. Solid, clear, the veil and the art
> with no cover in it are the same picture for as long as everything in
> the key is, and were rebuilt fifteen times a second regardless --
> and once a second when the motion was off, which is a rebuild of a
> picture that cannot change. A visualiser that has taken the mesh's
> place draws its own.

### `LyricsView.scene_layer`

**line 13512** — from the docstring, `def scene_layer(self) -> QPixmap:`

> The whole background, composited at 15fps and blitted at the frame
> rate. Only slow drift changes it, so rebuilding it every frame paid for
> several full-window passes nobody can see.
>
> In clear mode it is a wall with nothing in it: the pixmap starts
> transparent instead of at the ink, no cover and no mesh go into it,
> and the only thing left is the dim -- which stops being a veil over
> the album and becomes the whole of what sits between the words and
> the desktop. At 0 the window is a pane of glass with lyrics on it.

### `LyricsView._paint_scene`

**line 13669** — from the docstring, `def _paint_scene(self, p, dst: QRectF, W: int, H: int) -> None:`

> The wall, with the one it is replacing still under it if it is
> mid-change.
>
> Both are opaque and both cover the window, so the outgoing one is laid
> down whole and the incoming one painted over it at the mix. No third
> buffer, and the frames either side of a fade cost exactly what they
> cost before.
>
> Unless one of them is the clear wall, which covers nothing. Painting
> a transparent picture over an opaque one leaves the opaque one, so a
> fade into or out of clear would hold the old wall for its whole
> length and then cut. When either side carries alpha both are drawn at
> a share of the mix instead, which crossfades what they have -- one
> extra full-window pass, for the second the change takes.

### `LyricsView.step_viz_mix`

**line 13725** — from the docstring, `def step_viz_mix(self) -> bool:`

> Move the visualiser's fade on by the frame just gone. True while it
> moves.
>
> The visualiser arriving is the change nobody asked for and everybody
> sees: the analysis lands mid-song and a lit wall replaces a still one
> between two frames. This is what gives it the same `bg_fade` a change
> of cover gets.
>
> Stepped here rather than in the painter so it takes bg_fade whatever
> the window happens to be drawing at, and so that a fade in progress is
> itself a reason to keep drawing -- see `busy` in tick(), without which
> a paused song would walk through it at the idle ten frames a second.

### `LyricsView.viz_face`

**line 13741** — from the docstring, `def viz_face(self, W: int, H: int):`

> The visualiser as it should be drawn, or None when there is none.
>
> Held back a frame's worth of nothing: `viz_live` turns false the
> instant a track change drops the analysis, and the layer built without
> one is an empty picture rather than the last full one. So the last
> picture is kept and handed back while the mix runs down, which is what
> makes the way out a fade rather than a cut to the still wall.

### `LyricsView.scene_mix`

**line 13756** — from the docstring, `def scene_mix(self) -> float:`

> How far the wall has changed into the new one, 0 to 1.
>
> 1 means there is nothing to fade and the caller can just draw the
> current one, which is the answer on all but the second or so after a
> change. The outgoing picture is dropped here rather than in the
> painter, so nothing holds a window's worth of pixels once it is done.

### `LyricsView.viz_bands`

**line 13823** — from the docstring, `def viz_bands(self, dt: float) -> list[float]:`

> Everything the modes read, eased: up almost at once, down over
> about a third of a second.
>
> Segments run a quarter-second or so, so reading any of this raw makes
> the background step from segment to segment instead of moving -- and
> loudness raw is worse than chroma raw, because it scales the light on
> the whole window at once and so steps the whole window at once. The
> attack stays near-instant because a swell arriving late is the one
> error the eye reliably catches; it is the slow release that turns a
> sequence of discrete readings into something continuous.
>
> The gate is what keeps a rapped verse from thrashing. Where `voiced`
> says the twelve are carrying no chord, they are replaced by the
> loudness rather than merely flattened: a chroma vector arrives
> normalised to its own peak, so its mean on unpitched material sits
> near the top of the scale, and flattening alone pins every blob wide
> open for the whole verse. Loudness is what that material actually has
> to say. Nothing is lost where the vector IS pitched: there the gate is
> fully open and the shape arrives untouched.

### `LyricsView._viz_tint`

**line 13841** — from the docstring, `def _viz_tint(self, c: QColor, i: int, n: int) -> QColor:`

> The palette colour, brought up to something that shows on the wall.
>
> A cover whose colours are all weak gives blobs that read as a smudge
> rather than as anything answering the music -- which is most of what
> "the visualiser is hard to see" turns out to mean in practice. So a
> colour under the floor is saturated up to it. Only those: a cover with
> real colour in it still shows its own and nothing else.
>
> A TRUE GREY IS LEFT GREY. It reports no hue at all, and the only way to
> saturate something with no hue is to invent one -- which this used to
> do, spreading the blobs around the wheel from 0.58 by position. What
> that meant in the window: a grey cover lit up blue, and a cover the
> window drew grey all the way through until the visualiser arrived
> changed colour when it did. The brightness floor still applies, so the
> blobs are still something rather than nothing; they tell apart from
> each other by size and by light, which is what the modes vary anyway.

### `LyricsView.viz_layer`

**line 13877** — from the docstring, `def viz_layer(self, W: int, H: int) -> QPixmap:`

> The driven layer, in whichever mode is chosen.
>
> Painted into a reduced pixmap and scaled back up on the way out, by
> the divisor that mode can afford. It brings a per-frame repaint back
> down to about what the cached 15fps scene cost.
>
> Composited with Plus rather than over, because this lands on top of a
> background that is already finished: adding light to the album wall
> keeps it, while painting over it would punch translucent holes in it.

### `LyricsView._viz_bloom`

**line 13904** — from the docstring, `def _viz_bloom(self, p, w, h, bands: list[float], now: float) -> None:`

> The mesh, driven: the same drifting blobs, sized by what is sounding.
>
> The mode for music with chords in it. Each blob owns a slice of the
> twelve, so a chord moves them apart rather than pumping all of them
> together -- which is also why it is the mode with the least to say
> about a track that is mostly drums.

### `LyricsView._viz_pulse`

**line 13941** — from the docstring, `def _viz_pulse(self, p, w, h, bands: list[float], now: float) -> None:`

> One ring per beat, expanding from the middle and fading out.
>
> Everything here comes off the metrical grid and nothing off chroma,
> which is the point: on a rapped verse the chroma reader is being handed
> snares and consonants, while the grid is the one part of the analysis
> the music is actually built on. Each ring keeps the colour it was born
> with as it travels, so a bar reads as four rings crossing the window
> rather than as the window flashing four times.

### `LyricsView._viz_bars`

**line 13977** — from the docstring, `def _viz_bars(self, p, w, h, bands: list[float], now: float) -> None:`

> The twelve pitch classes as a row of columns standing on the floor.
>
> Ordered around the circle of fifths rather than up the chromatic
> scale, so the classes that sound together stand together: a chord
> lights a neighbourhood of the row instead of scattering across it, and
> a key change slides the lit part sideways. Chromatic order would put a
> triad's three notes four columns apart and show a comb.
>
> This is the mode that says what the analysis actually holds, so it is
> painted full size and left hard-edged rather than smeared into the
> wall like the others.

### `LyricsView._viz_tide`

**line 14001** — from the docstring, `def _viz_tide(self, p, w, h, bands: list[float], now: float) -> None:`

> A horizon that rises with the track: slow water, stacked.
>
> The calm one. No single beat moves it -- the crest takes its height
> from how loud the moment is and its speed from the tempo, so a dense
> track raises the water instead of strobing it. It is what to reach for
> when the blobs are too busy and the rings are too insistent, and it
> wants nothing from the analysis but loudness, which every analysis has.

### `LyricsView._viz_hush`

**line 14087** — from the docstring, `def _viz_hush(self, p, w, h) -> None:`

> Dim the middle of the layer, where the lyrics are.
>
> The crisp modes draw hairlines, and a bright hairline through a sung
> line is the one thing that makes the words harder to read. The soft
> modes need none of this; the bars and the tide keep out of the middle
> on their own.

### `LyricsView._viz_lines`

**line 14101** — from the docstring, `def _viz_lines(self, p, w, h, bands: list[float], now: float) -> None:`

> Thin waves strung across the window, after Kauna's frequency lines.
>
> The twelve in fifths order, read as a curve along the window, drawn
> five times over with a travelling phase so the set ripples. The beat
> flicks them -- a kick lifts the swing and jumps the phase on a little
> -- and between beats they drift. Additive, so where they cross the
> light builds up the way the original's does.

### `LyricsView._viz_confetti`

**line 14138** — from the docstring, `def _viz_confetti(self, p, w, h, bands: list[float], now: float) -> None:`

> Coloured discs thrown on each beat, drifting down and away, after
> Kauna's confetti.
>
> A beat's discs take the colour of the pitch class loudest when it
> landed, so the window's colour follows the harmony beat by beat. They
> grow in over an eighth of a second rather than appearing whole, then
> drift -- down, and sideways by their own seed -- and fade. The seed is
> the beat's index, so the same beat always throws the same discs and
> pausing does not reshuffle the window.

### `LyricsView._viz_prism`

**line 14175** — from the docstring, `def _viz_prism(self, p, w, h, bands: list[float], now: float) -> None:`

> A luminous triangle turning in the middle, ringed by twelve faint
> ones -- Kauna's triangular ring.
>
> The glow takes the beat, the size the loudness, the turn the tempo
> clock. The ring of small triangles is the twelve in fifths order, as
> the bars stand them, so a chord lights an arc of it.

### `LyricsView._viz_halo`

**line 14206** — from the docstring, `def _viz_halo(self, p, w, h, bands: list[float], now: float) -> None:`

> A glowing ring with jagged teeth inside and out -- Kauna's
> spectrum circle.
>
> The swell round the ring is the twelve in fifths order laid round a
> closed curve, so a chord pushes out one side of it. The analysis has
> twelve values and the ring has a hundred and eighty teeth; the fine
> jag between them is a seeded ornament, reseeded on each beat and held
> still between, and only ever scales what the twelve say -- it never
> stands in for them. Filled triangles drift behind it, the same ring
> of twelve the prism draws.

### `LyricsView._halo_band`

**line 14273** — from the docstring, `def _halo_band(p, box: QRectF, scale: float, strokes) -> None:`

> Stroke the halo's ring into a layer of its own and add the layer.
>
> Stroking the ring as a path is what the halo used to do, and it cost
> 8ms a frame on a 400px cover, 25ms at 2x scaling and 22ms over a
> 1600x900 wall -- the whole frame, twice over. Nearly all of it was
> Qt's antialiased path stroker on a closed 180-point zigzag: any pen
> wider than one pixel goes through it, and the hairline core paid
> almost as much as the wide glow.
>
> Separate segments skip the stroker and cost a sixth as much, but
> drawn straight onto the picture, translucent and added, they double
> up wherever two of them meet. So each pass is drawn here in SOURCE
> mode, which with one colour is idempotent: an overlap writes what is
> already there, and the segments come out as one stroke. Each joint
> still needs its outside corner filled, as the round joins did. On a
> thin stroke square caps do it, for a third of what round caps cost,
> and the corner they leave on a tooth tip is a fraction of a pixel. On
> a wide one that corner shows -- the glow went blocky round every
> tooth -- so there the segments are flat and a round dot is put on
> each point instead: the same shape round joins gave, still at half
> the cost of round caps.
>
> A later stroke in the list overwrites an earlier one where it lies,
> so the glow's two bands go in one layer: the mid band is drawn at the
> wide band's alpha plus its own, which is what adding the two gave.
> The glow is soft, so it is drawn at half resolution; the core at the
> screen's own. `box` is the ring's bounds, so a wall-sized canvas
> does not pay to clear and composite the empty corners round it.
>
> Measured after: 3ms, 7ms and 8ms for the three above.

### `LyricsView.mesh_palette`

**line 14315** — from the docstring, `def mesh_palette(self) -> list[QColor]:`

> The palette the mesh is allowed to spend, longest-first as always.
>
> `mesh_colours` is a ceiling and not a promise: a cover that yielded two
> dominant colours has two, whatever the setting says. One is the Genius
> picture -- a single album colour over the whole window -- and taking
> the first N rather than a spread of them is what makes that the
> DOMINANT colour rather than an arbitrary one.

### `LyricsView._mesh_wash`

**line 14350** — from the docstring, `def _mesh_wash(self, p, W: int, H: int, t: float) -> None:`

> One colour down the window from the top, the next back up from the
> bottom: a tinted room rather than lights moving in a dark one.
>
> Nothing here falls to nothing, and that is the whole difference from
> the blobs. The window already wears a vignette -- fade_layer, opaque
> at the top and bottom edges and clear by a quarter of the way in --
> so a gradient that spends its colour at the top edge spends it exactly
> where it is about to be painted out, and the band left in the middle,
> where the eye actually is, comes back black. The strong end is
> therefore only a lean, and the far end keeps a share of the tint.
>
> Spread is how far the lean carries: at 1.0 the middle of the window
> holds half the top's colour and the bottom a quarter, and by 2.5 the
> three are equal and the wash has become the veil. Motion is left with
> something to do -- the lean breathes by a twentieth -- because a
> frozen gradient makes `bg_motion` a setting that does nothing in this
> style, and a setting that does nothing reads as a broken one.

### `LyricsView.fade_layer`

**line 14383** — from the docstring, `def fade_layer(self) -> QPixmap:`

> Top/bottom vignette, cached for the same reason as glow_layer.
>
> Two of them, chosen by whether there is a wall to paint the edges
> into. Normally it is ink laid over the top and bottom quarter, which
> is what takes a line off the screen without a hard edge. On the clear
> wall there is nothing for ink to blend into -- it would be two black
> bands across the desktop -- so the same curve is built the other way
> up, as a mask that is solid through the middle and empty at the
> edges, and `_paint_fade` multiplies it into what is already drawn.
> The lines leave by going see-through instead of by going dark, which
> is the same disappearance against a wall and the only one that works
> without one.

### `LyricsView._paint_fade`

**line 14411** — from the docstring, `def _paint_fade(self, p: QPainter) -> None:`

> Wear the vignette: over the window, or cut out of it.
>
> Only its two bands are drawn. Between 0.26 and 0.74 of the height the
> layer is one flat colour that changes nothing in either mode -- no ink
> over the wall, full alpha into DestinationIn -- and blending it cost
> half of a full-window pass every frame to leave the middle as it was.

### `LyricsView.paintEvent`

**line 14470** — from the docstring, `def paintEvent(self, _ev) -> None:`

> Draw the window, and put the painter down whatever happens.
>
> The try is not decoration. A QPainter that is still ACTIVE when this
> unwinds leaves the backing store mid-paint: Qt says so once per frame
> -- "endPaint() called with active painter" -- and then dies on
> "Cannot destroy paint device that is being painted". An exception in
> here also loses everything drawn AFTER the point it was raised, and
> the lyric column is painted first, so the symptom of a fault anywhere
> below it is a window with words scrolling and no art panel, no
> progress bar, no volume and no toast.
>
> None of which says what went wrong. The traceback does, and it only
> gets printed if the frame it came from does not take the process down
> with it first.
>
> With the GPU canvas up, the window paints nothing: the canvas covers
> all of it and calls paint_onto with its own painter.

### `LyricsView._paint_backdrop_head`

**line 14957** — from the docstring, `def _paint_backdrop_head(self, p, W: int, H: int) -> None:`

> Now playing ▸ backdrop: the cover is only the wall; a small title
> at the top and a thin line along the bottom are all there is.
>
> The volume sits at the top right, beside the settings button, as it
> does in compact mode, rather than at the end of the progress line.
> Down there it was a second bar of the same weight butted against the
> first -- the one reached for mid-song -- and it cut that one short by
> its own width for nothing.
>
> A review sidebar takes a strip of the window, and all of this keeps
> to what is left -- the same strip, with the same margins, that the
> lyric column does (see _lyr_x).

### `LyricsView.halo_live`

**line 14986** — from the docstring, `def halo_live(self) -> bool:`

> Whether the cover's square shows the halo instead: whenever it is
> asked for.
>
> It used to want the track's pitch analysis too, and fall back to the
> cover without it. But every track change clears the analysis and the
> new one lands a second or so later, so each new song flashed its cover
> up before the halo came back. With nothing to read the bands simply
> ease down to nothing and the ring sits still and round until there
> is -- still the halo, never the cover.

### `LyricsView._paint_art_halo`

**line 14991** — from the docstring, `def _paint_art_halo(self, p, box: QRectF) -> None:`

> The halo mode, drawn where the cover would be.
>
> It reads the same eased bands the wall does. When the wall is being
> driven too those have already been stepped this frame, and stepping
> them again would ease twice as fast, so they are only stepped here
> when nothing else is doing it. Drawn at full strength whatever the
> wall's visualiser is set to -- it is the picture, not a tint over one.

### `LyricsView._scroll_text`

**line 15102** — from the docstring, `def _scroll_text(self, p, text: str, rect: QRectF, fm: QFontMetricsF,`

> Draw text in rect, sliding it back and forth if it does not fit.
>
> An ellipsis hides the end of a long title for as long as the song plays,
> and song titles are exactly where the tail matters -- the remix, the
> version, who it is with. Passing over the whole string costs nothing and
> eventually shows all of it.
>
> Held still at both ends, because text that never stops is text nobody
> finishes reading. Anything that fits is drawn plainly and keeps whatever
> alignment it was given; scrolling text is always left-aligned, there
> being no sense in centring something wider than its box.

### `LyricsView.sung_colour`

**line 15260** — from the docstring, `def sung_colour(self, ln: dict | None = None) -> QColor:`

> White unless asked otherwise; 'auto' lifts a bright tint out of the
> cover so the fill belongs to the artwork.
>
> A duet's second voice can take a colour of its own. The flag already
> moves those lines to the other side of the screen, which says "someone
> else" only if you know to read it; a different fill says it outright.

### `LyricsView.glow_colour`

**line 15273** — from the docstring, `def glow_colour(self, ln: dict | None = None) -> QColor:`

> The ink a line's halo is drawn in: its sung colour, at full value.
>
> A glow is brighter than the thing it comes off, and that is not a
> matter of laying the same colour on harder. The sung colour is TEXT
> unless somebody has asked otherwise -- the very ink the line is
> already drawn in -- so a halo cut from it and added back over the
> line is the line out of focus, which is the depth blur and not a
> glow at all. Lifting the value is what makes it light.
>
> The hue and the saturation are kept, so a duet's second voice glows
> in its own colour and an `auto` fill taken off the cover glows in the
> cover's. Only the brightness is taken to the top. See glow_pixmap,
> which has always cut the per-word halo in flat white for the same
> reason and gets away with it because it is only ever one word.

### `LyricsView.base_colour`

**line 15285** — from the docstring, `def base_colour(self, ln: dict) -> QColor:`

> The pen a line's words are drawn in before any of them is sung.
>
> White, except for a duet's second voice on an untimed line inside a
> document that is otherwise timed. The tint is normally carried by the
> sung fill, and a line with no timing never gets one -- so the colour
> that says "somebody else" was the one part of a duet that did not
> arrive on the lines the source could not place. The side it hangs off
> always did; see line_align.
>
> NOT ON A STATIC DOCUMENT, where nothing is timed at all. There the
> rule caught every second-voice line in the song at once, and a page
> of unsynced words came up half in one colour and half in another with
> nothing on screen to say why -- no reveal for it to be the resting
> state of, and nothing sung for it to differ from. It read as two
> lyrics rather than as two voices. A whole document with no clock is
> read, not followed, and the only thing colour can do to that is get
> in the way; the side of the screen still says who is singing.
>
> Only where the line itself is untimed, then, and only where its
> neighbours are not. A timed line keeps the fill it has always had,
> sweeping the tint across as it is sung, and painting its base coat in
> the same colour would take that reveal away on every duet in the
> library.
>
> The tint is laid on at TEXT's own value rather than the fill's, so
> the second voice reads as another voice rather than as a line that
> has already been sung: brightness is what says sung on this screen,
> and hue is what says who.

### `LyricsView._help_fit`

**line 15330** — from the docstring, `def _help_fit(self, W: int, H: int, rows: list, head: float,`

> A layout for `rows` that fits this window, or None.
>
> `head` is the room above the rows -- the title, and the tab strip
> where there is one. `tries` is the column counts worth attempting, in
> the order they look best; the sizes are tried largest first, so the
> panel only gets smaller when it has to. With `force` the last
> combination tried is returned however badly it fits, which is the
> answer for a window too small for anything: something legible and
> clipped beats nothing drawn at all.

### `LyricsView.help_layout`

**line 15354** — from the docstring, `def help_layout(self, W: int, H: int) -> dict:`

> What the Keys panel draws in a window this size.
>
> The whole list first, because seeing every key at once is the better
> answer wherever there is room for it -- two columns, then three if the
> window is wide and short. Only when nothing fits does it fall back to
> one section at a time, and then the tab strip appears with it: tabs
> that are never needed are clutter, and a panel that fits needs none.

### `LyricsView.open_review`

**line 16221** — from the docstring, `def open_review(self) -> None:`

> Go through the document on screen the way a person would.
>
> It is the one screen in this window that is not trying to make the
> lyrics look good. Everywhere else the player quietly puts a document
> right as it draws it -- the invisible characters are stripped, a line
> is played to the end of its words whatever its own end says, an open
> end is clamped -- so the things worth fixing in a file somebody is
> still writing are exactly the things the lyrics view cannot show. See
> review.py for what is looked for and why.
>
> Meant for a TTML that came in from outside: one dropped on the window
> or pushed over the live link. It will read anybody's document, and on
> a catalogue's copy it mostly reports the zero-width spaces that
> catalogue puts in -- which is true, and is worth seeing once.

### `LyricsView.build_review`

**line 16244** — from the docstring, `def build_review(self) -> None:`

> Read the document, unless the same one has already been read.
>
> The document is held and compared by IDENTITY, the way the rest of
> the window asks whether the lyric changed (see same_lyric) -- and the
> object itself is kept rather than its id, because this holds the
> REPORT rather than the thing it was made from, and an id belonging to
> something that has been freed is an id another document can be handed
> next. The live link is what makes that matter: an editor pushes a new
> document on every keystroke, each one replacing the last.

### `LyricsView.review_shown`

**line 16269** — from the docstring, `def review_shown(self) -> list:`

> The rows the page is listing, which is not always all of them.
>
> A row with nothing to say about it is left out, and one exception is
> kept: the LINE an ad-lib is written in comes with it. An ad-lib is
> half a line -- the words that are sung over the ones in front of them
> -- and on its own, under a line number that belongs to something else
> on screen, it reads as a line the song does not have.

### `LyricsView.review_folded`

**line 16283** — from the docstring, `def review_folded(self) -> list:`

> The listed rows with the repeats folded in: [(row, [the others])].
>
> A song repeats itself, and a document's faults repeat with it: "Wha-
> wha- what" is three lines of this folder's She Bugging and the same
> sentence three times, and Music Baby says "B-A-B-Y-B-O-Y" eleven
> times. Reading the same finding eleven times is not eleven times the
> information; it is a page somebody stops reading.
>
> Folded on what is ON SCREEN -- the words, and what is said about them
> under the tab and weight being read -- so two lines that only look
> alike stay apart, and the times of the others are kept and printed.
> `A` unfolds them, because "every line" should mean every line.

### `LyricsView.review_plan`

**line 16308** — from the docstring, `def review_plan(self, W: int):`

> Every listed row laid out down the page, worked out once.
>
> The same bargain the lyrics column strikes in Flow.plan: none of this
> answers to the clock or to the scroll, so a frame reads it instead of
> building it. It is rebuilt when the document, the filter, the rule or
> the width change -- which is what the key holds.

### `LyricsView._paint_review_loose`

**line 16608** — from the docstring, `def _paint_review_loose(self, p, W: int, rep, gut: float, y: float) -> float:`

> What is wrong with the DOCUMENT, which belongs to no line of it.
>
> Nothing is timed; something is timed past the end of the recording;
> nobody is credited with writing the song. The list below is a list of
> lines, so a finding with no line to hang on had nowhere to be drawn
> and was counted in the tabs without ever being shown -- a number
> beside a weight that nothing on the page accounted for.
>
> Read through the same filter as everything else: these belong to a
> tab and carry a weight like any other finding, and a page narrowed to
> the things that are wrong should not keep showing a note about the
> header.

### `LyricsView.marking`

**line 16641** — from the docstring, `def marking(self) -> bool:`

> Whether the words being drawn should carry their review marks.
>
> Any document, not only a file of the user's own. It was held to their
> own files at first, on the argument that being told about a zero-width
> space while a song plays is help on a file you are writing and noise
> on a copy you cannot edit -- and the argument is sound about ZWSPs,
> which the catalogues put between every pair of words. It is not a
> reason to refuse the question: what a catalogue's copy gets wrong is
> worth seeing too, and it is how anybody would decide whether to go and
> time the song themselves.
>
> What answers the noise instead is the filter the review page already
> has, which this reads: with the Splits tab up, or with `1` pressed for
> the things that are wrong, a document nobody would otherwise look at
> twice marks four words rather than four hundred.

### `LyricsView.review_spans`

**line 16646** — from the docstring, `def review_spans(self):`

> Where this document's faults are, as the column needs them.
>
> ({line key: [(start, end, level)]}, {line key: level}) -- the pieces to
> underline, and the worst thing said about each line for the bar in the
> margin.
>
> Built once per document and held: the read itself is a pass over the
> whole document, about 8ms for a song of this length, and the first one
> of a session also loads pyphen's patterns for another 70ms. The map is
> then 0.5ms to build and the drawing 0.09ms a frame, measured here over
> 300 frames of "Love Blur" -- so what this costs is one hitch on the
> frame a document lands, which is the frame that was already laying the
> whole column out.
>
> Keyed by TIME, which is the one thing a drawn line and a document row
> certainly agree on. They agree on nothing else: what gets drawn has
> been through `prepare` and the syllable splitter, so one document
> syllable can be three drawn fragments (split "all") or three can be
> one (merge), and the indices do not survive either. A fragment belongs
> to whichever piece of the document its start falls inside.

### `LyricsView._mark_level`

**line 16678** — from the docstring, `def _mark_level(spans, t: float) -> str:`

> What is wrong with the piece of the document sounding at `t`.
>
> A piece that BEGINS at `t` answers for it, and otherwise the last one
> to have started by then. Both halves are needed. Pieces of one word
> touch exactly, so one ends at the same millisecond the next begins,
> and accepting any piece containing `t` put every fragment inside its
> predecessor as well -- the rule under a bad seam ran on under the
> syllable after it.
>
> And more than one piece can begin at `t`, which is what the second
> half is for: a piece with no length at all sits exactly on top of the
> one after it. Walking on to the last of them handed the mark to the
> piece on top, so a syllable timed to last nothing -- which is the
> fault being reported -- was the one thing on the line with nothing
> drawn under it. LEDGER's "Foreigner" is 30 of them.

### `LyricsView._paint_review_marks`

**line 16696** — from the docstring, `def _paint_review_marks(self, p, x0: float, width: float, H: int) -> None:`

> The review, drawn over the column it is about.
>
> Two marks, and they answer different questions. A bar in the margin
> says THIS LINE has something wrong with it, on every line the window
> is showing, so a fault arrives on screen before the voice does. A rule
> under a word says WHICH WORD, and is drawn only within a line or two
> of the one being sung -- underlines all the way down a column are
> wallpaper, and stop being read after the first screenful.
>
> The geometry is the stack's own: `layout_line` lays out the rows and
> both the picture path and the live path put the first baseline at
> y + ruby + ascent and step by height * 1.06 + ruby. The one thing
> added back here is the line drop, because the line being sung is
> drawn a few pixels low as it arrives and a mark that ignored that
> would come unstuck from its word for the length of the entrance. What
> is deliberately NOT followed is the rise: a lifted word climbs off a
> rule that stays where the line is, which is what a rule under a line
> of type should do.
>
> The pinned renderers lay their own rows out at their own size (see
> Renderer.stacked) and get the margin bar alone, as do the three
> trolls that take the words off the line entirely -- there is nothing
> sensible to underline when the word is in the air.
>
> A stacked renderer may still DRAW a line under a scale -- the amll
> column shrinks everything but the line being sung -- and that moves
> the ink without moving the layout this works from. So each line's
> rules go through the renderer's own transform, taken from
> `line_scale` and applied about the same centre it uses, which is how
> they stay under the words through the grow rather than only at the
> two ends of it. The bar in the margin is deliberately left out of it:
> it is a mark against the COLUMN, at a fixed place beside it, and a
> bar that crept in and out by three percent as the voice went past
> would be the most distracting thing on screen.

### `LyricsView.toggle_review_marks`

**line 16781** — from the docstring, `def toggle_review_marks(self) -> None:`

> Turn the marks in the column on or off, and say what is about to
> happen -- which is not the same answer on every document.
>
> The count is worth the 8ms it costs to have: the same key over a file
> somebody hand-timed marks four words, and over a copy fetched from a
> catalogue it marks four hundred, and being told which of those is
> coming is the difference between a feature and a broken window.

### `LyricsView.review_mode_renderer`

**line 16818** — from the docstring, `def review_mode_renderer(self) -> None:`

> Swap in the review renderer as a review mode starts, and put the
> saved one back as the last of them ends.
>
> The swap is not a setting: while it is in, the renderer the settings
> keep is held in _rev_home_renderer and saved in its place, so picking
> another one meanwhile is for this stretch of reviewing only.

### `LyricsView.editor_closed`

**line 16834** — from the docstring, `def editor_closed(self) -> None:`

> Put the renderer and the review back as they were before the TTML
> Editor's first push, now that the last editor has gone.
>
> What the editor turned on -- "Review when the TTML Editor opens", and
> the review renderer that comes in with it -- or what was turned on by
> hand while it was open, was for working on that document. It was
> also saved as it went, so without this a session with the editor
> left the player reviewing, on the review renderer, from then on.

### `LyricsView.review_level_with_lyrics`

**line 16936** — from the docstring, `def review_level_with_lyrics(self, W: int) -> bool:`

> Scroll the sidebar so the line being sung sits level with itself.
>
> The height is the renderer's own: wherever it put that line on this
> frame -- `line_rects` less the scroll, which every renderer fills,
> the pinned ones included -- is where its row in the list is drawn.
> Aimed at where the column is going rather than where it is on this
> frame, so the list holds still under a line and makes one eased move
> to the next -- riding the column's own motion copied every drop and
> settle onto the list. A row the list leaves out is stood in for by the
> last listed one before it. A wheel or an arrow takes the list over
> for a few seconds, the way it does the lyrics. True while following.

### `LyricsView._paint_review_fold`

**line 17024** — from the docstring, `def _paint_review_fold(self, p, i: int, item, x0: float, ny: float,`

> The repeats of one line: one line about them, or all of them.
>
> Closed it is a sentence with the times in it, which is enough to know
> that the fault repeats and roughly where. Open it is a row per
> occurrence, each one somewhere to click and each one a place in the
> song to play from -- because the third time a line is sung is
> sometimes the one that is wrong in a way the first two are not, and
> the only way to find that out is to be able to reach it.

### `LyricsView._paint_review_keep`

**line 17058** — from the docstring, `def _paint_review_keep(self, p, k: int, right: float, y: float,`

> The button that answers one finding about a seam.
>
> Drawn in the seam's own colour, at the right-hand end of the sentence
> it answers rather than under the row -- a row can carry several
> findings and only some of them are answerable, and a button under the
> row would have nothing to say which one it meant. The sentence is
> wrapped to leave room for it (see review_plan), so it never lands on
> top of the words it belongs to.

### `LyricsView.review_fixes`

**line 17074** — from the docstring, `def review_fixes(self, at: int) -> list:`

> Which of the findings listed against one row can be ruled on.
>
> Read off what the page is SHOWING rather than off the row, because
> `told` writes out the first of each kind and counts the rest: a line
> that cuts two words oddly shows one sentence and one button, and the
> second word surfaces as the first once the first has been answered.

### `LyricsView.review_keep`

**line 17089** — from the docstring, `def review_keep(self, at: int) -> None:`

> Rule that the document has this word right and the splitter wrong.
>
> The reviewer holds every seam in a document to `editor.syllables`,
> and that rule is wrong about words often enough to matter -- it is a
> rule, and a lyric is full of names, spellings nobody prints and words
> sung the way they are sung. Until now the only place to tell it so
> was the editor's Syllabify dialogue, which means opening the other
> window over a document this one is only reading.
>
> It writes the editor's own store, so it is one decision rather than
> two: the word is settled here, in the editor, and in every song after
> this one. Nothing about the DOCUMENT is touched -- the seam stays
> exactly where the person who timed it put it, which is the whole
> point of saying it was right.

### `LyricsView.review_unkeep`

**line 17115** — from the docstring, `def review_unkeep(self) -> None:`

> Take back the last split kept from this page.
>
> Back to what it was rather than back to nothing: keeping a split over
> a word that already had one is how a correction gets corrected, and
> undoing that should leave the earlier one standing. Only this
> session's keeps are on the stack -- the rest of the store is the
> editor's dialogue to manage, which lists every correction there is.

### `LyricsView.review_correct`

**line 17151** — from the docstring, `def review_correct(self, at: int) -> None:`

> Say how a word IS split, rather than only that the rule is wrong.
>
> Filled in with the sung rule's split to start from, since that is
> usually the answer, and anything typed is taken: a word no rule
> splits the way it is sung is what this is for. The answer is kept as
> a correction the same way the editor keeps one, so it holds here, in
> the editor, and in every song after this one.

### `LyricsView.review_ignore`

**line 17238** — from the docstring, `def review_ignore(self, how: str) -> None:`

> Take a finding off the page, or every finding like it.
>
> `one` is this finding on this line of this song; `kind` is every
> finding of its kind in every song -- all the "runs into the next
> one"s; `level` is everything at its weight -- all the "worth a
> look"s. Kept with the reviews' own settings, and U takes back the
> latest.

### `LyricsView.review_flag`

**line 17275** — from the docstring, `def review_flag(self) -> None:`

> Put a flag of your own on the selected line.
>
> Picked from the flags kept so far or written new, with a weight. A
> flag with {word} in it asks for the word: "Please resync {word}" and
> "ball" is "Please resync ball". Where other lines read the same, it
> asks once whether they get the flag too, and never again for that
> flag on those words.

### `LyricsView._paint_review_tabs`

**line 17377** — from the docstring, `def _paint_review_tabs(self, p, W: int, rep, gut: float, y: float) -> float:`

> The strip that divides the findings into the questions they answer.
>
> Drawn the way the Keys panel draws its sections, and carrying each
> tab's count, because the count is the reason to press one: a document
> with nothing wrong in its words and eleven things wrong in its timing
> says so before anything is read.

### `LyricsView.review_cycle_lang`

**line 17487** — from the docstring, `def review_cycle_lang(self) -> None:`

> Read the document as another language.
>
> Not a setting so much as a correction. Which seams a word may be cut
> at is a fact about the language it is in, and the only thing that says
> what language a document is in is a tag anybody can get wrong -- every
> Dutch file in this folder is tagged `en`, and against English rules a
> Dutch lyric looks wrong at al·les, da·mes and lan·ge, all three of
> which are exactly right. Telling it takes the Krantenwijk file in this
> folder from sixteen findings to eight.

### `LyricsView.wind_genius`

**line 17753** — from the docstring, `def wind_genius(self, typed: str) -> None:`

> Start the countdown to asking Genius, or drop what it last said.
>
> Called on every keystroke in either box: the countdown is restarted so
> the request only goes once the typing stops (ask_genius), and a box
> emptied back below a searchable query forgets the answer to the one
> before it.

### `LyricsView.genius_rows`

**line 17793** — from the docstring, `def genius_rows(self, typed: str, known) -> list[dict]:`

> The Genius hits worth showing under a box that says `typed`.
>
> Dropped from them is anything `known` already covers: a song this
> machine has the lyrics to, or one the catalogue search itself found,
> is better as that row -- it has a Spotify id already and needs no
> matching. `known` is (title, artist) pairs in GR.key form.

### `LyricsView.merge_hits`

**line 17806** — from the docstring, `def merge_hits(self) -> None:`

> One order over both sources, best answer first.
>
> Cached and Genius rows are scored the same way (score_local, and
> GR.rank_hit before them), so a song whose NAME is what was typed comes
> above songs that merely quote the words, whichever side it came from.
> The song playing right now stays pinned at the top regardless.
>
> A song that is both is shown once, as the cached hit: that one can be
> jumped to inside the lyrics, and it already knows its Spotify id.

### `LyricsView.copy_info_row`

**line 18121** — from the docstring, `def copy_info_row(self, pos) -> bool:`

> Take the value of whichever row was clicked. False if none was.
>
> The panel is the one place in the window where the answer to a
> question is a string somebody wants elsewhere -- a track id to paste
> into a search, an ISRC, the songwriters, the name of the output. It
> stays open afterwards: copying one of them is usually the start of
> copying another.

### `LyricsView._paint_field`

**line 18331** — from the docstring, `def _paint_field(self, p, fld, rect: QRectF, fm, hint: str = "") -> None:`

> Draw a hand-made text box in the font and colour already set on
> the painter: the text, the selection under it, and the caret,
> scrolled so the caret stays in view however long the text runs -- and
> tell the field where all of that landed, so the next click can be
> placed in it.
>
> The only place any of this is written down. The romanisation editor,
> the lyric search and the Spotify search all come through here, which
> is what keeps the caret, the selection and a click on the text
> meaning the same thing in all three.

### `LyricsView._paint_drawer`

**line 18813** — from the docstring, `def _paint_drawer(self, p, W: int, H: int) -> None:`

> The settings drawer, from a picture kept between frames.
>
> Drawn afresh it is about 145 runs of text, 76 elisions and 165
> measurements in Python, every frame, for a panel that is the same
> frame after frame: measured at 1080p, 3.8ms a frame became 7.3 on the
> GPU and 7.8 became 12.6 on the CPU for as long as it was open. And the
> first open cost 64ms on the GPU, Qt's GL engine compiling programs
> for the drawer's shapes and rasterising its fonts on the spot.
>
> Everything it shows comes from the window's state and where the
> mouse is, so it is drawn into a picture -- on the CPU, so the GL side
> only ever blits it -- and drawn again only when one of those may have
> changed: its size, tab or scroll, any press, key, wheel or setting
> (_dr_rev), the mouse moving onto or off anything it can click, which
> is every hover it draws, or -- checked four times a second -- any
> value it shows having changed on its own, an update's progress or a
> cache's size (_dr_said). Within 2/255 of drawing it live, hovers
> included.

### `LyricsView._paint_tile_pic`

**line 19401** — from the docstring, `def _paint_tile_pic(self, p, o: str, pic: QRectF, u: float) -> None:`

> A small picture of what a background or a layout looks like,
> drawn once and kept.
>
> Drawn afresh they were most of what a search keystroke cost: the
> drawer's picture is made again on every key, a clear tile is a
> checkerboard of ~280 fillRects and art and mesh are radial gradients
> filled through a clip -- 8ms of a redraw at 1080p, with the hits for
> "background" on screen. Kept by everything the drawing reads, and by
> where it lands inside a device pixel, so the blit is a plain copy.

### `LyricsView.dr_song_key`

**line 20283** — from the docstring, `def dr_song_key(self, ev) -> bool:`

> The This song tab's own keys. False passes the press on.
>
> Settings and Keys take what is typed -- a search, a new binding --
> so they keep every key. This tab only shows things, as the classic
> box did, so everything but closing it and moving to another tab goes
> on doing what it does with the tab shut.

### `LyricsView.ask`

**line 20365** — from the docstring, `def ask(self, dlg: dict) -> None:`

> Put a question up. `dlg` holds:
>
> title, body (paragraphs), yes, no, danger, default_no
> input (starting text) and ph (its hint), need (input required)
> pick: [(section, [(key, label, change)])] -- ticked rows
> ok(dlg) / cancel(dlg) -- called with the dialogue as answered

### `LyricsView.blend_slot`

**line 20596** — from the docstring, `def blend_slot(self, key: str):`

> Which blend a Blends row stands for, or None for other rows.
>
> A family of its own, deliberately not folded into src_slot: a slot
> that answers there is one that can be REORDERED and whose switch is
> read through SRC_ATTR, and neither is true of a blend. The test is on
> the whole of "blend_slot" so it cannot catch the switches themselves,
> which are spelled blend_qq, blend_ne_qq and so on.

### `LyricsView.menu_row`

**line 20606** — from the docstring, `def menu_row(self, i: int):`

> MENU[i], with the Sources and Blends rows resolved.
>
> The flat MENU is built once at import and addressed by index everywhere,
> so the rows themselves cannot be shuffled. The slots are given their
> label and their key here instead, which puts them on screen in the
> order they are actually consulted.
>
> The blends are numbered from LS.blend_order, which is the same call
> the chain expands them with -- so the two cannot drift apart, and
> there is no second order stored anywhere.

### `LyricsView.clear_cache`

**line 20665** — from the docstring, `def clear_cache(self, which: str) -> None:`

> Clear one cache, or every ordinary one, and say what it freed.
>
> The two marked `keep` in the inventory -- alignments made here and the
> editor's backups -- are skipped by "clear all" and cleared only by
> their own row, which is the second thought they are worth. Nothing
> asks for confirmation: every row shows its size before it is pressed,
> and all of it comes back on its own.

### `LyricsView.share_read`

**line 20943** — from the docstring, `def share_read(self, text: str) -> dict | None:`

> Pasted settings text, as the settings it can safely set, or None.
>
> The clipboard is whatever somebody sent, so nothing in it is trusted:
> a piece whose label is not a shared row is skipped, a choice has to be
> one the menu offers, and a number is clamped into the menu's range.
> Section tags, line breaks and case do not matter.

### `LyricsView.preset_step`

**line 21039** — from the docstring, `def preset_step(self, delta: int) -> None:`

> ‹ › through the presets, each put on as it comes up.
>
> Nothing is asked: a preset is something to try, and the next press
> is the undo. Saving one is not in this cycle -- it is Share's "Save
> as preset" -- because reaching it here meant putting on every preset
> in between, and what got saved was the last of them rather than the
> settings somebody meant to keep.

### `LyricsView.flip_view`

**line 21477** — from the docstring, `def flip_view(self) -> None:`

> A, between the cover's own panel and the compact strip.
>
> It used to switch the art panel on and off, which is the same setting
> the menu offers as a switch and is not the one anybody reaches for
> while reading: what you want is the lyrics to have the width, and
> compact is how you say that -- the cover goes to a thumbnail beside
> the title and the words take the rest.
>
> Through menu_set, so the menu shows what the key just did and the
> layout caches are dropped by the one place that knows which settings
> make them stale -- which is also the line the old branch was quietly
> duplicating. Whether the cover is shown at all stays a separate
> question with a separate row in the menu.

### `LyricsView.seek_line`

**line 21578** — from the docstring, `def seek_line(self, step: int) -> None:`

> Up and Down: to the previous or next place worth starting from.
>
> Those are every line's start, the start of the song itself -- Up on
> the first line used to go nowhere, where the song's own start is the
> obvious place above it -- and the start of every instrumental break,
> which is where the last word before a long gap stops. A break was
> stepped straight over, so the only way to hear one again was to drag.
>
> Up within two seconds of where the current stretch began goes back
> one; later than that it starts the current one again, the way a
> player's back button does.

### `LyricsView.on_motion`

**line 21698** — from the docstring, `def on_motion(self, key: str, frames) -> None:`

> Frames arrive as QImages off the worker; QPixmap is GUI-thread-only.
>
> Held at the biggest size this screen could ever draw them, not at the
> size they were decoded to: sixty frames of 720px cover is 124MB of
> pixmap for a panel that is usually painting a third of that. Sized off
> the screen rather than the window so resizing never has to rebuild.

### `LyricsView._take_motion`

**line 21725** — from the docstring, `def _take_motion(self) -> None:`

> As many frames as fit in a slice of a frame, then give the loop back.
>
> Scaling and converting the whole animation takes about as long as four
> frames are allowed, and it lands on a track change where there is
> nothing to spare. The list is filled a slice at a time instead;
> motion_frame reads whatever is in it, so the animation starts on the
> first slice and simply loops shorter until the rest arrives.

### `LyricsView.motion_frame`

**line 21748** — from the docstring, `def motion_frame(self):`

> The frame due now, or None when there is no animation to play.
>
> A picture dropped on this song beats the animation, for as long as
> that song is playing. Both are drawn through here -- `motion_frame()
> or art_full` -- so an animated cover simply went on playing over the
> image that had just been dropped, and the drop looked like it had
> done nothing at all.

### `LyricsView.paste_to_play`

**line 21944** — from the docstring, `def paste_to_play(self) -> None:`

> Ctrl+V on the lyrics: play what was pasted.
>
> A Spotify track or album link or URI plays that track or album, from
> its first song. Any other link pasted_links reads -- a Spotify artist or
> playlist, or any Spotify link while Spotify is away -- is played
> through the home page (play_link). A bare id is asked of the player, which knows which of
> the two it is -- see on_id_played. Anything else is a search, and the
> first SONG it finds plays -- not an album or an artist, which would be
> a different thing to have asked for. Finding nothing leaves the player
> alone: a paste that misses is not a reason to stop what is playing.

### `LyricsView.overlay`

**line 22074** — from the docstring, `def overlay(self) -> str | None:`

> Which panel is up, as one name -- the single source of truth.
>
> These five used to be tested independently in six places (paintEvent and
> the five input handlers), each in a DIFFERENT order. That was only safe
> because every open_* setter clears the others by hand, so at most one is
> ever true; the orders were therefore equivalent, not correct. Adding a
> view that replaces the base layer rather than sitting over it would have
> doubled the number of hand-kept orderings, so they collapse to this.

### `LyricsView.vol_wheel`

**line 22158** — from the docstring, `def vol_wheel(self, ev) -> bool:`

> The volume, if the pointer is on its bar. Otherwise not ours.
>
> Last of the wheel's branches on purpose. Everything above it has
> already turned the wheel away in the views where this rect means
> nothing -- browse and detail paint through `_paint_browse`, which
> never touches `vol_rect`, so the one left over from the last lyric
> frame would still be sitting there claiming a strip of a screen that
> is not showing it.
>
> Hit-tested with the same slack the drag and the hover use. The bar is
> drawn four pixels tall because it is the control you reach for least,
> and a wheel is aimed no better than a click is.

### `LyricsView.field_key`

**line 22647** — from the docstring, `def field_key(self, fld, ev) -> tuple[bool, bool]:`

> One key press into one of the hand-drawn boxes: whether the box
> had a use for it, and whether what is in it changed.
>
> Both answers are needed and they are not the same one. A caller only
> searches again when the TEXT changed -- a caret key is not a new
> search -- and browse only keeps the key from the transport when the
> box USED it, so Left still seeks on a tab with no box on it.

### `LyricsView.said_clipped`

**line 22655** — from the docstring, `def said_clipped(self, fld) -> None:`

> Say so if the last thing to go in was too long for the box.
>
> Worth a line of its own because the alternative is silence: a token
> pasted into a full box keeps its first however-many characters and
> looks like a token, and the first anybody would know of it is Genius
> refusing them.

### `LyricsView.enter_fullscreen`

**line 22685** — from the docstring, `def enter_fullscreen(self) -> None:`

> Fill the screen, and on Windows actually fill it.
>
> Everywhere else showFullScreen is the whole of this.
>
> On Windows it leaves a border, and the border is DWM's rather than
> Qt's -- Windows 11 draws a one-pixel line round a top-level window
> and rounds its corners, and it goes on doing both to a window that
> has been given the screen. Neither is a window style anybody can drop:
> FramelessWindowHint does not remove them, it INVITES them, because a
> popup with no frame of its own is exactly the shape DWM decorates. So
> that was tried and it made the report worse -- a border, and now
> rounded corners on it too.
>
> The two attributes below are the ones that actually answer: do not
> round this window, and draw no border colour on it. Both are Windows
> 11 and both are refused with a shrug on Windows 10, which is why the
> call is wrapped and its result ignored.
>
> The geometry is then asked for outright as the screen's rectangle,
> which is a separate fix for a separate thing: at a fractional display
> scale the logical-to-physical rounding can leave a strip of desktop
> showing along one edge with nothing decorating anything.

### `LyricsView.set_on_top`

**line 23008** — from the docstring, `def set_on_top(self, on: bool) -> None:`

> Keep the window above the others, by whichever route works here.
>
> The Qt flag is still set first: it is what works on X11, and it is
> harmless where it does not. On Wayland it is quietly ignored, so KWin is
> asked directly -- and if neither route is available the toast says so
> rather than claiming a state the window is not in.

### `LyricsView.clear_bg`

**line 23025** — from the docstring, `def clear_bg(self) -> bool:`

> Whether the wall is nothing at all -- ASKED, and also delivered.
>
> The mode alone is not enough to paint on, and trusting it shipped a
> black window to every Windows user who tried it. Clear mode fills the
> scene with transparency and lays only the dim over it, and
> WA_TranslucentBackground brings WA_NoSystemBackground with it, so Qt
> stops clearing the backing store. Where the surface really does carry
> alpha that is exactly right: the window is glass. Where the platform
> quietly declined to give it one, nothing clears and nothing fills, and
> what reaches the screen is an uninitialised buffer -- black -- with
> the lyrics drawn on top of it and no clue as to why.
>
> So the wall is only taken away once the window we ACTUALLY got says it
> has somewhere to put the alpha. Where it has not, every painter here
> reads False and draws what it drew before, which makes an unavailable
> clear degrade into solid rather than into a hole. See `_clear_live`.

### `LyricsView.page_ink`

**line 23030** — from the docstring, `def page_ink(self, alpha: int = 255) -> QColor:`

> What browse, the song page and the review are laid on.
>
> Those three are not the lyric view: they are paragraphs of small type,
> rows of credits, numbered lines. Handing them the clear wall as it is
> would put all of that straight onto somebody's wallpaper. So in clear
> mode they keep CLEAR_PAGE of the ink -- see-through enough that the
> window is still visibly glass, solid enough to read a credit off.

### `LyricsView.frameless_clear`

**line 23035** — from the docstring, `def frameless_clear(self) -> bool:`

> Whether the window goes without its frame: in clear mode, everywhere.
>
> On Windows it has to. A top-level window there only gets per-pixel
> alpha as a layered window, and Qt only makes one of those for a
> frameless window -- WA_TranslucentBackground on a framed one gets an
> opaque surface, and the clear wall comes out black (Qt's own docs for
> the attribute say so). Elsewhere it is not needed for the glass, but a
> title bar hanging over see-through lyrics is the same look on every
> desktop, so the frame goes on all of them alike.
>
> No frame means no title bar and no borders, so `frame_press` does
> their job while this is on. The Windows half is UNVERIFIED: there is
> no Windows here. If a window still gives no alpha channel,
> settle_clear measures that and falls back to solid, as before.
>
> clear-framed is the one that keeps it, for desktops that composite a
> framed window's alpha. On Windows that is exactly the opaque surface
> described above, so there it settles to solid like any window without
> alpha.

### `LyricsView.frame_press`

**line 23073** — from the docstring, `def frame_press(self, ev) -> bool:`

> Move and resize a window that has no frame to do it with.
>
> A band FRAME_GRIP pixels wide along each edge resizes, and Alt with a
> left drag anywhere moves, both handed to the window manager through
> startSystemResize/startSystemMove. Plain drags inside the window are
> left alone, because the lyric view already uses them.

### `LyricsView.apply_clear`

**line 23099** — from the docstring, `def apply_clear(self, say: bool = False) -> None:`

> Give the window the surface its background mode needs.
>
> Qt fixes whether a window has an alpha channel when the PLATFORM
> window is made, not when WA_TranslucentBackground is set. Setting the
> attribute on a window that is already up leaves
> `windowHandle().format().alphaBufferSize()` exactly where it was --
> measured here on xcb, on wayland and on offscreen, all three -- and
> the clear wall then paints into an opaque surface and comes out
> black. So the native window is thrown away and made again, which is
> the documented way to get a different surface format and costs one
> frame plus a flicker.
>
> Nothing is torn down inside the event that asked for it -- the key
> press or the menu row is being delivered to the very window about to
> go -- so the swap is queued for the top of the next loop instead.

### `LyricsView.settle_clear`

**line 23122** — from the docstring, `def settle_clear(self, say: bool = False) -> None:`

> Ask the window we got whether the clear wall is on or off.
>
> `format().alphaBufferSize()` is the platform's answer rather than
> ours: Qt resolves it when the native window is made and reports what
> it ended up with, which on xcb, wayland and offscreen alike is 8
> where the request took and 0 or -1 where it did not. That is the only
> thing worth believing here -- the attribute is what we asked for, and
> asking is not getting.
>
> Two different failures reach this, and the toast tells them apart
> because the answers are different. A platform that never gave us an
> alpha channel cannot do clear at all and the window stays solid. A
> platform that did, on a desktop with nothing compositing, gives a
> window that is see-through onto nothing -- see clear_ok.

### `LyricsView._remake_window`

**line 23143** — from the docstring, `def _remake_window(self, say: bool = False) -> None:`

> Throw the platform window away and make another one.
>
> Everything Qt-side survives it: the window flags, so a window kept
> above by the X11 hint is still kept above, and every widget attribute
> set in __init__. The geometry and the fullscreen state are put back
> by hand. What does not survive is KWin's own keepAbove, which was a
> property of the surface we just destroyed, so it is asked for again.

### `LyricsView.apply_backdrop`

**line 23165** — from the docstring, `def apply_backdrop(self) -> None:`

> Ask the desktop to put a material in the pixels we are leaving empty.
>
> On Windows 11 that is DWM's own mica or acrylic -- see _dwm_backdrop,
> and note it needs 22H2. On KDE any of them asks KWin's Blur effect
> (_kwin_blur, where PyQt runs on the system's Qt). Everywhere else the
> answer is no, and what shows through is whatever is behind the window.
>
> AUTO ASKS FOR NOTHING, which is not where this started. It shipped
> asking for mica, and the first thing Windows users reported was a
> black window. The black had a different cause -- see clear_bg -- but
> it was found with two untested mechanisms layered on each other, and
> only one of them is needed for a see-through window. So the default
> is now the plain glass that the rest of this file can actually be
> reasoned about, and the materials are opted into by name. They remain
> unverified: there is no Windows here to check them on.

### `LyricsView.autosave`

**line 23335** — from the docstring, `def autosave(self) -> None:`

> Write settings as soon as they change, not only on a clean exit.
>
> closeEvent never runs if the process is interrupted -- Ctrl+C from the
> terminal or a SIGTERM dropped everything the user had just set. Polling
> for a change is cheap (19 scalars) and catches every path that mutates
> them: the menu, the keys, anything.

### `log_to_file`

**line 23418** — from the docstring, `def log_to_file() -> pathlib.Path | None:`

> Point this process's output at that file. The path, or None.
>
> THE DESCRIPTORS AS WELL AS THE PYTHON OBJECTS. Qt writes its own warnings
> from C++ straight to fd 2 and they never pass through sys.stderr, and they
> are half of what is worth having here -- "endPaint() called with active
> painter" is Qt's account of the same bad frame the traceback below is
> Python's. Both land in one file, in the order they happened.
>
> One previous run is kept. A log that grows for the life of an install is
> a log nobody opens, and the run before this one is the only other one
> anybody ever wants: it is where the fault that closed the window is.

### `hide_own_console`

**line 23440** — from the docstring, `def hide_own_console() -> None:`

> Drop the console window Windows opened just for us, and keep its output.
>
> Double-clicking a .py file runs it under python.exe, which allocates a
> console -- so a black window sits behind the lyrics for the whole session.
> pythonw.exe does not, which is what spicy-lyrics.pyw is for, but the file
> people reach for is this one.
>
> Only a console we own is hidden. Started from a terminal, the console is
> shared with the shell that launched us, and taking that away would close
> the window someone is working in and swallow every message meant for them.
> GetConsoleProcessList tells the two apart: a console made for us has one
> process attached, an inherited one has at least the shell as well.
>
> A hidden console is a console nobody can read, so the output goes to the
> log instead -- otherwise this call is the second of the two ways a Windows
> run ends up with nowhere to print a traceback, and the one that looks like
> it worked. The other is pythonw, which install_excepthook catches.

### `install_excepthook`

**line 23463** — from the docstring, `def install_excepthook() -> None:`

> Keep one bad frame from taking the window down with it.
>
> PyQt turns an unhandled exception inside a slot into a call to qFatal(),
> which aborts the process outright -- a single undefined name in tick() once
> killed this app three times in a row, with no window and no message, only a
> core dump. An installed hook takes precedence over that path, so the frame
> is lost and the event loop carries on.
>
> Repeats are folded deliberately. tick() runs sixty times a second and
> anything that fails once there usually fails every frame after, so printing
> each one would bury the first traceback -- the only one that says where the
> trouble started -- under thousands of identical copies, and take the journal
> with it.
>
> None of which is worth anything where the messages have nowhere to go, and
> on Windows they have nowhere to go: the launchers are .pyw files, pythonw
> leaves sys.stdout and sys.stderr as None, and printing to None is not an
> error -- print returns silently rather than raising. So every traceback
> this has ever folded on Windows went into nothing, which is why a window
> that stopped drawing there could not be told from one that was drawing
> something empty. log_to_file is what it prints to instead.

### `watch_stalls`

**line 23505** — from the docstring, `def watch_stalls(app) -> None:`

> Write every thread's stack to STALL_LOG when the window stops answering.
>
> A freeze leaves nothing behind once it is over, and catching one live
> takes root and a tool most people do not have. So the event loop re-arms
> faulthandler's alarm once a second; if STALL_AFTER seconds pass without
> that, the alarm's own thread writes where each thread is, while it is
> still there. The next beat after the stall says how long it lasted.
> Costs nothing while the loop is running. A suspended machine wakes up
> looking like a stall, and is written down like one.

### module level (comment)

**line 265** — before `FOLLOW_CLOSE = 0.15`

> How close Spotify has to be to the editor's file to be left alone. It was
> FOLLOW_DRIFT, a third of a second, so a Spotify walked along under a take
> could sit anywhere inside that and stay there -- which, heard, is "always a
> bit behind, by a different bit each time". Its reported position agrees
> with the editor's to about 50ms when it is where it was sent (measured off
> the follow log), so 0.15s is well clear of its own noise. FOLLOW_DRIFT is
> still what counts as the editor having gone somewhere NEW.

### `MotionArt._decode` (comment)

**line 5808** — before `cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",`

> A first play decodes 35 seconds of video on every core at normal
> priority, and the window is drawing over the top of it: measured
> with the same command against a local clip, paint time doubled and
> thirteen frames in the three seconds after a switch ran long. Two
> decode threads, one filter thread and a low priority put it back
> to one -- the animation arrives a little later, nothing else does.

### `LyricsView.tick` (comment)

**line 13045** — before `now = self.frame_now()`

> Measured, not taken from eff_hz: a frame that paints slower than the
> timer asks is exactly the case the easings must keep pace through.
> Clamped so the first step after an idle stretch, or a hidden window,
> moves a few frames' worth and not a jump. On the frame's own time
> (see _vsync_frame), which can sit a little either side of the wall
> clock -- hence the floor.

### `LyricsView` (comment)

**line 18486** — before `def dr_u(self, W: int, H: int) -> float:`

> ------------------------------------------------------------ the drawer
> The settings, in the new interface: a panel down the right-hand side,
> so the lyrics stay in view while they are being changed, and a control
> for each kind of setting that looks like what it does -- a switch for
> on/off, side-by-side buttons for a short list, a ▾ list for a long one,
> a slider for a number, a labelled button for something that happens
> once. The rows are the menu's own (MENU, menu_get, menu_set), so the
> classic menu and this one can never disagree about a value; only the
> order is different here, with headings, and rows that do not apply to
> what is picked are left out.

---

## Lift — 2026-10-11

Comments lifted out of `mild-lyrics/lyrics_gui.py` on 2026-10-11, from PR #2 as it was reviewed; the line numbers are that day's.

### `LyricsView.__init__`

**line 9240** — before `self.save_fetched_dir = str(_disk.get("save_fetched_dir") or "")`

> Where saved TTMLs go (Settings ▸ Storage ▸ Save TTMLs to). Held here so
> the menu can show the choice and autosave can keep it; save_lyrics hands
> it to saves.from_player. Read from the window, not gui.json, so
> --no-persist keeps a choice made in that run and ignores the one on disk.

### `LyricsView.pick_fetched_dir`

**line 20725** — from the docstring, `def pick_fetched_dir(self) -> None:`

> The editor's own room is not in Settings on purpose: where a piece of
> timed work is written is the writer's call, made with Save as at the
> moment they make it. A folder that cannot be written to is the same
> 'question nobody answered' the --save-dir fallback already handles: the
> TTMLs go to the Music folder and the save says so.


---

## Lift — 2026-09-26

Comments lifted out of `mild-lyrics/lyrics_gui.py` on 2026-09-26; the line numbers are that day's.

### module level

**line 310** — before `APP_VERSION = "1.0.5"`

> The release this is. Kept in step with the git tag (vX.Y.Z) by hand: the
> updater compares it with GitHub's latest release, and the changelog shown
> after an update is every release after the one recorded last time.

**line 465** — before `TROUBLE_MUTE: set = set()`

> Sources whose trouble is not worth saying out loud. Empty: LyricsPlus was
> the only one, its door timed out on nearly every song, and it is gone.

**line 561** — before `FRAME_GRIP = 6`

> How wide a strip along each edge resizes a window that has no frame.

**line 564** — before `CLEAR_PAGE = 216`

> How solid the content pages stay on the clear wall. They are small type
> over an unknown desktop, so they keep a wash the lyrics do not need.

**line 570** — before `VIZ_HUSH = {"lines", "prism", "confetti", "halo"}`

> Modes drawn in hairlines, dimmed across the middle where the lyrics sit.

**line 694** — before `_PRESET_KEYS = {`

> Sets of settings to try, each on whatever renderer is picked: a preset
> never changes the renderer, which is a choice of its own. Only the look:
> nothing about sources, the player, this machine's clock or the window's
> own chrome. "Mild Lyrics" is DEFAULTS; "Spicy Lyrics" is the value of each
> knob at which the Spicy Lyrics renderer draws exactly what the extension
> does -- a multiplier of 1 on its own number, 0 for something it does not
> do -- over its default animated cover background.

**line 724** — before `"amll": {`

> Apple Music-like Lyrics: the amll renderer reads Word pop and Word rise
> as multipliers on AMLL's own emphasis and float, so 1 is AMLL; it has
> no line drop, no scroll lead, and draws over the cover's mesh.

**line 744** — before `"bg_mode": "mesh", "mesh_style": "blobs", "viz": 0.0,`

> Spicy's dynamic background: the cover's colours as moving blobs.

**line 746** — before `"interlude": 3.0, "hide_gaps": True,`

> getLyricsBetweenShow(): dots for a gap of three seconds or more,
> on a musical line that has no height while it is not on.

**line 759** — before `SHARE_SECTIONS = ("Text", "Motion", "Background", "Romanisation", "Timing",`

> What a settings code carries: how the lyrics look and move, and nothing
> about where they come from or this machine. Sources, blends, the player,
> browse, updates and storage are somebody's own setup, not a look to pass on.

**line 764** — before `SHARE_SKIP = {"genius_token", "offset", "unpause_delay"}`

> Left out of those: a credential, and two clocks measured against this
> machine's own audio path, which mean nothing on somebody else's.


### `_dwm_backdrop`

**line 983** — before `dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(Margins(-1, -1, -1, -1)))`

> -1 on every side is "the whole client area is glass", which is
> what lets the material reach past the frame and under our words.


### module level

**line 1097** — before `NO_LEAD = set(",.!?;:)]}\u2019\u201d\u3001\u3002\uff0c\uff0e\uff01\uff1f"`

> What may not open a row: it belongs to the word before it, so a break that
> would fall in front of one falls in front of that word instead.


### `wrap_shape`

**line 1167** — before `carry = rows[-1][prev_at[1]:]`

> Take the word before along, rather than open the row
> with a comma -- unless it opened its own row already.


### `rtl_row`

**line 1235** — before `en[2] = " \u200e" + txt[:-1]`

> The LRM makes the fragment's own paragraph left to right, so
> the space is drawn where it is written. Qt otherwise takes the
> direction from the Arabic and puts the space back on the right.

**line 1246** — before `segs, k = [], 0`

> Segments in reading order: each right-to-left word alone, and each run
> of left-to-right words (with any neutral words between them) together.

**line 1278** — before `return sorted(((x + dx, w, t, i, ci) for x, w, t, i, ci in out),`

> Back into reading order: only the x moves. Everything that walks a row
> in time -- the sweep, the rise, words_of -- still walks it first to last.


### module level

**line 1512** — before `WIN_NAMED = ("{a45c254e-df1c-4efd-8020-67d146a850e0},2",`

> Windows keeps an endpoint's names under its own key, as property-store
> values rather than as named ones. The first is the whole label the sound
> settings show ("Headphones (WH-1000XM4 Stereo)"), the second is just the
> part the user is allowed to rename, the third the driver's word for the
> hardware. Any of the three is a name; the interface path is not.

**line 1522** — before `WINRT_NAMESPACES = ("windows.media.control", "windows.foundation",`

> Every namespace the media transport touches, not only the one it imports
> by name. winrt ships one distribution PER NAMESPACE and a plain
> `pip install winrt-Windows.Media.Control` brings only winrt-runtime with
> it -- the others have to be named too (not through `[all]`, which pulls
> in most of the Windows API). What that produces is a half install: the control module imports, so
> anything that probes with that one import thinks the transport is there,
> and the first real call then dies on winrt.windows.foundation, where the
> async operation and the session vector actually live. winsdk is one
> distribution with all of them in it and answers this the same way.


### `windows_output`

**line 1681** — before `name = ""`

> Asked for separately from the id: Devices.Enumeration is its own
> package and an install can have one half and not the other, and
> half of this is still worth having -- the id is what the offset is
> keyed by, and there are two more ways below to come by a name.


### module level

**line 2014** — before `BREAK_GAP = 3.0`

> A gap between two sung lines at least this long is an instrumental break,
> and Up/Down stop at its start as well as at the lines around it.


### `song_from_video`

**line 2129** — before `tagless = re.sub(r"^\s*[\[【(][^\]】)]*[\]】)]\s*[-–—|:]\s+", "", title)`

> A label's category tag in front of the whole thing -- Monstercat's
> "[Indie Dance] - WRLD - Little Too Close" -- is neither artist nor song.
> Taken off only where a dash follows it, so a title that merely opens on
> a bracket keeps it.


### `spotify_track_id`

**line 2168** — before `if (re.fullmatch(r"[A-Za-z0-9]{22}", text) and re.search(r"\d", text)`

> A bare id is 22 characters of mixed case and digits. A plain word of
> the same length is a search, not an id.


### `spotify_running`

**line 2250** — before `got = subprocess.run(["pgrep", "-x", name], capture_output=True,`

> -x matches the process name exactly, so this pgrep cannot find
> itself or the shell it runs in.


### `PortHelp.__init__`

**line 2270** — before `self.setFixedWidth(max(560, QFontMetricsF(self.font())`

> A fixed width, so the wrapped labels are measured at the width they
> are drawn at -- with only a minimum, Qt sized them for a narrower
> window and left gaps between the steps.

**line 2338** — before `self.resize(self.width(), max(200, box.heightForWidth(self.width())))`

> Exactly as tall as the text needs at this width.


### `SessionTransport.__init__`

**line 2432** — before `self._ok: dict = {}`

> Insertion-ordered, oldest first, so the cap can let go of the
> tracks cleared longest ago -- see allow().


### `SessionTransport._read_any`

**line 2511** — before `self._last = got`

> A seek, or the gap between two tracks: a moment of not playing
> is not a reason to go and find somebody else. Looking now found
> the browser's second copy of the same video (the bridge and the
> browser both publish it), and switched to it and back.


### `SessionTransport.allow`

**line 2664** — before `self._ok.pop(tid, None)`

> Trimmed from the old end, never emptied. Clearing the lot at 256
> un-cleared the track being played too, and nothing vets a track a
> second time -- so after enough skips the player stopped being
> followed at all, its song held back as if it were a video.


### `CdpTransport._pick`

**line 3156** — before `if self._eng_moved < ENGINE_TRUST:`

> A build that only refreshes the engine on a state change
> still refreshes it on a seek -- once, to the target, and
> then stands still again. Taking that one change as the
> engine being back pulled the words back to the seek target
> for the whole STALE_HOLD, and they sat there until control
> took over again. Once the engine has been caught standing
> still, it has to be SEEN running before it leads again.


### `_thumb_bytes`

**line 3611** — before `return box.get("value", b"") if done.wait(0.75) else b""`

> Some WinRT projections never resolve a thumbnail read. Art is optional;
> the lyrics window is not.


### `BackupTransport._follow`

**line 3995** — before `return self._good`

> One failed read -- a seek or an unpause on Spotify's side does
> this -- is not the player going away. Handing over here gave
> the clock whatever the other side last saw, a paused tab's
> track as often as not, and the window reloaded for it and then
> reloaded again when Spotify answered a moment later.

**line 4020** — before `playing = other is not None and other.get("status") == "Playing"`

> A paused player on the other side is only worth going to when
> this one has actually gone. "Nothing playing" here is also what
> a skip looks like for a moment -- the next track not started, or
> held back until it is vouched for -- and handing over then put
> whatever song the other player had open on screen for a second.

**line 4028** — before `self.on_backup = not self.on_backup`

> The same track on the other side is the same song told a
> second way, and the bus says Playing a beat before the port
> does on an unpause: the port catches up on its own, and it
> is the better clock (see make_transport).


### `Clock._apply`

**line 4182** — before `seeked = resumed and abs(pos - held) > SEEK_JUMP`

> A resume somewhere else entirely is a seek -- a browser reports
> one as a moment of "paused" -- and not an unpause to measure.


### `Clock._pin`

**line 4297** — before `if getattr(self.io, "app", DEVICE_APP) != DEVICE_APP:`

> Spotify's drift is what this corrects. A browser reports "paused"
> for a moment in the middle of a seek, still at the OLD position,
> and pinning it there sent the video back to where it was.


### `Fetcher._spotify_id`

**line 6771** — before `try:`

> Searched once, with the song's name as the catalogue spells it
> rather than as a video title does. The card is the same Apple
> answer the window asks for anyway (LS._once), so this costs nothing.

**line 6783** — before `if named != meta:`

> The catalogue's spelling first, and the player's own after it:
> a card that was sure of the wrong song is not the last word.

**line 6789** — before `for ask in (lambda: self._catsearch(`

> The desktop client first; then, with it closed, the Web API
> with the token kept from it (see _grab_spotify_token).


### `Fetcher._load`

**line 6855** — before `self._stood_in = tid`

> Every source switched off means no lyrics, not the last ones
> kept: a stored answer is still some provider's words.

**line 6860** — before `self._stood_in = tid`

> What was kept for this track goes up before anything is asked.
> It used to wait behind the Spotify id lookup and Spicy Lyrics'
> answer, so a song playing in another player sat on "Loading
> lyrics…" for a round trip or two with its words on disk.

**line 6874** — before `sid = self._spotify_id(tid) if self.spotify_lookup else None`

> Not a Spotify track: Spicy Lyrics is asked by Spotify id, so
> there is nothing to ask it with unless the reader said the
> song may be looked up on Spotify under their own session.


### `Fetcher._shaped`

**line 6941** — before `return LS.no_overlap(body)`

> Last, over whatever every step above left behind.


### module level

**line 7105** — before `PX_TOL = 0.03`

> The pixel half of the test, in ems of the lyric font: a pixel at the
> 32px the lyrics usually draw at. In ems so a resize, which changes the
> pixel size and does not rebuild the lines, does not change the verdict.


### `_join_flat`

**line 7200** — before `sung = [_sung_core(c) for c in cores]`

> Only what is SUNG is weighed. Punctuation at either end of a piece --
> the ?" of "cal·lin'?\"" -- is swept by the fill but not by the voice, so
> neither drawing follows the voice across it; counting it made that word
> look held on "cal" by 127ms when "cal" and "lin" are sung evenly.

**line 7214** — before `or any(c.isspace() for c in run[k][2])`

> a space inside the "word" means it is two: a blend flagged
> 'me, "' as part of "Never", and joining them made two sung
> words one sweep and one lift

**line 7219** — before `best: list = [(0, 0.0, 0)] + [None] * n`

> best[j]: (fragments, worst error, where the last group starts) for run[:j]


### `retime_roman`

**line 7303** — before `aside = set()`

> A bracketed aside Genius adds that the lyric itself does not have --
> "Hora say no (Say no)" over 「ほら Say No」 -- matches the same syllables
> as the words it echoes, and took them: the real "say no" went untimed
> and the aside was the one that filled. Where the line has no brackets
> of its own, the aside is left out of the matching; it stays untimed,
> or takes a syllable nothing else claims.

**line 7317** — before `said = GR.key(" ".join(t for _s, _e, t, _p in base)`

> Only an aside the lyric does not sing: where Genius has the words
> more times than the line's own reading does. "say no" is read once
> and written twice, so the bracketed one is the extra; 自分 is read
> four times and Genius writes "jibun (Jibun) jibun (Jibun)", all
> four of them sung.

**line 7339** — before `if _thin is None:`

> Arabic and Hebrew leave their short vowels unwritten, so a reading
> derived from the letters has none ("wfya") and Genius has them all
> ("wa fia"). Matched letter for letter the vowels are the noise that
> decides it: "fia" found nothing but a stray "a" and was left untimed.
> The consonants are what both spellings share -- but not always better:
> "Wulay wulay lalaha" over أو لاي لاي ليلا ("aw lay lay lila") matches
> on its vowels and loses a word without them. So both are tried, and
> the one leaving fewer words without a clock is kept; a tie keeps the
> letter-for-letter match, which is what every other script gets.

**line 7391** — before `claimed = {o for o in owner if o is not None}`

> Unmatched letters at either end of a WORD belong to that word's own
> syllables, not to its neighbours'. A word starts where a syllable
> starts: 酷く read "koku" by the dictionary and "hidoku" by Genius left
> "hid" matching nothing, and filling forward hung it on the "wa" before
> it -- drawn as "wa hid".
> And where the syllable next to the word is one no matched letter
> claimed, the unmatched end goes THERE: 居着いてる read "kyotsuiteru"
> left the "i" of "itsuiteru" unmatched, and put on 着 it left 居 with
> nothing, so the romanisation stood still for a syllable.

**line 7433** — before `whole = GR.similar(theirs, mine) < 0.6`

> Where the two only loosely agree -- アイウォンチュー under "I Want You"
> -- the letters that do match are coincidences: cutting a word at them
> drew "Yo|u", and following them hung both halves of the line on its
> first syllable. Hang each word whole where it falls by proportion.

**line 7457** — before `first = owner[c]`

> A stray letter or two is no evidence for cutting a word apart:
> the "a" of "ima" (今) found in "nyani" (夜に) sent the end of the
> word to the next syllable. It starts where it starts, and runs
> on over any syllables after it nothing else has claimed --
> 身体 read "shintai" takes "karada" over both, shared out by how
> long each one's reading is.

**line 7467** — before `while (span and span[-1] + 1 < len(base)`

> ...and no further than the word is long: "karada karada" over
> 身体 身体 took three syllables for the first and none for the
> second.

**line 7507** — before `timed_here = [a for a in run if a[0] in anchored]`

> Only the words that are really on this syllable share its time. A
> word Genius has and the file does not time -- "(Dandan, da-da-dan)"
> in 革命道中, the "Ah" before "hora mata" -- is drawn untimed, and
> while it took a share here it pushed the real words late: "He"
> started 0.86s after the file says.

**line 7527** — before `if a[0] in anchored:`

> An untimed word beside the one word on a syllable gets no
> time either. Given the syllable's, it became the "next word"
> the line after this trims ends to, and "desho" in
> "Shimacchau desho, ah-yeah" ended the moment it began.

**line 7537** — before `used = {o[4] for o in out if o[2] in anchored and o[4] is not None}`

> A word with nothing in common with our reading -- "fuu" for 風, which
> the dictionary reads "kaze"; a censored "****" -- was left untimed. It
> belongs to whatever syllables between its anchored neighbours no
> anchored word took, which is where the original has it.

**line 7557** — before `run = out[i:j + 1]`

> Cut at the syllables, by how long each one's reading is, and
> each piece on its own syllable's clock -- never across the gap
> between two of them, which is time the file gives to nobody.


### `LyricsView.__init__`

**line 8245** — before `self._clear_live = self.bg_mode == "clear"`

> Assumed until the window exists and can be asked; apply_clear is
> called once it does, from main() and from every later switch.

**line 8280** — before `self.resync_reset = (args.no_persist`

> Auto resync is off by default now, and was on for everybody before:
> turned off once, on the first start that knows this, and theirs to
> turn back on after that. A flag rather than a version compare, so it
> happens exactly once whatever version they came from.

**line 8318** — before `self.credit_faces: list = []`

> Community sync makers' pictures: what is on screen, and what has
> been fetched. See credit_face.

**line 8325** — before `self.review_side = False`

> The review sidebar, and the renderer the settings hold while a
> review mode has swapped in another (None when nothing is swapped).

**line 8330** — before `self._rev_hand_until = 0.0`

> Until when the sidebar is left where a hand put it, rather than
> kept level with the line being sung.

**line 8334** — before `self._rev_fresh = True`

> Set when the list was opened or moved by hand: the next aim is
> taken whichever way it points.

**line 8408** — before `self.credit_hot: list = []`

> The credit block's links, which are the lyric column's rather than
> the chrome's and so cannot live in `hot`: the column is painted
> first and `hot` is emptied after it, for the header. Filled by
> renderers._paint_credits, read by credit_at.

**line 8458** — before `self.review_ignored: list[dict] = []`

> What this session ignored, newest last, so U can take it back.


### `LyricsView.retune_frames`

**line 8681** — before `cap = self.fps_cap if self.fps_cap and self.fps_cap > 0 else hz`

> No cap (0) is the default: the frames follow the screen. The old
> default of 60 divided a 144Hz panel by three, to 48 frames a second
> -- fewer than a 60Hz one got -- and 165Hz to 55.


### `LyricsView.on_update_found`

**line 9053** — before `self.toast(f"Mild Lyrics {rel['tag'].lstrip('v')} is out — "`

> Only told, not updated: a message that stays a little longer than
> the usual ones, since it is the one thing this start has to say.


### `LyricsView.vet_pending`

**line 9214** — before `self.vet_sent.discard(tid)`

> Asked again, and actually asked: a track sent once and never
> answered -- its walk overtaken by a skip -- stayed "sent" for good,
> and was held back from the screen for as long as it played.


### `LyricsView.poll`

**line 9381** — before `same = bool(self.lines) and self.same_song(song, was_song)`

> The same song under another id -- the other player's copy of it,
> or the same player saying it a second way -- keeps its words up
> and is not resynced. Every handover between two players that
> both had it open used to blank the lyric, load it again, and
> then jump the clock, which is the "refresh" nobody asked for.


### `LyricsView.apply_romaji_fixes`

**line 9451** — before `fix = auto.get(f"{text}#{nth}") or auto.get(text) or ne.get(text)`

> By which time round this line is first: a repeat can be
> spelled differently each time, and keyed by its text alone
> every repeat took whichever was written last. Not by its
> position in the list -- the window adds lines of its own
> (the dots of an interlude, the credits), and a position
> kept from one layout put every romanisation after the first
> of them one line late in the next.

**line 9460** — before `fix = None`

> A "romanisation" that is the line itself says nothing new,
> and drawn under it the line just appears twice.


### `LyricsView._follow_to`

**line 9829** — before `self._follow_tries = 0`

> The gap closed: it went where it was sent, or most of the way.
> Closing rather than merely MOVING, because a player left running
> moves on its own -- a second of playback is three times
> FOLLOW_DRIFT -- and reading that as an answer would retire the
> count altogether and with it the one case it is for, a player
> that takes seeks and ignores them.


### `LyricsView.source_name`

**line 10617** — before `first, *rest = [p.strip() for p in made.split(" + ") if p.strip()]`

> What the blend was actually built from, which it records. The
> fixed names above say "Apple Music" for the lines whoever they
> came from -- a blend over Spicy Lyrics' Spotify copy was
> credited to Apple Music.

**line 10627** — before `return "unknown source"`

> A source this build no longer has -- a document cached before it
> was taken out, which LS.stored will still put up while the walk
> runs. Say that rather than falling through to the line below,
> which would credit the words to Spicy Lyrics: naming the wrong
> source is worse than naming none, and it is the one thing a
> credit line must never do.


### `LyricsView.this_sync_by`

**line 10764** — before `return next(iter(LS.person_list(LS.credits_of(self.body))), None)`

> Through person_list, which keeps the name and the id and drops the
> rest: a credit also carries the page it links to (see
> made_by_linked), and that belongs under the lyrics rather than in
> one of these two lists or in the settings file they are written to.


### `LyricsView`

**line 11063** — before `GAP_EASE = 0.1`

> How long a gap line takes to open as it starts, and to shut as it ends.


### `LyricsView.layout_line`

**line 11407** — before `held = "⠀" * len(RD.FACE_GAP)`

> A face's gap is whitespace, which the wrap would fold into one
> space; it rides through as a word of its own and comes back.


### `LyricsView.ruby_rows`

**line 11453** — before `return [], None`

> Furigana is for Japanese. Over a Chinese line it was pinyin,
> drawn a second time under the line by the romanisation.


### `LyricsView._paint_art_halo`

**line 12987** — before `m = box.width() * 0.08`

> The ring of triangles reaches past half the span; drawn a little
> smaller than the square, it stays inside where the cover's edge was.


### `LyricsView._paint_header`

**line 13112** — before `mirrored = self.art_side == "right"`

> With the art sent right, the strip is the mirror of itself: cover
> and title against the right edge, left of the settings button, and
> the volume slider over on the left where they used to be.

**line 13170** — before `gear = self.gear_box(W)`

> Left of the settings button, level with its middle.


### `LyricsView.gear_box`

**line 13180** — before `side = self.review_side_w() if self.art_side != "right" else 0.0`

> Clear of the review sidebar, which takes the right edge when the
> art panel is on the left.


### `LyricsView.help_layout`

**line 13356** — before `th = QFontMetricsF(self.help_title_font(W)).height()`

> Measured, not assumed: the title's font grows with the window, and
> a fixed 30px line cut the bottom off "Keys" on a large one.


### `LyricsView.review_plan`

**line 14193** — before `sep = fm.horizontalAdvance(RV.SEAM)`

> The gap a seam is drawn in the middle of. Measured on the mark the
> notes underneath write it with (RV.SEAM), so the bar the eye follows
> down the line and the character it reads in the sentence take the
> same room.


### `LyricsView._paint_review`

**line 14332** — before `sung = (chip.start is not None and chip.end is not None`

> The piece being sung takes the seam colour, and lets
> go of it as the next one starts.


### `LyricsView._paint_review_marks`

**line 14714** — before `prev = None`

> The syllable splits, in the review page's seam colour: a
> thin bar wherever one timed piece of a word meets the next.


### `LyricsView.review_level_with_lyrics`

**line 14906** — before `own = type(self.render).rest_top is not RD.Renderer.rest_top`

> The line the COLUMN is aiming at, which is not the one being sung:
> a scrolling column moves to the next line scroll_lead ahead of it,
> and keying the list to the sung line moved it twice per line --
> once as the column went, again as the voice arrived.
> AMLL and Spicy set focus_idx themselves and change line on their
> own beat, a moment after the voice; following the sung line there
> aimed at a line the column had not gone to yet, and the whole list
> dipped and came back.

**line 14932** — before `rest = self.render.rest_top(i)`

> Where the column is GOING, not where it is: the list
> moves once, to the next line, and then holds still.

**line 14942** — before `want = self.anchor()`

> The pinned renderers put the line in a place of their own --
> Karaoke alternates two bands -- and following that bounced the
> list on every line. One fixed height: the focus band.

**line 14954** — before `back = at < getattr(self, "_rev_at", at) - 0.002`

> Forward only while the song goes forward. The list skips lines the
> column shows (an interlude, a line with nothing said about it), so
> a row standing in for one sits a little off from where its own line
> will be -- and correcting that as the next listed line arrived was
> a dip and a climb back. Holding still instead reads as nothing. A
> seek backwards moves the column back, and is followed.


### `LyricsView.review_correct`

**line 15191** — before `head, core, _tail = SL.peel(word)`

> What is already kept, read back onto this word's own spelling and
> punctuation, so an answer that only adds a way is one more "/ ...".

**line 15213** — before `self._rev_hand_until = mono() + 4.0`

> The dialogue outlasts the hold a hand on the list buys, and the
> sidebar went back to the sung line the moment it closed -- the
> whole list flying up from the row just corrected. Hold it again,
> and after that follow the song only forward, as between lines.


### `LyricsView.review_flag`

**line 15334** — before `if self.clock.status == "Playing":`

> Hold the song while the flag is written, so the line being flagged
> is not three lines back by the time it is.


### `LyricsView.info_rows`

**line 16098** — before `who = str(getattr(self.clock.io, "name", "") or "")`

> Always, not only when following any player: with the setting off
> the row was missing on every machine that had it off, and which way
> in is driving the clock is what a timing report needs first.

**line 16104** — before `if tid and not re.fullmatch(r"[0-9a-f]{22}", tid):`

> A song_key is the card's words hashed, not an id anyone else knows.


### `LyricsView._paint_editor`

**line 16429** — before `said = self.judge_label() if self.edit_mode in PEOPLE_KEYS else ""`

> The two lists get a second button, because the one thing typing
> into this line cannot do is carry a Spicy Lyrics id -- see
> judge_into_edit. It is drawn first and Paste keeps its corner, so
> the box a person already knows does not move under them.


### `LyricsView.menu_set`

**line 16622** — before `if key == "auto_update" and value:`

> Updating by itself needs to know there is an update, so the one
> brings the other with it -- and turning the check off takes the
> updater with it.


### `LyricsView.menu_value`

**line 16964** — before `return self.update_state or "check"`

> Short: the value column is sized for "album tint".

**line 17001** — before `if self.bg_mode == "clear" and not self._clear_live:`

> The same answer set_on_top gives: say what the desktop will
> actually do rather than echo the choice back.


### `LyricsView._paint_menu`

**line 17019** — before `size = max(11.0, W * 0.0098)`

> Everything below is measured off the fonts, and the fonts are made
> smaller until the box fits the window. It was laid out in fixed
> pixels -- the title at +18, the tabs at +70 -- against a font size
> taken from the width alone, so a face with tall or wide letters ran
> its words into each other and a short window cut the box off.

**line 17059** — before `inner = box.width() - 52`

> Whatever is still too wide after the smallest type gives the value
> column its room and cuts the labels short instead.


### `LyricsView._load_face`

**line 17220** — before `ask = url`

> Discord serves an avatar as WebP, or GIF where it is animated; its
> PNG is the same picture standing still, which every Qt can read
> and is all a credit line wants.


### `LyricsView.mousePressEvent`

**line 17961** — before `self.menu_step(hit[1] or 1)`

> The share rows are buttons: nothing to step, and
> nothing lost to a stray click, unlike the cache rows.


### `LyricsView.right_click`

**line 18032** — before `who = self.this_sync_by()`

> Whose sync this is, where the document says -- the same opinion K
> and the two Sources rows write, offered where the person is already
> looking at the words they have the opinion about.


### `LyricsView._remake_window`

**line 18598** — before `self.setWindowFlag(Qt.WindowType.FramelessWindowHint,`

> Set with the window already gone: setWindowFlag hides a window
> that is up, and `vis` has to be read before that.


### `LyricsView.resizeEvent`

**line 18639** — before `self.user_scroll_until = 0.0`

> Every line moves under a new size; follow the song again, and land
> on it rather than gliding there from where the old layout had it.


### `main`

**line 19442** — before `if saved.get("fps_cap") == 60.0:`

> 60 was the old default for the frame cap, and nothing but the default
> ever wrote it: there is no setting for it. Saved, it held a 144Hz panel
> to 48 frames a second, so it is read as "no cap".


---

## Lift — 2026-09-17

### module level

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


### `ckpt_facts`

**line 784** — on `        except Exception:`

> not a zipfile save, or old torch

**line 792** — on `        return got`

> not remembered: try again later

**line 794** — before `for gone in [k for k in _CKPT_FACTS`

> Only this file's older readings go; another machine's rows in a synced
> copy are none of our business.


### `_sync_ckpt`

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


### module level

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


### `windows_output`

**line 1664** — on `        dev = MediaDevice.get_default_audio_render_id(0)`

> AudioDeviceRole.DEFAULT


### module level

**line 1711** — before `MERGE_WAS_ON = 40.0`

> What a fraction of the word's span was worth, as a flat number of
> milliseconds. Measured over the 1267 multi-syllable words in the folder this
> was written in: 14% of the span merged 783 words and 40ms merges 408, which
> is the closest a flat figure comes to the old setting on the words where the
> old setting was doing something defensible -- the short and middling ones.
> It is not a conversion, because there is none: the two rules disagree most
> exactly where the old one was wrong.


### `save_settings`

**line 1788** — before `values = dict(values, offsets={k: float(v) for k, v in offsets.items()`

> Zero included. It is a correction like any other -- "this track
> is right as it stands, do not measure it" -- and dropping it
> here would restore the measured offset on the next launch.


### module level

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

2026-10-16: not every session rewrites it each second. Firefox
(WindowsSMTCProvider::SetPositionState) writes start 0, end = duration,
position and rate only when its position state changes: play, pause, seek,
active tab. With no position state at all it writes zeros. So past 10s a
stamp is a clock only when it lands inside the track's length. When the
session gives no length, the catalogue's length is used (dress / _worn, now
worn by the Windows and Mac transports too). A report on 1.1.8: Firefox
followed, lines seek, but no time line and "sometimes doesn't follow". That
is what a zero length does. Whether Firefox really sent zero there is
unmeasured; doctor.py's Session line now prints "at m:ss of m:ss" / "no
length given".

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


### `_packaging`

**line 2134** — before `if len(words) <= 3 and words[-1] in ("release", "premiere", "exclusive"):`

> "[NCS Release]", "[Monstercat Release]": a label's name is not on any
> list here and never will be, but a short bracket that ENDS in one of
> these words is the upload being announced, not the song being named.


### `song_from_video`

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


### `SessionTransport`

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


### `SessionTransport.__init__`

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


### `SessionTransport`

**line 2314** — before `def _sessions(self) -> list:`

> -- what the service is, for a subclass to answer --------------------

**line 2341** — before `@property`

> -- the part that is the same everywhere ------------------------------


### `SessionTransport._read_any`

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


### `SessionTransport._tick`

**line 2495** — before `gaps = (was or {}).get("gaps") or []`

> HOW OFTEN THIS PLAYER ANSWERS SOMETHING NEW, which is its
> resolution, kept as the middle of the last few gaps. The middle
> rather than the smallest: one gap can be short because a reading
> landed either side of an update, and one can be long because the
> sampler was busy, and neither is what the player does. It is
> read by _step_floor, where a step smaller than this is not
> allowed to count as the player's clock having leapt.


### `SessionTransport.allow`

**line 2573** — before `self._looked = 0.0`

> And look NOW rather than at the next turn of LOOK_EVERY. The player
> holding this track is not the one being followed -- that is what
> holding it back means -- so it is only reached through `_look`, and
> waiting out that throttle is half a second of a song that has just
> been cleared to go on screen sitting behind the one before it.


### `MprisTransport._read_one`

**line 2742** — before `"who": who,`

> Whose reading this is. Read by _worth, by the frozen stand-in in
> _read_any, and by nothing in the clock, which has never cared
> where a reading came from.

**line 2746** — before `"grain": grain,`

> How coarse this player's clock is. See Clock._step_floor: it is
> what stops an update interval being mistaken for a leap.


### `MprisTransport._song_of`

**line 2779** — before `"url": str(meta.get("xesam:url", "")),`

> Not shown anywhere. It is here because it is the best thing on
> the bus for telling a song from a video, and because a player
> that gives one gives it in the same breath as the rest of this.
> See looks_like_a_song.


### `MprisTransport`

**line 2789** — before `CAN = {"Next": "CanGoNext", "Previous": "CanGoPrevious",`

> Which property says whether a player will take an instruction. MPRIS
> has one for each and they are not decoration: a player that answers
> false does nothing when told, silently.


### `MprisTransport._able`

**line 2823** — before `return self.who`

> It did not say. Telling it anyway is what this always did.


### `MprisTransport.seek`

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


### module level

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
> Asked twice. BEFORE the lyric walk, because the visualiser is drawn from this
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


### `CdpTransport`

**line 3006** — before `name = "Spotify"`

> What the window calls it. Spicetify is the door -- an extension loaded
> into the client -- and the player on the other side of it is Spotify,
> which is the answer to "what is this playing on".


### `CdpTransport.__init__`

**line 3016** — before `self.source = "engine"`

> Which clock the last reading came from, and how long the engine has
> been saying the same thing. The sampler takes nearly every reading,
> but not quite all of them -- resync() takes one on the thread it is
> called from -- and a stall is counted across readings, so the count
> is kept straight rather than left to whichever arrives first.

**line 3025** — before `self._eng_show: float | None = None`

> The smoothed engine clock: where it is, when that was, and whose
> song it is. See _smooth.


### `CdpTransport._pick`

**line 3124** — before `if engine != self._eng_pos or not playing:`

> The stall is looked for in the RAW reading. The smoothed one
> goes on advancing by construction, so asking it whether the
> engine has stopped would never get an answer.


### `CdpTransport.read`

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


### module level

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


### `SmtcTransport.__init__`

**line 3291** — before `self._seen: dict = {}`

> The session list, and when it was taken. See SMTC_LIST_FOR.

**line 3294** — before `self._art: dict = {}`

> Covers already pulled off the transport, by track id. A thumbnail is
> a stream to open, read and close -- worth doing once a song and not
> four times a second, which is what asking on every reading would be.


### `SmtcTransport.drop`

**line 3324** — before `self._mgr = None`

> The manager too, not only what was cached under it. A session
> list survives a player closing and goes on handing out a session
> that answers nothing; re-requesting it is one call.


### `SmtcTransport`

**line 3336** — before `@staticmethod`

> -- the service ------------------------------------------------------


### `SmtcTransport._key`

**line 3347** — before `got = got.split("!")[-1]`

> The Store form is publisher.package_hash!app, and it is the app on
> the far side of the bang that names the program.


### `SmtcTransport`

**line 3417** — before `def _read_one(self, want_volume: bool, who=None) -> dict:`

> -- one reading ------------------------------------------------------


### `SmtcTransport._read_one`

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


### `SmtcTransport`

**line 3520** — before `def seek(self, seconds: float) -> None:`

> -- telling it things -------------------------------------------------


### `SmtcTransport.seek`

**line 3531** — before `self._clocks.pop(self.who, None)`

> The anchor describes where the song was. Carried forward past a
> seek it walks on from the old place and the clock follows it
> back, which is a seek that lands and then unlands. See
> MprisTransport.seek, which drops it for the same reason.


### `_since`

**line 3589** — before `secs = float(stamp) / 1e7 - 11644473600.0`

> A raw FILETIME: hundred-nanosecond ticks since 1601-01-01.


### module level

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


### `MacTransport.__init__`

**line 3724** — before `self._mr_quiet = 0.0`

> When MediaRemote first said nothing was playing, and has said it
> ever since. See MR_DOUBT.

**line 3729** — before `self._slots: dict = {}`

> One slot per player that has to be asked over Apple Events: the last
> answer, when it landed, and whether somebody is out getting the next
> one. Read from the sampler's thread, written from the background
> ones; a dict assignment is what crosses between them, so there is
> nothing here to lock.


### `MacTransport.usable`

**line 3745** — before `return bool(MacTransport._open_apps())`

> No framework, so it comes down to whether anything is even there to
> ask. A Mac with neither music player open and no browser running is
> not a Mac this can read -- and saying so is what lets make_transport
> fall back to the debug port rather than installing a door that will
> never open.


### `MacTransport`

**line 3765** — before `@staticmethod`

> -- who is even here --------------------------------------------------

**line 3805** — before `def _doubted(self) -> bool:`

> -- MediaRemote -------------------------------------------------------

**line 3839** — before `def _slot(self, who: str) -> dict | None:`

> -- Apple Events, at their own pace -----------------------------------

**line 3872** — before `def _read_one(self, want_volume: bool, who=None) -> dict:`

> -- one reading -------------------------------------------------------


### `MacTransport._read_one`

**line 3881** — before `if got.get("playing"):`

> MediaRemote says the machine is silent and somebody here is
> playing. That is the shut framework, not a quiet Mac. It is
> not asked again this session; a new one is built whenever
> the settings change, so nothing is lost permanently.


### `MacTransport._shape`

**line 3903** — before `"volume": None,`

> No door on a Mac carries a volume that is the PLAYER's: Spotify
> and Music have one over Apple Events, but the browsers do not
> and MediaRemote has none at all, so the slider would appear and
> disappear with the player. It stays hidden.


### `MacTransport`

**line 3944** — before `def _tell(self, what: str) -> None:`

> -- telling it things -------------------------------------------------
>
> Only the music players take instructions. A browser tab has no transport
> to speak of -- the page draws its own -- and MediaRemote's command call
> is behind the same entitlement as the rest of it, so there is no route
> that would work where the reading route does not.


### `MacTransport.seek`

**line 3961** — before `self._clocks.pop(self.who, None)`

> The anchor is from before the seek; carried forward it walks on
> from where the song was and the clock follows it back. See
> MprisTransport.seek.


### `BackupTransport`

**line 3995** — before `LOOK = 0.5`

> How often the OTHER side is asked whether anything is playing on it,
> while the side being read has nothing. Twice a second: far under the
> sampler's rate, far over the rate at which somebody starts a song. A
> side that FAILED is knocked on at RETRY instead -- a dead debug port
> answers no faster for being asked ten times as often.


### `BackupTransport.__init__`

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


### `BackupTransport.allow`

**line 4058** — before `self._next_look = 0.0`

> Look at the other side on the very next reading. A track being
> vouched for is by definition on the side NOT being followed, and
> the answer arriving is the one moment its reading can change what
> is on screen -- so this is exactly when not to be waiting out LOOK.


### `BackupTransport._follow`

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


### module level

**line 4183** — before `def session_transport():`

> The platform's own way of knowing what is playing, whichever one this is:
> the session bus, the Windows media transport, or whatever door is open on a
> Mac. Named once so everything that has to ask "is there one of those here"
> -- make_transport, the settings menu, the doctor -- asks it the same way.


### `Clock.__init__`

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


### `Clock._apply`

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


### `Clock.seek`

**line 4616** — before `self._at = began + (time.monotonic() - began) / 2`

> Where the song went is known exactly; WHEN it went there is not.
> The player takes the command somewhere inside the round trip, so
> the middle of it is the honest anchor -- the same correction the
> readings get, and for the same reason: this timestamp is what
> every position between now and the next reading is measured from.


### `Pump.__init__`

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


### `Pump.run`

**line 4742** — before `self.clock.status = "Error"`

> `spotify_dom.connect` calls sys.exit when the debug port has
> gone. SystemExit is not an Exception, and raised on the GUI
> thread it used to take the window down with it; here it ends
> nothing but the reading it arrived in.

**line 4755** — before `self._wake.wait(self.every if self.clock.status != "Error"`

> A player that is not answering is not worth asking sixty times a
> second: back off to the old rate until it does. Nothing is
> moving while it is down, so there is nothing to be late for.


### module level

**line 4765** — before `HAVE_IT = 0.25`

> What a song already on this machine is worth beside one only Genius knows
> about. It stands in for the popularity Genius supplies and a local index
> cannot -- pitched at the top of that range on purpose, so an equally good
> match the user already has, and has probably timed by hand, takes the tie.


### `Beat`

**line 4868** — before `JS = "Promise.race([Spicetify.getAudioData(%s).then(d => ({" \`

> Raced against a deadline, so a page that is slow to fetch the analysis
> costs that and not the socket's own fifteen seconds. null means "not in
> time", which every caller reads as no answer -- see Fetcher._audio, which
> asks twice with two different deadlines.


### module level

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


### `MotionArt._work`

**line 6145** — before `with self._lock:`

> Off the in-flight list either way, so the same album can be
> asked for again when it comes round.


### module level

**line 6289** — before `_people = LS.people`

> Who a credit slot names. It lives in lyric_sources now, because the chain
> has to read the same field to know whose sync it is holding (see Roster) and
> two readings of one convention is how the name printed here and the name
> refused there drift apart.


### `Fetcher.__init__`

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


### `Fetcher.request`

**line 6373** — before `with self._lock:`

> Woken at the end, because this is the one request with somebody
> watching a clock on it. The loop sleeps POLL_IDLE between rounds, so
> a track asked for a moment after a sleep began waited out the rest
> of it before anything was fetched at all -- measured at 415ms on a
> launch, between the window knowing the song and the first ask going
> out. Everything else queued here is background work that nobody is
> timing, and the idle pace is right for it.


### `Fetcher._gsearch_loop`

**line 6548** — before `self.gsearch_ready.emit(q, got)`

> Emitted whatever has been typed since: the window knows
> which query is on screen and drops an answer to any other.


### `Fetcher.request_ahead`

**line 6570** — before `self._ahead_gen += 1`

> Bumped whoever is warming out of putting a track back on a list
> that is no longer the list it took it from; see _warm.


### `Fetcher._warm`

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


### `Fetcher.run`

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
> visualiser; come back to it later in the same run and get none, for
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

> Before the walk, not after it. The visualiser reads this and
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


### `Fetcher._interim`

**line 6104** — before `rank = LS.RANK.get(LS.quality(body), 0)`

> Bug: a track finds the right source, is replaced by a worse one for
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


### `Fetcher._watch_spicy`

**line 6840** — before `watch[tid] = (grace, now + SPICY_SLOW)`

> A read that did not get through says nothing about what
> Spicy Lyrics has. Dropping the watch on it ended the
> looking for good on one dropped socket, and left the song
> on somebody else's document for the rest of its play; hang
> on and ask again at the slow pace.


### `Fetcher._drop`

**line 6941** — before `return`

> The connection this call failed on has already been thrown
> away, and what is up now is somebody else's fresh one.
> Dropping that is how one thread's timeout came to cost
> every other thread its working socket, in a round nobody
> can win: each of them drops the last one made.


### `Fetcher._genius_match`

**line 7110** — before `title = re.sub(r"[\(\[\{].*?[\)\]\}]", "", raw).strip() or raw`

> "(Romanized)", "[Live]" and the rest are Genius's own bookkeeping and
> match nothing in the catalogue -- but a title that is ALL brackets is
> the song's actual name, so the trim is only kept if it leaves one.

**line 7116** — on `            artist = ""`

> "Genius Romanizations" is not who recorded it


### `Fetcher._spicy_hold`

**line 7211** — before `return None`

> Asked before the round trip, not after it, or the deadline
> is only honoured once it has already been overrun. This is
> the case the docstring above describes -- a walk that really
> went to the network -- and it was still paying for one more
> read of the page, on the connection that walk had just spent
> several seconds not using.


### `Fetcher._load`

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


### `Fetcher._shaped`

**line 7372** — before `if LS.lrc_shaped(body):`

> Before the ad-lib repair rather than after it: split_asides cuts a
> bracketed run out of the lead, and a hole closed across the place
> that run used to be is a word held over an ad-lib somebody else
> sang. Closing them first means every hole is closed between two
> syllables that really are neighbours.

**line 7379** — before `body = LS.quiet_marks(body)`

> After the unlump, so a mark that was glued into a lumped syllable
> has been cut out of it and can be seen for what it is.


### module level

**line 7530** — before `DASHES = "-\u2010\u2011\u2012\u2013\u2014"`

> Every dash a lyric uses to write a word's own split into it: the plain
> hyphen, the typographic and non-breaking ones, and the two long dashes that
> get used the same way ("Oh—oh—oh").

**line 7535** — before `JOIN_AT_MOST = 2`

> How many fragments one merge may fold together. Two: a seam is a statement
> about the two pieces either side of it, and that is the whole of what this
> rule can honestly test. See _join_flat for what raising it does and why the
> damage falls on long words.


### `_flat_group`

**line 7561** — on `        if abs(run[k][1] - at) > tol:`

> the boundary says something

**line 7563** — on `        if abs(run[k + 1][0] - run[k][1]) > tol:`

> a rest inside the word


### `_join_flat`

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


### `prepare`

**line 7885** — before `"opposite": bool(ln.get("opposite")),`

> The side the dots hang off is the side of the line they lead
> INTO, not the window's default. In a duet the two voices sit
> against opposite edges, and dots pinned to the left through
> an eight-bar gap in front of a right-hand line count down on
> the wrong side of the screen -- they are that singer's
> count-in, so they wait where that singer will arrive.


### `LiveLink._accept`

**line 7963** — before `sock.disconnected.connect(self._maybe_let_go)`

> An editor that was walking Spotify along with it and then went
> away -- closed, crashed, unplugged -- must not leave the player
> muted and running. Nobody is timing against it any more.


### `LiveLink._maybe_announce`

**line 8023** — before `self._was = (pos, now, state)`

> Measured from what was last SAID, not from the last tick. Anchored
> on the tick, a drift that comes on slowly is never more than a
> fiftieth of a second at a time, so it was never announced at all --
> and the editor was extrapolating from a reading that had quietly
> stopped describing the song.


### `LiveLink._handle`

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


### `Aligner._align`

**line 8320** — before `got = (LS.fallback(tid, meta, "none", set(names), order=names,`

> The roster counts here too: a song whose only word timing is
> somebody's the user has refused is a song this machine is not
> going to be shown word timing for, which is precisely when
> aligning it here is worth the GPU.


### module level

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


### `Field.__init__`

**line 8428** — before `self.clipped = False`

> Set whenever something had to be dropped to fit, and cleared by
> whoever says so. A paste that silently keeps its first N characters
> looks exactly like a paste that went wrong; see LyricsView.field_key.

**line 8434** — before `self.sel: int | None = None`

> The other end of the selection, or None when there is none. The
> caret is always one of the two ends, so a shifted arrow only ever
> has to move the caret.


### `Field`

**line 8442** — before `def set_text(self, text: str) -> None:`

> -- the text --------------------------------------------------------


### `Field.replace_at`

**line 8459** — before `room = self.limit - len(self.text) + (hi - lo)`

> What is being taken out makes room for what is going in, so a
> full box can still be typed into over a selection.


### `Field`

**line 8482** — before `def word(self, at: int, step: int) -> int:`

> -- moving about ----------------------------------------------------


### `Field.key`

**line 8537** — before `at = lo if back else hi`

> An unshifted arrow against a selection collapses it to the
> edge it points at rather than moving one place from there.

**line 8559** — before `if ev.text() and ev.text().isprintable() and (alt or not ctrl):`

> AltGr arrives as Ctrl+Alt and is how half of Europe types a
> character, so only Ctrl on its own means "this is not text".


### `Field`

**line 8566** — before `def laid_out(self, at: float, fm, rect) -> None:`

> -- where it was drawn, and what a click in it means ------------------


### `Field.pick_word`

**line 8626** — before `if self.text[at].isspace() and at > 0 and not self.text[at - 1].isspace():`

> A click in the gap AFTER a word belongs to that word, the way it
> does in every other text box -- otherwise the end of a line picks
> nothing at all.


### `LyricsView`

**line 8646** — before `query = property(lambda s: s.q_field.text,`

> The three text boxes this window draws by hand. Everything that only
> wants to know what was typed goes on reading `query`, `bq` and
> `edit_text` as the plain strings they have always been; the caret and
> the selection live on the Field beside them, which is also what a
> click and a drag are answered from. See Field.


### `LyricsView.__init__`

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

> True/False when the change under way is the visualiser arriving or
> leaving, naming which side is the lit one; None for every other kind
> of change. See scene_mix, which drives those two off the visualiser's
> own fade instead of off the clock.

**line 8969** — before `self._viz_mix = 0.0`

> How far in the visualiser is, 0 to 1, and the last picture it drew.
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

> The strength the visualiser had when V switched it off, so switching
> it back on restores it. A NAME OF ITS OWN: this used to be spelled
> _viz_last, which is the last picture the visualiser drew, and the two
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


### `LyricsView`

**line 9154** — before `def retune_frames(self, *_) -> None:`

> -- the frame rate follows the screen the window is actually on -----


### `LyricsView._frame`

**line 9213** — before `period = 1.0 / max(1.0, self.eff_hz if self.showing() else FRAME_IDLE_HZ)`

> In a finally because the old repeating timer would have carried
> on through a raised frame and this one would not: one traceback
> out of tick would leave the window alive but permanently frozen.

**line 9220** — before `self._frame_due = time.monotonic() + period`

> A long stall: a slow fetch on this thread, a resize, the
> machine suspended. Start the cadence again from here rather
> than firing a burst of frames chasing a moment that has gone.


### `LyricsView`

**line 9254** — before `def lyric_px(self) -> float:`

> -- fonts sized off the window, like the web view -------------------


### `LyricsView._lyric_face`

**line 9397** — before `if len(self._font_memo) > 16:`

> A resize walks the size through every pixel on the way, so this
> would otherwise grow a face per pixel of window width. The
> working set is two -- the lyric size and the backing-vocal one.


### `LyricsView`

**line 9410** — before `def on_reading(self) -> None:`

> -- data ------------------------------------------------------------


### `LyricsView.vet_pending`

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


### `LyricsView.on_card`

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


### `LyricsView.closeEvent`

**line 15492** — before `LS.offload.shutdown()`

> concurrent.futures already joins its workers at a normal exit, so this is
> for the other kind. A window that goes down hard leaves its pool forked and
> parentless -- seen while measuring, where a harness that called os._exit
> left two workers running after everything that knew about them had gone.


### `Clock.resync_soon`

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


### `LyricsView.poll`

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


### `LyricsView.apply_romaji_fixes`

**line 9833** — before `self._ink_gen += 1`

> The pieces a drawn line is keyed by have just changed under
> it. See line_ink.


### `LyricsView.rebuild_lines`

**line 9945** — before `self.layout_cache.clear()`

> Same words, re-folded: every line that survives the new gap keeps
> its picture. See line_pixmap.


### `LyricsView.show_dropped_lyric`

**line 10020** — before `LS.forget(tid)`

> The stored lookup would otherwise answer for this track before
> anybody asks the local slot, and the drop would come back only
> until the cache aged out.


### `LyricsView.restore_dropped`

**line 10062** — before `return False`

> The drop path says so out loud, because somebody is standing at
> the window watching for it. Nothing asked for this one, so a
> track that cannot be read falls back to the song's own lyrics
> without a word about a file the user has not thought about
> since yesterday.


### `LyricsView.show_live_lyric`

**line 10097** — before `self.own_body = self.body`

> The song's own document, kept aside before the editor's takes
> the screen. Without it "fetch what the player is showing"
> answers with whatever the editor last pushed -- which is the
> editor's own file, handed back to it as if it were a source.


### `LyricsView.follow_editor`

**the unmute** — before `self._unmute_for_editor()`

> Once the player has stopped, not once THEY have. The pause is a command
> and `_transport` only sends one every FOLLOW_STEADY, so unmuting on their
> pause alone put Spotify back to its own volume while it was still playing
> -- up to six tenths of a second of the song out loud, every time somebody
> stopped to fix a word. Staying muted is the safer way round to be wrong:
> a muted player that should be audible is handed back by the next tick, or
> by `unfollow_editor` when the editor goes.


### `LyricsView._follow_to`

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


### `LyricsView.unfollow_editor`

**line 10205** — before `self.clock.command("PlayPause")`

> Not player_do: this is the window tidying up after the editor,
> not a key somebody pressed, and there is nobody to tell.


### `LyricsView.show_dropped_art`

**line 10250** — before `self.on_art("", (img, blurred, palette_of(img)), dropped=True)`

> Said outright rather than left to the order of the two lines below
> it: a second picture dropped on a song already wearing one is still
> a picture somebody dropped, and reading it off dropped_art would
> have this refuse it.


### `LyricsView.reset_track`

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


### `LyricsView.on_art`

**line 10369** — before `self._art_fails[url] = self._art_fails.get(url, 0) + 1`

> The download gave up. Nothing would ever ask again: art_url is
> set to the wanted url before the thread starts, so the poll's
> own "have we already asked for this one" is what kept the song
> on the last song's cover for the rest of its play. Handing the
> url back is what lets the next poll ask afresh -- a few times,
> and then no more, because a url that is genuinely gone should
> not be asked for four times a second until the track changes.


### `LyricsView._swap_offset`

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


### `LyricsView.on_device`

**line 10552** — before `if was:`

> The output has gone -- no pactl, another platform, the sink
> closing under us. Put the live number away under the pairing it
> belonged to, since there is nothing to take out in its place and
> losing it would cost whatever was tuned by ear on that output.

**line 10560** — before `if was:`

> Nothing is said about the output the window came up on: that is not
> a change, it is where it started.


### `LyricsView.unpause_delay`

**line 10644** — before `self.clock.unpause_delay = max(-1.0, min(1.0, float(v)))`

> Held inside the range the menu offers, and that range reaches below
> zero. It used to be max(0.0, ...), which is what the setting meant
> when the only correction was a hold; with the measurement able to
> push the words forward as well, that clamp was silently throwing
> away everything the menu let anybody dial in on the negative side
> -- the row read -0.20s and the clock got 0.


### `LyricsView.on_lyrics`

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


### `LyricsView.say_alignment_outranked`

**line 10835** — before `return`

> What is held for this track is the file on screen. Nothing has
> outranked anything, and saying so under somebody's own document
> would send them to the Sources menu to fix a running order that
> is not deciding this.


### `LyricsView.source_name`

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


### `LyricsView.made_by`

**line 11015** — before `words = str(doc.get("_words_by") or "").strip()`

> Who vouched for the WORDS, which is a different credit and is why
> it is a different field. A Genius document is timed here, off the
> audio -- nobody named in `_words_by` made this sync, and LS.credited
> does not read it, so judge_sync cannot enrol them in a roster about
> timing. See genius_roman.credit_of. Printed last because the line
> reads best from this copy outwards: who timed it, then what the
> source says about the words underneath.


### `LyricsView.credit_rows`

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


### `LyricsView.set_people`

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


### `LyricsView.fetch_meta`

**line 11345** — before `"explicit": m.get("explicit")}`

> Not for finding the song -- nothing searches on it. It rides
> along because this dict is what reaches LS.clean_edit, and it
> is the best answer there is to "is the cut being played the
> clean one". None where the player did not say.


### `LyricsView`

**line 11433** — before `def troll_aim(self, idx: int) -> int:`

> -- trolls ----------------------------------------------------------


### `LyricsView.troll_aim`

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


### `LyricsView.searching_now`

**line 11527** — before `self.search_goal = self.scroll_target`

> No leg yet and no previous frame: the first frame of the bout picks
> one and takes the nominal step, where `now` would mean a first frame
> of no elapsed time and so no movement.


### `LyricsView.troll_search`

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


### `LyricsView`

**line 11603** — before `def instrumental(self) -> bool:`

> -- geometry --------------------------------------------------------


### `LyricsView.wrap_pieces`

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


### `wrap_shape`

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


### `stamp_rows`

**line 1187** — before `def stamp_rows(shape, pieces):`

> The times, written onto a shape. The arithmetic for a cut-up piece is
> split_to_fit's own, and the untimed case falls out the same way it does
> there: the first chunk carries the whole span and the rest sit empty at the
> end of it. That is not a decision made here, it is the old behaviour kept.


### `LyricsView.layout_line`

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


### `LyricsView.ruby_rows`

**line 11850** — before `if not self.furigana or not rows or self.roman == "instead":`

> Which reading goes over which script is `SL.ruby`'s decision, not
> this one's: kana over kanji, pinyin over hanzi, Revised
> Romanisation over a Hangul block. What this has to pass on is
> whether the DOCUMENT is Japanese, because Han characters are shared
> and nothing in a line of them says which language they are being
> read in -- pykakasi read 低音吉他, Chinese for "bass guitar", as
> ていおん・きち and set that over the credits.


### `LyricsView`

**line 11885** — before `def drift_of(self, key, x0: float, y0: float, w: float, h: float):`

> -- animation -------------------------------------------------------


### `LyricsView.tick`

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
> speed, and easing towards a target that is itself moving at that
> speed only adds lag to it.

**line 12004** — before `want = self.troll_aim(self.focus_idx)`

> Asked once a frame and only here: the answer is where the
> column stops, and nothing else in the view is entitled to it.


### `LyricsView`

**line 12077** — before `def drop_pixmaps(self) -> None:`

> -- text pixmaps, so distant lines can be blurred cheaply -----------


### `LyricsView.tick` — the scroll spring

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


### `LyricsView.line_pixmap`

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

**line 12105** — before `pen = self.base_colour(self.lines[idx]) if pen is None else pen`

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


### `LyricsView.glow_pixmap`

**line 12217** — before `key = (txt, font.toString(), radius)`

> The whole font, not just its size: the family and the weight change
> the shape being blurred, and a key that forgets them hands back the
> last font's glow. See drop_pixmaps, which is allowed to leave these
> alone precisely because the key is complete.


### `LyricsView.scene_layer`

**line 12285** — before `key = (W, H, tuple(c.rgb() for c in self.palette), self.art_gen,`

> The mesh fields go on the END, past viz_live(), because VIZ_IN_KEY
> is an index into this tuple and scene_mix counts on it.

**line 12296** — before `if (self.bg_fade > 0 and self._scene_pm is not None`

> A KEY change is a different wall -- another cover, another section,
> another mode, the visualiser arriving. The same key coming round
> again is only the drift being redrawn, and that is already smooth.
> So the one is worth fading and the other must not be, or every
> fifteenth of a second would start one.

**line 12305** — before `old_key = self._scene_key`

> Whether this change is ONLY the visualiser coming or going. In
> mesh mode the two walls either side of that are not independent
> pictures: the still mesh is left out of the lit one precisely
> because the visualiser is about to draw it driven, and painting
> both doubles every blob. Crossfading them on a clock of its own
> while the visualiser fades on another put the two out of step
> and the overlap is a flash of light between two dark walls.
>
> So a change of this one field is handed to the visualiser's own
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


### `LyricsView.viz_face`

**line 12410** — before `d = self.VIZ_DIVS.get(self.viz_mode, self.VIZ_DIV)`

> The layer is built at a REDUCED size -- VIZ_DIVS -- and blown back up
> by the painter, so it is never the size of the window and must not be
> compared against it. What matters is that it still matches the
> divisor this window width would use; anything else is a picture from
> before a resize, and the new one arrives next frame anyway.


### `LyricsView.scene_mix`

**line 12435** — before `k = self._viz_mix if self._scene_viz else 1.0 - self._viz_mix`

> The visualiser arriving or leaving. How much of the new wall to
> show is how far the visualiser is in -- or out, when the new wall
> is the still one -- so the light the wall gives up is exactly the
> light the visualiser takes over, and the two never overlap.

**line 12449** — before `k = max(0.0, k)`

> Smoothstep, so it leaves and arrives at rest. A linear crossfade
> between two full-window pictures reads as a wipe with a hard start.


### `LyricsView`

**line 12458** — before `VIZ_DIV = 3`

> -- visualiser ------------------------------------------------------

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


### `LyricsView.viz_layer`

**line 12603** — before `bands = self.viz_bands(dt)`

> Eased every frame whoever is painting, so switching mode mid-song
> arrives at chroma already settled rather than climbing from nothing.


### `LyricsView._viz_bloom`

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


### `LyricsView`

**line 12679** — on `    VIZ_RING = 1.35`

> seconds a ring takes to cross the window and go out


### `LyricsView._viz_pulse`

**line 12699** — before `a = self._viz_a(1.9 * (1.0 - age) ** 1.7 * strength`

> A ring is a thin band where a blob is half the window, so it
> needs the weight a blob does not: the same alpha spread over
> a twentieth of the area reads as nothing at all.

**line 12720** — before `core = tint[self._section % n]`

> A core under the rings, so a bar's rest still has something standing
> in the middle rather than an empty window between beats.


### `LyricsView._viz_bars`

**line 12752** — before `v = (bands[cls] if cls < len(bands) else 0.0) ** 2`

> Squared, because the twelve arrive normalised to their own
> peak and sit high: read straight, a triad differs from the nine
> classes it is not by a few pixels of column.


### `LyricsView`

**line 12908** — before `def paintEvent(self, _ev) -> None:`

> -- painting --------------------------------------------------------


### `LyricsView._paint_window`

**line 12977** — before `p.setOpacity(self._viz_mix)`

> Rides the beat zoom with the scene under it: they are one wall.


### `LyricsView._paint_panel`

**line 13040** — before `px0 = self.panel_x()`

> Every x below is measured from the panel's own left edge, which is
> the window's unless the art has been sent to the other side.


### `LyricsView._paint_volume`

**line 13144** — before `vol = (self.vol_drag if self.vol_drag is not None else`

> The drag first, then what the wheel has asked for and the player
> has not been told yet, then the player's own. Anything still owed
> is drawn as though it had landed -- it is what the hand asked for,
> a frame or two of round trip is not something anybody should watch
> the bar wait out, and `flush_volume` makes it true directly.


### `LyricsView`

**line 13479** — before `# -------------------------------------------------------- browse painting`

> -- search ----------------------------------------------------------

**line 13481** — before `ROW_PAD = 8.0`

> What a list row keeps clear above and below its two lines of text.


### `LyricsView.browse_metrics`

**line 13490** — before `r_t = QFontMetricsF(self.ui_font(max(11, W * 0.0105))).height()`

> A row is as tall as what goes in it. It was a flat 56 while the two
> fonts inside it were sized off the window, so on a big enough screen
> the pair no longer fit: the name sat mid-row and the artist under it
> spilled out of the bottom, landing against the next row's name and
> reading as if it belonged to THAT song. These are the same two fonts
> _paint_browse_search and _paint_browse_queue ask for.


### `LyricsView._paint_hit_row`

**line 13991** — before `nh, sh = fmt_.height() * 1.2, fms.height() * 1.3`

> Centred as a pair rather than hung off the top of the row, so
> the name and the artist under it stay one block whatever the
> row is worth on this window. See browse_metrics for the height.


### `LyricsView`

**line 14094** — before `REV_INK = {"error": QColor(255, 104, 104),`

> What a finding is drawn in. Three colours for the three weights, and
> nothing else on the page is coloured, so a page with no red in it is a
> document with nothing wrong that this knows how to see.

**line 14101** — before `REV_SEAM = QColor(112, 222, 192, 205)`

> The seam between two pieces of one word. A colour of its own, and
> deliberately not one of the three above: a seam is not a finding, it is
> the document's own structure being shown, and drawn in the blue a note
> is drawn in it would read as one.


### `LyricsView.build_review`

**line 14166** — before `title=str(self.clock.meta.get("title") or ""),`

> What the service says the song is. The file itself mostly
> cannot say: an Apple-style head carries the songwriters and
> nothing else, so "(feat. Somebody)" is known here and
> nowhere in the document. See review._check_credits.

**line 14173** — before `self.review = self.review_at = self.review_body = None`

> A screen that cannot be built is not a reason to lose the
> window: this is a reader, and the thing it is reading came off
> somebody's disk.


### `LyricsView.review_plan`

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


### `LyricsView._paint_review`

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
> easing towards it is tick's, like every other ease in the window, so
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


### `LyricsView._paint_review_head`

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


### `LyricsView`

**line 14606** — before `REVIEW_NEAR = 2`

> How far from the line being sung a mark is still drawn IN THE WORDS.
> The margin bar goes on every line on screen, because its whole job is to
> say what is coming; the underlines are for the line you are reading, and
> a column of them all the way down is the thing this is trying not to be.


### `LyricsView.review_spans`

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


### `LyricsView._mark_level`

**line 14720** — before `found = True`

> The worst of them where several begin together, the way the
> bar in the margin takes the worst thing said about a line:
> "your" timed y·o·ur with a zero-length o puts three pieces
> on two instants, and the one a reader needs to see is the
> heaviest -- a letter with no vowel in it, not the note
> about the piece it happens to share a millisecond with.


### `LyricsView._paint_review_marks`

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


### `LyricsView`

**line 14856** — before `REVIEW_LOUD = 60`

> Past this many findings a document is not being reviewed so much as
> papered over, and the toast says how to read it instead. It is what a
> catalogue's copy looks like -- they write a zero-width space between
> every pair of words, which is one finding per word for the whole song.


### `LyricsView._paint_review_fold`

**line 14919** — before `for other in [item["row"]] + list(also):`

> The line being shown is the first of them and belongs in the list:
> a dropdown that says "3 times" and offers two places to go is a list
> with a hole in it where the line you are looking at should be.


### `LyricsView.review_press`

**line 15138** — before `self.clock.seek(max(0.0, other.start) + self.track_offset())`

> One of the repeats, picked out of an opened fold: the song
> is played from THAT one rather than from the first.


### `LyricsView.on_gsearch`

**line 15319** — on `            return`

> answered a query the user has already typed past


### `LyricsView.genius_rows`

**line 15334** — before `if not self.gq_query or not typed.startswith(self.gq_query):`

> Kept up while the query is still being extended, so refining a line
> does not blink the Genius rows out and back on every letter; a
> backspace or a different query drops them, since those are no longer
> answers to what the box says.


### `LyricsView.merge_hits`

**line 15363** — before `line = g.get("line") or ""`

> Where Genius matched a LINE, the row reads like every other one:
> the line above, the song under it. Where it matched the name,
> the name is already the line above -- so the row under it is the
> artist alone, rather than the same words a second time.


### `LyricsView.activate_hit`

**line 15382** — before `self.gq_matching = hit["genius"]`

> Genius named a song; Spotify has to be asked which recording
> that is, and only for the one actually picked -- matching all
> eight would be eight catalogue searches per keystroke's worth
> of results, for seven nobody asked about.


### `LyricsView`

**line 15494** — before `def info_rows(self) -> list[tuple[str, str]]:`

> -- song info + share ----------------------------------------------


### `LyricsView.info_rows`

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


### `LyricsView._paint_info`

**line 15621** — before `self.info_rects = []`

> Where each row is, so a click can take its value. Rebuilt every
> frame because the panel's contents are: a row appears the moment
> there is something to put in it.


### `LyricsView.share_card`

**line 15739** — before `wrote = pm.save(str(path))`

> QPixmap.save answers False rather than raising, so a card that
> never reached the disk was announced as copied.


### `LyricsView`

**line 15750** — before `def open_editor(self, mode: str = "romaji", idx: int | None = None) -> None:`

> -- romaji correction ------------------------------------------------


### `LyricsView.open_editor`

**line 15789** — before `self.said_clipped(self.edit_field)`

> Only ever fires on a value that was already too long to be one --
> and says so rather than quietly handing back a shortened copy of
> it, which is what saving the field would then write down.


### `LyricsView._paint_field`

**line 15873** — before `shift = max(0.0, before - (wide - 12))`

> Scrolled only as far as it takes to keep the caret off the right
> edge; a field whose text fits is not scrolled at all.


### `LyricsView`

**line 15968** — before `def menu_section(self) -> int:`

> -- settings menu ---------------------------------------------------


### `LyricsView.src_move`

**line 16038** — before `self.toast("the blends follow the sources' order — reorder those")`

> Silently doing nothing here reads as a broken key. The blends
> are ordered by where their donors sit in Sources, on purpose --
> say which list to go and move.

**line 16053** — before `self.toast(" → ".join(SRC_LABEL[n] for n in self.src_order`

> The SOURCES that were just reordered, not the providers they expand
> to. source_order() returns the expansion -- "bini", "triblend" -- and
> SRC_LABEL is keyed by source, so reading it through this raised
> KeyError on every reorder.


### `LyricsView.menu_set`

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


### `LyricsView.menu_value`

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


### `LyricsView._paint_menu`

**line 16295** — before `note = SECTION_NOTE.get(MENU_SECTIONS[tab][0], "")`

> A section whose rows cannot say what they are on their own gets a
> line under the tabs. It is drawn in the slack a short section leaves
> under its last row -- the box is sized to the TALLEST section -- so
> a section already at full height silently gets none rather than
> overflowing the panel.


### `LyricsView`

**line 16368** — before `def flip_view(self) -> None:`

> -- helpers ---------------------------------------------------------


### `LyricsView.save_lyrics`

**line 16472** — before `self.toast(f"saved {path.name}" if asked else f"saved {path}")`

> The whole path where it is not the one they asked for. "saved
> song.ttml" is all anybody needs when they said where it goes;
> when this program picked, it owes them the place.


### `LyricsView`

**line 16485** — before `def on_thumb(self, url: str, img) -> None:`

> -- input -----------------------------------------------------------


### `LyricsView.on_motion`

**line 16506** — before `fits = max(1, MOTION_BUDGET // max(1, cap * cap * 4))`

> How many of these the budget can hold at that size, and hence how
> many to skip. Thinning rather than shrinking -- see MOTION_BUDGET.


### `LyricsView._take_motion`

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


### `LyricsView.browse_key`

**line 16571** — before `used, changed = self.field_key(self.bq_field, ev)`

> The box gets the rest before the transport does, so Left and
> Right walk the caret through what was typed rather than seeking
> the song. Up and Down are taken above, where they still pick a
> result; the transport keys are still there on the other tabs.


### `LyricsView.browse_activate`

**line 16663** — before `self.gq_matching = payload["genius"]`

> Genius named a song, not a recording; ask Spotify which one it
> is, and only for the row actually picked. See on_gmatch.


### `LyricsView.refresh_browse_hits`

**line 16696** — before `self.wind_genius(self.bq)`

> Genius once the typing stops, same as the overlay; see ask_genius.


### `LyricsView.merge_browse_hits`

**line 16712** — before `for g in self.genius_rows(self.bq.strip(), known):`

> The catalogue's own order is Spotify's ranking and is left alone;
> what is sorted here is the tail this window adds to it.

**line 16720** — before `"art": art_url(g.get("art") or ""), "ms": 0,`

> Through art_url like every other cover, which is
> also what keeps anything but http out of the
> fetcher's hands.


### `LyricsView.wheelEvent`

**line 16851** — before `if (self.view == "lyrics" and self.lines`

> A renderer that pins its lines gets first refusal: view.scroll means
> nothing to it, so without this the wheel did nothing at all. The one
> that takes it (the amll column) moves its own offset instead. See
> Renderer.wheel.


### `LyricsView`

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


### `LyricsView.vol_wheel`

**line 16916** — before `at = self.vol_want if self.vol_want is not None else self.clock.volume`

> Counted from what has been ASKED for rather than from what the
> player has been told, or every notch turned inside `VOL_GAP` would
> be measured from the same stale level and a fast turn would move
> the volume by one notch however far it went.


### `LyricsView.mouseMoveEvent`

**line 16933** — before `self.field_drag.drag_to(pos)`

> Above every view's own move handling, and not hit-tested: a
> selection dragged past the end of the box should go on growing
> rather than stop at the edge the pointer left.


### `LyricsView.keyPressEvent`

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

**line 17425** — before `self.toast("visualiser: on, no analysis for this track")`

> Say so rather than leave them staring at an unchanged
> background wondering whether the key did anything.

**line 17486** — before `whose = (self.dropped_from or "the editor"`

> Who was drawing, before reset_track forgets. A live document
> is not something R takes away: the editor pushing it is
> still open and still ticked, and it puts it back within the
> second -- so say what this actually did, which is to go and
> fetch the song's own copy underneath it.


### `LyricsView.set_on_top`

**line 17515** — before `self.on_top = on`

> on_top is set below, and enter_fullscreen reads it to carry the
> hint over the window it re-creates; tell it now.


### `LyricsView.resizeEvent`

**line 17527** — before `self.layout_cache.clear()`

> Not drop_pixmaps: the width a line was drawn at is in its key, so
> the old ones are simply not asked for again, and a drag across the
> desktop delivers a resize a frame -- each of which would otherwise
> have thrown away the column and rebuilt it before the next one
> arrived.


### `LyricsView.closeEvent`

**line 17634** — before `self.unfollow_editor(pause=False)`

> Before anything else: a muted player is this window's doing and
> must not outlive it.

**line 17639** — before `self.pump.stop()`

> Before the signals are pulled: the sampler emits on every reading,
> and one landing in a half-dismantled window is a slot running
> against objects that have gone.


### `main`

**line 18231** — before `if not hasattr(args, attr):`

> Not every setting is a flag. `align_ckpt` names a checkpoint to obey
> for good, which is a decision that outlives one launch -- it is read
> from the settings file at the point of use and has no business on
> argv, so there is no attribute here to fill in. Filling in only what
> the parser actually declared lets a settings-only key exist without
> taking the whole window down on the way up.


### `main._fixture`

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
> trained is what runs by default now: measured against the hand-made
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
> its nearest edge, which would quietly pull every estimate towards zero.
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
> would turn a clean exit into a crash dialogue.

**line 3796** — before `self.error = self.server.errorString()`

> Nearly always a second copy of the app already holding the port.
> Not fatal and not worth a dialogue: everything else still works,
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

**line 4306** — before `self._duet_rgb = (None if self.duet_colour in DUET_MODES`

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

> fade towards the top/bottom of the viewport as well as by line distance
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

> collapse to the edge you moved towards, not to where the caret was


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

**line 9738** — before `"sung_colour": ("auto" if self._sung is None else`

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

## 2026-10-17 — Clear backdrop on a layered window

Reported from Windows 11 (clear, Clear backdrop "mica", Background dim 0.65): "i don't have mica installed but why is it like this … there's some random background things and it's not really clear". The "random things" were their other windows. The dark bands line up with the Spotify app behind (top bar, header, player bar, its right panel's edge). Mica never shows windows, only a blurred wallpaper, so the material was not on. Yet the drawer read plain "mica", because `DwmSetWindowAttribute` returned S_OK.

Qt makes a frameless WA_TranslucentBackground raster window layered (WS_EX_LAYERED, drawn by UpdateLayeredWindow), and DWM draws no system backdrop behind a layered window. `_dwm_backdrop` now checks the extended style first (`_layered`) and reports False there, so the drawer says "mica · not here" instead of claiming it. Unverified, with no Windows here. If their drawer then says "not here", the layered reading was right. Getting a real material would need a non-layered translucent surface (a GL one, or Qt's DWM path for accelerated windows), which is a bigger, blind change.

What they see stays as it was: plain glass, darkened by Background dim. Glass that reads as clear needs the dim low (0.65 is most of the way to black).

## 2026-10-17 — KWin blur behind a clear window, and Visualiser dim

**KWin blur.** Clear backdrop was Windows-only, so on KDE the drawer said "mica · not here". KWin's Blur effect blurs behind any window that asks, through KF6's `KWindowEffects::enableBlurBehind(QWindow*, bool, QRegion)`, which PyQt does not expose. `_kwin_effects` calls it through ctypes, but only where `libKF6WindowSystem.so.6` sits beside the `libQt6Core` this process already has mapped: PyQt on the system's Qt, as on Arch. A pip PyQt brings its own Qt, and loading KF6 there would put a second Qt in the process, so it is never loaded. Any of mica/acrylic/tabbed in clear mode asks for blur (`_kwin_blur`), if `isEffectAvailable(BlurBehind)`. The drawer then reads "mica · KWin blur". Turning it off never loads KF6 just to do so. On headless KWin (no GL, no Blur effect) availability is False and nothing is asked. There, the call itself was run on a real Wayland window both ways and survived, with one Qt mapped. The QRegion must outlive the call: a temporary freed before KF6 copies it segfaults (it did, in the test).

**Visualiser dim** (`viz_dim`, Background ▸ Visualiser ▸ Dim, `--viz-dim`, default 0). Background dim is the veil inside the wall picture, and the visualiser is laid over the wall afterwards, so the dim never reached it. With bloom over the mesh's blobs, the visualiser IS the wall. The layer is now drawn at `_viz_mix * (1 - viz_dim)` over the dimmed wall. Under a white test layer: 255 at 0, 112 at 0.6, 18 (the wall alone) at 1.

Same day, "all mica/acrylic/tabbed are the exact same": KWin has one blur, so on KDE they are told apart as Windows does: a tint of our own baked into the clear scene (`KDE_MATERIAL`, in its key). Acrylic is the blur alone, mica (24,24,28)@0.30, tabbed (14,14,18)@0.45. Where KWin's Background contrast effect is on (`isEffectAvailable(9)`), `enableBackgroundContrast` also mutes them (contrast, brightness, saturation 0.9/0.8/0.6 and 0.85/0.6/0.5). On the desktop the contrast effect is not loaded, so there it is the tint alone. Measured at Background dim 0.2: the scene pixel is 5,5,10,51 for none and acrylic, 18,18,20,112 for mica, 13,13,16,142 for tabbed. "auto" read "auto · not here". It asks for nothing by design, and now reads "auto · none".

Then "mica still says not here". On their real KWin, `isEffectAvailable(BlurBehind)` reads False until the first Wayland roundtrip brings KWin's globals, then True (measured: False at once, True after ~0.75s). The window asked once, at startup, got False, and never asked again. Now the blur and contrast are always requested (KF6 holds a request until the manager is bound), and `apply_backdrop` re-checks up to three times, 0.7s apart. The count resets whenever clear is settled again. Checked on their KWin with a never-shown native window: False on the first ask, True after the roundtrip. Their Background contrast effect stays unavailable after it too, so there the materials differ by tint only.

## Editor pushes read off the window (2026-10-17)

Each push from the editor was parsed and timelined on the window thread:
12-13 ms median (to 30) per push, up to five a second while tapping. The
link now answers at once and `show_live_lyric_soon` hands the TTML to
`offload.call(lyric_sources.read_pushed, …)` from a thread; only the newest
waits, and an unreadable one goes back to the editor as `{"ev":
"push-failed"}`. A plain thread was tried first and still held the GIL for
~5 ms a push. Offscreen real window, a push every 180 ms, 20 s, two runs each:

|                         | on the window | worst gap | frames >1.5x |
|-------------------------|---------------|-----------|--------------|
| read in place           | 8.9-9.2 ms    | 39-41 ms  | 9-36         |
| read off the window     | 0.3 ms        | 18 ms     | 0            |

The pool is shared: a push can wait behind a Genius alignment (~1.3 s, once
a song). `_secs` is memoised too (8.8 -> 6.4 ms a parse).

## 2026-10-17 — Double-click and drag selects by words

Qt 6 delivers the second click of a double click as a press before the
double-click event, so `Field.press` armed `field_drag` and the drag after
`pick_word` moved the caret by letters from the word's start: dragging back
dropped the picked word. `Field.picked` now holds the picked run, and
`drag_to` extends by whole runs from it (forward from its start, backward
from its end). Any text change or new press clears it. The editor's
QLineEdits had the same fault in Qt itself; `editor/worddrag.py` is an
app-wide filter that does the same there.

## 2026-10-17 — Real Mica on Windows: EXPERIMENT, unverified

Decided after the layered-window finding above. Qt makes a clear window layered only when it is frameless (`setWindowLayered`: alpha + FramelessWindowHint), and DWM draws no material behind a layered window. So with clear plus mica/acrylic/tabbed on Windows (`win_material`), the window keeps a frame Qt can see: CustomizeWindowHint + WindowTitleHint, no buttons or system menu, not frameless (`set_frame_flags`, used everywhere the frameless flag was set). Three things then take the visible frame away:
- `nativeEvent` answers WM_NCCALCSIZE with "all client" (`_no_client_frame`), inset by the frame when maximised.
- `_frame_changed` sends SWP_FRAMECHANGED after creation, so that answer is asked for.
- `_dwm_backdrop` extends the frame into the client area and sets the system backdrop, as before (and now passes the layered check).

Qt's raster backing store for a non-layered alpha window is ARGB32 premultiplied, flushed by BitBlt. With the frame extended, DWM should take its alpha, so the transparent pixels show the material. Moving and resizing go through `frame_press`, as for the frameless window. Linux is untouched: `win_material` is False there, `nativeEvent` is only defined on Windows, and the flags were checked through a clear → art switch.

Known rough edges, if it works at all: Qt still believes in a title bar, so a background change that remakes the window can bring it back one frame larger (no geometry is saved, so nothing drifts across restarts). There may be a 1px DWM border. If the window comes out black, the alpha is not reaching DWM through BitBlt, and the fallback is Qt's own `_q_windowsCustomMargins` or our own wallpaper blur. Any of these is reported back from the Windows laptop.

## 2026-10-18 — 1.1.9 hung in show() on Windows: the nativeEvent override

Reported from a Windows machine (bg mesh, backdrop none, so `win_material` off): the player never showed, the editor ran. `stalls.log` had five dumps after the last 1.1.8 run, none ever answered. In all five the main thread is at `w.show()` (main, line 25819) with no Python frame above it, and every other thread is stopped at a point where it takes the GIL back (after `open`, `socket.close`, `http send`, WinRT `get()`). That is a GIL deadlock inside window creation. The 1.1.8 dumps never stop there.

The one thing 1.1.9 put under `show()` on Windows was the class-level `nativeEvent` override from the Mica experiment above. It was defined for every window, so every Windows message, including ones another thread sends synchronously during CreateWindowEx, went through Python even with the material path off. Mechanism not proven (no Windows here). The likely shape: a thread holding the GIL waits on the GUI thread (the WinRT/SMTC readers are mid-call in every dump), and the GUI thread waits on the GIL in the override.

Fix, the safe way round: no override at all. `_FrameFilter` is an app-wide native event filter that `_frame_filter` installs only while `win_material` is on, and removes when it goes off. It matches WM_NCCALCSIZE by the window's hwnd, which `apply_backdrop` sets just before `_frame_changed` has Windows ask again. So a default Windows window is made exactly as in 1.1.8. The material experiment still runs Python per message while it is on, so it can still meet this deadlock. Shipped as 1.1.91 and confirmed fixed on that machine (2026-10-18); the material path itself is still unverified.

## 2026-10-18 — Draw ahead gave up after a move between screens

Bug: the frame rate capped at 120 / 240, windowed on DP-3: the HUD said
`callback`, and Draw ahead read "on · swap not paced, off". The rate guard in
`_ahead_frame` had tripped while the window crossed to HDMI-A-1 and back
(`heard` flipped 60/240 four times in 13s): 240Hz swaps, judged against a
60Hz period, look unpaced. Off for the session, every frame then started at
the callback, and a 4.7ms paint missed the ~2ms windowed deadline every time.
Toggling the setting brought 240 back.

`retune_frames` now clears the swaps and lifts a give-up whenever the refresh
rate changes (`frames ahead-retry`); a give-up at one rate still stands.
The give-up itself is logged (`frames ahead-gave-up`, gap_ms, hz).

## 2026-10-18 — Lifted glow passes drew the whole line each

Their trace (windowed 1920x1020, GPU, draw ahead, a browser video playing the
song): 210 fps, ~10% of frames a refresh late, wall = CPU everywhere; the lyric
column was 3.5-4.5ms CPU while lines were sung, 0.7ms before the first line.
Offscreen A/B on the same frames (bench_column, Bruno Mars at 40s): 1.1.8
3.7-4.0ms a frame, 1.1.9 4.4-4.8. The difference was all_glow's per-letter
lifts (1.1.9): every lifted stretch re-ran draw() over every band of the line
and clipped all but its own rect away (_glow_flush 1634 -> 4109 calls).
`draw(near)` now builds and sends only the strips that reach the pass's clip:
4.0-4.2ms, lyric column pixel-identical on GL and raster (the HUD and a
progress bar differ run to run). ~0.3ms remained over 1.1.8: the save/clip/
translate and one flush per lifted pass.

Then the lifted passes were merged into ONE drawPixmapFragments on GL
(`_glow_gl` / `_glow_frags` / `_glow_draw`): each fragment cut by hand to the
scissor its clip rect would have set. Qt 6.11's GL engine rounds each mapped
edge of a rect clip (probed 300/300 random scale+translate cases; toRect 235,
toAlignedRect 14). Raster, or a clip already on the painter, keeps the
per-pass loop. Lyric column against the old code: worst 1/255, within the
bench's own run-to-run noise (two runs of one copy: 6 frames, worst 5/255);
4.9 -> 4.2-4.45ms in the same window.

## 2026-10-18 — A settling line stepped down whole pixels

"When a line settles back down, the going down looks a bit choppy." The amll
word float (`Amll.word_lifts`) was `on_grid(unit * RISE * rise * act *
(1 - blur))`: the FADED height rounded every frame. As a left line's float
eased down (activation's ~60ms, or `left_hold`'s sink over a held word's
landing, ~0.5s) it sat at 4.00px, then fell a pixel at a time -- once 4, 3,
4, 3 as the value hovered at a rounding edge. Now the resting height is put
on the grid and the fade scales it: at rest act is exactly 1 and blur 0 (the
activation snaps within 0.004), so lines at rest are on the grid as before.
Logged per frame at 240Hz (Bruno Mars from 40s): the leaving line moves every
frame, 4.00 3.89 3.62 3.20 ...; cost unchanged (3.98 vs 3.99ms).

## 2026-10-20: Source list, simple or extended

Settings ▸ Sources ▸ Source list (`source_list`, `--source-list`). Simple shows
only Sources, in order, and `apply_syncs` hands the chain no Syncs rules (no
refused syncs, no order of its own, NetEase's graft on), so the sources' order
rules alone. Extended replaces Sources, in order with Syncs, in order, applied;
a source with no sync at all (Genius) keeps its own row, last in that list.
There the Syncs are the only switches: a source is asked while any of its
syncs is on (menu_set turns src_* with them), and a source switched off under
Simple shows its syncs off. The Syncs
choices are kept either way; switching back brings them back unchanged. Unset
(`""`), it picks extended only for whoever already shaped Syncs: something
switched off, or an order that is not the one the sources give. The Sources
divider is now placed after DRAWER_WHEN, or it held the empty "Syncs" heading up.

## 2026-10-22 — This song links to the audio and the video

Goal: This song links to the audio file and the YouTube video on the web. Two rows under Playback:
- **Audio** (`web_audio`): what Mild Lyrics' player streams. That is the YouTube Music release (`music.youtube.com/watch?v=`) when the resolver picked it, the upload's own `youtube.com` page when it was picked by hand (YouTube tab, pasted link), and the Bandcamp/SoundCloud page as it is when that is the upload. Nothing for Spotify or another player, or for a local file.
- **Music video** (`web_video`): the video behind the lyrics, else the one the Finder picked for the song.

In the drawer's song tab a row whose value is an `https://` link is drawn in link blue, and clicking it opens it in the browser (the `link` hit; `open` was taken). Every other row still copies, and the footer says so. Checked offscreen on the real window with `QDesktopServices.openUrl` stubbed.

Later the same day (asked: "make the track ID also the Spotify link, and make right clicking them copy the ids"):
- **Track id** is now `https://open.spotify.com/track/<id>`, still only for a real Spotify id (not a 22-hex name key).
- A right-click on any link row in the song tab copies its id (`link_id`): the Spotify track id, the YouTube video id, or the whole link where there is no id (Bandcamp). A left-click opens it.
- The classic interface's info box copies what it shows, so the link there.

Checked offscreen with real right-button `QMouseEvent`s through `mousePressEvent`: the clipboard held `7qiZfU4dY1lWllzX7mPBI3` and `074r1TFfo0M`.

## 2026-10-22 — Windows freeze at startup

Seen on the Windows laptop: now and then the window freezes at startup ("Not Responding", for good), in 1.1.91 and in this checkout. Spotify was paused on Let You Down. `stalls.log` has 9 freezes since 10-18 that never ended. The entries hours long are sleep.

What the log shows for today's freeze: the GUI thread sits in `app.exec()` with no Python frame, which means it is waiting for the GIL. Every other thread is parked in a wait that hands the GIL over, except two. One is a cover read (`_thumb_bytes`, in `get()` on `stream.read_async`). The other is a thread that had finished, frozen at `threading.py:999` (`del self._target...`) with no Python under it. The 10-20 00:04 freeze has the same shape at `:995`, where a returning function's locals are freed after the frame is already off the stack.

pywinrt's generator (PyWinRT/WriterExtensions.cs) releases the GIL around method calls, `get()` and `wait()`. `_dealloc_*` does not: `std::destroy_at(&self->obj)` runs the COM Release with the GIL held.

The window did WinRT on the GUI thread: `LyricsView.__init__` → `clock.poll` → `SmtcTransport._read_one`, plus seek and command on clicks. Qt's GUI thread is an STA, so the sessions it listed (cached in `_seen`) and `info.thumbnail` were the GUI thread's. They were then used and freed on other threads. Freeing one off its apartment is marshalled back to the GUI thread. If that thread is waiting for the GIL just then (a timer firing a Python slot), and the freeing thread holds it, neither moves again. This is an inference: faulthandler cannot show native frames, and the py-spy `--native` dump that would confirm it was not taken.

Fix: `_WinrtHome` (`_WINRT`), one thread where every WinRT call is made and every WinRT object is freed. `SmtcTransport.read/seek/command/drop` and `windows_output` run there and hand back plain values. Exceptions have their traceback cleared on that thread, so WinRT locals don't die on the caller. `_run_winrt_here` waits at most `WINRT_WAIT` (3s) through `wait(timeout)`, or `asyncio.wait_for` on projections without it. An operation that runs over is cancelled and kept in `_WINRT_KEPT`, never freed. The cover read lost its throwaway thread: two `THUMB_WAIT` (0.75s) steps, and on a stall the ref and stream are kept too. Callers wait with the same limits (a read gets 6s). While a job has run past a caller's limit, new calls fail at once instead of queueing, so the window shows "Error" and carries on.

Checked here with fakes (scratchpad winrt_home_check.py): objects made in a job, and in a job that raised, are freed on `mild-winrt`. A stuck job times out and the next call fails fast. Read, seek, command and drop all run on the thread. test_platforms is 99 ok. Untested on Windows.

Later the same evening, with the fix on the laptop: two stalls that cleared themselves, neither of them WinRT. In one, at 21:46, the GUI thread waited 16.5s in `LyricsView.__init__` → `clock.poll` → `spotify_dom.evaluate`. Spotify's debug port accepted the connection and then let the read run to the socket's 15s timeout. That first synchronous read is gone. `_read_tid` starts at None, and the pump's first reading reaches `on_reading` as a track change, the same way a song change after launch arrives. Checked in the real window offscreen with a transport whose first read sleeps 3s: `__init__` took 0.04s, the read ran on the pump's thread, and the song was taken at 3.04s (scratchpad slowstart/harness.py). The other stall, at 21:37, was 5.3s in `launch_spotify` → `spotify_running` (tasklist, which has a 5s timeout), before the window exists. It is left as it is.

## 2026-10-23: startup marks ("boot" rows in follow.log)

Bug: Mild Lyrics opens much more slowly on Windows than on Linux. The laptop's stalls.log for tonight's start: the window did not answer for 7.4s, with the main thread in `w.show()` and no Python frame under it, so the time went into native code (GPU drawing is "on" there, so the GL canvas is already in the window). The process was 12s old before the window answered. The debug overlay's "startup" counts from `debug_hud`'s import and misses everything before it.

`boot_mark(what)` writes `{"who": "boot", "ev": what, "age": s}`, where age is the process's age as the OS keeps it (`GetProcessTimes` on Windows, `/proc/self/stat` on Linux), Python's own start included. The rows: main (with `imports`: seconds since lyrics_gui began loading), settings, qapp, built, gpu, show, shown, loop (the first turn of the event loop), gl-init (every new GL context, via `GC.ON_INIT`) and painted (the first paint, via `DH.ON_FIRST`). Offscreen on Linux (--no-persist, a fixture): painted at 0.31s. To be read off the laptop after one ordinary start.

The laptop's first rows (22:32, Spotify not running): main 1.10, qapp 1.22, built 6.98, show 6.99, gl-init 7.36, painted 7.42, loop 7.55. So this start spent 5.8s building the window and only 0.46s in show(). The 7.4s in show() at 20:42 was a cold GL start that this start did not repeat. stalls.log caught the build in `make_transport` → `CdpTransport.usable()` → `spotify_dom.list_targets`, waiting in `create_connection`. On Windows a connect to a closed loopback port is refused only after ~2.07s (measured on the laptop with .NET for 9222 and port 9; the stack retries the SYN), and every `usable()` and every dial on the GUI thread pays that while Spotify is closed. `spotify_dom._listening` now probes the port first with a 0.25s timeout on Windows (a listener answers in under 1ms). With the probe deployed (22:45, Spotify still closed): main 0.83, qapp 1.00, built 1.66, painted 1.83, loop 1.91, down from 7.55. The whole 5.8s build had been the dial: the other ~3.7s never showed up. A cProfile of the build (temporary, laptop only, since removed) put 0.59s into it: the probe's own 0.255s timeout, 0.22s in `QFontDatabase.families()` from `resolve_font` (Qt filling its font list on first use, which the first paint would otherwise pay), and nothing else over 0.05s. The probe's 0.25s is left as it is: a listener answers in under 1ms, but a busy laptop that misses the deadline would start on the media-transport fallback until watch_port notices.

The rest of stalls.log, sorted the same evening. Footers with no stacks above them are standby: the faulthandler alarm never fired. Every stall since 10-18 that has stacks came at launch or in the first minute after a wake or a boot: debug_hud's first `_render` (9.1s, 10-20 13:08, a minute after a wake), a glow blit on the first paint (6.0s, 10-22 21:14, after a wake), an import (23.4s, 10-20 00:04, after a boot) and show() (7.4s, 10-23 20:42, a minute after power-on). The others are already handled. The 10-17 run of 5.9s stalls every 6s is `_await_spotify` dialing a closed port, which `_listening` now covers. The 16.5s CDP read in `__init__` and the GUI thread waiting for the GIL in `app.exec()` (including the 29.5s at 10-20 00:22) are the 10-22 entries above. The four 0xc0000374 crashes on 10-22 are the soundcard race in live_audio.md. Since then: no crash events from Python in the Application log, no WER dumps, and no leftover offload workers.

## 2026-10-23: Periodic table (troll)

Settings → Troll → Periodic table: off / under / top right / numbers / symbols only / numbers only (`periodic`, `--periodic`). The two "only" modes are numbers or symbols with no small row (`PT.READS`), so furigana still works under them. Every word is spelled in element symbols (periodic.py): "mistake" is m I S Ta K e, the letters no symbol covers in lower case. The cover is the one that leaves the fewest letters out, then uses the fewest symbols. Words are runs of ASCII letters only, so an apostrophe or an accent ends one.

`line_pieces` re-cases the pieces, so every renderer shows the case. The numbers ride the furigana channel (`ruby_rows` → `periodic_rows`) and replace furigana while the setting is on. Timed pieces carry no spaces (a piece not glued to the next ends its word), so `line_pieces` puts one back before spelling. Without it "But I've" was spelled as one word. `periodic_rows` spells the laid-out fragments again and treats a row break as a word break.

"under" moves the reading band below the row. Every place that put the text `ruh` below the row top now asks `ruby_lead`, and every reading baseline comes from `ruby_base`: Flow's base, fill, spin box, clouds, zero-g, the line pixmap, review marks, and Spicy's `_baseline`. "top right" keeps the band above, sets each number's baseline just over the capitals, and starts it at the symbol's right edge. The flowplan, cards and Spicy layout keys and layout_ahead's key carry `periodic`.

Checked offscreen on the Rolling in the Deep fixture in Flow, AMLL, Spicy Lyrics, Karaoke and Cards, both modes, with no tracebacks.

"numbers" writes each symbol as its number in the lyric, separated by U+2027, the hyphenation point (`PT.SEP`). Outfit's own middle dot (13.9px at 48px) looked cramped. A hair space each side (26.7px) was too wide; about a quarter of that added space was wanted. Outfit has no other dot, and the fallback's U+2027 is 18.5px, about a third of the hair-space addition. Exactly a quarter would mean drawing the gaps in every renderer. Not checked on Windows, where the fallback font differs. with the symbol small under it (`PT.numbered`). The letters no symbol covers stay full size. A piece whose letters all went into a symbol that started in the piece before is dropped, and its end and glue go to that piece. `periodic_rows` reads the digits back off the laid-out text, so a number already in a lyric (1-118) gets a symbol too. Thin and hair spaces were tried as the separator. The thin space read as a word gap, and with the hair space "9 53 75" ran together as 95375.

Their first live look (amll, word glow 0.5) showed a second, glowing copy of the numbers next to the real ones. `all_glow` lights the line from `line_pixmap` drawn in the glow pen, and shifts it with a held word's spread letters, so the numbers in that picture were moved off their place. Glow pictures now leave the readings out while the setting is on (`bare` in the key). Top-right numbers touched the capitals once the word rose. They now sit 12% of a line height above the cap height. Each one starts at the symbol's right edge, like a superscript. Centring them on that edge put 68 over the r of "Er" rather than past it, unlike O's 8 and V's 23. `ruby_anchor` looks up the fragment just inside the symbol, so the lift, the float troll and the fill follow the symbol rather than the letter the number hangs over.

Switching modes only took effect on the next song. `line_pieces` cached its pieces per line and checked only that the source pieces were the same objects, so a line spelled for under or top right was served again in numbers mode. The cache now also records whether it holds numbers. Checked in the real window on a fake clock (scratchpad bench_switch.py), with `menu_set("periodic", ...)` mid-song: numbers, top right, under, numbers, and each frame showed its mode.

The same evening, three more:

- **Held long words collapsed.** `Amll.shaped_units` read glyph-run string indexes over the whole word. A word in two fonts (Outfit has no U+2027, so the separators come from Noto Sans) comes back from Qt with every index 0 or run-relative. "23‧68‧d‧74‧53‧j‧7‧t" became two units, "2" and the rest, and the ~400px rest was scaled as one letter, which pushed the "2" into "nacht". With more than one run it now asks Qt one character at a time, counting UTF-16 (an emoji is two). A character that lands where the one before it did is inside the same cluster, so ligatures hold ("fl‧fl" gives fl, ‧, fl). Any word with a fallback glyph (emoji, a stray symbol) had the same fault before the periodic troll existed. Checked on a fake clock with real-use settings (bench_switch.py, scratchpad nacht.ttml): the first letter now stays within half the word gap.
- **The dot ends the earlier syllable.** `numbered` writes a separator into the piece holding the token before it, so a syllable split is read as "23‧68‧ | d‧74…" and the dot fills with the syllable it follows.
- **CJK and other romanised scripts.** The original script has no Latin letters, so the troll goes on the romanisation. With romanisation "instead" that already worked. With "under", the romanisation rows now go through `roman_pieces`, and their readings ride on the rows list (`ReadRows`, and Spicy's `RowsRead`: `.ruby`, `.rufm`), so layout_line's 7-tuple is unchanged. Each place that steps through romanisation rows adds `roman_band`'s height: the line pixmap, draw_base and fill (both draw them through `Flow.roman_reads`), clouds, zero-g, all_glow, and Spicy's lay and `_roman_rows`. A line with no periodic marks falls through to furigana. Where a band sits now comes from the readings themselves (`Readings.place`: over, under or corner) rather than from the mode, so furigana stays over the kanji while the numbers go under the romanisation. The glow picture leaves out only the periodic numbers. Inline superscript digits were tried first and dropped: Outfit has only ¹²³⁴, so the others came from a fallback face.

## 2026-10-24: Fetch-ahead picks the sync ahead

Bug: for some people the look-ahead does not work. The next song still loads live, even with a queue the window can see. `_warm` used to warm caches with a walk of its own (`LS.fallback(tid, meta, "none")`) and the load then decided again, so the warm only helped where the load's walk asked exactly the same question (`names`, `bar`) as the stored answer. Two places where it did not:

- **Syncs order.** The warm walk worked out "ranked above Spicy" from the plain source order (the lead round in `_walk`). The load asks `LS.ahead_of`, which follows the Syncs order. With NetEase@w above Spicy@w and Spicy holding word timing, the warm asked Spicy alone and the load then walked NetEase live. Measured in a scratch harness with fake providers (scratchpad ahead/exp.py): warm `[spicy]`, load `[spicy, netease]`.
- **Local streams.** `local_ahead` keyed a stream by `LS.spotify_id_known(key)` when the resolver had no id. `LocalPlayer.reading` plays it under the name key in that case, so the record was filed under an id the load never asks for. The row now uses `reading()`'s id; the lyric-side id rides along as `meta["_spotify"]`.

Change: `_warm` now runs `_load_words` itself (`_pick_ahead`), with `_here.quiet` set: no interim, no stand-in, `_mine()` False, no `source_trouble`, no page socket (no token grab, no catalogue search; the Spotify id comes from `_spotify` or `spotify_id_known`). So the pick, the NetEase graft, the shaping, the uncensoring and the duet flags are all done ahead. The finished `(lines, body)` is kept in `Fetcher._picks` under the song's id and its `_spotify` id, with `_pick_key` (sources, order, graft, fold, uncensor, roster, bases, syncs, the song's own pick, split/threshold, Spotify lookup). `_load_words` hands it over once (`_kept_pick`) when the key still matches and it is under `PICK_KEPT` (30 min) old. The roster's `met` comes with it, so `people_met` still fires. Nothing is kept when the walk was cut short, when a source failed (`note`, or Spicy unreachable), or when a name-keyed song has no id yet and Spotify lookup is on (the load may still find one). Then the load decides as before, from the warmed caches. `ahead_ready` now carries the lines the load will show, so LayoutAhead and roman_ahead work from the real document and not an unshaped one. The debug overlay says "sources: picked ahead" for such a load. When the fetcher's own sources/order differ from the scan's (before the first `request()`), it warms as before.

Tests: test_fetcher 142 (seven new: the Syncs order case, Spicy word timing, a changed setting, a failed source), test_home_page 186 (the stream id), test_adlib_open 30, test_isrc_match 30. Not yet seen in the real app.

## 2026-10-24 — a new song jumping to its first line

**The real cause is in home_page.md, same day** (a stale link reloaded at the previous song's place). What follows is the first-line lead, which turned out to be their own clicks.

Bug: Mild Lyrics sometimes started a song more than halfway through, when the next song starts, in the lyrics view. In follow.log (10-23 22:00 to 10-24 18:30), 7 songs played from 0:00, then 0.8–2.6s in were sought to the start of their own first lyric line plus the global offset (−0.1). Fall To Light went to 37.36 (first line 37.46); One Night Only to 73.779 (73.879); Somewhere I Belong to 40.971 (41.071). Each seek arrived in the player's normal playing state (BufferedMedia), not through its own resume.

Ruled out: the editor link (no traffic), plugins (off), listen-along, Auto resync (off), the clock's pin (Spotify only), the music video (it only follows), and `_seek_when` (it needs a lyric click on a Song page). Only a click on that line in the lyrics view or Down from the intro gives "first line + offset". `seek_line(+1)` from 1.1s returns exactly 37.36 for Fall To Light. Which of the two it was is not in the log.

A 3s hold on line jumps after a song change was tried the same day and taken out. It dropped their own clicks, since they click lines right after a song starts on purpose, and the seven cases may have been clicks too. What stays: every `seek_song` logs `seek-song` with its caller, so the next unwanted jump names its source.

Other far starts in the same log, not this report: restarts resume the saved queue where it was (checked against plays.jsonl, mostly right to a few seconds); "Demuxing failed" reloads resume where the stream broke. Two jumps after going back to a song (FEAR to 263.1 of 268, HOPE to 170.0) are not explained yet. FEAR's lyrics end at 250, so FEAR's was not a line. The play log also showed a song logged with the previous song's length (FEAR, 129.8 = Story of a Warrior's): `LocalPlayer._snap` keeps the old length until Qt reports the new one.

## 2026-10-25 — the editor's Discord card wins while it has a sync

Bug: while syncing a song, the Discord card kept switching between the TTML Editor's and the player's. Both use the same application ID from their own IPC connections, so each new SET_ACTIVITY took the profile in turn.

Now the editor tells the player over the link whether its card is up (`cmd:discord`, `{"on": bool}`). `discord_rpc.Status.hold` sends it when the card comes or goes: up only when the editor's `activity()` is not None, i.e. Discord status is on there and a document with syllables is loaded. It sends again after every reconnect (`connected` resets `told`), and `False` from `stop()` on close. `LiveLink` keeps the sockets that said yes, and a closed socket drops out, so a crashed editor gives the card back too. While `editor_discord()` is true, `discord_tick` hands Presence None, which clears the player's card, and the drawer note says the editor's card is showing. With the editor's Discord status off, or no sync loaded, the player keeps its own card.

Tests: scratch test_discord_handover (real loopback sockets, 14 ok); test_editor_discord 30, test_discord_paused 19, test_livelink 78. test_linkgc aborts at HEAD: its `_Owner` stub has no `own_player_state`, which the state pulse calls; it passes with that stub added. Not yet seen on real Discord.

## 2026-10-25 — Fill song names left one song unnamed

"Fill song names" (`start_backfill` → `Fetcher._backfill_batch`) asked only the Spotify page (JS_TRACKS). With Spotify away, or for a track it returns no name for, the song stayed "1 to do" for good, and the run still said "song names filled in". Their one was 7mykoq6R3BArsSpNDjFQTm, "I Really Want to Stay at Your House" (Rosa Walton, Hallie Coggins), which is nowhere in plays.jsonl. Now each id the page did not name, if it is Spotify-shaped (22 alphanumerics), is read from Spotify's public embed page (`SS._embed("track", id)`, no app). The finish toast counts any that are still unnamed. test_backfill 4/4.

## 2026-10-26 — Spotify readings dated by the page, corrections rebased (PR #3)

From remiuku's PR #3 (merged as-is, 5100dd3). The carry on every platform and the wider stamp window below came on top. Two bugs:

- **Dating.** `CdpTransport.read` put each reading at the middle of the round trip. A stalled `Runtime.evaluate` (2.76s, seen on Windows) put the clock 1.37s ahead, and it stepped back on the next reading. JS_STATE now reads `ctl` after the engine's await and returns `sampled_at` (`Date.now()`). The read maps that onto mono() through `time.time()`, clamped to [began, ended]. An answer without `sampled_at` still uses the midpoint.
- **Overlapping slews.** `Clock._apply` measured each new error against `_pos + elapsed` and replaced `_slew`, so whatever was left of the last 0.35s correction was dropped as a step. Readings come every 250ms (60ms near edges), so this happened on most readings: 0.03-0.1s steps in the PR's test. It now rebases from `position(at)`, which includes the unfinished slew. A jump over SLEW_MAX, a pause, a track change, an audio hold or the resume settle sets the slew to 0 instead of keeping the old one.

The engine's `getPositionState()` also returns `timestamp` (a BigInt, ms) and `playbackSpeed` (0 when paused). On Linux the timestamp is on perf_counter's clock to within 1ms (read 2026-10-26, paused). The PR reports Windows uses the same clock. The engine position is carried from that stamp to `at` at that rate. Both platforms do this, not just Windows as in the PR. A stamp is used if it is no more than 50ms later than `at` and no older than max(STALE_HOLD, track length). That rejects a wall-clock stamp, and it still covers builds that only refresh the state on a change. The PR's 1s window would have snapped those builds back about 1s, one second after each change. macOS is untested.

Checks: the PR's 13 unit tests in tests/ (`python -m unittest discover -s tests`; 10 fail at 7da78b6), plus checks that an old stamp is carried and a wall-clock stamp is ignored (15). test_players 167/3, test_resync 18, test_local_seek 21, test_unpause, test_listen_along_resume give the same results before and after.

## Editor-driven lyrics get the global offset (2026-10-26)

While the editor drives the words (its own file, `editor_position`), `LyricsView.position()` used to return the editor's clock plus `track_offset()`, and every draw takes `track_offset()` off again: the words were drawn at the file's own time, with no offset. Every other document is drawn at the clock less the offset, so with a global offset of −0.1s a shared lyric ran 100ms behind the same file played afterwards. A clicked line still looked right, because the seek lands the sound and the words together. The rest of the line was late.

From a follow.log stretch the clock itself checked out: the player's copy of the editor clock was within 1ms of the editor's (118 playing samples), and `LS.read_pushed` kept every time it was handed. `position()` now returns the editor's own time. Drawing then takes the offset off as it does for anything else. Seeks, the muted player walked underneath and the toggle keep the old mapping (`editor_position`). `HomePage.mini_pos` does the same as `position()`.

The editor's own preview still draws the file's time with no offset when timing against a local file. Against Spotify its clock is already the player's less the offset.

## 2026-10-29 — Open Spotify's probes moved off the GUI thread

A Windows stalls.log (15 dumps, 1.1.8 to 1.2.0, 10-16 to 10-29) had seven stalls of 5–8s in the first seconds after start with the GUI thread inside `launch_spotify`: five in the port dial (`usable` → `list_targets`, before the 10-23 `_listening` probe) and two in `spotify_running`'s `tasklist`, which runs up to its 5s timeout. 1.2.0 still made both calls on the GUI thread, along with one `usable()` a second for up to `SPOTIFY_WAIT` polls after `spicetify auto`. Now `_launch_spotify` runs all of it on a `spotify-launch` thread and hands back to the GUI through `spotify_up` → `follow_players`. Toasts are plain attribute writes, the same as `watch_port`'s thread does.

The rest of the log: two 5s stalls in 1.1.8 (a debug-HUD paint, and the `nativeEvent` override fixed in 1.1.91), three show() stalls of ~15s in 1.1.91 (native, a cold start; one dump had a thread importing `winsdk.windows.media.core`), two hangs that never answered (1.1.91, app.exec, the process killed), and a single 1.2.0 stall of 38s with the GUI thread native in app.exec and every Python thread idle or in socket I/O. Gaps with no stacks (458s, 1366s, 120s) are standby. `check_debug_flag` still runs two `spicetify` calls on the GUI thread (8s timeout each). None of them shows in this log.

## 2026-10-29 — Hover polled the output device once per mouse move

On 1.2.0 the same reporter's stalls came mid-song, with the pointer over the window. `saw_event` sets `_dev_wake` on every WAKE_EVENT, MouseMove included, and `_watch_device` polled again on each wake. So while the mouse moved, the output was polled at the mouse's event rate rather than every DEVICE_POLL. On the offscreen window (synthetic moves at ~120Hz, `audio_sink` counted) that was 479 polls in 4s, against 2 in 4s idle. On Windows each poll is `MediaDevice.get_default_audio_render_id` on the WinRT thread, and pywinrt holds the GIL through its calls, as it does through its frees (2026-10-22). On Linux each poll is a `pactl` spawn. A wake now only brings an idle poll forward, never nearer than DEVICE_POLL to the last one: 2 polls in 4s either way. Whether this caused the stalls is unconfirmed. The log had no stack from a hover stall, because at STALL_AFTER = 5s a stall shorter than about 4s leaves nothing. STALL_AFTER is now 2s.
