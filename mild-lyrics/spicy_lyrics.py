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
import functools
import json
import os
import pathlib
import re
import sys
import time
import threading
import unicodedata
from xml.sax.saxutils import escape, quoteattr

_HERE = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]


# --------------------------------------------------------------------------
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
    """The playing track's id, preferring the caller's open `cdp` connection,
    else the session bus."""
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
OPENERS = "\"'(¿¡[“‘«「『（【〔〈《〝"


SAID_SYMBOLS = "$%#€£¥&"


def peel(word: str) -> tuple[str, str, str]:
    """`word` as (punctuation before, word, punctuation after); apostrophes
    stay in, spaces and zero-width spaces peel. head + core + tail is always
    the word."""
    core = word
    tail = ""
    while core and not (core[-1].isalnum() or core[-1] == "'"
                        or (core[-1] in SAID_SYMBOLS and len(core) > 1
                            and core[-2].isalnum())):
        tail = core[-1] + tail
        core = core[:-1]
    head = ""
    while core and (core[0] in OPENERS or core[0].isspace()
                    or core[0] == "\u200b"):
        head += core[0]
        core = core[1:]
    return head, core, tail


def syllabify(word: str) -> list[str]:
    """Heuristic English syllable split; pieces always rejoin to the input.
    Punctuation is peeled first, before the hyphen is looked for."""
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
    """Optionally subdivide whole words, interpolating times by length: "none"
    (the default), "long" (held past `threshold`) or "all". Existing splits
    untouched."""
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
SCRIPTED = re.compile("[\u3040-\u30ff\u2e80-\u2fdf\u3400-\u4dbf\u4e00-\u9fff"
                      "\u1100-\u11ff\u3131-\u318e\uac00-\ud7a3\ud7b0-\ud7fb"
                      "\u0400-\u04ff\u0370-\u03ff\u1f00-\u1ffe\u0600-\u06ff"
                      "\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff"
                      "\u0591-\u05c7\u05d0-\u05f4\ufb1d-\ufb4f\u0531-\u058f"
                      "\u10a0-\u10ff\u1c90-\u1cbf\u3005\u3006]")


def foreign(text) -> bool:
    """Whether anything here is in a script a romanisation is for, judged by
    script (so Vietnamese, in Latin letters, is not)."""
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
    """Whether the only non-Latin letters are Cyrillic or Greek look-alikes
    inside Latin words."""
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
    """Fold look-alike codepoints (e.g. KANGXI RADICAL TWO) onto the real
    kanji, one for one, by NFKC per character."""
    out = []
    for ch in text:
        fixed = unicodedata.normalize("NFKC", ch)
        out.append(fixed if len(fixed) == 1 else ch)
    return "".join(out)
SOKUON = re.compile(r"[っッ]\s*$")
_KKS = None

PYLIBS = pathlib.Path(__file__).resolve().parent.parent / "pylibs"
if PYLIBS.is_dir() and str(PYLIBS) not in sys.path:
    sys.path.append(str(PYLIBS))


class _PackedKanwa:
    """pykakasi's kanji table, each first kanji's entries kept pickled and
    unpickled on use: ~100MB loaded whole, ~16MB like this (2026-10-16).
    pykakasi only ever calls .get(ord(first char))."""
    HOT = 32

    def __init__(self, packed: dict, path=None) -> None:
        self.packed = packed
        self.path = path              # where to read it back after drop()
        self.hot: dict = {}
        self.lock = threading.Lock()

    def drop(self) -> bool:
        """Let the table go too (Memory use minimal); read again on use."""
        with self.lock:
            if self.path is None or self.packed is None:
                return False
            self.packed = None
            self.hot.clear()
            return True

    def get(self, key, default=None):
        with self.lock:
            hit = self.hot.pop(key, None)
            if hit is None:
                if self.packed is None:
                    import pickle
                    with open(self.path, "rb") as f:
                        self.packed = pickle.load(f)
                raw = self.packed.get(key)
                if raw is None:
                    return default
                import pickle
                hit = pickle.loads(raw)
                if len(self.hot) >= self.HOT:
                    self.hot.pop(next(iter(self.hot)))
            self.hot[key] = hit
            return hit


_PACK_KANWA = """import pickle, sys, os
d = pickle.load(open(sys.argv[1], "rb"))
with open(sys.argv[2] + ".tmp", "wb") as f:
    pickle.dump({k: pickle.dumps(v, 5) for k, v in d.items()}, f, 5)
os.replace(sys.argv[2] + ".tmp", sys.argv[2])
"""


def _pack_kanwa() -> None:
    """Put a _PackedKanwa in front of pykakasi before it loads its own. Packed
    in a child once and cached: unpickling it whole here leaves ~100MB behind."""
    import pickle
    import subprocess
    from pykakasi import kanji
    from pykakasi.properties import Configurations
    import lyric_sources
    state = kanji.Kanwa._shared_state
    if state.get("_jisyo_table") is not None:
        return
    src = pathlib.Path(Configurations.dictpath(Configurations.jisyo_kanwa))
    st = src.stat()
    out = lyric_sources.CACHE_DIR.parent / f"kanwa-{st.st_size}-{int(st.st_mtime)}.pickle"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            import noconsole
            run = noconsole.run
        except ImportError:
            run = subprocess.run
        run([sys.executable, "-I", "-c", _PACK_KANWA, str(src), str(out)],
            timeout=60, check=True, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    with open(out, "rb") as f:
        state["_jisyo_table"] = _PackedKanwa(pickle.load(f), out)


def _kakasi():
    """pykakasi if it is installed, else None. Optional on purpose: it is only
    used to rescue syllables the source failed to transliterate at all."""
    global _KKS, _READERS_USED
    _READERS_USED = time.monotonic()
    if _KKS is None:
        try:
            import pykakasi
            try:
                _pack_kanwa()
            except Exception:                            # noqa: BLE001
                pass                       # pykakasi loads its table whole
            _KKS = pykakasi.kakasi()
        except Exception:
            _KKS = False
    return _KKS or None


_SUDACHI = None
SUDACHI_OFF = False      # Memory use minimal: its ~80MB dictionary does not fit
_SUDACHI_LOCK = threading.Lock()

# Readings a lyric wants where Sudachi's dictionary gives another one --
# each checked against the Genius romaji saved here (docs/notes, 2026-10-15).
LYRIC_KANA = {"私": "ワタシ", "貴女": "アナタ", "貴方": "アナタ", "良い": "イイ",
              "金": "カネ", "言う": "イウ", "一回": "イッカイ"}
# Runs of morphemes Sudachi cuts or reads apart that are one reading.
LYRIC_RUNS = {"一歩": "イッポ", "手はずっと": "テワズット"}
_NANI_BEFORE = tuple("をがもかに")


def _sudachi():
    """Sudachi with its core dictionary if both are installed, else None.
    Optional: it reads words in context where pykakasi reads characters
    (お人好し o|hito|yoshi, not o|nin|kou|shi) -- see docs/notes."""
    global _SUDACHI, _READERS_USED
    _READERS_USED = time.monotonic()
    if SUDACHI_OFF:
        return None
    if _SUDACHI is None:
        try:
            import warnings
            from sudachipy import Dictionary, SplitMode
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _SUDACHI = Dictionary(dict="core").create(SplitMode.C)
        except Exception:
            _SUDACHI = False
    return _SUDACHI or None


_READERS_USED = 0.0


def release_readers(idle: float, deep: bool = False) -> bool:
    """Let Sudachi (an ~80MB dictionary mapping) and pykakasi's decoded
    entries go if neither was asked for in `idle` seconds, and with `deep`
    its packed table and pypinyin (~45MB of dicts) too; all come back on
    the next line that needs them."""
    global _SUDACHI, _PINYIN
    if time.monotonic() - _READERS_USED < idle:
        return False
    gone = False
    with _SUDACHI_LOCK:
        if _SUDACHI:
            _SUDACHI, gone = None, True
    try:
        from pykakasi import kanji
        table = kanji.Kanwa._shared_state.get("_jisyo_table")
        if isinstance(table, _PackedKanwa):
            with table.lock:
                gone = gone or bool(table.hot)
                table.hot.clear()
            if deep:
                gone = table.drop() or gone
    except Exception:                                    # noqa: BLE001
        pass
    if deep and "pypinyin" in sys.modules:
        _PINYIN, gone = None, True
        for name in [n for n in sys.modules
                     if n == "pypinyin" or n.startswith("pypinyin.")]:
            sys.modules.pop(name, None)
        syl = sys.modules.get("editor.syllables")
        if syl is not None and hasattr(syl, "_zh_phrases"):
            syl._zh_phrases.cache_clear()
    return gone


def _split_a():
    from sudachipy import SplitMode
    return SplitMode.A


def _hira(kana: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c
                   for c in kana)


def _joins(pos, prev, prev_surf: str, surf: str) -> bool:
    """Whether a Sudachi morpheme belongs to the word before it, the way a
    romanised lyric spaces words: endings on (aruite iru -> aruiteiru),
    particles apart (machi o aruku), a copula apart from its noun (ai da)."""
    if prev[0] == "接頭辞":
        return True
    if pos[0] == "接尾辞":
        return True
    if pos[0] == "助動詞":
        return not (surf[:1] in "だでじ" and prev[0] in ("名詞", "代名詞", "形状詞"))
    if pos[0] == "助詞" and pos[1] in ("接続助詞", "準体助詞"):
        return prev[0] not in ("名詞", "代名詞")
    return pos[0] == "動詞" and pos[1] == "非自立可能" and prev_surf in ("て", "で")


def _sudachi_segments(text: str, fine: bool = False):
    """`text` as pykakasi-shaped segments, words read by Sudachi; None if it
    cannot be read. Latin, digits and spaces keep their own text. `fine`
    keeps Sudachi's own morphemes rather than romanised-lyric words."""
    tok, k = _sudachi(), _kakasi()
    if tok is None or k is None:
        return None
    try:
        with _SUDACHI_LOCK:
            ms = [(x.surface(), x.reading_form(), x.part_of_speech())
                  for m in tok.tokenize(text)
                  for x in ((list(m.split(_split_a())) or [m]) if fine else [m])]
    except Exception:
        return None
    if "".join(m[0] for m in ms) != text:
        return None
    i = 0
    while i < len(ms):
        for n in (3, 2):
            run = "".join(m[0] for m in ms[i:i + n])
            if len(ms[i:i + n]) == n and run in LYRIC_RUNS:
                ms[i:i + n] = [(run, LYRIC_RUNS[run], ms[i][2])]
                break
        i += 1
    words: list[list] = []
    for i, (surf, read, pos) in enumerate(ms):
        jp = bool(KANA.search(surf) or _HAS_KANJI.search(surf))
        kana = LYRIC_KANA.get(surf, read) if jp else surf
        if surf == "何" and ms[i + 1:] and ms[i + 1][0].startswith(_NANI_BEFORE):
            kana = "ナニ"
        elif i and surf == "方" and ms[i - 1][2][0] == "代名詞":
            kana = "ガタ"                    # あなた方 anata gata
        elif i and surf == "通り" and ms[i - 1][2][0] == "名詞":
            kana = "ドオリ"                  # 文字通り moji doori
        small = surf[:1] in SMALL_VOWELS or surf[:1] in "ゎヮ"
        if (words and jp and words[-1][2] and (small or not fine and _joins(
                pos, ms[i - 1][2], ms[i - 1][0], surf))):
            words[-1][0] += surf
            words[-1][1] += kana
        else:
            words.append([surf, kana, jp])
    out = []
    for orig, kana, jp in words:
        conv = list(k.convert(kana)) if jp else []
        hira = "".join(x.get("hira", "") or "" for x in conv) if jp else orig
        rom = "".join(x.get("hepburn", "") or "" for x in conv) if jp else orig
        out.append({"orig": orig, "hira": hira, "kana": kana, "hepburn": rom,
                    "kunrei": rom, "passport": rom})
    return tuple(out)


_COMBOS = {
    "とぅ": "tu", "どぅ": "du", "てぃ": "ti", "でぃ": "di", "てゅ": "tyu",
    "でゅ": "dyu", "うぃ": "wi", "うぇ": "we", "うぉ": "wo", "しぇ": "she",
    "じぇ": "je", "ちぇ": "che", "つぁ": "tsa", "つぃ": "tsi", "つぇ": "tse",
    "つぉ": "tso", "くぁ": "kwa", "ぐぁ": "gwa", "いぇ": "ye", "ふゅ": "fyu",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo", "ゔ": "vu",
}
_COMBO = re.compile("|".join(sorted(_COMBOS, key=len, reverse=True)))


def _hep(seg: dict) -> str:
    """A pykakasi segment's Hepburn, with the pairs in _COMBOS read whole and
    っ doubling the consonant after it.

    pykakasi reads っ on its own too, so どっち came out "dotchi" and 眠っちゃう
    "nemutsuchau" where Hepburn -- and Genius -- write "docchi", "nemucchau".
    """
    rom = seg.get("hepburn", "") or ""
    hira = seg.get("hira", "") or ""
    if not (_COMBO.search(hira) or re.search("っ[^っー]", hira)):
        return rom
    out, double = [], False
    for piece in re.split(f"({_COMBO.pattern}|っ+)", hira):
        if not piece:
            continue
        if piece.startswith("っ"):
            double = True
            continue
        if piece in _COMBOS:
            said = _COMBOS[piece]
        else:
            if piece.startswith("ー") and out and out[-1][-1:] in "aeiou":
                run = len(piece) - len(piece.lstrip("ー"))
                out[-1] += out[-1][-1] * run
                piece = piece[run:]
                if not piece:
                    continue
            said = "".join(x.get("hepburn", "") or "" for x in _segments(piece))
        if double and said[:1].isalpha() and said[0] not in "aeiou":
            said = ("c" if said.startswith("ch") else said[0]) + said
        double = False
        out.append(said)
    return "".join(out)


SOLO_KANJI = {
    "君": "kimi", "僕": "boku", "私": "watashi", "俺": "ore", "夢": "yume",
    "空": "sora", "心": "kokoro", "愛": "ai", "涙": "namida", "花": "hana",
    "星": "hoshi", "月": "tsuki", "風": "kaze", "雨": "ame", "光": "hikari",
    "声": "koe", "手": "te", "目": "me", "胸": "mune", "今": "ima",
    "夜": "yoru", "朝": "asa", "恋": "koi", "道": "michi", "海": "umi",
    "街": "machi", "影": "kage", "嘘": "uso", "音": "oto", "色": "iro",
}
"""What a kanji is read as when a lyric uses it as a word on its own.

pykakasi reads a kanji standing alone by whichever reading its dictionary
lists first, and for several of the commonest words in a song that is the
Chinese one: 君 alone came back "kun", which is the honorific suffix and not
"kimi", the you every other love song is addressed to. Only whole segments
are looked up, so 君主 and 夜明け, which pykakasi reads as the words they are,
are left alone."""


@functools.lru_cache(maxsize=512)
def _segments(text: str, fine: bool = False) -> tuple:
    """pykakasi's (or Sudachi's) segments for `text`, kept for the last few
    hundred; the tuples are shared, and failures are not kept."""
    got = _sudachi_segments(text, fine) if _sudachi() else None
    if got is not None:
        return got
    segs = [dict(x) for x in _kakasi().convert(text)]
    for i, seg in enumerate(segs):
        orig = seg.get("orig", "") or ""
        if not i or not orig or orig.strip("々〻"):
            continue
        # 々 the dictionary does not know with its kanji (燦々) comes back
        # alone as "(kurikaesi)", its own name; it says the kanji again.
        prev = segs[i - 1].get("orig", "") or ""
        if not prev or not KANJI.match(prev[-1]):
            continue
        last = (segs[i - 1] if len(prev) == 1
                else (list(_kakasi().convert(prev[-1])) or [{}])[0])
        n = len(orig)
        for key in ("hira", "kana", "hepburn", "kunrei", "passport"):
            if last.get(key):
                seg[key] = last[key] * n
    return tuple(segs)


QUOTING = "「」『』"


def _quotes(orig: str, rom: str) -> str:
    """`rom` with the brackets pykakasi made of 「」『』 written as quotes again."""
    if not any(ch in QUOTING for ch in orig):
        return rom
    marks = iter([ch for ch in orig if ch in QUOTING + "()（）"])
    out = []
    for ch in rom:
        if ch in "()":
            mark = next(marks, None)
            out.append('"' if mark is not None and mark in QUOTING else ch)
        else:
            out.append(ch)
    return "".join(out)


def _convert(k, text: str, fine: bool = False) -> list[dict]:
    """pykakasi's segments for `text`, their "hepburn" read through _hep.

    Also carries a っ across a segment boundary: 眠っちゃう comes back as 眠っ +
    ちゃう, and each half read alone is "nemutsu" + "chau".
    """
    segs = [dict(x, hepburn=_hep(x)) for x in _segments(text, fine)]
    for seg in segs:
        alone = SOLO_KANJI.get(seg.get("orig", ""))
        if alone:
            seg["hepburn"] = alone
        seg["hepburn"] = _quotes(seg.get("orig", "") or "", seg["hepburn"])
    for a, b in zip(segs, segs[1:]):
        h, nxt = a.get("hira", "") or "", b["hepburn"]
        if (h.endswith("っ") and a["hepburn"].endswith("tsu")
                and nxt[:1].isalpha() and nxt[0] not in "aeiou"):
            a["hepburn"] = a["hepburn"][:-3]
            b["hepburn"] = ("c" if nxt.startswith("ch") else nxt[0]) + nxt
    return segs


def reading(text: str) -> str:
    """A whole string's romaji. The particles are read here too.

    They were not, and that was the single-string path quietly disagreeing
    with line_readings about the same sentence -- see particle_rom, which is
    defined below this because the table it needs is.
    """
    k = _kakasi()
    if not k or not text:
        return ""
    text = canon(text)
    try:
        out, at = [], 0
        for seg in _convert(k, text):
            src = seg.get("orig", "") or ""
            out.append(particle_rom(src, seg["hepburn"],
                                    at_start=(at == 0)))
            at += len(src)
        return re.sub(r"\d+", lambda m: " " + _digits_read(m.group()) + " ",
                      "".join(out)).strip()
    except Exception:
        return ""


PARTICLES = {"は": "wa", "へ": "e", "を": "o"}

_PARTICLE_SAID = {"は": ("ha", "wa"), "へ": ("he", "e"), "を": ("wo", "o")}
_ALL_KANA = re.compile(r"^[぀-ゟ゠-ヿー]+$")


def particle_rom(src: str, rom: str, at_start: bool = False) -> str:
    """A segment's reading with は/へ/を read as particles (wa, e, o) where the
    segment is that particle or an all-kana word ending in it. `at_start`
    guards は."""
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
        if low < i < len(rom) and _seam_ok(rom.lower(), i):
            return i
    return cut


def _seam_ok(rom: str, i: int) -> bool:
    """Whether a syllable may end before rom[i]: after a vowel, after an n
    that is ん (not before a vowel: ni|ai), or inside a doubled consonant,
    which goes hak|ka as がっ|こう does."""
    a, b = rom[i - 1], rom[i]
    if b not in "aeiou" and (rom[i + 1:i + 2] == b or rom[i:i + 3] == "tch"):
        return False
    if a in "aeiou":
        return True
    if a == "n":
        return b not in "aeiouy'"
    return a == b or rom[i - 1:i + 2] == "tch"


_VOICED = {"g": "k", "z": "s", "j": "sh", "d": "t", "b": "h", "p": "h",
           "f": "h", "ch": "sh", "ts": "s"}


def _kasane(rom: str, before: int):
    """X々 read as one sound twice (rara, taka|daka -- the second may be
    voiced): (what goes before, X's, 々's), or None. `before` letters at
    least are left for the pieces in front."""
    def onset(r):
        m = re.match(r"[^aeiou]*", r)
        return _VOICED.get(m.group(), m.group()), r[m.end():]
    for j in range(len(rom) - 1, 0, -1):
        o2, v2 = onset(rom[j:])
        for i in range(j - 1, before - 1, -1):
            if (i and not _seam_ok(rom, i)) or not _seam_ok(rom, j):
                continue
            o1, v1 = onset(rom[i:j])
            if v1 and v1 == v2 and o1 == o2:
                return rom[:i], rom[i:j], rom[j:]
    return None


TRAILING_KANA = "っゃゅょぁぃぅぇぉゎーッャュョァィゥェォヮ"
SMALL_VOWELS = "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮー"


def kana_cut(read: str, cut: int, low: int) -> int:
    """Nudge a split point in a kana reading onto a mora boundary (small kana
    and ー stay with the character before)."""
    while low < cut < len(read) and read[cut] in TRAILING_KANA:
        cut += 1
    return cut


_DIGITS = ["", "ichi", "ni", "san", "yon", "go", "roku", "nana", "hachi", "kyuu"]
_TENS = {1: "juu"}
_HUNDREDS = {1: "hyaku", 3: "sanbyaku", 6: "roppyaku", 8: "happyaku"}
_THOUSANDS = {1: "sen", 3: "sanzen", 8: "hassen"}


def _digits_read(digits: str) -> str:
    """A number as said; one with a leading 0 is said a digit at a time:
    00 is "zero zero" (Ado's 0), 007 "zero zero nana"."""
    if len(digits) > 1 and digits[0] == "0":
        return " ".join(number_reading(int(d)) for d in digits)
    return number_reading(int(digits))


def number_reading(n: int) -> str:
    """A number as said in Japanese, in Hepburn, up to 9999, with its own sound
    changes but no counter's."""
    if n == 0:
        return "zero"
    if n > 9999:
        return str(n)
    out = []
    th, n = divmod(n, 1000)
    if th:
        out.append(_THOUSANDS.get(th, _DIGITS[th] + "sen"))
    hu, n = divmod(n, 100)
    if hu:
        out.append(_HUNDREDS.get(hu, _DIGITS[hu] + "hyaku"))
    te, n = divmod(n, 10)
    if te:
        out.append(_TENS.get(te, _DIGITS[te] + "juu"))
    if n:
        out.append(_DIGITS[n])
    return "".join(out)


_INLINE_RUBY = re.compile(r"[(（]([぀-ヿー]+)[)）]")


def ruby_blocks(text: str) -> list[tuple[int, int, int]]:
    """A reading written in brackets after kanji, 傾(かぶ): (where the kanji
    it reads start, where the bracket opens, where it closes + 1). The kanji
    are the last word pykakasi finds before the bracket (異端|傾)."""
    out = []
    for m in _INLINE_RUBY.finditer(text):
        p0 = m.start()
        if not p0 or not KANJI.match(text[p0 - 1]):
            continue
        k0 = p0 - 1
        try:
            at = 0
            for seg in _segments(canon(text[:p0])):
                orig = seg.get("orig", "") or ""
                if at + len(orig) >= p0:
                    k0 = at
                    break
                at += len(orig)
        except Exception:
            pass
        while k0 < p0 - 1 and not KANJI.match(text[k0]):
            k0 += 1
        while k0 < p0 - 1 and not all(KANJI.match(c) for c in text[k0:p0]):
            k0 += 1
        out.append((k0, p0, m.end()))
    return out


_VOICED = str.maketrans("かきくけこさしすせそたちつてとはひふへほ",
                        "がぎぐげござじずぜぞだぢづでどばびぶべぼ")
_ALT = {"は": ("は", "わ"), "へ": ("へ", "え"), "を": ("を", "お")}


def _sound(rom: str) -> str:
    """A romaji spelling folded so Hepburn variants compare equal: case,
    accents, long vowels (ou/oo/ō), wo/o, dz/z, tch/cch, mp/np."""
    s = unicodedata.normalize("NFKD", rom or "").lower()
    s = "".join(c for c in s if "a" <= c <= "z")
    for a, b in (("tch", "cch"), ("dz", "z"), ("wo", "o"), ("mp", "np"),
                 ("mb", "nb"), ("ou", "o"), ("oo", "o"), ("uu", "u"),
                 ("aa", "a"), ("ii", "i"), ("ee", "e"), ("ei", "e")):
        s = s.replace(a, b)
    return s


def _kana_rom(kana: str) -> str:
    k = _kakasi()
    return "".join(_hep(dict(x)) for x in k.convert(kana)) if k and kana else ""


@functools.lru_cache(maxsize=4096)
def _kanji_kana(run: str, okuri: str = "") -> tuple:
    """Every reading pykakasi's dictionary lists for the kanji `run`: as a
    word, as the word with its okurigana (解っ わかっ), else a kanji at a
    time with rendaku and a final っ (一歩 いっぽ). Capped."""
    try:
        from pykakasi.kanji import Kanwa
        kw = Kanwa()
    except Exception:
        return ()

    def look(key):
        return [y for y, _t in (kw.load(key) or {}).get(key, [])]
    out = look(run)
    for n in range(1, len(okuri) + 1):
        out += [y[:-n] for y in look(run + okuri[:n])
                if y.endswith(okuri[:n]) and len(y) > n]
    if okuri:
        # a verb's stem from any of its listed forms: 疼く うず|く, for 疼いて
        table = kw.load(run) or {}
        out += [y[:-1] for key, ys in table.items()
                if len(key) == len(run) + 1 and key.startswith(run)
                and KANA.match(key[-1])
                for y, _t in ys if y.endswith(key[-1]) and len(y) > 1]
    if not out:
        combos = [""]
        for i, ch in enumerate(run):
            alone = look(ch) or [ch]
            each = set(alone)
            if i:
                each |= {y[:1].translate(_VOICED) + y[1:] for y in alone}
            if i < len(run) - 1:
                each |= {y[:-1] + "っ" for y in alone if y[-1:] in "つくちき"}
            combos = [c + y for c in combos for y in each][:96]
        out = combos
    # an okurigana the reading already ends in comes off: 好し is よ+し
    out += [y[:-m] for y in list(out) for m in (1, 2)
            if okuri and len(y) > m and okuri.startswith(y[-m:])]
    return tuple(dict.fromkeys(out))


def _piece_kana(text: str, after: str = "") -> list[str]:
    """Kana spellings a piece could be read as: its kana as written, its
    kanji by `_kanji_kana` (okurigana from `after`, the next piece, when it
    ends on one), Latin and marks as themselves. Capped."""
    units = re.findall(r"[㐀-䶿一-鿿々〻]+|[぀-ヿー]+|[^㐀-䶿一-鿿々〻぀-ヿー]+",
                       canon(text))
    combos = [""]
    for i, u in enumerate(units):
        if _HAS_KANJI.match(u):
            nxt = units[i + 1] if i + 1 < len(units) else canon(after)
            okuri = re.match(r"[぀-ヿー]*", nxt).group()
            each = list(_kanji_kana(u, _hira(okuri)))
        elif KANA.match(u):
            each = list(_ALT.get(u, (_hira(u),)))
        else:
            each = [u]
        if not each:
            return []
        combos = [c + y for c in combos for y in each][:160]
    return combos


def fit_readings(texts: list[str], readings: list[str], said: str) -> list[str]:
    """`readings` with the pieces Genius (`said`) disagrees with read again
    from the dictionary's other readings, where one spells exactly what it
    has there: 相も変わらず ai, not sou. The rest are left as they were."""
    n = len(texts)
    if n != len(readings) or not said or _kakasi() is None:
        return list(readings)
    want = _sound(said)
    mine = [_sound(r) for r in readings]
    from difflib import SequenceMatcher
    starts, at = [], 0
    for m in mine:
        starts.append(at)
        at += len(m)
    joined = "".join(mine)
    good = [False] * n
    where = [None] * n
    for a, b, size in SequenceMatcher(None, joined, want,
                                      autojunk=False).get_matching_blocks():
        for i in range(n):
            lo, hi = starts[i], starts[i] + len(mine[i])
            if mine[i] and a <= lo and hi <= a + size:
                good[i], where[i] = True, (b + lo - a, b + hi - a)
    out = list(readings)
    i = 0
    while i < n:
        if good[i] or not (KANA.search(texts[i]) or _HAS_KANJI.search(texts[i])):
            i += 1
            continue
        j = i
        while j < n and not good[j]:
            j += 1
        lo = where[i - 1][1] if i and where[i - 1] else (0 if i == 0 else None)
        hi = where[j][0] if j < n and where[j] else (len(want) if j == n else None)
        if lo is not None and hi is not None and lo <= hi and j - i <= 6:
            got = _fit_span(texts[i:j], want[lo:hi],
                            texts[j] if j < n else "")
            if got:
                out[i:j] = got
        i = j
    return out


def _fit_span(texts: list[str], target: str, after: str = ""):
    """Per-piece romaji for `texts` that sound exactly like `target`;
    `after` is the piece that follows, for okurigana."""
    options = [_piece_kana(t, texts[k + 1] if k + 1 < len(texts) else after)
               for k, t in enumerate(texts)]
    if not all(options):
        return None
    found = []

    def walk(k, acc):
        if found:
            return
        if k == len(texts):
            if _sound(_said("".join(acc))) == target:
                found.append(list(acc))
            return
        for y in options[k]:
            head = _sound(_said("".join(acc) + y))
            if y.endswith("っ") or target.startswith(head):
                walk(k + 1, acc + [y])
            if found:
                return
    walk(0, [])
    if not found:
        return None
    return line_readings(found[0]) if any(
        _HAS_KANJI.search(y) for y in found[0]) else _split_kana(found[0])


def _said(kana: str) -> str:
    """Romaji for a kana run; a っ it ends on is a stop, not "tsu"."""
    rom = _kana_rom(kana)
    return rom[:-3] if kana[-1:] in "っッ" and rom.endswith("tsu") else rom


def _split_kana(kanas: list[str]) -> list[str]:
    """Romaji for each of these kana pieces, read as one run (っ carried)."""
    whole = _said("".join(kanas))
    out, at = [], 0
    for idx, y in enumerate(kanas):
        rom = _kana_rom("".join(kanas[:idx + 1]))
        cut = len(rom)
        if y.endswith("っ") and idx + 1 < len(kanas):
            nxt = _kana_rom(kanas[idx + 1])[:1]
            cut = len(_kana_rom("".join(kanas[:idx + 1])[:-1])) + (
                1 if nxt and nxt not in "aeiou" else 0)
        out.append(whole[at:cut] if cut >= at else "")
        at = max(at, cut)
    out[-1] += whole[at:] if at < len(whole) else ""
    return out


def line_readings(texts: list[str]) -> list[str]:
    """Readings for a whole line, romanised in context and handed back per
    syllable, with the romaniser word index each came from."""
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
        # Sudachi's morphemes, not its words: a long word's reading shared
        # by character over many syllables lands its seams badly.
        segments = _convert(k, joined, fine=True)
    except Exception:
        return out, owner
    pos = 0
    for si, seg in enumerate(segments):
        src = seg.get("orig", "") or ""
        rom = seg["hepburn"].strip()
        a, b = pos, pos + len(src)
        pos = b
        if not src:
            continue
        rom = particle_rom(src, rom, at_start=(a == 0))
        touched = [i for i, (x, y) in enumerate(spans) if x < b and y > a and y > x]
        if not touched:
            continue
        for i in touched:
            if owner[i] < 0:
                owner[i] = si
        if len(touched) == 1:
            out[touched[0]] += rom
            continue
        if rom == src:
            for i in touched:
                out[i] += src[max(a, spans[i][0]) - a:min(b, spans[i][1]) - a]
            continue
        if _ALL_KANA.match(src):
            pieces = [src[max(a, spans[i][0]) - a:min(b, spans[i][1]) - a]
                      for i in touched]
            read = [seg["hepburn"] if len(pieces) == 1
                    else reading(p) for p in pieces]
            for j in range(len(pieces) - 1):
                nxt = read[j + 1]
                if pieces[j][-1:] in ("っ", "ッ") and nxt[:1].isalpha() \
                        and nxt[0] not in "aeiou":
                    dub = "c" if nxt.startswith("ch") else nxt[0]
                    stem = pieces[j].rstrip("っッ")
                    read[j] = (reading(stem) if stem else "") + dub
            for j in range(1, len(pieces)):
                lead = len(pieces[j]) - len(pieces[j].lstrip(SMALL_VOWELS))
                if not lead:
                    continue
                both = reading(pieces[j - 1] + pieces[j][:lead])
                if len(both) >= 2:
                    read[j - 1] = both[:-1]
                    read[j] = both[-1] + reading(pieces[j][lead:])
            # _convert moved a っ's consonant onto this segment ("tteiro"
            # after 黙っ); the pieces read alone lose it.
            if (len(rom) > 1 and rom[0] == rom[1] and rom[0] not in "aeiou"
                    and "".join(read) == rom[1:]):
                read[0] = rom[0] + read[0]
            head = "".join(read[:-1])
            if all(read):
                if (rom != "".join(read) and rom.startswith(head)
                        and len(rom) > len(head)):
                    read[-1] = rom[len(head):]
                for i, r in zip(touched, read):
                    out[i] += r
                continue
        pieces = [src[max(a, spans[i][0]) - a:min(b, spans[i][1]) - a]
                  for i in touched]
        kana = [reading(p) if _ALL_KANA.match(p) else "" for p in pieces]
        lo, hi, rest = 0, len(pieces), rom
        while (hi - lo > 1 and kana[hi - 1] and rest.endswith(kana[hi - 1])
               and len(rest) > len(kana[hi - 1])):
            rest, hi = rest[:-len(kana[hi - 1])], hi - 1
        while (hi - lo > 1 and kana[lo] and rest.startswith(kana[lo])
               and len(rest) > len(kana[lo])):
            rest, lo = rest[len(kana[lo]):], lo + 1
        # Kana at either end read as themselves (寝転ぶ is ne|koro|bu, not
        # ne|ko|robu): only the kanji between share what is left.
        for j, i in enumerate(touched):
            if not lo <= j < hi:
                out[i] += kana[j]
        rom, touched = rest, touched[lo:hi]
        mid = pieces[lo:hi]
        if (len(mid) in (2, 3) and mid[-1] == "々" and KANJI.match(mid[-2])):
            got = _kasane(rom, len(mid) - 2)
            if got and bool(got[0]) == (len(mid) == 3):
                for i, r in zip(touched, [x for x in got if x]):
                    out[i] += r
                continue
        # Seams where each piece's own dictionary reading puts them (生き|様
        # iki|zama, 始|ま|っ haji|ma|t), before sharing out by characters.
        got = _fit_span(mid, _sound(rom)) if 1 < len(mid) <= 6 else None
        if got and len(got) == len(touched) and all(got):
            for i, r in zip(touched, got):
                out[i] += r
            continue
        total = sum(min(b, spans[i][1]) - max(a, spans[i][0]) for i in touched) or 1
        acc = cut_prev = 0
        for j, i in enumerate(touched):
            acc += min(b, spans[i][1]) - max(a, spans[i][0])
            left = len(touched) - 1 - j
            cut = len(rom) if j == len(touched) - 1 else round(len(rom) * acc / total)
            cut = mora_cut(rom, cut, cut_prev)
            cut = max(cut, min(cut_prev + 1, len(rom) - left))
            cut = min(cut, len(rom) - left) if left else cut
            out[i] += rom[cut_prev:cut]
            cut_prev = cut
    # 傾(かぶ): the bracket is the kanji's reading, said once. A piece
    # holding both reads as the kana; split apart, the kana carry it.
    for k0, p0, p1 in ruby_blocks(joined):
        for i, (x, y) in enumerate(spans):
            if not (x < p1 and y > k0):
                continue
            said = "".join(c for j, c in enumerate(joined[x:y], x)
                           if not (k0 <= j < p0 or j in (p0, p1 - 1)))
            out[i] = reading(said) if said.strip() else ""
    for i, t in enumerate(texts):
        stripped = t.strip()
        if stripped in PARTICLES and (i or stripped != "は"):
            out[i] = PARTICLES[stripped]
    for i, t in enumerate(texts):
        if not re.search(r"\d", t):
            continue
        nxt = texts[i + 1] if i + 1 < len(texts) else ""
        r = re.sub(r"\d+", lambda m: _digits_read(m.group()), out[i])
        if re.search(r"\d", t) and (re.search(r"\d\s*[~〜～]", t) or
                                     (re.search(r"[~〜～]\s*$", t) and re.match(r"\s*\d", nxt))):
            r = re.sub(r"[~〜～]", "kara", r)
        out[i] = r
    for i in range(1, len(texts) - 1):
        nxt = out[i + 1]
        if (texts[i].strip() in ("っ", "ッ") and len(nxt) > 1
                and (nxt[0] == nxt[1] or nxt.startswith("cch"))
                and nxt[0] not in "aeiou"):
            out[i - 1] += out[i]
            out[i], out[i + 1] = nxt[0], nxt[1:]
    # The same for a syllable that ENDS in っ (待っ|て, the editor's split by
    # syllable): _convert carried the doubled consonant onto the next segment,
    # "ma" + "tte", where the syllable is mat-te, as がっ|こう is gak-kou.
    for i in range(len(texts) - 1):
        nxt, mine = out[i + 1], texts[i].strip()
        if (len(mine) > 1 and mine[-1] in "っッ" and len(nxt) > 1
                and (nxt[0] == nxt[1] or nxt.startswith("cch"))
                and nxt[0] not in "aeiou" and out[i]
                and out[i][-1:] in "aeiou"):
            out[i], out[i + 1] = out[i] + nxt[0], nxt[1:]
    # っ before a vowel or a pause is a stop, unwritten: まっ|いっか is
    # ma|ikka, あっ is a -- not "matsu", "atsu".
    for i, t in enumerate(texts):
        mine = t.strip()
        if len(mine) < 2 or mine[-1] not in "っッ" or not out[i].endswith("tsu"):
            continue
        nxt = next((r.strip() for r in out[i + 1:] if r.strip()), "")
        if not nxt[:1].isalpha() or nxt[0].lower() in "aeiou":
            out[i] = out[i][:-3]
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


_HAS_KANJI = re.compile(r"[㐀-䶿一-鿿々〻]")


def _kana_twice(read: str, before: int):
    """X々 in kana, one sound twice (ら|ら, たか|だか): (what goes before,
    X's, 々's), or None; `before` pieces in front each need a kana."""
    def bare(k):
        return "".join(c for c in unicodedata.normalize("NFD", k)
                       if c not in "\u3099\u309a")
    for m in range(len(read) // 2, 0, -1):
        front = read[:-2 * m]
        if len(front) < before or (before == 0 and front):
            continue
        a, b = read[-2 * m:-m], read[-m:]
        if bare(a) == bare(b):
            return front, a, b
    return None


def furigana(texts: list[str]) -> list[list[tuple[int, int, str]]]:
    """Kana readings for the kanji in each piece of a line, as (first, last +
    1, reading) per piece, segmented over the whole line."""
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
        segments = _segments(joined)
    except Exception:
        return out
    written = ruby_blocks(joined)
    pos = 0
    for seg in segments:
        src = seg.get("orig", "") or ""
        hira = (seg.get("hira", "") or "").strip()
        a, b = pos, pos + len(src)
        pos = b
        if not src or not hira or not _HAS_KANJI.search(src):
            continue
        lo, hi, read = _ruby(src, hira)
        if not read or hi <= lo:
            continue
        lo, hi = a + lo, a + hi
        if any(k0 <= lo and hi <= p0 for k0, p0, _p1 in written):
            continue   # its reading is written beside it: 傾(かぶ)
        touched = [i for i, (x, y) in enumerate(spans) if x < hi and y > lo]
        if not touched:
            continue
        if len(touched) == 1:
            i = touched[0]
            out[i].append((lo - spans[i][0], hi - spans[i][0], read))
            continue
        parts = [joined[max(lo, spans[i][0]):min(hi, spans[i][1])]
                 for i in touched]
        twice = _kana_twice(read, len(touched) - 2) if (
            len(touched) in (2, 3) and parts[-1] == "々") else None
        if twice:
            for i, part in zip(touched, [x for x in twice if x]):
                x, y = spans[i]
                out[i].append((max(lo, x) - x, min(hi, y) - x, part))
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


# --------------------------------------------------------------------------
GREEK = re.compile("[Ͱ-Ͽἀ-῾]")
ARABIC = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
HEBREW = re.compile("[֑-ׇא-״יִ-ﭏ]")
ARMENIAN = re.compile("[Ա-֏]")
GEORGIAN = re.compile("[Ⴀ-ჿᲐ-Ჿ]")

GR_LATIN = {
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o", "ϊ": "i", "ϋ": "y",
    ";": "?", "·": ";",
}
GR_VOICELESS = set("θκξπσςτφχψ")


def _cased(src: str, r: str) -> str:
    return r[:1].upper() + r[1:] if r and src != src.lower() else r


def greek_reading(text: str) -> str:
    """Greek in Latin letters: ELOT 743, accents dropped, case kept."""
    import unicodedata

    chars = []
    for ch in str(text or ""):
        base = unicodedata.normalize("NFD", ch)
        keep = base[0] + ("̈" if "̈" in base else "")
        chars.append(unicodedata.normalize("NFC", keep))
    out, i, n = [], 0, len(chars)
    while i < n:
        ch = chars[i]
        low = ch.lower()
        nxt = chars[i + 1].lower() if i + 1 < n else ""
        after = chars[i + 2].lower() if i + 2 < n else ""
        start = i == 0 or not chars[i - 1].isalpha()
        pair = low + nxt
        r = None
        if pair == "ου":
            r = "ou"
        elif pair in ("αυ", "ευ", "ηυ"):
            head = GR_LATIN[low]
            r = head + ("f" if (not after or after in GR_VOICELESS
                                or not after.isalpha()) else "v")
        elif pair == "μπ":
            r = "b" if start else "mp"
        elif pair == "ντ":
            r = "d" if start else "nt"
        elif pair == "γκ":
            r = "g" if start else "ng"
        elif pair in ("γγ", "γξ", "γχ"):
            r = "n" + GR_LATIN[nxt]
        if r is not None:
            out.append(_cased(ch, r))
            i += 2
            continue
        r = GR_LATIN.get(low)
        out.append(ch if r is None else _cased(ch, r))
        i += 1
    return "".join(out)


AR_LATIN = {
    "ء": "'", "آ": "a", "أ": "a", "إ": "i", "ؤ": "'", "ئ": "'", "ا": "a",
    "ب": "b", "ة": "a", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s",
    "ض": "d", "ط": "t", "ظ": "z", "ع": "'", "غ": "gh", "ف": "f", "ق": "q",
    "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "ى": "a", "ٱ": "a",
    "پ": "p", "چ": "ch", "ژ": "zh", "گ": "g", "ک": "k", "ڤ": "v", "ڨ": "g",
    "ٹ": "t", "ڈ": "d", "ڑ": "r", "ں": "n", "ہ": "h", "ھ": "h", "ۃ": "a",
    "ے": "e", "ۀ": "e",
    "،": ",", "؛": ";", "؟": "?", "٪": "%", "ـ": "",
}
AR_HARAKA = {"َ": "a", "ُ": "u", "ِ": "i", "ً": "an",
             "ٌ": "un", "ٍ": "in", "ْ": "", "ٰ": "a"}
AR_VOWELS = "aeiou"


def _digit(ch: str) -> str | None:
    import unicodedata

    if ch.isdigit() and not ch.isascii():
        try:
            return str(unicodedata.digit(ch))
        except ValueError:
            return None
    return None


def arabic_reading(text: str) -> str:
    """Arabic in Latin letters, a letter at a time (و/ي by position, "al-",
    shadda doubles)."""
    s = str(text or "")
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        prev_letter = i > 0 and ARABIC.match(s[i - 1]) is not None
        start = not prev_letter and not (out and out[-1][-1:].isalpha())
        if start and s.startswith("ال", i) and i + 2 < n and ARABIC.match(s[i + 2]):
            out.append("al-")
            i += 2
            continue
        if ch in AR_HARAKA:
            out.append(AR_HARAKA[ch])
        elif ch == "ّ":
            last = out[-1] if out else ""
            if last and last[-1] not in AR_VOWELS:
                out.append(last[-1])
        elif ch in ("و", "ي", "ی"):
            nxt = s[i + 1] if i + 1 < n else ""
            before = "".join(out)[-1:]
            consonant = start or (before != "" and before in AR_VOWELS) or (
                nxt != "" and (nxt in AR_HARAKA or nxt in "\u0627\u0648\u064a\u06cc\u0651"))
            if ch == "و":
                out.append("w" if consonant else "u")
            else:
                out.append("y" if consonant else "i")
        elif ch in AR_LATIN:
            out.append(AR_LATIN[ch])
        elif _digit(ch) is not None:
            out.append(_digit(ch))
        elif ARABIC.match(ch):
            out.append("")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


HE_LATIN = {
    "א": "", "ב": "v", "ג": "g", "ד": "d", "ה": "h", "ז": "z", "ח": "ch",
    "ט": "t", "כ": "kh", "ך": "kh", "ל": "l", "מ": "m", "ם": "m", "נ": "n",
    "ן": "n", "ס": "s", "ע": "", "פ": "f", "ף": "f", "צ": "ts", "ץ": "ts",
    "ק": "k", "ר": "r", "ש": "sh", "ת": "t", "־": "-", "׳": "", "״": "",
}
HE_HARD = {"ב": "b", "כ": "k", "ך": "k", "פ": "p", "ף": "p"}
HE_GERESH = {"ג": "j", "ז": "zh", "צ": "ch", "ץ": "ch", "ת": "th"}
HE_NIQQUD = {"ְ": "", "ֱ": "e", "ֲ": "a", "ֳ": "o",
             "ִ": "i", "ֵ": "e", "ֶ": "e", "ַ": "a",
             "ָ": "a", "ֹ": "o", "ֺ": "o", "ֻ": "u",
             "ׇ": "o"}


def hebrew_reading(text: str) -> str:
    """Hebrew in Latin letters, a letter at a time: consonants, matres
    lectionis, niqqud, dagesh, sin dot, geresh."""
    s = str(text or "")
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        marks = ""
        j = i + 1
        while j < n and "֑" <= s[j] <= "ׇ" and s[j] not in "־׀׃׆":
            marks += s[j]
            j += 1
        if j < n and s[j] in "׳'":
            marks += "׳"
            j += 1
        start = i == 0 or not HEBREW.match(s[i - 1])
        final = j >= n or not HEBREW.match(s[j])
        if ch == "ו":
            if "ּ" in marks and not start:
                r = "u"
            elif "ֹ" in marks:
                r = "o"
            elif start or any(m in HE_NIQQUD and HE_NIQQUD[m] for m in marks):
                r = "v"
            else:
                r = "o"
        elif ch == "י":
            r = "y" if start or any(m in HE_NIQQUD and HE_NIQQUD[m] for m in marks) else "i"
        elif ch == "ש":
            r = "s" if "ׂ" in marks else "sh"
        elif ch == "א" and start and s[j:j + 1] not in ("ו", "י"):
            r = "a" if not any(HE_NIQQUD.get(m) for m in marks) else ""
        elif ch == "ה" and final and not start:
            r = "a"
        elif "׳" in marks and ch in HE_GERESH:
            r = HE_GERESH[ch]
        elif ch in HE_HARD and ("ּ" in marks or start):
            r = HE_HARD[ch]
        elif ch in HE_LATIN:
            r = HE_LATIN[ch]
        elif HEBREW.match(ch):
            r = ""
        else:
            r = ch
        vowel = "".join(HE_NIQQUD.get(m, "") for m in marks
                        if not (ch == "ו" and m in "ֹּ"))
        out.append(r + vowel)
        i = j
    return "".join(out)


HY_LATIN = {
    "ա": "a", "բ": "b", "գ": "g", "դ": "d", "ե": "e", "զ": "z", "է": "e",
    "ը": "y", "թ": "t", "ժ": "zh", "ի": "i", "լ": "l", "խ": "kh", "ծ": "ts",
    "կ": "k", "հ": "h", "ձ": "dz", "ղ": "gh", "ճ": "ch", "մ": "m", "յ": "y",
    "ն": "n", "շ": "sh", "ո": "o", "չ": "ch", "պ": "p", "ջ": "j", "ռ": "r",
    "ս": "s", "վ": "v", "տ": "t", "ր": "r", "ց": "ts", "ւ": "v", "փ": "p",
    "ք": "k", "օ": "o", "ֆ": "f", "և": "ev", "։": ".", "՝": ",", "՞": "",
    "՜": "", "՛": "",
}


def armenian_reading(text: str) -> str:
    """Armenian in Latin letters (Eastern), with ու as u and case kept."""
    s = str(text or "")
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch.lower() == "ո" and s[i + 1:i + 2] == "ւ":
            out.append(_cased(ch, "u"))
            i += 2
            continue
        r = HY_LATIN.get(ch.lower())
        out.append(ch if r is None else _cased(ch, r))
        i += 1
    return "".join(out)


KA_LATIN = dict(zip(
    "აბგდევზთიკლმნოპჟრსტუფქღყშჩცძწჭხჯჰ",
    ["a", "b", "g", "d", "e", "v", "z", "t", "i", "k'", "l", "m", "n", "o",
     "p'", "zh", "r", "s", "t'", "u", "p", "k", "gh", "q'", "sh", "ch", "ts",
     "dz", "ts'", "ch'", "kh", "j", "h"]))


def georgian_reading(text: str) -> str:
    """Georgian in Latin letters: the national system, ejectives marked '."""
    out = []
    for ch in str(text or ""):
        low = chr(ord(ch) - 0x0BC0) if "Ა" <= ch <= "Ჿ" else ch
        r = KA_LATIN.get(low)
        out.append(ch if r is None else _cased(ch if low == ch else ch.lower(), r))
    return "".join(out)


LETTERWISE = {"ru": cyrillic_reading, "el": greek_reading,
              "ar": arabic_reading, "he": hebrew_reading,
              "hy": armenian_reading, "ka": georgian_reading}


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
    """Revised Romanisation, one string per character of `text`, with liaison,
    assimilation and ㅎ aspiration; no palatalisation."""
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
    """pypinyin if installed, else None."""
    global _PINYIN, _READERS_USED
    _READERS_USED = time.monotonic()
    if _PINYIN is None:
        try:
            from pypinyin import Style, pinyin
            _PINYIN = (pinyin, Style)
        except Exception:
            _PINYIN = False
    return _PINYIN or None


def pinyin_reading(text: str, tones: bool = True) -> list[str]:
    """Pinyin per character, read with the whole line for context; non-Han
    characters come back as themselves."""
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
    """Which romanisation this text wants: "ja", "zh", "ko", a LETTERWISE
    alphabet, or "". `japanese` says lone Han is Japanese."""
    text = str(text or "")
    if HANGUL.search(text):
        return "ko"
    if KANA.search(text):
        return "ja"
    if HAN.search(text):
        return "ja" if japanese else "zh"
    for kind, pat in (("ru", CYRILLIC), ("el", GREEK), ("ar", ARABIC),
                      ("he", HEBREW), ("hy", ARMENIAN), ("ka", GEORGIAN)):
        if pat.search(text):
            return kind
    return ""


def readings(texts: list[str], japanese: bool = False, cont=None):
    """Romanisation per piece for a line in any readable script, as (readings,
    owner), a run of one script at a time; owner is -1 outside Japanese."""
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
        if kind in LETTERWISE:
            read = LETTERWISE[kind]
            word = ""
            for i in run:
                word = word + texts[i] if cont and cont[i] and word else texts[i]
                head = read(word[:len(word) - len(texts[i])])
                full = read(word)
                out[i] = (full[len(head):] if head and full.startswith(head)
                          else read(texts[i]))
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
    """The pieces of a line grouped into runs of one script; scriptless pieces
    join the run they are in."""
    out: list[tuple[str, list[int]]] = []
    for i, t in enumerate(texts):
        kind = script_of(t, japanese)
        if out and (kind == out[-1][0] or (not kind and out[-1][0])):
            out[-1][1].append(i)
        else:
            out.append((kind, [i]))
    return out


def read_line(text: str, japanese: bool = False) -> str:
    """A whole line's romanisation from its text, a word at a time, or ""."""
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
    """Whether this machine can read anything in `texts`: Korean always,
    Japanese and Chinese only with their package."""
    for kind, _run in _runs(texts, japanese):
        if kind == "ko" or kind in LETTERWISE:
            return True
        if kind == "ja" and _kakasi():
            return True
        if kind == "zh" and _pypinyin():
            return True
    return False


def ruby(texts: list[str], japanese: bool = False,
         scripts=("ja", "zh", "ko")):
    """Ruby per piece for every script that has one (furigana, pinyin, Hangul),
    read a run at a time; `scripts` narrows which."""
    out: list[list[tuple[int, int, str]]] = [[] for _ in texts]
    kinds = {script_of(t, japanese) for t in texts if str(t or "").strip()}
    if kinds <= {"ja", ""}:
        return furigana(texts)
    for kind, run in _runs(texts, japanese):
        if kind == "ja":
            # Its own run only: pykakasi handed Hangul drops characters
            # around it (めっちゃ배고파見て loses the 見), and the kanji
            # after a Korean word went without their reading.
            for i, marks in zip(run, furigana([texts[i] for i in run])):
                out[i] = marks
            continue
        if kind not in ("zh", "ko") or kind not in scripts:
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
    """Make っ a doubled consonant carried onto the next syllable, exactly once;
    returns the corrected pair."""
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


# How far ahead of its line's first word an ad-lib has to come in to be
# drawn above the line rather than under it. 0.4 left One For the Money's
# "(Two)", sung 0.36-0.37s ahead of "It's two", under its line while the
# "(Three)" beside it (0.44s) went above. Under 0.3 is timing noise -- a tap
# a hair early -- and stays under.
BG_LEAD = 0.3


READ_IN_JOB = False     # memory minimal: songs needing a dictionary read in a job


def timeline(body, split: str = "none", threshold: float = 0.7) -> list[dict]:
    """Cache entry -> [{start, end, text, syls:[(start,end,text)]}] sorted by start.

    With READ_IN_JOB, a song in kana or Han is built in one offload job, so
    its readers (pykakasi, pypinyin) load and go with that process
    (docs/notes memory_mode.md)."""
    if READ_IN_JOB and _needs_reader(body):
        import offload                                   # noqa: PLC0415
        return offload.call(_timeline_job, body, split, threshold, SUDACHI_OFF)
    return _timeline(body, split, threshold)


def _needs_reader(body) -> bool:
    doc = payload(body)
    items = next((doc[k] for k in ("Content", "Lines")
                  if isinstance(doc.get(k), list) and doc[k]), [])
    return any(KANA.search(t) or HAN.search(t)
               for t in (line_text(i) or "" for i in items))


def _timeline_job(body, split: str, threshold: float, sudachi_off: bool):
    global SUDACHI_OFF
    SUDACHI_OFF = sudachi_off
    return _timeline(body, split, threshold)


def _timeline(body, split: str = "none", threshold: float = 0.7) -> list[dict]:
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
        cont = [i > 0 and bool(syls[i - 1].get("IsPartOfWord"))
                and not word_ends(syls[i - 1].get("Text", ""), texts[i])
                for i in range(len(syls))]
        derived, owner = readings(texts, japanese, cont)

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

        def as_written(k):
            return (not script_of(texts[k], japanese)
                    and rows[k][2] == _trim(texts[k]).strip())

        for i in range(len(rows) - 1):
            # A word already in Latin letters is its own reading, and its
            # syllables stay one word under the line as they are in it:
            # "romance" timed ro / mance was drawn "ro mance". Only where
            # nothing was read -- 3〜 / 6 are "sankara roku", two words.
            same = ((owner[i] >= 0 and owner[i] == owner[i + 1])
                    or (script_of(texts[i], japanese) in LETTERWISE
                        and script_of(texts[i + 1], japanese) in LETTERWISE)
                    or (as_written(i) and as_written(i + 1)))
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
        """The line's romanisation where the line is in a script that has one;
        a TransliteratedText on a Latin line is refused."""
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
        return got or read_line(raw, japanese)

    def first_sung(g):
        """When a group's own words start, which the line is believed to start
        at."""
        starts = [y.get("StartTime") for y in (g or {}).get("Syllables") or []
                  if isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float))]
        return min(starts) if starts else None

    def last_sung(g):
        """When a group's own words stop, which is not when it ends."""
        ends = [y.get("EndTime") for y in (g or {}).get("Syllables") or []
                if isinstance(y, dict) and isinstance(y.get("EndTime"), (int, float))]
        return max(ends) if ends else None

    def bounds(group, said_start, said_end):
        """A line runs from its first word to its last; the stated times only
        where it has no syllables."""
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
    for ln in out:
        rom = ln.get("text_roman") or "".join(
            t + ("" if p else " ") for _, _, t, p in ln.get("syls_roman") or [])
        if rom and same_words(ln.get("text", ""), rom):
            ln["text_roman"], ln["syls_roman"] = "", []
    synced = [ln for ln in out if ln["start"] is not None]
    if not synced:
        return out
    return synced


def same_words(text: str, rom: str) -> bool:
    """Whether a romanisation only repeats the line it is under (letters and
    digits, width and case folded)."""
    def fold(s):
        s = unicodedata.normalize("NFKC", s or "").casefold()
        return "".join(c for c in s if c.isalnum())
    a, b = fold(text), fold(rom)
    return bool(a) and a == b


def last_moment(ln: dict):
    """The last moment anything in this line is still sung: the last syllable
    to end, whatever the group says."""
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
    """When this line stops being sung, which is now its end; kept for line
    dicts made elsewhere."""
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
    """The line the view should sit on at `pos`: it moves down only when the
    line is done or outlasted; ad-libs carry it; `lead` steps early."""
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


def karaoke(line: dict, pos: float, colour: bool) -> str:
    """Render a line with syllables sung-so-far highlighted."""
    if not line["syls"] or not colour:
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
    """The lyrics document itself, unwrapping the old Spicetify cache envelope."""
    if isinstance(body, dict) and isinstance(body.get("Content"), dict):
        return body["Content"]
    return body if isinstance(body, dict) else {}


ZWSP = "\u200b"


_BETWEEN = re.compile(r"(?<=[^\s" + ZWSP + r"])" + ZWSP + r"(?=[^\s" + ZWSP + r"])")


def unzwsp(text, spaced: bool = False) -> str:
    """`text` without zero-width spaces; `spaced` turns one between letters
    into a space (a whole line), never between CJK characters."""
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
    """A whole document with every zero-width space removed (never widened),
    every string in it; the same object back when there was nothing to take
    out."""
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
    """Whether the word ends after `text`, from a separator in the text on
    either side of the join, whatever IsPartOfWord says."""
    text, nxt = str(text or ""), str(nxt or "")
    if not text.strip(SEPS) or not nxt.strip(SEPS):
        return False
    return text != text.rstrip(SEPS) or nxt != nxt.lstrip(SEPS)


def syllables_text(syls) -> str:
    """The words a run of syllables spells, spaced from IsPartOfWord, each
    syllable's edges trimmed."""
    out = ""
    for s in syls or []:
        if not isinstance(s, dict):
            continue
        text = str(s.get("Text", ""))
        out += text if s.get("IsPartOfWord") else _trim(text) + " "
    return out.strip()


def line_text(item, background: bool = False) -> str:
    """The words a line spells, from its own Text (minus invisible characters)
    or from its syllables."""
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
    """A line's times widened to hold every voice drawn inside it."""
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
    """Syllables -> <span> run, trimmed text spaced per IsPartOfWord (and
    `word_ends`)."""
    syls = [s for s in (group or {}).get("Syllables") or [] if isinstance(s, dict)]
    parts = []
    for i, s in enumerate(syls):
        raw = s.get("Text", "")
        nxt = syls[i + 1].get("Text", "") if i + 1 < len(syls) else ""
        parts.append(f"<span{_tattrs(s)}>{escape(_trim(raw))}</span>")
        if i < len(syls) - 1 and (not s.get("IsPartOfWord") or word_ends(raw, nxt)):
            parts.append(" ")
    return "".join(parts)


def _roman_spans(group) -> str:
    """The `_spans` run carrying each syllable's reading, one span per
    syllable, empty where there is no reading."""
    syls = [s for s in (group or {}).get("Syllables") or [] if isinstance(s, dict)]
    parts = []
    for i, s in enumerate(syls):
        raw = s.get("Text", "")
        nxt = syls[i + 1].get("Text", "") if i + 1 < len(syls) else ""
        rom = _trim(str(s.get("TransliteratedText") or ""))
        parts.append(f"<span{_tattrs(s)}>{escape(rom)}</span>")
        if i < len(syls) - 1 and (not s.get("IsPartOfWord") or word_ends(raw, nxt)):
            parts.append(" ")
    return "".join(parts)


def _has_roman(group) -> bool:
    return any(isinstance(y, dict) and _trim(str(y.get("TransliteratedText") or ""))
               for y in (group or {}).get("Syllables") or [])


def join_readings(texts: list[str], readings: list[str], parts: list[bool],
                  japanese: bool = False) -> str:
    """Per-syllable readings as one line, spaced where the words part (Japanese
    by the romaniser's segments)."""
    n = len(texts)
    cut = set()
    k = _kakasi() if japanese or any(KANA.search(t or "") for t in texts) else None
    if k is not None:
        try:
            at = 0
            for seg in _convert(k, canon("".join(texts))):
                at += len(seg.get("orig", "") or "")
                cut.add(at)
        except Exception:                                # noqa: BLE001
            cut = set()
    out, pos = "", 0
    for i in range(n):
        r = (readings[i] or "").strip() or _trim(texts[i] or "")
        out += r
        pos += len(canon(texts[i] or ""))
        if i == n - 1:
            break
        here, nxt = (texts[i] or "").rstrip(), (texts[i + 1] or "").lstrip()
        if not parts[i] or (pos in cut and (
                SCRIPTED.search(here) and SCRIPTED.search(nxt)
                # a quote stands apart from the words around it: 「好き」と
                # reads `"suki" to`, not `"suki"to`
                or SCRIPTED.search(here) and nxt[:1] in QUOTING[::2]
                or here[-1:] in QUOTING[1::2] and SCRIPTED.search(nxt))):
            out += " "
    return re.sub(r"\s+", " ", out).strip()


def _line_roman(group, item=None) -> str:
    """A group's reading as one line of text: its own, or its syllables'."""
    for src in (group, item):
        got = (src or {}).get("TransliteratedText") if isinstance(src, dict) else None
        if isinstance(got, str) and got.strip():
            return _trim(got.strip())
    if not _has_roman(group):
        return ""
    syls = [y for y in (group or {}).get("Syllables") or [] if isinstance(y, dict)]
    if any(SCRIPTED.search(y.get("Text", "") or "")
           and not _trim(str(y.get("TransliteratedText") or "")) for y in syls):
        return ""
    return join_readings([y.get("Text", "") for y in syls],
                         [str(y.get("TransliteratedText") or "") for y in syls],
                         [bool(y.get("IsPartOfWord")) for y in syls])


ROMAN_LANG = {"ja": "ja-Latn", "zh": "zh-Latn-pinyin", "ko": "ko-Latn"}


def roman_lang(lang, items) -> str:
    """The xml:lang a transliteration is filed under: the lyric's own
    language written in Latin letters. Asked of the words when the document
    does not say which language it is."""
    lang = str(lang or "").split("-")[0].lower()
    if not lang:
        said = " ".join(line_text(i) for i in items[:40] if isinstance(i, dict))
        lang = script_of(said, bool(KANA.search(said)))
    return ROMAN_LANG.get(lang, f"{lang}-Latn" if lang else "und-Latn")


def _groups(bg) -> list:
    """A line's Background, however many ways it was written."""
    if isinstance(bg, list):
        return [g for g in bg if isinstance(g, dict)]
    return [bg] if isinstance(bg, dict) else []


def _worth_spans(group) -> bool:
    """Whether this group has a timing or a word cut into pieces, which only
    spans can say."""
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

    rows, translit = [], []
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
        said = _line_roman(lead, item)
        if said:
            inner += f'<span ttm:role="x-roman">{escape(said)}</span>'
        per = [_roman_spans(lead)] if lead else []
        worth = _has_roman(lead)
        for g in bg:
            inside = (_spans(g) if g.get("Syllables")
                      else escape(_trim(str(g.get("Text") or ""))))
            said = _line_roman(g)
            if said:
                inside += f'<span ttm:role="x-roman">{escape(said)}</span>'
            worth = worth or _has_roman(g)
            per.append(f'<span ttm:role="x-bg"{_tattrs(g)}>'
                       f'{_roman_spans(g)}</span>')
            piece = f'<span ttm:role="x-bg"{_tattrs(g)}>{inside}</span>'
            if g.get("LeadIn") and not isinstance(g.get("StartTime"), (int, float)):
                inner = piece + inner
            else:
                inner += piece
        rows.append(f"<p{times}{attrs}>{inner}</p>")
        if worth:
            translit.append(f'<text for="L{n}">{"".join(per)}</text>')

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
    if translit:
        meta += (f"<transliterations><transliteration xml:lang="
                 f"{quoteattr(roman_lang(lang, items))}>"
                 + "".join(translit) + "</transliteration></transliterations>")
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
    """A connection to the running Spotify, or None; only the two now-playing
    commands need one."""
    try:
        from spotify_dom import connect
        return connect(a.port, a.target)
    except SystemExit:
        return None
    except Exception:                                    # noqa: BLE001
        return None


def _sources():
    """lyric_sources, imported only when a command needs it (it imports this
    module)."""
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
    w.add_argument("--no-colour", "--no-color", dest="no_colour", action="store_true")

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
            if LS.community_sync(body):
                sys.exit(f"{track}: a Spicy Lyrics community sync, which is "
                         f"not handed out. The player's save (S) writes "
                         f"Apple Music's instead.")
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
            offset = written = held = 0
            while True:
                batch = LS.spicy_page(offset, a.batch)
                if not batch:
                    break
                for e in batch:
                    if LS.community_sync(e["body"]):
                        held += 1
                        continue
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
            if held:
                print(f"left out {held} community syncs -- those are not "
                      f"handed out", file=sys.stderr)
            if not written:
                print("nothing held here yet -- `get` a few tracks first",
                      file=sys.stderr)

        elif a.cmd == "watch":
            cdp = _player(a)
            colour = sys.stdout.isatty() and not a.no_colour and not os.environ.get("NO_COLOR")
            track, lines, unsynced = None, [], False
            region, printed, started, retry_at = [], set(), False, 0.0

            def load(tid):
                """This track's lines, or [] -- and why, once, where it was
                the API that would not say rather than the song that has no
                lyrics."""
                try:
                    body = LS.spicy_lyrics(tid)
                except LS.SpicyError as exc:
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
                        if colour:
                            body = f"\033[35m{body}\033[0m" if not a.karaoke else body
                    return pre + body

                if a.karaoke and colour:
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
                            buf += "\r\033[K" + decorate(ln, karaoke(ln, pos, colour))
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
