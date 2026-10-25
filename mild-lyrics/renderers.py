"""How the lyric column is drawn: `Flow` (the stack, default) and its siblings.
A renderer must leave view.line_rects and view.content_h; it may set
`stacked` and answer `line_scale(i)`."""
import functools
import math
import re
import unicodedata
from collections import OrderedDict

import frame_clock as FCK
import language as LANG
import periodic as PT

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,
                         QLinearGradient,
                         QPaintEngine, QPainter, QPen, QPixmap,
                         QRadialGradient, QRegion,
                         QTextLayout, QTransform)

mono = FCK.mono     # the window's clock, from frame_clock (importing the window
                    # here would load a second copy of it when run as a script)


NUDGE = 1.0 + 1e-7


def blit(p: QPainter, target, pm, src=None) -> None:
    """drawPixmap at the exact fractional position asked for, not snapped to a
    whole pixel (every renderer picture goes through here)."""
    # Set and put back by hand rather than save/restore: ~200 calls a frame,
    # and the whole-state copy was most of their Python cost.
    smooth = p.testRenderHint(_SMOOTH)
    if not smooth:
        p.setRenderHint(_SMOOTH)
    t = p.transform()
    shift = t.type() in _SHIFTS
    if shift:
        p.setTransform(_NUDGE_T * t)
    if src is None:
        p.drawPixmap(target, pm)
    else:
        p.drawPixmap(target, pm, src)
    if shift:
        p.setTransform(t)
    if not smooth:
        p.setRenderHint(_SMOOTH, False)


_SMOOTH = QPainter.RenderHint.SmoothPixmapTransform
_SHIFTS = frozenset((QTransform.TransformationType.TxNone,
                     QTransform.TransformationType.TxTranslate))
_NUDGE_T = QTransform(1.0, 0.0, 0.0, NUDGE, 0.0, 0.0)
_TX_SCALE = QTransform.TransformationType.TxScale


_FONT_KEYS: dict = {}


def font_key(font: QFont) -> str:
    """font.key(), kept: equal fonts have equal keys, and hashing one costs
    a fifth of building the string."""
    k = _FONT_KEYS.get(font)
    if k is None:
        if len(_FONT_KEYS) > 256:
            _FONT_KEYS.clear()
        k = _FONT_KEYS[font] = font.key()
    return k


def adv(fm: QFontMetricsF, txt: str) -> float:
    """fm.horizontalAdvance(txt), kept on the metrics object -- the same memo
    as lyrics_gui.advance. The column asks ~130 widths a frame, up to 6us each."""
    try:
        memo = fm._adv
    except AttributeError:
        memo = fm._adv = {}
    w = memo.get(txt)
    if w is None:
        if len(memo) > 8192:
            memo.clear()
        w = memo[txt] = fm.horizontalAdvance(txt)
    return w


TEXT = None
_smooth = None
soft_scale = None

RISE_LEAD = 0.06
RISE_TIME = 0.30

STAYING = (0.0, None, 1.0)

MAX_BLUR = 9

WARM_EDGE = 40

WORD_CACHE_BYTES = 8 * 2**20

# all_glow's strips as one drawPixmapFragments on the GL engine; see _glow_flush.
GLOW_FRAGMENTS = True


def row_rtl(row) -> bool:
    """Whether a wrapped row reads right to left, so the fill comes in from the
    right."""
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


def whole_find(row: str, text: str, start: int = 0) -> int:
    """row.find(text), skipping hits inside a longer word, so a maker
    called "b" is not found in "Made by"."""
    cut = row.find(text, start)
    while cut >= 0:
        end = cut + len(text)
        before = row[cut - 1] if cut else ""
        past = row[end] if end < len(row) else ""
        if not ((before.isalnum() and text[0].isalnum())
                or (past.isalnum() and text[-1].isalnum())):
            return cut
        cut = row.find(text, cut + 1)
    return -1


def _gl_scaled(p) -> bool:
    """Whether `p` is Qt's GL engine on a scaled screen. There its glyphs
    differ from raster ones (and a gradient pen lands at its coordinates
    divided by the scale), so all text goes through a CPU picture to match
    the cached line pictures (see docs/notes/mild-lyrics/renderers.md)."""
    eng = p.paintEngine()
    if eng is None or eng.type() != QPaintEngine.Type.OpenGL2:
        return False
    dev = p.device()
    return dev is not None and abs(dev.devicePixelRatioF() - 1.0) > 1e-3


def _pad_of(pm: QPixmap, width: float) -> int:
    """The margin a line picture was built with, read off the picture: a
    stand-in at another blur level (see _nearest_blur) has another margin,
    and placing it by the asked-for one drew it off to the side."""
    return max(0, (round(pm.deviceIndependentSize().width()) - int(width)) // 2)


def _blur(v) -> float:
    """Depth blur as drawn now -- 0 while saving power without Keep depth blur."""
    now = getattr(v, "blur_now", None)
    return now() if now is not None else getattr(v, "blur_scale", 1.0)


def _playing(v) -> bool:
    """Whether the song is going: the editor's file while it draws, else the player.

    Not the player's status alone -- slowed, the editor parks Spotify paused
    while its own file plays on, which read as a seek every frame.
    """
    ask = getattr(v, "song_playing", None)
    if ask is not None:
        return bool(ask())
    return getattr(getattr(v, "clock", None), "status", "") == "Playing"


class Renderer:
    """The contract. See the module docstring for what has to be left behind."""

    name = ""
    scrolls = True
    stacked = False
    snap = False
    SCALE_EPS = 5e-4

    def __init__(self, view) -> None:
        self.v = view
        self._words: OrderedDict = OrderedDict()
        self._words_bytes = 0

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
        """What line `i` was last drawn scaled by about its own centre; 1.0
        unless a renderer scales lines (the review marks need it)."""
        return 1.0

    @staticmethod
    def scale_about(p, s: float, x0: float, width: float,
                    y: float, h: float) -> None:
        """Put the painter under line `i`'s scale (caller has saved); shared by
        the renderer and the review marks so they agree on the centre."""
        cx, cy = x0 + width * 0.5, y + h * 0.5
        p.translate(cx, cy)
        p.scale(s, s)
        p.translate(-cx, -cy)

    @staticmethod
    def words_of(row):
        """A wrapped row's fragments grouped into words, [[(index, fragment),
        ...]]: a word ends at a trailing space or a trailing hyphen."""
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
        """How long the word was sung: its fragments' lengths added up, holes
        left out."""
        got = [f[4] - f[3] for _k, f in run
               if f[3] is not None and f[4] is not None and f[4] > f[3]]
        return sum(got) if got else None

    def rise_plan(self, rows) -> list:
        """When every inked fragment of the line sets off, as (row, index,
        start), held to reading order. See renderers.md, "the rise
        schedule"."""
        plan, last = [], None
        for r_i, row in enumerate(rows):
            for f_i, (_x, _w, txt, s, _e) in enumerate(row):
                if s is None or not txt.strip():
                    continue
                last = s if last is None else max(s, last)
                plan.append((r_i, f_i, last - RISE_LEAD))
        return plan

    def lifted_word(self, p, at, txt: str, lift: float, fm: QFontMetricsF,
                    grow: float = 1.0, cx: float = 0.0, cy: float = 0.0,
                    exact: bool = False) -> None:
        """drawText for a word between two pixel rows: drawn into a small
        picture at a whole pixel, then blitted at its true height (`grow` is
        the pop)."""
        y = at.y() - lift
        dpr = self.v.devicePixelRatioF() or 1.0
        # Whether it lands on a screen row: a gliding line carries its fraction
        # in the painter's translation, and under a scale it never does (Amll's
        # arriving line), so those words are drawn as pictures.
        t = p.transform()
        shift = t.type() in _SHIFTS
        dy = t.dy() if shift else 0.0
        on_row = (shift
                  and abs((y + dy) * dpr - round((y + dy) * dpr)) < 0.02)
        if (grow == 1.0 and on_row and not exact
                and (dpr == 1.0 or not _gl_scaled(p))):
            row = round((y + dy) * dpr) / dpr
            if dy == round(dy):
                p.drawText(QPointF(at.x(), row - dy), txt)
                return
            # Qt's GL engine sets text a pixel high under a translate of 0 to
            # 0.5px, so a settling letter hopped up for the frames it landed
            # on a row. Drawn with the fraction taken off the painter instead.
            p.setTransform(QTransform.fromTranslate(t.dx(), 0.0))
            p.drawText(QPointF(at.x(), row), txt)
            p.setTransform(t)
            return
        m = max(3.0, fm.height() * 0.22)
        # `exact`: a letter of a held word pushed sideways is a picture every
        # frame carrying the fraction (Qt places glyphs in quarter pixels);
        # nothing else is.
        if exact:
            mx = math.ceil(m * dpr) / dpr
            ox = at.x() - mx
        else:
            mx = m
            ox = math.floor((at.x() - m) * dpr) / dpr
        oy = math.floor((at.y() - fm.ascent() - m) * dpr) / dpr
        pw = int(math.ceil((adv(fm, txt) + mx * 2) * dpr)) + 2
        ph = int(math.ceil((fm.height() + m * 2) * dpr)) + 2
        if pw <= 0 or ph <= 0:
            p.drawText(QPointF(at.x(), y), txt)
            return
        pm = self._word_picture(p, at, txt, ox, oy, pw, ph, dpr)
        p.save()
        if grow != 1.0:
            p.translate(cx, cy)
            p.scale(grow, grow)
            p.translate(-cx, -cy)
        blit(p, QPointF(ox, oy - lift), pm)
        p.restore()

    def grad_text(self, p, at: QPointF, txt: str) -> None:
        """drawText, except where _gl_scaled: then the same word as a CPU
        picture put in its place."""
        if not _gl_scaled(p):
            p.drawText(at, txt)
            return
        fm = QFontMetricsF(p.font())
        dpr = self.v.devicePixelRatioF() or 1.0
        m = max(3.0, fm.height() * 0.22)
        ox = math.floor((at.x() - m) * dpr) / dpr
        oy = math.floor((at.y() - fm.ascent() - m) * dpr) / dpr
        pw = int(math.ceil((adv(fm, txt) + m * 2) * dpr)) + 2
        ph = int(math.ceil((fm.height() + m * 2) * dpr)) + 2
        if pw <= 0 or ph <= 0:
            return
        blit(p, QPointF(ox, oy), self._word_picture(p, at, txt, ox, oy,
                                                     pw, ph, dpr))

    def _word_picture(self, p, at, txt: str, ox: float, oy: float,
                      pw: int, ph: int, dpr: float) -> QPixmap:
        """lifted_word's picture of `txt`, kept between frames by text, font,
        pen and sub-pixel offset (gradient pens never). Up to 8MB."""
        pen = p.pen()
        key = None
        if pen.brush().style() == Qt.BrushStyle.SolidPattern:
            key = (txt, font_key(p.font()), pen.color().getRgbF(), pen.widthF(),
                   at.x() - ox, at.y() - oy, pw, ph, dpr)
            pm = self._words.get(key)
            if pm is not None:
                self._words.move_to_end(key)
                return pm
        pm = QPixmap(pw, ph)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        pp = QPainter(pm)
        pp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pp.translate(-ox, -oy)
        pp.setFont(p.font())
        pp.setPen(pen)
        pp.drawText(at, txt)
        pp.end()
        if key is not None:
            self._words[key] = pm
            self._words_bytes += pw * ph * 4
            while (self._words_bytes > WORD_CACHE_BYTES * max(1.0, dpr * dpr)
                   and len(self._words) > 1):
                _k, old = self._words.popitem(last=False)
                self._words_bytes -= old.width() * old.height() * 4
        return pm

    _SHAPED: dict = {}
    _UNITS: dict = {}

    @classmethod
    def shaped_units(cls, txt: str, font: QFont, fm: QFontMetricsF) -> tuple:
        """`txt` cut where the font lets it be: ((piece, x), ...), ligatures
        kept whole."""
        key = (txt, font_key(font))
        hit = cls._UNITS.get(key)
        if hit is not None:
            return hit
        starts = {0}
        try:
            lay = QTextLayout(txt, font)
            lay.beginLayout()
            line = lay.createLine()
            if line.isValid():
                line.setLineWidth(1e6)
            lay.endLayout()
            fl = QTextLayout.GlyphRunRetrievalFlag
            want = fl(fl.RetrieveGlyphIndexes.value
                      | fl.RetrieveGlyphPositions.value
                      | fl.RetrieveStringIndexes.value)
            got = {}
            runs = lay.glyphRuns(-1, -1, want)
            if len(runs) > 1:
                # A word in more than one font (a fallback glyph) comes back
                # with its string indexes all 0, so each character is asked
                # on its own (Qt counts UTF-16). One that lands where the one
                # before it did is inside its cluster: a ligature.
                u16, last = 0, None
                for i, ch in enumerate(txt):
                    n = 2 if ord(ch) > 0xFFFF else 1
                    xs = [pt.x() for r in lay.glyphRuns(u16, n, want)
                          for pt in r.positions()]
                    if xs and (last is None or min(xs) != last):
                        got[i] = last = min(xs)
                    u16 += n
                runs = ()
            for run in runs:
                for si, pt in zip(run.stringIndexes(), run.positions()):
                    got[si] = min(got.get(si, pt.x()), pt.x())
            if got:
                starts = set(got) | {0}
        except Exception:
            got = {}
        offs = cls.shaped_offsets(txt, font, fm)
        out, at = [], 0
        for g in Amll.graphemes(txt):
            if at in starts or not out:
                out.append([g, got.get(at, offs[at] if at < len(offs) else 0.0)])
            else:
                out[-1][0] += g
            at += len(g)
        hit = tuple((p, x) for p, x in out)
        if len(cls._UNITS) > 4096:
            cls._UNITS.clear()
        cls._UNITS[key] = hit
        return hit

    @classmethod
    def shaped_offsets(cls, txt: str, font: QFont, fm: QFontMetricsF) -> tuple:
        """Where a drawText of `txt` actually puts each character (kerning
        included), cached per text and face; prefix widths as fallback."""
        key = (txt, font_key(font))
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
                   emph=None, pen_at=None) -> None:
        """A fragment drawn as one word or as separate characters, the same way
        in the unsung and sung layers."""
        if emph is None:
            self.lifted_word(p, at, txt, lift, fm, grow, cx, cy)
            return
        # A letter at a time, each in the slot emph_plan gave it, at its own
        # height and its own size about its own middle -- AMLL's per-letter
        # emphasis. `grow` is the whole word's (a troll's flight), so it goes
        # on the painter first and the letters move inside it.
        p.save()
        if grow != 1.0:
            p.translate(cx, cy)
            p.scale(grow, grow)
            p.translate(-cx, -cy)
        # Placed exactly only while a letter is really off its rest place or
        # size: standing where the word put it, it is drawn as the word would
        # draw it, so a word starting or ending its emphasis does not change
        # by a pixel (the kern checks hold it to that).
        units = self.shaped_units(txt.strip(), p.font(), fm)
        rest = ([ux for _u, ux in units] if len(units) == len(emph.parts)
                else None)
        for i, (ch, dx, up, scale, _lit) in enumerate(emph.parts):
            if pen_at is not None:
                p.setPen(pen_at(i))
            x = at.x() + dx
            rise = lift + up
            moved = (scale != 1.0 or rest is None
                     or abs(dx - rest[i]) > 0.01)
            self.lifted_word(p, QPointF(x, at.y()), ch, rise, fm, scale,
                             x + adv(fm, ch) * 0.5,
                             at.y() - fm.ascent() * 0.35 - rise, exact=moved)
        p.restore()

    def swell_of(self, s, e, pos: float, act: float) -> float:
        """How far into its swell a syllable is (0..1), on its own clock, only
        when held at least `pop_min`; shared by the pop and the glow."""
        if s is None or e is None or act <= 0.01 or not s <= pos < e:
            return 0.0
        bar = float(getattr(self.v, "pop_min", 0.0) or 0.0)
        gate = 1.0 if bar <= 0 else min(1.0, (e - s - bar) / 0.2)
        if gate <= 0:
            return 0.0
        return math.sin(math.pi * (pos - s) / max(1e-6, e - s)) * act * gate

    def pop_of(self, s, e, pos: float, act: float,
               fm: QFontMetricsF) -> tuple:
        """(grow, lift in pixels) of a syllable's pop this frame.

        Asked by every layer that draws the syllable -- the un-sung text, the
        fill and the glow -- because a layer that leaves the pop out is a
        second copy of the word sitting still under the one that swells.
        """
        pop = float(getattr(self.v, "pop", 0.0) or 0.0)
        k = self.swell_of(s, e, pos, act) if pop > 0 else 0.0
        if k <= 0:
            return 1.0, 0.0
        return 1.0 + k * pop * 0.035, k * pop * fm.height() * 0.055

    def long_glow(self, p, txt: str, font: QFont, fm: QFontMetricsF,
                  at: QPointF, s, e, pos: float, act: float, lift: float,
                  grow: float, fade: float, ln: dict | None = None) -> None:
        """Glow long words: a halo behind a syllable only while it swells.

        The same syllables the pop picks, lit on the same curve, so with
        `pop_glow` up and `glow` at 0 the light is on the held notes and
        nowhere else.
        """
        amount = float(getattr(self.v, "pop_glow", 0.0) or 0.0)
        core = txt.strip()
        if amount <= 0 or not core:
            return
        k = self.swell_of(s, e, pos, act)
        if k <= 0.004:
            return
        held = min(1.0, max(0.0, (e - s - 0.18) / 1.1))
        radius, strength = Flow.glow_of(core, fm, max(0.35, held))
        gp = self._glow_in(self.v.glow_pixmap(core, font, radius), ln)
        gw, gh = gp.width(), gp.height()
        pad = radius * 3
        lead = adv(fm, txt[:len(txt) - len(txt.lstrip())])
        ccx = at.x() + lead - pad + gw / 2
        ccy = at.y() - fm.ascent() - pad + gh / 2 - lift
        big = grow * (1.0 + 0.25 * k)
        p.setOpacity(min(1.0, fade * (0.35 + 0.65 * strength)
                         * k ** 0.7 * amount))
        blit(p, QRectF(ccx - gw * big / 2, ccy - gh * big / 2,
                       gw * big, gh * big), gp, QRectF(gp.rect()))
        p.setOpacity(1.0)

    def emph_shifts(self, emph, txt: str, font: QFont,
                    fm: QFontMetricsF) -> list:
        """How far each letter of a held fragment stands from where it sits
        at rest -- the spread, which the fill edge and its light have to be
        carried along by. See the held-word branch of _paint_line_at."""
        units = self.shaped_units(txt.strip(), font, fm)
        if len(units) != len(emph.parts):
            return [0.0] * len(emph.parts)
        return [c[1] - ux for c, (_u, ux) in zip(emph.parts, units)]

    def emph_glow(self, p, emph, at, font: QFont, fm: QFontMetricsF,
                  lift: float, fade: float, edge: float | None = None,
                  soft: float = 0.0, shifts=None,
                  tint: QColor | None = None) -> None:
        """The light behind each character of a held word, masked at the fill
        `edge`."""
        # The light spills past the edge across `soft`, and is added (Plus)
        # before the letters so their ink covers it; in the line's glow colour
        # (`tint`), sized by HALO_SIZE / HALO_SCALE.
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for i, (ch, dx, up, scale, lit) in enumerate(emph):
            x = at.x() + dx
            edge_i = (edge if edge is None or shifts is None
                      else edge + shifts[i])
            if edge_i is not None and edge_i + soft <= x:
                continue
            radius = max(1, round(self.glow_of(ch, fm, emph.held)[0]
                                  * self.HALO_SIZE * 0.5))
            pad = radius * 3
            gw = adv(fm, ch) + pad * 2
            box_l = x - pad + gw / 2 - gw * scale / 2
            box_r = box_l + gw * scale
            straddles = edge_i is not None and edge_i - soft < box_r
            if straddles:
                # The word's own level spills onto the letter the edge is
                # reaching, handed back to the letter's own as the edge moves
                # on past it. Switched at once, it was a flash and a drop on
                # every letter in turn.
                hand = max(0.0, min(1.0, (box_r + soft - edge_i)
                                    / max(1e-6, 2.0 * soft)))
                lit += (max(lit, emph.lit) - lit) * hand
            if lit <= 0.004:
                continue
            gp = self.v.glow_pixmap(ch, font, radius)
            if tint is not None:
                gp = self._tinted(gp, tint)
            gw, gh = gp.width(), gp.height()
            ccx = x - pad + gw / 2
            ccy = at.y() - fm.ascent() - pad + gh / 2 - lift - up
            box = QRectF(ccx - gw * scale / 2, ccy - gh * scale / 2,
                         gw * scale, gh * scale)
            if straddles:
                if edge_i + soft <= box.left():
                    continue
                gp = self._masked(gp, box, edge_i, soft)
            p.setOpacity(min(1.0, fade * lit * self.HALO_SCALE))
            blit(p, box, gp, QRectF(gp.rect()))
        p.restore()
        p.setOpacity(1.0)

    _TINTS: "OrderedDict" = None
    TINT_BYTES = 16 << 20       # Memory use sets it to the glow budget
    _tint_bytes = 0

    def _glow_in(self, gp: QPixmap, ln: dict | None) -> QPixmap:
        """A flat-white glow in the colour the Glow colour setting asks for."""
        tint = getattr(self.v, "glow_tint_of", lambda _ln: None)(ln)
        return gp if tint is None else self._tinted(gp, tint)

    @classmethod
    def _tinted(cls, gp: QPixmap, tint: QColor) -> QPixmap:
        """The white glow picture `gp` in `tint`, kept: a handful of letters
        a frame, the same few frame after frame."""
        if cls._TINTS is None:
            cls._TINTS = OrderedDict()
        key = (gp.cacheKey(), tint.rgba())
        hit = cls._TINTS.get(key)
        if hit is not None:
            cls._TINTS.move_to_end(key)
            return hit
        out = QPixmap(gp.size())
        out.fill(Qt.GlobalColor.transparent)
        q = QPainter(out)
        q.drawPixmap(0, 0, gp)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        q.fillRect(out.rect(), tint)
        q.end()
        cls._TINTS[key] = out
        cls._tint_bytes += out.width() * out.height() * 4
        while len(cls._TINTS) > 1 and (len(cls._TINTS) > 256
                                       or cls._tint_bytes > cls.TINT_BYTES):
            _k, old = cls._TINTS.popitem(last=False)
            cls._tint_bytes -= old.width() * old.height() * 4
        return out

    @classmethod
    def drop_tints(cls) -> None:
        if cls._TINTS:
            cls._TINTS.clear()
        cls._tint_bytes = 0

    @staticmethod
    def _masked(gp: QPixmap, box: QRectF, edge: float,
                soft: float) -> QPixmap:
        """`gp` faded out to the right of `edge`, across `soft` either side,
        where `box` is where it will be put. Only the one letter the fill is
        crossing comes through here, so it is a copy a frame for that one."""
        out = QPixmap(gp.size())
        out.fill(Qt.GlobalColor.transparent)
        q = QPainter(out)
        q.drawPixmap(0, 0, gp)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        per = gp.width() / max(1e-6, box.width())
        mid = (edge - box.left()) * per
        half = max(0.5, soft * per)
        g = QLinearGradient(mid - half, 0.0, mid + half, 0.0)
        g.setColorAt(0.0, QColor(255, 255, 255, 255))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        q.fillRect(out.rect(), QBrush(g))
        q.end()
        return out

    def fill_edge(self, sweep, px: float, w: float, frac: float,
                  rtl: bool = False):
        """Where the fill has got to in a fragment, as fill_pen reads it: None
        for all of it, -inf for none of it."""
        if frac >= 1.0 or rtl:
            return None
        if frac > 0.0:
            return px + w * frac
        ed = sweep.near(px, w) if sweep is not None else None
        return float("-inf") if ed is None else ed

    def on_grid(self, dy: float) -> float:
        """A vertical distance rounded onto the pixel grid, for where a rise
        ends."""
        dpr = self.v.devicePixelRatioF()
        return round(dy * dpr) / dpr if dpr > 0 else round(dy)

    def frag_lifts(self, rows, full: float, pos: float) -> list:
        """How far each fragment has lifted in pixels, one dict per row, held
        below the one in front; the destination snapped to the grid, the
        travel not."""
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
        """The instrumental break's three filling dots. `align` for renderers
        that set their own; `flights` from Flow.dot_flights."""
        r = fm.height() * 0.19
        gap = r * 3.4
        span = max(1e-6, ln["end"] - ln["start"])
        t = max(0.0, min(1.0, (pos - ln["start"]) / span))
        run = gap * 2
        slack = {"left": 0.0, "centre": (width - run) / 2, "right": width - run - r}
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
        """One wheel notch offered to the renderer first; True means taken.
        Default declines."""
        return False

    # ----------------------------------------------------------- the credits
    def credits_index(self):
        """Which line is the credit block, found rather than assumed, or None."""
        for i in range(len(self.v.lines) - 1, -1, -1):
            if self.v.lines[i].get("credits"):
                return i
        return None

    def credits_block(self, p, x0: float, width: float, top: float,
                      H: int = 0, fade: float = 1.0,
                      align: str = "centre") -> float:
        """The credit block drawn with its top at `top`, held inside `H`,
        centred; returns its height."""
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
        """The footer under the last line, dim and still; songwriters brighter,
        `links` underlined over the same row and recorded for credit_at."""
        align = {"centre": Qt.AlignmentFlag.AlignHCenter,
                 "right": Qt.AlignmentFlag.AlignRight}.get(
                     align or self.v.align, Qt.AlignmentFlag.AlignLeft)
        if fade <= 0.01:
            return
        font = self.v.credit_font()
        step = fm.height() * 1.4
        at = getattr(self.v, "mouse_pos", None)
        lit = set()
        t = p.transform()
        for part, n, cut, url, box in self._credit_links(rows, fm, x0, y,
                                                         width, links, align):
            box = t.mapRect(box)        # the painter is scrolled; the mouse is not
            self.v.credit_hot.append((box, url))
            if at is not None and box.contains(at):
                lit.add((n, cut))
        dpr = self.v.devicePixelRatioF() or 1.0
        shift = (t.type().value
                 <= QTransform.TransformationType.TxTranslate.value)
        dev = (y + (t.dy() if shift else 0.0)) * dpr
        if shift and abs(dev - round(dev)) < 0.02:
            self._credit_ink(p, rows, fm, font, x0, y, width, links, fade,
                             align, lit)
            return
        self._credits_picture(p, rows, fm, font, x0, y, width, links, fade,
                              align, lit, step, dpr)

    def _credit_links(self, rows, fm, x0: float, y: float, width: float,
                      links, align):
        """Where each clickable stretch of the credits lands:
        (credit, row, text, url, box), the box the ink plus a little."""
        step = fm.height() * 1.4
        ry = y + step
        for n, (part, row) in enumerate(rows):
            for text, url, cut in self._link_cuts(row, links, part):
                lx = (self._credit_left(fm, row, x0, width, align)
                      + fm.horizontalAdvance(row[:cut]))
                yield (part, n, cut, url,
                       QRectF(lx - 3, ry, fm.horizontalAdvance(text) + 6, step))
            ry += step

    @staticmethod
    def _link_cuts(row: str, links, part: int):
        """(text, url, where) for each link in `row`; a name linked twice
        ("by Gary · approved by Gary") takes its next appearance each time."""
        after = {}
        for text, url in (links[part] if part < len(links) else ()):
            cut = whole_find(row, text, after.get(text, 0)) if text else -1
            if cut < 0 or not url:
                continue
            after[text] = cut + len(text)
            yield text, url, cut

    @staticmethod
    def _credit_left(fm, row: str, x0: float, width: float, align) -> float:
        run = fm.horizontalAdvance(row)
        return (x0 if align == Qt.AlignmentFlag.AlignLeft else
                x0 + (width - run) / 2
                if align == Qt.AlignmentFlag.AlignHCenter
                else x0 + width - run)

    def _credit_ink(self, p, rows, fm, font, x0: float, y: float,
                    width: float, links, fade: float, align, lit) -> None:
        """The credit block's text, links and faces, drawn with its top at
        `y`. `lit` holds the (row, where) of the link under the pointer."""
        p.save()
        p.setFont(font)
        under = QFont(font)
        under.setUnderline(True)
        step = fm.height() * 1.4
        ry = y + step
        for n, (part, row) in enumerate(rows):
            dim = int((120 if part == 0 else 88) * fade)
            p.setPen(QColor(234, 234, 234, dim))
            p.drawText(QRectF(x0, ry, width, step),
                       int(align | Qt.AlignmentFlag.AlignVCenter), row)
            left = self._credit_left(fm, row, x0, width, align)
            for text, url, cut in self._link_cuts(row, links, part):
                lx = left + fm.horizontalAdvance(row[:cut])
                lw = fm.horizontalAdvance(text)
                p.setFont(under)
                p.setPen(QColor(234, 234, 234,
                                min(255, dim + (95 if (n, cut) in lit
                                                else 45))))
                p.drawText(QRectF(lx, ry, lw + 2, step),
                           int(Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignVCenter), text)
                p.setFont(font)
            for name, url in getattr(self.v, "credit_faces", ()):
                cut = whole_find(row, name + FACE_GAP)
                face = self.v.credit_face(url) if cut >= 0 else None
                if face is None:
                    continue
                gx = left + fm.horizontalAdvance(row[:cut + len(name)])
                gw = fm.horizontalAdvance(FACE_GAP)
                d = min(fm.height() * 0.95, gw * 0.8)
                p.setOpacity(0.85 * fade)
                blit(p, QRectF(gx + (gw - d) / 2, ry + (step - d) / 2, d, d),
                     face, QRectF(face.rect()))
                p.setOpacity(1.0)
            ry += step
        p.restore()

    def _credits_picture(self, p, rows, fm, font, x0: float, y: float,
                         width: float, links, fade: float, align, lit,
                         step: float, dpr: float) -> None:
        """The credit block as one kept picture placed at its fractional
        height; at rest it is plain text again."""
        m = 4
        left = math.floor(x0 * dpr) / dpr - m
        faces = []
        for name, url in getattr(self.v, "credit_faces", ()):
            face = self.v.faces.get(url) if hasattr(self.v, "faces") else None
            faces.append((name, url, face.cacheKey()
                          if hasattr(face, "cacheKey") else None))
        key = (tuple(rows), tuple(tuple(tuple(k) for k in l) for l in links),
               font.key(), fm.height(), x0 - left, width, round(fade, 3),
               int(align.value) if hasattr(align, "value") else int(align),
               frozenset(lit), tuple(faces), dpr)
        got = getattr(self, "_credit_pic", None)
        if got is not None and got[0] == key:
            pm = got[1]
        else:
            pw = int(math.ceil((width + 2 * m + 8) * dpr)) + 2
            ph = int(math.ceil((step * (len(rows) + 1) + 2 * m) * dpr)) + 2
            pm = QPixmap(max(1, pw), max(1, ph))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHints(p.renderHints())
            try:
                self._credit_ink(q, rows, fm, font, x0 - left, m, width,
                                 links, fade, align, lit)
            finally:
                q.end()
            self._credit_pic = (key, pm)
        blit(p, QPointF(left, y - m), pm)


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
                  bg: bool = False, font: QFont | None = None,
                  fade: float = 1.0) -> dict:
        """Which words of this line are held and how they move: empty for the
        stack (see Amll.emph_plan)."""
        return {}

    def left_hold(self, idx: int, ln: dict, rows, fm: QFontMetricsF,
                  pos: float, live) -> tuple:
        """(hold, sink) for a line the voice has left -- (0, 0) here, where
        nothing outlasts its line. See Amll.left_hold."""
        return 0.0, 0.0

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
        """Every line's place down the column, worked out once per document and
        kept in the window's layout cache; offsets relative to the column
        top and x0."""
        v = self.v
        key = ("flowplan", int(width), int(v.lyric_px()), v.align, v.roman,
               v.furigana, v.periodic, v.line_spacing)
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
        """line_rects in content space, rebuilt only when the anchor or x0
        move."""
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
        """On a frame with ration to spare, build the blur pictures the next
        line switch will want, only for lines that will land inside the
        window."""
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
        scale = _blur(v) * (1.0 - v.browse)
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
                              v.glow_colour(ln))
        self._warm_done = v._pix_left > 0 or v._pix_left == had

    def spin_frag(self, rows, fm, ox: float, y: float, ruh: float, pos: float,
                  ruby=()):
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
                lead = self.v.ruby_lead(ruh, ruby)
                ry = y + lead + fm.ascent() + r_i * (fm.height() * 1.06 + ruh)
                box = QRectF(ox + x - 2, ry - fm.ascent() - lead - 2,
                             w + 4, fm.height() + ruh + 4)
                return (r_i, x, box)
        return None

    def float_span(self) -> float:
        """How long one flight lasts, from letting go to gone."""
        return 1.0 / max(0.25, self.v.float_up)

    def float_of(self, at, pos: float):
        """(lift, opacity left, scale) of a word that set off at `at`, or None
        if not reached; driven by the song clock."""
        if at is None or pos <= at:
            return None
        t = min(1.0, (pos - at) / self.float_span())
        unit = self.v.lyric_fm(False).height()
        return (unit * 9.0 * t ** 1.6, 1.0 - _smooth(t), 1.0 + 1.5 * t ** 1.6)

    DOT_STAGGER = 0.34

    def dot_flights(self, ln, pos: float):
        """Where each of an interlude's three dots has got to, or None: they
        leave one after another at the end of the break."""
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
        """Every fragment already on its way out, keyed (romaji?, row, index):
        one flight per syllable, leaving as it is sung."""
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
        """(blur radius, strength) of a word's halo: radius by drawn width in
        line-heights, a little brightness, both scaled by `held`."""
        span = adv(fm, core) / max(1.0, fm.height())
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

    def roman_reads(self, p, ln, row, rruby, rr_i: int, ox: float, gy: float,
                    rfm, rruh: float, rrufm, gone: dict, alpha: float,
                    fill=None) -> None:
        """The periodic readings of one romanisation row; with `fill`
        ((sweep, sung, clear, pos)) only their sung part, as the fill does."""
        marks = rruby[rr_i]
        p.setFont(self.v.roman_ruby_font(ln))
        by = self.on_grid(self.v.ruby_base(gy, rfm, rruh, rrufm, rruby))
        for cx, read, s, e in marks:
            at = self.v.ruby_anchor(cx, read, rrufm, rruby)
            flew, left, big = gone.get((True, rr_i, self.frag_under(row, at)),
                                       STAYING)
            fade = alpha if left is None else alpha * left
            if fade <= 0.01:
                continue
            rw = adv(rrufm, read)
            rx = ox + cx - rw / 2
            if fill is not None:
                sweep, sung, clear, pos = fill
                if s is None or e is None:
                    continue
                frac = 1.0 if pos >= e else (
                    0.0 if pos <= s else (pos - s) / max(1e-6, e - s))
                if not self.fill_shows(sweep, rx, rw, frac, rrufm):
                    continue
                p.setPen(self.fill_pen(sweep, sung, clear, rx, rw, frac, rrufm))
            p.setOpacity(fade)
            self.lifted_word(p, QPointF(rx, by), read, flew, rrufm, big,
                             ox + cx, by - rrufm.ascent() * 0.35 - flew)
        p.setOpacity(alpha)

    def word_lifts(self, rows, fm: QFontMetricsF, pos: float, act: float,
                   blur: float, bg: bool = False) -> dict:
        """How far each fragment has been lifted, keyed (row, index): one lift
        per syllable on rise_plan. See renderers.md, "the rise schedule"."""
        if self.v.rise <= 0 or act <= 0.01 or blur >= 1.0:
            return {}
        unit = self.v.lyric_fm(False).height()
        full = unit * 0.055 * self.v.rise * act * (1.0 - blur)
        rows_lifts = self.frag_lifts(rows, full, pos)
        return {(r_i, f_i): lift
                for r_i, d in enumerate(rows_lifts) for f_i, lift in d.items()}

    def sung_edge(self, row, pos: float) -> float | None:
        """How far along a row the voice has got, in line-local pixels: the end
        of the run of reached fragments from the row's start; None if not
        reached."""
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

    def glow_lifts(self, rows, ox: float, lifted: dict, emphs: dict,
                   font: QFont, fm: QFontMetricsF) -> list:
        """(row, x0, x1, dy, dx) stretches for all_glow, alike neighbours
        merged; spread gaps bridged by _glow_bridged."""
        out = []
        for r_i, row in enumerate(rows):
            cur = None
            for f_i, frag in enumerate(row):
                lift = lifted.get((r_i, f_i), 0.0)
                x = ox + frag[0]
                em = emphs.get((r_i, f_i))
                units = (self.shaped_units(frag[2].strip(), font, fm)
                         if em is not None and em.parts else ())
                if units and len(units) == len(em.parts):
                    edges = [x + ux for _u, ux in units] + [x + frag[1]]
                    dxs = [c[1] - (edges[k] - x) for k, c in enumerate(em.parts)]
                    ups = [lift + c[2] for c in em.parts]
                    bits = (self._glow_bridged(edges, dxs, ups)
                            if any(u >= 0.25 or abs(d) >= 0.25
                                   for u, d in zip(ups, dxs)) else [])
                else:
                    up = (sum(c[2] for c in em.parts) / len(em.parts)
                          if em is not None and em.parts else 0.0)
                    bits = [(x, x + frag[1], lift + up, 0.0)]
                    if lift + up < 0.25:
                        bits = []
                if not bits:
                    if cur is not None:
                        out.append(cur)
                        cur = None
                    continue
                # Joined on the screen's own edges, then handed back in the
                # picture's: (row, x0, x1, dy, dx), drawn at x0 + dx.
                for s0, s1, dy, dx in bits:
                    if (cur is not None and abs(cur[3] - dy) < 0.25
                            and abs(cur[4] - dx) < 0.25):
                        cur = (r_i, cur[1], s1, cur[3], cur[4])
                    else:
                        if cur is not None:
                            out.append(cur)
                        cur = (r_i, s0, s1, dy, dx)
            if cur is not None:
                out.append(cur)
        return [(r, s0 - dx, s1 - dx, dy, dx) for r, s0, s1, dy, dx in out]

    @staticmethod
    def _glow_bridged(edges: list, dxs: list, ups: list) -> list:
        """(s0, s1, dy, dx) screen spans for a held word's letters, tiling it:
        each letter's own columns, and every gap the spread opens filled with
        the light that sat between those two letters at rest."""
        n = len(dxs)
        lo = [edges[k] + dxs[k] for k in range(n)]
        hi = [edges[k + 1] + dxs[k] for k in range(n)]
        out = []
        for k in range(n):
            s0, s1 = lo[k], hi[k]
            if k and lo[k] < hi[k - 1]:            # squeezed: meet halfway
                s0 = (lo[k] + hi[k - 1]) * 0.5
            if k + 1 < n and lo[k + 1] < hi[k]:
                s1 = (lo[k + 1] + hi[k]) * 0.5
            out.append((s0, s1, ups[k], dxs[k]))
            if k + 1 < n and lo[k + 1] > hi[k]:
                gap = lo[k + 1] - hi[k]
                m = min(4, math.ceil(gap))
                w = gap / m
                for j in range(m):
                    a = hi[k] + j * w
                    t = (j + 0.5) / m
                    out.append((a, a + w, ups[k] + (ups[k + 1] - ups[k]) * t,
                                a - (edges[k + 1] - w * 0.5)))
        return out

    def all_glow(self, p, idx: int, ln: dict, rows, fm: QFontMetricsF,
                 ox: float, y: float, width: float, lo: int, act: float,
                 ruh: float, pos: float, rrows, gone: dict, spin,
                 lifts=()) -> None:
        """A halo behind every word already sung, in the line's colour at full
        brightness, added (Plus), from the line's own blurred pixmap."""
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
        pm = v.line_pixmap(idx, width, level, v.glow_colour(ln))
        if pm is None:
            return
        pad = _pad_of(pm, width)
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
            rpitch = rfm.height() * 1.04 + self.v.roman_band(rrows)[0]
            rlit = [self.sung_edge(row, pos) for row in rrows]
            rlast = max((i for i, e in enumerate(rlit) if e is not None),
                        default=-1)
            rtop = pad + len(rows) * pitch
            for r_i, edge in enumerate(rlit):
                top = rtop + (fm.height() * 0.10 if r_i else 0.0) + r_i * rpitch
                bot = (rtop + fm.height() * 0.10 + (r_i + 1) * rpitch
                       if r_i < len(rrows) - 1 else float(H))
                bands.append((rrows[r_i], edge, top, bot, r_i < rlast))
        def strips() -> list:
            acc: list = []
            for row, edge, top, bot, behind in bands:
                if edge is None:
                    continue
                if behind:
                    self._glow_strip(p, at, pm, 0.0, float(pm.width()), top,
                                     bot, past, acc)
                    continue
                if row_rtl(row):
                    self._glow_strip(p, at, pm, pad + edge + trail,
                                     float(pm.width()), top, bot, past, acc)
                    self._glow_ramp(p, at, pm, pad + edge + soft,
                                    pad + edge + trail, top, bot, full, past,
                                    self.TRAIL_STEPS, acc)
                    self._glow_ramp(p, at, pm, pad + edge - soft,
                                    pad + edge + soft, top, bot, 0.0, full,
                                    max(1, int(soft)), acc)
                    continue
                self._glow_strip(p, at, pm, 0.0, pad + edge - trail, top, bot,
                                 past, acc)
                self._glow_ramp(p, at, pm, pad + edge - trail, pad + edge - soft,
                                top, bot, past, full, self.TRAIL_STEPS, acc)
                self._glow_ramp(p, at, pm, pad + edge - soft, pad + edge + soft,
                                top, bot, full, 0.0, max(1, int(soft)), acc)
            return acc

        def draw() -> None:
            self._glow_flush(p, at, pm, strips())

        def near(clip, dy, dx) -> tuple:
            # The clip in the picture's pixels, under the lift's translate,
            # with room for the aligned rect's and the nudge's rounding.
            m = 3.0
            return (clip.left() - dx - at.x() - m,
                    clip.right() + 1 - dx - at.x() + m,
                    clip.top() + dy - at.y() - m,
                    clip.bottom() + 1 + dy - at.y() + m)

        # `lifts` (row, x0, x1, dy, dx) are stretches standing off the row:
        # each is drawn again at its own dy and cut out of the plain pass, held
        # words included.
        if not lifts:
            draw()
        else:
            def span(r_i, x0, x1, dy):
                # Sides on whole pixels, so neighbouring passes abut: aligned
                # outwards, they shared a column and it was lit twice.
                band = bands[min(r_i, len(bands) - 1)]
                reach = dy + 2.0
                return QRectF(round(x0), at.y() + band[2] - reach,
                              round(x1) - round(x0), band[3] - band[2] + reach)
            keep = QRegion(-100000, -100000, 200000, 200000)
            for r_i, x0, x1, dy, dx in lifts:
                keep -= QRegion(span(r_i, x0, x1, dy).toAlignedRect())
                keep -= QRegion(span(r_i, x0 + dx, x1 + dx, dy).toAlignedRect())
            every = strips()
            def strips_near(nr) -> list:
                # Those a lifted pass's clip lets through, `nr` from near():
                # built once, since a held word is a dozen passes.
                return [s for s in every if s[0] < nr[1] and s[1] > nr[0]
                        and s[2] < nr[3] and s[3] > nr[2]]
            p.save()
            p.setClipRegion(keep)
            self._glow_flush(p, at, pm, every)
            p.restore()
            gl = None if p.hasClipping() else self._glow_gl(p, pm)
            if gl is None:
                for r_i, x0, x1, dy, dx in lifts:
                    clip = span(r_i, x0 + dx, x1 + dx, dy).toAlignedRect()
                    p.save()
                    p.setClipRect(clip)
                    p.translate(dx, -dy)
                    self._glow_flush(p, at, pm, strips_near(near(clip, dy, dx)))
                    p.restore()
            else:
                # One drawPixmapFragments for every lifted pass, each cut by
                # hand to the scissor its clip rect would have set (Qt 6.11's
                # GL engine rounds each mapped edge; probed 300/300). The
                # passes' own save/clip/translate/flush were ~0.3ms a frame.
                t = p.transform()
                frags: list = []
                for r_i, x0, x1, dy, dx in lifts:
                    clip = span(r_i, x0 + dx, x1 + dx, dy).toAlignedRect()
                    c = t.mapRect(QRectF(clip))
                    cut = (round(c.left()), round(c.left() + c.width()),
                           round(c.top()), round(c.top() + c.height()))
                    self._glow_frags(frags, QTransform.fromTranslate(dx, -dy) * t,
                                     gl[0], at, strips_near(near(clip, dy, dx)),
                                     cut, dx, -dy / gl[0])
                self._glow_draw(p, pm, frags, gl[1])
        p.restore()

    def _glow_ramp(self, p, at: QPointF, pm: QPixmap, x0: float, x1: float,
                   top: float, bot: float, a0: float, a1: float,
                   steps: int, out: list | None = None) -> None:
        """The glow across `x0`..`x1`, stepped from opacity `a0` to `a1` in
        clipped blits."""
        if x1 <= x0:
            return
        step = (x1 - x0) / steps
        for i in range(steps):
            self._glow_strip(p, at, pm, x0 + i * step, x0 + (i + 1) * step,
                             top, bot, a0 + (a1 - a0) * (i + 0.5) / steps, out)

    @staticmethod
    def _glow_flush(p, at: QPointF, pm: QPixmap, strips: list) -> None:
        """`strips` from _glow_strip, drawn. On the GL engine under a shift or
        a plain scale they go as one drawPixmapFragments, each cut to the
        device pixels its clip would have let through (within 1/255 of the
        clipped blits); elsewhere one clipped blit each."""
        gl = Flow._glow_gl(p, pm)
        if gl is None:
            for s in strips:
                Flow._glow_strip(p, at, pm, *s)
            return
        frags: list = []
        Flow._glow_frags(frags, p.transform(), gl[0], at, strips)
        Flow._glow_draw(p, pm, frags, gl[1])

    @staticmethod
    def _glow_gl(p, pm: QPixmap):
        """(nudge, transform) where glow strips can go as fragments: the GL
        engine under a shift or a plain scale at dpr 1; else None."""
        eng = p.paintEngine()
        t = p.transform()
        typ = t.type()
        if typ in _SHIFTS:
            nud, nt = NUDGE, _NUDGE_T * t           # as blit puts it
        elif typ == _TX_SCALE and t.m11() > 0 and t.m22() > 0:
            nud, nt = 1.0, t
        else:
            return None
        if (not GLOW_FRAGMENTS or eng is None
                or eng.type() != QPaintEngine.Type.OpenGL2
                or abs(pm.devicePixelRatio() - 1.0) > 1e-6
                or abs(p.device().devicePixelRatioF() - 1.0) > 1e-6):
            return None
        return nud, nt

    @staticmethod
    def _glow_frags(frags: list, t: QTransform, nud: float, at: QPointF,
                    strips: list, cut=None, mx: float = 0.0,
                    my: float = 0.0) -> None:
        """Append `strips` as fragments under `t`, each cut to the device
        pixels its clip would have let through, and to `cut` (left, right,
        top, bottom device pixels) if given; placed `mx`, `my` over from where
        `t` has them, for drawing under a transform without that shift."""
        # Plain floats, in mapRect's own order: Qt rects cost ~8us a strip.
        sx, sy, dx, dy = t.m11(), t.m22(), t.dx(), t.dy()
        ax, ay = at.x(), at.y()
        make = QPainter.PixmapFragment.create
        for x0, x1, top, bot, opacity in strips:
            # The scissor a clip would have set: each edge rounded.
            lx, uy = sx * (ax + x0) + dx, sy * (ay + top) + dy
            left, right = round(lx), round(lx + sx * (x1 - x0))
            up, down = round(uy), round(uy + sy * (bot - top))
            if cut is not None:
                left, right = max(left, cut[0]), min(right, cut[1])
                up, down = max(up, cut[2]), min(down, cut[3])
            if right <= left or down <= up:
                continue
            ux0, ux1 = (left - dx) / sx, (right - dx) / sx
            uy0, uy1 = (up - dy) / sy / nud, (down - dy) / sy / nud
            frags.append(make(
                QPointF((ux0 + ux1) * 0.5 + mx, (uy0 + uy1) * 0.5 + my),
                QRectF(ux0 - ax, uy0 - ay, ux1 - ux0, uy1 - uy0),
                1.0, 1.0, 0.0, opacity))

    @staticmethod
    def _glow_draw(p, pm: QPixmap, frags: list, nt: QTransform) -> None:
        """`frags` from _glow_frags, in one call under `nt`."""
        if not frags:
            return
        p.save()
        p.setOpacity(1.0)
        p.setRenderHint(_SMOOTH)
        p.setTransform(nt)
        p.drawPixmapFragments(frags, pm)
        p.restore()

    @staticmethod
    def _glow_strip(p, at: QPointF, pm: QPixmap, x0: float, x1: float,
                    top: float, bot: float, opacity: float,
                    out: list | None = None) -> None:
        """One horizontal slice of the glow, clipped (not cropped) out of the
        cached picture; `at` is the picture's corner."""
        if opacity <= 0.004 or x1 <= x0 or bot <= top:
            return
        if out is not None:
            out.append((x0, x1, top, bot, opacity))
            return
        p.save()
        p.setClipRect(QRectF(at.x() + x0, at.y() + top, x1 - x0, bot - top),
                      Qt.ClipOperation.IntersectClip)
        p.setOpacity(opacity)
        blit(p, at, pm)
        p.restore()

    def draw_base(self, p, ln, rows, fm: QFontMetricsF, ox: float, y: float,
                  alpha: float, lifted: dict, rrows, rfm, ruby, rufm,
                  spin, gone: dict, emphs: dict | None = None,
                  pos: float | None = None, act: float = 0.0) -> None:
        """The line's unsung text drawn live (the line being sung, with lifted
        words); words in `gone` at their height and opacity."""
        emphs = emphs or {}
        p.save()
        p.setPen(self.v.base_colour(ln))
        p.setOpacity(alpha)
        font = self.v.lyric_font(ln["background"])
        ruh = self.v.ruby_h(rufm)
        rufont = self.v.ruby_font(ln) if rufm is not None else None
        lead = self.v.ruby_lead(ruh, ruby)
        ry = y + lead + fm.ascent()
        for r_i, row in enumerate(rows):
            gy = self.on_grid(ry)
            if rufont is not None and r_i < len(ruby):
                p.setFont(rufont)
                by = self.on_grid(self.v.ruby_base(gy, fm, ruh, rufm, ruby))
                for cx, read, _s, _e in ruby[r_i]:
                    at = self.v.ruby_anchor(cx, read, rufm, ruby)
                    flew, left, big = gone.get(
                        (False, r_i, self.frag_under(row, at)), STAYING)
                    if left is not None and left <= 0.01:
                        continue
                    p.setOpacity(alpha if left is None else alpha * left)
                    lift = self.ruby_lift(row, lifted, r_i, at) + flew
                    self.lifted_word(
                        p, QPointF(ox + cx - adv(rufm, read) / 2, by),
                        read, lift, rufm, big,
                        ox + cx, by - rufm.ascent() * 0.35 - lift)
                p.setOpacity(alpha)
            p.setFont(font)
            for f_i, (x, w, txt, s, e) in enumerate(row):
                if spin is not None and (r_i, x) == (spin[0], spin[1]):
                    continue
                flew, left, big = gone.get((False, r_i, f_i), STAYING)
                if left is not None:
                    if left <= 0.01:
                        continue
                    p.setOpacity(alpha * left)
                grow, poplift = ((1.0, 0.0) if pos is None else
                                 self.pop_of(s, e, pos, act, fm))
                lift = lifted.get((r_i, f_i), 0.0) + flew + poplift
                self.place_word(p, QPointF(ox + x, gy), txt, lift, fm,
                                big * grow,
                                ox + x + w * 0.5,
                                gy - fm.ascent() * 0.35 - lift,
                                emphs.get((r_i, f_i)))
                if left is not None:
                    p.setOpacity(alpha)
            ry += fm.height() * 1.06 + ruh
        if rrows and rfm is not None:
            rfont = self.v.roman_font(ln)
            p.setFont(rfont)
            rruh, rruby, rrufm = self.v.roman_band(rrows)
            ry += (fm.height() * 0.10 - fm.ascent() - lead + rfm.ascent()
                   + self.v.ruby_lead(rruh, rruby))
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
                if rr_i < len(rruby):
                    self.roman_reads(p, ln, row, rruby, rr_i, ox, ry,
                                     rfm, rruh, rrufm, gone, alpha)
                    p.setFont(rfont)
                ry += rfm.height() * 1.04 + rruh
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
        """Drift state for one whole line, its path from a hash of the key."""
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
        """Every word adrift in its own cloud; no depth blur or furigana."""
        now = mono()
        W, H = self.v.width(), self.v.height()
        k = max(0.25, self.v.clouds)
        font = self.v.lyric_font(ln["background"])
        p.setFont(font)
        p.setOpacity(1.0)
        sung = self.v.sung_colour(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ruh = self.v.ruby_h(rufm)
        rowh = fm.height() * 1.06 + ruh
        puff = self.cloud_pixmap()

        lead = self.v.ruby_lead(ruh, ruby)
        blocks = [(rows, fm, y + lead + fm.ascent(), rowh, font, False)]
        if rrows and rfm is not None:
            rruh, rruby, _rrufm = self.v.roman_band(rrows)
            ry0 = (y + lead + fm.ascent() + len(rows) * rowh
                   + fm.height() * 0.10 - fm.ascent() - lead + rfm.ascent()
                   + self.v.ruby_lead(rruh, rruby))
            blocks.append((rrows, rfm, ry0, rfm.height() * 1.04 + rruh,
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
                    self.grad_text(p, QPointF(px, py), txt)
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
                        self.grad_text(p, QPointF(px, py), txt)
        if len(self.v.cloudy) > 400:
            cut = now - 4.0
            for key in [k2 for k2, v in self.v.cloudy.items() if v[6] < cut]:
                self.v.cloudy.pop(key, None)

    def _paint_loose(self, p, idx, ln, rows, fm, ox, y, pos, act, alpha,
                     rrows=(), rfm=None, ruby=(), rufm=None) -> None:
        """One line with every word cut loose, at rest plus physics offset; no
        depth blur or ruby, layout untouched."""
        font = self.v.lyric_font(ln["background"])
        p.setFont(font)
        p.setOpacity(1.0)
        sung = self.v.sung_colour(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        ruh = self.v.ruby_h(rufm)
        rowh = fm.height() * 1.06 + ruh

        lead = self.v.ruby_lead(ruh, ruby)
        blocks = [(rows, fm, y + lead + fm.ascent(), rowh, font, False)]
        if rrows and rfm is not None:
            rruh, rruby, _rrufm = self.v.roman_band(rrows)
            ry = (y + lead + fm.ascent() + len(rows) * rowh
                  + fm.height() * 0.10 - fm.ascent() - lead + rfm.ascent()
                  + self.v.ruby_lead(rruh, rruby))
            blocks.append((rrows, rfm, ry, rfm.height() * 1.04 + rruh,
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
                    self.grad_text(p, QPointF(px, py), txt)
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
                        self.grad_text(p, QPointF(px, py), txt)
                    p.restore()

    def focus_trim(self, dist: int):
        """What focus mode does to a line `dist` from the sung one: (hush,
        mute), or None to drop it; a hard edge, fine in a scrolling column."""
        edge = self.v.focus + 1
        if dist > edge:
            return None
        return (0.35, True) if dist == edge else (1.0, False)

    # Whether a line between two rows of pixels is drawn there whole -- see
    # _paint_line_at. Only the renderer that moves its lines on springs.
    GLIDE = False

    def _paint_line(self, p, *args, **kw) -> None:
        """_paint_line_at, with the painter put back as it was found -- the
        glide leaves a translation on it that no return path may leak."""
        p.save()
        try:
            self._paint_line_at(p, *args, **kw)
        finally:
            p.restore()

    def _paint_line_at(self, p, idx, ln, rows, fm, x0, y, pos, live, rrows=(),
                       rfm=None, ruby=(), rufm=None) -> None:
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
                pad = _pad_of(flat, width)
                p.setOpacity(0.82)
                blit(p, QPointF(ox - pad, y - pad), flat)
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
        blur *= (1.0 - act) * _blur(self.v) * (1.0 - self.v.browse)
        # A held word still moving after its line (Amll.left_hold) keeps the
        # line sharp -- a blurred line is one still picture -- and its float
        # coming down at `sink` rather than with the activation's 60ms.
        hold, sink = self.left_hold(idx, ln, rows, fm, pos, live)
        blur *= 1.0 - hold
        falloff = max(0.10, 0.32 - 0.055 * max(0, dist - 1))
        falloff *= hush
        falloff += (0.60 - falloff) * self.v.browse if falloff < 0.60 else 0.0
        alpha = (falloff + 0.14 * act) * (0.8 if ln["background"] else 1.0)
        if idx == self.v.hover_idx:
            alpha = min(1.0, alpha + 0.22)
        alpha_free = alpha
        alpha *= self.v.vfade(y + fm.height() * 0.5)
        y = y + (1.0 - act) * 7.0 * self.v.line_drop * (1 if idx in live else 0)

        # A moving line is drawn at the pixel and the painter carries the
        # fraction, so text, glow and lifted pictures move together; at rest
        # the springs land on a whole pixel.
        if self.GLIDE:
            snapped = self.on_grid(y)
            if abs(y - snapped) > 0.02:
                p.translate(0.0, y - snapped)
                y = snapped

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
        spin = self.spin_frag(rows, fm, ox, y, self.v.ruby_h(rufm), pos,
                              ruby)
        floats = max(act, sink)
        lifted = self.word_lifts(rows, fm, pos, floats, blur, ln["background"])
        # Faded out with the line rather than dropped; a line held for its word
        # is not faded, so the word runs to rest.
        stays = max(act, hold)
        emphs = (self.emph_plan(rows, pos, fm, ln["background"],
                                fade=min(1.0, stays * (1.0 - blur)))
                 if stays > 0.01 and blur < 1.0 else {})
        popping = (act > 0.01 and any(
            self.pop_of(f[3], f[4], pos, act, fm)[0] > 1.0
            for row in rows for f in row))
        own_text = ((self.v.rise > 0 and floats > 0.01 and blur < 1.0)
                    or bool(gone) or bool(emphs) or popping)
        glow_lifts = (self.glow_lifts(rows, ox, lifted, emphs,
                                      self.v.lyric_font(ln["background"]), fm)
                      if self.v.word_glow > 0 else [])
        self.all_glow(p, idx, ln, rows, fm, ox, y, width, lo, act,
                      self.v.ruby_h(rufm), pos, rrows, gone, spin, glow_lifts)
        p.save()
        if own_text:
            self.draw_base(p, ln, rows, fm, ox, y, alpha, lifted,
                           rrows, rfm, ruby, rufm, spin, gone, emphs,
                           pos, act)
        else:
            if spin is not None:
                p.setClipRegion(QRegion(self.v.rect())
                                - QRegion(spin[-1].toAlignedRect()))
            p.setOpacity(alpha * (1.0 - frac_b))
            flat = self.v.line_pixmap(idx, width, lo)
            if flat is not None:
                pad = _pad_of(flat, width)
                blit(p, QPointF(ox - pad, y - pad), flat)
            if frac_b > 0.01:
                over = self.v.line_pixmap(idx, width, lo + 1)
                if over is not None:
                    pad = _pad_of(over, width)
                    p.setOpacity(alpha * frac_b)
                    blit(p, QPointF(ox - pad, y - pad), over)
        p.restore()
        p.setOpacity(1.0)

        if act <= 0.01 and not gone:
            return
        p.save()
        font = self.v.lyric_font(ln["background"])
        p.setFont(font)
        sung = self.v.sung_colour(ln)
        clear = QColor(sung.red(), sung.green(), sung.blue(), 0)
        now = mono()
        ruh = self.v.ruby_h(rufm)
        rufont = self.v.ruby_font(ln) if rufm is not None else None
        lead = self.v.ruby_lead(ruh, ruby)
        ry = y + lead + fm.ascent()
        for r_i, row in enumerate(rows):
            gy = self.on_grid(ry)
            sweep = self.sweep_of(row, ox, pos, fm)
            rtl = row_rtl(row)
            if rufont is not None and r_i < len(ruby):
                p.setFont(rufont)
                by = self.on_grid(self.v.ruby_base(gy, fm, ruh, rufm, ruby))
                for cx, read, s, e in ruby[r_i]:
                    if s is None or e is None:
                        continue
                    at = self.v.ruby_anchor(cx, read, rufm, ruby)
                    flew, left, big = gone.get(
                        (False, r_i, self.frag_under(row, at)), STAYING)
                    fade = act if left is None else left
                    if fade <= 0.01:
                        continue
                    rw = adv(rufm, read)
                    rx = ox + cx - rw / 2
                    frac = 1.0 if pos >= e else (
                        0.0 if pos <= s else (pos - s) / max(1e-6, e - s))
                    f_i = self.frag_under(row, at)
                    if f_i is not None and 0.0 < frac < 1.0:
                        fx, fw = row[f_i][0], row[f_i][1]
                        edge = ox + fx + fw * frac
                        frac = max(0.0, min(1.0, (edge - rx) / max(1e-6, rw)))
                    if not self.fill_shows(sweep, rx, rw, frac, rufm):
                        continue
                    p.setPen(self.fill_pen(sweep, sung, clear, rx, rw, frac, rufm))
                    p.setOpacity(fade)
                    lift = self.ruby_lift(row, lifted, r_i, at) + flew
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
                popgrow, poplift = self.pop_of(s, e, pos, act, fm)
                self.long_glow(p, txt, font, fm, QPointF(px, gy), s, e, pos,
                               act, rise + poplift, popgrow * big, fade, ln)
                emph = emphs.get((r_i, f_i))
                if emph is not None:
                    # The fill edge travels with the letters, by each letter's
                    # own shift.
                    ed = self.fill_edge(sweep, px, w, frac, rtl)
                    soft = self._fade(fm)
                    shifts = self.emph_shifts(emph, txt, font, fm)

                    def pen_at(i, ed=ed, shifts=shifts, soft=soft):
                        if ed is None:
                            return sung
                        if ed == float("-inf"):
                            return clear
                        return sung_grad(ed + shifts[i], soft, sung, clear, rtl)

                    # The light first, the letters over it: see emph_glow.
                    tint = (self.v.glow_colour(ln)
                            if hasattr(self.v, "glow_colour") else None)
                    self.emph_glow(p, emph, QPointF(px, gy), font, fm,
                                   rise + poplift, fade, ed, soft, shifts,
                                   tint)
                    p.save()
                    wcx, wcy = px + w * 0.5, gy - fm.ascent() * 0.35
                    p.setOpacity(fade)
                    self.place_word(p, QPointF(px, gy), txt, rise + poplift,
                                    fm, big * popgrow, wcx,
                                    wcy - rise - poplift, emph, pen_at)
                    p.restore()
                    continue
                held = min(1.0, max(0.0, (e - s - 0.18) / 1.1))
                if self.HALO and self.v.glow_scale > 0 and singing and held > 0.02:
                    core = txt.strip()
                    radius, strength = self.glow_of(core, fm, held)
                    gp = self._glow_in(self.v.glow_pixmap(core, font, radius), ln)
                    swell = math.sin(math.pi * frac) ** 0.7
                    shimmer = 0.86 + 0.14 * math.sin(now * 6.5 + s * 4.0)
                    grow = (1.0 + 0.38 * swell * strength) * big
                    gw, gh = gp.width(), gp.height()
                    pad = radius * 3
                    ccx = (px + adv(fm, txt[:len(txt) - len(txt.lstrip())])
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
                grow = popgrow * big
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
            rruh, rruby, rrufm = self.v.roman_band(rrows)
            ry += (fm.height() * 0.10 - fm.ascent() - lead + rfm.ascent()
                   + self.v.ruby_lead(rruh, rruby))
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
                if rr_i < len(rruby):
                    self.roman_reads(p, ln, row, rruby, rr_i, ox, ry,
                                     rfm, rruh, rrufm, gone, act,
                                     (rsweep, sung, clear, pos))
                    p.setFont(rfont)
                ry += rfm.height() * 1.04 + rruh
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
    """CSS's cubic-bezier(x1, y1, x2, y2) as a function of x (Newton, bisection
    fallback), cached per curve."""
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


def _knee(z: float, soft: float) -> float:
    """max(0, z), eased over `soft` either side of 0 so nothing stops dead
    at a limit: 0 until z = -soft, z from z = soft on."""
    if soft <= 0.0 or z >= soft:
        return max(0.0, z)
    if z <= -soft:
        return 0.0
    return (z + soft) ** 2 / (4.0 * soft)


def _emp_easing(x: float) -> float:
    """Up over the first half of the word, down over the second."""
    if x <= 0.0 or x >= 1.0:
        return 0.0
    if x < 0.5:
        return _BEZ_IN(x / 0.5)
    return 1.0 - _BEZ_OUT((x - 0.5) / 0.5)


_CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")
_KANA = re.compile(r"[぀-ヿ]")
_SMALL_KANA = frozenset("ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶー")


@functools.lru_cache(maxsize=512)
def _ja_starts(text: str):
    """Offsets in `text` where pykakasi starts a word, or None where the
    text has no kana or pykakasi is not installed."""
    if not _KANA.search(text):
        return None
    try:
        import spicy_lyrics as SL                       # noqa: PLC0415
        if not SL._kakasi():
            return None
        segs = SL._segments(SL.canon(text))
    except Exception:
        return None
    out, at = set(), 0
    for seg in segs:
        out.add(at)
        at += len(seg.get("orig") or "")
    return frozenset(out) if at == len(text) else None


def _letters_of(core: str) -> int:
    """How many letters `core` reads as: a kana two (a small one or ー one),
    a kanji three, any other letter or digit one -- ずっと as "zutto"."""
    n = 0
    for ch in core:
        if _KANA.match(ch):
            n += 1 if ch in _SMALL_KANA else 2
        elif _CJK.match(ch):
            n += 3
        elif ch.isalnum():
            n += 1
    return n

_EM = 0.83

class Sweep:
    """Where the light is along one row this frame; more than one place when
    words of the row are sung across each other."""

    __slots__ = ("edges", "rtl")

    def __init__(self, edges, rtl: bool = False) -> None:
        self.edges = edges
        self.rtl = rtl

    def near(self, px: float, w: float) -> float | None:
        """The light this unreached fragment belongs to: the nearest one behind
        it, or None; lights already past it are dropped."""
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
    """A held word's characters and where each is this frame: (char, sideways,
    up, scale, lit) per grapheme plus one shared blur radius."""

    __slots__ = ("parts", "radius", "held", "lit", "until", "room")

    def __init__(self, parts, radius: int, held: float = 1.0,
                 lit: float | None = None, until: float | None = None,
                 room: float | None = None) -> None:
        self.parts, self.radius, self.held = parts, radius, held
        # The scale the word is spaced for, one for all its letters (see
        # Amll.emph_of); None spaces each letter for its own.
        self.room = room
        # When the last of the word's letters is back at rest: how long a
        # line the voice has left is held to finish it (Amll.left_hold).
        self.until = until
        # The whole WORD's light this frame, which a fragment's own parts do
        # not know: the glow spills from it past the fill edge (emph_glow).
        self.lit = (max((c[4] for c in parts), default=0.0)
                    if lit is None else lit)

    def __iter__(self):
        return iter(self.parts)


def _solve_spring(frm: float, vel: float, to: float, mass: float,
                  damping: float, stiffness: float):
    """Position at t for a spring let go at `frm` with velocity `vel` (over- or
    underdamped)."""
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
        """How fast the spring travels at t, by a centred difference clamped to
        the moment it was let go."""
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
    """The stack, moved like Apple Music-like Lyrics: each line springs to its
    own place, released in order down the column. view.scroll stays 0."""

    name = "amll"
    scrolls = False

    def rest_top(self, i: int) -> float | None:
        if not 0 <= i < len(self.ys):
            return None
        sp = self.ys[i]
        return sp._queued[1] if sp._queued is not None else sp.target
    HALO = False
    # The emphasis light behind the letters (emph_glow) is faint and wide,
    # the way AMLL's text-shadow is. Strong and tight, in the fill's own
    # colour, it ran into the glyph edges and the lit letters looked
    # fattened and out of focus: 5% more ink than unlit ones at 54px, +2%
    # at this, with as much light round them.
    HALO_SCALE = 0.4
    HALO_SIZE = 2.0
    # AMLL's per-letter emphasis: each letter of a held word grows by up to a
    # tenth of `amount` (SWELL) and lifts on its own (BOB), in slots as wide as
    # its grown advance.
    SWELL = 1.0
    BOB = 1.0

    ALIGN = 0.40
    SCALE = 0.97
    GLIDE = True
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
        self._leaving: dict = {}
        self._leads = (None, {})
        self._shut_memo = []
        self._shown: dict[int, float] = {}
        self._lift = 0.0
        self.now = getattr(view, "frame_now", mono)

    def focus_trim(self, dist: int):
        """The focus band faded out over FOCUS_FADE more lines instead of cut,
        since this column does not scroll; hard cut under zero-g or clouds."""
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
        """Whether any line is still on its way. A spring with no curve and
        nothing queued has arrived, which is nearly all of them nearly always,
        so that is looked at first and `arrived` only asked of the rest."""
        if self.offset != 0.0:
            return True
        if any(0.0 < o < 1.0 for o in self._shown.values()):
            return True
        for springs in (self.ys, self.scales):
            for s in springs:
                if (s._f is not None or s._queued is not None) and not s.arrived():
                    return True
        return False

    def wheel(self, dy: float) -> bool:
        """Take the wheel while the column is this renderer's to move (not for
        unsynced documents, which the stack draws); the step lands whole and
        springs carry it."""
        if not self.v.synced:
            return False
        lo, hi = self._bounds
        was = self.offset
        self.offset = max(lo, min(hi, self.offset - dy * 0.7))
        self._jolt = self._jolt or self.offset != was
        return True

    def _rebase(self, plan, H: int) -> bool:
        """A new song under the renderer means new springs, starting two
        windows below; keyed on the track id (the words only without a
        clock)."""
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
        self._shown, self._lift = {}, 0.0
        self._last_top = self._sought = self._focal_was = None
        self._early = 0
        self._leaving = {}
        return True

    def _step(self) -> float:
        """Seconds since the last frame, clamped (MAX_STEP); the unclamped
        figure is kept as `self._wall` for the seek detector."""
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
        """The line the column is built around: view.focus_line, except that a
        seek landing on a line's own start pins the column there until
        playback catches up."""
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

    def adlib_leads(self) -> dict:
        """{ad-lib line: its lead} -- the group's lead line, or the nearest
        lead above where there is no group. Ad-libs without one never fold.
        See docs/notes/mild-lyrics/renderers.md, 2026-10-19."""
        v = self.v
        had = self._leads[0]
        if had is not None and had[0] is v.lines and had[1] == len(v.lines):
            return self._leads[1]
        lead_of: dict = {}
        for i, ln in enumerate(v.lines):
            g = ln.get("group")
            if g is not None and not ln.get("background"):
                lead_of.setdefault(g, i)
        out, above = {}, None
        for i, ln in enumerate(v.lines):
            if not ln.get("background"):
                if not ln.get("dots") and not ln.get("credits"):
                    above = i
                continue
            g = ln.get("group")
            lead = lead_of.get(g) if g is not None else above
            if lead is not None:
                out[i] = lead
        self._leads = ((v.lines, len(v.lines)), out)
        return out

    # An ad-lib still opens as it is sung, but this much ahead, so it is half
    # out as its first word starts rather than 0.17s into it.
    ADLIB_EARLY = 0.12

    def shut_adlibs(self, live, focal: int, pos: float | None = None) -> frozenset:
        """The ad-libs folded away this frame (Ad-libs only with their line):
        every one whose lead (unless an interlude parts them) and own line are
        neither sounding nor focal, nor itself about to start."""
        if not getattr(self.v, "adlibs_with_line", False):
            return frozenset()
        on = set(live)
        on.add(focal)
        lines = self.v.lines
        if pos is not None:
            for i in self.adlib_leads():
                s = lines[i].get("start")
                if s is not None and 0.0 < s - pos <= self.ADLIB_EARLY:
                    on.add(i)

        def stray(i, lead):
            # An interlude between them: it opens on its own clock, not with
            # the lead (Self Aware's "Oh", 5s after its lead).
            return any(ln.get("dots")
                       for ln in lines[min(i, lead) + 1:max(i, lead)])

        return frozenset(i for i, lead in self.adlib_leads().items()
                         if i not in on and (lead not in on or stray(i, lead)))

    def shut_offs(self, plan, shut: frozenset):
        """The plan's offsets with shut ad-libs taking no room: each sits under
        the line after it, and its lead gets the ordinary gap back. Two kept:
        paint also asks for the column without the ad-libs opening ahead."""
        key = (plan, shut, self.v.line_spacing)
        for k, got in self._shut_memo:
            if k[0] is plan and k[1:] == key[1:]:
                return got
        v, n = self.v, len(plan)
        offs, cur = [0.0] * n, 0.0
        for i, entry in enumerate(plan):
            offs[i] = cur
            if i in shut:
                continue
            j = i + 1
            while j in shut:
                j += 1
            nxt_bg = j < n and v.lines[j]["background"]
            gap = entry[5].height() * (
                0.16 if (v.lines[i]["background"] or nxt_bg) else 0.42)
            cur += entry[1] + gap * v.line_spacing
        self._shut_memo = [(key, (offs, cur))] + self._shut_memo[:1]
        return offs, cur

    # How much of the room an ad-lib opening ahead of its lead takes from
    # above: the lines above go up this much of it, the lines below down the
    # rest.
    ADLIB_LIFT = 0.65

    def adlib_lift(self, plan, shut: frozenset, focal: int, total: float) -> float:
        """How far the column goes up for the ad-libs below the focal line
        that are out before their lead is."""
        leads = self.adlib_leads()
        ahead = [i for i, lead in leads.items()
                 if i > focal and lead != focal and i not in shut]
        if not ahead:
            return 0.0
        _offs, folded = self.shut_offs(plan, shut | frozenset(ahead))
        return self.ADLIB_LIFT * max(0.0, total - folded)

    ADLIB_IN, ADLIB_OUT = 0.15, 0.6

    def show_adlibs(self, shut: frozenset, step: float) -> dict:
        """{ad-lib: how far it has faded in}, eased towards out or in. Out is
        slow: a folding one fades as the gap closes (adlib_fade), this is the
        backstop."""
        out = {}
        for i in self.adlib_leads() if getattr(self.v, "adlibs_with_line",
                                                False) else ():
            want = 0.0 if i in shut else 1.0
            o = self._shown.get(i)
            if o is None:
                o = want
            elif o < want:
                o = min(want, o + step / self.ADLIB_IN)
            elif o > want:
                o = max(want, o - step / self.ADLIB_OUT)
            out[i] = o
        self._shown = out
        return out

    # The fade waits for this much of the room (in ad-lib heights), then
    # comes in over this much more: in step with the lines moving off.
    ROOM_FROM, ROOM_OVER = 0.3, 0.6

    def adlib_fade(self, i: int, y: float, h: float) -> float:
        """How strongly an ad-lib is drawn: its fade, held down until the line
        below has moved off far enough not to be printed through."""
        o = self._shown.get(i, 1.0)
        if o <= 0.0:
            return 0.0
        room = self.ys[i + 1].value - y if i + 1 < len(self.ys) else h
        return _smooth(o) * _smooth((room - self.ROOM_FROM * h)
                                    / (self.ROOM_OVER * h))

    @staticmethod
    def faded(p, fade: float, draw) -> None:
        """draw(), with every opacity it sets scaled by `fade`.

        QPainter.setOpacity is absolute and the fill, glow and base each set
        their own, so the painter's own setter is shadowed for the call."""
        QPainter.setOpacity(p, fade)
        p.setOpacity = lambda a: QPainter.setOpacity(p, a * fade)
        try:
            draw()
        finally:
            del p.setOpacity
            QPainter.setOpacity(p, 1.0)

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
        """Every light along this row, or None before any: the whole row is
        read; with nothing mid-flight the light waits at the furthest
        finished word."""
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
    LATE_POP = 1.0
    EMP_LETTERS = 4.5
    EMP_SHORT = 0.8
    EMP_POW = 0.6
    FLOAT_MIN = RISE_TIME
    EMP_LEAD = RISE_LEAD
    SETTLE = 0.25
    CHAR_STEP = RISE_LEAD
    RISE = 0.055
    # A letter's light runs this share of its grow, from the same start: it
    # flares as the fill reaches the letter and is out while the letter is
    # still up. On the grow's own envelope it peaked 1.4s behind the voice
    # on a 3.4s note and was still lit 2.9s on -- "lasts too long".
    EMP_GLOW = 0.4

    _GRAPHEMES: dict = {}

    def syll_bar(self) -> float:
        """How long a syllable must be held to be one, or 0 for the word (read
        through a default for the test stubs)."""
        return max(0.0, float(getattr(self.v, "syll_hold", 0.0) or 0.0))

    def held_bar(self) -> float:
        """How long a WORD must be held to be emphasised: Pop only past, or
        AMLL's own second where that is 0. The letter rate in `emphasised`
        still applies on top, so a long word spoken is not a note held."""
        if self.jelly() > 0.0:
            return self.JELLY_BAR
        return self.note_bar()

    def note_bar(self) -> float:
        """held_bar without the jelly troll: what makes a word a held note."""
        bar = float(getattr(self.v, "pop_min", 0.0) or 0.0)
        return bar if bar > 0.0 else self.EMP_MIN

    # The Jelly lines troll: what Pop only past at 0.05s did before the
    # bend was scaled by length -- every word of the line sung bends in
    # full, a quick "in" as far as a held note. It looked funny, so it stays.
    JELLY_BAR = 0.05
    JELLY_LEN = 0.5
    LEAN_MAX = 0.6

    @staticmethod
    def emp_tail(held: float) -> float:
        """How long a held word goes on moving after the note: it may lag
        behind a little, never by seconds -- 30% of the note, 0.3s to 0.6s."""
        return min(0.6, max(0.3, 0.3 * held))

    def jelly(self) -> float:
        return max(0.0, float(getattr(self.v, "jelly", 0.0) or 0.0))

    def pop_of(self, s, e, pos: float, act: float, fm: QFontMetricsF) -> tuple:
        """No whole-syllable pop here: AMLL has none. A held syllable moves
        through its emphasis (emph_of), and every other word only floats."""
        return 1.0, 0.0

    def long_glow(self, *_a, **_k) -> None:
        """Glow long words is the emphasis' own per-letter light here -- see
        emph_of, which adds `pop_glow` to the glow it gives each letter."""
        return None

    @classmethod
    def graphemes(cls, txt: str) -> tuple:
        """A word split into graphemes, a base character keeping its marks."""
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
            if len(cls._GRAPHEMES) > 4096:
                cls._GRAPHEMES.clear()
            hit = cls._GRAPHEMES[txt] = tuple(out)
        return hit

    @classmethod
    def emphasised(cls, core: str, dur: float, bar: float = 0.0,
                   least: float | None = None) -> bool:
        """Whether this word (or syllable, with `bar`) is held rather than
        merely long: a per-letter bar from EMP_LETTERS and EMP_POW, CJK by
        reading, never RTL."""
        if _rtl(core):
            return False
        if bar > 0.0:
            return bool(core) and dur >= bar
        least = cls.EMP_MIN if least is None else least
        if _CJK.search(core):
            n = _letters_of(core)
        else:
            n = sum(1 for g in cls.graphemes(core)
                    if any(c.isalnum() for c in g))
        return 1 < n and dur >= least * max(
            cls.EMP_SHORT, (n / cls.EMP_LETTERS) ** cls.EMP_POW)

    # After the held word settles, the line's blur comes back over this long
    # rather than in a frame; a line is only asked about this long after it
    # ends.
    HOLD_EASE = 0.25
    LEAVE_SPAN = 12.0

    def left_hold(self, idx: int, ln: dict, rows, fm: QFontMetricsF,
                  pos: float, live) -> tuple:
        """(hold, sink) for a line the voice has just left, so a held word
        still moving finishes before the line blurs and sinks."""
        if idx in live or not rows:
            self._leaving.pop(idx, None)
            return 0.0, 0.0
        got = self._leaving.get(idx)
        if got is not None and pos < got[0]:
            del self._leaving[idx]
            got = None
        if got is None:
            end = ln.get("end")
            if end is None or not end <= pos <= end + self.LEAVE_SPAN:
                return 0.0, 0.0
            # Asked once, the frame the line is first seen left: after that
            # nothing in it starts, so the answer does not change.
            plan = self.emph_plan(rows, pos, fm, ln["background"])
            until = max((em.until for em in plan.values()
                         if em.until is not None), default=None)
            got = (pos, until if until is not None and until > pos else None)
            self._leaving[idx] = got
        left, until = got
        if until is None:
            return 0.0, 0.0
        if pos <= until:
            x = (pos - left) / max(1e-6, until - left)
            return 1.0, 0.5 + 0.5 * math.cos(math.pi * min(1.0, x))
        return max(0.0, 1.0 - (pos - until) / self.HOLD_EASE), 0.0

    @staticmethod
    def cjk_words(run):
        """`run` cut where unspaced CJK meets: a line written without spaces
        is one word to words_of. Japanese is cut where pykakasi starts a word,
        other CJK a syllable at a time. Punctuation stays with the one before."""
        text = "".join(f[2] for _k, f in run)
        starts = _ja_starts(text)
        out, cur, at = [], [], 0
        for k, f in run:
            core = f[2].strip()
            ink = at + len(f[2]) - len(f[2].lstrip())
            at += len(f[2])
            if cur and any(c.isalnum() for c in core):
                a = _CJK.match(cur[-1][1][2].strip()[-1:])
                b = _CJK.match(core[:1])
                if (a or b) and (starts is None or not (a and b)
                                 or ink in starts):
                    out.append(cur)
                    cur = []
            cur.append((k, f))
        if cur:
            out.append(cur)
        return out

    def emph_plan(self, rows, pos: float, fm: QFontMetricsF,
                  bg: bool = False, font: QFont | None = None,
                  fade: float = 1.0) -> dict:
        """Held words, not held syllables: syllables grouped by words_of, the
        gate asked of the word, characters dealt back out; `syll_hold` makes
        it per syllable."""
        font = font or self.v.lyric_font(bg)
        bar = self.syll_bar()
        width = getattr(self.v, "_lyr_width", None)
        edge = width() if callable(width) else float("inf")
        tail = None
        runs_by_row = []
        for r_i, row in enumerate(rows):
            runs = [[(k, f) for k, f in run if f[2].strip()]
                    for run in self.words_of(row)]
            runs = [r for run in runs if run for r in self.cjk_words(run)]
            if bar > 0.0:
                runs = [[piece] for run in runs for piece in run]
            else:
                runs = [r for run in runs for r in self.held_parts(run)]
            runs_by_row.append(runs)
            if runs:
                tail = (r_i, len(runs) - 1)

        out = {}
        for r_i, runs in enumerate(runs_by_row):
            for w_i, run in enumerate(runs):
                core = "".join(f[2] for _k, f in run).strip()
                s, e = self.span_of(run)
                units = [self.shaped_units(f[2].strip(), font, fm)
                         for _k, f in run]
                chars = [tuple(u[0] for u in us) for us in units]
                flat = tuple(c for g in chars for c in g)
                # A letter sets off when the fill reaches it, so the bend is
                # one slope moving with the colour.
                arrive = []
                for (_k2, frag), us in zip(run, units):
                    fs = frag[3] if frag[3] is not None else s
                    fe = frag[4] if frag[4] is not None and frag[4] > fs else fs
                    wide = max(1e-6, adv(fm, frag[2].strip()))
                    arrive += [fs + (fe - fs) * (ux / wide) for _u, ux in us]
                got = self.emph_of(core, s, e, pos, fm,
                                   (r_i, w_i) == tail, bg, flat, arrive,
                                   self.voiced_of(run), fade)
                if got is None:
                    continue
                spans, at = [], 0
                for (_k2, frag), us in zip(run, units):
                    total_f = adv(fm, frag[2].strip())
                    for gi, (_u, ux) in enumerate(us):
                        end = us[gi + 1][1] if gi + 1 < len(us) else total_f
                        spans.append([frag[0] + ux, max(0.0, end - ux),
                                      frag[0], at + gi])
                    at += len(us)
                if not spans:
                    continue
                left = spans[0][0]
                plain = (spans[-1][0] + spans[-1][1]) - left
                # A third of AMLL's sideways push on top of the slot (0.01 *
                # amount em at full swell).
                push = fm.height() * _EM * 0.1

                def scale_of(i):
                    sc = got.parts[i][3]
                    return sc if got.room is None else max(sc, got.room)

                def wide_of(sp):
                    sc = scale_of(sp[3])
                    return sp[1] * sc + (sc - 1.0) * push

                # Outward from the word's middle: each letter moves by what the
                # letters between it and the middle have grown, plus half its
                # own.
                centre = left + plain * 0.5
                extra = [wide_of(sp) - sp[1] for sp in spans]
                mid = next((i for i, sp in enumerate(spans)
                            if sp[0] < centre < sp[0] + sp[1]), None)
                shift = [0.0] * len(spans)
                if mid is None:
                    right = next((i for i, sp in enumerate(spans)
                                  if sp[0] >= centre), len(spans))
                    inner_r = inner_l = 0.0
                    lo, hi = right - 1, right
                else:
                    inner_r = inner_l = extra[mid] * 0.5
                    lo, hi = mid - 1, mid + 1
                for i in range(hi, len(spans)):
                    shift[i] = inner_r + extra[i] * 0.5
                    inner_r += extra[i]
                for i in range(lo, -1, -1):
                    shift[i] = -(inner_l + extra[i] * 0.5)
                    inner_l += extra[i]
                # Kept off its neighbours: a word spreads into half the space
                # either side and never past its row's start; squeezed only
                # when both sides are short.
                runs = runs_by_row[r_i]
                if w_i > 0:
                    pf = runs[w_i - 1][-1][1]
                    pr = pf[0] + adv(fm, pf[2].rstrip())
                    lo = left - max(0.0, left - pr) * 0.5
                else:
                    lo = left
                if w_i + 1 < len(runs):
                    nf = runs[w_i + 1][0][1]
                    nl = nf[0] + adv(fm,
                        nf[2][:len(nf[2]) - len(nf[2].lstrip())])
                    hi = left + plain + max(0.0, nl - left - plain) * 0.5
                else:
                    # None past the column's edge either: a long word ending
                    # a full row spread out of the window.
                    hi = max(left + plain, edge)
                # At the row's edge the first letter sits flush, so its own
                # size, not the word's, says how far it reaches.
                sc0 = (got.parts[spans[0][3]][3] if w_i == 0
                       else scale_of(spans[0][3]))
                scn = scale_of(spans[-1][3])

                def reach(sh):
                    return (spans[0][0] + sh[0] - spans[0][1] * (sc0 - 1) * 0.5,
                            spans[-1][0] + sh[-1]
                            + spans[-1][1] * (1 + (scn - 1) * 0.5))

                # Eased into rather than hit: at a hard limit the outer
                # letter stopped dead mid-movement and jumped when let go.
                # Never wider than the room the word has at rest, so a word
                # standing still is not moved by it.
                soft = push
                l_e, r_e = reach(shift)
                extra = (r_e - l_e) - plain
                room = max(0.0, (hi - lo) - plain)
                if extra > 0:
                    keep = (extra - _knee(extra - room, min(soft, room))) / extra
                    if keep < 1.0:
                        shift = [x * keep for x in shift]
                        l_e, r_e = reach(shift)
                d = (_knee(lo - l_e, min(soft, left - lo))
                     - _knee(r_e - hi, min(soft, hi - left - plain)))
                if d:
                    shift = [x + d for x in shift]
                placed = {}
                for i, sp in enumerate(spans):
                    placed[sp[3]] = sp[0] + shift[i] - sp[2]
                at = 0
                for (k, _f), g in zip(run, chars):
                    if g:
                        out[(r_i, k)] = Emph(
                            [(c[0], placed[at + gi], c[2], c[3], c[4])
                             for gi, c in enumerate(got.parts[at:at + len(g)])],
                            got.radius, got.held, got.lit, got.until)
                    at += len(g)
        return out

    # A silence longer than this inside a word splits it for the emphasis.
    HOLE_MIN = 0.02

    def held_parts(self, run) -> list:
        """A word with a silence inside it, as the runs the emphasis judges:
        the whole word where every part is held, else each part on its own
        (only a held one moves). See docs/notes/mild-lyrics/renderers.md."""
        parts, last_end = [], None
        for k, f in run:
            if (parts and last_end is not None and f[3] is not None
                    and f[3] - last_end > self.HOLE_MIN):
                parts.append([])
            if not parts:
                parts.append([])
            parts[-1].append((k, f))
            if f[4] is not None:
                last_end = f[4]
        if len(parts) < 2:
            return [run]
        held = [self.emphasised("".join(f[2] for _k, f in part).strip(),
                                self.voiced_of(part) or 0.0, 0.0,
                                self.held_bar())
                for part in parts]
        return [run] if all(held) else parts

    def emph_of(self, txt: str, s, e, pos: float, fm: QFontMetricsF,
                last: bool, bg: bool, parts=None, arrive=None, voiced=None,
                fade: float = 1.0):
        """Where every character of a held word is this frame: grow with
        matching spacing, a sine float from EMP_LEAD, a bezier glow,
        staggered per character."""
        core = txt.strip()
        if s is None or e is None or not core:
            return None
        held_for = (e - s) if voiced is None else voiced
        if not self.emphasised(core, held_for, self.syll_bar(),
                               self.held_bar()):
            return None
        if parts is None:
            parts = self.graphemes(core)
        n = len(parts)
        if not n:
            return None
        # Under the jelly troll a word that is only in because of it moves
        # as one held EMP_MIN would, however long it really is: going by its
        # length, a slow song's ordinary words bent harder and slower than a
        # fast song's. A held note is still a held note and rises through it.
        jelly = self.jelly()
        uniform = jelly > 0.0 and not self.emphasised(
            core, held_for, self.syll_bar(), self.note_bar())
        du = self.EMP_MIN if uniform else max(self.EMP_MIN, held_for)

        amount = du / 2.0
        amount = math.sqrt(amount) if amount > 1.0 else amount ** 3
        amount *= 0.6

        held = min(1.0, max(0.0, (held_for - 0.18) / 1.1))
        radius, lit = self.glow_of(core, fm, held)
        if last:
            amount, lit, du = amount * 1.6, lit * 1.5, du * 1.2
        # How far a word bends answers to how long it is held, full from
        # EMP_MIN up: with Pop only past turned low every word of a line can
        # pass, and a quick "in" bending as far as a held note had the whole
        # line wobbling. Not under the jelly troll, which is exactly that.
        reach = 1.0 if jelly > 0.0 else min(1.0, held_for / self.EMP_MIN)
        amount = min(1.2, amount) * self.v.pop * reach
        lit = min(1.0, lit) * (self.v.glow_scale
                               + float(getattr(self.v, "pop_glow", 0.0) or 0.0))

        em = fm.height() * _EM
        # The bend: AMLL's stagger, swell and 1.4x float, squeezed to end
        # emp_tail after the note; Pop linger runs from that (0) to AMLL's own
        # lengths (1).
        linger = max(0.0, min(1.0, float(getattr(self.v, "pop_linger", 0.0)
                                         or 0.0)))
        end = (e - s) + self.emp_tail(held_for)
        end += (max(end, 1.8 * du) - end) * linger
        # A letter sets off at its own syllable, staggered by two fifths of the
        # syllable, and runs on to the word's end (capped at AMLL's du).
        if arrive is None:
            arrive = [s + (du / 2.5 / n) * i for i in range(n)]
        offs = [max(0.0, a - s) for a in arrive]
        # A letter's float sets off when the one before it arrives (LEAN_MAX);
        # only the float leans, the grow and light wait for the fill.
        leans = [0.0] + [min(self.LEAN_MAX, max(0.0, b - a))
                         for a, b in zip(offs, offs[1:])]
        lens = [max(0.15, min(du, (end - o + self.EMP_LEAD) / 1.4))
                for o in offs]
        floats = [max(0.15, min(du, (end - o + l + self.EMP_LEAD) / 1.4))
                  for o, l in zip(offs, leans)]
        if n > 1 and not uniform:
            # A late syllable (the y of happ|y) gets as long a pop as the first
            # letter's pop, running at most one more emp_tail past the word.
            past = end + self.emp_tail(held_for) + self.EMP_LEAD
            lens = [max(ln, min(du, self.LATE_POP * lens[0], (past - o) / 1.4))
                    for ln, o in zip(lens, offs)]
            floats = [max(fl, min(du, self.LATE_POP * floats[0],
                                  (past - o + l) / 1.4))
                      for fl, o, l in zip(floats, offs, leans)]
        if uniform:
            # What a jelly letter ran for before, typically: 0.48s median
            # over lyrics/fetched, and only the held 5% ran a second.
            leans = [min(l, self.JELLY_LEN * 0.25) for l in leans]
            lens = [self.JELLY_LEN] * n
            floats = [self.JELLY_LEN + l / 1.4 for l in leans]
        # Word pop is how far the word bends, so it scales the bob too: the
        # bob is most of what the eye reads as the bend, and with `amount`
        # alone the knob only reached the grow and a fraction of a pixel of
        # lift. 1 is AMLL's own 0.05em.
        swell = (em * 0.05 * min(1.0, self.v.rise)
                 * (jelly if jelly > 0.0 else max(0.0, self.v.pop) * reach))

        out, alive = [], False
        for i, ch in enumerate(parts):
            de = s + offs[i]
            k = _emp_easing(max(0.0, min(1.0, (pos - de) / lens[i]))) * fade
            kg = _emp_easing(max(0.0, min(1.0, (pos - de)
                                          / (lens[i] * self.EMP_GLOW)))) * fade
            x = (pos - (de - leans[i] - self.EMP_LEAD)) / (floats[i] * 1.4)
            # sin squared, not AMLL's sin: the same peak, landing at rest; the
            # grow's lift rides the same curve.
            up = (math.sin(math.pi * x) ** 2
                  * (swell + 0.025 * amount * em) * fade
                  if 0.0 < x < 1.0 else 0.0)
            if k > 1e-3 or up > 0.01:
                alive = True
            out.append((ch,
                        0.0,
                        up * self.BOB,
                        1.0 + k * 0.1 * amount * self.SWELL,
                        kg * lit))
        # The word opens on one curve: out with the first letter's grow and
        # back in as the letters come down. Spaced for each letter's own grow,
        # a letter out at the edge moved by the sum of every grow between it
        # and the middle -- one push per letter, each starting when the fill
        # got there, so it went out (and back) in stops and starts.
        until = s + max(max(o + ln, o - l - self.EMP_LEAD + fl * 1.4)
                        for o, l, ln, fl in zip(offs, leans, lens, floats))
        # On the grows' own curves, started with the first and ended with the
        # last, so it is never under any letter's grow: a letter's grow is
        # the same curve set off later and run shorter.
        t0, p0 = s - self.EMP_LEAD, s + offs[0] + lens[0] * 0.5
        p1 = max(p0, s + offs[-1] + lens[-1] * 0.5)
        if pos < p1:
            opens = _BEZ_IN(max(0.0, min(1.0, (pos - t0) / max(1e-6, p0 - t0))))
        else:
            opens = 1.0 - _BEZ_OUT(min(1.0, (pos - p1) / max(1e-6, until - p1)))
        room = 1.0 + opens * 0.1 * amount * self.SWELL * fade
        if not alive and room - 1.0 < 1e-5:
            return None
        return Emph(out, radius, held, until=until, room=room)

    def word_lifts(self, rows, fm: QFontMetricsF, pos: float, act: float,
                   blur: float, bg: bool = False) -> dict:
        """How far each word has floated on AMLL's schedule: over its own
        length, one float per word, floored at FLOAT_MIN. See renderers.md,
        "the rise schedule"."""
        if self.v.rise <= 0 or act <= 0.01 or blur >= 1.0:
            return {}
        unit = self.v.lyric_fm(False).height()
        # The resting height on the grid, faded off it: rounding the faded
        # height stepped a settling line down a whole pixel at a time.
        full = self.on_grid(unit * self.RISE * self.v.rise) * act * (1.0 - blur)
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
        playing = _playing(v)
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

        # Scrolled away, every ad-lib is out; back in sync they fold again.
        shut = frozenset() if reading else self.shut_adlibs(live, focal, pos)
        if fresh:
            self._shown = {}
        self.show_adlibs(shut, step)
        if shut:
            offs, total = self.shut_offs(plan, shut)
        else:
            offs = [entry[0] for entry in plan]
        lift = (self.adlib_lift(plan, shut, focal, total)
                if not reading and getattr(v, "adlibs_with_line", False)
                else 0.0)
        if lift > self._lift + 0.5:
            self._jolt = True       # one move with the ad-lib, not staggered
        self._lift = lift
        base = (H * getattr(self.v, "focus_height", self.ALIGN)
                - plan[focal][1] / 2 - offs[focal] - lift)
        self._bounds = (min(0.0, -offs[focal]),
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
            # Aimed at a whole pixel, so that a line which has arrived has no
            # fraction left to glide by -- see _paint_line_at -- and is drawn
            # as sharp glyphs, not pictures. Half a pixel, once, at rest.
            y = self.on_grid(top + offs[i])
            sp = self.ys[i]
            if not (sp._f is None and sp._queued is None
                    and abs(sp.target - y) < 0.001 and sp.stiffness == stiff
                    and sp.damping == damp and sp.mass == 0.9):
                sp.set_params(stiff, damp, 0.9)
                if fresh and i == focal:
                    sp.set_target(y)
                else:
                    sp.set_target(y, delay)
                sp.update(step)

            sc = self.scales[i]
            lit = i == focal or i in live
            goal = 1.0 if (lit or not playing) else small
            if not (sc._f is None and sc._queued is None
                    and abs(sc.target - goal) < 0.001 and sc.stiffness == 100.0
                    and sc.damping == 25.0 and sc.mass == 2.0):
                sc.set_params(100.0, 25.0, 2.0)
                sc.set_target(goal, delay)
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
            fade = self.adlib_fade(i, y, h) if i in self._shown else 1.0
            if fade <= 0.01:
                rects.append((i, y + v.scroll, 0.0, x0 + lo, x0 + hi))
                continue
            rects.append((i, y + v.scroll, h, x0 + lo, x0 + hi))
            if y >= H + m or y + h <= -m:
                continue
            if fade < 0.99:
                args = (i, v.lines[i], rows, fm, x0, y, pos, live,
                        rrows, rfm, ruby, rufm)
                s_i = self.scales[i].value
                self.faded(p, fade, lambda: self._scaled(
                    p, args, s_i, x0, width, y, h))
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
        """One line under its own scale if it has one; no transform at full
        size, so the sung line stays sharp."""
        if abs(s - 1.0) < self.SCALE_EPS:
            self._paint_line(p, *args)
            return
        p.save()
        self.scale_about(p, s, x0, width, y, h)
        self._paint_line(p, *args)
        p.restore()


class Pinned(Renderer):
    """Shared ground for the renderers that do not scroll: view.scroll stays 0
    and every word is drawn live."""

    scrolls = False
    ADLIB_GAP = 0.22

    CREDIT_AFTER = 0.0

    def __init__(self, view) -> None:
        super().__init__(view)
        self._pairs: dict = {}
        self._ikey = None
        self._idx = ({}, {}, [], {})
        self._page = None
        self._endkey, self._end, self._first = None, None, None

    def song_end(self) -> float | None:
        """The last moment this document has words, or None; worked out once
        per document."""
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
        """Only on the static page, where the layout is the stack's, so review
        marks can go under the words."""
        return not self.v.synced

    def static_page(self, p, x0: float, width: float, H: int) -> bool:
        """A document with no clock, handed whole to a kept stack renderer to
        print as a page. True if it was."""
        if self.v.synced:
            return False
        if self._page is None:
            self._page = Flow(self.v)
        self._page.paint(p, x0, width, H)
        return True

    def font(self, px: float) -> QFont:
        """The lyric face at a size of this renderer's choosing."""
        return self.v.ui_font(px, QFont.Weight.Black)

    def face_pair(self, px: float):
        """(font, metrics) at this size, built once and shared, so the metrics'
        memos survive frames."""
        v = self.v
        key = (v.family, max(8, int(px)), v.font_weight)
        got = self._pairs.get(key)
        if got is None:
            if len(self._pairs) > 32:
                self._pairs.clear()
            font = self.font(px)
            got = self._pairs[key] = (font, QFontMetricsF(font))
        return got

    def rows_of(self, ln: dict, fm: QFontMetricsF, width: float,
                align: str = "centre"):
        return self.v.wrap_pieces(self.v.line_pieces(ln), fm, width, align)

    def singable(self, i: int) -> bool:
        """A line these renderers pick between: never the trailing credits
        block."""
        ln = self.v.lines[i]
        return not ln.get("credits")

    def _index(self):
        """The document sorted into heads (lines with a place of their own) and
        the rest, via `group`; once per document."""
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
        """Whether (lines, count) is the document `had` was worked out for, the
        list compared with `is`."""
        return had is not None and had[0] is key[0] and had[1] == key[1]

    def forget(self) -> None:
        """The document was replaced: drop anything kept by line number.
        Default does nothing."""

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
        """The line to build the frame around (view.focus_line, lead before its
        ad-libs) and the head after it."""
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
        """Publish a line's box so a click seeks there, in stack space (scroll
        is 0 here)."""
        self.v.line_rects.append((i, top + self.v.scroll, h, x0, x0 + width))

    def line_lifts(self, rows, fm: QFontMetricsF, pos: float,
                   act: float) -> list:
        """How far each fragment has lifted, one dict per row, on the whole
        line's rise schedule (Renderer.rise_plan)."""
        if self.v.rise <= 0 or act <= 0.01:
            return [{} for _ in rows]
        full = fm.height() * 0.055 * self.v.rise * act
        return self.frag_lifts(rows, full, pos)

    def draw_row(self, p, row, ox: float, ry: float, fm: QFontMetricsF,
                 pos: float, act: float, alpha: float,
                 sung, base, clear, lifts: dict | None = None) -> None:
        """One wrapped row filled to the clock: unsung text then fill, under
        the pop and rise transform; `lifts` is this row's share of the
        line's rise."""
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
                grow, poplift = self.pop_of(s, e, pos, act, fm)
                lift += poplift
                self.long_glow(p, txt, p.font(), fm, QPointF(px, ry), s, e,
                               pos, act, lift, grow, act)
            else:
                frac = 0.0
            p.setPen(base)
            p.setOpacity(alpha)
            self.lifted_word(p, QPointF(px, ry), txt, lift, fm, grow, cx, cy)
            # The fill is drawn at opacity `act`: at 0 it paints nothing.
            if frac > 0 and act > 0:
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
        sung = self.v.sung_colour(ln)
        base = self.v.base_colour(ln)
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
        """The backing vocals of one line, small, under it inside its block.
        Returns the drop."""
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
    """The sung line alone and large between its neighbours, cross-faded on
    this renderer's own FADE clock; neighbours hung off its real height."""

    name = "spotlight"
    FADE = 0.22

    def __init__(self, view) -> None:
        super().__init__(view)
        self.cur = None
        self.gone: dict[int, float] = {}

    def forget(self) -> None:
        self.cur, self.gone = None, {}

    def leaving(self, cur):
        """{line: how much is left} for the one line on its way out, always the
        latest."""
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
        big, fm_big = self.face_pair(v.lyric_px() * 1.5)
        small, fm_sm = self.face_pair(v.lyric_px() * 0.62)
        out = self.leaving(cur)

        head = foot = H * 0.46
        p.setFont(big)
        for i in sorted(out, key=lambda k: out[k]) + ([] if cur is None else [cur]):
            ln = v.lines[i]
            act = 1.0 if i == cur else out[i]
            if ln.get("dots"):
                self._paint_dots(p, ln, fm_big, x0, H * 0.42, pos, act,
                                 act * 0.9, width, "centre")
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
    """Two lines in the middle: being sung and coming, alternating by lines
    that take a band; ad-libs drawn under their line; the next brightens
    toward its turn."""

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
        font, fm = self.face_pair(v.lyric_px() * 0.94)
        small, fm_sm = self.face_pair(v.lyric_px() * 0.58)
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
                                 0.20 if coming else 0.34, width, "centre")
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
    """One word at a time, very large: syllables rejoined into words, ad-libs
    as a small word below, unworded lines drawn whole."""

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
        font, fm = self.face_pair(px)
        p.setFont(font)
        txt, s, e = word
        w = fm.horizontalAdvance(txt)
        sung = self.v.sung_colour(ln)
        base = self.v.base_colour(ln)
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
        line_font, fm_line = self.face_pair(v.lyric_px() * 1.1)
        if ln.get("dots"):
            p.setFont(line_font)
            self._paint_dots(p, ln, fm_line, x0, H * 0.46, pos, 1.0, 0.9, width,
                             "centre")
            return

        live = self.live(pos)
        timed = self.timed_words(ln, fm_line, width)
        if not timed:
            p.setFont(line_font)
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
        sub_h = self.face_pair(sub_px)[1].height()
        y = mid + h * 0.55
        for j, word in subs:
            ox, w, _h = self.show_word(p, v.lines[j], word, x0, width,
                                       y + sub_h / 2, sub_px, pos, 0.30)
            self.mark(j, y, sub_h, ox, w)
            y += sub_h * 1.15
        if self.credits_due(pos):
            self.credits_block(p, x0, width, y + sub_h * 0.35, H)


class Cards(Pinned):
    """A card per line for the whole song, scrolling like the stack; ad-libs
    inset smaller, the credit at the foot of the column."""

    name = "cards"
    scrolls = True
    INSET = 0.10
    # Unlit cards as one kept picture each (see still_card); off to A/B it.
    STILL_CACHE = True
    STILL_BYTES = 16 * 2**20

    def rows(self, i: int, fm: QFontMetricsF, width: float):
        """This renderer's wrapped rows for a line, kept in the window's layout
        cache."""
        v = self.v
        key = ("cards", i, int(width), int(v.lyric_px()), v.align, v.roman,
               v.furigana, v.periodic)
        hit = v.layout_cache.get(key)
        if hit is None:
            hit = v.layout_cache[key] = self.rows_of(v.lines[i], fm, width)
        return hit

    def paint(self, p, x0: float, width: float, H: int) -> None:
        v = self.v
        v.line_rects = []
        pos = v.position() - v.track_offset()
        live = self.live(pos)
        font, fm = self.face_pair(v.lyric_px())
        small, fm_sm = self.face_pair(v.lyric_px() * 0.66)
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
                                     fade * 0.9 * room, cw - pad * 2, "centre")
                else:
                    p.save()
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(255, 255, 255,
                                      int((14 + 16 * lit) * dist)))
                    p.drawRoundedRect(QRectF(cx, y, cw, h), pad * 0.7, pad * 0.7)
                    p.restore()
                    alpha = (0.82 if still else 0.34) * fade
                    if not (act == 0 and self.STILL_CACHE and self.still_card(
                            p, i, ln, rows, f, cx + pad, cw - pad * 2,
                            y + pad, alpha)):
                        self.draw_block(p, ln, rows, f, cx + pad, cw - pad * 2,
                                        y + pad, pos, act, alpha)
            self.mark(i, y, h, cx, cw)
            y += h + gap * room
        v.content_h = y + v.scroll - top

    def still_card(self, p, i, ln, rows, fm, x0: float, width: float,
                   top: float, alpha: float) -> bool:
        """An unlit card's words as one kept picture drawn on whole device
        pixels; False where it cannot. Kept while the column rests."""
        t = p.transform()
        if t.type() not in _SHIFTS:
            return False
        v = self.v
        dpr = v.devicePixelRatioF() or 1.0
        m = max(3.0, fm.height() * 0.22) + 2.0
        gx, gy = (x0 + t.dx()) * dpr, (top + t.dy()) * dpr
        ox, oy = math.floor(gx - m * dpr), math.floor(gy - m * dpr)
        base = v.base_colour(ln)
        key = (i, font_key(p.font()), base.rgba(), dpr, round(width, 2),
               round(gx - ox, 4), round(gy - oy, 4))
        cache = getattr(self, "_still", None)
        if cache is None:
            cache = self._still = OrderedDict()
            self._still_bytes = 0
        got = cache.get(key)
        if got is not None and got[0] is rows:
            cache.move_to_end(key)
            pm = got[1]
        else:
            rowh = fm.height() * 1.06
            pw = int(math.ceil((width + m * 2) * dpr)) + 2
            ph = int(math.ceil((len(rows) * rowh + m * 2) * dpr)) + 2
            pm = QPixmap(max(1, pw), max(1, ph))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            pp = QPainter(pm)
            pp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            pp.translate(t.dx() - ox / dpr, t.dy() - oy / dpr)
            pp.setFont(p.font())
            pp.setPen(base)
            ry = top + fm.ascent()
            for row in rows:
                for x, w, txt, _s, _e in row:
                    px = x0 + x
                    self.lifted_word(pp, QPointF(px, ry), txt, 0.0, fm, 1.0,
                                     px + w * 0.5, ry - fm.ascent() * 0.35)
                ry += rowh
            pp.end()
            if got is not None:
                self._still_bytes -= got[1].width() * got[1].height() * 4
            cache[key] = (rows, pm)
            cache.move_to_end(key)
            self._still_bytes += pm.width() * pm.height() * 4
            while self._still_bytes > self.STILL_BYTES and len(cache) > 1:
                _k, (_r, old) = cache.popitem(last=False)
                self._still_bytes -= old.width() * old.height() * 4
        p.save()
        p.setOpacity(alpha)
        blit(p, QPointF(ox / dpr - t.dx(), oy / dpr - t.dy()), pm)
        p.restore()
        return True


class _Spr:
    """Spicy Lyrics' spring, a stepped port of Fraktality's spr (`f` in hertz,
    `d` the damping ratio)."""

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
    """The `cubic-spline` package Spicy draws its keyframes through: a natural
    cubic spline read at x."""

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
        self._end = None

    def end(self) -> float:
        """`at(1)`, where the effect finishes -- worked out once.

        Asked for by every settled fragment of every line on every frame (a
        hundred and fifty of them on a song of two hundred lines) and the
        curves are constants, so it is the same number each time.
        """
        if self._end is None:
            self._end = self.at(1)
        return self._end

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
                 "sc", "y", "g", "op", "rest")

    def __init__(self, row, x, w, core, s, e, origin, letters) -> None:
        self.row, self.x, self.w, self.core = row, x, w, core
        self.s, self.e, self.origin, self.letters = s, e, origin, letters
        self.sc = self.y = self.g = self.op = None
        self.rest = False


def _gauss(img: QImage, radius: float) -> QImage:
    """A Gaussian blur as a CSS text-shadow draws one, via Qt's blur effect at
    the CSS radius."""
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


class RowsRead(list):
    """Spicy's romanisation rows with their periodic readings and face."""
    ruby, rufm, rufont = (), None, None


class Spicy(Renderer):
    """Spicy Lyrics' renderer as the Spicetify extension draws it (springs per
    syllable, letter splits, gradient fill, shadow-drawn idle lines). See
    `knob`."""

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
        self.now = getattr(view, "frame_now", mono)
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
        self._pix_bytes = 0
        self._frags: dict = {}
        self._lays: dict = {}
        self._pairs: dict = {}
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
        """How each line is drawn by its place, not its own clock: above the
        current line finished, below it untouched; the current line is the
        last started."""
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
                    fr.rest = False
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
                        if fr.rest:
                            continue
                        if not self._resting(fr):
                            self._rest(fr, bool(lines[i].get("dots")))
                        fr.rest = True
                    continue
                for fr in frags[i]:
                    fr.rest = False
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
                    fr.rest = False
                    fr.sc = fr.y = fr.g = fr.op = None
                    for lt in fr.letters or ():
                        lt[3] = lt[4] = lt[5] = None

    def _resting(self, fr: _Frag) -> bool:
        """Already settled finished, as _rest leaves it."""
        return (fr.sc is not None and fr.sc.v == 0.0 and fr.y.v == 0.0
                and fr.g.v == 0.0 and fr.sc.p == fr.sc.g and fr.y.p == fr.y.g
                and fr.g.p == fr.g.g and fr.sc.g == (self.D_SCALE.end()
                if fr.op is not None else self.SCALE.end()))

    def _rest(self, fr: _Frag, dots: bool) -> None:
        """Springs already settled at the end of the syllable."""
        if dots:
            fr.sc = _Spr(self.D_SCALE.end(), *self.DOT_SC_SPR)
            fr.y = _Spr(self.D_YOFF.end(), *self.DOT_Y_SPR)
            fr.g = _Spr(self.D_GLOW.end(), *self.DOT_G_SPR)
            fr.op = _Spr(self.D_OP.end(), *self.DOT_OP_SPR)
            fr.op.settle()
        else:
            fr.sc = _Spr(self.SCALE.end(), *self.SC_SPR)
            fr.y = _Spr(self.YOFF.end(), *self.Y_SPR)
            fr.g = _Spr(self.GLOW.end(), *self.G_SPR)
            for lt in fr.letters or ():
                lt[3] = _Spr(self.L_SCALE.end(), *self.SC_SPR)
                lt[4] = _Spr(self.L_YOFF.end(), *self.Y_SPR)
                lt[5] = _Spr(self.GLOW.end(), *self.G_SPR)
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
                if fr.rest:
                    continue
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

    def face_pair(self, px: float, bg: bool = False):
        """(font, metrics) shared by every line at this size, keyed by face,
        rounded size and background."""
        key = (self.face(), max(1, int(round(px))), bool(bg))
        got = self._pairs.get(key)
        if got is None:
            if len(self._pairs) > 32:
                self._pairs.clear()
            font = self.font(px, bg)
            got = self._pairs[key] = (font, QFontMetricsF(font))
        return got

    def lay(self, i: int, width: float):
        """A line set at Spicy's size (bg at 3/4, rows 1.18em apart, 5cqw padding):
        (rows, fm, h, rrows, rfm, font, rfont, pitch, ox-shift,
        ruby, rufont, rufm, row-tops)."""
        v = self.v
        ln = v.lines[i]
        fam = self.face()
        own = (ln.get("pieces"), ln.get("pieces_roman"))
        key = (i, int(width), fam, v.align, v.roman, v.furigana, v.periodic,
               v.synced,
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
            font, fm = self.face_pair(px, bg)
            pitch = px * 1.1818
            align = v.line_align(ln)
            avail = width * 0.95
            shift = {"left": 0.0, "centre": width * 0.025}.get(align, width * 0.05)
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
                    rufont, rufm = self.face_pair(px * 0.34, bg)
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
                    rfont, rfm = self.face_pair(px * 0.6, bg)
                    rrows = RowsRead(v.wrap_pieces(v.roman_pieces(ln), rfm,
                                                   avail, v.roman_align(ln, align)))
                    if v.periodic in PT.READS:
                        rrows.rufont, rrufm = self.face_pair(px * 0.26, bg)
                        rrows.ruby, rrows.rufm = v.roman_ruby(ln, rrows, rfm,
                                                              rrufm)
                    h += pitch * 0.1 + len(rrows) * (rfm.height() * 1.04
                                                     + v.ruby_h(rrows.rufm))
                out = (rows, fm, h, rrows, rfm, font, rfont, pitch, shift,
                       ruby, rufont, rufm, tops)
        if len(self._lays) > 4000:
            self._lays.clear()
        self._lays[key] = (out, own)
        return out

    def lays_all(self, width: float, n: int) -> list:
        """`lay` for every line, with the cache key's common part built once."""
        v = self.v
        lines = v.lines
        w, fam = int(width), self.face()
        mode = (v.align, v.roman, v.furigana, v.periodic, v.synced)
        ink = getattr(v, "_ink_gen", 0)
        scale = self.knob("font_scale", 1.0)
        get = self._lays.get
        out = []
        for i in range(n):
            ln = lines[i]
            hit = get((i, w, fam, *mode, id(ln), id(ln.get("pieces")),
                       id(ln.get("pieces_roman")), ink, scale))
            out.append(hit[0] if hit is not None else self.lay(i, width))
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
        playing = _playing(v)
        lines = v.lines
        n = len(lines)
        v.content_h = 0.0
        if not n:
            v.line_rects = []
            return
        self._em = self.em(width)
        self._cq = width / 100.0
        lays = self.lays_all(width, n)
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
                k = _blur(self.v)
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
                self.grad_text(p, QPointF(ox + x, y), txt)
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
        rruh = self.v.ruby_h(getattr(rrows, "rufm", None))
        y = (top + self._row_top(lay, len(rows)) + lay[7] * 0.1
             + rfm.ascent() + self.v.ruby_lead(rruh, rrows.ruby))
        for r_i, row in enumerate(rrows):
            rtl = row_rtl(row)
            for x, w, txt, s, e in row:
                if fill is not None:
                    st = self.state(pos, s, e)
                    gp = (-20 + 120 * self.progress(pos, s, e) if st == "A"
                          else (-20.0 if st == "N" else 100.0))
                    p.setPen(fill(ox + x, w, gp, rtl))
                self.grad_text(p, QPointF(ox + x, y), txt)
            marks = rrows.ruby[r_i] if rruh and r_i < len(rrows.ruby) else ()
            if marks:
                p.setFont(rrows.rufont)
                by = self.v.ruby_base(y, rfm, rruh, rrows.rufm,
                                     rrows.ruby)
                for cx, read, s, e in marks:
                    rw = rrows.rufm.horizontalAdvance(read)
                    if fill is not None:
                        p.setPen(fill(ox + cx - rw / 2, rw,
                                      -20 + 120 * self.progress(pos, s, e)))
                    self.grad_text(p, QPointF(ox + cx - rw / 2, by), read)
                p.setFont(lay[6])
            y += rfm.height() * 1.04 + rruh
        p.restore()

    def _baseline(self, lay, top: float, row: int) -> float:
        """line-height 1.1818: the glyph box centred in each row's pitch."""
        fm, pitch = lay[1], lay[7]
        below = (Spicy._row_top(lay, row) if self.v.ruby_under(lay[9])
                 else Spicy._row_top(lay, row + 1) - pitch)
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
            by = self.v.ruby_base(self._baseline(lay, top, r_i), fm,
                                  rufm.height() * 0.92, rufm, ruby)
            for cx, read, s, e in marks:
                rw = rufm.horizontalAdvance(read)
                rx = ox + cx - rw / 2
                at = self.v.ruby_anchor(cx, read, rufm, ruby)
                under = next((fr for fr in frags if fr.row == r_i
                              and fr.x <= at <= fr.x + fr.w), None)
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
                self.grad_text(p, QPointF(rx, by - lift), read)
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
        sung = getattr(self.v, "sung_colour", None)
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
        """Text under a CSS `scale` about (ox, cy) after a translateY; a `fill`
        is laid into a solid mask so overlapping glyphs show no seams."""
        if fill is None:
            self.lifted_word(p, at, txt, lift, fm, scale, ox, cy)
            return
        dpr = self.v.devicePixelRatioF() or 1.0
        m = max(3.0, fm.height() * 0.22)
        x0 = math.floor((at.x() - m) * dpr) / dpr
        y0 = math.floor((at.y() - fm.ascent() - m) * dpr) / dpr
        pw = int(math.ceil((adv(fm, txt) + m * 2) * dpr)) + 2
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
        """A text-shadow (0 0 radius, white at alpha), blended between the two
        nearest half-pixel radii."""
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
        long_glow = self.knob("pop_glow", 0.0)
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
            held = self.swell_of(fr.s, fr.e, pos, 1.0) if long_glow > 0 else 0.0
            if held > 0.004:
                self._glow(p, fr.core, font, fm, QPointF(bx, base), 6.0,
                           0.35 * long_glow * held ** 0.7, scale, lift, orx, cy)
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
        settled = all(fr.rest or fr.sc is None
                      or (fr.sc.asleep() and fr.y.asleep()) for fr in frags)
        if lvl < 0.3:
            lvl = 0.0
        sig = None
        if settled:
            sig = (i, pen.rgb(), int(width), int(self._em), v.align,
                   v.roman, self.face(),
                   v.devicePixelRatioF(), id(lay[0]),
                   self.knob("pop", 1.0), self.knob("rise", 1.0),
                   self.knob("pop_min", 0.0),
                   tuple((round(sc, 3), round(yo, 4))
                         for sc, yo in map(self._now_of, frags)))
            have = self._pix.get(sig) or {}
            if have:
                self._pix[sig] = self._pix.pop(sig)
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
            self._keep_pix(sig, lvl, pm, pad)
        p.save()
        p.setOpacity(opac)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        blit(p, QPointF(x0 - pad, top - pad), pm)
        p.restore()

    PIX_BUDGET = 96 << 20

    def _keep_pix(self, sig, lvl, pm: QPixmap, pad: int) -> None:
        """Keep a drawn line within a count and a byte budget, dropping the
        least recently drawn."""
        room = self._pix
        if sig not in room and len(room) > 60:
            self._drop_pix(next(iter(room)))
        row = room.setdefault(sig, {})
        old = row.get(lvl)
        if old is not None:
            self._pix_bytes -= old[0].width() * old[0].height() * 4
        row[lvl] = (pm, pad)
        self._pix_bytes += pm.width() * pm.height() * 4
        if self._pix_bytes > self.PIX_BUDGET:
            for k in [k for k in room if k != sig]:
                if self._pix_bytes <= self.PIX_BUDGET:
                    break
                self._drop_pix(k)

    def _drop_pix(self, sig) -> None:
        for pm, _pad in (self._pix.pop(sig, None) or {}).values():
            self._pix_bytes -= pm.width() * pm.height() * 4

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
