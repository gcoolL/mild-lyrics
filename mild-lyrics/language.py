"""What language a lyric is actually in, when the file's own answer is wrong.

Every provider stamps a language code on its documents and a good share of
them are guesses made by a machine on a few hundred words. The failure mode
is specific and it is always the same shape: an English lyric comes back as
some other Latin-script language with a small corpus behind it -- `pcm`
(Nigerian Pidgin), `sco` (Scots), `nl`, `af`. Music Baby arrives as `pcm`.

That code is not decoration. It goes into the file as `xml:lang`, it picks
the hyphenation patterns a word is cut into syllables with, and it is what a
reader is told the song is. A wrong one is wrong three times over.

So the claim is CHECKED rather than trusted, and only overruled when the text
disagrees with it clearly. The test is deliberately blunt -- script first,
then how much of the text is made of English function words -- because a
subtle detector that is right nine times in ten would introduce a new way to
be wrong for songs whose code was fine all along.
"""
from __future__ import annotations

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


def check(claimed: str, text: str) -> tuple[str, str]:
    """The language to use, and why -- `claimed` unless the text says otherwise.

    Returns (code, reason). The reason is empty when the claim stands, and a
    sentence worth showing when it does not: a code being quietly rewritten
    is exactly as unhelpful as a code being quietly wrong.
    """
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
