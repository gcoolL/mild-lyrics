# `editor/waveform.py`

Comments lifted out of `editor/waveform.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 66** — before `LANES = 4`

> How many rows the lead voices and the backing voices each get before
> everything past the last one has to share it. Backing voices need more, not
> fewer: a song answers itself with two or three ad-libs at once far more
> readily than it sings two lead lines at once.


## `envelope`

**line 94** — before `fd, name = tempfile.mkstemp(prefix="mild-editor-peaks-", suffix=".wav")`

> A name of its own. A fixed one meant two editors decoding at the
> same time read each other's half-written file.


## `Wave.__init__`

**line 154** — before `self.vocal = None`

> The vocal view: a picture of the separated stem, the landmarks it
> offers, and whether either is on. All three are None until somebody
> asks -- separating a song is half a minute, and the strip has to be
> useful before then.

**line 161** — before `self.claimed = None`

> Which marks the document can account for, from `ops.claims`. Set by
> the window, because deciding it needs the document and this widget
> only draws. None means "not worked out": everything is drawn as
> though it were usable, which is what the strip did before there was
> a distinction to draw.


## `Wave`

**line 293** — before `OVERDRAW = 3`

> How many viewport-widths of audio the cached picture covers. Following
> the playhead scrolls the view every frame, so a picture drawn to fit
> the viewport exactly is stale the moment it exists; one drawn wider is
> blitted at an offset until the view walks off the end of it.


## `Wave._envelope`

**line 329** — before `at = self.view_at - (span - self.span) / 2.0`

> Centre the strip on the view, so scrolling either way has room.


## `Wave`

**line 363** — before `TOP, BOTTOM = 0.055, 0.385`

> The band the picture lives in: under the time labels, down to the rule
> the blocks hang off. The same room the envelope uses, so turning the
> vocal view on does not move a single syllable on screen.


## `Wave._paint_vocal`

**line 383** — before `gut = max(6.0, (y1 - y0) * 0.13)`

> A gutter under the picture for the ticks. They used to be stubs off
> the floor of the band, drawn over the low mel bands -- which are
> the loudest part of a vocal and so the brightest part of the
> picture, and a thin orange line over that is invisible. Given a
> strip of their own they are always readable, and the picture loses
> eight pixels it was not using for anything.

**line 394** — before `cx0, cx1 = max(0.0, sx0), min(float(img.width()), sx1)`

> Only the part of the song that exists; the rest stays background
> rather than being smeared out of the first or last column.


## `Wave._paint_flux`

**line 443** — before `tall = (y1 - y0) * 0.42`

> Hung from the TOP of the band, not stood on the floor of it. A sung
> vocal puts nearly all of its energy in the low mel bands, which are
> the bottom of this picture and the brightest part of it, so a thin
> line drawn there is competing with the loudest thing on screen. The
> top bands are almost empty; a trace hanging into that space is
> legible without anything having to be dimmed to make room for it.


## `Wave._paint_marks`

**line 511** — before `p.setPen(QPen(T.q(T.BACK, 150 if spoken else 60), 1))`

> An entrance earns a line up through the picture as well:
> it is the only mark founded on silence rather than on a
> jump in the spectrum, and it is usually the one somebody
> is actually looking for.


## `Wave._pack_rows`

**line 611** — before `lanes[k] = cap - 1`

> Everything past the cap shares the last lane. It is a
> floor, not a choice -- the strip scrolls instead, so
> the cap only bites on songs that would need more rows
> than a screen has pixels for.


## `Wave.mouseMoveEvent`

**line 832** — on `            self._grab = None`

> the document moved out from under it


---

## Lift — 2026-10-25

Docstrings shortened in `editor/waveform.py` on 2026-10-25. The full text of each is kept here under its function's name; the line numbers are that day's, after the shortening.

### module docstring

**line 1** — the module docstring

> The strip of audio the syllables are dragged around on.
>
> Two rows, because a line has two kinds of voice in it: the lead across the
> middle and any backing groups under it. Everything in view is drawn from the
> document, so a block is never a copy of a syllable that can fall out of step
> with the one being edited -- it IS the syllable, painted where its times say.
>
> The envelope behind them is a mono RMS at 100 Hz, which is enough to see a
> vocal attack and cheap enough to compute on a whole song at once. It is here
> to show WHERE the singing is, not to be traced.
>
> There is a second picture behind them now, off until it is asked for: the mel
> spectrogram of the DEMUCS VOCAL, from `vocalmap`. This module used to say a
> spectrogram was the wrong picture on principle, because hand-placed timings do not
> sit on the attack a spectrogram shows. That was measured on the MIXTURE, and
> on the mixture it is right -- the loudest attack in a bar is a snare. On the
> separated vocal it is not: 251 hand-placed word starts sit a consistent
> -0.028 s from the stem's flux attacks with a spread of 0.040 s, against
> 0.070 s on the mixture. So the vocal view is offered.
>
> What is NOT offered is snapping to it. That was built, measured and taken
> out: the same word sung again in the same song gets a mark in some repeats
> and not others, and where it does the offset moves by up to 130 ms. See
> `ops.consistency`. The picture is here to be READ -- by somebody who knows
> which of two adjacent syllables an attack belongs to, which no rule over
> unlabelled attacks does.

### `_levels`

**line 53** — from the docstring, `def _levels(path: str, hz: int):`

> (rms readings, frames, rate) of a file, read a couple of thousand
> readings at a time.
>
> The whole song used to be decoded in one go -- stereo, as float32 -- then
> averaged to mono and squared, so its peak was about three times the
> decoded size: 130MB for four minutes at 44.1kHz, 320MB for ten. A block
> at a time is a few megabytes whatever the length, and every reading is
> the same sum over the same samples, so the answer is the same to the bit.

### `_peaks`

**line 103** — from the docstring, `def _peaks(trace, lo, hi):`

> The largest reading in trace[lo[i]:hi[i]] for every i, 0 where that is
> empty.
>
> One reduceat over the ranges laid end to end -- start, stop, start, stop --
> keeping every other answer, because the ranges of neighbouring columns
> overlap when the view is zoomed in past one reading a pixel and a
> partition would not do. One extra element at the end lets a range stop
> at the last reading.

### `_corner`

**line 118** — from the docstring, `def _corner(r) -> tuple[float, float]:`

> The corner radius for a word's block, as (x, y).
>
> One radius for every block in the strip -- the same one the chips in the
> line list use, so a word is the same shape wherever it is drawn -- and
> never more than half the block, because a block is as wide as its word is
> long and a sixteenth-note "a" is a few pixels. Asking for a fixed radius
> on those is what made the corners look uneven: Qt quietly clamps it to
> what fits, so a long word came out square and a short one came out a
> pill, from the same number. Clamping it here means every block is as
> round as it can be up to one limit, which is what reads as even.

### `Wave.set_pos`

**line 202** — from the docstring, `def set_pos(self, t: float, playing: bool) -> None:`

> Move the playhead, and repaint if that moved anything.
>
> Called thirty times a second, paused or not, and a paused strip
> repainted every time -- the grid, the blocks, every lane -- to draw
> what was already there. Everything that changes the picture asks for
> its own repaint, but some of them only ever relied on this one, so a
> strip nothing has moved is still repainted every STILL_REPAINT
> seconds: late, at worst, and never wrong.

### `Wave._columns`

**line 281** — from the docstring, `def _columns(self, W: int, at: float | None = None,`

> One loudness per pixel column, cached until the view moves.
>
> The strip is repainted thirty times a second to move the playhead, and
> the picture behind it only changes when the view scrolls or zooms --
> so it is worked out once per view rather than once per frame. Taken as
> the LOUDEST reading inside each column, so zooming out cannot hide a
> short attack between two samples.

### `Wave._envelope`

**line 309** — from the docstring, `def _envelope(self, p, W: int, H: int) -> None:`

> The picture behind the blocks, drawn once per view and then blitted.
>
> It is one line per pixel column -- upwards of twelve hundred of them
> on a wide window -- and it was being redrawn on every one of thirty
> frames a second to move a playhead that does not touch it. The
> picture only changes when the view scrolls or zooms or the window
> resizes, so that is when it is drawn; the rest of the time this is a
> single blit, which is the difference between the strip keeping up and
> not.

### `Wave._paint_vocal`

**line 368** — from the docstring, `def _paint_vocal(self, p, W: int, H: int, at: float | None,`

> The separated vocal's spectrogram, and what it offers to snap to.
>
> Drawn straight out of the QImage `vocalmap` built once for the song --
> one column per 10 ms of audio, scaled to whatever the view is showing.
> Qt does the resampling, which at a two-minute zoom means columns are
> dropped; that is the right trade here, because the picture is being
> read for its shape rather than measured, and the landmark ticks on top
> of it are the thing that must not move.

### `Wave._paint_flux`

**line 400** — from the docstring, `def _paint_flux(self, p, W: int, at: float, span: float,`

> Energy arriving, drawn over the picture as a trace.
>
> The spectrogram is a picture of LOUDNESS and a word start is not
> loudness, it is a change in it -- which is why word starts are so much
> less obvious in it than line starts, where the vocal goes from nothing
> to something. `vocalmap.flux` is the same audio differenced and read
> against its own neighbourhood, and it stands three times above its
> background at a hand-placed word start where the picture manages 1.4.
>
> MAX over the columns a pixel covers, not their mean. A whole song in
> the strip is twenty columns to the pixel and an attack is one or two
> of them; averaging is how you make a trace that is smooth and says
> nothing. The peak is the whole point, so the peak is what is drawn.
>
> Over the mel rather than in a lane of its own: the two are the same
> moment in the same audio and reading them side by side means looking
> away from one to check the other. Kept faint, and only as high as a
> third of the band, so the picture underneath is still legible.

### `Wave._paint_marks`

**line 430** — from the docstring, `def _paint_marks(self, p, W: int, at: float, span: float,`

> Ticks where the vocal starts and stops something.
>
> Four distinctions, because the marks are not equally believable and
> the eye is the only thing here that can tell a `sane` from a `she`:
>
>   * an ENTRANCE -- the vocal arriving out of real silence -- gets a
>     full-height line. It is the only kind founded on silence rather
>     than on a jump in the spectrum.
>   * an attack the document can account for gets a solid stub.
>   * an attack that TWO syllables are both near, or that none is,
>     gets a dotted stub -- see `ops.claims`. Drawn apart so that a
>     mark sitting between `sane` and `she` looks like the ambiguity
>     it is rather than like evidence.
>   * a NOTE -- the pitch stepping rather than energy arriving -- gets
>     a short, dim stub. There are more of these than of anything else
>     and they are the least founded of the three kinds, so they are
>     drawn as the hint they are; on a chopped vocal they are also the
>     only marks there are, and then the row of them is the picture.

### `Wave._stamp`

**line 511** — from the docstring, `def _stamp(self):`

> Enough of the document to know when the packing is stale.
>
> The times and the shape, nothing else. Packing the whole song is not
> expensive once; it was expensive because it ran on every one of
> thirty frames a second, along with everything else this used to
> recompute per frame.

### `Wave._packing`

**line 521** — from the docstring, `def _packing(self) -> dict:`

> A lane for every voice: the lead, the duet and the backing in
> lanes of their own, and as many of each as it takes.
>
> Voices overlap -- a duet answers before the other singer stops, an
> ad-lib is sung over the words it answers, and one hand-timed file has
> twenty-five of them -- and there is no limit on how many can sound at
> once. So each kind is packed the way a calendar packs appointments,
> with no ceiling: a second backing vocal over the first gets a second
> backing lane, not a place on top of it. The lanes were capped at four
> before, and a fifth voice was drawn over the fourth.
>
> Packed over the WHOLE song rather than over what is in view: a lane
> worked out from the visible lines changes as you scroll, and a block
> that jumps to another row while you are reaching for it is worse than
> one drawn a little lower than it needs to be.

### `Wave._rows`

**line 640** — from the docstring, `def _rows(self, g) -> dict:`

> A row per syllable that is still sounding when the next begins.
>
> The same packing the lines get, one level down. Syllables inside a
> line overlap on purpose -- a word held over the ones after it, a
> rapped line whose breath carries through -- and drawn on one row the
> held word is buried under the words it rings over: it cannot be read,
> and its right edge cannot be grabbed to say how far it rings, because
> the chip on top of it answers the pointer first.

### `Wave._syl`

**line 746** — from the docstring, `def _syl(self, i: int, voice: int, k: int):`

> The syllable a grab names, or None if it is no longer there.
>
> A grab is held across mouse moves, and the document can change under
> it -- an undo, a line the model just retimed, a word deleted from
> another pane. Indexing doc.lines[i].groups()[v].syls[k] raw then
> raises inside a Qt slot, which takes the drag down with it and leaves
> the edit half applied.

---

## Earlier lift — 2026-08-23

Comments lifted out of `editor/waveform.py` on 2026-08-23, before the work that followed. They are not in the code any more, so they are kept here as they were; the line numbers are the ones that code had then.

### module level

**line 39** — on `EDGE = 4.0`

> px either side of a boundary that grabs it

**line 40** — before `ANCHOR = 0.35`

> Where "now" sits while the strip is following. Fixed, and the audio slides
> under it: a playhead that drifts across the window and then jumps back is
> two different motions to read, and the jump lands exactly when you are
> trying to place something.

**line 45** — before `LANES = 3`

> How many lines sounding at once the strip will draw side by side before it
> starts sharing the bottom lane.


### `Wave`

**line 91** — on `    follow_changed = pyqtSignal(bool)`

> the strip stopped following itself

**line 92** — on `    moved = pyqtSignal(int, int, int, float, float)`

> line, voice, syl, a, b

**line 93** — on `    picked = pyqtSignal(int, int, int)`

> line, voice, syl


### `Wave.__init__`

**line 104** — on `        self.view_at = 0.0`

> left edge, seconds

**line 105** — on `        self.span = 12.0`

> seconds across the widget

**line 109** — before `self.shown: list = []`

> (line, voice) pairs being worked on, drawn brighter. Pairs, because
> a backing voice is selected apart from the line it answers.

**line 112** — on `        self._drawn: list = []`

> (line, voice, syllable, rect) as painted

**line 115** — on `        self._grab = None`

> (line, voice, syl, which, grab-offset)


### `Wave.set_pos`

**line 137** — before `self.view_at = t - self.span * ANCHOR`

> Every frame, playing or not: the anchor is where "now" is, so a
> seek, a nudge and a tap all leave it in the same place.
>
> Except mid-drag. Scrolling the ground out from under a syllable
> somebody is holding is the one time a moving view is worse than
> a still one.


### `Wave.paintEvent`

**line 171** — before `for width, alpha in ((7.0, 26), (4.0, 46)):`

> A soft glow around it: at speed, a 1px line in a busy strip is
> genuinely hard to find, and this is the thing being watched.


### `Wave._grid`

**line 180** — before `step = 1.0 if self.span <= 20 else (5.0 if self.span <= 60 else 15.0)`

> A tick every second while the view is close in, every five or ten as
> it opens out -- the point is to be able to read a time off it, which
> a wall of unlabelled lines does not help with.

**line 185** — before `for a, b in ((self.view_at, 0.0),`

> Now that the view may run before the song starts and past its end,
> shade what is outside it. Without this the empty ground reads as a
> silent passage rather than as the edge of the recording.

**line 199** — before `if t >= 0 and (not self.length or t <= self.length):`

> No label outside the song: floor division made those read
> "-1:58" for a second and a half before zero.


### `Wave._columns`

**line 219** — before `step = self.span / max(W, 1)`

> Keyed on the view rounded to a PIXEL, not to a fraction of one:
> while following, view_at changes every frame, and a key finer than
> the thing being drawn would miss the cache on every one of them --
> and shimmer, because the columns would resample sub-pixel.

**line 235** — before `inside = (raw[:-1] >= 0) & (raw[:-1] < len(self.env))`

> Columns outside the song are empty, not a smear of its first or last
> sample -- which is what clipping alone would draw once the view is
> allowed to run past either end.

**line 242** — before `got = np.maximum.reduceat(self.env, starts[keep])`

> reduceat over the run each column covers: one pass over the
> envelope instead of a slice per pixel.

**line 245** — before `cols[keep] = got`

> reduceat runs each segment to the NEXT start, which is right
> everywhere the columns touch and too long only at the end.


### `Wave._envelope`

**line 253** — before `p.setPen(QPen(T.q(T.FAINT), 1))`

> An empty strip that says nothing looks broken. It is not: there
> is simply no sound here to draw yet.

**line 264** — before `grad = QLinearGradient(0.0, mid - amp, 0.0, mid + amp)`

> A gradient rather than a flat colour: the loud middle of the band is
> where the singing is, and the fade off it keeps the strip from
> competing with the syllables drawn below.


### `Wave._lanes`

**line 323** — before `lanes[i] = LANES - 1`

> More voices at once than there are lanes: share the
> last one rather than drawing off the bottom.


### `Wave._blocks`

**line 349** — before `self._drawn = []`

> Recorded as they are drawn, and hit-tested against the same list:
> the geometry cannot then disagree with itself.

**line 361** — before `if self.cursor is not None and 0 <= self.cursor[0] < len(self.doc.lines):`

> The untimed pieces belong to whatever is being worked on, not to
> every line at once -- forty loose rows would bury the strip.


### `Wave._group`

**line 385** — before `fill = T.q(T.CHIP if voice == 0 else T.BACK, 90)`

> Every line is drawn; the ones being worked on are the ones
> that stand out. Everything else is context.


### `Wave.mousePressEvent`

**line 466** — before `self.seeked.emit(max(0.0, self.t_of(x)))`

> Seeking does NOT stop following. It used to, and the checkbox was
> never told -- so one click in the strip left the box ticked, the
> view pinned, and no way back except toggling it twice. A click here
> asks to go somewhere; following is about what happens after.


### `Wave.wheelEvent`

**line 503** — before `if self.follow:`

> Scrolling the view sideways IS "let me look somewhere else", so
> it does stop following -- and says so, out loud, so the checkbox
> and the behaviour cannot disagree.
