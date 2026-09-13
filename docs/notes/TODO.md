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

**Still open here.** The cold layout burst is real but it is not a line-switch
cost -- it is paid when `layout_cache` is cleared, which is a better source
arriving mid-song or a resize, and the worst frame of a COLD sweep is still
about 37ms. Splitting the geometry from the times is one fix and it is a real
refactor; putting an LRU on `fm.horizontalAdvance` is the smaller one, since
the fragments are identical across a re-time and measurement is the whole cost
of a cold layout. `layout_cache` is also still an unbounded plain dict.

The rest of the "under load" half is untouched and untested: `autosave()` does
a JSON rewrite and a `Path.replace` from inside `tick()`, `LiveLink` walks
`findChildren(QObject)` at 20Hz on the paint thread, and the painter can wait
out a `sys.setswitchinterval` for the GIL while the ten-wide walk parses.

**Not yet explained:** the suspicion about Spicy Lyrics fetching in particular.
It would be GIL contention rather than paint cost -- the walk is ten providers
wide and parsing a document is pure Python, which competes with the painter for
the interpreter however fast the machine is. If it still stutters while a fetch
is in flight and not otherwise, that is where to look, and the fix is a smaller
`sys.setswitchinterval` or moving the parse off the walk threads, not anything
in the renderer.


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

What could work, and has not been tried: the boundary head the sync model
already has (`M.emit(..., return_boundary=True)`, used by `autotime`). That
is trained on where words divide rather than on where energy moves, which is
the actual question. It would want the same measurement the flux got --
how far it rises at a hand-placed word end against how far it rises anywhere
-- before it is drawn.


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

**Why it is not fixed here.** A held note is real, and there is nothing in
the document that tells the two apart: a ballad's last word genuinely does
ring for two seconds. The candidate rule is a ratio -- a last syllable more
than some multiple of its own line's median, on a line the next line follows
closely -- and it wants checking against songs where the hold is genuine
before it is let near anything. The blend already has an opinion about this
("Where the base says the singing stops, believe it") and the raw QQ path
does not, which is the other place to look.


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

**What would actually fix it** is per-document calibration at play time,
which needs something to calibrate against. Where NetEase answered there is
nothing to fix, because NetEase's clock is the one being used. Where QQ is
the only word-timed source, the candidates are `estimate_offset` against
Spotify's own analysis -- which already exists and already feeds
`auto_offset` -- and the local aligner. Whether the automatic offset is
already absorbing this on QQ-only songs has not been measured, and that is
the next thing to measure here.


## Matching a QQ line against Apple's when the words differ

**Reported:** "Was I never in love to have just everything you want ooh"
against "Was it never enough to have just everything you want? (Ooh)" should
pair "in love" with "e-nough" and take "Ooh" as an ad-lib. Koven's "Gold",
QQ Music against Apple Music.

**Not started.** This is the blend's word alignment: QQ mishears a lyric and
writes two words where Apple writes one syllabified into two, and the
matcher has to pair a run against a run rather than a word against a word.
The ad-lib half of it is `split_asides`' job and probably already works once
the pairing does.


## Loose ends

- `_paint_dots` sets `p.setPen(Qt.PenStyle.NoPen)` for the interlude dots and
  puts back only the BRUSH. The pen leaks into everything drawn after it in
  that frame. The art panel survives it by accident -- it sets its own pen
  before every draw -- but that is luck, not design, and the next thing to
  paint after a line of dots without setting one will draw nothing. Found
  while chasing the blank panel, which turned out to be something else.
- `aligner/&1` is a stray file from a mistyped shell redirect. It is not
  in the repo and nothing reads it; it can go.
- A provider that RAISES is passed over in the same silence as one that
  simply has nothing, which is how two functions sharing the name
  `_spoken_for` hid a crash in the Apple+QQ blend for as long as they did.
  Nothing was on screen to say the blend had been asked and had failed. The
  walk already collects faults for the "could not be reached" line; an
  exception out of a provider belongs there too.
- Four test files fail to import when run from the repository root --
  `test_aligner.py`, `test_anchor.py`, `test_syllables.py`, `test_voice.py`
  -- because they put `aligner/` on `sys.path` in a way that does not
  survive the working directory. `test_offset.py` fails on a fixture path
  under a scratch directory that no longer exists. None of these are
  regressions.
