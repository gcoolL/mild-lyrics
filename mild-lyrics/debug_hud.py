"""The debug overlay: what the window is doing, drawn in a corner of it.

Three levels past off, each the one before it with more added:

    minimal    the frame rate, what a frame costs, and how long this song's
               lyrics took and whose they are
    standard   every source the walk asked, what each one said and how long
               it took; the phases of the load; the player and the offset
    full       the frame timer's own target, the caches, memory and threads,
               the cover's load time, startup, recent loads, and what the
               look-ahead had already fetched before the song came on

Two halves, on two sides of a thread line. TRACE is filled in by the fetcher
and by the walk's own threads as a load happens -- it is a lock and a few
dicts, and costs nothing anyone could measure next to the network request
each entry stands for, so it records whether the overlay is up or not and a
song that is already playing has its story when the overlay is turned on.
Hud is the GUI-thread half: it times the paints and draws the box, and does
nothing at all while the level is off.

The box is drawn into a pixmap four times a second and blitted every frame,
so the overlay's own cost stays out of the paint cost it reports.
"""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict, deque

LEVELS = ["off", "minimal", "standard", "full"]

BOOT = time.perf_counter()
KEEP_TRACKS = 16
KEEP_RECENT = 6
REDRAW_EVERY = 0.25
SAMPLE_EVERY = 1.0
FRAME_WINDOW = 1.0
SLOW_LOAD = 2.0
SOURCES_PER_ROW = 4
WRAP_AT = 64

# what a source's answer was, as one letter: word, line, static, nothing,
# fault -- and the colour it is drawn in
MARK = {"syllable": "W", "line": "L", "static": "S", "none": "-", "fault": "x"}
TONE = {"syllable": "good", "line": "ok", "static": "warn", "none": "dim",
        "fault": "bad"}


def now() -> float:
    return time.perf_counter()


def next_level(level: str) -> str:
    at = LEVELS.index(level) if level in LEVELS else 0
    return LEVELS[(at + 1) % len(LEVELS)]


def _ms(secs) -> str:
    if secs is None:
        return "…"
    return f"{secs * 1000:.0f}ms" if secs < 10 else f"{secs:.1f}s"


def _quality(doc) -> str:
    if not isinstance(doc, dict):
        return "none"
    try:
        import lyric_sources as LS
        return LS.quality(doc)
    except Exception:                                    # noqa: BLE001
        return "line"


class _Track:
    """One song's load, as the fetcher and the walk tell it."""

    def __init__(self, tid: str) -> None:
        self.tid = tid
        self.began: float | None = None
        self.loads = 0
        self.asks: OrderedDict = OrderedDict()
        self.ahead: OrderedDict = OrderedDict()
        self.phases: dict = {}
        self.shown: float | None = None
        self.total: float | None = None
        self.result = ("", "none", 0)

    def copy(self) -> "_Track":
        out = _Track(self.tid)
        out.__dict__.update(self.__dict__)
        out.asks, out.ahead = OrderedDict(self.asks), OrderedDict(self.ahead)
        out.phases = dict(self.phases)
        return out


class Trace:
    """What each song's load did, written from any thread.

    A load is begun and ended by the fetcher. Between the two, every provider
    the walk asks reports in through `asked` -- on the walk's own threads,
    which is why everything here is under one lock. Asks that land for a song
    with no load begun are the look-ahead warming it; they are kept apart, in
    `ahead`, so the load that follows can say its answer was already on disk
    rather than look as if it asked nobody.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tracks: OrderedDict = OrderedDict()
        self._recent: deque = deque(maxlen=KEEP_RECENT)
        self.art: tuple | None = None

    def _rec(self, tid: str) -> _Track:
        rec = self._tracks.get(tid)
        if rec is None:
            rec = self._tracks[tid] = _Track(tid)
            while len(self._tracks) > KEEP_TRACKS:
                self._tracks.popitem(last=False)
        else:
            self._tracks.move_to_end(tid)
        return rec

    def begin(self, tid: str) -> None:
        with self._lock:
            rec = self._rec(tid)
            if rec.loads == 0 and rec.asks:
                rec.ahead = rec.asks
            rec.asks = OrderedDict()
            rec.loads += 1
            rec.began, rec.total, rec.shown = now(), None, None
            rec.phases = {}
            rec.result = ("", "none", 0)

    def phase(self, tid: str, name: str, since: float) -> None:
        with self._lock:
            self._rec(tid).phases[name] = now() - since

    def asked(self, tid: str, name: str, secs: float, doc, why: str = "") -> None:
        got = _quality(doc)
        if got == "none" and why:
            got = "fault"
        with self._lock:
            rec = self._rec(tid)
            (rec.asks if rec.loads else rec.ahead)[name] = (secs, got, why)

    def shown(self, tid: str) -> None:
        with self._lock:
            rec = self._rec(tid)
            if rec.began is not None and rec.shown is None:
                rec.shown = now() - rec.began

    def end(self, tid: str, source: str, quality: str, lines: int) -> None:
        with self._lock:
            rec = self._rec(tid)
            if rec.began is None:
                return
            rec.total = now() - rec.began
            # Spicy Lyrics' own copy is the one answer that comes back
            # unlabelled: the walk's and the stored one both carry _source
            if (not source and lines
                    and rec.asks.get("spicy", (0, "none"))[1] != "none"):
                source = "spicy"
            rec.result = (source, quality, lines)
            self._recent.append((rec.total, not rec.asks))

    def art_loaded(self, since: float, ok: bool) -> None:
        with self._lock:
            self.art = (now() - since, ok)

    def track(self, tid) -> _Track | None:
        with self._lock:
            rec = self._tracks.get(tid or "")
            return rec.copy() if rec is not None else None

    def recent(self) -> list:
        with self._lock:
            return list(self._recent)


TRACE = Trace()


class Frames:
    """When each paint happened and what it cost, over the last second."""

    def __init__(self) -> None:
        self.ring: deque = deque()
        self.last: float | None = None

    def reset(self) -> None:
        self.ring.clear()
        self.last = None

    def add(self, began: float, ended: float) -> None:
        gap = began - self.last if self.last is not None else None
        self.last = began
        self.ring.append((ended, gap, ended - began))
        while self.ring and self.ring[0][0] < ended - FRAME_WINDOW:
            self.ring.popleft()

    def stats(self) -> dict:
        gaps = [g for _t, g, _c in self.ring if g is not None]
        cost = sorted(c for _t, _g, c in self.ring)
        if not gaps:
            return {}
        span = sum(gaps)
        return {"fps": len(gaps) / span if span > 0 else 0.0,
                "worst": max(gaps),
                "paint": sum(cost) / len(cost),
                "paint_hi": cost[min(len(cost) - 1, int(len(cost) * 0.95))]}


def _memory() -> str:
    """Resident memory, where the platform says. Linux reads it current;
    elsewhere the peak is what there is."""
    try:
        with open("/proc/self/statm", encoding="ascii") as f:
            pages = int(f.read().split()[1])
        return f"{pages * os.sysconf('SC_PAGE_SIZE') / 2**20:.0f} MB"
    except Exception:                                    # noqa: BLE001
        pass
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        div = 2**20 if os.uname().sysname == "Darwin" else 2**10
        return f"{peak / div:.0f} MB peak"
    except Exception:                                    # noqa: BLE001
        return "?"


def _wrapped(row: list) -> list:
    """A row of one long run, broken at its spaces; any other row as is."""
    if len(row) != 1 or len(row[0][0]) <= WRAP_AT:
        return [row]
    text, tone = row[0]
    out, line = [], ""
    for word in text.split(" "):
        if line and len(line) + 1 + len(word) > WRAP_AT:
            out.append([(line, tone)])
            line = "  " + word
        else:
            line = f"{line} {word}" if line else word
    out.append([(line, tone)])
    return out


class Hud:
    """The GUI-thread half: paint timing, and the box itself."""

    PAD = 8
    MARGIN = 12

    def __init__(self) -> None:
        self.frames = Frames()
        self.level = "off"
        self._pm = None
        self._built = 0.0
        self._sampled = 0.0
        self._sample = ("?", 0)
        self._font = None
        self.first: float | None = None

    def paint(self, p, view, began: float) -> None:
        """Called last in paintEvent, with the moment the paint began."""
        if self.first is None:
            self.first = now()
        level = getattr(view, "debug", "off")
        if level != self.level:
            self.level, self._built = level, 0.0
            self.frames.reset()
        if level not in LEVELS[1:]:
            return
        self.frames.add(began, now())
        t = now()
        if self._pm is None or t - self._built >= REDRAW_EVERY:
            self._built = t
            try:
                self._pm = self._render(self.rows(view.debug_facts()),
                                        view.devicePixelRatioF())
            except Exception:                            # noqa: BLE001
                import traceback
                traceback.print_exc()
                self._pm = None
        if self._pm is not None:
            p.save()
            p.resetTransform()
            p.setClipping(False)
            p.setOpacity(1.0)
            p.drawPixmap(self.MARGIN, self.MARGIN, self._pm)
            p.restore()

    # -- what is said --------------------------------------------------------

    def rows(self, facts: dict) -> list:
        """The box's text, as rows of (text, tone) runs."""
        level = self.level
        rows = [self._frame_row(facts)]
        rec = TRACE.track(facts.get("tid"))
        rows.append(self._load_row(rec, facts))
        if level == "minimal":
            return rows
        if rec is not None:
            rows += self._source_rows(rec, facts, full=level == "full")
            rows.append(self._phase_row(rec))
        rows.append([(f"{facts.get('player', '?')} · {facts.get('status', '?')}"
                      f" · offset {facts.get('offset', 0.0):+.3f}s"
                      f" · {facts.get('lines', 0)} lines", "")])
        if level != "full":
            return rows
        rows += self._full_rows(rec, facts)
        return rows

    def _frame_row(self, facts: dict) -> list:
        st = self.frames.stats()
        if not st:
            return [("fps …", "dim")]
        rate, hz = facts.get("rate", 0.0), facts.get("screen_hz", 0.0)
        # nothing moving: the window repaints a few times a second on purpose,
        # and that is not a frame rate to be judged against the timer's
        idle = bool(facts.get("idle"))
        low = st["fps"] < 0.9 * rate
        out = [(f"{st['fps']:.0f} fps",
                "dim" if idle else "bad" if low else "good"),
               (f" / {rate:.0f}", "dim"),
               (f"  paint {st['paint'] * 1000:.1f}ms", ""),
               (f"  worst {st['worst'] * 1000:.0f}ms",
                "warn" if st["worst"] > 2.5 / max(1.0, rate) else "dim")]
        if facts.get("drawn_on"):
            out.append((f"  {facts['drawn_on']}", "dim"))
        if idle:
            out.append(("  idle", "dim"))
        elif rate < hz - 0.5:
            out.append(("  settled" if rate > 10 else "  hidden", "dim"))
        return out

    def _load_row(self, rec, facts: dict) -> list:
        label = facts.get("source") or ""
        if rec is None or rec.began is None:
            return [("lyrics: " + (label or "not loaded"), "dim")]
        if rec.total is None:
            return [(f"lyrics loading {_ms(now() - rec.began)}", "warn")]
        source, quality, lines = rec.result
        tone = "warn" if rec.total > SLOW_LOAD else ""
        out = [(f"lyrics {_ms(rec.total)}", tone)]
        if lines:
            out.append((f"  {label or source}", ""))
            out.append((f"  {quality}", TONE.get(quality, "")))
        else:
            out.append(("  none found", "bad"))
        if rec.loads > 1:
            out.append((f"  try {rec.loads}", "dim"))
        return out

    def _source_rows(self, rec, facts: dict, full: bool) -> list:
        """Every source asked, in the user's order, one cell each."""
        winner = rec.result[0]
        order = list(facts.get("order") or [])
        names = [n for n in order if n in rec.asks]
        names += [n for n in rec.asks if n not in names]
        if not names:
            if rec.phases.get("walk") is not None:
                why = "warmed ahead" if rec.ahead else "answered from cache"
                return [[("sources: " + why, "dim")]]
            return []
        cells = []
        for n in names:
            secs, got, why = rec.asks[n]
            cells.append([((">" if n == winner else " ") + n, "hi" if n == winner else ""),
                          (" " + MARK.get(got, "?"), TONE.get(got, "")),
                          (f" {_ms(secs):>6}", "dim")])
        rows = []
        for i in range(0, len(cells), SOURCES_PER_ROW):
            row = []
            for cell in cells[i:i + SOURCES_PER_ROW]:
                if row:
                    row.append(("  ", ""))
                row += cell
            rows.append(row)
        for n in names:
            secs, got, why = rec.asks[n]
            if got == "fault" and why:
                rows.append([(f" {n}: {why}"[:72], "bad")])
        if full:
            skipped = [n for n in order if n in (facts.get("enabled") or ())
                       and n not in rec.asks]
            if skipped:
                rows.append([("not asked: " + ", ".join(skipped), "dim")])
        return rows

    def _phase_row(self, rec) -> list:
        out = []
        if "spicy" in rec.asks:
            out.append((f"spicy {_ms(rec.asks['spicy'][0])}  ", ""))
        if "walk" in rec.phases:
            out.append((f"walk {_ms(rec.phases['walk'])}  ", ""))
        if rec.shown is not None:
            out.append((f"first words {_ms(rec.shown)}", "good"))
        return out or [("", "")]

    def _full_rows(self, rec, facts: dict) -> list:
        t = now()
        if t - self._sampled >= SAMPLE_EVERY:
            self._sampled = t
            self._sample = (_memory(), threading.active_count())
        mem, threads = self._sample
        st = self.frames.stats()
        rows = [[(f"timer {facts.get('rate', 0):.1f}Hz"
                  f"  screen {facts.get('refresh_hz', 0):.1f}Hz"
                  f"  cap {facts.get('cap') or 'screen'}", "")]]
        if st:
            rows.append([(f"paint p95 {st['paint_hi'] * 1000:.1f}ms"
                          f"  renderer {facts.get('renderer', '?')}"
                          f"  view {facts.get('view', '?')}", "")])
        rows.append([(f"pixmaps {facts.get('pix_n', 0)}"
                      f" ({facts.get('pix_mb', 0.0):.0f} MB)"
                      f"  glow {facts.get('glow_mb', 0.0):.0f} MB"
                      f"  layouts {facts.get('layouts', 0)}", "")])
        rows.append([(f"memory {mem}  threads {threads}", "")])
        art = TRACE.art
        boot = (self.first - BOOT) if self.first else None
        bits = []
        if art is not None:
            bits.append((f"cover {_ms(art[0])}" + ("" if art[1] else " failed"),
                         "" if art[1] else "bad"))
        if boot is not None:
            bits.append(((" · " if bits else "") + f"startup {_ms(boot)}", "dim"))
        if bits:
            rows.append(bits)
        recent = TRACE.recent()
        if recent:
            rows.append([("recent loads " + "  ".join(
                _ms(s) + ("*" if cached else "") for s, cached in recent),
                "dim")])
        if rec is not None and rec.ahead:
            rows.append([("fetched ahead: " + ", ".join(
                f"{n} {MARK.get(g, '?')}" for n, (_s, g, _w) in rec.ahead.items()),
                "dim")])
        tid = facts.get("tid") or ""
        rows.append([(f"track {tid}", "dim")])
        return rows

    # -- how it is drawn -----------------------------------------------------

    def _render(self, rows: list, dpr: float):
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap
        if self._font is None:
            font = QFont()
            font.setFamilies(["JetBrains Mono", "Cascadia Mono", "Consolas",
                              "DejaVu Sans Mono", "Menlo", "monospace"])
            font.setStyleHint(QFont.StyleHint.Monospace)
            font.setFixedPitch(True)
            font.setPixelSize(12)
            self._font = font
        fm = QFontMetricsF(self._font)
        tones = {"": QColor(225, 225, 225), "dim": QColor(150, 150, 150),
                 "good": QColor(120, 220, 140), "ok": QColor(140, 190, 255),
                 "warn": QColor(240, 190, 90), "bad": QColor(255, 110, 100),
                 "hi": QColor(255, 255, 255)}
        rows = [w for r in rows if any(text for text, _t in r)
                for w in _wrapped(r)]
        line_h = fm.height()
        width = max((sum(fm.horizontalAdvance(text) for text, _t in r)
                     for r in rows), default=0.0)
        w = int(width + 2 * self.PAD + 1)
        h = int(line_h * len(rows) + 2 * self.PAD + 1)
        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        try:
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.setPen(Qt.PenStyle.NoPen)
            q.setBrush(QColor(0, 0, 0, 175))
            q.drawRoundedRect(QRectF(0, 0, w, h), 6, 6)
            q.setFont(self._font)
            y = self.PAD + fm.ascent()
            for row in rows:
                x = float(self.PAD)
                for text, tone in row:
                    q.setPen(tones.get(tone, tones[""]))
                    q.drawText(QRectF(x, y - fm.ascent(), w, line_h),
                               Qt.AlignmentFlag.AlignLeft, text)
                    x += fm.horizontalAdvance(text)
                y += line_h
        finally:
            q.end()
        return pm
