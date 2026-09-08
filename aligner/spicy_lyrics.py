#!/usr/bin/env python3
"""
Pull lyrics out of the Spicy Lyrics Spicetify extension in the running Spotify app.

Sources, in order of preference:

  1. Cache Storage -- every build caches each fetched song in a bucket whose
     name starts "SpicyLyrics_LyricsStore", keyed by track id. The generation
     on the end of that name moves ("_g1" today, nothing at all before it), so
     every store matching the prefix is read, newest first; see CACHE_PREFIX.
     Complete lyrics with timings, available even when the lyrics view is closed,
     and unaffected by the DOM virtualizer. This is the one you want.

  2. IndexedDB     -- older builds used db "spicylyrics" / store "lyricsStore".
     Checked as a fallback.

  3. The DOM       -- #SpicyLyricsPage .line elements. Spicy Lyrics VIRTUALIZES
     the list, so this returns only the rendered window, not the whole song.
     Useful for "what is on screen right now", not for extraction.

Cache entry shape (verified against the live app):

    { ExpiresAt, CacheVersion,
      Content: { Type: "Syllable"|"Line"|"Static", id, uri, source, Language,
                 SongWriters[], StartTime, EndTime,
                 Content: [ line, ... ] } }

    Syllable line: { Type, OppositeAligned, Lead: { Syllables: [
                       {Text, IsPartOfWord, StartTime, EndTime} ], StartTime, EndTime } }
    Line line:     { Type, OppositeAligned, Text, StartTime, EndTime }
    Static line:   { Text }

    All times are SECONDS (floats).

Requires Spotify started with a DevTools port:

    pkill -x spotify
    spotify --remote-debugging-port=9222 >/dev/null 2>&1 &

Formats:
    text  plain lines, no timing
    lrc   standard LRC, one [mm:ss.xx] tag per line. Line-level ONLY -- the
          format cannot express word timing, so Syllable data is collapsed.
    elrc  Enhanced LRC (A2): [mm:ss.xx]<mm:ss.xx>syl<mm:ss.xx>syl...
          Preserves per-syllable timing. Degrades to line-level for Line/Static
          entries, which carry no syllable data. Use this for karaoke sync.
    json  raw cache entry, nothing discarded

Usage:
    ./spicy_lyrics.py keys                        # cached track ids (1000s of them)
    ./spicy_lyrics.py get                         # current track, plain text
    ./spicy_lyrics.py get --format elrc           # word-synced (A2)
    ./spicy_lyrics.py get --format lrc            # line-synced
    ./spicy_lyrics.py get <trackid> --format json # raw cache entry
    ./spicy_lyrics.py get --format elrc -o song.lrc
    ./spicy_lyrics.py dump ./lyrics-export        # export the whole cache (elrc)
    ./spicy_lyrics.py dom                         # what's rendered right now
    ./spicy_lyrics.py watch                       # karaoke; overlapping lines and
                                                  #   backing vocals both shown
    ./spicy_lyrics.py watch --offset -0.3         # show lines 300ms earlier
    ./spicy_lyrics.py watch --split long          # also break up held words
    ./spicy_lyrics.py watch --no-karaoke          # plain line-at-a-time
    ./spicy_lyrics.py watch --source dom          # old behaviour: scrape .line.Active
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
from spotify_dom import CDP, connect  # noqa: E402

# WHERE SPICY LYRICS KEEPS WHAT IT HAS FETCHED, as a prefix rather than a
# name. The bucket carries a generation in its own name and the extension
# bumps it: the Marketplace build today opens "SpicyLyrics_LyricsStore_g1",
# and the builds before it opened "SpicyLyrics_LyricsStore" plainly. Pinned
# to one generation this read an empty store on every other build -- and an
# empty store is indistinguishable from Spicy Lyrics having nothing for any
# song, which is what it looked like. Every store whose name starts with this
# is read, newest generation first.
#
# It is a PREFIX everywhere it is passed, and it has to be: caches.open()
# CREATES a store that is not there, so a name guessed wrong does not fail,
# it quietly makes an empty one and reads that.
CACHE_PREFIX = "SpicyLyrics_LyricsStore"
# ...and the IndexedDB the builds before those used, matched by prefix for
# the same reason. Only databases the page actually lists are opened, so a
# miss here cannot conjure one either.
IDB_NAME, IDB_STORE = "spicylyrics", "lyricsStore"

# Resolving both, in front of every snippet below that reads them.
_JS_STORES = """
  const _gen = (n) => { const m = /_g(\\d+)$/.exec(n); return m ? +m[1] : 0; };
  const _stores = async (prefix) => (await caches.keys())
      .filter((n) => n === prefix || n.startsWith(prefix + '_'))
      .sort((a, b) => _gen(b) - _gen(a));
  const _dbs = async (name) => {
    try {
      return (await indexedDB.databases()).map((d) => d.name)
        .filter((n) => n && n.toLowerCase().startsWith(name));
    } catch (e) { return []; }
  };
"""


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
def current_track_id() -> str | None:
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
JS_KEYS = """
(async (cachePrefix, idbName, idbStore) => {
""" + _JS_STORES + """
  const ids = new Set();
  for (const name of await _stores(cachePrefix)) {
    const c = await caches.open(name);
    for (const r of await c.keys()) {
      const seg = r.url.split('/').pop().split('?')[0];
      if (seg) ids.add(seg);
    }
  }
  for (const dbName of await _dbs(idbName)) {
    try {
      const db = await new Promise((res, rej) => {
        const r = indexedDB.open(dbName);
        r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
      });
      if (db.objectStoreNames.contains(idbStore)) {
        const ks = await new Promise((res) => {
          const q = db.transaction(idbStore, 'readonly').objectStore(idbStore).getAllKeys();
          q.onsuccess = () => res(q.result); q.onerror = () => res([]);
        });
        for (const k of ks) ids.add(String(k));
      }
      db.close();
    } catch (e) {}
  }
  return [...ids];
})(%s, %s, %s)
"""

# The same question with nothing but the ids wanted, which is what every tool
# here that walks the whole cache asks. It was six copies of one snippet that
# opened the store by name -- and so six more places that read an empty cache
# on a build whose generation had moved on, and made one each while they were
# at it.
JS_IDS = """
(async (cachePrefix) => {
""" + _JS_STORES + """
  const ids = new Set();
  for (const name of await _stores(cachePrefix)) {
    const c = await caches.open(name);
    for (const r of await c.keys()) {
      const seg = r.url.split('/').pop().split('?')[0];
      if (seg) ids.add(seg);
    }
  }
  return [...ids];
})(%s)
"""

JS_GET = """
(async (cachePrefix, idbName, idbStore, id) => {
""" + _JS_STORES + """
  for (const name of await _stores(cachePrefix)) {
    const c = await caches.open(name);
    // Ask for the one entry before reading every key. Spicy Lyrics stores each
    // song at a URL ending in its track id, and a bare id resolves against the
    // page's own origin to exactly that -- so the store can be indexed rather
    // than walked. The walk stays below for anything stored under a URL this
    // does not reconstruct.
    try {
      const hit = await c.match(id, { ignoreSearch: true });
      if (hit) return { source: 'cache', store: name, body: await hit.json() };
    } catch (e) {}
    for (const r of await c.keys()) {
      if (r.url.split('/').pop().split('?')[0] === id) {
        const resp = await c.match(r);
        if (resp) return { source: 'cache', store: name, body: await resp.json() };
      }
    }
  }
  for (const dbName of await _dbs(idbName)) {
    try {
      const db = await new Promise((res, rej) => {
        const r = indexedDB.open(dbName);
        r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
      });
      if (db.objectStoreNames.contains(idbStore)) {
        const v = await new Promise((res) => {
          const q = db.transaction(idbStore, 'readonly').objectStore(idbStore).get(id);
          q.onsuccess = () => res(q.result); q.onerror = () => res(null);
        });
        db.close();
        if (v) return { source: 'indexeddb', store: dbName, body: v };
      } else db.close();
    } catch (e) {}
  }
  return { source: null, body: null };
})(%s, %s, %s, %s)
"""

JS_DUMP_PAGE = """
(async (cachePrefix, offset, limit) => {
""" + _JS_STORES + """
  // Every generation's store, laid end to end and deduped, so that paging
  // over the lot is still one list with one offset. Newest first, so a song
  // an older store also holds is read from the newest copy of it.
  const seen = new Set(), reqs = [];
  for (const name of await _stores(cachePrefix)) {
    const c = await caches.open(name);
    for (const r of await c.keys()) {
      const id = r.url.split('/').pop().split('?')[0];
      if (id && !seen.has(id)) { seen.add(id); reqs.push([c, r, id]); }
    }
  }
  const out = [];
  for (const [c, r, id] of reqs.slice(offset, offset + limit)) {
    const resp = await c.match(r);
    if (!resp) continue;
    out.push({ id: id, body: await resp.json() });
  }
  return out;
})(%s, %d, %d)
"""

JS_DOM = """
(() => {
  const page = document.querySelector('#SpicyLyricsPage');
  if (!page) return { error: 'no #SpicyLyricsPage -- open the Spicy Lyrics view' };
  const nodes = [...page.querySelectorAll('.line')];
  return {
    rendered: nodes.length,
    note: 'virtualized: rendered window only, not necessarily the whole song',
    lines: nodes.map(el => ({
      text: (el.innerText || '').trim(),
      active: el.classList.contains('Active'),
      sung: el.classList.contains('Sung'),
      background: el.classList.contains('bg-line'),
      pre_hidden: el.classList.contains('pre-hidden'),
      opposite_aligned: el.classList.contains('OppositeAligned'),
      musical: el.classList.contains('musical-line'),
    })),
  };
})()
"""

JS_ACTIVE = """
(() => {
  const el = document.querySelector('#SpicyLyricsPage .line.Active');
  return el ? (el.innerText || '').trim().replace(/\\s+/g, ' ') : null;
})()
"""


def _j(*vals) -> tuple:
    return tuple(json.dumps(v) for v in vals)


# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
_PROPS = None


def player_state() -> tuple[str | None, float, str]:
    """(track_id, position_seconds, status). Position advances 1.0s/s while playing."""
    global _PROPS
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


def syllabify(word: str) -> list[str]:
    """Heuristic English syllable split. Pieces always re-join to the input.

    Punctuation is set aside before the spelling is read and put back after.
    It is not part of any word's sound, and leaving it in defeated the silent
    -e rule below on every word that happened to end a phrase: "Home," came
    back "Ho-me," and "cure?" as "cu-re?", because the test asked whether the
    last CHARACTER was an e.
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

    lead = len(word) - len(word.lstrip("\"'(¿¡[“‘«"))
    head, core = word[:lead], word[lead:]
    tail = ""
    while core and not (core[-1].isalnum() or core[-1] == "'"):
        tail = core[-1] + tail
        core = core[:-1]
    if head or tail:
        if not core:
            return [word]
        pieces = syllabify(core)
        pieces[0] = head + pieces[0]
        pieces[-1] = pieces[-1] + tail
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
# Every script here that a romanisation is FOR. CJK on its own leaves Hangul
# out, and Hangul is the case where a source hands us a perfectly good reading
# and nothing ever draws it: QQ Music files "na eo ddeo kae" against KiiiKiii's
# 나 어떡해 and the gate below threw it away for not being Chinese or Japanese.
SCRIPTED = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿ᄀ-ᇿㄱ-ㆎ가-힣ힰ-ퟻ]")


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
    k = _kakasi()
    if not k or not text:
        return ""
    try:
        return "".join(x["hepburn"] for x in k.convert(text)).strip()
    except Exception:
        return ""


PARTICLES = {"は": "wa", "へ": "e", "を": "o"}


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
        touched = [i for i, (x, y) in enumerate(spans) if x < b and y > a]
        if not touched:
            continue
        for i in touched:
            if owner[i] < 0:
                owner[i] = si
        if len(touched) == 1:
            out[touched[0]] += rom
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
# Han characters are shared; kana are not. This is what tells a Japanese
# lyric from a Chinese one, and pykakasi will read Chinese as Japanese all day
# without ever saying it cannot -- 电吉他 came back furigana'd ていおん・きち.
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
    # Asked of the whole document rather than of a line: a Japanese lyric has
    # lines that are all kanji, and one of those is not a Chinese song.
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
        if not any(y.get("TransliteratedText") for y in syls):
            if not (doc.get("HasTransliterations")
                    and any(SCRIPTED.search(y.get("Text", "") or "") for y in syls)):
                return []
        texts = [y.get("Text", "") or "" for y in syls]
        # pykakasi answers for any Han character put in front of it and never
        # says it could not -- it reads Chinese as Japanese, and Korean not at
        # all. Its readings are only asked for where this document is actually
        # Japanese; everywhere else the source's own romanisation stands, and
        # where the source has none the line is left in its own script rather
        # than given somebody else's language's reading of it.
        derived, owner = line_readings(texts) if japanese else ([""] * len(texts),
                                                                [-1] * len(texts))

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
            if (owner[i] >= 0 and owner[i] == owner[i + 1]
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
        # A "romanisation" still written in the script it was meant to leave is
        # not one -- it is the line again, drawn a second time in the smaller
        # type. That is what a Chinese lyric produces here: nothing installed
        # reads Han characters into pinyin, so where the source carries no
        # reading of its own there is genuinely nothing to show, and showing
        # the line twice is worse than showing it once.
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
        if not foreign(raw):
            return ""
        for src in (group, item):
            if isinstance(src, dict) and isinstance(src.get("TransliteratedText"), str):
                got = src["TransliteratedText"]
                return "" if SCRIPTED.search(got or "") else got
        return " ".join(
            y[2] for y in roman_of(group) if y[2]
        ).strip()

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

    out = []
    for group, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        lead = item.get("Lead") if isinstance(item.get("Lead"), dict) else None
        end = (lead or item).get("EndTime")
        here = len(out)
        out.append(
            {
                "start": line_start(item),
                "end": float(end) if isinstance(end, (int, float)) else None,
                "text": line_text(item),
                "syls": syls_of(lead),
                "syls_roman": roman_of(lead),
                "text_roman": roman_text(lead, item),
                "opposite": bool(item.get("OppositeAligned")),
                "background": False,
                # The line this one belongs to. An ad-lib is written as part of
                # its line and is drawn hanging off it, so the two have to stay
                # findable from each other after the list is flattened and a
                # backing group that starts early is moved ahead of its lead.
                "group": group,
                # When the singing stops, as opposed to when the line ends.
                "sung": last_sung(lead),
            }
        )
        bg = item.get("Background")
        lead_syls = [y.get("StartTime") for y in (lead or {}).get("Syllables") or []
                     if isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float))]
        lead_start = min(lead_syls) if lead_syls else out[here]["start"]
        for g in bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else []):
            if not isinstance(g, dict):
                continue
            gs, ge = g.get("StartTime"), g.get("EndTime")
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
                    "start": float(gs) if isinstance(gs, (int, float)) else None,
                    "end": float(ge) if isinstance(ge, (int, float)) else None,
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


def active_indices(lines: list[dict], pos: float) -> list[int]:
    """Every line covering pos. Lines overlap (duets, backing vocals), so more
    than one can be live at once -- returning only the newest dropped the other."""
    live = [
        i
        for i, ln in enumerate(lines)
        if ln["start"] is not None
        and ln["start"] <= pos
        and (ln["end"] is None or pos <= ln["end"])
    ]
    return live


def _sung_to(ln: dict):
    """When this line stops being sung, which is not always when it ends.

    A line's end is stretched over the ad-libs written inside it wherever the
    source felt like it -- every line in Stronger ends a second after the line
    AFTER it has started, because that is when its backing vocal stops. Where
    the syllables say otherwise they are believed: they are the words.
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
        # An interlude marker: breathing dots over an instrumental gap, with
        # nothing in it to sing. It is never mid-word, so it never has a claim
        # on the view -- without this the marker's end IS the next line's
        # start, and a scroll-ahead into a line that follows a gap could not
        # begin until the moment it was too late to be ahead of anything.
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
        # A document of nothing but ad-libs: there is no line to read on to,
        # so the newest thing that has started is as good as it gets.
        started = [i for i, ln in enumerate(lines)
                   if ln.get("start") is not None and ln["start"] <= pos]
        return started[-1] if started else (0 if lines else -1)
    # When each line's ad-libs first open their mouths. Taken as "has begun"
    # rather than "is sounding now": a two-word ad-lib can be over before the
    # line it announces starts, and a view that followed it there and came
    # back would have scrolled twice to arrive where it already was.
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
    """Unwrap the cache envelope to the lyrics document."""
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

# What a song is, as amll-ttml-db files it -- the only convention here that has
# anywhere to put a title. Apple's <head> names the writers and nothing else,
# so a document saved out of the editor with a title and an artist typed into
# its Song info box came back from disk anonymous, and the "that file holds a
# different song" guard had nothing left to compare.
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
    # The lead's stamps where it has them, the line's where it has not: a
    # group whose syllables are still untimed carries no stamps of its own,
    # and reading the pair off it alone unstamped every line-timed <p> in a
    # document that had any word timing at all.
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
            f"no lines in cache entry (Type={doc.get('Type')!r}, keys={sorted(doc)})"
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
        # A Lead holding no syllables is not a lead -- it is a line-timed line
        # wearing the word-timed shape, which every mixed document has some of.
        # Written out of its own (empty) spans the words went with them: 13 of
        # the 62 lines of NF's "Time" came back out of a save as empty <p>s.
        inner = _spans(lead) if _worth_spans(lead) else escape(line_text(item))
        for g in bg:
            inside = (_spans(g) if g.get("Syllables")
                      else escape(_trim(str(g.get("Text") or ""))))
            piece = f'<span ttm:role="x-bg"{_tattrs(g)}>{inside}</span>'
            # An untimed ad-lib that opens its line is written where it
            # sounds, because nothing else in the file can say so: a timed one
            # is placed by its stamps whichever end it is written at, and one
            # with no stamps has only its position left. Written after the
            # lead like the rest, "(Promise I like it like—) Promise I like it
            # like that" came back as an answer instead of a call.
            if g.get("LeadIn") and not isinstance(g.get("StartTime"), (int, float)):
                inner = piece + inner
            else:
                inner += piece
        rows.append(f"<p{times}{attrs}>{inner}</p>")

    lang = doc.get("LanguageISO2") or doc.get("Language")
    # Checked against the words before it is written. Providers guess this
    # from a few hundred words and the guess goes wrong the same way every
    # time -- an English lyric filed under a small Latin-script language.
    # Music Baby ships as `pcm`, Creep as `sco`. It picks the hyphenation a
    # word is cut with and it is what a reader is told the song is, so a
    # wrong one is not cosmetic.
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
    # A credit is a name, not a lyric, and one of them arrived with a
    # zero-width space in front of it -- which is invisible in the tag and
    # not invisible at all to anything matching the name.
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
            f"no lines in cache entry (Type={doc.get('Type')!r}, "
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
def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--target")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("keys", help="list cached track ids")
    sub.add_parser("dom", help="scrape the rendered lyrics DOM")

    g = sub.add_parser("get", help="cached lyrics for a track")
    g.add_argument("track", nargs="?", help="track id (default: currently playing)")
    g.add_argument("--format", choices=["text", "lrc", "elrc", "ttml", "json"], default="text")
    g.add_argument("--background", action="store_true", help="include backing vocals")
    g.add_argument("-o", "--out", help="write to file instead of stdout")

    d = sub.add_parser("dump", help="export the entire cache, one file per track")
    d.add_argument("outdir")
    d.add_argument("--format", choices=["text", "lrc", "elrc", "ttml", "json"], default="elrc")
    d.add_argument("--background", action="store_true")
    d.add_argument("--batch", type=int, default=100, help="entries per CDP round-trip")

    w = sub.add_parser("watch", help="follow lyrics live against playback position")
    w.add_argument("--interval", type=float, default=0.15)
    w.add_argument("--source", choices=["sync", "dom"], default="sync",
                   help="sync: cached lyrics + MPRIS clock (default). dom: scrape .line.Active")
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
    cdp = connect(a.port, a.target)
    try:
        if a.cmd == "keys":
            for k in sorted(cdp.evaluate(JS_KEYS % _j(CACHE_PREFIX, IDB_NAME, IDB_STORE)) or []):
                print(k)

        elif a.cmd == "dom":
            print(json.dumps(cdp.evaluate(JS_DOM), indent=2, ensure_ascii=False))

        elif a.cmd == "get":
            track = a.track or current_track_id()
            if not track:
                sys.exit("No track id given and MPRIS lookup failed. Try: spicy_lyrics.py keys")
            res = cdp.evaluate(JS_GET % _j(CACHE_PREFIX, IDB_NAME, IDB_STORE, track)) or {}
            if not res.get("body"):
                sys.exit(
                    f"No cached lyrics for {track}. Play it once with the Spicy Lyrics "
                    f"view open, then retry."
                )
            try:
                text = render(res["body"], a.format, a.background)
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
                batch = cdp.evaluate(JS_DUMP_PAGE % (json.dumps(CACHE_PREFIX), offset, a.batch))
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

        elif a.cmd == "watch" and a.source == "dom":
            last = object()
            while True:
                cur = cdp.evaluate(JS_ACTIVE)
                if cur != last:
                    if cur:
                        print(cur, flush=True)
                    last = cur
                time.sleep(a.interval)

        elif a.cmd == "watch":
            color = sys.stdout.isatty() and not a.no_color and not os.environ.get("NO_COLOR")
            track, lines, unsynced = None, [], False
            region, printed, started, retry_at = [], set(), False, 0.0

            def load(tid):
                res = cdp.evaluate(JS_GET % _j(CACHE_PREFIX, IDB_NAME, IDB_STORE, tid)) or {}
                if not res.get("body"):
                    return []
                return timeline(res["body"], split=a.split, threshold=a.split_threshold)

            while True:
                tid, pos, status = player_state()
                pos -= a.offset

                if tid != track:
                    track, unsynced, lines = tid, False, []
                    region, printed = [], set()
                    if tid:
                        lines = load(tid)
                        head = f"--- {tid} "
                        if not lines:
                            head += "(not cached yet -- waiting)"
                            retry_at = time.monotonic() + 2.0
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
                    retry_at = time.monotonic() + 2.0
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
                        for k, i in enumerate(region):
                            ln = lines[i]
                            buf += "\r\033[K" + decorate(ln, karaoke(ln, pos, color))
                            if k < len(region) - 1:
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
        cdp.close()


if __name__ == "__main__":
    main()
