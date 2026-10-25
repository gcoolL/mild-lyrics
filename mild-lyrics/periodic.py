"""Troll: spell the lyrics in chemical element symbols.

"mistake" reads m I S Ta K e -- each symbol in its own case, the letters no
element covers in lower case, and each symbol's atomic number to draw with it.
"""

import re

SYMBOLS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni "
    "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I "
    "Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt "
    "Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr "
    "Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og").split()
NUMBER = {s.lower(): (s, n) for n, s in enumerate(SYMBOLS, 1)}
MODES = ["off", "under", "top right", "numbers", "symbols only",
         "numbers only"]
READS = {"under", "top right", "numbers"}     # a small row of readings
NUMBERED = {"numbers", "numbers only"}        # numbers in the lyric itself
SEP = "\u2027"            # a little wider than Outfit's own middle dot

_WORD = re.compile(r"[A-Za-z]+")


def _cover(word: str) -> list[tuple[int, int]]:
    """The symbols to read `word` as: most letters covered, then fewest symbols."""
    low = word.lower()
    n = len(low)
    best: list = [None] * (n + 1)      # best[i]: (uncovered, symbols, cuts) for low[i:]
    best[n] = (0, 0, ())
    for i in range(n - 1, -1, -1):
        un, k, cuts = best[i + 1]
        pick = (un + 1, k, cuts)
        for size in (1, 2):
            if i + size <= n and low[i:i + size] in NUMBER:
                un, k, cuts = best[i + size]
                pick = min(pick, (un, k + 1, ((i, i + size),) + cuts))
        best[i] = pick
    return list(best[0][2])


def spell(text: str) -> tuple[str, list[tuple[int, int, int]]]:
    """The text re-cased as symbols, and (first, last + 1, atomic number) per symbol."""
    out = [c.lower() if len(c.lower()) == 1 else c for c in text or ""]
    marks = []
    for m in _WORD.finditer(text or ""):
        for a, b in _cover(m.group()):
            sym, num = NUMBER[m.group()[a:b].lower()]
            out[m.start() + a:m.start() + b] = sym
            marks.append((m.start() + a, m.start() + b, num))
    return "".join(out), marks


def numbered(texts: list[str], ends: list[bool]) -> list[str]:
    """Pieces with each symbol written as its atomic number, dotted apart.

    `ends[i]` is whether piece i ends its word. A symbol cut across two
    pieces is written in the piece it starts in, and a dot between two
    pieces ends the first of them.
    """
    joined = "".join(t + (" " if e else "") for t, e in zip(texts, ends))
    spelt, marks = spell(joined)
    starts = {a: (b, num) for a, b, num in marks}
    out: list[list[str]] = []
    g, skip, prev, held = 0, 0, None, None     # held: the piece prev is in
    for t, e in zip(texts, ends):
        bits: list[str] = []
        out.append(bits)
        for _ in t:
            if g < skip:
                g += 1
                continue
            if g in starts:
                skip, num = starts[g]
                tok, kind, dot = str(num), "num", prev is not None
            elif spelt[g].isalpha():
                tok, kind, dot = spelt[g], "let", prev == "num"
            else:
                tok, kind, dot = spelt[g], None, False
            if dot:
                out[held].append(SEP)
            bits.append(tok)
            prev, held = kind, len(out) - 1
            g += 1
        if e:
            g += 1
            prev = None
    return ["".join(b) for b in out]
