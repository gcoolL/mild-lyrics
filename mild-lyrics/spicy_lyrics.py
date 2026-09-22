#!/usr/bin/env python3
"""
The Spicy Lyrics document: what one looks like, what it says, and what this
program turns it into.

Fetching it is lyric_sources' job, with every other source's -- Spicy Lyrics
is an ordinary provider there now (see LS.from_spicy), asked by Spotify track
id over its own API. This module is what the answer becomes: the timeline the
window draws from, the syllabifier, the romanisations and furigana, and the
renderers for text, LRC, Enhanced LRC and TTML. The commands below are a front
door onto both.

What stood here before was a reader for the Spicetify extension's Cache
Storage inside the running Spotify app, which is why the fetching was ever in
this file at all. Everything that was awkward about it is gone with it: a song
no longer has to have been played once with the lyrics view open before it
exists, a cold track no longer answers "nothing yet" for a few seconds before
answering properly, and Spotify does not have to be running at all -- except
to be asked what is playing, which was always its own question (see
current_track_id, the one thing here that still talks to it).

The document:

    { Type: "Syllable"|"Line"|"Static", id, source, SongWriters[],
      StartTime, EndTime, TTMLUploadMetadata?, Content: [ line, ... ] }

    Syllable line: { Type, OppositeAligned, Lead: { Syllables: [
                       {Text, IsPartOfWord, StartTime, EndTime} ],
                     StartTime, EndTime }, Background: [ group, ... ] }
    Line line:     { Type, OppositeAligned, Text, StartTime, EndTime }
    Static line:   { Text }                    -- filed under `Lines`, not `Content`

    All times are SECONDS (floats). `source` is spl (the community), aml
    (Apple Music) or spt (Spotify), named the short way at the one door
    documents come in by; see LS._spicy_docked, which also files the credits
    under TTMLUploadMetadata and takes out the zero-width spaces.

ATTRIBUTION is a condition of the API, not a courtesy. Wherever the lyrics
are, the provider is named, and where the sync is the community's, the
uploader and the maker are named and LINKED -- each contributor carries the
`url` of their own page, and that is the link a credit line points at. Those
two are absent, not empty, on a catalogue's answer, so nothing may draw a
blank credit line; a document that names no source at all is credited to
nobody rather than to somebody. The window does this in
lyrics_gui.LyricsView.credit_rows.

Formats:
    text  plain lines, no timing
    lrc   standard LRC, one [mm:ss.xx] tag per line. Line-level ONLY -- the
          format cannot express word timing, so Syllable data is collapsed.
    elrc  Enhanced LRC (A2): [mm:ss.xx]<mm:ss.xx>syl<mm:ss.xx>syl...
          Preserves per-syllable timing. Degrades to line-level for Line/Static
          entries, which carry no syllable data. Use this for karaoke sync.
    json  the document as it is held, less the zero-width spaces Spicy Lyrics
          writes into it; nothing else discarded

Usage:
    ./spicy_lyrics.py key sl_sk_...               # keep a key of your own
    ./spicy_lyrics.py get <trackid>               # any track, plain text
    ./spicy_lyrics.py get                         # whatever Spotify is playing
    ./spicy_lyrics.py get --format elrc           # word-synced (A2)
    ./spicy_lyrics.py get --format lrc            # line-synced
    ./spicy_lyrics.py get <trackid> --format json # the document itself
    ./spicy_lyrics.py get --format elrc -o song.lrc
    ./spicy_lyrics.py keys                        # track ids fetched so far
    ./spicy_lyrics.py dump ./lyrics-export        # export those, elrc
    ./spicy_lyrics.py watch                       # karaoke; overlapping lines and
                                                  #   backing vocals both shown
    ./spicy_lyrics.py watch --offset -0.3         # show lines 300ms earlier
    ./spicy_lyrics.py watch --split long          # also break up held words
    ./spicy_lyrics.py watch --no-karaoke          # plain line-at-a-time

A key ships with the program, so none of that needs setting up; see
LS.SPICY_SHIPPED_KEY for what kind of key it has to be and why. Asking what is
playing, and following it, still wants Spotify started with a DevTools port --
or, on Linux, nothing at all, since the session bus answers the same question:

    pkill -x spotify                                       # Linux
    spotify --remote-debugging-port=9222 >/dev/null 2>&1 &

    osascript -e 'quit app "Spotify"'                      # macOS
    open -a Spotify --args --remote-debugging-port=9222

    "%APPDATA%\\Spotify\\Spotify.exe" --remote-debugging-port=9222   # Windows
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
from xml.sax.saxutils import escape, quoteattr

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]


# --------------------------------------------------------------------------
# What is playing. Still the player's own question, and the only thing here
# that wants Spotify to be running.
# --------------------------------------------------------------------------
JS_WHERE = """(() => {
  const P = Spicetify && Spicetify.Player;
  if (!P) return null;
  const it = (P.data || {}).item || (P.data || {}).track || {};
  return {uri: it.uri || "",
          pos: (P.getProgress ? P.getProgress() : 0) / 1000,
          playing: P.isPlaying ? !!P.isPlaying() : false};
})()"""


def current_track_id(cdp=None) -> str | None:
    """The playing track's id, off the page where there is one to ask.

    `cdp` is a connection this caller already has open, and where it is given
    it is preferred: it is the only route on Windows and macOS, and every
    command in this tool that wants a track id has one in its hand already.
    The session bus is the fallback, for a caller with no connection.
    """
    if cdp is not None:
        try:
            got = cdp.evaluate(JS_WHERE) or {}
            m = re.search(r"([A-Za-z0-9]{22})", str(got.get("uri") or ""))
            if m:
                return m.group(1)
        except Exception:
            pass
    try:
        import dbus
    except ImportError:
        return None
    try:
        obj = dbus.SessionBus().get_object(
            "org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2"
        )
        meta = dbus.Interface(obj, "org.freedesktop.DBus.Properties").Get(
            "org.mpris.MediaPlayer2.Player", "Metadata"
        )
        m = re.search(r"([A-Za-z0-9]{22})", str(meta.get("mpris:trackid", "")))
        return m.group(1) if m else None
    except Exception:
        return None


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
_PROPS = None


def player_state(cdp=None) -> tuple[str | None, float, str]:
    """(track_id, position_seconds, status). Position advances 1.0s/s while playing.

    Off the page where a connection is to hand -- see current_track_id for why
    that is both the portable route and the better one -- and off the session
    bus otherwise.
    """
    global _PROPS
    if cdp is not None:
        try:
            got = cdp.evaluate(JS_WHERE) or {}
            m = re.search(r"([A-Za-z0-9]{22})", str(got.get("uri") or ""))
            return ((m.group(1) if m else None), float(got.get("pos") or 0.0),
                    "Playing" if got.get("playing") else "Paused")
        except Exception:
            return None, 0.0, "Error"
    try:
        import dbus
    except ImportError:
        return None, 0.0, "NoDBus"
    try:
        if _PROPS is None:
            obj = dbus.SessionBus().get_object(
                "org.mpris.MediaPlayer2.spotify", "/org/mpris/MediaPlayer2"
            )
            _PROPS = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
        meta = _PROPS.Get("org.mpris.MediaPlayer2.Player", "Metadata")
        pos = float(_PROPS.Get("org.mpris.MediaPlayer2.Player", "Position")) / 1e6
        status = str(_PROPS.Get("org.mpris.MediaPlayer2.Player", "PlaybackStatus"))
        m = re.search(r"([A-Za-z0-9]{22})", str(meta.get("mpris:trackid", "")))
        return (m.group(1) if m else None), pos, status
    except Exception:
        _PROPS = None
        return None, 0.0, "Error"


VOWELS = "aeiouyàáâäåèéêëìíîïòóôöøùúûüæœ"
HYPHENS = "-\u2011\u2013"
DIGRAPHS = ("th", "ch", "sh", "ph", "wh", "gh", "ck", "qu")
OPENERS = "\"'(¿¡[“‘«"


def peel(word: str) -> tuple[str, str, str]:
    """`word` as (punctuation in front, the word itself, punctuation after).

    The one place this project decides what "the punctuation around a word"
    is, because every rule that reads a word's spelling has to set the same
    characters aside and put them back, and a comma that counts as part of
    the word in one of them and not in another is how "fallin'" and
    "fallin'," come to be split two different ways.

    An apostrophe is the one mark that is not peeled: it is the word's own
    spelling rather than punctuation around it, and fallin', don't and rock
    'n' roll are cut with it in.

    A space and a zero-width space peel too. They are not punctuation, but
    they are not part of the spelling either -- a zero-width one is a word
    boundary drawn without a gap -- and a word that ends in one was being
    read as ending in something that is not an e, which is how "have\u200b"
    came back ha|ve.

    head + core + tail is always exactly the word that went in.
    """
    core = word
    tail = ""
    while core and not (core[-1].isalnum() or core[-1] == "'"):
        tail = core[-1] + tail
        core = core[:-1]
    head = ""
    while core and (core[0] in OPENERS or core[0].isspace()
                    or core[0] == "\u200b"):
        head += core[0]
        core = core[1:]
    return head, core, tail


def syllabify(word: str) -> list[str]:
    """Heuristic English syllable split. Pieces always re-join to the input.

    Punctuation is set aside before the spelling is read and put back after,
    so a word is cut the same way wherever it stands in a line: "fallin'",
    "fallin'," and "fallin'!" all come back fal|lin'. It is not part of any
    word's sound, and leaving it in defeated the silent-e rule below on every
    word that happened to end a phrase: "Home," came back "Ho-me," and
    "cure?" as "cu-re?", because the test asked whether the last CHARACTER
    was an e.

    It is peeled BEFORE the hyphen is looked for, because a hyphen is where
    the word comes apart and punctuation is not: read the other way round,
    "Bed-," was cut into "Bed-" and a comma -- a syllable made of nothing,
    which is a syllable the singer never sings.
    """
    head, core, tail = peel(word)
    if (head or tail) and core:
        pieces = syllabify(core)
        pieces[0] = head + pieces[0]
        pieces[-1] = pieces[-1] + tail
        return pieces
    if len(word) > 1 and any(h in word[:-1] for h in HYPHENS):
        chunks, buf = [], ""
        for ch in word:
            buf += ch
            if ch in HYPHENS:
                chunks.append(buf)
                buf = ""
        if buf:
            chunks.append(buf)
        pieces: list[str] = []
        for chunk in chunks:
            mark = chunk[-1] if chunk[-1] in HYPHENS else ""
            body = chunk[:-1] if mark else chunk
            got = syllabify(body) if body else []
            if not got:
                if pieces:
                    pieces[-1] += mark
                else:
                    pieces.append(mark)
                continue
            got[-1] += mark
            pieces.extend(got)
        while len(pieces) > 1 and all(c in HYPHENS for c in pieces[0]):
            pieces[1] = pieces[0] + pieces[1]
            pieces.pop(0)
        return pieces

    lw = word.lower()
    n = len(word)
    if n <= 3:
        return [word]
    groups, i = [], 0
    while i < n:
        if lw[i] in VOWELS:
            j = i
            while j + 1 < n and lw[j + 1] in VOWELS:
                j += 1
            groups.append((i, j))
            i = j + 1
        else:
            i += 1
    final_le = (
        n >= 4 and lw.endswith("le") and lw[-3] not in VOWELS and lw[-3].isalpha()
    )
    silent = -1
    if not final_le and len(groups) > 1:
        if lw.endswith("e"):
            silent = n - 1
        elif lw.endswith("ed") and n > 3 and lw[-3] not in "td":
            silent = n - 2
        elif lw.endswith("es") and n > 3 and lw[-3] not in "sxzcg" \
                and lw[-4:-2] not in ("ch", "sh"):
            silent = n - 2
    if silent >= 0 and groups and groups[-1] == (silent, silent):
        groups.pop()
    if len(groups) < 2 and not final_le:
        return [word]
    cuts = []
    for k in range(len(groups) - 1):
        end_v, start_next = groups[k][1], groups[k + 1][0]
        units, at = [], end_v + 1
        while at < start_next:
            step = 2 if (lw[at:at + 2] in DIGRAPHS and at + 2 <= start_next) else 1
            units.append(at)
            at += step
        if not units:
            cut = start_next
        elif len(units) == 1:
            cut = units[0]
        else:
            cut = units[len(units) // 2]
        if cut > (cuts[-1] if cuts else 0):
            cuts.append(cut)
    if final_le:
        cuts = [c for c in cuts if c < n - 3] + [n - 3]
    pieces, prev = [], 0
    for c in cuts:
        if c > prev:
            pieces.append(word[prev:c])
            prev = c
    pieces.append(word[prev:])
    out: list[str] = []
    for p in pieces:
        if out and not any(ch in VOWELS for ch in p.lower()):
            out[-1] += p
        else:
            out.append(p)
    while len(out) > 1 and not any(ch in VOWELS for ch in out[0].lower()):
        out[1] = out[0] + out[1]
        out.pop(0)
    return out or [word]


def split_syllables(syls: list[tuple], mode: str = "none", threshold: float = 0.7) -> list[tuple]:
    """Optionally subdivide whole words, interpolating timings by length.

    mode "none" -- use the sync's own splits only. Whatever IsPartOfWord marks is
                   real measured data; nothing is invented. This is the default.
    mode "long" -- additionally subdivide only words held longer than `threshold`
                   seconds, where a static highlight is most visible.
    mode "all"  -- subdivide every standalone word.

    Entries already flagged IsPartOfWord are never touched in any mode.
    Interpolated boundaries are ESTIMATES, not measurements.
    """
    if mode == "none":
        return syls
    out = []
    for i, (s, e, txt, part) in enumerate(syls):
        prev_part = syls[i - 1][3] if i > 0 else False
        core = txt.strip()
        if part or prev_part or e <= s or not core:
            out.append((s, e, txt, part))
            continue
        if mode == "long" and (e - s) < threshold:
            out.append((s, e, txt, part))
            continue
        pieces = syllabify(core)
        if len(pieces) < 2:
            out.append((s, e, txt, part))
            continue
        lead = txt[: len(txt) - len(txt.lstrip())]
        tail = txt[len(txt.rstrip()):]
        total = sum(len(p) for p in pieces)
        t = s
        for k, p in enumerate(pieces):
            last = k == len(pieces) - 1
            end = e if last else t + (e - s) * len(p) / total
            text = (lead if k == 0 else "") + p + (tail if last else "")
            out.append((t, end, text, part if last else True))
            t = end
    return out


CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")
SCRIPTED = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿ᄀ-ᇿㄱ-ㆎ가-힣ힰ-ퟻЀ-ӿ]")


def foreign(text) -> bool:
    """Whether anything here is written in a script a romanisation is for.

    Wider than CJK on purpose -- Cyrillic, Greek, Hangul, Thai, Arabic and
    the rest all have romanisations and none of them are in that pattern --
    and asked by script rather than by code point, because a range wide
    enough to catch Vietnamese's diacritics catches Vietnamese, which is
    written in the Latin alphabet and needs nothing done to it.
    """
    import unicodedata

    for c in str(text or ""):
        if ord(c) < 0x0100 or not c.isalpha():
            continue
        try:
            if not unicodedata.name(c).startswith("LATIN"):
                return True
        except ValueError:
            continue
    return False


def strays_only(text) -> bool:
    """Whether the only non-Latin letters here are look-alikes in Latin words.

    "bе" with a Cyrillic е is an English word with a wrong key in it -- the
    review page calls it a homoglyph -- and not a line to romanise. Only
    Cyrillic and Greek, the alphabets that share letters with Latin; a word
    has to hold a Latin letter too for its odd one to be a stray.
    """
    import unicodedata

    stray = False
    for word in str(text or "").split():
        kinds = set()
        for c in word:
            if c.isalpha():
                try:
                    kinds.add(unicodedata.name(c).split()[0])
                except ValueError:
                    pass
        odd = kinds - {"LATIN"}
        if not odd:
            continue
        if "LATIN" in kinds and odd <= {"CYRILLIC", "GREEK"}:
            stray = True
            continue
        return False
    return stray


def needs_roman(text) -> bool:
    """Whether a line is written in a script a romanisation is for, and not
    merely an English one with a look-alike letter in it (strays_only)."""
    return bool(SCRIPTED.search(str(text or ""))) and not strays_only(text)


def canon(text: str) -> str:
    """Fold look-alike codepoints onto the real kanji.

    Some lyric sources spell 二人 with KANGXI RADICAL TWO (U+2F46) rather than
    U+4E8C. It renders identically, so nobody notices, but no romanizer or
    dictionary matches it. NFKC per character maps them back without changing
    the length, which the offset arithmetic below depends on.
    """
    out = []
    for ch in text:
        fixed = unicodedata.normalize("NFKC", ch)
        out.append(fixed if len(fixed) == 1 else ch)
    return "".join(out)
SOKUON = re.compile(r"[っッ]\s*$")
_KKS = None

# Where setup puts the pure-Python readers on a Python the distribution
# manages (PEP 668), beside the program rather than in the system's
# site-packages. Appended, so a real install still wins.
PYLIBS = pathlib.Path(__file__).resolve().parent.parent / "pylibs"
if PYLIBS.is_dir() and str(PYLIBS) not in sys.path:
    sys.path.append(str(PYLIBS))


def _kakasi():
    """pykakasi if it is installed, else None. Optional on purpose: it is only
    used to rescue syllables the source failed to transliterate at all."""
    global _KKS
    if _KKS is None:
        try:
            import pykakasi
            _KKS = pykakasi.kakasi()
        except Exception:
            _KKS = False
    return _KKS or None


def reading(text: str) -> str:
    """A whole string's romaji. The particles are read here too.

    They were not, and that was the single-string path quietly disagreeing
    with line_readings about the same sentence -- see particle_rom, which is
    defined below this because the table it needs is.
    """
    k = _kakasi()
    if not k or not text:
        return ""
    try:
        out, at = [], 0
        for seg in k.convert(text):
            src = seg.get("orig", "") or ""
            out.append(particle_rom(src, (seg.get("hepburn", "") or ""),
                                    at_start=(at == 0)))
            at += len(src)
        return "".join(out).strip()
    except Exception:
        return ""


PARTICLES = {"は": "wa", "へ": "e", "を": "o"}

_PARTICLE_SAID = {"は": ("ha", "wa"), "へ": ("he", "e"), "を": ("wo", "o")}
_ALL_KANA = re.compile(r"^[぀-ゟ゠-ヿー]+$")


def particle_rom(src: str, rom: str, at_start: bool = False) -> str:
    """A segment's reading, with は/へ/を read as the particles they are.

    pykakasi is a dictionary and gives these their spelling every time: は is
    `ha`, へ is `he`, を is `wo`. As grammatical particles they are said `wa`,
    `e` and `o`, and which one it is depends on the sentence, which pykakasi
    has no model of.

    This is applied where the reading is CUT rather than after it, and that is
    the whole of the fix. The correction used to sit in the last loop of
    line_readings, testing each SYLLABLE against the table, so it fired only
    when the lyric happened to time the particle as a syllable of its own. Over
    the 13 Japanese documents in bench/ and lyrics/ -- 143 particle characters:

         76  are a segment of their own          を, は
         44  are the last character of theirs    には -> niha, では -> deha
         23  are buried inside one               はない, あなたはかわいい

    The syllable rule reached 46 of the 143. A segment is a much better place
    to ask, because the segmenter has already decided where the words are: a
    lone particle segment, or a trailing は/へ/を on an all-kana one, reaches
    120. A line-timed Japanese lyric got none of them right before this and
    gets all of those now.

    The remaining 23 are left alone on purpose. はない really is "wa nai" and
    only grammar says so -- they are the OTHER fault (pykakasi having no
    morphological analyser) wearing this one's clothes, and chasing them with
    a longer table would start guessing. All-kana is the guard that keeps this
    honest: where the segmenter has bound a particle into a word with a kanji
    in it, it has made a judgement, and 今日は read as the greeting is that
    judgement being wrong in a way no table here can see.

    `at_start` carries the one case where は opening the text is not a
    particle -- nothing can be the topic before the topic is named.
    """
    src = (src or "").strip()
    if not src or not rom:
        return rom
    if src in PARTICLES:
        return rom if (at_start and src == "は") else PARTICLES[src]
    if len(src) > 1 and _ALL_KANA.match(src):
        said, want = _PARTICLE_SAID.get(src[-1], (None, None))
        if said and rom.endswith(said):
            return rom[:-len(said)] + want
    return rom


def mora_cut(rom: str, cut: int, low: int) -> int:
    """Nudge a split point onto a mora boundary.

    Dividing a reading by character share alone lands mid-syllable -- "fut|ari",
    "shiz|umu". Japanese mora end on a vowel or on n, so slide the cut to the
    nearest such position and the karaoke fill steps in whole sounds.
    """
    if cut <= low or cut >= len(rom):
        return cut
    for delta in (0, -1, 1, -2, 2):
        i = cut + delta
        if low < i < len(rom) and rom[i - 1].lower() in "aeioun":
            return i
    return cut


TRAILING_KANA = "っゃゅょぁぃぅぇぉゎーッャュョァィゥェォヮ"


def kana_cut(read: str, cut: int, low: int) -> int:
    """Nudge a split point in a KANA reading onto a mora boundary.

    mora_cut above works on romaji, where a mora ends on a vowel. In kana the
    rule is the other way round: small kana and the long mark belong to the
    character in front of them, so 直結 = ちょっけつ divides ちょっ / けつ and
    never ちょ / っけつ.
    """
    while low < cut < len(read) and read[cut] in TRAILING_KANA:
        cut += 1
    return cut


def line_readings(texts: list[str]) -> list[str]:
    """Readings for a whole line, handed back per syllable, plus the index of
    the romanizer word each syllable came from.

    A reading belongs to the WORD, not to its characters: romanising 明日 as
    明 + 日 gives "mei nichi" rather than "ashita", and 二人 gives "ni nin"
    rather than "futari". Measured over unambiguous cases, per-fragment scored
    0/14 and whole-line 9/14. So romanise the joined line for context and split
    the result back out -- where one word spans several syllables its reading is
    divided by character share, which can land the boundary a mora out inside
    that word but never gets the word itself wrong.
    """
    out = [""] * len(texts)
    owner = [-1] * len(texts)
    k = _kakasi()
    texts = [canon(t) for t in texts]
    joined = "".join(texts)
    if not k or not joined.strip():
        return out, owner
    spans, n = [], 0
    for t in texts:
        spans.append((n, n + len(t)))
        n += len(t)
    try:
        segments = k.convert(joined)
    except Exception:
        return out, owner
    pos = 0
    for si, seg in enumerate(segments):
        src = seg.get("orig", "") or ""
        rom = (seg.get("hepburn", "") or "").strip()
        a, b = pos, pos + len(src)
        pos = b
        if not src:
            continue
        rom = particle_rom(src, rom, at_start=(a == 0))
        touched = [i for i, (x, y) in enumerate(spans) if x < b and y > a]
        if not touched:
            continue
        for i in touched:
            if owner[i] < 0:
                owner[i] = si
        if len(touched) == 1:
            out[touched[0]] += rom
            continue
        if rom == src:
            # This segment needed no transliteration -- its reading IS its
            # text -- so every character can be pointed at exactly, and the
            # share below has nothing to guess at. Dividing it by share
            # anyway moves letters across the syllable boundaries: on a line
            # of Japanese with English in it the segmenter hands the whole
            # English run over as one segment, and "Hell yeah yeah yeah yeah"
            # timed a word at a time came out "Hell ye / a / h yea / h yea /
            # h yeah" on the screen. mora_cut makes it worse rather than
            # better there, because it is looking for Japanese mora in
            # somebody's chorus.
            for i in touched:
                out[i] += src[max(a, spans[i][0]) - a:min(b, spans[i][1]) - a]
            continue
        total = sum(min(b, spans[i][1]) - max(a, spans[i][0]) for i in touched) or 1
        acc = cut_prev = 0
        for j, i in enumerate(touched):
            acc += min(b, spans[i][1]) - max(a, spans[i][0])
            cut = len(rom) if j == len(touched) - 1 else round(len(rom) * acc / total)
            cut = mora_cut(rom, cut, cut_prev)
            out[i] += rom[cut_prev:cut]
            cut_prev = cut
    for i, t in enumerate(texts):
        stripped = t.strip()
        if stripped in PARTICLES and (i or stripped != "は"):
            out[i] = PARTICLES[stripped]
    return out, owner


KANJI = re.compile(r"[㐀-䶿一-鿿]")
KANA = re.compile(r"[぀-ゟ゠-ヿ]")


def _ruby(src: str, hira: str) -> tuple[int, int, str]:
    """Strip the okurigana off a segment: which slice of it needs a reading.

    A reading is set over the kanji only -- 動き is furigana'd as うご above 動,
    not うごき above both characters, because the き is already there to read.
    So peel matching kana off each end and keep what is left.
    """
    i = 0
    while (i < len(src) and i < len(hira) and src[i] == hira[i]
           and not KANJI.match(src[i])):
        i += 1
    j = 0
    while (j < len(src) - i and j < len(hira) - i
           and src[len(src) - 1 - j] == hira[len(hira) - 1 - j]
           and not KANJI.match(src[len(src) - 1 - j])):
        j += 1
    return i, len(src) - j, hira[i:len(hira) - j]


def furigana(texts: list[str]) -> list[list[tuple[int, int, str]]]:
    """Kana readings for the kanji in each piece of a line.

    Returns, per piece, a list of (first char, last char + 1, reading) so the
    view can set each reading over exactly the characters it belongs to. The
    whole line goes to the segmenter at once, for the same reason the
    romanisation does: 明日 read character by character is "mei nichi", and only
    in context is it あした.
    """
    out: list[list[tuple[int, int, str]]] = [[] for _ in texts]
    k = _kakasi()
    joined = "".join(texts)
    if not k or not KANJI.search(joined):
        return out
    spans, n = [], 0
    for t in texts:
        spans.append((n, n + len(t)))
        n += len(t)
    try:
        segments = k.convert(joined)
    except Exception:
        return out
    pos = 0
    for seg in segments:
        src = seg.get("orig", "") or ""
        hira = (seg.get("hira", "") or "").strip()
        a, b = pos, pos + len(src)
        pos = b
        if not src or not hira or not KANJI.search(src):
            continue
        lo, hi, read = _ruby(src, hira)
        if not read or hi <= lo:
            continue
        lo, hi = a + lo, a + hi
        touched = [i for i, (x, y) in enumerate(spans) if x < hi and y > lo]
        if not touched:
            continue
        if len(touched) == 1:
            i = touched[0]
            out[i].append((lo - spans[i][0], hi - spans[i][0], read))
            continue
        total = sum(min(hi, spans[i][1]) - max(lo, spans[i][0]) for i in touched) or 1
        acc = cut_prev = 0
        for m, i in enumerate(touched):
            acc += min(hi, spans[i][1]) - max(lo, spans[i][0])
            cut = len(read) if m == len(touched) - 1 else round(len(read) * acc / total)
            cut = kana_cut(read, cut, cut_prev)
            part = read[cut_prev:cut]
            cut_prev = cut
            if part:
                x, y = spans[i]
                out[i].append((max(lo, x) - x, min(hi, y) - x, part))
    return out


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
HANGUL = re.compile(r"[가-힣]")
HAN = re.compile(r"[㐀-䶿一-鿿⺀-⿟]")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")

# Russian as a reader without the alphabet would spell it (BGN/PCGN-ish,
# without the diacritics), plus the Ukrainian, Belarusian and Serbian
# letters a Russian table leaves as they are. Needs no package, like Korean.
CYR_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "'", "э": "e", "ю": "yu", "я": "ya",
    "є": "ye", "і": "i", "ї": "yi", "ґ": "g", "ў": "w", "ђ": "dj",
    "ј": "j", "љ": "lj", "њ": "nj", "ћ": "c", "џ": "dz", "ѓ": "gj",
    "ќ": "kj", "ѕ": "dz",
}


def cyrillic_reading(text: str) -> str:
    """Cyrillic in Latin letters, one character at a time, case kept."""
    out = []
    for ch in str(text or ""):
        low = ch.lower()
        r = CYR_LATIN.get(low)
        if r is None:
            out.append(ch)
        elif ch != low and r:
            out.append(r[0].upper() + r[1:])
        else:
            out.append(r)
    return "".join(out)

KO_LEAD = ("g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",
           "j", "jj", "ch", "k", "t", "p", "h")
KO_VOWEL = ("a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae",
            "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i")
KO_TAIL = ("", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l",
           "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p",
           "t")
KO_MOVE = ("", "g", "kk", "ks", "n", "nj", "n", "d", "r", "lg", "lm", "lb",
           "ls", "lt", "lp", "r", "m", "b", "ps", "s", "ss", "ng", "j", "ch",
           "k", "t", "p", "")
KO_BLEND = {("k", "n"): ("ng", "n"), ("k", "m"): ("ng", "m"),
            ("k", "r"): ("ng", "n"), ("n", "r"): ("l", "l"),
            ("l", "n"): ("l", "l"), ("l", "r"): ("l", "l"),
            ("p", "n"): ("m", "n"), ("p", "m"): ("m", "m"),
            ("p", "r"): ("m", "n"), ("t", "n"): ("n", "n"),
            ("t", "m"): ("n", "m"), ("t", "r"): ("n", "n"),
            ("ng", "r"): ("ng", "n"), ("m", "r"): ("m", "n")}
KO_ASPIRATE = {"g": "k", "d": "t", "j": "ch", "b": "p"}


def _ko_blocks(text: str) -> list[tuple]:
    """Each character with its (lead, vowel, tail), or None if it is not one."""
    out = []
    for ch in text:
        i = ord(ch) - 0xAC00
        out.append((ch, (i // 588, (i % 588) // 28, i % 28)
                    if 0 <= i < 11172 else None))
    return out


def hangul_pieces(text: str) -> list[str]:
    """Revised Romanization, one string per character of `text`.

    Per character rather than per line because a reading has to be drawable
    over the block it belongs to, and because the timed pieces of a Korean
    lyric are usually single blocks -- so this is the shape both callers want
    and `hangul_reading` is the join of it.

    Korean is the one script here that needs no dictionary. Hangul is an
    alphabet written in syllable blocks, so a reading is the letters plus the
    rules for what happens where two of them meet -- which is why this is
    fifty lines where the Japanese reading is a package.

    The sound changes it does are the ones a reader would hear: a final
    sliding onto a following ㅇ (한국어 hangugeo), assimilation across a
    boundary (신라 silla, 백마 baengma, 왕십리 wangsimni), and ㅎ aspirating
    what it touches (좋고 joko, 놓다 nota). Checked against the thirteen
    worked examples the standard itself gives.

    What it does NOT do is palatalisation (같이 comes out gati where a Korean
    reads gachi) or the tensing a native compound puts in without writing it,
    because both need to know where the word boundaries are and nothing here
    does. A source that ships its own romanisation still wins; this is for the
    songs where none does.
    """
    parts = _ko_blocks(text)
    out = [""] * len(parts)
    carried = ""
    for n, (ch, jamo) in enumerate(parts):
        if jamo is None:
            out[n] = ch
            carried = ""
            continue
        lead, vowel, tail = jamo
        nxt = parts[n + 1][1] if n + 1 < len(parts) else None
        head = carried or KO_LEAD[lead]
        carried = ""
        prev = parts[n - 1][1] if n else None
        if prev is not None and prev[2] == 27 and head in KO_ASPIRATE:
            head = KO_ASPIRATE[head]
        out[n] = head + KO_VOWEL[vowel]
        if not tail:
            continue
        if nxt is None:
            out[n] += KO_TAIL[tail]
            continue
        nlead = nxt[0]
        if nlead == 11:
            move = KO_MOVE[tail]
            if len(move) > 1 and KO_TAIL[tail] == move[:1]:
                out[n] += move[:1]
                carried = move[1:]
            else:
                carried = move
            continue
        if nlead == 18:
            out[n] += KO_TAIL[tail]
            continue
        if tail == 27:
            if KO_LEAD[nlead] not in KO_ASPIRATE:
                out[n] += "t"
            continue
        blend = KO_BLEND.get((KO_TAIL[tail], KO_LEAD[nlead]))
        if blend is None:
            out[n] += KO_TAIL[tail]
        else:
            out[n] += blend[0]
            carried = blend[1]
    return out


def hangul_reading(text: str) -> str:
    """`hangul_pieces` as one string -- the whole line in Latin letters."""
    return "".join(hangul_pieces(text)) if text else ""


_PINYIN = None


def _pypinyin():
    """pypinyin if it is installed, else None -- optional, like pykakasi.

    Han characters cannot be read one at a time: 行 is xíng in 银行 and háng
    in 一行, 了 is le or liǎo, and the difference is the word around them. That
    is a segmenter and a dictionary, which is a package rather than a table,
    and a person who never plays a Chinese song should not have to carry it.
    """
    global _PINYIN
    if _PINYIN is None:
        try:
            from pypinyin import Style, pinyin
            _PINYIN = (pinyin, Style)
        except Exception:
            _PINYIN = False
    return _PINYIN or None


def pinyin_reading(text: str, tones: bool = True) -> list[str]:
    """Pinyin per CHARACTER, one entry each, with the line for context.

    Handed the whole line, because that is the only way the polyphones come
    out right, and handed back per character so a reading can be set over
    exactly the character it belongs to. Anything that is not Han comes back
    as itself.
    """
    got = _pypinyin()
    if not got or not text:
        return [""] * len(text)
    pinyin, Style = got
    try:
        rows = pinyin(text, style=Style.TONE if tones else Style.NORMAL,
                      errors=lambda run: [run])
    except Exception:
        return [""] * len(text)
    out: list[str] = []
    for row in rows:
        piece = (row[0] if row else "") or ""
        if len(out) < len(text) and HAN.match(text[len(out)]):
            out.append(piece)
        else:
            out.extend([""] * max(1, len(piece)))
    return (out + [""] * len(text))[:len(text)]


def script_of(text, japanese: bool = False) -> str:
    """Which romanisation this text wants: "ja", "zh", "ko", or "".

    Hangul and kana say whose script they are outright. Han characters do not
    -- they are shared -- so `japanese` carries what the document as a whole
    said, which is the only place that question can be answered: a Japanese
    lyric has lines that are all kanji, and one of those is not a Chinese
    song.
    """
    text = str(text or "")
    if HANGUL.search(text):
        return "ko"
    if KANA.search(text):
        return "ja"
    if HAN.search(text):
        return "ja" if japanese else "zh"
    if CYRILLIC.search(text):
        return "ru"
    return ""


def readings(texts: list[str], japanese: bool = False):
    """Romanisation per piece for a line in any script this can read.

    The same shape `line_readings` returns -- (readings, owner) -- because it
    IS `line_readings` where the line is Japanese. Korean and Chinese have no
    equivalent of its owner index: a reading there belongs to the character,
    so every piece answers for itself and owner stays -1, which is what tells
    `roman_of` there is no word grouping to carry over.

    A mixed line is read a run at a time. Songs that put an English chorus on
    a Korean verse are ordinary, and so are Japanese lines with a Chinese
    place name in them; asking the LINE what language it is gets one of them
    wrong, so the question is asked of each run of one script instead.
    """
    n = len(texts)
    if not n:
        return [], []
    kinds = {script_of(t, japanese) for t in texts if str(t or "").strip()}
    if kinds <= {"ja", ""} and "ja" in kinds:
        return line_readings(texts)
    out, owner = [""] * n, [-1] * n
    for kind, run in _runs(texts, japanese):
        if not kind:
            continue
        if kind == "ja":
            got, _own = line_readings([texts[i] for i in run])
            for i, r in zip(run, got):
                out[i] = r
            continue
        if kind == "ru":
            for i in run:
                out[i] = cyrillic_reading(texts[i])
            continue
        joined = "".join(canon(texts[i]) for i in run)
        marks = (_ko_spans(joined) if kind == "ko" else
                 [(k, k + 1, r) for k, r in enumerate(pinyin_reading(joined))
                  if r and HAN.match(joined[k])])
        at = 0
        for i in run:
            here = len(canon(texts[i]))
            got = [r for a, _b, r in marks if at <= a < at + here]
            out[i] = " ".join(got) if kind == "zh" else "".join(got)
            at += here
    return out, owner


def _runs(texts: list[str], japanese: bool = False):
    """The pieces of a line grouped into runs of one script, in order.

    A mixed line is read a run at a time. Songs that put an English chorus on
    a Korean verse are ordinary, and so are Japanese lines with a Chinese
    place name in them; asking the LINE what language it is gets one of them
    wrong, so the question is asked of each run instead. A piece with no
    script of its own -- a comma, a space, "baby" -- joins the run it is
    inside rather than breaking it in two.
    """
    out: list[tuple[str, list[int]]] = []
    for i, t in enumerate(texts):
        kind = script_of(t, japanese)
        if out and (kind == out[-1][0] or (not kind and out[-1][0])):
            out[-1][1].append(i)
        else:
            out.append((kind, [i]))
    return out


def read_line(text: str, japanese: bool = False) -> str:
    """A whole line's romanisation derived from its text, or "".

    For lines with no syllables to hang a reading on. Read a word -- a run
    between spaces -- at a time through `readings`, so each script is read
    the way it is on a syllable-timed line and kanji keep enough of their
    neighbours to be read in context. A word nothing here can read is kept
    as it is, which is what a Latin word in a Korean line wants.
    """
    words = canon(str(text or "")).split()
    if not words or not can_read(words, japanese):
        return ""
    derived, _owner = readings(words, japanese)
    got = " ".join(
        ((r or "").strip() + re.search(r"[^\w]*$", w).group()) if (r or "").strip()
        and not re.search(r"[^\w]$", r.strip()) else ((r or "").strip() or w)
        for w, r in zip(words, derived))
    got = re.sub(r"\s+", " ", got).strip()
    return "" if not got or SCRIPTED.search(got) else got


def can_read(texts: list[str], japanese: bool = False) -> bool:
    """Whether this machine can derive a reading for anything in `texts`.

    Korean always; Japanese and Chinese only where their package is
    installed, because neither can be read without a dictionary. Asked before
    a line is romanised at all, so a song in a script nothing here reads is
    left alone instead of being drawn a second time in the same letters.
    """
    for kind, _run in _runs(texts, japanese):
        if kind in ("ko", "ru"):
            return True
        if kind == "ja" and _kakasi():
            return True
        if kind == "zh" and _pypinyin():
            return True
    return False


def ruby(texts: list[str], japanese: bool = False):
    """Readings to set OVER the text, per piece, for every script that has one.

    Furigana is the Japanese case and `furigana` is still the thing that does
    it. This is the same answer for the other two: pinyin over the hanzi it
    reads, Revised Romanization over a Hangul block. Same shape -- per piece,
    a list of (first character, last character + 1, reading) -- so the view
    that already draws kana over kanji draws these without knowing which
    script it is looking at.

    Read a RUN at a time, not a piece at a time, for the reason the
    romanisation is: the pieces handed in here are whatever the wrapper laid
    out, which on a syllable-timed lyric is one character each, and 적 and 인
    read apart come out "jeok in" where 적인 together is "jeo gin". Cutting
    the run's reading back up per character puts the liaison in the right
    place and keeps the ruby saying the same thing as the row underneath.

    Hangul is annotated whole-block: a block IS a syllable, so there is
    nothing to line up inside it, and a reading over each one is what a reader
    who does not have the alphabet actually needs.
    """
    out: list[list[tuple[int, int, str]]] = [[] for _ in texts]
    kinds = {script_of(t, japanese) for t in texts if str(t or "").strip()}
    if kinds <= {"ja", ""}:
        return furigana(texts)
    ja = furigana(texts) if "ja" in kinds else None
    for kind, run in _runs(texts, japanese):
        if kind == "ja":
            for i in run:
                out[i] = ja[i] if ja else []
            continue
        if kind not in ("zh", "ko"):
            continue
        joined = "".join(str(texts[i] or "") for i in run)
        marks = (_ko_spans(joined) if kind == "ko" else
                 [(k, k + 1, r) for k, r in enumerate(pinyin_reading(joined))
                  if r and HAN.match(joined[k])])
        at = 0
        for i in run:
            here = len(str(texts[i] or ""))
            out[i] = [(a - at, b - at, r) for a, b, r in marks
                      if at <= a < at + here]
            at += here
    return out


def _ko_spans(text: str) -> list[tuple[int, int, str]]:
    """One reading per Hangul block, the whole piece read for context."""
    return [(k, k + 1, r) for k, r in enumerate(hangul_pieces(text))
            if r and HANGUL.match(text[k])]


def geminate(cur: str, nxt: str) -> tuple[str, str] | None:
    """っ is a gemination mark, not the syllable "tsu".

    The source romanises 立っ as "tatsu" and 思いっ as "omoi tsu"; both should
    end in a doubled consonant carried onto the next syllable -- "tat"+"ta",
    "omoik"+"kiri". Hepburn doubles ch as t, so まっちゃ is "matcha".

    Returns the corrected pair, because the doubling may already be there.
    Where a source spells one syllable なっ instead of な + っ, the reading is
    cut into "nat" / "tte" and BOTH halves carry the consonant; adding a third
    spells "nattte". So this normalises to exactly one, wherever it sits.
    """
    base = re.sub(r"(tsu|tu)\s*$", "", cur).rstrip()
    if not base or not nxt:
        return None
    head = nxt.lstrip()
    if not head or not head[0].isalpha() or head[0].lower() in "aeiou":
        return None
    dbl = "t" if head[:2].lower() == "ch" else head[0].lower()
    if head[:2].lower() == dbl * 2:
        head = head[1:]
    if base[-1:].lower() != dbl:
        base += dbl
    return base, head


BG_LEAD = 0.4


def timeline(body, split: str = "none", threshold: float = 0.7) -> list[dict]:
    """Cache entry -> [{start, end, text, syls:[(start,end,text)]}] sorted by start."""
    doc = payload(body)
    items = next(
        (doc[k] for k in ("Content", "Lines") if isinstance(doc.get(k), list) and doc[k]), []
    )
    japanese = any(KANA.search(line_text(i) or "") for i in items)
    def syls_of(group, key="Text"):
        s = []
        timed = [y for y in (group or {}).get("Syllables") or []
                 if isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float))]
        for i, y in enumerate(timed):
            raw = y.get(key) or y.get("Text", "")
            nxt = timed[i + 1] if i + 1 < len(timed) else {}
            s.append(
                (
                    float(y["StartTime"]),
                    float(y.get("EndTime", y["StartTime"])),
                    _trim(raw),
                    bool(y.get("IsPartOfWord"))
                    and not word_ends(raw, nxt.get(key) or nxt.get("Text", "")),
                )
            )
        if key != "Text":
            return s
        return split_syllables(s, split, threshold) if s and split != "none" else s

    def roman_of(group):
        """Per-syllable romanisation, when the source carries one. Same timings
        as the original, so it can be filled in sync with it."""
        syls = [y for y in (group or {}).get("Syllables") or []
                if isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float))]
        if not any(SCRIPTED.search(y.get("Text", "") or "") for y in syls):
            return []
        if strays_only(syllables_text(syls)):
            return []
        texts = [y.get("Text", "") or ""  for y in syls]
        if not any(y.get("TransliteratedText") for y in syls):
            if not (doc.get("HasTransliterations") or can_read(texts, japanese)):
                return []
        derived, owner = readings(texts, japanese)

        def failed(y):
            """The source gave nothing usable for this syllable."""
            r = (y.get("TransliteratedText") or "").strip()
            return not r or bool(SCRIPTED.search(r))

        broken = {owner[i] for i, y in enumerate(syls) if failed(y) and owner[i] >= 0}
        rows = []
        for i, ((s, e, _t, _p), y) in enumerate(zip(syls_of(group, "TransliteratedText"), syls)):
            rom = (y.get("TransliteratedText") or "").strip()
            if failed(y) or owner[i] in broken:
                rom = (derived[i] or "").strip() or rom or canon(texts[i])
            rows.append([s, e, rom, False])
        for i in range(len(rows) - 1):
            # Cyrillic is read letter for letter, so a word the source split
            # into syllables is still one word once it is in Latin letters.
            same = ((owner[i] >= 0 and owner[i] == owner[i + 1])
                    or (CYRILLIC.search(texts[i]) and CYRILLIC.search(texts[i + 1])))
            if (same
                    and syls[i].get("IsPartOfWord")
                    and not word_ends(syls[i].get("Text", ""),
                                      syls[i + 1].get("Text", ""))):
                rows[i][3] = True
        for i in range(len(rows) - 1):
            if SOKUON.search(syls[i].get("Text", "") or ""):
                joined = geminate(rows[i][2], rows[i + 1][2])
                if joined:
                    rows[i][2], rows[i + 1][2] = joined
                    rows[i][3] = True
        if all(SCRIPTED.search(r[2] or "") or not (r[2] or "").strip()
               for r in rows):
            return []
        return [tuple(r) for r in rows]

    def roman_text(group, item=None):
        """The line's romanisation, where the line is in a script that has one.

        The document is not believed about this. Spicy Lyrics files a
        TransliteratedText against plenty of lines that are already in the
        Latin alphabet -- femtanyl's LOVESICK, CANNIBAL! carries "Go, go, go.
        go!" as the "romanisation" of "Go, go, go!" -- and with Romanisation
        set to "under" that draws a second row beneath a line that needed
        nothing doing to it, in the small indented type an ad-lib is drawn in.

        roman_of already refuses to romanise a line with nothing foreign in
        it. This is the same refusal, one level up, where it was missing.
        """
        raw = syllables_text((group or {}).get("Syllables") or []) or str(
            (item or {}).get("Text") or "" if isinstance(item, dict) else "")
        if not foreign(raw) or strays_only(raw):
            return ""
        for src in (group, item):
            if isinstance(src, dict) and isinstance(src.get("TransliteratedText"), str):
                got = src["TransliteratedText"]
                if got.strip() and not SCRIPTED.search(got):
                    return got
        got = "".join(y[2] + ("" if y[3] else " ")
                      for y in roman_of(group) if y[2]).strip()
        # A line-timed or static document has no syllables to read, which
        # left every LRC, NetEase and QQ line of a Chinese or Korean song
        # without a romanisation unless the source shipped one: read the
        # line's own text instead.
        return got or read_line(raw, japanese)

    def first_sung(g):
        """When a group's own words start, which is not always when it begins.

        The counterpart to last_sung, and the rarer of the two: measured over
        the 527 documents in lyrics/, 114 of 25,994 lines have a first
        syllable that starts after the line says it does, by 0.83s at the
        median and by as much as 6.45s. Those are lines that light up, scroll
        into place and then sit there with nothing being sung in them.

        A line is its words. Where they say when it starts, they are believed.
        """
        starts = [y.get("StartTime") for y in (g or {}).get("Syllables") or []
                  if isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float))]
        return min(starts) if starts else None

    def last_sung(g):
        """When a group's own words stop, which is not when it ends.

        A line's EndTime is routinely stretched over the ad-libs written
        inside it -- Stronger pads every one of them out to the end of its
        backing vocal, three seconds after the singer has finished the line
        and a second after the NEXT line has started. Anything asking "is
        this line done" has to ask the syllables, not the group.
        """
        ends = [y.get("EndTime") for y in (g or {}).get("Syllables") or []
                if isinstance(y, dict) and isinstance(y.get("EndTime"), (int, float))]
        return max(ends) if ends else None

    def bounds(group, said_start, said_end):
        """A line runs from its first word to its last one.

        Both ends are the group's own syllables wherever it has any, and the
        times the document states only where it has none -- a plain LRC line,
        or the 668 lines in lyrics/ that carry no syllable timing at all.

        The stated times are not a second opinion to be reconciled with the
        words; they are the line's packaging. 4.6% of the lines measured
        there end somewhere other than their last syllable, most of them
        LATER, because a source pads a line out over the ad-lib written
        inside it -- Stronger ends every line a second after the next one has
        started. Reading those as the line still being sung is what kept a
        finished line lit, and max(stated, sung) could never take it back.
        """
        begin, stop = first_sung(group), last_sung(group)
        if begin is None and isinstance(said_start, (int, float)):
            begin = float(said_start)
        if stop is None and isinstance(said_end, (int, float)):
            stop = float(said_end)
        return begin, stop

    out = []
    for group, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        lead = item.get("Lead") if isinstance(item.get("Lead"), dict) else None
        begin, stop = bounds(lead, line_start(item), (lead or item).get("EndTime"))
        here = len(out)
        out.append(
            {
                "start": begin,
                "end": stop,
                "text": line_text(item),
                "syls": syls_of(lead),
                "syls_roman": roman_of(lead),
                "text_roman": roman_text(lead, item),
                "opposite": bool(item.get("OppositeAligned")),
                "background": False,
                "group": group,
                "sung": last_sung(lead),
            }
        )
        bg = item.get("Background")
        lead_start = out[here]["start"]
        for g in bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else []):
            if not isinstance(g, dict):
                continue
            gs, ge = bounds(g, g.get("StartTime"), g.get("EndTime"))
            text = g["Text"] if isinstance(g.get("Text"), str) else syllables_text(
                g.get("Syllables")
            )
            if not text.strip():
                continue
            at = len(out)
            if (isinstance(gs, (int, float)) and lead_start is not None
                    and float(gs) < lead_start - BG_LEAD):
                at = here
                here += 1
            out.insert(
                at,
                {
                    "start": gs,
                    "end": ge,
                    "text": text,
                    "syls": syls_of(g),
                    "syls_roman": roman_of(g),
                    "text_roman": roman_text(g, g),
                    "opposite": bool(item.get("OppositeAligned")),
                    "background": True,
                    "group": group,
                    "sung": last_sung(g),
                }
            )
    synced = [ln for ln in out if ln["start"] is not None]
    if not synced:
        return out
    return synced


def last_moment(ln: dict):
    """The last moment anything in this line is still being sung.

    For a line `timeline` built this is already its end -- `bounds` settled
    that question there, out of the syllables -- and the two readings below
    agree. It stays because not every line dict comes from there: the window
    makes its own for the instrumental dots, and a caller can hand in
    anything with a `syls` in it.

    Both directions the stated end used to be wrong in are worth keeping
    written down, because they are why `bounds` exists. It is routinely
    LATER: a source pads a line out over the ad-lib written inside it -- see
    _sung_to, which is that direction. And it can be EARLIER: an ad-lib
    holding two voices at once is written as one group, so its syllables are
    not in time order, and the group's end tends to follow the LAST of them
    rather than the one that ends last. Marshmello's FRIENDS has it at 3:01:
    "I made it very clear;" runs to 3:05.416 and four "Ooh"s are written
    after it, the last ending at 3:04.729, which is what the group calls its
    end. Believing that stops the whole ad-lib while a word of it is still
    being sung.

    So the words decide, as they do everywhere else here: the line is going
    until the last of them is done, however the group was written.
    """
    end, sung = ln.get("end"), ln.get("sung")
    if sung is None:
        ends = [y[1] for y in (ln.get("syls") or [])
                if isinstance(y, (tuple, list)) and len(y) > 1
                and isinstance(y[1], (int, float))]
        sung = max(ends) if ends else None
    if end is None:
        return sung
    return end if sung is None else max(end, sung)


def active_indices(lines: list[dict], pos: float) -> list[int]:
    """Every line covering pos. Lines overlap (duets, backing vocals), so more
    than one can be live at once -- returning only the newest dropped the other."""
    live = []
    for i, ln in enumerate(lines):
        if ln["start"] is None or ln["start"] > pos:
            continue
        until = last_moment(ln)
        if until is None or pos <= until:
            live.append(i)
    return live


def _sung_to(ln: dict):
    """When this line stops being sung, which is now when it ends.

    It was not always: a line's end used to be whatever the source stated,
    and that is stretched over the ad-libs written inside it wherever the
    source felt like it -- every line in Stronger ends a second after the
    line AFTER it has started, because that is when its backing vocal stops.
    `bounds` settles it at the last syllable when the line is built, so for
    anything out of `timeline` the two are the same number. The preference is
    left in for line dicts made elsewhere, and because it says which of the
    two is the measurement.
    """
    got = ln.get("sung")
    return ln.get("end") if got is None else got


def _finished(ln: dict, pos: float, nxt: dict | None = None) -> bool:
    """Whether the singing of `ln` is over at `pos`.

    A line with no end of its own -- some line-timed sources give none -- is
    over when the next line has begun, which is the only statement the
    document makes about it.
    """
    if ln.get("dots") or not str(ln.get("text") or "").strip():
        return True
    e = _sung_to(ln)
    if e is not None:
        return pos >= e
    s = (nxt or {}).get("start")
    return s is not None and pos >= s


def focus_index(lines: list[dict], pos: float, lead: float = 0.0) -> int:
    """The line the view should sit on at `pos`.

    Walked forward from the top rather than taken as "the newest thing
    sounding", because whether the view has earned the next line is a question
    about the line it is leaving. It moves down from a line only when

      * that line is DONE -- everything it had to sing has been sung -- or
      * that line outlasts the one after it, which makes the next line
        something sung across the tail of this one (the second voice of a
        trade, a line answered before it is finished). Following it is the
        whole point; it will be over before this one is.

    and never otherwise, so two lines overlapping by a word no longer drag the
    view down to the second one while the first is still being sung.

    An ad-lib never takes the focus itself -- it is drawn beside the line it
    belongs to, not read on to -- but it does carry the view to that line. A
    chorus answered by its own backing vocals sounds the ad-lib first and the
    line a beat later, and a view that waited for the line would be showing
    the wrong part of the song while something in it was being sung. So an
    ad-lib sounding while its line has not started is enough to step down to
    that line, on the same terms as everything else here: only once the line
    being left has finished.

    `lead` moves the view early: with it set, the view may step down to a line
    that has not started yet, but only within `lead` seconds of its start and
    only once the line before it has finished singing. A line still sounding
    is never scrolled away from to make room for the next one.
    """
    real = [i for i, ln in enumerate(lines)
            if not ln.get("background") and ln.get("start") is not None]
    if not real:
        started = [i for i, ln in enumerate(lines)
                   if ln.get("start") is not None and ln["start"] <= pos]
        return started[-1] if started else (0 if lines else -1)
    opened: dict = {}
    for ln in lines:
        g, s = ln.get("group"), ln.get("start")
        if ln.get("background") and g is not None and s is not None:
            opened[g] = min(s, opened.get(g, s))
    at = 0
    while at + 1 < len(real):
        here, then = lines[real[at]], lines[real[at + 1]]
        done = _finished(here, pos, then)
        if then["start"] > pos:
            early = lead > 0.0 and then["start"] - pos <= lead
            adlib = opened.get(then.get("group"))
            if not (done and (early or (adlib is not None and adlib <= pos))):
                break
        elif not (done or _outlasts(here, then)):
            break
        at += 1
    return real[at]


def _outlasts(here: dict, then: dict) -> bool:
    """Whether `here` is still being sung after `then` has finished.

    Both measured by their words, for the same reason: an ad-lib hanging off
    the end of a line is not the line still going.
    """
    a, b = _sung_to(here), _sung_to(then)
    return a is not None and b is not None and a > b


def active_index(lines: list[dict], pos: float) -> int:
    """Index of the line covering pos, or -1 before the first line."""
    idx = -1
    for i, ln in enumerate(lines):
        if ln["start"] is not None and ln["start"] <= pos:
            idx = i
        else:
            break
    if idx >= 0:
        end = lines[idx]["end"]
        if end is not None and pos > end and idx + 1 < len(lines):
            nxt = lines[idx + 1]["start"]
            if nxt is not None and pos < nxt:
                return idx
    return idx


def karaoke(line: dict, pos: float, color: bool) -> str:
    """Render a line with syllables sung-so-far highlighted."""
    if not line["syls"] or not color:
        return line["text"]
    sung, unsung, reset = "\033[1;36m", "\033[2m", "\033[0m"
    out = []
    for i, (s, e, txt, part) in enumerate(line["syls"]):
        out.append((sung if pos >= s else unsung) + txt + reset)
        if i < len(line["syls"]) - 1 and not part:
            out.append(" ")
    return "".join(out)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def payload(body):
    """The lyrics document itself.

    The API hands one over already unwrapped, and so does everything that
    passes one around inside this program. What this still unwraps is the old
    Spicetify cache envelope -- {ExpiresAt, CacheVersion, Content: {...}} --
    because snapshots taken while that was the source are still on disk and
    are still read back by sync/ and the benchmarks.
    """
    if isinstance(body, dict) and isinstance(body.get("Content"), dict):
        return body["Content"]
    return body if isinstance(body, dict) else {}


ZWSP = "\u200b"


_BETWEEN = re.compile(r"(?<=[^\s" + ZWSP + r"])" + ZWSP + r"(?=[^\s" + ZWSP + r"])")


def unzwsp(text, spaced: bool = False) -> str:
    """`text` with the zero-width spaces taken out.

    They come in with several sources -- Spicy Lyrics' own cache writes
    "go! \u200b", NetEase and QQ Music mark word breaks with them -- and they
    are drawn as nothing, but they still hold a place in the string: they
    defeat a word match, and they ride out into every file written from here.

    `spaced` is for text that is already written with spaces in it: a whole
    line. There a zero-width space standing between two letters is the only
    thing holding two words apart, so a real space takes its place. Within a
    single syllable it is the opposite -- sources write it as GLUE, "my-" then
    "\u200b\u200bself", "run-" then "\u200bn\u200bing" -- and a space there
    would cut a word in half. So the substitution is asked for, never assumed.

    Never between Chinese or Japanese characters either, which are written
    with no space between words at all. There the mark IS the whole boundary,
    and widening it into a space would respell the line.
    """
    got = str(text or "")
    if ZWSP not in got:
        return got
    if not spaced:
        return got.replace(ZWSP, "")

    def gap(m):
        return "" if (CJK.match(got[m.start() - 1])
                      and CJK.match(got[m.end()])) else " "

    return _BETWEEN.sub(gap, got).replace(ZWSP, "")


def _trim(text) -> str:
    """A syllable's text, without the whitespace or the invisible characters."""
    got = unzwsp(text)
    return got.strip() or got


def unzwsp_body(body):
    """A whole document with every zero-width space gone from it.

    Plain removal, never the substitution `unzwsp(spaced=True)` makes, and
    that is the difference worth stating: in a document from Apple Music or
    NetEase a zero-width space standing between two letters is the only thing
    holding two words apart, so widening it into a real space is the only way
    to read the line. Spicy Lyrics' own copy is not that. It writes them in
    itself, over a line that already spells its gaps with real spaces and with
    IsPartOfWord, so there is no boundary in one to preserve -- a lumped
    "or\u200bam" is a mark inside one word as far as anything here can tell,
    and it comes back "oram".

    Every string in the document, not only the syllables' Text. A zero-width
    space in a title or a songwriter's name rides out into an export exactly
    as far as one in a word does, and it is no more anybody's spelling.

    The document itself comes back where there was nothing to take out, rather
    than a copy of it that says the same thing. The lyric window decides
    whether an answer is NEW by asking whether it is the document it already
    has, so rebuilding an untouched one would make every redraw look like a
    fresh lyric; see LyricsView.on_lyrics, and lyric_sources.unlump, which
    has always worked this way.
    """
    if isinstance(body, str):
        return body.replace(ZWSP, "") if ZWSP in body else body
    if isinstance(body, dict):
        out, hit = {}, False
        for k, v in body.items():
            got = unzwsp_body(v)
            hit = hit or got is not v
            out[k] = got
        return out if hit else body
    if isinstance(body, list):
        rows = [unzwsp_body(v) for v in body]
        return rows if any(a is not b for a, b in zip(rows, body)) else body
    return body


SEPS = " \t\r\n\f\v" + ZWSP


def word_ends(text, nxt) -> bool:
    """Whether the word ends after `text`, whatever IsPartOfWord says.

    Some sources carry the word break in the syllable text instead of in the
    flag: Apple Music writes "I \u200b", "saw \u200b", "the \u200b", "signs"
    with every one of them marked part-of-word, and amll-ttml-db has lines
    where the space simply rides along at the end of a span. Both spell the
    line correctly as long as the text is kept whole -- which is why the TTML
    those documents export reads perfectly, and why reading that export back
    puts the same line on screen with its spaces.

    The player does not keep the text whole. It trims each syllable, because
    a syllable's own padding would otherwise be drawn twice over the space the
    flag already asks for, and the trimmed text then has nothing left to say
    the word ended -- so "I saw the signs" was drawn "Isawthesigns".

    So the separator is read before it is trimmed away, from either side of
    the join: a trailing one on this syllable or a leading one on the next.
    Only where both sides have something left afterwards -- a syllable that is
    nothing but a separator is padding, not a word.
    """
    text, nxt = str(text or ""), str(nxt or "")
    if not text.strip(SEPS) or not nxt.strip(SEPS):
        return False
    return text != text.rstrip(SEPS) or nxt != nxt.lstrip(SEPS)


def syllables_text(syls) -> str:
    """The words a run of syllables spells.

    The space between two words is added HERE, from IsPartOfWord -- so a
    syllable that also carries one of its own inside its text spells the line
    with a double space in it. Plenty of documents do carry one: Spicy
    Lyrics' own cache writes "The " where the flag already says the word
    ends, and every one of those lines was drawn with a gap twice as wide as
    the rest. Only the EDGES are trimmed; a syllable holding two words really
    does have a space in the middle of it.
    """
    out = ""
    for s in syls or []:
        if not isinstance(s, dict):
            continue
        text = str(s.get("Text", ""))
        out += text if s.get("IsPartOfWord") else _trim(text) + " "
    return out.strip()


def line_text(item, background: bool = False) -> str:
    """The words a line spells, from its own Text or from its syllables.

    A line that carries its own Text is written as it stands, minus anything
    invisible: line-timed sources hand back whole lines, and NetEase's are
    full of zero-width spaces where a word ends -- which is a boundary the
    line already spells with a real space, so it says nothing here and only
    rides along into whatever this line is written into.
    """
    if not isinstance(item, dict):
        return unzwsp(item, True).strip()
    text = item.get("Text")
    if isinstance(text, str):
        text = unzwsp(text, True).strip()
    else:
        lead = item.get("Lead")
        text = syllables_text(lead.get("Syllables") if isinstance(lead, dict) else None)
    if background:
        bg = item.get("Background")
        parts = []
        for b in bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else []):
            t = (unzwsp(b["Text"], True).strip() if isinstance(b.get("Text"), str)
                 else syllables_text(b.get("Syllables")))
            if t:
                parts.append(t)
        if parts:
            text = (text + " " + " ".join(f"({p})" for p in parts)).strip()
    return text


def line_start(item) -> float | None:
    """Start time in seconds, or None for unsynced lines."""
    for src in (item, item.get("Lead") if isinstance(item, dict) else None):
        if isinstance(src, dict) and isinstance(src.get("StartTime"), (int, float)):
            return float(src["StartTime"])
    return None


def ts(sec: float, brackets: str = "[]") -> str:
    """Seconds -> [mm:ss.xx] (line tag) or <mm:ss.xx> (word tag)."""
    ms = int(round(sec * 1000))
    return f"{brackets[0]}{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000 // 10:02d}{brackets[1]}"


def syllable_group(group) -> str:
    """Render one Lead/Background group as inline <ts>-tagged syllables (A2)."""
    syls = [s for s in (group or {}).get("Syllables") or [] if isinstance(s, dict)]
    out = []
    for i, s in enumerate(syls):
        start = s.get("StartTime")
        tag = ts(float(start), "<>") if isinstance(start, (int, float)) else ""
        raw = s.get("Text", "")
        nxt = syls[i + 1].get("Text", "") if i + 1 < len(syls) else ""
        ends = not s.get("IsPartOfWord") or word_ends(raw, nxt)
        out.append(tag + _trim(raw) + (" " if ends else ""))
    body = "".join(out).rstrip()
    end = (group or {}).get("EndTime")
    return body + (ts(float(end), "<>") if isinstance(end, (int, float)) else "")


def elrc_line(item, background: bool = False) -> str:
    """Enhanced LRC (A2): [line]<syl>text<syl>text... Falls back to line-level."""
    start = line_start(item)
    head = ts(start) if start is not None else ""
    lead = item.get("Lead") if isinstance(item, dict) else None
    if isinstance(lead, dict) and lead.get("Syllables"):
        body = syllable_group(lead)
    else:
        body = line_text(item)
    if background:
        bg = item.get("Background") if isinstance(item, dict) else None
        groups = bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else [])
        extra = [syllable_group(g) if g.get("Syllables") else g.get("Text", "") for g in groups]
        extra = [e for e in extra if e]
        if extra:
            body = body + " " + " ".join(f"({e})" for e in extra)
    return head + body


"""
TTML output, matching the Apple Music / AMLL convention found in ~/Downloads:

  <tt xmlns=... xmlns:ttm=... xmlns:itunes=... itunes:timing="Word|Line|None">
    <head><metadata>
      <ttm:agent type="person" xml:id="v1"/>
      <iTunesMetadata xmlns="..."><songwriters>...</songwriters></iTunesMetadata>
    </metadata></head>
    <body dur="MM:SS.mmm"><div begin=".." end="..">
      <p begin=".." end=".." ttm:agent="v1" itunes:key="L1">...</p>
    </div></body>
  </tt>

  Word : <p> holds one <span begin end> per syllable.
  Line : <p> holds the line text directly.
  None : <p> per line, no timing at all.

Word boundaries are a literal space BETWEEN spans (</span> <span); syllables
inside one word are butted together (</span><span). That is exactly what
IsPartOfWord encodes. Span text itself is never padded.
"""

TTML_NS = {
    "xmlns": "http://www.w3.org/ns/ttml",
    "xmlns:ttm": "http://www.w3.org/ns/ttml#metadata",
    "xmlns:itunes": "http://music.apple.com/lyric-ttml-internal",
}
ITUNES_NS = "http://music.apple.com/lyric-ttml-internal"
AMLL_NS = "http://www.example.com/ns/amll"

LABELS = (("Title", "musicName"), ("Artist", "artists"), ("Album", "album"),
          ("SyncedBy", "ttmlAuthor"))
AMLL_LABELS = {at: key for key, at in LABELS if at != "ttmlAuthor"}


def ttml_ts(sec: float) -> str:
    """Seconds -> MM:SS.mmm, or H:MM:SS.mmm past the hour."""
    ms = int(round(float(sec) * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{msec:03d}" if h else f"{m:02d}:{s:02d}.{msec:03d}"


def _covering(item, lead, background: bool, until=None) -> dict:
    """A line's times, widened to hold every voice actually drawn inside it.

    The <p> used to be timed from the Lead alone. That was right while an
    ad-lib could only be placed inside the lead's own frames, and wrong the
    moment one could be placed after the line it answers: over 278 songs, 3135
    ad-libs ended up sounding after the <p> containing them had declared itself
    finished, by a median of 1.53s. A player lights a line and then sweeps its
    syllables; a syllable outside the line it belongs to has no reading.

    Done here rather than only on the document, so it holds for the cache's own
    documents too -- they carry the same shape and are drawn by the same code.
    """
    b, e = (lead or {}).get("StartTime"), (lead or {}).get("EndTime")
    if not isinstance(b, (int, float)):
        b = (item or {}).get("StartTime")
    if not isinstance(e, (int, float)):
        e = (item or {}).get("EndTime")
    if not background:
        return {"StartTime": b, "EndTime": e}
    own = e
    bg = item.get("Background")
    for g in (bg if isinstance(bg, list) else
              ([bg] if isinstance(bg, dict) else [])):
        if not isinstance(g, dict) or not g.get("Syllables"):
            continue
        gs, ge = g.get("StartTime"), g.get("EndTime")
        if isinstance(gs, (int, float)) and (not isinstance(b, (int, float))
                                             or gs < b):
            b = gs
        if isinstance(ge, (int, float)) and (not isinstance(e, (int, float))
                                             or ge > e):
            e = ge
    floor = own if isinstance(own, (int, float)) else None
    if (isinstance(until, (int, float)) and isinstance(e, (int, float))
            and isinstance(b, (int, float)) and until > b and e > until):
        e = until if floor is None else max(until, floor)
    return {"StartTime": b, "EndTime": e}


def _tattrs(obj) -> str:
    b, e = (obj or {}).get("StartTime"), (obj or {}).get("EndTime")
    out = ""
    if isinstance(b, (int, float)):
        out += f' begin="{ttml_ts(b)}"'
    if isinstance(e, (int, float)):
        out += f' end="{ttml_ts(e)}"'
    return out


def _spans(group) -> str:
    """Syllables -> <span> run, spaced per IsPartOfWord.

    The text is written trimmed, because a syllable's own padding would draw
    twice over the gap the flag already asks for -- and because the invisible
    half of that padding would otherwise be copied into every document written
    out of here. `word_ends` reads the break out of the padding first, so a
    source that spells the gap in the text instead of the flag still exports
    with its words apart.
    """
    syls = [s for s in (group or {}).get("Syllables") or [] if isinstance(s, dict)]
    parts = []
    for i, s in enumerate(syls):
        raw = s.get("Text", "")
        nxt = syls[i + 1].get("Text", "") if i + 1 < len(syls) else ""
        parts.append(f"<span{_tattrs(s)}>{escape(_trim(raw))}</span>")
        if i < len(syls) - 1 and (not s.get("IsPartOfWord") or word_ends(raw, nxt)):
            parts.append(" ")
    return "".join(parts)


def _groups(bg) -> list:
    """A line's Background, however many ways it was written."""
    if isinstance(bg, list):
        return [g for g in bg if isinstance(g, dict)]
    return [bg] if isinstance(bg, dict) else []


def _worth_spans(group) -> bool:
    """Whether this group has anything the flat line text cannot say.

    A timing, or a word cut into pieces. Without either, spans would only be
    the whitespace between the words written a second way -- and a line-timed
    document that spelled every line out in untimed spans would no longer look
    like the line-timed document it is. With either, writing the flat text
    instead throws the work away: an unsynced lyric already cut into syllables
    came back out of a save as whole words again.
    """
    syls = [y for y in (group or {}).get("Syllables") or [] if isinstance(y, dict)]
    return any(isinstance(y.get("StartTime"), (int, float)) or y.get("IsPartOfWord")
               for y in syls)


def render_ttml(body, background: bool = True) -> str:
    doc = payload(body)
    items = next(
        (doc[k] for k in ("Content", "Lines") if isinstance(doc.get(k), list) and doc[k]), None
    )
    if items is None:
        raise ValueError(
            f"no lines in the document (Type={doc.get('Type')!r}, keys={sorted(doc)})"
        )
    typ = doc.get("Type")
    timing = {"Syllable": "Word", "Line": "Line", "Static": "None"}.get(typ, "Line")
    dual = any(i.get("OppositeAligned") for i in items if isinstance(i, dict))

    rows = []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        agent = "v2" if item.get("OppositeAligned") else "v1"
        attrs = f' ttm:agent="{agent}" itunes:key="L{n}"'
        lead = item.get("Lead") if isinstance(item.get("Lead"), dict) else None
        bg = [g for g in (_groups(item.get("Background")) if background else [])
              if g.get("Syllables") or str(g.get("Text") or "").strip()]
        nxt = items[n] if n < len(items) else None
        nlead = (nxt or {}).get("Lead") if isinstance(nxt, dict) else None
        until = (nlead or nxt or {}).get("StartTime") if isinstance(nxt, dict) else None
        times = "" if timing == "None" else _tattrs(_covering(
            item, lead, bool(background) and timing == "Word", until))
        inner = _spans(lead) if _worth_spans(lead) else escape(line_text(item))
        for g in bg:
            inside = (_spans(g) if g.get("Syllables")
                      else escape(_trim(str(g.get("Text") or ""))))
            piece = f'<span ttm:role="x-bg"{_tattrs(g)}>{inside}</span>'
            if g.get("LeadIn") and not isinstance(g.get("StartTime"), (int, float)):
                inner = piece + inner
            else:
                inner += piece
        rows.append(f"<p{times}{attrs}>{inner}</p>")

    lang = doc.get("LanguageISO2") or doc.get("Language")
    if lang:
        try:
            import language as _LANG
            said = " ".join(line_text(i) for i in items[:80]
                            if isinstance(i, dict))
            lang = _LANG.check(str(lang), said)[0] or lang
        except Exception:
            pass
    labels = "".join(
        f'<amll:meta key="{at}" value={quoteattr(_trim(str(doc.get(key))))}/>'
        for key, at in LABELS if _trim(str(doc.get(key) or "")))
    root = " ".join(f'{k}="{v}"' for k, v in TTML_NS.items())
    if labels:
        root += f' xmlns:amll="{AMLL_NS}"'
    root += f' itunes:timing="{timing}"'
    if lang:
        root += f" xml:lang={quoteattr(str(lang))}"

    agents = '<ttm:agent type="person" xml:id="v1"/>'
    if dual:
        agents += '<ttm:agent type="person" xml:id="v2"/>'
    writers = "".join(
        f"<songwriter>{escape(_trim(w))}</songwriter>"
        for w in doc.get("SongWriters") or [] if _trim(w)
    )
    meta = f'<iTunesMetadata xmlns="{ITUNES_NS}">'
    meta += f"<songwriters>{writers}</songwriters>" if writers else ""
    meta += "</iTunesMetadata>" + labels

    starts = [t for t in (line_start(i) for i in items) if t is not None]
    ends = [
        e
        for e in (
            ((i.get("Lead") or i) if isinstance(i, dict) else {}).get("EndTime") for i in items
        )
        if isinstance(e, (int, float))
    ]
    dur = doc.get("EndTime") if isinstance(doc.get("EndTime"), (int, float)) else (
        max(ends) if ends else None
    )
    body_attr = f' dur="{ttml_ts(dur)}"' if dur is not None else ""
    div_attr = ""
    if starts and ends:
        div_attr = f' begin="{ttml_ts(min(starts))}" end="{ttml_ts(max(ends))}"'

    lines = "\n".join(rows)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<tt {root}>"
        f"<head><metadata>{agents}{meta}</metadata></head>\n"
        f"<body{body_attr}><div{div_attr}>\n{lines}\n</div></body></tt>"
    )


def render(body, fmt: str, background: bool = False) -> str:
    if fmt == "json":
        return json.dumps(body, indent=2, ensure_ascii=False)
    if fmt == "ttml":
        return render_ttml(body, True)
    doc = payload(body)
    items = next(
        (doc[k] for k in ("Content", "Lines") if isinstance(doc.get(k), list) and doc[k]), None
    )
    if items is None:
        raise ValueError(
            f"no lines in the document (Type={doc.get('Type')!r}, "
            f"keys={sorted(doc)}); use --format json to inspect"
        )
    if fmt == "text":
        return "\n".join(line_text(i, background) for i in items)
    if fmt in ("lrc", "elrc"):
        rows = []
        for meta_key, tag in (("id", "id"), ("Language", "la"), ("source", "re")):
            v = doc.get(meta_key)
            if v:
                rows.append(f"[{tag}:{v}]")
        for i in items:
            if fmt == "elrc":
                rows.append(elrc_line(i, background))
            else:
                sec, txt = line_start(i), line_text(i, background)
                rows.append(txt if sec is None else ts(sec) + txt)
        return "\n".join(rows)
    raise ValueError(fmt)


# --------------------------------------------------------------------------
def _player(a):
    """A connection to the running Spotify, or None.

    Only the two commands that ask what is playing want one, and neither of
    them needs it on Linux, where the session bus answers the same question.
    Every other command here talks to the API and to the disk, so a player
    that is not running is no longer a reason to refuse to run.
    """
    try:
        from spotify_dom import connect
        return connect(a.port, a.target)
    except SystemExit:
        return None
    except Exception:                                    # noqa: BLE001
        return None


def _sources():
    """lyric_sources, imported when a command actually needs it.

    Not at the top, and it cannot be: lyric_sources imports THIS module, so
    the two would be a cycle. That is the shape of the stack rather than an
    accident -- this file is the document, its timeline and its renderers, and
    the fetching of every source including Spicy Lyrics lives over there with
    the others. The commands below are a front door onto it.
    """
    import lyric_sources
    return lyric_sources


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--target")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("keys", help="track ids fetched to this machine so far")

    k = sub.add_parser("key", help="keep an API key for next time")
    k.add_argument("value", nargs="?", help="sl_pk_... or sl_sk_... (omit to "
                                            "show where the key comes from)")

    g = sub.add_parser("get", help="lyrics for a track")
    g.add_argument("track", nargs="?", help="track id (default: currently playing)")
    g.add_argument("--format", choices=["text", "lrc", "elrc", "ttml", "json"], default="text")
    g.add_argument("--background", action="store_true", help="include backing vocals")
    g.add_argument("--refresh", action="store_true",
                   help="ask the API again even if this track is already held")
    g.add_argument("-o", "--out", help="write to file instead of stdout")

    d = sub.add_parser("dump", help="export every track held here, one file each")
    d.add_argument("outdir")
    d.add_argument("--format", choices=["text", "lrc", "elrc", "ttml", "json"], default="elrc")
    d.add_argument("--background", action="store_true")
    d.add_argument("--batch", type=int, default=100, help="entries read per page")

    w = sub.add_parser("watch", help="follow lyrics live against playback position")
    w.add_argument("--interval", type=float, default=0.15)
    w.add_argument("--karaoke", action=argparse.BooleanOptionalAction, default=True,
                   help="highlight syllables as they are sung (default: on)")
    w.add_argument("--split", choices=["none", "long", "all"], default="none",
                   help="none (default): use the sync's own syllable splits only. "
                        "long: also subdivide words held past --split-threshold, "
                        "where a frozen highlight is most visible. all: subdivide "
                        "every word. long/all INTERPOLATE timings -- estimates, not "
                        "measurements; real IsPartOfWord splits are never touched.")
    w.add_argument("--split-threshold", type=float, default=0.7, metavar="SECS",
                   help="with --split long, the held-word cutoff (default 0.7s)")
    w.add_argument("--offset", type=float, default=0.0, metavar="SECS",
                   help="shift lyrics in time: positive = later, negative = earlier "
                        "(e.g. --offset -0.3 to show lines 300ms sooner)")
    w.add_argument("--no-color", action="store_true")

    a = p.parse_args()
    LS = _sources()
    cdp = None
    said: set = set()
    try:
        if a.cmd == "key":
            if a.value:
                where = LS.set_spicy_key(a.value)
                print(f"kept in {where}", file=sys.stderr)
            got = LS.spicy_key()
            if not got:
                sys.exit("no key: set SPICY_LYRICS_KEY, or "
                         "`spicy_lyrics.py key sl_pk_...`")
            src = next((n for n in LS.SPICY_KEY_ENV
                        if (os.environ.get(n) or "").strip()), "")
            print(f"{got[:8]}… from " + (f"${src}" if src else
                  (str(LS.SPICY_KEY_FILE) if LS.SPICY_KEY_FILE.exists()
                   else "SPICY_SHIPPED_KEY")))

        elif a.cmd == "keys":
            for k_id in LS.spicy_ids():
                print(k_id)

        elif a.cmd == "get":
            cdp = None if a.track else _player(a)
            track = a.track or current_track_id(cdp)
            if not track:
                sys.exit("No track id given and the player would not say. "
                         "Pass one: spicy_lyrics.py get <trackid>")
            try:
                body = LS.spicy_lyrics(track, refresh=a.refresh)
            except LS.SpicyError as exc:
                sys.exit(f"{track}: {exc}")
            if not body:
                sys.exit(f"Spicy Lyrics has no lyrics for {track}.")
            try:
                text = render(body, a.format, a.background)
            except ValueError as exc:
                sys.exit(f"{track}: {exc}")
            if a.out:
                pathlib.Path(a.out).write_text(text + "\n", encoding="utf-8")
                print(f"wrote {len(text.splitlines())} lines to {a.out}", file=sys.stderr)
            else:
                print(text)

        elif a.cmd == "dump":
            outdir = pathlib.Path(a.outdir)
            outdir.mkdir(parents=True, exist_ok=True)
            ext = {"text": "txt", "lrc": "lrc", "elrc": "lrc", "ttml": "ttml", "json": "json"}[a.format]
            offset = written = 0
            while True:
                batch = LS.spicy_page(offset, a.batch)
                if not batch:
                    break
                for e in batch:
                    try:
                        body = render(e["body"], a.format, a.background)
                    except Exception as exc:
                        print(f"  skip {e['id']}: {exc}", file=sys.stderr)
                        continue
                    (outdir / f"{e['id']}.{ext}").write_text(body + "\n", encoding="utf-8")
                    written += 1
                offset += len(batch)
                print(f"  {written} exported...", file=sys.stderr)
            print(f"wrote {written} files to {outdir}", file=sys.stderr)
            if not written:
                print("nothing held here yet -- `get` a few tracks first",
                      file=sys.stderr)

        elif a.cmd == "watch":
            cdp = _player(a)
            color = sys.stdout.isatty() and not a.no_color and not os.environ.get("NO_COLOR")
            track, lines, unsynced = None, [], False
            region, printed, started, retry_at = [], set(), False, 0.0

            def load(tid):
                """This track's lines, or [] -- and why, once, where it was
                the API that would not say rather than the song that has no
                lyrics."""
                try:
                    body = LS.spicy_lyrics(tid)
                except LS.SpicyError as exc:
                    # Said once. A key that is missing or refused is one fault,
                    # not one per song.
                    if str(exc) not in said:
                        said.add(str(exc))
                        print(f"--- {exc}", file=sys.stderr, flush=True)
                    return []
                if not body:
                    return []
                return timeline(body, split=a.split, threshold=a.split_threshold)

            while True:
                tid, pos, status = player_state(cdp)
                pos -= a.offset

                if tid != track:
                    track, unsynced, lines = tid, False, []
                    region, printed = [], set()
                    if tid:
                        lines = load(tid)
                        head = f"--- {tid} "
                        if not lines:
                            head += "(nothing for this track)"
                            retry_at = time.monotonic() + 30.0
                        elif all(ln["start"] is None for ln in lines):
                            head += f"({len(lines)} lines, unsynced)"
                            unsynced = True
                        else:
                            n = sum(len(ln["syls"]) for ln in lines)
                            head += f"({len(lines)} lines" + (f", {n} syllables)" if n else ")")
                        print(head, file=sys.stderr, flush=True)
                        if unsynced:
                            for ln in lines:
                                print(ln["text"], flush=True)

                # Only ever a retry after trouble: a track the API has
                # answered about is settled, and a miss is held for hours by
                # the cache, so this costs nothing where there is nothing.
                if not lines and track and time.monotonic() >= retry_at:
                    retry_at = time.monotonic() + 30.0
                    lines = load(track)
                    if lines:
                        unsynced = all(ln["start"] is None for ln in lines)
                        n = sum(len(ln["syls"]) for ln in lines)
                        print(
                            f"--- {track} ({len(lines)} lines"
                            + (", unsynced)" if unsynced else f", {n} syllables)"),
                            file=sys.stderr, flush=True,
                        )
                        if unsynced:
                            for ln in lines:
                                print(ln["text"], flush=True)

                if not lines or unsynced or status != "Playing":
                    time.sleep(max(a.interval, 0.3))
                    continue

                cur = active_indices(lines, pos)
                if not cur:
                    time.sleep(a.interval)
                    continue

                def decorate(ln, body):
                    pre = "    " if ln["background"] else ("  " if ln["opposite"] else "")
                    if ln["background"]:
                        body = f"({body})"
                        if color:
                            body = f"\033[35m{body}\033[0m" if not a.karaoke else body
                    return pre + body

                if a.karaoke and color:
                    while region and region[0] not in cur:
                        region.pop(0)
                    for i in cur:
                        if i not in region:
                            if started or region:
                                sys.stdout.write("\n")
                            region.append(i)
                            started = True
                    if region:
                        buf = ""
                        if len(region) > 1:
                            buf += f"\033[{len(region) - 1}A"
                        for k_at, i in enumerate(region):
                            ln = lines[i]
                            buf += "\r\033[K" + decorate(ln, karaoke(ln, pos, color))
                            if k_at < len(region) - 1:
                                buf += "\n"
                        sys.stdout.write(buf)
                        sys.stdout.flush()
                else:
                    for i in cur:
                        if i not in printed:
                            printed.add(i)
                            print(decorate(lines[i], lines[i]["text"]), flush=True)
                    if len(printed) > 512:
                        printed = {i for i in printed if i in cur}
                time.sleep(a.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if cdp is not None:
            cdp.close()


if __name__ == "__main__":
    main()
