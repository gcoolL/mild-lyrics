"""What language a lyric is actually in, when the provider's code is wrong:
script first, then English function words, overruling only clear cases."""
from __future__ import annotations

import functools
import re
import unicodedata

ENGLISH = frozenset("""
a about after all am an and any are as at back be because been before but by
can cause come could did do does don't down for from get go going got had has
have he her here him his how i i'm if in is it it's just know let like ll me
more my never no not now of oh on one only or our out over re said say see she
should so some still take tell than that the them then there these they this
through time to too up us ve want was way we well were what when where which
who why will with would you your
""".split())

NEAR_ENGLISH = frozenset({"sco", "pcm", "jam", "gd", "ga", "cy", "af", "fy",
                          "lb", "nds", "bar", "gsw", "en-x", "und", "unknown"})

_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)


def script_of(text: str) -> str:
    """The dominant writing system, by character counts."""
    tally: dict = {}
    for ch in str(text or ""):
        if not ch.isalpha():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        for key, mark in (("hangul", "HANGUL"), ("cjk", "CJK"),
                          ("kana", "HIRAGANA"), ("kana", "KATAKANA"),
                          ("cyrillic", "CYRILLIC"), ("arabic", "ARABIC"),
                          ("hebrew", "HEBREW"), ("greek", "GREEK"),
                          ("thai", "THAI"), ("devanagari", "DEVANAGARI"),
                          ("latin", "LATIN")):
            if mark in name:
                tally[key] = tally.get(key, 0) + 1
                break
    if not tally:
        return ""
    return max(tally, key=lambda k: tally[k])


def english_share(text: str) -> float:
    """How much of the text is made of English function words, 0..1."""
    words = [w.lower() for w in _WORD.findall(str(text or ""))]
    if len(words) < 12:
        return 0.0
    return sum(1 for w in words if w in ENGLISH) / len(words)


ENGLISH_AT = 0.20


@functools.lru_cache(maxsize=16)
def check(claimed: str, text: str) -> tuple[str, str]:
    """The language to use and why: (code, reason), reason empty when `claimed`
    stands. Remembered for the last few texts."""
    want = str(claimed or "").strip()
    short = want.lower().replace("_", "-").split("-")[0]
    script = script_of(text)
    if not script:
        return want, ""
    share = english_share(text)
    if share >= ENGLISH_AT and script == "latin":
        if short in ("en", ""):
            return want, ""
        if short in NEAR_ENGLISH:
            return "en", (f"the words are English ({share:.0%} function "
                          f"words) — “{want}” looks like a provider's guess")
        return want, ""
    if short == "en" and script not in ("latin", ""):
        return want, f"marked English but written in {script}"
    return want, ""


_BY_SCRIPT = {"hangul": "ko", "greek": "el", "thai": "th", "hebrew": "he"}
_KANA = re.compile(r"[぀-ヿ]")


@functools.lru_cache(maxsize=16)
def guess(text: str) -> str:
    """A code for text that came with none, or "" where the script alone
    cannot say (Cyrillic, Arabic, a Latin lyric that is not English)."""
    script = script_of(text)
    if script in ("kana", "cjk"):
        return "ja" if _KANA.search(text) else "zh"
    if script == "latin":
        return "en" if english_share(text) >= ENGLISH_AT else ""
    return _BY_SCRIPT.get(script, "")


# ------------------------------------------------------------ direction
@functools.lru_cache(maxsize=4096)
def is_rtl(text: str) -> bool:
    """Whether a line reads right to left: more RTL letters than LTR ones,
    counted."""
    r = l = 0
    for ch in text:
        d = unicodedata.bidirectional(ch)
        if d in ("R", "AL"):
            r += 1
        elif d == "L":
            l += 1
    return r > l


def strong_ltr(text: str) -> bool:
    """A word with left-to-right letters in it and no right-to-left ones."""
    dirs = {unicodedata.bidirectional(ch) for ch in text}
    return "L" in dirs and not dirs & {"R", "AL"}


_RIGHT_JOINING = set("ءآأؤإاةدذ"
                     "رزوٱٲٳٵٶٷ"
                     "ڈډڊڋڌڍڎڏڐ"
                     "ڑڒړڔڕږڗژڙ"
                     "ۀۃۄۅۆۇۈۉۊ"
                     "ۋۍۏ")
ZWJ = "‍"


def _joining_letter(ch: str) -> bool:
    return ("ؠ" <= ch <= "ي" or "ٮ" <= ch <= "ۓ"
            or "ۺ" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ")


def _last_letter(txt: str):
    for ch in reversed(txt):
        if unicodedata.category(ch) not in ("Mn", "Cf"):
            return ch
    return ""


def joins(a: str, b: str) -> bool:
    """Whether the end of syllable `a` is written joined to the start of `b`,
    so both get a ZWJ and Arabic keeps its connected forms."""
    la = _last_letter(a)
    fb = b[:1]
    return (bool(la) and bool(fb) and _joining_letter(la) and la not in _RIGHT_JOINING
            and _joining_letter(fb) and fb != "ء")
