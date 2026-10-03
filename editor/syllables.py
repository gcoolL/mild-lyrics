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

Punctuation around a word is not part of it in either rule, nor in the store
of kept corrections: it is peeled off before the spelling is read and put
back on the pieces it came off, so "fallin'", "fallin'," and "fallin'!" are
one word asked about once and answered once. Where that peel is exactly is
spicy_lyrics.peel, which the player's own splitting uses for the same reason.
It was worth doing: the store had grown a second entry for "alkmaar," beside
"alkmaar" and a third for "boyfriend?", each of them the same decision typed
again because the first one could not be found.

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
sys.path[:0] = [str(p) for p in (_HERE.parent / "mild-lyrics", _HERE.parent)
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

# How a script other than the Latin alphabet is cut -- Japanese, Chinese,
# Korean, Cyrillic, Greek: the scripts a reading is written for. The two
# rules above are about where a LATIN word comes apart and have nothing to
# say about these, so they get a choice of their own.
UNITS = [
    ("syllable", "By syllable",
     "A piece per syllable as it would be sung in English: Japanese kana "
     "keep ん, っ, ー and a long vowel or diphthong on the syllable they "
     "close (きょう, がっ|こう, せん|せい, 会い|たい); a kanji, a hanzi, a "
     "hangul block each; Cyrillic and Greek by their vowels."),
    ("mora", "By mora",
     "As above, but Japanese a kana at a time (with only the small kana and "
     "ー on the one before): きょ|う, が|っ|こ|う. The beat Japanese is sung "
     "on, and how the hand-timed amll-ttml-db files are mostly cut."),
    ("word", "By word",
     "A piece per word. Japanese is found by pykakasi, with a word's endings "
     "and the particles after it kept on it (君の, 聞こえる); Chinese by "
     "jieba where it is installed, and by the phrases pypinyin knows where "
     "it is not; Korean, Cyrillic and Greek at their spaces."),
]


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
def bare_pieces(word: str, pieces: list[str]) -> list[str] | None:
    """`pieces` re-cut as a split of `word` without the punctuation around it.

    A correction is a decision about the WORD, and a comma is not part of the
    word -- so it is stored, looked up and applied with the punctuation off.
    A cut that fell inside the punctuation is dropped rather than kept: there
    is nothing there to cut.
    """
    head, core, _tail = SL.peel(word)
    joined = "".join(pieces)
    if not core or len(joined) != len(word):
        return None
    lo, hi = len(head), len(head) + len(core)
    cuts, at = [], 0
    for p in pieces[:-1]:
        at += len(p)
        if lo < at < hi:
            cuts.append(at)
    out, prev = [], lo
    for c in sorted(set(cuts)):
        out.append(joined[prev:c])
        prev = c
    out.append(joined[prev:hi])
    return out if all(out) else None


def key(word: str) -> str:
    """What a correction is filed under: the word, without punctuation."""
    return SL.peel(word)[1].lower()


# Corrections that hold for this session and are never written down: the
# automatic split's "Remember corrections" turned off. A song somebody does
# not want cut all the way through -- a word timed whole on purpose, a name
# sung its own way this once -- still has to be told to the rule, and telling
# it used to mean teaching it for good. {bare word: [arrangement, ...]}, the
# usual one first, exactly the shape the store has.
_HELD: dict[str, list[list[str]]] = {}


def hold(word: str, ways: list[list[str]]) -> bool:
    """Answer for `word` with these arrangements until let go -- unsaved.

    False if any of them does not spell the word."""
    keep = []
    for pieces in ways:
        if "".join(pieces) != word or not all(pieces):
            return False
        bits = bare_pieces(word, list(pieces))
        if not bits:
            return False
        if bits not in keep:
            keep.append(bits)
    if not keep:
        return False
    _HELD[key(word)] = keep
    return True


def let_go(word: str) -> bool:
    return _HELD.pop(key(word), None) is not None


def let_go_all() -> None:
    """Forget every unsaved correction -- a new song is a new set of choices."""
    _HELD.clear()


def held() -> dict:
    return {k: [list(w) for w in v] for k, v in _HELD.items()}


def overrides() -> dict:
    """Every correction in force, filed by the bare word: kept, then held.

    A held one (see `hold`) wins over a kept one for the same word, and is
    never written back -- `remember_split` and `forget_split` read `_kept`.
    """
    out = _kept()
    for k, ways in _HELD.items():
        out[k] = list(ways[0])
    return out


_MEMO: dict = {"kept": (None, {}), "also": (None, {})}


def _kept() -> dict:
    """Every kept correction, filed by the bare word.

    Corrections kept before this was filed by the bare word are folded in on
    the way past -- "alkmaar," carries the same decision as "alkmaar" and
    always did -- and the fold is written back the next time anything is
    remembered or forgotten, so the store settles into one entry per word
    instead of one per word per closing mark.

    Rebuilt only when the store changed, which `keys.config` says by handing
    back the same object -- it was rebuilt for every word of a document, 1.5ms
    at 500 kept and 5.5 at 3000. The dict is the caller's to change; the lists
    in it are shared, so they are not.
    """
    from . import keys as K
    got = K.config().get("splits") or {}
    src, held = _MEMO["kept"]
    if got is src:
        return dict(held)
    out: dict[str, list[str]] = {}
    for word, pieces in got.items():
        if not isinstance(pieces, list) or not all(isinstance(x, str) for x in pieces):
            continue
        bits = bare_pieces(word, list(pieces))
        if bits:
            out[key(word)] = bits
    _MEMO["kept"] = (got, out)
    return dict(out)


def also_right() -> dict:
    """The other arrangements kept as right for a word, filed by the bare word.

    A word can be sung more than one way -- "battlin'" is bat|tlin' or
    bat|t|lin' depending on the singer -- and a file cut either way is cut
    right. The first arrangement, in `overrides`, is still the one the rule
    hands out; these are only ones a review should not raise. Kept apart from
    "splits" so everything that reads that store keeps reading one
    arrangement per word.
    """
    out = _kept_also()
    for k, ways in _HELD.items():
        if len(ways) > 1:
            out[k] = [list(w) for w in ways[1:]]
        else:
            out.pop(k, None)
    return out


def _kept_also() -> dict:
    """The other arrangements in the store itself -- see also_right. Kept the
    way `_kept` keeps its answer, and shared the same way."""
    from . import keys as K
    got = K.config().get("also_splits") or {}
    src, held = _MEMO["also"]
    if got is src:
        return dict(held)
    out: dict[str, list[list[str]]] = {}
    for word, alts in got.items():
        if not isinstance(alts, list):
            continue
        keep = []
        for pieces in alts:
            if isinstance(pieces, list) and all(isinstance(x, str) for x in pieces):
                bits = bare_pieces(word, list(pieces))
                if bits and bits not in keep:
                    keep.append(bits)
        if keep:
            out[key(word)] = keep
    _MEMO["also"] = (got, out)
    return dict(out)


def accepted(word: str) -> list[list[str]]:
    """Every arrangement kept as right for this word, the rule's own first."""
    k = key(word)
    first = overrides().get(k)
    out = [first] if first else []
    for bits in also_right().get(k, []):
        if bits not in out:
            out.append(bits)
    return out


def ways_for(word: str) -> list[list[str]]:
    """Every kept way for this word, spelled onto it: its case, and its
    punctuation back on the end pieces. The usual one first."""
    head, core, tail = SL.peel(word)
    out = []
    for way in accepted(word):
        if sum(map(len, way)) != len(core):
            continue
        cut, at = [], 0
        for b in way:
            cut.append(core[at:at + len(b)])
            at += len(b)
        cut[0] = head + cut[0]
        cut[-1] += tail
        out.append(cut)
    return out


SEAMS = "|·"
WAYS = "/"


def parse_ways(word: str, text: str) -> tuple[list[list[str]], str]:
    """What somebody typed about how `word` is cut, as arrangements of it.

    ([pieces, ...], "") -- or ([], the part that would not do). Pieces are
    marked off with | (or ·), and more than one right way with /, the usual
    one first. A - marks a seam too, in a word that has none of its own.

    Typed the way a person types, not the way the word is stored: the case
    need not match ("Lone|lier" for "lonelier"), the punctuation the word is
    wearing in this line may be left off ("lone|lier" for "lonelier,"), and
    the spaces round a / are nobody's business. Every one of those used to be
    turned away with "does not spell", which is how "lone|lier / lone|li|er"
    could not be kept for a "Lonelier" -- the pieces come back spelled as the
    word is, so nothing about the lyric can change.
    """
    head, core, tail = SL.peel(word)
    out: list[list[str]] = []
    seams = SEAMS if "-" in word else SEAMS + "-"
    for part in str(text or "").split(WAYS):
        part = part.strip()
        if not part:
            continue
        bits = [b for b in re.split("[" + re.escape(seams) + "]", part)]
        if "".join(bits) == word and all(bits):
            got = bits
        else:
            flat = "".join(bits)
            if flat.lower() == word.lower():
                base, lo = word, 0
            elif core and flat.lower() == core.lower():
                base, lo = word, len(head)
            else:
                return [], part
            if not all(bits):
                return [], part
            got, at = [], lo
            for b in bits:
                got.append(base[at:at + len(b)])
                at += len(b)
            got[0] = base[:lo] + got[0]
            got[-1] += base[at:]
        if got not in out:
            out.append(got)
    return out, ""


def is_accepted(word: str, pieces: list[str]) -> bool:
    """Whether `pieces` cut `word` one of the ways kept as right for it."""
    bits = bare_pieces(word, list(pieces)) if "".join(pieces) == word else None
    low = lambda way: [b.lower() for b in way]              # noqa: E731
    return bool(bits) and low(bits) in [low(w) for w in accepted(word)]


def add_also(word: str, pieces: list[str]) -> bool:
    """Keep `pieces` as one more right way to cut `word`, leaving the usual
    one the rule hands out as it is. With nothing kept yet, it BECOMES the
    usual one. False if it does not spell the word."""
    k = key(word)
    ways = ([_kept()[k]] if k in _kept() else []) + [
        w for w in _kept_also().get(k, [])]
    if not ways:
        return remember_split(word, pieces)
    bits = bare_pieces(word, list(pieces)) if "".join(pieces) == word else None
    if not bits:
        return False
    low = lambda way: [b.lower() for b in way]              # noqa: E731
    if low(bits) in [low(w) for w in ways]:
        return True
    core = SL.peel(word)[1]

    def onto(way):
        out, at = [], 0
        for b in way:
            out.append(core[at:at + len(b)])
            at += len(b)
        return out

    if any(sum(map(len, w)) != len(core) for w in ways):
        return False
    return remember_split(core, onto(ways[0]),
                          also=[onto(w) for w in ways[1:]] + [bits])


def remember_split(word: str, pieces: list[str], also=None) -> bool:
    """Keep this arrangement for this word. False if it does not spell it.

    `also` is the other arrangements that are right too (see also_right);
    None leaves whatever was kept of those alone, a list replaces them.
    """
    if not word or "".join(pieces) != word or not all(pieces):
        return False
    bits = bare_pieces(word, list(pieces))
    if not bits:
        return False
    from . import keys as K
    got = _kept()
    got[key(word)] = bits
    if also is None:
        K.remember(splits=got)
        return True
    alts = _kept_also()
    mine = []
    for other in also:
        if "".join(other) != word or not all(other):
            return False
        ob = bare_pieces(word, list(other))
        if not ob:
            return False
        if ob != bits and ob not in mine:
            mine.append(ob)
    if mine:
        alts[key(word)] = mine
    else:
        alts.pop(key(word), None)
    K.remember(splits=got, also_splits=alts)
    return True


def forget_split(word: str) -> bool:
    from . import keys as K
    got, alts = _kept(), _kept_also()
    if key(word) not in got and key(word) not in alts:
        return False
    got.pop(key(word), None)
    alts.pop(key(word), None)
    K.remember(splits=got, also_splits=alts)
    return True


def override_for(word: str) -> list[str] | None:
    """The kept arrangement for this word, re-cased onto it, or None.

    Kept for the word itself, so it answers for "fallin'", "fallin'," and
    "fallin'!" alike: the punctuation is set aside, the arrangement is read
    onto what is left, and the marks go back on the pieces they came off.
    """
    head, core, tail = SL.peel(word)
    got = overrides().get(core.lower()) if core else None
    if not got or sum(len(p) for p in got) != len(core):
        return None
    out, at = [], 0
    for piece in got:
        out.append(core[at:at + len(piece)])
        at += len(piece)
    out[0] = head + out[0]
    out[-1] = out[-1] + tail
    return out if "".join(out) == word and all(out) else None


def split(word: str, method: str = "sung", lang: str = DEFAULT_LANG,
          unit: str = "syllable", japanese: bool = False) -> list[str]:
    """`word` in pieces. Always rejoins; never fewer than one piece.

    A correction kept for this word wins over every rule -- including the
    correction "leave it alone", which is a kept split of one piece.

    `unit` is for the scripts that are not the Latin alphabet (see UNITS):
    "syllable", "mora" or "word". A Latin word is cut by `method` either way.
    `japanese` says a run of kanji alone is Japanese rather than Chinese --
    the document's language, which the characters cannot tell apart.
    """
    if not word or not word.strip():
        return [word]
    kept = override_for(word)
    if kept:
        return kept
    kind = script(word, japanese=japanese or lang.lower().startswith("ja"))
    if unit == "word" and kind:
        return _words(word, kind, method, lang)
    if kind in ("ja", "zh", "ko"):
        got = _cjk(word, method, lang)
        return got if unit == "mora" else _ja_syllables(word, got)
    if kind in ALPHABETS:
        return _vowel_split(word, ALPHABETS[kind])
    if not any(c.isalpha() for c in word):
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
            if out and is_tail(chunk):
                out[-1] += chunk
                continue
            if (out and out[-1].endswith("\u200b")
                    and not any(c.isalnum() for c in chunk)):
                out[-1] += chunk
                continue
            got = split(chunk, method, lang, unit, japanese)
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


# --------------------------------------------------------------------------
# Scripts that are not written in words of the Latin alphabet.
#
# Japanese and Chinese are not spaced into words at all, so a line of either
# comes in as ONE word, and the rule above -- which reads Latin vowels --
# handed it back whole. That was the half of the automatic split that did not
# work: a Japanese line could be timed only as a single block, or cut by hand
# one character at a time.
#
# The pieces here are the ones a singer's timing is made of, and the ones the
# hand-made amll-ttml-db files are cut into: a kana is a mora and a syllable
# of its own; a small kana (ゃ ゅ ょ ぁ ...) and the long mark ー belong to the
# kana in front of them -- きょ is one sound, not two; っ and ん are morae in
# their own right and stand alone; a kanji is one piece; a hangul block is a
# syllable by construction; a hanzi is a syllable by definition. Punctuation
# rides on the piece before it, as it does in the Latin rules, and a Latin
# word inside the run is cut by the Latin rule.
#
# Cyrillic and Greek are alphabets with vowels and get the sung rule's shape
# -- a vowel group per syllable, one consonant opening the next -- with their
# own vowels, which the Latin rule did not know were vowels.
SMALL_KANA = set("ぁぃぅぇぉゃゅょゎゕゖァィゥェォャュョヮヵヶㇰㇱㇲㇳㇴㇵㇶㇷㇸㇹㇺㇻㇼㇽㇾㇿー゛゜ゝゞヽヾ"
                 "ｧｨｩｪｫｬｭｮｰﾞﾟ")
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u2e80-\u2fdf々〆〇]")
_HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
_GREEK = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
ALPHABETS = {
    "cyr": "аеёиоуыэюяіїєўӣӯ",
    "el": "αεηιουωάέήίόύώϊϋΐΰ",
}


def script(word: str, japanese: bool = False) -> str:
    """"ja", "zh", "ko", "cyr", "el", or "" for anything else."""
    word = str(word or "")
    if _HANGUL.search(word):
        return "ko"
    if _KANA.search(word):
        return "ja"
    if _HAN.search(word):
        return "ja" if japanese else "zh"
    if _CYRILLIC.search(word):
        return "cyr"
    if _GREEK.search(word):
        return "el"
    return ""


def is_cjk(ch: str) -> bool:
    return bool(_KANA.match(ch) or _HAN.match(ch) or _HANGUL.match(ch))


OPENING = SL.OPENERS.strip("\"'")


def _cjk(word: str, method: str, lang: str) -> list[str]:
    """A run of Japanese, Chinese or Korean in the pieces it is sung in."""
    out: list[str] = []
    latin = ""
    held = ""                       # an opening bracket, waiting for its word

    def flush() -> None:
        nonlocal latin, held
        if latin:
            got = split(latin, method, lang) if latin.strip() else [latin]
            if out and not held and not any(c.isalnum() for c in got[0]):
                out[-1] += got[0]
                got = got[1:]
            if got:
                got[0], held = held + got[0], ""
            out.extend(got)
            latin = ""

    for ch in word:
        if is_cjk(ch):
            flush()
            if ch in SMALL_KANA and out and is_cjk(out[-1][-1:]) and not held:
                out[-1] += ch
            else:
                out.append(held + ch)
                held = ""
        elif ch.isalnum() or (latin and ch in "'’-"):
            if held and not latin:
                latin, held = held, ""
            latin += ch
        else:
            if latin and ch not in OPENING:
                latin += ch
            elif ch in OPENING or held:
                # 「 belongs to the word it opens: は|「好, never は「|好
                flush()
                held += ch
            elif out:
                out[-1] += ch
            else:
                out.append(ch)
    flush()
    if held:
        out.append(held)
    while len(out) > 1 and not any(c.isalnum() for c in out[0]):
        out[1] = out[0] + out[1]
        out.pop(0)
    return out if "".join(out) == word and all(out) else [word]


# --------------------------------------------------------------------------
# Japanese by syllable rather than by mora.
#
# A mora is the beat Japanese is sung on, but it is not a syllable: きょう is
# one syllable (kyō) and two morae, がっこう is gak-kō, せんせい sen-sei. Cut a
# kana at a time, a line came apart into pieces no English singer would hear
# as separate -- ん and っ alone, the second half of every long vowel alone.
# So, over the morae: ん, っ and ー always close the syllable before them (none
# of them can start one), and a bare vowel kana joins a syllable that is still
# a single open mora when the two make a long vowel (aa ii uu ee oo, ou, ei)
# or a diphthong (ai, oi, ui) -- unless it is about to make a long vowel
# with the kana after it, which it keeps for that (か|わ|いい, not か|わい|い).
# The joined syllable is closed; nothing else joins it but ん, っ and ー.
#
# The vowel join is the one that can be wrong, at a word boundary: この|うた
# is not "nou". So it never crosses a pykakasi segment, and a lone particle
# straight after a kanji or katakana word (君は|いつも, 家に|いる) does not
# take the vowel after it. pykakasi does not segment a run of hiragana, so
# inside one the join is a guess, and a kept correction is the way out.
_VOWEL_ROWS = {
    "a": "あかがさざただなはばぱまやらわぁゃゎゕ",
    "i": "いきぎしじちぢにひびぴみりゐぃ",
    "u": "うくぐすずつづぬふぶぷむゆるゔぅゅっ",
    "e": "えけげせぜてでねへべぺめれゑぇゖ",
    "o": "おこごそぞとどのほぼぽもよろをぉょ",
}
_VOWEL_OF = {ch: v for v, row in _VOWEL_ROWS.items() for ch in row}
_BARE = {"あ": "a", "い": "i", "う": "u", "え": "e", "お": "o"}
_JOINS = {"aa", "ii", "uu", "ee", "oo", "ou", "ei", "ai", "oi", "ui"}
_CLOSE = set("んっー")
_LONE = set("はがをにへのもとでや")


def _hira(text: str) -> str:
    """Katakana as hiragana, a character at a time (half-width is left as it
    is). Takes a whole piece as well as a single character."""
    return "".join(chr(ord(ch) - 0x60) if "\u30a1" <= ch <= "\u30f6" else ch
                   for ch in text)


def _ja_syllables(word: str, morae: list[str]) -> list[str]:
    """`morae` (from _cjk) put together into syllables; see above."""
    if len(morae) < 2 or not _KANA.search(word):
        return morae
    cuts, reads = _segment_marks(word)
    out: list[str] = []
    is_open: list[bool] = []
    vowel: list[str] = []
    at = 0
    for i, piece in enumerate(morae):
        start, at = at, at + len(piece)
        after = _hira(morae[i + 1]) if i + 1 < len(morae) else ""
        marks = "".join(c for c in piece if not c.isalnum())
        lead = len(piece) - len(piece.lstrip(marks))
        core = piece[lead:].rstrip(marks)
        first = _hira(piece[lead:lead + 1])
        prev = out[-1] if out else ""
        if (prev and not lead and first in _CLOSE and is_cjk(piece[:1])
                and is_cjk(prev[-1:])):
            out[-1] += piece
            is_open[-1] = False
            continue
        if (prev and not lead and is_open[-1] and is_cjk(prev[-1:]) and core
                and len(core) == 1 and _hira(core) in _BARE
                and vowel[-1] + _BARE[_hira(core)] in _JOINS
                and not (vowel[-1] != _BARE[_hira(core)]
                         and after == _hira(core) and at not in cuts)
                and start not in cuts
                and not (len(prev) == 1 and prev in _LONE and len(out) > 1
                         and _KANJI_KATA.search(out[-2][-1:]))):
            out[-1] += piece
            is_open[-1] = False
            continue
        out.append(piece)
        last = _hira(core[-1:]) if core else ""
        if _HAN.match(last):
            last = reads.get(start + lead + len(core) - 1, "")
        v = _VOWEL_OF.get(last, "")
        vowel.append(v)
        is_open.append(bool(v) and last != "っ"
                       and not any(_hira(c) in _CLOSE for c in core[1:]))
    return out if "".join(out) == word and all(out) else morae


def _segment_marks(word: str) -> tuple[set, dict]:
    """Where pykakasi's segments of `word` begin, and for the last kanji of
    each segment the last kana of its reading (思い -> 思 is read ...も), so a
    vowel after it can be told apart: 想い joins, 歌う does not."""
    try:
        segs = list(SL._convert(SL._kakasi(), word))
    except Exception:                                    # noqa: BLE001
        return set(), {}
    if "".join(str(x.get("orig") or "") for x in segs) != word:
        return set(), {}
    cuts: set = set()
    reads: dict = {}
    at = 0
    for seg in segs:
        orig, hira = str(seg.get("orig") or ""), str(seg.get("hira") or "")
        cuts.add(at)
        tail = len(orig)
        while tail and not _HAN.match(orig[tail - 1]):
            tail -= 1
        kana = "".join(_hira(c) for c in orig[tail:])
        if tail and hira.endswith(kana) and len(hira) > len(kana):
            reads[at + tail - 1] = hira[len(hira) - len(kana) - 1]
        at += len(orig)
    cuts.discard(0)
    return cuts, reads


# --------------------------------------------------------------------------
# By word, for the scripts a reading is written for.
#
# Japanese is not spaced, and pykakasi's segments are the nearest thing to
# words there is to hand -- but they are cut for READING, not for singing:
# 聞こえる comes back 聞こ + える and 続けたい as 続け + たい, and a particle is a
# segment of its own. So a segment of hiragana is put back on the one before
# it where that one holds kanji or katakana (the verb's ending, the particle
# after a noun), and a particle is put back on whatever it follows: the unit
# is the bunsetsu, 君の / 声が / 聞こえる, which is also where a singer breathes.
PARTICLES = {
    "は", "が", "を", "に", "で", "と", "も", "の", "へ", "や", "か", "ね", "よ",
    "な", "さ", "わ", "ぞ", "ぜ", "って", "から", "まで", "より", "けど", "けれど",
    "ても", "でも", "だけ", "しか", "ばかり", "など", "なら", "たら", "ば", "て",
    "た", "だ", "です", "ます", "ない", "たい", "には", "では", "とは", "へは",
    "のに", "ので", "のは", "のが", "かな", "よね", "かも",
}
CLOSERS = "」』）)]】〉》\"'”’"
_KANJI_KATA = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff々〆"
                         r"\u30a0-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HIRA = re.compile(r"^[\u3040-\u309fー]+$")


def _words(word: str, kind: str, method: str, lang: str) -> list[str]:
    """`word` cut at its words, spaces riding on the piece before them."""
    out: list[str] = []
    for chunk in re.split(r"(\s+)", word):
        if not chunk:
            continue
        if chunk.isspace():
            if out:
                out[-1] += chunk
            else:
                out.append(chunk)
            continue
        if kind == "ja" or (kind == "zh" and _KANA.search(chunk)):
            got = _ja_words(chunk)
        elif kind == "zh":
            got = _zh_words(chunk)
        else:
            got = [chunk]
        out.extend(got)
    out = _marks_back(out)
    return out if "".join(out) == word and all(out) else [word]


def _marks_back(out: list[str]) -> list[str]:
    """A piece that is only punctuation goes onto the piece before it (or,
    at the start, the one after): a comma is never a word of its own. An
    opening bracket goes onto the piece after it, the word it opens."""
    done: list[str] = []
    held = ""
    for piece in out:
        bare = not any(ch.isalnum() for ch in piece)
        if bare and piece.rstrip()[-1:] in OPENING:
            held += piece
        elif held:
            done.append(held + piece)
            held = ""
        elif done and bare:
            done[-1] += piece
        else:
            done.append(piece)
    if held:
        done.append(held)
    while len(done) > 1 and not any(ch.isalnum() for ch in done[0]):
        done[1] = done[0] + done[1]
        done.pop(0)
    return done


def _ja_words(text: str) -> list[str]:
    try:
        k = SL._kakasi()
        segs = [str(x.get("orig") or "") for x in SL._convert(k, text)]
    except Exception:                                    # noqa: BLE001
        return [text]
    if "".join(segs) != text:
        return [text]
    out: list[str] = []
    for seg in segs:
        # A closing mark pykakasi hands to the NEXT segment ("」って") goes
        # back onto the word it closes.
        while out and seg and not seg[0].isalnum() and seg[0] in CLOSERS + "、。，．！？!?,.":
            out[-1] += seg[0]
            seg = seg[1:]
        if not seg:
            continue
        prev = out[-1] if out else ""
        ends_open = prev and (any(ch.isalnum() for ch in prev[-1:])
                              or (prev[-1:] in CLOSERS and seg in PARTICLES))
        if prev and ends_open and _HIRA.match(seg) and (
                seg in PARTICLES or _KANJI_KATA.search(prev)
                or prev in PARTICLES or prev[-1:] in "っッ"):
            out[-1] += seg
        else:
            out.append(seg)
    return out


def _zh_words(text: str) -> list[str]:
    """Chinese in words: jieba where it is installed, else the longest
    phrases pypinyin knows, one hanzi at a time where it knows none."""
    try:
        import jieba                                     # noqa: PLC0415
        got = list(jieba.cut(text, HMM=True))
        if "".join(got) == text:
            return got
    except Exception:                                    # noqa: BLE001
        pass
    known = _zh_phrases()
    out, i = [], 0
    while i < len(text):
        step = 1
        for n in range(min(6, len(text) - i), 1, -1):
            if text[i:i + n] in known:
                step = n
                break
        out.append(text[i:i + step])
        i += step
    return out


@functools.lru_cache(maxsize=1)
def _zh_phrases() -> frozenset:
    try:
        from pypinyin.phrases_dict import phrases_dict  # noqa: PLC0415
        return frozenset(phrases_dict)
    except Exception:                                    # noqa: BLE001
        return frozenset()


def chinese_words_complete() -> bool:
    """Whether Chinese can be cut into words properly (jieba is here)."""
    try:
        import jieba                                     # noqa: F401,PLC0415
        return True
    except Exception:                                    # noqa: BLE001
        return False


def _vowel_split(word: str, vowels: str) -> list[str]:
    """The sung rule's shape for an alphabet it was not written for."""
    head, core, tail = SL.peel(word)
    if (head or tail) and core:
        got = _vowel_split(core, vowels)
        got[0] = head + got[0]
        got[-1] = got[-1] + tail
        return got
    low = word.lower()
    groups, i = [], 0
    while i < len(low):
        if low[i] in vowels:
            j = i
            while j + 1 < len(low) and low[j + 1] in vowels:
                j += 1
            groups.append((i, j))
            i = j + 1
        else:
            i += 1
    if len(groups) < 2 or len(word) <= 3:
        return [word]
    cuts = []
    for (a0, a1), (b0, _b1) in zip(groups, groups[1:]):
        gap = b0 - a1 - 1
        cuts.append(a1 + 1 if gap <= 1 else b0 - 1)
    out, prev = [], 0
    for c in cuts:
        if c > prev:
            out.append(word[prev:c])
            prev = c
    out.append(word[prev:])
    return out if "".join(out) == word and all(out) else [word]


def _hyphenate(word: str, lang: str) -> list[str]:
    """Liang hyphenation, mapped back onto the word as it is written.

    The patterns are fed the LETTERS only -- an apostrophe or a trailing
    comma is not part of any pattern and derails them -- and the cuts they
    return are then made in the original string, so every character the word
    had comes back in the piece it belongs to.

    The punctuation comes off first, for the same reason it does in the sung
    rule: a hyphen is a seam and a comma is not, so "Bed-," was coming back
    as "Bed-" and a comma standing alone as a syllable of its own.
    """
    head, core, tail = SL.peel(word)
    if (head or tail) and core:
        got = _hyphenate(core, lang)
        got[0] = head + got[0]
        got[-1] = got[-1] + tail
        return got if "".join(got) == word and all(got) else [word]
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
