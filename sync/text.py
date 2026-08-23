"""The alphabet the model reads, and how a lyric is spelled into it.

Twenty-nine symbols: a blank for CTC, a space, the twenty-six letters, and the
apostrophe. Nothing else, because everything else is either punctuation the
singer does not pronounce or a script this model was never shown.

A line arrives here as somebody typed it -- capitals, commas, brackets around
the ad-libs, sometimes kana -- and has to leave as a string the model could
have emitted. The two directions matter equally: `flatten` prepares a training
label, and `spell` prepares the token sequence a whole song is force-aligned
against, keeping a map back to the words it came from so the timings can be
handed back to the words the viewer will actually see.
"""
from __future__ import annotations

import re
import unicodedata

BLANK = 0
SYMBOLS = "|abcdefghijklmnopqrstuvwxyz'"   # '|' is the space
VOCAB = ["<b>"] + list(SYMBOLS)
INDEX = {c: i + 1 for i, c in enumerate(SYMBOLS)}
SPACE = INDEX["|"]
SIZE = len(VOCAB)

_DROP = re.compile(r"[^a-z']")
_ASCII = re.compile(r"^[a-z' ]+$")


def flatten(word: str) -> str:
    """One word as the model spells it, or '' if it cannot spell it at all.

    Accents are stripped rather than dropped, so `café` is `cafe` and not
    `caf`, and the several kinds of typographic apostrophe all become the one
    the alphabet has. A word that survives as nothing -- a bare `(`, an em
    dash, an instrumental marker -- comes back empty and is meant to be
    skipped by the caller, not taught as silence.

    Anything written in another script is handed to the player's romaniser if
    that is importable, because a Japanese song is otherwise not a hard example
    but an empty one. The import is deliberately lazy and deliberately
    optional: this module is the one piece of the package that everything else
    imports, and it must stay cheap and standalone.
    """
    s = unicodedata.normalize("NFKD", word)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("’", "'").replace("‘", "'")
    got = _DROP.sub("", s)
    if got or not word.strip():
        return got
    return _DROP.sub("", _romanised(word).lower().replace("’", "'"))


def _romanised(word: str) -> str:
    """`word` in latin letters, via the player's reader, or '' if it has none."""
    try:
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "aligner"))
        import local_align as LA
        return LA._romanise(word)
    except Exception:
        return ""


def line(text: str) -> str:
    """A whole line as a training label: words the model can spell, spaced.

    Returns '' when too little survives to be worth a training step. Four
    characters is the floor -- below that the label is more likely to be a
    stage direction than a sung line, and a wrong label costs more than a
    missing one.
    """
    got = " ".join(w for w in (flatten(x) for x in text.split()) if w)
    return got if len(got) >= 4 else ""


def encode(text: str) -> list[int]:
    """A spelled string as token ids. Spaces included, so words stay apart."""
    return [INDEX[c] for c in text.replace(" ", "|") if c in INDEX]


def decode(ids) -> str:
    """Token ids back to text, collapsing CTC repeats and dropping blanks."""
    out, last = [], -1
    for i in ids:
        i = int(i)
        if i != last and i != BLANK:
            out.append(SYMBOLS[i - 1])
        last = i
    return "".join(out).replace("|", " ").strip()


def spell(words: list[str]) -> tuple[list[int], list[tuple[int, int, int]]]:
    """Whole-song tokens, and where each word sits in them.

    Returns (tokens, spans) where spans is one (word index, first token, last
    token) per word that could be spelled. Words that could not are simply
    absent from the spans -- the caller keeps its own list and looks them up by
    index, so a word the alphabet cannot hold does not shift everything after
    it by one.

    Words are joined by a single space token. The space is a real symbol the
    model emits between words, not a separator invented here, which is what
    makes a word's first token a word ONSET rather than the tail of whatever
    came before it.
    """
    tokens: list[int] = []
    spans: list[tuple[int, int, int]] = []
    for i, word in enumerate(words):
        flat = flatten(word)
        if not flat:
            continue
        if tokens:
            tokens.append(SPACE)
        first = len(tokens)
        tokens.extend(encode(flat))
        spans.append((i, first, len(tokens) - 1))
    return tokens, spans


VOWELS = "aeiouy"
# Consonant runs that belong to one syllable: digraphs that spell a single
# sound, and the blends English will start a syllable with but not split.
KEPT = frozenset((
    "th ch sh ph wh gh ck qu ng "
    "bl br cl cr dr fl fr gl gr pl pr sc sk sl sm sn sp st sw tr tw "
    "str spr scr thr shr sch"
).split())


def syllables(word: str) -> list[str]:
    """A spelled word cut into syllables, by a rule rather than a dictionary.

    Not linguistics: the point is to give a long word two or three places where
    the karaoke sweep can turn, and the alignment supplies the times for those
    places from the characters themselves. Being one letter out on a boundary
    moves a highlight by a few tens of milliseconds, which is why a rule is
    enough and a pronunciation dictionary is not worth its weight.

    The rule: cut before the consonant that begins each vowel group after the
    first, keep at most one consonant with the following vowel, and never make
    a piece of one letter that has no vowel in it.
    """
    if len(word) <= 3:
        return [word]
    # Where the vowel groups are. Each one is a syllable's nucleus, and the
    # consonants between two of them have to be shared out.
    nuclei = [(m.start(), m.end()) for m in re.finditer(f"[{VOWELS}]+", word)]
    if len(nuclei) < 2:
        return [word]

    cuts = []
    for (_, end), (start, _) in zip(nuclei, nuclei[1:]):
        run = word[end:start]
        if not run:                       # two vowel groups meeting: cut between
            cut = end
        elif len(run) == 1:               # V-CV, the consonant leads the next
            cut = end
        elif run in KEPT or run[:2] in KEPT and len(run) == 2:
            cut = end                     # 'th', 'ck', 'str' -- not to be split
        else:
            cut = start - 1               # VC-CV, one each side
            while cut > end and word[cut - 1:cut + 1] in KEPT:
                cut -= 1
        cuts.append(max(nuclei[0][1], cut))

    out, last = [], 0
    for cut in cuts:
        if cut > last:
            out.append(word[last:cut])
            last = cut
    out.append(word[last:])
    out = [p for p in out if p]

    # Two tidy-ups, both about pieces that are not syllables. A piece with no
    # vowel in it cannot be sung on its own, and a final lone `e` is the silent
    # one at the end of `strange` rather than a beat of its own.
    fixed: list[str] = []
    for p in out:
        if fixed and not any(c in VOWELS for c in p):
            fixed[-1] += p
        else:
            fixed.append(p)
    if len(fixed) > 1 and re.fullmatch(r"[^aeiouy]*e", fixed[-1]):
        tail = fixed.pop()
        fixed[-1] += tail
    return fixed or [word]
