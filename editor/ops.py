"""Every edit the buttons make, as plain functions over a Doc returning a
sentence or None. A group's last syllable is never `part`; times are never
invented."""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "mild-lyrics", _HERE.parent)
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
    """Cut one syllable in two at character `cut`, keeping one word; the time
    is shared by letters."""
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
    """Cut one syllable at the given offsets (into the text as written),
    sharing the time out by letters."""
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
    _deal_roman(doc, idx, voice, syl, len(made), s.roman)
    return f"split {'|'.join(pieces)}"


def _deal_roman(doc: Doc, idx: int, voice: int, k: int, n: int,
                roman: str) -> None:
    """A piece's reading shared over the n pieces it was cut into (from k),
    seamed where the romaniser reads them. With no syllable read and a line
    reading (Genius'), that is shared over the syllables instead."""
    g = _at(doc, idx, voice)
    if not g:
        return
    if not roman.strip():
        if g.roman.strip() and not any(x.roman.strip() for x in g.syls):
            correct_reading(doc, idx, voice, g.roman)
        return
    guide = group_readings(g, japanese(doc))[k:k + n]
    have = [j for j, r in enumerate(guide) if r]
    got = _share([guide[j] for j in have], _flat(roman)) if have else None
    if got is None:
        g.syls[k].roman = roman
        return
    for j, piece in zip(have, got):
        g.syls[k + j].roman = piece


def cut_syllable(doc: Doc, idx: int, voice: int, k: int,
                 method: str = "sung", lang: str = "en_US",
                 unit: str = "syllable") -> str | None:
    """Cut one piece of a word into syllables and leave the rest alone: a
    Japanese line is one word, and its other pieces may be timed."""
    from . import syllables as SY
    g = _at(doc, idx, voice)
    if not g or not 0 <= k < len(g.syls):
        return None
    s = g.syls[k]
    pieces = SY.split(s.text, method, lang, unit, japanese(doc))
    if len(pieces) < 2:
        return None
    g.syls[k:k + 1] = _spread(pieces, s)
    _deal_roman(doc, idx, voice, k, len(pieces), s.roman)
    return f"cut {'|'.join(pieces)}"


def split_everywhere(doc: Doc, word: str, pieces: list[str],
                     skip: tuple | None = None) -> int:
    """Spell every other copy of this word the same way, ignoring case and
    surrounding punctuation; re-cuts copies already split. Returns how many."""
    want = "".join(pieces)
    if not want or not word:
        return 0
    from . import syllables as SY
    bits = SY.bare_pieces(word, list(pieces))
    if not bits:
        return 0
    key = SL.peel(word)[1].lower()
    lens, done = [len(x) for x in bits], 0
    for i, ln in enumerate(doc.lines):
        for v, g in enumerate(ln.groups()):
            for w in range(len(g.words()) - 1, -1, -1):
                run = g.words()[w]
                if skip is not None and (i, v, run[0]) == skip:
                    continue
                here = g.word_text(run)
                head, core, tail = SL.peel(here)
                if core.lower() != key:
                    continue
                if len(run) > 1:
                    merge_syllables(doc, i, v, run[0], run[-1])
                    run = [run[0]]
                s = g.syls[run[0]]
                if len(s.text) != len(here) or len(core) != sum(lens):
                    continue
                at, made = len(head), []
                for n in lens:
                    made.append(s.text[at:at + n])
                    at += n
                made[0] = head + made[0]
                made[-1] = made[-1] + tail
                if "".join(made) != s.text or not all(made):
                    continue
                got = _spread(made, s)
                got[-1].part = s.part
                g.syls[run[0]:run[0] + 1] = got
                _deal_roman(doc, i, v, run[0], len(got), s.roman)
                done += 1
    return done


def syllabify(doc: Doc, idx: int, voice: int, words: list[int] | None = None,
              method: str = "sung", lang: str = "en_US",
              resplit: bool = False, unit: str = "syllable") -> str | None:
    """Cut whole words into syllables by `method` (see editor/syllables.py).
    Words already cut are left alone unless `resplit`."""
    from . import syllables as SY
    g = _at(doc, idx, voice)
    if not g:
        return None
    got = g.words()
    want = list(range(len(got))) if words is None else [w for w in words
                                                       if 0 <= w < len(got)]
    done = 0
    ja = japanese(doc)
    for wi in sorted(want, reverse=True):
        run = got[wi]
        if len(run) > 1 and not resplit:
            done += _join_ruby(doc, idx, voice, g, run)
            continue
        if len(run) > 1:
            if SY.is_accepted(g.word_text(run), [g.syls[i].text for i in run],
                              lang):
                continue
            merge_syllables(doc, idx, voice, run[0], run[-1])
            run = [run[0]]
        s = g.syls[run[0]]
        pieces = SY.split(s.text, method, lang, unit, ja)
        if len(pieces) < 2:
            continue
        made = _spread(pieces, s)
        g.syls[run[0]:run[0] + 1] = made
        _deal_roman(doc, idx, voice, run[0], len(made), s.roman)
        done += 1
    return f"cut {done} word(s) into syllables" if done else None


def hyphens_on() -> bool:
    """Settings ▸ Words ▸ Split after hyphens (on unless turned off)."""
    from . import keys as K
    return bool(K.config().get("split_hyphens", True))


def cut_hyphens(lines, only: tuple | None = None) -> int:
    """Cut untimed whole words after their hyphens ("brand-|new"). `only`:
    (voice, first syllable, last syllable) of one group, for typed text.
    Timed words are never cut. Returns how many words were cut."""
    from . import syllables as SY
    done = 0
    for ln in lines:
        for v, g in enumerate(ln.groups()):
            if only is not None and v != only[0]:
                continue
            for run in reversed(g.words()):
                if len(run) != 1:
                    continue
                k = run[0]
                if only is not None and not only[1] <= k <= only[2]:
                    continue
                s = g.syls[k]
                if s.start is not None:
                    continue
                pieces = SY.hyphen_cut(s.text)
                if len(pieces) > 1:
                    g.syls[k:k + 1] = _spread(pieces, s)
                    done += 1
    return done


def words_to_cut(doc: Doc, idx: int, voice: int, words: list[int] | None = None,
                 resplit: bool = False, lang: str = "en_US") -> list[str]:
    """The words `syllabify` would cut with these arguments, as written --
    so the ones with several right ways can be asked about first."""
    from . import syllables as SY
    g = _at(doc, idx, voice)
    if not g:
        return []
    got = g.words()
    want = range(len(got)) if words is None else [w for w in words
                                                  if 0 <= w < len(got)]
    out = []
    for wi in want:
        run = got[wi]
        text = g.word_text(run)
        if len(run) > 1 and (not resplit or SY.is_accepted(
                text, [g.syls[i].text for i in run], lang)):
            continue
        out.append(text)
    return out


def _join_ruby(doc: Doc, idx: int, voice: int, g: Group, run: list) -> int:
    """Pieces cutting through 傾(かぶ) glued back, keeping their span: the
    bracket is the kanji's reading, sung as one syllable with it."""
    starts, at = [], 0
    for k in run:
        starts.append(at)
        at += len(g.syls[k].text)
    joined = 0
    for k0, _p0, p1 in reversed(SL.ruby_blocks(g.word_text(run))):
        hit = [k for k, x in zip(run, starts)
               if x < p1 and x + len(g.syls[k].text) > k0]
        if len(hit) > 1 and merge_syllables(doc, idx, voice, hit[0], hit[-1]):
            joined += 1
    return joined


def _spread(pieces: list[str], s: Syl) -> list[Syl]:
    """One syllable's text and time shared over its pieces: trailing whitespace
    ends a word (flag cleared), a zero-width space stays as a gapless
    boundary."""
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
    """Glue syllables lo..hi (inclusive) into one timed piece, keeping any
    space between words in its text."""
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
    roman = "".join(s.roman.strip() + ("" if s.part else " ") for s in run[:-1])
    roman = (roman + run[-1].roman.strip()).strip() if any(
        s.roman.strip() for s in run) else ""
    g.syls[lo:hi + 1] = [Syl(text, start, end, run[-1].part, roman)]
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
    """Take every lone ? ! : ; » back onto the word in front (« onto the one
    after), keeping the space and folding in the mark's time."""
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
    """Take the spaces out between the selected words, each unbroken stretch on
    its own."""
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
    """Put the spaces back inside each selected word: every join within it, so
    it undoes join_run."""
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
    """Put a space back after this syllable: two words where there was one (the
    inverse of join_words)."""
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls) - 1 or not g.syls[syl].part:
        return None
    g.syls[syl].part = False
    return f"split after {g.syls[syl].text}"


def set_text(doc: Doc, idx: int, voice: int, syl: int, text: str) -> str | None:
    """Rewrite one syllable keeping its times; a typed space makes two words,
    except French's space before ? or !."""
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
        was = old.text
        if parts[0] != was and old.roman and old.roman == derived_reading(
                doc, idx, voice, syl):
            old.roman = ""
        old.text = parts[0]
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
    """Copy what is selected in place, times and all; a backing voice alone, a
    lead with its whole line."""
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
    """Delete what is selected, by rows: a backing voice alone; a line only
    when its lead is selected."""
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


def insert_adlib(doc: Doc, line: int, text: str = "") -> str | None:
    """A new ad-lib under a line: its last backing voice, drawn below it."""
    if not 0 <= line < len(doc.lines):
        return None
    from .model import words_in
    doc.lines[line].bg.append(Group([Syl(w) for w in words_in(text)]))
    return "new ad-lib"


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
    """Put every line on the other side: main becomes duet, duet becomes main."""
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


def sweep(doc: Doc, idx: int, voice: int, frm: int, to: int,
          t_from: float, t_to: float) -> str | None:
    """Stamp the syllables crossed between two moments of one drag, shared out
    evenly; `to` is left open. Backwards is `untime`."""
    g = _at(doc, idx, voice)
    if not g or not 0 <= frm < len(g.syls) or not 0 <= to < len(g.syls):
        return None
    if to <= frm:
        return None
    n = to - frm
    span = max(0.0, float(t_to) - float(t_from))
    for j in range(1, n + 1):
        at = float(t_from) + span * j / n
        set_time(doc, idx, voice, frm + j - 1, None, at)
        set_time(doc, idx, voice, frm + j, at, at)
    return "timed"


def untime(doc: Doc, idx: int, voice: int, syls) -> str | None:
    """Forget the times of the named syllables only, for a drag wound back over
    its own tracks."""
    g = _at(doc, idx, voice)
    if not g:
        return None
    hit = 0
    for k in syls:
        if 0 <= k < len(g.syls):
            g.syls[k].start = g.syls[k].end = None
            hit += 1
    return "cleared" if hit else None


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
    """Share a line's span out evenly over its syllables."""
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
    """End every lead line before the next lead starts, moving only ends that
    were too late; ad-libs are left where they ring."""
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
    """A new untimed syllable at position `at`, its own word."""
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
    # Taking the last syllable off a word leaves the one before it ending
    # the word, or what is left of it runs straight on into the next one.
    if lo and not g.syls[hi].part:
        g.syls[lo - 1].part = False
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
    """Send a word to the end of the line above or the start of the one below,
    times and all; leads only."""
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
    """Make a backing voice an ordinary line of its own, keeping its times."""
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
    """Cut one backing voice into several wherever it is punctuated, times with
    the words, the separator dropped."""
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
    """Run each unbroken stretch of the selected lines together."""
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
    """Move what is selected up or down: backing voices among their line's
    voices, otherwise whole lines."""
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
    """Make each selected lead line an ad-lib of its neighbour, walking outward
    so a block all answers the line outside it."""
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
    runs = dest.words()
    at = max(0, min(int(at), len(runs)))
    anchor = (runs[at][0] if at < len(runs) else len(dest.syls))
    taken: list = []
    for line, voice, word in sorted(want, key=lambda p: (-p[0], -p[1], -p[2])):
        g, run = _word_syls(doc, line, voice, word)
        if g is None or not run:
            continue
        if g is dest and run[0] < anchor:
            anchor -= len(run)
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
RADIUS = 0.18
MAX_GAP = 0.35


def _nearest(marks: list[float], t: float, floor: float | None = None):
    """The mark closest to `t`, searching from `floor` on."""
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
    """How far this document's words sit from the landmarks (the median, a
    house style kept, not corrected), and how many voted."""
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


CONTEST = 0.10


def claims(doc: Doc, indices, starts: list[float],
           bias: float | None = None,
           contest: float = CONTEST) -> dict:
    """Which mark belongs to which syllable, where only one timed syllable is
    within `contest`; contested and orphan marks are dropped. Keyed biased
    and unbiased."""
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
    """How far this song's marks can be trusted, from repeated words: coverage,
    per-word offsets and spreads, how many are tight, the median spread."""
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


TIGHT = 20


def fill_gaps(doc: Doc, indices, max_gap: float = MAX_GAP) -> str | None:
    """Close small holes between words (up to `max_gap`), leaving rests and
    overlaps alone. No audio."""
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
    """The words further than `reach` from anything the vocal does, as (line,
    voice, word, distance), worst first. A question, not an edit."""
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


WALK_REACH = 0.15
WEAK = 0.5
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
    """Pick one candidate per word, in order, for the least total cost (a
    shortest path, not a greedy walk)."""
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


def _bound(doc: Doc, idx: int, a: float, ends, least: float):
    """When the line starting at `a` must end: the earliest of its own end, the
    next timed line, and where the vocal stops (after `least`)."""
    room = [t for t in (doc.lines[idx].end, _next_start(doc, idx))
            if t is not None and t > a]
    room += [t for t in (ends or ()) if t >= a + least]
    return min(room) if room else None


def _room(doc: Doc, idx: int, a: float) -> float | None:
    """The hard end: the next timed line, or what the document already says. No
    vocal."""
    room = [t for t in (doc.lines[idx].end, _next_start(doc, idx))
            if t is not None and t > a]
    return min(room) if room else None


SPEED_WORDS = 24

LAST_WORD = 0.12


def _sung_syls(g: Group, run: list[int]) -> int:
    """How many syllables the singer gets through in this word: its pieces if
    cut, else `syllables.split`."""
    if len(run) > 1:
        return len(run)
    from . import syllables
    try:
        return max(len(syllables.split(g.word_text(run).strip())), 1)
    except Exception:
        return 1


def speed(doc: Doc, idx: int, voice: int = 0,
          want: int = SPEED_WORDS) -> tuple[float | None, int]:
    """Seconds per syllable nearest line `idx` from start-to-start steps,
    line-final words left out: (seconds, voters), or (None, 0)."""
    import statistics
    got: list[float] = []
    for j in sorted(range(len(doc.lines)), key=lambda j: abs(j - idx)):
        if j == idx:
            continue
        g = _at(doc, j, voice)
        if g is None or not g.syls:
            continue
        runs = g.words()
        if len(runs) < 2:
            continue
        step = []
        for n, run in enumerate(runs[:-1]):
            here, nxt = g.syls[run[0]], g.syls[runs[n + 1][0]]
            if not here.timed or not nxt.timed or nxt.start <= here.start:
                step = []
                break
            step.append((nxt.start - here.start) / _sung_syls(g, run))
        got += step
        if len(got) >= want:
            break
    if not got:
        return None, 0
    return float(statistics.median(got)), len(got)


def rate_from_marks(a: float, need: list[int], marks: list[float],
                    lo: float = 0.08, hi: float = 0.80,
                    reach: float = 0.12) -> float | None:
    """How fast this one line is sung, by fitting speeds to the vocal's
    landmarks; for a first line with no house speed."""
    import bisect
    marks = sorted(marks or ())
    if not marks or len(need) < 2:
        return None
    body = need[:-1]

    def miss(at: float) -> float:
        k = bisect.bisect(marks, at)
        near = []
        if k:
            near.append(marks[k - 1])
        if k < len(marks):
            near.append(marks[k])
        return min((abs(at - m) for m in near), default=reach)

    best, cheapest = None, None
    rate = lo
    while rate <= hi + 1e-9:
        at, cost = a, 0.0
        for syls in body:
            at += rate * syls
            cost += min(miss(at), reach)
        cost /= len(body)
        if cheapest is None or cost < cheapest:
            best, cheapest = rate, cost
        rate *= 1.03
    return best


def from_first(doc: Doc, idx: int, voice: int = 0,
               starts: list[float] | None = None, bias: float | None = None,
               reach: float = WALK_REACH, gap: float = MAX_GAP,
               ends: list[float] | None = None,
               rate: float | None = None,
               weak: set | None = None) -> str | None:
    """Time the rest of a line from its first word at the file's speed, then
    nudge words to landmarks within `reach`. A first pass, not a placement."""
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
    least = WALK_STEP * len(runs)
    exits = sorted(t + (bias or 0.0) for t in (ends or ()))
    hard = _room(doc, idx, a)
    if rate is None:
        rate, _voted = speed(doc, idx, voice)
    if rate is None:
        rate = rate_from_marks(
            a, [_sung_syls(g, r) for r in runs],
            sorted({m + (bias or 0.0) for m in (starts or ())}
                   | {m + (bias or 0.0) for m in (weak or ())}))

    if hard is not None and hard - a < least:
        return None

    if rate:
        share = [rate * _sung_syls(g, r) for r in runs]
        guess, at = [], a
        for w in share[:-1]:
            at += w
            guess.append(at)
        if hard is not None and guess and guess[-1] > hard - LAST_WORD:
            room = max(hard - LAST_WORD - a, WALK_STEP)
            if guess[-1] - a <= 0:
                return None
            k = room / (guess[-1] - a)
            guess = [a + (t - a) * k for t in guess]
            share = [w * k for w in share]
        ceiling = max((hard if hard is not None else guess[-1] + LAST_WORD),
                      guess[-1] + WALK_STEP + 1e-6)
        held = None
    else:
        b = _bound(doc, idx, a, exits, least)
        if b is None or b - a < least:
            return None
        weight = [max(sum(len(g.syls[k].text.strip()) for k in r), 1)
                  for r in runs]
        total = sum(weight)
        share = [(b - a) * w / total for w in weight]
        guess, at = [], a
        for w in share[:-1]:
            at += w
            guess.append(at)
        ceiling, held = b, b

    hurt = {round(m + (bias or 0.0), 6) for m in (weak or ())}
    marks = sorted((m + (bias or 0.0)) for m in (starts or []))
    cands = []
    for want in guess:
        near = [(m, abs(m - want)
                 + (WEAK * reach if round(m, 6) in hurt else 0.0))
                for m in marks if abs(m - want) <= reach]
        cands.append(sorted(near + [(want, reach)]))
    picked = _walk_dp(guess, cands, a, ceiling, WALK_STEP) or guess

    if held is None:
        stops = [t for t in exits if t >= picked[-1] + LAST_WORD
                 and (hard is None or t <= hard)]
        held = min(stops) if stops else None
        b = held if held is not None else (
            hard if hard is not None else picked[-1] + share[-1])
        b = max(b, picked[-1] + WALK_STEP)
        if held is not None:
            share[-1] = max(share[-1], b - picked[-1])

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
            + (f" at {rate:.2f}s a syllable" if rate else
               " as an even share — nothing else here is timed and the vocal "
               "has no marks to read a speed off either")
            + (f", {moved} of them on the vocal" if moved else
               ", none of them on an attack"))


# ------------------------------------------------------------- romanisation
# Readings per syllable (Syl.roman) or per voice (Group.roman); typed ones are
# never replaced, and the romaniser is the player's own
# (spicy_lyrics.readings).
PARTICLES_WRITTEN = {"は": "ha", "へ": "he", "を": "wo"}


def japanese(doc: Doc) -> bool:
    """Whether the lyric is Japanese, which is what decides how kanji read."""
    lang = str(doc.meta.get("LanguageISO2") or doc.meta.get("Language") or "")
    if lang.split("-")[0].lower() == "ja":
        return True
    return any(SL.KANA.search(s.text) for ln in doc.lines
               for g in ln.groups() for s in g.syls)


def needs_roman(doc: Doc) -> bool:
    """Whether anything in the lyric is in a script a reading is for."""
    return any(SL.needs_roman(ln.text()) or any(SL.needs_roman(g.text())
                                                for g in ln.bg)
               for ln in doc.lines)


def group_readings(g: Group, ja: bool, particles: str = "as said") -> list[str]:
    """What the romaniser says each syllable of `g` is read as."""
    texts = [s.text for s in g.syls]
    if not texts or not any(SL.needs_roman(t) for t in texts):
        return [""] * len(texts)
    cont = [i > 0 and g.syls[i - 1].part for i in range(len(texts))]
    try:
        got, _owner = SL.readings(texts, ja, cont)
    except Exception:                                    # noqa: BLE001
        return [""] * len(texts)
    out = []
    for t, r in zip(texts, got):
        r = (r or "").strip()
        if SL.SCRIPTED.search(r):
            r = ""
        if particles == "as written" and t.strip() in PARTICLES_WRITTEN:
            r = PARTICLES_WRITTEN[t.strip()]
        out.append(r if SL.needs_roman(t) else "")
    return out


def derived_reading(doc: Doc, idx: int, voice: int, syl: int,
                    particles: str = "as said") -> str:
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls):
        return ""
    got = group_readings(g, japanese(doc), particles)
    return got[syl] if syl < len(got) else ""


def line_reading(g: Group, ja: bool) -> str:
    """A whole voice's reading spaced into words; Japanese a pykakasi segment
    at a time."""
    text = g.text()
    try:
        k = SL._kakasi() if ja or SL.KANA.search(text) else None
        if k and SL.KANA.search(text) or (k and ja and SL.HAN.search(text)):
            out, at, lead = [], 0, ""
            for seg in SL._convert(k, SL.canon(text)):
                src = seg.get("orig", "") or ""
                rom = SL.particle_rom(src, seg["hepburn"].strip(), at == 0)
                at += len(src)
                if not rom:
                    continue
                # An opening quote or bracket goes onto the word it opens,
                # not the one before: `wa "suki"`, never `wa" suki"`.
                if src.strip() and src.strip()[-1] in SL.OPENERS.strip("\"'"):
                    lead += rom
                    continue
                if lead:
                    out.append(lead + rom)
                    lead = ""
                elif out and src[:1] in "っッ" or (out and not src.strip()):
                    out[-1] += rom
                elif out and not rom[:1].isalnum():
                    out[-1] += rom
                else:
                    out.append(rom)
            if lead:
                out.append(lead)
            got = " ".join(" ".join(out).split())
            if got and not SL.SCRIPTED.search(got):
                return got
        return SL.read_line(text, ja)
    except Exception:                                    # noqa: BLE001
        return ""


def fill_roman(doc: Doc, detail: str = "per syllable",
               particles: str = "as said", indices=None) -> str | None:
    """Give every syllable (or line) with no reading one from the romaniser.

    Readings already there -- typed, or brought in with the file -- are kept.
    Returns what it did, or None when there was nothing it could fill.
    """
    ja = japanese(doc)
    rows = range(len(doc.lines)) if indices is None else indices
    done = 0
    for i in rows:
        if not 0 <= i < len(doc.lines):
            continue
        for g in doc.lines[i].groups():
            if detail == "per line":
                if not g.roman.strip() and not g.roman_text_of_syls() \
                        and SL.needs_roman(g.text()):
                    got = line_reading(g, ja)
                    if got:
                        g.roman = got
                        done += 1
                continue
            got = group_readings(g, ja, particles)
            for s, r in zip(g.syls, got):
                if r and not s.roman.strip():
                    s.roman = r
                    done += 1
    if not done:
        return None
    what = "line" if detail == "per line" else "syllable"
    return f"filled in {done} {what} reading{'s' if done != 1 else ''}"


def clear_roman(doc: Doc, indices=None) -> str | None:
    """Take every reading off the lyric (or off these lines)."""
    rows = range(len(doc.lines)) if indices is None else indices
    done = 0
    for i in rows:
        if not 0 <= i < len(doc.lines):
            continue
        for g in doc.lines[i].groups():
            if g.roman:
                g.roman, done = "", done + 1
            for s in g.syls:
                if s.roman:
                    s.roman, done = "", done + 1
    return "took the romanisation off" if done else None


def set_roman(doc: Doc, idx: int, voice: int, syl: int, text: str) -> str | None:
    """Type one syllable's reading. Empty takes it off."""
    g = _at(doc, idx, voice)
    if not g or not 0 <= syl < len(g.syls):
        return None
    from .model import _clean
    text = " ".join(_clean(text or "").split())
    if g.syls[syl].roman == text:
        return None
    g.syls[syl].roman = text
    return "reading set" if text else "reading taken off"


def set_line_roman(doc: Doc, idx: int, voice: int, text: str) -> str | None:
    """Type a whole voice's reading, the way amll-ttml-db keeps them."""
    g = _at(doc, idx, voice)
    if not g:
        return None
    text = " ".join((text or "").split())
    if g.roman == text:
        return None
    g.roman = text
    return "reading set" if text else "reading taken off"


def roman_count(doc: Doc) -> tuple[int, int]:
    """(syllables with a reading, syllables that want one)."""
    have = want = 0
    for ln in doc.lines:
        for g in ln.groups():
            for s in g.syls:
                if SL.needs_roman(s.text):
                    want += 1
                    have += bool(s.roman.strip())
    return have, want


# ------------------------------------------------------ a line sung again
def _bare_word(text: str) -> str:
    """A word as a repeat is recognised by: letters and digits only, any case."""
    return "".join(ch for ch in SL.unzwsp(text or "").casefold() if ch.isalnum())


def _word_keys(g: Group) -> list[str]:
    return [_bare_word(g.word_text(run)) for run in g.words()]


def repeat_source(doc: Doc, idx: int) -> int | None:
    """The nearest earlier fully timed line singing the same words, or None."""
    if not 0 <= idx < len(doc.lines):
        return None
    want = _word_keys(doc.lines[idx].lead)
    if not any(want):
        return None
    for j in range(idx - 1, -1, -1):
        src = doc.lines[j].lead
        if (src.syls and all(s.timed and s.end is not None for s in src.syls)
                and _word_keys(src) == want):
            return j
    return None


def _recut_like(g: Group, src: Group) -> list | None:
    """Cut `g`'s words where `src` cuts the same words. None where a word
    cannot be spelled that way, which leaves `g` exactly as it was; else
    (first piece, pieces, reading) for each word recut that had a reading."""
    plan, deals = [], []
    for run, srun in zip(g.words(), src.words()):
        if len(run) == len(srun):
            plan.append([g.syls[k] for k in run])
            continue
        text = g.word_text(run)
        # Where the source's seams fall, counted in letters: the same word
        # in another line may differ in case and in the marks round it.
        seams, n = [], 0
        for k in srun[:-1]:
            n += sum(1 for ch in src.syls[k].text if ch.isalnum())
            seams.append(n)
        cuts, n = [], 0
        for i, ch in enumerate(text):
            if n in seams and ch.isalnum() and (not cuts or cuts[-1][0] != n):
                cuts.append((n, i))
            if ch.isalnum():
                n += 1
        if len(cuts) != len(seams):
            return None
        pieces, prev = [], 0
        for _n, at in cuts:
            pieces.append(text[prev:at])
            prev = at
        pieces.append(text[prev:])
        if not all(pieces) or "".join(pieces) != text:
            return None
        last = g.syls[run[-1]]
        made = [Syl(p, None, None, True) for p in pieces]
        made[-1].part = last.part
        roman = "".join(g.syls[k].roman.strip() for k in run)
        if roman:
            deals.append((sum(map(len, plan)), len(made), roman))
        plan.append(made)
    g.syls[:] = [s for word in plan for s in word]
    return deals


def fill_from_repeat(doc: Doc, idx: int) -> str | None:
    """Time a line that repeats an earlier one from its first timed syllable:
    the earlier line's times shifted, backing voices too."""
    j = repeat_source(doc, idx)
    if j is None:
        return None
    anchor = _anchor(doc.lines[idx].lead)
    if anchor is None or not _cut_like(doc, idx, j):
        return None
    delta = _delta(doc, j, anchor)
    _copy_times(doc, idx, j, delta)
    return f"line {idx + 1} timed from line {j + 1}, {delta:+.2f}s on"


def _anchor(lead: Group) -> tuple | None:
    """(word, syllable in it, its start, syllable in the line) of the first
    syllable with a time. Read before the line is recut: a recut makes its
    syllables afresh."""
    return next(((w, r, lead.syls[k].start, k)
                 for w, run in enumerate(lead.words())
                 for r, k in enumerate(run) if lead.syls[k].timed), None)


def _cut_like(doc: Doc, idx: int, j: int) -> bool:
    """Line idx's lead cut into the syllables line j's is cut into.

    Other words sung in as many syllables (a run grouped by its syllables)
    are copied syllable for syllable, each line left cut as it is -- by the
    sung syllables where the two are not cut alike (see _units)."""
    lead, src = doc.lines[idx].lead, doc.lines[j].lead
    if _word_keys(lead) != _word_keys(src):
        return (len(lead.syls) == len(src.syls)
                or len(_units(doc, lead)) == len(_units(doc, src)))
    if len(lead.syls) == len(src.syls) and [
            len(x) for x in lead.words()] == [len(x) for x in src.words()]:
        return True
    deals = _recut_like(lead, src)
    if deals is None:
        return False
    for k, n, roman in deals:
        _deal_roman(doc, idx, 0, k, n, roman)
    return True


def _delta(doc: Doc, j: int, anchor: tuple,
           dst: Group | None = None) -> float:
    """How far the anchor's line sits from line j, by the syllable `anchor`
    names -- read off it before it was recut, found in j's cut. `dst`, the
    anchor's own lead, for a line in other words: there only the sung
    syllables line up, and the anchor is the first of its chip's."""
    src = doc.lines[j].lead
    w, r, at, k = anchor
    if dst is not None:
        if len(dst.syls) == len(src.syls):
            return at - src.syls[min(k, len(src.syls) - 1)].start
        du, su = _units(doc, dst), _units(doc, src)
        n = next((n for n, u in enumerate(du) if u[0] == k), 0)
        return at - _when(src, su[min(n, len(su) - 1)], False)
    r = r if r < len(src.words()[w]) else 0
    return at - src.syls[src.words()[w][r]].start


def _copy_times(doc: Doc, idx: int, j: int, delta: float) -> None:
    """Every time in line j, moved by delta, onto line idx -- whose lead is
    already cut like j's. A backing voice comes along only where j has the
    same one, in the same place, timed; any other is left exactly as it was,
    untimed if it was, for the tap that is the only thing that knows when."""
    ln, src = doc.lines[idx], doc.lines[j]

    def copy(dst: Group, frm: Group) -> None:
        if len(dst.syls) != len(frm.syls):
            # Cut differently, sung alike: each chip from the sung syllables
            # it holds -- its first one's start to its last one's end.
            du, su = _units(doc, dst), _units(doc, frm)
            if len(du) != len(su):
                return
            for k, d in enumerate(dst.syls):
                mine = [n for n, u in enumerate(du) if u[0] == k]
                a = _when(frm, su[mine[0]], False)
                b = _when(frm, su[mine[-1]], True)
                d.start = max(0.0, a + delta) if a is not None else None
                d.end = (max(d.start or 0.0, b + delta)
                         if b is not None else d.start)
            return
        for d, s in zip(dst.syls, frm.syls):
            d.start = max(0.0, s.start + delta) if s.start is not None else None
            d.end = (max(d.start or 0.0, s.end + delta)
                     if s.end is not None else d.start)

    copy(ln.lead, src.lead)
    for g, sg in zip(ln.bg, src.bg):
        if ([_bare_word(s.text) for s in g.syls]
                == [_bare_word(s.text) for s in sg.syls]
                and all(s.timed for s in sg.syls)):
            copy(g, sg)
    for attr in ("start", "end"):
        v = getattr(src, attr)
        if v is not None:
            setattr(ln, attr, max(0.0, v + delta))


# ----------------------------------------------- lines grouped as one
# A part holding LIKE is lines sung alike in other words (see make_alike); no
# line key can equal it.
LIKE = ("~",)


def line_key(ln) -> tuple:
    """A line as a group recognises it: its lead's words, as repeat_source
    compares them -- case, punctuation and the cut into syllables aside."""
    return tuple(_word_keys(ln.lead))


def _full(ln) -> bool:
    """Every syllable of the lead timed, to the end: a line to copy from."""
    return bool(ln.lead.syls) and all(s.timed and s.end is not None
                                      for s in ln.lead.syls)


def _units(doc: Doc, g: Group, ja: bool | None = None,
           memo: dict | None = None) -> list:
    """A voice's sung syllables in order: (chip, start, end) as fractions of
    the chip by letters; an uncut word holds as many as the rule cuts."""
    ja = japanese(doc) if ja is None else ja
    whole = {run[0] for run in g.words() if len(run) == 1}
    memo = _split_memo() if memo is None else memo
    out = []
    for k, s in enumerate(g.syls):
        pieces = [s.text]
        if k in whole and not any(ch.isspace() or ch == "\u200b"
                                  for ch in s.text.strip()):
            pieces = memo.get((s.text, ja))
            if pieces is None:
                from . import syllables as SY
                pieces = memo[(s.text, ja)] = SY.split(
                    s.text, "sung", SY.DEFAULT_LANG, "syllable", ja)
        sizes = [sum(ch.isalnum() for ch in p) for p in pieces]
        total = sum(sizes)
        if not total:
            sizes, total = [1] * len(pieces), len(pieces)
        at = 0
        for n in sizes:
            out.append((k, at / total, (at + n) / total))
            at += n
    return out


_SPLITS: dict = {"at": None, "memo": {}}


def _split_memo() -> dict:
    """The syllable rule's answers so far, (word, japanese) -> pieces: asked
    for every line on every layout, and the same words come round all song
    long. Forgotten when a kept or held split changes what it answers."""
    from . import keys as K
    from . import shared_splits as SH
    from . import syllables as SY
    got = K.config()
    at = (id(got.get("splits")), repr(SY._HELD), repr(SY._CHOSEN),
          SH.version(), bool(got.get("split_shared", True)))
    if _SPLITS["at"] != at or len(_SPLITS["memo"]) > 20000:
        _SPLITS["at"], _SPLITS["memo"] = at, {}
    return _SPLITS["memo"]


def sung(doc: Doc, ln) -> int:
    """How many syllables a line's lead is sung in (see _units)."""
    return len(_units(doc, ln.lead))


def _counts(doc: Doc) -> list:
    ja, memo = japanese(doc), _split_memo()
    return [len(_units(doc, ln.lead, ja, memo)) for ln in doc.lines]


def _when(g: Group, u: tuple, end: bool) -> float | None:
    """When a sung syllable (from _units) starts or ends, read off its chip."""
    s = g.syls[u[0]]
    if s.start is None:
        return None
    b = s.end if s.end is not None else s.start
    return s.start + (b - s.start) * (u[2] if end else u[1])


def _shared(a: tuple, b: tuple) -> float:
    """How much of two lines' words are the same ones, 0 to 1, any order."""
    if not a or not b:
        return 0.0
    from collections import Counter
    return sum((Counter(a) & Counter(b)).values()) / max(len(a), len(b))


def blocks(part: tuple) -> list:
    """A group's blocks of lines, sung alike: one for a group of repeats,
    one for each stretch of lines sung alike (LIKE between them). The first
    is the one picked -- a chorus, where lines are sung like the chorus."""
    out, cur = [], []
    for key in part:
        if key == LIKE:
            out.append(tuple(cur))
            cur = []
        else:
            cur.append(key)
    out.append(tuple(cur))
    return out


def _joined(bs: list) -> tuple:
    out: tuple = ()
    for n, b in enumerate(bs):
        out += ((LIKE,) if n else ()) + tuple(b)
    return out


def _shape(doc: Doc, keys: tuple, counts: list,
           lines: list | None = None) -> list:
    """The syllable counts each line of `keys` is sung in, from every line
    of the song that sings its words (`lines`, their keys, if in hand)."""
    want: dict = {k: set() for k in keys}
    lines = [line_key(ln) for ln in doc.lines] if lines is None else lines
    for i, mine in enumerate(lines):
        got = want.get(mine)
        if got is not None:
            got.add(counts[i])
    return [want[k] for k in keys]


def _shape_of(doc: Doc, bs: list, counts: list, keys: list) -> list:
    """_shape over every block of a group at once: the counts each line of
    it is sung in, line for line, whichever of them is sung."""
    want: dict = {}
    for block in bs:
        for o, k in enumerate(block):
            want.setdefault(k, set()).add(o)
    shape = [set() for _ in range(max((len(x) for x in bs), default=0))]
    for i, mine in enumerate(keys):
        for o in want.get(mine, ()):
            shape[o].add(counts[i])
    return shape


def _reach(doc: Doc, keys: tuple, at: int, shape: list, counts: list,
           free: set | None = None) -> int:
    """How many of the group's lines, from its first, are sung from line `at`:
    by words, or by syllable shape; a last line by shape keeps half the
    words."""
    n = 0
    while (n < len(keys) and at + n < len(doc.lines)
           and (free is None or at + n in free)):
        mine = line_key(doc.lines[at + n])
        if mine != keys[n] and (n == 0 or not any(mine) or n >= len(shape)
                                or counts[at + n] not in shape[n]):
            break
        n += 1
    while n > 1:
        mine = line_key(doc.lines[at + n - 1])
        if mine == keys[n - 1] or _shared(mine, keys[n - 1]) >= 0.5:
            break
        n -= 1
    return n


def _block_runs(doc: Doc) -> list:
    """part_runs, each with the block it is a run of: (part, block, first
    line, how many lines)."""
    keys = [line_key(ln) for ln in doc.lines]
    counts = _counts(doc) if doc.parts else []
    found = []
    for n, part in enumerate(doc.parts):
        bs = blocks(part)
        shape = _shape_of(doc, bs, counts, keys)
        seen = set()
        for b, block in enumerate(bs):
            if not block or block in seen:
                continue
            seen.add(block)
            least = min(2, len(block))
            for at in range(len(keys)):
                if keys[at] != block[0]:
                    continue
                got = _reach(doc, block, at, shape, counts)
                if got >= least:
                    found.append((n, b, at, got))
    found.sort(key=lambda x: (-x[3], x[2], x[0]))
    taken: set = set()
    out = []
    for n, b, at, got in found:
        span = set(range(at, at + got))
        if span & taken:
            continue
        taken |= span
        out.append((n, b, at, got))
    return sorted(out, key=lambda x: x[2])


def part_runs(doc: Doc) -> list:
    """Every place a group is sung as (part, first line, count): from its first
    line, at least two lines, longest runs first, no line in two."""
    return [(n, at, got) for n, _b, at, got in _block_runs(doc)]


def block_runs(doc: Doc) -> list:
    """part_runs with the block each is a run of: (part, block, first line,
    how many lines)."""
    return _block_runs(doc)


def by_syllables(doc: Doc, runs: list | None = None,
                 groups: set | None = None) -> set:
    """The lines of every run (of `groups`, where given) that do not sing
    the words of their group's first block: grouped because they are sung
    in as many syllables. `runs` from block_runs, if in hand."""
    out = set()
    for n, _bl, at, got in _block_runs(doc) if runs is None else runs:
        if groups is not None and n not in groups:
            continue
        first = blocks(doc.parts[n])[0]
        for o in range(got):
            if o >= len(first) or line_key(doc.lines[at + o]) != first[o]:
                out.add(at + o)
    return out


def _syl_note(doc: Doc, groups: set) -> str:
    """What of `groups` was grouped by its syllables, said after the rest."""
    got = sorted(by_syllables(doc, groups=groups))
    if not got:
        return ""
    return (f" — line{'s' * (len(got) > 1)} "
            + ", ".join(str(i + 1) for i in got)
            + " by syllables: other words, as many of them sung")


def run_at(doc: Doc, idx: int) -> tuple | None:
    """The (part, first line, length) run line idx is in, if any."""
    return next((r for r in part_runs(doc) if r[1] <= idx < r[1] + r[2]), None)


def _sung_at(doc: Doc, src: tuple, size: int, counts: list) -> list:
    """Every line the first `size` lines of block `src` are sung from, by
    its words -- in a run of its own group or of another's."""
    if len(src) < size:
        return []
    shape = _shape(doc, src, counts)
    return [q for q in range(len(doc.lines) - size + 1)
            if line_key(doc.lines[q]) == src[0]
            and _reach(doc, src, q, shape, counts) >= size]


def part_source(doc: Doc, n: int, at: int, size: int) -> int | None:
    """Where to copy a run of group n at line `at`, `size` lines long, from: a
    timed run of the same group, nearest before first, then after."""
    def timed(q: int) -> bool:
        return all(_full(doc.lines[q + o]) for o in range(size))

    ok = {q for m, q, got in part_runs(doc)
          if m == n and q != at and got >= size and timed(q)}
    part = doc.parts[n] if 0 <= n < len(doc.parts) else ()
    if LIKE in part:
        counts = _counts(doc)
        for block in blocks(part):
            ok |= {q for q in _sung_at(doc, block, size, counts)
                   if (q + size <= at or q >= at + size) and timed(q)}
    before = sorted(q for q in ok if q < at)
    if before:
        return before[-1]
    return min(ok) if ok else None


def make_part(doc: Doc, lines: list) -> str | None:
    """Group lines -- the first to the last of them, and all in between."""
    if not lines:
        return None
    a, b = min(lines), max(lines)
    if not (0 <= a and b < len(doc.lines)):
        return None
    keys = tuple(line_key(doc.lines[i]) for i in range(a, b + 1))
    if not all(any(k) for k in keys):
        return None
    if keys in doc.parts:
        return None
    doc.parts.append(keys)
    runs = [r for r in part_runs(doc) if r[0] == len(doc.parts) - 1]
    again = [r for r in runs if r[1] != a]
    span = f"line {a + 1}" if a == b else f"lines {a + 1}–{b + 1}"
    if not again:
        return f"grouped {span} — it is not sung anywhere else yet"
    return (f"grouped {span} — sung again {len(again)} time(s), from line"
            f"{'s' if len(again) > 1 else ''} "
            + ", ".join(str(r[1] + 1) for r in again)
            + _syl_note(doc, {len(doc.parts) - 1}))


# --------------------------------------------- lines sung like others
def _lines(a: int, size: int) -> str:
    return f"line {a + 1}" if size == 1 else f"lines {a + 1}–{a + size}"


def _repeated(doc: Doc, block: tuple, counts: list) -> bool:
    """A block sung by its own words in two places at least: a chorus, a
    group of repeats in its own right."""
    return len(_sung_at(doc, block, min(2, len(block)), counts)) >= 2


def _settle(doc: Doc, groups: list, touched: set) -> None:
    """doc.parts from `groups` (each a list of blocks, None for one taken
    out). A touched group left with one block keeps it only where that
    block is a chorus -- it was there for the lines sung like it otherwise
    -- and one left with none goes."""
    counts = _counts(doc)
    out = []
    for n, bs in enumerate(groups):
        bs = list(dict.fromkeys(x for x in bs if x))
        if not bs:
            continue
        if n in touched and len(bs) == 1 and not _repeated(doc, bs[0], counts):
            continue
        out.append(_joined(bs))
    doc.parts[:] = out


def alike_blocked(doc: Doc, lines: list, runs: list | None = None) -> str | None:
    """Why lines cannot be picked as sung like others, whoever with: one of
    them is in the middle of a group's run. A run that STARTS at their first
    line is theirs -- picking them adds to its group -- and lines sung like
    others that they cover are taken over by them."""
    a, b = min(lines), max(lines)
    size = b - a + 1
    runs = _block_runs(doc) if runs is None else runs
    for n, _bl, at, got in runs:
        if at > b or at + got <= a:
            continue
        like = LIKE in doc.parts[n]
        if at == a and (got >= size or like):
            continue
        if like and a <= at and at + got - 1 <= b:
            continue
        if at == a:
            return (f"the group here is only {_lines(at, got)} long — pick "
                    "those, or ungroup it first")
        i = max(a, at)
        return (f"line {i + 1} is in the middle of a group "
                f"({_lines(at, got)}) — pick from its first line, or "
                "ungroup it first")
    return None


def alike_why(doc: Doc, lines: list, q: int, counts: list | None = None,
              runs: list | None = None) -> str | None:
    """Why the lines from the first of `lines` to the last cannot be sung
    like the as many lines from q -- None where they can. Each line must be
    sung in as many syllables as its partner, the two stretches must not
    overlap, and they must not sing all the same words (that is a repeat,
    and Group's). Neither may start in the middle of a group (alike_blocked);
    q's lines may be inside a chorus, where they have it to copy from."""
    if not lines:
        return "no lines picked"
    a, b = min(lines), max(lines)
    size = b - a + 1
    if not (0 <= a and b < len(doc.lines)):
        return "no such lines"
    if not 0 <= q or q + size > len(doc.lines):
        return f"there are not {size} lines from line {q + 1} on"
    if a < q + size and q <= b:
        return ("those are the lines being paired" if q == a else
                f"{_lines(q, size)} overlap{'s' * (size == 1)} "
                f"{_lines(a, size)}")
    mine = [line_key(doc.lines[i]) for i in range(a, b + 1)]
    theirs = [line_key(doc.lines[q + o]) for o in range(size)]
    if not all(any(k) for k in mine + theirs):
        return "a line with no words in it cannot be sung like anything"
    if theirs == mine:
        return (f"{_lines(q, size)} sing{'s' * (size == 1)} the same words "
                "— that is a repeat: Group them instead")
    counts = _counts(doc) if counts is None else counts
    for o in range(size):
        if counts[a + o] != counts[q + o]:
            return (f"line {q + o + 1} is sung in {counts[q + o]} "
                    f"syllables, line {a + o + 1} in {counts[a + o]}")
    groups = [blocks(p) for p in doc.parts]
    like = [LIKE in p for p in doc.parts]
    mine = _owner(groups, like, tuple(mine))
    if mine is not None and mine == _owner(groups, like, tuple(theirs)):
        return (f"{_lines(q, size)} {'is' if size == 1 else 'are'} sung "
                f"alike with {_lines(a, size)} already — Ungroup on "
                f"{'it' if size == 1 else 'them'} takes "
                f"{'it' if size == 1 else 'them'} out")
    runs = _block_runs(doc) if runs is None else runs
    for n, _bl, at, got in runs:
        if LIKE in doc.parts[n] and at < q < at + got:
            return (f"line {q + 1} is in the middle of {_lines(at, got)}, "
                    f"sung like others — click line {at + 1}")
    return alike_blocked(doc, lines, runs)


def alike_candidates(doc: Doc, lines: list) -> list:
    """Every q the lines could be sung like (alike_why), timed blocks first,
    then by nearness -- before the lines, then after them."""
    if not lines:
        return []
    a, b = min(lines), max(lines)
    size = b - a + 1
    counts, runs = _counts(doc), _block_runs(doc)
    out = [q for q in range(len(doc.lines) - size + 1)
           if alike_why(doc, lines, q, counts, runs) is None]
    return sorted(out, key=lambda q: (
        not all(_full(doc.lines[q + o]) for o in range(size)),
        q > a, abs(q - a)))


def _owner(groups: list, like: list, keys: tuple) -> int | None:
    """The group lines singing `keys` belong to as lines sung alike: one
    with a block that starts with them, or a chorus that does."""
    for n, bs in enumerate(groups):
        if like[n] and any(x and x[:len(keys)] == keys for x in bs):
            return n
    for n, bs in enumerate(groups):
        if bs and bs[0] and bs[0][:len(keys)] == keys:
            return n
    return None


def _waiting(doc: Doc, at: int, size: int) -> bool:
    """A run with nothing timed in it but the first syllable of its first
    line -- one tap, waiting for the rest to follow it (as a tap on a run
    is answered in the editor)."""
    for o in range(size):
        for v, g in enumerate(doc.lines[at + o].groups()):
            for k, s in enumerate(g.syls):
                if s.timed != ((o, v, k) == (0, 0, 0)):
                    return False
    return True


def make_alike(doc: Doc, lines: list, q: int) -> str | None:
    """Make the lines from the first of `lines` to the last sung like as many
    lines from q, merging with existing alike groups."""
    if not lines:
        return None
    a, b = min(lines), max(lines)
    size = b - a + 1
    runs = _block_runs(doc)
    if alike_why(doc, lines, q, None, runs) is not None:
        return None
    k_s = tuple(line_key(doc.lines[i]) for i in range(a, b + 1))
    k_q = tuple(line_key(doc.lines[q + o]) for o in range(size))
    groups = [list(blocks(p)) for p in doc.parts]
    like = [LIKE in p for p in doc.parts]
    counts = _counts(doc)

    def done(said: str, n: int) -> str:
        _settle(doc, groups, {n})
        return said + _fill_waiting(doc, a)

    # Carrying on a pairing: the stretches just before both, of one group.
    for n, bl, at, got in runs:
        if not like[n] or len(groups[n][bl]) != got:
            continue
        for n2, bl2, at2, got2 in runs:
            if n2 != n or bl2 == bl or len(groups[n][bl2]) != got2:
                continue
            if at + got == a and at2 + got2 == q and got2 == got:
                groups[n][bl] = groups[n][bl] + k_s
                groups[n][bl2] = groups[n][bl2] + k_q
            elif b + 1 == at and q + size == at2 and got2 == got:
                groups[n][bl] = k_s + groups[n][bl]
                groups[n][bl2] = k_q + groups[n][bl2]
            else:
                continue
            lo = min(a, at)
            return done(f"{_lines(lo, got + size)} sung like "
                        f"{_lines(min(q, at2), got + size)} — the pairing "
                        "grown", n)

    def owner(keys: tuple) -> int | None:
        return _owner(groups, like, keys)

    # Stretches sung like others that these lines cover: theirs now.
    took = [(n, bl) for n, bl, at, got in runs
            if like[n] and a <= at and at + got - 1 <= b
            and (at != a or got < size)]
    n_s = owner(k_s)
    if n_s is None and took:
        n_s = took[0][0]
    for n, bl in took:
        groups[n][bl] = None
    n_q = owner(k_q)

    def add(n: int, keys: tuple) -> None:
        if not any(x and x[:len(keys)] == keys for x in groups[n]):
            groups[n].append(keys)

    if n_s is None and n_q is None:
        groups.append([k_q, k_s])
        like.append(True)
        n = len(groups) - 1
    elif n_s is None:
        add(n_q, k_s)
        n = n_q
    elif n_q is None:
        add(n_s, k_q)
        n = n_s
    elif n_s == n_q:
        n = n_s
    else:
        # Two groups sung alike are one: into the chorus, where one is.
        n, gone = ((n_s, n_q) if any(x and _repeated(doc, x, counts)
                                     for x in groups[n_s][:1])
                   else (n_q, n_s))
        for x in groups[gone]:
            if x:
                add(n, x)
        groups[gone] = []
    key = groups[n][0]
    said = (f"{_lines(a, size)} sung like {_lines(q, size)} ("
            + "·".join(str(counts[i]) for i in range(a, b + 1))
            + " syllables)")
    _settle(doc, groups, {n})
    n = next((m for m, p in enumerate(doc.parts) if blocks(p)[0] == key),
             None)
    if n is not None:
        where = places(doc, n)
        if len(where) > 2:
            said += (f" — sung alike in {len(where)} places: "
                     + ", ".join(_lines(at, got) for at, got in where))
    return said + _fill_waiting(doc, a)


def places(doc: Doc, n: int) -> list:
    """Every (first line, how many) group n is sung at: its runs, and where
    lines sung alike are sung inside another group's run -- two lines of a
    chorus that a verse is sung like are still sung there."""
    got = {(r[1], r[2]) for r in part_runs(doc) if r[0] == n}
    if LIKE in doc.parts[n]:
        counts = _counts(doc)
        for block in blocks(doc.parts[n]):
            got |= {(q, len(block)) for q in _sung_at(doc, block, len(block),
                                                     counts)}
    out = []
    for at, size in sorted(got, key=lambda x: (x[0], -x[1])):
        if not out or at >= out[-1][0] + out[-1][1]:
            out.append((at, size))
    return out


def _fill_waiting(doc: Doc, at: int) -> str:
    """Every run of the group line `at` is in that has had its first
    syllable tapped and nothing else, timed from the rest of the group now
    -- said after what made it so."""
    run = run_at(doc, at)
    if run is None:
        return ""
    timed = []
    for n, first, got in part_runs(doc):
        if n == run[0] and _waiting(doc, first, got):
            said = fill_part(doc, first)
            if said:
                timed.append(_lines(first, got))
    if timed:
        return "; timed " + ", ".join(timed) + " from the others"
    if not any(all(_full(doc.lines[at + o]) for o in range(size))
               for at, size in places(doc, run[0])):
        return "; once one of them is timed, a tap on another's first " \
               "syllable times it"
    return "; a tap on a first syllable now times the rest of that line" \
           + ("s" if run[2] > 1 else "")

def _blocks(doc: Doc, keys: list, free: set) -> dict:
    """Every block of two or more lines sung again, as its keys -> where it
    starts, counting only lines in `free` and no line twice. Sung again from
    its first line's words, with any line after that sung in as many
    syllables (see _reach)."""
    found = {}
    n = len(keys)
    counts = _counts(doc)
    for i in range(n):
        if i not in free or not keys[i]:
            continue
        for j in range(i + 1, n):
            if keys[j] != keys[i] or j not in free:
                continue
            size = 0
            while (i + size < j and j + size < n and keys[i + size]
                   and keys[j + size]
                   and (keys[i + size] == keys[j + size]
                        or (size and counts[i + size] == counts[j + size]))
                   and i + size in free and j + size in free):
                size += 1
            while size > 1 and keys[i + size - 1] != keys[j + size - 1] and \
                    _shared(keys[i + size - 1], keys[j + size - 1]) < 0.5:
                size -= 1
            if size >= 2:
                found.setdefault(tuple(keys[i:i + size]), None)
    out = {}
    for block in found:
        shape = _shape(doc, block, counts)
        at, starts = 0, []
        while at + len(block) <= n:
            if keys[at] == block[0] and _reach(
                    doc, block, at, shape, counts, free) >= len(block):
                starts.append(at)
                at += len(block)
            else:
                at += 1
        if len(starts) >= 2:
            out[block] = starts
    return out

def auto_parts(doc: Doc) -> str | None:
    """Lines ▸ Group for the whole song: every repeated block of two or more
    lines becomes a group, biggest saving first; hand groups kept."""
    keys = [line_key(ln) for ln in doc.lines]
    free = set(range(len(keys)))
    for _n, at, got in part_runs(doc):
        free -= set(range(at, at + got))
    made, new = [], set()
    while True:
        blocks = _blocks(doc, keys, free)
        if not blocks:
            break
        block, starts = max(blocks.items(),
                            key=lambda kv: (len(kv[0]) * (len(kv[1]) - 1),
                                            len(kv[0]), -kv[1][0]))
        if block not in doc.parts:
            doc.parts.append(block)
            new.add(len(doc.parts) - 1)
            made.append((starts[0], len(block), len(starts)))
        for at in starts:
            free -= set(range(at, at + len(block)))
    if not made:
        return None
    made.sort()
    return (f"grouped {len(made)} repeated part{'s' * (len(made) != 1)}: "
            + "; ".join(f"lines {a + 1}–{a + n} ×{k}" for a, n, k in made)
            + _syl_note(doc, new))

def sections(doc: Doc, most: int = 0) -> list:
    """The song cut into sections, in order: (first line, how many, group or
    None). A section is a run of a group -- a chorus where it is sung -- or
    the lines between two of them (a verse, a bridge). Those are cut further
    where the singer changes, when both sides keep two lines, and into even
    pieces of at most `most` lines when given, so a song with nothing sung
    twice can still be shared out."""
    out = []
    runs = part_runs(doc)
    at = 0

    def loose(a: int, b: int) -> None:
        cuts = [a]
        for i in range(a + 2, b - 1):
            if doc.lines[i].agent != doc.lines[i - 1].agent and i - cuts[-1] >= 2:
                cuts.append(i)
        cuts.append(b)
        for x, y in zip(cuts, cuts[1:]):
            size = y - x
            pieces = max(1, -(-size // most)) if most else 1
            for k in range(pieces):
                lo = x + size * k // pieces
                hi = x + size * (k + 1) // pieces
                if hi > lo:
                    out.append((lo, hi - lo, None))

    for n, first, got in runs:
        if first > at:
            loose(at, first)
        out.append((first, got, n))
        at = first + got
    if at < len(doc.lines):
        loose(at, len(doc.lines))
    return out


def share_out(doc: Doc, people: list, most: int = 0) -> dict:
    """Sections shared between `people` (in the order given, the first
    taking ties): person -> line numbers. Every place a group is sung goes
    to ONE person, since timing it once times them all; it weighs as its
    first run plus a quarter of each repeat, for the checking. The heaviest
    goes first, each to whoever has least so far."""
    if not people:
        return {}
    if not most:
        # About two pieces each, rounded down: rounded up, the last piece
        # comes out short and one person is left with half a share.
        most = max(3, len(doc.lines) // (2 * len(people)))
    units: dict = {}
    for first, size, n in sections(doc, most):
        key = ("g", n) if n is not None else ("s", first)
        units.setdefault(key, []).append(range(first, first + size))
    load = {p: 0.0 for p in people}
    got: dict = {p: [] for p in people}

    def weight(runs):
        return len(runs[0]) + 0.25 * sum(len(r) for r in runs[1:])

    for key, runs in sorted(units.items(),
                            key=lambda kv: (-weight(kv[1]), kv[1][0].start)):
        who = min(people, key=lambda p: (load[p], people.index(p)))
        load[who] += weight(runs)
        for r in runs:
            got[who].extend(r)
    return {p: sorted(v) for p, v in got.items()}


def drop_parts(doc: Doc, lines: list) -> str | None:
    """Ungroup whatever group any of these lines is a run of -- or, on
    lines sung alike, just those lines: the rest of them stay together."""
    hit = {(n, bl) for n, bl, at, got in _block_runs(doc)
           if any(at <= i < at + got for i in lines)}
    if not hit:
        return None
    whole = {n for n, bl in hit if LIKE not in doc.parts[n]}
    alike = {(n, bl) for n, bl in hit if n not in whole}
    groups = [list(blocks(p)) for p in doc.parts]
    for n in whole:
        groups[n] = []
    for n, bl in alike:
        groups[n][bl] = None
    _settle(doc, groups, {n for n, _bl in alike})
    if not whole:
        return (f"took {len(alike)} stretch{'es' * (len(alike) > 1)} of "
                "lines sung like others out of their group")
    return f"ungrouped {len(whole)} group(s)"


def fill_part(doc: Doc, idx: int) -> str | None:
    """Time a whole run of a group from one syllable in it, with one shift for
    the run; lines that cannot be cut alike are named and left."""
    run = run_at(doc, idx)
    if run is None:
        return None
    n, at, size = run
    q = part_source(doc, n, at, size)
    if q is None:
        return None
    first = next((o for o in range(size)
                  if any(s.timed for s in doc.lines[at + o].lead.syls)), None)
    if first is None:
        return None
    anchor = _anchor(doc.lines[at + first].lead)
    if not _cut_like(doc, at + first, q + first):
        return None
    other = line_key(doc.lines[at + first]) != line_key(doc.lines[q + first])
    delta = _delta(doc, q + first, anchor,
                   doc.lines[at + first].lead if other else None)
    kept, sung = [], []
    for o in range(size):
        if o != first and not _cut_like(doc, at + o, q + o):
            kept.append(at + o + 1)
            continue
        if line_key(doc.lines[at + o]) != line_key(doc.lines[q + o]):
            sung.append(at + o + 1)
        _copy_times(doc, at + o, q + o, delta)

    def span(a: int) -> str:
        return (f"line {a + 1}" if size == 1
                else f"lines {a + 1}–{a + size}")

    said = (f"{span(at)} timed {'as one ' * (size > 1)}from {span(q)}, "
            f"{delta:+.2f}s on")
    if sung:
        said += (" — by syllables, other words: line"
                 f"{'s' if len(sung) > 1 else ''} "
                 + ", ".join(map(str, sung)))
    if kept:
        said += (" — left as they were, cut differently: line"
                 f"{'s' if len(kept) > 1 else ''} "
                 + ", ".join(map(str, kept)))
    return said


# ------------------------------------------------- a reading put right
_NOT_READ = set(",.!?;:\"“”«»()[]{}…—–¡¿、。，．！？「」『』")


def reading_key(text: str) -> str:
    """A reading as two are compared: no case, no spacing, no punctuation,
    no accents -- "Tōkyō," and "tokyo" say the same thing; "toukyou" does
    not, and is worth showing to somebody."""
    import unicodedata
    flat = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(ch for ch in flat if ch.isalnum())


def correct_reading(doc: Doc, idx: int, voice: int, text: str) -> str | None:
    """Put a voice's reading right from a better one, in place, keeping its
    syllables: word by word, then letter alignment inside words."""
    g = _at(doc, idx, voice)
    if not g:
        return None
    text = " ".join((text or "").split())
    # Syllables not read yet take the romaniser's reading as their guide, so a
    # line with one syllable read (じゃん "jan") does not pour all of Genius' into it.
    derived = group_readings(g, japanese(doc))
    guide = [s.roman.strip() or (derived[k] if k < len(derived) else "")
             for k, s in enumerate(g.syls)]
    if SL.CJK.search(g.text()):
        # Where Genius says the dictionary guessed wrong (相 ai, not sou),
        # read those pieces again so the seams are found against a right one.
        guide = SL.fit_readings([s.text for s in g.syls], guide, text)
    have = [k for k, r in enumerate(guide) if r]
    if not have:
        return set_line_roman(doc, idx, voice, text)
    runs = g.words()
    words = [w for w in (_flat(x) for x in text.split()) if w]
    plan = {}
    if len(words) == len(runs):
        for run, word in zip(runs, words):
            mine = [k for k in run if guide[k]]
            if not mine:
                if _bare_word(g.word_text(run)) != _bare_word(word):
                    plan = {}                # the words are not lined up after all
                    break
                continue
            got = _share([_flat(guide[k]) or guide[k] for k in mine], word)
            if got is None:
                plan = {}
                break
            plan.update(zip(mine, got))
    if not plan:
        # The whole line against the whole reading, the Latin syllables standing for
        # themselves: "Lokomoko" for Loco Moco, "two" for 2 fall to them, not to a kana.
        # Digits are no anchor: 14 is sung "juushi", and keeps going to the kana before it.
        own = [(k, _flat(guide[k]) if guide[k] else "" if SL.needs_roman(s.text)
                or any(ch.isdigit() for ch in s.text) else _flat(s.text).casefold())
               for k, s in enumerate(g.syls)]
        own = [(k, piece) for k, piece in own if piece]
        flat_words = [w for w in (_flat(x) for x in text.split()) if w]
        got = _share([piece for _k, piece in own], "".join(flat_words))
        if got is None:
            return set_line_roman(doc, idx, voice, text)
        got = _snap_to_words(got, flat_words, [piece for _k, piece in own])
        plan = {k: piece for (k, _p), piece in zip(own, got) if guide[k]}
    was = [(s.roman, g.roman) for s in g.syls]
    for k, piece in plan.items():
        g.syls[k].roman = piece
    # The line's own reading too, in Genius' spacing -- that is what the
    # per-line view and the file's line transliteration show.
    g.roman = text
    return "reading put right" if [(s.roman, g.roman) for s in g.syls] != was \
        else None


def _flat(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace() and ch not in _NOT_READ)


def _snap_to_words(pieces: list[str], words: list[str], guide: list[str]) -> list[str]:
    """A seam one letter off a word break of the reading moves onto it ("A|hNan" -> "Ah|Nan"),
    unless both its sides read as the guide does (なってい|た stays "nattei|ta")."""
    breaks, at = set(), 0
    for w in words[:-1]:
        at += len(w)
        breaks.add(at)
    whole, seams, at = "".join(pieces), [], 0
    for p in pieces[:-1]:
        at += len(p)
        seams.append(at)
    for n, sm in enumerate(seams):
        if sm in breaks or all(pieces[j].casefold() == guide[j].casefold() for j in (n, n + 1)):
            continue
        lo = seams[n - 1] if n else 0
        hi = seams[n + 1] if n + 1 < len(seams) else len(whole)
        near = [b for b in (sm - 1, sm + 1) if b in breaks and lo < b < hi]
        if len(near) == 1:
            seams[n] = near[0]
    cuts = [0] + seams + [len(whole)]
    return [whole[a:b] for a, b in zip(cuts, cuts[1:])]


def _share(old_pieces: list[str], new: str) -> list[str] | None:
    """`new` cut into as many pieces as `old_pieces`, where they were cut."""
    import difflib
    if len(new) < len(old_pieces):
        return None
    if len(old_pieces) == 1:
        return [new]
    old = "".join(old_pieces)
    ops_ = difflib.SequenceMatcher(None, old.casefold(), new.casefold(),
                                   autojunk=False).get_opcodes()

    def where(p: int) -> int:
        # A seam where the new reading ADDS letters takes them with the
        # syllable before it: "to|kyo" -> "tou|kyou", a long vowel, and the
        # first of a doubled consonant or an ん. Any other consonant starts
        # the next one: "ki|zui" -> "ki|dzui", not "kid|zui".
        for tag, i1, i2, j1, j2 in ops_:
            if tag == "insert" and i1 == p:
                add, nxt = new[j1:j2].casefold(), new[j2:j2 + 1].casefold()
                if (any(c in "aeiou" for c in add) or add[-1:] == nxt
                        or (add == "n" and nxt not in "aeiouy")):
                    return j2
                return j1
        for tag, i1, i2, j1, j2 in ops_:
            if i1 <= p < i2 or (p == i2 and tag != "insert"):
                if tag == "equal":
                    return j1 + (p - i1)
                if i2 == i1:
                    return j1
                return j1 + round((p - i1) * (j2 - j1) / (i2 - i1))
        return len(new)

    def doubled(sm: int) -> int:
        # Never inside a doubled consonant: hak|ka, as がっ|こう.
        low = new.casefold()
        if (0 < sm < len(low) - 1 and low[sm] not in "aeiou"
                and (low[sm + 1] == low[sm] or low[sm:sm + 3] == "tch")):
            return sm + 1
        return sm

    seams, at = [], 0
    for piece in old_pieces[:-1]:
        at += len(piece)
        seams.append(doubled(where(at)))
    fixed, lo = [], 1
    for n, sm in enumerate(seams):
        hi = len(new) - (len(seams) - n)
        sm = max(lo, min(sm, hi))
        fixed.append(sm)
        lo = sm + 1
    cuts = [0] + fixed + [len(new)]
    pieces = [new[a:b] for a, b in zip(cuts, cuts[1:])]
    return pieces if all(pieces) else None


# ------------------------------------------------- ad-libs written in a line
def inline_adlibs(doc: Doc, idx: int) -> list[tuple[int, int]]:
    """Bracketed runs sitting inside a line's lead, as (first word, last word).

    "You (Okay) must (Uh) find (Your mind)" -- how a page writes ad-libs that
    are sung between the words. Only a run that closes is one, and a line that
    is nothing BUT brackets is left alone: there is no lead to take them out of.
    """
    g = doc.group(idx, 0) if 0 <= idx < len(doc.lines) else None
    if g is None:
        return []
    words = [g.word_text(run) for run in g.words()]
    runs, i = [], 0
    while i < len(words):
        if words[i][:1] not in ("(", "（"):
            i += 1
            continue
        depth, j = 0, i
        while j < len(words):
            depth += sum(words[j].count(c) for c in "(（")
            depth -= sum(words[j].count(c) for c in ")）")
            if depth <= 0:
                break
            j += 1
        if j < len(words) and depth == 0:
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    if sum(b - a + 1 for a, b in runs) >= len(words):
        return []
    return runs


def gather_adlibs(doc: Doc, idx: int, how: str = "gather") -> str | None:
    """Take a line's bracketed runs out of its lead as ad-libs: `how` is
    "gather" (one, comma-joined) or "separate"."""
    runs = inline_adlibs(doc, idx)
    if not runs or how not in ("gather", "separate"):
        return None
    ln = doc.lines[idx]
    g = ln.lead
    words = g.words()
    pieces, drop = [], set()
    for a, b in runs:
        syls = [g.syls[k] for w in range(a, b + 1) for k in words[w]]
        drop.update(id(s) for s in syls)
        syls[0].text = syls[0].text.lstrip("(（").lstrip()
        # A comma after the bracket belongs to the word before it: "You
        # (Okay), must" is "You, must" with an ad-lib, not an ad-lib that
        # ends in a comma. Anything else after the bracket stays with it.
        tail = syls[-1].text
        body = tail.rstrip(",;")
        commas = tail[len(body):]
        body = body.rstrip(")）").rstrip()
        syls[-1].text = body
        if commas and a > 0:
            prev = g.syls[words[a - 1][-1]]
            if id(prev) not in drop and not prev.text.endswith(","):
                prev.text += ","
        syls = [s for s in syls if s.text.strip()]
        if syls:
            syls[-1].part = False
            pieces.append(syls)
    g.syls = [s for s in g.syls if id(s) not in drop]
    _tidy(g)
    if not pieces:
        return None
    if how == "separate":
        at = next((n for n, b in enumerate(ln.bg) if not b.lead_in),
                  len(ln.bg))
        for syls in pieces:
            ln.bg.insert(at, Group(syls))
            at += 1
    else:
        old = next((b for b in ln.bg if not b.lead_in), None)
        if old is not None:
            ln.bg.remove(old)
            pieces.append(list(old.syls))
        for n, syls in enumerate(pieces):
            if n and syls[0].text not in ("I",) and not syls[0].text.startswith(
                    ("I'", "I’")):
                syls[0].text = syls[0].text[:1].lower() + syls[0].text[1:]
            if n < len(pieces) - 1 and syls[-1].text[-1:] not in ",;.!?…—-":
                syls[-1].text += ","
        ln.bg.append(Group([s for syls in pieces for s in syls]))
    if ln.start is not None:
        lo, hi = ln.span()
        if lo is not None:
            ln.start, ln.end = lo, hi
    return "moved the bracketed words into ad-libs"


def rewrite_line(doc: Doc, idx: int, text: str) -> str | None:
    """Replace a line with what was typed, keeping the times of each word still
    there (case and punctuation changes included)."""
    from .model import from_text
    if not 0 <= idx < len(doc.lines):
        return None
    new = from_text(text)
    if len(new.lines) != 1:
        return None
    old = doc.lines[idx]
    line = new.lines[0]
    take_times(time_pool([old]), line)
    if hyphens_on():
        cut_hyphens([line])
    line.agent = old.agent
    if line.start is None:
        line.start, line.end = old.start, old.end
    doc.lines[idx] = line
    return "rewrote the line"


def _norm_word(t: str) -> str:
    return "".join(c for c in t.lower() if c.isalnum())


def time_pool(lines: list) -> list:
    """Every word of these lines with its timed syllables, for take_times:
    [spelling, syllables, used, which of the lines]."""
    import copy
    pool = []
    for n, ln in enumerate(lines):
        for g in ln.groups():
            for run in g.words():
                pool.append([_norm_word(g.word_text(run)),
                             [copy.copy(g.syls[k]) for k in run], False, n])
    return pool


def take_times(pool: list, line, prefer: int | None = None) -> None:
    """Give each word of `line` the times of the same word in the pool, in
    order -- from line `prefer` of the pool first, where it says, so a line
    rewritten among others takes its own words' times before a neighbour's.
    A word whose spelling only changed in case or punctuation keeps them too;
    one that is really new stays untimed."""
    for g in line.groups():
        out = []
        for s in g.syls:
            want = _norm_word(s.text)
            free = [p for p in pool if not p[2] and p[0] == want]
            hit = next((p for p in free if p[3] == prefer), None) or (
                free[0] if free else None)
            if hit is None or not want:
                out.append(s)
                continue
            hit[2] = True
            olds = hit[1]
            if sum(len(o.text) for o in olds) == len(s.text):
                at = 0
                for o in olds:
                    o.text, at = s.text[at:at + len(o.text)], at + len(o.text)
                    o.part = True
                olds[-1].part = False
                out.extend(olds)
            else:
                s.start, s.end, s.roman = olds[0].start, (
                    olds[-1].end if olds[-1].end is not None else
                    olds[-1].start), " ".join(o.roman for o in olds).strip()
                out.append(s)
        g.syls = out
    line.start, line.end = line.span()
