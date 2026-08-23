#!/usr/bin/env python3
"""
Pull lyrics out of the Spicy Lyrics Spicetify extension in the running Spotify app.

Sources, in order of preference:

  1. Cache Storage -- the current Marketplace build caches every fetched song in
     the Cache Storage bucket "SpicyLyrics_LyricsStore_g1", keyed by track id.
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
import math
import os
import pathlib
import re
import sys
import time
import unicodedata
from xml.sax.saxutils import escape, quoteattr

_HERE = pathlib.Path(__file__).resolve().parent
# spotify_dom.py may sit next to this file or one level up -- offer both, or the
# import below fails depending on where the scripts were dropped.
sys.path[:0] = [str(p) for p in (_HERE, _HERE.parent) if str(p) not in sys.path]
from spotify_dom import CDP, connect  # noqa: E402

CACHE_NAME = "SpicyLyrics_LyricsStore_g1"
IDB_NAME, IDB_STORE = "spicylyrics", "lyricsStore"


# --------------------------------------------------------------------------
# current track id, straight off D-Bus (no CDP needed)
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
# JS payloads
# --------------------------------------------------------------------------
JS_KEYS = """
(async (cacheName, idbName, idbStore) => {
  const ids = new Set();
  if ((await caches.keys()).includes(cacheName)) {
    const c = await caches.open(cacheName);
    for (const r of await c.keys()) {
      const seg = r.url.split('/').pop().split('?')[0];
      if (seg) ids.add(seg);
    }
  }
  try {
    const dbs = (await indexedDB.databases()).map(d => d.name);
    if (dbs.includes(idbName)) {
      const db = await new Promise((res, rej) => {
        const r = indexedDB.open(idbName);
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
    }
  } catch (e) {}
  return [...ids];
})(%s, %s, %s)
"""

JS_GET = """
(async (cacheName, idbName, idbStore, id) => {
  if ((await caches.keys()).includes(cacheName)) {
    const c = await caches.open(cacheName);
    // Ask for the one entry before reading every key. Spicy Lyrics stores each
    // song at a URL ending in its track id, and a bare id resolves against the
    // page's own origin to exactly that -- so the store can be indexed rather
    // than walked. The walk stays below for anything stored under a URL this
    // does not reconstruct.
    try {
      const hit = await c.match(id, { ignoreSearch: true });
      if (hit) return { source: 'cache', body: await hit.json() };
    } catch (e) {}
    for (const r of await c.keys()) {
      if (r.url.split('/').pop().split('?')[0] === id) {
        const resp = await c.match(r);
        if (resp) return { source: 'cache', body: await resp.json() };
      }
    }
  }
  try {
    const db = await new Promise((res, rej) => {
      const r = indexedDB.open(idbName);
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
    if (db.objectStoreNames.contains(idbStore)) {
      const v = await new Promise((res) => {
        const q = db.transaction(idbStore, 'readonly').objectStore(idbStore).get(id);
        q.onsuccess = () => res(q.result); q.onerror = () => res(null);
      });
      db.close();
      if (v) return { source: 'indexeddb', body: v };
    } else db.close();
  } catch (e) {}
  return { source: null, body: null };
})(%s, %s, %s, %s)
"""

JS_DUMP_PAGE = """
(async (cacheName, offset, limit) => {
  const c = await caches.open(cacheName);
  const reqs = (await c.keys()).slice(offset, offset + limit);
  const out = [];
  for (const r of reqs) {
    const resp = await c.match(r);
    if (!resp) continue;
    out.push({ id: r.url.split('/').pop().split('?')[0], body: await resp.json() });
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
# player clock (D-Bus, no CDP round-trips)
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
# Written boundaries: a hyphen, a non-breaking hyphen, an en dash.
HYPHENS = "-\u2011\u2013"
# Only true digraphs -- one sound, never split. Ordinary onset clusters (st, tr,
# bl...) must stay splittable or VCCV words break: ques-tion, not que-stion.
DIGRAPHS = ("th", "ch", "sh", "ph", "wh", "gh", "ck", "qu")


def syllabify(word: str) -> list[str]:
    """Heuristic English syllable split. Pieces always re-join to the input.

    Punctuation is set aside before the spelling is read and put back after.
    It is not part of any word's sound, and leaving it in defeated the silent
    -e rule below on every word that happened to end a phrase: "Home," came
    back "Ho-me," and "cure?" as "cu-re?", because the test asked whether the
    last CHARACTER was an e.
    """
    # A hyphen already IS a syllable boundary -- somebody wrote it there --
    # and it belongs to the piece before it: "Ten-time" is sung "Ten-" then
    # "time", never "Ten" then "-time". Split on it first and syllabify each
    # part on its own, so the rule below never has to reason about a word with
    # two halves in it.
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
                # the chunk was a bare hyphen; it rides on whatever is there
                if pieces:
                    pieces[-1] += mark
                else:
                    pieces.append(mark)
                continue
            got[-1] += mark
            pieces.extend(got)
        # ...and a leading bare hyphen has nothing before it to ride on
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
    # word-final consonant + "le" is a syllable of its own (lit-tle, im-pos-si-ble)
    final_le = (
        n >= 4 and lw.endswith("le") and lw[-3] not in VOWELS and lw[-3].isalpha()
    )
    # otherwise a trailing silent 'e' is not its own syllable -- and it stays
    # silent with an inflection stuck on it: saved, named, missed, Tides.
    # Those came back "sa-ved", "na-med", "mis-sed", "Ti-des", which is a
    # second syllable nobody sings.
    #
    # It is only silent where English actually swallows it. After t or d the
    # -ed IS a syllable (wan-ted, nee-ded), and after a sibilant so is the -es
    # (wish-es, ra-ces, pa-ges) -- hence the two exception sets.
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
        # Count the consonants between two vowels in UNITS, where a digraph
        # is one unit -- "ch" is a single sound and cannot be cut through.
        #
        # Doing it this way, rather than counting letters and then shoving the
        # cut off a digraph, is what tells "tea-cher" from "wach-ten". Both
        # contain "ch"; in the first it is the entire cluster, so it opens the
        # next syllable, and in the second a "t" follows it, so the "ch" closes
        # this one. The old code moved the cut LEFT whenever it landed inside a
        # digraph, which gave "wa-chten" -- an onset no language has.
        units, at = [], end_v + 1
        while at < start_next:
            step = 2 if (lw[at:at + 2] in DIGRAPHS and at + 2 <= start_next) else 1
            units.append(at)
            at += step
        if not units:
            cut = start_next
        elif len(units) == 1:
            cut = units[0]        # one consonant: it opens the next syllable
        else:
            cut = units[len(units) // 2]
        if cut > (cuts[-1] if cuts else 0):
            cuts.append(cut)
    if final_le:
        # the last syllable is consonant + "le", so cut before that consonant
        cuts = [c for c in cuts if c < n - 3] + [n - 3]
    pieces, prev = [], 0
    for c in cuts:
        if c > prev:
            pieces.append(word[prev:c])
            prev = c
    pieces.append(word[prev:])
    # a piece with no vowel is not a syllable -- fold it into its neighbour
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


                                  # kana, radicals/compat forms, ext-A, unified
CJK = re.compile(r"[぀-ヿ⺀-⿟㐀-䶿一-鿿]")


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
SOKUON = re.compile(r"[っッ]\s*$")      # small tsu, っ / ッ
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


# Standalone particles are written one way and read another. Romanising them
# per-character gives "watashi ha" / "kimi wo", which is simply wrong.
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


# kana that never begin a mora: they lean on the character before them
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
    owner = [-1] * len(texts)          # which romanizer word each syllable fell in
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
        # a syllable that is nothing but は/へ/を is the particle, not the kana
        if stripped in PARTICLES and (i or stripped != "は"):
            out[i] = PARTICLES[stripped]
    return out, owner


KANJI = re.compile(r"[㐀-䶿一-鿿]")


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
        # A reading can straddle two timed pieces, since the syllable split and
        # the word split are different things. Divide it by character share
        # rather than dropping it or hanging it off one side.
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
        return None            # gemination before a vowel is not a thing
    dbl = "t" if head[:2].lower() == "ch" else head[0].lower()
    if head[:2].lower() == dbl * 2:
        head = head[1:]        # already doubled on the far side
    if base[-1:].lower() != dbl:
        base += dbl
    return base, head


# How far ahead of its line a backing vocal must start before it is read as
# leading the line rather than opening with it.
#
# Not any amount: a backing vocal sung WITH the line is routinely stamped a
# hair early. On "No More Sorrow" the ad-libs lead by 0.01-0.02s, which is
# jitter, and lifting those above the line they answer just scattered it. The
# same track's genuine early entries lead by ~3.3s, so there is a lot of room
# between the two. Of the 416 early backing vocals in a 2323-song library, 288
# clear this and 128 are the near-simultaneous kind.
BG_LEAD = 0.4


def timeline(body, split: str = "none", threshold: float = 0.7) -> list[dict]:
    """Cache entry -> [{start, end, text, syls:[(start,end,text)]}] sorted by start."""
    doc = payload(body)
    items = next(
        (doc[k] for k in ("Content", "Lines") if isinstance(doc.get(k), list) and doc[k]), []
    )
    def syls_of(group, key="Text"):
        s = []
        for y in (group or {}).get("Syllables") or []:
            if isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float)):
                s.append(
                    (
                        float(y["StartTime"]),
                        float(y.get("EndTime", y["StartTime"])),
                        # some syllables carry an empty romanisation; showing the
                        # original there beats rendering a hole in the line
                        #
                        # Trimmed at the edges: the layout puts its own gap
                        # between two pieces that are not part of one word, so
                        # a piece carrying a trailing space of its own is drawn
                        # with two. See syllables_text.
                        _trim(y.get(key) or y.get("Text", "")),
                        bool(y.get("IsPartOfWord")),
                    )
                )
        if key != "Text":
            # A romanisation is already one token per sung syllable; re-splitting
            # it would interpolate boundaries inside "sayonara" for no gain.
            return s
        return split_syllables(s, split, threshold) if s and split != "none" else s

    def roman_of(group):
        """Per-syllable romanisation, when the source carries one. Same timings
        as the original, so it can be filled in sync with it."""
        # must use the SAME filter syls_of does, or the zip below pairs each
        # romanisation with the wrong original
        syls = [y for y in (group or {}).get("Syllables") or []
                if isinstance(y, dict) and isinstance(y.get("StartTime"), (int, float))]
        # A line with no CJK in it is already readable, so it gets no second
        # row -- some sources hand back a "transliteration" for the English
        # lines of a mixed song that is just the English again.
        if not any(CJK.search(y.get("Text", "") or "") for y in syls):
            return []
        # Some tracks flag transliterations at the top but leave whole lines
        # without one. Derive those rather than showing a blank under every
        # other romanised line.
        if not any(y.get("TransliteratedText") for y in syls):
            if not (doc.get("HasTransliterations")
                    and any(CJK.search(y.get("Text", "") or "") for y in syls)):
                return []
        # derived readings come from the whole line at once, for the context
        texts = [y.get("Text", "") or "" for y in syls]
        derived, owner = line_readings(texts)

        def failed(y):
            """The source gave nothing usable for this syllable."""
            r = (y.get("TransliteratedText") or "").strip()
            return not r or bool(CJK.search(r))

        # If any syllable of a word needs deriving, derive the whole word. Mixing
        # a derived "shi" for 沈 with the source's "mu" for む spells "shi mu";
        # taking both halves of the derived reading spells "shizumu".
        broken = {owner[i] for i, y in enumerate(syls) if failed(y) and owner[i] >= 0}
        rows = []
        for i, ((s, e, _t, _p), y) in enumerate(zip(syls_of(group, "TransliteratedText"), syls)):
            rom = (y.get("TransliteratedText") or "").strip()
            # The source is kept wherever it holds up -- it is community-curated
            # and handles the invented readings lyrics are full of, which nothing
            # can infer from the text.
            if failed(y) or owner[i] in broken:
                rom = (derived[i] or "").strip() or rom or canon(texts[i])
            rows.append([s, e, rom, False])
        # Syllables that fall inside one romanizer word are one word on screen:
        # "shizu" + "mu" reads as "shizumu", and 諦めの悪い輩 reads "taime no
        # warui tomogara" rather than "tai me no waru i tomogara".
        #
        # It takes BOTH signals to agree. The romanizer alone lumps a whole kana
        # run into one segment, which glued "sayonara dake datta" into a blob;
        # IsPartOfWord alone is Japanese orthography, which happily runs a
        # entire phrase together because the script has no spaces. Where the
        # word segmentation and the source's own word flag say the same thing,
        # the join is safe.
        for i in range(len(rows) - 1):
            if (owner[i] >= 0 and owner[i] == owner[i + 1]
                    and syls[i].get("IsPartOfWord")):
                rows[i][3] = True
        # っ geminates onto the next syllable, so those two do join
        for i in range(len(rows) - 1):
            if SOKUON.search(syls[i].get("Text", "") or ""):
                joined = geminate(rows[i][2], rows[i + 1][2])
                if joined:
                    rows[i][2], rows[i + 1][2] = joined
                    rows[i][3] = True
        # Note every token is spaced (part=False) except those joins: IsPartOfWord
        # encodes Japanese orthography, which is right for かな but would glue the
        # romanisation into "sayonaradakedatsuta".
        return [tuple(r) for r in rows]

    def roman_text(group, item=None):
        for src in (group, item):
            if isinstance(src, dict) and isinstance(src.get("TransliteratedText"), str):
                return src["TransliteratedText"]
        return " ".join(
            y[2] for y in roman_of(group) if y[2]
        ).strip()

    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lead = item.get("Lead") if isinstance(item.get("Lead"), dict) else None
        end = (lead or item).get("EndTime")
        here = len(out)               # where this line's own row begins
        out.append(
            {
                "start": line_start(item),
                "end": float(end) if isinstance(end, (int, float)) else None,
                "text": line_text(item),
                "syls": syls_of(lead),
                "syls_roman": roman_of(lead),
                # line-level lyrics carry the romanisation on the item, not on a
                # Lead group -- passing `lead` twice never looked there
                "text_roman": roman_text(lead, item),
                "opposite": bool(item.get("OppositeAligned")),
                "background": False,
            }
        )
        # Backing vocals are a concurrent voice with their own timings, not part
        # of the lead line -- emit them as separate entries so they overlap it.
        bg = item.get("Background")
        # When the lead is actually SUNG, not when its group nominally opens.
        # Lead.StartTime is padded ahead of the first syllable, and comparing
        # against it found no early ad-libs at all in the whole cache -- while
        # 416 backing vocals do come in before the lead's first syllable, which
        # is the moment a listener hears the line begin.
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
            # An ad-lib that comes in BEFORE the line it belongs to should be
            # read before it, not under it. Anything starting at or after the
            # lead stays below, which is the common case (an answering vocal).
            at = len(out)
            if (isinstance(gs, (int, float)) and lead_start is not None
                    and float(gs) < lead_start - BG_LEAD):
                at = here
                here += 1              # the lead has moved down a row
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
                }
            )
    synced = [ln for ln in out if ln["start"] is not None]
    if not synced:
        return out
    # Deliberately NOT sorted by start. The source lists lines in reading order,
    # and sorting broke that wherever two voices overlap: a backing vocal whose
    # own StartTime falls after the NEXT lead line's got lifted away from the
    # line it answers and dropped a row lower ("critics I turn to" / "Crickets"
    # landing under the following line), and an ad-lib that comes in a beat
    # before the lead it sits under jumped above it. Across the whole local
    # cache that hit 64 of 1988 songs; only one had source order genuinely
    # wrong, and that one has stale timestamps no ordering can rescue.
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


def _span(ln: dict) -> tuple[float, float]:
    s = ln["start"]
    return (s if s is not None else math.inf,
            ln["end"] if ln["end"] is not None else math.inf)


def _covers(outer: dict, inner: dict) -> bool:
    """Does outer's span wholly contain inner's?"""
    os_, oe = _span(outer)
    is_, ie = _span(inner)
    return os_ <= is_ and ie <= oe


def focus_index(lines: list[dict], live) -> int:
    """Of the sounding lines, the one the view should sit on.

    Newest wins, so overlapping lines scroll as they arrive -- but a line that
    starts AND ends inside an older sounding one is an interjection (backing
    vocal, a nested second voice), not the next thing to read. Those hand the
    focus back to the line that contains them, so the view holds still and only
    moves when a line arrives that outlives its neighbour.

        1: 2:00-2:10  2: 2:02-2:04  3: 2:09-2:12
            line 3 outlasts line 1, so 2:09 scrolls down to it.

        1: 2:00-2:08  2: 2:02-2:04  3: 2:09-2:12
            line 2 is nested, so the view stays on line 1 until 2:09.
    """
    live = sorted(live)
    if not live:
        return -1
    cur = live[-1]
    moved = True
    while moved:                      # walk out to the outermost container
        moved = False
        for j in live:
            if j < cur and _covers(lines[j], lines[cur]):
                cur, moved = j, True
                break
    return cur


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
                return idx  # still in the gap after this line
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
# formatting
# --------------------------------------------------------------------------
def payload(body):
    """Unwrap the cache envelope to the lyrics document."""
    if isinstance(body, dict) and isinstance(body.get("Content"), dict):
        return body["Content"]
    return body if isinstance(body, dict) else {}


ZWSP = "\u200b"


def _trim(text) -> str:
    """A syllable's text, without the whitespace or the invisible characters.

    Zero-width spaces come in with some sources and are drawn as nothing --
    but they still take up a place in the string, so they defeat a word match
    and travel into anything copied out of here. Where one stood between two
    letters it was doing the job of a space, and a space takes its place.
    """
    got = str(text or "")
    if ZWSP in got:
        got = re.sub(r"(?<=[^\s" + ZWSP + r"])" + ZWSP
                     + r"(?=[^\s" + ZWSP + r"])", " ", got)
        got = got.replace(ZWSP, "")
    return got.strip() or got


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
        # Both edges: a leading space doubles the gap just as a trailing one
        # does, and the piece before it has already ended its word.
        out += text if s.get("IsPartOfWord") else _trim(text) + " "
    return out.strip()


def line_text(item, background: bool = False) -> str:
    if not isinstance(item, dict):
        return str(item or "")
    text = item.get("Text")
    if not isinstance(text, str):
        lead = item.get("Lead")
        text = syllables_text(lead.get("Syllables") if isinstance(lead, dict) else None)
    if background:
        bg = item.get("Background")
        parts = []
        for b in bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else []):
            t = b.get("Text") if isinstance(b.get("Text"), str) else syllables_text(
                b.get("Syllables")
            )
            if t:
                parts.append(t)
        if parts:
            # One pair of brackets per GROUP, not one pair around all of them.
            # Two answering voices written apart -- "(Baow) (What the fuck are
            # you doing, Toxi?)" -- came back as "(Baow What the fuck are you
            # doing, Toxi?)", which is every word in the wrong shape and reads
            # as one long ad-lib rather than two short ones.
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
    out = []
    for s in (group or {}).get("Syllables") or []:
        if not isinstance(s, dict):
            continue
        start = s.get("StartTime")
        tag = ts(float(start), "<>") if isinstance(start, (int, float)) else ""
        # IsPartOfWord means "joins the next syllable with no space"
        out.append(tag + s.get("Text", "") + ("" if s.get("IsPartOfWord") else " "))
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
        body = line_text(item)  # Line/Static types carry no syllable data
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
    src = lead or item
    b, e = (src or {}).get("StartTime"), (src or {}).get("EndTime")
    if not background:
        return {"StartTime": b, "EndTime": e}
    # What the line sings on its own, before any ad-lib widens it. The clamp
    # below may not cut into this.
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
    # ...but not so far that two lines are lit at once.
    #
    # Widening a line to hold its ad-libs and stopping there traded one visible
    # fault for another: containment went perfect and a quarter of the lines
    # began overlapping the next, which is the fault a reader actually notices.
    # So the line reaches as far as it must and no further than the next line's
    # start. What is being cut is an ad-lib's END, which was mostly the hold
    # rather than a measurement -- and a line that has to be truncated here is
    # really telling you its ad-lib is mistimed, which is a different bug.
    #
    # ONLY the ad-lib's end. That is what this always said it did, and not
    # what it did: `e` is the widened end, and where nothing had widened it,
    # the line's own singing was cut instead. A duet answering before the
    # other singer has finished -- two voices overlapping on purpose, which
    # is the whole point of two agents -- came out of a save with its <p>
    # ending where the answer began, and the rest of the line outside the
    # element that carries it. Hence `own`: the clamp may take back the hold
    # an ad-lib added and no more.
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
    """Syllables -> <span> run, spaced per IsPartOfWord."""
    syls = [s for s in (group or {}).get("Syllables") or [] if isinstance(s, dict)]
    parts = []
    for i, s in enumerate(syls):
        parts.append(f"<span{_tattrs(s)}>{escape(s.get('Text', ''))}</span>")
        if i < len(syls) - 1 and not s.get("IsPartOfWord"):
            parts.append(" ")
    return "".join(parts)


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
        if timing == "None":
            rows.append(f"<p{attrs}>{escape(line_text(item))}</p>")
            continue
        lead = item.get("Lead") if isinstance(item.get("Lead"), dict) else None
        nxt = items[n] if n < len(items) else None       # n is 1-based
        nlead = (nxt or {}).get("Lead") if isinstance(nxt, dict) else None
        until = (nlead or nxt or {}).get("StartTime") if isinstance(nxt, dict) else None
        times = _tattrs(_covering(item, lead,
                                  bool(background) and timing == "Word", until))
        if timing == "Word" and lead:
            inner = _spans(lead)
            if background:
                bg = item.get("Background")
                for g in bg if isinstance(bg, list) else ([bg] if isinstance(bg, dict) else []):
                    if isinstance(g, dict) and g.get("Syllables"):
                        inner += f'<span ttm:role="x-bg"{_tattrs(g)}>{_spans(g)}</span>'
        else:
            inner = escape(line_text(item))
        rows.append(f"<p{times}{attrs}>{inner}</p>")

    lang = doc.get("LanguageISO2") or doc.get("Language")
    root = " ".join(f'{k}="{v}"' for k, v in TTML_NS.items())
    root += f' itunes:timing="{timing}"'
    if lang:
        root += f" xml:lang={quoteattr(str(lang))}"

    agents = '<ttm:agent type="person" xml:id="v1"/>'
    if dual:
        agents += '<ttm:agent type="person" xml:id="v2"/>'
    writers = "".join(
        f"<songwriter>{escape(str(w))}</songwriter>" for w in doc.get("SongWriters") or []
    )
    meta = f'<iTunesMetadata xmlns="{ITUNES_NS}">'
    meta += f"<songwriters>{writers}</songwriters>" if writers else ""
    meta += "</iTunesMetadata>"

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
        # x-bg is how TTML natively carries backing vocals -- always emit them,
        # unlike the text/lrc formats where they are an opt-in inline annotation.
        return render_ttml(body, True)
    doc = payload(body)
    # synced types (Syllable/Line) use "Content"; unsynced "Static" uses "Lines"
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
            for k in sorted(cdp.evaluate(JS_KEYS % _j(CACHE_NAME, IDB_NAME, IDB_STORE)) or []):
                print(k)

        elif a.cmd == "dom":
            print(json.dumps(cdp.evaluate(JS_DOM), indent=2, ensure_ascii=False))

        elif a.cmd == "get":
            track = a.track or current_track_id()
            if not track:
                sys.exit("No track id given and MPRIS lookup failed. Try: spicy_lyrics.py keys")
            res = cdp.evaluate(JS_GET % _j(CACHE_NAME, IDB_NAME, IDB_STORE, track)) or {}
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
                batch = cdp.evaluate(JS_DUMP_PAGE % (json.dumps(CACHE_NAME), offset, a.batch))
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
                res = cdp.evaluate(JS_GET % _j(CACHE_NAME, IDB_NAME, IDB_STORE, tid)) or {}
                if not res.get("body"):
                    return []
                return timeline(res["body"], split=a.split, threshold=a.split_threshold)

            while True:
                tid, pos, status = player_state()
                pos -= a.offset  # positive offset shows lines later

                if tid != track:
                    track, unsynced, lines = tid, False, []
                    region, printed = [], set()
                    if tid:
                        lines = load(tid)
                        head = f"--- {tid} "
                        if not lines:
                            # Spicy Lyrics writes the cache only after it fetches a
                            # song, so a just-started track is often not there yet.
                            # Keep re-checking instead of going silent for the song.
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
                    # live region = every currently-sounding line, redrawn in place.
                    # Lines that stop sounding drop out of the region and stay on
                    # screen above it as history.
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
