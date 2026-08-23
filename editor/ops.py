"""Every edit the buttons make, as plain functions over a Doc.

Each one takes the document and returns a short sentence saying what it did,
or None when it could not do anything -- the window turns the first into a
toast and an undo entry, and the second into a quiet no-op. Keeping them out
of the widgets is what makes them testable and what makes undo a snapshot of
one call rather than of whatever the UI happened to touch.

Two rules hold throughout:

  * the last syllable of a group is never `part` -- there is nothing after it
    to be joined to, and a stray flag there spells the next line's first word
    onto the end of this one;
  * times are never invented. An operation that cannot know a time leaves it
    None, and the timing tab shows untimed pieces as untimed.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "aligner", _HERE.parent)
                if str(p) not in sys.path]

import spicy_lyrics as SL       # noqa: E402

from .model import Doc, Group, Line, Syl  # noqa: E402


def _tidy(g: Group) -> Group:
    g.syls = [s for s in g.syls if s.text.strip()]
    if g.syls:
        g.syls[-1].part = False
    return g


def _at(doc: Doc, idx: int, voice: int = 0) -> Group | None:
    return doc.group(idx, voice)


# --------------------------------------------------------------------- words
def split_word(doc: Doc, idx: int, voice: int, syl: int, cut: int) -> str | None:
    """Cut one syllable in two at character `cut`, keeping them one word.

    This is the manual half of syllable splitting: the automatic one guesses
    from spelling, and this is for the times it guesses wrong or for a word
    sung across a boundary no dictionary knows about.

    The time is split in proportion to the letters, which is a guess -- but a
    guess that puts the new boundary inside the word rather than at one end,
    so nudging it is a nudge and not a rescue.
    """
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls):
        return None
    s = g.syls[syl]
    if not 0 < cut < len(s.text):
        return None
    left, right = s.text[:cut], s.text[cut:]
    a = b = None
    if s.timed and s.end is not None and s.end > s.start:
        a = s.start + (s.end - s.start) * cut / max(len(s.text), 1)
        b = a
    first = Syl(left, s.start, a if a is not None else s.end, True)
    second = Syl(right, b if b is not None else s.start, s.end, s.part)
    g.syls[syl:syl + 1] = [first, second]
    return f"split {left}|{right}"


def split_at(doc: Doc, idx: int, voice: int, syl: int,
             cuts: list[int]) -> str | None:
    """Cut one syllable at the given character offsets, all at once.

    The offsets are into the syllable as WRITTEN, which is what a person
    points at. Times are shared out by letters, so the new boundaries land
    inside the word rather than at one end -- close enough that nudging one
    is a nudge and not a rescue.
    """
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls):
        return None
    s = g.syls[syl]
    want = sorted({int(c) for c in cuts if 0 < int(c) < len(s.text)})
    if not want:
        return None
    pieces, prev = [], 0
    for c in want:
        pieces.append(s.text[prev:c])
        prev = c
    pieces.append(s.text[prev:])
    made = _spread(pieces, s)
    made[-1].part = s.part
    g.syls[syl:syl + 1] = made
    return f"split {'|'.join(pieces)}"


def split_everywhere(doc: Doc, word: str, pieces: list[str],
                     skip: tuple | None = None) -> int:
    """Spell every other copy of this word the same way. Returns how many.

    The same word is sung the same way all through a song, so a split made
    once is a decision about the word rather than about the line it happens
    to be on. Matched without regard to case and re-cased onto whatever each
    line actually says, so "Somethin'" follows "somethin'".

    A copy that is already split is glued back together first and cut again,
    keeping its span: "apply this everywhere" means everywhere.
    """
    want = "".join(pieces)
    if not want or not word:
        return 0
    lens, done = [len(x) for x in pieces], 0
    for i, ln in enumerate(doc.lines):
        for v, g in enumerate(ln.groups()):
            for w in range(len(g.words()) - 1, -1, -1):
                run = g.words()[w]
                if skip is not None and (i, v, run[0]) == skip:
                    continue
                here = g.word_text(run)
                if here.lower() != word.lower():
                    continue
                if len(run) > 1:
                    merge_syllables(doc, i, v, run[0], run[-1])
                    run = [run[0]]
                s = g.syls[run[0]]
                if len(s.text) != len(want):
                    continue
                at, made = 0, []
                for n in lens:
                    made.append(s.text[at:at + n])
                    at += n
                got = _spread(made, s)
                got[-1].part = s.part
                g.syls[run[0]:run[0] + 1] = got
                done += 1
    return done


def syllabify(doc: Doc, idx: int, voice: int, words: list[int] | None = None,
              method: str = "sung", lang: str = "en_US",
              resplit: bool = False) -> str | None:
    """Cut whole words into syllables.

    `method` picks the rule -- see editor/syllables.py, which also carries the
    measurement that decided the default. Whatever it answers, the pieces
    rejoin to the word: the split may be wrong, but the lyric cannot change.

    Words already cut into pieces are left alone unless `resplit` is asked
    for, because those pieces may have been placed by hand or measured from
    the audio, and re-cutting them throws that away. `resplit` glues them back
    together first, keeping the span, and cuts again.
    """
    from . import syllables as SY
    g = _at(doc, idx, voice)
    if not g:
        return None
    got = g.words()
    want = list(range(len(got))) if words is None else [w for w in words
                                                       if 0 <= w < len(got)]
    done = 0
    for wi in sorted(want, reverse=True):
        run = got[wi]
        if len(run) > 1:
            if not resplit:
                continue
            merge_syllables(doc, idx, voice, run[0], run[-1])
            run = [run[0]]
        s = g.syls[run[0]]
        pieces = SY.split(s.text, method, lang)
        if len(pieces) < 2:
            continue
        g.syls[run[0]:run[0] + 1] = _spread(pieces, s)
        done += 1
    return f"cut {done} word(s) into syllables" if done else None


def _spread(pieces: list[str], s: Syl) -> list[Syl]:
    """One syllable's text and time shared out over the pieces it spells.

    A piece ending in whitespace is a WORD ending, not a syllable one: the
    space goes, and the flag says so, which is how the line still reads "do
    your" rather than "doyour". A zero-width space means the same boundary
    drawn without a gap, so it stays in the text and the flag does not
    change -- the files this reads use it to hold two words in one timing.
    """
    out = []
    total = sum(len(p) for p in pieces) or 1
    at = 0
    for i, p in enumerate(pieces):
        a = b = None
        if s.timed and s.end is not None and s.end > s.start:
            a = s.start + (s.end - s.start) * at / total
            b = s.start + (s.end - s.start) * (at + len(p)) / total
        elif s.timed:
            a = b = s.start
        at += len(p)
        text, part = p, (True if i < len(pieces) - 1 else s.part)
        if p != p.rstrip() and p.strip():
            text, part = p.rstrip(), False
        out.append(Syl(text, a, b, part))
    return [y for y in out if y.text] or [Syl(s.text, s.start, s.end, s.part)]


def merge_syllables(doc: Doc, idx: int, voice: int, lo: int, hi: int) -> str | None:
    """Glue syllables lo..hi (inclusive) back into one timed piece."""
    g = _at(doc, idx, voice)
    if not g or not 0 <= lo < hi < len(g.syls):
        return None
    run = g.syls[lo:hi + 1]
    text = "".join(s.text for s in run)
    timed = [s for s in run if s.timed]
    start = min(s.start for s in timed) if timed else None
    end = (max(s.end if s.end is not None else s.start for s in timed)
           if timed else None)
    g.syls[lo:hi + 1] = [Syl(text, start, end, run[-1].part)]
    return f"merged into {text}"


def join_words(doc: Doc, idx: int, voice: int, word: int) -> str | None:
    """Take the space out between a word and the one after it.

    The two stay separately timed -- they become one word made of two timed
    pieces, which is exactly what a word sung across a syllable boundary is.
    """
    g = _at(doc, idx, voice)
    if not g:
        return None
    got = g.words()
    if not 0 <= word < len(got) - 1:
        return None
    g.syls[got[word][-1]].part = True
    return f"joined {g.word_text(got[word])}{g.word_text(got[word + 1])}"


def end_word(doc: Doc, idx: int, voice: int, syl: int) -> str | None:
    """Put a space back after this syllable: two words where there was one.

    The inverse of join_words, and addressed by SYLLABLE rather than by word
    on purpose -- the boundary being restored is inside a word, so there is no
    word index that names it. Splitting "thereworld" back apart means ending
    the word after "there", and only the syllable knows where that is.
    """
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls) - 1 or not g.syls[syl].part:
        return None
    g.syls[syl].part = False
    return f"split after {g.syls[syl].text}"


def set_text(doc: Doc, idx: int, voice: int, syl: int, text: str) -> str | None:
    """Rewrite one syllable, keeping its times.

    Typing a space inside it means two words, so it is taken as such rather
    than stored as a syllable with a space in it -- which no player would
    space correctly.
    """
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls):
        return None
    from .model import _clean
    old = g.syls[syl]
    parts = _clean(text).split()
    if not parts:
        del g.syls[syl]
        _tidy(g)
        return "removed a syllable"
    if len(parts) == 1:
        old.text = parts[0]
        return None if parts[0] == old.text else "edited"
    made = _spread(parts, old)
    for s in made[:-1]:
        s.part = False
    made[-1].part = old.part
    g.syls[syl:syl + 1] = made
    return "edited"


# --------------------------------------------------------------------- lines
def split_line(doc: Doc, idx: int, word: int) -> str | None:
    """Break a line in two before word `word` of its lead.

    Backing voices follow the half they sound in, by time where the line is
    timed and the first half otherwise -- an ad-lib whose line has been split
    belongs with whichever part it answers, and there is nothing else to go on.
    """
    if not 0 <= idx < len(doc.lines):
        return None
    ln = doc.lines[idx]
    got = ln.lead.words()
    if not 0 < word < len(got):
        return None
    cut = got[word][0]
    first = Line(_tidy(Group(ln.lead.syls[:cut])), [], ln.agent)
    second = Line(_tidy(Group(ln.lead.syls[cut:])), [], ln.agent)
    edge = second.lead.span()[0]
    for g in ln.bg:
        gs = g.span()[0]
        (second if edge is not None and gs is not None and gs >= edge
         else first).bg.append(g)
    first.start, first.end = first.span()
    second.start, second.end = second.span()
    doc.lines[idx:idx + 1] = [first, second]
    return "split the line"


def merge_lines(doc: Doc, idx: int, count: int = 2) -> str | None:
    """Run `count` lines together from `idx`, in the order they are written."""
    if not 0 <= idx < len(doc.lines) or count < 2:
        return None
    run = doc.lines[idx:idx + count]
    if len(run) < 2:
        return None
    lead = Group([s for ln in run for s in ln.lead.syls])
    out = Line(_tidy(lead), [g for ln in run for g in ln.bg], run[0].agent)
    out.start, out.end = out.span()
    if out.start is None:
        out.start = next((ln.start for ln in run if ln.start is not None), None)
        out.end = next((ln.end for ln in reversed(run) if ln.end is not None), None)
    doc.lines[idx:idx + count] = [out]
    return f"merged {len(run)} lines"


def duplicate_lines(doc: Doc, indices: list[int]) -> str | None:
    """Copy lines in place, keeping their times.

    Kept rather than cleared on purpose: a duplicated chorus is nearly always
    about to be moved somewhere else in time, and starting from the times it
    had is a shorter trip than starting from nothing.
    """
    idx = sorted(i for i in indices if 0 <= i < len(doc.lines))
    if not idx:
        return None
    for i in reversed(idx):
        import copy
        doc.lines.insert(i + 1, copy.deepcopy(doc.lines[i]))
    return f"duplicated {len(idx)} line(s)"


def duplicate_rows(doc: Doc, rows) -> str | None:
    """Copy what is selected, in place.

    Same rule as deleting: a selected backing voice is copied on its own, a
    selected lead copies its whole line. Times come with the copy -- a
    duplicated line is nearly always about to be moved somewhere else in
    time, and starting from the times it had is a shorter trip than starting
    from nothing.
    """
    import copy
    want: dict = {}
    for row in rows:
        line, voice = row if isinstance(row, tuple) else (row, 0)
        if 0 <= line < len(doc.lines):
            want.setdefault(line, set()).add(voice)
    if not want:
        return None
    lines = voices = 0
    for line in sorted(want, reverse=True):
        picked = want[line]
        if 0 in picked:
            doc.lines.insert(line + 1, copy.deepcopy(doc.lines[line]))
            lines += 1
            continue
        ln = doc.lines[line]
        for voice in sorted(picked, reverse=True):
            if 1 <= voice <= len(ln.bg):
                ln.bg.insert(voice, copy.deepcopy(ln.bg[voice - 1]))
                voices += 1
    said = []
    if lines:
        said.append(f"duplicated {lines} line(s)")
    if voices:
        said.append(f"duplicated {voices} backing vocal(s)")
    return ", ".join(said) if said else None


def delete_rows(doc: Doc, rows) -> str | None:
    """Delete what is selected -- rows, not lines.

    A backing voice is its own row and its own selection, so deleting one has
    to remove that voice and nothing else. Sending its LINE number to
    delete_lines took the words it was answering with it, which is not what
    anybody pointing at an ad-lib meant.

    A line goes only when its lead is what was selected. Selecting a lead
    takes the whole line, ad-libs and all, because they belong to it.
    """
    want: dict = {}
    for row in rows:
        line, voice = row if isinstance(row, tuple) else (row, 0)
        if 0 <= line < len(doc.lines):
            want.setdefault(line, set()).add(voice)
    if not want:
        return None
    lines = gone = 0
    for line in sorted(want, reverse=True):
        voices = want[line]
        if 0 in voices:
            del doc.lines[line]
            lines += 1
            continue
        ln = doc.lines[line]
        for voice in sorted(voices, reverse=True):
            if 1 <= voice <= len(ln.bg):
                del ln.bg[voice - 1]
                gone += 1
        if not ln.lead.syls and not ln.bg:
            del doc.lines[line]
            lines += 1
    said = []
    if lines:
        said.append(f"deleted {lines} line(s)")
    if gone:
        said.append(f"deleted {gone} backing vocal(s)")
    return ", ".join(said) if said else None


def delete_lines(doc: Doc, indices: list[int]) -> str | None:
    idx = sorted((i for i in indices if 0 <= i < len(doc.lines)), reverse=True)
    if not idx:
        return None
    for i in idx:
        del doc.lines[i]
    return f"deleted {len(idx)} line(s)"


def insert_line(doc: Doc, at: int, text: str = "") -> str | None:
    at = max(0, min(at, len(doc.lines)))
    doc.lines.insert(at, Line(Group([Syl(w) for w in text.split()])))
    return "new line"


def move_lines(doc: Doc, indices: list[int], delta: int) -> str | None:
    idx = sorted(i for i in indices if 0 <= i < len(doc.lines))
    if not idx or delta == 0:
        return None
    if delta < 0 and idx[0] + delta < 0:
        return None
    if delta > 0 and idx[-1] + delta >= len(doc.lines):
        return None
    order = idx if delta < 0 else list(reversed(idx))
    for i in order:
        doc.lines[i], doc.lines[i + delta] = doc.lines[i + delta], doc.lines[i]
    return "moved"


def set_agent(doc: Doc, indices: list[int], agent: str) -> str | None:
    hit = 0
    for i in indices:
        if 0 <= i < len(doc.lines) and doc.lines[i].agent != agent:
            doc.lines[i].agent = agent
            hit += 1
    return f"{hit} line(s) -> {agent}" if hit else None


def to_background(doc: Doc, idx: int, lo: int, hi: int) -> str | None:
    """Move a run of the lead's syllables into a backing voice of its own."""
    if not 0 <= idx < len(doc.lines):
        return None
    ln = doc.lines[idx]
    if not 0 <= lo <= hi < len(ln.lead.syls):
        return None
    run = ln.lead.syls[lo:hi + 1]
    del ln.lead.syls[lo:hi + 1]
    _tidy(ln.lead)
    ln.bg.append(_tidy(Group(run)))
    if not ln.lead.syls and len(ln.bg) == 1:
        ln.lead, ln.bg = ln.bg[0], []
        return "made it a backing line"
    return "moved to backing vocals"


def to_lead(doc: Doc, idx: int, which: int) -> str | None:
    """Fold a backing voice back into the words the lead sings."""
    if not 0 <= idx < len(doc.lines):
        return None
    ln = doc.lines[idx]
    if not 0 <= which < len(ln.bg):
        return None
    g = ln.bg.pop(which)
    ln.lead.syls.extend(g.syls)
    ln.lead.syls.sort(key=lambda s: (s.start is None, s.start or 0.0))
    _tidy(ln.lead)
    return "moved into the lead"


# -------------------------------------------------------------------- timing
def set_time(doc: Doc, idx: int, voice: int, syl: int,
             start: float | None = None, end: float | None = None) -> str | None:
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls):
        return None
    s = g.syls[syl]
    if start is not None:
        s.start = max(0.0, float(start))
        if s.end is None or s.end < s.start:
            s.end = s.start
    if end is not None:
        s.end = max(float(end), s.start if s.start is not None else 0.0)
    return "timed"


def shift(doc: Doc, indices, delta: float) -> str | None:
    """Move lines in time, syllables and all.

    `indices` may be line numbers or (line, voice) pairs. Pairs move ONE
    voice: a backing vocal that came in late is nudged without dragging the
    words it answers along with it.
    """
    hit = 0
    for row in indices:
        i, voice = row if isinstance(row, tuple) else (row, None)
        if not 0 <= i < len(doc.lines):
            continue
        ln = doc.lines[i]
        groups = (ln.groups() if voice is None
                  else ([ln.groups()[voice]] if voice < len(ln.groups()) else []))
        for g in groups:
            for s in g.syls:
                if s.timed:
                    s.start = max(0.0, s.start + delta)
                    if s.end is not None:
                        s.end = max(0.0, s.end + delta)
                    hit += 1
        if voice in (None, 0):
            for attr in ("start", "end"):
                v = getattr(ln, attr)
                if v is not None:
                    setattr(ln, attr, max(0.0, v + delta))
    return f"{delta:+.2f}s" if hit else None


def spread(doc: Doc, idx: int, voice: int = 0) -> str | None:
    """Share a line's span out evenly over its syllables.

    A starting point for hand timing, and the honest thing to do with a line
    that is line-synced and has to become word-synced: every syllable gets an
    equal slice, which is wrong everywhere and wrong by a little, rather than
    right at the start and drifting.
    """
    g = _at(doc, idx, voice)
    ln = doc.lines[idx] if 0 <= idx < len(doc.lines) else None
    if not g or not g.syls or ln is None:
        return None
    a, b = g.span()
    if a is None:
        a, b = ln.start, ln.end
    if a is None or b is None or b <= a:
        return None
    n = len(g.syls)
    weights = [max(len(s.text), 1) for s in g.syls]
    total = sum(weights)
    at = a
    for s, w in zip(g.syls, weights):
        s.start = at
        at += (b - a) * w / total
        s.end = at
    g.syls[-1].end = b
    return f"spread {n} syllables"


def clear_times(doc: Doc, indices) -> str | None:
    """Forget times. Line numbers clear the whole line; (line, voice) pairs
    clear that voice only."""
    hit = 0
    for row in indices:
        i, voice = row if isinstance(row, tuple) else (row, None)
        if not 0 <= i < len(doc.lines):
            continue
        ln = doc.lines[i]
        groups = (ln.groups() if voice is None
                  else ([ln.groups()[voice]] if voice < len(ln.groups()) else []))
        for g in groups:
            for s in g.syls:
                s.start = s.end = None
                hit += 1
        if voice in (None, 0):
            ln.start = ln.end = None
    return f"cleared {hit} syllable(s)" if hit else None


def snap_line_ends(doc: Doc) -> str | None:
    """Stop every line before the next one starts.

    Two lines lit at once is the fault a reader notices first, and it is easy
    to make by hand: a line held open to cover its ad-lib runs into the line
    after it. Nothing is moved except an end that was already too late.
    """
    hit = 0
    for i, ln in enumerate(doc.lines[:-1]):
        a, b = ln.span()
        nxt = doc.lines[i + 1].span()[0]
        if a is None or b is None or nxt is None or nxt <= a or b <= nxt:
            continue
        for g in ln.groups():
            for s in g.syls:
                if s.end is not None and s.end > nxt:
                    s.end = max(s.start or nxt, nxt)
                    hit += 1
        if ln.end is not None and ln.end > nxt:
            ln.end = nxt
    return f"pulled {hit} ending(s) back" if hit else None


# ------------------------------------------------------------- chips
def insert_syllable(doc: Doc, idx: int, voice: int, at: int,
                    text: str = "word") -> str | None:
    """A new untimed syllable at position `at`, its own word.

    Untimed on purpose: a word that was not sung has no time, and giving it
    one borrowed from a neighbour would put a syllable on screen at a moment
    nobody sang it. The timing tab shows it in the loose row until it is
    given one.
    """
    g = _at(doc, idx, voice)
    if not g or not text.strip():
        return None
    at = max(0, min(int(at), len(g.syls)))
    if at:
        g.syls[at - 1].part = False
    g.syls.insert(at, Syl(text.strip()))
    _tidy(g)
    return f"inserted {text.strip()}"


def delete_syllables(doc: Doc, idx: int, voice: int, lo: int, hi: int) -> str | None:
    """Remove syllables lo..hi (inclusive).

    A group emptied this way is removed with the voice it was: a backing group
    with no words in it renders as an empty <span>, and a lead with none is an
    empty line. The line itself only goes if it was the last voice in it.
    """
    g = _at(doc, idx, voice)
    if not g or not 0 <= lo <= hi < len(g.syls):
        return None
    gone = hi - lo + 1
    del g.syls[lo:hi + 1]
    _tidy(g)
    ln = doc.lines[idx]
    if not g.syls:
        if voice and voice - 1 < len(ln.bg):
            del ln.bg[voice - 1]
        elif ln.bg:
            ln.lead = ln.bg.pop(0)
        else:
            del doc.lines[idx]
            return f"deleted {gone} syllable(s) and the line with them"
    return f"deleted {gone} syllable(s)"


def move_word(doc: Doc, idx: int, voice: int, word: int, delta: int) -> str | None:
    """Send a word to the end of the line above, or the start of the one below.

    The times go with it, because they are still when it was sung -- moving a
    word between lines is a statement about which line it BELONGS to, not
    about when it happened. It only ever moves between the leads: an ad-lib
    that wants to be in another line is a different operation (to_lead, then
    this, then to_background).
    """
    if not 0 <= idx < len(doc.lines) or delta not in (-1, 1):
        return None
    to = idx + delta
    if not 0 <= to < len(doc.lines):
        return None
    g = _at(doc, idx, voice)
    if not g:
        return None
    runs = g.words()
    if not 0 <= word < len(runs):
        return None
    run = runs[word]
    moving = g.syls[run[0]:run[-1] + 1]
    del g.syls[run[0]:run[-1] + 1]
    _tidy(g)
    dest = doc.lines[to].lead
    if delta < 0:
        dest.syls.extend(moving)
    else:
        dest.syls[:0] = moving
    _tidy(dest)
    if not g.syls and voice == 0 and not doc.lines[idx].bg:
        del doc.lines[idx]
        return "moved the last word out, and the line with it"
    return f"moved {''.join(s.text for s in moving)} to line {to + 1}"


# ------------------------------------------------------------ moving things
def reorder_lines(doc: Doc, indices: list[int], to: int) -> str | None:
    """Move the selected lines so the first of them lands at `to`.

    `to` is an index into the document AS IT IS NOW, which is what a drag
    reports: the lines being moved are taken out first, and the target slides
    up by however many of them came before it.
    """
    idx = sorted({i for i in indices if 0 <= i < len(doc.lines)})
    if not idx or not 0 <= to <= len(doc.lines):
        return None
    picked = [doc.lines[i] for i in idx]
    rest = [ln for j, ln in enumerate(doc.lines) if j not in set(idx)]
    at = max(0, min(len(rest), to - sum(1 for i in idx if i < to)))
    if rest[:at] + picked + rest[at:] == doc.lines:
        return None
    doc.lines = rest[:at] + picked + rest[at:]
    return f"moved {len(picked)} line(s)"


def move_backing(doc: Doc, line: int, voice: int, to_line: int,
                 at: int | None = None) -> str | None:
    """Move a backing voice to another line, or to another place on this one.

    Its times come with it: where an ad-lib SOUNDS is a measurement, and which
    line it belongs to is a reading of the song. Moving it is a statement
    about the second, never the first.
    """
    if not 0 <= line < len(doc.lines) or voice < 1:
        return None
    ln = doc.lines[line]
    k = voice - 1
    if k >= len(ln.bg) or not 0 <= to_line < len(doc.lines):
        return None
    g = ln.bg.pop(k)
    dest = doc.lines[to_line]
    at = len(dest.bg) if at is None else max(0, min(int(at), len(dest.bg)))
    dest.bg.insert(at, g)
    said = ("reordered the backing vocals" if to_line == line
            else f"moved it to line {to_line + 1}")
    if not ln.lead.syls and not ln.bg and line != to_line:
        del doc.lines[line]
        said += ", and the line it left was empty"
    return said


def split_off_backing(doc: Doc, line: int, voice: int) -> str | None:
    """Give a backing voice a line of its own, next to the one it was on.

    Still a backing voice -- a line with no lead is exactly how a TTML says
    "these words are only ever an answering voice" -- but its own row, so it
    can be moved, timed and read apart from anything else.
    """
    if not 0 <= line < len(doc.lines) or voice < 1:
        return None
    ln = doc.lines[line]
    k = voice - 1
    if k >= len(ln.bg):
        return None
    g = ln.bg.pop(k)
    made = Line(Group([]), [g], ln.agent)
    made.start, made.end = g.span()
    doc.lines.insert(line if g.lead_in else line + 1, made)
    return "gave the backing vocal its own line"


def to_backing(doc: Doc, line: int, voice: int, to_line: int) -> str | None:
    """Make a whole line into a backing voice of another line."""
    if not 0 <= line < len(doc.lines) or not 0 <= to_line < len(doc.lines):
        return None
    if line == to_line or voice != 0:
        return None
    ln = doc.lines[line]
    if not ln.lead.syls:
        return None
    g = ln.lead
    a = g.span()[0]
    dest = doc.lines[to_line]
    b = dest.lead.span()[0]
    g.lead_in = bool(a is not None and b is not None and a < b)
    dest.bg.extend([g] + ln.bg)
    del doc.lines[line]
    return f"made it a backing vocal of line {to_line + (0 if to_line < line else -1) + 1}"


# ------------------------------------------------------------------- words
# A word is what a person points at. A syllable is a piece of one, and moving
# or deleting a piece on its own would leave the word spelled wrong -- so
# everything below addresses words, and takes the syllables with them.
def _word_syls(doc: Doc, line: int, voice: int, word: int):
    g = doc.group(line, voice)
    if g is None:
        return None, None
    runs = g.words()
    if not 0 <= word < len(runs):
        return g, None
    return g, runs[word]


def delete_words(doc: Doc, picks) -> str | None:
    """Remove whole words, wherever they are.

    Back to front, because taking one word out renumbers everything after it
    -- and a line or a voice left with nothing in it goes too.
    """
    want = sorted({(int(a), int(b), int(c)) for a, b, c in picks},
                  key=lambda p: (-p[0], -p[1], -p[2]))
    gone = 0
    for line, voice, word in want:
        g, run = _word_syls(doc, line, voice, word)
        if g is None or not run:
            continue
        del g.syls[run[0]:run[-1] + 1]
        _tidy(g)
        gone += 1
    for line in sorted({p[0] for p in want}, reverse=True):
        if not 0 <= line < len(doc.lines):
            continue
        ln = doc.lines[line]
        ln.bg = [b for b in ln.bg if b.syls]
        if not ln.lead.syls and ln.bg:
            ln.lead, ln.bg = ln.bg[0], ln.bg[1:]
        elif not ln.lead.syls and not ln.bg:
            del doc.lines[line]
    return f"deleted {gone} word(s)" if gone else None


def move_words(doc: Doc, picks, to_line: int, to_voice: int,
               at: int) -> str | None:
    """Move whole words to a place among another group's words.

    The times go with them, as they do everywhere here: which words a line
    holds is a reading of the song, and when they were sung is a measurement.
    """
    want = sorted({(int(a), int(b), int(c)) for a, b, c in picks})
    dest = doc.group(to_line, to_voice)
    if dest is None or not want:
        return None
    # Where the destination's own syllables are, before anything moves.
    runs = dest.words()
    at = max(0, min(int(at), len(runs)))
    anchor = (runs[at][0] if at < len(runs) else len(dest.syls))
    taken: list = []
    for line, voice, word in sorted(want, key=lambda p: (-p[0], -p[1], -p[2])):
        g, run = _word_syls(doc, line, voice, word)
        if g is None or not run:
            continue
        if g is dest and run[0] < anchor:
            anchor -= len(run)           # it is coming out from before the mark
        taken.insert(0, g.syls[run[0]:run[-1] + 1])
        del g.syls[run[0]:run[-1] + 1]
        _tidy(g)
    if not taken:
        return None
    flat = [s for run in taken for s in run]
    for s in flat:
        s.part = True
    for run in taken:
        run[-1].part = False
    dest.syls[anchor:anchor] = flat
    _tidy(dest)
    for line in sorted({p[0] for p in want} | {to_line}, reverse=True):
        if not 0 <= line < len(doc.lines):
            continue
        ln = doc.lines[line]
        ln.bg = [b for b in ln.bg if b.syls]
        if not ln.lead.syls and ln.bg:
            ln.lead, ln.bg = ln.bg[0], ln.bg[1:]
        elif not ln.lead.syls and not ln.bg:
            del doc.lines[line]
    return f"moved {len(taken)} word(s)"
