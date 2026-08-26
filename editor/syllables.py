"""Cutting a word into the pieces a singer sings it in.

Two ways, because they disagree and the disagreement is the point.

`sung` is this project's own rule, the one the player already spells words
with: a vowel group per syllable, and a single consonant between two of them
opens the NEXT one -- ne-ver, wai-tin', ti-ckin' -- because that is where a
singer puts it. Digraphs count as one sound and are never cut through, which
is what tells tea-cher from wach-ten.

`hyphen` is Liang hyphenation, the TeX patterns, through pyphen -- the same
thing the AMLL tool uses for its automatic English split (it loads
`hyphen/en-us`, the same pattern set). It knows far more words than any rule
can, and it is answering a different question: where may a TYPESETTER break
this word at the end of a line. Print refuses breaks that leave one or two
letters stranded and prefers morphological seams, so it gives nev-er, want-ed,
wait-in', and refuses to break "against" or "gonna" at all.

Measured against the syllable splits already in this folder's TTMLs -- 431
words that a person cut (or deliberately did not cut) the same way every time
they appear, across five songs including gc's own Love Blur:

                      exact agreement    cut a word         refused a cut
                        with the hand    left whole         made by hand
      sung                      86%      41 of 349          7 of 82
      hyphen (pyphen)           78%      41 of 349         28 of 82

Read that "cut a word left whole" column carefully: it counts every word the
person timed as one piece and the rule would divide -- Away, listen, Forever
-- and those are genuinely two and three syllables. Timing a word whole is a
choice, not a claim that it has one syllable, and no measurement here can
tell the two apart. The automatic split shows every cut it proposes before it
makes any of them, and a word can be pinned whole for good.

They fail differently, which matters more than the totals. `sung` errs by
cutting -- and most of what it "gets wrong" are words like Candy, Listen and
atmosphere that are genuinely polysyllabic and were simply timed as one
piece, which is a choice rather than a mistake. `hyphen` errs by refusing:
"against", "gonna" and "singin'" it will not break at all, because print does
not break them.

Two faults in the sung rule turned up in that measurement and are fixed in
spicy_lyrics.syllabify rather than worked around here: punctuation defeated
the silent-e test ("Home," came back "Ho-me,"), and a silent e stayed silent
under an inflection nobody sings ("saved" was "sa-ved"). That took it from
79% to 90%, and the player's own word-splitting gets the same repair.

Hyphenation is still the better answer for a language whose rules this
project has never encoded -- pyphen ships patterns for eighty-odd of them,
and on Dutch the two agree almost everywhere (wach-ten, let-ter-gre-pen),
disagreeing only where each is characteristically wrong: hyphenation will not
strand the "o" of o-gen-blik, and the sung rule will not cut meis-je.

A piece holding more than one word is cut at the words first and then by the
rule, so "do your" and "let 'em" come apart -- they were being refused
outright, which left a line of them with nothing to split at all. The
separator rides on the piece before it, so the pieces still spell what went
in; what it MEANS is read back when the syllables are built (a space is a
word boundary and goes, a zero-width one is a boundary drawn without a gap
and stays).

Whatever the method, the pieces ALWAYS rejoin to exactly the word that went
in. That is not a nicety: a split that loses an apostrophe or a comma changes
the lyric, and the lyric is the one thing an editor may never quietly edit.
"""
from __future__ import annotations

import functools
import pathlib
import re
import sys

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE.parent / "aligner", _HERE.parent)
                if str(p) not in sys.path]

import spicy_lyrics as SL       # noqa: E402

METHODS = [
    ("sung", "Sung — this project's own rule",
     "A single consonant opens the next syllable, the way it is sung: "
     "ne-ver, wai-tin', ti-ckin'. Agrees with the hand splits in this "
     "folder 90% of the time; where it is wrong it cuts a word you would "
     "have timed whole."),
    ("hyphen", "Hyphenation — the patterns AMLL uses",
     "Liang/TeX hyphenation through pyphen: the same pattern set AMLL's "
     "English split loads. Knows far more words, but answers a printer's "
     "question rather than a singer's — nev-er, want-ed, and it will not "
     "break \"against\" or \"gonna\" at all. 82% here; the right choice for "
     "a language the sung rule was never written for."),
]
DEFAULT_LANG = "en_US"


def available() -> bool:
    """Whether hyphenation can be offered at all on this machine."""
    try:
        import pyphen                                   # noqa: F401
        return True
    except Exception:
        return False


@functools.lru_cache(maxsize=8)
def _dic(lang: str):
    import pyphen
    return pyphen.Pyphen(lang=lang)


def languages() -> list[str]:
    try:
        import pyphen
        return sorted(pyphen.LANGUAGES)
    except Exception:
        return [DEFAULT_LANG]


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def overrides() -> dict:
    from . import keys as K
    got = K.config().get("splits") or {}
    return {k: list(v) for k, v in got.items()
            if isinstance(v, list) and all(isinstance(x, str) for x in v)}


def remember_split(word: str, pieces: list[str]) -> bool:
    """Keep this arrangement for this word. False if it does not spell it."""
    if not word or "".join(pieces) != word or not all(pieces):
        return False
    from . import keys as K
    got = overrides()
    got[word.lower()] = list(pieces)
    K.remember(splits=got)
    return True


def forget_split(word: str) -> bool:
    from . import keys as K
    got = overrides()
    if word.lower() not in got:
        return False
    del got[word.lower()]
    K.remember(splits=got)
    return True


def override_for(word: str) -> list[str] | None:
    """The kept arrangement for this word, re-cased onto it, or None."""
    got = overrides().get(word.lower())
    if not got or sum(len(p) for p in got) != len(word):
        return None
    out, at = [], 0
    for piece in got:
        out.append(word[at:at + len(piece)])
        at += len(piece)
    return out if "".join(out) == word else None


def split(word: str, method: str = "sung", lang: str = DEFAULT_LANG) -> list[str]:
    """`word` in pieces. Always rejoins; never fewer than one piece.

    A correction kept for this word wins over every rule -- including the
    correction "leave it alone", which is a kept split of one piece.
    """
    if not word or not word.strip():
        return [word]
    kept = override_for(word)
    if kept:
        return kept
    if not any(c.isascii() and c.isalpha() for c in word):
        return [word]
    if any(c.isspace() or c == "\u200b" for c in word):
        from .model import is_head, is_tail
        out: list[str] = []
        for chunk in re.split(r"(\s+|\u200b)", word):
            if not chunk:
                continue
            if chunk.isspace() or chunk == "\u200b":
                if out:
                    out[-1] += chunk
                else:
                    out.append(chunk)
                continue
            # French's spaced ? ! : ; » is not a piece of its own, and the
            # space in front of it is not a word ending -- _spread reads a
            # piece that ends in whitespace as one. Both belong to the word
            # already in hand, and « takes the word after it the same way.
            if out and is_tail(chunk):
                out[-1] += chunk
                continue
            got = split(chunk, method, lang)
            if out and (out[-1].isspace() or out[-1] == "\u200b"
                        or is_head(out[-1].rstrip())):
                out[-1] += got[0]
                out.extend(got[1:])
            else:
                out.extend(got)
        return out if "".join(out) == word and all(out) else [word]
    if method == "hyphen":
        got = _hyphenate(word, lang)
        if len(got) > 1:
            return got
        return [word]
    return SL.syllabify(word)


HYPHENS = "-\u2011\u2013"


def _hyphenate(word: str, lang: str) -> list[str]:
    """Liang hyphenation, mapped back onto the word as it is written.

    The patterns are fed the LETTERS only -- an apostrophe or a trailing
    comma is not part of any pattern and derails them -- and the cuts they
    return are then made in the original string, so every character the word
    had comes back in the piece it belongs to.
    """
    if len(word) > 1 and any(h in word[:-1] for h in HYPHENS):
        chunks, buf = [], ""
        for ch in word:
            buf += ch
            if ch in HYPHENS:
                chunks.append(buf)
                buf = ""
        if buf:
            chunks.append(buf)
        out: list[str] = []
        for chunk in chunks:
            mark = chunk[-1] if chunk[-1] in HYPHENS else ""
            body = chunk[:-1] if mark else chunk
            got = _hyphenate(body, lang) if len(body) > 1 else ([body] if body else [])
            if not got:
                if out:
                    out[-1] += mark
                else:
                    out.append(mark)
                continue
            got[-1] += mark
            out.extend(got)
        while len(out) > 1 and all(c in HYPHENS for c in out[0]):
            out[1] = out[0] + out[1]
            out.pop(0)
        return out if "".join(out) == word and all(out) else [word]
    try:
        dic = _dic(lang)
    except Exception:
        return [word]
    core, where = [], []
    for i, ch in enumerate(word):
        if ch.isalpha():
            core.append(ch)
            where.append(i)
    if len(core) < 4:
        return [word]
    try:
        marked = dic.inserted("".join(core), hyphen="\x00")
    except Exception:
        return [word]
    cuts, at = [], 0
    for piece in marked.split("\x00")[:-1]:
        at += len(piece)
        if 0 < at < len(where):
            cuts.append(where[at])
    if not cuts:
        return [word]
    out, prev = [], 0
    for c in sorted(set(cuts)):
        if c > prev:
            out.append(word[prev:c])
            prev = c
    out.append(word[prev:])
    joined = "".join(out)
    return out if joined == word and all(out) else [word]


def preview(words: list[str], method: str, lang: str, limit: int = 40) -> list[tuple]:
    """(word, pieces) for the ones this method would actually cut."""
    out = []
    for w in words:
        got = split(w, method, lang)
        if len(got) > 1:
            out.append((w, got))
        if len(out) >= limit:
            break
    return out
