"""How the lyric column is drawn.

The window paints every pixel itself, and until now it painted the lyrics
exactly one way: a scrolling stack of same-size lines, depth carried by opacity
and distance blur rather than by size, the line being sung filling
syllable-by-syllable. That is `Flow`, and it is still the default -- everything
here started as `LyricsView._paint_lines` and its helpers, moved out unchanged
so that the other ways of showing the same lines are its siblings rather than
special cases inside it.

A renderer owns the lyric column and nothing else. The background, the cover
panel, the header, the overlays and every menu are the window's, and it draws
them around whatever happens here.

Two things every renderer must leave on the view, because the rest of the
window reads them and there is no default that works:

  view.line_rects   (i, top, h, lo, hi) per line drawn, `top` in content space
                    -- screen y plus view.scroll. tick() aims the scroll at it
                    and line_at() turns a click into a seek. A renderer that
                    pins its lines keeps view.scroll at 0, and then content
                    space and screen space are the same thing -- line_at()
                    subtracts the anchor from both sides, so it needs no help.
  view.content_h    how tall the column came out, for the scroll clamp. Pinned
                    renderers set 0.0.

A renderer is constructed with the view and keeps it as `self.v` for the life
of the window; switching renderers builds a new one.
"""
import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient,
                         QPainter, QPen, QPixmap, QRadialGradient, QRegion,
                         QTransform)

# The two things these painters need from the window's own module. lyrics_gui
# fills them in where it imports this one. A plain `import lyrics_gui` here
# would load a SECOND copy of that module every time the window is started as a
# script -- which is how the .desktop file starts it -- so the dependency is
# handed over instead of reached for.
TEXT = None
_smooth = None

# The rise sets off a little before the syllable does and is over shortly
# after it starts, so a syllable is already moving when it arrives rather
# than setting out once it is being sung. Held notes would otherwise climb
# for as long as they are held -- the rise took the whole of a word's length,
# so a note held four seconds rose for four seconds, which reads as drifting
# rather than as a lift.
#
# The lead was 0.18s, which is a fifth of a second of a word standing up
# before anything is sung: on a line of short words the whole line was in the
# air ahead of the voice. It is a HINT that the word is coming, not an
# announcement, so it is down to the width of one frame or two at the rates
# this draws at -- the movement still starts first, which is all it was for.
#
# It was worth finding out what a wider schedule looks like, and the answer is
# that it looks wrong. Cutting the window from the local word rate so that
# consecutive rises overlap does make the line move more continuously -- about
# half as many frames with nothing moving at all, measured over three
# documents at three tempos -- but what you get for that is two or three words
# off the floor at once, and a word standing up before it is sung reads as the
# line guessing ahead rather than as the voice lifting it. The rise belongs to
# the word being sung. It stays there.
RISE_LEAD = 0.06
RISE_TIME = 0.30

# What float_lifts hands back for a word that has not set off yet: on its
# baseline, at the size it was set in, and at whatever opacity the rest of
# the line is being drawn at -- which is what the None says, since only the
# caller knows whether that is the un-sung falloff or the activation.
STAYING = (0.0, None, 1.0)

# The blurriest a distant line is allowed to get, and so the number of
# pictures one line can ever need. lyrics_gui reads it to know the range to
# look through when it is rationing builds -- see its _nearest_blur.
MAX_BLUR = 9


class Renderer:
    """The contract. See the module docstring for what has to be left behind."""

    name = ""
    # False pins the lines: tick() then leaves view.scroll where it is instead
    # of chasing the line being sung down the column.
    scrolls = True
    # Each word takes the sung colour whole at the moment it starts, rather
    # than the fill sweeping through it. Only the stack has a use for this so
    # far, but the fill is written once, in draw_row, and reads it from here.
    snap = False

    def __init__(self, view) -> None:
        self.v = view

    def paint(self, p, x0: float, width: float, H: int) -> None:
        raise NotImplementedError

    @staticmethod
    def words_of(row):
        """A wrapped row's fragments, grouped back into the words they spell.

        wrap_pieces lays out syllables and drops the flag that said which of
        them belonged together, but it leaves behind the mark that matters:
        the last syllable of a word is the one carrying the trailing space. So
        a word is the run up to and including the next fragment that ends in
        one. A word long enough to have been split across rows comes back as
        one run per row, which is what should happen to it anyway.

        Returns [[(index in row, fragment), ...], ...].
        """
        out, run = [], []
        for k, frag in enumerate(row):
            run.append((k, frag))
            if frag[2].endswith(" "):
                out.append(run)
                run = []
        if run:
            out.append(run)
        return out

    @staticmethod
    def span_of(run):
        """When a word starts and stops, out of the syllables that spell it."""
        starts = [f[3] for _k, f in run if f[3] is not None]
        ends = [f[4] for _k, f in run if f[4] is not None]
        return (min(starts) if starts else None, max(ends) if ends else None)

    def rise_plan(self, rows) -> list:
        """When every fragment in the line sets off, in reading order.

        The schedule, worked out for the line at once rather than read off
        each fragment as it is drawn. Each entry is (row, index in row, when
        the rise starts), and only for the fragments that have ink and a stamp
        -- a space between two words is not a thing that rises.

        What is settled here and cannot be settled a fragment at a time is the
        ORDER. The stamps are not always in it: a line with an ad-lib written
        into it can have its last word starting before its second-to-last,
        because the two really are sung across each other. The eye reads the
        line forwards, so the rise has to travel forwards, and a word yanked
        up out of turn is a picket fence rather than a wave. Each stamp is
        therefore held to the one before it on the way past.
        """
        plan, last = [], None
        for r_i, row in enumerate(rows):
            for f_i, (_x, _w, txt, s, _e) in enumerate(row):
                if s is None or not txt.strip():
                    continue
                last = s if last is None else max(s, last)
                plan.append((r_i, f_i, last - RISE_LEAD))
        return plan

    # Qt blits a pixmap onto whole device pixels while the transform is a
    # plain translation, and resamples it the moment the transform is anything
    # else. This is the smallest thing that is not a translation. It is not a
    # trick to be tidied away: without it the picture lands on a whole pixel
    # and the word steps instead of moving. See lifted_word.
    NUDGE = 1.0 + 1e-7

    def lifted_word(self, p, at, txt: str, lift: float, fm: QFontMetricsF,
                    grow: float = 1.0, cx: float = 0.0, cy: float = 0.0) -> None:
        """drawText, for a word standing between two rows of pixels.

        Qt puts a glyph run on a whole device pixel and nothing moves it off:
        not a scale, not a change of hinting, not asking for outlines. So a
        rise five pixels tall is five jumps however smooth the number driving
        it is -- which is what the raising looked like once the glow was made
        to step along WITH the word instead of sliding against it. The stepping
        was always there; making everything agree is what left it on its own
        to be seen.

        A picture is not treated that way. So the word is drawn into a small
        one at a whole pixel -- under the painter's own font, pen and opacity,
        so a fill gradient falls exactly where it would have -- and then that
        picture is put at the height the word actually is.

        At a whole pixel and unscaled, a blit is the same picture drawText
        would have made, to the last alpha value: measured across a word at
        three sizes, mean difference 0.00 and worst 0. So a word that has
        finished rising drops back to being glyphs with nothing to see at the
        join, and only the one or two words actually in motion ever pay for
        this -- about a twentieth of a millisecond each, against a frame that
        has sixteen.

        `grow` and the centre are the pop, taken here for the same reason: it
        is the same word moving in the same direction, and text under a scale
        snaps exactly as hard.
        """
        y = at.y() - lift
        dpr = self.v.devicePixelRatioF() or 1.0
        on_row = abs(y * dpr - round(y * dpr)) < 0.02
        if grow == 1.0 and on_row:
            p.drawText(QPointF(at.x(), round(y * dpr) / dpr), txt)
            return
        # Room for what hangs outside the advance -- a "j" reaches left of its
        # origin, an "f" past the end of it -- and for the resample to have
        # something to reach into rather than a hard edge.
        m = max(3.0, fm.height() * 0.22)
        ox = math.floor((at.x() - m) * dpr) / dpr
        oy = math.floor((at.y() - fm.ascent() - m) * dpr) / dpr
        pw = int(math.ceil((fm.horizontalAdvance(txt) + m * 2) * dpr)) + 2
        ph = int(math.ceil((fm.height() + m * 2) * dpr)) + 2
        if pw <= 0 or ph <= 0:
            p.drawText(QPointF(at.x(), y), txt)
            return
        pm = QPixmap(pw, ph)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pp.translate(-ox, -oy)
        pp.setFont(p.font())
        pp.setPen(p.pen())
        pp.drawText(at, txt)
        pp.end()
        p.save()
        if grow != 1.0:
            p.translate(cx, cy)
            p.scale(grow, grow)
            p.translate(-cx, -cy)
        else:
            p.setTransform(QTransform(1.0, 0.0, 0.0, self.NUDGE, 0.0, 0.0), True)
        p.drawPixmap(QPointF(ox, oy - lift), pm)
        p.restore()

    def on_grid(self, dy: float) -> float:
        """A vertical distance rounded onto the screen's own pixel grid.

        Used for where a rise ENDS, not for where it is along the way. A word
        that has finished rising sits at a whole pixel and can be drawn as
        plain glyphs, which is both sharper and very much cheaper than the
        picture lifted_word has to make for one still moving -- and since only
        the moving ones need that treatment, there are one or two of them in a
        frame rather than a line's worth.

        Rounding every step of the way instead is what made the raising
        choppy: it is the same five jumps Qt would have imposed anyway, with
        the glow stepping along in time with them so that nothing was left to
        disguise it.
        """
        dpr = self.v.devicePixelRatioF()
        return round(dy * dpr) / dpr if dpr > 0 else round(dy)

    def frag_lifts(self, rows, full: float, pos: float) -> list:
        """How far each fragment has lifted in pixels, one dict per row.

        The plan says when each one sets off; this says how far along it the
        clock has got. Held down to whatever the fragment in front of it
        reached, which is the other half of keeping the line in reading order:
        the plan puts the stamps in order, and this keeps the heights in it.

        The DESTINATION is put on the pixel grid, and the travel to it is
        left alone. So a word at rest sits exactly on a row of pixels and is
        drawn as glyphs, and a word in motion is somewhere between two of
        them and is drawn as a picture -- see lifted_word. Every layer reads
        this one number, so the base text, the fill over it, the glow behind
        it and any reading above it cannot disagree about where the word is.
        """
        full = self.on_grid(full)
        out = [{} for _ in rows]
        cap = 1.0
        for r_i, f_i, off in self.rise_plan(rows):
            cap = k = min(cap, _smooth((pos - off) / RISE_TIME))
            lift = k * full
            if lift > 0.01:
                out[r_i][f_i] = lift
        return out

    def _paint_dots(self, p, ln, fm, ox, y, pos, act, alpha, width,
                    align: str | None = None, flights=None) -> None:
        """Instrumental break, the way Apple Music shows it: three dots that
        fill across the gap so a 40-second solo is not just dead air.

        `align` is for the renderers that set their own: the stack follows the
        window's alignment setting, but one that centres every line it draws
        would otherwise leave the dots hanging off to the left of it.

        `flights` is one (lift, opacity left, how much bigger) per dot, or
        None per dot for one still sitting in its place -- the float troll,
        handed in rather than asked for here, because it belongs to the stack
        and this is drawn by every renderer there is. See Flow.dot_flights.
        """
        r = fm.height() * 0.19
        gap = r * 3.4
        span = max(1e-6, ln["end"] - ln["start"])
        t = max(0.0, min(1.0, (pos - ln["start"]) / span))
        run = gap * 2
        slack = {"left": 0.0, "center": (width - run) / 2, "right": width - run - r}
        cx = ox + r + slack[align or self.v.line_align(ln)]
        cy = y + fm.height() * 0.55
        now = time.monotonic()
        cue = max(0.0, (t - 0.88) / 0.12) if t > 0.88 else 0.0
        p.setPen(Qt.PenStyle.NoPen)
        e = self.v.beat_energy()
        for k in range(3):
            lift, left, big = (flights[k] if flights else None) or STAYING
            if left is not None and left <= 0.01:
                continue                        # this one has gone
            fill = max(0.0, min(1.0, t * 3 - k))
            if e > 0.004:
                breathe = 1.0 + 0.34 * e * act
            else:
                breathe = 1.0 + 0.10 * math.sin(now * 2.4 + k * 0.8) * act
            rad = r * (0.62 + 0.40 * fill + 0.25 * cue) * breathe * big
            a = alpha * (0.22 + 0.78 * fill) * (0.30 + 0.70 * act)
            if left is not None:
                a *= left
            p.setBrush(QColor(234, 234, 234, int(255 * max(0.0, min(1.0, a)))))
            p.drawEllipse(QPointF(cx + k * gap, cy - lift), rad, rad)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def animating(self) -> bool:
        """True while there is motion of the renderer's own still to draw.

        tick() stops repainting an idle window, and it cannot see motion that
        lives in here rather than in the scroll or the activations.
        """
        return False


class Flow(Renderer):
    """The scrolling stack: the window's own look, and the default.

    Lines are all one size. Distance from the line being sung is carried by
    opacity and by a blur that is baked into a cached pixmap per line, so the
    only text drawn live is the line actually being sung.
    """

    name = "flow"

    def __init__(self, view) -> None:
        super().__init__(view)
        # What `rects` last handed back, and what it was built for.
        self._rk = self._rects = None
        self._rtop = self._rx0 = None
        # Which line _warm_next is building ahead for, and whether it has
        # finished. See _warm_next.
        self._warm_at: int | None = None
        self._warm_done = False

    def plan(self, width: float):
        """Every line's place down the column, worked out once for the document.

        Nothing in here answers to the clock or to the scroll. How tall a line
        is, the air under it, and the ink it covers left to right are decided
        by the words and the size they are set at -- so the whole column is
        one list, and a frame reads it instead of building it.

        It used to be built on every frame, and the whole document's worth:
        the loop needs each line's height to know where the next one goes, so
        there was no way to ask about the nine lines the window can show
        without laying out all hundred and thirty first. That is the cost the
        layout cache never covered, because a cache hit per line per frame is
        still a hundred and thirty lookups per frame.

        Kept in the WINDOW's cache rather than one of this renderer's own, so
        that everything which already empties that -- a new lyric, a new font,
        a new size, a resize -- empties this too. `line_spacing` is in the key
        as well because it moves the lines without changing one of them.

        The two offsets are RELATIVE for the same reason. `off` is measured
        from the top of the column and `lo`/`hi` from x0, and neither the
        anchor nor the art panel changes a thing about how the words are laid
        out -- so the panel can slide and the window can be dragged taller
        without throwing the column away and wrapping it all again.
        """
        v = self.v
        key = ("flowplan", int(width), int(v.lyric_px()), v.align, v.roman,
               v.furigana, v.line_spacing)
        hit = v.layout_cache.get(key)
        if hit is not None:
            return hit
        out: list[tuple] = []
        off = 0.0
        n = len(v.lines)
        for i, ln in enumerate(v.lines):
            rows, fm, h, rrows, rfm, ruby, rufm = v.layout_line(i, width)
            ox = v.line_ox(ln, fm, 0.0)
            grab = fm.height() * 0.45
            if ln.get("credits"):
                lo = hi = ox
            elif ln.get("dots"):
                span = fm.height() * 0.19 * 3.4 * 2
                lo, hi = ox - grab, ox + span + grab
            else:
                ink = [(r[0][0], r[-1][0] + r[-1][1]) for r in rows if r]
                lo = ox + min(a for a, _ in ink) - grab if ink else ox
                hi = ox + max(b for _, b in ink) + grab if ink else ox
            nxt_bg = i + 1 < n and v.lines[i + 1]["background"]
            gap = fm.height() * (0.16 if (ln["background"] or nxt_bg) else 0.42)
            out.append((off, h, lo, hi, rows, fm, rrows, rfm, ruby, rufm))
            off += h + gap * v.line_spacing
        plan = (out, off)
        v.layout_cache[key] = plan
        return plan

    def rects(self, plan, top: float, x0: float):
        """line_rects for the column, which moves only when the window does.

        The list is in CONTENT space -- the scroll is added back the moment it
        is taken off -- so the one thing that changes every frame is the one
        thing it does not depend on. It is rebuilt when the anchor or x0 move,
        and otherwise handed back as it stands. Held by identity rather than
        by a key so that a plan thrown away takes its rectangles with it.
        """
        if (self._rk is not plan or self._rtop != top or self._rx0 != x0):
            self._rk, self._rtop, self._rx0 = plan, top, x0
            self._rects = [(i, top + off, h, x0 + lo, x0 + hi)
                           for i, (off, h, lo, hi, *_r) in enumerate(plan)]
        return self._rects

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        pos = v.position() - v.track_offset()
        live = v.sounding(pos) if v.synced else []
        top = v.anchor()
        plan, total = self.plan(width)
        v.line_rects = self.rects(plan, top, x0)
        v.content_h = total
        base = top - v.scroll
        # One margin and one cloud test for the frame, not one of each per line.
        m = H if (v.zero_g > 0 or v.clouds > 0) else 40
        clouds = v.clouds > 0
        lo_y, hi_y = -m - base, H + m - base
        deferred: list[tuple] = []
        for i, (off, h, _lo, _hi, rows, fm, rrows, rfm, ruby, rufm) in enumerate(plan):
            if off >= hi_y or off + h <= lo_y:
                continue
            if clouds and live and min(abs(i - j) for j in live) > 3:
                continue
            ln = v.lines[i]
            args = (i, ln, rows, fm, x0, base + off, pos, live,
                    rrows, rfm, ruby, rufm)
            if clouds and (i in live or v.activation.get(i, 0.0) > 0.02):
                deferred.append(args)
            else:
                self._paint_line(p, *args)
        for args in deferred:
            self._paint_line(p, *args)
        self._warm_next(plan, live, width)

    # How far from the line being sung a picture is still worth building
    # ahead. Beyond this the blur has saturated -- 1.4 * 4**1.35 is already
    # over MAX_BLUR -- so every line out here shares one level and has had it
    # since the last switch. Nothing to warm.
    WARM_REACH = 5

    def _warm_next(self, plan, live, width: float) -> None:
        """On a frame with ration to spare, build what the NEXT switch wants.

        A line's blur is how far it is from the line being sung, so a switch
        moves every line in the column to a new level and each level is its
        own picture -- six to eleven of them on the frame it lands, against a
        ration of two. PIX_PER_FRAME exists to spread that over the frames
        after, which works and is invisible, but it is paying for the burst
        once it has already happened.

        The burst is predictable a whole line ahead. `blur` is base(dist)
        scaled by (1 - act), and act is zero on every line but the one going
        out and the one coming in -- so for all the rest, next line's picture
        is this line's arithmetic with dist measured from one further down.
        The two that are easing are left to the ration exactly as now: they
        sweep through levels gradually and there is nothing to precompute.

        This costs nothing where there is nothing to do. The ration goes
        unspent on the great majority of frames -- 2374 of 2400 over a warm
        sweep of "NF - Time" -- and a pass that builds nothing sets _warm_done
        and is not run again until the line changes.
        """
        v = self.v
        if (v._pix_left <= 0 or not live or v.clouds > 0 or v.zero_g > 0
                or not v.lines):
            return
        here = v.focus_idx if v.focus_idx is not None and v.focus_idx >= 0 \
            else min(live)
        nf = here + 1
        if nf >= len(plan):
            return
        if nf == self._warm_at:
            if self._warm_done:
                return
        else:
            self._warm_at, self._warm_done = nf, False
        had = v._pix_left
        scale = v.blur_scale * (1.0 - v.browse)
        for i in range(max(0, nf - self.WARM_REACH),
                       min(len(plan), nf + self.WARM_REACH + 1)):
            if v._pix_left <= 0:
                return          # more to do; come back next frame
            # Only the rows _paint_line actually BLITS. It hands a credits
            # block to _paint_credits and an interlude to _paint_dots, both
            # before the pixmap path, and neither of them has a picture --
            # layout_line gives a credits row (n, text) pairs rather than the
            # (x, advance, text, start, end) line_pixmap unpacks, and gives an
            # interlude no rows at all. Asking for one raised straight out of
            # paintEvent, which loses the whole frame AFTER the lyrics: the
            # art panel, the toast and any overlay simply never got drawn.
            ln = v.lines[i]
            if ln.get("credits") or ln.get("dots"):
                continue
            dist = abs(i - nf)
            # The same window _paint_line draws, so nothing is built for a
            # line that will not be on screen to want it.
            if v.focus and dist > v.focus + 1:
                continue
            blur = 0.0 if dist == 0 else min(float(MAX_BLUR), 1.4 * dist ** 1.35)
            blur *= scale
            lo = int(blur)
            v.line_pixmap(i, width, lo)
            if v._pix_left > 0 and blur - lo > 0.01:
                v.line_pixmap(i, width, lo + 1)
        # The loop ran to the end, so every line in range was asked for and
        # there is nothing to come back for. The one thing that can still be
        # outstanding is the second level on the very last line, skipped
        # because the ration ran out exactly there -- which reads as no ration
        # left and something built, and is the one case that runs again.
        self._warm_done = v._pix_left > 0 or v._pix_left == had

    def spin_frag(self, rows, fm, ox: float, y: float, ruh: float, pos: float):
        """The word being sung right now, and the box it occupies.

        Only one at a time: whichever fragment the clock is inside. Returns
        (row, x, box) so the base layer can be cut around it and the overlay can
        turn it about the same centre.
        """
        if self.v.spin <= 0:
            return None
        for r_i, row in enumerate(rows):
            for x, w, txt, s, e in row:
                if s is None or e is None or not (s <= pos < e) or not txt.strip():
                    continue
                ry = y + ruh + fm.ascent() + r_i * (fm.height() * 1.06 + ruh)
                box = QRectF(ox + x - 2, ry - fm.ascent() - ruh - 2,
                             w + 4, fm.height() + ruh + 4)
                return (r_i, x, box)
        return None

    def float_span(self) -> float:
        """How long one flight lasts, from letting go to gone."""
        return 1.0 / max(0.25, self.v.float_up)

    def float_of(self, at, pos: float):
        """Where a word that set off at `at` has got to, and what is left of it.

        Returns (lift in pixels, the opacity it has left, how much bigger it is
        being drawn), or None for a note the clock has not reached -- which is
        everything still to be sung, so the ordinary path pays one comparison
        for this.

        Driven by the CLOCK and not by the wall, which is what makes it agree
        with itself: a syllable dragged back under the playhead comes back with
        everything else, a pause holds a half-gone word exactly where it had
        got to, and the same second of the song looks the same twice. The
        cloud drift is entitled to the wall because it is weather -- it says
        nothing about where the song is -- and this says exactly that.
        """
        if at is None or pos <= at:
            return None
        # Clamped rather than short-circuited at the far end, so what comes
        # back never goes backwards: a word long gone reads as all the way up
        # with nothing left, and not as back on its baseline. Nothing draws it
        # either way -- the caller is gone at zero -- but a lift that falls to
        # zero at the end of the flight is a trap for the next thing that asks.
        t = min(1.0, (pos - at) / self.float_span())
        # It goes faster the higher it gets, and it is transparent long before
        # it is far: at half gone it has travelled a third of the distance,
        # which is what letting go of something looks like from underneath --
        # a thing that is thrown starts fast and slows, and this does not.
        #
        # The distance is measured off the MAIN lyric font rather than the
        # line's own, the way word_lifts measures the rise, so an ad-lib set
        # at two thirds the size does not float two thirds as far.
        #
        # And it grows on the way, on the same curve as the climb, so that the
        # word reads as coming AT the reader rather than receding: a thing
        # going away gets smaller, and a word that shrank as it faded would be
        # leaving through the back of the window instead of over your head.
        # Half faded it is half again as big, which is as far as this can go
        # before a word passing the line above it is wearing it.
        unit = self.v.lyric_fm(False).height()
        return (unit * 9.0 * t ** 1.6, 1.0 - _smooth(t), 1.0 + 1.5 * t ** 1.6)

    # How far apart the three dots let go, as a share of one flight. A third
    # of a flight: enough that they leave in a countable order rather than as
    # one object coming apart, and not so much that the first one is halfway
    # up the window before the last has moved.
    DOT_STAGGER = 0.34

    def dot_flights(self, ln, pos: float):
        """Where each of the three dots of an interlude has got to, or None.

        The dots are a countdown rather than a lyric, so they do not leave one
        at a time across the whole of a break the way syllables leave across a
        line: a dot let go at the third of a forty-second solo would be gone
        for half a minute of nothing, and what is left behind is a countdown
        with no numerals in it. They leave at the END, one after another, the
        last of them landing exactly as the words come back -- so the break
        finishes on an empty window and the line arrives into it.

        Handed to _paint_dots, which is on the base class and is drawn by the
        pinned renderers too. Like every other troll this one belongs to the
        stack, and a renderer that never asks for this never gets it.
        """
        if self.v.float_up <= 0 or ln.get("end") is None:
            return None
        span = self.float_span()
        # The last dot's flight ends on the line's first word; the ones before
        # it set off a stagger earlier each, and none of them before the break
        # itself has started -- a gap shorter than the whole departure lets
        # them all go at once rather than going back in time to do it.
        start = ln.get("start")
        out = []
        for k in range(3):
            at = ln["end"] - span * (1.0 + (2 - k) * self.DOT_STAGGER)
            out.append(self.float_of(at if start is None else max(start, at),
                                     pos))
        return out

    def float_lifts(self, rows, rrows, ln, pos: float) -> dict:
        """Every fragment already on its way out, keyed (romaji?, row, index).

        One flight per SYLLABLE, and each one sets off the moment that syllable
        is SUNG rather than when its note is over, so the word leaves while the
        voice is still on it -- the fill sweeps across it on the way up and the
        halo goes with it. That is the whole of the effect: the line comes
        apart in the order it is being sung, the front of it already up the
        window while the last word is still being held.

        A line-timed document has one fragment to a line and so the line goes
        up as a slab, which is the only thing it can be given -- there is
        nothing in it that says when one word started and the next one did.

        Keyed the way `lifted` is, because it lands in the same places: the
        base text, the fill drawn over it, the halo, and the reading sitting
        above a kanji, all of which have to agree to the pixel about where the
        word IS.
        """
        if self.v.float_up <= 0:
            return {}
        start = ln.get("start")
        out = {}
        for is_rom, rws in ((False, rows), (True, rrows or ())):
            for r_i, row in enumerate(rws):
                for f_i, (_x, _w, _txt, s, _e) in enumerate(row):
                    # A fragment with no clock of its own leaves with the line
                    # it is part of, rather than sitting there for ever after
                    # everything round it has gone.
                    flight = self.float_of(s if s is not None else start, pos)
                    if flight is not None:
                        out[(is_rom, r_i, f_i)] = flight
        return out

    @staticmethod
    def glow_of(core: str, fm: QFontMetricsF, held: float):
        """How wide and how bright the halo on one word is.

        Returns (blur radius in pixels, strength 0..1), and both of them
        answer to the word's LENGTH -- which is measured the way the eye
        measures it, as the width the word was drawn at, in line-heights.
        Counting characters is a poor stand-in for that in a proportional font
        ("ill" and "WOW" are both three of them) and a worse one for a script
        that spells a whole word in a single glyph.

        Length goes mostly into how far the light CARRIES. Lit from behind, a
        long word throws a broad soft halo and a short one a tight bright
        spark; blurring both by the same few pixels made the short one a blob
        with a letter somewhere in it and left the long one wearing a thin
        outline. The radius ran 2..10 pixels across the whole range of words
        before, which is barely a range at all, and it ran in PIXELS -- so the
        halo shrank back into the letters every time the type was made bigger.
        It is a fraction of the line height now, and the type takes it along.

        It goes only a little into how BRIGHT the word is. A long word is
        already putting out more light by having more ink in it, and paying it
        for its length a second time blows the line out.

        `held` is how long the note is, which is the other half of both: a
        word gone by in a sixteenth has no time to light up.
        """
        span = fm.horizontalAdvance(core) / max(1.0, fm.height())
        lenf = min(1.0, max(0.0, (span - 0.35) / 3.4))
        radius = max(1, min(26, round(
            fm.height() * (0.055 + 0.13 * lenf) * (0.45 + 0.55 * held))))
        return radius, held * (0.62 + 0.38 * lenf)

    @staticmethod
    def frag_under(row, cx: float):
        """Which fragment of a row a reading is sitting over, or None.

        Furigana is placed by its centre rather than by an index, so the only
        way to ask what it belongs to is to ask what is underneath it.
        """
        for f_i, (x, w, _t, _s, _e) in enumerate(row):
            if x <= cx < x + w:
                return f_i
        return None

    def ruby_lift(self, row, lifted: dict, r_i: int, cx: float) -> float:
        """The lift of the fragment a reading is sitting over.

        A reading left on the baseline while the kanji climbs out from under
        it is the same detachment as a glow left behind in the hole.
        """
        f_i = self.frag_under(row, cx)
        return 0.0 if f_i is None else lifted.get((r_i, f_i), 0.0)

    def word_lifts(self, rows, fm: QFontMetricsF, pos: float, act: float,
                   blur: float) -> dict:
        """How far each fragment has been lifted, keyed by (row, index in row).

        One lift per SYLLABLE, on a schedule cut for the whole line at once --
        see rise_plan. This used to be one lift per word shared by every
        syllable in it, on the grounds that a word rising a syllable at a time
        tears in half. It does not stay torn: the next syllable is already on
        its way up before the last has settled, so what the eye gets is not a
        seam but a wave travelling through the word at the speed it is sung.

        The distance is measured off the MAIN lyric font, not off the line's
        own. An ad-lib is set at two thirds the size, and scaling its rise with
        its type made it go up by two thirds of the amount -- which is not what
        an amount is. Every word in the window now travels the same distance.

        Faded out against the depth blur rather than stopped dead, so a line
        that has just been passed settles back onto its baseline instead of
        dropping the moment the clock leaves it.
        """
        if self.v.rise <= 0 or act <= 0.01 or blur >= 1.0:
            return {}
        unit = self.v.lyric_fm(False).height()
        full = unit * 0.055 * self.v.rise * act * (1.0 - blur)
        rows_lifts = self.frag_lifts(rows, full, pos)
        return {(r_i, f_i): lift
                for r_i, d in enumerate(rows_lifts) for f_i, lift in d.items()}

    def draw_base(self, p, ln, rows, fm: QFontMetricsF, ox: float, y: float,
                  alpha: float, lifted: dict, rrows, rfm, ruby, rufm,
                  spin, gone: dict) -> None:
        """The line's un-sung text, drawn here instead of blitted from cache.

        Every word in the cached pixmap is on the baseline, so a line with a
        word lifted out of it cannot use one. Cutting the lifted word out of
        the pixmap was the first way this was done and it is not sound: a cut
        is a rectangle, and a neighbouring glyph is entitled to put ink inside
        it. The left arm of a "t" reaches back under the space in front of it,
        and lost that arm every time the word before it finished.

        Only the line being sung ever comes through here -- everything else in
        the column still gets its pixmap -- so this is one line's worth of text
        a frame, on top of the fill that line is already drawing live.

        A word in `gone` is on its way out of the window: it is drawn at the
        height it has got to and at what is left of its opacity, exactly as
        the fill draws its sung half over the top. A word left down here on
        the baseline while its lit self climbs away is the same ghost the spin
        clip used to leave behind.
        """
        p.save()
        p.setPen(self.v.base_color(ln))
        p.setOpacity(alpha)
        font = self.v.lyric_font(ln["background"])
        ruh = self.v.ruby_h(rufm)
        rufont = self.v.ruby_font(ln) if rufm is not None else None
        ry = y + ruh + fm.ascent()
        for r_i, row in enumerate(rows):
            gy = self.on_grid(ry)
            if rufont is not None and r_i < len(ruby):
                p.setFont(rufont)
                by = self.on_grid(gy - fm.ascent() - ruh + rufm.ascent())
                for cx, read, _s, _e in ruby[r_i]:
                    # A reading goes wherever the kanji under it goes, grows
                    # with it and fades with it. See ruby_lift: the same
                    # argument, and the same answer.
                    flew, left, big = gone.get(
                        (False, r_i, self.frag_under(row, cx)), STAYING)
                    if left is not None and left <= 0.01:
                        continue
                    p.setOpacity(alpha if left is None else alpha * left)
                    lift = self.ruby_lift(row, lifted, r_i, cx) + flew
                    self.lifted_word(
                        p, QPointF(ox + cx - rufm.horizontalAdvance(read) / 2, by),
                        read, lift, rufm, big,
                        ox + cx, by - rufm.ascent() * 0.35 - lift)
                p.setOpacity(alpha)
            p.setFont(font)
            for f_i, (x, w, txt, _s, _e) in enumerate(row):
                # The word being spun draws its own base, turned; a second
                # copy sitting still underneath it is the thing the old clip
                # was cutting away.
                if spin is not None and (r_i, x) == (spin[0], spin[1]):
                    continue
                flew, left, big = gone.get((False, r_i, f_i), STAYING)
                if left is not None:
                    if left <= 0.01:
                        continue
                    p.setOpacity(alpha * left)
                lift = lifted.get((r_i, f_i), 0.0) + flew
                # The centre a growing word turns about is where the word
                # actually IS, which is the lift's business: scaling about the
                # baseline it left behind would throw it further up the window
                # the bigger it got. Nothing noticed while the only thing that
                # scaled was the pop, two pixels off its own line.
                self.lifted_word(p, QPointF(ox + x, gy), txt, lift, fm, big,
                                 ox + x + w * 0.5,
                                 gy - fm.ascent() * 0.35 - lift)
                if left is not None:
                    p.setOpacity(alpha)
            ry += fm.height() * 1.06 + ruh
        if rrows and rfm is not None:
            p.setFont(self.v.roman_font(ln))
            ry += fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent()
            for rr_i, row in enumerate(rrows):
                for rf_i, (x, w, txt, _s, _e) in enumerate(row):
                    flew, left, big = gone.get((True, rr_i, rf_i), STAYING)
                    if left is not None:
                        if left <= 0.01:
                            continue
                        p.setOpacity(alpha * left)
                    self.lifted_word(p, QPointF(ox + x, ry), txt, flew, rfm, big,
                                     ox + x + w * 0.5,
                                     ry - rfm.ascent() * 0.35 - flew)
                    if left is not None:
                        p.setOpacity(alpha)
                ry += rfm.height() * 1.04
        p.restore()
        p.setOpacity(1.0)

    def cloud_pixmap(self) -> QPixmap:
        """One soft puff, drawn once and blitted behind every word.

        A radial gradient per word would be dozens of full gradient fills a
        frame -- the same cost that made setOpacity under a transform expensive.
        One pixmap stretched to each word is a plain blit.
        """
        hit = self.v.pix_cache.get("cloud")
        if hit:
            return hit
        R = 384
        pm = QPixmap(R, R)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        lobes = ((0.50, 0.50, 0.44), (0.24, 0.56, 0.34), (0.76, 0.56, 0.34),
                 (0.37, 0.42, 0.30), (0.63, 0.42, 0.30), (0.12, 0.58, 0.22),
                 (0.88, 0.58, 0.22))
        for cx, cy, rr in lobes:
            g = QRadialGradient(R * cx, R * cy, R * rr)
            g.setColorAt(0.0, QColor(255, 255, 255, 96))
            g.setColorAt(0.5, QColor(255, 255, 255, 54))
            g.setColorAt(1.0, QColor(255, 255, 255, 0))
            q.fillRect(0, 0, R, R, QBrush(g))
        q.end()
        self.v.pix_cache["cloud"] = pm
        return pm

    def cloud_of(self, key, W: int, H: int):
        """Drift state for one whole LINE.

        Per word it scrambled the reading order -- each word arrived from its own
        direction and the line landed as a jumble. The cloud is the line: the
        words keep their layout inside it, so it stays readable however far it
        has floated.

        Entry and exit directions come from a hash of the key, so a line keeps
        the same path instead of teleporting when it leaves and comes back.
        """
        st = self.v.cloudy.get(key)
        if st is None:
            n = hash(key)
            a1 = (n % 6283) / 1000.0
            a2 = ((n >> 11) % 6283) / 1000.0
            far = max(W, H) * 1.15
            st = [time.monotonic(),
                  math.cos(a1) * far, math.sin(a1) * far,
                  math.cos(a2) * far, math.sin(a2) * far,
                  (n >> 5) % 628 / 100.0, 0.0, 0.0,
                  (((n >> 17) % 200) / 100.0 - 1.0),
                  (((n >> 23) % 200) / 100.0 - 1.0)]
            self.v.cloudy[key] = st
        st[6] = time.monotonic()
        return st

    def _paint_cloud(self, p, idx, ln, rows, fm, ox, y, pos, act, alpha, dist,
                     x0=0.0, colw=0.0, rrows=(), rfm=None, ruby=(),
                     rufm=None) -> None:
        """Every word adrift in its own cloud.

        It floats in from off-screen as the line arrives, bobs while the line is
        being sung, and floats away again once the line has passed. Like the
        zero-g mode this gives up depth blur and furigana -- there is nowhere for
        a reading to sit above a word that is halfway across the window.
        """
        now = time.monotonic()
        W, H = self.v.width(), self.v.height()
        k = max(0.25, self.v.clouds)
        font = self.v.lyric_font(ln["background"])
        p.setFont(font)
        p.setOpacity(1.0)
        sung = self.v.sung_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ruh = self.v.ruby_h(rufm)
        rowh = fm.height() * 1.06 + ruh
        puff = self.cloud_pixmap()

        blocks = [(rows, fm, y + ruh + fm.ascent(), rowh, font, False)]
        if rrows and rfm is not None:
            ry0 = (y + ruh + fm.ascent() + len(rows) * rowh
                   + fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent())
            blocks.append((rrows, rfm, ry0, rfm.height() * 1.04,
                           self.v.roman_font(ln), True))

        st = self.cloud_of((idx, ln.get("text", "")), W, H)
        span = 3.2 / max(0.4, k)
        if dist > 1 and st[7] == 0.0:
            st[7] = now
        elif dist <= 1:
            st[7] = 0.0
        tin = _smooth(min(1.0, (now - st[0]) / span))
        out = _smooth(min(1.0, (now - st[7]) / span)) if st[7] else 0.0
        if out >= 1.0:
            return

        colw = colw or float(W)
        home_x = st[8] * colw * 0.16
        home_y = (H * 0.42 - y) + st[9] * H * 0.20

        t, ph = now * 0.055 * k, st[5]
        dx = home_x + (math.sin(t + ph) * W * 0.17
                       + math.sin(t * 0.41 + ph * 2.1) * W * 0.06)
        dy = home_y + (math.cos(t * 0.77 + ph * 1.3) * H * 0.11
                       + math.cos(t * 0.29 + ph) * H * 0.04)
        dx = (home_x + st[1]) + (dx - home_x - st[1]) * tin
        dy = (home_y + st[2]) + (dy - home_y - st[2]) * tin
        if out > 0.0:
            dx += (home_x + st[3] - dx) * out
            dy += (home_y + st[4] - dy) * out
        if out <= 0.0 and tin >= 1.0 and not ln.get("dots"):
            ink = [(r[0][0], r[-1][0] + r[-1][1]) for r in rows if r]
            if ink:
                lo_x = ox + min(a2 for a2, _ in ink)
                hi_x = ox + max(b for _, b in ink)
                left = x0 + 8.0
                right = (x0 + colw - 8.0) if colw else (W - 8.0)
                if hi_x - lo_x < right - left:
                    dx = min(max(dx, left - lo_x), right - hi_x)
                else:
                    dx = max(min(dx, left - lo_x), right - hi_x)
                dy = min(max(dy, 8.0 - y), H - 8.0 - (y + fm.height()))

        for rws, met, top, step, fnt, is_rom in blocks:
            p.setFont(fnt)
            mh = met.height()
            for r_i, row in enumerate(rws):
                by = top + r_i * step
                if row:
                    rx0 = ox + row[0][0] + dx
                    rx1 = ox + row[-1][0] + row[-1][1] + dx
                    ry0 = by - met.ascent() + dy
                    a_row = alpha * tin * (1.0 - out)
                    if a_row > 0.01 and rx1 > 0 and rx0 < W and ry0 + mh > 0 and ry0 < H:
                        size = mh * 2.6
                        span = (rx1 - rx0) + mh * 1.4
                        n = max(2, int(span / (size * 0.42)))
                        p.setOpacity(min(1.0, a_row * 1.35))
                        cx0 = rx0 - mh * 0.7
                        for i2 in range(n):
                            f = i2 / max(1, n - 1)
                            bob = math.sin(f * 3.1 + ph * 2.0) * mh * 0.22
                            sc = 0.78 + 0.34 * math.sin(f * 5.3 + ph)
                            sw = size * sc
                            p.drawPixmap(
                                QRectF(cx0 + f * (span - sw),
                                       ry0 + mh * 0.5 - sw * 0.5 + bob, sw, sw),
                                puff, QRectF(puff.rect()))
                        p.setOpacity(1.0)
                for x, w, txt, s, e in row:
                    if not txt.strip():
                        continue
                    cx, cy = ox + x + dx, by - met.ascent() + dy
                    if cx + w < 0 or cx > W or cy + mh < 0 or cy > H:
                        continue
                    a = alpha * tin * (1.0 - out)
                    if a <= 0.01:
                        continue
                    px, py = cx, cy + met.ascent()
                    p.setPen(QColor(TEXT.red(), TEXT.green(), TEXT.blue(),
                                    max(0, min(255, int(a * 255)))))
                    p.drawText(QPointF(px, py), txt)
                    frac = (0.0 if s is None or e is None or pos <= s else
                            (1.0 if pos >= e else (pos - s) / max(1e-6, e - s)))
                    if frac > 0 and act > 0.01:
                        av = max(0, min(255, int(act * (1.0 - out) * tin * 255)))
                        if frac >= 1.0 or self.snap:
                            p.setPen(QColor(sung.red(), sung.green(), sung.blue(), av))
                        else:
                            edge = px + w * frac
                            soft = max(0.75, self.v.edge * mh * 0.22)
                            g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                            g.setColorAt(0.0, QColor(sung.red(), sung.green(),
                                                     sung.blue(), av))
                            g.setColorAt(1.0, clear)
                            p.setPen(QPen(QBrush(g), 0))
                        p.drawText(QPointF(px, py), txt)
        if len(self.v.cloudy) > 400:
            cut = now - 4.0
            for key in [k2 for k2, v in self.v.cloudy.items() if v[6] < cut]:
                self.v.cloudy.pop(key, None)

    def _paint_loose(self, p, idx, ln, rows, fm, ox, y, pos, act, alpha,
                     rrows=(), rfm=None, ruby=(), rufm=None) -> None:
        """One line with every word cut loose from it.

        Each word is drawn on its own, at its resting position plus whatever
        offset the physics has accumulated, turned about its own centre. Two
        things are deliberately given up while this is on: depth blur, because
        blurring per word instead of per line would mean a pixmap per word per
        frame, and the ruby/furigana row, because a reading has nowhere to sit
        once the kanji it belongs to has floated off. Everything else -- the
        sung fill, the activation fade, the viewport falloff -- still applies,
        so the line reads normally apart from being scattered.

        Layout is untouched: `rows` is the same list the normal path uses, so
        wrapping, hit-testing and scrolling all still see the line where it was.
        """
        font = self.v.lyric_font(ln["background"])
        p.setFont(font)
        p.setOpacity(1.0)
        sung = self.v.sung_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ruh = self.v.ruby_h(rufm)
        rowh = fm.height() * 1.06 + ruh

        blocks = [(rows, fm, y + ruh + fm.ascent(), rowh, font, False)]
        if rrows and rfm is not None:
            ry = (y + ruh + fm.ascent() + len(rows) * rowh
                  + fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent())
            blocks.append((rrows, rfm, ry, rfm.height() * 1.04,
                           self.v.roman_font(ln), True))

        W, H = self.v.width(), self.v.height()
        for rws, met, top, step, fnt, is_rom in blocks:
            p.setFont(fnt)
            mh = met.height()
            for r_i, row in enumerate(rws):
                by = top + r_i * step
                for x, w, txt, s, e in row:
                    if not txt.strip():
                        continue
                    key = (idx, is_rom, r_i, round(x, 1), txt)
                    st = self.v.drift_of(key, ox + x, by - met.ascent(),
                                       w, met.height())
                    if st is None:
                        continue
                    px, py = st[0], st[1] + met.ascent()
                    if (px + w < 0 or px > W or py < -mh or py - mh > H):
                        continue
                    p.save()
                    if st[4]:
                        cx, cy = px + w * 0.5, py - met.ascent() * 0.35
                        p.translate(cx, cy)
                        p.rotate(st[4])
                        p.translate(-cx, -cy)
                    p.setPen(QColor(TEXT.red(), TEXT.green(), TEXT.blue(),
                                    max(0, min(255, int(alpha * 255)))))
                    p.drawText(QPointF(px, py), txt)
                    frac = (0.0 if s is None or e is None or pos <= s else
                            (1.0 if pos >= e else (pos - s) / max(1e-6, e - s)))
                    if frac > 0 and act > 0.01:
                        a = max(0, min(255, int(act * 255)))
                        if frac >= 1.0 or self.snap:
                            p.setPen(QColor(sung.red(), sung.green(), sung.blue(), a))
                        else:
                            edge = px + w * frac
                            soft = max(0.75, self.v.edge * met.height() * 0.22)
                            g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                            g.setColorAt(0.0, QColor(sung.red(), sung.green(),
                                                     sung.blue(), a))
                            g.setColorAt(1.0, clear)
                            p.setPen(QPen(QBrush(g), 0))
                        p.drawText(QPointF(px, py), txt)
                    p.restore()

    def _paint_line(self, p, idx, ln, rows, fm, x0, y, pos, live, rrows=(), rfm=None,
                    ruby=(), rufm=None) -> None:
        width = self.v._lyr_width()
        act = self.v.activation.get(idx, 0.0)
        ox = self.v.line_ox(ln, fm, x0)

        if ln.get("credits"):
            self._paint_credits(p, rows, fm, x0, y, width)
            return
        if not self.v.synced:
            p.setOpacity(0.82)
            p.drawPixmap(QPointF(ox - 10, y - 10), self.v.line_pixmap(idx, width, 0))
            p.setOpacity(1.0)
            return

        dist = min((abs(idx - j) for j in live), default=6) if live else 6
        # The line the column has SCROLLED TO counts as near, as well as the
        # line being sung. With `scroll_lead` set -- and it is set by default
        # -- the two are different for the third of a second before a line
        # starts: the column has already moved down to it, so it is sitting at
        # the anchor being read, and it was still being drawn blurred because
        # nobody was singing it yet. Whatever the reader is looking at is
        # what should be sharp.
        peek = self.v.focus_idx
        if peek is not None and peek >= 0:
            dist = min(dist, abs(idx - peek))
        if self.v.focus and live and self.v.browse < 0.5:
            if dist > self.v.focus + 1:
                return
            if dist == self.v.focus + 1:
                act = 0.0
        blur = 0.0 if dist == 0 else min(float(MAX_BLUR), 1.4 * dist**1.35)
        blur *= (1.0 - act) * self.v.blur_scale * (1.0 - self.v.browse)
        falloff = max(0.10, 0.32 - 0.055 * max(0, dist - 1))
        if self.v.focus and live and dist == self.v.focus + 1 and self.v.browse < 0.5:
            falloff *= 0.35
        falloff += (0.60 - falloff) * self.v.browse if falloff < 0.60 else 0.0
        alpha = (falloff + 0.14 * act) * (0.8 if ln["background"] else 1.0)
        if idx == self.v.hover_idx:
            alpha = min(1.0, alpha + 0.22)
        alpha_free = alpha
        alpha *= self.v.vfade(y + fm.height() * 0.5)
        # The line's own entrance: it lands seven pixels low the frame its
        # first word starts and rides the activation back up to where the plan
        # put it. The drop is a STEP -- a line not yet sounding is drawn at its
        # place, and joining `live` moves it -- so what the eye gets is the
        # line being knocked down and recovering, not sliding in from below.
        # That is the effect, and `line_drop` scales it; at 0 the line simply
        # lights up where it already was.
        y = y + (1.0 - act) * 7.0 * self.v.line_drop * (1 if idx in live else 0)

        if ln.get("dots"):
            self._paint_dots(p, ln, fm, ox, y, pos, act,
                             self.v.vfade(y + fm.height() * 0.5), width,
                             None, self.dot_flights(ln, pos))
            return

        lo = int(blur)
        frac_b = blur - lo
        if self.v.clouds > 0:
            self._paint_cloud(p, idx, ln, rows, fm, ox, y, pos, act, alpha_free,
                              dist, x0, width, rrows, rfm, ruby, rufm)
            return
        if self.v.zero_g > 0:
            self._paint_loose(p, idx, ln, rows, fm, ox, y, pos, act, alpha_free,
                              rrows, rfm, ruby, rufm)
            return
        # Troll: every syllable lifts off and fades from the moment the voice
        # reaches it, so a line comes apart in the order it is being sung
        # rather than going up as a slab. What is settled here is only which
        # words have left and how far; draw_base and the fill below put them
        # where that says, between them drawing the un-sung half of a word and
        # the sung half at the same height.
        #
        # Below the clouds and zero-g on purpose. Both of those already have
        # the words off the line and moving on their own account, and two sets
        # of arithmetic arguing over where one word is is not a third effect.
        gone = {}
        if self.v.float_up > 0:
            # Nothing in the line sets off later than the line's own end, so
            # once THAT flight is over every word in it has gone and there is
            # nothing here to draw at all. One comparison to find that out,
            # before the scan below walks the fragments: it is the answer for
            # every line the song has already passed, which by the end of a
            # play is most of the document.
            last = self.float_of(ln.get("end") or ln.get("start"), pos)
            if last is not None and last[1] <= 0.01:
                return
            gone = self.float_lifts(rows, rrows, ln, pos)
        spin = self.spin_frag(rows, fm, ox, y, self.v.ruby_h(rufm), pos)
        lifted = self.word_lifts(rows, fm, pos, act, blur)
        # Whether the line draws its own text is decided by whether the rise
        # can reach it at all, not by whether anything has lifted YET: live
        # text and a blitted pixmap do not rasterise quite alike, and switching
        # between them at the moment the first word sets off puts a visible
        # change of weight in the middle of a line. Switching when the line
        # activates hides it under the fade that is happening anyway.
        #
        # A line with a word in the air cannot use a picture either, and for
        # the same reason the rise cannot: every word in a pixmap is on the
        # baseline. That half is not gated on the activation, unlike the rise
        # -- a line whose last word left as the next line started is still in
        # the air well after its activation has eased away to nothing.
        own_text = (self.v.rise > 0 and act > 0.01 and blur < 1.0) or bool(gone)
        p.save()
        if own_text:
            self.draw_base(p, ln, rows, fm, ox, y, alpha, lifted,
                           rrows, rfm, ruby, rufm, spin, gone)
        else:
            if spin is not None:
                p.setClipRegion(QRegion(self.v.rect())
                                - QRegion(spin[-1].toAlignedRect()))
            p.setOpacity(alpha * (1.0 - frac_b))
            pad = 10 + lo * 6
            p.drawPixmap(QPointF(ox - pad, y - pad),
                         self.v.line_pixmap(idx, width, lo))
            if frac_b > 0.01:
                pad = 10 + (lo + 1) * 6
                p.setOpacity(alpha * frac_b)
                p.drawPixmap(QPointF(ox - pad, y - pad),
                             self.v.line_pixmap(idx, width, lo + 1))
        p.restore()
        p.setOpacity(1.0)

        if act <= 0.01 and not gone:
            return
        p.save()
        font = self.v.lyric_font(ln["background"])
        p.setFont(font)
        sung = self.v.sung_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        now = time.monotonic()
        ruh = self.v.ruby_h(rufm)
        rufont = self.v.ruby_font(ln) if rufm is not None else None
        ry = y + ruh + fm.ascent()
        for r_i, row in enumerate(rows):
            # The same rounding draw_base does, because the fill goes over the
            # text draw_base drew and the two cannot disagree about where the
            # row is. See lifted_word: a baseline on the grid is what lets a
            # word that is not moving be glyphs instead of a picture.
            gy = self.on_grid(ry)
            if rufont is not None and r_i < len(ruby):
                p.setFont(rufont)
                by = self.on_grid(gy - fm.ascent() - ruh + rufm.ascent())
                for cx, read, s, e in ruby[r_i]:
                    if s is None or e is None or pos < s:
                        continue
                    flew, left, big = gone.get(
                        (False, r_i, self.frag_under(row, cx)), STAYING)
                    fade = act if left is None else left
                    if fade <= 0.01:
                        continue
                    p.setPen(sung)
                    p.setOpacity(fade * (1.0 if pos >= e else 0.55))
                    lift = self.ruby_lift(row, lifted, r_i, cx) + flew
                    self.lifted_word(
                        p, QPointF(ox + cx - rufm.horizontalAdvance(read) / 2, by),
                        read, lift, rufm, big,
                        ox + cx, by - rufm.ascent() * 0.35 - lift)
                p.setOpacity(1.0)
                p.setFont(font)
            for f_i, (x, w, txt, s, e) in enumerate(row):
                px = ox + x
                if s is None or e is None:
                    continue
                # How far this word has floated off, and what it is being
                # drawn at: its own remaining opacity if it has left, and the
                # line's activation if it is still in place. A word on its way
                # out is lit at the brightness it was sung at and fades from
                # there -- it does not drop to the un-sung falloff the instant
                # it leaves, which is a flicker in the middle of the line.
                flew, left, big = gone.get((False, r_i, f_i), STAYING)
                fade = act if left is None else left
                if fade <= 0.01:
                    continue
                frac = 1.0 if pos >= e else (0.0 if pos <= s else (pos - s) / max(1e-6, e - s))
                if frac <= 0:
                    continue
                singing = s <= pos < e
                # Both of the vertical moves this fragment is about to make,
                # worked out before anything is drawn: the glow is painted
                # first and has to be put where the word is GOING to be, not
                # where its baseline is. A halo drawn at the baseline sat in
                # the hole a lifted word had just climbed out of -- the word
                # up in the air with its own light left on the floor beneath
                # it, which is the one thing a halo must never do.
                rise = lifted.get((r_i, f_i), 0.0) + flew
                gate = 1.0 if self.v.pop_min <= 0 else min(1.0, (e - s - self.v.pop_min) / 0.2)
                popk = (math.sin(math.pi * frac) * act * gate
                        if self.v.pop > 0 and singing and gate > 0 else 0.0)
                # Left fractional, like the rise: lifted_word places the
                # word where this actually says rather than on the nearest row
                # of pixels, and the glow below is given the very same number,
                # so the halo cannot cross a boundary half a frame before the
                # letters it belongs to.
                poplift = popk * self.v.pop * fm.height() * 0.055
                held = min(1.0, max(0.0, (e - s - 0.18) / 1.1))
                if self.v.glow_scale > 0 and singing and held > 0.02:
                    core = txt.rstrip()
                    radius, strength = self.glow_of(core, fm, held)
                    gp = self.v.glow_pixmap(core, font, radius)
                    swell = math.sin(math.pi * frac) ** 0.7
                    shimmer = 0.86 + 0.14 * math.sin(now * 6.5 + s * 4.0)
                    # `big` as well: a word being sung is also a word on its
                    # way out under the float troll, and a halo that stayed
                    # its own size while the word grew through it would be a
                    # light sitting inside the letters instead of behind them.
                    grow = (1.0 + 0.38 * swell * strength) * big
                    gw, gh = gp.width(), gp.height()
                    pad = radius * 3
                    ccx = px - pad + gw / 2
                    ccy = gy - fm.ascent() - pad + gh / 2 - rise - poplift
                    p.setOpacity(min(1.0, fade * (0.16 + 0.66 * strength)
                                     * swell * shimmer * self.v.glow_scale))
                    p.drawPixmap(
                        QRectF(ccx - gw * grow / 2, ccy - gh * grow / 2,
                               gw * grow, gh * grow),
                        gp, QRectF(gp.rect()),
                    )
                    p.setOpacity(1.0)
                p.save()
                # draw_base has already put this word's un-sung self at the
                # same height; the fill goes over it. Neither of them puts the
                # lift on the painter any more -- lifted_word places the word
                # itself, because a translation is exactly what Qt rounds away.
                wcx, wcy = px + w * 0.5, gy - fm.ascent() * 0.35
                grow = (1.0 + popk * self.v.pop * 0.035 if popk else 1.0) * big
                spun = spin is not None and (r_i, x) == (spin[0], spin[1])
                if spun:
                    # The spun word turns about its own centre, and a rotation
                    # is a transform on the painter whatever else is going on,
                    # so its lift rides along on that rather than through
                    # lifted_word. It is already being resampled.
                    if rise or poplift:
                        p.translate(0.0, -(rise + poplift))
                    if grow != 1.0:
                        p.translate(wcx, wcy)
                        p.scale(grow, grow)
                        p.translate(-wcx, -wcy)
                    p.translate(wcx, wcy)
                    p.rotate(360.0 * self.v.spin * frac)
                    p.translate(-wcx, -wcy)
                    p.setPen(TEXT)
                    p.setOpacity(alpha if left is None else alpha * left)
                    p.drawText(QPointF(px, gy), txt)
                if frac >= 1.0 or self.snap:
                    p.setPen(sung)
                else:
                    edge = px + w * frac
                    soft = max(0.75, self.v.edge * fm.height() * 0.22)
                    g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                    g.setColorAt(0.0, sung)
                    g.setColorAt(1.0, clear)
                    p.setPen(QPen(QBrush(g), 0))
                p.setOpacity(fade)
                if spun:
                    p.drawText(QPointF(px, gy), txt)
                else:
                    # The centre follows the word up. See draw_base, which
                    # draws the un-sung half of this same word at the same
                    # place and has to agree with it to the pixel.
                    self.lifted_word(p, QPointF(px, gy), txt, rise + poplift,
                                     fm, grow, wcx, wcy - rise - poplift)
                p.restore()
            ry += fm.height() * 1.06 + ruh
        if rrows and rfm is not None:
            rfont = self.v.roman_font(ln)
            p.setFont(rfont)
            ry += fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent()
            for rr_i, row in enumerate(rrows):
                for rf_i, (x, w, txt, s, e) in enumerate(row):
                    if s is None or e is None:
                        continue
                    flew, left, big = gone.get((True, rr_i, rf_i), STAYING)
                    fade = act if left is None else left
                    if fade <= 0.01:
                        continue
                    frac = (1.0 if pos >= e else
                            (0.0 if pos <= s else (pos - s) / max(1e-6, e - s)))
                    if frac <= 0:
                        continue
                    px = ox + x
                    if frac >= 1.0 or self.snap:
                        p.setPen(sung)
                    else:
                        edge = px + w * frac
                        soft = max(0.75, self.v.edge * rfm.height() * 0.22)
                        g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                        g.setColorAt(0.0, sung)
                        g.setColorAt(1.0, clear)
                        p.setPen(QPen(QBrush(g), 0))
                    p.setOpacity(fade * 0.85)
                    self.lifted_word(p, QPointF(px, ry), txt, flew, rfm, big,
                                     px + w * 0.5, ry - rfm.ascent() * 0.35 - flew)
                ry += rfm.height() * 1.04
        p.restore()

    def _paint_credits(self, p, rows, fm, x0: float, y: float, width: float) -> None:
        """The footer under the last line. Dim and unanimated -- it is not part
        of the song and should never look like the next thing to be sung.

        `rows` are (which credit, one wrapped line of it). The songwriters are
        the song's own credit and are drawn brighter than the rest, however
        many lines of them there are.
        """
        align = {"center": Qt.AlignmentFlag.AlignHCenter,
                 "right": Qt.AlignmentFlag.AlignRight}.get(
                     self.v.align, Qt.AlignmentFlag.AlignLeft)
        p.save()
        p.setFont(self.v.credit_font())
        ry = y + fm.height() * 1.4
        for part, row in rows:
            p.setPen(QColor(234, 234, 234, 120 if part == 0 else 88))
            p.drawText(QRectF(x0, ry, width, fm.height() * 1.4),
                       int(align | Qt.AlignmentFlag.AlignVCenter), row)
            ry += fm.height() * 1.4
        p.restore()

class Snap(Flow):
    """The stack again, with the fill switched off.

    A word does not fill in as it is held -- it takes the sung colour whole at
    the moment it starts. Everything else about the stack is inherited: the
    blur, the focus band, the pop and the rise, the troll knobs.
    """

    name = "snap"
    snap = True


class Pinned(Renderer):
    """Shared ground for the renderers that do not scroll.

    The stack is a column taller than the window that slides past a focus
    band. These are not: they show one or two lines, in a place they choose,
    and the line being sung changes what is drawn rather than where the window
    is looking. So view.scroll stays at 0 and the wheel does nothing to them.
    (Cards outgrew that and scrolls again -- what it kept is everything below.)

    They also draw every word live. The stack caches an un-sung line as a
    pre-blurred pixmap because it has thirty of them on screen; two lines at a
    size of their own would miss that cache on every frame it mattered.
    """

    scrolls = False
    # The air between a line and the first of the ad-libs under it, in lines
    # of the type they are set in.
    ADLIB_GAP = 0.22

    def __init__(self, view) -> None:
        super().__init__(view)
        self._ikey = None
        self._idx = ({}, {}, [], {})

    def font(self, px: float) -> QFont:
        """The lyric face at a size of this renderer's choosing."""
        return self.v.ui_font(px, QFont.Weight.Black)

    def rows_of(self, ln: dict, fm: QFontMetricsF, width: float,
                align: str = "center"):
        return self.v.wrap_pieces(self.v.line_pieces(ln), fm, width, align)

    def singable(self, i: int) -> bool:
        """A line these renderers have anything to say about.

        The trailing credits block is a paragraph about the document, not a
        line of the song -- the stack has room to put it at the end and these
        do not.
        """
        ln = self.v.lines[i]
        return not ln.get("credits")

    # -- ad-libs, and the lines they hang off ----------------------------
    def _index(self):
        """The document sorted into lines that own a place and lines that do not.

        `group` is the item a line was written in, so a backing vocal and the
        line it belongs to still point at each other after the flattening has
        moved an ad-lib that opens early ahead of its own lead. What comes out
        of that is a HEAD -- a line one of these renderers gives a place of its
        own: every lead line, plus an ad-lib whose lead is missing, which is
        the whole document in a source that is nothing but backing vocals.

        Worked out once per document. A new lyric is a new list rather than an
        edited one, so its identity and length are enough to notice one.
        """
        v = self.v
        key = (id(v.lines), len(v.lines))
        if self._ikey != key:
            lead: dict = {}
            extra: dict = {}
            for i, ln in enumerate(v.lines):
                g = ln.get("group")
                if g is None or not self.singable(i):
                    continue
                if ln.get("background"):
                    extra.setdefault(g, []).append(i)
                else:
                    lead.setdefault(g, i)
            heads = [i for i, ln in enumerate(v.lines)
                     if self.singable(i)
                     and (not ln.get("background")
                          or lead.get(ln.get("group")) is None)]
            self._ikey = key
            self._idx = (lead, extra, heads, {i: k for k, i in enumerate(heads)})
            self.forget()
        return self._idx

    def forget(self) -> None:
        """The document under the renderer has been replaced.

        Anything one of these remembers between frames is remembered as a LINE
        NUMBER, and a line number means nothing once the next song is on: at
        best it is a different line, at worst it is past the end of a shorter
        document. Nothing to do by default; Spotlight has a fade to drop.
        """

    def head_of(self, i: int) -> int:
        """The line an ad-lib hangs off, or the line itself."""
        ln = self.v.lines[i]
        if ln.get("background"):
            return self._index()[0].get(ln.get("group"), i)
        return i

    def adlibs_of(self, i: int) -> list[int]:
        """The backing vocals written into a line, in the order they sound."""
        ln = self.v.lines[i]
        if ln.get("background"):
            return []
        return self._index()[1].get(ln.get("group"), [])

    def rank(self, i: int) -> int:
        """Which head this is, counting from the top of the document.

        Not the line's own index. With an ad-lib between them two lines sung
        one after the other are two apart, and anything alternating on the
        index alone then puts both of them in the same place.
        """
        return self._index()[3].get(i, i)

    def live(self, pos: float) -> list[int]:
        """Every line sounding at `pos` that these renderers can draw."""
        return [i for i in (self.v.sounding(pos) if self.v.synced else [])
                if self.singable(i)]

    def act_of(self, i: int, live) -> float:
        """How much of a line is on: sounding, or easing out of having been."""
        return 1.0 if i in live else self.v.activation.get(i, 0.0)

    def current(self, pos: float):
        """The line to build the frame around, and the head after it.

        The window's own answer to where the song is (see view.focus_line),
        not the first thing sounding. The two differ exactly where a line has
        an ad-lib written into it: the document stretches such a line's end
        over its backing vocal, so it is still "sounding" through the whole
        of the line after it -- and a renderer that drew the first live line
        sat on the finished one and would not move on until the ad-lib let
        go. It also puts a lead line in front of anything backing it, which
        is what these want anyway: an ad-lib is drawn hanging off its line,
        so the line is what the frame is about even when the ad-lib is the
        only part of it sounding yet.
        """
        live = self.live(pos)
        if not live:
            return None, None
        cur = self.v.focus_line(pos)
        if cur < 0 or cur >= len(self.v.lines) or not self.singable(cur):
            # No line to read on to -- a document of nothing but ad-libs, or
            # one whose only singable lines are backing vocals.
            cur = next((i for i in live if not self.v.lines[i].get("background")),
                       None)
            if cur is None:
                cur = self.head_of(live[0])
        return cur, self.after(cur)

    def after(self, cur):
        """The next line that gets a place of its own -- never an ad-lib of
        this one, which is part of the line being sung and not what is next."""
        if cur is None:
            return None
        heads, rank = self._index()[2], self._index()[3]
        k = rank.get(cur)
        if k is None:
            return next((j for j in heads if j > cur), None)
        return heads[k + 1] if k + 1 < len(heads) else None

    def before(self, cur):
        """The line before the one being sung, if there is one to show."""
        if cur is None:
            return None
        heads, rank = self._index()[2], self._index()[3]
        k = rank.get(cur)
        if k is None:
            return next((j for j in reversed(heads) if j < cur), None)
        return heads[k - 1] if k > 0 else None

    def mark(self, i: int, top: float, h: float, x0: float, width: float) -> None:
        """Publish a line's box so a click on it seeks there.

        In the space the stack publishes in: screen y plus view.scroll, which
        is 0 for everything here that pins its lines. line_at subtracts the
        anchor from the click and from the box alike, so it cancels and must
        not be added in.
        """
        self.v.line_rects.append((i, top + self.v.scroll, h, x0, x0 + width))

    def line_lifts(self, rows, fm: QFontMetricsF, pos: float,
                   act: float) -> list:
        """How far each fragment has lifted, one dict per row, keyed by index.

        The same schedule the stack uses and for the same reason: the rise is
        cut for the whole LINE rather than run off each syllable's own clock,
        so what crosses it is an incline and not a step. Asked for the line
        and not for a row at a time because the incline does not stop at a row
        break -- the head of row two is the next thing after the tail of row
        one, and it should be on its way up before the voice gets there. See
        Renderer.rise_plan.
        """
        if self.v.rise <= 0 or act <= 0.01:
            return [{} for _ in rows]
        full = fm.height() * 0.055 * self.v.rise * act
        return self.frag_lifts(rows, full, pos)

    def draw_row(self, p, row, ox: float, ry: float, fm: QFontMetricsF,
                 pos: float, act: float, alpha: float,
                 sung, base, clear, lifts: dict | None = None) -> None:
        """One wrapped row of a line, filled to the clock.

        Un-sung text first and the fill over it, both under whatever transform
        the pop and the rise have put on the painter -- so a word that lifts
        takes all of itself with it. Nothing is cached and nothing is clipped,
        which is why these renderers never had the stack's trouble of a cut
        rectangle biting a neighbouring glyph.

        `lifts` is this row's share of the whole line's rise, worked out once
        by the caller. A row left to work out its own would be a line the wave
        has to restart at every row break.
        """
        if lifts is None:
            lifts = self.line_lifts([row], fm, pos, act)[0]
        for f_i, (x, w, txt, s, e) in enumerate(row):
            px = ox + x
            p.save()
            # Neither the lift nor the pop goes on the painter: lifted_word
            # places the word, because a translation is the one thing Qt
            # rounds to a whole pixel. See Renderer.lifted_word.
            lift = lifts.get(f_i, 0.0)
            cx, cy = px + w * 0.5, ry - fm.ascent() * 0.35
            grow = 1.0
            if s is not None and e is not None:
                frac = (1.0 if pos >= e else
                        (0.0 if pos <= s else (pos - s) / max(1e-6, e - s)))
                gate = (1.0 if self.v.pop_min <= 0
                        else min(1.0, (e - s - self.v.pop_min) / 0.2))
                if self.v.pop > 0 and s <= pos < e and gate > 0:
                    k = math.sin(math.pi * frac) * act * gate
                    grow = 1.0 + k * self.v.pop * 0.035
                    lift += k * self.v.pop * fm.height() * 0.055
            else:
                frac = 0.0
            p.setPen(base)
            p.setOpacity(alpha)
            self.lifted_word(p, QPointF(px, ry), txt, lift, fm, grow, cx, cy)
            if frac > 0:
                if frac >= 1.0 or self.snap:
                    p.setPen(sung)
                else:
                    edge = px + w * frac
                    soft = max(0.75, self.v.edge * fm.height() * 0.22)
                    g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
                    g.setColorAt(0.0, sung)
                    g.setColorAt(1.0, clear)
                    p.setPen(QPen(QBrush(g), 0))
                p.setOpacity(act)
                self.lifted_word(p, QPointF(px, ry), txt, lift, fm, grow, cx, cy)
            p.restore()
        p.setOpacity(1.0)

    def draw_block(self, p, ln, rows, fm: QFontMetricsF, x0: float,
                   width: float, top: float, pos: float, act: float,
                   alpha: float) -> float:
        """A whole line's rows, laid down from `top`. Returns its height."""
        sung = self.v.sung_color(ln)
        base = self.v.base_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        lifts = self.line_lifts(rows, fm, pos, act)
        ry = top + fm.ascent()
        for r_i, row in enumerate(rows):
            self.draw_row(p, row, x0, ry, fm, pos, act, alpha, sung, base,
                          clear, lifts[r_i])
            ry += fm.height() * 1.06
        return len(rows) * fm.height() * 1.06

    def adlibs_h(self, of: int, live, fm: QFontMetricsF, width: float) -> float:
        """How much room draw_adlibs is going to want under a line.

        Asked before anything is drawn, because a renderer that centres a
        block has to know how tall the block is first.
        """
        h = 0.0
        for j in self.adlibs_of(of):
            if self.act_of(j, live) > 0.02:
                h += fm.height() * (self.ADLIB_GAP + 1.06 * len(
                    self.rows_of(self.v.lines[j], fm, width)))
        return h

    def draw_adlibs(self, p, of: int, live, font: QFont, fm: QFontMetricsF,
                    x0: float, width: float, top: float, pos: float,
                    fade: float = 1.0) -> float:
        """The backing vocals of one line, small, under it. Returns the drop.

        They are drawn INSIDE the block of the line they belong to rather than
        given a place of their own, because that is what they are: a second
        voice on this line, sung across it. A renderer that handed them a slot
        of their own had them taking the place of the line coming next, which
        is the one thing the reader needs to be able to see.
        """
        drop = 0.0
        p.setFont(font)
        for j in self.adlibs_of(of):
            act = self.act_of(j, live)
            if act <= 0.02:
                continue
            rows = self.rows_of(self.v.lines[j], fm, width)
            drop += fm.height() * self.ADLIB_GAP
            h = self.draw_block(p, self.v.lines[j], rows, fm, x0, width,
                                top + drop, pos, act, act * 0.34 * fade)
            self.mark(j, top + drop, h, x0, width)
            drop += h
        return drop


class Spotlight(Pinned):
    """The line being sung, alone and large, between the two either side of it.

    Nothing moves up the window: a line arrives where the last one was and the
    two cross-fade.

    That fade is on a clock of this renderer's own, and not on the activations
    the window eases, because those say what is SOUNDING. A line whose last
    word is held under the start of the next one goes on sounding through it,
    and every line written that way -- a trade, a chorus with a tail, anything
    with an ad-lib in it -- was drawn at full strength straight through its
    replacement for as long as the document said it lasted. Lines here are
    stacked in one place, so what that reads as is not a line leaving: it is
    two lyrics printed over each other. The line being sung is now the only
    big one, and whatever it took over from has FADE seconds to get out.

    The neighbours are set small and dim, and hung off the top and bottom of
    whatever the middle line actually came out to be rather than off a guess at
    how tall one line is -- a couplet that wraps to three rows would otherwise
    have them printed through it. All three take a click.
    """

    name = "spotlight"
    # Long enough to read as a dissolve rather than a cut, short enough that
    # the two lines are never both legible at once.
    FADE = 0.22

    def __init__(self, view) -> None:
        super().__init__(view)
        self.cur = None
        self.gone: dict[int, float] = {}

    def forget(self) -> None:
        self.cur, self.gone = None, {}

    def leaving(self, cur):
        """{line: how much of it is left}, for the line on its way out.

        One at a time, and always the last one there was. A drag along the
        progress bar changes the line under the clock on every frame, and a
        fade that kept all of them had a second of song dissolving on top of
        itself -- twenty big lines drawn over each other, for as long as the
        reader held the bar.
        """
        now = time.monotonic()
        if cur is not None and cur != self.cur:
            self.gone = {} if self.cur is None else {self.cur: now}
            self.cur = cur
        out = {}
        for i, t in list(self.gone.items()):
            f = 1.0 - (now - t) / self.FADE
            if f <= 0.02 or i == cur:
                del self.gone[i]
            else:
                out[i] = _smooth(f)
        return out

    def animating(self) -> bool:
        # The window eases activations and repaints while they move; this fade
        # is quicker than they are and has to ask for its own frames.
        return bool(self.gone)

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        v.line_rects = []
        v.content_h = 0.0
        pos = v.position() - v.track_offset()
        cur, nxt = self.current(pos)
        prv = self.before(cur)
        live = self.live(pos)
        big, small = self.font(v.lyric_px() * 1.5), self.font(v.lyric_px() * 0.62)
        fm_big, fm_sm = QFontMetricsF(big), QFontMetricsF(small)
        out = self.leaving(cur)

        head = foot = H * 0.46
        p.setFont(big)
        # Faintest first, and the line being sung last of all, so it is drawn
        # over whatever it is replacing rather than under it.
        for i in sorted(out, key=lambda k: out[k]) + ([] if cur is None else [cur]):
            ln = v.lines[i]
            act = 1.0 if i == cur else out[i]
            if ln.get("dots"):
                self._paint_dots(p, ln, fm_big, x0, H * 0.42, pos, act,
                                 act * 0.9, width, "center")
                continue
            rows = self.rows_of(ln, fm_big, width)
            h = len(rows) * fm_big.height() * 1.06
            top = H * 0.46 - h / 2
            self.draw_block(p, ln, rows, fm_big, x0, width, top, pos,
                            act, act * 0.34)
            if i == cur:
                head, foot = top, top + h
                self.mark(i, top, h, x0, width)

        if cur is None:
            return
        p.setFont(small)
        # The backing vocals of the line being sung, hung off the bottom of it
        # at the size the neighbours are set in. They are part of this line, so
        # the line coming next is pushed below them.
        foot += self.draw_adlibs(p, cur, live, small, fm_sm, x0, width, foot,
                                 pos)
        for i, below in ((prv, False), (nxt, True)):
            if i is None or v.lines[i].get("dots"):
                continue
            rows = self.rows_of(v.lines[i], fm_sm, width)
            h = len(rows) * fm_sm.height() * 1.06
            top = (foot + fm_sm.height() * 0.9 if below
                   else head - fm_sm.height() * 0.9 - h)
            self.draw_block(p, v.lines[i], rows, fm_sm, x0, width, top, pos,
                            0.0, 0.30)
            self.mark(i, top, h, x0, width)


class Karaoke(Pinned):
    """Two lines in the middle of the window: what is being sung, and what is
    coming.

    Which of the two bands a line lands in is decided by where it is in the
    document and not by which band is free, so a line never changes row
    halfway through being sung -- that is the whole reason the pair alternates
    rather than scrolling. It counts LINES THAT TAKE A BAND, though, rather
    than raw indices: a verse with an ad-lib written into every line has its
    lines two apart, and alternating on the index alone put every one of them
    in the same band, each printed through the last.

    Ad-libs do not take a band at all. They are drawn small underneath the
    line they hang off, inside its block, which is where they are sung from --
    handing them a band of their own is handing them the place where the
    reader looks for what is coming next.

    Where two lead lines overlap -- a trade, a second voice answering before
    the first has finished -- both are sounding and both are drawn filling,
    one per band, which is what the alternation was for in the first place.

    The line that has not started yet is dim, and comes up out of that dimness
    over the couple of seconds before its turn. Being dim says "not this one";
    getting brighter says when -- and it says it in the one thing every
    renderer here already uses to mean now, which drawing a bar under it did
    not.
    """

    name = "karaoke"
    LEAD = 2.0                   # seconds of run-up the bar shows

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        v.line_rects = []
        v.content_h = 0.0
        pos = v.position() - v.track_offset()
        cur, nxt = self.current(pos)
        if cur is None:
            return
        font, small = self.font(v.lyric_px() * 0.94), self.font(v.lyric_px() * 0.58)
        fm, fm_sm = QFontMetricsF(font), QFontMetricsF(small)
        live = self.live(pos)

        # Who is in which band. Every line SOUNDING that takes a band takes
        # the one its own place in the document gives it, and the line coming
        # takes whichever band is left over -- if two voices are already using
        # both, the line coming next IS one of them and nothing is being held
        # back. Sounding, and not "the line an ad-lib belongs to": reaching
        # back from a live ad-lib would put a line whose own words finished a
        # bar ago into the pair, and put it there dressed as the line coming
        # next, which is the last thing it is.
        slots: dict[int, int] = {}
        for i in [cur] + [j for j in live if self.head_of(j) == j]:
            slots.setdefault(self.rank(i) % 2, i)
        if nxt is not None and len(slots) < 2:
            slots.setdefault(self.rank(nxt) % 2, nxt)

        # Two bands of a fixed height, so the pair can never reach each other
        # however many rows either line wraps to -- a slot whose position came
        # out of its own line's height is a slot that moves, and the point of
        # the alternation is that neither of them does.
        #
        # A block too tall for its band grows AWAY from the divider between
        # them rather than out of the middle in both directions. Growing both
        # ways was survivable while a band held one line of two or three rows;
        # a line with its ad-libs under it is regularly taller than that, and
        # what came of two of those was the second voice of one band printed
        # through the first row of the other.
        band = fm.height() * 2.6
        low = H * 0.5                       # top of the lower of the two
        divide = fm.height() * 0.35         # the closest either comes to it
        for slot, i in sorted(slots.items()):
            ln = v.lines[i]
            coming = i not in live
            act = 0.0 if coming else self.act_of(i, live)
            rows = self.rows_of(ln, fm, width)
            own = len(rows) * fm.height() * 1.06
            h = own + self.adlibs_h(i, live, fm_sm, width)
            top = (max(low + (band - h) / 2, low + divide) if slot
                   else min(low - band + (band - h) / 2, low - divide - h))
            if ln.get("dots"):
                p.setFont(font)
                self._paint_dots(p, ln, fm, x0, top, pos, act,
                                 0.20 if coming else 0.34, width, "center")
                continue
            # The line coming brightens as it approaches, which is the whole
            # of what tells the pair apart: two lines set the same size, one
            # of them lit and one of them coming up.
            alpha = (0.18 + 0.14 * self.run_up(ln, pos)) if coming else 0.34
            p.setFont(font)
            self.draw_block(p, ln, rows, fm, x0, width, top, pos, act, alpha)
            # Its own rows, not the whole block: what is under it belongs to
            # the ad-libs, and each of them publishes a box of its own to be
            # clicked on.
            self.mark(i, top, own, x0, width)
            self.draw_adlibs(p, i, live, small, fm_sm, x0, width, top + own,
                             pos, 0.6 if coming else 1.0)

    def run_up(self, ln: dict, pos: float) -> float:
        """How far into its run-up a line that has not started yet is."""
        s = ln.get("start")
        if s is None or pos >= s:
            return 1.0
        return 1.0 - max(0.0, min(1.0, (s - pos) / self.LEAD))


class Word(Pinned):
    """One word at a time, very large, in the middle of the window.

    A word, not a syllable. Word-timed documents are timed per syllable and the
    layout keeps them that way -- which is what lets the fill sweep through a
    held note -- so the syllables are put back together here and the word takes
    the span of the ones that spell it. Otherwise a line of Apple Music TTML
    reads out as "you", "'", "re" rather than as the words being sung.

    An ad-lib sung across the line gets a word of its own underneath, small.
    Two voices cannot share one slot in the middle of the window: it used to
    take whichever of them came first in the document and drop the other, so a
    chorus answered by its own backing vocals came out as either the chorus or
    the answer, never as the two of them at once -- and which one it was came
    down to how the source happened to have written them down.

    A line with no word timing under it has nothing to take apart, so it is
    drawn whole instead -- which is also what happens to every line of a
    line-synced source, and is why this degrades rather than going blank.
    """

    name = "word"

    def timed_words(self, ln: dict, fm: QFontMetricsF, width: float):
        """A line's whole words, each with the span of what spells it.

        Laid out against a width nothing can wrap at, so the line comes back
        as one row and every word in it is whole.
        """
        flat = self.rows_of(ln, fm, width * 8)
        out = []
        for run in self.words_of(flat[0] if flat else []):
            s, e = self.span_of(run)
            txt = "".join(f[2] for _k, f in run).strip()
            if s is not None and e is not None and txt:
                out.append((txt, s, e))
        return out

    @staticmethod
    def pick(timed, pos: float):
        """The word sounding, or the last one the clock went past. Never the
        one coming: this renderer says where the song IS."""
        got = None
        for word in timed:
            if word[1] <= pos:
                got = word
            if word[1] <= pos < word[2]:
                break
        return got

    def show_word(self, p, ln: dict, word, x0: float, width: float, mid: float,
                  px: float, pos: float, alpha: float):
        """One word, centred on `mid`. Returns the box it took."""
        font = self.font(px)
        fm = QFontMetricsF(font)
        p.setFont(font)
        txt, s, e = word
        w = fm.horizontalAdvance(txt)
        sung = self.v.sung_color(ln)
        base = self.v.base_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ox = x0 + (width - w) / 2
        self.draw_row(p, [(0.0, w, txt, s, e)], ox, mid + fm.ascent() / 2, fm,
                      pos, 1.0, alpha, sung, base, clear)
        return ox, w, fm.height()

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        v.line_rects = []
        v.content_h = 0.0
        pos = v.position() - v.track_offset()
        cur, _nxt = self.current(pos)
        if cur is None:
            return
        ln = v.lines[cur]
        fm_line = QFontMetricsF(self.font(v.lyric_px() * 1.1))
        if ln.get("dots"):
            p.setFont(self.font(v.lyric_px() * 1.1))
            self._paint_dots(p, ln, fm_line, x0, H * 0.46, pos, 1.0, 0.9, width,
                             "center")
            return

        live = self.live(pos)
        timed = self.timed_words(ln, fm_line, width)
        if not timed:
            # Nothing to pick from: the whole line, centred.
            p.setFont(self.font(v.lyric_px() * 1.1))
            rows = self.rows_of(ln, fm_line, width)
            h = len(rows) * fm_line.height() * 1.06
            self.draw_block(p, ln, rows, fm_line, x0, width, H * 0.46 - h / 2,
                            pos, 1.0, 0.34)
            self.mark(cur, H * 0.46 - h / 2, h, x0, width)
            return

        # The ad-libs of this line that are sounding, and what each of them is
        # saying. Whichever of them opened first stands in for the line itself
        # while the line has not been sung into yet: an ad-lib that comes in
        # ahead of its lead is what the song is doing, and the middle of the
        # window is for what the song is doing.
        subs = []
        for j in self.adlibs_of(cur):
            if j not in live:
                continue
            said = self.timed_words(v.lines[j], fm_line, width)
            # Its first word until it has sung one, the same fallback the line
            # itself gets: a voice that is sounding has something to show even
            # in the breath before its first word.
            got = self.pick(said, pos) or (said[0] if said else None)
            if got:
                subs.append((j, got))
        big, of = self.pick(timed, pos), cur
        if big is None and subs:
            # The line has not been sung into yet and something backing it
            # has: that is what the song is doing, so it takes the middle
            # rather than being printed under a word nobody has sung.
            of, big = subs.pop(0)
        if big is None:
            big, of = timed[0], cur

        # The big word sits a little high when something is written under it,
        # so the pair is centred on the window rather than the lead alone.
        mid = H * 0.46 if not subs else H * 0.42
        ox, w, h = self.show_word(p, v.lines[of], big, x0, width, mid,
                                  v.lyric_px() * 2.6, pos, 0.34)
        self.mark(of, mid - h / 2, h, ox, w)
        sub_px = v.lyric_px() * 1.15
        sub_h = QFontMetricsF(self.font(sub_px)).height()
        y = mid + h * 0.55
        for j, word in subs:
            ox, w, _h = self.show_word(p, v.lines[j], word, x0, width,
                                       y + sub_h / 2, sub_px, pos, 0.30)
            self.mark(j, y, sub_h, ox, w)
            y += sub_h * 1.15


class Cards(Pinned):
    """A card per line, the whole song's worth, scrolling past the window.

    Every card takes a click, over the whole of its rounded rectangle rather
    than over the text alone -- the card is what the reader is aiming at.

    This drew three cards and pinned them: the line being sung and one either
    side, moving past a window that never scrolled. Three cards is all the song
    a reader can have, and the wheel did nothing to them, so there was no way
    to look ahead or back. It lays the whole document out now and lets the
    column scroll like the stack does -- the window follows the song on its
    own, and a reader who takes the wheel gets the rest of the song and is
    given it back four seconds later, which is the behaviour the stack has had
    all along.

    An ad-lib is set smaller on a card inset from its line's, so the two read
    as one thing written together rather than as two lines of the song.
    """

    name = "cards"
    scrolls = True
    INSET = 0.10                 # of the column, per side, for an ad-lib card

    def rows(self, i: int, fm: QFontMetricsF, width: float):
        """This renderer's wrapped rows for a line, kept between frames.

        Cards lays out the whole document rather than the two lines around the
        clock, and wrapping every line of it on every frame is not free. It is
        kept in the WINDOW's cache rather than one of this renderer's own so
        that everything which already empties that -- a new lyric, a new font,
        a new size -- empties this too.
        """
        v = self.v
        key = ("cards", i, int(width), int(v.lyric_px()), v.align, v.roman,
               v.furigana)
        hit = v.layout_cache.get(key)
        if hit is None:
            hit = v.layout_cache[key] = self.rows_of(v.lines[i], fm, width)
        return hit

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        v.line_rects = []
        pos = v.position() - v.track_offset()
        live = self.live(pos)
        font, small = self.font(v.lyric_px()), self.font(v.lyric_px() * 0.66)
        fm, fm_sm = QFontMetricsF(font), QFontMetricsF(small)
        pad = fm.height() * 0.55
        gap = fm.height() * 0.5

        top = v.anchor()
        y = top - v.scroll
        for i, ln in enumerate(v.lines):
            if not self.singable(i):
                continue
            bg = bool(ln.get("background"))
            f = fm_sm if bg else fm
            inset = width * self.INSET if bg else 0.0
            cx, cw = x0 + inset, width - inset * 2
            rows = self.rows(i, f, cw - pad * 2)
            h = len(rows) * f.height() * 1.06 + pad * 2
            act = self.act_of(i, live)
            if -h - gap < y < H + gap:
                p.setFont(small if bg else font)
                # Faded by distance from the focus band as well as by whether
                # it is being sung, the way the stack fades its own column: a
                # scrolling renderer that did not would slice the card at the
                # top of the window off at full strength. The card itself goes
                # with its words -- a panel left behind by the text that was on
                # it is a blank card floating at the edge of the window.
                dist = v.vfade(y + h / 2)
                fade = (0.38 + 0.62 * act) * dist
                if ln.get("dots"):
                    self._paint_dots(p, ln, f, cx + pad, y + pad, pos, act,
                                     fade * 0.9, cw - pad * 2, "center")
                else:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255,
                                      int((14 + 16 * act) * dist)))
                    p.drawRoundedRect(QRectF(cx, y, cw, h), pad * 0.7, pad * 0.7)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    self.draw_block(p, ln, rows, f, cx + pad, cw - pad * 2,
                                    y + pad, pos, act, 0.34 * fade)
            self.mark(i, y, h, cx, cw)
            y += h + gap
        v.content_h = y + v.scroll - top


RENDERERS = {r.name: r for r in (Flow, Snap, Spotlight, Karaoke, Word, Cards)}
RENDER_MODES = list(RENDERERS)
