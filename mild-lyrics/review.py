"""Reading a timed lyric back for the things that are wrong with it.

Everything here answers one question: if somebody sat down with this document
and went through it line by line, what would they stop at? It is for the files
that come in from OUTSIDE the player -- one dropped on the window, one pushed
over the live link from the editor -- because those are the ones somebody is
still working on. See LyricsView.open_review for the screen it draws on.

The player is the wrong instrument for this on its own, and that is the whole
reason this exists. It is built to make a document look right: `_trim` takes
the invisible characters out of every syllable before it is drawn, `unzwsp`
takes them out of a line, `prepare` clamps an open end, and `last_moment`
quietly plays a line to the end of its longest word whatever the line said. A
zero-width space, a no-break space, a Cyrillic e, a line that runs a tenth of
a second into the next one -- none of them show. They are all still in the
file, and the file is what gets published.

WHAT IS CHECKED, and why each one is worth a person's attention:

  characters   Anything invisible (ZWSP, the joiners, a BOM, a soft hyphen),
               any space that is not a plain one, any bidi control, any
               apostrophe that is not ', and any letter sitting in a word
               written in another alphabet -- the Cyrillic e in "be" being the
               one everybody has met. These travel: they come in with a copy
               and paste out of a browser and they ride into everything the
               file is ever turned into.

               And the punctuation a page writes that a singer cannot sing:
               an ellipsis, a slash, a backslash. Nothing is sung there, and
               in a timed document the words either side of one have times of
               their own, so there is nothing for it to stand for. With a
               comma hung off an em dash, “—,”, which is the dash saying the
               phrase breaks and then the comma saying it again -- the dash
               on its own is the whole mark.

  how it reads Whether a line is in capitals throughout, has no capital in it
               anywhere, or is capitalised word by word the way a title is --
               all three being what a transcript looks like rather than what
               a lyric looks like. Said once about the document where it is
               how the whole document is written, because writing a lyric in
               lower case is a thing people do on purpose. See _check_case,
               and mind the exemptions: a word spelled out B-O-Y is not a
               line in capitals, and Korean has no capitals to leave out.

  splits       The document's own syllable seams, against the rule the editor
               splits by -- `editor.syllables.split`, which is this project's
               sung rule plus every correction the person using it has kept,
               so a word they have already ruled on is never raised again.
               Both of the editor's rules are asked and a seam is only raised
               where BOTH refuse it, because they are wrong in different
               places: the sung rule reads "nosebleeds" as no-seb-leeds and
               hyphenation has it as it was timed.

               And three seams that are wrong whatever the rules say: a
               hyphen with nothing to join -- the word stopping after it,
               drawn "Wha- wha- what", gap and all; a space typed after it;
               or the line ending on it (_check_hyphens); a hyphen at the
               head of a piece rather than the tail of the one before it,
               shake|-up for shake-|up, which lights the hyphen up with the
               wrong syllable (_check_hyphen_side); and a word spelled out
               loud cut halfway, "PVA" timed PV|A, which is timed whole or a
               letter at a time and nothing in between.

               Only one direction is reported. A word the rules would cut and
               the document times whole is NOT a fault: timing a word whole is
               a choice, and editor/syllables.py measures that direction at 41
               of 349 -- it is the common case, not the mistake. A cut neither
               rule would make is the other way round, and is nearly always a
               slip of the hand.

               Nearly always, which is why each of those three findings --
               split, split-digraph, split-whole -- carries its own answer:
               the word and the arrangement the document has, ready to be
               kept as the rule for it (see _kept_of and keep_split). The
               rules are wrong about a word often enough that a page with no
               way to say so is a page that gets read past, and the store it
               is kept in is the editor's own, so saying it once settles the
               word for both windows and for every song after this one. The
               other three -- a hyphen with nothing to join, a hyphen on the
               wrong side, a word spelled out and cut halfway -- carry no
               answer, because they are wrong whatever any rule thinks.

  timing       Two things running through each other, at any amount at all:
               syllables, words and lines. A millisecond of overlap is not a
               rounding error in a document written in milliseconds, and it is
               exactly what a player hides -- a line is drawn from whenever it
               starts until whenever its words stop, so nothing on screen ever
               shows it.

               Weighed differently depending on what is crossing what, and
               by how much. Inside a line a short clip is a fault -- one voice
               cannot sing two words at once, and nothing about a performance
               is decided at four milliseconds -- while a long one is a word
               held over the one after it, which somebody may have meant, so
               past CLIP_SLIP it is only doubtful. Between lines it is never
               more than worth a look: singers trade lines and a line rings on
               under the next, so the amount is measured and shown and nothing
               is called wrong. See _check_between.

               And where a line's WORDS stopped before the next line began
               and only its written end crosses, that is what is said: the
               number is in the <p> end rather than in the singing, and the
               sentence points at the end rather than describing an overlap
               nobody performed.

               Also the arithmetic that cannot be right whoever is singing: an
               end before its start, a syllable outside its own line, times
               out of order, a hole in the middle of a word.

  the document Whether a line's own Text spells what its syllables spell,
               whether anything is timed past the end of the recording, and
               the small print -- empty chips, a line with times and no words,
               and a bracket or a quotation mark opened and never closed.
               That last one is counted over the whole document rather than
               over a line, because a quotation in a lyric is routinely opened
               on one line and closed two lines later; see _check_pairs.

               And an ad-lib typed into the line instead of written as one: a
               word-timed document has a Background group to put "(Huh)" in,
               and a lead line that spells it out has two characters nobody
               sings inside the singer's own words. See _check_parens.

  the header   Whether anybody is credited with writing the song, and whether
               a song with a guest on it has a second voice anywhere in it.
               Neither shows in the words however carefully they are read --
               the first is a field nobody filled in, the second is every
               line of a duet filed as the same singer. The second is a note
               and only ever a note, and it is asked in one direction: a
               feature with no second voice is worth a look, a second voice
               with no feature is just a duet. See _check_credits.

What is DRAWN from all this is the page's business, not this file's -- it
keeps every finding it made, and the page folds the repeats, hides the clean
lines and narrows by tab and by weight. A song repeats itself and its faults
repeat with it; see LyricsView.review_folded.

Nothing here edits a DOCUMENT. It reads one and says what it saw; the fixing
is the editor's job, and a file the player holds is not the file on disk
anyway. The one thing it will write is a correction to the RULE -- keep_split
and forget_split, straight into the editor's store of kept splits -- which is
a statement about a word rather than about this file, and is what makes a
wrong finding about a seam answerable on the screen that made it.

Run it over a folder of TTMLs from the command line to see what it makes of
them:

    python3 mild-lyrics/review.py *.ttml
"""
from __future__ import annotations

import pathlib
import json
import re
import sys
import unicodedata

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]

import spicy_lyrics as SL  # noqa: E402

ERROR, WARN, NOTE = "error", "warn", "note"
LEVELS = (ERROR, WARN, NOTE)

EPS = 0.0005

CLIP_SLIP = 0.050

# ---------------------------------------------------------------- characters
INVISIBLE = {
    "‌": "zero-width non-joiner",
    "‍": "zero-width joiner",
    "⁠": "word joiner",
    "﻿": "byte-order mark",
    "­": "soft hyphen",
    "᠎": "Mongolian vowel separator",
}
ZWSP = "​"
SPACES = {
    " ": "no-break space", " ": "narrow no-break space",
    " ": "figure space", " ": "thin space", " ": "hair space",
    " ": "en space", " ": "em space", " ": "three-per-em space",
    " ": "four-per-em space", " ": "six-per-em space",
    " ": "punctuation space", " ": "medium mathematical space",
    "　": "ideographic space", " ": "Ogham space mark",
    "\t": "tab", "": "vertical tab", "\f": "form feed",
}
BIDI = {
    "‎": "left-to-right mark", "‏": "right-to-left mark",
    "‪": "left-to-right embedding", "‫": "right-to-left embedding",
    "‬": "pop directional formatting", "‭": "left-to-right override",
    "‮": "right-to-left override", "⁦": "left-to-right isolate",
    "⁧": "right-to-left isolate", "⁨": "first strong isolate",
    "⁩": "pop directional isolate",
}
APOSTROPHES = {
    "’": "right single quotation mark",
    "‘": "left single quotation mark",
    "ʼ": "modifier letter apostrophe",
    "ʹ": "modifier letter prime",
    "´": "acute accent",
    "`": "grave accent",
    "′": "prime",
    "＇": "fullwidth apostrophe",
    "՚": "Armenian apostrophe",
    "‛": "single high-reversed-9 quotation mark",
}
QUOTES = {
    "“": "left double quotation mark",
    "”": "right double quotation mark",
    "„": "double low-9 quotation mark",
    "″": "double prime",
    "＂": "fullwidth quotation mark",
}
SHOWN = {"\t": "→", "\n": "↵", "\r": "↵"}
DOT = "·"
BOX = "␣"

# Where a word is cut, written the way the page DRAWS it: the review puts a
# little upright bar in the gap between two pieces of one word, and what the
# note underneath says has to be the same mark or the reader is left matching
# one notation against another. It used to be the middle dot, which on this
# page already means something else -- an invisible character, see DOT -- so
# "wi·thout" was a seam and "or·am" was a zero-width space, in the same type,
# two lines apart.
SEAM = "|"

CONFUSABLE = ("CYRILLIC", "GREEK")

VOWELS = set("aeiouyàáâäãåèéê"
             "ëìíîïòóôöõ"
             "øùúûüæœ"
             "аеёиоуыэюя")
DIGRAPHS = ("sch", "th", "ch", "sh", "ph", "wh", "gh", "ck", "qu", "ij")


GROUPS = {
    "splits": ("split", "split-digraph", "split-whole", "no-vowel",
               "hyphen-gap", "hyphen-side", "half-spelled"),
    "sync": ("syl-overlap", "word-overlap", "line-overlap", "adlib-overlap",
             "out-of-order", "lines-out-of-order", "backwards", "zero-length",
             "very-short", "very-long", "hole", "outside", "line-end-short",
             "line-end-long",
             "untimed", "negative", "past-the-end", "unsynced"),
    # Not findings: every split word, listed so the splits can be read down
    # a column. Only ever shown under their own tab, and never counted.
    "seams": ("seam",),
}
TABS = ("all", "words", "splits", "sync", "seams")
LEVEL_NAMES = {"error": "wrong", "warn": "doubtful", "note": "worth a look"}
LISTED = {"seams"}


def group_of(kind: str) -> str:
    """Which tab a finding belongs under."""
    for name, kinds in GROUPS.items():
        if kind in kinds:
            return name
    return "words"


def _under(group: str, kind: str) -> bool:
    """Whether a finding of `kind` is shown under the tab `group`."""
    mine = group_of(kind)
    if mine in LISTED:
        return group == mine
    return group in ("", "all") or group == mine


def _script(ch: str) -> str:
    """Which alphabet a letter is written in, by its Unicode name."""
    if not ch.isalpha():
        return ""
    try:
        return unicodedata.name(ch).split()[0]
    except ValueError:
        return ""


def _fmt(t) -> str:
    """A time as a person writes it down."""
    if t is None:
        return "—"
    t = float(t)
    sign = "-" if t < 0 else ""
    t = abs(t)
    return f"{sign}{int(t // 60)}:{t % 60:06.3f}"


stamp = _fmt


def _ms(x: float) -> str:
    """A duration, in the unit the document is written in."""
    return f"{x * 1000:.0f}ms" if abs(x) < 1.0 else f"{x:.3f}s"


def _said(text: str) -> str:
    """A syllable as it can be quoted in a sentence about it."""
    return SL._trim(SL.unzwsp(text or "")) or (text or "").strip() or "—"


def _around(text: str, i: int) -> str:
    """The word one character sits in, for quoting it back.

    Asked of the word rather than of the chip because a chip is not always a
    syllable: a line-timed document is one chip holding the whole line, and
    "a Cyrillic e, in <the entire line>" is a sentence that hides the thing it
    is pointing at.
    """
    a = i
    while a > 0 and not text[a - 1].isspace():
        a -= 1
    b = i + 1
    while b < len(text) and not text[b].isspace():
        b += 1
    got = shown_text(text[a:b]).strip()
    if not any(ch.isalnum() for ch in got):
        return shown_text(text).strip() or got
    return got or shown_text(text[max(0, i - 8):i + 8])


# -------------------------------------------------------------------- shapes
class Mark:
    """One highlighted run of characters inside one chip.

    `a` and `b` index the SHOWN text, not the document's -- an invisible
    character is drawn as a visible stand-in and the mark has to land on what
    is actually on screen.
    """

    __slots__ = ("a", "b", "kind", "level", "says")

    def __init__(self, a: int, b: int, kind: str, level: str, says: str) -> None:
        self.a, self.b, self.kind, self.level, self.says = a, b, kind, level, says


class Chip:
    """One timed piece of the document -- a syllable, or a whole word.

    `glue` is whether the next chip is part of the same word, read the way the
    player reads it: the flag, unless the text itself carries the separator.
    See SL.word_ends.
    """

    __slots__ = ("text", "shown", "start", "end", "glue", "part", "marks",
                 "flags")

    def __init__(self, text: str, start, end, glue: bool, part: bool = False) -> None:
        self.text, self.start, self.end, self.glue = text, start, end, glue
        self.part = part
        self.shown = shown_text(text)
        self.marks: list[Mark] = []
        self.flags: list[tuple[str, str]] = []

    def mark(self, a: int, b: int, kind: str, level: str, says: str) -> None:
        self.marks.append(Mark(a, b, kind, level, says))

    def flag(self, kind: str, level: str) -> None:
        if (kind, level) not in self.flags:
            self.flags.append((kind, level))

    def worst(self) -> str:
        """The heaviest thing said about this chip, for the colour it draws in."""
        return _worst([m.level for m in self.marks] + [lv for _k, lv in self.flags])

    def shows(self, group: str = "all"):
        """(the marks to draw, the weight of the piece itself) under one tab.

        A tab is a question being asked of the document, and the answer has to
        be the same in the list and on the words: reading the Sync tab with
        red boxes round the brackets still on the line is being shown the
        answer to a question nobody asked. See group_of.
        """
        if group in ("", "all"):
            return list(self.marks), self.flagged()
        return ([m for m in self.marks if group_of(m.kind) == group],
                _worst([lv for k, lv in self.flags if group_of(k) == group]))

    def flagged(self) -> str:
        """The heaviest thing said about the chip AS A WHOLE.

        Not the same question as `worst`, and the page asks both: a mark sits
        on the characters it is about and needs no underline under the rest of
        the piece, while a flag -- a bad split, an overlap, no length -- is
        about the piece itself and has nothing smaller to point at. Reading
        one for the other put a red rule under the entire line of a
        line-timed document because one letter in it was Cyrillic.
        """
        return _worst([lv for _k, lv in self.flags])


def _worst(levels) -> str:
    """The heaviest of a set of weights, or "" for nothing said at all."""
    for want in LEVELS:
        if want in levels:
            return want
    return ""


def shown_text(text: str) -> str:
    """`text` with everything invisible in it replaced by something visible."""
    out = []
    for ch in text or "":
        if ch in SHOWN:
            out.append(SHOWN[ch])
        elif ch == ZWSP or ch in INVISIBLE or ch in BIDI:
            out.append(DOT)
        elif ch in SPACES:
            out.append(BOX)
        else:
            out.append(ch)
    return "".join(out)


class Row:
    """One drawable row of the review: a lead line, or one ad-lib inside it."""

    __slots__ = ("n", "kind", "start", "end", "background", "opposite",
                 "chips", "found", "group")

    def __init__(self, n: int, kind: str, group: int) -> None:
        self.n, self.kind, self.group = n, kind, group
        self.start = self.end = None
        self.background = kind == "bg"
        self.opposite = False
        self.chips: list[Chip] = []
        self.found: list[int] = []

    def text(self) -> str:
        """What this row spells, the way the player would draw it."""
        out = ""
        for c in self.chips:
            out += c.text if c.glue else SL._trim(c.text) + " "
        return out.strip()

    def last(self):
        """When the last of this row's words stops, whatever the row says."""
        ends = [c.end for c in self.chips if c.end is not None]
        if self.end is not None:
            ends.append(self.end)
        return max(ends) if ends else None


class Report:
    """Everything one pass over one document saw."""

    def __init__(self, rule: str, lang: str, whose: str = "") -> None:
        self.rule, self.lang, self.whose = rule, lang, whose
        self.second = ""
        self.kept: list[str] = []
        self.rows: list[Row] = []
        self.findings: list[dict] = []
        self.counts = {ERROR: 0, WARN: 0, NOTE: 0}

    def say(self, row, level: str, kind: str, says: str,
            at=None, chip: int | None = None, fix=None, suggest=None,
            md: str | None = None) -> int:
        """File one finding, and hand back where it went.

        `fix` is how the finding can be ANSWERED, where it can be: for a
        seam, the word and the arrangement the document already has, which
        keep_split files as a correction and the rule then defers to. It is
        the only thing in a finding that is not a description of the
        document, and it is still not a change to one -- a correction says
        what the RULE should think of a word, here and in the next song.
        """
        k = len(self.findings)
        self.findings.append({
            "level": level, "kind": kind,
            # A seam listed and a flag somebody wrote are printed as they are.
            "says": says if kind in ("seam", "custom") else sentence(says),
            "suggest": suggest, "ignored": False,
            "row": None if row is None else self.rows.index(row),
            "line": None if row is None else row.n, "chip": chip,
            "at": at if at is not None else (row.start if row else None),
            "fix": fix, "md": md,
        })
        self.counts[level] += 1
        if row is not None:
            row.found.append(k)
        return k

    def worst_of(self, row: Row) -> str:
        levels = [self.findings[k]["level"] for k in row.found
                  if not self.findings[k]["ignored"]
                  and group_of(self.findings[k]["kind"]) not in LISTED]
        for want in LEVELS:
            if want in levels:
                return want
        return ""

    def total(self) -> int:
        return sum(1 for f in self.findings if not f["ignored"]
                   and group_of(f["kind"]) not in LISTED)

    def ignored(self) -> int:
        """How many findings an ignore rule is keeping off the page."""
        return sum(1 for f in self.findings if f["ignored"])

    def summary(self) -> str:
        if not self.total():
            return "nothing to report"
        return ", ".join(
            f"{self.counts[lv]} {name}" for lv, name in
            ((ERROR, "wrong"), (WARN, "doubtful"), (NOTE, "worth a look"))
            if self.counts[lv])

    def said_rule(self) -> str:
        """Who the splits were held to, for the line under the heading."""
        if self.rule == "not checked":
            return "not checked"
        if not self.second:
            return f"{self.rule}, on its own"
        return f"{self.rule} and {self.second} — only a seam both refuse"

    def said_kept(self) -> str:
        """How much of this document a kept correction already answers for."""
        n = len(self.kept)
        if not n:
            return ""
        return (f"{n} word here follows a correction you kept" if n == 1
                else f"{n} words here follow a correction you kept")

    def told(self, row: Row, group: str = "all", level: str = "") -> list[tuple]:
        """What to print under one row: (level, kind, sentence, how many more).

        One line of a song can hold eight zero-width spaces and eight
        sentences about them, which is a wall rather than a review. So each
        kind is one line, naming every one of them, separated by semicolons.
        "How many more" is always 0 now and kept for the callers' sake.

        Splits are the exception: each is a different word with its own
        answer, and each is listed so each can be corrected.
        """
        out, seen = [], {}
        for k in row.found:
            f = self.findings[k]
            if f["ignored"]:
                continue
            if not _under(group, f["kind"]):
                continue
            if level and f["level"] != level:
                continue
            at = seen.get(f["kind"])
            if (at is None or group_of(f["kind"]) in ("splits",) + tuple(LISTED)
                    or f["kind"] == "custom"):
                seen[f["kind"]] = len(out)
                out.append([f["level"], f["kind"], f["says"], 0, k])
            else:
                # The rest of the kind go into the same line, each named.
                first, more = out[at][2].rstrip("."), f["says"].rstrip(".")
                if more not in first.split("; "):
                    out[at][2] = f"{first}; {more}."
        return [tuple(x) for x in out]

    def in_group(self, group: str, level: str = "") -> list:
        """The findings under one tab, in the order they are listed.

        `level` narrows to one weight -- the wrong things on their own, or the
        doubtful ones on their own. The two questions are independent and
        somebody going through a document asks both: what is this about, and
        how much does it matter.
        """
        return [f for f in self.findings if not f["ignored"]
                and _under(group, f["kind"])
                and (not level or f["level"] == level)]

    def group_counts(self) -> dict:
        """How many findings each tab holds, for the strip that names them."""
        out = {name: 0 for name in TABS}
        for f in self.findings:
            if f["ignored"]:
                continue
            mine = group_of(f["kind"])
            if mine not in LISTED:
                out["all"] += 1
            out[mine] += 1
        return out

    def kinds(self) -> list[tuple[str, int]]:
        """What was found, commonest first."""
        got: dict = {}
        for f in self.findings:
            if f["ignored"]:
                continue
            got[f["kind"]] = got.get(f["kind"], 0) + 1
        return sorted(got.items(), key=lambda kv: (-kv[1], kv[0]))

    def as_text(self) -> str:
        """The whole review as something that can go in a clipboard.

        A line, then what is wrong with it, a sentence to a line:

            **Line 23, 0:45.524:** The tenacity
            *Tenacity* is split as *ten|acity*. Correct split: *te|na|ci|ty*

        in Discord's markdown, with a line that repeats written once:
        **Lines 3, 9, 0:10.000, 0:52.000:** and the rest.

        No heading and no level names. The review said who it was for and
        how the splits were judged at the top of every copy, which is two
        lines of the reviewer describing itself to somebody who wanted the
        list; the weights are in the window, where they can be filtered on.
        """
        out, groups, at = [], [], {}
        for row in self.rows:
            told = self.told(row, "all")
            if not told:
                continue
            key = (row.kind, row.text(),
                   tuple((kind, says) for _lv, kind, says, _m, _k in told))
            if key in at:
                groups[at[key]][0].append(row)
            else:
                at[key] = len(groups)
                groups.append(([row], told))
        for rows, told in groups:
            if out:
                out.append("")
            what = "Line" if rows[0].kind == "lead" else "Ad-lib in line"
            if len(rows) > 1:
                what += "s"
            where = ", ".join([str(r.n) for r in rows]
                              + [_fmt(r.start) for r in rows])
            out.append(f"**{what} {where}:** {_md(rows[0].text())}")
            for _level, _kind, says, _more, k in told:
                out.extend((self.findings[k].get("md") or says).split("\n"))
        loose = [f for f in self.findings if f["row"] is None and not f["ignored"]]
        if loose:
            if out:
                out.append("")
            for f in loose:
                out.extend(f["says"].split("\n"))
        return "\n".join(out)


def _md(text: str) -> str:
    """Lyric text made safe to paste into Discord's markdown."""
    for ch in "\\*_~`":
        text = text.replace(ch, "\\" + ch)
    return text


def _md_split(core: str, as_cut: str, why: str, right: str, sung) -> str:
    """A split finding as the copy writes it, the pieces in italics:
    *like, "Who* is split as *like, "|Who*. Correct split: *like, |"Who*"""
    head = f"*{_md(core)}* is split as *{_md(as_cut)}*{why}. "
    if len(sung) <= 1:
        return head + "Should not be split."
    return head + f"Correct split: *{_md(right)}*"


def sentence(says: str) -> str:
    """A finding as the review prints it: straight quotes, a capital first.

    The quotes are the ones the review wraps round what it quotes; a curly
    apostrophe INSIDE a lyric it is quoting is the lyric's, and stays.
    """
    says = (says or "").replace("\u201c", '"').replace("\u201d", '"')
    head, nl, rest = says.partition("\n")
    if head and (head[-1].isalnum() or head[-1] in ')"') \
            and "Correct split:" not in head:
        head += "."
    says = head + nl + rest
    # Only a sentence that opens on a word of its own. One that opens on a
    # quote is quoting the lyric, and "i" capitalised there is no longer
    # the "i" the finding is about.
    if says[:1].isalpha():
        says = says[0].upper() + says[1:]
    return says


# --------------------------------------------------------------- the checks
def _chips_of(group: dict) -> list[Chip]:
    """A group's syllables as chips, with the word boundaries already read."""
    syls = [y for y in (group or {}).get("Syllables") or [] if isinstance(y, dict)]
    out = []
    for i, y in enumerate(syls):
        text = y.get("Text")
        text = text if isinstance(text, str) else ""
        nxt = syls[i + 1].get("Text", "") if i + 1 < len(syls) else ""
        glue = bool(y.get("IsPartOfWord")) and not SL.word_ends(text, nxt)
        start, end = y.get("StartTime"), y.get("EndTime")
        out.append(Chip(text,
                        float(start) if isinstance(start, (int, float)) else None,
                        float(end) if isinstance(end, (int, float)) else None,
                        glue and i + 1 < len(syls),
                        bool(y.get("IsPartOfWord"))))
    return out


def _words(chips: list[Chip]) -> list[tuple[int, int]]:
    """Where each word begins and ends in the chip list, as [first, last]."""
    out, first = [], 0
    for i, c in enumerate(chips):
        if not c.glue or i == len(chips) - 1:
            out.append((first, i))
            first = i + 1
    return out


def _check_text(rep: Report, row: Row) -> None:
    """Every character in the row that has no business being in a lyric."""
    for ci, chip in enumerate(row.chips):
        text = chip.text
        if not text:
            rep.say(row, ERROR, "empty-chip",
                    f"empty timed piece at {_fmt(chip.start)}",
                    chip.start, ci)
            chip.flag("empty-chip", ERROR)
        elif not text.strip():
            rep.say(row, WARN, "blank-chip",
                    f"whitespace-only piece at {_fmt(chip.start)}",
                    chip.start, ci)
            chip.flag("blank-chip", WARN)
        scripts = {_script(c) for c in text}
        scripts.discard("")
        latin = "LATIN" in scripts
        for i, ch in enumerate(text):
            name, kind, level = "", "", ERROR
            if ch == ZWSP:
                name, kind = "zero-width space", "invisible"
            elif ch in INVISIBLE:
                name, kind = INVISIBLE[ch], "invisible"
            elif ch in BIDI:
                name, kind = BIDI[ch], "bidi"
            elif ch in SPACES:
                name, kind = SPACES[ch], "space"
            elif ch in ("\n", "\r"):
                name, kind = "line break", "space"
            elif ch in APOSTROPHES:
                name, kind, level = APOSTROPHES[ch], "apostrophe", WARN
            elif ch in QUOTES:
                name, kind, level = QUOTES[ch], "quote", NOTE
            elif ord(ch) < 0x20 or ord(ch) == 0x7f:
                name, kind = f"control character U+{ord(ch):04X}", "control"
            elif latin and _script(ch) in CONFUSABLE:
                name, kind = f"{_script(ch).capitalize()} {ch}", "homoglyph"
            elif not latin and _script(ch) == "LATIN" and scripts & set(CONFUSABLE):
                name, kind = f"Latin {ch}", "homoglyph"
            if not name:
                continue
            said = {
                "invisible": f"invisible {name} (U+{ord(ch):04X})",
                "bidi": f"{name} (U+{ord(ch):04X})",
                "space": f"{name} (U+{ord(ch):04X}), not a plain space",
                "control": f"{name}",
                "apostrophe": f"{name} (U+{ord(ch):04X}) as apostrophe, not '",
                "quote": f"typographic {name} (U+{ord(ch):04X})",
                "homoglyph": f"{name} (U+{ord(ch):04X}) from another alphabet",
            }[kind]
            rep.say(row, level, kind, f"{said}, in “{_around(text, i)}”",
                    chip.start, ci)
            chip.mark(i, i + 1, kind, level, said)
        for m in ELLIPSIS.finditer(text):
            rep.say(row, WARN, "ellipsis",
                    f"ellipsis in “{_around(text, m.start())}”", chip.start, ci)
            chip.mark(m.start(), m.end(), "ellipsis", WARN, "an ellipsis")
        for m in DASH_COMMA.finditer(text):
            rep.say(row, ERROR, "dash-comma",
                    f"comma after a dash in “{_around(text, m.start())}”", chip.start, ci)
            chip.mark(m.start(), m.end(), "dash-comma", ERROR,
                      "a comma after an em dash")
        for i, ch in enumerate(text):
            if ch not in "/\\":
                continue
            rep.say(row, WARN, "slash",
                    f"{'backslash' if ch == chr(92) else 'slash'} in "
                    f"“{_around(text, i)}”",
                    chip.start, ci)
            chip.mark(i, i + 1, "slash", WARN,
                      f"a {'backslash' if ch == chr(92) else 'slash'}")
        if text and text != unicodedata.normalize("NFC", text):
            rep.say(row, WARN, "nfc",
                    f"“{_said(text)}” uses combining marks (not NFC)", chip.start, ci)
            chip.flag("nfc", WARN)
        if text.strip() and not chip.glue and text != text.rstrip():
            rep.say(row, NOTE, "double-space",
                    f"“{_said(text)}” ends in a space: double gap",
                    chip.start, ci)
            chip.flag("double-space", NOTE)


ELLIPSIS = re.compile(r"\.{2,}|\u2026+")
DASH_COMMA = re.compile("\u2014,")

BRACKETS = {"(": ")", "[": "]", "{": "}", "\u201c": "\u201d"}
QUOTE = '"'


def _check_pairs(rep: Report, rows: list[Row]) -> None:
    """Brackets and quotation marks, counted over the whole document.

    Over the whole document because that is the unit they are written in. A
    quotation in a lyric routinely opens on one line and closes two lines
    later --

        Mama said, "Where you been at?
        Make sure you're doin' good"

    -- and asked a line at a time both of those lines are wrong and the song
    is right. That was every single one of the thirteen this raised over the
    53 TTMLs in this folder: not one real fault among them.

    So the state is carried down the lead lines, and what is reported is a
    bracket or a quotation that is still open when the song ends, filed
    against the line that opened it. An ad-lib is checked on its own: it is a
    few words sung over somebody else's line rather than the next thing in the
    sentence, and threading it through the same walk would have it closing the
    lead line's quotation.
    """
    def walk(rows_here: list[Row], shut: bool) -> None:
        stack: list = []
        quote = None
        for row in rows_here:
            for ch in row.text():
                if ch in BRACKETS:
                    stack.append((ch, row))
                elif ch in BRACKETS.values():
                    if stack and BRACKETS[stack[-1][0]] == ch:
                        stack.pop()
                    else:
                        rep.say(row, NOTE, "brackets",
                                f"a closing {ch} with nothing open before it")
                elif ch == QUOTE:
                    quote = None if quote else row
        if not shut:
            return
        for ch, row in stack:
            rep.say(row, NOTE, "brackets",
                    f"{ch} is opened here and never closed")
        if quote is not None:
            rep.say(quote, NOTE, "brackets",
                    'a " is opened here and never closed')

    walk([r for r in rows if r.kind == "lead"], True)
    for row in rows:
        if row.kind != "lead":
            walk([row], True)


def _check_line_text(rep: Report, row: Row, item: dict) -> None:
    """The line's own Text against what its syllables actually spell."""
    said = row.text()
    own = item.get("Text") if isinstance(item, dict) else None
    if isinstance(own, str) and own.strip() and row.chips and len(row.chips) > 1:
        a = re.sub(r"\s+", " ", SL.unzwsp(own, True)).strip()
        b = re.sub(r"\s+", " ", said).strip()
        if a != b:
            rep.say(row, WARN, "text-mismatch",
                    f"line text “{a}” ≠ syllables “{b}”")



def _check_times(rep: Report, row: Row) -> None:
    """The arithmetic of one row: order, length, and things running together."""
    chips = row.chips
    timed = [c for c in chips if c.start is not None and c.end is not None]
    for ci, c in enumerate(chips):
        if c.start is None or c.end is None:
            if timed:
                rep.say(row, ERROR, "untimed",
                        f"“{_said(c.text)}” is untimed", row.start, ci)
                c.flag("untimed", ERROR)
            continue
        if c.end < c.start - EPS:
            rep.say(row, ERROR, "backwards",
                    f"“{_said(c.text)}” ends {_ms(c.start - c.end)} before "
                    f"it starts ({_fmt(c.start)} → {_fmt(c.end)})", c.start, ci)
            c.flag("backwards", ERROR)
        elif abs(c.end - c.start) <= EPS:
            rep.say(row, WARN, "zero-length",
                    f"“{_said(c.text)}” has no length ({_fmt(c.start)})", c.start, ci)
            c.flag("zero-length", WARN)
        elif c.end - c.start < 0.04:
            rep.say(row, NOTE, "very-short",
                    f"“{_said(c.text)}” lasts {_ms(c.end - c.start)}: too short", c.start, ci)
            c.flag("very-short", NOTE)
        elif c.end - c.start > 10.0:
            rep.say(row, NOTE, "very-long",
                    f"“{_said(c.text)}” lasts {c.end - c.start:.1f}s",
                    c.start, ci)
            c.flag("very-long", NOTE)
        if c.start < -EPS:
            rep.say(row, ERROR, "negative",
                    f"“{_said(c.text)}” starts before 0:00 ({_fmt(c.start)})", c.start, ci)
            c.flag("negative", ERROR)
    weight = ERROR if row.kind == "lead" else WARN
    voices = "" if row.kind == "lead" else " (two voices?)"
    for i in range(len(chips) - 1):
        a, b = chips[i], chips[i + 1]
        if a.end is None or b.start is None:
            continue
        if a.start is not None and b.start < a.start - EPS:
            rep.say(row, weight, "out-of-order",
                    f"“{_said(b.text)}” starts before "
                    f"“{_said(a.text)}” ({_fmt(b.start)} vs "
                    f"{_fmt(a.start)}){voices}", b.start, i + 1)
            b.flag("out-of-order", weight)
            continue
        over = a.end - b.start
        if over > EPS:
            same = a.glue
            heavy = weight if over <= CLIP_SLIP else WARN
            held = "" if over <= CLIP_SLIP else " (held note?)"
            rep.say(row, heavy, "syl-overlap" if same else "word-overlap",
                    (f"“{_said(a.text)}” and “{_said(b.text)}” "
                     f"run through each other by {_ms(over)}" if same else
                     f"“{_said(a.text)}” runs {_ms(over)} into "
                     f"“{_said(b.text)}”") + f", at {_fmt(b.start)}"
                    + (voices or held), b.start, i + 1)
            a.flag("syl-overlap" if same else "word-overlap", heavy)
            b.flag("syl-overlap" if same else "word-overlap", heavy)
        elif a.glue and -over > 0.12:
            rep.say(row, NOTE, "hole",
                    f"{_ms(-over)} gap inside “{_said(a.text)}"
                    f"{_said(b.text)}”", a.end, i)
            a.flag("hole", NOTE)
    if row.start is not None and timed:
        first = min(c.start for c in timed)
        last = max(c.end for c in timed)
        if first < row.start - EPS:
            rep.say(row, WARN, "outside",
                    f"first word starts {_ms(row.start - first)} before the line")
        if row.end is not None and last > row.end + EPS:
            rep.say(row, NOTE, "line-end-short",
                    f"last word ends {_ms(last - row.end)} after the line "
                    f"({_fmt(last)} vs {_fmt(row.end)})")


JOINERS = "-\u2010\u2011"


def _check_hyphen_side(rep: Report, row: Row) -> None:
    """Which side of a seam the hyphen ends up on.

    It goes on the piece BEFORE the cut -- shake-|up, not shake|-up -- and
    that is not a matter of taste. The player draws a piece at a time and
    fills it as it is sung, so a hyphen sitting at the head of the next piece
    is a hyphen that lights up with the syllable AFTER the one it belongs to;
    it is the tail of "shake" and it should darken and light with "shake".
    Everything else in this project already agrees: SL.syllabify hands the
    mark to the chunk in front of it, `editor.syllables._hyphenate` does the
    same, and gc's own kept splits hold Oh-|woah and Yeah-|yeah-|yeah.

    Three of these over the 53 TTMLs in this folder, all in one song, all of
    them a word cut zy|-bizz where it should read zy-|bizz.
    """
    for first, last in _words(row.chips):
        chips = row.chips[first:last + 1]
        pieces = [_said(c.text) for c in chips]
        for k, c in enumerate(chips):
            if not k:
                continue
            head = c.text.lstrip()
            n = len(head) - len(head.lstrip(JOINERS))
            if not n:
                continue
            core = SL.unzwsp("".join(x.text for x in chips)).strip()
            want = list(pieces)
            want[k - 1] += pieces[k][:n]
            want[k] = pieces[k][n:]
            want = [x for x in want if x]
            rep.say(row, ERROR, "hyphen-side",
                    f"“{core}” is split as {SEAM.join(pieces)} (hyphen goes "
                    f"before the cut). Correct split: {SEAM.join(want)}",
                    c.start, first + k, fix=_kept_of(chips), suggest=want,
                    md=_md_split(core, SEAM.join(pieces),
                                 " (hyphen goes before the cut)",
                                 SEAM.join(want), want))
            c.flag("hyphen-side", ERROR)


def _check_hyphens(rep: Report, row: Row) -> None:
    """A hyphen with nothing to join: three ways to write the same fault.

    A hyphen says the word carries on. The document then says it does not,
    and the reader is shown a mark hanging off the end of a word with a gap,
    or the end of the line, after it:

        the piece ends in one and the next piece is a new word. The player
        believes the boundary -- it is the thing that decides whether a space
        is drawn -- so the line comes out "Wha- wha- what", with the gap
        sitting after a hyphen that promised there would not be one. Two ways
        to arrive at THAT, and they are fixed differently, so the sentence
        says which: the piece carries a space of its own inside its text
        (which `word_ends` reads as the end of the word however the flag is
        set), or IsPartOfWord was simply not set on it. Six of these over the
        53 TTMLs in this folder, all in one song, all of the second kind --
        and the first kind is what a hyphen with a real space typed after it
        produces, which is the one people write by hand;

        the hyphen sits inside a piece with a space after it, which is the
        same line written without a seam at the hyphen at all: a line-timed
        document, a word timed whole, or a dash used as punctuation with air
        either side of it. Marked on the character rather than flagged on the
        piece, because the piece can be the whole line;

        the line ends on one. Nothing follows it in the row, so there is
        nothing for it to carry the word into -- a word cut off at the end of
        a line is written with the letters it got to and no mark, or with an
        em dash, which is punctuation rather than a joiner and is left alone
        here.

    Only these three, and only the hyphens: an em dash is not in JOINERS.
    """
    last = len(row.chips) - 1
    for i, c in enumerate(row.chips):
        text = c.text
        for k, ch in enumerate(text):
            if ch not in JOINERS:
                continue
            tail = text[k + 1:]
            if tail.strip():
                if not tail[0].isspace():
                    continue
                rep.say(row, ERROR, "hyphen-gap",
                        f"hyphen then a space in “{_around(text, k)}”", c.start, i)
                c.mark(k, k + 1, "hyphen-gap", ERROR,
                       "a hyphen with a space after it")
                continue
            if i == last:
                rep.say(row, ERROR, "hyphen-gap",
                        f"line ends on a hyphen: “{_said(text)}”",
                        c.start, i)
                c.flag("hyphen-gap", ERROR)
                continue
            if c.glue:
                continue
            nxt = row.chips[i + 1]
            why = ("space after the hyphen" if c.part
                   else "next piece not marked part of the word")
            rep.say(row, ERROR, "hyphen-gap",
                    f"“{_said(c.text)} {_said(nxt.text)}”: gap after a "
                    f"hyphen ({why})",
                    c.start, i)
            c.flag("hyphen-gap", ERROR)


def _digraph_at(word: str, cut: int) -> str:
    """The sound this cut goes through, if it goes through one.

    Asked of the letters either side of the seam rather than of the word: a
    digraph is two or three letters that spell one sound, so a cut is through
    it when the letters it separates are the ones that spell it.
    """
    low = word.lower()
    for d in DIGRAPHS:
        for at in range(max(0, cut - len(d) + 1), cut + 1):
            if low[at:at + len(d)] == d and at < cut < at + len(d):
                return d
    return ""


DASHES = "-‐‑‒–—"


def _bare(piece: str) -> str:
    """A piece with the punctuation a lyric hangs off it taken away."""
    return piece.strip().strip(".,!?;:'\u2019\"" + DASHES)


def _spelled(piece: str) -> bool:
    """Whether this piece is a letter being SAID rather than a syllable sung.

    "B-", "f-", "P-": a letter with a dash hanging off it, which is how
    everybody writes a stutter and how everybody writes a word spelled out
    loud. There is no vowel in "B", and the person timing it cut there on
    purpose, one tap per letter. Without this exemption the vowel test finds
    89 pieces across the 53 TTMLs in this folder rather than 59.

    The dash is what says so, not the length. A single letter on its own is
    only being spelled when the whole word is (see _initialism): the "w" of
    know, timed kn|o|w, is a piece of a word with no vowel in it and is
    exactly what this check is for.
    """
    return bool(piece.strip()) and piece.strip()[-1:] in DASHES


def _capitals(core: str) -> bool:
    """Whether this word is written in capitals throughout."""
    return (any(ch.isalpha() for ch in core)
            and not any(ch.islower() for ch in core))


def _tail(core: str) -> tuple:
    """A word in capitals with a small ending stuck on it: ("SSRI", "s").

    SSRIs, CDs, IDs, TVs. The capitals are the word and the ending is the
    grammar, and it is timed with the letter in front of it: S|S|R|Is.
    Without this an initialism stopped being one the moment somebody made it
    plural, and every letter of it was then a piece with no vowel in it.

    ("", "") for anything else, which includes a word that is all capitals --
    that is _capitals' question -- and a word like "Apple" whose one leading
    capital is just a capital.
    """
    letters = [ch for ch in core if ch.isalpha()]
    end = 0
    while end < len(letters) and letters[len(letters) - 1 - end].islower():
        end += 1
    head = letters[:len(letters) - end]
    if len(head) >= 2 and 0 < end <= 2 and all(ch.isupper() for ch in head):
        return "".join(head), "".join(letters[len(letters) - end:])
    return "", ""


def _spelled_shape(core: str) -> bool:
    """Whether the word LOOKS like one that is said a letter at a time."""
    return _capitals(core) or bool(_tail(core)[0])


def _letter_by_letter(core: str) -> str:
    """This word cut the way a word said letter by letter is cut: S|S|R|Is."""
    head, tail = _tail(core)
    if not head:
        return SEAM.join(ch for ch in core if not ch.isspace())
    return SEAM.join(list(head[:-1]) + [head[-1] + tail])


def _initialism(core: str, chips: list) -> bool:
    """Whether this whole word is being spelled out rather than sung.

    "O-D", "V-V-S", "F-R-I-E-N-D-S": every piece a single letter. Neither
    splitter has anything to say about these, and gc's own kept splits are
    full of them, which is where the shape of this test comes from. Worth 15
    of the vowel findings and 9 of the split ones over this folder's 53. A
    plural counts as one: SSRIs cut S|S|R|Is is the same word said the same
    way with an ending on it, and the ending is timed with the letter in front
    of it. See _tail.
    """
    pieces = [SL.unzwsp(c.text).strip() for c in chips]
    head, tail = _tail(core)
    if head and tail and pieces and pieces[-1].endswith(tail):
        pieces = pieces[:-1] + [pieces[-1][:-len(tail)]]
    return bool(pieces) and all(len(_bare(p)) <= 1 for p in pieces)


def _cuts_of(pieces: list) -> set:
    """Where a set of pieces puts its seams, as offsets into the word."""
    out, at = set(), 0
    for piece in pieces[:-1]:
        at += len(piece)
        out.add(at)
    return out


def _kept_of(chips: list) -> tuple | None:
    """The word these chips spell and how the document cuts it.

    What a finding about a seam carries so that the finding can be ANSWERED
    rather than only read: hand it to keep_split and the arrangement the
    document already has becomes the rule for that word.

    Two liberties are taken with the text, both of them the store's own. The
    zero-width spaces come out -- one is a word boundary drawn without a gap
    rather than part of the spelling, and a correction filed with one in it
    could never be looked up again -- and the punctuation stays ON, because
    `editor.syllables` peels it off itself and puts it back on whichever
    marks the word wears the next time it turns up. See bare_pieces there.

    None where the pieces cannot be stored as a split of the word at all: a
    piece that was nothing but a zero-width space, or a "word" that is all
    punctuation and has no spelling to rule on.
    """
    pieces = [SL.unzwsp(c.text) for c in chips]
    word = "".join(pieces)
    if len(pieces) < 2 or not all(pieces) or not SL.peel(word)[1]:
        return None
    return word, pieces


def corrections() -> dict:
    """Every split correction kept by hand, filed by the bare word.

    The editor's store, read through the editor -- the player has no store
    of its own and must not grow one, because the whole value of a
    correction is that the rule answers the same way in both windows and in
    the next song. Empty where the editor cannot be imported at all, which
    is also where _cutter falls back to the uncorrected sung rule.
    """
    try:
        from editor import syllables as SY
        return SY.overrides()
    except Exception:                                    # noqa: BLE001
        return {}


def keep_split(word: str, pieces: list) -> str:
    """Rule that this is how the word is cut. "" if it was kept, else why not.

    The answer to a seam the rules refused and the person stands by. It goes
    into the same store the editor's Syllabify dialog writes, which _cutter
    reads before either rule is consulted -- so the seam stops being raised
    here, in the editor, and in the next document that cuts the word this
    way. A kept arrangement of ONE piece is the other thing it can say:
    leave this word alone.
    """
    try:
        from editor import syllables as SY
    except Exception as exc:                             # noqa: BLE001
        return f"the editor is not importable from here — {exc}"
    try:
        if not SY.remember_split(word, list(pieces)):
            return f"“{SEAM.join(pieces)}” does not spell “{word}”"
    except Exception as exc:                             # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return ""


def forget_split(word: str) -> bool:
    """Put this word back under the rule. False if nothing was kept for it."""
    try:
        from editor import syllables as SY
        return SY.forget_split(word)
    except Exception:                                    # noqa: BLE001
        return False


def _kept_here(rep: Report) -> list[str]:
    """The words in this document a kept correction already answers for.

    Said on the page because a review that has been corrected looks exactly
    like one that never had anything to say, and the two are worth telling
    apart -- especially on somebody else's machine, where the corrections
    are somebody else's.
    """
    got = corrections()
    if not got:
        return []
    out, seen = [], set()
    for row in rep.rows:
        for first, last in _words(row.chips):
            word = SL.peel(SL.unzwsp(
                "".join(c.text for c in row.chips[first:last + 1])))[1]
            if word and word.lower() in got and word.lower() not in seen:
                seen.add(word.lower())
                out.append(word)
    return out


def _check_splits(rep: Report, row: Row, cut, second, names) -> None:
    """The document's own seams inside a word, against the editor's rule.

    A seam is only raised where BOTH splitters refuse it. They are wrong in
    different places and the second opinion costs nothing, so making the two
    of them agree takes out the whole class of false alarm this check would
    otherwise be full of: the sung rule reads "nosebleeds" as no-seb-leeds and
    "rewrite" as rew-rite, and hyphenation has both of them exactly as they
    were timed. What survives is a seam that neither a singer's rule nor a
    printer's patterns can account for -- wi-thout, teac-her -- which is what
    a slip of the hand looks like.

    A word the person has already ruled on is not raised at all, whichever
    splitter is asked: a kept correction wins inside `editor.syllables.split`
    before either rule is consulted, so both of them hand back the arrangement
    that person chose. See override_for.
    """
    for first, last in _words(row.chips):
        if last <= first:
            continue
        chips = row.chips[first:last + 1]
        word = "".join(c.text for c in chips)
        core = SL.unzwsp(word).strip()
        if not core or not any(ch.isascii() and ch.isalpha() for ch in core):
            continue
        if any(k in ("hyphen-side", "hyphen-gap")
               for c in chips for k, _lv in c.flags):
            continue
        if _initialism(core, chips):
            continue
        if any(ch.isdigit() for ch in core):
            continue
        as_cut = _cut_shown(c.text for c in chips)
        mine, at = [], 0
        for c in chips[:-1]:
            at += len(c.text)
            mine.append(at)
        try:
            pieces = cut(word)
            other = second(word) if second is not None else None
        except Exception:                                # noqa: BLE001
            continue
        if set(mine) == _cuts_of(pieces):
            continue
        fix = _kept_of(chips)
        sung = (pieces if names[0] == "the sung rule" or other is None
                else other if names[1] == "the sung rule" else pieces)
        right = _cut_shown(sung)
        # A split with a piece that has no vowel in it is a split like any
        # other, and answered the same way: K keeps it or corrects it.
        bare = []
        for k, c in enumerate(chips):
            piece = SL.unzwsp(c.text).strip()
            if piece and any(ch.isalpha() for ch in piece) \
                    and not any(ch.lower() in VOWELS for ch in piece) \
                    and not any(a in piece for a in APOSTROPHES) and "'" not in piece \
                    and not _spelled(piece) \
                    and any(ch.lower() in VOWELS for ch in core):
                bare.append((k, piece))
        if bare:
            k = bare[0][0]
            piece = "”, “".join(x for _k, x in bare)
            if _spelled_shape(core):
                rep.say(row, ERROR, "half-spelled",
                        f"“{core}” is split as {as_cut} (spelled out: {core} "
                        f"or {_letter_by_letter(core)}). "
                        + _correct(right, sung),
                        chips[k].start, first + k, fix=fix, suggest=list(sung),
                        md=_md_split(core, as_cut,
                                     f" (spelled out: *{_md(core)}* or "
                                     f"*{_md(_letter_by_letter(core))}*)",
                                     right, sung))
                for kk, _x in bare:
                    chips[kk].flag("half-spelled", ERROR)
            else:
                rep.say(row, ERROR, "no-vowel",
                        f"“{core}” is split as {as_cut} (no vowel in "
                        f"“{piece}”). " + _correct(right, sung),
                        chips[k].start, first + k, fix=fix, suggest=list(sung),
                        md=_md_split(core, as_cut,
                                     f' (no vowel in "{_md(piece)}")',
                                     right, sung))
                for kk, _x in bare:
                    chips[kk].flag("no-vowel", ERROR)
            continue
        theirs = _cuts_of(pieces)
        if other is not None:
            theirs |= _cuts_of(other)
        bad = []
        for seam in [m for m in mine if m not in theirs]:
            k, at = 0, 0
            for k, chip in enumerate(chips):
                at += len(chip.text)
                if at == seam:
                    break
            bad.append((k, _digraph_at(word, seam)))
        if not bad:
            continue
        # One finding for the word, however many of its seams are wrong: the
        # answer is one split of the whole word.
        k = bad[0][0]
        through = next((t for _k, t in bad if t), "")
        why = ""
        if through:
            kind, level = "split-digraph", ERROR
            says = f"“{core}” is split as {as_cut}, through “{through}”. "
            why = f', through "{through}"'
        elif len(pieces) == 1 and (other is None or len(other) == 1):
            kind, level = "split-whole", NOTE
            says = f"“{core}” is split as {as_cut}. "
        else:
            kind, level = "split", WARN
            says = f"“{core}” is split as {as_cut}. "
        rep.say(row, level, kind, says + _correct(right, sung),
                chips[k].start, first + k, fix=fix, suggest=list(sung),
                md=_md_split(core, as_cut, why, right, sung))
        for kk, _t in bad:
            chips[kk].flag(kind, level)


def _cut_shown(pieces) -> str:
    """Pieces joined at their seams, with the spaces inside them kept:
    'like, |"Who', not 'like,|"Who'. Only the ends of the whole are trimmed."""
    return SEAM.join(SL.unzwsp(p or "") for p in pieces).strip()


def _correct(right: str, sung: list) -> str:
    """The answer to a split finding, on the same line as it."""
    if len(sung) <= 1:
        return "Should not be split."
    return f"Correct split: {right}"


def _check_between(rep: Report, rows: list[Row]) -> None:
    """Lines running through each other, and lines out of order.

    An ad-lib is written inside its line and is SUNG over it, so a backing
    group crossing the lead it belongs to is the format working as intended
    and is not reported at all.

    Two LEAD lines crossing is reported, at any amount -- the first
    millisecond of it counts, and the amount is in the sentence -- but only as
    something worth a look. It is not necessarily wrong: two singers trade
    lines that overlap, a line is held under the one that follows it, and a
    word left ringing over the start of the next line is a real thing a real
    recording does. What it is, always, is a decision somebody should have
    made on purpose, which is exactly what this screen is for showing them.

    Inside one line the same crossing IS a fault and is filed as one, because
    there the two things are one voice singing two words at once. See
    _check_times.

    Two sentences, because there are two different things to see. Where the
    WORDS of one line are still going when the next begins, that is two
    voices crossing and the line is what runs long. Where they stopped in
    time and only the line's stated end crosses, nothing was sung over
    anything: the number lives in the <p> end, an exporter wrote it, and the
    finding says so rather than describing an overlap a reader will not find
    in the words. It is the same fault as line-end-short from the other side
    -- a stated end that disagrees with the singing -- and it is only ever
    worth a look, because the player plays to the end of the words anyway.
    """
    lead = [r for r in rows if r.kind == "lead" and r.start is not None]
    for i in range(len(lead) - 1):
        a, b = lead[i], lead[i + 1]
        if b.start < a.start - EPS:
            rep.say(b, ERROR, "lines-out-of-order",
                    f"starts at {_fmt(b.start)}, before the line above "
                    f"({_fmt(a.start)})")
            continue
        last = a.last()
        if last is None:
            continue
        over = last - b.start
        if over <= EPS:
            continue
        # Everything sung in the line counts, its ad-libs as well as its lead:
        # "It's way too late for you to leave now (Get ready)" stops its lead
        # at 0:33.466 and sings "Get ready" to 0:34.287, and "nothing is sung
        # in that time" was said of the ad-lib still going.
        ends = [c.end for r in rows if r.group == a.group
                for c in r.chips if c.end is not None]
        sung = max(ends) if ends else None
        says = f"runs {_ms(over)} into the next line"
        if sung is not None and a.end is not None and sung - b.start <= EPS:
            # Only the <p> end crosses: an exporter wrote it, and nothing is
            # sung over anything. Filed apart so it can be ignored apart.
            rep.say(a, NOTE, "line-end-long", says)
            continue
        rep.say(a, NOTE, "line-overlap", says)
    for r in rows:
        if r.kind != "bg" or r.start is None:
            continue
        for x in lead:
            if x.group == r.group:
                continue
            last = x.last()
            if last is None:
                continue
            if x.start - EPS < r.start < last - EPS:
                rep.say(r, NOTE, "adlib-overlap",
                        f"ad-lib starts inside line {x.n} ({_fmt(r.start)})")
                break


def _worded(rows: list[Row]) -> bool:
    """Whether this document is timed word by word rather than line by line.

    Asked of the document itself rather than of the Type it claims to be:
    NetEase, QQ Music and Kugou all stamp "Syllable" on whatever they hand
    over, and the rest of this program has read the data instead for exactly
    that reason (see LS.quality, and the note in info_rows).
    """
    return any(len([c for c in r.chips if c.start is not None]) > 1
               for r in rows if r.kind == "lead")


PARENS = "()"


def _check_parens(rep: Report, rows: list[Row]) -> None:
    """Ad-libs typed into the line, in a document that can hold them properly.

    A word-timed document has somewhere for a backing vocal to go: a
    Background group, sung over its line, drawn in the smaller type hanging
    off it and timed on its own. A line that spells one out instead --
    "You're not who I love (Huh)" -- is a line whose words include two
    brackets nobody sings, and every one of them is then timed as part of the
    lead: the singer's line is stretched over an ad-lib they are not singing,
    and the ad-lib cannot be drawn where ad-libs go.

    Only where the document IS word-timed. A line-timed source has no
    Background groups to put anything in and writes its ad-libs in brackets
    because that is the only thing it can do, and telling somebody their
    LRCLIB copy is wrong helps nobody.

    Measured over the 53 TTMLs in this folder: 78 lead lines across 12
    word-timed documents, and not one ad-lib group with a bracket in it --
    so this says something about the lead groups only, and there is no
    exemption to write for the other side.
    """
    if not _worded(rows):
        return
    for row in rows:
        if row.kind != "lead":
            continue
        said = row.text()
        if not any(ch in said for ch in PARENS):
            continue
        inside = re.findall(r"\([^)]*\)?", said) or ["()"]
        rep.say(row, ERROR, "parens",
                f"“{inside[0]}” is typed into the line; make it an ad-lib")
        for ci, chip in enumerate(row.chips):
            for i, ch in enumerate(chip.text):
                if ch in PARENS:
                    chip.mark(i, i + 1, "parens", ERROR,
                              "a bracket in the line's own words")


def _spelled_word(word: str) -> bool:
    """Whether a whole word is being spelled out: B-A-B-Y, F-R-I-E-N-D-S."""
    parts = [p for p in re.split("[" + re.escape(DASHES) + "]", word) if p]
    return len(parts) > 1 and all(len(_bare(p)) <= 1 for p in parts)


def _case_of(text: str) -> str:
    """How a line is cased: "upper", "lower", "title", or "" for ordinary.

    Three things are deliberately not asked about. A word spelled out is not
    evidence of anything -- "Like B-O-Y" is not a line in capitals -- and nor
    is a script with no capitals to use: Hangul and kana have no case at all,
    and counting them as "no capital anywhere" would put a warning on every
    line of every Korean song. And the first word of a line is capitalised
    because it is the first word, so title case is judged on the rest.

    Title case wants four words before it will say anything, because the
    shape it is looking for -- a scrape that took the styling of a song title
    with it -- is a whole line of capitals, and at two or three words it is
    also the shape of an ordinary line that happens to name something. "In
    New York" is three words, every one of them capitalised, and perfectly
    written.
    """
    words = [w for w in re.split(r"\s+", text.strip())
             if any(c.isupper() or c.islower() for c in w)]
    cased = [c for c in "".join(words) if c.isupper() or c.islower()]
    if len(words) < 2 or not cased:
        return ""
    first = next((c for c in text if c.isalpha()), "")
    if not any(c.isupper() for c in cased):
        # A line that opens in a script with no capitals -- 愛してる baby,
        # 私は you and me -- has no start to capitalise, and what follows it
        # in Latin letters is the middle of a sentence.
        return "lower" if first.isupper() or first.islower() else ""
    spoken = [w for w in words if not _spelled_word(w)]
    said = [c for c in "".join(spoken) if c.isupper() or c.islower()]
    if len(spoken) < 2 or not said:
        return ""
    if not any(c.islower() for c in said):
        return "upper"
    rest = [w for w in words[1:] if not _spelled_word(w)]
    heads = [w for w in rest if next((c for c in w if c.isalpha()), "").isupper()]
    if rest and len(heads) == len(rest) and len(words) >= 4:
        return "title"
    return ""


CASE_SAYS = {
    "upper": "line is all capitals",
    "lower": "line has no capitals, not even the first letter",
    "title": "every word is capitalised, like a title",
}
CASE_STYLE = {
    "upper": "lines in capitals",
    "lower": "lines with no capitals",
    "title": "lines in title case",
}
CASE_STYLE_AT = 0.5
CASE_STYLE_MIN = 7


# The pronoun, and the contractions that are the same word with something
# hung on the end of it. "i" is the one English word whose capital is not
# optional and not a style: it is how the word is spelled.
# The tags the catalogues hand out for songs sung in English; see _check_i.
ENGLISH_ENOUGH = {"en", "eng", "pcm", "sco", "jam"}

LONE_I = re.compile(r"^i(?:['\u2019](?:m|ve|ll|d))?$")


def _check_i(rep: Report, rows: list[Row]) -> None:
    """A lower-case "i" standing on its own, in an English lyric.

    English capitalises the pronoun wherever it falls, which is why this is a
    spelling rather than a matter of taste: "yesterday i was" is wrong in a
    way "yesterday Was" is not, and a transcript typed in a hurry is full of
    them.

    Only where the document says it is English, because "i" is an ordinary
    word in Italian, a letter in Dutch and Danish compounds, and a pronoun
    that is not capitalised in most of the languages this reads. A document
    with no tag is taken at its default, which is English.

    THE TAG IS NOT ALWAYS "en", and refusing anything else would have left a
    third of this library unchecked. Of 400 documents here, 110 are tagged
    `pcm` -- Nigerian Pidgin -- and 17 `sco`, Scots, and they are Dua Lipa,
    Queen, Eminem and the SpongeBob theme: the catalogues guess the language
    and guess it badly on anything sung with an accent. Both of those, and
    Jamaican Patois with them, are English-lexifier and write the pronoun the
    same way, so a wrong guess costs nothing here and refusing them costs the
    check.

    Softened to a note where the whole lyric is written in lower case, on the
    same grounds _check_case softens itself: somebody who typed forty lines
    without a capital did not miss this one, and forty warnings about a style
    are forty ways of saying nothing. Still said line by line, though, because
    unlike a line's case this one has a place in the words -- it is a mark on
    a syllable, and it is the mark that makes it findable and fixable.
    """
    if not str(rep.lang or "en").lower().split("_")[0] in ENGLISH_ENOUGH:
        return
    lead = [r for r in rows if r.kind == "lead" and r.text().strip()]
    lower = sum(1 for r in lead if _case_of(r.text()) == "lower")
    style = len(lead) >= CASE_STYLE_MIN and lower >= len(lead) * CASE_STYLE_AT
    level = NOTE if style else WARN
    for row in rows:
        for first, last in _words(row.chips):
            core = "".join(c.text for c in row.chips[first:last + 1])
            bare = core.strip().strip(BARE_PUNCT)
            if not LONE_I.match(bare):
                continue
            chip = row.chips[first]
            at = chip.text.find("i")
            said = f"“{bare}” should be capital I"
            rep.say(row, level, "lower-i", said, chip.start, first)
            if at >= 0:
                chip.mark(at, at + 1, "lower-i", level, said)
            else:
                chip.flag("lower-i", level)


BARE_PUNCT = " \t.,!?;:()[]{}\"\u201c\u201d\u2018\u2019-\u2014\u2013"


def _check_case(rep: Report, rows: list[Row]) -> None:
    """Lines shouting, whispering, or dressed as titles.

    Said once about the document where it is how the document is written --
    plenty of people write a whole lyric in lower case on purpose, and a
    warning on all forty lines of one of those is forty ways of saying
    nothing.
    """
    lead = [r for r in rows if r.kind == "lead" and r.text().strip()]
    seen = [(r, _case_of(r.text())) for r in lead]
    counts: dict = {}
    for _r, kind in seen:
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    style = {k for k, n in counts.items()
             if len(seen) >= CASE_STYLE_MIN and n >= len(seen) * CASE_STYLE_AT}
    # A line in capitals is flagged on its own however many there are: it
    # is the one of these that is almost never the document's style and
    # almost always a line pasted from somewhere that shouts.
    style.discard("upper")
    for kind in sorted(style):
        rep.say(None, NOTE, f"case-{kind}",
                f"{CASE_STYLE[kind]}: {counts[kind]} of {len(seen)}, so a style")
    for row, kind in seen:
        if kind and kind not in style:
            rep.say(row, WARN, f"case-{kind}", CASE_SAYS[kind])


def _check_document(rep: Report, rows: list[Row], length: float) -> None:
    """The things that are about the file rather than about any one line."""
    timed = [r for r in rows if r.start is not None]
    if not timed:
        rep.say(None, NOTE, "unsynced", "nothing in this document is timed")
        return
    if length and length > 0:
        ends = [c.end for r in rows for c in r.chips if c.end is not None]
        over = [e for e in ends if e > length + 0.05]
        if over:
            rep.say(None, ERROR, "past-the-end",
                    f"{len(over)} piece{'' if len(over) == 1 else 's'} past the "
                    f"track's end ({_fmt(max(ends))} vs {_fmt(length)})")
    seen: dict = {}
    for r in rows:
        if r.kind != "lead" or r.start is None:
            continue
        key = (r.text().strip().lower(), round(r.start, 3))
        if not key[0]:
            continue
        if key in seen:
            rep.say(r, WARN, "duplicate",
                    f"same words, same time as line {seen[key]}")
        else:
            seen[key] = r.n
    for r in rows:
        if r.start is not None and not r.text().strip():
            rep.say(r, WARN, "empty-line",
                    f"timed line with no words ({_fmt(r.start)})")


FEAT = re.compile(r"[\(\[]\s*(?:feat|ft|featuring|with)\.?\s+([^\)\]]+)[\)\]]",
                  re.I)
FEAT_APART = re.compile(r"\s*(?:,|&|\bx\b|\band\b)\s*", re.I)


def _featured(*texts) -> list[str]:
    """The guests named in any of these, in the order they are named."""
    out: list[str] = []
    for text in texts:
        for chunk in FEAT.findall(str(text or "")):
            for name in FEAT_APART.split(chunk):
                name = name.strip(" .\u2014-")
                if name and name.lower() not in [o.lower() for o in out]:
                    out.append(name)
    return out


def _check_credits(rep: Report, doc: dict, rows: list[Row],
                   title: str, artist: str) -> None:
    """The header, against what the song is: who wrote it, and who sings it.

    Two things a document can be complete as a lyric and still be missing,
    neither of which any amount of reading the words will show.

    The songwriters, because <songwriters> is the one field in an Apple-style
    <head> that says anything about the song at all, and a file published
    without it credits nobody. The editor can look them up (editor.sources
    .songwriters), which is why this is worth saying rather than shrugging
    at: it is a field somebody forgot, not a fact nobody has. An LRC has
    nowhere to put them and will always be told so, which is true.

    And a guest with nothing to sing. Where the song is credited "(feat.
    Somebody)" and every line in the document is written for the one voice,
    either the guest's lines are filed as the lead singer's -- which is what
    the second agent exists to say, and what a player draws on the other side
    of the screen -- or the guest really is only on the hook. Both happen, so
    it is a note and never a fault.

    ONE WAY ONLY. A duet with no feature in its title is not raised and must
    not be: a song by two credited artists is sung by two of them and names
    neither as a guest, which is the ordinary shape of half the duets there
    are, and "why is there a second voice here" is a question with an obvious
    answer and no fix.
    """
    writers = [w for w in (doc.get("SongWriters") or [])
               if str(w or "").strip()]
    if not writers:
        rep.say(None, WARN, "no-writers",
                "no songwriter credits")
    named = _featured(title or doc.get("Title"), artist or doc.get("Artist"),
                      rep.whose)
    if named and not any(r.opposite for r in rows):
        who = named[0] if len(named) == 1 else (
            ", ".join(named[:-1]) + " and " + named[-1])
        rep.say(None, NOTE, "one-voice",
                f"{who} is a guest, but every line is one voice "
                f"(guest lines use agent v2)")


# ----------------------------------------------------------------- the whole
def _cutter(rule: str, lang: str):
    """Who says where a word comes apart: (rule, cut, other rule, cut).

    The editor's splitter, wherever the editor can be imported -- that is the
    whole point of using it rather than SL.syllabify, which is the same sung
    rule without any of the corrections: `editor.syllables` checks the kept
    splits first, so a word the person has already ruled on comes back the way
    they ruled and is never raised with them again.

    The second opinion is the OTHER method, and it is what makes this check
    quiet enough to read (see _check_splits). It is left out where pyphen is
    not installed or has no patterns for this language -- then a seam is
    judged on one rule, which is stricter, and the screen says so.
    """
    if rule == "off":
        return "not checked", None, "", None
    try:
        from editor import syllables as SY
        if not SY.split("forever", rule, lang):
            raise ValueError("the splitter answered with nothing")
    except Exception:                                    # noqa: BLE001
        return "sung", (lambda word: SL.syllabify(word)), "", None
    other = "hyphen" if rule == "sung" else "sung"
    hyph = _hyphens_for(lang)

    def name(which: str) -> str:
        """What to call a splitter, with the patterns named where they differ.

        A document tagged `pcm` held to en-us patterns is being held to
        somebody else's language, and the screen has to say so -- it is the
        difference between "the rule disagrees" and "an English rule
        disagrees with your Dutch".
        """
        if which == "sung":
            return "the sung rule"
        return "hyphenation" + (f" ({hyph} patterns)"
                                if hyph.split("_")[0] != lang.split("_")[0] else "")

    if not hyph:
        return "the sung rule", (lambda word: SY.split(word, "sung", lang)), "", None
    use = lang if other == "sung" else hyph
    first = lang if rule == "sung" else hyph
    return (name(rule), (lambda word: SY.split(word, rule, first)),
            name(other), (lambda word: SY.split(word, other, use)))


def _hyphens_for(lang: str) -> str:
    """The pattern set to hyphenate this language with, or "" for none.

    English is the last resort rather than a refusal. A tag pyphen has never
    heard of is usually a language written in the Latin alphabet with an
    English-shaped lexicon behind it -- gc's own files are tagged `pcm`,
    Nigerian Pidgin, and are full of English words -- and the second opinion
    is only ever used to EXCUSE a seam the first rule refused. Consulting the
    wrong patterns can therefore let a real slip through; it cannot invent a
    fault, which is the failure worth avoiding here.
    """
    try:
        import pyphen
        have = set(pyphen.LANGUAGES)
    except Exception:                                    # noqa: BLE001
        return ""
    for want in (PREFER.get(lang, lang), lang,
                 PREFER.get(lang.split("_")[0], lang.split("_")[0]), "en_US"):
        if want and want in have:
            return want
    return ""


PREFER = {"en": "en_US"}


def _lang_of(doc: dict, want: str = "") -> str:
    """The document's own language tag, in the shape pyphen names them."""
    got = str(want or (doc or {}).get("Language") or "").strip().replace("-", "_")
    return got or "en"


LANGUAGES = ("en_US", "nl", "fr", "de", "es", "it", "pt", "sv", "pl", "ru",
             "tr", "id", "da", "nb")


def languages(doc=None) -> list:
    """What the language can be set to here: the file's own tag, then these."""
    have = []
    try:
        import pyphen
        known = set(pyphen.LANGUAGES)
    except Exception:                                    # noqa: BLE001
        known = set()
    own = _lang_of(SL.payload(doc or {}))
    for lang in (own,) + LANGUAGES:
        if lang not in have and (lang == own or lang in known):
            have.append(lang)
    return have


def _rule_for(rule: str, lang: str) -> str:
    """Which splitter to hold the document to.

    "auto" is the editor's own measured advice, applied: the sung rule for
    English, where it was written and where it agrees with the hand splits in
    this folder 90% of the time -- and hyphenation for a language whose rules
    this project has never encoded, where pyphen ships patterns and the sung
    rule is guessing. See the table at the top of editor/syllables.py.
    """
    if rule in ("sung", "hyphen", "off"):
        return rule
    if lang.split("_")[0] in ("en", ""):
        return "sung"
    return "hyphen" if _hyphens_for(lang) == lang.split("_")[0] \
        or _hyphens_for(lang) == lang else "sung"


# ------------------------------------------------ seams, ignores, own flags
def _list_seams(rep: Report, cut, second, names) -> None:
    """Every word the document splits, as it is split, one to a finding.

    Not a judgement -- see LISTED. The splits tab shows the seams a rule
    refused; this shows all of them, down a column under each line, so a
    whole song's splitting can be read at a glance and a bad one corrected
    wherever it is, whether or not a rule would have raised it.
    """
    for row in rep.rows:
        for first, last in _words(row.chips):
            if last <= first:
                continue
            chips = row.chips[first:last + 1]
            word = "".join(c.text for c in chips)
            core = SL.unzwsp(word).strip()
            if not core:
                continue
            try:
                pieces = cut(word)
                other = second(word) if second is not None else None
            except Exception:                            # noqa: BLE001
                pieces, other = [word], None
            sung = (pieces if names[0] == "the sung rule" or other is None
                    else other if names[1] == "the sung rule" else pieces)
            rep.say(row, NOTE, "seam",
                    _cut_shown(c.text for c in chips),
                    chips[0].start, first, fix=_kept_of(chips), suggest=list(sung))


# Where what the person has said about reviews is kept: what to leave out,
# and flags of their own. Set by whoever hosts the review (the window points
# it into its config directory); None keeps everything in memory, which is
# what the tests and the command line want.
STORE: pathlib.Path | None = None
_MEMORY: dict = {}


def marks() -> dict:
    """{"ignore": [rule, ...], "flags": [flag, ...], "templates": [...],
    "asked": [...]} -- whatever has been kept, with every list present."""
    got: dict = dict(_MEMORY)
    if STORE is not None:
        try:
            got = json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            got = {}
    for k in ("ignore", "flags", "templates", "asked"):
        if not isinstance(got.get(k), list):
            got[k] = []
    if not got["templates"]:
        got["templates"] = [dict(t) for t in TEMPLATES]
    return got


def keep_marks(got: dict) -> None:
    global _MEMORY
    if STORE is None:
        _MEMORY = json.loads(json.dumps(got))
        return
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".part")
        tmp.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(STORE)
    except Exception:                                    # noqa: BLE001
        pass


TEMPLATES = (
    {"says": "Please resync {word}", "level": WARN},
    {"says": "Wrong words here", "level": ERROR},
    {"says": "Timing is off on this line", "level": WARN},
)


def line_key(row: Row) -> str:
    """A line as an ignore or a flag remembers it: its words, folded."""
    return " ".join(SL.unzwsp(row.text()).split()).casefold()


def ignored(held: dict, song: str, f: dict, rows: list) -> bool:
    """Whether a rule the person made keeps this finding off the page.

    Four sizes of rule: one finding on one line of one song; every finding
    saying the same thing, anywhere (a kind and its sentence); every finding
    of that kind, anywhere ("runs Xms into the next line", all of them); and
    every finding at a level ("worth a look", all of them).
    """
    row = rows[f["row"]] if f.get("row") is not None else None
    for r in held.get("ignore") or []:
        if not isinstance(r, dict):
            continue
        if r.get("level") and r.get("level") == f["level"] and not r.get("kind"):
            return True
        if r.get("kind") and r.get("kind") == f["kind"] and not r.get("song") \
                and r.get("says", f["says"]) == f["says"] \
                and r.get("shape", shape(f["says"])) == shape(f["says"]):
            return True
        if (r.get("song") and r.get("song") == song and row is not None
                and r.get("kind") == f["kind"] and r.get("text") == line_key(row)
                and r.get("says", f["says"]) == f["says"]):
            return True
    return False


NUMBERS = re.compile(r"\d+(?:[:.,]\d+)*")


def shape(says: str) -> str:
    """A finding with its numbers taken out, which is what "the same" means
    when ignoring every one like it: "runs 117ms into the next line" and
    "runs 300ms into the next line" are one complaint."""
    return NUMBERS.sub("#", says or "")


def ignore(rule: dict) -> None:
    got = marks()
    if rule not in got["ignore"]:
        got["ignore"].append(rule)
    keep_marks(got)


def unignore(rule: dict) -> bool:
    got = marks()
    if rule not in got["ignore"]:
        return False
    got["ignore"].remove(rule)
    keep_marks(got)
    return True


def _flags_on(rep: Report, held: dict, song: str) -> None:
    """The person's own flags, put on the lines they were put on.

    A flag remembers the line by its words, so it stays on the line through
    a re-timing, and one given to every line that reads the same is on all
    of them, the ones added since included.
    """
    for fl in held.get("flags") or []:
        if not isinstance(fl, dict) or fl.get("song") != song:
            continue
        level = fl.get("level") if fl.get("level") in LEVELS else WARN
        for row in rep.rows:
            if row.kind != "lead" or line_key(row) != fl.get("text"):
                continue
            if not fl.get("all") and row.n != fl.get("line"):
                continue
            rep.say(row, level, "custom", str(fl.get("says") or ""))


def add_flag(song: str, row: Row, says: str, level: str, every: bool) -> dict:
    fl = {"song": song, "text": line_key(row), "line": row.n,
          "says": says, "level": level, "all": bool(every)}
    got = marks()
    got["flags"].append(fl)
    keep_marks(got)
    return fl


def drop_flag(fl: dict) -> bool:
    got = marks()
    if fl not in got["flags"]:
        return False
    got["flags"].remove(fl)
    keep_marks(got)
    return True


def review(doc, *, whose: str = "", length: float = 0.0, rule: str = "auto",
           lang: str = "", title: str = "", artist: str = "",
           song: str = "") -> Report:
    """Read a document and say everything that looks wrong with it.

    `title` and `artist` are what the PLAYER knows about the song, which is
    more than the file does: an Apple-style <head> carries the songwriters
    and nothing else, so a document that is credited "(feat. Somebody)" on
    the service it came from says so nowhere in itself. Where they are not
    given, whatever the document does carry is used -- an amll:meta title or
    artist, and the name this copy is being reviewed under.
    """
    doc = SL.payload(doc or {})
    items = [x for x in (doc.get("Content") or []) if isinstance(x, dict)]
    lang = _lang_of(doc, lang)
    rule, cut, other, second = _cutter(_rule_for(rule, lang), lang)
    rep = Report(rule, lang, whose)
    rep.second = other
    for n, item in enumerate(items, 1):
        lead = item.get("Lead") if isinstance(item.get("Lead"), dict) else None
        groups = [("lead", lead if lead is not None else item)]
        bg = item.get("Background")
        for g in (bg if isinstance(bg, list) else [bg] if isinstance(bg, dict) else []):
            if isinstance(g, dict):
                groups.append(("bg", g))
        for kind, group in groups:
            row = Row(n, kind, n)
            src = group if isinstance(group, dict) else {}
            start, end = src.get("StartTime"), src.get("EndTime")
            if not isinstance(start, (int, float)) and kind == "lead":
                start = item.get("StartTime")
            if not isinstance(end, (int, float)) and kind == "lead":
                end = item.get("EndTime")
            row.start = float(start) if isinstance(start, (int, float)) else None
            row.end = float(end) if isinstance(end, (int, float)) else None
            row.opposite = bool(item.get("OppositeAligned"))
            row.chips = _chips_of(src)
            if not row.chips:
                text = src.get("Text") if src is not item else item.get("Text")
                if isinstance(text, str) and text.strip():
                    row.chips = [Chip(text, row.start, row.end, False)]
            rep.rows.append(row)
            _check_text(rep, row)
            _check_hyphens(rep, row)
            _check_hyphen_side(rep, row)
            _check_times(rep, row)
            if cut is not None:
                _check_splits(rep, row, cut, second, (rule, other))
            _check_line_text(rep, row, item if kind == "lead" else src)
    _check_between(rep, rep.rows)
    _check_pairs(rep, rep.rows)
    _check_parens(rep, rep.rows)
    _check_case(rep, rep.rows)
    _check_i(rep, rep.rows)
    _check_document(rep, rep.rows, length)
    _check_credits(rep, doc, rep.rows, title, artist)
    if cut is not None:
        _list_seams(rep, cut, second, (rule, other))
    held = marks()
    _flags_on(rep, held, song)
    crossed = {f["row"] for f in rep.findings if f["kind"] == "line-overlap"}
    typed = {f["row"] for f in rep.findings if f["kind"] == "parens"}
    rep.findings = [
        f for f in rep.findings
        if not (f["kind"] == "line-end-short" and f["row"] in crossed)
        and not (f["kind"] == "brackets" and f["row"] in typed)]
    rep.kept = _kept_here(rep) if cut is not None else []
    rep.song = song
    for f in rep.findings:
        f["ignored"] = ignored(held, song, f, rep.rows)
    rep.counts = {lv: sum(1 for f in rep.findings if f["level"] == lv
                          and not f["ignored"]
                          and group_of(f["kind"]) not in LISTED)
                  for lv in LEVELS}
    rep.findings.sort(key=lambda f: (f["row"] if f["row"] is not None else 1 << 30,
                                     LEVELS.index(f["level"])))
    for row in rep.rows:
        row.found = []
    for k, f in enumerate(rep.findings):
        if f["row"] is not None:
            rep.rows[f["row"]].found.append(k)
    return rep


def main(argv: list[str]) -> int:
    import lyric_sources as LS
    if not argv:
        print(__doc__.strip().splitlines()[0])
        print("\n    python3 mild-lyrics/review.py <file.ttml> [...]")
        return 2
    worst = 0
    for name in argv:
        path = pathlib.Path(name)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            body = LS.parse_lrc(text) if path.suffix.lower() in (".lrc", ".elrc") \
                else LS.parse_ttml(text)
        except Exception as exc:                         # noqa: BLE001
            print(f"{path.name}: could not read it — {exc}")
            worst = max(worst, 1)
            continue
        rep = review(body, whose=path.name)
        print(rep.as_text())
        print()
        worst = max(worst, 1 if rep.counts[ERROR] else 0)
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
