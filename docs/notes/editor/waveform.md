# `editor/waveform.py`

Comments lifted out of `editor/waveform.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

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


## `Wave`

**line 91** — on `    follow_changed = pyqtSignal(bool)`

> the strip stopped following itself

**line 92** — on `    moved = pyqtSignal(int, int, int, float, float)`

> line, voice, syl, a, b

**line 93** — on `    picked = pyqtSignal(int, int, int)`

> line, voice, syl


## `Wave.__init__`

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


## `Wave.set_pos`

**line 137** — before `self.view_at = t - self.span * ANCHOR`

> Every frame, playing or not: the anchor is where "now" is, so a
> seek, a nudge and a tap all leave it in the same place.
>
> Except mid-drag. Scrolling the ground out from under a syllable
> somebody is holding is the one time a moving view is worse than
> a still one.


## `Wave.paintEvent`

**line 171** — before `for width, alpha in ((7.0, 26), (4.0, 46)):`

> A soft glow around it: at speed, a 1px line in a busy strip is
> genuinely hard to find, and this is the thing being watched.


## `Wave._grid`

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


## `Wave._columns`

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


## `Wave._envelope`

**line 253** — before `p.setPen(QPen(T.q(T.FAINT), 1))`

> An empty strip that says nothing looks broken. It is not: there
> is simply no sound here to draw yet.

**line 264** — before `grad = QLinearGradient(0.0, mid - amp, 0.0, mid + amp)`

> A gradient rather than a flat colour: the loud middle of the band is
> where the singing is, and the fade off it keeps the strip from
> competing with the syllables drawn below.


## `Wave._lanes`

**line 323** — before `lanes[i] = LANES - 1`

> More voices at once than there are lanes: share the
> last one rather than drawing off the bottom.


## `Wave._blocks`

**line 349** — before `self._drawn = []`

> Recorded as they are drawn, and hit-tested against the same list:
> the geometry cannot then disagree with itself.

**line 361** — before `if self.cursor is not None and 0 <= self.cursor[0] < len(self.doc.lines):`

> The untimed pieces belong to whatever is being worked on, not to
> every line at once -- forty loose rows would bury the strip.


## `Wave._group`

**line 385** — before `fill = T.q(T.CHIP if voice == 0 else T.BACK, 90)`

> Every line is drawn; the ones being worked on are the ones
> that stand out. Everything else is context.


## `Wave.mousePressEvent`

**line 466** — before `self.seeked.emit(max(0.0, self.t_of(x)))`

> Seeking does NOT stop following. It used to, and the checkbox was
> never told -- so one click in the strip left the box ticked, the
> view pinned, and no way back except toggling it twice. A click here
> asks to go somewhere; following is about what happens after.


## `Wave.wheelEvent`

**line 503** — before `if self.follow:`

> Scrolling the view sideways IS "let me look somewhere else", so
> it does stop following -- and says so, out loud, so the checkbox
> and the behaviour cannot disagree.
