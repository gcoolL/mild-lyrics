# `aligner/renderers.py`

Comments lifted out of `aligner/renderers.py`. Docstrings stayed in the code, and so did tool directives (`noqa`, `pragma`, the shebang).


## module level

**line 52** — before `TEXT = None`

> The two things these painters need from the window's own module. lyrics_gui
> fills them in where it imports this one. A plain `import lyrics_gui` here
> would load a SECOND copy of that module every time the window is started as a
> script -- which is how the .desktop file starts it -- so the dependency is
> handed over instead of reached for.

**line 60** — before `RISE_LEAD = 0.06`

> The rise sets off a little before the syllable does and is over shortly
> after it starts, so a syllable is already moving when it arrives rather
> than setting out once it is being sung. Held notes would otherwise climb
> for as long as they are held -- the rise took the whole of a word's length,
> so a note held four seconds rose for four seconds, which reads as drifting
> rather than as a lift.
>
> The lead was 0.18s, which is a fifth of a second of a word standing up
> before anything is sung: on a line of short words the whole line was in the
> air ahead of the voice. It is a HINT that the word is coming, not an
> announcement, so it is down to the width of one frame or two at the rates
> this draws at -- the movement still starts first, which is all it was for.
>
> It was worth finding out what a wider schedule looks like, and the answer is
> that it looks wrong. Cutting the window from the local word rate so that
> consecutive rises overlap does make the line move more continuously -- about
> half as many frames with nothing moving at all, measured over three
> documents at three tempos -- but what you get for that is two or three words
> off the floor at once, and a word standing up before it is sung reads as the
> line guessing ahead rather than as the voice lifting it. The rise belongs to
> the word being sung. It stays there.

**line 84** — before `STAYING = (0.0, None, 1.0)`

> What float_lifts hands back for a word that has not set off yet: on its
> baseline, at the size it was set in, and at whatever opacity the rest of
> the line is being drawn at -- which is what the None says, since only the
> caller knows whether that is the un-sung falloff or the activation.

**line 90** — before `MAX_BLUR = 9`

> The blurriest a distant line is allowed to get, and so the number of
> pictures one line can ever need. lyrics_gui reads it to know the range to
> look through when it is rationing builds -- see its _nearest_blur.


## `Renderer`

**line 100** — before `scrolls = True`

> False pins the lines: tick() then leaves view.scroll where it is instead
> of chasing the line being sung down the column.

**line 103** — before `stacked = False`

> Whether the column is laid out by view.layout_line at the window's own
> lyric font -- so the window can work out where any fragment of any line
> ended up without asking. Only the stack is: the pinned renderers choose
> their own sizes and lay their rows out themselves. What reads it is
> LyricsView._paint_review_marks, which draws under the words and cannot
> guess at their boxes; a renderer that answers False gets the marks in
> the margin and none in the text.

**line 111** — before `snap = False`

> Each word takes the sung colour whole at the moment it starts, rather
> than the fill sweeping through it. Only the stack has a use for this so
> far, but the fill is written once, in draw_row, and reads it from here.

**line 115** — before `SCALE_EPS = 5e-4`

> Nearer to full size than this is full size: a transform that moves the
> ink by less than half a thousandth costs a resample and shows nothing.
> Read by everything that has to decide whether a line_scale is worth
> applying, on both sides of the window. See scale_about.

**line 266** — before `NUDGE = 1.0 + 1e-7`

> Qt blits a pixmap onto whole device pixels while the transform is a
> plain translation, and resamples it the moment the transform is anything
> else. This is the smallest thing that is not a translation. It is not a
> trick to be tidied away: without it the picture lands on a whole pixel
> and the word steps instead of moving. See lifted_word.


## `Renderer.lifted_word`

**line 308** — before `m = max(3.0, fm.height() * 0.22)`

> Room for what hangs outside the advance -- a "j" reaches left of its
> origin, an "f" past the end of it -- and for the resample to have
> something to reach into rather than a hard edge.


## `Renderer.place_word`

**line 403** — before `parts = emph.parts`

> Each character goes where the WHOLE fragment would have put it, not
> where adding up the characters one at a time puts it.
>
> The two are not the same, and the difference is kerning. Drawing
> "even" in one go, the font pulls the pair after the "v" in by a
> pixel; drawing four separate characters and stepping by each one's
> own advance, it does not. So the moment a word starts being
> emphasised -- which is the moment it stops being drawn in one piece
> -- its later letters jump sideways, and they jump back when the
> emphasis ends. Measured over five documents: 19 of 104 emphasised
> words move a letter this way, by up to 3.7px.
>
> Asking the metrics for the width of the text BEFORE each character
> is asking for the shaped position, kerning and all, so the letters
> sit exactly where they sat a frame earlier and the only thing that
> moves them is the swell.
> Drawn in ONE piece, not character by character.
>
> Character by character is how AMLL does it, and it cannot be made
> safe at this type size. Measured on the real window at the settings
> this is used at, the ink gaps INSIDE a word are one to two pixels.
> Every per-character path then closes them: each character is floored
> onto the pixel grid on its own, scaled about its own centre on its
> own, and haloed on its own. A word with six letters came out as two
> runs of ink while it was held -- letters welded into blocks -- and
> every arrangement of slots, kerning and halo strength that was tried
> moved the problem around without fixing it, because a one pixel gap
> has nothing to give.
>
> So the swell is applied to the fragment as a whole: one scale about
> its own centre, one float, one string handed to lifted_word exactly
> as an un-emphasised word is. The gaps are then whatever the font
> laid out, scaled -- they cannot close, because nothing is positioned
> independently any more.
>
> What that costs is the per-character wave, which is the part of
> AMLL's emphasis that needs room this face does not have between its
> letters. What survives is the swell and the light, on the word.


## `Renderer.emph_glow`

**line 469** — before `radius = max(1, round(self.glow_of(ch, fm, emph.held)[0]`

> Sized for THIS character, not for the word it is part of,
> and then taken in by HALO_SIZE.


## `Renderer._paint_dots`

**line 551** — before `p.save()`

> Saved, not put back by hand at the end. This used to set NoPen and
> restore only the BRUSH, so the pen leaked into the rest of the
> frame: measured, a drawText straight after a line of dots put zero
> ink on the screen. The art panel survived it by luck -- it sets its
> own pen before every draw -- and a paint fault here is silent, so
> what it would have looked like is the window losing everything
> drawn after the dots.

**line 564** — on `                continue`

> this one has gone


## `Flow.__init__`

**line 616** — before `self._rk = self._rects = None`

> What `rects` last handed back, and what it was built for.

**line 619** — before `self._warm_at: int | None = None`

> Which line _warm_next is building ahead for, and whether it has
> finished. See _warm_next.


## `Flow`

**line 624** — before `HALO = True`

> Whether an ordinary word gets a halo behind it while it is being sung.
> The stack lights every word held longer than a moment. AMLL lights only
> the ones it has decided are being PERFORMED -- see Amll.emphasized --
> and gives the rest no shadow at all, which is most of what makes its
> held notes stand out: there is nothing else lit to compete with them.

**line 630** — before `HALO_SCALE = 1.0`

> How strongly a held word's own light is laid on, and how far it spreads.
> 1.0 is what glow_of asks for.

**line 635** — before `ALL_GLOW_SPREAD = 2`

> The light behind the words the voice has been through -- see all_glow,
> and `word_glow` for whether it is on at all. How many blur levels wider
> than the line's own picture the light is cut, and how brightly it is
> added at the line's full activation.
>
> Two levels, not three. `line_pixmap` blurs by shrinking the picture
> through a mip chain by (1 + level), so the spread is about how far the
> light carries from the letters: three levels is a quarter-size wash that
> pools in the gaps between words and reads as fog over the line, and one
> is so tight it barely leaves the ink. Two hugs the letters and falls off
> inside half their height, which is the bloom a glow actually looks like.
> It is also well inside MAX_BLUR from a focused line, so the level asked
> for is one the cache already keeps a family member at and the ration
> already knows how to stand in for -- see _warm_next, which builds it
> ahead with the rest.

**line 653** — before `ALL_GLOW_PAST = 0.4`

> What a word the voice has left behind keeps, against the word in the
> mouth, and how far back the one comes down to the other -- in line
> heights, so the type takes it along the way everything else here does.
>
> Under half. The point of this is that sung words go on glowing, but if
> they glow as hard as the word being sung then the brightest thing in the
> window is whichever part of the line has the most ink in it, and there
> is nothing for the eye to follow. Kept as a trail rather than a step at
> the word boundary: a step is a seam standing still in the middle of a
> line, and this is meant to read as a light being carried.

**line 665** — before `TRAIL_STEPS = 7`

> How many blits the trail is stepped across. It is a slow gradient over a
> couple of line heights, so it takes far fewer than the edge does.

**line 669** — before `def emph_plan(self, rows, pos: float, fm: QFontMetricsF,`

> -- the fill, as three decisions a subclass can take differently ----
>
> Pulled out of _paint_line rather than left inline because the amll
> column fills a line by a different rule and the rest of that method --
> the rise, the pop, the glow, the ruby, the readings -- is the same
> either way. What is a per-word question here is a per-row one there.


## `Flow.paint`

**line 797** — before `m = H if (v.zero_g > 0 or v.clouds > 0) else 40`

> One margin and one cloud test for the frame, not one of each per line.


## `Flow`

**line 818** — before `WARM_REACH = 5`

> How far from the line being sung a picture is still worth building
> ahead. Beyond this the blur has saturated -- 1.4 * 4**1.35 is already
> over MAX_BLUR -- so every line out here shares one level and has had it
> since the last switch. Nothing to warm.


## `Flow._warm_next`

**line 865** — on `                return`

> more to do; come back next frame

**line 866** — before `ln = v.lines[i]`

> Only the rows _paint_line actually BLITS. It hands a credits
> block to _paint_credits and an interlude to _paint_dots, both
> before the pixmap path, and neither of them has a picture --
> layout_line gives a credits row (n, text) pairs rather than the
> (x, advance, text, start, end) line_pixmap unpacks, and gives an
> interlude no rows at all. Asking for one raised straight out of
> paintEvent, which loses the whole frame AFTER the lyrics: the
> art panel, the toast and any overlay simply never got drawn.

**line 878** — before `if v.focus and dist > v.focus + 1:`

> The same window _paint_line draws, so nothing is built for a
> line that will not be on screen to want it.

**line 888** — before `if v.word_glow > 0 and v._pix_left > 0:`

> The glow is another member of the same family -- the same line
> at a wider level, in the sung colour instead of the base ink --
> wanted on the same frames and missing from the cache for the
> same reason. Warmed here so turning it on does not double the
> burst a switch pays. See all_glow.

**line 896** — before `self._warm_done = v._pix_left > 0 or v._pix_left == had`

> The loop ran to the end, so every line in range was asked for and
> there is nothing to come back for. The one thing that can still be
> outstanding is the second level on the very last line, skipped
> because the ration ran out exactly there -- which reads as no ration
> left and something built, and is the one case that runs again.


## `Flow.float_of`

**line 943** — before `t = min(1.0, (pos - at) / self.float_span())`

> Clamped rather than short-circuited at the far end, so what comes
> back never goes backwards: a word long gone reads as all the way up
> with nothing left, and not as back on its baseline. Nothing draws it
> either way -- the caller is gone at zero -- but a lift that falls to
> zero at the end of the flight is a trap for the next thing that asks.

**line 949** — before `unit = self.v.lyric_fm(False).height()`

> It goes faster the higher it gets, and it is transparent long before
> it is far: at half gone it has travelled a third of the distance,
> which is what letting go of something looks like from underneath --
> a thing that is thrown starts fast and slows, and this does not.
>
> The distance is measured off the MAIN lyric font rather than the
> line's own, the way word_lifts measures the rise, so an ad-lib set
> at two thirds the size does not float two thirds as far.
>
> And it grows on the way, on the same curve as the climb, so that the
> word reads as coming AT the reader rather than receding: a thing
> going away gets smaller, and a word that shrank as it faded would be
> leaving through the back of the window instead of over your head.
> Half faded it is half again as big, which is as far as this can go
> before a word passing the line above it is wearing it.


## `Flow`

**line 967** — before `DOT_STAGGER = 0.34`

> How far apart the three dots let go, as a share of one flight. A third
> of a flight: enough that they leave in a countable order rather than as
> one object coming apart, and not so much that the first one is halfway
> up the window before the last has moved.


## `Flow.dot_flights`

**line 991** — before `start = ln.get("start")`

> The last dot's flight ends on the line's first word; the ones before
> it set off a stagger earlier each, and none of them before the break
> itself has started -- a gap shorter than the whole departure lets
> them all go at once rather than going back in time to do it.


## `Flow.float_lifts`

**line 1029** — before `flight = self.float_of(s if s is not None else start, pos)`

> A fragment with no clock of its own leaves with the line
> it is part of, rather than sitting there for ever after
> everything round it has gone.


## `Flow.all_glow`

**line 1205** — before `lit = [self.sung_edge(row, pos) for row in rows]`

> Where the light reaches on each row, and the band of the picture
> that row owns.
>
> The bands meet at the row BOXES and not midway between the
> baselines. Midway looks like the fair answer and is not: a row's box
> is its ascent and its reading above it, which reaches a good deal
> further up than half the gap, so the seam fell inside the next row's
> capitals and lit the tops of words the voice had not got to. See
> sung_edge -- the whole point of this is that nothing ahead of the
> voice is lit, and a seam is no excuse.
>
> So a band starts where its row's box starts and ends where the next
> one's does. The first runs up to the top of the picture, which is
> the padding the first row's own light spills into. The last runs to
> the bottom for the same reason -- unless there are romaji under it,
> which are their own words at their own widths and have no business
> being lit by the row above.

**line 1243** — before `self._glow_strip(p, at, pm, 0.0, float(pm.width()), top, bot, past)`

> A row the voice has finished with. All of it is behind, so
> all of it is at the settled level -- the trail below is
> measured from where the voice IS, and it is not on this row.

**line 1248** — before `self._glow_strip(p, at, pm, 0.0, pad + edge - trail, top, bot, past)`

> The row the light is on. Three pieces, left to right: everything
> well behind the voice at the settled level, a trail coming up to
> full across the last line-height and a half, and the soft edge
> the voice itself is standing on.
>
> The trail is what makes it a light being CARRIED rather than a
> line that has been switched on. Words already sung keep a glow,
> because that is the point of this, but they keep less of one
> than the word in the mouth -- otherwise the brightest thing in
> the window is wherever the line happens to be longest, and the
> eye has nothing to follow.
>
> All of it drawn as narrow blits with the opacity stepping across
> them rather than by masking the picture through a gradient. A
> gradient cannot be applied to a pixmap without an off-screen
> copy, which is a full-size allocation and three more passes over
> every pixel of the line, every frame. The strips are clipped, so
> they share out the row's pixels rather than each paying for them
> -- twenty of them cost about what one blit of the row does.


## `Flow.draw_base`

**line 1347** — before `flew, left, big = gone.get(`

> A reading goes wherever the kanji under it goes, grows
> with it and fades with it. See ruby_lift: the same
> argument, and the same answer.

**line 1363** — before `if spin is not None and (r_i, x) == (spin[0], spin[1]):`

> The word being spun draws its own base, turned; a second
> copy sitting still underneath it is the thing the old clip
> was cutting away.

**line 1374** — before `self.place_word(p, QPointF(ox + x, gy), txt, lift, fm, big,`

> The centre a growing word turns about is where the word
> actually IS, which is the lift's business: scaling about the
> baseline it left behind would throw it further up the window
> the bigger it got. Nothing noticed while the only thing that
> scaled was the pop, two pixels off its own line.


## `Flow._paint_line`

**line 1676** — before `peek = self.v.focus_idx`

> The line the column has SCROLLED TO counts as near, as well as the
> line being sung. With `scroll_lead` set -- and it is set by default
> -- the two are different for the third of a second before a line
> starts: the column has already moved down to it, so it is sitting at
> the anchor being read, and it was still being drawn blurred because
> nobody was singing it yet. Whatever the reader is looking at is
> what should be sharp.

**line 1702** — before `y = y + (1.0 - act) * 7.0 * self.v.line_drop * (1 if idx in live else 0)`

> The line's own entrance: it lands seven pixels low the frame its
> first word starts and rides the activation back up to where the plan
> put it. The drop is a STEP -- a line not yet sounding is drawn at its
> place, and joining `live` moves it -- so what the eye gets is the
> line being knocked down and recovering, not sliding in from below.
> That is the effect, and `line_drop` scales it; at 0 the line simply
> lights up where it already was.

**line 1727** — before `gone = {}`

> Troll: every syllable lifts off and fades from the moment the voice
> reaches it, so a line comes apart in the order it is being sung
> rather than going up as a slab. What is settled here is only which
> words have left and how far; draw_base and the fill below put them
> where that says, between them drawing the un-sung half of a word and
> the sung half at the same height.
>
> Below the clouds and zero-g on purpose. Both of those already have
> the words off the line and moving on their own account, and two sets
> of arithmetic arguing over where one word is is not a third effect.

**line 1739** — before `last = self.float_of(ln.get("end") or ln.get("start"), pos)`

> Nothing in the line sets off later than the line's own end, so
> once THAT flight is over every word in it has gone and there is
> nothing here to draw at all. One comparison to find that out,
> before the scan below walks the fragments: it is the answer for
> every line the song has already passed, which by the end of a
> play is most of the document.

**line 1751** — before `emphs = (self.emph_plan(rows, pos, fm, ln["background"])`

> Once for the line: the un-sung layer below and the fill over it must
> agree to the pixel about where every character of a held word is.

**line 1755** — before `own_text = ((self.v.rise > 0 and act > 0.01 and blur < 1.0)`

> Whether the line draws its own text is decided by whether the rise
> can reach it at all, not by whether anything has lifted YET: live
> text and a blitted pixmap do not rasterise quite alike, and switching
> between them at the moment the first word sets off puts a visible
> change of weight in the middle of a line. Switching when the line
> activates hides it under the fade that is happening anyway.
>
> A line with a word in the air cannot use a picture either, and for
> the same reason the rise cannot: every word in a pixmap is on the
> baseline. That half is not gated on the activation, unlike the rise
> -- a line whose last word left as the next line started is still in
> the air well after its activation has eased away to nothing.
> A line with a word coming apart into its characters cannot use its
> cached picture either, and for the same reason the rise cannot:
> every word in that picture is one piece, on the baseline.

**line 1806** — before `gy = self.on_grid(ry)`

> The same rounding draw_base does, because the fill goes over the
> text draw_base drew and the two cannot disagree about where the
> row is. See lifted_word: a baseline on the grid is what lets a
> word that is not moving be glyphs instead of a picture.

**line 1836** — before `flew, left, big = gone.get((False, r_i, f_i), STAYING)`

> How far this word has floated off, and what it is being
> drawn at: its own remaining opacity if it has left, and the
> line's activation if it is still in place. A word on its way
> out is lit at the brightness it was sung at and fades from
> there -- it does not drop to the un-sung falloff the instant
> it leaves, which is a flicker in the middle of the line.

**line 1850** — before `rise = lifted.get((r_i, f_i), 0.0) + flew`

> Both of the vertical moves this fragment is about to make,
> worked out before anything is drawn: the glow is painted
> first and has to be put where the word is GOING to be, not
> where its baseline is. A halo drawn at the baseline sat in
> the hole a lifted word had just climbed out of -- the word
> up in the air with its own light left on the floor beneath
> it, which is the one thing a halo must never do.

**line 1860** — before `self.emph_glow(p, emph, QPointF(px, gy), font, fm,`

> The word is being held, and its swell replaces the pop
> and the one halo cut for the whole word outright rather
> than layering under them.

**line 1876** — before `poplift = popk * self.v.pop * fm.height() * 0.055`

> Left fractional, like the rise: lifted_word places the
> word where this actually says rather than on the nearest row
> of pixels, and the glow below is given the very same number,
> so the halo cannot cross a boundary half a frame before the
> letters it belongs to.

**line 1889** — before `grow = (1.0 + 0.38 * swell * strength) * big`

> `big` as well: a word being sung is also a word on its
> way out under the float troll, and a halo that stayed
> its own size while the word grew through it would be a
> light sitting inside the letters instead of behind them.

**line 1907** — before `wcx, wcy = px + w * 0.5, gy - fm.ascent() * 0.35`

> draw_base has already put this word's un-sung self at the
> same height; the fill goes over it. Neither of them puts the
> lift on the painter any more -- lifted_word places the word
> itself, because a translation is exactly what Qt rounds away.

**line 1915** — before `if rise or poplift:`

> The spun word turns about its own centre, and a rotation
> is a transform on the painter whatever else is going on,
> so its lift rides along on that rather than through
> lifted_word. It is already being resampled.

**line 1936** — before `self.lifted_word(p, QPointF(px, gy), txt, rise + poplift,`

> The centre follows the word up. See draw_base, which
> draws the un-sung half of this same word at the same
> place and has to agree with it to the pixel.


## module level

**line 2001** — before `def _bezier(x1: float, y1: float, x2: float, y2: float):`

> -- AMLL's emphasis, and the easings it is cut with ----------------------
>
> Ported from applemusic-like-lyrics,
> packages/core/src/lyric-player/dom/animation/{emphasize,float}/index.ts.
>
> The stack's own swell -- the pop and the glow -- is one movement per WORD:
> the whole word grows and lights on a sine through its own span. AMLL's is
> per CHARACTER, and it is three movements at once, each on its own clock:
>
>   * the letters grow, and push APART from the middle of the word, so a held
>     word opens out rather than simply getting bigger;
>   * each letter floats up and back down on a sine, starting 400ms before its
>     own glow and running 1.4 times as long;
>   * the glow swells and dies on a two-piece bezier that is not symmetric --
>     it comes up faster than it goes away.
>
> and each letter is started a little after the one before it, so the movement
> travels through the word instead of happening to all of it at once. That
> stagger is the reason it is worth having per character at all.

**line 2067** — before `_BEZ_IN = _bezier(0.2, 0.4, 0.58, 1.0)`

> The two halves of the emphasis envelope. It is deliberately lopsided: the
> light arrives on one curve and leaves on another, so the word does not
> simply breathe in and out symmetrically.

**line 2072** — before `_EASE_OUT = _bezier(0.0, 0.0, 0.58, 1.0)`

> CSS `ease-out`, which is what a word's ordinary float is cut with.

**line 2085** — before `_CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")`

> The ranges spicy_lyrics.CJK covers, kept here rather than imported so that
> this module goes on depending on nothing but Qt. If that one moves, this is
> the other place to look.

**line 2090** — before `_EM = 0.83`

> A line's height is not its em. 0.05em is AMLL's float distance and this is
> what that comes to as a fraction of QFontMetricsF.height(), which carries
> the leading as well.


## `Emph.__init__`

**line 2145** — before `self.parts, self.radius, self.held = parts, radius, held`

> `radius` is the halo the WORD would take; `held` is how long the
> note is, which is what a halo for one CHARACTER has to be worked out
> from. See emph_glow: a blur cut for a six letter word is two and a
> half times what a single letter wants, and drawing that on each
> letter is how a held word ended up wearing a haze.


## module level

**line 2156** — before `def _solve_spring(frm: float, vel: float, to: float, mass: float,`

> -- springs, for the renderer below ---------------------------------------
>
> Ported from applemusic-like-lyrics, packages/core/src/utils/spring.ts and
> packages/core/src/lyric-player/base/spring.ts.
>
> The thing worth taking is that the spring is SOLVED rather than stepped. A
> stepped spring integrates a velocity once per frame, so its path depends on
> how the frames fell -- a dropped frame is a different curve, and a window
> that was hidden for a second comes back somewhere else entirely. This one
> has a closed form for position at time t, so the frames only decide where it
> is SAMPLED. Two machines drawing at 60 and at 144 draw the same movement.


## `Spring`

**line 2210** — before `H = 1e-3`

> The step either side used to read a speed off the solved curve. AMLL's
> derivative.ts, which does the same thing for the same reason: the closed
> form gives a position and re-aiming needs a velocity.


## `Spring.__init__`

**line 2219** — on `        self._f = None`

> None: sitting on the target

**line 2220** — on `        self._queued = None`

> (seconds to wait, where to go)


## `Spring.arrived`

**line 2268** — on `            return True`

> the cheap answer, and the common one


## `Spring.set_target`

**line 2292** — before `if self._queued is not None:`

> Saying again what has already been said does not restart the
> wait. The renderer re-states every line's aim on every frame --
> it has no cheap way to know the aim did not move -- and a wait
> re-armed each frame is a wait that never comes round, which is a
> line that never sets off at all. What the caller means by a
> delay is "be there after this long", not "start counting again".


## module level

**line 2329** — before `_SLOW = (90.0, 15.0)`

> How the column is carried, by the gap between the line being sung and the one
> before it. AMLL's getPosYSpringPolicy, numbers and all.
>
> What this buys is a column that moves at the song's rate without being told
> what that is: a patter verse whose lines are a fifth of a second apart is
> carried stiffly enough to keep up, and a ballad with four seconds between
> lines is carried gently, because a stiff spring over a long gap arrives and
> then sits waiting, which reads as the column twitching between lines.

**line 2337** — on `_SLOW = (90.0, 15.0)`

> seeks and interludes


## `_spring_policy`

**line 2347** — before `ratio = (1.0 - (g - _MIN_GAP) / (_MAX_GAP - _MIN_GAP)) ** _GAP_EXP`

> Fifth root, so the mapping leans toward the fast end rather than
> sitting in the middle of the range for most of it.


## `Amll`

**line 2384** — before `HALO = False`

> Only a word this renderer has decided is being held lights up, and it
> lights per character. See Flow.HALO and Amll.emph_of.

**line 2387** — before `HALO_SCALE = 1.0`

> How strongly a held word's own light is laid on.
>
> This was turned down to a quarter for a while, to stop the light from
> bridging the gap between two letters and welding them. That was the
> wrong culprit, found with a measurement that could not tell a letter the
> fill had not lit yet from a letter that had merged with its neighbour.
> What was actually welding them was the word GROWING -- see SWELL.
>
> With the growing gone the letters no longer move, so the gaps can be
> measured where they actually are. At full strength the dimmest point
> between two letters still sits 54% below the letters themselves, over
> every emphasised word in a chorus. There is nothing here to turn down.

**line 2400** — before `HALO_SIZE = 1.0`

> How much a held word grows. 0 keeps the letters exactly as the font laid
> them out, which is the only thing that holds at a one pixel gap; see the
> note by `word_scale` in emph_of.
> How far a held word's light spreads, against what glow_of asks for.
>
> 1.0, because the shrinking that was wanted had already happened. The
> halo used to be sized from the whole WORD's width and then drawn on each
> letter -- eleven pixels of blur on a single character instead of four --
> which is what read as a huge glow. Sizing it per character fixed that;
> taking it in by half on top left about two pixels, which is barely a
> glow at all. This is the knob if it wants adjusting, but the fault was
> the wrong unit, not the amount.

**line 2414** — before `BOB = 0.0`

> How much each character bobs on its own while the word is held. Off for
> the same reason SWELL is; see the note by the parts built in emph_of.

**line 2418** — before `ALIGN = 0.35`

> Where the line being sung is held down the window: AMLL's alignPosition,
> against its Center anchor, so it is the line's MIDDLE that lands here and
> a couplet that wraps to three rows does not sit lower than a short one.

**line 2422** — before `SCALE = 0.97`

> What a line that is NOT being sung is drawn at -- AMLL's SCALE_ASPECT.
> The way round is worth noticing: the sung line stays its own size and
> everything else shrinks a little, so the line being sung is never bigger
> than the type the document was set in. Against its neighbours it still
> reads as growing, and `scales` springs each line between the two, so it
> grows over about the length of a word rather than snapping.
>
> This was 1.0 for a while, which turned the whole cue off, over two
> objections that are both answered now:
>
>   * The review marks. `stacked` used to answer False for anything
>     scaled, which sent the marks to the margin for as long as this
>     renderer was in use. But the layout never stopped being the
>     window's -- only the painter was transformed -- so the answer is to
>     publish the transform, not to disown the layout. See `line_scale`,
>     which _paint_review_marks now puts the boxes through.
>   * Resampling. A painter under any transform resamples, so a scaled
>     line is a slightly soft line. That is true and it is the price;
>     what makes it payable is that it is never charged on a line
>     anybody is reading sharp. The line being sung and its neighbours
>     are lit, and lit lines are held at 1.0 and never see a transform;
>     a hand on the wheel takes the column to full size for as long as it
>     is there (see `browse` below); and a stopped song is all 1.0. What
>     is left is the un-sung depth of a playing column, which the stack
>     has already blurred and faded.

**line 2448** — before `STAGGER = 0.05`

> The stagger. Each line down the column sets off this much later than the
> one above it, and below the line being sung the spacing tightens by
> DECAY per line, so the wave gathers as it goes rather than spreading.

**line 2453** — before `MAX_STEP = 0.10`

> A step longer than this is a window that was hidden, not a slow frame.
> Handing it to the springs whole runs most of a second of travel between
> two drawn frames, which is a column that teleports on being shown again.

**line 2457** — before `FADE = 0.25`

> Half the width of the light that travels along a row, as a fraction of
> the line's height -- so the band itself is 0.5 of it, which is AMLL's
> wordFadeWidth default. Scaled by the window's own `edge` knob, which
> goes on meaning the same thing it means everywhere else.

**line 2462** — before `JITTER = 0.15`

> Telling a seek from playback, which is AMLL's SeekDetector and its
> numbers. The idea is to stop guessing at a threshold and compare the
> MEDIA clock's advance against what the wall clock says it should have
> been: playing, it should have moved by the frame time; paused, not at
> all. Anything else is a jump.
>
> A fixed threshold could not do this. At 1.5 seconds it missed a click on
> a line a beat away -- which reads as ordinary playback by size alone,
> and is nothing of the kind -- and any threshold small enough to catch
> that would have fired on the clock's own slew.
>
> Springs go to the slow parameters across a seek and the stagger is
> dropped: a drag along the progress bar moves the focal line every frame,
> and a wave started on each of them is a column that never settles.

**line 2476** — on `    JITTER = 0.15`

> what the clock may be out by regardless

**line 2477** — on `    DRIFT = 0.5`

> ...plus this share of the expected advance

**line 2478** — on `    UNTRUSTED = 0.8`

> a frame longer than this proves nothing


## `Amll.__init__`

**line 2488** — before `self.offset = 0.0`

> How far the reader has pushed the column away from where the song
> would have put it, and the range that is allowed to be. AMLL's
> scrollOffset, and the bounds its beginFrame works out every frame.

**line 2493** — before `self._sought = None`

> The line a click asked for, held until the song's own answer reaches
> it. See _focal.

**line 2496** — before `self._focal_was = None`

> The last focus worth believing, and how many frames running the
> clock has claimed to be before the song started. See _focal.

**line 2500** — before `self._jolt = False`

> Set whenever the column is moved by the reader rather than by the
> song, which is one of the cases the stagger must not be used for.
> See the note above `spacing` in paint.

**line 2504** — before `self._last_top = None`

> Where the column was aimed last frame, so this one can tell which
> way it is about to move and how far.

**line 2507** — before `self._held = None`

> The line the column was built around when the reader took the
> wheel. AMLL's FocusController freezes it for as long as they are
> reading, so the song does not slide the column out from under them.

**line 2511** — before `self.now = mono`

> The wall clock the springs are stepped by, held rather than reached
> for so that a test can drive a frame at a time. Nothing else moves
> them: the song's own clock says WHERE the column should be, and this
> says how long it has had to get there.


## `Amll`

**line 2517** — before `def line_scale(self, i: int) -> float:`

> Inherited from Flow, and true: the column is laid out by
> view.layout_line at the window's own lyric size, which is the question
> `stacked` asks. It used to answer False here on the grounds that SCALE
> moves the ink, but that is a fact about the PAINTER, and the answer to
> it is `line_scale` rather than giving up the layout. See SCALE.


## `Amll._rebase`

**line 2610** — before `hold = self.ys[-1].value`

> Same song, different number of lines -- a marker inserted, a
> split changed. Make the lists fit and leave the column alone:
> anything new starts where the line above it already is, so
> nothing flies in and nothing jumps.


## `Amll._seeking`

**line 2651** — before `return False`

> The window was away. Nothing can be told from this frame, so
> nothing is claimed -- the baseline above is all it is good for.


## `Amll._focal`

**line 2686** — before `if seeking:`

> A click is authoritative and immediate: the reader pointed at a
> line, and that is where the column goes.

**line 2692** — on `                self._sought = None`

> the song has caught up

**line 2698** — before `if self._focal_was is not None and i < self._focal_was - 1:`

> Otherwise, a clock that has momentarily lost its place must not move
> the column. A seek is a round trip to the player, and until it
> answers, the position can read as something from before it. Taken at
> face value that is the song being somewhere else entirely, so
> clicking a line could send the whole column up the document and then
> bring it back down -- two moves, the first one to nowhere.
>
> What tells the two apart is not WHERE the answer is but whether it
> lasts: a reading that was never true is replaced a frame or two
> later, and a real one keeps saying the same thing. So a jump
> backwards that nothing asked for is held for three frames before it
> is believed. A genuine one still arrives, fifty milliseconds late,
> which is nothing; a phantom is gone before it can move anything.


## `Amll`

**line 2720** — before `CLICK_SNAP = 0.05`

> How near a seek has to land to a line's start to count as a click on it.

**line 2745** — before `def _fade(self, fm: QFontMetricsF) -> float:`

> -- one light, travelling along the row -----------------------------
>
> The stack fills a word from the word's own clock: the boundary is at
> `frac` of the way through THIS word, and the soft edge either side of it
> is drawn only on this word, because this is the only word being drawn
> with a gradient. Everything to its left is solid and everything to its
> right has not been drawn at all.
>
> That is not what AMLL does, and the difference is the soft edge. There
> the mask is one gradient per row in the ROW's own coordinates, so the
> band is a light of real width -- half a line height -- travelling along
> the row, and when it straddles a syllable boundary it lights the tail of
> one word and the head of the next at the same time. Cut at every
> boundary, as the stack cuts it, a band that wide is a band that is
> almost never drawn whole: on syllable-timed text it is truncated several
> times a word.
>
> So the position is worked out once for the row and every fragment near
> it is drawn with the same gradient, in the same coordinates. Where the
> light is between two words -- a gap in the timing, a held breath -- it
> sits still at the end of the last word sung, which is AMLL's pause
> segment and the reason the sweep does not run ahead of the voice.


## `Amll.fill_shows`

**line 2811** — before `if frac > 0:`

> Its own clock says it is lit, whatever the rest of the row is doing.
> This is what keeps a word being sung across another one drawn: the
> nearest light may well be the other voice's.

**line 2816** — before `soft = self._fade(fm)`

> A word the voice has not reached has ink only where a light BEHIND
> it spills onto it, and `Sweep.near` is what decides that a light is
> behind it.
>
> Asking only whether it lies left of the light was the first bug.
> With one voice nothing unstarted ever does, so it never showed; with
> two, a word waiting for the second voice sits well to the left of the
> first voice's light, passed that test, and was then drawn solid for
> being "behind" a light that was never coming for it. Measured over
> four lines that have words sung across each other, a word that had
> not started was drawn fully sung in 679 frames out of 680.
>
> Asking whether the band reached it from EITHER side was the second,
> and it is the same fault a hair's breadth narrower. The band is a
> TRAILING fill -- sung behind the light, clear in front of it -- so a
> light two pixels past a word's last letter leaves every letter of it
> behind the light, and a gradient PADS: the word is painted as solidly
> as one being performed. What it looks like is a word lighting up for
> the two or three frames it takes the other voice to move on.
>
> With the light in front of a word dropped where it is chosen, all
> this has left to ask is the other end: whether the band reaches
> FORWARD far enough to touch a word the light has yet to arrive at.


## `Amll.fill_pen`

**line 2834** — before `if frac >= 1.0:`

> Sung is sung. Nothing else in the row may un-sing it.
>
> This used to ask the nearest light instead, and where two voices
> share a row the nearest light moves: a word finished by the first
> voice would find the second voice's light closer, get that light's
> gradient, and go back to being half unlit. On screen the line looks
> like it re-ran its own sync from the middle.

**line 2843** — before `if frac > 0.0:`

> Part way through: its OWN light, not the row's nearest. With one
> voice these are the same thing -- the row's light IS this word's --
> so the only case they differ is the one that was going wrong.

**line 2849** — before `ed = sweep.near(px, w)`

> Not started: the only light that can reach it is a neighbour's,
> which is what lets the soft edge cross a word boundary. It is
> never solid -- nothing the voice has not reached is fully sung,
> whatever is lit elsewhere in the row. Which is why the clear
> colour is an answer this has to be able to give: `Sweep.near`
> hands back nothing at all when every light in the row is in
> front of this word, and a pen of the sung colour at no alpha
> draws exactly the nothing that deserves.


## `Amll`

**line 2860** — before `EMP_MIN = 1.0`

> -- the swell, AMLL's way -------------------------------------------

**line 2862** — on `    EMP_MIN = 1.0`

> a word held this long is worth emphasising

**line 2863** — on `    EMP_CHARS = 7`

> ...and that second buys this many letters. A longer word is not shut
> out, it is asked to be held for proportionally longer -- see
> `Amll.emphasized`, where the ceiling this used to be is argued into a
> rate. Unless it is CJK, which is exempt from both readings.

**line 2864** — before `FLOAT_MIN = RISE_TIME`

> The shortest a float is allowed to take, which is the one number here
> that is deliberately NOT AMLL's.
>
> AMLL floats a word over max(1s, its length). The 1s floor is written for
> word-timed lyrics, where a word often lasts about that. Against
> syllable-timed text it is the wrong floor by a factor of four -- the
> median syllable across three documents here is 0.22 to 0.26s -- so every
> ordinary syllable was caught a quarter of the way up its climb and the
> `rise` knob read at about a THIRD of what the same number gives in the
> stack: measured 0.35, 0.36 and 0.46 of it on Poker Face, Time and
> Clocks. A setting shared with every other renderer cannot mean a
> different amount here.
>
> Lowered to the stack's own RISE_TIME, which is its answer to the same
> question. That brings the three documents to 0.84, 0.82 and 0.75 of the
> stack, and it costs nothing that makes AMLL's float what it is: the
> floor only ever binds on syllables SHORTER than it, so a held note is
> untouched -- a three second note still climbs for the whole three
> seconds, reaching the same 1.6, 4.1 and 6.0 pixels at 0.5s, 1.5s and 3s
> whatever this is set to. Put it back to 1.0 for AMLL's own number.

**line 2885** — before `EMP_LEAD = RISE_LEAD`

> How early a character's float sets off ahead of its own glow. AMLL says
> 400ms; this says RISE_LEAD, and the argument is already written down at
> the top of this file.
>
> At 0.4s the swell does not start early within a word, it starts during
> the WORD BEFORE. Measured on a held word following a short one: every
> one of its six characters was already moving 0.30 to 0.38s before the
> word began, which is to say the whole of it was in the air while the
> previous word was still being sung -- and the letter that shows it worst
> is whichever one opens the held syllable, because that is the part of
> the word the voice has not reached at all.
>
> RISE_LEAD's note records this same finding for the stack's own rise and
> settles it: a lead of 0.18s was already judged too much, because "a word
> standing up before it is sung reads as the line guessing ahead rather
> than as the voice lifting it", and it came down to one or two frames --
> enough that the movement still starts first, which is all a lead is for.
> That answer applies here unchanged; 0.4s is more than twice the value it
> rejected. AMLL can afford it because a word there is one timed unit and
> its neighbours are words, not syllables of the same word.

**line 2906** — before `SETTLE = 0.25`

> How long after the note the last character is still settling. See span.

**line 2908** — before `CHAR_STEP = RISE_LEAD`

> How far apart the characters of one SYLLABLE set off. A couple of
> frames -- enough to read as a wave, never enough to pretend the voice
> has moved through a held note. See the note by `arrive` in emph_plan.

**line 2912** — before `RISE = 0.055`

> How far a word floats, as a fraction of the line height.
>
> AMLL says 0.05em and the stack says 0.055 line-heights, which are the
> same intent in different units -- but the window's `rise` knob is
> calibrated against the STACK's, and converting the em honestly came out
> at three quarters of it. The knob then meant something quieter here than
> everywhere else in the window, which is the one thing a shared setting
> must not do. So the distance is the stack's and the SCHEDULE is AMLL's,
> which is the half that actually differs. See word_lifts.


## `Amll.emph_plan`

**line 3008** — before `arrive = []`

> When the voice actually reaches each character, read off
> the syllable it belongs to rather than assumed even across
> the word. See emph_of.
> When the voice reaches each character.
>
> A SYLLABLE is the smallest thing the voice actually moves
> between, so its start is when all of its characters arrive.
> Spreading them across the syllable's length instead -- which
> is what this did first -- claims the voice walks through the
> letters of a held note, and it does not: two characters held
> for two seconds had the second one arriving a full second
> after the first, so it swelled on its own, a second late,
> with the rest of the word already flat. One letter bulging
> by itself for the length of a held note, and right again the
> moment the note ends.
>
> Within a syllable the characters are given a couple of
> frames between them and no more: enough for the swell to
> read as travelling rather than as the whole syllable
> snapping at once, never enough to claim the voice has moved.
> Capped by the syllable's own length so a quick one cannot
> stagger past its own end.

**line 3042** — before `spans, at = [], 0`

> Lay the whole word out at its current size, across its
> fragments, and hand each fragment the slice that is its own.

**line 3063** — before `cur = left + (plain - grown) * 0.5`

> Re-centred, so opening out does not walk the word sideways
> into whatever is beside it.

**line 3069** — before `placed[sp[3]] = (cur + (wide - sp[1]) * 0.5) - sp[2]`

> The glyph is drawn unscaled then scaled about its own
> centre, so its centre goes to the middle of the slot.


## `Amll.emph_of`

**line 3122** — before `held_for = (e - s) if voiced is None else voiced`

> How long the NOTE is, which is what the gate and the two curves
> below are all asking about, and not the same as how wide the word's
> span is -- see voiced_of. The default is the span, so a caller with
> only a start and an end (a word asked about on its own) gets exactly
> what it always did.

**line 3141** — before `held = min(1.0, max(0.0, (held_for - 0.18) / 1.1))`

> How BRIGHT, and how far the light carries, from the window's own
> glow_of rather than from AMLL's curve -- the same trade as the rise,
> and for the same reason.
>
> AMLL cubes its glow below three seconds, so a word of 1.0s is lit at
> 0.018 and one of 1.5s at 0.063. Its own gate lets a word in at 1.0s,
> which means AMLL admits words to the emphasis and then gives them
> nothing to see: measured over five documents here, the peak alpha
> came out at 0.02 on Poker Face and 0.05 on Time. The effect was
> firing and was invisible.
>
> glow_of answers the same question -- how wide and how bright is the
> halo on a word held this long -- and it is already calibrated
> against these documents and against the window's type. It also
> measures the word's length as a WIDTH rather than a character count,
> which is the better measure and the one this file argues for at
> length. AMLL's own curve is two lines above, if it is wanted back.

**line 3166** — before `if arrive is None:`

> When each character starts, and the one place this cannot simply
> copy AMLL.
>
> AMLL sets character i going at `de + (du / 2.5 / n) * i` -- evenly
> spread across the word, then compressed toward its start so the
> swell travels through quickly rather than taking the whole note.
> Evenly spread is right THERE, because a word is one timed unit with
> nothing inside it.
>
> Here a word has syllables inside it, each with its own stamps, and
> they are regularly nothing like even. Spread evenly anyway, the
> characters of a late syllable set off long before the voice reaches
> them: a word split "mat" + "ter" with a long first syllable had the
> second "t" moving most of a second before it was sung, which reads
> as one letter of the word jumping the queue.
>
> So what is spread evenly is replaced by when the voice ACTUALLY
> arrives at each character, and the same compression is applied to
> that. It is the same formula: AMLL's `(du/n) * i` is simply the
> arrival time of character i in a word with no internal timing, so
> this reduces to exactly AMLL's stagger for such a word and follows
> the syllables for one that has them.

**line 3189** — before `arrive = [s + ((e - s) / n) * i for i in range(n)]`

> From the word's own length, not from `du` -- `du` carries the
> one second floor and the 1.2 the last word of a line is given,
> neither of which has anything to say about when the voice
> reaches a character. emph_plan always passes the real arrival
> times; this is the fallback for a word asked about on its own.

**line 3195** — before `offs = [max(0.0, a - s) for a in arrive]`

> A character starts when the voice reaches IT, not before.
>
> AMLL divides this by 2.5, pulling every character back toward the
> start of the word so the swell travels through quickly instead of
> taking the whole note. That is harmless there, because an AMLL word
> is one timed unit -- there is no such thing as "when the voice
> reaches character three", so nothing can be early relative to it.
>
> Here there is. Measured on a held word timed 4 + 2 characters: the
> voice reaches the fourth character at 71.904 and the compression
> started it moving at 71.620, nearly three tenths of a second before
> it was sung -- and the last two, which belong to the held syllable,
> set off 0.36s and 0.95s before their turn. One letter of a word
> stirring while the voice is still somewhere to the left of it is the
> whole complaint, and no lead small enough to fix it would leave a
> lead at all.
>
> So the arrival times are used as they stand. The swell then follows
> the voice across the word rather than anticipating it, which is what
> the fill beside it already does, and each character still leads its
> own moment by EMP_LEAD -- a frame or two, the same everywhere else.

**line 3218** — before `ends = (e - s) + self.SETTLE`

> How long each character's own swell lasts, chosen so that the LAST
> of them finishes as the word does.
>
> AMLL runs every character for the word's full length and staggers
> the starts on top of that, so the last character finishes a stagger
> AFTER the word -- four tenths of the note, which on a three second
> hold is well over a second of a finished word still shining while
> the next ones are being sung. Its float is worse: 1.4 times the
> length again.
>
> The swell belongs to the word being sung, the same rule the lead
> obeys at EMP_LEAD. So the stagger is taken OUT of the window rather
> than added to it, and the last character lands SETTLE after the end
> of the note rather than a whole stagger after it.
>
> SETTLE is not slack, it is what keeps the word looking shiny rather
> than rippling. With the characters no longer allowed to anticipate
> the voice their starts are spread across the whole note, so if each
> one also had to FINISH by the end of it, each envelope would be a
> fraction of the note and only one or two letters would ever be up at
> a time -- a wave running along the word instead of the word itself
> lighting. Letting the last one run a quarter second past the end
> gives every envelope enough room to overlap its neighbours.
> Each character is lit until the NOTE is over, not for a length
> shared with every other character.
>
> One shared length has to be short enough that the last character to
> start still finishes by the end, and where a syllable split puts
> that character late, it is very short -- so the characters that
> started first went dark long before the word was done being sung. On
> a word split four letters then two, the first letter's light ended a
> third of a second early; on a word whose last syllable opens at four
> fifths of the note, before the halfway mark.
>
> Measured from each character's own start to the same finish instead,
> so an early character simply glows for longer. They still peak in
> order, which is what makes the light travel.

**line 3257** — before `swell = fm.height() * self.RISE * min(1.0, self.v.rise)`

> The per-character swell is AMLL's own fixed amplitude, and `rise`
> may switch it off but not amplify it.
>
> This one does not belong to the knob. The knob moves a WORD, and a
> word moving further is just a word moving further -- it stays one
> shape. This moves the characters of a word against EACH OTHER, so
> turning it up does not make the effect bigger, it makes the word
> come apart: measured on a six-character word at 46px, the spread
> between its first and last character runs 3.7px at rise 1, 6.8px at
> rise 2 and 9.9px at rise 3, against AMLL's own 0.05em, which is
> 3.4px here. Past about four the letters stop reading as one word.
>
> So the knob is a gate rather than a multiplier here: 0 turns it off,
> anything above 1 is AMLL's amplitude and no more. The word's own
> float above goes on scaling with it in full, because that one moves
> every character of the word by the same amount and cannot tear it.
> Not doubled for a background line. AMLL floats an ad-lib twice as
> far; this file's own rule is that every word in the window travels
> the SAME distance, whatever type it is set in -- see the note in
> Flow.word_lifts, which measures off the main lyric font for exactly
> this reason. An ad-lib going up twice as far as the line it hangs
> off does not read as emphasis, it reads as a different renderer
> drawing it.

**line 3281** — before `word_k = max((_emp_easing(max(0.0, min(1.0, (pos - (s + o)) / sp)))`

> One scale for the whole word, not one per character.
>
> A character scaled about its own centre grows into its neighbours,
> and the neighbours are close: measured on the lyric face, the INK
> gaps inside a word are 3 to 6 pixels, against the two and a half a
> tenth of extra size adds. Giving each character a slot as wide as
> its own grown advance keeps the ADVANCES right and still merges the
> ink, because the characters are not all growing by the same amount
> at the same moment -- the wave is passing through them. Rendered and
> counted, 41 frames of 73 across one held note had two letters fused
> into one shape.
>
> With a single scale every gap grows by that same factor instead of
> closing, which no arrangement of per-character sizes can promise.
> What is lost is the size wave; what keeps the swell travelling is
> the glow and the float, which are still per character and neither of
> which can push a letter sideways. Taken at the leading edge of the
> wave so the word swells with the first character the voice reaches.

**line 3301** — before `word_scale = 1.0 + word_k * 0.1 * amount * self.SWELL`

> The swell does not change the SIZE of the text, only its light and
> its height.
>
> Growing it is what AMLL does and there is no room for it here.
> Measured on the real window at the settings this runs at, the ink
> gaps inside a word are one to two pixels. Growing the word by a
> tenth moves every letter's edge outward by more than that, and the
> glyphs are re-rasterised onto the pixel grid at the new size, so a
> gap of one pixel does not become a gap of one and a bit -- it
> rounds away. A six-letter word came out as two runs of ink instead
> of six while it was held, and it kept doing it after the spacing was
> made to follow the size, after the kerning was fixed, and with the
> halo turned off entirely, because none of those put a pixel back
> that the grid had taken.
>
> A face with air between its letters would carry it. This one does
> not, and the letters are worth more than the swell: what is left --
> the word lifting and lighting as it is held -- is the part that
> still reads at this size. SWELL is the amount, for a face that can
> afford it.

**line 3332** — before `0.0,`

> No sideways push: emph_plan places the letters, and
> nothing is allowed to move them off that.

**line 3335** — before `up * self.BOB + k * 0.025 * amount * em * self.BOB,`

> ...and no vertical bob either. AMLL floats each
> character as the companion to growing it, so the
> letters ride the swell they are part of. With the
> growing gone -- see SWELL -- a letter rising on its
> own is movement with nothing to explain it: the
> syllables just go up. What the word does instead is
> the float every word gets, from word_lifts, which
> moves all of it together. BOB puts this back for a
> face that can carry the growing too.


## `Amll.word_lifts`

**line 3405** — before `full = self.on_grid(unit * self.RISE * self.v.rise * act * (1.0 - blur))`

> On the pixel grid, for the reason Renderer.on_grid gives: a word
> that has finished floating then sits exactly on a row of pixels and
> draws as glyphs instead of as the little picture lifted_word has to
> make for one still moving. Without this every word in the column was
> parked a fraction of a pixel off the grid for the whole song, so the
> whole column was permanently resampled -- softer, and paying the
> picture cost on every word of every frame.
> `bg` is deliberately not in this. AMLL floats a background line
> twice as far as a lead one; the stack's own rule, at the top of
> Flow.word_lifts, is that the distance comes off the MAIN lyric font
> so that every word in the window travels the same amount. An ad-lib
> is set at two thirds the size and rising twice as far made it the
> most mobile thing on screen.

**line 3419** — before `out = {}`

> In READING order, whatever order the stamps are in.
>
> They are not always in it. A line with an ad-lib written into it can
> have a word stamped before the word in front of it, because the two
> really are sung across each other -- one such line in this
> collection has its third word starting sixty-five milliseconds
> before its second. Run off the stamps as they stand, the third word
> goes up before the second and the line comes apart: measured over
> that line, a word stood higher than the word before it in 36 frames
> of 111, where the stack managed none.
>
> So the same two rules Renderer.rise_plan and frag_lifts use between
> them: each word's start is held to the one before it on the way
> past, and each word's lift is held down to whatever the word before
> it reached. The eye reads the line forwards, so the rise has to
> travel forwards; what crosses the line is a wave and never a word
> yanked up out of turn. Held across the whole LINE rather than per
> row, because the head of row two is the next thing after the tail of
> row one.


## `Amll.paint`

**line 3462** — before `if not v.synced:`

> An unsynced document has no clock to follow and nothing to spring
> to. The stack already knows how to print a page of text.
>
> And it moves that page with view.scroll, which makes the whole of
> this renderer's own way of moving the column dead on this path: the
> offset is not read, the springs are not stepped, and `_last_top` is
> about a column that is not being drawn. Dropped rather than left to
> sit, so that a clock arriving later starts from where the words are
> instead of applying a push the reader gave a static page. See wheel.

**line 3480** — before `v.content_h = 0.0`

> Nothing for the window to scroll: the wheel comes here instead, and
> what it moves is this renderer's own offset. See Amll.wheel, and
> Renderer.wheel for why the window has to be asked at all.

**line 3494** — before `reading = mono() < getattr(v, "user_scroll_until", 0.0)`

> While the reader is reading ahead, the column stops following the
> song. Letting it follow puts the line they are looking at somewhere
> else every few seconds, which is the column being taken back off
> them one line at a time rather than all at once when the four
> seconds are up. AMLL freezes the same thing for the same reason --
> see its FocusController, which holds the target for the whole of a
> scroll rather than re-deriving it per frame.

**line 3510** — before `self.offset = 0.0`

> Four seconds after the last notch the column is the song's
> again. The offset is dropped whole and the springs carry every
> line home with the stagger running down them, which is AMLL's
> resetScroll: the return is an animation nobody has to write,
> because it is the same one a line change already uses.

**line 3517** — before `v.focus_idx = focal`

> tick() only works this out for a renderer that scrolls, and this one
> does not -- so the renderer that owns the column owes it the answer.
> _paint_line reads it to keep the line being read sharp, and so do
> the review marks.

**line 3525** — before `base = H * self.ALIGN - plan[focal][1] / 2 - plan[focal][0]`

> Where every line would sit if the springs were already there. The
> focal line's MIDDLE lands on the align position; everything else
> follows from the plan, which is the same prefix sum down the column
> that the stack uses.

**line 3530** — before `self._bounds = (min(0.0, -plan[focal][0]),`

> How far the wheel is allowed to push it, which is AMLL's beginFrame:
> back as far as the top of the document, forward until the last line
> sits in the middle of the window. Worked out every frame because
> both ends move as the song does.

**line 3539** — before `stride = plan[focal][1] * 2.0`

> The stagger is safe in ONE direction, and only over a short move.
>
> It works by letting the top of the column set off before the bottom
> of it. Which way the column is going therefore decides whether that
> is a wave or a collision:
>
>   * moving UP -- the song advancing to the next line, which is
>     almost every move there is -- the line that sets off first moves
>     AWAY from the one under it. The gaps stretch and close again.
>     Nothing can touch anything.
>   * moving DOWN -- seeking back, clicking a line above, scrolling
>     back, coming home from a scroll -- the line that sets off first
>     moves straight at the one under it, which is still waiting its
>     turn. It arrives on top of it, and stays there until the wave
>     reaches the bottom of the window.
>
> Enumerating the causes was the wrong way round and kept missing
> them: a click that seeks forward by less than a second read as
> ordinary playback and got the stagger anyway. The direction is the
> property that actually matters, and it does not need to know why the
> column is moving.
>
> The distance is the other half. A move of about one line is what the
> wave is for; a click ten lines up covers ten times that, and with a
> stagger under it the top of the column is most of a window away from
> the bottom before the bottom has moved at all. So: up, and no
> further than the step a line change actually takes -- one line, or
> two where the step carries over an ad-lib.
>
> AMLL arrives at the same place from the other end, by naming the
> scenarios: DiscreteScroll, ContinuousScroll, InteractionStart and
> Seek all set disableStagger.

**line 3579** — before `small = 1.0 + (self.SCALE - 1.0) * (1.0 - v.browse)`

> What an un-sung line is aimed at, which is not always SCALE. A hand
> on the wheel takes the whole column back to full size, and it is the
> same reason the blur lets go of it (see `browse` in tick, and the
> note by the review marks' distance fade): somebody scrolling is
> READING the column rather than listening to it, and every line they
> are reading wants to be the size the document was set in and drawn
> without a transform over it. The depth cue is for a column being
> sung past, and it comes back as soon as the hand does.

**line 3594** — before `sp.set_target(y)`

> The line being sung when a document lands is already the one
> being read -- it flies in with the rest, but it is not given
> the wait, so the words are legible while the column settles.

**line 3608** — before `if y + entry[1] >= 0:`

> Only the lines from the top of the window down are given a wait:
> a line that is already above the viewport has nothing to show for
> having set off late, and counting it would spend the whole
> stagger before the wave reached anything visible.

**line 3617** — before `m = H if (v.zero_g > 0 or v.clouds > 0) else 40`

> From here down this is the stack's own frame loop, against spring
> positions instead of a scrolled plan. See Flow.paint.

**line 3624** — before `rects.append((i, y + v.scroll, h, x0 + lo, x0 + hi))`

> In content space, which for a renderer that pins its scroll is
> the same space -- added back the moment it is taken off, so the
> contract holds if that ever stops being true.


## `Pinned`

**line 3677** — before `ADLIB_GAP = 0.22`

> The air between a line and the first of the ad-libs under it, in lines
> of the type they are set in.


## `Pinned.__init__`

**line 3685** — before `self._page = None`

> The stack, built only if a document with no clock turns up. See
> static_page.


## `Pinned`

**line 3752** — before `def _index(self):`

> -- ad-libs, and the lines they hang off ----------------------------


## `Pinned.current`

**line 3848** — before `cur = next((i for i in live if not self.v.lines[i].get("background")),`

> No line to read on to -- a document of nothing but ad-libs, or
> one whose only singable lines are backing vocals.


## `Pinned.draw_row`

**line 3924** — before `lift = lifts.get(f_i, 0.0)`

> Neither the lift nor the pop goes on the painter: lifted_word
> places the word, because a translation is the one thing Qt
> rounds to a whole pixel. See Renderer.lifted_word.


## `Spotlight`

**line 4036** — before `FADE = 0.22`

> Long enough to read as a dissolve rather than a cut, short enough that
> the two lines are never both legible at once.


## `Spotlight.animating`

**line 4071** — before `return bool(self.gone)`

> The window eases activations and repaints while they move; this fade
> is quicker than they are and has to ask for its own frames.


## `Spotlight.paint`

**line 4077** — before `if self.static_page(p, x0, width, H):`

> No clock, no voice to follow: the page is printed instead, by the
> stack, which also leaves it somewhere the wheel can move. See
> Pinned.static_page.

**line 4094** — before `for i in sorted(out, key=lambda k: out[k]) + ([] if cur is None else [cur]):`

> Faintest first, and the line being sung last of all, so it is drawn
> over whatever it is replacing rather than under it.

**line 4115** — before `foot += self.draw_adlibs(p, cur, live, small, fm_sm, x0, width, foot,`

> The backing vocals of the line being sung, hung off the bottom of it
> at the size the neighbours are set in. They are part of this line, so
> the line coming next is pushed below them.


## `Karaoke`

**line 4161** — on `    LEAD = 2.0`

> seconds of run-up the bar shows


## `Karaoke.paint`

**line 4165** — before `if self.static_page(p, x0, width, H):`

> No clock, no voice to follow: the page is printed instead, by the
> stack, which also leaves it somewhere the wheel can move. See
> Pinned.static_page.

**line 4180** — before `slots: dict[int, int] = {}`

> Who is in which band. Every line SOUNDING that takes a band takes
> the one its own place in the document gives it, and the line coming
> takes whichever band is left over -- if two voices are already using
> both, the line coming next IS one of them and nothing is being held
> back. Sounding, and not "the line an ad-lib belongs to": reaching
> back from a live ad-lib would put a line whose own words finished a
> bar ago into the pair, and put it there dressed as the line coming
> next, which is the last thing it is.

**line 4194** — before `band = fm.height() * 2.6`

> Two bands of a fixed height, so the pair can never reach each other
> however many rows either line wraps to -- a slot whose position came
> out of its own line's height is a slot that moves, and the point of
> the alternation is that neither of them does.
>
> A block too tall for its band grows AWAY from the divider between
> them rather than out of the middle in both directions. Growing both
> ways was survivable while a band held one line of two or three rows;
> a line with its ad-libs under it is regularly taller than that, and
> what came of two of those was the second voice of one band printed
> through the first row of the other.

**line 4206** — on `        low = H * 0.5`

> top of the lower of the two

**line 4207** — on `        divide = fm.height() * 0.35`

> the closest either comes to it

**line 4222** — before `alpha = (0.18 + 0.14 * self.run_up(ln, pos)) if coming else 0.34`

> The line coming brightens as it approaches, which is the whole
> of what tells the pair apart: two lines set the same size, one
> of them lit and one of them coming up.

**line 4228** — before `self.mark(i, top, own, x0, width)`

> Its own rows, not the whole block: what is under it belongs to
> the ad-libs, and each of them publishes a box of its own to be
> clicked on.


## `Word.paint`

**line 4311** — before `if self.static_page(p, x0, width, H):`

> No clock, no voice to follow: the page is printed instead, by the
> stack, which also leaves it somewhere the wheel can move. See
> Pinned.static_page.

**line 4333** — before `p.setFont(self.font(v.lyric_px() * 1.1))`

> Nothing to pick from: the whole line, centred.

**line 4342** — before `subs = []`

> The ad-libs of this line that are sounding, and what each of them is
> saying. Whichever of them opened first stands in for the line itself
> while the line has not been sung into yet: an ad-lib that comes in
> ahead of its lead is what the song is doing, and the middle of the
> window is for what the song is doing.

**line 4352** — before `got = self.pick(said, pos) or (said[0] if said else None)`

> Its first word until it has sung one, the same fallback the line
> itself gets: a voice that is sounding has something to show even
> in the breath before its first word.

**line 4360** — before `of, big = subs.pop(0)`

> The line has not been sung into yet and something backing it
> has: that is what the song is doing, so it takes the middle
> rather than being printed under a word nobody has sung.

**line 4367** — before `mid = H * 0.46 if not subs else H * 0.42`

> The big word sits a little high when something is written under it,
> so the pair is centred on the window rather than the lead alone.


## `Cards`

**line 4404** — on `    INSET = 0.10`

> of the column, per side, for an ad-lib card


## `Cards.paint`

**line 4435** — before `still = not v.synced`

> A document with no clock. Nothing on it is being sung and nothing is
> waiting its turn, which is the whole of what `act` separates -- so
> every card is drawn as the present one rather than as the un-sung
> one. It was the un-sung one: a card nobody is on keeps its words at
> a third of a fade that is itself down at 0.38, which on a timed song
> is a depth cue and on a page of untimed lyrics is a sheet of frosted
> glass over the whole document.
>
> `act` itself is left alone and stays 0. It is also what the rise and
> the fill read, and there is no time on this document for either of
> them to happen at -- what is wanted is a page that can be read, not
> a page pretending to be sung. Compare base_color, which refuses the
> duet tint on a static document for the same reason.

**line 4461** — before `dist = v.vfade(y + h / 2)`

> Faded by distance from the focus band as well as by whether
> it is being sung, the way the stack fades its own column: a
> scrolling renderer that did not would slice the card at the
> top of the window off at full strength. The card itself goes
> with its words -- a panel left behind by the text that was on
> it is a blank card floating at the edge of the window.

**line 4474** — before `p.save()`

> Saved around the panel for the reason _paint_dots is:
> the window hands one painter to everything it draws, and
> this used to hand it back with NoPen and NoBrush on it
> after EVERY frame, not only over an interlude.

**line 4484** — before `self.draw_block(p, ln, rows, f, cx + pad, cw - pad * 2,`

> 0.34 is what an un-sung card's words are worth under
> the sung fill that is coming for them. With no clock
> nothing is coming, so there is no layer to leave room
> for and the words go on at the strength the stack gives
> a static page.
