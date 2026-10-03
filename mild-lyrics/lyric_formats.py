"""Lyric file formats other than TTML: written by the TTML Editor's Save menu,
read by the player when one is dropped on its window and by the editor's Open.

Everything here speaks the document both programs already pass between them
-- the Spicy Lyrics shape, a "Content" list of items with a Lead group of
Syllables and any Background groups -- so a format is one writer and one
reader, and neither program needs to know the formats exist.

    format   timing      backing vocals              duets
    LRC      line        inline, in brackets         --
    ELRC     word (A2)   inline, in brackets         --
    SRT      line        inline, in brackets         --
    ASS      word (\\k)   a Dialogue of their own     the Name field, v1/v2
    KRC      word        inline, in brackets         --
    QRC      word        inline, in brackets         --
    YRC      word        inline, in brackets         --
    LYS      word        a line of their own         the line's property
    TXT      none        inline, in brackets         --

"Inline, in brackets" is how those formats' own apps write a backing vocal,
and how every reader here (and the KRC/QRC/YRC sources in lyric_sources)
lifts one back out: see lyric_sources._ne_bg. Where a format has a place of
its own for one, the brackets are a choice -- `parens` -- as they are for
TTML, whose reader peels Apple's "(For" ... "you)" back off (_unwrap).

A line with no times at all has nowhere to go in a format that is nothing
but times; writers leave those out and say how many.
"""
from __future__ import annotations

import base64
import copy
import html
import pathlib
import re

import lyric_sources as LS
import spicy_lyrics as SL

# key, menu label, file suffix, what it is
FORMATS = [
    ("lrc", "LRC", ".lrc", "Line-timed, read by almost every player."),
    ("elrc", "Enhanced LRC", ".lrc", "LRC with a time on every word (A2)."),
    ("ass", "ASS", ".ass", "Karaoke subtitles: \\k per syllable, for "
     "Aegisub, mpv and ffmpeg."),
    ("krc", "KRC", ".krc", "Kugou's word-timed lyric, as plain text."),
    ("qrc", "QRC", ".qrc", "QQ Music's word-timed lyric, as plain text."),
    ("yrc", "YRC", ".yrc", "NetEase's word-timed lyric."),
    ("lys", "LYS", ".lys", "Lyricify Syllable: word-timed, with backing "
     "vocals and duet sides."),
    ("srt", "SRT", ".srt", "Line-timed subtitles."),
    ("txt", "Plain text", ".txt", "The words alone."),
]
SUFFIX = {k: ext for k, _l, ext, _w in FORMATS}
LABEL = {k: label for k, label, _e, _w in FORMATS}

# What the player and the editor take when one is dropped or opened.
READS = (".ttml", ".xml", ".lrc", ".elrc", ".ass", ".ssa", ".krc", ".qrc",
         ".yrc", ".lys", ".srt", ".txt")

HEADS = (("Title", "ti"), ("Artist", "ar"), ("Album", "al"),
         ("SyncedBy", "by"))


# ------------------------------------------------------------ the document
def _items(body) -> list[dict]:
    doc = SL.payload(body or {})
    for k in ("Content", "Lines"):
        if isinstance(doc.get(k), list):
            return [i for i in doc[k] if isinstance(i, dict)]
    return []


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _syls(group) -> list[dict]:
    return [y for y in (group or {}).get("Syllables") or [] if isinstance(y, dict)]


def _span(syls, group=None) -> tuple:
    starts = [_num(y.get("StartTime")) for y in syls]
    ends = [_num(y.get("EndTime")) or _num(y.get("StartTime")) for y in syls]
    starts = [t for t in starts if t is not None]
    ends = [t for t in ends if t is not None]
    if starts:
        return min(starts), max(ends)
    g = group or {}
    return _num(g.get("StartTime")), _num(g.get("EndTime"))


def _tokens(group, text: str = "", at=(None, None)):
    """A voice as (text, start, end) pieces, the space after a word kept on
    it; or None where it has no times at all.

    One piece per syllable where every syllable is timed; one for the whole
    voice where only the voice is -- a line-timed document, or a line part
    way through being timed. A syllable is never given a time it was not
    given: the voice's span is the only time there is.
    """
    syls = _syls(group)
    if syls and all(_num(y.get("StartTime")) is not None for y in syls):
        out = []
        for i, y in enumerate(syls):
            word = SL._trim(str(y.get("Text") or ""))
            if not y.get("IsPartOfWord") and i < len(syls) - 1:
                word += " "
            s = _num(y["StartTime"])
            e = _num(y.get("EndTime"))
            out.append((word, s, e if e is not None and e >= s else s))
        return out
    words = SL.syllables_text(syls) if syls else SL._trim(text)
    s, e = _span(syls, group)
    if s is None:
        s, e = at
    if s is None or not words:
        return None
    return [(words, s, e if e is not None and e >= s else s)]


def _bracketed(toks):
    if not toks:
        return toks
    toks = list(toks)
    t, s, e = toks[0]
    toks[0] = ("(" + t, s, e)
    t, s, e = toks[-1]
    toks[-1] = (t.rstrip() + ")", s, e)
    return toks


class _Line:
    """One item, read the same way by every writer."""

    def __init__(self, item: dict) -> None:
        self.item = item
        lead = item.get("Lead") if isinstance(item.get("Lead"), dict) else {}
        self.text = SL.line_text(item)
        self.v2 = bool(item.get("OppositeAligned"))
        at = (_num(item.get("StartTime")), _num(item.get("EndTime")))
        self.lead = _tokens(lead, self.text, at) if (lead or self.text) else None
        self.lead_at = self.lead[0][1] if self.lead else None
        bg = item.get("Background")
        groups = bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else [])
        self.bg = []          # (tokens or None, text, comes first)
        for g in groups:
            if not isinstance(g, dict):
                continue
            words = (SL.syllables_text(_syls(g)) if _syls(g)
                     else SL._trim(str(g.get("Text") or "")))
            if not words:
                continue
            toks = _tokens(g, words)
            gs = toks[0][1] if toks else None
            first = bool(g.get("LeadIn")) or (
                gs is not None and self.lead_at is not None
                and gs < self.lead_at - SL.BG_LEAD)
            self.bg.append((toks, words, first))

    def timed(self) -> bool:
        return bool(self.lead) or any(t for t, _w, _f in self.bg)

    def inline(self) -> list | None:
        """Lead and backing vocals as one run of pieces, the backing ones in
        brackets, each where it sounds: before the words or after them."""
        if not self.timed():
            return None
        parts = [_bracketed(t) for t, _w, f in self.bg if f and t]
        parts.append(self.lead or [])
        parts += [_bracketed(t) for t, _w, f in self.bg if not f and t]
        out = []
        for p in parts:
            if not p:
                continue
            if out and not out[-1][0].endswith(" "):
                t, s, e = out[-1]
                out[-1] = (t + " ", s, e)
            out += p
        return out

    def inline_text(self) -> str:
        bits = [f"({w})" for _t, w, f in self.bg if f]
        bits.append(self.text)
        bits += [f"({w})" for _t, w, f in self.bg if not f]
        return " ".join(b for b in bits if b)

    def span(self) -> tuple:
        toks = self.inline() or []
        if not toks:
            return None, None
        return min(t[1] for t in toks), max(t[2] for t in toks)


def _lines(body) -> list[_Line]:
    return [_Line(i) for i in _items(body)]


def _ms(sec: float) -> int:
    return max(0, int(round(sec * 1000)))


def _head(body, tags=HEADS, extra: str = "") -> list[str]:
    doc = SL.payload(body or {})
    rows = []
    for key, tag in tags:
        v = doc.get(key)
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v if x)
        if v:
            rows.append(f"[{tag}:{SL._trim(str(v))}]")
    if extra:
        rows.append(extra)
    return rows


# ------------------------------------------------------------------ TTML
def ttml(body, compact: bool = False, parens: bool = False) -> str:
    """The document as TTML, as the editor has always written it -- or with
    the brackets Apple writes around a backing vocal's words, which every
    TTML reader here takes back off, and/or all on one line.

    One line is safe for the words: the only line breaks in it are between
    tags, and the space between two words is text INSIDE a <p>, never one."""
    if parens:
        body = copy.deepcopy(body)
        for item in _items(body):
            bg = item.get("Background")
            for g in bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else []):
                syls = _syls(g)
                if syls:
                    syls[0]["Text"] = "(" + SL._trim(str(syls[0].get("Text") or ""))
                    syls[-1]["Text"] = SL._trim(str(syls[-1].get("Text") or "")) + ")"
                elif isinstance(g.get("Text"), str) and g["Text"].strip():
                    g["Text"] = f"({g['Text'].strip()})"
    xml = SL.render_ttml(body, True)
    return re.sub(r">\s*\n\s*<", "><", xml) if compact else xml


# --------------------------------------------------------------- writers
def write(body, fmt: str, parens: bool = False) -> tuple:
    """(the file's contents and what had to be
    left out: {"lines": lines with no times, "adlibs": backing vocals with
    no times on lines that were written}). Neither is given a time it did
    not have; a format made of times has nowhere else to put them."""
    data, lines = _WRITERS[fmt](body, parens)
    adlibs = 0
    if fmt not in ("lrc", "srt", "txt"):
        adlibs = sum(1 for ln in _lines(body) if ln.timed()
                     for t, _w, _f in ln.bg if not t)
    return data, {"lines": lines, "adlibs": adlibs}


def left_out(said: dict) -> str:
    """What `write` left out, said in a few words; "" for nothing."""
    bits = []
    if said.get("lines"):
        n = said["lines"]
        bits.append(f"{n} untimed line{'' if n == 1 else 's'}")
    if said.get("adlibs"):
        n = said["adlibs"]
        bits.append(f"{n} untimed ad-lib{'' if n == 1 else 's'}")
    return " and ".join(bits)


def _ts(sec: float, brackets: str = "[]") -> str:
    """[mm:ss.xx], to the NEAREST hundredth: SL.ts drops the rest, which
    puts every time up to 10ms early."""
    cs = max(0, int(round(sec * 100)))
    return f"{brackets[0]}{cs // 6000:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}{brackets[1]}"


def _lrc(body, _parens) -> tuple:
    rows = _head(body)
    lines = _lines(body)
    for n, ln in enumerate(lines):
        s, e = ln.span()
        if s is None:
            rows.append(ln.inline_text())
            continue
        rows.append(_ts(s) + ln.inline_text())
        nxt = next((x.span()[0] for x in lines[n + 1:] if x.span()[0] is not None), None)
        # An empty stamp where the line stops and the next is a while off,
        # so a player clears it rather than holding it through the gap.
        if e is not None and (nxt is None or nxt - e >= 1.0):
            rows.append(_ts(e))
    return "\n".join(rows) + "\n", 0


def _elrc(body, _parens) -> tuple:
    rows = _head(body)
    for ln in _lines(body):
        toks = ln.inline()
        if not toks:
            rows.append(ln.inline_text())
            continue
        out = _ts(toks[0][1])
        for i, (t, s, e) in enumerate(toks):
            out += _ts(s, "<>") + t
            nxt = toks[i + 1][1] if i + 1 < len(toks) else None
            if nxt is None or abs(nxt - e) > 0.005:
                out += _ts(e, "<>")
        rows.append(out)
    return "\n".join(rows) + "\n", 0


def _srt_ts(sec: float) -> str:
    ms = _ms(sec)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _srt(body, _parens) -> tuple:
    out, n, skipped = [], 0, 0
    for ln in _lines(body):
        s, e = ln.span()
        if s is None:
            skipped += 1
            continue
        n += 1
        out.append(f"{n}\n{_srt_ts(s)} --> {_srt_ts(max(e, s + 0.5))}\n"
                   f"{ln.inline_text()}\n")
    return "\n".join(out), skipped


def _txt(body, _parens) -> tuple:
    return "\n".join(ln.inline_text() for ln in _lines(body)) + "\n", 0


def _ass_ts(sec: float) -> str:
    cs = max(0, int(round(sec * 100)))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_text(t: str) -> str:
    return t.replace("{", "(").replace("}", ")").replace("\n", " ")


def _karaoke(toks) -> str:
    """{\\k} per piece, in centiseconds from the line's start, with the gaps
    between pieces as {\\k} of nothing. Counted from absolute times rounded
    once each, so a long line does not drift by its rounding."""
    out, at = "", int(round(toks[0][1] * 100))
    for t, s, e in toks:
        cs, ce = int(round(s * 100)), int(round(e * 100))
        if cs > at:
            out += f"{{\\k{cs - at}}}"
            at = cs
        out += f"{{\\k{max(0, ce - at)}}}{_ass_text(t)}"
        at = max(at, ce)
    return out


ASS_HEAD = """[Script Info]
; Written by the Mild Lyrics TTML Editor
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080
{title}
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lead,Arial,64,&H00FFFFFF,&H80FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,1,80,80,140,1
Style: Duet,Arial,64,&H00FFFFFF,&H80FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,3,80,80,140,1
Style: Background,Arial,46,&H00FFFFFF,&H80FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,1,80,80,70,1
Style: Background Duet,Arial,46,&H00FFFFFF,&H80FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,3,80,80,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass(body, parens) -> tuple:
    doc = SL.payload(body or {})
    title = f"Title: {SL._trim(str(doc.get('Title')))}\n" if doc.get("Title") else ""
    rows, skipped = [], 0
    for ln in _lines(body):
        if not ln.timed():
            skipped += 1
            continue
        who = "v2" if ln.v2 else "v1"
        voices = []
        if ln.lead:
            voices.append(("Duet" if ln.v2 else "Lead", who, ln.lead))
        for toks, _w, _f in ln.bg:
            if toks:
                voices.append(("Background Duet" if ln.v2 else "Background",
                               who + "-bg", _bracketed(toks) if parens else toks))
        for style, name, toks in voices:
            s = min(t[1] for t in toks)
            e = max(t[2] for t in toks)
            rows.append(f"Dialogue: 0,{_ass_ts(s)},{_ass_ts(max(e, s + 0.01))},"
                        f"{style},{name},0,0,0,,{_karaoke(toks)}")
    return ASS_HEAD.format(title=title) + "\n".join(rows) + "\n", skipped


def _krc(body, _parens) -> tuple:
    rows, skipped = _head(body, extra="[offset:0]"), 0
    for ln in _lines(body):
        toks = ln.inline()
        if not toks:
            skipped += 1
            continue
        s = min(t[1] for t in toks)
        e = max(t[2] for t in toks)
        out = f"[{_ms(s)},{_ms(e) - _ms(s)}]"
        for t, ts_, te in toks:
            out += f"<{_ms(ts_) - _ms(s)},{_ms(te) - _ms(ts_)},0>{html.escape(t, quote=False)}"
        rows.append(out)
    return "\n".join(rows) + "\n", skipped


def _stamped(body, stamp, head=True) -> tuple:
    """QRC and YRC: [line start, length] and a stamp of absolute times for
    every piece -- after it in QRC, before it in YRC."""
    rows, skipped = (_head(body, extra="[offset:0]") if head else []), 0
    for ln in _lines(body):
        toks = ln.inline()
        if not toks:
            skipped += 1
            continue
        s = min(t[1] for t in toks)
        e = max(t[2] for t in toks)
        rows.append(f"[{_ms(s)},{_ms(e) - _ms(s)}]"
                    + "".join(stamp(t, _ms(a), _ms(b) - _ms(a)) for t, a, b in toks))
    return "\n".join(rows) + "\n", skipped


def _qrc(body, _parens) -> tuple:
    return _stamped(body, lambda t, a, d: f"{t}({a},{d})")


def _yrc(body, _parens) -> tuple:
    return _stamped(body, lambda t, a, d: f"({a},{d},0){t}", head=False)


def _lys(body, parens) -> tuple:
    """Lyricify Syllable. The property says two things: whether the line is a
    backing vocal (3-5 no, 6-8 yes) and its side (left, right, or not set
    where the song has no duet at all)."""
    lines = _lines(body)
    duet = any(ln.v2 for ln in lines)
    rows, skipped = _head(body), 0

    def side(ln, base):
        return base + (0 if not duet else (2 if ln.v2 else 1))

    def say(toks):
        return "".join(f"{t}({_ms(a)},{_ms(b) - _ms(a)})" for t, a, b in toks)

    for ln in lines:
        if not ln.timed():
            skipped += 1
            continue
        # Every backing line after the line it belongs to, even one sung
        # before it: that is the only order a reader can pair them up by.
        # Its times say where it sounds.
        if ln.lead:
            rows.append(f"[{side(ln, 3)}]" + say(ln.lead))
        for toks, _w, _f in ln.bg:
            if toks:
                rows.append(f"[{side(ln, 6)}]"
                            + say(_bracketed(toks) if parens else toks))
    return "\n".join(rows) + "\n", skipped


_WRITERS = {"lrc": _lrc, "elrc": _elrc, "srt": _srt, "txt": _txt,
            "ass": _ass, "krc": _krc, "qrc": _qrc, "yrc": _yrc, "lys": _lys}


# --------------------------------------------------------------- readers
def read(path) -> dict | None:
    """A lyric file from disk as a document, whichever of these it is; by its
    suffix, or by what is in it where the suffix says nothing."""
    p = pathlib.Path(path)
    raw = p.read_bytes()
    return read_bytes(raw, p.suffix.lower())


def read_bytes(raw: bytes, suffix: str = "") -> dict | None:
    if raw[:4] == b"krc1":
        text = _unkrc(raw)
        return _from_rows(_krc_rows(text), text) if text else None
    text = raw.decode("utf-8-sig", errors="replace")
    kind = _kind(text, suffix)
    if kind == "ttml":
        return LS.parse_ttml(text)
    if kind == "krc":
        return _from_rows(_krc_rows(text), text)
    if kind == "qrc":
        return _from_rows(_qrc_rows(_qrc_text(text)), text)
    if kind == "yrc":
        return _from_rows(_yrc_rows(text), text)
    if kind == "lys":
        return _read_lys(text)
    if kind == "ass":
        return _read_ass(text)
    if kind == "srt":
        return _read_srt(text)
    if kind == "lrc":
        return _read_lrc(text)
    return _read_txt(text)


STAMP_LINE = re.compile(r"^\[(\d+),(\d+)\]", re.M)


def _kind(text: str, suffix: str) -> str:
    s = text.lstrip()
    if suffix in (".ttml", ".xml") or s.startswith("<?xml") and "<tt" in s[:400] \
            or s.startswith("<tt"):
        return "ttml" if "QrcInfos" not in s[:400] else "qrc"
    if suffix in (".ass", ".ssa") or "[Script Info]" in s[:200] \
            or re.search(r"^Dialogue:", s, re.M):
        return "ass"
    if suffix in (".krc", ".qrc", ".yrc", ".lys", ".srt"):
        return suffix[1:]
    if suffix in (".elrc",):
        return "lrc"
    if STAMP_LINE.search(s):
        if re.search(r"<\d+,\d+,\d+>", s):
            return "krc"
        if re.search(r"\(\d+,\d+,\d+\)", s):
            return "yrc"
        return "qrc"
    if re.search(r"^\[\d\][^\]\n]*\(\d+,\d+\)", s, re.M):
        return "lys"
    if re.search(r"^\d+\s*\n\d+:\d+:\d+[,.]\d+\s*-->", s, re.M):
        return "srt"
    if LS.LRC_TAG.search(s):
        return "lrc"
    return "txt"


def _meta(text: str) -> dict:
    out = {}
    for key, tag in HEADS:
        m = re.search(rf"^\[{tag}:(.*?)\]\s*$", text, re.M)
        if m and m.group(1).strip():
            out[key] = m.group(1).strip()
    return out


def _syl(text: str, s: float, e: float) -> dict:
    got = text.rstrip()
    return {"Text": got, "StartTime": s, "EndTime": max(e, s),
            "IsPartOfWord": text == got}


def _item(pieces, line_at=None, line_end=None, v2: bool = False) -> dict | None:
    """One line of (text, start, end) pieces as an item, its bracketed
    pieces lifted out into backing vocals the way the sources lift them."""
    syls = []
    for text, s, e in pieces:
        if not text.strip():
            if syls:
                syls[-1]["IsPartOfWord"] = False
            continue
        if text != text.lstrip() and syls:
            syls[-1]["IsPartOfWord"] = False
        syls.append(_syl(text.lstrip(), s, e))
    if not syls:
        return None
    lead, bg = LS._ne_bg(syls, cap=False)
    if not lead:
        lead, bg = syls, []
    lead[-1] = {**lead[-1], "IsPartOfWord": False}
    ls = min(y["StartTime"] for y in lead)
    le = max(y["EndTime"] for y in lead)
    start = min([ls] + [g["StartTime"] for g in bg if "StartTime" in g])
    end = max([le] + [g["EndTime"] for g in bg if "EndTime" in g])
    if line_at is not None:
        start = min(start, line_at)
    if line_end is not None:
        end = max(end, line_end)
    item = {"Text": SL.syllables_text(lead), "StartTime": start, "EndTime": end,
            "Lead": {"StartTime": ls, "EndTime": le, "Syllables": lead}}
    if bg:
        item["Background"] = bg
    if v2:
        item["OppositeAligned"] = True
    return item


def _from_rows(rows, text: str) -> dict | None:
    items = [i for i in (_item(*r) for r in rows) if i]
    if not items:
        return None
    return {**_meta(text), "Type": "Syllable", "Content": items}


def _between(raw: str, start: int, stamps, before: bool):
    """Pieces of a line whose words sit between stamps: each stamp's word
    after it (KRC, YRC) or before it (QRC, LYS). Read between the stamps
    rather than matched as tokens, so a word may hold a bracket."""
    out = []
    stamps = list(stamps)
    for k, m in enumerate(stamps):
        if before:
            lo = stamps[k - 1].end() if k else start
            word = raw[lo:m.start()]
        else:
            hi = stamps[k + 1].start() if k + 1 < len(stamps) else len(raw)
            word = raw[m.end():hi]
        out.append((word, m))
    return out


def _unkrc(raw: bytes) -> str | None:
    return LS._krc(base64.b64encode(raw).decode("ascii"))


KRC_STAMP = re.compile(r"<(\d+),(\d+),\d+>")


def _krc_rows(text: str):
    for raw in text.splitlines():
        m = STAMP_LINE.match(raw.lstrip("\ufeff"))
        if not m:
            continue
        raw = raw.lstrip("\ufeff")
        at = int(m.group(1)) / 1000
        pieces = [(html.unescape(w), at + int(s.group(1)) / 1000,
                   at + (int(s.group(1)) + int(s.group(2))) / 1000)
                  for w, s in _between(raw, m.end(), KRC_STAMP.finditer(raw, m.end()), False)]
        yield pieces, at, at + int(m.group(2)) / 1000


QRC_STAMP = re.compile(r"\((\d+),(\d+)\)")


def _qrc_text(text: str) -> str:
    """QRC as it is found on disk: bare lines, the same inside QQ's XML
    envelope, or that envelope's hex payload."""
    m = re.search(r'LyricContent="(.*?)"\s*/>', text, re.S)
    if m:
        return html.unescape(m.group(1))
    s = text.strip()
    if s and re.fullmatch(r"[0-9A-Fa-f\s]+", s) and len(s) > 32:
        got = LS._qrc_here(re.sub(r"\s+", "", s)) or ""
        m = re.search(r'LyricContent="(.*?)"\s*/>', got, re.S)
        return html.unescape(m.group(1)) if m else got
    return text


def _qrc_rows(text: str):
    for raw in text.splitlines():
        m = STAMP_LINE.match(raw)
        if not m:
            continue
        pieces = [(w, int(s.group(1)) / 1000, (int(s.group(1)) + int(s.group(2))) / 1000)
                  for w, s in _between(raw, m.end(), QRC_STAMP.finditer(raw, m.end()), True)]
        at = int(m.group(1)) / 1000
        yield pieces, at, at + int(m.group(2)) / 1000


YRC_STAMP = re.compile(r"\((\d+),(\d+),\d+\)")


def _yrc_rows(text: str):
    for raw in text.splitlines():
        m = STAMP_LINE.match(raw)
        if not m:
            continue
        pieces = [(w, int(s.group(1)) / 1000, (int(s.group(1)) + int(s.group(2))) / 1000)
                  for w, s in _between(raw, m.end(), YRC_STAMP.finditer(raw, m.end()), False)]
        at = int(m.group(1)) / 1000
        yield pieces, at, at + int(m.group(2)) / 1000


LYS_LINE = re.compile(r"^\[(\d)\]")


def _read_lys(text: str) -> dict | None:
    items = []
    for raw in text.splitlines():
        m = LYS_LINE.match(raw)
        if not m:
            continue
        prop = int(m.group(1))
        pieces = [(w, int(s.group(1)) / 1000, (int(s.group(1)) + int(s.group(2))) / 1000)
                  for w, s in _between(raw, m.end(), QRC_STAMP.finditer(raw, m.end()), True)]
        syls = []
        for w, s, e in pieces:
            if not w.strip():
                if syls:
                    syls[-1]["IsPartOfWord"] = False
                continue
            syls.append(_syl(w, s, e))
        if not syls:
            continue
        syls[-1]["IsPartOfWord"] = False
        v2 = prop in (2, 5, 8)
        if prop >= 6:
            # A backing line belongs to the line above it.
            g = _bg_group(syls)
            if not items:
                items.append(_item_plain(syls, v2))
                continue
            host = items[-1]
            if g["StartTime"] < host["Lead"]["StartTime"] - SL.BG_LEAD:
                g["LeadIn"] = True
            host.setdefault("Background", []).append(g)
            continue
        items.append(_item_plain(syls, v2))
    for i in items:
        if i.get("Background"):
            i["StartTime"] = min([i["StartTime"]] + [g["StartTime"] for g in i["Background"]])
            i["EndTime"] = max([i["EndTime"]] + [g["EndTime"] for g in i["Background"]])
    if not items:
        return None
    return {**_meta(text), "Type": "Syllable", "Content": items}


def _bg_group(syls) -> dict:
    syls = LS._unwrap(syls)
    return {"Syllables": syls, "StartTime": min(y["StartTime"] for y in syls),
            "EndTime": max(y["EndTime"] for y in syls)}


def _item_plain(syls, v2: bool) -> dict:
    s = min(y["StartTime"] for y in syls)
    e = max(y["EndTime"] for y in syls)
    item = {"Text": SL.syllables_text(syls), "StartTime": s, "EndTime": e,
            "Lead": {"StartTime": s, "EndTime": e, "Syllables": syls}}
    if v2:
        item["OppositeAligned"] = True
    return item


ASS_TIME = re.compile(r"(\d+):(\d+):(\d+)[.:](\d+)")
ASS_K = re.compile(r"\\[kK][fo]?(\d+)")


def _ass_secs(t: str) -> float | None:
    m = ASS_TIME.match(t.strip())
    if not m:
        return None
    h, mi, s, frac = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(s) + int(frac) / (10 ** len(frac))


def _read_ass(text: str) -> dict | None:
    fields = None
    events = []
    for raw in text.splitlines():
        if raw.startswith("Format:") and fields is None and "Text" in raw \
                and "Start" in raw:
            fields = [f.strip() for f in raw[7:].split(",")]
        elif raw.startswith("Dialogue:"):
            if fields is None:
                fields = ["Layer", "Start", "End", "Style", "Name", "MarginL",
                          "MarginR", "MarginV", "Effect", "Text"]
            vals = raw[9:].split(",", len(fields) - 1)
            if len(vals) == len(fields):
                events.append(dict(zip(fields, (v.strip() if k != "Text" else v
                                                for k, v in zip(fields, vals)))))
    items = []
    for ev in events:
        s, e = _ass_secs(ev.get("Start", "")), _ass_secs(ev.get("End", ""))
        if s is None:
            continue
        style = ev.get("Style", "").lower()
        name = ev.get("Name", ev.get("Actor", "")).lower()
        bg = "bg" in name or "background" in style or "back" in name
        v2 = name.startswith("v2") or "duet" in style or "right" in style
        body = ev.get("Text", "").replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
        pieces, at, sung = [], s, False
        for m in re.finditer(r"\{([^}]*)\}([^{]*)", "{}" + body if not body.startswith("{") else body):
            k = ASS_K.search(m.group(1))
            word = m.group(2)
            if k:
                sung = True
                dur = int(k.group(1)) / 100
                if word:
                    pieces.append((word, at, at + dur))
                at += dur
            elif word:
                pieces.append((word, at, at))
        if not sung:
            words = re.sub(r"\{[^}]*\}", "", body).strip()
            if not words:
                continue
            item = {"Text": words, "StartTime": s, "EndTime": e if e else s}
            if v2:
                item["OppositeAligned"] = True
            if bg and items:
                items[-1].setdefault("Background", []).append(
                    {"Text": LS._unbracket(words), "StartTime": s, "EndTime": e})
            else:
                items.append(item)
            continue
        syls = []
        for w, a, b in pieces:
            if not w.strip():
                if syls:
                    syls[-1]["IsPartOfWord"] = False
                continue
            if w != w.lstrip() and syls:
                syls[-1]["IsPartOfWord"] = False
            syls.append(_syl(w.lstrip(), a, b))
        if not syls:
            continue
        syls[-1]["IsPartOfWord"] = False
        if bg:
            g = _bg_group(syls)
            # The line above it, as these files are written; a file whose
            # backing lines are elsewhere gets them on the nearest line.
            host = items[-1] if items else None
            if host is not None and g["StartTime"] > host.get("EndTime", 0) + 2.0:
                host = min(items, key=lambda i: abs(i.get("StartTime", 0)
                                                    - g["StartTime"]))
            if host is None:
                continue
            if "Lead" in host and g["StartTime"] < host["Lead"]["StartTime"] - SL.BG_LEAD:
                g["LeadIn"] = True
            host.setdefault("Background", []).append(g)
            host["StartTime"] = min(host["StartTime"], g["StartTime"])
            host["EndTime"] = max(host["EndTime"], g["EndTime"])
        else:
            item = _item_plain(syls, v2)
            item["EndTime"] = max(item["EndTime"], e or 0)
            items.append(item)
    if not items:
        return None
    # In the file's order, not re-sorted: two lines that overlap are in the
    # order they were written, which a sort by start time can swap.
    word = any("Lead" in i for i in items)
    m = re.search(r"^Title:\s*(.+)$", text, re.M)
    meta = {"Title": m.group(1).strip()} if m else {}
    return {**meta, "Type": "Syllable" if word else "Line", "Content": items}


def _read_srt(text: str) -> dict | None:
    items = []
    stamp = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        rows = [r for r in block.strip().split("\n") if r.strip()]
        for k, r in enumerate(rows):
            m = stamp.search(r)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            s = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            words = " ".join(re.sub(r"<[^>]+>", "", x).strip() for x in rows[k + 1:])
            if words:
                items.append({"Text": words, "StartTime": s, "EndTime": e})
            break
    return {"Type": "Line", "Content": items} if items else None


LRC_WORD = re.compile(r"<(\d+):(\d+(?:[.:]\d+)?)>")


def _lrc_secs(m) -> float:
    return int(m.group(1)) * 60 + float(m.group(2).replace(":", "."))


def _read_lrc(text: str) -> dict | None:
    """LRC, and enhanced LRC: a word-timed line is read word by word, its
    bracketed words lifted out as backing vocals; a line-timed one is left to
    lyric_sources.parse_lrc, as it always was."""
    if not LRC_WORD.search(text):
        body = LS.parse_lrc(text)
        if body:
            body.update(_meta(text))
        return body
    rows = []
    for raw in text.splitlines():
        heads = list(LS.LRC_TAG.finditer(raw))
        if not heads or heads[0].start() != 0:
            continue
        rest = raw[heads[-1].end():]
        at = _lrc_secs(heads[0])
        words = list(LRC_WORD.finditer(rest))
        if not words:
            if rest.strip():
                rows.append(("line", at, rest.strip()))
            else:
                rows.append(("stop", at, ""))
            continue
        pieces = []
        lead = rest[:words[0].start()]
        if lead.strip():
            pieces.append((lead, at, _lrc_secs(words[0])))
        for k, m in enumerate(words):
            hi = words[k + 1].start() if k + 1 < len(words) else len(rest)
            word = rest[m.end():hi]
            s = _lrc_secs(m)
            e = _lrc_secs(words[k + 1]) if k + 1 < len(words) else s
            if word:
                pieces.append((word, s, e))
        rows.append(("words", at, pieces))
    items = []
    for n, (kind, at, what) in enumerate(rows):
        nxt = next((r[1] for r in rows[n + 1:]), None)
        if kind == "words":
            pieces = list(what)
            if pieces and pieces[-1][2] <= pieces[-1][1]:
                t, s, _e = pieces[-1]
                pieces[-1] = (t, s, min(nxt, s + 1.0) if nxt else s + 1.0)
            got = _item(pieces, at)
            if got:
                items.append(got)
        elif kind == "line":
            end = min(nxt, at + 10.0) if nxt is not None else at + 6.0
            items.append({"Text": what, "StartTime": at, "EndTime": end})
    if not items:
        return None
    word = any("Lead" in i for i in items)
    return {**_meta(text), "Type": "Syllable" if word else "Line", "Content": items}


def _read_txt(text: str) -> dict | None:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    return {"Type": "Static", "Lines": [{"Text": l} for l in lines]}
