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
                         QPainter, QPen, QPixmap, QRadialGradient, QRegion)

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
RISE_LEAD = 0.06
RISE_TIME = 0.30


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

    def _paint_dots(self, p, ln, fm, ox, y, pos, act, alpha, width,
                    align: str | None = None) -> None:
        """Instrumental break, the way Apple Music shows it: three dots that
        fill across the gap so a 40-second solo is not just dead air.

        `align` is for the renderers that set their own: the stack follows the
        window's alignment setting, but one that centres every line it draws
        would otherwise leave the dots hanging off to the left of it.
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
            fill = max(0.0, min(1.0, t * 3 - k))
            if e > 0.004:
                breathe = 1.0 + 0.34 * e * act
            else:
                breathe = 1.0 + 0.10 * math.sin(now * 2.4 + k * 0.8) * act
            rad = r * (0.62 + 0.40 * fill + 0.25 * cue) * breathe
            a = alpha * (0.22 + 0.78 * fill) * (0.30 + 0.70 * act)
            p.setBrush(QColor(234, 234, 234, int(255 * max(0.0, min(1.0, a)))))
            p.drawEllipse(QPointF(cx + k * gap, cy), rad, rad)
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

    def paint(self, p, x0: float, width: float, H: int) -> None:
        pos = self.v.position() - self.v.track_offset()
        live = self.v.sounding(pos) if self.v.synced else []
        top = self.v.anchor()
        y = top - self.v.scroll
        self.v.line_rects = []
        deferred: list[tuple] = []
        for i, ln in enumerate(self.v.lines):
            rows, fm, h, rrows, rfm, ruby, rufm = self.v.layout_line(i, width)
            ox = self.v.line_ox(ln, fm, x0)
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
            self.v.line_rects.append((i, y + self.v.scroll, h, lo, hi))
            nxt_bg = i + 1 < len(self.v.lines) and self.v.lines[i + 1]["background"]
            gap = fm.height() * (0.16 if (ln["background"] or nxt_bg) else 0.42)
            m = H if (self.v.zero_g > 0 or self.v.clouds > 0) else 40
            far = (self.v.clouds > 0 and live
                   and min(abs(i - j) for j in live) > 3)
            if not far and y + h > -m and y < H + m:
                args = (i, ln, rows, fm, x0, y, pos, live, rrows, rfm, ruby, rufm)
                if self.v.clouds > 0 and (i in live
                                        or self.v.activation.get(i, 0.0) > 0.02):
                    deferred.append(args)
                else:
                    self._paint_line(p, *args)
            y += h + gap * self.v.line_spacing
        for args in deferred:
            self._paint_line(p, *args)
        self.v.content_h = y + self.v.scroll - top

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

    def word_lifts(self, rows, fm: QFontMetricsF, pos: float, act: float,
                   blur: float) -> dict:
        """How far each fragment has been lifted, keyed by (row, index in row).

        One lift per SYLLABLE, each setting off on its own stamp. This used to
        be one lift per word shared by every syllable in it, on the grounds
        that a word rising a syllable at a time tears in half -- the syllable
        the clock is inside at full height, the one after it still on the
        baseline.

        It does not stay torn, which is what that reasoning missed. The next
        syllable sets off when its own turn comes and closes the gap, and
        RISE_TIME is long enough next to a syllable that the two are always
        overlapping: what the eye gets is not a seam but a wave travelling
        through the word at the speed it is being sung. Whole-word rise threw
        that away -- a word four syllables long went up in one piece on the
        first of them, ahead of three syllables that had not been sung yet.

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
        out = {}
        unit = QFontMetricsF(self.v.lyric_font(False)).height()
        full = unit * 0.055 * self.v.rise * act * (1.0 - blur)
        for r_i, row in enumerate(rows):
            for f_i, (_x, _w, txt, s, e) in enumerate(row):
                if s is None or e is None or pos <= s - RISE_LEAD:
                    continue
                if not txt.strip():
                    continue
                lift = _smooth((pos - (s - RISE_LEAD)) / RISE_TIME) * full
                if lift <= 0.01:
                    continue
                out[(r_i, f_i)] = lift
        return out

    def draw_base(self, p, ln, rows, fm: QFontMetricsF, ox: float, y: float,
                  alpha: float, lifted: dict, rrows, rfm, ruby, rufm,
                  spin) -> None:
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
        """
        p.save()
        p.setPen(self.v.base_color(ln))
        p.setOpacity(alpha)
        font = self.v.lyric_font(ln["background"])
        ruh = self.v.ruby_h(rufm)
        rufont = self.v.ruby_font(ln) if rufm is not None else None
        ry = y + ruh + fm.ascent()
        for r_i, row in enumerate(rows):
            if rufont is not None and r_i < len(ruby):
                p.setFont(rufont)
                by = ry - fm.ascent() - ruh + rufm.ascent()
                for cx, read, _s, _e in ruby[r_i]:
                    p.drawText(QPointF(
                        ox + cx - rufm.horizontalAdvance(read) / 2, by), read)
            p.setFont(font)
            for f_i, (x, w, txt, _s, _e) in enumerate(row):
                # The word being spun draws its own base, turned; a second
                # copy sitting still underneath it is the thing the old clip
                # was cutting away.
                if spin is not None and (r_i, x) == (spin[0], spin[1]):
                    continue
                p.drawText(QPointF(ox + x, ry - lifted.get((r_i, f_i), 0.0)), txt)
            ry += fm.height() * 1.06 + ruh
        if rrows and rfm is not None:
            p.setFont(self.v.roman_font(ln))
            ry += fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent()
            for row in rrows:
                for x, _w, txt, _s, _e in row:
                    p.drawText(QPointF(ox + x, ry), txt)
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
        if self.v.focus and live and self.v.browse < 0.5:
            if dist > self.v.focus + 1:
                return
            if dist == self.v.focus + 1:
                act = 0.0
        blur = 0.0 if dist == 0 else min(9.0, 1.4 * dist**1.35)
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
        y = y + (1.0 - act) * 7.0 * (1 if idx in live else 0)

        if ln.get("dots"):
            self._paint_dots(p, ln, fm, ox, y, pos, act,
                             self.v.vfade(y + fm.height() * 0.5), width)
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
        spin = self.spin_frag(rows, fm, ox, y, self.v.ruby_h(rufm), pos)
        lifted = self.word_lifts(rows, fm, pos, act, blur)
        # Whether the line draws its own text is decided by whether the rise
        # can reach it at all, not by whether anything has lifted YET: live
        # text and a blitted pixmap do not rasterise quite alike, and switching
        # between them at the moment the first word sets off puts a visible
        # change of weight in the middle of a line. Switching when the line
        # activates hides it under the fade that is happening anyway.
        own_text = self.v.rise > 0 and act > 0.01 and blur < 1.0
        p.save()
        if own_text:
            self.draw_base(p, ln, rows, fm, ox, y, alpha, lifted,
                           rrows, rfm, ruby, rufm, spin)
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

        if act <= 0.01:
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
            if rufont is not None and r_i < len(ruby):
                p.setFont(rufont)
                by = ry - fm.ascent() - ruh + rufm.ascent()
                for cx, read, s, e in ruby[r_i]:
                    if s is None or e is None or pos < s:
                        continue
                    p.setPen(sung)
                    p.setOpacity(act * (1.0 if pos >= e else 0.55))
                    p.drawText(QPointF(ox + cx - rufm.horizontalAdvance(read) / 2, by), read)
                p.setOpacity(1.0)
                p.setFont(font)
            for f_i, (x, w, txt, s, e) in enumerate(row):
                px = ox + x
                if s is None or e is None:
                    continue
                frac = 1.0 if pos >= e else (0.0 if pos <= s else (pos - s) / max(1e-6, e - s))
                if frac <= 0:
                    continue
                singing = s <= pos < e
                held = min(1.0, max(0.0, (e - s - 0.18) / 1.1))
                if self.v.glow_scale > 0 and singing and held > 0.02:
                    core = txt.rstrip()
                    lenf = min(1.0, max(0.0, (len(core.strip()) - 1) / 7.0))
                    strength = held * (0.55 + 0.45 * lenf)
                    radius = max(1, int(2 + 8 * strength))
                    gp = self.v.glow_pixmap(core, font, radius)
                    swell = math.sin(math.pi * frac) ** 0.7
                    shimmer = 0.86 + 0.14 * math.sin(now * 6.5 + s * 4.0)
                    grow = 1.0 + 0.38 * swell * strength
                    gw, gh = gp.width(), gp.height()
                    pad = radius * 3
                    ccx = px - pad + gw / 2
                    ccy = ry - fm.ascent() - pad + gh / 2
                    p.setOpacity(min(1.0, act * (0.16 + 0.66 * strength)
                                     * swell * shimmer * self.v.glow_scale))
                    p.drawPixmap(
                        QRectF(ccx - gw * grow / 2, ccy - gh * grow / 2,
                               gw * grow, gh * grow),
                        gp, QRectF(gp.rect()),
                    )
                    p.setOpacity(1.0)
                p.save()
                rise = lifted.get((r_i, f_i), 0.0)
                if rise:
                    # draw_base has already put this word's un-sung self at the
                    # same height; the fill goes over it.
                    p.translate(0.0, -rise)
                gate = 1.0 if self.v.pop_min <= 0 else min(1.0, (e - s - self.v.pop_min) / 0.2)
                if self.v.pop > 0 and singing and gate > 0:
                    k = math.sin(math.pi * frac) * act * gate
                    lift = k * self.v.pop * fm.height() * 0.055
                    grow = 1.0 + k * self.v.pop * 0.035
                    p.translate(px + w * 0.5, ry - fm.ascent() * 0.35 - lift)
                    p.scale(grow, grow)
                    p.translate(-(px + w * 0.5), -(ry - fm.ascent() * 0.35))
                if spin is not None and (r_i, x) == (spin[0], spin[1]):
                    cx, cy = px + w * 0.5, ry - fm.ascent() * 0.35
                    p.translate(cx, cy)
                    p.rotate(360.0 * self.v.spin * frac)
                    p.translate(-cx, -cy)
                    p.setPen(TEXT)
                    p.setOpacity(alpha)
                    p.drawText(QPointF(px, ry), txt)
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
                p.drawText(QPointF(px, ry), txt)
                p.restore()
            ry += fm.height() * 1.06 + ruh
        if rrows and rfm is not None:
            rfont = self.v.roman_font(ln)
            p.setFont(rfont)
            ry += fm.height() * 0.10 - fm.ascent() - ruh + rfm.ascent()
            for row in rrows:
                for x, w, txt, s, e in row:
                    if s is None or e is None:
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
                    p.setOpacity(act * 0.85)
                    p.drawText(QPointF(px, ry), txt)
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

    They also draw every word live. The stack caches an un-sung line as a
    pre-blurred pixmap because it has thirty of them on screen; two lines at a
    size of their own would miss that cache on every frame it mattered.
    """

    scrolls = False

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

    def current(self, pos: float):
        """The line to build the frame around, and the one after it."""
        v = self.v
        live = v.sounding(pos) if v.synced else []
        cur = next((i for i in live if self.singable(i)), None)
        if cur is None:
            return None, None
        nxt = next((j for j in range(cur + 1, len(v.lines))
                    if self.singable(j)), None)
        return cur, nxt

    def before(self, cur):
        """The line before the one being sung, if there is one to show."""
        if cur is None:
            return None
        return next((j for j in range(cur - 1, -1, -1)
                     if self.singable(j)), None)

    def mark(self, i: int, top: float, h: float, x0: float, width: float) -> None:
        """Publish a line's box so a click on it seeks there.

        In the space the stack publishes in: screen y plus view.scroll, which
        is 0 for everything here. line_at subtracts the anchor from the click
        and from the box alike, so it cancels and must not be added in.
        """
        self.v.line_rects.append((i, top + self.v.scroll, h, x0, x0 + width))

    def row_lifts(self, row, fm: QFontMetricsF, pos: float, act: float) -> dict:
        """How far each fragment in one row has lifted, keyed by its index.

        The same rule the stack uses and for the same reason: one lift per
        SYLLABLE, so the rise travels through a word as it is sung instead of
        taking the whole word up on its first syllable. See Flow.word_lifts.
        """
        if self.v.rise <= 0 or act <= 0.01:
            return {}
        out = {}
        full = fm.height() * 0.055 * self.v.rise * act
        for f_i, (_x, _w, txt, s, e) in enumerate(row):
            if s is None or e is None or pos <= s - RISE_LEAD or not txt.strip():
                continue
            lift = _smooth((pos - (s - RISE_LEAD)) / RISE_TIME) * full
            if lift > 0.01:
                out[f_i] = lift
        return out

    def draw_row(self, p, row, ox: float, ry: float, fm: QFontMetricsF,
                 pos: float, act: float, alpha: float,
                 sung, base, clear) -> None:
        """One wrapped row of a line, filled to the clock.

        Un-sung text first and the fill over it, both under whatever transform
        the pop and the rise have put on the painter -- so a word that lifts
        takes all of itself with it. Nothing is cached and nothing is clipped,
        which is why these renderers never had the stack's trouble of a cut
        rectangle biting a neighbouring glyph.
        """
        lifts = self.row_lifts(row, fm, pos, act)
        for f_i, (x, w, txt, s, e) in enumerate(row):
            px = ox + x
            p.save()
            lift = lifts.get(f_i, 0.0)
            if lift:
                p.translate(0.0, -lift)
            if s is not None and e is not None:
                frac = (1.0 if pos >= e else
                        (0.0 if pos <= s else (pos - s) / max(1e-6, e - s)))
                gate = (1.0 if self.v.pop_min <= 0
                        else min(1.0, (e - s - self.v.pop_min) / 0.2))
                if self.v.pop > 0 and s <= pos < e and gate > 0:
                    k = math.sin(math.pi * frac) * act * gate
                    cx, cy = px + w * 0.5, ry - fm.ascent() * 0.35
                    grow = 1.0 + k * self.v.pop * 0.035
                    p.translate(0.0, -k * self.v.pop * fm.height() * 0.055)
                    p.translate(cx, cy)
                    p.scale(grow, grow)
                    p.translate(-cx, -cy)
            else:
                frac = 0.0
            p.setPen(base)
            p.setOpacity(alpha)
            p.drawText(QPointF(px, ry), txt)
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
                p.drawText(QPointF(px, ry), txt)
            p.restore()
        p.setOpacity(1.0)

    def draw_block(self, p, ln, rows, fm: QFontMetricsF, x0: float,
                   width: float, top: float, pos: float, act: float,
                   alpha: float) -> float:
        """A whole line's rows, laid down from `top`. Returns its height."""
        sung = self.v.sung_color(ln)
        base = self.v.base_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ry = top + fm.ascent()
        for row in rows:
            self.draw_row(p, row, x0, ry, fm, pos, act, alpha, sung, base, clear)
            ry += fm.height() * 1.06
        return len(rows) * fm.height() * 1.06


class Spotlight(Pinned):
    """The line being sung, alone and large, between the two either side of it.

    Nothing moves up the window: a line arrives where the last one was and the
    two cross-fade, which is why every line with any activation left in it is
    drawn rather than only the current one. tick() eases those activations
    already, so the fade costs nothing here.

    The neighbours are set small and dim, and hung off the top and bottom of
    whatever the middle line actually came out to be rather than off a guess at
    how tall one line is -- a couplet that wraps to three rows would otherwise
    have them printed through it. All three take a click.
    """

    name = "spotlight"

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        v.line_rects = []
        v.content_h = 0.0
        pos = v.position() - v.track_offset()
        cur, nxt = self.current(pos)
        prv = self.before(cur)
        big, small = self.font(v.lyric_px() * 1.5), self.font(v.lyric_px() * 0.62)
        fm_big, fm_sm = QFontMetricsF(big), QFontMetricsF(small)

        head = foot = H * 0.46
        show = sorted(
            (i for i in range(len(v.lines))
             if self.singable(i) and (i == cur or v.activation.get(i, 0.0) > 0.02)),
            key=lambda i: v.activation.get(i, 0.0))
        p.setFont(big)
        for i in show:
            ln = v.lines[i]
            act = 1.0 if i == cur else v.activation.get(i, 0.0)
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
    """Two lines in the middle of the window, alternating.

    The one being sung fills; the other already says what is coming. Which of
    the two rows a line lands in is decided by its own index, not by which is
    free, so a line never changes row halfway through being sung -- that is the
    whole reason the pair alternates rather than scrolling.
    """

    name = "karaoke"

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        v.line_rects = []
        v.content_h = 0.0
        pos = v.position() - v.track_offset()
        cur, nxt = self.current(pos)
        if cur is None:
            return
        fm = QFontMetricsF(self.font(v.lyric_px() * 0.94))
        p.setFont(self.font(v.lyric_px() * 0.94))
        # Two bands of a fixed height, so the pair can never reach each other
        # however many rows either line wraps to -- a slot whose position came
        # out of its own line's height is a slot that moves, and the point of
        # the alternation is that neither of them does. A line taller than its
        # band grows out of the middle of it in both directions.
        band = fm.height() * 2.4
        low = H * 0.5                       # top of the lower of the two
        for i, act, alpha in ((cur, 1.0, 0.34), (nxt, 0.0, 0.20)):
            if i is None:
                continue
            ln = v.lines[i]
            rows = self.rows_of(ln, fm, width)
            h = len(rows) * fm.height() * 1.06
            top = (low if i % 2 else low - band) + (band - h) / 2
            if ln.get("dots"):
                self._paint_dots(p, ln, fm, x0, top, pos, act, alpha, width,
                                 "center")
                continue
            self.draw_block(p, ln, rows, fm, x0, width, top, pos, act, alpha)
            self.mark(i, top, h, x0, width)


class Word(Pinned):
    """One word at a time, very large, in the middle of the window.

    A word, not a syllable. Word-timed documents are timed per syllable and the
    layout keeps them that way -- which is what lets the fill sweep through a
    held note -- so the syllables are put back together here and the word takes
    the span of the ones that spell it. Otherwise a line of Apple Music TTML
    reads out as "you", "'", "re" rather than as the words being sung.

    A line with no word timing under it has nothing to take apart, so it is
    drawn whole instead -- which is also what happens to every line of a
    line-synced source, and is why this degrades rather than going blank.
    """

    name = "word"

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

        # Laid out against a width nothing can wrap at, so the line comes
        # back as one row and every word in it is whole.
        flat = self.rows_of(ln, fm_line, width * 8)
        timed = []
        for run in self.words_of(flat[0] if flat else []):
            s, e = self.span_of(run)
            txt = "".join(f[2] for _k, f in run).strip()
            if s is not None and e is not None and txt:
                timed.append((txt, s, e))
        if not timed:
            # Nothing to pick from: the whole line, centred.
            p.setFont(self.font(v.lyric_px() * 1.1))
            rows = self.rows_of(ln, fm_line, width)
            h = len(rows) * fm_line.height() * 1.06
            self.draw_block(p, ln, rows, fm_line, x0, width, H * 0.46 - h / 2,
                            pos, 1.0, 0.34)
            self.mark(cur, H * 0.46 - h / 2, h, x0, width)
            return

        # The word sounding, or the last one the clock went past. Never the
        # one coming: this renderer says where the song IS.
        pick = None
        for word in timed:
            if word[1] <= pos:
                pick = word
            if word[1] <= pos < word[2]:
                break
        if pick is None:
            pick = timed[0]
        txt, s, e = pick

        font = self.font(v.lyric_px() * 2.6)
        fm = QFontMetricsF(font)
        p.setFont(font)
        w = fm.horizontalAdvance(txt)
        row = [(0.0, w, txt, s, e)]
        sung = v.sung_color(ln)
        base = v.base_color(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ox = x0 + (width - w) / 2
        self.draw_row(p, row, ox, H * 0.46 + fm.ascent() / 2, fm, pos,
                      1.0, 0.34, sung, base, clear)
        self.mark(cur, H * 0.46 - fm.height() / 2, fm.height(), ox, w)


class Cards(Pinned):
    """A card per line: up from below as it arrives, away above once past.

    Every card takes a click, over the whole of its rounded rectangle rather
    than over the text alone -- the card is what the reader is aiming at.

    The stack moves the window over the lines; this moves the lines past the
    window. Only the line being sung and its two neighbours are ever drawn, and
    where each of them sits comes from the activations tick() is already
    easing -- so there is no motion of this renderer's own to keep alive.
    """

    name = "cards"
    REACH = 1                    # neighbours either side

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        v.line_rects = []
        v.content_h = 0.0
        pos = v.position() - v.track_offset()
        cur, _nxt = self.current(pos)
        if cur is None:
            return
        fm = QFontMetricsF(self.font(v.lyric_px()))
        p.setFont(self.font(v.lyric_px()))
        pad = fm.height() * 0.55
        gap = fm.height() * 0.5

        # Measured before any of it is drawn. A fixed step between cards is a
        # step that is wrong for every line that wraps -- one long enough for
        # two rows prints through the card above it -- so the stack is laid out
        # from the real heights and hung off the middle card.
        want = [i for i in range(cur - self.REACH, cur + self.REACH + 1)
                if 0 <= i < len(v.lines) and self.singable(i)]
        rows_of = {i: self.rows_of(v.lines[i], fm, width - pad * 2)
                   for i in want}
        high = {i: len(rows_of[i]) * fm.height() * 1.06 + pad * 2 for i in want}
        top_of = {cur: H * 0.46 - high[cur] / 2}
        y = top_of[cur]
        for i in range(cur - 1, cur - self.REACH - 1, -1):   # upwards
            if i in high:
                y = top_of[i] = y - high[i] - gap
        y = top_of[cur] + high[cur] + gap
        for i in range(cur + 1, cur + self.REACH + 1):       # downwards
            if i in high:
                top_of[i] = y
                y += high[i] + gap

        # Back to front: the card being sung is drawn last and sits over its
        # neighbours wherever a long line brings them close.
        for i in sorted(want, key=lambda k: abs(k - cur), reverse=True):
            ln = v.lines[i]
            act = 1.0 if i == cur else v.activation.get(i, 0.0)
            # The card slides the last of the way in on the activation, so a
            # line arrives moving and stops where the one before it stopped.
            # Signed by which side of the current line it is: what is coming
            # rises from below and what is done carries on up, which is also
            # what keeps a card that has not arrived out of the one above it.
            slide = (1.0 - act) * fm.height() * 0.8 * (1 if i > cur else -1)
            top = top_of[i] + pad + slide
            fade = 1.0 if i == cur else 0.38
            h = high[i] - pad * 2
            if ln.get("dots"):
                self._paint_dots(p, ln, fm, x0 + pad, top, pos, act,
                                 fade * 0.9, width - pad * 2, "center")
                continue
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, int(20 * fade + 10 * act)))
            p.drawRoundedRect(QRectF(x0, top - pad, width, h + pad * 2),
                              pad * 0.7, pad * 0.7)
            p.setBrush(Qt.BrushStyle.NoBrush)
            self.draw_block(p, ln, rows_of[i], fm, x0 + pad, width - pad * 2,
                            top, pos, act, 0.34 * fade)
            self.mark(i, top - pad, h + pad * 2, x0, width)


RENDERERS = {r.name: r for r in (Flow, Snap, Spotlight, Karaoke, Word, Cards)}
RENDER_MODES = list(RENDERERS)
