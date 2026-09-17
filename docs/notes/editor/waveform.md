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
