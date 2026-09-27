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

One thing a renderer may say about itself: `stacked`, whether its lines are
laid out by view.layout_line at the window's own lyric size. The stack is; the
pinned renderers are not, and set their own type. It is not about drawing --
it is about whether anything OUTSIDE the column can work out where a word
ended up, which the review marks need. See LyricsView._paint_review_marks.

A stacked renderer may still draw a line under a transform, and says so with
`line_scale(i)`: what the painter was scaled by about that line's own centre
when it was drawn, 1.0 for anything untransformed. The layout is still the
window's, so the outside still knows the boxes -- it just has to put them
through the same scale to land on the ink. See Amll.SCALE.

A renderer is constructed with the view and keeps it as `self.v` for the life
of the window; switching renderers builds a new one.
"""
import math
import re
import time
import unicodedata

import language as LANG

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,
                         QLinearGradient,
                         QPainter, QPen, QPixmap, QRadialGradient, QRegion,
                         QTextLayout, QTransform)

def mono() -> float:
    """Elapsed time, off the clock the window uses. See lyrics_gui.mono.

    Spelled out again here rather than imported, for the same reason TEXT and
    VIEW are handed over rather than reached for: importing the window from
    here loads a second copy of it whenever it is started as a script.
    """
    return time.perf_counter()


NUDGE = 1.0 + 1e-7


def blit(p: QPainter, target, pm, src=None) -> None:
    """drawPixmap, put where it is asked to be and not on the nearest pixel.

    Under a transform that only shifts -- and a scale of exactly 1 is one --
    Qt's raster engine puts a picture on a whole device pixel whatever the
    smooth-transform hint says. So a word lifting by a fraction of a pixel a
    frame stood still and then jumped a pixel, each word on a frame of its
    own: the line shook while it rose, popped or glowed. Measured by ink
    centroid over tenths of a pixel: plain, 0.0 x5 then 1.0; nudged, 0.1 a
    step. Every picture a renderer draws goes through here so that no new
    call can bring that back.
    """
    p.save()
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if p.transform().type().value <= QTransform.TransformationType.TxTranslate.value:
        p.setTransform(QTransform(1.0, 0.0, 0.0, NUDGE, 0.0, 0.0), True)
    if src is None:
        p.drawPixmap(target, pm)
    else:
        p.drawPixmap(target, pm, src)
    p.restore()


TEXT = None
_smooth = None
soft_scale = None

RISE_LEAD = 0.06
RISE_TIME = 0.30

STAYING = (0.0, None, 1.0)

MAX_BLUR = 9

WARM_EDGE = 40


def row_rtl(row) -> bool:
    """Whether a wrapped row reads right to left.

    wrap_shape has already laid such a row out from the right (see rtl_row):
    its x run the other way, and each word's space leads its last fragment
    instead of trailing it. Everything that fills by the clock asks this so
    the light comes in from the right edge of each word, not the left.
    """
    return LANG.is_rtl("".join(f[2] for f in row))


def sung_grad(edge: float, soft: float, sung: QColor, clear: QColor,
              rtl: bool = False) -> QPen:
    """The pen for a fragment the voice is part way across: sung behind the
    edge, clear ahead of it -- and for a right-to-left row, behind is right."""
    g = QLinearGradient(edge - soft, 0.0, edge + soft, 0.0)
    g.setColorAt(1.0 if rtl else 0.0, sung)
    g.setColorAt(0.0 if rtl else 1.0, clear)
    return QPen(QBrush(g), 0)


FACE_GAP = "\u2002\u2003"


class Renderer:
    """The contract. See the module docstring for what has to be left behind."""

    name = ""
    scrolls = True
    stacked = False
    snap = False
    SCALE_EPS = 5e-4

    def __init__(self, view) -> None:
        self.v = view

    def rest_top(self, i: int) -> float | None:
        """Where line `i`'s top will SETTLE on screen, for a renderer whose
        lines travel on their own -- springs, tweens -- so that something
        kept level with a line (the review sidebar) can aim at where it is
        going instead of copying every overshoot on the way. None means
        line_rects less the scroll is already the answer."""
        return None

    def paint(self, p, x0: float, width: float, H: int) -> None:
        raise NotImplementedError

    def line_scale(self, i: int) -> float:
        """What line `i` was last drawn scaled by, about its own centre.

        1.0 unless a renderer says otherwise, which is every renderer that
        draws its lines at the size the plan gives them. A renderer that
        scales a line has to answer here, because the window puts the review
        marks where the LAYOUT says the words are and nothing else can tell
        it the ink moved. See LyricsView._paint_review_marks.
        """
        return 1.0

    @staticmethod
    def scale_about(p, s: float, x0: float, width: float,
                    y: float, h: float) -> None:
        """Put the painter under line `i`'s scale. The caller has saved.

        Written once and called from both sides -- the renderer drawing the
        line and the window marking it -- because the two have to agree about
        the CENTRE to the pixel or the rules sit off the words by a fraction
        that grows with the distance from it. Two copies of three lines of
        arithmetic is exactly the kind of agreement that stops being one.
        """
        cx, cy = x0 + width * 0.5, y + h * 0.5
        p.translate(cx, cy)
        p.scale(s, s)
        p.translate(-cx, -cy)

    @staticmethod
    def words_of(row):
        """A wrapped row's fragments, grouped back into the words they spell.

        wrap_pieces lays out syllables and drops the flag that said which of
        them belonged together, but it leaves behind the mark that matters:
        the last syllable of a word is the one carrying the trailing space. So
        a word is the run up to and including the next fragment that ends in
        one. A word long enough to have been split across rows comes back as
        one run per row, which is what should happen to it anyway.

        A TRAILING HYPHEN ends a run too, and that is the whole difference
        between two shapes that reach here looking identical. Both are
        fragments joined with no space between them, but they are not the same
        thing at all:

          * "wor" + "ry,", "a" + "po" + "lo" + "gize" -- one written word,
            cut up because the timing needed it. The pieces are not utterances
            and nothing in the text says where they meet. These must stay one
            word: what reads them is the rise, and a word whose halves go up
            at their own speeds tears in two and holds the pose (see
            Amll.word_lifts).
          * "fuck-" x5, "F-" "R-" "I-" "E-" "N-" "D-" "S", "d-" + "do",
            "Off-" + "off-" + ... -- a stutter, a spell-out, a hyphenated
            compound. Each piece is a whole utterance with a boundary the
            writer PRINTED, and the voice arrives at each one separately.
            Grouped into one word they went up as a single slab, so a line
            that is sung as eight little hits rose once, all together.

        The hyphen is the discriminator because it is ink. A syllable split
        inside a word is written with nothing between the pieces; a hyphen is
        a character somebody typed, and a reader sees a boundary where it is.
        Measured across this collection the two never overlap: of 279
        hyphen-joined runs not one is a mid-word split, and of 1356 plain ones
        not one carries a hyphen.

        U+002D is the only one the documents actually use; the other two are
        here because they are the same character by another name. The dashes
        are deliberately NOT: an en or em dash between words is punctuation
        and comes with its own spaces.

        Returns [[(index in row, fragment), ...], ...].
        """
        out, run = [], []
        rtl = row_rtl(row)
        for k, frag in enumerate(row):
            run.append((k, frag))
            txt = frag[2]
            if ((txt.startswith(" ") if rtl else txt.endswith(" "))
                    or txt.rstrip().endswith(("-", "\u2010", "\u2011"))):
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

    @staticmethod
    def voiced_of(run):
        """How long the word was SUNG, which is not how long it lasted.

        span_of dates a word from its first start to its last end, which is
        what it is for -- that is where the word sits. But the fragments of a
        split word do not always abut, and where they do not the silence
        between them is inside that span and the word was not being sung
        through it. Anything asking "how long is this note" wants this
        instead: the fragments' own lengths added up, with the holes left out.

        Identical to `e - s` for every word whose pieces meet, which is 1335
        of the 1356 split words in this collection. On the 21 that have a hole
        it is the difference between what the singer did and what the document
        spans: "ver|koop" is voiced 0.84s and dated 1.52s, "Andr|e" 0.63s
        against 1.20s, and both are words the EMP_MIN gate is meant to turn
        down and was letting through on the strength of the silence.

        Not used for where a word ENDS. A light that stops early is a
        different change from a light with a hole in it, and which of the two
        is wanted has not been decided -- see docs/notes/TODO.md.
        """
        got = [f[4] - f[3] for _k, f in run
               if f[3] is not None and f[4] is not None and f[4] > f[3]]
        return sum(got) if got else None

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
        blit(p, QPointF(ox, oy - lift), pm)
        p.restore()

    _SHAPED: dict = {}

    @classmethod
    def shaped_offsets(cls, txt: str, font: QFont, fm: QFontMetricsF) -> tuple:
        """Where a drawText of `txt` actually puts each character.

        Not the same as adding up the characters' own advances, and not the
        same as the width of the text before each one either. Both of those
        miss KERNING, which the font applies to a PAIR: the width of "ev" does
        not include the tuck between the "v" and whatever follows it, so a
        character placed at that width sits a pixel to the right of where the
        font would have put it.

        A pixel matters here because this is only used when a word is drawn
        character by character -- which is only while it is being emphasised.
        A letter that is a pixel out for the length of a held note, and right
        again the moment the note ends, is exactly as visible as it sounds.
        Measured over five documents before this: 19 of 104 emphasised words
        moved a letter when the glow started, by up to 3.7px.

        So the real positions are asked for, by laying the text out the way
        the painter will. Cached per text and face; a line has a handful of
        distinct words and a song a few hundred.

        Falls back to the prefix widths where the layout does not hand back
        one glyph per character -- a ligature, a combining mark -- which is
        the old behaviour and no worse than it was.
        """
        key = (txt, font.key())
        hit = cls._SHAPED.get(key)
        if hit is None:
            hit = tuple(fm.horizontalAdvance(txt[:j]) for j in range(len(txt)))
            try:
                lay = QTextLayout(txt, font)
                lay.beginLayout()
                line = lay.createLine()
                if line.isValid():
                    line.setLineWidth(1e6)
                lay.endLayout()
                xs = sorted(pt.x() for run in lay.glyphRuns()
                            for pt in run.positions())
                if len(xs) == len(txt):
                    hit = tuple(xs)
            except Exception:
                pass
            if len(cls._SHAPED) > 4096:
                cls._SHAPED.clear()
            cls._SHAPED[key] = hit
        return hit

    def place_word(self, p, at, txt: str, lift: float, fm: QFontMetricsF,
                   grow: float = 1.0, cx: float = 0.0, cy: float = 0.0,
                   emph=None) -> None:
        """A fragment, drawn as one word or as its separate characters.

        Every path that puts lyric text on the screen goes through here, so
        that a renderer which moves the characters of a word independently --
        see Amll.emph_of -- moves them in the un-sung layer and the sung layer
        alike. They are the same letters: if only the lit half is displaced,
        the word tears in two along the fill boundary.
        """
        if emph is None:
            self.lifted_word(p, at, txt, lift, fm, grow, cx, cy)
            return
        parts = emph.parts
        scale = max((c[3] for c in parts), default=1.0)
        rise = lift + sum(c[2] for c in parts) / max(1, len(parts))
        self.lifted_word(p, at, txt, rise, fm, scale * grow,
                         at.x() + fm.horizontalAdvance(txt) * 0.5,
                         at.y() - fm.ascent() * 0.35 - rise)

    def emph_glow(self, p, emph, at, font: QFont, fm: QFontMetricsF,
                  lift: float, fade: float) -> None:
        """The light behind each character of a held word.

        Per character rather than one halo for the whole word, because
        glow_of sizes its blur from the drawn WIDTH: ask it for a six letter
        word and it gives about eleven pixels of spread, against four for a
        single letter. One halo for the word is therefore not the same light
        only wider -- it is a much bigger one, and it reads as a haze around
        the word rather than as the letters being lit.

        The halos of two neighbours do meet in the gap between them, where
        they add. That was survivable once the word stopped GROWING: measured
        over every held word in a chorus, the dimmest point between two
        letters still sits 54% below the letters at full strength. It was not
        survivable before, which is what sent this looking for a culprit in
        the light when the culprit was the size. See Amll.SWELL.
        """
        for ch, dx, up, scale, lit in emph:
            x = at.x() + dx
            if lit > 0.004:
                radius = max(1, round(self.glow_of(ch, fm, emph.held)[0]
                                      * self.HALO_SIZE))
                pad = radius * 3
                gp = self.v.glow_pixmap(ch, font, radius)
                gw, gh = gp.width(), gp.height()
                ccx = x - pad + gw / 2
                ccy = at.y() - fm.ascent() - pad + gh / 2 - lift - up
                p.setOpacity(min(1.0, fade * lit * self.HALO_SCALE))
                blit(p, QRectF(ccx - gw * scale / 2, ccy - gh * scale / 2,
                                    gw * scale, gh * scale),
                             gp, QRectF(gp.rect()))
        p.setOpacity(1.0)

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
        now = mono()
        cue = max(0.0, (t - 0.88) / 0.12) if t > 0.88 else 0.0
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        e = self.v.beat_energy()
        for k in range(3):
            lift, left, big = (flights[k] if flights else None) or STAYING
            if left is not None and left <= 0.01:
                continue
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
        p.restore()

    def animating(self) -> bool:
        """True while there is motion of the renderer's own still to draw.

        tick() stops repainting an idle window, and it cannot see motion that
        lives in here rather than in the scroll or the activations.
        """
        return False

    def wheel(self, dy: float) -> bool:
        """One notch of the wheel, offered here before the window takes it.

        The window's own answer is to move view.scroll, which is the right
        answer for a renderer whose lines are laid out against it and no
        answer at all for one that pins them -- so a pinned renderer that
        wants to be scrollable has had no way to say so, and the wheel simply
        did nothing to it.

        True means taken, and the window leaves its own scroll alone. The
        default is to decline, which is what every renderer but the amll
        column does: their lines are where they are for reasons the wheel has
        nothing to say about.
        """
        return False

    # ----------------------------------------------------------- the credits
    def credits_index(self):
        """Which line is the credit block, or None.

        The last one where there is one, or the first with credits_top on --
        see LyricsView.build_lines, which puts it there -- but found rather than assumed, because a renderer
        that drew the wrong row here would be printing a lyric where the
        attribution belongs.
        """
        for i in range(len(self.v.lines) - 1, -1, -1):
            if self.v.lines[i].get("credits"):
                return i
        return None

    def credits_block(self, p, x0: float, width: float, top: float,
                      H: int = 0, fade: float = 1.0,
                      align: str = "center") -> float:
        """The credit block, drawn with its top at `top`. Returns its height.

        For the renderers that do not lay the whole document out and so never
        reach the row it rides on. They put it under whatever they drew last,
        once the song has finished -- see credits_due, and the renderers that
        call this, which each decide where "last" is for them.

        Held inside the window where `H` says how tall that is: these
        renderers place their lines by the height of the window rather than by
        a scroll, so a long credit under a line that wrapped three ways would
        otherwise run off the bottom and be absent again.

        Centred by default rather than following the window's own alignment,
        because the renderers that come here centre their lines whatever that
        setting says, and a credit hanging off the left under a line in the
        middle reads as something else on the screen rather than as the foot
        of what is above it.
        """
        i = self.credits_index()
        if i is None:
            return 0.0
        rows, fm, h = self.v.layout_line(i, width)[:3]
        if H and getattr(self.v, "credits_top", False):
            top = H * 0.08
        if H:
            top = min(top, H - h)
        self._paint_credits(p, rows, fm, x0, top, width,
                            self.v.lines[i].get("credit_links") or (), fade,
                            align)
        return h

    def _paint_credits(self, p, rows, fm, x0: float, y: float, width: float,
                       links=(), fade: float = 1.0, align: str = "") -> None:
        """The footer under the last line. Dim and unanimated -- it is not part
        of the song and should never look like the next thing to be sung.

        `rows` are (which credit, one wrapped line of it). The songwriters are
        the song's own credit and are drawn brighter than the rest, however
        many lines of them there are.

        `links` is that same block's clickable stretches, one list per credit:
        a Spicy Lyrics contributor's own page, Unison's address. They are drawn
        over the row that already holds them rather than instead of it -- same
        font, same place, brighter and underlined -- so the line reads the same
        whether or not anything in it is a link, and a name that wrapped onto
        the next row simply does not match there and is left alone.

        Where they land is written down for the window to hit-test; see
        LyricsView.credit_at. The rect is the ink plus a little, because a
        credit is small type and a link nobody can hit is not a link.
        """
        align = {"center": Qt.AlignmentFlag.AlignHCenter,
                 "right": Qt.AlignmentFlag.AlignRight}.get(
                     align or self.v.align, Qt.AlignmentFlag.AlignLeft)
        if fade <= 0.01:
            return
        p.save()
        font = self.v.credit_font()
        p.setFont(font)
        under = QFont(font)
        under.setUnderline(True)
        step = fm.height() * 1.4
        ry = y + step
        at = getattr(self.v, "mouse_pos", None)
        for part, row in rows:
            dim = int((120 if part == 0 else 88) * fade)
            p.setPen(QColor(234, 234, 234, dim))
            p.drawText(QRectF(x0, ry, width, step),
                       int(align | Qt.AlignmentFlag.AlignVCenter), row)
            for text, url in (links[part] if part < len(links) else ()):
                cut = row.find(text)
                if cut < 0 or not url:
                    continue
                run = fm.horizontalAdvance(row)
                left = (x0 if align == Qt.AlignmentFlag.AlignLeft else
                        x0 + (width - run) / 2
                        if align == Qt.AlignmentFlag.AlignHCenter
                        else x0 + width - run)
                lx = left + fm.horizontalAdvance(row[:cut])
                lw = fm.horizontalAdvance(text)
                box = QRectF(lx - 3, ry, lw + 6, step)
                self.v.credit_hot.append((box, url))
                p.setFont(under)
                p.setPen(QColor(234, 234, 234,
                                min(255, dim + (95 if at is not None
                                                and box.contains(at) else 45))))
                p.drawText(QRectF(lx, ry, lw + 2, step),
                           int(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter), text)
                p.setFont(font)
            for name, url in getattr(self.v, "credit_faces", ()):
                cut = row.find(name + FACE_GAP)
                face = self.v.credit_face(url) if cut >= 0 else None
                if face is None:
                    continue
                run = fm.horizontalAdvance(row)
                left = (x0 if align == Qt.AlignmentFlag.AlignLeft else
                        x0 + (width - run) / 2
                        if align == Qt.AlignmentFlag.AlignHCenter
                        else x0 + width - run)
                gx = left + fm.horizontalAdvance(row[:cut + len(name)])
                gw = fm.horizontalAdvance(FACE_GAP)
                d = min(fm.height() * 0.95, gw * 0.8)
                p.setOpacity(0.85 * fade)
                blit(p, QRectF(gx + (gw - d) / 2, ry + (step - d) / 2, d, d),
                     face, QRectF(face.rect()))
                p.setOpacity(1.0)
            ry += step
        p.restore()


class Flow(Renderer):
    """The scrolling stack: the window's own look, and the default.

    Lines are all one size. Distance from the line being sung is carried by
    opacity and by a blur that is baked into a cached pixmap per line, so the
    only text drawn live is the line actually being sung.
    """

    name = "flow"
    stacked = True

    def __init__(self, view) -> None:
        super().__init__(view)
        self._rk = self._rects = None
        self._rtop = self._rx0 = None
        self._warm_at: int | None = None
        self._warm_done = False

    HALO = True
    HALO_SCALE = 1.0
    HALO_SIZE = 1.0

    ALL_GLOW_SPREAD = 2
    ALL_GLOW_LEVEL = 0.8

    ALL_GLOW_PAST = 0.4
    ALL_GLOW_TRAIL = 1.6
    TRAIL_STEPS = 7

    def emph_plan(self, rows, pos: float, fm: QFontMetricsF,
                  bg: bool = False) -> dict:
        """Which words of this line are being held, and how they are moving.

        Empty for the stack, whose swell is the pop and the glow and belongs
        to the word as a whole. See Amll.emph_plan for the other answer, and
        for why it is worked out once for the line rather than per fragment:
        both the un-sung layer and the fill over it have to read the same one.
        """
        return {}

    def sweep_of(self, row, ox: float, pos: float, fm: QFontMetricsF):
        """What the row needs to know about the fill before it draws a word.

        Nothing, for the stack: each word is filled from its own clock and
        knows everything it needs. See Amll.sweep_of for the other answer.
        """
        return None

    def fill_shows(self, sweep, px: float, w: float, frac: float,
                   fm: QFontMetricsF) -> bool:
        """Whether this fragment has any sung ink to draw at all."""
        return frac > 0

    def fill_pen(self, sweep, sung: QColor, clear: QColor, px: float,
                 w: float, frac: float, fm: QFontMetricsF, rtl: bool = False):
        """The pen the sung half of this fragment is drawn with.

        A word part way through is drawn with a gradient that goes from the
        sung colour to nothing across the point the voice has reached, so the
        boundary is a soft edge rather than a cut between two letters.
        """
        if frac >= 1.0 or self.snap:
            return sung
        edge = px + w * ((1.0 - frac) if rtl else frac)
        soft = max(0.75, self.v.edge * fm.height() * 0.22)
        return sung_grad(edge, soft, sung, clear, rtl)

    def plan(self, width: float):
        """The column, with each gap line at the room Hide idle gaps leaves
        it. The layout under it is cached; this pass is not, but it hands
        back the same plan while nothing is opening or shutting, so the
        rectangles built on it stay kept."""
        base = self.layout_plan(width)
        v = self.v
        if not getattr(v, "hide_gaps", False):
            return base
        pos = v.position() - v.track_offset()
        opens = tuple((i, v.gap_open(i, pos)) for i, ln in enumerate(v.lines)
                      if ln.get("dots"))
        # The base itself, held, and not its id(): a resize throws the base
        # away and the one laid out at the new size can be born at the same
        # address, which handed back the old size's rows and metrics -- words
        # spaced for the smaller font, drawn in the bigger one, on top of each
        # other.
        if (getattr(self, "_gap_base", None) is base
                and self._gap_opens == opens):
            return self._gap_plan
        rows, total = base
        room = dict(opens)
        out, off = [], 0.0
        for i, (o, h, *rest) in enumerate(rows):
            step = (rows[i + 1][0] if i + 1 < len(rows) else total) - o
            k = room.get(i, 1.0)
            out.append((off, h * k, *rest))
            off += step * k
        self._gap_base, self._gap_opens = base, opens
        self._gap_plan = (out, off)
        return self._gap_plan

    def layout_plan(self, width: float):
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
        self._warm_next(plan, live, width, H)

    WARM_REACH = 5

    def _warm_next(self, plan, live, width: float, H: int = 0) -> None:
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

        REACH IS A NUMBER OF LINES; THE WINDOW IS A NUMBER OF PIXELS. Five
        either way is the right guess for ordinary type in an ordinary window
        and badly wrong at the edges: at 46px in a 500px window the stack holds
        about three lines, and warming five each way built 55 pictures nobody
        could see out of 63 -- 87% of the work, and 87% of the cache it
        evicted. So each candidate is placed where it will BE after the switch
        (the line coming in sits at the anchor, so everything else moves by the
        difference between their offsets) and the ones that land outside the
        window are left alone. The reach stays five: it is now a ceiling
        rather than the whole rule, and on a tall window with small type
        nothing changes at all.
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
        top, here_off = v.anchor(), plan[nf][0]
        for i in range(max(0, nf - self.WARM_REACH),
                       min(len(plan), nf + self.WARM_REACH + 1)):
            if v._pix_left <= 0:
                return
            ln = v.lines[i]
            if ln.get("credits") or ln.get("dots"):
                continue
            if H:
                y = top + plan[i][0] - here_off
                if y >= H + WARM_EDGE or y + plan[i][1] <= -WARM_EDGE:
                    continue
            dist = abs(i - nf)
            if v.focus and self.focus_trim(dist) is None:
                continue
            blur = 0.0 if dist == 0 else min(float(MAX_BLUR), 1.4 * dist ** 1.35)
            blur *= scale
            lo = int(blur)
            v.line_pixmap(i, width, lo)
            if v._pix_left > 0 and blur - lo > 0.01:
                v.line_pixmap(i, width, lo + 1)
            if v.word_glow > 0 and v._pix_left > 0:
                v.line_pixmap(i, width, min(MAX_BLUR, lo + self.ALL_GLOW_SPREAD),
                              v.glow_color(ln))
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
        t = min(1.0, (pos - at) / self.float_span())
        unit = self.v.lyric_fm(False).height()
        return (unit * 9.0 * t ** 1.6, 1.0 - _smooth(t), 1.0 + 1.5 * t ** 1.6)

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
                   blur: float, bg: bool = False) -> dict:
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

    def sung_edge(self, row, pos: float) -> float | None:
        """How far along a row the voice has got, in line-local pixels.

        None where it has not reached the row at all. The answer is the right
        edge of the longest run of fragments from the START of the row that
        the clock is level with or past -- so it stops at the first word the
        voice has not reached, and the word it stops inside contributes its
        own fraction of itself.

        Walking a run rather than taking the furthest lit fragment is what
        keeps this honest where a source stamps a line out of order, which
        they do. Furthest-lit would run the light out to a word the voice is
        nowhere near because its stamps happen to sit early; a run stops
        where the singing stops. See the fill, which asks each word its own
        clock and has the same rule for the same reason.
        """
        edge = None
        rtl = row_rtl(row)
        for x, w, _txt, s, e in row:
            if s is None or e is None or pos <= s:
                break
            if pos >= e:
                edge = x if rtl else x + w
                continue
            f = (pos - s) / max(1e-6, e - s)
            edge = x + w * ((1.0 - f) if rtl else f)
            break
        return edge

    def all_glow(self, p, idx: int, ln: dict, rows, fm: QFontMetricsF,
                 ox: float, y: float, width: float, lo: int, act: float,
                 ruh: float, pos: float, rrows, gone: dict, spin) -> None:
        """A halo behind every word the voice has already been through.

        The halo the fill draws below is one word's: it comes up under the
        syllable being sung and goes out behind it, so at any moment exactly
        one word in the window is lit. This is the other thing a glow can be
        -- the light stays. Every word the voice has passed goes on glowing,
        the word being sung glows as far into itself as the fill has got, and
        a word the voice has not reached has no light at all. What travels
        along the line is the EDGE of it. Off unless `word_glow` is turned up,
        and the two stack: the word being sung still gets its own on top.

        Three things make it light rather than fog, and the first two were
        what was wrong with it before:

        It is drawn in the line's own colour taken to full brightness --
        see glow_color -- and not in the base ink. A blurred copy of the same
        grey the text is already drawn in, added back over itself, is not a
        glow; it is the line out of focus, which is the one effect this window
        already has and calls the depth blur. Light is brighter than the thing
        it comes off.

        It stops where the voice has. A line lit end to end has nothing moving
        in it, and a soft wash under un-sung words is a smear behind text that
        is not doing anything yet. Lit to the voice and no further, the glow
        is the fill's own shadow and moves with it.

        And it is ADDED -- `CompositionMode_Plus` -- because that is what
        light does. Laid over normally it would be a grey film on the
        background between the words; added, the gaps take nothing.

        Nothing is drawn twice to get it. The obvious way to light every word
        is to take each one, blur a copy and lay it behind -- a second
        rasterisation of every word on screen, a per-word cache where there
        was one entry per SUNG word, and, at a tight radius, a legible second
        copy of the word sitting behind the first. The picture wanted here
        already exists: `line_pixmap` keeps one drawing of the line per blur
        level, and it takes a pen, so the light is that same drawing in the
        sung colour at a wider level. One picture per line, cached beside the
        ones the depth blur is already keeping, and the glyphs are rasterised
        exactly as often as they were.

        The level is the line's own blur plus the spread, never less: a halo
        sharper than the text it belongs to is exactly the ghost copy this
        avoids, and a distant line is already soft.

        Skipped where the words are not where the picture says they are --
        every word in a pixmap is on the baseline, so a line coming apart
        under the float troll, or a word turning under the spin, would be lit
        where it used to be. The rise is not in that class: 5.5% of a line
        height, well inside the blur, and a wash does not notice.
        """
        v = self.v
        if v.word_glow <= 0 or act <= 0.01 or gone or spin is not None:
            return
        pitch = fm.height() * 1.06 + ruh
        soft = max(0.75, v.edge * fm.height() * 0.22)
        lit = [self.sung_edge(row, pos) for row in rows]
        last = max((i for i, e in enumerate(lit) if e is not None), default=None)
        if last is None:
            return
        level = min(MAX_BLUR, lo + self.ALL_GLOW_SPREAD)
        pad = 10 + level * 6
        pm = v.line_pixmap(idx, width, level, v.glow_color(ln))
        if pm is None:
            return
        at = QPointF(ox - pad, y - pad)
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        full = min(1.0, act * self.ALL_GLOW_LEVEL * v.word_glow)
        past = full * self.ALL_GLOW_PAST
        trail = self.ALL_GLOW_TRAIL * fm.height()
        H = pm.height()
        split = bool(rrows) and any(row_rtl(row) for row in rows)
        bands = []
        for r_i, edge in enumerate(lit):
            top = 0.0 if r_i == 0 else pad + r_i * pitch
            bot = (pad + (r_i + 1) * pitch
                   if r_i < len(rows) - 1 or (rrows and not split) else float(H))
            if split and r_i == len(rows) - 1:
                bot = pad + (r_i + 1) * pitch
            bands.append((rows[r_i], edge, top, bot, r_i < last))
        if split:
            rfm = QFontMetricsF(v.roman_font(ln))
            rpitch = rfm.height() * 1.04
            rlit = [self.sung_edge(row, pos) for row in rrows]
            rlast = max((i for i, e in enumerate(rlit) if e is not None),
                        default=-1)
            rtop = pad + len(rows) * pitch
            for r_i, edge in enumerate(rlit):
                top = rtop + (fm.height() * 0.10 if r_i else 0.0) + r_i * rpitch
                bot = (rtop + fm.height() * 0.10 + (r_i + 1) * rpitch
                       if r_i < len(rrows) - 1 else float(H))
                bands.append((rrows[r_i], edge, top, bot, r_i < rlast))
        for row, edge, top, bot, behind in bands:
            if edge is None:
                continue
            if behind:
                self._glow_strip(p, at, pm, 0.0, float(pm.width()), top, bot, past)
                continue
            if row_rtl(row):
                self._glow_strip(p, at, pm, pad + edge + trail,
                                 float(pm.width()), top, bot, past)
                self._glow_ramp(p, at, pm, pad + edge + soft, pad + edge + trail,
                                top, bot, full, past, self.TRAIL_STEPS)
                self._glow_ramp(p, at, pm, pad + edge - soft, pad + edge + soft,
                                top, bot, 0.0, full, max(1, int(soft)))
                continue
            self._glow_strip(p, at, pm, 0.0, pad + edge - trail, top, bot, past)
            self._glow_ramp(p, at, pm, pad + edge - trail, pad + edge - soft,
                            top, bot, past, full, self.TRAIL_STEPS)
            self._glow_ramp(p, at, pm, pad + edge - soft, pad + edge + soft,
                            top, bot, full, 0.0, max(1, int(soft)))
        p.restore()

    def _glow_ramp(self, p, at: QPointF, pm: QPixmap, x0: float, x1: float,
                   top: float, bot: float, a0: float, a1: float,
                   steps: int) -> None:
        """The glow across `x0`..`x1`, stepping from opacity `a0` to `a1`.

        Each step is its own clipped blit, and the clips do not overlap, so
        what this costs over a single blit of the same span is the calls and
        not the pixels. See all_glow for why the alternative -- a real
        gradient, through an off-screen copy of the picture -- is not worth
        its allocation on every frame.
        """
        if x1 <= x0:
            return
        step = (x1 - x0) / steps
        for i in range(steps):
            self._glow_strip(p, at, pm, x0 + i * step, x0 + (i + 1) * step,
                             top, bot, a0 + (a1 - a0) * (i + 0.5) / steps)

    @staticmethod
    def _glow_strip(p, at: QPointF, pm: QPixmap, x0: float, x1: float,
                    top: float, bot: float, opacity: float) -> None:
        """One horizontal slice of the glow, clipped out of the whole picture.

        `x0`..`x1` and `top`..`bot` are in the PICTURE's own pixels; `at` is
        where its top-left corner goes. Clipping rather than cropping because
        a crop is a copy: the clip costs the pixels it lets through and the
        source pixmap is the one in the cache, untouched.
        """
        if opacity <= 0.004 or x1 <= x0 or bot <= top:
            return
        p.save()
        p.setClipRect(QRectF(at.x() + x0, at.y() + top, x1 - x0, bot - top),
                      Qt.ClipOperation.IntersectClip)
        p.setOpacity(opacity)
        blit(p, at, pm)
        p.restore()

    def draw_base(self, p, ln, rows, fm: QFontMetricsF, ox: float, y: float,
                  alpha: float, lifted: dict, rrows, rfm, ruby, rufm,
                  spin, gone: dict, emphs: dict | None = None) -> None:
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
        emphs = emphs or {}
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
                if spin is not None and (r_i, x) == (spin[0], spin[1]):
                    continue
                flew, left, big = gone.get((False, r_i, f_i), STAYING)
                if left is not None:
                    if left <= 0.01:
                        continue
                    p.setOpacity(alpha * left)
                lift = lifted.get((r_i, f_i), 0.0) + flew
                self.place_word(p, QPointF(ox + x, gy), txt, lift, fm, big,
                                ox + x + w * 0.5,
                                gy - fm.ascent() * 0.35 - lift,
                                emphs.get((r_i, f_i)))
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
            st = [mono(),
                  math.cos(a1) * far, math.sin(a1) * far,
                  math.cos(a2) * far, math.sin(a2) * far,
                  (n >> 5) % 628 / 100.0, 0.0, 0.0,
                  (((n >> 17) % 200) / 100.0 - 1.0),
                  (((n >> 23) % 200) / 100.0 - 1.0)]
            self.v.cloudy[key] = st
        st[6] = mono()
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
        now = mono()
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
                            blit(p,
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
                            rtl = row_rtl(row)
                            edge = px + w * ((1.0 - frac) if rtl else frac)
                            soft = max(0.75, self.v.edge * mh * 0.22)
                            p.setPen(sung_grad(edge, soft, QColor(
                                sung.red(), sung.green(), sung.blue(), av),
                                clear, rtl))
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
                            rtl = row_rtl(row)
                            edge = px + w * ((1.0 - frac) if rtl else frac)
                            soft = max(0.75, self.v.edge * met.height() * 0.22)
                            p.setPen(sung_grad(edge, soft, QColor(
                                sung.red(), sung.green(), sung.blue(), a),
                                clear, rtl))
                        p.drawText(QPointF(px, py), txt)
                    p.restore()

    def focus_trim(self, dist: int):
        """What focus mode does to a line `dist` lines from the one being sung.

        Returns (hush, mute) -- a multiplier on the un-sung opacity, and
        whether the line gives up its sung overlay as well -- or None for a
        line focus takes off the screen altogether.

        The band has a hard edge: focus N keeps N lines either side, the ring
        at N+1 is the hint of one more, and everything past that is not drawn.
        That is what the knob says it does, and in a column that SCROLLS it is
        never seen doing it. By the time a line is far enough out for the cut
        to reach it, the viewport gradient has all but finished it off -- so
        what focus deletes is something already invisible, and what the reader
        sees is the periphery blurring away rather than lines being taken.

        Which is a property of the column, not of the knob, and Amll has a
        different column. See Amll.focus_trim.
        """
        edge = self.v.focus + 1
        if dist > edge:
            return None
        return (0.35, True) if dist == edge else (1.0, False)

    def _paint_line(self, p, idx, ln, rows, fm, x0, y, pos, live, rrows=(), rfm=None,
                    ruby=(), rufm=None) -> None:
        width = self.v._lyr_width()
        act = self.v.activation.get(idx, 0.0)
        ox = self.v.line_ox(ln, fm, x0)

        if ln.get("credits"):
            self._paint_credits(p, rows, fm, x0, y, width,
                                ln.get("credit_links") or ())
            return
        if not self.v.synced:
            flat = self.v.line_pixmap(idx, width, 0)
            if flat is not None:
                p.setOpacity(0.82)
                blit(p, QPointF(ox - 10, y - 10), flat)
                p.setOpacity(1.0)
            return

        dist = min((abs(idx - j) for j in live), default=6) if live else 6
        peek = self.v.focus_idx
        if peek is not None and peek >= 0:
            dist = min(dist, abs(idx - peek))
        hush = 1.0
        if self.v.focus and live and self.v.browse < 0.5:
            trim = self.focus_trim(dist)
            if trim is None:
                return
            hush, mute = trim
            if mute:
                act = 0.0
        blur = 0.0 if dist == 0 else min(float(MAX_BLUR), 1.4 * dist**1.35)
        blur *= (1.0 - act) * self.v.blur_scale * (1.0 - self.v.browse)
        falloff = max(0.10, 0.32 - 0.055 * max(0, dist - 1))
        falloff *= hush
        falloff += (0.60 - falloff) * self.v.browse if falloff < 0.60 else 0.0
        alpha = (falloff + 0.14 * act) * (0.8 if ln["background"] else 1.0)
        if idx == self.v.hover_idx:
            alpha = min(1.0, alpha + 0.22)
        alpha_free = alpha
        alpha *= self.v.vfade(y + fm.height() * 0.5)
        y = y + (1.0 - act) * 7.0 * self.v.line_drop * (1 if idx in live else 0)

        if ln.get("dots"):
            self._paint_dots(p, ln, fm, ox, y, pos, act,
                             self.v.vfade(y + fm.height() * 0.5)
                             * self.v.gap_open(idx, pos), width,
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
        gone = {}
        if self.v.float_up > 0:
            last = self.float_of(ln.get("end") or ln.get("start"), pos)
            if last is not None and last[1] <= 0.01:
                return
            gone = self.float_lifts(rows, rrows, ln, pos)
        spin = self.spin_frag(rows, fm, ox, y, self.v.ruby_h(rufm), pos)
        lifted = self.word_lifts(rows, fm, pos, act, blur, ln["background"])
        emphs = (self.emph_plan(rows, pos, fm, ln["background"])
                 if act > 0.01 and blur < 1.0 else {})
        own_text = ((self.v.rise > 0 and act > 0.01 and blur < 1.0)
                    or bool(gone) or bool(emphs))
        self.all_glow(p, idx, ln, rows, fm, ox, y, width, lo, act,
                      self.v.ruby_h(rufm), pos, rrows, gone, spin)
        p.save()
        if own_text:
            self.draw_base(p, ln, rows, fm, ox, y, alpha, lifted,
                           rrows, rfm, ruby, rufm, spin, gone, emphs)
        else:
            if spin is not None:
                p.setClipRegion(QRegion(self.v.rect())
                                - QRegion(spin[-1].toAlignedRect()))
            p.setOpacity(alpha * (1.0 - frac_b))
            pad = 10 + lo * 6
            flat = self.v.line_pixmap(idx, width, lo)
            if flat is not None:
                blit(p, QPointF(ox - pad, y - pad), flat)
            if frac_b > 0.01:
                pad = 10 + (lo + 1) * 6
                over = self.v.line_pixmap(idx, width, lo + 1)
                if over is not None:
                    p.setOpacity(alpha * frac_b)
                    blit(p, QPointF(ox - pad, y - pad), over)
        p.restore()
        p.setOpacity(1.0)

        if act <= 0.01 and not gone:
            return
        p.save()
        font = self.v.lyric_font(ln["background"])
        p.setFont(font)
        sung = self.v.sung_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        now = mono()
        ruh = self.v.ruby_h(rufm)
        rufont = self.v.ruby_font(ln) if rufm is not None else None
        ry = y + ruh + fm.ascent()
        for r_i, row in enumerate(rows):
            gy = self.on_grid(ry)
            sweep = self.sweep_of(row, ox, pos, fm)
            rtl = row_rtl(row)
            if rufont is not None and r_i < len(ruby):
                p.setFont(rufont)
                by = self.on_grid(gy - fm.ascent() - ruh + rufm.ascent())
                for cx, read, s, e in ruby[r_i]:
                    if s is None or e is None:
                        continue
                    flew, left, big = gone.get(
                        (False, r_i, self.frag_under(row, cx)), STAYING)
                    fade = act if left is None else left
                    if fade <= 0.01:
                        continue
                    rw = rufm.horizontalAdvance(read)
                    rx = ox + cx - rw / 2
                    frac = 1.0 if pos >= e else (
                        0.0 if pos <= s else (pos - s) / max(1e-6, e - s))
                    f_i = self.frag_under(row, cx)
                    if f_i is not None and 0.0 < frac < 1.0:
                        fx, fw = row[f_i][0], row[f_i][1]
                        edge = ox + fx + fw * frac
                        frac = max(0.0, min(1.0, (edge - rx) / max(1e-6, rw)))
                    if not self.fill_shows(sweep, rx, rw, frac, rufm):
                        continue
                    p.setPen(self.fill_pen(sweep, sung, clear, rx, rw, frac, rufm))
                    p.setOpacity(fade)
                    lift = self.ruby_lift(row, lifted, r_i, cx) + flew
                    self.lifted_word(
                        p, QPointF(rx, by),
                        read, lift, rufm, big,
                        ox + cx, by - rufm.ascent() * 0.35 - lift)
                p.setOpacity(1.0)
                p.setFont(font)
            for f_i, (x, w, txt, s, e) in enumerate(row):
                px = ox + x
                if s is None or e is None:
                    continue
                flew, left, big = gone.get((False, r_i, f_i), STAYING)
                fade = act if left is None else left
                if fade <= 0.01:
                    continue
                frac = 1.0 if pos >= e else (0.0 if pos <= s else (pos - s) / max(1e-6, e - s))
                if not self.fill_shows(sweep, px, w, frac, fm):
                    continue
                singing = s <= pos < e
                rise = lifted.get((r_i, f_i), 0.0) + flew
                emph = emphs.get((r_i, f_i))
                if emph is not None:
                    self.emph_glow(p, emph, QPointF(px, gy), font, fm,
                                   rise, fade)
                    p.save()
                    wcx, wcy = px + w * 0.5, gy - fm.ascent() * 0.35
                    p.setPen(self.fill_pen(sweep, sung, clear, px, w, frac, fm, rtl))
                    p.setOpacity(fade)
                    self.place_word(p, QPointF(px, gy), txt, rise, fm, big,
                                    wcx, wcy - rise, emph)
                    p.restore()
                    continue
                gate = 1.0 if self.v.pop_min <= 0 else min(1.0, (e - s - self.v.pop_min) / 0.2)
                popk = (math.sin(math.pi * frac) * act * gate
                        if self.v.pop > 0 and singing and gate > 0 else 0.0)
                poplift = popk * self.v.pop * fm.height() * 0.055
                held = min(1.0, max(0.0, (e - s - 0.18) / 1.1))
                if self.HALO and self.v.glow_scale > 0 and singing and held > 0.02:
                    core = txt.strip()
                    radius, strength = self.glow_of(core, fm, held)
                    gp = self.v.glow_pixmap(core, font, radius)
                    swell = math.sin(math.pi * frac) ** 0.7
                    shimmer = 0.86 + 0.14 * math.sin(now * 6.5 + s * 4.0)
                    grow = (1.0 + 0.38 * swell * strength) * big
                    gw, gh = gp.width(), gp.height()
                    pad = radius * 3
                    ccx = (px + fm.horizontalAdvance(txt[:len(txt) - len(txt.lstrip())])
                           - pad + gw / 2)
                    ccy = gy - fm.ascent() - pad + gh / 2 - rise - poplift
                    p.setOpacity(min(1.0, fade * (0.16 + 0.66 * strength)
                                     * swell * shimmer * self.v.glow_scale))
                    blit(p,
                        QRectF(ccx - gw * grow / 2, ccy - gh * grow / 2,
                               gw * grow, gh * grow),
                        gp, QRectF(gp.rect()),
                    )
                    p.setOpacity(1.0)
                p.save()
                wcx, wcy = px + w * 0.5, gy - fm.ascent() * 0.35
                grow = (1.0 + popk * self.v.pop * 0.035 if popk else 1.0) * big
                spun = spin is not None and (r_i, x) == (spin[0], spin[1])
                if spun:
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
                p.setPen(self.fill_pen(sweep, sung, clear, px, w, frac, fm, rtl))
                p.setOpacity(fade)
                if spun:
                    p.drawText(QPointF(px, gy), txt)
                else:
                    self.lifted_word(p, QPointF(px, gy), txt, rise + poplift,
                                     fm, grow, wcx, wcy - rise - poplift)
                p.restore()
            ry += fm.height() * 1.06 + ruh
        if rrows and rfm is not None:
            rfont = self.v.roman_font(ln)
            p.setFont(rfont)
            ry += fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent()
            for rr_i, row in enumerate(rrows):
                rsweep = self.sweep_of(row, ox, pos, rfm)
                rtl = row_rtl(row)
                for rf_i, (x, w, txt, s, e) in enumerate(row):
                    if s is None or e is None:
                        continue
                    flew, left, big = gone.get((True, rr_i, rf_i), STAYING)
                    fade = act if left is None else left
                    if fade <= 0.01:
                        continue
                    frac = (1.0 if pos >= e else
                            (0.0 if pos <= s else (pos - s) / max(1e-6, e - s)))
                    px = ox + x
                    if not self.fill_shows(rsweep, px, w, frac, rfm):
                        continue
                    p.setPen(self.fill_pen(rsweep, sung, clear, px, w, frac, rfm, rtl))
                    p.setOpacity(fade * 0.85)
                    self.lifted_word(p, QPointF(px, ry), txt, flew, rfm, big,
                                     px + w * 0.5, ry - rfm.ascent() * 0.35 - flew)
                ry += rfm.height() * 1.04
        p.restore()

class Snap(Flow):
    """The stack again, with the fill switched off.

    A word does not fill in as it is held -- it takes the sung colour whole at
    the moment it starts. Everything else about the stack is inherited: the
    blur, the focus band, the pop and the rise, the troll knobs.
    """

    name = "snap"
    snap = True


def _bezier(x1: float, y1: float, x2: float, y2: float):
    """CSS's cubic-bezier(x1, y1, x2, y2), as a function of x.

    The curve is given as a parametric pair and wanted as y for a given x, so
    the parameter is found by Newton-Raphson and bisection is kept as the
    fallback for the flat stretches Newton cannot climb. Cached per curve
    because there are only ever three of them.
    """
    def bez(a, b, t):
        return (((1 - t) ** 3) * 0.0
                + 3 * ((1 - t) ** 2) * t * a
                + 3 * (1 - t) * t * t * b
                + t ** 3)

    def slope(a, b, t):
        return (3 * ((1 - t) ** 2) * a
                + 6 * (1 - t) * t * (b - a)
                + 3 * t * t * (1 - b))

    def f(x: float) -> float:
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        t = x
        for _ in range(6):
            d = slope(x1, x2, t)
            if abs(d) < 1e-6:
                break
            err = bez(x1, x2, t) - x
            if abs(err) < 1e-6:
                return bez(y1, y2, t)
            t -= err / d
        lo, hi = 0.0, 1.0
        t = x
        for _ in range(24):
            if bez(x1, x2, t) < x:
                lo = t
            else:
                hi = t
            t = (lo + hi) / 2
        return bez(y1, y2, t)
    return f


_BEZ_IN = _bezier(0.2, 0.4, 0.58, 1.0)
_BEZ_OUT = _bezier(0.3, 0.0, 0.58, 1.0)
_EASE_OUT = _bezier(0.0, 0.0, 0.58, 1.0)


def _emp_easing(x: float) -> float:
    """Up over the first half of the word, down over the second."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    if x < 0.5:
        return _BEZ_IN(x / 0.5)
    return 1.0 - _BEZ_OUT((x - 0.5) / 0.5)


_CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")

_EM = 0.83

class Sweep:
    """Where the light is along one row, this frame.

    Usually one place. Not always: a document can have two words of the same
    row sung ACROSS each other -- a trade, a second voice answering before the
    first has finished, an ad-lib written inline -- and then there are two
    voices in the row and two places the light has to be at once. A single
    edge cannot express that. It has to pick one of them, and whichever it
    picks, the other word is the one being sung with no light on it.
    """

    __slots__ = ("edges", "rtl")

    def __init__(self, edges, rtl: bool = False) -> None:
        self.edges = edges
        self.rtl = rtl

    def near(self, px: float, w: float) -> float | None:
        """The light this fragment belongs to: the nearest one BEHIND it, or
        None where every light in the row has already gone past it.

        With a single light -- which is almost every row of almost every
        document -- this hands the same one to every fragment, and the whole
        row is drawn through one gradient exactly as before. Two lights, and
        each word takes the one that is actually sweeping through it.

        Only ever asked about a fragment the voice has NOT REACHED: one part
        way through is filled from its own clock and a finished one is filled
        solid, and neither comes here (see Amll.fill_pen). So the only light
        that belongs to a fragment here is one arriving at it, and a light
        already past it belongs to some other word.

        Which is why the ones past it are dropped rather than measured. The
        gradient a light draws is sung on its left and clear on its right,
        and a gradient PADS: hand a fragment a light past its own right edge
        and every letter of it is left of the sung end, so it is painted
        solid -- a word the voice is nowhere near, lit end to end. That is
        what a row with two lights in it did to the word between them. It
        took the far one whenever that was the nearer of the two, and the
        fragment lit for the two or three frames until the light moved on:
        "Boop-boop-boop; yeah", with the "yeah" of an ad-lib stamped before
        the "boop;" in front of it, lights that "boop;" whole for 40ms as the
        "yeah" opens, and 40ms is long enough to see and short enough to look
        like a fault in the window rather than in the document.

        A light that has reached the fragment but not crossed it is kept, and
        that is the case this is here for: two voices in one row, each word
        filling from the one sweeping through it.
        """
        if self.rtl:
            got = [ed for ed in self.edges if ed >= px]
        else:
            got = [ed for ed in self.edges if ed <= px + w]
        if not got:
            return None
        if len(got) == 1:
            return got[0]
        mid = px + w * 0.5
        return min(got, key=lambda ed: abs(ed - mid))


class Emph:
    """A held word's characters, and where each of them is this frame.

    `(character, sideways, up, scale, how lit)` per grapheme, in pixels, plus
    the one blur radius they share -- AMLL animates the shadow's alpha and
    leaves its spread alone for the whole of a word's life.

    `sideways` is a finished offset from the fragment's own laid-out x, not a
    nudge: it already carries the word's opening out. It has to, because a
    word can be written as several fragments and each fragment is laid out
    against the UNSCALED widths of the ones before it. Widening a fragment on
    its own therefore walks it into the fragment after it -- measured at 12.6
    pixels of overlap on a six-letter word in two fragments, which is two
    letters drawn through each other. The whole word is laid out at once in
    emph_plan instead, and each fragment is handed its own slice of it.
    """

    __slots__ = ("parts", "radius", "held")

    def __init__(self, parts, radius: int, held: float = 1.0) -> None:
        self.parts, self.radius, self.held = parts, radius, held

    def __iter__(self):
        return iter(self.parts)


def _solve_spring(frm: float, vel: float, to: float, mass: float,
                  damping: float, stiffness: float):
    """Position at t, for a spring let go at `frm` moving at `vel`.

    The two branches are the two ways a spring can be: damped hard enough
    that it crawls in to the target, and damped less than that, so it arrives
    early and rings. Both are the standard solution; what matters here is that
    the velocity is an argument, because a spring re-aimed halfway through has
    to leave at the speed it was already going or the line visibly stops dead
    and sets off again.
    """
    delta = to - frm
    if stiffness <= 0 or mass <= 0:
        return lambda _t: to
    if damping >= 2.0 * math.sqrt(stiffness * mass):
        w = -math.sqrt(stiffness / mass)
        left = -w * delta - vel

        def over(t: float) -> float:
            return to if t < 0 else to - (delta + t * left) * math.exp(t * w)
        return over
    wd = math.sqrt(4.0 * mass * stiffness - damping ** 2)
    left = (damping * delta - 2.0 * mass * vel) / wd
    dfm = 0.5 * wd / mass
    dm = -0.5 * damping / mass

    def under(t: float) -> float:
        if t < 0:
            return to
        return to - (math.cos(t * dfm) * delta
                     + math.sin(t * dfm) * left) * math.exp(t * dm)
    return under


class Spring:
    """One number on its way to another, and how it is travelling.

    A target can be set for LATER -- that is the whole of the stagger in the
    renderer below, where every line down the column is given the same new
    place and a later moment to set off for it.
    """

    H = 1e-3

    def __init__(self, position: float = 0.0) -> None:
        self.value = self.target = float(position)
        self.t = 0.0
        self.mass, self.damping, self.stiffness = 1.0, 10.0, 100.0
        self._f = None
        self._queued = None

    def _speed(self, t: float) -> float:
        """How fast it is travelling at t, off the solved curve.

        The window either side is CLAMPED to the moment the spring was let
        go, and that is not a rounding detail. _solve_spring answers the
        TARGET for any t below zero -- it is a curve from 0 forwards and a
        flat line before it -- so a centred difference that reaches back past
        zero reads the whole remaining distance as though it had been covered
        in a millisecond. On a frame shorter than H, which is the first frame
        after every re-aim if the caller is stepping fast enough, that is a
        velocity a thousand times too big, handed straight back to _reaim by
        the next set_target. Measured, with a target that moves every frame:
        at a 1ms step the value tracks the target 50 behind, and at 0.9ms it
        is -inf inside 3000 frames.

        Clamping here rather than putting a floor under `step` in update():
        a floor makes the clock run fast, which is a spring that settles
        sooner than the caller asked for, and it would leave _accel -- which
        reads this function at t +/- H, one whole H further back -- reaching
        past zero anyway.
        """
        if self._f is None:
            return 0.0
        t = max(0.0, t)
        lo, hi = max(0.0, t - self.H), t + self.H
        return (self._f(hi) - self._f(lo)) / (hi - lo)

    def _accel(self, t: float) -> float:
        if self._f is None:
            return 0.0
        return (self._speed(t + self.H) - self._speed(t - self.H)) / (2 * self.H)

    def _reaim(self) -> None:
        v = self._speed(self.t)
        self.t = 0.0
        self._f = _solve_spring(self.value, v, self.target, self.mass,
                                self.damping, self.stiffness)

    def arrived(self) -> bool:
        """Near enough to the target, and slow enough, to stop drawing frames.

        The acceleration is in the test as well as the speed because a spring
        at the top of its swing has neither position nor velocity left but is
        about to have both.
        """
        if self._f is None and self._queued is None:
            return True
        return (self._queued is None
                and abs(self.target - self.value) < 0.01
                and abs(self._speed(self.t)) < 0.01
                and abs(self._accel(self.t)) < 0.01)

    def set_position(self, value: float) -> None:
        """Put it there, with no travel. For a document that has been replaced."""
        self.value = self.target = float(value)
        self.t = 0.0
        self._f = None
        self._queued = None

    def set_params(self, stiffness: float, damping: float,
                   mass: float = 1.0) -> None:
        if (stiffness == self.stiffness and damping == self.damping
                and mass == self.mass):
            return
        self.stiffness, self.damping, self.mass = stiffness, damping, mass
        if self._f is not None:
            self._reaim()

    def set_target(self, target: float, delay: float = 0.0) -> None:
        if delay > 0:
            if self._queued is not None:
                if abs(self._queued[1] - target) < 0.001:
                    return
            elif abs(self.target - target) < 0.001:
                return
            self._queued = (delay, float(target))
            return
        self._queued = None
        if abs(self.target - target) < 0.001:
            return
        self.target = float(target)
        self._reaim()

    def update(self, step: float) -> None:
        if self._f is None and self._queued is None:
            return
        self.t += step
        if self._f is not None:
            self.value = self._f(self.t)
        if self._queued is not None:
            left, where = self._queued
            left -= step
            if left <= 0:
                self._queued = None
                self.set_target(where)
            else:
                self._queued = (left, where)
        if self.arrived():
            self.set_position(self.target)


_SLOW = (90.0, 15.0)
_MIN_GAP, _MAX_GAP = 0.100, 0.800
_MIN_STIFF, _MAX_STIFF = 170.0, 220.0
_DAMP_MUL, _GAP_EXP = 2.2, 0.2


def _spring_policy(seeking: bool, gap: float | None) -> tuple[float, float]:
    if seeking or gap is None:
        return _SLOW
    g = min(max(gap, _MIN_GAP), _MAX_GAP)
    ratio = (1.0 - (g - _MIN_GAP) / (_MAX_GAP - _MIN_GAP)) ** _GAP_EXP
    stiff = _MIN_STIFF + ratio * (_MAX_STIFF - _MIN_STIFF)
    return stiff, math.sqrt(stiff) * _DAMP_MUL


class Amll(Flow):
    """The stack again, moved the way Apple Music-like Lyrics moves it.

    Everything about the WORDS is the stack's: the same plan, the same blurred
    pictures for distant lines, the same fill sweeping through the line being
    sung, the same rise and pop and glow and dots. What is different is how
    the column gets from one line to the next.

    The stack scrolls. There is one number -- view.scroll -- the window eases
    towards the line being sung, and every line in the column is a fixed
    distance from every other, so the whole thing arrives together like a page
    being slid.

    This does not scroll at all. Every line is given its own place in the
    window and its own spring to get there, and the springs are let go in
    order down the column, each a little after the one above it. A line change
    therefore moves the top of the column first and the bottom of it last, and
    for the fifth of a second in between, the column is not straight: it is a
    wave passing down it. That is the whole effect, and it cannot be had by
    easing a scroll, because a scroll has one number and a wave needs one per
    line.

    Because the lines carry themselves, view.scroll is left at 0 and the wheel
    does nothing -- the same bargain the pinned renderers make, for the same
    reason. AMLL's own touch-and-wheel engine, which lets a reader drag the
    column and hands it back five seconds later, is not ported.
    """

    name = "amll"
    scrolls = False

    def rest_top(self, i: int) -> float | None:
        if not 0 <= i < len(self.ys):
            return None
        sp = self.ys[i]
        return sp._queued[1] if sp._queued is not None else sp.target
    HALO = False
    HALO_SCALE = 1.0
    HALO_SIZE = 1.0
    SWELL = 0.0
    BOB = 0.0

    ALIGN = 0.40
    SCALE = 0.97
    STAGGER = 0.05
    STAGGER_DECAY = 1.05
    MAX_STEP = 0.10
    FADE = 0.25
    JITTER = 0.15
    DRIFT = 0.5
    UNTRUSTED = 0.8
    FOCUS_FADE = 3

    def __init__(self, view) -> None:
        super().__init__(view)
        self._key = None
        self.ys: list[Spring] = []
        self.scales: list[Spring] = []
        self._last_pos = None
        self._last_t = None
        self._wall = 0.0
        self.offset = 0.0
        self._bounds = (0.0, 0.0)
        self._sought = None
        self._focal_was = None
        self._early = 0
        self._jolt = False
        self._last_top = None
        self._held = None
        self.now = mono

    def focus_trim(self, dist: int):
        """The same band, taken away gradually, because here it is watched.

        Flow.focus_trim cuts at N+1 and is right to: a scrolling column has
        already carried a line that far out into the viewport gradient, so
        the line the cut takes was a ghost before it was taken.

        This column does not scroll. Every line springs to a place of its
        own around the window's Line height, the gradient's centre, and it
        is packed the way AMLL packs it -- so the line sitting at N+1 here
        is still perfectly legible when the focal line moves on and the cut
        reaches it. Cutting there does not read as
        focus. It reads as a line being DELETED in mid-air, one row below
        something the reader is in the middle of, on the beat of every line
        change.

        So the band keeps going past the edge instead, at a share of the ring
        that falls away over FOCUS_FADE more lines and is squared so it goes
        quickly, which the depth blur is riding up to MAX_BLUR through at the
        same time. By the last of them the line is carrying about two parts
        in a thousand of the ink, which is nothing to look at and nothing to
        draw -- and THAT is where it is dropped, on a line nobody can see
        rather than on one they can.

        Focus still means what the knob says: N lines either side is what is
        readable, and the rest is periphery. What it no longer does is take
        the periphery away while someone is looking at it.

        Not under zero-g or the clouds, which cut a line into its words and
        draw them one at a time -- there is no cached picture to lean on, so
        a line carrying two parts in a thousand of the ink costs exactly what
        the line being sung costs. _warm_next stands down in those two modes
        for the same reason. The hard cut comes back, and it is the right
        trade: a mode that is already throwing the words about is not one
        where a line leaving quietly is what anybody is looking at.
        """
        edge = self.v.focus + 1
        if dist <= edge:
            return (0.35, True) if dist == edge else (1.0, False)
        if self.v.zero_g > 0 or self.v.clouds > 0:
            return None
        over = dist - edge
        if over > self.FOCUS_FADE:
            return None
        return (0.35 * (1.0 - over / (self.FOCUS_FADE + 1)) ** 2, True)

    def line_scale(self, i: int) -> float:
        """Where line `i`'s own spring has got to between 1.0 and SCALE.

        Read by the window for the review marks, so it has to be the value
        the line was actually DRAWN at this frame, not the target -- half way
        through the grow they are different by most of the effect.
        """
        return self.scales[i].value if i < len(self.scales) else 1.0

    def animating(self) -> bool:
        return (self.offset != 0.0
                or any(not s.arrived() for s in self.ys)
                or any(not s.arrived() for s in self.scales))

    def wheel(self, dy: float) -> bool:
        """Taken, while the column is this renderer's to move.

        It is not always. An unsynced document has no clock to spring to, so
        paint hands the frame to the stack, and the stack moves the column
        with view.scroll -- nothing on that path ever reads the offset this
        would move. Taking the wheel there was taking it nowhere: a page of
        static lyrics could not be scrolled at all under this renderer, which
        is the one kind of document a reader has to scroll BY HAND, because
        there is no clock to carry them down it.

        Declined, and the window falls through to its own scroll, which is
        what is actually drawing the column at that moment.

        The step lands on the offset whole rather than being eased into it,
        because the easing is already there: every line springs to its new
        place, so a notch of the wheel is carried by the same movement a line
        change is, with the same stagger running down the column. That is what
        AMLL does with a wheel step too -- its DiscreteScroll relayout moves
        the targets and lets the springs do the rest.
        """
        if not self.v.synced:
            return False
        lo, hi = self._bounds
        was = self.offset
        self.offset = max(lo, min(hi, self.offset - dy * 0.7))
        self._jolt = self._jolt or self.offset != was
        return True

    def _rebase(self, plan, H: int) -> bool:
        """A new SONG under the renderer means new springs.

        Everything remembered here is remembered by LINE NUMBER, and a line
        number means nothing once the next song is on -- the same trap the
        pinned renderers document at Pinned.forget.

        The new springs start two windows below the bottom, which is where
        AMLL starts a rebuilt view, so a song arrives by flying up into place
        with the stagger running down it rather than by being switched on.

        Keyed on the TRACK, which is the only thing that actually answers the
        question. A document is replaced far more often than the song
        changes: a better source arriving mid-song hands over a new one, and
        the reader is told about it by the whole column scrolling in from
        below to announce lyrics that were already on screen.

        Keying on the list it came in was wrong -- every replacement is a new
        list. Keying on the WORDS was wrong too, and less obviously: a better
        source is a different transcription, so the punctuation and the
        capitals move, and prepare() puts interlude markers in where the gaps
        are, so a corrected clock can add or drop a line and change the count.
        Either is enough to make the same song look like a different one.

        The track id changes when the song does and at no other time, so that
        is what this asks. Where there is no clock to ask -- a fixture, a
        test -- it falls back to the words, which is at least stable across a
        re-timing.

        Being handed a different NUMBER of lines for the same song is a
        separate question from being handed a different song: the springs
        have to be resized either way, but only a new song arrives from
        below. See below the key.
        """
        v = self.v
        tid = getattr(getattr(v, "clock", None), "tid", None)
        key = ("tid", tid) if tid else (
            "ink", len(v.lines),
            hash(tuple((ln.get("text") or "") for ln in v.lines)))
        same = self._key == key
        self._key = key
        if same and len(self.ys) == len(plan):
            return False
        if same and self.ys:
            hold = self.ys[-1].value
            self.ys = [self.ys[i] if i < len(self.ys) else Spring(hold)
                       for i in range(len(plan))]
            self.scales = [self.scales[i] if i < len(self.scales)
                           else Spring(1.0) for i in range(len(plan))]
            return False
        below = float(H * 2)
        self.ys = [Spring(below) for _ in plan]
        self.scales = [Spring(1.0) for _ in plan]
        self._last_pos = self._last_t = None
        self.offset, self._held, self._jolt = 0.0, None, False
        self._last_top = self._sought = self._focal_was = None
        self._early = 0
        return True

    def _step(self) -> float:
        """Seconds since the last frame, clamped. See MAX_STEP.

        The unclamped figure is kept as `self._wall`, because the clamp is for
        the springs and the seek detector needs the truth: a frame that really
        did take a second is a frame the song really did advance a second in,
        and comparing it against a tenth would call that a seek.
        """
        now = self.now()
        last, self._last_t = self._last_t, now
        if last is None:
            self._wall = 0.0
            return 0.0
        self._wall = max(0.0, now - last)
        return min(self.MAX_STEP, self._wall)

    def _seeking(self, pos: float, wall: float, playing: bool) -> bool:
        """Did the song JUMP, or did it just play on? See JITTER."""
        last, self._last_pos = self._last_pos, pos
        if last is None:
            return True
        if wall > self.UNTRUSTED:
            return False
        want = wall if playing else 0.0
        return abs((pos - last) - want) > self.JITTER + want * self.DRIFT

    def _focal(self, pos: float, n: int, seeking: bool = False) -> int:
        """The line the column is built around.

        The window's own answer, so this renderer and every other one agree
        about where the song is -- and, more to the point, so that a line
        whose end has been stretched over an ad-lib written into it does not
        hold the column while the next line sings. See view.focus_line.

        With one exception, for the case that answer is not written for.
        focus_index never scrolls away from a line that is still sounding,
        which is right while the song is playing and wrong the instant someone
        CLICKS a line: a line beginning under the tail of the one before it
        then lands on the line before it, and the column travels there, waits
        for that line to finish, and only then goes on to the line that was
        actually asked for. Two moves, and the first of them to the wrong
        place.

        So a seek that lands exactly on a line's own start -- which is what a
        click is, and what nothing else produces -- pins the column to that
        line, and holds it there until the song's own answer catches up with
        it. Nothing about playback changes: this can only ever move the focus
        FORWARD, to a line that has already begun.
        """
        i = self.v.focus_line(pos)
        if i is None or i < 0 or i >= n:
            live = self.v.sounding(pos)
            i = min(live) if live else 0
        i = max(0, min(n - 1, i))

        if self._sought is not None and self._sought >= n:
            self._sought = None
        if self._focal_was is not None and self._focal_was >= n:
            self._focal_was, self._early = None, 0
        if seeking:
            self._sought = self._clicked(pos, n)
        if self._sought is not None:
            if i >= self._sought:
                self._sought = None
            else:
                i = self._sought
            self._focal_was, self._early = i, 0
            return i

        if self._focal_was is not None and i < self._focal_was - 1:
            self._early += 1
            if self._early < 3:
                return self._focal_was
        else:
            self._early = 0
        self._focal_was = i
        return i

    CLICK_SNAP = 0.05

    def _clicked(self, pos: float, n: int):
        """The line a seek landed on the start of, if it landed on one."""
        for i, ln in enumerate(self.v.lines[:n]):
            start = ln.get("start")
            if start is None or ln.get("background") or ln.get("credits"):
                continue
            if abs(start - pos) <= self.CLICK_SNAP:
                return i
            if start > pos + self.CLICK_SNAP:
                break
        return None

    def _gap(self, focal: int) -> float | None:
        """Seconds between the line being sung and the one before it."""
        lines = self.v.lines
        if focal <= 0 or focal >= len(lines):
            return None
        here, prev = lines[focal].get("start"), lines[focal - 1].get("start")
        if here is None or prev is None:
            return None
        return max(0.0, here - prev)

    def _fade(self, fm: QFontMetricsF) -> float:
        return max(0.75, self.v.edge * fm.height() * self.FADE)

    def sweep_of(self, row, ox: float, pos: float, fm: QFontMetricsF):
        """Every light burning along this row, or None before any of them.

        A fragment part way through its own span puts a light where the voice
        has got to inside it. Normally exactly one fragment is in that state
        and the row has one light; where two words are sung across each other
        it has two, and both words fill at once. See Sweep.

        The whole row is read, never broken out of early. Breaking at the
        first fragment that has not started was the bug: stamps are not always
        in reading order -- a line with an ad-lib written into it can have its
        last word start before its second-to-last -- and stopping there left
        a word that really was being sung with no light on it until whatever
        preceded it in the ROW caught up.

        With nothing mid-flight the light waits at the end of the furthest
        word finished, which is AMLL's pause segment: through a gap in the
        timing the sweep holds rather than running on to meet the next word.
        """
        edges, done = [], None
        rtl = row_rtl(row)
        for x, w, txt, s, e in row:
            if s is None or e is None or not txt.strip():
                continue
            if pos >= e:
                if rtl:
                    left = ox + x
                    done = left if done is None else min(done, left)
                else:
                    right = ox + x + w
                    done = right if done is None else max(done, right)
            elif pos > s:
                f = (pos - s) / max(1e-6, e - s)
                edges.append(ox + x + w * ((1.0 - f) if rtl else f))
        if not edges:
            if done is None:
                return None
            edges = [done]
        else:
            edges.sort()
        return Sweep(edges, rtl)

    def fill_shows(self, sweep, px: float, w: float, frac: float,
                   fm: QFontMetricsF) -> bool:
        if sweep is None:
            return False
        if frac > 0:
            return True
        soft = self._fade(fm)
        ed = sweep.near(px, w)
        if ed is None:
            return False
        return px + w > ed - soft if sweep.rtl else px < ed + soft

    def fill_pen(self, sweep, sung: QColor, clear: QColor, px: float,
                 w: float, frac: float, fm: QFontMetricsF, rtl: bool = False):
        soft = self._fade(fm)
        if frac >= 1.0:
            return sung
        if frac > 0.0:
            ed = px + w * ((1.0 - frac) if rtl else frac)
        else:
            ed = sweep.near(px, w)
            if ed is None:
                return clear
        return sung_grad(ed, soft, sung, clear, rtl)


    EMP_MIN = 1.0
    EMP_CHARS = 7
    FLOAT_MIN = RISE_TIME
    EMP_LEAD = RISE_LEAD
    SETTLE = 0.25
    CHAR_STEP = RISE_LEAD
    RISE = 0.055

    _GRAPHEMES: dict = {}

    def syll_bar(self) -> float:
        """How long a SYLLABLE must be held to be one, or 0 for the word.

        The window's knob, read through a default because the renderers are
        also driven by the stub views in the tests, which borrow the real
        methods off LyricsView rather than inheriting its state. A knob added
        here should not be a thing each of those has to learn about before
        anything will paint.
        """
        return max(0.0, float(getattr(self.v, "syll_hold", 0.0) or 0.0))

    @classmethod
    def graphemes(cls, txt: str) -> tuple:
        """A word split the way it is READ, not the way it is stored.

        AMLL reaches for Intl.Segmenter here. There is no such thing to hand,
        so this is the part of it that matters for lyrics: a base character
        keeps whatever hangs off it -- accents, a variation selector, the
        joiner in a compound emoji -- instead of being torn off it and given
        a scale and a float of its own.
        """
        hit = cls._GRAPHEMES.get(txt)
        if hit is None:
            out, cur, join = [], "", False
            for ch in txt:
                if cur and (join or ch in "\u200d\ufe0f"
                            or unicodedata.combining(ch)):
                    cur += ch
                else:
                    if cur:
                        out.append(cur)
                    cur = ch
                join = ch == "\u200d"
            if cur:
                out.append(cur)
            hit = cls._GRAPHEMES[txt] = tuple(out)
        return hit

    @classmethod
    def emphasized(cls, core: str, dur: float, bar: float = 0.0) -> bool:
        """Whether this word is being HELD, as against merely being long.

        With `bar` above zero the question is asked about a SYLLABLE instead,
        and the whole of it is "was this piece held that long" -- see
        emph_plan, which is where the unit is chosen. Both of AMLL's guards
        are dropped with the unit, deliberately: the letter rate below is a
        measure of how much text there is to get through and a syllable is
        one mouthful by construction, and the single-letter rule is about a
        one-letter WORD, where the whole of the note is one character. The
        "o" of a held "o-oh" is neither, and it is exactly what this is for.

        AMLL's shouldEmphasize, and the length cap is the interesting half of
        it: a second of "understanding" is a word being pronounced and a
        second of "stay" is a note. Only the second is a performance, so only
        the second lights up. The stack lights both, because it decides on
        duration alone -- which is why a slow line there can have four or five
        words glowing at once and a line here has one.

        The cap is a RATE, not a ceiling, and that is the one place this
        parts from AMLL. Written as a ceiling it says a word of more than
        EMP_CHARS letters is never a performance however long it is held --
        which is how "Titanium", eight letters and four seconds of the
        chorus, sat there unlit, and "compares" held 14.7s at the end of
        Clocks with it. What the ceiling is really asking is whether the
        time is being SPENT on saying the word, and that question is per
        letter: AMLL's own corner, seven letters in a second, is a seventh
        of a second each, so every letter past the seventh buys the word
        another seventh of a second to earn. Below the corner this is AMLL
        exactly -- at EMP_CHARS letters or fewer the bar is EMP_MIN and
        nothing else -- and above it the line goes on instead of stopping.

        Measured over the 62180 words in this folder, against the same
        fragment grouping the layout uses: 2304 lit before and 487 more do
        now, 0.8% of the words, and not one that lit before goes dark. The
        median new one is nine letters held 1.86s. "understanding" at 1.6s
        is still turned down, because thirteen letters ask for 1.86s.

        CJK is exempt because the rate is counting the wrong thing there: a
        whole phrase is a handful of characters.

        Right-to-left words never are: the emphasis moves each letter on its
        own, which pulls joined Arabic apart into its isolated forms, and the
        letter positions it reads are laid out left to right. Spicy turns its
        letter groups off for them for the same reason.
        """
        if _rtl(core):
            return False
        if bar > 0.0:
            return bool(core) and dur >= bar
        if dur < cls.EMP_MIN:
            return False
        if _CJK.search(core):
            return True
        n = len(core)
        return 1 < n and dur >= cls.EMP_MIN * n / cls.EMP_CHARS

    def emph_plan(self, rows, pos: float, fm: QFontMetricsF,
                  bg: bool = False, font: QFont | None = None) -> dict:
        """Held WORDS, not held syllables.

        This is the thing that stopped it firing at all. AMLL asks
        shouldEmphasize about a word, and a word there is the whole word --
        the merged chunk, with the whole note's length on it. The rows here
        are cut into SYLLABLES, and a note held two seconds over three of them
        has not one syllable lasting a second, so the gate turned every one of
        them down and nothing in the document ever lit up.
        
        So the syllables are grouped back into the words they spell -- which
        Renderer.words_of already does, and span_of already dates -- the gate
        is asked about the word, and the characters of the word are then dealt
        back out to the syllables that own them. The stagger and the push are
        therefore cut across the whole word, which is also what AMLL does:
        both count from the word's first character, not from each syllable's.

        `syll_hold` puts the unit back to the syllable, on purpose and with
        its own bar. The reason the word is the unit above is that a syllable
        cannot clear a bar of EMP_MIN -- the median one in these documents is
        a quarter of a second -- so the gate is no use at the smaller unit
        until it is told a smaller number, and that number is the setting.
        Given one, every piece the document was timed into is judged on its
        own length: the run is split here, before the tail is picked, and
        everything downstream is unchanged because a one-piece run is a shape
        it already handles. What changes on screen is that a word stops
        moving as one thing. "Ti|ta|ni|um" with the hold on its last piece
        lights that piece and leaves the other three alone, where the word
        unit lights all eight letters off the whole four seconds.

        The bar is what decides how much of a song glows, and it is steep.
        Over the 71922 timed pieces in this folder: 1.0s lights 3.5% of them
        and leaves something lit in 22% of the 8892 lines, which is roughly
        what the word unit does at 25%; 0.75s is 33% of lines, 0.5s is 56%,
        and 0.4s is 70%. So the number is not a threshold to be tuned around
        a word -- it is the density knob, and the word unit sits at the top
        of its range.
        """
        font = font or self.v.lyric_font(bg)
        bar = self.syll_bar()
        tail = None
        runs_by_row = []
        for r_i, row in enumerate(rows):
            runs = [[(k, f) for k, f in run if f[2].strip()]
                    for run in self.words_of(row)]
            runs = [r for r in runs if r]
            if bar > 0.0:
                runs = [[piece] for run in runs for piece in run]
            runs_by_row.append(runs)
            if runs:
                tail = (r_i, len(runs) - 1)

        out = {}
        for r_i, runs in enumerate(runs_by_row):
            for w_i, run in enumerate(runs):
                core = "".join(f[2] for _k, f in run).strip()
                s, e = self.span_of(run)
                chars = [self.graphemes(f[2].strip()) for _k, f in run]
                flat = tuple(c for g in chars for c in g)
                arrive = []
                for (_k2, frag), g in zip(run, chars):
                    fs = frag[3] if frag[3] is not None else s
                    fe = frag[4] if frag[4] is not None and frag[4] > fs else fs
                    step = min(self.CHAR_STEP, (fe - fs) / max(1, len(g)))
                    for j in range(len(g)):
                        arrive.append(fs + step * j)
                got = self.emph_of(core, s, e, pos, fm,
                                   (r_i, w_i) == tail, bg, flat, arrive,
                                   self.voiced_of(run))
                if got is None:
                    continue
                spans, at = [], 0
                for (_k2, frag), g in zip(run, chars):
                    core_f = frag[2].strip()
                    offs_f = self.shaped_offsets(core_f, font, fm)
                    total_f = fm.horizontalAdvance(core_f)
                    c_at = 0
                    for gi, gch in enumerate(g):
                        nxt = c_at + len(gch)
                        end = offs_f[nxt] if nxt < len(offs_f) else total_f
                        spans.append([frag[0] + offs_f[c_at],
                                      max(0.0, end - offs_f[c_at]),
                                      frag[0], at + gi])
                        c_at = nxt
                    at += len(g)
                if not spans:
                    continue
                left = spans[0][0]
                plain = (spans[-1][0] + spans[-1][1]) - left
                grown = sum(sp[1] * got.parts[sp[3]][3] for sp in spans)
                cur = left + (plain - grown) * 0.5
                placed = {}
                for sp in spans:
                    wide = sp[1] * got.parts[sp[3]][3]
                    placed[sp[3]] = (cur + (wide - sp[1]) * 0.5) - sp[2]
                    cur += wide
                at = 0
                for (k, _f), g in zip(run, chars):
                    if g:
                        out[(r_i, k)] = Emph(
                            [(c[0], placed[at + gi], c[2], c[3], c[4])
                             for gi, c in enumerate(got.parts[at:at + len(g)])],
                            got.radius, got.held)
                    at += len(g)
        return out

    def emph_of(self, txt: str, s, e, pos: float, fm: QFontMetricsF,
                last: bool, bg: bool, parts=None, arrive=None, voiced=None):
        """Where every character of a held word is, this frame.

        Three movements at once, each on its own clock, which is what makes
        this a different thing from the stack's pop rather than a tuning of
        it:

          * the characters grow, and the word opens out by exactly as much
            as they grow, so the letters keep the gaps they were set with.
            AMLL does that with a separate sideways push of a fixed share of
            the em; this does it by giving each character a slot as wide as
            its own scaled advance. See emph_plan for why the push could not
            do the job on this face;
          * each one floats up and back down on a sine, setting off EMP_LEAD
            before its own glow and running 1.4 times as long, so the movement
            is already under way when the light arrives;
          * the light swells and dies on a two-piece bezier that is not
            symmetric -- see _emp_easing, which comes up on one curve and
            leaves on another.

        and each character is started a little after the one before it, by a
        fifth of the word's length divided between them. That stagger is the
        reason any of this is per character: without it the letters all do the
        same thing at the same moment, which is a word scaling, which is the
        pop the stack already has.

        How MUCH of all that is a curve on the word's length -- cubed while it
        is under two seconds and square-rooted past it, so a note held briefly
        barely moves and a long one does not run away with the line. The last
        word of a line is given half again, which is AMLL putting a button on
        the end of the phrase.

        The window's own knobs still mean what they mean: `pop` scales the
        movement, `glow_scale` the light and `rise` the float.
        """
        core = txt.strip()
        if s is None or e is None or not core:
            return None
        held_for = (e - s) if voiced is None else voiced
        if not self.emphasized(core, held_for, self.syll_bar()):
            return None
        if parts is None:
            parts = self.graphemes(core)
        n = len(parts)
        if not n:
            return None
        du = max(self.EMP_MIN, held_for)

        amount = du / 2.0
        amount = math.sqrt(amount) if amount > 1.0 else amount ** 3
        amount *= 0.6

        held = min(1.0, max(0.0, (held_for - 0.18) / 1.1))
        radius, lit = self.glow_of(core, fm, held)
        if last:
            amount, lit, du = amount * 1.6, lit * 1.5, du * 1.2
        amount = min(1.2, amount) * self.v.pop
        lit = min(1.0, lit) * self.v.glow_scale

        em = fm.height() * _EM
        if arrive is None:
            arrive = [s + ((e - s) / n) * i for i in range(n)]
        offs = [max(0.0, a - s) for a in arrive]

        ends = (e - s) + self.SETTLE
        spans = [max(0.25, ends - o) for o in offs]
        swell = fm.height() * self.RISE * min(1.0, self.v.rise)
        word_k = max((_emp_easing(max(0.0, min(1.0, (pos - (s + o)) / sp)))
                      for o, sp in zip(offs, spans)), default=0.0)
        word_scale = 1.0 + word_k * 0.1 * amount * self.SWELL

        out, alive = [], False
        for i, ch in enumerate(parts):
            de = s + offs[i]
            k = _emp_easing(max(0.0, min(1.0, (pos - de) / spans[i])))
            x = (pos - (de - self.EMP_LEAD)) / spans[i]
            up = math.sin(math.pi * x) * swell if 0.0 < x < 1.0 else 0.0
            if k > 1e-3 or up > 0.01:
                alive = True
            out.append((ch,
                        0.0,
                        up * self.BOB + k * 0.025 * amount * em * self.BOB,
                        word_scale,
                        k * lit))
        if not alive:
            return None
        return Emph(out, radius, held)

    def word_lifts(self, rows, fm: QFontMetricsF, pos: float, act: float,
                   blur: float, bg: bool = False) -> dict:
        """How far each word has floated, on AMLL's schedule rather than the
        stack's.

        The two disagree about what a float is FOR. The stack gives every
        syllable a fixed window of a third of a second, set off a frame or two
        early and held down to whatever the syllable in front of it reached,
        so that what crosses the line is a wave in reading order and never a
        word standing up out of turn -- and the docstring at RISE_LEAD records
        that a wider schedule was tried there and rejected, because two or
        three words off the floor at once reads as the line guessing ahead of
        the voice.

        AMLL's is the wider schedule. A word floats over its own LENGTH, so a
        held note climbs for as long as it is held and several words really
        are in the air together. That is the thing the stack decided against,
        and it is here because it is what this renderer is a port of: on a
        line of short words the whole line drifts up, and on a held one the
        note rises with it. It is ease-out and it does not come back down --
        the word stays where it got to.

        One float per WORD, though, not per syllable, and this is the other
        half of why the two schedules cannot be mixed. The stack can afford a
        lift per syllable because each one is over in a third of a second and
        the next is already climbing before the last has settled -- a wave
        through the word, not a seam. Run over each syllable's OWN length
        instead and the seam stops being momentary: a word split "sta" + "y"
        with the hold on the second syllable has the first floating over a
        third of a second and the second over a second and a half, so the
        front half of the word stands up while the back half is still on the
        floor, and stays there. The word tears in two and holds the pose.

        So every syllable of a word is given the word's own span and the same
        lift, and the word goes up in one piece. That is also what AMLL means
        by a word: the thing it emphasises is the merged chunk, not the pieces
        the timing happens to be written in.

        What a word is, though, is settled by Renderer.words_of, and a piece
        that ends in a HYPHEN ends one. That is not a syllable split -- it is
        a stutter, a spell-out or a hyphenated compound, and each piece of it
        is an utterance the voice arrives at separately. Read as one word they
        went up as a slab: "fuck-fuck-fuck-fuck-fuck" rose once over the whole
        of itself instead of five times, and so did every "F-R-I-E-N-D-S" in
        the chorus of one. The tearing this schedule has to avoid is a word
        coming apart at a seam nobody wrote; a hyphen is a seam somebody did.

        The one other departure is the floor under that length, and it is
        there so that the `rise` knob means the same amount of movement here
        as it does everywhere else in the window. See FLOAT_MIN.
        """
        if self.v.rise <= 0 or act <= 0.01 or blur >= 1.0:
            return {}
        unit = self.v.lyric_fm(False).height()
        full = self.on_grid(unit * self.RISE * self.v.rise * act * (1.0 - blur))
        out = {}
        last_s, cap = None, 1.0
        for r_i, row in enumerate(rows):
            for run in self.words_of(row):
                run = [(k, f) for k, f in run if f[2].strip()]
                if not run:
                    continue
                s, e = self.span_of(run)
                if s is None:
                    continue
                s = s if last_s is None else max(s, last_s)
                last_s = s
                span = (e - s) if e is not None and e > s else 0.0
                du = max(self.FLOAT_MIN, span)
                cap = k = min(cap, _EASE_OUT(max(0.0, min(1.0, (pos - s) / du))))
                if k <= 0.001:
                    continue
                lift = k * full
                for f_i, _frag in run:
                    out[(r_i, f_i)] = lift
        return out

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        if not v.synced:
            self.offset = 0.0
            self._last_top = None
            super().paint(p, x0, width, H)
            return

        pos = v.position() - v.track_offset()
        live = v.sounding(pos)
        plan, total = self.plan(width)
        v.content_h = 0.0
        if not plan:
            v.line_rects = []
            return

        fresh = self._rebase(plan, H)
        playing = getattr(getattr(v, "clock", None), "status", "") == "Playing"
        step = self._step()
        seeking = self._seeking(pos, self._wall, playing)
        focal = self._focal(pos, len(plan), seeking)

        reading = mono() < getattr(v, "user_scroll_until", 0.0)
        if reading:
            if self._held is None:
                self._held, self._jolt = focal, True
            focal = min(self._held, len(plan) - 1)
        else:
            if self._held is not None or self.offset != 0.0:
                self._jolt = True
            self._held = None
            self.offset = 0.0

        v.focus_idx = focal

        stiff, damp = _spring_policy(seeking, self._gap(focal))

        base = (H * getattr(self.v, "focus_height", self.ALIGN)
                - plan[focal][1] / 2 - plan[focal][0])
        self._bounds = (min(0.0, -plan[focal][0]),
                        max(0.0, base + total - H / 2))
        self.offset = max(self._bounds[0], min(self._bounds[1], self.offset))
        top = base - self.offset

        stride = plan[focal][1] * 2.0
        shift = 0.0 if self._last_top is None else top - self._last_top
        gentle = self._last_top is not None and -stride <= shift <= 0.01
        self._last_top = top
        spacing = (self.STAGGER
                   if gentle and not (seeking or fresh or self._jolt)
                   else 0.0)
        self._jolt = False
        small = 1.0 + (self.SCALE - 1.0) * (1.0 - v.browse)
        delay = 0.0
        for i, entry in enumerate(plan):
            y = top + entry[0]
            sp = self.ys[i]
            sp.set_params(stiff, damp, 0.9)
            if fresh and i == focal:
                sp.set_target(y)
            else:
                sp.set_target(y, delay)
            sp.update(step)

            sc = self.scales[i]
            sc.set_params(100.0, 25.0, 2.0)
            lit = i == focal or i in live
            sc.set_target(1.0 if (lit or not playing) else small, delay)
            sc.update(step)

            if y + entry[1] >= 0:
                delay += spacing
                if i >= focal:
                    spacing /= self.STAGGER_DECAY

        m = H if (v.zero_g > 0 or v.clouds > 0) else 40
        clouds = v.clouds > 0
        rects, deferred = [], []
        for i, (off, h, lo, hi, rows, fm, rrows, rfm, ruby, rufm) in enumerate(plan):
            y = self.ys[i].value
            rects.append((i, y + v.scroll, h, x0 + lo, x0 + hi))
            if y >= H + m or y + h <= -m:
                continue
            if clouds and live and min(abs(i - j) for j in live) > 3:
                continue
            args = (i, v.lines[i], rows, fm, x0, y, pos, live,
                    rrows, rfm, ruby, rufm)
            if clouds and (i in live or v.activation.get(i, 0.0) > 0.02):
                deferred.append((args, self.scales[i].value, y, h))
            else:
                self._scaled(p, args, self.scales[i].value, x0, width, y, h)
        for args, s, y, h in deferred:
            self._scaled(p, args, s, x0, width, y, h)
        v.line_rects = rects
        self._warm_next(plan, live, width)

    def _scaled(self, p, args, s: float, x0: float, width: float,
                y: float, h: float) -> None:
        """One line, under its own scale if it has one.

        The transform is skipped entirely at full size rather than applied as
        an identity, because a painter under ANY transform resamples the
        pictures the stack blurs its distant lines into. The line being sung
        is the one at full size, so the line that has to be sharp is the one
        that never sees a transform.
        """
        if abs(s - 1.0) < self.SCALE_EPS:
            self._paint_line(p, *args)
            return
        p.save()
        self.scale_about(p, s, x0, width, y, h)
        self._paint_line(p, *args)
        p.restore()


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
    ADLIB_GAP = 0.22

    CREDIT_AFTER = 0.0

    def __init__(self, view) -> None:
        super().__init__(view)
        self._ikey = None
        self._idx = ({}, {}, [], {})
        self._page = None
        self._endkey, self._end, self._first = None, None, None

    def song_end(self) -> float | None:
        """The last moment this document has anything to say, or None.

        Worked out once per document, the way _index is: a new lyric is a new
        list rather than an edited one, so its identity and length are enough
        to notice one. The credits row has no clock and the interludes are not
        words, so neither counts -- what is wanted is when the singing stops.
        """
        key = (self.v.lines, len(self.v.lines))
        if not self._same_doc(self._endkey, key):
            end = first = None
            for ln in self.v.lines:
                if ln.get("credits") or ln.get("dots"):
                    continue
                t0 = ln.get("start")
                if isinstance(t0, (int, float)):
                    first = t0 if first is None else min(first, t0)
                for t in (ln.get("end"), ln.get("start")):
                    if isinstance(t, (int, float)):
                        end = t if end is None else max(end, t)
                        break
            self._endkey, self._end, self._first = key, end, first
        return self._end

    def credits_due(self, pos: float) -> bool:
        """Whether the credit belongs on the screen: once the song is over,
        or with credits_top on, until its first line starts."""
        end = self.song_end()
        if getattr(self.v, "credits_top", False):
            return self._first is not None and pos < self._first
        return end is not None and pos >= end + self.CREDIT_AFTER

    @property
    def stacked(self) -> bool:
        """Only on the static page, which is the stack's own layout.

        These renderers set their own type and lay their own rows out, so the
        window cannot work out where a word of theirs ended up -- which is
        what `stacked` asks, and why the review marks go to the margin under
        them. A document with no clock is drawn by the stack instead (see
        static_page), and on that path the layout IS the window's, so the
        rules can go back under the words.
        """
        return not self.v.synced

    def static_page(self, p, x0: float, width: float, H: int) -> bool:
        """A document with no clock, printed as a page. True if it was.

        These renderers are about WHERE THE VOICE IS: one line held in the
        middle of the window, the next one waiting, the last one fading out.
        Take the clock away and there is no voice to be anywhere, and what
        they did with that was draw nothing at all -- `live` is empty, so
        `current` has no line to build a frame around and the paint fell
        straight through to the end. A reader who had chosen one of these and
        opened a page of untimed lyrics got an empty window.
        (Cards is the exception and does not come here: it lays the whole
        document out already, so it has a page to draw without a clock. What
        it had instead was every card dimmed as un-sung -- see its paint.)

        The stack knows how to print a page of text, and it moves that page
        with view.scroll, which is the thing the window scrolls when a
        renderer declines the wheel -- so this hands over whole rather than
        reimplementing a static column here. It is the same answer Amll
        reaches for on the same path, and for the same reason.

        The stack is built on first use and kept: a renderer is made once per
        window and a document arrives unsynced far more often than never,
        but there is no reason for every one of these to carry a second
        renderer around for a document that may never come.
        """
        if self.v.synced:
            return False
        if self._page is None:
            self._page = Flow(self.v)
        self._page.paint(p, x0, width, H)
        return True

    def font(self, px: float) -> QFont:
        """The lyric face at a size of this renderer's choosing."""
        return self.v.ui_font(px, QFont.Weight.Black)

    def rows_of(self, ln: dict, fm: QFontMetricsF, width: float,
                align: str = "center"):
        return self.v.wrap_pieces(self.v.line_pieces(ln), fm, width, align)

    def singable(self, i: int) -> bool:
        """A line these renderers have anything to say about.

        The trailing credits block is a paragraph about the document, not a
        line of the song, so it is never one of the lines these pick between,
        never takes a band or a card of its own, and is never the line the
        clock is on. It is still DRAWN -- attribution has to be wherever the
        lyrics are -- by credits_block, under whatever the renderer put last
        on the screen, or at the foot of the column where there is one.
        """
        ln = self.v.lines[i]
        return not ln.get("credits")

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
        key = (v.lines, len(v.lines))
        if not self._same_doc(self._ikey, key):
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

    @staticmethod
    def _same_doc(had, key) -> bool:
        """Whether (lines, count) is the document `had` was worked out for.

        The list itself is held and compared by `is`, not remembered by id():
        a song's list is freed when the next one replaces it, and the next can
        be born at the same address -- with the same number of lines, that was
        the old song's index handed to the new one.
        """
        return had is not None and had[0] is key[0] and had[1] == key[1]

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
        rtl = row_rtl(row)
        for f_i, (x, w, txt, s, e) in enumerate(row):
            px = ox + x
            p.save()
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
                    edge = px + w * ((1.0 - frac) if rtl else frac)
                    soft = max(0.75, self.v.edge * fm.height() * 0.22)
                    p.setPen(sung_grad(edge, soft, sung, clear, rtl))
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

    The credit goes under the lowest of them once the song has finished, for
    the same reason it is hung off the real height rather than a guess: where
    the lines end is not known until they are drawn.
    """

    name = "spotlight"
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
        now = mono()
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
        return bool(self.gone)

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        if self.static_page(p, x0, width, H):
            return
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
        foot += self.draw_adlibs(p, cur, live, small, fm_sm, x0, width, foot,
                                 pos)
        under = foot
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
            if below:
                under = top + h
        if self.credits_due(pos):
            self.credits_block(p, x0, width, under + fm_sm.height() * 0.5, H)


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

    The credit sits under the lower band once the song has finished,
    whichever of the two that turned out to be.
    """

    name = "karaoke"
    LEAD = 2.0

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        if self.static_page(p, x0, width, H):
            return
        v.line_rects = []
        v.content_h = 0.0
        pos = v.position() - v.track_offset()
        cur, nxt = self.current(pos)
        if cur is None:
            return
        font, small = self.font(v.lyric_px() * 0.94), self.font(v.lyric_px() * 0.58)
        fm, fm_sm = QFontMetricsF(font), QFontMetricsF(small)
        live = self.live(pos)

        slots: dict[int, int] = {}
        for i in [cur] + [j for j in live if self.head_of(j) == j]:
            slots.setdefault(self.rank(i) % 2, i)
        if nxt is not None and len(slots) < 2:
            slots.setdefault(self.rank(nxt) % 2, nxt)

        band = fm.height() * 2.6
        low = H * 0.5
        divide = fm.height() * 0.35
        under = low + divide
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
            alpha = (0.18 + 0.14 * self.run_up(ln, pos)) if coming else 0.34
            p.setFont(font)
            self.draw_block(p, ln, rows, fm, x0, width, top, pos, act, alpha)
            self.mark(i, top, own, x0, width)
            self.draw_adlibs(p, i, live, small, fm_sm, x0, width, top + own,
                             pos, 0.6 if coming else 1.0)
            under = max(under, top + h)
        if self.credits_due(pos):
            self.credits_block(p, x0, width, under + fm_sm.height() * 0.7, H)

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

    The credit follows the last word on screen -- the ad-lib under it where
    there is one, the word itself where there is not -- a beat after the last
    word of the song has been sung.
    """

    name = "word"
    CREDIT_AFTER = 0.6

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
        if self.static_page(p, x0, width, H):
            return
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
            p.setFont(self.font(v.lyric_px() * 1.1))
            rows = self.rows_of(ln, fm_line, width)
            h = len(rows) * fm_line.height() * 1.06
            self.draw_block(p, ln, rows, fm_line, x0, width, H * 0.46 - h / 2,
                            pos, 1.0, 0.34)
            self.mark(cur, H * 0.46 - h / 2, h, x0, width)
            if self.credits_due(pos):
                self.credits_block(p, x0, width, H * 0.46 + h / 2
                                   + fm_line.height() * 0.35, H)
            return

        subs = []
        for j in self.adlibs_of(cur):
            if j not in live:
                continue
            said = self.timed_words(v.lines[j], fm_line, width)
            got = self.pick(said, pos) or (said[0] if said else None)
            if got:
                subs.append((j, got))
        big, of = self.pick(timed, pos), cur
        if big is None and subs:
            of, big = subs.pop(0)
        if big is None:
            big, of = timed[0], cur

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
        if self.credits_due(pos):
            self.credits_block(p, x0, width, y + sub_h * 0.35, H)


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

    The credit takes no card. It is not a line of the song, and it rides at
    the foot of the column exactly as it does at the foot of the stack -- this
    is the one of these four that lays the document out, so it is the one that
    has a foot to put it at.
    """

    name = "cards"
    scrolls = True
    INSET = 0.10

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
        still = not v.synced
        for i, ln in enumerate(v.lines):
            if ln.get("credits"):
                if -fm.height() * 8 < y < H + gap:
                    self.credits_block(p, x0, width, y)
                y += v.layout_line(i, width)[2] + gap
                continue
            if not self.singable(i):
                continue
            bg = bool(ln.get("background"))
            f = fm_sm if bg else fm
            inset = width * self.INSET if bg else 0.0
            cx, cw = x0 + inset, width - inset * 2
            rows = self.rows(i, f, cw - pad * 2)
            h = len(rows) * f.height() * 1.06 + pad * 2
            room = v.gap_open(i, pos) if ln.get("dots") else 1.0
            h *= room
            act = self.act_of(i, live)
            if room > 0.0 and -h - gap < y < H + gap:
                p.setFont(small if bg else font)
                dist = v.vfade(y + h / 2)
                lit = 1.0 if still else act
                fade = (0.38 + 0.62 * lit) * dist
                if ln.get("dots"):
                    self._paint_dots(p, ln, f, cx + pad, y + pad, pos, act,
                                     fade * 0.9 * room, cw - pad * 2, "center")
                else:
                    p.save()
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255,
                                      int((14 + 16 * lit) * dist)))
                    p.drawRoundedRect(QRectF(cx, y, cw, h), pad * 0.7, pad * 0.7)
                    p.restore()
                    self.draw_block(p, ln, rows, f, cx + pad, cw - pad * 2,
                                    y + pad, pos, act,
                                    (0.82 if still else 0.34) * fade)
            self.mark(i, y, h, cx, cw)
            y += h + gap * room
        v.content_h = y + v.scroll - top


class _Spr:
    """Spicy Lyrics' spring: a port of Fraktality's spr, as Spicy ships it.

    Not the Spring above. That one is AMLL's, and is solved for a position
    at t from a moment it was let go; this one is stepped, frame by frame,
    from where it is and how fast it is going -- which is what the words of a
    Spicy line are driven by, and what gives them their particular settle.
    `f` is in hertz and `d` is the damping ratio, as spr takes them.
    """

    __slots__ = ("p", "v", "g", "f", "d")

    def __init__(self, p: float, f: float, d: float) -> None:
        self.p = self.g = float(p)
        self.v = 0.0
        self.f, self.d = f, d

    def goal(self, g: float, snap: bool = False) -> None:
        self.g = g
        if snap:
            self.p, self.v = g, 0.0

    def settle(self) -> None:
        """No overshoot from here on: where it is and how fast it is going
        carry over, only the damping becomes critical."""
        if self.d < 1.0:
            self.d = 1.0

    def step(self, dt: float) -> float:
        d, f, g = self.d, self.f * 2.0 * math.pi, self.g
        p, v = self.p, self.v
        o = p - g
        if d == 1.0:
            q = math.exp(-f * dt)
            w = dt * q
            p = o * (q + w * f) + v * w + g
            v = v * (q - w * f) - o * (w * f * f)
        elif d < 1.0:
            q = math.exp(-d * f * dt)
            c = math.sqrt(1.0 - d * d)
            i, j = math.cos(dt * f * c), math.sin(dt * f * c)
            if c > 1e-5:
                z = j / c
            else:
                a = dt * f
                z = a + ((a * a) * (c * c) * (c * c) / 20 - c * c) * (a ** 3) / 6
            if f * c > 1e-5:
                y = j / (f * c)
            else:
                b = f * c
                y = dt + ((dt * dt) * (b * b) * (b * b) / 20 - b * b) * (dt ** 3) / 6
            p = (o * (i + z * d) + v * y) * q + g
            v = (v * (i - z * d) - o * (z * f)) * q
        else:
            c = math.sqrt(d * d - 1.0)
            r1, r2 = -f * (d + c), -f * (d - c)
            co2 = (v - o * r1) / (2 * f * c)
            co1 = math.exp(r1 * dt) * (o - co2)
            e2 = math.exp(r2 * dt)
            p = co1 + co2 * e2 + g
            v = co1 * r1 + co2 * e2 * r2
        self.p, self.v = p, v
        return p

    def asleep(self) -> bool:
        return self.v * self.v <= 1e-4 and (self.p - self.g) ** 2 <= (1 / 3840) ** 2


class _Curve:
    """The `cubic-spline` package Spicy draws its keyframes through.

    A natural cubic spline, solved once for the knots and read at x. Spicy
    hands it three or four (time, value) points per effect and asks it where
    the effect should be at a word's progress -- so the curve between the
    knots, overshoot and all, is part of the look and is reproduced exactly
    rather than eased some other way.
    """

    def __init__(self, pts) -> None:
        xs = [float(t) for t, _v in pts]
        ys = [float(v) for _t, v in pts]
        n = len(xs) - 1
        a = [[0.0] * (n + 2) for _ in range(n + 1)]
        for i in range(1, n):
            l, r = xs[i] - xs[i - 1], xs[i + 1] - xs[i]
            a[i][i - 1] = 1 / l
            a[i][i] = 2 * (1 / l + 1 / r)
            a[i][i + 1] = 1 / r
            a[i][n + 1] = 3 * ((ys[i] - ys[i - 1]) / l ** 2
                               + (ys[i + 1] - ys[i]) / r ** 2)
        l0, ln_ = xs[1] - xs[0], xs[n] - xs[n - 1]
        a[0][0], a[0][1] = 2 / l0, 1 / l0
        a[0][n + 1] = 3 * (ys[1] - ys[0]) / l0 ** 2
        a[n][n - 1], a[n][n] = 1 / ln_, 2 / ln_
        a[n][n + 1] = 3 * (ys[n] - ys[n - 1]) / ln_ ** 2
        m = n + 1
        for c in range(m):
            piv = max(range(c, m), key=lambda r: abs(a[r][c]))
            a[c], a[piv] = a[piv], a[c]
            for r in range(c + 1, m):
                k = a[r][c] / a[c][c]
                for j in range(c, m + 1):
                    a[r][j] -= k * a[c][j]
        ks = [0.0] * m
        for r in range(m - 1, -1, -1):
            ks[r] = (a[r][m] - sum(a[r][j] * ks[j] for j in range(r + 1, m))) / a[r][r]
        self.xs, self.ys, self.ks = xs, ys, ks

    def at(self, x: float) -> float:
        xs, ys, ks = self.xs, self.ys, self.ks
        i = 1
        while i < len(xs) - 1 and xs[i] < x:
            i += 1
        span = xs[i] - xs[i - 1]
        t = (x - xs[i - 1]) / span
        a = ks[i - 1] * span - (ys[i] - ys[i - 1])
        b = -ks[i] * span + (ys[i] - ys[i - 1])
        return ((1 - t) * ys[i - 1] + t * ys[i]
                + t * (1 - t) * (a * (1 - t) + b * t))


def _css_linear(stops):
    """CSS's linear() easing, from its (output, input) stops."""
    def f(x: float) -> float:
        if x <= 0.0:
            return stops[0][0]
        for (v0, t0), (v1, t1) in zip(stops, stops[1:]):
            if x <= t1:
                return v0 + (v1 - v0) * (x - t0) / max(1e-9, t1 - t0)
        return stops[-1][0]
    return f


class _Tween:
    """A CSS transition: from wherever it is now to the new value, on a curve.

    Re-aimed mid-flight it sets off from the value it had reached, which is
    what a browser does to a transition interrupted by a class change.
    """

    __slots__ = ("a", "b", "t0", "dur", "ease")

    def __init__(self, value: float) -> None:
        self.a = self.b = float(value)
        self.t0, self.dur, self.ease = 0.0, 0.0, None

    def value(self, now: float) -> float:
        if self.dur <= 0 or now >= self.t0 + self.dur:
            return self.b
        k = self.ease(max(0.0, (now - self.t0) / self.dur))
        return self.a + (self.b - self.a) * k

    def to(self, b: float, dur: float, ease, now: float) -> None:
        if abs(b - self.b) < 1e-6:
            return
        self.a, self.b = self.value(now), float(b)
        self.t0, self.dur, self.ease = now, dur, ease

    def moving(self, now: float) -> bool:
        return self.dur > 0 and now < self.t0 + self.dur


def _rtl(txt: str) -> bool:
    return any(unicodedata.bidirectional(c) in ("R", "AL") for c in txt)


class _Frag:
    """One timed fragment of a Spicy line: a word, a letter group, or a dot."""

    __slots__ = ("row", "x", "w", "core", "s", "e", "origin", "letters",
                 "sc", "y", "g", "op")

    def __init__(self, row, x, w, core, s, e, origin, letters) -> None:
        self.row, self.x, self.w, self.core = row, x, w, core
        self.s, self.e, self.origin, self.letters = s, e, origin, letters
        self.sc = self.y = self.g = self.op = None


def _gauss(img: QImage, radius: float) -> QImage:
    """A Gaussian blur, as a CSS text-shadow draws one.

    Qt's own blur effect, which is a true Gaussian: measured on a hard edge,
    its 10-90% ramp is 1.25-1.3 times the radius it is given, and a CSS
    shadow of blur b -- a Gaussian of sigma b/2 -- has a ramp of 1.28 b. So a
    CSS radius goes in as it is. soft_scale, which the stack blurs with, was
    tried first and cannot be fitted: its ramp moves in steps of whole
    halvings and even goes backwards between them (5px at 3x, 4px at 3.5x).
    """
    from PyQt6.QtWidgets import (QGraphicsBlurEffect, QGraphicsPixmapItem,
                                 QGraphicsScene)
    if radius <= 0.05:
        return img
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(img))
    fx = QGraphicsBlurEffect()
    fx.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    fx.setBlurRadius(radius)
    item.setGraphicsEffect(fx)
    scene.addItem(item)
    out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(0)
    p = QPainter(out)
    scene.render(p, QRectF(out.rect()), QRectF(0, 0, img.width(), img.height()))
    p.end()
    return out


class Spicy(Renderer):
    """Spicy Lyrics' renderer, as the Spicetify extension draws it.

    A port of src/utils/Lyrics/Animator/Lyrics/LyricsAnimator.ts, the
    Applyer that builds its DOM, the CSS in src/css/Lyrics/Mixed.css that
    turns the animator's variables into pixels, and ScrollToActiveLine. The
    default look -- Spicy's "simple lyrics mode" is off by default there and
    is not ported.

    What it does, all of it Spicy's own numbers:

      * Every syllable is its own element with three springs -- scale, a lift
        measured in font sizes, and a glow -- aimed each frame at a natural
        cubic spline read at the syllable's progress. Idle at 95% and a
        hundredth of an em low, it swells to 105% as it is sung and settles.
      * A syllable held a second or more is split into letters, each letter
        timed over the syllable less its last quarter second, and each with
        springs of its own pulled towards the letter being sung by distance.
      * The fill is a gradient per syllable, 85% white to 50% across a fifth
        of its width, carried from -20% to 100% as it is sung.
      * A line not being sung is drawn the way the CSS draws it: the glyphs
        themselves are transparent and what shows is their text-shadow, white
        at half strength for a line to come and 85% for one gone by, under a
        line opacity of about a half and a blur of 1.25px per line of
        distance from the one being sung.
      * A gap long enough for dots opens a line of three that swell and
        light in turn, and the group springs shut half a second before the
        words come back.
      * Hovering a line lights it, clears its blur, and puts Spicy's rounded
        highlight behind it.

    The column moves the way Spicy moves it -- its smooth scroll, and the
    wheel taking the blur off until
    three quarters of a second after the last notch -- but WHEN it moves
    and to which line, and to what height, is the stack's: the window's own
    focus line, with Scroll ahead and Off by one, at its Line height (Spicy
    puts it thirty pixels above the middle). Spicy's rule for that holds the earlier of
    two sounding lines while a long one lasts, which sent the column back
    up a line mid-song.

    Every knob in the window's menu reaches it; see `knob`.
    """

    name = "Spicy Lyrics"
    scrolls = False

    def rest_top(self, i: int) -> float | None:
        offs = getattr(self, "_offs", None)
        if not offs or not 0 <= i < len(offs) or self.sy is None:
            return None
        end = (self.scroll_tw[1] if self.scroll_tw is not None
               else self.wheel_to if self.wheel_to is not None else self.sy)
        return end + offs[i]
    stacked = False

    SCALE = _Curve([(0, 0.95), (0.7, 1.0505), (1, 1)])
    YOFF = _Curve([(0, 1 / 100), (0.9, -(1 / 60)), (1, 0)])
    GLOW = _Curve([(0, 0), (0.15, 1), (0.6, 1), (1, 0)])
    L_SCALE = _Curve([(0, 0.95), (0.7, 1.175), (1, 1)])
    L_YOFF = _Curve([(0, 1 / 100), (0.9, -(1 / 56)), (1, 0)])
    D_SCALE = _Curve([(0, 0.75), (0.7, 1.05), (1, 1)])
    D_YOFF = _Curve([(0, 0), (0.9, -0.12), (1, 0)])
    D_GLOW = _Curve([(0, 0), (0.6, 1), (1, 1)])
    D_OP = _Curve([(0, 0.35), (0.6, 1), (1, 1)])
    Y_SPR = (1.45, 0.4)
    SC_SPR = (0.88, 0.64)
    G_SPR = (1.18, 0.56)
    DOT_Y_SPR = (1.25, 0.4)
    DOT_SC_SPR = (0.7, 0.6)
    DOT_G_SPR = (1.0, 0.5)
    DOT_OP_SPR = (1.0, 0.5)
    SUNG_LETTER_GLOW = 0.2
    LETTER_GLOW_OP = 1.85

    LETTER_MIN = 1.0
    LETTER_TRIM = 0.25
    PRE_HIDDEN = 0.5
    DOT_PAD = -0.55

    BLUR_STEP = 1.25
    BLUR_MAX = BLUR_STEP * 5 + BLUR_STEP * 0.465
    NOT_SUNG_OP = 0.51
    SUNG_OP = 0.497
    ALPHA = (0.85, 0.5)
    BG_ALPHA = (0.6, 0.3)
    LINE_EASE = staticmethod(_bezier(0.61, 1.0, 0.88, 1.0))
    CSS_EASE = staticmethod(_bezier(0.25, 0.1, 0.25, 1.0))
    DOT_HIDE = staticmethod(_css_linear([
        (0, 0), (-0.006, .094), (-0.029, .18), (-0.157, .433),
        (-0.185, .514), (-0.189, .559), (-0.182, .60), (-0.163, .639),
        (-0.133, .676), (-0.074, .723), (0.006, .767), (0.238, .85),
        (0.566, .927), (1, 1)]))
    HOVER_GROW = staticmethod(_css_linear([
        (0, 0), (0.013, .01), (0.051, .022), (0.404, .098), (0.51, .126),
        (0.602, .155), (0.683, .187), (0.754, .222), (0.813, .26),
        (0.861, .302), (0.9, .348), (0.931, .40), (0.972, .527),
        (0.992, .702), (1, 1)]))

    LINE_GAP = 0.3

    BUILDS = 2

    COOLDOWN = 0.75
    DRASTIC = 1.0
    OVERSCAN = 5
    SCROLL_EASE = staticmethod(_bezier(0.42, 0.0, 0.58, 1.0))

    def __init__(self, view) -> None:
        super().__init__(view)
        self.now = mono
        self._key = None
        self._builds = self.BUILDS
        self._reset()

    def _reset(self) -> None:
        self.sy = None
        self.scroll_tw = None
        self.wheel_to = None
        self.last_line = None
        self.last_pos = None
        self.last_user = -1e9
        self.hide_blur = False
        self.anim: dict = {}
        self.op: dict = {}
        self.dotline: dict = {}
        self.hover: dict = {}
        self._t = None
        self._pix: dict = {}
        self._frags: dict = {}
        self._lays: dict = {}
        self._halos: dict = {}

    # ------------------------------------------------------------ the model
    def _rebase(self) -> None:
        """A new song starts from nothing; a better source for the same one
        keeps what has already been sung. Keyed as Amll._rebase keys it."""
        v = self.v
        tid = getattr(getattr(v, "clock", None), "tid", None)
        key = ("tid", tid) if tid else (
            "ink", len(v.lines),
            hash(tuple((ln.get("text") or "") for ln in v.lines)))
        if key != self._key:
            self._key = key
            self._reset()

    def frags_of(self, i: int, lay):
        """Line `i`'s rows as Spicy's elements, cached against the layout."""
        rows, fm, font = lay[0], lay[1], lay[5]
        hit = self._frags.get(i)
        if hit is not None and hit[0] is rows:
            return hit[1]
        out = []
        rtl = any(_rtl(f[2]) for row in rows for f in row)
        for r_i, row in enumerate(rows):
            for run in self.words_of(row):
                inked = [(k, f) for k, f in run if f[2].strip()]
                for n, (_k, (x, _w, txt, s, e)) in enumerate(inked):
                    core = txt.strip()
                    x += fm.horizontalAdvance(txt[:len(txt) - len(txt.lstrip())])
                    w = fm.horizontalAdvance(core)
                    if len(inked) == 1:
                        origin = 0.5
                    elif n == 0:
                        origin = 0.0 if rtl else 1.0
                    elif n == len(inked) - 1:
                        origin = 1.0 if rtl else 0.0
                    else:
                        origin = 0.5
                    letters = None
                    if (s is not None and e is not None
                            and e - s >= self.LETTER_MIN and not _rtl(core)):
                        letters = self._letters(core, fm, font)
                    out.append(_Frag(r_i, x, w, core, s, e, origin, letters))
        self._frags[i] = (rows, out)
        return out

    def _letters(self, core: str, fm, font):
        offs = self.shaped_offsets(core, font, fm)
        out, ci = [], 0
        for g in Amll.graphemes(core):
            lx = offs[ci] if ci < len(offs) else fm.horizontalAdvance(core[:ci])
            nx = (offs[ci + len(g)] if ci + len(g) < len(offs)
                  else fm.horizontalAdvance(core))
            out.append([g, lx, max(0.0, nx - lx), None, None, None])
            ci += len(g)
        return out

    @staticmethod
    def state(pos: float, s, e) -> str:
        if s is None or pos < s:
            return "N"
        return "S" if e is None or pos >= e else "A"

    def _by_place(self, states, frags, pos: float) -> set:
        """Where a line sits, not its own clock, says how it is drawn: every
        line above the one being sung is finished and every line below it
        untouched, even one already sung. The lines being sung stay as they
        are. The current line is the last one started, so an ad-lib that ends
        under a lead still being sung stays sung rather than going back.

        A line above the current one whose every syllable is sung is
        finished then and there, though its own end is still to come; the
        lines it returns went that way this frame and are drawn so at once."""
        lines = self.v.lines
        cur = -1
        for i, ln in enumerate(lines):
            if states[i] is not None and ln.get("start") is not None \
                    and ln["start"] <= pos:
                cur = i
        snap = set()
        for i, st in enumerate(states):
            if st is None:
                continue
            if st == "A":
                ends = [fr.e for fr in frags[i] if fr.e is not None]
                if i < cur and ends and max(ends) <= pos:
                    states[i] = "S"
                    snap.add(i)
                continue
            begun = lines[i].get("start") is None or lines[i]["start"] <= pos
            states[i] = "S" if i <= cur and begun else "N"
        return snap

    @staticmethod
    def progress(pos: float, s, e) -> float:
        if s is None or e is None or pos <= s:
            return 0.0
        return 1.0 if pos >= e else (pos - s) / (e - s)

    @staticmethod
    def dot_times(ln):
        """Syllable.ts: three dots across the gap, the last out 0.55s early."""
        s, e = ln["start"], ln["end"]
        total = e - s
        base, pad = total / 3, Spicy.DOT_PAD / 3
        d1 = max(s, s + base + pad)
        d2 = max(d1, s + base * 2 + pad * 2)
        d3 = max(d2, s + total + Spicy.DOT_PAD)
        return ((s, d1), (d1, d2), (d2, d3))

    # -------------------------------------------------------- the animator
    def _word(self, fr: _Frag, st: str, pct: float, dt: float) -> None:
        if fr.sc is None:
            fr.sc = _Spr(self.SCALE.at(0), *self.SC_SPR)
            fr.y = _Spr(self.YOFF.at(0), *self.Y_SPR)
            fr.g = _Spr(self.GLOW.at(0), *self.G_SPR)
        at = pct if st == "A" else (0.0 if st == "N" else 1.0)
        fr.sc.goal(self.SCALE.at(at))
        fr.y.goal(self.YOFF.at(at))
        fr.g.goal(self.GLOW.at(at))
        if st == "S":
            for spr in (fr.sc, fr.y, fr.g):
                spr.settle()
        fr.sc.step(dt)
        fr.y.step(dt)
        fr.g.step(dt)

    def _letter_springs(self, lt) -> None:
        if lt[3] is None:
            lt[3] = _Spr(self.L_SCALE.at(0), *self.SC_SPR)
            lt[4] = _Spr(self.L_YOFF.at(0), *self.Y_SPR)
            lt[5] = _Spr(self.GLOW.at(0), *self.G_SPR)

    def _group(self, fr: _Frag, pos: float, dt: float) -> None:
        """A letter group: the group moves as a word, each letter on its own."""
        s, e = fr.s, fr.e - self.LETTER_TRIM
        st = self.state(pos, s, e)
        self._word(fr, st, self.progress(pos, s, e), dt)
        n = len(fr.letters)
        step = (e - s) / n
        if st == "A":
            act, act_p = -1, 0.0
            for k in range(n):
                ls, le = s + k * step, s + (k + 1) * step
                if self.state(pos, ls, le) == "A":
                    act, act_p = k, self.progress(pos, ls, le)
                    break
            r_sc, r_y, r_g = self.L_SCALE.at(0), self.L_YOFF.at(0), self.GLOW.at(0)
            if act >= 0:
                b_sc, b_y = self.L_SCALE.at(act_p), self.L_YOFF.at(act_p)
                b_g = self.GLOW.at(act_p)
        for k, lt in enumerate(fr.letters):
            self._letter_springs(lt)
            ls, le = s + k * step, s + (k + 1) * step
            if st == "A":
                t_sc, t_y, t_g = r_sc, r_y, r_g
                lst = self.state(pos, ls, le)
                if act >= 0:
                    d = abs(k - act)
                    fall = 1 / (1 + d ** 2.8)
                    gfall = 1 / (1 + d * 0.9)
                    t_sc = r_sc + (b_sc - r_sc) * fall
                    t_y = r_y + (b_y - r_y) * fall
                    t_g = r_g + (b_g - r_g) * gfall
                if lst == "N":
                    t_sc, t_y, t_g = r_sc, r_y, r_g
                elif lst == "S" and act == -1:
                    t_g = self.GLOW.at(self.SUNG_LETTER_GLOW)
            else:
                at = 0.0 if st == "N" else 1.0
                t_sc, t_y, t_g = (self.L_SCALE.at(at), self.L_YOFF.at(at),
                                  self.GLOW.at(at))
            lt[3].goal(t_sc)
            lt[4].goal(t_y)
            lt[5].goal(t_g)
            if st == "S":
                for spr in lt[3:6]:
                    spr.settle()
            lt[3].step(dt)
            lt[4].step(dt)
            lt[5].step(dt)

    def _dot(self, fr: _Frag, st: str, pct: float, dt: float) -> None:
        if fr.sc is None:
            fr.sc = _Spr(self.D_SCALE.at(0), *self.DOT_SC_SPR)
            fr.y = _Spr(self.D_YOFF.at(0), *self.DOT_Y_SPR)
            fr.g = _Spr(self.D_GLOW.at(0), *self.DOT_G_SPR)
            fr.op = _Spr(self.D_OP.at(0), *self.DOT_OP_SPR)
        at = pct if st == "A" else (0.0 if st == "N" else 1.0)
        for spr, curve in ((fr.sc, self.D_SCALE), (fr.y, self.D_YOFF),
                           (fr.g, self.D_GLOW), (fr.op, self.D_OP)):
            spr.goal(curve.at(at))
            if st == "S":
                spr.settle()
            spr.step(dt)

    def dots_of(self, i: int):
        hit = self._frags.get(i)
        if hit is None or hit[0] != "dots":
            ln = self.v.lines[i]
            hit = ("dots", [_Frag(0, 0.0, 0.0, "•", s, e, 0.5, None)
                            for s, e in self.dot_times(ln)])
            self._frags[i] = hit
        return hit[1]

    def animate(self, pos: float, dt: float, frags, states) -> None:
        """One Animate() call: the Syllable branch of LyricsAnimator.ts."""
        lines = self.v.lines
        order = [i for i in range(len(lines)) if not lines[i].get("credits")]
        for k, i in enumerate(order):
            st = states[i]
            if st == "A":
                for fr in frags[i]:
                    if fr.letters and not lines[i].get("dots"):
                        self._group(fr, pos, dt)
                        continue
                    fst = self.state(pos, fr.s, fr.e)
                    pct = self.progress(pos, fr.s, fr.e)
                    if lines[i].get("dots"):
                        self._dot(fr, fst, pct, dt)
                    else:
                        self._word(fr, fst, pct, dt)
            elif st == "S":
                nxt = order[k + 1] if k + 1 < len(order) else None
                if nxt is not None and states[nxt] == "S":
                    for fr in frags[i]:
                        if not self._resting(fr):
                            self._rest(fr, bool(lines[i].get("dots")))
                    continue
                for fr in frags[i]:
                    if fr.sc is None:
                        self._rest(fr, bool(lines[i].get("dots")))
                        continue
                    if lines[i].get("dots"):
                        self._dot(fr, "S", 1.0, dt)
                    elif fr.letters:
                        self._group(fr, max(pos, fr.e), dt)
                    else:
                        self._word(fr, "S", 1.0, dt)
            elif st == "N":
                for fr in frags[i]:
                    fr.sc = fr.y = fr.g = fr.op = None
                    for lt in fr.letters or ():
                        lt[3] = lt[4] = lt[5] = None

    def _resting(self, fr: _Frag) -> bool:
        """Already settled finished, as _rest leaves it."""
        return (fr.sc is not None and fr.sc.v == 0.0 and fr.y.v == 0.0
                and fr.g.v == 0.0 and fr.sc.p == fr.sc.g and fr.y.p == fr.y.g
                and fr.g.p == fr.g.g and fr.sc.g == (self.D_SCALE.at(1)
                if fr.op is not None else self.SCALE.at(1)))

    def _rest(self, fr: _Frag, dots: bool) -> None:
        """Springs already settled at the end of the syllable."""
        if dots:
            fr.sc = _Spr(self.D_SCALE.at(1), *self.DOT_SC_SPR)
            fr.y = _Spr(self.D_YOFF.at(1), *self.DOT_Y_SPR)
            fr.g = _Spr(self.D_GLOW.at(1), *self.DOT_G_SPR)
            fr.op = _Spr(self.D_OP.at(1), *self.DOT_OP_SPR)
            fr.op.settle()
        else:
            fr.sc = _Spr(self.SCALE.at(1), *self.SC_SPR)
            fr.y = _Spr(self.YOFF.at(1), *self.Y_SPR)
            fr.g = _Spr(self.GLOW.at(1), *self.G_SPR)
            for lt in fr.letters or ():
                lt[3] = _Spr(self.L_SCALE.at(1), *self.SC_SPR)
                lt[4] = _Spr(self.L_YOFF.at(1), *self.Y_SPR)
                lt[5] = _Spr(self.GLOW.at(1), *self.G_SPR)
                for spr in lt[3:6]:
                    spr.settle()
        for spr in (fr.sc, fr.y, fr.g):
            spr.settle()

    # ------------------------------------------------------------- scrolling
    def aim_line(self, pos: float):
        """The line to scroll to: the stack's, not Spicy's. See the class
        docstring. LyricsView.tick asks the same question the same way."""
        import spicy_lyrics as SL
        v = self.v
        if not v.lines:
            return None
        i = SL.focus_index(v.lines, pos, self.knob("scroll_lead", 0.0))
        if i is None or i < 0:
            return None
        aim = getattr(v, "troll_aim", None)
        if aim is not None and self.knob("off_by_one", 0.0) > 0:
            i = aim(i)
        return max(0, min(len(v.lines) - 1, i))

    def _aim(self, i: int, offs, hs, H: int, now: float, instant: bool) -> None:
        want = H * self.knob("focus_height", 0.40) - hs[i] / 2 - offs[i]
        self.wheel_to = None
        if instant or self.sy is None:
            self.sy, self.scroll_tw = want, None
            return
        cur = self.sy
        dur = min(math.sqrt(abs(want - cur)), 12.0) / 60.0
        self.scroll_tw = (cur, want, now, dur)

    def _scroll(self, pos: float, playing: bool, offs, hs, H: int, now: float):
        """ScrollToActiveLine's mechanics, on the stack's choice of line."""
        cur = self.aim_line(pos)
        last, self.last_pos = self.last_pos, pos
        if cur is None:
            return None
        drastic = last is not None and abs(pos - last) > self.DRASTIC
        moved = last is not None and not playing and pos != last
        if self.last_line is None or drastic or moved:
            instant = self.last_line is None or drastic
            self.last_line = cur
            self.hide_blur, self.last_user = False, -1e9
            self._aim(cur, offs, hs, H, now, instant)
            return cur
        if now - self.last_user > self.COOLDOWN and self._near_view(cur, offs, hs, H):
            self.hide_blur = False
            if cur != self.last_line:
                self.last_line = cur
                self._aim(cur, offs, hs, H, now, False)
        return cur

    def _near_view(self, i: int, offs, hs, H: int) -> bool:
        """Visible, or inside the virtualizer's overscan of five lines."""
        sy = self.sy or 0.0
        shown = [j for j in range(len(offs))
                 if sy + offs[j] + hs[j] > 0 and sy + offs[j] < H]
        if not shown:
            return False
        return min(shown) - self.OVERSCAN <= i <= max(shown) + self.OVERSCAN

    def wheel(self, dy: float) -> bool:
        if not self.v.synced or self.sy is None:
            return False
        self.scroll_tw = None
        lo, hi = getattr(self, "_bounds", (-1e9, 1e9))
        to = self.sy if self.wheel_to is None else self.wheel_to
        self.wheel_to = max(lo, min(hi, to + dy * 0.8))
        self.last_user = self.now()
        self.hide_blur = True
        return True

    def animating(self) -> bool:
        now = self.now()
        if self.scroll_tw is not None or self.wheel_to is not None:
            return True
        if any(t.moving(now) for t in self.op.values()):
            return True
        if any(a.moving(now) or b.moving(now)
               for a, b in list(self.dotline.values()) + list(self.hover.values())):
            return True
        for _rows, frs in self._frags.values():
            for fr in frs:
                if fr.sc is not None and not (fr.sc.asleep() and fr.y.asleep()
                                              and fr.g.asleep()):
                    return True
        return self.hide_blur and now - self.last_user <= self.COOLDOWN + 0.1

    # ------------------------------------------------------------- the type
    def em(self, width: float) -> float:
        """--DefaultLyricsSize: clamp(1.85rem, 7cqw, 3.5rem), times Text size."""
        k = self.knob("font_scale", 1.0)
        if not self.v.synced:
            return max(12.8, min(40.0, width * 0.05)) * k
        return max(29.6, min(56.0, width * 0.07)) * k

    def font(self, px: float, bg: bool = False) -> QFont:
        """The window's own lyric font -- the Font setting, its weight and
        all -- at Spicy's size. Spicy ships a face of its own and draws its
        lines at 700; neither is a reason to overrule what was picked here.
        """
        get = getattr(self.v, "lyric_font", None)
        f = QFont(get(bg)) if get is not None else QFont(self.v.family)
        f.setPixelSize(max(1, int(round(px))))
        try:
            for tag in ("liga", "clig"):
                f.setFeature(QFont.Tag(tag), 0)
        except (AttributeError, TypeError):
            pass
        return f

    def face(self) -> str:
        key = getattr(self.v, "lyric_font_key", None)
        return key() if key is not None else self.v.family

    def lay(self, i: int, width: float):
        """A line set at Spicy's size: background vocals at three quarters,
        rows 1.18 ems apart, and 5cqw kept clear on the far side as the
        line's padding does. The face is the window's; see font().

        (rows, fm, h, rrows, rfm, font, rfont, pitch, ox-shift,
         ruby, rufont, rufm, row-tops)

        Readings above sit in a band of their own over the rows that have
        any, set at the same share of the line's size as in the window. A
        row with none gets no band: a line that wraps into a Latin tail kept
        its tail a whole band away from the rest of it. row-tops is where
        each row starts, and one more entry for where the last one ends.
        """
        v = self.v
        ln = v.lines[i]
        fam = self.face()
        own = (ln.get("pieces"), ln.get("pieces_roman"))
        key = (i, int(width), fam, v.align, v.roman, v.furigana, v.synced,
               id(ln), id(own[0]), id(own[1]), getattr(v, "_ink_gen", 0),
               self.knob("font_scale", 1.0))
        hit = self._lays.get(key)
        if hit is not None:
            return hit[0]
        em = self.em(width)
        if ln.get("credits"):
            rows, fm, h = v.layout_line(i, width)[:3]
            out = (rows, fm, h, [], None, None, None, 0.0, 0.0,
                   [], None, None, None)
        else:
            bg = bool(ln.get("background"))
            px = em * (0.75 if bg else 1.0)
            font = self.font(px, bg)
            fm = QFontMetricsF(font)
            pitch = px * 1.1818
            align = v.line_align(ln)
            avail = width * 0.95
            shift = {"left": 0.0, "center": width * 0.025}.get(align, width * 0.05)
            if ln.get("dots"):
                out = ([], fm, 0.0, [], None, font, None, pitch, shift,
                       [], None, None, None)
            else:
                rows = v.wrap_pieces(v.line_pieces(ln), fm, avail, align)
                ruby, _ = v.ruby_rows(ln, rows, fm)
                rufont = rufm = None
                ruh = 0.0
                bands = [0.0] * len(rows)
                if ruby:
                    rufont = self.font(px * 0.34, bg)
                    rufm = QFontMetricsF(rufont)
                    ruh = rufm.height() * 0.92
                    bands = [ruh if r_i < len(ruby) and ruby[r_i] else 0.0
                             for r_i in range(len(rows))]
                tops, y_ = [], 0.0
                for b in bands:
                    tops.append(y_)
                    y_ += pitch + b
                tops.append(y_)
                h = y_
                rrows, rfm, rfont = [], None, None
                if v.roman == "under" and ln.get("pieces_roman"):
                    rfont = self.font(px * 0.6, bg)
                    rfm = QFontMetricsF(rfont)
                    rrows = v.wrap_pieces(ln["pieces_roman"], rfm, avail,
                                          v.roman_align(ln, align))
                    h += pitch * 0.1 + len(rrows) * rfm.height() * 1.04
                out = (rows, fm, h, rrows, rfm, font, rfont, pitch, shift,
                       ruby, rufont, rufm, tops)
        if len(self._lays) > 4000:
            self._lays.clear()
        self._lays[key] = (out, own)
        return out

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        if not v.synced:
            self._static(p, x0, width, H)
            return
        self._rebase()
        self._builds = self.BUILDS
        now = self.now()
        dt = 0.0 if self._t is None else max(0.0, min(1.0, now - self._t))
        self._t = now
        pos = v.position() - v.track_offset()
        playing = getattr(getattr(v, "clock", None), "status", "") == "Playing"
        lines = v.lines
        n = len(lines)
        v.content_h = 0.0
        if not n:
            v.line_rects = []
            return
        self._em = self.em(width)
        self._cq = width / 100.0
        lays = [self.lay(i, width) for i in range(n)]
        states = [None if ln.get("credits")
                  else self.state(pos, ln.get("start"), ln.get("end"))
                  for ln in lines]
        frags = [self.dots_of(i) if ln.get("dots")
                 else ([] if ln.get("credits")
                       else self.frags_of(i, lays[i]))
                 for i, ln in enumerate(lines)]
        snap = self._by_place(states, frags, pos)
        self.animate(pos, dt, frags, states)
        for i in snap:
            dots = bool(lines[i].get("dots"))
            for fr in frags[i]:
                self._rest(fr, dots)

        cq, px = self._cq, self._em
        ls = self.knob("line_spacing", 1.0)
        hs, gaps, shows = [], [], {}
        for i, ln in enumerate(lines):
            if ln.get("dots"):
                a_, gs = self._dot_state(i, ln, states[i], pos, now)
                shows[i] = (a_, gs)
                room = v.gap_open(i, pos)
                hs.append(px * 1.1818 * room)
                gaps.append(px * self.LINE_GAP * ls * room)
                continue
            hs.append(lays[i][2])
            nxt_bg = i + 1 < n and lines[i + 1].get("background")
            gaps.append(cq * 0.2 if nxt_bg else px * self.LINE_GAP * ls)
        offs, off = [], 0.0
        for h, g in zip(hs, gaps):
            offs.append(off)
            off += h + g
        self._bounds = (H / 2 - off, H / 2)
        geom = (int(width), int(H))
        if geom != getattr(self, "_geom", geom) and self.last_line is not None \
                and self.last_line < n:
            self.hide_blur, self.last_user = False, -1e9
            self._aim(self.last_line, offs, hs, H, now, True)
        self._geom = geom
        focal = self._scroll(pos, playing, offs, hs, H, now)
        if self.scroll_tw is not None:
            a0, b0, t0, dur = self.scroll_tw
            k = 1.0 if dur <= 0 else min(1.0, (now - t0) / dur)
            self.sy = a0 + (b0 - a0) * self.SCROLL_EASE(k)
            if k >= 1.0:
                self.scroll_tw = None
        if self.wheel_to is not None and self.sy is not None:
            self.sy += (self.wheel_to - self.sy) * (1.0 - math.exp(-dt * 24.0))
            if abs(self.wheel_to - self.sy) < 0.3:
                self.sy, self.wheel_to = self.wheel_to, None
        if self.sy is None:
            self.sy = H * 0.4
        v.focus_idx = focal if focal is not None else -1
        v.content_h = 0.0
        base = self.sy

        rank, r_ = [], -1
        for ln in lines:
            if not (ln.get("background") or ln.get("dots") or ln.get("credits")):
                r_ += 1
            rank.append(max(0, r_))
        act = [i for i in range(n) if states[i] == "A"]
        if act:
            self._blur_from = act[-1]
        here = focal if focal is not None else getattr(self, "_blur_from", None)
        mouse = getattr(v, "mouse_pos", None)
        rects = []
        self._offs = list(offs)
        for i, ln in enumerate(lines):
            top = base + offs[i]
            h = hs[i]
            rects.append((i, top + v.scroll, h, x0, x0 + width))
            if ln.get("dots"):
                a_, gs = shows[i]
                self._dot_line(p, i, ln, frags[i], x0, width, top, a_, gs)
                continue
            if top > H + 40 or top + h < -40:
                if i in self.op and states[i] is not None:
                    st = states[i]
                    self.op[i] = _Tween(1.0 if st == "A" else (
                        self.NOT_SUNG_OP if st == "N" else self.SUNG_OP))
                continue
            if ln.get("credits"):
                rows, fm = lays[i][0], lays[i][1]
                self._paint_credits(p, rows, fm, x0, top, width,
                                    ln.get("credit_links") or ())
                continue
            hov = (mouse is not None and x0 <= mouse.x() <= x0 + width
                   and top <= mouse.y() <= top + h)
            self._hover_bg(p, i, hov, x0, width, top, h, now)
            st = states[i]
            tw = self.op.get(i)
            want = 1.0 if (st == "A" or hov) else (
                self.NOT_SUNG_OP if st == "N" else self.SUNG_OP)
            if tw is None:
                tw = self.op[i] = _Tween(want)
            tw.to(want, 0.0 if i in snap and not hov else 0.2,
                  self.LINE_EASE, now)
            opac = tw.value(now)
            dist = abs(rank[i] - rank[here]) if here is not None else 0
            band = self.knob("focus", 0)
            if band and st != "A" and not hov and not self.hide_blur:
                if dist > band + 1:
                    continue
                if dist == band + 1:
                    opac *= 0.35
            if st == "A":
                act_ = self.knob("activation", {}).get(i, 1.0)
                drop = (1.0 - act_) * 7.0 * self.knob("line_drop", 0.0)
                self._active_line(p, i, ln, lays[i], frags[i], x0, top + drop,
                                  pos, opac)
            else:
                k = self.knob("blur_scale", 1.0)
                blur = min(self.BLUR_STEP * dist, self.BLUR_MAX) * k
                if hov or self.hide_blur:
                    blur = 0.0
                self._shadow_line(p, i, ln, lays[i], frags[i], x0, width, top,
                                  st, blur, opac)
        v.line_rects = rects

    def _static(self, p, x0: float, width: float, H: int) -> None:
        """An unsynced document: every line solid white, scrolled by hand."""
        v = self.v
        top0 = v.anchor() - v.scroll
        self._em, self._cq = self.em(width), width / 100.0
        rects, off = [], 0.0
        for i, ln in enumerate(v.lines):
            lay = self.lay(i, width)
            rows, fm, h = lay[0], lay[1], lay[2]
            y = top0 + off
            rects.append((i, v.anchor() + off, h, x0, x0 + width))
            if -40 < y + h and y < H + 40:
                if ln.get("credits"):
                    self._paint_credits(p, rows, fm, x0, y, width,
                                        ln.get("credit_links") or ())
                elif not ln.get("dots"):
                    p.save()
                    p.setFont(lay[5])
                    p.setPen(QColor(255, 255, 255))
                    self._text_rows(p, ln, lay, x0 + lay[8], y)
                    p.restore()
            off += h + self._em * self.LINE_GAP * self.knob("line_spacing", 1.0)
        v.line_rects = rects
        v.content_h = off

    def _text_rows(self, p, ln, lay, ox: float, top: float) -> None:
        """Plain text for a line, and its romanisation under it."""
        for r, row in enumerate(lay[0]):
            y = self._baseline(lay, top, r)
            for x, _w, txt, _s, _e in row:
                p.drawText(QPointF(ox + x, y), txt)
        self._ruby_rows(p, lay, ox, top)
        self._roman_rows(p, ln, lay, ox, top)

    def _roman_rows(self, p, ln, lay, ox: float, top: float, pos=None,
                    fill=None) -> None:
        """The romanisation under a line. On the line being sung each piece
        is wiped across by its own clock, as the words above it are."""
        rows, fm, _h, rrows, rfm = lay[:5]
        if not rrows or rfm is None:
            return
        p.save()
        p.setFont(lay[6])
        y = (top + self._row_top(lay, len(rows)) + lay[7] * 0.1
             + rfm.ascent())
        for row in rrows:
            rtl = row_rtl(row)
            for x, w, txt, s, e in row:
                if fill is not None:
                    st = self.state(pos, s, e)
                    gp = (-20 + 120 * self.progress(pos, s, e) if st == "A"
                          else (-20.0 if st == "N" else 100.0))
                    p.setPen(fill(ox + x, w, gp, rtl))
                p.drawText(QPointF(ox + x, y), txt)
            y += rfm.height() * 1.04
        p.restore()

    @staticmethod
    def _baseline(lay, top: float, row: int) -> float:
        """line-height 1.1818: the glyph box centred in each row's pitch."""
        fm, pitch = lay[1], lay[7]
        below = Spicy._row_top(lay, row + 1) - pitch
        return top + below + (pitch - fm.height()) / 2 + fm.ascent()

    @staticmethod
    def _row_top(lay, row: int) -> float:
        """Where row `row` starts, its reading band included."""
        tops = lay[12]
        if tops is None:
            return row * lay[7]
        return tops[min(row, len(tops) - 1)]

    def _ruby_rows(self, p, lay, ox: float, top: float, frags=(), pos=None,
                   fill=None) -> None:
        """The readings over each row. On the line being sung each follows
        the word under it -- its lift, and the wipe across it, measured where
        the wipe is on that word so a reading lights as its characters do."""
        ruby, rufont, rufm = lay[9], lay[10], lay[11]
        if not ruby or rufont is None:
            return
        fm = lay[1]
        p.save()
        p.setFont(rufont)
        for r_i, marks in enumerate(ruby):
            if r_i >= len(lay[0]):
                break
            if not marks:
                continue
            by = self._baseline(lay, top, r_i) - fm.ascent() \
                - rufm.height() * 0.92 + rufm.ascent()
            for cx, read, s, e in marks:
                rw = rufm.horizontalAdvance(read)
                rx = ox + cx - rw / 2
                under = next((fr for fr in frags if fr.row == r_i
                              and fr.x <= cx <= fr.x + fr.w), None)
                lift = 0.0
                if under is not None:
                    lift = -self._look(under)[1] * self._em
                if fill is not None:
                    frac = self.progress(pos, s, e)
                    if under is not None:
                        edge = ox + under.x + under.w * self.progress(
                            pos, under.s, under.e)
                        frac = max(0.0, min(1.0, (edge - rx) / max(1e-6, rw)))
                    p.setPen(fill(rx, rw, -20 + 120 * frac))
                p.drawText(QPointF(rx, by - lift), read)
        p.restore()

    # ---------------------------------------------------------- the knobs
    def knob(self, name: str, default):
        return getattr(self.v, name, default)

    def _gate(self, fr) -> float:
        """Pop only past: a syllable shorter than the bar does not swell."""
        bar = self.knob("pop_min", 0.0)
        if bar <= 0 or fr.s is None or fr.e is None:
            return 1.0
        return max(0.0, min(1.0, (fr.e - fr.s - bar) / 0.2))

    def _pop(self, sc: float, fr) -> float:
        """Word pop scales how far a size strays from 100%, idle 95% too."""
        return 1.0 + (sc - 1.0) * self.knob("pop", 1.0) * self._gate(fr)

    def _look(self, fr):
        """(scale, lift in ems) as drawn: the springs, through the knobs."""
        sc, yo = self._now_of(fr)
        return self._pop(sc, fr), yo * self.knob("rise", 1.0)

    def _sung(self, ln) -> QColor:
        """The sung colour: Spicy's white, or the album or duet tint."""
        sung = getattr(self.v, "sung_color", None)
        if sung is None:
            return QColor(255, 255, 255)
        c = sung(ln)
        if TEXT is not None and c == TEXT:
            return QColor(255, 255, 255)
        return QColor(c)

    @staticmethod
    def _now_of(fr: _Frag, letter: bool = False):
        """(scale, lift in ems) an element was last left at."""
        if fr.sc is None:
            return 0.95, (0.02 if fr.letters or letter else 0.01)
        return fr.sc.p, fr.y.p

    def _put(self, p, at: QPointF, txt: str, fm, scale: float, lift: float,
             ox: float, cy: float, fill=None) -> None:
        """Text under a CSS `scale` about (ox, cy) after a translateY.

        With a `fill`, the word is drawn once in solid white as a mask and
        the fill -- a translucent gradient -- laid into it. Drawing the
        glyphs straight in a translucent pen lays the colour on twice
        wherever two glyphs overlap, which heavy faces do at every join
        ("fl", "ck", "It"): a light seam at each one. A browser shapes the
        whole run first and fills that, so Spicy never shows one.
        """
        if fill is None:
            self.lifted_word(p, at, txt, lift, fm, scale, ox, cy)
            return
        dpr = self.v.devicePixelRatioF() or 1.0
        m = max(3.0, fm.height() * 0.22)
        x0 = math.floor((at.x() - m) * dpr) / dpr
        y0 = math.floor((at.y() - fm.ascent() - m) * dpr) / dpr
        pw = int(math.ceil((fm.horizontalAdvance(txt) + m * 2) * dpr)) + 2
        ph = int(math.ceil((fm.height() + m * 2) * dpr)) + 2
        if pw <= 0 or ph <= 0:
            return
        pm = QPixmap(pw, ph)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pp.translate(-x0, -y0)
        pp.setFont(p.font())
        pp.setPen(QColor(255, 255, 255))
        pp.drawText(at, txt)
        pp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        pp.fillRect(QRectF(x0, y0, pw / dpr, ph / dpr), fill)
        pp.end()
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(ox, cy)
        p.scale(scale, scale)
        p.translate(-ox, -cy)
        blit(p, QPointF(x0, y0 - lift), pm)
        p.restore()

    def _halo(self, txt: str, font, step: int):
        """The glyphs as a text-shadow of radius step/2, cached."""
        key = (txt, font.key(), step)
        hit = self._halos.get(key)
        if hit is not None:
            return hit
        dpr = self.v.devicePixelRatioF() or 1.0
        fm = QFontMetricsF(font)
        pad = int(step * 0.5 * 2.2) + 2
        img = QImage(int((fm.horizontalAdvance(txt) + pad * 2) * dpr) + 1,
                     int((fm.height() + pad * 2) * dpr) + 1,
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QPointF(pad, pad + fm.ascent()), txt)
        p.end()
        pm = QPixmap.fromImage(_gauss(img, step * 0.5 * dpr))
        pm.setDevicePixelRatio(dpr)
        if len(self._halos) > 600:
            self._halos.pop(next(iter(self._halos)))
        self._halos[key] = (pm, pad)
        return pm, pad

    def _glow(self, p, txt: str, font, fm, at: QPointF, radius: float,
              alpha: float, scale: float, lift: float, ox: float,
              cy: float) -> None:
        """A text-shadow: 0 0 radius, white at alpha.

        The radius moves every frame with the glow spring, so it is drawn as
        the two nearest half-pixel steps laid over each other in proportion
        -- a halo that grows smoothly rather than one that jumps between
        cached sizes a few frames apart.
        """
        alpha *= self.knob("glow_scale", 1.0)
        if alpha <= 0.004:
            return
        pos = max(0.0, radius * 2.0)
        lo = int(pos)
        w = pos - lo
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(ox, cy)
        p.scale(scale, scale)
        p.translate(-ox, -cy)
        was = p.opacity()
        for step, share in ((lo, 1.0 - w), (lo + 1, w)):
            if share <= 0.01:
                continue
            pm, pad = self._halo(txt, font, step)
            left = alpha
            while left > 0.004:
                p.setOpacity(was * min(1.0, left) * share)
                blit(p, QPointF(at.x() - pad, at.y() - fm.ascent() - pad - lift), pm)
                left -= 1.0
        p.setOpacity(was)
        p.restore()

    def _fill(self, x: float, w: float, gp: float, a1: float, a2: float,
              rtl: bool, sung: QColor | None = None):
        """The syllable's own gradient, from `gp`% to `gp`+20% of its width.

        Fill softness scales the 20%: 0 is a hard edge.
        """
        soft = 20.0 * self.knob("edge", 1.0)
        if rtl:
            xa, xb = x + w - w * gp / 100, x + w - w * (gp + soft) / 100
        else:
            xa, xb = x + w * gp / 100, x + w * (gp + soft) / 100
        if abs(xb - xa) < 0.5:
            xb = xa + (0.5 if xb >= xa else -0.5)
        g = QLinearGradient(xa, 0.0, xb, 0.0)
        c = QColor(sung) if sung is not None else QColor(255, 255, 255)
        c.setAlpha(int(255 * a1))
        g.setColorAt(0.0, c)
        g.setColorAt(1.0, QColor(255, 255, 255, int(255 * a2)))
        return QPen(QBrush(g), 0)

    def _active_line(self, p, i, ln, lay, frags, x0, top, pos, opac) -> None:
        v = self.v
        rows, fm = lay[0], lay[1]
        ox = x0 + lay[8]
        font = lay[5]
        a1, a2 = self.BG_ALPHA if ln["background"] else self.ALPHA
        em = self._em
        rtl = any(_rtl(fr.core) for fr in frags)
        sung = self._sung(ln)
        every = self.knob("word_glow", 0.0)
        p.save()
        p.setOpacity(opac)
        p.setFont(font)
        for fr in frags:
            base = self._baseline(lay, top, fr.row)
            bx = ox + fr.x
            cy = base - fm.ascent() + fm.height() / 2
            scale, yoff = self._look(fr)
            lift = -yoff * em
            orx = bx + fr.w * fr.origin
            if every > 0 and fr.s is not None and pos >= fr.s:
                self._glow(p, fr.core, font, fm, QPointF(bx, base), 6.0,
                           0.25 * every, scale, lift, orx, cy)
            if fr.letters:
                self._active_letters(p, fr, font, fm, bx, base, scale, lift,
                                     orx, cy, pos, em, a1, a2, sung)
                continue
            st = self.state(pos, fr.s, fr.e)
            gp = (-20 + 120 * self.progress(pos, fr.s, fr.e) if st == "A"
                  else (-20.0 if st == "N" else 100.0))
            g = fr.g.p if fr.g is not None else 0.0
            at = QPointF(bx, base)
            self._glow(p, fr.core, font, fm, at, 4 + 2 * g, g * 0.35,
                       scale, lift, orx, cy)
            self._put(p, at, fr.core, fm, scale, lift, orx, cy,
                      self._fill(bx, fr.w, gp, a1, a2, rtl, sung).brush())
        fill = lambda x, w, gp, d=rtl: self._fill(x, w, gp, a1, a2, d, sung)
        self._ruby_rows(p, lay, ox, top, frags, pos, fill)
        self._roman_rows(p, ln, lay, ox, top, pos, fill)
        p.restore()

    def _active_letters(self, p, fr, font, fm, bx, base, gscale, glift, gox,
                        gcy, pos, em, a1, a2, sung=None) -> None:
        """A letter group: the group's transform, then each letter's own."""
        s, e = fr.s, fr.e - self.LETTER_TRIM
        n = len(fr.letters)
        step = (e - s) / n
        act = -1
        for k in range(n):
            if self.state(pos, s + k * step, s + (k + 1) * step) == "A":
                act = k
                break
        p.save()
        p.translate(gox, gcy - glift)
        p.scale(gscale, gscale)
        p.translate(-gox, -gcy)
        for k, (ch, lx, lw, sc, yo, gl) in enumerate(fr.letters):
            ls, le = s + k * step, s + (k + 1) * step
            lst = self.state(pos, ls, le)
            if lst == "N":
                gp = -20.0
            elif lst == "S":
                gp = 100.0
            else:
                gp = (-20 + 120 * math.sin(self.progress(pos, ls, le) * math.pi / 2)
                      if k == act else -20.0)
            lsc = self._pop(sc.p if sc is not None else self.L_SCALE.at(0), fr)
            lyo = ((yo.p * 2) if yo is not None else 0.02) * self.knob("rise", 1.0)
            lg = gl.p if gl is not None else 0.0
            x = bx + lx
            at = QPointF(x, base)
            cx = x + lw / 2
            lift = -lyo * em
            self._glow(p, ch, font, fm, at, 4 + 12 * lg,
                       lg * self.LETTER_GLOW_OP, lsc, lift, cx, gcy)
            self._put(p, at, ch, fm, lsc, lift, cx, gcy,
                      self._fill(x, lw, gp, a1, a2, False, sung).brush())
        p.restore()

    def _shadow_line(self, p, i, ln, lay, frags, x0, width, top, st, blur,
                     opac) -> None:
        """A line not being sung: only its text-shadow shows, blurred."""
        v = self.v
        a1, a2 = self.BG_ALPHA if ln["background"] else self.ALPHA
        alpha = a2 if st == "N" else a1
        pen = self._sung(ln) if st == "S" else QColor(255, 255, 255)
        pen.setAlpha(255)
        opac *= alpha
        lvl = round(blur * 4) / 4
        settled = all(fr.sc is None or (fr.sc.asleep() and fr.y.asleep())
                      for fr in frags)
        if lvl < 0.3:
            lvl = 0.0
        sig = None
        if settled:
            sig = (i, pen.rgb(), int(width), int(self._em), v.align,
                   v.roman, self.face(),
                   v.devicePixelRatioF(), id(lay[0]),
                   self.knob("pop", 1.0), self.knob("rise", 1.0),
                   self.knob("pop_min", 0.0),
                   tuple((round(self._now_of(fr)[0], 3),
                          round(self._now_of(fr)[1], 4)) for fr in frags))
            have = self._pix.get(sig) or {}
            hit = have.get(lvl)
            if hit is None and self._builds <= 0 and have:
                hit = have[min(have, key=lambda k: abs(k - lvl))]
            if hit is not None:
                pm, pad = hit
                p.save()
                p.setOpacity(opac)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                blit(p, QPointF(x0 - pad, top - pad), pm)
                p.restore()
                return
        self._builds -= 1
        pad = 10 + int(lvl * 3)
        dpr = v.devicePixelRatioF() or 1.0
        pm = QPixmap(int((width + pad * 2) * dpr), int((lay[2] + pad * 2) * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pp.translate(pad - x0, pad - top)
        self._shadow_ink(pp, ln, lay, frags, x0, top, pen)
        pp.end()
        pm = QPixmap.fromImage(_gauss(pm.toImage(), lvl * dpr))
        pm.setDevicePixelRatio(dpr)
        if sig is not None:
            if sig not in self._pix and len(self._pix) > 60:
                self._pix.pop(next(iter(self._pix)))
            self._pix.setdefault(sig, {})[lvl] = (pm, pad)
        p.save()
        p.setOpacity(opac)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        blit(p, QPointF(x0 - pad, top - pad), pm)
        p.restore()

    def _shadow_ink(self, p, ln, lay, frags, x0, top, pen) -> None:
        v = self.v
        rows, fm = lay[0], lay[1]
        ox = x0 + lay[8]
        em = self._em
        p.setFont(lay[5])
        p.setPen(pen)
        for fr in frags:
            base = self._baseline(lay, top, fr.row)
            bx = ox + fr.x
            cy = base - fm.ascent() + fm.height() / 2
            scale, yoff = self._look(fr)
            orx = bx + fr.w * fr.origin
            if not fr.letters:
                self._put(p, QPointF(bx, base), fr.core, fm, scale, -yoff * em,
                          orx, cy)
                continue
            p.save()
            p.translate(orx, cy + yoff * em)
            p.scale(scale, scale)
            p.translate(-orx, -cy)
            for ch, lx, lw, sc, yo, _gl in fr.letters:
                lsc = self._pop(sc.p if sc is not None else self.L_SCALE.at(0), fr)
                lyo = ((yo.p * 2) if yo is not None else 0.02) * self.knob("rise", 1.0)
                x = bx + lx
                self._put(p, QPointF(x, base), ch, fm, lsc, -lyo * em,
                          x + lw / 2, cy)
            p.restore()
        self._ruby_rows(p, lay, ox, top, frags)
        self._roman_rows(p, ln, lay, ox, top)

    def _hover_bg(self, p, i, hov, x0, width, top, h, now) -> None:
        """The line:hover::before highlight: a rounded wash that grows in."""
        tw = self.hover.get(i)
        if tw is None:
            if not hov:
                return
            tw = self.hover[i] = (_Tween(0.0), _Tween(0.9))
        op, sc = tw
        op.to(1.0 if hov else 0.0, 0.25, self.CSS_EASE, now)
        sc.to(1.05 if hov else 0.9, 0.4, self.HOVER_GROW, now)
        a = op.value(now)
        if a <= 0.004:
            if not hov and not op.moving(now):
                self.hover.pop(i, None)
            return
        cq = self._cq
        s = sc.value(now)
        box = QRectF(x0 - cq * 0.5, top + h / 2 - (h + cq * 1.7) / 2,
                     width + cq * 0.5, h + cq * 1.7)
        c = box.center()
        p.save()
        p.translate(c)
        p.scale(s, s)
        p.translate(-c)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(255 * 0.1 * a)))
        p.drawRoundedRect(box, 16, 16)
        p.restore()

    def _dot_state(self, i, ln, st, pos, now):
        """(line opacity, group scale) of a musical line this frame."""
        tw = self.dotline.get(i)
        if tw is None:
            tw = self.dotline[i] = (_Tween(0.0), _Tween(0.0))
        op, grp = tw
        on = st == "A"
        early = on and pos > ln["end"] - self.PRE_HIDDEN
        op.to(1.0 if on else 0.0, 0.14, self.CSS_EASE, now)
        if on and not early:
            grp.to(1.0, 0.1, self.CSS_EASE, now)
        else:
            grp.to(0.0, 0.35, self.DOT_HIDE, now)
        return op.value(now), grp.value(now)

    def _dot_line(self, p, i, ln, frags, x0, width, top, a, gs) -> None:
        """A musical line: shown only while active, springing shut early."""
        if a <= 0.004 or abs(gs) <= 0.004:
            return
        beat = getattr(self.v, "beat_energy", None)
        e = beat() if beat is not None else 0.0
        if e > 0.004:
            gs *= 1.0 + 0.34 * e
        v = self.v
        em = self._em
        font = self.font(em * 1.3)
        fm = QFontMetricsF(font)
        adv = fm.horizontalAdvance("•")
        gap = em * 0.08
        gw = adv * 3 + gap * 2
        align = v.line_align(ln)
        gx = (x0 if align == "left" else
              x0 + width - gw if align == "right" else x0 + (width - gw) / 2)
        cy = top + em * 1.1818 / 2
        base = cy - (fm.ascent() + fm.descent()) / 2 + fm.ascent()
        p.save()
        p.setOpacity(a)
        p.setFont(font)
        gc = QPointF(gx + gw / 2, cy)
        p.translate(gc)
        p.scale(gs, gs)
        p.translate(-gc)
        for k, fr in enumerate(frags):
            x = gx + k * (adv + gap)
            if fr.sc is None:
                sc, yo, g, o = self.D_SCALE.at(0), 0.0, 0.0, self.D_OP.at(0)
            else:
                sc, yo, g, o = fr.sc.p, fr.y.p, fr.g.p, fr.op.p
            at = QPointF(x, base)
            lift = -yo * em
            cx = x + adv / 2
            p.setOpacity(a * max(0.0, min(1.0, o)))
            self._glow(p, "•", font, fm, at, 4 + 6 * g, g * 0.9, sc,
                       lift, cx, cy)
            p.setPen(QColor(255, 255, 255, int(255 * 0.85)))
            self._put(p, at, "•", fm, sc, lift, cx, cy)
        p.restore()


RENDERERS = {r.name: r for r in (Flow, Snap, Amll, Spotlight, Karaoke, Word,
                                 Cards, Spicy)}
RENDER_MODES = list(RENDERERS)
