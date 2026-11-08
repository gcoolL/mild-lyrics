"""The document being edited and every operation on it, with no Qt, audio or
network. A word is a run of syllables joined by `part`, not stored."""
from __future__ import annotations

import copy
import weakref
import pathlib
import re
import secrets
import sys
from dataclasses import dataclass, field, fields, replace

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "mild-lyrics", _HERE.parent)
                if str(p) not in sys.path]

import lyric_sources as LS      # noqa: E402
import spicy_lyrics as SL       # noqa: E402


# --------------------------------------------------------------------------
# Bumped by every change to a Syl, Group, Line or Doc, or to a list one holds,
# so a view can know "nothing changed" without walking a 5000-line song.
REV = [0]
# The same, but not by a syllable's or line's start or end: the text and shape.
SHAPE = [0]
# Every object changed, in order, held so its id stays its own while it is
# here; each Changes reader keeps its place in it. LOG_AT is LOG[0]'s place.
LOG: list = []
LOG_AT = [0]
_LOG_CAP = 100_000
_READERS: "weakref.WeakSet" = None     # set below, once Changes exists


class _Tracked(list):
    """A list that bumps REV whenever it is changed."""


def _bumping(name: str):
    base = getattr(list, name)

    def f(self, *a, **k):
        REV[0] += 1
        SHAPE[0] += 1
        _touch(self)
        return base(self, *a, **k)
    f.__name__ = name
    return f


for _n in ("append", "extend", "insert", "pop", "remove", "clear", "sort",
           "reverse", "__setitem__", "__delitem__", "__iadd__", "__imul__"):
    setattr(_Tracked, _n, _bumping(_n))
del _n


class _Rev:
    """Every attribute changed bumps REV (and SHAPE unless it is a time); a
    plain list set becomes a _Tracked."""

    def __setattr__(self, name, value):
        if type(value) is list:
            value = _Tracked(value)
        d = self.__dict__
        # A first set is __init__: an object being built is in no document
        # yet, and gets there through a list, which bumps.
        if name in d:
            REV[0] += 1
            if name not in _TIMES:
                SHAPE[0] += 1
            _touch(self)
        d[name] = value


_TIMES = frozenset(("start", "end"))


def _touch(obj) -> None:
    LOG.append(obj)
    if len(LOG) > _LOG_CAP:
        _trim()


def _trim() -> None:
    """Drop what every reader has read; if one lags far behind, drop it all
    and let the laggards start over."""
    end = LOG_AT[0] + len(LOG)
    least = min((r.pos for r in _READERS if r.doc is not None), default=end)
    cut = least - LOG_AT[0]
    if cut < len(LOG) // 2:
        cut = len(LOG)
    del LOG[:cut]
    LOG_AT[0] += cut


class Changes:
    """Which lines of a document changed since this reader last asked."""

    def __init__(self) -> None:
        self.doc = None
        self.pos = 0
        self.shape = -1
        _READERS.add(self)

    def take(self, doc) -> tuple[bool, list, bool]:
        """(start over?, objects changed since, lost track?): start over for
        another document, a change of text or shape, or a reader so far
        behind that the log no longer reaches back to it."""
        end = LOG_AT[0] + len(LOG)
        lost = self.pos < LOG_AT[0]
        fresh = lost or doc is not self.doc or self.shape != SHAPE[0]
        objs = [] if lost else LOG[self.pos - LOG_AT[0]:]
        self.doc, self.shape, self.pos = doc, SHAPE[0], end
        return fresh, objs, lost

    def lines(self, doc) -> set | None:
        """The indices of the lines changed since the last ask, or None:
        start over."""
        fresh, objs, _lost = self.take(doc)
        if fresh:
            return None
        own = owners(doc)
        out = set()
        for o in objs:
            got = own.get(id(o))
            if got is not None and got[0] is o:
                out.add(got[1])
        return out


_OWN: list = [None, -1, {}]


def owners(doc) -> dict:
    """id -> (object, line index) for everything in `doc`'s lines; kept
    until the text or shape of anything changes."""
    if _OWN[0] is doc and _OWN[1] == SHAPE[0]:
        return _OWN[2]
    m = {}
    for i, ln in enumerate(doc.lines):
        m[id(ln)] = (ln, i)
        m[id(ln.bg)] = (ln.bg, i)
        for g in ln.groups():
            m[id(g)] = (g, i)
            m[id(g.syls)] = (g.syls, i)
            for x in g.syls:
                m[id(x)] = (x, i)
    _OWN[:] = [doc, SHAPE[0], m]
    return m


def rev() -> int:
    return REV[0]


def shape_rev() -> int:
    return SHAPE[0]


@dataclass
class Syl(_Rev):
    """One sung piece of text, and when it was sung.

    `part` is the join to the NEXT syllable: True means no space between them,
    which is how a word is spelled out of several timed pieces.
    """
    text: str
    start: float | None = None
    end: float | None = None
    part: bool = False
    roman: str = ""

    @property
    def timed(self) -> bool:
        return self.start is not None


@dataclass
class Group(_Rev):
    """One voice inside a line: the lead, or one backing run. `lead_in` marks a
    backing run sung before the words it answers (BG_LEAD in the player)."""
    syls: list[Syl] = field(default_factory=list)
    lead_in: bool = False
    roman: str = ""

    def roman_text_of_syls(self) -> str:
        """The syllables' readings alone, joined the way the words are."""
        if not any(s.roman.strip() for s in self.syls):
            return ""
        return SL.join_readings([s.text for s in self.syls],
                                [s.roman for s in self.syls],
                                [s.part for s in self.syls])

    def roman_text(self) -> str:
        """How the whole group is read: its own per-line reading if it has
        one, else its syllables' readings joined the way the words are."""
        return self.roman.strip() or self.roman_text_of_syls()

    def text(self) -> str:
        out = ""
        for s in self.syls:
            out += s.text if s.part else s.text.strip() + " "
        return out.strip()

    def span(self) -> tuple[float | None, float | None]:
        lo = hi = None
        for s in self.syls:
            a = s.start
            if a is None:
                continue
            e = s.end if s.end is not None else a
            if lo is None or a < lo:
                lo = a
            if hi is None or e > hi:
                hi = e
        return lo, hi

    def words(self) -> list[list[int]]:
        """Syllable indices, grouped into the words they spell."""
        out, cur = [], []
        for i, s in enumerate(self.syls):
            cur.append(i)
            if not s.part:
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        return out

    def word_text(self, w: list[int]) -> str:
        return "".join(self.syls[i].text for i in w)


@dataclass
class Line(_Rev):
    """One <p>: a lead voice, its backing voices, and which side it sits on."""
    lead: Group = field(default_factory=Group)
    bg: list[Group] = field(default_factory=list)
    agent: str = "v1"
    start: float | None = None
    end: float | None = None
    # Which line this is in a shared session (collab.py), however it moves
    # about. Never written to the file, and not part of what a line IS:
    # two lines with the same words and times are equal whatever it says.
    uid: str = field(default_factory=lambda: new_uid(), compare=False)

    def text(self) -> str:
        return self.lead.text()

    def span(self) -> tuple[float | None, float | None]:
        """When this line sounds, counting every voice drawn inside it."""
        lo, hi = self.lead.span()
        for g in self.bg:
            gs, ge = g.span()
            if gs is not None and (lo is None or gs < lo):
                lo = gs
            if ge is not None and (hi is None or ge > hi):
                hi = ge
        if lo is None:
            return self.start, self.end
        return lo, hi

    @property
    def timed(self) -> bool:
        return self.span()[0] is not None

    def groups(self) -> list[Group]:
        return [self.lead] + list(self.bg)


@dataclass
class Doc(_Rev):
    """A whole lyric: the lines and the file's song info. `parts` are
    timed-together runs kept as word keys per line, never line numbers;
    editor-only."""
    lines: list[Line] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    parts: list = field(default_factory=list)

    def clone(self) -> "Doc":
        """An independent copy, built field by field (ten times faster than
        deepcopy); falls back to deepcopy if a field is missing from
        `_CLONED`."""
        if not _CLONE_OK:
            return copy.deepcopy(self)
        return _bare(Doc, lines=_Tracked([_line(ln) for ln in self.lines]),
                     meta=copy.deepcopy(self.meta),
                     parts=_Tracked(self.parts))

    # ----------------------------------------------------------- addressing
    def group(self, idx: int, voice: int) -> Group | None:
        """Voice 0 is the lead; 1.. are the backing runs, in order."""
        if not 0 <= idx < len(self.lines):
            return None
        gs = self.lines[idx].groups()
        return gs[voice] if 0 <= voice < len(gs) else None

    def timed_lines(self) -> int:
        return sum(1 for ln in self.lines if ln.timed)

    def duration(self) -> float:
        ends = [ln.span()[1] for ln in self.lines if ln.span()[1] is not None]
        return max(ends) if ends else 0.0


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def from_body(body) -> Doc:
    """A Spicy Lyrics / parsed-TTML document as something editable."""
    doc = SL.payload(body or {})
    lines = []
    for item in LS._items(doc):
        if not isinstance(item, dict):
            continue
        ln = Line()
        lead = item.get("Lead")
        if isinstance(lead, dict) and lead.get("Syllables"):
            ln.lead = _group_in(lead)
        else:
            ln.lead = Group([Syl(w) for w in words_in(_clean_line(item.get("Text")))])
        for src in (lead if isinstance(lead, dict) else None, item):
            said = (src or {}).get("TransliteratedText")
            if isinstance(said, str) and said.strip() and not ln.lead.roman:
                ln.lead.roman = said.strip()
        bg = item.get("Background")
        lead_at = ln.lead.span()[0]
        for g in (bg if isinstance(bg, list) else
                  ([bg] if isinstance(bg, dict) else [])):
            if isinstance(g, dict) and (g.get("Syllables") or g.get("Text")):
                ln.bg.append(_group_in(g, lead_at))
        ln.agent = "v2" if item.get("OppositeAligned") else "v1"
        for src in (item.get("Lead") if isinstance(item.get("Lead"), dict) else None,
                    item):
            if isinstance(src, dict):
                if isinstance(src.get("StartTime"), (int, float)):
                    ln.start = float(src["StartTime"])
                if isinstance(src.get("EndTime"), (int, float)):
                    ln.end = float(src["EndTime"])
        for g in ln.groups():
            if g.roman and _squash(g.roman) == _squash(g.roman_text_of_syls()):
                g.roman = ""
        if ln.lead.syls or ln.bg:
            lines.append(ln)
    meta = {k: doc.get(k) for k in
            ("SongWriters", "LanguageISO2", "Language", "id", "SyncedBy",
             "source", "Title", "Artist", "Album")
            if doc.get(k) is not None}
    if doc.get("_maker") and not meta.get("SyncedBy"):
        meta["SyncedBy"] = doc["_maker"]
    return Doc(lines, meta)


ZWSP = SL.ZWSP


def _squash(text) -> str:
    """A reading as it compares: without spaces, which are only how it was
    written down -- a file from another tool spaces a line differently and
    it is still the same reading of it."""
    return "".join(str(text or "").split()).casefold()

TAIL_MARKS = "?!:;»"
HEAD_MARKS = "«"
_TAIL = re.compile("^[" + re.escape(TAIL_MARKS) + "]")
_HEAD = re.compile("[" + re.escape(HEAD_MARKS) + "]$")
_WORDY = re.compile(r"[^\W_]", re.UNICODE)


def is_tail(bit: str) -> bool:
    """Nothing but punctuation French would space away from the word before."""
    bit = bit or ""
    return bool(_TAIL.match(bit)) and not _WORDY.search(bit)


def is_head(bit: str) -> bool:
    """Nothing but punctuation French would space away from the word after."""
    bit = bit or ""
    return bool(_HEAD.search(bit)) and not _WORDY.search(bit)


def words_in(text) -> list[str]:
    """`text` in words, keeping French's spaced punctuation on its word.

    The space is kept exactly as it was typed rather than normalised: where a
    writer used a no-break space, the mark stays unable to wrap away from its
    word, and where they used a plain one nothing has been decided for them.
    """
    out: list[str] = []
    gap = ""
    for i, bit in enumerate(re.split(r"(\s+)", str(text or "").strip())):
        if i % 2:
            gap = bit
        elif not bit:
            continue
        elif out and (is_tail(bit) or is_head(out[-1])):
            out[-1] += gap + bit
        else:
            out.append(bit)
    return out


def _clean(text) -> str:
    """A syllable's text without invisible characters, by the player's own
    rule."""
    return SL._trim(text)


def _clean_line(text) -> str:
    """A whole line of it, where a zero-width space stands in for a real one."""
    return SL.unzwsp(text, True).strip()


def _group_in(g: dict, lead_at: float | None = None) -> Group:
    raw = [y for y in g.get("Syllables") or [] if isinstance(y, dict)]
    syls = []
    for i, y in enumerate(raw):
        s = y.get("StartTime")
        e = y.get("EndTime")
        nxt = raw[i + 1].get("Text", "") if i + 1 < len(raw) else ""
        part = bool(y.get("IsPartOfWord")) and not SL.word_ends(y.get("Text", ""), nxt)
        rom = y.get("TransliteratedText")
        syls.append(Syl(_clean(y.get("Text")),
                        float(s) if isinstance(s, (int, float)) else None,
                        float(e) if isinstance(e, (int, float)) else None,
                        part, _clean(rom) if isinstance(rom, str) else ""))
    if not syls and str(g.get("Text") or "").strip():
        syls = [Syl(w) for w in words_in(_clean_line(g["Text"]))]
    if syls:
        syls[-1].part = False
    got = Group(syls)
    said = g.get("TransliteratedText")
    if isinstance(said, str) and said.strip():
        got.roman = said.strip()
    first = next((s.start for s in syls if s.timed), None)
    if lead_at is not None and first is not None:
        got.lead_in = first < lead_at - SL.BG_LEAD
    elif first is None:
        got.lead_in = bool(g.get("LeadIn"))
    return got


def to_body(doc: Doc, readings: bool = True) -> dict:
    """The editable document back in the shape the player and renderer read.
    `readings` False leaves every romanisation out."""
    items = []
    for ln in doc.lines:
        item: dict = {"Text": ln.text()}
        if readings and ln.lead.roman.strip():
            item["TransliteratedText"] = ln.lead.roman.strip()
        if ln.lead.syls:
            item["Lead"] = _group_out(ln.lead, readings)
        elif ln.start is not None:
            item["Lead"] = {"Syllables": [], "StartTime": ln.start,
                            "EndTime": ln.end}
        ls, le = ln.span()
        if ls is not None:
            item["StartTime"] = ls
        if le is not None:
            item["EndTime"] = le
        if ln.bg:
            out = [_group_out(g, readings) for g in ln.bg if g.syls]
            if out:
                item["Background"] = out
        if ln.agent != "v1":
            item["OppositeAligned"] = True
        items.append(item)
    word = any(isinstance(y.get("StartTime"), (int, float))
               for i in items
               for y in ((i.get("Lead") or {}).get("Syllables") or []))
    line = any("StartTime" in i for i in items)
    body = dict(doc.meta)
    body["Content"] = items
    body["Type"] = "Syllable" if word else ("Line" if line else "Static")
    return body


def _group_out(g: Group, readings: bool = True) -> dict:
    syls = []
    for s in g.syls:
        y: dict = {"Text": _clean(s.text), "IsPartOfWord": bool(s.part)}
        if readings and s.roman.strip():
            y["TransliteratedText"] = _clean(s.roman)
        if s.timed:
            y["StartTime"] = float(s.start)
            y["EndTime"] = float(s.end if s.end is not None else s.start)
        syls.append(y)
    out: dict = {"Syllables": syls}
    if readings and g.roman.strip():
        out["TransliteratedText"] = g.roman.strip()
    a, b = g.span()
    if a is not None:
        out["StartTime"], out["EndTime"] = a, b
    elif g.lead_in:
        out["LeadIn"] = True
    return out


def timed_only(doc: Doc) -> Doc:
    """The document as the player can draw it: only the timed lines. The editor
    itself keeps every line."""
    # Built whole, not appended to: an append is a change to a document,
    # and every view would think the song had been edited.
    return Doc([Line(ln.lead, [g for g in ln.bg if g.span()[0] is not None],
                     ln.agent, ln.start, ln.end)
                for ln in doc.lines if ln.span()[0] is not None],
               dict(doc.meta))


def to_ttml(doc: Doc) -> str:
    return SL.render_ttml(to_body(doc), True)


def from_ttml(xml: str) -> Doc | None:
    body = LS.parse_ttml(xml)
    return from_body(body) if body else None


def from_text(text: str) -> Doc:
    """Plain pasted lyrics as an untimed document: `>` is the answering voice,
    end brackets are backing vocals, a brackets-only row is the line above's
    ad-lib."""
    lines = []
    for row in text.replace("\r\n", "\n").split("\n"):
        ln = parse_row(row)
        if ln is None:
            continue
        if not ln.lead.syls and lines:
            under(lines[-1], ln.bg)
        else:
            lines.append(ln)
    return Doc(lines)


def parse_row(row: str) -> Line | None:
    """One row of the text tab as a line, or None for a blank one. A row of
    brackets alone comes back with no lead: what it belongs to is the
    caller's to say."""
    row = row.strip()
    if not row:
        return None
    agent = "v1"
    if row.startswith(">"):
        agent, row = "v2", row[1:].strip()
    lead, head, bgs = _peel_backing(_clean_line(row))
    ln = Line(Group([Syl(_clean(w)) for w in words_in(lead)]), agent=agent)
    for b in head:
        ln.bg.append(Group([Syl(_clean(w)) for w in words_in(b)],
                           lead_in=True))
    for b in bgs:
        ln.bg.append(Group([Syl(_clean(w)) for w in words_in(b)]))
    return ln if ln.lead.syls or ln.bg else None


def under(ln: Line, bgs: list) -> None:
    """Backing voices from a row of their own, onto the line they answer:
    after its words, which is where a row underneath sounds."""
    for g in bgs:
        g.lead_in = False
        ln.bg.append(g)
    lo, hi = ln.span()
    if lo is not None:
        ln.start, ln.end = lo, hi


def text_row(ln: Line) -> str:
    """One line as the text tab writes it -- see from_text for the rules."""
    row = ln.text()
    for g in ln.bg:
        piece = f"({g.text()})"
        row = (piece + " " + row) if g.lead_in else (
            (row + " " if row else "") + piece)
    return (">" if ln.agent != "v1" else "") + row


def as_text(doc: Doc) -> str:
    """The document as the text tab shows it -- see from_text for the rules."""
    return "\n".join(text_row(ln) for ln in doc.lines)


PAIRS = {"(": ")", "（": "）"}


def _peel_backing(row: str) -> tuple[str, list[str], list[str]]:
    """Split a line into (lead, ad-libs before, ad-libs after); brackets at
    either end count, one in the middle is left alone."""
    lead, head = row.strip(), []
    while lead.startswith(("(", "（")):
        opening = lead[0]
        close = PAIRS[opening]
        depth, cut = 0, -1
        for i, ch in enumerate(lead):
            if ch == opening:
                depth += 1
            elif ch == close:
                depth -= 1
                if depth == 0:
                    cut = i
                    break
        if cut < 0 or not lead[cut + 1:].strip():
            break
        inner = lead[1:cut].strip()
        if not inner:
            break
        head.append(inner)
        lead = lead[cut + 1:].strip()
    bgs = []
    while lead.endswith((")", "）")):
        close = lead[-1]
        opening = "(" if close == ")" else "（"
        depth, cut = 0, -1
        for i in range(len(lead) - 1, -1, -1):
            if lead[i] == close:
                depth += 1
            elif lead[i] == opening:
                depth -= 1
                if depth == 0:
                    cut = i
                    break
        if cut < 0:
            break
        inner = lead[cut + 1:-1].strip()
        if not inner:
            break
        bgs.insert(0, inner)
        lead = lead[:cut].rstrip()
    return lead, head, bgs


_CLONED = {Syl: ("text", "start", "end", "part", "roman"),
           Group: ("syls", "lead_in", "roman"),
           Line: ("lead", "bg", "agent", "start", "end", "uid"),
           Doc: ("lines", "meta", "parts")}
_CLONE_OK = all(tuple(f.name for f in fields(cls)) == names
                for cls, names in _CLONED.items())


def _bare(cls, **kv):
    """`cls` filled in without __init__ or _Rev.__setattr__: clone() makes
    tens of thousands per edit on a long song, none of them in a document."""
    obj = object.__new__(cls)
    obj.__dict__.update(kv)
    return obj


def _syl(s: Syl) -> Syl:
    return _bare(Syl, text=s.text, start=s.start, end=s.end, part=s.part,
                 roman=s.roman)


def _group(g: Group) -> Group:
    return _bare(Group, syls=_Tracked([_syl(s) for s in g.syls]),
                 lead_in=g.lead_in, roman=g.roman)


def _line(ln: Line) -> Line:
    return _bare(Line, lead=_group(ln.lead),
                 bg=_Tracked([_group(g) for g in ln.bg]), agent=ln.agent,
                 start=ln.start, end=ln.end, uid=ln.uid)


# The live line -> its copy in the last snapshot(), by id (holding the line).
_COPIES: dict = {}


def _untouched(ln: Line, t: dict) -> bool:
    if id(ln) in t or id(ln.bg) in t:
        return False
    for g in ln.groups():
        if id(g) in t or id(g.syls) in t:
            return False
        for s in g.syls:
            if id(s) in t:
                return False
    return True


_SNAP = None                    # the Changes reader snapshot() keeps


def snapshot(doc: Doc) -> Doc:
    """A copy for the undo stack, sharing with the last one every line not
    changed since. Never edit it: history.take() unshares it first."""
    global _SNAP
    if _SNAP is None:
        _SNAP = Changes()
    fresh, objs, lost = _SNAP.take(doc)
    if lost:
        _COPIES.clear()
    if not fresh and _LAST[0] is doc and len(_LAST[1]) == len(doc.lines):
        # Only timings moved, and the lines are the ones the last snapshot
        # had, in order: its list again, with the changed lines recopied.
        lines = list(_LAST[1])
        for i in lines_of(doc, objs):
            ln = doc.lines[i]
            got = _COPIES[id(ln)] = (ln, _line(ln))
            lines[i] = got[1]
    else:
        lines, kept, copies = [], {}, _COPIES
        t = {id(o): o for o in objs}
        for ln in doc.lines:
            got = copies.get(id(ln))
            if got is None or got[0] is not ln or not _untouched(ln, t):
                got = (ln, _line(ln))
            kept[id(ln)] = got
            lines.append(got[1])
        _COPIES.clear()
        _COPIES.update(kept)
    _LAST[:] = [doc, lines]
    snap = _bare(Doc, lines=_Tracked(lines), meta=copy.deepcopy(doc.meta),
                 parts=_Tracked(doc.parts))
    # What restore_times needs: whose it is, its shape, its place in the log.
    snap.__dict__.update(_shared=True, _of=doc, _shape=SHAPE[0],
                         _at=LOG_AT[0] + len(LOG))
    return snap


_LAST: list = [None, []]        # the last snapshot's document and lines


def lines_of(doc, objs) -> set:
    """The indices of `doc`'s lines that hold any of `objs`."""
    own, out = owners(doc), set()
    for o in objs:
        got = own.get(id(o))
        if got is not None and got[0] is o:
            out.add(got[1])
    return out


def times_only_since(doc, snap) -> set | None:
    """The lines whose times are all that changed in `doc` since `snap`
    (a snapshot of it) was taken, or None when anything else did."""
    d = snap.__dict__
    at = d.get("_at")
    if (not d.get("_shared") or d.get("_later") or d.get("_of") is not doc
            or d.get("_shape") != SHAPE[0] or at is None or at < LOG_AT[0]
            or len(snap.lines) != len(doc.lines) or snap.meta != doc.meta):
        return None
    return lines_of(doc, LOG[at - LOG_AT[0]:])


def copy_times(src: Line, dst: Line) -> None:
    """dst's times set to src's, where they differ; same shape assumed."""
    if dst.start != src.start:
        dst.start = src.start
    if dst.end != src.end:
        dst.end = src.end
    for gs, gd in zip(src.groups(), dst.groups()):
        for a, b in zip(gs.syls, gd.syls):
            if b.start != a.start:
                b.start = a.start
            if b.end != a.end:
                b.end = a.end


def unshare(doc: Doc) -> Doc:
    """A snapshot()'s lines made its own, in place, so it can be edited."""
    if doc.__dict__.pop("_shared", False):
        object.__setattr__(doc, "lines",
                           _Tracked([_line(ln) for ln in doc.lines]))
    for k in ("_of", "_shape", "_at"):
        doc.__dict__.pop(k, None)
    return doc


def new_uid() -> str:
    return secrets.token_hex(6)


def ensure_unique(doc: Doc) -> int:
    """Give every line that shares a uid with an earlier one a fresh uid;
    returns how many were renamed."""
    seen, fixed = set(), 0
    for ln in doc.lines:
        if ln.uid in seen:
            ln.uid = new_uid()
            fixed += 1
        seen.add(ln.uid)
    return fixed


_READERS = weakref.WeakSet()
