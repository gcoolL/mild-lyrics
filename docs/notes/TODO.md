# Still to do

Reported and not yet fixed. Some of it is blocked on evidence -- a song
nobody has named, a question only the person who asked can answer -- and
some is work that is understood and simply has not been done. Each entry
says which, what is already measured, and where to start.

Fixed items are not listed. They are in the commit log, which says what the
measurement was.

Gone from this list since it was written: QQ Music on Windows, which was
never reproduced and now works; the two halves of the stutter that were the
drawn-line cache; and the 2GB, which was an animated cover with no ceiling
on how many frames it kept.


## NetEase is passed over for a worse source

**Reported:** NetEase has the better lyrics for a song and something else
gets used.

**Known:** nothing yet, because no song has been named. The pick is
`_walk`'s: `beats()` takes better timing over worse, and between two
documents of equal timing the user's own source order decides, with
`_fullest` stepping in where the better-ranked one is missing a section of
the song. Any of those three could be the one that is wrong here, and they
want different fixes -- an order that is being honoured correctly and simply
is not what was wanted is not a bug at all.

Worth ruling out first: this is not `_ne_rank` picking the wrong RELEASE.
That was checked -- ten songs, every candidate list, and the word-timed copy
came back each time -- and the report is about a different source winning,
not about NetEase answering badly.

**Needed:** one song where it happens. Both documents will already be on
disk under `~/.cache/mild-lyrics/sources/<track id>.json`, so a title is
enough to compare what NetEase said with what won and to see which of the
three rules made the choice.


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

**What is left, measured.** Clearing the caches the way a refresh does and
timing the frames after it: 16ms on the frame it lands and 40ms over the six
after. That remainder is the LAYOUT, and it is not the same kind of problem.
`Flow.paint` calls `layout_line` for every line in the song on every frame,
because it needs each line's height to know where the next one goes, so an
empty layout cache is the whole document re-wrapped on one frame.

The layout genuinely does carry the times -- `wrap_pieces` hands back rows of
(x, advance, text, start, end) -- so it cannot be kept across a re-timing the
way the pixmaps now are. What could be kept is the GEOMETRY: the x, the
advance and the text depend on nothing but the words, and only the last two
fields change when a song is re-timed. Splitting the cache in two along that
line would leave a refresh re-attaching times to rows it already has. It is a
real refactor -- the renderers all read those five-tuples -- and it is the
next thing to do here if the burst still shows.

**Not yet explained:** the lag when a line changes, and the suspicion about
Spicy Lyrics fetching in particular. The first should be small now (a line
change no longer re-rasterises anything that was on screen); the second
would be GIL contention rather than paint cost -- the walk is ten providers
wide and parsing a document is pure Python, which competes with the painter
for the interpreter however fast the machine is. If it still stutters while
a fetch is in flight and not otherwise, that is where to look, and the fix
is a smaller `sys.setswitchinterval` or moving the parse off the walk
threads, not anything in the renderer.


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


## Whether the measured resume hold should move the lyrics

**Reported:** "measured resume hold should affect lyrics delay".

**Not started, because it is not clear which way.** The measurement already
moves the words: `Clock._bias` is subtracted from the reported position on
every reading, so the lyrics ARE held back by what was measured. Two other
readings of the request are possible and they want opposite changes.

  * the measurement is clamped by the setting -- `min(self.unpause_delay,
    want)` -- so a leap larger than the Unpause delay is clipped and the
    words stay wrong by the difference. If that is it, the ceiling should
    come off or be raised.
  * or the measured hold should feed the Timing offset the user can see and
    tune, rather than living only in the clock where the info panel reports
    it.

Sync behaviour here is tuned by ear and by measurement over many sessions
(see the comments around `_resume_lead`), so this wants the question answered
before anything moves.


## A better picture in the vocal view

**Reported:** the spectrogram itself is not readable enough to time against.

**Known:** the picture is `vocalmap.VocalMap.image` -- a mel spectrogram of
the demucs vocal, one column per 10ms, windowed on the song's own 40th and
99.5th percentiles and gamma'd at 1.35 so the quiet detail stays down. The
strip zooms on the wheel (`Wave.zoom`) and that zoom is horizontal only.
There is no control over the contrast, no way to look at part of the
frequency range, and the picture is drawn from one fixed ramp.

**Needed:** which of these is actually in the way -- zoom, frequency range,
contrast, or scrubbing the playhead against it. They are four different
pieces of work and the fourth is the only one that is not just drawing.


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


## QQ's clock is a different distance out on every song

**Reported:** the QQ delay looks like -0.10s often, but it can be 0.00s or
-0.20s.

**Confirmed, and it is per document.** Ten songs with both a hand-timed file
in ./lyrics and a QQ answer, every word matched by text and in order, and the
median of (QQ's start - the hand-placed start):

    Dynasties and Dystopia   -0.113s   scatter 0.058s   449 words
    DYSTOPIA                 -0.039s           0.069s   335
    CAREFUL                  -0.010s           0.030s   639
    Move On                  +0.011s           0.037s    53
    Scared of the Dark       +0.044s           0.066s   440
    On & On                  +0.127s           0.143s   189
    Gold                     +0.152s           0.067s   161
    Go To War                +0.193s           0.094s   372
    SpongeBob SquarePants    +0.204s           0.119s    61
    Wishes                   +0.357s           0.127s   138

The scatter WITHIN a song is three to ten times smaller than the spread
BETWEEN songs, so each document is out by a near-constant amount and that
amount is a property of the document, not of QQ. A single global offset
cannot fix it and a per-track hand correction is what the user is already
doing by ear.

**What would fix it:** something to measure the constant against at play
time. Three candidates, in order of what they cost -- the local aligner,
which has the audio and is already run for other reasons; a blend's Apple
line stamps, which are independent evidence about where a line begins and are
already fetched; or the beat analysis. The second is nearly free where a
blend exists and is the one to try first.


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
