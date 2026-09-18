# Still to do

Reported and not yet fixed. Some of it is blocked on evidence -- a song
nobody has named, a question only the person who asked can answer -- and
some is work that is understood and simply has not been done. Each entry
says which, what is already measured, and where to start.

Fixed items are not listed. They are in the commit log, which says what the
measurement was.

Gone from this list since it was written: QQ Music on Windows, which was
never reproduced and now works; the two halves of the stutter that were the
drawn-line cache; the 2GB, which was an animated cover with no ceiling on
how many frames it kept; the resume hold, which turned out to be a
correction that could only ever go one way; and NetEase being passed over,
which is withdrawn -- there was never an example.

And, on a pass that ran each loose end instead of reading it: the pen the
interlude dots leaked, which cards leaked too and nobody had noticed; the
provider that raised in silence, which was already fixed; the stray
`aligner/&1`; and the five test files, which were four one-line path
breakages and a fixture in a dead scratchpad. Reading them was what had kept
them: three of the five entries were already false when they were checked.

Gone on the pass after that, which fixed rather than measured: the Spring
that could not take a step under a millisecond; the glow crediting a word
with the silence inside it; the Japanese particles, which were being asked
of a syllable and are now asked of a segment; and the text measurement a
cold layout pays twice. Each has its numbers in the commit log.

And one more that went the way the three above it did, on a pass that
fetched the documents rather than reading the entry: the QQ line whose words
differ from Apple's. It was written down as the blend needing to match a run
against a run, and the blend has never matched words to words at all -- see
_relay, which measured that and refused it. The letters are lined up and the
cuts come across with them, so a run is not a case. Koven's "Gold" fetched
fresh from both: "in love" cuts "enough" into "en" and "ough" on QQ's own two
stamps, through the pairing and through the re-stream alike, and split_asides
takes "(Ooh)" into a backing voice of its own. tests/test_blends.py pins both
halves now.


## Lag in the lyrics on Windows

**Reported:** half-fixed. It comes in random bursts, it happens when a better
source arrives mid-song and the same thing settles it again, sometimes when
the line changes, and `--viz 0 --bg solid --glow 0 --rise 0` is affected just
the same.

**Known and dealt with:** two of those were the drawn-line cache. It was
keyed by LINE NUMBER, so any document that disagreed about anything threw all
of them away -- and a better answer is nearly always the same words with a
better clock, which is not in the picture. It also shared one dict with the
glows under a rule of "over 400 entries, empty it", which fired two to three
times a song. Both are gone; see the commit for the numbers.

**What was left, and where it actually was.** The layout was the suspect here
and it was the wrong one. `Flow.plan` now lays the column out once per document
rather than once per frame, so the re-wrap this entry described is paid on the
frame a cache is cleared and not otherwise -- and measuring a frame instead of
guessing at it put the cost somewhere else entirely.

Timed over 2400 frames of "NF - Time" at 60fps, offscreen, with a warm cache
(`tests/test_paint.py` reports this now; it counted pixmap builds before and
never milliseconds):

                          median    p95    p99   worst
    before                 1.79ms   2.81   4.25   7.00
    after                  1.34ms   2.20   3.84   5.39

    pictures built on a line-switch frame:  1.9 avg / 3 worst  ->  1.6 / 2

`lifted_word` was 42% of paint time, and 27,673 of its 27,936 calls over that
sweep built a throwaway QPixmap. Its docstring says "only the one or two words
actually in motion ever pay for this", and `frag_lifts` says "a word at rest
sits exactly on a row of pixels and is drawn as glyphs". Neither was true:
`draw_base` calls it for EVERY fragment of the active line every frame, and the
fast path tests a baseline derived from `view.scroll`, which is a continuously
eased float. So for the whole second the column eases after a line change --
which is to say on exactly the frames anybody complained about -- no word could
take it, and the active line was rasterised word by word, twice over.

Rounding that baseline onto the device grid, which is what `on_grid` already
existed to do for where a rise ENDS, took the fast path from 1% of calls to
89%. The rest is the genuine motion, which still wants its picture.

Two other things went with it: the lyric font, its name and its metrics are
memoised together (they were being rebuilt forty thousand times a sweep, all
but a handful identical), and `line_ink` is kept on the line instead of being
rebuilt twice per visible line per frame. `Flow._warm_next` also spends the
pixmap ration ahead of a switch on frames that have it to spare, which is
nearly all of them.

**Two suspects checked and dropped**, so they are not chased again: the drawn
line cache's KEY, which is only 0.10ms of a frame, and the glow cache, which
costs about 0.4ms on the 46 frames of a sweep that build one.

**The smaller half of the cold layout burst is done.** It is paid when
`layout_cache` is cleared, which is a better source arriving mid-song or a
resize. Text measurement was the whole of it, as `wrap_pieces` already said
where it takes care to ask only once per fragment: 985 calls to
`fm.horizontalAdvance` in one cold layout of "NF - Time", 58% of them asking
about a fragment already measured.

`lyrics_gui.advance` memoises it, and the memo hangs on the QFontMetricsF
rather than on the window. That is the part worth keeping: a re-time is the
SAME fragments with a different clock, so a memo on the face survives the
layout cache being emptied and dies by itself when the type changes, because
`_lyric_face` builds a new face and the old memo goes with the old one.
Nothing has to remember to invalidate anything. Measured over the five longest
documents here, total time to lay every line out from an empty cache:

                            before    after
    a first cold layout     22.5ms    10.9ms      51% off
    a re-time of the same    22.5ms     3.7ms      83% off

Checked for identity rather than for speed alone: 31212 line layouts across
three widths and three alignments, every one of them the same rows to the
float.

**The bigger half is done too**, and it cost less than the entry feared.
`wrap_shape` decides where the words go and `stamp_rows` writes the times onto
it, so a re-time asks for shapes it already has -- the memo hangs on the
QFontMetricsF, beside `advance`'s, and needs no invalidating. Held to the old
loop line for line: 97794 layouts of every line of all 58 documents here, at
three sizes, three widths and three alignments, then 4020 more with the clock
moved underneath. Every one identical.

The last of it was not a refactor at all. `layout_line` was building
`QFontMetricsF(self.lyric_font(...))` per line, a new object every time, which
quietly undid both memos that hang on a face -- a re-plan with everything
supposedly warm was still making 945 calls to `horizontalAdvance`, one per
fragment, which is what a completely cold layout makes. `lyric_fm` hands back
the metrics `_lyric_face` already built for that font.

    a first cold plan of "NF - Time"    30.9ms  ->  26.1ms
    a re-time, everything else warm      3.39ms ->   0.34ms

Nothing was re-keyed and no `layout_cache.clear()` was removed. Keying that
cache by ink instead of by line number was the plan and is now not worth its
risk: what it would save is the 0.34ms above.

`layout_cache` being "an unbounded plain dict" was in this entry and is
withdrawn. It is a plain dict, but `resizeEvent` clears it and so does every
track change -- `reset_track`, `on_lyrics`, `rebuild_lines`, `drop_live_lyric`
and `on_font_ready` -- so it cannot carry anything from one song to the next.
What it holds inside one song is one entry per line per size tried.

**Two more of this entry's suspects, measured and dropped.** Both were written
down from reading and neither survived being run:

  * `LiveLink` walking `findChildren(QObject)` at 20Hz. It does, but a
    LiveLink's children are the server and its two or three sockets: **2us a
    call, 0.039ms per second of wall clock.** It is not a cost and it is not
    worth touching.
  * `autosave()` rewriting JSON from inside `tick()`. It is called from
    `tick`, at most every two seconds, but it compares its 19 scalars first
    and returns without writing unless one of them moved. The rewrite is paid
    on a setting actually changing, not on a tick.

**The "under load" half had a name, and it was not the walk's width.** The
suspicion about a fetch in flight was right about the GIL and wrong about
where it was held. Ten providers parsing TTML is 8-14ms each; `_qrc_des` --
QQ's QRC envelope, decrypted bit by bit in Python -- was **1.6 seconds** of
interpreter per cold track, three passes over each of two payloads, never
releasing the GIL and never blocking. QQ is in the default order and a donor
for two of the blends, so it ran on every cold track. It is table-driven now:
273ms a pass down to 33ms, the envelope 1.64s to 0.20s, and
`tests/test_qrc.py` keeps the bit-by-bit original beside it.

**`sys.setswitchinterval` is measured and refused**, so it is not chased
again. 900 frames with four threads parsing:

    5ms (today)  median  1.99ms  p99 206.33  worst 464.72  dropped  66/900
    1ms          median  4.63ms  p99  60.39  worst 113.61  dropped 263/900
    0.2ms        median  7.92ms  p99  32.83  worst  52.50  dropped 133/900

It trims the catastrophic tail and makes the median four times worse. That is
a trade, not a fix.

**The glow is exonerated**, and this is the second time -- the cache was
already priced at 0.4ms and dropped, and the renderers were then measured
cold, 1800 frames each, after a track change empties everything:

    flow 1.62ms median / worst 42.38 (frame one, the cold layout)
    amll 1.82 / 7.58   snap 1.59 / 8.14   cards 4.63 / 11.46
    glow pixmaps built across all 1800 frames: 53 for flow, 6 for amll

Only one frame in any of them went over budget and it was layout, not light.

**Three more reported after all of the above, and all three measured.** The
window was being timed by its lyric column alone; `tests/test_paint.py` times
`flow.paint`, and the background, the visualiser, the art panel and the
overlays are outside it. Driving the real window offscreen through
`--fixture` and timing `_paint_window` put the median at 3.2ms rather than
1.2ms and found all three:

  * **frame drops on a line change** -- the ration's escape hatch for a line
    with no picture at any blur had no bound. See `line_pixmap`.
  * **a little lag a bit after a song starts** -- `reset_track` puts `scroll`
    back to 0, so the column springs the whole way down to wherever the song
    has got to, building a picture for every line it passes. See the scroll
    spring in `tick`.
  * **the right source replaced by a worse one for a second** -- `_load`
    stands a stored document in front of the walk but tells the walk it holds
    nothing. See `_interim`.

Together, over 45s of full-window painting: worst frame 19.4ms to 15.8ms and
**frames over budget 2-4 down to 0**.

## A big stall at the first line, the first time a song is played

**Reported:** a long lag right at the first line, and only the first time a
track is visited -- named on a switch from "No Excuses" to "CAREFUL". Never on
a second visit, which was the whole clue: `_cached` makes a repeat visit skip
the walk, so what was left was the cold walk.

**Measured, on the real cold path,** by attaching to the running player,
forgetting the cache for the track that was up, asking for it again, and
watching a 16ms PreciseTimer while every slot on the window was timed.
Playback was never touched.

                              median    p99    worst   ticks a frame late
    before                     0.04ms   70.8   1419.8        90
    after                      0.03ms    6.4    202.3        17

**The window was never doing it.** Everything it ran on the GUI thread through
that window came to nothing: `on_lyrics` 94ms across 12 calls, then 64ms, 25ms,
3ms. The 1.4 seconds was the GUI thread not being allowed to RUN --
`_paint_window`'s own worst frame was 293ms, which is a paint being held off
the interpreter rather than a paint doing work. It is 24ms now.

**What held it,** timed on the walk threads through one cold fetch:

    difflib.get_opcodes   3292 calls   3761ms   worst  925ms
      ...all of it _shorter  12 calls   2046ms   worst  389ms on 3216x3293
    _qrc / _qrc_des                      ~930ms
    cached_body / unzwsp_body            ~440ms

**Two ways to make `_shorter` itself cheaper, both tried, both reverted,
neither to be tried again.** Both were exact on paper and both changed real
answers -- checked over 522 cuts of 58 documents:

  * **A line-level ceiling first.** A line the two documents spell identically
    is matched at line level, so the longest unmatched run of donor letters
    that leaves ought to be a ceiling on what the letter pass can find. It is
    not. `SequenceMatcher` is greedy, not optimal: at letter granularity it can
    fail to match lines the line pass matched and report a LONGER gap. Six
    documents here have a cut where the ceiling sits below the real answer.
  * **Trimming the identical head and tail**, which no gap can span. 100-174x
    where a section really is missing, and it still moved answers, for the
    same reason.

The lesson, and the reason `aligner/offload.py` exists at all: `_shorter`'s
answer is not a property of the two documents, it is a property of what
difflib's recursion happens to match. Anything that changes what it is handed
changes what it says.

**So the work moved processes rather than getting cheaper.** `_shorter` and
`_qrc` run the same code on the same interpreter in a worker, so nothing they
decide can come out differently -- `tests/test_offload.py` holds a pooled
answer against a local one over 406 cuts of 58 documents and both blobs of the
decrypt. What crosses the pipe is small on purpose: `_shorter` reads only its
two documents' letters, so `_short_of` takes the letters and the documents
stay put, about 6KB against megabytes. A round trip is 0.6ms on 154ms of work.

Three things about it that were found by running it and are worth not
rediscovering:

  * **fork, not forkserver or spawn.** The other two rebuild a worker by
    re-running the parent's main module, which here is lyrics_gui. A worker
    asked to do that never finished importing it.
  * **The pool is opt-in.** Only `warm()` builds one, and only `main()` calls
    `warm()`. Under a method that re-runs the main module, a program without a
    `__main__` guard would start a second copy of itself; every entry point
    here has one, but the test scripts do not, and now neither needs to care.
  * **`warm()` starts a worker rather than leaving it to the first submit**,
    or the fork lands on the first blend of the first track, which is the
    moment being cleared.

None of it is required: no pool, a pool that will not build, a worker that
raises, or `MILD_LYRICS_NO_POOL` all fall back to doing the work here.

**Still open, in the 17 ticks that are left:** `on_lyrics` at 47ms worst,
`say_alignment_outranked` at 34ms and `measure_offset` at 20ms are now the
largest things the window does to itself, and `duet_flags` (59ms) and
`cached_body` (25ms) are the largest left on the walk threads. All an order
of magnitude below what was there, and none of them measured further.


## Lag in the lyrics on Windows, continued

**Still open:** whether any of this is still felt on Windows. Everything above
was measured on Linux, and the numbers that moved most -- the QRC decrypt, the
blocking resync -- move further on a slower machine, not less.

**It was still felt**, reported again on 2026-09-18 with "only on some PCs"
attached, and that turned out not to be about cost at all -- see *Why the
lyrics are less smooth on Windows than on Linux*, which measured it and found
`time.monotonic`, which on Windows under CPython 3.12 and earlier moves in
15.625ms steps. It was the clock under the frame pump, under the position the
fill is drawn at, and under the timestep every spring in the column is
integrated with. None of the costs in this entry could ever have explained
"some PCs": they are the same on every machine, and the Python and the
monitor are not. What is below is still worth doing and was never the reason
the platforms differed.

**Also open, and now the biggest single cost in a frame: `scene_layer`
rebuilds 13 times a second.** Its docstring says "composited at 15fps and
blitted at the frame rate", and that is exactly what it does -- but the cap is
the only thing holding it, because the freshness test fires on the CLOCK
whenever `bg_motion` is on, whatever the key says. Measured over 30s of
full-window painting, 1811 frames:

    scene_layer rebuilds   398   median 3.63ms   worst 9.36ms

So roughly every fourth frame carries an extra 3.6ms, and that is most of the
difference between the lyric column's median (~1.3ms) and the whole window's
(~3.0ms).

What makes it worth looking at rather than accepting is the rate the drift
actually moves: `t = now * 0.06 * bg_motion`, so between two rebuilds 1/15s
apart `t` advances by 0.004, which for most `bg_mode`/`mesh_style` settings is
well under a pixel. A large share of those 398 rebuilds are painting the same
picture again.

Two ways, and they are not the same:

  * **Quantise the drift into the key.** No visual change at all -- the
    rebuild is skipped only where it would have produced the same pixels. It
    needs the step that corresponds to a pixel of movement, which has to come
    out of `_paint_mesh` and `_art_src` rather than be guessed at.
  * **Lower the cap.** One number, and it trades against how smoothly the
    background drifts, so it is the user's call and not a free win.

Not done here because the first needs measuring per bg_mode and the second is
a matter of taste, not a bug.


## Nothing on Windows works that needs the Windows bindings

**Reported:** the song panel has no Output row and no Player row, and a song
playing in Firefox is not followed even though Windows itself draws a card for
it on the volume flyout.

**Known, and it is one cause with three faces.** All three of those go through
`winsdk` / `winrt`, and none of them says so when it is not there:

  * `SmtcTransport.usable` returns False, so `make_transport` falls back to
    `CdpTransport` -- the Spotify debug port, which is the only door that does
    not need the bindings and the only one that cannot see a browser. That is
    the whole of "YouTube Music is not picked up". Windows has the session;
    we have no way to ask for it.
  * `windows_output` returns `("", "")`, so `self.device` is empty, so
    `info_rows` leaves the **Output** row out -- and `offset_key` has no device
    to key by, which quietly puts every output back on one shared offset.
  * the **Player** row is `if self.any_player`, which is a separate thing and
    is covered below.

Every one of those paths ends in `except Exception: return ""` or in a
`usable()` that answers False, which is right -- a missing optional binding is
not a crash -- but it means the window looks like it has decided these things
do not apply here rather than like it could not ask.

**Why it is probably not installed, even on a machine where it once was.**
`winsdk`'s last release is 1.0.0b10 and its newest wheel is **cp312**. Python
3.13 and 3.14 get no wheel, so pip falls back to the sdist, which wants a C++
toolchain and normally just fails. `doctor.py` said `pip install winsdk` in as
many words, so the fix it printed could not work on a current Python. The
maintained package is `winrt-*`, at 3.2.1, with wheels for cp39 through cp314
-- and the code has read both since it was written, `winsdk` first and `winrt`
second, at all five call sites. Only the advice was stale.

**Done here:**

  * `doctor.py` names the `winrt-*` packages, prints the Python it is running
    under and says why winsdk is not the answer on it. `winrt_module` replaces
    the four hand-written try/except ImportError pairs, so the check asks the
    question the same way round the window does.
  * a new `check_windows_output` asks for the default render device and prints
    its name. `Windows.Media.Devices` and `Windows.Devices.Enumeration` are a
    different pair of namespaces from `Windows.Media.Control` and installable
    without them, and the symptom of having one and not the other was a row
    that is simply absent.

**What would settle it:** `python aligner\doctor.py --no-shortcut` on the
machine. It now prints a line per namespace and, if the transport answers, a
line per open session, so "Windows sees it and we do not" becomes a line
saying which of the two is true.

**Still open, and it is the one that needs the user rather than the code.**
The **Player** row appears only with **Any media player** on (Player section
of the menu), and so does following a browser at all: `read()` with
`any_player` off calls `_read_one(want_volume, self.HOME)`, which asks for
Spotify. There is a fallback -- `_session` answers
`get_current_session()` when Spotify is not there and `any_player` is off --
so a browser CAN be read that way, but nothing hands over to it mid-song and
nothing vets it. If the bindings turn out to be installed after all, this
setting is the next thing to check, and the honest question is whether the
window should say so: "no player here but Spotify" and "not looking at
anything but Spotify" read identically from the outside.

**One thing that is not the cause, so it is not chased again.** `AUMID_NAMES`
maps five Firefox AUMID hashes to the name "firefox", and Firefox's AUMID is a
hash of its install path -- so a Firefox installed anywhere unusual is not in
that list. It does not matter. `_key` falls through to the generic path and
hands back the hash itself, which is non-empty and stable, which is all
`_live` and `_clocks` want. The session is still listed and still followed;
the only cost is that the Player row and the per-player offset are keyed by a
hex blob instead of by a word.


## Fetching from Genius in the editor, on Windows

**Reported 2026-09-18:** "From Genius" in the TTML editor does not work on a
Windows machine. Not reproduced -- the same path run here finds Clocks, gets
19 hits and reads 33 lines off the embed page -- and there is no Windows
branch anywhere in it: `editor/start.fetch_genius` to `sources.genius_hits` to
`local_align._genius_hits` to `genius_roman._get` is one `urllib` call on
every platform. So it is the machine, not the code, and the question was which
part of the machine.

**Which could not be asked, because every layer answered empty.**
`GR.lyrics_for` caught and returned `""`, `_genius_hits` caught per attempt and
returned `[]`, `sources.genius_doc` caught and returned `None`, and
`fetch_genius` turned all of it into one sentence: *Genius has nothing for
that*. A token Genius refused, a proxy in front of the request, an antivirus
intercepting TLS and a song nobody has written down yet were one message.
`lyric_sources._genius` said as much in its own docstring -- "a Genius outage
and a song Genius has not got arrive looking exactly alike" -- and left it
there.

**Now they are told apart.** `GR.why` turns an exception into a sentence, with
401, 403 and 429 spelled out because each says something different and only one
of them is about the song; `_genius_hits.last_error` is set only when NO query
got through, so one flaky request is still swallowed; `genius_doc.last_error`
carries it to the chain, which files it against `genius` the way it files
every other source. The editor raises where Genius could not be ASKED and
answers empty where it was asked and knows nothing, so the status line now
reads *could not ask Genius -- [SSL: CERTIFICATE_VERIFY_FAILED]...* or *Genius
has nothing for that*, and those are different sentences. `tests/test_gdoor.py`
pins both halves.

**Still open: what the Windows machine actually says.** To find out, on that
machine:

    python aligner\doctor.py --source genius --song "Clocks" --artist Coldplay

It walks the three doors in order -- the token out of the settings file, the
search on `api.genius.com`, the words on `genius.com/songs/<id>/embed` -- and
names the one that fails. The two hosts are asked separately on purpose: the
embed page needs no token and is a different name, so an interception can shut
one with the other standing.

**What to expect, in the order they are worth suspecting.** A token typed into
the player on one machine is not on the other -- the settings live in
`%APPDATA%\mild-lyrics\gui.json` there and `~/.config/mild-lyrics/gui.json`
here, and nothing syncs them; that shows as *none in ...* or as HTTP 401.
Then TLS interception, which is the usual Windows answer and the one QQ Music
was first blamed for. Then a proxy, which `urllib` reads out of the registry
whether or not anything else on that machine honours it. The editor writes
nothing to a console there -- pythonw has none -- so the other place to look
is `%LOCALAPPDATA%\mild-lyrics\ttml-editor.log.txt`.


## The renderer "dying" on Windows

**Reported, then corrected.** It was first reported as the renderer dying --
stopping altogether. Asked again, what it does is **lag far more**, not stop.
That is the entry below, and this one is kept only for what it fixed, which
stands on its own and would be needed again the moment something really does
stop.

**Windows had nowhere to print a traceback, and now it has one.** The
launchers are `.pyw` files, Windows binds those to `pythonw.exe`, and pythonw
leaves `sys.stdout` and `sys.stderr` as **None**. Printing to None is not an
error -- CPython returns silently rather than raising -- so
`install_excepthook`, whose whole job is to keep a bad frame from taking the
window down and to print the one traceback that says where the trouble
started, folded every one of them into nothing. `hide_own_console` is the
second way in: double-click the `.py` instead and it hides the console we own,
which puts the traceback on a window nobody can read.

`log_to_file` is what they go to now:
`%LOCALAPPDATA%\mild-lyrics\<launcher>.log.txt`, one previous run kept beside
it, descriptors moved as well as the Python objects so Qt's own warnings --
written from C++, never through `sys.stderr` -- land in the same file in the
same order.

**Still worth having because the two faults look identical from outside.** A
window that is up, responsive and not drawing is what `tick()` raising every
frame looks like: `_frame` runs it in a `try/finally` and re-arms in the
`finally`, so a fault every frame loses every frame and never stops the pump.
So does a paint fault, which half-draws the window rather than crashing. If
either ever happens, the log now says which.


## Why the lyrics are less smooth on Windows than on Linux

**Reported:** not as smooth as on Linux, and only on some PCs. Reported
separately as the renderer dying, which on being asked again is the same
thing -- it lags far more, it does not stop.

**FOUND AND FIXED, AND IT WAS OURS, NOT WINDOWS'.** Everything in this program
that asks how much time has passed asked `time.monotonic()`. Under CPython
**3.12 and earlier on Windows, `time.monotonic` is `GetTickCount64`, which
moves in steps of 15.625ms** -- so every elapsed-time reading was rounded down
to the nearest sixteenth of a second, on a clock read sixty times a second to
decide where a word has been sung to and how far a spring has travelled.

CPython **3.13 moved `monotonic` onto QueryPerformanceCounter**. That is the
whole of "only on some PCs": the same build, on the same hardware, with the
same settings, judders under 3.12 and does not under 3.13.

**Measured on the machine, 976 frames, Python 3.12.10, at a 20.000ms frame
period -- the probe's own before and after:**

                        median     p95     p99   worst   over 1.5x
    --clock monotonic   19.935  30.714  32.215  35.050      6.2%
    --clock perf        20.030  21.112  21.296  21.850      0.0%

    where the frames landed, on monotonic:  a smear, 6ms to 34ms
    where the frames landed, on perf:       19ms 23.5% / 20ms 51.9% / 21ms 23.9%

    monotonic     steps of 15.625000ms
    perf_counter  steps of  0.000100ms

A 28ms-wide spread became a 4ms-wide one and the late frames went to none.
The residual 19/20/21 is `QTimer::start` taking whole milliseconds against a
20.000ms period, which is sub-frame and is what the deadline carry is for.

**Three things read that clock every frame and all three reach the eye**, so
the fix is all three, not just the pump:

  * **`_frame`** asks how much of the period is left. Against a 15.6ms grain
    it asked the timer for the wrong number in a fresh direction every frame.
    The timer was always faithful -- the machine's own table says asked 17 ->
    17, asked 22 -> 22 -- which is what proved the fault was on our side.
  * **`Clock.position`** carries the song forward from the last reading, so
    the fill sweeping through a word advanced in 15.6ms lurches.
  * **`Amll._step`** takes the difference between two readings as the timestep
    it integrates every spring in the column with.

**How bad the third one gets depends on the FRAME rate, which is not the
refresh rate.** `retune_frames` runs at an integer divisor of the panel, so
`eff_hz` is never above `fps_cap` whatever the panel does -- and at the
default cap of 60 that puts the period at 16.7ms or longer, always longer than
the 15.625ms grain, with a screen slower than the cap only making it longer
still. While it is longer the step merely alternates; once it is
shorter, consecutive frames read the same tick and the step is **zero**, a
frame the column does not move on at all. Over 2000 frames of `Amll._step`
against a 15.625ms clock, by the rate the frames are actually DRAWN at:

        50 fps   0.0% of frames a zero step     step 15.6-31.2ms
        60 fps   0.0%                           step 15.6-31.2ms
        75 fps  14.7%                           step  0.0-15.6ms
       120 fps  46.7%                           step  0.0-15.6ms
       144 fps  55.6%                           step  0.0-15.6ms
       240 fps  73.3%                           step  0.0-15.6ms

On `perf_counter` every one of those is a flat step at the period. **The
divisor was quietly keeping the default cap out of the bottom four rows.** It
takes `--fps-cap` above 64 to reach them, and somebody who had raised it to
match a fast panel was in them -- at 144fps more than half the frames drawn
with the springs exactly where the last frame left them. Everybody on the
default was in the top two rows, where the step alternates and never stops.

**Done:** `mono()` in `lyrics_gui.py` and in `renderers.py`, used for every
elapsed-time reading in both. `perf_counter` is QueryPerformanceCounter on
Windows and the same `clock_gettime(CLOCK_MONOTONIC)` that `monotonic` already
is everywhere else, so nothing off Windows changes.

**Why all of it and not the three that showed.** The danger in a half-done
change is mixing two clocks in one subtraction, and `Clock.position`
differences `now` against a stamp the transports wrote -- not the same lines
of code. One clock everywhere cannot be mixed. Checked before it was done:
nothing here is serialised, sent over the link or saved, so no reading
outlives the process that took it, and the editor and the player each keep
their own.

**It reproduces on demand.** `tools_frame_probe.py --clock coarse` drops
`perf_counter` onto the same 15.625ms grid, so the fault can be seen on a
machine with no Windows on it. At a 33.333ms period here it takes p95 from
34.120ms to 44.151 and worst from 35.125 to 47.496.

**Three suspects measured and dropped. None is chased again.**

  * **arming the timer.** 6-10us on Windows against 3us here, on a 20ms
    frame. The `timeSetEvent` / `timeKillEvent` pair is real and it is 0.04%
    of a frame.
  * **the full-window repaint and blit.** 0.83-0.88ms median on Windows
    against 0.64ms here for the same paint. Not nothing, and not this.
  * **the scheduler tick, and `timeBeginPeriod`.** This entry claimed it and a
    `FineTick` class was written and shipped for it before the evidence was
    in. `--period 1` on the machine moved nothing: 6.7% of frames over 1.5x
    with it, 6.6% and 7.4% without. It is reverted. The reasoning was sound as
    far as it went -- `timeBeginPeriod` really is per-process since Windows 10
    2004, and `NtQueryTimerResolution` really does report the machine's tick
    and not the process's -- but it was built on a single probe run that has
    never reproduced, showing a clean 16/32 grid and 25.2% late where every
    run since shows the smear above and a faithful timer. What was different
    about that run is not known and is written down as not known.

**The lesson worth keeping, because it cost two passes.** The first probe
printed the system tick and not the clock the deadline was measured against,
and the wrong line was read as exonerating the right suspect. It prints both
clocks' resolution now, which is the line that would have ended this on the
first run.

**The 50Hz in the first runs was not a panel and not a misreport.** It was
read here as the monitor's rate and it is the DIVIDED one: the probe printed
`target 50.000Hz` and `retune_frames` gets that from a 100Hz panel over a
divisor of 2, at the default 60fps cap. Confirmed against the other machine in
this report, whose main output runs at 239.51Hz and is driven at 59.88 over a
divisor of 4 -- which had been read as "it says 60Hz but it is not 60Hz". The
probe prints the screen rate, the divisor and the target on separate lines
now, because two people read that one number as the panel.


## The GPU sits at 0%

**Reported:** nothing on the GPU while Mild Lyrics runs.

**Known:** expected, and not fixable where it stands. Every renderer here is
QPainter over a QWidget, and in Qt 6 QPainter is a CPU raster engine -- the
OpenGL paint engine that used to back it was removed in the Qt 5 series and
has no successor for widgets. What the GPU does do is composite the finished
window, which is the desktop compositor's work and does not show up against
this process.

Moving the drawing onto the GPU means not drawing it with QPainter: a
QQuickWindow with the scene graph, or a QRhiWidget with the shapes written as
shaders. That is a rewrite of `renderers.py` and of every painting method on
LyricsView, not a setting. Worth doing only if the CPU cost is what is
actually hurting, which the measurements above say it is not -- the median
frame is under 4ms.


## Word ENDS in the vocal view

**Reported:** where words start and end is not obvious from the picture,
only where lines start and end.

**Half done.** Word STARTS have a trace now -- see the flux commit, which
has the numbers. Word ENDS do not, and the reason is worth writing down
rather than trying again: there is nothing to draw. A line's end is visible
because the vocal stops, and a word's end inside a phrase is not a stop --
the singer runs one word into the next and the spectrum simply changes.
Half-wave rectification threw the falling edge away on purpose back in
`vocal.onsets`, and putting it back gets a signal that fires on every vowel
transition inside a word as readily as between two.

**The boundary head was the candidate, and it is now MEASURED and refused.**
The model has a word-end channel of its own (`M.emit(..., return_boundary=True)`,
channel 1, used by `autotime`), trained on where words divide rather than on
where energy moves -- which is the actual question. Measured before drawing
anything, the way the flux was: `syncnet-w2v-linemix` over `Coldplay - Clocks`,
which is gc's own hand timing and is in that checkpoint's `gold_held`, so the
head has never seen its answers. 204 words.

The trap in the obvious measurement is that on a hand-timed document a word's
end INSIDE a phrase is the next word's start -- the same instant, written
twice. Against all 204 ends, channel 1 scores a 0.037s spread against 0.100s
chance and looks like a result; channel 0 -- the START channel -- scores
0.035s against 0.105s on that same list of ENDS, because both channels fire
on word divisions and every division is on both lists. What separates them is the marks where the two events happen
at different times: a PURE START (a word start with no end within 150 ms, the
singer coming in) and a PURE END (a word end with no start after it, the
singer stopping). 56 of each.

    P(channel reads higher here than at a word's middle)

      channel 0 at a pure start      0.837     <- the trace already drawn
      channel 0 at a pure end        0.480     correctly ignores them
      channel 1 at a pure START      0.770
      channel 1 at a pure end        0.658

The end channel is better at finding STARTS than ends. It has largely learned
to be a second copy of channel 0, which is what an 80 ms-sigma target on a
document with no holes in it teaches. What is left over for ends is real --
0.658 is not a coin toss, and the level does rise at a stop, 0.398 against
0.290 in the middle of a held word -- and it is about a quarter of the rise
channel 0 gets, which is not enough to read a mark off.

At matched peak density (~0.85 peaks a second, the density the start trace is
drawn at) the share of hand-placed marks with a peak near them:

      tolerance             60ms  100ms  150ms  200ms  300ms
      ch0 at pure starts    0.68   0.75   0.75   0.79   0.80
      ch1 at pure starts    0.46   0.50   0.55   0.57   0.59
      ch1 at pure ends      0.12   0.20   0.32   0.39   0.41

Not a localisation failure that a wider tolerance rescues: at 300 ms, which is
already too loose to place anything with, it still finds two ends in five.
Drawing that puts a mark a second on the picture that is right two times in
five and, where it is right, right to a third of a second.

So: nothing to draw, from this direction too, and for a reason worth keeping
-- the head cannot learn ends from documents in which ends are not separately
observed. Only 22 of Clocks' 171 mid-phrase words have a hole after them at
all. A head that is to know an end from a start wants a target that tells them
apart; this one was given two channels and one event. `sync/data.py:_bounds`
is where that would change, and it is a retrain, not a setting.


## What is wrong with a bad QQ sync

**Reported:** "You Ain't Ready" (Skillet) is good, "For the Glory" (All Good
Things) is bad, "Omen" (Cartoon, Jéda, Time To Talk, Asena) has sudden ends
for no reason, "By Design" (WRLD) has inaccurate word timings. What
differentiates them?

**Two defects, and they are separable.** Profiling the six named songs, plus
19 more taken at random from ./lyrics:

    song                 syllables   meets end-to-end   held over 1s
    You Ain't Ready            349          91%             2.9%
    Omen                       277          75%             2.5%
    By Design                  103         100%             7.8%
    Light Up                   307          35%             8.8%
    Gold                       193          97%            13.0%
    For the Glory              266          81%            19.5%

The first column is the HOLES: a word ending before the next one starts, in
the middle of a phrase. That is the "sudden ends", and it is now closed --
see `close_holes`.

The second is the other one and it is not fixed. A syllable held over a
second is usually a line's LAST word stretched to the line's own end: "For
the Glory" writes `royalty[32.82-35.03]`, 2.2 seconds for one word in a line
whose median syllable is 0.3, with the next line starting at 35.29. That is
what "bad sync" looks like on that song -- every line crawls to a stop.

**Why it is not fixed here, and the candidate rule is now REFUTED.** A held
note is real, and there is nothing in the document that tells the two apart:
a ballad's last word genuinely does ring for two seconds.

The candidate rule was a ratio -- a last syllable more than some multiple of
its own line's median, on a line the next line follows closely -- and this
entry said it wanted checking against songs where the hold is genuine before
it was let near anything. It has been checked, against the 54 hand-timed
word-synced documents in this folder, every hold in which was placed by ear
by somebody listening. 3007 lines with a last syllable to judge:

        k       fires on a hand-timed line
      2.0        788  (26.2%)
      3.0        336  (11.2%)
      4.0        178  ( 5.9%)
      6.0         45  ( 1.5%)
      8.0         18  ( 0.6%)

Every one of those is the rule proposing to shorten a note somebody meant.
And it is not firing on the marginal cases -- it is firing hardest on the
most famous sustains in the collection:

    end         held 7.38s, line median 0.55s   Linkin Park - In the End
    o           held 7.33s, line median 0.56s   Linkin Park - In the End
    rime        held 10.18s, line median 0.29s  GIMS - J'me tire
    go          held 2.90s, line median 0.10s   Hellberg - The Girl

There is no k that separates them. At 8.0 the rule still shortens 18
hand-placed holds, and by then it has stopped describing "every line crawls
to a stop" at all. A ratio inside one document cannot do this, and that is
now measured rather than suspected: what a stretched last word and a sustain
have in common is everything the document records about them.

**So the fix has to come from outside the document.** The blend already has
an opinion -- "Where the base says the singing stops, believe it" -- and the
raw QQ path does not, which is where to look. A second source's line sync, or
the audio, can say the voice stopped; the syllable lengths cannot.

One caveat on the control, kept because this entry has been caught by it
before: a hand-timed file made on top of a QQ document inherits its stretch,
and there are known cases (see the offsets table above, where two songs came
back at exactly +0.000). That would make the table above flatter than the
truth, not steeper -- it cannot manufacture the Linkin Park sustains, which
are real notes on a song anyone can check by ear.


## QQ's clock is late, and not by a constant

**Reported:** QQ's delay looks negative -- the words arrive after the voice
-- while NetEase usually has it right.

**Both halves confirmed.** 34 songs with a hand-timed file in ./lyrics, every
word matched by text and in order, against both sources. The number is the
median of (the source's word start - the hand-placed one), so positive means
the source is LATE:

                  songs   median   within 50ms   spread
    NetEase          16   -0.008s     10/16       0.131
    QQ Music         17   +0.069s      4/17       0.191

    QQ minus NetEase, paired on the 13 songs both answered:  +0.142s

So QQ is about a seventh of a second later than NetEase on the same song, and
NetEase needs no correction at all. Two songs were dropped from NetEase's
column first -- Gold and TRIALS came back at exactly +0.000 with zero
scatter, which means the hand-timed file was made on top of that very
document and is not independent evidence. Dropping them barely moves it.

**A constant does not fix it, and this is the useful half.** Shifting every
QQ stamp by S and asking how far out each song then is:

        S     median |err|   within 50ms   songs made WORSE
     +0.00       0.127          4/17              0
     -0.04       0.112          4/17              7
     -0.10       0.104          4/17              8
     -0.14       0.129          4/17              9
     -0.25       0.181          1/17             11

The best shift buys 23ms of median error and makes eight songs of seventeen
worse, and it does not move the within-50ms count at all. QQ's lateness is a
property of each DOCUMENT, not of QQ: the spread between songs (0.191) swamps
it. The same table run over NetEase is the control and behaves exactly as it
should -- a source that is already right gets worse at every shift, 12 of 18
songs within 50ms falling to 1.

**So nothing was changed.** The running order already ranks NetEase above
Kugou above QQ, and `blend_rank` already puts a NetEase-timed blend ahead of
a QQ-timed one, which is what this measurement asks for. A blanket shift
would also invalidate every QQ track already corrected by hand -- there are
153 such corrections on this machine, centred on -0.005s.

**What would actually fix it** is a per-document correction at play time,
which needs something to measure against. Where NetEase answered there is
nothing to fix, because NetEase's clock is the one being used. Where QQ is
the only word-timed source, the candidates are `estimate_offset` against
Spotify's own analysis -- which already exists and feeds `auto_offset` -- and
the local aligner.

"Whether the automatic offset is already absorbing this on QQ-only songs" was
the next thing to measure here, and half of it now has an answer: it was
absorbing nothing, on any song. `auto_offset` used to take a calibration off
the reading, and that calibration gated it -- fewer than five hand-tuned
tracks that ALSO carried a reading and every track got 0.0 whatever had been
measured. This machine has 172 hand offsets and an empty `est_raw`, so the
intersection is empty and always was. The measurement was taken, shown in the
menu, and never applied to anything.

The calibration is gone (see the note where `calibrate()` was), so the
reading is applied as it stands and the question can actually be asked now.
It wants asking the same way as the table above: the applied offset against a
hand-timed file, on songs where QQ is the only word-timed source.

**Half of it is now used rather than corrected.** "A property of each
DOCUMENT, not of QQ" is exactly the thing `in_order` reads: where a blend has
two donors it measures each one's shift against the base's line sync and
gives the song to whichever needs no correction, instead of trying to correct
either. That is not the calibration this section is asking for -- it cannot
help a song with only one word-timed source, which is where the lateness
actually bites -- but it does mean the three-way no longer hands a whole song
to a document that is out by a second when the other donor is not. Measured
over 354 songs in eval_blends' jar: 32 change, 15 better, 6 worse.


## A reading is only checked for a uri

**Not reproduced, and written down rather than fixed.** `CdpTransport.read`
guards on one field:

    if not isinstance(got, dict) or not got.get("uri"):
        raise RuntimeError("no player state")

Every other field is `or ""` / `or 0.0`. So an item carrying a uri and nothing
else would be accepted, would name the same track -- reset_track never fires --
and would overwrite `clock.meta` with blanks. The art panel is four separate
truthiness tests on four of its fields, so all four would stop drawing at once
and the window would lose its whole left side with the lyric column still
scrolling.

That is exactly what was seen once, and it was NOT this: it was a TypeError out
of paintEvent losing everything drawn after the lyrics. Nothing has ever been
observed handing back a skeletal item. Keeping the last meta that said
something was written and then taken out again for that reason -- it is a
change to the clock justified by a fault that turned out to be somewhere else,
and the clock is not the place to carry a guess.

**The log this asked for is in, and nothing else is changed.** `CdpTransport
.read` now counts the readings that carry a uri and no title, printing the
first three and then every hundredth -- the same shape as the excepthook's
throttle, and a dict lookup on a reading already being parsed. The clock is
untouched: keeping the last meta that said something was written once and
taken out again, and it is still a change justified by a fault that turned
out to be somewhere else.

So what settles it is a session with track changes, ads and a Connect
handover in it. If `[player state with a uri and no title: ...]` never
appears, there is nothing here and this entry can go. If it does, it names
the case, and the fix is four lines of the shape above.


## Words sung across each other, in the amll column

**Reported:** still wrong, after four passes at it. The example is
"Falling In Reverse - NO FEAR", line 86, at about 3:27 -- an ad-lib of three
short interjections. The complaint is that the line "re-renders, redoes the
sync".

**Three faults found and measured, all of them real and none of them it.**
Listed so that the next attempt does not spend itself here again:

  * `fill_pen` asked the row for its NEAREST light. Where two voices share a
    row the nearest light moves, so a word the first voice had finished
    would take the second voice's gradient and go back to half unlit. Fixed;
    a word part way through is lit from its own clock now.
  * a word the voice had NOT reached was drawn solid, for lying to the left
    of a light that belonged to the other voice. Measured over four real
    lines that have words sung across each other: 679 frames of 680. Now 0.
  * the rise ran backwards. That line's third fragment starts 65ms before
    its second, and `word_lifts` had dropped the two rules `rise_plan` and
    `frag_lifts` use to keep the wave in reading order. 36 frames of 111
    had a word standing higher than the word before it; now 0, matching the
    stack.

**The measurement this entry asked for has been run, and the fill is
cleared.** Row 86 of that document is "Ha, ha; woo", a background row whose
lead is 85, "Step up, motherfucker, let's go" -- and its stamps really are out
of order, `woo` at 207.560 against `ha;` at 207.625. Rendered alone,
offscreen, at 60fps across 207.2s..208.3s:

  * no word's lit fraction ever DECREASED: 0 of 201 word-frames;
  * no word was lit, went dark and lit again: 0 times;
  * neither row ever travelled backwards: 0 of 67 frames each.

So it is not the fill, and it is not the reading order either. Both were
fixed above and both stay fixed under measurement.

**What the same pass did find**, which is the next suspect and now has a
number on it. The ad-lib and its lead are two lines in the plan 66.5px apart,
and on screen they are **0.00px apart when the ad-lib begins and 62.19px
apart when it ends**. They ride separate springs, and the ad-lib spends the
whole of being sung sliding down away from the line above it into a place it
only reaches as the words finish. The fill is running across a row that is
still moving into position underneath it.

That is a candidate for "re-renders, redoes the sync" that fits the words
better than anything measured so far: nothing re-runs, but the row does not
hold still while it is being sung.

**What is not settled is whether that is wrong**, and it is a judgement rather
than a measurement. The stagger is deliberate -- Spring takes a target for
LATER precisely so a column can open out rather than snap -- and a stagger
tuned for a line is being applied to an interjection a third the length. The
decision is whether an ad-lib should be given a shorter delay than a line, or
be placed relative to its lead instead of springing to its own slot. Neither
should be changed on a hunch; what this needs is the person who saw it looking
at the column with that 0-to-62px in mind and saying which of the two it is.

The same row is already the fixture for the reading-order check in
`tests/test_renderers.py`, which asserts up front that its stamps really are
out of order, so it will not quietly stop testing anything.

**One thing this is NOT**, checked so it is not checked again. The word rise
now breaks a run at a hyphen -- a stutter or a spell-out is several
utterances, not one word going up as a slab -- and this line is not one of
those. Line 86 is "Ha, ha; woo": three space-separated words with no hyphen
anywhere, so the grouping that changed cannot reach it. The out-of-order
stamp the third bullet above is about is still exactly there, `woo` at
207.560 against `ha;` at 207.625.


## The amll glow over a break inside a word

**Reported:** the glow is wrong where a word has a small break in it -- a gap
in the timing, with no space in the text.

**Measured, and what is wrong is the length the word is credited with.**
`words_of` groups the fragments of one written word back together, which is
right and is argued at length in its own note; `span_of` then dates that word
as `min(start) .. max(end)`. Where the fragments abut -- which is nearly
always -- that is the note. Where they do not, the silence in the middle is
counted as part of it, and everything downstream is told the word was held
for longer than it was sung.

Across the 55 documents in this folder: 23433 words, 1356 of them cut into
several pieces, 17 of those with a real gap inside. Median 96ms, largest
1.14s. A small population, but not a small error on it:

  * two of the 17 pass `emphasized` ONLY because of the silence. `EMP_MIN` is
    1.0s, and "ver|koop" is voiced 0.84s and dated 1.52s, "Andr|é" 0.63s
    against 1.20s. Both are words the gate is meant to turn down;
  * both then light at nearly full strength. `held` is `(e - s - 0.18) / 1.1`,
    so verkoop is lit at 1.00 where the voice earns 0.60 and André at 0.93
    against 0.41;
  * and the light stays on across the break. `emph_of` runs every character's
    envelope to `ends = (e - s) + SETTLE`, so a character before the gap goes
    on glowing through the silence and out the other side.

**The first two are done.** `Renderer.voiced_of` adds the fragments' own
lengths up, and `emph_of` takes a word's length from that rather than from
its span: the gate, the amount of movement and the brightness all now ask how
long the word was SUNG. Checked over the same documents through the real
layout path -- 1356 split words, and the number is identical to `e - s` on
1333 of them, so the change is confined to the 23 that have a hole. Three
words have their emphasis turned off by it, and two of them are the two this
entry named: verkoop (0.84s voiced against 1.52s dated) and André (0.63s
against 1.20s).

The third is "her"+"like", which is one of the four join cases at the bottom
of this entry rather than one of the 17 -- a word the document has glued to
the next one with the space lost. Turning it down is right on the numbers
(0.37s voiced, dated 1.85s) but it is a document fault being covered rather
than fixed, and it stays in that list.

`Amll.word_lifts` still dates a word through `span_of`, so the RISE carries
the old stretch where the glow no longer does. That was written here as
something both should do together; on the measurement they are 21 words, and
splitting them is what let the glow change be checked as a no-op on 1333.
Whether the rise should follow is the same question as the third bullet and
belongs with it.

The third bullet is a different fix and should be taken separately, because
shortening an envelope is not the same as putting a hole in one. Decide what
is wanted first: a word that lights once across the break, or one that goes
out and comes back with the voice. "Small break" covers both the 115ms median,
where a hole would read as a flicker, and the 1.48s case, where the light
sitting on a silent word is presumably the complaint. Watskeburt is where to
look -- four of them are in it and they are the big ones, "Cen|traal" twice at
8.12s and 4.68s dated against 6.98s and 4.02s sung.

`emph_of` still runs every character's envelope to `ends = (e - s) + SETTLE`,
deliberately, and where a word ENDS has not moved. That is the one thing
`voiced_of` is documented not to be used for.

**Four cases that are NOT this**, found while counting and worth their own
look: "this"+"pride" and "her"+"like" in `takihasdied, femtanyl - SH3 L00K3D
D3DD`, and `myself, "`+`I` and `trash? "`+`No"` in the two NF files. These
reach `words_of` looking like a mid-word split but they are two whole words
with the space lost -- the line really does read "thispride" on screen, in
`ln["text"]`, before any renderer sees it. That is `word_ends` finding no
separator on either side of the join, and it is a document or a parse
question, not a glow one.


## Japanese romanisation

**Reported:** Japanese romanisation is wrong, "and providers".

**Two faults, both measured, and only one of them is a bug in this code.
The first is fixed; the second cannot be fixed with pykakasi at all.**

The first was the grammatical particles. は, へ and を are read `wa`, `e` and
`o` when they are particles and `ha`, `he` and `wo` otherwise, and pykakasi
gives the spelling every time. `spicy_lyrics.PARTICLES` knows this, but the
correction is applied in one place only -- the last loop of `line_readings`,
which tests each PIECE against the table -- so it fires exactly when the
lyric happens to time the particle as a syllable of its own and not
otherwise. Over the 16 Japanese documents in `bench/` and `lyrics/`: 143
particle characters, 46 of them alone in their own syllable and 97 sitting
inside a bigger piece. Sixty-eight per cent of them are wrong today, and a
line-timed Japanese lyric gets none of them right. What it looks like:

    心中を綴るには困る   ->  shinjuu o tsuzuru niha komaru
    杞憂では済まなそうな  ->  kiyuu deha suma nasouna

`o` correct because を was timed alone, `niha` and `deha` wrong because には
and では were not.

The second is the readings themselves, and it is pykakasi being a dictionary
with no grammar behind it: 君 comes back `kun` rather than `kimi`, 宣って as
`notamatsu te` rather than `notamatte`. Worse, the whole-line context that
`line_readings` introduced on purpose -- and that is right, it is what gets
明日 as `ashita` and 二人 as `futari` -- is also what lets 今日は be read as
the greeting こんにちは: 今日 alone gives `kyou`, and 今日は晴れ gives
`konnichihahare`. No particle table can reach that one; the segmenter has
already swallowed the particle into the word.

**The first is fixed.** The table is applied where the reading is CUT rather
than after it: `spicy_lyrics.particle_rom` takes a segment and its reading,
and `line_readings` calls it on each segment before dividing the reading out
among the syllables. A segment is a much better place to ask than a syllable
is, because the segmenter has already decided where the words are. Counted
over the same 143 particle characters:

     76  are a segment of their own          を, は
     44  are the last character of theirs    には -> niha, では -> deha
     23  are buried inside one               はない, あなたはかわいい

The rule is "a lone particle segment, or a trailing は/へ/を on an all-kana
one", and it reaches 120 where the syllable rule reached 46. Run over the
documents and printed one by one, every one of the 44 trailing corrections is
a real particle -- には, では, ては, それは, だけは, のは, とは, あなたを,
きみを, ぐらを -- and there are no false positives to report: no all-kana word
merely ENDING in は was caught. The two examples this entry was written
against now read `shinjuu o tsuzuru ni wa komaru` and `kiyuu de wa suma
nasouna`.

The 23 buried ones are left alone on purpose, and all-kana is the guard that
does it. They are the second fault wearing the first one's clothes -- はない
is genuinely "wa nai" and only grammar says so.

`reading()`, the single-string path, applied the table nowhere at all and now
walks the same segments. That was the one-liner and it was the two paths
quietly disagreeing about the same sentence.

For the second: pykakasi has no morphological analyser and cannot be made to
have one. `cutlet` over `fugashi`/MeCab does, gets the particles right by
construction, and is the same shape of optional dependency pykakasi already
is (see `_kakasi`, `can_read` and the `doctor.py` check that reports it).
Adding it as a preferred reader with pykakasi as the fallback is the honest
fix and is a bigger job than the first; the 16 documents above are the
fixture either way, and `tests/test_readings.py` is where the checks go.

**"And providers" is not pinned down and needs one sentence from whoever
saw it.** It reads two ways and they have different answers. If it means the
ROMANISERS: pypinyin is not installed on this machine, so `can_read` refuses
Chinese here and a Chinese lyric is left in its own script -- which is the
designed behaviour and may be what was seen. If it means the LYRIC SOURCES:
`roman_of` prefers a provider's own `TransliteratedText` and only derives a
reading where that one `failed`, so a provider shipping bad romaji beats a
correct derived reading and nothing says so; NetEase's is a separate
`romalrc` grafted onto lines by nearest timestamp within 0.35s, which is
line-level and cannot fill in sync under a word-timed lyric. Both are real
shapes. Neither should be touched until it is known which one was meant.


## Crediting a Genius lyric

**Asked for:** a Genius document should credit the contributors who
transcribed the song. **Answered differently, because the transcribers
cannot be had** -- the embed carries a contributor COUNT and no names, and
no reachable endpoint turns that count into people.

**What Genius does name is who VOUCHED for the lyric**, which is a smaller
set and a stronger claim, and all three can be true of one song at once:

  * `lyrics_marked_complete_by` -- somebody said the words are finished;
  * `lyrics_marked_staff_approved_by` -- Genius staff agreed;
  * `verified_lyrics_by` -- a list, usually the artist, with
    `human_readable_role_for_display` wording the role.

`lyrics_state` == "complete" and `pending_lyrics_edits_count` sit in the
search result and were printed at first, on the grounds that they cost
nothing. **They are not printed any more, on the grounds that a state is not
a credit** -- it names nobody, nobody's word is behind it, and under the last
line of a song it read as though Genius itself had signed off on the words.
The line is a list of people or it is absent.

**Done.** `genius_roman.credit_of` composes the line and `song_of` fetches
the record it reads -- one extra request per document, because the people are
only on the full record, and it is allowed to fail. A document with all three
reads:

    Marked complete by gc · Staff approved by louiedro · Verified by Eminem

`login` and `name` differ on an artist account (eminem against Eminem) and
the display name is the one printed.

**The decision this entry said to take first was taken as it said.** The
credit rides in `_words_by`, its own field, which `made_by` prints and
`LS.credited` does not read -- so `judge_sync` cannot enrol anybody in a
roster about timing they had no part in. `from_genius.untimed` is True and
the sync is measured here off the audio; marking a lyric complete is a
statement about the WORDS. Both halves are pinned in `tests/test_people.py`:
the credit reaches the line under the lyrics, and `LS.credited` of that same
document is empty.

**What is not settled**, and only shows on a real fetch: whether these fields
are on the `/songs/<id>` response for songs nobody has verified, and how
often a song has none of them and the line is simply absent. Neither changes
the shape -- an absent credit is the state every Genius document was in
before this -- but the first run against a token is worth watching for it.

The other fields on a search hit that were noted while doing this and are not
used yet: `apple_music_id` and `apple_music_player_url`, and a `media` list
carrying YouTube, Spotify (`native_uri`, a `spotify:track:` id) and SoundCloud
links. The Spotify id is the interesting one -- it is a second opinion on
WHICH RECORDING a Genius page is about, which is the question `_same_cut` is
answering by title text today.


## Move the commentary out of the code and into /docs

**Done once, and it did not stay done.** This entry used to say the work had
not been started. It had: `8afab08`, 2026-08-23, lifted 4453 lines of comment
out of `aligner/` and `editor/` into the 1319 entries under `docs/notes/`, and
the lift HELD -- of 649 quoted lines sampled back against the modules they came
from, one is in the code again. Nothing crept back.

**What happened instead is that the code went on being written.** 5778 comment
lines have been added to `aligner/` and `editor/` since that commit, which is
more than the lift took out, and there are 6185 there now. The split is clean
and it says what the problem actually is:

    module                        note holds    comment lines now
    aligner/lyrics_gui.py            530             2147
    aligner/lyric_sources.py         145             1520
    aligner/renderers.py               -              980
    editor/app.py                     29              238
    ...
    aligner/run_pipeline.py           35                1
    aligner/align_song.py              8                1
    aligner/build_dataset.py          10                1

Every module at 1 is one nothing has been edited since August. Every module
far above its note is one that has been worked on. `renderers.py` has no note
at all because it did not exist at the lift -- it was split out of
`lyrics_gui.py` on 2026-09-09 (`c92c856`), and its thousand lines of prose have
never been anywhere else.

So the mechanism works and was never the thing in doubt. What does not exist
is anything that keeps it up: a lift is a one-off against a codebase that
writes prose faster than it was taken out, and a second wholesale pass would
be in the same position by November.

**What moving it would cost, which is unchanged and is the argument against
simply running it again.** These comments are load-bearing where they sit:
they are read by whoever is editing the line below them, which is exactly
when they are needed and exactly the moment a reader will not go looking in
another directory. A note that has drifted from the code it describes is
worse than no note -- and the notes ARE drifting now, because `README.md`
anchors each entry to a line number and says so. So this is not a
cut-and-paste job, and the last one is the evidence: what belongs in /docs is
the argument, and what belongs by the code is the consequence and a pointer
to it.

**Where to start.** `renderers.py` is the densest and the best test of whether
it works at all, and it is also the one module with nothing written down yet.
Take one argument that is already self-contained -- the rise schedule, say,
which is the RISE_LEAD note, the `word_lifts` docstring and the amll column's
own `FLOAT_MIN` note all making the same case with different numbers -- write
it once in `docs/notes/aligner/renderers.md`, and leave each of the three
sites with the finding and a reference. If the code reads worse afterwards,
the answer is no and this entry can go.

**And the second question, which the numbers above make the more useful one:**
whether a note can be kept honest at all without somebody deciding to. The
line-number anchors are already stale; `README.md` calls them "the ones the
code had when the comments were lifted" and leans on the enclosing name and
the quoted line instead. Whether that is enough to re-find an entry
mechanically has not been tested, and it is what decides whether /docs can
hold reasoning for a codebase that is still moving.


## A word boundary lands inside one of our words

**Reported as part of something else and left standing.** Slushii's "LUV U
NEED U" through Kugou, the line the re-stream floor was lowered for: Apple's
"And watch these moments fall back into place" against Kugou's "And though
she's moving slow back into place". The line fills now, and one boundary
inside the mishearing is in the wrong place. It comes out

    And | watch | these | moment | s | fall | back | into | place

with "fall" on an onset nobody measured. The cause is exact and is in
`_recut`: SequenceMatcher reads the 's' that ends "moments" as the 's' that
begins "slow", so Kugou's word boundary is pinned INSIDE one of ours. The
`breaks` rule exists to stop precisely this and never gets the chance,
because it only moves a cut that falls in a stretch the two sides disagree
about, and a one-letter agreement is not one.

**The fix was written, measured and refused, which is why this is an entry
and not a commit.** Folding matching runs shorter than three letters into the
disagreement around them fixes this line outright -- eight words, eight
stamps, nothing guessed -- and the shape of the evidence is good: over the
5,492 lines the jar's blends re-cut, a one-letter run sits inside a word of
ours 35.3% of the time and a two-letter run 16.1%, against 1.6% for three
letters and up. 18.4% of all runs are one or two letters long.

It costs Koven's "Gold" the onset of "enough". There QQ hears "in love" for
Apple's "enough", and the ONE-letter agreement between the 'e' of "enough"
and the 'e' of "love" is the only thing splitting our word in the right
place. Folded, `breaks` snaps the cut to the far side instead, "never"
swallows half a second and "enough" starts 0.46s late. Over the jar as a
whole the fold is a wash -- same lines timed, median and p90 within a
thousandth -- so it is a real regression bought with nothing.

**Where to start.** The two cases differ in what the short run is doing, not
in how long it is: in Gold it is the only evidence there is about where our
word divides, and in LUV there is a word boundary of ours three letters away
that the aligner had no reason to prefer. A rule that reads "fold a short run
when our own word boundary is within a letter or two of it" would take LUV
and leave Gold, and has not been written or measured. `tests/test_blends.py`
pins both outcomes as they stand, so a change that fixes one and breaks the
other says so immediately.

## The blend on "TELL ME WHAT I DID" - Tiffany Day

**Reported:** the blend is wrong on this one. Blocked on evidence: that is
the whole of what is known. No symptom has been written down yet -- whether
the words are wrong, the timing is, a source is being passed over, or the
result is worse than one of its donors on its own -- and the document is not
in the jar, so nothing here can be reproduced or scored.

**Where to start, and the first step is not optional here.** The jar on this
machine is EMPTY -- `~/.cache/mild-lyrics/eval-jar` does not exist, and
`./eval_blends.py` run as it stands answers "0 songs with a reference" and
stops. The thousand files in `bench/` are a different tool's output and are
not it. So nothing about any blend can be scored here until somebody runs the
fetch, which is the one step that goes to the network.

**And the reason `fetch` itself does nothing is worth writing down, because
it is not the network.** `songs()` reads the track list out of
`~/.cache/mild-lyrics/tracks.json`, which does not exist on this machine
either, so the fetch is handed an empty list and writes an empty jar. The
titles and lengths it wants are all sitting in `./lyrics` already -- the
filenames are "ARTIST - TITLE" and the last line of each TTML gives the
length -- and QQ, Kugou and NetEase are all found by those three fields and
not by a Spotify id at all. Filling the jar from the references rather than
from tracks.json fetched all three donors for 109 songs in about half an
hour, and that jar is what the numbers in the _recut entry above were
measured over. Only the `apple` and `spicy` slots really need an id, and a
blend can be scored without them by taking the reference's own line stamps as
the base, which is what a line-synced Apple document is.

`eval_blends.py` is built for exactly this question and answers it without the
network once the jar is filled:

    ./eval_blends.py fetch          # the only step that goes out
    ./eval_blends.py --json now.json

That scores every blend over the same donor documents however often the code
changes, so a difference in the output is a difference in the code rather
than in what a server felt like answering. `bench/` already holds a thousand
files for the songs that are in it; another artist's track is there
(`Tiffany Day - SAME LA`), which is worth a look first in case whatever this
is shows up there too and is already measurable.

The second thing to get is the symptom in one sentence, from whoever saw it.
Which of the four questions eval_blends asks is the one going wrong --
onsets, the words, the splits, or the choice of donor -- decides where to
look, and guessing between them is what the last few days of the amll column
were spent on.


## The offset fixture nobody has

**Blocked on evidence, and the evidence is a network job.** `test_offset.py`
checks that the gates on the measured offset are set where a hundred real
tracks want them: for each one, the estimate against the offset that track was
corrected to by hand. Thirteen checks above it are arithmetic over made-up
readings and need nothing; this last one needs the measurements, and the file
they were in belonged to the session that made it.

It now looks in `tests/data/scored.json` or at `$MILD_LYRICS_SCORED`, and
SKIPS rather than dying when neither is there -- a fixture nobody has is a
check that cannot run, not a failure. One row per track: `tid`, the `delta`
and `conf` and `n` and `rev` that `est_raw` stores, and `hand`.

**Why it cannot simply be rebuilt.** The settings file has **177** hand
offsets -- it was 172 when this was written, so the corpus is still growing --
and an EMPTY `est_raw`, so there is still no track on this machine with both
halves recorded. Getting them means running the estimator against Spotify's
analysis over the corrected tracks, which is a hundred and seventy-odd
requests on somebody's own account, through a player that has to be running
and signed in. It is worth doing deliberately, not as a side effect of
running a test, and not by anything acting on its own.

Checked while looking: `gui.json` carries a `genius_token` and no Spotify
credential of any kind, so nothing here can reach the analysis without the
app being up. The one thing that WOULD make this cheap is recording the
reading as it is taken -- `auto_time` is on, so every track played with a
clear estimate could write its `est_raw` row as it goes, and the fixture
would assemble itself over a few weeks of ordinary listening rather than in
one burst of requests. That is a smaller change than the fixture is worth.

That same empty `est_raw` is what made the calibration a dead letter, and the
check has changed shape with it: there is no bias between the reading and the
offset any more, so what it asks is whether the reading ALONE lands near what
a track was tuned to by ear. Which is a harder question and the right one.


## Apple Music, off a browser, when the upload is long

**Reported** as "it also fails to fetch Apple Music/NetEase lyrics pretty
often", and narrowed by the person who saw it to a browser, Firefox
specifically. Two causes were measured. The first is fixed and is in the
commit log; this is the half that is left.

**Not the providers.** Ten songs from ./lyrics put to both on 2026-09-17,
read-only: nine of ten answered on each, Apple in 0.4s and NetEase in 2.1s.

**What Firefox gives them.** Its own MPRIS publishes the WINDOW title and no
`xesam:artist` at all -- see BRIDGE_PLAYERS -- and `song_from_video` recovers
one only where the upload is named "Artist - Title". "The Taste | YouTube
Music" has no dash and the artist stays empty. The length it gives is the
UPLOAD's, which is the release plus whatever was welded on either end.

**The fixed half, for the record:** `from_bini` refused the whole lookup
without an artist, the name query and the ISRC door together, though
`apple_isrcs` finds the recording by title and duration and needs no artist.
Six of seven songs answered with an artist and none of seven without, with the
codes found every time. See the commit; the guard is now "a title, and either
an artist or a length", and `tests/test_trouble.py` pins which door each shape
of caller reaches.

**The half that is left is the LENGTH, and it is a cliff rather than a
slope.** Every Apple door is gated on the duration at NEAR, which is 6.0s:
BiniLyrics is handed `duration=` on the name query, and `apple_isrcs` keeps
only the hits inside `_near`. So both shut together. The record's own duration
off Apple's catalogue, then the same lookup with that number moved:

    song                              record    +0   +2   +4  +5.5   +7  +10  +20
    Coldplay - Clocks                  307.9  syll syll syll  syll    —    —    —
    Bruno Mars - That's What I Like    206.7  syll syll syll  syll    —    —    —
    Baby Keem - HONEST                 172.7  syll syll syll  syll    —    —    —
    Linkin Park - In the End           216.3  syll line line  line    —    —    —
    Radiohead - Creep                  238.6  syll syll syll  syll    —    —    —
    NF - Time                          240.4  line line line  line    —    —    —

Two things in that table. Past NEAR there is no degraded answer, there is NO
answer -- and asking with no length at all answers nine times in ten, so a
wrong length is strictly worse than no length. And inside the tolerance it
still costs: In the End is word-synced at the record's own length and
line-synced two seconds off it.

**Why the usual repair does not reach this case.** `card_len` and
`better_question` exist for exactly the upload-is-longer problem, and they
work by getting the record's duration off the card. But the CARD is gated too:
`_apple_card` calls a match `sure` on an artist in common OR a duration within
NEAR, and a Firefox track has neither -- no artist, and an upload more than
six seconds long. So nothing is dressed, `card_len` is never written, and the
walk goes out with the upload's length and no artist for the rest of the song.
An upload inside six seconds is fine and most are: `fetch_meta` cites 200.4s
released against 206 uploaded, which just clears it. A lyric video with a long
intro does not.

**The obvious fix is refused on the evidence there is.** Letting `apple_isrcs`
fall back to its `loose` rows when nothing is near, or retrying without the
length, would turn these misses into hits and would also throw away the only
thing separating two recordings. Measured with neither an artist nor a length,
matching on the title alone: "Time" comes back as Pink Floyd's 425.9s rather
than NF's 240.4s, and "The Taste" as The Used's. That is the failure NEAR and
`_same_artist` are both written around ("Apple has Clocks at 306.9s and Clocks
(Live) at 285.0s, and only one of them is the recording anybody is playing").

**Where to start**, and it is a different question from the one this entry has
been asking. The upload's length is not evidence about the record and is being
used as though it were. What IS evidence is the title -- a YouTube name
carries the artist often enough that `song_from_video` is built on it -- so
the candidate to measure is asking the catalogue with the title and NO
duration, and then checking the answer against the upload's length with a much
wider slack than NEAR: wide enough to admit an upload with an intro, narrow
enough to refuse Pink Floyd. The five songs above give the shape of what a
right answer looks like; what nobody has measured is how many of Apple's
title-only answers survive a slack of, say, thirty seconds, and that is one
probe against the corpus in ./lyrics. Do that before touching NEAR itself,
which is load-bearing for every source here and not only for Apple.

All of this is network and none of it has a fixture. The probes were six to
ten names, `LS.apple_card` for the record's duration, and `LS.from_bini`.


## The live link, and whether the stall was the only thing wrong with it

**Reported:** syncing a whole song with "Show in Mild Lyrics" on, the link
seems to cut somewhere around the middle. Three symptoms together: new lines
stop appearing on the player, the words stop sweeping, and the timing stops
matching what was stamped. Seen on SABAI - Scared, 2026-09-17, timed against
the fetched local copy rather than against Spotify.

**A cause was found and fixed** -- see `_follow_to` and its note in
docs/notes/aligner/lyrics_gui.md -- but it has NOT been confirmed against the
symptom on the machine that saw it, which is the only reason this is here
rather than in the commit log alone. The seek that walks Spotify along was
rationed and was given up on where the player would not take it; unbounded,
it was an unbounded stall on the GUI thread, which is the one thread that
draws the words, reads the editor's socket and announces the state.

**Four things it is NOT.** Each was measured against the running pair, so
none of them needs chasing again.

  * *not the socket.* With the player 50 minutes up and the editor
    mid-session, `ss` showed the pair `ESTAB` with both queues at zero, and
    the player's journal held exactly two socket teardowns all session -- one
    when the editor was closed, one from the probe that went looking.
  * *not the document.* Asked for what it was drawing, the player handed back
    36 lines running 00:07.9 to 02:45.5, 16299 bytes against the 16300 on
    disk. Nothing was truncated and nothing was lost.
  * *not the push stream under load.* The real `LyricsView` offscreen on a
    spare port against the real editor `Link`, document growing to 120 lines
    and 55 KB at the editor's own 180ms rate: 120 sent, 120 landed, no write
    failures, no refusals, worst gap between state rows 0.16s against a 1.2s
    staleness limit. With `follow` added at 120ms: 970 sent, 970 landed.
  * *not the editor's cost per push.* `timed_only` plus `to_ttml` on that
    document is 1.15ms, and 5.03ms on one four times its length.

**What was measured about the bus, and what was not.** A read round trip to
Spotify on this machine is 0.14ms median and 0.45ms worst, over 60 samples
each of Position, Metadata and CanSeek -- so the reads were never the stall.
The three that WRITE (SetPosition, SetVolume, PlayPause) could not be timed
without driving somebody's playback, and they are what the fix rations.

**How to confirm it, in one sync.** `tools_link_watch.py` connects as a
second read-only client and calls out a stall as it happens:

    python3 tools_link_watch.py --log /tmp/link.jsonl

It works because the player promises a state row every SAY_EVERY (0.5s) off
a 50ms timer on that same GUI thread, so a gap in that stream is the only
measurement from outside of the event loop stopping. It also calls out
`live` going false, the track changing underneath, and `base` or the
per-track offset moving -- the three other shapes the report could have had.
Run it through a sync. No stall lines means this was the whole of it; a
stall line with the seeking rationed means it was not, and the timestamp
says what to look at next.


## Loose ends

- `_paint_dots` reads `ln["end"] - ln["start"]` and raises on a dots block
  with no times on it. The DIVISION is safe -- the span is
  `max(1e-6, end - start)`, so a zero-length marker is drawn rather than
  dividing by nothing -- and what is left is the read itself: a missing key
  or a None on either side, which is a KeyError or a TypeError before the
  guard is reached. Not reachable today: `prepare` refuses to insert
  interlude markers into a document with no timings at all, so every marker
  that exists has real ones. Written down because a paint fault here is
  silent -- it half-draws the window rather than crashing -- so if a path
  ever does hand one over, what it looks like is the window losing everything
  below the column and nothing saying why.
- `tests/test_blends.full.py` fails on this branch and is not a regression.
  It calls `LS._same_clock`, which exists on `blends-full` (`c6f6b50`) and has
  never been an ancestor of this branch; here the same question is `in_order`.
  `tests/` is gitignored, so a test file does not change with the branch and
  this one has been sitting in the tree since 2026-09-07 while
  `test_blends.py` -- 123 checks against 74, and passing -- superseded it.
  Delete it or keep it for that branch, but it is the only red in the suite
  and it says nothing about this code.
- `_speed`'s window is clamped to the moment the spring was let go, which
  is the fix for the sub-millisecond step this entry used to describe. Worth
  keeping only for WHY the floor suggested here was not what was done:
  `_solve_spring` answers the TARGET for any t below zero rather than
  continuing the curve, so a centred difference reaching back past zero read
  the whole remaining distance as a millisecond's travel. Reproduced with a
  target that moves every frame -- at a 1ms step the value trails its target
  by 50, at 0.9ms it is -inf inside 3000 frames. A floor under `step` would
  have made the clock run fast, and would have left `_accel` -- which reads
  `_speed` one whole H further back -- reaching past zero anyway.
