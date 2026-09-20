"""The document being edited, and every operation that changes it.

The shape is the one the rest of the project already speaks -- a line holds a
Lead group of syllables and any number of Background groups, and a syllable
carries its text, its times and whether the next syllable is glued to it
(`part`, the document's IsPartOfWord). A *word* is not stored anywhere: it is
the maximal run of syllables joined by that flag, which is what makes
"split this word into syllables" a change to one flag rather than a change of
representation.

Nothing here knows about Qt, audio or the network, so the operations can be
tested on their own and the undo stack can be a plain list of snapshots.
"""
from __future__ import annotations

import copy
import pathlib
import re
import sys
from dataclasses import dataclass, field, replace

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "mild-lyrics", _HERE.parent)
                if str(p) not in sys.path]

import lyric_sources as LS      # noqa: E402
import spicy_lyrics as SL       # noqa: E402


# --------------------------------------------------------------------------
@dataclass
class Syl:
    """One sung piece of text, and when it was sung.

    `part` is the join to the NEXT syllable: True means no space between them,
    which is how a word is spelled out of several timed pieces.
    """
    text: str
    start: float | None = None
    end: float | None = None
    part: bool = False

    @property
    def timed(self) -> bool:
        return self.start is not None


@dataclass
class Group:
    """One voice inside a line: the lead, or one backing run.

    `lead_in` marks a backing run that comes in BEFORE the words it answers --
    "(Promise I like it like—) Promise I like it like that". The player
    already reads those first (spicy_lyrics.timeline, BG_LEAD), so the editor
    has to remember which they are or a round trip through the text tab would
    move the ad-lib to the end of the line it opens.
    """
    syls: list[Syl] = field(default_factory=list)
    lead_in: bool = False

    def text(self) -> str:
        out = ""
        for s in self.syls:
            out += s.text if s.part else s.text.strip() + " "
        return out.strip()

    def span(self) -> tuple[float | None, float | None]:
        times = [s for s in self.syls if s.timed]
        if not times:
            return None, None
        return (min(s.start for s in times),
                max((s.end if s.end is not None else s.start) for s in times))

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
class Line:
    """One <p>: a lead voice, its backing voices, and which side it sits on."""
    lead: Group = field(default_factory=Group)
    bg: list[Group] = field(default_factory=list)
    agent: str = "v1"
    start: float | None = None
    end: float | None = None

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
class Doc:
    """A whole lyric: the lines, and what the file says about the song."""
    lines: list[Line] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def clone(self) -> "Doc":
        return copy.deepcopy(self)

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
    """A syllable's text, without the invisible characters.

    A zero-width space does nothing a reader can see and everything a reader
    cannot: it survives copy and paste, it defeats a word match, and it turns
    up in files nobody put it in. Out it goes.

    The player's own rule, borrowed rather than copied, so a document cannot
    read one way here and another way there.
    """
    return SL._trim(text)


def _clean_line(text) -> str:
    """A whole line of it, where a zero-width space stands in for a real one.

    A line is written with spaces already, so one that is invisible is there
    to hold two words apart -- unlike inside a syllable, where the same mark
    is glue. `SL.unzwsp` knows the difference; it just has to be told which
    of the two it is looking at.
    """
    return SL.unzwsp(text, True).strip()


def _group_in(g: dict, lead_at: float | None = None) -> Group:
    raw = [y for y in g.get("Syllables") or [] if isinstance(y, dict)]
    syls = []
    for i, y in enumerate(raw):
        s = y.get("StartTime")
        e = y.get("EndTime")
        nxt = raw[i + 1].get("Text", "") if i + 1 < len(raw) else ""
        part = bool(y.get("IsPartOfWord")) and not SL.word_ends(y.get("Text", ""), nxt)
        syls.append(Syl(_clean(y.get("Text")),
                        float(s) if isinstance(s, (int, float)) else None,
                        float(e) if isinstance(e, (int, float)) else None,
                        part))
    if not syls and str(g.get("Text") or "").strip():
        syls = [Syl(w) for w in words_in(_clean_line(g["Text"]))]
    if syls:
        syls[-1].part = False
    got = Group(syls)
    first = next((s.start for s in syls if s.timed), None)
    if lead_at is not None and first is not None:
        got.lead_in = first < lead_at - SL.BG_LEAD
    elif first is None:
        got.lead_in = bool(g.get("LeadIn"))
    return got


def to_body(doc: Doc) -> dict:
    """The editable document back in the shape the player and renderer read."""
    items = []
    for ln in doc.lines:
        item: dict = {"Text": ln.text()}
        if ln.lead.syls:
            item["Lead"] = _group_out(ln.lead)
        elif ln.start is not None:
            item["Lead"] = {"Syllables": [], "StartTime": ln.start,
                            "EndTime": ln.end}
        ls, le = ln.span()
        if ls is not None:
            item["StartTime"] = ls
        if le is not None:
            item["EndTime"] = le
        if ln.bg:
            out = [_group_out(g) for g in ln.bg if g.syls]
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


def _group_out(g: Group) -> dict:
    syls = []
    for s in g.syls:
        y: dict = {"Text": _clean(s.text), "IsPartOfWord": bool(s.part)}
        if s.timed:
            y["StartTime"] = float(s.start)
            y["EndTime"] = float(s.end if s.end is not None else s.start)
        syls.append(y)
    out: dict = {"Syllables": syls}
    a, b = g.span()
    if a is not None:
        out["StartTime"], out["EndTime"] = a, b
    elif g.lead_in:
        out["LeadIn"] = True
    return out


def timed_only(doc: Doc) -> Doc:
    """The document as the player can actually draw it.

    A player sweeps syllables; a line with no times has nothing to sweep, and
    a document where NOTHING has times is not a lyric being timed but a block
    of static text -- which is what the reader got, because that is what the
    file said. So the untimed lines are held back until they have times, and
    what goes over is a document that is entirely synced, however little of it
    there is yet.

    Not a filter on the way out of the editor: the editor keeps every line,
    timed or not. This is only what the player is shown.
    """
    out = Doc([], dict(doc.meta))
    for ln in doc.lines:
        if ln.span()[0] is None:
            continue
        keep = Line(ln.lead, [g for g in ln.bg if g.span()[0] is not None],
                    ln.agent, ln.start, ln.end)
        out.lines.append(keep)
    return out


def to_ttml(doc: Doc) -> str:
    return SL.render_ttml(to_body(doc), True)


def from_ttml(xml: str) -> Doc | None:
    body = LS.parse_ttml(xml)
    return from_body(body) if body else None


def from_text(text: str) -> Doc:
    """Plain pasted lyrics as an untimed document.

    The two conventions the editor writes are read back here so a round trip
    through the text tab keeps what the timing tab knows: a line beginning
    `>` is the answering voice, and a trailing (parenthesised) run is a
    backing vocal rather than words the lead sings.
    """
    lines = []
    for row in text.replace("\r\n", "\n").split("\n"):
        row = row.strip()
        if not row:
            continue
        agent = "v1"
        if row.startswith(">"):
            agent, row = "v2", row[1:].strip()
        lead, head, bgs = _peel_backing(_clean_line(row))
        ln = Line(Group([Syl(_clean(w)) for w in words_in(lead)]),
                  agent=agent)
        for b in head:
            ln.bg.append(Group([Syl(_clean(w)) for w in words_in(b)],
                               lead_in=True))
        for b in bgs:
            ln.bg.append(Group([Syl(_clean(w)) for w in words_in(b)]))
        if ln.lead.syls or ln.bg:
            lines.append(ln)
    return Doc(lines)


def as_text(doc: Doc) -> str:
    """The document as the text tab shows it -- see from_text for the rules."""
    rows = []
    for ln in doc.lines:
        row = ln.text()
        for g in ln.bg:
            piece = f"({g.text()})"
            row = (piece + " " + row) if g.lead_in else (
                (row + " " if row else "") + piece)
        rows.append((">" if ln.agent != "v1" else "") + row)
    return "\n".join(rows)


PAIRS = {"(": ")", "（": "）"}


def _peel_backing(row: str) -> tuple[str, list[str], list[str]]:
    """Split a line into (lead, ad-libs before it, ad-libs after it).

    Both ends, not just the trailing one. Genius writes an answering voice at
    whichever end it sounds -- "(Promise I like it like—) Promise I like it
    like that" is 21 lines of one song -- and taking only the trailing ones
    left those ad-libs sitting inside the lead, sung by the wrong voice.

    A bracket in the MIDDLE is still left alone: there it is far more often
    part of the lyric than an ad-lib, and a wrong guess silently moves words
    out of the line the singer sings.
    """
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
