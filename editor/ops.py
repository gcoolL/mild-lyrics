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
    """Glue syllables lo..hi (inclusive) back into one timed piece.

    Inside a word the pieces run straight together -- that is what a syllable
    boundary is. ACROSS one the space comes with them, into the text of the
    single piece this becomes: "Est-ce" and "que" sung on one note is
    "Est-ce que", not "Est-ceque", and the lyric may not change just because
    the timing did. Group.text and the TTML writer both keep a syllable's own
    text whole, and absorb_marks has been storing a space inside one since
    French's "Pourquoi ?" -- so this is a shape the document already has.
    """
    g = _at(doc, idx, voice)
    if not g or not 0 <= lo < hi < len(g.syls):
        return None
    run = g.syls[lo:hi + 1]
    text = "".join(s.text + ("" if s.part else " ") for s in run[:-1])
    text += run[-1].text
    timed = [s for s in run if s.timed]
    start = min(s.start for s in timed) if timed else None
    end = (max(s.end if s.end is not None else s.start for s in timed)
           if timed else None)
    g.syls[lo:hi + 1] = [Syl(text, start, end, run[-1].part)]
    return f"merged into {text}"


def _glue(prev: list[Syl], run: list[Syl], gap: str) -> None:
    """Fold `run`'s text and time onto the last syllable of `prev`."""
    tail = prev[-1]
    tail.text += gap + "".join(s.text for s in run)
    timed = [s for s in run if s.timed]
    if not timed:
        return
    lo = min(s.start for s in timed)
    hi = max(s.end if s.end is not None else s.start for s in timed)
    tail.start = lo if not tail.timed else min(tail.start, lo)
    tail.end = hi if tail.end is None else max(tail.end, hi)


def absorb_marks(doc: Doc, indices=None, gap: str = " ") -> str | None:
    """Take every lone ? ! : ; » back onto the word in front of it.

    The repair for a lyric read in before the splitting knew about French --
    "Pourquoi ?" arrives as two words, so the mark gets a chip of its own to
    click and a span of its own to time. This puts it back where it belongs,
    with the space between them kept, so the line still reads "Pourquoi ?" and
    not "Pourquoi?". « takes the word after it the same way.

    Not join_words, which is the other thing: that makes two words into one
    word of two timed pieces and takes the space OUT, which is right for a
    word sung across a boundary and wrong for this.

    The mark's time is folded into the word's rather than dropped, so nothing
    that was timed comes back untimed.
    """
    from .model import is_head, is_tail
    rows = range(len(doc.lines)) if indices is None else indices
    done = 0
    for i in rows:
        if not 0 <= i < len(doc.lines):
            continue
        for g in doc.lines[i].groups():
            runs = [[g.syls[k] for k in run] for run in g.words()]
            out: list[list[Syl]] = []
            hit = 0
            for run in runs:
                said = "".join(s.text for s in run)
                back = out and is_tail(said)
                fore = out and is_head("".join(s.text for s in out[-1]))
                if back or fore:
                    _glue(out[-1], run, gap)
                    hit += 1
                else:
                    out.append(run)
            if not hit:
                continue
            done += hit
            g.syls = []
            for run in out:
                for k, s in enumerate(run):
                    s.part = k < len(run) - 1
                    g.syls.append(s)
            _tidy(g)
    return f"put {done} mark(s) back on their word" if done else None


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


# ------------------------------------------------- the same, over a selection
# A person who has picked out four words and presses "Join words" means those
# four. Every one of these used to read the CURSOR and ignore the selection
# entirely, so the answer was about one word the user had stopped pointing at.
def _by_group(doc: Doc, picks):
    """Selected words as {(line, voice): [word indices, ascending]}."""
    out: dict = {}
    for line, voice, word in picks:
        g = doc.group(int(line), int(voice))
        if g is None or not 0 <= int(word) < len(g.words()):
            continue
        out.setdefault((int(line), int(voice)), []).append(int(word))
    return {k: sorted(set(v)) for k, v in out.items()}


def join_run(doc: Doc, picks) -> str | None:
    """Take the spaces out between the selected words.

    They become one word of several timed pieces, which is what join_words
    does for two -- this is the same statement about a whole run. Only words
    that are next to each other can be joined, so a selection with a gap in
    it joins each unbroken stretch and leaves the gaps alone.
    """
    done = 0
    for (line, voice), words in _by_group(doc, picks).items():
        g = doc.group(line, voice)
        for w in sorted(words, reverse=True):
            runs = g.words()
            if w + 1 >= len(runs) or (w + 1) not in words:
                continue
            g.syls[runs[w][-1]].part = True
            done += 1
    return f"joined {done + 1} words" if done else None


# --------------------------------------------- one note, more than one word
# join_words makes two words ONE WORD of two timings; this makes them one
# TIMING that still reads as two words. "Est-ce que" is sung on a single note
# in about half the French songs that use it, and until now the only way to
# say so was to take the space out -- so the timing was right and the lyric
# was wrong, or the other way about.
#
# The space lives inside the syllable's own text, which is a shape this
# document has had since French's spaced marks: Group.text keeps a syllable
# whole, spicy_lyrics writes it into one <span> and trims only its ends, and
# reading that TTML back gives the same one piece. The player draws the whole
# span as it sweeps, which is what "sung as one" looks like.
#
# The ZERO-WIDTH space does the same job where the words are sung with no gap
# heard between them -- see _spread. This is that with the gap still drawn.
# `note` is handed what was glued, the way the source walk is handed the
# doors that would not open. The window keeps those phrases so the automatic
# split leaves them alone -- see Editor.keep_whole -- and that is the window's
# business rather than the document's, exactly as remembering a hand-made
# split is.
def join_as_one(doc: Doc, idx: int, voice: int, word: int,
                note=None) -> str | None:
    """This word and the next, sung on one note, with the space kept."""
    g = _at(doc, idx, voice)
    if not g:
        return None
    got = g.words()
    if not 0 <= word < len(got) - 1:
        return None
    lo, hi = got[word][0], got[word + 1][-1]
    if not merge_syllables(doc, idx, voice, lo, hi):
        return None
    said = g.syls[lo].text
    if note is not None:
        note([said])
    return f"sung as one: {said}"


def join_run_as_one(doc: Doc, picks, note=None) -> str | None:
    """Each selected run of neighbouring words, sung on one note.

    Like join_run, a selection with a gap in it does each unbroken stretch on
    its own rather than swallowing what nobody picked -- and a stretch of one
    word is nothing to glue, so it is left alone rather than reported.
    """
    glued = []
    for (line, voice), words in _by_group(doc, picks).items():
        runs: list[list[int]] = []
        for w in sorted(words):
            if runs and runs[-1][-1] == w - 1:
                runs[-1].append(w)
            else:
                runs.append([w])
        for run in reversed([r for r in runs if len(r) > 1]):
            g = doc.group(line, voice)
            got = g.words()
            if run[-1] >= len(got):
                continue
            lo = got[run[0]][0]
            if merge_syllables(doc, line, voice, lo, got[run[-1]][-1]):
                glued.append(g.syls[lo].text)
    if note is not None:
        note(glued)
    return f"sung as one: {len(glued)} run(s) of words" if glued else None


def break_words(doc: Doc, picks) -> str | None:
    """Put the spaces back inside each selected word -- the inverse of join_run.

    Every join WITHIN the word goes, not just the one after it. Breaking only
    after the last syllable is a no-op on a word that already ends a word,
    which is exactly the word somebody has just joined and wants back --
    so "Join words" and "Break word" on the same selection have to be each
    other's undo, and this is what makes them so.
    """
    done = 0
    for (line, voice), words in _by_group(doc, picks).items():
        g = doc.group(line, voice)
        for w in sorted(words, reverse=True):
            runs = g.words()
            if not 0 <= w < len(runs) or len(runs[w]) < 2:
                continue
            for k in runs[w]:
                g.syls[k].part = False
            done += 1
    _tidy_all(doc, {(line, voice) for line, voice in _by_group(doc, picks)})
    return f"broke {done} word(s) apart" if done else None


def _tidy_all(doc: Doc, rows) -> None:
    for line, voice in rows:
        g = doc.group(line, voice)
        if g is not None:
            _tidy(g)


def merge_words(doc: Doc, picks) -> str | None:
    """Glue each selected word's syllables back into one timed piece."""
    done = 0
    for (line, voice), words in _by_group(doc, picks).items():
        for w in sorted(words, reverse=True):
            g = doc.group(line, voice)
            runs = g.words()
            if not 0 <= w < len(runs) or len(runs[w]) < 2:
                continue
            if merge_syllables(doc, line, voice, runs[w][0], runs[w][-1]):
                done += 1
    return f"merged {done} word(s) back together" if done else None


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
    space correctly. The exception is the space French puts BEFORE a mark
    like ? or !, which belongs to the word in front of it and is kept there;
    see model.words_in.
    """
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls):
        return None
    from .model import _clean, words_in
    old = g.syls[syl]
    parts = words_in(_clean(text))
    if not parts:
        del g.syls[syl]
        _tidy(g)
        return "removed a syllable"
    if len(parts) == 1:
        # Compared against what it WAS. Assigning first and comparing after
        # made the test always true, so a real rewrite reported "nothing
        # happened" -- the signal the window reads as a no-op, which pops the
        # undo entry it had just pushed and skips the dirty flag and the push
        # to the player.
        was, old.text = old.text, parts[0]
        return None if parts[0] == was else "edited"
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
    from .model import words_in
    doc.lines.insert(at, Line(Group([Syl(w) for w in words_in(text)])))
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


def swap_agents(doc: Doc, indices=None) -> str | None:
    """Put every line on the other side: main becomes duet, duet becomes main.

    A swap, not a stripe. Striping every other line was a CONVENTION applied
    to a song nobody had read -- it says nothing true about who sings what,
    and on a lyric that already had its sides marked it threw that reading
    away. Swapping keeps the reading and only mirrors it, which is the thing
    anybody actually wants when the two voices came in the wrong way round.
    """
    rows = (range(len(doc.lines)) if indices is None
            else [i for i in indices if 0 <= i < len(doc.lines)])
    hit = 0
    for i in rows:
        ln = doc.lines[i]
        ln.agent, hit = ("v1" if ln.agent != "v1" else "v2"), hit + 1
    return f"swapped the voices on {hit} line(s)" if hit else None


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
    """Stop every LEAD line before the next one starts.

    Two lines lit at once is the fault a reader notices first, and it is easy
    to make by hand: a line held open runs into the line after it. Nothing is
    moved except an end that was already too late.

    Ad-libs are left exactly where they are. A backing vocal ringing on past
    the line it answers -- into the next line, and sometimes through it -- is
    not a mistake to be tidied away; it is what the singer did, and it is
    half the reason a document has backing groups at all. This used to walk
    ln.groups(), which is the lead AND every ad-lib, so one press cropped
    every held answer in the song back to the next line's first word.

    The next line's LEAD start is the boundary, for the same reason: an
    ad-lib that opens the next line early must not drag this line's end back
    with it.
    """
    hit = 0
    for i, ln in enumerate(doc.lines[:-1]):
        a, b = ln.lead.span()
        nxt = doc.lines[i + 1].lead.span()[0]
        if nxt is None:
            nxt = doc.lines[i + 1].start
        if a is None or b is None or nxt is None or nxt <= a or b <= nxt:
            continue
        for s in ln.lead.syls:
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


def adlib_to_line(doc: Doc, line: int, voice: int) -> str | None:
    """Make a backing voice an ordinary line of its own.

    Not split_off_backing, which is the other half of the pair: that gives it
    a row of its own and leaves it a backing voice, which is right for an
    ad-lib that only ever answers. This is for the case where a run was read
    as an ad-lib and is not one -- a second singer's line, a hook, a bracket
    in the source that meant something else. It becomes a lead, so it is sung
    rather than answered, and it keeps its times because when it sounds is a
    measurement either way.
    """
    if not 0 <= line < len(doc.lines) or voice < 1:
        return None
    ln = doc.lines[line]
    k = voice - 1
    if k >= len(ln.bg):
        return None
    g = ln.bg.pop(k)
    g.lead_in = False
    made = Line(_tidy(g), [], ln.agent)
    made.start, made.end = made.span()
    at = line if (made.start is not None and (ln.lead.span()[0] is None
                  or made.start < ln.lead.span()[0])) else line + 1
    doc.lines.insert(at, made)
    if not ln.lead.syls and not ln.bg:
        del doc.lines[line if at > line else line + 1]
        return "made it a line of its own"
    return "made it an ordinary line"


def split_backing_on(doc: Doc, line: int, voice: int,
                     sep: str = ";") -> str | None:
    """Cut one backing voice into several, wherever it is punctuated.

    `Lyric (Lyric; Lyric)` is two answers written in one bracket, and read in
    as one it is one run of words with one span -- so the two get a single
    highlight sweeping across both, and no way to time them apart. This
    separates them into a backing voice each, so each has its own span.

    Times come with the words. The separator itself goes: it was punctuation
    between two things, and once they are two things there is nothing left
    for it to separate.
    """
    if not 0 <= line < len(doc.lines) or voice < 1:
        return None
    ln = doc.lines[line]
    k = voice - 1
    if k >= len(ln.bg):
        return None
    g = ln.bg[k]
    runs, cur = [], []
    for syl in g.syls:
        text = syl.text
        cut = sep in text
        if cut:
            text = text.replace(sep, "").rstrip()
        if text:
            cur.append(Syl(text, syl.start, syl.end, syl.part))
        if cut and cur:
            cur[-1].part = False
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    runs = [r for r in runs if r]
    if len(runs) < 2:
        return None
    made = []
    for r in runs:
        piece = _tidy(Group(r, lead_in=g.lead_in))
        if piece.syls:
            made.append(piece)
    if len(made) < 2:
        return None
    ln.bg[k:k + 1] = made
    return f"split it into {len(made)} backing vocals"


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


# ------------------------------------------- the same, over a row selection
# The word commands learned this a while ago (see _by_group above); the LINE
# commands had not. Every one of them read the CURSOR, so picking out four
# lines and asking for them to be spread, or made into ad-libs, answered
# about one line the user had stopped pointing at and left the other three
# alone -- with no hint that the selection had been ignored.
#
# The catch is that half of these move lines around, so a (line, voice) pair
# noted before the first one runs names a different row by the time the
# second one does. They are addressed by IDENTITY here and looked up again
# each time round, which is the only thing that stays true across an insert.
def _rows_now(doc: Doc, rows) -> list:
    """Selected rows as (line object, group object) pairs, in order."""
    out = []
    for row in rows:
        line, voice = row if isinstance(row, tuple) else (row, 0)
        if not 0 <= int(line) < len(doc.lines):
            continue
        ln = doc.lines[int(line)]
        got = ln.groups()
        if 0 <= int(voice) < len(got):
            out.append((ln, got[int(voice)]))
    return out


def _where(doc: Doc, ln: Line, g: Group):
    """Where a remembered row sits NOW, or None if it has gone."""
    for i, other in enumerate(doc.lines):
        if other is ln:
            for v, grp in enumerate(other.groups()):
                if grp is g:
                    return i, v
            return None
    return None


def spread_rows(doc: Doc, rows) -> str | None:
    """Share each selected row's span out over its own syllables."""
    done = 0
    for row in rows:
        line, voice = row if isinstance(row, tuple) else (row, 0)
        if spread(doc, int(line), int(voice)):
            done += 1
    return f"spread {done} row(s)" if done else None


def merge_runs(doc: Doc, lines) -> str | None:
    """Run each unbroken stretch of the selected lines together.

    Not the span from the first to the last: a selection with a gap in it
    used to swallow the lines nobody had picked, which is the one mistake
    here that cannot be seen at a glance afterwards. Each run is merged on
    its own, exactly like join_run does for words.
    """
    idx = sorted({int(i) for i in lines if 0 <= int(i) < len(doc.lines)})
    runs: list[list[int]] = []
    for i in idx:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    runs = [r for r in runs if len(r) > 1]
    if not runs:
        return None
    done = 0
    for run in reversed(runs):
        if merge_lines(doc, run[0], len(run)):
            done += len(run)
    return (f"merged {done} lines" if len(runs) == 1
            else f"merged {done} lines into {len(runs)}")


def move_rows(doc: Doc, rows, delta: int) -> str | None:
    """Move what is selected, up or down.

    A selection made only of backing voices moves among its line's own
    voices, because that is the only direction an ad-lib has; anything with
    a lead in it moves whole lines. The ribbon's arrows have always done
    this and the menu's had not, so the same two words meant two things
    depending on which one was used.
    """
    picks = [(int(i), int(v)) for i, v in
             ((row if isinstance(row, tuple) else (row, 0)) for row in rows)
             if 0 <= int(i) < len(doc.lines)]
    if not picks or delta == 0:
        return None
    if all(v for _i, v in picks):
        line, voice = picks[0]
        return move_backing(doc, line, voice, line,
                            voice - 2 if delta < 0 else voice)
    return move_lines(doc, sorted({i for i, _v in picks}), delta)


def adlibs_to_lines(doc: Doc, rows) -> str | None:
    """Make every selected backing voice an ordinary line of its own."""
    done = 0
    for ln, g in reversed(_rows_now(doc, rows)):
        at = _where(doc, ln, g)
        if at is None or at[1] == 0:
            continue
        if adlib_to_line(doc, at[0], at[1]):
            done += 1
    return f"made {done} ad-lib(s) ordinary lines" if done else None


def split_off_backings(doc: Doc, rows) -> str | None:
    """Give every selected backing voice a row of its own."""
    done = 0
    for ln, g in reversed(_rows_now(doc, rows)):
        at = _where(doc, ln, g)
        if at is None or at[1] == 0:
            continue
        if split_off_backing(doc, at[0], at[1]):
            done += 1
    return f"gave {done} ad-lib(s) a row of their own" if done else None


def split_backings_on(doc: Doc, rows, sep: str = ";") -> str | None:
    """Cut every selected backing voice at its punctuation."""
    done = 0
    for ln, g in reversed(_rows_now(doc, rows)):
        at = _where(doc, ln, g)
        if at is None or at[1] == 0:
            continue
        if split_backing_on(doc, at[0], at[1], sep):
            done += 1
    return f"split {done} backing vocal(s)" if done else None


def lines_to_backing(doc: Doc, lines, delta: int) -> str | None:
    """Make each selected LEAD line an ad-lib of its neighbour.

    Walked from the neighbour outwards -- upwards for the line above,
    downwards for the line below -- so a block of four selected lines all
    end up answering the one line outside the block, rather than the second
    disappearing into the first the moment the first stops being a line.
    """
    got = [(ln, g) for ln, g in _rows_now(doc, lines) if g is ln.lead]
    if delta > 0:
        got.reverse()
    done = 0
    for ln, g in got:
        at = _where(doc, ln, g)
        if at is None or at[1] != 0:
            continue
        if to_backing(doc, at[0], 0, at[0] + delta):
            done += 1
    return f"made {done} line(s) backing vocals" if done else None


def to_leads(doc: Doc, lines) -> str | None:
    """Fold each selected line's first backing voice into its lead."""
    done = 0
    for ln, _g in _rows_now(doc, lines):
        at = _where(doc, ln, ln.lead)
        if at is None or not ln.bg:
            continue
        if to_lead(doc, at[0], 0):
            done += 1
    return f"folded {done} backing vocal(s) into the lead" if done else None


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


# ------------------------------------------------------- snapping to a vocal
# How far to look for the landmark a word belongs to. Wider than this and a
# word starts finding the attack of the word after it.
RADIUS = 0.18
# Gaps up to this get closed; anything longer is a silence somebody meant.
# The file this was built against has 301 syllable-to-syllable gaps inside its
# groups and 293 of them are exactly zero, so the rule is not a preference --
# it is what a hand-timed document already looks like. Its line-to-line gaps
# are bimodal with nothing between 0.66 s and 1.40 s, which is where a
# default of a third of a second sits comfortably clear of both.
MAX_GAP = 0.35


def _nearest(marks: list[float], t: float, floor: float | None = None):
    """The mark closest to `t`, ignoring any before `floor`.

    The floor is applied by starting the search at it rather than by throwing
    candidates away afterwards -- a filter over the two marks either side of
    `t` returns nothing when both are behind the floor, and the answer was
    the next one along.
    """
    import bisect
    lo = 0 if floor is None else bisect.bisect_left(marks, floor)
    if lo >= len(marks):
        return None
    k = bisect.bisect_left(marks, t, lo)
    best = None
    for c in (k - 1, k):
        if lo <= c < len(marks) and (best is None
                                     or abs(marks[c] - t) < abs(best - t)):
            best = marks[c]
    return best


def vocal_bias(doc: Doc, indices, starts: list[float],
               radius: float = RADIUS) -> tuple[float, int]:
    """How far this document's words sit from the landmarks, and how many voted.

    A file has a house style. gc's sit about 0.03 s AHEAD of the attack, every
    one of them, on every setting the measurement was run at -- that is not an
    error to be corrected, it is where this person puts a word, and a snap
    that ignored it would drag the whole song 30 ms late in the name of
    tidiness. So the median is measured and then preserved: what gets removed
    is the scatter around it, not the offset itself.
    """
    import statistics
    gaps = []
    for i, _v, g in _scope(doc, indices):
        for run in g.words():
            s = g.syls[run[0]]
            if not s.timed:
                continue
            m = _nearest(starts, s.start)
            if m is not None and abs(s.start - m) <= radius:
                gaps.append(s.start - m)
    if len(gaps) < 8:
        return 0.0, len(gaps)
    return float(statistics.median(gaps)), len(gaps)


def _scope(doc: Doc, indices):
    """(line, voice, group) for everything the caller asked for.

    `indices` is line numbers or (line, voice) pairs, the same as `shift` and
    `clear_times` take.
    """
    for row in indices:
        i, voice = row if isinstance(row, tuple) else (row, None)
        if not 0 <= i < len(doc.lines):
            continue
        gs = doc.lines[i].groups()
        for v, g in enumerate(gs):
            if voice is None or v == voice:
                yield i, v, g


# How close a second syllable has to be before a mark stops being evidence
# for the first. Measured on `MaKE ME FAMOUSS >_<`: at 0.10 s, 236 of 337
# marks have exactly one syllable near them and 33 have two or more. Widening
# it to 0.18 flips that -- 153 contested against 135 clean -- because the
# marks are denser than the words are. This is the width at which a contest
# is a real ambiguity rather than an artefact of the reach.
CONTEST = 0.10


def claims(doc: Doc, indices, starts: list[float],
           bias: float | None = None,
           contest: float = CONTEST) -> dict:
    """Which mark belongs to which syllable, where that is not in doubt.

    THE MISTAKE THIS EXISTS TO STOP. In "I'm goin' insane, she might", the
    document has `sane,` at 20.322 and `she` at 20.387, and the vocal offers
    ONE mark, at 20.387. Both syllables are within a breath of it. The old
    rule handed it to whichever was nearer and moved that word onto it, which
    put `she` on an attack that a listener can hear is the /s/ of `sane` --
    reported, correctly, as "it decided to snap to she".

    No rule over unlabelled attacks can tell those two apart; that needs the
    lyric, which is what the sync model is for. What a rule CAN do is notice
    that the mark has two claimants and decline to use it for either. A mark
    is kept only when exactly one timed syllable in the document lies within
    `contest` of it -- and then it belongs to that syllable and to nothing
    else.

    Marks with NO syllable near them are dropped too. Those are real events
    in the audio -- a breath, a hi-hat leaking through the separation, a
    consonant in a word nobody has timed yet -- and a word reaching out to
    one is reaching for something the document has no account of.

    Returns {"owner": {biased mark: the syllable start it belongs to},
             "contested": [...], "orphan": [...], "bias": the offset used,
             "usable": {the ORIGINAL, unbiased marks that are owned}}.

    Both keyings are handed back on purpose. Snapping works in biased time,
    because that is where the answer has to land; the strip draws the marks
    it was given by `vocalmap`, which are unbiased. Returning one and letting
    the caller derive the other is how the strip came to draw every mark as
    contested -- the membership test compared two different numbers and was
    quietly never true.
    """
    import bisect
    if bias is None:
        bias, _voted = vocal_bias(doc, indices, starts)
    aimed = sorted(m + bias for m in starts)
    syls = sorted(s.start for _i, _v, g in _scope(doc, indices)
                  for s in g.syls if s.timed)
    owner, contested, orphan = {}, [], []
    for m in aimed:
        lo = bisect.bisect_left(syls, m - contest)
        hi = bisect.bisect_right(syls, m + contest)
        if hi - lo == 1:
            owner[m] = syls[lo]
        elif hi - lo == 0:
            orphan.append(m)
        else:
            contested.append(m)
    return {"owner": owner, "contested": contested, "orphan": orphan,
            "bias": bias, "usable": {m - bias for m in owner}}


def consistency(doc: Doc, indices, starts: list[float],
                bias: float | None = None,
                contest: float = CONTEST) -> dict:
    """How much this song's marks can be trusted, measured on the song itself.

    A song repeats itself. When the same word is sung again, the vocal ought
    to put a mark in the same place relative to it -- and where it does not,
    the marks are telling you about this delivery of this line rather than
    about where the word is.

    That is the number somebody needs before believing any of this, and it
    can only be had per song. On `MaKE ME FAMOUSS >_<`: of 32 words sung
    three or more times, twelve agree across their repeats to within 20 ms,
    the median spread is 25 ms, and the worst is `famous` at 130 ms -- sung
    six times, marked four, at +100, -30, +100 and +0 ms. `might` and `drive`
    are +0 every time. Same song, same picture, and no threshold separates
    the two groups, because the difference is in how the line was sung.

    Returns {"covered": share of word heads with a mark of their own,
             "words": [(word, times sung, offsets in ms, spread in ms)],
             "tight": how many of those agree within TIGHT,
             "spread": the median spread}.
    """
    import collections
    import statistics
    mine = claims(doc, indices, starts, bias, contest)
    owner = mine["owner"]
    mark_of = {round(syl, 3): m for m, syl in owner.items()}
    heads = []
    for _i, _v, g in _scope(doc, indices):
        for run in g.words():
            h = g.syls[run[0]]
            if h.timed:
                heads.append((g.word_text(run), h.start))
    if not heads:
        return {"covered": 0.0, "words": [], "tight": 0, "spread": 0.0,
                "heads": 0}
    by = collections.defaultdict(list)
    for text, at in heads:
        m = mark_of.get(round(at, 3))
        by[text.strip(",.\"'!?").lower()].append(
            None if m is None else round((m - at) * 1000))
    rows = []
    for word, offs in by.items():
        real = [o for o in offs if o is not None]
        if len(offs) < 3 or len(real) < 2:
            continue
        rows.append((word, len(offs), offs, max(real) - min(real)))
    rows.sort(key=lambda r: -r[3])
    spreads = [r[3] for r in rows]
    return {"covered": sum(1 for _t, a in heads
                           if round(a, 3) in mark_of) / len(heads),
            "heads": len(heads), "words": rows,
            "tight": sum(1 for s in spreads if s <= TIGHT),
            "spread": statistics.median(spreads) if spreads else 0.0}


TIGHT = 20        # ms: two marks this close are saying the same thing


def fill_gaps(doc: Doc, indices, max_gap: float = MAX_GAP) -> str | None:
    """Close the small holes between words; leave the rests alone.

    No audio in this one, which is why it outlived the snapping it was built
    beside. A hand-timed document is contiguous inside a phrase --
    the file this was measured against has 301 syllable-to-syllable gaps and
    293 of them are exactly zero -- so a hole of a few tens of milliseconds is
    almost always an artefact of how the times were made rather than something
    somebody sang. Above `max_gap` it is a rest, and filling a rest lights a
    word through a bar nobody is singing in.

    A pair that already overlapped keeps its overlap: a syllable held over the
    ones after it is the singer's doing, and this is not the place to tidy it.
    """
    closed = 0
    for _i, _v, g in _scope(doc, indices):
        runs = [r for r in g.words() if g.syls[r[0]].timed]
        for n in range(len(runs) - 1):
            a, b = g.syls[runs[n][-1]], g.syls[runs[n + 1][0]]
            if a.end is None or b.start is None:
                continue
            gap = b.start - a.end
            if 1e-6 < gap <= max_gap:
                a.end = b.start
                closed += 1
    return f"closed {closed} gap(s) under {max_gap:.2f}s" if closed else None


def stranded(doc: Doc, indices, starts: list[float], reach: float = 0.15,
             bias: float | None = None) -> list[tuple[int, int, int, float]]:
    """The words sitting further than `reach` from anything the vocal does.

    This is what the measurement actually supports, and it is deliberately a
    QUESTION rather than an edit. Against gc's own timing of `MaKE ME FAMOUSS
    >_<`, the nearest landmark puts a word within 0.028 s of where they put it
    and chance alone manages 0.040 s -- real information, and nowhere near
    enough to move a word by. What survives that is the other end of the
    distribution: a word 0.15 s from every attack and every entrance in
    earshot is a word worth listening to again, and pointing at it costs
    nothing if it turns out to be fine.

    Returns (line, voice, word, distance), worst first.
    """
    if not starts:
        return []
    if bias is None:
        bias, _voted = vocal_bias(doc, indices, starts)
    aimed = sorted(m + bias for m in starts)
    out = []
    for i, v, g in _scope(doc, indices):
        for w, run in enumerate(g.words()):
            s = g.syls[run[0]]
            if not s.timed:
                continue
            m = _nearest(aimed, s.start)
            if m is None:
                continue
            d = abs(s.start - m)
            if d > reach:
                out.append((i, v, w, round(d, 3)))
    return sorted(out, key=lambda r: -r[3])


# How far from the even-share guess a landmark may be and still be taken as
# where that word starts; see `from_first`. The same figure `stranded` calls
# a word worth listening to again, and for the same reason: the measurement
# in `vocalmap` puts a hand-placed word 0.028 s from its nearest landmark
# against 0.040 s for chance, so what a landmark can be trusted to settle is
# a placement that is otherwise a guess, over a radius wide enough to catch
# the right attack and narrow enough to miss the next word's.
WALK_REACH = 0.15
# The least a word may run for. Two words on the same attack is not a
# timing, and audio.FRAME is 0.02 s, so this is three frames.
WALK_STEP = 0.06


def _next_start(doc: Doc, i: int) -> float | None:
    """When the next timed line after `i` starts, if there is one."""
    for j in range(i + 1, len(doc.lines)):
        a, _b = doc.lines[j].span()
        if a is not None:
            return a
    return None


def _walk_dp(guesses: list[float], cands: list[list[tuple[float, float]]],
             floor: float, ceiling: float, step: float) -> list[float] | None:
    """Pick one candidate per word, in order, for the least total cost.

    A greedy nearest-landmark pass cannot do this: the attack nearest word
    three may be the one word two has to have, and a greedy walk takes it and
    then has nowhere to put word two but after it. Choosing all of them at
    once is a shortest path over at most a few dozen states either way, so it
    costs nothing to be right about.
    """
    rows: list[list[tuple[float, float, int]]] = []
    for j, layer in enumerate(cands):
        lo = floor + step * (j + 1)
        hi = ceiling - step * (len(guesses) - j)
        row: list[tuple[float, float, int]] = []
        for t, own in layer:
            if not (lo - 1e-9 <= t <= hi + 1e-9):
                continue
            if j == 0:
                row.append((t, own, -1))
                continue
            best, at = None, -1
            for k, (pt, pc, _pk) in enumerate(rows[j - 1]):
                if t >= pt + step and (best is None or pc < best):
                    best, at = pc, k
            if best is not None:
                row.append((t, best + own, at))
        if not row:
            return None
        rows.append(row)
    at = min(range(len(rows[-1])), key=lambda k: rows[-1][k][1])
    out = []
    for j in range(len(rows) - 1, -1, -1):
        t, _c, back = rows[j][at]
        out.append(t)
        at = back
    return out[::-1]


def from_first(doc: Doc, idx: int, voice: int = 0,
               starts: list[float] | None = None, bias: float | None = None,
               reach: float = WALK_REACH, gap: float = MAX_GAP) -> str | None:
    """Time the rest of a line from its first word and the vocal's attacks.

    WHAT THIS IS AND IS NOT. It is a better starting point than an even share.
    It is not a placement, and if there is a trained checkpoint on the machine
    the model is the thing to use instead -- this is for the case where there
    is not, or where somebody wants a first pass to drag into shape.

    Measured against two hand-timed files, each line stripped back to its
    first word and re-timed, every other word compared with where it really
    is:

                            median   within 50ms   within 100ms
        MaKE ME FAMOUSS >_<
          even share        0.255s       9%            21%
          with the vocal    0.219s      16%            22%
        Scared of the Dark
          even share        0.133s      24%            42%
          with the vocal    0.132s      33%            43%

    So the vocal roughly doubles the words that land where they belong and
    leaves the rest about where an even share left them. A median of a fifth
    of a second is not a timing anybody would keep; a word that IS on its
    attack is one fewer to drag.

    The reason it is no better than that is in `vocalmap`'s own numbers. The
    nearest landmark to a hand-placed word is 0.033s away and 60% of them are
    within 50ms, so the marks know where the words are -- what is missing is
    which mark belongs to which word. Choosing that from the words' letter
    counts was tried three ways (absolute, squared and log duration cost) at
    three mark densities, and the best of the nine is 0.193s against that
    0.033s ceiling. The information is there and the letter counts cannot
    get at it. Whatever improves this will be a better model of how long a
    word takes, not more marks: dropping the flux floor from 0.45 to 0.25
    nearly triples the marks, lifts the ceiling to 0.020s, and makes the
    answer WORSE.

    The shape, then: spread first, then let the vocal move each word to the
    nearest thing it actually does, in order and never past its neighbours.
    A landmark further than `reach` from where the share put a word is not
    offered at all, which is what keeps the fifth of a second from becoming a
    second. The first word is the anchor and is never moved -- it is the one
    time in the line somebody placed by ear, and it is also what tells this
    where the line begins.

    Reading the bias rather than removing it, for the reason `vocal_bias`
    gives: this file's words sit a consistent 0.03 s ahead of the attack they
    belong to, that is where their author puts a word, and the landmarks are
    aimed accordingly.

    Words are laid end to end, because a hand-timed line is contiguous inside
    a phrase -- but only where the join is a join. A hole longer than `gap` is
    a rest somebody is not singing in, and the word before it keeps its own
    length rather than being held open across it. That is `fill_gaps`'
    threshold and the same judgement.
    """
    g = _at(doc, idx, voice)
    ln = doc.lines[idx] if 0 <= idx < len(doc.lines) else None
    if not g or not g.syls or ln is None:
        return None
    runs = g.words()
    if len(runs) < 2:
        return None
    head = g.syls[runs[0][0]]
    if not head.timed:
        return None
    if any(g.syls[r[0]].timed for r in runs[1:]):
        return None
    a = head.start
    ends = [t for t in (ln.end, _next_start(doc, idx)) if t is not None]
    b = min(ends) if ends else None
    if b is None or b - a < WALK_STEP * len(runs):
        return None

    weight = [max(sum(len(g.syls[k].text.strip()) for k in r), 1) for r in runs]
    total = sum(weight)
    share = [(b - a) * w / total for w in weight]
    guess, at = [], a
    for w in share[:-1]:
        at += w
        guess.append(at)

    marks = sorted((m + (bias or 0.0)) for m in (starts or []))
    cands = []
    for want in guess:
        near = [(m, abs(m - want)) for m in marks if abs(m - want) <= reach]
        # The guess itself, priced at the reach: any landmark inside the reach
        # is preferred to it, and nothing outside the reach was ever offered.
        cands.append(sorted(near + [(want, reach)]))
    picked = _walk_dp(guess, cands, a, b, WALK_STEP) or guess

    moved = sum(1 for t, w in zip(picked, guess) if abs(t - w) > 1e-6)
    heads = [a] + list(picked)
    for n, run in enumerate(runs):
        s0 = heads[n]
        nxt = heads[n + 1] if n + 1 < len(heads) else b
        stop = min(s0 + share[n], nxt)
        if nxt - stop <= gap:
            stop = nxt
        inner = [max(len(g.syls[k].text.strip()), 1) for k in run]
        span, cut = stop - s0, sum(inner)
        t = s0
        for k, w in zip(run, inner):
            g.syls[k].start = t
            t += span * w / cut
            g.syls[k].end = t
        g.syls[run[-1]].end = stop
    ln.start = a
    if ln.end is None or ln.end < g.syls[-1].end:
        ln.end = g.syls[-1].end
    return (f"timed {len(runs) - 1} word(s) from the first"
            + (f", {moved} of them on the vocal" if moved else
               " — no attack was near enough, so this is an even share"))
